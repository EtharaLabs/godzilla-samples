"""Reinforcement: bars drawn by hand (`rebar`), bars by rules (`reinforce`) for a beam, a column (rectangular and round),
a footing (rectangular and round) and a floor (with openings and a slope), presets (`reinforcement_preset`), several hosts
at once, the NBR 6118 check's notes, the refusals that say what to change, the bar schedule, and plans, IFC and files that
hold the bars."""

import json

import pytest
from conftest import make_project, normalize, png_pixels

# Hosts, each the first element of a new project, so its id is 100002.
BEAM = 'beam {"points": [[0, 0], [6000, 0]]}'
COLUMN = 'structural_column {"at": [1000, 2000], "type": "Concrete 300 x 300", "height": 3000}'
ROUND_COLUMN = 'structural_column {"at": [0, 0], "type": "Concrete Round 400", "height": 3000}'
FOOTING = 'footing {"at": [3000, 3000], "type": "Footing 1200 x 1200"}'
SLAB = 'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}'
HOST = 100002


def _round(v):
    """Numbers to a millionth (so a cosine's last bit does not show), minus zero as zero."""
    if isinstance(v, float):
        x = round(v, 6)
        return 0.0 if x == 0 else x
    if isinstance(v, list):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def _bar_line(e):
    path = json.dumps(_round(e["path"]), separators=(",", ":"))
    return (f"{e['id']} {e.get('layer') or '-'} d={e['diameter']} {e['grade']} L={_round(e['length'])} "
            f"kg={e['weight_kg']} {path}")


def _report(r):
    """A run's exit code, its replies (an `elements` listing of bars written one bar to a line, numbers to a millionth)
    and stderr."""
    out = [f"exit: {r.returncode}"]
    for line in r.stdout.decode().splitlines():
        reply = json.loads(line)
        if isinstance(reply, dict) and "elements" in reply and all(isinstance(e, dict) and e.get("category") == "rebar" for e in reply["elements"]):
            out.append(f"{reply['count']} bars, {reply['returned']} returned")
            out.extend(_bar_line(e) for e in reply["elements"])
        else:
            out.append(json.dumps(_round(reply), ensure_ascii=False, sort_keys=True))
    out.append("--- stderr")
    out.append(r.stderr.decode().rstrip("\n"))
    return normalize("\n".join(out) + "\n")


def _args(*commands):
    out = ["run"]
    for c in commands:
        out += ["--cmd", c]
    return out


VARIABLE = ('type {"category": "floor", "name": "Var", "layers": [{"function": "finish", "thickness": 60, "variable": true}, '
            '{"function": "structure", "thickness": 200}]}')
DEEP = 'type {"category": "beam", "name": "Deep", "width": 200, "depth": 800, "material": "Concrete"}'

# Each case: the host's command, the `reinforce` parameters (but the host), and commands to run between them.
ARMED = {
    "beam_rows_and_stirrups": (BEAM, {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "top": {"count": 2, "diameter": 12.5},
                                      "stirrup": {"diameter": 5, "spacing": 150}}, ()),
    "beam_closer_stirrups_at_the_ends_and_skin": (
        'beam {"points": [[0, 0], [5000, 0]], "type": "Deep"}',
        {"cover": 30, "bottom": {"count": 2, "diameter": 20}, "stirrup": {"diameter": 6.3, "spacing": 200, "ends": {"length": 1000, "spacing": 100}},
         "skin": {"diameter": 8, "spacing": 150}}, ()),
    "beam_hooks_and_anchors": (BEAM, {"cover": 25, "bottom": {"count": 2, "diameter": 16, "hook": 150},
                                      "top": {"count": 2, "diameter": 10, "hook": {"start": 100, "end": 200}},
                                      "stirrup": {"diameter": 5, "spacing": 300, "hook": 50}, "anchor": {"start": 0, "end": 300}}, ()),
    "beam_bent_up_bars": (BEAM, {"cover": 25, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 2, "top": 500}},
                                 "stirrup": {"diameter": 5, "spacing": 600}}, ()),
    "beam_bent_up_steeper_by_default_length": (BEAM, {"cover": 25, "bottom": {"count": 3, "diameter": 16, "bent": {"count": 1, "angle": 60}},
                                                      "top": {"count": 2, "diameter": 12.5}}, ()),
    "beam_cover_by_face_and_grades": (BEAM, {"cover": {"top": 40, "bottom": 30, "sides": 20}, "grade": "CA-60", "grade_stirrup": "CA-50",
                                             "clearance": 25, "bottom": {"count": 2, "diameter": 12.5}, "stirrup": {"diameter": 5, "spacing": 1000}}, ()),
    "beam_sloped_three_four_five": ('beam {"points": [[0, 0], [3000, 4000]], "offset": 3000, "end_offset": 3000}',
                                    {"cover": 25, "bottom": {"count": 2, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 1500}}, ()),
    "beam_rising": ('beam {"points": [[0, 0], [3000, 0]], "offset": 0, "end_offset": 1000, "justify": "centre"}',
                    {"cover": 25, "top": {"count": 2, "diameter": 10}, "stirrup": {"diameter": 5, "spacing": 1000}}, ()),
    "beam_cover_from_its_cobrimento": (BEAM, {"bottom": {"count": 2, "diameter": 16}},
                                       ('parameter {"name": "Cobrimento", "kind": "length", "categories": ["beam"]}',
                                        'modify {"id": 100002, "params": {"Cobrimento": 30}}')),
    "column_bars_stirrups_and_ties": (COLUMN, {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3}, "stirrup": {"diameter": 5, "spacing": 600},
                                               "ties": {"diameter": 6.3}}, ()),
    "column_cover_by_face_and_anchors": (COLUMN, {"cover": {"top": 25, "bottom": 50, "sides": 25}, "bars": {"diameter": 16, "x": 2, "y": 3},
                                                  "anchor": {"below": 400, "above": 600}}, ()),
    "column_hooks_and_tied_tails": (COLUMN, {"cover": 25, "stirrup": {"diameter": 5, "spacing": 1500}, "bars": {"diameter": 16, "x": 3, "y": 3, "hook": {"below": 150}},
                                             "ties": {"diameter": 6.3, "hook": 50}}, ()),
    "column_jog_near_the_top": (COLUMN, {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3, "jog": {"by": 30, "from_top": 400}}}, ()),
    "column_gentle_jog": (COLUMN, {"cover": 25, "bars": {"diameter": 16, "jog": {"by": 30, "from_top": 500, "slope": 10}, "hook": {"above": 100}}}, ()),
    "column_turned": ('structural_column {"at": [1000, 2000], "type": "Concrete 200 x 500", "height": 3000, "angle": 33}',
                      {"cover": 25, "bars": {"diameter": 12.5, "x": 2, "y": 3}, "stirrup": {"diameter": 5, "spacing": 1400}}, ()),
    "column_round": (ROUND_COLUMN, {"cover": 25, "stirrup": {"diameter": 5, "spacing": 1500, "hook": 50},
                                    "bars": {"diameter": 16, "count": 8, "hook": {"below": 100}, "jog": {"by": 20, "from_top": 400}}}, ()),
    "footing_mesh_with_hooks": (FOOTING, {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}, "y": {"diameter": 12.5, "spacing": 200}, "hook": 100}}, ()),
    "footing_turned_one_layer": ('footing {"at": [0, 0], "type": "Footing 1500 x 1500", "thickness": 600, "angle": 90}',
                                 {"cover": 40, "grade": "CA-25", "mesh": {"y": {"diameter": 10, "spacing": 300}}}, ()),
    "footing_round": ('footing {"at": [3000, 3000], "type": "Round 1000"}',
                      {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}, "y": {"diameter": 10, "spacing": 150}, "hook": 100}},
                      ()),
    "floor_two_meshes": (SLAB, {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 150}, "y": {"diameter": 8, "spacing": 200}},
                                "top": {"x": {"diameter": 6.3, "spacing": 400}}}, ()),
    "floor_l_shaped": ('floor {"boundary": [[0, 0], [4000, 0], [4000, 1400], [1500, 1400], [1500, 3000], [0, 3000]]}',
                       {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 300}, "y": {"diameter": 8, "spacing": 400}}}, ()),
    "floor_round_an_opening": ('floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "openings": [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]]}',
                               {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 300}}}, ()),
    "floor_hooks": (SLAB, {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 500}, "hook": 100},
                           "top": {"y": {"diameter": 6.3, "spacing": 800}, "hook": 60}}, ()),
    "beam_one_bar_in_the_middle": (BEAM, {"cover": 25, "bottom": {"count": 1, "diameter": 20}, "top": {"count": 1, "diameter": 10}}, ()),
    "column_closer_stirrups_at_the_ends": (COLUMN, {"cover": 25, "bars": {"diameter": 12.5},
                                                    "stirrup": {"diameter": 5, "spacing": 1000, "ends": {"length": 500, "spacing": 250}}}, ()),
    "floor_shaped_over_its_variable_layer": (
        'floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "type": "Var"}',
        {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 1000}}, "top": {"y": {"diameter": 8, "spacing": 1500}}},
        ('add_point {"id": 100002, "at": [2000, 1500], "z": -40}',)),
    "floor_sloped": ('floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "slope": 5, "arrow": [[0, 0], [4000, 0]]}',
                     {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 600}, "y": {"diameter": 8, "spacing": 800}}}, ()),
}


@pytest.mark.parametrize("case", sorted(ARMED))
def test_reinforce_lays_bars_by_rules(run, golden, case):
    """CATCHES: a rewrite whose `reinforce` lays a host's bars elsewhere (inside the cover and the stirrups, spread
    evenly with the last a spacing's room from the end), with another count, length, weight, layer, grade or bend
    (hooks, anchors, bent-up bars, stirrup tails, ties, a column's jog, a round host's circle, a floor's outline,
    openings and slope), or replies with another count, weight or notes."""
    host, spec, before = ARMED[case]
    setup = (DEEP,) if "Deep" in host else ()
    if "Round 1000" in host:
        setup = ('type {"category": "footing", "name": "Round 1000", "width": 1000, "round": true}',)
    if '"Var"' in host:
        setup = (VARIABLE,)
    args = _args(*setup, host, *before, "reinforce " + json.dumps({"host": HOST, **spec}),
                 'elements {"category": "rebar"}')
    golden.check(_report(run(args)), f"armed_{case}.txt")


def _refusals(run, host_cmd, specs, setup=()):
    """Each `reinforce` of a new host with one of `specs` (the host added), in a process of its own."""
    parts = []
    for spec in specs:
        cmd = "reinforce " + json.dumps({"host": HOST, **spec})
        r = run(_args(*setup, host_cmd, cmd))
        parts.append(f"$ {cmd}\nexit: {r.returncode}\n{r.stderr.decode()}")
    return normalize("".join(parts))


ROW = {"count": 2, "diameter": 16}
STIR = {"diameter": 5, "spacing": 150}
REFUSED = {
    "beam": (BEAM, [
        {"cover": 25, "bottom": {"count": 6, "diameter": 25}},
        {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "clearance": 60},
        {"cover": 100, "bottom": {"count": 1, "diameter": 16}},
        {"cover": 25},
        {"cover": {"top": 230, "bottom": 230, "sides": 25}, "top": ROW, "bottom": ROW},
        {"cover": 25, "mesh": {"x": {"diameter": 10, "spacing": 200}}},
        {"cover": 25, "bottom": ROW, "colour": "red"},
        {"cover": 25, "bottom": {"count": 0, "diameter": 16}},
        {"cover": 25, "bottom": {"count": 2, "diameter": 1}},
        {"cover": 25, "bottom": {"count": 2, "diameter": 200}},
        {"cover": 25, "bottom": {"count": 2}},
        {"cover": 25, "bottom": {"count": 2, "diameter": 16, "colour": 1}},
        {"cover": 25, "stirrup": {"diameter": 5, "spacing": 0}},
        {"cover": 25, "stirrup": {"diameter": 5, "spacing": 3}},
        {"cover": 25, "stirrup": {"diameter": 5, "spacing": 5.5}},
        {"cover": 25, "stirrup": {"diameter": 5, "spacing": 150, "ends": {"length": -1, "spacing": 100}}},
        {"cover": 25, "stirrup": {"diameter": 5, "spacing": 150, "hook": -3}},
        {"cover": -5, "bottom": ROW},
        {"cover": 1e300, "bottom": ROW},
        {"cover": "thick", "bottom": ROW},
        {"cover": {"top": 25, "middle": 3}, "bottom": ROW},
        {"bottom": ROW},
        {"cover": 25, "bottom": ROW, "grade": ""},
        {"cover": 25, "bottom": ROW, "grade_stirrup": " "},
        {"cover": 25, "bottom": ROW, "clearance": 0},
        {"cover": 25, "bottom": {"count": 2, "diameter": 16, "hook": 500}, "stirrup": STIR},
        {"cover": 25, "bottom": {"count": 2, "diameter": 16, "hook": {"middle": 5}}},
        {"cover": 25, "bottom": {"count": 2, "diameter": 16, "hook": "x"}},
        {"cover": 25, "bottom": ROW, "anchor": {"start": -1}},
        {"cover": 25, "bottom": ROW, "skin": {"diameter": 8, "spacing": 5}},
        {"cover": 25, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 3}}},
        {"cover": 25, "bottom": {"count": 2, "diameter": 16, "bent": {"count": 1}}},
        {"cover": 25, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 1, "angle": 10}}},
        {"cover": 25, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 1, "top": 2800}}},
        {"cover": 25, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 1, "top": -1}}},
        {"cover": 25, "bottom": {"count": 4, "diameter": 16}, "top": {"count": 2, "diameter": 12.5, "bent": {"count": 1}}},
        {"cover": 25, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 2}}, "top": {"count": 3, "diameter": 12.5}},
        {"cover": {"top": 230, "bottom": 230, "sides": 25}, "bottom": {"count": 2, "diameter": 50}},
        {"cover": {"top": 25, "bottom": 25, "sides": 50}, "bottom": ROW, "skin": {"diameter": 100, "spacing": 150}, "stirrup": STIR},
    ]),
    "column": (COLUMN, [
        {"cover": 25, "bars": {"diameter": 16, "x": 1}},
        {"cover": 25, "bars": {"diameter": 16, "x": 2000}},
        {"cover": 25, "bars": {"diameter": 16, "x": 9, "y": 9}},
        {"cover": 25, "bars": {"diameter": 16}, "ties": {"diameter": 6.3}},
        {"cover": 25, "bars": {"diameter": 16}, "stirrup": STIR, "ties": {"diameter": 6.3}},
        {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3}, "stirrup": STIR, "ties": {"diameter": 6.3, "hook": -1}},
        {"cover": 25, "bars": {"diameter": 16}, "mesh": {}},
        {"cover": 25, "bars": {"diameter": 16}, "bottom": ROW},
        {"cover": 25, "stirrup": STIR, "anchor": {"below": -5}},
        {"cover": 200, "bars": {"diameter": 16}},
        {"cover": 25},
        {"cover": 25, "bars": {"diameter": 16, "count": 8}},
        {"cover": 25, "stirrup": STIR, "bars": {"diameter": 16, "hook": 300}},
        {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3, "jog": {"by": 30, "from_top": 3000}}},
        {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3, "jog": {"by": 30, "from_top": 100}}},
        {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3, "jog": {"by": 30, "from_top": 400, "slope": 0.5}}},
        {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3, "jog": {"by": 0, "from_top": 400}}},
        {"cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3, "jog": {"by": 100, "from_top": 800}}},
        {"cover": {"top": 1600, "bottom": 1600, "sides": 25}, "bars": {"diameter": 16}},
        {"cover": 145, "bars": {"diameter": 16}},
        {"cover": {"top": 1500, "bottom": 1497, "sides": 25}, "bars": {"diameter": 16}, "stirrup": STIR},
        {"cover": 25, "bars": {"diameter": 16}, "stirrup": {"diameter": 5, "spacing": 150, "ends": {"length": 0, "spacing": 100}}},
    ]),
    "round_column": (ROUND_COLUMN, [
        {"cover": 25, "bars": {"diameter": 16, "x": 3}},
        {"cover": 25, "bars": {"diameter": 16}},
        {"cover": 25, "bars": {"diameter": 16, "count": 2}},
        {"cover": 25, "bars": {"diameter": 16, "count": 60}},
        {"cover": 25, "bars": {"diameter": 16, "count": 8}, "stirrup": STIR, "ties": {"diameter": 5}},
        {"cover": 25, "bars": {"diameter": 16, "count": 8, "hook": 500}},
        {"cover": 195, "bars": {"diameter": 16, "count": 8}},
    ]),
    "footing": (FOOTING, [
        {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}, "hook": 400}},
        {"cover": 200, "mesh": {"x": {"diameter": 10, "spacing": 150}}},
        {"cover": 50, "mesh": {}},
        {"cover": 50, "mesh": {"z": {"diameter": 10, "spacing": 150}}},
        {"cover": 50, "bottom": {"count": 2, "diameter": 10}},
        {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 10}}},
        {"cover": 650, "mesh": {"x": {"diameter": 10, "spacing": 150}}},
        {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}}, "check": "NBR 6118", "aggressiveness": 5},
        {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 15}}},
        {"cover": 50, "mesh": {"y": {"diameter": 10, "spacing": 150}}, "clearance": 200},
    ]),
    "floor": (SLAB, [
        {"cover": 90, "bottom": {"x": {"diameter": 8, "spacing": 150}}, "top": {"x": {"diameter": 8, "spacing": 150}}},
        {"cover": 20, "bottom": {}},
        {"cover": 20, "stirrup": STIR, "bottom": {"x": {"diameter": 8, "spacing": 150}}},
        {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 150}, "hook": 300}},
        {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 150}, "hook": -1}},
        {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 1}}},
        {"cover": 20, "top": {"y": {"diameter": 8, "spacing": 150}, "hook": 250}},
        {"cover": 20},
        {"cover": {"top": 180, "bottom": 20, "sides": 20}, "bottom": {"x": {"diameter": 8, "spacing": 150}}},
        {"cover": {"top": 20, "bottom": 180, "sides": 20}, "top": {"x": {"diameter": 8, "spacing": 150}}},
    ]),
}


@pytest.mark.parametrize("host", sorted(REFUSED))
def test_reinforce_refuses_what_does_not_fit_and_says_what_to_change(run, golden, host):
    """CATCHES: a rewrite that arms a host with bars that do not fit (clearance, cover, a hook or a jog past the
    section, bent bars that meet), accepts a parameter of another kind of host or an unknown key, a diameter, count,
    spacing, cover or grade out of range, or words any refusal (including serde's words for a key) differently."""
    host_cmd, specs = REFUSED[host]
    golden.check(_refusals(run, host_cmd, specs), f"refused_{host}.txt")


def test_reinforce_refusals_of_the_host_itself(run, golden):
    """CATCHES: a rewrite that arms something that is no beam, column, footing or floor (a wall, a round beam, a pipe),
    finds no element where the reference does, or refuses `host` and `hosts` given together, an empty or oversized list,
    or a host that is not an id, with other words."""
    cmds = [
        ('wall {"points": [[0, 0], [4000, 0]]}', {"host": HOST, "cover": 25, "bottom": ROW}),
        ('beam {"points": [[0, 0], [4000, 0]], "type": "Steel Tube 150"}', {"host": HOST, "cover": 25, "bottom": ROW}),
        ('pipe {"points": [[0, 0], [4000, 0]]}', {"host": HOST, "cover": 25, "bottom": ROW}),
        (BEAM, {"cover": 25, "bottom": ROW}),
        (BEAM, {"host": 999999, "cover": 25, "bottom": ROW}),
        (BEAM, {"host": "x", "cover": 25, "bottom": ROW}),
        (BEAM, {"host": HOST, "hosts": [HOST], "cover": 25, "bottom": ROW}),
        (BEAM, {"hosts": [], "cover": 25, "bottom": ROW}),
        (BEAM, {"hosts": "all", "cover": 25, "bottom": ROW}),
        (BEAM, {"hosts": [HOST, 999999], "cover": 25, "bottom": ROW}),
        (BEAM, {"hosts": [HOST, "nope"], "cover": 25, "bottom": ROW}),
        (BEAM, {"hosts": [HOST] * 1001, "cover": 25, "bottom": ROW}),
        (BEAM, {"host": HOST, "cover": 25, "bottom": ROW, "check": "NBR 9999"}),
        (BEAM, {"host": HOST, "cover": 25, "bottom": ROW, "aggressiveness": 2}),
        (BEAM, {"host": HOST, "cover": 25, "bottom": ROW, "check": "NBR 6118", "fck": 5}),
        (BEAM, {"host": HOST, "cover": 25, "bottom": ROW, "check": "NBR 6118", "aggressiveness": 0}),
        (BEAM, {"host": HOST, "cover": 25, "bottom": ROW, "check": 6118}),
        (BEAM, {"host": HOST, "preset": "nope"}),
        (BEAM, {"host": HOST, "preset": 5}),
        ('floor {"boundary": [[0, 0], [40000, 0], [40000, 30000], [0, 30000]]}',
         {"host": HOST, "cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 28}}}),
        ('floor {"boundary": [[0, 0], [40000, 0], [40000, 30000], [0, 30000]]}',
         {"host": HOST, "cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 60}, "y": {"diameter": 8, "spacing": 60}}}),
        ('beam {"points": [[0, 0], [40, 0]]}', {"host": HOST, "cover": 25, "bottom": ROW}),
        ('beam {"points": [[0, 0], [40, 0]]}', {"host": HOST, "cover": 25, "bottom": ROW, "anchor": {"start": 0, "end": 0}, "stirrup": STIR}),
        ('type {"category": "footing", "name": "F 2000 x 600", "width": 2000, "depth": 600}; footing {"at": [0, 0], "type": "F 2000 x 600", "angle": 30}',
         {"host": HOST, "cover": {"top": 50, "bottom": 50, "sides": 300}, "mesh": {"y": {"diameter": 10, "spacing": 150}}}),
        ('floor {"boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}; add_point {"id": 100002, "at": [2000, 1500], "z": -40}',
         {"host": HOST, "cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 150}}}),
    ]
    parts = []
    for host_cmd, spec in cmds:
        cmd = "reinforce " + json.dumps(spec)
        r = run(_args(*host_cmd.split("; "), cmd))
        parts.append(f"$ {host_cmd} ; {cmd[:300]}\nexit: {r.returncode}\n{r.stderr.decode()}")
    golden.check(normalize("".join(parts)), "refused_hosts.txt")


def test_more_bars_than_a_command_may_make_across_its_hosts(run, workdir, golden):
    """CATCHES: a rewrite that lets one `reinforce` make more than 20000 bars over all its hosts, or cuts them short
    instead of refusing."""
    (workdir / "floors.txt").write_text(
        "\n".join('floor {"boundary": [[0, 0], [27000, 0], [27000, 1000], [0, 1000]]}' for _ in range(21)) + "\n")
    hosts = list(range(HOST, HOST + 21))
    r = run(["run", "--script", "floors.txt", "--cmd",
             "reinforce " + json.dumps({"hosts": hosts, "cover": 20, "bottom": {"y": {"diameter": 8, "spacing": 28}}})])
    golden.check(_report(r), "too_many_bars_all.txt")


def test_reinforcing_again_replaces_its_bars_and_keeps_the_hand_drawn_ones(run, golden):
    """CATCHES: a rewrite whose second `reinforce` of a host keeps the bars of the first, removes a bar drawn by hand
    (one with no layer), does not report how many it removed, or whose bars do not go when their host is deleted and
    come back with undo."""
    spec = {"host": HOST, "cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 1500}}
    r = run(_args(BEAM, 'rebar {"points": [[50, 0, -400], [5950, 0, -400]], "diameter": 20, "host": 100002}',
                  "reinforce " + json.dumps(spec),
                  "reinforce " + json.dumps({**spec, "bottom": {"count": 2, "diameter": 20}}),
                  'elements {"category": "rebar"}', "undo", 'elements {"category": "rebar", "limit": 3}',
                  'delete {"ids": [100002]}', 'elements {"category": "rebar"}', "undo",
                  'elements {"category": "rebar", "limit": 2}'))
    golden.check(_report(r), "rearmed.txt")


def test_several_hosts_are_armed_alike_or_none_is(run, golden):
    """CATCHES: a rewrite whose `hosts` arms each listed host alike (each once), whose refusal for one host does not name
    it (`for the beam 100004`), or which arms the others when one refuses."""
    spec = {"hosts": [100002, 100003, 100002], "cover": 25, "bottom": {"count": 2, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 1000},
            "check": "NBR 6118", "aggressiveness": 2}
    four = {"hosts": [100002, 100003, 100004], "cover": 25, "bottom": {"count": 4, "diameter": 16}}
    r = run(_args(BEAM, 'beam {"points": [[0, 1000], [4000, 1000]]}', 'beam {"points": [[0, 3000], [4000, 3000]], "type": "Beam 150 x 400"}',
                  "reinforce " + json.dumps(spec), 'elements {"category": "rebar"}', "reinforce " + json.dumps(four)))
    golden.check(_report(r), "several_hosts.txt")


def _mcp(run, calls):
    """The replies of the MCP server to `execute` calls of (command, params), one after another on one model."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}]
    for n, (command, params) in enumerate(calls, start=2):
        msgs.append({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                     "params": {"name": "execute", "arguments": {"command": command, "params": params}}})
    r = run(["mcp"], input="".join(json.dumps(m) + "\n" for m in msgs))
    replies = [json.loads(line) for line in r.stdout.decode().splitlines()[1:]]
    out = [f"exit: {r.returncode}"]
    for (command, _), reply in zip(calls, replies):
        res = reply["result"]
        text = "".join(c["text"] for c in res["content"])
        if command == "elements" and not res.get("isError"):
            listed = json.loads(text)
            text = f"{listed['count']} elements: " + " ".join(f"{e['id']}:{e.get('layer') or '-'}" for e in listed["elements"])
        out.append(f"{command} error={res.get('isError', False)}: {text}")
    return normalize("\n".join(out) + "\n")


def test_a_refused_reinforce_arms_none_and_keeps_the_bars_it_had(run, golden):
    """CATCHES: a rewrite whose `reinforce` of several hosts arms the ones that fit when one refuses, removes the bars a
    host had before a refused command, or leaves an undo step for it."""
    two = {"hosts": [100002, 100003], "cover": 25, "bottom": {"count": 2, "diameter": 16}}
    three = {"hosts": [100002, 100003, 100004], "cover": 25, "bottom": {"count": 4, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 1000}}
    text = _mcp(run, [("beam", {"points": [[0, 0], [6000, 0]]}), ("beam", {"points": [[0, 1000], [4000, 1000]]}),
                      ("beam", {"points": [[0, 3000], [4000, 3000]], "type": "Beam 150 x 400"}),
                      ("reinforce", two), ("reinforce", three), ("elements", {"category": "rebar"}),
                      ("undo", {}), ("elements", {"category": "rebar"})])
    golden.check(text, "refused_arms_none.txt")


def test_presets_keep_a_kind_of_hosts_parameters(run, workdir, golden):
    """CATCHES: a rewrite whose `reinforcement_preset` does not keep, list, rename or delete a preset, whose `reinforce`
    with `preset` does not take its parameters and let the ones given replace them key by key, arms a host of another
    kind with it, or whose project file loses presets."""
    beam = {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 1500}}
    r = run(_args(BEAM, 'beam {"points": [[0, 1000], [4000, 1000]]}', COLUMN,
                  "reinforcement_preset " + json.dumps({"name": "V 20 x 50", "kind": "beam", "params": beam}),
                  'reinforcement_preset {"name": "P 30", "kind": "column", "params": {"cover": 30, "bars": {"diameter": 12.5}}}',
                  "reinforcement_preset",
                  'reinforce {"hosts": [100002, 100003], "preset": "V 20 x 50"}',
                  'reinforce {"host": 100002, "preset": "V 20 x 50", "stirrup": {"diameter": 6.3, "spacing": 2000}, "cover": 30}',
                  'reinforce {"host": 100004, "preset": "P 30", "bars": {"diameter": 16, "x": 3}}',
                  'reinforcement_preset {"name": "V 20 x 50", "rename": "Viga padrão"}',
                  'reinforcement_preset {"name": "Viga padrão", "params": {"cover": 20, "top": {"count": 2, "diameter": 10}}}',
                  'library {"kind": "reinforcement-preset"}',
                  'reinforce {"host": 100003, "preset": "Viga padrão"}',
                  SLAB, 'reinforcement_preset {"name": "Laje", "kind": "floor", "params": {"cover": 20, "bottom": {"y": {"diameter": 8, "spacing": 2000}}}}',
                  'reinforce {"host": 100035, "preset": "Laje", "grade": "CA-60"}',
                  'elements {"category": "rebar", "limit": 4, "offset": 10}'))
    golden.check(_report(r), "presets.txt")
    r = run(_args('reinforcement_preset {"name": "Sapata", "kind": "footing", "params": {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}}}}')
            + ["--save", "p.bimcraft"])
    assert r.returncode == 0, r.stderr
    saved = json.loads((workdir / "p.bimcraft").read_text())
    golden.check(normalize(json.dumps({k: saved[k] for k in saved if k in ("reinforcement",)}, indent=1, sort_keys=True) + "\n"
                           + json.dumps([v for v in saved["library"].values() if v["kind"] == "reinforcement-preset"], indent=1) + "\n"),
                 "presets_in_file.json")
    r = run(["run", "p.bimcraft", "--cmd", FOOTING, "--cmd", 'reinforce {"host": 100002, "preset": "Sapata"}',
             "--cmd", 'reinforcement_preset {"name": "Sapata", "delete": true}', "--cmd", "reinforcement_preset"])
    golden.check(_report(r), "presets_reopened.txt")


PRESET_REFUSALS = [
    'reinforcement_preset {"name": "A", "params": {"cover": 25}}',
    'reinforcement_preset {"name": "A", "kind": "wall", "params": {"cover": 25}}',
    'reinforcement_preset {"name": "A", "kind": "beam"}',
    'reinforcement_preset {"name": "A", "kind": "beam", "params": "x"}',
    'reinforcement_preset {"name": "A", "kind": "beam", "params": {"mesh": {}}}',
    'reinforcement_preset {"name": "A", "kind": "floor", "params": {"bars": {"diameter": 10}}}',
    'reinforcement_preset {"name": "A", "kind": "beam", "params": {"host": 100002}}',
    'reinforcement_preset {"name": "A", "kind": "beam", "params": {"preset": "B"}}',
    'reinforcement_preset {"name": "A", "kind": "beam", "params": {"cover": 25}, "colour": 1}',
    'reinforcement_preset {"name": "A", "kind": "beam", "params": {"cover": "' + "y" * 70000 + '"}}',
    'reinforcement_preset {"name": "A", "delete": true}',
    'reinforcement_preset {"name": "A", "rename": "B"}',
]


def test_preset_refusals(run, golden):
    """CATCHES: a rewrite that keeps a preset of no kind or of a kind that is not a host's, with no parameters, with a
    parameter its kind does not take (or `host`, or `preset`), too large, or that renames or deletes one that does not
    exist, or words these refusals differently."""
    parts = []
    for cmd in PRESET_REFUSALS:
        r = run(["run", "--cmd", cmd])
        parts.append(f"$ {cmd[:160]}\nexit: {r.returncode}\n{r.stderr.decode()}")
    r = run(_args('reinforcement_preset {"name": "A", "kind": "beam", "params": {"cover": 25}}',
                  'reinforcement_preset {"name": "B", "kind": "beam", "params": {"cover": 25}}',
                  'reinforcement_preset {"name": "A", "rename": "B"}'))
    parts.append(f"$ rename onto another\nexit: {r.returncode}\n{r.stderr.decode()}")
    r = run(_args(COLUMN, 'reinforcement_preset {"name": "V", "kind": "beam", "params": {"cover": 25, "bottom": {"count": 9, "diameter": 25}}}',
                  'reinforce {"host": 100002, "preset": "V"}'))
    parts.append(f"$ a beam preset on a column\nexit: {r.returncode}\n{r.stderr.decode()}")
    r = run(_args(BEAM, 'reinforcement_preset {"name": "V", "kind": "beam", "params": {"cover": 25, "bottom": {"count": 9, "diameter": 25}}}',
                  'reinforce {"host": 100002, "preset": "V"}'))
    parts.append(f"$ a preset that does not fit\nexit: {r.returncode}\n{r.stderr.decode()}")
    r = run(_args('wall {"points": [[0, 0], [4000, 0]]}', 'reinforcement_preset {"name": "L", "kind": "floor", "params": {"cover": 20}}',
                  'reinforce {"host": 100002, "preset": "L"}'))
    parts.append(f"$ a floor preset on a wall\nexit: {r.returncode}\n{r.stderr.decode()}")
    golden.check(normalize("".join(parts)), "preset_refusals.txt")


def test_too_many_presets(run, workdir, golden):
    """CATCHES: a rewrite that keeps more presets than the project holds, or counts an edit of one it has against it."""
    lines = [f'reinforcement_preset {{"name": "p{i}", "kind": "beam", "params": {{"cover": 25}}}}' for i in range(256)]
    (workdir / "presets.txt").write_text("\n".join(lines) + "\n")
    r = run(["run", "--script", "presets.txt", "--cmd", 'reinforcement_preset {"name": "p0", "params": {"cover": 30}}',
             "--cmd", 'reinforcement_preset {"name": "one too many", "kind": "beam", "params": {"cover": 25}}'])
    out = r.stdout.decode().splitlines()
    golden.check(normalize(f"exit: {r.returncode}\n{len(out)} replies\n{out[-1]}\n{r.stderr.decode()}"), "too_many_presets.txt")


CHECKED = {
    "beam_class_one_sound": (BEAM, {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "top": {"count": 2, "diameter": 12.5},
                                    "stirrup": {"diameter": 5, "spacing": 150}, "check": "NBR 6118", "aggressiveness": 1}),
    "beam_class_two_cover": (BEAM, {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "top": {"count": 2, "diameter": 12.5},
                                    "stirrup": {"diameter": 5, "spacing": 150}, "check": "nbr6118:2014", "aggressiveness": 2}),
    "beam_thin_stirrups_far_apart": (BEAM, {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 4, "spacing": 400},
                                            "check": "NBR 6118"}),
    "beam_thick_stirrups_little_steel": (BEAM, {"cover": 30, "bottom": {"count": 2, "diameter": 6.3}, "stirrup": {"diameter": 25, "spacing": 300},
                                                "check": "NBR 6118", "fck": 25}),
    "beam_too_much_steel": (BEAM, {"cover": 25, "bottom": {"count": 3, "diameter": 32}, "top": {"count": 3, "diameter": 32},
                                   "clearance": 20, "check": "NBR 6118"}),
    "beam_strong_concrete": (BEAM, {"cover": 25, "bottom": {"count": 2, "diameter": 16}, "check": "NBR 6118", "fck": 40}),
    "beam_deep_without_skin": ('beam {"points": [[0, 0], [6000, 0]], "type": "Deep"}',
                               {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 150}, "check": "NBR 6118"}),
    "beam_deep_with_sparse_skin": ('beam {"points": [[0, 0], [6000, 0]], "type": "Deep"}',
                                   {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 150},
                                    "skin": {"diameter": 5, "spacing": 300}, "check": "NBR 6118"}),
    "beam_deep_with_skin": ('beam {"points": [[0, 0], [6000, 0]], "type": "Deep"}',
                            {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 150},
                             "skin": {"diameter": 8, "spacing": 150}, "check": "NBR 6118"}),
    "beam_deep_with_far_skin": ('beam {"points": [[0, 0], [6000, 0]], "type": "Deep"}',
                                {"cover": 25, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 150},
                                 "skin": {"diameter": 12.5, "spacing": 350}, "check": "NBR 6118"}),
    "column_too_much_steel": (COLUMN, {"cover": 25, "check": "NBR 6118", "bars": {"diameter": 40, "x": 3, "y": 3},
                                       "stirrup": {"diameter": 10, "spacing": 150}}),
    "column_thin_and_sparse": (COLUMN, {"cover": 25, "check": "NBR 6118", "bars": {"diameter": 8, "x": 2, "y": 2},
                                        "stirrup": {"diameter": 4, "spacing": 300}}),
    "column_sound": (COLUMN, {"cover": 25, "check": "NBR 6118", "bars": {"diameter": 16, "x": 3, "y": 3}, "stirrup": {"diameter": 5, "spacing": 150}}),
    "column_thick_bars_far_apart": ('structural_column {"at": [0, 0], "type": "Concrete 200 x 500", "height": 3000}',
                                    {"cover": 25, "check": "NBR 6118", "aggressiveness": 3, "bars": {"diameter": 32, "x": 2, "y": 2}}),
    "column_round_few_bars": (ROUND_COLUMN, {"cover": 30, "check": "NBR 6118", "bars": {"diameter": 10, "count": 4}, "stirrup": {"diameter": 5, "spacing": 250}}),
    "footing_class_four": (FOOTING, {"cover": 40, "check": "NBR 6118", "aggressiveness": 4, "mesh": {"x": {"diameter": 10, "spacing": 150}}}),
    "floor_thick_bars_far_apart": (SLAB, {"cover": 20, "check": "NBR 6118", "aggressiveness": 4, "bottom": {"x": {"diameter": 32, "spacing": 300}}}),
    "floor_sound": (SLAB, {"cover": 25, "check": "NBR 6118", "bottom": {"x": {"diameter": 8, "spacing": 150}, "y": {"diameter": 8, "spacing": 150}}}),
}


@pytest.mark.parametrize("case", sorted(CHECKED))
def test_the_nbr_6118_check_adds_notes_and_refuses_nothing(run, golden, case):
    """CATCHES: a rewrite whose NBR 6118 check notes another limit than the reference's (Table 7.2's cover by class, the
    least and most steel, bar sizes and spacings of beams, columns and floors, stirrups, skin bars), words or rounds a
    note differently, notes what the reference does not, or refuses to make the bars."""
    host, spec = CHECKED[case]
    setup = (DEEP,) if "Deep" in host else ()
    r = run(_args(*setup, host, "reinforce " + json.dumps({"host": HOST, **spec})))
    golden.check(_report(r), f"checked_{case}.txt")


def test_rebar_drawn_by_hand(run, golden):
    """CATCHES: a rewrite whose `rebar` does not make a bar along its points (z over the level), close a hoop, lay a row
    of `count` bars `step` apart, take its host's level, default the grade to CA-50, or lists a bar with another length or
    weight (steel at 7850 kg/m³) or other fields."""
    r = run(_args(BEAM,
                  'rebar {"points": [[0, 0, 100], [1000, 0, 100]], "diameter": 10}',
                  'rebar {"points": [[0, 0, 0], [140, 0, 0], [140, 440, 0], [0, 440, 0]], "closed": true, "diameter": 8, "grade": "CA-60", "layer": "hoop"}',
                  'rebar {"points": [[50, -60, -440], [5950, -60, -440]], "diameter": 12.5, "host": 100002, "count": 3, "step": [0, 60, 0]}',
                  'rebar {"points": [[0, 0, 0], [0, 0, 2000]], "diameter": 20, "level": "Level 2"}',
                  'elements {"category": "rebar"}'))
    golden.check_run(r, "rebar_by_hand.txt")


REBAR_REFUSALS = [
    'rebar {"points": [[0, 0, 0]], "diameter": 10}',
    'rebar {"points": [[5, 5, 5], [5, 5, 5]], "diameter": 10}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]]}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 2}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 101}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "grade": "  "}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "count": 0, "step": [0, 50, 0]}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "count": 1001, "step": [0, 50, 0]}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "count": 3}',
    'rebar {"points": [' + ", ".join(f"[{k * 10}, 0, 0]" for k in range(11)) + '], "diameter": 10, "count": 1000, "step": [0, 50, 0]}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "count": 3, "step": [0, 50]}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "host": 999999}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "host": "x"}',
    'rebar {"points": [[0, 0], [1000, 0]], "diameter": 10}',
    'rebar {"diameter": 10}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "level": "Level 9"}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "closed": "yes"}',
    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": "thick"}',
]


def test_rebar_refusals(run, golden):
    """CATCHES: a rewrite that makes a bar of one point or no length, without a diameter or of one out of 3 to 100 mm, of
    a blank grade, of too few or many bars, a row without a step, on a host or level that does not exist, or words these
    refusals differently."""
    parts = []
    for cmd in REBAR_REFUSALS:
        r = run(["run", "--cmd", cmd])
        parts.append(f"$ {cmd[:200]}\nexit: {r.returncode}\n{r.stderr.decode()}")
    golden.check(normalize("".join(parts)), "rebar_refusals.txt")


def test_bar_schedules(run, golden):
    """CATCHES: a rewrite whose rebar schedule has other columns (Id, Level, Grade, Diameter, Length, Count, Weight,
    Host, and Layer available), or whose bar schedule grouped by grade, diameter and length counts or totals its bars
    differently."""
    spec = {"host": HOST, "cover": 25, "bottom": {"count": 3, "diameter": 16}, "top": {"count": 2, "diameter": 12.5},
            "stirrup": {"diameter": 5, "spacing": 300}}
    r = run(_args(BEAM, "reinforce " + json.dumps(spec),
                  'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10, "grade": "CA-60"}',
                  'schedule {"name": "Bars", "category": "rebar"}',
                  'schedule {"name": "Bar schedule", "category": "rebar", "fields": ["Grade", "Diameter", "Length", "Count", {"name": "Weight", "total": true}, "Layer"], "sort": ["Grade", "Diameter", "Length"], "grouped": true}',
                  'schedule {"name": "By layer", "category": "rebar", "fields": ["Layer", "Count"], "sort": ["Layer"], "grouped": true, "filters": [{"field": "Diameter", "op": "greater", "value": 5}]}'))
    golden.check_run(r, "bar_schedules.txt")


def test_plans_and_sections_draw_the_bars(run, workdir, golden):
    """CATCHES: a rewrite whose plan does not draw a floor's bars under the cut plane solid, a beam's overhead dashed,
    a column's standing bars as dots and its stirrups once, or still draws bars the view hides."""
    beam = {"host": 100003, "cover": 25, "bottom": {"count": 2, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 1000}}
    col = {"host": 100004, "cover": 25, "bars": {"diameter": 16, "x": 3, "y": 3}, "stirrup": {"diameter": 5, "spacing": 1000}}
    r = run(_args(SLAB, 'beam {"points": [[0, 5000], [6000, 5000]], "offset": 2800}',
                  'structural_column {"at": [8000, 1000], "type": "Concrete 300 x 300", "height": 3000}',
                  'reinforce {"host": 100002, "cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 500}}}',
                  "reinforce " + json.dumps(beam), "reinforce " + json.dumps(col),
                  'render {"view": "Level 1", "path": "bars.svg"}',
                  'graphics {"view": "Level 1", "hide": ["rebar"]}',
                  'render {"view": "Level 1", "path": "hidden.svg"}'))
    assert r.returncode == 0, r.stderr
    golden.check((workdir / "bars.svg").read_text(), "bars.svg")
    golden.check((workdir / "hidden.svg").read_text(), "bars_hidden.svg")


def test_ifc_writes_each_bar_aggregated_to_its_host(run, workdir, golden):
    """CATCHES: a rewrite whose IFC leaves out a bar, writes it other than as an IfcReinforcingBar (grade, diameter,
    cross-section, length; a swept disk along a polyline) aggregated to its host (or in its storey with none), or whose
    import does not read the bars and their host back."""
    spec = {"host": HOST, "cover": 25, "bottom": {"count": 2, "diameter": 16}, "stirrup": {"diameter": 5, "spacing": 3000}}
    make_project(run, workdir, "r.bimcraft", _args(BEAM, "reinforce " + json.dumps(spec),
                                                    'rebar {"points": [[0, 0, 0], [1000, 0, 0]], "diameter": 10}')[1:])
    assert run(["convert", "r.bimcraft", "r.ifc"]).returncode == 0
    golden.check(normalize((workdir / "r.ifc").read_text()), "rebar.ifc")
    r = run(["run", "r.ifc", "--cmd", 'elements {"category": "rebar"}', "--cmd", 'elements {"category": "beams"}'])
    golden.check(_report(r), "rebar_from_ifc.txt")


def test_a_project_file_keeps_the_bars_and_their_layers(run, workdir, golden):
    """CATCHES: a rewrite whose project file loses a bar's host (by GUID), layer, grade or path, or that reads them
    back differently."""
    spec = {"host": HOST, "cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 500}, "hook": 100}}
    r = run(_args(FOOTING, "reinforce " + json.dumps(spec)) + ["--save", "f.bimcraft"])
    assert r.returncode == 0, r.stderr
    d = json.loads((workdir / "f.bimcraft").read_text())
    bars = [v for v in d["elements"].values() if "Rebar" in v]
    golden.check(normalize(json.dumps(bars, indent=1, sort_keys=True) + "\n"), "saved_bars.json")
    r = run(["run", "f.bimcraft", "--cmd", "reinforce " + json.dumps({**spec, "mesh": {"y": {"diameter": 12.5, "spacing": 600}}}),
             "--cmd", 'elements {"category": "rebar"}'])
    golden.check(_report(r), "reopened_rearmed.txt")


def test_sections_draw_the_bars_they_cut(run, workdir, golden):
    """CATCHES: a rewrite whose section does not draw a bar it crosses as a dot over the host's poché and a bar in its
    plane as a strip along it, or draws the bars of a host it does not cut."""
    spec = {"host": HOST, "cover": 25, "bottom": {"count": 3, "diameter": 16}, "top": {"count": 2, "diameter": 12.5},
            "stirrup": {"diameter": 5, "spacing": 500}}
    r = run(_args(BEAM, "reinforce " + json.dumps(spec),
                  'section {"start": [3000, -1000], "end": [3000, 1000], "name": "Across"}',
                  'render {"view": "Across", "path": "across.png"}',
                  'section {"start": [-500, 0], "end": [6500, 0], "name": "Along"}',
                  'render {"view": "Along", "path": "along.png"}'))
    golden.check(_report(r), "sections.txt")
    golden.check(png_pixels((workdir / "across.png").read_bytes()) + png_pixels((workdir / "along.png").read_bytes()),
                 "sections_png.txt")


MODIFIED = [
    '{"id": 100003, "diameter": 200}',
    '{"id": 100003, "grade": " "}',
    '{"id": 100003, "path": [[0, 0, 0]]}',
    '{"id": 100003, "path": [[0, 0, 0], [0, 0, 0]]}',
    '{"id": 100003, "path": [[0, 0, 0], [2e9, 0, 0]]}',
    '{"id": 100003, "host": 100004}',
    '{"id": 100003, "layer": "' + "l" * 300 + '"}',
    '{"id": 100003, "diameter": 12, "grade": "CA-60", "layer": "x", "path": [[0, 0, 0], [500, 0, 0], [500, 500, 0]]}',
]


def test_a_bar_changed_with_modify_is_checked(run, golden):
    """CATCHES: a rewrite that lets `modify` give a bar a diameter out of 3 to 100 mm, a blank grade, a path of one point
    or of no length or past the model's reach, a host that is no beam, column, footing or floor, or a layer too long, or
    whose bar changed within bounds is listed with another length or weight."""
    parts = []
    for m in MODIFIED:
        r = run(_args(BEAM, 'rebar {"points": [[50, 0, -400], [5950, 0, -400]], "diameter": 20, "host": 100002}',
                      'wall {"points": [[0, 5000], [4000, 5000]]}', "modify " + m, 'elements {"category": "rebar"}'))
        parts.append(f"$ modify {m[:120]}\n" + _report(r))
    golden.check("".join(parts), "modified_bars.txt")
