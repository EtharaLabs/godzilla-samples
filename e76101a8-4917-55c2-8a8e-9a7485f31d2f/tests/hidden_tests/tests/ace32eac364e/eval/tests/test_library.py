"""The project's library: types, materials and textures, paint, project parameters, delete_type, rename_type, purge,
the `library` listing with its ids, GUIDs and parts; and the project's units and language."""

import json

import pytest
from conftest import normalize, pdf_summary, png_pixels, resources_for

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'
CAVITY = json.dumps({"category": "wall", "name": "Cavity 300", "layers": [
    {"function": "finish", "material": "Brick", "thickness": 100},
    {"function": "thermal", "material": "Mineral wool", "thickness": 50},
    {"function": "structure", "material": "Concrete block", "thickness": 140},
    {"function": "finish", "material": "Plaster", "thickness": 10},
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


WALLS = 'elements {"category": "wall"}'

CASES = {
    # type: every category made, changed everywhere it's used, and what a new one needs.
    "types": (
        [BOX, 'door {"at": [2000, 0]}'],
        [
            ['type {"category": "wall", "name": "Brick - 250mm", "thickness": 250}', 'modify {"id": 100002, "type": "Brick - 250mm"}',
             'type {"category": "wall", "name": "Brick - 250mm", "thickness": 280}', WALLS],
            ['type {"category": "door", "name": "Single 900 x 2100", "width": 1000, "operation": "double-swing"}',
             'elements {"category": "door"}'],
            ['type {"category": "door", "name": "Wide"}'],
            ['type {"category": "door", "name": "Wide", "width": 1200}'],
            ['type {"category": "window", "name": "Strip", "width": 2400, "height": 400}', 'type {"category": "window", "name": "Strip", "sill": 1800}'],
            ['type {"category": "floor", "name": "Slab 250", "thickness": 250}', 'type {"category": "roof", "name": "Roof 150", "thickness": 150}',
             'type {"category": "ceiling", "name": "Tile 300", "thickness": 15, "grid": 300}'],
            ['type {"category": "column", "name": "Round 500", "width": 500, "round": true}',
             'type {"category": "structural column", "name": "C 250 x 600", "width": 250, "depth": 600}',
             'type {"category": "footing", "name": "F 2000", "width": 2000}'],
            ['type {"category": "beam", "name": "B 300 x 700", "width": 300, "depth": 700, "material": "Concrete"}',
             'type {"category": "pipe", "name": "PVC 75", "width": 75, "round": true, "material": "PVC"}',
             'type {"category": "cable tray", "name": "Tray 400", "width": 400, "depth": 100}'],
            ['type {"category": "beam", "name": "B 1", "width": 300}'],
            ['type {"category": "railing", "name": "Low", "height": 900, "spacing": 0}', 'type {"category": "railing", "name": "No"}'],
            ['type {"category": "room", "name": "X"}'],
            ['type {"name": "X", "thickness": 1}'],
            ['type {"category": "wall", "thickness": 1}'],
            ['type {"category": "wall", "name": " ", "thickness": 1}'],
            ['type {"category": "wall", "name": "Nothing"}'],
            ['type {"category": "wall", "name": "Thin", "thickness": -5}'],
            ['type {"category": "wall", "name": "Thin", "thickness": "thick"}'],
        ],
    ),
    # Compound types: as thick as their layers, a new thickness going to the structure, layers keeping their ids.
    "layered_types": (
        ['material {"name": "Mineral wool", "color": "#e6d68c", "cut": "insulation"}', "type " + CAVITY,
         'wall {"points": [[0, 0], [5000, 0]], "type": "Cavity 300"}'],
        [
            [WALLS, 'library {"kind": "layer", "name": "Cavity 300"}'],
            ['type {"category": "wall", "name": "Cavity 300", "thickness": 340}', WALLS, 'library {"kind": "layer", "name": "Cavity 300"}'],
            ['type {"category": "wall", "name": "Cavity 300", "thickness": 100}'],
            ['type {"category": "wall", "name": "Cavity 300", "thickness": 290, "layers": [{"material": "Brick", "thickness": 300}]}'],
            ['type {"category": "wall", "name": "Odd", "layers": [{"material": "Unobtainium", "thickness": 100}]}'],
            ['type {"category": "wall", "name": "Odd", "layers": [{"function": "glue", "thickness": 100}]}'],
            ['type {"category": "wall", "name": "Odd", "layers": [{"thickness": 0}]}'],
            ['type {"category": "wall", "name": "Odd", "layers": []}'],
            ['type {"category": "floor", "name": "Screeded", "layers": [{"function": "finish", "material": "Ceramic tile", "thickness": 10},'
             ' {"function": "substrate", "material": "Screed", "thickness": 40}, {"function": "structure", "material": "Concrete", "thickness": 200}]}',
             'floor {"boundary": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]], "type": "Screeded"}', 'elements {"category": "floor"}'],
            ['material {"name": "Mineral wool", "delete": true}'],
            ['material {"name": "Mineral wool", "rename": "Rock wool"}', 'library {"kind": "layer", "name": "Cavity 300"}',
             'inspect'],
        ],
    ),
    # material: made, changed, its texture of a pattern drawn in code, renamed and deleted; and what it refuses.
    "materials": (
        ['material {"name": "Oak", "color": "#a07040", "cut": "diagonal", "surface": "horizontal"}'],
        [
            ['material {"name": "Oak"}', 'material {"name": "Oak", "color": [10, 20, 30], "transparency": 25}'],
            ['material {"name": "Oak", "texture": {"kind": "boards"}}', 'material {"name": "Oak", "texture": {"size": [600, 300], "angle": 90, "offset": [10, 20]}}',
             'material {"name": "Oak", "texture": {"size": 250}}', 'material {"name": "Oak", "texture": null}'],
            ['material {"name": "Oak", "rename": "Walnut"}', 'library {"kind": "material", "name": "Walnut"}', 'material {"name": "Walnut", "delete": true}',
             'library {"kind": "material", "name": "Walnut"}'],
            ['fill_pattern {"name": "Dots", "target": "model", "lines": [{"angle": 0, "spacing": 100, "dashes": [0, -100]}]}',
             'material {"name": "Oak", "surface": "Dots", "cut": "Dots"}'],
            ['material {"name": "Oak", "rename": "Brick"}'],
            ['material {"name": "Oak", "rename": " "}'],
            ['material {"name": "Nope", "delete": true}'],
            ['material {"name": "Brick", "delete": true}'],
            ['material {"name": "Timber", "delete": true}'],
            ['material {"color": "#ffffff"}'],
            ['material {"name": "Oak", "color": "#ggg"}'],
            ['material {"name": "Oak", "color": [1, 2]}'],
            ['material {"name": "Oak", "color": [1, 2, 300]}'],
            ['material {"name": "Oak", "transparency": 101}'],
            ['material {"name": "Oak", "transparency": 2.5}'],
            ['material {"name": "Oak", "cut": "zigzag"}'],
            ['material {"name": "Oak", "texture": "brick"}'],
            ['material {"name": "Oak", "texture": {"kind": "marble"}}'],
            ['material {"name": "Oak", "texture": {"size": [10, 10]}}'],
            ['material {"name": "Oak", "texture": {"kind": "brick", "size": [0, 10]}}'],
            ['material {"name": "Oak", "texture": {"kind": "brick", "size": [1, 2, 3]}}'],
            ['material {"name": "Oak", "texture": {"kind": "brick", "angle": "steep"}}'],
            ['material {"name": "Oak", "texture": {"kind": "brick", "path": "x.png"}}'],
            ['material {"name": "Oak", "texture": {"kind": "image"}}'],
            ['material {"name": "Oak", "texture": {"kind": "image", "image": "nope"}}'],
            ['material {"name": "Oak", "texture": {"kind": "brick", "scale": 2}}'],
        ],
    ),
    # paint: a face of an element painted, every face, paint taken off; what has no face, or no such face.
    "paint": (
        [BOX, 'floor {}', 'family {"name": "Box", "types": {"A": {}}, "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500}]}',
         'component {"family": "Box", "at": [1000, 1000]}', 'grid {"start": [0, -1000], "end": [0, 7000]}'],
        [
            ['paint {"id": 100002, "face": "exterior", "material": "Brick"}', 'PT {"ids": [100006, 100007], "material": "Timber"}',
             'elements {"category": "wall"}', 'elements {"category": "floor"}', 'elements {"category": "component"}'],
            ['paint {"ids": [100002, 100003], "material": "Glass"}', 'paint {"id": 100002, "face": "interior", "material": null}', WALLS],
            ['paint {"id": 100002, "material": "Brick"}', 'material {"name": "Brick", "delete": true}'],
            ['paint {"id": 100002, "face": "top", "material": "Brick"}'],
            ['paint {"id": 100008, "material": "Brick"}'],
            ['paint {"id": 100002, "material": "Nope"}'],
            ['paint {"id": 100002}'],
            ['paint {"id": 100002, "material": 5}'],
            ['paint {"material": "Brick"}'],
            ['modify {"id": 100002, "params": {"Paint": {"top": "Brick"}}}'],
            ['modify {"id": 100002, "params": {"Paint": {"exterior": "Nope"}}}'],
            ['modify {"id": 100002, "params": {"Paint": "Brick"}}'],
            ['modify {"id": 100002, "params": {"Paint": {"exterior": "Brick"}}}', WALLS],
        ],
    ),
    # Project parameters: values of their own on the elements of their categories, renamed, retyped, deleted.
    "parameters": (
        [BOX, 'door {"at": [2000, 0]}', 'room {"point": [4000, 3000], "name": "Hall"}',
         'parameter {"name": "Fire Rating", "kind": "text", "categories": ["wall", "door"]}',
         'parameter {"name": "Accessible", "kind": "yesno", "categories": ["room"]}',
         'modify {"id": 100002, "params": {"Fire Rating": "EI 60"}}', 'modify {"id": 100007, "params": {"Accessible": true}}'],
        [
            ['elements {"category": "wall", "limit": 1}', 'elements {"category": "room"}'],
            ['parameter {"name": "Fire Rating", "rename": "Rating"}', 'elements {"category": "wall", "limit": 1}', 'library {"kind": "parameter"}'],
            ['parameter {"name": "Fire Rating", "categories": ["door"]}', 'elements {"category": "wall", "limit": 1}'],
            ['parameter {"name": "Fire Rating", "delete": true}', 'elements {"category": "wall", "limit": 1}'],
            ['parameter {"name": "Width Note", "kind": "length", "categories": ["window", "column", "component"]}', 'parameter {"name": "Width Note"}'],
            ['parameter {"name": "Fire Rating", "kind": "number"}'],
            ['modify {"id": 100002, "params": {"Accessible": true}}'],
            ['modify {"id": 100007, "params": {"Accessible": "yes"}}'],
            ['parameter {"name": "Fire Rating", "rename": "Accessible"}'],
            ['parameter {"name": "Fire Rating", "rename": ""}'],
            ['parameter {"name": "X", "kind": "colour"}'],
            ['parameter {"name": "X", "categories": ["sheet"]}'],
            ['parameter {"name": "X", "categories": "wall"}'],
            ['parameter {"name": "Nope", "delete": true}'],
            ['parameter {}'],
        ],
    ),
    # delete_type and rename_type, of a category's types and of a family's, with their refusals.
    "delete_and_rename_types": (
        [BOX, 'type {"category": "wall", "name": "Spare", "thickness": 120}', 'component {"family": "Table", "type": "1600 x 900", "at": [1000, 1000]}'],
        [
            ['delete_type {"category": "wall", "type": "Spare"}', 'library {"kind": "type:wall"}'],
            ['delete_type {"category": "wall", "type": "Generic - 200mm"}'],
            ['delete_type {"category": "floor", "type": "Generic - 200mm"}'],
            ['delete_type {"category": "wall", "type": "Nope"}'],
            ['delete_type {"family": "Table", "type": "1200 x 800"}', 'family {"name": "Table"}'],
            ['delete_type {"family": "Table", "type": "1600 x 900"}'],
            ['delete_type {"family": "Table"}'],
            ['delete_type {"family": "Bed"}', 'family {"name": "Bed"}'],
            ['delete_type {"family": "WC", "type": "400 x 650"}'],
            ['delete_type {"family": "Nope"}'],
            ['delete_type {"family": "Table", "type": "9 x 9"}'],
            ['delete_type {"type": "Spare"}'],
            ['rename_type {"category": "wall", "type": "Generic - 200mm", "name": "Plain 200"}', WALLS, 'library {"kind": "type:wall"}'],
            ['rename_type {"family": "Table", "type": "1600 x 900", "name": "Large"}', 'elements {"category": "component"}'],
            ['rename_type {"category": "wall", "type": "Spare", "name": "Spare"}'],
            ['rename_type {"category": "wall", "type": "Spare", "name": "Generic - 200mm"}'],
            ['rename_type {"family": "Table", "type": "1600 x 900", "name": "1200 x 800"}'],
            ['rename_type {"category": "wall", "type": "Spare"}'],
            ['rename_type {"category": "wall", "type": "Spare", "name": "X", "colour": 1}'],
            ['rename_type {"category": "door", "type": "Nope", "name": "X"}'],
        ],
    ),
    # purge: what nothing uses, pass after pass; a dry run lists it and changes nothing.
    "purge": (
        [BOX, 'material {"name": "Lonely", "color": "#123456"}',
         'family {"name": "Crate", "types": {"A": {}}, "parameters": [{"name": "M", "kind": "material", "value": "Lonely"}],'
         ' "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500, "material": "M"}]}',
         'type {"category": "wall", "name": "Spare", "thickness": 120}'],
        [
            ['purge {"dry_run": true}', 'library {"kind": "type:wall"}'],
            ['PU {}', 'purge {}'],
            ['purge {"kinds": ["material"]}'],
            ['purge {"kinds": ["family", "material"], "dry_run": true}'],
            ['purge {"kinds": ["template", "filter", "picture"]}'],
            ['purge {"kinds": ["spaceship"]}'],
            ['purge {"kinds": "type"}'],
            ['purge {"kinds": []}'],
        ],
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_library_commands(run, workdir, golden, case):
    """CATCHES: a rewrite whose types, materials, paint, project parameters, type deletion and renaming, or Purge
    Unused change the model differently (thicknesses, layers and their ids, values that follow a rename, what purge
    takes in which order), reply in a different shape, or refuse other inputs, in other words."""
    setup, probes = CASES[case]
    golden.check(session(run, workdir, setup, probes), f"{case}.txt")


def test_a_texture_of_a_picture(run, workdir, golden):
    """CATCHES: a rewrite that takes a PNG into the project differently (its id, kept size, tile size from its
    proportions), keeps a picture no material uses, or reads a file that isn't a picture without the reference's error."""
    (workdir / "grass.png").write_bytes((resources_for(__file__) / "grass.png").read_bytes())  # a 4 x 2 green PNG
    (workdir / "notpng.png").write_bytes(b"this is not a picture at all")
    r = run(["run", "--cmd", 'material {"name": "Lawn", "texture": {"kind": "image", "path": "grass.png"}}',
             "--cmd", 'material {"name": "Turf", "texture": {"kind": "image", "path": "grass.png", "size": [500, 500]}}',
             "--cmd", 'library {"kind": "picture"}',
             "--cmd", 'material {"name": "Lawn", "texture": {"kind": "brick"}}',
             "--cmd", 'material {"name": "Turf", "texture": null}',
             "--cmd", 'library {"kind": "picture"}',
             "--cmd", 'material {"name": "Lawn", "texture": {"kind": "image", "path": "missing.png"}}'])
    golden.check_run(r, "picture_texture.txt")
    r = run(["run", "--cmd", 'material {"name": "Lawn", "texture": {"kind": "image", "path": "notpng.png"}}'])
    golden.check_run(r, "picture_not_a_picture.txt")


def test_the_library_lists_every_entry_with_its_id_and_guid(run, golden):
    """CATCHES: a rewrite whose starter library has other entries, kinds, names, ids (counting down from 999999) or
    parts, or whose `library` filters by kind and name differently."""
    r = run(["run", "--cmd", "library", "--cmd", 'library {"kind": "type:door"}', "--cmd", 'library {"kind": "family", "name": "Bed"}',
             "--cmd", 'library {"kind": "family-type", "name": "Bed: 900 x 2000"}', "--cmd", 'library {"kind": "nothing"}',
             "--cmd", 'library {"kind": "connector"}'])
    golden.check_run(r, "library_listing.txt")


UNITS_SETUP = [BOX, 'room {"point": [4000, 3000], "name": "Hall"}', 'dimension {"refs": [{"id": 100002}, {"id": 100004}], "at": [1000, 3000]}',
               'schedule {"name": "Walls", "category": "walls", "fields": ["Type", "Length", "Height", "Thickness"]}']


@pytest.mark.parametrize("unit", ["mm", "cm", "m", "in", "ft", "ft-in"])
def test_units_change_what_drawings_and_schedules_show(run, workdir, golden, unit):
    """CATCHES: a rewrite whose project units change the model or command replies (which stay in mm), or that formats
    lengths and areas in schedules' files and the plan's dimension text differently from the reference."""
    (workdir / "setup.txt").write_text("\n".join(UNITS_SETUP) + "\n")
    r = run(["run", "--script", "setup.txt", "--cmd", f'UN {{"length": "{unit}"}}', "--cmd", 'elements {"category": "room"}',
             "--cmd", 'schedule {"name": "Walls", "path": "walls.csv"}', "--cmd", 'schedule {"name": "Room Schedule", "path": "rooms.csv"}',
             "--cmd", 'schedule {"name": "Long", "category": "walls", "filters": [{"field": "Length", "op": "greater", "value": 7000}]}',
             "--save", "plan.svg"])
    golden.check_run(r, f"units_{unit}.txt")
    golden.check((workdir / "walls.csv").read_text() + "---\n" + (workdir / "rooms.csv").read_text(), f"units_{unit}.csv")
    golden.check((workdir / "plan.svg").read_text(), f"units_{unit}.svg")


def test_units_command_and_its_refusal(run, golden):
    """CATCHES: a rewrite whose `units` without a length doesn't just say the current one, that takes an undo step for
    no change, keeps the units out of the saved project, or words its refusal differently."""
    out = []
    for args in [["--cmd", "units", "--cmd", 'units {"length": "mm"}', "--cmd", "undo"],
                 ["--cmd", 'units {"length": "ft"}', "--cmd", "undo", "--cmd", "units", "--cmd", "redo", "--save", "u.bimcraft"],
                 ["u.bimcraft", "--cmd", "units"],
                 ["--cmd", 'units {"length": "furlongs"}'],
                 ["--cmd", 'units {"length": 5}']]:
        r = run(["run", *args])
        out.append(f"=== {' '.join(args)}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "units_command.txt")


LANGUAGE_PROBE = [BOX, 'room {"point": [4000, 3000]}', 'section {"start": [-1000, 3000], "end": [9000, 3000]}', 'elevation {}',
                  'sheet {}', 'level {"elevation": 6000}', 'grid {"start": [0, -1000], "end": [0, 7000]}',
                  'schedule {"category": "rooms"}', 'schedule {"category": "doors"}', 'elements {"category": "room"}',
                  'elements {"category": "elevation"}', 'elements {"category": "sheet"}', 'detail_line {"start": [0, 0], "end": [100, 0]}',
                  'elements {"category": "line"}']


@pytest.mark.parametrize("code", ["en", "pt", "es", "sv", "cs", "fr", "nl", "de", "it"])
def test_a_new_project_names_what_it_makes_in_its_language(run, workdir, golden, code):
    """CATCHES: a rewrite whose project languages name levels, rooms, sections, elevations, sheets, schedules and their
    headings, or the default line style, differently, or keep another language's words in a drawing's lettering."""
    (workdir / "s.txt").write_text(f'new {{"language": "{code}"}}\n' + "\n".join(LANGUAGE_PROBE) + "\n")
    r = run(["run", "--script", "s.txt", "--cmd", 'stair {"start": [1000, 1000], "angle": 0}', "--save", "plan.svg"])
    golden.check_run(r, f"language_{code}.txt")
    golden.check((workdir / "plan.svg").read_text(), f"language_{code}.svg")


def test_language_command(run, golden):
    """CATCHES: a rewrite whose `language` renames what's already named, takes codes and aliases differently, keeps no
    undo step, or words its refusals differently."""
    out = []
    for args in [["--cmd", 'new {"name": "Casa", "language": "pt"}', "--cmd", "language", "--cmd", BOX, "--cmd", 'room {"point": [4000, 3000]}',
                  "--cmd", 'language {"code": "en"}', "--cmd", 'level {"elevation": 6000}', "--cmd", 'room {"point": [4000, 3000]}',
                  "--cmd", 'elements {"category": "room"}', "--cmd", "undo", "--cmd", "undo", "--cmd", "undo", "--cmd", "language"],
                 ["--cmd", 'language {"code": "Deutsch"}', "--cmd", 'language {"code": "pt-BR"}', "--cmd", 'language {"code": "CZ"}',
                  "--cmd", 'language {"code": "nl_BE"}', "--cmd", 'language {"code": "vlaams"}', "--cmd", 'language {"code": "it"}'],
                 ["--cmd", 'language {"code": "klingon"}'],
                 ["--cmd", 'new {"language": "vi"}'],
                 ["--cmd", 'new {"name": "X", "language": 3}']]:
        r = run(["run", *args])
        out.append(f"=== {' '.join(args)}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "language_command.txt")


def test_rename_a_type_of_every_category(run, workdir, golden):
    """CATCHES: a rewrite whose rename_type misses a category's types (floors, doors, windows, columns, structural
    columns, footings, roofs, ceilings, railings, runs) or the elements of them, or doesn't keep the type's GUID."""
    setup = [BOX, 'door {"at": [2000, 0]}', 'window {"at": [8000, 3000]}', 'floor {}', 'ceiling {"point": [4000, 3000]}',
             'column {"at": [2000, 2000]}', 'structural_column {"at": [3000, 2000]}', 'footing {"at": [4000, 2000]}',
             'roof {"boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "slope": 0}', 'railing {"path": [[1000, 5000], [3000, 5000]]}',
             'beam {"points": [[1000, 3000], [5000, 3000]]}', 'pipe {"points": [[1000, 4000], [5000, 4000]]}']
    renames = [("floor", "Generic - 200mm"), ("door", "Single 900 x 2100"), ("window", "Fixed 1200 x 1500"),
               ("column", "Rectangular 400 x 400"), ("structuralcolumn", "Concrete 300 x 300"), ("footing", "Footing 1200 x 1200"),
               ("roof", "Generic - 300mm"), ("ceiling", "Generic - 20mm"), ("railing", "Railing - 1000mm"),
               ("beam", "Beam 200 x 500"), ("pipe", "PVC 110"), ("duct", "Round 300")]
    cmds = [f'rename_type {json.dumps({"category": c, "type": t, "name": t + " (renamed)"})}' for c, t in renames]
    probes = [cmds + ['elements {}', 'library {"name": "PVC 110 (renamed)"}'],
              ['rename_type {"category": "floor", "type": "Generic - 200mm", "name": "  "}']]
    golden.check(session(run, workdir, setup, probes), "rename_every_category.txt")


def test_purge_family_types_filters_and_templates(run, workdir, golden):
    """CATCHES: a rewrite whose purge takes a used family's unused types other than the reference does (it keeps one),
    leaves unused view filters or templates, or takes a filter or template a view uses."""
    setup = [BOX, 'component {"family": "Table", "type": "1600 x 900", "at": [1000, 1000]}',
             'filter {"name": "Thick walls", "categories": ["walls"], "rules": [{"field": "Thickness", "op": "greater", "value": 250}]}',
             'filter {"name": "Spare", "categories": ["doors"]}',
             'graphics {"view": "Level 1", "filters": [{"filter": "Thick walls", "hidden": true}]}',
             'template {"name": "Mine", "from": "Level 1"}', 'graphics {"view": "Level 2", "template": "Mine"}']
    probes = [
        ['purge {"kinds": ["type"], "dry_run": true}'],
        ['purge {"kinds": ["filter", "template"]}', 'library {"kind": "view-filter"}', 'library {"kind": "view-template"}'],
        ['purge {"kinds": ["family"]}', 'family {}'],
    ]
    golden.check(session(run, workdir, setup, probes), "purge_more.txt")


def test_library_parts_of_every_kind(run, workdir, golden):
    """CATCHES: a rewrite whose library lists other parts with ids and GUIDs (a type's layers, a family's forms, symbols
    and connectors, a sketch's lines, a shape's points and split lines, a detail group's members) or numbers them
    otherwise."""
    setup = ['floor {"sketch": [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]], [[4000, 3000], [0, 3000]], [[0, 3000], [0, 0]]]}',
             'add_point {"id": 100002, "at": [2000, 1500], "z": -30}', 'add_split_line {"id": 100002, "a": [0, 0], "b": [4000, 3000]}',
             'detail_line {"start": [0, -1000], "end": [500, -1000]}', 'detail_line {"start": [0, -1200], "end": [500, -1200]}',
             'create_group {"ids": [100003, 100004], "name": "Pair"}']
    probes = [['library {"kind": "sketch line"}', 'library {"kind": "shape point"}', 'library {"kind": "split line"}',
               'library {"kind": "member"}', 'library {"kind": "connector"}', 'library {"kind": "layer"}', 'library {"kind": "symbol"}',
               'library {"kind": "form", "name": "Base Cabinet"}']]
    golden.check(session(run, workdir, setup, probes), "library_parts.txt")


def _png(width, height, rgb, ihdr_size=None):
    """A PNG of one colour; `ihdr_size` puts another size in its header than its data has."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    w, h = ihdr_size or (width, height)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_pictures_taken_in_resized_or_refused(run, workdir, golden):
    """CATCHES: a rewrite that keeps a picture over 1024 px a side at another size, takes in a JPEG differently (its id,
    its size, a grey one as colour), lets one material's texture use another's picture by id differently, takes more
    than 24 pictures, or refuses a picture too large in its header, cut short or not decodable with other words.
    (A picture's id is a hash of the PNG the program keeps, made from its pixels, so it doesn't depend on how the test's
    PNG was compressed.)"""
    (workdir / "wide.png").write_bytes(_png(2050, 3, (200, 30, 30)))
    (workdir / "huge.png").write_bytes(_png(2, 2, (0, 0, 0), ihdr_size=(5000, 5000)))
    (workdir / "short.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (workdir / "broken.png").write_bytes(_png(4, 4, (1, 2, 3))[:40] + b"garbage")
    (workdir / "broken.jpg").write_bytes(b"\xff\xd8\xff\xe0garbage")
    for name in ("gray.jpg", "mono.jpg"):  # baseline JPEGs of flat grey: 16 x 8 in colour, and 8 x 8 grey-scale
        (workdir / name).write_bytes((resources_for(__file__) / name).read_bytes())
    for k in range(25):
        (workdir / f"c{k}.png").write_bytes(_png(2, 2, (k * 10, 100, 50)))
    first = run(["run", "--cmd", 'material {"name": "Wide", "texture": {"kind": "image", "path": "wide.png"}}'])
    image = json.loads(first.stdout.decode().splitlines()[0])["material"]["texture"]["image"]
    out = []
    for cmd in [
        ['material {"name": "Wide", "texture": {"kind": "image", "path": "wide.png"}}',
         f'material {{"name": "Copy", "texture": {{"kind": "image", "image": "{image}"}}}}', 'inspect'],
        ['material {"name": "Gray", "texture": {"kind": "image", "path": "gray.jpg"}}',
         'material {"name": "Mono", "texture": {"kind": "image", "path": "mono.jpg"}}', 'library {"kind": "picture"}'],
        ['material {"name": "X", "texture": {"kind": "image", "path": "huge.png"}}'],
        ['material {"name": "X", "texture": {"kind": "image", "path": "short.png"}}'],
        ['material {"name": "X", "texture": {"kind": "image", "path": "broken.png"}}'],
        ['material {"name": "X", "texture": {"kind": "image", "path": "broken.jpg"}}'],
        ['material {"name": "X", "texture": {"kind": "image", "path": 5}}'],
        ['material {"name": "X", "texture": {"kind": "image", "image": 5}}'],
        [f'material {{"name": "M{k}", "texture": {{"kind": "image", "path": "c{k}.png"}}}}' for k in range(25)],
    ]:
        args = []
        for c in cmd:
            args += ["--cmd", c]
        r = run(["run", *args])
        out.append(f"=== {cmd[0]}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "pictures.txt")


def test_textures_are_drawn_in_the_3d_view(run, workdir, golden):
    """CATCHES: a rewrite whose 3D view draws a material's texture (each pattern drawn in code, a picture, their size,
    angle and offset, paint over a type's material) differently from the reference."""
    (workdir / "grass.png").write_bytes((resources_for(__file__) / "grass.png").read_bytes())
    kinds = ["brick", "block", "boards", "concrete", "plaster", "tile", "roof", "fabric", "metal", "insulation"]
    lines = []
    for k, kind in enumerate(kinds):
        lines.append(f'material {{"name": "T{k}", "color": [{60 + k * 15}, 120, 90], "texture": {{"kind": "{kind}", "size": 400, "angle": {k * 10}, "offset": [{k * 7}, 3]}}}}')
        lines.append(f'wall {{"points": [[{k * 1500}, 0], [{k * 1500 + 1200}, 0]], "height": 2000}}')
        lines.append(f'paint {{"id": {100002 + k}, "material": "T{k}"}}')
    lines.append('material {"name": "Lawn", "texture": {"kind": "image", "path": "grass.png", "size": [300, 150]}}')
    lines.append('floor {"boundary": [[0, -3000], [15000, -3000], [15000, -500], [0, -500]]}')
    lines.append('paint {"id": 100012, "face": "top", "material": "Lawn"}')
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    r = run(["run", "--script", "s.txt", "--cmd", 'render {"view": "{3D}", "width": 320, "height": 200, "azimuth": 250, "elevation": 25, "path": "v.png"}'])
    golden.check_run(r, "textures_3d.txt")
    golden.check(png_pixels((workdir / "v.png").read_bytes()), "textures_3d.png.txt")


def test_a_project_file_whose_ids_or_guids_clash_is_refused(run, workdir, golden):
    """CATCHES: a rewrite that opens a project file in which two elements share a GUID, an element's GUID is a number,
    two library entries share an id, a GUID or a name, instead of refusing it with the reference's words."""
    r = run(["run", "--cmd", BOX, "--cmd", 'material {"name": "Oak", "color": "#a07040"}', "--save", "good.bimcraft"])
    assert r.returncode == 0, r.stderr.decode()
    good = json.loads((workdir / "good.bimcraft").read_text())
    lib = good["library"]
    oak = next(k for k, v in lib.items() if v["name"] == "Oak")
    brick = next(k for k, v in lib.items() if v["name"] == "Brick" and v["kind"] == "material")

    def variant(name, change):
        data = json.loads(json.dumps(good))
        change(data)
        (workdir / name).write_text(json.dumps(data, indent=1))

    variant("same_guid.bimcraft", lambda d: d["elements"]["100003"].update(guid=d["elements"]["100002"]["guid"]))
    variant("guid_number.bimcraft", lambda d: d["elements"]["100003"].update(guid=100003))
    variant("lib_same_guid.bimcraft", lambda d: d["library"][oak].update(guid=d["library"][brick]["guid"]))
    variant("lib_same_name.bimcraft", lambda d: d["library"][oak].update(name="Brick"))
    variant("lib_guid_number.bimcraft", lambda d: d["library"][oak].update(guid=5))
    out = []
    for name in ["same_guid", "guid_number", "lib_same_guid", "lib_same_name", "lib_guid_number"]:
        r = run(["run", f"{name}.bimcraft", "--cmd", 'library {"kind": "material", "name": "Oak"}'])
        out.append(f"=== {name}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{normalize(r.stderr.decode())}")
    golden.check("".join(out), "clashing_files.txt")


@pytest.mark.parametrize("unit", ["mm", "m", "ft-in", "in"])
def test_units_on_sheets_spots_and_line_weights(run, workdir, golden, unit):
    """CATCHES: a rewrite whose project units don't reach a sheet's title block and viewport scales (1 : 100, or the
    architect's 1/8" = 1'-0" and the engineer's 1" = 20'-0"), a spot elevation's or a level head's text, or the names
    of the model line weights' scales, or that formats them differently from the reference."""
    (workdir / "s.txt").write_text("\n".join([
        BOX, 'floor {"offset": -150}', 'spot {"at": [3000, 3000]}', 'section {"start": [-1000, 3000], "end": [9000, 3000]}',
        f'units {{"length": "{unit}"}}', 'sheet {}', 'place {"sheet": "A101", "view": "Level 1"}',
        'place {"sheet": "A101", "view": "Section 1", "scale": 240}', 'line_weights {}']) + "\n")
    r = run(["run", "--script", "s.txt", "--save", "sheet.pdf", "--save", "plan.svg"])
    golden.check_run(r, f"sheet_units_{unit}.txt")
    golden.check(pdf_summary((workdir / "sheet.pdf").read_bytes()), f"sheet_units_{unit}.pdf.txt")
    golden.check((workdir / "plan.svg").read_text(), f"sheet_units_{unit}.svg")


def test_a_parameter_follows_into_schedules_and_view_filters(run, workdir, golden):
    """CATCHES: a rewrite whose project parameter, renamed, leaves a schedule's column, filter or sort or a view filter's
    rule on the old name; taken off a category, leaves that category's schedules showing it; or lets a parameter a view
    filter has a rule on go."""
    setup = [BOX, 'parameter {"name": "Rating", "kind": "text", "categories": ["wall"]}', 'modify {"id": 100002, "params": {"Rating": "EI 60"}}',
             'schedule {"name": "Rated", "category": "walls", "fields": ["Type", "Rating"], "filters": [{"field": "Rating", "op": "has-value"}], "sort": ["Rating"]}',
             'filter {"name": "Rated walls", "categories": ["walls"], "rules": [{"field": "Rating", "op": "equals", "value": "EI 60"}]}']
    probes = [
        ['parameter {"name": "Rating", "rename": "Fire Rating"}', 'schedule {"name": "Rated"}', 'filter {"name": "Rated walls"}'],
        ['parameter {"name": "Rating", "delete": true}'],
        ['parameter {"name": "Rating", "categories": ["door"]}'],
        ['filter {"name": "Rated walls", "delete": true}', 'parameter {"name": "Rating", "categories": ["door"]}', 'schedule {"name": "Rated"}'],
        ['filter {"name": "Rated walls", "delete": true}', 'parameter {"name": "Rating", "delete": true}', 'schedule {"name": "Rated"}',
         'elements {"category": "wall", "limit": 1}'],
    ]
    golden.check(session(run, workdir, setup, probes), "parameter_follows.txt")


def test_names_a_family_or_a_type_may_not_take_and_files_too_large(run, workdir, golden):
    """CATCHES: a rewrite that lets a family parameter take a name an element holds its phase, design option or mass
    under, a type more than 32 layers, or reads a family file of 256 MiB or a picture of more than 32 MiB instead of
    refusing it by its size."""
    with open(workdir / "huge.json", "wb") as f:
        f.truncate(256 << 20)  # sparse: takes no room on disk
    with open(workdir / "huge.png", "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.truncate((32 << 20) + 1)
    out = []
    many = json.dumps([{"thickness": 10}] * 33)
    for cmd in ['family {"name": "F", "types": {"A": {}}, "parameters": [{"name": "Phase Created"}]}',
                'family {"name": "F", "types": {"A": {}}, "parameters": [{"name": "Design Option"}]}',
                'family {"name": "F", "types": {"A": {}}, "parameters": [{"name": "Mass Face"}]}',
                'family {"path": "huge.json"}',
                'material {"name": "X", "texture": {"kind": "image", "path": "huge.png"}}',
                f'type {{"category": "wall", "name": "Many", "layers": {many}}}',
                'type {"category": "wall", "name": "Bare", "thickness": 120, "layers": []}',
                'type {"category": "wall", "name": "Bare", "layers": "thick"}']:
        r = run(["run", "--cmd", cmd])
        out.append(f"=== {cmd[:120]}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "refused_names_and_sizes.txt")


def test_what_the_model_check_refuses_of_types_and_parameters(run, golden):
    """CATCHES: a rewrite whose model check lets a project parameter take a name a category's elements or a family's
    parameters already have, a reserved name or no category, or lets a type have a material the library hasn't, balusters
    closer than 50 mm or ceiling tiles under 100 mm; or refuses them in other words."""
    out = []
    for cmd in ['parameter {"name": "Height", "categories": ["wall"]}',
                'parameter {"name": "Width", "categories": ["component"]}',
                'parameter {"name": "Paint", "categories": ["wall"]}',
                'parameter {"name": "Phase Created", "categories": ["wall"]}',
                'parameter {"name": "Lonely"}',
                'parameter {"name": "9 lives", "categories": ["wall"]}',
                'type {"category": "beam", "name": "B", "width": 100, "depth": 200, "material": "Unobtainium"}',
                'type {"category": "railing", "name": "R", "height": 900, "spacing": 10}',
                'type {"category": "ceiling", "name": "C", "thickness": 20, "grid": 50}',
                'type {"category": "door", "name": "D", "width": 0, "height": 2000}',
                'type {"category": "column", "name": "C", "width": -1}']:
        r = run(["run", "--cmd", cmd])
        out.append(f"=== {cmd}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "checked_types_and_parameters.txt")
