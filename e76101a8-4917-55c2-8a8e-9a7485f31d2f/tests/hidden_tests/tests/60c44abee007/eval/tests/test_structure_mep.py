"""Structure, MEP and the engineering calculators: columns, footings, beams, the runs of every discipline, bars and
`reinforce`, stairs, ramps and railings, falls, the electrical settings, and the stateless sizing commands (`circuit`,
`conduit_fill`, `drain_size`, `vent_size`, `hydrant_size`, `water_size`, `storm_size`, `load_points`)."""

import json

import pytest


def each(sc, command, cases, pre=()):
    """One `run --cmd` per case, so a refusal is its own transcript entry and never stops the next case."""
    for params in cases:
        sc.cmds(f"{command} {json.dumps(params, ensure_ascii=False)}", pre=pre)


def cmd(command, params=None):
    return command if params is None else f"{command} {json.dumps(params, ensure_ascii=False)}"


# ---------------------------------------------------------------------------
# circuit (NBR 5410)
# ---------------------------------------------------------------------------


def test_circuit_sizes_sections_breakers_and_drops(sc):
    """CATCHES: wrong design currents for one phase, two phases or three, a lighting circuit not allowed down to 1.5 mm², the
    voltage drop over `length` not growing the section, `apparent` VA treated as W, a chosen section or breaker shrunk, or
    the reduced neutral and protective conductor of Tabelas 48 and 58 written wrong in `conductors`."""
    each(sc, "circuit", [
        {"load": 2000},
        {"load": 1200, "use": "lighting"},
        {"load": 1200, "use": "lighting", "length": 50000},
        {"load": 5000, "apparent": True, "phases": "FF"},
        {"load": 9000, "phases": "FF", "system": "220/380", "length": 30000},
        {"load": 30000, "phases": "3F", "system": "230/400"},
        {"load": 3000, "section": 6, "breaker": 32, "length": 20000},
        {"load": 3000, "length": 200000, "drop_limit": 2},
        {"load": 200000, "phases": "3FN", "reduced_neutral": True, "system": "220/380", "length": 100000, "method": "3",
         "power_factor": 0.8},
        {"load": 60000, "phases": "3FN", "reduced_neutral": True, "demand": 0.7, "power_factor": 0.92},
        {"load": 20000, "phases": "3FN", "method": "61A", "grouped": 3, "spacing": 250, "soil": 2, "ambient": 25,
         "insulation": "epr", "conductor": "rigid", "section": 10, "breaker": 40, "reduced_neutral": True,
         "power_factor": 0.85, "demand": 0.8},
    ])
    assert sc.transcript() == sc.golden()


def test_circuit_installation_methods_temperature_and_grouping(sc):
    """CATCHES: the wrong column of Tabelas 36/37 for a method, wrong grouping factors (bundled, a layer, a ceiling, the tail
    rows past 8 circuits, buried conduits by their spacing), wrong temperature factors in air or soil, or EPR read from the
    PVC table."""
    base = {"load": 30000, "phases": "3F"}
    each(sc, "circuit", [
        {**base, "method": m} for m in ["1", "2", "4", "5", "6", "8", "11", "11A", "61", "61A"]
    ] + [
        {**base, "method": "11", "grouped": 4},
        {**base, "method": "11", "grouped": 4, "bundle": True},
        {**base, "method": "11A", "grouped": 12},
        {**base, "method": "11", "grouped": 10},
        {**base, "method": "7", "grouped": 25},
        {**base, "method": "7", "grouped": 3, "ambient": 45},
        {**base, "method": "7", "grouped": 3, "ambient": 45, "insulation": "epr"},
        {**base, "method": "61", "grouped": 3, "spacing": 500},
        {**base, "method": "61", "grouped": 2, "spacing": 0, "ambient": 35, "soil": 1.5},
        {**base, "method": "61A", "grouped": 6, "spacing": 1000, "soil": 3},
    ])
    assert sc.transcript() == sc.golden()


def test_circuit_refusals(sc):
    """CATCHES: a circuit that sizes something for a missing or zero load, a section or breaker off the standard's lists,
    an unknown method, phases or parameter, a factor outside its range, or a load no conductor carries, instead of the
    refusal that says what to change."""
    each(sc, "circuit", [
        {},
        {"load": 0},
        {"load": -5},
        {"load": "big"},
        {"load": 5000000},
        {"load": 1000, "method": "9"},
        {"load": 1000, "section": 3},
        {"load": 1000, "breaker": 17},
        {"load": 1000, "bogus": 1},
        {"load": 1000, "phases": "2F"},
        {"load": 1000, "system": "110/220"},
        {"load": 1000, "demand": 2},
        {"load": 1000, "power_factor": 0},
        {"load": 1000, "insulation": "rubber"},
        {"load": 1000, "conductor": "solid"},
        {"load": 1000, "use": "heating"},
        {"load": 1000, "grouped": 0},
        {"load": 50000, "phases": "3FN", "method": "61", "grouped": 8, "spacing": 500},
        {"load": 50000, "phases": "3FN", "method": "61", "soil": 5},
        {"load": 50000, "phases": "3FN", "method": "61", "ambient": 5},
        {"load": 50000, "phases": "3FN", "method": "1", "ambient": 75},
        {"load": 1000, "apparent": "yes"},
        [1, 2],
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# conduit_fill
# ---------------------------------------------------------------------------


def test_conduit_fill_smallest_size_and_fill_of_a_size(sc):
    """CATCHES: the wrong conductors of a circuit (a neutral for FN and 3FN only, a reduced neutral, the protective
    conductor of Tabela 58), wrong fill percentages or limits, the wrong smallest size of each family, or a section the
    catalogue lacks guessed instead of left pending."""
    each(sc, "conduit_fill", [
        {"section": 2.5},
        {"section": 2.5, "size": '3/4"'},
        {"section": 2.5, "circuits": 7, "size": '1/2"'},
        {"section": 6, "phases": "3FN", "circuits": 3, "family": "steel-heavy"},
        {"section": 50, "phases": "3FN", "reduced_neutral": True, "family": "pvc-solder"},
        {"section": 16, "phases": "FF", "circuits": 2, "family": "steel-rir", "size": '1"'},
        {"section": 10, "phases": "3F", "family": "pvc-thread", "size": '1.1/4"'},
        {"section": 1.5, "circuits": 4, "family": "pvc-solder", "size": "DN25"},
        {"section": 300},
        {"section": 240, "phases": "3FN", "circuits": 10},
    ])
    assert sc.transcript() == sc.golden()


def test_conduit_fill_refusals(sc):
    """CATCHES: a conduit fill computed for no section, an unknown family or size mark, a bad circuit count or an unknown
    parameter, instead of a refusal listing what is allowed."""
    each(sc, "conduit_fill", [
        {},
        {"section": 0},
        {"section": 2.5, "family": "copper"},
        {"section": 2.5, "size": '9"'},
        {"section": 2.5, "family": "steel-rir", "size": '1/3"'},
        {"section": 2.5, "colour": 1},
        {"section": 2.5, "circuits": 0},
        {"section": 2.5, "phases": "1F"},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# drain_size and vent_size (NBR 8160)
# ---------------------------------------------------------------------------


def test_drain_size_branches_mains_and_stacks(sc):
    """CATCHES: wrong fixture units or fixture DNs of Tabela 3, a branch read from the building drain's table (or the
    other way round), DN 100 and 150 not left out of a building drain at 0.5 %, a stack not sized by its floors, or
    `min_dn` not keeping the drain at least as large as what flows into it."""
    each(sc, "drain_size", [
        {"units": 5},
        {"units": 30},
        {"fixtures": {"wc": 1, "lav": 1, "shower": 1}},
        {"fixtures": {"lav": 2, "sink": 1}},
        {"fixtures": {"wc": 0, "lav": 1}},
        {"fixtures": {"laundry": 2, "shower": 3}},
        {"units": 40, "role": "main"},
        {"units": 40, "role": "main", "slope": 0.005},
        {"units": 2000, "role": "main", "slope": 0.04},
        {"units": 500, "role": "main", "slope": 0.02},
        {"units": 300, "role": "stack", "floors": 2},
        {"units": 300, "role": "stack", "floors": 5},
        {"units": 30, "role": "stack"},
        {"units": 3, "min_dn": 75},
        {"units": 10, "fixtures": {"wc": 2}},
    ])
    assert sc.transcript() == sc.golden()


def test_drain_size_refusals(sc):
    """CATCHES: a drain sized from nothing, from an unknown fixture, a fractional or negative count, a list where counts
    are asked, an unknown role, or a load past the tables, instead of a refusal that names the most the tables carry."""
    each(sc, "drain_size", [
        {},
        {"units": 0},
        {"fixtures": {"bidet": 1}},
        {"fixtures": {"wc": 1.5}},
        {"fixtures": {"wc": -1}},
        {"fixtures": [1]},
        {"units": 5, "role": "riser"},
        {"units": 99999999},
        {"units": 100000, "role": "main", "slope": 0.005},
        {"units": 5000, "role": "branch"},
        {"units": 5, "pipes": 2},
    ])
    assert sc.transcript() == sc.golden()


def test_vent_size_branch_vents_stacks_and_traps(sc):
    """CATCHES: a branch vent of Tabela 8 sized without regard to a water closet, a vent stack of Tabela 2 not reporting
    its longest length, a trap's distance of Tabela 1 wrong, or a refusal missing for an off-table DN, a missing
    length, too many units or an unknown parameter."""
    each(sc, "vent_size", [
        {"units": 10},
        {"units": 10, "wc": True},
        {"units": 30, "wc": True},
        {"units": 2, "trap_dn": 40},
        {"units": 20, "stack_dn": 100, "length": 30000},
        {"units": 200, "stack_dn": 100, "length": 60000, "trap_dn": 50},
        {"units": 600, "stack_dn": 150, "length": 90000, "trap_dn": 75},
        {"units": 20, "trap_dn": 100},
        {"units": 100, "wc": True},
        {"units": 20, "stack_dn": 99, "length": 3000},
        {"units": 20, "stack_dn": 100},
        {"units": 20, "trap_dn": 60},
        {"units": 0},
        {"units": 5000, "stack_dn": 75, "length": 3000},
        {"units": 10, "foo": 1},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# hydrant_size (IT 22/2025)
# ---------------------------------------------------------------------------


def test_hydrant_size_system_type_and_reserve_by_occupation(sc):
    """CATCHES: the wrong system type or fire reserve of Tabela 3 for a column and area band (the band edges inclusive
    above), a type 4 system not asking for its nozzle only when a pipe is given, or a type that contradicts the column and
    area accepted."""
    each(sc, "hydrant_size", [
        {"column": 1, "area": 500},
        {"column": 1, "area": 2500},
        {"column": 1, "area": 2501},
        {"column": 2, "area": 20000},
        {"column": 3, "area": 5000},
        {"column": 3, "area": 60000},
        {"column": 4, "area": 2500},
        {"column": 4, "area": 3000, "type": "4-65", "inside": 80, "nominal": 80},
        {"column": 5, "area": 50000},
        {"column": 5, "area": 9000, "hydrants": 3},
        {"column": 4, "area": 2501, "inside": 80},
        {"column": 4, "area": 3000, "type": "3"},
        {"column": 1, "area": 500, "type": "5"},
    ])
    assert sc.transcript() == sc.golden()


def test_hydrant_size_pipe_speed_head_loss_and_size(sc):
    """CATCHES: a design flow not of the two most unfavourable jets, the wrong Hazen-Williams C for a material, the head
    loss or speed computed wrong, the rise (up or down) left out of `need_mca`, or `size_ok` not following the DN 65 (DN 50
    for types 1 and 2) minimum."""
    each(sc, "hydrant_size", [
        {"type": "2"},
        {"type": "1", "hydrants": 1},
        {"type": "5", "hydrants": 3},
        {"type": "2", "region": "SP"},
        {"column": 2, "area": 20000, "inside": 65},
        {"type": "4-65", "inside": 65, "length": 30000},
        {"type": "3", "inside": 63, "length": 50000, "rise": 12000, "material": "steel-wet", "nominal": 65},
        {"type": "5", "inside": 100, "length": 80000, "rise": -3000, "material": "pvc", "nominal": 50},
        {"type": "2", "inside": 30, "length": 10000, "material": "copper"},
        {"type": "4-40", "inside": 50, "material": "pex", "nominal": 50},
        {"type": "1", "inside": 40, "length": 25000, "rise": 9000, "nominal": 50},
    ])
    assert sc.transcript() == sc.golden()


def test_hydrant_size_refusals(sc):
    """CATCHES: a hydrant sizing that runs without a type or occupation, with half of column and area, a column that is
    not a whole number from 1 to 5, a `nominal` without `inside`, an unknown type, region, material or parameter."""
    each(sc, "hydrant_size", [
        {},
        {"column": 1},
        {"area": 100},
        {"column": 2.5, "area": 100},
        {"column": 6, "area": 100},
        {"column": 1, "area": 0},
        {"type": "2", "nominal": 65},
        {"type": "6"},
        {"type": "2", "region": "RJ"},
        {"type": "2", "hydrants": 1.5},
        {"type": "2", "inside": 50, "material": "iron"},
        {"type": "2", "foo": 1},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# water_size (NBR 5626)
# ---------------------------------------------------------------------------


def test_water_size_flows_dns_losses_and_pressure(sc):
    """CATCHES: the weights method (0.3 √ΣP, capped by the fixtures' own flows) confused with the sum, the wrong smallest
    DN for 3 m/s, the equivalent lengths of fittings not added to the length, a wrong Darcy-Weisbach loss, or the pressure
    left at the end and `ok` not taking the rise and the 10 kPa least into account."""
    each(sc, "water_size", [
        {"fixtures": {"wc": 1, "lav": 1, "shower": 1, "sink": 1}},
        {"fixtures": {"wc": 1, "lav": 1, "shower": 1, "sink": 1}, "method": "sum"},
        {"fixtures": {"wc": 2, "lav": 2, "shower": 2, "sink": 1, "laundry": 1}, "method": "sum"},
        {"fixtures": {"wc": 12, "lav": 12, "shower": 12, "sink": 6, "laundry": 6}},
        {"fixtures": {"lav": 1}},
        {"flow": 0.5, "length": 12000, "fittings": {"elbow90": 4, "tee_side": 1, "gate": 1}, "pressure": 150, "rise": 3000},
        {"flow": 0.5, "dn": 20, "length": 12000},
        {"flow": 0.5, "dn": 25, "length": 12000, "fittings": {"elbow90": 4, "tee_side": 1, "gate": 1}},
        {"flow": 2.0, "dn": 110, "length": 50000, "fittings": {"elbow45": 2, "tee_through": 3, "globe": 1, "check": 1},
         "pressure": 100, "rise": 6000},
        {"flow": 1.2, "dn": 20},
        {"flow": 0.3, "pressure": 5},
        {"flow": 0.3, "pressure": 40, "rise": -2000, "length": 5000},
        {"flow": 0.01, "dn": 25, "length": 10000},
    ])
    assert sc.transcript() == sc.golden()


def test_water_size_refusals(sc):
    """CATCHES: water sizing that accepts both `flow` and `fixtures`, an unknown fixture, fitting or method, a negative
    count, a DN that is not PVC soldável, or a flow no DN keeps under 3 m/s, instead of refusing."""
    each(sc, "water_size", [
        {},
        {"flow": 50},
        {"flow": 0.3, "fixtures": {"wc": 1}},
        {"fixtures": {"wc": 1, "bath": 1}},
        {"fixtures": {"wc": -1}},
        {"fixtures": 3},
        {"flow": 0.3, "dn": 22},
        {"flow": 0.3, "fittings": {"valve": 1}},
        {"flow": 0.3, "fittings": {"elbow90": 0.5}},
        {"flow": 0.3, "fittings": [1]},
        {"flow": 0.3, "method": "peak"},
        {"flow": 0.3, "colour": "blue"},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# storm_size (NBR 10844)
# ---------------------------------------------------------------------------


def test_storm_size_downpipes(sc):
    """CATCHES: the flow Q = I·A/60 at the 150 mm/h default or a given rainfall computed wrong, the abacuses of Figure 3
    read wrong for the gutter depth, the length and an edge or funnel outlet, or the 70 mm least not applied."""
    each(sc, "storm_size", [
        {"kind": "downpipe", "area": 80, "gutter": 60, "length": 3000},
        {"kind": "downpipe", "area": 300, "rainfall": 170, "gutter": 80, "length": 5000, "outlet": "funnel"},
        {"kind": "downpipe", "area": 300, "rainfall": 170, "gutter": 80, "length": 5000, "outlet": "edge"},
        {"kind": "downpipe", "flow": 1500, "gutter": 100, "length": 1000},
        {"kind": "downpipe", "flow": 1200, "gutter": 75, "length": 8000, "outlet": "funnel"},
        {"kind": "downpipe", "flow": 600, "gutter": 50, "length": 300},
    ])
    assert sc.transcript() == sc.golden()


def test_storm_size_horizontal_drains(sc):
    """CATCHES: Manning at two thirds full with n 0.011 computed wrong, or `carries_lpm` and `ok` of a given inside
    diameter missing or wrong."""
    each(sc, "storm_size", [
        {"kind": "horizontal", "area": 90, "slope": 0.01},
        {"kind": "horizontal", "area": 400, "rainfall": 180, "slope": 0.02, "inside": 100},
        {"kind": "horizontal", "area": 400, "rainfall": 180, "slope": 0.02, "inside": 150},
        {"kind": "horizontal", "flow": 900, "slope": 0.005, "inside": 75},
        {"kind": "horizontal", "flow": 300, "slope": 0.04},
    ])
    assert sc.transcript() == sc.golden()


def test_storm_size_refusals(sc):
    """CATCHES: storm sizing that ignores a key of the other kind, takes both `flow` and `area`, uses the default rainfall
    for a roof over 100 m², runs without kind, slope, gutter or length, or reads the abacuses off their range."""
    each(sc, "storm_size", [
        {"area": 50},
        {"kind": "vertical", "area": 50},
        {"kind": "downpipe", "flow": 20000, "gutter": 50, "length": 2000},
        {"kind": "downpipe", "flow": 200, "gutter": 40, "length": 2000},
        {"kind": "downpipe", "flow": 200, "gutter": 60, "length": 200},
        {"kind": "downpipe", "flow": 200, "length": 2000},
        {"kind": "downpipe", "flow": 200, "gutter": 60},
        {"kind": "downpipe", "flow": 200, "gutter": 60, "length": 2000, "slope": 0.01},
        {"kind": "downpipe", "flow": 200, "gutter": 60, "length": 2000, "outlet": "pipe"},
        {"kind": "horizontal", "flow": 900, "slope": 0.004},
        {"kind": "horizontal", "flow": 900},
        {"kind": "horizontal", "flow": 900, "slope": 0.01, "gutter": 50},
        {"kind": "horizontal", "flow": 900, "area": 10, "slope": 0.01},
        {"kind": "horizontal", "flow": 900, "rainfall": 100, "slope": 0.01},
        {"kind": "horizontal", "area": 500, "slope": 0.01},
        {"kind": "horizontal", "slope": 0.01},
        {"kind": "horizontal", "flow": 900, "slope": 0.01, "foo": 2},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# load_points (NBR 5410 9.5.2)
# ---------------------------------------------------------------------------

DWELLING = [
    {"name": "Sala", "area": 18.5, "perimeter": 17600},
    {"name": "Cozinha", "area": 9.2, "perimeter": 12400},
    {"name": "Banheiro", "area": 3.6, "perimeter": 7800},
    {"name": "Dormitório 1", "area": 11, "perimeter": 13400},
    {"name": "Área de serviço", "area": 4.5, "perimeter": 8600},
    {"name": "Varanda", "area": 6, "perimeter": 10000},
    {"name": "Hall", "area": 3, "perimeter": 7000},
    {"name": "Escritório", "area": 9, "perimeter": 12000, "kind": "dry"},
    {"name": "Lavanderia", "area": 6.5, "perimeter": 10400},
    {"name": "Copa", "area": 7, "perimeter": 10600},
    {"name": "Bedroom", "area": 30, "perimeter": 22000},
    {"name": "Storage", "area": 12, "perimeter": 14000, "kind": "other"},
    {"name": "Lavabo Íntimo", "area": 2.5, "perimeter": 6400},
    {"name": "Área de Serviço Única", "area": 5, "perimeter": 9000},
    {"name": "Suíte", "area": 14, "perimeter": 15000},
    {"name": "Cozinha Gourmet Pública", "area": 20, "perimeter": 18000},
    {"name": "Varanda Técnica", "area": 4, "perimeter": 8000},
]


def test_load_points_of_given_rooms_by_kind(sc):
    """CATCHES: a room's kind not read from its Portuguese or English name, a `kind` given not taking precedence, the
    lighting load (100 VA to 6 m², 60 VA more each whole 4 m²) or the outlets by perimeter or area wrong for a kind, the
    600 VA of the first three points of a wet room, the counter outlets of a kitchen or pantry, or the note on an
    unnamed kind missing."""
    each(sc, "load_points", [{"rooms": DWELLING}])
    assert sc.transcript() == sc.golden()


def test_load_points_points_given_and_the_alternative(sc):
    """CATCHES: the points a room has not replacing the least it needs, `ok` false not reported when a room has too few,
    or the alternative (600 VA for the first two points of each wet room) applied when not asked, when not possible, or
    not applied when asked."""
    wet = [
        {"name": "Kitchen", "area": 14, "perimeter": 15000, "points": 3},
        {"name": "Laundry", "area": 8, "perimeter": 12000, "points": 6},
        {"name": "Bathroom", "area": 5, "perimeter": 9000, "points": 2},
    ]
    each(sc, "load_points", [
        {"rooms": wet, "alternative": True},
        {"rooms": wet, "alternative": False},
        {"rooms": wet[2:], "alternative": True},
        {"rooms": [{"name": "Living", "area": 20, "perimeter": 18000, "points": 0}]},
        {"rooms": []},
    ])
    assert sc.transcript() == sc.golden()


def test_load_points_of_the_model_rooms(sc):
    """CATCHES: load_points without `rooms` not measuring the sample house's rooms inside the walls' finish, or a room no
    walls enclose not listed in `skipped` with why."""
    sc.run(["run", "--sample", "--cmd", "load_points {}"])
    sc.cmds(
        cmd("wall", {"points": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]], "closed": True}),
        cmd("room", {"point": [2500, 2000], "name": "Banheiro"}),
        cmd("room", {"point": [20000, 20000], "name": "Varanda"}),
        "load_points {}",
    )
    assert sc.transcript() == sc.golden()


def test_load_points_refusals(sc):
    """CATCHES: load_points accepting a room without area or perimeter, an unknown kind or key, negative points, rooms
    that are not a list of objects, or an unknown top-level parameter."""
    each(sc, "load_points", [
        {"rooms": [{"name": "X", "area": 7}]},
        {"rooms": [{"name": "X", "perimeter": 7000}]},
        {"rooms": [{"name": "X", "area": 7, "perimeter": 100, "kind": "garage"}]},
        {"rooms": [{"name": "X", "area": 7, "perimeter": 100, "points": -1}]},
        {"rooms": [{"name": "X", "area": 7, "perimeter": 100, "points": 2.5}]},
        {"rooms": [{"name": "X", "area": 7, "perimeter": 100, "colour": 1}]},
        {"rooms": [{"name": "X", "area": -7, "perimeter": 100}]},
        {"rooms": "none"},
        {"rooms": [5]},
        {"foo": 1},
        {"alternative": "yes"},
    ])
    assert sc.transcript() == sc.golden()


def test_sizing_commands_change_nothing(sc):
    """CATCHES: a sizing command that adds an undo step, an element or a library entry to the project: after all of them
    the history is empty, undo has nothing to take back, and the saved project holds what a fresh one does."""
    sizing = [
        cmd("circuit", {"load": 2000}),
        cmd("conduit_fill", {"section": 2.5}),
        cmd("drain_size", {"units": 5}),
        cmd("vent_size", {"units": 10}),
        cmd("hydrant_size", {"type": "2"}),
        cmd("water_size", {"flow": 0.3}),
        cmd("storm_size", {"kind": "horizontal", "area": 90, "slope": 0.01}),
        cmd("load_points", {"rooms": [{"name": "Sala", "area": 10, "perimeter": 13000}]}),
    ]
    p = sc.run(["run", *sum((["--cmd", c] for c in sizing), []), "--cmd", "elements {}", "--save", "after.bimcraft"],
               show=False)
    sc.note(f"exit {p.returncode}; last two lines: {p.stdout.decode().splitlines()[-2:]}")
    sc.cmds(*sizing[:3], "undo {}")
    sc.run(["run", "--save", "fresh.bimcraft"], show=False)
    after = (sc.workdir / "after.bimcraft").read_text()
    fresh = (sc.workdir / "fresh.bimcraft").read_text()
    import re as _re

    strip = lambda t: _re.sub(r'"uid": \d+', '"uid": 0', _re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "G", t))
    sc.note(f"saved project equals a fresh one: {strip(after) == strip(fresh)}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Electrical settings: voltage, distribution_system, wire_type
# ---------------------------------------------------------------------------


def test_voltages_listed_made_edited_renamed_and_deleted(sc):
    """CATCHES: a new voltage's band not 10 % either way unless given, a rename that loses the band or the systems not
    following a renamed voltage, a deleted voltage still listed, or the starter voltages listed wrong."""
    sc.cmds(
        "voltage {}",
        cmd("voltage", {"name": "110 V", "nominal": 110}),
        cmd("voltage", {"name": "24 V", "nominal": 24, "min": 20, "max": 28}),
        cmd("voltage", {"name": "110 V", "rename": "115 V", "nominal": 115}),
        cmd("voltage", {"name": "24 V", "delete": True}),
        cmd("voltage", {"name": "127 V", "rename": "127 V AC"}),
        "voltage {}",
        "distribution_system {}",
        cmd("library", {"kind": "voltage"}),
    )
    assert sc.transcript() == sc.golden()


def test_voltage_refusals(sc):
    """CATCHES: deleting a voltage a distribution system supplies, a new voltage without a nominal, a band that does not
    hold the nominal, a negative nominal, a rename onto a taken name, or deleting a voltage that isn't there."""
    each(sc, "voltage", [
        {"name": "220 V", "delete": True},
        {"name": "9 V"},
        {"name": "9 V", "nominal": 9, "min": 10},
        {"name": "9 V", "nominal": 9, "max": 8},
        {"name": "9 V", "nominal": -9},
        {"name": "127 V", "rename": "220 V"},
        {"name": "nope", "delete": True},
        {"name": "9 V", "nominal": 9, "colour": 1},
        {"name": "  ", "nominal": 9},
        {"name": "9 V", "rename": "12 V"},
    ])
    assert sc.transcript() == sc.golden()


def test_distribution_systems_made_renamed_and_deleted(sc):
    """CATCHES: a distribution system's voltages, phases, wires or earthing stored wrong, "" not taking a voltage away, a
    renamed voltage not followed by the system that names it, or a deleted system still listed."""
    sc.cmds(
        cmd("voltage", {"name": "115 V", "nominal": 115}),
        cmd("distribution_system", {"name": "115 V mono", "phases": 1, "wires": 2, "l_n": "115 V", "ground": "TT"}),
        cmd("voltage", {"name": "115 V", "rename": "117 V"}),
        cmd("distribution_system", {"name": "115 V mono"}),
        cmd("distribution_system", {"name": "115 V mono", "rename": "Mono", "l_g": "117 V"}),
        cmd("distribution_system", {"name": "X", "phases": 2, "wires": 3, "l_l": "220 V", "l_n": "127 V", "ground": "IT"}),
        cmd("distribution_system", {"name": "Delta", "phases": 3, "wires": 3, "l_l": "380 V"}),
        cmd("distribution_system", {"name": "127/220 V", "l_g": ""}),
        cmd("distribution_system", {"name": "230/400 V", "delete": True}),
        "distribution_system {}",
    )
    assert sc.transcript() == sc.golden()


def test_distribution_system_refusals(sc):
    """CATCHES: a system accepted with three phases whose line voltage is not about 1.73 times the phase voltage, naming
    a voltage the project lacks (the refusal lists those it has), with phases or wires out of range, an unknown earthing,
    no voltage at all, or an unknown parameter."""
    each(sc, "distribution_system", [
        {"name": "X", "phases": 3, "wires": 4, "l_l": "400 V", "l_n": "127 V"},
        {"name": "X", "phases": 1, "wires": 2, "l_n": "999 V"},
        {"name": "X", "phases": 4, "wires": 2, "l_n": "127 V"},
        {"name": "X", "phases": 3, "wires": 2, "l_l": "380 V"},
        {"name": "X", "phases": 1, "wires": 2, "l_n": "127 V", "ground": "TN"},
        {"name": "X", "phases": 1, "wires": 2},
        {"name": "X", "phases": 2, "wires": 3, "l_n": "127 V"},
        {"name": "Y", "rename": "Z"},
        {"name": "   ", "phases": 1, "wires": 2, "l_n": "127 V"},
        {"name": "nope", "delete": True},
        {"name": "127/220 V", "rename": "220/380 V"},
        {"name": "X", "colour": 1},
    ])
    assert sc.transcript() == sc.golden()


def test_wire_types_made_edited_renamed_and_deleted(sc):
    """CATCHES: a wire type's table not replaced by `sizes`, a label lost, a rename that keeps the old name listed, a
    delete that leaves it, or an empty `name` not listing every wire type."""
    sc.cmds(
        cmd("wire_type", {"name": "Al XLPE 90", "material": "aluminium", "temperature": 90, "insulation": "XLPE",
                          "note": "maker table", "sizes": [{"section": 16, "ampacity": 68},
                                                           {"section": 25, "ampacity": 89, "label": "25 mm²"}]}),
        cmd("wire_type", {"name": "Al XLPE 90", "sizes": [{"section": 10, "ampacity": 50}, {"section": 16, "ampacity": 50}]}),
        cmd("wire_type", {"name": "Cu PVC 70 °C", "rename": "Cobre PVC", "temperature": 70}),
        cmd("wire_type", {"name": "Cu THW 75 °C", "delete": True}),
        cmd("wire_type", {"name": ""}),
    )
    assert sc.transcript() == sc.golden()


def test_wire_type_refusals(sc):
    """CATCHES: a wire type accepted with a table out of order, a smaller ampacity for a larger section, a section or
    ampacity out of range, an empty table, an unknown material or row key, a blank insulation, a temperature out of
    range, or a new one missing its material, temperature, insulation or sizes."""
    name = "Cu PVC 70 °C"
    each(sc, "wire_type", [
        {"name": name, "sizes": [{"section": 25, "ampacity": 89}, {"section": 16, "ampacity": 68}]},
        {"name": name, "sizes": [{"section": 1, "ampacity": 20}, {"section": 2, "ampacity": 10}]},
        {"name": name, "sizes": [{"section": 10, "ampacity": 50}, {"section": 10, "ampacity": 50}]},
        {"name": name, "sizes": [{"section": -1, "ampacity": 10}]},
        {"name": name, "sizes": [{"section": 1, "ampacity": 0}]},
        {"name": name, "sizes": []},
        {"name": name, "sizes": [{"section": 1, "ampacity": 10, "x": 1}]},
        {"name": name, "material": "gold"},
        {"name": name, "temperature": 500},
        {"name": name, "insulation": ""},
        {"name": name, "note": "n" * 257},
        {"name": name, "sizes": [{"section": 1, "ampacity": 10, "label": "L" * 257}]},
        {"name": name, "rename": "Cu THHN 90 °C"},
        {"name": "W"},
        {"name": "W", "material": "copper"},
        {"name": "W", "material": "copper", "temperature": 70},
        {"name": "W", "material": "copper", "temperature": 60, "insulation": "Rubber"},
        {"name": "nope", "delete": True},
        {"name": "nope", "rename": "yes"},
        {"name": name, "sizes": [{"section": 1 + i, "ampacity": 10 + i} for i in range(65)]},
    ])
    assert sc.transcript() == sc.golden()


def test_electrical_settings_survive_save_and_open(sc):
    """CATCHES: voltages, distribution systems or wire types left out of the project file, or read back changed, so that
    `inspect` of the reopened project differs from what was made."""
    sc.cmds(
        cmd("voltage", {"name": "24 V", "nominal": 24, "min": 21, "max": 27}),
        cmd("distribution_system", {"name": "SELV", "phases": 1, "wires": 2, "l_n": "24 V", "ground": "IT"}),
        cmd("wire_type", {"name": "Flex 24", "material": "copper", "temperature": 60, "insulation": "Silicone",
                          "sizes": [{"section": 0.5, "ampacity": 3}, {"section": 1, "ampacity": 6, "label": "18 AWG"}]}),
        post=["--save", "selv.bimcraft"],
    )
    p = sc.run(["run", "selv.bimcraft", "--cmd", "inspect {}"], show=False)
    lines = p.stdout.decode().splitlines()
    inspect = json.loads(lines[-1])
    sc.note(f"exit {p.returncode}")
    sc.note(json.dumps({k: inspect[k] for k in ("voltages", "distribution_systems")}, ensure_ascii=False, sort_keys=True))
    sc.note(json.dumps(inspect["wire_types"]["Flex 24"], ensure_ascii=False, sort_keys=True))
    sc.note(json.dumps(sorted(inspect["wire_types"]), ensure_ascii=False))
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Columns, structural columns and footings
# ---------------------------------------------------------------------------


def test_columns_structural_columns_and_footings(sc):
    """CATCHES: a column not running up to the next level (or to `top_level`, or `height` mm), its `angle`,
    `base_offset` or type lost, a structural column put in the architectural category or types, or a footing whose
    `thickness` and `offset` do not hang it below the level (its base offset the offset less the thickness)."""
    sc.cmds(
        cmd("level", {"elevation": 6500, "name": "Roof"}),
        cmd("column", {"at": [0, 0]}),
        cmd("CL", {"at": [5000, 0], "type": "Round 300", "angle": 30, "height": 2500, "base_offset": 200}),
        cmd("structural_column", {"at": [0, 5000], "type": "Concrete 200 x 500", "top_level": "Roof"}),
        cmd("structural_column", {"at": [5000, 5000], "type": "Concrete Round 400", "level": "Level 2", "angle": 45}),
        cmd("footing", {"at": [0, 0], "thickness": 500, "offset": -100, "angle": 15}),
        cmd("FI", {"at": [5000, 5000], "type": "Footing 1500 x 1500"}),
        cmd("elements", {"category": "column"}),
        cmd("elements", {"category": "structural_column"}),
        cmd("elements", {"category": "footing"}),
        post=["--save", "plan.svg"],
    )
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_column_and_footing_refusals(sc):
    """CATCHES: a column made with a non-positive height, a top at or under its base, a type of another category, a level
    the project lacks, or a footing with no thickness, instead of the refusal that names what is wrong."""
    each(sc, "column", [
        {"at": [0, 0], "height": -5},
        {"at": [0, 0], "top_level": "Level 1"},
        {"at": [0, 0], "type": "Concrete 300 x 300"},
        {"at": [0, 0], "level": "Basement"},
        {},
    ])
    each(sc, "structural_column", [
        {"at": [0, 0], "type": "Round 300"},
        {"at": [0, 0], "height": 0},
    ])
    each(sc, "footing", [
        {"at": [0, 0], "thickness": 0},
        {"at": [0, 0], "type": "Rectangular 400 x 400"},
        {"thickness": 400},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Beams and strip footings
# ---------------------------------------------------------------------------


def test_beams_justification_offsets_slopes_and_systems(sc):
    """CATCHES: a beam's axis height not following its `justify` line (top by default, centre, bottom) at `offset` and
    `end_offset`, a sloped beam's length not the 3D length, a chain of points not making a beam for each segment (and a
    closing one with `closed`), or `system` and type lost."""
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [5000, 0], [5000, 5000]], "level": "Level 2", "type": "Beam 200 x 500"}),
        cmd("BM", {"points": [[0, 5000], [5000, 5000]], "offset": 2800, "end_offset": 3200, "justify": "centre",
                   "system": "Frame A"}),
        cmd("beam", {"points": [[0, 8000], [6000, 8000]], "offset": 3000, "justify": "bottom", "type": "Steel Tube 150"}),
        cmd("beam", {"points": [[10000, 0], [14000, 0], [14000, 3000], [10000, 3000]], "closed": True, "offset": 2900}),
        cmd("elements", {"category": "beam"}),
        post=["--save", "beams.svg"],
    )
    sc.file("beams.svg")
    assert sc.transcript() == sc.golden()


def test_strip_footings_under_walls(sc):
    """CATCHES: a strip footing not hanging under its level with its top at `offset`, the closed ring missing its last
    side, or its type, width or system lost."""
    sc.cmds(
        cmd("wall", {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": True}),
        cmd("strip_footing", {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": True, "offset": -200,
                              "system": "Foundations"}),
        cmd("type", {"category": "stripfooting", "name": "Strip 800 x 400", "width": 800, "depth": 400,
                     "material": "Concrete"}),
        cmd("FW", {"points": [[3000, 0], [3000, 4000]], "type": "Strip 800 x 400"}),
        cmd("elements", {"category": "strip_footing"}),
        post=["--save", "footings.svg"],
    )
    sc.file("footings.svg")
    assert sc.transcript() == sc.golden()


def test_beam_and_strip_footing_refusals(sc):
    """CATCHES: a beam steeper than 75° (what stands is a column), one of no length or a single point, an unknown type or
    justification, an `end_offset` over several segments, or a strip footing of a beam's type, being accepted."""
    each(sc, "beam", [
        {"points": [[0, 0], [100, 0]], "offset": 0, "end_offset": 3000},
        {"points": [[0, 0], [0, 0]], "offset": 0, "end_offset": 3000},
        {"points": [[0, 0], [0, 0]]},
        {"points": [[0, 0]]},
        {"points": [[0, 0], [5000, 0]], "type": "Beam 999"},
        {"points": [[0, 0], [5000, 0]], "justify": "middle"},
        {"points": [[0, 0], [5000, 0], [5000, 5000]], "end_offset": 300},
        {"points": [[0, 0], [5000, 0]], "level": "Level 9"},
        {},
    ])
    each(sc, "strip_footing", [
        {"points": [[0, 0], [5000, 0]], "type": "Beam 200 x 500"},
        {"points": [[0, 0], [100, 0]], "offset": 0, "end_offset": 2000},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# The runs of every discipline
# ---------------------------------------------------------------------------

RUNS = [
    cmd("pipe", {"points": [[0, 0], [4000, 0], [4000, 3000]], "offset": 600, "system": "Água fria"}),
    cmd("PI", {"points": [[1000, 1000], [1000, 1000]], "offset": -500, "end_offset": 3500, "type": "PVC 110",
               "system": "Esgoto"}),
    cmd("pipe", {"points": [[0, 500], [6000, 500]], "offset": 400, "end_offset": 280, "justify": "bottom", "type": "PVC 50"}),
    cmd("duct", {"points": [[0, 2000], [8000, 2000]], "offset": 2700, "type": "Rectangular 600 x 400", "system": "Supply air"}),
    cmd("DU", {"points": [[2000, 2500], [2000, 2500]], "offset": 0, "end_offset": 2700, "type": "Round 300"}),
    cmd("conduit", {"points": [[0, 0], [0, 4000], [3000, 4000]], "closed": True, "offset": 2900, "type": "PVC 25",
                    "system": "C1"}),
    cmd("cable_tray", {"points": [[0, 3500], [6000, 3500]], "offset": 2800, "justify": "top"}),
    cmd("wire", {"points": [[0, 0], [2000, 0]], "offset": 2900, "system": "C1", "type": "Wire 4"}),
    cmd("down_conductor", {"points": [[0, 0], [0, 0]], "offset": 0, "end_offset": 6000, "type": "Flat 25 x 3",
                           "system": "SPDA"}),
    cmd("ground_conductor", {"points": [[-500, -500], [8500, -500], [8500, 6500], [-500, 6500]], "closed": True,
                             "offset": -500}),
    cmd("cabling", {"points": [[0, 1500], [3000, 1500]], "offset": 2900, "type": "Cat6A", "system": "LAN"}),
]


def test_runs_of_every_discipline(sc):
    """CATCHES: a run command putting its runs in the wrong category or type set, a riser (the same point twice and two
    heights) refused or laid flat, centre justification not the default for a pipe, closed chains missing their closing
    segment, or a run's system, offsets or derived axis wrong."""
    categories = ["pipe", "duct", "conduit", "cabletray", "wire", "downconductor", "groundconductor", "cable"]
    sc.cmds(*RUNS, *[cmd("elements", {"category": c}) for c in categories], post=["--save", "runs.svg"])
    sc.file("runs.svg")
    assert sc.transcript() == sc.golden()


def test_runs_and_structure_in_ifc(sc):
    """CATCHES: runs written as the wrong IFC class or predefined type, systems not grouped into an IfcSystem, a beam's,
    column's or footing's profile set and cardinal point missing, or structural elements without LoadBearing."""
    sc.cmds(
        *RUNS,
        cmd("structural_column", {"at": [0, 0], "type": "Concrete Round 400"}),
        cmd("beam", {"points": [[0, 0], [5000, 0]], "level": "Level 2", "system": "Frame"}),
        cmd("beam", {"points": [[0, 3000], [5000, 3000]], "offset": 3000, "justify": "centre"}),
        cmd("footing", {"at": [0, 0]}),
        cmd("strip_footing", {"points": [[0, 0], [0, 5000]]}),
        cmd("floor", {"boundary": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]], "structural": True}),
        post=["--save", "mep.ifc"],
    )
    sc.file("mep.ifc")
    assert sc.transcript() == sc.golden()


def test_run_refusals(sc):
    """CATCHES: a run of no length or no height accepted, an unknown type of its category (the refusal lists them), a
    type of another discipline, or a bad justification, instead of refusing."""
    each(sc, "pipe", [
        {"points": [[0, 0], [0, 0]]},
        {"points": [[0, 0], [3000, 0]], "type": "PVC 999"},
        {"points": [[0, 0], [3000, 0]], "type": "Cat6"},
        {"points": [[0, 0], [3000, 0]], "justify": "left"},
    ])
    each(sc, "conduit", [{"points": [[0, 0], [3000, 0]], "type": "PVC 50"}])
    each(sc, "cable_tray", [{"points": [[0, 0], [3000, 0]], "type": "PVC 25"}])
    each(sc, "duct", [{"points": [[0, 0]]}])
    each(sc, "wire", [{"points": [[0, 0], [3000, 0]], "type": "Wire 99"}])
    each(sc, "down_conductor", [{"points": [[0, 0], [3000, 0]], "type": "Copper 9"}])
    each(sc, "ground_conductor", [{"points": [[0, 0], [3000, 0]], "type": "Flat 25 x 3"}])
    each(sc, "cabling", [{"points": [[0, 0], [3000, 0]], "type": "Cat7"}])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Types of the structural and run categories
# ---------------------------------------------------------------------------


def test_types_of_structure_and_runs_made_and_changed_everywhere(sc):
    """CATCHES: a new run, column or footing type stored without its width, depth, roundness or material, a round type's
    depth not its width, or an edited type not changing the elements that use it."""
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [5000, 0]], "type": "Beam 150 x 400"}),
        cmd("column", {"at": [0, 0]}),
        cmd("type", {"category": "beam", "name": "Beam 300 x 600", "width": 300, "depth": 600, "material": "Concrete"}),
        cmd("type", {"category": "pipe", "name": "PVC 75", "width": 75, "round": True, "material": "PVC"}),
        cmd("type", {"category": "cabletray", "name": "Tray 400 x 100", "width": 400, "depth": 100}),
        cmd("type", {"category": "structuralcolumn", "name": "Round 500", "width": 500, "round": True}),
        cmd("type", {"category": "footing", "name": "F 2000", "width": 2000, "depth": 1800}),
        cmd("type", {"category": "wire", "name": "Wire 10", "width": 7, "round": True}),
        cmd("type", {"category": "duct", "name": "Duct 800 x 500", "width": 800, "depth": 500, "material": "Metal"}),
        cmd("type", {"category": "downconductor", "name": "Round 10", "width": 10, "round": True, "material": "Copper"}),
        cmd("type", {"category": "groundconductor", "name": "Strip 30 x 4", "width": 30, "depth": 4}),
        cmd("type", {"category": "cable", "name": "Cat8", "width": 8, "round": True}),
        cmd("type", {"category": "conduit", "name": "Steel 32", "width": 32, "round": True, "material": "Metal"}),
        cmd("type", {"category": "railing", "name": "Rail 900", "height": 900, "spacing": 100}),
        cmd("type", {"category": "beam", "name": "Beam 150 x 400", "depth": 450, "material": "Timber"}),
        cmd("type", {"category": "column", "name": "Rectangular 400 x 400", "width": 500}),
        cmd("elements", {"category": "beam"}),
        cmd("elements", {"category": "column"}),
    )
    p = sc.run(["run", "--cmd", cmd("type", {"category": "beam", "name": "Beam 300 x 600", "width": 300, "depth": 600}),
                "--cmd", "inspect {}"], show=False)
    sc.note(json.dumps(json.loads(p.stdout.decode().splitlines()[-1])["types"]["runs"]["beam"], sort_keys=True))
    assert sc.transcript() == sc.golden()


def test_type_refusals_for_structure_and_runs(sc):
    """CATCHES: a run type of no width, a material the library lacks, a new type missing its depth, or a category with no
    types being accepted."""
    each(sc, "type", [
        {"category": "beam", "name": "B", "width": 0, "depth": 100},
        {"category": "beam", "name": "B", "width": 100, "depth": 100, "material": "Gold"},
        {"category": "duct", "name": "D", "width": 100},
        {"category": "pipe", "name": "P"},
        {"category": "footing", "name": "F", "width": -1, "depth": 100},
        {"category": "spaceship", "name": "S"},
        {"category": "railing", "name": "R", "height": -900},
    ])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Bars: rebar, reinforce, reinforcement_preset
# ---------------------------------------------------------------------------


def rounded(value, places=2):
    """A JSON value with every float rounded, for bars laid round a circle (their coordinates come from sines and
    cosines, whose last bits are not the point)."""
    if isinstance(value, float):
        return round(value, places) + 0.0
    if isinstance(value, list):
        return [rounded(v, places) for v in value]
    if isinstance(value, dict):
        return {k: rounded(v, places) for k, v in value.items()}
    return value


def bars_summary(sc, args):
    """Run `args` (ending with `elements {"category": "rebar"}`) and note each bar, its floats rounded to 0.01 mm."""
    p = sc.run(args, show=False)
    lines = p.stdout.decode().splitlines()
    sc.note(f"exit {p.returncode}; stderr: {p.stderr.decode().strip()}")
    for line in lines[:-1]:
        sc.note(json.dumps(rounded(json.loads(line)), ensure_ascii=False, sort_keys=True))
    for e in json.loads(lines[-1])["elements"]:
        e.pop("guid"), e.pop("host", None), e.pop("level")
        sc.note(json.dumps(rounded(e), sort_keys=True))


def test_rebar_bars_hoops_layers_and_schedule(sc):
    """CATCHES: a bar's length or weight (7850 kg/m³) wrong, a hoop (`closed`) not closing on its first point, `count`
    and `step` not making evenly offset copies, the grade not CA-50 by default, a hosted bar not on its host's level, or
    the bar schedule not listing and grouping them."""
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [4000, 0]], "level": "Level 2"}),
        cmd("rebar", {"points": [[0, 0, -100], [4000, 0, -100]], "diameter": 12.5}),
        cmd("rebar", {"points": [[50, -50, -50], [50, 50, -50], [50, 50, -350], [50, -50, -350]], "closed": True,
                      "diameter": 5, "host": 100002, "count": 3, "step": [150, 0, 0], "grade": "CA-60",
                      "layer": "stirrup"}),
        cmd("rebar", {"points": [[0, 0, 0], [0, 0, 3000]], "diameter": 20, "level": "Level 2"}),
        cmd("rebar", {"points": [[0, 0, 0], [300, 0, 0], [300, 400, 0]], "diameter": 8, "host": 100002}),
        cmd("elements", {"category": "rebar"}),
        cmd("schedule", {"name": "Bars", "category": "rebar"}),
        cmd("schedule", {"name": "Bar schedule", "category": "rebar",
                         "fields": ["Grade", "Diameter", "Length", "Count", {"name": "Weight", "total": True}],
                         "sort": ["Grade", "Diameter", "Length"], "grouped": True}),
        cmd("delete", {"ids": [100002]}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_rebar_refusals(sc):
    """CATCHES: a bar of a diameter outside 3 to 100 mm, fewer than two points or points without z, more than 1000 bars,
    copies without a `step`, a host that cannot hold bars or does not exist, no diameter, all points in one place, or a
    blank grade, being made."""
    each(sc, "rebar", [
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 2},
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 101},
        {"points": [[0, 0, 0]], "diameter": 10},
        {"points": [[0, 0], [100, 0]], "diameter": 10},
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 10, "count": 1001, "step": [10, 0, 0]},
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 10, "count": 3},
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 10, "host": 100000},
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 10, "host": 999},
        {"points": [[0, 0, 0], [100, 0, 0]]},
        {"points": [[0, 0, 0], [0, 0, 0]], "diameter": 10},
        {"points": [[0, 0, 0], [100, 0, 0]], "diameter": 10, "grade": ""},
    ])
    assert sc.transcript() == sc.golden()


BEAM_700 = [
    cmd("type", {"category": "beam", "name": "Beam 200 x 700", "width": 200, "depth": 700, "material": "Concrete"}),
    cmd("beam", {"points": [[0, 0], [6000, 0]], "level": "Level 2", "type": "Beam 200 x 700"}),
]


def test_reinforce_beam_rows_hooks_stirrups_with_closer_ends(sc):
    """CATCHES: bottom and top bars not laid inside the cover and the stirrup, a hook not turned up from the bottom bars
    (and down from the top ones), stirrups not closer in the `ends` lengths, a stirrup hook's tails missing, or the
    reply's count and weight wrong."""
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [6000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
        cmd("reinforce", {"host": 100002, "cover": 30, "bottom": {"count": 3, "diameter": 16, "hook": 150},
                          "top": {"count": 2, "diameter": 10},
                          "stirrup": {"diameter": 6.3, "spacing": 200, "ends": {"length": 1000, "spacing": 100},
                                      "hook": 80}}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforce_beam_bent_bars_skin_anchors_grades_and_check(sc):
    """CATCHES: bent-up bars not rising `top` mm from each end at `angle`, skin bars missing on a deep beam, anchors not
    running the bars past the ends, the stirrup grade not apart from the bars', or the NBR 6118 notes for class III
    covers and an fck past C30 missing or worded differently."""
    sc.cmds(
        *BEAM_700,
        cmd("reinforce", {"host": 100002, "cover": {"top": 30, "bottom": 30, "sides": 25},
                          "bottom": {"count": 4, "diameter": 16, "bent": {"count": 2, "angle": 45, "top": 1000}},
                          "top": {"count": 2, "diameter": 12.5, "hook": {"start": 200, "end": 0}},
                          "stirrup": {"diameter": 6.3, "spacing": 150}, "skin": {"diameter": 8, "spacing": 200},
                          "anchor": {"start": 0, "end": 100}, "check": "NBR 6118", "aggressiveness": 3, "fck": 40,
                          "grade": "CA-60", "grade_stirrup": "CA-50", "clearance": 25}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforce_beam_check_notes_of_a_thin_design(sc):
    """CATCHES: the check missing the least steel, the skin bars a beam over 600 mm deep wants, a stirrup under 5 mm or
    stirrups too far apart; and the cover read from the host's Cobrimento parameter when none is given."""
    sc.cmds(
        *BEAM_700,
        cmd("reinforce", {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 8},
                          "stirrup": {"diameter": 4.2, "spacing": 400}, "check": "NBR 6118"}),
    )
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [6000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
        cmd("parameter", {"name": "Cobrimento", "kind": "length", "categories": ["beam"]}),
        cmd("modify", {"id": 100002, "params": {"Cobrimento": 35}}),
        cmd("reinforce", {"host": 100002, "bottom": {"count": 2, "diameter": 10}}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforce_rectangular_column_bars_hooks_jog_ties(sc):
    """CATCHES: a rectangular column's bars not placed x along the width and y along the depth (corners counted), the
    foot hooks, the jog toward the axis below the top, the ties between face bars, the anchors past the ends, or the
    class II cover note missing."""
    sc.cmds(
        cmd("structural_column", {"at": [0, 0], "type": "Concrete 200 x 500"}),
        cmd("reinforce", {"host": 100002, "cover": {"top": 40, "bottom": 50, "sides": 25},
                          "bars": {"diameter": 12.5, "x": 2, "y": 3, "hook": {"below": 100, "above": 0},
                                   "jog": {"by": 15, "from_top": 600}},
                          "stirrup": {"diameter": 5, "spacing": 150}, "ties": {"diameter": 5, "hook": 50},
                          "anchor": {"below": 0, "above": 500}, "check": "NBR 6118", "aggressiveness": 2, "fck": 30}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforce_round_column_and_reinforcing_again(sc):
    """CATCHES: a round column's bars not spread evenly round its circle, its stirrup not a 24-sided hoop, reinforcing
    again not replacing the bars it made (`removed`), a bar drawn by hand taken away with them, or the round-column notes
    (6 bars at least, stirrup size and spacing, class IV covers) missing."""
    sc.cmds(
        cmd("structural_column", {"at": [0, 0], "type": "Concrete 200 x 500"}),
        cmd("structural_column", {"at": [3000, 0], "type": "Concrete Round 400"}),
        cmd("reinforce", {"host": 100003, "cover": 30, "bars": {"diameter": 16, "count": 6},
                          "stirrup": {"diameter": 6.3, "spacing": 200}, "check": "NBR 6118", "fck": 25}),
    )
    base = ["run", "--cmd", cmd("structural_column", {"at": [3000, 0], "type": "Concrete Round 400"}),
            "--cmd", cmd("reinforce", {"host": 100002, "cover": 30, "bars": {"diameter": 16, "count": 6},
                                       "stirrup": {"diameter": 6.3, "spacing": 200}}),
            "--cmd", cmd("rebar", {"points": [[3000, 0, 100], [3000, 0, 2900]], "diameter": 10, "host": 100002}),
            "--cmd", cmd("reinforce", {"host": 100002, "cover": 30, "bars": {"diameter": 20, "count": 4},
                                       "stirrup": {"diameter": 4, "spacing": 350}, "check": "NBR 6118",
                                       "aggressiveness": 4}),
            "--cmd", cmd("elements", {"category": "rebar"})]
    bars_summary(sc, base)
    assert sc.transcript() == sc.golden()


def test_reinforce_footings_square_and_round(sc):
    """CATCHES: a footing's mesh not two layers inside the cover with ends turned up by `hook`, a round footing's bars
    not stopping at its circle, or a mesh that does not fit the thickness accepted."""
    sc.cmds(
        cmd("footing", {"at": [0, 0], "thickness": 500}),
        cmd("reinforce", {"host": 100002, "cover": 50, "mesh": {"x": {"diameter": 12.5, "spacing": 150},
                                                                 "y": {"diameter": 10, "spacing": 200}, "hook": 200}}),
        cmd("elements", {"category": "rebar"}),
    )
    bars_summary(sc, [
        "run",
        "--cmd", cmd("type", {"category": "footing", "name": "Round 1500", "width": 1500, "round": True}),
        "--cmd", cmd("footing", {"at": [4000, 0], "type": "Round 1500"}),
        "--cmd", cmd("reinforce", {"host": 100002, "cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 250},
                                                                          "y": {"diameter": 10, "spacing": 250}}}),
        "--cmd", cmd("elements", {"category": "rebar"}),
    ])
    assert sc.transcript() == sc.golden()


def test_reinforce_floor_meshes_round_an_opening(sc):
    """CATCHES: a floor's bottom and top meshes not running east and north a cover short of its outline and its
    opening, the hooks of the bottom mesh not turned up, or the NBR 6118 floor notes (bar size against the thickness,
    spacing) missing."""
    sc.cmds(
        cmd("floor", {"boundary": [[0, 0], [3000, 0], [3000, 2000], [0, 2000]],
                      "openings": [[[1000, 800], [1600, 800], [1600, 1400], [1000, 1400]]], "structural": True}),
        cmd("reinforce", {"host": 100002, "cover": {"top": 25, "bottom": 30, "sides": 30},
                          "bottom": {"x": {"diameter": 8, "spacing": 300}, "y": {"diameter": 8, "spacing": 400},
                                     "hook": 100},
                          "top": {"y": {"diameter": 6.3, "spacing": 500}}, "check": "NBR 6118"}),
        cmd("elements", {"category": "rebar"}),
        cmd("reinforce", {"host": 100002, "cover": 20, "bottom": {"x": {"diameter": 32, "spacing": 450}},
                          "check": "NBR 6118"}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforce_several_hosts_with_a_preset(sc):
    """CATCHES: `hosts` not arming each host alike, a preset's parameters not standing in for those not given (and given
    ones not replacing its own), a preset of another kind than the host accepted, or one refusing host not stopping all
    of them."""
    sc.cmds(
        cmd("reinforcement_preset", {"name": "V-std", "kind": "beam",
                                     "params": {"cover": 25, "bottom": {"count": 3, "diameter": 12.5},
                                                "stirrup": {"diameter": 5, "spacing": 300}}}),
        cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2"}),
        cmd("beam", {"points": [[0, 3000], [3000, 3000]], "level": "Level 2", "type": "Beam 150 x 400"}),
        cmd("reinforce", {"hosts": [100002, 100003], "preset": "V-std", "top": {"count": 2, "diameter": 8}, "cover": 30}),
        cmd("elements", {"category": "rebar"}),
    )
    sc.cmds(
        cmd("reinforcement_preset", {"name": "Slab", "kind": "floor",
                                     "params": {"cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 150}}}}),
        cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2"}),
        cmd("reinforce", {"host": 100002, "preset": "Slab"}),
    )
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2"}),
        cmd("wall", {"points": [[0, 3000], [3000, 3000]]}),
        cmd("reinforce", {"hosts": [100002, 100003], "cover": 30, "bottom": {"count": 2, "diameter": 16}}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforcement_presets_made_renamed_listed_and_deleted(sc):
    """CATCHES: a preset's kind or parameters stored wrong, a rename that leaves the old name, a delete that keeps it,
    the library not listing it, or a preset of an unknown kind, with a host or with keys its kind does not take accepted."""
    sc.cmds(
        "reinforcement_preset {}",
        cmd("reinforcement_preset", {"name": "V-std", "kind": "beam",
                                     "params": {"cover": 25, "bottom": {"count": 3, "diameter": 12.5}}}),
        cmd("reinforcement_preset", {"name": "P-std", "kind": "column",
                                     "params": {"cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2}}}),
        cmd("reinforcement_preset", {"name": "S-std", "kind": "footing",
                                     "params": {"cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}}}}),
        cmd("reinforcement_preset", {"name": "V-std", "rename": "Viga"}),
        cmd("reinforcement_preset", {"name": "S-std", "delete": True}),
        "reinforcement_preset {}",
        cmd("library", {"kind": "reinforcement-preset"}),
    )
    each(sc, "reinforcement_preset", [
        {"name": "X", "kind": "wall", "params": {}},
        {"name": "X", "kind": "beam", "params": {"host": 100002}},
        {"name": "X", "kind": "beam", "params": {"mesh": {}}},
        {"name": "X"},
        {"name": "Nope", "delete": True},
        {"name": "X", "kind": "beam", "params": 5},
        {"name": " ", "kind": "beam", "params": {}},
        {"name": "X", "kind": "beam", "params": {"cover": 30, "colour": 1}},
        {"name": "Big", "kind": "beam", "params": {"grade": "x" * 17000}},
    ])
    each(sc, "reinforcement_preset", [
        {"name": "A", "rename": "B"},
        {"name": "A", "kind": "footing", "params": {"cover": 40}},
    ], pre=["--cmd", cmd("reinforcement_preset", {"name": "A", "kind": "beam", "params": {"cover": 25}}),
            "--cmd", cmd("reinforcement_preset", {"name": "B", "kind": "beam", "params": {"cover": 30}})])
    assert sc.transcript() == sc.golden()


REINFORCE_HOSTS = [
    "--cmd", cmd("beam", {"points": [[0, 0], [6000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
    "--cmd", cmd("structural_column", {"at": [0, 0], "type": "Concrete 200 x 500"}),
    "--cmd", cmd("structural_column", {"at": [3000, 0], "type": "Concrete Round 400"}),
    "--cmd", cmd("footing", {"at": [6000, 0]}),
    "--cmd", cmd("floor", {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                           "openings": [[[2000, 1000], [3000, 1000], [3000, 2000], [2000, 2000]]]}),
    "--cmd", cmd("wall", {"points": [[0, 6000], [4000, 6000]]}),
    "--cmd", cmd("beam", {"points": [[0, 8000], [6000, 8000]], "level": "Level 2", "type": "Steel Tube 150"}),
]

REINFORCE_REFUSALS = [
    {"host": 100002},
    {"host": 100002, "cover": 30},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 2}},
    {"host": 100002, "cover": 30, "bottom": {"count": 0, "diameter": 16}},
    {"host": 100002, "cover": 30, "bottom": {"count": 20, "diameter": 16}},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16, "colour": 1}},
    {"host": 100002, "cover": 30, "mesh": {"x": {"diameter": 10, "spacing": 100}}},
    {"host": 100002, "cover": 30, "stirrup": {"diameter": 6.3, "spacing": 5}},
    {"host": 100002, "cover": 300, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100002, "cover": 30, "bottom": {"count": 4, "diameter": 16, "bent": {"count": 2, "angle": 80}}},
    {"host": 100002, "cover": 30, "top": {"count": 2, "diameter": 16, "bent": {"count": 1}}},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16, "hook": {"start": 100, "middle": 3}}},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16, "hook": 800}},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16}, "check": "ACI 318"},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16}, "fck": 30},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16}, "check": "NBR 6118", "aggressiveness": 5},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16}, "check": "NBR 6118", "fck": 5},
    {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 16}, "grade": ""},
    {"host": 100002, "cover": {"top": 30, "bottom": 30}, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100002, "cover": -5, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100008, "cover": 30, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100007, "cover": 30, "bottom": {"count": 2, "diameter": 16}},
    {"host": 999999, "cover": 30},
    {"host": 100003, "cover": 30, "bars": {"diameter": 12.5, "count": 6}},
    {"host": 100004, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2}},
    {"host": 100004, "cover": 30, "bars": {"diameter": 12.5, "count": 6}, "ties": {"diameter": 5},
     "stirrup": {"diameter": 5, "spacing": 150}},
    {"host": 100003, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2}, "ties": {"diameter": 5},
     "stirrup": {"diameter": 5, "spacing": 150}},
    {"host": 100003, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 3}, "ties": {"diameter": 5}},
    {"host": 100003, "cover": 30, "bars": {"diameter": 12.5, "x": 1, "y": 2}},
    {"host": 100003, "cover": 30},
    {"host": 100003, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2,
                                           "jog": {"by": 15, "from_top": 600, "slope": 0.5}}},
    {"host": 100003, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2, "hook": {"below": 200}}},
    {"host": 100005, "cover": 30},
    {"host": 100005, "cover": 30, "mesh": {"x": {"diameter": 10, "spacing": 100}}, "bottom": {"count": 2, "diameter": 10}},
    {"host": 100005, "cover": 250, "mesh": {"x": {"diameter": 10, "spacing": 100}}},
    {"host": 100006, "cover": 30},
    {"host": 100006, "cover": 90, "bottom": {"x": {"diameter": 10, "spacing": 100}},
     "top": {"x": {"diameter": 10, "spacing": 100}}},
    {"hosts": [100002, 100007], "cover": 30, "bottom": {"count": 2, "diameter": 16}},
    {"hosts": [], "cover": 30},
    {"host": 100002, "hosts": [100002], "cover": 30, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100002, "preset": "Nope", "bottom": {"count": 2, "diameter": 16}},
    {"cover": 30},
]


@pytest.mark.parametrize("part", range(4))
def test_reinforce_refusals(sc, part):
    """CATCHES: reinforce arming a host without a cover, with nothing to lay, bars that do not fit, keys of another kind
    of host, a bent top row, a hook that leaves the stirrup, an unknown check or misplaced check options, a round beam, a
    wall, a round column with x and y or ties, a rectangular one with count, a slab whose meshes meet, or a list with a
    host that cannot be armed; each refusal says what to change and the model is left as it was."""
    for params in REINFORCE_REFUSALS[part::4]:
        p = sc.run(["run", *REINFORCE_HOSTS, "--cmd", cmd("reinforce", params)], show=False)
        sc.note(f"reinforce {json.dumps(params)}")
        sc.note(f"  exit {p.returncode}; stdout lines {len(p.stdout.splitlines())}; {p.stderr.decode().strip()}")
    assert sc.transcript() == sc.golden()


def test_reinforced_beam_in_ifc_and_plan(sc):
    """CATCHES: bars not written as IfcReinforcingBar (grade, diameter, area, length) with a swept disk along their
    polyline aggregated to their host, or a plan of their level not drawing them."""
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
        cmd("reinforce", {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 12.5},
                          "top": {"count": 2, "diameter": 8}, "stirrup": {"diameter": 5, "spacing": 600}}),
        cmd("rebar", {"points": [[0, 1000, 0], [3000, 1000, 0]], "diameter": 10}),
        cmd("render", {"view": "Level 2", "path": "level2.svg"}),
        post=["--save", "bars.ifc"],
    )
    sc.file("bars.ifc")
    sc.file("level2.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Stairs, ramps and railings
# ---------------------------------------------------------------------------


def test_stairs_straight_with_landings_turns_and_railings(sc):
    """CATCHES: a stair's riser count not the fewest that keep each riser at most `riser` (and its riser height the
    height over them), its runs not turned after a landing as `turn` says (straight, left, right, back beside it), its
    length and end wrong, `railings` not making one down each side, or `height` and `top_level` ignored."""
    sc.cmds(
        cmd("stair", {"start": [0, 0], "end": [5000, 0]}),
        cmd("stair", {"start": [0, 3000], "angle": 90, "width": 1200, "riser": 170, "tread": 300, "railings": True}),
        cmd("stair", {"start": [6000, 0], "angle": 0, "landings": [{"at": 8, "turn": 90}]}),
        cmd("stair", {"start": [6000, 6000], "angle": 0, "landings": [{"at": 8, "turn": -90}], "railings": True}),
        cmd("stair", {"start": [10000, 0], "angle": 0, "landings": [{"at": 6, "turn": 180}, {"at": 12, "turn": 0}],
                      "height": 4000, "top_level": None}),
        cmd("stair", {"start": [14000, 0], "angle": 180, "landings": [{"at": 9, "turn": -180}]}),
        cmd("stair", {"start": [0, -4000], "angle": 0, "riser": 500, "tread": 250}),
        cmd("elements", {"category": "stair"}),
        cmd("elements", {"category": "railing"}),
        post=["--save", "stairs.svg"],
    )
    sc.file("stairs.svg")
    assert sc.transcript() == sc.golden()


def test_ramps_and_railings_by_host_and_path(sc):
    """CATCHES: a ramp's length not its height over `slope` per cent (8.33 by default), its landings `at` mm up not
    turning it, its railings missing, a railing on one `side` of a stair not 50 mm in from its edge, or a railing along
    a `path` not standing `base_offset` mm up in its type."""
    sc.cmds(
        cmd("ramp", {"start": [0, 0], "end": [10000, 0], "height": 600}),
        cmd("ramp", {"start": [0, 3000], "angle": 90, "height": 1000, "slope": 5, "width": 1500,
                     "landings": [{"at": 500, "turn": -90}], "railings": True}),
        cmd("stair", {"start": [0, -5000], "angle": 180}),
        cmd("railing", {"host": 100006, "side": "left", "type": "Railing - 1000mm"}),
        cmd("type", {"category": "railing", "name": "Rail 900", "height": 900, "spacing": 0}),
        cmd("railing", {"path": [[0, -8000], [4000, -8000], [4000, -6000]], "base_offset": 150, "type": "Rail 900"}),
        cmd("railing", {"host": 100002, "side": "right"}),
        cmd("elements", {"category": "ramp"}),
        cmd("elements", {"category": "railing"}),
        post=["--save", "ramps.svg"],
    )
    sc.file("ramps.svg")
    assert sc.transcript() == sc.golden()


def test_stair_ramp_and_railing_refusals(sc):
    """CATCHES: a stair or ramp made without a start, climbing nowhere, with a non-positive riser, width or height, a
    landing that leaves a run of fewer than two risers or turns by an odd angle, a ramp slope outside 1 to 50 %, a landing
    above its top, or a railing on no stair or ramp, of an unknown type or along a one-point path."""
    each(sc, "stair", [
        {},
        {"start": [0, 0], "end": [0, 0]},
        {"start": [0, 0], "angle": 0, "riser": 0},
        {"start": [0, 0], "angle": 0, "width": -1},
        {"start": [0, 0], "angle": 0, "height": 0},
        {"start": [0, 0], "angle": 0, "landings": [{"at": 30}]},
        {"start": [0, 0], "angle": 0, "landings": [{"at": 0}]},
        {"start": [0, 0], "angle": 0, "landings": [{"at": 5, "turn": 45}]},
    ])
    each(sc, "ramp", [
        {},
        {"start": [0, 0], "angle": 0, "slope": 0},
        {"start": [0, 0], "angle": 0, "slope": 60},
        {"start": [0, 0], "angle": 0, "height": 500, "landings": [{"at": 900}]},
    ])
    each(sc, "railing", [
        {"host": 100000},
        {},
        {"path": [[0, 0]]},
        {"path": [[0, 0], [1000, 0]], "type": "Glass"},
    ])
    each(sc, "railing", [{"host": 100002, "side": "middle"}],
         pre=["--cmd", cmd("stair", {"start": [0, 0], "angle": 0})])
    each(sc, "stair", [{"start": [0, 0], "angle": 0, "landings": {"at": 5}}])
    assert sc.transcript() == sc.golden()


def test_stair_and_ramp_schedule_and_ifc(sc):
    """CATCHES: stairs, ramps and railings left out of their schedules or IFC (IfcStair, IfcRamp, IfcRailing), or their
    riser counts, widths and lengths scheduled wrong."""
    sc.cmds(
        cmd("stair", {"start": [0, 0], "angle": 0, "landings": [{"at": 8, "turn": 180}], "railings": True}),
        cmd("ramp", {"start": [0, 4000], "angle": 0, "height": 450}),
        cmd("schedule", {"name": "Stairs", "category": "stairs"}),
        cmd("schedule", {"name": "Ramps", "category": "ramps"}),
        cmd("schedule", {"name": "Railings", "category": "railings"}),
        post=["--save", "stairs.ifc"],
    )
    sc.file("stairs.ifc")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# falls
# ---------------------------------------------------------------------------

SLAB = cmd("floor", {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                     "openings": [[[2000, 1000], [3000, 1000], [3000, 2000], [2000, 2000]]]})


def test_falls_to_drains_round_an_opening_and_ridges(sc):
    """CATCHES: a drain's depth not the fall over its farthest corner (round an opening's corners where it can't see
    straight), the top split wrong into planes, a ridge not parting the top between two drains, or the shape's points
    and split lines written wrong."""
    sc.cmds(
        SLAB,
        cmd("falls", {"id": 100002, "drains": [[1000, 1000]], "fall": 1.5}),
        cmd("elements", {"category": "floor"}),
        cmd("falls", {"id": 100002, "drains": [[1000, 1500], [4000, 1500]], "fall": 1.5}),
    )
    sc.cmds(
        cmd("floor", {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]}),
        cmd("falls", {"id": 100002, "drains": [[3000, 2000]], "fall": 1.5}),
        cmd("falls", {"id": 100002, "drains": [[1500, 2000], [4500, 2000]], "fall": 2,
                      "ridges": [[[3000, 0], [3000, 4000]]]}),
        cmd("elements", {"category": "floor"}),
    )
    sc.cmds(
        cmd("floor", {"boundary": [[0, 0], [6000, 0], [6000, 2000], [2000, 2000], [2000, 6000], [0, 6000]]}),
        cmd("falls", {"id": 100002, "drains": [[5000, 1000], [1000, 5000]], "fall": 1}),
        cmd("roof", {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "level": "Level 2", "slope": 0}),
        cmd("falls", {"id": 100003, "drains": [[3000, 2000]], "fall": 2}),
    )
    assert sc.transcript() == sc.golden()


def test_falls_refusals(sc):
    """CATCHES: falls accepted with no drains, a drain outside the outline or in an opening, two drains a millimetre
    apart, a fall out of range or missing, a ridge that doesn't divide the top, a part with no drain, a corner a drain
    can't see, a pitched roof or a wall, or an unknown parameter."""
    pre = ["--cmd", SLAB, "--cmd", cmd("wall", {"points": [[0, 6000], [4000, 6000]]}),
           "--cmd", cmd("roof", {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "level": "Level 2"})]
    each(sc, "falls", [
        {"id": 100002, "drains": [], "fall": 1.5},
        {"id": 100002, "drains": [[9000, 2000]], "fall": 1.5},
        {"id": 100002, "drains": [[2500, 1500]], "fall": 1.5},
        {"id": 100002, "drains": [[1000, 1000], [1000.5, 1000]], "fall": 1.5},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 0},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 101},
        {"id": 100002, "drains": [[1000, 1000]]},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 1, "ridges": [[[3000, 500], [3000, 3500]]]},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 1, "ridges": [[[3000, 0], [3000, 4000]]]},
        {"id": 100003, "drains": [[1000, 1000]], "fall": 1},
        {"id": 100004, "drains": [[1000, 1000]], "fall": 1},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 1, "colour": 1},
        {"id": 100002, "drains": [[1000, 1500]], "fall": 1.5, "ridges": [[[2000, 1500], [3000, 1500]]]},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 1, "ridges": [[[0, 0], [0, 0]]]},
        {"id": 100002, "drains": [[10 + i * 20, 10] for i in range(201)], "fall": 1},
        {"id": 100002, "drains": [[1000, 1000]], "fall": 1,
         "ridges": [[[0, 10 + i * 10], [6000, 10 + i * 10]] for i in range(201)]},
    ], pre=pre)
    each(sc, "falls", [{"id": 100002, "drains": [[5000, 1000]], "fall": 1}],
         pre=["--cmd", cmd("floor", {"boundary": [[0, 0], [6000, 0], [6000, 2000], [2000, 2000], [2000, 6000],
                                                  [0, 6000]]})])
    assert sc.transcript() == sc.golden()


CHECK_HOSTS = [
    "--cmd", cmd("type", {"category": "beam", "name": "Beam 200 x 1200", "width": 200, "depth": 1200,
                          "material": "Concrete"}),
    "--cmd", cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
    "--cmd", cmd("beam", {"points": [[0, 2000], [3000, 2000]], "level": "Level 2", "type": "Beam 200 x 1200"}),
    "--cmd", cmd("structural_column", {"at": [0, 5000], "type": "Concrete 200 x 500"}),
    "--cmd", cmd("structural_column", {"at": [3000, 5000], "type": "Concrete 300 x 300"}),
    "--cmd", cmd("footing", {"at": [6000, 0]}),
    "--cmd", cmd("floor", {"boundary": [[0, 0], [3000, 0], [3000, 2000], [0, 2000]]}),
]

CHECKS = [
    {"host": 100002, "cover": 20, "clearance": 5, "bottom": {"count": 5, "diameter": 25},
     "top": {"count": 5, "diameter": 25}, "check": "NBR 6118"},
    {"host": 100002, "cover": 30, "bottom": {"count": 3, "diameter": 16}, "stirrup": {"diameter": 25, "spacing": 150},
     "check": "NBR 6118", "fck": 20},
    {"host": 100003, "cover": 30, "bottom": {"count": 3, "diameter": 16}, "skin": {"diameter": 16, "spacing": 300},
     "check": "NBR 6118"},
    {"host": 100004, "cover": 30, "bars": {"diameter": 8, "x": 2, "y": 2}, "check": "NBR 6118"},
    {"host": 100004, "cover": 30, "clearance": 10, "bars": {"diameter": 32, "x": 3, "y": 5},
     "stirrup": {"diameter": 10, "spacing": 150}, "check": "NBR 6118"},
    {"host": 100005, "cover": 30, "bars": {"diameter": 10, "x": 2, "y": 2}, "stirrup": {"diameter": 5, "spacing": 120},
     "check": "NBR 6118"},
    {"host": 100006, "cover": 30, "mesh": {"x": {"diameter": 10, "spacing": 150}}, "check": "NBR 6118",
     "aggressiveness": 3},
    {"host": 100007, "cover": 20, "bottom": {"x": {"diameter": 8, "spacing": 150}}, "check": "NBR 6118",
     "aggressiveness": 2},
    {"host": 100007, "cover": 30, "bottom": {"x": {"diameter": 8, "spacing": 150}}, "check": "NBR 6118",
     "aggressiveness": 1},
]


def test_reinforce_check_notes_for_each_kind_of_host(sc):
    """CATCHES: the NBR 6118 check missing or misworded notes: a beam's 4 % most, a stirrup over a tenth of the width,
    skin bars too far apart on a deep beam, a column's bars under 10 mm or over an eighth of the side, under 0.4 % or over
    8 % of steel, too far apart along a face, and the covers of Table 7.2 for a footing and a floor by class."""
    for params in CHECKS:
        p = sc.run(["run", *CHECK_HOSTS, "--cmd", cmd("reinforce", params)], show=False)
        reply = json.loads(p.stdout.decode().splitlines()[-1])
        sc.note(f"reinforce {json.dumps(params)}")
        sc.note(f"  exit {p.returncode}; count {reply['count']}; weight {reply['weight_kg']} kg")
        for n in reply["notes"]:
            sc.note(f"  - {n}")
    assert sc.transcript() == sc.golden()


def test_reinforce_column_ties_both_ways_stirrup_hooks_and_closer_ends(sc):
    """CATCHES: ties not made across both axes between face bars (straight when they have no hook), a column's stirrup
    hook tails, or the closer stirrups of `ends` at a column's foot and top; and a single bottom bar not set in the
    middle, bent-up bars not taking a fifth of the length along the top when `top` is not given."""
    sc.cmds(
        cmd("structural_column", {"at": [0, 0], "type": "Concrete 300 x 300", "height": 1200}),
        cmd("reinforce", {"host": 100002, "cover": 30, "bars": {"diameter": 12.5, "x": 3, "y": 3},
                          "stirrup": {"diameter": 5, "spacing": 300, "hook": 60, "ends": {"length": 300, "spacing": 100}},
                          "ties": {"diameter": 5}}),
        cmd("elements", {"category": "rebar"}),
    )
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
        cmd("reinforce", {"host": 100002, "cover": 30, "bottom": {"count": 4, "diameter": 12.5, "bent": {"count": 2}},
                          "top": {"count": 1, "diameter": 10}}),
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()


def test_reinforce_shaped_and_sloped_floors(sc):
    """CATCHES: a floor shaped by falls not armed under its variable layer (or not refused when its type has none), or a
    sloped floor's meshes not following its top, the cover square to it."""
    floors = [
        "--cmd", cmd("type", {"category": "floor", "name": "Slab var",
                              "layers": [{"function": "finish", "material": "Screed", "thickness": 50, "variable": True},
                                         {"function": "structure", "material": "Concrete", "thickness": 150}]}),
        "--cmd", cmd("floor", {"boundary": [[0, 0], [3000, 0], [3000, 2000], [0, 2000]], "type": "Slab var"}),
        "--cmd", cmd("floor", {"boundary": [[0, 5000], [3000, 5000], [3000, 7000], [0, 7000]], "slope": 10,
                               "arrow": [[0, 5000], [3000, 5000]]}),
        "--cmd", cmd("floor", {"boundary": [[0, 9000], [3000, 9000], [3000, 11000], [0, 11000]]}),
        "--cmd", cmd("falls", {"id": 100002, "drains": [[1500, 1000]], "fall": 1}),
        "--cmd", cmd("falls", {"id": 100004, "drains": [[1500, 10000]], "fall": 1}),
    ]
    bars_summary(sc, ["run", *floors,
                      "--cmd", cmd("reinforce", {"host": 100002, "cover": 25, "bottom": {"x": {"diameter": 8, "spacing": 500}}}),
                      "--cmd", cmd("reinforce", {"host": 100003, "cover": 25,
                                                 "bottom": {"x": {"diameter": 8, "spacing": 700}},
                                                 "top": {"y": {"diameter": 8, "spacing": 900}, "hook": 50}}),
                      "--cmd", cmd("elements", {"category": "rebar"})])
    sc.run(["run", *floors, "--cmd", cmd("reinforce", {"host": 100004, "cover": 25,
                                                       "bottom": {"x": {"diameter": 8, "spacing": 500}}})])
    assert sc.transcript() == sc.golden()


GEOMETRY_HOSTS = [
    "--cmd", cmd("type", {"category": "beam", "name": "Deep", "width": 200, "depth": 5000, "material": "Concrete"}),
    "--cmd", cmd("type", {"category": "footing", "name": "Round 1500", "width": 1500, "round": True}),
    "--cmd", cmd("beam", {"points": [[0, 0], [6000, 0]], "level": "Level 2", "type": "Beam 200 x 500"}),
    "--cmd", cmd("beam", {"points": [[0, 2000], [50, 2000]], "level": "Level 2"}),
    "--cmd", cmd("structural_column", {"at": [9000, 0], "height": 50}),
    "--cmd", cmd("structural_column", {"at": [3000, 0], "type": "Concrete Round 400"}),
    "--cmd", cmd("footing", {"at": [6000, 0]}),
    "--cmd", cmd("footing", {"at": [12000, 0], "type": "Round 1500"}),
    "--cmd", cmd("floor", {"boundary": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]}),
    "--cmd", cmd("beam", {"points": [[0, 9000], [6000, 9000]], "level": "Level 2", "type": "Deep"}),
    "--cmd", cmd("structural_column", {"at": [0, 0], "type": "Concrete 300 x 300"}),
]

GEOMETRY_REFUSALS = [
    {"host": 100002, "cover": 30, "stirrup": {"diameter": 5, "spacing": 5.5}},
    {"host": 100002, "cover": {"top": 30, "bottom": 30, "sides": 95}, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100003, "cover": 30, "bottom": {"count": 2, "diameter": 16}},
    {"host": 100002, "cover": {"top": 210, "bottom": 210, "sides": 20}, "bottom": {"count": 2, "diameter": 90}},
    {"host": 100002, "cover": 30, "bottom": {"count": 4, "diameter": 12.5, "bent": {"count": 2}},
     "top": {"count": 4, "diameter": 12.5}},
    {"host": 100002, "cover": {"top": 220, "bottom": 220, "sides": 30}, "bottom": {"count": 2, "diameter": 25},
     "top": {"count": 2, "diameter": 25}},
    {"host": 100002, "cover": {"top": 30, "bottom": 30, "sides": 80}, "stirrup": {"diameter": 10, "spacing": 200},
     "bottom": {"count": 2, "diameter": 10}},
    {"host": 100009, "cover": 30, "bottom": {"count": 2, "diameter": 10}, "skin": {"diameter": 3, "spacing": 3.5}},
    {"host": 100003, "cover": 10, "stirrup": {"diameter": 50, "spacing": 100}},
    {"host": 100002, "cover": 30, "bottom": {"count": 3, "diameter": 12.5, "bent": {"count": 2}}},
    {"host": 100002, "cover": 30, "bottom": {"count": 4, "diameter": 12.5, "bent": {"count": 2, "top": 2900}}},
    {"host": 100002, "cover": 30, "stirrup": {"diameter": 5, "spacing": 200, "ends": {"length": -5, "spacing": 100}}},
    {"host": 100010, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2, "jog": {"by": 15, "from_top": 5000}}},
    {"host": 100010, "cover": 150, "bars": {"diameter": 12.5, "x": 2, "y": 2}},
    {"host": 100010, "cover": 30, "bars": {"diameter": 12.5, "x": 4, "y": 4, "jog": {"by": 60, "from_top": 600}}},
    {"host": 100010, "cover": 30, "bars": {"diameter": 12.5, "x": 3, "y": 3},
     "stirrup": {"diameter": 5, "spacing": 200, "ends": {"length": 0, "spacing": 100}}},
    {"host": 100004, "cover": 30, "bars": {"diameter": 12.5, "x": 2, "y": 2}},
    {"host": 100004, "cover": 20, "stirrup": {"diameter": 20, "spacing": 100}},
    {"host": 100005, "cover": 30, "bars": {"diameter": 12.5, "count": 2}},
    {"host": 100005, "cover": 30, "bars": {"diameter": 12.5}},
    {"host": 100005, "cover": 150, "bars": {"diameter": 100, "count": 6}},
    {"host": 100005, "cover": 30, "bars": {"diameter": 20, "count": 40}},
    {"host": 100005, "cover": 30, "bars": {"diameter": 12.5, "count": 6, "hook": 500}},
    {"host": 100006, "cover": {"top": 50, "bottom": 50, "sides": 700}, "mesh": {"x": {"diameter": 10, "spacing": 100}}},
    {"host": 100006, "cover": {"top": 50, "bottom": 50, "sides": 590}, "mesh": {"y": {"diameter": 10, "spacing": 100}}},
    {"host": 100006, "cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 25}}},
    {"host": 100007, "cover": 50, "mesh": {"x": {"diameter": 10, "spacing": 150}, "hook": 400}},
    {"host": 100008, "cover": 30, "bottom": {"x": {"diameter": 10, "spacing": 100}, "hook": 300}},
    {"host": 100008, "cover": 30, "top": {"x": {"diameter": 10, "spacing": 100}, "hook": 300}},
    {"host": 100008, "cover": {"top": 30, "bottom": 190, "sides": 30}, "bottom": {"x": {"diameter": 10, "spacing": 100}}},
    {"host": 100008, "cover": {"top": 190, "bottom": 30, "sides": 30}, "top": {"x": {"diameter": 10, "spacing": 100}}},
    {"host": 100008, "cover": 30, "clearance": 1, "bottom": {"x": {"diameter": 3, "spacing": 3.5},
                                                           "y": {"diameter": 3, "spacing": 3.5}}},
    {"host": 100008, "cover": 30, "bottom": {"x": {"diameter": 10, "spacing": 100, "colour": 2}}},
    {"host": 100008, "cover": 30, "bottom": {"x": {"diameter": 10, "spacing": 3}}},
    {"host": 100008, "cover": 30, "bottom": {"x": {"diameter": 10, "spacing": 100}}, "clearance": -3},
    {"host": 100002, "cover": {"top": 30, "bottom": 30, "sides": 80}, "stirrup": {"diameter": 10, "spacing": 200},
     "skin": {"diameter": 32, "spacing": 100}},
    {"host": 100005, "cover": 160, "bars": {"diameter": 100, "count": 6}},
]


@pytest.mark.parametrize("part", range(4))
def test_reinforce_refusals_of_what_does_not_fit(sc, part):
    """CATCHES: reinforce making bars that do not fit their host: more than 1000 bars, rows too wide or too deep for the
    section, a beam or column too short for its cover or stirrup, bent bars meeting a top bar or each other in the
    middle, a jog off the bars or crowding them, round-column bars too many or too thick for the circle, meshes that
    leave their footing or floor, hooks past the other face, or spacings and clearances out of range."""
    for params in GEOMETRY_REFUSALS[part::4]:
        p = sc.run(["run", *GEOMETRY_HOSTS, "--cmd", cmd("reinforce", params)], show=False)
        sc.note(f"reinforce {json.dumps(params)}")
        sc.note(f"  exit {p.returncode}; stdout lines {len(p.stdout.splitlines())}; {p.stderr.decode().strip()}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------
# Schedules and IFC round trips of structure and MEP
# ---------------------------------------------------------------------------


def test_schedules_of_structure_and_runs(sc):
    """CATCHES: the schedule of columns, structural columns, footings, beams, strip footings or pipes listing the wrong
    fields or values, beams not grouped and totalled by type, a filter on System not keeping only that system's runs, or
    a multi-category schedule not giving each its Category, Type, Width, Length and Material."""
    sc.cmds(
        cmd("column", {"at": [0, 0]}),
        cmd("structural_column", {"at": [3000, 0], "type": "Concrete Round 400"}),
        cmd("footing", {"at": [0, 0]}),
        cmd("beam", {"points": [[0, 0], [3000, 0], [3000, 3000]], "level": "Level 2", "system": "Frame A"}),
        cmd("beam", {"points": [[0, 3000], [3000, 3000]], "level": "Level 2", "type": "Beam 150 x 400",
                     "system": "Frame B"}),
        cmd("strip_footing", {"points": [[0, 0], [0, 3000]]}),
        cmd("pipe", {"points": [[0, 500], [3000, 500]], "offset": 300, "system": "Esgoto", "type": "PVC 110"}),
        cmd("pipe", {"points": [[0, 800], [2000, 800]], "offset": 300, "system": "Água fria", "type": "PVC 25"}),
        cmd("schedule", {"name": "C", "category": "columns"}),
        cmd("schedule", {"name": "SC", "category": "structural columns"}),
        cmd("schedule", {"name": "F", "category": "footings"}),
        cmd("schedule", {"name": "B", "category": "beams",
                         "fields": ["Type", "System", {"name": "Length", "total": True}, "Count"],
                         "sort": ["Type"], "grouped": True}),
        cmd("schedule", {"name": "B2", "category": "beams", "fields": ["Id", "System", "Length"],
                         "filters": [{"field": "System", "op": "equals", "value": "Frame A"}]}),
        cmd("schedule", {"name": "SF", "category": "strip footings"}),
        cmd("schedule", {"name": "P", "category": "pipes", "sort": [{"field": "Length", "descending": True}]}),
        cmd("schedule", {"name": "M", "category": "multicategory",
                         "fields": ["Category", "Type", "Level", "Count", "Width", "Length", "Material"],
                         "sort": ["Category", "Type"]}),
        post=["--cmd", cmd("schedule", {"name": "B", "path": "beams.csv"})],
    )
    sc.file("beams.csv")
    assert sc.transcript() == sc.golden()


def test_structure_and_mep_come_back_from_ifc(sc):
    """CATCHES: an IFC export and import losing a run's category, type, system, justification or heights, a riser laid
    flat, bars losing their host, or structural columns and floors losing what makes them structural; `info` of the file
    must count what went out."""
    built = [
        *RUNS,
        cmd("structural_column", {"at": [0, 0], "type": "Concrete Round 400"}),
        cmd("beam", {"points": [[0, 0], [5000, 0]], "level": "Level 2", "system": "Frame"}),
        cmd("footing", {"at": [0, 0]}),
        cmd("strip_footing", {"points": [[0, 0], [0, 5000]]}),
        cmd("reinforce", {"host": 100020, "cover": 30, "bottom": {"count": 2, "diameter": 12.5}}),
        cmd("floor", {"boundary": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]], "structural": True}),
        cmd("column", {"at": [3000, 3000], "level": "Level 2"}),
    ]
    p = sc.run(["run", *sum((["--cmd", c] for c in built), []), "--save", "mep.ifc"], show=False)
    sc.note(f"export: exit {p.returncode}, {p.stdout.decode().splitlines()[-1]}")
    p = sc.run(["info", "mep.ifc"], show=False)
    info = json.loads(p.stdout.decode())
    sc.note(f"info: exit {p.returncode}")
    sc.note(json.dumps({k: info[k] for k in ("counts", "levels", "warnings")}, ensure_ascii=False, sort_keys=True))
    sc.note(json.dumps(info["types"]["runs"], ensure_ascii=False, sort_keys=True))
    sc.run(["run", "mep.ifc", "--cmd", "elements {}"])
    assert sc.transcript() == sc.golden()


def test_runs_and_hosts_edited_moved_copied_and_deleted(sc):
    """CATCHES: `modify` of a run's offsets, justification, system or type not moving its axis to match, a beam edited
    past 75° accepted, `move` and `copy` of runs and columns wrong, bars not going with a deleted host, or undo not
    bringing the host and its bars back."""
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [5000, 0]], "level": "Level 2"}),
        cmd("pipe", {"points": [[0, 1000], [5000, 1000]], "offset": 500, "system": "A"}),
        cmd("structural_column", {"at": [0, 0]}),
        cmd("modify", {"id": 100003, "offset": 800, "end_offset": 600, "justify": "bottom", "system": "Esgoto",
                       "type": "PVC 110"}),
        cmd("modify", {"id": 100002, "end_offset": 400}),
        cmd("move", {"ids": [100002], "by": [0, 500]}),
        cmd("copy", {"ids": [100003, 100004], "by": [0, 1000]}),
        cmd("rotate", {"ids": [100004], "about": [0, 0], "angle": 90}),
        cmd("elements", {"category": "pipe"}),
        cmd("elements", {"category": "beam"}),
        cmd("elements", {"category": "structural_column"}),
    )
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [5000, 0]], "level": "Level 2"}),
        cmd("modify", {"id": 100002, "end_offset": 50000}),
    )
    sc.cmds(
        cmd("beam", {"points": [[0, 0], [3000, 0]], "level": "Level 2"}),
        cmd("reinforce", {"host": 100002, "cover": 30, "bottom": {"count": 2, "diameter": 10}}),
        cmd("rebar", {"points": [[0, 2000, 0], [3000, 2000, 0]], "diameter": 8}),
        cmd("delete", {"ids": [100002]}),
        "inspect {}",
        "undo {}",
        cmd("elements", {"category": "rebar"}),
    )
    assert sc.transcript() == sc.golden()
