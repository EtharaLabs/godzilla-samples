"""Compile diagnostics (SPEC 21): every documented error/warning condition, in the
human `file:line:col: level: message` form and in the `--json` document form."""

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

CASES = {
    'unterminated_string': '|box| "open\n',
    'value_expected': '|box| { width: 1..2; }\n',
    'bad_escape': '|box| "a\\qb"\n',
    'unexpected_char': '|box| "x" @\n',
    'operator_outside_group': '|box| { padding: 8 * 2; }\n',
    'single_quotes': "|box| 'hi'\n",
    'unknown_property': '|box| { colr: red; }\n',
    'unknown_property_far': '|box| { zzzzqqq: 1; }\n',
    'misused_property': '|box| { points: 0 0, 10 10; }\n',
    'cell_in_flow': '|box| { cell: 1 1; }\n',
    'inert_every_wearer': '{ .hot { points: 0 0, 1 1; } }\n|box| .hot\n',
    'class_never_worn': '{\n  .hot { fill: red; }\n  .cold { fill: blue; }\n}\n|box| .cold\n',
    'opacity_range': '|box| { opacity: 2; }\n',
    'translate_arity': '|box| { translate: 1 2 3; }\n',
    'padding_comma': '|box| { padding: 1, 2; }\n',
    'wavy_outline': '|box| { stroke-style: wavy; }\n',
    'data_space_list': '|chart| { categories: "a", "b", "c"; } [ |bars| { data: 9 15 24; } ]\n',
    'chart_layout_on_root': '{ layout: chart; }\n|bars| { data: 1, 2; }\n',
    'deferred_property': '|box| { legend: top; }\n',
    'routing_on_link': '|box#a|\n|box#b|\na -> b { routing: natural; }\n',
    'radius_on_hex': '|hex| { radius: 4; }\n',
    'font_weight_numeric': '|box| "x" { font-weight: 450; }\n',
    'gradient_on_text': '|box| "x" { color: gradient(--rose, --sky); }\n',
    'percent_width': '|box| { width: 50%; }\n',
    'href_javascript': '|box| "x" { href: "JavaScript:alert(1)"; }\n',
    'href_tab_in_scheme': '|box| "x" { href: " java\tscript:alert(1)"; }\n',
    'duplicate_id': '|box#a| "one"\n|oval#a| "two"\n',
    'unknown_type': '|bxo| "x"\n',
    'unknown_class': '|box| "x" .nope\n',
    'inheritance_cycle': '{\n  |a::b| {}\n  |b::a| {}\n}\n|a|\n',
    'shadows_builtin': '{ |box::oval| {} }\n|box|\n',
    'empty_bars': '| | "x"\n',
    'invalid_id': '|box#123| "x"\n',
    'reserved_id': '|box#lini-x| "x"\n',
    'class_in_bars': '|box.hot| "x"\n',
    'symbol_twice': '|icon| "bell" { symbol: user; }\n',
    'text_children': '"hello" [ |box| ]\n',
    'pin_on_text': '"hello" { pin: top; }\n',
    'decl_outside_block': 'fill: red;\n',
    'bare_node_on_canvas': 'api\n',
    'bare_type_in_stylesheet': '{ box { fill: red; } }\n',
    'missing_semicolon': '{ fill: red\n gap: 4; }\n',
    'style_block_non_decl': '|box| { |oval| }\n',
    'decl_in_brackets': '|box| [ fill: red; ]\n',
    'two_head_labels': '|box| "a" "b"\n',
    'label_after_class': '{ .hot { fill: red; } }\n|box| .hot "x"\n',
    'stylesheet_after_canvas': '|box| "x"\n{ gap: 4; }\n',
    'glued_compound_rule': '{ |box.hot| { fill: red; } }\n|box|\n',
    'spaced_class_chain': '{\n  .hot { fill: red; }\n  .loud { stroke: red; }\n}\n|box| .hot .loud\n',
    'unknown_endpoint_path': '|group#g| [ |box#child| "C" ]\n|box#a|\na -> g.chlid\n',
    'auto_create_shadows': '|group#g| [ |box#x| "X" ]\nx -> y\n',
    'auto_create_near_miss': '|box#cat| "Cat"\n|box#dog| "Dog"\ncta -> dog\n',
    'chain_mixes_ops': 'a -> b (-) c\n',
    'chain_too_short': 'a ->\n',
    'bare_o_marker': 'a -o b\n',
    'line_requires_points': '|line|\n',
    'link_in_stylesheet': '{\n  -> b\n}\n',
    'link_type_instance': '|-| "x"\n',
    'link_keyword_instance': '|link| "x"\n',
    'node_umbrella': '|node| "x"\n',
    'unknown_routing': '{ routing: curvy; }\na -> b\n',
    'unknown_side': 'a:middle -> b\n',
    'split_link_labels': 'a -> b "x" [ "y" ]\n',
    'capsule_in_drawing': '{ layout: drawing; }\n|rect#p| { width: 20; height: 20; }\np <- |note#n| "x"\n',
    'invalid_color': '|box| { fill: notacolour; }\n',
    'rgb_out_of_range': '|box| { fill: rgb(300, 0, 0); }\n',
    'oklch_invalid': '|box| { fill: oklch(2, 0.1, 30); }\n',
    'gradient_one_stop': '|box| { fill: gradient(--rose); }\n',
    'linear_gradient_no_angle': '|box| { fill: linear-gradient(--rose, --sky); }\n',
    'unquoted_text_value': '|box| { hint: hello; }\n',
    'invalid_pin': '|group| [ |box| { pin: middle; } ]\n',
    'negative_gap': '{ gap: -4; }\n|box|\n|box|\n',
    'skew_range': '|slant| { skew: 95; }\n',
    'skew_on_box': '|box| { skew: 20; }\n',
    'unknown_name_expr': '|box| { width: (foo * 2); }\n',
    'function_arity': '|box| { width: (sin(1, 2)); }\n',
    'spaced_call_paren': '|box| { fill: rgb (1, 2, 3); }\n',
    'hatch_on_stroke': '|box| { stroke: hatch(45); }\n',
    'image_missing': '|image| { src: "./logo.svg"; width: 20; height: 20; }\n',
    'grid_missing_columns': '{ layout: grid; }\n|box|\n',
    'grid_bad_track': '{ layout: grid; columns: wide; }\n|box|\n',
    'grid_cell_out_of_range': '{ layout: grid; columns: 80, 80, 80; }\n|box| { cell: 5 1; }\n',
    'nowrap_cannot_fit': '|box| "a long label that will never fit" { max-width: 80; text-wrap: nowrap; }\n',
    'child_wider_than_cap': '|box| { max-width: 80; } [ |box| { width: 200; } ]\n',
    'width_above_max': '|box| { width: 200; max-width: 120; }\n',
    'topic_outside_tree': '|topic| "x"\n',
    'tree_no_root': '{ layout: tree; }\n|box| "x"\n',
    'tree_two_roots': '{ layout: tree; }\n|topic| "A"\n|topic| "B"\n',
    'bilateral_side_top': '|mindmap| "R" [ |topic| "a" { side: top; } ]\n',
    'side_in_row_tree': '{ layout: tree; direction: row; }\n|topic| "R" [ |topic| "a" { side: left; } ]\n',
    'tree_unknown_direction': '{ layout: tree; direction: radial; }\n|topic| "R"\n',
    'loop_outside_sequence': '|loop| "x" [ a -> b ]\n',
    'else_outside_alt': '{ layout: sequence; }\n|box#a|\n|else| "x"\n',
    'sequence_note_no_place': '{ layout: sequence; }\n|box#a|\n|note| "x"\n',
    'sequence_bad_place': '{ layout: sequence; }\n|box#a|\n|note| "x" { place: under a; }\n',
    'place_outside_sequence': '|note| "x" { place: over a; }\n',
    'bars_outside_chart': '|bars| { data: 1, 2; }\n',
    'axis_outside_chart': '|axis| "x"\n',
    'slice_outside_pie': '|slice| { value: 3; }\n',
    'pie_with_series': '|pie| [ |bars| { data: 1, 2; } ]\n',
    'slice_with_children': '|pie| [ |slice| { value: 3; } [ |slice| { value: 1; } ] ]\n',
    'empty_chart': '|chart| { categories: "a"; }\n',
    'empty_pie': '|pie|\n',
    'series_data_and_fn': '|chart| [ |line| { data: 0 0, 1 1; fn: (x * 2); } ]\n',
    'series_no_data': '|chart| [ |line| ]\n',
    'arrow_marker_series': '|chart| { categories: "a", "b"; } [ |line| { data: 1, 2; marker: arrow; } ]\n',
    'data_category_mismatch': '|chart| { categories: "a", "b", "c"; } [ |bars| { data: 1, 2; } ]\n',
    'labels_count_mismatch': '|chart| { categories: "a", "b"; } [ |bars| { data: 1, 2; labels: "x"; } ]\n',
    'labels_on_fn': '|chart| [ |line| { fn: (x * 2); labels: "x"; } ]\n',
    'mark_without_axis': '|chart| { categories: "a", "b"; } [\n  |bars| { data: 1, 2; }\n  |mark| { at: 1; }\n]\n',
    'bubble_missing': '|chart| [ |bubble| { at: 1 2; } ]\n',
    'unknown_axis_id': '|chart| { categories: "a", "b"; } [\n  |axis#ms| { side: left; }\n  |bars| { data: 1, 2; axis: mz; }\n]\n',
    'range_bad': '|chart| { categories: "a", "b"; } [\n  |axis#y| { side: left; range: 1 2 3; }\n  |bars| { data: 1, 2; axis: y; }\n]\n',
    'range_equal_ends': '|chart| { categories: "a", "b"; } [\n  |axis#y| { side: left; range: 5 5; }\n  |bars| { data: 1, 2; axis: y; }\n]\n',
    'mark_bad_at': '|chart| { categories: "a", "b"; } [\n  |axis#y| { side: left; }\n  |bars| { data: 1, 2; axis: y; }\n  |mark| { axis: y; at: 1 2 3; }\n]\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_human_diagnostic(run, workdir, name):
    """CATCHES: a diagnostic with a different message text, level, line:col position, related span, exit code, or one that fires where the reference stays silent (or vice versa)."""
    write_files(workdir, {"d.lini": CASES[name]})
    r = run(["--check", "d.lini"])
    assert outcome(r) == G(f"human_{name}")


@pytest.mark.parametrize("name", sorted(CASES))
def test_json_diagnostic(run, name):
    """CATCHES: a --json record with a wrong stable code, family, severity, byte span, line/col/endLine/endCol, related span or suggestion."""
    r = run(["--json", "-"], input=CASES[name])
    assert outcome(r) == G(f"json_{name}")


def test_wire_hops_may_differ_in_one_chain(run):
    """CATCHES: rejecting 'a -> b --> c' as mixed operators; wire hops of one chain may each carry their own line style and marker."""
    r = run(["-"], input="a -> b --> c\n")
    assert outcome(r) == G("svg_wire_hops_may_differ")
