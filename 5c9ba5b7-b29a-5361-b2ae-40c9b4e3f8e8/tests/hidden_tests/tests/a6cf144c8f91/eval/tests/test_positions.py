"""Diagnostic positions and multiplicity: columns count characters while JSON
offsets count bytes; tabs, CRLF and missing final newlines; a compile stops
at its first hard error while --json reports every diagnostic."""

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

CASES = {
    "multibyte_before_error": '|box| "héllo 你好" { colr: red; }\n',
    "emoji_before_error": '|box| "🙂🙂" { colr: red; }\n|oval| "ok"\n',
    "tabs_before_error": '|box|\t"x"\t{ colr: red; }\n',
    "crlf_second_line": '|box| "a"\r\n|box| { colr: red; }\r\n',
    "no_final_newline": '|box| { colr: red; }',
    "error_on_last_line_deep": '\n\n\n|group| [\n  |group| [\n    |box| { fill: rgb(1, 2); }\n  ]\n]\n',
    "many_errors": '{\n .a { fill: red; }\n .b { fill: red; }\n}\n|box| { colr: red; opacty: 1; }\n|box| { fill: nocolour; }\n',
    "warnings_only_many": '{\n .a { fill: red; }\n}\n|box| "x"\ncat -> dog\n|box#k| "y"\nkat -> dog\n',
    "multiline_span": '|box| {\n  fill:\n    nocolour;\n}\n',
    "unicode_identifier_char": '|box#café| "x"\n',
    "lex_error_after_unicode_comment": '// ünïcödé ✓\n|box| "x" $\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_human_position(run, workdir, name):
    """CATCHES: line:col computed in bytes instead of characters, tabs or '\\r' counted wrongly, or more than the first hard error printed by a compile."""
    write_files(workdir, {"p.lini": CASES[name]})
    r = run(["p.lini"])
    assert outcome(r) == G(f"human_{name}")


@pytest.mark.parametrize("name", sorted(CASES))
def test_json_position(run, name):
    """CATCHES: JSON spans whose start/end are not byte offsets, whose line/col/endLine/endCol are not character positions, or a JSON document that omits diagnostics after the first."""
    r = run(["--json", "-"], input=CASES[name])
    assert outcome(r) == G(f"json_{name}")


def test_fmt_table_alignment_with_non_ascii(run):
    """CATCHES: table-cell padding computed with a different width measure than the reference for accented and CJK cells."""
    r = run(["fmt", "-"], input='|table| { columns: auto, auto; } [\n"Café" "x"\n"Cafe" "y"\n"你好" "z"\n"plain" "w"\n]\n')
    assert outcome(r) == G("fmt_non_ascii_table")


def test_strict_promotes_all_warnings(run, workdir):
    """CATCHES: --strict printing only the first warning or exiting 0 when several warnings fire."""
    write_files(workdir, {"w.lini": CASES["warnings_only_many"]})
    r = run(["--strict", "--check", "w.lini"])
    assert outcome(r) == G("strict_many_warnings")
