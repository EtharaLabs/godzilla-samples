"""The sizing commands of the MEP tabs, which change nothing in the model: `circuit` (NBR 5410), `conduit_fill`,
`drain_size` and `vent_size` (NBR 8160), `hydrant_size` (IT 22/2025), `water_size` (NBR 5626), `storm_size` (NBR 10844) and
`load_points` (NBR 5410 item 9.5.2). Their replies are rich JSON compared whole; the edges of their tables (the smallest and
largest sizes, nothing that fits, band limits) and every refusal's words are pinned down too."""

import pytest
from conftest import normalize


def _transcript(run, commands):
    """Each command run in a process of its own (`run --cmd`): the command, its exit code, stdout and stderr, in turn."""
    parts = []
    for cmd in commands:
        r = run(["run", "--cmd", cmd])
        parts.append(f"$ {cmd}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    return normalize("".join(parts))


# Each case: the commands of one transcript (each run on its own).
CASES = {
    # ---- circuit: NBR 5410 sizing of one copper circuit
    "circuit_sizes": [
        'circuit {"load": 2000}',
        'circuit {"load": 2000, "system": "230/400"}',
        'circuit {"load": 9000, "phases": "3FN", "system": "220/380", "length": 40000, "power_factor": 0.92, "demand": 0.8}',
        'circuit {"load": 5000, "apparent": true, "phases": "FF", "length": 25000, "section": 4, "breaker": 32}',
        'circuit {"load": 5000, "apparent": true, "phases": "FF", "section": 1.5, "breaker": 16}',
        'circuit {"load": 600, "use": "lighting", "method": "11", "grouped": 4, "insulation": "epr", "conductor": "rigid", "ambient": 40}',
        'circuit {"load": 20000, "phases": "3F", "method": "61A", "grouped": 3, "spacing": 250, "soil": 2, "system": "230/400"}',
        'circuit {"load": 20000, "phases": "3F", "method": "61", "ambient": 35, "soil": 3}',
        'circuit {"load": 150000, "phases": "3FN", "system": "220/380", "reduced_neutral": true}',
        'circuit {"load": 150000, "phases": "3FN", "system": "220/380"}',
        'circuit {"load": 3000, "length": 80000}',
        'circuit {"load": 3000, "length": 80000, "drop_limit": 2, "conductor": "rigid"}',
        'circuit {"load": 1000, "breaker": 40}',
        'circuit {"load": 1000, "ambient": 10, "method": "1"}',
        'circuit {"load": 1000, "method": "11", "bundle": true, "grouped": 12}',
        'circuit {"load": 1000, "method": "11A", "grouped": 20}',
        'circuit {"load": 1000, "method": "11", "grouped": 20}',
        'circuit {"load": 1000, "grouped": 25}',
        'circuit {"load": 1000, "grouped": 2.4, "method": "4", "use": "lighting", "length": 15000, "power_factor": 0.5}',
    ],
    "circuit_refusals": [
        "circuit {}",
        "circuit []",
        'circuit {"load": -1}',
        'circuit {"load": 0}',
        'circuit {"load": 1e9}',
        'circuit {"load": 1000, "colour": 1}',
        'circuit {"load": 1000, "section": 3}',
        'circuit {"load": 1000, "breaker": 17}',
        'circuit {"load": 1000, "method": "9"}',
        'circuit {"load": 1000, "method": 7}',
        'circuit {"load": 1000, "phases": "2F"}',
        'circuit {"load": 1000, "system": "110/220"}',
        'circuit {"load": 1000, "use": "heating"}',
        'circuit {"load": 1000, "insulation": "xlpe"}',
        'circuit {"load": 1000, "conductor": "stranded"}',
        'circuit {"load": 1000, "ambient": 75}',
        'circuit {"load": 1000, "ambient": 5}',
        'circuit {"load": 1000, "ambient": -60}',
        'circuit {"load": 1000, "method": "61", "grouped": 7}',
        'circuit {"load": 1000, "method": "61A", "grouped": 2, "spacing": 2000}',
        'circuit {"load": 1000, "method": "61", "soil": 0.5}',
        'circuit {"load": 1000, "demand": 1.5}',
        'circuit {"load": 1000, "power_factor": 0}',
        'circuit {"load": 1000, "apparent": "yes"}',
        'circuit {"load": 1000, "length": -5}',
        'circuit {"load": 1000, "grouped": 0}',
        'circuit {"load": 1000, "drop_limit": 101}',
    ],
    # ---- conduit_fill: conductors of a circuit over a conduit's inside
    "conduit_fill_sizes": [
        'conduit_fill {"section": 2.5}',
        'conduit_fill {"section": 2.5, "size": "3/4\\""}',
        'conduit_fill {"section": 25, "phases": "3FN", "size": "1/2\\""}',
        'conduit_fill {"section": 4, "phases": "FN", "size": "1/2\\"", "circuits": 2}',
        'conduit_fill {"section": 10, "phases": "3FN", "circuits": 3, "family": "steel-heavy"}',
        'conduit_fill {"section": 120, "phases": "3FN", "reduced_neutral": true, "family": "steel-rir", "size": "4\\""}',
        'conduit_fill {"section": 240, "phases": "3FN", "circuits": 2, "family": "pvc-solder"}',
        'conduit_fill {"section": 1.5, "phases": "FF", "family": "pvc-solder", "size": "DN20"}',
        'conduit_fill {"section": 35, "phases": "3F", "circuits": 2.5, "family": "steel-rir"}',
        'conduit_fill {"section": 0.5, "phases": "3F", "circuits": 1000}',
        'conduit_fill {"section": 300}',
        'conduit_fill {"section": 3}',
    ],
    "conduit_fill_refusals": [
        "conduit_fill {}",
        'conduit_fill {"section": 0}',
        'conduit_fill {"section": 2000}',
        'conduit_fill {"section": 2.5, "size": "7\\""}',
        'conduit_fill {"section": 2.5, "size": 1}',
        'conduit_fill {"section": 2.5, "family": "copper"}',
        'conduit_fill {"section": 2.5, "circuits": 0}',
        'conduit_fill {"section": 2.5, "phases": "N"}',
        'conduit_fill {"section": 2.5, "reduced_neutral": 1}',
        'conduit_fill {"section": 2.5, "insulation": "epr"}',
        "conduit_fill 7",
    ],
    # ---- drain_size: NBR 8160 Tabelas 3, 5, 6 and 7
    "drain_size_sizes": [
        'drain_size {"units": 3}',
        'drain_size {"units": 3.5}',
        'drain_size {"units": 160}',
        'drain_size {"fixtures": {"wc": 1}}',
        'drain_size {"fixtures": {"wc": 1, "lav": 1}}',
        'drain_size {"fixtures": {"lav": 2, "shower": 1, "sink": 0}, "min_dn": 75}',
        'drain_size {"fixtures": {"sink": 1, "laundry": 1}, "units": 4}',
        'drain_size {"units": 50, "role": "main"}',
        'drain_size {"units": 150, "role": "main", "slope": 0.005}',
        'drain_size {"units": 150, "role": "main", "slope": 0.02}',
        'drain_size {"units": 230, "role": "main", "slope": 0.03}',
        'drain_size {"units": 12000, "role": "main", "slope": 0.04}',
        'drain_size {"units": 300, "role": "stack", "floors": 5}',
        'drain_size {"units": 300, "role": "stack", "floors": 3}',
        'drain_size {"units": 300, "role": "stack", "floors": 4}',
        'drain_size {"units": 8, "role": "stack", "min_dn": 75}',
    ],
    "drain_size_refusals": [
        "drain_size {}",
        'drain_size {"units": 200}',
        'drain_size {"units": 13000, "role": "main", "slope": 0.04}',
        'drain_size {"units": 10, "role": "main", "slope": 0.001}',
        'drain_size {"units": 9000, "role": "stack", "floors": 10}',
        'drain_size {"fixtures": {"bidet": 1}}',
        'drain_size {"fixtures": {"wc": 1.5}}',
        'drain_size {"fixtures": {"wc": -1}}',
        'drain_size {"fixtures": [1]}',
        'drain_size {"fixtures": {"wc": 0}}',
        'drain_size {"units": 10, "role": "vent"}',
        'drain_size {"units": 10, "slope": 2}',
        'drain_size {"units": 10, "floors": 0}',
        'drain_size {"units": 10, "min_dn": 2000}',
        'drain_size {"units": 10, "dn": 100}',
    ],
    # ---- vent_size: NBR 8160 Tabelas 8, 2 and 1
    "vent_size_sizes": [
        'vent_size {"units": 12}',
        'vent_size {"units": 13}',
        'vent_size {"units": 36}',
        'vent_size {"units": 17, "wc": true}',
        'vent_size {"units": 30, "wc": true, "trap_dn": 40}',
        'vent_size {"units": 100, "stack_dn": 100, "length": 50000}',
        'vent_size {"units": 100, "stack_dn": 100, "length": 50000, "trap_dn": 75}',
        'vent_size {"units": 5, "stack_dn": 40, "length": 46000}',
        'vent_size {"units": 20000, "stack_dn": 300, "length": 100000, "trap_dn": 100}',
        'vent_size {"units": 2900, "stack_dn": 150, "length": 0}',
    ],
    "vent_size_refusals": [
        "vent_size {}",
        'vent_size {"units": 37}',
        'vent_size {"units": 61, "wc": true}',
        'vent_size {"units": 5, "stack_dn": 40, "length": 47000}',
        'vent_size {"units": 600, "stack_dn": 100, "length": 1000}',
        'vent_size {"units": 10, "stack_dn": 400, "length": 1000}',
        'vent_size {"units": 10, "stack_dn": 90, "length": 1000}',
        'vent_size {"units": 10, "stack_dn": 100}',
        'vent_size {"units": 10, "stack_dn": 100, "length": -1}',
        'vent_size {"units": 10, "trap_dn": 60}',
        'vent_size {"units": 10, "wc": "yes"}',
        'vent_size {"units": 10, "role": "branch"}',
    ],
    # ---- hydrant_size: IT 22/2025 Tabelas 1 to 3
    "hydrant_size_sizes": [
        'hydrant_size {"column": 5, "area": 60000}',
        'hydrant_size {"column": 4, "area": 2500}',
        'hydrant_size {"column": 4, "area": 2500.5}',
        'hydrant_size {"column": 5, "area": 5000}',
        'hydrant_size {"column": 5, "area": 5001}',
        'hydrant_size {"column": 1, "area": 100, "inside": 27, "length": 20000}',
        'hydrant_size {"column": 4, "area": 2500, "type": "4-65", "inside": 66.9, "length": 80000, "rise": 15000, "nominal": 65, "material": "steel-wet"}',
        'hydrant_size {"type": "1", "hydrants": 1, "inside": 27, "nominal": 25, "length": 30000, "material": "pvc"}',
        'hydrant_size {"type": "5", "hydrants": 4, "inside": 52.5, "length": 10000, "rise": -3000}',
        'hydrant_size {"type": "2", "inside": 53, "nominal": 50, "material": "copper", "region": "SP"}',
        'hydrant_size {"type": "3", "inside": 66.9, "nominal": 50, "material": "pex"}',
        'hydrant_size {"type": "4-40"}',
    ],
    "hydrant_size_refusals": [
        "hydrant_size {}",
        'hydrant_size {"column": 4, "area": 2500, "inside": 60}',
        'hydrant_size {"type": "2", "nominal": 50}',
        'hydrant_size {"column": 1, "area": 100, "type": "3"}',
        'hydrant_size {"column": 1}',
        'hydrant_size {"area": 100}',
        'hydrant_size {"column": 2.5, "area": 100}',
        'hydrant_size {"column": 6, "area": 100}',
        'hydrant_size {"column": 3, "area": 0}',
        'hydrant_size {"type": "6"}',
        'hydrant_size {"type": 1}',
        'hydrant_size {"type": "1", "hydrants": 1.5}',
        'hydrant_size {"type": "1", "hydrants": 0}',
        'hydrant_size {"region": "RJ", "type": "1"}',
        'hydrant_size {"type": "3", "inside": 0}',
        'hydrant_size {"type": "3", "inside": 60, "material": "iron"}',
        'hydrant_size {"type": "3", "inside": 60, "length": -1}',
        'hydrant_size {"type": "3", "pressure": 10}',
    ],
    # ---- water_size: NBR 5626, PVC soldável
    "water_size_sizes": [
        'water_size {"fixtures": {"wc": 2, "lav": 2, "shower": 2, "sink": 1, "laundry": 1}}',
        'water_size {"fixtures": {"wc": 2, "lav": 2, "shower": 2, "sink": 1, "laundry": 1}, "method": "sum", "length": 12000, "fittings": {"elbow90": 4, "tee_side": 1, "gate": 1}, "pressure": 80, "rise": 3000}',
        'water_size {"flow": 0.5, "dn": 20, "length": 5000, "pressure": 30, "rise": 2500}',
        'water_size {"flow": 0.5, "dn": 25, "length": 5000, "pressure": 60, "rise": -1000}',
        'water_size {"flow": 0.01, "dn": 110, "length": 1000}',
        'water_size {"fixtures": {"lav": 1, "wc": 0}}',
        'water_size {"flow": 3}',
        'water_size {"flow": 1, "dn": 50, "length": 2000, "fittings": {"elbow90": 1, "elbow45": 1, "tee_through": 1, "tee_side": 1, "gate": 1, "globe": 1, "check": 1}}',
        'water_size {"flow": 20}',
    ],
    "water_size_refusals": [
        "water_size {}",
        'water_size {"flow": 40}',
        'water_size {"flow": 0}',
        'water_size {"flow": 1, "fixtures": {"wc": 1}}',
        'water_size {"fixtures": {"bidet": 1}}',
        'water_size {"fixtures": {"wc": 0}}',
        'water_size {"fixtures": {"wc": 2.5}}',
        'water_size {"fixtures": "x"}',
        'water_size {"flow": 1, "dn": 30}',
        'water_size {"flow": 1, "fittings": {"bend": 1}}',
        'water_size {"flow": 1, "fittings": {"gate": -1}}',
        'water_size {"flow": 1, "fittings": 3}',
        'water_size {"flow": 1, "method": "hunter"}',
        'water_size {"flow": 1, "pressure": -1}',
        'water_size {"flow": 1, "speed": 2}',
    ],
    # ---- storm_size: NBR 10844, Figure 3's abacuses and Manning
    "storm_size_sizes": [
        'storm_size {"kind": "downpipe", "area": 80, "gutter": 60, "length": 3000}',
        'storm_size {"kind": "downpipe", "flow": 1500, "gutter": 75, "length": 1200, "outlet": "funnel"}',
        'storm_size {"kind": "downpipe", "flow": 1500, "gutter": 75, "length": 1200, "outlet": "edge"}',
        'storm_size {"kind": "downpipe", "flow": 2500, "gutter": 100, "length": 50000}',
        'storm_size {"kind": "downpipe", "flow": 800, "gutter": 50, "length": 300}',
        'storm_size {"kind": "downpipe", "flow": 1200, "gutter": 90, "length": 25000, "outlet": "funnel"}',
        'storm_size {"kind": "horizontal", "area": 400, "rainfall": 170, "slope": 0.01, "inside": 100}',
        'storm_size {"kind": "horizontal", "area": 50, "slope": 0.005, "inside": 75}',
        'storm_size {"kind": "horizontal", "area": 100, "slope": 0.02}',
        'storm_size {"kind": "horizontal", "flow": 300, "slope": 0.04, "inside": 150}',
    ],
    "storm_size_refusals": [
        'storm_size {"area": 30}',
        'storm_size {"kind": "vertical"}',
        'storm_size {"kind": "downpipe", "flow": 10000, "gutter": 50, "length": 3000}',
        'storm_size {"kind": "downpipe", "flow": 100, "gutter": 40, "length": 3000}',
        'storm_size {"kind": "downpipe", "flow": 100, "gutter": 60, "length": 200}',
        'storm_size {"kind": "downpipe", "flow": 300, "gutter": 60}',
        'storm_size {"kind": "downpipe", "flow": 300, "length": 3000}',
        'storm_size {"kind": "downpipe", "flow": 300, "area": 30, "gutter": 60, "length": 3000}',
        'storm_size {"kind": "downpipe", "flow": 300, "gutter": 60, "length": 3000, "slope": 0.01}',
        'storm_size {"kind": "horizontal", "area": 400, "slope": 0.01}',
        'storm_size {"kind": "horizontal", "flow": 300, "slope": 0.001}',
        'storm_size {"kind": "horizontal", "flow": 300}',
        'storm_size {"kind": "horizontal", "flow": 300, "gutter": 60, "slope": 0.01}',
        'storm_size {"kind": "horizontal", "rainfall": 100, "flow": 300, "slope": 0.01}',
        'storm_size {"kind": "horizontal", "slope": 0.01}',
        'storm_size {"kind": "horizontal", "flow": 300, "slope": 0.01, "diameter": 100}',
    ],
    # ---- load_points: NBR 5410 item 9.5.2 for rooms given
    "load_points_rooms": [
        'load_points {"rooms": [{"name": "Cozinha", "area": 9.5, "perimeter": 12400}, {"name": "Banheiro", "area": 3.2, "perimeter": 7200}, {"name": "Área de Serviço", "area": 4, "perimeter": 8000, "points": 2}, {"name": "Sala", "area": 18.3, "perimeter": 17200}, {"name": "Varanda", "area": 5, "perimeter": 9000}, {"name": "Hall", "area": 4, "perimeter": 8000}, {"name": "Escritório", "area": 10.5, "perimeter": 13000}, {"name": "Depósito", "area": 2, "perimeter": 6000, "kind": "other"}, {"name": "Copa", "area": 7, "perimeter": 11000, "points": 6}]}',
        'load_points {"alternative": true, "rooms": [{"name": "Kitchen", "area": 12, "perimeter": 14000}, {"name": "Bathroom", "area": 4, "perimeter": 8000, "points": 3}, {"name": "Laundry", "area": 6, "perimeter": 10000}]}',
        'load_points {"alternative": true, "rooms": [{"name": "WC", "area": 2, "perimeter": 6000}, {"name": "Suíte Master", "area": 6, "perimeter": 10000}]}',
        'load_points {"rooms": [{"name": "Lavabo", "area": 2, "perimeter": 6000, "kind": "dry"}, {"name": "Garage", "area": 30, "perimeter": 22000}, {"name": "Sacada", "area": 3, "perimeter": 7000, "points": 0}, {"name": "", "area": 6.01, "perimeter": 9800}, {"name": "Café", "area": 8, "perimeter": 12000}, {"name": "Estúdio", "area": 14, "perimeter": 15000}, {"name": "COZINHA AMERICANA", "area": 10, "perimeter": 13000}]}',
        "load_points {}",
    ],
    "load_points_refusals": [
        'load_points {"rooms": [{"name": "A", "area": 5}]}',
        'load_points {"rooms": [{"name": "A", "perimeter": 5000}]}',
        'load_points {"rooms": [{"name": "A", "area": 5, "perimeter": 9000, "kind": "garage"}]}',
        'load_points {"rooms": [{"name": "A", "area": 5, "perimeter": 9000, "points": -1}]}',
        'load_points {"rooms": [{"name": "A", "area": 5, "perimeter": 9000, "points": 1001}]}',
        'load_points {"rooms": [{"name": "A", "area": 5, "perimeter": 9000, "colour": 1}]}',
        'load_points {"rooms": [{"name": "A", "area": -5, "perimeter": 9000}]}',
        'load_points {"rooms": [{"name": 7, "area": 5, "perimeter": 9000}]}',
        'load_points {"rooms": [3]}',
        'load_points {"rooms": {}}',
        'load_points {"floors": 1}',
        'load_points {"alternative": 1}',
        "load_points 5",
    ],
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_sizing(run, golden, case):
    """CATCHES: a rewrite whose sizing replies differ from the reference's in any key, number or rounding (the design
    current, the section and breaker chosen, the fill, the DN, a head loss, the abacus' diameter, a room's points and VA),
    that reads a table's band or edge on the wrong side, sizes where the reference finds nothing, or that refuses (or
    accepts) a parameter the reference accepts (or refuses), or words a refusal differently."""
    golden.check(_transcript(run, CASES[case]), f"{case}.txt")


def test_sizing_changes_nothing_and_is_no_undo_step(run, golden):
    """CATCHES: a rewrite whose sizing commands change the model or leave an undo step, so that `undo` after them would
    take back a sizing instead of the wall drawn before it."""
    r = run(["run", "--cmd", 'wall {"points": [[0, 0], [4000, 0]]}', "--cmd", 'circuit {"load": 2000}',
             "--cmd", 'drain_size {"units": 3}', "--cmd", 'water_size {"flow": 0.5}', "--cmd", 'load_points {}',
             "--cmd", "undo", "--cmd", 'elements {"category": "walls"}', "--cmd", "undo"])
    golden.check_run(r, "sizing_is_no_undo_step.txt")


def test_load_points_reads_the_rooms_of_the_model(run, golden):
    """CATCHES: a rewrite whose `load_points` without `rooms` does not read the model's rooms inside the walls' finish
    (their area and perimeter), knows a room's kind from its name differently, or does not list a room that walls do not
    enclose as skipped."""
    r = run(["run",
             "--cmd", 'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}',
             "--cmd", 'wall {"points": [[3000, 0], [3000, 4000]]}',
             "--cmd", 'wall {"points": [[0, 4000], [0, 7000], [6000, 7000], [6000, 4000]]}',
             "--cmd", 'room {"point": [1500, 2000], "name": "Cozinha"}',
             "--cmd", 'room {"point": [4500, 2000], "name": "Dormitório 1"}',
             "--cmd", 'room {"point": [3000, 5500], "name": "Banheiro Social"}',
             "--cmd", 'room {"point": [20000, 2000], "name": "Lost"}',
             "--cmd", 'load_points {"alternative": true}'])
    golden.check_run(r, "load_points_model_rooms.txt")


def test_load_points_measures_rooms_where_the_project_says(run, golden):
    """CATCHES: a rewrite whose `load_points` measures the model's rooms at the walls' centre lines instead of inside
    their finish, whatever `room_area` says."""
    r = run(["run",
             "--cmd", 'wall {"points": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]], "closed": true}',
             "--cmd", 'room {"point": [2500, 2000], "name": "Sala de Estar"}',
             "--cmd", 'room_area {"at": "centre"}',
             "--cmd", 'load_points {}'])
    golden.check_run(r, "load_points_room_area_centre.txt")
