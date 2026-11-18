"""Shared fixtures for the hidden behavioural test suite.

Every test treats ./executable (the workspace root) as a black box: run it as a
subprocess and assert on stdout, stderr, exit code and the files it writes.
Expected outputs that were captured from the reference program live under
eval/test_resources/<test module name>/.
"""

import fcntl
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTABLE = ROOT / "executable"
RESOURCES = Path(__file__).resolve().parent.parent / "test_resources"
DEFAULT_TIMEOUT = 20

# declscope type-checks Go code through the go command, which compiles the
# export data of every standard-library package a fixture imports. A fresh
# build cache per test would recompile the standard library each time, so all
# tests share one cache. It only changes how long the go command takes, never
# what it reports.
GOCACHE = Path(tempfile.gettempdir()) / f"declscope-eval-gocache-{os.getuid()}"
_WARM_MARKER = GOCACHE / ".declscope-eval-warm-v1"
_WARM_IMPORTS = ("encoding/json", "errors", "fmt", "io", "os", "reflect", "sort", "strconv", "strings", "sync",
                 "testing", "unsafe")


def _warm_go_cache() -> None:
    """Compile the export data the fixtures need once, before any test's timeout starts."""
    GOCACHE.mkdir(parents=True, exist_ok=True)
    with open(GOCACHE.parent / f"{GOCACHE.name}.lock", "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if _WARM_MARKER.exists():
            return
        with tempfile.TemporaryDirectory() as d:
            mod = Path(d) / "warm"
            mod.mkdir()
            (mod / "go.mod").write_text("module warm\n\ngo 1.25\n")
            (mod / "warm.go").write_text("package warm\n")
            imports = "".join(f'\t_ "{p}"\n' for p in _WARM_IMPORTS)
            (mod / "warm_test.go").write_text(f"package warm\n\nimport (\n{imports})\n")
            env = base_env(Path(d))
            subprocess.run(["go", "list", "-e", "-export", "-deps", "-test", "-compiled", "-json=ImportPath", "./..."],
                           cwd=mod, env=env, capture_output=True, timeout=1800)
        _WARM_MARKER.write_text("ok\n")


def pytest_sessionstart(session):
    _warm_go_cache()


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
        # The go command declscope runs: a shared build cache, the installed
        # toolchain only, and no network.
        "GOCACHE": str(GOCACHE),
        "GOTOOLCHAIN": "local",
        "GOPROXY": "off",
        "GOSUMDB": "off",
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
def fixed_workdir():
    """A working directory whose absolute path has the same length on every run.

    Markdown tables pad their columns to the widest cell, and a cell can hold an absolute path, so the padding of a
    table naming one depends on how long the path is. Normalizing the path keeps the text stable only when its
    length is stable too.
    """
    root = Path("/tmp") / f"dse-{secrets.token_hex(8)}"
    d = root / "work"
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(root, ignore_errors=True)


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


# ----------------------------------------------------------------------------- helpers for Go fixtures


def write_files(root: Path, files: dict[str, str]) -> None:
    """Write each relative path of files under root, creating directories as needed."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def gomod(path: str, extra: str = "") -> str:
    """The text of a go.mod for module path."""
    return f"module {path}\n\ngo 1.25\n" + (f"\n{extra}" if extra else "")


def normalize(text: str, workdir: Path) -> str:
    """Spell the test's temporary directories as $WORK (the working directory) and $TMP (its parent)."""
    tmp = workdir.parent
    for real, name in ((workdir, "$WORK"), (tmp, "$TMP")):
        for spelled in {str(real.resolve()), str(real)}:
            text = text.replace(spelled, name)
    return text


def transcript(proc: subprocess.CompletedProcess, workdir: Path, files: tuple[str, ...] = ()) -> str:
    """Exit code, stdout, stderr and the named files under workdir, as one text with paths normalized."""
    parts = [f"exit: {proc.returncode}",
             "--- stdout", proc.stdout.decode(errors="replace"),
             "--- stderr", proc.stderr.decode(errors="replace")]
    for rel in files:
        path = workdir / rel
        parts += [f"--- file {rel}", path.read_text() if path.exists() else "<missing>"]
    return normalize("\n".join(parts), workdir)


def golden_path(test_file: str, name: str) -> Path:
    return resources_for(test_file) / f"{name}.golden"


def assert_golden(actual: str, test_file: str, name: str) -> None:
    """Compare actual with the golden file <name>.golden of the calling test module."""
    expected = golden_path(test_file, name).read_text()
    assert actual == expected


def snapshot(root: Path) -> dict[str, str]:
    """Every file under root, by its path relative to root."""
    return {p.relative_to(root).as_posix(): p.read_text(errors="replace")
            for p in sorted(root.rglob("*")) if p.is_file()}


def changes(before: dict[str, str], root: Path) -> str:
    """The files under root that differ from before: each changed or new file whole, and each removed one named."""
    after = snapshot(root)
    parts = []
    for rel in sorted(set(before) | set(after)):
        if rel not in after:
            parts.append(f"--- removed {rel}\n")
        elif before.get(rel) != after[rel]:
            parts.append(f"--- changed {rel}\n{after[rel]}")
    return normalize("".join(parts) if parts else "--- no file changed\n", root)


def analyze_fixture(run, workdir: Path, module: str, files: dict[str, str], fix: bool = False,
                    survey: bool = False) -> str:
    """Write files as module and run the analyzer over ./... With fix, run -fix and record what it changed. With
    survey, also record survey -format=json, whose counts show why a silent run was silent."""
    write_files(workdir, {"go.mod": gomod(module), **files})
    before = snapshot(workdir)
    out = transcript(run(["./..."]), workdir)
    if fix:
        out += "\n=== -fix\n" + transcript(run(["-fix", "./..."]), workdir) + changes(before, workdir)
    if survey:
        out += "\n=== survey -format=json\n" + transcript(run(["survey", "-format=json", "./..."]), workdir)
    return out
