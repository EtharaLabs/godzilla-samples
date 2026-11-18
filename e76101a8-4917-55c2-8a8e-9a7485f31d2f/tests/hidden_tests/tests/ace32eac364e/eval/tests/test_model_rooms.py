"""Rooms, room separation lines and how rooms are measured: bounding by walls (Room Bounding, Computation Height),
separators, curved walls, rooms sharing a space or not enclosed, heights, frozen rooms and `room_area`, with `inspect`'s
warnings and every refusal."""

import json

import pytest
from conftest import normalize

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _slim(r):
    """The outcome of a run, an `inspect` reply cut down to its counts, warnings and history (the rest is the library)."""
    lines = []
    for line in r.stdout.decode().splitlines():
        reply = json.loads(line)
        if isinstance(reply, dict) and "warnings" in reply and "counts" in reply:
            reply = {k: reply[k] for k in ("counts", "warnings", "history", "room_area")}
        lines.append(json.dumps(reply, sort_keys=True) + "\n")
    return (f"exit: {r.returncode}\n--- stdout\n" + normalize("".join(lines))
            + "--- stderr\n" + normalize(r.stderr.decode("utf-8", "replace")))


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


def test_rooms_follow_the_walls_round_them(run, workdir, golden):
    """CATCHES: a rewrite whose room isn't bounded by the walls round its point, doesn't follow a partition put in
    later, names or numbers rooms otherwise, measures a curved wall's room otherwise, or places one outside the walls
    without the unbounded warning (in its reply and in `inspect`)."""
    r = _script(workdir, run, [
        BOX,
        'room {"point": [9000, 1000]}',
        'RM {"point": [4000, 3000], "name": "Living"}',
        'wall {"points": [[5000, 0], [5000, 6000]], "type": "Interior - 100mm"}',
        'room {"point": [6500, 3000], "name": "Kitchen", "number": "K-01"}',
        'room {"point": [2000, 3000]}',
        'wall {"points": [[20000, 3000], [16000, 3000], [16000, 0], [20000, 0]]}',
        'wall {"points": [[20000, 0], [20000, 3000]], "arc": 180}',
        'room {"point": [20500, 1500], "name": "Apse"}',
        'elements {"category": "rooms"}',
        'inspect',
        'render {"view": "Level 1", "path": "plan.svg"}',
    ])
    golden.check(_slim(r), "rooms.txt")
    golden.check((workdir / "plan.svg").read_text(), "rooms.svg")


def test_rooms_sharing_a_space_and_room_separators(run, workdir, golden):
    """CATCHES: a rewrite that lets two rooms share one space (the first placed keeps it), doesn't part an open plan
    with a separation line, ignores a separator drawn to a wall's face when measuring at the centre lines, or lists a
    separator's length otherwise."""
    r = _script(workdir, run, [
        BOX,
        'room {"point": [1000, 1000], "name": "First"}',
        'room {"point": [7000, 5000], "name": "Second"}',
        'elements {"category": "room"}',
        'inspect',
        'room_separator {"points": [[4000, 100], [4000, 5900]]}',
        'elements {"category": "rooms"}',
        'room_separator {"points": [[5000, 2000], [7000, 2000], [7000, 4000], [5000, 4000]], "closed": true}',
        'room {"point": [6000, 3000], "name": "Island"}',
        'elements {"category": "roomseparator"}',
        'elements {"category": "room"}',
        'render {"view": "Level 1", "path": "plan.svg"}',
    ])
    golden.check(_slim(r), "shared_and_separators.txt")
    golden.check((workdir / "plan.svg").read_text(), "shared_and_separators.svg")


def test_room_bounding_and_computation_height_decide_what_bounds_a_room(run, workdir, golden):
    """CATCHES: a rewrite whose rooms are bounded by a wall with Room Bounding off, or by a low wall the level's
    Computation Height passes over, or not by a separation line whatever its height."""
    r = _script(workdir, run, [
        'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
        'wall {"points": [[3000, 0], [3000, 4000]], "room_bounding": false}',
        'room {"point": [1500, 2000]}',
        'modify {"id": 100006, "room_bounding": true}',
        'elements {"category": "room"}',
        'modify {"id": 100006, "height": 1000, "top_level": null}',
        'elements {"category": "room"}',
        'modify {"id": 100000, "computation_height": 500}',
        'elements {"category": "room"}',
        'room_separator {"points": [[0, 3000], [3000, 3000]]}',
        'elements {"category": "room"}',
        'elements {"category": "wall"}',
    ])
    golden.check(_slim(r), "bounding.txt")


def test_room_heights_are_revits_upper_limit_and_offsets(run, workdir, golden):
    """CATCHES: a rewrite whose new room doesn't reach 300 mm under the level above (or, with none above, 2500 mm,
    not bounded), takes its upper limit and offsets otherwise, or computes another unbounded height or volume."""
    r = _script(workdir, run, [
        'wall {"points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "closed": true, "height": 2800, "top_level": null}',
        'room {"point": [2000, 1500]}',
        'level {"elevation": 9000, "name": "Roof"}',
        'wall {"points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "closed": true, "level": "Roof", "height": 3000}',
        'room {"point": [2000, 1500], "level": "Roof"}',
        'room {"point": [2000, 1500], "level": "Level 2", "base_offset": 200, "limit_offset": 2700}',
        'wall {"points": [[10000, 0], [14000, 0], [14000, 3000], [10000, 3000]], "closed": true}',
        'room {"point": [12000, 1500], "top_level": "Roof", "limit_offset": -1000, "base_offset": 100}',
        'modify {"id": 100006, "top_level": null, "limit_offset": 2700}',
        'elements {"category": "room"}',
    ])
    golden.check(_slim(r), "heights.txt")


ROOM_REFUSALS = [
    ("no_point", 'room {}'),
    ("point_not_a_point", 'room {"point": [1, "x"]}'),
    ("unknown_level", 'room {"point": [2000, 1500], "level": "Attic"}'),
    ("top_below_bottom", 'room {"point": [1000, 1000], "limit_offset": 0, "top_level": "Level 1"}'),
    ("limit_offset_too_low", 'room {"point": [1000, 1000]}\nmodify {"id": 100006, "limit_offset": -3000}'),
    ("base_offset_too_high", 'room {"point": [1000, 1000]}\nmodify {"id": 100006, "base_offset": 3000}'),
    ("limit_offset_unusable", 'room {"point": [1000, 1000], "limit_offset": 1e300}'),
    ("name_not_text", 'room {"point": [1000, 1000], "name": 5}'),
    ("frozen_not_a_flag", 'room {"point": [1000, 1000], "frozen": 1}'),
    ("frozen_unbounded", 'room {"point": [9000, 1000], "frozen": true}'),
    ("inside_a_wall_at_the_faces", 'room_area {"at": "finish"}\nroom {"point": [2000, 30]}'),
    ("separator_one_point", 'room_separator {"points": [[0, 0]]}'),
    ("separator_no_points", 'room_separator {}'),
    ("separator_too_short", 'room_separator {"points": [[0, 0], [0.5, 0]]}'),
    ("separator_unknown_level", 'room_separator {"points": [[0, 0], [1000, 0]], "level": "Attic"}'),
    ("room_area_unknown", 'room_area {"at": "core"}'),
    ("room_area_number", 'room_area {"at": 5}'),
    ("room_area_list", 'room_area {"at": [0, 0]}'),
]


@_cases(ROOM_REFUSALS)
def test_room_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that accepts a room whose top is not above its bottom, a frozen room with no boundary, a room
    inside a wall's body, a separator of one point or no length, or a room area other than centre or finish, or that
    words those refusals differently (they say how to fix it)."""
    golden.check(_slim(_script(workdir, run, [BOX, line])), f"room_refusal_{name}.txt")


def test_rooms_measure_at_the_centre_lines_or_at_the_finish_faces(run, workdir, golden):
    """CATCHES: a rewrite whose `room_area` measures at another line, doesn't take an island of walls out at the faces,
    measures four rooms round a crossing otherwise, makes it no undo step, or reports another setting."""
    r = _script(workdir, run, [
        'room_area {}',
        'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true, "type": "Exterior - 300mm"}',
        'wall {"points": [[3000, 0], [3000, 4000]], "type": "Exterior - 300mm"}',
        'wall {"points": [[0, 2000], [6000, 2000]], "type": "Exterior - 300mm"}',
        'room {"point": [1500, 1000]}',
        'room {"point": [4500, 1000]}',
        'room {"point": [1500, 3000]}',
        'room {"point": [4500, 3000]}',
        'wall {"points": [[10000, 0], [16000, 0], [16000, 5000], [10000, 5000]], "closed": true, "type": "Exterior - 300mm"}',
        'wall {"points": [[12500, 2000], [13500, 2000], [13500, 3000], [12500, 3000]], "closed": true, "type": "Exterior - 300mm"}',
        'room {"point": [11000, 1000]}',
        'room {"point": [13000, 2500]}',
        'wall {"points": [[20000, 0], [26000, 0], [26000, 2000], [22000, 2000], [22000, 5000], [20000, 5000]], "closed": true, '
        '"type": "Exterior - 300mm", "location": "interior-finish"}',
        'room {"point": [21000, 1000]}',
        'elements {"category": "room"}',
        'room_area {"at": "finish"}',
        'room_area {}',
        'elements {"category": "room"}',
        'inspect',
    ], "--cmd", "undo", "--cmd", "room_area")
    golden.check(_slim(r), "room_area.txt")


TWO_ROOMS = [
    'wall {"points": [[0, 0], [6000, 0], [6000, 2000], [0, 2000]], "closed": true}',
    'wall {"points": [[3000, 0], [3000, 2000]]}',
    'room {"point": [1500, 1000], "name": "Frozen", "frozen": true}',
    'room {"point": [4500, 1000], "name": "Live"}',
]


def test_frozen_rooms_keep_their_boundary(run, workdir, golden):
    """CATCHES: a rewrite whose frozen room follows the walls when they move or go, isn't found from the walls again
    once thawed, or loses its boundary when moved or mirrored."""
    r = _script(workdir, run, [
        *TWO_ROOMS,
        'move {"ids": [100005], "by": [-1000, 0]}',
        'move {"ids": [100003], "by": [1000, 0]}',
        'elements {"category": "room"}',
        'modify {"id": 100007, "frozen": false}',
        'elements {"category": "room"}',
        'modify {"id": 100007, "frozen": true}',
        'delete {"ids": [100002, 100003, 100004, 100005, 100006]}',
        'elements {"category": "room"}',
        'inspect',
        'room_area {"at": "finish"}',
        'elements {"category": "room"}',
        'move {"ids": [100007], "by": [10000, 0]}',
        'mirror {"ids": [100007], "axis": [[0, 0], [0, 1000]], "copy": true}',
        'elements {"category": "room"}',
    ])
    golden.check(_slim(r), "frozen.txt")


@_cases([
    ("freeze_one_not_enclosed", 'delete {"ids": [100002, 100003, 100004, 100005, 100006]}\nmodify {"id": 100008, "frozen": true}'),
    ("kept_two_points", 'modify {"id": 100007, "kept": {"centre": {"outer": [[0, 0], [1, 0]], "holes": []}}}'),
    ("kept_too_far", 'modify {"id": 100007, "kept": {"centre": {"outer": [[0, 0], [2e9, 0], [0, 1]], "holes": []}}}'),
    ("kept_nothing", 'modify {"id": 100007, "kept": {"centre": null, "finish": null}}'),
])
def test_frozen_room_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that freezes a room that isn't enclosed, or takes a kept boundary of too few points, of
    unusable numbers or of nothing, or words those refusals differently."""
    golden.check(_slim(_script(workdir, run, [*TWO_ROOMS, line])), f"frozen_refusal_{name}.txt")
