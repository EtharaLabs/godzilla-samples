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


# ---------------------------------------------------------------------------
# Case tables: a test describes one invocation (argv, stdin, input files, the
# files it expects the program to write) and compares the whole observable
# transcript — exit code, stdout, stderr and written files — with a golden.
# ---------------------------------------------------------------------------

import socket
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    args: tuple
    stdin: str | bytes | None = None
    files: dict = field(default_factory=dict)  # relative path -> str | bytes, created before the run
    outputs: tuple = ()  # relative paths read back after the run
    env: dict = field(default_factory=dict)


def write_files(workdir: Path, files: dict) -> None:
    for rel, content in files.items():
        p = workdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


def transcript(result: subprocess.CompletedProcess, workdir: Path, outputs=()) -> str:
    """Everything observable about one run, as one string for an exact golden compare."""
    parts = [
        f"exit: {result.returncode}\n",
        "--- stdout\n", result.stdout.decode("utf-8"),
        "\n--- stderr\n", result.stderr.decode("utf-8"),
    ]
    for rel in outputs:
        p = workdir / rel
        if p.exists():
            parts += [f"\n--- file {rel}\n", p.read_bytes().decode("utf-8")]
        else:
            parts.append(f"\n--- file {rel} (absent)\n")
    return "".join(parts)


def execute_case(case: Case, workdir: Path, env: dict) -> str:
    write_files(workdir, case.files)
    r = run_executable(list(case.args), input=case.stdin, cwd=workdir, env={**env, **case.env})
    return transcript(r, workdir, case.outputs)


@pytest.fixture
def run_case(workdir: Path, env: dict):
    """run_case(Case) -> transcript string (exit code, stdout, stderr, written files)."""
    return lambda case: execute_case(case, workdir, env)


@pytest.fixture
def golden(request):
    """golden(name) -> the text of eval/test_resources/<module>/<name>.golden."""
    base = resources_for(request.module.__file__)
    return lambda name: (base / f"{name}.golden").read_bytes().decode("utf-8")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def spawn(workdir: Path, env: dict):
    """spawn(args, cwd=None, stdout=None, stderr=None) -> a running Popen of the program
    (killed at teardown) for long-lived modes. stdout/stderr may name files to log into;
    by default they are pipes."""
    procs = []

    def _spawn(args, cwd=None, stdout=None, stderr=None):
        streams = {}
        for key, target in (("stdout", stdout), ("stderr", stderr)):
            streams[key] = open(target, "wb") if target is not None else subprocess.PIPE
        p = subprocess.Popen([str(EXECUTABLE), *map(str, args)], cwd=cwd or workdir, env=env,
                             stdin=subprocess.DEVNULL, **streams)
        for f in streams.values():
            if f is not subprocess.PIPE:
                f.close()
        procs.append(p)
        return p

    yield _spawn
    for p in procs:
        if p.poll() is None:
            p.kill()
        p.communicate(timeout=10)


def wait_for(predicate, timeout=8.0, interval=0.05):
    """Poll predicate() until it returns a truthy value; returns that value (or None on timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None
