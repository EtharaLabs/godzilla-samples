"""Schedules (`schedule`): the ones every project has, new ones with fields, calculated fields, filters, sorting,
grouping and totals, project and family parameters in them, multi-category schedules, and their CSV and .xlsx files."""

import io
import zipfile

import pytest

# Two rooms, three doors (one of another type) and a partition, as the engine's own schedule tests have them.
FLAT = """wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}
wall {"points": [[5000, 0], [5000, 6000]], "type": "Interior - 100mm"}
room {"point": [6500, 3000], "name": "Kitchen"}
room {"point": [2000, 3000], "name": "Living", "number": "10"}
door {"at": [6000, 0], "mark": "D2"}
door {"at": [2000, 0]}
door {"at": [5000, 3000], "type": "Single 800 x 2100"}
"""
COSTS = ('schedule {"name": "Costs", "category": "rooms", "fields": ["Name", "Area", '
         '{"name": "Cost", "formula": "Area * 120", "total": true}, '
         '{"name": "Half Perimeter", "formula": "Perimeter / 2", "kind": "length"}, '
         '{"name": "Large", "formula": "Area > 20", "kind": "yesno"}, '
         '{"name": "Cost With Tax", "formula": "Cost * 1.1", "heading": "Cost + 10%"}]}\n')


def _run(run, workdir, script, *extra):
    (workdir / "script.txt").write_text(script)
    return run(["run", "--script", "script.txt", *extra])


def _cmds(cmds):
    args = []
    for c in cmds:
        args += ["--cmd", c]
    return args


CASES = {
    # The schedules every project has, of the sample house, and how they're named.
    "the_samples_standard_schedules": ("", [
        'schedule {"category": "rooms"}',
        'schedule {"category": "doors"}',
        'schedule {"category": "windows"}',
        'schedule {"category": "walls"}',
        'schedule {"category": "floors"}',
        'schedule {"category": "levels"}',
        'schedule {"name": "level schedule"}',
        'schedule {"name": "Tabla de habitaciones"}',
        'elements {"category": "schedule"}',
    ]),
    "the_samples_other_categories": ("", [
        'schedule {"category": "ceilings"}',
        'schedule {"category": "roofs"}',
        'schedule {"category": "components"}',
        'schedule {"category": "multicategory"}',
    ]),
    "schedules_of_more_categories": (FLAT + 'stair {"start": [1000, 1000], "angle": 90}\ncolumn {"at": [4000, 3000]}\n'
                                     + 'structural_column {"at": [3000, 3000]}\nbeam {"points": [[0, 3000], [5000, 3000]]}\n'
                                     + 'footing {"at": [3000, 3000]}\nroof {}\nceiling {"point": [2000, 3000]}\n', [
        'schedule {"category": "stairs"}',
        'schedule {"category": "columns"}',
        'schedule {"category": "structural columns"}',
        'schedule {"category": "beams"}',
        'schedule {"category": "footings"}',
        'schedule {"category": "roofs"}',
        'schedule {"category": "ceilings"}',
    ]),
    # A new schedule: its fields, sorted, filtered; then a standard one changed, grouped and totalled.
    "fields_filters_sort_group_and_totals": (FLAT, [
        'schedule {"name": "Rooms by Area", "category": "rooms", "fields": ["Name", {"name": "Area", "total": true}, "Number"], '
        '"sort": [{"field": "Area", "descending": true}]}',
        'schedule {"name": "Rooms by Area", "filters": [{"field": "Name", "op": "begins-with", "value": "kit"}]}',
        'schedule {"name": "Rooms by Area", "filters": [{"field": "Area", "op": "greater", "value": 20}]}',
        'schedule {"name": "Rooms by Area"}',
        'schedule {"name": "Door Schedule", "fields": ["Type", "Width", {"name": "Count", "total": true}, "Mark"], "sort": ["Type"], '
        '"grouped": true}',
        'schedule {"category": "doors"}',
        'schedule {"name": "Door Schedule", "fields": [], "sort": [], "grouped": false}',
        'schedule {"name": "Door Schedule", "sort": [{"field": "Mark", "descending": true}]}',
        'elements {"category": "schedule"}',
        "undo",
        "undo",
        'schedule {"name": "Door Schedule"}',
    ]),
    "every_filter_op": (FLAT, [
        'schedule {"name": "R", "category": "rooms", "fields": ["Name", "Number", "Area"], "filters": [{"field": "Name", "op": "equals", "value": "LIVING"}]}',
        'schedule {"name": "R", "filters": [{"field": "Name", "op": "not-equals", "value": "living"}]}',
        'schedule {"name": "R", "filters": [{"field": "Area", "op": "greater-or-equal", "value": 30}]}',
        'schedule {"name": "R", "filters": [{"field": "Area", "op": "less", "value": 30}]}',
        'schedule {"name": "R", "filters": [{"field": "Area", "op": "less-or-equal", "value": 18}]}',
        'schedule {"name": "R", "filters": [{"field": "Name", "op": "contains", "value": "TCH"}]}',
        'schedule {"name": "R", "filters": [{"field": "Name", "op": "not-contains", "value": "tch"}]}',
        'schedule {"name": "R", "filters": [{"field": "Name", "op": "not-begins-with", "value": "Liv"}]}',
        'schedule {"name": "R", "filters": [{"field": "Name", "op": "ends-with", "value": "EN"}]}',
        'schedule {"name": "R", "filters": [{"field": "Name", "op": "not-ends-with", "value": "en"}]}',
        'schedule {"name": "R", "filters": [{"field": "Number", "op": "has-value"}, {"field": "Area", "op": "greater", "value": 1}]}',
        'schedule {"name": "R", "filters": [{"field": "Unbounded Height", "op": "has-no-value"}]}',
        'schedule {"name": "R", "filters": []}',
    ]),
    "calculated_fields": (FLAT + COSTS, [
        'schedule {"name": "Costs", "filters": [{"field": "Large", "op": "equals", "value": true}]}',
        'schedule {"name": "Costs", "filters": [{"field": "Large", "op": "not-equals", "value": true}], "sort": ["Cost"]}',
        'parameter {"name": "Rate", "kind": "number", "categories": ["room"]}',
        'modify {"id": 100008, "params": {"Rate": 100}}',
        'schedule {"name": "Costs", "filters": [], "fields": ["Name", {"name": "Cost", "formula": "Area * Rate"}]}',
        'parameter {"name": "Rate", "delete": true}',
    ]),
    "project_parameters_in_schedules": (FLAT + 'parameter {"name": "Fire Rating", "categories": ["door"]}\n'
                                        + 'modify {"id": 100010, "params": {"Fire Rating": "30 min"}}\n', [
        'schedule {"name": "Fire Doors", "category": "doors", "fields": ["Mark", "Fire Rating"], '
        '"filters": [{"field": "Fire Rating", "op": "has-value"}], "sort": ["Fire Rating"]}',
        'parameter {"name": "Fire Rating", "rename": "Fire Resistance"}',
        'schedule {"name": "Fire Doors"}',
        'parameter {"name": "Fire Resistance", "categories": ["window"]}',
        'schedule {"name": "Fire Doors"}',
        'parameter {"name": "Rate", "kind": "number", "categories": ["door"]}',
        'schedule {"name": "Fire Doors", "fields": ["Mark", {"name": "Cost", "formula": "Rate * 2"}]}',
        'parameter {"name": "Rate", "delete": true}',
    ]),
    "a_parameter_named_like_an_own_field": (FLAT, ['parameter {"name": "Width", "categories": ["door"]}']),
    "an_unset_yes_or_no_is_no": (FLAT + 'parameter {"name": "Accessible", "kind": "yesno", "categories": ["room"]}\n'
                                 + 'modify {"id": 100007, "params": {"Accessible": true}}\n', [
        'schedule {"name": "Access", "category": "rooms", "fields": ["Name", "Accessible"]}',
        'schedule {"name": "Access", "filters": [{"field": "Accessible", "op": "equals", "value": false}]}',
    ]),
    "components_with_their_families_parameters": (FLAT + 'component {"family": "Chair", "at": [1000, 2000]}\n'
                                                  + 'component {"family": "Chair", "at": [2000, 2000]}\n'
                                                  + 'component {"family": "Table", "at": [3000, 2000], "type": "1600 x 900"}\n', [
        'schedule {"name": "Furniture", "category": "components", "fields": ["Family", "Type", "Width", {"name": "Count", "total": true}], '
        '"sort": ["Family"], "grouped": true}',
        'schedule {"name": "Furniture", "grouped": false, "sort": [{"field": "Width", "descending": true}]}',
    ]),
    "a_familys_own_value_beats_a_project_parameter": (FLAT + 'family {"name": "Crate", "parameters": [{"name": "Cost", "kind": "number", '
                                                       '"instance": true, "value": 5}], "types": {"Small": {}}, '
                                                       '"forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500}]}\n'
                                                       + 'component {"family": "Crate", "at": [1000, 1000], "params": {"Cost": 7}}\n'
                                                       + 'parameter {"name": "Cost", "kind": "number", "categories": ["door"]}\n'
                                                       + 'modify {"id": 100010, "params": {"Cost": 100}}\n', [
        'schedule {"name": "Crates", "category": "components", "fields": ["Family", "Cost"], '
        '"filters": [{"field": "Cost", "op": "has-value"}], "sort": ["Cost"]}',
        'schedule {"name": "Costly doors", "category": "doors", "fields": ["Mark", "Cost"], "filters": [{"field": "Cost", "op": "greater", "value": 50}]}',
        'parameter {"name": "Cost", "categories": ["wall"]}',
        'schedule {"name": "Crates"}',
    ]),
    "a_familys_yes_or_no_and_material": (FLAT + 'family {"name": "Crate", "parameters": [{"name": "Lidded", "kind": "yesno", '
                                          '"instance": true, "value": 0}, {"name": "Finish", "kind": "material", "value": "Timber"}], '
                                          '"types": {"Small": {}}, "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500}]}\n'
                                          + 'component {"family": "Crate", "at": [1000, 1000], "params": {"Lidded": 1}}\n'
                                          + 'component {"family": "Crate", "at": [2000, 1000]}\n', [
        'schedule {"name": "Crates", "category": "components", "fields": ["Family", "Type", "Lidded", "Finish"]}',
        'schedule {"name": "Crates", "filters": [{"field": "Lidded", "op": "equals", "value": true}]}',
        'schedule {"name": "Stuff", "category": "multicategory", "categories": ["components"], "fields": ["Family", "Material", "Count"]}',
    ]),
    "mass_floors": ('mass {"boundary": [[0, 0], [10000, 0], [10000, 6000], [0, 6000]], "height": 7000, "name": "Block"}\n'
                    + 'level {"elevation": 6000}\n', [
        'schedule {"category": "massfloors"}',
        'schedule {"name": "Gross", "category": "massfloor", "fields": ["Level", {"name": "Area", "total": true}], "sort": [{"field": "Level", "descending": true}]}',
    ]),
    # Text sorts numbers by value first, then the rest in any case; numbers compare as the schedule shows them.
    "natural_sort_and_shown_numbers": (FLAT + 'room {"point": [6500, 1000], "name": "Store", "number": "2"}\n'
                                       + 'modify {"id": 100007, "number": "b"}\nmodify {"id": 100008, "number": "A"}\n', [
        'schedule {"name": "N", "category": "rooms", "fields": ["Number", "Name", "Area"], "sort": ["Number"]}',
        'schedule {"name": "N", "sort": [{"field": "Number", "descending": true}]}',
        'schedule {"name": "N", "filters": [{"field": "Number", "op": "greater", "value": "1"}]}',
        'schedule {"name": "N", "filters": [{"field": "Area", "op": "equals", "value": 30.004}]}',
        'schedule {"name": "N", "filters": [{"field": "Area", "op": "not-equals", "value": 30.004}]}',
    ]),
    # Multi-category.
    "multi_category": (FLAT, [
        'schedule {"name": "Takeoff", "category": "multi-category", "categories": ["walls", "doors"], '
        '"fields": ["Category", "Type", {"name": "Count", "total": true}], "sort": ["Category", "Type"], "grouped": true}',
        'schedule {"name": "Takeoff", "categories": ["doors"]}',
        'schedule {"name": "Takeoff", "categories": [], "fields": [], "grouped": false, "sort": []}',
        'schedule {"name": "Areas", "category": "multicategory", "categories": ["walls", "doors", "rooms"], '
        '"fields": ["Category", "Id", "Width", "Height", "Length", "Area", "Material"], "sort": ["Category", "Id"]}',
    ]),
    "multi_category_of_an_unknown_category": (FLAT, ['schedule {"name": "M", "category": "multicategory", "categories": ["balloons"]}']),
    "multi_category_of_rooms_only": (FLAT, ['schedule {"name": "M", "category": "multicategory", "categories": ["rooms"]}']),
    "categories_of_a_door_schedule": (FLAT, ['schedule {"name": "Door Schedule", "categories": ["walls"]}']),
    "a_schedule_in_portuguese": (FLAT + 'language {"code": "pt"}\n', [
        'schedule {"category": "rooms"}',
        'schedule {"category": "doors", "fields": ["Mark", "Count"]}',
        'schedule {"name": "Ambientes", "category": "rooms", "fields": ["Name", {"name": "Area", "total": true}]}',
    ]),
    "a_schedule_in_feet_and_inches": (FLAT + 'units {"length": "ft-in"}\n', [
        'schedule {"category": "rooms"}',
        'schedule {"category": "doors"}',
    ]),
    # A standard schedule named in another language is still that one.
    "standard_schedules_in_any_language": (FLAT + 'language {"code": "pt"}\nsheet {}\n'
                                           + 'place {"sheet": "A101", "view": "Room Schedule"}\nlanguage {"code": "en"}\n', [
        'elements {"category": "schedule"}',
        'schedule {"category": "rooms"}',
        'modify {"id": 100013, "name": "room schedule"}',
        'schedule {"category": "rooms"}',
        'schedule {"name": "Rooms 2", "category": "rooms"}',
    ]),
    "place_a_placed_standard_schedule_again": (FLAT + 'language {"code": "pt"}\nsheet {}\n'
                                               + 'place {"sheet": "A101", "view": "Room Schedule"}\nlanguage {"code": "en"}\n',
                                               ['place {"sheet": "A101", "view": "Room Schedule"}']),
    "rename_onto_a_standard_name": (FLAT + 'schedule {"name": "Rooms 2", "category": "rooms"}\n',
                                    ['modify {"id": 100012, "name": "Tabla de habitaciones"}']),
    "rename_onto_a_standard_name_of_another_category": (FLAT + 'schedule {"name": "Rooms 2", "category": "rooms"}\n',
                                                        ['modify {"id": 100012, "name": "Window Schedule"}']),
    # What a schedule refuses.
    "unknown_field": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": ["Colour"]}']),
    "field_twice": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": ["Name", "Name"]}']),
    "text_total": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "Name", "total": true}]}']),
    "kind_without_formula": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "Area", "kind": "length"}]}']),
    "formula_on_an_unknown_field": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "X", "formula": "Nope * 2"}]}']),
    "formula_that_comes_back_to_itself": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "A", "formula": "B + 1"}, '
                                                 '{"name": "B", "formula": "A * 2"}]}']),
    "formula_on_text": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "X", "formula": "Name * 2"}]}']),
    "formula_named_like_an_own_field": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "Area", "formula": "1"}]}']),
    "formula_not_closed": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "X", "formula": "(1 + Area"}]}']),
    "formula_bad_function": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "X", "formula": "sqrt(Area, 2)"}]}']),
    "formula_of_text_kind": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": [{"name": "X", "formula": "Area", "kind": "text"}]}']),
    "formulas_twenty_in_a_row": (FLAT, ['schedule {"name": "Chain", "category": "walls", "fields": ["Id", '
                                        + ", ".join('{"name": "A%02d", "formula": "%s + 1"}' % (i, "Id" if i == 20 else "A%02d" % (i + 1))
                                                    for i in range(1, 21)) + "]}"]),
    "contains_on_an_area": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": ["Area"], '
                                   '"filters": [{"field": "Area", "op": "contains", "value": "1"}]}']),
    "word_for_an_area": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": ["Area"], '
                                '"filters": [{"field": "Area", "op": "greater", "value": "big"}]}']),
    "greater_on_a_yes_or_no": (FLAT + 'parameter {"name": "Accessible", "kind": "yesno", "categories": ["room"]}\n',
                               ['schedule {"name": "X", "category": "rooms", "filters": [{"field": "Accessible", "op": "greater", "value": 1}]}']),
    "unknown_op": (FLAT, ['schedule {"name": "X", "category": "rooms", "filters": [{"field": "Area", "op": "near", "value": 1}]}']),
    "filter_on_an_unknown_field": (FLAT, ['schedule {"name": "X", "category": "rooms", "filters": [{"field": "Colour", "op": "has-value"}]}']),
    "sort_by_an_unknown_field": (FLAT, ['schedule {"name": "X", "category": "rooms", "sort": ["Colour"]}']),
    "grouped_not_a_flag": (FLAT, ['schedule {"name": "X", "category": "rooms", "grouped": "yes"}']),
    "fields_not_a_list": (FLAT, ['schedule {"name": "X", "category": "rooms", "fields": "Name"}']),
    "schedule_of_another_category": (FLAT + 'schedule {"name": "Costs", "category": "rooms"}\n', ['schedule {"name": "Costs", "category": "doors"}']),
    "unknown_schedule_without_category": (FLAT, ['schedule {"name": "Nowhere"}']),
    "schedule_of_clouds": (FLAT, ['schedule {"name": "S", "category": "clouds"}']),
    "schedule_without_name_or_category": (FLAT, ["schedule {}"]),
    "more_than_64_fields": (FLAT, ['schedule {"category": "walls", "fields": [' + ", ".join(['"Id"'] * 65) + "]}"]),
    "a_formula_circle_in_an_unkept_schedule": (FLAT, ['schedule {"category": "stairs", "fields": ["Id", {"name": "A", "formula": "B + 1"}, '
                                                      '{"name": "B", "formula": "A + 1"}]}']),
    "a_standard_name_for_another_category": (FLAT, ['schedule {"name": "Level 1", "category": "rooms"}']),
    "a_standard_name_of_another_category": (FLAT, ['schedule {"name": "Window Schedule", "category": "rooms"}']),
    "a_filter_value_too_long": (FLAT, ['schedule {"name": "Y", "category": "rooms", "filters": [{"field": "Name", "op": "equals", '
                                       '"value": "' + "x" * 300 + '"}]}']),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_schedules(run, workdir, golden, case):
    """CATCHES: a rewrite whose schedules differ from the reference's: each category's own fields and the ones shown
    unless chosen, the units of the columns (areas in m², lengths in mm), how filters compare, how rows sort and group,
    what totals sum, calculated fields' values, project and family parameters, multi-category rows, which schedule a
    name means, what each reply holds, and the wording of every refusal."""
    setup, cmds = CASES[case]
    if setup:
        r = _run(run, workdir, setup, *_cmds(cmds))
    else:
        r = run(["run", "--sample", *_cmds(cmds)])
    golden.check_run(r, f"{case}.txt")


def test_a_schedule_written_as_csv(run, workdir, golden):
    """CATCHES: a rewrite whose CSV differs: its heading row (with units), numbers as the table holds them, text quoted
    where it needs to be, a cell a spreadsheet would read as a formula guarded with a quote, empty cells, totals."""
    script = FLAT + 'modify {"id": 100008, "name": "=SUM(A1:A9)"}\nmodify {"id": 100007, "name": "Kitchen, \\"open\\""}\n'
    r = _run(run, workdir, script, "--cmd",
             'schedule {"name": "Export", "category": "rooms", "fields": ["Number", "Name", {"name": "Area", "total": true}, '
             '"Perimeter", "Unbounded Height", {"name": "Cost", "formula": "Area * 1.5", "total": true}], "path": "rooms.csv"}',
             "--cmd", 'schedule {"category": "doors", "path": "doors.csv"}')
    golden.check_run(r, "csv.txt")
    golden.check((workdir / "rooms.csv").read_text(encoding="utf-8"), "rooms.csv")
    golden.check((workdir / "doors.csv").read_text(encoding="utf-8"), "doors.csv")


def _xlsx_parts(data: bytes) -> str:
    """Every part of a workbook, by name, in the order the zip holds them."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        out = []
        for info in z.infolist():
            out.append(f"=== {info.filename}\n{z.read(info.filename).decode('utf-8')}\n")
        return "".join(out)


def test_a_schedule_written_as_a_workbook(run, workdir, golden):
    """CATCHES: a rewrite whose .xlsx workbook differs in its parts: the sheet named for the schedule, headings in bold,
    numbers as numbers, text as inline strings, the totals row; or that writes CSV for a path ending .xlsx."""
    script = FLAT + 'modify {"id": 100008, "name": "=SUM(A1:A9) & <b>"}\nmodify {"id": 100007, "name": "Kit\\u0007chen\\t\\"1\\" \'2\'"}\n'
    wide = ", ".join('{"name": "C%02d", "formula": "Area * %d", "total": true}' % (i, i) for i in range(1, 28))
    r = _run(run, workdir, script, "--cmd",
             'schedule {"name": "Room Areas", "category": "rooms", "fields": ["Number", "Name", {"name": "Area", "total": true}, '
             '{"name": "Large", "formula": "Area > 20", "kind": "yesno"}], "path": "rooms.XLSX"}',
             "--cmd", 'schedule {"category": "stairs", "path": "stairs.xlsx"}',
             "--cmd", 'schedule {"name": "Wide", "category": "rooms", "fields": ["Name", %s], "path": "wide.xlsx"}' % wide)
    golden.check_run(r, "xlsx.txt")
    golden.check(_xlsx_parts((workdir / "wide.xlsx").read_bytes()), "wide.xlsx.txt")
    golden.check(_xlsx_parts((workdir / "rooms.XLSX").read_bytes()), "rooms.xlsx.txt")
    golden.check(_xlsx_parts((workdir / "stairs.xlsx").read_bytes()), "stairs.xlsx.txt")


@pytest.mark.parametrize("case", ["unknown_field", "standard_name"])
def test_a_refused_schedule_writes_no_file(run, workdir, golden, case):
    """CATCHES: a rewrite that writes a schedule's file before checking it, so a refused schedule leaves a file behind."""
    params = {"unknown_field": '{"name": "X", "category": "rooms", "fields": ["Nope"], "path": "x.csv"}',
              "standard_name": '{"name": "Level 1", "category": "rooms", "path": "x.csv"}'}[case]
    r = _run(run, workdir, FLAT, "--cmd", "schedule " + params)
    golden.check_run(r, f"refused_file_{case}.txt")
    # (An instrumented build drops its .profraw counters in the working directory; they are not the program's output.)
    assert sorted(p.name for p in workdir.iterdir() if p.suffix != ".profraw") == ["script.txt"]


def test_a_schedule_into_a_missing_folder(run, workdir, golden):
    """CATCHES: a rewrite that creates missing folders for a schedule's file, or words the failure differently."""
    r = _run(run, workdir, FLAT, "--cmd", 'schedule {"category": "rooms", "path": "nodir/rooms.csv"}')
    golden.check_run(r, "missing_folder.txt")
