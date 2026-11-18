"""`lini fmt`: in-place rewrite, --check, --stdout, stdin, parse errors, and
the canonical style it prints (indentation, declaration grouping, comments,
blank lines, table alignment, draw: wrapping)."""

import os

import pytest

from conftest import Case

UGLY = '{|box|{radius:4}}\n|box#x|"hi"\n|group#g|{direction:column}[\n|box#a|\n|box#b|\n]\na  ->   b\n'
PRETTY = '|box#a| "A"\n|box#b| "B"\n\na -> b\n'
BROKEN = '|box#a| "A" {\n  fill: red;\n'

FMT_MODE_CASES = {
    "in_place_rewrites_file": Case(("fmt", "u.lini"), files={"u.lini": UGLY}, outputs=("u.lini",)),
    "stdout_leaves_file": Case(("fmt", "--stdout", "u.lini"), files={"u.lini": UGLY}, outputs=("u.lini",)),
    "stdin_to_stdout": Case(("fmt", "-"), stdin=UGLY),
    "stdin_with_stdout_flag": Case(("fmt", "--stdout", "-"), stdin=UGLY),
    "check_would_reformat": Case(("fmt", "--check", "u.lini"), files={"u.lini": UGLY}, outputs=("u.lini",)),
    "check_stdin_would_reformat": Case(("fmt", "--check", "-"), stdin=UGLY),
    "check_wins_over_stdout": Case(("fmt", "--check", "--stdout", "u.lini"), files={"u.lini": UGLY},
                                   outputs=("u.lini",)),
    "check_subdirectory_name": Case(("fmt", "--check", "src/u.lini"), files={"src/u.lini": UGLY}),
    "parse_error_in_place": Case(("fmt", "b.lini"), files={"b.lini": BROKEN}, outputs=("b.lini",)),
    "parse_error_check": Case(("fmt", "--check", "b.lini"), files={"b.lini": BROKEN}),
    "parse_error_stdin": Case(("fmt", "-"), stdin=BROKEN),
    "lex_error": Case(("fmt", "--stdout", "l.lini"), files={"l.lini": '|box#a| "open\n'}),
    "missing_file": Case(("fmt", "missing.lini")),
    "missing_file_check": Case(("fmt", "--check", "missing.lini")),
    "directory_input": Case(("fmt", "d"), files={"d/.keep": ""}),
    "not_utf8": Case(("fmt", "bad.lini"), files={"bad.lini": b"\xff\xfe\n"}),
    "comment_only_file": Case(("fmt", "--stdout", "e.lini"), files={"e.lini": "\n\n// just a note\n\n\n"}),
    "semantic_error_still_formats": Case(("fmt", "--stdout", "s.lini"),
                                         files={"s.lini": "|box#a|{colr:red}\n|nosuch#b|\n"}),
    "crlf_line_endings": Case(("fmt", "--stdout", "w.lini"), files={"w.lini": '|box#a| "A"\r\n|box#b|\r\n'}),
    "no_trailing_newline": Case(("fmt", "--stdout", "n.lini"), files={"n.lini": '|box#a| "A"'}),
}

# Inputs harvested from the documented canonical style [SPEC 20] — each printed
# with `fmt --stdout`.
STYLE_INPUTS = {
    "head_label": '|box#x| "hi"\n',
    "bracket_text_child": '|box#x|[ "hi" ]\n',
    "bare_id": "|#cat|\n",
    "bare_string": '"Apple"\n',
    "class_chain": "|box#x| .hot.loud\n",
    "label_class_style": '|box#api| "API" .hot{fill:red}\n',
    "children_one_per_line": "|group#g|{direction:column}[\n|box#a|\n|box#b|\n]\n",
    "config_decls_share_line": "|group#g| { cell: 1 2; direction: column; gap: 16 } [\n|box#a|\n]\n",
    "comment_breaks_decl_group": "|group#g| {\n  direction: row;\n  // note\n  gap: 10;\n} [\n  |box#a|\n]\n",
    "stylesheet_layout": "{layout:grid}\n",
    "stylesheet_var": "{--brand:#ff6600}\n",
    "stylesheet_type_rule": "{|box|{radius:6}}\n",
    "stylesheet_class_rule": "{.hot{stroke-width:2}}\n",
    "stylesheet_id_rule": "{#hero{fill:gold}}\n",
    "stylesheet_descendant": "{|table| |box|{padding:4 8}}\n",
    "stylesheet_define": "{|treat::box|{radius:5}}\n",
    "comma_groups": "|line#dim|{points:0 0,10 10}\n",
    "repeat_track": "{layout:grid;\ncolumns:repeat(3)}\n",
    "bindings_and_functions": "{my_r=5; scale(n)=(100 * 1.2 ^ n)}\n|box#a| { padding: (8 * 2); width: scale(2) }\n",
    "numeric_forms": "{ --a: +3; --b: .5; }\n",
    "links": 'a -> b\na -> b "x"\na & b -> c\na -> b -> c\na --> b\na ---> b\na ~> b\n',
    "link_style_labels": 'a -> b {along:0.3, 0.7}[ "near a" "near b" ]\n',
    "link_classes": 'a -> b .loud\na -> b .c1.c2\na -> b "flows" .loud\na.b:left -> c\n',
    "phases_blank_line": "{|box|{radius:4}}\n|box#x|\na -> b\n",
    "interleaved_body": "|group#g| [\n  a -> b\n  |box#m|\n  m -> a\n]\n",
    "interleaved_sequence_root": "{layout:sequence}\n|box#a|\na -> b\n|loop#l| [ b -> a ]\n",
    "trailing_comment": '|box#a| "A"   // the hero\n|box#b| "B"\n',
    "trailing_comment_on_decl": "{\n  w = 10;   // the width\n}\n|box#a|\n",
    "trailing_comment_phase_break": '|box#a| "A"\n|box#b| "B"  // hero\na -> b\n',
    "leading_comment": '|box#a| "A"\n// about b\n|box#b| "B"\n',
    "blank_lines_collapse": "|box#a|\n\n\n\n|box#b|\n",
    "table_alignment": '|table#t|{columns:80, 80}[\n"A" "Quantity"\n"Apple" "3"\n]\n',
    "entity_alignment": '|entity#e| "Users" [\n"id" "int"\n"name" "text"\n]\n',
    "define_entity_alignment": '{ |myent::entity| {} }\n|myent#f| [\n"id" "int"\n"name" "text"\n]\n',
    "repeated_columns_last_wins": '|table#t| { columns: 80; columns: 80, 80 } [\n"a" "b"\n"ccc" "d"\n]\n',
    "styled_cell_row_steps_out": '|table#t|{columns:80, 80}[\n"A" "Qty"\n"Apple"{color:red} "3"\n"Mango" "5"\n]\n',
    "comment_before_children": "|box#p| { fill: red } [\n  // kids\n  |oval#a|\n]\n",
    "data_lists": "|chart#c| [\n|bars| { data: 9,15,24 }\n|dots| { data: 10 20,30 40 }\n]\n",
    "draw_wraps_at_budget": "|sketch#bar| { draw: move(-150, 0) up(10) chamfer(1.5) right(40):thread point():a right(260) chamfer(1.5) down(10); mirror: x-axis; }\n",
    "draw_each_move_new_line": "|sketch#plate| { draw: move(0, 0) right(60) close() move(20, 15) circle(6); }\n",
    "draw_short_inline": "|sketch#s| { draw: move(0, 0) right(10); }\n",
    "mates_and_measures": 'a:left||b:right{gap:-10}\nbar:thread   (o)   { side: left; tol: h6 }\nbar:left (-) bar:right{side:bottom}\nbolt <- "THRU"\n',
    "annotation_label_block": 'a:left (-) a:right [ "W" |feature-control| "flatness" { tol: 0.1 } ]\n',
    "text_label_block_inline": 'a -> b [ "x" "y" ]\n',
    "comment_in_label_block": 'a -> b [\n  // why\n  "x"\n  "y"\n]\n',
    "capsule_endpoints": 'cat -> |cyl#db|\n|cyl#db| -> cat\na -> |box| -> c\na & b -> |gnd|\nx - |component#U9|.p4\n|cyl#db|:left -> x\na -> |#cat|\n',
    "glued_capsule_op": "a -|gnd|- b\n",
    "one_ended_label_wires": 'u7.diag - "NSTDBY"\nu7.diag -> "NSTDBY"\nu7.diag -< "NSTDBY"\nu7.diag -<> "NSTDBY"\nu7.diag -* "NSTDBY"\nu7.diag -- "NSTDBY" { stroke: red; }\n',
    "classed_text_leaf": '{ .card-title { font-size: 17; } }\n"Starter" .card-title { color: red }\n',
    "floorplan_vocabulary": (
        "{layout: floorplan; unit: m; scale: 0.02; thickness: 0.15}\n"
        "|wall#outer| {draw: move(0, 0) right(7.2):north down(4.8):east left(7.2):south close():west} [\n"
        "|door#entry| { on: south; at: 3; swing: right }\n|window#w1| { on: north; at: 0.9; width: 1.8 }\n]\n"
        "|stairs| { steps: 14; translate: 6 3 }\nouter:west (-) outer:east { side: top }\n"
    ),
    "nested_deep": '|group#a|[|group#b|[|group#c|[|box#d| "deep" {fill:red;stroke:blue}]]]\n',
    "semicolon_siblings": '|row| [ |box| "a"; |box| "b"; |box| "c" ]\n',
    "expressions_and_colours": "{ --c: oklch(0.7, 0.1, 200); }\n|box#a| { fill: gradient(--rose, --sky); stroke: rgb(10,20,30); opacity: 0.5 }\n",
    "long_head_wraps": '|box#a| "A fairly long label that keeps going" .first.second.third { fill: --teal-wash; stroke: --teal-ink; stroke-width: 3; radius: 12; padding: 24 }\n',
}

STYLE_CASES = {f"style_{k}": Case(("fmt", "--stdout", "in.lini"), files={"in.lini": v}) for k, v in STYLE_INPUTS.items()}


@pytest.mark.parametrize("name", sorted(FMT_MODE_CASES))
def test_fmt_modes(run_case, golden, name):
    """CATCHES: fmt rewriting the file under --check/--stdout, not rewriting it in
    place by default, a wrong `FILE: would reformat` message or exit code, stdin
    not going to stdout, or a parse/I-O failure with the wrong message, exit code
    (1 parse, 2 I/O) or a clobbered file."""
    assert run_case(FMT_MODE_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(STYLE_CASES))
def test_fmt_canonical_style(run_case, golden, name):
    """CATCHES: a formatter whose canonical style differs — indentation, `key: value;`
    grouping, collapsed style-only heads, label/class order, children layout,
    comment and blank-line placement, table column padding, draw: wrapping, or
    number/expression spelling."""
    assert run_case(STYLE_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", ["style_label_class_style", "style_table_alignment", "style_draw_wraps_at_budget",
                                  "style_trailing_comment_phase_break", "style_capsule_endpoints"])
def test_fmt_is_idempotent(run, workdir, name, golden):
    """CATCHES: a formatter that is not a fixed point — formatting its own output
    changes it again, or `fmt --check` flags already-canonical output."""
    expected = golden(name).split("--- stdout\n", 1)[1].rsplit("\n--- stderr\n", 1)[0]
    (workdir / "f.lini").write_text(expected)
    again = run(["fmt", "--stdout", "f.lini"])
    assert again.stdout.decode() == expected
    check = run(["fmt", "--check", "f.lini"])
    assert (check.returncode, check.stdout, check.stderr) == (0, b"", b"")
    rewrite = run(["fmt", "f.lini"])
    assert (rewrite.returncode, rewrite.stdout, rewrite.stderr) == (0, b"", b"")
    assert (workdir / "f.lini").read_text() == expected


def test_fmt_in_place_then_check_passes(run, workdir):
    """CATCHES: an in-place fmt whose result still fails `fmt --check` (the check
    and the rewrite disagreeing about what canonical means)."""
    (workdir / "u.lini").write_text(UGLY)
    before = run(["fmt", "--check", "u.lini"])
    assert (before.returncode, before.stderr) == (1, b"u.lini: would reformat\n")
    assert run(["fmt", "u.lini"]).returncode == 0
    after = run(["fmt", "--check", "u.lini"])
    assert (after.returncode, after.stdout, after.stderr) == (0, b"", b"")
    assert (workdir / "u.lini").read_text() == run(["fmt", "-"], input=UGLY).stdout.decode()


def test_fmt_leaves_canonical_file_untouched(run, workdir):
    """CATCHES: an in-place fmt that rewrites (re-touches) a file that is already
    canonical, or that fails to rewrite a non-canonical sibling in the same run
    of the tool."""
    canonical = workdir / "p.lini"
    canonical.write_text(PRETTY)
    os.utime(canonical, (1_000_000_000, 1_000_000_000))
    r = run(["fmt", "p.lini"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    assert canonical.read_text() == PRETTY
    assert canonical.stat().st_mtime == 1_000_000_000
    ugly = workdir / "u.lini"
    ugly.write_text(UGLY)
    assert run(["fmt", "u.lini"]).returncode == 0
    assert ugly.read_text() == (
        '{\n  |box| { radius: 4; }\n}\n\n|box#x| "hi"\n|group#g| { direction: column; } [\n'
        "  |box#a|\n  |box#b|\n]\n\na -> b\n"
    )
