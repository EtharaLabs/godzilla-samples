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
DEFAULT_TIMEOUT = 200


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
    """run(args, input=None, cwd=None, env_overrides=None, timeout=200) -> CompletedProcess (cwd defaults to workdir)."""

    def _run(args, *, input=None, cwd=None, env_overrides=None, timeout=DEFAULT_TIMEOUT):
        return run_executable(args, input=input, cwd=cwd or workdir, env={**env, **(env_overrides or {})}, timeout=timeout)

    return _run


# ---------------------------------------------------------------------------
# Normalisation of the parts of an output that are random by design, and
# comparison against golden files captured from the reference program.
# ---------------------------------------------------------------------------

import hashlib
import json
import re
import struct
import zlib

# An element's GUID is a random version 4 UUID: numbered in order of first appearance, so references between elements
# still have to match.
GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# IFC GlobalIds (the first attribute of every IfcRoot entity) are the GUIDs compressed to 22 characters.
IFC_GLOBALID_RE = re.compile(r"(=IFC[A-Z0-9]+\()'[0-9A-Za-z_$]{22}'")
# The time an IFC file was written, in its FILE_NAME header.
IFC_STAMP_RE = re.compile(r"^(FILE_NAME\('[^']*',)'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d'", re.M)
# A project's random uid, in a .bimcraft file.
UID_RE = re.compile(r'("uid": ?)\d+')


# A decimal number as the program prints one (with a point or an exponent).
NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+(?:[eE][-+]?\d+)?|[eE][-+]?\d+)(?![\w.])")


def _portable_number(m: re.Match) -> str:
    """A number with 13 or more significant digits rounded to 12, and one of those that is only rounding noise (an
    exponent form under 1e-6, such as 500 * cos(90°)) shown as <~0>.

    Such numbers come from the platform's sin, cos and atan2, whose last bit may differ between x86-64 and arm64; every
    shorter number, and all twelve leading digits of a long one, are compared exactly."""
    s = m.group(0)
    mantissa = re.split("[eE]", s)[0].lstrip("-").replace(".", "")
    if len(mantissa.strip("0")) < 13:
        return s
    x = float(s)
    if ("e" in s or "E" in s) and abs(x) < 1e-6:
        return "<~0>"
    rounded = f"{x:.12g}"
    return rounded if any(c in rounded for c in ".e") else rounded + ".0"


def normalize(text: str) -> str:
    """The text with each random identifier replaced by a stable placeholder (numbered by first appearance), and the
    last digits of long floating-point numbers rounded off (see `_portable_number`)."""
    guids: dict[str, str] = {}
    text = GUID_RE.sub(lambda m: guids.setdefault(m.group(0), f"GUID-{len(guids) + 1}"), text)
    gids: dict[str, str] = {}
    text = IFC_GLOBALID_RE.sub(lambda m: m.group(1) + "'" + gids.setdefault(m.group(0), f"GID-{len(gids) + 1}") + "'", text)
    text = IFC_STAMP_RE.sub(lambda m: m.group(1) + "'<TIMESTAMP>'", text)
    text = UID_RE.sub(lambda m: m.group(1) + "<UID>", text)
    return NUMBER_RE.sub(_portable_number, text)


def png_pixels(data: bytes) -> str:
    """A PNG described by its header and a digest of its decoded pixels (independent of how it was compressed)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", data[:16]
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    width, height, depth, colour, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    bpp = max(1, channels * depth // 8)
    stride = (width * channels * depth + 7) // 8
    raw = zlib.decompress(idat)
    out = bytearray()
    prev = bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    digest = hashlib.sha256(bytes(out)).hexdigest()
    return f"PNG {width}x{height} depth={depth} colour={colour} interlace={interlace} pixels={digest}\n"


def glb_summary(data: bytes) -> str:
    """A binary glTF as its normalised JSON chunk and a digest of its binary chunk."""
    magic, version, length = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and length == len(data), data[:12]
    pos, parts = 12, [f"glTF version={version}"]
    while pos < len(data):
        size, kind = struct.unpack("<I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        if kind == b"JSON":
            parts.append(normalize(json.dumps(json.loads(body), indent=1, sort_keys=True)))
        else:
            parts.append(f"{kind.decode()} {size} bytes sha256={hashlib.sha256(body).hexdigest()}")
        pos += 8 + size
    return "\n".join(parts) + "\n"


PDF_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def pdf_summary(data: bytes) -> str:
    """A PDF with its compressed streams inflated, and the lengths and offsets that depend on the compression dropped."""
    def inflate(m):
        body = m.group(1)
        try:
            body = zlib.decompress(body)
        except zlib.error:
            pass
        return b"stream\n" + hashlib.sha256(body).hexdigest().encode() + b" " + str(len(body)).encode() + b"\nendstream"

    text = PDF_STREAM_RE.sub(inflate, data)
    text = re.sub(rb"/Length \d+", b"/Length N", text)
    text = re.sub(rb"xref.*?trailer", b"xref ... trailer", text, flags=re.S)
    text = re.sub(rb"startxref\s+\d+", b"startxref N", text)
    return text.decode("latin-1")


class Golden:
    """The expected outputs of one test module, in eval/test_resources/<module>/."""

    def __init__(self, test_file: str):
        self.dir = resources_for(test_file)

    def read(self, name: str) -> str:
        return (self.dir / name).read_text(encoding="utf-8")

    def check(self, actual: str, name: str) -> None:
        expected = self.read(name)
        assert actual == expected, f"{name}: output differs from the golden file"

    def check_run(self, r: subprocess.CompletedProcess, name: str) -> None:
        """Exit code, normalised stdout and stderr, all at once."""
        actual = (f"exit: {r.returncode}\n--- stdout\n" + normalize(r.stdout.decode("utf-8", "replace"))
                  + "--- stderr\n" + normalize(r.stderr.decode("utf-8", "replace")))
        self.check(actual, name)


@pytest.fixture
def golden(request) -> Golden:
    return Golden(str(request.fspath))


def mcp_lines(messages) -> str:
    """MCP messages (dicts or raw strings) as the lines a client writes to the server's stdin."""
    return "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)


def fix_guids(path: Path) -> None:
    """Give every GUID in a saved project a fixed value, in order of first appearance, and fix its uid.

    Some exports order what they write by GUID (IFC storeys, for one), so a project made by the program, whose GUIDs are
    random, is made deterministic this way before it is exported."""
    text = path.read_text(encoding="utf-8")
    seen: dict[str, str] = {}

    def fixed(m):
        n = len(seen) + 1
        return seen.setdefault(m.group(0), f"{0x10000000 + n:08x}-{n % 0x10000:04x}-4000-8000-{n:012x}")

    text = GUID_RE.sub(fixed, text)
    text = UID_RE.sub(lambda m: m.group(1) + "1234567890123", text)
    path.write_text(text, encoding="utf-8")


def make_project(run, workdir: Path, name: str, args) -> Path:
    """`run ARGS --save NAME` in the working directory, then the project's GUIDs fixed (see `fix_guids`)."""
    r = run(["run", *args, "--save", name])
    assert r.returncode == 0, r.stderr.decode()
    fix_guids(workdir / name)
    return workdir / name
