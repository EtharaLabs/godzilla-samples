"""Views, drawings and graphics: plans (SVG and PNG), ceiling plans, sections and elevations, sheets and their PDF,
scale, detail level and crop, Visibility/Graphics, filters, templates, phases and design options, line weights and object
styles, standards, and annotation (dimensions, tags, notes, spot elevations) as the drawings show them.

Plans are compared as SVG text, exactly. Pictures that only come as PNG (sections, elevations, sheets with them) are
compared by their size, exactly, and by a thumbnail of block averages within a small tolerance: the rasteriser's
anti-aliasing may differ by a level or two between processors, a drawing that changed does not.

Lettering that a system font would draw (dimension numbers and text notes, Arial by default) is put in IBM Plex Sans,
which the program carries, so the drawings don't depend on the fonts a machine has.
"""

import json
import struct
import zlib
from pathlib import Path

from conftest import resources_for

# A small two-room house: a compound exterior, a partition, two doors, a window, two rooms, a floor and two grids.
HOUSE = [
    'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true, "type": "Exterior - 300mm"}',
    'wall {"points": [[3000,0],[3000,4000]], "type": "Interior - 100mm"}',
    'door {"at": [1500, 0]}',
    'door {"at": [3000, 2000]}',
    'window {"at": [6000, 2000]}',
    'room {"point": [1500, 2000], "name": "Living"}',
    'room {"point": [4500, 2000], "name": "Bed"}',
    "floor {}",
    'grid {"start": [0, -1000], "end": [0, 5000]}',
    'grid {"start": [6000, -1000], "end": [6000, 5000]}',
]

# The lettering that would be the system's Arial, in a font the program carries.
PLEX = [
    'dimension_type {"name": "Diagonal - 2.5mm Arial", "font": "IBM Plex Sans"}',
    'dimension_type {"name": "Arrow - 2.5mm Arial", "font": "IBM Plex Sans"}',
    'text_type {"name": "2.5mm", "font": "IBM Plex Sans"}',
    'text_type {"name": "3.5mm", "font": "IBM Plex Sans"}',
    'text_type {"name": "5mm", "font": "IBM Plex Sans"}',
]

# What a listing says of this machine's fonts, which differs between machines.
SYSTEM_KEYS = ("fonts", "drawn_with")

SMALL = '"width": 400, "height": 300'


def cmd_args(*commands, pre=(), post=()):
    args = ["run", *pre]
    for c in commands:
        args += ["--cmd", c]
    return [*args, *post]


def steps(sc, *commands, pre=(), post=(), scrub=False):
    """Run `run [pre…] --cmd … [post…]` and record it; with `scrub`, each result line is recorded without what names the
    system's fonts."""
    args = cmd_args(*commands, pre=pre, post=post)
    if not scrub:
        return sc.run(args)
    p = sc.run(args, show=False)
    sc.note("$ bimcraft-cli run … (fonts scrubbed)")
    sc.note(f"[exit {p.returncode}]")
    for line in p.stdout.decode().splitlines():
        v = json.loads(line)
        if isinstance(v, dict):
            for k in SYSTEM_KEYS:
                v.pop(k, None)
        sc.note(json.dumps(v, ensure_ascii=False, sort_keys=True))
    sc.note("--- stderr")
    sc.note(p.stderr.decode())
    return p


def written(sc):
    """The files in the working directory (what a coverage build of the program drops there left out)."""
    names = sorted(p.name for p in sc.workdir.iterdir() if p.is_file() and p.suffix != ".profraw")
    sc.note("=== files: " + ", ".join(names))


def svg(sc, path):
    """An SVG the program wrote, one element a line."""
    text = (sc.workdir / path).read_text(encoding="utf-8")
    sc.note(f"=== svg {path}")
    sc.note(text.replace("><", ">\n<"))


def png_raw(data: bytes):
    """A PNG's (width, height, channels, rows of bytes): 8-bit, non-interlaced."""
    from itertools import accumulate
    from operator import add

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
    width, height, depth, ctype, _, _, interlace = ihdr
    assert depth == 8 and interlace == 0
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = width * bpp
    low = (255).__and__
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if f == 1:
            for ch in range(bpp):
                line[ch::bpp] = bytes(map(low, accumulate(line[ch::bpp])))
        elif f == 2:
            line = bytearray(map(low, map(add, line, prev)))
        elif f in (3, 4):
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                if f == 3:
                    line[x] = (line[x] + ((a + b) >> 1)) & 255
                    continue
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, bpp, rows


def thumbnail(width, height, bpp, rows, cols=16, nrows=12):
    """Block averages of the first three channels (or the grey one) over a cols x nrows grid."""
    cells = []
    channels = 3 if bpp >= 3 else 1
    for by in range(nrows):
        y0, y1 = by * height // nrows, (by + 1) * height // nrows
        for bx in range(cols):
            x0, x1 = bx * width // cols, (bx + 1) * width // cols
            sums = [0] * channels
            for y in range(y0, y1):
                row = rows[y]
                for ch in range(channels):
                    sums[ch] += sum(row[x0 * bpp + ch:x1 * bpp:bpp])
            n = max(1, (y1 - y0) * (x1 - x0))
            cells.append([round(s / n, 1) for s in sums])
    return cells


TOLERANCE = 4.0


def expected_thumbs(test_file: str, name: str, actual: dict) -> dict:
    """The thumbnails a test expects, captured from the reference program (`<name>.thumbs.json`)."""
    return json.loads((resources_for(test_file) / f"{name}.thumbs.json").read_text(encoding="utf-8"))


class Pictures:
    """PNGs a test looks at: their size in the transcript, their thumbnails compared within TOLERANCE."""

    def __init__(self, sc):
        self.sc, self.thumbs = sc, {}

    def png(self, path, data=None):
        data = data if data is not None else (self.sc.workdir / path).read_bytes()
        w, h, bpp, rows = png_raw(data)
        self.sc.note(f"=== png {path}: {w}x{h}, {bpp} channels")
        self.thumbs[path] = thumbnail(w, h, bpp, rows)

    def image(self, label, width, height, rgb: bytes):
        rows = [rgb[y * width * 3:(y + 1) * width * 3] for y in range(height)]
        self.sc.note(f"=== image {label}: {width}x{height}")
        self.thumbs[label] = thumbnail(width, height, 3, rows)

    def assert_match(self):
        expected = expected_thumbs(self.sc.test_file, self.sc.name, self.thumbs)
        assert sorted(expected) == sorted(self.thumbs)
        for key, cells in self.thumbs.items():
            assert len(cells) == len(expected[key])
            worst = max(abs(a - b) for got, want in zip(cells, expected[key]) for a, b in zip(got, want))
            assert worst <= TOLERANCE, f"{key}: a block differs by {worst} levels"


def pdf_pages(sc, pics, path):
    """A PDF's objects in order: vector content streams by length and sha256 of their text, images by size and thumbnail."""
    import hashlib
    import re

    data = (sc.workdir / path).read_bytes()
    first = data.split(b"\n", 1)[0].decode()
    sc.note(f"=== pdf {path}: {first}")
    pos, image = 0, 0
    start_re = re.compile(rb"(?<![0-9])(\d+) 0 obj\b")
    while True:
        m = start_re.search(data, pos)
        if not m:
            break
        num, body = m.group(1).decode(), m.end()
        s_at, e_at = data.find(b"stream", body), data.find(b"endobj", body)
        if s_at != -1 and s_at < e_at:
            head = data[body:s_at]
            length = int(re.search(rb"/Length (\d+)", head).group(1))
            start = s_at + len(b"stream\n")
            stream = zlib.decompress(data[start:start + length])
            pos = data.find(b"endobj", start + length) + 6
            head_text = re.sub(rb"/Length \d+", b"/Length *", head).strip().decode("latin-1")
            if b"/Subtype /Image" in head:
                w = int(re.search(rb"/Width (\d+)", head).group(1))
                h = int(re.search(rb"/Height (\d+)", head).group(1))
                sc.note(f"obj {num}: {head_text}")
                if b"/DeviceRGB" in head:
                    pics.image(f"{path} image {image}", w, h, stream)
                image += 1
            else:
                sc.note(f"obj {num}: {head_text} stream[{len(stream)}] sha256={hashlib.sha256(stream).hexdigest()}")
        else:
            sc.note(f"obj {num}: {data[body:e_at].strip().decode('latin-1')}")
            pos = e_at + 6


# ---------------------------------------------------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------------------------------------------------


def test_plan_svg_of_a_small_house(sc):
    """CATCHES: a plan drawn wrongly: wall poché and compound layers, door swings, the window, room tags with names and
    areas, grid lines and bubbles, its fitting to the requested size, SVG syntax, or the render reply's fields."""
    steps(sc, *HOUSE, f'render {{"path": "plan.svg", {SMALL}}}')
    svg(sc, "plan.svg")
    assert sc.transcript() == sc.golden()


def test_plan_png_and_inline_base64(sc):
    """CATCHES: a PNG plan of the wrong size, colour type or drawing, or a render with no path not answering with the
    picture inline as pngBase64 (the same picture)."""
    pics = Pictures(sc)
    p = sc.run(cmd_args(*HOUSE, f'render {{"path": "plan.png", {SMALL}}}', f"render {{{SMALL}}}"), show=False)
    lines = p.stdout.decode().splitlines()
    sc.note(f"[exit {p.returncode}] {lines[-2]}")
    inline = json.loads(lines[-1])
    import base64

    png = base64.b64decode(inline.pop("pngBase64"))
    sc.note(json.dumps(inline, sort_keys=True))
    sc.note(f"inline is the file: {png == (sc.workdir / 'plan.png').read_bytes()}")
    pics.png("plan.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_save_svg_and_png_draw_the_lowest_level(sc):
    """CATCHES: `--save x.svg` drawing another level than the lowest, at another size than 1600 x 1000, or differently from
    `render` of that level."""
    sc.run(cmd_args('level {"elevation": -3000, "name": "Basement"}', *HOUSE[:2],
                    'wall {"level": "Basement", "points": [[0,0],[2000,0],[2000,2000]]}',
                    'render {"view": "Basement", "path": "basement.svg"}') + ["--save", "saved.svg"])
    sc.note(f"same as render of Basement: {(sc.workdir / 'saved.svg').read_bytes() == (sc.workdir / 'basement.svg').read_bytes()}")
    svg(sc, "saved.svg")
    assert sc.transcript() == sc.golden()


def test_render_level_by_name_and_id_and_upper_level(sc):
    """CATCHES: render picking the wrong level when given a name or a numeric id, or an upper level's plan not showing what
    stands on it (and what it sees below)."""
    steps(sc, *HOUSE, 'wall {"level": "Level 2", "points": [[0,0],[6000,4000]]}',
          f'render {{"view": "Level 2", "path": "by-name.svg", {SMALL}}}',
          f'render {{"view": 100001, "path": "by-id.svg", {SMALL}}}')
    sc.note(f"same picture: {(sc.workdir / 'by-name.svg').read_bytes() == (sc.workdir / 'by-id.svg').read_bytes()}")
    svg(sc, "by-name.svg")
    assert sc.transcript() == sc.golden()


def test_reflected_ceiling_plan(sc):
    """CATCHES: a ceiling plan that doesn't look up (shows floors' furniture or door swings), draws no ceiling grid of a
    tiled type, or is reported as a plain plan."""
    steps(sc, *HOUSE, 'ceiling {"point": [1500, 2000]}', 'ceiling {"point": [4500, 2000], "type": "Tile 600 x 600"}',
          f'render {{"ceiling": true, "path": "rcp.svg", {SMALL}}}')
    svg(sc, "rcp.svg")
    assert sc.transcript() == sc.golden()


def test_render_errors(sc):
    """CATCHES: a render to an unknown view, an extension other than .png and .svg, a section to SVG, or a missing family
    not being refused with a message that says what to do."""
    for c in ['render {"view": "Nowhere"}', 'render {"path": "plan.jpg"}',
              'render {"view": "Section 1", "path": "s.svg"}', 'render {"family": "Nope"}',
              'render {"family": "Sofa", "mode": "side"}', 'render {"family": "Sofa", "type": "9 x 9"}']:
        steps(sc, *HOUSE[:2], 'section {"start": [-1000, 2000], "end": [7000, 2000]}', c)
    written(sc)
    assert sc.transcript() == sc.golden()


def test_render_size_is_clamped(sc):
    """CATCHES: a width or height outside 16..8192 being refused or used as given instead of clamped."""
    steps(sc, *HOUSE[:1], 'render {"path": "tiny.svg", "width": 3, "height": 99999}')
    text = (sc.workdir / "tiny.svg").read_text()
    sc.note(text[:text.index("<path")])
    assert sc.transcript() == sc.golden()


def test_sample_house_level_1_plan(sc):
    """CATCHES: any difference in the sample house's ground floor plan: furniture families seen from above, dimensions,
    door and window tags, the spot elevation, the note, the section and elevation marks, the roof's edge overhead."""
    steps(sc, *PLEX, 'render {"view": "Level 1", "path": "l1.svg"}', pre=["--sample"])
    svg(sc, "l1.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Scale, detail level, crop and duplicated views
# ---------------------------------------------------------------------------------------------------------------------


def test_scale_sizes_annotation_and_pens(sc):
    """CATCHES: a view's scale not sizing its annotation (room tags, grid bubbles) and its line weights, the scale command
    not reporting a view's scale, or out-of-range and null scales being accepted."""
    steps(sc, *HOUSE, 'scale {"view": "Level 1"}', 'scale {"view": "Level 1", "scale": 50}',
          f'render {{"path": "fifty.svg", {SMALL}}}')
    svg(sc, "fifty.svg")
    for bad in ['scale {"view": "Level 1", "scale": 0}', 'scale {"view": "Level 1", "scale": null}',
                'scale {"view": "Level 1", "scale": 100001}', 'scale {"scale": 50}']:
        steps(sc, bad)
    assert sc.transcript() == sc.golden()


def test_detail_levels_coarse_medium_fine(sc):
    """CATCHES: detail levels drawing the same: coarse must give one poché and gaps for openings, medium the layer lines and
    swings, fine the layer patterns; or a bad detail level accepted."""
    for level in ["coarse", "medium", "fine"]:
        steps(sc, *HOUSE[:5], f'detail {{"view": "Level 1", "detail": "{level}"}}',
              f'render {{"path": "{level}.svg", "width": 300, "height": 200}}')
        svg(sc, f"{level}.svg")
    steps(sc, 'detail {"view": "Level 1", "detail": "ultra"}')
    assert sc.transcript() == sc.golden()


def test_crop_plan_region_and_uncrop(sc):
    """CATCHES: a crop region not limiting what a plan shows, cropping to what the view shows giving the wrong extent,
    or `region: null` not uncropping."""
    steps(sc, *HOUSE, 'crop {"view": "Level 1"}', 'crop {"view": "Level 1", "region": [[0, 0], [3000, 4000]]}',
          f'render {{"path": "cropped.svg", {SMALL}}}', 'crop {"view": "Level 1", "region": null}',
          'crop {"view": "Level 1", "region": [[3000, 4000], [0, 0]]}')
    svg(sc, "cropped.svg")
    assert sc.transcript() == sc.golden()


def test_duplicate_view_modes(sc):
    """CATCHES: duplicate_view naming copies wrongly, `detailing` not copying a view's annotation, `dependent` not showing
    its parent's, or a section being duplicated."""
    steps(sc, *HOUSE, *PLEX, 'tag {}', 'text {"text": "North wing", "at": [500, 3500]}',
          'duplicate_view {"view": "Level 1"}', 'duplicate_view {"view": "Level 1", "mode": "detailing", "name": "L1 Notes"}',
          'duplicate_view {"view": "Level 1", "mode": "dependent"}',
          'text {"text": "Only here", "at": [3500, 3500], "view": "Level 1 Copy 1"}',
          f'render {{"view": "Level 1 Copy 1", "path": "copy.svg", {SMALL}}}',
          'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'duplicate_view {"view": "Section 1"}')
    svg(sc, "copy.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Sections and elevations
# ---------------------------------------------------------------------------------------------------------------------


def test_section_and_elevations_render_as_png(sc):
    """CATCHES: a section that cuts the wrong walls or sees nothing beyond, elevations made for the wrong sides or named
    wrongly, or pictures of the wrong size."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, 'roof {"slope": 30, "overhang": 400}', 'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'elevation {}', 'elevation {"facing": "south", "name": "Front"}',
          f'render {{"view": "Section 1", "path": "section.png", {SMALL}}}',
          f'render {{"view": "North", "path": "north.png", {SMALL}}}',
          f'render {{"view": "Front", "path": "front.png", {SMALL}}}')
    for f in ["section.png", "north.png", "front.png"]:
        pics.png(f)
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_section_depth_and_crop(sc):
    """CATCHES: a section's `depth` not limiting what it sees beyond its line, or a section crop not limiting the picture."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, 'section {"start": [-1000, 1000], "end": [7000, 1000], "depth": 500, "name": "Shallow"}',
          'crop {"view": "Shallow", "region": [[1000, -500], [5000, 3500]]}',
          'scale {"view": "Shallow", "scale": 50}',
          f'render {{"view": "Shallow", "path": "shallow.png", {SMALL}}}')
    pics.png("shallow.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


# ---------------------------------------------------------------------------------------------------------------------
# Visibility/Graphics
# ---------------------------------------------------------------------------------------------------------------------


def test_graphics_hide_categories_and_elements(sc):
    """CATCHES: hidden categories (rooms, grids) or hidden elements still drawn, singular/plural category names not both
    accepted, or the view's settings reported wrongly."""
    steps(sc, *HOUSE, 'graphics {"hide": ["rooms", "grid"], "hide_elements": [100006]}',
          f'render {{"path": "hidden.svg", {SMALL}}}', 'graphics {"show": ["grids"]}', 'graphics {"hide": ["unicorns"]}')
    svg(sc, "hidden.svg")
    assert sc.transcript() == sc.golden()


def test_graphics_category_overrides(sc):
    """CATCHES: category overrides not applied: a cut colour, pen, dash and fill on walls, a projection colour on doors,
    halftone on rooms; or a null not taking an override away."""
    steps(sc, *HOUSE,
          'graphics {"categories": {"walls": {"cut": {"color": [200, 0, 0], "weight": 12, "dash": "dashed", "fill": "#00ff00"}},'
          ' "doors": {"projection": {"color": "#0000ff", "weight": 2}}, "rooms": {"halftone": true}}}',
          f'render {{"path": "over.svg", {SMALL}}}',
          'graphics {"categories": {"doors": null}}')
    svg(sc, "over.svg")
    assert sc.transcript() == sc.golden()


def test_graphics_element_overrides_beat_categories(sc):
    """CATCHES: an element's own override not prevailing over its category's, or element overrides applied to others."""
    steps(sc, *HOUSE,
          'graphics {"categories": {"walls": {"cut": {"fill": [0, 0, 255]}}}, "elements": {"100006": {"cut": {"fill": [255, 0, 0], "color": [255, 0, 0]}, "halftone": true}}}',
          f'render {{"path": "elem.svg", {SMALL}}}')
    svg(sc, "elem.svg")
    assert sc.transcript() == sc.golden()


def test_view_filter_picks_and_overrides(sc):
    """CATCHES: a view filter picking the wrong elements by its rules, a view applying it not drawing them its way, or a
    deleted filter still applied."""
    steps(sc, *HOUSE,
          'filter {"name": "Exterior", "categories": ["walls"], "rules": [{"field": "Type", "op": "contains", "value": "Exterior"}]}',
          'filter {"name": "Exterior"}',
          'filter {"name": "Small rooms", "categories": ["rooms"], "rules": [{"field": "Name", "op": "begins-with", "value": "B"}]}',
          'graphics {"filters": [{"filter": "Exterior", "cut": {"fill": [250, 180, 200], "color": [120, 0, 0]}}, {"filter": "Small rooms", "hidden": true}]}',
          f'render {{"path": "filtered.svg", {SMALL}}}',
          'filter {"name": "Small rooms", "delete": true}', 'graphics {}',
          'filter {"name": "Bad", "categories": ["walls"], "rules": [{"field": "Type", "op": "resembles", "value": "x"}]}')
    svg(sc, "filtered.svg")
    assert sc.transcript() == sc.golden()


def test_view_template_from_a_view_and_assigned(sc):
    """CATCHES: a template not taking a view's settings, a view following it not drawing as it says, a controlled setting
    changed on the follower instead of refused, or a renamed template not followed."""
    steps(sc, *HOUSE,
          'graphics {"hide": ["grids"], "categories": {"walls": {"cut": {"fill": [90, 90, 160]}}}}',
          'scale {"view": "Level 1", "scale": 50}',
          'template {"name": "Presentation", "from": "Level 1"}',
          'graphics {"view": "Level 2", "template": "Presentation"}', post=["--save", "model.bimcraft"])
    sc.run(["run", "model.bimcraft", "--cmd", 'scale {"view": "Level 2", "scale": 200}'])
    steps(sc, 'template {"name": "Presentation", "rename": "Pres"}', 'graphics {"view": "Level 2"}',
          f'render {{"view": "Level 2", "path": "follower.svg", {SMALL}}}', 'template {"name": "Pres"}',
          'template {"name": "Pres", "controls": ["categories"]}', 'scale {"view": "Level 2", "scale": 200}',
          'template {"name": "Pres", "delete": true}', 'graphics {"view": "Level 2"}', pre=["model.bimcraft"])
    svg(sc, "follower.svg")
    assert sc.transcript() == sc.golden()


def test_graphics_reset_and_background_grid(sc):
    """CATCHES: a background grid not drawn with its spacing, divisions and rotation, or `reset` not taking every own
    setting of the view away."""
    steps(sc, *HOUSE[:2],
          'graphics {"background_grid": {"visible": true, "main": {"enabled": true, "color": [200, 50, 50], "pen": 2}, "sub": {"enabled": true}, "spacing": [2000, 1000], "divisions": [2, 2], "rotation": 30}}',
          f'render {{"path": "grid.svg", {SMALL}}}',
          'graphics {"hide": ["walls"]}', 'graphics {"reset": true}',
          'graphics {"background_grid": {"divisions": [0, 5]}}')
    svg(sc, "grid.svg")
    assert sc.transcript() == sc.golden()


def test_phases_and_phase_filters_in_a_plan(sc):
    """CATCHES: elements made in an earlier phase not drawn halftone, demolished ones not dashed red, a view's phase or
    phase filter not changing what it shows, or phases not kept in order."""
    steps(sc, *HOUSE[:2],
          'phase {}', 'phase {"name": "Stage 2", "after": "Existing"}',
          'modify {"ids": [100002, 100003], "params": {"Phase Created": "Existing"}}',
          'modify {"id": 100004, "params": {"Phase Created": "Existing", "Phase Demolished": "Stage 2"}}',
          'graphics {"phase": "Stage 2", "phase_filter": "Show All"}',
          f'render {{"path": "all.svg", {SMALL}}}',
          'phase_filter {"name": "Only new", "existing": "not-displayed", "demolished": "not-displayed"}',
          'graphics {"phase_filter": "Only new"}',
          f'render {{"path": "new.svg", {SMALL}}}',
          'phase_filter {"name": "Only new", "delete": true}')
    svg(sc, "all.svg")
    svg(sc, "new.svg")
    assert sc.transcript() == sc.golden()


def test_design_options_in_a_plan(sc):
    """CATCHES: a design option's elements shown in a view that shows another option, the primary not shown by default,
    or accepting an option keeping the wrong elements."""
    steps(sc, *HOUSE[:1],
          'option {"set": "Layout", "options": ["Open", "Split"]}',
          'wall {"points": [[3000,0],[3000,4000]]}',
          'wall {"points": [[0,2000],[6000,2000]]}',
          'modify {"id": 100006, "params": {"Design Option": "Layout: Open"}}',
          'modify {"id": 100007, "params": {"Design Option": "Layout: Split"}}',
          f'render {{"path": "primary.svg", {SMALL}}}',
          'graphics {"options": {"Layout": "Split"}}',
          f'render {{"path": "split.svg", {SMALL}}}',
          'option {"set": "Layout", "primary": "Split"}',
          'option {"set": "Layout", "accept": true}',
          'elements {"category": "wall"}')
    svg(sc, "primary.svg")
    svg(sc, "split.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Line weights, object styles and standards
# ---------------------------------------------------------------------------------------------------------------------


def test_line_weights_set_and_reset(sc):
    """CATCHES: line weights not listed per scale, a model column not changing how wide a plan's cut lines draw, `reset`
    not going back to the start, or a wrong count of pens, no scale, a bad or repeated scale or a width out of range
    accepted."""
    widths = ", ".join(["0.5"] * 16)
    steps(sc, *HOUSE[:2], f'line_weights {{"model": [{{"scale": 100, "widths": [{widths}]}}]}}',
          f'render {{"path": "heavy.svg", "width": 300, "height": 200}}',
          'line_weights {"reset": true}', 'line_weights {}')
    svg(sc, "heavy.svg")
    ok = ", ".join(["0.3"] * 16)
    for bad in ['line_weights {"annotation": [1]}', 'line_weights {"model": []}',
                f'line_weights {{"model": [{{"scale": 0, "widths": [{ok}]}}]}}',
                f'line_weights {{"model": [{{"scale": 50, "widths": [{ok}]}}, {{"scale": 50, "widths": [{ok}]}}]}}',
                f'line_weights {{"annotation": [{ok.replace("0.3", "30", 1)}]}}']:
        steps(sc, bad)
    assert sc.transcript() == sc.golden()


def test_object_styles_pens(sc):
    """CATCHES: object styles not listing every model category's pens, a category's cut pen not used by a plan, a given
    category losing the pen it wasn't given, or an unknown category accepted."""
    steps(sc, *HOUSE[:3], 'object_styles {}', 'object_styles {"categories": {"wall": {"cut": 16}, "door": {"projection": 1}}}',
          f'render {{"path": "styled.svg", "width": 300, "height": 200}}',
          'object_styles {"reset": true}', 'object_styles {"categories": {"dragon": {"cut": 3}}}')
    svg(sc, "styled.svg")
    assert sc.transcript() == sc.golden()


def test_standards_report_and_set(sc):
    """CATCHES: the standards listing changing, `standard set` not adapting line weights and object styles, or an unknown
    standard accepted."""
    steps(sc, 'standard {}', 'standard {"set": "nbr", "adapt_all": true}', 'line_weights {}', 'object_styles {}',
          'standard {"set": "din"}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------------------------------------------------


def test_sheet_with_plan_and_schedule_as_pdf(sc):
    """CATCHES: a sheet whose title block, viewport title, scale note or schedule table differ, a default placement in the
    wrong place, or a PDF page of the wrong paper size."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, *PLEX, 'sheet {"name": "Ground Floor"}', 'place {"sheet": "A101", "view": "Level 1"}',
          'place {"sheet": "A101", "view": "Room Schedule"}', 'render {"view": "A101", "path": "a101.pdf"}',
          'render {"view": "A101", "path": "a101.png"}')
    pdf_pages(sc, pics, "a101.pdf")
    pics.png("a101.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_sheet_sizes_and_numbers(sc):
    """CATCHES: sheet numbers not running A101, A102…, a size other than A0..A4 accepted, or paper sizes in the PDF's
    MediaBox wrong for each size."""
    pics = Pictures(sc)
    steps(sc, 'sheet {"size": "A4"}', 'sheet {"size": "A0", "name": "Big"}', 'sheet {"number": "X-1", "size": "A2"}',
          'sheet {"size": "B5"}', pre=[])
    for n, size in [("A101", "A4"), ("A102", "A0"), ("X-1", "A2")]:
        steps(sc, f'sheet {{"size": "{size}", "number": "{n}"}}', f'render {{"view": "{n}", "path": "{n}.pdf"}}')
        pdf_pages(sc, pics, f"{n}.pdf")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_sheet_with_section_and_elevation_pdf(sc):
    """CATCHES: a sheet's section or elevation viewport not drawn as a picture of what lies beyond plus its cut, viewport
    titles and scales wrong, or several scales not making SCALE AS INDICATED."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, *PLEX, 'section {"start": [-1000, 2000], "end": [7000, 2000]}', 'elevation {"facing": "south"}',
          'sheet {"name": "Sections", "size": "A3"}',
          'place {"sheet": "A101", "view": "Section 1", "at": [120, 200], "scale": 50}',
          'place {"sheet": "A101", "view": "South", "at": [300, 200]}',
          'render {"view": "A101", "path": "a101.pdf"}')
    pdf_pages(sc, pics, "a101.pdf")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_save_pdf_prints_every_sheet_of_the_sample(sc):
    """CATCHES: `--save x.pdf` missing a sheet, printing them out of order, or drawing any page differently."""
    pics = Pictures(sc)
    steps(sc, *PLEX, pre=["--sample"], post=["--save", "sheets.pdf"])
    pdf_pages(sc, pics, "sheets.pdf")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_place_errors(sc):
    """CATCHES: a view placed on two sheets, on a sheet that isn't there, or a view that isn't there, being accepted."""
    for c in ['place {"sheet": "A101", "view": "Level 1"}', 'place {"sheet": "A999", "view": "Level 2"}',
              'place {"sheet": "A101", "view": "Nowhere"}', 'place {"sheet": "A102", "view": "Level 1"}']:
        steps(sc, *HOUSE[:1], 'sheet {}', 'sheet {}', 'place {"sheet": "A101", "view": "Level 1"}', c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Annotation: dimensions, tags, notes, spot elevations
# ---------------------------------------------------------------------------------------------------------------------

# Three parallel walls, 3000 and 4000 apart, to dimension.
THREE_WALLS = [
    'wall {"points": [[0,0],[0,4000]]}',
    'wall {"points": [[3000,0],[3000,4000]]}',
    'wall {"points": [[7000,0],[7000,4000]]}',
]


def test_dimensions_of_every_kind(sc):
    """CATCHES: wrong values or labels for linear (both orientations), aligned, angular, radial, diameter and arc-length
    dimensions, the default dimension types they start in, or how a plan draws their ticks, witness lines and numbers."""
    steps(sc, *PLEX,
          'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
          'wall {"points": [[8000,0],[12000,0]], "arc": 90}',
          'column {"at": [3000, 2000], "type": "Round 300"}',
          'dimension {"refs": [{"endpoint": [0,0]}, {"endpoint": [6000,4000]}], "at": [3000, -1000], "kind": "linear", "orient": "horizontal"}',
          'dimension {"refs": [{"endpoint": [0,0]}, {"endpoint": [6000,4000]}], "at": [7000, 2000], "kind": "linear"}',
          'dimension {"refs": [{"endpoint": [0,0]}, {"endpoint": [6000,4000]}], "at": [2000, 3000]}',
          'dimension {"refs": [{"id": 100002}, {"id": 100003}], "at": [5500, 500], "kind": "angular"}',
          'dimension {"refs": [{"id": 100006}], "at": [10000, 3000], "kind": "radial"}',
          'dimension {"refs": [{"id": 100007}], "at": [3500, 2500], "kind": "diameter"}',
          'dimension {"refs": [{"id": 100006}], "at": [10000, 2500], "kind": "arc_length"}',
          'elements {"category": "dimension"}',
          'render {"path": "dims.svg", "width": 600, "height": 300}')
    svg(sc, "dims.svg")
    assert sc.transcript() == sc.golden()


def test_dimension_between_walls_faces_doors_and_grids(sc):
    """CATCHES: wrong distances to a wall's faces against its centre line, to a door's jambs, or between grids; or a
    dimension across walls that aren't parallel being accepted."""
    steps(sc, *HOUSE,
          'dimension {"refs": [{"id": 100005, "face": "left"}, {"id": 100006}, {"id": 100003, "face": "right"}], "at": [3000, -800]}',
          'dimension {"refs": [{"id": 100013}, {"id": 100014}], "at": [3000, 4800]}',
          'dimension {"refs": [{"id": 100007, "face": "start"}, {"id": 100007, "face": "end"}], "at": [1500, -500]}',
          'dimension {"refs": [{"id": 100005, "face": "right", "point": "start"}, {"id": 100003, "face": "left", "point": "end"}], "at": [3000, 4400], "kind": "linear", "orient": "horizontal"}')
    steps(sc, *HOUSE[:2], 'dimension {"refs": [{"id": 100002}, {"id": 100006}], "at": [3000, -800]}')
    assert sc.transcript() == sc.golden()


def test_dimension_type_and_dimension_text(sc):
    """CATCHES: a dimension type's ticks, colour, units, decimals, string and lettering not changing how its dimensions
    read and draw, a dimension's prefix, suffix, below text or a segment's replacement not shown, or a type in use deleted."""
    steps(sc, *PLEX, *THREE_WALLS,
          'dimension {"refs": [{"id": 100002}, {"id": 100003}, {"id": 100004}], "at": [3500, -800]}',
          'dimension_type {"name": "Arrows cm", "like": "Diagonal - 2.5mm Arial", "tick": "arrow", "units": "cm", "decimals": 1, "color": "#0055aa", "string": "baseline", "text_size": 3, "bold": true}',
          'modify {"id": 100005, "type": "Arrows cm"}',
          'dimension_text {"id": 100005, "prefix": "~", "suffix": " cl", "below": "TYP", "above": "CLEAR"}',
          'dimension_text {"id": 100005, "segment": 1, "replace": "VARIES"}',
          'elements {"category": "dimension"}',
          'render {"path": "typed.svg", "width": 500, "height": 300}',
          'dimension_type {"name": "Arrows cm", "rename": "Arrows"}',
          'dimension_type {"name": "Dots", "tick": "dot", "decimals": 2, "units": "m"}',
          'dimension_type {"name": "Feet", "tick": "open_arrow", "decimals": 2, "units": "ft", "witness": "fixed", "witness_length": 3, "read": "up_then_right", "background": "transparent", "italic": true, "underline": true, "width_factor": 0.7, "centre_mark": false, "font": "BIMCraft Lettering"}',
          'modify {"id": 100005, "type": "Feet"}', 'elements {"category": "dimension"}',
          'render {"path": "feet.svg", "width": 500, "height": 300}',
          'dimension_type {"name": "Ordinate dots", "like": "Dots", "string": "ordinate", "font": "IBM Plex Mono"}',
          'modify {"id": 100005, "type": "Ordinate dots"}', 'render {"path": "dots.svg", "width": 500, "height": 300}',
          'dimension_type {"name": "Plain", "tick": "none", "font": "IBM Plex Sans", "line_extension": 3, "witness_gap": 2, "witness_extension": 2, "text_offset": 3}',
          'modify {"id": 100005, "type": "Plain"}', 'render {"path": "plain.svg", "width": 500, "height": 300}',
          'modify {"id": 100005, "type": "Arrows"}',
          'dimension_type {"name": "Arrows", "delete": true}', scrub=True)
    for f in ["typed.svg", "feet.svg", "dots.svg", "plain.svg"]:
        svg(sc, f)
    assert sc.transcript() == sc.golden()


def test_dimension_type_listing_and_bad_values(sc):
    """CATCHES: the two starting dimension types or their parameters differing; a bad tick, pen, decimals, width factor,
    tick or text size or a multi-line symbol accepted; an empty font not keeping Arial; or an unused type not deletable."""
    steps(sc, 'dimension_type {}', scrub=True)
    for bad in ['dimension_type {"name": "X", "tick": "star"}', 'dimension_type {"name": "X", "line_pen": 17}',
                'dimension_type {"name": "X", "decimals": 7}', 'dimension_type {"name": "X", "like": "Nope"}',
                'dimension_type {"name": "X", "width_factor": 20}', 'dimension_type {"name": "X", "tick_size": 60}',
                'dimension_type {"name": "X", "text_size": 0}', 'dimension_type {"name": "X", "radius_symbol": "a\\nb"}',
                'dimension_type {"name": "X", "font": ""}', 'dimension_type {"name": "Diagonal - 2.5mm Arial", "delete": true}']:
        steps(sc, bad)
    assert sc.transcript() == sc.golden()


def test_dimension_constraints_lock_and_equal(sc):
    """CATCHES: an EQ constraint not moving the middle wall to equal segments, a locked segment not carried along when a
    wall it measures moves, or the constraint's state misreported."""
    steps(sc, *THREE_WALLS,
          'dimension {"refs": [{"id": 100002}, {"id": 100003}, {"id": 100004}], "at": [3500, -800]}',
          'dimension_constraint {"id": 100005, "equal": true}',
          'elements {"category": "wall"}', 'elements {"category": "dimension"}',
          'dimension_constraint {"id": 100005, "equal": false, "locked": [0]}',
          'move {"ids": [100002], "by": [-500, 0]}',
          'elements {"category": "wall"}', 'elements {"category": "dimension"}',
          'dimension_constraint {"id": 100005, "locked": [5]}')
    assert sc.transcript() == sc.golden()


def test_dimension_follows_what_it_measures(sc):
    """CATCHES: a dimension keeping its old value after a wall it measures moves, or one left pointing at a deleted wall."""
    steps(sc, *THREE_WALLS,
          'dimension {"refs": [{"id": 100002}, {"id": 100003}, {"id": 100004}], "at": [3500, -800]}',
          'move {"ids": [100004], "by": [1000, 0]}', 'elements {"category": "dimension"}',
          'delete {"ids": [100003]}', 'elements {"category": "dimension"}')
    assert sc.transcript() == sc.golden()


def test_tags_with_labels_offsets_and_leaders(sc):
    """CATCHES: tags naming the wrong field (a door's mark, a room's name, a label such as Area or Thickness), placed
    at the wrong offset, a leader not drawn, or tagging twice tagging again what is tagged."""
    steps(sc, *HOUSE, 'tag {}', 'tag {"category": "room", "label": "Area"}',
          'tag {"ids": [100002, 100006], "offset": [300, 600], "leader": true}',
          'tag {"ids": [100012], "label": "Thickness"}',
          'elements {"category": "tag"}',
          f'render {{"path": "tags.svg", {SMALL}}}', post=["--save", "tags.bimcraft"])
    steps(sc, 'tag {}', pre=["tags.bimcraft"])
    steps(sc, 'tag {"ids": [100002], "label": "Shoe Size"}', pre=["tags.bimcraft"])
    svg(sc, "tags.svg")
    assert sc.transcript() == sc.golden()


def test_text_notes_types_and_runs(sc):
    """CATCHES: notes lettered in the wrong font, size, weight, colour or width, a border or leader missing, lines not
    broken at \\n, a turned note not turned, or bold/italic/underline runs not applied to their characters."""
    steps(sc, *PLEX, *HOUSE[:1],
          'text_type {"name": "Boxed", "like": "3.5mm", "font": "IBM Plex Mono", "border": true, "border_offset": 2, "border_pen": 6, "bold": true, "color": "#aa0000", "width_factor": 0.8}',
          'text_type {"name": "Letters", "font": "BIMCraft Lettering", "size": 5, "italic": true, "underline": true}',
          'text {"text": "Line one\\nLine two", "at": [500, 3500], "type": "Boxed", "angle": 15, "leader": [1500, 2500]}',
          'text {"text": "Mixed runs here", "at": [3500, 3500], "override_format": true, "runs": [{"from": 0, "to": 5, "bold": true}, {"from": 6, "to": 10, "italic": true, "underline": true}]}',
          'text {"text": "LETTERING", "at": [500, 1000], "type": "Letters"}',
          'elements {"category": "text"}',
          f'render {{"path": "notes.svg", {SMALL}}}')
    svg(sc, "notes.svg")
    assert sc.transcript() == sc.golden()


def test_text_type_rename_delete_and_refusals(sc):
    """CATCHES: a renamed text type not followed by its notes, a type in use deleted, an unknown type or a bad size
    accepted, or a note with no text accepted."""
    steps(sc, 'text_type {"name": "Big", "size": 7, "font": "IBM Plex Sans"}',
          'text {"text": "Hello", "at": [0, 0], "type": "Big"}',
          'text_type {"name": "Big", "rename": "Huge"}', 'elements {"category": "text"}',
          'text_type {"name": "Spare", "like": "Huge"}', 'text_type {"name": "Spare", "delete": true}',
          post=["--save", "notes.bimcraft"])
    for bad in ['text_type {"name": "Huge", "delete": true}',
                'text {"text": "x", "at": [0, 0], "type": "Nope"}', 'text {"text": "", "at": [0, 0]}',
                'text_type {"name": "X", "size": -1}']:
        steps(sc, bad, pre=["notes.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_spot_elevations_and_slopes(sc):
    """CATCHES: a spot elevation reading the wrong height on a sloped floor, a spot slope's percentage or downhill
    direction wrong, a spot in a section not reading the point's height, or one placed on nothing accepted."""
    steps(sc, *PLEX, 'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
          'floor {"slope": 5, "arrow": [[0, 2000], [6000, 2000]], "offset": 100}',
          'spot {"at": [1000, 1000]}', 'spot {"at": [5000, 1000]}', 'spot_slope {"at": [3000, 2000]}',
          'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'spot {"at": [3000, 1500], "view": "Section 1"}',
          'elements {"category": "spot"}',
          f'render {{"path": "spots.svg", {SMALL}}}')
    svg(sc, "spots.svg")
    steps(sc, 'spot {"at": [99000, 99000]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Filled regions over the model
# ---------------------------------------------------------------------------------------------------------------------

SQUARE = '[[[500,500],[2500,500]],[[2500,500],[2500,2500]],[[2500,2500],[500,2500]],[[500,2500],[500,500]]]'


def test_filled_and_masking_regions_in_a_plan(sc):
    """CATCHES: a filled region drawn without its pattern or colour, a masking region not hiding the model under it, or a
    region type with an unknown pattern accepted."""
    steps(sc, *HOUSE[:3],
          f'filled_region {{"sketch": {SQUARE}, "type": "Diagonal Up"}}',
          'filled_region {"sketch": [[[3500,500],[5500,500]],[[5500,500],[5500,-500]],[[5500,-500],[3500,-500]],[[3500,-500],[3500,500]]], "type": "Masking"}',
          'filled_region_type {"name": "Green", "foreground": "Crosshatch", "foreground_color": [0, 120, 0], "background": "Solid fill", "background_color": [220, 255, 220]}',
          'filled_region {"sketch": [[[1000,3000],[2000,3000]],[[2000,3000],[1500,3800]],[[1500,3800],[1000,3000]]], "type": "Green", "line_style": null}',
          f'render {{"path": "regions.svg", {SMALL}}}')
    svg(sc, "regions.svg")
    steps(sc, 'filled_region_type {"name": "Hatch", "foreground": "Diagonal up"}')
    assert sc.transcript() == sc.golden()


def test_filled_region_in_a_section(sc):
    """CATCHES: a filled region in a section not drawn over what the section sees, or drawn in the wrong place along it."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, 'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'filled_region {"view": "Section 1", "sketch": [[[2000,500],[4000,500]],[[4000,500],[4000,2500]],[[4000,2500],[2000,2500]],[[2000,2500],[2000,500]]], "type": "Crosshatch"}',
          f'render {{"view": "Section 1", "path": "section.png", {SMALL}}}')
    pics.png("section.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


# ---------------------------------------------------------------------------------------------------------------------
# Units and language in drawings
# ---------------------------------------------------------------------------------------------------------------------


def test_units_change_what_drawings_say(sc):
    """CATCHES: a project's units not changing dimension numbers, room areas and the sheet's scale note (feet and inches,
    metres), or an unknown unit accepted; the model keeping millimetres throughout."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, *PLEX,
          'dimension {"refs": [{"id": 100005}, {"id": 100006}, {"id": 100003}], "at": [3000, -800]}',
          'units {}', 'units {"length": "ft-in"}',
          f'render {{"path": "imperial.svg", {SMALL}}}',
          'scale {"view": "Level 1"}',
          'sheet {}', 'place {"sheet": "A101", "view": "Level 1"}', 'render {"view": "A101", "path": "a101.pdf"}',
          'units {"length": "m"}', f'render {{"path": "metres.svg", {SMALL}}}',
          'elements {"category": "dimension"}', 'units {"length": "furlong"}')
    svg(sc, "imperial.svg")
    svg(sc, "metres.svg")
    pdf_pages(sc, pics, "a101.pdf")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_language_names_views_and_sheet_words(sc):
    """CATCHES: a project's language not naming new levels, sections, elevations, sheets and rooms in it, or the sheet's
    SCALE word and a room schedule's headings left in English."""
    pics = Pictures(sc)
    steps(sc, 'new {"language": "pt"}', *HOUSE, *PLEX,
          'section {"start": [-1000, 2000], "end": [7000, 2000]}', 'elevation {"facing": "north"}',
          'sheet {}', 'place {"sheet": "A101", "view": "Nível 1"}', 'place {"sheet": "A101", "view": "Room Schedule"}',
          'level {"elevation": 6000}',
          'render {"view": "A101", "path": "a101.pdf"}', 'language {}', 'language {"code": "es"}',
          'level {"elevation": 9000}', 'language {"code": "xx"}')
    pdf_pages(sc, pics, "a101.pdf")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


# ---------------------------------------------------------------------------------------------------------------------
# The sample house's other views
# ---------------------------------------------------------------------------------------------------------------------


def test_sample_house_section_and_elevations(sc):
    """CATCHES: the sample house's section (cut walls in poché, the hipped roof along its slope, levels and grids) or its
    four elevations drawn differently, or named and sized wrongly."""
    pics = Pictures(sc)
    views = ["Section 1", "North", "South", "East", "West"]
    steps(sc, *PLEX, *[f'render {{"view": "{v}", "path": "{v}.png", {SMALL}}}' for v in views], pre=["--sample"])
    for v in views:
        pics.png(f"{v}.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_sample_house_ceiling_plan_and_level_2(sc):
    """CATCHES: the sample's reflected ceiling plan (its four ceilings, the kitchen's tiles) or its Level 2 plan (the
    roof seen below the cut, nothing of Level 1's furniture) drawn differently."""
    steps(sc, *PLEX, f'render {{"view": "Level 1", "ceiling": true, "path": "rcp.svg", {SMALL}}}',
          f'render {{"view": "Level 2", "path": "l2.svg", {SMALL}}}', pre=["--sample"])
    svg(sc, "rcp.svg")
    svg(sc, "l2.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Phases and design options: their life cycle
# ---------------------------------------------------------------------------------------------------------------------


def test_phase_list_add_rename_delete_and_now(sc):
    """CATCHES: phases added in the wrong place, a rename not followed by elements, views and filter rules, a held phase
    deleted without `into`, `now` not stamping new elements, or overrides not merged and taken away by null."""
    steps(sc, *HOUSE[:2],
          'phase {}', 'phase {"name": "Demolition", "before": "New Construction"}', 'phase {"name": "Fit-out"}',
          'phase {"name": "Survey", "before": "Existing"}',
          'modify {"id": 100002, "params": {"Phase Created": "Existing", "Phase Demolished": "Demolition"}}',
          'graphics {"phase": "Demolition"}',
          'filter {"name": "Going", "categories": ["walls"], "rules": [{"field": "Phase Demolished", "op": "equals", "value": "Demolition"}]}',
          'phase {"name": "Demolition", "rename": "Strip-out"}',
          'elements {"category": "wall", "limit": 1}', 'graphics {}', 'filter {"name": "Going"}',
          'phase {"now": "Fit-out"}', 'wall {"points": [[0,6000],[4000,6000]]}', 'elements {"category": "wall", "offset": 4}',
          'phase {"overrides": {"new": {"projection": {"color": [0, 160, 0]}, "halftone": true}, "existing": null}}',
          'phase {"name": "Strip-out", "delete": true, "into": "New Construction"}',
          'elements {"category": "wall", "limit": 1}', 'phase {"now": null}',
          post=["--save", "phased.bimcraft"])
    for bad in ['phase {"name": "Existing", "delete": true}', 'phase {"name": "Fit-out", "rename": "Existing"}',
                'phase {"name": "Late", "after": "Nowhere"}', 'phase {"now": "Nowhere"}',
                'modify {"id": 100003, "params": {"Phase Created": "Fit-out", "Phase Demolished": "Existing"}}']:
        steps(sc, bad, pre=["phased.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_phase_filter_overridden_statuses_in_a_plan(sc):
    """CATCHES: a phase filter's `overridden` status not drawn with the project's overrides for it (demolished dashed red,
    existing halftone, changed ones as set), or `not-displayed` statuses still drawn."""
    steps(sc, *HOUSE[:2],
          'phase {"name": "Stage 2"}',
          'modify {"ids": [100002, 100003], "params": {"Phase Created": "Existing"}}',
          'modify {"id": 100004, "params": {"Phase Created": "Existing", "Phase Demolished": "New Construction"}}',
          'modify {"id": 100006, "params": {"Phase Created": "New Construction", "Phase Demolished": "New Construction"}}',
          'phase_filter {"name": "Review", "new": "overridden", "existing": "overridden", "demolished": "overridden", "temporary": "overridden"}',
          'phase {"overrides": {"new": {"cut": {"fill": [0, 200, 0]}}, "temporary": {"projection": {"dash": "dotted", "color": "#ff8800"}, "cut": {"color": "#ff8800"}}}}',
          'graphics {"phase": "New Construction", "phase_filter": "Review"}',
          f'render {{"path": "review.svg", {SMALL}}}',
          'graphics {"phase_filter": "Show Previous + Demolished"}',
          f'render {{"path": "previous.svg", {SMALL}}}',
          'graphics {"phase": "Stage 2", "phase_filter": "Show Complete"}',
          f'render {{"path": "later.svg", {SMALL}}}')
    for f in ["review.svg", "previous.svg", "later.svg"]:
        svg(sc, f)
    assert sc.transcript() == sc.golden()


def test_design_option_set_life_cycle(sc):
    """CATCHES: renaming a set or an option not followed by its elements and the views choosing it, `now` not putting new
    elements in an option, deleting a set not deleting its elements, or names with colons accepted."""
    steps(sc, *HOUSE[:1],
          'option {"set": "Stair", "options": ["Straight", "L-shaped", "Spiral"]}',
          'option {"set": "Stair", "now": "Stair: L-shaped"}', 'wall {"points": [[1000,1000],[1000,3000]]}',
          'option {"set": "Stair", "now": null}',
          'wall {"points": [[2000,1000],[2000,3000]]}',
          'graphics {"options": {"Stair": "L-shaped"}}',
          'option {"set": "Stair", "option": "L-shaped", "rename": "Dog-leg"}',
          'option {"set": "Stair", "rename": "Stairs"}',
          'graphics {}', 'elements {"category": "wall", "offset": 4}',
          'option {"set": "Stairs", "options": ["Straight", "Dog-leg"]}',
          'option {"set": "Roof", "options": ["Flat", "Pitched"]}',
          'option {"set": "Stairs", "delete": true}', 'elements {"category": "wall", "offset": 4}',
          post=["--save", "options.bimcraft"])
    for bad in ['option {"set": "A: B", "options": ["x"]}', 'option {"set": "Roof", "options": ["Flat", "Flat"]}',
                'option {"set": "Nope", "accept": true}', 'option {"set": "Roof", "now": "Roof: Domed"}',
                'graphics {"options": {"Roof": "Domed"}}']:
        steps(sc, bad, pre=["options.bimcraft"])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Graphics refused, and what a template controls
# ---------------------------------------------------------------------------------------------------------------------


def test_graphics_refusals(sc):
    """CATCHES: a view accepting a filter it doesn't have or one applied twice, a template, phase, phase filter or option
    that isn't there, a transparency or pen out of range, or an override field it doesn't know."""
    steps(sc, *HOUSE[:1], 'filter {"name": "All walls", "categories": ["walls"]}', 'option {"set": "S", "options": ["a", "b"]}',
          post=["--save", "base.bimcraft"])
    for bad in ['graphics {"filters": [{"filter": "Nope"}]}',
                'graphics {"filters": [{"filter": "All walls"}, {"filter": "All walls", "halftone": true}]}',
                'graphics {"template": "Nope"}', 'graphics {"phase": "Nope"}', 'graphics {"phase_filter": "Nope"}',
                'graphics {"options": {"S": "c"}}', 'graphics {"options": {"T": "a"}}',
                'graphics {"categories": {"walls": {"transparency": 101}}}',
                'graphics {"categories": {"walls": {"cut": {"weight": 17}}}}',
                'graphics {"categories": {"walls": {"sparkle": true}}}',
                'graphics {"view": "Nowhere", "hide": ["walls"]}',
                'graphics {"elements": {"999999": {"halftone": true}}}']:
        steps(sc, bad, pre=["base.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_template_controls_refuse_changes_on_followers(sc):
    """CATCHES: a view following a template changing what the template controls (categories, filters, detail, phase, view
    range) instead of being refused, or what it doesn't control being refused."""
    steps(sc, *HOUSE[:1],
          'template {"name": "Plans", "kind": "plan", "hide": ["rooms"], "detail": "medium", "controls": ["categories", "filters", "range", "phase", "detail", "options"]}',
          'graphics {"view": "Level 1", "template": "Plans"}', 'scale {"view": "Level 1", "scale": 20}',
          'template {"name": "Plans", "view_range": {"cut": 900}}', 'template {"name": "Plans"}',
          post=["--save", "followed.bimcraft"])
    for bad in ['graphics {"hide": ["walls"]}', 'detail {"view": "Level 1", "detail": "fine"}',
                'graphics {"phase": "Existing"}', 'modify {"id": 100000, "view_range": {"cut": 1500}}',
                'template {"name": "Plans", "from": "Nowhere"}', 'template {"name": "Plans", "controls": ["colour"]}',
                'template {"name": "Copy", "like": "Nope"}', 'graphics {"view": "Level 1", "template": null}']:
        steps(sc, bad, pre=["followed.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_template_kinds_copies_and_3d(sc):
    """CATCHES: `like` not copying a template, `from` a section not making a section template, a 3D template not taking
    a visual style, a renamed template's followers not following, or a deleted one's followers not keeping its settings
    (a template of another kind is followed as well)."""
    steps(sc, *HOUSE[:2], 'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'template {"name": "Sections", "from": "Section 1", "detail": "coarse"}',
          'template {"name": "Sections B", "like": "Sections"}',
          'template {"name": "Shaded 3D", "kind": "3d", "visual_style": "hidden_line"}',
          'graphics {"view": "Section 1", "template": "Sections B"}', 'detail {"view": "Section 1"}',
          'template {"name": "Sections B", "rename": "Sect"}', 'template {"name": "Shaded 3D"}',
          post=["--save", "t.bimcraft"])
    steps(sc, 'graphics {"view": "Level 1", "template": "Sect"}', pre=["t.bimcraft"])
    steps(sc, 'graphics {"view": "Level 1", "template": "Shaded 3D"}', pre=["t.bimcraft"])
    steps(sc, 'template {"name": "Sect", "delete": true}', 'graphics {"view": "Section 1"}', pre=["t.bimcraft"])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# What a plan cuts and sees
# ---------------------------------------------------------------------------------------------------------------------


def test_view_range_cut_plane(sc):
    """CATCHES: a plan's cut plane not deciding what is cut (a window above it seen, not cut), its view depth not limiting
    what is seen below, or a bad view range accepted."""
    steps(sc, *HOUSE[:5], 'window {"at": [4500, 4000], "sill": 1400}',
          'modify {"id": 100000, "view_range": {"cut": 1000}}', 'elements {"category": "level", "limit": 1}',
          f'render {{"path": "low-cut.svg", {SMALL}}}',
          'modify {"id": 100000, "view_range": {"cut": 99999}}')
    svg(sc, "low-cut.svg")
    assert sc.transcript() == sc.golden()


def test_shaft_and_layer_patterns_close_up(sc):
    """CATCHES: a shaft not drawn as its outline and crossed diagonals through a floor, or a compound wall's cut layers
    without their brick, insulation zigzag, block crosshatch and concrete stipple when wide enough to show them."""
    steps(sc, 'type {"category": "wall", "name": "Concrete 250", "layers": [{"function": "structure", "material": "Concrete", "thickness": 250}]}',
          'wall {"points": [[0,0],[3000,0]], "type": "Exterior - 300mm"}',
          'wall {"points": [[0,1500],[3000,1500]], "type": "Concrete 250"}',
          'floor {"boundary": [[0,-150],[3000,-150],[3000,1625],[0,1625]]}',
          'shaft {"boundary": [[1200,400],[1800,400],[1800,1000],[1200,1000]]}',
          'scale {"view": "Level 1", "scale": 20}',
          'render {"path": "close.svg", "width": 800, "height": 500}')
    svg(sc, "close.svg")
    assert sc.transcript() == sc.golden()


def test_room_separators_and_room_reference_subcategory(sc):
    """CATCHES: room separation lines not bounding rooms or not drawn, the rooms' reference cross shown before it is
    asked for, or hiding rooms not hiding their subcategories too."""
    steps(sc, 'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
          'room_separator {"points": [[3000,0],[3000,4000]]}',
          'room {"point": [1500, 2000]}', 'room {"point": [4500, 2000]}',
          'graphics {"show": ["roomreference"]}',
          f'render {{"path": "rooms.svg", {SMALL}}}',
          'graphics {"hide": ["rooms"]}',
          f'render {{"path": "no-rooms.svg", {SMALL}}}')
    svg(sc, "rooms.svg")
    svg(sc, "no-rooms.svg")
    assert sc.transcript() == sc.golden()


def test_linework_restyles_an_edge(sc):
    """CATCHES: linework restyling the whole element instead of the one edge nearest the point, `invisible` not hiding it,
    or `remove` not taking it off again."""
    steps(sc, *HOUSE[:2],
          'linework {"id": 100002, "at": [3000, -150], "style": "Wide Lines"}',
          'linework {"id": 100006, "at": [3050, 2000], "invisible": true}',
          f'render {{"path": "linework.svg", "width": 300, "height": 200}}',
          'linework {"id": 100002, "at": [3000, -150], "remove": true}',
          'linework {"id": 100002, "at": [3000, -150], "style": "No Such Style"}')
    svg(sc, "linework.svg")
    assert sc.transcript() == sc.golden()


def test_lettering_of_every_kind_of_character(sc):
    """CATCHES: the program's own single-stroke lettering missing or misdrawing digits, punctuation, accented capitals,
    Cyrillic, symbols such as ² ° ± €, lower case drawn as capitals, ß as SS, or an unknown character not drawn as ?."""
    names = ["ÁÉÍÓÚ ÀÈ ÂÊ ÃÕÑ ÄÖÜ ŐŰ ČŠŽ ÅŮ ĀĒ ĂĞ ĖŻ ÇŞ ĄĘ Ø Ł", "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
             "0123456789 .,-+=_/(){}:'\"#×²°±!;*%&[]<>@?\\|~$€³·–—‘’“”„ Æ", "straße 漢字 ok"]
    cmds = ['wall {"points": [[0,0],[8000,0],[8000,8000],[0,8000]], "closed": true}',
            'wall {"points": [[0,2000],[8000,2000]]}', 'wall {"points": [[0,4000],[8000,4000]]}',
            'wall {"points": [[0,6000],[8000,6000]]}']
    for i, n in enumerate(names):
        cmds.append(json.dumps({"point": [4000, 1000 + 2000 * i], "name": n}, ensure_ascii=False).join(["room ", ""]))
    steps(sc, *cmds, 'render {"path": "letters.svg", "width": 1200, "height": 800}')
    svg(sc, "letters.svg")
    assert sc.transcript() == sc.golden()


def test_text_edit_keeps_runs_on_what_did_not_change(sc):
    """CATCHES: `modify` with new text losing a note's bold or italic runs, or not giving what was typed in the format of
    the character before it."""
    steps(sc, 'text {"text": "Hello world", "at": [0, 0], "override_format": true, "runs": [{"from": 0, "to": 5, "bold": true}, {"from": 6, "to": 11, "italic": true}]}',
          'modify {"id": 100002, "text": "Hello big world"}', 'elements {"category": "text"}',
          'modify {"id": 100002, "text": "Hi"}', 'elements {"category": "text"}',
          'text {"text": "x", "at": [0, 0], "override_format": true, "runs": [{"from": 0, "to": 9, "bold": true}]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Standards on sheets
# ---------------------------------------------------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.mark.parametrize("code", ["nbr", "iso", "ansi", "eu", "jis"])
def test_standard_sets_units_pens_and_sheet_layout(sc, code):
    """CATCHES: a technical standard not reporting its name, projection, default units and sheet size, not adapting the
    project's units, line weights and object styles, or a sheet's margins, title box and NBR folding marks wrong."""
    pics = Pictures(sc)
    steps(sc, *HOUSE[:3], *PLEX, f'standard {{"set": "{code}"}}', 'units {}', 'line_weights {}',
          'object_styles {"categories": {}}', 'sheet {"size": "A1"}', 'place {"sheet": "A101", "view": "Level 1"}',
          'render {"view": "A101", "path": "a101.pdf"}')
    pdf_pages(sc, pics, "a101.pdf")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_standard_adapt_flags_and_aliases(sc):
    """CATCHES: `adapt_*` flags not limiting what a standard changes, a standard's other names (abnt, japan, usa) not
    accepted, or a flag that isn't true or false accepted."""
    steps(sc, 'standard {"set": "abnt", "adapt_all": false, "adapt_units": true}', 'units {}', 'line_weights {}',
          'standard {"set": "usa", "adapt_all": false, "adapt_line_weights": true}', 'units {}', 'line_weights {}',
          'standard {"set": "japan", "adapt_object_styles": false}', 'units {}',
          'standard {"set": "iso", "adapt_units": "yes"}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# More of what plans, sections and elevations draw
# ---------------------------------------------------------------------------------------------------------------------


def test_regions_overlapping_masks_and_holes(sc):
    """CATCHES: a region's hole filled, a masking region not hiding what is under it (but hiding a later region's model
    lines), or overlapping regions composited in the wrong order."""
    steps(sc, *HOUSE[:5],
          'filled_region {"sketch": [[[2000,-1000],[4000,-1000]],[[4000,-1000],[4000,1000]],[[4000,1000],[2000,1000]],[[2000,1000],[2000,-1000]]], "type": "Masking"}',
          'filled_region {"sketch": [[[1000,500],[5000,500]],[[5000,500],[5000,3500]],[[5000,3500],[1000,3500]],[[1000,3500],[1000,500]],'
          '[[2500,1500],[3500,1500]],[[3500,1500],[3500,2500]],[[3500,2500],[2500,2500]],[[2500,2500],[2500,1500]]], "type": "Sand"}',
          'filled_region {"sketch": [[[4500,3000],[6500,3000]],[[6500,3000],[6500,4500]],[[6500,4500],[4500,4500]],[[4500,4500],[4500,3000]]], "type": "Solid Black", "line_style": "Wide Lines"}',
          'elements {"category": "region"}',
          f'render {{"path": "regions.svg", {SMALL}}}')
    svg(sc, "regions.svg")
    assert sc.transcript() == sc.golden()


def test_camera_mark_in_plan(sc):
    """CATCHES: a camera made by `camera` not shown in its level's plan as its mark (body, lens, sight line and name), or
    its eye, target and lens not read back."""
    steps(sc, *HOUSE[:2], 'camera {"eye": [-2000, -2000, 1600], "target": [3000, 2000, 1200], "name": "Entry"}',
          'camera {"view": "Entry"}', 'camera {"eye": [7000, 5000, 1500], "target": [3000, 2000, 1500], "lens": 24}',
          f'render {{"path": "cameras.svg", {SMALL}}}',
          'camera {"eye": [0, 0, 0], "target": [0, 0, 0]}')
    svg(sc, "cameras.svg")
    assert sc.transcript() == sc.golden()


def test_elevations_through_a_point_and_along_a_line(sc):
    """CATCHES: an elevation `at` a point not facing the side it is on, one along a line not looking to its left, a
    cropped elevation not cropped, or their marks missing from the plan."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, 'elevation {"at": [3000, 6000]}', 'elevation {"start": [7500, -500], "end": [7500, 4500], "name": "Side"}',
          'elevation {"facing": "west", "depth": 2000}',
          'crop {"view": "Side", "region": [[500, -200], [3500, 2500]]}',
          'elements {"category": "elevation"}',
          f'render {{"path": "marks.svg", {SMALL}}}',
          f'render {{"view": "Side", "path": "side.png", {SMALL}}}',
          f'render {{"view": "North", "path": "north.png", {SMALL}}}')
    svg(sc, "marks.svg")
    pics.png("side.png")
    pics.png("north.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_section_graphics_detail_and_scale(sc):
    """CATCHES: a section ignoring its own Visibility/Graphics (hidden doors, a walls' cut fill), its detail level or its
    scale; or the section picture of the same view by id differing from by name."""
    pics = Pictures(sc)
    steps(sc, *HOUSE, 'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'graphics {"view": "Section 1", "hide": ["doors", "levels"], "categories": {"walls": {"cut": {"fill": [200, 40, 40]}}}}',
          'detail {"view": "Section 1", "detail": "coarse"}', 'scale {"view": "Section 1", "scale": 50}',
          f'render {{"view": "Section 1", "path": "a.png", {SMALL}}}',
          f'render {{"view": 100015, "path": "b.png", {SMALL}}}')
    sc.note(f"by id is by name: {(sc.workdir / 'a.png').read_bytes() == (sc.workdir / 'b.png').read_bytes()}")
    pics.png("a.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_dependent_view_shows_parent_annotation_and_own_crop(sc):
    """CATCHES: a dependent view not following its parent's graphics, not showing the parent's notes beside its own, or
    its own crop not limiting it; or a detailing copy's annotation not its own."""
    steps(sc, *HOUSE, *PLEX, 'text {"text": "Parent note", "at": [500, 3500]}',
          'duplicate_view {"view": "Level 1", "mode": "dependent", "name": "West half"}',
          'crop {"view": "West half", "region": [[-500, -500], [3200, 4500]]}',
          'text {"text": "Own note", "at": [500, 1000], "view": "West half"}',
          'graphics {"view": "Level 1", "hide": ["rooms"]}',
          f'render {{"view": "West half", "path": "dependent.svg", {SMALL}}}',
          'duplicate_view {"view": "Level 1", "mode": "detailing", "name": "Notes copy"}',
          'elements {"category": "text"}')
    svg(sc, "dependent.svg")
    assert sc.transcript() == sc.golden()


def test_beams_and_columns_above_the_cut(sc):
    """CATCHES: a beam above a plan's cut plane not drawn, or one hidden over a ceiling still drawn, or a structural column
    not cut in poché."""
    steps(sc, 'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
          'structural_column {"at": [3000, 2000]}',
          'beam {"points": [[0, 2000], [6000, 2000]], "offset": 2900}',
          'beam {"points": [[3000, 0], [3000, 4000]], "offset": 2900, "type": "Steel Tube 150"}',
          'ceiling {"boundary": [[3500, 2500], [5500, 2500], [5500, 3500], [3500, 3500]], "offset": 2500}',
          'modify {"id": 100000, "view_range": {"top": 3000}}',
          f'render {{"path": "structure.svg", {SMALL}}}')
    svg(sc, "structure.svg")
    assert sc.transcript() == sc.golden()


def test_notes_on_a_sheet_and_in_a_section(sc):
    """CATCHES: a note, a detail line or a filled region on a sheet not placed in paper mm, a note in a section not placed
    along its line and up, or any of them not printed in the sheet's PDF."""
    pics = Pictures(sc)
    steps(sc, *HOUSE[:2], *PLEX, 'section {"start": [-1000, 2000], "end": [7000, 2000]}',
          'sheet {"size": "A4"}', 'text {"text": "General notes:\\n1. Check on site.", "at": [20, 190], "view": "A101", "type": "3.5mm"}',
          'detail_line {"points": [[20, 170], [120, 170]], "view": "A101", "style": "Wide Lines"}',
          'filled_region {"sketch": [[[20,150],[60,150]],[[60,150],[60,160]],[[60,160],[20,160]],[[20,160],[20,150]]], "view": "A101", "type": "Crosshatch"}',
          'text {"text": "Cut here", "at": [2000, 1500], "view": "Section 1"}',
          'elements {"category": "text"}',
          'render {"view": "A101", "path": "a101.pdf"}',
          f'render {{"view": "Section 1", "path": "section.png", {SMALL}}}')
    pdf_pages(sc, pics, "a101.pdf")
    pics.png("section.png")
    assert sc.transcript() == sc.golden()
    pics.assert_match()


def test_dimension_constraints_that_cannot_be_kept(sc):
    """CATCHES: equality on a dimension whose walls a locked dimension holds, or on locked segments of different lengths,
    being accepted instead of refused with nothing changed; or a move along the walls, or a turn that keeps the locked
    lengths, being refused."""
    steps(sc, *THREE_WALLS,
          'dimension {"refs": [{"id": 100002}, {"id": 100003}, {"id": 100004}], "at": [3500, -800]}',
          'dimension {"refs": [{"id": 100002, "face": "left"}, {"id": 100002, "face": "right"}, {"id": 100004}], "at": [3500, 4800]}',
          'dimension_constraint {"id": 100005, "locked": [0, 1]}',
          post=["--save", "locked.bimcraft"])
    for bad in ['rotate {"ids": [100002, 100004], "about": [3500, 2000], "angle": 180}',
                'dimension_constraint {"id": 100006, "equal": true}',
                'dimension_constraint {"id": 100005, "equal": true}']:
        steps(sc, bad, pre=["locked.bimcraft"])
    steps(sc, 'move {"ids": [100004], "by": [0, 500]}', 'elements {"category": "wall"}', pre=["locked.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_family_component_categories_in_graphics(sc):
    """CATCHES: `component` overrides not reaching every family category under it, a family category's own override not
    laid over it, a starter electrical template not hiding or halftoning its devices, or hiding `component` not hiding
    them all."""
    steps(sc, *HOUSE[:1],
          'component {"family": "Sofa", "at": [1500, 1000]}', 'component {"family": "Base Cabinet", "at": [4500, 3500]}',
          'component {"family": "Outlet", "at": [3000, 150]}', 'component {"family": "Ceiling Luminaire", "at": [3000, 2000]}',
          'graphics {"categories": {"component": {"halftone": true, "projection": {"color": [0, 0, 200]}}, "furniture": {"projection": {"color": [200, 0, 0]}}}}',
          f'render {{"path": "components.svg", {SMALL}}}',
          'duplicate_view {"view": "Level 1", "name": "Power"}', 'graphics {"view": "Power", "reset": true}',
          'graphics {"view": "Power", "template": "Electrical Lighting"}',
          f'render {{"view": "Power", "path": "lighting.svg", {SMALL}}}',
          'graphics {"hide": ["component"]}',
          f'render {{"path": "none.svg", {SMALL}}}')
    for f in ["components.svg", "lighting.svg", "none.svg"]:
        svg(sc, f)
    assert sc.transcript() == sc.golden()


def test_view_filter_rules_pick_by_numbers_and_values(sc):
    """CATCHES: a view filter's numeric comparisons, has-value and text rules picking the wrong elements, a filter of
    several categories without rules not picking all of them, or one reading a filter that isn't there succeeding."""
    steps(sc, *HOUSE,
          'filter {"name": "Long walls", "categories": ["walls"], "rules": [{"field": "Length", "op": "greater-or-equal", "value": 4000}]}',
          'filter {"name": "Short walls", "categories": ["walls"], "rules": [{"field": "Length", "op": "less", "value": 4500}, {"field": "Type", "op": "not-contains", "value": "Interior"}]}',
          'filter {"name": "Openings", "categories": ["doors", "windows"]}',
          'filter {"name": "Named", "categories": ["rooms"], "rules": [{"field": "Name", "op": "has-value"}, {"field": "Name", "op": "ends-with", "value": "ING"}]}',
          'filter {"name": "Long walls", "rules": [{"field": "Length", "op": "greater", "value": 5000}]}',
          'graphics {"filters": [{"filter": "Openings", "projection": {"color": [0, 0, 255]}, "cut": {"color": [0, 0, 255]}}, {"filter": "Long walls", "halftone": true}]}',
          f'render {{"path": "filters.svg", {SMALL}}}')
    svg(sc, "filters.svg")
    steps(sc, 'filter {"name": "Nope"}')
    assert sc.transcript() == sc.golden()
