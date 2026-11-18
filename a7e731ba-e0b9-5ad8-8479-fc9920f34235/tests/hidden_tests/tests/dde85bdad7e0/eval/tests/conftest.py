"""Shared fixtures for the hidden behavioural test suite.

Every test treats ./executable (the workspace root) as a black box: run it as a
subprocess and assert on stdout, stderr, exit code and the files it writes.
Expected outputs that were captured from the reference program live under
eval/test_resources/<test module name>/.
"""

import os
import re
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
def run(workdir: Path, env: dict[str, str], tool_bin: Path):
    """run(args, input=None, cwd=None, env_overrides=None, timeout=20) -> CompletedProcess (cwd defaults to workdir).

    PATH defaults to `tool_bin` (Python, Git and a few POSIX tools) so optional embedded
    formatters such as ruff, air, prettier or mdformat are reliably absent unless a test
    supplies a fake one."""

    def _run(args, *, input=None, cwd=None, env_overrides=None, timeout=DEFAULT_TIMEOUT):
        merged = {**env, "PATH": str(tool_bin), **(env_overrides or {})}
        return run_executable(args, input=input, cwd=cwd or workdir, env=merged, timeout=timeout)

    return _run


# Utilities that fake formatter scripts may call. Tests that need a controlled
# PATH (so optional formatters such as ruff/air/prettier are reliably absent)
# expose only these, plus Python.
TOOLS = ("git", "sh", "cat", "tr", "sed", "head", "tail", "printf", "echo", "sleep", "true", "false", "env", "dd", "rev")


@pytest.fixture
def tool_bin(tmp_path: Path) -> Path:
    """A PATH directory holding python/python3 and a few POSIX tools, nothing else."""
    import shutil
    import sys

    b = tmp_path / "bin"
    b.mkdir()
    for name in ("python", "python3"):
        (b / name).symlink_to(sys.executable)
    for tool in TOOLS:
        found = shutil.which(tool)
        if found:
            (b / tool).symlink_to(found)
    return b


def load_golden(module: str, name: str):
    """Expected result recorded from the reference binary: test_resources/<module>/<name>.golden (JSON)."""
    import json

    return json.loads((RESOURCES / module / f"{name}.golden").read_text(encoding="utf-8"))


@pytest.fixture
def golden(request):
    """golden(name) -> the JSON golden for this test module."""
    module = Path(request.module.__file__).stem

    def _load(name: str):
        return load_golden(module, name)

    return _load


YAML_TRACE = re.compile(r"(note: yaml trace:)[^\n]*")


def normalize_trace(text: str) -> str:
    """`--diagnostics` appends a `yaml trace:` note whose counters describe internal parser
    passes; keep the note but drop those implementation-specific numbers."""
    return YAML_TRACE.sub(r"\1 <counters>", text)


def outcome(result: subprocess.CompletedProcess, workdir: Path | None = None, files=()) -> dict:
    """Everything observable about one run: decoded stdout/stderr, exit status, and the named files' bytes."""
    observed = {
        "stdout": result.stdout.decode("utf-8", errors="surrogateescape"),
        "stderr": normalize_trace(result.stderr.decode("utf-8", errors="surrogateescape")),
        "status": result.returncode,
    }
    if files:
        observed["files"] = {
            name: (workdir / name).read_bytes().decode("utf-8", errors="surrogateescape")
            if (workdir / name).exists() else None
            for name in files
        }
    return observed


def format_both_ways(run, workdir: Path, path: str, text, *flags, env_overrides=None) -> dict:
    """Format `text` through stdin (`--stdin-file-path path`) and through path-mode
    `--check` on a file of the same name; return both observed outcomes."""
    data = text.encode() if isinstance(text, str) else text
    stdin_result = run(["format", "--stdin-file-path", path, *flags], input=data, env_overrides=env_overrides)
    target = workdir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    check = run(["format", "--check", *flags, path], env_overrides=env_overrides)
    return {"stdin": outcome(stdin_result), "check": outcome(check, workdir, [path])}


def run_with_stdout_file(args, stdout_path: str, *, input=None, cwd=None, env=None, timeout=DEFAULT_TIMEOUT):
    """Run the program with stdout redirected to `stdout_path` (e.g. /dev/full); stderr captured."""
    if isinstance(input, str):
        input = input.encode()
    with open(stdout_path, "wb") as sink:
        stdin = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}
        return subprocess.run([str(EXECUTABLE), *map(str, args)], cwd=cwd, env=env, stdout=sink,
                              stderr=subprocess.PIPE, timeout=timeout, **stdin)
