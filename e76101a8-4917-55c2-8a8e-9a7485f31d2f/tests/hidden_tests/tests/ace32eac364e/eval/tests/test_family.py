"""The `family` command (parameters, formulas, types, forms, symbols, connectors, files, dry runs, patches, warnings
and refusals), `component`, and `symbol_set`."""

import json

import pytest
from conftest import normalize

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'

DESK = json.dumps({
    "name": "Work Desk",
    "parameters": [
        {"name": "Width", "value": 1200},
        {"name": "Depth", "value": 600},
        {"name": "Height", "instance": True, "value": 740},
        {"name": "Top", "formula": "Height - 30"},
    ],
    "types": {"1200 x 600": {}, "1600 x 800": {"Width": 1600, "Depth": 800}},
    "forms": [{"profile": [[0, 0], ["Width", 0], ["Width", "Depth"], [0, "Depth"]], "from": "Top", "to": "Height",
               "material": "Timber"}],
})

SOCKET = {
    "name": "Socket", "category": "lighting",
    "parameters": [{"name": "Show", "kind": "yesno", "value": 1, "instance": True},
                   {"name": "Circuit", "kind": "number", "value": 3, "instance": True}],
    "types": {"A": {}},
    "forms": [{"profile": [[300, 300], [400, 300], [400, 400], [300, 400]], "to": 100}],
    "symbols": [
        {"line": [[0, 0], [100, 0]]},
        {"arc": {"centre": [0, 0], "radius": 50, "from": 0, "to": 180}, "visible": "Show"},
        {"text": {"at": [0, -150], "height": 60, "value": "C{Circuit}"}},
        {"dot": {"centre": [200, 100], "radius": 20}},
    ],
}

SHELF = json.dumps({"name": "Shelf", "types": {"A": {}}, "forms": [
    {"profile": [[0, 0], [600, 0], [600, 400], [0, 400]], "to": 30},
    {"profile": [[50, 50], [150, 50], [150, 150], [50, 150]], "to": 600},
    {"circle": {"centre": [500, 300], "radius": 25}, "to": 600},
]})


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


def fam(**fields):
    return "family " + json.dumps(fields)


def socket_with(symbols):
    return fam(**{**SOCKET, "symbols": symbols})


COMPONENTS = 'elements {"category": "component"}'

CASES = {
    # A desk family: types sized by parameters and formulas, components of it, instance and type parameters.
    "components_of_a_desk": (
        ["family " + DESK, 'component {"family": "Work Desk", "type": "1600 x 800", "at": [1000, 2000], "angle": 90}'],
        [
            [COMPONENTS],
            ['modify {"id": 100002, "params": {"Height": 720}, "offset": 100}', COMPONENTS],
            ['modify {"id": 100002, "params": {"Width": 5}}'],
            ['modify {"id": 100002, "params": {"Height": "tall"}}'],
            ['modify {"id": 100002, "params": {"Nope": 1}}'],
            [fam(name="Work Desk", types={"1600 x 800": {"Width": 0}})],
            [fam(name="Work Desk", types={"1600 x 800": {"Width": 1700}}), COMPONENTS],
            [fam(name="Work Desk", rename="Writing desk"), COMPONENTS, 'component {"family": "Work Desk", "at": [0, 0]}'],
            [fam(name="Work Desk", delete=True)],
            ['CM {"family": "Work Desk", "at": [0, 0], "mirrored": true, "offset": 50, "params": {"Height": 800}}', COMPONENTS],
            ['delete {"ids": [100002]}', fam(name="Work Desk", delete=True), 'family {"name": "Work Desk"}'],
            [fam(name="Work Desk", types={"1600 x 800": None}), fam(name="Work Desk")],
            [fam(name="Work Desk", rename="")],
            [fam(name="Work Desk", rename="Table")],
            ['component {"family": "Work Desk", "type": "9 x 9", "at": [0, 0]}'],
            ['component {"family": "Work Desk"}'],
            ['component {"at": [0, 0]}'],
            ['component {"family": "Work Desk", "at": [0, 0], "params": [1]}'],
            ['component {"family": "Work Desk", "at": [0, 0], "level": "Nowhere"}'],
            ['component {"family": "Work Desk", "at": [0, 0], "params": {"Height": null}}', COMPONENTS],
        ],
    ),
    # Reading: the list, one family with its values worked out, a dry run of a change and of a refused one.
    "read_and_dry_run": (
        ["family " + DESK],
        [
            ['family {}'],
            ['family {"name": "Work Desk"}', 'undo'],
            ['family {"name": "Nope"}'],
            ['family {"name": "Work Desk", "dry_run": true}'],
            [fam(name="Work Desk", dry_run=True,
                 parameters=[{"name": "Width", "value": 1200}, {"name": "Depth", "value": 600},
                             {"name": "Height", "instance": True, "value": 740}, {"name": "Top", "formula": "Height - 30"},
                             {"name": "Shelf", "value": 300}],
                 types={"1600 x 800": {"Depth": 900}, "1800 x 900": {"Width": 1800, "Depth": 900}}),
             'family {"name": "Work Desk"}'],
            [fam(name="Work Desk", dry_run=True, types={"1800 x 900": {"Width": 0}})],
            [fam(name="Work Desk", dry_run=True, rename="Bureau")],
            [fam(name="Work Desk", dry_run=True, delete=True), 'family {"name": "Work Desk"}'],
            ['family {"delete": true}'],
            ['family {"rename": "X"}'],
            ['family {"name": "Nope", "delete": true}'],
        ],
    ),
    # Forms patched and deleted one by one by id, the others keeping theirs; what names no form of it is refused.
    "patch_forms_by_id": (
        ["family " + SHELF],
        [
            ['library {"kind": "form", "name": "Shelf"}'],
            ['family {"name": "Shelf", "form": {"id": 999464, "to": 900}}', 'library {"kind": "form", "name": "Shelf"}'],
            ['family {"name": "Shelf", "form": {"id": 999463, "material": "Timber"}}',
             'family {"name": "Shelf", "form": {"id": 999463, "material": null}}'],
            ['family {"name": "Shelf", "delete_form": [999465]}', 'library {"kind": "form", "name": "Shelf"}'],
            ['family {"name": "Shelf", "dry_run": true, "form": {"id": 999464, "to": 900}, "delete_form": [999463]}'],
            ['family {"name": "Shelf", "form": {"id": 999000, "to": 1}}'],
            ['family {"name": "Shelf", "delete_form": [999000]}'],
            ['family {"name": "Shelf", "form": {"to": 1}}'],
            ['family {"name": "Shelf", "form": 5}'],
            ['family {"name": "Shelf", "form": {"id": "nope"}}'],
            ['family {"name": "Shelf", "form": {"id": 999464, "to": "tall"}}'],
            ['family {"name": "Shelf", "symbol": {"id": 999464}}'],
        ],
    ),
    # Warnings that don't stop a change come all at once; errors come with them.
    "warnings_and_errors": (
        [fam(name="Odd Door", category="door",
             parameters=[{"name": "Width", "value": 900}, {"name": "Height", "value": 2100}],
             types={"900 x 2100": {}},
             forms=[{"profile": [["-Width / 2", "-40"], ["Width / 2", "-40"], ["Width / 2", "40"], ["-Width / 2", 40]], "to": "Height"},
                    {"void": True, "profile": [[3000, 3000], [3200, 3000], [3200, 3200], [3000, 3200]], "to": 100},
                    {"profile": [[0, 0], [200, 0], [200, 200], [0, 200]], "from": 5000, "to": 5200},
                    {"profile": [[-100, -400], [100, -400], [100, 400], [-100, 400]], "to": 100}])],
        [
            ['family {"name": "Odd Door"}'],
            [fam(name="Odd Door", parameters=[{"name": "Width", "value": 900}, {"name": "Height", "value": 2100},
                                             {"name": "A", "formula": "Width + Nowhere"}, {"name": "B", "formula": "Height / -"}])],
            [fam(name="Odd Door", forms=[{"profile": [[0, 0], [1, 0]], "to": 100},
                                         {"void": True, "profile": [[3000, 3000], [3200, 3000], [3200, 3200], [3000, 3200]], "to": 100}])],
            [fam(name="Odd Door", parameters=[{"name": "Width", "value": 900}])],
            [fam(name="Odd Door", parameters=[{"name": "Width", "value": 900}, {"name": "Height", "value": 2100},
                                             {"name": "Wall Thickness", "value": 100}])],
            [fam(name="Odd Door", parameters=[{"name": "Width", "value": 900}, {"name": "Height", "kind": "number", "value": 2100}])],
        ],
    ),
    # Parameters and formulas: functions, chains, kinds, and every way one is refused.
    "formulas": (
        [fam(name="Calc", parameters=[
            {"name": "A", "value": 1000},
            {"name": "B", "formula": "if(A > 600, 4, 2)"},
            {"name": "C", "formula": "min(A, 300) + max(1, 2) * abs(-3) - sqrt(16) / 2 ^ 2"},
            {"name": "D", "formula": "round(A / 3) + roundup(1.2) + rounddown(1.8)"},
            {"name": "E", "kind": "angle", "value": 30},
            {"name": "F", "formula": "sin(E) * 1000 + cos(60) * 1000 + tan(45)"},
            {"name": "G", "kind": "yesno", "formula": "and(A > 1, or(B = 4, not(A < 0)))"},
            {"name": "H", "kind": "material", "value": "Timber"},
            {"name": "I", "kind": "number", "instance": True, "value": 2},
        ], types={"T": {"A": 2000}, "U": {}}, forms=[{"profile": [[0, 0], ["A", 0], ["A", 500], [0, 500]], "to": "B * 100", "material": "H"}])],
        [
            ['family {"name": "Calc"}'],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "B + 1"}, {"name": "B", "formula": "A + 1"}],
                 forms=[{"profile": [[0, 0], ["A", 0], ["A", 500], [0, 500]], "to": 100}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "foo(1)"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "sqrt(1, 2)"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "if(1, 2)"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "1 +"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "(1 + 2"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "1 2"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": ""}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "1 / 0"}],
                 forms=[{"profile": [[0, 0], ["A", 0], ["A", 500], [0, 500]], "to": 100}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "M", "kind": "material", "formula": "1"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "M", "kind": "material", "value": "Unobtainium"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "1st"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A"}, {"name": "A"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "Paint"}])],
            [fam(name="Bad", types={"T": {"Z": 1}}, parameters=[{"name": "A"}])],
            [fam(name="Bad", types={"T": {"I": 1}}, parameters=[{"name": "I", "instance": True}])],
            [fam(name="Bad", types={"T": {"F": 1}}, parameters=[{"name": "F", "formula": "2"}])],
            [fam(name="Bad", types={}, parameters=[{"name": "A"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "kind": "colour"}])],
            [fam(name="Bad", types={"T": {}}, category="spaceship")],
            [fam(name="Bad", types={"T": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "to": "A * 2"}])],
            [fam(name="Bad", types={"T": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "to": 100, "material": "Nope"}])],
            [fam(name="Bad", types={"T": {}}, parameters=[{"name": "Y", "kind": "yesno", "value": "maybe"}])],
        ],
    ),
    # Forms of every kind: swept in each plane, turned about an axis, voids cutting, triangles; what doesn't build.
    "forms": (
        [fam(name="Lamp", types={"A": {}}, forms=[
            {"plane": "xz", "profile": [[0, 0], [200, 0], [100, 400], [0, 400]], "axis": [[0, 0], [0, 400]], "from": 0, "to": 360,
             "material": "Metal"},
            {"plane": "yz", "profile": [[0, 0], [100, 0], [100, 100], [0, 100]], "from": -50, "to": 50},
            {"circle": {"centre": [0, 0], "radius": 300}, "from": 400, "to": 420, "visible": "1 > 0"},
            {"void": True, "circle": {"centre": [0, 0], "radius": 100}, "from": 390, "to": 430},
            {"mesh": [[[0, 0, 0], [100, 0, 0], [0, 100, 0]]]},
        ])],
        [
            ['family {"name": "Lamp"}', 'component {"family": "Lamp", "at": [500, 500]}', COMPONENTS],
            [fam(name="Bad", types={"A": {}}, forms=[{"plane": "xz", "profile": [[0, 0], [200, 0], [100, 400]],
                                                      "axis": [[0, 0], [0, 400]], "from": 0, "to": 400}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"plane": "xz", "profile": [[-100, 0], [200, 0], [100, 400]],
                                                      "axis": [[0, 0], [0, 400]], "to": 90}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"plane": "xz", "profile": [[0, 0], [200, 0], [100, 400]],
                                                      "axis": [[0, 0], [0, 0]], "to": 90}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"profile": [[0, 0], [0, 100], [0, 200]], "axis": [[0, 0], [0, 400]],
                                                      "plane": "xz", "to": 90}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"profile": [[0, 0], [100, 100], [100, 0], [0, 100]], "to": 100}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "from": 100, "to": 100}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"to": 100}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"circle": {"centre": [0, 0], "radius": 0}, "to": 100}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"circle": {"centre": [0, 0], "radius": 10}, "profile": [[0, 0], [1, 0], [1, 1]], "to": 100}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"mesh": [[[0, 0, 0], [100, 0, 0], [0, 100, 0]]], "axis": [[0, 0], [0, 1]]}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "to": 100, "plane": "zz"}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "to": 1e300}])],
            [fam(name="Bad", types={"A": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "to": 100, "colour": 1}])],
        ],
    ),
    # Plan symbols of every kind, and every symbol refused with what to fix.
    "symbols": (
        [fam(**SOCKET), 'component {"family": "Socket", "at": [1000, 1000], "params": {"Circuit": 12}}'],
        [
            ['family {"name": "Socket"}', COMPONENTS],
            ['family {"name": "Socket", "symbol": {"id": 999459, "dot": {"centre": [0, 0], "radius": 5}}}',
             'library {"kind": "symbol", "name": "Socket"}'],
            ['family {"name": "Socket", "delete_symbol": [999461, 999460]}', 'library {"kind": "symbol", "name": "Socket"}'],
            [socket_with([{"text": {"at": [0, 0], "height": 60, "value": "  "}}])],
            [socket_with([{"text": {"at": [0, 0], "height": 0, "value": "A"}}])],
            [socket_with([{"text": {"at": [0, 0], "height": -4, "value": "A"}}])],
            [socket_with([{"text": {"at": [0, 0], "height": "sqrt(0 - 1)", "value": "A"}}])],
            [socket_with([{"text": {"at": [0, 0], "height": 60, "value": "{Nope}"}}])],
            [socket_with([{"text": {"at": [0, 0], "height": 60, "value": "{Circuit"}}])],
            [socket_with([{"text": {"at": [0, 0], "height": 60, "value": "x" * 300}}])],
            [socket_with([{"text": {"at": [0, 0], "height": 60, "value": "A", "align": "up"}}])],
            [socket_with([{"text": {"at": [0, 0], "height": 60, "value": "A", "size": 1}}])],
            [socket_with([{"dot": {"centre": [0, 0], "radius": 0}}])],
            [socket_with([{"dot": {"centre": [0, 0], "radius": 1e300}}])],
            [socket_with([{"dot": {"centre": [0, 0], "radius": 1}, "text": {"at": [0, 0], "height": 5, "value": "A"}}])],
            [socket_with([{}])],
            [socket_with([{"arc": {"centre": [0, 0], "radius": 50, "from": 0, "to": 400}}])],
            [socket_with([{"line": [[0, 0], ["Nope", 0]]}])],
            [socket_with([{"line": [[0, 0]], "visible": "Show"}])],
        ],
    ),
    # Door and window families placed in walls, with how they open; a component's connectors.
    "hosted_and_connectors": (
        [BOX, 'door {"at": [2000, 0], "family": "Single Door", "type": "800 x 2100"}',
         'window {"at": [8000, 3000], "family": "Fixed Window", "type": "600 x 900"}'],
        [
            ['elements {"category": "door"}', 'elements {"category": "window"}'],
            ['family {"name": "Single Door", "operation": "sliding"}', 'elements {"category": "door"}'],
            ['family {"name": "Single Door", "operation": "rolling"}'],
            ['door {"at": [5000, 0], "family": "Single Door", "type": "Nope"}'],
            ['door {"at": [5000, 0], "family": "Table"}'],
            ['window {"at": [0, 3000], "family": "Casement Window"}', 'elements {"category": "window"}'],
            [fam(name="Plug", category="outlet", parameters=[{"name": "Load", "kind": "number", "value": 100}], types={"A": {}, "B": {"Load": 600}},
                 connectors=[{"kind": "power", "system": "power-balanced", "poles": 1, "voltage": 127, "load_va": "Load",
                              "power_factor": 0.9, "classification": "general"}]),
             'component {"family": "Plug", "type": "B", "at": [1000, 1000]}', COMPONENTS],
            [fam(name="Plug", category="outlet", types={"A": {}},
                 connectors=[{"kind": "power", "system": "power-balanced"}, {"kind": "power", "system": "power-balanced"}])],
            [fam(name="Plug", category="switch", types={"A": {}}, connectors=[{"kind": "switch", "system": "switch", "load_va": 10}])],
            [fam(name="Plug", category="outlet", types={"A": {}}, connectors=[{"kind": "power", "system": "switch"}])],
            [fam(name="Plug", category="outlet", types={"A": {}}, connectors=[{"kind": "switch", "system": "power-balanced"}])],
            [fam(name="Plug", category="outlet", types={"A": {}}, connectors=[{"kind": "power", "system": "power-balanced", "poles": 4}])],
            [fam(name="Plug", category="outlet", types={"A": {}}, connectors=[{"kind": "power", "system": "power-balanced", "voltage": 0}])],
            [fam(name="Plug", category="outlet", types={"A": {}}, connectors=[{"kind": "power", "system": "power-balanced", "voltage": 230, "power_factor": 1.5}])],
            [fam(name="Plug", category="outlet", types={"A": {}}, connectors=[{"kind": "power", "system": "power-balanced", "voltage": 230, "load_va": -1}])],
            [fam(name="Plug", category="outlet", types={"A": {}},
                 connectors=[{"kind": "power", "system": "power-unbalanced", "poles": 3, "voltage": 230, "load_va": [100, 200, 300]}]),
             'component {"family": "Plug", "at": [1000, 1000]}', COMPONENTS],
            [fam(name="Basin", category="plumbing", kind="wc", types={"A": {}}), 'family {"name": "Basin", "kind": ""}'],
            [fam(name="Basin", category="plumbing", kind="jacuzzi", types={"A": {}})],
            [fam(name="Basin", category="furniture", kind="wc", types={"A": {}})],
        ],
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_family_command(run, workdir, golden, case):
    """CATCHES: a rewrite whose families build different forms, work formulas out differently, lay out its family and
    component replies differently (values, warnings, changes of a dry run, part ids), keeps a change a dry run or a
    refusal should not make, or accepts or refuses a different set of definitions, with different words."""
    setup, probes = CASES[case]
    golden.check(session(run, workdir, setup, probes), f"{case}.txt")


def test_family_saved_to_a_file_and_loaded_from_one(run, workdir, golden):
    """CATCHES: a rewrite whose family file differs from the reference's (keys, order, numbers, ids), that loads a
    file's `delete` or `rename` instead of only the family, names a loaded family other than by `name`, the file's name
    or its stem, writes a file on a dry run, or words a file's problems differently."""
    (workdir / "chair.json").write_text(json.dumps({"name": "Chair", "delete": True, "rename": "Gone",
                                                    "types": {"Tall": {"Height": 1100}}}))
    (workdir / "list.json").write_text("[1, 2]")
    (workdir / "broken.json").write_text("{nope")
    (workdir / "plank.json").write_text(json.dumps({"types": {"A": {}}, "forms": [
        {"profile": [[0, 0], [2000, 0], [2000, 200], [0, 200]], "to": 30}]}))
    probes = [
        ['family {"name": "Work Desk", "save": "desk.json"}'],
        ['family {"name": "Work Desk", "save": "dry.json", "dry_run": true}'],
        ['family {"save": "x.json"}'],
        ['family {"name": "Nope", "save": "x.json"}'],
        ['family {"name": "Work Desk", "save": "nodir/x.json"}'],
        ['family {"path": "chair.json"}', 'family {"name": "Chair"}', 'family {"name": "Gone"}'],
        ['family {"path": "plank.json"}', 'family {}'],
        ['family {"path": "plank.json", "name": "Board", "dry_run": true}', 'family {"name": "Board"}'],
        ['family {"path": "list.json"}'],
        ['family {"path": "broken.json"}'],
        ['family {"path": "missing.json"}'],
    ]
    text = session(run, workdir, ["family " + DESK], probes)
    golden.check(text, "family_files.txt")
    golden.check(normalize((workdir / "desk.json").read_text()), "desk.json.golden")
    # (A coverage-instrumented build may leave its .profraw data behind; that is no file of the program's.)
    assert sorted(p.name for p in workdir.iterdir() if p.suffix != ".profraw") == ["broken.json", "chair.json", "desk.json", "list.json",
                                                          "p.bimcraft", "plank.json", "setup.txt"]
    # The saved file loads back into another project as the same family.
    r = run(["run", "--cmd", 'family {"path": "desk.json", "name": "Loaded"}', "--cmd", 'family {"name": "Loaded"}'])
    golden.check_run(r, "desk_loaded_back.txt")


def test_a_form_patched_by_its_guid(run, workdir, golden):
    """CATCHES: a rewrite that patches a family's form by GUID differently from by id: a different form, other forms'
    ids or GUIDs changed, or a field given as null not taken away."""
    r = run(["run", "--cmd", "family " + SHELF, "--save", "p.bimcraft"])
    assert r.returncode == 0, r.stderr.decode()
    forms = json.loads((workdir / "p.bimcraft").read_text())["families"]["Shelf"]["forms"]
    guid = forms[2]["guid"]
    r = run(["run", "p.bimcraft", "--cmd", 'family {"name": "Shelf", "form": {"guid": "%s", "material": "Timber", "from": 10}}' % guid,
             "--cmd", 'family {"name": "Shelf", "form": {"guid": "%s", "from": null}}' % guid.upper(),
             "--cmd", 'library {"kind": "form", "name": "Shelf"}',
             "--cmd", 'family {"name": "Shelf", "delete_form": ["%s"]}' % guid, "--cmd", 'family {"name": "Shelf"}'])
    golden.check_run(r, "patch_by_guid.txt")


def test_symbols_are_drawn_in_the_plan(run, workdir, golden):
    """CATCHES: a rewrite that draws a family's plan symbols (line, arc hidden by its yes/no, text reading a parameter,
    dot) elsewhere, turned or mirrored the wrong way, lettered differently, or not at all."""
    r = run(["run", "--cmd", fam(**SOCKET), "--cmd", 'component {"family": "Socket", "at": [1000, 1000], "angle": 90}',
             "--cmd", 'component {"family": "Socket", "at": [3000, 1000], "mirrored": true, "params": {"Show": 0, "Circuit": 12}}',
             "--save", "plan.svg"])
    golden.check_run(r, "symbols_plan.txt")
    golden.check((workdir / "plan.svg").read_text(), "symbols_plan.svg")


SYMBOL_SETS = {
    "english_twice": ["--cmd", 'symbol_set {"set": "arei"}', "--cmd", 'symbol_set {"set": "arei"}', "--cmd", 'family {}'],
    "dutch": ["--cmd", 'symbol_set {"set": "arei", "names": "nl"}', "--cmd", 'family {"name": "Bel"}'],
    "dutch_project": ["--cmd", 'new {"language": "nl"}', "--cmd", 'symbol_set {"set": "arei"}'],
    "french_project": ["--cmd", 'new {"language": "fr"}', "--cmd", 'symbol_set {"set": "arei"}'],
    "english_in_dutch_project": ["--cmd", 'new {"language": "nl"}', "--cmd", 'symbol_set {"set": "arei", "names": "en"}'],
    "no_set": ["--cmd", 'symbol_set {}'],
    "unknown_set": ["--cmd", 'symbol_set {"set": "iec"}'],
    "bad_names": ["--cmd", 'symbol_set {"set": "arei", "names": "de"}'],
}


@pytest.mark.parametrize("case", sorted(SYMBOL_SETS))
def test_symbol_set(run, golden, case):
    """CATCHES: a rewrite whose AREI symbol set loads different families (names, categories, symbols), picks the names'
    language differently, overwrites a family the project has, or words its refusals differently."""
    r = run(["run", *SYMBOL_SETS[case]])
    golden.check_run(r, f"symbol_set_{case}.txt")


def _png_size(data):
    """A PNG's width and height, from its header."""
    import struct
    assert data[:8] == b"\x89PNG\r\n\x1a\n", data[:16]
    return struct.unpack(">II", data[16:24])


def test_a_family_is_drawn_on_its_own_and_the_project_is_left_alone(run, workdir, golden):
    """CATCHES: a rewrite whose `render {family}` keeps an element or an undo step in the project, draws at another size
    or from another side than its reply says, picks another type, or refuses an unknown family, type, mode or wall
    thickness in other words."""
    out = []
    for cmd in ['render {"family": "Table", "path": "f.png", "width": 200, "height": 150}',
                'render {"family": "Single Door", "type": "800 x 2100", "mode": "plan", "path": "d.png", "wall_thickness": 300}',
                'render {"family": "Table", "mode": "elevation", "path": "e.png"}',
                'render {"family": "Nope"}', 'render {"family": "Table", "type": "9"}', 'render {"family": "Table", "mode": "side"}',
                'render {"family": "Single Door", "wall_thickness": -5}']:
        r = run(["run", "--cmd", BOX, "--cmd", cmd, "--cmd", 'elements {"category": "component"}', "--cmd", "undo", "--cmd", "undo"])
        out.append(f"=== {cmd}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}")
    sizes = {name: _png_size((workdir / name).read_bytes()) for name in ("f.png", "d.png", "e.png")}
    golden.check("".join(out) + f"sizes: {sorted(sizes.items())}\n", "family_render.txt")


MORE_FAMILY = [
    fam(name="Calc", types={"T": {}}, parameters=[{"name": "A", "value": 2.5e3}, {"name": "B", "formula": "1.5e2 + 2E-1 - A / 1e3"},
                                                  {"name": "C", "kind": "yesno", "formula": "A >= 2500"}, {"name": "D", "kind": "yesno", "value": True},
                                                  {"name": "M", "kind": "material", "value": None}]),
    fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "max()"}]),
    fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "min(1 2)"}]),
    fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "1 + )"}]),
    fam(name="Bad", types={"T": {}}, parameters=[{"name": "A", "formula": "1 + " * 300 + "1"}]),
    fam(name="Bad", types={"": {}}, parameters=[{"name": "A"}]),
    fam(name="Bad", types={"T": {"M": "Unobtainium"}}, parameters=[{"name": "M", "kind": "material"}]),
    fam(name="Bad", types={"T": {}}, parameters=[{"name": "M", "kind": "material"}, {"name": "L", "formula": "M * 2"}]),
    fam(name="Bad", types={"T": {}}, forms=[{"profile": [[0, 0], [300, 0], [300, 100], [100, -100]], "to": 100}]),
    fam(name="Bad", types={"T": {}}, forms=[{"profile": [[0, 0], [100, 0], [100, 100]], "to": "1 + " * 300 + "1"}]),
    fam(name="Bad", category="outlet", types={"T": {}},
        connectors=[{"kind": "power", "system": "power-balanced", "voltage": 230, "load_va": [100, 200]}]),
    fam(name="Bad", category="outlet", types={"T": {}},
        connectors=[{"kind": "power", "system": "power-balanced", "voltage": 230, "classification": "x" * 300}]),
]


def test_more_formulas_values_and_refusals(run, golden):
    """CATCHES: a rewrite whose formulas read numbers in exponent notation, >= and yes/no values differently, or refuse
    a function of no values, a missing comma, a stray `)`, a formula too long, an unnamed type, a type's material the
    library hasn't, a material used as a number, a profile that crosses itself, a balanced connector given a load per
    phase, or a long classification in other words; and one whose labels read a material by its name."""
    out = []
    for cmd in MORE_FAMILY:
        r = run(["run", "--cmd", cmd])
        out.append(f"=== {cmd[:200]}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "more_formulas.txt")


def test_a_label_reads_a_material_by_its_name_and_aligns(run, workdir, golden):
    """CATCHES: a rewrite whose plan symbol text reads a material parameter other than by the material's name, or
    anchors a centred or right-aligned label elsewhere."""
    label = fam(name="Label", category="lighting", types={"T": {}}, parameters=[{"name": "M", "kind": "material", "value": "Timber"}],
                symbols=[{"text": {"at": [0, 0], "height": 300, "value": "{M}", "align": "center"}},
                         {"text": {"at": [0, -500], "height": 300, "value": "R", "align": "right"}}])
    r = run(["run", "--cmd", label, "--cmd", 'component {"family": "Label", "at": [2000, 2000]}', "--save", "plan.svg"])
    golden.check_run(r, "label_plan.txt")
    golden.check((workdir / "plan.svg").read_text(), "label_plan.svg")
