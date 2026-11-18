"""Shared fixtures for the hidden behavioural test suite.

Every test treats ./executable (the workspace root) as a black box: run it as a
subprocess and assert on stdout, stderr, exit code and the files it writes.
Expected outputs that were captured from the reference program live under
eval/test_resources/<test module name>/.

declscope loads packages through the go command, which compiles the export
data of every standard-library dependency into the Go build cache. A fresh
cache per test costs tens of seconds, so every test shares one cache directory,
and the controller warms it once before any test starts.
"""

import difflib
import fcntl
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTABLE = ROOT / "executable"
RESOURCES = Path(__file__).resolve().parent.parent / "test_resources"
DEFAULT_TIMEOUT = 20

# One build cache for the whole suite. Its contents never reach any output.
GO_CACHE = Path(tempfile.gettempdir()) / "declscope-eval-gocache"

# A module header used by most fixtures.
GO_MOD = "module example.com/app\n\ngo 1.25\n"


def resources_for(test_file: str) -> Path:
    """eval/test_resources/<module>/ for the calling test module (pass __file__)."""
    return RESOURCES / Path(test_file).stem


COVERAGE_VARS = ("LLVM_PROFILE_FILE", "GOCOVERDIR")  # only set while measuring coverage


def go_env() -> dict[str, str]:
    """Settings for the go command declscope runs: offline, no toolchain switch, the shared cache."""
    return {
        "GOCACHE": str(GO_CACHE),
        "GOFLAGS": "-p=1",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOTOOLCHAIN": "local",
        "GONOSUMDB": "",
        "GOPRIVATE": "",
    }


def base_env(home: Path) -> dict[str, str]:
    """A fixed environment so outputs do not depend on the host."""
    passthrough = {k: os.environ[k] for k in COVERAGE_VARS if k in os.environ}
    if os.environ.get("SUITE_CHECK_AUDIT") == "1" and "PYTEST_CURRENT_TEST" in os.environ:  # argv audit only
        passthrough["PYTEST_CURRENT_TEST"] = os.environ["PYTEST_CURRENT_TEST"]
    return {
        **passthrough,
        **go_env(),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin") + ":/usr/local/go/bin",
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


# ----------------------------------------------------------------------------------------- cache warm-up
_WARM_FILES = {
    "go.mod": "module example.com/warm\n\ngo 1.25\n",
    "p/p.go": (
        "package p\n\nimport (\n\t\"bytes\"\n\t\"context\"\n\t\"encoding/json\"\n\t\"errors\"\n\t\"fmt\"\n"
        "\t\"io\"\n\t\"os\"\n\t\"reflect\"\n\t\"sort\"\n\t\"strconv\"\n\t\"strings\"\n\t\"sync\"\n\t\"time\"\n"
        "\t\"unsafe\"\n\n\t\"example.com/warm/internal/q\"\n)\n\n"
        "var _ = bytes.NewReader\nvar _ = context.Background\nvar _ = json.Marshal\nvar _ = errors.New\n"
        "var _ = fmt.Sprint\nvar _ = io.EOF\nvar _ = os.Getenv\nvar _ = reflect.TypeOf\nvar _ = sort.Strings\n"
        "var _ = strconv.Itoa\nvar _ = strings.ToLower\nvar _ sync.Mutex\nvar _ = time.Now\n"
        "var _ = unsafe.Sizeof(0)\nvar _ = q.Q\n"
    ),
    "p/p_test.go": "package p\n\nimport \"testing\"\n\nfunc TestP(t *testing.T) {}\n",
    "p/x_test.go": "package p_test\n\nimport \"testing\"\n\nfunc TestX(t *testing.T) {}\n",
    "internal/q/q.go": "package q\n\nfunc Q() {}\n",
}


def _warm_go_cache() -> None:
    """Compile the export data the fixtures need, once, under a lock shared by concurrent suites."""
    GO_CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="declscope-warm-") as tmp:
        home = Path(tmp) / "home"
        work = Path(tmp) / "work"
        home.mkdir()
        for rel, text in _WARM_FILES.items():
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        env = base_env(home)
        env.pop("GOCOVERDIR", None)
        env.pop("LLVM_PROFILE_FILE", None)
        with (GO_CACHE.parent / "declscope-eval-gocache.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            for cmd in (
                ["go", "list", "-e", "-compiled", "-export", "-deps", "-test", "-json", "./..."],
                ["go", "list", "-e", "-compiled", "-export", "-deps", "-json", "./..."],
            ):
                try:
                    subprocess.run(cmd, cwd=work, env=env, capture_output=True, timeout=900,
                                   stdin=subprocess.DEVNULL)
                except (OSError, subprocess.SubprocessError):
                    pass
            for args in (["./..."], ["-test=false", "./..."], ["shrink", "./..."]):
                try:
                    run_executable(args, cwd=work, env=env, timeout=900)
                except (OSError, subprocess.SubprocessError):
                    pass


def pytest_configure(config):
    # Only the controller warms the cache: xdist workers carry `workerinput`.
    if not hasattr(config, "workerinput"):
        _warm_go_cache()


# ----------------------------------------------------------------------------------------------- helpers
def write_tree(root: Path, files: dict[str, str]) -> None:
    """Write each relative path in `files` under root, creating directories."""
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _realign_table(block: list[str]) -> list[str]:
    """Re-pad one Markdown table the way the program pads it (cells padded to the widest, numeric columns
    right-aligned, rule rows of at least three dashes). Used only on tables whose width came from an
    absolute temporary path that was replaced by $WORK, so that the padding does not depend on it."""
    rows = [[c.strip() for c in _CELL_SPLIT.split(line)[1:-1]] for line in block]
    rule = rows[1] if len(rows) > 1 else []
    numeric = [c.endswith(":") for c in rule]
    body = [r for i, r in enumerate(rows) if i != 1]
    widths = [max(len(r[i]) for r in body if i < len(r)) for i in range(len(rule))]
    out = []
    for n, row in enumerate(body):
        line = ""
        for i, cell in enumerate(row):
            pad = " " * (widths[i] - len(cell))
            line += f"| {pad}{cell} " if numeric[i] else f"| {cell}{pad} "
        out.append(line + "|")
        if n == 0:
            line = ""
            for i, width in enumerate(widths):
                dashes = "-" * max(width, 3)
                line += f"| {dashes[:-1]}: " if numeric[i] else f"| {dashes} "
            out.append(line + "|")
    return out


def _realign_tables(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("|"):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].startswith("|"):
            j += 1
        block = lines[i:j]
        out.extend(_realign_table(block) if any("$WORK" in line for line in block) else block)
        i = j
    return "\n".join(out)


def normalize(text, workdir: Path | None = None) -> str:
    """Decode output and replace the absolute working directory with $WORK.

    A Markdown table that held the absolute path was padded to its length, which differs between runs,
    so such a table (and only such a table) is re-padded after the replacement."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if workdir is not None:
        real = os.path.realpath(workdir)
        for spelling in sorted({real, str(workdir)}, key=len, reverse=True):
            text = text.replace(spelling, "$WORK")
        if "$WORK" in text:
            text = _realign_tables(text)
    return text


def render_result(result: subprocess.CompletedProcess, workdir: Path | None = None) -> str:
    """Exit status, stdout and stderr of one run, in one text block."""
    return (f"[exit] {result.returncode}\n"
            f"[stdout]\n{normalize(result.stdout, workdir)}"
            f"[stderr]\n{normalize(result.stderr, workdir)}")


def _golden_compare(path: Path, actual: str) -> None:
    expected = path.read_text()
    if actual != expected:
        diff = "".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True),
                                            "expected", "actual"))
        raise AssertionError(f"output differs from {path.name}:\n{diff}")


def assert_golden(test_file: str, name: str, actual: str) -> None:
    """Assert `actual` == the content of test_resources/<module>/<name>.golden."""
    _golden_compare(resources_for(test_file) / f"{name}.golden", actual)


def assert_run_golden(test_file: str, name: str, result: subprocess.CompletedProcess,
                      workdir: Path | None = None) -> None:
    """Assert the exit status, stdout and stderr of a run all equal the golden file."""
    _golden_compare(resources_for(test_file) / f"{name}.golden", render_result(result, workdir))


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


@pytest.fixture
def tree(workdir: Path):
    """tree({path: text}) writes files under the working directory."""

    def _tree(files: dict[str, str]) -> Path:
        write_tree(workdir, files)
        return workdir

    return _tree
