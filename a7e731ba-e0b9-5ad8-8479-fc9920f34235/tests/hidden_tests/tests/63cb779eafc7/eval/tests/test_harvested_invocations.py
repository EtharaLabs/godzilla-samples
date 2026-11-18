"""Exact replays of CLI invocations taken from the project's public CLI test suites.

Each `<id>.json` resource records argv, stdin, the files present in the working
directory (configs, fake formatter executables on PATH, inputs) and whether the
stdin result is re-checked in path mode. `<id>.golden` holds the reference
binary's exact status, stdout, stderr and the bytes of every file afterwards.
"""

import base64

import pytest

from conftest import load_json, materialize, redact, resources_for, stdin_check_args

RESOURCES = resources_for(__file__)
CASES = sorted(path.stem for path in RESOURCES.glob("*.json"))


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return "base64:" + base64.b64encode(data).decode()


def observe_invocation(name, workdir, env, runner) -> dict:
    spec = load_json(RESOURCES / f"{name}.json")
    materialize(workdir, spec["files"])
    stdin = spec["stdin"].encode("utf-8") if "stdin" in spec else base64.b64decode(spec["stdin_b64"])
    overrides = {}
    if spec["path_dirs"]:
        overrides["PATH"] = ":".join([str(workdir / d) for d in spec["path_dirs"]] + [env["PATH"]])
    result = runner(spec["args"], input=stdin, env_overrides=overrides)
    pairs = [("{{workdir}}", workdir)]
    observed = {
        "status": result.returncode,
        "stdout": redact(_text(result.stdout), *pairs),
        "stderr": redact(_text(result.stderr), *pairs),
        "files": {rel: _text((workdir / rel).read_bytes()) for rel, entry in sorted(spec["files"].items())
                  if "link" not in entry and (workdir / rel).is_file()},
    }
    if spec.get("check_rerun"):
        args, path = stdin_check_args(spec["args"])
        (workdir / path).parent.mkdir(parents=True, exist_ok=True)
        (workdir / path).write_bytes(stdin)
        rerun = runner(args, env_overrides=overrides)
        observed["check_rerun"] = {"status": rerun.returncode, "stdout": _text(rerun.stdout),
                                   "stderr": redact(_text(rerun.stderr), *pairs)}
    return observed


@pytest.mark.parametrize("name", CASES)
def test_invocation(name, run, workdir, env):
    """CATCHES: rewrites that differ from the reference in exact formatted output, diagnostics, exit status or
    written file bytes for invocations drawn from the project's public CLI specifications (Markdown wrapping
    modes, YAML scalar/collection layout, directives, templates, front matter, Python/R source targets, external
    formatter dispatch through PATH, JSON-family projection), and stdin-mode results that `--check` would not
    accept as already formatted."""
    expected = load_json(RESOURCES / f"{name}.golden")
    assert observe_invocation(name, workdir, env, run) == expected
