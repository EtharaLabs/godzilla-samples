"""Shape editing of floors and flat roofs: `edit_shape`, `add_point`, `add_split_line`, `reset_shape` and `falls`.

Each test drives the program through a script and compares every reply (faces, top range, points and lines with their
ids, corners) with the reference's, plus the plan SVG where the creases are drawn, and every refusal word for word."""

import json

import pytest

SLAB = 'floor {"boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}'
HOLED = ('floor {"boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], '
         '"openings": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]]}')
FLAT_ROOF = 'roof {"level": "Level 2", "slope": 0, "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}'


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


def test_a_drain_split_lines_and_points_shape_a_floor_and_reset_takes_them_off(run, workdir, golden):
    """CATCHES: a rewrite whose shaped top folds into a different number of planes, reports another top range, keeps a
    second point within a millimetre of the first instead of setting it again, measures `offset` (along the surface) or
    `absolute` (an elevation) from the wrong height, numbers the shape's parts differently, or draws other creases."""
    r = _script(workdir, run, [
        SLAB,
        'edit_shape {"id": 100002, "points": [{"at": [4000, 3000], "z": -30}]}',
        'edit_shape {"id": 100002}',
        'add_split_line {"id": 100002, "a": [4000, 3000], "b": [4000, 6000]}',
        'add_point {"id": 100002, "at": [4000.5, 3000], "z": -40}',
        'add_point {"id": 100002, "at": [2000, 1500]}',
        'add_point {"id": 100002, "at": [6000, 1500], "offset": 5}',
        'modify {"id": 100002, "offset": 100}',
        'add_point {"id": 100002, "at": [6000, 4500], "z": 90, "absolute": true}',
        'edit_shape {"id": 100002}',
        'elements {"category": "floor"}',
        'render {"view": "Level 1", "path": "shaped.svg"}',
        'reset_shape {"id": 100002}',
        'elements {"category": "floor"}',
    ])
    golden.check_run(r, "drain_points_lines_reset.txt")
    golden.check((workdir / "shaped.svg").read_text(), "drain_points_lines_reset.svg")


def test_points_and_lines_sent_back_with_their_ids_keep_them(run, workdir, golden):
    """CATCHES: a rewrite that gives a point or split line sent back with its `id` a new id, accepts the `guid` an agent
    echoes back as an error, or makes no point at a split line's loose end."""
    r = _script(workdir, run, [
        SLAB,
        'edit_shape {"id": 100002, "points": [{"at": [0, 3000], "z": -20}, {"at": [8000, 3000], "z": -20}], '
        '"lines": [{"a": [0, 3000], "b": [8000, 3000]}]}',
        'add_split_line {"id": 100002, "a": [4000, 3000], "b": [4000, 6000]}',
        'edit_shape {"id": 100002}',
    ])
    assert r.returncode == 0, r.stderr.decode()
    shape = json.loads(r.stdout.decode().splitlines()[-1])
    shape["points"][0]["z"] = -25
    lines = [
        SLAB,
        'edit_shape {"id": 100002, "points": [{"at": [0, 3000], "z": -20}, {"at": [8000, 3000], "z": -20}], '
        '"lines": [{"a": [0, 3000], "b": [8000, 3000]}]}',
        'add_split_line {"id": 100002, "a": [4000, 3000], "b": [4000, 6000]}',
        "edit_shape " + json.dumps({"id": 100002, "points": shape["points"], "lines": shape["lines"]}),
        'edit_shape {"id": 100002}',
        'elements {"category": "floor"}',
    ]
    golden.check_run(_script(workdir, run, lines), "ids_kept.txt")


def test_a_shaped_floor_moves_mirrors_and_copies_with_its_points(run, workdir, golden):
    """CATCHES: a rewrite that leaves a shape's points behind when its floor moves or is mirrored, or gives a copy the
    same part ids as the original."""
    r = _script(workdir, run, [
        SLAB,
        'edit_shape {"id": 100002, "points": [{"at": [4000, 3000], "z": -30}], "lines": [{"a": [0, 0], "b": [4000, 3000]}]}',
        'move {"ids": [100002], "by": [1000, 0]}',
        'edit_shape {"id": 100002}',
        'mirror {"ids": [100002], "axis": [[0, 0], [0, 1000]]}',
        'edit_shape {"id": 100002}',
        'copy {"ids": [100002], "by": [0, 10000]}',
        'edit_shape {"id": 100003}',
    ])
    golden.check_run(r, "move_mirror_copy.txt")


REFUSALS = [
    ("point_outside", 'add_point {"id": 100002, "at": [9000, 3000], "z": -10}'),
    ("point_in_opening", 'add_point {"id": 100002, "at": [4000, 3000], "z": -10}'),
    ("point_too_high", 'add_point {"id": 100002, "at": [1000, 1000], "z": 1e12}'),
    ("point_z_and_offset", 'add_point {"id": 100002, "at": [1000, 1000], "z": 5, "offset": 20}'),
    ("point_without_at", 'add_point {"id": 100002, "z": 5}'),
    ("split_line_across_opening", 'add_split_line {"id": 100002, "a": [0, 0], "b": [8000, 6000]}'),
    ("split_lines_crossing", 'edit_shape {"id": 100002, "lines": [{"a": [0, 0], "b": [2500, 6000]}, {"a": [0, 6000], "b": [2500, 0]}]}'),
    ("points_within_a_millimetre", 'edit_shape {"id": 100002, "points": [{"at": [1000, 1000], "z": -1}, {"at": [1000.5, 1000], "z": -2}]}'),
    ("point_without_z", 'edit_shape {"id": 100002, "points": [{"at": [1000, 1000]}]}'),
    ("point_unknown_key", 'edit_shape {"id": 100002, "points": [{"at": [1000, 1000], "z": 1, "height": 3}]}'),
    ("points_not_a_list", 'edit_shape {"id": 100002, "points": 5}'),
    ("unknown_parameter", 'edit_shape {"id": 100002, "pointz": []}'),
    ("no_id", 'reset_shape {}'),
    ("no_such_element", 'reset_shape {"id": 123456}'),
    ("a_wall_has_no_shape", 'add_point {"id": 100003, "at": [1000, 8000], "z": 0}'),
    ("edit_shape_of_a_wall", 'edit_shape {"id": 100003}'),
    ("slope_arrow_on_a_shaped_floor", 'modify {"id": 100002, "slope": 2, "arrow": [[0, 0], [8000, 0]]}'),
    ("split_line_along_the_outline", 'add_split_line {"id": 100002, "a": [0, 0], "b": [4000, 0]}\nedit_shape {"id": 100002}'),
    ("split_line_along_an_opening", 'add_split_line {"id": 100002, "a": [3000, 2000], "b": [5000, 2000]}\nedit_shape {"id": 100002}'),
    ("split_line_to_an_opening_corner", 'add_split_line {"id": 100002, "a": [1000, 1000], "b": [3000, 2000]}\nedit_shape {"id": 100002}'),
    ("split_line_into_an_opening", 'add_split_line {"id": 100002, "a": [1000, 1000], "b": [4000, 3000]}'),
    ("modify_a_loose_split_line", 'modify {"id": 100002, "shape": {"points": [], "lines": [{"a": [0, 0], "b": [1000, 500]}]}}'),
    ("modify_a_point_too_high", 'modify {"id": 100002, "shape": {"points": [{"at": [1000, 1000], "z": 2e9}]}}'),
    ("modify_a_point_outside", 'modify {"id": 100002, "shape": {"points": [{"at": [9000, 1000], "z": -5}]}}'),
]


@_cases(REFUSALS)
def test_what_a_shape_refuses_it_says(run, workdir, golden, name, line):
    """CATCHES: a rewrite that accepts a point outside the outline or in an opening, crossing split lines, two points a
    millimetre apart, a height past the model's limits, both `z` and `offset`, or a slope arrow on a shaped floor, or
    that words any of these refusals differently."""
    setup = [HOLED, 'wall {"points": [[0, 8000], [8000, 8000]]}', 'add_point {"id": 100002, "at": [1000, 1000], "z": -10}']
    golden.check_run(_script(workdir, run, [*setup, line]), f"refusal_{name}.txt")


def test_only_a_flat_roof_by_footprint_takes_a_shape(run, workdir, golden):
    """CATCHES: a rewrite that shapes a pitched or an extruded roof, keeps a pitched roof's slope on a shaped one, or
    reports a shaped flat roof's top at the wrong height (its base plus its thickness)."""
    good = _script(workdir, run, [
        FLAT_ROOF,
        'edit_shape {"id": 100002, "points": [{"at": [2000, 1500], "z": -40}, {"at": [6000, 1500], "z": -40}, '
        '{"at": [2000, 4500], "z": -40}, {"at": [6000, 4500], "z": -40}]}',
        'wall {"points": [[0, 1500], [8000, 1500]], "attach_top": 100002}',
        'elements {"category": "wall"}',
        'move {"ids": [100002], "by": [1000, 0]}',
        'edit_shape {"id": 100002}',
        'elements {"category": "roof"}',
        'render {"view": "Level 2", "path": "roof.svg"}',
    ])
    golden.check_run(good, "flat_roof_shaped.txt")
    golden.check((workdir / "roof.svg").read_text(), "flat_roof_shaped.svg")


@_cases([
    ("pitched_edit_shape", 'edit_shape {"id": 100002, "points": [{"at": [4000, 3000], "z": -40}]}'),
    ("pitched_add_point", 'add_point {"id": 100002, "at": [4000, 3000], "z": -40}'),
    ("extruded_add_point", 'add_point {"id": 100003, "at": [2000, 3000], "z": -40}'),
    ("shaped_roof_given_a_slope", 'modify {"id": 100004, "slope": 20}'),
    ("shaped_roof_reset_then_sloped", 'reset_shape {"id": 100004}\nmodify {"id": 100004, "slope": 20}\nelements {"category": "roof"}'),
])
def test_a_pitched_or_extruded_roof_takes_no_shape(run, workdir, golden, name, line):
    """CATCHES: a rewrite that gives points to a pitched or an extruded roof, or a slope to a shaped flat roof before its
    shape is reset, or words those refusals differently."""
    setup = [
        'roof {"level": "Level 2", "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}',
        'roof {"level": "Level 2", "extrusion": {"line": [[0, 0], [8000, 0]], "profile": [[0, 0], [4000, 0]], "to": 6000}}',
        FLAT_ROOF,
        'add_point {"id": 100004, "at": [4000, 3000], "z": -40}',
    ]
    golden.check_run(_script(workdir, run, [*setup, line]), f"roof_refusal_{name}.txt")


TERRACE = ('type {"category": "floor", "name": "Terrace", "layers": [{"function": "finish", "material": "Ceramic tile", '
           '"thickness": 10}, {"function": "substrate", "thickness": 60, "variable": true}, {"function": "membrane", '
           '"thickness": 5}, {"function": "structure", "material": "Concrete", "thickness": 200}]}')


VARIABLE = [
    ("volume", 'elements {"category": "floor"}'),
    ("too_deep", 'add_point {"id": 100002, "at": [2000, 3000], "z": -80}'),
    ("type_made_too_thin", 'type {"category": "floor", "name": "Terrace", "layers": [{"function": "finish", "material": '
                           '"Ceramic tile", "thickness": 10}, {"function": "substrate", "thickness": 20, "variable": true}, '
                           '{"function": "membrane", "thickness": 5}, {"function": "structure", "material": "Concrete", '
                           '"thickness": 200}]}'),
    ("two_variable_layers", 'type {"category": "floor", "name": "Two", "layers": [{"thickness": 50, "variable": true}, '
                            '{"thickness": 200, "variable": true}]}'),
    ("variable_wall_layer", 'type {"category": "wall", "name": "Odd", "layers": [{"thickness": 50, "variable": true}, '
                            '{"thickness": 200}]}'),
    ("roof_too_deep", 'type {"category": "roof", "name": "Terrace Roof", "layers": [{"function": "finish", "thickness": 10}, '
                      '{"function": "substrate", "thickness": 100, "variable": true}, {"function": "structure", '
                      '"thickness": 200}]}\n'
                      'roof {"level": "Level 2", "slope": 0, "type": "Terrace Roof", "boundary": [[0, 0], [8000, 0], '
                      '[8000, 6000], [0, 6000]]}\n'
                      'edit_shape {"id": 100003, "points": [{"at": [4000, 3000], "z": -40}]}\n'
                      'elements {"category": "roof"}\n'
                      'add_point {"id": 100003, "at": [2000, 1500], "z": -150}'),
]


@_cases(VARIABLE)
def test_a_variable_layer_takes_up_the_fall_and_refuses_to_go_below_nothing(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose volume of a shaped floor over a variable layer ignores the screed the fall takes out,
    lets a point leave the variable layer thinner than nothing, or refuses it without saying by how much to raise it."""
    setup = [
        TERRACE,
        'floor {"boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "type": "Terrace"}',
        'edit_shape {"id": 100002, "points": [{"at": [4000, 3000], "z": -30}]}',
    ]
    golden.check_run(_script(workdir, run, [*setup, line]), f"variable_layer_{name}.txt")


def test_falls_to_two_drains_and_again_to_one(run, workdir, golden):
    """CATCHES: a rewrite whose falls put the drains at another depth (as low as the fall takes the farthest corner, to
    the tenth of a millimetre down), make another number of planes, or keep the old shape when falls are given anew."""
    r = _script(workdir, run, [
        'floor {"boundary": [[0, 0], [12000, 0], [12000, 6000], [0, 6000]]}',
        'falls {"id": 100002, "drains": [[3000, 3000], [9000, 3000]], "fall": 1.5}',
        'edit_shape {"id": 100002}',
        'render {"view": "Level 1", "path": "falls.svg"}',
        'falls {"id": 100002, "drains": [[6000, 3000]], "fall": 2}',
        'edit_shape {"id": 100002}',
        FLAT_ROOF,
        'falls {"id": 100003, "drains": [[4000, 3000]], "fall": 1}',
    ])
    golden.check_run(r, "falls_two_drains.txt")
    golden.check((workdir / "falls.svg").read_text(), "falls_two_drains.svg")


def test_falls_run_round_an_opening_and_ridges_part_the_top(run, workdir, golden):
    """CATCHES: a rewrite whose valleys don't turn at an opening's corners, or that ignores the ridges drawn, so the
    shape's points, lines and drain depths differ from the reference's."""
    r = _script(workdir, run, [
        'floor {"boundary": [[0, 0], [12000, 0], [12000, 6000], [0, 6000]], '
        '"openings": [[[5500, 2500], [6500, 2500], [6500, 3500], [5500, 3500]]]}',
        'falls {"id": 100002, "drains": [[3000, 3000], [9000, 3000]], "fall": 1.5}',
        'edit_shape {"id": 100002}',
        'falls {"id": 100002, "drains": [[3000, 3000]], "fall": 1.5}',
        'edit_shape {"id": 100002}',
        'floor {"level": "Level 2", "boundary": [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]}',
        'falls {"id": 100003, "drains": [[2000, 3000], [7000, 3000]], "fall": 1.5, "ridges": [[[4000, 0], [4000, 6000]]]}',
        'edit_shape {"id": 100003}',
    ])
    golden.check_run(r, "falls_opening_ridges.txt")


FALLS_REFUSALS = [
    ("drain_outside", 'falls {"id": 100002, "drains": [[9000, 3000]], "fall": 1.5}'),
    ("no_drains", 'falls {"id": 100002, "drains": [], "fall": 1.5}'),
    ("drains_missing", 'falls {"id": 100002, "fall": 1.5}'),
    ("fall_zero", 'falls {"id": 100002, "drains": [[4000, 3000]], "fall": 0}'),
    ("fall_missing", 'falls {"id": 100002, "drains": [[4000, 3000]]}'),
    ("drains_within_a_millimetre", 'falls {"id": 100002, "drains": [[4000, 3000], [4000.5, 3000]], "fall": 1}'),
    ("l_shape_far_wing", 'falls {"id": 100003, "drains": [[5000, 1000]], "fall": 1}'),
    ("drain_in_opening", 'falls {"id": 100004, "drains": [[22500, 2500]], "fall": 1}'),
    ("part_with_no_drain", 'falls {"id": 100002, "drains": [[2000, 3000]], "fall": 1.5, "ridges": [[[4000, 0], [4000, 6000]]]}'),
    ("ridge_divides_nothing", 'falls {"id": 100002, "drains": [[2000, 3000], [7000, 3000]], "fall": 1.5, '
                              '"ridges": [[[4000, 0], [4000, 3000]]]}'),
    ("unknown_parameter", 'falls {"id": 100002, "drains": [[2000, 3000]], "fall": 1.5, "slope": 2}'),
    ("fall_past_100", 'falls {"id": 100002, "drains": [[1000, 1000]], "fall": 150}'),
    ("ridge_off_the_top", 'falls {"id": 100002, "drains": [[1000, 3000], [7000, 3000]], "fall": 1, "ridges": [[[4000, -1000], [4000, 6000]]]}'),
    ("ridge_end_too_far", 'falls {"id": 100002, "drains": [[1000, 3000], [7000, 3000]], "fall": 1, "ridges": [[[4000, -2e9], [4000, 6000]]]}'),
    ("falls_on_a_wall", 'wall {"points": [[0, 9000], [1000, 9000]]}\nfalls {"id": 100005, "drains": [[500, 9000]], "fall": 1}'),
    ("l_shape_two_drains", 'falls {"id": 100003, "drains": [[5000, 1000], [1000, 5000]], "fall": 1}'),
]


@_cases(FALLS_REFUSALS)
def test_falls_refuse_what_they_cant_drain_saying_why(run, workdir, golden, name, line):
    """CATCHES: a rewrite that drains a corner a drain can only reach over the outline, accepts a drain outside the
    floor or in an opening, a part with no drain, or no fall, or words those refusals differently."""
    setup = [
        SLAB,
        'floor {"level": "Level 2", "boundary": [[0, 0], [6000, 0], [6000, 2000], [2000, 2000], [2000, 6000], [0, 6000]]}',
        'floor {"boundary": [[20000, 0], [26000, 0], [26000, 6000], [20000, 6000]], '
        '"openings": [[[22000, 2000], [23000, 2000], [23000, 3000], [22000, 3000]]]}',
    ]
    golden.check_run(_script(workdir, run, [*setup, line]), f"falls_refusal_{name}.txt")


CREASED = [SLAB, 'edit_shape {"id": 100002, "points": [{"at": [4000, 3000], "z": -30}, {"at": [2000, 1500], "z": -10}], '
                 '"lines": [{"a": [0, 0], "b": [8000, 6000]}]}']


def _with_hole(x0, y0, x1, y1):
    return json.dumps([[[0, 0], [8000, 0]], [[8000, 0], [8000, 6000]], [[8000, 6000], [0, 6000]], [[0, 6000], [0, 0]],
                       [[x0, y0], [x1, y0]], [[x1, y0], [x1, y1]], [[x1, y1], [x0, y1]], [[x0, y1], [x0, y0]]])


@pytest.mark.parametrize("case,hole", [
    ("round_the_drain", (3500, 2500, 4500, 3500)),
    ("across_the_split_line", (5500, 3800, 6500, 4800)),
    ("clear_of_it_all", (6000, 500, 7000, 1500)),
])
def test_edit_boundary_keeps_what_stays_of_a_shape(run, workdir, golden, case, hole):
    """CATCHES: a rewrite whose new outline drops points it should keep, keeps ones inside a new hole, doesn't cut a
    split line where it enters the hole, or gives the new corners other heights than the top had there (`dropped`,
    `cut` and `added` in the reply)."""
    r = _script(workdir, run, [*CREASED, 'edit_boundary {"id": 100002, "sketch": ' + _with_hole(*hole) + "}",
                               'edit_shape {"id": 100002}'])
    golden.check_run(r, f"edit_boundary_{case}.txt")


def test_edit_boundary_of_a_shaped_flat_roof_and_a_smaller_floor(run, workdir, golden):
    """CATCHES: a rewrite whose smaller outline keeps a point now outside it, or whose roof's courtyard drawn through a
    shape doesn't cut its split line as a floor's opening does."""
    square = json.dumps([[[0, 0], [6000, 0]], [[6000, 0], [6000, 6000]], [[6000, 6000], [0, 6000]], [[0, 6000], [0, 0]]])
    r = _script(workdir, run, [
        SLAB,
        'edit_shape {"id": 100002, "points": [{"at": [3000, 3000], "z": -30}, {"at": [7000, 5000], "z": -10}], '
        '"lines": [{"a": [0, 0], "b": [3000, 3000]}, {"a": [8000, 6000], "b": [7000, 5000]}]}',
        'edit_boundary {"id": 100002, "sketch": ' + square + "}",
        'edit_shape {"id": 100002}',
        FLAT_ROOF,
        'edit_shape {"id": 100003, "points": [{"at": [4000, 3000], "z": -40}], "lines": [{"a": [0, 0], "b": [4000, 3000]}]}',
        'edit_boundary {"id": 100003, "sketch": ' + _with_hole(1500, 500, 2500, 2500) + "}",
        'edit_shape {"id": 100003}',
        'mirror {"ids": [100003], "axis": [[3000, 0], [3000, 6000]]}',
        'edit_shape {"id": 100003}',
    ])
    golden.check_run(r, "edit_boundary_square_and_roof.txt")
