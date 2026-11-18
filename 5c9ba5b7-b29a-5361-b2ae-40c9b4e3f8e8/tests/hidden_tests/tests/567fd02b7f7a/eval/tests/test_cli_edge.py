"""Edge cases of the CLI contract: unusual file names in diagnostics and the
JSON `file` field, stdin decoding failures for every subcommand, flag
combinations, and outputs that overwrite inputs."""

import pytest

from conftest import Case

HELLO = '|box| "x"\n'
ERROR = '|box#a| { colr: red; }\n'
WARN = '{ .hot { fill: red; } }\n|box#a| "A"\n'

EDGE_CASES = {
    # file names that need escaping in JSON / appear verbatim in human diagnostics
    "json_file_name_with_quote_and_backslash": Case(("--json", 'we"ird\\name.lini'),
                                                    files={'we"ird\\name.lini': ERROR}),
    "json_file_name_with_tab": Case(("--json", "tab\there.lini"), files={"tab\there.lini": ERROR}),
    "human_file_name_with_spaces": Case(("my diagram.lini",), files={"my diagram.lini": ERROR}),
    "human_file_name_unicode": Case(("схема.lini",), files={"схема.lini": ERROR}),
    "dot_slash_path_kept": Case(("./a.lini",), files={"a.lini": ERROR}),
    "parent_relative_path_kept": Case(("../work/a.lini",), files={"a.lini": ERROR}),
    "fmt_check_odd_name": Case(("fmt", "--check", "my file.lini"), files={"my file.lini": "|box#a|{fill:red}\n"}),
    # control characters in diagnostics
    "stray_control_char_human": Case(("c.lini",), files={"c.lini": '|box| "a"\x01\n'}),
    "stray_control_char_json": Case(("--json", "c.lini"), files={"c.lini": '|box| "a"\x01\n'}),
    "stray_delete_char_json": Case(("--json", "c.lini"), files={"c.lini": '|box| "a" \x7f\n'}),
    "escapes_in_label": Case(("e.lini",), files={"e.lini": '|box| "say \\"hi\\"\\\\ \\n next\\tcol"\n'}),
    "unterminated_escape_at_eof": Case(("e.lini",), files={"e.lini": '|box| "abc\\'}),
    # stdin decode failures for each subcommand
    "fmt_stdin_not_utf8": Case(("fmt", "-"), stdin=b"\xff\xfe\n"),
    "fmt_check_stdin_not_utf8": Case(("fmt", "--check", "-"), stdin=b"\xff\xfe\n"),
    "desugar_stdin_not_utf8": Case(("desugar", "-"), stdin=b"\xff\xfe\n"),
    "highlight_stdin_not_utf8": Case(("highlight", "-"), stdin=b"\xff\xfe\n"),
    "json_stdin_not_utf8": Case(("--json", "-"), stdin=b"\xff\xfe\n"),
    "empty_stdin_compile": Case(("-",), stdin=b""),
    "empty_stdin_desugar": Case(("desugar", "-"), stdin=b""),
    "utf8_bom_input": Case(("b.lini",), files={"b.lini": "﻿" + HELLO}),
    # flag combinations
    "html_embed_font": Case(("--format", "html", "--embed-font", "a.lini"), files={"a.lini": '|box| "Hi"\n'}),
    "theme_embed_font": Case(("--theme", "dark", "--embed-font", "a.lini"), files={"a.lini": '|box| "Hi"\n'}),
    "static_theme_pair_html": Case(("--static", "--theme", "high-contrast/blueprint", "--format", "html", "a.lini"),
                                   files={"a.lini": '|box| "Hi" { fill: --accent; }\n'}),
    "check_json_no_warn_strict_conflict": Case(("--check", "--json", "--no-warn", "--strict", "a.lini"),
                                               files={"a.lini": HELLO}),
    "check_html_writes_nothing": Case(("--check", "--format", "html", "-o", "o.html", "w.lini"),
                                      files={"w.lini": WARN}, outputs=("o.html",)),
    "no_fs_static_json": Case(("--no-fs", "--static", "--json", "w.lini"), files={"w.lini": WARN}),
    "strict_no_warnings_exit_zero": Case(("--strict", "-o", "o.svg", "a.lini"), files={"a.lini": HELLO},
                                         outputs=("o.svg",)),
    "output_overwrites_input": Case(("a.lini", "-o", "a.lini"), files={"a.lini": HELLO}, outputs=("a.lini",)),
    "output_named_dash_is_a_file": Case(("a.lini", "-o", "-"), files={"a.lini": HELLO}, outputs=("-",)),
    "check_error_keeps_output_file": Case(("--check", "-o", "o.svg", "e.lini"),
                                          files={"e.lini": ERROR, "o.svg": "kept\n"}, outputs=("o.svg",)),
    "warning_and_error_order": Case(("m.lini",), files={"m.lini": '{\n.a { fill: red; }\n.b { fill: blue; }\n}\n|box#x| "X" { opacity: 5; }\nx -> xx\n'}),
}


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_cli_edge(run_case, golden, name):
    """CATCHES: file names not escaped in the JSON `file` field or altered in
    `file:line:col` prefixes, control characters printed raw, stdin decode
    failures with the wrong message/exit code in a subcommand, flag
    combinations that interact differently, or -o targets handled specially."""
    assert run_case(EDGE_CASES[name]) == golden(name)
