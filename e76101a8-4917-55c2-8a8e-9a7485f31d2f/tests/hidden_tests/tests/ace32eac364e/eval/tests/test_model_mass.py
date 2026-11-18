"""Masses and what is made from them: `mass` (straight, lofted to a top outline, leaning), `mass_floors`,
`wall_by_face`, `floor_by_face`, `roof_by_face`, `update_by_face` and `show_mass`, with the areas and volumes `elements`
derives, the marks the made elements hold, the plans that draw masses dashed, and every refusal."""

import json

import pytest

BLOCK = [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]
TOWER = ['level {"elevation": 6000, "name": "Level 3"}', 'level {"elevation": 9000, "name": "Level 4"}',
         'mass {"boundary": ' + json.dumps(BLOCK) + ', "top_level": 100003, "name": "Tower"}']


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


def test_a_mass_is_a_footprint_extruded_up_to_a_level_or_a_height(run, workdir, golden):
    """CATCHES: a rewrite whose mass keeps a clockwise footprint clockwise, reaches another height, names itself
    otherwise, or reports another area, volume, gross floor area or list of levels crossed, before and after it moves."""
    r = _script(workdir, run, [
        'mass {"boundary": [[0, 0], [0, 6000], [10000, 6000], [10000, 0]], "name": "Block"}',
        'MS {"boundary": ' + json.dumps(BLOCK) + ', "height": 9000, "base_offset": 500}',
        'modify {"id": 100002, "top_level": null, "height": 4500}',
        'move {"ids": [100002], "by": [1000, 500]}',
        'copy {"ids": [100002], "by": [0, 8000]}',
        'mirror {"ids": [100002], "axis": [[0, 0], [0, 1000]], "copy": true}',
        'rotate {"ids": [100002], "about": [0, 0], "angle": 90}',
        'elements {"category": "masses"}',
    ], "--save", "plan.svg")
    golden.check_run(r, "mass.txt")
    golden.check((workdir / "plan.svg").read_text(), "mass.svg")


def test_a_lofted_mass_is_measured_from_its_cross_sections(run, workdir, golden):
    """CATCHES: a rewrite whose lofted or leaning mass has another volume (exact, from the cross sections), floor
    outlines between its footprint and its top, gross floor area, or that keeps a top equal to its footprint as a loft,
    or doesn't turn a clockwise top round with its footprint."""
    r = _script(workdir, run, [
        'level {"elevation": 6000, "name": "Level 3"}',
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "top_level": 100002, "top": [[2000, 2000], [8000, 2000], [8000, 4000], '
        '[2000, 4000]], "name": "Frustum"}',
        'MF {"mass": 100003}',
        'elements {"category": "floor"}',
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "top_level": 100002, "lean": [3000, 0], "name": "Lean"}',
        'mass_floors {"mass": 100006}',
        'mass {"boundary": [[0, 0], [0, 6000], [10000, 6000], [10000, 0]], "height": 6000, '
        '"top": [[2000, 2000], [2000, 4000], [8000, 4000], [8000, 2000]]}',
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "top": ' + json.dumps(BLOCK) + "}",
        'mirror {"ids": [100003], "axis": [[-1000, 0], [-1000, 1000]]}',
        'elements {"category": "mass"}',
        'schedule {"category": "massfloors", "sort": ["Level"]}',
        'modify {"id": 100003, "top": null}',
        'elements {"category": "mass"}',
    ], "--save", "plan.svg")
    golden.check_run(r, "lofted.txt")
    golden.check((workdir / "plan.svg").read_text(), "lofted.svg")


MASS_REFUSALS = [
    ("no_boundary", 'mass {}'),
    ("boundary_two_points", 'mass {"boundary": [[0, 0], [1000, 0]]}'),
    ("top_too_few_points", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "top": [[0, 0], [1, 0], [1, 1]]}'),
    ("top_not_points", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "top": "x"}'),
    ("top_too_far", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "top": [[0, 0], [1e300, 0], [1, 1], [0, 1]]}'),
    ("top_the_other_way", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, '
                          '"top": [[0, 6000], [10000, 6000], [10000, 0], [0, 0]]}'),
    ("top_collapses", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, '
                      '"top": [[10000, 6000], [0, 6000], [0, 0], [10000, 0]]}'),
    ("top_and_lean", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "top": ' + json.dumps(BLOCK) + ', "lean": [1, 1]}'),
    ("lean_not_a_point", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "lean": 5}'),
    ("lean_too_far", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "lean": [1e300, 0]}'),
    ("height_negative", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": -5}'),
    ("top_not_above_base", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "top_level": "Level 1"}'),
    ("unknown_level", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "level": "Basement"}'),
    ("modify_boundary_short_of_its_top", 'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, '
                                         '"top": [[1000, 1000], [9000, 1000], [9000, 5000], [1000, 5000]]}\n'
                                         'modify {"id": 100002, "boundary": [[0, 0], [100, 0], [0, 100]]}'),
    ("delete_its_level", 'mass {"boundary": ' + json.dumps(BLOCK) + '}\ndelete {"ids": [100000]}'),
    ("no_area", 'mass {"boundary": [[0, 0], [1000, 0], [2000, 0]]}'),
    ("floor_by_face_of_a_bow_tie", 'mass {"boundary": [[0, 0], [4000, 4000], [4000, 0], [0, 2000]], "height": 3000}\n'
                                   'floor_by_face {"mass": 100002}'),
    ("mass_floors_of_a_bow_tie", 'mass {"boundary": [[0, 0], [4000, 4000], [4000, 0], [0, 2000]], "height": 3000}\nmass_floors {}'),
]


@_cases(MASS_REFUSALS)
def test_mass_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that accepts a top outline that doesn't pair up with the footprint, runs the other way round
    or collapses the mass, both `top` and `lean`, a mass whose top isn't above its base, or deletes a level a mass
    stands on, or that words those refusals differently."""
    golden.check_run(_script(workdir, run, [line]), f"mass_refusal_{name}.txt")


def test_mass_floors_make_update_and_prune_a_floor_on_each_level(run, workdir, golden):
    """CATCHES: a rewrite whose mass floors start at another level, make one at the mass's top, make a second floor on
    a second run, don't give their floors the mass's new outline or type, don't list stale floors, or delete them
    without `prune`."""
    r = _script(workdir, run, [
        *TOWER,
        'MF {"mass": 100004}',
        'elements {"category": "floor"}',
        'mass_floors {"mass": 100004}',
        'floor {"boundary": [[0, 0], [1000, 0], [0, 1000]]}',
        'modify {"id": 100004, "boundary": [[0, 0], [12000, 0], [12000, 6000], [0, 6000]]}',
        'mass_floors {"mass": 100004}',
        'modify {"id": 100004, "top_level": 100002}',
        'mass_floors {"mass": 100004, "type": "Generic - 200mm"}',
        'mass_floors {"mass": 100004, "prune": true}',
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "base_offset": 500, "height": 7000}',
        'mass_floors {}',
        'elements {"category": "floor"}',
        'schedule {"category": "massfloors", "sort": ["Level"]}',
    ])
    golden.check_run(r, "mass_floors.txt")


@_cases([
    ("no_mass_at_all", 'delete {"ids": [100004]}\nmass_floors {}'),
    ("unknown_type", 'mass_floors {"mass": 100004, "type": "Nothing"}'),
    ("not_a_mass", 'wall {"points": [[0, 0], [1000, 0]]}\nmass_floors {"mass": 100005}'),
    ("prune_not_a_flag", 'mass_floors {"mass": 100004, "prune": "yes"}'),
    ("mark_on_a_wall", 'wall {"points": [[0, 0], [1000, 0]]}\n'
                       'modify {"id": 100005, "params": {"Mass Floor": {"mass": 100004, "level": 100000}}}'),
])
def test_mass_floors_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose mass floors run with no mass, of an unknown type, from what is no mass, or let a wall
    hold a mass floor's mark, or word those refusals differently."""
    golden.check_run(_script(workdir, run, [*TOWER, line]), f"mass_floors_refusal_{name}.txt")


def test_walls_floors_and_roofs_by_face_follow_a_mass(run, workdir, golden):
    """CATCHES: a rewrite whose walls by face stand off the footprint's edges, face in, reach another height or base,
    whose floor or roof by face lies elsewhere than the mass's top face, or which marks them with another mass face."""
    r = _script(workdir, run, [
        'mass {"boundary": ' + json.dumps(BLOCK) + "}",
        'WB {"mass": 100002}',
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 4000, "base_offset": 200}',
        'wall_by_face {"mass": 100007, "faces": [1, 3], "location": "centre", "type": "Interior - 100mm"}',
        'FB {"mass": 100002}',
        'floor_by_face {"mass": 100007, "type": "Generic - 200mm"}',
        'RB {"mass": 100002}',
        'roof_by_face {"mass": 100007, "slope": 20, "overhang": 300}',
        'elements {"category": "wall"}',
        'elements {"category": "floor"}',
        'elements {"category": "roof"}',
        'render {"view": "Level 1", "path": "plan.svg"}',
        'delete {"ids": [100002, 100007]}',
        'elements {"category": "wall", "limit": 1}',
    ])
    golden.check_run(r, "by_face.txt")
    golden.check((workdir / "plan.svg").read_text(), "by_face.svg")


def test_by_face_on_a_lofted_mass_stands_only_on_plumb_faces(run, workdir, golden):
    """CATCHES: a rewrite that stands a wall on a face that leans, or puts a floor or roof on the footprint instead of
    the top outline of a lofted mass."""
    r = _script(workdir, run, [
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "top": [[0, 0], [10000, 0], [8000, 6000], [0, 6000]]}',
        'wall_by_face {"mass": 100002}',
        'floor_by_face {"mass": 100002}',
        'roof_by_face {"mass": 100002}',
        'elements {"category": "floor"}',
        'elements {"category": "roof"}',
    ])
    golden.check_run(r, "by_face_lofted.txt")


BY_FACE_SETUP = [
    'level {"elevation": 6000, "name": "Level 3"}',
    'mass {"boundary": ' + json.dumps(BLOCK) + ', "top_level": 100002, "top": [[2000, 2000], [8000, 2000], [8000, 4000], [2000, 4000]]}',
    'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 4000}',
]


@_cases([
    ("every_face_leans", 'wall_by_face {"mass": 100003}'),
    ("chosen_face_leans", 'wall_by_face {"mass": 100003, "faces": [1]}'),
    ("face_past_the_last", 'wall_by_face {"mass": 100004, "faces": [4]}'),
    ("face_negative", 'wall_by_face {"mass": 100004, "faces": [-1]}'),
    ("face_not_a_number", 'wall_by_face {"mass": 100004, "faces": ["top"]}'),
    ("faces_not_a_list", 'wall_by_face {"mass": 100004, "faces": 2}'),
    ("unknown_wall_type", 'wall_by_face {"mass": 100004, "type": "Nothing"}'),
    ("not_a_mass", 'wall_by_face {"mass": 100000}'),
    ("no_mass_given", 'wall_by_face {}'),
    ("floor_not_a_mass", 'floor_by_face {"mass": 100000}'),
    ("roof_no_mass_given", 'roof_by_face {}'),
    ("roof_too_steep", 'roof_by_face {"mass": 100004, "slope": 80}'),
])
def test_by_face_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that stands a wall on a leaning face or one that is no edge of the footprint, makes by face
    from what is no mass, or gives a roof by face a slope past 75°, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [*BY_FACE_SETUP, line]), f"by_face_refusal_{name}.txt")


def test_update_by_face_rebuilds_what_was_made_from_the_mass_as_it_is_now(run, workdir, golden):
    """CATCHES: a rewrite whose Update to Face doesn't move walls onto the mass's new edges and height, loses a roof's
    slope or a type changed since, renumbers a mirrored mass's faces otherwise, updates part of a request when a face
    is gone, or reports `updated` and `unchanged` otherwise."""
    r = _script(workdir, run, [
        *TOWER,
        'WB {"mass": 100004}',
        'FB {"mass": 100004}',
        'RB {"mass": 100004}',
        'modify {"id": 100004, "boundary": [[0, 0], [12000, 0], [12000, 6000], [0, 6000]], "top_level": 100002}',
        'UF {"mass": 100004}',
        'update_by_face {}',
        'modify {"id": 100010, "slope": 25}',
        'modify {"id": 100004, "top_level": 100003}',
        'update_by_face {"ids": [100010, 100007]}',
        'elements {"category": "wall"}',
        'elements {"category": "roof"}',
        'mass {"boundary": ' + json.dumps(BLOCK) + ', "height": 3000, "name": "Flip"}',
        'wall_by_face {"mass": 100011, "faces": [0, 1]}',
        'mirror {"ids": [100011], "axis": [[-1000, 0], [-1000, 1000]]}',
        'update_by_face {"mass": 100011}',
        'elements {"category": "wall"}',
        'modify {"id": 100004, "boundary": [[0, 0], [12000, 0], [0, 6000]]}',
        'update_by_face {"ids": [100005, 100006, 100009]}',
        'elements {"category": "floor"}',
    ])
    golden.check_run(r, "update_by_face.txt")


@_cases([
    ("a_face_gone", 'modify {"id": 100004, "boundary": [[0, 0], [12000, 0], [0, 6000]]}\nupdate_by_face {"mass": 100004}'),
    ("not_made_by_face", 'update_by_face {"ids": [100010]}'),
    ("not_a_mass", 'update_by_face {"mass": 100010}'),
    ("ids_and_mass", 'update_by_face {"mass": 100004, "ids": [100005]}'),
    ("no_such_element", 'update_by_face {"ids": [9999]}'),
    ("ids_not_a_list", 'update_by_face {"ids": "x"}'),
    ("mass_deleted", 'delete {"ids": [100004]}\nupdate_by_face {}'),
    ("mark_beyond_the_footprint", 'modify {"id": 100010, "params": {"Mass Face": {"mass": 100004, "face": 7}}}\n'
                                  'update_by_face {"ids": [100010]}'),
    ("mark_top_on_a_wall", 'modify {"id": 100005, "params": {"Mass Face": {"mass": 100004, "face": "top"}}}'),
    ("mark_edge_on_a_floor", 'modify {"id": 100009, "params": {"Mass Face": {"mass": 100004, "face": 0}}}'),
    ("mark_of_no_mass", 'modify {"id": 100005, "params": {"Mass Face": {"mass": 100010, "face": 0}}}'),
    ("mark_without_face", 'modify {"id": 100005, "params": {"Mass Face": {"mass": 100004}}}'),
    ("a_face_leans_now", 'modify {"id": 100004, "top": [[0, 0], [10000, 0], [10000, 5000], [0, 5000]]}\n'
                         'update_by_face {"ids": [100005, 100006]}'),
])
def test_update_by_face_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose Update to Face updates part of what was asked when a face is gone, takes what isn't
    made by face or a mass that isn't one, both `ids` and `mass`, or a mark of the wrong kind for its element, or words
    those refusals differently."""
    setup = [*TOWER, 'WB {"mass": 100004}', 'FB {"mass": 100004}', 'wall {"points": [[0, 0], [100, 0]]}']
    golden.check_run(_script(workdir, run, [*setup, line]), f"update_by_face_refusal_{name}.txt")


def test_show_mass_toggles_the_mass_category_in_one_view(run, workdir, golden):
    """CATCHES: a rewrite whose Show Mass changes other views than the one asked, doesn't flip what the view does now
    when not told, makes no undo step, or still draws masses in a plan that hides them."""
    r = _script(workdir, run, [
        *TOWER,
        'MH {"view": 100000}',
        'render {"view": "Level 1", "path": "hidden.svg"}',
        'show_mass {"view": 100000}',
        'show_mass {"view": "Level 1", "show": false}',
        'show_mass {"view": "Level 1", "show": false}',
        'show_mass {"view": 100000, "show": true}',
        'undo',
        'graphics {"view": "Level 1"}',
        'show_mass {"view": "{3D}", "show": false}',
        'section {"start": [5000, -4000], "end": [5000, 10000]}',
        'show_mass {"view": 100006}',
        'show_mass {}',
        'render {"view": "Level 2", "path": "shown.svg"}',
    ])
    golden.check_run(r, "show_mass.txt")
    golden.check((workdir / "hidden.svg").read_text(), "show_mass_hidden.svg")
    golden.check((workdir / "shown.svg").read_text(), "show_mass_shown.svg")


@_cases([
    ("show_not_a_flag", 'show_mass {"view": 100000, "show": "yes"}'),
    ("show_a_number", 'show_mass {"view": 100000, "show": 5}'),
    ("no_such_view", 'show_mass {"view": "nowhere"}'),
    ("view_follows_a_template", 'template {"name": "T", "controls": ["categories"]}\n'
                            'graphics {"view": 100001, "template": "T"}\nshow_mass {"view": 100001}'),
])
def test_show_mass_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite whose Show Mass takes a `show` that is no yes or no, a view that doesn't exist, or changes a
    view whose categories follow a template, or words those refusals differently."""
    golden.check_run(_script(workdir, run, [*TOWER, line]), f"show_mass_refusal_{name}.txt")


def test_a_mass_holds_the_projects_parameters_for_masses(run, workdir, golden):
    """CATCHES: a rewrite whose mass doesn't hold a project parameter's value, lets its copy lose it, or takes a value of
    the wrong kind or a parameter of another category without saying so."""
    r = _script(workdir, run, [
        'parameter {"name": "Use", "kind": "text", "categories": ["mass"]}',
        'mass {"boundary": ' + json.dumps(BLOCK) + "}",
        'modify {"id": 100002, "params": {"Use": "Housing"}}',
        'copy {"ids": [100002], "by": [0, 8000]}',
        'elements {"category": "mass"}',
    ])
    golden.check_run(r, "parameters.txt")
    setup = ['parameter {"name": "Use", "kind": "text", "categories": ["mass"]}', 'mass {"boundary": ' + json.dumps(BLOCK) + "}",
             'wall {"points": [[0, 0], [1000, 0]]}']
    for name, line in [("wrong_kind", 'modify {"id": 100002, "params": {"Use": 5}}'),
                       ("not_for_walls", 'modify {"id": 100003, "params": {"Use": "Housing"}}'),
                       ("reserved_name", 'parameter {"name": "Mass Face", "kind": "text", "categories": ["wall"]}')]:
        golden.check_run(_script(workdir, run, [*setup, line]), f"parameters_refusal_{name}.txt")
