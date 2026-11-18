"""Revit files (.rvt, .rfa, .rte, .rft) on the command line: `info`, the import by `run` and `convert`, and the MCP server.

The inputs are synthetic Revit-shaped files (Compound Files holding BasicFileInfo, Formats/Latest, Global/ElemTable and
partitions in the record layouts the reader knows), stored next to the goldens in test_resources/test_revit/. No file from
Autodesk is used. Imported GUIDs are random, so every output goes through `normalize`, and the IFC export is made from a
project whose GUIDs were fixed first (IFC orders storeys by GUID).
"""

import json
import shutil

import pytest
from conftest import GUID_RE, fix_guids, mcp_lines, normalize, png_pixels, resources_for

RES = resources_for(__file__)


def put(workdir, name, as_name=None):
    """Copy the input file `name` into the working directory (as `as_name`), and return the name to give the program."""
    target = as_name or name
    shutil.copyfile(RES / name, workdir / target)
    return target


def outcome(r) -> str:
    """Exit code, normalised stdout and stderr of a run, as `golden.check_run` writes them."""
    return (f"exit: {r.returncode}\n--- stdout\n" + normalize(r.stdout.decode("utf-8", "replace"))
            + "--- stderr\n" + normalize(r.stderr.decode("utf-8", "replace")))


def masked(value) -> str:
    """A value with its random GUIDs left out, for telling whether it changed."""
    return GUID_RE.sub("<guid>", json.dumps(value, sort_keys=True))


def changed(now, before):
    """What `now` holds that `before` does not (or holds otherwise, GUIDs aside), key by key down through nested objects."""
    both = isinstance(now, dict) and isinstance(before, dict)
    return {
        **{k: (changed(v, before[k]) if k in before else v) for k, v in now.items()
           if k not in before or masked(v) != masked(before[k])},
        **{k: "<removed>" for k in before if k not in now},
    } if both else now


def empty_inspect(run):
    r = run(["run", "--cmd", "inspect"])
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout)


def imported(run, workdir, name, before) -> str:
    """The import of `name`: the open reply, every element, and what the import added to the library (types, materials,
    families) or changed in the project, compared with a new empty project's `inspect`."""
    put(workdir, name)
    r = run(["run", name, "--cmd", "elements {}", "--cmd", "inspect"])
    assert r.returncode == 0, outcome(r)
    reply, elements, inspect = [json.loads(line) for line in r.stdout.decode().splitlines()]
    text = json.dumps({"open": reply, "elements": elements, "project": changed(inspect, before)}, indent=1,
                      sort_keys=True, ensure_ascii=False)
    return f"=== {name}\n{text}\n" + r.stderr.decode()


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

INFO = {
    "house": "house.rvt",
    "walls_2019": "walls_2019.rvt",
    "levels_odd": "levels_odd.rvt",
    "levels_odd_2023": "levels_odd_2023.rvt",
    "storeys_2019": "storeys_2019.rvt",
    "storeys_2024": "storeys_2024.rvt",
    "inventory_2015": "inventory_2015.rvt",
    "inventory_2024": "inventory_2024.rvt",
    "workshared_2018": "workshared_2018.rvt",
    "legacy_2016": "legacy_2016.rvt",
    "titled": "titled.rvt",
    "titled_blank": "titled_blank.rvt",
    "bad_atom": "bad_atom.rvt",
    "family_without_schema": "chair.rfa",
    "family_without_partitions": "desk.rfa",
    "release_2030": "release_2030.rvt",
    "generic_2024": "generic_2024.rvt",
    "two_partitions": "newest_22.rvt",
}


@pytest.mark.parametrize("case", sorted(INFO))
def test_info_of_a_revit_file(run, workdir, golden, case):
    """CATCHES: a rewrite whose `info` of a Revit file reads a different release, build, document GUID, locale,
    worksharing state, Atom title/date/OmniClass, last saver or save path, or counts elements, placed instances, declared
    ids, levels (with their elevations in mm and Building Story setting), unread and owned levels differently; one that fails
    instead of showing the metadata and an `error` for a family with no schema or partition or an unknown release; or one
    that prints compact JSON or leaves out the note."""
    name = put(workdir, INFO[case])
    golden.check_run(run(["info", name]), f"info_{case}.txt")


# ---------------------------------------------------------------------------
# the import: what comes in, what is noted and what is left out
# ---------------------------------------------------------------------------

IMPORTS = {
    "house": ["house.rvt"],
    "walls_releases": ["walls_2019.rvt", "walls_2023.rvt", "walls_2024.rvt", "walls_2026.rvt"],
    "walls_odd": ["walls_odd.rvt"],
    "walls_levels": ["walls_levels.rvt", "walls_tie.rvt"],
    "materials": ["materials_2024_pattern.rvt", "materials_2024_param.rvt", "materials_2024_closed.rvt",
                  "materials_2019_param.rvt", "materials_2023_pattern.rvt", "materials_2023_data.rvt",
                  "materials_terminated_2023.rvt", "materials_terminated_2024.rvt"],
    "category_material": ["category_material_2019.rvt", "category_material_2024.rvt", "category_material_2025.rvt",
                          "category_material_two.rvt"],
    "floors_releases": ["floors_2019.rvt", "floors_2023.rvt", "floors_2024.rvt", "floors_2026.rvt"],
    "floors_odd": ["floors_odd.rvt"],
    "roofs_flat": ["roofs_2023.rvt", "roofs_2024.rvt"],
    "roofs_odd": ["roofs_odd.rvt"],
    "roofs_extrusion": ["gable_2024.rvt", "gable_2026.rvt", "extrusion_more.rvt"],
    "roofs_extrusion_odd": ["extrusion_odd.rvt"],
    "openings_releases": ["openings_2019.rvt", "openings_2023.rvt", "openings_2024.rvt", "openings_2026.rvt"],
    "openings_more": ["openings_more.rvt"],
    "openings_odd": ["openings_odd.rvt"],
    "columns": ["columns_2019.rvt", "columns_2024.rvt", "columns_nine.rvt"],
    "columns_turned": ["columns_turned.rvt"],
    "rooms_releases": ["rooms_2019.rvt", "rooms_2023.rvt", "rooms_2024.rvt", "rooms_2026.rvt"],
    "rooms_odd": ["rooms_odd.rvt"],
    "mep": ["mep_2019.rvt", "mep_2024.rvt"],
    "generic": ["generic_2019.rvt", "generic_2024.rvt"],
    "levels_releases": ["levels_2015.rvt", "levels_2019.rvt", "levels_2023.rvt", "levels_2024.rvt", "levels_2027.rvt"],
    "levels_odd": ["levels_odd.rvt", "levels_odd_2023.rvt", "no_levels.rvt", "storeys_2024.rvt"],
    "inventory": ["inventory_2015.rvt", "inventory_2023.rvt", "inventory_2024.rvt", "inventory_2027.rvt",
                  "inventory_inside.rvt"],
    "partitions": ["newest_21.rvt", "newest_22.rvt", "members_2024.rvt", "partition_bad_crc.rvt",
                   "partition_no_trailer.rvt"],
    "metadata": ["titled.rvt", "titled_blank.rvt", "bad_atom.rvt", "legacy_2016.rvt", "workshared_2018.rvt"],
    "streams": ["schema_rich.rvt", "gz_flags.rvt", "gz_formats_flags.rvt", "gz_reserved.rvt", "gz_junk.rvt",
                "gz_hidden_member.rvt", "gz_no_trailers.rvt", "gz_paged.rvt"],
    "walls_more": ["walls_more.rvt", "walls_2019_names.rvt"],
    "openings_hosts": ["openings_hosts.rvt"],
    "floors_more": ["floors_more.rvt"],
    "roofs_more": ["roofs_more.rvt"],
    "tied_levels": ["tie.rvt"],
}

WHAT = {
    "house": "a wall's line, height, levels, layered type and materials",
    "walls_releases": "straight, flipped and curved walls in the 2019, 2023, 2024 and 2026 record forms",
    "walls_odd": "walls with no data, a climbing or unlevel line, no type or two, curtain types, membranes, damaged "
                 "layers, decks, turned and upright arcs, and the notes and reasons for each",
    "walls_levels": "the base and top levels, offsets and unconnected heights of walls, and a wall on two tied levels",
    "materials": "material names read by each naming rule only where its release writes it, from data up to 2023, and "
                 "a material named twice differently",
    "category_material": "a layer with no material taking its category's from the object styles up to 2024",
    "floors_releases": "a floor with a hole, a ceiling, a curved corner, a box-only triangle and a sketch of two loops",
    "floors_odd": "sloped, open, unsketched, untyped, crossing and offset floors, owner slots, and types of one name",
    "roofs_flat": "a flat roof by footprint with a courtyard and the wall whose top it cuts",
    "roofs_odd": "a rising roof, a roof by face, a roof with no sketch or two loops, a roof leaving a wall no height, and "
                 "roof types of one name",
    "roofs_extrusion": "roofs by extrusion: the profile swept across, its type square to each slope, lines in any order",
    "roofs_extrusion_odd": "roofs by extrusion left out: a wrong box, an arc, a plane at 45 degrees, an open chain, 300 lines",
    "openings_releases": "a door and a window set in their wall in four releases",
    "openings_more": "hosts by id, narrowed neighbours, overrunning boxes, a turned wall, offsets and types by name entry",
    "openings_odd": "openings in walls at an angle, a curved wall, no wall, a wall from its box, and overlaps refused",
    "columns": "architectural and structural columns, short of their top level, on no named level, nine in one note",
    "columns_turned": "turned columns, quarter turns, unknown symbol sizes, geometry nodes and column types of one name",
    "rooms_releases": "a room's number, name, level and point inside the walls round it",
    "rooms_odd": "partitions, unenclosed rooms, a free-standing core and a wall a googol of feet long",
    "mep": "pipes between their connectors, ducts and cable trays along their lines, and those left out",
    "generic": "boxes of other categories, unnamed categories, companions and categories with no reader",
    "levels_releases": "levels lowest first in millimetres in five releases",
    "levels_odd": "levels of one name, owned, unnamed, unconfirmed and far away, a file with no levels, storeys",
    "inventory": "records without data, symbols, undeclared ids, frames inside other records",
    "partitions": "the newest copy across partitions, members cut anywhere, a wrong CRC and a missing trailer",
    "metadata": "the project's name from its Atom title, a blank title, a damaged ZIP, a 2016 file and a workshared 2018 one",
    "streams": "a schema with every kind of field that stops after the classes the records need, gzip members with "
               "header flags, reserved flags, junk, a member hidden in stored data, no trailers, and a paged partition",
    "walls_more": "layer functions, a wall from a box long in y, tied named levels, walls below every level, thin and "
                  "curved curtain walls, nameless, empty and unknown layer lists, names that are no names, a bad flip, "
                  "a wall the model refuses taking its door along, and a one-letter name before 2023",
    "openings_hosts": "a skylight, doors in walls left out and in a curtain wall, an overrun past the end, no room",
    "floors_more": "a line floating in a floor, two named levels, ceilings of two loops or no sketch, a lens, ends "
                   "that miss, an arc read as an arc, a side short of its corner, a line twice, an arc over a full turn",
    "roofs_more": "a roof by face with no type, profiles standing on a point or running back, a profile with no type",
    "tied_levels": "two levels at one height: what names no level and stands above them stands on none",
}


@pytest.mark.parametrize("group", sorted(IMPORTS))
def test_import_of_revit_files(run, workdir, golden, group):
    """CATCHES: a rewrite whose Revit import makes different elements (geometry in mm, levels, offsets, heights, hosts,
    types, materials, families, rooms), or reports different `skipped` notes (wording, counts, grouping, order, ids), for
    the file kind under test (what each group holds is in WHAT, and heads its golden)."""
    before = empty_inspect(run)
    text = f"# {WHAT[group]}\n" + "".join(imported(run, workdir, name, before) for name in IMPORTS[group])
    golden.check(normalize(text), f"import_{group}.txt")


# ---------------------------------------------------------------------------
# files that are not Revit projects, or are damaged
# ---------------------------------------------------------------------------

REFUSED = [
    "text.rvt", "empty.rvt", "short.rvt", "zip.rvt", "signature_only.rvt", "bad_signature.rvt", "truncated_half.rvt",
    "truncated_header.rvt", "word.rvt", "basic_garbage.rvt", "basic_year77.rvt", "release_2030.rvt", "release_2014.rvt",
    "chair.rfa", "desk.rfa", "no_formats.rvt", "formats_not_gzip.rvt", "formats_cut_header.rvt",
    "formats_bad_deflate.rvt", "schema_empty.rvt", "schema_no_plane.rvt", "no_elemtable.rvt", "elemtable_garbage.rvt",
    "elemtable_zero.rvt", "elemtable_short.rvt", "no_partitions.rvt", "partition_not_gzip.rvt", "partition_cut.rvt",
    "huge_stream.rvt", "long_stream.rvt", "many_streams.rvt",
]


@pytest.mark.parametrize("name", REFUSED)
def test_a_damaged_or_foreign_file_is_refused_with_the_reason(run, workdir, golden, name):
    """CATCHES: a rewrite that imports a damaged or foreign file as an empty project, panics, or refuses it with a
    message that does not name the file and the exact fault (the bytes it starts with, the missing stream, the stream that
    does not inflate and where, the release it does not guess at, the element table or schema that does not fit); one whose
    `info` does not still show the metadata of a file it cannot inventory; or whose `convert` writes a file anyway."""
    put(workdir, name)
    info = run(["info", name])
    imp = run(["run", name, "--cmd", "inspect"])
    conv = run(["convert", name, "out.ifc"])
    text = "\n".join([f"--- info\n{outcome(info)}", f"--- run\n{outcome(imp)}", f"--- convert\n{outcome(conv)}"])
    golden.check(text, f"refused_{name.replace('.', '_')}.txt")
    assert not (workdir / "out.ifc").exists(), "nothing is written"


SCHEMA_ERRORS = ["separator", "name_length", "name_ascii", "inline_pad", "inline_tag", "modifier", "array_count",
                 "array_filler", "field_count", "guid_count", "types_deep", "classes_deep", "version_cut"]


def test_a_schema_the_grammar_refuses_at_its_first_class_says_where_it_stopped(run, workdir, golden):
    """CATCHES: a rewrite whose Formats/Latest reader accepts a class that breaks the grammar (a separator that is not 0,
    a name of no length or not ASCII, a bad inline base, an unknown type modifier, an array count or field count or GUID
    count past its limit, nesting too deep, a class cut short), or that says something other than where and why it stopped
    when no class could be read, in `info` and on import."""
    outs = []
    for case in SCHEMA_ERRORS:
        name = put(workdir, f"schema_{case}.rvt")
        info = json.loads(run(["info", name]).stdout)
        outs.append(f"{case}: {info['elements']}\n{outcome(run(['run', name]))}")
    golden.check("\n".join(outs), "schema_errors.txt")


ATOMS = ["atom_entities.rvt", "atom_stored.rvt", "atom_not_zip.rvt", "atom_cut_header.rvt", "atom_no_data.rvt",
         "atom_stored_cut.rvt", "atom_bad_deflate.rvt", "atom_bomb.rvt", "atom_closes.rvt", "atom_deep.rvt", "atom_cut.rvt",
         "atom_unclosed.rvt", "atom_not_utf8.rvt", "atom_family_bad.rfa", "atom_family_ok.rfa"]


def test_the_atom_entry_gives_the_title_the_date_and_the_omniclass_or_nothing(run, workdir, golden):
    """CATCHES: a rewrite that decodes the Atom entry's title differently (entities, numeric references, a nested title,
    comments and CDATA, a stored or deflated ZIP entry, a family's PartAtom), names the imported project by anything but a
    readable title, or fails the whole file (or shows a title) when the entry is damaged, cut, too deep, too big or not
    UTF-8, or its ZIP is cut short or does not inflate."""
    outs = []
    for name in ATOMS:
        put(workdir, name)
        info = json.loads(run(["info", name]).stdout)["revit"]
        imp = run(["run", name])
        shown = {k: info[k] for k in ("title", "saved", "omniclass")}
        outs.append(f"{name}: {json.dumps(shown, ensure_ascii=False)}\n{outcome(imp)}")
    golden.check("\n".join(outs), "atoms.txt")


def test_a_folder_or_a_missing_file_named_as_a_revit_file(run, workdir, golden):
    """CATCHES: a rewrite that reads a folder named `x.rvt` as an empty project or crashes on it, or whose error for a
    file that is not there does not name it and the system's reason."""
    (workdir / "folder.rvt").mkdir()
    outs = [outcome(run([cmd, path, *rest])) for path in ["folder.rvt", "missing.rvt"]
            for cmd, *rest in [["info"], ["run"], ["convert", "out.bimcraft"]]]
    golden.check("\n".join(outs), "folder_and_missing.txt")


# ---------------------------------------------------------------------------
# which files are Revit's, and what the session does with one
# ---------------------------------------------------------------------------

def test_any_case_of_the_four_revit_extensions_is_read_as_a_revit_file(run, workdir, golden):
    """CATCHES: a rewrite that reads only lower-case `.rvt` with the Revit reader, and not a template (.rte), a family
    (.rfa), a family template (.rft) or an upper-case `.RVT`, or that names the imported project other than by the file's
    stem; and one that reads a Revit file named `.bimcraft` or `.ifc` with the Revit reader instead of refusing it as the
    format its extension names."""
    names = ["Plan.RVT", "office.rte", "chair.Rfa", "shelf.rft", "HOUSE_UPPER.RVT", "house.bimcraft", "house.ifc"]
    for n in names:
        put(workdir, "house.rvt", n)
    outs = [outcome(run(["run", n])) for n in names] + [outcome(run(["info", "office.rte"]))]
    golden.check("\n".join(outs), "extensions.txt")


def test_the_core_open_command_does_not_read_revit_files(run, workdir, golden):
    """CATCHES: a rewrite whose `open` command (in a script, unlike a FILE given to `run`) imports a Revit file instead
    of refusing it as a project file, or that keeps going after the failing line."""
    put(workdir, "house.rvt")
    (workdir / "s.txt").write_text('open {"path": "house.rvt"}\ninspect\n')
    golden.check_run(run(["run", "--script", "s.txt"]), "open_command.txt")


def test_an_imported_project_starts_with_no_history_and_takes_commands(run, workdir, golden):
    """CATCHES: a rewrite whose import leaves an undo step (an undo right after the import must say there is nothing to
    undo), or whose imported walls, levels and types cannot be used by later commands: a door placed in the imported wall,
    listed, undone."""
    name = put(workdir, "house.rvt")
    script = "\n".join([
        'door {"at": [3000, 0]}',
        'elements {"category": "door"}',
        'elements {"category": "wall"}',
        "undo",
        'elements {"category": "door"}',
    ])
    (workdir / "s.txt").write_text(script + "\n")
    first = run(["run", name, "--cmd", "undo"])
    later = run(["run", name, "--script", "s.txt", "--cmd", "undo"])
    golden.check(outcome(first) + outcome(later), "commands_after_import.txt")


def test_a_revit_file_given_later_replaces_the_project_built_so_far(run, workdir, golden):
    """CATCHES: a rewrite that merges an imported Revit project into the model made by earlier commands instead of
    replacing it (the level made first is gone afterwards), or that imports only when the file comes first."""
    put(workdir, "levels_2024.rvt")
    put(workdir, "house.rvt")
    r = run(["run", "--cmd", 'level {"elevation": 5000, "name": "Mine"}', "levels_2024.rvt",
             "--cmd", 'elements {"category": "level"}', "house.rvt", "--cmd", 'elements {"category": "level"}'])
    golden.check_run(r, "replaces_project.txt")


def test_an_imported_project_saves_and_opens_again_as_the_same_project(run, workdir, golden):
    """CATCHES: a rewrite whose saved import does not open again to the same elements (types, layers, hosts, rooms), or
    whose save reply differs."""
    name = put(workdir, "openings_2024.rvt")
    first = run(["run", name, "--cmd", "elements {}", "--save", "p.bimcraft"])
    assert first.returncode == 0, outcome(first)
    again = run(["run", "p.bimcraft", "--cmd", "elements {}"])
    golden.check(outcome(first) + outcome(again), "save_and_reopen.txt")
    assert first.stdout.decode().splitlines()[1] == again.stdout.decode().splitlines()[1], "the same elements, GUIDs and all"


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------

def test_convert_a_revit_file_to_a_project(run, workdir, golden):
    """CATCHES: a rewrite whose `convert` of a Revit file writes a project with other elements, types or name than the
    import makes, or replies with another line."""
    name = put(workdir, "rooms_2024.rvt")
    r = run(["convert", name, "out.bimcraft"])
    assert run(["run", "--save", "empty.bimcraft"]).returncode == 0
    saved = json.loads((workdir / "out.bimcraft").read_text())
    empty = json.loads((workdir / "empty.bimcraft").read_text())
    text = outcome(r) + normalize(json.dumps(changed(saved, empty), indent=1, sort_keys=True, ensure_ascii=False)) + "\n"
    golden.check(text, "convert_rooms_to_project.txt")


@pytest.mark.parametrize("name", ["openings_2024.rvt", "floors_2024.rvt", "rooms_odd.rvt"])
def test_convert_a_revit_file_to_a_plan_svg(run, workdir, golden, name):
    """CATCHES: a rewrite whose imported walls, openings, floors, ceilings or rooms draw a different plan of the lowest
    level (an SVG compared as text)."""
    put(workdir, name)
    r = run(["convert", name, "plan.svg"])
    golden.check(outcome(r) + normalize((workdir / "plan.svg").read_text()), f"svg_{name.replace('.', '_')}.txt")


def test_convert_a_revit_file_to_a_plan_png(run, workdir, golden):
    """CATCHES: a rewrite that rasterises the imported plan to other pixels, or another size."""
    name = put(workdir, "rooms_2024.rvt")
    r = run(["convert", name, "plan.png"])
    golden.check(outcome(r) + png_pixels((workdir / "plan.png").read_bytes()), "png_rooms_2024.txt")


@pytest.mark.parametrize("name", ["openings_2024.rvt", "roofs_2024.rvt", "gable_2024.rvt"])
def test_an_imported_project_exports_to_ifc(run, workdir, golden, name):
    """CATCHES: a rewrite whose imported model exports different IFC entities (storeys, walls with their layers and
    materials, openings, roofs by footprint or extrusion, the walls a roof cuts), compared after the project's GUIDs are
    fixed so that the storeys' order is stable."""
    put(workdir, name)
    r = run(["run", name, "--save", "p.bimcraft"])
    assert r.returncode == 0, outcome(r)
    fix_guids(workdir / "p.bimcraft")
    conv = run(["convert", "p.bimcraft", "out.ifc"])
    golden.check(outcome(conv) + normalize((workdir / "out.ifc").read_text()), f"ifc_{name.replace('.', '_')}.txt")


# ---------------------------------------------------------------------------
# the MCP server
# ---------------------------------------------------------------------------

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}


def call(n, name, arguments):
    return {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def test_mcp_serves_a_revit_file_named_on_the_command_line(run, workdir, golden):
    """CATCHES: a rewrite whose `mcp FILE.rvt` does not import the Revit file before it answers, so the agent sees an
    empty project, or whose tools see other elements of it."""
    name = put(workdir, "openings_2024.rvt")
    msgs = [call(2, "query_elements", {"category": "door"}), call(3, "query_elements", {"category": "level"}),
            call(4, "execute", {"command": "elements", "params": {"category": "window"}})]
    golden.check_run(run(["mcp", name], input=mcp_lines(msgs)), "mcp_file.txt")


def test_mcp_open_imports_a_revit_file_and_a_bad_one_is_a_tool_error(run, workdir, golden):
    """CATCHES: a rewrite whose MCP `open` tool does not import a Revit file (its reply: the counts, the format, what was
    skipped), or that answers a damaged one with a protocol error instead of a tool error naming the file, or that loses
    the project it had when the open fails."""
    put(workdir, "walls_odd.rvt")
    put(workdir, "word.rvt")
    msgs = [call(2, "open", {"path": "walls_odd.rvt"}), call(3, "open", {"path": "word.rvt"}),
            call(4, "open", {"path": "missing.rvt"}), call(5, "query_elements", {"category": "level"})]
    golden.check_run(run(["mcp"], input=mcp_lines(msgs)), "mcp_open.txt")


@pytest.mark.parametrize("name", ["text.rvt", "chair.rfa", "release_2014.rvt"])
def test_mcp_refuses_to_start_on_a_revit_file_it_cannot_import(run, workdir, golden, name):
    """CATCHES: a rewrite whose `mcp FILE` serves an empty project when the Revit file named cannot be imported, instead
    of exiting 1 with the reason on stderr and answering nothing."""
    put(workdir, name)
    r = run(["mcp", name], input=mcp_lines([INIT]))
    golden.check_run(r, f"mcp_refused_{name.replace('.', '_')}.txt")
