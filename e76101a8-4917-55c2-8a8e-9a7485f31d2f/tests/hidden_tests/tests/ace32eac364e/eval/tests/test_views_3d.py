"""3D views: `visual_style`, `section_box`, `perspective`, `graphic_display_options`, `camera`, `work_plane`,
`dimension_3d`, `render` of 3D views, and the scene exported as glTF (`--save x.glb`)."""

import pytest
from conftest import glb_summary, png_pixels

BOX = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}\n'
# A house with one of most things in it, and a mass beside it.
RICH = """wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true, "type": "Exterior - 300mm"}
wall {"points": [[5000, 0], [5000, 6000]], "type": "Interior - 100mm"}
door {"at": [2000, 0]}
window {"at": [8000, 3000]}
floor {"boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}
roof {}
column {"at": [3000, 3000]}
structural_column {"at": [6500, 1500]}
beam {"points": [[500, 500], [4500, 500]], "level": "Level 2"}
stair {"start": [1000, 1000], "angle": 90, "width": 900}
component {"family": "Chair", "at": [6500, 4000]}
component {"family": "Table", "at": [6500, 3000]}
pipe {"points": [[500, 5500], [4500, 5500]], "offset": 2500}
duct {"points": [[5500, 5500], [7500, 5500]], "offset": 2600}
ceiling {"point": [6500, 3000]}
room {"point": [2500, 3000], "name": "Living"}
mass {"boundary": [[9000, 0], [12000, 0], [12000, 3000], [9000, 3000]], "height": 4000}
railing {"host": 100014}
door {"at": [5000, 4500], "family": "Double Door"}
ramp {"start": [9500, 4500], "angle": 0, "height": 500}
mass {"boundary": [[13000, 0], [15000, 0], [15000, 2000], [13000, 2000]], "top": [[13500, 500], [14500, 500], [14500, 1500], [13500, 1500]], "height": 3000}
"""
OPEN_UP = ('graphics {"view": "{3D}", "show": ["rooms"], "hide": ["roofs", "ceilings"], "categories": {"walls": {"transparency": 30}}, '
           '"elements": {"100012": {"projection": {"color": [200, 0, 0], "fill": [0, 0, 200]}}, "100021": {"halftone": true}}}\n')
HOUSE = BOX + """door {"at": [2000, 0]}
window {"at": [8000, 3000]}
floor {"boundary": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]}
"""


def _run(run, workdir, script, *extra):
    (workdir / "script.txt").write_text(script)
    return run(["run", "--script", "script.txt", *extra])


def _cmds(cmds):
    args = []
    for c in cmds:
        args += ["--cmd", c]
    return args


CASES = {
    # Visual style: reading makes nothing, setting makes the default 3D view, any case, undo and redo.
    "visual_style": (BOX, [
        "visual_style {}",
        'elements {"category": "view3d"}',
        'visual_style {"style": "wireframe"}',
        'visual_style {"style": "Hidden Line", "view": "{3D}"}',
        'visual_style {"style": "HIDDENLINE", "view": 100006}',
        'visual_style {"view": "3D"}',
        'graphics {"view": "{3D}", "hide": ["doors"]}',
        "undo", "undo",
        "visual_style {}",
        "redo", "redo",
        'visual_style {"style": "shaded"}',
        'elements {"category": "view3d"}',
    ]),
    "visual_style_unknown": (BOX, ['visual_style {"style": "x-ray"}']),
    "visual_style_number": (BOX, ['visual_style {"style": 7}']),
    "visual_style_of_a_plan": (BOX, ['visual_style {"style": "shaded", "view": 100000}']),
    "visual_style_of_a_wall": (BOX, ['visual_style {"style": "shaded", "view": 100002}']),
    # Section box: fitted round the model, set, turned off keeping its extents, a corner changed alone.
    "section_box": (BOX, [
        "section_box {}",
        'section_box {"min": [0, 0, 0], "max": [4000, 3000, 2000]}',
        'section_box {"on": false}',
        'section_box {"max": [5000, 3000, 2000]}',
        'section_box {"view": "{3D}", "on": true, "min": [-100, -100, -100]}',
        'elements {"category": "view3d"}',
    ]),
    "section_box_of_nothing": ("", ["section_box {}"]),
    "section_box_of_a_plan": (BOX, ['section_box {"view": "Level 1"}']),
    "section_box_bad_corner": (BOX, ['section_box {"min": [0, 0], "max": [1000, 1000, 1000]}']),
    "section_box_on_not_a_flag": (BOX, ['section_box {"on": "yes"}']),
    "section_box_too_thin": (BOX, ['section_box {"min": [0, 0, 0], "max": [5, 1000, 1000]}']),
    "section_box_inside_out": (BOX, ['section_box {"min": [1000, 0, 0], "max": [0, 1000, 1000]}']),
    # Perspective.
    "perspective": (BOX, [
        "perspective {}",
        'perspective {"lens": 50}',
        'perspective {"on": false}',
        'perspective {"on": true}',
        'perspective {"view": "{3D}", "lens": 600}',
        'elements {"category": "view3d"}',
    ]),
    "perspective_lens_too_short": (BOX, ['perspective {"lens": 5}']),
    "perspective_lens_too_long": (BOX, ['perspective {"lens": 601}']),
    "perspective_on_not_a_flag": (BOX, ['perspective {"on": 1}']),
    "perspective_of_a_section": (BOX + 'section {"start": [0, 3000], "end": [8000, 3000]}\n', ['perspective {"view": "Section 1"}']),
    # Graphic Display Options.
    "graphic_display_options": (BOX, [
        "graphic_display_options {}",
        'elements {"category": "view3d"}',
        'graphic_display_options {"edges": false, "silhouette": 3, "ambient_shadows": true}',
        'graphic_display_options {"silhouette": 0}',
        "GD {}",
        'graphic_display_options {"edges": true, "ambient_shadows": false, "silhouette": 10}',
        'elements {"category": "view3d"}',
    ]),
    "silhouette_too_wide": (BOX, ['graphic_display_options {"silhouette": 11}']),
    "silhouette_not_whole": (BOX, ['graphic_display_options {"silhouette": 1.5}']),
    "silhouette_negative": (BOX, ['graphic_display_options {"silhouette": -1}']),
    "edges_not_a_flag": (BOX, ['graphic_display_options {"edges": "no"}']),
    "display_options_of_a_plan": (BOX, ['graphic_display_options {"view": "Level 1", "edges": false}']),
    # Cameras.
    "cameras": (BOX, [
        'camera {"eye": [-5000, -4000, 1600], "target": [4000, 3000, 1200]}',
        'camera {"eye": [-5000, -4000, 1600], "target": [4000, 3000, 1200], "lens": 24, "name": "Corner"}',
        'camera {"eye": [9000, 9000, 5000], "target": [4000, 3000, 0]}',
        'camera {"view": "Camera 1", "lens": 50}',
        'camera {"view": 100006, "eye": [-6000, -4000, 1700]}',
        'camera {"view": "Camera 1"}',
        'camera {"view": "{3D}"}',
        'camera {"view": "{3D}", "eye": [0, -9000, 2000], "target": [4000, 3000, 1000]}',
        'perspective {"view": "Corner", "on": false}',
        'camera {"view": "Corner"}',
        'elements {"category": "view3d"}',
    ]),
    "camera_eye_on_target": (BOX, ['camera {"eye": [1000, 1000, 1000], "target": [1000, 1000, 1000]}']),
    "camera_lens_too_short": (BOX, ['camera {"eye": [0, 0, 1000], "target": [1000, 1000, 1000], "lens": 5}']),
    "camera_without_target": (BOX, ['camera {"eye": [0, 0, 1000]}']),
    "camera_bad_eye": (BOX, ['camera {"eye": [0, 0], "target": [1000, 1000, 1000]}']),
    "camera_lens_alone_on_a_view_without_one": (BOX, ['camera {"view": "{3D}", "lens": 50}']),
    "camera_on_a_plan": (BOX, ['camera {"view": "Level 1", "eye": [0, 0, 1000], "target": [1000, 1000, 1000]}']),
    "camera_name_taken": (BOX, ['camera {"eye": [0, 0, 1000], "target": [1000, 1000, 1000], "name": "Level 1"}']),
    # Work planes.
    "work_plane": (BOX, [
        "work_plane {}",
        'work_plane {"level": "Level 2", "offset": 500}',
        'work_plane {"offset": 200}',
        'work_plane {"points": [[0, 0, 0], [1000, 0, 0], [0, 1000, 1000]]}',
        'work_plane {"points": [[0, 0, 0], [1000, 0, 0], [0, 0, 1000]]}',
        'work_plane {"surface": {"point": [0, 3000, 1500], "normal": [-1, 0, 0]}, "offset": 100}',
        'work_plane {"level": 100000}',
        'elements {"category": "view3d"}',
        "work_plane {}",
        'work_plane {"view": "{3D}"}',
    ]),
    "work_plane_level_deleted": (BOX + 'level {"elevation": 6000, "name": "Roof"}\nwork_plane {"level": "Roof"}\n', [
        'delete {"ids": [100006]}',
        "work_plane {}",
    ]),
    "work_plane_points_in_a_line": (BOX, ['work_plane {"points": [[0, 0, 0], [1000, 0, 0], [2000, 0, 0]]}']),
    "work_plane_two_points": (BOX, ['work_plane {"points": [[0, 0, 0], [1000, 0, 0]]}']),
    "work_plane_unknown_key": (BOX, ['work_plane {"plane": "Level 1"}']),
    "work_plane_bad_surface": (BOX, ['work_plane {"surface": {"point": [0, 0, 0]}}']),
    "work_plane_surface_facing_nowhere": (BOX, ['work_plane {"surface": {"point": [0, 0, 0], "normal": [0, 0, 0]}}']),
    "work_plane_unknown_level": (BOX, ['work_plane {"level": "Level 9"}']),
    "work_plane_of_a_plan": (BOX, ['work_plane {"view": "Level 1"}']),
    # Dimensions in 3D.
    "dimension_3d": (BOX, [
        'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [8000, 0, 0]}], "at": [4000, -1000, 0]}',
        'dimension_3d {"refs": [{"at": [0, 0, 3000], "edge": [[0, 0, 3000], [8000, 0, 3000]]}, '
        '{"at": [0, 6000, 3000], "edge": [[0, 6000, 3000], [8000, 6000, 3000]]}], "at": [9000, 3000, 3000]}',
        'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [0, 0, 3000], "edge": [[0, 0, 3000], [8000, 0, 3000]]}], '
        '"at": [-500, 0, 1500], "type": "Arrow - 2.5mm Arial"}',
        'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [3000, 4000, 1200]}], "at": [0, 0, 2000]}',
        'elements {"category": "dimension3d"}',
    ]),
    "dimension_3d_in_a_camera_view": (BOX + 'camera {"eye": [-5000, -4000, 1600], "target": [4000, 3000, 1200]}\n', [
        'dimension_3d {"view": "Camera 1", "refs": [{"at": [0, 0, 0]}, {"at": [0, 6000, 0]}], "at": [-1000, 3000, 0]}',
        'delete {"ids": [100006]}',
        'elements {"category": "dimension3d"}',
    ]),
    "dimension_3d_one_ref": (BOX, ['dimension_3d {"refs": [{"at": [0, 0, 0]}], "at": [0, 0, 0]}']),
    "dimension_3d_bad_ref": (BOX, ['dimension_3d {"refs": [{"at": [0, 0]}, {"at": [1000, 0, 0]}], "at": [0, 0, 0]}']),
    "dimension_3d_ref_too_far": (BOX, ['dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [1e12, 0, 0]}], "at": [0, 0, 0]}']),
    "dimension_3d_without_at": (BOX, ['dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [1000, 0, 0]}]}']),
    "dimension_3d_unknown_type": (BOX, ['dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [1000, 0, 0]}], "at": [0, -500, 0], '
                                        '"type": "Nope"}']),
    "dimension_3d_same_point": (BOX, ['dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [0, 0, 0]}], "at": [0, -500, 0]}']),
    "dimension_3d_in_a_plan": (BOX, ['dimension_3d {"view": "Level 1", "refs": [{"at": [0, 0, 0]}, {"at": [1000, 0, 0]}], '
                                     '"at": [0, 0, 0]}']),
    # A camera view named or numbered where a 3D view is asked for.
    "settings_of_a_camera_view": (BOX + 'camera {"eye": [-5000, 3000, 1600], "target": [4000, 3000, 1600]}\n', [
        'section_box {"view": "Camera 1"}',
        'perspective {"view": "Camera 1", "lens": 70}',
        'graphic_display_options {"view": 100006, "silhouette": 4}',
        'work_plane {"view": "Camera 1", "level": "Level 2"}',
        'visual_style {"view": "Camera 1", "style": "hidden_line"}',
        'graphics {"view": "Camera 1", "hide": ["levels"]}',
        'dimension_3d {"view": 100006, "refs": [{"at": [0, 0, 0]}, {"at": [0, 0, 3000]}], "at": [0, -500, 1500]}',
        'render {"view": 100006, "width": 64, "height": 48, "path": "c.png"}',
        'elements {"category": "view3d"}',
    ]),
    "work_plane_on_a_level_and_through_points": (BOX, ['work_plane {"level": "Level 1", "points": [[0, 0, 0], [1000, 0, 0], [0, 1000, 0]]}']),
    "work_plane_offset_too_far": (BOX, ['work_plane {"offset": 2e9}']),
    "work_plane_points_not_numbers": (BOX, ['work_plane {"points": [[0, 0, 0], [1000, 0, 0], [0, "y", 0]]}']),
    # A family drawn on its own, and what that refuses.
    "render_an_unknown_family": (BOX, ['render {"family": "Nope", "path": "f.png"}']),
    "render_a_familys_unknown_type": (BOX, ['render {"family": "Chair", "type": "Nope", "path": "f.png"}']),
    "render_a_family_in_an_unknown_mode": (BOX, ['render {"family": "Chair", "mode": "section", "path": "f.png"}']),
    "render_a_door_in_a_wall_too_thin": (BOX, ['render {"family": "Single Door", "wall_thickness": -5, "path": "f.png"}']),
    "render_a_mode_without_a_family": (BOX, ['render {"mode": "plan", "path": "f.svg"}']),
    "render_a_family_leaves_the_project_as_it_was": (BOX, [
        'render {"family": "Table", "type": "1600 x 900", "mode": "3d", "width": 64, "height": 48, "path": "t.png"}',
        'render {"family": "Casement Window", "mode": "elevation", "width": 64, "height": 48, "path": "w.png"}',
        'elements {"category": "window"}',
        "undo",
        "undo",
    ]),
    # What render refuses of a 3D view.
    "render_3d_as_svg": (BOX, ['render {"view": "{3D}", "path": "view.svg"}']),
    "render_raising_a_parallel_eye": (BOX, ['render {"view": "{3D}", "eye_elevation": 1600, "path": "x.png"}']),
    "render_raising_an_eye_too_far": (BOX + "perspective {}\n", ['render {"view": "{3D}", "eye_elevation": 1e12, "path": "x.png"}']),
    # glTF of nothing, or of nothing shown.
    "glb_of_nothing": ("", ['save {"path": "scene.glb"}']),
    "glb_of_everything_hidden": (BOX + 'graphics {"view": "{3D}", "hide": ["walls"]}\n', ['save {"path": "scene.glb"}']),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_3d_view_commands(run, workdir, golden, case):
    """CATCHES: a rewrite whose 3D view settings (visual style, section box, perspective, display options, cameras,
    work planes, 3D dimensions) differ from the reference's in their defaults, what they keep when a part is left out,
    when they make the default 3D view, what they reply, or how they word and refuse a bad request."""
    setup, cmds = CASES[case]
    r = _run(run, workdir, setup, *_cmds(cmds))
    golden.check_run(r, f"{case}.txt")


# Each: setup, the render command, the picture's file name.
RENDERS = {
    "shaded_default": (HOUSE, 'render {"view": "{3D}", "width": 240, "height": 160, "path": "v.png"}'),
    "wireframe_boxed_from_the_north_west": (
        HOUSE + 'visual_style {"style": "wireframe"}\nsection_box {"min": [-100, -100, -100], "max": [5000, 7000, 2000]}\n',
        'render {"view": "{3D}", "width": 240, "height": 160, "azimuth": 135, "elevation": 20, "path": "v.png"}'),
    "hidden_line_with_dimensions": (
        HOUSE + 'visual_style {"style": "hidden_line"}\n'
        + 'dimension_type {"name": "Dots", "like": "Diagonal - 2.5mm Arial", "tick": "dot"}\n'
        + 'dimension_type {"name": "Bare", "like": "Diagonal - 2.5mm Arial", "tick": "none"}\n'
        + 'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [8000, 0, 0]}], "at": [4000, -1500, 0]}\n'
        + 'dimension_3d {"refs": [{"at": [8000, 0, 0]}, {"at": [8000, 6000, 0]}], "at": [9500, 3000, 0], "type": "Dots"}\n'
        + 'dimension_3d {"refs": [{"at": [0, 6000, 0]}, {"at": [0, 6000, 3000]}], "at": [-1000, 6000, 1500], "type": "Arrow - 2.5mm Arial"}\n'
        + 'dimension_3d {"refs": [{"at": [0, 0, 3000]}, {"at": [8000, 6000, 3000]}], "at": [4000, 3000, 3500], "type": "Bare"}\n',
        'render {"view": "{3D}", "width": 240, "height": 160, "path": "v.png"}'),
    "everything_with_overrides_shadows_and_a_scan": (
        RICH + OPEN_UP + 'graphic_display_options {"silhouette": 2, "ambient_shadows": true}\n'
        + 'point_cloud {"path": "scan.pts", "at": [10000, 5000]}\n',
        'render {"view": "{3D}", "width": 320, "height": 240, "elevation": 45, "path": "v.png"}'),
    "a_scan_cut_by_the_section_box": (
        BOX + 'point_cloud {"path": "scan.pts", "at": [4000, 3000]}\n'
        + 'section_box {"min": [2500, 2500, -100], "max": [9000, 9000, 1000]}\n',
        'render {"view": "{3D}", "width": 200, "height": 150, "path": "v.png"}'),
    "from_inside_the_house": (
        RICH + OPEN_UP + 'camera {"eye": [2500, 3000, 1600], "target": [7000, 3000, 1600], "lens": 20, "name": "Inside"}\n',
        'render {"view": "Inside", "width": 240, "height": 160, "path": "v.png"}'),
    "a_section_through_everything": (
        RICH + 'section {"start": [2500, -1000], "end": [2500, 7000], "name": "Cut"}\n',
        'render {"view": "Cut", "width": 300, "height": 200, "path": "v.png"}'),
    "camera_raised_eye_with_silhouettes": (
        HOUSE + 'camera {"eye": [-5000, -4000, 1600], "target": [4000, 3000, 1200], "lens": 28}\n'
        + 'graphic_display_options {"view": "Camera 1", "silhouette": 2, "ambient_shadows": true}\n',
        'render {"view": "Camera 1", "width": 240, "height": 160, "eye_elevation": 4000, "path": "v.png"}'),
}


def _scan(workdir):
    """A small laser scan, as a PTS file: a strip of floor and of wall, 400 points in metres."""
    pts = []
    for i in range(20):
        for j in range(10):
            pts.append(f"{i * 0.2:.1f} {j * 0.2:.1f} 0.0 0 200 100 50")
            pts.append(f"{i * 0.2:.1f} 0.0 {j * 0.2:.1f} 0 50 100 200")
    (workdir / "scan.pts").write_text(f"{len(pts)}\n" + "\n".join(pts) + "\n")


@pytest.mark.parametrize("case", sorted(RENDERS))
def test_3d_render(run, workdir, golden, case):
    """CATCHES: a rewrite that draws the 3D view differently: its fit, its default direction (south-east, 30 degrees
    up), azimuth and elevation, the visual styles, the section box's cut, perspective through a camera's lens and a
    raised eye or from inside the model, silhouettes and shadows, overrides, a scan's points, and 3D dimensions painted
    over the picture; or replies differently."""
    _scan(workdir)
    setup, cmd = RENDERS[case]
    r = _run(run, workdir, setup, "--cmd", cmd)
    golden.check_run(r, f"render_{case}.txt")
    golden.check(png_pixels((workdir / "v.png").read_bytes()), f"render_{case}.png.txt")


def test_glb_of_a_house(run, workdir, golden):
    """CATCHES: a rewrite whose glTF scene differs: a node and mesh per element with its id, GUID and category, a
    primitive per colour, positions in metres with y up and north as -z, linear-light colours, shared vertices and
    the binary chunk's bytes; or whose save reply counts elements and triangles differently."""
    r = _run(run, workdir, HOUSE, "--save", "house.glb")
    golden.check_run(r, "glb_house.txt")
    golden.check(glb_summary((workdir / "house.glb").read_bytes()), "glb_house.glb.txt")


def test_glb_of_everything(run, workdir, golden):
    """CATCHES: a rewrite whose glTF scene of compound walls (a primitive per layer), roofs, columns, beams, stairs,
    railings, family components, runs, ceilings, rooms shown in 3D and a see-through mass differs from the reference's."""
    r = _run(run, workdir, RICH + OPEN_UP, "--save", "rich.glb")
    golden.check_run(r, "glb_rich.txt")
    golden.check(glb_summary((workdir / "rich.glb").read_bytes()), "glb_rich.glb.txt")


def test_glb_follows_what_the_3d_view_shows(run, workdir, golden):
    """CATCHES: a rewrite whose glTF ignores what the default 3D view hides, the colours and transparency it overrides,
    its phase, or that applies its section box (the export writes each shown element whole)."""
    script = HOUSE + (
        'modify {"id": 100002, "params": {"Phase Created": "New Construction"}}\n'
        'graphics {"view": "{3D}", "hide": ["doors"], "elements": {"100003": {"projection": {"fill": [200, 30, 30]}, '
        '"transparency": 50}}, "phase": "Existing"}\n'
        'section_box {"min": [0, 0, 0], "max": [1000, 1000, 1000]}\n')
    r = _run(run, workdir, script, "--save", "shown.glb")
    golden.check_run(r, "glb_shown.txt")
    golden.check(glb_summary((workdir / "shown.glb").read_bytes()), "glb_shown.glb.txt")


def test_convert_a_project_to_glb(run, workdir, golden):
    """CATCHES: a rewrite whose `convert` to .glb writes a different scene than `run --save` does for the same project."""
    r = _run(run, workdir, BOX, "--save", "p.bimcraft")
    assert r.returncode == 0, r.stderr
    r = run(["convert", "p.bimcraft", "p.glb"])
    golden.check_run(r, "convert_glb.txt")
    golden.check(glb_summary((workdir / "p.glb").read_bytes()), "convert_glb.glb.txt")


@pytest.mark.parametrize("family", ["Single Door", "Chair"])
def test_a_family_in_plan_on_its_own(run, workdir, golden, family):
    """CATCHES: a rewrite whose family preview in plan draws other symbols than the family's (a door in a wall of the
    thickness asked, its swing; furniture on a floor of its footprint), or touches the project."""
    r = _run(run, workdir, BOX, "--cmd",
             'render {"family": "%s", "mode": "plan", "wall_thickness": 300, "width": 160, "height": 120, "path": "f.svg"}' % family,
             "--cmd", 'elements {"category": "door"}')
    name = family.lower().replace(" ", "_")
    golden.check_run(r, f"family_plan_{name}.txt")
    golden.check((workdir / "f.svg").read_text(), f"family_plan_{name}.svg")
