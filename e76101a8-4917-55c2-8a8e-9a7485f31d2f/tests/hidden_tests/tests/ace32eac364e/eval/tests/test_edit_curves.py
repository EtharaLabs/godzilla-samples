"""Editing detail lines of every shape: split, join_polyline, explode, fillet, corner, trim_extend, offset, vertex,
convert_spline, and moving, turning and mirroring curves."""

import pytest
from conftest import normalize

# Ids: Level 1 is 100000, Level 2 100001, the first element made 100002, then up by one.


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


LINES = 'elements {"category": "line"}'

CASES = {
    # split: a line in two, a spline by control points exactly, one through points, a closed circle opened then cut.
    "split": (
        [
            'detail_line {"start": [0, 0], "end": [4000, 0]}',
            'detail_line {"control": [[0, 0], [1000, 2000], [2500, -1000], [4000, 1500], [5000, 0]], "style": "Wide Lines"}',
            'detail_line {"fit": [[0, 0], [1500, 1200], [3000, -800], [4200, 900], [6000, 0]]}',
            'detail_line {"centre": [0, 0], "radius": 1000}',
            'detail_line {"centre": [0, 0], "radii": [2000, 800], "angle": 30}',
            'detail_line {"points": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], "closed": true}',
        ],
        [
            ['split {"id": 100002, "at": [1000, 30]}', LINES],
            ['SL {"id": 100003, "at": [2500, 300]}', LINES],
            ['split {"id": 100004, "at": [2200, 200]}', LINES],
            ['split {"id": 100005, "at": [0, 1000]}', 'split {"id": 100005, "at": [0, -1000]}', LINES],
            ['split {"id": 100006, "at": [1700, 1000]}', LINES],
            ['split {"id": 100007, "at": [500, 0]}', LINES],
            ['split {"id": 100002, "at": [9000, 9000]}'],
            ['split {"id": 100002, "at": [0, 0]}'],
            ['split {"id": 100002}'],
            ['split {"at": [0, 0]}'],
            ['split {"id": 100000, "at": [0, 0]}'],
        ],
    ),
    # join_polyline and explode, with the reasons a join is refused.
    "join_and_explode": (
        [
            'detail_line {"start": [0, 0], "end": [1000, 0], "style": "Medium Lines"}',
            'detail_line {"start": [1000, 1000], "end": [1000, 0]}',
            'detail_line {"start": [1000, 1000], "end": [0, 1000], "arc": 90}',
            'detail_line {"start": [5000, 0], "end": [6000, 0]}',
            'detail_line {"centre": [0, 0], "radius": 300}',
            'detail_line {"start": [0, 1000], "end": [0, 0]}',
            'section {"start": [-1000, 2000], "end": [3000, 2000], "name": "S"}',
            'detail_line {"view": "S", "start": [1000, 0], "end": [1000, 500]}',
        ],
        [
            ['join_polyline {"ids": [100002, 100003, 100004]}', LINES, 'undo'],
            ['PJ {"ids": [100002, 100003, 100004, 100007]}', LINES],
            ['join_polyline {"ids": [100002, 100003, 100004]}', 'explode {"id": 100002}', LINES],
            ['join_polyline {"ids": [100002, 100005]}'],
            ['join_polyline {"ids": [100002, 100006]}'],
            ['join_polyline {"ids": [100002]}'],
            ['join_polyline {"ids": [100002, 100009]}'],
            ['join_polyline {"ids": [100002, 100000]}'],
            ['explode {"id": 100005}'],
            ['EX {"id": 100006}'],
            ['explode {"id": 100000}'],
            ['explode {"id": 999}'],
            ['explode {}'],
        ],
    ),
    # A dimension measuring a line that is joined in loses it, and goes when left with fewer than two references.
    "join_takes_a_dimension_along": (
        [
            'detail_line {"start": [0, 0], "end": [1000, 0]}',
            'detail_line {"start": [1000, 0], "end": [2000, 0]}',
            'detail_line {"start": [0, 3000], "end": [2000, 3000]}',
            'dimension {"refs": [{"id": 100003}, {"id": 100004}], "at": [1000, 1500]}',
        ],
        [
            ['join_polyline {"ids": [100002, 100003]}', 'elements {}', 'undo', 'elements {"category": "dimension"}'],
        ],
    ),
    # A dimension of three references keeps the two that stay.
    "join_keeps_a_dimension_of_three": (
        [
            'detail_line {"start": [0, 0], "end": [0, 1000]}',
            'detail_line {"start": [0, 1000], "end": [0, 2000]}',
            'detail_line {"start": [2000, 0], "end": [2000, 2000]}',
            'detail_line {"start": [4000, 0], "end": [4000, 2000]}',
            'dimension {"refs": [{"id": 100003}, {"id": 100004}, {"id": 100005}], "at": [1000, 3000]}',
        ],
        [
            ['join_polyline {"ids": [100002, 100003]}', 'elements {"category": "dimension"}'],
        ],
    ),
    # fillet two straight detail lines, and every way it is refused.
    "fillet_lines": (
        [
            'detail_line {"start": [-3000, 0], "end": [-100, 0], "style": "Wide Lines"}',
            'detail_line {"start": [0, 3000], "end": [0, 200]}',
            'detail_line {"centre": [0, 5000], "radius": 800}',
            'detail_line {"control": [[0, 8000], [500, 9000], [1000, 8000]]}',
            'detail_line {"start": [0, -500], "end": [3000, -500]}',
            'section {"start": [-1000, 2000], "end": [3000, 2000], "name": "S"}',
            'detail_line {"view": "S", "start": [0, 500], "end": [2000, 500]}',
        ],
        [
            ['fillet {"ids": [100002, 100003], "radius": 1000}', LINES, 'undo'],
            ['FL {"ids": [100002, 100003], "radius": 99999}'],
            ['fillet {"ids": [100002, 100003]}'],
            ['fillet {"ids": [100002, 100003], "radius": 0}'],
            ['fillet {"ids": [100002, 100003], "radius": -5}'],
            ['fillet {"ids": [100004, 100002], "radius": 100}'],
            ['fillet {"ids": [100002, 100005], "radius": 100}'],
            ['fillet {"ids": [100002], "radius": 100}'],
            ['fillet {"ids": [100002, 100006], "radius": 100}'],
            ['fillet {"ids": [100002, 100008], "radius": 100}'],
            ['fillet {"ids": [100002, 100000], "radius": 100}'],
        ],
    ),
    # corner on detail lines (lines and arcs) and trim_extend to a wall, a grid and a line, one view at a time.
    "corner_and_trim_extend": (
        [
            'detail_line {"start": [0, 0], "end": [800, 0]}',
            'detail_line {"start": [1000, 200], "end": [1000, 1000]}',
            'wall {"points": [[0, 3000], [5000, 3000]]}',
            'detail_line {"start": [2000, 1500], "end": [2000, 2500]}',
            'detail_line {"start": [3000, 4000], "end": [3000, 2000], "style": "Wide Lines"}',
            'grid {"start": [7000, -1000], "end": [7000, 9000]}',
            'section {"start": [-1000, 6000], "end": [3000, 6000], "name": "S"}',
            'detail_line {"view": "S", "start": [0, 500], "end": [2000, 500]}',
            'detail_line {"view": "S", "start": [3000, 0], "end": [3000, 3000]}',
            'detail_line {"start": [0, 10000], "end": [0, 12000], "arc": 90}',
            'detail_line {"start": [-3000, 11000], "end": [-2000, 11000]}',
            'detail_line {"start": [0, -2000], "end": [1000, -2000]}',
        ],
        [
            ['TR {"ids": [100002, 100003], "keep": [[100, 0], [1000, 900]]}', LINES],
            ['corner {"ids": [100002, 100003]}', LINES],
            ['trim_extend {"boundary": 100004, "ids": [100005, 100006], "keep": [[2000, 1600], [3000, 2100]]}', LINES],
            ['trim_extend {"boundary": 100007, "ids": [100002, 100013], "keep": [[100, 0], [500, -2000]]}', LINES],
            ['trim_extend {"boundary": 100010, "ids": [100009], "keep": [[100, 500]]}', LINES],
            ['corner {"ids": [100011, 100012], "keep": [[700, 11000], [-2500, 11000]]}', LINES],
            ['trim_extend {"boundary": 100004, "ids": [100009], "keep": [[100, 500]]}'],
            ['trim_extend {"boundary": 100010, "ids": [100002], "keep": [[100, 0]]}'],
            ['corner {"ids": [100002, 100009]}'],
            ['corner {"ids": [100002, 100013]}'],
            ['corner {"ids": [100002, 100003], "keep": "nonsense"}'],
            ['corner {"ids": [100002, 100003], "keep": [[0, 0], [1, 1], [2, 2]]}'],
            ['trim_extend {"boundary": 100004, "ids": [100005], "keep": []}'],
            ['trim_extend {"ids": [100005], "keep": [[0, 0]]}'],
            ['trim_extend {"boundary": 100004, "ids": [100004], "keep": [[0, 0]]}'],
            ['trim_extend {"boundary": 100004, "ids": [100013], "keep": [[500, -2000]]}'],
            ['trim_extend {"boundary": 100000, "ids": [100005], "keep": [[2000, 1600]]}'],
            ['trim_extend {"boundary": 100004, "ids": [100005], "keep": [[2000, 3500]]}'],
        ],
    ),
    # offset: an arc round its centre, a line moved, an ellipse as a spline through points, a polyline's corners.
    "offset": (
        [
            'detail_line {"start": [0, 0], "end": [2000, 0], "arc": -180}',
            'detail_line {"start": [0, 5000], "end": [1000, 5000]}',
            'detail_line {"centre": [0, 0], "radii": [500, 300]}',
            'detail_line {"points": [[0, 8000], [2000, 8000], [2000, 10000]], "arcs": [0, 0]}',
            'detail_line {"centre": [5000, 5000], "radius": 1000}',
        ],
        [
            ['offset {"id": 100002, "distance": 200, "toward": [1000, 0]}', LINES],
            ['OF {"id": 100003, "distance": 300, "toward": [500, 4000], "copy": false}', LINES],
            ['offset {"id": 100004, "distance": 10, "toward": [0, 0]}', LINES],
            ['offset {"id": 100005, "distance": 250, "toward": [1000, 9000]}', LINES],
            ['offset {"id": 100006, "distance": 500, "toward": [9000, 5000], "copy": true}', LINES],
            ['offset {"id": 100004, "distance": 400, "toward": [0, 0]}'],
            ['offset {"id": 100006, "distance": 1500, "toward": [5000, 5000]}'],
            ['offset {"id": 100002, "distance": 0, "toward": [0, 0]}'],
            ['offset {"id": 100002, "toward": [0, 0]}'],
            ['offset {"id": 100002, "distance": 10}'],
            ['offset {"distance": 10, "toward": [0, 0]}'],
            ['offset {"id": 100000, "distance": 10, "toward": [0, 0]}'],
        ],
    ),
    # vertex added and deleted, splines converted both ways, and what they refuse.
    "vertex_and_convert_spline": (
        [
            'detail_line {"points": [[0, 0], [2000, 0], [2000, 2000]]}',
            'detail_line {"fit": [[0, 0], [1000, 800], [2500, -300], [4000, 500]]}',
            'detail_line {"centre": [0, 0], "radius": 500}',
            'detail_line {"control": [[0, 5000], [1000, 7000], [3000, 7000], [4000, 5000]]}',
            'detail_line {"start": [0, -1000], "end": [1000, -1000]}',
            'detail_line {"points": [[0, 6000], [3000, 6000], [3000, 9000]]}',
        ],
        [
            ['vertex {"id": 100002, "at": [1000, 20]}', 'vertex {"id": 100002, "at": [2000, 0], "delete": true}', LINES],
            ['convert_spline {"id": 100003}', LINES, 'convert_spline {"id": 100003}', LINES],
            ['vertex {"id": 100005, "at": [2000, 6500]}', LINES],
            ['vertex {"id": 100005, "at": [1000, 7000], "delete": true}', LINES],
            ['vertex {"id": 100003, "at": [2500, -300], "delete": true}', LINES],
            ['vertex {"id": 100007, "at": [1000, 6000]}', LINES],
            ['vertex {"id": 100004, "at": [500, 0]}'],
            ['vertex {"id": 100004, "at": [500, 0], "delete": true}'],
            ['vertex {"id": 100006, "at": [500, -1000]}'],
            ['vertex {"id": 100002, "at": [1500, 5000]}'],
            ['vertex {"id": 100002, "at": [9000, 9000], "delete": true}'],
            ['vertex {"id": 100002, "at": [0, 0], "delete": true}', 'vertex {"id": 100002, "at": [2000, 0], "delete": true}'],
            ['vertex {"id": 100002}'],
            ['vertex {"at": [0, 0]}'],
            ['vertex {"id": 100000, "at": [0, 0]}'],
            ['convert_spline {"id": 100004}'],
            ['convert_spline {"id": 100006}'],
            ['convert_spline {}'],
        ],
    ),
    # Curves moved, copied, turned and mirrored keep their shape (an ellipse's span, a spline's tangent).
    "move_rotate_mirror_curves": (
        [
            'detail_line {"centre": [1000, 0], "radii": [2000, 800], "angle": 30, "span": [10, 200]}',
            'detail_line {"fit": [[0, 0], [1000, 1500], [3000, -500]], "start_tangent": [0, 1]}',
            'detail_line {"start": [0, 0], "end": [2000, 0], "through": [1000, 1000]}',
            'detail_line {"control": [[0, 0], [1000, 2000], [3000, 2000], [4000, 0]], "knots": [0, 0, 0, 0, 1, 1, 1, 1]}',
        ],
        [
            ['mirror {"ids": [100002, 100003, 100004, 100005], "axis": [[0, -5000], [0, 5000]], "copy": false}', LINES],
            ['rotate {"ids": [100002, 100003, 100004, 100005], "angle": 90, "about": [0, 0]}', LINES],
            ['move {"ids": [100002, 100003], "by": [500, -250]}', LINES],
            ['copy {"ids": [100004, 100005], "by": [0, 3000]}', LINES],
            ['rotate {"ids": [100004], "angle": 45, "about": [1000, 0], "copy": true}', LINES],
            ['mirror {"ids": [100004], "axis": [[0, 0], [1000, 1000]], "copy": true}', LINES],
        ],
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_curve_editing(run, workdir, golden, case):
    """CATCHES: a rewrite whose curve editing (split, join, explode, fillet, corner, trim_extend, offset, vertex,
    convert_spline, and moving, turning or mirroring a curve) gives different geometry, ids, replies or undo-step
    names, or that refuses (or accepts) a different set of inputs, words a refusal differently, or changes the model
    when it refuses."""
    setup, probes = CASES[case]
    golden.check(session(run, workdir, setup, probes), f"{case}.txt")


def test_fillet_two_walls_keeps_their_doors_where_they_stand(run, workdir, golden):
    """CATCHES: a rewrite whose wall fillet makes the arc wall of another type, size or turn, moves the doors of a
    trimmed wall in plan instead of only their offset, or cuts a door away instead of refusing."""
    setup = [
        'wall {"points": [[0, 0], [-6000, 0]]}',
        'wall {"points": [[0, 0], [0, 6000]], "type": "Interior - 100mm"}',
        'door {"wall": 100002, "offset": 3000}',
        'door {"wall": 100003, "offset": 500}',
        'wall {"points": [[10000, 0], [14000, 0]], "arc": 90}',
        'wall {"points": [[20000, 0], [24000, 0]]}',
        'wall {"points": [[20000, 1000], [24000, 1000]]}',
    ]
    probes = [
        ['fillet {"ids": [100002, 100003], "radius": 1500}'],
        ['delete {"ids": [100005]}', 'fillet {"ids": [100002, 100003], "radius": 1500}',
         'elements {"category": "wall"}', 'elements {"category": "door"}', 'undo'],
        ['fillet {"ids": [100002, 100006], "radius": 100}'],
        ['fillet {"ids": [100007, 100008], "radius": 100}'],
        ['fillet {"ids": [100002, 100003], "radius": 1e300}'],
        ['fillet {"ids": [100002, 100003]}'],
        ['fillet {"ids": [100002, 100003, 100007], "radius": 100}'],
    ]
    golden.check(session(run, workdir, setup, probes), "fillet_walls.txt")


SHAPES = [
    # Every shape a detail line takes, read back as `elements` shows it.
    'detail_line {"start": [0, 0], "end": [1000, 0]}',
    'detail_line {"start": [0, 0], "end": [2000, 0], "arc": 90}',
    'detail_line {"start": [0, 0], "end": [2000, 0], "through": [1000, 1000]}',
    'detail_line {"points": [[0, 0], [1000, 0], [1000, 1000]], "arcs": [0, 90], "closed": false}',
    'detail_line {"points": [[0, 0], [1000, 0], [1000, 1000]], "closed": true}',
    'detail_line {"points": [[0, 0], [1000, 0]], "arcs": [180, 180], "closed": true}',
    'detail_line {"centre": [0, 0], "radius": 1500}',
    'detail_line {"centre": [0, 0], "radii": [2000, 800], "angle": 30}',
    'detail_line {"centre": [0, 0], "radii": [2000, 800], "span": [0, 180]}',
    'detail_line {"control": [[0, 0], [1000, 2000], [3000, 2000], [4000, 0]]}',
    'detail_line {"control": [[0, 0], [1000, 2000], [2000, 0], [3000, 2000], [4000, 0]], "knots": [0, 0, 0, 1, 2, 3, 3, 3]}',
    'detail_line {"fit": [[0, 0], [1000, 1500], [3000, -500], [4000, 0]], "start_tangent": [1, 0], "end_tangent": [0, -1]}',
    'detail_line {"start": [0, 0], "end": [1000.0000000000001, 0.0000000000004], "arc": 89.99999999999999}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "style": "Wide Lines", "level": "Level 2"}',
]

REFUSED = [
    'detail_line {"centre": [0, 0], "radius": 0.5}',
    'detail_line {"centre": [0, 0]}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "radius": 500}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "through": [500, 500], "arc": 90}',
    'detail_line {"control": [[0, 0], [1000, 0]], "knots": [0, 1]}',
    'detail_line {"control": [[0, 0], [1000, 0], [2000, 0]], "knots": [0, 0, 1, 0, 1]}',
    'detail_line {"control": [[0, 0], [1000, 0], [2000, 0]], "knots": [0, 1, 1, 1, 1]}',
    'detail_line {"control": [[0, 0], [1000, 0], [2000, 0], [3000, 0]], "knots": [0, 0, 1, 1, 1, 2]}',
    'detail_line {"control": [[0, 0]]}',
    'detail_line {"control": [[0, 0], [1e12, 0]]}',
    'detail_line {"fit": [[0, 0], [0, 0]]}',
    'detail_line {"fit": [[0, 0]]}',
    'detail_line {"fit": [[0, 0], [100, 0]], "start_tangent": [0, 0]}',
    'detail_line {"fit": [[0, 0], [1e12, 0]]}',
    'detail_line {"points": [[0, 0], [1000, 0]], "arcs": [10, 10]}',
    'detail_line {"points": [[0, 0]]}',
    'detail_line {"points": [[0, 0], [1000, 0]], "closed": true}',
    'detail_line {"points": [[0, 0], [0, 0], [1000, 0]]}',
    'detail_line {"points": [[0, 0], [1e12, 0]]}',
    'detail_line {"points": [[0, 0], [1000, 0]], "arcs": [360]}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "arc": 0.000001}',
    'detail_line {"points": [[0, 0], [100000000, 0]], "arcs": [359]}',
    'detail_line {"centre": [0, 0], "radius": 1e300}',
    'detail_line {"centre": [999999990, 0], "radius": 100}',
    'detail_line {"centre": [1e12, 0], "radius": 100}',
    'detail_line {"centre": [0, 0], "radii": [0, 800]}',
    'detail_line {"centre": [0, 0], "radii": [2000, 800], "angle": 1e9}',
    'detail_line {"centre": [0, 0], "radii": [2000, 800], "span": [10, 10]}',
    'detail_line {"centre": [0, 0], "radii": [2000, 800], "span": [10, 1e9]}',
    'detail_line {"centre": [999999000, 0], "radii": [2000, 800]}',
    'detail_line {"centre": [1e12, 0], "radii": [2000, 800]}',
    'detail_line {"centre": [0, 0], "radius": 10, "radii": [1, 1]}',
    'detail_line {"control": [[0, 0], [1, 1]], "fit": [[0, 0], [1, 1]]}',
    'detail_line {"points": [[0, 0], [1, 1]], "radius": 3}',
    'detail_line {"fit": [[0, 0], [1, 1]], "knots": [0, 1]}',
    'detail_line {"start": [0, 0]}',
    'detail_line {}',
    'detail_line {"start": "here", "end": [1, 1]}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "colour": 1}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "style": "Nope"}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "view": "Nowhere"}',
]


def test_detail_line_shapes_and_refusals(run, workdir, golden):
    """CATCHES: a rewrite whose detail lines of each shape (line, arc by turn or through a point, polyline with arcs,
    open or closed, circle, ellipse whole or partial, spline by control points with or without knots, spline through
    points with tangents) are held or shown differently (rounding to the micron and the billionth of a degree
    included), or that accepts a shape the reference refuses, or refuses with other words."""
    (workdir / "shapes.txt").write_text("\n".join(SHAPES) + '\nelements {"category": "line"}\n')
    out = _block("shapes", run(["run", "--script", "shapes.txt"]))
    for cmd in REFUSED:
        out += _block(cmd, run(["run", "--cmd", cmd]))
    golden.check(out, "detail_line_shapes.txt")


MORE = {
    # A polyline with arcs, open and closed, offset to either side; two arcs cornered; an arc trimmed to a line.
    "arcs_offset_cornered_and_trimmed": (
        [
            'detail_line {"points": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]], "arcs": [0, 90, 0], "closed": false}',
            'detail_line {"points": [[0, 5000], [3000, 5000], [3000, 8000], [0, 8000]], "arcs": [0, -60, 0, 0], "closed": true}',
            'detail_line {"start": [10000, 0], "end": [14000, 0], "arc": 90}',
            'detail_line {"start": [12000, -500], "end": [16000, -500], "arc": -90}',
            'detail_line {"start": [10000, 3000], "end": [14000, 3000]}',
            'detail_line {"start": [20000, 0], "end": [22000, 0], "arc": 180}',
            'detail_line {"start": [21000, -2000], "end": [21000, 3000]}',
        ],
        [
            ['offset {"id": 100002, "distance": 200, "toward": [1000, 1000]}', 'offset {"id": 100002, "distance": 200, "toward": [1000, -1000]}', LINES],
            ['offset {"id": 100003, "distance": 300, "toward": [1500, 6500]}', 'offset {"id": 100003, "distance": 300, "toward": [-1000, 6500]}', LINES],
            ['offset {"id": 100003, "distance": 1600, "toward": [1500, 6500]}'],
            ['corner {"ids": [100004, 100005], "keep": [[10500, -300], [15500, -300]]}', LINES],
            ['corner {"ids": [100004, 100006]}', LINES],
            ['trim_extend {"boundary": 100008, "ids": [100007], "keep": [[20100, 300]]}', LINES],
            ['trim_extend {"boundary": 100008, "ids": [100007], "keep": [[21900, 300]]}', LINES],
            ['trim_extend {"boundary": 100007, "ids": [100008], "keep": [[21000, 2500]]}', LINES],
            ['trim_extend {"boundary": 100002, "ids": [100006], "keep": [[12000, 3000]]}'],
            ['offset {"id": 100004, "distance": 500, "toward": [12000, 0]}', 'offset {"id": 100004, "distance": 500, "toward": [12000, 5000]}', LINES],
        ],
    ),
    # Splitting, joining and taking apart polylines with arcs, closed ones and reversed chains; vertices of each kind.
    "polylines_split_joined_and_edited": (
        [
            'detail_line {"points": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]], "arcs": [0, 90, 0, 0], "closed": true}',
            'detail_line {"start": [5000, 0], "end": [6000, 0]}',
            'detail_line {"start": [7000, 0], "end": [6000, 0]}',
            'detail_line {"start": [5000, 1000], "end": [5000, 0]}',
            'detail_line {"centre": [0, 10000], "radii": [2000, 800], "span": [0, 270]}',
            'detail_line {"control": [[0, 15000], [1000, 17000], [2000, 15000], [3000, 17000], [4000, 15000]], "knots": [0, 0, 0, 1, 2, 3, 3, 3]}',
            'detail_line {"fit": [[0, 20000], [1000, 21000], [2000, 20000], [3000, 21000]]}',
        ],
        [
            ['split {"id": 100002, "at": [1000, 0]}', 'split {"id": 100002, "at": [2000, 2000]}', LINES],
            ['explode {"id": 100002}', LINES],
            ['join_polyline {"ids": [100004, 100003, 100005]}', LINES, 'explode {"id": 100004}', LINES],
            ['join_polyline {"ids": [100003, 100005, 100004]}', LINES],
            ['split {"id": 100006, "at": [-2000, 10000]}', LINES],
            ['split {"id": 100007, "at": [2000, 15500]}', 'convert_spline {"id": 100007}', LINES],
            ['vertex {"id": 100002, "at": [1000, 2000]}', 'vertex {"id": 100002, "at": [0, 0], "delete": true}', LINES],
            ['vertex {"id": 100007, "at": [1000, 16300]}', 'vertex {"id": 100007, "at": [2000, 15000], "delete": true}', LINES],
            ['vertex {"id": 100008, "at": [1500, 20500]}', 'vertex {"id": 100008, "at": [3000, 21000], "delete": true}', LINES],
            ['vertex {"id": 100006, "at": [2000, 10000]}'],
            ['vertex {"id": 100003, "at": [5500, 0], "delete": true}'],
            ['mirror {"ids": [100002, 100006, 100007], "axis": [[0, 0], [0, 1000]], "copy": true}', LINES],
        ],
    ),
}


@pytest.mark.parametrize("case", sorted(MORE))
def test_more_curve_editing(run, workdir, golden, case):
    """CATCHES: a rewrite that offsets, corners, trims, splits, joins, explodes or edits the vertices of arcs, closed
    polylines, partial ellipses and splines over knots differently from the reference, or refuses (or accepts) other
    cases."""
    setup, probes = MORE[case]
    golden.check(session(run, workdir, setup, probes), f"{case}.txt")
