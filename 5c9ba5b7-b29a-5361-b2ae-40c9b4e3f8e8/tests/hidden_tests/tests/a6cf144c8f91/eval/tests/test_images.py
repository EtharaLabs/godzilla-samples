"""`|image|` assets (SPEC 7/18): local SVG and raster files embed (SVG ids
prefixed, rasters base64), URLs and data: URIs pass through, paths resolve
against the source file's directory, and --no-fs refuses every local read."""

import shutil

import pytest

from conftest import Goldens, outcome, resources_for, write_files

R = resources_for(__file__)
G = Goldens(__file__)

LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4f8bd8"/>
      <stop offset="1" stop-color="#7fd8c8"/>
    </linearGradient>
    <circle id="dot" r="4"/>
  </defs>
  <rect x="4" y="4" width="40" height="40" rx="10" fill="url(#g)"/>
  <use href="#dot" x="17" y="24" fill="#fff"/>
  <use href="#dot" x="31" y="24" fill="#fff"/>
</svg>
"""

TRICKY_SVG = """﻿<?xml version="1.0" encoding="UTF-8"?>
<!-- a comment before the root -->
<!DOCTYPE svg>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="30" height="20" id="root" class='kept'>
  <style><![CDATA[ .a { fill: url(#pat); } #shape { stroke: red; } ]]></style>
  <defs><pattern id="pat" width="4" height="4"><rect width='2' height=2 /></pattern></defs>
  <rect id="shape" class="a" width="30" height="20" style="filter: url(#nope); fill: url(#pat)"/>
  <use xlink:href="#shape" href="other.svg#shape"/>
  <a href="#root"><text>hi &amp; bye</text></a>
</svg>
"""

IMAGES = '|image| { src: "mark.png"; width: 40; height: 40; }\n|image| { src: "logo.svg"; width: 60; height: 30; fit: contain; }\n'


def stage(workdir, files):
    write_files(workdir, files)
    shutil.copy(R / "mark.png", workdir / "mark.png")


def test_local_png_and_svg_embed(run, workdir):
    """CATCHES: a PNG not inlined as a base64 data URI, or an SVG asset not nested with its ids/refs prefixed by the content hash."""
    stage(workdir, {"logo.svg": LOGO, "i.lini": IMAGES})
    r = run(["i.lini"])
    assert outcome(r) == G("embed_png_svg")


def test_stdin_resolves_against_cwd(run, workdir):
    """CATCHES: stdin input resolving image paths anywhere but the working directory."""
    stage(workdir, {"logo.svg": LOGO})
    r = run(["-"], input=IMAGES)
    assert outcome(r) == G("embed_png_svg")


def test_paths_resolve_against_source_directory(run, workdir):
    """CATCHES: image paths resolved against the cwd instead of the .lini file's own directory."""
    write_files(workdir, {"sub/i.lini": IMAGES, "sub/logo.svg": LOGO})
    shutil.copy(R / "mark.png", workdir / "sub" / "mark.png")
    stage(workdir, {})
    r = run(["sub/i.lini"])
    assert outcome(r) == G("embed_png_svg")


def test_missing_relative_to_source_dir(run, workdir):
    """CATCHES: a missing image (relative to the source dir) not reported at the src: span with 'no such file'."""
    stage(workdir, {"logo.svg": LOGO, "sub/i.lini": IMAGES})
    r = run(["sub/i.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\nsub/i.lini:1:11: error: cannot read image 'mark.png' — no such file\n"


def test_no_fs_refuses_local_image(run, workdir):
    """CATCHES: --no-fs still reading a local image instead of the asset-no-fs error."""
    stage(workdir, {"logo.svg": LOGO, "i.lini": IMAGES})
    r = run(["--no-fs", "i.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\ni.lini:1:11: error: cannot read image 'mark.png' — local files are off (--no-fs); use an http(s) URL or a data: URI\n"


def test_no_fs_json_code(run, workdir):
    """CATCHES: the --no-fs image refusal carrying a wrong JSON code/family (R024 asset-no-fs)."""
    stage(workdir, {"i.lini": IMAGES})
    r = run(["--no-fs", "--json", "i.lini"])
    assert outcome(r) == G("no_fs_json")


def test_no_fs_allows_urls(run):
    """CATCHES: --no-fs rejecting http(s) URLs or data: URIs, which never touch the disk."""
    src = '|image| { src: "HTTPS://example.com/a.png"; width: 20; height: 20; }\n|image| { src: "data:image/svg+xml;utf8,<svg/>"; width: 20; height: 20; }\n|image| { src: "http://x.test/b.jpg"; width: 10; height: 30; fit: stretch; }\n'
    r = run(["--no-fs", "-"], input=src)
    assert outcome(r) == G("no_fs_urls")


def test_svg_rewrite_edge_cases(run, workdir):
    """CATCHES: an SVG embedder that mishandles a BOM, prolog, comment or doctype, CDATA <style> url() refs, unquoted/single-quoted attributes, xlink:href, external fragments, or a root without viewBox."""
    write_files(workdir, {"t.svg": TRICKY_SVG})
    r = run(["-"], input='|image| { src: "t.svg"; width: 60; height: 40; fit: cover; }\n')
    assert outcome(r) == G("svg_tricky")


def test_self_closing_svg(run, workdir):
    """CATCHES: a self-closing root <svg .../> rejected or embedded with stray content."""
    write_files(workdir, {"e.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>'})
    r = run(["-"], input='|image| { src: "e.svg"; width: 20; height: 20; }\n')
    assert outcome(r) == G("svg_self_closing")


def test_unclosed_svg_errors(run, workdir):
    """CATCHES: an SVG asset without a closing tag accepted instead of 'cannot read image ... — unclosed <svg>'."""
    write_files(workdir, {"u.svg": '<svg xmlns="http://www.w3.org/2000/svg"><rect/>'})
    r = run(["-"], input='|image| { src: "u.svg"; width: 20; height: 20; }\n')
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\n<stdin>:1:11: error: cannot read image 'u.svg' — unclosed <svg>\n"


def test_unknown_format_errors(run, workdir):
    """CATCHES: arbitrary bytes embedded as an image instead of the 'not an SVG or raster' error."""
    write_files(workdir, {"notes.txt": "just some text, not an image\n"})
    r = run(["-"], input='|image| { src: "notes.txt"; width: 20; height: 20; }\n')
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\n<stdin>:1:11: error: cannot read image 'notes.txt' — not an SVG or raster (PNG/JPEG/GIF/WebP)\n"


@pytest.mark.parametrize("name,data", [
    ("jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"),
    ("gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"),
    ("webp", b"RIFF\x0c\x00\x00\x00WEBPVP8 "),
])
def test_raster_kinds_sniffed_by_magic(run, workdir, name, data):
    """CATCHES: raster MIME chosen by file extension instead of magic bytes (each file here has a misleading .bin name)."""
    write_files(workdir, {"pic.bin": data})
    r = run(["-"], input='|image| { src: "pic.bin"; width: 16; height: 16; }\n')
    assert outcome(r) == G(f"raster_{name}")


def test_image_fit_modes(run, workdir):
    """CATCHES: wrong preserveAspectRatio / viewBox mapping for fit auto, contain, cover and stretch."""
    stage(workdir, {"logo.svg": LOGO})
    src = "".join(f'|image| {{ src: "{f}"; width: 50; height: 20; fit: {m}; }}\n' for f in ("logo.svg", "mark.png") for m in ("auto", "contain", "cover", "stretch"))
    r = run(["-"], input=src)
    assert outcome(r) == G("fit_modes")


def test_same_asset_twice_shares_prefix(run, workdir):
    """CATCHES: an asset embedded twice with different id prefixes (the prefix derives from the bytes, so both copies must agree)."""
    write_files(workdir, {"logo.svg": LOGO, "copy.svg": LOGO})
    r = run(["--static", "-"], input='|image| { src: "logo.svg"; width: 20; height: 20; }\n|image| { src: "copy.svg"; width: 30; height: 30; }\n')
    assert outcome(r) == G("shared_prefix_static")


def test_image_in_drawing_sheet(run, workdir):
    """CATCHES: an image inside a title-block cell (the documented logo recipe) placed or embedded differently."""
    write_files(workdir, {"logo.svg": LOGO})
    src = '|page| { sheet: a5; } [\n  |drawing| [ |rect| { width: 40; height: 20; } ]\n  |title-block| { title: "Logo test"; drawing-number: "L-1"; } [ |image| { src: "logo.svg"; cell: 3 3; width: 12; height: 12; } ]\n]\n'
    r = run(["-"], input=src)
    assert outcome(r) == G("title_block_logo")
