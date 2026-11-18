"""Stairs, ramps and railings: risers, runs, landings and turns, slopes, railings along a host's sides or a path, what
`elements` derives (risers, riser height, runs, ends, lengths, railing paths), their plans, and every refusal."""

import pytest

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'


def _script(workdir, run, lines, *extra):
    """Run LINES as one script (one `id {json}` per line), then the EXTRA options of `run`."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    return run(["run", "--script", "s.txt", *extra])


def _cases(cases):
    """Parametrize a test over (name, command) cases, each run after the test's setup in a fresh project."""
    return pytest.mark.parametrize("name,line", cases, ids=[name for name, _ in cases])


def test_stairs_climb_in_risers_and_turn_at_landings(run, workdir, golden):
    """CATCHES: a rewrite whose stair has another number of risers (as many as keep each at most `riser`), another
    tread run or width, lays its runs and landings out elsewhere for each kind of turn, or reports other runs, end,
    length or riser height."""
    r = _script(workdir, run, [
        BOX,
        'stair {"start": [1000, 1000], "end": [1000, 2000]}',
        'stair {"start": [3000, 1000], "angle": 90, "landings": [{"at": 8, "turn": -90}]}',
        'stair {"start": [5000, 1000], "angle": 90, "landings": [{"at": 8, "turn": 180}]}',
        'stair {"start": [7000, 5000], "angle": 270, "landings": [{"at": 6, "turn": 90}, {"at": 12, "turn": -180}]}',
        'stair {"start": [10000, 0], "landings": [{"at": 5}], "width": 1200, "riser": 170, "tread": 300}',
        'stair {"start": [14000, 0], "angle": 180, "height": 1000, "top_level": null}',
        'level {"elevation": 7000}',
        'stair {"start": [18000, 0], "level": "Level 2", "top_level": 100012, "angle": 30}',
        'elements {"category": "stairs"}',
        'render {"view": "Level 1", "path": "plan.svg"}',
    ])
    golden.check_run(r, "stairs.txt")
    golden.check((workdir / "plan.svg").read_text(), "stairs.svg")


def test_a_stair_moves_and_mirrors_with_its_turns(run, workdir, golden):
    """CATCHES: a rewrite whose mirrored stair keeps turning the same way, or whose moved stair or railings stay put."""
    r = _script(workdir, run, [
        BOX,
        'stair {"start": [1000, 1000], "angle": 90, "landings": [{"at": 8, "turn": 180}], "railings": true}',
        'mirror {"ids": [100006], "axis": [[4000, 0], [4000, 1000]]}',
        'elements {"category": "stair"}',
        'move {"ids": [100006], "by": [-500, 0]}',
        'elements {"category": "railing"}',
        'copy {"ids": [100006], "by": [0, 8000]}',
        'delete {"ids": [100006]}',
        'elements {"category": "railing"}',
    ])
    golden.check_run(r, "stair_moves.txt")


STAIR_REFUSALS = [
    ("no_start", 'stair {}'),
    ("end_on_start", 'stair {"start": [1000, 1000], "end": [1000, 1000]}'),
    ("too_many_risers", 'stair {"start": [0, 0], "end": [1000, 0], "riser": 1}'),
    ("one_riser", 'stair {"start": [0, 0], "height": 100, "top_level": null}'),
    ("landing_too_early", 'stair {"start": [0, 0], "landings": [{"at": 1, "turn": 0}]}'),
    ("landing_too_late", 'stair {"start": [0, 0], "landings": [{"at": 16, "turn": 0}]}'),
    ("landing_turn_45", 'stair {"start": [0, 0], "landings": [{"at": 8, "turn": 45}]}'),
    ("landings_out_of_order", 'stair {"start": [0, 0], "landings": [{"at": 9, "turn": 0}, {"at": 8, "turn": 0}]}'),
    ("landing_half_a_riser", 'stair {"start": [0, 0], "landings": [{"at": 8.5, "turn": 0}]}'),
    ("landing_without_at", 'stair {"start": [0, 0], "landings": [{"turn": 90}]}'),
    ("landings_not_a_list", 'stair {"start": [0, 0], "landings": 3}'),
    ("width_zero", 'stair {"start": [0, 0], "width": 0}'),
    ("tread_negative", 'stair {"start": [0, 0], "tread": -280}'),
    ("top_below_base", 'stair {"start": [0, 0], "top_level": "Level 1"}'),
    ("railings_not_a_flag", 'stair {"start": [0, 0], "railings": "both"}'),
]


@_cases(STAIR_REFUSALS)
def test_stair_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that builds a stair of one riser or more than 200, with a landing leaving a run of fewer than
    two risers, after part of a riser, turning other than square or back, or with no width or tread, or that words those
    refusals differently."""
    golden.check_run(_script(workdir, run, [line]), f"stair_refusal_{name}.txt")


def test_ramps_climb_at_their_slope_with_landings(run, workdir, golden):
    """CATCHES: a rewrite whose ramp is another length for its rise and slope (8.33 % by default), lays its runs and
    landings out elsewhere, takes another default width, or makes no railings with `railings`."""
    r = _script(workdir, run, [
        BOX,
        'ramp {"start": [-4000, -6000], "angle": 0, "height": 600, "slope": 8.333333333333334, "landings": [{"at": 300, "turn": 180}]}',
        'ramp {"start": [10000, 0], "end": [10000, 1000], "height": 900, "landings": [{"at": 300, "turn": 90}, {"at": 600, "turn": -90}], '
        '"width": 1500}',
        'ramp {"start": [20000, 0], "slope": 50, "level": "Level 1"}',
        'ramp {"start": [-5000, -5000], "height": 300, "railings": true}',
        'elements {"category": "ramp"}',
        'elements {"category": "railing"}',
        'render {"view": "Level 1", "path": "plan.svg"}',
        'undo',
    ], "--cmd", 'elements {"category": "railing"}')
    golden.check_run(r, "ramps.txt")
    golden.check((workdir / "plan.svg").read_text(), "ramps.svg")


RAMP_REFUSALS = [
    ("slope_zero", 'ramp {"start": [0, 0], "slope": 0}'),
    ("slope_too_steep", 'ramp {"start": [0, 0], "slope": 60}'),
    ("landing_at_the_top", 'ramp {"start": [0, 0], "height": 600, "landings": [{"at": 600, "turn": 0}]}'),
    ("landing_at_the_foot", 'ramp {"start": [0, 0], "height": 600, "landings": [{"at": 0, "turn": 0}]}'),
    ("landings_going_down", 'ramp {"start": [0, 0], "height": 900, "landings": [{"at": 600}, {"at": 300}]}'),
    ("landing_turn_30", 'ramp {"start": [0, 0], "height": 900, "landings": [{"at": 300, "turn": 30}]}'),
    ("too_many_landings", 'ramp {"start": [0, 0], "landings": [' + ", ".join('{"at": %d}' % (i + 1) for i in range(101)) + "]}"),
    ("no_start", 'ramp {"angle": 90}'),
    ("width_negative", 'ramp {"start": [0, 0], "width": -1}'),
    ("top_below_base", 'ramp {"start": [0, 0], "top_level": "Level 1"}'),
    ("end_on_start", 'ramp {"start": [0, 0], "end": [0, 0.5]}'),
]


@_cases(RAMP_REFUSALS)
def test_ramp_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that builds a ramp flatter than 1 % or steeper than 50 %, with a landing at or past its top,
    at its foot or going down, turning at an angle, or that words those refusals differently."""
    golden.check_run(_script(workdir, run, [line]), f"ramp_refusal_{name}.txt")


def test_railings_run_along_a_host_or_a_path(run, workdir, golden):
    """CATCHES: a rewrite whose railing on a stair isn't 50 mm in from its edges (left going up is west going north),
    follows only one side when not asked, doesn't climb with its host round a landing, or along a path stands at
    another height or with another type."""
    r = _script(workdir, run, [
        BOX,
        'stair {"start": [1000, 1000], "end": [1000, 2000]}',
        'railing {"host": 100006}',
        'stair {"start": [4000, 1000], "angle": 90, "landings": [{"at": 8, "turn": -90}]}',
        'railing {"host": 100009, "side": "right"}',
        'ramp {"start": [10000, 0], "height": 600, "landings": [{"at": 300, "turn": 180}]}',
        'railing {"host": 100011, "side": "left"}',
        'railing {"path": [[0, 7000], [4000, 7000], [4000, 9000]], "level": "Level 2", "base_offset": 150}',
        'type {"category": "railing", "name": "Glass - 1100mm", "height": 1100, "spacing": 0}',
        'railing {"path": [[0, 10000], [3000, 10000]], "type": "Glass - 1100mm"}',
        'elements {"category": "railing"}',
        'render {"view": "Level 1", "path": "plan.svg"}',
    ])
    golden.check_run(r, "railings.txt")
    golden.check((workdir / "plan.svg").read_text(), "railings.svg")


RAILING_REFUSALS = [
    ("path_one_point", 'railing {"path": [[0, 0]]}'),
    ("no_path_no_host", 'railing {}'),
    ("path_of_no_length", 'railing {"path": [[0, 0], [0, 0]]}'),
    ("host_a_wall", 'railing {"host": 100002}'),
    ("host_missing", 'railing {"host": 999000}'),
    ("side_middle", 'railing {"host": 100003, "side": "middle"}'),
    ("unknown_type", 'railing {"path": [[0, 0], [1000, 0]], "type": "Rope"}'),
    ("too_many_balusters", 'type {"category": "railing", "name": "Close", "height": 1000, "spacing": 50}\n'
                           'railing {"path": [[0, 0], [900000000, 0]], "type": "Close"}'),
    ("spacing_too_close", 'type {"category": "railing", "name": "Dense", "height": 1000, "spacing": 5}'),
    ("moved_on_its_own", 'railing {"host": 100003}\nmove {"ids": [100004], "by": [100, 0]}'),
    ("host_without_a_side", 'railing {"host": 100003, "side": "left"}\nmodify {"id": 100004, "side": null}'),
    ("host_deleted", 'railing {"path": [[0, 0], [1000, 0]]}\nmodify {"id": 100004, "host": 100002, "side": "left"}'),
]


@_cases(RAILING_REFUSALS)
def test_railing_refusals(run, workdir, golden, name, line):
    """CATCHES: a rewrite that runs a railing along a path of one point or no length, on a host that is no stair or
    ramp, on a side that is neither left nor right, with balusters closer than 50 mm or more than the most, or moves a
    hosted railing apart from its host, or that words those refusals differently."""
    setup = ['wall {"points": [[0, -2000], [4000, -2000]]}', 'stair {"start": [1000, 1000], "end": [1000, 2000]}']
    golden.check_run(_script(workdir, run, [*setup, line]), f"railing_refusal_{name}.txt")
