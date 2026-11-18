"""Projects as files (save, open, info, convert, lenient reading, migration, autosave and recovery, insert and link), and
what reads the model: schedules and their exports, the library, selection and inquiry, units, languages and history."""

import hashlib
import json
import re
import shutil

import pytest

from conftest import base_env, canonical_ifc, normalize, run_executable


@pytest.fixture(scope="session")
def sample_project(tmp_path_factory):
    """The sample house, built once and saved: opening it is much quicker than building it again."""
    d = tmp_path_factory.mktemp("sample")
    (d / "home").mkdir()
    p = run_executable(["run", "--sample", "--save", "sample.bimcraft"], cwd=d, env=base_env(d / "home"), timeout=600)
    assert p.returncode == 0, p.stderr
    return d / "sample.bimcraft"


@pytest.fixture
def sample(sample_project, workdir):
    """`sample.bimcraft` in the test's working directory; `run sample.bimcraft …` opens it."""
    shutil.copy(sample_project, workdir / "sample.bimcraft")
    return "sample.bimcraft"


def digest(sc, path: str):
    """Record a big text file the program wrote by the length and sha256 of its normalised text (its random GUIDs and
    uid, whose digits vary in number, replaced; an IFC file canonical too)."""
    text = (sc.workdir / path).read_text(encoding="utf-8")
    if path.endswith(".ifc"):
        text = canonical_ifc(text)  # its relationships come in an order that follows its random GUIDs
    text = normalize(text)
    sc.note(f"=== file {path}: {len(text)} normalised characters, sha256={hashlib.sha256(text.encode()).hexdigest()}")


def listing(sc):
    """The files in the working directory, by name, but for coverage data an instrumented build may leave there."""
    names = sorted(str(p.relative_to(sc.workdir)) for p in sc.workdir.rglob("*") if p.is_file() and p.suffix != ".profraw")
    sc.note("=== files: " + ", ".join(names))


def scrub(sc, pattern: str, repl: str):
    """Replace a volatile part (a temporary file's random name) in what the scenario has recorded so far."""
    sc.parts = [re.sub(pattern, repl, part) for part in sc.parts]

# A small house: four walls, a partition, a door in each, two rooms and a floor.
HOUSE = [
    'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true, "type": "Exterior - 300mm"}',
    'wall {"points": [[5000,0],[5000,6000]], "type": "Interior - 100mm"}',
    'door {"at": [2000, 0]}',
    'door {"at": [5000, 3000], "type": "Single 800 x 2100"}',
    'window {"at": [8000, 3000]}',
    'window {"at": [2500, 6000], "sill": 1100}',
    'room {"point": [2500, 3000], "name": "Living"}',
    'room {"point": [6500, 3000], "name": "Bedroom"}',
    "floor {}",
]


def house_args(*extra: str) -> list[str]:
    args = ["run"]
    for c in [*HOUSE, *extra]:
        args += ["--cmd", c]
    return args


# A project file written by hand: the fields this version reads, and a few it doesn't know.
LENIENT = """{"format": 17, "name": "Tiny", "uid": 42, "colour": "blue", "next_id": 100003,
 "types": {"wall": {"Generic - 200mm": {"thickness": 200.0, "fancy": 1}}, "floor": {}, "door": {}, "window": {}},
 "elements": {
  "100000": {"guid": "11111111-1111-4111-8111-111111111111", "category": "level", "name": "Ground", "elevation": 0.0, "mood": "happy"},
  "100001": {"guid": "22222222-2222-4222-8222-222222222222", "category": "level", "name": "First", "elevation": 3200.0},
  "100002": {"guid": "33333333-3333-4333-8333-333333333333", "category": "wall", "type": "Generic - 200mm",
             "level": "11111111-1111-4111-8111-111111111111", "start": [0, 0], "end": [5000, 0], "height": 3200.0, "colour": [1, 2, 3]}
 }}
"""

# A file from before element GUIDs (no `format`): small ids, and references by id.
FORMAT_ZERO = """{"name": "Old", "uid": 7, "next_id": 5,
 "types": {"wall": {"Generic - 200mm": {"thickness": 200.0}}, "floor": {}, "door": {"Single 900 x 2100": {"width": 900, "height": 2100}}, "window": {}},
 "elements": {
  "1": {"category": "level", "name": "Level 1", "elevation": 0.0},
  "2": {"category": "level", "name": "Level 2", "elevation": 3000.0},
  "3": {"category": "wall", "type": "Generic - 200mm", "level": 1, "start": [0, 0], "end": [6000, 0], "height": 3000.0},
  "4": {"category": "door", "type": "Single 900 x 2100", "host": 3, "offset": 2000}
 }}
"""


# ---------------------------------------------------------------------------------------------------------------------
# Saving, opening, info and convert
# ---------------------------------------------------------------------------------------------------------------------


def test_sample_saved_then_opened_and_inspected(sc):
    """CATCHES: a project file that loses elements, types, ids or GUID links on a save and open round trip, or an `info`
    whose pretty-printed levels, counts, types and warnings differ."""
    sc.run(["run", "--sample", "--save", "house.bimcraft"])
    digest(sc, "house.bimcraft")
    sc.run(["info", "house.bimcraft"])
    sc.run(["run", "house.bimcraft", "--cmd", 'elements {"category": "room"}', "--cmd", 'elements {"category": "door"}'])
    assert sc.transcript() == sc.golden()


def test_small_project_file_contents(sc):
    """CATCHES: a .bimcraft writer that orders keys differently, drops the library section, writes ids or GUID references
    in another shape, or indents the JSON another way."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0],[4000,3000]], "type": "Interior - 100mm"}',
            "--cmd", 'room_separator {"points": [[0,0],[0,3000]]}', "--save", "small.bimcraft"])
    sc.file("small.bimcraft")
    assert sc.transcript() == sc.golden()


def test_open_then_save_without_a_path_writes_back(sc):
    """CATCHES: `save {}` after opening a file not writing back to the file it came from, or `info` not seeing the change."""
    sc.run(house_args("save {\"path\": \"house.bimcraft\"}"), show=False)
    sc.run(["run", "house.bimcraft", "--cmd", 'wall {"points": [[0,-3000],[3000,-3000]]}', "--cmd", "save {}",
            "--cmd", 'elements {"category": "wall", "limit": 1, "offset": 5}'])
    p = sc.run(["info", "house.bimcraft"], show=False)
    info = json.loads(p.stdout)
    sc.note(json.dumps({k: info[k] for k in ("counts", "levels", "name", "path", "warnings", "history")}, indent=1))
    assert sc.transcript() == sc.golden()


def test_run_then_save_in_order_of_the_arguments(sc):
    """CATCHES: `run` that saves after all commands instead of where --save stands: the first file must hold one wall and
    the second two."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--save", "one.bimcraft",
            "--cmd", 'wall {"points": [[0,0],[0,4000]]}', "--save", "two.bimcraft"])
    for f in ("one.bimcraft", "two.bimcraft"):
        p = sc.run(["info", f], show=False)
        sc.note(f"{f}: {json.dumps(json.loads(p.stdout)['counts'])} history={json.loads(p.stdout)['history']}")
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("ext", ["bimcraft", "svg", "ifc"])
def test_convert_a_project(sc, ext):
    """CATCHES: `convert` that fails on a project, prints another reply, or writes other contents than `run … --save`
    would for the same project and format."""
    sc.run(house_args('save {"path": "house.bimcraft"}'), show=False)
    sc.run(["convert", "house.bimcraft", f"out.{ext}"])
    digest(sc, f"out.{ext}")
    assert sc.transcript() == sc.golden()


def test_convert_and_info_errors(sc):
    """CATCHES: convert or info of a file that is missing, or convert to a folder that doesn't exist, not failing with the
    path and the system's reason."""
    sc.run(["run", "--save", "p.bimcraft"], show=False)
    sc.run(["convert", "missing.bimcraft", "out.ifc"])
    sc.run(["convert", "p.bimcraft", "no/such/dir/out.bimcraft"])
    sc.run(["info", "missing.ifc"])
    scrub(sc, r"/\.tmp[A-Za-z0-9]{6}\b", "/.tmp<RANDOM>")
    listing(sc)
    assert sc.transcript() == sc.golden()


def test_unknown_fields_are_left_out_and_listed(sc):
    """CATCHES: a reader that refuses a file with fields it doesn't know (or keeps them), or lists `left_out` paths in
    another form or order; once saved again, the file opens with nothing left out."""
    sc.write("tiny.bimcraft", LENIENT)
    sc.run(["run", "tiny.bimcraft", "--cmd", "elements {}", "--save", "again.bimcraft"])
    sc.run(["run", "again.bimcraft"])
    sc.run(["info", "tiny.bimcraft"])
    assert sc.transcript() == sc.golden()


def test_a_file_from_before_guids_is_migrated(sc):
    """CATCHES: a reader of a file with no `format` that doesn't move small ids up to six digits, give GUIDs, or turn the
    references by id into references to the right elements."""
    sc.write("old.bimcraft", FORMAT_ZERO)
    sc.run(["run", "old.bimcraft", "--cmd", "elements {}", "--cmd", 'wall {"points": [[0,0],[0,3000]]}'])
    assert sc.transcript() == sc.golden()


def test_a_file_of_a_newer_format_is_refused(sc):
    """CATCHES: a reader that opens a file saved by a newer version instead of refusing it, naming both format numbers."""
    sc.write("new.bimcraft", FORMAT_ZERO.replace('"name": "Old"', '"format": 18, "name": "Old"'))
    sc.write("big.bimcraft", FORMAT_ZERO.replace('"name": "Old"', '"format": 1000000, "name": "Old"'))
    sc.run(["run", "new.bimcraft"])
    sc.run(["info", "big.bimcraft"])
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"{not json", id="bad_json"),
        pytest.param(b'{"format": "x"}', id="format_text"),
        pytest.param(b'{"format": 17}', id="missing_fields"),
        pytest.param(b"\xff\xfe\x00{", id="not_utf8"),
        pytest.param(b"[1, 2]", id="array"),
        pytest.param(b'{"format": 17, "name": 5, "uid": 1, "next_id": 1, "elements": {},'
                     b' "types": {"wall": {}, "floor": {}, "door": {}, "window": {}}}', id="name_number"),
        pytest.param(b'{"format": 17, "name": "N", "uid": 1, "next_id": 1, "types": {"wall": {}, "floor": {}, "door": {}, "window": {}},'
                     b' "elements": {"100000": {"category": "teapot"}}}', id="unknown_category"),
        pytest.param(b"null", id="null"),
    ],
)
def test_files_that_are_not_projects(sc, content):
    """CATCHES: a reader that crashes, opens an empty model, or words the error differently for a file that isn't a
    project: empty, malformed JSON, a format that isn't a number, missing fields, bytes that aren't UTF-8."""
    sc.write("bad.bimcraft", content)
    sc.run(["info", "bad.bimcraft"])
    sc.run(["run", "bad.bimcraft", "--cmd", "inspect {}"])
    assert sc.transcript() == sc.golden()


def test_open_parameter_errors(sc):
    """CATCHES: `open` without a path, with a path that isn't text or is longer than 256 characters, or of a folder,
    being accepted or worded differently."""
    (sc.workdir / "folder.bimcraft").mkdir()
    sc.cmds("open {}")
    sc.cmds('open {"path": 5}')
    sc.cmds(json.dumps({"path": "a" * 300}).join(["open ", ""]))
    sc.cmds('open {"path": "folder.bimcraft"}')
    sc.cmds('open {"path": "x.bimcraft", "extra": 1}')
    assert sc.transcript() == sc.golden()


def test_a_failed_open_keeps_the_project(sc):
    """CATCHES: a failing `open` that replaces or empties the project it was asked from instead of changing nothing."""
    sc.cmds('wall {"points": [[0,0],[4000,0]]}', 'open {"path": "missing.bimcraft"}')
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--script", "/dev/null", "--cmd",
            'level {"elevation": 4000}', "--cmd", 'elements {"category": "level"}'])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# New projects, languages, units, room areas
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["en", "pt", "es", "sv", "cs", "fr", "nl", "de"])
def test_new_project_in_each_language(sc, code):
    """CATCHES: `new` naming its levels, a new level, room, section, sheet and the standard schedules in the wrong
    language, or not recording the project's language."""
    sc.cmds(
        f'new {{"name": "Casa", "language": "{code}"}}',
        'level {"elevation": 6000}',
        'wall {"points": [[0,0],[4000,0],[4000,3000],[0,3000]], "closed": true}',
        'room {"point": [2000, 1500]}',
        'section {"start": [-1000, 1500], "end": [5000, 1500]}',
        "sheet {}",
        'schedule {"category": "levels"}',
        'schedule {"category": "rooms"}',
        'elements {"category": "level"}',
    )
    assert sc.transcript() == sc.golden()


def test_language_command_and_unknown_codes(sc):
    """CATCHES: `language` not reporting the code, renaming what is already named, or accepting a code it has no words
    for; and `new` accepting an unknown language."""
    sc.cmds("language {}", 'language {"code": "fr"}', 'level {"elevation": 7000}', "language {}",
            'elements {"category": "level"}')
    sc.cmds('language {"code": "xx"}')
    sc.cmds('new {"language": "klingon"}')
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("unit", ["mm", "cm", "m", "in", "ft", "ft-in"])
def test_units_change_what_schedules_show_not_commands(sc, unit):
    """CATCHES: `units` that changes the model's millimetres, or a schedule's CSV that doesn't format lengths and areas
    in the project's units."""
    sc.run(house_args(
        f'units {{"length": "{unit}"}}',
        "units {}",
        'schedule {"category": "walls", "path": "walls.csv"}',
        'schedule {"category": "rooms", "path": "rooms.csv"}',
        'elements {"category": "wall", "limit": 1}',
    ))
    sc.file("walls.csv")
    sc.file("rooms.csv")
    assert sc.transcript() == sc.golden()


def test_unknown_unit_is_refused(sc):
    """CATCHES: `units` accepting a unit it doesn't list, or naming the choices differently."""
    sc.cmds('units {"length": "furlong"}')
    sc.cmds('units {"length": 5}')
    assert sc.transcript() == sc.golden()


def test_room_area_at_centre_and_at_finish(sc):
    """CATCHES: rooms measured at the wrong faces: `finish` must shrink each room's area and perimeter to the walls'
    faces, and `centre` give back the centre-line values."""
    sc.run(house_args(
        'schedule {"category": "rooms"}',
        'room_area {"at": "finish"}',
        "room_area {}",
        'schedule {"category": "rooms"}',
        'room_area {"at": "centre"}',
        'schedule {"category": "rooms"}',
        'room_area {"at": "outside"}',
    ))
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------------------------------------------------


def test_undo_and_redo_steps(sc):
    """CATCHES: undo or redo that take back the wrong number of steps, forget redo after a new change, or report the
    history in inspect differently."""
    p = sc.run(house_args(
        "undo {}",
        'undo {"count": 2}',
        "redo {}",
        'level {"elevation": 9000}',
        "redo {}",
        'undo {"count": 100}',
        'elements {"category": "wall"}',
    ))
    sc.note(f"exit {p.returncode}")
    p = sc.run(house_args("undo {\"count\": 3}", "redo {\"count\": 2}", "inspect {}"), show=False)
    sc.note(json.dumps(json.loads(p.stdout.splitlines()[-1])["history"]))
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Autosave and recovery
# ---------------------------------------------------------------------------------------------------------------------


def test_autosave_keeps_the_project_path_and_recover_saves_to_the_project(sc):
    """CATCHES: autosave that changes where Save writes or the undo history, or a recovered snapshot whose Save doesn't
    go to the `project` it names."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--save", "house.bimcraft",
            "--cmd", 'wall {"points": [[0,0],[0,4000]]}',
            "--cmd", 'autosave {"path": "house.bimcraft.autosave.bimcraft"}',
            "--cmd", "undo {}", "--cmd", "save {}"])
    sc.note("saved: " + json.dumps(json.loads(sc.run(["info", "house.bimcraft"], show=False).stdout)["counts"]))
    sc.run(["run", "--cmd", 'recover {"path": "house.bimcraft.autosave.bimcraft", "project": "house.bimcraft"}',
            "--cmd", 'elements {"category": "wall"}', "--cmd", "save {}"])
    sc.note("after recovery: " + json.dumps(json.loads(sc.run(["info", "house.bimcraft"], show=False).stdout)["counts"]))
    listing(sc)
    assert sc.transcript() == sc.golden()


def test_recover_without_a_project_asks_for_save_as(sc):
    """CATCHES: a recovered untitled snapshot that saves over the snapshot itself, or recover of a missing or broken
    snapshot not failing as open does."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--cmd", 'autosave {"path": "untitled.autosave.bimcraft"}'])
    sc.cmds('recover {"path": "untitled.autosave.bimcraft"}', "inspect {}", "save {}")
    sc.cmds('recover {"path": "missing.bimcraft"}')
    sc.write("broken.bimcraft", "{")
    sc.cmds('recover {"path": "broken.bimcraft"}')
    sc.cmds("autosave {}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Insert from file and links
# ---------------------------------------------------------------------------------------------------------------------

OTHER = [
    'new {"name": "Other"}',
    'level {"elevation": 6000, "name": "Roof"}',
    'wall {"points": [[0,0],[3000,0],[3000,3000]], "type": "Exterior - 300mm"}',
    'door {"at": [1500, 0]}',
    'wall {"points": [[0,0],[0,2000]], "level": "Roof"}',
    'parameter {"name": "Fire Rating", "categories": ["wall"]}',
    'type {"category": "wall", "name": "Thick 450", "thickness": 450}',
    'wall {"points": [[0,5000],[3000,5000]], "type": "Thick 450"}',
    'save {"path": "other.bimcraft"}',
]


def test_insert_everything_and_then_some_ids_again(sc):
    """CATCHES: Insert from File that renumbers ids it could keep, doesn't suffix clashing names with ` 2`, doesn't bring
    in the types and parameters the elements need, or that doesn't make copies with new ids of what is already here."""
    sc.cmds(*OTHER)
    sc.cmds('wall {"points": [[0,0],[1000,0]]}', 'insert {"path": "other.bimcraft"}', 'insert {"path": "other.bimcraft", "ids": [100003]}',
            'elements {"category": "wall"}', 'elements {"category": "level"}', 'elements {"category": "door"}',
            'library {"kind": "type:wall"}', 'library {"kind": "parameter"}')
    assert sc.transcript() == sc.golden()


def test_insert_a_project_into_itself_copies_it_whole(sc):
    """CATCHES: inserting a project into a copy of itself that skips elements whose GUIDs are already here instead of
    copying them with new GUIDs and ids."""
    sc.cmds(*OTHER)
    sc.run(["run", "other.bimcraft", "--cmd", 'insert {"path": "other.bimcraft"}', "--cmd", 'elements {"category": "level"}'])
    sc.run(["run", "other.bimcraft", "--cmd", 'insert {"path": "other.bimcraft", "ids": [100004]}',
            "--cmd", 'elements {"category": "door"}'])
    assert sc.transcript() == sc.golden()


def test_insert_errors(sc):
    """CATCHES: insert of a missing file, of ids the file hasn't, or without a path being accepted or worded otherwise."""
    sc.cmds(*OTHER)
    sc.cmds('insert {"path": "missing.bimcraft"}')
    sc.cmds('insert {"path": "other.bimcraft", "ids": [123456]}')
    sc.cmds("insert {}")
    sc.cmds('insert {"path": "other.bimcraft", "ids": "all"}')
    assert sc.transcript() == sc.golden()


def test_link_reload_and_a_link_whose_file_went(sc):
    """CATCHES: a link not counting the other project's elements, not kept by its relative path in the saved project,
    or a missing file not reported in `links_not_loaded` on open and in `failed` on reload."""
    sc.cmds(*OTHER)
    sc.cmds('link {"path": "other.bimcraft", "at": [10000, 0], "angle": 90, "name": "Neighbour"}', "reload {}",
            'elements {"category": "link"}', 'save {"path": "host.bimcraft"}')
    sc.run(["run", "host.bimcraft", "--cmd", 'reload {"id": 100002}'])
    (sc.workdir / "other.bimcraft").rename(sc.workdir / "gone.bimcraft")
    sc.run(["run", "host.bimcraft", "--cmd", "reload {}", "--cmd", "inspect {}"], show=False)
    sc.run(["run", "host.bimcraft", "--cmd", "reload {}"])
    sc.cmds('link {"path": "nope.bimcraft"}')
    sc.cmds("link {}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    ["rooms", "doors", "windows", "walls", "floors", "ceilings", "roofs", "components", "levels", "Room", "DOOR"],
)
def test_each_categorys_own_schedule_of_the_sample(sc, sample, category):
    """CATCHES: a category's standard schedule with other columns, rows, row order, element ids, available fields or
    name, or category names not read in any case, singular or plural."""
    sc.run(["run", sample, "--cmd", f'schedule {{"category": "{category}"}}'])
    assert sc.transcript() == sc.golden()


def test_schedules_of_categories_with_elements_of_their_own(sc):
    """CATCHES: schedules of columns, structural columns, footings, beams, pipes, stairs, ramps and railings that list
    other default fields or values than the elements hold."""
    sc.cmds(
        'column {"at": [0, 0]}',
        'column {"at": [4000, 0], "type": "Round 300"}',
        'structural_column {"at": [0, 4000]}',
        'footing {"at": [0, 0]}',
        'beam {"points": [[0, 0], [4000, 0], [4000, 4000]], "offset": 3000}',
        'pipe {"points": [[0, 1000], [6000, 1000]], "offset": 500, "end_offset": 400}',
        'stair {"start": [8000, 0], "end": [8000, 4000], "railings": true}',
        'ramp {"start": [12000, 0], "height": 600}',
        'schedule {"category": "columns"}',
        'schedule {"category": "structural columns"}',
        'schedule {"category": "footings"}',
        'schedule {"category": "beams"}',
        'schedule {"category": "pipes"}',
        'schedule {"category": "stairs"}',
        'schedule {"category": "ramps"}',
        'schedule {"category": "railings"}',
    )
    assert sc.transcript() == sc.golden()


def test_schedule_fields_calculated_totals_and_descending_sort(sc, sample):
    """CATCHES: calculated fields worked out wrongly (lengths in mm, areas in m²), totals missing or summed over the
    wrong column, a heading not used, or a descending sort not applied."""
    sc.run(["run", sample, "--cmd", json.dumps({
        "name": "Paint", "category": "rooms",
        "fields": ["Name", "Perimeter", {"name": "Paint", "formula": "Perimeter * 2600 / 1000000", "kind": "area",
                                         "total": True, "heading": "Paint area"},
                   {"name": "Area", "total": True}, {"name": "Big", "formula": "Area > 15", "kind": "yesno"},
                   {"name": "Cost", "formula": "Area * 120", "kind": "number", "total": True}],
        "sort": [{"field": "Area", "descending": True}, "Name"],
    }).join(["schedule ", ""]), "--cmd", 'schedule {"name": "Paint"}'])
    assert sc.transcript() == sc.golden()


def test_schedule_grouped_counts_and_blank_differing_values(sc, sample):
    """CATCHES: grouping that doesn't sum Count, keeps values that differ inside a group instead of leaving them empty,
    or orders the groups another way."""
    sc.run(["run", sample, "--cmd",
            'schedule {"name": "Doors by type", "category": "doors", "fields": ["Type", "Width", "Count", "Mark", "Family"], "sort": ["Type"], "grouped": true}',
            "--cmd", 'schedule {"name": "Doors by type", "grouped": false}',
            "--cmd", 'schedule {"name": "Wall types", "category": "walls", "fields": ["Type", {"name": "Length", "total": true}, "Count"], "sort": ["Type"], "grouped": true}'])
    assert sc.transcript() == sc.golden()


FILTER_CASES = [
    ("equals", "Name", "Kitchen"),
    ("equals", "Area", 14),
    ("not-equals", "Name", "kitchen"),
    ("greater", "Area", 14),
    ("greater-or-equal", "Area", 18),
    ("less", "Perimeter", 18000),
    ("less-or-equal", "Perimeter", 18000),
    ("contains", "Name", "t"),
    ("not-contains", "Name", "T"),
    ("begins-with", "Name", "s"),
    ("not-begins-with", "Name", "B"),
    ("ends-with", "Name", "EN"),
    ("not-ends-with", "Name", "y"),
    ("has-value", "Finish", None),
    ("has-no-value", "Finish", None),
    ("equals", "Accessible", True),
    ("not-equals", "Accessible", True),
]


@pytest.mark.parametrize("op,field,value", FILTER_CASES, ids=[f"{o}-{f}-{v}" for o, f, v in FILTER_CASES])
def test_schedule_filter_operators(sc, sample, op, field, value):
    """CATCHES: a schedule filter operator that compares in the wrong direction, is case sensitive for text, compares
    numbers other than as shown, or treats an unset yes or no as anything but no."""
    rule = {"field": field, "op": op}
    if value is not None:
        rule["value"] = value
    sc.run(["run", sample,
            "--cmd", 'parameter {"name": "Finish", "categories": ["room"]}',
            "--cmd", 'parameter {"name": "Accessible", "kind": "yesno", "categories": ["room"]}',
            "--cmd", 'modify {"id": 100025, "params": {"Finish": "Oak", "Accessible": true}}',
            "--cmd", 'modify {"id": 100027, "params": {"Finish": "Tile", "Accessible": false}}',
            "--cmd", json.dumps({"name": "Filtered", "category": "rooms", "fields": ["Name", "Area", "Perimeter", "Finish", "Accessible"],
                                 "filters": [rule]}).join(["schedule ", ""])])
    assert sc.transcript() == sc.golden()


def test_multicategory_schedule_and_its_csv(sc, sample):
    """CATCHES: a multi-category schedule that lists other categories, rows or shared fields (an area worked out for walls,
    doors and windows; the structure layer's material), or a CSV that quotes or leaves cells differently."""
    sc.run(["run", sample,
            "--cmd", 'schedule {"name": "Openings and walls", "category": "multicategory", "categories": ["walls", "doors", "windows"], "fields": ["Category", "Type", "Area", "Material", "Count"], "path": "all.csv"}',
            "--cmd", 'schedule {"name": "Everything", "category": "multicategory", "sort": ["Category", "Type"], "grouped": true}'])
    sc.file("all.csv")
    assert sc.transcript() == sc.golden()


def test_schedule_csv_guards_formulas_and_quotes(sc):
    """CATCHES: CSV export that doesn't quote cells with commas or quotes, or doesn't guard text a spreadsheet would read
    as a formula (=, +, -, @) with a leading apostrophe."""
    sc.cmds(
        'wall {"points": [[0,0],[3000,0],[3000,3000],[0,3000]], "closed": true}',
        'wall {"points": [[6000,0],[9000,0],[9000,3000],[6000,3000]], "closed": true}',
        'wall {"points": [[12000,0],[15000,0],[15000,3000],[12000,3000]], "closed": true}',
        'room {"point": [1500, 1500], "name": "=SUM(A1:A9)", "number": "-1"}',
        'room {"point": [7500, 1500], "name": "Hall, \\"main\\"", "number": "@2"}',
        'room {"point": [13500, 1500], "name": "Line\\nbreak", "number": "+3"}',
        'schedule {"category": "rooms", "path": "rooms.csv"}',
    )
    sc.file("rooms.csv")
    assert sc.transcript() == sc.golden()


def test_schedule_xlsx_workbook(sc, sample):
    """CATCHES: an .xlsx export with other parts, a sheet name other than the schedule's, headings not bold, numbers
    written as text, or text not as inline strings."""
    sc.run(["run", sample, "--cmd",
            'schedule {"name": "Rooms & areas", "category": "rooms", "fields": ["Number", "Name", {"name": "Area", "total": true}], "path": "rooms.xlsx"}',
            "--cmd", 'schedule {"category": "levels", "path": "LEVELS.XLSX"}'])
    sc.file("rooms.xlsx")
    sc.file("LEVELS.XLSX")
    assert sc.transcript() == sc.golden()


SCHEDULE_ERRORS = {
    "nothing": 'schedule {}',
    "unknown_name": 'schedule {"name": "Nope"}',
    "unknown_category": 'schedule {"name": "X", "category": "teapots"}',
    "standard_of_another_category": 'schedule {"name": "Room Schedule", "category": "doors"}',
    "unknown_field": 'schedule {"name": "X", "category": "rooms", "fields": ["Nope"]}',
    "field_twice": 'schedule {"name": "X", "category": "rooms", "fields": ["Name", "Name"]}',
    "total_of_text": 'schedule {"name": "X", "category": "rooms", "fields": [{"name": "Name", "total": true}]}',
    "formula_of_itself": 'schedule {"name": "X", "category": "rooms", "fields": [{"name": "C", "formula": "C + 1"}]}',
    "formula_of_text": 'schedule {"name": "X", "category": "rooms", "fields": [{"name": "C", "formula": "Name * 2"}]}',
    "formula_named_as_a_field": 'schedule {"name": "X", "category": "rooms", "fields": [{"name": "Area", "formula": "1"}]}',
    "kind_without_formula": 'schedule {"name": "X", "category": "rooms", "fields": [{"name": "Name", "kind": "number"}]}',
    "fields_not_a_list": 'schedule {"name": "X", "category": "rooms", "fields": "Name"}',
    "grouped_not_a_bool": 'schedule {"name": "X", "category": "rooms", "grouped": 1}',
    "sort_by_unknown": 'schedule {"name": "X", "category": "rooms", "sort": ["Nope"]}',
    "contains_on_a_number": 'schedule {"name": "X", "category": "rooms", "filters": [{"field": "Area", "op": "contains", "value": "2"}]}',
    "greater_on_text": 'schedule {"name": "X", "category": "rooms", "filters": [{"field": "Name", "op": "greater", "value": 3}]}',
    "unknown_op": 'schedule {"name": "X", "category": "rooms", "filters": [{"field": "Name", "op": "like", "value": "x"}]}',
    "categories_of_a_single_category": 'schedule {"name": "X", "category": "rooms", "categories": ["walls"]}',
    "csv_to_a_missing_folder": 'schedule {"name": "X", "category": "rooms", "path": "no/dir/x.csv"}',
    "named_as_a_standard_one": 'schedule {"name": "Door Schedule", "category": "multicategory"}',
}


@pytest.mark.parametrize("command", SCHEDULE_ERRORS.values(), ids=SCHEDULE_ERRORS.keys())
def test_schedule_errors(sc, sample, command):
    """CATCHES: schedules accepting unknown categories or fields, fields twice, totals of text, a formula that reads
    itself or text, malformed lists, or a filter op that doesn't fit the field, instead of failing with the error saying
    what to fix and making nothing."""
    sc.run(["run", sample, "--cmd", command])
    assert sc.transcript() == sc.golden()


def test_schedule_on_an_empty_project_and_a_changed_standard_one_is_kept(sc):
    """CATCHES: a standard schedule made an element before it is changed, or not kept (by its name, saved and reopened)
    once its fields are."""
    sc.cmds('schedule {"category": "rooms"}', 'schedule {"category": "doors", "fields": ["Mark", "Count"]}',
            'schedule {"name": "Door Schedule"}', 'elements {"category": "schedule"}', 'save {"path": "p.bimcraft"}')
    sc.run(["run", "p.bimcraft", "--cmd", 'schedule {"name": "door schedule"}'])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Library, types and project parameters
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["type:wall", "type:door", "type:beam", "material", "family", "phase", "phase-filter",
                                  "view-template", "family-type", "layer", "form"])
def test_library_entries_by_kind(sc, kind):
    """CATCHES: library entries listed under other kinds, ids, or order, parts not listed with their owner and index, or
    `count` not counting the entries."""
    sc.cmds(f'library {{"kind": "{kind}"}}')
    assert sc.transcript() == sc.golden()


def test_library_by_name_and_a_new_material(sc):
    """CATCHES: `library {name}` matching other entries, or a new material not getting the next id down from 999999's
    entries and a GUID of its own."""
    sc.cmds('library {"name": "Brick"}', 'library {"kind": "layer", "name": "Exterior - 300mm"}',
            'material {"name": "Cork", "color": "#a07850"}', 'library {"name": "Cork"}', 'library {"kind": "nothing"}')
    assert sc.transcript() == sc.golden()


def test_types_created_edited_renamed_and_deleted(sc):
    """CATCHES: `type` that doesn't create or change a type everywhere it's used, rename_type that doesn't carry its
    elements along, or delete_type that deletes a type in use or the last of a category."""
    sc.cmds(
        'type {"category": "wall", "name": "Brick 250", "layers": [{"function": "finish", "material": "Brick", "thickness": 100}, {"function": "structure", "material": "Concrete block", "thickness": 150}]}',
        'wall {"points": [[0,0],[5000,0]], "type": "Brick 250"}',
        'type {"category": "wall", "name": "Brick 250", "thickness": 200}',
        'elements {"category": "wall"}',
        'rename_type {"category": "wall", "type": "Brick 250", "name": "Brick Cavity"}',
        'elements {"category": "wall"}',
        'type {"category": "door", "name": "Wide 1200", "width": 1200, "height": 2200}',
        'type {"category": "column", "name": "Round 500", "width": 500, "round": true}',
        'type {"category": "pipe", "name": "Steel 80", "width": 80, "round": true, "material": "Metal"}',
        'delete_type {"category": "door", "type": "Wide 1200"}',
        'library {"kind": "type:wall"}',
    )
    sc.cmds('wall {"points": [[0,0],[5000,0]]}', 'delete_type {"category": "wall", "type": "Generic - 200mm"}')
    sc.cmds('delete_type {"category": "floor", "type": "Generic - 200mm"}')
    sc.cmds('rename_type {"category": "wall", "type": "Generic - 200mm", "name": "Interior - 100mm"}')
    sc.cmds('rename_type {"category": "wall", "type": "Nope", "name": "X"}')
    sc.cmds('type {"category": "teapot", "name": "X"}')
    sc.cmds('delete_type {"family": "Sofa", "type": "2000 x 900"}', 'delete_type {"family": "Sofa"}', 'library {"name": "Sofa"}')
    assert sc.transcript() == sc.golden()


def test_project_parameters_values_rename_and_delete(sc):
    """CATCHES: project parameters whose values aren't kept by elements, aren't followed through a rename, don't show in
    the schedule's available fields, or aren't refused for a kind they don't hold."""
    sc.run(house_args(
        'parameter {"name": "Fire Rating", "kind": "number", "categories": ["wall", "door"]}',
        'modify {"id": 100002, "params": {"Fire Rating": 60}}',
        'modify {"id": 100007, "params": {"Fire Rating": 30}}',
        'schedule {"name": "Ratings", "category": "walls", "fields": ["Id", "Fire Rating"]}',
        'parameter {"name": "Fire Rating", "rename": "FR"}',
        'schedule {"name": "Ratings"}',
        'elements {"category": "door", "limit": 1}',
        'parameter {"name": "FR", "categories": ["wall"]}',
        'elements {"category": "door", "limit": 1}',
        'parameter {"name": "FR", "delete": true}',
        'inspect {}',
    ))
    sc.run(house_args('parameter {"name": "P", "kind": "length", "categories": ["wall"]}',
                      'modify {"id": 100002, "params": {"P": "long"}}'))
    sc.cmds('parameter {"name": "Q", "kind": "colour"}')
    sc.cmds('parameter {"name": "Q", "categories": ["teapot"]}')
    assert sc.transcript() == sc.golden()


def test_purge_dry_run_then_purge(sc):
    """CATCHES: purge that takes out what is used, keeps what isn't, doesn't go again for what that frees, or changes
    anything on a dry run."""
    sc.cmds(
        'type {"category": "wall", "name": "Unused A", "thickness": 123}',
        'wall {"points": [[0,0],[4000,0]], "type": "Interior - 100mm"}',
        'purge {"dry_run": true}',
        'library {"kind": "type:wall"}',
        'purge {"kinds": ["material"], "dry_run": true}',
        'purge {}',
        'library {"kind": "type:wall"}',
        'purge {}',
        'purge {"kinds": ["teapot"]}',
    )
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Inquiry, selection and elements
# ---------------------------------------------------------------------------------------------------------------------


def test_ids_of_then_select_by_id_by_guid_and_ifc_globalid(sc, sample):
    """CATCHES: select_by_id that doesn't find an element by its GUID with or without dashes and braces, or by its IFC
    GlobalId, lists one twice, or reports what named nothing, the plan and the extent differently."""
    p = sc.run(["run", sample, "--cmd", 'ids_of {"ids": [100007, 100014, 100025, 100054]}'])
    named = json.loads(p.stdout.decode().splitlines()[-1])["elements"]
    wall, door, room = named[0], named[1], named[2]
    text = (f"{wall['guid']}, {{{door['guid'].upper()}}}; {room['ifc']}\n{wall['guid'].replace('-', '')} 100007 "
            f"999999 12345678 nonsense")
    # The GUIDs are the file's own and random: the command is recorded by what it names, its reply as it is.
    p = sc.run(["run", sample, "--cmd", json.dumps({"text": text}).join(["select_by_id ", ""])], show=False)
    sc.note("select_by_id of: wall GUID, {DOOR GUID IN CAPITALS}; room IFC GlobalId, wall GUID without dashes, 100007 "
            "999999 12345678 nonsense")
    sc.note(f"[exit {p.returncode}]\n{p.stdout.decode()}{p.stderr.decode()}")
    sc.run(["run", sample, "--cmd", 'select_by_id {"text": ["100018", 100019]}', "--cmd", 'select_by_id {"text": "100021; 100014"}',
            "--cmd", 'select_by_id {"text": ""}', "--cmd", 'select_by_id {}'])
    sc.cmds('ids_of {"ids": [100000, 999999]}')
    assert sc.transcript() == sc.golden()


def test_filter_selection_by_category_and_by_a_parameter(sc, sample):
    """CATCHES: Filter on a selection that groups by other values, lists other shared fields, keeps the wrong ids, or
    accepts a parameter not every element has."""
    sc.run(["run", sample,
            "--cmd", 'filter_selection {"ids": [100007, 100008, 100011, 100014, 100015, 100018, 100025]}',
            "--cmd", 'filter_selection {"ids": [100007, 100008, 100011], "by": "Type", "keep": ["Interior - 100mm"]}',
            "--cmd", 'filter_selection {"ids": [100014, 100015, 100016, 100017], "by": "Width", "keep": ["800", "900"]}',
            "--cmd", 'filter_selection {"ids": [100007, 100014], "by": "Mark"}'])
    sc.run(["run", sample, "--cmd", 'filter_selection {"ids": [100007], "keep": "wall"}'])
    sc.run(["run", sample, "--cmd", 'filter_selection {"ids": [123456]}'])
    assert sc.transcript() == sc.golden()


def test_elements_paging_by_level_and_category(sc):
    """CATCHES: `elements` paging (limit and offset) that counts or returns other elements, or a level filter by name or
    id that picks elements of other levels."""
    sc.cmds(
        'wall {"points": [[0,0],[1000,0],[2000,0],[3000,0],[4000,0]]}',
        'wall {"points": [[0,5000],[3000,5000]], "level": "Level 2"}',
        'elements {"category": "wall", "limit": 2}',
        'elements {"category": "wall", "limit": 2, "offset": 3}',
        'elements {"category": "wall", "offset": 10}',
        'elements {"category": "wall", "level": "Level 2"}',
        'elements {"level": 100001}',
        'elements {"category": "walls", "level": "Level 1", "limit": 1, "offset": 1}',
    )
    sc.cmds('elements {"level": "Level 9"}')
    sc.cmds('elements {"category": "teapot"}')
    sc.cmds('elements {"limit": -1}')
    assert sc.transcript() == sc.golden()


def test_inspect_lists_warnings_for_a_room_no_longer_enclosed(sc):
    """CATCHES: `inspect` not warning about a room whose walls are gone, or listing the history labels differently."""
    p = sc.run(house_args('delete {"ids": [100003]}', "inspect {}"), show=False)
    inspect = json.loads(p.stdout.splitlines()[-1])
    sc.note(json.dumps({k: inspect[k] for k in ("counts", "history", "warnings")}, indent=1, ensure_ascii=False))
    assert sc.transcript() == sc.golden()


def test_highrise_storeys_out_of_range(sc):
    """CATCHES: `highrise` accepting a number of storeys outside 1–80, or one that isn't a whole number."""
    sc.cmds('highrise {"storeys": 0}')
    sc.cmds('highrise {"storeys": 81}')
    sc.cmds('highrise {"storeys": "ten"}')
    sc.cmds('highrise {"storeys": 2.5}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# More of reading kindly, Insert from File and links
# ---------------------------------------------------------------------------------------------------------------------


def test_unknown_fields_deep_in_a_saved_file_are_left_out(sc):
    """CATCHES: a lenient reader that only looks at the top level: unknown keys inside a type's layers, a level's view
    range, a material's texture, a family's forms and parameters, a detail group's members and a phase filter must
    each be left out and listed by their JSON path, and the rest read."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]], "type": "Exterior - 300mm"}',
            "--cmd", 'detail_line {"points": [[0,1000],[3000,1000]]}', "--cmd", 'detail_line {"points": [[0,1500],[3000,1500]]}',
            "--cmd", 'create_group {"ids": [100003, 100004], "name": "Pair"}', "--cmd", "sheet {}",
            "--cmd", 'place {"sheet": "A101", "view": "Level 1"}', "--save", "g.bimcraft"], show=False)
    d = json.loads((sc.workdir / "g.bimcraft").read_text())
    d["future"] = {"a": 1}
    d["types"]["wall"]["Exterior - 300mm"]["layers"][1]["sparkle"] = True
    d["elements"]["100000"]["view_range"]["haze"] = 5
    d["elements"]["100002"]["colour"] = "red"
    d["elements"]["100006"]["stamp"] = "draft"
    d["materials"]["Brick"]["texture"]["sheen"] = 0.5
    d["families"]["Sofa"]["forms"][0]["bevel"] = 3
    d["families"]["Sofa"]["parameters"][0]["unit"] = "mm"
    d["detail_groups"]["Pair"]["members"][1]["element"]["glow"] = 1
    d["detail_groups"]["Pair"]["note"] = "x"
    d["region_types"]["Solid Black"]["shine"] = 1
    d["dimension_types"][next(iter(d["dimension_types"]))]["flair"] = 1
    sc.write("g.bimcraft", json.dumps(d, indent=1))
    sc.run(["run", "g.bimcraft", "--cmd", 'elements {"category": "detailgroup"}', "--cmd", 'group_type {}'])
    assert sc.transcript() == sc.golden()


SOURCE = [
    'new {"name": "Source"}',
    'material {"name": "Cork", "color": "#a07850", "cut": "diagonal"}',
    'type {"category": "wall", "name": "Cork Wall", "layers": [{"function": "structure", "material": "Cork", "thickness": 150}]}',
    'wall {"points": [[0,0],[4000,0]], "type": "Cork Wall"}',
    'line_style {"name": "Red Lines", "pen": 3, "color": "#ff0000", "pattern": "Dash Dot"}',
    'detail_line {"points": [[0,1000],[3000,1000]], "style": "Red Lines"}',
    'phase {"name": "Phase 0", "before": "Existing"}',
    'modify {"id": 100002, "params": {"Phase Created": "Phase 0"}}',
    'family {"name": "Crate", "parameters": [{"name": "Cost", "kind": "number", "instance": true, "value": 5}, {"name": "Finish", "kind": "material", "value": "Cork"}], "types": {"Small": {}}, "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500, "material": "Finish"}]}',
    'component {"family": "Crate", "at": [1000, 2000]}',
    'grid {"start": [0,-1000], "end": [0, 5000]}',
    "sheet {}",
    'section {"start": [-1000, 500], "end": [5000, 500]}',
    'save {"path": "src.bimcraft"}',
]


def test_insert_brings_what_the_elements_use_and_renames_clashes(sc):
    """CATCHES: Insert from File that doesn't bring the materials, types, line styles and families the elements use, or
    doesn't give a grid name, a sheet number or a section name taken here ` 2`, or drops a phase this project lacks
    without saying so in `left_out`."""
    sc.cmds(*SOURCE)
    sc.cmds('grid {"start": [9000,-1000], "end": [9000, 5000]}', "sheet {}", 'section {"start": [-1000, 9500], "end": [5000, 9500]}',
            'insert {"path": "src.bimcraft"}', 'elements {"category": "grid"}', 'elements {"category": "sheet"}',
            'elements {"category": "section"}', 'elements {"category": "component"}', 'library {"name": "Crate"}',
            'library {"kind": "family-parameter"}', 'line_style {"name": "Red Lines"}')
    assert sc.transcript() == sc.golden()


def test_insert_some_ids_brings_what_they_point_at_on_levels_of_the_same_name(sc):
    """CATCHES: inserting some elements that doesn't bring their host or type, or puts them on a copy of a level this
    project has by name instead of on its own."""
    sc.cmds(*SOURCE)
    sc.cmds('level {"elevation": 4000, "name": "Upper"}', 'insert {"path": "src.bimcraft", "ids": [100004]}',
            'insert {"path": "src.bimcraft", "ids": [100002, 100003]}', 'elements {"category": "level"}',
            'elements {"category": "wall"}', 'elements {"category": "line"}')
    assert sc.transcript() == sc.golden()


def test_insert_from_an_ifc_file(sc):
    """CATCHES: Insert from File of an .ifc that doesn't import its elements into this project with new ids, or that
    replaces the project instead."""
    sc.run(house_args('save {"path": "house.ifc"}'), show=False)
    sc.cmds('level {"elevation": 7000, "name": "Top"}', 'insert {"path": "house.ifc"}',
            'elements {"category": "level"}', 'schedule {"category": "rooms"}')
    assert sc.transcript() == sc.golden()


def test_a_linked_model_is_drawn_in_the_plans_and_moves_with_its_placement(sc):
    """CATCHES: a link that isn't drawn in the host's plan, or isn't drawn again where `modify` moves and turns it: the
    plan before the link, with it, and with it moved must each be drawn as the reference draws them."""
    sc.cmds(*OTHER)
    sc.cmds('wall {"points": [[-3000,-3000],[-3000,3000]]}', 'render {"view": "Level 1", "path": "before.svg"}',
            'link {"path": "other.bimcraft", "at": [2000, 1000], "angle": 30}', 'render {"view": "Level 1", "path": "after.svg"}',
            'modify {"id": 100003, "at": [0, 0], "angle": 0}', 'render {"view": "Level 1", "path": "moved.svg"}',
            'elements {"category": "link"}')
    for f in ("before.svg", "after.svg", "moved.svg"):
        digest(sc, f)
    same = (sc.workdir / "before.svg").read_text() == (sc.workdir / "after.svg").read_text()
    sc.note(f"plan unchanged by the link: {same}")
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("unit", ["mm", "cm", "m", "in", "ft", "ft-in"])
def test_units_change_the_dimension_text_of_a_plan(sc, unit):
    """CATCHES: drawings that don't write a dimension's length in the project's units (mm, cm, m, fractional inches,
    decimal feet, feet and inches), or a view scale that isn't 1 : 96 by default in inches and feet."""
    sc.cmds(
        'wall {"points": [[0,0],[8130,0],[8130,6000],[0,6000]], "closed": true}',
        'dimension {"refs": [[0, 3000], [8130, 3000]], "at": [4000, -1000]}',
        'dimension {"refs": [[4000, 0], [4000, 6000]], "at": [-1000, 3000]}',
        f'units {{"length": "{unit}"}}',
        'scale {"view": "Level 1"}',
        'render {"view": "Level 1", "path": "plan.svg"}',
    )
    digest(sc, "plan.svg")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Scripts and files: encodings, sizes, names
# ---------------------------------------------------------------------------------------------------------------------


def test_script_files_with_crlf_bom_no_final_newline_and_bad_bytes(sc):
    """CATCHES: a script reader that keeps the carriage return of CRLF lines, strips a byte-order mark (the reference
    reads it as part of the command id and refuses it), needs a final newline, or reads bytes that aren't UTF-8."""
    sc.write("crlf.txt", b'level {"elevation": 4000}\r\n# comment\r\n\r\nlevel {"elevation": 5000, "name": "Five"}\r\n')
    sc.write("nonl.txt", b'level {"elevation": 4000}')
    sc.write("bom.txt", b'\xef\xbb\xbflevel {"elevation": 4000}\n')
    sc.write("bin.txt", b"\xff\xfe\x00level")
    sc.write("empty.txt", b"")
    sc.write("comments.txt", b"# nothing\n   # at all\n\n")
    for f in ("crlf.txt", "nonl.txt", "bom.txt", "bin.txt", "empty.txt", "comments.txt"):
        sc.run(["run", "--script", f])
    assert sc.transcript() == sc.golden()


def test_a_long_script_of_many_walls(sc):
    """CATCHES: a script run that drops or reorders results on a long input, numbers ids wrongly past a few hundred, or
    totals a schedule's lengths wrongly."""
    lines = [f'wall {{"points": [[{i * 1000}, 0], [{i * 1000}, {2000 + (i % 7) * 100}]]}}' for i in range(300)]
    lines.append('schedule {"name": "Lengths", "category": "walls", "fields": ["Type", {"name": "Length", "total": true}, "Count"], "grouped": true}')
    sc.write("long.txt", "\n".join(lines) + "\n")
    p = sc.run(["run", "--script", "long.txt", "--cmd", "inspect {}"], show=False)
    out_lines = p.stdout.decode().splitlines()
    sc.note(f"[exit {p.returncode}] {len(out_lines)} lines")
    sc.note("\n".join(out_lines[:3] + out_lines[297:301]))
    sc.note(json.dumps(json.loads(out_lines[-1])["counts"]))
    assert sc.transcript() == sc.golden()


def test_unicode_project_names_and_file_names(sc):
    """CATCHES: a project name or a file name with accents, emoji or spaces mangled on save, open or info, or escaped
    in the JSON replies instead of written as UTF-8."""
    sc.run(["run", "--cmd", 'new {"name": "Café 🏠 «Ω»"}', "--cmd", 'level {"elevation": 3500, "name": "Térreo ✓"}',
            "--save", "my house é.bimcraft"])
    p = sc.run(["info", "my house é.bimcraft"], show=False)
    info = json.loads(p.stdout)
    sc.note(json.dumps({k: info[k] for k in ("name", "levels", "path")}, ensure_ascii=False))
    sc.run(["run", "my house é.bimcraft", "--cmd", 'elements {"category": "level"}'])
    assert sc.transcript() == sc.golden()


def test_run_opens_several_files_in_turn(sc):
    """CATCHES: `run A B` that merges the projects or keeps the first, instead of opening each in turn so the commands
    after B work on B alone."""
    sc.run(["run", "--cmd", 'new {"name": "First"}', "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--save", "a.bimcraft"], show=False)
    sc.run(["run", "--cmd", 'new {"name": "Second"}', "--cmd", 'level {"elevation": 6000}', "--save", "b.bimcraft"], show=False)
    p = sc.run(["run", "a.bimcraft", "b.bimcraft", "--cmd", "inspect {}"], show=False)
    lines = p.stdout.decode().splitlines()
    sc.note("\n".join(lines[:2]))
    sc.note(json.dumps({k: json.loads(lines[2])[k] for k in ("name", "counts", "path")}))
    sc.run(["run", "a.bimcraft", "missing.bimcraft", "--cmd", "inspect {}"])
    assert sc.transcript() == sc.golden()


def test_save_as_moves_where_save_writes(sc):
    """CATCHES: `save {path}` that doesn't become the project's file (Save As), so a later `save {}` writes over the
    file it was opened from instead."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--save", "a.bimcraft"], show=False)
    sc.run(["run", "a.bimcraft", "--cmd", 'save {"path": "b.bimcraft"}', "--cmd", 'wall {"points": [[0,0],[0,4000]]}',
            "--cmd", "save {}", "--cmd", "inspect {}"], show=False)
    for f in ("a.bimcraft", "b.bimcraft"):
        info = json.loads(sc.run(["info", f], show=False).stdout)
        sc.note(f"{f}: {json.dumps(info['counts'])}")
    assert sc.transcript() == sc.golden()


def test_info_and_convert_of_an_ifc_file(sc):
    """CATCHES: `info` of an IFC file that doesn't import it before inspecting, or `convert` of an IFC file to a project
    that loses its storeys, walls, openings or rooms."""
    sc.run(house_args('save {"path": "house.ifc"}'), show=False)
    p = sc.run(["info", "house.ifc"], show=False)
    info = json.loads(p.stdout)
    sc.note(f"[exit {p.returncode}] " + json.dumps({k: info[k] for k in ("counts", "levels", "name", "path", "warnings", "types")}, indent=1))
    sc.run(["convert", "house.ifc", "house.bimcraft"])
    sc.run(["run", "house.bimcraft", "--cmd", 'schedule {"category": "rooms"}', "--cmd", 'schedule {"category": "doors"}'])
    assert sc.transcript() == sc.golden()
