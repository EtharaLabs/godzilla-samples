"""A project file is read kindly: what this version doesn't know is left out of it and named (`left_out`), whatever
element or library entry holds it; a value of the wrong kind is still an error that says what is wrong.

(The IFC area's share of reading files: `open` of a .bimcraft project, as `info`, `run` and `convert` do.)
"""

import json

import pytest
from conftest import make_project

RICH = r"""wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true}
door {"at": [2000, 0]}
window {"at": [8000, 3000]}
floor {}
room {"point": [4000, 3000]}
text {"text": "Hello", "at": [1000, 1000]}
detail_line {"points": [[0, 7000], [1000, 7000], [1000, 8000]], "arcs": [0, 90]}
detail_line {"start": [2000, 7000], "end": [3000, 7000]}
filled_region {"sketch": [[[4000,7000],[5000,7000]],[[5000,7000],[5000,8000]],[[5000,8000],[4000,8000]],[[4000,8000],[4000,7000]]]}
create_group {"ids": [100010, 100011], "name": "Note group"}
detail_group {"type": "Note group", "at": [10000, 0]}
repeating_detail {"type": "Note group", "start": [0, 12000], "end": [5000, 12000], "spacing": 2500}
spot {"at": [4000, 3000]}
schedule {"name": "Wall list", "category": "wall"}
camera {"eye": [20000, -20000, 10000], "target": [4000, 3000, 0], "name": "Corner"}
duplicate_view {"view": "Level 1", "name": "Level 1 copy"}
section {"start": [-1000, 3000], "end": [9000, 3000]}
elevation {"facing": "south"}
sheet {"name": "Plans"}
place {"sheet": "A101", "view": "Level 1"}
tag {"ids": [100006]}
dimension {"refs": [[100, 3000], [7900, 3000]], "at": [4000, 2000]}
link {"path": "other.bimcraft"}
point_cloud {"path": "scan.pts"}
import_cad {"path": "plan.dxf"}
grid {"start": [0, -3000], "end": [8000, -3000]}
text {"text": "Loose note", "at": [1000, -1000]}
column {"at": [10000, 5000]}
structural_column {"at": [12000, 5000]}
footing {"at": [14000, 5000]}
beam {"points": [[10000, 8000], [14000, 8000]], "offset": 3000}
strip_footing {"points": [[10000, 9000], [14000, 9000]]}
pipe {"points": [[10000, 10000], [14000, 10000]], "offset": 500}
rebar {"points": [[0, 20000, 100], [3000, 20000, 100]], "diameter": 10}
component {"family": "Chair", "at": [2000, 2000]}
stair {"start": [20000, 0], "end": [23000, 0], "height": 700}
ramp {"start": [20000, 5000], "angle": 0, "height": 300}
railing {"path": [[20000, 10000], [23000, 10000]]}
roof {"level": "Level 2", "boundary": [[0,0],[8000,0],[8000,6000],[0,6000]], "slope": 30}
ceiling {"point": [4000, 3000]}
shaft {"boundary": [[5000,1000],[6000,1000],[6000,2000],[5000,2000]]}
mass {"boundary": [[30000, 0], [36000, 0], [36000, 5000], [30000, 5000]], "height": 6000}
room_separator {"points": [[0,3000],[4000,3000]]}
dimension_3d {"refs": [{"at": [0, -100, 0]}, {"at": [8000, -100, 0]}], "at": [4000, -2000, 0]}
standard {"set": "nbr", "adapt_all": true}
object_styles {"categories": {"wall": {"cut": 5}}}
filter {"name": "Tall walls", "categories": ["wall"], "rules": [{"field": "Height", "op": "greater", "value": 2000}]}
template {"name": "My plan", "from": "Level 1"}
graphics {"hide": ["door"]}
detail_line {"centre": [20000, 20000], "radius": 500}
room_area {"at": "finish"}
units {"length": "ft-in"}
text_type {"name": "Big", "size": 5}
line_pattern {"name": "Dots", "segments": ["dot", {"space": 2}]}
line_pattern {"name": "Fancy", "segments": [{"dash": 2}, {"offset": {"length": 4, "count": 3, "distance": 0.5}}, {"wave": {"length": 6, "frequency": 2, "amplitude": 1}}, {"zigzag": {"length": 6, "frequency": 3, "amplitude": 1}}, {"text": {"length": 12, "size": 2, "text": "Gas"}}, {"dot_length": 1}]}
line_style {"name": "Red", "pen": 3, "color": "#ff0000", "pattern": "Dots"}
fill_pattern {"name": "Hatch", "lines": [{"angle": 45, "spacing": 3}]}
filled_region_type {"name": "Hatched", "foreground": "Hatch"}
phase {"overrides": {"new": {"cut": {"color": [0, 0, 200]}}}}
option {"set": "Facade", "options": ["Brick", "Glass"]}
reinforcement_preset {"name": "B1", "kind": "beam", "params": {"cover": 30}}
text {"text": "Runs", "at": [0, -5000], "runs": [{"from": 0, "to": 2, "bold": true}]}
"""


def _rich(run, workdir):
    """A project holding an element of nearly every category (a link, a point cloud and a CAD drawing among them, and a
    detail group's members), saved with fixed GUIDs, and its JSON."""
    (workdir / "scan.pts").write_text("3\n0 0 0\n1000 0 0\n0 1000 500\n")
    (workdir / "plan.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n0\n10\n0\n20\n0\n11\n1000\n21\n1000\n0\nENDSEC\n0\nEOF\n")
    assert run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--save", "other.bimcraft"]).returncode == 0
    (workdir / "rich.txt").write_text(RICH)
    path = make_project(run, workdir, "rich.bimcraft", ["--script", "rich.txt"])
    return path, json.loads(path.read_text(encoding="utf-8"))


def _later(obj, value=1):
    """`obj` holding a key a newer BIMCraft might have added."""
    obj["made_later"] = value
    return obj


def test_unknown_keys_anywhere_in_a_project_are_left_out_and_named(run, workdir, golden):
    """CATCHES: a rewrite that refuses a project holding keys a newer version added (in any element of any category, a
    detail group's members, a type and its layers, a material, a family and its forms, a view template, a line or text
    or dimension type, the project itself), or opens it without saying which, as JSON pointers with `/` and `~`
    escaped, how many in all, and the elements as they were."""
    path, data = _rich(run, workdir)
    for e in data["elements"].values():
        _later(e, {"nested": [1, 2]})
    for group in data["detail_groups"].values():
        for member in group["members"]:
            _later(member["element"])
            _later(member)
    _later(data)
    _later(data["types"])
    for name, kind in data["types"]["wall"].items():
        _later(kind)
        for layer in kind.get("layers", []):
            _later(layer)
    for kind in data["types"]["runs"]["beam"].values():
        _later(kind)
    _later(data["materials"]["Brick"])
    _later(data["materials"]["Brick"]["texture"])
    chair = data["families"]["Chair"]
    _later(chair)
    _later(chair["forms"][0])
    _later(chair["parameters"][0])
    for section in ("view_templates", "line_styles", "text_types", "dimension_types", "fill_patterns", "region_types"):
        _later(next(iter(data[section].values())))
    data["materials"]["Odd/name~1"] = dict(data["materials"]["Brick"])
    # A segment that is a word ("dot"), written as an object of it, as serde reads one too.
    data["line_patterns"]["Dots"][0] = {"dot": None}
    _later(data["line_patterns"]["Fancy"][1]["offset"])
    path.write_text(json.dumps(data), encoding="utf-8")
    r = run(["run", "rich.bimcraft", "--cmd", 'elements {"category": "wall"}'])
    golden.check_run(r, "unknown_keys.txt")


BAD = {
    "units_a_list": ("/units", [1]),
    "types_a_list": ("/types", []),
    "materials_a_list": ("/materials", [1]),
    "wall_start_an_object": ("/elements/100002/start", {"x": 1}),
    "wall_level_a_number": ("/elements/100002/level", 5),
    "element_of_no_category": ("/elements/100002/category", "hologram"),
    "layer_function_of_no_kind": ("/types/wall/Exterior - 300mm/layers/0/function", "decoration"),
    "family_form_material_a_list": ("/families/Chair/forms/0/material", ["x"]),
    "phases_a_string": ("/phases", "Existing"),
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_a_value_of_the_wrong_kind_is_an_error_that_says_what_is_wrong(run, workdir, golden, case):
    """CATCHES: a rewrite whose kind reading also forgives a value of the wrong kind (a list where an object belongs, an
    object where a point does, a number for a reference, a category or a layer function of no known kind) instead of
    refusing the file with the reader's own message, or that leaves out the key instead."""
    make_project(run, workdir, "p.bimcraft", ["--cmd", 'wall {"points": [[0,0],[8000,0]]}'])
    data = json.loads((workdir / "p.bimcraft").read_text(encoding="utf-8"))
    pointer, value = BAD[case]
    *parents, key = pointer.strip("/").split("/")
    at = data
    for p in parents:
        at = at[int(p)] if isinstance(at, list) else at[p]
    at[int(key) if isinstance(at, list) else key] = value
    (workdir / "p.bimcraft").write_text(json.dumps(data), encoding="utf-8")
    golden.check_run(run(["info", "p.bimcraft"]), f"bad_{case}.txt")


def test_past_a_hundred_keys_left_out_the_reply_names_the_first_hundred_and_counts_them_all(run, workdir, golden):
    """CATCHES: a rewrite whose reply lists every key it left out, however many, or stops counting at the hundred it
    names."""
    make_project(run, workdir, "p.bimcraft", [])
    data = json.loads((workdir / "p.bimcraft").read_text(encoding="utf-8"))
    for family in data["families"].values():
        for form in family["forms"]:
            _later(form)
    (workdir / "p.bimcraft").write_text(json.dumps(data), encoding="utf-8")
    r = run(["run", "p.bimcraft", "--cmd", 'elements {"category": "level"}'])
    golden.check_run(r, "past_a_hundred.txt")
