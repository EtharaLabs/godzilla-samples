"""Projects and files between projects: new, insert (Insert from File), link and reload (Link Model), autosave and
recover."""

import json
import os

import pytest
from conftest import normalize, resources_for

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'


def block(label, r):
    return (f"=== {label}\nexit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode('utf-8', 'replace'))}"
            f"--- stderr\n{normalize(r.stderr.decode('utf-8', 'replace'))}")


def made(run, name, *cmds):
    """A project made by the program: `cmds` run and saved as `name` (in the working directory)."""
    args = []
    for c in cmds:
        args += ["--cmd", c]
    r = run(["run", *args, "--save", name])
    assert r.returncode == 0, r.stderr.decode()


def project_part(path):
    """A saved project's top-level keys and its elements, normalised (the library is checked elsewhere)."""
    data = json.loads(path.read_text())
    return normalize(json.dumps({"keys": list(data), "next_id": data["next_id"], "elements": data["elements"]}, indent=1) + "\n")


def runs(run, steps, cwd=None):
    """Each step a list of `run` arguments (a bare word that ends in .bimcraft or .ifc opens that file), in a process of
    its own; their transcript."""
    out = []
    for step in steps:
        args = []
        for a in step:
            args += [a] if a.endswith((".bimcraft", ".ifc")) and " " not in a else ["--cmd", a]
        out.append(block(" | ".join(step), run(["run", *args], cwd=cwd)))
    return "".join(out)


ARCH = [BOX, 'door {"at": [2000, 0], "mark": "D1"}', 'room {"point": [4000, 3000], "name": "Hall"}',
        'type {"category": "wall", "name": "Brick 250", "thickness": 250}', 'wall {"points": [[0, 8000], [6000, 8000]], "type": "Brick 250"}',
        'material {"name": "Oak", "color": "#a07040"}',
        'family {"name": "Crate", "types": {"A": {}}, "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500, "material": "Oak"}]}',
        'component {"family": "Crate", "at": [1000, 1000]}', 'level {"elevation": 6000, "name": "Roof"}',
        'wall {"points": [[0, 0], [4000, 0]], "level": "Roof", "height": 1000}',
        'line_pattern {"name": "Fence", "segments": [{"dash": 4}, {"space": 1}, "dot", {"space": 1}]}',
        'line_style {"name": "Fence Line", "pen": 3, "color": [200, 0, 0], "pattern": "Fence"}',
        'detail_line {"points": [[0, -1000], [1000, -1000]], "style": "Fence Line"}']


def test_insert_from_file(run, workdir, golden):
    """CATCHES: a rewrite whose Insert from File brings in other elements, renumbers ids or GUIDs differently, misses
    what they point at (types, families, materials, line styles and patterns, levels by name), names clashes otherwise
    (` 2`), or replies with another `ids` map, `copies`, `library` or `left_out`."""
    made(run, "arch.bimcraft", *ARCH)
    made(run, "mine.bimcraft", 'wall {"points": [[0, 0], [3000, 0]]}', 'door {"at": [1500, 0], "mark": "D1"}',
         'material {"name": "Oak", "color": "#000000"}', 'level {"elevation": 9000, "name": "Attic"}')
    steps = [
        # Into an empty project: everything, each keeping its id.
        [ 'insert {"path": "arch.bimcraft"}', 'elements {}', 'inspect'],
        # Into one that has ids, a mark and a material of its own: new ids, its own Oak kept, the door's mark taken.
        ["mine.bimcraft", 'insert {"path": "arch.bimcraft", "ids": [100006, 100008, 100009]}', 'elements {}', 'material {"name": "Oak"}',
         'undo', 'elements {"category": "wall"}'],
        # A detail line brings its line style and pattern; a wall on Roof brings that level.
        ["mine.bimcraft", 'insert {"path": "arch.bimcraft", "ids": [100012, 100011]}', 'line_style {"name": "Fence Line"}',
         'elements {"category": "level"}'],
        # The same file into itself: a copy of the whole, with GUIDs of its own.
        ["arch.bimcraft", 'insert {"path": "arch.bimcraft", "ids": [100002, 100003]}', 'elements {"category": "wall"}'],
        ['insert {}'],
        ['insert {"path": "missing.bimcraft"}'],
        ['insert {"path": "arch.bimcraft", "ids": [999999]}'],
        ['insert {"path": "arch.bimcraft", "ids": "all"}'],
        ['insert {"path": "notes.txt"}'],
    ]
    (workdir / "notes.txt").write_text("not a project")
    golden.check(runs(run, steps), "insert.txt")


def test_insert_from_an_ifc_file_the_program_wrote(run, workdir, golden):
    """CATCHES: a rewrite that can't bring elements in from an IFC file it exported, or brings them with other ids,
    types, levels or a different reply."""
    r = run(["run", "--cmd", BOX, "--cmd", 'door {"at": [2000, 0]}', "--cmd", 'room {"point": [4000, 3000], "name": "Hall"}',
             "--save", "box.ifc"])
    assert r.returncode == 0, r.stderr.decode()
    steps = [['insert {"path": "box.ifc"}', 'elements {}'],
             ['wall {"points": [[0, -5000], [3000, -5000]]}', 'insert {"path": "box.ifc", "ids": [100002]}', 'elements {"category": "wall"}']]
    golden.check(runs(run, steps), "insert_ifc.txt")


def test_link_model_and_reload(run, workdir, golden):
    """CATCHES: a rewrite whose links count, name, place or turn the linked project differently, let it be selected,
    scheduled or exported, keep more than the path in the project file, read a relative path from elsewhere than the
    project's folder, or reload and report failures differently."""
    os.mkdir(workdir / "site")
    made(run, "site/arch.bimcraft", BOX, 'door {"at": [2000, 0]}', 'level {"name": "Roof deck", "elevation": 9100}',
         'wall {"points": [[0, 0], [4000, 0]], "level": "Roof deck"}')
    made(run, "site/project.bimcraft")
    (workdir / "junk.bimcraft").write_text("not a project")
    steps = [
        ["site/project.bimcraft", 'LK {"path": "arch.bimcraft", "name": "Architecture", "at": [1000, 2000], "angle": 90}',
         'elements {}', 'inspect', 'schedule {"category": "walls"}', 'reload {}', 'save {}'],
        ["site/project.bimcraft", 'elements {"category": "link"}'],
        ["site/project.bimcraft", 'link {"path": "arch.bimcraft"}', 'move {"ids": [100002], "by": [500, 700]}',
         'modify {"id": 100002, "angle": 180}', 'elements {"category": "link"}', 'delete {"ids": [100002]}', 'undo',
         'reload {"id": 100002}', 'reload {"id": 100000}'],
        ['link {}'],
        ['link {"path": "nowhere.bimcraft"}'],
        ['link {"path": "junk.bimcraft"}'],
        ['link {"path": "site/arch.bimcraft", "name": "A"}', 'link {"path": "site/arch.bimcraft", "name": "A"}'],
        ['link {"path": "site/arch.bimcraft", "angle": 1e9}'],
        ['link {"path": "site/arch.bimcraft", "at": [1e12, 0]}'],
    ]
    golden.check(runs(run, steps), "link.txt")
    golden.check(project_part(workdir / "site" / "project.bimcraft"), "linked_project_elements.json")
    # The plan draws the link, halftone.
    r = run(["run", "site/project.bimcraft", "--save", "plan.svg"])
    golden.check_run(r, "link_plan.txt")
    golden.check((workdir / "plan.svg").read_text(), "link_plan.svg")
    # The linked file changes, then goes: reload reads it again, then says it failed; opening says so too.
    r = run(["run", "site/arch.bimcraft", "--cmd", 'wall {"points": [[0, 0], [0, -3000]]}', "--save", "site/arch.bimcraft"])
    assert r.returncode == 0, r.stderr.decode()
    steps = [["site/project.bimcraft", 'reload {}']]
    out = runs(run, steps)
    os.remove(workdir / "site" / "arch.bimcraft")
    out += runs(run, [["site/project.bimcraft", 'reload {}', 'elements {"category": "link"}']])
    golden.check(out, "link_reload.txt")


def test_a_link_to_an_ifc_file(run, workdir, golden):
    """CATCHES: a rewrite that can't link an IFC file the program wrote, or counts and draws its elements differently."""
    r = run(["run", "--cmd", BOX, "--save", "box.ifc"])
    assert r.returncode == 0, r.stderr.decode()
    r = run(["run", "--cmd", 'link {"path": "box.ifc"}', "--cmd", 'elements {}', "--save", "plan.svg"])
    golden.check_run(r, "link_ifc.txt")
    golden.check((workdir / "plan.svg").read_text(), "link_ifc_plan.svg")


def test_autosave_and_recover(run, workdir, golden):
    """CATCHES: a rewrite whose autosave writes something other than the project, changes the project's path or undo
    history, may write over the project's own file, or whose recover saves to the wrong place afterwards, reads links
    from the backup's folder, or words its refusals differently."""
    os.mkdir(workdir / "proj")
    os.mkdir(workdir / "backups")
    made(run, "proj/arch.bimcraft", 'wall {"points": [[0, 0], [8000, 0]]}')
    steps = [
        ['wall {"points": [[0, 0], [5000, 0]]}', 'save {"path": "proj/p.bimcraft"}', 'link {"path": "arch.bimcraft"}',
         'autosave {"path": "backups/snap.bimcraft"}', 'inspect', 'undo', 'autosave {"path": "proj/p.bimcraft"}'],
        ['recover {"path": "backups/snap.bimcraft", "project": "proj/p.bimcraft"}', 'elements {}', 'save {}'],
        ['recover {"path": "backups/snap.bimcraft"}', 'save {}'],
        ['autosave {}'],
        ['recover {}'],
        ['recover {"path": "backups/missing.bimcraft"}'],
        ['recover {"path": "backups/snap.bimcraft", "project": 5}'],
        ['wall {"points": [[0, 0], [5000, 0]]}', 'link {"path": "proj/arch.bimcraft"}', 'autosave {"path": "backups/twin.bimcraft"}',
         'save {"path": "proj/twin.bimcraft"}'],
    ]
    golden.check(runs(run, steps), "autosave_recover.txt")
    # The snapshot is the project as Save writes it, byte for byte.
    assert (workdir / "backups" / "twin.bimcraft").read_text() == (workdir / "proj" / "twin.bimcraft").read_text()
    golden.check(project_part(workdir / "backups" / "snap.bimcraft"), "snap_elements.json")


def test_new_replaces_the_project(run, golden):
    """CATCHES: a rewrite whose `new` keeps anything of the project it replaces (elements, undo steps), names the
    project or its levels otherwise in a language, or takes other languages."""
    steps = [
        [BOX, 'new {}', 'inspect', 'undo'],
        ['new {"name": "Casa", "language": "pt"}', 'elements {"category": "level"}'],
        ['new {"name": "Huis", "language": "nl"}', 'new {"language": "sv"}', 'elements {"category": "level"}'],
        ['new {"name": 5}'],
        ['new {"language": "tlh"}'],
    ]
    golden.check(runs(run, steps), "new.txt")


def test_insert_names_clashes_apart_and_leaves_out_unknown_phases(run, workdir, golden):
    """CATCHES: a rewrite whose Insert from File names a level, a view, a grid or a sheet number this project has
    otherwise than with ` 2`, ` 3`…, keeps a phase or a design option this project hasn't (instead of leaving it out
    and saying so in `left_out`), or doesn't bring what a region type, a material's picture or a schedule needs."""
    (workdir / "grass.png").write_bytes((resources_for(__file__) / "grass.png").read_bytes())
    made(run, "other.bimcraft", 'phase {"name": "Later"}', 'option {"set": "Roof", "options": ["Flat", "Pitched"]}',
         BOX, 'modify {"id": 100002, "params": {"Phase Created": "Later"}}', 'modify {"id": 100003, "params": {"Design Option": "Roof: Flat"}}',
         'grid {"start": [-1000, -1000], "end": [-1000, 7000]}', 'section {"start": [-1000, 3000], "end": [9000, 3000]}',
         'sheet {}', 'schedule {"name": "Walls", "category": "walls"}', 'camera {"eye": [-5000, -5000, 1600], "target": [4000, 3000, 1000]}',
         'fill_pattern {"name": "Dots", "lines": [{"angle": 45, "spacing": 2, "dashes": [0, -2]}]}',
         'filled_region_type {"name": "Dotted", "foreground": "Dots"}',
         'filled_region {"type": "Dotted", "sketch": [[[0, 0], [400, 0]], [[400, 0], [400, 400]], [[400, 400], [0, 400]], [[0, 400], [0, 0]]]}',
         'material {"name": "Lawn", "texture": {"kind": "image", "path": "grass.png"}}',
         'type {"category": "wall", "name": "Green", "layers": [{"material": "Lawn", "thickness": 150}]}', 'modify {"id": 100004, "type": "Green"}')
    made(run, "mine.bimcraft", 'grid {"start": [0, 0], "end": [0, 5000]}', 'section {"start": [0, -1000], "end": [5000, -1000]}',
         'sheet {}', 'schedule {"name": "Walls", "category": "walls"}', 'camera {"eye": [-5000, 0, 1600], "target": [0, 0, 1000]}',
         'level {"elevation": 3000, "name": "Level 2b"}')
    steps = [["mine.bimcraft", 'insert {"path": "other.bimcraft"}', 'elements {}', 'library {"kind": "picture"}',
              'filled_region_type {"name": "Dotted"}', 'inspect']]
    golden.check(runs(run, steps), "insert_clashes.txt")
