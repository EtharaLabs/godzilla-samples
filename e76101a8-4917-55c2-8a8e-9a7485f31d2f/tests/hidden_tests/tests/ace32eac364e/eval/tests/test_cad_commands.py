"""CAD imports as elements: `import_cad`'s options and refusals, `cad_layers`, `cad_query`, `reload_cad` and linked
drawings, editing an import, saving it with the project, and a DWG read through the program's own child process."""

import base64
import json
import re
import zlib

from conftest import normalize, resources_for

LONG_FLOAT = re.compile(r"-?\d+\.\d{7,}")


def check_rounded(golden, r, name):
    """`golden.check_run`, with the long decimals of the output (sines and cosines) rounded to six places."""
    out = LONG_FLOAT.sub(lambda m: repr(round(float(m.group(0)), 6)), r.stdout.decode())
    golden.check(f"exit: {r.returncode}\n--- stdout\n{normalize(out)}--- stderr\n{normalize(r.stderr.decode())}", name)


def outcome(r):
    """A run as `golden.check_run` shows it: its exit code, then its normalised output and errors."""
    return f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{normalize(r.stderr.decode())}"


def refusals(run, first, command, cases):
    """Each case's params given to COMMAND after the FIRST arguments, one run each: its outcome under its name."""
    report = []
    for case in sorted(cases):
        r = run(["run", *first, "--cmd", f"{command} " + json.dumps(cases[case])])
        report.append(f"### {case}\n{outcome(r)}")
    return "".join(report)


def pairs(*items):
    return "".join(f"{c}\n{v}\n" for c, v in items)


def dxf(entities, units="6", layers=(("WALLS", "1", False), ("FURN", "3", True), ("TEXT", "7", False)), tables=""):
    """An ASCII DXF of `units` ($INSUNITS) with these layers (name, colour, off) and entities."""
    table = pairs((0, "TABLE"), (2, "LAYER"))
    for name, color, off in layers:
        table += pairs((0, "LAYER"), (2, name), (70, "0"), (62, f"-{color}" if off else color), (6, "Continuous"))
    table += pairs((0, "ENDTAB"))
    return (pairs((0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, units), (0, "ENDSEC"))
            + pairs((0, "SECTION"), (2, "TABLES")) + tables + table + pairs((0, "ENDSEC"))
            + pairs((0, "SECTION"), (2, "ENTITIES")) + entities + pairs((0, "ENDSEC"), (0, "EOF")))


def line(layer, a, b):
    return pairs((0, "LINE"), (8, layer), (10, a[0]), (20, a[1]), (11, b[0]), (21, b[1]))


def plan_entities():
    """A room 10 m by 6 m in metres: walls on WALLS (red), a bench on FURN (off in its file), a note on TEXT."""
    walls = "".join(line("WALLS", a, b) for a, b in [((0, 0), (10, 0)), ((10, 0), (10, 6)), ((10, 6), (0, 6)), ((0, 6), (0, 0))])
    return walls + line("FURN", (1, 1), (2, 1)) + pairs((0, "TEXT"), (8, "TEXT"), (10, "1"), (20, "5"), (40, "0.25"), (1, "Kitchen"))


PLAN = dxf(plan_entities())


def script(workdir, *lines):
    (workdir / "script.txt").write_text("\n".join(lines) + "\n")
    return ["--script", "script.txt"]


# ---------------------------------------------------------------------------
# import_cad
# ---------------------------------------------------------------------------

def test_a_drawing_comes_in_centred_in_its_files_unit_with_its_off_layers_hidden(run, workdir, golden):
    """CATCHES: a rewrite whose import_cad reply or element differs (its keys, its name from the file's stem, the unit
    from $INSUNITS, the middle of the drawing on the origin, the layers off in the file hidden), or that leaves
    `colors`/`view` in an element that has the defaults."""
    (workdir / "ground floor.dxf").write_text(PLAN)
    r = run(["run", *script(workdir, 'import_cad {"path": "ground floor.dxf"}', 'elements {"category": "cadimport"}',
                            'cad_layers {"id": 100002}')])
    golden.check_run(r, "default_import.txt")


def test_position_at_and_angle_place_it(run, workdir, golden):
    """CATCHES: a rewrite that puts the drawing's middle or its origin on the wrong point, turns it the wrong way about
    `at`, or reports extents that don't follow the placing."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", *script(workdir,
                            'import_cad {"path": "plan.dxf", "position": "origin", "at": [1000, 2000]}',
                            'import_cad {"cad": "plan", "position": "centre", "at": [-500, 0]}',
                            'import_cad {"cad": "plan", "position": "center", "at": [0, 0], "angle": 90}',
                            'import_cad {"cad": "plan", "position": "origin", "at": [100, 200], "angle": 30}',
                            'import_cad {"cad": "plan", "units": "cm", "position": "origin", "at": [1000, 2000], "angle": -90}',
                            'elements {"category": "cadimport"}')])
    check_rounded(golden, r, "position_angle.txt")


def test_layers_visible_all_or_a_list(run, workdir, golden):
    """CATCHES: a rewrite that hides the wrong layers for `layers: visible`, `all` or a list of those to show, or keeps
    an element's `hidden` when nothing is."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", *script(workdir,
                            'import_cad {"path": "plan.dxf", "layers": "visible"}',
                            'import_cad {"cad": "plan", "layers": "all"}',
                            'import_cad {"cad": "plan", "layers": ["WALLS"]}',
                            'import_cad {"cad": "plan", "layers": []}',
                            'import_cad {"cad": "plan", "layers": null}',
                            'elements {"category": "cadimport"}')])
    golden.check_run(r, "layers_option.txt")


def test_colors_are_kept_inverted_or_black_in_the_plan(run, workdir, golden):
    """CATCHES: a rewrite that draws an import's colours as they are when asked to invert them (red becomes cyan, white
    becomes black, ink stays ink) or to draw them all in the view's ink, or that names the choice differently in the
    element; "black and white" is black."""
    (workdir / "plan.dxf").write_text(dxf(plan_entities() + pairs(
        (0, "CIRCLE"), (8, "WALLS"), (420, "16777215"), (10, "5"), (20, "3"), (40, "1"),
        (0, "CIRCLE"), (8, "WALLS"), (62, "250"), (10, "5"), (20, "3"), (40, "2"))))
    report = []
    for colors in ["preserve", "invert", "black", "Black and White"]:
        r = run(["run", *script(workdir, 'import_cad ' + json.dumps({"path": "plan.dxf", "colors": colors, "layers": "all"}),
                                'elements {"category": "cadimport"}',
                                'render {"view": "Level 1", "width": 400, "height": 300, "path": "plan.svg"}')])
        report.append(f"### {colors}\n{outcome(r)}--- plan.svg\n{(workdir / 'plan.svg').read_text()}\n")
    golden.check("".join(report), "colors.txt")


# How the drawing is read and shown.
IMPORT_READING_ERRORS = {
    "units_unknown": {"cad": "plan", "units": "furlong"},
    "units_and_scale": {"cad": "plan", "units": "mm", "scale": 2},
    "scale_zero": {"cad": "plan", "scale": 0},
    "scale_too_big": {"cad": "plan", "scale": 1e9},
    "scale_not_a_number": {"cad": "plan", "scale": "big"},
    "colors_unknown": {"cad": "plan", "colors": "pink"},
    "layers_unknown_layer": {"cad": "plan", "layers": ["NOPE"]},
    "layers_not_a_list": {"cad": "plan", "layers": 5},
    "layers_word_unknown": {"cad": "plan", "layers": "some"},
    "layers_list_of_numbers": {"cad": "plan", "layers": [1]},
}

# Which drawing, and under which name.
IMPORT_SOURCE_ERRORS = {
    "link_a_held_drawing": {"cad": "plan", "link": True},
    "link_not_a_flag": {"cad": "plan", "link": "yes"},
    "cad_unknown": {"cad": "nope"},
    "path_and_cad": {"path": "plan.dxf", "cad": "plan"},
    "neither_path_nor_cad": {},
    "same_name_again": {"path": "plan.dxf"},
    "empty_name": {"path": "plan.dxf", "name": "  "},
    "path_not_text": {"path": 5},
}

# Where it goes.
IMPORT_PLACING_ERRORS = {
    "position_unknown": {"cad": "plan", "position": "left"},
    "level_unknown": {"cad": "plan", "level": "Roof"},
    "view_of_another_level": {"cad": "plan", "level": "Level 1", "view": "Level 2"},
    "view_not_a_plan": {"cad": "plan", "view": "{3D}"},
    "at_not_a_point": {"cad": "plan", "at": [1]},
    "angle_not_a_number": {"cad": "plan", "angle": "x"},
    "at_past_the_models_reach": {"cad": "plan", "at": [2e9, 0]},
    "placed_past_the_models_reach": {"cad": "plan", "at": [999999000, 0]},
}


def test_import_cad_refuses_how_it_cant_read_or_show_a_drawing(run, workdir, golden):
    """CATCHES: a rewrite that takes an unknown unit, both `units` and `scale`, a scale out of 1e-6..1e7, an unknown
    colour mode or a layer the drawing lacks, instead of refusing it with the reference's message (the elements after
    are the first import's only)."""
    (workdir / "plan.dxf").write_text(PLAN)
    golden.check(refusals(run, ["--cmd", 'import_cad {"path": "plan.dxf"}'], "import_cad", IMPORT_READING_ERRORS),
                 "import_errors_reading.txt")


def test_import_cad_refuses_a_source_or_name_it_cant_take(run, workdir, golden):
    """CATCHES: a rewrite that links a held drawing, takes `path` and `cad` together or neither, brings a file in twice
    under one name, or takes an empty name or a path that isn't text."""
    (workdir / "plan.dxf").write_text(PLAN)
    golden.check(refusals(run, ["--cmd", 'import_cad {"path": "plan.dxf"}'], "import_cad", IMPORT_SOURCE_ERRORS),
                 "import_errors_source.txt")


def test_import_cad_refuses_a_place_it_cant_take(run, workdir, golden):
    """CATCHES: a rewrite that takes an unknown position, level or view, a view of another level than `level`, a point
    or angle that isn't one, or a place that carries the drawing past the model's reach."""
    (workdir / "plan.dxf").write_text(PLAN)
    golden.check(refusals(run, ["--cmd", 'import_cad {"path": "plan.dxf"}'], "import_cad", IMPORT_PLACING_ERRORS),
                 "import_errors_placing.txt")


def test_the_held_drawings_are_named_when_one_isnt_found(run, workdir, golden):
    """CATCHES: a rewrite that doesn't list the drawings a project holds (or says `none`) when `cad` names another."""
    (workdir / "a.dxf").write_text(PLAN)
    (workdir / "b.dxf").write_text(PLAN)
    r = run(["run", "--cmd", 'import_cad {"cad": "x"}'])
    golden.check_run(r, "unknown_cad_none_held.txt")
    r = run(["run", "--cmd", 'import_cad {"path": "a.dxf"}', "--cmd", 'import_cad {"path": "b.dxf", "name": "second"}',
             "--cmd", 'import_cad {"cad": "x"}'])
    golden.check_run(r, "unknown_cad_two_held.txt")


def test_a_project_holds_at_most_64_drawings(run, workdir, golden):
    """CATCHES: a rewrite with no cap on the CAD drawings a project holds, another cap, or another refusal."""
    (workdir / "plan.dxf").write_text(dxf(line("A", (0, 0), (1, 1))))
    lines = ['import_cad ' + json.dumps({"path": "plan.dxf", "name": f"d{i}"}) for i in range(64)]
    r = run(["run", *script(workdir, *lines), "--cmd", 'import_cad {"cad": "d63"}',
             "--cmd", 'import_cad {"path": "plan.dxf", "name": "d64"}'])
    out = r.stdout.decode().splitlines()
    assert len(out) == 65, out[-3:]
    golden.check(f"exit: {r.returncode}\nlast: {out[-1]}\n--- stderr\n{r.stderr.decode()}", "max_cads.txt")


def test_current_view_only_places_it_in_one_plan(run, workdir, golden):
    """CATCHES: a rewrite that puts an import for one view in every plan of its level, or that doesn't record the view
    (and its level) a plan view names; deleting the view takes the import and its drawing with it."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", *script(workdir,
                            'duplicate_view {"view": "Level 2"}',
                            'import_cad {"path": "plan.dxf", "view": 100002}',
                            'import_cad {"cad": "plan", "view": "Level 1"}',
                            'elements {"category": "cadimport"}',
                            'delete {"ids": [100002]}',
                            'elements {"category": "cadimport"}',
                            'import_cad {"cad": "plan"}')])
    golden.check_run(r, "current_view_only.txt")


# ---------------------------------------------------------------------------
# cad_layers and Visibility/Graphics
# ---------------------------------------------------------------------------

def test_cad_layers_hide_and_show_everywhere_and_in_one_view(run, workdir, golden):
    """CATCHES: a rewrite whose cad_layers doesn't hide and show layers for the element or for one view's graphics, that
    reports `shown_in_view` wrongly, that loses the view's hiding on undo, or whose graphics `layers` differ."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", *script(workdir,
                            'import_cad {"path": "plan.dxf", "position": "origin"}',
                            'cad_layers {"id": 100002}',
                            'cad_layers {"id": 100002, "hide": ["TEXT"], "show": ["FURN"]}',
                            'cad_layers {"id": 100002, "view": "Level 1", "hide": ["WALLS"]}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "hidden.svg"}',
                            'cad_layers {"id": 100002, "view": "Level 1", "show": ["WALLS"], "hide": ["FURN"]}',
                            'undo',
                            'cad_layers {"id": 100002, "view": "Level 1"}',
                            'cad_layers {"id": 100002, "view": "Level 1", "show": ["WALLS"]}',
                            'graphics {"view": "Level 1"}',
                            'undo',
                            'graphics {"view": "Level 1", "layers": {"plan": ["FURN", "TEXT"]}}',
                            'graphics {"view": "Level 1", "layers": {"plan": null}}',
                            'cad_layers {"id": 100002, "view": "Level 1"}',
                            'elements {"category": "cadimport"}')])
    golden.check_run(r, "cad_layers_sequence.txt")
    golden.check((workdir / "hidden.svg").read_text(), "cad_layers_hidden.svg")


CAD_LAYERS_ERRORS = {
    "unknown_layer": {"id": 100002, "hide": ["NOPE"]},
    "hide_and_show": {"id": 100002, "hide": ["FURN"], "show": ["FURN"]},
    "hide_not_a_list": {"id": 100002, "hide": "WALLS"},
    "layer_not_a_name": {"id": 100002, "show": [1]},
    "not_a_cad_import": {"id": 100000},
    "no_such_element": {"id": 999999},
    "id_not_an_id": {"id": "abc"},
    "no_id": {},
    "unknown_view": {"id": 100002, "view": "Nope", "hide": ["WALLS"]},
}


def test_cad_layers_refuses_what_it_cant_do(run, workdir, golden):
    """CATCHES: a rewrite whose cad_layers takes an unknown layer, a layer both hidden and shown, a list that isn't one,
    an unknown view, or an element that is no CAD import, or refuses them with other words."""
    (workdir / "plan.dxf").write_text(PLAN)
    golden.check(refusals(run, ["--cmd", 'import_cad {"path": "plan.dxf"}'], "cad_layers", CAD_LAYERS_ERRORS),
                 "cad_layers_errors.txt")


def test_an_unknown_layer_names_the_first_twenty_of_many(run, workdir, golden):
    """CATCHES: a rewrite that lists every layer of a drawing with many in its refusal, or none, instead of the first
    twenty and an ellipsis."""
    layers = [(f"L{i:02}", "1", False) for i in range(25)]
    (workdir / "many.dxf").write_text(dxf("".join(line(f"L{i:02}", (i, 0), (i, 1)) for i in range(25)), layers=layers))
    r = run(["run", "--cmd", 'import_cad {"path": "many.dxf"}', "--cmd", 'cad_layers {"id": 100002, "show": ["X"]}'])
    golden.check_run(r, "unknown_layer_of_many.txt")


def test_graphics_layers_refuses_unknown_drawings_and_layers(run, workdir, golden):
    """CATCHES: a rewrite whose Visibility/Graphics `layers` takes a drawing the project doesn't hold or a layer it
    doesn't have, or a value of the wrong shape."""
    (workdir / "plan.dxf").write_text(PLAN)
    out = []
    for layers in [{"plan": ["NOPE"]}, {"other": ["WALLS"]}, {"plan": [5]}, 5]:
        r = run(["run", "--cmd", 'import_cad {"path": "plan.dxf"}', "--cmd",
                 "graphics " + json.dumps({"view": "Level 1", "layers": layers})])
        out.append(f"{json.dumps(layers)} -> exit {r.returncode}: {r.stderr.decode()}")
    golden.check("".join(out), "graphics_layers_errors.txt")


def test_the_imported_category_hidden_in_a_view(run, workdir, golden):
    """CATCHES: a rewrite whose Visibility/Graphics can't hide the `cadimport` category in a plan (Imported Categories),
    or halftones it differently."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", *script(workdir,
                            'import_cad {"path": "plan.dxf"}',
                            'graphics {"view": "Level 1", "categories": {"cadimport": {"halftone": true}}}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "half.svg"}',
                            'graphics {"view": "Level 1", "hide": ["cadimport"]}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "none.svg"}')])
    assert r.returncode == 0, r.stderr
    golden.check((workdir / "half.svg").read_text(), "category_halftone.svg")
    golden.check((workdir / "none.svg").read_text(), "category_hidden.svg")


# ---------------------------------------------------------------------------
# cad_query
# ---------------------------------------------------------------------------

QUERY_DXF = dxf(
    plan_entities() + pairs(
        (0, "CIRCLE"), (8, "COLS"), (10, "20"), (20, "3"), (40, "0.5"),
        (0, "ARC"), (8, "COLS"), (62, "4"), (10, "20"), (20, "10"), (40, "1"), (50, "0"), (51, "90"),
        (0, "POINT"), (8, "PTS"), (10, "30"), (20, "0"),
        (0, "LWPOLYLINE"), (8, "WALLS"), (6, "DASHED"), (90, "3"), (70, "0"), (10, "30"), (20, "5"), (10, "32"), (20, "5"),
        (10, "32"), (20, "7"),
        (0, "SOLID"), (8, "FILL"), (62, "5"), (10, "40"), (20, "0"), (11, "42"), (21, "0"), (12, "40"), (22, "2"), (13, "42"),
        (23, "2"),
    ),
    tables=pairs((0, "TABLE"), (2, "LTYPE"), (0, "LTYPE"), (2, "DASHED"), (49, "0.5"), (49, "-0.25"), (0, "ENDTAB")),
)

QUERIES = [
    {"at": [5000, 30]},
    {"at": [1500, 1000], "reach": 50},
    {"at": [1500, 1000]},
    {"at": [1000, 5000]},
    {"at": [20000, 3550]},
    {"at": [20600, 10600], "reach": 300},
    {"at": [30000, 40]},
    {"at": [31000, 5020]},
    {"at": [41000, 1000]},
    {"at": [41000, 1000], "reach": 0.5},
    {"at": [42100, 1000], "reach": 200},
    {"at": [60000, 60000]},
    {"at": [5000, 3000], "reach": 3500},
]


def test_query_names_the_entity_nearest_a_point(run, workdir, golden):
    """CATCHES: a rewrite whose Query finds another entity than the nearest one shown, measures its distance in other
    units than mm, finds an entity of a hidden layer, doesn't treat the inside of a fill as on it, or names kinds,
    colours or linetypes differently."""
    (workdir / "q.dxf").write_text(QUERY_DXF)
    lines = ['import_cad {"path": "q.dxf", "position": "origin"}']
    lines += ["cad_query " + json.dumps({"id": 100002, **q}) for q in QUERIES]
    golden.check_run(run(["run", *script(workdir, *lines)]), "query.txt")


def test_query_follows_the_imports_placing(run, workdir, golden):
    """CATCHES: a rewrite whose Query looks at the drawing's own coordinates instead of where the import is placed,
    turned and scaled, or measures the distance in drawing units."""
    (workdir / "q.dxf").write_text(QUERY_DXF)
    lines = ['import_cad {"path": "q.dxf", "position": "origin", "at": [1000, 1000], "angle": 90, "units": "cm"}',
             'cad_query {"id": 100002, "at": [1000, 1050]}',
             'cad_query {"id": 100002, "at": [1020, 1050]}',
             'cad_query {"id": 100002, "at": [930, 1200]}']
    check_rounded(golden, run(["run", *script(workdir, *lines)]), "query_placed.txt")


QUERY_ERRORS = {
    "reach_zero": {"id": 100002, "at": [0, 0], "reach": 0},
    "reach_negative": {"id": 100002, "at": [0, 0], "reach": -5},
    "no_at": {"id": 100002},
    "not_a_cad_import": {"id": 100000, "at": [0, 0]},
    "no_such_element": {"id": 999, "at": [0, 0]},
    "no_id": {"at": [0, 0]},
}


def test_query_refuses_what_it_cant_do(run, workdir, golden):
    """CATCHES: a rewrite whose Query takes a reach of nothing, no point, or an element that is no import."""
    (workdir / "plan.dxf").write_text(PLAN)
    golden.check(refusals(run, ["--cmd", 'import_cad {"path": "plan.dxf"}'], "cad_query", QUERY_ERRORS), "query_errors.txt")


# ---------------------------------------------------------------------------
# Linked drawings
# ---------------------------------------------------------------------------

def test_reload_cad_reads_a_linked_file_again(run, workdir, golden):
    """CATCHES: a rewrite whose reload_cad doesn't notice a change (or reports one when there's none), can't be undone,
    reloads a drawing that isn't linked, or refuses with other words; a link is read beside the project once it's saved
    elsewhere."""
    (workdir / "plan.dxf").write_text(PLAN)
    (workdir / "other.dxf").write_text(PLAN)
    (workdir / "sub").mkdir()
    (workdir / "sub" / "plan.dxf").write_text(dxf(plan_entities() + line("WALLS", (0, 0), (10, 6))))
    (workdir / "script.txt").write_text("\n".join([
        'import_cad {"path": "plan.dxf", "link": true}',
        'reload_cad {"cad": "plan"}',
        'elements {"category": "cadimport"}',
        'import_cad {"path": "other.dxf"}',
    ]) + "\n")
    (workdir / "after.txt").write_text("\n".join([
        'reload_cad {"cad": "plan"}',
        'elements {"category": "cadimport"}',
        'undo',
        'elements {"category": "cadimport"}',
    ]) + "\n")
    r = run(["run", "--script", "script.txt", "--save", "sub/p.bimcraft", "--script", "after.txt"])
    golden.check_run(r, "reload_cad.txt")
    out = []
    for p in [{"cad": "other"}, {"cad": "nope"}, {}, {"cad": 5}]:
        r = run(["run", "sub/p.bimcraft", "--cmd", "reload_cad " + json.dumps(p)])
        out.append(f"{json.dumps(p)} -> exit {r.returncode}: {r.stderr.decode()}")
    golden.check("".join(out), "reload_cad_errors.txt")


def test_opening_a_project_reads_its_linked_drawings_again(run, workdir, golden):
    """CATCHES: a rewrite that opens a project with the drawing it saved instead of the linked file's new content, or
    that fails to open (rather than keeping what it holds and naming the drawing in `cads_not_reloaded`) when the file
    is gone or no longer a drawing."""
    (workdir / "plan.dxf").write_text(PLAN)
    assert run(["run", "--cmd", 'import_cad {"path": "plan.dxf", "link": true}', "--save", "p.bimcraft"]).returncode == 0
    (workdir / "plan.dxf").write_text(dxf(plan_entities() + line("WALLS", (0, 0), (10, 6))))
    r1 = run(["run", "--cmd", 'open {"path": "p.bimcraft"}', "--cmd", 'elements {"category": "cadimport"}'])
    (workdir / "plan.dxf").write_text("0\nSECTION\n2\nENTITIES\nbroken\n")
    r2 = run(["run", "--cmd", 'open {"path": "p.bimcraft"}', "--cmd", 'elements {"category": "cadimport"}'])
    (workdir / "plan.dxf").unlink()
    r3 = run(["run", "p.bimcraft", "--cmd", 'reload_cad {"cad": "plan"}'])
    golden.check_run(r1, "open_rereads.txt")
    golden.check_run(r2, "open_broken_link.txt")
    golden.check_run(r3, "open_missing_link.txt")


# ---------------------------------------------------------------------------
# Editing an import, and the project file
# ---------------------------------------------------------------------------

def test_an_import_moves_turns_copies_is_modified_and_refuses_to_mirror(run, workdir, golden):
    """CATCHES: a rewrite whose move, rotate, copy or modify of an import changes other fields than the reference's, that
    mirrors a drawing (its text would read backwards), or that keeps a drawing nothing places after a delete; undo
    brings it back."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", *script(workdir,
                            'import_cad {"path": "plan.dxf"}',
                            'move {"ids": [100002], "by": [100, 200]}',
                            'rotate {"ids": [100002], "about": [100, 200], "angle": 90}',
                            'copy {"ids": [100002], "by": [20000, 0]}',
                            'modify {"id": 100002, "colors": "invert", "scale": 500, "level": "Level 2", "at": [1, 2], "angle": 45}',
                            'elements {"category": "cadimport"}',
                            'delete {"ids": [100002, 100003]}',
                            'elements {"category": "cadimport"}',
                            'undo',
                            'elements {"category": "cadimport"}'),
             "--cmd", 'mirror {"ids": [100002], "axis": [[0, 0], [0, 1000]]}'])
    check_rounded(golden, r, "edit_import.txt")


MODIFY_ERRORS = {
    "colors": {"id": 100002, "colors": "pink"},
    "scale": {"id": 100002, "scale": 0},
    "level": {"id": 100002, "level": "Roof"},
    "cad": {"id": 100002, "cad": "nope"},
}


def test_modify_of_an_import_is_checked(run, workdir, golden):
    """CATCHES: a rewrite whose modify lets an import hold an unknown colour mode, a scale out of range, a level or a
    drawing the project doesn't have."""
    (workdir / "plan.dxf").write_text(PLAN)
    golden.check(refusals(run, ["--cmd", 'import_cad {"path": "plan.dxf"}'], "modify", MODIFY_ERRORS), "modify_errors.txt")


def _held(project_text):
    """What a project file holds of its drawings and imports: each drawing's DXF unpacked (so the test doesn't depend on
    how it was compressed), the levels and import elements, and the library entries of the drawings."""
    p = json.loads(project_text)
    cads = {}
    for key, cad in p["cads"].items():
        cad = dict(cad)
        cad["dxf"] = zlib.decompress(base64.b64decode(cad["dxf"])).decode("utf-8")
        cads[key] = cad
    imports = {k: e for k, e in p["elements"].items() if e.get("category") in ("level", "cadimport")}
    library = {k: e for k, e in p["library"].items() if e.get("kind") == "cad"}
    return normalize(json.dumps({"format": p["format"], "cads": cads, "imports": imports, "library": library}, indent=1))


def test_a_drawing_is_saved_with_the_project_and_opens_as_it_was(run, workdir, golden):
    """CATCHES: a rewrite whose project file doesn't hold the drawing's own DXF bytes (and its source and link) or the
    import's fields, or that opens it differently; Insert from File brings the drawing with its import."""
    (workdir / "plan.dxf").write_text(PLAN)
    r = run(["run", "--cmd", 'import_cad {"path": "plan.dxf", "link": true, "angle": 30, "at": [100, 200], "colors": "invert"}',
             "--cmd", 'import_cad {"cad": "plan", "view": "Level 2", "layers": "all", "scale": 2}',
             "--cmd", 'cad_layers {"id": 100002, "view": "Level 1", "hide": ["WALLS"]}', "--save", "p.bimcraft"])
    assert r.returncode == 0, r.stderr
    golden.check(_held((workdir / "p.bimcraft").read_text()), "saved_project.json")
    r = run(["run", "p.bimcraft", "--cmd", 'elements {"category": "cadimport"}', "--cmd", 'cad_layers {"id": 100002, "view": "Level 1"}'])
    check_rounded(golden, r, "saved_project_opened.txt")
    r = run(["run", "--cmd", 'insert {"path": "p.bimcraft", "ids": [100003]}', "--cmd", 'elements {"category": "cadimport"}'])
    check_rounded(golden, r, "saved_project_inserted.txt")


def test_a_damaged_drawing_in_a_project_file_is_refused(run, workdir, golden):
    """CATCHES: a rewrite that opens a project whose drawing data isn't base64, isn't zlib, or isn't a DXF, or that
    holds more than 64 drawings, or that doesn't say whose data is wrong."""
    (workdir / "plan.dxf").write_text(PLAN)
    assert run(["run", "--cmd", 'import_cad {"path": "plan.dxf"}', "--save", "p.bimcraft"]).returncode == 0
    good = json.loads((workdir / "p.bimcraft").read_text())
    out = []
    for name, data in [("not_base64", "!!!"), ("not_zlib", base64.b64encode(b"hello").decode()),
                       ("not_dxf", base64.b64encode(zlib.compress(b"0\nEOF\n")).decode())]:
        bad = json.loads(json.dumps(good))
        bad["cads"]["plan"]["dxf"] = data
        (workdir / f"{name}.bimcraft").write_text(json.dumps(bad))
        r = run(["run", f"{name}.bimcraft"])
        out.append(f"{name}: exit {r.returncode}: {r.stderr.decode()}")
    for name, value in [("cads_not_a_map", []), ("cads_null", None)]:
        bad = json.loads(json.dumps(good))
        bad["cads"] = value
        (workdir / f"{name}.bimcraft").write_text(json.dumps(bad))
        r = run(["run", f"{name}.bimcraft"])
        out.append(f"{name}: exit {r.returncode}: {r.stderr.decode()}")
    many = json.loads(json.dumps(good))
    for i in range(64):
        many["cads"][f"copy {i}"] = good["cads"]["plan"]
    (workdir / "many.bimcraft").write_text(json.dumps(many))
    r = run(["run", "many.bimcraft"])
    out.append(f"many: exit {r.returncode}: {r.stderr.decode()}")
    golden.check("".join(out), "damaged_drawing.txt")


# ---------------------------------------------------------------------------
# DWG, read by the program's own child process
# ---------------------------------------------------------------------------

def test_a_dwg_comes_in_as_the_drawing_it_holds(run, workdir, golden):
    """CATCHES: a rewrite that can't read a DWG (an AutoCAD 2004 file, written here by an open-source library from DXF)
    or reads its unit, layers, colours or entities differently from the DXF it was written from."""
    (workdir / "room.dwg").write_bytes((resources_for(__file__) / "room.dwg").read_bytes())
    r = run(["run", *script(workdir,
                            'import_cad {"path": "room.dwg", "layers": "all", "position": "origin"}',
                            'cad_layers {"id": 100002}',
                            'cad_query {"id": 100002, "at": [5000, 3150]}',
                            'cad_query {"id": 100002, "at": [10020, 3000]}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "room.svg"}')])
    golden.check_run(r, "dwg_room.txt")
    golden.check((workdir / "room.svg").read_text(), "dwg_room.svg")


def test_a_file_named_dwg_that_isnt_one_says_so(run, workdir, golden):
    """CATCHES: a rewrite that reads anything named .dwg as a drawing, or refuses it without the file's name and the
    reason (a DWG begins with its version)."""
    (workdir / "bad.dwg").write_bytes(b"  0\nSECTION\n")
    golden.check_run(run(["run", "--cmd", 'import_cad {"path": "bad.dwg"}']), "dwg_not_a_dwg.txt")


def test_a_damaged_dwg_is_refused_without_a_crash(run, workdir):
    """CATCHES: a rewrite that crashes (or takes the whole program down) on a damaged DWG (its version and nothing
    readable, or a real one cut short), or that takes it, instead of refusing it as a DWG that couldn't be read. The
    decoder's own words after that are not compared."""
    room = (resources_for(__file__) / "room.dwg").read_bytes()
    for data in [b"AC1032 this is not a dwg file at all", room[:200]]:
        (workdir / "bad.dwg").write_bytes(data)
        r = run(["run", "--cmd", 'import_cad {"path": "bad.dwg"}', "--cmd", 'elements {"category": "cadimport"}'])
        assert (r.returncode, r.stdout) == (1, b"")
        assert r.stderr.decode().startswith("line 1 (import_cad): import_cad: bad.dwg: the DWG couldn't be read: "), r.stderr
