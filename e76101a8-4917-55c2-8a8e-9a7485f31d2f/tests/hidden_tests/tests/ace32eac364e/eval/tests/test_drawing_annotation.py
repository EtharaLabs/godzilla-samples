"""Annotation in plans: dimensions (kinds, types, text, constraints, typed lengths), text notes and text types, spot
elevations and slopes, and tags: their replies, their errors, and how a plan draws them (the SVG a plan saves to).

Lettering that names Arial is drawn with whatever font the machine has in its place, so every drawing here letters its
notes and dimensions in a font the program carries (IBM Plex Sans or Mono, BIMCraft Lettering)."""

import json
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


def _cmd(name, params):
    return f"{name} {json.dumps(params)}"


# A room of four walls (100002 south, 100003 east, 100004 north, 100005 west), a door in the south wall (100006), a
# window in the north one (100007) and a grid west of it (100008); dimensions lettered in a font the program carries.
ROOM = [
    'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
    'door {"at": [3000, 0]}',
    'window {"at": [3000, 4000]}',
    'grid {"start": [-1000, -2000], "end": [-1000, 6000]}',
    _cmd("dimension_type", {"name": "Diagonal - 2.5mm Arial", "font": "IBM Plex Sans"}),
    _cmd("dimension_type", {"name": "Arrow - 2.5mm Arial", "font": "IBM Plex Sans"}),
]

KINDS = [
    _cmd("dimension", {"refs": [{"id": 100008}, {"id": 100005, "face": "left"}, {"id": 100006},
                                {"id": 100006, "face": "end"}, {"id": 100003, "face": "right"}], "at": [0, -1500]}),
    _cmd("dimension", {"refs": [[0, 2000], [6000, 2000]], "at": [3000, 5500]}),
    _cmd("dimension", {"kind": "linear", "refs": [{"id": 100002, "point": "start"}, {"id": 100003, "point": "end"}],
                       "at": [8000, 2000]}),
    _cmd("dimension", {"kind": "linear", "orient": "horizontal",
                       "refs": [{"endpoint": [5950, 3950]}, {"id": 100004, "point": "end"}], "at": [3000, 6500]}),
    _cmd("dimension", {"kind": "angular", "refs": [{"id": 100002}, {"id": 100003}], "at": [5000, 1000]}),
    _cmd("detail_line", {"centre": [3000, 2000], "radius": 700}),
    _cmd("dimension", {"kind": "radial", "refs": [[3700, 2000]], "at": [4500, 2500]}),
    _cmd("dimension", {"kind": "diameter", "refs": [[3700, 2000]], "at": [4500, 1500]}),
    _cmd("detail_line", {"start": [1000, 1000], "end": [2000, 2000], "arc": 90}),
    _cmd("dimension", {"kind": "arc_length", "refs": [[1707.1, 1292.9]], "at": [1000, 2500]}),
    _cmd("dimension", {"refs": [{"id": 100004, "face": "left"}, {"id": 100004, "face": "right"}], "at": [7000, 4000],
                       "prefix": "~", "suffix": " mm", "above": "WALL", "below": "THICK"}),
]


def test_dimensions_of_every_kind(run, workdir, golden):
    """CATCHES: a rewrite that measures a wall's faces, a door's centre and jamb, a grid, points and endpoints, angles,
    radii, diameters and arc lengths differently, orients a linear dimension the other way, gives a radial one another
    type than the arrow one, or lists dimensions (labels, refs, orient) differently."""
    r = _script(run, workdir, [*ROOM, *KINDS, 'elements {"category": "dimension"}'])
    golden.check_run(r, "kinds.txt")


def test_dimensions_drawn_in_a_plan(run, workdir, golden):
    """CATCHES: a rewrite that draws a dimension's line, ticks (diagonal and arrows), witness lines, numbers, prefix,
    suffix and text above and below in other places or sizes, or draws a radial, diameter, angular or arc length
    dimension differently."""
    r = _script(run, workdir, [*ROOM, *KINDS], "--save", "dims.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "dims.svg").read_text(), "dims.svg")


STYLED = [
    *ROOM,
    _cmd("dimension_type", {"name": "Baseline", "like": "Diagonal - 2.5mm Arial", "string": "baseline",
                            "baseline_spacing": 10, "tick": "dot", "color": "#c00000", "units": "m", "decimals": 2}),
    _cmd("dimension_type", {"name": "Ordinate", "like": "Diagonal - 2.5mm Arial", "string": "ordinate", "tick": "none",
                            "witness": "fixed", "witness_length": 3, "text_size": 3.5, "bold": True}),
    _cmd("dimension_type", {"name": "Open", "like": "Arrow - 2.5mm Arial", "tick": "open_arrow", "tick_size": 3,
                            "line_pen": 2, "tick_pen": 9, "background": "transparent", "read": "up_then_right",
                            "units": "cm", "font": "IBM Plex Mono", "italic": True, "underline": True,
                            "width_factor": 0.8, "text_offset": 2, "line_extension": 3, "witness_gap": 2,
                            "witness_extension": 2}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100006}, {"id": 100003}], "at": [0, -1500], "type": "Baseline"}),
    _cmd("dimension", {"refs": [{"id": 100002}, {"id": 100004}], "at": [-2500, 0], "type": "Ordinate"}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100007}, {"id": 100003}], "at": [0, 5500], "type": "Open"}),
    _cmd("dimension_type", {"name": "Ordinate", "rename": "Running"}),
    _cmd("dimension_type", {"name": "Strokes", "font": "BIMCraft Lettering", "text_size": 3, "radius_symbol": "RAD",
                            "equality_text": "EQUAL", "centre_mark": False, "witness": "fixed"}),
    _cmd("dimension", {"kind": "angular", "refs": [{"id": 100002}, {"id": 100003}], "at": [5000, 1000],
                       "type": "Strokes"}),
    _cmd("dimension", {"refs": [{"id": 100008}, {"id": 100005}, {"id": 100003}], "at": [0, 7000], "type": "Strokes",
                       "equality": True}),
]


def test_dimension_types_shape_labels_and_drawing(run, workdir, golden):
    """CATCHES: a rewrite whose dimension types don't start from `like`, whose baseline and ordinate strings read other
    numbers, whose own units and rounding are ignored, whose rename doesn't reach its dimensions, or that draws dot,
    open-arrow and no ticks, fixed witness lines, pens, colours and transparent text differently."""
    r = _script(run, workdir, [*STYLED, 'elements {"category": "dimension"}'], "--save", "styled.svg")
    golden.check_run(r, "styled.txt")
    golden.check((workdir / "styled.svg").read_text(), "styled.svg")


def test_dimension_labels_follow_the_project_units(run, workdir, golden):
    """CATCHES: a rewrite that labels dimensions in millimetres whatever the project's units, or formats feet and
    inches, metres or centimetres differently."""
    lines = [*ROOM, KINDS[0], KINDS[4], KINDS[5], KINDS[6]]
    for units in ["ft-in", "m", "cm", "in", "ft"]:
        lines += [_cmd("units", {"length": units}), 'elements {"category": "dimension"}']
    r = _script(run, workdir, lines)
    golden.check_run(r, "units.txt")


DIMENSION_ERRORS = [
    _cmd("dimension", {"refs": [{"id": 100002}, {"id": 100003}], "at": [0, -1000]}),
    _cmd("dimension", {"refs": [{"id": 100002}], "at": [0, -1000]}),
    _cmd("dimension", {"at": [0, -1000]}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}]}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}], "at": [0, -1000], "kind": "slanted"}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}], "at": [0, -1000], "kind": "linear", "orient": "diagonal"}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}], "at": [0, -1000], "orient": "vertical"}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100005}], "at": [0, -1000]}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}], "at": [0, -1000], "type": "Fancy"}),
    _cmd("dimension", {"refs": [[3000, 9000], [6000, 2000]], "at": [0, -1000]}),
    _cmd("dimension", {"refs": [{"endpoint": [3000, 9000]}, {"id": 100003}], "at": [0, -1000]}),
    _cmd("dimension", {"refs": [{"id": 100005, "face": "middle"}, {"id": 100003}], "at": [0, -1000]}),
    _cmd("dimension", {"refs": [{"id": 999999}, {"id": 100003}], "at": [0, -1000]}),
    _cmd("dimension", {"kind": "angular", "refs": [{"id": 100005}, {"id": 100003}], "at": [3000, 2000]}),
    _cmd("dimension", {"kind": "angular", "refs": [{"id": 100005}, {"id": 100002}, {"id": 100003}], "at": [3000, 2000]}),
    _cmd("dimension", {"kind": "radial", "refs": [[3000, 2000]], "at": [3000, 2000]}),
    _cmd("dimension", {"kind": "radial", "refs": [{"id": 100003}], "at": [3000, 2000]}),
    _cmd("dimension", {"kind": "arc_length", "refs": [[3000, 2000]], "at": [3000, 2000]}),
    _cmd("dimension", {"kind": "linear", "orient": "horizontal", "refs": [{"id": 100002}, {"id": 100004}], "at": [3000, 9000]}),
    _cmd("dimension", {"refs": [{"id": 100002, "point": "start"}, {"id": 100005, "point": "end"}], "at": [-500, 2000]}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}], "at": [0, -1000], "level": "Level 9"}),
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003}], "at": [0, -1000], "prefix": "a\nb"}),
]


def test_dimension_errors(run, workdir, golden):
    """CATCHES: a rewrite that dimensions walls that aren't parallel, fewer than two references, no point, an unknown
    kind or orientation, an orient on an aligned one, the same reference twice, an unknown type, a point on nothing, an
    unknown face or element, an angle between parallel lines or of three, a radius of something not round, a linear
    dimension across what isn't square to it, points in one place, or a text on two lines; or words those differently."""
    golden.check(_sweep(run, workdir, ROOM[:4], DIMENSION_ERRORS), "dimension_errors.txt")


DIMENSION_TYPE_ERRORS = [
    _cmd("dimension_type", {"name": "X", "tick": "star"}),
    _cmd("dimension_type", {"name": "X", "string": "chain"}),
    _cmd("dimension_type", {"name": "X", "text_size": 0}),
    _cmd("dimension_type", {"name": "X", "width_factor": 20}),
    _cmd("dimension_type", {"name": "X", "tick_size": 60}),
    _cmd("dimension_type", {"name": "X", "witness_gap": -1}),
    _cmd("dimension_type", {"name": "X", "decimals": 7}),
    _cmd("dimension_type", {"name": "X", "units": "furlongs"}),
    _cmd("dimension_type", {"name": "X", "line_pen": 20}),
    _cmd("dimension_type", {"name": "X", "color": "teal"}),
    _cmd("dimension_type", {"name": "X", "equality_text": "E\nQ"}),
    _cmd("dimension_type", {"name": "X", "sparkle": True}),
    _cmd("dimension_type", {"name": "X", "like": "Nothing"}),
    _cmd("dimension_type", {"name": "Arrow - 2.5mm Arial", "rename": "Diagonal - 2.5mm Arial"}),
    _cmd("dimension_type", {"name": "Diagonal - 2.5mm Arial", "delete": True}),
    _cmd("dimension_type", {"name": "Gone", "delete": True}),
    _cmd("dimension_type", {"name": "Spare", "like": "Arrow - 2.5mm Arial"}) + "\n"
    + _cmd("dimension_type", {"name": "Spare", "delete": True}),
]


def test_dimension_type_errors(run, workdir, golden):
    """CATCHES: a rewrite that takes an unknown tick, string or units, sizes and pens out of range, more than six
    decimals, a colour that isn't one, text on two lines, an unknown key, a `like` there isn't, a rename over another
    type, or deletes a type a dimension is of; or that words the refusal differently."""
    setup = [*ROOM[:4], KINDS[1]]
    golden.check(_sweep(run, workdir, setup, DIMENSION_TYPE_ERRORS), "dimension_type_errors.txt")


THREE = [
    *ROOM,
    _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100006}, {"id": 100003}], "at": [0, -1500]}),
]


def test_dimension_text_overrides_and_segments(run, workdir, golden):
    """CATCHES: a rewrite whose dimension text doesn't put a prefix and suffix round each number, lets a segment's own
    text win over the dimension's, doesn't clear a segment with empty text, or draws text above and below in other
    places."""
    r = _script(run, workdir, [
        *THREE,
        _cmd("dimension_text", {"id": 100009, "prefix": "(", "suffix": ")"}),
        _cmd("dimension_text", {"id": 100009, "segment": 1, "replace": "VARIES", "above": "CLEAR"}),
        _cmd("dimension_text", {"id": 100009, "segment": 0, "prefix": "~", "below": "MIN"}),
        _cmd("dimension_text", {"id": 100009, "segment": 1, "replace": ""}),
        'elements {"category": "dimension"}',
    ], "--save", "texts.svg")
    golden.check_run(r, "texts.txt")
    golden.check((workdir / "texts.svg").read_text(), "texts.svg")


def test_dimension_constraints_keep_what_they_measure(run, workdir, golden):
    """CATCHES: a rewrite that doesn't keep an equal dimension's segments equal when a wall moves, doesn't hold a locked
    segment's length by moving what it measures to, refuses what it can keep, keeps what it can't, or replies
    differently."""
    r = _script(run, workdir, [
        *THREE,
        _cmd("dimension_constraint", {"id": 100009, "equal": True}),
        'elements {"category": "door"}',
        _cmd("move", {"ids": [100003], "by": [1000, 0]}),
        'elements {"category": "door"}',
        _cmd("dimension_constraint", {"id": 100009, "equal": False, "locked": [1, 1]}),
        _cmd("move", {"ids": [100006], "by": [-500, 0]}),
        'elements {"category": "dimension"}',
        _cmd("dimension_constraint", {"id": 100009, "locked": []}),
    ])
    golden.check_run(r, "constraints.txt")


def test_dimension_constraints_that_cannot_be_kept_are_refused(run, workdir, golden):
    """CATCHES: a rewrite that makes locked segments of other lengths equal, lets a command pull a locked run apart (a
    wall made thicker between two locked faces, a typed length against another dimension's lock), instead of refusing
    it and naming the dimension."""
    setup = [
        *THREE,
        _cmd("dimension_value", {"id": 100009, "value": 2000}),
        _cmd("dimension_constraint", {"id": 100009, "locked": [0, 1]}),
        'type {"category": "wall", "name": "Thick", "thickness": 400}',
        _cmd("dimension", {"refs": [{"id": 100005}, {"id": 100003, "face": "left"}, {"id": 100003, "face": "right"}],
                           "at": [0, 6000]}),
        _cmd("dimension_constraint", {"id": 100010, "locked": [0, 1]}),
    ]
    cases = [
        _cmd("dimension_constraint", {"id": 100009, "equal": True}),
        _cmd("modify", {"id": 100003, "type": "Thick"}),
        "\n".join([_cmd("dimension", {"refs": [{"id": 100005}, {"id": 100006}], "at": [0, -3000]}),
                   _cmd("dimension_constraint", {"id": 100011, "locked": [0]}),
                   _cmd("dimension_value", {"id": 100011, "value": 1500})]),
        _cmd("move", {"ids": [100005], "by": [300, 0]}) + "\n" + 'elements {"category": "wall"}',
    ]
    golden.check(_sweep(run, workdir, setup, cases), "constraints_refused.txt")


def test_dimension_value_moves_what_a_segment_ends_at(run, workdir, golden):
    """CATCHES: a rewrite whose typed length moves the wrong element, by the wrong amount or the wrong way, ignores
    `segment`, or doesn't lock a locked segment at its new length."""
    r = _script(run, workdir, [
        *THREE,
        _cmd("dimension_value", {"id": 100009, "value": 2000}),
        'elements {"category": "door"}',
        _cmd("dimension_constraint", {"id": 100009, "locked": [0]}),
        _cmd("dimension_value", {"id": 100009, "value": 3500, "segment": 1}),
        _cmd("dimension_value", {"id": 100009, "value": 2500, "segment": 0}),
        'elements {"category": "dimension"}',
    ])
    golden.check_run(r, "values.txt")


CONSTRAINT_ERRORS = [
    _cmd("dimension_constraint", {"id": 100003, "equal": True}),
    _cmd("dimension_constraint", {"id": 100009, "locked": [5]}),
    _cmd("dimension_constraint", {"id": 100009, "locked": "all"}),
    _cmd("dimension_constraint", {"id": 100010, "equal": True}),
    _cmd("dimension_constraint", {"id": 100011, "locked": [0]}),
    _cmd("dimension_constraint", {"id": 100009, "frozen": True}),
    _cmd("dimension_text", {"id": 100003, "prefix": "x"}),
    _cmd("dimension_text", {"id": 100009, "segment": 7, "prefix": "x"}),
    _cmd("dimension_text", {"id": 100009, "suffix": "a\tb"}),
    _cmd("dimension_text", {"id": 100009, "font": "x"}),
    _cmd("dimension_value", {"id": 100009}),
    _cmd("dimension_value", {"id": 100009, "value": -5}),
    _cmd("dimension_value", {"id": 100009, "value": 100, "segment": 4}),
    _cmd("dimension_value", {"id": 100011, "value": 100}),
    _cmd("dimension_value", {"id": 999999, "value": 100}),
    _cmd("dimension_value", {"id": 100003, "value": 100}),
]


def test_dimension_constraint_text_and_value_errors(run, workdir, golden):
    """CATCHES: a rewrite that constrains, words or types a length into what isn't a dimension, a segment there isn't,
    a dimension of one segment made equal, an angle locked or typed, a length that isn't one, or an unknown key; or
    that words the refusal differently."""
    setup = [*THREE, KINDS[1], KINDS[4]]
    golden.check(_sweep(run, workdir, setup, CONSTRAINT_ERRORS), "constraint_errors.txt")


TYPES = [
    _cmd("text_type", {"name": "2.5mm", "font": "IBM Plex Sans"}),
    _cmd("text_type", {"name": "Title", "like": "5mm", "font": "ibm plex mono", "bold": True, "border": True,
                       "border_offset": 2, "border_pen": 3, "color": [0, 0, 160]}),
    _cmd("text_type", {"name": "Hand", "font": "BIMCraft Lettering", "size": 3.5, "italic": True, "underline": True,
                       "width_factor": 1.5, "color": "#008000"}),
    _cmd("text_type", {"name": "Title", "rename": "Heading"}),
    _cmd("text_type", {"name": "Spare", "like": "Hand", "size": 7}),
    _cmd("text_type", {"name": "Spare", "delete": True}),
]

NOTES = [
    'wall {"points": [[0, 0], [8000, 0]]}',
    _cmd("text", {"text": "Plain note\nsecond line", "at": [0, 3000]}),
    _cmd("text", {"text": "HEADING", "at": [0, 5000], "type": "Heading"}),
    _cmd("text", {"text": "Turned", "at": [5000, 3000], "type": "Hand", "angle": 30}),
    _cmd("text", {"text": "With a leader", "at": [3000, 1500], "leader": [2000, 0], "type": "Heading"}),
    _cmd("text", {"text": "Bold and plain", "at": [0, 7000], "override_format": True,
                  "runs": [{"from": 0, "to": 4, "bold": True}, {"from": 9, "to": 14, "italic": True, "underline": True}]}),
    _cmd("text", {"text": "one two three\nfour", "at": [0, 8000], "override_format": True, "type": "Hand",
                  "runs": [{"from": 4, "to": 7, "underline": False, "bold": True}, {"from": 8, "to": 16, "underline": True}]}),
    _cmd("text", {"text": "Árvíztűrő Σ Ж", "at": [5000, 6500]}),
]


def test_text_types_and_notes(run, workdir, golden):
    """CATCHES: a rewrite whose text types don't start from `like` or the 2.5mm Arial default, don't name a carried
    font as it is spelt, lose a rename on the notes of the type, or list notes (type, angle, leader, runs)
    differently."""
    r = _script(run, workdir, [*TYPES, *NOTES, 'elements {"category": "text"}'])
    golden.check_run(r, "notes.txt")


def test_text_notes_drawn_in_a_plan(run, workdir, golden):
    """CATCHES: a rewrite that letters notes in other outlines or places: the line pitch of two lines, a type's size,
    bold, italic, underline, width factor and colour, a border and its offset, a turned note, a leader from the border,
    formatting runs, and accented, Greek and Cyrillic letters."""
    r = _script(run, workdir, [*TYPES, *NOTES], "--save", "notes.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "notes.svg").read_text(), "notes.svg")


def test_a_note_keeps_its_runs_when_its_text_changes(run, workdir, golden):
    """CATCHES: a rewrite whose `modify` with new text drops a note's formatting runs or doesn't carry them over the
    characters that stayed, or that changes a note's type without keeping its runs."""
    r = _script(run, workdir, [
        _cmd("text", {"text": "Bold and plain", "at": [0, 0], "override_format": True,
                      "runs": [{"from": 0, "to": 4, "bold": True}, {"from": 9, "to": 14, "italic": True}]}),
        _cmd("modify", {"id": 100002, "text": "Very Bold and plain"}),
        _cmd("modify", {"id": 100002, "type": "5mm"}),
        'elements {"category": "text"}',
    ])
    golden.check_run(r, "runs.txt")


TEXT_ERRORS = [
    _cmd("text", {"at": [0, 0]}),
    _cmd("text", {"text": "x"}),
    _cmd("text", {"text": "x", "at": [0, 0], "size": 5}),
    _cmd("text", {"text": "x", "at": [0, 0], "type": "Huge"}),
    _cmd("text", {"text": "x", "at": [0, 0], "view": "Nowhere"}),
    _cmd("text", {"text": "x" * 4001, "at": [0, 0]}),
    _cmd("text", {"text": 42, "at": [0, 0]}),
    _cmd("text", {"text": "abc", "at": [0, 0], "override_format": True, "runs": [{"from": 1, "to": 9, "bold": True}]}),
    _cmd("text", {"text": "abcdef", "at": [0, 0], "override_format": True,
                  "runs": [{"from": 0, "to": 3, "bold": True}, {"from": 2, "to": 4, "italic": True}]}),
    _cmd("text", {"text": "abc", "at": [0, 0], "override_format": True, "runs": [{"from": 0, "to": 2}]}),
    _cmd("text", {"text": "abc", "at": [0, 0], "runs": [{"from": 0, "to": 2, "shout": True}]}),
    _cmd("text", {"text": "abc", "at": [0, 0], "angle": "steep"}),
    _cmd("text", {"text": "abc", "at": [0, 0], "colour": "red"}),
    _cmd("text_type", {"name": "X", "size": 0}),
    _cmd("text_type", {"name": "X", "size": 101}),
    _cmd("text_type", {"name": "X", "width_factor": 0.05}),
    _cmd("text_type", {"name": "X", "border_offset": 60}),
    _cmd("text_type", {"name": "X", "border_pen": 17}),
    _cmd("text_type", {"name": "X", "color": [1, 2]}),
    _cmd("text_type", {"name": "X", "bold": "yes"}),
    _cmd("text_type", {"name": "X", "like": "Nothing"}),
    _cmd("text_type", {"name": "3.5mm", "rename": "5mm"}),
    _cmd("text_type", {"name": "2.5mm", "delete": True}),
    _cmd("text_type", {"name": "Gone", "delete": True}),
    _cmd("text_type", {"name": "X", "leading": 2}),
]


def test_text_and_text_type_errors(run, workdir, golden):
    """CATCHES: a rewrite that makes a note without text or a point, of a size of its own, of a type or view there
    isn't, longer than a note holds, or with runs out of the text, overlapping, overriding nothing or of unknown keys;
    or a text type of a size, width, border or pen out of range, from a `like` there isn't, renamed over another, or
    deleted while a note is of it; or that words the refusal differently."""
    setup = ['text {"text": "kept", "at": [0, 0]}']
    golden.check(_sweep(run, workdir, setup, TEXT_ERRORS), "text_errors.txt")


HOUSE = [
    'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
    'floor {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]}',
    'door {"at": [3000, 0]}',
    'window {"at": [3000, 4000]}',
    'window {"at": [0, 2000]}',
    'room {"point": [3000, 2000], "name": "Hall"}',
    'roof {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "level": "Level 2", "slope": 30}',
]

SPOTS = [
    'spot {"at": [1000, 1000]}',
    'spot {"at": [3000, 0]}',
    'spot {"at": [1000, 1000], "view": "Level 2"}',
    'spot {"at": [5000, 3000], "host": 100006}',
    'spot_slope {"at": [500, 2000], "view": "Level 2"}',
    'spot_slope {"at": [3000, 3900], "view": "Level 2"}',
    'spot_slope {"at": [1000, 1000]}',
    'section {"start": [3000, -2000], "end": [3000, 6000], "name": "S"}',
    'spot {"at": [1000, 3000], "view": "S"}',
]


def test_spot_elevations_and_slopes(run, workdir, golden):
    """CATCHES: a rewrite that reads a spot elevation off another element (a floor's top, a wall's top, a hip roof's
    surface), measures a roof's slope or the way down differently, gives a level floor a slope or a way, or lists spots
    differently; and one that misreads a spot in a section."""
    r = _script(run, workdir, [*HOUSE, *SPOTS, 'elements {"category": "spot"}'])
    golden.check_run(r, "spots.txt")


def test_spot_elevations_and_slopes_drawn(run, workdir, golden):
    """CATCHES: a rewrite that draws a spot elevation's mark and figure, or a spot slope's arrow and percentage, in
    other places, sizes or ways."""
    r = _script(run, workdir, [*HOUSE, *SPOTS[:4], *SPOTS[6:7]], "--save", "spots1.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "spots1.svg").read_text(), "spots_level1.svg")
    r = run(["run", "--script", "s.txt", "--cmd", SPOTS[4], "--cmd", SPOTS[5], "--cmd",
             'render {"view": "Level 2", "path": "spots2.svg"}'])
    golden.check_run(r, "spots_level2_run.txt")
    golden.check((workdir / "spots2.svg").read_text(), "spots_level2.svg")


SPOT_ERRORS = [
    'spot {"at": [20000, 20000]}',
    'spot {}',
    'spot {"at": [0, 0], "view": "Nowhere"}',
    'spot {"at": [0, 0], "host": 999999}',
    'spot_slope {"at": [20000, 20000]}',
    'spot_slope {"at": [1000, 1000], "view": "S"}',
    'spot_slope {"at": [1000, 1000], "host": 100002}',
]


def test_spot_errors(run, workdir, golden):
    """CATCHES: a rewrite that places a spot over nothing, without a point, in a view or of a host there isn't, or a spot
    slope in a section or on a wall; or that words the refusal differently."""
    setup = [*HOUSE, 'section {"start": [3000, -2000], "end": [3000, 6000], "name": "S"}']
    golden.check(_sweep(run, workdir, setup, SPOT_ERRORS), "spot_errors.txt")


TAGS = [
    'tag {}',
    'tag {"ids": [100010], "label": "Area"}',
    'tag {"category": "wall", "offset": [100, 200], "leader": true}',
    'tag {"ids": [100006], "label": "Thickness"}',
    'tag {"ids": [100010]}',
    'tag {"category": "room", "level": "Level 1"}',
]


def test_tags(run, workdir, golden):
    """CATCHES: a rewrite whose Tag All tags other elements than the untagged doors and windows of the level, whose
    tags read another field (mark, room name, type, a schedule field by label), sit at another offset, or are listed
    differently; and one that tags a room twice."""
    r = _script(run, workdir, [*HOUSE, *TAGS[:5], 'elements {"category": "tag"}'])
    golden.check_run(r, "tags.txt")


def test_tags_drawn(run, workdir, golden):
    """CATCHES: a rewrite that draws a tag's box, text or leader in other places or sizes."""
    r = _script(run, workdir, [*HOUSE, *TAGS[:5]], "--save", "tags.svg")
    assert r.returncode == 0, r.stderr.decode()
    golden.check((workdir / "tags.svg").read_text(), "tags.svg")


TAG_ERRORS = [
    'tag {}',
    'tag {"category": "column"}',
    'tag {"ids": [100008], "label": "Area"}',
    'tag {"ids": [999999]}',
    'tag {"ids": [100002], "offset": "up"}',
    'tag {"ids": [100002], "level": "Level 9"}',
]


def test_tag_errors(run, workdir, golden):
    """CATCHES: a rewrite that tags nothing quietly when every door and window has its tag, tags a category the level
    hasn't, a field the element hasn't, or an element there isn't, or takes an offset that isn't a vector; or that
    words the refusal differently."""
    setup = [*HOUSE, 'tag {}']
    golden.check(_sweep(run, workdir, setup, TAG_ERRORS), "tag_errors.txt")


LETTERS = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ Æ 0123456789 .,-+=_/({})':\"#×²°±\n"
           "АВЕКМНОРСТХЗБГДЖИЛПУФЦЧШЩЪЫЬЭЮЯ ЁЙ !;*%&[]<>@?|~$€³·–—‘’“”„\n"
           "ÁÀÂÃÄÅĀĂĄ ĆČÇ Ď ÉÈÊËĚĒĖĘ Ğ ÍÌÎÏĪİ ĹŁ ÑŃŇ ÓÒÔÕÖŐŌØ ŔŘ ŚŠŞ Ť ÚÙÛÜŰŮŪ ÝŸ ŹŽŻ\n"
           "lower case: abc xyz áé ñ")


def test_lettering_draws_every_letter_it_has(run, workdir, golden):
    """CATCHES: a rewrite whose single-stroke lettering draws a capital, figure, sign, Cyrillic letter or accent in
    other strokes, letters lower case otherwise than as capitals, or draws a letter it hasn't (in a room's tag) as
    anything but its question mark."""
    r = _script(run, workdir, [
        _cmd("text_type", {"name": "Hand", "font": "BIMCraft Lettering", "size": 5}),
        _cmd("text", {"text": LETTERS, "at": [0, 0], "type": "Hand"}),
        'wall {"points": [[0, -6000], [6000, -6000], [6000, -2000], [0, -2000]], "closed": true}',
        _cmd("room", {"point": [3000, -4000], "name": "Ωmega №7 ∑ Ľ"}),
    ], "--save", "letters.svg")
    golden.check_run(r, "letters_run.txt")
    golden.check((workdir / "letters.svg").read_text(), "letters.svg")
