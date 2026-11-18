"""IFC: IFC4 export (`--save x.ifc`, `save`, `convert`) and IFC2x3/IFC4 import (`run x.ifc`, `open`, `info`, `convert`,
`insert`, `link`), checked through the STEP file written and the elements read back.

An exported IFC file is compared in canonical form (conftest.canonical_ifc): GlobalIds and the header's timestamp, which
change every run, are replaced, and each run of relationship entities, which the program orders by random GUIDs, is sorted.
"""

import json
import re

from conftest import canonical_ifc, out

# FILE_NAME's timestamp, after a file name that may hold doubled quotes ('Casa d''Agua.ifc').
STAMP_AFTER_ANY_NAME_RE = re.compile(r"(FILE_NAME\('(?:[^']|'')*',)'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d'")


def rounded(v, digits: int = 3):
    """A JSON value with its numbers rounded to `digits` decimals: for points the program works out with sines and
    cosines and prints to the last bit, which may differ in it from one machine's maths library to another's."""
    if isinstance(v, float):
        return round(v, digits) + 0.0
    if isinstance(v, list):
        return [rounded(x, digits) for x in v]
    if isinstance(v, dict):
        return {k: rounded(x, digits) for k, x in v.items()}
    return v


def note_rounded(sc, proc, digits: int = 3):
    """Records a run as sc.run does, each stdout line (JSON) with its numbers rounded."""
    sc.note(f"[exit {proc.returncode}]")
    for line in out(proc).splitlines():
        sc.note(json.dumps(rounded(json.loads(line), digits), sort_keys=True, ensure_ascii=False))
    sc.note("--- stderr")
    sc.note(proc.stderr.decode())


def note_digest(sc, path: str):
    """Records a big text file the program wrote by the digest of its normalised text (its raw length varies with the
    random project uid it holds, so it is left out)."""
    import hashlib

    from conftest import normalize

    text = normalize((sc.workdir / path).read_text(encoding="utf-8"))
    sc.note(f"=== file {path}: normalised sha256={hashlib.sha256(text.encode()).hexdigest()}")


def note_ifc(sc, path: str):
    """Records an IFC file the program wrote, as sc.file does, its timestamp found after any file name."""
    text = (sc.workdir / path).read_text(encoding="utf-8")
    sc.note(f"=== file {path}")
    sc.note(canonical_ifc(STAMP_AFTER_ANY_NAME_RE.sub(r"\1'<STAMP>'", text)))

# ---------------------------------------------------------------------------
# Hand-written IFC inputs.
# ---------------------------------------------------------------------------

MM_UNITS = "#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);\n#2=IFCUNITASSIGNMENT((#1));"


def ifc_text(body: str, *, schema: str = "IFC4", units: str = MM_UNITS, name: str = "Hand Made", header: str = "") -> str:
    """A STEP file: a project #3 in `units` (which define #1 and #2), a placement #6 at the origin and storey #7 on it, then
    `body`, which says what the storey contains."""
    return (
        "ISO-10303-21;\nHEADER;\n"
        "FILE_DESCRIPTION(('ViewDefinition [DesignTransferView]'),'2;1');\n"
        "FILE_NAME('hand.ifc','2020-01-01T00:00:00',('Tester'),('Org'),'Hand','Hand','');\n"
        f"{header}FILE_SCHEMA(('{schema}'));\nENDSEC;\nDATA;\n"
        f"{units}\n"
        f"#3=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,'{name}',$,$,$,$,$,#2);\n"
        "#4=IFCCARTESIANPOINT((0.,0.,0.));\n"
        "#5=IFCAXIS2PLACEMENT3D(#4,$,$);\n"
        "#6=IFCLOCALPLACEMENT($,#5);\n"
        "#7=IFCBUILDINGSTOREY('1kTvXnbbzCWw8lcMd1dR4o',$,'Ground',$,$,#6,$,$,.ELEMENT.,0.);\n"
        f"{body.strip()}\n"
        "ENDSEC;\nEND-ISO-10303-21;\n"
    )


def cmd_args(commands) -> list[str]:
    """`--cmd C` for each command."""
    return [a for c in commands for a in ("--cmd", c)]


def box_brep(first: int, x0, y0, z0, x1, y1, z1) -> tuple[str, int]:
    """An IFCFACETEDBREP of a box, its entities numbered from `first`: (the lines, the brep's number)."""
    corners = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]
    lines, n = [], first
    for c in corners:
        lines.append(f"#{n}=IFCCARTESIANPOINT(({float(c[0])},{float(c[1])},{float(c[2])}));")
        n += 1
    face_ids = []
    for f in faces:
        pts = ",".join(f"#{first + i - 1}" for i in f)
        lines.append(f"#{n}=IFCPOLYLOOP(({pts}));")
        lines.append(f"#{n + 1}=IFCFACEOUTERBOUND(#{n},.T.);")
        lines.append(f"#{n + 2}=IFCFACE((#{n + 1}));")
        face_ids.append(f"#{n + 2}")
        n += 3
    lines.append(f"#{n}=IFCCLOSEDSHELL(({','.join(face_ids)}));")
    lines.append(f"#{n + 1}=IFCFACETEDBREP(#{n});")
    return "\n".join(lines), n + 1


class Ifc:
    """A hand-written IFC file, built entity by entity: `add` numbers each from #10 on and returns its reference. The
    preamble is `ifc_text`'s: a project #3, a placement #6 at the origin and a storey #7 on it."""

    def __init__(self, **kwargs):
        self.lines: list[str] = []
        self.n = 10
        self.kwargs = kwargs

    def add(self, entity: str) -> str:
        ref = f"#{self.n}"
        self.lines.append(f"{ref}={entity};")
        self.n += 1
        return ref

    def pt(self, *c) -> str:
        return self.add("IFCCARTESIANPOINT((" + ",".join(f"{float(x)}" for x in c) + "))")

    def dir(self, *c) -> str:
        return self.add("IFCDIRECTION((" + ",".join(f"{float(x)}" for x in c) + "))")

    def place(self, x=0.0, y=0.0, z=0.0, *, axis=None, ref=None, rel="#6") -> str:
        """A local placement at (x, y, z) under `rel`, its z along `axis` and its x along `ref` when given."""
        o = self.pt(x, y, z)
        a = self.dir(*axis) if axis else "$"
        r = self.dir(*ref) if ref else "$"
        return self.add(f"IFCLOCALPLACEMENT({rel},{self.add(f'IFCAXIS2PLACEMENT3D({o},{a},{r})')})")

    def shape(self, *items: str, kind="Body", rep="SweptSolid", axis_items=()) -> str:
        reps = [self.add(f"IFCSHAPEREPRESENTATION($,'{kind}','{rep}',({','.join(items)}))")]
        if axis_items:
            reps.insert(0, self.add(f"IFCSHAPEREPRESENTATION($,'Axis','Curve2D',({','.join(axis_items)}))"))
        return self.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({','.join(reps)}))")

    def extrude(self, profile: str, depth: float, along=(0, 0, 1), at=None) -> str:
        pos = "$" if at is None else self.add(f"IFCAXIS2PLACEMENT3D({self.pt(*at)},$,$)")
        return self.add(f"IFCEXTRUDEDAREASOLID({profile},{pos},{self.dir(*along)},{float(depth)})")

    def rect(self, x, y, w, d) -> str:
        """A rectangle profile w by d centred on (x, y)."""
        at = self.add(f"IFCAXIS2PLACEMENT2D({self.pt(x, y)},$)")
        return self.add(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,{at},{float(w)},{float(d)})")

    def polyline(self, *pts) -> str:
        return self.add("IFCPOLYLINE((" + ",".join(self.pt(*p) for p in pts) + "))")

    def brep(self, x0, y0, z0, x1, y1, z1) -> str:
        text, last = box_brep(self.n, x0, y0, z0, x1, y1, z1)
        self.lines.extend(text.splitlines())
        self.n = last + 1
        return f"#{last}"

    def wall(self, name, a, b, t, h, *, cls="IFCWALL", z=0.0, extra_args=",$,$") -> str:
        """A straight wall from `a` to `b` in plan, `t` thick and `h` high: an axis and a body extruded from a rectangle, in
        a placement at `a` turned along it."""
        import math

        (x0, y0), (x1, y1) = a, b
        length = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        place = self.place(x0, y0, z, axis=(0, 0, 1), ref=(ux, uy, 0))
        axis = self.polyline((0, 0), (length, 0))
        body = self.extrude(self.rect(length / 2, 0, length, t), h)
        return self.add(f"{cls}('{gid(self.n)}',$,'{name}',$,$,{place},{self.shape(body, axis_items=[axis])}{extra_args})")

    def contain(self, *refs: str, storey="#7"):
        self.add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{gid(self.n)}',$,$,$,({','.join(refs)}),{storey})")

    def text(self) -> str:
        return ifc_text("\n".join(self.lines), **self.kwargs)


def gid(n: int) -> str:
    """A GlobalId for entity number `n`: 22 characters of IFC's alphabet, the same every time."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
    digits, v = [], n * 2654435761 + 12345
    for _ in range(21):
        digits.append(alphabet[v % 64])
        v //= 64
    return "1" + "".join(digits)


# The README's house.
HOUSE = [
    'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true, "type": "Exterior - 300mm"}',
    'door {"at": [2000, 0]}',
    'window {"at": [8000, 3000]}',
    'room {"point": [4000, 3000], "name": "Living"}',
    "floor {}",
    "roof {}",
]

STRUCTURE = [
    'grid {"start": [0, -1000], "end": [0, 7000]}',
    'structural_column {"at": [0, 0]}',
    'structural_column {"at": [6000, 0], "type": "Concrete Round 400"}',
    'column {"at": [3000, 3000], "type": "Round 300"}',
    'footing {"at": [0, 0]}',
    'footing {"at": [6000, 0], "thickness": 500}',
    'beam {"points": [[0, 0], [6000, 0]], "level": "Level 2"}',
    'beam {"points": [[0, 6000], [6000, 6000]], "level": "Level 2", "end_offset": 500, "type": "Steel Tube 150", "justify": "centre"}',
    'strip_footing {"points": [[0, 6000], [6000, 6000]]}',
    'floor {"boundary": [[0,0],[6000,0],[6000,6000],[0,6000]], "level": "Level 2", "structural": true}',
]

MEP = [
    'wall {"points": [[0,0],[6000,0],[6000,5000],[0,5000]], "closed": true}',
    'pipe {"points": [[500, 500], [5500, 500]], "offset": 600, "system": "Cold Water"}',
    'pipe {"points": [[5500, 500], [5500, 500]], "offset": 0, "end_offset": 3000, "type": "PVC 110", "system": "Sewer"}',
    'duct {"points": [[500, 2500], [5500, 2500]], "offset": 2700, "type": "Round 300"}',
    'conduit {"points": [[500, 4000], [3000, 4000]], "offset": 2900}',
    'cable_tray {"points": [[500, 4500], [5500, 4500]], "offset": 2800, "justify": "top"}',
    'wire {"points": [[1000, 1000], [2000, 1000]], "offset": 2500, "system": "C1"}',
    'down_conductor {"points": [[0, 0], [0, 0]], "offset": 0, "end_offset": 3000}',
    'ground_conductor {"points": [[-500, -500], [6500, -500]], "offset": -500}',
    'cabling {"points": [[1000, 3000], [2000, 3000]], "offset": 300}',
    'component {"family": "WC", "at": [3000, 4500]}',
    'component {"family": "Outlet", "at": [100, 2000], "angle": 90}',
    'component {"family": "Distribution Board", "at": [5900, 2000], "angle": 180}',
]

CIRCULATION = [
    'wall {"points": [[0,0],[10000,0],[10000,8000],[0,8000]], "closed": true, "type": "Exterior - 300mm"}',
    'wall {"points": [[5000,0],[5000,8000]], "type": "Interior - 100mm"}',
    'wall {"points": [[12000,0],[16000,0]], "arc": 90}',
    'stair {"start": [1000, 1000], "end": [1000, 5000], "width": 1000}',
    'ramp {"start": [7000, 1000], "angle": 90, "width": 1200, "height": 500}',
    'room {"point": [2500, 6000], "name": "Hall"}',
    'room_separator {"points": [[5000, 4000], [10000, 4000]]}',
    'room {"point": [7500, 6000], "name": "Office"}',
    'ceiling {"point": [7500, 6000]}',
    "floor {}",
    'mass {"boundary": [[20000,0],[24000,0],[24000,4000],[20000,4000]], "height": 6000}',
    'railing {"path": [[0, -1000], [4000, -1000]]}',
]


# ---------------------------------------------------------------------------
# Export.
# ---------------------------------------------------------------------------


def test_export_readme_house(sc):
    """CATCHES: an IFC4 export with the wrong header or schema, missing spatial structure (project, site, building, storeys),
    wrong wall extrusions or material layer sets, a door or window without its opening and fill relations, a room, floor or
    roof written as the wrong entity, or misplaced coordinates."""
    sc.cmds(*HOUSE, post=["--save", "house.ifc"])
    sc.file("house.ifc")
    assert sc.transcript() == sc.golden()


def test_export_empty_project_has_only_the_spatial_structure(sc):
    """CATCHES: an export of an empty project that leaves out its two storeys or units, or writes elements it hasn't."""
    sc.run(["run", "--save", "empty.ifc"])
    sc.file("empty.ifc")
    assert sc.transcript() == sc.golden()


def test_export_sample_house(sc):
    """CATCHES: any change in how the sample house is written to IFC: walls cut to the hipped roof, layered wall types,
    doors and windows from families, furniture as faceted bodies, ceilings, rooms as spaces, quantities and property sets."""
    sc.run(["run", "--sample", "--save", "sample.ifc"])
    sc.file("sample.ifc")
    assert sc.transcript() == sc.golden()


def test_export_structure(sc):
    """CATCHES: beams, structural and architectural columns, isolated and strip footings or a structural floor written as
    the wrong IFC class or predefined type, with the wrong profile (rectangle or circle), slope, LoadBearing flag or
    material profile sets."""
    sc.cmds(*STRUCTURE, post=["--save", "structure.ifc"])
    sc.file("structure.ifc")
    assert sc.transcript() == sc.golden()


def test_export_mep_runs_systems_and_fixtures(sc):
    """CATCHES: pipes, ducts, conduits, cable trays, wires, conductors and cabling written as the wrong segment classes, an
    upright pipe or a sloped one mis-extruded, runs not assigned to their IfcSystem, or the starter fixtures (WC, outlet,
    distribution board) written as the wrong terminal classes."""
    sc.cmds(*MEP, post=["--save", "mep.ifc"])
    sc.file("mep.ifc")
    assert sc.transcript() == sc.golden()


def test_export_stairs_ramps_rooms_ceilings_and_masses(sc):
    """CATCHES: a stair or ramp not aggregated from its flights, a curved wall not written as faceted bodies, a room
    separator not an IfcVirtualElement, a ceiling not an IfcCovering, a mass not a building element proxy, or a railing
    along a path left out."""
    sc.cmds(*CIRCULATION, post=["--save", "circulation.ifc"])
    sc.file("circulation.ifc")
    assert sc.transcript() == sc.golden()


def test_export_project_parameters_as_property_sets(sc):
    """CATCHES: project parameter values not written as a property set with IFCTEXT, IFCREAL, IFCLENGTHMEASURE and
    IFCBOOLEAN values, or written on elements that hold none."""
    sc.cmds(
        'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}',
        'door {"at": [4000, 0]}',
        'room {"point": [4000, 3000]}',
        'parameter {"name": "Fire Rating", "categories": ["wall", "door"]}',
        'parameter {"name": "Cost", "kind": "number", "categories": ["door"]}',
        'parameter {"name": "Finish Height", "kind": "length", "categories": ["room"]}',
        'parameter {"name": "Accessible", "kind": "yesno", "categories": ["door", "room"]}',
        'modify {"id": 100002, "params": {"Fire Rating": "60 min"}}',
        'modify {"id": 100006, "params": {"Fire Rating": "30 min", "Cost": 450.5, "Accessible": true}}',
        'modify {"id": 100007, "params": {"Finish Height": 2400, "Accessible": false}}',
        post=["--save", "params.ifc"],
    )
    sc.file("params.ifc")
    assert sc.transcript() == sc.golden()


def test_export_phases_and_design_options(sc):
    """CATCHES: the project's phases and design option sets not written in the BIMCraft_Phasing property set on the
    project, or an element's Phase Created and Phase Demolished not written with its demolish status."""
    sc.cmds(
        'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}',
        'phase {"name": "Demolition", "after": "Existing"}',
        'door {"at": [4000, 0]}',
        'option {"set": "Kitchen", "options": ["Open", "Closed"]}',
        'modify {"id": 100002, "params": {"Phase Created": "Existing", "Phase Demolished": "Demolition"}}',
        post=["--save", "phased.ifc"],
    )
    sc.file("phased.ifc")
    assert sc.transcript() == sc.golden()


def test_export_escapes_quotes_backslashes_and_unicode(sc):
    """CATCHES: STEP strings not escaped as ISO 10303-21 says: a quote not doubled, a backslash not doubled, a letter
    outside ASCII not written as \\X2\\ (UTF-16) or past the BMP as \\X4\\ (UTF-32)."""
    sc.cmds(
        'new {"name": "Casa d\'Água \\\\ 😀"}',
        'wall {"points": [[0,0],[5000,0],[5000,4000],[0,4000]], "closed": true}',
        'room {"point": [2500, 2000], "name": "Sala de Jantar — Ñandú\'s"}',
        'level {"elevation": 6000, "name": "Étage ½"}',
        post=["--save", "names.ifc"],
    )
    note_ifc(sc, "names.ifc")
    assert sc.transcript() == sc.golden()


def test_convert_project_to_ifc_matches_saving_it(sc):
    """CATCHES: `convert IN.bimcraft OUT.ifc` writing anything other than what `--save OUT.ifc` writes of the same project,
    or `convert` printing another result line."""
    sc.cmds(*HOUSE, post=["--save", "house.bimcraft", "--save", "direct.ifc"])
    sc.run(["convert", "house.bimcraft", "converted.ifc"])
    a = (sc.workdir / "direct.ifc").read_text()
    b = (sc.workdir / "converted.ifc").read_text()
    from conftest import canonical_ifc

    sc.note(f"converted equals direct: {canonical_ifc(a) == canonical_ifc(b)}")
    sc.file("converted.ifc")
    assert sc.transcript() == sc.golden()


def test_export_door_and_window_families_and_flipped_walls(sc):
    """CATCHES: a door family's operation (double, sliding) not written as its OperationType, a sliding door's hand not
    following flip_hand, a window family not partitioned, or a flipped wall's layers written the wrong way round."""
    sc.cmds(
        'wall {"points": [[0,0],[9000,0],[9000,6000],[0,6000]], "closed": true, "type": "Exterior - 300mm"}',
        'door {"at": [1500, 0], "family": "Double Door"}',
        'door {"at": [4500, 0], "family": "Sliding Door", "flip_hand": true}',
        'door {"at": [7500, 0], "family": "Single Door", "flip_facing": true}',
        'window {"at": [9000, 3000], "family": "Casement Window"}',
        'window {"at": [0, 3000], "family": "Sliding Window", "sill": 1000}',
        'flip {"ids": [100003]}',
        post=["--save", "openings.ifc"],
    )
    sc.file("openings.ifc")
    assert sc.transcript() == sc.golden()


def test_export_shaft_through_floors_and_sloped_roof(sc):
    """CATCHES: a shaft not written as opening elements voiding each floor it passes through, or a roof with gables and
    slopes written with the wrong faceted body."""
    sc.cmds(
        'level {"elevation": 6000, "name": "Level 3"}',
        'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}',
        "floor {}",
        'floor {"level": "Level 2", "boundary": [[0,0],[8000,0],[8000,6000],[0,6000]]}',
        'shaft {"boundary": [[1000,1000],[2000,1000],[2000,2000],[1000,2000]], "top_level": "Level 3", "base_offset": -500}',
        'roof {"level": "Level 3", "boundary": [[0,0],[8000,0],[8000,6000],[0,6000]], "slope": 30, "gables": [1, 3], "overhang": 400}',
        post=["--save", "shaft.ifc"],
    )
    sc.file("shaft.ifc")
    assert sc.transcript() == sc.golden()


VARIETY = [
    'type {"category": "floor", "name": "Screed on Slab", "layers": [{"function": "finish", "material": "Ceramic tile", "thickness": 20}, '
    '{"function": "substrate", "material": "Screed", "thickness": 50}, {"function": "membrane", "material": "Membrane", "thickness": 5}, '
    '{"function": "structure", "material": "Concrete", "thickness": 150}]}',
    'type {"category": "roof", "name": "Tiled Roof", "layers": [{"function": "finish", "material": "Roof tiles", "thickness": 30}, '
    '{"function": "thermal", "material": "Insulation", "thickness": 100}, {"function": "structure", "material": "Timber", "thickness": 50}]}',
    'type {"category": "ceiling", "name": "Plaster Ceiling", "layers": [{"function": "finish", "material": "Gypsum board", "thickness": 15}]}',
    'wall {"points": [[0,0],[10000,0],[10000,8000],[0,8000]], "closed": true}',
    'floor {"type": "Screed on Slab", "openings": [[[1000,1000],[2000,1000],[2000,2000],[1000,2000]]]}',
    'floor {"boundary": [[12000,0],[18000,0],[18000,6000],[12000,6000]], "slope": 5, "arrow": [[12000,3000],[18000,3000]]}',
    'roof {"type": "Tiled Roof", "slope": 35}',
    'room {"point": [5000, 4000], "name": "Hall"}',
    'modify {"id": 100009, "colour": [214, 229, 210]}',
    'ceiling {"point": [5000, 4000], "type": "Plaster Ceiling"}',
    'window {"at": [5000, 8000]}',
    'stair {"start": [20000, 0], "angle": 90, "landings": [{"at": 6, "turn": 90}]}',
    'stair {"start": [26000, 0], "angle": 90, "landings": [{"at": 5, "turn": 90}, {"at": 10, "turn": 90}]}',
    'stair {"start": [32000, 0], "angle": 90, "landings": [{"at": 8, "turn": 0}]}',
    'beam {"points": [[0,10000],[6000,10000]], "level": "Level 2", "justify": "top"}',
    'beam {"points": [[0,11000],[6000,11000]], "level": "Level 2", "justify": "bottom"}',
    'column {"at": [3000, 12000]}',
    'footing {"at": [3000, 12000]}',
    'ramp {"start": [40000, 0], "angle": 90, "height": 400}',
    'railing {"path": [[40000, -500], [42000, -500]]}',
    'modify {"ids": [100006, 100011, 100017], "params": {"Phase Created": "Existing"}}',
    'modify {"ids": [100008, 100015, 100018], "params": {"Phase Created": "Existing", "Phase Demolished": "New Construction"}}',
    'modify {"ids": [100010, 100012, 100019, 100020], "params": {"Phase Created": "New Construction", "Phase Demolished": "New Construction"}}',
    'modify {"ids": [100013, 100014, 100016], "params": {"Phase Created": "New Construction"}}',
]


def test_export_layered_slabs_landings_justified_beams_and_statuses(sc):
    """CATCHES: floor, roof and ceiling layer sets (and their usage on a floor) missing or with the wrong layer categories,
    a floor's opening not a void in its profile, a sloped floor not a faceted body, a stair's shape with landings not
    QUARTER_TURN, TWO_QUARTER_TURN or TWO_STRAIGHT_RUN, a beam's cardinal point not following its justification, a room's
    colour not styling its space, or Pset_*Common Status not EXISTING, DEMOLISH, TEMPORARY or NEW by its phases."""
    sc.cmds(*VARIETY, post=["--save", "variety.ifc"])
    sc.file("variety.ifc")
    assert sc.transcript() == sc.golden()


def test_variety_round_trip(sc):
    """CATCHES: layered floor, roof and ceiling types, a sloped floor, landings and their turns, or the phases of many
    categories not read back as they were written."""
    sc.run(["run", *cmd_args(VARIETY), "--save", "v.ifc"], show=False)
    sc.run(["run", "v.ifc", "--cmd", 'elements {"category": "floor"}', "--cmd", 'elements {"category": "stair"}',
            "--cmd", 'elements {"category": "ceiling"}', "--cmd", 'elements {"category": "room"}', "--cmd", 'elements {"category": "beam"}'])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Import of what the program exports.
# ---------------------------------------------------------------------------


def test_sample_round_trip_elements(sc):
    """CATCHES: an import of the sample's own IFC that loses or misreads elements: wall ends, heights cut to the roof,
    layered types, door and window offsets and marks, rooms, ceilings, furniture families, or the counts `open` reports."""
    sc.run(["run", "--sample", "--save", "house.ifc"], show=False)
    sc.run(["run", "house.ifc", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_info_of_an_ifc_file(sc):
    """CATCHES: `info FILE.ifc` not importing the file, or printing anything but the inspected project as pretty JSON
    (levels, counts, types read from the file, warnings)."""
    sc.run(["run", *cmd_args(HOUSE), "--save", "house.ifc"], show=False)
    sc.run(["info", "house.ifc"])
    assert sc.transcript() == sc.golden()


def test_structure_round_trip(sc):
    """CATCHES: a structural import that turns load-bearing columns into architectural ones, loses a beam's slope or
    justification, reads an isolated footing as a strip, or a structural floor as an ordinary one."""
    sc.run(["run", *cmd_args(STRUCTURE), "--save", "s.ifc"], show=False)
    sc.run(["run", "s.ifc", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_mep_round_trip(sc):
    """CATCHES: runs not read back into their own categories (from BIMCraft_Run), their systems, heights or upright
    pipes lost, or the fixtures not read back as components of their families."""
    sc.run(["run", *cmd_args(MEP), "--save", "m.ifc"], show=False)
    sc.run(["run", "m.ifc", "--cmd", 'elements {"category": "pipe"}', "--cmd", 'elements {"category": "wire"}',
            "--cmd", 'elements {"category": "cabletray"}', "--cmd", 'elements {"category": "component"}'])
    assert sc.transcript() == sc.golden()


def test_circulation_round_trip(sc):
    """CATCHES: stairs, ramps, railings, room separators, a curved wall, a ceiling or a mass not read back as their
    BIMCraft elements, or read with other riser counts, slopes, arcs or heights."""
    sc.run(["run", *cmd_args(CIRCULATION), "--save", "c.ifc"], show=False)
    sc.run(["run", "c.ifc", "--cmd", 'elements {"category": "stair"}', "--cmd", 'elements {"category": "ramp"}',
            "--cmd", 'elements {"category": "railing"}', "--cmd", 'elements {"category": "roomseparator"}',
            "--cmd", 'elements {"category": "wall"}', "--cmd", 'elements {"category": "mass"}',
            "--cmd", 'elements {"category": "ceiling"}'])
    assert sc.transcript() == sc.golden()


def test_parameters_and_phases_round_trip(sc):
    """CATCHES: project parameters not read back from their property set with their kinds and values, or the phases,
    design option sets and an element's phases not read back from BIMCraft_Phasing."""
    sc.run(["run",
            "--cmd", 'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}',
            "--cmd", 'door {"at": [4000, 0]}',
            "--cmd", 'parameter {"name": "Fire Rating", "categories": ["wall", "door"]}',
            "--cmd", 'parameter {"name": "Cost", "kind": "number", "categories": ["door"]}',
            "--cmd", 'parameter {"name": "Accessible", "kind": "yesno", "categories": ["door"]}',
            "--cmd", 'modify {"id": 100006, "params": {"Fire Rating": "30 min", "Cost": 450.5, "Accessible": true}}',
            "--cmd", 'phase {"name": "Demolition", "after": "Existing"}',
            "--cmd", 'option {"set": "Kitchen", "options": ["Open", "Closed"]}',
            "--cmd", 'modify {"id": 100002, "params": {"Phase Created": "Existing", "Phase Demolished": "Demolition"}}',
            "--save", "p.ifc"], show=False)
    sc.run(["run", "p.ifc", "--cmd", 'elements {"category": "door"}', "--cmd", 'elements {"category": "wall", "limit": 1}',
            "--cmd", 'phase {}', "--cmd", 'option {"set": "Kitchen"}', "--cmd", 'library {"kind": "parameter"}'])
    assert sc.transcript() == sc.golden()


def test_opened_ifc_is_a_new_unsaved_project(sc):
    """CATCHES: an imported IFC remembering the .ifc as the project's own file, so that `save {}` writes over it instead
    of asking for a path; Save As a .bimcraft must work and the .ifc stay as it was."""
    sc.run(["run", *cmd_args(HOUSE), "--save", "house.ifc"], show=False)
    before = (sc.workdir / "house.ifc").read_bytes()
    sc.run(["run", "house.ifc", "--cmd", "save {}"])
    sc.run(["run", "house.ifc", "--cmd", 'save {"path": "house.bimcraft"}', "--cmd", 'inspect {}'], show=False)
    sc.run(["info", "house.bimcraft"])
    sc.note(f"ifc unchanged: {(sc.workdir / 'house.ifc').read_bytes() == before}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Import of hand-written files.
# ---------------------------------------------------------------------------

IFC2X3_HOUSE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0]'),'2;1');
FILE_NAME('w23.ifc','2020-01-01T00:00:00',('Someone'),('Org'),'Hand','Hand','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
/* lengths in metres, angles in radians */
#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#2=IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.);
#3=IFCUNITASSIGNMENT((#1,#2));
#4=IFCPROJECT('2O2Fr$t4X7Zf8NOew3FLOH',$,'Caf\\X2\\00E9\\X0\\ Project',$,$,$,$,$,#3);
#5=IFCCARTESIANPOINT((0.,0.,0.));
#6=IFCAXIS2PLACEMENT3D(#5,$,$);
#7=IFCLOCALPLACEMENT($,#6);
#8=IFCSITE('3hPkD5Vbr8vQWk3mN7x2sA',$,'Site',$,$,#7,$,$,.ELEMENT.,$,$,$,$,$);
#9=IFCBUILDING('0yZXkPpWzBXw1uC2Eh3Mji',$,'Building',$,$,#7,$,$,.ELEMENT.,$,$,$);
#10=IFCBUILDINGSTOREY('1kTvXnbbzCWw8lcMd1dR4o',$,'Ground Floor',$,$,#7,$,$,.ELEMENT.,0.);
#11=IFCCARTESIANPOINT((0.,0.,3.5));
#12=IFCAXIS2PLACEMENT3D(#11,$,$);
#13=IFCLOCALPLACEMENT(#7,#12);
#14=IFCBUILDINGSTOREY('2kTvXnbbzCWw8lcMd1dR4o',$,'First Floor',$,$,#13,$,$,.ELEMENT.,3.5);
#20=IFCCARTESIANPOINT((0.,0.));
#21=IFCCARTESIANPOINT((6.,0.));
#22=IFCPOLYLINE((#20,#21));
#23=IFCSHAPEREPRESENTATION($,'Axis','Curve2D',(#22));
#24=IFCCARTESIANPOINT((3.,0.));
#25=IFCAXIS2PLACEMENT2D(#24,$);
#26=IFCRECTANGLEPROFILEDEF(.AREA.,$,#25,6.,0.25);
#27=IFCDIRECTION((0.,0.,1.));
#28=IFCEXTRUDEDAREASOLID(#26,$,#27,3.);
#29=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#28));
#30=IFCPRODUCTDEFINITIONSHAPE($,$,(#23,#29));
#31=IFCWALLSTANDARDCASE('0DWgwt6o1FOx7466fPk$jl',$,'Basic Wall',$,$,#7,#30,$);
#40=IFCCARTESIANPOINT((2.,-0.125,0.));
#41=IFCAXIS2PLACEMENT3D(#40,$,$);
#42=IFCLOCALPLACEMENT(#7,#41);
#43=IFCCARTESIANPOINT((0.45,0.125));
#44=IFCAXIS2PLACEMENT2D(#43,$);
#45=IFCRECTANGLEPROFILEDEF(.AREA.,$,#44,0.9,0.25);
#46=IFCEXTRUDEDAREASOLID(#45,$,#27,2.1);
#47=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#46));
#48=IFCPRODUCTDEFINITIONSHAPE($,$,(#47));
#49=IFCOPENINGELEMENT('1DWgwt6o1FOx7466fPk$jl',$,'Opening',$,$,#42,#48,$);
#50=IFCRELVOIDSELEMENT('2DWgwt6o1FOx7466fPk$jl',$,$,$,#31,#49);
#51=IFCDOOR('3DWgwt6o1FOx7466fPk$jl',$,'Door',$,$,#42,#48,'D-01',2.1,0.9);
#52=IFCRELFILLSELEMENT('0EWgwt6o1FOx7466fPk$jl',$,$,$,#49,#51);
#53=IFCDOORSTYLE('0GWgwt6o1FOx7466fPk$jl',$,'Sliding',$,$,$,$,$,.SLIDING_TO_LEFT.,.NOTDEFINED.,.F.,.F.);
#54=IFCRELDEFINESBYTYPE('0HWgwt6o1FOx7466fPk$jl',$,$,$,(#51),#53);
#60=IFCRELCONTAINEDINSPATIALSTRUCTURE('1EWgwt6o1FOx7466fPk$jl',$,$,$,(#31,#51),#10);
#61=IFCRELAGGREGATES('2EWgwt6o1FOx7466fPk$jl',$,$,$,#4,(#8));
#62=IFCRELAGGREGATES('3EWgwt6o1FOx7466fPk$jl',$,$,$,#8,(#9));
#63=IFCRELAGGREGATES('0FWgwt6o1FOx7466fPk$jl',$,$,$,#9,(#10,#14));
ENDSEC;
END-ISO-10303-21;
"""


def test_import_ifc2x3_wall_and_door_in_metres(sc):
    """CATCHES: an IFC2x3 reader that ignores the METRE length unit, misreads the wall's axis and rectangle body, places the
    door off the opening that fills it, loses its tag as the mark or the door style's sliding operation, decodes the
    project name's \\X2\\ escape wrongly, or takes storey heights from their attribute instead of their placement."""
    sc.write("w23.ifc", IFC2X3_HOUSE)
    sc.run(["run", "w23.ifc", "--cmd", "elements {}", "--cmd", 'inspect {}'])
    assert sc.transcript() == sc.golden()


def test_import_mesh_wall_and_mapped_column(sc):
    """CATCHES: a reader that needs an extrusion to measure a wall (here a triangle mesh with no axis, turned north by its
    placement), or that ignores IfcMappedItem, so a column whose body is its type's representation map is lost."""
    pts = "(0.,-100.,0.),(5000.,-100.,0.),(5000.,100.,0.),(0.,100.,0.),(0.,-100.,2700.),(5000.,-100.,2700.),(5000.,100.,2700.),(0.,100.,2700.)"
    tris = "(1,3,2),(1,4,3),(5,6,7),(5,7,8),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,4,8),(3,8,7),(4,1,5),(4,5,8)"
    body = f"""
#10=IFCCARTESIANPOINTLIST3D(({pts}));
#11=IFCTRIANGULATEDFACESET(#10,$,.T.,({tris}),$);
#12=IFCSHAPEREPRESENTATION($,'Body','Tessellation',(#11));
#13=IFCPRODUCTDEFINITIONSHAPE($,$,(#12));
#14=IFCCARTESIANPOINT((1000.,2000.,0.));
#15=IFCDIRECTION((0.,1.,0.));
#16=IFCDIRECTION((0.,0.,1.));
#17=IFCAXIS2PLACEMENT3D(#14,#16,#15);
#18=IFCLOCALPLACEMENT(#6,#17);
#19=IFCWALL('2O2Fr$t4X7Zf8NOew3FLOH',$,'Mesh Wall',$,$,#18,#13,$,$);
#30=IFCRECTANGLEPROFILEDEF(.AREA.,$,$,300.,500.);
#31=IFCEXTRUDEDAREASOLID(#30,$,#16,3000.);
#32=IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#31));
#33=IFCREPRESENTATIONMAP(#5,#32);
#34=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#4,$,$);
#35=IFCMAPPEDITEM(#33,#34);
#36=IFCSHAPEREPRESENTATION($,'Body','MappedRepresentation',(#35));
#37=IFCPRODUCTDEFINITIONSHAPE($,$,(#36));
#38=IFCCARTESIANPOINT((3000.,4000.,0.));
#39=IFCAXIS2PLACEMENT3D(#38,#16,$);
#40=IFCLOCALPLACEMENT(#6,#39);
#41=IFCCOLUMN('3DWgwt6o1FOx7466fPk$jl',$,'Column',$,$,#40,#37,$,$);
#50=IFCRELCONTAINEDINSPATIALSTRUCTURE('0EWgwt6o1FOx7466fPk$jl',$,$,$,(#19,#41),#7);
"""
    sc.write("mesh.ifc", ifc_text(body))
    sc.run(["run", "mesh.ifc", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


FEET = """#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#8=IFCDIMENSIONALEXPONENTS(1,0,0,0,0,0,0);
#9=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(0.3048),#1);
#100=IFCCONVERSIONBASEDUNIT(#8,.LENGTHUNIT.,'FOOT',#9);
#101=IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.);
#102=IFCDIMENSIONALEXPONENTS(0,0,0,0,0,0,0);
#103=IFCMEASUREWITHUNIT(IFCPLANEANGLEMEASURE(0.0174532925199433),#101);
#104=IFCCONVERSIONBASEDUNIT(#102,.PLANEANGLEUNIT.,'DEGREE',#103);
#2=IFCUNITASSIGNMENT((#100,#104));"""


def test_import_feet_and_degrees(sc):
    """CATCHES: conversion-based units not followed to their SI base (a foot is 304.8 mm), so a wall 20 ft long by 8 in
    thick and 10 ft high, a 2 ft square column and a 30 ft storey come in at the wrong sizes."""
    b = Ifc(units=FEET)
    w = b.wall("Feet Wall", (0, 0), (20, 0), 0.6666666666666666, 10)
    c = b.add(f"IFCCOLUMN('{gid(1)}',$,'Square Column',$,$,{b.place(10, 5, 0)},{b.shape(b.extrude(b.rect(0, 0, 2, 2), 10))},$,$)")
    upper = b.add(f"IFCBUILDINGSTOREY('{gid(2)}',$,'Roof Deck',$,$,{b.place(0, 0, 30)},$,$,.ELEMENT.,30.)")
    b.contain(w, c)
    b.add(f"IFCRELAGGREGATES('{gid(3)}',$,$,$,#3,(#7,{upper}))")
    sc.write("feet.ifc", b.text())
    sc.run(["run", "feet.ifc", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_import_millimetre_prefixes_and_centimetres(sc):
    """CATCHES: an SI prefix other than MILLI (here CENTI) not scaling lengths, so a 400 cm wall reads as 400 mm."""
    b = Ifc(units="#1=IFCSIUNIT(*,.LENGTHUNIT.,.CENTI.,.METRE.);\n#2=IFCUNITASSIGNMENT((#1));")
    b.contain(b.wall("Centimetre Wall", (0, 0), (400, 0), 20, 280))
    sc.write("cm.ifc", b.text())
    sc.run(["run", "cm.ifc", "--cmd", 'elements {"category": "wall"}'])
    assert sc.transcript() == sc.golden()


def holed_slab_text(slab_predefined: str = ".FLOOR.", cls: str = "IFCSLAB") -> str:
    """A 6 x 4 m slab 200 mm thick round two holes, with an opening element voiding it through the east one."""
    b = Ifc()

    def loop(x0, y0, x1, y1):
        return b.polyline((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))

    outer, h1, h2 = loop(0, 0, 6000, 4000), loop(1000, 1000, 2500, 2000), loop(4000, 1000, 5000, 2000)
    profile = b.add(f"IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,{outer},({h1},{h2}))")
    slab_place = b.place(0, 0, -200)
    slab = b.add(f"{cls}('{gid(10)}',$,'Slab',$,$,{slab_place},{b.shape(b.extrude(profile, 200))},$,{slab_predefined})")
    hole = b.add(f"IFCOPENINGELEMENT('{gid(11)}',$,'Hole',$,$,{slab_place},"
                 f"{b.shape(b.extrude(b.rect(4500, 1500, 1000, 1000), 200))},$,.OPENING.)")
    b.add(f"IFCRELVOIDSELEMENT('{gid(12)}',$,$,$,{slab},{hole})")
    b.contain(slab)
    return b.text()


def test_import_slab_with_holes_and_an_opening(sc):
    """CATCHES: a slab's arbitrary profile with voids losing its holes, or an IfcOpeningElement through it not coming in
    as a shaft; the floor's top, thickness, area and openings must be read from the extrusion."""
    sc.write("slab.ifc", holed_slab_text())
    sc.run(["run", "slab.ifc", "--cmd", 'elements {"category": "floor"}', "--cmd", 'elements {"category": "shaft"}'])
    assert sc.transcript() == sc.golden()


def test_import_flat_roof_slab(sc):
    """CATCHES: a slab whose predefined type is ROOF read as a floor instead of a flat roof by its footprint."""
    sc.write("roofslab.ifc", holed_slab_text(".ROOF."))
    sc.run(["run", "roofslab.ifc", "--cmd", 'elements {"category": "roof"}', "--cmd", 'elements {"category": "floor"}'])
    assert sc.transcript() == sc.golden()


def walled_box(b: Ifc, w=6000, d=4000, h=3000, t=200) -> list[str]:
    """Four walls round a w x d box, their axes on its edges."""
    return [
        b.wall("South", (0, 0), (w, 0), t, h),
        b.wall("East", (w, 0), (w, d), t, h),
        b.wall("North", (w, d), (0, d), t, h),
        b.wall("West", (0, d), (0, 0), t, h),
    ]


def test_import_spaces_become_rooms(sc):
    """CATCHES: IfcSpace not read as a room at a point inside its footprint, its Name and LongName not taken as number and
    name, a space without a LongName not numbered on, or a space with no body not placed at its own origin."""
    b = Ifc()
    walls = walled_box(b)
    b.wall("Middle", (3000, 0), (3000, 4000), 100, 3000)
    walls.append(f"#{b.n - 1}")
    s1 = b.add(f"IFCSPACE('{gid(1)}',$,'101',$,$,{b.place()},{b.shape(b.brep(0, 0, 0, 3000, 4000, 2800))},'Kitchen',.ELEMENT.,.SPACE.,$)")
    s2 = b.add(f"IFCSPACE('{gid(2)}',$,'Lounge',$,$,{b.place()},{b.shape(b.brep(3000, 0, 0, 6000, 4000, 2800))},$,.ELEMENT.,.SPACE.,$)")
    s3 = b.add(f"IFCSPACE('{gid(3)}',$,$,$,$,{b.place(9000, 9000, 0)},$,$,.ELEMENT.,.SPACE.,$)")
    b.contain(*walls)
    b.add(f"IFCRELAGGREGATES('{gid(4)}',$,$,$,#7,({s1},{s2},{s3}))")
    sc.write("rooms.ifc", b.text())
    sc.run(["run", "rooms.ifc", "--cmd", 'elements {"category": "room"}'])
    assert sc.transcript() == sc.golden()


def test_import_structural_members(sc):
    """CATCHES: a column whose Pset_ColumnCommon says LoadBearing not made a structural column, a round column not read
    as round, a beam extruded along x not read as a beam with its section, or a pad and a strip footing confused."""
    b = Ifc()
    up = (0, 0, 1)
    c1 = b.add(f"IFCCOLUMN('{gid(1)}',$,'C1',$,$,{b.place(0, 0, 0)},{b.shape(b.extrude(b.rect(0, 0, 300, 500), 3000))},$,.COLUMN.)")
    circle = b.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,{b.add(f'IFCAXIS2PLACEMENT2D({b.pt(0, 0)},$)')},200.)")
    c2 = b.add(f"IFCCOLUMN('{gid(2)}',$,'C2',$,$,{b.place(6000, 0, 0)},{b.shape(b.extrude(circle, 3000, up))},$,.COLUMN.)")
    beam_place = b.place(0, 0, 2750, axis=(1, 0, 0), ref=(0, 1, 0))
    beam = b.add(f"IFCBEAM('{gid(3)}',$,'B1',$,$,{beam_place},{b.shape(b.extrude(b.rect(0, 0, 200, 500), 6000))},$,.BEAM.)")
    pad = b.add(f"IFCFOOTING('{gid(4)}',$,'F1',$,$,{b.place(0, 0, -500)},"
                f"{b.shape(b.extrude(b.rect(0, 0, 1200, 1200), 500))},$,.PAD_FOOTING.)")
    strip_place = b.place(0, 4000, -400, axis=(1, 0, 0), ref=(0, 1, 0))
    strip = b.add(f"IFCFOOTING('{gid(5)}',$,'S1',$,$,{strip_place},"
                  f"{b.shape(b.extrude(b.rect(0, 0, 600, 400), 6000))},$,.STRIP_FOOTING.)")
    prop = b.add("IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.T.),$)")
    pset = b.add(f"IFCPROPERTYSET('{gid(6)}',$,'Pset_ColumnCommon',$,({prop}))")
    b.add(f"IFCRELDEFINESBYPROPERTIES('{gid(7)}',$,$,$,({c1}),{pset})")
    b.contain(c1, c2, beam, pad, strip)
    sc.write("structure.ifc", b.text())
    sc.run(["run", "structure.ifc", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_import_unknown_entities_are_listed_as_left_out(sc):
    """CATCHES: products BIMCraft has no element for (plates, members, a flow terminal, a building element part) being
    dropped silently, or not counted by class in `skipped`; a door in no wall must be said to be in none."""
    b = Ifc()
    w = b.wall("Wall", (0, 0), (5000, 0), 200, 3000)
    things = [
        b.add(f"IFCPLATE('{gid(1)}',$,'Plate A',$,$,{b.place()},{b.shape(b.brep(0, 1000, 0, 1000, 1010, 2000))},$,$)"),
        b.add(f"IFCPLATE('{gid(2)}',$,'Plate B',$,$,{b.place()},{b.shape(b.brep(0, 2000, 0, 1000, 2010, 2000))},$,$)"),
        b.add(f"IFCMEMBER('{gid(3)}',$,'Mullion',$,$,{b.place()},{b.shape(b.brep(0, 3000, 0, 50, 3050, 2000))},$,$)"),
        b.add(f"IFCFLOWTERMINAL('{gid(4)}',$,'Terminal',$,$,{b.place()},$,$)"),
        b.add(f"IFCBUILDINGELEMENTPART('{gid(5)}',$,'Part',$,$,{b.place()},$,$,$)"),
        b.add(f"IFCDOOR('{gid(6)}',$,'Lonely Door',$,$,{b.place(8000, 0, 0)},$,'D9',2100.,900.,$,$,$)"),
    ]
    b.contain(w, *things)
    sc.write("unknown.ifc", b.text())
    sc.run(["run", "unknown.ifc"])
    assert sc.transcript() == sc.golden()


def test_import_far_from_the_origin_is_moved_near_it(sc):
    """CATCHES: a site at map coordinates (hundreds of km out) not brought near the origin by whole kilometres, or the
    distance it moved not reported as `moved`."""
    b = Ifc()
    site = b.place(512_345_678, 7_654_321_000, 0, rel="$")
    walls = []
    for name, a, c in [("A", (0, 0), (5000, 0)), ("B", (5000, 0), (5000, 3000))]:
        (x0, y0), (x1, y1) = a, c
        import math

        length = math.hypot(x1 - x0, y1 - y0)
        place = b.place(x0, y0, 0, axis=(0, 0, 1), ref=((x1 - x0) / length, (y1 - y0) / length, 0), rel=site)
        body = b.extrude(b.rect(length / 2, 0, length, 200), 3000)
        walls.append(b.add(f"IFCWALL('{gid(b.n)}',$,'{name}',$,$,{place},{b.shape(body, axis_items=[b.polyline((0, 0), (length, 0))])},$,$)"))
    b.contain(*walls)
    sc.write("far.ifc", b.text())
    sc.run(["run", "far.ifc", "--cmd", 'elements {"category": "wall"}'])
    assert sc.transcript() == sc.golden()


def test_import_property_sets_become_project_parameters(sc):
    """CATCHES: property values of another program's sets not read as project parameters of the right kind (text,
    yes/no, length in mm from the file's unit, number), a property name a formula can't say not tidied, or the values not
    put on the elements the set is related to."""
    b = Ifc(units="#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n#2=IFCUNITASSIGNMENT((#1));")
    w1 = b.wall("W1", (0, 0), (5, 0), 0.2, 3)
    w2 = b.wall("W2", (5, 0), (5, 4), 0.2, 3)
    props = [
        b.add("IFCPROPERTYSINGLEVALUE('Fire Rating',$,IFCLABEL('REI 60'),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('IsExternal',$,IFCBOOLEAN(.T.),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Cladding Depth',$,IFCLENGTHMEASURE(0.025),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Cargas (G2)',$,IFCREAL(1.5),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Layers',$,IFCINTEGER(3),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Note',$,IFCTEXT('Caf\\X2\\00E9\\X0\\ side'),$)"),
    ]
    pset = b.add(f"IFCPROPERTYSET('{gid(1)}',$,'Acme_Wall',$,({','.join(props)}))")
    b.add(f"IFCRELDEFINESBYPROPERTIES('{gid(2)}',$,$,$,({w1},{w2}),{pset})")
    other = b.add("IFCPROPERTYSINGLEVALUE('Fire Rating',$,IFCLABEL('REI 30'),$)")
    pset2 = b.add(f"IFCPROPERTYSET('{gid(3)}',$,'Acme_Other',$,({other}))")
    b.add(f"IFCRELDEFINESBYPROPERTIES('{gid(4)}',$,$,$,({w2}),{pset2})")
    b.contain(w1, w2)
    sc.write("props.ifc", b.text())
    sc.run(["run", "props.ifc", "--cmd", 'elements {"category": "wall"}', "--cmd", 'library {"kind": "parameter"}'])
    assert sc.transcript() == sc.golden()


def test_import_material_layers_and_colours(sc):
    """CATCHES: a wall's IfcMaterialLayerSetUsage not read into its type's layers (from the exterior, as the usage stacks
    them), a layer's material missing from the library, or a material's surface style colour and transparency lost."""
    b = Ifc()
    w = b.wall("Layered", (0, 0), (5000, 0), 250, 3000)
    brick = b.add("IFCMATERIAL('Red Brick',$,$)")
    plaster = b.add("IFCMATERIAL('Lime Plaster',$,$)")
    l1 = b.add(f"IFCMATERIALLAYER({brick},200.,$,$,$,'Structure',$)")
    l2 = b.add(f"IFCMATERIALLAYER({plaster},50.,$,$,$,'Finish',$)")
    lset = b.add(f"IFCMATERIALLAYERSET(({l1},{l2}),'Brick and plaster',$)")
    usage = b.add(f"IFCMATERIALLAYERSETUSAGE({lset},.AXIS2.,.POSITIVE.,-125.,$)")
    b.add(f"IFCRELASSOCIATESMATERIAL('{gid(1)}',$,$,$,({w}),{usage})")
    colour = b.add("IFCCOLOURRGB($,0.8,0.2,0.1)")
    shading = b.add(f"IFCSURFACESTYLESHADING({colour},0.25)")
    style = b.add(f"IFCSURFACESTYLE('Brick red',.BOTH.,({shading}))")
    styled = b.add(f"IFCSTYLEDITEM($,({style}),$)")
    srep = b.add(f"IFCSTYLEDREPRESENTATION($,'Style','Material',({styled}))")
    b.add(f"IFCMATERIALDEFINITIONREPRESENTATION($,$,({srep}),{brick})")
    b.contain(w)
    sc.write("layers.ifc", b.text())
    p = sc.run(["run", "layers.ifc", "--cmd", 'elements {"category": "wall"}', "--cmd", "inspect {}"], show=False)
    lines = out(p).splitlines()
    inspect = json.loads(lines[2])
    sc.note(f"exit {p.returncode}")
    sc.note("\n".join(lines[:2]))
    sc.note(json.dumps(inspect["types"]["wall"], indent=1, sort_keys=True))
    sc.note(json.dumps({k: v for k, v in inspect["materials"].items() if k in ("Red Brick", "Lime Plaster")}, sort_keys=True))
    assert sc.transcript() == sc.golden()


def test_import_stair_of_flights_and_landing(sc):
    """CATCHES: a stair not measured from its flights' treads: two flights of steps stacked as boxes, the second turned
    back beside the first after a landing, must come in as one stair with its riser count, tread, width and a landing that
    turns 180 degrees; the railing among its parts must come in along it."""
    b = Ifc()
    items1, items2 = [], []
    for i in range(5):  # first flight: north-east along x, treads 280 deep, risers 175
        items1.append(b.brep(i * 280, 0, 0, (i + 1) * 280, 1000, (i + 1) * 175))
    for i in range(5):  # second flight: back along -x beside it, from 875 up
        x1 = 1400 - i * 280
        items2.append(b.brep(x1 - 280, 1100, 875, x1, 2100, 875 + (i + 1) * 175))
    f1 = b.add(f"IFCSTAIRFLIGHT('{gid(1)}',$,'Run 1',$,$,{b.place()},{b.shape(*items1, rep='Brep')},$,6,5,175.,280.,.STRAIGHT.)")
    f2 = b.add(f"IFCSTAIRFLIGHT('{gid(2)}',$,'Run 2',$,$,{b.place()},{b.shape(*items2, rep='Brep')},$,6,5,175.,280.,.STRAIGHT.)")
    rail = b.add(f"IFCRAILING('{gid(3)}',$,'Rail',$,$,{b.place()},"
                 f"{b.shape(b.polyline((0, 0, 1175), (1400, 0, 2050)), kind='Axis', rep='Curve3D')},$,.HANDRAIL.)")
    stair = b.add(f"IFCSTAIR('{gid(4)}',$,'Stair',$,$,{b.place()},$,$,.HALF_TURN_STAIR.)")
    b.add(f"IFCRELAGGREGATES('{gid(5)}',$,$,$,{stair},({f1},{f2},{rail}))")
    b.contain(stair)
    sc.write("stair.ifc", b.text())
    sc.run(["run", "stair.ifc", "--cmd", 'elements {"category": "stair"}', "--cmd", 'elements {"category": "railing"}'])
    assert sc.transcript() == sc.golden()


def test_import_ramp_from_its_sloping_top(sc):
    """CATCHES: a ramp's slope not read from its sloping top face (a wedge 6 m long rising 500 mm is 8.33 per cent), or
    its width, start and direction misread."""
    b = Ifc()
    pts = "(0.,0.,0.),(6000.,0.,0.),(6000.,1200.,0.),(0.,1200.,0.),(6000.,0.,500.),(6000.,1200.,500.)"
    tris = "(1,3,2),(1,4,3),(1,2,5),(1,5,6),(1,6,4),(2,3,6),(2,6,5),(3,4,6)"
    lst = b.add(f"IFCCARTESIANPOINTLIST3D(({pts}))")
    mesh = b.add(f"IFCTRIANGULATEDFACESET({lst},$,.T.,({tris}),$)")
    ramp = b.add(f"IFCRAMP('{gid(1)}',$,'Ramp',$,$,{b.place(1000, 2000, 0)},{b.shape(mesh, rep='Tessellation')},$,.STRAIGHT_RUN_RAMP.)")
    b.contain(ramp)
    sc.write("ramp.ifc", b.text())
    sc.run(["run", "ramp.ifc", "--cmd", 'elements {"category": "ramp"}'])
    assert sc.transcript() == sc.golden()


def test_import_ceiling_grid_room_separator_and_railing(sc):
    """CATCHES: an IfcCovering CEILING not read as a ceiling at its underside's height, an IfcGrid's axes not each a grid
    line with their tags (a SameSense of false reversing one), a RoomSeparation virtual element not a room separator, or
    a railing standing alone not read along its axis."""
    b = Ifc()
    walls = walled_box(b)
    cover = b.add(f"IFCCOVERING('{gid(1)}',$,'Ceiling',$,$,{b.place(0, 0, 2600)},"
                  f"{b.shape(b.extrude(b.rect(3000, 2000, 5800, 3800), 20))},$,.CEILING.)")
    ax = []
    for tag, line, sense in [("A", ((0, -1000), (0, 5000)), ".T."), ("B", ((6000, -1000), (6000, 5000)), ".F."),
                             ("1", ((-1000, 0), (7000, 0)), ".T.")]:
        ax.append(b.add(f"IFCGRIDAXIS('{tag}',{b.polyline(*line)},{sense})"))
    grid = b.add(f"IFCGRID('{gid(2)}',$,'Grid',$,$,{b.place()},$,({ax[0]},{ax[1]}),({ax[2]}),$,$)")
    sep_axis = b.shape(b.polyline((3000, 0), (3000, 4000)), kind="Axis", rep="Curve2D")
    sep = b.add(f"IFCVIRTUALELEMENT('{gid(3)}',$,'Room Separation Line',$,'RoomSeparation',{b.place()},{sep_axis},$)")
    rail_axis = b.shape(b.polyline((0, -1000, 1000), (6000, -1000, 1000)), kind="Axis", rep="Curve3D")
    rail = b.add(f"IFCRAILING('{gid(4)}',$,'Guard',$,$,{b.place()},{rail_axis},$,.GUARDRAIL.)")
    b.contain(*walls, cover, grid, sep, rail)
    sc.write("misc.ifc", b.text())
    sc.run(["run", "misc.ifc", "--cmd", 'elements {"category": "ceiling"}', "--cmd", 'elements {"category": "grid"}',
            "--cmd", 'elements {"category": "roomseparator"}', "--cmd", 'elements {"category": "railing"}'])
    assert sc.transcript() == sc.golden()


def test_import_furniture_as_components_of_families(sc):
    """CATCHES: furniture and proxies not read as components of families made of their bodies ("Family:Type" names split
    into family and type), two of one type not sharing it, or a furnishing element's own placement and turn lost."""
    b = Ifc()
    walls = walled_box(b, 8000, 6000)
    top = b.brep(-600, -300, 700, 600, 300, 750)
    leg = b.brep(-600, -300, 0, -550, -250, 700)
    t1 = b.add(f"IFCFURNITURE('{gid(1)}',$,'Desk:1200 x 600',$,$,{b.place(2000, 2000, 0)},{b.shape(top, leg, rep='Brep')},$,.TABLE.)")
    top2 = b.brep(-600, -300, 700, 600, 300, 750)
    leg2 = b.brep(-600, -300, 0, -550, -250, 700)
    t2 = b.add(f"IFCFURNITURE('{gid(2)}',$,'Desk:1200 x 600',$,$,{b.place(5000, 3000, 0, axis=(0, 0, 1), ref=(0, 1, 0))},"
               f"{b.shape(top2, leg2, rep='Brep')},$,.TABLE.)")
    box = b.brep(-250, -250, 0, 250, 250, 900)
    proxy = b.add(f"IFCBUILDINGELEMENTPROXY('{gid(3)}',$,'Plinth',$,$,{b.place(6500, 1000, 0)},{b.shape(box, rep='Brep')},$,$)")
    b.contain(*walls, t1, t2, proxy)
    sc.write("furniture.ifc", b.text())
    sc.run(["run", "furniture.ifc", "--cmd", 'elements {"category": "component"}', "--cmd", 'family {"name": "Desk"}'])
    assert sc.transcript() == sc.golden()


def test_import_curved_wall_on_a_trimmed_circle(sc):
    """CATCHES: a wall whose axis is an IfcTrimmedCurve on an IfcCircle not read as a curved wall with its arc, ends and
    thickness (the spread of its body round the centre)."""
    b = Ifc()
    centre = b.add(f"IFCAXIS2PLACEMENT2D({b.pt(0, 0)},$)")
    circle = b.add(f"IFCCIRCLE({centre},5000.)")
    trimmed = b.add(f"IFCTRIMMEDCURVE({circle},(IFCPARAMETERVALUE(0.)),(IFCPARAMETERVALUE(1.5707963267948966)),.T.,.PARAMETER.)")
    # The body: a quarter ring 200 thick, as a mesh of its corners every 15 degrees.
    import math

    pts, n = [], 7
    for k in range(n):
        a = math.radians(15 * k)
        for r in (4900, 5100):
            for z in (0, 3000):
                pts.append(f"({r * math.cos(a):.4f},{r * math.sin(a):.4f},{z}.)")
    tris = []
    for k in range(n - 1):
        i, j = 4 * k + 1, 4 * (k + 1) + 1  # inner bottom, inner top, outer bottom, outer top
        tris += [(i, j, j + 2), (i, j + 2, i + 2), (i + 1, i + 3, j + 3), (i + 1, j + 3, j + 1),
                 (i, i + 1, j + 1), (i, j + 1, j), (i + 2, j + 2, j + 3), (i + 2, j + 3, i + 3)]
    tris += [(1, 3, 4), (1, 4, 2)]
    last = 4 * (n - 1) + 1
    tris += [(last, last + 1, last + 3), (last, last + 3, last + 2)]
    lst = b.add(f"IFCCARTESIANPOINTLIST3D(({','.join(pts)}))")
    mesh = b.add(f"IFCTRIANGULATEDFACESET({lst},$,.T.,({','.join(f'({a},{c},{d})' for a, c, d in tris)}),$)")
    shape = b.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({b.add(f'IFCSHAPEREPRESENTATION($,{chr(39)}Axis{chr(39)},{chr(39)}Curve2D{chr(39)},({trimmed}))')},"
                  f"{b.add(f'IFCSHAPEREPRESENTATION($,{chr(39)}Body{chr(39)},{chr(39)}Tessellation{chr(39)},({mesh}))')}))")
    wall = b.add(f"IFCWALL('{gid(1)}',$,'Curved',$,$,{b.place()},{shape},$,$)")
    b.contain(wall)
    sc.write("curved.ifc", b.text())
    sc.run(["run", "curved.ifc", "--cmd", 'elements {"category": "wall"}'])
    assert sc.transcript() == sc.golden()


def test_import_column_profiles(sc):
    """CATCHES: profile definitions not read into a column's section: an I-shape and an L-shape by their overall width and
    depth, an ellipse, a hollow circle as round, an arbitrary closed polyline and a derived (rotated) profile."""
    b = Ifc()
    o2 = lambda: b.add(f"IFCAXIS2PLACEMENT2D({b.pt(0, 0)},$)")  # noqa: E731
    profiles = [
        f"IFCISHAPEPROFILEDEF(.AREA.,'HEA 300',{o2()},300.,290.,8.5,14.,27.,$,$)",
        f"IFCLSHAPEPROFILEDEF(.AREA.,'L 150',{o2()},150.,100.,12.,$,$,$,$)",
        f"IFCELLIPSEPROFILEDEF(.AREA.,$,{o2()},300.,150.)",
        f"IFCCIRCLEHOLLOWPROFILEDEF(.AREA.,$,{o2()},250.,10.)",
        f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{b.polyline((-200, -100), (200, -100), (200, 100), (-200, 100), (-200, -100))})",
    ]
    base = b.add(f"IFCRECTANGLEPROFILEDEF(.AREA.,'R',{o2()},600.,200.)")
    op = b.add(f"IFCCARTESIANTRANSFORMATIONOPERATOR2D({b.dir(0, 1)},{b.dir(-1, 0)},{b.pt(0, 0)},$)")
    profiles.append(f"IFCDERIVEDPROFILEDEF(.AREA.,$,{base},{op},'Turned')")
    cols = []
    for i, prof in enumerate(profiles):
        p = b.add(prof)
        cols.append(b.add(f"IFCCOLUMN('{gid(i + 1)}',$,'Col {i + 1}',$,$,{b.place(i * 2000, 0, 0)},{b.shape(b.extrude(p, 3000))},$,.COLUMN.)"))
    b.contain(*cols)
    sc.write("profiles.ifc", b.text())
    sc.run(["run", "profiles.ifc", "--cmd", 'elements {"category": "column"}'])
    assert sc.transcript() == sc.golden()


def ifc4_wall_with_openings(door_op: str = "$", door_type: str = "", window_height: float = 1200.0) -> str:
    """A 6 m wall 200 thick and 3 m high, with a door and a window in openings through it (IFC4)."""
    b = Ifc()
    wall = b.wall("Wall", (0, 0), (6000, 0), 200, 3000)
    made = []
    for i, (cls, x, sill, w, h, tag, extra) in enumerate([
        ("IFCDOOR", 1000, 0, 900, 2100, "D1", f",.DOOR.,{door_op},$"),
        ("IFCWINDOW", 4000, 900, 1200, window_height, "W1", ",.WINDOW.,.SINGLE_PANEL.,$"),
    ]):
        place = b.place(x, -100, sill)
        body = b.shape(b.extrude(b.rect(w / 2, 100, w, 200), h))
        opening = b.add(f"IFCOPENINGELEMENT('{gid(10 + i)}',$,'Opening',$,$,{place},{body},$,.OPENING.)")
        b.add(f"IFCRELVOIDSELEMENT('{gid(20 + i)}',$,$,$,{wall},{opening})")
        product = b.add(f"{cls}('{gid(30 + i)}',$,'{cls[3:].title()}',$,$,{place},{body},'{tag}',{float(h)},{float(w)}{extra})")
        b.add(f"IFCRELFILLSELEMENT('{gid(40 + i)}',$,$,$,{opening},{product})")
        made.append(product)
    if door_type:
        t = b.add(door_type)
        b.add(f"IFCRELDEFINESBYTYPE('{gid(50)}',$,$,$,({made[0]}),{t})")
    b.contain(wall, *made)
    return b.text()


def test_import_ifc4_door_operation_from_its_type(sc):
    """CATCHES: an IFC4 door's operation not read from its IfcDoorType when the door gives none (a double swing), its
    window's sill not measured from the wall's base, or the tags not taken as marks."""
    door_type = f"IFCDOORTYPE('{gid(60)}',$,'Double Leaf',$,$,$,$,$,$,.DOOR.,.DOUBLE_DOOR_SINGLE_SWING.,.F.,$)"
    sc.write("doors.ifc", ifc4_wall_with_openings(door_type=door_type))
    sc.run(["run", "doors.ifc", "--cmd", 'elements {"category": "door"}', "--cmd", 'elements {"category": "window"}'])
    assert sc.transcript() == sc.golden()


def test_import_ifc4_sliding_door_operation_on_the_door(sc):
    """CATCHES: an IFC4 door's own OperationType (SLIDING_TO_RIGHT) ignored, or its hand not flipped for RIGHT."""
    sc.write("sliding.ifc", ifc4_wall_with_openings(door_op=".SLIDING_TO_RIGHT."))
    sc.run(["run", "sliding.ifc", "--cmd", 'elements {"category": "door"}'])
    assert sc.transcript() == sc.golden()


def test_import_window_taller_than_its_wall_is_left_out(sc):
    """CATCHES: a window rising past its wall's top (as Revit allows) breaking the import or coming in, instead of being
    left out with its wall named as the file names it and both heights said."""
    sc.write("tall.ifc", ifc4_wall_with_openings(window_height=2500.0))
    sc.run(["run", "tall.ifc"])
    assert sc.transcript() == sc.golden()


def test_import_cable_and_pipe_runs(sc):
    """CATCHES: a cable segment swept as a disk along an indexed polycurve not read as a wire of the disk's diameter, a
    pipe segment extruded along its own axis not read as a pipe with its height, or a system grouping not kept."""
    b = Ifc()
    lst = b.add("IFCCARTESIANPOINTLIST3D(((0.,0.,0.),(3000.,0.,0.)))")
    curve = b.add(f"IFCINDEXEDPOLYCURVE({lst},(IFCLINEINDEX((1,2))),$)")
    disk = b.add(f"IFCSWEPTDISKSOLID({curve},3.7,$,$,$)")
    cable = b.add(f"IFCCABLESEGMENT('{gid(1)}',$,'Cable',$,$,{b.place(1000, 2000, 2900)},{b.shape(disk, rep='AdvancedSweptSolid')},$,.CABLESEGMENT.)")
    circle = b.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,{b.add(f'IFCAXIS2PLACEMENT2D({b.pt(0, 0)},$)')},25.)")
    pipe_place = b.place(0, 500, 600, axis=(1, 0, 0), ref=(0, 1, 0))
    pipe = b.add(f"IFCPIPESEGMENT('{gid(2)}',$,'Pipe',$,$,{pipe_place},{b.shape(b.extrude(circle, 4000))},$,.RIGIDSEGMENT.)")
    system = b.add(f"IFCDISTRIBUTIONSYSTEM('{gid(3)}',$,'Hot Water',$,$,$,.DOMESTICHOTWATER.)")
    b.add(f"IFCRELASSIGNSTOGROUP('{gid(4)}',$,$,$,({pipe}),$,{system})")
    b.contain(cable, pipe)
    sc.write("runs.ifc", b.text())
    sc.run(["run", "runs.ifc", "--cmd", 'elements {"category": "wire"}', "--cmd", 'elements {"category": "pipe"}'])
    assert sc.transcript() == sc.golden()


def test_import_unicode_names_round_trip(sc):
    """CATCHES: \\X2\\ and \\X4\\ escapes or doubled quotes in STEP strings not decoded back into the names written: the
    project's, a level's and a room's."""
    sc.run(["run", "--cmd", 'new {"name": "Casa d\'Água 😀"}', "--cmd",
            'wall {"points": [[0,0],[5000,0],[5000,4000],[0,4000]], "closed": true}',
            "--cmd", 'room {"point": [2500, 2000], "name": "Ñandú\'s — Sala"}',
            "--cmd", 'level {"elevation": 6000, "name": "Étage ½"}', "--save", "names.ifc"], show=False)
    sc.run(["run", "names.ifc", "--cmd", 'elements {"category": "room"}', "--cmd", 'elements {"category": "level"}'])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Files that are not what they say, and STEP's corners.
# ---------------------------------------------------------------------------

GOOD_WALL = Ifc()
GOOD_WALL.contain(GOOD_WALL.wall("Wall", (0, 0), (4000, 0), 200, 3000))
GOOD_TEXT = GOOD_WALL.text()

BROKEN = {
    "empty": "",
    "not_step": "hello, this is not an IFC file\n",
    "no_data_section": "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nEND-ISO-10303-21;\n",
    "string_never_ends": GOOD_TEXT.split("'Hand Made'")[0] + "'Hand Made",
    "string_unclosed_to_a_later_quote": GOOD_TEXT.replace("'Hand Made'", "'Hand Made"),
    "unexpected_character": GOOD_TEXT.replace("#4=IFCCARTESIANPOINT((0.,0.,0.));", "#4=IFCCARTESIANPOINT((0.,@,0.));"),
    "bad_entity_number": GOOD_TEXT.replace("#4=IFCCARTESIANPOINT", "#X=IFCCARTESIANPOINT"),
    "missing_semicolon": GOOD_TEXT.replace("#5=IFCAXIS2PLACEMENT3D(#4,$,$);", "#5=IFCAXIS2PLACEMENT3D(#4,$,$)"),
    "bad_number": GOOD_TEXT.replace("#4=IFCCARTESIANPOINT((0.,0.,0.));", "#4=IFCCARTESIANPOINT((0.,1.2.3e,0.));"),
    "enum_never_closes": GOOD_TEXT.split(".ELEMENT.")[0] + ".ELEMENT",
    "binary_never_closes": GOOD_TEXT.split("ENDSEC;\nEND-ISO")[0] + '#901=IFCPIXELTEXTURE($,$,$,$,$,1,1,1,("0FF',
    "truncated": GOOD_TEXT[: len(GOOD_TEXT) // 2],
    "lists_nested_too_deep": GOOD_TEXT.replace("#4=IFCCARTESIANPOINT((0.,0.,0.));", "#4=IFCCARTESIANPOINT(" + "(" * 40 + "0." + ")" * 40 + ");"),
    "other_step_schema": GOOD_TEXT.replace("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'))"),
    "no_schema": GOOD_TEXT.replace("FILE_SCHEMA(('IFC4'));\n", ""),
    "entity_without_a_name": GOOD_TEXT.replace("#4=IFCCARTESIANPOINT((0.,0.,0.));", "#4=((0.,0.,0.));"),
    "no_project": GOOD_TEXT.replace("#3=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,'Hand Made',$,$,$,$,$,#2);\n", ""),
    "unusable_length_unit": GOOD_TEXT.replace(
        MM_UNITS,
        "#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n#8=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(0.),#1);\n"
        "#9=IFCCONVERSIONBASEDUNIT($,.LENGTHUNIT.,'NOTHING',#8);\n#2=IFCUNITASSIGNMENT((#9));"),
}


import pytest  # noqa: E402


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_file_is_refused_with_why(sc, case):
    """CATCHES: a malformed or foreign STEP file opening as an empty project, crashing, or failing without saying the
    file, the line and what was wrong; `convert` must write nothing, and `info` must fail the same way."""
    sc.write("broken.ifc", BROKEN[case])
    sc.run(["run", "broken.ifc"])
    sc.run(["convert", "broken.ifc", "out.bimcraft"])
    sc.run(["info", "broken.ifc"])
    sc.note(f"out.bimcraft written: {(sc.workdir / 'out.bimcraft').exists()}")
    assert sc.transcript() == sc.golden()


def test_step_corners_comments_complex_instances_case_and_named_data(sc):
    """CATCHES: a STEP reader that fails on what ISO 10303-21 allows: comments anywhere, CRLF line ends, entity names in
    lower case, a named DATA section (edition 3), a complex instance `(A()B())`, binary "..." values and \\X\\ and \\S\\
    escapes; the wall must still come in, named from its escapes."""
    text = GOOD_TEXT.replace("DATA;", "DATA('main',('IFC4'));")
    text = text.replace("IFCCARTESIANPOINT", "IfcCartesianPoint").replace("IFCWALL(", "ifcWall(")
    text = text.replace("'Wall'", "'W\\X\\E4nde \\S\\D /* not a comment */'")
    text = text.replace("'Hand Made'", r"'Gr\X\FC\X\DF \S\D \PA\ok \\ back \q \X2\00C9\X0\t\X4\0001F3E0\X0\'")
    text = text.replace("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA((*,'ifc4'))")
    text = text.replace("ENDSEC;\nEND-ISO", "#900=(IFCLENGTHMEASURE(1.)IFCLABEL('x'));\n/* a comment\nover lines */\n"
                        "#901=IFCPIXELTEXTURE($,$,$,$,$,1,1,1,(\"0FF\"));\nENDSEC;\nEND-ISO")
    text = text.replace("\n", "\r\n")
    sc.write("corners.ifc", text)
    sc.run(["run", "corners.ifc", "--cmd", 'elements {"category": "wall"}'])
    assert sc.transcript() == sc.golden()


def test_storeys_by_elevation_attribute_and_the_first_project(sc):
    """CATCHES: a storey with no placement not taken at its Elevation attribute, storeys not sorted lowest first, two
    storeys of one name not told apart, a file with no storey not given a Level 1, or the project named from a second
    IfcProject instead of the first."""
    b = Ifc(units="#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n#2=IFCUNITASSIGNMENT((#1));")
    b.add(f"IFCBUILDINGSTOREY('{gid(1)}',$,'Upper',$,$,$,$,$,.ELEMENT.,6.5)")
    b.add(f"IFCBUILDINGSTOREY('{gid(2)}',$,'Middle',$,$,$,$,$,.ELEMENT.,3.25)")
    b.add(f"IFCBUILDINGSTOREY('{gid(3)}',$,'Middle',$,$,$,$,$,.ELEMENT.,4.)")
    b.add(f"IFCPROJECT('{gid(4)}',$,'Second Project',$,$,$,$,$,#2)")
    sc.write("storeys.ifc", b.text())
    sc.run(["run", "storeys.ifc", "--cmd", 'elements {"category": "level"}'])
    bare = (
        "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC2X3'));\nENDSEC;\nDATA;\n" + MM_UNITS + "\n"
        "#3=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,$,$,$,'Long Project Name',$,$,#2);\nENDSEC;\nEND-ISO-10303-21;\n"
    )
    sc.write("bare.ifc", bare)
    sc.run(["run", "bare.ifc", "--cmd", 'elements {"category": "level"}'])
    nameless = bare.replace("'Long Project Name'", "$")
    sc.write("nameless-file.ifc", nameless)
    sc.run(["run", "nameless-file.ifc"])
    assert sc.transcript() == sc.golden()


def test_bodies_of_every_kind(sc):
    """CATCHES: a body description the reader can't measure: a boolean clipping result, a tapered extrusion, a polygonal
    face set, a face-based surface model, a shell-based surface model, an IfcBlock and a bounding box, a composite curve
    profile and an extrusion with its own position, each a column whose section and height must come out."""
    b = Ifc()
    o2 = lambda x=0, y=0: b.add(f"IFCAXIS2PLACEMENT2D({b.pt(x, y)},$)")  # noqa: E731
    items = []
    # Boolean clipping: a 400 x 400 box 3 m high, clipped by a half space (ignored: the first operand is measured).
    first = b.extrude(b.rect(0, 0, 400, 400), 3000)
    plane = b.add(f"IFCPLANE({b.add(f'IFCAXIS2PLACEMENT3D({b.pt(0, 0, 2800)},$,$)')})")
    half = b.add(f"IFCHALFSPACESOLID({plane},.F.)")
    items.append(b.add(f"IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,{first},{half})"))
    # Tapered extrusion.
    items.append(b.add(f"IFCEXTRUDEDAREASOLIDTAPERED({b.rect(0, 0, 500, 300)},$,{b.dir(0, 0, 1)},2500.,{b.rect(0, 0, 500, 300)})"))
    # Polygonal face set: a box 300 x 600 x 2000.
    lst = b.add("IFCCARTESIANPOINTLIST3D(((-150.,-300.,0.),(150.,-300.,0.),(150.,300.,0.),(-150.,300.,0.),"
                "(-150.,-300.,2000.),(150.,-300.,2000.),(150.,300.,2000.),(-150.,300.,2000.)))")
    faces = [b.add(f"IFCINDEXEDPOLYGONALFACE(({','.join(map(str, f))}))")
             for f in [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]]
    items.append(b.add(f"IFCPOLYGONALFACESET({lst},.T.,({','.join(faces)}),$)"))
    # Face-based surface model of a brep's shell.
    brep = b.brep(-200, -200, 0, 200, 200, 1500)
    shell = f"#{int(brep[1:]) - 1}"
    items.append(b.add(f"IFCFACEBASEDSURFACEMODEL(({b.add(f'IFCCONNECTEDFACESET(({b.lines[-2].split(chr(40), 2)[2].split(chr(41))[0]}))')}))"))
    items.append(b.add(f"IFCSHELLBASEDSURFACEMODEL(({shell}))"))
    # A block and a bounding box.
    items.append(b.add(f"IFCBLOCK({b.add(f'IFCAXIS2PLACEMENT3D({b.pt(-350, -250, 0)},$,$)')},700.,500.,2200.)"))
    items.append(b.add(f"IFCBOUNDINGBOX({b.pt(-100, -450, 0)},200.,900.,2400.)"))
    # A composite curve as a closed profile, extruded from a position of its own.
    segs = []
    corners = [(-250, -250), (250, -250), (250, 250), (-250, 250), (-250, -250)]
    for p, q in zip(corners, corners[1:]):
        segs.append(b.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,{b.polyline(p, q)})"))
    comp = b.add(f"IFCCOMPOSITECURVE(({','.join(segs)}),.F.)")
    prof = b.add(f"IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,{comp})")
    items.append(b.extrude(prof, 2700, at=(0, 0, 100)))
    cols = []
    for i, item in enumerate(items):
        rep = b.shape(item, rep="Body")
        cols.append(b.add(f"IFCCOLUMN('{gid(i + 1)}',$,'Body {i + 1}',$,$,{b.place(i * 2000, 0, 0)},{rep},$,.COLUMN.)"))
    b.contain(*cols)
    sc.write("bodies.ifc", b.text())
    sc.run(["run", "bodies.ifc", "--cmd", 'elements {"category": "column"}'])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# What an IFC file converts to, and other projects taking it in.
# ---------------------------------------------------------------------------


def test_convert_ifc_to_every_format(sc):
    """CATCHES: `convert IN.ifc OUT` not importing first, or writing the wrong thing for an extension: the project, its
    lowest level's plan as SVG and PNG, its 3D scene as glTF binary, and IFC again."""
    sc.write("w23.ifc", IFC2X3_HOUSE)
    for target in ["out.bimcraft", "plan.svg", "plan.png", "scene.glb", "again.ifc"]:
        sc.run(["convert", "w23.ifc", target])
    note_digest(sc, "out.bimcraft")
    sc.file("plan.svg")
    sc.file("plan.png")
    sc.file("scene.glb")
    sc.file("again.ifc")
    sc.run(["info", "out.bimcraft"], show=False)
    sc.run(["run", "out.bimcraft", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_same_ifc_file_reads_the_same_every_time(sc):
    """CATCHES: GUIDs of what an IFC file holds that are random, not made from the file: the same file opened twice must
    give every element, type and library entry the same GUID, and its walls' GlobalIds must be their GUIDs."""
    sc.write("w23.ifc", IFC2X3_HOUSE)
    first = sc.run(["run", "w23.ifc", "--cmd", "elements {}", "--cmd", 'library {"kind": "type:wall"}', "--cmd",
                    'ids_of {"ids": [100002, 100003]}'], show=False)
    second = sc.run(["run", "w23.ifc", "--cmd", "elements {}", "--cmd", 'library {"kind": "type:wall"}', "--cmd",
                     'ids_of {"ids": [100002, 100003]}'], show=False)
    sc.note(f"same both times: {first.stdout == second.stdout}")
    sc.note(out(first).splitlines()[-1])
    assert sc.transcript() == sc.golden()


def test_insert_from_an_ifc_file(sc):
    """CATCHES: `insert` of an .ifc not bringing its elements into the open project: ids taken here given anew, levels
    matched by name, what they point at following, and the reply's `ids`, `copies`, `library` and `left_out` lists."""
    sc.write("w23.ifc", IFC2X3_HOUSE)
    sc.run(["run", "--cmd", 'level {"elevation": 7000, "name": "Ground Floor"}', "--cmd",
            'wall {"points": [[0, 5000], [4000, 5000]]}', "--cmd", 'insert {"path": "w23.ifc"}',
            "--cmd", 'elements {"category": "door"}', "--cmd", 'elements {"category": "level"}'])
    sc.run(["run", "--cmd", 'insert {"path": "w23.ifc", "ids": [100003]}', "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_link_an_ifc_file(sc):
    """CATCHES: `link` of an .ifc not reading it as a reference: its name defaulting to the file's, its count of
    elements, and nothing of it becoming an element of the project; a link to a missing file must fail and say so."""
    sc.write("w23.ifc", IFC2X3_HOUSE)
    sc.run(["run", "--cmd", 'link {"path": "w23.ifc", "at": [10000, 0], "angle": 90}', "--cmd", "inspect {}"], show=False)
    sc.run(["run", "--cmd", 'link {"path": "w23.ifc", "at": [10000, 0], "angle": 90}', "--cmd", 'elements {}',
            "--cmd", "reload {}"])
    sc.run(["run", "--cmd", 'link {"path": "gone.ifc"}'])
    assert sc.transcript() == sc.golden()


def test_reinforcement_round_trip(sc):
    """CATCHES: reinforcing bars not exported as IfcReinforcingBar parts of the beam they reinforce, or not read back as
    rebar elements of it with their bars' diameters and counts."""
    sc.run(["run", "--cmd", 'beam {"points": [[0, 0], [5000, 0]], "level": "Level 2"}', "--cmd",
            'reinforce {"host": 100002, "cover": 30, "bottom": {"count": 3, "diameter": 12.5}, "top": {"count": 2, "diameter": 10},'
            ' "stirrup": {"diameter": 5, "spacing": 200}}',
            "--cmd", 'rebar {"points": [[500, 0, 100], [4500, 0, 100]], "diameter": 16, "host": 100002, "layer": "extra"}',
            "--save", "rebar.ifc"])
    sc.run(["run", "rebar.ifc", "--cmd", 'elements {"category": "rebar"}'])
    assert sc.transcript() == sc.golden()


def test_lofted_mass_and_shaped_floor_round_trip(sc):
    """CATCHES: a lofted mass not written as a triangulated face set with its BIMCraft_Mass property set and read back as a
    loft, or a floor whose top was shaped (a point raised) not written as a faceted Brep and read back with its shape."""
    sc.run(["run", "--cmd", 'mass {"boundary": [[0,0],[6000,0],[6000,6000],[0,6000]], "height": 9000, '
            '"top": [[1000,1000],[5000,1000],[5000,5000],[1000,5000]]}',
            "--cmd", 'floor {"boundary": [[10000,0],[16000,0],[16000,6000],[10000,6000]]}',
            "--cmd", 'add_point {"id": 100003, "at": [13000, 3000], "offset": 150}',
            "--save", "shapes.ifc"])
    sc.file("shapes.ifc")
    sc.run(["run", "shapes.ifc", "--cmd", 'elements {"category": "mass"}', "--cmd", 'elements {"category": "floor"}'])
    assert sc.transcript() == sc.golden()


PHASED = [
    'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}',
    'phase {"name": "Demolition", "after": "Existing"}',
    'door {"at": [4000, 0]}',
    'option {"set": "Kitchen", "options": ["Open", "Closed"]}',
    'modify {"id": 100002, "params": {"Phase Created": "Existing", "Phase Demolished": "Demolition"}}',
    'modify {"id": 100003, "params": {"Design Option": "Kitchen: Closed"}}',
    'phase_filter {"name": "Mine", "new": "overridden"}',
    'phase {"overrides": {"new": {"halftone": true}}}',
]


def test_full_phasing_round_trip(sc):
    """CATCHES: the project's phase filters, phase overrides and design option sets, an element's design option, or the
    implied first phase not read back from BIMCraft_Phasing as they were written."""
    sc.run(["run", *cmd_args(PHASED), "--save", "p.ifc"], show=False)
    sc.run(["run", "p.ifc", "--cmd", 'elements {"category": "wall"}', "--cmd", 'phase {}', "--cmd", 'phase_filter {"name": "Mine"}',
            "--cmd", 'option {"set": "Kitchen"}'])
    assert sc.transcript() == sc.golden()


def test_tampered_phasing_is_left_out_with_why(sc):
    """CATCHES: phase values another tool changed breaking the import instead of being left out and counted: a phase the
    project hasn't, a demolition before the element was made, a design option set that isn't JSON, a phase list that
    isn't names."""
    sc.run(["run", *cmd_args(PHASED), "--save", "p.ifc"], show=False)
    text = (sc.workdir / "p.ifc").read_text()
    text = text.replace("'Phase Created',$,IFCTEXT('Existing')", "'Phase Created',$,IFCTEXT('Nowhere')", 1)
    text = text.replace("IFCTEXT('Kitchen: Closed')", "IFCTEXT('Kitchen: Missing')")
    text = text.replace("'{\"Kitchen\":{\"options\":[\"Open\",\"Closed\"],\"primary\":\"Open\"}}'", "'{not json'")
    sc.write("tampered.ifc", text)
    sc.run(["run", "tampered.ifc", "--cmd", 'elements {"category": "wall", "limit": 1}', "--cmd", "phase {}"])
    early = (sc.workdir / "p.ifc").read_text().replace("'Phase Created',$,IFCTEXT('Existing')",
                                                         "'Phase Created',$,IFCTEXT('New Construction')", 1)
    sc.write("early.ifc", early)
    sc.run(["run", "early.ifc", "--cmd", 'elements {"category": "wall", "limit": 1}'])
    names = (sc.workdir / "p.ifc").read_text().replace("IFCPROPERTYLISTVALUE('Phases',$,(IFCTEXT('Existing'),",
                                                         "IFCPROPERTYLISTVALUE('Phases',$,(IFCINTEGER(4),")
    sc.write("names.ifc", names)
    sc.run(["run", "names.ifc", "--cmd", "phase {}"])
    assert sc.transcript() == sc.golden()


def test_roofs_round_trip(sc):
    """CATCHES: roofs not read back as BIMCraft writes them: a hipped roof with gables and per-edge slopes over its
    footprint, a roof round a courtyard, a roof by extrusion (its profile swept across), and a flat roof whose top was
    shaped by a raised point."""
    sc.run(["run",
            "--cmd", 'roof {"level": "Level 2", "boundary": [[0,0],[8000,0],[8000,6000],[0,6000]], "slope": 30, "gables": [1]}',
            "--cmd", 'roof {"level": "Level 2", "boundary": [[12000,0],[24000,0],[24000,12000],[12000,12000]], '
                     '"courtyards": [[[16000,4000],[16000,8000],[20000,8000],[20000,4000]]], "slope": 25, "overhang": 0}',
            "--cmd", 'roof {"level": "Level 2", "extrusion": {"line": [[0,20000],[8000,20000]], '
                     '"profile": [[0,0],[4000,2000],[8000,0]], "to": 6000}}',
            "--cmd", 'roof {"level": "Level 2", "boundary": [[30000,0],[36000,0],[36000,6000],[30000,6000]], "slope": 0, "overhang": 0}',
            "--cmd", 'add_point {"id": 100005, "at": [33000, 3000], "offset": 200}',
            "--save", "roofs.ifc"])
    sc.run(["run", "roofs.ifc", "--cmd", 'elements {"category": "roof"}'])
    assert sc.transcript() == sc.golden()


def test_tampered_mass_rebar_and_separator_are_left_out(sc):
    """CATCHES: a lofted mass whose BIMCraft_Mass set is gone, a bar swept with a disk thicker than a bar can be, or a
    room separation line with no axis coming in anyway or stopping the import, instead of each being left out with why."""
    sc.run(["run", "--cmd", 'mass {"boundary": [[0,0],[6000,0],[6000,6000],[0,6000]], "height": 9000, '
            '"top": [[1000,1000],[5000,1000],[5000,5000],[1000,5000]]}',
            "--cmd", 'beam {"points": [[10000, 0], [15000, 0]], "level": "Level 2"}',
            "--cmd", 'rebar {"points": [[10500, 0, -400], [14500, 0, -400]], "diameter": 16, "host": 100003}',
            "--cmd", 'room_separator {"points": [[0, 8000], [6000, 8000]]}',
            "--save", "t.ifc"], show=False)
    text = (sc.workdir / "t.ifc").read_text()
    text = text.replace("'BIMCraft_Mass'", "'Somebody_Mass'")
    text = text.replace("IFCSWEPTDISKSOLID(", "IFCSWEPTDISKSOLID(").replace(",8.,$,$,$)", ",500.,$,$,$)")
    import re as _re

    text = _re.sub(r"(IFCVIRTUALELEMENT\('[^']*',\$,'[^']*',\$,'RoomSeparation',#\d+,)#\d+", r"\1$", text)
    sc.write("tampered.ifc", text)
    sc.run(["run", "tampered.ifc"])
    assert sc.transcript() == sc.golden()


def test_railing_with_no_axis_and_stairs_that_do_not_match(sc):
    """CATCHES: a railing with only a thin body not read along the middle of it at its top, a stair whose flights differ in
    width coming in instead of being left out, or a ramp of two flights not read with a landing between them."""
    b = Ifc()
    rail = b.add(f"IFCRAILING('{gid(1)}',$,'Thin Rail',$,$,{b.place()},{b.shape(b.brep(0, -50, 0, 4000, 0, 1100), rep='Brep')},$,.GUARDRAIL.)")
    f1 = b.add(f"IFCSTAIRFLIGHT('{gid(2)}',$,'Wide',$,$,{b.place(0, 2000, 0)},"
               f"{b.shape(*[b.brep(i * 280, 0, 0, (i + 1) * 280, 1200, (i + 1) * 175) for i in range(4)], rep='Brep')},$,5,4,175.,280.,.STRAIGHT.)")
    f2 = b.add(f"IFCSTAIRFLIGHT('{gid(3)}',$,'Narrow',$,$,{b.place(0, 2000, 0)},"
               f"{b.shape(*[b.brep(1400 + i * 280, 0, 875 + i * 175, 1400 + (i + 1) * 280, 800, 875 + (i + 1) * 175) for i in range(4)], rep='Brep')},"
               f"$,5,4,175.,280.,.STRAIGHT.)")
    stair = b.add(f"IFCSTAIR('{gid(4)}',$,'Odd Stair',$,$,{b.place()},$,$,.STRAIGHT_RUN_STAIR.)")
    b.add(f"IFCRELAGGREGATES('{gid(5)}',$,$,$,{stair},({f1},{f2}))")

    def wedge(x0, x1, z0, z1, y0=6000, y1=7200):
        pts = f"(({x0}.,{y0}.,{z0}.),({x1}.,{y0}.,{z0}.),({x1}.,{y1}.,{z0}.),({x0}.,{y1}.,{z0}.),({x0}.,{y0}.,{z0 + 1}.),({x1}.,{y0}.,{z1}.),({x1}.,{y1}.,{z1}.),({x0}.,{y1}.,{z0 + 1}.))"
        lst = b.add(f"IFCCARTESIANPOINTLIST3D({pts})")
        tris = "(1,3,2),(1,4,3),(5,6,7),(5,7,8),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,4,8),(3,8,7),(4,1,5),(4,5,8)"
        return b.add(f"IFCTRIANGULATEDFACESET({lst},$,.T.,({tris}),$)")

    r1 = b.add(f"IFCRAMPFLIGHT('{gid(6)}',$,'Up 1',$,$,{b.place()},{b.shape(wedge(0, 4000, 0, 334), rep='Tessellation')},$,$)")
    r2 = b.add(f"IFCRAMPFLIGHT('{gid(7)}',$,'Up 2',$,$,{b.place()},{b.shape(wedge(5500, 9500, 334, 668), rep='Tessellation')},$,$)")
    ramp = b.add(f"IFCRAMP('{gid(8)}',$,'Long Ramp',$,$,{b.place()},$,$,.STRAIGHT_RUN_RAMP.)")
    b.add(f"IFCRELAGGREGATES('{gid(9)}',$,$,$,{ramp},({r1},{r2}))")
    b.contain(rail, stair, ramp)
    sc.write("odd.ifc", b.text())
    sc.run(["run", "odd.ifc", "--cmd", 'elements {"category": "railing"}', "--cmd", 'elements {"category": "ramp"}'])
    assert sc.transcript() == sc.golden()


def ring_mesh(b: Ifc, r0: float, r1: float, a0: float, a1: float, h: float, steps: int = 6) -> str:
    """A triangle mesh of a ring's piece between radii r0 and r1, from angle a0 to a1 (degrees), h high."""
    import math

    pts = []
    for k in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * k / steps)
        for r in (r0, r1):
            for z in (0, h):
                pts.append(f"({r * math.cos(a):.4f},{r * math.sin(a):.4f},{float(z)})")
    tris = []
    for k in range(steps):
        i, j = 4 * k + 1, 4 * (k + 1) + 1
        tris += [(i, j, j + 2), (i, j + 2, i + 2), (i + 1, i + 3, j + 3), (i + 1, j + 3, j + 1),
                 (i, i + 1, j + 1), (i, j + 1, j), (i + 2, j + 2, j + 3), (i + 2, j + 3, i + 3)]
    last = 4 * steps + 1
    tris += [(1, 3, 4), (1, 4, 2), (last, last + 1, last + 3), (last, last + 3, last + 2)]
    lst = b.add(f"IFCCARTESIANPOINTLIST3D(({','.join(pts)}))")
    return b.add(f"IFCTRIANGULATEDFACESET({lst},$,.T.,({','.join(f'({x},{y},{z})' for x, y, z in tris)}),$)")


def test_wall_axes_of_every_curve_kind(sc):
    """CATCHES: a wall axis the reader can't follow: an indexed polycurve with no segments, a composite curve with a
    reversed segment, a line trimmed by parameters (with its vector's length) or by points, a circle trimmed by points the
    other way round (clockwise), and a wall placed through a chain of relative, turned placements."""
    b = Ifc()
    walls = []

    def wall(name, axis_curve, body, place="#6"):
        shape = b.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({b.add(f'IFCSHAPEREPRESENTATION($,{chr(39)}Axis{chr(39)},{chr(39)}Curve2D{chr(39)},({axis_curve}))')},"
                      f"{b.add(f'IFCSHAPEREPRESENTATION($,{chr(39)}Body{chr(39)},{chr(39)}Brep{chr(39)},({body}))')}))")
        walls.append(b.add(f"IFCWALL('{gid(len(walls) + 1)}',$,'{name}',$,$,{place},{shape},$,$)"))

    lst = b.add("IFCCARTESIANPOINTLIST2D(((0.,0.),(5000.,0.)))")
    wall("Indexed", b.add(f"IFCINDEXEDPOLYCURVE({lst},$,$)"), b.brep(0, -100, 0, 5000, 100, 3000))
    s1 = b.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,{b.polyline((0, 2000), (2000, 2000))})")
    s2 = b.add(f"IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.F.,{b.polyline((5000, 2000), (2000, 2000))})")
    wall("Composite", b.add(f"IFCCOMPOSITECURVE(({s1},{s2}),.F.)"), b.brep(0, 1900, 0, 5000, 2100, 3000))
    vec = b.add(f"IFCVECTOR({b.dir(1, 0)},1000.)")
    line = b.add(f"IFCLINE({b.pt(0, 4000)},{vec})")
    wall("Line by parameters", b.add(f"IFCTRIMMEDCURVE({line},(IFCPARAMETERVALUE(0.)),(IFCPARAMETERVALUE(5.)),.T.,.PARAMETER.)"),
         b.brep(0, 3900, 0, 5000, 4100, 3000))
    line2 = b.add(f"IFCLINE({b.pt(0, 6000)},{b.add(f'IFCVECTOR({b.dir(1, 0)},1.)')})")
    wall("Line by points", b.add(f"IFCTRIMMEDCURVE({line2},({b.pt(0, 6000)}),({b.pt(5000, 6000)}),.T.,.CARTESIAN.)"),
         b.brep(0, 5900, 0, 5000, 6100, 3000))
    circle = b.add(f"IFCCIRCLE({b.add(f'IFCAXIS2PLACEMENT2D({b.pt(20000, 0)},$)')},4000.)")
    arc = b.add(f"IFCTRIMMEDCURVE({circle},({b.pt(20000, 4000)}),({b.pt(24000, 0)}),.F.,.CARTESIAN.)")
    body = ring_mesh(b, 3900, 4100, 90, 0, 3000)
    # The ring's mesh is round the origin: the wall's own placement puts it round the circle's centre.
    wall("Clockwise arc", arc, body)
    walls.pop()
    b.lines = [ln for ln in b.lines if "'Clockwise arc'" not in ln]
    arc_place = b.place(20000, 0, 0)
    circle2 = b.add(f"IFCCIRCLE({b.add(f'IFCAXIS2PLACEMENT2D({b.pt(0, 0)},$)')},4000.)")
    arc2 = b.add(f"IFCTRIMMEDCURVE({circle2},({b.pt(0, 4000)}),({b.pt(4000, 0)}),.F.,.CARTESIAN.)")
    wall("Clockwise arc", arc2, body, place=arc_place)
    outer = b.place(30000, 0, 0, axis=(0, 0, 1), ref=(0, 1, 0))
    inner = b.place(1000, 0, 0, axis=(0, 0, 1), ref=(0, 1, 0), rel=outer)
    wall("Nested placement", b.polyline((0, 0), (4000, 0)), b.brep(0, -100, 0, 4000, 100, 2500), place=inner)
    b.contain(*walls)
    sc.write("axes.ifc", b.text())
    sc.run(["run", "axes.ifc", "--cmd", 'elements {"category": "wall"}'])
    assert sc.transcript() == sc.golden()


def test_mapped_items_scaled_and_turned(sc):
    """CATCHES: a mapped item's transformation operator ignored: a uniform scale of 2, a non-uniform one, an operator
    turned a quarter round, and a representation map with an origin of its own, each a column whose section and height
    must follow."""
    b = Ifc()
    o3 = b.add(f"IFCAXIS2PLACEMENT3D({b.pt(0, 0, 0)},$,$)")
    rep = b.add(f"IFCSHAPEREPRESENTATION($,'Body','SweptSolid',({b.extrude(b.rect(0, 0, 300, 200), 1000)}))")
    rmap = b.add(f"IFCREPRESENTATIONMAP({o3},{rep})")
    moved_origin = b.add(f"IFCAXIS2PLACEMENT3D({b.pt(500, 0, 0)},$,$)")
    rmap2 = b.add(f"IFCREPRESENTATIONMAP({moved_origin},{rep})")
    ops = [
        (rmap, f"IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,{b.pt(0, 0, 0)},2.,$)"),
        (rmap, f"IFCCARTESIANTRANSFORMATIONOPERATOR3DNONUNIFORM($,$,{b.pt(0, 0, 0)},1.,$,3.,2.5)"),
        (rmap, f"IFCCARTESIANTRANSFORMATIONOPERATOR3D({b.dir(0, 1, 0)},$,{b.pt(0, 0, 0)},$,{b.dir(0, 0, 1)})"),
        (rmap2, f"IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,{b.pt(0, 0, 500)},$,$)"),
    ]
    cols = []
    for i, (m, op) in enumerate(ops):
        item = b.add(f"IFCMAPPEDITEM({m},{b.add(op)})")
        shape = b.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({b.add(f'IFCSHAPEREPRESENTATION($,{chr(39)}Body{chr(39)},{chr(39)}MappedRepresentation{chr(39)},({item}))')}))")
        cols.append(b.add(f"IFCCOLUMN('{gid(i + 1)}',$,'Mapped {i + 1}',$,$,{b.place(i * 3000, 0, 0)},{shape},$,.COLUMN.)"))
    b.contain(*cols)
    sc.write("mapped.ifc", b.text())
    sc.run(["run", "mapped.ifc", "--cmd", 'elements {"category": "column"}'])
    assert sc.transcript() == sc.golden()


def test_products_without_a_readable_body_are_left_out_with_why(sc):
    """CATCHES: products with no representation (a wall, a column, a beam, a stair, a ramp, a railing, a mass proxy, a
    slab, a covering, a roof) crashing the import or coming in as empty elements, instead of each being listed with why;
    a door whose wall was left out must say so, and a space with neither body nor placement be placed at the origin."""
    b = Ifc()
    p = b.place()
    things = [
        b.add(f"IFCWALL('{gid(1)}',$,'Bodiless Wall',$,$,{p},$,$,$)"),
        b.add(f"IFCCOLUMN('{gid(2)}',$,'Bodiless Column',$,$,{p},$,$,.COLUMN.)"),
        b.add(f"IFCBEAM('{gid(3)}',$,'Bodiless Beam',$,$,{p},$,$,.BEAM.)"),
        b.add(f"IFCSTAIR('{gid(4)}',$,'Bodiless Stair',$,$,{p},$,$,.STRAIGHT_RUN_STAIR.)"),
        b.add(f"IFCRAMP('{gid(5)}',$,'Bodiless Ramp',$,$,{p},$,$,.STRAIGHT_RUN_RAMP.)"),
        b.add(f"IFCRAILING('{gid(6)}',$,'Bodiless Railing',$,$,{p},$,$,.GUARDRAIL.)"),
        b.add(f"IFCBUILDINGELEMENTPROXY('{gid(7)}',$,'Bodiless Mass',$,'Mass',{p},$,$,$)"),
        b.add(f"IFCSLAB('{gid(8)}',$,'Bodiless Slab',$,$,{p},$,$,.FLOOR.)"),
        b.add(f"IFCCOVERING('{gid(9)}',$,'Bodiless Ceiling',$,$,{p},$,$,.CEILING.)"),
        b.add(f"IFCROOF('{gid(10)}',$,'Bodiless Roof',$,$,{p},$,$,.FLAT_ROOF.)"),
        b.add(f"IFCFOOTING('{gid(11)}',$,'Bodiless Footing',$,$,{p},$,$,.PAD_FOOTING.)"),
        b.add(f"IFCPIPESEGMENT('{gid(12)}',$,'Bodiless Pipe',$,$,{p},$,$,.RIGIDSEGMENT.)"),
        b.add(f"IFCREINFORCINGBAR('{gid(13)}',$,'Bodiless Bar',$,$,{p},$,$,$,12.,$,$,$,.MAIN.,.TEXTURED.)"),
        b.add(f"IFCVIRTUALELEMENT('{gid(14)}',$,'Bodiless Separator',$,'RoomSeparation',{p},$,$)"),
    ]
    opening = b.add(f"IFCOPENINGELEMENT('{gid(15)}',$,'Opening',$,$,{p},$,$,.OPENING.)")
    b.add(f"IFCRELVOIDSELEMENT('{gid(16)}',$,$,$,{things[0]},{opening})")
    door = b.add(f"IFCDOOR('{gid(17)}',$,'Orphan Door',$,$,{p},$,'D1',2100.,900.,$,$,$)")
    b.add(f"IFCRELFILLSELEMENT('{gid(18)}',$,$,$,{opening},{door})")
    space = b.add(f"IFCSPACE('{gid(19)}',$,'S1',$,$,$,$,'Nowhere',.ELEMENT.,.SPACE.,$)")
    b.contain(*things, door, space)
    sc.write("bodiless.ifc", b.text())
    sc.run(["run", "bodiless.ifc", "--cmd", 'elements {"category": "room"}'])
    assert sc.transcript() == sc.golden()


def test_more_property_kinds_marks_and_family_clashes(sc):
    """CATCHES: a structural program's names not kept as marks of beams and columns (but not when the name is only the
    type's), IFCIDENTIFIER, IFCLOGICAL, IFCPOSITIVELENGTHMEASURE, IFCNUMERICMEASURE and IFCCOUNTMEASURE values not read,
    values of other kinds (an IFCLABEL list, an IFCLOGICAL unknown) taken as parameters, or a property named as a
    family's parameter on a component made a project parameter."""
    b = Ifc()
    col = b.add(f"IFCCOLUMN('{gid(1)}',$,'P1',$,$,{b.place(0, 0, 0)},{b.shape(b.extrude(b.rect(0, 0, 300, 300), 3000))},$,.COLUMN.)")
    beam_place = b.place(0, 0, 2700, axis=(1, 0, 0), ref=(0, 1, 0))
    beam = b.add(f"IFCBEAM('{gid(2)}',$,'Concrete 20x50',$,'Concrete 20x50',{beam_place},"
                 f"{b.shape(b.extrude(b.rect(0, 0, 200, 500), 5000))},$,.BEAM.)")
    chair = b.add(f"IFCFURNITURE('{gid(3)}',$,'Stool:Low',$,$,{b.place(2000, 2000, 0)},{b.shape(b.brep(-200, -200, 0, 200, 200, 450), rep='Brep')},$,.CHAIR.)")
    props = [
        b.add("IFCPROPERTYSINGLEVALUE('Code',$,IFCIDENTIFIER('X-1'),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Checked',$,IFCLOGICAL(.T.),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Unsure',$,IFCLOGICAL(.U.),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Cover',$,IFCPOSITIVELENGTHMEASURE(30.),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Ratio',$,IFCNUMERICMEASURE(0.25),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Bars',$,IFCCOUNTMEASURE(8),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Area',$,IFCAREAMEASURE(2.5),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('Empty',$,$,$)"),
        b.add("IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.F.),$)"),
        b.add("IFCPROPERTYSINGLEVALUE('***',$,IFCLABEL('nameless'),$)"),
    ]
    pset = b.add(f"IFCPROPERTYSET('{gid(4)}',$,'Eng_Data',$,({','.join(props)}))")
    b.add(f"IFCRELDEFINESBYPROPERTIES('{gid(5)}',$,$,$,({col},{beam}),{pset})")
    fam = [b.add("IFCPROPERTYSINGLEVALUE('Width',$,IFCLENGTHMEASURE(400.),$)"),
           b.add("IFCPROPERTYSINGLEVALUE('Maker',$,IFCLABEL('Acme'),$)")]
    pset2 = b.add(f"IFCPROPERTYSET('{gid(6)}',$,'Acme_Furniture',$,({','.join(fam)}))")
    b.add(f"IFCRELDEFINESBYPROPERTIES('{gid(7)}',$,$,$,({chair}),{pset2})")
    ours = b.add(f"IFCPROPERTYSET('{gid(8)}',$,'BIMCraft_Other',$,({b.add('IFCPROPERTYSINGLEVALUE(' + chr(39) + 'Hidden' + chr(39) + ',$,IFCLABEL(' + chr(39) + 'x' + chr(39) + '),$)')}))")
    b.add(f"IFCRELDEFINESBYPROPERTIES('{gid(9)}',$,$,$,({col}),{ours})")
    b.contain(col, beam, chair)
    sc.write("props2.ifc", b.text())
    sc.run(["run", "props2.ifc", "--cmd", 'elements {"category": "column"}', "--cmd", 'elements {"category": "beam"}',
            "--cmd", 'elements {"category": "component"}', "--cmd", 'library {"kind": "parameter"}'])
    assert sc.transcript() == sc.golden()


def test_export_door_in_a_curved_wall_odd_stairs_and_shared_layer_sets(sc):
    """CATCHES: a door's opening through a curved wall not reaching past the wall's bow, a stair of three landings not
    NOTDEFINED in shape, or two floors of one layered type not sharing a layer set; and each read back."""
    sc.run(["run",
            "--cmd", 'type {"category": "floor", "name": "Layered", "layers": [{"function": "finish", "material": "Screed", "thickness": 50}, '
                     '{"function": "structure", "material": "Concrete", "thickness": 150}]}',
            "--cmd", 'wall {"points": [[0,0],[8000,0]], "arc": 120}',
            "--cmd", 'door {"wall": 100002, "offset": 4000}',
            "--cmd", 'stair {"start": [20000, 0], "angle": 0, "landings": [{"at": 4, "turn": 90}, {"at": 8, "turn": 90}, {"at": 12, "turn": 90}]}',
            "--cmd", 'floor {"type": "Layered", "boundary": [[0,10000],[4000,10000],[4000,14000],[0,14000]]}',
            "--cmd", 'floor {"type": "Layered", "level": "Level 2", "boundary": [[0,10000],[4000,10000],[4000,14000],[0,14000]]}',
            "--save", "odd.ifc"])
    sc.file("odd.ifc")
    back = sc.run(["run", "odd.ifc", "--cmd", 'elements {"category": "door"}', "--cmd", 'elements {"category": "stair"}',
                   "--cmd", 'elements {"category": "floor"}'], show=False)
    note_rounded(sc, back)
    assert sc.transcript() == sc.golden()


def test_asymmetric_extruded_roof_and_off_centre_shaped_roof_round_trip(sc):
    """CATCHES: a roof by extrusion whose profile isn't symmetric (so no one slope all round) not read back as an
    extrusion with its profile, or a flat roof shaped off its centre not read back with its shape points."""
    sc.run(["run",
            "--cmd", 'roof {"level": "Level 2", "extrusion": {"line": [[0,0],[9000,0]], "profile": [[0,0],[3000,2000],[9000,500]], "to": 5000}}',
            "--cmd", 'roof {"level": "Level 2", "boundary": [[20000,0],[26000,0],[26000,6000],[20000,6000]], "slope": 0, "overhang": 0}',
            "--cmd", 'add_point {"id": 100003, "at": [21500, 1500], "offset": 250}',
            "--save", "roofs.ifc"], show=False)
    sc.run(["run", "roofs.ifc", "--cmd", 'elements {"category": "roof"}'])
    assert sc.transcript() == sc.golden()
