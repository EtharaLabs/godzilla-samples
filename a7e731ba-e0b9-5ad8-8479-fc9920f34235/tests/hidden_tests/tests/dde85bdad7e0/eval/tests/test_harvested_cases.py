"""CLI transcripts harvested from the project's own `.case` files.

Each resource pair holds the invocation (`<name>.json`: argv, stdin, extra files
written into the working directory, and the working subdirectory) and the
reference binary's complete result (`<name>.golden`: stdout, stderr, exit
status). Every transcript is replayed against the binary under test and the
whole result is compared exactly.
"""

import base64
import json

import pytest

from conftest import resources_for

RESOURCES = resources_for(__file__)
CASES = sorted(path.stem for path in RESOURCES.glob("*.json"))


@pytest.mark.parametrize("name", CASES)
def test_transcript(name, run, workdir):
    """CATCHES: any regression in YAML/Markdown/source-language formatting, JSON-family
    projection, config discovery, diff/check summaries or error diagnostics, because
    the exact stdout, stderr and exit status of each recorded invocation must match."""
    manifest = json.loads((RESOURCES / f"{name}.json").read_text())
    expected = json.loads((RESOURCES / f"{name}.golden").read_text())
    for relative, data in manifest["files"].items():
        target = workdir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(data))
    cwd = workdir / manifest["cwd"]
    result = run(manifest["args"], input=manifest["stdin"], cwd=cwd)
    actual = {
        "stdout": result.stdout.decode(),
        "stderr": result.stderr.decode(),
        "status": result.returncode,
    }
    if "check_args" in manifest:
        # Output equals input: confirm path mode agrees that the file is
        # already formatted (summary on stderr, status 0, bytes untouched).
        target = cwd / manifest["check_args"][-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(manifest["stdin"])
        check = run(manifest["check_args"], cwd=cwd)
        actual["check"] = {
            "stdout": check.stdout.decode(),
            "stderr": check.stderr.decode(),
            "status": check.returncode,
            "file": target.read_bytes().decode(),
        }
    assert actual == expected
