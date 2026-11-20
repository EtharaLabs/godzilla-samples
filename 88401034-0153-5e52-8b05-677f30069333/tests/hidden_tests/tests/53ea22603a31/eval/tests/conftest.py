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


def assert_golden(actual: bytes, path: Path) -> None:
    """Exact comparison of program output with a golden file captured from the reference binary."""
    expected = path.read_bytes()
    assert actual.decode("utf-8", "replace") == expected.decode("utf-8", "replace")  # readable diff first
    assert actual == expected


def assert_result(result: subprocess.CompletedProcess, golden: Path, *, rc: int = 0, stderr: str | bytes | Path = b"") -> None:
    """stdout == golden file, exact stderr (literal or another golden file) and exact exit code."""
    assert_golden(result.stdout, golden)
    if isinstance(stderr, Path):
        assert_golden(result.stderr, stderr)
    else:
        expected_err = stderr.encode() if isinstance(stderr, str) else stderr
        assert result.stderr.decode("utf-8", "replace") == expected_err.decode("utf-8", "replace")
        assert result.stderr == expected_err
    assert result.returncode == rc


def check_script(run, workdir: Path, golden_dir: Path, name: str, source: str, *, filename: str | None = None,
                 args=(), cli=(), input=None, rc: int = 0, stderr: str | bytes | Path = b"",
                 env_overrides=None) -> subprocess.CompletedProcess:
    """Write `source` to workdir/<filename> (default <name>.js), run `lumen-cli [cli...] <file> [args...]`
    and assert stdout == <golden_dir>/<name>.golden plus the exact stderr and exit code."""
    filename = filename or f"{name}.js"
    target = workdir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)
    result = run([*cli, filename, *args], input=input, env_overrides=env_overrides)
    assert_result(result, golden_dir / f"{name}.golden", rc=rc, stderr=stderr)
    return result


def write_files(root: Path, files: dict[str, str | bytes]) -> None:
    """Create a tree of input files (relative paths) under root."""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)
