"""Visibility/Graphics (`graphics`), view filters (`filter`) and view templates (`template`): what a view hides and how
it draws the rest, as replies and as the plan they change."""

import pytest

HOUSE = """wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}
door {"at": [2000, 0]}
window {"at": [8000, 3000]}
room {"point": [4000, 3000], "name": "Hall"}
"""
SECTION = 'section {"start": [-1000, 3000], "end": [9000, 3000]}\n'
INTERIOR = 'modify {"id": 100002, "type": "Interior - 100mm"}\n'


def _run(run, workdir, script, *extra):
    (workdir / "script.txt").write_text(script)
    return run(["run", "--script", "script.txt", *extra])


def _cmds(cmds):
    args = []
    for c in cmds:
        args += ["--cmd", c]
    return args


CASES = {
    # Reading: the lowest level's plan unless told; the 3D view before it is made.
    "read_defaults": (HOUSE, [
        "graphics {}",
        'graphics {"view": "Level 2"}',
        'graphics {"view": 100001}',
        'graphics {"view": "{3D}"}',
        'elements {"category": "view3d"}',
    ]),
    # Categories and elements hidden, shown again, overridden and the overrides merged and taken away.
    "hide_show_and_override": (HOUSE, [
        'graphics {"view": "Level 1", "hide": ["Walls", "room", "GRIDS"]}',
        'graphics {"view": "Level 1", "show": ["walls", "grids"]}',
        'graphics {"view": "Level 1", "hide_elements": [100006]}',
        'graphics {"view": "Level 1", "show_elements": [100006, 100007]}',
        'graphics {"view": "Level 1", "hide_elements": ["100007"]}',
        'graphics {"view": "Level 1", "categories": {"walls": {"cut": {"color": [200, 0, 0], "weight": 12, "dash": "dashed"}, '
        '"projection": {"color": "#00ff00"}, "halftone": true}}}',
        'graphics {"view": "Level 1", "categories": {"walls": {"cut": {"weight": null}, "transparency": 40}}}',
        'graphics {"view": "Level 1", "elements": {"100003": {"cut": {"color": [0, 0, 200], "fill": [250, 220, 220]}}}}',
        'graphics {"view": "Level 1", "categories": {"walls": null}, "elements": {"100003": null}}',
        'graphics {"view": "Level 1", "reset": true}',
        "undo",
        'graphics {"view": "Level 1"}',
    ]),
    "a_call_that_changes_nothing_is_no_undo_step": (HOUSE + 'graphics {"hide": ["doors"]}\n', [
        'graphics {"hide": ["doors"]}',
        "undo",
        'graphics {"view": "Level 1"}',
    ]),
    "sections_and_the_3d_view": (HOUSE + SECTION, [
        'graphics {"view": "Section 1", "hide": ["doors", "levels"]}',
        'graphics {"view": 100009, "categories": {"windows": {"projection": {"color": [0, 0, 255]}}}}',
        'graphics {"view": "{3D}", "show": ["rooms"], "hide": ["walls"]}',
        'graphics {"view": "3D", "show": ["roomreference"], "hide": ["roomseparator"]}',
        'graphics {"view": "{3D}", "show": ["walls"]}',
        'elements {"category": "section"}',
        'elements {"category": "view3d"}',
    ]),
    "deleting_an_element_takes_its_overrides": (HOUSE + 'graphics {"hide_elements": [100006], "elements": {"100003": {"halftone": true}}}\n', [
        'delete {"ids": [100006, 100003]}',
        'graphics {"view": "Level 1"}',
    ]),
    # What graphics refuses.
    "unknown_category": (HOUSE, ['graphics {"hide": ["balloons"]}']),
    "unknown_view": (HOUSE, ['graphics {"view": "nowhere"}']),
    "graphics_of_a_sheet": (HOUSE + "sheet {}\n", ['graphics {"view": "A101", "hide": ["walls"]}']),
    "hide_a_missing_element": (HOUSE, ['graphics {"hide_elements": [9999]}']),
    "hide_a_sheet_element": (HOUSE + "sheet {}\n", ['graphics {"hide_elements": [100009]}']),
    "pen_too_heavy": (HOUSE, ['graphics {"categories": {"walls": {"cut": {"weight": 17}}}}']),
    "pen_not_whole": (HOUSE, ['graphics {"categories": {"walls": {"cut": {"weight": 2.5}}}}']),
    "pen_by_name": (HOUSE, ['graphics {"categories": {"walls": {"projection": {"weight": "heavy"}}}}']),
    "transparency_over_100": (HOUSE, ['graphics {"categories": {"walls": {"transparency": 101}}}']),
    "unknown_dash": (HOUSE, ['graphics {"categories": {"walls": {"projection": {"dash": "wavy"}}}}']),
    "colour_out_of_range": (HOUSE, ['graphics {"categories": {"walls": {"projection": {"color": [300, 0, 0]}}}}']),
    "misspelt_colour_key": (HOUSE, ['graphics {"categories": {"walls": {"projection": {"colour": [3, 0, 0]}}}}']),
    "override_of_an_unknown_category": (HOUSE, ['graphics {"categories": {"balloons": {"halftone": true}}}']),
    "override_of_a_bad_id": (HOUSE, ['graphics {"elements": {"abc": {"halftone": true}}}']),
    "override_of_a_missing_element": (HOUSE, ['graphics {"elements": {"9999": {"halftone": true}}}']),
    "apply_an_unknown_filter": (HOUSE, ['graphics {"filters": [{"filter": "Nope"}]}']),
    "follow_an_unknown_template": (HOUSE, ['graphics {"template": "Nope"}']),
    "hide_not_a_list": (HOUSE, ['graphics {"hide": "walls"}']),
    "categories_not_a_map": (HOUSE, ['graphics {"categories": ["walls"]}']),
    "filters_not_a_list": (HOUSE, ['graphics {"filters": "Interior"}']),
    "template_not_a_name": (HOUSE, ['graphics {"template": 5}']),
    "unknown_fill_pattern_layer": (HOUSE, ['graphics {"categories": {"walls": {"cut": {"foreground": {"pattern": "Nope"}}}}}']),
    # View filters.
    "view_filters": (HOUSE + INTERIOR, [
        'filter {"name": "Interior", "categories": ["walls"], "rules": [{"field": "Type", "op": "equals", "value": "Interior - 100mm"}]}',
        'filter {"name": "Long", "categories": ["walls"], "rules": [{"field": "Length", "op": "greater", "value": 7000}]}',
        'filter {"name": "Openings", "categories": ["doors", "windows", "door"]}',
        'filter {"name": "Long"}',
        'filter {"name": "Long", "rules": [{"field": "Length", "op": "less-or-equal", "value": 6000}]}',
        'graphics {"view": 100000, "filters": [{"filter": "Interior", "cut": {"color": [200, 0, 0], "fill": [250, 220, 220]}}, '
        '{"filter": "Openings", "halftone": true}]}',
        'graphics {"view": 100001, "filters": [{"filter": "Long", "hidden": true}]}',
        'filter {"name": "Long", "delete": true}',
        'graphics {"view": 100001}',
        'library {"kind": "view-filter"}',
    ]),
    "filter_follows_a_renamed_parameter": (HOUSE + 'parameter {"name": "Fire Rating", "kind": "number", "categories": ["walls"]}\n'
                                           + 'modify {"id": 100003, "params": {"Fire Rating": 2}}\n', [
        'filter {"name": "Rated", "categories": ["wall"], "rules": [{"field": "Fire Rating", "op": "greater-or-equal", "value": 1}]}',
        'parameter {"name": "Fire Rating", "rename": "Fire Class"}',
        'filter {"name": "Rated"}',
        'parameter {"name": "Fire Class", "delete": true}',
    ]),
    "filter_without_name": (HOUSE, ['filter {"categories": ["walls"]}']),
    "filter_without_categories": (HOUSE, ['filter {"name": "X"}']),
    "filter_with_no_categories": (HOUSE, ['filter {"name": "X", "categories": []}']),
    "filter_of_an_unknown_category": (HOUSE, ['filter {"name": "X", "categories": ["balloons"]}']),
    "filter_on_an_unknown_field": (HOUSE, ['filter {"name": "X", "categories": ["walls"], "rules": [{"field": "Nope", "op": "equals", "value": 1}]}']),
    "filter_on_a_field_not_all_have": (HOUSE, ['filter {"name": "X", "categories": ["walls", "rooms"], '
                                               '"rules": [{"field": "Type", "op": "equals", "value": "a"}]}']),
    "filter_text_op_on_a_length": (HOUSE, ['filter {"name": "X", "categories": ["walls"], '
                                           '"rules": [{"field": "Length", "op": "contains", "value": "a"}]}']),
    "filter_word_for_a_length": (HOUSE, ['filter {"name": "X", "categories": ["walls"], '
                                         '"rules": [{"field": "Length", "op": "greater", "value": "long"}]}']),
    "filter_unknown_op": (HOUSE, ['filter {"name": "X", "categories": ["walls"], "rules": [{"field": "Length", "op": "near", "value": 1}]}']),
    "filter_rules_not_a_list": (HOUSE, ['filter {"name": "X", "categories": ["walls"], "rules": "all"}']),
    "delete_an_unknown_filter": (HOUSE, ['filter {"name": "Nope", "delete": true}']),
    "a_filter_applied_twice": (HOUSE + 'filter {"name": "A", "categories": ["walls"]}\n',
                               ['graphics {"filters": [{"filter": "A"}, {"filter": "A", "halftone": true}]}']),
    # View templates.
    "templates_from_views": (HOUSE + 'grid {"start": [-1000, 3000], "end": [9000, 3000]}\n', [
        'graphics {"view": 100000, "hide": ["grids"], "categories": {"walls": {"cut": {"color": [200, 0, 0]}}}}',
        'template {"name": "Presentation", "from": "Level 1"}',
        'graphics {"view": "Level 2", "template": "Presentation"}',
        'template {"name": "Presentation", "categories": {"walls": {"cut": {"color": [0, 0, 200]}}}}',
        'graphics {"view": "Level 2"}',
        'template {"name": "Presentation", "controls": ["filters"]}',
        'graphics {"view": 100001, "hide": ["rooms"]}',
        'graphics {"view": 100001, "template": null}',
        'template {"name": "Presentation"}',
    ]),
    "templates_kinds_copies_and_renames": (HOUSE, [
        'template {"name": "Plans", "from": "Level 1"}',
        'graphics {"view": "{3D}", "hide": ["levels"]}',
        'template {"name": "Shaded", "from": "{3D}"}',
        'template {"name": "Cuts", "kind": "section", "detail": "fine"}',
        'template {"name": "Any", "controls": ["scale"]}',
        'graphics {"view": "Level 2", "template": "Plans"}',
        'template {"name": "Plans 2", "like": "Plans", "detail": "coarse"}',
        'template {"name": "Plans", "rename": "Working Plans"}',
        'graphics {"view": "Level 2"}',
        'template {"name": "Any", "kind": null}',
        'library {"kind": "view-template"}',
    ]),
    "template_view_range": (HOUSE, [
        'template {"name": "Low cut", "view_range": {"cut": 500, "top": 2000}, "controls": ["range"]}',
        'modify {"id": 100001, "view_range": {"cut": 1500}}',
        'graphics {"view": 100001, "template": "Low cut"}',
        'template {"name": "Low cut", "view_range": {"top": null}}',
        'graphics {"view": 100001, "template": null}',
        'elements {"category": "level"}',
    ]),
    "template_controls_scale_detail_and_style": (HOUSE + 'scale {"view": 100001, "scale": 100}\ndetail {"view": 100001, "detail": "coarse"}\n', [
        'template {"name": "Plans", "from": 100001}',
        'scale {"view": 100000, "scale": 50}',
        'graphics {"view": 100000, "template": "Plans"}',
        'scale {"view": 100000}',
        'detail {"view": 100000}',
        'template {"name": "Plans", "controls": ["scale"]}',
        'detail {"view": 100000, "detail": "medium"}',
        'template {"name": "Plans", "scale": 200, "detail": "fine", "visual_style": "wireframe"}',
        'scale {"view": 100000}',
        'visual_style {"style": "wireframe"}',
        'template {"name": "Wire", "from": "{3D}"}',
        'graphics {"view": "{3D}", "reset": true, "template": "Wire"}',
        'visual_style {}',
        'template {"name": "Wire", "visual_style": "hidden_line"}',
        'visual_style {}',
    ]),
    "template_refuses_a_followers_scale": (HOUSE + 'template {"name": "Plans", "from": 100001}\n'
                                           + 'graphics {"view": 100000, "template": "Plans"}\n',
                                           ['scale {"view": 100000, "scale": 20}']),
    "template_refuses_a_followers_detail": (HOUSE + 'template {"name": "Plans", "from": 100001}\n'
                                            + 'graphics {"view": 100000, "template": "Plans"}\n',
                                            ['detail {"view": 100000, "detail": "medium"}']),
    "template_refuses_a_followers_categories": (HOUSE + 'template {"name": "Plans", "from": 100001}\n'
                                                + 'graphics {"view": 100000, "template": "Plans"}\n',
                                                ['graphics {"view": 100000, "hide": ["rooms"]}']),
    "template_refuses_a_followers_style": (HOUSE + 'visual_style {"style": "wireframe"}\ntemplate {"name": "Wire", "from": "{3D}"}\n'
                                           + 'graphics {"view": "{3D}", "template": "Wire"}\n',
                                           ['visual_style {"style": "hidden_line"}']),
    "template_refuses_a_followers_view_range": (HOUSE + 'template {"name": "Plans", "from": 100001}\n'
                                                + 'graphics {"view": 100000, "template": "Plans"}\n',
                                                ['modify {"id": 100000, "view_range": {"cut": 1800}}']),
    "unfollow_and_change_in_one_call": (HOUSE + 'template {"name": "Plans", "from": 100001}\n'
                                        + 'graphics {"view": 100000, "template": "Plans"}\n',
                                        ['graphics {"view": 100000, "template": null, "hide": ["rooms"]}']),
    "template_deleted_its_views_keep_their_own": (HOUSE + 'graphics {"view": 100000, "hide": ["rooms"]}\n'
                                                  + 'template {"name": "T", "from": 100000}\n'
                                                  + 'graphics {"view": 100001, "template": "T"}\n', [
        'template {"name": "T", "delete": true}',
        'graphics {"view": 100001}',
        'graphics {"view": 100000}',
    ]),
    "template_without_name": (HOUSE, ['template {"from": "Level 1"}']),
    "template_named_alone_is_read_never_made": (HOUSE, ['template {"name": "Nope"}']),
    "template_from_nowhere": (HOUSE, ['template {"name": "T", "from": "nowhere"}']),
    "template_from_a_sheet": (HOUSE + "sheet {}\n", ['template {"name": "T", "from": 100009}']),
    "template_unknown_control": (HOUSE, ['template {"name": "T", "controls": ["layout"]}']),
    "template_controls_not_a_list": (HOUSE, ['template {"name": "T", "controls": "all"}']),
    "template_bad_view_range": (HOUSE, ['template {"name": "T", "view_range": {"cut": -5, "bottom": 10}}']),
    "template_view_range_not_a_map": (HOUSE, ['template {"name": "T", "view_range": [1]}']),
    "template_with_elements": (HOUSE, ['template {"name": "T", "hide_elements": [100002]}']),
    "template_following_a_template": (HOUSE, ['template {"name": "T", "template": "U"}']),
    "template_unknown_kind": (HOUSE + 'template {"name": "Cuts", "kind": "section"}\n', ['template {"name": "Cuts", "kind": "sheet"}']),
    "template_like_an_unknown_one": (HOUSE, ['template {"name": "Plans 3", "like": "Nope"}']),
    "template_renamed_onto_another": (HOUSE + 'template {"name": "A", "controls": ["scale"]}\ntemplate {"name": "B", "controls": ["scale"]}\n',
                                      ['template {"name": "A", "rename": "B"}']),
    "template_bad_scale": (HOUSE + 'template {"name": "T", "controls": ["scale"]}\n', ['template {"name": "T", "scale": 0}']),
    "template_bad_style": (HOUSE + 'template {"name": "T", "controls": ["style"]}\n', ['template {"name": "T", "visual_style": "pretty"}']),
    "delete_an_unknown_template": (HOUSE, ['template {"name": "Nope", "delete": true}']),
    "starter_templates_in_portuguese": ('new {"language": "pt"}\n', ['library {"kind": "view-template"}']),
    # What modify does to a view's graphics, checked as graphics checks them.
    "modify_a_views_graphics": (HOUSE, [
        'modify {"id": 100000, "graphics": {"categories": {"room": {"hidden": true}}}}',
        'graphics {"view": 100000}',
        'modify {"id": 100000, "graphics": {"categories": {"room": null}}}',
        'graphics {"view": 100000}',
    ]),
    "modify_graphics_unknown_category": (HOUSE, ['modify {"id": 100000, "graphics": {"categories": {"balloon": {"hidden": true}}}}']),
    "modify_graphics_heavy_pen": (HOUSE, ['modify {"id": 100000, "graphics": {"categories": {"wall": {"cut": {"weight": 500}}}}}']),
    "modify_graphics_transparency": (HOUSE, ['modify {"id": 100000, "graphics": {"categories": {"wall": {"transparency": 120}}}}']),
    "modify_graphics_unknown_filter": (HOUSE, ['modify {"id": 100000, "graphics": {"filters": [{"filter": "Nope"}]}}']),
    "modify_graphics_unknown_template": (HOUSE, ['modify {"id": 100000, "graphics": {"template": "Nope"}}']),
    "modify_graphics_bad_element": (HOUSE, ['modify {"id": 100000, "graphics": {"elements": {"x": {"hidden": true}}}}']),
    "modify_graphics_unknown_phase": (HOUSE, ['modify {"id": 100000, "graphics": {"phase": "Nowhere"}}']),
    "modify_graphics_unknown_option_set": (HOUSE, ['modify {"id": 100000, "graphics": {"options": {"Nope": "x"}}}']),
    "modify_graphics_scale": (HOUSE, ['modify {"id": 100000, "graphics": {"scale": 0}}']),
    "modify_a_followers_style": (HOUSE + 'template {"name": "Plans", "from": 100001}\ngraphics {"view": 100000, "template": "Plans"}\n',
                                 ['modify {"id": 100000, "graphics": {"style": "wireframe"}}']),
    # Background grids, as graphics sets them.
    "background_grids": (HOUSE, [
        'graphics {"view": "Level 1", "background_grid": {"visible": true, "main": {"enabled": true, "color": [200, 0, 0], "pen": 2}, '
        '"spacing": [500, 250], "divisions": [4, 2], "rotation": 30}}',
        'graphics {"view": "Level 1", "background_grid": {"sub": {"enabled": true}}}',
        'render {"view": "Level 1", "width": 200, "height": 150, "path": "grid.svg"}',
        'graphics {"view": "Level 1", "background_grid": null}',
        'template {"name": "Grid", "controls": ["background_grid"], "background_grid": {"main": {"enabled": true}}}',
        'graphics {"view": "Level 2", "template": "Grid"}',
    ]),
    "background_grid_not_an_object": (HOUSE, ['graphics {"background_grid": 5}']),
    "background_grid_no_divisions": (HOUSE, ['graphics {"background_grid": {"divisions": [0, 5]}}']),
    "background_grid_turned_too_far": (HOUSE, ['graphics {"background_grid": {"rotation": 400}}']),
    "background_grid_bad_pen": (HOUSE, ['graphics {"background_grid": {"main": {"pen": 17}}}']),
    "background_grid_unknown_key": (HOUSE, ['graphics {"background_grid": {"colour": [1, 2, 3]}}']),
    "background_grid_of_a_follower": (HOUSE + 'template {"name": "Grid", "controls": ["background_grid"]}\n'
                                      + 'graphics {"view": "Level 2", "template": "Grid"}\n',
                                      ['graphics {"view": "Level 2", "background_grid": {"visible": false}}']),
    # Layers of CAD drawings, which a project without one hasn't.
    "layers_of_an_unknown_drawing": (HOUSE, ['graphics {"layers": {"site.dxf": ["A-WALL"]}}']),
    "layers_not_a_map": (HOUSE, ['graphics {"layers": ["A-WALL"]}']),
    "filter_categories_not_a_list": (HOUSE, ['filter {"name": "X", "categories": "walls"}']),
    "show_elements_not_a_list": (HOUSE, ['graphics {"show_elements": 100006}']),
    "elements_not_a_map": (HOUSE, ['graphics {"elements": [100006]}']),
    # A family component is of its family's category.
    "family_categories": (HOUSE + 'component {"family": "Chair", "at": [2000, 2000]}\n'
                          + 'component {"family": "Ceiling Luminaire", "at": [4000, 3000]}\n'
                          + 'component {"family": "Outlet", "at": [7900, 1000]}\n', [
        'graphics {"view": "Level 1", "hide": ["furniture"], "categories": {"lighting": {"halftone": true}}}',
        'graphics {"view": "Level 2", "hide": ["component"]}',
        'graphics {"view": "Level 2", "show": ["lighting"]}',
        'filter {"name": "Things", "categories": ["components"]}',
        'filter {"name": "Chairs", "categories": ["components"], "rules": [{"field": "Family", "op": "equals", "value": "Chair"}]}',
        'graphics {"view": "Level 1", "template": "Electrical Lighting"}',
    ]),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_graphics_filters_and_templates(run, workdir, golden, case):
    """CATCHES: a rewrite whose Visibility/Graphics, view filters or view templates differ from the reference's: how
    categories and elements are hidden and overridden and how overrides merge, which elements a filter picks, what a
    template takes from a view and controls in its followers, what each reply holds, and how each refusal is worded."""
    setup, cmds = CASES[case]
    r = _run(run, workdir, setup, *_cmds(cmds))
    golden.check_run(r, f"{case}.txt")


PLAN = 'render {"view": "Level 1", "width": 200, "height": 150, "path": "plan.svg"}'

# What a plan draws once its graphics change: each case's setup, then the plan as an SVG.
DRAWN = {
    "as_it_starts": HOUSE,
    "doors_and_rooms_hidden": HOUSE + 'graphics {"view": "Level 1", "hide": ["doors", "rooms"]}\n',
    "walls_overridden_and_halftone": HOUSE + 'graphics {"view": "Level 1", "categories": {"walls": {"cut": {"color": [200, 0, 0], '
                                             '"weight": 12, "dash": "dashed", "fill": [250, 220, 220]}}, "windows": {"halftone": true}}}\n',
    "an_element_beats_a_filter_which_beats_its_category": HOUSE + INTERIOR
        + 'filter {"name": "Interior", "categories": ["walls"], "rules": [{"field": "Type", "op": "equals", "value": "Interior - 100mm"}]}\n'
        + 'graphics {"view": "Level 1", "categories": {"walls": {"cut": {"color": [9, 9, 9], "dash": "dotted"}}}, '
          '"filters": [{"filter": "Interior", "cut": {"color": [0, 200, 0], "weight": 3}}], '
          '"elements": {"100002": {"cut": {"color": [0, 0, 200]}}}}\n',
    "a_filter_hides": HOUSE + INTERIOR
        + 'filter {"name": "Interior", "categories": ["walls"], "rules": [{"field": "Type", "op": "contains", "value": "interior"}]}\n'
        + 'graphics {"view": "Level 1", "filters": [{"filter": "Interior", "hidden": true}]}\n',
    "furniture_hidden_and_luminaires_halftone": HOUSE + 'component {"family": "Chair", "at": [2000, 2000]}\n'
        + 'component {"family": "Table", "at": [3000, 3000]}\n'
        + 'component {"family": "Ceiling Luminaire", "at": [6000, 3000]}\n'
        + 'graphics {"view": "Level 1", "hide": ["furniture"], "categories": {"lighting": {"halftone": true}}}\n',
    "following_a_template": HOUSE + 'graphics {"view": "Level 2", "hide": ["walls"]}\n'
        + 'template {"name": "No walls", "from": "Level 2", "controls": ["categories"]}\n'
        + 'graphics {"view": "Level 1", "template": "No walls"}\n',
}


@pytest.mark.parametrize("case", sorted(DRAWN))
def test_graphics_change_what_a_plan_draws(run, workdir, golden, case):
    """CATCHES: a rewrite whose plan ignores what the view hides, draws an override's colour, pen, dash, fill or
    halftone differently, applies filters and element overrides in another order of precedence, or ignores the
    template a view follows."""
    r = _run(run, workdir, DRAWN[case], "--cmd", PLAN)
    golden.check_run(r, f"drawn_{case}.txt")
    golden.check((workdir / "plan.svg").read_text(), f"drawn_{case}.svg")
