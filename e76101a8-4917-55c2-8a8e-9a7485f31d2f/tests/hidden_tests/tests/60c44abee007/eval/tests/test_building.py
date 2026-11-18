"""The building model itself: levels, grids, walls and their joins, doors and windows in them, rooms and their boundaries,
floors, ceilings, shafts, roofs and dormers, sketches and their problems, and the rules every model is checked against
after each command (what a refused command says, and that it changes nothing)."""

import copy
import json

import pytest

# A 6 m x 4 m box of compound walls with a partition: the house most tests build on.
BOX = 'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true, "type": "Exterior - 300mm"}'
PARTITION = 'wall {"points": [[3000,0],[3000,4000]], "type": "Interior - 100mm"}'


def elements(category: str) -> str:
    return 'elements {"category": "%s"}' % category


# ---------------------------------------------------------------------------------------------------------------------
# Levels and grids
# ---------------------------------------------------------------------------------------------------------------------


def test_levels_named_in_turn_sorted_by_elevation(sc):
    """CATCHES: new levels not named on from the last (Level 3, Level 4), negative elevations refused, or inspect not
    listing levels by elevation."""
    sc.cmds('level {"elevation": 6000}', 'level {"elevation": -1200, "name": "Basement"}', 'level {"elevation": 9000}',
            'level {"elevation": 4500, "name": "Mezzanine", "extent": [[-1000,-1000],[9000,7000]]}',
            elements("level"))
    assert sc.transcript() == sc.golden()


def test_level_errors(sc):
    """CATCHES: a duplicate level name, an elevation that isn't a number, or an extent given north-east first being accepted."""
    sc.cmds('level {"elevation": 3000, "name": "Level 1"}')
    sc.cmds('level {"elevation": "high"}')
    sc.cmds('level {"elevation": 1e12}')
    sc.cmds('level {"elevation": 5000, "extent": [[9000,7000],[0,0]]}')
    sc.cmds("level {}")
    assert sc.transcript() == sc.golden()


def test_grids_numbered_and_lettered_in_turn(sc):
    """CATCHES: grid names not following the last grid (1, 2, 3 after 1; B, C after A), or a duplicate grid name accepted."""
    sc.cmds('grid {"start": [0,-1000], "end": [0,5000]}', 'grid {"start": [3000,-1000], "end": [3000,5000]}',
            'grid {"start": [-1000,0], "end": [7000,0], "name": "A"}', 'grid {"start": [-1000,4000], "end": [7000,4000]}',
            'grid {"start": [6000,-1000], "end": [6000,5000]}', elements("grid"))
    sc.cmds('grid {"start": [0,0], "end": [0,5000], "name": "X"}', 'grid {"start": [1,0], "end": [1,5000], "name": "X"}')
    sc.cmds('grid {"start": [0,0], "end": [0,0]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Walls
# ---------------------------------------------------------------------------------------------------------------------


def test_closed_compound_box_and_partition(sc):
    """CATCHES: wrong wall ids, lengths, heights, thicknesses, type GUIDs or top levels for a closed loop of compound walls
    and a partition drawn into it."""
    sc.cmds(BOX, PARTITION, elements("wall"))
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize("location", ["centre", "core-centre", "exterior-finish", "interior-finish", "exterior-core", "interior-core"])
def test_wall_location_lines(sc, location):
    """CATCHES: a location line that puts a compound wall's faces in the wrong place: the plan's poché must sit where that
    line of the wall's layers (its centre, its core's centre, a finish face or a core face) runs along the points."""
    sc.cmds('wall {"points": [[0,0],[4000,0]], "type": "Exterior - 300mm", "location": "%s"}' % location,
            elements("wall"), 'render {"path": "plan.svg"}')
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_wall_heights_by_top_level_offsets_and_height(sc):
    """CATCHES: a wall's height not following its top level and top offset, an unconnected height, or a base offset."""
    sc.cmds('level {"elevation": 7000}',
            'wall {"points": [[0,0],[4000,0]], "top_level": "Level 3", "top_offset": -500}',
            'wall {"points": [[0,1000],[4000,1000]], "height": 2400, "base_offset": 300}',
            'wall {"points": [[0,2000],[4000,2000]], "level": "Level 2"}',
            'wall {"points": [[0,3000],[4000,3000]], "top_level": "Level 2", "top_offset": 600}',
            elements("wall"))
    assert sc.transcript() == sc.golden()


def test_arc_walls(sc):
    """CATCHES: an arc wall's radius and length computed wrongly, its turn's sign ignored, or a closed loop of arcs
    not making one round room."""
    sc.cmds('wall {"points": [[0,0],[4000,0]], "arc": 90}', 'wall {"points": [[0,1000],[4000,1000]], "arc": -180}',
            'wall {"points": [[10000,0],[14000,0],[10000,0]], "arc": 180, "closed": true}',
            elements("wall"), 'render {"path": "plan.svg"}')
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_wall_errors(sc):
    """CATCHES: walls with too few points, a point repeated, a zero height, a top under the base, an unknown type, location
    or level, or an arc of 360 degrees being accepted."""
    for c in [
        'wall {"points": [[0,0]]}',
        'wall {"points": [[0,0],[0,0]]}',
        'wall {"points": [[0,0],[4000,0]], "height": 0}',
        'wall {"points": [[0,0],[4000,0]], "top_level": "Level 1", "top_offset": -100}',
        'wall {"points": [[0,0],[4000,0]], "type": "Glass Curtain"}',
        'wall {"points": [[0,0],[4000,0]], "location": "middle"}',
        'wall {"points": [[0,0],[4000,0]], "level": "Roof"}',
        'wall {"points": [[0,0],[4000,0]], "arc": 360}',
        'wall {"points": [[0,0],[1e10,0]]}',
    ]:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


def test_wall_end_moved_keeps_its_corner_joined(sc):
    """CATCHES: moving one end of a wall (`move` with `end`) without the wall joined at that corner following it, or the
    joined walls' lengths not changing with it."""
    sc.cmds(BOX, 'move {"ids": [100003], "by": [1000, 0]}', elements("wall"))
    sc.cmds(BOX, 'move {"ids": [100003], "by": [500, 0], "end": "start"}', elements("wall"))
    assert sc.transcript() == sc.golden()


def test_attach_wall_top_to_a_roof_and_base_to_a_floor(sc):
    """CATCHES: attach_top/attach_base not taking a roof or a floor, or accepting something else to attach to."""
    sc.cmds(BOX, "floor {}", 'roof {"slope": 30}',
            'wall {"points": [[1000,1000],[1000,3000]], "attach_top": 100007, "attach_base": 100006}',
            elements("wall"))
    sc.cmds(BOX, 'wall {"points": [[1000,1000],[1000,3000]], "attach_top": 100002}')
    assert sc.transcript() == sc.golden()


def test_room_bounding_off_lets_a_room_run_past_a_wall(sc):
    """CATCHES: a wall with room_bounding false still splitting the room, or `modify` not turning it back on."""
    sc.cmds(BOX, 'wall {"points": [[3000,0],[3000,4000]], "room_bounding": false}', 'room {"point": [1500, 2000]}',
            elements("room"), 'modify {"id": 100006, "room_bounding": true}', elements("room"))
    assert sc.transcript() == sc.golden()


def test_flip_walls_keeps_their_openings(sc):
    """CATCHES: `flip` not turning a compound wall's exterior side, moving its door, or flipping walls it wasn't given."""
    sc.cmds(BOX, 'door {"at": [1500, 0]}', 'flip {"ids": [100002]}', elements("wall"), elements("door"),
            'render {"path": "plan.svg"}')
    sc.file("plan.svg")
    assert sc.transcript() == sc.golden()


def test_split_wall_with_door_on_each_side(sc):
    """CATCHES: `split` not cutting a wall in two at a point, or a door on the second part not moving to the new wall."""
    sc.cmds('wall {"points": [[0,0],[8000,0]]}', 'door {"at": [1500, 0]}', 'window {"at": [6000, 0]}',
            'split {"id": 100002, "at": [4000, 0]}', elements("wall"), elements("door"), elements("window"))
    sc.cmds('wall {"points": [[0,0],[8000,0]]}', 'split {"id": 100002, "at": [100, 0]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Doors and windows
# ---------------------------------------------------------------------------------------------------------------------


def test_doors_and_windows_marks_offsets_and_types(sc):
    """CATCHES: door and window marks not counting up per category, offsets not measured from the wall's start, a type or a
    family's type not taken, or sills not defaulting to the type's."""
    sc.cmds(BOX, 'door {"at": [1500, 0]}', 'door {"wall": 100003, "offset": 2000, "type": "Single 900 x 2100"}',
            'door {"at": [4500, 4000], "family": "Double Door", "type": "1500 x 2100", "mark": "D-7"}',
            'window {"at": [4500, 0]}', 'window {"at": [0, 2000], "type": "Fixed 600 x 900"}',
            'window {"at": [6000, 1000], "family": "Casement Window", "sill": 1000}',
            'door {"at": [1500, 4000], "flip_facing": true, "flip_hand": true}',
            elements("door"), elements("window"))
    assert sc.transcript() == sc.golden()


def test_door_and_window_refusals(sc):
    """CATCHES: openings placed off any wall, overlapping one another, running past a wall's end or above its top, or of a
    family that isn't a door's, being accepted (or failing without saying why)."""
    for c in [
        'door {"at": [3000, 2000]}',
        'door {"wall": 100002, "offset": 1000}\ndoor {"wall": 100002, "offset": 1500}',
        'door {"at": [5900, 0]}',
        'window {"at": [3000, 0], "sill": 2500}',
        'door {"at": [3000, 0], "family": "Casement Window"}',
        'door {"at": [3000, 0], "type": "Revolving"}',
        'window {"at": [3000, 0], "family": "Sofa"}',
        'door {"wall": 100099}',
    ]:
        sc.cmds('wall {"points": [[0,0],[6000,0]]}', c)
    assert sc.transcript() == sc.golden()


def test_openings_follow_their_wall(sc):
    """CATCHES: doors and windows left behind when their wall moves or rotates, or not deleted with their wall."""
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', 'door {"at": [1500, 0]}', 'window {"at": [4000, 0]}',
            'move {"ids": [100002], "by": [0, 2000]}', elements("door"), elements("window"),
            'delete {"ids": [100002]}', "inspect {}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------------------------------------------------


def test_rooms_numbered_with_areas_perimeters_and_volumes(sc):
    """CATCHES: room areas, perimeters, volumes or numbers wrong for two rooms either side of a partition, or a room's
    name and number not taken."""
    sc.cmds(BOX, PARTITION, 'room {"point": [1500, 2000], "name": "Living"}', 'room {"point": [4500, 2000]}',
            'room {"point": [1500, 1000], "name": "Again"}', elements("room"))
    assert sc.transcript() == sc.golden()


def test_room_area_at_wall_centres_or_finish_faces(sc):
    """CATCHES: `room_area` not switching where rooms are measured (centre lines versus the walls' finish faces)."""
    sc.cmds(BOX, PARTITION, 'room {"point": [1500, 2000]}', 'room {"point": [4500, 2000]}', "room_area {}",
            'room_area {"at": "finish"}', elements("room"), 'room_area {"at": "centre"}', elements("room"),
            'room_area {"at": "middle"}')
    assert sc.transcript() == sc.golden()


def test_unenclosed_room_and_room_separators(sc):
    """CATCHES: a room in an open plan reported enclosed, or room separation lines not closing it into two rooms."""
    sc.cmds('wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]]}', 'room {"point": [3000, 2000]}', elements("room"),
            'room_separator {"points": [[0,0],[0,4000]]}', elements("room"),
            'room_separator {"points": [[3000,0],[3000,4000]]}', elements("room"), elements("roomseparator"))
    assert sc.transcript() == sc.golden()


def test_room_heights_and_limits(sc):
    """CATCHES: a room's unbounded height and volume not following its upper limit, limit offset and base offset, or a
    room whose top is under its bottom accepted."""
    sc.cmds(BOX, 'level {"elevation": 6000}',
            'room {"point": [3000, 2000], "top_level": "Level 3", "limit_offset": 500, "base_offset": 200}',
            elements("room"))
    sc.cmds(BOX, 'room {"point": [3000, 2000], "limit_offset": -4000}')
    assert sc.transcript() == sc.golden()


def test_frozen_room_keeps_its_boundary(sc):
    """CATCHES: a frozen room's area following a moved wall, or a thawed one not finding its boundary again."""
    sc.cmds(BOX, 'room {"point": [3000, 2000], "frozen": true}', 'move {"ids": [100003], "by": [2000, 0]}',
            elements("room"), 'modify {"id": 100006, "frozen": false}', elements("room"))
    assert sc.transcript() == sc.golden()


def test_room_errors(sc):
    """CATCHES: a room placed outside the walls, on a level that doesn't exist, or with a point that isn't a point."""
    sc.cmds('room {"point": [1500, 2000]}')
    sc.cmds(BOX, 'room {"point": [1500, 2000], "level": "Level 9"}')
    sc.cmds(BOX, 'room {"point": [1500]}')
    sc.cmds(BOX, 'room {"point": [1500, 2000], "number": ""}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Floors, ceilings and shafts
# ---------------------------------------------------------------------------------------------------------------------


def test_floor_from_walls_boundary_and_sketch_with_openings(sc):
    """CATCHES: a floor's outline from the walls, a given boundary, or a sketch with a hole solved wrongly, or openings
    not cut from its area."""
    sc.cmds(BOX, "floor {}",
            'floor {"boundary": [[0,0],[3000,0],[3000,2000],[0,2000]], "level": "Level 2", "offset": -100, "openings": [[[500,500],[1000,500],[1000,1000],[500,1000]]]}',
            'floor {"sketch": [[[10000,0],[14000,0]],[[14000,3000],[10000,3000]],[[14000,0],[14000,3000]],[[10000,3000],[10000,0]],[[11000,1000],[12000,1000]],[[12000,1000],[12000,2000]],[[12000,2000],[11000,2000]],[[11000,2000],[11000,1000]]]}',
            'floor {"boundary": [[20000,0],[24000,0],[24000,3000],[20000,3000]], "structural": true, "type": "Generic - 200mm"}',
            elements("floor"))
    assert sc.transcript() == sc.golden()


def test_sloped_floor_by_arrow(sc):
    """CATCHES: a sloped floor not rising from its arrow's tail toward its head, or a slope without an arrow accepted."""
    sc.cmds('floor {"boundary": [[0,0],[6000,0],[6000,4000],[0,4000]], "slope": 5, "arrow": [[0,2000],[6000,2000]]}',
            elements("floor"), 'section {"start": [-500, 2000], "end": [6500, 2000]}',
            'render {"view": "Section 1", "path": "s.png", "width": 400, "height": 300}')
    sc.file("s.png")
    sc.cmds('floor {"boundary": [[0,0],[6000,0],[6000,4000],[0,4000]], "slope": 5}')
    sc.cmds('floor {"boundary": [[0,0],[6000,0],[6000,4000],[0,4000]], "slope": 80, "arrow": [[0,2000],[6000,2000]]}')
    assert sc.transcript() == sc.golden()


def test_floor_errors(sc):
    """CATCHES: floors with no walls to follow, a bow-tie boundary, an opening outside it, too few points or an unknown
    type being accepted, or refused without saying what to redraw."""
    for c in [
        "floor {}",
        'floor {"boundary": [[0,0],[4000,4000],[4000,0],[0,4000]]}',
        'floor {"boundary": [[0,0],[4000,0],[4000,4000]], "openings": [[[5000,5000],[6000,5000],[6000,6000]]]}',
        'floor {"boundary": [[0,0],[4000,0]]}',
        'floor {"boundary": [[0,0],[4000,0],[4000,4000]], "type": "Marble"}',
        'floor {"boundary": [[0,0],[4000,0],[4000,4000]], "sketch": [[[0,0],[1,1]]]}',
        'floor {"sketch": [[[0,0],[4000,0]],[[4000,0],[4000,3000]]]}',
    ]:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


def test_ceilings_by_room_point_and_boundary(sc):
    """CATCHES: a ceiling at a room's point not running to the walls' faces, its default height or offset wrong, or a tile
    grid type not taken."""
    sc.cmds(BOX, PARTITION, 'ceiling {"point": [1500, 2000]}',
            'ceiling {"point": [4500, 2000], "type": "Tile 600 x 600", "offset": 2400}',
            'ceiling {"boundary": [[10000,0],[12000,0],[12000,2000],[10000,2000]], "openings": [[[10500,500],[11000,500],[11000,1000],[10500,1000]]]}',
            elements("ceiling"), 'render {"path": "rcp.svg", "ceiling": true}')
    sc.file("rcp.svg")
    sc.cmds('ceiling {"point": [1500, 2000]}')
    assert sc.transcript() == sc.golden()


def test_shaft_cuts_floors_on_its_way(sc):
    """CATCHES: a shaft not cutting the floors, ceilings and roofs between its base and top, or one with no height."""
    sc.cmds(BOX, "floor {}", 'floor {"level": "Level 2", "boundary": [[0,0],[6000,0],[6000,4000],[0,4000]]}',
            'shaft {"boundary": [[1000,1000],[2000,1000],[2000,2000],[1000,2000]], "top_level": "Level 2", "height": 500}',
            elements("shaft"), elements("floor"))
    sc.cmds(BOX, 'shaft {"boundary": [[1000,1000],[2000,1000],[2000,2000],[1000,2000]], "height": 0}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Roofs and dormers
# ---------------------------------------------------------------------------------------------------------------------


def test_flat_hip_and_gable_roofs(sc):
    """CATCHES: a roof by footprint whose ridge height, overhang, gables or per-edge slopes are worked out wrongly."""
    sc.cmds(BOX, 'roof {"slope": 30, "overhang": 500}', elements("roof"), 'delete {"ids": [100006]}',
            'roof {"slope": 35, "gables": [1, 3]}', elements("roof"), 'delete {"ids": [100007]}',
            'roof {"slope": 25, "slopes": [0, 45, 0, 0]}', elements("roof"), 'delete {"ids": [100008]}',
            'roof {"offset": 300}', elements("roof"))
    assert sc.transcript() == sc.golden()


def test_roof_with_courtyard_in_plan_and_3d(sc):
    """CATCHES: a courtyard not cut from a roof with eaves of its own, as the plan and the 3D view draw it."""
    sc.cmds('roof {"level": "Level 2", "boundary": [[0,0],[12000,0],[12000,10000],[0,10000]], "courtyards": [[[4000,3000],[8000,3000],[8000,7000],[4000,7000]]], "slope": 30}',
            elements("roof"), 'render {"view": "{3D}", "path": "r3d.png", "width": 320, "height": 200}',
            'render {"view": "Level 2", "path": "r.svg"}')
    sc.file("r3d.png")
    sc.file("r.svg")
    assert sc.transcript() == sc.golden()


def test_roof_errors(sc):
    """CATCHES: roofs with no walls below to follow, slopes past the limit, gables or slopes for edges it hasn't, or
    courtyards outside the boundary being accepted."""
    for c in [
        "roof {}",
        BOX + '\nroof {"slope": 80}',
        BOX + '\nroof {"slope": 30, "gables": [9]}',
        BOX + '\nroof {"slope": 30, "slopes": [10, 10]}',
        'roof {"boundary": [[0,0],[4000,0],[4000,4000],[0,4000]], "courtyards": [[[5000,5000],[6000,5000],[6000,6000]]]}',
        BOX + '\nroof {"level": "Level 1"}',
    ]:
        sc.cmds(c)
    assert sc.transcript() == sc.golden()


def test_dormer_on_a_hip_roof(sc):
    """CATCHES: a dormer not standing on its host roof's slope with its walls, roof and window, or one off the roof or
    running back over the ridge accepted."""
    sc.cmds('wall {"points": [[0,0],[10000,0],[10000,8000],[0,8000]], "closed": true}', 'roof {"slope": 35}',
            'dormer {"host": 100006, "at": [5000, 800], "width": 2400, "height": 1200, "window": "Fixed 600 x 900", "slope": 20}',
            elements("wall"), elements("window"), elements("roof"), 'render {"view": "{3D}", "path": "d.png", "width": 320, "height": 200}')
    sc.file("d.png")
    sc.cmds('wall {"points": [[0,0],[10000,0],[10000,8000],[0,8000]], "closed": true}', 'roof {"slope": 35}',
            'dormer {"host": 100006, "at": [50000, 1500]}')
    sc.cmds('wall {"points": [[0,0],[10000,0],[10000,8000],[0,8000]], "closed": true}', 'roof {"slope": 35}',
            'dormer {"host": 100006, "at": [5000, 1500], "width": 2000, "height": 1800}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Sketches
# ---------------------------------------------------------------------------------------------------------------------

SQUARE = [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]], [[4000, 3000], [0, 3000]], [[0, 3000], [0, 0]]]
SKETCHES = {
    "rectangle": SQUARE,
    "with_a_hole": SQUARE + [[[1000, 1000], [2000, 1000]], [[2000, 1000], [2000, 2000]], [[2000, 2000], [1000, 2000]],
                             [[1000, 2000], [1000, 1000]]],
    "lines_in_any_order_and_direction": [[[4000, 3000], [4000, 0]], [[0, 0], [0, 3000]], [[4000, 0], [0, 0]],
                                         [[0, 3000], [4000, 3000]]],
    "two_regions": SQUARE + [[[5000, 0], [6000, 0]], [[6000, 0], [6000, 1000]], [[6000, 1000], [5000, 0]]],
    "half_disc_arc": [[[0, 0], [4000, 0], [2000, 2000]], [[0, 0], [4000, 0]]],
    "crossing": [[[0, 0], [4000, 3000]], [[4000, 0], [0, 3000]], [[0, 0], [4000, 0]], [[0, 3000], [4000, 3000]]],
    "overlapping": [[[0, 0], [4000, 0]], [[2000, 0], [6000, 0]]],
    "open": [[[0, 0], [4000, 0]], [[4000, 0], [4000, 3000]]],
    "too_short": [[[0, 0], [0.001, 0]]],
    "empty": [],
    "back_and_forth": [[[0, 0], [4000, 0]], [[4000, 0], [0, 0]]],
    "out_of_range": [[[0, 0], [1e12, 0]]],
    "branching": SQUARE + [[[0, 0], [4000, 3000]]],
    "nested_holes": SQUARE + [[[500, 500], [3500, 500]], [[3500, 500], [3500, 2500]], [[3500, 2500], [500, 2500]],
                              [[500, 2500], [500, 500]], [[1000, 1000], [2000, 1000]], [[2000, 1000], [2000, 2000]],
                              [[2000, 2000], [1000, 2000]], [[1000, 2000], [1000, 1000]]],
    "bad_point": [[[0, 0], [4000]]],
    "self_crossing_triangle_pair": [[[0, 0], [4000, 0]], [[4000, 0], [0, 3000]], [[0, 3000], [4000, 3000]],
                                    [[4000, 3000], [0, 0]]],
}


@pytest.mark.parametrize("name", list(SKETCHES))
def test_sketch_solves_or_names_its_problems(sc, name):
    """CATCHES: a sketch solver that finds the wrong loops, holes or areas, or that misses or misnames a problem (lines
    crossing, overlapping, open ends, branches, lines too short or out of range, nothing drawn)."""
    sc.cmds("sketch " + json.dumps({"lines": SKETCHES[name]}))
    assert sc.transcript() == sc.golden()


def test_edit_boundary_lists_and_redraws_a_floor(sc):
    """CATCHES: edit_boundary not listing a floor's sketch lines with their ids, not keeping the id of a line sent back
    with it, or not changing the floor's area when its outline is redrawn."""
    sc.cmds('floor {"boundary": [[0,0],[4000,0],[4000,3000],[0,3000]]}', 'edit_boundary {"id": 100002}')
    sc.cmds('floor {"boundary": [[0,0],[4000,0],[4000,3000],[0,3000]]}',
            'edit_boundary {"id": 100002, "sketch": [[[0,0],[6000,0]],[[6000,0],[6000,3000]],[[6000,3000],[0,3000]],[[0,3000],[0,0]]]}',
            elements("floor"), 'edit_boundary {"id": 100002}',
            'edit_boundary {"id": 100002, "sketch": [[[0,0],[6000,0]],[[6000,0],[6000,3000]]]}')
    sc.cmds(BOX, 'edit_boundary {"id": 100002}')
    assert sc.transcript() == sc.golden()


def test_edit_boundary_of_a_shaped_floor_keeps_its_falls(sc):
    """CATCHES: a shaped floor's outline redrawn smaller without dropping the points outside it, cutting the split line
    that crosses the new edge, and adding a point where that line now ends at the height the top had there."""
    sc.cmds('floor {"boundary": [[0,0],[6000,0],[6000,4000],[0,4000]]}',
            'add_point {"id": 100002, "at": [3000, 2000], "z": -50}', 'add_point {"id": 100002, "at": [5000, 3000], "z": 40}',
            'add_split_line {"id": 100002, "a": [0, 2000], "b": [6000, 2000]}',
            'edit_boundary {"id": 100002, "sketch": [[[0,0],[4000,0]],[[4000,0],[4000,4000]],[[4000,4000],[0,4000]],[[0,4000],[0,0]]]}',
            'edit_shape {"id": 100002}', elements("floor"))
    assert sc.transcript() == sc.golden()


def test_edit_boundary_of_roofs_ceilings_and_shafts(sc):
    """CATCHES: a roof's sketch not giving each line the slope of its edge, a ceiling's or a shaft's outline not listed or
    redrawn, or an extrusion roof's boundary edited instead of refused."""
    sc.cmds('roof {"boundary": [[0,0],[6000,0],[6000,4000],[0,4000]], "slopes": [30, 0, 0, 45], "slope": 20}',
            'edit_boundary {"id": 100002}',
            'ceiling {"boundary": [[0,0],[3000,0],[3000,3000],[0,3000]], "openings": [[[1000,1000],[2000,1000],[2000,2000],[1000,2000]]]}',
            'edit_boundary {"id": 100003}',
            'edit_boundary {"id": 100003, "sketch": [[[0,0],[4000,0]],[[4000,0],[4000,3000]],[[4000,3000],[0,3000]],[[0,3000],[0,0]]]}',
            'shaft {"boundary": [[1000,1000],[2000,1000],[2000,2000],[1000,2000]]}', 'edit_boundary {"id": 100004}',
            'edit_boundary {"id": 100004, "sketch": [[[1000,1000],[3000,1000]],[[3000,1000],[3000,3000]],[[3000,3000],[1000,1000]]]}',
            elements("ceiling"), elements("shaft"))
    sc.cmds('roof {"extrusion": {"line": [[10000,0],[14000,0]], "profile": [[0,0],[2000,1500],[4000,0]], "to": 5000}}',
            'edit_boundary {"id": 100002}')
    sc.cmds("edit_boundary {}")
    sc.cmds('edit_boundary {"id": 123456}')
    assert sc.transcript() == sc.golden()


def test_dimensions_picked_by_points(sc):
    """CATCHES: a dimension's references given as points not picking the nearest wall centre line, round column edge,
    circle or curved wall, the wrong value for each kind (aligned, radial, diameter, arc length), or a point near nothing
    accepted."""
    sc.cmds('wall {"points": [[0,0],[6000,0]], "arc": 90}', 'column {"at": [8000, 2000], "type": "Round 300"}',
            'wall {"points": [[0,3000],[6000,3000]]}', 'wall {"points": [[0,5000],[6000,5000]]}',
            'detail_line {"centre": [12000, 2000], "radius": 800}',
            'dimension {"refs": [[3000, 3000], [3000, 5000]], "at": [3500, 4000]}',
            'dimension {"kind": "radial", "refs": [[8150, 2000]], "at": [9000, 2500]}',
            'dimension {"kind": "diameter", "refs": [[12800, 2000]], "at": [13500, 2500]}',
            'dimension {"kind": "arc_length", "refs": [[3000, -1242.6]], "at": [3000, -2500]}',
            'dimension {"kind": "radial", "refs": [[3000, -1242.6]], "at": [3000, -2000]}',
            elements("dimension"))
    for kind in ("radial", "arc_length", "aligned"):
        sc.cmds('dimension {"kind": "%s", "refs": [[100, 100]], "at": [0, 0]}' % kind)
    assert sc.transcript() == sc.golden()


def test_room_inside_a_wall_and_on_the_top_level(sc):
    """CATCHES: a room placed inside a wall's thickness (measured at the faces) accepted, or a room on the top level not
    getting the unbounded 2500 mm height it has with no level above."""
    sc.cmds(BOX, 'room_area {"at": "finish"}', 'room {"point": [3000, 50]}')
    sc.cmds('wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true, "level": "Level 2"}',
            'room {"point": [3000, 2000], "level": "Level 2"}', elements("room"))
    assert sc.transcript() == sc.golden()


def test_views_and_levels_have_no_place_in_plan_to_move(sc):
    """CATCHES: move, rotate or copy accepting a level, a sheet, a schedule, a plan view or the default 3D view, which have
    no place in plan, instead of saying what to do."""
    sc.cmds('move {"ids": [100000], "by": [10, 0]}')
    sc.cmds("sheet {}", 'rotate {"ids": [100002], "about": [0, 0], "angle": 90}')
    sc.cmds('schedule {"name": "Doors", "category": "doors"}', 'copy {"ids": [100002], "by": [10, 0]}')
    sc.cmds('duplicate_view {"view": "Level 1"}', 'move {"ids": [100002], "by": [10, 0]}')
    sc.cmds('visual_style {"style": "wireframe"}', 'move {"ids": [100002], "by": [10, 0]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# What `modify` may not do: the model's rules after each command
# ---------------------------------------------------------------------------------------------------------------------

BASE = [BOX, PARTITION, 'door {"at": [1500, 0]}', 'window {"at": [4500, 4000]}', 'room {"point": [1500, 2000]}',
        "floor {}", 'roof {"slope": 30}', 'grid {"start": [0,-1000], "end": [0,5000]}',
        'grid {"start": [6000,-1000], "end": [6000,5000]}', 'stair {"start": [4000, 500], "end": [4000, 3500]}']
# Ids in BASE: levels 100000-1, walls 100002-6, door 100007, window 100008, room 100009, floor 100010, roof 100011,
# grids 100012-13, stair 100014 (with its railings after it).
MODIFY_REFUSED = {
    "level_name_taken": '{"id": 100001, "name": "Level 1"}',
    "level_elevation_not_a_number": '{"id": 100001, "elevation": "high"}',
    "level_extent_backwards": '{"id": 100001, "extent": [[5000,5000],[0,0]]}',
    "level_view_range_upside_down": '{"id": 100000, "view_range": {"cut": 100, "bottom": 500}}',
    "grid_name_taken": '{"id": 100013, "name": "1"}',
    "grid_of_no_length": '{"id": 100012, "start": [0, 0], "end": [0, 0]}',
    "wall_arc_too_far": '{"id": 100002, "arc": 400}',
    "wall_top_under_base": '{"id": 100006, "top_level": "Level 1"}',
    "wall_attached_to_a_door": '{"id": 100006, "attach_top": 100007}',
    "wall_unknown_type": '{"id": 100006, "type": "Glass"}',
    "door_off_its_wall": '{"id": 100007, "offset": 99000}',
    "window_sill_too_high": '{"id": 100008, "sill": 2900}',
    "room_top_under_bottom": '{"id": 100009, "limit_offset": -3500}',
    "room_on_no_level": '{"id": 100009, "level": "Level 7"}',
    "floor_slope_without_arrow": '{"id": 100010, "slope": 5}',
    "floor_slope_too_steep": '{"id": 100010, "slope": 89}',
    "roof_slope_too_steep": '{"id": 100011, "slope": 85}',
    "roof_slopes_for_too_few_edges": '{"id": 100011, "slopes": [10, 20]}',
    "roof_edge_slope_too_steep": '{"id": 100011, "slopes": [10, 20, 30, 89]}',
    "stair_too_many_risers": '{"id": 100014, "riser": 1}',
    "unknown_field": '{"id": 100002, "colour": "red"}',
    "no_such_element": '{"id": 999, "name": "x"}',
    "category_cannot_change": '{"id": 100002, "category": "door"}',
}


@pytest.mark.parametrize("case", list(MODIFY_REFUSED))
def test_modify_refused(sc, case):
    """CATCHES: a modify that leaves the model breaking one of its rules being kept (exit 0), or refused with another
    message than the one that says what to fix."""
    sc.write("base.txt", "\n".join(BASE) + "\n")
    sc.run(["run", "--script", "base.txt", "--save", "base.bimcraft"], show=False)
    sc.run(["run", "base.bimcraft", "--cmd", "modify " + MODIFY_REFUSED[case]])
    assert sc.transcript() == sc.golden()


def test_modify_accepted_changes_fields(sc):
    """CATCHES: modify with only an id not giving the element back unchanged, or modify not changing a level's elevation
    (and the walls on it), a door's mark and offset, a room's name and number, a wall's type, or several elements at once
    with `ids`."""
    sc.cmds(*BASE, 'modify {"id": 100002}', 'modify {"id": 100001, "elevation": 3500}', 'modify {"id": 100007, "mark": "D1", "offset": 1200}',
            'modify {"id": 100009, "name": "Lounge", "number": "101"}', 'modify {"id": 100003, "type": "Generic - 200mm"}',
            'modify {"ids": [100012, 100013], "start": [0, -2000]}', elements("level"), elements("door"),
            elements("room"), elements("grid"), elements("wall"))
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# What a project file may not hold: the same rules, met by a file edited by hand
# ---------------------------------------------------------------------------------------------------------------------

# A project with something of most kinds a rule is about: compound walls, a door, a room, a floor and a ceiling, a project
# parameter, a sheet with a viewport, a duplicated plan, a tag, a detail group, a stair, a beam with a bar, a camera and
# a spot elevation.
RICH = [
    BOX,
    'door {"at": [1500, 0]}',
    'room {"point": [3000, 2000]}',
    "floor {}",
    'ceiling {"point": [3000, 2000]}',
    'parameter {"name": "Fire Rating", "kind": "text", "categories": ["wall"]}',
    "sheet {}",
    'place {"sheet": "A101", "view": "Level 1"}',
    'duplicate_view {"view": "Level 1", "name": "Level 1 - Copy"}',
    "tag {}",
    'detail_line {"points": [[0,0],[1000,1000]]}',
    'text {"text": "Note", "at": [500, 500]}',
    'create_group {"ids": [100014, 100015], "name": "Note Group"}',
    'stair {"start": [4000, 500], "end": [4000, 3500]}',
    'beam {"points": [[0,0],[6000,0]], "level": "Level 2"}',
    'rebar {"host": 100018, "points": [[100,100,2700],[5900,100,2700]], "diameter": 10}',
    'camera {"name": "Cam", "eye": [-5000,-5000,1700], "target": [3000,2000,1000]}',
    'spot {"at": [3000, 2000], "host": 100005}',
]


def by_cat(d, cat):
    return [e for e in d["elements"].values() if e["category"] == cat]


def level_guid(d, name="Level 1"):
    return next(e["guid"] for e in by_cat(d, "level") if e["name"] == name)


FILE_EDITS = {
    "line_pattern_named_solid": lambda d: d["line_patterns"].__setitem__("Solid", [{"dash": 2.0}, {"space": 1.0}]),
    "material_cut_pattern_missing": lambda d: d["materials"]["Brick"].__setitem__("cut", "Zebra"),
    "detail_group_empty": lambda d: d["detail_groups"]["Note Group"].__setitem__("members", []),
    "door_type_zero_width": lambda d: d["types"]["door"]["Single 900 x 2100"].__setitem__("width", 0.0),
    "window_type_sill_not_a_number": lambda d: d["types"]["window"]["Fixed 600 x 900"].__setitem__("sill", 1e12),
    "material_transparency_over_100": lambda d: d["materials"]["Glass"].__setitem__("transparency", 150),
    "material_blank_name": lambda d: d["materials"].__setitem__(" ", {"color": [1, 2, 3], "cut": "none", "surface": "none"}),
    "family_blank_name": lambda d: d["families"].__setitem__(" ", copy.deepcopy(d["families"]["Chair"])),
    "parameter_bad_name": lambda d: d["parameters"].__setitem__("9 Lives", {"kind": "text", "categories": ["wall"]}),
    "parameter_without_category": lambda d: d["parameters"].__setitem__("Notes", {"kind": "text", "categories": []}),
    "parameter_unknown_category": lambda d: d["parameters"].__setitem__("Notes", {"kind": "text", "categories": ["spaceship"]}),
    "parameter_shadowing_own_field": lambda d: d["parameters"].__setitem__("Length", {"kind": "number", "categories": ["wall"]}),
    "parameter_shadowing_family_parameter": lambda d: d["parameters"].__setitem__("Seat Height", {"kind": "length", "categories": ["component"]}),
    "wall_layers_not_adding_up": lambda d: d["types"]["wall"]["Exterior - 300mm"].__setitem__("thickness", 320.0),
    "wall_variable_layer": lambda d: d["types"]["wall"]["Exterior - 300mm"]["layers"][0].__setitem__("variable", True),
    "floor_two_variable_layers": lambda d: d["types"]["floor"].__setitem__("Two", {"thickness": 200.0, "layers": [{"function": "structure", "thickness": 100.0, "variable": True}, {"function": "finish", "thickness": 100.0, "variable": True}]}),
    "run_category_unknown": lambda d: d["types"]["runs"].__setitem__("teleporter", {"T1": {"width": 10.0, "depth": 10.0, "round": True}}),
    "round_run_type_not_square": lambda d: d["types"]["runs"]["pipe"]["PVC 50"].__setitem__("depth", 60.0),
    "railing_spacing_too_tight": lambda d: d["types"]["railing"]["Railing - 1000mm"].__setitem__("spacing", 10.0),
    "ceiling_grid_too_fine": lambda d: d["types"]["ceiling"]["Tile 600 x 600"].__setitem__("grid", 50.0),
    "rebar_without_grade": lambda d: by_cat(d, "rebar")[0].__setitem__("grade", " "),
    "rebar_one_point": lambda d: by_cat(d, "rebar")[0].__setitem__("path", [[0.0, 0.0, 0.0]]),
    "rebar_of_no_length": lambda d: by_cat(d, "rebar")[0].__setitem__("path", [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
    "rebar_point_too_far": lambda d: by_cat(d, "rebar")[0].__setitem__("path", [[0.0, 0.0, 0.0], [1e10, 0.0, 0.0]]),
    "sheet_without_number": lambda d: by_cat(d, "sheet")[0].__setitem__("number", " "),
    "viewport_scale_too_small": lambda d: by_cat(d, "viewport")[0].__setitem__("scale", 0.5),
    "viewport_on_a_level": lambda d: by_cat(d, "viewport")[0].__setitem__("sheet", level_guid(d)),
    "view3d_elevation_too_steep": lambda d: by_cat(d, "view3d")[0].__setitem__("elevation", 95.0),
    "view3d_lens_too_short": lambda d: by_cat(d, "view3d")[0]["perspective"].__setitem__("lens", 1.0),
    "view3d_named_as_a_level": lambda d: by_cat(d, "view3d")[0].__setitem__("name", "Level 2"),
    "view3d_without_name": lambda d: by_cat(d, "view3d")[0].__setitem__("name", " "),
    "camera_eye_on_target": lambda d: by_cat(d, "view3d")[0]["camera"].__setitem__("eye", [3000.0, 2000.0, 1000.0]),
    "planview_named_as_a_level": lambda d: by_cat(d, "planview")[0].__setitem__("name", "Level 2"),
    "planview_without_name": lambda d: by_cat(d, "planview")[0].__setitem__("name", " "),
    "spot_in_a_plan_without_host": lambda d: by_cat(d, "spot")[0].pop("host"),
    "tag_on_a_level": lambda d: by_cat(d, "tag")[0].__setitem__("host", level_guid(d)),
    "stair_landing_below_its_foot": lambda d: by_cat(d, "stair")[0].__setitem__("landings", [{"at": 0.0, "turn": 0.0}]),
    "room_separator_on_no_level": lambda d: d["elements"].__setitem__("100099", {"guid": "11111111-2222-4333-8444-555555555555", "category": "roomseparator", "level": "11111111-2222-4333-8444-666666666666", "start": [0.0, 0.0], "end": [1000.0, 0.0]}),
    "level_view_range_upside_down": lambda d: by_cat(d, "level")[0]["view_range"].__setitem__("depth", 500.0),
    "grids_named_alike": lambda d: [d["elements"].__setitem__(k, {"guid": g, "category": "grid", "name": "1", "start": [0.0, y], "end": [5000.0, y]}) for k, g, y in (("100097", "11111111-2222-4333-8444-000000000001", 0.0), ("100098", "11111111-2222-4333-8444-000000000002", 1000.0))],
}



@pytest.mark.parametrize("case", list(FILE_EDITS))
def test_project_file_breaking_a_rule_is_refused(sc, case):
    """CATCHES: a project file that breaks one of the model's rules (a name taken or blank, a size out of range, layers
    that don't add up, a reference to nothing, a view named as a level…) being opened anyway, or refused without the
    message that says which element or entry is wrong and what to fix."""
    sc.write("rich.txt", "\n".join(RICH) + "\n")
    sc.run(["run", "--script", "rich.txt", "--save", "rich.bimcraft"], show=False)
    doc = json.loads((sc.workdir / "rich.bimcraft").read_text(encoding="utf-8"))
    FILE_EDITS[case](doc)
    sc.write("edited.bimcraft", json.dumps(doc, indent=2))
    sc.run(["info", "edited.bimcraft"])
    sc.run(["run", "edited.bimcraft", "--cmd", "inspect {}"])
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# The sample and the tower
# ---------------------------------------------------------------------------------------------------------------------


def test_sample_house_inspect(sc):
    """CATCHES: the sample house built with other counts, levels, history steps or warnings than the reference's."""
    p = sc.run(["run", "--sample", "--cmd", "inspect {}"], show=False)
    data = json.loads(p.stdout.decode().splitlines()[-1])
    sc.note(f"exit {p.returncode}")
    sc.note(json.dumps({k: data[k] for k in ("counts", "levels", "history", "warnings", "name", "phases")}, sort_keys=True))
    assert sc.transcript() == sc.golden()


def test_sample_house_elements_by_category(sc):
    """CATCHES: the sample's walls, doors, windows, rooms, floors and roof built with other geometry or derived values."""
    sc.cmds(*(elements(c) for c in ("wall", "door", "window", "room", "floor", "roof", "grid")), pre=["--sample"])
    assert sc.transcript() == sc.golden()


def test_highrise_one_storey(sc):
    """CATCHES: the synthetic tower built with another element count or mix for one storey, or its storey limits not
    enforced (1 to 80)."""
    p = sc.run(["run", "--cmd", 'highrise {"storeys": 1}', "--cmd", "inspect {}"], show=False)
    lines = p.stdout.decode().splitlines()
    sc.note(f"exit {p.returncode}")
    sc.note(lines[0])
    sc.note(json.dumps(json.loads(lines[1])["counts"], sort_keys=True))
    sc.cmds('highrise {"storeys": 0}')
    sc.cmds('highrise {"storeys": 81}')
    assert sc.transcript() == sc.golden()
