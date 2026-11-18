"""The DXF reader behind `import_cad`: header units, layers and linetypes, every entity kind it draws, blocks placed by
INSERT, what it leaves out, and why a file it can't read is refused.

Each drawing is written here as DXF text; what came in is seen in `import_cad`'s reply, `cad_layers`, `cad_query` and the
plan the drawing is drawn in (an SVG, whose coordinates are the drawing's, scaled to the view)."""

import json
import re

import pytest
from conftest import normalize

# A number computed through sines and cosines may differ in its last digits between machines: those of a reply are
# compared to six decimals.
LONG_FLOAT = re.compile(r"-?\d+\.\d{7,}")


def outcome(r):
    """A run as `golden.check_run` shows it: its exit code, then its normalised output and errors."""
    return f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{normalize(r.stderr.decode())}"


def check_rounded(golden, r, name):
    """`golden.check_run`, with the long decimals of the output rounded to six places."""
    out = LONG_FLOAT.sub(lambda m: repr(round(float(m.group(0)), 6)), r.stdout.decode())
    golden.check(f"exit: {r.returncode}\n--- stdout\n{normalize(out)}--- stderr\n{normalize(r.stderr.decode())}", name)


def pairs(*items):
    """Group codes and values as a DXF writes them: a code line, then its value line."""
    return "".join(f"{c}\n{v}\n" for c, v in items)


def section(name, body):
    return pairs((0, "SECTION"), (2, name)) + body + pairs((0, "ENDSEC"))


def layer_table(*layers):
    """A LAYER table: each layer is (name, colour code 62, more pairs...)."""
    body = pairs((0, "TABLE"), (2, "LAYER"))
    for name, color, *more in layers:
        body += pairs((0, "LAYER"), (2, name), (70, "0"), (62, color), (6, "Continuous"), *more)
    return body + pairs((0, "ENDTAB"))


def ltype_table(*types):
    """An LTYPE table: each linetype is (name, [dash, gap, ...])."""
    body = pairs((0, "TABLE"), (2, "LTYPE"))
    for name, dashes in types:
        body += pairs((0, "LTYPE"), (2, name), *[(49, d) for d in dashes])
    return body + pairs((0, "ENDTAB"))


def dxf(entities, header=(), tables="", blocks=""):
    """A whole ASCII DXF: a header of (name, code, value) variables, tables, blocks and model space's entities."""
    head = "".join(pairs((9, name), (code, value)) for name, code, value in header)
    text = section("HEADER", head)
    if tables:
        text += section("TABLES", tables)
    if blocks:
        text += section("BLOCKS", blocks)
    return text + section("ENTITIES", entities) + pairs((0, "EOF"))


def line(a, b, layer="0", *more):
    return pairs((0, "LINE"), (8, layer), *more, (10, a[0]), (20, a[1]), (11, b[0]), (21, b[1]))


def block(name, entities, base=(0, 0)):
    return pairs((0, "BLOCK"), (2, name), (10, base[0]), (20, base[1])) + entities + pairs((0, "ENDBLK"))


MM = [("$INSUNITS", 70, "4")]


def import_and_draw(run, workdir, text, extra_cmds=(), import_params=None, size=(400, 300), name="drawing.dxf"):
    """Writes the DXF, imports it by its origin, runs more commands, and renders Level 1's plan to plan.svg."""
    (workdir / name).write_text(text)
    params = {"path": name, "position": "origin", "layers": "all", **(import_params or {})}
    lines = ["import_cad " + json.dumps(params), *extra_cmds,
             'render ' + json.dumps({"view": "Level 1", "width": size[0], "height": size[1], "path": "plan.svg"})]
    (workdir / "script.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "script.txt"])


# ---------------------------------------------------------------------------
# Units from the header
# ---------------------------------------------------------------------------

UNIT_CODES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "13", "14", "15", "16", "18", "19", "20", "21",
              "99"]


def test_insunits_says_the_drawings_unit_and_scale(run, workdir, golden):
    """CATCHES: a rewrite that maps $INSUNITS codes to the wrong unit name or millimetre factor (inches, feet, metres,
    US survey feet, decimetres...), that reads a unitless or astronomical file as anything but mm, that labels the unit
    it read without saying the file had none, or that places a drawing at a scale below 1e-6 (angstroms)."""
    lines = []
    for code in UNIT_CODES:
        (workdir / f"u{code}.dxf").write_text(dxf(line((0, 0), (2, 1)), header=[("$INSUNITS", 70, code)]))
        lines.append("import_cad " + json.dumps({"path": f"u{code}.dxf", "position": "origin"}))
    # No header at all, and a header whose $INSUNITS isn't a whole number.
    (workdir / "nohead.dxf").write_text(section("ENTITIES", line((0, 0), (2, 1))) + pairs((0, "EOF")))
    (workdir / "frac.dxf").write_text(dxf(line((0, 0), (2, 1)), header=[("$INSUNITS", 70, "6.7")]))
    lines += ['import_cad {"path": "nohead.dxf", "position": "origin"}', 'import_cad {"path": "frac.dxf", "position": "origin"}']
    (workdir / "script.txt").write_text("\n".join(lines) + "\n")
    # Angstroms make a scale below the 1e-6 mm an import may have: refused, after the rest came in.
    (workdir / "u11.dxf").write_text(dxf(line((0, 0), (2, 1)), header=[("$INSUNITS", 70, "11")]))
    golden.check_run(run(["run", "--script", "script.txt", "--cmd", 'import_cad {"path": "u11.dxf", "position": "origin"}']),
                     "insunits.txt")


def test_units_given_override_the_files(run, workdir, golden):
    """CATCHES: a rewrite whose `units`, `scale` and `auto` don't override (or keep) the file's unit as the reference
    does, or that words the unit it read in differently ("cm (its file says m)", "a scale of its own ...")."""
    (workdir / "m.dxf").write_text(dxf(line((0, 0), (2, 1)), header=[("$INSUNITS", 70, "6")]))
    (workdir / "none.dxf").write_text(dxf(line((0, 0), (2, 1))))
    cmds = [
        'import_cad {"path": "m.dxf", "units": "auto", "position": "origin"}',
        'import_cad {"cad": "m", "units": "mm", "position": "origin"}',
        'import_cad {"cad": "m", "units": "cm", "position": "origin"}',
        'import_cad {"cad": "m", "units": "in", "position": "origin"}',
        'import_cad {"cad": "m", "units": "ft", "position": "origin"}',
        'import_cad {"cad": "m", "units": "M", "position": "origin"}',
        'import_cad {"cad": "m", "scale": 2.5, "position": "origin"}',
        'import_cad {"path": "none.dxf", "position": "origin"}',
        'import_cad {"cad": "none", "units": "m", "position": "origin"}',
        'import_cad {"cad": "none", "scale": 0.001, "position": "origin"}',
    ]
    (workdir / "script.txt").write_text("\n".join(cmds) + "\n")
    golden.check_run(run(["run", "--script", "script.txt"]), "units_given.txt")


# ---------------------------------------------------------------------------
# Layers, colours and linetypes
# ---------------------------------------------------------------------------

def test_layer_table_colours_off_frozen_and_true_colour(run, workdir, golden):
    """CATCHES: a rewrite that reads layer colours wrongly (the 255-colour index, true colour 420 over 62, index 7 as
    the view's ink), that doesn't take a negative colour as off or flag 1 as frozen, that keeps an off or frozen layer
    shown under `layers: visible`, or that fails to add a layer an entity names but the table doesn't."""
    tables = layer_table(
        ("RED", "1"), ("YEL", "2"), ("GRN", "3"), ("CYA", "4"), ("BLU", "5"), ("MAG", "6"), ("INK", "7"),
        ("GREY8", "8"), ("GREY9", "9"), ("HUE10", "10"), ("HUE11", "11"), ("HUE23", "23"), ("HUE45", "45"),
        ("HUE50", "50"), ("HUE97", "97"), ("HUE138", "138"), ("HUE179", "179"), ("HUE249", "249"), ("G250", "250"), ("G251", "251"), ("G255", "255"),
        ("TRUE", "1", (420, "1193046")), ("OFF", "-5"), ("BYBLOCK", "0"), ("BYLAYER", "256"),
    ) + pairs((0, "TABLE"), (2, "LAYER"), (0, "LAYER"), (2, "FROZEN"), (70, "1"), (62, "3"), (0, "LAYER"), (2, "NOCOLOUR"),
              (0, "LAYER"), (6, ""), (0, "ENDTAB"))
    names = ["RED", "OFF", "FROZEN", "NOCOLOUR", "0", "STRAY"]
    entities = "".join(line((i, 0), (i, 1), n) for i, n in enumerate(names))
    (workdir / "layers.dxf").write_text(dxf(entities, header=MM, tables=tables))
    cmds = ['import_cad {"path": "layers.dxf"}', 'cad_layers {"id": 100002}', 'elements {"category": "cadimport"}']
    (workdir / "script.txt").write_text("\n".join(cmds) + "\n")
    golden.check_run(run(["run", "--script", "script.txt"]), "layer_table.txt")


def test_entity_colours_linetypes_and_weights_seen_by_query(run, workdir, golden):
    """CATCHES: a rewrite whose Query reports an entity's colour (its own index or true colour, its layer's when by
    layer), linetype (its own, else its layer's; BYLAYER means the layer's) or line weight (hundredths of mm) wrongly."""
    tables = layer_table(("WALLS", "1", (370, "50")), ("DASH", "5")) + ltype_table(("HIDDEN", ["6", "-3"]))
    tables = tables.replace("2\nDASH\n70\n0\n62\n5\n6\nContinuous\n", "2\nDASH\n70\n0\n62\n5\n6\nHIDDEN\n")
    entities = (
        line((0, 0), (1000, 0), "WALLS")
        + line((0, 1000), (1000, 1000), "WALLS", (62, "3"), (370, "35"))
        + line((0, 2000), (1000, 2000), "WALLS", (420, "16744448"), (6, "HIDDEN"))
        + line((0, 3000), (1000, 3000), "DASH", (6, "BYLAYER"))
        + line((0, 4000), (1000, 4000), "DASH", (62, "-2"), (370, "-1"))
    )
    (workdir / "q.dxf").write_text(dxf(entities, header=MM, tables=tables))
    cmds = ['import_cad {"path": "q.dxf", "position": "origin"}']
    cmds += ['cad_query ' + json.dumps({"id": 100002, "at": [500, y + 10]}) for y in (0, 1000, 2000, 3000, 4000)]
    (workdir / "script.txt").write_text("\n".join(cmds) + "\n")
    golden.check_run(run(["run", "--script", "script.txt"]), "query_styles.txt")


def test_dashed_linetype_and_ltscale_draw_dashes(run, workdir, golden):
    """CATCHES: a rewrite that draws a linetype's dashes without $LTSCALE, takes the dash or the gap from the wrong
    entries, draws a dotted type (a 0 dash) as solid, or loses the line weights' pens."""
    tables = ltype_table(("DASHED", ["200", "-100"]), ("DOT", ["0", "-80"]), ("CENTER", ["300", "-50", "60", "-50"]))
    tables += layer_table(("THICK", "5", (370, "70")))
    entities = (
        line((0, 0), (4000, 0), "0", (6, "DASHED"))
        + line((0, 1000), (4000, 1000), "0", (6, "dot"))
        + line((0, 2000), (4000, 2000), "THICK", (6, "CENTER"))
        + line((0, 3000), (4000, 3000), "THICK")
    )
    text = dxf(entities, header=MM + [("$LTSCALE", 40, "2")], tables=tables)
    r = import_and_draw(run, workdir, text)
    golden.check_run(r, "dashes.txt")
    golden.check((workdir / "plan.svg").read_text(), "dashes.svg")


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

ENTITIES = {
    "lwpolyline_bulges": pairs(
        (0, "LWPOLYLINE"), (8, "0"), (90, "4"), (70, "1"),
        (10, "0"), (20, "0"), (42, "0.5"), (10, "2000"), (20, "0"), (10, "2000"), (20, "1000"), (42, "-1"),
        (10, "0"), (20, "1000"),
    ) + pairs((0, "LWPOLYLINE"), (8, "0"), (90, "3"), (70, "0"), (10, "3000"), (20, "0"), (10, "4000"), (20, "500"),
              (42, "1"), (10, "4000"), (20, "1500")),
    "polyline_vertices": pairs(
        (0, "POLYLINE"), (8, "0"), (66, "1"), (70, "1"),
        (0, "VERTEX"), (8, "0"), (10, "0"), (20, "0"), (42, "0.3"),
        (0, "VERTEX"), (8, "0"), (10, "1500"), (20, "0"),
        (0, "VERTEX"), (8, "0"), (10, "1500"), (20, "1500"),
        (0, "VERTEX"), (8, "0"), (42, "0.5"),
        (0, "SEQEND"), (8, "0"),
        # A spline-fit polyline: its frame's control points (flag 16) are not drawn.
        (0, "POLYLINE"), (8, "0"), (70, "4"),
        (0, "VERTEX"), (10, "2000"), (20, "0"), (70, "16"),
        (0, "VERTEX"), (10, "2500"), (20, "1000"), (70, "8"),
        (0, "VERTEX"), (10, "3000"), (20, "0"), (70, "8"),
        (0, "SEQEND"),
        # A polygon mesh is left out.
        (0, "POLYLINE"), (8, "0"), (70, "16"),
        (0, "VERTEX"), (10, "0"), (20, "0"), (0, "VERTEX"), (10, "1"), (20, "1"), (0, "SEQEND"),
    ),
    "circle_arc_ellipse": pairs(
        (0, "CIRCLE"), (8, "0"), (10, "1000"), (20, "1000"), (40, "500"),
        (0, "ARC"), (8, "0"), (10, "3000"), (20, "1000"), (40, "600"), (50, "45"), (51, "200"),
        (0, "ARC"), (8, "0"), (10, "3000"), (20, "3000"), (40, "400"), (50, "300"), (51, "60"),
        (0, "ELLIPSE"), (8, "0"), (10, "5000"), (20, "1000"), (11, "800"), (21, "0"), (40, "0.5"),
        (0, "ELLIPSE"), (8, "0"), (10, "5000"), (20, "3000"), (11, "0"), (21, "700"), (40, "0.4"), (41, "0"), (42, "3.14159265"),
        (0, "CIRCLE"), (8, "0"), (10, "0"), (20, "0"), (40, "0"),
        (0, "ARC"), (8, "0"), (10, "1000"), (20, "3000"), (40, "300"), (50, "30"), (51, "30"),
        (0, "ARC"), (8, "0"), (10, "0"), (20, "0"), (40, "0"), (50, "0"), (51, "90"),
    ),
    "splines": pairs(
        # Control points and a clamped knot vector, degree 3.
        (0, "SPLINE"), (8, "0"), (70, "8"), (71, "3"), (72, "8"), (73, "4"),
        (40, "0"), (40, "0"), (40, "0"), (40, "0"), (40, "1"), (40, "1"), (40, "1"), (40, "1"),
        (10, "0"), (20, "0"), (10, "1000"), (20, "2000"), (10, "2000"), (20, "-1000"), (10, "3000"), (20, "1000"),
        # Rational: weights at 41.
        (0, "SPLINE"), (8, "0"), (70, "12"), (71, "2"),
        (40, "0"), (40, "0"), (40, "0"), (40, "1"), (40, "1"), (40, "1"),
        (10, "0"), (20, "2000"), (41, "1"), (10, "1000"), (20, "3000"), (41, "0.5"), (10, "2000"), (20, "2000"), (41, "1"),
        # Five control points over interior knots.
        (0, "SPLINE"), (8, "0"), (70, "8"), (71, "3"),
        (40, "0"), (40, "0"), (40, "0"), (40, "0"), (40, "0.5"), (40, "1"), (40, "1"), (40, "1"), (40, "1"),
        (10, "0"), (20, "-1000"), (10, "1000"), (20, "-2000"), (10, "2000"), (20, "-1000"), (10, "3000"), (20, "-2000"),
        (10, "4000"), (20, "-1000"),
        # Fit points only.
        (0, "SPLINE"), (8, "0"), (70, "0"), (71, "3"),
        (11, "4000"), (21, "0"), (11, "4500"), (21, "800"), (11, "5000"), (21, "0"),
    ),
    "points_solids_traces": pairs(
        (0, "POINT"), (8, "0"), (10, "100"), (20, "100"),
        (0, "SOLID"), (8, "0"), (62, "1"), (10, "0"), (20, "500"), (11, "1000"), (21, "500"), (12, "0"), (22, "1500"),
        (13, "1000"), (23, "1500"),
        (0, "SOLID"), (8, "0"), (62, "3"), (10, "1500"), (20, "500"), (11, "2500"), (21, "500"), (12, "2000"), (22, "1500"),
        (13, "2000"), (23, "1500"),
        (0, "TRACE"), (8, "0"), (62, "5"), (10, "3000"), (20, "500"), (11, "4000"), (21, "500"), (12, "3000"), (22, "700"),
        (13, "4000"), (23, "700"),
    ),
    "hatches": pairs(
        # A solid hatch of a polyline boundary with a bulge.
        (0, "HATCH"), (8, "0"), (62, "1"), (2, "SOLID"), (70, "1"), (71, "0"), (91, "1"),
        (92, "2"), (72, "1"), (73, "1"), (93, "3"), (10, "0"), (20, "0"), (42, "0"), (10, "1000"), (20, "0"), (42, "0.4"),
        (10, "1000"), (20, "1000"), (42, "0"), (97, "0"),
        (75, "0"), (76, "1"), (98, "0"),
        # A patterned hatch of edges: a line, an arc, an elliptic arc and a spline, and a second, square path.
        (0, "HATCH"), (8, "0"), (62, "5"), (2, "ANSI31"), (70, "0"), (71, "0"), (91, "2"),
        (92, "1"), (93, "4"),
        (72, "1"), (10, "2000"), (20, "0"), (11, "3000"), (21, "0"),
        (72, "2"), (10, "3000"), (20, "500"), (40, "500"), (50, "270"), (51, "90"), (73, "1"),
        (72, "3"), (10, "2500"), (20, "1000"), (11, "500"), (21, "0"), (40, "0.5"), (50, "0"), (51, "180"), (73, "1"),
        (72, "4"), (94, "1"), (73, "0"), (74, "0"), (95, "4"), (96, "2"), (40, "0"), (40, "0"), (40, "1"), (40, "1"),
        (10, "2000"), (20, "1000"), (10, "2000"), (20, "0"),
        (97, "0"),
        (92, "1"), (93, "4"),
        (72, "1"), (10, "4000"), (20, "0"), (11, "5000"), (21, "0"),
        (72, "1"), (10, "5000"), (20, "0"), (11, "5000"), (21, "1000"),
        (72, "1"), (10, "5000"), (20, "1000"), (11, "4000"), (21, "1000"),
        (72, "2"), (10, "4000"), (20, "500"), (40, "500"), (50, "90"), (51, "270"), (73, "0"),
        (97, "0"),
        (75, "0"), (76, "1"), (52, "45"), (41, "1"), (77, "0"), (78, "1"), (98, "0"),
        # Edges by fit points, a clockwise elliptic arc, then an edge of a kind a hatch doesn't have, which ends the
        # path; a path of two points is no ring.
        (0, "HATCH"), (8, "0"), (62, "3"), (2, "SOLID"), (70, "1"), (71, "0"), (91, "2"),
        (92, "1"), (93, "3"),
        (72, "4"), (94, "3"), (73, "0"), (74, "0"), (95, "0"), (96, "0"), (97, "3"),
        (11, "0"), (21, "2000"), (11, "500"), (21, "2600"), (11, "1000"), (21, "2000"),
        (72, "3"), (10, "500"), (20, "2000"), (11, "500"), (21, "0"), (40, "0.6"), (50, "0"), (51, "180"), (73, "0"),
        (72, "9"),
        (97, "0"),
        (92, "2"), (72, "0"), (73, "1"), (93, "2"), (10, "0"), (20, "0"), (10, "1"), (20, "1"),
        (97, "0"),
        # Paths whose edges stop short: a line, then an arc, then an ellipse of no ratio; each path ends where its data
        # does.
        (0, "HATCH"), (8, "0"), (62, "6"), (2, "SOLID"), (70, "1"), (91, "3"),
        (92, "1"), (93, "4"), (72, "1"), (10, "3000"), (20, "2000"), (11, "4000"), (21, "2000"),
        (72, "1"), (10, "4000"), (20, "2000"), (11, "4000"), (21, "3000"), (72, "1"), (10, "4000"),
        (92, "1"), (93, "2"), (72, "2"), (10, "0"),
        (92, "1"), (93, "2"), (72, "3"), (10, "0"), (20, "0"), (11, "1"), (21, "0"), (40, "0"),
    ),
    "texts": pairs(
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (40, "200"), (1, "LEFT %%d %%p %%c %%% 100%%u"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (11, "3000"), (21, "1000"), (40, "150"), (72, "1"), (73, "2"), (1, "MID"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (11, "3000"), (21, "2000"), (40, "150"), (72, "2"), (73, "3"), (50, "30"),
        (1, "RIGHT TOP"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (11, "1000"), (21, "2500"), (40, "150"), (72, "4"), (1, "MIDDLE"),
        (0, "TEXT"), (8, "0"), (10, "500"), (20, "3000"), (11, "2500"), (21, "3000"), (40, "150"), (72, "5"), (1, "FIT"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (40, "100"), (1, "   "),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (40, "0"), (1, "ZERO"),
        # Codes a text doesn't know are kept as written; an unknown %% code, a bad \\U+ and a lone backslash too.
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "-500"), (40, "150"), (1, "A%%XB %%Q \\U+ZZZZ \\X%%"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "-800"), (40, "150"), (1, "TRAILING\\"),
        (0, "ATTRIB"), (8, "0"), (10, "0"), (20, "-1100"), (40, "150"), (1, "ATTRIB OUTSIDE"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (11, "3000"), (21, "-500"), (40, "150"), (72, "1"), (73, "1"), (1, "CB"),
        (0, "TEXT"), (8, "0"), (10, "0"), (20, "0"), (11, "3000"), (21, "-1000"), (40, "150"), (72, "7"), (73, "0"),
        (1, "ODD"),
    ),
    "mtext": pairs(
        (0, "MTEXT"), (8, "0"), (10, "0"), (20, "3000"), (40, "200"), (71, "1"),
        (3, "{\\fArial|b1;FIRST} \\H2x;LINE\\P\\C1;SEC"), (1, "OND\\~ROW \\S1/2; \\U+00C9 \\\\ \\{x\\}"),
        (0, "MTEXT"), (8, "0"), (10, "4000"), (20, "1000"), (40, "150"), (71, "5"), (44, "1.5"), (50, "90"),
        (1, "TURNED\\PTWO\\PTHREE"),
        (0, "MTEXT"), (8, "0"), (10, "4000"), (20, "3000"), (40, "150"), (71, "9"), (11, "1"), (21, "1"),
        (1, "SLANT\\PBY DIR"),
        (0, "MTEXT"), (8, "0"), (10, "0"), (20, "0"), (40, "150"), (1, "\\P\\P"),
        (0, "MTEXT"), (8, "0"), (10, "0"), (20, "1500"), (40, "150"), (71, "2"),
        (1, "\\A1;\\Q15;\\T1.2;\\W0.8;\\pxi-3;\\Lunder\\l \\Oover\\o \\Kstrike\\k \\Nnext \\S3#4; \\S5^6;"),
        (0, "MTEXT"), (8, "0"), (10, "0"), (20, "0"), (40, "0"), (1, "NO HEIGHT"),
    ),
    "left_out_kinds": pairs(
        (0, "3DFACE"), (8, "0"), (10, "0"), (20, "0"), (11, "1"), (21, "0"), (12, "1"), (22, "1"),
        (0, "VIEWPORT"), (8, "0"), (67, "1"),
        (0, "LINE"), (8, "0"), (67, "1"), (10, "0"), (20, "0"), (11, "500"), (21, "500"),
        (0, "IMAGE"), (8, "0"),
        (0, "ACAD_PROXY_ENTITY"), (8, "0"),
        (0, "LINE"), (8, "0"), (10, "0"), (20, "0"),
        (0, "INSERT"), (8, "0"), (2, "NOWHERE"), (10, "0"), (20, "0"),
        (0, "INSERT"), (8, "0"), (10, "0"), (20, "0"),
        (0, "LINE"), (8, "0"), (10, "0"), (20, "0"), (11, "1000"), (21, "1000"),
        # Shapes of nothing: an ellipse of no ratio, a polyline of one point, a spline of neither controls nor fit
        # points, a hatch of no paths, a solid of two corners.
        (0, "ELLIPSE"), (8, "0"), (10, "0"), (20, "0"), (11, "100"), (21, "0"), (40, "0"),
        (0, "LWPOLYLINE"), (8, "0"), (90, "1"), (10, "5"), (20, "5"),
        (0, "SPLINE"), (8, "0"), (71, "3"), (40, "0"), (10, "0"), (20, "0"),
        (0, "HATCH"), (8, "0"), (70, "1"),
        (0, "SOLID"), (8, "0"), (10, "0"), (20, "0"), (11, "1"), (21, "0"),
        (0, "VERTEX"), (8, "0"), (10, "0"), (20, "0"),
        (0, "SEQEND"), (8, "0"),
        (0, "ATTDEF"), (8, "0"),
    ),
}


@pytest.mark.parametrize("case", sorted(ENTITIES))
def test_entities_come_in_and_are_drawn(run, workdir, golden, case):
    """CATCHES: a rewrite that flattens bulges, arcs, ellipses or splines to other points, closes or opens a polyline
    wrongly, draws a spline's control frame or a mesh, fills a solid in the wrong corner order, loses a hatch's edges
    or paths, aligns or decodes text (%%d, MTEXT codes, \\P lines) differently, or counts what it left out under other
    names."""
    r = import_and_draw(run, workdir, dxf(ENTITIES[case], header=MM))
    check_rounded(golden, r, f"entities_{case}.txt")
    golden.check((workdir / "plan.svg").read_text(), f"entities_{case}.svg")


BLOCKS = block("DOOR", line((0, 0), (900, 0), "0") + pairs(
    (0, "ARC"), (8, "0"), (62, "0"), (10, "0"), (20, "0"), (40, "900"), (50, "0"), (51, "90"),
    (0, "CIRCLE"), (8, "OWN"), (62, "3"), (10, "450"), (20, "450"), (40, "100"),
    (0, "TEXT"), (8, "0"), (10, "100"), (20, "100"), (40, "100"), (1, "D"),
    (0, "ATTRIB"), (8, "0"), (10, "100"), (20, "300"), (40, "80"), (1, "SHOWN"), (70, "0"),
    (0, "ATTRIB"), (8, "0"), (10, "100"), (20, "500"), (40, "80"), (1, "HIDDEN"), (70, "1"),
    (0, "ATTDEF"), (8, "0"), (10, "0"), (20, "0"),
)) + block("PAIR", pairs((0, "INSERT"), (8, "0"), (2, "DOOR"), (10, "0"), (20, "0"))
           + pairs((0, "INSERT"), (8, "0"), (2, "DOOR"), (10, "2000"), (20, "0"), (41, "-1"))) \
   + block("BASED", line((1000, 1000), (1500, 1000), "0"), base=(1000, 1000))


INSERTS = {
    "placed_scaled_turned": pairs(
        (0, "INSERT"), (8, "DOORS"), (62, "1"), (2, "DOOR"), (10, "0"), (20, "0"),
        (0, "INSERT"), (8, "DOORS"), (62, "5"), (2, "DOOR"), (10, "3000"), (20, "0"), (41, "2"), (42, "2"), (50, "90"),
        (0, "INSERT"), (8, "DOORS"), (2, "DOOR"), (10, "5000"), (20, "0"), (41, "1"), (42, "0.5"),
        (0, "INSERT"), (8, "DOORS"), (2, "BASED"), (10, "0"), (20, "3000"),
        (0, "INSERT"), (8, "DOORS"), (2, "DOOR"), (10, "0"), (20, "0"), (41, "0"),
    ),
    "arrays_and_nesting": pairs(
        (0, "INSERT"), (8, "GRID"), (2, "BASED"), (10, "0"), (20, "0"), (70, "3"), (71, "2"), (44, "700"), (45, "400"),
        (0, "INSERT"), (8, "PAIRS"), (2, "PAIR"), (10, "0"), (20, "2000"), (50, "180"),
        (0, "INSERT"), (8, "PAIRS"), (2, "PAIR"), (10, "0"), (20, "5000"), (230, "-1"),
    ),
}


@pytest.mark.parametrize("case", sorted(INSERTS))
def test_blocks_are_placed_by_their_inserts(run, workdir, golden, case):
    """CATCHES: a rewrite that places a block's entities without its base point, scale, turn, array or nesting, that
    doesn't give layer 0's entities the insert's layer and by-block colour, that draws an invisible attribute, or that
    mirrors (or fails to mirror) a block whose extrusion points down."""
    r = import_and_draw(run, workdir, dxf(INSERTS[case], header=MM, blocks=BLOCKS),
                        extra_cmds=['cad_layers {"id": 100002}'])
    check_rounded(golden, r, f"inserts_{case}.txt")
    golden.check((workdir / "plan.svg").read_text(), f"inserts_{case}.svg")


def test_dimension_draws_its_anonymous_block(run, workdir, golden):
    """CATCHES: a rewrite that skips a DIMENSION, or draws it from its definition points instead of the block it
    names; one that names no block draws nothing."""
    blocks = block("*D1", line((0, -200), (2000, -200), "0") + pairs(
        (0, "SOLID"), (8, "0"), (10, "0"), (20, "-200"), (11, "100"), (21, "-170"), (12, "100"), (22, "-230")) + pairs(
        (0, "MTEXT"), (8, "0"), (10, "1000"), (20, "-100"), (40, "120"), (71, "8"), (1, "2000")))
    entities = line((0, 0), (2000, 0), "WALL") + pairs(
        (0, "DIMENSION"), (8, "DIMS"), (2, "*D1"), (10, "2000"), (20, "-200"), (13, "0"), (23, "0"), (14, "2000"), (24, "0"),
        (0, "DIMENSION"), (8, "DIMS"), (10, "0"), (20, "0"))
    r = import_and_draw(run, workdir, dxf(entities, header=MM, blocks=blocks))
    golden.check_run(r, "dimension.txt")
    golden.check((workdir / "plan.svg").read_text(), "dimension.svg")


def test_blocks_nested_too_deep_are_left_out_and_counted(run, workdir, golden):
    """CATCHES: a rewrite that follows blocks inside blocks without the depth bound of 16, recursing forever on a
    block that inserts itself, or that doesn't count what it left out by why."""
    blocks = block("SELF", line((0, 0), (100, 0), "0") + pairs((0, "INSERT"), (8, "0"), (2, "SELF"), (10, "0"), (20, "100")))
    entities = pairs((0, "INSERT"), (8, "LOOP"), (2, "SELF"), (10, "0"), (20, "0"))
    (workdir / "deep.dxf").write_text(dxf(entities, header=MM, blocks=blocks))
    golden.check_run(run(["run", "--cmd", 'import_cad {"path": "deep.dxf", "position": "origin"}']), "nested_too_deep.txt")


def test_scaled_blocks_past_any_drawing_are_left_out(run, workdir, golden):
    """CATCHES: a rewrite that keeps an entity whose block scales carry it past 1e12 drawing units instead of leaving
    it out as "past what a drawing holds"."""
    blocks = block("BIG", line((0, 0), (1000000, 0), "0")) + block(
        "HUGE", pairs((0, "INSERT"), (8, "0"), (2, "BIG"), (10, "0"), (20, "0"), (41, "1000000"), (42, "1000000")))
    entities = line((0, 0), (5000, 0), "KEEP") + pairs(
        (0, "INSERT"), (8, "0"), (2, "HUGE"), (10, "0"), (20, "0"), (41, "100"), (42, "100"))
    (workdir / "far.dxf").write_text(dxf(entities, header=MM, blocks=blocks))
    golden.check_run(run(["run", "--cmd", 'import_cad {"path": "far.dxf", "position": "origin"}']), "past_a_drawing.txt")


def test_a_few_stray_entities_far_off_are_counted_and_warned_about(run, workdir, golden):
    """CATCHES: a rewrite that lets one stray line a hundred kilometres away blow up a drawing's extents and centring,
    or that doesn't count and warn about entities far from the rest; and one that refuses a place within reach."""
    entities = "".join(line((i * 250, 0), (i * 250 + 250, 6000), "WALLS") for i in range(40))
    entities += line((100000000, 100000000), (100001000, 100000000), "JUNK")
    (workdir / "site.dxf").write_text(dxf(entities, header=MM))
    r = run(["run", "--cmd", 'import_cad {"path": "site.dxf"}', "--cmd", 'elements {"category": "cadimport"}',
             "--cmd", 'import_cad {"cad": "site", "at": [1000000000, 0]}'])
    golden.check_run(r, "far_entities.txt")


def test_a_small_drawing_has_no_entity_far_off(run, workdir, golden):
    """CATCHES: a rewrite that counts entities as far off in a drawing of fewer than 20 entities (all of it is bulk)."""
    entities = "".join(line((i * 100, 0), (i * 100, 100), "A") for i in range(5)) + line((5e6, 0), (5e6 + 1, 0), "B")
    (workdir / "few.dxf").write_text(dxf(entities, header=MM))
    golden.check_run(run(["run", "--cmd", 'import_cad {"path": "few.dxf", "position": "origin"}']), "few_entities.txt")


# ---------------------------------------------------------------------------
# Text encodings and line endings
# ---------------------------------------------------------------------------

def _text_dxf(words: bytes, page: bytes | None) -> bytes:
    head = b"0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n"
    if page is not None:
        head += b"9\n$DWGCODEPAGE\n3\n" + page + b"\n"
    head += b"0\nENDSEC\n"
    ents = (b"0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n0\n10\n0\n20\n-500\n11\n4000\n21\n-500\n"
            b"0\nTEXT\n8\n0\n10\n0\n20\n0\n40\n500\n1\n" + words + b"\n0\nENDSEC\n0\nEOF\n")
    return head + ents


ENCODINGS = {
    "utf8": ("ДОМ É".encode("utf-8"), None),
    "utf8_bom": (b"\xef\xbb\xbf", None),
    "latin1_default": ("ÉÀ".encode("latin-1"), None),
    "cp1251": ("ДОМ".encode("cp1251"), b"ANSI_1251"),
    "cp1252": ("ÉÀ".encode("cp1252"), b"ansi_1252"),
    "dos_page_reads_latin1": ("ÉÀ".encode("latin-1"), b"dos850"),
    "koi8": ("ДОМ".encode("koi8_r"), b"KOI8_R"),
}


def test_text_is_decoded_by_its_code_page(run, workdir, golden):
    """CATCHES: a rewrite that reads a pre-2007 file's text in the wrong code page ($DWGCODEPAGE: Windows, KOI8, a DOS
    page as Latin-1), mangles UTF-8, or fails on a byte-order mark: the lettering each draws in the plan is compared."""
    report = []
    for case in sorted(ENCODINGS):
        words, page = ENCODINGS[case]
        data = _text_dxf(words if case != "utf8_bom" else "BOM".encode(), page)
        if case == "utf8_bom":
            data = words + data
        (workdir / f"{case}.dxf").write_bytes(data)
        lines = ['import_cad ' + json.dumps({"path": f"{case}.dxf", "position": "origin"}),
                 'render {"view": "Level 1", "width": 400, "height": 300, "path": "plan.svg"}']
        (workdir / "script.txt").write_text("\n".join(lines) + "\n")
        r = run(["run", "--script", "script.txt"])
        report.append(f"### {case}\n{outcome(r)}--- plan.svg\n{(workdir / 'plan.svg').read_text()}\n")
    golden.check("".join(report), "encodings.txt")


# Each code page $DWGCODEPAGE may name, and the bytes 0xC0 0xC1 0xE9 0xF0 in a layer's name: what they read as is in
# `cad_layers`. A page with no decoder here (the DOS ones) reads as Latin-1.
PAGES = ["ANSI_874", "ANSI_932", "ANSI_936", "ANSI_949", "ANSI_950", "ANSI_1250", "ANSI_1251", "ANSI_1252", "ANSI_1253",
         "ANSI_1254", "ANSI_1255", "ANSI_1256", "ANSI_1257", "ANSI_1258", "ANSI_8859_2", "ANSI_8859_3", "ANSI_8859_4",
         "ANSI_8859_5", "ANSI_8859_6", "ANSI_8859_7", "ANSI_8859_8", "ANSI_8859_9", "DOS866", "KOI8_R", "MACINTOSH",
         "ANSI_65001", "DOS437", "NONE"]


def _named_layer_dxf(page: bytes | None, code: bytes = b"3") -> bytes:
    head = b"0\nSECTION\n2\nHEADER\n"
    if page is not None:
        head += b"9\n$DWGCODEPAGE\n" + code + b"\n" + page + b"\n"
    head += b"0\nENDSEC\n"
    return head + b"0\nSECTION\n2\nENTITIES\n0\nLINE\n8\nL\xc0\xc1\xe9\xf0\n10\n0\n20\n0\n11\n1\n21\n1\n0\nENDSEC\n0\nEOF\n"


def test_every_code_page_decodes_a_layers_name(run, workdir, golden):
    """CATCHES: a rewrite that maps a $DWGCODEPAGE name (Windows, ISO 8859, East Asian, KOI8, Mac, UTF-8 as 65001) to
    another encoding, decodes a page it has no decoder for (DOS) as anything but Latin-1, or reads the page from a
    header variable whose value isn't a page name (code 3)."""
    lines = []
    for i, page in enumerate(PAGES):
        (workdir / f"p{i}.dxf").write_bytes(_named_layer_dxf(page.encode()))
        lines += ['import_cad ' + json.dumps({"path": f"p{i}.dxf", "name": page}), f'cad_layers {{"id": {100002 + i}}}']
    (workdir / "code1.dxf").write_bytes(_named_layer_dxf(b"ANSI_1251", b"1"))
    lines += ['import_cad {"path": "code1.dxf"}', f'cad_layers {{"id": {100002 + len(PAGES)}}}']
    (workdir / "script.txt").write_text("\n".join(lines) + "\n")
    r = run(["run", "--script", "script.txt"])
    layers = [json.loads(line)["layers"][0]["name"] for line in r.stdout.decode().splitlines() if '"layers":[' in line]
    report = "".join(f"{page}: {name}\n" for page, name in zip(PAGES + ["ANSI_1251 under code 1"], layers))
    golden.check(f"exit: {r.returncode}\n{report}--- stderr\n{r.stderr.decode()}", "code_pages.txt")


def test_sections_and_records_it_passes_over(run, workdir, golden):
    """CATCHES: a rewrite that fails on comments (999) and stray records between sections, on sections it doesn't draw
    (CLASSES, OBJECTS, THUMBNAILIMAGE), on header
    variables it doesn't use ($ACADVER, $EXTMIN, $EXTMAX, $LTSCALE of 0), on an entity between blocks, or on table
    entries of other kinds (STYLE, VIEW)."""
    text = (pairs((999, "made by hand"), (0, "JUNK"), (0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1015"), (9, "$INSUNITS"), (70, "4"),
                  (9, "$EXTMIN"), (10, "-100"), (20, "-100"), (30, "0"), (9, "$EXTMAX"), (10, "5100"), (20, "100"),
                  (9, "$LTSCALE"), (40, "0"), (0, "ENDSEC"))
            + pairs((0, "SECTION"), (2, "CLASSES"), (0, "CLASS"), (1, "ACDBDICTIONARYWDFLT"), (0, "ENDSEC"))
            + section("TABLES", pairs((999, "tables"), (0, "TABLE"), (2, "STYLE"), (0, "STYLE"), (2, "Standard"), (40, "0"), (0, "ENDTAB"),
                                      (0, "TABLE"), (2, "VIEW"), (0, "ENDTAB")) + ltype_table(("DASHED", ["100", "-50"])))
            + section("BLOCKS", pairs((999, "blocks")) + line((0, 0), (1, 1), "STRAY") + block("B", line((0, 0), (500, 0), "0")))
            + section("ENTITIES", pairs((999, "entities")) + line((0, 0), (5000, 0), "A", (6, "DASHED"))
                      + pairs((0, "INSERT"), (8, "A"), (2, "B"), (10, "0"), (20, "100")))
            + pairs((0, "SECTION"), (2, "OBJECTS"), (0, "DICTIONARY"), (5, "C"), (0, "ENDSEC"))
            + pairs((0, "SECTION"), (2, "THUMBNAILIMAGE"), (90, "4"), (310, "00000000"), (0, "ENDSEC"))
            + pairs((0, "EOF")) + "anything after the end\n")
    r = import_and_draw(run, workdir, text, extra_cmds=['cad_layers {"id": 100002}'])
    golden.check_run(r, "passed_over.txt")
    golden.check((workdir / "plan.svg").read_text(), "passed_over.svg")


def test_windows_line_endings_and_padded_codes_are_read(run, workdir, golden):
    """CATCHES: a rewrite that fails on CRLF line endings or right-aligned group codes ("  0"), as AutoCAD writes them,
    or that keeps the spaces of a name."""
    text = dxf(line((0, 0), (3000, 0), "WALLS") + pairs((0, "TEXT"), (8, "NOTES "), (10, "0"), (20, "500"), (40, "200"),
                                                        (1, "CRLF ")), header=MM)
    padded = "".join(f"{int(c):>3}\r\n{v}\r\n" for c, v in zip(text.split("\n")[0::2], text.split("\n")[1::2]))
    (workdir / "win.dxf").write_bytes(padded.encode())
    cmds = ['import_cad {"path": "win.dxf", "position": "origin"}', 'cad_layers {"id": 100002}']
    (workdir / "script.txt").write_text("\n".join(cmds) + "\n")
    golden.check_run(run(["run", "--script", "script.txt"]), "crlf_padded.txt")


# ---------------------------------------------------------------------------
# Files it can't read
# ---------------------------------------------------------------------------

# Files whose pairs can't be read: each refusal names the line.
BAD_PAIRS = {
    "binary_dxf": b"AutoCAD Binary DXF\r\n\x1a\x00rest",
    "not_a_group_code": b"0\nSECTION\n2\nENTITIES\nhello\n",
    "ends_after_code": b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n",
    "value_not_a_number": dxf(pairs((0, "LINE"), (8, "0"), (10, "abc"), (20, "0"), (11, "1"), (21, "1"))).encode(),
    "nan_value": dxf(pairs((0, "LINE"), (8, "0"), (10, "NaN"), (20, "0"), (11, "1"), (21, "1"))).encode(),
    "infinite_value": dxf(pairs((0, "CIRCLE"), (8, "0"), (10, "0"), (20, "0"), (40, "inf"))).encode(),
    "past_a_drawing": dxf(pairs((0, "LINE"), (8, "0"), (10, "2e12"), (20, "0"), (11, "1"), (21, "1"))).encode(),
    "bad_number_in_layer_table": dxf(line((0, 0), (1, 1)), tables=pairs(
        (0, "TABLE"), (2, "LAYER"), (0, "LAYER"), (2, "A"), (62, "red"), (0, "ENDTAB"))).encode(),
    "bad_number_in_hatch": dxf(pairs((0, "HATCH"), (8, "0"), (70, "1"), (91, "1"), (92, "2"), (72, "0"), (93, "1"),
                                     (10, "x"), (20, "0"))).encode(),
}

# Files that read, but hold no drawing.
BAD_DRAWINGS = {
    "no_entities_section": section("HEADER", pairs((9, "$INSUNITS"), (70, "4"))).encode() + b"0\nEOF\n",
    "section_with_no_name": b"0\nSECTION\n9\nHEADER\n0\nENDSEC\n0\nEOF\n",
    "draws_nothing": dxf("", header=MM).encode(),
    "only_paper_space": dxf(pairs((0, "LINE"), (8, "0"), (67, "1"), (10, "0"), (20, "0"), (11, "1"), (21, "1"))).encode(),
    "empty_file": b"",
}


def _refusals(run, workdir, cases):
    report = []
    for case in sorted(cases):
        (workdir / "bad.dxf").write_bytes(cases[case])
        r = run(["run", "--cmd", 'import_cad {"path": "bad.dxf"}', "--cmd", 'elements {"category": "cadimport"}'])
        report.append(f"### {case}\n{outcome(r)}")
    return "".join(report)


def test_a_file_whose_pairs_cant_be_read_says_why(run, workdir, golden):
    """CATCHES: a rewrite that takes a binary DXF, a code that isn't a number, a file ending after a code, or a value
    that isn't a finite number within 1e12 (NaN, inf, a word), or refuses it without the file's name and the line."""
    golden.check(_refusals(run, workdir, BAD_PAIRS), "bad_pairs.txt")


def test_a_file_that_holds_no_drawing_says_why(run, workdir, golden):
    """CATCHES: a rewrite that takes an empty file, one with no ENTITIES section or a nameless SECTION, or one whose
    model space draws nothing (all of it paper space), instead of refusing it with the reference's words."""
    golden.check(_refusals(run, workdir, BAD_DRAWINGS), "bad_drawings.txt")


def test_files_that_are_no_dxf_say_what_it_reads(run, workdir, golden):
    """CATCHES: a rewrite that tries to read a PDF or an extensionless file as a drawing, or doesn't name a missing
    file and the OS's reason."""
    (workdir / "plan.pdf").write_text("%PDF-1.7")
    (workdir / "PLAN.DXF").write_text(dxf(line((0, 0), (1000, 0)), header=MM))
    for args, name in [
        (["--cmd", 'import_cad {"path": "plan.pdf"}'], "not_dxf_pdf.txt"),
        (["--cmd", 'import_cad {"path": "nowhere.dxf"}'], "not_dxf_missing.txt"),
        (["--cmd", 'import_cad {"path": "noext"}'], "not_dxf_noext.txt"),
        (["--cmd", 'import_cad {"path": "PLAN.DXF", "position": "origin"}'], "upper_case_extension.txt"),
    ]:
        golden.check_run(run(["run", *args]), name)
