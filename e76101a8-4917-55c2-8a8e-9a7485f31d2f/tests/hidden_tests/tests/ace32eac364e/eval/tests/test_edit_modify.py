"""Modify tools on walls, doors, rooms and grids: modify, match_properties, move, copy, rotate, mirror, flip, align,
split, corner, delete, and undo/redo with counts."""

import json

import pytest
from conftest import normalize

# A closed 8 x 6 m box of walls on Level 1: walls 100002 (south), 100003 (east), 100004 (north), 100005 (west).
BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'
WALLS = 'elements {"category": "wall"}'


def session(run, workdir, setup, probes):
    """`setup` (script lines) run and saved to p.bimcraft, then each probe (a list of `--cmd` values) run on a fresh
    copy of that project in a process of its own; the whole transcript, normalised."""
    (workdir / "setup.txt").write_text("\n".join(setup) + "\n")
    r = run(["run", "--script", "setup.txt", "--save", "p.bimcraft"])
    out = [_block("setup", r)]
    assert r.returncode == 0, r.stderr.decode()
    for probe in probes:
        args = ["p.bimcraft"]
        for cmd in probe:
            args += ["--cmd", cmd]
        out.append(_block(" | ".join(probe), run(["run", *args])))
    return "".join(out)


def _block(label, r):
    return (f"=== {label}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode('utf-8', 'replace'))}"
            f"--- stderr\n{normalize(r.stderr.decode('utf-8', 'replace'))}")


CASES = {
    # modify: one element (its JSON back), several (one step), names for levels, merging into an object field.
    "modify": (
        [BOX, 'door {"at": [2000, 0]}', 'room {"point": [4000, 3000], "name": "Hall"}'],
        [
            ['modify {"id": 100002, "type": "Exterior - 300mm"}', WALLS],
            ['modify {"ids": [100002, 100004], "type": "Exterior - 300mm"}', WALLS, 'undo', WALLS],
            ['modify {"id": 100002, "top_level": null, "height": 2500, "level": "Level 1"}'],
            ['modify {"id": 100003, "location": "exterior-finish"}', WALLS],
            ['modify {"id": 100006, "mark": "D-1", "flip_hand": true}', 'elements {"category": "door"}'],
            ['modify {"id": 100007, "name": "Living", "number": "7"}', 'elements {"category": "room"}'],
            ['modify {"id": 100000, "view_range": {"cut": 1500}}', 'elements {"category": "level"}'],
            ['modify {"id": 100000, "elevation": -500, "name": "Ground"}', 'elements {"category": "level"}'],
            ['modify {"id": 100002, "hieght": 2000}'],
            ['modify {"id": 100002, "category": "floor"}'],
            ['modify {"id": 100002, "category": "wall", "height": 2000}'],
            ['modify {"id": 100002, "type": "Nope"}'],
            ['modify {"id": 100002, "level": "Level 9"}'],
            ['modify {"id": 999999, "height": 1}'],
            ['modify {"height": 1}'],
            ['modify {"ids": "x", "height": 1}'],
            ['modify {"id": 100002, "height": "tall"}'],
            ['modify {"id": 100002, "start": [8000, 0]}'],
        ],
    ),
    # match_properties: the type of `from` to elements of its category; the rest skipped.
    "match_properties": (
        [BOX, 'door {"at": [2000, 30]}', 'modify {"id": 100002, "type": "Exterior - 300mm"}',
         'family {"name": "Box", "category": "furniture", "types": {"A": {}, "B": {}}, "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500}]}',
         'component {"family": "Box", "at": [1000, 1000]}', 'component {"family": "Table", "at": [3000, 3000]}'],
        [
            ['MA {"from": 100002, "ids": [100003, 100004, 100006, 100002]}', WALLS, 'undo'],
            ['match_properties {"from": 100007, "ids": [100008]}', 'elements {"category": "component"}'],
            ['match_properties {"ids": [100003]}'],
            ['match_properties {"from": 9999999, "ids": [100003]}'],
            ['match_properties {"from": 100002}'],
            ['match_properties {"from": 100002, "ids": []}'],
            ['match_properties {"from": 100002, "ids": [100006]}'],
            ['match_properties {"from": 100000, "ids": [100001]}'],
        ],
    ),
    # move: joined walls stretch, doors stay or slide, one end; and its refusals.
    "move": (
        [BOX, 'wall {"points": [[0, 3000], [8000, 3000]], "type": "Interior - 100mm"}', 'room {"point": [4000, 1500]}',
         'door {"at": [2000, 0]}', 'window {"at": [8000, 1500]}'],
        [
            ['MV {"ids": [100003], "by": [1000, 0]}', WALLS, 'elements {"category": "room"}',
             'elements {"category": "door"}', 'elements {"category": "window"}'],
            ['move {"ids": [100002], "by": [-1000, 0], "end": "start"}', WALLS, 'elements {"category": "door"}'],
            ['move {"ids": [100008], "by": [1500, 700]}', 'elements {"category": "door"}'],
            ['move {"ids": [100000], "by": [10, 0]}'],
            ['move {"ids": [100002], "by": [1e300, 0]}'],
            ['move {"ids": [100002]}'],
            ['move {"ids": [100002, 100003], "by": [10, 0], "end": "end"}'],
            ['move {"ids": [100002], "by": [10, 0], "end": "middle"}'],
            ['move {"ids": [100008], "by": [10, 0], "end": "start"}'],
            ['move {"by": [10, 0]}'],
            ['move {"ids": [100002], "by": [10]}'],
            ['move {"ids": [100002, 100002], "by": [0, -500]}', WALLS],
        ],
    ),
    # copy: walls with their doors (a new mark), rooms with a new number; what it refuses.
    "copy": (
        [BOX, 'door {"at": [2000, 0]}', 'room {"point": [4000, 3000], "name": "Hall"}', 'grid {"start": [0, -1000], "end": [0, 7000]}'],
        [
            ['CO {"ids": [100002], "by": [0, -2000]}', WALLS, 'elements {"category": "door"}'],
            ['copy {"ids": [100007], "by": [100, 100]}', 'elements {"category": "room"}'],
            ['copy {"ids": [100008], "by": [1000, 0]}', 'elements {"category": "grid"}'],
            ['copy {"ids": [100000], "by": [10, 0]}'],
            ['copy {"ids": [100006], "by": [300, 0]}'],
            ['copy {"ids": [100002]}'],
        ],
    ),
    # rotate: about a point, joined walls staying joined, a copy, and a door that only turns with its wall.
    "rotate": (
        [BOX, 'wall {"points": [[4000, 0], [4000, 6000]], "type": "Interior - 100mm"}', 'door {"at": [6000, 0]}'],
        [
            ['RO {"ids": [100002, 100003, 100004, 100005], "about": [4000, 3000], "angle": 90}', WALLS, 'elements {"category": "door"}'],
            ['rotate {"ids": [100006], "about": [4000, 3000], "angle": 90, "copy": true}', WALLS],
            ['rotate {"ids": [100002, 100003, 100004, 100005, 100006], "about": [0, 0], "angle": 180}', WALLS],
            ['rotate {"ids": [100007], "about": [0, 0], "angle": 5}'],
            ['rotate {"ids": [100002], "about": [0, 0]}'],
            ['rotate {"ids": [100002], "angle": 5}'],
            ['rotate {"ids": [100001], "about": [0, 0], "angle": 5}'],
        ],
    ),
    # mirror: a copy whose doors swing the mirrored way, a grid mirrored itself, and a bad axis.
    "mirror": (
        [BOX, 'door {"at": [2000, 0]}', 'grid {"start": [0, -1000], "end": [0, 7000]}'],
        [
            ['MM {"ids": [100002], "axis": [[10000, -5000], [10000, 5000]], "copy": true}', WALLS, 'elements {"category": "door"}'],
            ['DM {"ids": [100007], "axis": [[4000, 0], [4000, 1000]]}', 'elements {"category": "grid"}'],
            ['mirror {"ids": [100002, 100003, 100004, 100005], "axis": [[0, 0], [8000, 0]]}', WALLS, 'elements {"category": "door"}'],
            ['mirror {"ids": [100007], "axis": [[1, 1], [1, 1]]}'],
            ['mirror {"ids": [100007], "axis": [[1, 1]]}'],
            ['mirror {"ids": [100007]}'],
            ['mirror {"ids": [100006], "axis": [[0, 0], [0, 1000]]}'],
        ],
    ),
    # flip: walls turned round about their location lines; their doors keep their place.
    "flip": (
        [BOX, 'door {"at": [2000, 0]}', 'window {"at": [8000, 2000]}', 'wall {"points": [[10000, 0], [14000, 0]], "arc": 90}',
         'grid {"start": [0, -1000], "end": [0, 7000]}'],
        [
            ['flip {"ids": [100002, 100003]}', WALLS, 'elements {"category": "door"}', 'elements {"category": "window"}', 'undo'],
            ['flip {"ids": [100008]}', WALLS],
            ['flip {"ids": [100002, 100009]}'],
            ['flip {"ids": [100006]}'],
            ['flip {}'],
        ],
    ),
    # split a wall: the part a door is in takes it; across a door, off the wall, or at an end is refused.
    "split_walls": (
        [BOX, 'room {"point": [4000, 3000]}', 'door {"at": [2000, 0]}', 'window {"at": [6000, 0]}',
         'wall {"points": [[10000, 0], [14000, 0]], "arc": 90}'],
        [
            ['SL {"id": 100002, "at": [4000, 20]}', WALLS, 'elements {"category": "door"}', 'elements {"category": "window"}',
             'elements {"category": "room"}'],
            ['split {"id": 100009, "at": [12000, -820]}', WALLS],
            ['split {"id": 100002, "at": [2000, 0]}'],
            ['split {"id": 100002, "at": [2000, 3000]}'],
            ['split {"id": 100002, "at": [0, 0]}'],
            ['split {"id": 100006, "at": [0, 0]}'],
        ],
    ),
    # corner: two walls trimmed or extended to meet, `keep` choosing the parts; parallel and curved walls refused.
    "corner_walls": (
        ['wall {"points": [[0, 0], [4000, 0]]}', 'wall {"points": [[5000, 1000], [5000, 6000]]}',
         'wall {"points": [[-2000, 3000], [3000, 3000]]}', 'wall {"points": [[1000, 1500], [1000, 5000]]}',
         'wall {"points": [[0, 8000], [4000, 8000]]}', 'wall {"points": [[10000, 0], [14000, 0]], "arc": 90}'],
        [
            ['TR {"ids": [100002, 100003]}', WALLS],
            ['corner {"ids": [100004, 100005], "keep": [[-1000, 3000], [1000, 4500]]}', WALLS],
            ['corner {"ids": [100002, 100006]}'],
            ['corner {"ids": [100002, 100007]}'],
            ['corner {"ids": [100002]}'],
            ['corner {"ids": [100002, 100000]}'],
            ['corner {"ids": [100002, 100003], "keep": [[0, 0]]}'],
        ],
    ),
    # align: a wall to a grid (parallel, so it moves only), a door sliding along its wall, the padlock.
    "align": (
        ['wall {"points": [[0, 0], [0, 4000]]}', 'wall {"points": [[500, 6000], [500, 9000]]}',
         'wall {"points": [[3000, 0], [9000, 0]]}', 'door {"wall": 100004, "offset": 2000}',
         'grid {"start": [-1000, -2000], "end": [-1000, 10000]}', 'detail_line {"centre": [20000, 0], "radius": 1000}'],
        [
            ['AL {"id": 100003, "reference": [[0, 0], [0, 4000]], "line": [[500, 6000], [500, 9000]], "lock": true}', WALLS,
             'move {"ids": [100002], "by": [300, 0]}', WALLS],
            ['align {"id": 100002, "reference": [[-1000, -2000], [-1000, 10000]], "line": [[0, 0], [0, 4000]]}', WALLS],
            ['align {"id": 100003, "reference": [[-1000, -2000], [-1000, 10000]], "line": [[500, 6000], [500, 9000]], "lock": true, "to": 100006}',
             'elements {"category": "dimension"}'],
            ['align {"id": 100005, "reference": [[1500, -1000], [1500, 1000]], "line": [[5000, -100], [5000, 100]]}',
             'elements {"category": "door"}'],
            ['align {"id": 100005, "reference": [[4500, -1000], [4500, 1000]], "line": [[5000, -100], [5000, 100]]}',
             'elements {"category": "door"}'],
            ['align {"id": 100005, "reference": [[0, 500], [6000, 500]], "line": [[4000, 0], [6000, 0]]}'],
            ['align {"id": 100002, "reference": [[0, 0], [0, 0]], "line": [[0, 0], [0, 4000]]}'],
            ['align {"id": 100002, "reference": [[0, 0], [0, 4000]], "line": [[1, 1], [1, 1]]}'],
            ['align {"id": 100002, "reference": [[0, 0]], "line": [[0, 0], [0, 4000]]}'],
            ['align {"reference": [[0, 0], [0, 4000]], "line": [[0, 0], [0, 4000]]}'],
            ['align {"id": 100007, "reference": [[0, 0], [0, 4000]], "line": [[20000, 0], [21000, 0]]}'],
            ['align {"id": 999999, "reference": [[0, 0], [0, 4000]], "line": [[0, 0], [0, 4000]]}'],
            ['align {"id": 100003, "reference": [[7000, 0], [7000, 4000]], "line": [[500, 6000], [500, 9000]], "lock": true}'],
            ['align {"id": 100003, "reference": [[0, 0], [0, 4000]], "line": [[500, 6000], [500, 9000]], "lock": true, "to": 100004}'],
        ],
    ),
    # delete: a wall takes its doors and their tags; a level in use is refused.
    "delete": (
        [BOX, 'door {"at": [2000, 0]}', 'tag {"id": 100006}', 'room {"point": [4000, 3000]}',
         'dimension {"refs": [{"id": 100002}, {"id": 100004}], "at": [1000, 3000]}'],
        [
            ['DE {"ids": [100002]}', 'elements {}'],
            ['delete {"ids": [100002, 100004]}', 'elements {"category": "dimension"}'],
            ['delete {"ids": [100000]}'],
            ['delete {"ids": [100001]}', 'elements {"category": "level"}'],
            ['delete {"ids": [999999]}'],
            ['delete {}'],
            ['delete {"id": 100008}', 'undo', 'elements {"category": "room"}'],
        ],
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_modify_tools(run, workdir, golden, case):
    """CATCHES: a rewrite whose modify tools move, stretch, copy, turn, mirror, flip, split, trim, align or delete
    walls and what they host differently (joins, door offsets and flips, marks and numbers of copies, rooms following),
    whose replies differ in shape, or that refuses different inputs, with different words, or leaves a change behind
    when it refuses."""
    setup, probes = CASES[case]
    golden.check(session(run, workdir, setup, probes), f"{case}.txt")


def test_undo_and_redo_go_back_several_steps_at_once(run, golden):
    """CATCHES: a rewrite whose undo/redo ignores `count`, names a different step in its reply, accepts a count of 0
    or more steps than there are, takes unknown parameters, keeps the redo list after a new command, or keeps an
    undo step for a command that failed or changed nothing."""
    out = []
    for args in [
        ["--cmd", BOX, "--cmd", 'level {"elevation": 6000}', "--cmd", 'door {"at": [2000, 0]}',
         "--cmd", 'undo {"count": 2}', "--cmd", 'elements {"category": "level"}', "--cmd", 'redo {"count": 2}',
         "--cmd", 'elements {"category": "door"}', "--cmd", 'undo {"count": 3}', "--cmd", "inspect"],
        ["--cmd", BOX, "--cmd", 'undo {"count": 2}'],
        ["--cmd", BOX, "--cmd", 'undo {"count": 0}'],
        ["--cmd", BOX, "--cmd", "undo", "--cmd", 'redo {"count": 2}'],
        ["--cmd", BOX, "--cmd", 'undo {"steps": 1}'],
        ["--cmd", BOX, "--cmd", 'undo {"count": -1}'],
        ["--cmd", BOX, "--cmd", 'undo {"count": 1.5}'],
        ["--cmd", BOX, "--cmd", "undo", "--cmd", 'level {"elevation": 6000}', "--cmd", "redo"],
        ["--cmd", BOX, "--cmd", 'elements {}', "--cmd", 'move {"ids": [100002], "by": [0, 0]}', "--cmd", "undo", "--cmd", "undo"],
    ]:
        r = run(["run", *args])
        out.append(f"=== {' '.join(args)}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}"
                   f"--- stderr\n{normalize(r.stderr.decode())}")
    golden.check("".join(out), "undo_redo_counts.txt")


def test_undo_keeps_the_last_two_hundred_steps(run, workdir, golden):
    """CATCHES: a rewrite that keeps more or fewer than 200 undo steps, or forgets the newest instead of the oldest."""
    (workdir / "s.txt").write_text("".join(f'grid {{"start": [{k * 100}, 0], "end": [{k * 100}, 1000]}}\n' for k in range(201)))
    r = run(["run", "--script", "s.txt", "--cmd", 'undo {"count": 201}'])
    tail = r.stdout.decode().splitlines()[-1]
    first = run(["run", "--script", "s.txt", "--cmd", 'undo {"count": 200}', "--cmd", 'elements {"category": "grid"}'])
    golden.check(f"exit: {r.returncode}\nlast: {tail}\n--- stderr\n{r.stderr.decode()}"
                 f"exit: {first.returncode}\nlast two:\n" + "\n".join(normalize(first.stdout.decode()).splitlines()[-2:]) + "\n",
                 "undo_limit.txt")


EVERYTHING = [
    BOX, 'door {"at": [2000, 0]}', 'window {"at": [8000, 2000]}', 'column {"at": [2000, 2000], "angle": 30}',
    'structural_column {"at": [3000, 2000]}', 'footing {"at": [4000, 2000]}', 'beam {"points": [[1000, 3000], [5000, 3000]]}',
    'pipe {"points": [[1000, 4000], [5000, 4000]]}', 'stair {"start": [6000, 1000], "angle": 90, "railings": true}',
    'railing {"path": [[1000, 5000], [3000, 5000]]}', 'floor {}', 'ceiling {"point": [4000, 3000]}',
    'shaft {"boundary": [[500, 500], [1000, 500], [1000, 1000], [500, 1000]]}',
    'mass {"boundary": [[10000, 0], [12000, 0], [12000, 2000], [10000, 2000]], "height": 3000}',
    'room_separator {"points": [[0, 3500], [8000, 3500]]}', 'room {"point": [4000, 1500], "name": "Front"}',
    'text {"text": "Note", "at": [1000, 1000], "leader": [2000, 2000]}', 'spot {"at": [3000, 3000]}',
    'filled_region {"sketch": [[[100, 100], [400, 100]], [[400, 100], [400, 400]], [[400, 400], [100, 400]], [[100, 400], [100, 100]]]}',
    'detail_line {"start": [0, -1000], "end": [500, -1000]}', 'create_group {"ids": [100026], "name": "Tick"}',
    'repeating_detail {"type": "Tick", "start": [0, -2000], "end": [2000, -2000], "spacing": 500}',
    'section {"start": [-1000, 3000], "end": [9000, 3000]}', 'elevation {"facing": "south"}',
    'dimension {"refs": [{"id": 100002}, {"id": 100004}], "at": [1000, 3000]}', 'tag {"ids": [100006]}',
    'camera {"eye": [-5000, -5000, 1600], "target": [4000, 3000, 1000]}', 'grid {"start": [-1000, -1000], "end": [-1000, 7000]}',
    'ramp {"start": [14000, 0], "angle": 0, "height": 500, "railings": true}',
    'roof {"boundary": [[20000, 0], [24000, 0], [24000, 4000], [20000, 4000]], "slope": 30}',
]
# Ids: walls 100002-100005, door 100006, window 100007, column 100008, structural column 100009, footing 100010, beam 100011,
# pipe 100012, stair 100013 and its railings 100014-100015, railing 100016, floor 100017, ceiling 100018, shaft 100019,
# mass 100020, room separator 100021, room 100022, note 100023, spot 100024, region 100025, detail group 100027, repeating
# detail 100028, section 100029, elevation 100030, dimension 100031, tag 100032, camera view 100033, grid 100034, ramp 100035
# and its railings 100036-100037, roof 100038.
ALL_IDS = [i for i in range(100002, 100039) if i != 100026]
NO_CAMERA = [i for i in ALL_IDS if i != 100033]


def test_every_kind_of_element_moves_turns_mirrors_and_copies(run, workdir, golden):
    """CATCHES: a rewrite whose move, rotate, mirror or copy leaves out or mishandles some kind of element (columns turn,
    runs, stairs with their railings, ramps, slabs and their outlines, masses, roofs, notes and their leaders, spot
    elevations, regions' patterns, detail groups, sections, elevations, dimensions, tags, a camera's eye and target), or
    copies a camera view under a name that clashes differently, or lets a stair's railing go without its stair."""
    ids, rest = json.dumps(ALL_IDS), json.dumps(NO_CAMERA)
    probes = [
        [f'move {{"ids": {ids}, "by": [1000, 500]}}', 'elements {}'],
        [f'rotate {{"ids": {ids}, "about": [4000, 3000], "angle": 90}}', 'elements {}'],
        [f'mirror {{"ids": {ids}, "axis": [[0, -5000], [1000, -5000]]}}', 'elements {}'],
        [f'mirror {{"ids": {rest}, "axis": [[0, -5000], [1000, -5000]], "copy": true}}', 'elements {"offset": 37}'],
        [f'copy {{"ids": {rest}, "by": [40000, 0]}}', 'elements {"offset": 37}'],
        [f'copy {{"ids": {ids}, "by": [40000, 0]}}'],
        ['rotate {"ids": [100014], "about": [0, 0], "angle": 30}'],
        ['move {"ids": [100036], "by": [10, 0]}'],
    ]
    golden.check(session(run, workdir, EVERYTHING, probes), "transform_everything.txt")


def test_what_has_no_place_in_plan_or_cannot_be_mirrored(run, workdir, golden):
    """CATCHES: a rewrite that moves a sheet, a schedule or a plan view in plan, mirrors a CAD import or a point cloud,
    or words those refusals differently; and one whose viewport doesn't move on its sheet."""
    (workdir / "a.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n0\n10\n0\n20\n0\n11\n1000\n21\n0\n0\nENDSEC\n0\nEOF\n")
    (workdir / "s.pts").write_text("3\n0 0 0\n1 0 0\n0 1 0\n")
    setup = ['import_cad {"path": "a.dxf"}', 'point_cloud {"path": "s.pts"}', 'sheet {}', 'place {"sheet": "A101", "view": "Level 1"}',
             'schedule {"name": "W", "category": "walls"}', 'duplicate_view {"view": "Level 1"}']
    probes = [
        ['mirror {"ids": [100002], "axis": [[0, 0], [1000, 0]]}'],
        ['mirror {"ids": [100003], "axis": [[0, 0], [1000, 0]], "copy": true}'],
        ['move {"ids": [100004], "by": [10, 0]}'],
        ['move {"ids": [100005], "by": [10, 0]}', 'elements {"category": "viewport"}'],
        ['move {"ids": [100006], "by": [10, 0]}'],
        ['copy {"ids": [100007], "by": [10, 0]}'],
        ['rotate {"ids": [100002, 100003], "about": [0, 0], "angle": 90}', 'elements {"category": "cadimport"}', 'elements {"category": "pointcloud"}'],
    ]
    golden.check(session(run, workdir, setup, probes), "no_place_in_plan.txt")


def test_modify_keeps_what_follows_from_a_change(run, workdir, golden):
    """CATCHES: a rewrite whose modify of a note's text drops or shifts its formatting runs, of a curved wall's location
    line doesn't rescale its doors' offsets along it, or which takes an id given as a float or a negative number
    differently."""
    setup = ['text {"text": "Hello world", "at": [0, 0], "override_format": true, "runs": [{"from": 6, "to": 11, "bold": true}]}',
             'wall {"points": [[0, 5000], [6000, 5000]], "arc": 90, "type": "Exterior - 300mm"}', 'door {"wall": 100003, "offset": 3000}']
    probes = [
        ['modify {"id": 100002, "text": "Hello, big world"}', 'elements {"category": "text"}'],
        ['modify {"id": 100002, "text": "Bye", "runs": []}', 'elements {"category": "text"}'],
        ['modify {"id": 100003, "location": "interior-finish"}', 'elements {"category": "wall"}', 'elements {"category": "door"}'],
        ['modify {"id": 100003.0, "height": 2500}'],
        ['modify {"id": -5, "height": 2500}'],
        ['modify {"id": 1.5, "height": 2500}'],
        ['modify {"id": "x", "height": 2500}'],
        ['modify {"ids": [100003, 999999], "height": 2500}'],
    ]
    golden.check(session(run, workdir, setup, probes), "modify_follows.txt")


# What the model check refuses, reached through `modify`: each probe one change the reference refuses (or takes).
REFUSALS = [
    'modify {"id": 100001, "name": "Level 1"}',
    'modify {"id": 100000, "extent": [[10, 10], [0, 0]]}',
    'modify {"id": 100000, "extent": [[0, 0], [5000, 5000]]}',
    'modify {"id": 100002, "arc": 400}',
    'modify {"id": 100002, "attach_top": 100003}',
    'modify {"id": 100002, "top_level": "Level 1", "top_offset": -100}',
    'modify {"id": 100007, "sill": 2500}',
    'modify {"id": 100008, "type": "Nope"}',
    'modify {"id": 100011, "type": "Nope"}',
    'modify {"id": 100013, "riser": 10}',
    'modify {"id": 100013, "top_level": "Level 1"}',
    'modify {"id": 100014, "host": 100002}',
    'modify {"id": 100016, "path": [[1000, 5000]]}',
    'modify {"id": 100016, "path": [[1000, 5000], [1000, 5000]]}',
    'modify {"id": 100017, "slope": 80}',
    'modify {"id": 100017, "slope": 5}',
    'modify {"id": 100018, "type": "Nope"}',
    'modify {"id": 100019, "top_level": "Level 1"}',
    'modify {"id": 100020, "top_level": "Level 1", "height": null}',
    'modify {"id": 100020, "top": [[10000, 0], [12000, 0], [12000, 2000]]}',
    'modify {"id": 100022, "limit_offset": -5000}',
    'modify {"id": 100023, "type": "Nope"}',
    'modify {"id": 100024, "host": null}',
    'modify {"id": 100025, "type": "Nope"}',
    'modify {"id": 100027, "type": "Nope"}',
    'modify {"id": 100028, "spacing": 0.5}',
    'modify {"id": 100028, "spacing": 1, "end": [9000000, -2000]}',
    'modify {"id": 100028, "type": "Nope"}',
    'modify {"id": 100029, "name": "South"}',
    'modify {"id": 100029, "name": ""}',
    'modify {"id": 100029, "depth": -5}',
    'modify {"id": 100031, "type": "Nope"}',
    'modify {"id": 100031, "kind": "angular"}',
    'modify {"id": 100031, "kind": "radial"}',
    'modify {"id": 100031, "orient": "horizontal"}',
    'modify {"id": 100033, "elevation": 95}',
    'modify {"id": 100033, "camera": {"lens": 1}}',
    'modify {"id": 100033, "name": "Section 1"}',
    'modify {"id": 100034, "name": ""}',
    'modify {"id": 100035, "slope": 80}',
    'modify {"id": 100038, "slope": 89}',
    'modify {"id": 100038, "type": "Nope"}',
    'modify {"id": 100006, "type": "Nope"}',
    'modify {"id": 100010, "top_level": "Level 1"}',
    'modify {"id": 100012, "type": "Nope"}',
]


REFUSAL_EXTRAS = [
    ['grid {"start": [-2000, -1000], "end": [-2000, 7000]}', 'modify {"id": 100039, "name": "1"}'],
    ['schedule {"name": "W", "category": "walls"}', 'schedule {"name": "V", "category": "walls"}', 'modify {"id": 100040, "name": "W"}'],
    ['component {"family": "Table", "at": [0, 0]}', 'modify {"id": 100039, "family": "Nope"}'],
    ['component {"family": "Table", "at": [0, 0]}', 'modify {"id": 100039, "family": "Single Door"}'],
]
CHECKED = [[cmd] for cmd in REFUSALS] + REFUSAL_EXTRAS


@pytest.mark.parametrize("part", range(4))
def test_modify_is_checked_whole(run, workdir, golden, part):
    """CATCHES: a rewrite whose model check after `modify` lets through what the reference refuses (names taken, levels
    and tops below bases, arcs past a whole turn, sills over the wall, types and families and detail groups that don't
    exist, stairs of too many risers, slopes out of range, dimensions of the wrong kind, views without a name...), or
    refuses it with other words, or refuses what the reference takes."""
    probes = CHECKED[part::4]
    golden.check(session(run, workdir, EVERYTHING, probes), f"modify_checked_{part}.txt")


def test_what_is_made_is_made_in_the_sessions_phase_and_option(run, golden):
    """CATCHES: a rewrite that stamps what a command makes with another phase or design option than the session's (the
    first phase leaving no value, a door taking its phase although it follows its wall), lets a copy keep its original's
    phase, or keeps the session's phase in the file."""
    r = run(["run", "--cmd", 'wall {"points": [[0, 0], [4000, 0]]}', "--cmd", 'phase {"now": "New Construction"}',
             "--cmd", 'wall {"points": [[0, 1000], [4000, 1000]]}', "--cmd", 'copy {"ids": [100002], "by": [0, 2000]}',
             "--cmd", 'option {"set": "Roof", "options": ["Flat", "Pitched"]}', "--cmd", 'option {"now": "Roof: Pitched"}',
             "--cmd", 'wall {"points": [[0, 5000], [4000, 5000]]}', "--cmd", 'door {"wall": 100002, "offset": 1000}',
             "--cmd", 'phase {"now": "Existing"}', "--cmd", 'wall {"points": [[0, 7000], [4000, 7000]]}',
             "--cmd", 'mirror {"ids": [100003], "axis": [[0, 9000], [1000, 9000]], "copy": true}',
             "--cmd", 'rotate {"ids": [100007], "about": [0, 7000], "angle": 180, "copy": true}',
             "--cmd", 'elements {"category": "wall"}', "--cmd", 'elements {"category": "door"}', "--save", "p.bimcraft"])
    out = (f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}")
    r = run(["run", "p.bimcraft", "--cmd", 'wall {"points": [[0, 9000], [4000, 9000]]}', "--cmd", 'elements {"category": "wall", "offset": 8}'])
    out += f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}"
    golden.check(out, "session_phase_option.txt")
