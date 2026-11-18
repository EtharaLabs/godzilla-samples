"""The 3D view (render, perspective, cameras, styles, section boxes, work planes, 3D dimensions), glTF export, families
and components, materials, paint, favorites, masses and shape editing, all driven through `bimcraft-cli run`."""

import json
import struct
import zlib

# A small house every 3D test can look at: four walls with layers, a door, a window, a floor and a pitched roof.
HOUSE = [
    'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true, "type": "Exterior - 300mm"}',
    'door {"at": [3000, 0]}',
    'window {"at": [6000, 2000]}',
    "floor {}",
    'roof {"slope": 30, "overhang": 300}',
]

SMALL = '"width": 320, "height": 200'

# A generic family with a parameter of each kind, a formula, two types and a form in each sketch plane.
PLINTH = (
    'family {"name": "Plinth", "category": "generic", "parameters": ['
    '{"name": "Width", "kind": "length", "value": 1000}, {"name": "Depth", "kind": "length", "value": 600}, '
    '{"name": "Height", "kind": "length", "formula": "Width / 2"}, {"name": "Count", "kind": "number", "value": 3}, '
    '{"name": "Tilt", "kind": "angle", "value": 15}, {"name": "Lid", "kind": "yesno", "value": true}, '
    '{"name": "Finish", "kind": "material", "value": "Concrete"}, '
    '{"name": "Lift", "kind": "length", "instance": true, "value": 0}], '
    '"types": {"Small": {"Width": 800}, "Large": {"Width": 1600, "Depth": 900}}, '
    '"forms": ['
    '{"plane": "xy", "profile": [["-Width / 2", "-Depth / 2"], ["Width / 2", "-Depth / 2"], ["Width / 2", "Depth / 2"], '
    '["-Width / 2", "Depth / 2"]], "from": "Lift", "to": "Height", "material": "Finish"}, '
    '{"plane": "xz", "circle": {"centre": [0, "Height + 150"], "radius": 100}, "from": -200, "to": 200, "visible": "Lid"}, '
    '{"plane": "yz", "profile": [[-100, 0], [100, 0], [0, 200]], "from": "-Width / 2 - 100", "to": "-Width / 2", '
    '"material": "Metal"}]}'
)


def make_png(width: int, height: int, colour_at) -> bytes:
    """An 8-bit RGB PNG whose pixel (x, y) is colour_at(x, y)."""
    raw = b"".join(b"\x00" + b"".join(bytes(colour_at(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def files(sc):
    """Every file in the working directory, by name (an instrumented build's own *.profraw left out)."""
    names = sorted(str(p.relative_to(sc.workdir)) for p in sc.workdir.rglob("*") if p.is_file() and p.suffix != ".profraw")
    sc.note("=== files: " + ", ".join(names))


def checker(x: int, y: int):
    return (200, 40, 40) if (x // 4 + y // 4) % 2 else (240, 230, 90)


# ---------------------------------------------------------------------------------------------------------------------
# The 3D view
# ---------------------------------------------------------------------------------------------------------------------


def test_render_3d_default_and_turned_views(sc):
    """CATCHES: a 3D render that ignores azimuth or elevation, draws the house from another default side than the
    south-east 30 degrees up, writes another picture, or replies with other fields (eye, lens, kind, size)."""
    sc.cmds(
        *HOUSE,
        f'render {{"view": "{{3D}}", {SMALL}, "path": "se.png"}}',
        f'render {{"view": "{{3D}}", {SMALL}, "azimuth": 135, "elevation": 10, "path": "nw.png"}}',
        f'render {{"view": "3D", {SMALL}, "azimuth": -90, "elevation": 89, "path": "top.png"}}',
    )
    sc.file("se.png")
    sc.file("nw.png")
    sc.file("top.png")
    assert sc.transcript() == sc.golden()


def test_render_3d_inline_png_and_size_clamped(sc):
    """CATCHES: a 3D render without a path that doesn't answer with an inline base64 PNG, or sizes not clamped to at
    least 16 px a side."""
    sc.cmds(*HOUSE, 'render {"view": "{3D}", "width": 40, "height": 2}')
    assert sc.transcript() == sc.golden()


def test_render_3d_of_an_empty_project(sc):
    """CATCHES: a crash or an error drawing the 3D view of a project with nothing in it but its two levels."""
    sc.cmds(f'render {{"view": "{{3D}}", {SMALL}, "path": "empty.png"}}')
    sc.file("empty.png")
    assert sc.transcript() == sc.golden()


def test_render_3d_to_svg_is_refused(sc):
    """CATCHES: a 3D render written as an SVG (only plans make SVGs) instead of being refused with a message."""
    sc.cmds(*HOUSE, 'render {"view": "{3D}", "path": "view.svg"}')
    files(sc)
    assert sc.transcript() == sc.golden()


def test_visual_styles_draw_differently(sc):
    """CATCHES: hidden_line or wireframe drawing the same picture as shaded, the style not being kept by the view, or
    `visual_style` without a style changing it instead of reading it."""
    sc.cmds(
        *HOUSE,
        "visual_style {}",
        f'render {{"view": "{{3D}}", {SMALL}, "path": "shaded.png"}}',
        'visual_style {"style": "hidden_line"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "hidden.png"}}',
        'visual_style {"view": "{3D}", "style": "wireframe"}',
        "visual_style {}",
        f'render {{"view": "{{3D}}", {SMALL}, "path": "wire.png"}}',
    )
    sc.file("shaded.png")
    sc.file("hidden.png")
    sc.file("wire.png")
    assert sc.transcript() == sc.golden()


def test_visual_style_errors(sc):
    """CATCHES: an unknown visual style being accepted, or a plan given as the view of a 3D-only setting."""
    sc.cmds(*HOUSE, 'visual_style {"style": "sketchy"}')
    sc.cmds(*HOUSE, 'visual_style {"view": "Level 1", "style": "wireframe"}')
    assert sc.transcript() == sc.golden()


def test_perspective_lens_and_eye_elevation(sc):
    """CATCHES: perspective not kept with its lens, eye_elevation not raising the eye (and the elevation it reports),
    turning perspective off losing the lens, or a parallel view accepting an eye_elevation."""
    sc.cmds(
        *HOUSE,
        'perspective {"lens": 50}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "p50.png"}}',
        f'render {{"view": "{{3D}}", {SMALL}, "eye_elevation": 1600, "path": "eye.png"}}',
        'perspective {"on": false}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "parallel.png"}}',
        "perspective {}",
    )
    sc.cmds(*HOUSE, f'render {{"view": "{{3D}}", {SMALL}, "eye_elevation": 1600}}')
    sc.cmds(*HOUSE, 'perspective {"on": "yes"}')
    sc.file("p50.png")
    sc.file("eye.png")
    sc.file("parallel.png")
    assert sc.transcript() == sc.golden()


def test_camera_views_made_read_and_changed(sc):
    """CATCHES: cameras not named Camera 1, Camera 2, a named camera losing its name, reading a camera changing it, a lens
    alone not keeping the camera's points, or the camera's render not looking from its eye."""
    sc.cmds(
        *HOUSE,
        'camera {"view": "{3D}"}',
        'camera {"eye": [-5000, -6000, 1700], "target": [3000, 2000, 1000]}',
        'camera {"eye": [9000, 9000, 4000], "target": [3000, 2000, 0], "lens": 24, "name": "Corner"}',
        'camera {"eye": [-4000, 2000, 1500], "target": [3000, 2000, 1500]}',
        'camera {"view": "Camera 1"}',
        'camera {"view": "Camera 1", "lens": 85}',
        'camera {"view": "Corner", "target": [3000, 2000, 2000]}',
        f'render {{"view": "Camera 1", {SMALL}, "path": "cam1.png"}}',
        f'render {{"view": "Corner", {SMALL}, "path": "corner.png"}}',
    )
    sc.file("cam1.png")
    sc.file("corner.png")
    assert sc.transcript() == sc.golden()


def test_camera_errors(sc):
    """CATCHES: a camera with its eye on its target, a lens outside 10 to 600 mm, a camera without both points, a camera
    on a plan view, or a malformed point being accepted."""
    for bad in [
        'camera {"eye": [1000, 1000, 1000], "target": [1000, 1000, 1000]}',
        'camera {"eye": [0, 0, 1000], "target": [1000, 1000, 1000], "lens": 5}',
        'camera {"eye": [0, 0, 1000], "target": [1000, 1000, 1000], "lens": 601}',
        'camera {"eye": [0, 0, 1000]}',
        'camera {"view": "Level 1", "lens": 50}',
        'camera {"eye": [0, 0], "target": [1000, 1000, 1000]}',
    ]:
        sc.cmds(*HOUSE[:1], bad)
    assert sc.transcript() == sc.golden()


def test_graphic_display_options(sc):
    """CATCHES: wrong defaults (edges on, no silhouette, no ambient shadows), options given not kept while the others
    stay, silhouettes or shadows not changing the picture, or a silhouette that is no whole number from 0 to 10 being
    accepted."""
    sc.cmds(
        *HOUSE,
        "graphic_display_options {}",
        'graphic_display_options {"edges": false}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "noedges.png"}}',
        'GD {"silhouette": 4, "ambient_shadows": true}',
        'graphic_display_options {"view": "{3D}"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "outlined.png"}}',
    )
    for bad in ['{"silhouette": 11}', '{"silhouette": 1.5}', '{"edges": "no"}', '{"view": "Level 1", "edges": true}']:
        sc.cmds(*HOUSE[:1], f"graphic_display_options {bad}")
    sc.file("noedges.png")
    sc.file("outlined.png")
    assert sc.transcript() == sc.golden()


def test_section_box_fitted_moved_and_off(sc):
    """CATCHES: a section box not fitted 300 mm round the model when turned on with no corners, a corner given not
    replacing only that corner, `on: false` losing the extents, or the boxed render not cutting the house away."""
    sc.cmds(
        *HOUSE,
        "section_box {}",
        'section_box {"max": [3000, 5000, 2000]}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "boxed.png"}}',
        'section_box {"on": false}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "unboxed.png"}}',
        'section_box {"on": true, "min": [1000, -1000, -100], "max": [5000, 2000, 6000]}',
    )
    sc.file("boxed.png")
    sc.file("unboxed.png")
    assert sc.transcript() == sc.golden()


def test_section_box_errors(sc):
    """CATCHES: a section box fitted round an empty project, a corner that is not [x, y, z], `on` that is not a boolean,
    or a plan given a section box."""
    sc.cmds("section_box {}")
    sc.cmds(*HOUSE[:1], 'section_box {"min": [0, 0]}')
    sc.cmds(*HOUSE[:1], 'section_box {"on": 1}')
    sc.cmds(*HOUSE[:1], 'section_box {"view": "Level 2"}')
    assert sc.transcript() == sc.golden()


def test_work_plane_level_points_surface_offset(sc):
    """CATCHES: a work plane at the wrong height or normal for a level with an offset, three points, an upright surface
    or a moved plane, the wrong slope in degrees, or nothing given not going back to the lowest level."""
    sc.cmds(
        *HOUSE[:1],
        "work_plane {}",
        'work_plane {"level": "Level 2", "offset": 100}',
        'work_plane {"offset": -250}',
        'work_plane {"points": [[0, 0, 0], [1000, 0, 0], [0, 1000, 1000]]}',
        'work_plane {"surface": {"point": [0, 2000, 1500], "normal": [-1, 0, 0]}, "offset": 150}',
        'work_plane {"points": [[0, 0, 0], [1000, 0, 0], [0, 0, 1000]]}',
        "work_plane {}",
    )
    assert sc.transcript() == sc.golden()


def test_work_plane_errors(sc):
    """CATCHES: three points along a line, malformed points or surfaces, an unknown key or a level that isn't there
    being accepted as a work plane."""
    for bad in [
        '{"points": [[0, 0, 0], [1000, 0, 0], [2000, 0, 0]]}',
        '{"points": [[0, 0], [1, 0], [0, 1]]}',
        '{"surface": {"point": [0, 0, 0]}}',
        '{"plane": "xy"}',
        '{"level": "Level 9"}',
        '{"view": "Level 1"}',
    ]:
        sc.cmds(f"work_plane {bad}")
    assert sc.transcript() == sc.golden()


def test_dimension_3d_points_and_edges(sc):
    """CATCHES: a 3D dimension measuring the wrong length between points, from a point to an edge's line or between
    parallel edges, not being kept by the default 3D view, or not drawn over the 3D render."""
    sc.cmds(
        *HOUSE,
        'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [6000, 0, 0]}], "at": [3000, -1000, 0]}',
        'dimension_3d {"refs": [{"at": [0, 0, 0], "edge": [[0, 0, 0], [0, 0, 3000]]}, '
        '{"at": [6000, 4000, 0], "edge": [[6000, 4000, 0], [6000, 4000, 3000]]}], "at": [3000, -500, 3000]}',
        'dimension_3d {"refs": [{"at": [0, 0, 3000]}, {"at": [6000, 0, 0], "edge": [[6000, 0, 0], [6000, 4000, 0]]}], '
        '"at": [3000, -800, 1500]}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "dims.png"}}',
        'elements {"category": "dimension"}',
    )
    sc.cmds(*HOUSE[:1], 'dimension_3d {"refs": [{"at": [0, 0, 0]}], "at": [0, 0, 0]}')
    sc.cmds(*HOUSE[:1], 'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [0, 0, 0]}], "at": [0, 1000, 0]}')
    sc.file("dims.png")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# glTF
# ---------------------------------------------------------------------------------------------------------------------


def test_glb_export_of_a_house(sc):
    """CATCHES: a .glb with other nodes, meshes, materials, accessors, extras (id, GUID, category) or vertex data than the
    reference's, metres and y up, or a save reply with other element and triangle counts."""
    sc.run(["run", *sum((["--cmd", c] for c in HOUSE), []), "--save", "house.glb"])
    sc.file("house.glb")
    assert sc.transcript() == sc.golden()


def test_glb_export_of_an_empty_project(sc):
    """CATCHES: a .glb written for a project with nothing built, instead of refusing with a message and writing no file."""
    sc.run(["run", "--save", "empty.glb"])
    sc.run(["run", "--cmd", 'wall {"points": [[0, 0], [4000, 0]]}', "--cmd", 'graphics {"view": "{3D}", "hide": ["walls"]}',
            "--save", "hidden.glb"])
    files(sc)
    assert sc.transcript() == sc.golden()


def test_convert_project_to_glb_with_components_and_glass(sc):
    """CATCHES: `convert` from a .bimcraft to .glb losing components (a table, a chair), a column or the window's
    see-through glass, or writing other geometry than `run --save` would."""
    sc.run(
        [
            "run",
            "--cmd", HOUSE[0],
            "--cmd", 'window {"at": [3000, 4000], "family": "Casement Window"}',
            "--cmd", 'component {"family": "Table", "at": [3000, 2000]}',
            "--cmd", 'component {"family": "Chair", "at": [2000, 2000], "angle": 90}',
            "--cmd", 'column {"at": [1000, 1000], "type": "Round 300"}',
            "--save", "room.bimcraft",
        ],
        show=False,
    )
    sc.run(["convert", "room.bimcraft", "room.glb"])
    sc.file("room.glb")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Families and components
# ---------------------------------------------------------------------------------------------------------------------


def test_family_list_and_read_a_starter(sc):
    """CATCHES: the starter families listed with other categories or counts of types, forms and symbols, or a family read
    without its formulas, its types' worked-out values or its forms' ids."""
    sc.cmds("family {}", 'family {"name": "Table"}', 'family {"name": "Single Door"}')
    sc.cmds('family {"name": "Nope"}')
    assert sc.transcript() == sc.golden()


def test_family_created_with_every_parameter_kind(sc):
    """CATCHES: a family whose formulas aren't worked out per type (Height = Width / 2), a type value not merged over the
    defaults, yes/no read as anything but 1, or forms in the xy, xz and yz planes stored differently."""
    sc.cmds(PLINTH, 'family {"name": "Plinth"}', "family {}")
    assert sc.transcript() == sc.golden()


def test_family_component_render_previews(sc):
    """CATCHES: a family preview in 3d, plan or elevation drawn differently, the preview leaving an element or an undo step
    in the project, or the first type not being the default."""
    sc.cmds(
        PLINTH,
        f'render {{"family": "Plinth", "type": "Large", {SMALL}, "path": "f3d.png"}}',
        f'render {{"family": "Plinth", "mode": "plan", {SMALL}, "path": "fplan.png"}}',
        f'render {{"family": "Plinth", "mode": "elevation", {SMALL}, "path": "felev.png"}}',
        "inspect {}",
    )
    sc.file("f3d.png")
    sc.file("fplan.png")
    sc.file("felev.png")
    assert sc.transcript() == sc.golden()


def test_family_preview_errors(sc):
    """CATCHES: previews of a family or type that isn't there, an unknown mode, a non-positive wall thickness, or a
    `mode` without `family` being drawn instead of refused."""
    for bad in [
        '{"family": "Nope"}',
        '{"family": "Table", "type": "9 x 9"}',
        '{"family": "Table", "mode": "section"}',
        '{"family": "Single Door", "wall_thickness": -5}',
        '{"mode": "3d"}',
    ]:
        sc.cmds(f"render {bad}")
    assert sc.transcript() == sc.golden()


def test_door_family_in_walls_of_different_thickness(sc):
    """CATCHES: a hosted family preview not standing in a wall as thick as `wall_thickness`, or a door family placed in
    a wall not drawn with its forms in plan and 3D."""
    sc.cmds(
        f'render {{"family": "Single Door", "type": "900 x 2100", "wall_thickness": 100, {SMALL}, "path": "thin.png"}}',
        f'render {{"family": "Single Door", "type": "900 x 2100", "wall_thickness": 400, {SMALL}, "path": "thick.png"}}',
        f'render {{"family": "Casement Window", "mode": "elevation", {SMALL}, "path": "win.png"}}',
    )
    sc.cmds(
        'wall {"points": [[0, 0], [5000, 0]]}',
        'door {"at": [2500, 0], "family": "Double Door", "type": "1500 x 2100", "flip_facing": true}',
        'elements {"category": "door"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "door3d.png"}}',
    )
    sc.file("thin.png")
    sc.file("thick.png")
    sc.file("win.png")
    sc.file("door3d.png")
    assert sc.transcript() == sc.golden()


def test_family_with_voids_revolves_and_warnings(sc):
    """CATCHES: a void that cuts nothing not warned of, a void not cutting the solid before it, a profile turned about an
    axis not drawn as a solid of revolution, or a warning that stops the change."""
    sc.cmds(
        'family {"name": "Basin", "category": "plumbing", "parameters": [{"name": "Size", "kind": "length", "value": 600}], '
        '"types": {"Standard": {}}, "forms": ['
        '{"plane": "xy", "profile": [["-Size / 2", "-Size / 2"], ["Size / 2", "-Size / 2"], ["Size / 2", "Size / 2"], '
        '["-Size / 2", "Size / 2"]], "from": 0, "to": 800, "material": "Porcelain"}, '
        '{"plane": "xy", "circle": {"centre": [0, 0], "radius": "Size / 3"}, "from": 600, "to": 900, "void": true}, '
        '{"plane": "xy", "circle": {"centre": [5000, 0], "radius": 100}, "from": 0, "to": 100, "void": true}]}',
        'family {"name": "Lamp", "category": "lighting", "parameters": [], "types": {"Standard": {}}, "forms": ['
        '{"plane": "xz", "profile": [[0, 0], [200, 0], [100, 400], [0, 400]], "axis": [[0, 0], [0, 400]], "from": 0, '
        '"to": 360, "material": "Metal"}]}',
        f'render {{"family": "Basin", {SMALL}, "path": "basin.png"}}',
        f'render {{"family": "Lamp", {SMALL}, "path": "lamp.png"}}',
        'component {"family": "Basin", "at": [0, 0]}',
        'component {"family": "Lamp", "at": [2000, 0]}',
        "save {\"path\": \"bits.glb\"}",
    )
    sc.file("basin.png")
    sc.file("lamp.png")
    sc.file("bits.glb")
    assert sc.transcript() == sc.golden()


def test_family_validation_errors_are_all_reported(sc):
    """CATCHES: a formula reading an unknown parameter, a syntax error, a type naming no parameter, a door family without
    Width and Height, a form with neither profile nor circle, or an unknown material being accepted, or only the first
    error being reported."""
    for bad in [
        '{"name": "A", "parameters": [{"name": "W", "kind": "length", "formula": "Q * 2"}], "types": {"T": {}}}',
        '{"name": "B", "parameters": [{"name": "W", "kind": "length", "formula": "(1 + "}], "types": {"T": {}}}',
        '{"name": "C", "parameters": [{"name": "W", "kind": "length", "value": 1}], "types": {"T": {"Z": 3}}}',
        '{"name": "D", "category": "door", "parameters": [], "types": {"T": {}}}',
        '{"name": "E", "parameters": [], "types": {"T": {}}, "forms": [{"plane": "xy", "to": 100}]}',
        '{"name": "F", "parameters": [], "types": {"T": {}}, "forms": [{"plane": "xy", '
        '"profile": [[0, 0], [100, 0], [0, 100]], "to": 100, "material": "Unobtainium"}]}',
        '{"name": "G", "parameters": [{"name": "W", "kind": "length", "formula": "Q"}, {"name": "W", "kind": "length"}], '
        '"types": {"T": {}}, "forms": [{"plane": "xy", "profile": [[0, 0], ["Nope", 0], [0, 100]], "to": 100}]}',
        '{"name": "H", "parameters": [], "types": {}}',
        '{"name": "I", "category": "spaceship", "types": {"T": {}}}',
        '{"name": "J", "parameters": [{"name": "Paint", "kind": "length"}], "types": {"T": {}}}',
        '{"name": "K", "parameters": [{"name": "W", "kind": "length", "value": 1, "instance": true}], '
        '"types": {"T": {"W": 2}}}',
    ]:
        sc.cmds(f"family {bad}")
    assert sc.transcript() == sc.golden()


def test_family_dry_run_patch_and_delete_forms(sc):
    """CATCHES: a dry run that changes the family, `changes` not listing what was added and replaced, a form patched by
    id losing its id or place, delete_form taking another form, or a missing form id being accepted."""
    sc.cmds(
        PLINTH,
        'family {"name": "Plinth", "types": {"Huge": {"Width": 3000}, "Small": null}, "dry_run": true}',
        'family {"name": "Plinth"}',
        'family {"name": "Plinth", "form": {"id": 999455, "radius": null, "circle": {"centre": [0, 0], "radius": 50}}}',
        'family {"name": "Plinth", "delete_form": [999454]}',
        'family {"name": "Plinth"}',
    )
    sc.cmds(PLINTH, 'family {"name": "Plinth", "delete_form": [123456]}')
    assert sc.transcript() == sc.golden()


def test_family_rename_and_delete(sc):
    """CATCHES: a renamed family whose components don't follow it, a rename onto a name taken, a family deleted while
    a component uses it, or deleting a family that isn't there."""
    sc.cmds(
        PLINTH,
        'component {"family": "Plinth", "at": [0, 0]}',
        'family {"name": "Plinth", "rename": "Base"}',
        'elements {"category": "component"}',
    )
    sc.cmds(PLINTH, 'family {"name": "Plinth", "rename": "Table"}')
    sc.cmds(PLINTH, 'component {"family": "Plinth", "at": [0, 0]}', 'family {"name": "Plinth", "delete": true}')
    sc.cmds(PLINTH, 'family {"name": "Plinth", "delete": true}', 'family {"name": "Plinth"}')
    sc.cmds('family {"name": "Nope", "delete": true}')
    sc.cmds('family {"delete": true}')
    assert sc.transcript() == sc.golden()


def test_family_saved_to_json_and_loaded_into_another_project(sc):
    """CATCHES: a family file written with another layout, or loading it with `path` (under its own or another name)
    not giving the same parameters, types and forms, or a file that isn't a family being accepted."""
    sc.cmds(PLINTH, 'family {"name": "Plinth", "save": "plinth.json"}')
    sc.file("plinth.json")
    sc.cmds('family {"path": "plinth.json"}', 'family {"path": "plinth.json", "name": "Copy"}', "family {}")
    sc.write("bad.json", "[1, 2, 3]")
    sc.write("broken.json", "{not json")
    sc.cmds('family {"path": "bad.json"}')
    sc.cmds('family {"path": "broken.json"}')
    sc.cmds('family {"path": "absent.json"}')
    sc.cmds('family {"name": "Nope", "save": "x.json"}')
    assert sc.transcript() == sc.golden()


def test_family_with_symbols_text_and_dots(sc):
    """CATCHES: plan symbols (lines, arcs, text with a parameter read in, dots) not drawn in the family's plan preview or
    the level's plan, or a text reading an unknown parameter being accepted."""
    fam = (
        'family {"name": "Marker", "category": "generic", "parameters": [{"name": "Code", "kind": "number", "value": 7}], '
        '"types": {"Standard": {}}, "symbols": ['
        '{"line": [[-300, -300], [300, -300], [300, 300], [-300, 300], [-300, -300]]}, '
        '{"arc": {"centre": [0, 0], "radius": 250, "from": 0, "to": 270}}, '
        '{"text": {"at": [0, 0], "height": 120, "value": "N{Code}", "align": "center"}}, '
        '{"dot": {"centre": [200, 200], "radius": 40}}]}'
    )
    sc.cmds(
        fam,
        f'render {{"family": "Marker", "mode": "plan", {SMALL}, "path": "marker.png"}}',
        'component {"family": "Marker", "at": [1000, 1000], "angle": 45}',
        'family {"name": "Marker"}',
    )
    sc.cmds(
        'family {"name": "Bad", "types": {"Standard": {}}, "symbols": [{"text": {"at": [0, 0], "height": 100, '
        '"value": "{Missing}"}}]}'
    )
    sc.cmds('family {"name": "Bad", "types": {"Standard": {}}, "symbols": [{"dot": {"centre": [0, 0], "radius": 0}}]}')
    sc.file("marker.png")
    assert sc.transcript() == sc.golden()


def test_components_placed_with_angle_offset_mirror_and_params(sc):
    """CATCHES: a component's angle, offset, mirror or instance parameters not kept, its first type not the default, a
    type parameter given per instance or an unknown family or type being accepted."""
    sc.cmds(
        PLINTH,
        'component {"family": "Plinth", "at": [1000, 2000], "angle": 30, "offset": 100, "mirrored": true, '
        '"params": {"Lift": 50}}',
        'CM {"family": "Plinth", "type": "Large", "at": [4000, 0]}',
        'component {"family": "Table", "type": "1200 x 800", "at": [0, -2000]}',
        'elements {"category": "component"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "comps.png"}}',
    )
    sc.cmds(PLINTH, 'component {"family": "Plinth", "at": [0, 0], "params": {"Width": 500}}')
    sc.cmds('component {"family": "Nope", "at": [0, 0]}')
    sc.cmds('component {"family": "Table", "type": "9 x 9", "at": [0, 0]}')
    sc.cmds('component {"family": "Table"}')
    sc.file("comps.png")
    assert sc.transcript() == sc.golden()


def test_symbol_set_arei_in_three_languages(sc):
    """CATCHES: the AREI set loading another number of families or other names in English, Dutch or French, a second load
    overwriting what is there instead of keeping it, or an unknown set being accepted."""
    sc.cmds('symbol_set {"set": "arei"}', 'symbol_set {"set": "arei"}')
    sc.cmds('symbol_set {"set": "arei", "names": "nl"}')
    sc.cmds('symbol_set {"set": "arei", "names": "fr"}')
    sc.cmds('symbol_set {"set": "xyz"}')
    sc.cmds('symbol_set {"set": "arei", "names": "de"}')
    assert sc.transcript() == sc.golden()


def test_symbol_set_family_read_and_drawn(sc):
    """CATCHES: an AREI family read with other symbols, of another category, or its plan preview drawn differently."""
    sc.run(["run", "--cmd", 'symbol_set {"set": "arei"}', "--cmd", 'family {"name": "Bell"}',
            "--cmd", f'render {{"family": "Bell", "mode": "plan", {SMALL}, "path": "bell.png"}}'])
    sc.file("bell.png")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Materials, textures, paint and favorites
# ---------------------------------------------------------------------------------------------------------------------


def test_material_created_changed_renamed_deleted(sc):
    """CATCHES: a material's colour read wrongly from #rrggbb or [r, g, b], its patterns, transparency or texture not
    kept, a change not merging over what it had, a rename that layers don't follow, or a used material deleted."""
    sc.cmds(
        'material {"name": "Teal", "color": "#118899", "cut": "diagonal", "surface": "grid", "transparency": 25, '
        '"texture": {"kind": "tile", "size": [300, 300], "angle": 45, "offset": [10, 20]}}',
        'material {"name": "Teal", "color": [10, 20, 30], "texture": null}',
        'material {"name": "Teal", "rename": "Sea"}',
        'type {"category": "wall", "name": "Sea Wall", "layers": [{"function": "structure", "material": "Sea", '
        '"thickness": 200}]}',
        'material {"name": "Sea", "delete": true}',
    )
    sc.cmds('material {"name": "Gone", "color": "#ffffff"}', 'material {"name": "Gone", "delete": true}', "library {\"kind\": \"material\"}")
    assert sc.transcript() == sc.golden()


def test_material_errors(sc):
    """CATCHES: malformed colours, an unknown pattern or texture kind, a transparency over 100, renaming onto a
    material that exists or deleting one a starter type uses being accepted."""
    for bad in [
        '{"name": "X", "color": "#12345"}',
        '{"name": "X", "color": [300, 0, 0]}',
        '{"name": "X", "cut": "polka"}',
        '{"name": "X", "texture": {"kind": "marble"}}',
        '{"name": "X", "transparency": 101}',
        '{"name": "Brick", "rename": "Concrete"}',
        '{"name": "Brick", "delete": true}',
        '{"name": "Nope", "delete": true}',
        '{"name": "X", "texture": {"kind": "image", "path": "missing.png"}}',
    ]:
        sc.cmds(f"material {bad}")
    assert sc.transcript() == sc.golden()


def test_material_texture_from_a_picture(sc):
    """CATCHES: a PNG texture not taken into the project as a picture (listed by inspect), not tiled at its size on the
    faces of a wall's type in the 3D view, or the picture not saved with the project."""
    sc.write("checker.png", make_png(16, 16, checker))
    sc.run(
        [
            "run",
            "--cmd", 'material {"name": "Checks", "color": "#ffffff", "texture": {"kind": "image", "path": "checker.png", '
                     '"size": [500, 500]}}',
            "--cmd", 'type {"category": "wall", "name": "Checked", "layers": [{"function": "structure", '
                     '"material": "Checks", "thickness": 200}]}',
            "--cmd", 'wall {"points": [[0, 0], [6000, 0], [6000, 4000]], "type": "Checked"}',
            "--cmd", 'library {"kind": "material", "name": "Checks"}',
            "--cmd", f'render {{"view": "{{3D}}", {SMALL}, "path": "textured.png"}}',
            "--save", "tex.bimcraft",
        ]
    )
    p = sc.run(["info", "tex.bimcraft"], show=False)
    info = json.loads(p.stdout)
    sc.note(json.dumps({"images": info["images"], "Checks": info["materials"]["Checks"]}, sort_keys=True))
    sc.file("textured.png")
    assert sc.transcript() == sc.golden()


def test_material_texture_kinds_render(sc):
    """CATCHES: the drawn texture kinds (brick, boards, roof, metal…) not drawn in the 3D view, or drawn alike."""
    cmds = []
    for i, kind in enumerate(["brick", "boards", "roof", "metal", "plaster", "fabric"]):
        cmds += [
            f'material {{"name": "M{kind}", "color": "#a0a0a0", "texture": {{"kind": "{kind}"}}}}',
            f'type {{"category": "wall", "name": "W{kind}", "layers": [{{"material": "M{kind}", "thickness": 200}}]}}',
            f'wall {{"points": [[{i * 1500}, 0], [{i * 1500 + 1200}, 0]], "type": "W{kind}"}}',
        ]
    sc.cmds(*cmds, f'render {{"view": "{{3D}}", "width": 480, "height": 240, "azimuth": -90, "elevation": 5, '
                   f'"path": "kinds.png"}}')
    sc.file("kinds.png")
    assert sc.transcript() == sc.golden()


def test_paint_faces_and_take_it_off(sc):
    """CATCHES: paint not kept per face (a wall's exterior and interior, a floor's top, every face of a column), not
    changing the 3D view, `material: null` not taking only that face's off, or paint with an unknown material, face or
    element accepted."""
    sc.cmds(
        *HOUSE,
        'column {"at": [8000, 1500]}',
        'paint {"id": 100002, "face": "exterior", "material": "Timber"}',
        'paint {"id": 100002, "face": "interior", "material": "Copper"}',
        'PT {"ids": [100008], "face": "top", "material": "Ceramic tile"}',
        'paint {"id": 100010, "material": "Copper"}',
        'elements {"category": "column"}',
        'elements {"category": "wall", "limit": 1}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "painted.png"}}',
        'paint {"id": 100002, "face": "exterior", "material": null}',
        'paint {"id": 100010, "material": null}',
        'elements {"category": "wall", "limit": 1}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "unpainted.png"}}',
    )
    sc.cmds(*HOUSE[:1], 'paint {"id": 100002, "material": "Unobtainium"}')
    sc.cmds(*HOUSE[:1], 'paint {"id": 100002, "face": "top", "material": "Timber"}')
    sc.cmds(*HOUSE[:1], 'paint {"id": 999999, "material": "Timber"}')
    sc.file("painted.png")
    sc.file("unpainted.png")
    assert sc.transcript() == sc.golden()


def test_favorites_saved_listed_loaded_deleted(sc):
    """CATCHES: favorites not written to the file `path` names, a load over a material the project has without
    `replace`, `as` not naming the copy, a family kept without its materials, or delete removing the wrong one."""
    sc.cmds(
        'material {"name": "Teal", "color": "#118899", "texture": {"kind": "tile", "size": [300, 300]}}',
        'favorite {"action": "save", "kind": "material", "name": "Teal", "path": "fav.json"}',
        'favorite {"action": "save", "kind": "family", "name": "Table", "as": "My Table", "path": "fav.json"}',
        'favorite {"path": "fav.json"}',
        'favorite {"action": "load", "kind": "material", "name": "Teal", "as": "Teal 2", "path": "fav.json"}',
        'favorite {"action": "load", "kind": "material", "name": "Teal", "replace": true, "path": "fav.json"}',
        'favorite {"action": "load", "kind": "family", "name": "My Table", "path": "fav.json"}',
        'favorite {"action": "delete", "kind": "material", "name": "Teal", "path": "fav.json"}',
        'favorite {"action": "list", "path": "fav.json"}',
    )
    sc.file("fav.json")
    sc.cmds('favorite {"action": "load", "kind": "material", "name": "Teal", "path": "fav.json"}')
    sc.cmds('favorite {"action": "save", "kind": "material", "name": "Nope", "path": "fav.json"}')
    sc.cmds('favorite {"action": "frobnicate", "path": "fav.json"}')
    sc.cmds('favorite {"path": "none.json"}')
    assert sc.transcript() == sc.golden()


def test_favorites_with_a_picture_and_the_default_file(sc):
    """CATCHES: a material favorite saved without the picture its texture is made of, or a favorite kept anywhere but
    BIMCRAFT_FAVORITES when no path is given."""
    sc.write("checker.png", make_png(8, 8, checker))
    p = sc._run(
        [
            "run",
            "--cmd", 'material {"name": "Checks", "texture": {"kind": "image", "path": "checker.png"}}',
            "--cmd", 'favorite {"action": "save", "kind": "material", "name": "Checks"}',
            "--cmd", 'favorite {}',
        ],
        env_overrides={"BIMCRAFT_FAVORITES": "favs.json"},
    )
    sc.note(f"[exit {p.returncode}]\n{p.stdout.decode()}{p.stderr.decode()}")
    p = sc._run(
        ["run", "--cmd", 'favorite {"action": "load", "kind": "material", "name": "Checks"}',
         "--cmd", 'library {"kind": "material", "name": "Checks"}'],
        env_overrides={"BIMCRAFT_FAVORITES": "favs.json"},
    )
    sc.note(f"[exit {p.returncode}]\n{p.stdout.decode()}{p.stderr.decode()}")
    sc.file("favs.json")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Masses
# ---------------------------------------------------------------------------------------------------------------------

LEVELS = ['level {"elevation": 6000}', 'level {"elevation": 9000}']
BLOCK = 'mass {"boundary": [[0,0],[10000,0],[10000,8000],[0,8000]], "height": 9500, "name": "Block"}'


def test_mass_shapes_straight_lofted_and_leaning(sc):
    """CATCHES: a mass's area, volume, gross floor area or levels computed wrongly for a box up to a level, a lofted
    mass (exact volume by its cross sections) or a leaning one, or a top outline that doesn't pair up accepted."""
    sc.cmds(
        *LEVELS,
        BLOCK,
        'MS {"boundary": [[20000,0],[26000,0],[26000,6000],[20000,6000]], "top_level": "Level 3", "base_offset": 500}',
        'mass {"boundary": [[30000,0],[36000,0],[36000,6000],[30000,6000]], "top": [[31000,1000],[35000,1000],'
        '[35000,5000],[31000,5000]], "height": 7000, "name": "Loft"}',
        'mass {"boundary": [[40000,0],[44000,0],[44000,4000],[40000,4000]], "lean": [2000, 0], "height": 6000}',
        'elements {"category": "mass"}',
    )
    sc.cmds('mass {"boundary": [[0,0],[1000,0],[1000,1000],[0,1000]], "top": [[0,0],[1000,0],[500,800]]}')
    sc.cmds('mass {"boundary": [[0,0],[1000,0]]}')
    sc.cmds('mass {"boundary": [[0,0],[1000,0],[1000,1000],[0,1000]], "height": -10}')
    assert sc.transcript() == sc.golden()


def test_mass_floors_made_updated_stale_and_pruned(sc):
    """CATCHES: mass_floors making a second floor on a rerun, not listing floors on levels the mass no longer crosses as
    stale, deleting them without `prune`, or the massfloors schedule giving other areas and volumes."""
    sc.cmds(
        *LEVELS,
        BLOCK,
        "mass_floors {}",
        "MF {}",
        'modify {"id": 100004, "height": 5000}',
        'mass_floors {"mass": 100004, "type": "Generic - 200mm"}',
        'schedule {"name": "Mass Floors", "category": "massfloors"}',
        'mass_floors {"mass": 100004, "prune": true}',
        'elements {"category": "floor"}',
    )
    sc.cmds('mass_floors {"mass": 100000}')
    assert sc.transcript() == sc.golden()


def test_model_by_face_and_update_to_face(sc):
    """CATCHES: walls by face not on each footprint edge (or only the faces asked), a floor or roof by face not on the
    mass's top, or update_by_face not rebuilding them after the mass changes while keeping a roof's slope."""
    sc.cmds(
        *LEVELS,
        BLOCK,
        'wall_by_face {"mass": 100004, "faces": [0, 2], "type": "Exterior - 300mm"}',
        'WB {"mass": 100004, "faces": [1]}',
        'floor_by_face {"mass": 100004}',
        'roof_by_face {"mass": 100004, "slope": 20, "overhang": 400}',
        'modify {"id": 100004, "boundary": [[0,0],[12000,0],[12000,8000],[0,8000]], "height": 6500}',
        'UF {"mass": 100004}',
        "update_by_face {}",
        'elements {"category": "wall"}',
        'elements {"category": "roof"}',
    )
    sc.cmds(*LEVELS, BLOCK, 'wall_by_face {"mass": 100004, "faces": [7]}')
    sc.cmds(*LEVELS, 'wall_by_face {"mass": 100000}')
    assert sc.transcript() == sc.golden()


def test_mass_in_3d_glb_and_show_mass(sc):
    """CATCHES: a mass not drawn see-through in 3D, show_mass not toggling the category in a view (or not as `show`
    says), masses missing from the glTF export, or a glTF written of a 3D view whose masses are all hidden."""
    sc.cmds(
        *LEVELS,
        BLOCK,
        'mass {"boundary": [[12000,0],[16000,0],[16000,4000],[12000,4000]], "top": [[13000,1000],[15000,1000],'
        '[15000,3000],[13000,3000]], "height": 5000}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "masses.png"}}',
        'save {"path": "masses.glb"}',
        "show_mass {}",
        "MH {}",
        'show_mass {"view": "Level 2", "show": false}',
        'show_mass {"view": "{3D}", "show": false}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "hidden.png"}}',
        'save {"path": "hidden.glb"}',
    )
    sc.file("masses.png")
    sc.file("hidden.png")
    sc.file("masses.glb")
    files(sc)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Shape editing and flipping
# ---------------------------------------------------------------------------------------------------------------------


def test_shape_editing_a_floor(sc):
    """CATCHES: edit_shape not folding a floor's top along split lines through points at their heights, add_point with an
    offset over the top as it is, add_split_line not making points at its ends, the shape read back wrongly, or
    reset_shape not making it flat."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
        "floor {}",
        'edit_shape {"id": 100006, "points": [{"at": [3000, 2000], "z": -50}], "lines": [{"a": [0,0], "b": [6000,4000]}]}',
        'edit_shape {"id": 100006}',
        'add_point {"id": 100006, "at": [1000, 1000], "offset": 20}',
        'add_point {"id": 100006, "at": [5000, 1000], "z": 3000, "absolute": true}',
        'add_split_line {"id": 100006, "a": [0, 4000], "b": [6000, 0]}',
        'edit_shape {"id": 100006}',
        'elements {"category": "floor"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "shaped.png"}}',
        'reset_shape {"id": 100006}',
        'edit_shape {"id": 100006}',
    )
    sc.file("shaped.png")
    assert sc.transcript() == sc.golden()


def test_shape_editing_a_flat_roof_and_errors(sc):
    """CATCHES: a flat roof's top not taking points (its underside following), a sloped roof or a wall accepted for
    shape editing, or a point outside the outline accepted."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
        "roof {}",
        'add_point {"id": 100006, "at": [3000, 2000], "z": 200}',
        'add_split_line {"id": 100006, "a": [0, 2000], "b": [6000, 2000]}',
        'edit_shape {"id": 100006}',
    )
    sc.cmds('wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}', 'roof {"slope": 30}',
            'add_point {"id": 100006, "at": [3000, 2000], "z": 200}')
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', 'edit_shape {"id": 100002}')
    sc.cmds('wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}', "floor {}",
            'add_point {"id": 100006, "at": [9000, 9000], "z": 10}')
    sc.cmds('wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}', "floor {}",
            'edit_shape {"id": 100006, "points": [{"at": [1000, 1000]}]}')
    assert sc.transcript() == sc.golden()


def test_flip_walls_keeps_openings(sc):
    """CATCHES: flip not turning a wall's exterior to the other side about its location line, moving its door, or
    accepting something that isn't a wall."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]], "type": "Exterior - 300mm", "location": "exterior-finish"}',
        'door {"at": [3000, 0]}',
        'elements {"category": "wall"}',
        'flip {"ids": [100002]}',
        'elements {"category": "wall"}',
        'elements {"category": "door"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "flipped.png"}}',
    )
    sc.cmds('wall {"points": [[0,0],[6000,0]]}', 'door {"at": [3000, 0]}', 'flip {"ids": [100003]}')
    sc.cmds('flip {"ids": []}')
    sc.file("flipped.png")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# More of the 3D view: every kind of solid, big models, layered and sloped slabs, sheets
# ---------------------------------------------------------------------------------------------------------------------

EVERYTHING = [
    'wall {"points": [[0,0],[10000,0],[10000,8000],[0,8000]], "closed": true, "type": "Exterior - 300mm"}',
    'type {"category": "floor", "name": "Layered 250", "layers": [{"function": "finish", "material": "Ceramic tile", '
    '"thickness": 20}, {"function": "structure", "material": "Concrete", "thickness": 200}, {"material": "Plaster", '
    '"thickness": 30}]}',
    'floor {"type": "Layered 250"}',
    'stair {"start": [1000, 1000], "end": [1000, 5000], "width": 1000, "railings": true}',
    'ramp {"start": [3000, 1000], "angle": 90, "width": 1200, "height": 600, "railings": true}',
    'railing {"path": [[5000, 1000], [5000, 6000]]}',
    'beam {"points": [[0, 4000], [10000, 4000]], "level": "Level 2"}',
    'pipe {"points": [[6000, 1000], [9000, 1000]], "offset": 500, "end_offset": 300}',
    'duct {"points": [[6000, 2000], [9000, 2000]], "offset": 2500}',
    'cable_tray {"points": [[6000, 3000], [9000, 3000]], "offset": 2600}',
    'structural_column {"at": [7000, 6000], "type": "Concrete Round 400"}',
    'footing {"at": [7000, 6000]}',
    'strip_footing {"points": [[0,0],[10000,0]]}',
    'ceiling {"point": [8000, 6000]}',
    'shaft {"boundary": [[8000,500],[9000,500],[9000,1500],[8000,1500]], "height": 3000}',
    'rebar {"points": [[6500, 5000, 100], [7500, 5000, 100]], "diameter": 12, "count": 3, "step": [0, 150, 0]}',
    'floor {"boundary": [[11000,0],[14000,0],[14000,3000],[11000,3000]], "slope": 5, "arrow": [[11000,0],[14000,0]]}',
    'room {"point": [8000, 7000], "name": "Store"}',
    'roof {"slope": 25, "gables": [1, 3], "overhang": 200}',
]


def test_3d_view_of_every_kind_of_solid(sc):
    """CATCHES: a 3D view or glTF that leaves out or misdraws stairs, ramps, railings, beams, sloped pipes, ducts, trays,
    columns, footings, rebar, ceilings, shafts cut through floors, layered and sloped floors, gabled roofs, or rooms
    shown as see-through solids."""
    sc.cmds(
        *EVERYTHING,
        'graphics {"view": "{3D}", "show": ["rooms"]}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "all.png"}}',
        'visual_style {"style": "wireframe"}',
        f'render {{"view": "{{3D}}", {SMALL}, "azimuth": 200, "elevation": 45, "path": "all-wire.png"}}',
        'save {"path": "all.glb"}',
    )
    sc.file("all.png")
    sc.file("all-wire.png")
    sc.file("all.glb", digest=False)
    assert sc.transcript() == sc.golden()


def test_3d_view_of_a_model_with_over_a_thousand_elements(sc):
    """CATCHES: a 3D render of a model of a thousand elements and more that draws otherwise than a small one would (the
    order of its triangles, its depth ties), or is refused."""
    import json as _json

    pts = [[i * 10, (i % 2) * 10] for i in range(1001)]
    sc.write("many.txt", "room_separator " + _json.dumps({"points": pts}) + "\n"
             + 'wall {"points": [[0,0],[6000,0],[6000,4000]]}\n'
             + f'render {{"view": "{{3D}}", {SMALL}, "path": "many.png"}}\n')
    p = sc.run(["run", "--script", "many.txt"], show=False)
    lines = p.stdout.decode().splitlines()
    sc.note(f"[exit {p.returncode}] {len(_json.loads(lines[0])['ids'])} separators")
    sc.note("\n".join(lines[1:]))
    sc.file("many.png")
    assert sc.transcript() == sc.golden()


def test_3d_view_placed_on_a_sheet_with_its_dimensions(sc):
    """CATCHES: the 3D view not placed on a sheet from the azimuth and elevation asked, or its 3D dimensions (with an arrow
    or dot tick type) not drawn on the sheet as in the view."""
    sc.cmds(
        *HOUSE,
        'dimension_type {"name": "Dot 3D", "like": "Diagonal - 2.5mm Arial", "tick": "dot", "font": "BIMCraft Lettering"}',
        'dimension_3d {"refs": [{"at": [0, 0, 0], "edge": [[0, 0, 0], [0, 0, 3000]]}, {"at": [6000, 0, 1500]}], '
        '"at": [3000, -900, 0], "type": "Dot 3D"}',
        'dimension_3d {"refs": [{"at": [6000, 0, 0]}, {"at": [6000, 4000, 0]}], "at": [7000, 2000, 0], '
        '"type": "Arrow - 2.5mm Arial"}',
        'sheet {"number": "A101", "name": "Axonometric", "size": "A4"}',
        'place {"sheet": "A101", "view": "{3D}", "azimuth": -60, "elevation": 35}',
        'render {"view": "A101", "path": "sheet.png"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "dims.png"}}',
    )
    sc.file("sheet.png")
    sc.file("dims.png")
    assert sc.transcript() == sc.golden()


def test_work_plane_more_errors(sc):
    """CATCHES: a work plane given a level and points at once, a surface facing nowhere ([0, 0, 0]) or far off, or an
    offset beyond any length being accepted."""
    for bad in [
        '{"level": "Level 1", "points": [[0, 0, 0], [1000, 0, 0], [0, 1000, 0]]}',
        '{"surface": {"point": [0, 0, 0], "normal": [0, 0, 0]}}',
        '{"surface": {"point": [1e12, 0, 0], "normal": [0, 0, 1]}}',
        '{"points": [[0, 0, 0], [1e12, 0, 0], [0, 1000, 0]]}',
        '{"level": "Level 1", "offset": 1e12}',
    ]:
        sc.cmds(f"work_plane {bad}")
    sc.cmds('work_plane {"level": "Level 2"}', 'delete {"ids": [100001]}', "work_plane {}")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# More of families: formulas, IFC classes, materials followed
# ---------------------------------------------------------------------------------------------------------------------


def _param(name, formula, kind="number"):
    return {"name": name, "kind": kind, "formula": formula}


def test_family_formulas_every_function_and_operator(sc):
    """CATCHES: a formula language that works out if, and, or, not, min, max, abs, sqrt, round, roundup, rounddown, the
    trigonometric functions in degrees, exp, ln, log, pi, powers, comparisons, exponents, unary signs or nested
    parentheses otherwise than the reference."""
    params = [
        {"name": "W", "kind": "length", "value": 1200},
        {"name": "D", "kind": "length", "value": 450},
        _param("A", "if(W > 1000, 4, 2)"),
        _param("B", "and(W > 1000, D < 500) + or(W < 0, D = 450) * 10 + not(W)"),
        _param("C", "min(W, D, 300) + max(1, 2, 3) + abs(-7)"),
        _param("E", "sqrt(16) + round(2.5) + roundup(2.1) + rounddown(2.9)"),
        _param("F", "sin(30) + cos(60) + tan(45)"),
        _param("G", "asin(0.5) + acos(0.5) + atan(1)"),
        _param("H", "exp(1) + ln(10) + log(1000)"),
        _param("I", "pi() * 2 ^ 3 ^ 0.5"),
        _param("J", "(W >= 1200) + (D <= 449) + (W < D) + (W > D) + -(-3) + +2"),
        _param("K", "1e3 + 2.5E-1 + .5"),
        _param("L", "((W - D) / (2 * (1 + 1))) - W / 4 * 2"),
        _param("M", "A + C * 2", "length"),
    ]
    fam = {"name": "Maths", "category": "generic", "parameters": params, "types": {"Wide": {}, "Narrow": {"W": 800}}}
    sc.cmds("family " + json.dumps(fam), 'family {"name": "Maths", "dry_run": true}')
    assert sc.transcript() == sc.golden()


def test_family_formula_errors(sc):
    """CATCHES: formulas that come back to themselves, call a function with the wrong number of values or one that isn't
    there, leave a parenthesis open, have something after their end, are empty, do sums with a material, or come to
    infinity, being accepted, or their errors not saying the character they stop at."""
    for i, formula in enumerate([
        "X + 1",
        "if(1, 2)",
        "frob(2)",
        "(1 + 2",
        "1 + 2)",
        " ",
        "Mat * 2",
        "1 / 0",
        "min()",
        "sqrt(1, 2)",
        "max(1 2)",
        "pi(3)",
        "2 * * 3",
        "@",
    ]):
        params = [{"name": "Mat", "kind": "material", "value": "Timber"}, _param("X", formula)]
        fam = {"name": f"Bad{i}", "parameters": params, "types": {"T": {}}}
        sc.cmds("family " + json.dumps(fam))
    sc.cmds("family " + json.dumps({"name": "Mat", "parameters": [{"name": "M", "kind": "material", "formula": "1"}],
                                    "types": {"T": {}}}))
    sc.cmds("family " + json.dumps({"name": "Name", "parameters": [{"name": "1st", "kind": "length"}], "types": {"T": {}}}))
    assert sc.transcript() == sc.golden()


def test_family_kinds_and_categories_in_ifc(sc):
    """CATCHES: components written to IFC under other classes or predefined types for their category and kind (a WC as
    a toilet pan, a floor drain as a floor trap, a bend, a rack as a proxy), or read back from IFC into other
    categories and kinds."""
    sc.cmds(
        'family {"name": "WC", "kind": "wc"}',
        'family {"name": "Floor Drain", "kind": "floor_waste"}',
        'family {"name": "Elbow 90", "kind": "bend"}',
        'family {"name": "Table", "kind": "wc"}',
    )
    placed = ["WC", "Floor Drain", "Elbow 90", "Table", "Base Cabinet", "Rack", "Outlet", "Switch", "Distribution Board",
              "Air Terminal", "Earthing Electrode", "Inspection Box", "Gate Valve", "Recessed Luminaire", "Data Outlet",
              "Voice Outlet", "Patch Panel"]
    args = ["run"]
    for f in ["WC", "Floor Drain", "Elbow 90"]:
        args += ["--cmd", f'family {{"name": "{f}", "kind": "{ {"WC": "wc", "Floor Drain": "floor_waste", "Elbow 90": "bend"}[f] }"}}']
    for i, f in enumerate(placed):
        args += ["--cmd", f'component {{"family": "{f}", "at": [{i * 1500}, 0]}}']
    args += ["--save", "fixtures.ifc"]
    sc.run(args, show=False)
    text = (sc.workdir / "fixtures.ifc").read_text()
    import re as _re

    products = [ln.split("=", 1)[1] for ln in text.splitlines()
                if _re.match(r"#\d+=IFC(FURNITURE|SANITARYTERMINAL|WASTETERMINAL|PIPEFITTING|VALVE|ELECTRICDISTRIBUTIONBOARD|"
                             r"OUTLET|SWITCHINGDEVICE|COMMUNICATIONSAPPLIANCE|BUILDINGELEMENTPROXY|LIGHTFIXTURE)\(", ln)]
    sc.note("\n".join(_re.sub(r"#\d+", "#", p) for p in products))
    sc.run(["convert", "fixtures.ifc", "back.bimcraft"])
    p = sc.run(["run", "back.bimcraft", "--cmd", "family {}"], show=False)
    sc.note(p.stdout.decode().splitlines()[-1])
    p = sc.run(["run", "back.bimcraft", "--cmd", 'family {"name": "WC"}'], show=False)
    fam = json.loads(p.stdout.decode().splitlines()[-1])
    sc.note(json.dumps({"category": fam["family"]["category"], "kind": fam["family"].get("kind")}))
    assert sc.transcript() == sc.golden()


def test_material_rename_followed_by_families_and_types(sc):
    """CATCHES: a material renamed without the families' parameters and forms and the wall types' layers that name it
    following, or deleting a material a family uses being allowed."""
    sc.cmds(
        'material {"name": "Timber", "rename": "Oak"}',
        'family {"name": "Table"}',
        'material {"name": "Brick", "rename": "Clay Brick"}',
        'library {"kind": "type:wall"}',
        "inspect {}",
    )
    assert sc.transcript() == sc.golden()


def test_material_texture_pictures_errors_and_reuse(sc):
    """CATCHES: a texture given an existing picture by id not sharing it, a picture over 1024 px a side not halved, a file
    that is neither PNG nor JPEG, a cut-short PNG, a broken PNG, a tile size out of range or a picture id on a drawn
    texture being accepted."""
    sc.write("wide.png", make_png(1100, 4, lambda x, y: (x % 256, 128, 255 - x % 256)))
    sc.write("small.png", make_png(4, 4, checker))
    sc.write("text.png", "not a picture at all")
    sc.write("short.png", b"\x89PNG\r\n\x1a\n\x00\x00")
    sc.write("broken.png", make_png(4, 4, checker)[:40])
    sc.run([
        "run",
        "--cmd", 'material {"name": "Wide", "texture": {"kind": "image", "path": "wide.png"}}',
        "--cmd", 'material {"name": "Small", "texture": {"kind": "image", "path": "small.png", "size": [100, 100]}}',
        "--save", "pics.bimcraft",
    ], show=False)
    p = sc.run(["info", "pics.bimcraft"], show=False)
    info = json.loads(p.stdout)
    sc.note(json.dumps({"images": info["images"], "Wide": info["materials"]["Wide"]}, sort_keys=True))
    image = info["materials"]["Small"]["texture"]["image"]
    sc.cmds(f'material {{"name": "Again", "texture": {{"kind": "image", "image": "{image}"}}}}',
            'library {"kind": "material", "name": "Again"}', pre=["pics.bimcraft"])
    for bad in [
        '{"name": "X", "texture": {"kind": "image", "path": "text.png"}}',
        '{"name": "X", "texture": {"kind": "image", "path": "short.png"}}',
        '{"name": "X", "texture": {"kind": "image", "path": "broken.png"}}',
        '{"name": "X", "texture": {"kind": "brick", "size": [0.001, 100]}}',
        '{"name": "X", "texture": {"kind": "brick", "image": "img-0000"}}',
        '{"name": "X", "texture": {"kind": "image", "image": "img-0000"}}',
        '{"name": "X", "texture": {"kind": "image"}}',
    ]:
        sc.cmds(f"material {bad}")
    assert sc.transcript() == sc.golden()


def test_favorites_default_folder_and_bad_files(sc):
    """CATCHES: favorites kept anywhere but XDG_CONFIG_HOME/bimcraft/favorites.json (else HOME/.config) when no path or
    BIMCRAFT_FAVORITES is given, or a favorites file that isn't one being read."""
    p = sc._run(["run", "--cmd", 'favorite {"action": "save", "kind": "material", "name": "Brick"}', "--cmd", "favorite {}"],
                env_overrides={"XDG_CONFIG_HOME": "cfg"})
    sc.note(f"[exit {p.returncode}]\n{p.stdout.decode()}{p.stderr.decode()}")
    p = sc._run(["run", "--cmd", 'favorite {"action": "save", "kind": "family", "name": "Desk"}', "--cmd", "favorite {}"])
    sc.note(f"[exit {p.returncode}]\n{p.stdout.decode()}{p.stderr.decode()}")
    sc.write("bad.json", '{"version": 1, "materials": {"": {"material": {"color": [1, 2, 3]}}}}')
    sc.write("junk.json", "[]")
    sc.cmds('favorite {"path": "bad.json"}')
    sc.cmds('favorite {"path": "junk.json"}')
    sc.cmds('favorite {"action": "delete", "kind": "family", "name": "Nope", "path": "fresh.json"}')
    sc.cmds('favorite {"action": "save", "kind": "chair", "name": "Desk", "path": "fresh.json"}')
    files(sc)
    sc.file("cfg/bimcraft/favorites.json", digest=True)
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# More of masses
# ---------------------------------------------------------------------------------------------------------------------


def test_update_to_face_refused_when_a_face_is_gone_or_leans(sc):
    """CATCHES: update_by_face rebuilding walls on faces a footprint no longer has, or on a mass that leans now, instead
    of refusing the lot and naming each wall."""
    sc.cmds(*LEVELS, BLOCK, "wall_by_face {\"mass\": 100004}",
            'modify {"id": 100004, "boundary": [[0,0],[10000,0],[5000,8000]]}', "update_by_face {}")
    sc.cmds(*LEVELS, BLOCK, "wall_by_face {\"mass\": 100004, \"faces\": [0]}",
            'modify {"id": 100004, "top": [[1000,0],[11000,0],[11000,8000],[1000,8000]]}', 'update_by_face {"ids": [100005]}')
    sc.cmds(*LEVELS, 'mass {"boundary": [[0,0],[4000,0],[4000,4000],[0,4000]], "lean": [1000, 0], "height": 3000}',
            'wall_by_face {"mass": 100004}')
    assert sc.transcript() == sc.golden()


def test_mass_deleted_copied_and_mirrored(sc):
    """CATCHES: what a deleted mass made keeping its marks, a copied wall by face keeping the mass's, or a mass mirrored in
    place not renumbering the faces its walls hold."""
    sc.cmds(
        *LEVELS,
        BLOCK,
        'wall_by_face {"mass": 100004, "faces": [0, 1]}',
        "mass_floors {}",
        'copy {"ids": [100005], "by": [0, -1000]}',
        'mirror {"ids": [100004], "axis": [[5000, 0], [5000, 8000]]}',
        'elements {"category": "wall"}',
        'delete {"ids": [100004]}',
        'elements {"category": "wall"}',
        'elements {"category": "floor", "limit": 1}',
    )
    assert sc.transcript() == sc.golden()


def test_lofted_masses_twisted_reversed_and_collapsing(sc):
    """CATCHES: a twisted loft's exact volume and area per level, or a top outline running the other way round or one
    that collapses the cross section part way up being accepted."""
    sc.cmds(
        *LEVELS,
        'mass {"boundary": [[0,0],[6000,0],[6000,6000],[0,6000]], "top": [[3000,-1000],[7000,3000],[3000,7000],'
        '[-1000,3000]], "height": 8000, "name": "Twist"}',
        "mass_floors {}",
        'schedule {"name": "Twist Floors", "category": "massfloors"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "twist.png"}}',
        'save {"path": "twist.glb"}',
    )
    sc.cmds('mass {"boundary": [[0,0],[6000,0],[6000,6000],[0,6000]], "top": [[0,6000],[6000,6000],[6000,0],[0,0]]}')
    sc.cmds('mass {"boundary": [[0,0],[6000,0],[6000,6000],[0,6000]], "top": [[6000,6000],[0,6000],[0,0],[6000,0]]}')
    sc.file("twist.png")
    sc.file("twist.glb")
    assert sc.transcript() == sc.golden()


def test_masses_in_plan_section_and_ifc(sc):
    """CATCHES: a mass not dashed in plan at the cut height, a section not outlining a lofted mass where its line cuts
    it, or a lofted mass not surviving IFC export and import with its footprint and top outline."""
    sc.cmds(
        *LEVELS,
        BLOCK,
        'mass {"boundary": [[12000,0],[18000,0],[18000,6000],[12000,6000]], "top": [[13000,1000],[17000,1000],'
        '[17000,5000],[13000,5000]], "height": 7000, "name": "Loft"}',
        'section {"start": [-1000, 3000], "end": [20000, 3000], "name": "Cut"}',
        'render {"view": "Cut", "width": 400, "height": 200, "path": "cut.png"}',
        'render {"view": "Level 1", "width": 400, "height": 200, "path": "plan.png"}',
        'save {"path": "masses.ifc"}',
    )
    sc.run(["run", "masses.ifc", "--cmd", 'elements {"category": "mass"}'])
    sc.file("cut.png")
    sc.file("plan.png")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Hosted families, form geometry, connectors and symbols
# ---------------------------------------------------------------------------------------------------------------------

DOOR_FAMILY = {
    "name": "Pivot Door",
    "category": "door",
    "operation": "sliding",
    "parameters": [
        {"name": "Width", "kind": "length", "value": 1000},
        {"name": "Height", "kind": "length", "value": 2200},
        {"name": "Leaf", "kind": "length", "formula": "Wall Thickness / 4"},
        {"name": "Glazed", "kind": "yesno", "value": False},
    ],
    "types": {"1000 x 2200": {}, "1200 x 2400": {"Width": 1200, "Height": 2400, "Glazed": True}},
    "forms": [
        {"plane": "xz", "profile": [["-Width / 2", 0], ["Width / 2", 0], ["Width / 2", "Height"], ["-Width / 2", "Height"]],
         "from": "-Leaf / 2", "to": "Leaf / 2", "material": "Timber"},
        {"plane": "xz", "profile": [[-200, 1200], [200, 1200], [200, 1800], [-200, 1800]], "from": -30, "to": 30,
         "material": "Glass", "visible": "Glazed"},
    ],
    "symbols": [
        {"line": [["-Width / 2", 0], ["-Width / 2", "-Width"]]},
        {"arc": {"centre": ["-Width / 2", 0], "radius": "Width", "from": 270, "to": 360}},
    ],
}


def test_door_and_window_families_in_walls(sc):
    """CATCHES: a door family's opening not sized by its Width and Height, its formulas not reading the wall's thickness,
    its operation not kept, a window family's Sill Height not its default sill, or the hosted openings not drawn in plan
    and 3D with their symbols and forms."""
    window = {
        "name": "Strip Window", "category": "window",
        "parameters": [{"name": "Width", "kind": "length", "value": 2000}, {"name": "Height", "kind": "length", "value": 600},
                       {"name": "Sill Height", "kind": "length", "value": 1500}],
        "types": {"Standard": {}},
        "forms": [{"plane": "xz", "profile": [["-Width / 2", 0], ["Width / 2", 0], ["Width / 2", "Height"],
                                               ["-Width / 2", "Height"]], "from": -10, "to": 10, "material": "Glass"}],
        "symbols": [{"line": [["-Width / 2", 0], ["Width / 2", 0]]}],
    }
    sc.cmds(
        "family " + json.dumps(DOOR_FAMILY),
        "family " + json.dumps(window),
        'wall {"points": [[0,0],[8000,0],[8000,5000],[0,5000]], "closed": true, "type": "Exterior - 300mm"}',
        'door {"at": [2000, 0], "family": "Pivot Door"}',
        'door {"at": [5000, 0], "family": "Pivot Door", "type": "1200 x 2400", "flip_hand": true}',
        'window {"at": [8000, 2500], "family": "Strip Window"}',
        'window {"at": [4000, 5000], "family": "Strip Window", "sill": 900}',
        'elements {"category": "door"}',
        'elements {"category": "window"}',
        'render {"view": "Level 1", "width": 400, "height": 260, "path": "plan.png"}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "3d.png"}}',
        f'render {{"family": "Pivot Door", "type": "1200 x 2400", "mode": "plan", "wall_thickness": 300, {SMALL}, '
        '"path": "door-plan.png"}',
    )
    sc.file("plan.png")
    sc.file("3d.png")
    sc.file("door-plan.png")
    assert sc.transcript() == sc.golden()


def test_hosted_family_warnings_and_wall_thickness(sc):
    """CATCHES: a door family's form wholly outside its opening, or thicker than the wall, not warned of (per type), a
    hosted family without symbols not warned, or `Wall Thickness` taken as a parameter's name or read by a family that
    isn't hosted."""
    fam = dict(DOOR_FAMILY, name="Odd Door", symbols=[], forms=[
        {"plane": "xz", "profile": [[3000, 0], [3500, 0], [3500, 500], [3000, 500]], "from": -10, "to": 10},
        {"plane": "xz", "profile": [[-100, 0], [100, 0], [100, 100], [-100, 100]], "from": -400, "to": 400},
    ])
    sc.cmds("family " + json.dumps(fam), 'family {"name": "Odd Door"}')
    sc.cmds("family " + json.dumps(dict(DOOR_FAMILY, name="Wally", parameters=DOOR_FAMILY["parameters"] + [
        {"name": "Wall Thickness", "kind": "length", "value": 10}])))
    sc.cmds("family " + json.dumps({"name": "Shelf", "parameters": [{"name": "D", "kind": "length",
                                                                       "formula": "Wall Thickness"}], "types": {"T": {}}}))
    sc.cmds('family {"name": "Gap", "category": "window", "parameters": [{"name": "Width", "kind": "number", "value": 1}, '
            '{"name": "Height", "kind": "length", "value": 1}], "types": {"T": {}}}')
    sc.cmds('family {"name": "Table", "category": "door"}')
    assert sc.transcript() == sc.golden()


def test_family_form_geometry_errors(sc):
    """CATCHES: forms that sweep nothing, have no area, cross themselves, a circle of no radius, a turn of over 360
    degrees, an axis of no length, a profile crossing or lying along its axis being accepted, or a placed component
    of such a type not refused."""
    base = {"parameters": [{"name": "R", "kind": "length", "value": 100}], "types": {"T": {}}}
    sq = [[0, 0], [100, 0], [100, 100], [0, 100]]
    for i, form in enumerate([
        {"plane": "xy", "profile": sq, "from": 100, "to": 100},
        {"plane": "xy", "profile": [[0, 0], [100, 0], [200, 0]], "to": 100},
        {"plane": "xy", "profile": [[0, 0], [300, 300], [300, 0], [0, 100]], "to": 100},
        {"plane": "xy", "circle": {"centre": [0, 0], "radius": "R - 100"}, "to": 100},
        {"plane": "xz", "profile": [[10, 0], [100, 0], [100, 100]], "axis": [[0, 0], [0, 100]], "from": 0, "to": 400},
        {"plane": "xz", "profile": [[10, 0], [100, 0], [100, 100]], "axis": [[0, 0], [0, 0]], "to": 90},
        {"plane": "xz", "profile": [[-50, 0], [100, 0], [100, 100]], "axis": [[0, 0], [0, 100]], "to": 90},
        {"plane": "xz", "profile": [[0, 0], [0, 50], [0, 100]], "axis": [[0, 0], [0, 100]], "to": 90},
        {"plane": "xy", "profile": sq, "to": 100, "visible": "Nope"},
        {"plane": "xy", "circle": {"centre": [0, 0], "radius": 10}, "profile": sq, "to": 100},
    ]):
        sc.cmds("family " + json.dumps(dict(base, name=f"F{i}", forms=[form])))
    # A part-turn about an upright axis, which is fine, and how its plan outline comes out.
    sc.cmds("family " + json.dumps(dict(base, name="Shade", forms=[
        {"plane": "xz", "profile": [[100, 0], [300, 0], [200, 400], [100, 400]], "axis": [[0, 0], [0, 400]], "from": 0,
         "to": 135, "material": "Fabric"},
        {"plane": "yz", "profile": [[0, 500], [100, 500], [100, 600]], "axis": [[0, 500], [100, 500]], "from": 0, "to": 360}])),
        f'render {{"family": "Shade", "mode": "plan", {SMALL}, "path": "shade-plan.png"}}',
        f'render {{"family": "Shade", {SMALL}, "path": "shade.png"}}')
    sc.file("shade-plan.png")
    sc.file("shade.png")
    assert sc.transcript() == sc.golden()


def test_family_connectors_and_their_checks(sc):
    """CATCHES: a device family's power connector (voltage, load per type by formula, power factor, poles) not kept or
    shown on its components, or a second power connector, a switch with a load, the wrong system, poles outside 1 to
    3, a voltage, power factor or load out of range being accepted."""
    good = {
        "name": "Heater", "category": "outlet",
        "parameters": [{"name": "Power", "kind": "number", "value": 1500}],
        "types": {"Small": {"Power": 1000}, "Big": {}},
        "connectors": [{"kind": "power", "system": "power-balanced", "poles": 1, "voltage": 220, "load_va": "Power * 1.1",
                        "power_factor": 0.9, "classification": "heating"}],
    }
    sc.cmds("family " + json.dumps(good), 'component {"family": "Heater", "type": "Small", "at": [0, 0]}',
            'elements {"category": "component"}', 'family {"name": "Heater"}')
    for i, connectors in enumerate([
        [{"kind": "power", "system": "power-balanced"}, {"kind": "power", "system": "power-balanced"}],
        [{"kind": "switch", "system": "switch", "load_va": 100}],
        [{"kind": "power", "system": "switch"}],
        [{"kind": "switch", "system": "power-balanced"}],
        [{"kind": "power", "system": "power-balanced", "poles": 4}],
        [{"kind": "power", "system": "power-balanced", "voltage": 0}],
        [{"kind": "power", "system": "power-balanced", "voltage": 220, "power_factor": 1.5}],
        [{"kind": "power", "system": "power-balanced", "voltage": 220, "load_va": -5}],
        [{"kind": "power", "system": "power-unbalanced", "poles": 3, "load_va": [100, 200]}],
    ]):
        sc.cmds("family " + json.dumps({"name": f"C{i}", "category": "outlet", "types": {"T": {}}, "connectors": connectors}))
    assert sc.transcript() == sc.golden()


def test_family_symbols_patched_deleted_and_checked(sc):
    """CATCHES: a symbol patched by GUID losing its place or id, delete_symbol removing another, dry-run of a delete
    deleting, or a label with an unclosed brace, no text, an arc of no radius or a line of one point being accepted."""
    marker = {
        "name": "Tag", "category": "generic", "parameters": [{"name": "N", "kind": "number", "value": 2}],
        "types": {"Standard": {}},
        "symbols": [{"line": [[0, 0], [100, 0]]}, {"text": {"at": [0, 50], "height": 50, "value": "T{N}"}},
                    {"dot": {"centre": [0, 0], "radius": 10}}],
    }
    p = sc.run(["run", "--cmd", "family " + json.dumps(marker), "--cmd", 'family {"name": "Tag"}'], show=False)
    read = json.loads(p.stdout.decode().splitlines()[-1])
    guid = read["family"]["symbols"][1]["guid"]
    first = read["family"]["symbols"][0]["id"]
    sc.cmds(
        "family " + json.dumps(marker),
        'family {"name": "Tag", "symbol": {"id": %d, "line": [[0, 0], [0, 100]], "visible": "N > 1"}}' % first,
        'family {"name": "Tag", "delete_symbol": [%d], "dry_run": true}' % first,
        'family {"name": "Tag", "delete": true, "dry_run": true}',
        'family {"name": "Tag", "save": "tag.json", "dry_run": true}',
        'family {"name": "Tag"}',
    )
    sc.note(f"(a symbol's GUID is made anew in every project: {len(guid)} characters)")
    for i, symbol in enumerate([
        {"text": {"at": [0, 0], "height": 50, "value": "{N"}},
        {"text": {"at": [0, 0], "height": 50, "value": "  "}},
        {"text": {"at": [0, 0], "height": 0, "value": "A"}},
        {"arc": {"centre": [0, 0], "radius": 0, "to": 90}},
        {"line": [[0, 0]]},
        {"line": [[0, 0], [1, 1]], "dot": {"centre": [0, 0], "radius": 1}},
    ]):
        sc.cmds("family " + json.dumps(dict(marker, name=f"S{i}", symbols=[symbol])))
    sc.cmds("family " + json.dumps(marker), 'family {"name": "Tag", "delete_symbol": [123]}')
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# Shaped slabs over a variable layer
# ---------------------------------------------------------------------------------------------------------------------


def test_shaped_floor_and_roof_over_a_variable_layer(sc):
    """CATCHES: a shaped slab whose variable layer doesn't take up the difference (its underside staying level and the
    layers under it whole), a point set lower than the variable layer allows being accepted, or the layers drawn wrongly
    in 3D, a section and glTF."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
        'type {"category": "floor", "name": "Screed on Slab", "layers": [{"function": "finish", "material": "Ceramic tile", '
        '"thickness": 10}, {"material": "Screed", "thickness": 60, "variable": true}, {"function": "structure", '
        '"material": "Concrete", "thickness": 150}]}',
        'type {"category": "roof", "name": "Insulated Flat", "layers": [{"material": "Membrane", "thickness": 10}, '
        '{"material": "Insulation", "thickness": 100, "variable": true}, {"function": "structure", "material": "Concrete", '
        '"thickness": 200}]}',
        'floor {"type": "Screed on Slab"}',
        'roof {"type": "Insulated Flat", "overhang": 0, "slope": 0}',
        'edit_shape {"id": 100006, "points": [{"at": [3000, 2000], "z": -40}]}',
        'add_point {"id": 100007, "at": [3000, 2000], "z": 80}',
        'elements {"category": "floor"}',
        'elements {"category": "roof"}',
        'section {"start": [-500, 2000], "end": [6500, 2000]}',
        'render {"view": "Section 1", "width": 400, "height": 200, "path": "section.png"}',
        f'render {{"view": "{{3D}}", {SMALL}, "elevation": 10, "path": "slab3d.png"}}',
        'save {"path": "slabs.glb"}',
    )
    sc.cmds(
        'wall {"points": [[0,0],[6000,0],[6000,4000],[0,4000]], "closed": true}',
        'type {"category": "floor", "name": "Screed on Slab", "layers": [{"material": "Screed", "thickness": 60, '
        '"variable": true}, {"function": "structure", "material": "Concrete", "thickness": 150}]}',
        'floor {"type": "Screed on Slab"}',
        'add_point {"id": 100006, "at": [3000, 2000], "z": -100}',
    )
    sc.cmds(
        'type {"category": "floor", "name": "Two Variable", "layers": [{"material": "Screed", "thickness": 60, '
        '"variable": true}, {"material": "Concrete", "thickness": 150, "variable": true}]}'
    )
    sc.file("section.png")
    sc.file("slab3d.png")
    sc.file("slabs.glb")
    assert sc.transcript() == sc.golden()


# ---------------------------------------------------------------------------------------------------------------------
# The refusals left: what each command says when given what it can't take
# ---------------------------------------------------------------------------------------------------------------------


def test_mass_command_refusals(sc):
    """CATCHES: a mass given both `top` and `lean`, mass_floors with no mass, show_mass with a `show` that is no boolean,
    wall_by_face with faces that aren't a list or a face that leans, update_by_face given both ids and a mass or an
    element not made by face being accepted; or a clockwise footprint not turned counter-clockwise with its top."""
    sc.cmds(
        *LEVELS,
        'mass {"boundary": [[0,8000],[10000,8000],[10000,0],[0,0]], "top": [[1000,7000],[9000,7000],[9000,1000],[1000,1000]], '
        '"height": 5000}',
        'elements {"category": "mass"}',
    )
    for bad in [
        'mass {"boundary": [[0,0],[1000,0],[1000,1000]], "top": [[0,0],[1000,0],[1000,1000]], "lean": [10, 0]}',
        "mass_floors {}",
        'show_mass {"show": "yes"}',
    ]:
        sc.cmds(bad)
    sc.cmds(*LEVELS, BLOCK, 'wall_by_face {"mass": 100004, "faces": 2}')
    sc.cmds(*LEVELS, 'mass {"boundary": [[0,0],[4000,0],[4000,4000],[0,4000]], "top": [[0,0],[4000,0],[4000,3000],'
                     '[0,3000]], "height": 3000}', 'wall_by_face {"mass": 100004, "faces": [0, 2]}')
    sc.cmds(*LEVELS, BLOCK, 'wall_by_face {"mass": 100004, "faces": [0]}', 'update_by_face {"mass": 100004, "ids": [100005]}')
    sc.cmds(*LEVELS, BLOCK, 'wall {"points": [[0, 0], [1000, 0]]}', 'update_by_face {"ids": [100005]}')
    assert sc.transcript() == sc.golden()


def test_material_and_paint_refusals(sc):
    """CATCHES: a material's cut taking a fill pattern by name not kept, a texture size of one number not squared, or a
    texture that is no object, an unknown texture key, a texture without a kind, an empty rename, paint without a
    material, with a material that is no name, or on an element with no faces being accepted."""
    sc.cmds(
        'material {"name": "Hatched", "cut": "Diagonal Up", "surface": "Tile 300"}',
        'material {"name": "Hatched", "texture": {"kind": "tile", "size": 250}}',
        'library {"kind": "material", "name": "Hatched"}',
    )
    for bad in [
        'material {"name": "X", "texture": 5}',
        'material {"name": "X", "texture": {"kind": "tile", "colour": "red"}}',
        'material {"name": "X", "texture": {"size": [10, 10]}}',
        'material {"name": "Brick", "rename": "  "}',
        'material {"name": "X", "surface": "Nope Pattern"}',
    ]:
        sc.cmds(bad)
    sc.cmds(*HOUSE[:1], 'paint {"id": 100002}')
    sc.cmds(*HOUSE[:1], 'paint {"id": 100002, "material": 7}')
    sc.cmds(*HOUSE[:1], 'grid {"start": [0, -1000], "end": [6000, -1000]}', 'paint {"id": 100006, "material": "Timber"}')
    assert sc.transcript() == sc.golden()


def test_family_and_component_refusals(sc):
    """CATCHES: family parameters named as a mass's or a phase's reserved names, an empty rename, a form patch that is
    no object or names no id, a dry run of a family file loading it, component params that are no object, or a
    favorite family loaded over one the project has, being accepted."""
    sc.run(["run", "--cmd", PLINTH, "--cmd", 'family {"name": "Plinth", "save": "plinth.json"}'], show=False)
    sc.cmds('family {"path": "plinth.json", "dry_run": true}', "family {}")
    for bad in [
        '{"name": "M", "parameters": [{"name": "Mass Face", "kind": "length"}], "types": {"T": {}}}',
        '{"name": "P", "parameters": [{"name": "Phase Created", "kind": "length"}], "types": {"T": {}}}',
        '{"name": "Table", "rename": " "}',
        '{"name": "Table", "form": 5}',
        '{"name": "Table", "form": {"radius": 5}}',
        '{"name": "Table", "delete_form": [true]}',
        '{"name": "Table", "form": {"guid": "00000000-0000-4000-8000-000000000000", "to": 5}}',
    ]:
        sc.cmds(f"family {bad}")
    sc.cmds('component {"family": "Table", "at": [0, 0], "params": [1, 2]}')
    sc.cmds(
        'favorite {"action": "save", "kind": "family", "name": "Table", "path": "fav.json"}',
        'favorite {"action": "load", "kind": "family", "name": "Table", "path": "fav.json"}',
    )
    sc.cmds(
        'favorite {"action": "save", "kind": "family", "name": "Table", "path": "fav.json"}',
        'favorite {"action": "load", "kind": "family", "name": "Table", "replace": true, "path": "fav.json"}',
        'favorite {"action": "load", "kind": "family", "name": "Table", "as": "Table 2", "path": "fav.json"}',
    )
    assert sc.transcript() == sc.golden()


def test_3d_view_commands_on_camera_views_and_by_id(sc):
    """CATCHES: perspective, section boxes, display options, work planes and 3D dimensions not reaching a camera view by
    its name or id, the default 3D view not made by a camera given to it, render by a 3D view's id, or an unusable eye
    elevation accepted."""
    sc.cmds(
        *HOUSE,
        'camera {"view": "{3D}", "eye": [-6000, -6000, 4000], "target": [3000, 2000, 1000]}',
        'camera {"eye": [12000, -3000, 1600], "target": [3000, 2000, 1500], "name": "East"}',
        'perspective {"view": "East", "lens": 28}',
        'perspective {"view": 100011, "on": false}',
        'section_box {"view": "East", "min": [0, 0, 0], "max": [6000, 4000, 2000]}',
        'graphic_display_options {"view": "East", "edges": false}',
        'work_plane {"view": "East", "level": "Level 2"}',
        'visual_style {"view": "East", "style": "hidden_line"}',
        'dimension_3d {"view": "East", "refs": [{"at": [0, 0, 0]}, {"at": [0, 4000, 0]}], "at": [-500, 2000, 0]}',
        f'render {{"view": 100011, {SMALL}, "path": "east.png"}}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "default.png"}}',
    )
    sc.cmds(*HOUSE, 'perspective {}', f'render {{"view": "{{3D}}", {SMALL}, "eye_elevation": 1e12}}')
    sc.cmds(*HOUSE, 'perspective {"view": "Level 1"}')
    sc.cmds(*HOUSE, 'dimension_3d {"view": "Level 1", "refs": [{"at": [0, 0, 0]}, {"at": [1, 0, 0]}], "at": [0, 0, 0]}')
    sc.cmds(*HOUSE, 'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [1000, 0, 0]}]}')
    sc.cmds(*HOUSE, 'dimension_3d {"refs": [{"at": [0, 0, 1e12]}, {"at": [1000, 0, 0]}], "at": [0, 0, 0]}')
    sc.cmds(*HOUSE, 'dimension_3d {"refs": [{"point": [0, 0, 0]}, {"at": [1000, 0, 0]}], "at": [0, 0, 0]}')
    sc.file("east.png")
    sc.file("default.png")
    assert sc.transcript() == sc.golden()


def test_flip_keeps_dimensions_on_the_same_lines(sc):
    """CATCHES: flipping a wall leaving a dimension to its faces, ends and its door's jambs on the wrong side, or the
    dimension's length changing."""
    sc.cmds(
        'wall {"points": [[0,0],[6000,0]], "type": "Exterior - 300mm"}',
        'door {"at": [3000, 0]}',
        'dimension {"refs": [{"id": 100002, "face": "left", "point": "start"}, {"id": 100003, "face": "start"}, '
        '{"id": 100002, "point": "end"}], "at": [0, -1500]}',
        'elements {"category": "dimension"}',
        'flip {"ids": [100002]}',
        'elements {"category": "dimension"}',
    )
    assert sc.transcript() == sc.golden()


def test_point_cloud_drawn_in_the_3d_view_and_cut_by_a_section_box(sc):
    """CATCHES: a point cloud's points not drawn in the 3D view in their own colours beside the model, a section box not
    cutting them away like the model's surfaces, or the cloud left out of the glTF it isn't part of."""
    rows = []
    for i in range(30):
        for j in range(30):
            rows.append(f"{i * 0.1:.2f} {j * 0.1:.2f} {((i + j) % 7) * 0.05:.2f} {i * 8} {j * 8} 200")
    sc.write("scan.xyz", "\n".join(rows) + "\n")
    sc.cmds(
        'wall {"points": [[0, 0], [6000, 0]]}',
        'point_cloud {"path": "scan.xyz", "at": [3000, 2000], "angle": 30}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "cloud.png"}}',
        'section_box {"min": [0, -500, -100], "max": [3200, 4000, 3000]}',
        f'render {{"view": "{{3D}}", {SMALL}, "path": "cloud-cut.png"}}',
        'save {"path": "cloud.glb"}',
    )
    sc.file("cloud.png")
    sc.file("cloud-cut.png")
    sc.file("cloud.glb")
    assert sc.transcript() == sc.golden()
