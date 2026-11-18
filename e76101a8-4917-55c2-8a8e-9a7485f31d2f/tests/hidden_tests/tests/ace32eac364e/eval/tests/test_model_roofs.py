"""Roofs (over the walls or a footprint: hipped, gabled, per-edge slopes, courtyards, extrusions, openings, joins) and
dormers: what `elements` derives (ridge, area, outline), the plan of the level they stand on, and every refusal."""

import json

import pytest
from conftest import normalize

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'
RECT = [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _rounded(value, places):
    """VALUE with every float rounded to PLACES decimals."""
    if isinstance(value, float):
        return round(value, places) + 0.0
    if isinstance(value, list):
        return [_rounded(v, places) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v, places) for k, v in value.items()}
    return value


def _rounded_outcome(r, places=4):
    """The outcome with each reply's floats rounded: a dormer's heights come from tangents and cosines, whose last bits
    may differ between machines, and are kept unrounded."""
    lines = [json.dumps(_rounded(json.loads(line), places), sort_keys=True) for line in r.stdout.decode().splitlines()]
    return (f"exit: {r.returncode}\n--- stdout\n" + normalize("".join(line + "\n" for line in lines))
            + "--- stderr\n" + normalize(r.stderr.decode("utf-8", "replace")))


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


# Each: the walls (or nothing), the roof command, and what it shows: a footprint's straight skeleton, drawn in the
# plan of the level the roof is on.
FOOTPRINTS = {
    "hip_over_a_box": ([BOX, 'wall {"points": [[4000, 0], [4000, 6000]]}'], 'roof {}'),
    "gable_ends": ([BOX], 'roof {"gable": true, "slope": 40}'),
    "l_shape_over_walls": (['wall {"points": [[0, 0], [12000, 0], [12000, 6000], [6000, 6000], [6000, 12000], [0, 12000]], "closed": true}'],
                           'roof {}'),
    "l_shape_with_gables": (['wall {"points": [[0, 0], [12000, 0], [12000, 6000], [6000, 6000], [6000, 12000], [0, 12000]], "closed": true}'],
                            'roof {"gables": [1, 4]}'),
    "triangle": ([], 'roof {"boundary": [[20000, 0], [26000, 0], [23000, 5196.152]]}'),
    "flat_triangle": ([], 'roof {"slope": 0, "boundary": [[0, 0], [4000, 0], [2000, 3000]], "offset": 250}'),
    "t_shape": ([], 'roof {"boundary": [[0, 0], [12000, 0], [12000, 4000], [8000, 4000], [8000, 10000], [4000, 10000], '
                    '[4000, 4000], [0, 4000]], "slope": 35}'),
    "u_shape_overhang": ([], 'roof {"boundary": [[0, 0], [14000, 0], [14000, 10000], [10000, 10000], [10000, 4000], [4000, 4000], '
                             '[4000, 10000], [0, 10000]], "overhang": 600, "slope": 25}'),
    "per_edge_slopes": ([], 'roof {"boundary": ' + json.dumps(RECT) + ', "slope": 30, "slopes": [30, 45, 30, 45]}'),
    "slopes_with_gables": ([], 'roof {"boundary": ' + json.dumps(RECT) + ', "slope": 30, "slopes": [0, 10, 0, 74], "gables": [1, 3]}'),
    "courtyard_given": ([], 'roof {"boundary": [[0, 0], [16000, 0], [16000, 16000], [0, 16000]], '
                            '"courtyards": [[[6000, 6000], [10000, 6000], [10000, 10000], [6000, 10000]]]}'),
    "courtyard_gable": ([], 'roof {"boundary": [[0, 0], [16000, 0], [16000, 16000], [0, 16000]], '
                            '"courtyards": [[[6000, 6000], [10000, 6000], [10000, 10000], [6000, 10000]]], "gables": [4]}'),
    "courtyard_edge_slope": ([], 'roof {"boundary": ' + json.dumps(RECT) + ', "courtyards": [[[2000, 2000], [6000, 2000], [6000, 4000], '
                                 '[2000, 4000]]], "slope": 30, "slopes": [0, 0, 0, 0, 45, 0, 0, 0]}'),
    "courtyard_over_walls": (['wall {"points": [[0, 0], [16000, 0], [16000, 16000], [0, 16000]], "closed": true}',
                              'wall {"points": [[6000, 6000], [10000, 6000], [10000, 10000], [6000, 10000]], "closed": true}'], 'roof {}'),
    "courtyard_roofed_over_by_overhang": (['wall {"points": [[0, 0], [16000, 0], [16000, 16000], [0, 16000]], "closed": true}',
                                           'wall {"points": [[6000, 6000], [10000, 6000], [10000, 10000], [6000, 10000]], "closed": true}'],
                                          'roof {"overhang": 2100}'),
    "courtyard_with_a_room_is_indoors": (['wall {"points": [[0, 0], [16000, 0], [16000, 16000], [0, 16000]], "closed": true}',
                                          'wall {"points": [[6000, 6000], [10000, 6000], [10000, 10000], [6000, 10000]], "closed": true}',
                                          'room {"point": [8000, 8000], "name": "Hall"}'], 'roof {}'),
    "sketch_with_slopes": ([], 'roof {"slope": 30, "sketch": [{"start": [0, 0], "end": [8000, 0]}, {"start": [8000, 0], '
                               '"end": [8000, 6000], "slope": 45}, {"start": [8000, 6000], "end": [0, 6000]}, {"start": [0, 6000], '
                               '"end": [0, 0], "slope": 45}]}'),
    "openings_and_offset": ([], 'roof {"boundary": ' + json.dumps(RECT) + ', "offset": 400, "slope": 20, '
                                '"openings": [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]]}'),
    "level_one_up": ([], 'roof {"level": "Level 1", "boundary": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]], "type": "Generic - 300mm"}'),
    "t_shape_gabled_wings": ([], 'roof {"boundary": [[0, 0], [12000, 0], [12000, 4000], [8000, 4000], [8000, 10000], [4000, 10000], '
                                 '[4000, 4000], [0, 4000]], "gables": [1, 3, 4, 5, 7]}'),
    "comb": ([], 'roof {"boundary": [[0, 0], [2000, 0], [2000, 3000], [4000, 3000], [4000, 0], [6000, 0], [6000, 3000], [8000, 3000], '
                 '[8000, 0], [10000, 0], [10000, 5000], [0, 5000]]}'),
    "two_courtyards": ([], 'roof {"boundary": [[0, 0], [10000, 0], [10000, 10000], [0, 10000]], "courtyards": [[[1000, 1000], '
                           '[3000, 1000], [3000, 3000], [1000, 3000]], [[6000, 6000], [9000, 6000], [9000, 9000], [6000, 9000]]]}'),
    "wide_courtyard": ([], 'roof {"boundary": [[0, 0], [10000, 0], [10000, 10000], [0, 10000]], '
                           '"courtyards": [[[500, 2000], [9500, 2000], [9500, 8000], [500, 8000]]]}'),
    "star": ([], 'roof {"boundary": [[0, 0], [5000, -2000], [10000, 0], [7000, 2000], [10000, 6000], [5000, 4000], [0, 6000], '
                 '[3000, 2000]], "slope": 40}'),
    "courtyard_all_gables": ([], 'roof {"boundary": [[0, 0], [10000, 0], [10000, 6000], [0, 6000]], "courtyards": [[[2000, 2000], '
                                 '[8000, 2000], [8000, 4000], [2000, 4000]]], "gables": [4, 5, 6, 7]}'),
    "thin_steep_ends": ([], 'roof {"boundary": [[0, 0], [10000, 0], [10000, 1000], [0, 1000]], "slopes": [10, 70, 10, 70]}'),
    "square_two_gables": ([], 'roof {"boundary": [[0, 0], [6000, 0], [6000, 6000], [0, 6000]], "gables": [0, 2]}'),
    "dumbbell": ([], 'roof {"boundary": [[0, 0], [4000, 0], [4000, 1500], [6000, 1500], [6000, 0], [10000, 0], [10000, 4000], '
                     '[6000, 4000], [6000, 2500], [4000, 2500], [4000, 4000], [0, 4000]]}'),
    "chevron": ([], 'roof {"boundary": [[0, 0], [5000, 3000], [10000, 0], [10000, 2000], [5000, 5000], [0, 2000]]}'),
    "courtyard_near_the_eaves": ([], 'roof {"boundary": [[0, 0], [10000, 0], [10000, 10000], [0, 10000]], '
                                     '"courtyards": [[[1000, 500], [9000, 500], [9000, 9000], [1000, 9000]]]}'),
    "short_edge": ([], 'roof {"boundary": [[0, 0], [10000, 0], [10000, 50], [10050, 3000], [10000, 6000], [0, 6000]]}'),
    "notch": ([], 'roof {"boundary": [[0, 0], [8000, 0], [8000, 6000], [4100, 6000], [4000, 3000], [3900, 6000], [0, 6000]]}'),
}


@pytest.mark.parametrize("case", sorted(FOOTPRINTS))
def test_roofs_by_footprint(run, workdir, golden, case):
    """CATCHES: a rewrite whose roof footprint over the walls differs (500 mm past their faces, courtyards found in free
    loops of walls), or whose straight skeleton (hips, valleys, ridges, gable ends, edges of different slopes meeting
    along hips) puts its ridge at another height, measures another area, or draws other slopes in the roof's plan."""
    walls, roof = FOOTPRINTS[case]
    r = _script(workdir, run, [*walls, roof, 'elements {"category": "roof"}', 'render {"view": "Level 2", "path": "roof.svg"}',
                               'render {"view": "Level 1", "path": "below.svg"}'])
    golden.check_run(r, f"footprint_{case}.txt")
    golden.check((workdir / "roof.svg").read_text(), f"footprint_{case}.svg")


def test_a_roof_edited_keeps_its_slopes_and_gables_where_its_edges_stay(run, workdir, golden):
    """CATCHES: a rewrite whose `edit_boundary` of a roof loses the gables on edges that stay, the slope of an edge it
    cuts in two, or doesn't give back the slope a line's edges share, and whose `modify` of `slopes`, `gables` or
    `slope` reshapes the roof otherwise."""
    lines = [
        'roof {"boundary": ' + json.dumps(RECT) + ', "slope": 30, "slopes": [30, 45, 30, 45], "gables": [1]}',
        'edit_boundary {"id": 100002}',
        'edit_boundary {"id": 100002, "sketch": [[[0, 0], [4000, 0]], [[4000, 0], [8000, 0]], [[8000, 0], [8000, 6000]], '
        '[[8000, 6000], [0, 6000]], [[0, 6000], [0, 0]]]}',
        'elements {"category": "roof"}',
        'edit_boundary {"id": 100002, "sketch": [[[0, -1000], [8000, -1000]], [[8000, -1000], [8000, 6000]], [[8000, 6000], [0, 6000]], '
        '[[0, 6000], [0, -1000]]]}',
        'elements {"category": "roof"}',
        'edit_boundary {"id": 100002, "sketch": [{"start": [0, -1000], "end": [8000, -1000], "slope": 50}, '
        '{"start": [8000, -1000], "end": [8000, 6000]}, {"start": [8000, 6000], "end": [0, 6000], "slope": 0}, '
        '{"start": [0, 6000], "end": [0, -1000]}]}',
        'edit_boundary {"id": 100002}',
        'modify {"id": 100002, "slopes": []}',
        'modify {"id": 100002, "slope": 20, "gables": [0, 2]}',
        'elements {"category": "roof"}',
        'modify {"id": 100002, "slope": 0}',
        'elements {"category": "roof"}',
    ]
    golden.check_run(_script(workdir, run, lines), "edited.txt")


ROOF_REFUSALS = [
    ("no_walls_below", 'roof {"level": "Level 2"}'),
    ("no_level_below", 'roof {"level": "Level 1"}'),
    ("boundary_too_small", 'roof {"boundary": [[0, 0], [1000, 0]]}'),
    ("slope_too_steep", 'roof {"boundary": ' + json.dumps(RECT) + ', "slope": 80}'),
    ("slope_negative", 'roof {"boundary": ' + json.dumps(RECT) + ', "slope": -5}'),
    ("slopes_too_few", 'roof {"boundary": ' + json.dumps(RECT) + ', "slope": 30, "slopes": [30, 45, 30]}'),
    ("slopes_edge_too_steep", 'roof {"boundary": ' + json.dumps(RECT) + ', "slopes": [30, 80, 30, 30]}'),
    ("slopes_edge_negative", 'roof {"boundary": ' + json.dumps(RECT) + ', "slopes": [30, 30, -5, 30]}'),
    ("slopes_not_a_list", 'roof {"boundary": ' + json.dumps(RECT) + ', "slopes": "steep"}'),
    ("slopes_courtyard_not_counted", 'roof {"boundary": ' + json.dumps(RECT) + ', "courtyards": [[[2000, 2000], [6000, 2000], '
                                     '[6000, 4000], [2000, 4000]]], "slopes": [30, 30, 30, 30]}'),
    ("gable_not_an_edge", 'roof {"boundary": ' + json.dumps(RECT) + ', "gables": [6]}'),
    ("gable_on_a_triangle", 'roof {"boundary": [[0, 0], [4000, 0], [2000, 3000]], "gable": true}'),
    ("courtyard_outside", 'roof {"boundary": ' + json.dumps(RECT) + ', "courtyards": [[[20000, 0], [22000, 0], [22000, 2000]]]}'),
    ("courtyard_across_the_edge", 'roof {"boundary": ' + json.dumps(RECT) + ', "courtyards": [[[-1000, 2000], [2000, 2000], '
                                  '[2000, 4000], [-1000, 4000]]]}'),
    ("courtyards_overlap", 'roof {"boundary": [[0, 0], [16000, 0], [16000, 16000], [0, 16000]], "courtyards": [[[6000, 6000], '
                           '[10000, 6000], [10000, 10000], [6000, 10000]], [[7000, 7000], [12000, 7000], [12000, 12000]]]}'),
    ("extrusion_with_courtyards", 'roof {"extrusion": {"line": [[0, 0], [16000, 0]], "profile": [[0, 0], [8000, 3000], [16000, 0]], '
                                  '"to": 16000}, "courtyards": [[[6000, 6000], [10000, 6000], [10000, 10000]]]}'),
    ("extrusion_with_slopes", 'roof {"extrusion": {"line": [[0, 0], [4000, 0]], "profile": [[0, 0], [2000, 1000], [4000, 0]], '
                              '"to": 3000}, "slopes": [30]}'),
    ("extrusion_profile_backwards", 'roof {"extrusion": {"line": [[0, 0], [4000, 0]], "profile": [[0, 0], [0, 1000]], "to": 3000}}'),
    ("extrusion_one_point", 'roof {"extrusion": {"line": [[0, 0], [4000, 0]], "profile": [[0, 0]], "to": 3000}}'),
    ("extrusion_swept_backwards", 'roof {"extrusion": {"line": [[0, 0], [4000, 0]], "profile": [[0, 0], [4000, 0]], "from": 0, '
                                  '"to": -600}}'),
    ("extrusion_line_too_short", 'roof {"extrusion": {"line": [[0, 0], [0, 0]], "profile": [[0, 0], [4000, 0]], "to": 600}}'),
    ("extrusion_missing_to", 'roof {"extrusion": {"line": [[0, 0], [4000, 0]], "profile": [[0, 0], [4000, 0]]}}'),
    ("sketch_line_slope_too_steep", 'roof {"sketch": [{"start": [0, 0], "end": [8000, 0], "slope": 90}, {"start": [8000, 0], '
                                    '"end": [8000, 6000]}, {"start": [8000, 6000], "end": [0, 6000]}, {"start": [0, 6000], "end": [0, 0]}]}'),
    ("floor_sketch_with_a_slope", 'floor {"sketch": [{"start": [0, 0], "end": [8000, 0], "slope": 30}, {"start": [8000, 0], '
                                  '"end": [8000, 6000]}, {"start": [8000, 6000], "end": [0, 6000]}, {"start": [0, 6000], "end": [0, 0]}]}'),
    ("opening_bow_tie", 'roof {"boundary": ' + json.dumps(RECT) + ', "openings": [[[1000, 1000], [2000, 2000], [2000, 1000], [1000, 2000]]]}'),
    ("join_not_a_roof", 'roof {"boundary": ' + json.dumps(RECT) + ', "join": 100000}'),
    ("unknown_type", 'roof {"boundary": ' + json.dumps(RECT) + ', "type": "Thatch"}'),
    ("every_edge_a_gable", 'roof {"boundary": ' + json.dumps(RECT) + ', "gables": [0, 1, 2, 3]}'),
    ("gables_fence_in_a_wing", 'roof {"boundary": [[0, 0], [12000, 0], [12000, 4000], [8000, 4000], [8000, 10000], [4000, 10000], '
                               '[4000, 4000], [0, 4000]], "gables": [0, 1, 2, 3, 4, 6, 7]}'),
    ("gables_not_a_list", 'roof {"boundary": ' + json.dumps(RECT) + ', "gables": "ends"}'),
    ("gable_not_a_flag", 'roof {"boundary": ' + json.dumps(RECT) + ', "gable": "yes"}'),
]


@_cases(ROOF_REFUSALS)
def test_roof_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that accepts slopes past 75° or of the wrong number, a gable that is no edge, a courtyard
    outside or overlapping, an extrusion whose profile runs back or that sweeps backwards, a sketch line's slope on a
    floor, or that words those refusals differently (they say how many edges there are and which is wrong)."""
    golden.check_run(_script(workdir, run, [line]), f"roof_refusal_{name}.txt")


def test_extrusion_roofs_sweep_their_profile_and_walls_attach_to_them(run, workdir, golden):
    """CATCHES: a rewrite whose extrusion roof has another ridge or area, or whose walls attached under it don't follow
    its profile."""
    r = _script(workdir, run, [
        BOX,
        'roof {"extrusion": {"line": [[0, 0], [8000, 0]], "profile": [[-500, 0], [3000, 2000], [8500, 0]], "from": -600, "to": 6600}}',
        'modify {"ids": [100002, 100003, 100004, 100005], "attach_top": 100006}',
        'elements {"category": "wall"}',
        'roof {"extrusion": {"line": [[20000, 0], [20000, 6000]], "profile": [[0, 0], [6000, 1500]], "to": 4000}, '
        '"openings": [[[18000, 1000], [19000, 1000], [19000, 2000], [18000, 2000]]], "offset": 300}',
        'elements {"category": "roof"}',
        'render {"view": "Level 2", "path": "roof.svg"}',
    ])
    golden.check_run(r, "extrusion.txt")
    golden.check((workdir / "roof.svg").read_text(), "extrusion.svg")


def test_a_roof_joined_to_another_ends_at_its_top(run, workdir, golden):
    """CATCHES: a rewrite whose joined roof doesn't stop where it meets the other's top, or keeps the join after that
    roof is deleted."""
    r = _script(workdir, run, [
        'roof {"boundary": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]], "slope": 30}',
        'roof {"boundary": [[4000, -3000], [8000, -3000], [8000, 4000], [4000, 4000]], "slope": 30, "gables": [0], "join": 100002}',
        'elements {"category": "roof"}',
        'render {"view": "Level 2", "path": "roof.svg"}',
        'delete {"ids": [100002]}',
        'elements {"category": "roof"}',
    ])
    golden.check_run(r, "join.txt")
    golden.check((workdir / "roof.svg").read_text(), "join.svg")


def test_dormers_stand_out_of_a_roof_and_open_it_under_them(run, workdir, golden):
    """CATCHES: a rewrite whose dormer walls, roof or window stand elsewhere or at other heights, that doesn't open the
    host roof under it, or that leaves the dormer's roof joined and its walls attached once the host is deleted."""
    r = _script(workdir, run, [
        'wall {"points": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]], "closed": true}',
        'roof {}',
        'dormer {"host": 100006, "at": [6000, 1000], "width": 1600, "height": 800, "window": "Fixed 600 x 900"}',
        'dormer {"host": 100006, "at": [6000, 7000], "type": "Interior - 100mm", "slope": 40, "height": 600}',
        'elements {"category": "roof"}',
        'elements {"category": "wall"}',
        'elements {"category": "window"}',
        'render {"view": "Level 2", "path": "roof.svg"}',
        'delete {"ids": [100006]}',
        'elements {"category": "roof"}',
        'elements {"category": "wall"}',
    ])
    golden.check(_rounded_outcome(r), "dormers.txt")
    golden.check((workdir / "roof.svg").read_text(), "dormers.svg")


DORMER_REFUSALS = [
    ("no_host", 'dormer {"at": [6000, 1000]}'),
    ("host_not_a_roof", 'dormer {"host": 100002, "at": [6000, 1000]}'),
    ("host_joins_another", 'roof {"boundary": [[4000, -3000], [8000, -3000], [8000, 1000], [4000, 1000]], "join": 100006}\n'
                           'dormer {"host": 100007, "at": [6000, -2000]}'),
    ("no_at", 'dormer {"host": 100006}'),
    ("not_over_the_roof", 'dormer {"host": 100006, "at": [30000, 1000]}'),
    ("on_a_flat_roof", 'roof {"slope": 0, "boundary": [[20000, 0], [24000, 0], [24000, 4000], [20000, 4000]]}\n'
                       'dormer {"host": 100007, "at": [22000, 2000]}'),
    ("narrower_than_its_walls", 'dormer {"host": 100006, "at": [6000, 1000], "width": 150}'),
    ("slope_too_steep", 'dormer {"host": 100006, "at": [6000, 1000], "slope": 80}'),
    ("no_height", 'dormer {"host": 100006, "at": [6000, 1000], "height": 0}'),
    ("over_the_ridge", 'dormer {"host": 100006, "at": [6000, 3000], "height": 2500}'),
    ("unknown_window_type", 'dormer {"host": 100006, "at": [6000, 1000], "height": 800, "window": "Bay"}'),
]


@_cases(DORMER_REFUSALS)
def test_dormer_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that stands a dormer on what is no roof, off the roof, on a level roof or one that joins
    another, narrower than its walls, too steep or running over the ridge, or that words those refusals differently."""
    setup = ['wall {"points": [[0, 0], [12000, 0], [12000, 8000], [0, 8000]], "closed": true}', 'roof {}']
    golden.check_run(_script(workdir, run, [*setup, line]), f"dormer_refusal_{name}.txt")
