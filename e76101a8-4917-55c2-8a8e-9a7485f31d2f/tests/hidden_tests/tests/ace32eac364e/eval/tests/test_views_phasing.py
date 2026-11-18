"""Phases, phase filters and design options (`phase`, `phase_filter`, `option`), and what views, schedules and view
filters make of them."""

import pytest

HOUSE = 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}\n'
# The four walls: the first existing, the second new, the third demolished, the fourth temporary.
PHASED = HOUSE + """modify {"id": 100003, "params": {"Phase Created": "New Construction"}}
modify {"id": 100004, "params": {"Phase Demolished": "New Construction"}}
modify {"id": 100005, "params": {"Phase Created": "New Construction", "Phase Demolished": "New Construction"}}
"""
WALLS = 'schedule {"name": "Phasing", "category": "walls", "fields": ["Id", "Phase Created", "Phase Demolished", "Design Option"]}'
FACADE = 'option {"set": "Facade", "options": ["Brick", "Glass"]}\n'


def _run(run, workdir, script, *extra):
    (workdir / "script.txt").write_text(script)
    return run(["run", "--script", "script.txt", *extra])


def _cmds(cmds):
    args = []
    for c in cmds:
        args += ["--cmd", c]
    return args


CASES = {
    # A project's phases and phase filters, in English and in Portuguese.
    "starting_phases": (HOUSE, [
        "phase {}",
        'phase_filter {"name": "Show All"}',
        'phase_filter {"name": "Show Previous + New"}',
        'library {"kind": "phase"}',
        'library {"kind": "phase-filter"}',
        'new {"language": "pt"}',
        "phase {}",
        'library {"kind": "phase-filter"}',
    ]),
    # Added in place, renamed with what holds them, deleted into another.
    "phases_added_renamed_and_deleted": (PHASED, [
        'phase {"name": "Demolition", "before": "New Construction"}',
        'phase {"name": "Furniture"}',
        'phase {"name": "Landscape", "after": "Furniture"}',
        'graphics {"view": 100000, "phase": "New Construction"}',
        'phase {"now": "New Construction"}',
        'phase {"name": "New Construction", "rename": "Works"}',
        'graphics {"view": 100000}',
        WALLS,
        'phase {"name": "Works", "delete": true, "into": "Demolition"}',
        'schedule {"name": "Phasing"}',
        'graphics {"view": 100000}',
        "phase {}",
        'phase {"name": "Landscape", "delete": true}',
        'phase {"name": "Furniture", "delete": true, "into": "Demolition"}',
        'phase {"name": "Demolition", "delete": true, "into": "Existing"}',
        'schedule {"name": "Phasing"}',
    ]),
    # What a session makes is made in its phase; the first phase holds no value; copies.
    "made_in_the_phase_the_session_is_in": (HOUSE, [
        'phase {"now": "New Construction"}',
        'wall {"points": [[0, 7000], [3000, 7000]]}',
        'door {"at": [1000, 7000]}',
        'phase {"now": "Existing"}',
        'copy {"ids": [100006], "by": [0, 1000]}',
        'phase {"now": null}',
        'copy {"ids": [100006], "by": [0, 2000]}',
        'elements {"category": "wall"}',
        'elements {"category": "door"}',
        "phase {}",
    ]),
    "phase_put_in_before_the_first": (HOUSE + 'door {"at": [2000, 0]}\n', [
        'phase {"name": "Survey", "before": "Existing"}',
        WALLS,
        'schedule {"category": "doors", "fields": ["Mark", "Phase Created"]}',
        'phase {"name": "Survey", "delete": true, "into": "Existing"}',
        WALLS,
    ]),
    "deleting_the_first_phase": (HOUSE, [
        'phase {"name": "Existing", "delete": true, "into": "New Construction"}',
        WALLS,
    ]),
    # Overrides of the statuses a phase filter draws overridden, and phase filters of the project's.
    "phase_filters_and_overrides": (PHASED, [
        'phase_filter {"name": "Renovation", "new": "overridden", "existing": "by-category", "demolished": "not-displayed", '
        '"temporary": "not-displayed"}',
        'phase_filter {"name": "Bare"}',
        'phase_filter {"name": "Show New", "existing": "overridden"}',
        'phase {"overrides": {"new": {"cut": {"color": [0, 0, 200]}}}}',
        'phase {"overrides": {"new": {"projection": {"weight": 6}}, "existing": null}}',
        'graphics {"view": 100000, "phase_filter": "Renovation"}',
        'graphics {"view": 100000, "phase_filter": null}',
        'phase_filter {"name": "Renovation", "delete": true}',
        'library {"kind": "phase-filter"}',
    ]),
    # Phases as fields of schedules and view filters: sorted and grouped by the project's order.
    "phase_fields_in_schedules_and_filters": (PHASED + 'phase {"name": "Alpha", "after": "New Construction"}\n'
                                              + 'modify {"id": 100002, "params": {"Phase Created": "Alpha"}}\n', [
        WALLS,
        'schedule {"name": "Phasing", "sort": ["Phase Created", {"field": "Id", "descending": true}]}',
        'schedule {"name": "Phasing", "sort": [{"field": "Phase Demolished", "descending": true}, "Id"]}',
        'schedule {"name": "By phase", "category": "walls", "fields": ["Phase Created", {"name": "Count", "total": true}], '
        '"sort": ["Phase Created"], "grouped": true}',
        'filter {"name": "New work", "categories": ["walls"], "rules": [{"field": "Phase Created", "op": "equals", '
        '"value": "New Construction"}]}',
        'filter {"name": "Coming down", "categories": ["walls"], "rules": [{"field": "Phase Demolished", "op": "has-value"}]}',
        'filter {"name": "Standing", "categories": ["walls"], "rules": [{"field": "Phase Demolished", "op": "has-no-value"}]}',
    ]),
    "renaming_a_phase_renames_it_in_filters_and_schedules": (PHASED + 'filter {"name": "New work", "categories": ["walls"], '
                                                             '"rules": [{"field": "Phase Created", "op": "equals", "value": "New Construction"}]}\n'
                                                             + 'schedule {"name": "New walls", "category": "walls", "fields": ["Id"], '
                                                             '"filters": [{"field": "Phase Created", "op": "equals", "value": "New Construction"}]}\n', [
        'phase {"name": "New Construction", "rename": "Works"}',
        'filter {"name": "New work"}',
        'schedule {"name": "New walls"}',
    ]),
    "a_door_follows_its_wall": (HOUSE + 'door {"at": [2000, 0]}\nmodify {"id": 100002, "params": {"Phase Created": "New Construction"}}\n', [
        'schedule {"category": "doors", "fields": ["Mark", "Phase Created", "Phase Demolished"]}',
        'modify {"id": 100006, "params": {"Phase Created": "Existing"}}',
        'schedule {"category": "doors"}',
    ]),
    # What phase refuses.
    "phase_name_taken": (HOUSE, ['phase {"name": "Existing"}']),
    "phase_before_an_unknown_one": (HOUSE, ['phase {"name": "New", "before": "Nowhere"}']),
    "phase_before_and_after": (HOUSE, ['phase {"name": "New", "before": "Existing", "after": "New Construction"}']),
    "rename_an_unknown_phase": (HOUSE, ['phase {"name": "Nowhere", "rename": "X"}']),
    "rename_onto_another_phase": (HOUSE, ['phase {"name": "New Construction", "rename": "Existing"}']),
    "rename_to_nothing": (HOUSE, ['phase {"name": "New Construction", "rename": ""}']),
    "delete_a_phase_in_use_without_into": (PHASED, ['phase {"name": "New Construction", "delete": true}']),
    "delete_a_phase_into_itself": (HOUSE, ['phase {"name": "New Construction", "delete": true, "into": "New Construction"}']),
    "delete_a_phase_into_an_unknown_one": (HOUSE, ['phase {"name": "New Construction", "delete": true, "into": "Nowhere"}']),
    "delete_the_only_phase": (HOUSE + 'phase {"name": "New Construction", "delete": true}\n',
                              ['phase {"name": "Existing", "delete": true, "into": "Existing"}']),
    "phase_blank_name": (HOUSE, ['phase {"name": "  "}']),
    "rename_without_name": (HOUSE, ['phase {"rename": "X"}']),
    "now_not_a_name": (HOUSE, ['phase {"now": 5}']),
    "now_an_unknown_phase": (HOUSE, ['phase {"now": "Nowhere"}']),
    "overrides_not_a_map": (HOUSE, ['phase {"overrides": 5}']),
    "overrides_of_an_unknown_status": (HOUSE, ['phase {"overrides": {"future": {}}}']),
    "overrides_that_hide": (HOUSE, ['phase {"overrides": {"existing": {"hidden": true}}}']),
    "phase_filter_without_name": (HOUSE, ['phase_filter {"new": "overridden"}']),
    "phase_filter_bad_status": (HOUSE, ['phase_filter {"name": "X", "new": "sometimes"}']),
    "phase_filter_in_use": (HOUSE + 'graphics {"view": 100000, "phase_filter": "Show New"}\n',
                            ['phase_filter {"name": "Show New", "delete": true}']),
    "phase_filter_of_a_template": (HOUSE + 'template {"name": "T", "controls": ["phase"], "phase_filter": "Show New"}\n',
                                   ['phase_filter {"name": "Show New", "delete": true}']),
    "delete_an_unknown_phase_filter": (HOUSE, ['phase_filter {"name": "Nope", "delete": true}']),
    "modify_an_unknown_phase": (HOUSE, ['modify {"id": 100002, "params": {"Phase Created": "Nowhere"}}']),
    "modify_a_phase_as_a_number": (HOUSE, ['modify {"id": 100002, "params": {"Phase Created": 5}}']),
    "demolished_before_made": (HOUSE, ['modify {"id": 100002, "params": {"Phase Created": "New Construction", '
                                       '"Phase Demolished": "Existing"}}']),
    "a_parameter_named_like_a_phase": (HOUSE, ['parameter {"name": "Phase Created", "categories": ["wall"]}']),
    "view_shows_an_unknown_phase": (HOUSE, ['graphics {"view": 100000, "phase": "Nowhere"}']),
    "view_shows_an_unknown_phase_filter": (HOUSE, ['graphics {"view": 100000, "phase_filter": "Nope"}']),
    "view_phase_not_a_name": (HOUSE, ['graphics {"view": 100000, "phase": 5}']),
    # Design options.
    "design_options": (HOUSE + 'door {"at": [2000, 0]}\n', [
        FACADE.strip(),
        'modify {"ids": [100002], "params": {"Design Option": "Facade: Brick"}}',
        'modify {"ids": [100004], "params": {"Design Option": "Facade: Glass"}}',
        'graphics {"view": 100000, "options": {"Facade": "Glass"}}',
        'option {"set": "Facade", "primary": "Glass"}',
        'option {"now": "Facade: Brick"}',
        'wall {"points": [[0, 7000], [3000, 7000]]}',
        'option {"now": null}',
        'option {"set": "Facade", "options": ["Brick", "Glass", "Timber"]}',
        'option {"set": "Facade", "option": "Glass", "rename": "Curtain wall"}',
        'graphics {"view": 100000}',
        'option {"set": "Facade", "rename": "Envelope"}',
        WALLS,
        'library {"kind": "option-set"}',
        'library {"kind": "design-option"}',
    ]),
    "accepting_the_primary": (HOUSE + 'door {"at": [2000, 0]}\n'
                              + 'option {"set": "Facade", "options": ["Brick", "Glass"], "primary": "Glass"}\n'
                              + 'modify {"id": 100002, "params": {"Design Option": "Facade: Brick"}}\n'
                              + 'modify {"id": 100004, "params": {"Design Option": "Facade: Glass"}}\n', [
        'option {"set": "Facade", "accept": true}',
        WALLS,
        'elements {"category": "door"}',
        'option {"set": "Roof", "options": ["Hip", "Gable"]}',
        'modify {"id": 100003, "params": {"Design Option": "Roof: Gable"}}',
        'option {"set": "Roof", "delete": true}',
        "undo",
        WALLS,
    ]),
    "an_option_with_elements_cant_go": (HOUSE + FACADE + 'modify {"id": 100002, "params": {"Design Option": "Facade: Glass"}}\n',
                                        ['option {"set": "Facade", "options": ["Brick"]}']),
    "option_unknown_primary": (HOUSE + FACADE, ['option {"set": "Facade", "primary": "Nowhere"}']),
    "option_no_options": (HOUSE + FACADE, ['option {"set": "Facade", "options": []}']),
    "option_twice": (HOUSE, ['option {"set": "Facade", "options": ["A", "A"]}']),
    "set_name_with_a_colon": (HOUSE, ['option {"set": "A:B", "options": ["x"]}']),
    "option_name_with_a_colon": (HOUSE, ['option {"set": "Roof", "options": ["x: y"]}']),
    "a_new_set_without_options": (HOUSE, ['option {"set": "Roof"}']),
    "delete_an_unknown_set": (HOUSE + FACADE, ['option {"set": "Nowhere", "delete": true}']),
    "now_an_unknown_option": (HOUSE + FACADE, ['option {"now": "Nowhere: A"}']),
    "option_now_not_a_name": (HOUSE, ['option {"now": 5}']),
    "option_without_set": (HOUSE, ["option {}"]),
    "rename_an_unknown_option": (HOUSE + FACADE, ['option {"set": "Facade", "option": "Steel", "rename": "X"}']),
    "rename_onto_another_option": (HOUSE + FACADE, ['option {"set": "Facade", "option": "Glass", "rename": "Brick"}']),
    "rename_onto_another_set": (HOUSE + FACADE + 'option {"set": "Roof", "options": ["Hip"]}\n', ['option {"set": "Facade", "rename": "Roof"}']),
    "element_in_an_unknown_option": (HOUSE, ['modify {"id": 100002, "params": {"Design Option": "Nowhere: A"}}']),
    "element_option_without_its_set": (HOUSE + FACADE, ['modify {"id": 100002, "params": {"Design Option": "Brick"}}']),
    "view_shows_an_unknown_set": (HOUSE, ['graphics {"view": 100000, "options": {"Nope": "x"}}']),
    "view_shows_an_unknown_option": (HOUSE + FACADE, ['graphics {"view": 100000, "options": {"Facade": "Nope"}}']),
    "view_options_not_a_map": (HOUSE, ['graphics {"view": 100000, "options": 5}']),
    "view_option_not_a_name": (HOUSE + FACADE, ['graphics {"view": 100000, "options": {"Facade": 5}}']),
    "an_option_a_view_chose_goes": (HOUSE + FACADE + 'graphics {"view": 100000, "options": {"Facade": "Glass"}}\n', [
        'option {"set": "Facade", "options": ["Brick", "Timber"]}',
        'graphics {"view": 100000}',
    ]),
    "templates_control_phase_and_options": (PHASED + FACADE + 'modify {"id": 100002, "params": {"Design Option": "Facade: Glass"}}\n', [
        'graphics {"view": 100000, "phase": "Existing", "phase_filter": "Show Complete", "options": {"Facade": "Glass"}}',
        'template {"name": "Survey", "from": 100000}',
        'graphics {"view": 100001, "template": "Survey"}',
        'graphics {"view": 100001}',
        'template {"name": "Survey", "controls": ["categories"]}',
        'graphics {"view": 100001, "phase": "New Construction"}',
    ]),
    # The option this session makes elements in follows what happens to its set.
    "the_sessions_option_follows_renames": (HOUSE + FACADE + 'option {"now": "Facade: Glass"}\n', [
        'option {"set": "Facade", "option": "Glass", "rename": "Curtain wall"}',
        'option {"set": "Facade", "rename": "Envelope", "now": "Envelope: Brick"}',
        'wall {"points": [[0, 7000], [3000, 7000]]}',
        'option {"set": "Envelope", "rename": "Skin"}',
        'option {"set": "Skin", "primary": "Curtain wall", "now": "Skin: Curtain wall"}',
        'wall {"points": [[0, 8000], [3000, 8000]]}',
        'option {"set": "Skin", "accept": true}',
        'wall {"points": [[0, 9000], [3000, 9000]]}',
        WALLS,
    ]),
    "the_sessions_option_goes_with_its_set": (HOUSE + FACADE + 'option {"now": "Facade: Glass"}\n', [
        'option {"set": "Facade", "delete": true}',
        'wall {"points": [[0, 7000], [3000, 7000]]}',
        WALLS,
    ]),
    "rename_a_set_to_an_unknown_now": (HOUSE + FACADE, ['option {"set": "Facade", "rename": "Envelope", "now": "Facade: Brick"}']),
    "set_now_with_a_change": (HOUSE + FACADE, ['option {"set": "Facade", "primary": "Glass", "now": "Nowhere: X"}']),
    "rename_with_a_colon": (HOUSE + FACADE, ['option {"set": "Facade", "rename": "A: B"}']),
    "options_not_a_list": (HOUSE, ['option {"set": "Facade", "options": "Brick"}']),
    "option_a_number": (HOUSE, ['option {"set": "Facade", "options": ["Brick", 5]}']),
    "template_refuses_a_followers_phase": (PHASED + 'template {"name": "Survey", "from": 100000}\n'
                                           + 'graphics {"view": 100001, "template": "Survey"}\n',
                                           ['graphics {"view": 100001, "phase": "Existing"}']),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_phases_and_options(run, workdir, golden, case):
    """CATCHES: a rewrite whose phases, phase filters, overrides and design option sets differ from the reference's: the
    starting ones and their names by language, what renaming, deleting and combining carry along to elements, views,
    filters and schedules, the phase and option new elements are made in, accepting and deleting a set, the replies,
    and every refusal's wording."""
    setup, cmds = CASES[case]
    r = _run(run, workdir, setup, *_cmds(cmds))
    golden.check_run(r, f"{case}.txt")


PLAN = 'render {"view": "Level 1", "width": 200, "height": 150, "path": "plan.svg"}'

# What Level 1's plan draws of the phased walls (and of two design options) as its phase and phase filter say.
DRAWN = {
    "show_all": PHASED,
    "show_complete": PHASED + 'graphics {"view": 100000, "phase_filter": "Show Complete"}\n',
    "show_new": PHASED + 'graphics {"view": 100000, "phase_filter": "Show New"}\n',
    "show_previous_and_demolished": PHASED + 'graphics {"view": 100000, "phase_filter": "Show Previous + Demolished"}\n',
    "show_previous_and_new": PHASED + 'graphics {"view": 100000, "phase_filter": "Show Previous + New"}\n',
    "existing_phase": PHASED + 'graphics {"view": 100000, "phase": "Existing"}\n',
    "own_overrides": PHASED + 'phase_filter {"name": "Renovation", "new": "overridden", "demolished": "not-displayed", '
                              '"temporary": "not-displayed"}\n'
                     + 'phase {"overrides": {"new": {"cut": {"color": [0, 0, 200]}}}}\n'
                     + 'graphics {"view": 100000, "phase_filter": "Renovation"}\n',
    "primary_option": HOUSE + FACADE + 'modify {"id": 100002, "params": {"Design Option": "Facade: Brick"}}\n'
                      + 'modify {"id": 100004, "params": {"Design Option": "Facade: Glass"}}\n',
    "chosen_option": HOUSE + FACADE + 'modify {"id": 100002, "params": {"Design Option": "Facade: Brick"}}\n'
                     + 'modify {"id": 100004, "params": {"Design Option": "Facade: Glass"}}\n'
                     + 'graphics {"view": 100000, "options": {"Facade": "Glass"}}\n',
}


@pytest.mark.parametrize("case", sorted(DRAWN))
def test_phases_and_options_change_what_a_plan_draws(run, workdir, golden, case):
    """CATCHES: a rewrite whose plan shows new, existing, demolished and temporary elements otherwise than its phase and
    phase filter say (left out, by category, or overridden: existing halftone, demolished dashed red), or shows an
    option's elements in a view that doesn't show that option."""
    r = _run(run, workdir, DRAWN[case], "--cmd", PLAN)
    golden.check_run(r, f"drawn_{case}.txt")
    golden.check((workdir / "plan.svg").read_text(), f"drawn_{case}.svg")


def test_a_3d_render_follows_its_phase(run, workdir, golden):
    """CATCHES: a rewrite whose 3D view ignores the phase and phase filter it is given."""
    r = _run(run, workdir, PHASED + 'graphics {"view": "{3D}", "phase": "Existing", "phase_filter": "Show New"}\n',
             "--save", "phase.glb")
    golden.check_run(r, "glb_phase.txt")
