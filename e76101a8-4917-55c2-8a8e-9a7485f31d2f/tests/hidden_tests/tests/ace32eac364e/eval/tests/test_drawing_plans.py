"""How a plan is drawn: the sample house's plans and ceiling plan, scale and detail level, line weights, object styles,
technical standards and background grids, and the `render` command's replies, files and errors.

The sample house letters a note in Arial, which the machine's own font stands in for, so its tests letter that type in a
font the program carries (IBM Plex Sans) first."""

import base64
import json
import re
import zlib
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


PLEX = _cmd("text_type", {"name": "2.5mm", "font": "IBM Plex Sans"})


def test_sample_house_plans_and_ceiling_plan(run, workdir, golden):
    """CATCHES: a rewrite whose plans of the sample house differ from the reference's in any line, fill, pattern, symbol
    or letter: walls cut with their layers, doors' swings, windows, stairs, rooms and their tags, the note, the levels'
    title; or whose reflected ceiling plan draws another thing than what is overhead."""
    r = run(["run", "--sample", "--cmd", PLEX, "--save", "plan.svg",
             "--cmd", 'render {"view": "Level 1", "ceiling": true, "path": "ceiling.svg"}'])
    golden.check_run(r, "sample_run.txt")
    golden.check((workdir / "plan.svg").read_text(), "sample_plan.svg")
    golden.check((workdir / "ceiling.svg").read_text(), "sample_ceiling.svg")


# A compound wall (finish, insulation, structure) in an L, with a door and a window, and a floor with a surface pattern.
COMPOUND = [
    _cmd("material", {"name": "Tiles", "surface": "Tile 300", "cut": "crosshatch"}),
    _cmd("type", {"category": "wall", "name": "Cavity", "layers": [
        {"function": "finish", "material": "Brick", "thickness": 100},
        {"function": "thermal", "material": "Insulation", "thickness": 50},
        {"function": "structure", "material": "Concrete", "thickness": 150}]}),
    _cmd("type", {"category": "floor", "name": "Tiled", "layers": [
        {"function": "finish", "material": "Tiles", "thickness": 20},
        {"function": "structure", "material": "Concrete", "thickness": 200}]}),
    'wall {"points": [[0, 0], [5000, 0], [5000, 3000]], "type": "Cavity"}',
    'door {"at": [2500, 0]}',
    'window {"at": [5000, 1500]}',
    'floor {"boundary": [[0, 0], [5000, 0], [5000, 3000], [0, 3000]], "type": "Tiled"}',
]


def test_detail_levels_and_scales_change_the_drawing(run, workdir, golden):
    """CATCHES: a rewrite that draws a compound wall's layers, their patterns, a door's leaf and swing, a window's glass
    or a floor's surface pattern at a detail level that leaves them out (coarse: one poché and gaps; medium: layers,
    leaves and swings but no patterns), or that doesn't size pens and annotation by the view's scale."""
    r = _script(run, workdir, COMPOUND, "--save", "fine.svg",
                "--cmd", 'detail {"view": "Level 1", "detail": "medium"}', "--save", "medium.svg",
                "--cmd", 'detail {"view": "Level 1", "detail": "coarse"}', "--save", "coarse.svg",
                "--cmd", 'detail {"view": "Level 1", "detail": "fine"}',
                "--cmd", 'scale {"view": "Level 1", "scale": 20}', "--save", "at20.svg",
                "--cmd", 'scale {"view": "Level 1", "scale": 500}', "--save", "at500.svg")
    golden.check_run(r, "detail_run.txt")
    for name in ["fine", "medium", "coarse", "at20", "at500"]:
        golden.check((workdir / f"{name}.svg").read_text(), f"compound_{name}.svg")


SCALE_ERRORS = [
    'scale {"view": "Level 1", "scale": null}',
    'scale {"view": "Level 1", "scale": 0}',
    'scale {"view": "Level 1", "scale": 200000}',
    'scale {"view": "Level 1", "scale": "1:50"}',
    'scale {"view": "Nowhere", "scale": 50}',
    'scale {"view": "A101", "scale": 50}',
    'scale {"scale": 50}',
    'scale {"view": "{3D}", "scale": 50}',
    'detail {"view": "Level 1", "detail": "extreme"}',
    'detail {"view": "Level 1", "detail": 3}',
    'detail {"view": "A101", "detail": "fine"}',
    'detail {"view": "Nowhere"}',
]


def test_scale_and_detail_replies_and_errors(run, workdir, golden):
    """CATCHES: a rewrite whose `scale` and `detail` don't say what a plan, a section or an elevation has without a
    value, take a scale out of 1 to 100000 or null, set them on a sheet or a view there isn't, or take an unknown detail
    level; or that words the refusal differently."""
    setup = [
        'wall {"points": [[0, 0], [4000, 0]]}',
        'section {"start": [2000, -1000], "end": [2000, 1000], "name": "S"}',
        'sheet {"number": "A101", "name": "Plans"}',
    ]
    r = _script(run, workdir, [
        *setup,
        'scale {"view": "Level 1"}',
        'scale {"view": "S", "scale": 25}',
        'scale {"view": "S"}',
        'detail {"view": "Level 2"}',
        'detail {"view": "S", "detail": "coarse"}',
        'detail {"view": "S"}',
        'units {"length": "ft-in"}',
        'scale {"view": "Level 2"}',
        'scale {"view": "Level 2", "scale": 48}',
    ])
    golden.check(_outcome(r) + "\n" + _sweep(run, workdir, setup, SCALE_ERRORS), "scale_detail.txt")


def test_line_weights_are_read_set_and_reset(run, workdir, golden):
    """CATCHES: a rewrite whose starter line weights differ (metric or imperial columns, the scale names), that doesn't
    sort the columns given, doesn't say `own`, doesn't draw a plan's pens in the column of the scale nearest the view's,
    or doesn't go back to the start on `reset`."""
    widths = [round(0.1 * (i + 1), 2) for i in range(16)]
    r = _script(run, workdir, [
        'wall {"points": [[0, 0], [4000, 0], [4000, 3000]]}',
        'text_type {"name": "2.5mm", "font": "IBM Plex Sans"}',
        'text {"text": "Pens", "at": [0, 1500]}',
        "line_weights {}",
        _cmd("line_weights", {"model": [{"scale": 200, "widths": widths[::-1]}, {"scale": 50, "widths": widths}],
                              "annotation": [0.5] * 16}),
        'scale {"view": "Level 1", "scale": 75}',
    ], "--save", "own.svg", "--cmd", 'line_weights {"reset": true}', "--save", "reset.svg",
        "--cmd", 'units {"length": "ft-in"}', "--cmd", "line_weights {}")
    golden.check_run(r, "line_weights.txt")
    golden.check((workdir / "own.svg").read_text(), "line_weights_own.svg")
    golden.check((workdir / "reset.svg").read_text(), "line_weights_reset.svg")


LINE_WEIGHT_ERRORS = [
    _cmd("line_weights", {"model": []}),
    _cmd("line_weights", {"model": [{"scale": 100, "widths": [0.2] * 15}]}),
    _cmd("line_weights", {"model": [{"scale": 100, "widths": [0.2] * 16}, {"scale": 100, "widths": [0.3] * 16}]}),
    _cmd("line_weights", {"model": [{"scale": 0, "widths": [0.2] * 16}]}),
    _cmd("line_weights", {"model": [{"scale": 100, "widths": [0.2] * 15 + [25]}]}),
    _cmd("line_weights", {"annotation": [0.2] * 15 + [0.001]}),
    _cmd("line_weights", {"annotation": "thin"}),
    _cmd("line_weights", {"reset": "yes"}),
    _cmd("line_weights", {"model": [{"scale": 100 + i, "widths": [0.2] * 16} for i in range(33)]}),
]


def test_line_weight_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes no scales or more than 32, a column of other than 16 pens, a scale twice or out of
    range, a width out of 0.01 to 20 mm, or a `reset` that isn't true or false; or that words the refusal differently."""
    golden.check(_sweep(run, workdir, [], LINE_WEIGHT_ERRORS), "line_weight_errors.txt")


def test_object_styles_are_read_set_and_reset(run, workdir, golden):
    """CATCHES: a rewrite whose starter object styles differ, that loses the pen a category isn't given, keeps a
    category given what it starts with as its own, lays `component` under the family categories, doesn't draw the
    plan's cut walls and doors in the pens set, or doesn't go back on `reset`."""
    r = _script(run, workdir, [
        *COMPOUND,
        _cmd("object_styles", {"categories": {"wall": {"cut": 14}, "door": {"projection": 1, "cut": 12},
                                              "window": {"cut": 6}, "component": {"projection": 8}}}),
        _cmd("object_styles", {"categories": {"wall": {"projection": 2}, "furniture": {"cut": 3}}}),
    ], "--save", "styled.svg", "--cmd", 'object_styles {"reset": true}', "--cmd",
        'object_styles {"categories": {"floor": {"projection": 4}}}')
    golden.check_run(r, "object_styles.txt")
    golden.check((workdir / "styled.svg").read_text(), "object_styles.svg")


OBJECT_STYLE_ERRORS = [
    _cmd("object_styles", {"categories": {"dimension": {"cut": 3}}}),
    _cmd("object_styles", {"categories": {"wall": {"cut": 17}}}),
    _cmd("object_styles", {"categories": {"wall": {"cut": 2.5}}}),
    _cmd("object_styles", {"categories": {"wall": {"weight": 2}}}),
    _cmd("object_styles", {"categories": ["wall"]}),
    _cmd("object_styles", {"reset": 1}),
]


def test_object_style_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes an annotation category, a pen past 16 or not whole, an unknown key, a list for the
    categories or a `reset` that isn't true or false; or that words the refusal differently."""
    golden.check(_sweep(run, workdir, [], OBJECT_STYLE_ERRORS), "object_style_errors.txt")


def test_technical_standards(run, workdir, golden):
    """CATCHES: a rewrite whose standards report other names, references, projections, units or sheet sizes, or that
    adapts line weights, object styles and units otherwise than each flag says (ANSI to feet and inches, back to the
    standard's own units), or that a Portuguese project doesn't start in NBR."""
    r = _script(run, workdir, [
        "standard {}",
        _cmd("standard", {"set": "ansi"}),
        'units {}',
        "line_weights {}",
        _cmd("standard", {"set": "ISO", "adapt_all": False}),
        "line_weights {}",
        _cmd("standard", {"set": "jis", "adapt_all": False, "adapt_units": True, "adapt_object_styles": True}),
        "object_styles {}",
        _cmd("standard", {"set": "eu", "adapt_line_weights": True, "adapt_object_styles": False, "adapt_units": False}),
        "line_weights {}",
        _cmd("standard", {"set": "nbr"}),
        "object_styles {}",
        "line_weights {}",
        'new {"language": "pt"}',
        "standard {}",
    ])
    golden.check_run(r, "standards.txt")


def test_a_standards_pens_drawn_in_a_plan(run, workdir, golden):
    """CATCHES: a rewrite whose standard sets other pens' widths or category pens, so a plan's cut and seen lines draw
    other widths."""
    r = _script(run, workdir, [*COMPOUND, _cmd("standard", {"set": "nbr"})], "--save", "nbr.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "nbr.svg").read_text(), "standard_nbr.svg")


STANDARD_ERRORS = [
    _cmd("standard", {"set": "din"}),
    _cmd("standard", {"set": "iso", "adapt_all": "yes"}),
    _cmd("standard", {"set": "iso", "adapt_units": 1}),
    _cmd("standard", {"set": 5}),
]


def test_standard_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes a standard it hasn't, or a flag that isn't true or false; or words it differently."""
    golden.check(_sweep(run, workdir, [], STANDARD_ERRORS), "standard_errors.txt")


def test_background_grids_of_views_and_templates(run, workdir, golden):
    """CATCHES: a rewrite whose background grid patch doesn't merge into what a view has, doesn't go back to the
    defaults on null, isn't saved with the view, or isn't taken from a template that controls it (nor refused to the
    view that follows it)."""
    r = _script(run, workdir, [
        _cmd("graphics", {"background_grid": {"main": {"enabled": True, "color": [200, 0, 0], "pen": 2},
                                              "sub": {"enabled": True}, "spacing": [500, 250], "divisions": [4, 2],
                                              "rotation": 30}}),
        _cmd("graphics", {"background_grid": {"visible": False, "sub": {"pen": 5}}}),
        _cmd("template", {"name": "Gridded", "kind": "plan", "background_grid": {"main": {"enabled": True},
                                                                                 "spacing": [1200, 1200]},
                          "controls": ["background_grid"]}),
        _cmd("graphics", {"view": "Level 2", "template": "Gridded"}),
        _cmd("graphics", {"view": "Level 1", "background_grid": None}),
    ], "--save", "p.bimcraft")
    saved = json.loads((workdir / "p.bimcraft").read_text())
    views = {e["name"]: e.get("graphics") for e in saved["elements"].values() if e.get("category") == "level"}
    golden.check(_outcome(r) + normalize(json.dumps(views, indent=1, sort_keys=True)) + "\n", "background_grid.txt")


BACKGROUND_GRID_ERRORS = [
    _cmd("graphics", {"background_grid": {"spacing": [0, 1]}}),
    _cmd("graphics", {"background_grid": {"divisions": [0, 5]}}),
    _cmd("graphics", {"background_grid": {"rotation": 400}}),
    _cmd("graphics", {"background_grid": {"main": {"pen": 17}}}),
    _cmd("graphics", {"background_grid": {"colour": [1, 2, 3]}}),
    _cmd("graphics", {"background_grid": "on"}),
    _cmd("graphics", {"view": "Level 2", "background_grid": {"visible": False}}),
]


def test_background_grid_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes a grid spacing, divisions, rotation or pen out of range, an unknown key or a grid
    that isn't an object, or lets a view change a grid its template controls; or that words the refusal differently."""
    setup = [
        _cmd("template", {"name": "Gridded", "kind": "plan", "controls": ["background_grid"]}),
        _cmd("graphics", {"view": "Level 2", "template": "Gridded"}),
    ]
    golden.check(_sweep(run, workdir, setup, BACKGROUND_GRID_ERRORS), "background_grid_errors.txt")


def test_render_writes_a_plan_as_png_and_as_base64(run, workdir, golden):
    """CATCHES: a rewrite whose `render` of a plan replies with other fields, sizes the picture otherwise (clamped to
    16 to 8192 px a side), or draws other pixels into the file it writes or the PNG it returns as base64."""
    r = _script(run, workdir, [
        'wall {"points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "closed": true}',
        'door {"at": [2000, 0]}',
        'detail_line {"start": [0, 1500], "end": [4000, 1500], "style": "Hidden Lines"}',
        'render {"view": "Level 1", "path": "plan.png", "width": 400, "height": 300}',
        'render {"view": 100000, "path": "tiny.png", "width": 5, "height": 9000}',
        'render {"width": 200, "height": 120}',
        'render {"view": "Level 1", "ceiling": true, "width": 200, "height": 120}',
    ])
    assert r.returncode == 0, r.stderr.decode()
    lines = r.stdout.decode().splitlines()
    shown = []
    for line in lines[-4:]:
        reply = json.loads(line)
        data = reply.pop("pngBase64", None)
        pixels = png_pixels(base64.b64decode(data)) if data else "(written)\n"
        shown.append(json.dumps(reply, sort_keys=True) + "\n" + pixels)
    golden.check("".join(shown), "render_replies.txt")
    golden.check(png_pixels((workdir / "plan.png").read_bytes()), "render_plan_png.txt")
    golden.check(png_pixels((workdir / "tiny.png").read_bytes()), "render_tiny_png.txt")


RENDER_ERRORS = [
    'render {"view": "Nowhere"}',
    'render {"view": "Level 1", "path": "plan.pdf"}',
    'render {"view": "S", "path": "s.svg"}',
    'render {"view": 123456}',
    'render {"view": "Level 1", "width": "wide"}',
    'render {"view": "Level 1", "ceiling": "yes"}',
    'render {"view": "Level 1", "path": "nodir/plan.svg"}',
    'render {"view": "Level 1", "path": "nodir/plan.png"}',
]


def test_render_errors(run, workdir, golden):
    """CATCHES: a rewrite that renders a view there isn't, takes a width that isn't a number or a ceiling flag that
    isn't true or false, or writes into a missing folder; or that words the refusal differently."""
    setup = ['wall {"points": [[0, 0], [4000, 0]]}', 'section {"start": [2000, -1000], "end": [2000, 1000], "name": "S"}']
    golden.check(_sweep(run, workdir, setup, RENDER_ERRORS), "render_errors.txt")


# Cut layers in each pattern drawn in code (diagonal, horizontal, vertical, crosshatch) and one of the project's fill patterns,
# a floor's surface in a code pattern, and a ceiling of 600 mm tiles.
PATTERNED = [
    _cmd("material", {"name": "Diag", "cut": "diagonal", "surface": "grid"}),
    _cmd("material", {"name": "Hor", "cut": "horizontal"}),
    _cmd("material", {"name": "Ver", "cut": "vertical"}),
    _cmd("material", {"name": "Cross", "cut": "crosshatch"}),
    _cmd("material", {"name": "Hatch", "cut": "Diagonal Crosshatch"}),
    _cmd("type", {"category": "wall", "name": "Five", "layers": [
        {"function": "finish", "material": "Diag", "thickness": 100},
        {"function": "substrate", "material": "Hor", "thickness": 100},
        {"function": "structure", "material": "Ver", "thickness": 100},
        {"function": "thermal", "material": "Cross", "thickness": 100},
        {"function": "membrane", "material": "Hatch", "thickness": 100}]}),
    _cmd("type", {"category": "floor", "name": "Gridded", "layers": [
        {"function": "finish", "material": "Diag", "thickness": 20},
        {"function": "structure", "material": "Concrete", "thickness": 200}]}),
    _cmd("type", {"category": "ceiling", "name": "Tiles 600", "grid": 600, "thickness": 20}),
    'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true, "type": "Five"}',
    'floor {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "type": "Gridded"}',
    'ceiling {"point": [3000, 2000], "type": "Tiles 600"}',
]


def test_material_patterns_in_cut_layers_floors_and_ceilings(run, workdir, golden):
    """CATCHES: a rewrite that draws a cut layer's code pattern (diagonal, horizontal, vertical, crosshatch) or fill pattern
    along the wrong way or spacing, a floor's surface pattern, or a ceiling's tile grid in its reflected ceiling plan
    differently."""
    r = _script(run, workdir, PATTERNED, "--save", "plan.svg",
                "--cmd", 'render {"view": "Level 1", "ceiling": true, "path": "ceiling.svg"}')
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "plan.svg").read_text(), "patterned_plan.svg")
    golden.check((workdir / "ceiling.svg").read_text(), "patterned_ceiling.svg")


def test_a_cropped_plan_with_pattern_overrides(run, workdir, golden):
    """CATCHES: a rewrite that doesn't cut a plan's drawing to its crop region (lines, fills and patterns clipped at
    its sides), doesn't put a view's cut foreground and background patterns over the layers' own, or replies to `crop`
    differently."""
    r = _script(run, workdir, [
        *PATTERNED,
        _cmd("crop", {"view": "Level 1", "region": [[-500, -500], [3000, 2000]]}),
        _cmd("graphics", {"categories": {"wall": {"cut": {
            "foreground": {"pattern": "Sand", "color": [0, 0, 255]},
            "background": {"pattern": "Solid fill", "color": [255, 255, 200]}}}}}),
    ], "--save", "cropped.svg", "--cmd", 'crop {"view": "Level 1", "region": null}', "--save", "uncropped.svg")
    golden.check_run(r, "cropped_run.txt")
    golden.check((workdir / "cropped.svg").read_text(), "cropped.svg")
    golden.check((workdir / "uncropped.svg").read_text(), "uncropped.svg")


def _pdf_text(data):
    """A PDF with each stream inflated in place (it is vector drawing, so text), the cross reference table left out."""
    out = re.sub(rb"stream\r?\n(.*?)\r?\nendstream", lambda m: b"stream\n" + zlib.decompress(m.group(1)) + b"\nendstream",
                 data, flags=re.S)
    out = re.sub(rb"/Length \d+", b"/Length N", out)
    out = re.sub(rb"xref.*?trailer", b"xref ... trailer", out, flags=re.S)
    return re.sub(rb"startxref\s+\d+", b"startxref N", out).decode("latin-1")


def test_sheets_laid_out_by_each_standard(run, workdir, golden):
    """CATCHES: a rewrite whose sheet borders, binding margins, title blocks and folding marks don't follow the
    project's standard and the paper's size (NBR's 25 mm margin and folds on A3, ANSI's inch margins, JIS's A4)."""
    setup = ['wall {"points": [[0, 0], [6000, 0]]}']
    texts = []
    for code, size in [("nbr", "A3"), ("nbr", "A4"), ("ansi", "A4"), ("jis", "A4"), ("iso", "A4")]:
        r = _script(run, workdir, [
            *setup,
            _cmd("standard", {"set": code, "adapt_all": False}),
            _cmd("sheet", {"number": "A101", "name": "Plans", "size": size}),
            _cmd("place", {"sheet": "A101", "view": "Level 1"}),
        ], "--save", "sheet.pdf")
        assert r.returncode == 0, r.stderr.decode()
        texts.append(f"== {code} {size}\n" + _pdf_text((workdir / "sheet.pdf").read_bytes()))
    golden.check("\n".join(texts), "standard_sheets.txt")


FEATURES = [
    'wall {"points": [[0, 0], [12000, 0], [12000, 9000], [0, 9000]], "closed": true}',
    'stair {"start": [1000, 1500], "end": [5000, 1500], "landings": [{"at": 8, "turn": 180}], "railings": true}',
    'ramp {"start": [1000, 7000], "end": [9000, 7000], "height": 400, "railings": true}',
    'railing {"path": [[7000, 1000], [11000, 1000], [11000, 4000]]}',
    'shaft {"boundary": [[8000, 2000], [9500, 2000], [9500, 3500], [8000, 3500]]}',
    'room_separator {"points": [[6000, 4500], [12000, 4500]]}',
    'room {"point": [9000, 5500], "name": "East"}',
    'room {"point": [15000, 6000], "name": "Lost"}',
    'mass {"boundary": [[13000, 0], [15000, 0], [15000, 2000], [13000, 2000]], "height": 5000}',
    'column {"at": [6500, 3000], "base_offset": 2000}',
    'beam {"points": [[6000, 8000], [11000, 8000]], "offset": 2800}',
    'floor {"boundary": [[6500, 5000], [8000, 5000], [8000, 6000], [6500, 6000]], "slope": 5, "arrow": [[6500, 5500], [8000, 5500]]}',
    'graphics {"show": ["roomreference"]}',
]


def test_plans_draw_stairs_ramps_shafts_and_rooms(run, workdir, golden):
    """CATCHES: a rewrite whose plan draws a stair's treads, cut line and walk line (UP below, DN above), a ramp, a
    railing, a shaft's cross, a room separation line, a room's reference cross, an unenclosed room's warning, a mass's
    dashed outline, a beam above the cut or a sloped floor's arrow otherwise."""
    r = _script(run, workdir, FEATURES, "--save", "level1.svg",
                "--cmd", 'render {"view": "Level 2", "path": "level2.svg"}')
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "level1.svg").read_text(), "features_level1.svg")
    golden.check((workdir / "level2.svg").read_text(), "features_level2.svg")


CROP_ERRORS = [
    _cmd("crop", {"view": "Level 1", "region": [[3000, 3000], [0, 0]]}),
    _cmd("crop", {"view": "Level 1", "region": [[0, 0]]}),
    _cmd("crop", {"view": "Level 1", "region": "all"}),
    _cmd("crop", {"view": "S", "region": [[2000, 0], [500, 3000]]}),
    _cmd("crop", {"view": "Nowhere"}),
    _cmd("crop", {"view": "Level 2"}),
]


def test_crop_to_what_a_view_shows_and_crop_errors(run, workdir, golden):
    """CATCHES: a rewrite whose `crop` without a region doesn't crop a plan to what it shows (1 m round it) or a
    section to its heights, crops a section's line otherwise, or takes corners the wrong way round, a region that isn't
    two corners, or an empty plan; or that words the refusal differently."""
    setup = ['wall {"points": [[0, 0], [4000, 0], [4000, 3000]]}',
             'section {"start": [2000, -1000], "end": [2000, 4000], "name": "S"}']
    r = _script(run, workdir, [
        *setup,
        _cmd("crop", {"view": "Level 1"}),
        _cmd("crop", {"view": "S"}),
        _cmd("crop", {"view": "S", "region": [[500, -200], [4000, 3500]]}),
        'elements {"category": "section"}',
    ], "--save", "cropped.svg")
    golden.check(_outcome(r) + "\n" + _sweep(run, workdir, setup, CROP_ERRORS), "crop.txt")
