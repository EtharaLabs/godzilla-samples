"""Shared fixtures for the hidden behavioural test suite.

Every test treats ./executable (the workspace root) as a black box: run it as a
subprocess and assert on stdout, stderr, exit code and the files it writes.
Expected outputs that were captured from the reference program live under
eval/test_resources/<test module name>/.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTABLE = ROOT / "executable"
RESOURCES = Path(__file__).resolve().parent.parent / "test_resources"
DEFAULT_TIMEOUT = 20


def resources_for(test_file: str) -> Path:
    """eval/test_resources/<module>/ for the calling test module (pass __file__)."""
    return RESOURCES / Path(test_file).stem


COVERAGE_VARS = ("LLVM_PROFILE_FILE", "GOCOVERDIR")  # only set while measuring coverage


def base_env(home: Path) -> dict[str, str]:
    """A fixed environment so outputs do not depend on the host."""
    passthrough = {k: os.environ[k] for k in COVERAGE_VARS if k in os.environ}
    if os.environ.get("SUITE_CHECK_AUDIT") == "1" and "PYTEST_CURRENT_TEST" in os.environ:  # argv audit only
        passthrough["PYTEST_CURRENT_TEST"] = os.environ["PYTEST_CURRENT_TEST"]
    return {
        **passthrough,
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TERM": "dumb",
        "COLUMNS": "80",
        "LINES": "24",
        "NO_COLOR": "1",
    }


def run_executable(args, *, input=None, cwd=None, env=None, timeout=DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run the program under test. `input` is bytes or str; stdout/stderr are bytes."""
    if isinstance(input, str):
        input = input.encode()
    stdin = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}  # never inherit pytest's stdin
    return subprocess.run([str(EXECUTABLE), *map(str, args)], cwd=cwd, env=env, capture_output=True,
                          timeout=timeout, **stdin)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Empty working directory; run the program here and use relative paths so outputs stay stable."""
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    return base_env(home)


@pytest.fixture
def run(workdir: Path, env: dict[str, str]):
    """run(args, input=None, cwd=None, env_overrides=None, timeout=20) -> CompletedProcess (cwd defaults to workdir)."""

    def _run(args, *, input=None, cwd=None, env_overrides=None, timeout=DEFAULT_TIMEOUT):
        return run_executable(args, input=input, cwd=cwd or workdir, env={**env, **(env_overrides or {})}, timeout=timeout)

    return _run


# --- shared helpers -------------------------------------------------------

import json  # noqa: E402

GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Suite",
    "GIT_AUTHOR_EMAIL": "suite@example.test",
    "GIT_COMMITTER_NAME": "Suite",
    "GIT_COMMITTER_EMAIL": "suite@example.test",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
}


def git(args, cwd, env, *, input=None) -> subprocess.CompletedProcess:
    """Run git for fixture setup or inspection; fails loudly when git fails."""
    if isinstance(input, str):
        input = input.encode()
    stdin = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}
    result = subprocess.run(["git", *map(str, args)], cwd=cwd, env={**env, **GIT_ENV}, capture_output=True,
                            timeout=DEFAULT_TIMEOUT, **stdin)
    assert result.returncode == 0, (args, result.stderr.decode(errors="replace"))
    return result


def make_git_repo(root: Path, env, files: dict, config: dict | None = None, *, index_files=None,
                  commit: bool = True) -> Path:
    """Create a git repository at root with the given files (str or bytes) committed."""
    root.mkdir(parents=True, exist_ok=True)
    git(["-c", "init.defaultBranch=main", "init", "-q"], root, env)
    git(["config", "user.name", "Suite"], root, env)
    git(["config", "user.email", "suite@example.test"], root, env)
    git(["config", "commit.gpgSign", "false"], root, env)
    for key, value in (config or {}).items():
        git(["config", key, value], root, env)
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, str):
            contents = contents.encode()
        path.write_bytes(contents)
    for entry in index_files or []:
        name = bytes(entry["name_bytes"])
        blob = git(["hash-object", "-w", "--stdin"], root, env, input=entry["contents"]).stdout.decode().strip()
        subprocess.run([b"git", b"update-index", b"--add", b"--cacheinfo", b"100644", blob.encode(), name],
                       cwd=root, env={**env, **GIT_ENV}, check=True, capture_output=True)
        subprocess.run([b"git", b"update-index", b"--skip-worktree", b"--", name],
                       cwd=root, env={**env, **GIT_ENV}, check=True, capture_output=True)
    if commit:
        git(["add", "."], root, env)
        git(["commit", "-q", "-m", "fixture"], root, env)
    return root


def redact(text: str, *paths: Path) -> str:
    """Replace absolute temporary paths with stable placeholders ({{repo}}, {{workdir}}...)."""
    for placeholder, path in paths:
        real = str(Path(path).resolve())
        text = text.replace(real, placeholder)
        if str(path) != real:
            text = text.replace(str(path), placeholder)
    return text


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def transcript(result: subprocess.CompletedProcess, *redactions) -> str:
    """Render exit status, stdout and stderr exactly (optionally with path placeholders)."""
    stdout = redact(result.stdout.decode("utf-8"), *redactions)
    stderr = redact(result.stderr.decode("utf-8"), *redactions)
    return f"exit status: {result.returncode}\n--- stdout\n{stdout}--- stderr\n{stderr}"


def assert_golden(actual: str, test_file: str, name: str) -> None:
    """Compare text exactly (bytes, including line endings) with test_resources/<module>/<name>.golden."""
    expected = (resources_for(test_file) / f"{name}.golden").read_bytes().decode("utf-8")
    assert actual == expected


def materialize(root: Path, files: dict) -> None:
    """Create files from a {relative path: {"text"|"b64": ..., "mode": int} | {"link": target}} mapping."""
    import base64
    for rel, entry in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if "link" in entry:
            os.symlink(entry["link"], path)
            continue
        data = entry["text"].encode("utf-8") if "text" in entry else base64.b64decode(entry["b64"])
        path.write_bytes(data)
        os.chmod(path, entry.get("mode", 0o644))


def stdin_check_args(args: list[str]) -> tuple[list[str], str]:
    """Turn `format --stdin-file-path P ...` into the equivalent `format --check ... P` path-mode argv."""
    index = args.index("--stdin-file-path")
    path = args[index + 1]
    rest = args[1:index] + args[index + 2:]
    return ["format", "--check", *rest, path], path


def run_with_closed_stdout(args, *, input=b"", cwd, env) -> subprocess.CompletedProcess:
    """Run the program with stdout connected to a pipe whose reader is already closed (writes fail with EPIPE)."""
    if isinstance(input, str):
        input = input.encode()
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        return subprocess.run([str(EXECUTABLE), *map(str, args)], input=input, stdout=write_end,
                              stderr=subprocess.PIPE, cwd=cwd, env=env, timeout=DEFAULT_TIMEOUT)
    finally:
        os.close(write_end)
