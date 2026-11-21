"""Shared fixtures for the hidden behavioural test suite.

Every test treats ./executable (the workspace root) as a black box: run it as a
subprocess and assert on stdout, stderr, exit code and the files it writes.
Expected outputs that were captured from the reference program live under
eval/test_resources/<test module name>/, or in one file per module,
eval/test_resources/<test module name>.bundle.json.gz (see resources_for).
"""

import functools
import gzip
import io
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
EXECUTABLE = ROOT / "executable"
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


class BundledPath:
    """A path inside one module's resource bundle, eval/test_resources/<module>.bundle.json.gz: every file of the
    module's resource directory keyed by its relative path, in one read-only file of the grader's eval/ tree (the
    core-behavior modules carry about 20,000 resource files; one file each keeps the task small). It answers the
    reads the tests make with pathlib's results: `/`, read_bytes(), and read_text() in text mode (newlines translated
    as Path.read_text translates them)."""

    def __init__(self, files: dict[str, str], rel: str = ""):
        self._files, self._rel = files, rel

    def __truediv__(self, name) -> "BundledPath":
        return BundledPath(self._files, f"{self._rel}/{name}" if self._rel else str(name))

    def __repr__(self) -> str:
        return f"BundledPath({self._rel!r})"

    def is_file(self) -> bool:
        return self._rel in self._files

    def exists(self) -> bool:
        return self.is_file() or any(k.startswith(f"{self._rel}/") for k in self._files)

    def read_bytes(self) -> bytes:
        if self._rel not in self._files:
            raise FileNotFoundError(f"{self._rel}: not in the module's resource bundle")
        return self._files[self._rel].encode("utf-8")

    def read_text(self, encoding: str | None = None, errors: str | None = None) -> str:
        return io.TextIOWrapper(io.BytesIO(self.read_bytes()), encoding=encoding, errors=errors).read()


@functools.lru_cache(maxsize=None)
def _bundle(path: Path) -> dict[str, str]:
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def resources_for(test_file: str):
    """eval/test_resources/<module>/ for the calling test module (pass __file__): the module's directory when it has
    one, else its bundle eval/test_resources/<module>.bundle.json.gz, read the same way."""
    stem = Path(test_file).stem
    directory, bundle = RESOURCES / stem, RESOURCES / f"{stem}.bundle.json.gz"
    if not directory.exists() and bundle.is_file():
        return BundledPath(_bundle(bundle))
    return directory


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


# ---------------------------------------------------------------------------
# Helpers shared by the core-behaviour modules.
# ---------------------------------------------------------------------------

def read_golden(test_file: str, name: str) -> str:
    """Text of eval/test_resources/<module>/<name>.golden (captured from the reference binary)."""
    return (resources_for(test_file) / f"{name}.golden").read_bytes().decode("utf-8")


def write_files(root: Path, files: dict[str, str]) -> None:
    """Create each relative path under `root` with the given UTF-8 text."""
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))


def transcript(proc: subprocess.CompletedProcess) -> str:
    """One string holding exit code, stdout and stderr, the shape every *.golden transcript uses."""
    return (
        f"exit: {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout.decode('utf-8', 'replace')}"
        f"--- stderr ---\n{proc.stderr.decode('utf-8', 'replace')}"
    )


def case_transcript(proc: subprocess.CompletedProcess, case: dict, workdir: Path | None = None) -> str:
    """`transcript(proc)` with the case's `normalize` (regex, replacement) pairs applied.

    Used only where an output embeds a volatile part (such as the temporary staging
    directory in a Python traceback); everything else is compared verbatim. An LSP
    case (one with an `lsp` message list) is rendered with `lsp_transcript`.
    """
    text = lsp_transcript(proc, workdir) if "lsp" in case else transcript(proc)
    for pattern, repl in case.get("normalize", []):
        text = re.sub(pattern, repl, text)
    return text


def golden_name(case_id: str, output: str | None = None) -> str:
    """Golden file stem for a case transcript, or for a file the case's command writes."""
    return case_id if output is None else f"{case_id}__{output.replace('/', '__')}"


def run_case(run, workdir: Path, case: dict) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    """Materialise a case's input files, run its command, and collect the files it should write.

    A case is a dict with `id`, `files` ({relative path: text}), `args`, and optionally
    `bytes` ({relative path: raw bytes}), `setup` (argument lists run first),
    `stdin` (text), `cwd` (a subdirectory of the workdir to run in), `executables`
    (relative paths to mark executable), `env` (overrides; `{workdir}` expands to the
    absolute working directory and `{PATH}` to the inherited search path) and `outputs` (relative paths the command creates).
    """
    write_files(workdir, case.get("files", {}))
    for rel, data in case.get("bytes", {}).items():
        (workdir / rel).write_bytes(data)
    for rel in case.get("executables", []):
        (workdir / rel).chmod(0o755)
    env = {k: v.replace("{workdir}", str(workdir)).replace("{PATH}", os.environ.get("PATH", ""))
           for k, v in case.get("env", {}).items()}
    cwd = workdir / case["cwd"] if "cwd" in case else None
    for setup_args in case.get("setup", []):  # earlier commands whose effects the case builds on
        run(setup_args, cwd=cwd, env_overrides=env)
    stdin = case.get("stdin")
    if "lsp" in case:
        stdin = lsp_input(case["lsp"], workdir)
    proc = run(case["args"], input=stdin, cwd=cwd, env_overrides=env)
    written = {}
    for rel in case.get("outputs", []):
        p = workdir / rel
        written[rel] = p.read_bytes().decode("utf-8") if p.is_file() else "<missing>"
    return proc, written


def listing(root: Path) -> str:
    """Sorted relative paths of every file under `root` (directories end with '/')."""
    lines = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        lines.append(rel + "/" if p.is_dir() else rel)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Language-server sessions (`pyfun lsp`): Content-Length framed JSON-RPC over stdio.
# ---------------------------------------------------------------------------

def root_uri(workdir: Path) -> str:
    """The `file://` URI of the working directory (no trailing slash)."""
    return "file://" + str(workdir)


def _substitute(value, root: str):
    if isinstance(value, str):
        return value.replace("{root}", root)
    if isinstance(value, list):
        return [_substitute(v, root) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, root) for k, v in value.items()}
    return value


def lsp_frame(body: bytes) -> bytes:
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


def lsp_input(messages, workdir: Path) -> bytes:
    """Frame each message; a message is a JSON-able object (`{root}` in any string expands
    to the workdir's URI) or raw `bytes` sent verbatim (to exercise the framing itself)."""
    root = root_uri(workdir)
    out = b""
    for m in messages:
        if isinstance(m, bytes):
            out += m
        else:
            out += lsp_frame(json.dumps(_substitute(m, root), ensure_ascii=False).encode("utf-8"))
    return out


def lsp_messages(stream: bytes) -> list:
    """Split the server's stdout into its framed JSON bodies (the frame lengths are
    checked: a body must be exactly Content-Length bytes)."""
    messages = []
    while stream:
        header_end = stream.index(b"\r\n\r\n")
        header = stream[:header_end].decode("ascii")
        length = int(header.split("Content-Length:")[1].strip())
        body = stream[header_end + 4:header_end + 4 + length]
        assert len(body) == length, "truncated frame"
        messages.append(json.loads(body.decode("utf-8")))
        stream = stream[header_end + 4 + length:]
    return messages


def lsp_transcript(proc: subprocess.CompletedProcess, workdir: Path | None) -> str:
    """Exit code, each server message pretty-printed (key order as sent), and stderr.
    The working directory's absolute URI is replaced by `{root}` so goldens are portable."""
    msgs = lsp_messages(proc.stdout)
    body = "".join(json.dumps(m, ensure_ascii=False, indent=1) + "\n" for m in msgs)
    if workdir is not None:
        body = body.replace(root_uri(workdir), "{root}").replace(str(workdir), "{root-path}")
    return (f"exit: {proc.returncode}\n--- messages ---\n{body}"
            f"--- stderr ---\n{proc.stderr.decode('utf-8', 'replace')}")


def pytest_collection_modifyitems(config, items):
    """pytest's per-test limit (eval/run.sh --timeout) scales like every other limit; untouched on native hardware."""
    if TIME_SCALE == 1.0:
        return
    base = config.getoption("timeout", None) or 30
    for item in items:
        item.add_marker(pytest.mark.timeout(base * TIME_SCALE))
