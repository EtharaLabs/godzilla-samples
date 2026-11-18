"""Line patterns, line styles, detail lines of every shape and Linework: their replies, their errors and how a plan draws
them (the SVG a plan saves to)."""

import json
from concurrent.futures import ThreadPoolExecutor

from conftest import normalize, png_pixels


def _script(run, workdir, lines, *extra, name="s.txt"):
    """`run --script` over `lines` (one `id {json}` each) written to `name` in the working directory."""
    (workdir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run(["run", "--script", name, *extra])


def _outcome(r):
    return (f"exit: {r.returncode}\n--- stdout\n" + normalize(r.stdout.decode("utf-8", "replace"))
            + "--- stderr\n" + normalize(r.stderr.decode("utf-8", "replace")))


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


FENCE = _cmd("line_pattern", {"name": "Fence", "segments": [{"dash": 4}, {"space": 1}, "dot", {"space": 1}]})
FENCE_LINE = _cmd("line_style", {"name": "Fence Line", "pen": 3, "color": [200, 0, 0], "pattern": "Fence"})


def test_line_patterns_and_styles_are_made_renamed_and_deleted(run, workdir, golden):
    """CATCHES: a rewrite whose starter line patterns or styles differ (names, pens, dashes), that doesn't carry a
    pattern's rename into the styles that use it, that loses what a changed style isn't given, that reads `"Solid"` as a
    pattern, or whose replies are shaped differently."""
    r = _script(run, workdir, [
        "line_pattern {}",
        "line_style {}",
        FENCE,
        FENCE_LINE,
        _cmd("line_pattern", {"name": "Fence", "rename": "Paling"}),
        _cmd("line_style", {"name": "Fence Line"}),
        _cmd("line_pattern", {"name": "Paling"}),
        _cmd("line_pattern", {"name": "  Fancy  ", "segments": [
            {"dot_length": 2}, {"offset": {"length": 5, "count": 3, "distance": 0.5}},
            {"wave": {"length": 6, "frequency": 2, "amplitude": 0.5}},
            {"zigzag": {"length": 4, "frequency": 1, "amplitude": 1}},
            {"text": {"length": 8, "size": 1.5, "text": "GAS"}}]}),
        _cmd("line_style", {"name": "Thick", "pen": 4}),
        _cmd("line_style", {"name": "Thick", "color": "#00ff00", "pattern": "Fancy"}),
        _cmd("line_style", {"name": "Thick", "pattern": "solid"}),
        _cmd("line_style", {"name": "Thick", "rename": "Heavy", "pen": 0}),
        _cmd("line_style", {"name": "Heavy", "delete": True}),
        _cmd("line_pattern", {"name": "Fancy", "delete": True}),
        "line_style {}",
    ])
    golden.check_run(r, "patterns_and_styles.txt")


LINE_PATTERN_ERRORS = [
    _cmd("line_pattern", {"name": "None", "segments": []}),
    _cmd("line_pattern", {"name": "Many", "segments": [{"dash": 1}] * 33}),
    _cmd("line_pattern", {"name": "Tiny", "segments": [{"dash": 0.01}]}),
    _cmd("line_pattern", {"name": "Long", "segments": [{"dash": 2}, {"space": 101}]}),
    _cmd("line_pattern", {"name": "Lonely", "segments": [{"offset": {"length": 5, "count": 1, "distance": 1}}]}),
    _cmd("line_pattern", {"name": "Flat", "segments": [{"wave": {"length": 5, "frequency": 0.05, "amplitude": 1}}]}),
    _cmd("line_pattern", {"name": "Mute", "segments": [{"text": {"length": 5, "size": 1, "text": "   "}}]}),
    _cmd("line_pattern", {"name": "Odd", "segments": [{"squiggle": 3}]}),
    _cmd("line_pattern", {"name": "Solid", "segments": [{"dash": 3}]}),
    _cmd("line_pattern", {"name": "Nothing"}),
    _cmd("line_pattern", {"name": "Dash", "rename": "Dot"}),
    _cmd("line_pattern", {"name": "Hidden", "delete": True}),
    _cmd("line_pattern", {"name": "Nowhere", "delete": True}),
    _cmd("line_pattern", {"name": "Dash", "colour": "red"}),
]


def test_line_pattern_errors(run, workdir, golden):
    """CATCHES: a rewrite that accepts a pattern of no or too many segments, a segment shorter or longer than paper
    allows, an offset of one line, a wave too slow, blank text, an unknown segment, the reserved name Solid, or that
    deletes a pattern a style still uses; or whose error messages are worded differently."""
    golden.check(_sweep(run, workdir, [], LINE_PATTERN_ERRORS), "line_pattern_errors.txt")


LINE_STYLE_ERRORS = [
    _cmd("line_style", {"name": "New"}),
    _cmd("line_style", {"name": "New", "pen": 17}),
    _cmd("line_style", {"name": "New", "pen": "heavy"}),
    _cmd("line_style", {"name": "New", "pen": 2, "color": [300, 0, 0]}),
    _cmd("line_style", {"name": "New", "pen": 2, "color": "#12345"}),
    _cmd("line_style", {"name": "New", "pen": 2, "pattern": "Wiggle"}),
    _cmd("line_style", {"name": "New", "pen": 2, "pattern": 3}),
    _cmd("line_style", {"name": "Thin Lines", "rename": "Wide Lines"}),
    _cmd("line_style", {"name": "Gone", "delete": True}),
    _cmd("line_style", {"name": "Wide Lines", "delete": True}),
    _cmd("line_style", {"name": "Medium Lines", "delete": True}),
    _cmd("line_style", {"name": "Hidden Lines", "delete": True}),
    _cmd("line_style", {"name": "Centre Lines", "delete": True}),
    _cmd("line_style", {"name": "Thin Lines", "weight": 3}),
]

LINE_STYLE_SETUP = [
    'wall {"points": [[0, 0], [4000, 0]]}',
    _cmd("detail_line", {"start": [0, 1000], "end": [2000, 1000], "style": "Wide Lines"}),
    _cmd("linework", {"id": 100002, "at": [1000, 100], "style": "Medium Lines"}),
    _cmd("filled_region", {"sketch": [[[0, 2000], [500, 2000]], [[500, 2000], [500, 2500]], [[500, 2500], [0, 2000]]],
                           "line_style": "Hidden Lines"}),
    _cmd("detail_line", {"start": [0, 3000], "end": [2000, 3000], "style": "Centre Lines"}),
    _cmd("create_group", {"ids": [100005], "name": "Axis"}),
]


def test_line_style_errors(run, workdir, golden):
    """CATCHES: a rewrite that makes a style without a pen, takes a pen past 16, a colour out of range or a pattern the
    project hasn't, renames over another style, or deletes a style a detail line, a view's Linework, a filled region's
    boundary or a detail group's member is drawn in; or that words those refusals differently."""
    golden.check(_sweep(run, workdir, LINE_STYLE_SETUP, LINE_STYLE_ERRORS), "line_style_errors.txt")


SHAPES = [
    FENCE,
    FENCE_LINE,
    _cmd("detail_line", {"start": [0, 0], "end": [3000, 0], "style": "Fence Line"}),
    _cmd("detail_line", {"start": [0, 1000], "end": [3000, 1000], "arc": 60, "style": "Wide Lines"}),
    _cmd("detail_line", {"start": [3500, 0], "end": [5000, 1000], "through": [4500, 200], "style": "Hidden Lines"}),
    _cmd("detail_line", {"centre": [5000, 2000], "radius": 800, "centre_mark": True}),
    _cmd("detail_line", {"centre": [8000, 2000], "radii": [1000, 500], "angle": 30, "span": [0, 270], "centre_mark": True}),
    _cmd("detail_line", {"centre": [8000, -1000], "radii": [900, 400]}),
    _cmd("detail_line", {"control": [[0, 3000], [1000, 4000], [2000, 3000], [3000, 4000]], "style": "Centre Lines"}),
    _cmd("detail_line", {"fit": [[4000, 3000], [5000, 4000], [6000, 3000]], "start_tangent": [1, 0], "end_tangent": [0, -1]}),
    _cmd("detail_line", {"points": [[0, -2000], [2000, -2000], [2000, -1000]], "arcs": [0, 90], "insulation": 200}),
    _cmd("detail_line", {"points": [[4000, -2000], [6000, -2000], [6000, -1000], [4000, -1000]], "closed": True,
                         "cloud": 300, "revision": "Rev A", "style": "Medium Lines"}),
    _cmd("detail_line", {"points": [[0, -3000], [3000, -3000]], "cloud": 250}),
    'elements {"category": "line"}',
]


def test_detail_lines_of_every_shape(run, workdir, golden):
    """CATCHES: a rewrite that stores a detail line's shape differently (lines, arcs by turn or through a point, circles,
    ellipses whole and partial, control-point and fitted splines, polylines with arcs, insulation and revision clouds),
    measures their lengths differently, or lists them in `elements` with other fields."""
    r = _script(run, workdir, SHAPES)
    golden.check_run(r, "shapes.txt")


def test_detail_lines_drawn_in_a_plan(run, workdir, golden):
    """CATCHES: a rewrite that draws detail lines in other pixels: a pattern's dashes and dots scaled to the paper, a
    style's pen width and colour, chords of arcs, ellipses and splines, centre marks, batt insulation's loops or a
    revision cloud's scallops."""
    r = _script(run, workdir, SHAPES[:-1], "--save", "plan.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "plan.svg").read_text(), "shapes.svg")


def test_pattern_segments_drawn_at_two_scales(run, workdir, golden):
    """CATCHES: a rewrite that draws a pattern's offset lines, waves, zigzags, dots of a length or lettering differently
    (round a closed line's corners too), draws a pattern of spaces only, doesn't keep them the same size on paper when
    the view's scale changes (1 : 50 draws them half as big against the model), or doesn't draw solid a pattern too
    small to see in a small picture."""
    lines = [
        _cmd("line_pattern", {"name": "Fancy", "segments": [
            {"dash": 3}, {"space": 1}, {"dot_length": 1}, {"space": 1},
            {"offset": {"length": 5, "count": 3, "distance": 0.6}}, {"space": 1},
            {"wave": {"length": 6, "frequency": 2, "amplitude": 0.6}}, {"space": 1},
            {"zigzag": {"length": 4, "frequency": 1, "amplitude": 0.8}}, {"space": 1},
            {"text": {"length": 8, "size": 1.5, "text": "GAS"}}, {"space": 1}]}),
        _cmd("line_style", {"name": "Fancy", "pen": 2, "pattern": "Fancy", "color": "#0000c0"}),
        _cmd("detail_line", {"start": [0, 0], "end": [6000, 0], "style": "Fancy"}),
        _cmd("detail_line", {"start": [0, 1500], "end": [6000, 1500], "arc": 40, "style": "Fancy"}),
        _cmd("detail_line", {"points": [[0, -3000], [3000, -3000], [3000, -1500], [0, -1500]], "closed": True,
                             "style": "Fancy"}),
        _cmd("line_pattern", {"name": "Blank", "segments": [{"space": 2}]}),
        _cmd("line_style", {"name": "Blank", "pen": 2, "pattern": "Blank"}),
        _cmd("detail_line", {"start": [4000, -3000], "end": [6000, -1500], "style": "Blank"}),
    ]
    r = _script(run, workdir, lines, "--save", "at100.svg", "--cmd", 'scale {"view": "Level 1", "scale": 50}',
                "--save", "at50.svg", "--cmd", 'render {"view": "Level 1", "path": "small.svg", "width": 60, "height": 40}')
    golden.check_run(r, "fancy_run.txt")
    golden.check((workdir / "at100.svg").read_text(), "fancy_100.svg")
    golden.check((workdir / "at50.svg").read_text(), "fancy_50.svg")
    golden.check((workdir / "small.svg").read_text(), "fancy_small.svg")


DETAIL_LINE_ERRORS = [
    "detail_line {}",
    _cmd("detail_line", {"start": [0, 0]}),
    _cmd("detail_line", {"start": [0, 0], "end": [0, 0]}),
    _cmd("detail_line", {"centre": [0, 0], "radius": -5}),
    _cmd("detail_line", {"centre": [0, 0], "radius": 2e9}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "arc": 359.9999999999}),
    _cmd("detail_line", {"points": [[0, 0]]}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "insulation": 0.5}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "insulation": 20000}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "cloud": 1e9}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "insulation": 100, "cloud": 100}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "view": "Nowhere"}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "style": "Squiggly"}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "colour": "red"}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "centre": [5, 5], "radius": 3}),
    _cmd("detail_line", {"start": ["a", 0], "end": [1000, 0]}),
    _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "cloud": 100, "revision": "r" * 257}),
]


def test_detail_line_errors(run, workdir, golden):
    """CATCHES: a rewrite that accepts a line with no shape, of no length, a circle of negative or astronomic radius, an
    arc that is all but a whole turn, insulation or clouds out of range or both at once, an unknown view or style, two
    shapes at once, or an unknown key; or that words those refusals differently."""
    golden.check(_sweep(run, workdir, [], DETAIL_LINE_ERRORS), "detail_line_errors.txt")


def test_detail_lines_in_a_section_and_on_a_sheet(run, workdir, golden):
    """CATCHES: a rewrite that puts a detail line given a section or a sheet in the wrong view, takes its coordinates in
    the wrong terms there (along and up a section; paper mm on a sheet), or lists it differently."""
    r = _script(run, workdir, [
        'wall {"points": [[0, 0], [4000, 0]]}',
        'section {"start": [2000, -2000], "end": [2000, 2000], "name": "A"}',
        'sheet {"number": "A101", "name": "Details"}',
        _cmd("detail_line", {"start": [0, 0], "end": [1000, 2000], "view": "A"}),
        _cmd("detail_line", {"centre": [100, 100], "radius": 20, "view": "A101", "style": "Wide Lines"}),
        _cmd("detail_line", {"start": [0, 0], "end": [1000, 0], "view": "Level 2"}),
        'elements {"category": "line"}',
    ])
    golden.check_run(r, "views.txt")


LINEWORK = [
    'type {"category": "wall", "name": "Partition", "thickness": 100}',
    'wall {"points": [[0, 0], [4000, 0]], "type": "Partition"}',
    'wall {"points": [[0, 2000], [4000, 2000]], "type": "Partition"}',
    _cmd("linework", {"id": 100002, "at": [1000, 45], "style": "Wide Lines"}),
    _cmd("linework", {"id": 100002, "at": [1000, -45], "invisible": True}),
    _cmd("linework", {"id": 100003, "at": [1000, 2045], "style": "Hidden Lines", "view": "Level 1"}),
    _cmd("linework", {"id": 100003, "at": [1000, 2045], "style": "Centre Lines"}),
]


def test_linework_restyles_and_hides_one_edge(run, workdir, golden):
    """CATCHES: a rewrite whose Linework picks another edge than the one nearest the point, doesn't replace the entry
    when the same edge is picked again, draws the whole element restyled instead of one face, or doesn't hide the
    invisible face; or whose replies differ."""
    r = _script(run, workdir, LINEWORK, "--save", "plan.svg", "--save", "p.bimcraft")
    golden.check_run(r, "linework_run.txt")
    golden.check((workdir / "plan.svg").read_text(), "linework.svg")
    saved = json.loads((workdir / "p.bimcraft").read_text())
    level = [e for e in saved["elements"].values() if e.get("category") == "level" and e.get("name") == "Level 1"]
    golden.check(normalize(json.dumps(level, indent=1, sort_keys=True)) + "\n", "linework_level.json")


def test_linework_remove_takes_off_one_edge_at_a_time(run, workdir, golden):
    """CATCHES: a rewrite whose `remove` takes off every edge within reach (both faces of a thin wall are), takes one
    off when the nearest edge has none, or doesn't take off a stale entry on a face a T wall cut in two."""
    r = _script(run, workdir, [
        *LINEWORK[:5],
        _cmd("linework", {"id": 100002, "at": [1000, 45], "remove": True}),
        _cmd("linework", {"id": 100002, "at": [1000, 45], "remove": True}),
        _cmd("linework", {"id": 100002, "at": [1000, 45], "style": "Wide Lines"}),
        'wall {"points": [[2000, 0], [2000, 1500]], "type": "Partition"}',
        _cmd("linework", {"id": 100002, "at": [500, 50], "remove": True}),
        _cmd("linework", {"id": 100002, "at": [1000, -50], "remove": True}),
        _cmd("linework", {"id": 100002, "at": [1000, -50], "remove": True}),
    ])
    golden.check_run(r, "linework_remove.txt")


LINEWORK_ERRORS = [
    _cmd("linework", {"id": 100002, "at": [1000, 900], "style": "Wide Lines"}),
    _cmd("linework", {"id": 100002, "at": [1000, 100]}),
    _cmd("linework", {"id": 100002, "at": [1000, 100], "style": "Nope"}),
    _cmd("linework", {"view": "Section 1", "id": 100002, "at": [1000, 100], "style": "Wide Lines"}),
    _cmd("linework", {"id": 999999, "at": [1000, 100], "style": "Wide Lines"}),
    _cmd("linework", {"id": 100002, "style": "Wide Lines"}),
    _cmd("linework", {"id": 100002, "at": [1000, 100], "style": "Wide Lines", "pen": 3}),
]


def test_linework_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes an edge too far from the pick, a Linework with neither style nor invisible, a line
    style the project hasn't, a section for a plan, an element there isn't or no point; or words the refusal differently."""
    setup = ['wall {"points": [[0, 0], [4000, 0]]}', 'section {"start": [0, -2000], "end": [0, 2000]}']
    golden.check(_sweep(run, workdir, setup, LINEWORK_ERRORS), "linework_errors.txt")


def test_linework_in_a_patterned_style(run, workdir, golden):
    """CATCHES: a rewrite that draws a Linework edge in a style whose pattern isn't plain dashes (waves, offsets,
    lettering) as plain dashes or solid, or restyles more of the element than that edge."""
    r = _script(run, workdir, [
        _cmd("line_pattern", {"name": "Wavy", "segments": [{"wave": {"length": 4, "frequency": 2, "amplitude": 0.5}},
                                                           {"space": 1}, "dot", {"space": 1},
                                                           {"text": {"length": 5, "size": 1.5, "text": "W"}}]}),
        _cmd("line_style", {"name": "Wavy", "pen": 3, "pattern": "Wavy", "color": "#0060c0"}),
        'wall {"points": [[0, 0], [6000, 0], [6000, 3000]]}',
        _cmd("linework", {"id": 100002, "at": [3000, 100], "style": "Wavy"}),
        _cmd("linework", {"id": 100003, "at": [5900, 1500], "style": "Hidden Lines"}),
    ], "--save", "wavy.svg")
    golden.check_run(r, "linework_wavy_run.txt")
    golden.check((workdir / "wavy.svg").read_text(), "linework_wavy.svg")


def test_a_long_revision_cloud_has_fewer_even_scallops(run, workdir, golden):
    """CATCHES: a rewrite that draws a revision cloud of more than 1,024 scallops (or of more corners than that allows)
    scallop by scallop instead of with fewer, even ones, or that draws one at all differently."""
    r = _script(run, workdir, [
        _cmd("detail_line", {"start": [0, 0], "end": [200000, 0], "cloud": 50, "revision": "B"}),
        _cmd("detail_line", {"points": [[0, 2000], *[[x * 100 + 50 * (x % 2), 2000 + 3000 * (x % 2)] for x in range(1, 1500)]],
                             "cloud": 40}),
        'elements {"category": "line", "limit": 1}',
        _cmd("render", {"view": "Level 1", "path": "clouds.png", "width": 600, "height": 300}),
    ])
    golden.check_run(r, "clouds_run.txt")
    golden.check(png_pixels((workdir / "clouds.png").read_bytes()), "clouds_png.txt")
