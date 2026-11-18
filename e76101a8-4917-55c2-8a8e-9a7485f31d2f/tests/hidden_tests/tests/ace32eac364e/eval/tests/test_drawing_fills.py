"""Fill patterns, filled region types and filled regions: making them, PAT files in and out, patterns made of lines drawn,
their errors, and how a plan draws them (the SVG a plan saves to)."""

import json
import re
from concurrent.futures import ThreadPoolExecutor

from conftest import normalize, png_pixels


def _script(run, workdir, lines, *extra, name="s.txt"):
    """`run --script` over `lines` (one `id {json}` each) written to `name` in the working directory."""
    (workdir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run(["run", "--script", name, *extra])


def _outcome(r):
    # A file written atomically names its temporary file, at a random absolute path, when the write fails.
    err = re.sub(r' at path "[^"]*"', ' at path "<TMP>"', r.stderr.decode("utf-8", "replace"))
    return (f"exit: {r.returncode}\n--- stdout\n" + normalize(r.stdout.decode("utf-8", "replace"))
            + "--- stderr\n" + normalize(err))


def _rounded(text):
    """`text` with each number of ten or more decimals rounded to six: what trigonometry gives may differ in its last
    bit from one machine to another, and the six decimals a PAT file keeps don't."""
    return re.sub(r"-?\d+\.\d{10,}", lambda m: f"{float(m.group()):.6f}", text)


def _sweep(run, workdir, setup, cases):
    """Each case run as the last line of a script after `setup`, each in a run of its own (a few at a time, each with a
    script of its own); their outcomes in one text, in the order of the cases."""
    def one(i):
        r = _script(run, workdir, [*setup, cases[i]], name=f"case{i}.txt")
        return f"$ {cases[i][:200]}\n{_outcome(r)}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        return "\n".join(pool.map(one, range(len(cases))))


def _cmd(name, params):
    return f"{name} {json.dumps(params)}"


def _box(x0, y0, x1, y1):
    """A sketch of the rectangle between two corners, as four lines."""
    return [[[x0, y0], [x1, y0]], [[x1, y0], [x1, y1]], [[x1, y1], [x0, y1]], [[x0, y1], [x0, y0]]]


def test_fill_patterns_are_made_retargeted_renamed_and_deleted(run, workdir, golden):
    """CATCHES: a rewrite whose starter fill patterns or region types differ, that doesn't keep what a changed pattern
    isn't given, rescales a pattern that wasn't drawn from lines, doesn't carry a pattern's rename into the region types
    that fill with it, or whose replies are shaped differently."""
    r = _script(run, workdir, [
        "fill_pattern {}",
        "filled_region_type {}",
        _cmd("fill_pattern", {"name": "Diag 45", "lines": [{"angle": 45, "spacing": 2}]}),
        _cmd("fill_pattern", {"name": "Planks", "target": "model", "lines": [
            {"angle": 0, "spacing": 150}, {"angle": 90, "spacing": 150, "shift": 75, "origin": [10, 20], "dashes": [150, -150]}]}),
        _cmd("fill_pattern", {"name": "Diag 45", "target": "model"}),
        _cmd("fill_pattern", {"name": "Diag 45", "drawn": 20}),
        _cmd("fill_pattern", {"name": "Diag 45", "target": "drafting"}),
        _cmd("fill_pattern", {"name": "Diag 45", "drawn": None, "lines": [{"angle": 135, "spacing": 3, "dashes": [2, -1, 0, -1]}]}),
        _cmd("fill_pattern", {"name": "Plain", "target": "drafting"}),
        _cmd("filled_region_type", {"name": "Floorboards", "foreground": "Planks", "foreground_color": "#804000",
                                    "background": "Solid fill", "background_color": [255, 240, 200]}),
        _cmd("fill_pattern", {"name": "Planks", "rename": "Boards"}),
        _cmd("filled_region_type", {"name": "Floorboards"}),
        _cmd("fill_pattern", {"name": "Plain", "delete": True}),
        _cmd("fill_pattern", {"name": "Diag 45"}),
    ])
    golden.check_run(r, "patterns.txt")


FILL_PATTERN_ERRORS = [
    _cmd("fill_pattern", {"name": "Nothing"}),
    _cmd("fill_pattern", {"name": "Tight", "lines": [{"angle": 0, "spacing": 0.001}]}),
    _cmd("fill_pattern", {"name": "Wide", "lines": [{"angle": 0, "spacing": 1e7}]}),
    _cmd("fill_pattern", {"name": "Far", "lines": [{"angle": 0, "spacing": 1, "origin": [2e6, 0]}]}),
    _cmd("fill_pattern", {"name": "Gaps", "lines": [{"angle": 0, "spacing": 1, "dashes": [-1, -2]}]}),
    _cmd("fill_pattern", {"name": "Solidly", "lines": [{"angle": 0, "spacing": 1, "dashes": [1, 2]}]}),
    _cmd("fill_pattern", {"name": "Many", "lines": [{"angle": i, "spacing": 1} for i in range(257)]}),
    _cmd("fill_pattern", {"name": "Odd", "lines": [{"angle": 0}]}),
    _cmd("fill_pattern", {"name": "Odd", "lines": [{"angle": 0, "spacing": 1, "colour": 2}]}),
    _cmd("fill_pattern", {"name": "Odd", "target": "paper", "lines": []}),
    _cmd("fill_pattern", {"name": "Sand", "drawn": "big"}),
    _cmd("fill_pattern", {"name": "Sand", "drawn": 0}),
    _cmd("fill_pattern", {"name": "Sand", "rename": "Crosshatch"}),
    _cmd("fill_pattern", {"name": "Sand", "delete": True}),
    _cmd("fill_pattern", {"name": "Tile 300", "delete": True}),
    _cmd("fill_pattern", {"name": "Gone", "delete": True}),
    _cmd("fill_pattern", {"name": "Sand", "scale": 2}),
    _cmd("fill_pattern", {"name": "Slid", "lines": [{"angle": 0, "spacing": 1, "shift": 2e5}]}),
    _cmd("fill_pattern", {"name": "Busy", "lines": [{"angle": 0, "spacing": 1, "dashes": [1, -1] * 8 + [1]}]}),
    _cmd("fill_pattern", {"name": "Huge", "lines": [{"angle": 0, "spacing": 1, "dashes": [2e5, -1]}]}),
]


def test_fill_pattern_errors(run, workdir, golden):
    """CATCHES: a rewrite that accepts lines closer or wider than a pattern allows, an origin too far, dashes of spaces
    only or of no space, too many families, a family without a spacing, an unknown target, a drawn scale that isn't a
    positive number, a rename over another pattern, or deletes a pattern a region type or a material uses; or that words
    those refusals differently."""
    setup = [_cmd("material", {"name": "Tiled", "surface": "Tile 300"})]
    golden.check(_sweep(run, workdir, setup, FILL_PATTERN_ERRORS), "fill_pattern_errors.txt")


def test_filled_region_types_and_regions(run, workdir, golden):
    """CATCHES: a rewrite whose region types don't keep what they aren't given, whose rename doesn't reach the regions of
    the type, whose regions measure a sketch with a hole and an island differently, take another default type or line
    style, or are listed in `elements` with other fields."""
    r = _script(run, workdir, [
        _cmd("filled_region_type", {"name": "Tiles", "foreground": "Tile 300", "background": "Sand",
                                    "background_color": "#c0c0ff"}),
        _cmd("filled_region_type", {"name": "Tiles", "masking": True, "foreground_color": [0, 0, 128]}),
        _cmd("filled_region_type", {"name": "Tiles", "background": None}),
        _cmd("filled_region_type", {"name": "Blank"}),
        _cmd("filled_region", {"sketch": _box(0, 0, 3000, 2000) + _box(1000, 500, 2000, 1500) + _box(1250, 750, 1750, 1250),
                               "type": "Tiles"}),
        _cmd("filled_region", {"sketch": [[[4000, 0], [5000, 0]], [[5000, 0], [4500, 1000]], [[4500, 1000], [4000, 0]]],
                               "line_style": None}),
        _cmd("filled_region", {"sketch": _box(6000, 0, 7000, 1000), "line_style": "Invisible", "type": "Masking"}),
        _cmd("filled_region", {"sketch": _box(8000, 0, 9000, 1000), "line_style": "Wide Lines", "type": "Blank"}),
        _cmd("filled_region_type", {"name": "Tiles", "rename": "Floor Tiles"}),
        'elements {"category": "region"}',
        _cmd("filled_region_type", {"name": "Spare", "foreground": "Vertical"}),
        _cmd("filled_region_type", {"name": "Spare", "delete": True}),
        _cmd("filled_region", {"sketch": _box(0, 0, 100, 100)}),
        'filled_region_type {}',
    ])
    golden.check_run(r, "regions.txt")


REGION_ERRORS = [
    _cmd("filled_region_type", {"name": "Bad", "foreground": "Plaid"}),
    _cmd("filled_region_type", {"name": "Bad", "background": 3}),
    _cmd("filled_region_type", {"name": "Bad", "foreground_color": "blue"}),
    _cmd("filled_region_type", {"name": "Bad", "masking": "yes"}),
    _cmd("filled_region_type", {"name": "Sand", "rename": "Brick"}),
    _cmd("filled_region_type", {"name": "Crosshatch", "delete": True}),
    _cmd("filled_region_type", {"name": "Gone", "delete": True}),
    _cmd("filled_region_type", {"name": "Sand", "pattern": "Sand"}),
    "filled_region {}",
    _cmd("filled_region", {"sketch": [[[0, 0], [1000, 0]], [[1000, 0], [1000, 1000]]]}),
    _cmd("filled_region", {"sketch": _box(0, 0, 10, 10), "type": "Plaid"}),
    _cmd("filled_region", {"sketch": _box(0, 0, 10, 10), "line_style": "Faint"}),
    _cmd("filled_region", {"sketch": _box(0, 0, 10, 10), "line_style": 4}),
    _cmd("filled_region", {"sketch": _box(0, 0, 10, 10), "view": "Nowhere"}),
    _cmd("filled_region", {"sketch": _box(0, 0, 10, 10), "colour": "red"}),
    _cmd("filled_region", {"sketch": "a square"}),
]


def test_filled_region_type_and_region_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes a pattern the project hasn't or one that isn't a name, a colour that isn't one, a
    rename over another type, deletes a type a region is of, or makes a region whose sketch doesn't close, of an unknown
    type, line style or view; or that words those refusals differently."""
    setup = [_cmd("filled_region", {"sketch": _box(0, 0, 1000, 1000), "type": "Crosshatch"})]
    golden.check(_sweep(run, workdir, setup, REGION_ERRORS), "region_errors.txt")


REGIONS_DRAWN = [
    'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
    _cmd("filled_region", {"sketch": _box(500, 500, 2500, 1800), "type": "Crosshatch"}),
    _cmd("filled_region", {"sketch": _box(3000, 500, 5500, 1800) + _box(3500, 900, 4500, 1400), "type": "Brick"}),
    _cmd("filled_region", {"sketch": _box(500, 2200, 2500, 3500), "type": "Sand", "line_style": "Wide Lines"}),
    _cmd("filled_region", {"sketch": _box(5500, 2500, 6500, 3500), "type": "Masking", "line_style": None}),
    _cmd("filled_region", {"sketch": [[[3000, 2200], [5000, 2200]], [[5000, 2200], [4000, 3600]],
                                      [[4000, 3600], [3000, 2200]]], "type": "Solid Black"}),
    'text {"text": "OVER", "at": [5600, 3300]}',
    'text_type {"name": "2.5mm", "font": "BIMCraft Lettering"}',
]


def test_filled_regions_drawn_at_two_scales(run, workdir, golden):
    """CATCHES: a rewrite that draws a region's pattern in other strokes (a drafting pattern the same on paper at any
    scale, a model pattern the same in the building), leaves a hole filled, draws a boundary in another style, doesn't
    hide the wall under a masking region or hides the note over it."""
    r = _script(run, workdir, REGIONS_DRAWN, "--save", "at100.svg", "--cmd", 'scale {"view": "Level 1", "scale": 50}',
                "--save", "at50.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "at100.svg").read_text(), "regions_100.svg")
    golden.check((workdir / "at50.svg").read_text(), "regions_50.svg")


def test_a_pattern_too_dense_for_the_view_is_left_out_with_a_note(run, workdir, golden):
    """CATCHES: a rewrite that draws a pattern of more strokes than a view holds (or hangs on it) instead of leaving it
    out, or that doesn't say so in the reply's `notes`."""
    r = _script(run, workdir, [
        _cmd("fill_pattern", {"name": "Dotty", "target": "model", "lines": [{"angle": 0, "spacing": 100, "dashes": [1, -1]}]}),
        _cmd("filled_region_type", {"name": "Dotty", "foreground": "Dotty"}),
        _cmd("filled_region", {"sketch": _box(0, 0, 100000, 50000), "type": "Dotty"}),
        _cmd("render", {"view": "Level 1", "path": "dense.svg"}),
    ])
    golden.check_run(r, "dense_run.txt")
    golden.check((workdir / "dense.svg").read_text(), "dense.svg")


PAT = """;%UNITS=INCH
;; a file of patterns, some of them broken
*Lines45, 45 degree lines
45, 0,0, 0,0.125
*Bricks, running bond ;%TYPE=MODEL
;%TYPE=MODEL
0, 0,0, 0,3
90, 0,0, 3,4, 3,-3
*Empty, nothing here
*Stacked, offset zero
0, 0,0, 1,0
*Ghost, only spaces
0, 0,0, 0,1, -1,-1
*Garbled
0, zero, 0, 0, 1
*Lines45
0, 0,0, 0,1
;%UNITS=MM
*Dots
0, 0,0, 0.5,1, 0,-1
*Sand, already in the project
0, 0,0, 0,2
"""


def test_import_fill_patterns_from_text_then_export_them(run, workdir, golden):
    """CATCHES: a rewrite that reads a PAT file's inches, `;%TYPE=MODEL`, dashes and negative offsets wrongly, keeps a
    pattern it should leave out (no lines, an offset of 0, all spaces, a line that isn't numbers, a name twice, a name
    the project has) or words why differently, replaces without `replace`, or writes a PAT file differently."""
    r = _script(run, workdir, [
        _cmd("import_fill_patterns", {"text": PAT}),
        _cmd("import_fill_patterns", {"text": "*Sand\n0, 0,0, 0,3\n*Lines45\n90, 0,0, 0,1\n", "replace": True}),
        _cmd("fill_pattern", {"name": "Bricks"}),
        _cmd("export_fill_patterns", {"names": ["Lines45", "Bricks", "Dots", "Sand"]}),
        _cmd("export_fill_patterns", {}),
    ])
    golden.check_run(r, "import_text.txt")


def test_import_fill_patterns_from_a_file_and_export_to_a_file(run, workdir, golden):
    """CATCHES: a rewrite that reads a PAT file at `path` differently from its text, doesn't read a byte that isn't UTF-8
    as its Latin-1 letter, or writes a different PAT file to `path`."""
    (workdir / "in.pat").write_bytes(b"*Caf\xe9 tiles, Latin-1 name\n0, 0,0, 0,6\n90, 0,0, 0,6\n*Plain\n30, 1,2, 0,4, 2,-1\n")
    r = _script(run, workdir, [
        _cmd("import_fill_patterns", {"path": "in.pat"}),
        _cmd("export_fill_patterns", {"path": "out.pat", "names": ["Café tiles", "Plain", "Brick 225 x 75"]}),
    ])
    golden.check_run(r, "import_file.txt")
    golden.check((workdir / "out.pat").read_text(encoding="utf-8"), "out.pat")


PAT_ERRORS = [
    "import_fill_patterns {}",
    _cmd("import_fill_patterns", {"text": "*A\n0,0,0,0,1\n", "path": "a.pat"}),
    _cmd("import_fill_patterns", {"text": 42}),
    _cmd("import_fill_patterns", {"path": "missing.pat"}),
    _cmd("import_fill_patterns", {"text": "", "merge": True}),
    _cmd("export_fill_patterns", {"names": ["Sand", "Plaid"]}),
    _cmd("export_fill_patterns", {"names": "Sand"}),
    _cmd("export_fill_patterns", {"path": "nodir/out.pat"}),
    _cmd("export_fill_patterns", {"format": "pat"}),
]


def test_import_and_export_errors(run, workdir, golden):
    """CATCHES: a rewrite that imports with neither or both of `path` and `text`, takes a number for text, opens a file
    that isn't there quietly, exports a pattern the project hasn't, takes a name for a list, or writes into a missing
    folder; or that words the refusal differently."""
    golden.check(_sweep(run, workdir, [], PAT_ERRORS), "pat_errors.txt")


MADE = [
    'detail_line {"start": [0, 0], "end": [1000, 0]}',
    'detail_line {"start": [0, 0], "end": [1000, 1000]}',
    'detail_line {"start": [500, 0], "end": [500, 1000]}',
    'detail_line {"start": [0, 1000], "end": [2000, 0]}',
    'detail_line {"start": [200, 300], "end": [700, 300]}',
]


def test_make_fill_pattern_from_lines_drawn(run, workdir, golden):
    """CATCHES: a rewrite whose pattern made of lines has other families (a line on the tile's edge and its copy one
    family, a sloped line turned to whole tiles, a short line dashed to its repeat, what lies outside the tile cut off),
    doesn't keep the scale a drafting one was drawn at, or rescales it differently when it is turned to a model one."""
    r = _script(run, workdir, [
        *MADE,
        _cmd("make_fill_pattern", {"ids": [100002, 100003, 100004, 100005, 100006], "from": [0, 0], "to": [1000, 1000],
                                   "name": "Made"}),
        _cmd("make_fill_pattern", {"ids": [100002, 100004, 100006], "from": [1000, 1000], "to": [0, 0], "name": "Paper",
                                   "target": "drafting"}),
        _cmd("fill_pattern", {"name": "Paper", "target": "model"}),
        _cmd("filled_region_type", {"name": "Made", "foreground": "Made"}),
        _cmd("filled_region", {"sketch": _box(0, -3000, 3000, -1000), "type": "Made"}),
        _cmd("export_fill_patterns", {"names": ["Made", "Paper"]}),
    ], "--save", "made.svg")
    golden.check(_rounded(_outcome(r)), "made.txt")
    golden.check((workdir / "made.svg").read_text(), "made.svg")


MAKE_ERRORS = [
    _cmd("make_fill_pattern", {"from": [0, 0], "to": [1000, 1000], "name": "X"}),
    _cmd("make_fill_pattern", {"ids": [100002], "from": [0, 0], "to": [1000, 1000]}),
    _cmd("make_fill_pattern", {"ids": [100002], "from": [0, 0], "to": [1000, 1000], "name": "Sand"}),
    _cmd("make_fill_pattern", {"ids": [100002], "from": [0, 0], "to": [1000, 0.01], "name": "X"}),
    _cmd("make_fill_pattern", {"ids": [100003], "from": [0, 0], "to": [1000, 1000], "name": "X"}),
    _cmd("make_fill_pattern", {"ids": [100002], "from": [0, 0], "to": [1000, 1000], "name": "X", "target": "paper"}),
    _cmd("make_fill_pattern", {"ids": [123456], "from": [0, 0], "to": [1000, 1000], "name": "X"}),
    _cmd("make_fill_pattern", {"ids": [100002], "to": [1000, 1000], "name": "X"}),
    _cmd("make_fill_pattern", {"ids": [100002], "from": [0, 0], "to": [1000, 1000], "name": "X", "scale": 1}),
    _cmd("make_fill_pattern", {"ids": [100002], "from": [5000, 5000], "to": [6000, 6000], "name": "X"}),
]


def test_make_fill_pattern_errors(run, workdir, golden):
    """CATCHES: a rewrite that makes a pattern without ids, a name, or a corner, over a name the project has, from a
    tile too thin, of a wall instead of detail lines, of an element there isn't, or of an unknown target; or that words
    the refusal differently."""
    setup = ['detail_line {"start": [0, 0], "end": [1000, 0]}', 'wall {"points": [[0, 500], [1000, 500]]}']
    golden.check(_sweep(run, workdir, setup, MAKE_ERRORS), "make_errors.txt")


def test_regions_keep_the_model_ink_above_them(run, workdir, golden):
    """CATCHES: a rewrite whose non-masking region hides the walls, the door's swing, the cut poché, a stair's dashed
    treads, a beam's dashed outline or a mass's dashed edge under it instead of keeping their lines (and their dashes'
    phase) over its fill, keeps the lines a masking region drawn before it hides, or lifts lines out of another
    region's area."""
    r = _script(run, workdir, [
        'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
        'door {"at": [3000, 0]}',
        'wall {"points": [[3000, 0], [3000, 4000]]}',
        'beam {"points": [[2500, 2500], [5500, 2500]], "offset": 2800}',
        'stair {"start": [3500, 700], "end": [5500, 700], "width": 800}',
        'mass {"boundary": [[4500, 1500], [5500, 1500], [5500, 2200], [4500, 2200]], "height": 2000}',
        _cmd("filled_region", {"sketch": _box(4500, 2500, 7000, 4500), "type": "Masking", "line_style": None}),
        _cmd("filled_region_type", {"name": "Wash", "background": "Solid fill", "background_color": "#ffe0a0",
                                    "foreground": "Diagonal Up", "foreground_color": [160, 80, 0]}),
        _cmd("filled_region", {"sketch": _box(2000, -500, 6500, 3000), "type": "Wash"}),
        _cmd("filled_region", {"sketch": _box(-500, 1000, 1500, 3500) + _box(-200, 1500, 300, 2500), "type": "Solid Black"}),
    ], "--save", "ink.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "ink.svg").read_text(), "ink.svg")


def test_annotation_in_a_section(run, workdir, golden):
    """CATCHES: a rewrite that puts a section's detail lines, regions, notes and spot elevations elsewhere along and up
    it, doesn't keep the section's own lines over a non-masking region, or doesn't hide them under a masking one."""
    r = _script(run, workdir, [
        'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
        'floor {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]}',
        'section {"start": [3000, -2000], "end": [3000, 6000], "name": "S"}',
        'text_type {"name": "2.5mm", "font": "BIMCraft Lettering"}',
        _cmd("detail_line", {"start": [1000, 500], "end": [5000, 2500], "view": "S", "style": "Wide Lines"}),
        _cmd("filled_region", {"sketch": _box(1500, -200, 3500, 1500), "view": "S", "type": "Diagonal Up"}),
        _cmd("filled_region", {"sketch": _box(5000, 1000, 6500, 3500), "view": "S", "type": "Masking"}),
        _cmd("text", {"text": "SECTION NOTE", "at": [500, 4000], "view": "S", "leader": [2000, 3000]}),
        'spot {"at": [1000, 3000], "view": "S"}',
        'elements {"category": "region"}',
        _cmd("render", {"view": "S", "path": "s.png", "width": 800, "height": 500}),
    ])
    golden.check_run(r, "section_run.txt")
    golden.check(png_pixels((workdir / "s.png").read_bytes()), "section_png.txt")


def _hostile_pat():
    """A PAT file of 2003 patterns: one with a family of more dashes than a family holds, one of more families than a
    pattern holds, one made a model pattern then a drafting one again, then plain ones past the 2000 a file is read to."""
    out = ["*TooManyDashes", "0, 0,0, 0,1, " + ", ".join(["1,-1"] * 9),
           "*TooManyFamilies"] + [f"{i % 180}, 0,0, 0,1" for i in range(257)] + [
           "*Retyped", ";%TYPE=MODEL", ";%TYPE=DRAFTING", "45, 0,0, 0,2"]
    for i in range(2000):
        out += [f"*Plain{i:04d}", "0, 0,0, 0,1"]
    return "\n".join(out) + "\n"


def test_import_a_hostile_pat_file(run, workdir, golden):
    """CATCHES: a rewrite that reads more than 2000 patterns of a file, doesn't count the rest, keeps a family of more
    than 16 dashes or a pattern of more than 256 families, names more than the first 100 left out, or doesn't let a
    later `;%TYPE` line win."""
    r = _script(run, workdir, [_cmd("import_fill_patterns", {"text": _hostile_pat()}), _cmd("fill_pattern", {"name": "Retyped"})])
    assert r.returncode == 0, r.stderr.decode()
    first, second = r.stdout.decode().splitlines()
    reply = json.loads(first)
    imported = reply.pop("imported")
    summary = {"imported": len(imported), "first": imported[:3], "last": imported[-3:], **reply}
    golden.check(json.dumps(summary, indent=1, ensure_ascii=False) + "\n" + second + "\n", "hostile_pat.txt")
