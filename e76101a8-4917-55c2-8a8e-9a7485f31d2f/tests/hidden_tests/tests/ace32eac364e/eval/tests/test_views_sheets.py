"""Sections, elevations, sheets and what goes on them: `section`, `elevation`, `sheet`, `place`, `crop`,
`duplicate_view`, `scale`, `detail`, and `render` / `--save` of sections, elevations and sheets (PNG and PDF)."""

import pytest
from conftest import pdf_summary, png_pixels

# A box of four walls with a door, a window and a room.
HOUSE = """wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}
door {"at": [2000, 0]}
window {"at": [8000, 3000]}
room {"point": [4000, 3000], "name": "Hall"}
"""
SECTION = 'section {"start": [-1000, 3000], "end": [9000, 3000]}\n'


def _script(workdir, text, name="script.txt"):
    (workdir / name).write_text(text)
    return name


def _run(run, workdir, script, *extra):
    """`run --script` the setup, then the extra arguments (more --cmd values, --save…)."""
    return run(["run", "--script", _script(workdir, script), *extra])


# Each case: the setup script, then --cmd values run after it (the last one usually the one under test).
CASES = {
    # Sections and elevations, and how they are listed.
    "section_and_elevations": (HOUSE, [
        SECTION.strip(),
        'section {"start": [4000, -1000], "end": [4000, 7000], "depth": 1500, "name": "Cross"}',
        "elevation {}",
        'elevation {"at": [4000, -5000]}',
        'elevation {"facing": "east", "at": [12000, 3000]}',
        'elevation {"facing": "West"}',
        'elevation {"start": [0, 9000], "end": [8000, 9000], "depth": 2000, "name": "Back"}',
        'elevation {"start": [9000, -2000], "end": [-1000, -2000]}',
        'elements {"category": "section"}',
        'elements {"category": "elevation"}',
    ]),
    "section_named_like_an_elevation": (HOUSE + "elevation {}\n", ['section {"start": [0, 0], "end": [1000, 0], "name": "North"}']),
    "section_named_like_a_level": (HOUSE, ['section {"start": [0, 0], "end": [1000, 0], "name": "Level 1"}']),
    "section_without_end": (HOUSE, ['section {"start": [0, 0]}']),
    "section_with_no_length": (HOUSE, ['section {"start": [1000, 1000], "end": [1000, 1000]}']),
    "section_bad_point": (HOUSE, ['section {"start": [0, "x"], "end": [1000, 0]}']),
    "four_elevations_twice": (HOUSE + "elevation {}\n", ["elevation {}"]),
    "elevation_bad_facing": (HOUSE, ['elevation {"facing": "up"}']),
    "elevation_start_without_end": (HOUSE, ['elevation {"start": [0, 0]}']),
    "elevation_of_nothing": ("", ["elevation {}"]),
    # Sheets and placing views on them.
    "sheets_and_viewports": (HOUSE + SECTION, [
        "sheet {}",
        'sheet {"name": "Sections", "size": "a2"}',
        'sheet {"number": "S-1", "name": "Small", "size": "A4"}',
        'place {"sheet": "A101", "view": "Level 1"}',
        'place {"sheet": "A102", "view": "Section 1", "scale": 50, "at": [300, 200]}',
        'place {"sheet": 100010, "view": "Door Schedule"}',
        'place {"sheet": "S-1", "view": "{3D}", "azimuth": 30, "elevation": 20}',
        'place {"sheet": "Small", "view": "Level 2", "scale": 200}',
        'elements {"category": "viewport"}',
        'elements {"category": "sheet"}',
        'elements {"category": "view3d"}',
        'elements {"category": "schedule"}',
    ]),
    "sheet_bad_size": (HOUSE, ['sheet {"size": "B5"}']),
    "sheet_number_taken": (HOUSE + "sheet {}\n", ['sheet {"number": "A101"}']),
    "sheet_numbers_skip_the_taken": (HOUSE + 'sheet {"number": "A102"}\n', ["sheet {}", "sheet {}", 'elements {"category": "sheet"}']),
    "place_a_view_twice": (HOUSE + "sheet {}\nsheet {}\n" + 'place {"sheet": "A101", "view": "Level 1"}\n',
                           ['place {"sheet": "A102", "view": 100000}']),
    "place_the_3d_view_twice": (HOUSE + "sheet {}\nsheet {}\n" + 'place {"sheet": "A101", "view": "{3D}"}\n',
                                ['place {"sheet": "A102", "view": "{3D}"}']),
    "place_an_unknown_schedule": (HOUSE + "sheet {}\n", ['place {"sheet": "A101", "view": "Furniture Schedule"}']),
    "place_on_an_unknown_sheet": (HOUSE + "sheet {}\n", ['place {"sheet": "A999", "view": "Level 1"}']),
    "place_on_a_sheet_id_that_is_a_wall": (HOUSE + "sheet {}\n", ['place {"sheet": 100002, "view": "Level 1"}']),
    "place_a_wall": (HOUSE + "sheet {}\n", ['place {"sheet": "A101", "view": 100002}']),
    "place_without_view": (HOUSE + "sheet {}\n", ['place {"sheet": "A101"}']),
    "place_without_sheet": (HOUSE + "sheet {}\n", ['place {"view": "Level 1"}']),
    "place_takes_the_views_scale": (HOUSE + SECTION + 'scale {"view": "Level 1", "scale": 50}\nsheet {}\n', [
        'place {"sheet": "A101", "view": "Level 1"}',
        'place {"sheet": "A101", "view": "Section 1"}',
        'elements {"category": "viewport"}',
    ]),
    "place_in_feet_and_inches": (HOUSE + 'units {"length": "ft-in"}\nsheet {}\n', [
        'scale {"view": 100000}',
        'place {"sheet": "A101", "view": 100000}',
        'elements {"category": "viewport"}',
    ]),
    "deleting_views_and_sheets_takes_viewports": (HOUSE + SECTION + "sheet {}\n" + 'place {"sheet": "A101", "view": "Level 1"}\n'
                                                  + 'place {"sheet": "A101", "view": "Section 1"}\n', [
        'delete {"ids": [100009]}',
        'elements {"category": "viewport"}',
        'delete {"ids": [100010]}',
        'elements {"category": "viewport"}',
    ]),
    # Crop regions.
    "crop_plans_and_sections": (HOUSE + "sheet {}\n" + 'place {"sheet": "A101", "view": "Level 1"}\n', [
        'crop {"view": "Level 1", "region": [[-500, -500], [4000, 6500]]}',
        'elements {"category": "viewport"}',
        'crop {"view": "Level 1", "region": null}',
        'crop {"view": 100000}',
        SECTION.strip(),
        'text {"text": "Insulated", "at": [3000, 1000], "view": "Section 1"}',
        'crop {"view": "Section 1", "region": [[500, -200], [6000, 2500]]}',
        'elements {"category": "section"}',
        'elements {"category": "text"}',
        'crop {"view": "Section 1"}',
        'crop {"view": "Section 1", "region": null}',
    ]),
    "crop_corners_the_wrong_way": (HOUSE, ['crop {"view": 100000, "region": [[4000, 0], [0, 4000]]}']),
    "crop_section_corners_the_wrong_way": (HOUSE + SECTION, ['crop {"view": "Section 1", "region": [[4000, 0], [0, 4000]]}']),
    "crop_a_sheet": (HOUSE + "sheet {}\n", ['crop {"view": "A101"}']),
    "crop_three_corners": (HOUSE, ['crop {"view": 100000, "region": [[0, 0], [1, 1], [2, 2]]}']),
    "crop_an_empty_plan": (HOUSE, ['crop {"view": "Level 2"}']),
    "crop_an_unknown_view": (HOUSE, ['crop {"view": "Nowhere"}']),
    # Duplicate View.
    "duplicate_views": (HOUSE + 'text {"text": "Note", "at": [1000, 1000]}\n', [
        'duplicate_view {"view": "Level 1"}',
        'duplicate_view {"view": "Level 1", "mode": "detailing"}',
        'duplicate_view {"view": "Level 1", "mode": "dependent"}',
        'duplicate_view {"view": "Level 1 Copy 1", "name": "Furniture Plan"}',
        'elements {"category": "planview"}',
        'elements {"category": "text"}',
    ]),
    "duplicate_view_keeps_scale_and_graphics": (HOUSE + 'scale {"view": "Level 1", "scale": 50}\n'
                                                + 'graphics {"view": "Level 1", "hide": ["doors"]}\n', [
        'duplicate_view {"view": "Level 1"}',
        'scale {"view": "Level 1 Copy 1"}',
        'graphics {"view": "Level 1 Copy 1"}',
    ]),
    "duplicate_a_section": (HOUSE + SECTION, ['duplicate_view {"view": "Section 1"}']),
    "duplicate_view_bad_mode": (HOUSE, ['duplicate_view {"view": "Level 1", "mode": "twin"}']),
    "dependent_of_a_dependent": (HOUSE + 'duplicate_view {"view": "Level 1", "mode": "dependent"}\n',
                                 ['duplicate_view {"view": "Level 1 Dependent 1", "mode": "dependent"}']),
    "dependent_view_graphics_refused": (HOUSE + 'duplicate_view {"view": "Level 1", "mode": "dependent"}\n',
                                        ['graphics {"view": "Level 1 Dependent 1", "hide": ["walls"]}']),
    "dependent_view_scale_refused": (HOUSE + 'duplicate_view {"view": "Level 1", "mode": "dependent"}\n',
                                     ['scale {"view": "Level 1 Dependent 1", "scale": 50}']),
    "dependent_view_reads_its_parents_scale": (HOUSE + 'duplicate_view {"view": "Level 1", "mode": "dependent"}\n', [
        'scale {"view": "Level 1", "scale": 20}',
        'scale {"view": "Level 1 Dependent 1"}',
        'detail {"view": "Level 1 Dependent 1"}',
    ]),
    "duplicate_view_name_taken": (HOUSE + SECTION, ['duplicate_view {"view": "Level 1", "name": "Section 1"}']),
    # Scale and detail level.
    "scale_and_detail": (HOUSE + SECTION, [
        'scale {"view": "Level 1"}',
        'detail {"view": 100000}',
        'scale {"view": "Level 1", "scale": 50}',
        'detail {"view": 100000, "detail": "coarse"}',
        'scale {"view": "Section 1", "scale": 20.5}',
        'detail {"view": "Section 1", "detail": "Medium"}',
        'scale {"view": 100009}',
        'detail {"view": "Section 1"}',
        'scale {"view": 100000, "scale": 50}',
        "undo",
        'detail {"view": 100000}',
    ]),
    "scale_null": (HOUSE, ['scale {"view": 100000, "scale": null}']),
    "scale_zero": (HOUSE, ['scale {"view": 100000, "scale": 0}']),
    "scale_negative": (HOUSE, ['scale {"view": 100000, "scale": -100}']),
    "scale_too_large": (HOUSE, ['scale {"view": 100000, "scale": 1e9}']),
    "scale_as_text": (HOUSE, ['scale {"view": 100000, "scale": "1:100"}']),
    "scale_of_a_wall": (HOUSE, ['scale {"view": 100002, "scale": 100}']),
    "scale_of_the_3d_view": (HOUSE + 'visual_style {"style": "wireframe"}\n', ['scale {"view": "{3D}"}']),
    "detail_ultra": (HOUSE, ['detail {"view": 100000, "detail": "ultra"}']),
    "detail_number": (HOUSE, ['detail {"view": 100000, "detail": 3}']),
    "detail_of_a_wall": (HOUSE, ['detail {"view": 100002, "detail": "fine"}']),
    # What render says of sections, elevations and sheets it can't draw as asked.
    "render_section_as_svg": (HOUSE + SECTION, ['render {"view": "Section 1", "path": "s.svg"}']),
    "render_elevation_as_svg": (HOUSE + "elevation {}\n", ['render {"view": "North", "path": "n.svg"}']),
    "render_unknown_view": (HOUSE, ['render {"view": "Nowhere"}']),
    "save_pdf_without_sheets": (HOUSE, ['save {"path": "set.pdf"}']),
    "save_without_a_path": (HOUSE, ["save {}"]),
    "sheet_sizes": (HOUSE, [
        'sheet {"size": "A0"}',
        'sheet {"size": "a1", "name": "Big"}',
        'sheet {"size": " A4 "}',
        'elements {"category": "sheet"}',
    ]),
    "a_sheet_named_like_a_level_renders_the_level": (HOUSE + 'sheet {"name": "Level 1", "size": "A4"}\n', [
        'render {"view": "Level 1", "width": 100, "height": 80, "path": "plan.svg"}',
        'render {"view": 100009, "width": 100, "height": 80, "path": "sheet.png"}',
    ]),
    "crop_keeps_leaders_and_spots_in_place": (HOUSE + SECTION
                                              + 'text {"text": "Wall", "at": [3000, 1000], "view": "Section 1", "leader": [3500, 500]}\n'
                                              + 'spot {"at": [3000, 0], "view": "Section 1"}\n', [
        'crop {"view": "Section 1", "region": [[500, -200], [6000, 2500]]}',
        'elements {"category": "text"}',
        'elements {"category": "spot"}',
    ]),
    "duplicate_with_detailing_copies_the_annotation": (HOUSE
                                                       + 'dimension {"refs": [{"id": 100003}, {"id": 100005}], "at": [4000, 3000]}\n'
                                                       + 'tag {}\nspot {"at": [8000, 3000]}\n'
                                                       + 'detail_line {"points": [[0, -1000], [8000, -1000]]}\n'
                                                       + 'filled_region {"sketch": [[[1000, 1000], [2000, 1000]], [[2000, 1000], [2000, 2000]], '
                                                       + '[[2000, 2000], [1000, 2000]], [[1000, 2000], [1000, 1000]]]}\n'
                                                       + 'text {"text": "Note", "at": [1000, 5000]}\n', [
        'duplicate_view {"view": "Level 1", "mode": "detailing"}',
        'duplicate_view {"view": "Level 1", "mode": "duplicate"}',
        'duplicate_view {"view": "Level 1 Copy 1", "mode": "dependent"}',
        'elements {"category": "dimension"}',
        'elements {"category": "tag"}',
        'elements {"category": "spot"}',
        'elements {"category": "line"}',
        'elements {"category": "region"}',
        'delete {"ids": [100016]}',
        'elements {"category": "planview"}',
    ]),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_views_and_sheets(run, workdir, golden, case):
    """CATCHES: a rewrite whose sections, elevations, sheets, viewports, crops, duplicated views, scales or detail levels
    differ from the reference's in what they make (names, numbering, lines, looking directions, paper sizes, viewport
    places and sizes, crops), in what they reply, or in how they word and refuse a bad request."""
    setup, cmds = CASES[case]
    args = []
    for c in cmds:
        args += ["--cmd", c]
    r = _run(run, workdir, setup, *args)
    golden.check_run(r, f"{case}.txt")


def test_section_and_elevation_render_as_png(run, workdir, golden):
    """CATCHES: a rewrite that draws a section or an elevation differently (what it cuts and sees, its lines, its
    levels, its size), or replies differently when writing one to a path."""
    r = _run(run, workdir, HOUSE + SECTION + 'elevation {"facing": "south"}\n',
             "--cmd", 'render {"view": "Section 1", "width": 400, "height": 300, "path": "section.png"}',
             "--cmd", 'render {"view": "South", "width": 300, "height": 200, "path": "south.png"}')
    golden.check_run(r, "render_section_elevation.txt")
    golden.check(png_pixels((workdir / "section.png").read_bytes()), "section.png.txt")
    golden.check(png_pixels((workdir / "south.png").read_bytes()), "south.png.txt")


def test_a_cropped_coarse_section_renders_differently(run, workdir, golden):
    """CATCHES: a rewrite whose section ignores its crop region, its scale or its detail level when drawn."""
    r = _run(run, workdir, HOUSE + SECTION,
             "--cmd", 'crop {"view": "Section 1", "region": [[500, -200], [6000, 2500]]}',
             "--cmd", 'detail {"view": "Section 1", "detail": "coarse"}',
             "--cmd", 'scale {"view": "Section 1", "scale": 50}',
             "--cmd", 'render {"view": "Section 1", "width": 400, "height": 300, "path": "cropped.png"}')
    golden.check_run(r, "render_cropped_section.txt")
    golden.check(png_pixels((workdir / "cropped.png").read_bytes()), "cropped.png.txt")


def test_a_sheet_renders_as_png_and_as_one_pdf_page(run, workdir, golden):
    """CATCHES: a rewrite whose sheet (title block, viewports, their titles and scales) is drawn differently, whose
    sheet PNG is not 5 px a paper millimetre, or whose one-sheet PDF differs from the reference's."""
    r = _run(run, workdir, HOUSE + 'sheet {"name": "Plans", "size": "A4"}\n' + 'place {"sheet": "A101", "view": "Level 1"}\n',
             "--cmd", 'render {"view": "A101", "path": "a101.png"}',
             "--cmd", 'render {"view": "Plans", "path": "a101.pdf"}')
    golden.check_run(r, "render_sheet.txt")
    golden.check(png_pixels((workdir / "a101.png").read_bytes()), "a101.png.txt")
    golden.check(pdf_summary((workdir / "a101.pdf").read_bytes()), "a101.pdf.txt")


def test_saving_a_pdf_prints_every_sheet_a_page_each_in_number_order(run, workdir, golden):
    """CATCHES: a rewrite that prints sheets out of number order, misses one, draws a viewport (a plan's lines, a
    section's picture, a schedule's table) differently, or writes a PDF whose objects differ from the reference's."""
    r = _run(run, workdir, HOUSE + SECTION
             + 'sheet {"number": "B200", "name": "Sections", "size": "A3"}\n'
             + 'sheet {"number": "A100", "name": "Plans", "size": "A4"}\n'
             + 'place {"sheet": "A100", "view": "Level 1"}\n'
             + 'place {"sheet": "B200", "view": "Section 1", "scale": 50}\n'
             + 'place {"sheet": "B200", "view": "Room Schedule", "at": [100, 250]}\n',
             "--save", "set.pdf")
    golden.check_run(r, "save_pdf.txt")
    golden.check(pdf_summary((workdir / "set.pdf").read_bytes()), "set.pdf.txt")


def test_a_reflected_ceiling_plan(run, workdir, golden):
    """CATCHES: a rewrite whose reflected ceiling plan of a level does not draw its ceilings (their grid), or draws the
    floor plan instead."""
    r = _run(run, workdir, HOUSE + 'ceiling {"point": [4000, 3000], "type": "Tile 600 x 600"}\n',
             "--cmd", 'render {"view": "Level 1", "ceiling": true, "width": 200, "height": 150, "path": "rcp.svg"}')
    golden.check_run(r, "rcp.txt")
    golden.check((workdir / "rcp.svg").read_text(), "rcp.svg")


def test_a_sheet_set_to_nbr_with_mixed_scales_a_schedule_and_its_own_notes(run, workdir, golden):
    """CATCHES: a rewrite whose sheets ignore the technical standard (NBR margins and folding marks on A0 to A2), title a
    sheet of views at different scales otherwise than SCALE AS INDICATED, draw a placed schedule's table and totals
    differently, or leave out the notes and lines drawn on the sheet itself."""
    script = (HOUSE + SECTION + 'standard {"set": "nbr"}\n'
              + 'sheet {"number": "A1-01", "name": "Plans", "size": "A1"}\n'
              + 'place {"sheet": "A1-01", "view": "Level 1", "scale": 100}\n'
              + 'place {"sheet": "A1-01", "view": "Level 2", "scale": 50}\n'
              + 'schedule {"name": "Areas", "category": "rooms", "fields": ["Name", {"name": "Area", "total": true}]}\n'
              + 'place {"sheet": "A1-01", "view": "Areas", "at": [700, 500]}\n'
              + 'text {"text": "General notes", "at": [50, 550], "view": "A1-01"}\n'
              + 'detail_line {"view": "A1-01", "points": [[40, 540], [200, 540]]}\n'
              + 'filled_region {"view": "A1-01", "sketch": [[[40, 500], [80, 500]], [[80, 500], [80, 520]], [[80, 520], [40, 520]], '
              + '[[40, 520], [40, 500]]]}\n'
              + 'sheet {"number": "A0-01", "size": "A0"}\n'
              + 'sheet {"number": "A2-01", "size": "A2"}\n'
              + 'place {"sheet": "A2-01", "view": "Section 1"}\n')
    r = _run(run, workdir, script, "--cmd", 'elements {"category": "viewport"}', "--save", "nbr.pdf")
    golden.check_run(r, "nbr_sheets.txt")
    golden.check(pdf_summary((workdir / "nbr.pdf").read_bytes()), "nbr_sheets.pdf.txt")


def test_a_3d_view_on_a_sheet_with_its_dimensions(run, workdir, golden):
    """CATCHES: a rewrite whose sheet draws its 3D viewport from another direction or size than the view's azimuth and
    elevation at the viewport's scale, or leaves the view's 3D dimensions off the paper."""
    script = (HOUSE + 'dimension_3d {"refs": [{"at": [0, 0, 0]}, {"at": [8000, 0, 0]}], "at": [4000, -1500, 0]}\n'
              + 'sheet {"size": "A4"}\n'
              + 'place {"sheet": "A101", "view": "{3D}", "scale": 200}\n')
    r = _run(run, workdir, script, "--cmd", 'elements {"category": "viewport"}', "--cmd", 'render {"view": "A101", "path": "a.pdf"}')
    golden.check_run(r, "sheet_3d.txt")
    golden.check(pdf_summary((workdir / "a.pdf").read_bytes()), "sheet_3d.pdf.txt")
