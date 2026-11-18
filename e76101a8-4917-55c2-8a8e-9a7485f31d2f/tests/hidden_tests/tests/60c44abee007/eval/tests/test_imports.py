"""Bringing in what other programs make: DXF and DWG drawings (import_cad, cad_layers, reload_cad, cad_query), laser scans
(point_cloud from PTS, XYZ, PLY, LAS and E57) and Revit files (info, run, convert)."""

import json
import math
import re
import shutil
import struct

import pytest

from conftest import resources_for

RES = resources_for(__file__)

# A number printed to nine or more decimals: what a sine or a square root last went through, whose last bits a libm of
# another machine may round otherwise. Kept to six decimals; everything else is compared as printed.
LONG_FLOAT = re.compile(r"(?<![\w.])(-?\d+\.\d{9,})(?!\d)")


@pytest.fixture
def sc(sc):
    """The suite's Scenario, its transcript with long decimals kept to six places."""
    whole = sc.transcript
    sc.transcript = lambda: LONG_FLOAT.sub(lambda m: f"{float(m.group(1)):.6f}", whole())
    return sc


# ---------------------------------------------------------------------------
# Input builders
# ---------------------------------------------------------------------------


def pairs(items) -> str:
    """Group codes and values as a DXF writes them, a line each."""
    return "".join(f"{c}\n{v}\n" for c, v in items)


def dxf(entities=(), header=(), tables=(), blocks=None) -> str:
    """An ASCII DXF: a header, tables, blocks (when given) and entities."""
    text = pairs([(0, "SECTION"), (2, "HEADER"), *header, (0, "ENDSEC")])
    text += pairs([(0, "SECTION"), (2, "TABLES"), *tables, (0, "ENDSEC")])
    if blocks is not None:
        text += pairs([(0, "SECTION"), (2, "BLOCKS"), *blocks, (0, "ENDSEC")])
    text += pairs([(0, "SECTION"), (2, "ENTITIES"), *entities, (0, "ENDSEC"), (0, "EOF")])
    return text


def layer(name, color=7, linetype="CONTINUOUS", flags=0, extra=()):
    return [(0, "LAYER"), (2, name), (70, flags), (62, color), (6, linetype), *extra]


def layers(*rows):
    out = [(0, "TABLE"), (2, "LAYER")]
    for r in rows:
        out += r
    return out + [(0, "ENDTAB")]


def line(a, b, lay="0", extra=()):
    return [(0, "LINE"), (8, lay), *extra, (10, a[0]), (20, a[1]), (30, 0), (11, b[0]), (21, b[1]), (31, 0)]


MM = [(9, "$ACADVER"), (1, "AC1027"), (9, "$INSUNITS"), (70, 4)]

# A plan in millimetres: walls on a red layer with a line weight, a dashed layer that is off, a frozen one, one in a true
# colour, a block of a chair placed turned and scaled, a note and a 3D face the reader leaves out.
PLAN_TABLES = [
    (0, "TABLE"), (2, "LTYPE"),
    (0, "LTYPE"), (2, "DASHED"), (70, 0), (3, "Dashed __ __"), (72, 65), (73, 2), (40, 15), (49, 10), (49, -5),
    (0, "ENDTAB"),
    *layers(
        layer("0"),
        layer("WALLS", 1, extra=[(370, 50)]),
        layer("HIDDEN", -3, "DASHED"),
        layer("FROZEN", 5, flags=1),
        layer("TRUE", 7, extra=[(420, 0x336699)]),
    ),
]
PLAN_BLOCKS = [
    (0, "BLOCK"), (8, "0"), (2, "CHAIR"), (70, 0), (10, 0), (20, 0), (30, 0),
    *line((0, 0), (500, 0)),
    (0, "CIRCLE"), (8, "0"), (62, 0), (10, 250), (20, 250), (40, 100),
    (0, "ENDBLK"), (8, "0"),
]
PLAN_ENTITIES = [
    *line((0, 0), (10000, 0), "WALLS"),
    (0, "LWPOLYLINE"), (8, "WALLS"), (90, 4), (70, 1),
    (10, 0), (20, 0), (10, 10000), (20, 0), (42, 0.5), (10, 10000), (20, 5000), (10, 0), (20, 5000),
    (0, "CIRCLE"), (8, "HIDDEN"), (10, 5000), (20, 2500), (40, 1000),
    (0, "ARC"), (8, "TRUE"), (10, 2000), (20, 2000), (40, 500), (50, 0), (51, 90),
    (0, "TEXT"), (8, "0"), (10, 100), (20, 100), (40, 250), (1, "Room %%d 1"),
    (0, "INSERT"), (8, "WALLS"), (2, "CHAIR"), (10, 3000), (20, 3000), (41, 2), (42, 2), (50, 45),
    (0, "POINT"), (8, "FROZEN"), (10, 7000), (20, 7000),
    (0, "3DFACE"), (8, "0"), (10, 0), (20, 0), (30, 0),
]


def plan_dxf(header=MM) -> str:
    return dxf(PLAN_ENTITIES, header, PLAN_TABLES, PLAN_BLOCKS)


def cmd(id_, params) -> str:
    return f"{id_} {json.dumps(params)}"


def project_part(sc, path, key):
    """Record one top-level part of a .bimcraft project file the program wrote."""
    doc = json.loads((sc.workdir / path).read_text(encoding="utf-8"))
    sc.note(f"=== {path} [{key}]")
    sc.note(json.dumps(doc.get(key), indent=1, sort_keys=True, ensure_ascii=False))


def written_files(sc):
    """The files in the working directory, by name (a coverage build's profiles left out)."""
    names = sorted(p.name for p in sc.workdir.iterdir() if p.is_file() and p.suffix != ".profraw")
    sc.note("=== files: " + ", ".join(names))


def copy_resource(sc, name, as_name=None):
    shutil.copy(RES / name, sc.workdir / (as_name or name))


def las_bytes(minor, fmt, scale, offset, pts, gap=0) -> bytes:
    """An uncompressed LAS file: `pts` as ([x, y, z] integers, intensity, [r, g, b])."""
    header = 375 if minor >= 4 else 227
    size = {0: 20, 1: 28, 2: 26, 3: 34, 6: 30, 7: 36}[fmt]
    b = bytearray(header + gap)
    b[0:4] = b"LASF"
    b[24], b[25] = 1, minor
    b[94:96] = struct.pack("<H", header)
    b[96:100] = struct.pack("<I", header + gap)
    b[104] = fmt
    b[105:107] = struct.pack("<H", size)
    if fmt >= 6:
        b[247:255] = struct.pack("<Q", len(pts))
    else:
        b[107:111] = struct.pack("<I", len(pts))
    for k in range(3):
        b[131 + 8 * k:139 + 8 * k] = struct.pack("<d", scale[k])
        b[155 + 8 * k:163 + 8 * k] = struct.pack("<d", offset[k])
    colour = {2: 20, 3: 28, 7: 30}.get(fmt)
    for xyz, intensity, rgb in pts:
        r = bytearray(size)
        r[0:12] = struct.pack("<3i", *xyz)
        r[12:14] = struct.pack("<H", intensity)
        if colour is not None:
            r[colour:colour + 6] = struct.pack("<3H", *rgb)
        b += r
    return bytes(b)


def ply_bytes(form, pts) -> bytes:
    """A PLY file of points (x y z floats, a normal's x, then red green blue bytes), with an empty face element after."""
    head = (
        f"ply\r\nformat {form} 1.0\ncomment made by hand\nelement vertex {len(pts)}\nproperty float x\nproperty float y\n"
        "property float z\nproperty float nx\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nelement face 0\n"
        "property list uchar int vertex_indices\nend_header\n"
    ).encode()
    body = b""
    for p, c in pts:
        if form == "ascii":
            body += f"{p[0]} {p[1]} {p[2]} 0.5 {c[0]} {c[1]} {c[2]}\n".encode()
        else:
            order = "<" if form == "binary_little_endian" else ">"
            body += struct.pack(order + "4f", p[0], p[1], p[2], 0.5) + bytes(c)
    return head + body


# E57 (ASTM E2807): 1024-byte pages whose last four bytes are a checksum (left nought: the reader doesn't check them).
E57_PAGE, E57_DATA = 1024, 1020


def e57_float(name, values, single=True):
    xml = f'<{name} type="Float"{" precision=\"single\"" if single else ""}/>'
    return {"xml": xml, "kind": "f32" if single else "f64", "values": list(values)}


def e57_int(name, lo, hi, values, scale=1.0, offset=0.0):
    plain = scale == 1.0 and offset == 0.0
    kind = "Integer" if plain else "ScaledInteger"
    more = "" if plain else f' scale="{scale}" offset="{offset}"'
    xml = f'<{name} type="{kind}" minimum="{lo}" maximum="{hi}"{more}>0</{name}>'
    bits = (hi - lo).bit_length()
    return {"xml": xml, "kind": "int", "lo": lo, "bits": bits, "scale": scale, "offset": offset, "values": list(values)}


def e57_stream(f) -> bytes:
    out, acc, n = bytearray(), 0, 0
    for v in f["values"]:
        if f["kind"] == "f64":
            raw, bits = struct.unpack("<Q", struct.pack("<d", v))[0], 64
        elif f["kind"] == "f32":
            raw, bits = struct.unpack("<I", struct.pack("<f", v))[0], 32
        else:
            raw, bits = round((v - f["offset"]) / f["scale"]) - f["lo"], f["bits"]
        acc |= raw << n
        n += bits
        while n >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            n -= 8
    if n > 0:
        out.append(acc & 0xFF)
    return bytes(out)


def e57_physical(logical):
    return logical // E57_DATA * E57_PAGE + logical % E57_DATA


def e57_bytes(scans, edit=lambda xml: xml) -> bytes:
    """An E57 file of `scans` (each {"fields": [...], "more": xml}): the header, a section of data packets for each scan
    (streams cut so values cross packets), then the XML (`edit` changes it first), laid in pages."""
    logical = bytearray(48)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<e57Root type="Structure" xmlns="http://www.astm.org/COMMIT/E57/2010-e57-v1.0">\n'
        '<formatName type="String"><![CDATA[ASTM E57 3D Imaging Data File]]></formatName>\n'
        '<data3D type="Vector" allowHeterogeneousChildren="1">\n'
    )
    for i, scan in enumerate(scans):
        start = len(logical)
        streams = [e57_stream(f) for f in scan["fields"]]
        packets, cut, first = bytearray(), [0] * len(streams), True
        while any(c < len(s) for c, s in zip(cut, streams)):
            parts = []
            for k, s in enumerate(streams):
                to = min(cut[k] + 5 + 3 * k, len(s))
                parts.append(s[cut[k]:to])
                cut[k] = to
            p = bytearray([1, 0, 0, 0]) + struct.pack("<H", len(parts))
            for part in parts:
                p += struct.pack("<H", len(part))
            for part in parts:
                p += part
            while len(p) % 4:
                p.append(0)
            p[2:4] = struct.pack("<H", len(p) - 1)
            packets += p
            if first:
                packets += bytes([2, 0, 7, 0, 0, 0, 0, 0])
                first = False
        logical += bytes([1, 0, 0, 0, 0, 0, 0, 0])
        logical += struct.pack("<Q", 32 + len(packets))
        logical += struct.pack("<Q", e57_physical(start + 32))
        logical += struct.pack("<Q", 0)
        logical += packets
        while len(logical) % 4:
            logical.append(0)
        count = len(scan["fields"][0]["values"]) if scan["fields"] else 0
        prototype = "".join(f["xml"] for f in scan["fields"])
        xml += (
            f'<vectorChild type="Structure">\n<name type="String"><![CDATA[scan {i}]]></name>\n{scan.get("more", "")}\n'
            f'<points type="CompressedVector" fileOffset="{e57_physical(start)}" recordCount="{count}">\n'
            f'<prototype type="Structure">{prototype}</prototype>\n'
            '<codecs type="Vector" allowHeterogeneousChildren="1"></codecs>\n</points>\n</vectorChild>\n'
        )
    xml += '</data3D>\n<images2D type="Vector" allowHeterogeneousChildren="1"/>\n</e57Root>\n'
    xml = edit(xml)
    xml_at = len(logical)
    logical += xml.encode()
    pages = -(-len(logical) // E57_DATA)
    h = b"ASTM-E57" + struct.pack("<II", 1, 0) + struct.pack("<QQQQ", pages * E57_PAGE, e57_physical(xml_at), len(xml), E57_PAGE)
    logical[0:48] = h
    out = bytearray()
    for k in range(0, len(logical), E57_DATA):
        out += logical[k:k + E57_DATA]
        out += bytes(-len(out) % E57_PAGE)
    return bytes(out)


def e57_cartesian(points):
    return [e57_float(n, [p[k] for p in points]) for k, n in enumerate(["cartesianX", "cartesianY", "cartesianZ"])]


def grid_points(n):
    """Points along a line with a zigzag: enough of them that streams cross packets and pages."""
    return [[i * 0.01, (i % 7) * 0.5, -i * 0.002] for i in range(n)]


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------


def test_dxf_import_reports_its_unit_entities_layers_and_what_was_left_out(sc):
    """CATCHES: an import that counts entities or layers wrongly, forgets the 3DFACE it left out, centres the drawing on the
    wrong point, gives the off and frozen layers as shown, or lists a layer's colour or linetype wrongly."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("import_cad", {"path": "plan.dxf"}),
        cmd("cad_layers", {"id": 100002}),
        cmd("elements", {"category": "cadimport"}),
    )
    assert sc.transcript() == sc.golden()


def test_dxf_import_draws_in_the_svg_plan(sc):
    """CATCHES: a plan that leaves an import out, draws its hidden layers, ignores its layers' colours, line weights,
    the bulge of a polyline, the turned and scaled block, or the note's lettering."""
    sc.write("plan.dxf", plan_dxf())
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "plan.dxf"}), "--save", "plan.svg"])
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_dxf_units_auto_given_or_a_scale(sc):
    """CATCHES: `units` auto not reading $INSUNITS (metres here), a unit given not overriding it, a `scale` not being mm to
    each unit, or the reply's unit text not saying what the file said."""
    header = [(9, "$INSUNITS"), (70, 6)]
    sc.write("site.dxf", dxf(line((0, 0), (10, 0)) + line((10, 0), (10, 6)), header))
    sc.cmds(
        cmd("import_cad", {"path": "site.dxf"}),
        cmd("import_cad", {"path": "site.dxf", "name": "as cm", "units": "cm"}),
        cmd("import_cad", {"path": "site.dxf", "name": "as feet", "units": "ft"}),
        cmd("import_cad", {"path": "site.dxf", "name": "scaled", "scale": 25.4}),
        cmd("import_cad", {"path": "site.dxf", "name": "auto", "units": "auto"}),
    )
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("code", [0, 1, 2, 5, 14, 18, 21])
def test_dxf_insunits_codes(sc, code):
    """CATCHES: a wrong millimetre factor or unit name for an $INSUNITS code (inches, feet, cm, dm, US survey feet), or a
    unit no building is drawn in (astronomical units) or a unitless file not being read as millimetres and said so."""
    sc.write("d.dxf", dxf(line((0, 0), (100, 50)), [(9, "$INSUNITS"), (70, code)]))
    sc.cmds(cmd("import_cad", {"path": "d.dxf"}))
    assert sc.transcript() == sc.golden()


def test_dxf_position_origin_at_and_angle(sc):
    """CATCHES: `position: origin` not putting the drawing's origin on `at`, `at` ignored, `angle` turning the wrong way, or
    the extents not following the placement."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("import_cad", {"path": "plan.dxf", "position": "origin"}),
        cmd("import_cad", {"path": "plan.dxf", "name": "moved", "position": "origin", "at": [20000, 5000]}),
        cmd("import_cad", {"path": "plan.dxf", "name": "turned", "position": "centre", "at": [-30000, 0], "angle": 90}),
        cmd("elements", {"category": "cadimport"}),
    )
    assert sc.transcript() == sc.golden()


def test_dxf_layers_all_or_a_list_and_colours(sc):
    """CATCHES: `layers: all` still hiding the off and frozen layers, a list not hiding the others, or `colors` invert or
    black not being kept on the import and drawn so in the plan."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("import_cad", {"path": "plan.dxf", "layers": "all", "colors": "invert"}),
        cmd("import_cad", {"path": "plan.dxf", "name": "two", "layers": ["WALLS", "TRUE"], "colors": "black", "at": [0, 20000]}),
        cmd("import_cad", {"path": "plan.dxf", "name": "visible", "layers": "visible", "colors": "preserve", "at": [0, -20000]}),
        cmd("elements", {"category": "cadimport"}),
        post=["--save", "plan.svg"],
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_dxf_import_parameter_errors(sc):
    """CATCHES: bad import_cad parameters accepted instead of refused with a message naming the parameter and its choices:
    units and scale together, a scale out of range, an unknown unit, position, colors or layers value, a layer the drawing
    hasn't, neither path nor cad, both, an empty name, a name already held."""
    sc.write("plan.dxf", plan_dxf())
    bad = [
        {"path": "plan.dxf", "units": "mm", "scale": 2},
        {"path": "plan.dxf", "scale": 0},
        {"path": "plan.dxf", "scale": 1e9},
        {"path": "plan.dxf", "units": "furlong"},
        {"path": "plan.dxf", "position": "corner"},
        {"path": "plan.dxf", "colors": "sepia"},
        {"path": "plan.dxf", "layers": "some"},
        {"path": "plan.dxf", "layers": ["NOPE"]},
        {"path": "plan.dxf", "layers": [3]},
        {},
        {"path": "plan.dxf", "cad": "plan"},
        {"path": "plan.dxf", "name": "  "},
        {"cad": "nothing"},
        {"path": "plan.dxf", "level": "Level 9"},
    ]
    for params in bad:
        sc.cmds(cmd("import_cad", params))
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("import_cad", {"path": "plan.dxf"}))
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("import_cad", {"cad": "plan", "link": True}))
    assert sc.transcript() == sc.golden()


def test_dxf_files_that_cannot_be_read_say_why(sc):
    """CATCHES: a reader that accepts or crashes on a broken file instead of naming the problem and its line: a missing file,
    another extension, a binary DXF, no ENTITIES section, a group code that isn't a number, a file ending after a group
    code, a value that isn't a number, a coordinate past what a drawing holds, a SECTION with no name, nothing drawn."""
    files = {
        "missing.dxf": None,
        "drawing.txt": dxf(line((0, 0), (1, 1))),
        "binary.dxf": b"AutoCAD Binary DXF\r\n\x1a\x00rest",
        "noents.dxf": pairs([(0, "SECTION"), (2, "HEADER"), (0, "ENDSEC"), (0, "EOF")]),
        "code.dxf": "  0\nSECTION\nabc\nENTITIES\n",
        "ends.dxf": pairs([(0, "SECTION"), (2, "ENTITIES"), (0, "LINE"), (8, "0")]) + "10\n",
        "nan.dxf": dxf([(0, "LINE"), (8, "0"), (10, "one"), (20, 0), (11, 5), (21, 5)]),
        "inf.dxf": dxf([(0, "LINE"), (8, "0"), (10, "inf"), (20, 0), (11, 5), (21, 5)]),
        "huge.dxf": dxf([(0, "LINE"), (8, "0"), (10, "1e13"), (20, 0), (11, 5), (21, 5)]),
        "noname.dxf": "0\nSECTION\n9\nX\n",
        "empty.dxf": dxf([]),
        "onlypaper.dxf": dxf(line((0, 0), (5, 5), extra=[(67, 1)])),
    }
    for name, body in files.items():
        if body is not None:
            sc.write(name, body)
        sc.cmds(cmd("import_cad", {"path": name}))
    assert sc.transcript() == sc.golden()


def test_dxf_curves_polylines_ellipses_and_splines(sc):
    """CATCHES: a reader that draws POLYLINE vertices without their bulges, keeps a spline frame's control vertices or a
    polyface mesh, draws a partial ellipse whole, ignores a spline's knots, or draws a spline with no knots from anything
    but its fit points; and an extrusion pointing down not mirroring an arc."""
    ents = [
        (0, "POLYLINE"), (8, "P"), (66, 1), (70, 1),
        (0, "VERTEX"), (8, "P"), (10, 0), (20, 0), (42, 1),
        (0, "VERTEX"), (8, "P"), (10, 2000), (20, 0),
        (0, "VERTEX"), (8, "P"), (10, 2000), (20, 1000),
        (0, "SEQEND"), (8, "P"),
        (0, "POLYLINE"), (8, "P"), (66, 1), (70, 4),
        (0, "VERTEX"), (8, "P"), (10, 0), (20, 3000), (70, 16),
        (0, "VERTEX"), (8, "P"), (10, 500), (20, 3500), (70, 8),
        (0, "VERTEX"), (8, "P"), (10, 1500), (20, 3000), (70, 8),
        (0, "SEQEND"), (8, "P"),
        (0, "POLYLINE"), (8, "MESH"), (66, 1), (70, 64),
        (0, "VERTEX"), (8, "MESH"), (10, 0), (20, 0),
        (0, "SEQEND"), (8, "MESH"),
        (0, "ELLIPSE"), (8, "E"), (10, 5000), (20, 1000), (11, 1000), (21, 0), (40, 0.5),
        (0, "ELLIPSE"), (8, "E"), (10, 5000), (20, 4000), (11, 0), (21, 800), (40, 0.25), (41, 0), (42, 3.14159265),
        (0, "SPLINE"), (8, "S"), (70, 8), (71, 3), (72, 8), (73, 4),
        (40, 0), (40, 0), (40, 0), (40, 0), (40, 1), (40, 1), (40, 1), (40, 1),
        (10, 8000), (20, 0), (10, 9000), (20, 2000), (10, 10000), (20, -1000), (10, 11000), (20, 1000),
        (0, "SPLINE"), (8, "S"), (70, 0), (71, 3), (74, 3), (11, 8000), (21, 3000), (11, 9000), (21, 4000), (11, 11000), (21, 3500),
        (0, "ARC"), (8, "M"), (10, 3000), (20, 6000), (40, 600), (50, 0), (51, 90), (210, 0), (220, 0), (230, -1),
        (0, "LWPOLYLINE"), (8, "M"), (90, 1), (70, 0), (10, 0), (20, 0),
        (0, "CIRCLE"), (8, "M"), (10, 0), (20, 0), (40, 0),
    ]
    sc.write("curves.dxf", dxf(ents, MM))
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "curves.dxf"}), "--save", "curves.svg",
            "--cmd", cmd("cad_query", {"id": 100002, "at": [-7300, -3800], "reach": 5000})])
    sc.file("curves.svg")
    assert sc.transcript() == sc.golden()


def test_dxf_text_mtext_and_their_alignment(sc):
    """CATCHES: text whose %% codes, \\U+ characters, MTEXT formatting codes, stacked fractions or paragraph breaks are not
    decoded as the DXF reference says, or which ignores its alignment point, rotation, attachment or line spacing."""
    ents = [
        (0, "TEXT"), (8, "T"), (10, 0), (20, 0), (40, 300), (1, "%%c50 %%p2 100%%% %%uUnder%%u \\U+00E9"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 1000), (11, 4000), (21, 1000), (40, 200), (72, 1), (73, 2), (1, "centred"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 2000), (11, 4000), (21, 2000), (40, 200), (72, 2), (73, 3), (50, 30), (1, "right top"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 3000), (11, 4000), (21, 3000), (40, 200), (72, 4), (1, "middle"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4000), (40, 0), (1, "no height"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4500), (40, 100), (1, "   "),
        (0, "MTEXT"), (8, "T"), (10, 6000), (20, 0), (40, 250), (71, 5), (44, 1.5),
        (3, "{\\fArial|b1;Bold} first\\Psecond \\H2x;tall\\P"), (1, "\\S1/2; and \\S3^4; \\~end"),
        (0, "MTEXT"), (8, "T"), (10, 6000), (20, 4000), (40, 200), (11, 0), (21, 1), (71, 9), (1, "turned\\Pby direction"),
        (0, "ATTRIB"), (8, "T"), (10, 0), (20, 6000), (40, 200), (1, "attribute"), (70, 0),
        (0, "ATTRIB"), (8, "T"), (10, 0), (20, 6500), (40, 200), (1, "invisible"), (70, 1),
    ]
    sc.write("text.dxf", dxf(ents, MM))
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "text.dxf"}), "--save", "text.svg"])
    sc.file("text.svg")
    assert sc.transcript() == sc.golden()


def test_dxf_hatches_solids_and_traces(sc):
    """CATCHES: a hatch whose polyline or edge boundaries (lines, arcs, elliptic arcs, splines) aren't followed, a solid
    hatch drawn as a pattern or the other way round, or a SOLID and TRACE drawn with their corners in file order."""
    ents = [
        (0, "HATCH"), (8, "H"), (62, 3), (2, "SOLID"), (70, 1), (91, 1),
        (92, 2), (72, 1), (73, 1), (93, 4),
        (10, 0), (20, 0), (42, 0), (10, 2000), (20, 0), (42, 0.4), (10, 2000), (20, 2000), (42, 0), (10, 0), (20, 2000), (42, 0),
        (0, "HATCH"), (8, "H"), (62, 5), (2, "ANSI31"), (70, 0), (91, 2),
        (92, 1), (93, 4),
        (72, 1), (10, 3000), (20, 0), (11, 6000), (21, 0),
        (72, 2), (10, 6000), (20, 1000), (40, 1000), (50, 270), (51, 90), (73, 1),
        (72, 3), (10, 4500), (20, 2000), (11, 1500), (21, 0), (40, 0.3), (50, 0), (51, 180), (73, 1),
        (72, 1), (10, 3000), (20, 2000), (11, 3000), (21, 0),
        (92, 1), (93, 1),
        (72, 4), (94, 3), (73, 0), (74, 0), (95, 8), (96, 4),
        (40, 0), (40, 0), (40, 0), (40, 0), (40, 1), (40, 1), (40, 1), (40, 1),
        (10, 4000), (20, 500), (10, 4500), (20, 1500), (10, 5000), (20, 500), (10, 4000), (20, 500),
        (0, "HATCH"), (8, "H"), (70, 1), (91, 1), (92, 1), (93, 1),
        (72, 2), (10, 8000), (20, 1000), (40, 800), (50, 0), (51, 360), (73, 0),
        (0, "HATCH"), (8, "H"), (70, 1),
        (0, "SOLID"), (8, "S"), (62, 1), (10, 0), (20, 4000), (11, 1000), (21, 4000), (12, 0), (22, 5000), (13, 1000), (23, 5000),
        (0, "TRACE"), (8, "S"), (62, 4), (10, 2000), (20, 4000), (11, 3000), (21, 4000), (12, 2500), (22, 5000), (13, 2500), (23, 5000),
        (0, "SOLID"), (8, "S"), (10, 0), (20, 0),
    ]
    sc.write("hatch.dxf", dxf(ents, MM))
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "hatch.dxf", "position": "origin"}), "--save", "hatch.svg",
            "--cmd", cmd("cad_query", {"id": 100002, "at": [1000, 1000]}),
            "--cmd", cmd("cad_query", {"id": 100002, "at": [500, 4500]})])
    sc.file("hatch.svg")
    assert sc.transcript() == sc.golden()


def test_dxf_blocks_arrays_nesting_and_dimensions(sc):
    """CATCHES: an INSERT that ignores its block's base point, its array of columns and rows, a non-uniform scale (a circle
    becoming an ellipse), nesting, inheriting layer 0 and by-block colours, or a DIMENSION not drawing its block; and the
    left-out counts for paper space, undefined blocks, zero scales, blocks nested too deep, and unknown entities."""
    blocks = [
        (0, "BLOCK"), (8, "0"), (2, "MARK"), (70, 0), (10, 100), (20, 100),
        (0, "CIRCLE"), (8, "0"), (62, 0), (10, 100), (20, 100), (40, 100),
        *line((0, 100), (200, 100), "OWN", [(62, 2)]),
        (0, "ENDBLK"),
        (0, "BLOCK"), (8, "0"), (2, "PAIR"), (70, 0), (10, 0), (20, 0),
        (0, "INSERT"), (8, "0"), (2, "MARK"), (10, 0), (20, 0),
        (0, "INSERT"), (8, "0"), (2, "MARK"), (10, 400), (20, 0), (50, 90),
        (0, "ENDBLK"),
        (0, "BLOCK"), (8, "0"), (2, "*D1"), (70, 1), (10, 0), (20, 0),
        *line((0, 0), (3000, 0), "0"),
        (0, "TEXT"), (8, "0"), (10, 1400), (20, 100), (40, 150), (1, "3000"),
        (0, "ENDBLK"),
    ]
    deep = []
    for k in range(18):
        deep += [(0, "BLOCK"), (2, f"N{k}"), (10, 0), (20, 0)]
        deep += [(0, "INSERT"), (8, "0"), (2, f"N{k + 1}"), (10, 10), (20, 0)] if k < 17 else line((0, 0), (50, 50))
        deep += [(0, "ENDBLK")]
    ents = [
        (0, "INSERT"), (8, "RED"), (62, 1), (2, "MARK"), (10, 0), (20, 0), (70, 3), (71, 2), (44, 600), (45, 500),
        (0, "INSERT"), (8, "BLUE"), (62, 5), (2, "PAIR"), (10, 0), (20, 2000), (41, 2), (42, 1),
        (0, "INSERT"), (8, "0"), (2, "MARK"), (10, 0), (20, 4000), (41, 0),
        (0, "INSERT"), (8, "0"), (2, "GHOST"), (10, 0), (20, 0),
        (0, "INSERT"), (8, "0"), (10, 0), (20, 0),
        (0, "INSERT"), (8, "0"), (2, "N0"), (10, 5000), (20, 5000),
        (0, "DIMENSION"), (8, "DIM"), (2, "*D1"), (10, 0), (20, -1000),
        *line((0, 0), (9, 9), "0", [(67, 1)]),
        (0, "VIEWPORT"), (8, "0"),
        (0, "IMAGE"), (8, "0"),
        (0, "IMAGE"), (8, "0"),
    ]
    sc.write("blocks.dxf", dxf(ents, MM, layers(layer("RED", 1), layer("BLUE", 5)), blocks + deep))
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "blocks.dxf"}), "--cmd", cmd("cad_layers", {"id": 100002}),
            "--save", "blocks.svg"])
    sc.file("blocks.svg")
    assert sc.transcript() == sc.golden()


def test_dxf_far_off_entities_and_survey_coordinates(sc):
    """CATCHES: a stray entity far from the rest counted into the extents instead of being reported as far off with a
    warning, or a survey drawing whose origin lies past the model's reach placed by its origin instead of being refused."""
    ents = []
    for k in range(60):
        ents += line((k * 100, 0), (k * 100, 500), "A")
    ents += line((5e8, 5e8), (5e8 + 10, 5e8), "STRAY")
    sc.write("stray.dxf", dxf(ents, MM))
    survey = line((7e9, 9e9), (7e9 + 5000, 9e9), "S") + line((7e9, 9e9), (7e9, 9e9 + 3000), "S")
    sc.write("survey.dxf", dxf(survey, MM))
    sc.cmds(cmd("import_cad", {"path": "stray.dxf"}))
    sc.cmds(cmd("import_cad", {"path": "survey.dxf", "position": "origin"}))
    sc.cmds(cmd("import_cad", {"path": "survey.dxf"}))
    assert sc.transcript() == sc.golden()


def test_dxf_code_pages_and_utf8(sc):
    """CATCHES: a pre-2007 file in a Windows code page or Shift-JIS read as UTF-8 or Latin-1, a page with no decoder not
    falling back to Latin-1, or a UTF-8 byte-order mark breaking the first group code; seen in the layer names."""

    def coded(page, name_bytes):
        head = pairs([(0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1015"), (9, "$DWGCODEPAGE"), (3, page),
                      (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES"), (0, "LINE"), (8, "")]).encode()
        head = head[: -len(b"\n")]  # the layer name's value comes next
        tail = pairs([(10, 0), (20, 0), (11, 100), (21, 0), (0, "ENDSEC"), (0, "EOF")]).encode()
        return head + name_bytes + b"\n" + tail

    sc.write("cp1252.dxf", coded("ANSI_1252", "Paredes é ç".encode("cp1252")))
    sc.write("sjis.dxf", coded("ANSI_932", "壁".encode("shift_jis")))
    sc.write("cp1251.dxf", coded("ANSI_1251", "Стены".encode("cp1251")))
    sc.write("dos.dxf", coded("DOS850", "Mur é".encode("cp850")))
    sc.write("bom.dxf", b"\xef\xbb\xbf" + dxf(line((0, 0), (5, 5), "Wände")).encode())
    for i, name in enumerate(["cp1252.dxf", "sjis.dxf", "cp1251.dxf", "dos.dxf", "bom.dxf"]):
        sc.cmds(cmd("import_cad", {"path": name}), cmd("cad_layers", {"id": 100002}))
    assert sc.transcript() == sc.golden()


def test_dxf_index_colours_of_layers(sc):
    """CATCHES: AutoCAD colour indexes turned into the wrong RGB: the seven named colours, 8 and 9, the hue wheel 10 to
    249 (full and pale, odd and even), the greys 250 to 255, by layer and by block; a layer with no colour is index 7."""
    rows = [layer(f"C{n}", n) for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18, 19, 30, 41, 52, 66, 90,
                                         127, 128, 165, 200, 239, 249, 250, 251, 252, 253, 254, 255]]
    rows.append([(0, "LAYER"), (2, "NOCOLOUR"), (70, 0)])
    ents = line((0, 0), (10, 10), "C1") + line((0, 0), (10, 10), "NOCOLOUR")
    ents += line((0, 0), (5, 5), "C2", [(62, 0)]) + line((0, 0), (6, 6), "C3", [(62, 256)])
    ents += line((0, 0), (7, 7), "C4", [(420, 0xFF8000)])
    sc.write("colours.dxf", dxf(ents, MM, layers(*rows)))
    sc.cmds(
        cmd("import_cad", {"path": "colours.dxf", "position": "origin"}),
        cmd("cad_layers", {"id": 100002}),
        cmd("cad_query", {"id": 100002, "at": [5, 5], "reach": 0.01}),
        cmd("cad_query", {"id": 100002, "at": [6, 6], "reach": 0.01}),
        cmd("cad_query", {"id": 100002, "at": [7, 7], "reach": 0.01}),
        cmd("cad_query", {"id": 100002, "at": [9, 9], "reach": 0.01}),
    )
    assert sc.transcript() == sc.golden()


def test_dxf_insunits_every_other_code(sc):
    """CATCHES: a wrong factor or name for the rarer $INSUNITS codes (miles, km, microinches, mils, yards, angstroms,
    nanometres, microns, decametres, hectometres, light years, parsecs, and codes past the table)."""
    for code in [3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 19, 20, 22, 99]:
        sc.write("d.dxf", dxf(line((0, 0), (100, 50)), [(9, "$INSUNITS"), (70, code)]))
        sc.note(f"--- $INSUNITS {code}")
        sc.cmds(cmd("import_cad", {"path": "d.dxf", "name": f"code {code}"}))
    assert sc.transcript() == sc.golden()


def test_dxf_odd_but_legal_files(sc):
    """CATCHES: a reader that stumbles over what the reference allows: pairs outside any entity, sections it skips, a
    LINE or CIRCLE missing a value, an ARC whose ends meet, an open bulged polyline, a flat ellipse, a spline over several
    knot spans or with too few knots, text and MTEXT aligned every way or of no height, a huge text, by-layer and by-block
    linetypes, colours past 255, a block scaled past what a drawing holds, Latin-1 with no code page, and hatch edges
    that stop short."""
    blocks = [
        (0, "BLOCK"), (2, "B"), (10, 0), (20, 0),
        *line((0, 0), (100, 0), "0", [(6, "BYBLOCK"), (62, 0)]),
        (0, "ARC"), (8, "0"), (10, 0), (20, 0), (40, 50), (50, 0), (51, 180),
        (0, "ENDBLK"),
        (0, "BLOCK"), (2, "FAR"), (10, 0), (20, 0),
        *line((0, 0), (1e7, 0), "0"),
        (0, "ENDBLK"),
    ]
    ents = [
        (999, "a comment between entities"),
        (0, "LINE"), (8, "L"), (10, 0), (20, 0),
        (0, "CIRCLE"), (8, "L"), (10, 0), (20, 0),
        (0, "ARC"), (8, "L"), (10, 1000), (20, 0), (40, 200), (50, 45), (51, 45),
        (0, "LWPOLYLINE"), (8, "L"), (90, 3), (70, 0), (10, 0), (20, 1000), (42, 1), (10, 1000), (20, 1000), (10, 2000), (20, 1500),
        (0, "ELLIPSE"), (8, "L"), (10, 0), (20, 0), (11, 100), (21, 0), (40, 0),
        (0, "SPLINE"), (8, "L"), (71, 3), (40, 0), (40, 0), (40, 0), (40, 0), (40, 0.5), (40, 1), (40, 1), (40, 1), (40, 1),
        (10, 0), (20, 2000), (41, 2), (10, 500), (20, 3000), (10, 1000), (20, 2000), (10, 1500), (20, 3000), (10, 2000), (20, 2000),
        (0, "SPLINE"), (8, "L"), (71, 3), (40, 0), (40, 1), (10, 0), (20, 0), (10, 1, ), (20, 1), (10, 2), (20, 0), (10, 3), (20, 1),
        (0, "SPLINE"), (8, "L"), (71, 2),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4000), (11, 100), (21, 4000), (40, 100), (72, 0), (73, 1), (1, "bottom left"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4200), (11, 100), (21, 4200), (40, 100), (72, 1), (73, 0), (1, "centre baseline"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4400), (11, 900), (21, 4400), (40, 100), (72, 5), (1, "fit"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4600), (11, 900), (21, 4600), (40, 100), (72, 7), (73, 2), (1, "odd code"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 4800), (40, 100), (1, "%%x %%" ),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 5000), (40, 100), (1, "\\U+ZZZZ \\{x\\} \\\\ \\Lunder\\l \\Xodd \\"),
        (0, "TEXT"), (8, "T"), (10, 0), (20, 5200), (40, 10), (1, "W" * 5000),
        (0, "MTEXT"), (8, "T"), (10, 0), (20, 6000), (40, 0), (1, "no height"),
        (0, "MTEXT"), (8, "T"), (10, 0), (20, 6000), (40, 100), (1, "\\P\\P"),
        (0, "MTEXT"), (8, "T"), (10, 0), (20, 6000), (40, 100), (71, 1), (1, "top left"),
        (0, "MTEXT"), (8, "T"), (10, 0), (20, 6500), (40, 100), (71, 4), (1, "middle left\\Ptwo"),
        (0, "MTEXT"), (8, "T"), (10, 0), (20, 7000), (40, 100), (71, 7), (50, 90), (1, "bottom left"),
        *line((0, 8000), (500, 8000), "BYL", [(6, "BYLAYER"), (62, 300)]),
        (0, "INSERT"), (8, "BL"), (6, "DASHED"), (62, 3), (2, "B"), (10, 3000), (20, 0), (41, 2), (42, 1),
        (0, "INSERT"), (8, "BL"), (2, "FAR"), (10, 0), (20, 0), (41, 1e6), (42, 1e6),
        (0, "TEXT"), (8, "LATIN"), (10, 0), (20, 9000), (40, 100), (1, "café"),
        (0, "HATCH"), (8, "H"), (70, 1), (91, 4),
        (92, 1), (93, 2), (72, 1), (10, 0), (20, 0), (11, 100), (21, 0), (72, 1), (10, 100),
        (92, 1), (93, 1), (72, 2), (10, 0), (20, 0),
        (92, 1), (93, 1), (72, 3), (10, 0), (20, 0), (11, 1), (21, 0),
        (92, 1), (93, 1), (72, 4), (94, 2), (73, 1), (74, 0), (95, 6), (96, 3), (40, 0), (40, 0), (40, 0), (40, 1), (40, 1), (40, 1),
        (10, 0), (20, 0), (42, 1), (10, 50), (20, 100), (42, 2), (10, 100), (20, 0), (42, 1), (97, 2), (11, 0), (21, 0), (11, 100),
        (0, "HATCH"), (8, "H"), (70, 1), (91, 1), (92, 1), (93, 1), (72, 4), (94, 3), (95, 2), (96, 0), (40, 0), (40, 1),
        (97, 3), (11, 0), (21, 0), (11, 50), (21, 80), (11, 100), (21, 0),
    ]
    text = pairs([(1, "loose pair before any section"), (0, "SECTION"), (2, "CLASSES"), (0, "CLASS"), (1, "X"), (0, "ENDSEC"),
                  (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, 4), (0, "ENDSEC"), (0, "UNKNOWN"),
                  (0, "SECTION"), (2, "TABLES"), (5, "1F"), (0, "TABLE"), (2, "LAYER"), (0, "LAYER"), (2, "BYL"), (62, 6),
                  (0, "ENDTAB"), (0, "ENDSEC"),
                  (0, "SECTION"), (2, "BLOCKS"), (5, "20"), *blocks, (0, "ENDSEC"),
                  (0, "SECTION"), (2, "ENTITIES"), (5, "21"), *ents, (0, "ENDSEC"), (0, "EOF")])
    sc.write("odd.dxf", text.encode("latin-1"))
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "odd.dxf"}), "--cmd", cmd("cad_layers", {"id": 100002}),
            "--save", "odd.svg"])
    sc.file("odd.svg", digest=True)
    assert sc.transcript() == sc.golden()


def test_dxf_limits_on_shapes_and_block_work(sc):
    """CATCHES: a reader with no cap on what blocks multiply into: an array of a block of paper-space lines past the work it
    allows, and of drawn lines past the shapes it keeps, must each be refused with the limit named."""
    work = [(0, "BLOCK"), (2, "PAPER"), (10, 0), (20, 0), *line((0, 0), (1, 0), "0", [(67, 1)]), (0, "ENDBLK")]
    sc.write("work.dxf", dxf([(0, "INSERT"), (8, "0"), (2, "PAPER"), (10, 0), (20, 0), (70, 3000), (71, 3000), (44, 1), (45, 1)],
                             MM, (), work))
    shapes = [(0, "BLOCK"), (2, "DOT"), (10, 0), (20, 0), (0, "POINT"), (8, "0"), (10, 0), (20, 0), (0, "ENDBLK")]
    sc.write("shapes.dxf", dxf([(0, "INSERT"), (8, "0"), (2, "DOT"), (10, 0), (20, 0), (70, 1001), (71, 1000), (44, 1), (45, 1)],
                               MM, (), shapes))
    sc.cmds(cmd("import_cad", {"path": "work.dxf"}))
    sc.cmds(cmd("import_cad", {"path": "shapes.dxf"}))
    assert sc.transcript() == sc.golden()


def test_cad_layers_hide_and_show_everywhere_or_in_one_view(sc):
    """CATCHES: cad_layers that doesn't hide or show layers in every view, mixes a view's own hiding into every view, lets a
    layer be both hidden and shown, accepts a layer the drawing hasn't, or doesn't report `shown_in_view` for a view."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("import_cad", {"path": "plan.dxf"}),
        cmd("cad_layers", {"id": 100002, "hide": ["WALLS"], "show": ["HIDDEN"]}),
        cmd("cad_layers", {"id": 100002, "view": "Level 1", "hide": ["TRUE", "0"]}),
        cmd("cad_layers", {"id": 100002, "view": "Level 1", "show": ["0"]}),
        cmd("cad_layers", {"id": 100002}),
        cmd("graphics", {"view": "Level 1"}),
        post=["--save", "plan.svg"],
    )
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("cad_layers", {"id": 100002, "hide": ["WALLS"], "show": ["WALLS"]}))
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("cad_layers", {"id": 100002, "hide": ["NOPE"]}))
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("cad_layers", {"id": 100001}))
    sc.cmds(cmd("cad_layers", {}))
    sc.cmds(cmd("cad_layers", {"id": 999}))
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_cad_query_names_the_nearest_entity(sc):
    """CATCHES: a query that doesn't find the nearest entity within `reach`, gives the wrong kind, layer, colour, linetype
    (its own or its layer's) or weight, or the distance unrounded; and `reach` not above 0 accepted."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("import_cad", {"path": "plan.dxf", "position": "origin", "layers": "all"}),
        cmd("cad_query", {"id": 100002, "at": [5000, 30]}),
        cmd("cad_query", {"id": 100002, "at": [5000, 1530]}),
        cmd("cad_query", {"id": 100002, "at": [2354, 2354]}),
        cmd("cad_query", {"id": 100002, "at": [150, 150]}),
        cmd("cad_query", {"id": 100002, "at": [7000, 7040]}),
        cmd("cad_query", {"id": 100002, "at": [3000, 3050]}),
        cmd("cad_query", {"id": 100002, "at": [5000, 300], "reach": 50}),
        cmd("cad_query", {"id": 100002, "at": [5000, 300], "reach": 400}),
        cmd("cad_query", {"id": 100002, "at": [10900, 2500]}),
    )
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("cad_query", {"id": 100002, "at": [0, 0], "reach": 0}))
    sc.cmds(cmd("cad_query", {"id": 100000, "at": [0, 0]}))
    assert sc.transcript() == sc.golden()


def test_reload_cad_reads_a_linked_file_again(sc):
    """CATCHES: reload_cad that rereads a file that hasn't changed as changed, misses a change, reloads a drawing that isn't
    linked, or accepts a drawing the project hasn't; a relative link is read beside the project's file once it has one, and
    a linked file that is gone is reported."""
    sc.write("site.dxf", dxf(line((0, 0), (1000, 0)), MM))
    sc.write("other/site.dxf", dxf(line((0, 0), (1000, 0)) + line((0, 0), (0, 1000)) + line((0, 1000), (1000, 1000)), MM))
    sc.cmds(
        cmd("import_cad", {"path": "site.dxf", "link": True}),
        cmd("reload_cad", {"cad": "site"}),
        cmd("save", {"path": "other/p.bimcraft"}),
        cmd("reload_cad", {"cad": "site"}),
        cmd("reload_cad", {"cad": "site"}),
        cmd("elements", {"category": "cadimport"}),
    )
    sc.cmds(cmd("import_cad", {"path": "site.dxf", "name": "copy"}), cmd("reload_cad", {"cad": "copy"}))
    sc.cmds(cmd("reload_cad", {"cad": "nothing"}))
    sc.cmds(cmd("reload_cad", {}))
    sc.write("other/site.dxf", "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")
    sc.cmds(cmd("reload_cad", {"cad": "site"}), pre=["other/p.bimcraft"])
    (sc.workdir / "other/site.dxf").unlink()
    sc.cmds(cmd("reload_cad", {"cad": "site"}), pre=["other/p.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_opening_a_project_reads_its_linked_drawings_again(sc):
    """CATCHES: open that doesn't reread a linked drawing whose file changed, or doesn't name in `cads_not_reloaded` one whose
    file is gone (keeping what the project held of it); a relative link is kept as given and read beside the project's file."""
    (sc.workdir / "proj").mkdir()
    sc.write("proj/site.dxf", dxf(line((0, 0), (2000, 0)), MM))
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "site.dxf", "link": True}), "--save", "p.bimcraft"],
           cwd=sc.workdir / "proj")
    sc.run(["run", "proj/p.bimcraft", "--cmd", cmd("elements", {"category": "cadimport"})])
    sc.write("proj/site.dxf", dxf(line((0, 0), (2000, 0)) + line((0, 0), (0, 3000)), MM))
    sc.run(["run", "proj/p.bimcraft", "--cmd", cmd("elements", {"category": "cadimport"}), "--save", "proj/again.bimcraft"])
    (sc.workdir / "proj/site.dxf").unlink()
    sc.run(["run", "proj/again.bimcraft", "--cmd", cmd("elements", {"category": "cadimport"})])
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "proj/site.dxf", "link": True})])
    assert sc.transcript() == sc.golden()


def test_a_drawing_held_by_a_project_survives_save_and_open_and_places_again(sc):
    """CATCHES: a project file that loses an import's drawing, layers hidden or colours, or a `cad` placement that copies
    the wrong drawing; and a drawing nothing places any more not being dropped (and brought back by undo)."""
    sc.write("plan.dxf", plan_dxf())
    sc.run(["run", "--cmd", cmd("import_cad", {"path": "plan.dxf", "colors": "invert"}),
            "--cmd", cmd("cad_layers", {"id": 100002, "hide": ["TRUE"]}), "--save", "p.bimcraft"])
    (sc.workdir / "plan.dxf").unlink()
    sc.cmds(
        cmd("cad_layers", {"id": 100002}),
        cmd("import_cad", {"cad": "plan", "at": [0, 15000], "angle": 180}),
        cmd("elements", {"category": "cadimport"}),
        cmd("delete", {"ids": [100002, 100003]}),
        cmd("import_cad", {"cad": "plan"}),
        pre=["p.bimcraft"],
    )
    sc.cmds(
        cmd("delete", {"ids": [100002]}),
        cmd("undo", {}),
        cmd("import_cad", {"cad": "plan", "name": "ignored"}),
        pre=["p.bimcraft"],
    )
    project_part(sc, "p.bimcraft", "cads")
    assert sc.transcript() == sc.golden()


def test_an_import_moves_turns_copies_and_modifies_but_never_mirrors(sc):
    """CATCHES: move, rotate or copy not taking an import as an element, mirror not being refused, or modify not changing
    its level, at, angle, scale and colors (and refusing a scale out of range)."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("import_cad", {"path": "plan.dxf"}),
        cmd("move", {"ids": [100002], "by": [1000, 2000]}),
        cmd("rotate", {"ids": [100002], "about": [0, 0], "angle": 90}),
        cmd("copy", {"ids": [100002], "by": [0, 20000]}),
        cmd("modify", {"id": 100003, "scale": 2, "colors": "black", "level": "Level 2", "at": [5, 5], "angle": 10}),
        cmd("elements", {"category": "cadimport"}),
    )
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("mirror", {"ids": [100002], "axis": [[0, 0], [0, 1000]]}))
    sc.cmds(cmd("import_cad", {"path": "plan.dxf"}), cmd("modify", {"id": 100002, "scale": -1}))
    assert sc.transcript() == sc.golden()


def test_an_import_in_one_view_only(sc):
    """CATCHES: `view` not limiting an import to that plan, a view of another level than `level` accepted, or a view that
    isn't a plan accepted."""
    sc.write("plan.dxf", plan_dxf())
    sc.cmds(
        cmd("duplicate_view", {"view": "Level 1", "name": "Tracing"}),
        cmd("import_cad", {"path": "plan.dxf", "view": "Tracing"}),
        cmd("elements", {"category": "cadimport"}),
        post=["--save", "plan.svg"],
    )
    sc.cmds(cmd("import_cad", {"path": "plan.dxf", "view": "Level 1", "level": "Level 2"}))
    sc.cmds(cmd("import_cad", {"path": "plan.dxf", "view": "{3D}"}))
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_dwg_is_read_as_the_dxf_it_becomes(sc):
    """CATCHES: a DWG not being read (in metres, its layers' colours, its entities), or a file that isn't a DWG, or one that
    is missing, not refused with the reason."""
    copy_resource(sc, "room.dwg")
    sc.write("fake.dwg", b"AC1018 but not really a drawing at all")
    sc.write("text.dwg", b"hello")
    sc.cmds(cmd("import_cad", {"path": "room.dwg"}), cmd("cad_layers", {"id": 100002}),
            cmd("cad_query", {"id": 100002, "at": [0, 0], "reach": 300}), post=["--save", "room.svg"])
    sc.cmds(cmd("import_cad", {"path": "fake.dwg"}))
    sc.cmds(cmd("import_cad", {"path": "text.dwg"}))
    sc.cmds(cmd("import_cad", {"path": "gone.dwg"}))
    data = (RES / "room.dwg").read_bytes()
    for at, value, name in [(848, 0, "skipped.dwg"), (6694, 255, "objects.dwg"), (7249, 255, "pages.dwg")]:
        damaged = bytearray(data)
        damaged[at] = value
        sc.write(name, bytes(damaged))
        sc.cmds(cmd("import_cad", {"path": name}))
    sc.file("room.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Point clouds
# ---------------------------------------------------------------------------

PTS = "4\n0 0 0 10 255 0 0\n1 0 0 20 0 255 0\n1 2 0.5 30 0 0 255\n0.5 1 0.25 40 128 128 128\n"


def test_pts_scan_comes_in_with_its_middle_and_foot(sc):
    """CATCHES: a PTS reader that takes the count line for a point, misreads intensity and colour columns, or a placement
    that doesn't put the scan's middle on the origin and its foot on the level; or an element listing that loses them."""
    sc.write("room.pts", PTS)
    sc.cmds(cmd("point_cloud", {"path": "room.pts"}), cmd("elements", {"category": "pointcloud"}), post=["--save", "p.bimcraft"])
    project_part(sc, "p.bimcraft", "clouds")
    (sc.workdir / "room.pts").unlink()
    sc.cmds(cmd("elements", {"category": "pointcloud"}), cmd("point_cloud", {"cloud": "room", "at": [5000, 0]}),
            pre=["p.bimcraft"], post=["--save", "again.bimcraft"])
    project_part(sc, "again.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


def test_xyz_text_columns_separators_and_comments(sc):
    """CATCHES: an XYZ reader that doesn't take spaces, tabs and commas alike, chokes on # and // comments or blank lines,
    or reads six columns as anything but x y z r g b; and a .txt not read as XYZ."""
    sc.write("a.xyz", "# x y z\n// a comment\n\n0,0,0\n1000\t0\t0\n0 1000 500\n")
    sc.write("b.txt", "0 0 0 255 255 255\n2 0 0 0 0 0\n0 3 1 0.5 0.5 0.5\n")
    sc.cmds(
        cmd("point_cloud", {"path": "a.xyz", "units": "mm"}),
        cmd("point_cloud", {"path": "b.txt", "name": "six columns", "at": [10000, 0]}),
        cmd("elements", {"category": "pointcloud"}),
        post=["--save", "p.bimcraft"],
    )
    project_part(sc, "p.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


def test_ply_text_and_both_byte_orders_read_the_same(sc):
    """CATCHES: a PLY reader that misses the vertex properties' order (a normal between position and colour), the CRLF
    after `ply`, the elements after the vertices, or one byte order; the three files must give the same scan."""
    pts = [([0.0, 0.0, 0.0], [255, 0, 0]), ([2.0, 0.0, 0.0], [0, 255, 0]), ([2.0, 1.0, 0.5], [0, 0, 255])]
    for form in ["ascii", "binary_little_endian", "binary_big_endian"]:
        sc.write(f"{form}.ply", ply_bytes(form, pts))
        sc.cmds(cmd("point_cloud", {"path": f"{form}.ply"}), post=["--save", f"{form}.bimcraft"])
        project_part(sc, f"{form}.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


def test_ply_headers_of_other_shapes(sc):
    """CATCHES: a PLY reader that needs `red` rather than `diffuse_red` or float colours from nought to one, misses an
    intensity, can't step over an element before the vertices, or accepts a header PLY doesn't have."""
    head = "ply\nformat ascii 1.0\n"
    sc.write("diffuse.ply", head + "element camera 1\nproperty float a\nelement vertex 2\nproperty double x\nproperty double y\n"
             "property double z\nproperty float diffuse_red\nproperty float diffuse_green\nproperty float diffuse_blue\nend_header\n"
             "7\n0 0 0 1 0.5 0\n1 1 1 0 0.25 1\n")
    sc.write("intensity.ply", head + "obj_info scanner\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
             "property ushort intensity\nend_header\n0 0 0 100\n1 0 0 200\n0 1 0 300\n")
    binary = ("ply\nformat binary_little_endian 1.0\nelement camera 1\nproperty uchar a\nproperty short b\nelement vertex 2\n"
              "property int x\nproperty uint y\nproperty char z\nproperty int16 nx\nproperty uint8 red\nproperty uint8 green\n"
              "property uint8 blue\nend_header\n").encode()
    binary += bytes([9]) + struct.pack("<h", -3)
    binary += struct.pack("<iIbhBBB", 1, 2, -3, 7, 10, 20, 30) + struct.pack("<iIbhBBB", -1, 0, 3, 7, 40, 50, 60)
    sc.write("binary.ply", binary)
    for name in ["diffuse.ply", "intensity.ply", "binary.ply"]:
        sc.cmds(cmd("point_cloud", {"path": name}), post=["--save", "p.bimcraft"])
        project_part(sc, "p.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("minor,fmt", [(2, 0), (2, 1), (2, 2), (3, 3), (4, 6), (4, 7)])
def test_las_formats_scale_and_offset(sc, minor, fmt):
    """CATCHES: a LAS reader that ignores the header's scale and offset or the gap before the points, reads the 64-bit
    count of LAS 1.4, misplaces a format's colour, or doesn't grey intensity when there is no colour."""
    pts = [([0, 0, 0], 100, [65535, 0, 0]), ([1000, 0, 0], 200, [0, 65535, 0]), ([1000, 2000, 500], 300, [0, 0, 65535])]
    sc.write("scan.las", las_bytes(minor, fmt, [0.001, 0.001, 0.001], [100.0, 200.0, 10.0], pts, gap=12))
    sc.cmds(cmd("point_cloud", {"path": "scan.las"}), post=["--save", "p.bimcraft"])
    project_part(sc, "p.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


def test_e57_scans_with_colour_pose_spherical_and_scaled_integers(sc):
    """CATCHES: an E57 reader that doesn't follow pages and packets, doesn't place each scan by its pose, misreads scaled
    integers, spherical coordinates, invalid points or colour limits, or counts `read` other than the record counts."""
    pts = grid_points(500)
    fields = e57_cartesian(pts)
    for k, n in enumerate(["colorRed", "colorGreen", "colorBlue"]):
        fields.append(e57_int(n, 0, 255, [(i * (k + 3)) % 256 for i in range(len(pts))]))
    h = math.sqrt(0.5)
    pose = (
        f'<pose type="Structure"><rotation type="Structure"><w type="Float">{h}</w><x type="Float">0</x><y type="Float">0</y>'
        f'<z type="Float">{h}</z></rotation><translation type="Structure"><x type="Float">10</x><y type="Float">0</y>'
        '<z type="Float">2</z></translation></pose>'
    )
    turned = {"fields": e57_cartesian([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), "more": pose}
    scaled = {"fields": [
        e57_int("cartesianX", -1000, 2000, [0.0, 1.234, -0.5], 0.001),
        e57_int("cartesianY", 0, 5, [10.0, 11.5, 12.5], 0.5, 10.0),
        e57_float("cartesianZ", [0.25, 0.5, 0.75], single=False),
        e57_float("intensity", [0.0, 0.5, 1.0], single=False),
        e57_int("cartesianInvalidState", 0, 2, [0, 0, 2]),
    ]}
    q = math.pi / 2
    spherical = {"fields": [
        e57_float("sphericalRange", [2.0, 1.0], single=False),
        e57_float("sphericalAzimuth", [q, 0.0], single=False),
        e57_float("sphericalElevation", [0.0, q], single=False),
    ]}
    limits = '<colorLimits type="Structure"><colorRedMinimum type="Integer">0</colorRedMinimum>' \
             '<colorRedMaximum type="Integer">65535</colorRedMaximum></colorLimits>'
    deep = {"fields": e57_cartesian([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
            + [e57_int(n, 0, 65535, [65535, 0]) for n in ["colorRed", "colorGreen", "colorBlue"]], "more": limits}
    sc.write("colour.e57", e57_bytes([{"fields": fields}]))
    sc.write("survey.e57", e57_bytes([turned, scaled, spherical]))
    sc.write("limits.e57", e57_bytes([deep]))
    for name in ["colour.e57", "survey.e57", "limits.e57"]:
        sc.cmds(cmd("point_cloud", {"path": name, "origin": "file"}), post=["--save", "p.bimcraft"])
        project_part(sc, "p.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


def test_e57_files_that_cannot_be_read_say_why(sc):
    """CATCHES: an E57 reader that accepts or crashes on a file that isn't E57, of another version, cut short, with an
    unknown codec, with more records than its section holds, with broken XML, or with a field type E57 doesn't pack."""
    good = e57_bytes([{"fields": e57_cartesian(grid_points(300))}])

    def rewritten(old, new):
        return e57_bytes([{"fields": e57_cartesian(grid_points(300))}], lambda xml: xml.replace(old, new))

    v2 = bytearray(good)
    v2[8] = 2
    cases = {
        "not.e57": b"not an e57 at all",
        "short.e57": good[:40],
        "half.e57": good[: len(good) // 2],
        "v2.e57": bytes(v2),
        "codec.e57": rewritten('"1"></codecs>', '"1"><x/></codecs>'),
        "count.e57": rewritten('recordCount="300"', 'recordCount="900"'),
        "missing.e57": rewritten('recordCount="300"', 'recordCount="301"'),
        "xml.e57": rewritten("<data3D", "<data3X"),
        "string.e57": rewritten('type="Float" precision', 'type="String" precision'),
        "empty.e57": e57_bytes([{"fields": e57_cartesian([])}]),
        "nopoints.e57": rewritten("points", "dots"),
        "notvector.e57": rewritten('type="CompressedVector"', 'type="Vector"'),
        "nooffset.e57": rewritten(' fileOffset="', ' at="'),
        "nocount.e57": rewritten(' recordCount="', ' n="'),
        "noproto.e57": rewritten("prototype", "proto"),
        "nocoords.e57": rewritten("cartesianX", "otherX"),
        "badpose.e57": e57_bytes([{"fields": e57_cartesian([[0.0, 0.0, 0.0]]),
                                   "more": '<pose type="Structure"><rotation type="Structure"><w type="Float">0</w>'
                                           '</rotation></pose>'}]),
        "badtype.e57": rewritten('type="Float" precision="single"/><cartesianY', 'type="Mystery"/><cartesianY'),
    }
    for name, body in cases.items():
        sc.write(name, body)
        sc.cmds(cmd("point_cloud", {"path": name}))
    assert sc.transcript() == sc.golden()


def test_point_cloud_units_spacing_origin_at_offset_angle_and_level(sc):
    """CATCHES: `units` not scaling the file's coordinates, `spacing` not keeping one point per cube, `origin: file` not
    placing the scan where its coordinates say (over the level's elevation), or `at`, `offset`, `angle` and `level`
    ignored."""
    rows = [f"{x * 0.1} {y * 0.1} {z * 0.1}" for x in range(10) for y in range(10) for z in range(3)]
    sc.write("cube.xyz", "\n".join(rows) + "\n")
    sc.cmds(
        cmd("point_cloud", {"path": "cube.xyz"}),
        cmd("point_cloud", {"path": "cube.xyz", "name": "cm", "units": "cm"}),
        cmd("point_cloud", {"path": "cube.xyz", "name": "ft", "units": "ft"}),
        cmd("point_cloud", {"path": "cube.xyz", "name": "in", "units": "in"}),
        cmd("point_cloud", {"path": "cube.xyz", "name": "thin", "spacing": 250}),
        cmd("point_cloud", {"path": "cube.xyz", "name": "file", "origin": "file", "level": "Level 2"}),
        cmd("point_cloud", {"path": "cube.xyz", "name": "placed", "at": [5000, -2000], "offset": 1200, "angle": 30,
                            "origin": "centre"}),
        cmd("elements", {"category": "pointcloud"}),
    )
    assert sc.transcript() == sc.golden()


def test_point_cloud_placed_again_moved_copied_and_removed(sc):
    """CATCHES: `cloud` not placing a held scan again, a scan not dropped once nothing places it (and back with undo), a
    copy or a move not taking a point cloud as an element, mirror not refused, or the scan's name not checked."""
    sc.write("room.pts", PTS)
    sc.cmds(
        cmd("point_cloud", {"path": "room.pts"}),
        cmd("point_cloud", {"cloud": "room", "at": [3000, 0], "angle": 90}),
        cmd("copy", {"ids": [100003], "by": [0, 3000]}),
        cmd("move", {"ids": [100002], "by": [-1000, 0]}),
        cmd("rotate", {"ids": [100002], "about": [0, 0], "angle": 45}),
        cmd("elements", {"category": "pointcloud"}),
        cmd("delete", {"ids": [100002, 100003, 100004]}),
        cmd("library", {"kind": "cloud"}),
        cmd("undo", {}),
        cmd("library", {"kind": "cloud"}),
    )
    sc.cmds(cmd("point_cloud", {"path": "room.pts"}), cmd("mirror", {"ids": [100002], "axis": [[0, 0], [0, 1000]]}))
    sc.cmds(cmd("point_cloud", {"path": "room.pts"}), cmd("point_cloud", {"path": "room.pts"}))
    sc.cmds(cmd("point_cloud", {"cloud": "room"}))
    sc.cmds(cmd("point_cloud", {"path": "room.pts"}), cmd("point_cloud", {"cloud": "nothing"}))
    assert sc.transcript() == sc.golden()


def test_survey_stations_come_in_as_one_scan(sc):
    """CATCHES: a list of station files not merged into one scan about the middle of them all, overlapping points kept twice
    under `spacing`, a file without colour among coloured ones not greyed, or the stations not listed on the element."""
    sc.write("north.pts", "0 0 0 1 255 0 0\n1 0 0 1 255 0 0\n")
    sc.write("south.xyz", "1 0 0\n3 0 0\n3 1 0\n")
    sc.write("east.las", las_bytes(2, 2, [0.01, 0.01, 0.01], [0, 0, 0], [([300, 100, 0], 5, [0, 0, 65535])]))
    sc.cmds(
        cmd("point_cloud", {"path": ["north.pts", "south.xyz", "east.las"], "spacing": 100}),
        cmd("point_cloud", {"path": ["north.pts"], "name": "one"}),
        cmd("elements", {"category": "pointcloud"}),
        post=["--save", "p.bimcraft"],
    )
    project_part(sc, "p.bimcraft", "clouds")
    assert sc.transcript() == sc.golden()


def test_point_cloud_parameter_and_file_errors(sc):
    """CATCHES: point_cloud accepting what it must refuse with a reason: neither path nor cloud, both, an empty or bad list,
    a bad unit, origin or spacing, a missing file, LAZ, RCP, an unknown extension, a file with no points, bad numbers or
    columns, broken PLY and LAS headers, a scan too wide, a file origin past the model's reach."""
    sc.write("ok.xyz", "0 0 0\n1 1 1\n")
    files = {
        "scan.laz": b"LASF",
        "scan.rcp": b"x",
        "scan.obj": b"v 0 0 0",
        "empty.xyz": "# nothing\n",
        "word.xyz": "0 0 zero\n",
        "nan.xyz": "0 0 NaN\n",
        "five.xyz": "0 0 0 1 2\n",
        "binary.pts": b"0 0 \xff\n",
        "noply.ply": "not a ply",
        "noend.ply": "ply\nformat ascii 1.0\nelement vertex 1\n",
        "noformat.ply": "ply\nelement vertex 1\nproperty float x\nend_header\n0\n",
        "form.ply": "ply\nformat utf8 1.0\nelement vertex 0\nend_header\n",
        "type.ply": "ply\nformat ascii 1.0\nelement vertex 1\nproperty quad x\nend_header\n",
        "novertex.ply": "ply\nformat ascii 1.0\nelement face 0\nend_header\n",
        "noz.ply": "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nend_header\n0 0\n",
        "list.ply": "ply\nformat ascii 1.0\nelement vertex 1\nproperty list uchar int idx\nend_header\n",
        "cut.ply": "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n",
        "cutbin.ply": "ply\nformat binary_little_endian 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n",
        "orphan.ply": "ply\nformat ascii 1.0\nproperty float x\nend_header\n",
        "count.ply": "ply\nformat ascii 1.0\nelement vertex many\nend_header\n",
        "bad.ply": "ply\nformat ascii 1.0\nwhat is this\nend_header\n",
        "nolasf.las": b"PK" + bytes(300),
        "shortlas.las": b"LASF" + bytes(100),
        "las20.las": las_bytes(2, 0, [1, 1, 1], [0, 0, 0], [([0, 0, 0], 0, [0, 0, 0])])[:24] + b"\x02\x00"
        + las_bytes(2, 0, [1, 1, 1], [0, 0, 0], [([0, 0, 0], 0, [0, 0, 0])])[26:],
        "zeroscale.las": las_bytes(2, 0, [0, 1, 1], [0, 0, 0], [([0, 0, 0], 0, [0, 0, 0])]),
        "cutlas.las": las_bytes(2, 1, [1, 1, 1], [0, 0, 0], [([0, 0, 0], 0, [0, 0, 0])] * 3)[:-10],
        "wide.xyz": "0 0 0\n30000 0 0\n",
    }
    laz = bytearray(las_bytes(2, 0, [1, 1, 1], [0, 0, 0], [([0, 0, 0], 0, [0, 0, 0])]))
    laz[104] = 0x80
    files["laz.las"] = bytes(laz)
    fmt = bytearray(laz)
    fmt[104] = 11
    files["fmt.las"] = bytes(fmt)
    for name, body in files.items():
        sc.write(name, body)
    for params in [
        {},
        {"path": "ok.xyz", "cloud": "x"},
        {"path": []},
        {"path": [1]},
        {"path": 5},
        {"path": "ok.xyz", "units": "yards"},
        {"path": "ok.xyz", "origin": "corner"},
        {"path": "ok.xyz", "spacing": -1},
        {"path": "ok.xyz", "name": " "},
        {"path": "missing.xyz"},
        {"path": "far.xyz", "origin": "file"},
        *({"path": n} for n in files),
    ]:
        if params.get("path") == "far.xyz":
            sc.write("far.xyz", "2000000 0 0\n2000001 0 0\n")
        sc.cmds(cmd("point_cloud", params))
    assert sc.transcript() == sc.golden()


def test_point_cloud_drawn_in_plan_and_3d(sc):
    """CATCHES: a plan that leaves a scan out or draws it in other colours or sizes (the SVG holds its dots as a PNG), a
    3D view that doesn't draw its points, or a reflected ceiling plan that draws them."""
    rows = [f"{x * 0.2} {y * 0.2} {z * 0.5} {x * 20} {y * 20} 100" for x in range(12) for y in range(10) for z in range(3)]
    sc.write("box.xyz", "\n".join(rows) + "\n")
    sc.cmds(
        cmd("point_cloud", {"path": "box.xyz"}),
        cmd("render", {"view": "{3D}", "path": "3d.png", "width": 400, "height": 300}),
        cmd("render", {"view": "Level 1", "ceiling": True, "path": "rcp.png", "width": 400, "height": 300}),
        cmd("graphics", {"view": "Level 1", "categories": {"pointcloud": {"projection": {"fill": [200, 0, 40]}}}}),
        cmd("render", {"view": "Level 1", "path": "red.png", "width": 400, "height": 300}),
        post=["--save", "plan.svg"],
    )
    sc.file("plan.svg")
    sc.file("3d.png")
    sc.file("rcp.png")
    sc.file("red.png")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Revit files (synthetic, written by the reader's own fixture writer: see test_resources/test_imports/PROVENANCE.md)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["house2024.rvt", "house2019.rvt", "levels.rvt", "office.rvt", "bare.rvt", "damaged.rvt"])
def test_revit_info_shows_release_save_levels_and_categories(sc, name):
    """CATCHES: info that misreads a Revit file's release, build, document GUID, locale or worksharing, its Atom entry's
    title and date, the user name and the path of its last save, its levels (feet to millimetres, building story
    settings, those inside families), or its element counts by category, placed or not, and their names."""
    copy_resource(sc, name)
    sc.run(["info", name])
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", ["chair.rfa", "template.rft"])
def test_revit_info_of_a_family_or_template_without_elements(sc, name):
    """CATCHES: info refusing a family or a template that has no partition instead of showing its metadata (the 2017 build
    line, an Atom entry's OmniClass) and saying why it has no elements."""
    copy_resource(sc, name)
    sc.run(["info", name])
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", ["house2024.rvt", "house2019.rvt", "house2026.rvt"])
def test_revit_run_imports_a_house_of_every_kind_of_element(sc, name):
    """CATCHES: an import that drops or misplaces walls, a door and a window in their wall, a floor with its hole, a
    ceiling, a flat roof, a room, columns, pipes, ducts and a cable tray, boxes of other categories, or whose notes of
    what it left out and why are not the same in each record form (2019's narrow ids, 2024's and 2026's wide ones)."""
    copy_resource(sc, name)
    sc.cmds(cmd("elements", {}), pre=[name])
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", ["curved2023.rvt", "gable.rvt", "column.rvt", "levels.rvt", "bare.rvt", "office.rvt", "wall.rvt"])
def test_revit_run_imports_curves_extrusions_turned_columns_and_levels(sc, name):
    """CATCHES: an import that loses a wall's arc or its flip, a roof by extrusion's profile, a turned column's angle and
    size, levels that share a name, or doesn't give a file with no levels one at zero."""
    copy_resource(sc, name)
    sc.cmds(cmd("elements", {}), pre=[name])
    assert sc.transcript() == sc.golden()


def test_revit_convert_to_a_project_and_ifc_and_open_again(sc):
    """CATCHES: convert that doesn't write what the import made as a project (which opens again with the same counts) or as
    IFC4 with its walls, openings, slabs and storeys; and the saver's name or the path of the last save leaking into
    either."""
    copy_resource(sc, "office.rvt")
    copy_resource(sc, "house2024.rvt")
    sc.run(["convert", "house2024.rvt", "house.bimcraft"])
    sc.run(["convert", "house2024.rvt", "house.ifc"])
    sc.run(["convert", "office.rvt", "office.bimcraft"])
    sc.run(["run", "house.bimcraft", "--cmd", "inspect {}"], show=False)
    p = sc.run(["info", "house.bimcraft"], show=False)
    sc.note("info counts: " + json.dumps(json.loads(p.stdout)["counts"], sort_keys=True))
    sc.file("house.ifc")
    office = (sc.workdir / "office.bimcraft").read_text(encoding="utf-8")
    sc.note(f"office.bimcraft names jdoe: {'jdoe' in office}; names the saved path: {'Projects' in office}")
    project_part(sc, "office.bimcraft", "name")
    assert sc.transcript() == sc.golden()


def test_revit_run_then_save_plan_and_3d(sc):
    """CATCHES: an imported project that doesn't draw its plan (walls, door swing, window, room, column, runs) or 3D view as
    a project built by commands would."""
    copy_resource(sc, "house2024.rvt")
    sc.run(["run", "house2024.rvt", "--cmd", cmd("render", {"view": "{3D}", "path": "3d.png", "width": 480, "height": 320}),
            "--save", "plan.svg", "--save", "plan.png"])
    sc.file("plan.svg", digest=True)
    sc.file("plan.png")
    sc.file("3d.png")
    assert sc.transcript() == sc.golden()


def test_revit_files_that_cannot_be_read_say_why(sc):
    """CATCHES: a reader that accepts or crashes on a file that isn't a Compound File, a family with no partition given to
    run or convert, a missing file, or any of the four Revit extensions (rvt, rfa, rte, rft) not taken for a Revit file;
    and convert writing a file when the read failed."""
    sc.write("fake.rvt", b"this is not a Revit file at all")
    sc.write("fake.rte", b"not a template either")
    sc.write("FAKE.RFA", b"upper case extension")
    copy_resource(sc, "chair.rfa")
    sc.run(["info", "fake.rvt"])
    sc.run(["run", "fake.rvt"])
    sc.run(["convert", "fake.rvt", "out.ifc"])
    sc.run(["info", "fake.rte"])
    sc.run(["info", "FAKE.RFA"])
    sc.run(["run", "chair.rfa"])
    sc.run(["convert", "chair.rfa", "chair.bimcraft"])
    sc.run(["info", "missing.rvt"])
    sc.run(["run", "--sample", "missing.rvt"])
    written_files(sc)
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", [
    "floor_arc.rvt", "floor_triangle.rvt", "floor_bad.rvt", "floor_loops.rvt", "floor_cross.rvt", "walls_levels.rvt",
    "openings.rvt", "openings_angled.rvt", "openings_curved.rvt", "roof_rises.rvt", "roof_attached.rvt", "gable_box.rvt",
    "gable_arc.rvt", "gable_chain.rvt", "gable_many.rvt", "columns.rvt", "rooms.rvt",
])
def test_revit_import_of_what_the_reader_reads_only_in_part(sc, name):
    """CATCHES: an import that doesn't follow a floor's arc edge as chords, place a diagonal known only by its box, split
    separate loops, give a crossed sketch its box; take a wall's levels and offsets from its box, keep a wall with no
    orientation as drawn or a storefront as its box's plane; host an opening in the nearest wall below its id, solve its
    width in a wall at an angle, narrow neighbours that overlap a little, cut one that overruns; cut a wall's top by the
    roof it names; refuse a roof by extrusion whose box, lines or chain don't check out; correct a column's bottom from its
    geometry node; move a room's point off a wall or out of a core; and in each case say so in the notes as it should."""
    copy_resource(sc, name)
    sc.cmds(cmd("elements", {}), pre=[name])
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", [
    "future.rvt", "nopartition.rvt", "noplane.rvt", "badtable.rvt", "nobasic.rvt", "badyear.rvt", "nometa.rvt",
    "badgzip.rvt", "truncgzip.rvt", "storedgzip.rvt", "badzip.rvt", "storedzip.rvt", "badatom.rfa",
])
def test_revit_containers_that_break_somewhere(sc, name):
    """CATCHES: info or run that crashes or accepts a Revit file broken in one place instead of saying where: a release the
    reader doesn't guess at, no partition, a schema without Plane, an element table that doesn't fit, a BasicFileInfo that
    isn't one or names no release, no BasicFileInfo, a stream that doesn't inflate; and a stored or cut gzip member, a
    stored or unknown zip entry and a broken Atom entry read as far as they go."""
    copy_resource(sc, name)
    sc.run(["info", name])
    sc.run(["run", name])
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", [
    "mat_framed.rvt", "mat_closed.rvt", "mat_param.rvt", "mat_closed2023.rvt", "mat_style2019.rvt", "mat_style2024.rvt",
    "mat_style2025.rvt", "mat_twice.rvt", "workshared2018.rvt",
])
def test_revit_layer_materials_by_each_naming_rule(sc, name):
    """CATCHES: a reader that names a wall layer's material by a rule its release doesn't write (2023's Closed), misses one
    it does (framed, closed, parameter entry), doesn't take a layer's material from its category's object style up to 2024,
    names a material whose copies disagree, or loses the records of a workshared 2018 file."""
    copy_resource(sc, name)
    p = sc.run(["run", name, "--cmd", "inspect {}"], show=False)
    lines = p.stdout.decode().splitlines()
    sc.note(f"exit {p.returncode}")
    sc.note(lines[0])
    walls = json.loads(lines[1])["types"]["wall"]["Brick wall"]
    sc.note(json.dumps(walls, sort_keys=True))
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("name", ["schema_cut.rvt", "schema_nested.rvt"])
def test_revit_schema_that_breaks_its_grammar(sc, name):
    """CATCHES: a schema reader that crashes on a class name of absurd length or on inline bases nested without end, instead
    of stopping and saying the records can't be found."""
    copy_resource(sc, name)
    sc.run(["info", name])
    sc.run(["run", name])
    assert sc.transcript() == sc.golden()


def test_project_files_holding_broken_scans_or_drawings_are_refused(sc):
    """CATCHES: open that accepts a project whose scan or drawing data is damaged (not base64, not zlib, cut short, a colour
    count that isn't the point count, a point past the span, an origin that isn't one, no points, more points kept than
    read, a drawing whose DXF doesn't read) instead of naming what is wrong; and one nothing places still opening."""
    import base64
    import zlib

    sc.write("room.pts", PTS)
    sc.write("plan.dxf", dxf(line((0, 0), (1000, 0)), MM))
    sc.run(["run", "--cmd", cmd("point_cloud", {"path": "room.pts"}), "--cmd", cmd("import_cad", {"path": "plan.dxf"}),
            "--save", "p.bimcraft"], show=False)
    doc = json.loads((sc.workdir / "p.bimcraft").read_text(encoding="utf-8"))

    def packed(raw: bytes) -> str:
        return base64.b64encode(zlib.compress(raw)).decode()

    cases = {
        "b64": ("clouds", "room", "points", "!!!notbase64"),
        "zlib": ("clouds", "room", "points", base64.b64encode(b"not zlib").decode()),
        "cut": ("clouds", "room", "points", packed(b"1234567")),
        "colours": ("clouds", "room", "colours", packed(b"123")),
        "nan": ("clouds", "room", "points", packed(b"\x00\x00\xc0\x7f" * 12)),
        "origin": ("clouds", "room", "origin", [1e30, 0, 0]),
        "none": ("clouds", "room", "points", packed(b"")),
        "read": ("clouds", "room", "read", 1),
        "cadb64": ("cads", "plan", "dxf", "%%%"),
        "cadzlib": ("cads", "plan", "dxf", base64.b64encode(b"nope").decode()),
        "caddxf": ("cads", "plan", "dxf", packed(b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n")),
    }
    for name, (part, key, field, value) in cases.items():
        broken = json.loads(json.dumps(doc))
        broken[part][key][field] = value
        sc.write(f"{name}.bimcraft", json.dumps(broken))
        sc.run(["run", f"{name}.bimcraft"])
    unplaced = json.loads(json.dumps(doc))
    unplaced["elements"] = {k: v for k, v in unplaced["elements"].items() if v.get("category") != "pointcloud"}
    sc.write("unplaced.bimcraft", json.dumps(unplaced))
    sc.cmds(cmd("library", {"kind": "cloud"}), cmd("elements", {}), pre=["unplaced.bimcraft"])
    assert sc.transcript() == sc.golden()
