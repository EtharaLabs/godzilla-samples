"""Floors, ceilings and shafts, the `sketch` solver and `edit_boundary`: outlines from walls or given, openings and
courtyards, slope arrows, sketches of lines and curves, and what each refuses (an outline that isn't simple, openings out
of place), word for word."""

import json

import pytest

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'
RECT = [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]], [[4000, 3000], [0, 3000]], [[0, 3000], [0, 0]]]
HOLE = [[[1000, 1000], [2000, 1000]], [[2000, 1000], [2000, 2000]], [[2000, 2000], [1000, 2000]], [[1000, 2000], [1000, 1000]]]


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


def _rounded(value, places):
    """VALUE with every float rounded to PLACES decimals: a curve's chords come from sines and cosines, whose last bits
    may differ between machines."""
    if isinstance(value, float):
        return round(value, places) + 0.0
    if isinstance(value, list):
        return [_rounded(v, places) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v, places) for k, v in value.items()}
    return value


def test_floors_over_the_walls_given_sketched_or_sloped(run, workdir, golden):
    """CATCHES: a rewrite whose floor without a boundary doesn't follow the walls' centre lines, leaves no courtyard
    open in a free loop of walls (and one when a room is in it), measures area, volume or the top's range of a sloped
    floor otherwise, or keeps a different sketch, openings or `structural` flag."""
    r = _script(workdir, run, [
        BOX,
        'floor {}',
        'wall {"points": [[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]], "closed": true}',
        'floor {}',
        'room {"point": [4000, 3000]}',
        'floor {"type": "Generic - 200mm", "offset": -50, "structural": true}',
        'floor {"level": "Level 2", "sketch": ' + json.dumps(RECT + HOLE) + "}",
        'floor {"level": "Level 2", "boundary": [[10000, 0], [16000, 0], [16000, 1500], [10000, 1500]], "offset": 100, '
        '"slope": 5, "arrow": [[10000, 750], [16000, 750]]}',
        'floor {"boundary": [[20000, 0], [20000, 3000], [24000, 3000], [24000, 0], [24000, 0.5]], '
        '"openings": [[[21000, 1000], [22000, 1000], [22000, 2000], [21000, 2000]]]}',
        'elements {"category": "floor"}',
    ])
    golden.check_run(r, "floors.txt")


FLOOR_REFUSALS = [
    ("no_walls_on_the_level", 'floor {"level": "Level 2"}'),
    ("two_points", 'floor {"boundary": [[0, 0], [4000, 0]]}'),
    ("points_within_a_millimetre", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 0.0001]]}'),
    ("no_area", 'floor {"boundary": [[0, 0], [4000, 0], [8000, 0]]}'),
    ("bow_tie", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [2000, 0], [0, 3000]]}'),
    ("keyhole_slit", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [2000, 3000], [2000, 1000], [2000, 3000], [0, 3000]]}'),
    ("opening_outside", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], '
                        '"openings": [[[3000, 1000], [5000, 1000], [5000, 2000], [3000, 2000]]]}'),
    ("openings_overlap", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "openings": '
                         '[[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]], [[1500, 1500], [2500, 1500], [2500, 2500], [1500, 2500]]]}'),
    ("opening_bow_tie", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], '
                        '"openings": [[[1000, 1000], [2000, 2000], [2000, 1000], [1000, 2000]]]}'),
    ("opening_too_small", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "openings": [[[1000, 1000], [2000, 1000]]]}'),
    ("slope_without_arrow", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "slope": 5}'),
    ("slope_too_steep", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "slope": 80, "arrow": [[0, 0], [4000, 0]]}'),
    ("arrow_one_point", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "slope": 5, "arrow": [[0, 0]]}'),
    ("arrow_too_short", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "slope": 5, "arrow": [[0, 0], [0, 0]]}'),
    ("sketch_and_boundary", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "sketch": [[[0, 0], [1, 1]]]}'),
    ("sketch_two_outlines", 'floor {"sketch": ' + json.dumps(RECT + [[[5000, 0], [6000, 0]], [[6000, 0], [6000, 1000]],
                                                                      [[6000, 1000], [5000, 0]]]) + "}"),
    ("sketch_open", 'floor {"sketch": [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]]]}'),
    ("unknown_type", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "type": "Timber"}'),
    ("structural_not_a_flag", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "structural": "yes"}'),
    ("offset_not_a_number", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "offset": "high"}'),
    ("walls_touching_at_a_corner", 'wall {"points": [[20000, 0], [24000, 0], [24000, 4000], [20000, 4000]], "closed": true}\n'
                                   'wall {"points": [[24000, 4000], [28000, 4000], [28000, 8000], [24000, 8000]], "closed": true}\n'
                                   'floor {"level": "Level 1"}'),
    ("modify_into_a_bow_tie", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}\n'
                              'modify {"id": 100003, "boundary": [[0, 0], [4000, 3000], [4000, 0], [0, 3000]]}'),
]


@_cases(FLOOR_REFUSALS)
def test_floor_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that makes a floor of a bow tie, a keyhole, no area or too few points, with an opening outside
    it or overlapping another, a slope without an arrow or past 75°, or that words those refusals differently (they say
    which edges and where, and what to do: give a simple boundary, or redraw it with `edit_boundary`)."""
    golden.check_run(_script(workdir, run, ['wall {"points": [[30000, 0], [31000, 0]]}', line]), f"floor_refusal_{name}.txt")


def test_ceilings_fill_rooms_out_to_the_faces_of_their_walls(run, workdir, golden):
    """CATCHES: a rewrite whose ceiling in a room doesn't stop at the walls' faces, doesn't leave holes round a free
    loop of walls inside it, takes another default height (2600 mm), or lists its grid and thickness otherwise."""
    r = _script(workdir, run, [
        BOX,
        'wall {"points": [[5000, 0], [5000, 6000]], "type": "Interior - 100mm"}',
        'ceiling {"point": [2000, 3000]}',
        'ceiling {"boundary": [[5050, 100], [7900, 100], [7900, 5900], [5050, 5900]], "offset": 2400, "type": "Tile 600 x 600"}',
        'wall {"points": [[1000, 2000], [2000, 2000], [2000, 3000], [1000, 3000]], "closed": true, "level": "Level 2"}',
        'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true, "level": "Level 2"}',
        'ceiling {"point": [4000, 4500], "level": "Level 2"}',
        'ceiling {"level": "Level 2", "sketch": ' + json.dumps(RECT + HOLE) + ', "offset": 2500}',
        'elements {"category": "ceilings"}',
        'render {"view": "Level 1", "ceiling": true, "path": "rcp.svg"}',
    ])
    golden.check_run(r, "ceilings.txt")
    golden.check((workdir / "rcp.svg").read_text(), "ceilings_rcp.svg")


@_cases([
    ("nothing_closes_round_the_point", 'ceiling {"point": [20000, 0]}'),
    ("nothing_given", 'ceiling {}'),
    ("opening_outside", 'ceiling {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], '
                        '"openings": [[[3000, 1000], [5000, 1000], [5000, 2000], [3000, 2000]]]}'),
    ("sketch_and_openings", 'ceiling {"sketch": ' + json.dumps(RECT) + ', "openings": [[[1, 1], [2, 1], [2, 2]]]}'),
    ("unknown_type", 'ceiling {"point": [4000, 3000], "type": "Plaster"}'),
])
def test_ceiling_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that makes a ceiling round a point no walls close round, with nothing to bound it, an opening
    outside it, both a sketch and openings, or an unknown type, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [BOX, line]), f"ceiling_refusal_{name}.txt")


def test_shafts_cut_the_floors_ceilings_and_roofs_they_pass_through(run, workdir, golden):
    """CATCHES: a rewrite whose shaft doesn't take its area out of the floors and ceilings it passes through (and not
    of the one under its base, nor the roof above its top until it reaches it), or reaches another height."""
    r = _script(workdir, run, [
        BOX,
        'floor {}',
        'floor {"level": "Level 2", "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}',
        'ceiling {"point": [4000, 3000]}',
        'roof {}',
        'shaft {"boundary": [[3000, 2000], [4000, 2000], [4000, 4000], [3000, 4000]]}',
        'elements {}',
        'modify {"id": 100010, "top_level": null, "height": 8000}',
        'shaft {"sketch": [[[6000, 1000], [7000, 1000]], [[7000, 1000], [7000, 2000]], [[7000, 2000], [6000, 1000]]], '
        '"base_offset": -500, "height": 1000}',
        'elements {"category": "shaft"}',
        'elements {"category": "floor"}',
        'elements {"category": "roof"}',
    ])
    golden.check_run(r, "shafts.txt")


@_cases([
    ("no_boundary", 'shaft {}'),
    ("negative_height", 'shaft {"boundary": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]], "height": -5}'),
    ("top_not_above_base", 'shaft {"boundary": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]], "top_level": "Level 1"}'),
    ("a_hole_in_it", 'shaft {"sketch": ' + json.dumps(RECT + HOLE) + "}"),
    ("bow_tie", 'shaft {"boundary": [[1000, 1000], [2000, 2000], [2000, 1000], [1000, 2000]]}'),
])
def test_shaft_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that makes a shaft with no outline, no height, its top under its base, a hole in it or a bow
    tie outline, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [BOX, line]), f"shaft_refusal_{name}.txt")


def test_sketch_solves_lines_into_outlines_and_holes(run, workdir, golden):
    """CATCHES: a rewrite whose sketch solver nests loops otherwise (an island in a hole is an outline again), turns
    outlines clockwise or holes counter-clockwise, starts a loop at another corner, or totals the area differently."""
    island = [[[1200, 1200], [1800, 1200]], [[1800, 1200], [1800, 1800]], [[1800, 1800], [1200, 1800]], [[1200, 1800], [1200, 1200]]]
    triangle = [[[5000, 0], [6000, 0]], [[6000, 0], [6000, 1000]], [[6000, 1000], [5000, 0]]]
    r = _script(workdir, run, [
        'sketch {"lines": ' + json.dumps(RECT) + "}",
        'sketch {"lines": ' + json.dumps(list(reversed([[b, a] for a, b in RECT]))) + "}",
        'sketch {"lines": ' + json.dumps(RECT + HOLE + island + triangle) + "}",
        'sketch {"lines": [{"points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "closed": true}]}',
        'sketch {"lines": [{"start": [0, 0], "end": [4000, 0]}, {"start": [4000, 0], "end": [0, 3000]}, [[0, 3000], [0, 0]]]}',
    ])
    golden.check_run(r, "sketch_lines.txt")


def test_sketch_cuts_curves_into_chords(run, workdir, golden):
    """CATCHES: a rewrite that cuts arcs, circles, ellipses and splines into another number of chords (none more than
    5° round), or that totals their areas otherwise; coordinates compared to the hundredth of a millimetre."""
    sketches = [
        [[[0, 0], [4000, 0]], [[4000, 0], [0, 0], [2000, 1500]]],
        [{"centre": [0, 0], "radius": 1000}],
        [{"points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "closed": True, "arcs": [0, 90, 0, 0]}],
        [{"start": [0, 0], "end": [4000, 0], "arc": 180}, [[4000, 0], [0, 0]]],
        [{"centre": [0, 0], "radii": [2000, 1000]}],
        [{"control": [[0, 0], [1000, 2000], [3000, 2000], [4000, 0]]}, [[4000, 0], [0, 0]]],
        [{"fit": [[0, 0], [1000, 1000], [2000, 0]]}, [[2000, 0], [0, 0]]],
        [{"start": [0, 0], "end": [2000, 0], "through": [1000, 1000]}, [[2000, 0], [0, 0]]],
    ]
    r = _script(workdir, run, ['sketch {"lines": ' + json.dumps(s) + "}" for s in sketches])
    assert r.returncode == 0, r.stderr.decode()
    out = []
    for line in r.stdout.decode().splitlines():
        reply = json.loads(line)
        for region in reply["regions"]:
            region["corners"] = len(region["outline"])
        out.append(json.dumps(_rounded(reply, 2), sort_keys=True))
    golden.check("\n".join(out) + "\n", "sketch_curves.txt")


SKETCH_REFUSALS = [
    ("no_lines", 'sketch {}'),
    ("lines_not_a_list", 'sketch {"lines": 4}'),
    ("open_loop", 'sketch {"lines": [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]], [[0, 3000], [0, 0]]]}'),
    ("crossing", 'sketch {"lines": [[[0, 0], [4000, 3000]], [[4000, 0], [0, 3000]], [[0, 0], [4000, 0]], [[0, 3000], [4000, 3000]]]}'),
    ("overlapping", 'sketch {"lines": [[[0, 0], [2000, 0]], [[1000, 0], [3000, 0]], [[3000, 0], [1500, 2000]], [[1500, 2000], [0, 0]]]}'),
    ("four_at_a_point", 'sketch {"lines": [[[0, 0], [1000, 0]], [[1000, 0], [1000, 1000]], [[1000, 1000], [0, 1000]], [[0, 1000], [0, 0]], '
                        '[[0, 0], [-1000, 0]], [[-1000, 0], [-1000, -1000]], [[-1000, -1000], [0, -1000]], [[0, -1000], [0, 0]]]}'),
    ("too_short", 'sketch {"lines": [[[0, 0], [0.5, 0]]]}'),
    ("a_line_twice", 'sketch {"lines": [[[0, 0], [1000, 0]], [[1000, 0], [1000, 1000]], [[1000, 1000], [0, 0]], [[0, 0], [1000, 1000]]]}'),
    ("ending_part_way_along", 'sketch {"lines": [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]], [[4000, 3000], [0, 3000]], '
                              '[[0, 3000], [0, 0]], [[2000, 0], [2000, 1500]]]}'),
    ("bow_tie_polyline", 'sketch {"lines": [{"points": [[0, 0], [4000, 3000], [4000, 0], [0, 3000]], "closed": true}]}'),
    ("unknown_line_id", 'sketch {"lines": [{"id": 5, "start": [0, 0], "end": [1, 1]}]}'),
    ("half_a_curve", 'sketch {"lines": [{"start": [0, 0]}]}'),
    ("point_too_far", 'sketch {"lines": [[[0, 0], [2e9, 0]]]}'),
]


@_cases(SKETCH_REFUSALS)
def test_sketch_refusals_name_every_problem_and_its_lines(run, workdir, golden, name, line):
    """CATCHES: a rewrite that stops at the first problem instead of naming every one, ranks them otherwise, names the
    lines by another number, or accepts lines that don't close, cross, overlap, meet three at a point or are too short."""
    golden.check_run(_script(workdir, run, [line]), f"sketch_refusal_{name}.txt")


def test_edit_boundary_gives_and_redraws_an_outline_keeping_line_ids(run, workdir, golden):
    """CATCHES: a rewrite whose edit_boundary without a sketch doesn't give the outline's edges as lines (the kept sketch
    once there is one, with ids), gives a line sent back with its `id` a new one, or redraws an outline with other
    openings or area."""
    r = _script(workdir, run, [
        'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}',
        'edit_boundary {"id": 100002}',
        'edit_boundary {"id": 100002, "sketch": ' + json.dumps([[[0, 0], [5000, 0]], [[5000, 0], [5000, 3000]],
                                                                 [[5000, 3000], [0, 3000]], [[0, 3000], [0, 0]]] + HOLE) + "}",
        'edit_boundary {"id": 100002}',
        'edit_boundary {"id": 100002, "sketch": [{"id": 999467, "start": [0, 0], "end": [6000, 0]}, [[6000, 0], [5000, 3000]], '
        '[[5000, 3000], [0, 3000]], [[0, 3000], [0, 0]]]}',
        'edit_boundary {"id": 100002}',
        'elements {"category": "floor"}',
        'ceiling {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "openings": [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]]}',
        'edit_boundary {"id": 100003}',
        'edit_boundary {"id": 100003, "sketch": ' + json.dumps(RECT) + "}",
        'shaft {"boundary": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]}',
        'edit_boundary {"id": 100004, "sketch": [[[1000, 1000], [3000, 1000]], [[3000, 1000], [1000, 3000]], [[1000, 3000], [1000, 1000]]]}',
        'elements {"category": "shaft"}',
    ])
    golden.check_run(r, "edit_boundary.txt")


@_cases([
    ("no_id", 'edit_boundary {}'),
    ("no_such_element", 'edit_boundary {"id": 123456}'),
    ("a_wall", 'edit_boundary {"id": 100002}'),
    ("open_sketch", 'edit_boundary {"id": 100003, "sketch": [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]]]}'),
    ("shaft_with_a_hole", 'edit_boundary {"id": 100004, "sketch": ' + json.dumps(RECT + HOLE) + "}"),
    ("extrusion_roof", 'roof {"level": "Level 2", "extrusion": {"line": [[0, 0], [8000, 0]], "profile": [[0, 0], [4000, 0]], '
                       '"to": 6000}}\nedit_boundary {"id": 100005}'),
    ("line_id_of_another_sketch", 'edit_boundary {"id": 100003, "sketch": [{"id": 5, "start": [0, 0], "end": [4000, 0]}, '
                                  '[[4000, 0], [4000, 3000]], [[4000, 3000], [0, 3000]], [[0, 3000], [0, 0]]]}'),
])
def test_edit_boundary_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose edit_boundary edits what has no outline (a wall, an extrusion roof), gives a shaft a
    hole, takes a sketch that doesn't close, or keeps a line id the sketch never had, or words those refusals
    differently."""
    setup = ['wall {"points": [[0, 0], [4000, 0]]}', 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}',
             'shaft {"boundary": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]}']
    golden.check_run(_script(workdir, run, [*setup, line]), f"edit_boundary_refusal_{name}.txt")


def test_a_file_with_a_bow_tie_floor_opens_and_works_until_its_outline_changes(run, workdir, golden):
    """CATCHES: a rewrite that refuses to open a project whose floor crosses itself, or refuses what leaves that outline
    as bad as it was (a move, a copy, a mirror, an offset), or lets a command make it worse or draw a new one like it."""
    assert run(["run", "--cmd", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}', "--save", "f.bimcraft"]).returncode == 0
    project = json.loads((workdir / "f.bimcraft").read_text())
    project["elements"]["100002"]["boundary"] = [[0, 0], [4000, 4000], [4000, 0], [0, 2000]]
    (workdir / "bad.bimcraft").write_text(json.dumps(project))
    r = run(["run", "bad.bimcraft", "--cmd", 'move {"ids": [100002], "by": [1000, 0]}', "--cmd", 'modify {"id": 100002, "offset": 50}',
             "--cmd", 'copy {"ids": [100002], "by": [0, 9000]}', "--cmd", 'mirror {"ids": [100002], "axis": [[0, 0], [0, 1000]]}',
             "--cmd", 'edit_boundary {"id": 100002}', "--cmd", 'elements {"category": "floor"}'])
    golden.check_run(r, "bow_tie_file.txt")


@_cases([
    ("reshaped_worse", 'modify {"id": 100002, "boundary": [[0, 0], [5000, 5000], [5000, 0], [0, 2000]]}'),
    ("a_new_one_like_it", 'floor {"boundary": [[0, 0], [4000, 4000], [4000, 0], [0, 2000]]}'),
    ("redrawn_simple", 'edit_boundary {"id": 100002, "sketch": ' + json.dumps(RECT) + "}"),
])
def test_a_bow_tie_floor_from_a_file_is_asked_to_be_redrawn(run, workdir, golden, name, line):
    """CATCHES: a rewrite that lets a command change a bad outline a file holds into another bad one, or draw a new
    floor like it, without saying to redraw it (or to give a simple boundary), or that refuses a simple redraw."""
    assert run(["run", "--cmd", 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}', "--save", "f.bimcraft"]).returncode == 0
    project = json.loads((workdir / "f.bimcraft").read_text())
    project["elements"]["100002"]["boundary"] = [[0, 0], [4000, 4000], [4000, 0], [0, 2000]]
    (workdir / "bad.bimcraft").write_text(json.dumps(project))
    golden.check_run(run(["run", "bad.bimcraft", "--cmd", line]), f"bow_tie_file_{name}.txt")


def test_a_boundary_given_closed_drops_its_repeated_points(run, workdir, golden):
    """CATCHES: a rewrite that keeps a closing point repeating the first, or a click twice on a corner, as corners of
    the outline, so the floor, ceiling, roof and shaft hold other boundaries."""
    ring = [[0, 0], [0, 0.4], [4000, 0], [4000, 3000], [4000, 3000], [0, 3000], [0, 0], [0.3, 0]]
    r = run(["run", "--cmd", 'floor {"boundary": ' + json.dumps(ring) + "}", "--cmd", 'ceiling {"boundary": ' + json.dumps(ring) + "}",
             "--cmd", 'roof {"boundary": ' + json.dumps(ring) + "}", "--cmd", 'shaft {"boundary": ' + json.dumps(ring) + "}",
             "--cmd", 'elements {}'])
    golden.check_run(r, "closed_boundary.txt")


def test_edit_boundary_of_a_filled_region(run, workdir, golden):
    """CATCHES: a rewrite whose edit_boundary of a filled region doesn't give its sketch back as it is, or doesn't take
    any number of loops for it, or measures the redrawn region otherwise."""
    two = RECT + [[[5000, 0], [6000, 0]], [[6000, 0], [6000, 1000]], [[6000, 1000], [5000, 0]]]
    r = run(["run", "--cmd", 'filled_region {"sketch": ' + json.dumps(RECT) + "}", "--cmd", 'edit_boundary {"id": 100002}',
             "--cmd", 'edit_boundary {"id": 100002, "sketch": ' + json.dumps(two) + "}", "--cmd", 'elements {"category": "region"}'])
    golden.check_run(r, "filled_region.txt")
    r = run(["run", "--cmd", 'filled_region {"sketch": ' + json.dumps(RECT) + "}",
             "--cmd", 'edit_boundary {"id": 100002, "sketch": [[[0, 0], [4000, 0]]]}'])
    golden.check_run(r, "filled_region_open.txt")


@_cases([
    ("empty_lines", 'sketch {"lines": []}'),
    ("two_points_together", 'sketch {"lines": [{"points": [[0, 0], [0.5, 0], [1000, 0], [1000, 1000]], "closed": true}]}'),
    ("a_point_passed_twice", 'sketch {"lines": [{"points": [[0, 0], [1000, 0], [1000, 1000], [0, 0], [-1000, 0], [-1000, -1000]], '
                             '"closed": true}]}'),
])
def test_sketch_refusals_of_lines_it_cannot_draw(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose sketch solver takes no lines, a polyline with two points closer than a millimetre, or one
    that passes a point twice, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [line]), f"sketch_refusal_{name}.txt")
