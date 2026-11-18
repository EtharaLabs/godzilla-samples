"""The runs of the MEP tabs: `pipe`, `duct`, `conduit`, `cable_tray`, `wire`, `down_conductor`, `ground_conductor` and
`cabling`. One run for each segment of the points, their default types and justification, heights that fall, rise and
stand, their refusals, Edit Type of a run type, their schedules, the plan that draws them, and IFC (their classes and
systems) there and back."""

import json

import pytest
from conftest import make_project, normalize, png_pixels

# command: (its shortcut, its category as `elements` takes it in the plural)
RUNS = {
    "pipe": ("PI", "pipes"),
    "duct": ("DU", "ducts"),
    "conduit": ("CN", "conduits"),
    "cable_tray": ("CT", "cabletrays"),
    "wire": ("EW", "wires"),
    "down_conductor": ("DC", "downconductors"),
    "ground_conductor": ("GC", "groundconductors"),
    "cabling": ("CB", "cables"),
}


@pytest.mark.parametrize("command", sorted(RUNS))
def test_a_run_is_made_for_each_segment_in_its_default_type(run, golden, command):
    """CATCHES: a rewrite that makes one element for a polyline instead of one for each segment, closes a ring wrongly,
    gives a run another default type, width, depth, roundness or justification (centre for these), puts its axis at
    another height, ignores the shortcut, or lists runs with other fields in `elements`."""
    alias, plural = RUNS[command]
    r = run(["run",
             "--cmd", f'{command} {{"points": [[0, 0], [6000, 0], [6000, 4000]]}}',
             "--cmd", f'{alias} {{"points": [[0, 0], [1000, 0], [1000, 1000]], "closed": true, "offset": 2700}}',
             "--cmd", f'elements {{"category": "{plural}"}}'])
    golden.check_run(r, f"made_{command}.txt")


def test_runs_fall_rise_stand_and_take_a_system(run, golden):
    """CATCHES: a rewrite that puts a run's heights on the wrong line of its section (`justify` top, centre, bottom; a
    sloped run is depth / cos deep vertically), does not stand a run whose two points are one with two heights, reads
    `justify` case-sensitively, or does not change a run's height, slope and system with `modify`."""
    r = run(["run",
             "--cmd", 'pipe {"points": [[0, 0], [6000, 0]], "offset": 2400, "end_offset": 2340, "system": "Esgoto", "level": "Level 1"}',
             "--cmd", 'pipe {"points": [[500, 500], [500, 500]], "offset": 0, "end_offset": 3000}',
             "--cmd", 'duct {"points": [[0, 3000], [4000, 3000]], "offset": 2800, "justify": "TOP"}',
             "--cmd", 'duct {"points": [[0, 4000], [3000, 4000]], "offset": 0, "end_offset": 4000, "justify": "bottom"}',
             "--cmd", 'down_conductor {"points": [[9000, 1000], [9000, 1000]], "offset": 6000, "end_offset": -500, "system": "SPDA"}',
             "--cmd", 'ground_conductor {"points": [[0, -1000], [9000, -1000], [9000, 9000]], "offset": -500, "system": "Anel"}',
             "--cmd", 'cable_tray {"points": [[0, 7000], [8000, 7000]], "offset": 2900, "level": "Level 2", "justify": "bottom"}',
             "--cmd", 'modify {"id": 100003, "offset": 100, "system": "Água fria"}',
             "--cmd", 'modify {"id": 100002, "end_offset": 2400, "justify": "top"}',
             "--cmd", "elements"])
    golden.check_run(r, "heights_and_systems.txt")


REFUSALS = [
    'pipe {"points": [[0, 0], [0, 0]]}',
    'duct {"points": [[0, 0], [0.5, 0]]}',
    'conduit {"points": [[0, 0]]}',
    'cable_tray {"points": [[0, 0], [3000, 0]], "type": "Nope"}',
    'wire {"points": [[0, 0], [3000, 0]], "type": "PVC 25"}',
    'cabling {"points": [[0, 0], [3000, 0]], "justify": "sideways"}',
    'down_conductor {"points": [[0, 0], [3000, 0]], "offset": 1e300}',
    'ground_conductor {"points": [[0, 0], [3000, 0]], "end_offset": "low"}',
    'pipe {"points": [[0, 0], [1000, 0], [2000, 0]], "end_offset": 100}',
    'pipe {"points": [[0, 0], [3000, 0, 5]]}',
    'pipe {"points": [[0, 0], [2e9, 0]]}',
    "pipe {}",
    'pipe {"points": "x"}',
    'duct {"points": [[0, 0], [3000, 0]], "level": "Level 9"}',
    'conduit {"points": [[0, 0], [3000, 0]], "closed": "yes"}',
    'wire {"points": [[0, 0], [3000, 0]], "system": "' + "x" * 300 + '"}',
    'cable_tray {"points": [[0, 0], [3000, 0]], "system": 5}',
]


def test_a_run_that_cannot_be_one_is_refused(run, golden):
    """CATCHES: a rewrite that makes a run of no length, of one point, of a type its category lacks (the list of the
    category's types in the refusal), of an unknown justification, beyond the model's reach, or a slope given with more
    than one segment, or that words any of these refusals differently."""
    parts = []
    for cmd in REFUSALS:
        r = run(["run", "--cmd", cmd])
        parts.append(f"$ {cmd[:120]}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    golden.check(normalize("".join(parts)), "refusals.txt")


def _mcp(run, calls):
    """The replies of the MCP server to `execute` calls of (command, params), one after another on one model."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}]
    for n, (command, params) in enumerate(calls, start=2):
        msgs.append({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                     "params": {"name": "execute", "arguments": {"command": command, "params": params}}})
    r = run(["mcp"], input="".join(json.dumps(m) + "\n" for m in msgs))
    replies = [json.loads(line) for line in r.stdout.decode().splitlines()[1:]]
    out = [f"exit: {r.returncode}"]
    for (command, _), reply in zip(calls, replies):
        res = reply["result"]
        out.append(f"{command} error={res.get('isError', False)}: " + "".join(c["text"] for c in res["content"]))
    return normalize("\n".join(out) + "\n")


def test_a_refused_run_changes_nothing(run, golden):
    """CATCHES: a rewrite that keeps the first segments of a polyline whose later segment is refused, instead of rolling
    the whole command back, or that leaves an undo step for a refused command."""
    text = _mcp(run, [("pipe", {"points": [[0, 0], [3000, 0]]}),
                      ("pipe", {"points": [[0, 1000], [3000, 1000], [3000, 1000]]}),
                      ("elements", {"category": "pipes"}),
                      ("undo", {}), ("undo", {})])
    golden.check(text, "refused_rolls_back.txt")


def test_edit_type_of_a_run_type(run, golden):
    """CATCHES: a rewrite whose `type` for a run category does not make the type (round or not, in a material of the
    library), does not change every run of a type it changes, keeps a round type's own depth, or accepts a material the
    library lacks."""
    r = run(["run",
             "--cmd", 'conduit {"points": [[0, 0], [3000, 0]], "type": "PVC 20"}',
             "--cmd", 'type {"category": "conduit", "name": "PVC 20", "width": 21.3}',
             "--cmd", 'type {"category": "cabletray", "name": "Ladder 400 x 100", "width": 400, "depth": 100, "material": "Metal"}',
             "--cmd", 'cable_tray {"points": [[0, 1000], [3000, 1000]], "type": "Ladder 400 x 100"}',
             "--cmd", 'type {"category": "downconductor", "name": "Flat 30 x 4", "width": 30, "depth": 4, "round": false, "material": "Copper"}',
             "--cmd", 'type {"category": "cable", "name": "Coax", "width": 7, "round": true, "material": "PVC"}',
             "--cmd", 'cabling {"points": [[0, 2000], [3000, 2000]], "type": "Coax"}',
             "--cmd", 'elements {"category": "conduits"}',
             "--cmd", 'elements {"category": "cables"}',
             "--cmd", 'library {"kind": "type:cabletray"}',
             "--cmd", 'type {"category": "pipe", "name": "Odd", "width": 75, "round": true, "material": "Unobtainium"}'])
    golden.check_run(r, "edit_type.txt")


def test_schedules_of_runs_by_system(run, golden):
    """CATCHES: a rewrite whose schedule of a run category has other columns (System, Length and Diameter for a round
    run, Width and Depth for a rectangular one), groups or sorts by system differently, or totals the lengths wrongly."""
    r = run(["run",
             "--cmd", 'pipe {"points": [[0, 0], [3000, 0], [3000, 2000]], "system": "AF"}',
             "--cmd", 'pipe {"points": [[0, 1000], [2000, 1000]], "system": "AF", "type": "PVC 25"}',
             "--cmd", 'pipe {"points": [[0, 2000], [5000, 2000]], "system": "ES", "type": "PVC 110"}',
             "--cmd", 'cable_tray {"points": [[0, 5000], [4000, 5000]], "system": "Força"}',
             "--cmd", 'schedule {"name": "Pipes", "category": "pipes"}',
             "--cmd", 'schedule {"name": "Pipes", "fields": ["System", "Type", "Length", "Count"], "sort": ["System", "Type"], "grouped": true}',
             "--cmd", 'schedule {"name": "By system", "category": "pipes", "fields": ["System", {"name": "Length", "total": true}], "sort": [{"field": "System", "descending": true}], "grouped": true}',
             "--cmd", 'schedule {"name": "Trays", "category": "cabletrays"}',
             "--cmd", 'schedule {"name": "All runs", "category": "multicategory", "categories": ["pipes", "cabletrays"], "fields": ["Category", "Type", "Length", "Material"]}'])
    golden.check_run(r, "schedules.txt")


def _mep(run):
    """A pipe system and runs of every tab at every height a plan treats differently."""
    return ["run",
            "--cmd", 'pipe {"points": [[0, 0], [6000, 0]], "offset": 2400, "system": "Cold water"}',
            "--cmd", 'pipe {"points": [[0, 3000], [4000, 3000]], "offset": 1000, "end_offset": 940, "justify": "top", "system": "Sewer"}',
            "--cmd", 'pipe {"points": [[500, 5000], [500, 5000]], "offset": 0, "end_offset": 3000}',
            "--cmd", 'pipe {"points": [[0, 6000], [4000, 6000]], "offset": -500, "type": "PVC 110"}',
            "--cmd", 'duct {"points": [[7000, 0], [7000, 6000]], "offset": 2600}',
            "--cmd", 'conduit {"points": [[1000, 1500], [5000, 1500]], "offset": 300, "system": "C1"}',
            "--cmd", 'cable_tray {"points": [[0, 8000], [5000, 8000]], "offset": 2800, "system": "C1"}',
            "--cmd", 'wire {"points": [[1000, 2000], [5000, 2000]], "offset": 1100, "system": "C1"}',
            "--cmd", 'down_conductor {"points": [[9000, 0], [9000, 0]], "offset": -500, "end_offset": 6000, "type": "Flat 25 x 3", "system": "SPDA"}',
            "--cmd", 'ground_conductor {"points": [[-1000, -1000], [10000, -1000]], "offset": -500, "system": "SPDA"}',
            "--cmd", 'cabling {"points": [[1000, 2500], [5000, 2500]], "offset": 2900, "system": "Rede"}']


def test_a_plan_draws_runs_through_its_cut_plane_overhead_and_below(run, workdir, golden):
    """CATCHES: a rewrite whose plan draws a run cut by the plane, overhead (dashed), under the level, standing (its
    section) or of another tab in other places, weights, colours or dash patterns than the reference."""
    r = run(_mep(run) + ["--save", "plan.svg"])
    assert r.returncode == 0, r.stderr
    golden.check((workdir / "plan.svg").read_text(), "plan.svg")


def test_a_plan_of_the_level_above_and_with_runs_hidden(run, workdir, golden):
    """CATCHES: a rewrite that draws a lower level's runs in the plan above, or still draws a category the view's
    Visibility/Graphics hides."""
    args = _mep(run) + ["--cmd", 'pipe {"points": [[0, 9000], [6000, 9000]], "level": "Level 2", "offset": 1000}',
                        "--cmd", 'render {"view": "Level 2", "path": "upper.svg"}',
                        "--cmd", 'graphics {"view": "Level 1", "hide": ["pipe", "cabletray", "downconductor"]}',
                        "--cmd", 'render {"view": "Level 1", "path": "hidden.svg"}']
    r = run(args)
    golden.check_run(r, "plan_upper_and_hidden.txt")
    golden.check((workdir / "upper.svg").read_text(), "upper.svg")
    golden.check((workdir / "hidden.svg").read_text(), "hidden.svg")


def test_ifc_writes_each_run_as_its_class_in_its_system(run, workdir, golden):
    """CATCHES: a rewrite that writes a run as another IFC class or predefined type than the reference's table gives its
    category (pipe segment, duct segment, conduit and tray carrier segments, cable and conductor segments), leaves out its
    IfcSystem and IfcRelAssignsToGroup, its BIMCraft_Run property set (justification, category) or its material."""
    make_project(run, workdir, "mep.bimcraft", _mep(run)[1:])
    r = run(["convert", "mep.bimcraft", "mep.ifc"])
    assert r.returncode == 0, r.stderr
    golden.check(normalize((workdir / "mep.ifc").read_text()), "mep.ifc")


def test_runs_come_back_from_ifc_with_their_category_justification_and_system(run, workdir, golden):
    """CATCHES: a rewrite whose IFC import of its own runs loses their category (a ground conductor is told from a down
    conductor, a data cable from a wire, by BIMCraft's Category), their justification, heights, type or system."""
    make_project(run, workdir, "mep.bimcraft", _mep(run)[1:])
    assert run(["convert", "mep.bimcraft", "mep.ifc"]).returncode == 0
    r = run(["run", "mep.ifc", "--cmd", "elements"])
    assert r.returncode == 0, r.stderr
    # The elements as they come back, without what the import makes anew (ids, GUIDs).
    rows = []
    for e in json.loads(r.stdout.decode().splitlines()[-1])["elements"]:
        if e["category"] in ("level", "view3d", "planview"):
            continue
        rows.append({k: v for k, v in e.items() if k not in ("guid", "id", "level", "type_guid")})
    rows.sort(key=lambda e: (e["category"], json.dumps(e, sort_keys=True)))
    golden.check(json.dumps(rows, indent=1, sort_keys=True, ensure_ascii=False) + "\n", "from_ifc.json")


def test_a_project_with_runs_saves_and_opens_again(run, workdir, golden):
    """CATCHES: a rewrite whose project file loses a run's justification, end height, system or type, or which reads
    them back differently."""
    r = run(_mep(run) + ["--save", "mep.bimcraft"])
    assert r.returncode == 0, r.stderr
    d = json.loads((workdir / "mep.bimcraft").read_text())
    runs = {k: v for k, v in d["elements"].items() if not any(t in v for t in ("Level", "View3D", "PlanView"))}
    golden.check(normalize(json.dumps(runs, indent=1, sort_keys=True, ensure_ascii=False) + "\n"), "saved_runs.json")
    r = run(["run", "mep.bimcraft", "--cmd", 'elements {"category": "downconductors"}', "--cmd", 'elements {"category": "wires"}'])
    golden.check_run(r, "reopened.txt")


def test_a_section_cuts_runs_square_and_aslant(run, workdir, golden):
    """CATCHES: a rewrite whose section does not cut a round run as a ring (an ellipse where it crosses aslant), a
    rectangular one as its section, or draws a run the section's line does not cross."""
    r = run(["run",
             "--cmd", 'pipe {"points": [[0, 2000], [6000, 2000]], "offset": 1000, "type": "PVC 110"}',
             "--cmd", 'pipe {"points": [[0, 3000], [6000, 4000]], "offset": 500, "end_offset": 900}',
             "--cmd", 'duct {"points": [[0, 1000], [6000, 1000]], "offset": 2500}',
             "--cmd", 'cable_tray {"points": [[0, 500], [6000, 500]], "offset": 2800, "justify": "top"}',
             "--cmd", 'conduit {"points": [[3000, 6000], [3000, 6000]], "offset": 0, "end_offset": 2000}',
             "--cmd", 'section {"start": [3000, -1000], "end": [3000, 5000], "name": "A"}',
             "--cmd", 'render {"view": "A", "path": "a.png"}'])
    golden.check_run(r, "section.txt")
    golden.check(png_pixels((workdir / "a.png").read_bytes()), "section_png.txt")
