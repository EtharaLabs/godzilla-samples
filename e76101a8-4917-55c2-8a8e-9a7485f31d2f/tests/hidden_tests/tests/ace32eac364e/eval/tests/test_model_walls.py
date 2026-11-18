"""Levels, grids, walls (straight and curved, location lines, heights, attachment, joins), doors and windows, measure
and align: the replies, the `elements` listings with their derived values, plan SVGs, and every refusal word for word."""

import pytest

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


def test_levels_and_grids_name_themselves(run, workdir, golden):
    """CATCHES: a rewrite that names a new level other than `Level N` after the count, a grid other than the next number
    or letter after the last one, leaves out a level's extent or computation height, or lists them in another order."""
    r = _script(workdir, run, [
        'level {"elevation": 6000, "extent": [[-1000, -1000], [9000, 7000]]}',
        'LL {"elevation": -1000}',
        'level {"elevation": 9000, "name": "Roof"}',
        'level {"elevation": 12000}',
        'grid {"start": [0, -1000], "end": [0, 7000]}',
        'GR {"start": [8000, -1000], "end": [8000, 7000]}',
        'grid {"start": [-1000, 0], "end": [9000, 0], "name": "A"}',
        'grid {"start": [-1000, 6000], "end": [9000, 6000]}',
        'grid {"start": [-1000, 3000], "end": [9000, 3000], "name": "Z"}',
        'grid {"start": [-1000, 4000], "end": [9000, 4000]}',
        'grid {"start": [-1000, 5000], "end": [9000, 5000], "name": "A3"}',
        'grid {"start": [-1000, 5500], "end": [9000, 5500]}',
        'elements {"category": "levels"}',
        'elements {"category": "grid"}',
    ])
    golden.check_run(r, "levels_and_grids.txt")


LEVEL_GRID_REFUSALS = [
    ("level_without_elevation", 'level {}'),
    ("level_elevation_text", 'level {"elevation": "x"}'),
    ("level_elevation_too_far", 'level {"elevation": 1e300}'),
    ("level_extent_one_corner", 'level {"elevation": 6000, "extent": [[0, 0]]}'),
    ("level_extent_backwards", 'level {"elevation": 6000, "extent": [[5000, 5000], [0, 0]]}'),
    ("level_name_taken", 'level {"elevation": 6000, "name": "Level 1"}'),
    ("level_name_not_text", 'level {"elevation": 6000, "name": 7}'),
    ("grid_too_short", 'grid {"start": [0, 0], "end": [0, 0.5]}'),
    ("grid_without_end", 'grid {"start": [0, 0]}'),
    ("grid_bad_point", 'grid {"start": [0, 0], "end": [0, "x"]}'),
    ("grid_name_taken", 'grid {"start": [0, 0], "end": [0, 5000]}\ngrid {"start": [1000, 0], "end": [1000, 5000], "name": "1"}'),
]


@_cases(LEVEL_GRID_REFUSALS)
def test_level_and_grid_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that accepts a level without an elevation, an extent given backwards, a level or grid name
    already taken or a grid too short to draw, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [line]), f"level_grid_refusal_{name}.txt")


def test_walls_stand_as_their_parameters_say(run, workdir, golden):
    """CATCHES: a rewrite whose walls go up to another height (next level, `height` unconnected, `top_level` with a
    `top_offset`), measure an arc's length or radius differently, keep other `location`, `room_bounding` or type fields,
    or makes a closed chain into other walls than one per side."""
    r = _script(workdir, run, [
        BOX,
        'WA {"points": [[0, 10000], [6000, 10000]], "arc": 90}',
        'wall {"points": [[0, 13000], [6000, 13000]], "location": "exterior-finish", "type": "Exterior - 300mm"}',
        'wall {"points": [[0, 16000], [6000, 16000]], "location": "interior-core", "type": "Exterior - 300mm"}',
        'wall {"points": [[0, 19000], [6000, 19000]], "height": 2500, "base_offset": 200}',
        'wall {"points": [[0, 22000], [6000, 22000]], "top_level": "Level 2", "top_offset": -500, "base_offset": -300}',
        'level {"elevation": 7000}',
        'wall {"points": [[0, 25000], [6000, 25000], [6000, 28000]], "level": "Level 2", "top_level": 100011, "room_bounding": false}',
        'wall {"points": [[0, 31000], [4000, 31000]], "arc": -180, "type": "Interior - 100mm"}',
        'elements {"category": "wall"}',
    ])
    golden.check_run(r, "walls.txt")


WALL_REFUSALS = [
    ("one_point", 'wall {"points": [[0, 0]]}'),
    ("no_points", 'wall {}'),
    ("points_not_points", 'wall {"points": [[0, 0], [1000]]}'),
    ("point_too_far", 'wall {"points": [[0, 0], [2e9, 0]]}'),
    ("zero_length", 'wall {"points": [[0, 0], [0, 0]]}'),
    ("half_a_millimetre", 'wall {"points": [[0, 0], [0.5, 0]]}'),
    ("unknown_location", 'wall {"points": [[0, 0], [1000, 0]], "location": "middle"}'),
    ("arc_full_circle", 'wall {"points": [[0, 0], [1000, 0]], "arc": 360}'),
    ("arc_not_a_number", 'wall {"points": [[0, 0], [1000, 0]], "arc": "x"}'),
    ("arc_reaching_too_far", 'wall {"points": [[0, 0], [1000, 0]], "arc": 0.0000001}'),
    ("unknown_type", 'wall {"points": [[0, 0], [1000, 0]], "type": "Glass"}'),
    ("unknown_level", 'wall {"points": [[0, 0], [1000, 0]], "level": "Basement"}'),
    ("level_not_a_level", 'wall {"points": [[0, 0], [1000, 0]], "level": 100002}'),
    ("top_below_base", 'wall {"points": [[0, 0], [1000, 0]], "top_level": "Level 1", "top_offset": -200}'),
    ("height_zero", 'wall {"points": [[0, 0], [1000, 0]], "height": 0}'),
    ("height_negative", 'wall {"points": [[0, 0], [1000, 0]], "height": -10}'),
    ("base_offset_above_height", 'wall {"points": [[0, 0], [1000, 0]], "top_level": "Level 2", "base_offset": 3500}'),
    ("room_bounding_not_a_flag", 'wall {"points": [[0, 0], [1000, 0]], "room_bounding": "yes"}'),
    ("closed_not_a_flag", 'wall {"points": [[0, 0], [1000, 0]], "closed": 1}'),
    ("attach_top_to_a_wall", 'wall {"points": [[0, 3000], [1000, 3000]], "attach_top": 100002}'),
    ("attach_base_missing", 'wall {"points": [[0, 3000], [1000, 3000]], "attach_base": 999000}'),
    ("attach_top_not_an_id", 'wall {"points": [[0, 3000], [1000, 3000]], "attach_top": "roof"}'),
    ("unknown_parameter_ignored", 'wall {"points": [[0, 3000], [1000, 3000]], "thickness": 300}'),
]


@_cases(WALL_REFUSALS)
def test_wall_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that makes a wall of no length, a full-circle arc, a wall whose top is not above its base, an
    attachment to something that is no roof or floor, or of an unknown type, location or level, or that words those
    refusals differently (they name the element, what is wrong, and how to fix it)."""
    golden.check_run(_script(workdir, run, ['wall {"points": [[0, 0], [8000, 0]]}', line]), f"wall_refusal_{name}.txt")


def test_walls_attached_to_a_roof_and_floors_follow_them(run, workdir, golden):
    """CATCHES: a rewrite whose attached wall keeps its own height instead of following the roof's underside or the
    floor it stands on or stops under, that refuses a window rising into a gable once its wall is attached, or keeps an
    attachment to an element deleted since."""
    r = _script(workdir, run, [
        BOX,
        'roof {"gable": true}',
        'modify {"ids": [100002, 100003, 100004, 100005], "attach_top": 100006}',
        'window {"at": [8000, 3000], "sill": 2000}',
        'floor {"level": "Level 2", "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}',
        'wall {"points": [[4000, 0], [4000, 6000]], "base_offset": 500, "attach_top": 100008}',
        'floor {}',
        'elements {"category": "wall"}',
        'modify {"id": 100009, "attach_base": 100010}',
        'elements {"category": "wall"}',
        'delete {"ids": [100010]}',
        'elements {"category": "wall"}',
    ])
    golden.check_run(r, "attached.txt")


@_cases([
    ("window_in_the_gable_unattached", 'window {"at": [8000, 3000], "sill": 2000}'),
    ("detached_wall_loses_the_window", 'modify {"id": 100003, "attach_top": 100006}\n'
                                       'window {"at": [8000, 3000], "sill": 2000}\n'
                                       'modify {"id": 100003, "attach_top": null}'),
])
def test_a_window_in_a_gable_needs_its_wall_attached(run, workdir, golden, name, line):
    """CATCHES: a rewrite that lets a window rise above an unattached wall's top, or lets a wall come loose from the
    roof while a window stands in the gable it reaches."""
    golden.check_run(_script(workdir, run, [BOX, 'roof {"gable": true}', line]), f"attached_refusal_{name}.txt")


def test_walls_join_in_plan_with_mitred_caps_at_any_angle(run, workdir, golden):
    """CATCHES: a rewrite that draws walls meeting at L, T and X joins, at a slant, with different thicknesses, on other
    location lines or curved, with other outlines than the reference's (the plan SVG of the lowest level)."""
    r = _script(workdir, run, [
        'wall {"points": [[0, 0], [10000, 0], [10000, 8000], [0, 8000]], "closed": true, "type": "Exterior - 300mm", '
        '"location": "exterior-finish"}',
        'wall {"points": [[5000, 0], [5000, 8000]], "type": "Interior - 100mm"}',
        'wall {"points": [[0, 4000], [10000, 4000]]}',
        'wall {"points": [[10000, 8000], [14000, 11000]]}',
        'wall {"points": [[14000, 11000], [14000, 3000]], "arc": 120}',
        'wall {"points": [[2000, 8000], [2000, 6000], [3500, 5000]], "type": "Interior - 100mm"}',
        'wall {"points": [[0, -4000], [6000, -4000], [6000, -8000]], "type": "Exterior - 300mm", "location": "core-centre"}',
        'wall {"points": [[0, -6000], [3000, -6000]], "type": "Exterior - 300mm", "location": "exterior-core"}',
        'wall {"points": [[3000, -6000], [3000, -9000]], "type": "Exterior - 300mm", "location": "interior-core"}',
        'wall {"points": [[0, -9000], [3000, -9000]], "type": "Exterior - 300mm", "location": "interior-finish"}',
    ], "--save", "plan.svg")
    golden.check_run(r, "joins.txt")
    golden.check((workdir / "plan.svg").read_text(), "joins.svg")


def test_doors_and_windows_find_their_wall_and_number_themselves(run, workdir, golden):
    """CATCHES: a rewrite that hosts a door in another wall than the one under the point, centres one `offset` from the
    wrong end, numbers marks in another series, gives a window another default sill, or lists a family door's values,
    operation or place differently."""
    r = _script(workdir, run, [
        BOX,
        'door {"at": [2000, 30]}',
        'DR {"wall": 100003, "offset": 1500, "type": "Single 800 x 2100", "flip_hand": true}',
        'WN {"at": [8000, 4500]}',
        'window {"at": [5000, 6000], "sill": 1200, "type": "Fixed 600 x 900", "mark": "W-01"}',
        'window {"at": [3000, 6000], "flip_facing": true}',
        'door {"at": [5000, 0], "mark": "D7"}',
        'door {"at": [0, 3000], "family": "Single Door"}',
        'window {"at": [0, 5000], "family": "Casement Window", "type": "600 x 900"}',
        'door {"at": [6500, 0], "family": "Sliding Door", "type": "1500 x 2100"}',
        'elements {"category": "doors"}',
        'elements {"category": "window"}',
    ], "--save", "plan.svg")
    golden.check_run(r, "doors_windows.txt")
    golden.check((workdir / "plan.svg").read_text(), "doors_windows.svg")


OPENING_REFUSALS = [
    ("no_wall_there", 'door {"at": [4000, 3000]}'),
    ("neither_at_nor_wall", 'door {}'),
    ("wall_not_a_wall", 'door {"wall": 100000}'),
    ("does_not_fit_its_length", 'door {"wall": 100002, "offset": 100}'),
    ("too_tall_for_the_wall", 'window {"at": [8000, 3000], "sill": 2000}'),
    ("overlapping", 'door {"at": [2000, 0]}\ndoor {"at": [2300, 0]}'),
    ("unknown_family", 'door {"at": [2000, 0], "family": "Nope"}'),
    ("window_family_for_a_door", 'door {"at": [2000, 0], "family": "Casement Window"}'),
    ("unknown_family_type", 'door {"at": [2000, 0], "family": "Single Door", "type": "2 x 2"}'),
    ("unknown_type", 'window {"at": [2000, 0], "type": "Nope"}'),
    ("level_does_not_cut_it", 'door {"at": [2000, 0], "level": "Level 2"}'),
    ("flag_not_a_flag", 'door {"at": [2000, 0], "flip_facing": 1}'),
    ("negative_sill", 'window {"at": [2000, 0], "sill": -100}'),
    ("mark_not_text", 'door {"at": [2000, 0], "mark": 5}'),
]


@_cases(OPENING_REFUSALS)
def test_door_and_window_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that places a door where no wall is, in a wall it doesn't fit, over another opening, or of an
    unknown family or type, or a window past its wall's top, or that words the refusals differently (the level that
    doesn't cut a wall standing there is named with its cut height)."""
    golden.check_run(_script(workdir, run, [BOX, line]), f"opening_refusal_{name}.txt")


def test_measure_reads_length_parts_and_angle_and_changes_nothing(run, workdir, golden):
    """CATCHES: a rewrite whose ruler rounds differently, measures the angle clockwise or from another axis, makes an
    undo step of a measure, or accepts points that aren't points."""
    r = _script(workdir, run, [
        'measure {"from": [0, 0], "to": [3000, 4000]}',
        'ME {"from": [0, 0], "to": [-1000, 0]}',
        'measure {"from": [500, 500], "to": [500, -500]}',
        'measure {"from": [7, 7], "to": [7, 7]}',
        'measure {"from": [0.001, 0], "to": [1000.006, 333.3333]}',
        'measure {"from": [0, 0], "to": [-1, -1]}',
    ], "--cmd", "undo")
    golden.check_run(r, "measure.txt")


@_cases([
    ("no_to", 'measure {"from": [0, 0]}'),
    ("no_from", 'measure {"to": [0, 0]}'),
    ("too_far", 'measure {"from": [1e300, 0], "to": [0, 0]}'),
    ("not_a_point", 'measure {"from": "x", "to": [0, 0]}'),
])
def test_measure_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose ruler reads a point that is missing, not a pair of numbers, or past the model's limits,
    or words those refusals differently."""
    golden.check_run(_script(workdir, run, [line]), f"measure_refusal_{name}.txt")


ALIGN_SETUP = [
    'grid {"start": [0, -2000], "end": [0, 8000]}',
    'wall {"points": [[1000, 1000], [5000, 1000]]}',
    'floor {"boundary": [[3000, 0], [6000, 0], [6000, 3000], [3000, 3000]]}',
    'door {"wall": 100003, "offset": 2000}',
]


def test_align_puts_a_picked_line_on_a_reference(run, workdir, golden):
    """CATCHES: a rewrite whose Align turns by the other angle, moves the element by another amount, doesn't lock the
    wall to the grid so that it follows the grid's move, or keeps a pattern origin unmoved."""
    r = _script(workdir, run, [
        *ALIGN_SETUP,
        'AL {"id": 100003, "reference": [[0, -2000], [0, 8000]], "line": [[1000, 1000], [5000, 1000]], "lock": true}',
        'align {"id": 100004, "reference": [[2000, 0], [2000, 1000]], "line": [[3000, 0], [3000, 3000]]}',
        'elements {"category": "wall"}',
        'elements {"category": "floor"}',
        'move {"ids": [100002], "by": [500, 0]}',
        'elements {"category": "dimension"}',
        'elements {"category": "wall"}',
    ])
    golden.check_run(r, "align.txt")


@_cases([
    ("no_id", 'align {"reference": [[0, 0], [0, 1000]], "line": [[0, 0], [0, 1000]]}'),
    ("one_point_line", 'align {"id": 100003, "reference": [[0, 0], [0, 1000]], "line": [[0, 0]]}'),
    ("door_turned", 'align {"id": 100005, "reference": [[0, 0], [0, 1000]], "line": [[1000, 1000], [5000, 1000]]}'),
    ("level_has_no_line", 'align {"id": 100000, "reference": [[0, 0], [1000, 0]], "line": [[0, 0], [1000, 0]]}'),
    ("reference_of_no_length", 'align {"id": 100003, "reference": [[0, 0], [0, 0]], "line": [[1000, 1000], [5000, 1000]]}'),
    ("floor_has_nothing_to_lock", 'align {"id": 100004, "reference": [[9000, 0], [9000, 1000]], '
                                  '"line": [[3000, 0], [3000, 3000]], "lock": true}'),
    ("lock_to_nothing", 'align {"id": 100003, "reference": [[9000, 0], [9000, 1000]], "line": [[1000, 1000], [5000, 1000]], '
                        '"lock": true}'),
])
def test_align_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that lets a door turn out of its wall, aligns what has no straight line in plan, locks a line
    to nothing, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [*ALIGN_SETUP, line]), f"align_refusal_{name}.txt")


def test_flip_turns_walls_round_their_location_lines(run, workdir, golden):
    """CATCHES: a rewrite whose flipped wall doesn't run the other way (its exterior to the other side), whose flipped arc
    doesn't turn the other way, or whose doors and windows move, or don't swing and hinge the other way."""
    r = _script(workdir, run, [
        'wall {"points": [[0, 0], [5000, 0]], "type": "Exterior - 300mm", "location": "exterior-finish"}',
        'wall {"points": [[0, 4000], [4000, 4000]], "arc": 180}',
        'door {"wall": 100002, "offset": 1000}',
        'window {"wall": 100002, "offset": 3500}',
        'flip {"ids": [100002, 100003]}',
        'elements {"category": "wall"}',
        'elements {"category": "door"}',
        'elements {"category": "window"}',
    ], "--save", "plan.svg")
    golden.check_run(r, "flip.txt")
    golden.check((workdir / "plan.svg").read_text(), "flip.svg")


@_cases([
    ("not_a_wall", 'flip {"ids": [100000]}'),
    ("no_ids", 'flip {}'),
    ("no_such_element", 'flip {"ids": [999000]}'),
    ("view_range_upside_down", 'modify {"id": 100000, "view_range": {"cut": -100}}'),
    ("crop_backwards", 'modify {"id": 100000, "crop": [[5000, 5000], [0, 0]]}'),
    ("computation_height_unusable", 'modify {"id": 100000, "computation_height": 2e9}'),
    ("level_extent_backwards", 'modify {"id": 100001, "extent": [[5000, 5000], [0, 0]]}'),
])
def test_flip_and_level_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that flips what is no wall, or keeps a level with a view range that doesn't run top to depth,
    a crop or an extent given backwards, or an unusable computation height, or words those refusals differently."""
    golden.check_run(_script(workdir, run, ['wall {"points": [[0, 0], [5000, 0]]}', line]), f"flip_level_refusal_{name}.txt")


def test_align_locks_to_the_element_named(run, workdir, golden):
    """CATCHES: a rewrite whose Align `to` locks to another element than the one named, or refuses one that has a line
    along the reference."""
    r = _script(workdir, run, [
        'grid {"start": [0, -2000], "end": [0, 8000]}',
        'wall {"points": [[0, -2000], [0, 8000]], "type": "Interior - 100mm"}',
        'wall {"points": [[1000, 1000], [5000, 1000]]}',
        'align {"id": 100004, "reference": [[0, -2000], [0, 8000]], "line": [[1000, 1000], [5000, 1000]], "lock": true, "to": 100003}',
        'elements {"category": "dimension"}',
    ])
    golden.check_run(r, "align_to.txt")
    r = _script(workdir, run, [
        'grid {"start": [0, -2000], "end": [0, 8000]}',
        'wall {"points": [[1000, 1000], [5000, 1000]]}',
        'align {"id": 100003, "reference": [[0, -2000], [0, 8000]], "line": [[1000, 1000], [5000, 1000]], "lock": true, "to": 999000}',
    ])
    golden.check_run(r, "align_to_nothing.txt")


def test_align_moves_stairs_roofs_masses_and_the_rest_by_their_edges(run, workdir, golden):
    """CATCHES: a rewrite whose Align finds no straight edge on a stair, a ramp, a railing, a roof, a shaft, a mass, a
    ceiling, a room separator or a sketched floor, or moves one by another amount than puts that edge on the reference."""
    grid = [[-5000, 0], [-5000, 30000]]
    r = _script(workdir, run, [
        'grid {"start": [-5000, 0], "end": [-5000, 30000]}',
        'stair {"start": [1000, 1000], "end": [1000, 2000]}',
        'ramp {"start": [4000, 1000], "angle": 90, "height": 300}',
        'railing {"path": [[8000, 1000], [8000, 4000]]}',
        'roof {"boundary": [[10000, 0], [14000, 0], [14000, 3000], [10000, 3000]]}',
        'shaft {"boundary": [[16000, 0], [17000, 0], [17000, 1000], [16000, 1000]]}',
        'mass {"boundary": [[19000, 0], [22000, 0], [22000, 3000], [19000, 3000]]}',
        'ceiling {"boundary": [[24000, 0], [26000, 0], [26000, 2000], [24000, 2000]]}',
        'room_separator {"points": [[28000, 0], [28000, 3000]]}',
        'floor {"sketch": [{"points": [[30000, 0], [33000, 0], [33000, 2000], [30000, 2000]], "closed": true}]}',
        'column {"at": [35000, 1000]}',
        'beam {"points": [[37000, 3000], [41000, 3000]]}',
        *['align {"id": %d, "reference": %s, "line": %s}' % (i, grid, line) for i, line in [
            (100003, [[500, 1000], [500, 5480]]), (100004, [[3400, 1000], [3400, 4600]]), (100005, [[8000, 1000], [8000, 4000]]),
            (100006, [[10000, 0], [10000, 3000]]), (100007, [[16000, 0], [16000, 1000]]), (100008, [[19000, 0], [19000, 3000]]),
            (100009, [[24000, 0], [24000, 2000]]), (100010, [[28000, 0], [28000, 3000]]), (100011, [[30000, 0], [30000, 2000]]),
            (100012, [[34800, 800], [34800, 1200]]), (100013, [[37000, 3000], [41000, 3000]])]],
        'elements {}',
    ])
    golden.check_run(r, "align_many.txt")
