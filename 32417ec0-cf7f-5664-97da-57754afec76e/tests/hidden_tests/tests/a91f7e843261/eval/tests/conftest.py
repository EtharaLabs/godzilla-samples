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


# --------------------------------------------------------------------------------------------------
# declscope-specific helpers.
#
# declscope is a Go linter: every run loads Go packages through the go command, so each test lays out a
# small Go module in its workdir. The Go build cache is shared between tests (it is safe for concurrent
# use and never changes what the program prints), so standard-library export data is compiled once
# rather than once per test. GOPROXY=off and GOTOOLCHAIN=local keep the go command off the network.

import tempfile  # noqa: E402

GOCACHE = Path(tempfile.gettempdir()) / f"declscope-eval-gocache-{os.getuid()}"
GO_ENV = {
    "GOCACHE": str(GOCACHE),
    "GOTOOLCHAIN": "local",
    "GOPROXY": "off",
    "GOSUMDB": "off",
    "GOFLAGS": "-trimpath",
    "GO111MODULE": "",
}

GO_MOD = "module example.com/app\n\ngo 1.22\n"


# Paths the program prints are absolute, and markdown tables pad their columns to them. Every test therefore works
# in a directory whose path has a fixed length, and that path is replaced by a token of the same length, so the
# padding in an expected output is exactly what the program prints.
SCRATCH_TOKEN = "/tmp/dse-xxxxxxxxxxxx"


def _force_remove(func, path, exc):
    os.chmod(os.path.dirname(path), 0o755)
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, 0o755)
    func(path)


@pytest.fixture
def scratch():
    """/tmp/dse-<12 hex digits>, holding work/ and home/; removed afterwards (module caches are read-only)."""
    import secrets
    import shutil

    base = Path("/tmp") / f"dse-{secrets.token_hex(6)}"
    assert len(str(base)) == len(SCRATCH_TOKEN)
    (base / "work").mkdir(parents=True)
    (base / "home").mkdir()
    yield base
    # A go command a timed-out run left behind may still be writing here; a second pass, then giving up, keeps a
    # slow cleanup from turning into a test error.
    for _ in range(2):
        try:
            shutil.rmtree(base, onexc=_force_remove)
            break
        except OSError:
            continue


@pytest.fixture
def workdir(scratch: Path) -> Path:
    """Empty working directory at a fixed-length path; use relative paths so outputs stay stable."""
    return scratch / "work"


@pytest.fixture
def goenv(env: dict[str, str], scratch: Path) -> dict[str, str]:
    """The fixed environment plus the Go settings above, with HOME inside the scratch directory."""
    return {**env, **GO_ENV, "HOME": str(scratch / "home")}


def write_tree(root: Path, files: dict) -> None:
    """Write {relative path: text or bytes} under root, creating directories."""
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")


def snapshot_tree(root: Path, skip_dirs=("home",)) -> str:
    """Every regular file under root, in path order, as one text: '=== path\\n<content>'."""
    out = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.split("/")[0] in skip_dirs:
            continue
        out.append(f"=== {rel}\n{path.read_bytes().decode('utf-8', 'replace')}")
    return "\n".join(out)


class Outcome:
    """A finished run with every volatile path replaced by a fixed token."""

    def __init__(self, proc: subprocess.CompletedProcess, subs: list[tuple[str, str]]):
        self.returncode = proc.returncode
        self.stdout = normalize(proc.stdout, subs)
        self.stderr = normalize(proc.stderr, subs)

    @property
    def transcript(self) -> str:
        """Exit status, stdout and stderr in one text, so one == compares all three."""
        return f"exit {self.returncode}\n--- stdout\n{self.stdout}--- stderr\n{self.stderr}"

    @property
    def json_transcript(self) -> str:
        """The transcript of a -json run, with the edits of each suggested fix in file and offset order.

        The program lists the edits of a fix that spans several files in no fixed order (a rename's edits come
        from a map), so only their set is the contract. Everything else is kept as printed.
        """
        import json

        data = json.loads(self.stdout)
        for analyzers in data.values():
            for diagnostics in analyzers.values():
                for diagnostic in diagnostics if isinstance(diagnostics, list) else []:
                    for fix in diagnostic.get("suggested_fixes", []):
                        fix["edits"] = sorted(fix["edits"], key=lambda e: (e["filename"], e["start"], e["end"], e["new"]))
        stdout = json.dumps(data, indent="\t", ensure_ascii=False) + "\n"
        return f"exit {self.returncode}\n--- stdout (edits sorted)\n{stdout}--- stderr\n{self.stderr}"


def normalize(data: bytes, subs: list[tuple[str, str]]) -> str:
    text = data.decode("utf-8", "replace")
    for old, new in subs:
        text = text.replace(old, new)
    return text


def path_subs(scratch: Path) -> list[tuple[str, str]]:
    pairs = {}
    for path, token in ((scratch, SCRATCH_TOKEN), (GOCACHE, "$GOCACHE")):
        for variant in {str(path), str(path.resolve())}:
            pairs[variant] = token
    return sorted(pairs.items(), key=lambda kv: -len(kv[0]))


@pytest.fixture
def ds(workdir: Path, scratch: Path, goenv: dict[str, str]):
    """ds(args, cwd=None, env_overrides=None, input=None) -> Outcome; runs declscope in workdir (or cwd)."""
    subs = path_subs(scratch)

    def _ds(args, *, cwd=None, env_overrides=None, input=None, timeout=28):
        proc = run_executable(args, input=input, cwd=cwd or workdir, env={**goenv, **(env_overrides or {})},
                              timeout=timeout)
        return Outcome(proc, subs)

    return _ds


def read_golden(test_file: str, name: str) -> str:
    return (resources_for(test_file) / f"{name}.golden").read_text(encoding="utf-8")


WARM_GO = """package warm

import (
\t_ "bytes"
\t_ "context"
\t_ "encoding/json"
\t_ "errors"
\t_ "fmt"
\t_ "io"
\t_ "os"
\t_ "reflect"
\t_ "sort"
\t_ "strconv"
\t_ "strings"
\t_ "sync"
\t_ "time"
\t_ "unsafe"
)
"""


def pytest_sessionstart(session):
    """Compile the standard library's export data into the shared cache once, before any test's timeout runs.

    xdist starts one session per worker; a file lock makes one of them do the work while the others wait.
    """
    import fcntl

    GOCACHE.mkdir(parents=True, exist_ok=True)
    with open(GOCACHE.parent / f"{GOCACHE.name}.lock", "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        stamp = GOCACHE / ("declscope-eval-warm" + GO_ENV["GOFLAGS"].replace("-", "_"))
        if stamp.exists():
            return
        with tempfile.TemporaryDirectory(prefix="declscope-warm-") as tmp:
            root = Path(tmp)
            write_tree(root, {
                "go.mod": "module example.com/warm\n\ngo 1.22\n",
                "w.go": WARM_GO,
                "w_test.go": 'package warm\n\nimport "testing"\n\nfunc TestW(t *testing.T) {}\n',
                "x_test.go": 'package warm_test\n\nimport "testing"\n\nfunc TestX(t *testing.T) {}\n',
            })
            home = root / "home"
            home.mkdir()
            subprocess.run(["go", "list", "-e", "-export", "-compiled", "-test", "-deps", "./..."], cwd=root,
                           env={**base_env(home), **GO_ENV}, capture_output=True, timeout=600)
        stamp.write_text("")
