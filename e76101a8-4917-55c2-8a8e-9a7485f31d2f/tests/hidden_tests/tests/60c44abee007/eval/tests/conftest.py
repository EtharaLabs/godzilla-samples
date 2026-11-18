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
# Helpers shared by the behavioural tests.
# ---------------------------------------------------------------------------

import hashlib
import json
import re
import struct
import zlib

# A GUID as the program writes it (8-4-4-4-12 lowercase hex). GUIDs are random per run.
GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# An IFC GlobalId: 22 characters of IFC's base64 alphabet, as a quoted STEP string or a JSON "ifc" value.
IFC_GLOBALID_STEP_RE = re.compile(r"'[0-9A-Za-z_$]{22}'")
IFC_GLOBALID_JSON_RE = re.compile(r'"ifc": ?"[0-9A-Za-z_$]{22}"')
# The project's own random 64-bit uid in a .bimcraft file.
UID_RE = re.compile(r'"uid": ?\d+')
# The timestamp IFC's FILE_NAME header carries.
IFC_STAMP_RE = re.compile(r"FILE_NAME\('((?:[^']|'')*)','\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d'")
# A number printed with nine or more decimals: the tail of sines, cosines and square roots, whose last bits a system's maths
# library may round differently on another processor. Rounded to six decimals (a micrometre of a millimetre).
LONG_FLOAT_RE = re.compile(r"(?<![\w.])-?\d+\.\d{9,}(?:[eE][-+]?\d+)?(?![\w.])")


def round_long_floats(text: str) -> str:
    """Numbers with nine or more decimals rounded to six (and -0.0 to 0.0), so trig noise stays out of comparisons."""
    return LONG_FLOAT_RE.sub(lambda m: repr(round(float(m.group(0)), 6) + 0.0), text)


def normalize_guids(text: str) -> str:
    """Replace each distinct GUID with <GUID-n>, numbered by first appearance, so equal GUIDs stay equal."""
    seen: dict[str, str] = {}

    def sub(m):
        return seen.setdefault(m.group(0), f"<GUID-{len(seen) + 1}>")

    return GUID_RE.sub(sub, text)


def normalize(text: str) -> str:
    """Normalise every random part of the program's output: GUIDs, IFC GlobalIds, project uids, IFC timestamps."""
    text = normalize_guids(text)
    seen: dict[str, str] = {}

    def gid(m):
        return seen.setdefault(m.group(0), f"'<GID-{len(seen) + 1}>'")

    text = IFC_GLOBALID_STEP_RE.sub(gid, text)
    seen_json: dict[str, str] = {}

    def gid_json(m):
        return seen_json.setdefault(m.group(0), f'"ifc":"<GID-{len(seen_json) + 1}>"')

    text = IFC_GLOBALID_JSON_RE.sub(gid_json, text)
    text = UID_RE.sub('"uid":<UID>', text)
    text = IFC_STAMP_RE.sub(r"FILE_NAME('\1','<STAMP>'", text)
    return round_long_floats(text)


def out(proc) -> str:
    """stdout as text."""
    return proc.stdout.decode()


def err(proc) -> str:
    """stderr as text."""
    return proc.stderr.decode()


def read_golden(test_file: str, name: str) -> str:
    return (resources_for(test_file) / name).read_text(encoding="utf-8")


def png_pixels(data: bytes) -> tuple[int, int, str, str]:
    """Decode a PNG (8-bit RGB/RGBA/grey, non-interlaced) to (width, height, colour type, sha256 of the raw pixels)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    assert ihdr is not None, "no IHDR"
    width, height, depth, ctype, _, _, interlace = ihdr
    assert depth == 8 and interlace == 0, f"unsupported PNG depth {depth} interlace {interlace}"
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = width * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        rows.append(bytes(line))
        prev = line
    names = {0: "grey", 2: "rgb", 4: "grey-alpha", 6: "rgba"}
    return width, height, names[ctype], hashlib.sha256(b"".join(rows)).hexdigest()


def glb_parts(data: bytes) -> tuple[dict, str]:
    """A .glb file as (its JSON chunk, sha256 of its binary chunk)."""
    magic, version, total = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and version == 2 and total == len(data), "not a glTF 2.0 binary"
    (jlen, jtype) = struct.unpack("<II", data[12:20])
    assert jtype == 0x4E4F534A
    doc = json.loads(data[20:20 + jlen])
    rest = data[20 + jlen:]
    binary = b""
    if rest:
        (blen, btype) = struct.unpack("<II", rest[:8])
        assert btype == 0x004E4942
        binary = rest[8:8 + blen]
    return doc, hashlib.sha256(binary).hexdigest()


# ---------------------------------------------------------------------------
# Scenario: run steps, record a transcript (exit code, stdout, stderr, files written) and compare it with a golden file.
# ---------------------------------------------------------------------------

import shlex

IFC_REL_RE = re.compile(r"^#\d+=(IFCREL[A-Z]+)\((.*)\);$")
REF_LIST_RE = re.compile(r"\((#\d+(?:,#\d+)*)\)")


def canonical_ifc(text: str) -> str:
    """An IFC (STEP) file in a form that is the same every run: GlobalIds and the header's timestamp replaced, and the
    relationship entities, which the program writes in an order that follows random GUIDs, sorted within each run of them
    (their entity numbers dropped and the lists of references in them sorted)."""
    text = IFC_STAMP_RE.sub(r"FILE_NAME('\1','<STAMP>'", text)
    text = IFC_GLOBALID_STEP_RE.sub("'<GID>'", text)
    lines, block, result = text.split("\n"), [], []

    def flush():
        result.extend(sorted(block))
        block.clear()

    for line in lines:
        m = IFC_REL_RE.match(line)
        if m:
            body = REF_LIST_RE.sub(lambda r: "(" + ",".join(sorted(r.group(1).split(","), key=lambda s: int(s[1:]))) + ")", m.group(2))
            block.append(f"#?={m.group(1)}({body});")
        else:
            flush()
            result.append(line)
    flush()
    return "\n".join(result)


PDF_OBJ_START_RE = re.compile(rb"(?<![0-9])(\d+) 0 obj\b")


def canonical_pdf(data: bytes) -> str:
    """A PDF as its objects in file order, each stream decompressed and given as its length and sha256 (the byte offsets of
    the cross-reference table left out, since they follow how the streams compress)."""
    assert data.startswith(b"%PDF-"), "not a PDF"
    lines = [data.split(b"\n", 1)[0].decode()]
    pos = 0
    while True:
        m = PDF_OBJ_START_RE.search(data, pos)
        if not m:
            break
        num, body_start = m.group(1).decode(), m.end()
        s_at = data.find(b"stream", body_start)
        e_at = data.find(b"endobj", body_start)
        if s_at != -1 and s_at < e_at:
            head = data[body_start:s_at]
            length = re.search(rb"/Length (\d+)", head)
            start = s_at + len(b"stream")
            start += 2 if data[start:start + 2] == b"\r\n" else 1
            if length:
                stream = data[start:start + int(length.group(1))]
            else:
                stream = data[start:data.find(b"endstream", start)].rstrip(b"\r\n")
            pos = data.find(b"endobj", start + len(stream)) + len(b"endobj")
            if b"/FlateDecode" in head:
                stream = zlib.decompress(stream)
            head = re.sub(rb"/Length \d+", b"/Length *", head).strip()
            lines.append(f"obj {num}: {head.decode('latin-1')} stream[{len(stream)}] sha256={hashlib.sha256(stream).hexdigest()}")
        else:
            lines.append(f"obj {num}: {data[body_start:e_at].strip().decode('latin-1')}")
            pos = e_at + len(b"endobj")
    tail = data[data.rfind(b"trailer"):] if b"trailer" in data else b""
    trailer = re.sub(rb"startxref\s+\d+", b"startxref *", tail)
    lines.append(trailer.decode("latin-1").strip())
    return "\n".join(lines)


def zip_entries(data: bytes) -> list[tuple[str, bytes]]:
    """The entries of a zip file (an .xlsx), in the order they are stored."""
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [(i.filename, z.read(i.filename)) for i in z.infolist()]


TEXT_SUFFIXES = {".svg", ".ifc", ".json", ".txt", ".csv", ".pat", ".dxf", ".bimcraft", ".xml", ".md"}


def describe_file(path: Path, *, digest: bool = False) -> str:
    """What a file the program wrote holds, as text a golden can keep."""
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".png":
        w, h, kind, sha = png_pixels(data)
        return f"png {w}x{h} {kind} pixels-sha256={sha}"
    if suffix == ".glb":
        doc, sha = glb_parts(data)
        return json.dumps(doc, indent=1, ensure_ascii=False) + f"\nbin-sha256={sha}"
    if suffix == ".pdf":
        return canonical_pdf(data)
    if suffix == ".xlsx":
        parts = []
        for name, body in zip_entries(data):
            parts.append(f"[{name}]\n{body.decode('utf-8')}")
        return "\n".join(parts)
    if suffix in TEXT_SUFFIXES:
        text = data.decode("utf-8")
        if suffix == ".ifc":
            text = canonical_ifc(text)
        if digest:
            norm = normalize(text).encode()
            return f"normalised: {len(norm)} bytes, sha256={hashlib.sha256(norm).hexdigest()}"
        return text
    return f"{len(data)} bytes sha256={hashlib.sha256(data).hexdigest()}"


PNG_B64_RE = re.compile(r'"pngBase64":"([A-Za-z0-9+/=]*)"')


def png_b64_description(b64: str) -> str:
    """An inline base64 PNG (a render with no path) as its size and pixel digest."""
    import base64

    w, h, kind, sha = png_pixels(base64.b64decode(b64))
    return f"<png {w}x{h} {kind} pixels-sha256={sha}>"


class Scenario:
    """Steps run in the test's working directory, their transcript compared with `<module>/<name>.golden`.

    sc.write(path, content) puts an input file in place; sc.run(args, input=...) runs the program and records its exit
    code, stdout and stderr; sc.file(path) records what a file it wrote holds; sc.note(text) records a line;
    sc.transcript() is the whole transcript, normalised (GUIDs numbered by first appearance), and sc.golden() the expected one.
    """

    def __init__(self, run, workdir: Path, test_file: str, name: str):
        self._run, self.workdir, self.test_file, self.name = run, workdir, test_file, name
        self.parts: list[str] = []

    def write(self, path: str, content) -> Path:
        p = self.workdir / path
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            p.write_text(content, encoding="utf-8")
        else:
            p.write_bytes(content)
        return p

    def run(self, args, *, input=None, cwd=None, show: bool = True):
        args = [str(a) for a in args]
        p = self._run(args, input=input, cwd=cwd)
        if show:
            self.parts.append(f"$ bimcraft-cli {shlex.join(args)}")
            self.parts.append(f"[exit {p.returncode}]")
            self.parts.append("--- stdout")
            self.parts.append(p.stdout.decode("utf-8", "replace"))
            self.parts.append("--- stderr")
            self.parts.append(p.stderr.decode("utf-8", "replace"))
        return p

    def cmds(self, *commands: str, pre=(), post=()):
        """`run [pre…] --cmd C1 --cmd C2 … [post…]`."""
        args = ["run", *pre]
        for c in commands:
            args += ["--cmd", c]
        return self.run([*args, *post])

    def file(self, path: str, *, digest: bool = False):
        p = self.workdir / path
        self.parts.append(f"=== file {path}")
        self.parts.append(describe_file(p, digest=digest) if p.exists() else "(missing)")

    def files(self):
        """Every file in the working directory, by name, so what was written (and nothing else) is checked (what a
        coverage build of the program drops there, `*.profraw`, left out)."""
        names = sorted(str(p.relative_to(self.workdir)) for p in self.workdir.rglob("*")
                       if p.is_file() and p.suffix != ".profraw")
        self.parts.append("=== files: " + ", ".join(names))

    def note(self, text: str):
        self.parts.append(text)

    def transcript(self) -> str:
        text = "\n".join(self.parts)
        text = PNG_B64_RE.sub(lambda m: '"pngBase64":"' + png_b64_description(m.group(1)) + '"', text)
        home = str(self.workdir.parent / "home")
        text = text.replace(str(self.workdir), "<WORKDIR>").replace(home, "<HOME>")
        return normalize(text) + "\n"

    def golden_path(self) -> Path:
        return resources_for(self.test_file) / f"{self.name}.golden"

    def golden(self) -> str:
        """The expected transcript: tests assert `sc.transcript() == sc.golden()`."""
        return self.golden_path().read_text(encoding="utf-8")


@pytest.fixture
def sc(run, workdir, request):
    """A Scenario for this test, its golden named after the test (parameters included)."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name).strip("_")
    return Scenario(run, workdir, str(request.node.fspath), name)
