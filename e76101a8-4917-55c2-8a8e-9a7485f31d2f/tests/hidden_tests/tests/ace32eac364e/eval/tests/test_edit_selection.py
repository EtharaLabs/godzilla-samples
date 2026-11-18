"""Finding and reading elements: select_by_id, ids_of, filter_selection, elements (category, level, limit, offset) and
inspect."""

import json

import pytest
from conftest import make_project, normalize

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'
SETUP = ["--cmd", BOX, "--cmd", 'type {"category": "wall", "name": "Thick", "thickness": 300}',
         "--cmd", 'modify {"ids": [100003, 100005], "type": "Thick"}', "--cmd", 'door {"wall": 100002, "offset": 2000, "mark": "D7"}',
         "--cmd", 'window {"wall": 100003, "offset": 3000}', "--cmd", 'room {"point": [4000, 3000], "name": "Hall"}',
         "--cmd", 'wall {"points": [[0, 0], [4000, 0]], "level": "Level 2", "height": 2500}',
         "--cmd", 'grid {"start": [-1000, -1000], "end": [-1000, 7000]}', "--cmd", 'detail_line {"start": [0, -500], "end": [1000, -500]}',
         "--cmd", 'sheet {}']
# Ids: walls 100002-100005 (100003 and 100005 Thick), door 100006, window 100007, room 100008, a wall on Level 2 100009,
# grid 100010, detail line 100011, sheet 100012.


def block(label, r):
    return (f"=== {label}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode('utf-8', 'replace'))}"
            f"--- stderr\n{normalize(r.stderr.decode('utf-8', 'replace'))}")


def probe(run, cmds):
    args = ["p.bimcraft"]
    for c in cmds:
        args += ["--cmd", c]
    return block(" | ".join(cmds), run(["run", *args]))


@pytest.fixture
def project(run, workdir):
    """The project above, its GUIDs fixed; the GUIDs of its elements by id, and of its library entries by name."""
    path = make_project(run, workdir, "p.bimcraft", SETUP)
    data = json.loads(path.read_text())
    guids = {int(k): v["guid"] for k, v in data["elements"].items()}
    return guids, data


def test_select_by_id_finds_elements_however_they_are_named(run, project, golden):
    """CATCHES: a rewrite whose Select by ID misses a GUID written in capitals, in braces, without dashes or quoted, or an
    IFC GlobalId; lists an element twice, out of order, or a library entry as an element; splits the list on other
    separators; or names another plan or extent for what it found."""
    guids, data = project
    ifc = json.loads(run(["run", "p.bimcraft", "--cmd", 'ids_of {"ids": [100004]}']).stdout.decode().splitlines()[-1])["elements"][0]["ifc"]
    g3, g6 = guids[100003], guids[100006]
    brick = next(e["guid"] for e in data["library"].values() if e["kind"] == "material" and e["name"] == "Brick")
    texts = [
        f"100002, {g3.upper()};{{{g6}}}\n{ifc}  nowhere 100099 100002 \"100007\"",
        f"{g3.replace('-', '')} 100009",
        "100010 100011",
        "100012",
        "100000",
        "",
        "nope 1234",
        f"{brick} 100002",
    ]
    cmds = [f'select_by_id {json.dumps({"text": t})}' for t in texts]
    cmds += ['select_by_id {"text": ["100002", 100003, "x"]}', 'select_by_id {}', 'select_by_id {"text": 5}']
    golden.check("".join(probe(run, [c]) for c in cmds), "select_by_id.txt")


def test_ids_of_names_elements_and_library_entries(run, project, golden):
    """CATCHES: a rewrite whose IDs of Selection gives another id, GUID, IFC GlobalId, category or name for an element or
    a library entry (by its id, GUID or name), or refuses what names nothing in other words."""
    guids, data = project
    cmds = [
        'ids_of {"ids": [100002, 100006, 100007, 100008, 100010, 100011, 100012, 100000]}',
        f'ids_of {json.dumps({"ids": [guids[100003], 100009]})}',
        'ids_of {"id": 100004}',
        'ids_of {"ids": ["Brick", "Thick", 999999, 999628]}',
        'ids_of {"ids": [123]}',
        'ids_of {"ids": ["Nothing at all"]}',
        'ids_of {}',
        'ids_of {"ids": "100002"}',
    ]
    golden.check("".join(probe(run, [c]) for c in cmds), "ids_of.txt")


def test_filter_selection(run, project, golden):
    """CATCHES: a rewrite whose Filter counts a selection by other values (categories' keys, schedule fields as shown in
    the project's units), lists other shared fields, keeps other elements, or words its refusals differently."""
    cmds = [
        ['filter_selection {"ids": [100002, 100006, 100003, 100004, 100005, 100007, 100011]}'],
        ['filter_selection {"ids": [100002, 100006, 100003, 100004, 100005], "keep": ["wall"]}'],
        ['filter_selection {"ids": [100002, 100003, 100004, 100005, 100009], "by": "Type"}'],
        ['filter_selection {"ids": [100002, 100003, 100004, 100005, 100009], "by": "Type", "keep": ["Thick", "Nope"]}'],
        ['filter_selection {"ids": [100002, 100003, 100004, 100005, 100009], "by": "Level"}'],
        ['units {"length": "ft-in"}', 'filter_selection {"ids": [100002, 100003, 100004, 100005, 100009], "by": "Length"}'],
        ['filter_selection {"ids": [100002, 100003], "by": "Length", "keep": ["8000"]}'],
        ['filter_selection {"ids": [100006, 100007], "by": "Mark"}'],
        ['filter_selection {"ids": [100002, 100006], "by": "Mark"}'],
        ['filter_selection {"ids": [100002], "keep": [1]}'],
        ['filter_selection {"ids": [100002], "keep": "wall"}'],
        ['filter_selection {"ids": [100002], "by": 5}'],
        ['filter_selection {"ids": [999999]}'],
        ['filter_selection {}'],
    ]
    golden.check("".join(probe(run, c) for c in cmds), "filter_selection.txt")


def test_elements_by_category_level_and_page(run, project, golden):
    """CATCHES: a rewrite whose `elements` filters by category (any case, singular or plural) or level (by name, id or
    plan) differently, pages with `limit` and `offset` differently, counts otherwise, or words its refusals differently."""
    cmds = [
        ['elements {"category": "walls", "limit": 2}'],
        ['elements {"category": "Wall", "offset": 3}'],
        ['elements {"category": "wall", "level": "Level 2"}'],
        ['elements {"level": 100001}'],
        ['elements {"category": "door", "level": "Level 1"}'],
        ['elements {"limit": 0}'],
        ['elements {"offset": 100}'],
        ['elements {"category": "spaceship"}'],
        ['elements {"limit": -1}'],
        ['elements {"limit": "all"}'],
        ['elements {"level": "Level 9"}'],
        ['elements {"category": 3}'],
    ]
    golden.check("".join(probe(run, c) for c in cmds), "elements.txt")


def test_inspect_warns_and_keeps_the_history(run, project, golden):
    """CATCHES: a rewrite whose `inspect` counts categories, lists levels, warns of an unenclosed room or names undo
    steps differently from the reference."""
    out = probe(run, ['delete {"ids": [100002]}', 'room {"point": [20000, 0], "name": "Out"}', 'level {"elevation": 6000}', 'inspect'])
    golden.check(out, "inspect.txt")
