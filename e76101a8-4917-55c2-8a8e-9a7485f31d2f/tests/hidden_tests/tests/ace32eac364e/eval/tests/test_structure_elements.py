"""The structure's elements: `column` and `structural_column`, `footing`, `beam` and `strip_footing` (and a structural
floor). Their defaults (types, heights, justification), refusals, types, schedules, the plan that draws them, IFC there and
back, a project file whose run type is impossible, and the `highrise` performance sample built of them."""

import json

import pytest
from conftest import make_project, normalize


def _transcript(run, commands):
    """Each command run in a process of its own (`run --cmd`): the command, its exit code, stdout and stderr, in turn."""
    parts = []
    for cmd in commands:
        r = run(["run", "--cmd", cmd])
        parts.append(f"$ {cmd}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    return normalize("".join(parts))


def _args(*commands):
    out = ["run"]
    for c in commands:
        out += ["--cmd", c]
    return out


def test_columns_and_footings_take_their_defaults(run, golden):
    """CATCHES: a rewrite whose column or structural column does not go up to the next level by default, or stands
    `height` mm tall from its `base_offset`; whose footing is not 400 mm thick with its top at the level (`offset` its top,
    so its base is `offset - thickness`); whose CL makes a structural column; or which counts the categories wrongly."""
    r = run(_args('column {"at": [0, 0]}',
                  'CL {"at": [3000, 0], "type": "Round 300", "angle": 30, "height": 2500, "base_offset": 200}',
                  'structural_column {"at": [6000, 0], "top_level": "Level 2"}',
                  'structural_column {"at": [9000, 0], "type": "Concrete Round 400", "level": "Level 2"}',
                  'structural_column {"at": [12000, 0], "type": "Concrete 200 x 500", "angle": 90, "height": 3200, "base_offset": -200}',
                  'footing {"at": [0, 0]}',
                  'FI {"at": [3000, 0], "type": "Footing 1500 x 1500", "thickness": 600, "offset": -1000, "angle": 45}',
                  'footing {"at": [6000, 0], "level": "Level 2", "offset": 200}',
                  "elements",
                  'elements {"category": "structural columns"}',
                  'elements {"category": "structural_column", "limit": 1, "offset": 2}',
                  'elements {"category": "footings", "level": "Level 2"}'))
    golden.check_run(r, "columns_and_footings.txt")


def test_beams_and_strip_footings_hang_from_their_heights(run, golden):
    """CATCHES: a rewrite whose beam's or strip footing's heights are not those of its top by default (so it hangs below
    the level), whose sloped beam is not depth / cos deep, that ignores `justify`, `system` or `closed`, or that puts a
    strip footing's top elsewhere than at `offset`."""
    r = run(_args('beam {"points": [[0, 0], [6000, 0], [6000, 6000]], "offset": 3000}',
                  'BM {"points": [[0, 6000], [6000, 6000]], "type": "Beam 150 x 400", "justify": "centre", "end_offset": 3500, "system": "Pórtico 1"}',
                  'beam {"points": [[0, 8000], [3000, 8000]], "offset": 0, "end_offset": 4000, "justify": "bottom"}',
                  'beam {"points": [[500, 9000], [3500, 10000]], "type": "Steel Tube 150", "offset": 3000, "level": "Level 2"}',
                  'beam {"points": [[0, 12000], [1000, 12000]], "end_offset": 3700}',
                  'strip_footing {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true, "offset": -300, "system": "Fundação"}',
                  'FW {"points": [[0, 2000], [6000, 2000]]}',
                  'elements {"category": "beams"}',
                  'elements {"category": "strip footings"}'))
    golden.check_run(r, "beams_and_strip_footings.txt")


REFUSALS = [
    'beam {"points": [[0, 0], [0, 0]], "end_offset": 3000}',
    'beam {"points": [[0, 0], [500, 0]], "end_offset": 3000}',
    'beam {"points": [[0, 0], [0, 0]]}',
    'beam {"points": [[0, 0], [3000, 0]], "type": "Rectangular 400 x 400"}',
    'beam {"points": [[0, 0], [3000, 0], [6000, 0]], "end_offset": 200}',
    'beam {"points": [[0, 0], [3000, 0]], "justify": "middle"}',
    'strip_footing {"points": [[0, 0], [0, 0]]}',
    'strip_footing {"points": [[0, 0], [3000, 0]], "type": "Beam 200 x 500"}',
    'footing {"at": [0, 0], "thickness": 0}',
    'footing {"at": [0, 0], "thickness": -5}',
    'footing {"at": [0, 0], "type": "Concrete 300 x 300"}',
    "footing {}",
    'footing {"at": [0, 0], "level": "Basement"}',
    'column {"at": [0, 0], "type": "Concrete 300 x 300"}',
    'structural_column {"at": [0, 0], "type": "Rectangular 400 x 400"}',
    'column {"at": [0, 0], "top_level": "Roof"}',
    'column {"at": [0, 0], "height": 0}',
    'structural_column {"at": [0, 0], "height": -100}',
    'column {"at": [0]}',
    'column {"at": [0, 0], "angle": "x"}',
    'structural_column {"at": [0, 0], "top_level": "Level 1"}',
    'column {"at": [0, 0], "level": "Level 2", "top_level": "Level 1"}',
    'structural_column {"at": [0, 0], "base_offset": 1e300}',
]


def test_structure_that_cannot_be_built_is_refused(run, golden):
    """CATCHES: a rewrite that lets a beam or strip footing stand or lean past 75°, takes another category's type,
    makes a footing of no thickness or a column whose top is not above its base, or words any refusal differently."""
    golden.check(_transcript(run, REFUSALS), "refusals.txt")


def test_types_of_the_structure(run, golden):
    """CATCHES: a rewrite whose `type` does not keep the structural column's, the footing's and the column's types
    apart, makes a round section deeper or shallower than wide, keeps a beam's old width where it is used, or accepts a
    beam type without a depth, of no width, of a material the library lacks, or of a category with no types."""
    commands = [
        'type {"category": "beam", "name": "IPE 200", "width": 100, "depth": 200, "material": "Metal"}',
        'type {"category": "beams", "name": "Tube 100", "width": 100, "round": true}',
        'type {"category": "stripfooting", "name": "Strip 800 x 300", "width": 800, "depth": 300}',
        'type {"category": "structural column", "name": "C 250 x 600", "width": 250, "depth": 600}',
        'type {"category": "footing", "name": "Round 1000", "width": 1000, "round": true}',
        'type {"category": "column", "name": "Round 300", "width": 350}',
        'type {"category": "beam", "name": "Odd", "width": 100, "depth": 200, "material": "Unobtainium"}',
        'type {"category": "beam", "name": "Flat", "width": 100}',
        'type {"category": "beam", "name": "Zero", "width": 0, "depth": 10}',
        'type {"category": "kettle", "name": "P", "width": 10}',
    ]
    r = run(_args(*commands[:6], 'beam {"points": [[0, 0], [3000, 0]], "type": "IPE 200"}',
                  'type {"category": "beam", "name": "IPE 200", "width": 150}',
                  'structural_column {"at": [0, 0], "type": "C 250 x 600"}', 'footing {"at": [0, 0], "type": "Round 1000"}',
                  'elements {"category": "beams"}', 'elements {"category": "footings"}',
                  'library {"kind": "type:structuralcolumn"}', 'library {"kind": "type:footing"}'))
    golden.check_run(r, "types_made.txt")
    golden.check(_transcript(run, commands[6:]), "types_refused.txt")


def _structure():
    """Beams at their heights (one sloped, one round, one drawn west), footings, strip footings, structural columns
    (round and turned), an architectural column, and a structural floor overhead: as the engine's own tests build it."""
    return [
        'beam {"points": [[0, 0], [6000, 0]], "offset": 3000}',
        'beam {"points": [[0, 3000], [4000, 3000]], "offset": 2800, "end_offset": 3400, "justify": "centre", "type": "Beam 150 x 400"}',
        'beam {"points": [[500, 5000], [3500, 4000]], "type": "Steel Tube 150", "offset": 3000, "end_offset": 3900, "justify": "centre"}',
        'footing {"at": [0, 0], "thickness": 500, "angle": 20, "type": "Footing 1500 x 1500"}',
        'footing {"at": [6000, 0]}',
        'strip_footing {"points": [[0, 0], [6000, 0], [6000, 5000]], "offset": -200}',
        'structural_column {"at": [4000, 3000], "type": "Concrete Round 400"}',
        'structural_column {"at": [5000, 3000], "type": "Concrete 200 x 500", "angle": 30}',
        'column {"at": [8000, 3000]}',
        'type {"category": "beam", "name": "B 250 x 600", "width": 250, "depth": 600, "material": "Concrete"}',
        'type {"category": "stripfooting", "name": "S 900 x 350", "width": 900, "depth": 350}',
        'type {"category": "structuralcolumn", "name": "C 250 x 600", "width": 250, "depth": 600}',
        'type {"category": "footing", "name": "F 1800", "width": 1800, "depth": 1800}',
        'beam {"points": [[6000, 6500], [0, 6500]], "type": "B 250 x 600", "offset": 3000}',
        'beam {"points": [[7500, 500], [6500, 4500]], "offset": 3000}',
        'strip_footing {"points": [[0, 5500], [3000, 5500]], "type": "S 900 x 350"}',
        'structural_column {"at": [1000, 4000], "type": "C 250 x 600"}',
        'footing {"at": [3000, 4000], "type": "F 1800", "offset": 3000, "thickness": 400}',
        'floor {"boundary": [[0, 0], [6000, 0], [6000, 5000], [0, 5000]], "structural": true, "offset": 3000}',
        'floor {"boundary": [[7000, 0], [9000, 0], [9000, 2000], [7000, 2000]]}',
    ]


def test_schedules_of_the_structure(run, golden):
    """CATCHES: a rewrite whose schedules of beams, strip footings, structural columns, footings and floors have other
    columns or values (a footing's Thickness, a beam's Length, Width and Depth, a floor's Structural), or that mixes the
    architectural and structural columns."""
    r = run(_args(*_structure(),
                  'schedule {"name": "B", "category": "beams"}',
                  'schedule {"name": "B", "fields": ["Type", "System", "Length", "Count"], "sort": ["Type"], "grouped": true}',
                  'schedule {"name": "S", "category": "strip footings"}',
                  'schedule {"name": "C", "category": "structural columns"}',
                  'schedule {"name": "A", "category": "columns"}',
                  'schedule {"name": "F", "category": "footings"}',
                  'schedule {"name": "Fl", "category": "floors", "fields": ["Id", "Structural", "Offset"]}'))
    golden.check_run(r, "schedules.txt")


def test_plans_draw_the_structure(run, workdir, golden):
    """CATCHES: a rewrite whose plan does not draw beams hanging under the level above as overhead, footings under the
    level, cut columns with their poché, a round column as a circle and a turned one turned, or whose plan of Level 2
    shows what stands below it."""
    r = run(_args(*_structure(), 'render {"view": "Level 1", "path": "l1.svg"}', 'render {"view": "Level 2", "path": "l2.svg"}'))
    assert r.returncode == 0, r.stderr
    golden.check((workdir / "l1.svg").read_text(), "level1.svg")
    golden.check((workdir / "l2.svg").read_text(), "level2.svg")


def test_ifc_writes_the_structure_with_its_profiles_and_load_bearing(run, workdir, golden):
    """CATCHES: a rewrite whose IFC writes a beam, a column or a footing other than as its class with a type carrying an
    IfcMaterialProfileSet (rectangle or circle profile, cardinal point by justification), a strip footing other than as a
    STRIP_FOOTING, leaves out LoadBearing, or writes a structural floor as not carrying load."""
    make_project(run, workdir, "s.bimcraft", _args(*_structure())[1:])
    r = run(["convert", "s.bimcraft", "s.ifc"])
    assert r.returncode == 0, r.stderr
    golden.check(normalize((workdir / "s.ifc").read_text()), "structure.ifc")


def test_the_structure_comes_back_from_ifc(run, workdir, golden):
    """CATCHES: a rewrite whose IFC import of its own structure loses a category (a structural column, a footing, a strip
    footing), a beam's justification, slope, type or section, a column's angle, or a floor's structural flag."""
    make_project(run, workdir, "s.bimcraft", _args(*_structure())[1:])
    assert run(["convert", "s.bimcraft", "s.ifc"]).returncode == 0
    r = run(["run", "s.ifc", "--cmd", "elements"])
    assert r.returncode == 0, r.stderr
    rows = []
    for e in json.loads(r.stdout.decode().splitlines()[-1])["elements"]:
        if e["category"] in ("level", "view3d", "planview"):
            continue
        keep = {k: v for k, v in e.items() if k not in ("guid", "id", "level", "top_level", "type_guid", "boundary_ids", "edges")}
        rows.append(keep)
    rows.sort(key=lambda e: (e["category"], json.dumps(e, sort_keys=True)))
    golden.check(json.dumps(rows, indent=1, sort_keys=True, ensure_ascii=False) + "\n", "from_ifc.json")


def test_a_project_with_an_impossible_run_type_is_refused(run, workdir, golden):
    """CATCHES: a rewrite that opens a project whose beam type is round but not as deep as it is wide, whose run types
    are of a category that has no runs, instead of refusing it with the reason."""
    assert run(["run", "--save", "base.bimcraft"]).returncode == 0
    base = json.loads((workdir / "base.bimcraft").read_text())
    cases = []
    odd = json.loads(json.dumps(base))
    odd["types"]["runs"]["beam"]["Odd"] = {"width": 100.0, "depth": 200.0, "round": True, "material": "Concrete"}
    cases.append(("round_not_square", odd))
    kettle = json.loads(json.dumps(base))
    kettle["types"]["runs"]["kettle"] = {}
    cases.append(("no_run_category", kettle))
    out = []
    for name, doc in cases:
        (workdir / f"{name}.bimcraft").write_text(json.dumps(doc))
        r = run(["run", f"{name}.bimcraft"])
        out.append(f"== {name}\nexit: {r.returncode}\n{r.stdout.decode()}{r.stderr.decode()}")
    golden.check(normalize("".join(out)), "impossible_run_types.txt")


def test_structure_moves_copies_rotates_mirrors_and_deletes(run, golden):
    """CATCHES: a rewrite whose move, rotate, mirror or copy of a beam, a structural column or a footing loses a run's
    heights (each end keeps its own), does not turn a column, or whose delete and undo of them differ."""
    r = run(_args('beam {"points": [[0, 0], [4000, 0]], "offset": 2800, "end_offset": 3000}',
                  'structural_column {"at": [0, 0], "angle": 0}', 'footing {"at": [0, 0]}',
                  'move {"ids": [100002, 100003, 100004], "by": [1000, 500]}',
                  'rotate {"ids": [100002, 100003], "about": [1000, 500], "angle": 90}',
                  'mirror {"ids": [100002], "axis": [[0, 0], [0, 1000]], "copy": true}',
                  'copy {"ids": [100002, 100003, 100004], "by": [0, -2000]}',
                  'delete {"ids": [100002, 100003, 100004]}', "undo",
                  'elements {"category": "beams"}', 'elements {"category": "structural columns"}', 'elements {"category": "footings"}'))
    golden.check_run(r, "edits.txt")


def test_highrise_builds_the_performance_sample(run, golden):
    """CATCHES: a rewrite whose `--highrise` sample differs in its storeys, levels, element counts by category (beams,
    structural columns, walls, windows, floors, ceilings, furniture), types, families or settings, or that prints no
    reply for it."""
    r = run(["run", "--highrise", "--cmd", "inspect"], timeout=600)
    golden.check_run(r, "highrise_inspect.txt")


def test_highrise_command_replaces_the_project(run, golden):
    """CATCHES: a rewrite whose `highrise` command keeps the project it replaces or its undo history, builds another
    number of storeys or elements, puts the storeys at other heights, or lays a storey's beams and columns out
    differently."""
    r = run(_args('wall {"points": [[0, 0], [1000, 0]]}', 'highrise {"storeys": 2}',
                  'elements {"category": "levels"}',
                  'schedule {"name": "Columns", "category": "structural columns", "fields": ["Level", "Type", "Count"], "sort": ["Level"], "grouped": true}',
                  'schedule {"name": "Beams", "category": "beams", "fields": ["Level", "Type", {"name": "Length", "total": true}, "Count"], "sort": ["Level"], "grouped": true}',
                  'elements {"category": "beams", "level": "Level 2", "limit": 3, "offset": 50}',
                  'elements {"category": "walls", "limit": 1}', "undo", "undo", "undo"), timeout=600)
    golden.check_run(r, "highrise_command.txt")


def test_highrise_refusals(run, golden):
    """CATCHES: a rewrite that builds a highrise of 0 or more than 80 storeys, of a fractional or negative count, or that
    takes unknown parameters, or words these refusals differently."""
    golden.check(_transcript(run, ['highrise {"storeys": 0}', 'highrise {"storeys": 81}', 'highrise {"storeys": 2.5}',
                                   'highrise {"storeys": -1}', 'highrise {"floors": 2}', "highrise []"]), "highrise_refusals.txt")


MODIFIED = [
    'modify {"id": 100002, "end_offset": 5000}',
    'modify {"id": 100002, "end": [500, 0], "end_offset": 3000}',
    'modify {"id": 100002, "end": [0, 0]}',
    'modify {"id": 100002, "type": "PVC 50"}',
    'modify {"id": 100002, "justify": "bottom", "system": "S", "type": "Beam 150 x 400"}',
    'modify {"id": 100003, "type": "Rectangular 400 x 400"}',
    'modify {"id": 100003, "top_level": null, "height": 2500, "angle": 45}',
    'modify {"id": 100004, "height": 600, "base_offset": -600, "type": "Footing 1500 x 1500"}',
    'modify {"id": 100004, "type": "Concrete 300 x 300"}',
    'modify {"id": 100005, "start": [0, 0], "end": [0, 0]}',
    'modify {"id": 100005, "end_offset": 3000, "end": [100, 0]}',
]


def test_modify_of_the_structure_is_checked(run, golden):
    """CATCHES: a rewrite whose `modify` lets a beam or strip footing stand or lean past 75° or shrink to nothing, gives a
    column, footing or run a type of another category, or lists a changed one with other heights, slope or length."""
    parts = []
    for m in MODIFIED:
        r = run(_args('beam {"points": [[0, 0], [6000, 0]]}', 'structural_column {"at": [0, 0]}', 'footing {"at": [0, 0]}',
                      'strip_footing {"points": [[0, 0], [6000, 0]]}', m))
        last = r.stdout.decode().splitlines()[-1] if r.returncode == 0 else ""
        parts.append(f"$ {m}\nexit: {r.returncode}\n{last}\n{r.stderr.decode()}")
    golden.check(normalize("".join(parts)), "modified.txt")
