"""Drafting and the modify tools: detail lines in every shape, line patterns and styles, fill patterns, filled regions,
detail groups, Linework, and the tools that move, copy, turn, trim, split, join and reshape what is drawn."""

import json

from conftest import png_pixels

LINES = 'elements {"category": "line"}'
PLAN_SVG = 'render {"view": "Level 1", "path": "plan.svg"}'


def png_shape(sc, path):
    """Record a PNG the program wrote by its size and colour type only: its anti-aliased pixels come from a rasterizer whose
    SIMD arithmetic differs between x86-64 and arm64, so a pixel digest would not be portable (plans are checked as SVG)."""
    w, h, kind, _ = png_pixels((sc.workdir / path).read_bytes())
    sc.note(f"=== file {path}\npng {w}x{h} {kind}")


def lines_and_plan(sc, *commands, pre=()):
    """Run the commands, then list the detail lines and draw Level 1's plan to plan.svg (recorded)."""
    sc.cmds(*commands, LINES, PLAN_SVG, pre=pre)
    sc.file("plan.svg")


# ---------------------------------------------------------------------------
# Detail lines
# ---------------------------------------------------------------------------


def test_detail_line_every_shape_in_a_plan(sc):
    """CATCHES: a detail line built in the wrong shape, with the wrong length, the wrong arc for a `through` point, a circle
    or ellipse drawn with wrong radii, angle or span, or a spline drawn off its control or fit points in the plan."""
    lines_and_plan(
        sc,
        'detail_line {"points": [[0,0],[1000,0],[1000,1000]]}',
        'detail_line {"start": [2000,0], "end": [4000,0]}',
        'detail_line {"start": [0,2000], "end": [2000,2000], "arc": 90}',
        'detail_line {"start": [3000,2000], "end": [5000,2000], "through": [4000,2500]}',
        'detail_line {"centre": [-2000,0], "radius": 500, "centre_mark": true}',
        'detail_line {"centre": [-2000,3000], "radii": [800,400], "angle": 30}',
        'detail_line {"centre": [0,4000], "radii": [800,400], "angle": 30, "span": [0,180], "centre_mark": true}',
        'detail_line {"control": [[0,6000],[1000,7000],[2000,6000],[3000,7000]]}',
        'detail_line {"fit": [[4000,6000],[5000,7000],[6000,6000]], "start_tangent": [1,0], "end_tangent": [0,-1]}',
        'detail_line {"points": [[6000,0],[7000,0],[7000,1000],[6000,1000]], "arcs": [0,90,0,-45], "closed": true}',
    )
    assert sc.transcript() == sc.golden()


def test_detail_line_spline_with_knots(sc):
    """CATCHES: knots given to a control-point spline being ignored or read as another degree, so its points, length or
    drawing differ from a clamped spline's."""
    lines_and_plan(
        sc,
        'detail_line {"control": [[0,0],[1000,2000],[2000,0],[3000,2000],[4000,0]], "knots": [0,0,0,1,2,3,3,3]}',
        'detail_line {"control": [[0,3000],[1000,5000],[2000,3000],[3000,5000],[4000,3000]], "knots": [0,0,1,2,3,4,4]}',
        'detail_line {"control": [[0,6000],[2000,8000],[4000,6000]]}',
    )
    assert sc.transcript() == sc.golden()


def test_detail_line_styles_insulation_and_revision_cloud(sc):
    """CATCHES: insulation or a revision cloud not drawn along the line (or kept without its width, arc length or revision
    label), or a line style's pen and pattern not changing how the plan draws it."""
    lines_and_plan(
        sc,
        'detail_line {"points": [[0,0],[4000,0]], "style": "Wide Lines"}',
        'detail_line {"points": [[0,1000],[4000,1000]], "style": "Hidden Lines"}',
        'detail_line {"points": [[0,2000],[4000,2000]], "style": "Centre Lines"}',
        'detail_line {"points": [[0,3000],[4000,3000]], "insulation": 300}',
        'detail_line {"points": [[0,5000],[3000,5000],[3000,7000],[0,7000]], "closed": true, "cloud": 400, "revision": "Rev 2"}',
        'detail_line {"centre": [6000,6000], "radius": 1000, "cloud": 500}',
        'detail_line {"start": [5000,0], "end": [8000,0], "arc": 120, "insulation": 200}',
    )
    assert sc.transcript() == sc.golden()


def test_detail_lines_in_a_section_a_sheet_and_another_level(sc):
    """CATCHES: a detail line's `view` (a section, a sheet by number, a level's plan by name) put in the wrong view, or a
    line in one view drawn in another (the Level 1 plan must show none of them)."""
    sc.cmds(
        'section {"start": [0,-1000], "end": [6000,-1000], "name": "S1"}',
        'detail_line {"view": "S1", "points": [[0,0],[3000,2000]], "style": "Medium Lines"}',
        'sheet {"number": "A101", "name": "Plans", "size": "A4"}',
        'detail_line {"view": "A101", "start": [20,20], "end": [200,20], "through": [110,60]}',
        'detail_line {"view": "Level 2", "points": [[0,0],[1000,0]]}',
        LINES,
        'render {"view": "S1", "path": "s1.png", "width": 400, "height": 300}',
        'render {"view": "A101", "path": "sheet.png"}',
        'render {"view": "Level 2", "path": "level2.svg"}',
        PLAN_SVG,
    )
    png_shape(sc, "s1.png")
    png_shape(sc, "sheet.png")
    sc.file("level2.svg")
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


DETAIL_LINE_ERRORS = [
    'detail_line {"start": [0,0], "end": [1000,0], "arc": 90, "through": [500,100]}',
    'detail_line {"points": [[0,0]]}',
    'detail_line {"points": [[0,0],[0,0]]}',
    'detail_line {"points": [[0,0],[1000,1000]], "arcs": [1,2]}',
    'detail_line {"points": [[0,0],[1000,1000]], "closed": true}',
    'detail_line {"start": [0,0], "end": [1000,0], "arc": 360}',
    'detail_line {"centre": [0,0], "radius": 0}',
    'detail_line {"centre": [0,0], "radii": [0,4]}',
    'detail_line {"centre": [0,0], "radii": [10,4], "span": [10,10]}',
    'detail_line {"control": [[0,0]]}',
    'detail_line {"control": [[0,0],[1000,1000],[2000,0]], "knots": [0,0,0,1,1]}',
    'detail_line {"control": [[0,0],[1000,1000],[2000,0]], "knots": [0,0,1,0.5,1,1]}',
    'detail_line {"fit": [[0,0],[1000,1000]], "start_tangent": [0,0]}',
    'detail_line {"fit": [[0,0],[0,0]]}',
    'detail_line {"points": [[0,0],[1000,1000]], "insulation": 100, "cloud": 50}',
    'detail_line {"points": [[0,0],[1000,1000]], "bogus": 1}',
    'detail_line {"points": [[0,0],[1000,1000]], "view": "Nowhere"}',
    'detail_line {"points": [[0,0],[1000,1000]], "style": "Nope"}',
    "detail_line {}",
    'detail_line {"start": [0,0]}',
    'detail_line {"centre": [0,0], "radius": 10, "points": [[0,0],[1,1]]}',
    'detail_line {"points": [[0,0],[1e12,1]]}',
    'detail_line {"points": [[0,0],[0.0001,0]]}',
    'detail_line {"points": [[0,0],[1000,0]], "insulation": -5}',
    'detail_line {"points": [[0,0],[1000,0]], "cloud": 0}',
    'detail_line {"start": [0,0], "end": [1000,0], "arc": 1e-6}',
    'detail_line {"points": [[0,0],[1000,0]], "arcs": [400]}',
    'detail_line {"centre": [2e9,0], "radius": 10}',
    'detail_line {"centre": [999999000,0], "radius": 10000}',
    'detail_line {"centre": [2e9,0], "radii": [10,5]}',
    'detail_line {"centre": [999999000,0], "radii": [10000,5]}',
    'detail_line {"centre": [0,0], "radii": [10,5], "angle": 1e7}',
    'detail_line {"centre": [0,0], "radii": [10,5], "span": [1e7,0]}',
    'detail_line {"control": [[0,0],[1000,1000],[2000,0]], "knots": [0,0,1,1]}',
    'detail_line {"control": [[0,0],[1000,1000],[2000,0]], "knots": [0,0,0.5,1,1,1]}',
    'detail_line {"control": [[0,0],[2e9,1000]]}',
    'detail_line {"fit": [[0,0],[2e9,1000]]}',
    'detail_line {"fit": [[0,0]]}',
    'detail_line {"points": [[0,0],[2000000,0],[0,0],[2000000,0],[0,0],[2000000,0]], "arcs": [175,175,175,175,175]}',
]


def test_detail_line_refusals(sc):
    """CATCHES: a malformed detail line (mixed shapes, too few or repeated points, arcs not matching segments, whole-circle
    arcs, zero radii, empty spans, bad knots or tangents, insulation and cloud together, unknown keys, views or styles,
    points out of range) accepted, or refused with another message."""
    for c in DETAIL_LINE_ERRORS:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Line patterns and line styles
# ---------------------------------------------------------------------------


def test_line_patterns_listed_and_every_segment_kind(sc):
    """CATCHES: a project starting with other line patterns, or a pattern of dashes, spaces, dots, dot lengths, offsets,
    waves, zigzags and text kept or drawn other than given."""
    sc.cmds(
        "line_pattern {}",
        'line_pattern {"name": "Mixed", "segments": [{"dash": 6}, {"space": 2}, "dot", {"space": 2}, {"dot_length": 1}, {"space": 2}]}',
        'line_pattern {"name": "Rails", "segments": [{"offset": {"length": 10, "count": 3, "distance": 1.5}}]}',
        'line_pattern {"name": "Wave", "segments": [{"wave": {"length": 10, "frequency": 2, "amplitude": 1}}, {"space": 1}]}',
        'line_pattern {"name": "Zig", "segments": [{"zigzag": {"length": 8, "frequency": 3, "amplitude": 1.5}}]}',
        'line_pattern {"name": "Gas", "segments": [{"dash": 10}, {"text": {"length": 6, "size": 2, "text": "GAS"}}]}',
        'line_style {"name": "Mixed Lines", "pen": 3, "pattern": "Mixed"}',
        'line_style {"name": "Rail Lines", "pen": 2, "pattern": "Rails", "color": "#0000ff"}',
        'line_style {"name": "Wave Lines", "pen": 2, "pattern": "Wave", "color": [200, 0, 0]}',
        'line_style {"name": "Zig Lines", "pen": 1, "pattern": "Zig"}',
        'line_style {"name": "Gas Lines", "pen": 2, "pattern": "Gas"}',
        'detail_line {"points": [[0,0],[6000,0]], "style": "Mixed Lines"}',
        'detail_line {"points": [[0,1500],[6000,1500]], "style": "Rail Lines"}',
        'detail_line {"start": [0,3000], "end": [6000,3000], "arc": 60, "style": "Wave Lines"}',
        'detail_line {"points": [[0,5000],[6000,5000]], "style": "Zig Lines"}',
        'detail_line {"centre": [3000,8000], "radius": 1500, "style": "Gas Lines"}',
        PLAN_SVG,
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_line_pattern_edit_rename_and_delete(sc):
    """CATCHES: a renamed pattern that its line styles don't follow, a pattern deleted while a style uses it, Solid accepted
    as a pattern name, an edit without segments that changes it, or segments out of range accepted."""
    pre = ['line_pattern {"name": "Mine", "segments": [{"dash": 4}, {"space": 2}]}',
           'line_style {"name": "My Lines", "pen": 2, "pattern": "Mine"}']
    sc.cmds(*pre, 'line_pattern {"name": "Mine"}', 'line_pattern {"name": "Mine", "rename": "Ours"}',
            'line_style {"name": "My Lines"}')
    for c in [
        'line_pattern {"name": "Mine", "delete": true}',
        'line_pattern {"name": "Gone", "delete": true}',
        'line_pattern {"name": "Gone"}',
        'line_pattern {"name": "Mine", "rename": "Dash"}',
        'line_pattern {"name": "Solid", "segments": [{"dash": 2}]}',
        'line_pattern {"name": "Tiny", "segments": [{"dash": 0.01}]}',
        'line_pattern {"name": "Huge", "segments": [{"dash": 200}]}',
        'line_pattern {"name": "None", "segments": []}',
        'line_pattern {"name": "Bad", "segments": [{"squiggle": 2}]}',
        'line_pattern {"name": "Rails", "segments": [{"offset": {"length": 10, "count": 12, "distance": 1}}]}',
        'line_pattern {"name": "Wave", "segments": [{"wave": {"length": 10, "frequency": 500, "amplitude": 1}}]}',
        'line_pattern {"name": "Mine", "colour": 1}',
    ]:
        sc.cmds(*pre, c)
    sc.cmds('line_pattern {"name": "Spare", "segments": [{"dash": 3}, {"space": 3}]}', 'line_pattern {"name": "Spare", "delete": true}',
            "line_pattern {}")
    assert sc.transcript() == sc.golden()


def test_line_style_create_change_rename_and_delete(sc):
    """CATCHES: a line style made without a pen, an edit that loses what it wasn't given, a rename its lines don't follow,
    a style deleted while a line is drawn in it, or a bad colour, pen or pattern accepted."""
    sc.cmds(
        "line_style {}",
        'line_style {"name": "Red", "pen": 5, "color": "#c80000"}',
        'line_style {"name": "Red", "pattern": "Dash"}',
        'line_style {"name": "Red", "pen": 7}',
        'line_style {"name": "Red", "pattern": "Solid"}',
        'detail_line {"points": [[0,0],[2000,0]], "style": "Red"}',
        'line_style {"name": "Red", "rename": "Crimson"}',
        LINES,
    )
    pre = ['line_style {"name": "Red", "pen": 5}', 'detail_line {"points": [[0,0],[2000,0]], "style": "Red"}']
    for c in [
        'line_style {"name": "Red", "delete": true}',
        'line_style {"name": "Nope", "delete": true}',
        'line_style {"name": "Blue"}',
        'line_style {"name": "Blue", "pen": 17}',
        'line_style {"name": "Blue", "pen": 2, "color": "blue"}',
        'line_style {"name": "Blue", "pen": 2, "color": [300, 0, 0]}',
        'line_style {"name": "Blue", "pen": 2, "pattern": "Nope"}',
        'line_style {"name": "Blue", "pen": 2, "pattern": 5}',
        'line_style {"name": "Red", "rename": "Thin Lines"}',
        'line_style {"name": "Red", "weight": 2}',
    ]:
        sc.cmds(*pre, c)
    sc.cmds('line_style {"name": "Spare", "pen": 1}', 'line_style {"name": "Spare", "delete": true}', 'line_style {"name": "Spare"}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Fill patterns, PAT files, filled region types and filled regions
# ---------------------------------------------------------------------------


def test_fill_patterns_listed_created_retargeted_renamed(sc):
    """CATCHES: a project starting with other fill patterns, a pattern's families (angle, origin, shift, dashes) or target
    kept wrongly, a solid pattern not made from no lines, or a rename that its filled region types don't follow."""
    sc.cmds(
        "fill_pattern {}",
        'fill_pattern {"name": "Stripes", "lines": [{"angle": 45, "spacing": 3}]}',
        'fill_pattern {"name": "Dashed Grid", "target": "model", "lines": [{"angle": 0, "spacing": 200, "origin": [10, 20], '
        '"shift": 100, "dashes": [100, -50, 0, -50]}, {"angle": 90, "spacing": 200}]}',
        'fill_pattern {"name": "Plain", "lines": []}',
        'fill_pattern {"name": "Stripes"}',
        'fill_pattern {"name": "Stripes", "target": "model", "lines": [{"angle": 135, "spacing": 250}]}',
        'filled_region_type {"name": "Hatched", "foreground": "Stripes", "foreground_color": "#ff0000", '
        '"background": "Solid fill", "background_color": [200, 200, 255]}',
        'fill_pattern {"name": "Stripes", "rename": "Diagonal 250"}',
        'filled_region_type {"name": "Hatched"}',
        'fill_pattern {"name": "Plain", "delete": true}',
        'library {"kind": "fill-pattern"}',
    )
    assert sc.transcript() == sc.golden()


FILL_PATTERN_ERRORS = [
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 0}]}',
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 5, "dashes": [-1, -2]}]}',
    'fill_pattern {"name": "X", "lines": [{"angle": "a", "spacing": 5}]}',
    'fill_pattern {"name": "X"}',
    'fill_pattern {"name": "X", "target": "paper"}',
    'fill_pattern {"name": "Crosshatch", "delete": true}',
    'fill_pattern {"name": "Brick 225 x 75", "delete": true}',
    'fill_pattern {"name": "Nope", "delete": true}',
    'fill_pattern {"name": "Horizontal", "rename": "Vertical"}',
    'fill_pattern {"name": "Horizontal", "drawn": "big"}',
    'fill_pattern {"name": "Horizontal", "colour": 1}',
    'filled_region_type {"name": "T"}',
    'filled_region_type {"name": "T", "foreground": "Nope"}',
    'filled_region_type {"name": "Sand", "rename": "Brick"}',
    'filled_region_type {"name": "T", "foreground_color": "red"}',
    'filled_region_type {"name": "Nope", "delete": true}',
    'filled_region_type {"name": "Nope", "masking": true}',
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 5}], "drawn": -1}',
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 5, "shift": 1e12}]}',
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 5, "origin": [1e12, 0]}]}',
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 5, "dashes": [1,-1,1,-1,1,-1,1,-1,1,-1,1,-1,1,-1,1,-1,1,-1]}]}',
    'fill_pattern {"name": "X", "lines": [{"angle": 0, "spacing": 5, "dashes": [1e12,-1]}]}',
    'fill_pattern {"name": "X", "lines": ' + json.dumps([{"angle": i, "spacing": 5} for i in range(257)]) + '}',
]


def test_fill_pattern_and_region_type_refusals(sc):
    """CATCHES: a fill pattern with lines on each other or dashes all spaces, an unknown target, a delete of a pattern a
    region type or material uses, a clash on rename, or a region type naming a missing pattern, being accepted or refused
    with another message."""
    for c in FILL_PATTERN_ERRORS:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


PAT_FILE = """﻿;%UNITS=MM
;%VERSION=3.0
; a comment line
*Running Bond, bricks laid in courses
;%TYPE=MODEL
0, 0,0, 0,75
90, 0,0, 75,115, 75,-75
*Hatch45
45, 0,0, 0,2.5 ; trailing comment
*Dots
0, 0,0, 0.5,1, 0,-1
*Empty
*Flat
0, 0,0, 0,0
*Nothing
0, 0,0, 0,5, -1,-2
*Words
0, zero, 0, 0, 5
*Hatch45
45, 0,0, 0,3
*Crosshatch
0, 0,0, 0,9
90, 0,0, 0,9
"""

INCH_FILE = """;%UNITS=INCH
*Inch Grid
;%TYPE=MODEL
0, 0,0, 0,1
90, 0,0, 0,1, 0.5,-0.5
*Stepped
30, 1,2, 0.25,-0.5
"""


def test_import_fill_patterns_from_text_with_left_out_and_replace(sc):
    """CATCHES: a PAT reader that misreads model and drafting types, comments, a byte order mark or descriptions after a
    name, keeps a pattern with no lines, an offset of 0, dashes all spaces or words, keeps a duplicate, or replaces a
    project's pattern without `replace`."""
    pat = json.dumps(PAT_FILE)
    sc.cmds(
        f'import_fill_patterns {{"text": {pat}}}',
        'fill_pattern {"name": "Running Bond"}',
        'fill_pattern {"name": "Hatch45"}',
        'fill_pattern {"name": "Dots"}',
        'fill_pattern {"name": "Crosshatch"}',
    )
    sc.cmds(f'import_fill_patterns {{"text": {pat}, "replace": true}}', 'fill_pattern {"name": "Crosshatch"}')
    assert sc.transcript() == sc.golden()


def test_import_fill_patterns_from_a_file_in_inches_and_latin1(sc):
    """CATCHES: `;%UNITS=INCH` not scaling every length by 25.4 (origins, shifts, offsets and dashes), a negative offset
    not stepping the other way, a Latin-1 file not read, or a missing file not named."""
    sc.write("inch.pat", INCH_FILE)
    sc.write("latin.pat", b"*Ma\xe7onnerie\n0, 0,0, 0,10\n")
    sc.cmds(
        'import_fill_patterns {"path": "inch.pat"}',
        'fill_pattern {"name": "Inch Grid"}',
        'fill_pattern {"name": "Stepped"}',
        'import_fill_patterns {"path": "latin.pat"}',
    )
    for c in [
        'import_fill_patterns {"path": "missing.pat"}',
        "import_fill_patterns {}",
        'import_fill_patterns {"path": "inch.pat", "text": "*A\\n0,0,0,0,1"}',
        'import_fill_patterns {"text": 5}',
    ]:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


def test_export_fill_patterns_as_text_and_to_a_file(sc):
    """CATCHES: an export that includes solid patterns, writes another PAT layout (units and version header, TYPE lines,
    numbers), ignores `names`, or doesn't write the file it is given; a round trip must read back what was written."""
    sc.cmds(
        'fill_pattern {"name": "Odd, Name", "target": "model", "lines": [{"angle": 30, "spacing": 125.5, "origin": [1, 2], '
        '"shift": 0.25, "dashes": [10, -5, 0, -5]}]}',
        "export_fill_patterns {}",
        'export_fill_patterns {"names": ["Tile 300", "Sand"]}',
        'export_fill_patterns {"path": "out.pat", "names": ["Odd, Name", "Brick 225 x 75", "Solid fill"]}',
        'export_fill_patterns {"names": ["Nope"]}',
    )
    sc.file("out.pat")
    sc.cmds('import_fill_patterns {"path": "out.pat"}', 'import_fill_patterns {"path": "out.pat", "replace": true}')
    sc.files()
    assert sc.transcript() == sc.golden()


def test_make_fill_pattern_from_detail_lines(sc):
    """CATCHES: Make Pattern taking lines outside the tile, giving a family the wrong spacing, origin, shift or dashes,
    a drafting pattern not scaled to paper at the view's scale, or `drawn` and retargeting not rescaling it."""
    sc.cmds(
        'detail_line {"points": [[0,0],[300,0]]}',
        'detail_line {"points": [[0,0],[300,300]]}',
        'detail_line {"points": [[150,0],[150,300]]}',
        'detail_line {"points": [[-500,-500],[-400,-500]]}',
        'make_fill_pattern {"ids": [100002, 100003, 100004, 100005], "from": [0,0], "to": [300,300], "name": "Tile Made"}',
        'make_fill_pattern {"ids": [100002, 100003, 100004], "from": [0,0], "to": [300,300], "name": "Tile Paper", "target": "drafting"}',
        'fill_pattern {"name": "Tile Paper", "target": "model"}',
        'fill_pattern {"name": "Tile Paper", "target": "drafting"}',
        'fill_pattern {"name": "Tile Paper", "drawn": 50}',
        'fill_pattern {"name": "Tile Paper", "target": "model"}',
        'fill_pattern {"name": "Tile Paper", "drawn": null}',
    )
    pre = ['detail_line {"points": [[0,0],[300,0]]}', 'section {"start": [0,-1000], "end": [6000,-1000], "name": "S1"}',
           'detail_line {"view": "S1", "points": [[0,0],[300,0]]}']
    for c in [
        'make_fill_pattern {"ids": [100002], "from": [0,0], "to": [300,300], "name": "Brick 225 x 75"}',
        'make_fill_pattern {"ids": [100002], "from": [0,0], "to": [300,300]}',
        'make_fill_pattern {"ids": [100002], "from": [0,0], "to": [0,300], "name": "X"}',
        'make_fill_pattern {"ids": [100002, 100004], "from": [0,0], "to": [300,300], "name": "X"}',
        'make_fill_pattern {"ids": [100003], "from": [0,0], "to": [300,300], "name": "X"}',
        'make_fill_pattern {"ids": [100002], "from": [1000,1000], "to": [1300,1300], "name": "X"}',
        'make_fill_pattern {"ids": [100002], "from": [0,0], "to": [300,300], "name": "X", "target": "paper"}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


def test_filled_region_types_listed_created_renamed_deleted(sc):
    """CATCHES: a project starting with other region types, a new type not starting empty, colours or masking not kept,
    a rename its regions don't follow, or a type deleted while a region is of it."""
    sc.cmds(
        "filled_region_type {}",
        'filled_region_type {"name": "Blank"}',
        'filled_region_type {"name": "Blank", "foreground": "Diagonal Up", "foreground_color": [0, 128, 0]}',
        'filled_region_type {"name": "Blank", "background": "Solid fill", "background_color": "#eeeeee", "masking": true}',
        'filled_region_type {"name": "Blank", "foreground": null}',
        'filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]], "type": "Blank"}',
        'filled_region_type {"name": "Blank", "rename": "Grey Mask"}',
        'elements {"category": "region"}',
    )
    sc.cmds(
        'filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]], "type": "Sand"}',
        'filled_region_type {"name": "Sand", "delete": true}',
    )
    sc.cmds('filled_region_type {"name": "Sand", "delete": true}', "filled_region_type {}")
    assert sc.transcript() == sc.golden()


SQUARE = '[[0,0],[4000,0]],[[4000,0],[4000,3000]],[[4000,3000],[0,3000]],[[0,3000],[0,0]]'
HOLE = '[[1000,1000],[2000,1000]],[[2000,1000],[2000,2000]],[[2000,2000],[1000,2000]],[[1000,2000],[1000,1000]]'


def test_filled_regions_with_holes_arcs_masking_and_pattern_origin(sc):
    """CATCHES: a filled region whose area ignores its hole, an arc in its sketch, a masking region drawn with a boundary
    after `line_style: null`, or a model pattern's `pattern_origin` and `pattern_angle` not kept or not drawn."""
    lines_and_plan(
        sc,
        'wall {"points": [[-1000,-1000],[9000,-1000]]}',
        f'filled_region {{"sketch": [{SQUARE},{HOLE}], "type": "Crosshatch"}}',
        'filled_region {"sketch": [[[5000,0],[7000,0]],[[7000,0],[6000,2000]],[[6000,2000],[5000,0]]], "type": "Masking", "line_style": null}',
        'filled_region {"sketch": [[[0,4000],[4000,4000]],[[4000,4000],[0,4000],[2000,6000]]], "type": "Brick", "line_style": "Wide Lines"}',
        'filled_region {"sketch": [[[5000,4000],[8000,4000]],[[8000,4000],[8000,7000]],[[8000,7000],[5000,7000]],[[5000,7000],[5000,4000]]], "type": "Sand"}',
        'modify {"id": 100006, "pattern_origin": [100, 50], "pattern_angle": 30}',
        'elements {"category": "region"}',
    )
    assert sc.transcript() == sc.golden()


def test_filled_regions_in_a_section_and_on_a_sheet(sc):
    """CATCHES: a filled region's `view` ignored (drawn in the plan instead of the section or on the sheet), or its area
    worked out in the wrong terms."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]]}',
        'section {"start": [0,-1000], "end": [6000,-1000], "name": "S1"}',
        f'filled_region {{"view": "S1", "sketch": [{SQUARE}], "type": "Diagonal Up"}}',
        'sheet {"number": "A9", "size": "A4"}',
        'filled_region {"view": "A9", "sketch": [[[10,10],[60,10]],[[60,10],[60,40]],[[60,40],[10,40]],[[10,40],[10,10]]]}',
        'elements {"category": "region"}',
        'render {"view": "S1", "path": "s1.png", "width": 400, "height": 300}',
        'render {"view": "A9", "path": "a9.png"}',
    )
    png_shape(sc, "s1.png")
    png_shape(sc, "a9.png")
    assert sc.transcript() == sc.golden()


def test_filled_region_refusals(sc):
    """CATCHES: a filled region accepted from a sketch that doesn't close, crosses itself or has none, or in an unknown
    view, type or line style."""
    for c in [
        'filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]]]}',
        'filled_region {"sketch": [[[0,0],[1000,1000]],[[1000,1000],[1000,0]],[[1000,0],[0,1000]],[[0,1000],[0,0]]]}',
        'filled_region {"sketch": []}',
        "filled_region {}",
        f'filled_region {{"sketch": [{SQUARE}], "type": "Nope"}}',
        f'filled_region {{"sketch": [{SQUARE}], "line_style": "Nope"}}',
        f'filled_region {{"sketch": [{SQUARE}], "view": "Nope"}}',
        f'filled_region {{"sketch": [{SQUARE}], "colour": 1}}',
    ]:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Detail groups and repeating details
# ---------------------------------------------------------------------------

GROUP_MEMBERS = [
    'detail_line {"points": [[0,0],[1000,0]]}',
    'detail_line {"points": [[0,0],[0,500]], "style": "Wide Lines"}',
    'filled_region {"sketch": [[[200,100],[800,100]],[[800,100],[800,400]],[[800,400],[200,400]],[[200,400],[200,100]]], "type": "Sand"}',
    'text {"text": "Tie", "at": [100, 600]}',
]
GROUPS = 'elements {"category": "detailgroup"}'
REPEATS = 'elements {"category": "repeatingdetail"}'


def test_create_group_place_it_turned_and_mirrored(sc):
    """CATCHES: Create Group not replacing its members with one group at their middle, a placed group not turned or
    mirrored as asked, or `group_type` miscounting members and placements."""
    sc.cmds(
        *GROUP_MEMBERS,
        'create_group {"ids": [100002, 100003, 100004, 100005], "name": "Batt Tie"}',
        "group_type {}",
        'detail_group {"type": "Batt Tie", "at": [5000,0], "angle": 90}',
        'detail_group {"type": "Batt Tie", "at": [0,5000], "mirrored": true}',
        'create_group {"ids": [100002]}',
    )
    sc.cmds(
        *GROUP_MEMBERS,
        'create_group {"ids": [100002, 100003, 100004, 100005], "name": "Batt Tie"}',
        'detail_group {"type": "Batt Tie", "at": [5000,0], "angle": 90}',
        'detail_group {"type": "Batt Tie", "at": [0,5000], "mirrored": true}',
        'detail_line {"points": [[0,-2000],[500,-2000]]}',
        'create_group {"ids": [100009]}',
        "group_type {}",
        GROUPS,
        "elements {}",
        PLAN_SVG,
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_repeating_detail_along_a_line(sc):
    """CATCHES: a repeating detail placed the wrong number of times for its length and spacing, not turned along its line,
    or not mirrored when asked."""
    sc.cmds(
        'detail_line {"points": [[0,0],[0,400]]}',
        'detail_line {"points": [[0,400],[200,200]]}',
        'create_group {"ids": [100002, 100003], "name": "Tick"}',
        'repeating_detail {"type": "Tick", "start": [0,2000], "end": [6000,2000], "spacing": 1500}',
        'repeating_detail {"type": "Tick", "start": [0,4000], "end": [3000,7000], "spacing": 1000, "mirrored": true}',
        'repeating_detail {"type": "Tick", "start": [0,0], "end": [100,0], "spacing": 1000}',
        "group_type {}",
        REPEATS,
        PLAN_SVG,
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_ungroup_rename_and_delete_group_types(sc):
    """CATCHES: Ungroup not giving back the members where the group drew them (turned with it) as new elements, a renamed
    type its groups don't follow, or a type deleted while placed."""
    sc.cmds(
        *GROUP_MEMBERS,
        'create_group {"ids": [100002, 100003, 100004, 100005], "name": "Batt Tie"}',
        'detail_group {"type": "Batt Tie", "at": [5000,0], "angle": 90}',
        'group_type {"name": "Batt Tie", "rename": "Tie"}',
        GROUPS,
        'ungroup {"id": 100007}',
        'elements {"category": "line"}',
        'elements {"category": "region"}',
        'elements {"category": "text"}',
        'group_type {"name": "Tie", "delete": true}',
    )
    sc.cmds(
        *GROUP_MEMBERS,
        'create_group {"ids": [100002, 100003, 100004, 100005], "name": "Batt Tie"}',
        'delete {"ids": [100006]}',
        'group_type {"name": "Batt Tie", "delete": true}',
        "group_type {}",
    )
    assert sc.transcript() == sc.golden()


def test_group_refusals(sc):
    """CATCHES: a group made of a wall or of elements of two views, a duplicate group name, an unknown type placed or
    repeated, a non-group ungrouped, or a group type renamed onto another, being accepted or refused with another message."""
    pre = [*GROUP_MEMBERS, 'create_group {"ids": [100002, 100003], "name": "G"}',
           'wall {"points": [[0,-3000],[3000,-3000]]}', 'detail_line {"view": "Level 2", "points": [[0,0],[100,0]]}',
           'create_group {"ids": [100004], "name": "H"}']
    for c in [
        'create_group {"ids": [100007]}',
        'create_group {"ids": [100005, 100008]}',
        'create_group {"ids": [100005], "name": "G"}',
        'create_group {"ids": []}',
        'detail_group {"type": "Nope", "at": [0,0]}',
        'detail_group {"at": [0,0]}',
        'repeating_detail {"type": "G", "start": [0,0], "end": [1000,0]}',
        'ungroup {"id": 100007}',
        'group_type {"name": "G", "rename": "H"}',
        'group_type {"name": "Nope"}',
        'group_type {"name": "G", "delete": true}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Linework
# ---------------------------------------------------------------------------


def test_linework_restyles_hides_and_restores_wall_edges(sc):
    """CATCHES: Linework picking another edge than the one nearest `at`, not drawing it in the style given or leaving it
    out when invisible, `remove` taking off the wrong one, or what a view holds not shown by `graphics`."""
    sc.cmds(
        'wall {"points": [[0,0],[5000,0],[5000,4000]]}',
        'linework {"id": 100002, "at": [2500,100], "style": "Wide Lines"}',
        'linework {"id": 100002, "at": [2500,-100], "invisible": true}',
        'linework {"id": 100003, "at": [5100,2000], "style": "Hidden Lines"}',
        "graphics {}",
        PLAN_SVG,
    )
    sc.file("plan.svg")
    sc.cmds(
        'wall {"points": [[0,0],[5000,0],[5000,4000]]}',
        'linework {"id": 100002, "at": [2500,100], "style": "Wide Lines"}',
        'linework {"id": 100002, "at": [2500,-100], "invisible": true}',
        'linework {"id": 100002, "at": [2500,-100], "remove": true}',
        'linework {"id": 100002, "at": [2500,-100], "remove": true}',
        'duplicate_view {"view": "Level 1", "name": "Working"}',
        'linework {"view": "Working", "id": 100002, "at": [2500,100], "style": "Medium Lines"}',
        'graphics {"view": "Working"}',
        'line_style {"name": "Wide Lines", "delete": true}',
    )
    assert sc.transcript() == sc.golden()


def test_linework_refusals(sc):
    """CATCHES: Linework accepted far from any edge, for an unknown style, both a style and invisible, or with nothing
    asked, or refused with another message."""
    pre = ['wall {"points": [[0,0],[5000,0]]}', 'detail_line {"points": [[0,2000],[1000,2000]]}']
    for c in [
        'linework {"id": 100002, "at": [2500,3000], "style": "Wide Lines"}',
        'linework {"id": 100002, "at": [2500,100], "style": "Nope"}',
        'linework {"id": 100002, "at": [2500,100]}',
        'linework {"id": 100002, "at": [2500,100], "style": "Wide Lines", "invisible": true}',
        'linework {"id": 100003, "at": [500,2000], "style": "Wide Lines"}',
        'linework {"id": 999, "at": [500,2000], "style": "Wide Lines"}',
        'linework {"id": 100002, "at": [2500,100], "remove": true}',
        'linework {"id": 100002, "at": [2500,100], "style": "Wide Lines", "view": "Nope"}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# The modify tools on detail lines
# ---------------------------------------------------------------------------

SHAPES = [
    'detail_line {"points": [[0,0],[2000,0]]}',
    'detail_line {"start": [3000,0], "end": [5000,0], "arc": 90}',
    'detail_line {"centre": [0,3000], "radius": 500}',
    'detail_line {"centre": [3000,3000], "radii": [800,400], "angle": 30}',
    'detail_line {"control": [[0,6000],[1000,7000],[2000,6000],[3000,7000]]}',
    'detail_line {"points": [[4000,6000],[5000,6000],[5000,7000]], "arcs": [0, 90]}',
]


def test_move_and_copy_detail_lines_of_every_shape(sc):
    """CATCHES: move or copy shifting a shape's points unevenly (an arc's ends, a circle's or ellipse's centre, a spline's
    control points, a polyline's arcs), copies not getting new ids, or the reply listing the wrong ids."""
    sc.cmds(
        *SHAPES,
        'move {"ids": [100002, 100003, 100004], "by": [100, 200]}',
        'copy {"ids": [100005, 100006, 100007], "by": [-500, 10000]}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_rotate_and_mirror_detail_lines(sc):
    """CATCHES: rotate turning clockwise or about the wrong point, a rotated or mirrored arc keeping the wrong turn, an
    ellipse's angle not following, or copies left out when `copy` is true."""
    sc.cmds(
        *SHAPES,
        'rotate {"ids": [100002], "about": [0,0], "angle": 90}',
        'rotate {"ids": [100003, 100005], "about": [1000,1000], "angle": -30, "copy": true}',
        'mirror {"ids": [100004, 100006], "axis": [[0,0],[1000,1000]]}',
        'mirror {"ids": [100003, 100007], "axis": [[0,0],[0,1000]], "copy": true}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_corner_and_trim_extend_detail_lines(sc):
    """CATCHES: Trim/Extend to Corner keeping the wrong part of each line, missing where an arc's circle meets a line, or
    Trim/Extend to a boundary (a detail line, a wall, a grid) cutting or extending the lines the wrong way."""
    sc.cmds(
        'detail_line {"points": [[0,0],[2000,0]]}',
        'detail_line {"points": [[3000,-1000],[3000,1000]]}',
        'corner {"ids": [100002, 100003]}',
        'detail_line {"points": [[0,2000],[4000,2000]]}',
        'detail_line {"points": [[2000,1000],[2000,3000]]}',
        'corner {"ids": [100004, 100005], "keep": [[500,2000],[2000,2500]]}',
        'detail_line {"points": [[0,5000],[1000,5000]]}',
        'detail_line {"points": [[0,6000],[3000,6000]]}',
        'detail_line {"points": [[2000,4000],[2000,7000]]}',
        'trim_extend {"boundary": 100008, "ids": [100006, 100007], "keep": [[500,5000],[500,6000]]}',
        'detail_line {"start": [0,8000], "end": [2000,8000], "arc": 180}',
        'detail_line {"points": [[1000,7000],[1000,10000]]}',
        'corner {"ids": [100009, 100010], "keep": [[0,8000],[1000,7500]]}',
        'grid {"start": [6000,-2000], "end": [6000,12000]}',
        'wall {"points": [[-1000,11000],[8000,11000]]}',
        'detail_line {"points": [[4000,0],[5000,0]]}',
        'detail_line {"points": [[4000,10000],[4000,10500]]}',
        'trim_extend {"boundary": 100011, "ids": [100013], "keep": [[4500,0]]}',
        'trim_extend {"boundary": 100012, "ids": [100014], "keep": [[4000,10200]]}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_offset_detail_lines_of_every_shape(sc):
    """CATCHES: offset putting the copy on the wrong side of `toward`, at the wrong distance, an arc or circle not kept
    round the same centre, a polyline's corners not mitred, an ellipse or spline not refitted, or `copy: false` copying."""
    sc.cmds(
        *SHAPES,
        'offset {"id": 100002, "distance": 300, "toward": [1000, 1000]}',
        'offset {"id": 100003, "distance": 200, "toward": [4000, -2000]}',
        'offset {"id": 100004, "distance": 100, "toward": [0, 3000]}',
        'offset {"id": 100005, "distance": 150, "toward": [3000, 5000]}',
        'offset {"id": 100006, "distance": 100, "toward": [1000, 8000]}',
        'offset {"id": 100007, "distance": 250, "toward": [4500, 6500], "copy": false}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_split_detail_lines_of_every_shape_and_open_closed_ones(sc):
    """CATCHES: split cutting a line, arc, polyline or spline anywhere but nearest `at`, a split spline not keeping its
    shape, or a circle or ellipse cut in two instead of opened there (`opened`)."""
    sc.cmds(
        *SHAPES,
        'detail_line {"fit": [[6000,0],[7000,1000],[8000,0],[9000,1000]]}',
        'split {"id": 100002, "at": [500, 10]}',
        'split {"id": 100003, "at": [4000, -414]}',
        'split {"id": 100004, "at": [500, 3000]}',
        'split {"id": 100005, "at": [3000, 3400]}',
        'split {"id": 100006, "at": [1500, 6500]}',
        'split {"id": 100007, "at": [5000, 6000]}',
        'split {"id": 100008, "at": [7500, 500]}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_fillet_join_and_explode_detail_lines(sc):
    """CATCHES: Fillet Arc cutting back the lines to the wrong points or drawing an arc of another radius, Join not making
    one polyline (closed when it comes round) with the first's id, or Explode not giving a piece per segment."""
    sc.cmds(
        'detail_line {"points": [[0,0],[3000,0]]}',
        'detail_line {"points": [[3000,0],[3000,2000]], "style": "Wide Lines"}',
        'fillet {"ids": [100002, 100003], "radius": 500}',
        'detail_line {"points": [[5000,0],[6000,0]]}',
        'detail_line {"points": [[6000,0],[6000,1000]]}',
        'detail_line {"start": [6000,1000], "end": [5000,1000], "arc": 180}',
        'detail_line {"points": [[5000,1000],[5000,0]]}',
        'join_polyline {"ids": [100005, 100006, 100007, 100008]}',
        'detail_line {"points": [[0,4000],[1000,4000],[1000,5000],[2000,5000]], "arcs": [0, 90, 0]}',
        'explode {"id": 100009}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_join_polyline_drops_dimension_references(sc):
    """CATCHES: joining lines a dimension measures not reporting in `notes` that it lost a reference, or keeping a
    dimension left with fewer than two references."""
    sc.cmds(
        'detail_line {"points": [[0,0],[1000,0]]}',
        'detail_line {"points": [[1000,0],[1000,1000]]}',
        'detail_line {"points": [[3000,0],[3000,1000]]}',
        'detail_line {"points": [[5000,0],[5000,1000]]}',
        'dimension {"refs": [{"id": 100003}, {"id": 100004}], "at": [2000, 500]}',
        'dimension {"refs": [{"id": 100003}, {"id": 100004}, {"id": 100005}], "at": [3000, 1500]}',
        'join_polyline {"ids": [100002, 100003]}',
        'elements {"category": "dimension"}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


def test_vertex_and_convert_spline(sc):
    """CATCHES: a vertex added anywhere but nearest `at` or a control point added that changes a spline's shape, the
    wrong vertex deleted, or Convert not switching a spline between fit points and control points."""
    sc.cmds(
        'detail_line {"points": [[0,0],[2000,0],[2000,2000]]}',
        'vertex {"id": 100002, "at": [1000, 50]}',
        'vertex {"id": 100002, "at": [2000, 0], "delete": true}',
        'detail_line {"control": [[0,4000],[1000,5000],[2000,4000],[3000,5000]]}',
        'vertex {"id": 100003, "at": [1500, 4500]}',
        'vertex {"id": 100003, "at": [3000, 5000], "delete": true}',
        'detail_line {"fit": [[0,7000],[1000,8000],[2000,7000]]}',
        'vertex {"id": 100004, "at": [1500, 7700]}',
        'convert_spline {"id": 100004}',
        'convert_spline {"id": 100004}',
        'convert_spline {"id": 100003}',
        LINES,
    )
    assert sc.transcript() == sc.golden()


MODIFY_TOOL_ERRORS = [
    'mirror {"ids": [100002], "axis": [[0,0],[0,1]]}',
    'mirror {"ids": [100002]}',
    'rotate {"ids": [100002], "about": [0,0]}',
    'move {"ids": [100002]}',
    'move {"ids": [100002], "by": [1,1], "end": "start"}',
    'move {"ids": [100002], "by": [1,1], "end": "middle"}',
    'move {"ids": [999999], "by": [1,1]}',
    'copy {"ids": [], "by": [1,1]}',
    'corner {"ids": [100002]}',
    'corner {"ids": [100002, 100003]}',
    'corner {"ids": [100002, 100005]}',
    'corner {"ids": [100002, 100004], "keep": [[0,0]]}',
    'trim_extend {"ids": [100002], "keep": [[0,0]]}',
    'trim_extend {"boundary": 100004, "ids": [100002], "keep": []}',
    'trim_extend {"boundary": 100003, "ids": [100002], "keep": [[500,0]]}',
    'trim_extend {"boundary": 100004, "ids": [100005], "keep": [[500,0]]}',
    'offset {"id": 100002, "distance": 0, "toward": [0,100]}',
    'offset {"id": 100002, "toward": [0,100]}',
    'offset {"id": 100006, "distance": 600, "toward": [0,5000]}',
    'offset {"id": 100007, "distance": 100, "toward": [0,100]}',
    'split {"id": 100002, "at": [500, 900]}',
    'split {"id": 100002, "at": [0, 0]}',
    'split {"id": 100002}',
    'fillet {"ids": [100002, 100003], "radius": 100}',
    'fillet {"ids": [100002, 100004]}',
    'fillet {"ids": [100002, 100006], "radius": 100}',
    'fillet {"ids": [100002, 100004], "radius": 50000}',
    'fillet {"ids": [100002, 100005], "radius": 100}',
    'join_polyline {"ids": [100002]}',
    'join_polyline {"ids": [100002, 100003]}',
    'join_polyline {"ids": [100002, 100006]}',
    'join_polyline {"ids": [100002, 100005]}',
    'explode {"id": 100002}',
    'explode {"id": 100007}',
    'vertex {"id": 100002, "at": [500, 500]}',
    'vertex {"id": 100006, "at": [0, 4500]}',
    'vertex {"id": 100002, "at": [0, 0], "delete": true}',
    'convert_spline {"id": 100002}',
    'convert_spline {}',
]


def test_modify_tool_refusals(sc):
    """CATCHES: the modify tools accepting a bad axis, a missing angle, offset or radius, a wall `end` for a line, two
    parallel lines to corner, lines of different views, points off the line, or a line that is already one piece, or
    refusing with another message."""
    pre = [
        'detail_line {"points": [[0,0],[1000,0]]}',
        'detail_line {"points": [[0,1000],[1000,1000]]}',
        'detail_line {"points": [[2000,-1000],[2000,1000]]}',
        'detail_line {"view": "Level 2", "points": [[0,0],[0,1000]]}',
        'detail_line {"centre": [0,5000], "radius": 500}',
        'wall {"points": [[0,-3000],[3000,-3000]]}',
    ]
    for c in MODIFY_TOOL_ERRORS:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# The modify tools on walls and what they host
# ---------------------------------------------------------------------------

WALLS = 'elements {"category": "wall"}'
OPENINGS = ['elements {"category": "door"}', 'elements {"category": "window"}']
L_WALLS = ['wall {"points": [[0,0],[6000,0],[6000,4000]]}', 'door {"at": [2000, 0]}', 'window {"at": [6000, 2000]}']


def test_move_walls_joined_walls_stretch_and_openings_slide(sc):
    """CATCHES: moving a wall without the wall joined to it stretching to stay joined, its doors and windows not moving
    with it, `end` moving the whole wall instead of one end, or a moved door leaving its host."""
    sc.cmds(
        *L_WALLS,
        'move {"ids": [100003], "by": [500, 0]}',
        'move {"ids": [100002], "by": [-1000, 0], "end": "start"}',
        'move {"ids": [100004], "by": [700, 0]}',
        'move {"ids": [100003], "by": [0, 300], "end": "end"}',
        WALLS,
        *OPENINGS,
    )
    assert sc.transcript() == sc.golden()


def test_copy_rotate_and_mirror_walls_with_their_openings(sc):
    """CATCHES: copied walls without copies of their doors and windows (with new marks), a rotation that leaves the wall
    joined to it unjoined or turns its openings off the wall, or a mirrored door not flipped to face the other way."""
    sc.cmds(
        *L_WALLS,
        'copy {"ids": [100002], "by": [0, -5000]}',
        'mirror {"ids": [100006], "axis": [[0,-6000],[1000,-6000]], "copy": true}',
        'rotate {"ids": [100003], "about": [6000,0], "angle": 90}',
        'mirror {"ids": [100002, 100003], "axis": [[-1000,0],[-1000,1000]]}',
        'rotate {"ids": [100006], "about": [0,-5000], "angle": 180, "copy": true}',
        WALLS,
        *OPENINGS,
    )
    assert sc.transcript() == sc.golden()


def test_corner_split_and_fillet_walls(sc):
    """CATCHES: Trim/Extend to Corner on walls not meeting at their lines' crossing or keeping the wrong ends, Split not
    sending a door to the part it is in (with its offset from that part's start), or a wall fillet not adding an arc wall
    of the first's type and cutting both back while keeping their doors where they stand."""
    sc.cmds(
        'wall {"points": [[0,8000],[3000,8000]], "type": "Exterior - 300mm"}',
        'wall {"points": [[4000,9000],[4000,12000]]}',
        'corner {"ids": [100002, 100003]}',
        'wall {"points": [[0,0],[8000,0]]}',
        'wall {"points": [[5000,-2000],[5000,3000]]}',
        'corner {"ids": [100004, 100005], "keep": [[1000,0],[5000,2000]]}',
        'door {"wall": 100004, "offset": 1000}',
        'window {"wall": 100004, "offset": 4000}',
        'split {"id": 100004, "at": [2500, 0]}',
        'wall {"points": [[10000,0],[16000,0],[16000,5000]], "type": "Exterior - 300mm"}',
        'door {"at": [12000, 0]}',
        'fillet {"ids": [100009, 100010], "radius": 1500}',
        WALLS,
        *OPENINGS,
        PLAN_SVG,
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_wall_modify_refusals(sc):
    """CATCHES: a wall split through a door, off the wall or at its end, a corner of parallel, curved or non-wall elements,
    a fillet that cuts a door off or doesn't fit, or `end` given for two walls, being accepted or refused otherwise."""
    pre = [
        'wall {"points": [[0,0],[6000,0],[6000,4000]]}',
        'door {"at": [2000, 0]}',
        'wall {"points": [[0,2000],[3000,2000]]}',
        'wall {"points": [[0,6000],[4000,6000]], "arc": 90}',
    ]
    for c in [
        'split {"id": 100002, "at": [2000, 0]}',
        'split {"id": 100002, "at": [2000, 900]}',
        'split {"id": 100002, "at": [0, 0]}',
        'split {"id": 100004, "at": [1000, 2000]}',
        'split {"at": [1000, 2000]}',
        'corner {"ids": [100002, 100004]}',
        'corner {"ids": [100002, 100005]}',
        'corner {"ids": [100002, 100003], "keep": [[1000,0]]}',
        'corner {"ids": [100002, 100006]}',
        'fillet {"ids": [100002, 100003], "radius": 3800}',
        'fillet {"ids": [100002, 100003], "radius": 0}',
        'fillet {"ids": [100002, 100005], "radius": 100}',
        'fillet {"ids": [100002, 100006], "radius": 100}',
        'fillet {"ids": [100002, 100003]}',
        'fillet {"ids": [100002], "radius": 100}',
        'move {"ids": [100002, 100003], "by": [1,1], "end": "start"}',
        'move {"ids": [100004], "by": [0, 500]}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Align, Match Properties, Delete, Modify, Measure
# ---------------------------------------------------------------------------


def test_align_turns_and_moves_onto_a_reference_and_locks(sc):
    """CATCHES: Align moving by the wrong amount, turning a picked line the long way round or about the wrong point, or a
    lock that doesn't keep a wall on a grid it was aligned to when the grid moves."""
    sc.cmds(
        'grid {"start": [0,-1000], "end": [0,6000]}',
        'wall {"points": [[500,0],[500,4000]]}',
        'align {"id": 100003, "reference": [[0,-1000],[0,6000]], "line": [[500,0],[500,4000]], "lock": true}',
        'detail_line {"points": [[2000,0],[3000,1000]]}',
        'align {"id": 100005, "reference": [[0,-1000],[0,6000]], "line": [[2000,0],[3000,1000]]}',
        'detail_line {"points": [[4000,0],[4000,2000]]}',
        'align {"id": 100006, "reference": [[0,8000],[1000,8000]], "line": [[4000,0],[4000,2000]]}',
        'move {"ids": [100002], "by": [300, 0]}',
        WALLS,
        LINES,
        'elements {"category": "dimension"}',
    )
    pre = ['grid {"start": [0,-1000], "end": [0,6000]}', 'wall {"points": [[500,0],[3500,0]]}', 'door {"at": [2000,0]}',
           'detail_line {"points": [[2000,3000],[3000,3000]]}']
    for c in [
        'align {"id": 100003, "reference": [[0,0]], "line": [[0,0],[1,1]]}',
        'align {"reference": [[0,0],[0,1000]], "line": [[500,0],[3500,0]]}',
        'align {"id": 999999, "reference": [[0,0],[0,1000]], "line": [[500,0],[3500,0]]}',
        'align {"id": 100004, "reference": [[0,0],[0,1000]], "line": [[1550,0],[1550,200]]}',
        'align {"id": 100004, "reference": [[0,0],[1000,1000]], "line": [[1550,0],[1550,200]]}',
        'align {"id": 100004, "reference": [[2000,0],[2000,1000]], "line": [[1550,0],[1550,200]]}\nelements {"category": "door"}',
        'align {"id": 100005, "reference": [[5000,0],[5000,1000]], "line": [[2000,3000],[3000,3000]], "lock": true}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


def test_match_properties_by_category(sc):
    """CATCHES: Match Properties giving a type to elements of another category instead of skipping them, not changing a
    door's type and size, or not refusing a source with no type."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]], "type": "Exterior - 300mm"}',
        'wall {"points": [[0,2000],[6000,2000]]}',
        'door {"at": [2000, 2000]}',
        'door {"at": [4000, 0], "type": "Single 800 x 2100"}',
        'detail_line {"points": [[0,5000],[1000,5000]]}',
        'match_properties {"from": 100002, "ids": [100003, 100004, 100006]}',
        'match_properties {"from": 100005, "ids": [100004]}',
        WALLS,
        *OPENINGS[:1],
    )
    sc.cmds('detail_line {"points": [[0,5000],[1000,5000]]}', 'detail_line {"points": [[0,6000],[1000,6000]]}',
            'match_properties {"from": 100002, "ids": [100003]}')
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', 'match_properties {"from": 100002}')
    assert sc.transcript() == sc.golden()


def test_delete_takes_what_depends_on_it(sc):
    """CATCHES: deleting a wall without its doors, windows and their tags, deleting a door without its tag, a dimension
    kept with fewer than two references, or a view's notes and detail lines kept when the view goes."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]]}',
        'wall {"points": [[0,2000],[6000,2000]]}',
        'door {"at": [2000, 2000]}',
        'window {"at": [4000, 2000]}',
        "tag {}",
        'dimension {"refs": [{"id": 100002}, {"id": 100003}], "at": [1000, 1000]}',
        'section {"start": [0,-1000], "end": [6000,-1000], "name": "S1"}',
        'detail_line {"view": "S1", "points": [[0,0],[1000,1000]]}',
        'text {"view": "S1", "text": "Note", "at": [100, 100]}',
        'delete {"ids": [100004]}',
        'delete {"ids": [100003]}',
        'delete {"ids": [100009]}',
        'delete {"ids": []}',
        "elements {}",
    )
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', 'delete {"ids": [123]}')
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', "delete {}")
    assert sc.transcript() == sc.golden()


def test_modify_fields_of_lines_walls_and_doors(sc):
    """CATCHES: modify not changing a detail line's style or ends, a wall's type, ends or top offset (and the height that
    follows), several elements at once, or a door's offset and mark; or accepting an unknown field or a mixed shape."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]]}',
        'door {"at": [2000, 0]}',
        'detail_line {"points": [[0,6000],[1000,6000]]}',
        'modify {"id": 100004, "style": "Hidden Lines", "end": [2000, 7000]}',
        'modify {"id": 100002, "type": "Interior - 100mm", "top_offset": -200}',
        'modify {"id": 100002, "end": [8000, 0]}',
        'modify {"id": 100003, "offset": 5000, "mark": "D1"}',
        'wall {"points": [[0,3000],[6000,3000]]}',
        'modify {"ids": [100002, 100005], "base_offset": 100}',
        WALLS,
        *OPENINGS[:1],
    )
    pre = ['wall {"points": [[0,0],[6000,0]]}', 'detail_line {"points": [[0,6000],[1000,6000]]}']
    for c in [
        'modify {"id": 100002, "bogus": 1}',
        'modify {"id": 100003, "points": [[0,0],[500,500],[1000,0]]}',
        'modify {"id": 100003, "style": "Nope"}',
        'modify {"id": 100002, "type": "Nope"}',
        "modify {}",
        'modify {"id": 999999, "height": 1}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


def test_measure_reads_length_parts_and_angle(sc):
    """CATCHES: Measure giving the wrong length, signs of dx and dy, or an angle not measured counter-clockwise from
    east (0 to 360), or changing the model (no undo step)."""
    sc.cmds(
        'measure {"from": [0,0], "to": [3000,4000]}',
        'measure {"from": [0,0], "to": [-1000,0]}',
        'measure {"from": [1000,1000], "to": [1000,-2000]}',
        'measure {"from": [0,0], "to": [-1000,-1000]}',
        'measure {"from": [5,5], "to": [5,5]}',
        'ME {"from": [0,0], "to": [0.5,0.25]}',
        "undo {}",
    )
    sc.cmds('measure {"from": [0,0]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Undo and redo
# ---------------------------------------------------------------------------


def inspect_summary(sc, *commands):
    """Run the commands, then `inspect`, noting the exit code, each reply but the last, and the inspect's counts and history."""
    p = sc.run(["run", *sum((["--cmd", c] for c in [*commands, "inspect {}"]), [])], show=False)
    lines = p.stdout.decode().splitlines()
    sc.note(f"[exit {p.returncode}] {p.stderr.decode().strip()}")
    sc.note("\n".join(lines[:-1]))
    if p.returncode == 0:
        last = json.loads(lines[-1])
        sc.note(json.dumps({"counts": last["counts"], "history": last["history"]}, sort_keys=True))


def test_undo_and_redo_with_counts_and_history(sc):
    """CATCHES: undo or redo taking back the wrong number of steps or naming the wrong one, a new command not clearing the
    redo steps, or commands that change nothing (measure, elements) making steps of their own."""
    base = [
        'detail_line {"points": [[0,0],[1000,0]]}',
        'wall {"points": [[0,1000],[1000,1000]]}',
        'move {"ids": [100002], "by": [0, 500]}',
        'measure {"from": [0,0], "to": [1,1]}',
        LINES,
    ]
    inspect_summary(sc, *base)
    inspect_summary(sc, *base, "undo {}")
    inspect_summary(sc, *base, 'undo {"count": 3}', 'redo {"count": 2}')
    inspect_summary(sc, *base, 'undo {"count": 2}', 'copy {"ids": [100002], "by": [0, 100]}')
    inspect_summary(sc, *base, 'undo {"count": 2}', LINES, 'redo {}', LINES)
    assert sc.transcript() == sc.golden()


def test_undo_and_redo_refusals(sc):
    """CATCHES: undo or redo past the steps there are, of a count that isn't a whole number, with an unknown parameter,
    or with nothing to undo or redo, being accepted or refused with another message."""
    for c in ["undo {}", "redo {}"]:
        sc.cmds(c)
    pre = ['detail_line {"points": [[0,0],[1000,0]]}']
    for c in ['undo {"count": 0}', 'undo {"count": 2}', 'undo {"count": -1}', 'undo {"count": "x"}', 'redo {"count": 1.5}',
              'undo {"steps": 1}', "redo {}"]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


def test_split_and_reshape_polylines_and_splines(sc):
    """CATCHES: a closed polyline opened anywhere but at the point (mid-edge or at a corner), an open polyline split on an
    arc or at a corner into the wrong pieces, a vertex added to a closed polyline that opens it, or a control point or
    fit point deleted that leaves the wrong knots or points."""
    shapes = [
        'detail_line {"points": [[0,0],[2000,0],[2000,2000],[0,2000]], "closed": true}',
        'detail_line {"points": [[0,4000],[1000,4000],[2000,5000],[3000,4000]], "arcs": [0,90,0]}',
        'detail_line {"control": [[0,7000],[1000,8000],[2000,7000],[3000,8000],[4000,7000]], "knots": [0,0,0,1,2,3,3,3]}',
        'detail_line {"fit": [[0,10000],[1000,11000],[2000,10000],[3000,11000]]}',
    ]
    for c in [
        'split {"id": 100002, "at": [1000, 0]}',
        'split {"id": 100002, "at": [2000, 2000]}',
        'split {"id": 100003, "at": [1000, 4000]}',
        'split {"id": 100003, "at": [1707, 4293]}',
        'split {"id": 100004, "at": [2000, 7250]}',
        'vertex {"id": 100002, "at": [1000, 2000]}',
        'vertex {"id": 100002, "at": [0, 0], "delete": true}',
        'vertex {"id": 100003, "at": [1000, 4000], "delete": true}',
        'vertex {"id": 100003, "at": [2000, 5000], "delete": true}',
        'vertex {"id": 100004, "at": [2000, 7000], "delete": true}',
        'vertex {"id": 100004, "at": [2000, 7250]}',
        'vertex {"id": 100005, "at": [1000, 11000], "delete": true}',
        'vertex {"id": 100005, "at": [1500, 10500]}',
        'convert_spline {"id": 100004}',
    ]:
        sc.cmds(*shapes, c, LINES)
    assert sc.transcript() == sc.golden()


def test_join_polyline_of_reversed_pieces_and_arcs(sc):
    """CATCHES: Join failing on pieces drawn the other way round (an arc's turn must flip with it), joining out of order,
    or not closing the polyline when its ends meet."""
    sc.cmds(
        'detail_line {"points": [[1000,0],[0,0]]}',
        'detail_line {"start": [2000,1000], "end": [1000,0], "arc": -90}',
        'detail_line {"points": [[2000,1000],[2000,2000],[3000,2000]]}',
        'join_polyline {"ids": [100003, 100002, 100004]}',
        'detail_line {"points": [[0,5000],[1000,5000]]}',
        'detail_line {"start": [1000,6000], "end": [1000,5000], "arc": 180}',
        'detail_line {"points": [[0,6000],[1000,6000]]}',
        'detail_line {"points": [[0,6000],[0,5000]]}',
        'join_polyline {"ids": [100005, 100006, 100007, 100008]}',
        LINES,
        PLAN_SVG,
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_align_columns_floors_regions_notes_separators_sections_and_pipes(sc):
    """CATCHES: Align not finding the straight edges or axes of a column, a floor, a filled region, a text note, a room
    separator, a section line or an upright pipe, or turning an upright pipe that has no plan rotation."""
    ref = '"reference": [[0,-1000],[0,20000]]'
    sc.cmds(
        'grid {"start": [0,-1000], "end": [0,20000]}',
        'column {"at": [1000, 0]}',
        f'align {{"id": 100003, {ref}, "line": [[800,-200],[800,200]]}}',
        'floor {"boundary": [[1000,2000],[3000,2000],[3000,4000],[1000,4000]]}',
        f'align {{"id": 100004, {ref}, "line": [[1000,2000],[1000,4000]]}}',
        'filled_region {"sketch": [[[1000,5000],[2000,5000]],[[2000,5000],[2000,6000]],[[2000,6000],[1000,6000]],[[1000,6000],[1000,5000]]]}',
        f'align {{"id": 100005, {ref}, "line": [[1000,5000],[1000,6000]]}}',
        'text {"text": "Note", "at": [1000, 7000]}',
        f'align {{"id": 100006, {ref}, "line": [[1000,6990],[1000,7010]]}}',
        'room_separator {"points": [[1000,8000],[1000,9000]]}',
        f'align {{"id": 100007, {ref}, "line": [[1000,8000],[1000,9000]]}}',
        'section {"start": [1000,10000], "end": [1000,12000], "name": "S1"}',
        f'align {{"id": 100008, {ref}, "line": [[1000,10000],[1000,12000]]}}',
        'pipe {"points": [[1000,13000],[1000,13000]], "offset": 0, "end_offset": 2000}',
        f'align {{"id": 100009, {ref}, "line": [[1000,13000],[1000,13025]]}}',
        'detail_line {"points": [[1000,15000],[2000,15000]]}',
        'create_group {"ids": [100010], "name": "Dash"}',
        f'align {{"id": 100011, {ref}, "line": [[1000,15000],[2000,15000]]}}',
        'elements {"category": "column"}',
        'elements {"category": "floor"}',
        'elements {"category": "detailgroup"}',
    )
    sc.cmds(
        'pipe {"points": [[1000,13000],[1000,13000]], "offset": 0, "end_offset": 2000}',
        'align {"id": 100002, "reference": [[0,0],[1000,1000]], "line": [[1000,13000],[1000,13025]]}',
    )
    sc.cmds('detail_line {"centre": [0,0], "radius": 500}', 'align {"id": 100002, "reference": [[0,0],[0,1000]], "line": [[500,0],[500,10]]}')
    assert sc.transcript() == sc.golden()


def test_filled_regions_with_curved_sketch_lines_and_edit_boundary(sc):
    """CATCHES: a filled region's sketch not taking whole curves (an ellipse outline, a circle hole, a spline edge, a line
    of its own style or invisible), its area worked out wrongly, or Edit Boundary not listing its lines with ids and
    keeping a line sent back by id."""
    sc.cmds(
        'filled_region {"sketch": [{"centre": [0,0], "radii": [3000,2000]}, {"centre": [0,0], "radius": 1000, "style": "Wide Lines"}], "type": "Crosshatch"}',
        'filled_region {"sketch": [{"fit": [[5000,0],[6000,1000],[7000,0]]}, {"start": [7000,0], "end": [5000,0], "invisible": true}], "type": "Diagonal Up"}',
        'filled_region {"sketch": [{"control": [[0,4000],[1000,6000],[2000,4000]]}, [[2000,4000],[0,4000]]]}',
        'edit_boundary {"id": 100002}',
        'elements {"category": "region"}',
        PLAN_SVG,
    )
    sc.file("plan.svg")
    p = sc.run(["run", "--cmd", 'filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]]}',
                "--cmd", 'edit_boundary {"id": 100002}'], show=False)
    lines = json.loads(p.stdout.decode().splitlines()[1])
    sc.note(f"edit_boundary lists {len(lines['sketch'])} lines")
    ids = [l["id"] for l in lines["sketch"]]
    sketch = json.dumps([{"id": ids[0], "start": [0, 0], "end": [2000, 0], "style": "Wide Lines"},
                         [[2000, 0], [2000, 1000]], [[2000, 1000], [0, 1000]], {"id": ids[3], "start": [0, 1000], "end": [0, 0]}])
    sc.cmds('filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]]}',
            f'edit_boundary {{"id": 100002, "sketch": {sketch}}}', 'elements {"category": "region"}')
    sc.cmds('filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]]}',
            'edit_boundary {"id": 100002, "sketch": [{"id": 12345, "start": [0,0], "end": [1,1]}]}')
    sc.cmds('filled_region {"sketch": [{"centre": [0,0], "radius": 1000, "points": [[0,0],[1,1]]}]}')
    assert sc.transcript() == sc.golden()


def test_filled_regions_over_walls_floors_and_dashed_overhead_edges(sc):
    """CATCHES: a filled region drawn under the walls' poché or a masking region not hiding the model under it, a
    non-masking region losing the ink of the walls, dashed overhead roof edges, or a region of its own, or detail lines
    drawn under a region instead of over it."""
    sc.cmds(
        'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true, "type": "Exterior - 300mm"}',
        'roof {"overhang": 600}',
        'floor {}',
        'detail_line {"points": [[-1000,3000],[9000,3000]], "style": "Hidden Lines"}',
        'filled_region {"sketch": [[[-500,-500],[3000,-500]],[[3000,-500],[3000,2000]],[[3000,2000],[-500,2000]],[[-500,2000],[-500,-500]]], "type": "Solid Black"}',
        'filled_region {"sketch": [[[2000,1000],[5000,1000]],[[5000,1000],[5000,7000]],[[5000,7000],[2000,7000]],[[2000,7000],[2000,1000]]], "type": "Masking"}',
        'filled_region {"sketch": [[[6000,-800],[9000,-800]],[[9000,-800],[9000,6800]],[[9000,6800],[6000,6800]],[[6000,6800],[6000,-800]]], "type": "Diagonal Up"}',
        'filled_region {"sketch": [[[4000,4000],[7000,4000]],[[7000,4000],[7000,5000]],[[7000,5000],[4000,5000]],[[4000,5000],[4000,4000]]], "type": "Brick"}',
        PLAN_SVG,
        'render {"view": "Level 1", "path": "plan.png", "width": 800, "height": 500}',
    )
    sc.file("plan.svg")
    png_shape(sc, "plan.png")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Move, rotate, mirror and copy every kind of element
# ---------------------------------------------------------------------------

MANY = [
    'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}',
    'door {"at": [2000, 0]}',
    'room {"point": [4000, 3000], "name": "Hall"}',
    "floor {}",
    'ceiling {"point": [4000, 3000]}',
    'roof {"slope": 30}',
    'shaft {"boundary": [[5000,4000],[6000,4000],[6000,5000],[5000,5000]]}',
    'grid {"start": [-1000,-1000], "end": [-1000,7000]}',
    'section {"start": [0,-2000], "end": [8000,-2000], "name": "S1"}',
    'component {"family": "Table", "at": [2000, 3000]}',
    'stair {"start": [6000, 1000], "angle": 90, "landings": [{"at": 8, "turn": 90}], "railings": true}',
    'spot {"at": [1000, 5000]}',
    'tag {"ids": [100006]}',
    'dimension {"refs": [{"id": 100002}, {"id": 100004}], "at": [4000, 1000]}',
    'column {"at": [1000, 1000]}',
    'beam {"points": [[0,0],[8000,0]], "level": "Level 2"}',
    'mass {"boundary": [[20000,0],[25000,0],[25000,5000],[20000,5000]], "height": 6000}',
    'ramp {"start": [12000, 0], "end": [12000, 8000]}',
    'railing {"path": [[14000,0],[14000,4000]]}',
    'text {"text": "Note", "at": [500, 500]}',
    'detail_line {"points": [[0,-500],[1000,-500]]}',
]
MANY_IDS = json.dumps(list(range(100002, 100028)))


def test_rotate_and_mirror_every_kind_of_element(sc):
    """CATCHES: rotate or mirror leaving some kind of element where it was or turning it wrongly: walls with their door
    and its tag, rooms, floors, ceilings, roofs, shafts, grids, sections, components, stairs with turned landings and
    their railings, spots, dimensions, columns, beams, masses, ramps, railings, notes and detail lines."""
    sc.cmds(*MANY, f'rotate {{"ids": {MANY_IDS}, "about": [4000,3000], "angle": 90}}', "elements {}")
    sc.cmds(*MANY, f'mirror {{"ids": {MANY_IDS}, "axis": [[-2000,0],[-2000,1000]]}}', "elements {}")
    assert sc.transcript() == sc.golden()


def test_copy_and_mirrored_copies_of_every_kind_of_element(sc):
    """CATCHES: copies of a whole building not getting new ids, new grid, section and room names or numbers and door
    marks, hosted doors, tags, spots, railings and dimensions not pointing at their copied hosts, or mirrored copies not
    flipped."""
    sc.cmds(*MANY, f'copy {{"ids": {MANY_IDS}, "by": [0, 30000]}}', "elements {}")
    sc.cmds(*MANY, f'mirror {{"ids": {MANY_IDS}, "axis": [[0,-5000],[1000,-5000]], "copy": true}}', "elements {}")
    assert sc.transcript() == sc.golden()


def test_transform_refusals_and_viewports(sc):
    """CATCHES: a level moved in plan, a door turned or mirrored without its wall, a stair's railing moved without it, a
    view placed twice on a sheet by copying its viewport, or overlapping doors made by a copy, being accepted; or a
    viewport and a camera view not moving."""
    pre = [
        'wall {"points": [[0,0],[8000,0]]}',
        'door {"at": [2000, 0]}',
        'stair {"start": [6000, 1000], "angle": 90, "railings": true}',
        'sheet {"number": "A1"}',
        'place {"sheet": "A1", "view": "Level 1"}',
        'camera {"eye": [10000, -10000, 1600], "target": [0, 0, 1000], "name": "Cam"}',
    ]
    for c in [
        'move {"ids": [100000], "by": [1, 1]}',
        'move {"ids": [100007], "by": [1, 1]}',
        'rotate {"ids": [100003], "about": [0,0], "angle": 30}',
        'mirror {"ids": [100003], "axis": [[0,0],[0,1000]]}',
        'move {"ids": [100003], "by": [100, 100]}',
        'rotate {"ids": [100005], "about": [0,0], "angle": 30}',
        'copy {"ids": [100005], "by": [0, 5000]}',
        'copy {"ids": [100003], "by": [500, 0]}',
        'copy {"ids": [100008], "by": [10, 10]}',
        'copy {"ids": [100000], "by": [10, 10]}',
        'move {"ids": [100008], "by": [10, 20]}\nelements {"category": "viewport"}',
        'rotate {"ids": [100009], "about": [0,0], "angle": 90}\nelements {"category": "view3d"}',
        'mirror {"ids": [100009], "axis": [[0,0],[1000,0]]}\nelements {"category": "view3d"}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


def test_modify_text_location_nested_fields_and_category(sc):
    """CATCHES: modify letting an element change category, a wall's `location` change that moves the wall's faces (it must
    keep them and move its line), a level's `view_range` not merged field by field, or a note's text not changed."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]], "type": "Exterior - 300mm"}',
        'door {"at": [3000, 0]}',
        'modify {"id": 100002, "location": "exterior-finish"}',
        'modify {"id": 100000, "view_range": {"cut": 1500, "top": 2800}}',
        'modify {"id": 100000, "view_range": {"bottom": -100, "depth": -500}}',
        'text {"text": "First note", "at": [0, 1000]}',
        'modify {"id": 100004, "text": "Second note, longer"}',
        WALLS,
        *OPENINGS[:1],
        'elements {"category": "level"}',
        'elements {"category": "text"}',
    )
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', 'modify {"id": 100002, "category": "floor"}')
    assert sc.transcript() == sc.golden()


def test_line_style_and_pattern_deletes_refused_where_used(sc):
    """CATCHES: a line style deleted while a filled region's boundary or a detail group's member is drawn in it, or a
    fill pattern deleted while a material shows it, or a `pattern: null` not making a style solid."""
    sc.cmds('line_style {"name": "Edge", "pen": 3, "pattern": "Dash"}', 'line_style {"name": "Edge", "pattern": null}')
    sc.cmds('line_style {"name": "Edge", "pen": 3}',
            'filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]], "line_style": "Edge"}',
            'line_style {"name": "Edge", "delete": true}')
    sc.cmds('line_style {"name": "Edge", "pen": 3}', 'detail_line {"points": [[0,0],[1000,0]], "style": "Edge"}',
            'create_group {"ids": [100002], "name": "G"}', 'line_style {"name": "Edge", "delete": true}')
    sc.cmds('fill_pattern {"name": "Mine", "lines": [{"angle": 0, "spacing": 2}]}',
            'material {"name": "Stone", "cut": "Mine"}', 'fill_pattern {"name": "Mine", "delete": true}')
    sc.cmds('filled_region_type {"name": "T", "foreground": 5}')
    sc.cmds('filled_region {"sketch": [[[0,0],[1000,0]],[[1000,0],[1000,1000]],[[1000,1000],[0,1000]],[[0,1000],[0,0]]], "line_style": 5}')
    sc.cmds('wall {"points": [[0,0],[5000,0]]}', 'section {"start": [0,-1000], "end": [5000,-1000], "name": "S1"}',
            'linework {"view": "S1", "id": 100002, "at": [2500,100], "style": "Wide Lines"}')
    assert sc.transcript() == sc.golden()


def test_dimension_value_moves_what_it_measures_and_locks_hold(sc):
    """CATCHES: a typed dimension value moving the wrong reference or by the wrong amount, a later segment's value
    ignored, or a locked segment not carried along when what it measures to is moved."""
    sc.cmds(
        'wall {"points": [[0,0],[0,4000]]}',
        'wall {"points": [[3000,0],[3000,4000]]}',
        'wall {"points": [[5000,0],[5000,4000]]}',
        'dimension {"refs": [{"id": 100002}, {"id": 100003}, {"id": 100004}], "at": [0, 2000]}',
        'dimension_value {"id": 100005, "value": 2500}',
        'dimension_value {"id": 100005, "value": 1000, "segment": 1}',
        'dimension_constraint {"id": 100005, "locked": [0]}',
        'move {"ids": [100003], "by": [500, 0]}',
        'dimension_value {"id": 100005, "value": 1800}',
        WALLS,
        'elements {"category": "dimension"}',
    )
    pre = ['wall {"points": [[0,0],[0,4000]]}', 'wall {"points": [[3000,0],[3000,4000]]}',
           'dimension {"refs": [{"id": 100002}, {"id": 100003}], "at": [0, 2000]}']
    for c in [
        'dimension_value {"id": 100004, "value": 0}',
        'dimension_value {"id": 100004}',
        'dimension_value {"id": 100004, "value": 100, "segment": 3}',
        'dimension_value {"id": 100002, "value": 100}',
        'dimension_value {"id": 100004, "value": 100, "bogus": 1}',
    ]:
        sc.cmds(*pre, c)
    assert sc.transcript() == sc.golden()


def test_align_components_ceilings_roofs_shafts_masses_runs_and_stairs(sc):
    """CATCHES: Align not finding the edges of a component's pieces, a ceiling, a roof's outline, a shaft, a mass, a
    beam's footprint, a railing's path, a stair's run or a round column's axes, or moving one by the wrong amount."""
    ref = '"reference": [[0,-1000],[0,40000]]'
    sc.cmds(
        'grid {"start": [0,-1000], "end": [0,40000]}',
        'component {"family": "Table", "at": [2000, 0]}',
        f'align {{"id": 100003, {ref}, "line": [[1400,-400],[1400,400]]}}',
        'ceiling {"boundary": [[1000,2000],[3000,2000],[3000,4000],[1000,4000]]}',
        f'align {{"id": 100004, {ref}, "line": [[1000,2000],[1000,4000]]}}',
        'roof {"boundary": [[1000,5000],[3000,5000],[3000,7000],[1000,7000]]}',
        f'align {{"id": 100005, {ref}, "line": [[1000,5000],[1000,7000]]}}',
        'shaft {"boundary": [[1000,8000],[2000,8000],[2000,9000],[1000,9000]]}',
        f'align {{"id": 100006, {ref}, "line": [[1000,8000],[1000,9000]]}}',
        'mass {"boundary": [[1000,10000],[2000,10000],[2000,11000],[1000,11000]], "height": 3000}',
        f'align {{"id": 100007, {ref}, "line": [[1000,10000],[1000,11000]]}}',
        'beam {"points": [[1000,12000],[1000,15000]]}',
        f'align {{"id": 100008, {ref}, "line": [[1000,12000],[1000,15000]]}}',
        'railing {"path": [[1000,16000],[1000,18000]]}',
        f'align {{"id": 100009, {ref}, "line": [[1000,16000],[1000,18000]]}}',
        'stair {"start": [2000, 20000], "angle": 90}',
        f'align {{"id": 100010, {ref}, "line": [[1500,20000],[1500,24480]]}}',
        'column {"at": [1000, 30000], "type": "Round 300"}',
        f'align {{"id": 100011, {ref}, "line": [[1000,29900],[1000,30100]]}}',
        "elements {}",
    )
    assert sc.transcript() == sc.golden()


def test_import_fill_patterns_limits_of_a_hostile_file(sc):
    """CATCHES: a PAT reader without its limits: a family of more than 16 dashes or a pattern of more than 256 families
    kept, a bad line not spoiling only its own pattern, an explicit `;%TYPE=DRAFTING` misread, or a file of more than
    2000 patterns read whole instead of its first 2000 with the rest counted."""
    many_dashes = "0,0,0,0,10" + ",1,-1" * 9
    families = "".join(f"{i},0,0,0,10\n" for i in range(257))
    sc.write("edge.pat", f"*Drafted\n;%TYPE=MODEL\n;%TYPE=DRAFTING\n0,0,0,0,4\n*Dashy\n{many_dashes}\n*Crowd\n{families}"
                         "*Spoilt\n0,0,0,0,5\nnot numbers\n90,0,0,0,5\n*Good, after\n90,0,0,0,7\n")
    sc.write("many.pat", "".join(f"*P{i}\n0,0,0,0,10\n" for i in range(2003)))
    sc.cmds('import_fill_patterns {"path": "edge.pat"}', 'fill_pattern {"name": "Drafted"}', 'fill_pattern {"name": "Good"}')
    p = sc.run(["run", "--cmd", 'import_fill_patterns {"path": "many.pat"}'], show=False)
    reply = json.loads(p.stdout.decode())
    sc.note(f"[exit {p.returncode}] imported {len(reply['imported'])}: {reply['imported'][:2]} … {reply['imported'][-2:]}")
    sc.note(json.dumps({"left_out": reply["left_out"], "left_out_count": reply["left_out_count"]}))
    assert sc.transcript() == sc.golden()
