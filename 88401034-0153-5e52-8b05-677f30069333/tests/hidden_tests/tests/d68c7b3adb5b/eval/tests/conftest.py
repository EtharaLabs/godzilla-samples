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
EXECUTABLE = Path(os.environ.get("LUMEN_SUITE_EXECUTABLE") or ROOT / "executable")  # override: coverage builds
RESOURCES = Path(__file__).resolve().parent.parent / "test_resources"
DEFAULT_TIMEOUT = 20


# Time limits follow this machine's speed. They were set on native hardware (pytest's per-test --timeout in
# eval/run.sh, each run of the program, the tests' own socket waits). Under CPU emulation (an amd64 image on an arm64
# host, or the reverse) everything runs 10-35x slower, and the reference program itself would hit them. A fixed amount
# of pure-Python work is timed once: within 4x of its native time (0.0142 s on the arm64 host the limits were checked
# on) every limit stays exactly as written; slower than that, every limit is multiplied by the measured slowdown, at
# most 20x.
def _measured_slowdown() -> float:
    import time

    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        n = 0
        for i in range(200_000):
            n = (n + i * i) % 1_000_003
        best = min(best, time.perf_counter() - start)
    return best / 0.0142


SLOWDOWN = _measured_slowdown()
TIME_SCALE = 1.0 if SLOWDOWN < 4 else min(SLOWDOWN, 20.0)


def scaled(seconds):
    """A time limit for this machine: as written on native hardware, longer under emulation."""
    return None if seconds is None else seconds * TIME_SCALE


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
                          timeout=scaled(timeout), **stdin)


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


# ---------------------------------------------------------------------------------------- goldens
def load_golden(path: Path) -> str:
    """Expected output captured from the reference binary (read-only; tests never write goldens)."""
    return path.read_text(encoding="utf-8")


@pytest.fixture
def golden(request):
    """golden(name) -> text of eval/test_resources/<this test module>/<name>.golden."""
    base = resources_for(str(request.path))

    def _golden(name: str) -> str:
        return load_golden(base / f"{name}.golden")

    return _golden


def out(proc: subprocess.CompletedProcess) -> str:
    """Decoded stdout of a finished run."""
    return proc.stdout.decode("utf-8", errors="replace")


def err(proc: subprocess.CompletedProcess) -> str:
    """Decoded stderr of a finished run."""
    return proc.stderr.decode("utf-8", errors="replace")


@pytest.fixture
def js(run, workdir):
    """js(code, *flags, name="main.js", env_overrides=None, input=None) writes `code` to
    workdir/<name> and runs `lumen-cli [flags] <name>` on it."""

    def _js(code: str, *flags, name: str = "main.js", env_overrides=None, input=None, args=()):
        (workdir / name).write_text(code, encoding="utf-8")
        return run([*flags, name, *args], env_overrides=env_overrides, input=input)

    return _js


# ------------------------------------------------------------------------------- native addons
def build_addon(c_source: str, dest: Path) -> Path:
    """Compile an N-API addon from C source into `dest` (a .node shared library) with the system C
    compiler, the way examples/native-addon/build.sh does. Skips the test if no compiler exists."""
    import shutil

    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        pytest.skip("no C compiler available to build the N-API addon")
    src = dest.with_suffix(".c")
    src.write_text(c_source, encoding="utf-8")
    proc = subprocess.run([cc, "-shared", "-fPIC", "-O0", "-o", str(dest), str(src)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    src.unlink()
    return dest


def pytest_collection_modifyitems(config, items):
    """pytest's per-test limit (eval/run.sh --timeout) scales like every other limit; untouched on native hardware."""
    if TIME_SCALE == 1.0:
        return
    base = config.getoption("timeout", None) or 30
    for item in items:
        item.add_marker(pytest.mark.timeout(base * TIME_SCALE))
