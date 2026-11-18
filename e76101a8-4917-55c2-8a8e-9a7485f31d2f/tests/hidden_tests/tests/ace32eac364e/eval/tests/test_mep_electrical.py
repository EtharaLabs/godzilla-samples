"""The project's electrical settings: `voltage`, `distribution_system` and `wire_type` (as Revit's Electrical Settings).
The starter set, making, editing, renaming (a system follows its voltages) and deleting them, every refusal's words, how a
project file holds them (a system names its voltages by GUID) and Insert from File bringing them in."""

import json

import pytest
from conftest import normalize


def _transcript(run, commands):
    """Each command run in a process of its own (`run --cmd`): the command, its exit code, stdout and stderr, in turn."""
    parts = []
    for cmd in commands:
        r = run(["run", "--cmd", cmd])
        parts.append(f"$ {cmd[:200]}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    return normalize("".join(parts))


def test_a_new_project_starts_with_the_starter_settings(run, golden):
    """CATCHES: a rewrite whose new project lacks a starter voltage, distribution system or wire type (230/400 V,
    127/220 V, 220/380 V, 277/480 V; Cu PVC 70 °C, Cu XLPE/EPR 90 °C, THHN, THW), or differs in a band, an earthing, a
    note, a label or an ampacity, or lists them in another shape or order."""
    r = run(["run", "--cmd", "voltage", "--cmd", "distribution_system", "--cmd", 'wire_type {"name": "  "}'])
    golden.check_run(r, "starter_settings.txt")


def test_a_portuguese_project_has_the_same_starter_settings(run, golden):
    """CATCHES: a rewrite that translates or leaves out the electrical settings of a project made in another language."""
    r = run(["run", "--cmd", 'new {"language": "pt"}', "--cmd", "distribution_system", "--cmd", 'voltage {"name": "127 V"}'])
    golden.check_run(r, "starter_settings_pt.txt")


SCENARIO = [
    # A voltage with the default band (10 % either way, to a tenth), one with its own band.
    'voltage {"name": "110 V", "nominal": 110}',
    'voltage {"name": "24 V", "nominal": 24, "min": 20, "max": 28}',
    # An edit keeps what it does not give; naming one that exists only reads it back.
    'voltage {"name": "24 V", "max": 30}',
    'voltage {"name": "24 V"}',
    # A nominal changed alone keeps the band it had.
    'voltage {"name": "110 V", "nominal": 115}',
    'distribution_system {"name": "SELV", "phases": 1, "wires": 2, "l_n": "24 V", "l_g": "24 V", "ground": "IT"}',
    'distribution_system {"name": "Bi 220", "phases": 2, "wires": 3, "l_l": "220 V", "l_n": "110 V"}',
    # Renamed, a voltage is followed by the systems that name it.
    'voltage {"name": "24 V", "rename": "SELV 24 V"}',
    'distribution_system {"name": "SELV"}',
    # "" takes a voltage or the earthing away; a rename keeps the rest.
    'distribution_system {"name": "127/220 V", "ground": "", "l_g": ""}',
    'distribution_system {"name": "127/220 V", "rename": "Rede BT", "ground": "TN-C-S"}',
    'wire_type {"name": "Al XLPE 90", "material": "aluminium", "temperature": 90, "insulation": "XLPE", "note": "maker table", "sizes": [{"section": 16, "ampacity": 60}, {"section": 25, "ampacity": 79, "label": "25 mm²"}, {"section": 35, "ampacity": 79}]}',
    # Giving `sizes` replaces the table; "" clears the note.
    'wire_type {"name": "Al XLPE 90", "sizes": [{"section": 50, "ampacity": 105}], "note": ""}',
    'wire_type {"name": "Al XLPE 90", "rename": "Al 90", "temperature": 85.5}',
    'wire_type {"name": "Cu THW 75 °C", "delete": true}',
    'distribution_system {"name": "Bi 220", "delete": true}',
    # A voltage no system supplies any more can go.
    'voltage {"name": "110 V", "delete": true}',
    "voltage",
    "distribution_system",
    'library {"kind": "voltage"}',
    'library {"kind": "distribution-system"}',
    'library {"kind": "wire-type"}',
    "undo",
    # A listing is no undo step: the redo still does the delete again.
    "voltage",
    "redo",
    # A voltage named alone is read back, and is an undo step that changes nothing.
    'voltage {"name": "SELV 24 V"}',
    "undo",
    "voltage",
]


def test_settings_are_made_edited_renamed_and_deleted(run, golden):
    """CATCHES: a rewrite that loses a field an edit did not give, does not round the default band, does not make the
    systems follow a renamed voltage, clears the wrong thing on "", keeps a wire type's old table or note, numbers the
    library entries differently, or does not undo and redo these changes as single steps."""
    args = ["run"]
    for cmd in SCENARIO:
        args += ["--cmd", cmd]
    golden.check_run(run(args), "scenario.txt")


REFUSALS = {
    "voltage": [
        'voltage {"name": "127 V", "delete": true}',
        'voltage {"name": "99 V", "delete": true}',
        'voltage {"name": "x", "rename": "y"}',
        'voltage {"name": "x"}',
        'voltage {"name": "x", "nominal": 0}',
        'voltage {"name": "x", "nominal": 200000}',
        'voltage {"name": "x", "nominal": 100, "min": 120}',
        'voltage {"name": "x", "nominal": 100, "max": 90}',
        'voltage {"name": "x", "nominal": 100, "min": -1}',
        'voltage {"name": "x", "nominal": "a"}',
        'voltage {"name": "x", "nominal": 100, "colour": 1}',
        'voltage {"name": "220 V", "rename": "127 V"}',
        'voltage {"name": 5}',
        'voltage {"name": "x", "nominal": 100, "delete": "yes"}',
        'voltage {"name": "' + "v" * 257 + '", "nominal": 100}',
    ],
    "distribution_system": [
        'distribution_system {"name": "X", "phases": 4, "wires": 4, "l_l": "220 V"}',
        'distribution_system {"name": "X", "phases": 0, "wires": 2, "l_n": "220 V"}',
        'distribution_system {"name": "X", "phases": 3, "wires": 2, "l_l": "220 V"}',
        'distribution_system {"name": "X", "phases": 3, "wires": 5, "l_l": "220 V"}',
        'distribution_system {"name": "X", "phases": 1, "wires": 3, "l_n": "220 V"}',
        'distribution_system {"name": "X", "phases": 1, "wires": 2}',
        'distribution_system {"name": "X", "phases": 2, "wires": 2, "l_n": "127 V"}',
        'distribution_system {"name": "X", "phases": 3, "wires": 4, "l_l": "999 V"}',
        'distribution_system {"name": "X", "phases": 1, "wires": 2, "l_g": "12 V"}',
        'distribution_system {"name": "X", "phases": 3, "wires": 4, "l_l": "220 V", "l_n": "220 V"}',
        'distribution_system {"name": "X", "phases": 3, "wires": 3, "l_l": "220 V", "ground": "TN"}',
        'distribution_system {"name": "X", "wires": 3}',
        'distribution_system {"name": "X", "phases": 3}',
        'distribution_system {"name": "X", "phases": 300, "wires": 3}',
        'distribution_system {"name": "X", "phases": 1.5, "wires": 3}',
        'distribution_system {"name": "X", "rename": "Y"}',
        'distribution_system {"name": "X", "delete": true}',
        'distribution_system {"name": "230/400 V", "rename": "127/220 V"}',
        'distribution_system {"name": "230/400 V", "l_l": ""}',
        'distribution_system {"name": "X", "voltage": 1}',
    ],
    "wire_type": [
        'wire_type {"name": "W"}',
        'wire_type {"name": "W", "material": "gold", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 10}]}',
        'wire_type {"name": "W", "material": "copper"}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC"}',
        'wire_type {"name": "W", "material": "copper", "temperature": 300, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 10}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 0, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 10}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": " ", "sizes": [{"section": 1, "ampacity": 10}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": []}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 0, "ampacity": 10}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 20000, "ampacity": 10}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 0}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 2, "ampacity": 10}, {"section": 1.5, "ampacity": 12}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 2, "ampacity": 10}, {"section": 2, "ampacity": 12}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 10}, {"section": 1.5, "ampacity": 9}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1, "amps": 10}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": "big"}',
        'wire_type {"name": "W", "material": "copper", "temperature": "hot", "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 10}]}',
        'wire_type {"name": "W", "rename": "V"}',
        'wire_type {"name": "W", "delete": true}',
        'wire_type {"name": "Cu THW 75 °C", "rename": "Cu THHN 90 °C"}',
        'wire_type {"name": "W", "size": 1}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 10, "label": "' + "L" * 300 + '"}]}',
        'wire_type {"name": "W", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": ['
        + ", ".join(f'{{"section": {n}, "ampacity": {n}}}' for n in range(1, 66)) + "]}",
    ],
}


@pytest.mark.parametrize("command", sorted(REFUSALS))
def test_refusals(run, golden, command):
    """CATCHES: a rewrite that accepts a voltage, distribution system or wire type the reference refuses (a band that
    leaves out the nominal, wires that don't suit the phases, a voltage the project lacks, three phases whose voltages are
    not about root three apart, an unknown earthing, a table that shrinks), deletes a voltage a system supplies, or words
    a refusal differently."""
    golden.check(_transcript(run, REFUSALS[command]), f"refusals_{command}.txt")


def test_too_many_voltages_are_refused(run, workdir, golden):
    """CATCHES: a rewrite that lets a project hold more than 64 voltages, or refuses one fewer."""
    lines = [f'voltage {{"name": "V{n}", "nominal": {n}}}' for n in range(1, 57)]  # 7 starter ones + 56 = 63
    (workdir / "many.txt").write_text("\n".join(lines) + "\n")
    r = run(["run", "--script", "many.txt", "--cmd", 'voltage {"name": "V64", "nominal": 64}',
             "--cmd", 'voltage {"name": "V99", "nominal": 99}'])
    golden.check_run(r, "too_many_voltages.txt")


def _electrical(path):
    """What a project file holds of its electrical settings: the three tables and their library entries."""
    d = json.loads(path.read_text())
    lib = {k: v for k, v in d["library"].items() if v["kind"] in ("voltage", "distribution-system", "wire-type")}
    keep = {"voltages": d["voltages"], "distribution_systems": d["distribution_systems"],
            "wire_types": {k: v for k, v in d["wire_types"].items() if k == "Al"}, "library": lib}
    return normalize(json.dumps(keep, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def test_a_project_file_names_a_systems_voltages_by_guid(run, workdir, golden):
    """CATCHES: a rewrite whose project file holds a system's voltages by name instead of by the voltage's GUID, gives the
    settings no library entries (ids counting down from 999999 and GUIDs), or loses a setting when the file is opened."""
    r = run(["run", "--cmd", 'voltage {"name": "24 V", "nominal": 24}',
             "--cmd", 'distribution_system {"name": "SELV", "phases": 1, "wires": 2, "l_n": "24 V"}',
             "--cmd", 'wire_type {"name": "Al", "material": "aluminium", "temperature": 90, "insulation": "XLPE", "sizes": [{"section": 16, "ampacity": 60, "label": "16"}]}',
             "--save", "e.bimcraft"])
    assert r.returncode == 0, r.stderr
    golden.check(_electrical(workdir / "e.bimcraft"), "file_electrical.json")
    r = run(["run", "e.bimcraft", "--cmd", 'voltage {"name": "24 V", "rename": "Extra-low"}',
             "--cmd", "distribution_system", "--cmd", 'wire_type {"name": "Al"}'])
    golden.check_run(r, "file_reopened.txt")


def test_insert_from_file_brings_settings_by_name(run, workdir, golden):
    """CATCHES: a rewrite whose Insert from File leaves out the other project's voltages and distribution systems, or
    brings one in whose name this project already has instead of using this project's own."""
    r = run(["run", "--cmd", 'voltage {"name": "24 V", "nominal": 24}', "--cmd", 'voltage {"name": "48 V", "nominal": 48}',
             "--cmd", 'distribution_system {"name": "SELV", "phases": 1, "wires": 2, "l_n": "24 V", "l_g": "48 V"}',
             "--cmd", 'wall {"points": [[0, 0], [1000, 0]]}', "--save", "a.bimcraft"])
    assert r.returncode == 0, r.stderr
    r = run(["run", "--cmd", 'voltage {"name": "24 V", "nominal": 25}', "--cmd", 'insert {"path": "a.bimcraft"}',
             "--cmd", "voltage", "--cmd", 'distribution_system {"name": "SELV"}'])
    golden.check_run(r, "insert_settings.txt")


def test_inspect_lists_the_three_tables(run, golden):
    """CATCHES: a rewrite whose `inspect` leaves out the voltages, the distribution systems or the wire types, or shows
    them other than the commands list them."""
    r = run(["run", "--cmd", 'voltage {"name": "24 V", "nominal": 24}', "--cmd", 'wire_type {"name": "Cu THHN 90 °C", "delete": true}',
             "--cmd", "inspect"])
    assert r.returncode == 0, r.stderr
    last = json.loads(r.stdout.decode().splitlines()[-1])
    text = json.dumps({k: last[k] for k in ("voltages", "distribution_systems", "wire_types")}, indent=1, ensure_ascii=False)
    golden.check(text + "\n", "inspect_electrical.json")


def test_too_many_systems_and_wire_types_are_refused(run, workdir, golden):
    """CATCHES: a rewrite that lets a project hold more than 64 distribution systems or 64 wire types, or refuses the
    64th."""
    systems = [f'distribution_system {{"name": "S{n}", "phases": 1, "wires": 2, "l_n": "230 V"}}' for n in range(1, 61)]
    wires = [f'wire_type {{"name": "W{n}", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{{"section": 1, "ampacity": {n}}}]}}'
             for n in range(1, 61)]
    (workdir / "many.txt").write_text("\n".join(systems + wires) + "\n")
    r = run(["run", "--script", "many.txt", "--cmd", 'distribution_system {"name": "S61", "phases": 1, "wires": 2, "l_n": "230 V"}'])
    out = r.stdout.decode().splitlines()
    text = f"exit: {r.returncode}\n{len(out)} replies\n{out[-1]}\n{r.stderr.decode()}"
    r = run(["run", "--script", "many.txt", "--cmd",
             'wire_type {"name": "W61", "material": "copper", "temperature": 70, "insulation": "PVC", "sizes": [{"section": 1, "ampacity": 1}]}'])
    out = r.stdout.decode().splitlines()
    text += f"exit: {r.returncode}\n{len(out)} replies\n{out[-1]}\n{r.stderr.decode()}"
    golden.check(text, "too_many_systems_and_wire_types.txt")


def test_a_project_file_with_broken_settings_is_refused(run, workdir, golden):
    """CATCHES: a rewrite that opens a project file whose electrical settings break the rules a command keeps (a system
    naming a voltage the file lacks, a voltage whose band leaves out its nominal, a shrinking wire table, a blank name,
    more than 64 voltages) instead of refusing it with the reason."""
    assert run(["run", "--save", "base.bimcraft"]).returncode == 0
    base = json.loads((workdir / "base.bimcraft").read_text())

    def edited(change):
        doc = json.loads(json.dumps(base))
        change(doc)
        return doc

    def lost_voltage(d):
        d["distribution_systems"]["230/400 V"]["l_n"] = "999 V"

    def band(d):
        d["voltages"]["230 V"]["min"] = 300.0

    def shrinking(d):
        d["wire_types"]["Cu PVC 70 °C"]["sizes"][3]["ampacity"] = 1.0

    def blank(d):
        d["voltages"]["  "] = {"nominal": 12.0, "min": 11.0, "max": 13.0}

    def many(d):
        for n in range(1, 60):
            d["voltages"][f"V{n}"] = {"nominal": float(n), "min": n * 0.9, "max": n * 1.1}

    def long_note(d):
        d["wire_types"]["Cu PVC 70 °C"]["note"] = "n" * 300

    out = []
    for name, change in [("lost_voltage", lost_voltage), ("band", band), ("shrinking", shrinking), ("blank", blank),
                         ("many", many), ("long_note", long_note)]:
        (workdir / f"{name}.bimcraft").write_text(json.dumps(edited(change)))
        r = run(["run", f"{name}.bimcraft"])
        out.append(f"== {name}\nexit: {r.returncode}\n{r.stdout.decode()}{r.stderr.decode()}")
    golden.check(normalize("".join(out)), "broken_files.txt")
