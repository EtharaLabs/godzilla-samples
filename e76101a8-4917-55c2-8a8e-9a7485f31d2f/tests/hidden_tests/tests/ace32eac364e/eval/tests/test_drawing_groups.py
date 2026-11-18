"""Detail groups and repeating details: Create Group, placing a group again (turned, mirrored), repeating it along a
line, Ungroup and group types; their replies, their errors, and how a plan draws them (the SVG a plan saves to)."""

import json
import re
from concurrent.futures import ThreadPoolExecutor

from conftest import normalize


def _script(run, workdir, lines, *extra, name="s.txt"):
    """`run --script` over `lines` (one `id {json}` each) written to `name` in the working directory."""
    (workdir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run(["run", "--script", name, *extra])


def _outcome(r):
    return (f"exit: {r.returncode}\n--- stdout\n" + normalize(r.stdout.decode("utf-8", "replace"))
            + "--- stderr\n" + normalize(r.stderr.decode("utf-8", "replace")))


def _sweep(run, workdir, setup, cases):
    """Each case run as the last line of a script after `setup`, each in a run of its own (a few at a time, each with a
    script of its own); their outcomes in one text, in the order of the cases."""
    def one(i):
        r = _script(run, workdir, [*setup, cases[i]], name=f"case{i}.txt")
        return f"$ {cases[i][:200]}\n{_outcome(r)}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        return "\n".join(pool.map(one, range(len(cases))))


def _rounded(text):
    """`text` with each number of ten or more decimals (or an exponent) rounded to six: a turn's sine and cosine may
    differ in their last bit from one machine to another, and six decimals don't."""
    return re.sub(r"-?\d+\.\d+e-?\d+|-?\d+\.\d{10,}", lambda m: f"{float(m.group()) + 0.0:.6f}", text)


def _cmd(name, params):
    return f"{name} {json.dumps(params)}"


# An angle of two detail lines (100002, 100003), a triangle region (100004) and a note (100005) in Level 1's plan, the
# note lettered in a font the program carries.
MEMBERS = [
    'text_type {"name": "2.5mm", "font": "BIMCraft Lettering"}',
    'detail_line {"start": [0, 0], "end": [1000, 0], "style": "Wide Lines"}',
    'detail_line {"start": [0, 0], "end": [0, 600]}',
    _cmd("filled_region", {"sketch": [[[100, 100], [500, 100]], [[500, 100], [100, 400]], [[400 - 300, 400], [100, 100]]],
                           "type": "Crosshatch"}),
    'text {"text": "L1", "at": [600, 500]}',
]

GROUPED = [
    *MEMBERS,
    _cmd("create_group", {"ids": [100002, 100003, 100004, 100005], "name": "Angle"}),
    _cmd("detail_group", {"type": "Angle", "at": [3000, 0], "angle": 90}),
    _cmd("detail_group", {"type": "Angle", "at": [5000, 0], "mirrored": True}),
    _cmd("detail_group", {"type": "Angle", "at": [7000, 0], "angle": 45, "mirrored": True, "view": "Level 1"}),
    'detail_line {"start": [0, -100], "end": [0, 100], "style": "Medium Lines"}',
    _cmd("create_group", {"ids": [100010]}),
    _cmd("repeating_detail", {"type": "Group 1", "start": [0, -2000], "end": [4000, -2000], "spacing": 500}),
    _cmd("repeating_detail", {"type": "Group 1", "start": [5000, -3000], "end": [7000, -1000], "spacing": 700,
                              "mirrored": True}),
]


def test_groups_are_made_placed_and_repeated(run, workdir, golden):
    """CATCHES: a rewrite whose Create Group doesn't take its members out of the view and put one group at the middle
    of them, names a new group another way than Group 1, 2…, counts a repeating detail's places differently, or whose
    `group_type` listing (members, placed) or `elements` of groups differ."""
    r = _script(run, workdir, [
        *GROUPED,
        "group_type {}",
        'elements {"category": "line"}',
        'elements {"category": "detailgroup"}',
        'elements {"category": "repeatingdetail"}',
    ])
    golden.check_run(r, "made.txt")


def test_groups_drawn_turned_mirrored_and_repeated(run, workdir, golden):
    """CATCHES: a rewrite that draws a group's members elsewhere, doesn't turn them by its angle or mirror them across
    their x axis first, mirrors a note's lettering, draws regions over lines, or places a repeating detail's copies at
    other spacings or turns."""
    r = _script(run, workdir, GROUPED, "--save", "groups.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "groups.svg").read_text(), "groups.svg")


def test_ungroup_gives_back_the_members_where_the_group_drew_them(run, workdir, golden):
    """CATCHES: a rewrite whose Ungroup puts the members back unturned, unmirrored or at the type's origin, keeps the
    group, takes the type away, or gives the members other ids."""
    r = _script(run, workdir, [
        *GROUPED[:8],
        _cmd("ungroup", {"id": 100008}),
        _cmd("ungroup", {"id": 100007}),
        'elements {"category": "line"}',
        'elements {"category": "region"}',
        'elements {"category": "text"}',
        "group_type {}",
    ])
    golden.check(_rounded(_outcome(r)), "ungroup.txt")


def test_group_types_are_renamed_and_deleted(run, workdir, golden):
    """CATCHES: a rewrite whose group type rename doesn't reach the groups and repeating details of it, or that deletes
    a type something is placed of, or keeps one nothing is."""
    r = _script(run, workdir, [
        *GROUPED,
        _cmd("group_type", {"name": "Angle", "rename": "Corner"}),
        _cmd("group_type", {"name": "Group 1", "rename": "Tick"}),
        'elements {"category": "repeatingdetail"}',
        _cmd("delete", {"ids": [100006, 100007, 100008, 100009]}),
        _cmd("group_type", {"name": "Corner", "delete": True}),
        _cmd("group_type", {"name": "Tick"}),
        "group_type {}",
    ])
    golden.check_run(r, "types.txt")


def test_groups_move_rotate_and_mirror_whole(run, workdir, golden):
    """CATCHES: a rewrite whose move, rotate, mirror or copy of a placed group or a repeating detail doesn't carry its
    origin, angle and mirroring (or a repeat's ends) as one."""
    r = _script(run, workdir, [
        *GROUPED,
        _cmd("move", {"ids": [100007], "by": [0, 1000]}),
        _cmd("rotate", {"ids": [100008], "angle": 90, "about": [5000, 0]}),
        _cmd("mirror", {"ids": [100009, 100012], "axis": [[0, -5000], [10000, -5000]]}),
        _cmd("copy", {"ids": [100011], "by": [0, -500]}),
        'elements {"category": "detailgroup"}',
        'elements {"category": "repeatingdetail"}',
    ])
    golden.check_run(r, "transformed.txt")


GROUP_ERRORS = [
    "create_group {}",
    _cmd("create_group", {"ids": []}),
    _cmd("create_group", {"ids": [100002, 100007]}),
    _cmd("create_group", {"ids": [100002, 100008]}),
    _cmd("create_group", {"ids": [100002], "name": "Angle"}),
    _cmd("create_group", {"ids": [999999]}),
    _cmd("create_group", {"ids": [100002], "label": "x"}),
    "detail_group {}",
    _cmd("detail_group", {"type": "Nothing", "at": [0, 0]}),
    _cmd("detail_group", {"type": "Angle"}),
    _cmd("detail_group", {"type": "Angle", "at": [0, 0], "view": "Nowhere"}),
    _cmd("detail_group", {"type": "Angle", "at": [0, 0], "scale": 2}),
    _cmd("repeating_detail", {"type": "Angle", "start": [0, 0], "end": [1000, 0]}),
    _cmd("repeating_detail", {"type": "Angle", "start": [0, 0], "end": [1000, 0], "spacing": 0.5}),
    _cmd("repeating_detail", {"type": "Angle", "start": [0, 0], "end": [100000, 0], "spacing": 10}),
    _cmd("repeating_detail", {"type": "Nothing", "start": [0, 0], "end": [1000, 0], "spacing": 100}),
    _cmd("repeating_detail", {"start": [0, 0], "end": [1000, 0], "spacing": 100}),
    _cmd("ungroup", {"id": 100002}),
    _cmd("ungroup", {}),
    _cmd("group_type", {"name": "Nothing"}),
    _cmd("group_type", {"name": "Angle", "delete": True}),
    _cmd("group_type", {"name": "Angle", "rename": "Other"}),
    _cmd("group_type", {"name": "Angle", "colour": "red"}),
]


def test_group_errors(run, workdir, golden):
    """CATCHES: a rewrite that groups nothing, a wall, elements of two views, under a name taken or with an element
    there isn't; places a group of a type there isn't, without a point or in an unknown view; repeats one without a
    spacing, closer than 1 mm, more than it may, or of no type; ungroups what isn't a group; or renames over or deletes
    a type in use; or that words the refusal differently."""
    setup = [
        'detail_line {"start": [0, 0], "end": [1000, 0]}',
        'detail_line {"start": [0, 500], "end": [1000, 500]}',
        _cmd("create_group", {"ids": [100003], "name": "Angle"}),
        'detail_line {"start": [0, 900], "end": [1000, 900]}',
        _cmd("create_group", {"ids": [100005], "name": "Other"}),
        'wall {"points": [[0, 2000], [3000, 2000]]}',
        'detail_line {"start": [0, 0], "end": [1000, 0], "view": "Level 2"}',
    ]
    golden.check(_sweep(run, workdir, setup, GROUP_ERRORS), "group_errors.txt")


EVERYTHING = [
    _cmd("line_pattern", {"name": "Fence", "segments": [{"dash": 4}, {"space": 1}, "dot", {"space": 1}]}),
    _cmd("line_style", {"name": "Fence Line", "pen": 3, "color": [200, 0, 0], "pattern": "Fence"}),
    _cmd("fill_pattern", {"name": "Planks", "target": "model", "lines": [{"angle": 0, "spacing": 150}]}),
    _cmd("filled_region_type", {"name": "Boards", "foreground": "Planks"}),
    _cmd("text_type", {"name": "Hand", "font": "BIMCraft Lettering"}),
    _cmd("dimension_type", {"name": "Mine", "like": "Diagonal - 2.5mm Arial", "tick": "dot"}),
    'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
    'door {"at": [3000, 0]}',
    _cmd("detail_line", {"start": [0, 1000], "end": [3000, 1000], "style": "Fence Line"}),
    _cmd("detail_line", {"centre": [4000, 2000], "radius": 500, "cloud": 100, "revision": "A"}),
    _cmd("filled_region", {"sketch": [[[500, 2000], [1500, 2000]], [[1500, 2000], [1500, 3000]], [[1500, 3000], [500, 2000]]],
                           "type": "Boards"}),
    _cmd("text", {"text": "Note", "at": [100, 3500], "type": "Hand", "leader": [0, 4000]}),
    _cmd("create_group", {"ids": [100008, 100010], "name": "Pair"}),
    _cmd("detail_group", {"type": "Pair", "at": [8000, 0], "angle": 90}),
    _cmd("repeating_detail", {"type": "Pair", "start": [0, -2000], "end": [6000, -2000], "spacing": 2000}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100006}, {"id": 100003}], "at": [0, -1000], "type": "Mine"}),
    _cmd("dimension_constraint", {"id": 100014, "locked": [0]}),
    _cmd("dimension_text", {"id": 100014, "segment": 1, "suffix": " clear"}),
    'spot {"at": [3000, 0]}',
    "tag {}",
    _cmd("linework", {"id": 100002, "at": [1000, 100], "style": "Fence Line"}),
]

MINE = ["format", "line_patterns", "line_styles", "fill_patterns", "region_types", "text_types", "dimension_types",
        "detail_groups", "elements"]
KINDS = {"line-pattern", "line-style", "fill-pattern", "filled-region-type", "text-type", "dimension-type", "detail-group"}


def test_annotation_round_trips_through_a_project_file(run, workdir, golden):
    """CATCHES: a rewrite that saves line patterns and styles, fill patterns, region and text and dimension types,
    detail groups and their members, detail lines, regions, notes, dimensions with their locks and texts, spots, tags
    and a view's Linework in another shape (names held as library GUIDs, members as parts with ids of their own), or
    that reads them back into anything but the same project."""
    r = _script(run, workdir, EVERYTHING, "--save", "p.bimcraft")
    assert r.returncode == 0, r.stderr.decode()
    saved = json.loads((workdir / "p.bimcraft").read_text())
    part = {k: saved[k] for k in MINE}
    part["library"] = {k: v for k, v in saved["library"].items() if v["kind"] in KINDS}
    golden.check(normalize(json.dumps(part, indent=1)) + "\n", "round_trip.json")
    r = run(["run", "p.bimcraft", "--cmd", "group_type {}", "--cmd", 'elements {"category": "dimension"}',
             "--save", "again.bimcraft"])
    golden.check_run(r, "round_trip_open.txt")
    assert json.loads((workdir / "again.bimcraft").read_text()) == saved
