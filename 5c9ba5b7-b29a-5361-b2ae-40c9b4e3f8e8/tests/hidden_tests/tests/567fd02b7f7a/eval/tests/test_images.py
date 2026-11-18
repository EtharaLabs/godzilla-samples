"""`|image|` assets [SPEC 7/18] as the CLI sees them: local paths resolved
against the input's directory and embedded (SVG nested with ids isolated,
rasters as data URIs), URLs passed through, and `--no-fs` refusing reads."""

import pytest

from conftest import Case

SVG_ASSET = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<!-- a tiny logo -->\n"
    '<!DOCTYPE svg>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10" width="10" height="10">\n'
    '  <defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient>\n'
    '  <style><![CDATA[ .a { fill: url(#g); } ]]></style></defs>\n'
    '  <rect id="r" class="a" width="10" height="10" fill="url(#g)" style="stroke: url(#g)"/>\n'
    '  <use href="#r"/><use xlink:href="#r" x=\'2\'/>\n'
    "</svg>\n"
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(range(32))
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(16))
GIF = b"GIF89a" + bytes(range(10))
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + bytes(range(8))


def img(src, extra=""):
    return '|image| { src: "%s"; width: 40; height: 30;%s }\n' % (src, extra)


IMAGE_CASES = {
    "svg_embedded_ids_isolated": Case(("a.lini",), files={"a.lini": img("logo.svg"), "logo.svg": SVG_ASSET}),
    "svg_self_closing_root": Case(("a.lini",), files={"a.lini": img("dot.svg"),
                                                      "dot.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'}),
    "svg_with_bom": Case(("a.lini",), files={"a.lini": img("bom.svg"),
                                             "bom.svg": "﻿<svg viewBox='0 0 4 4'><circle r='2'/></svg>"}),
    "svg_fit_contain": Case(("a.lini",), files={"a.lini": img("logo.svg", " fit: contain;"), "logo.svg": SVG_ASSET}),
    "svg_fit_cover": Case(("a.lini",), files={"a.lini": img("logo.svg", " fit: cover;"), "logo.svg": SVG_ASSET}),
    "svg_fit_stretch": Case(("a.lini",), files={"a.lini": img("logo.svg", " fit: stretch;"), "logo.svg": SVG_ASSET}),
    "svg_static": Case(("--static", "a.lini"), files={"a.lini": img("logo.svg"), "logo.svg": SVG_ASSET}),
    "same_asset_twice": Case(("a.lini",), files={"a.lini": img("logo.svg") + img("logo.svg"), "logo.svg": SVG_ASSET}),
    "png_data_uri": Case(("a.lini",), files={"a.lini": img("mark.png"), "mark.png": PNG}),
    "jpeg_data_uri": Case(("a.lini",), files={"a.lini": img("photo.jpg"), "photo.jpg": JPEG}),
    "gif_data_uri": Case(("a.lini",), files={"a.lini": img("anim.gif"), "anim.gif": GIF}),
    "webp_data_uri": Case(("a.lini",), files={"a.lini": img("pic.webp"), "pic.webp": WEBP}),
    "raster_sniffed_not_by_extension": Case(("a.lini",), files={"a.lini": img("really-png.svg"), "really-png.svg": PNG}),
    "unrecognised_bytes": Case(("a.lini",), files={"a.lini": img("notes.txt"), "notes.txt": "plain text\n"}),
    "empty_asset": Case(("a.lini",), files={"a.lini": img("empty.png"), "empty.png": b""}),
    "missing_asset": Case(("a.lini",), files={"a.lini": img("./logo.svg")}),
    "missing_asset_json": Case(("--json", "a.lini"), files={"a.lini": img("./logo.svg")}),
    "asset_is_directory": Case(("a.lini",), files={"a.lini": img("dir"), "dir/.keep": ""}),
    "relative_to_input_directory": Case(("docs/a.lini",), files={"docs/a.lini": img("assets/logo.svg"),
                                                                 "docs/assets/logo.svg": SVG_ASSET}),
    "not_relative_to_cwd": Case(("docs/a.lini",), files={"docs/a.lini": img("logo.svg"), "logo.svg": SVG_ASSET}),
    "parent_path_unbounded": Case(("docs/a.lini",), files={"docs/a.lini": img("../shared/logo.svg"),
                                                           "shared/logo.svg": SVG_ASSET}),
    "stdin_resolves_from_cwd": Case(("-",), stdin=img("logo.svg"), files={"logo.svg": SVG_ASSET}),
    "http_url_passes_through": Case(("a.lini",), files={"a.lini": img("https://example.com/logo.png")}),
    "uppercase_http_passes_through": Case(("a.lini",), files={"a.lini": img("HTTP://example.com/x.png")}),
    "data_uri_passes_through": Case(("a.lini",), files={"a.lini": img("data:image/png;base64,iVBORw0KGgo=")}),
    "image_requires_src": Case(("a.lini",), files={"a.lini": "|image| { width: 10; height: 10; }\n"}),
    "image_requires_size": Case(("a.lini",), files={"a.lini": '|image| { src: "https://example.com/a.png"; }\n'}),
    "image_html_wrapper": Case(("--format", "html", "a.lini"), files={"a.lini": img("mark.png"), "mark.png": PNG}),
}

NO_FS_CASES = {
    "no_fs_local_path_errors": Case(("--no-fs", "a.lini"), files={"a.lini": img("logo.svg"), "logo.svg": SVG_ASSET}),
    "no_fs_missing_path_same_error": Case(("--no-fs", "a.lini"), files={"a.lini": img("./nope.svg")}),
    "no_fs_json": Case(("--no-fs", "--json", "a.lini"), files={"a.lini": img("logo.svg"), "logo.svg": SVG_ASSET}),
    "no_fs_url_ok": Case(("--no-fs", "a.lini"), files={"a.lini": img("https://example.com/logo.svg")}),
    "no_fs_data_uri_ok": Case(("--no-fs", "a.lini"), files={"a.lini": img("data:image/svg+xml;base64,PHN2Zy8+")}),
    "no_fs_check": Case(("--no-fs", "--check", "a.lini"), files={"a.lini": img("logo.svg")}),
}


@pytest.mark.parametrize("name", sorted(IMAGE_CASES))
def test_image_assets(run_case, golden, name):
    """CATCHES: local images not embedded (or embedded with ids that are not
    prefixed / references not rewritten), rasters detected by extension instead
    of magic bytes, paths resolved against the cwd instead of the input's
    directory, URLs fetched or rewritten, or the wrong asset error message."""
    assert run_case(IMAGE_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(NO_FS_CASES))
def test_image_no_fs(run_case, golden, name):
    """CATCHES: --no-fs still reading (or stat-ing) a local image, leaking whether
    the file exists, or rejecting URLs and data URIs that need no disk."""
    assert run_case(NO_FS_CASES[name]) == golden(name)
