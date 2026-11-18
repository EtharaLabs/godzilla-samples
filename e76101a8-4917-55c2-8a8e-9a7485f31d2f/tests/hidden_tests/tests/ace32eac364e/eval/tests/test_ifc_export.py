"""IFC export: projects built with commands, written as IFC4 (`convert p.bimcraft out.ifc`), compared entity by entity
with the reference's file, and read back in (`run out.ifc`).

Every project is made with `make_project`, which fixes its GUIDs: the export orders storeys by GUID and takes each
element's GlobalId from its GUID, so a project of random GUIDs would come out in another order each time.
"""

import re

import pytest
from conftest import make_project, normalize

# The time an IFC file was written, after a FILE_NAME whose string may hold doubled quotes (a project named `d'Água`),
# which conftest's `normalize` leaves alone.
STAMP_RE = re.compile(r"^(FILE_NAME\('(?:[^']|'')*',)'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d'", re.M)


def _ifc(path):
    """An exported IFC file's text, its random ids and the time it was written made placeholders."""
    return normalize(STAMP_RE.sub(lambda m: m.group(1) + "'<TIMESTAMP>'", path.read_text(encoding="utf-8")))

# Each scenario: a script of commands (one per line), the project the export is made of. Ids in it are the ids the
# script's own commands make, counting from 100002 (the two starter levels are 100000 and 100001).
SCENARIOS = {
    "walls": r"""
type {"category": "wall", "name": "Layered 300", "layers": [{"function": "finish", "material": "Brick", "thickness": 100}, {"function": "thermal", "material": "Insulation", "thickness": 50}, {"function": "structure", "material": "Concrete", "thickness": 140}, {"function": "finish", "material": "Plaster", "thickness": 10}]}
wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true, "type": "Layered 300"}
wall {"points": [[4000,0],[4000,6000]], "type": "Interior - 100mm"}
wall {"points": [[12000,0],[18000,0]], "arc": 90, "type": "Layered 300", "location": "interior-finish"}
wall {"points": [[12000,-3000],[18000,-3000]], "height": 2400, "base_offset": 300, "room_bounding": false}
door {"at": [2000, 0]}
door {"at": [4000, 3000], "flip_hand": true, "mark": "P7"}
window {"at": [8000, 3000], "mark": "W-01"}
door {"at": [6000, 6000], "family": "Sliding Door"}
window {"at": [2000, 6000], "family": "Casement Window", "type": "600 x 900"}
window {"at": [15000, -3000], "family": "Fixed Window", "type": "600 x 900", "sill": 1200}
door {"wall": 100007, "offset": 3000, "family": "Double Door"}
family {"name": "Plain Door", "category": "door", "parameters": [{"name": "Width", "kind": "length", "value": 900}, {"name": "Height", "kind": "length", "value": 2100}], "types": {"900 x 2100": {}}, "forms": [{"plane": "xz", "profile": [["-Width / 2", 0], ["Width / 2", 0], ["Width / 2", "Height"], ["-Width / 2", "Height"]], "from": -20, "to": 20, "material": "Timber"}]}
door {"at": [6000, 0], "family": "Plain Door"}
""",
    "attached": r"""
roof {"level": "Level 2", "boundary": [[-500,-500],[6500,-500],[6500,4500],[-500,4500]], "slope": 30, "gables": [1, 3]}
floor {"boundary": [[0,6000],[6000,6000],[6000,8000],[0,8000]], "offset": 600, "slope": 3, "arrow": [[0,6000],[6000,6000]]}
wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true, "attach_top": 100002}
wall {"points": [[0,7000],[6000,7000]], "attach_base": 100003, "height": 2000}
""",
    "slabs": r"""
wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}
wall {"points": [[4000,0],[4000,6000]]}
room_separator {"points": [[0,3000],[4000,3000]]}
floor {"openings": [[[1000,1000],[2000,1000],[2000,2000],[1000,2000]]]}
floor {"level": "Level 2", "boundary": [[0,0],[8000,0],[8000,6000],[0,6000]], "structural": true}
type {"category": "floor", "name": "Slab 250", "layers": [{"function": "finish", "material": "Ceramic tile", "thickness": 20}, {"function": "substrate", "material": "Screed", "thickness": 30}, {"function": "membrane", "material": "Membrane", "thickness": 0}, {"function": "structure", "material": "Concrete", "thickness": 200}]}
floor {"boundary": [[10000,0],[14000,0],[14000,4000],[10000,4000]], "type": "Slab 250", "offset": 100}
type {"category": "ceiling", "name": "Gypsum 50", "layers": [{"function": "finish", "material": "Gypsum board", "thickness": 12.5}, {"function": "thermal", "material": "Insulation", "thickness": 37.5}]}
ceiling {"point": [2000, 4500], "type": "Gypsum 50"}
ceiling {"point": [6000, 3000], "type": "Tile 600 x 600", "offset": 2400}
room {"point": [2000, 1500], "name": "Kitchen", "number": "1"}
room {"point": [2000, 4500], "name": "Dining"}
room {"point": [6000, 3000], "name": "Living"}
room {"point": [20000, 0], "name": "Nowhere"}
shaft {"boundary": [[5000,1000],[6000,1000],[6000,2000],[5000,2000]], "base_offset": -500, "height": 4000}
modify {"id": 100013, "colour": [214, 229, 210]}
floor {"boundary": [[16000,0],[20000,0],[20000,4000],[16000,4000]], "type": "Slab 250"}
""",
    "shaped": r"""
floor {"boundary": [[30000,0],[38000,0],[38000,6000],[30000,6000]], "openings": [[[31000,1000],[32000,1000],[32000,2000],[31000,2000]]]}
edit_shape {"id": 100002, "points": [{"at": [35000,3000], "z": -30}], "lines": [{"a": [35000,3000], "b": [38000,6000]}]}
type {"category": "floor", "name": "Terrace", "layers": [{"function": "finish", "thickness": 10}, {"function": "substrate", "thickness": 60, "variable": true}, {"function": "structure", "thickness": 200}]}
floor {"boundary": [[40000,0],[48000,0],[48000,6000],[40000,6000]], "type": "Terrace"}
edit_shape {"id": 100003, "points": [{"at": [44000,3000], "z": -30}]}
roof {"level": "Level 2", "slope": 0, "boundary": [[50000,0],[58000,0],[58000,6000],[50000,6000]]}
edit_shape {"id": 100004, "points": [{"at": [52000,3000], "z": -40}, {"at": [56000,3000], "z": -40}]}
type {"category": "roof", "name": "Terrace Roof", "layers": [{"function": "finish", "thickness": 10}, {"function": "substrate", "thickness": 100, "variable": true}, {"function": "structure", "thickness": 200}]}
roof {"level": "Level 2", "slope": 0, "type": "Terrace Roof", "boundary": [[60000,0],[68000,0],[68000,6000],[60000,6000]]}
edit_shape {"id": 100005, "points": [{"at": [64000,3000], "z": -40}]}
""",
    "roofs": r"""
roof {"level": "Level 2", "boundary": [[30000, 0], [42000, 0], [42000, 6000], [36000, 6000], [36000, 12000], [30000, 12000]], "slope": 25, "gables": [1], "openings": [[[33000, 1000], [35000, 1000], [35000, 2000], [33000, 2000]]]}
roof {"level": "Level 2", "extrusion": {"line": [[50000, 0], [58000, 0]], "profile": [[0, 0], [3000, 2000], [8000, 0]], "to": 6000}}
roof {"level": "Level 2", "extrusion": {"line": [[60000, 0], [64000, 0]], "profile": [[0, 0], [4000, 1000]], "from": 500, "to": 3000}}
roof {"level": "Level 2", "boundary": [[70000, 0], [86000, 0], [86000, 16000], [70000, 16000]], "courtyards": [[[76000, 6000], [80000, 6000], [80000, 10000], [76000, 10000]]], "gables": [5]}
roof {"level": "Level 2", "boundary": [[90000, 0], [96000, 0], [96000, 4000], [90000, 4000]], "slope": 0, "offset": 200}
roof {"level": "Level 2", "boundary": [[100000, 0], [106000, 0], [106000, 4000], [100000, 4000]], "gable": true, "slope": 35}
roof {"level": "Level 2", "boundary": [[110000, 0], [116000, 0], [116000, 4000], [110000, 4000]], "slopes": [30, 0, 45, 0]}
wall {"points": [[120000, 0], [126000, 0], [126000, 4000], [120000, 4000]], "closed": true}
roof {"level": "Level 2", "type": "Generic - 300mm", "slope": 20}
roof {"level": "Level 2", "extrusion": {"line": [[130000, 0], [138000, 0]], "profile": [[0, 0], [2000, 1000], [4000, 2000], [8000, 0]], "to": 5000}}
""",
    "structure": r"""
column {"at": [0, 0]}
column {"at": [4000, 0], "type": "Round 300", "angle": 30}
structural_column {"at": [0, 4000]}
structural_column {"at": [4000, 4000], "type": "Concrete Round 400", "height": 2800}
footing {"at": [0, 8000]}
footing {"at": [4000, 8000], "thickness": 500, "offset": -200, "angle": 45}
strip_footing {"points": [[0,12000],[6000,12000]]}
beam {"points": [[0,0],[4000,0]], "offset": 3000}
beam {"points": [[0,4000],[4000,4000]], "offset": 2800, "end_offset": 3200, "justify": "centre"}
type {"category": "beam", "name": "B 150x600", "width": 150, "depth": 600, "material": "Concrete"}
beam {"points": [[0,9000],[6000,9000]], "offset": 3000, "type": "B 150x600", "justify": "bottom"}
beam {"points": [[0,10500],[6000,10500]], "offset": 3000, "end_offset": 3500, "type": "Steel Tube 150", "justify": "centre"}
floor {"boundary": [[0,0],[6000,0],[6000,4000],[0,4000]], "structural": true, "level": "Level 2"}
rebar {"points": [[50,0,-100],[3950,0,-100]], "diameter": 12.5, "host": 100009}
rebar {"points": [[100,-70,-30],[100,70,-30],[100,70,-370],[100,-70,-370]], "closed": true, "diameter": 8, "grade": "CA-60", "host": 100009}
rebar {"points": [[0,20000,100],[3000,20000,100]], "diameter": 10}
""",
    "mep": r"""
pipe {"points": [[0,6000],[6000,6000]], "offset": 500, "end_offset": 300, "system": "Cold water"}
pipe {"points": [[1000,6500],[1000,6500]], "offset": 0, "end_offset": 3000, "type": "PVC 110", "system": "Waste"}
duct {"points": [[0,8000],[6000,8000]], "offset": 2500, "system": "Supply air"}
duct {"points": [[0,8800],[4000,8800]], "offset": 2500, "type": "Round 300"}
conduit {"points": [[0,7000],[6000,7000]], "offset": 2500, "justify": "top", "system": "Circuit 1"}
cable_tray {"points": [[0,7500],[6000,7500]], "offset": 2700, "justify": "bottom"}
wire {"points": [[0,9500],[3000,9500]], "offset": 2400, "system": "Circuit 1"}
cabling {"points": [[0,10000],[6000,10000]], "offset": 2500, "system": "Network"}
down_conductor {"points": [[0,11000],[0,11000]], "offset": 0, "end_offset": 6000}
ground_conductor {"points": [[0,12000],[8000,12000]], "offset": -500}
""",
    "devices": r"""
component {"family": "Outlet", "type": "Low 300", "at": [0, 0]}
component {"family": "Switch", "at": [1000, 0], "angle": 90}
component {"family": "Ceiling Luminaire", "at": [2000, 0], "offset": 2600}
component {"family": "Three-Phase Outlet", "type": "Unbalanced 1100", "at": [3000, 0]}
component {"family": "Distribution Board", "at": [4000, 0], "offset": 1200}
component {"family": "WC", "at": [0, 3000]}
component {"family": "Washbasin", "at": [1000, 3000], "offset": 800}
component {"family": "Floor Drain", "at": [2000, 3000]}
component {"family": "Elbow 90", "type": "50", "at": [3000, 3000], "offset": 500}
component {"family": "Gate Valve", "at": [4000, 3000], "offset": 500}
component {"family": "Air Terminal", "type": "500", "at": [0, 6000], "offset": 6000}
component {"family": "Earthing Electrode", "at": [1000, 6000], "offset": -2400}
component {"family": "Inspection Box", "at": [2000, 6000]}
component {"family": "Rack", "type": "600 x 800", "at": [3000, 6000]}
component {"family": "Patch Panel", "at": [4000, 6000], "offset": 1800}
component {"family": "Data Outlet", "at": [5000, 6000]}
component {"family": "Voice Outlet", "at": [6000, 6000]}
symbol_set {"set": "arei"}
component {"family": "Bell", "at": [7000, 6000]}
""",
    "furniture": r"""
material {"name": "Smoked glass", "color": "#405060", "transparency": 40}
family {"name": "Glass Table", "category": "furniture", "parameters": [{"name": "Width", "kind": "length", "value": 1200}, {"name": "Depth", "kind": "length", "value": 600}], "types": {"Small": {}}, "forms": [{"plane": "xy", "profile": [[0, 0], ["Width", 0], ["Width", "Depth"], [0, "Depth"]], "from": 700, "to": 720, "material": "Smoked glass"}, {"plane": "xy", "profile": [[0, 0], [50, 0], [50, 50], [0, 50]], "from": 0, "to": 700, "material": "Metal"}]}
component {"family": "Table", "type": "1600 x 900", "at": [2000, 3000], "angle": 30}
component {"family": "WC", "at": [-500, 0]}
component {"family": "WC", "at": [500, 0], "mirrored": true, "offset": 50}
component {"family": "Bed", "at": [6000, 4000], "angle": -90}
component {"family": "Glass Table", "at": [9000, 0]}
level {"elevation": 6000, "name": "Level 3"}
component {"family": "Chair", "at": [0, 8000], "level": "Level 3"}
""",
    "circulation": r"""
type {"category": "railing", "name": "Glass 1100", "height": 1100, "spacing": 0}
stair {"start": [0, 0], "end": [3000, 0], "width": 900, "height": 700}
stair {"start": [6000, 0], "angle": 90, "width": 1100, "height": 1050, "landings": [{"at": 3, "turn": 180}]}
stair {"start": [12000, 0], "angle": 0, "height": 700, "landings": [{"at": 2, "turn": 0}]}
stair {"start": [20000, 0], "angle": 0, "height": 700, "landings": [{"at": 2, "turn": 90}]}
stair {"start": [28000, 0], "angle": 0, "height": 1050, "landings": [{"at": 2, "turn": -90}, {"at": 4, "turn": -90}]}
stair {"start": [36000, 0], "angle": 0, "height": 1050, "landings": [{"at": 2, "turn": 90}, {"at": 4, "turn": -90}]}
ramp {"start": [0, -10000], "angle": 0, "height": 450, "landings": [{"at": 300, "turn": -90}]}
ramp {"start": [20000, -10000], "end": [30000, -10000], "height": 600, "slope": 6}
railing {"host": 100003, "type": "Glass 1100"}
railing {"host": 100008, "side": "left", "type": "Glass 1100"}
railing {"host": 100009, "side": "right", "type": "Glass 1100"}
railing {"path": [[0, -20000], [3000, -20000], [3000, -17000]], "base_offset": 150, "type": "Glass 1100"}
railing {"path": [[5000, -20000], [6000, -20000]]}
""",
    "phasing": r"""
wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}
door {"at": [2000, 0]}
window {"at": [8000, 3000]}
door {"at": [8000, 1500]}
room {"point": [4000, 3000]}
component {"family": "Chair", "at": [2000, 2000]}
phase {"name": "Demolition", "before": "New Construction"}
phase {"name": "Landscape"}
phase_filter {"name": "Renovation", "new": "overridden", "existing": "by-category", "demolished": "not-displayed", "temporary": "not-displayed"}
phase {"overrides": {"new": {"cut": {"color": [0, 0, 200]}}}}
option {"set": "Facade", "options": ["Brick", "Glass"], "primary": "Glass"}
option {"set": "Roof", "options": ["Hip", "Gable", "Flat"]}
modify {"id": 100003, "params": {"Phase Created": "New Construction"}}
modify {"id": 100004, "params": {"Phase Demolished": "Demolition", "Design Option": "Facade: Brick"}}
modify {"id": 100005, "params": {"Phase Created": "Demolition", "Phase Demolished": "New Construction"}}
modify {"id": 100006, "params": {"Phase Created": "Existing"}}
modify {"id": 100008, "params": {"Phase Created": "Existing"}}
modify {"id": 100009, "params": {"Design Option": "Roof: Gable"}}
modify {"id": 100010, "params": {"Phase Created": "Existing", "Design Option": "Facade: Glass"}}
parameter {"name": "Fire Rating", "categories": ["wall", "door"]}
parameter {"name": "Cost", "kind": "number", "categories": ["door", "component"]}
parameter {"name": "Finish Height", "kind": "length", "categories": ["room"]}
parameter {"name": "Accessible", "kind": "yesno", "categories": ["door", "room"]}
modify {"id": 100002, "params": {"Fire Rating": "60 min"}}
modify {"id": 100006, "params": {"Fire Rating": "30 min", "Cost": 450.5, "Accessible": true}}
modify {"id": 100009, "params": {"Finish Height": 2400, "Accessible": false}}
modify {"id": 100010, "params": {"Cost": 80}}
""",
    "phased_kinds": r"""
type {"category": "railing", "name": "Glass 1100", "height": 1100, "spacing": 0}
wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}
door {"at": [4000, 0]}
window {"at": [8000, 3000]}
room {"point": [4000, 3000]}
floor {}
ceiling {"point": [4000, 3000]}
roof {}
column {"at": [3000, 5500]}
component {"family": "Chair", "at": [2000, 2000]}
phase {"name": "Landscape"}
option {"set": "Facade", "options": ["Brick", "Glass"]}
stair {"start": [20000, 0], "angle": 90, "width": 1100, "height": 700, "landings": [{"at": 2, "turn": 180}]}
railing {"host": 100014, "type": "Glass 1100"}
ramp {"start": [30000, 0], "angle": 0, "height": 450, "landings": [{"at": 300, "turn": -90}]}
railing {"host": 100017, "side": "left", "type": "Glass 1100"}
railing {"path": [[0, -500], [3000, -500]], "type": "Glass 1100"}
structural_column {"at": [5000, 5500]}
beam {"points": [[0, 3000], [8000, 3000]], "offset": 2900}
footing {"at": [3000, 3000]}
strip_footing {"points": [[0, 0], [8000, 0]]}
mass {"boundary": [[40000, 0], [46000, 0], [46000, 5000], [40000, 5000]], "height": 6000}
pipe {"points": [[0, 1000], [8000, 1000]], "offset": 500}
modify {"id": 100002, "params": {"Phase Created": "New Construction"}}
modify {"id": 100003, "params": {"Phase Demolished": "New Construction"}}
modify {"id": 100004, "params": {"Design Option": "Facade: Glass"}}
modify {"id": 100005, "params": {"Phase Created": "Existing", "Design Option": "Facade: Brick"}}
modify {"id": 100006, "params": {"Phase Created": "New Construction", "Phase Demolished": "Landscape", "Design Option": "Facade: Glass"}}
modify {"id": 100007, "params": {"Phase Created": "New Construction"}}
modify {"id": 100008, "params": {"Phase Demolished": "New Construction"}}
modify {"id": 100009, "params": {"Design Option": "Facade: Glass"}}
modify {"id": 100010, "params": {"Phase Created": "Existing", "Design Option": "Facade: Brick"}}
modify {"id": 100011, "params": {"Phase Created": "New Construction", "Phase Demolished": "Landscape", "Design Option": "Facade: Glass"}}
modify {"id": 100012, "params": {"Phase Created": "New Construction"}}
modify {"id": 100013, "params": {"Phase Demolished": "New Construction"}}
modify {"id": 100014, "params": {"Design Option": "Facade: Glass"}}
modify {"id": 100015, "params": {"Phase Created": "Existing", "Design Option": "Facade: Brick"}}
modify {"id": 100016, "params": {"Phase Created": "New Construction", "Phase Demolished": "Landscape", "Design Option": "Facade: Glass"}}
modify {"id": 100017, "params": {"Phase Created": "New Construction"}}
modify {"id": 100018, "params": {"Phase Demolished": "New Construction"}}
modify {"id": 100019, "params": {"Design Option": "Facade: Glass"}}
modify {"id": 100020, "params": {"Phase Created": "Existing", "Design Option": "Facade: Brick"}}
modify {"id": 100021, "params": {"Phase Created": "New Construction", "Phase Demolished": "Landscape", "Design Option": "Facade: Glass"}}
modify {"id": 100022, "params": {"Phase Created": "New Construction"}}
modify {"id": 100023, "params": {"Phase Demolished": "New Construction"}}
modify {"id": 100024, "params": {"Design Option": "Facade: Glass"}}
modify {"id": 100025, "params": {"Phase Created": "Existing", "Design Option": "Facade: Brick"}}
""",
    "masses": r"""
parameter {"name": "Use", "kind": "text", "categories": ["mass"]}
mass {"boundary": [[0, 0], [10000, 0], [10000, 6000], [0, 6000]], "name": "Tower", "base_offset": 500}
modify {"id": 100002, "params": {"Use": "Housing"}}
mass {"level": "Level 2", "boundary": [[0, 10000], [6000, 10000], [6000, 14000]], "height": 4200, "name": "Wing"}
mass {"boundary": [[20000, 0], [30000, 0], [30000, 6000], [20000, 6000]], "name": "Taper", "height": 5000, "top": [[22000, 2000], [28000, 2000], [28000, 4000], [22000, 4000]]}
mass {"boundary": [[40000, 0], [44000, 0], [44000, 4000]], "name": "Lean", "height": 3500, "lean": [1500, -500]}
room_separator {"points": [[0, 20000], [5000, 20000], [5000, 25000]]}
room_separator {"points": [[10000, 20000], [14000, 20000], [14000, 24000], [10000, 24000]], "closed": true}
""",
    "names": r"""
new {"name": "Casa d'Água \"Nova\" \\ 😀"}
level {"elevation": 7000, "name": "Cobertura"}
level {"elevation": -3000, "name": "Subsolo"}
level {"elevation": 3500, "name": "Mezanino ç"}
""",
}


def _project(run, workdir, script, name="p.bimcraft"):
    (workdir / "script.txt").write_text(script, encoding="utf-8")
    return make_project(run, workdir, name, ["--script", "script.txt"])


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_export_writes_the_ifc4_file_of_the_reference(run, workdir, golden, scenario):
    """CATCHES: a rewrite whose IFC4 export of the same project differs from the reference's anywhere: the header, the
    spatial tree (project, site, building, storeys in their order), each element's class, predefined type, placement and
    body (swept profiles, closed shells of attached walls and sloped or shaped slabs, face sets of components and family
    doors and windows, swept disks of bars), openings voiding and filled, layer sets and their usages, type objects and
    their material profile sets, quantity sets, property sets (project parameters, BIMCraft's runs, masses, connectors,
    phasing, common sets with LoadBearing and Status), systems and materials with their surface styles."""
    _project(run, workdir, SCENARIOS[scenario])
    r = run(["convert", "p.bimcraft", "out.ifc"])
    golden.check_run(r, f"{scenario}_convert.txt")
    golden.check(_ifc(workdir / "out.ifc"), f"{scenario}.ifc")


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_what_the_export_writes_comes_back_in(run, workdir, golden, scenario):
    """CATCHES: a rewrite whose import of its own export doesn't give the project back: walls (layered, curved, attached),
    doors and windows with their marks and operations, floors level, sloped or shaped, ceilings, rooms with their colours,
    shafts, roofs of every kind, columns, footings, beams and the other runs in their systems with their justification,
    bars on their hosts, components of their families (mirrored too), stairs and ramps with their landings and the
    railings along them, masses (lofted too), room separation lines, project parameters, phases and design options."""
    _project(run, workdir, SCENARIOS[scenario])
    assert run(["convert", "p.bimcraft", "out.ifc"]).returncode == 0
    golden.check_run(run(["run", "out.ifc", "--cmd", "elements {}"]), f"{scenario}_back.txt")


def test_saving_as_ifc_from_run_writes_the_same_file_as_convert(run, workdir, golden):
    """CATCHES: a rewrite whose `run --save x.ifc` and `convert` export differently, or whose save reply differs; and one
    that changes the project or its file when it exports."""
    project = _project(run, workdir, SCENARIOS["walls"])
    before = project.read_text(encoding="utf-8")
    r = run(["run", "p.bimcraft", "--save", "a.ifc", "--save", "B.IFC"])
    golden.check_run(r, "save_as_ifc.txt")
    a, b = _ifc(workdir / "a.ifc"), _ifc(workdir / "B.IFC")
    assert a == b
    golden.check(a, "walls.ifc")
    assert project.read_text(encoding="utf-8") == before


def test_an_empty_project_exports_its_spatial_tree_and_nothing_else(run, workdir, golden):
    """CATCHES: a rewrite that writes elements, types, materials, property sets or phasing into the IFC of a new
    project, or leaves out its project, site, building or storeys."""
    make_project(run, workdir, "p.bimcraft", [])
    r = run(["convert", "p.bimcraft", "out.ifc"])
    golden.check_run(r, "empty_convert.txt")
    golden.check(_ifc(workdir / "out.ifc"), "empty.ifc")
