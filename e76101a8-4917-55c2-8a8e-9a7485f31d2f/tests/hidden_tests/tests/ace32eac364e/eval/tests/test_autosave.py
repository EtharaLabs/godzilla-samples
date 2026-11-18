"""`autosave` and `recover`: a recovery snapshot written without touching the project's path or its undo history, and
opened again as unsaved work whose Save goes to the project it was a copy of (or asks for a path)."""

import json
import re

from conftest import normalize

WALL = 'wall {"points": [[0, 0], [4000, 0]]}'
DOOR = 'door {"at": [2000, 0]}'


def result(r):
    return f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{normalize(r.stderr.decode())}"


def test_a_snapshot_is_what_save_would_write_and_leaves_the_project_alone(run, workdir, golden):
    """CATCHES: a rewrite whose autosave writes something other than the project file Save would write, changes the
    session's project path (so a later Save goes to the snapshot), adds a step to the undo history, or touches the saved
    project."""
    r = run(["run", "--cmd", WALL, "--save", "house.bimcraft", "--cmd", DOOR,
             "--cmd", 'autosave {"path": "house.bimcraft.autosave.bimcraft"}',
             "--cmd", "undo", "--cmd", "save {}", "--cmd", "redo", "--save", "same.bimcraft"])
    golden.check(result(r), "snapshot.txt")
    # Redone, the model is the one the snapshot was taken of: Save As writes the same file.
    snapshot = (workdir / "house.bimcraft.autosave.bimcraft").read_text()
    assert snapshot == (workdir / "same.bimcraft").read_text()
    # The project was saved again after the undo: without the door. The snapshot keeps it.
    for name, golden_name in [("house.bimcraft", "project"), ("house.bimcraft.autosave.bimcraft", "snapshot")]:
        r = run(["run", name, "--cmd", 'elements {"category": "door"}'])
        golden.check(result(r), f"snapshot_opened_{golden_name}.txt")


def test_an_untitled_projects_snapshot_leaves_it_untitled(run, workdir, golden):
    """CATCHES: a rewrite whose autosave of an untitled project makes the snapshot its file, so that Save without a path
    writes there instead of asking for one; undo still takes back the last command, not the snapshot."""
    r = run(["run", "--cmd", WALL, "--cmd", 'autosave {"path": "untitled.autosave.bimcraft"}', "--cmd", "undo",
             "--cmd", "save {}"])
    golden.check(result(r), "untitled.txt")
    r = run(["run", "untitled.autosave.bimcraft", "--cmd", 'elements {"category": "wall"}'])
    golden.check(result(r), "untitled_opened.txt")


def test_a_later_snapshot_replaces_the_earlier_one(run, workdir, golden):
    """CATCHES: a rewrite that appends to, or refuses to replace, an existing recovery file instead of replacing it
    whole with the newer snapshot."""
    (workdir / "copy.bimcraft").write_text("an older snapshot, much longer than nothing at all " * 1000)
    r = run(["run", "--cmd", WALL, "--cmd", 'autosave {"path": "copy.bimcraft"}', "--cmd", DOOR,
             "--cmd", 'autosave {"path": "copy.bimcraft"}', "--save", "same.bimcraft"])
    assert r.returncode == 0, r.stderr
    assert (workdir / "copy.bimcraft").read_text() == (workdir / "same.bimcraft").read_text()
    golden.check(result(run(["run", "copy.bimcraft", "--cmd", 'elements {"category": "door"}'])), "replaced.txt")


def test_autosave_refuses_what_it_cant_do(run, workdir, golden):
    """CATCHES: a rewrite whose autosave overwrites the saved project itself, writes with no path or a path that isn't
    text, or reports a folder that doesn't exist with other words."""
    assert run(["run", "--cmd", WALL, "--save", "house.bimcraft"]).returncode == 0
    out = []
    for args in [["house.bimcraft", "--cmd", 'autosave {"path": "house.bimcraft"}'],
                 ["--cmd", "autosave {}"], ["--cmd", 'autosave {"path": 5}'], ["--cmd", 'autosave {"path": null}'],
                 ["--cmd", 'autosave {"path": "nodir/x.autosave.bimcraft"}']]:
        r = run(["run", *args])
        # The temporary file a snapshot is first written to has a random name and an absolute path.
        err = re.sub(r' at path "[^"]*"', ' at path "<TMP>"', r.stderr.decode())
        out.append(f"{' '.join(args)}\n-> exit {r.returncode}: {r.stdout.decode()}{err}")
    golden.check("".join(out), "autosave_refused.txt")


def test_recover_opens_the_snapshot_and_save_goes_to_the_project(run, workdir, golden):
    """CATCHES: a rewrite whose recover doesn't open the snapshot's model, keeps undo history from before, makes the
    snapshot the file a later Save writes to (instead of `project`), or removes the snapshot."""
    assert run(["run", "--cmd", WALL, "--save", "house.bimcraft", "--cmd", DOOR,
                "--cmd", 'autosave {"path": "house.bimcraft.autosave.bimcraft"}']).returncode == 0
    r = run(["run", "--cmd", 'recover {"path": "house.bimcraft.autosave.bimcraft", "project": "house.bimcraft"}',
             "--cmd", 'elements {"category": "door"}', "--cmd", "save {}", "--cmd", "undo"])
    golden.check(result(r), "recover_with_project.txt")
    golden.check(result(run(["run", "house.bimcraft", "--cmd", 'elements {"category": "door"}'])), "recovered_project.txt")
    assert (workdir / "house.bimcraft").read_text() == (workdir / "house.bimcraft.autosave.bimcraft").read_text()


def test_recover_without_a_project_asks_for_a_path_on_save(run, workdir, golden):
    """CATCHES: a rewrite whose recover of an untitled snapshot lets Save write without a path (to the snapshot, or
    anywhere), instead of asking for one."""
    assert run(["run", "--cmd", WALL, "--cmd", 'autosave {"path": "u.autosave.bimcraft"}']).returncode == 0
    r = run(["run", "--cmd", 'recover {"path": "u.autosave.bimcraft"}', "--cmd", 'elements {"category": "wall"}',
             "--cmd", "save {}"])
    golden.check(result(r), "recover_untitled.txt")


def test_recover_refuses_a_snapshot_it_cant_open(run, workdir, golden):
    """CATCHES: a rewrite whose recover opens a damaged or newer snapshot, or a missing one, or takes a `project` that
    isn't text, instead of refusing it with the reference's words (Open's)."""
    (workdir / "truncated.bimcraft").write_text('{"format": 17, "name": "Pro')
    (workdir / "newer.bimcraft").write_text('{"format": 99}')
    (workdir / "empty.bimcraft").write_text("")
    out = []
    for params in [{"path": "truncated.bimcraft", "project": "house.bimcraft"}, {"path": "newer.bimcraft"},
                   {"path": "empty.bimcraft"}, {"path": "missing.bimcraft"}, {}, {"path": "truncated.bimcraft", "project": 5},
                   {"path": 7}]:
        r = run(["run", "--cmd", WALL, "--cmd", "recover " + json.dumps(params)])
        out.append(f"{json.dumps(params)} -> exit {r.returncode}: {r.stdout.decode()}{r.stderr.decode()}")
    golden.check(normalize("".join(out)), "recover_refused.txt")


def _plan(lines):
    """A DXF in mm of the given number of short lines."""
    body = "".join(f"0\nLINE\n8\nA\n10\n{i * 100}\n20\n0\n11\n{i * 100}\n21\n500\n" for i in range(lines))
    return ("0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n" + body
            + "0\nENDSEC\n0\nEOF\n")


def test_recover_reads_linked_drawings_beside_the_project_not_the_snapshot(run, workdir, golden):
    """CATCHES: a rewrite whose recover reads a snapshot's linked CAD drawings beside the snapshot (or the working
    folder) instead of beside the project it recovers, or that loses a scan or a drawing the snapshot holds."""
    for folder, lines in [("proj", 3), ("backups", 5), (".", 7)]:
        (workdir / folder).mkdir(exist_ok=True)
        (workdir / folder / "plan.dxf").write_text(_plan(lines))
    (workdir / "scan.xyz").write_text("0 0 0 255 0 0\n1 1 1 0 0 255\n")
    r = run(["run", "--cmd", 'import_cad {"path": "plan.dxf", "link": true, "position": "origin"}',
             "--cmd", 'point_cloud {"path": "scan.xyz"}', "--save", "proj/p.bimcraft",
             "--cmd", 'autosave {"path": "backups/p.bimcraft.autosave.bimcraft"}'])
    golden.check(result(r), "linked_snapshot.txt")
    for name, params in [("with_project", {"path": "backups/p.bimcraft.autosave.bimcraft", "project": "proj/p.bimcraft"}),
                         ("untitled", {"path": "backups/p.bimcraft.autosave.bimcraft"})]:
        r = run(["run", "--cmd", "recover " + json.dumps(params), "--cmd", 'elements {"category": "cadimport"}',
                 "--cmd", 'elements {"category": "pointcloud"}'])
        golden.check(result(r), f"linked_recover_{name}.txt")
    (workdir / "proj" / "plan.dxf").unlink()
    r = run(["run", "--cmd", 'recover {"path": "backups/p.bimcraft.autosave.bimcraft", "project": "proj/p.bimcraft"}'])
    golden.check(result(r), "linked_recover_missing.txt")
