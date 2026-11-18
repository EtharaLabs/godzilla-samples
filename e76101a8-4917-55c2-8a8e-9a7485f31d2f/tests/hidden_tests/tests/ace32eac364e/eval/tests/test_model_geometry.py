"""The geometry the building elements are built with, as IFC writes it: walls' prisms (joined, curved, layered, cut by
openings, under attached roofs and shaped floors), slabs and roofs (shaped tops, variable layers, courtyards, extrusions,
dormers, shafts), masses (swept or lofted into a face set), stairs, ramps and railings, and rooms as spaces; and the
reference crosses a plan draws for rooms. Each model is built, its GUIDs fixed, then converted, so the file is stable."""

from conftest import glb_summary, make_project, normalize

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}'


def _ifc(run, workdir, lines):
    """LINES run as a script into a project whose GUIDs are then fixed, converted to IFC: the file's text, normalised."""
    (workdir / "s.txt").write_text("\n".join(lines) + "\n")
    make_project(run, workdir, "p.bimcraft", ["--script", "s.txt"])
    r = run(["convert", "p.bimcraft", "out.ifc"])
    assert r.returncode == 0, r.stderr.decode()
    return normalize((workdir / "out.ifc").read_text())


def test_walls_in_ifc(run, workdir, golden):
    """CATCHES: a rewrite whose walls' solids in IFC differ from the reference's: mitred caps where they join, a curved
    wall's arc, a compound wall's layers on its location line, the voids of its doors and windows, and the tops of walls
    attached to a gable roof following its underside."""
    text = _ifc(run, workdir, [
        'wall {"points": [[0, 0], [0, 6000], [8000, 6000], [8000, 0]], "closed": true, "type": "Exterior - 300mm", '
        '"location": "exterior-finish"}',
        'wall {"points": [[4000, 0], [4000, 6000]], "type": "Interior - 100mm"}',
        'wall {"points": [[8000, 0], [8000, 6000]], "arc": -90, "level": "Level 2", "height": 2500}',
        'door {"at": [2000, 0]}',
        'window {"at": [0, 3000]}',
        'door {"at": [6000, 6000], "family": "Single Door"}',
        'roof {"gable": true, "boundary": [[-500, -500], [8500, -500], [8500, 6500], [-500, 6500]]}',
        'modify {"ids": [100002, 100003, 100004, 100005, 100006], "attach_top": 100011}',
    ])
    golden.check(text, "walls.ifc")


TERRACE = ('type {"category": "floor", "name": "Terrace", "layers": [{"function": "finish", "material": "Ceramic tile", '
           '"thickness": 10}, {"function": "substrate", "thickness": 60, "variable": true}, {"function": "membrane", '
           '"thickness": 5}, {"function": "structure", "material": "Concrete", "thickness": 200}]}')


def test_shaped_floors_and_the_walls_under_them_in_ifc(run, workdir, golden):
    """CATCHES: a rewrite whose shaped floor over a variable layer isn't one closed solid of its planes over a level
    underside, whose plain shaped floor's underside doesn't follow its top, or whose walls attached under them don't stop
    at the underside (level under the variable layer, folding under the plain one)."""
    text = _ifc(run, workdir, [
        TERRACE,
        'floor {"level": "Level 2", "type": "Terrace", "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}',
        'edit_shape {"id": 100002, "points": [{"at": [4000, 3000], "z": -30}]}',
        'wall {"points": [[4000, 0], [4000, 6000]], "type": "Interior - 100mm", "attach_top": 100002}',
        'floor {"level": "Level 2", "boundary": [[10000, 0], [18000, 0], [18000, 6000], [10000, 6000]]}',
        'falls {"id": 100004, "drains": [[12000, 3000], [16000, 3000]], "fall": 1.5}',
        'wall {"points": [[10000, 3000], [18000, 3000]], "attach_top": 100004}',
        'wall {"points": [[10000, 1000], [18000, 1000]], "attach_base": 100004, "level": "Level 2", "height": 1000}',
    ])
    golden.check(text, "shaped_floors.ifc")


def test_slabs_roofs_and_shafts_in_ifc(run, workdir, golden):
    """CATCHES: a rewrite whose sloped floor, floor with an opening, ceiling, hipped roof round a courtyard, extrusion
    roof with an opening, flat roof with falls or dormer differ in IFC from the reference's, or whose shaft doesn't void
    each slab it passes through."""
    text = _ifc(run, workdir, [
        BOX,
        'floor {}',
        'floor {"level": "Level 2", "boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], '
        '"openings": [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]]}',
        'floor {"boundary": [[10000, 0], [16000, 0], [16000, 1500], [10000, 1500]], "offset": 100, "slope": 5, '
        '"arrow": [[10000, 750], [16000, 750]]}',
        'ceiling {"point": [4000, 3000], "type": "Tile 600 x 600"}',
        'shaft {"boundary": [[3000, 2000], [4000, 2000], [4000, 4000], [3000, 4000]], "height": 8000}',
        'roof {"level": "Level 2", "boundary": [[20000, 0], [36000, 0], [36000, 16000], [20000, 16000]], '
        '"courtyards": [[[26000, 6000], [30000, 6000], [30000, 10000], [26000, 10000]]], "slopes": [30, 45, 30, 45, 0, 0, 0, 0]}',
        'roof {"level": "Level 2", "extrusion": {"line": [[40000, 0], [48000, 0]], "profile": [[-500, 0], [3000, 2000], [8500, 0]], '
        '"from": -600, "to": 6600}, "openings": [[[43000, 2000], [44000, 2000], [44000, 3000], [43000, 3000]]]}',
        'roof {"level": "Level 2", "slope": 0, "boundary": [[50000, 0], [58000, 0], [58000, 6000], [50000, 6000]]}',
        'falls {"id": 100013, "drains": [[54000, 3000]], "fall": 1}',
        'roof {}',
        'dormer {"host": 100014, "at": [4000, 100], "width": 1600, "height": 800, "window": "Fixed 600 x 900"}',
    ])
    golden.check(text, "slabs_roofs.ifc")


def test_masses_stairs_ramps_railings_and_rooms_in_ifc(run, workdir, golden):
    """CATCHES: a rewrite whose mass isn't swept up (or, lofted, a closed triangulated face set with its pairing), whose
    stair or ramp runs and landings, or railings' rails and balusters, lie elsewhere in IFC, or whose rooms aren't spaces
    swept their height, with the separation lines as virtual elements."""
    text = _ifc(run, workdir, [
        'mass {"boundary": [[20000, 0], [30000, 0], [30000, 6000], [20000, 6000]], "height": 4000}',
        'mass {"boundary": [[40000, 0], [50000, 0], [50000, 6000], [40000, 6000]], "height": 6000, '
        '"top": [[42000, 2000], [48000, 2000], [48000, 4000], [42000, 4000]]}',
        'type {"category": "railing", "name": "Railing - 1000mm", "height": 1000, "spacing": 1500}',
        'stair {"start": [1000, 1000], "angle": 90, "landings": [{"at": 8, "turn": -90}], "railings": true}',
        'ramp {"start": [6000, -6000], "height": 600, "landings": [{"at": 300, "turn": 180}], "railings": true}',
        'type {"category": "railing", "name": "Glass - 1100mm", "height": 1100, "spacing": 0}',
        'railing {"path": [[0, 9000], [4000, 9000], [4000, 11000]], "level": "Level 2", "type": "Glass - 1100mm"}',
        'wall {"points": [[10000, 0], [16000, 0], [16000, 4000], [10000, 4000]], "closed": true}',
        'room_separator {"points": [[13000, 0], [13000, 4000]]}',
        'room {"point": [11000, 2000], "name": "West"}',
        'room {"point": [15000, 2000], "name": "East", "top_level": "Level 2", "limit_offset": 500}',
    ])
    golden.check(text, "masses_stairs_rooms.ifc")


def test_a_plan_shows_room_references_and_separators_when_asked(run, workdir, golden):
    """CATCHES: a rewrite whose plan draws no room reference crosses when the `roomreference` subcategory is shown, draws
    them out to other edges than the room's boundary along its diagonals, or labels rooms NOT ENCLOSED or REDUNDANT
    otherwise."""
    r = run(["run", "--cmd", BOX, "--cmd", 'wall {"points": [[5000, 0], [5000, 6000]]}',
             "--cmd", 'room_separator {"points": [[0, 3000], [5000, 3000]]}',
             "--cmd", 'room {"point": [2000, 1500], "name": "Study"}', "--cmd", 'room {"point": [2500, 4500], "name": "Den"}',
             "--cmd", 'room {"point": [6500, 3000], "name": "Hall"}', "--cmd", 'room {"point": [7000, 1000], "name": "Twin"}',
             "--cmd", 'room {"point": [12000, 3000], "name": "Out"}',
             "--cmd", 'graphics {"view": "Level 1", "show": ["roomreference"]}', "--save", "plan.svg"])
    golden.check_run(r, "references.txt")
    golden.check((workdir / "plan.svg").read_text(), "references.svg")


def test_walls_with_openings_in_the_3d_scene(run, workdir, golden):
    """CATCHES: a rewrite whose 3D scene (as glTF) cuts other holes in walls for their doors and windows, or builds the
    walls, floor and flat roof of a box with other meshes than the reference's."""
    (workdir / "s.txt").write_text("\n".join([
        BOX,
        'door {"at": [2000, 0]}',
        'window {"at": [8000, 3000]}',
        'window {"at": [4000, 6000], "type": "Fixed 600 x 900"}',
        'floor {}',
        'roof {"slope": 0, "overhang": 0}',
    ]) + "\n")
    make_project(run, workdir, "p.bimcraft", ["--script", "s.txt"])
    r = run(["convert", "p.bimcraft", "scene.glb"])
    golden.check_run(r, "scene.txt")
    golden.check(glb_summary((workdir / "scene.glb").read_bytes()), "scene.glb.txt")
