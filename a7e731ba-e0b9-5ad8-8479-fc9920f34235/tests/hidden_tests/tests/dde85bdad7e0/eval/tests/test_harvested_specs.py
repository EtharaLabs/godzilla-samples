"""CLI invocations harvested from the project's Rust CLI specification suite.

Each `<name>.json` resource records one invocation: argv, stdin (base64), the
working subdirectory, files and symlinks to create first (fake formatter
scripts, configs, inputs), directories to prepend to PATH, and which files are
executable (large stdin payloads are stored zlib-compressed, flagged by `stdin_zlib`).
`<name>.golden` holds the reference binary's stdout, stderr, exit
status and the exact contents of every file the run created or modified.

PATH is restricted to the test's own tool directory so optional formatters such
as ruff, air, or prettier are absent unless the invocation supplies a fake one.
"""

import base64
import json
import os
import zlib

import pytest

from conftest import normalize_trace, resources_for

RESOURCES = resources_for(__file__)
CASES = sorted(path.stem for path in RESOURCES.glob("*.json"))


def _materialize(workdir, manifest):
    originals = {}
    for relative, data in manifest["files"].items():
        target = workdir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(data)
        target.write_bytes(raw)
        originals[relative] = raw
    for relative, link_target in manifest.get("symlinks", {}).items():
        link = workdir / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(link_target)
    for relative in manifest.get("executable", []):
        os.chmod(workdir / relative, 0o755)
    return originals


def _changed_files(workdir, originals):
    changed = {}
    for path in sorted(workdir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = str(path.relative_to(workdir))
        data = path.read_bytes()
        if originals.get(relative) != data:
            changed[relative] = data.decode()
    for relative in originals:
        if not (workdir / relative).exists():
            changed[relative] = "<<deleted>>"
    return changed


@pytest.mark.parametrize("name", CASES)
def test_spec_invocation(name, run, workdir, tool_bin):
    """CATCHES: formatting, preservation, directive, config, workspace traversal,
    diff/check and external-formatter regressions, since stdout, stderr, exit status
    and every byte the run writes to disk must equal the reference binary's."""
    manifest = json.loads((RESOURCES / f"{name}.json").read_text())
    expected = json.loads((RESOURCES / f"{name}.golden").read_text())
    originals = _materialize(workdir, manifest)
    path = os.pathsep.join([*(str(workdir / d) for d in manifest["path_prepend"]), str(tool_bin)])
    stdin = base64.b64decode(manifest["stdin"])
    if manifest.get("stdin_zlib"):
        stdin = zlib.decompress(stdin)
    result = run(
        manifest["args"],
        input=stdin,
        cwd=workdir / manifest["cwd"],
        env_overrides={"PATH": path, **manifest["env"]},
    )
    actual = {
        "stdout": result.stdout.decode(),
        "stderr": normalize_trace(result.stderr.decode()),
        "status": result.returncode,
        "changed_files": _changed_files(workdir, originals),
    }
    if "check" in manifest:
        # Stdin output equals input: path mode must agree the file is already
        # formatted and leave its bytes untouched.
        target = workdir / manifest["check"]["target"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(stdin)
        check = run(
            manifest["check"]["args"],
            cwd=workdir / manifest["cwd"],
            env_overrides={"PATH": path, **manifest["env"]},
        )
        actual["check"] = {
            "stdout": check.stdout.decode(),
            "stderr": normalize_trace(check.stderr.decode()),
            "status": check.returncode,
            "file": target.read_bytes().decode(),
        }
    assert actual == expected
