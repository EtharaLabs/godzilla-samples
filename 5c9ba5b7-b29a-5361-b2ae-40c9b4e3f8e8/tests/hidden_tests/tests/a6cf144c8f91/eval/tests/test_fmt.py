"""`lini fmt`: canonical formatting — in place, --check, --stdout and stdin."""

import os

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

MESSY = """{layout:grid;columns:repeat(2);gap:30;
--brand:#ff6600;
w=120; scale(n)=(100*1.2^n);
|box|{radius:6;}
   |svc::box|{fill:--teal-wash;stroke:--teal-ink}
.hot{stroke:--red-deep}
}
// leading comment
|svc#api|"API"   // trailing comment
|box#b|{fill:red}
|group#g|"G"[|box#x|"x";|box#y|"y"
x -> y]


|table#t|{columns:80,140;}[
"Fruit" "Qty"
"Apple" "12"
"Watermelon" "3" {color:--red-ink}
]
api -> b "q" .hot
"""

CASES = {
    "node_head_forms": '|box#x|[ "hi" ]\n|#cat|\n"Apple"\n|box#x2| .hot.loud\n|#y| .hot\n|box#api| "API" .hot{fill:red}\n',
    "group_body": '|group#g|{direction:column}[\n|box#a|\n|box#b|\n]\n',
    "group_comment_in_style": '|group#g|{\ndirection:row;\n    // note\ngap:10;\n}[\n|box#a|\n]\n',
    "stylesheet_rules": '{layout:grid;\ncolumns:repeat(3);\n--brand:#ff6600;\n|box|{radius:6}\n.hot{stroke-width:2}\n#hero{fill:gold}\n|table| |box|{padding:4 8}\n|table#main| |box|{fill:white}\n|treat::box|{radius:5}}\n',
    "bindings_and_groups": '{my_r=5;scale(n)=(100 * 1.2 ^ n)}\n|box#a| { padding: (8 * 2); width: scale(2 * my_r) }\n',
    "points_list": '|line#dim|{points:0 0,10 10;marker-end:arrow}\n',
    "link_forms": 'a -> b\na -> b "x"\na & b -> c\na -> b -> c\na --> b\na ---> b\na ~> b\na -> b {along:0.3, 0.7}[ "near a" "near b" ]\na -> b .loud\na -> b "flows" .c1.c2\na.b:left -> c\n',
    "link_ops_spacing": 'a   ->   b\nc <-> d\ne  *-*  f\ng -o< h\ni -+ j\nk >o-o< l\nm -<> n\n',
    "phases": '{|box|{radius:4}}\n|box#x|\na -> b\n',
    "interleaved_body": '|group#g| [\na  ->  b\n      |box#m|\n m -> a\n]\n',
    "sequence_root": '{layout:sequence}\n|box#a|\na -> b\n|loop#l| [ b -> a ]\n',
    "trailing_comments": '|box#a| "A"   // the hero\n|box#b| "B"  // second\na -> b\n',
    "comment_in_stylesheet": '{\n  w = 10;   // the width\n  direction: column;  // config\n}\n|box#a|\n',
    "leading_comment_kept": '|box#a|   "A"\n   // about b\n|box#b|"B"\n',
    "blank_runs_collapse": '|box#a|\n\n\n\n|box#b|\n\n\n',
    "table_alignment": '|table#t|{columns:80, 80}[\n"A" "Quantity"\n"Apple" "3"\n"Kiwi fruit" "1200"\n]\n',
    "table_styled_row": '|table#t|{columns:80, 80}[\n"A" "Qty"\n"Apple"{color:red} "3"\n"Mango" "5"\n]\n',
    "entity_alignment": '|entity#e| "Users" [\n"PK" "id" "int"\n"" "email" "varchar"\n"FK" "org_id" "int"\n]\n',
    "define_over_entity": '{ |myent::entity| {} }\n|myent#f| [\n"id" "int"\n"name" "text"\n]\n',
    "repeated_columns": '|table#t| { columns: 80; columns: 80, 80 } [\n"a" "b"\n"ccc" "d"\n]\n',
    "data_lists": '|chart#c| [\n|bars| { data: 9,15,24; }\n|dots| { data: 10 20,30 40; }\n]\n',
    "comment_before_children": '|box#p| { fill: red } [\n  // kids\n  |oval#a|\n]\n',
    "draw_wrap": '|sketch#bar| { draw: move(-150, 0) up(10) chamfer(1.5) right(40):thread point():a right(260) chamfer(1.5) down(10); mirror: x-axis; }\n',
    "draw_subpaths": '|sketch#plate| { draw: move(0, 0) right(60) close() move(20, 15) circle(6); }\n',
    "draw_short_inline": '|sketch#s|{draw:move(0,0) right(10)}\n',
    "mates_and_measures": '{layout:drawing}\na:left||b:right{gap:-10}\nbar:thread   (o)   { side: left; tol: h6 }\nbar:left (-) bar:right{side:bottom}\nbolt <- "THRU"\n',
    "dimension_label_block": 'a:left (-) a:right [ "W" |feature-control| "flatness" { tol: 0.1 } ]\n',
    "link_comment_in_labels": 'a -> b [\n// why\n"x"\n    "y"]\n',
    "numbers_canonical": '{ --a: +3; --b: .5; w = 1.50; h = -0.0; }\n|box| { width: 010; translate: +4 -.25; opacity: .750 }\n',
    "strings_escapes": '|box| "say \\"hi\\"\\n\\tback\\\\slash"\n|box| "  padded  "\n',
    "classed_text_leaf": '{ .card-title { font-size: 17; } }\n"Starter" .card-title { color: red }\n',
    "capsule_endpoints": 'cat -> |cyl#db|\n|cyl#db2| -> cat\na -> |box| -> c\na & b -> |gnd|\na -|gnd|- b\nx - |component#U9|.p4\n|cyl#db3|:left -> x\na -> |#cat|\n',
    "one_ended_wires": '{layout:schematic}\nu7.diag - "NSTDBY"\nu7.diag -> "NSTDBY"\nu7.diag -< "NSTDBY" { stroke: red; }\n',
    "long_style_breaks": '|box#a| "Label" { fill: --teal-wash; stroke: --teal-ink; color: --teal-ink; stroke-width: 1.5; radius: 12; padding: 10 20; }\n',
    "nested_deep": '|group#a|[|group#b|[|group#c|[|box#d|"deep"{fill:red}]]]\n',
    "semicolon_separated": '|topic| "A"; |topic| "B"; |box#c|; c -> d\n',
    "gradient_and_calls": '|box| { fill: gradient( --rose , --sky ); stroke: rgb( 10 , 20 , 30 ); }\n|box| { fill: linear-gradient(135,--rose,--sky); shadow: 2 4 8; }\n',
    "messy_full": MESSY,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_fmt_stdin_canonical(run, name):
    """CATCHES: a formatter whose canonical layout differs (indentation, declaration grouping, collapse rules, spacing of ops, number/string canonicalisation, comment placement, alignment)."""
    r = run(["fmt", "-"], input=CASES[name])
    assert outcome(r) == G(f"fmt_{name}")


@pytest.mark.parametrize("name", sorted(CASES))
def test_fmt_is_idempotent(run, name):
    """CATCHES: a formatter that is not a fixed point — formatting its own output must change nothing (fmt --check exits 0)."""
    once = run(["fmt", "-"], input=CASES[name])
    assert outcome(once) == G(f"fmt_{name}")
    twice = run(["fmt", "-"], input=once.stdout)
    assert outcome(twice) == outcome(once)


def test_fmt_rewrites_file_in_place(run, workdir):
    """CATCHES: fmt that prints instead of rewriting, or writes different text than --stdout shows."""
    write_files(workdir, {"m.lini": MESSY})
    r = run(["fmt", "m.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    expected = G("fmt_messy_full").split("--- stdout ---\n", 1)[1].split("--- stderr ---\n")[0]
    assert (workdir / "m.lini").read_text() == expected


def test_fmt_leaves_canonical_file_untouched(run, workdir):
    """CATCHES: fmt rewriting (and so touching the mtime of) a file that is already canonical."""
    write_files(workdir, {"c.lini": '|box#a| "A"\n'})
    os.utime(workdir / "c.lini", (1_000_000_000, 1_000_000_000))
    r = run(["fmt", "c.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    assert os.stat(workdir / "c.lini").st_mtime == 1_000_000_000
    assert (workdir / "c.lini").read_text() == '|box#a| "A"\n'
    write_files(workdir, {"n.lini": '|box#a|"A"\n'})
    os.utime(workdir / "n.lini", (1_000_000_000, 1_000_000_000))
    r = run(["fmt", "n.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    assert os.stat(workdir / "n.lini").st_mtime != 1_000_000_000
    assert (workdir / "n.lini").read_text() == '|box#a| "A"\n'


def test_fmt_stdout_does_not_rewrite(run, workdir):
    """CATCHES: fmt --stdout modifying the file it prints."""
    write_files(workdir, {"m.lini": MESSY})
    r = run(["fmt", "--stdout", "m.lini"])
    assert outcome(r) == G("fmt_messy_full")
    assert (workdir / "m.lini").read_text() == MESSY


def test_fmt_check_would_reformat(run, workdir):
    """CATCHES: fmt --check not exiting 1 with 'FILE: would reformat', or modifying the file."""
    write_files(workdir, {"m.lini": MESSY})
    r = run(["fmt", "--check", "m.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\nm.lini: would reformat\n"
    assert (workdir / "m.lini").read_text() == MESSY


def test_fmt_check_clean(run, workdir):
    """CATCHES: fmt --check failing or printing anything for an already-canonical file, while still flagging a non-canonical one."""
    write_files(workdir, {"c.lini": '{\n  gap: 10;\n}\n\n|box#a| "A"\n|box#b| "B"\n\na -> b\n',
                          "d.lini": '{ gap: 10; }\n|box#a| "A"\n|box#b| "B"\na -> b\n'})
    r = run(["fmt", "--check", "c.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    r = run(["fmt", "--check", "d.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\nd.lini: would reformat\n"


def test_fmt_check_stdin(run):
    """CATCHES: fmt --check on stdin not naming '<stdin>' in its would-reformat message."""
    r = run(["fmt", "--check", "-"], input="|box#a|{fill:red}\n")
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\n<stdin>: would reformat\n"


def test_fmt_check_with_stdout_writes_nothing(run, workdir):
    """CATCHES: --check combined with --stdout printing the formatted text (check must win and write nothing)."""
    write_files(workdir, {"m.lini": MESSY})
    r = run(["fmt", "--check", "--stdout", "m.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\nm.lini: would reformat\n"


def test_fmt_parse_error(run, workdir):
    """CATCHES: fmt rewriting a file it cannot parse, or reporting the error without its location/exit 1."""
    src = '|box#a| "A"\n|box#b| { fill: red\n'
    write_files(workdir, {"bad.lini": src})
    r = run(["fmt", "bad.lini"])
    assert outcome(r) == G("fmt_parse_error")
    assert (workdir / "bad.lini").read_text() == src


def test_fmt_glued_link_op_is_an_error(run):
    """CATCHES: lexing 'a->b' as a link; identifiers absorb '-', so the '>' that follows must be a located error."""
    r = run(["fmt", "-"], input="a->b\n")
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\n<stdin>:1:3: error: expected link-op line after '>'\n"


def test_fmt_incomplete_link_is_not_a_parse_error(run):
    """CATCHES: a formatter that rejects a dangling 'a ->' (fmt only parses; the endpoint-count rule belongs to compile)."""
    r = run(["fmt", "-"], input='|box#a| "A"\na ->\n')
    assert outcome(r) == 'exit: 0\n--- stdout ---\n|box#a| "A"\n\na ->\n--- stderr ---\n'


def test_fmt_lex_error_stdin(run):
    """CATCHES: fmt accepting an unterminated string instead of the located lex error."""
    r = run(["fmt", "-"], input='|box| "open\n')
    assert outcome(r) == G("fmt_lex_error")


def test_fmt_missing_file(run):
    """CATCHES: fmt on a missing file not failing with exit 2 and the OS message."""
    r = run(["fmt", "nope.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: nope.lini: No such file or directory (os error 2)\n"


def test_fmt_does_not_validate(run):
    """CATCHES: fmt rejecting files that parse but fail validation (unknown property/type); it only reformats."""
    r = run(["fmt", "-"], input='|nosuch#a|{colr:red}\n')
    assert outcome(r) == 'exit: 0\n--- stdout ---\n|nosuch#a| { colr: red; }\n--- stderr ---\n'


def test_fmt_empty_input(run):
    """CATCHES: fmt emitting a stray newline or failing on empty or blank-only input, or not trimming surplus blank lines after a comment."""
    r = run(["fmt", "-"], input="")
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    r = run(["fmt", "-"], input="\n\n\n")
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    r = run(["fmt", "-"], input="// c\n\n\n")
    assert outcome(r) == "exit: 0\n--- stdout ---\n// c\n\n--- stderr ---\n"


def test_fmt_requires_input(run):
    """CATCHES: fmt without an input not raising the usage error with exit 3."""
    r = run(["fmt"])
    assert outcome(r) == G("fmt_no_input")


def test_fmt_preserves_rendering(run, workdir):
    """CATCHES: a formatter that changes semantics — the formatted file must compile to the identical SVG."""
    write_files(workdir, {"m.lini": MESSY})
    before = run(["m.lini"])
    run(["fmt", "m.lini"])
    after = run(["m.lini"])
    assert outcome(after) == outcome(before)
    assert outcome(after) == G("messy_svg")
