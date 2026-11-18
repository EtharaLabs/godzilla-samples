"""Exact CLI transcripts harvested from the project's documented `.case` examples.

Each resource `<name>.json` records the invocation (argv, stdin and an optional
Git repository fixture); `<name>.golden` records the reference binary's exact
exit status, stdout and stderr, plus Git index/worktree/status checks when the
case changes a repository.
"""

import shutil
from pathlib import Path

import pytest

from conftest import git, load_json, make_git_repo, redact, resources_for, stdin_check_args

RESOURCES = resources_for(__file__)
CASES = sorted(path.stem for path in RESOURCES.glob("*.json"))


def observe_transcript(name: str, workdir: Path, env: dict, runner) -> dict:
    """Run one harvested transcript and return everything a test compares."""
    spec = load_json(RESOURCES / f"{name}.json")
    fixtures = workdir / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    for fixture in (RESOURCES / "fixtures").iterdir():
        shutil.copyfile(fixture, fixtures / fixture.name)
    repo = None
    cwd = workdir
    if "git_fixture" in spec:
        fixture = spec["git_fixture"]
        repo = make_git_repo(workdir / "repo", env, fixture["files"], fixture.get("config"),
                             index_files=fixture.get("unix-index-files"))
        cwd = repo / fixture.get("cwd", ".")
    result = runner(spec["args"], input=spec["stdin"], cwd=cwd,
                    env_overrides={"GIT_CONFIG_NOSYSTEM": "1"})
    pairs = [("{{repo}}", repo)] if repo else []
    observed = {
        "status": result.returncode,
        "stdout": redact(result.stdout.decode("utf-8", "replace"), *pairs),
        "stderr": redact(result.stderr.decode("utf-8", "replace"), *pairs),
    }
    if spec.get("check_rerun"):
        args, path = stdin_check_args(spec["args"])
        (cwd / path).parent.mkdir(parents=True, exist_ok=True)
        (cwd / path).write_text(spec["stdin"], encoding="utf-8")
        rerun = runner(args, cwd=cwd, env_overrides={"GIT_CONFIG_NOSYSTEM": "1"})
        observed["check_rerun"] = {"status": rerun.returncode, "stdout": rerun.stdout.decode(),
                                   "stderr": redact(rerun.stderr.decode(), *pairs)}
    if repo is not None:
        if spec.get("git_status"):
            observed["git_status"] = git(["status", "--porcelain"], repo, env).stdout.decode()
        if spec.get("git_index"):
            observed["git_index"] = {
                path: git(["show", f":{path}"], repo, env).stdout.decode() for path in spec["git_index"]
            }
        if spec.get("git_worktree"):
            observed["git_worktree"] = {
                path: (repo / path).read_bytes().decode() for path in spec["git_worktree"]
            }
    return observed


@pytest.mark.parametrize("name", CASES)
def test_transcript(name, run, workdir, env):
    """CATCHES: any rewrite whose exact stdout, stderr or exit status differs from the reference for the
    project's own documented CLI transcripts (formatting, wrapping modes, diff/check output, to-yaml
    conversion, external formatter handling, config discovery and git-filter adoption), including
    wrong Git index or working-tree bytes after git-filter commands."""
    expected = load_json(RESOURCES / f"{name}.golden")
    assert observe_transcript(name, workdir, env, run) == expected
