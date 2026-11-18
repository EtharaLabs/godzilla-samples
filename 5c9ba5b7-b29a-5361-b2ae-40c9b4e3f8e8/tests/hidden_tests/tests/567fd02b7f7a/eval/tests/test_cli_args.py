"""Argument parsing: help and version text, per-subcommand help, unknown and
conflicting flags, missing values and the exit code (3) for an invalid CLI."""

import pytest

from conftest import Case, transcript

HELLO = {"a.lini": '|box| "x"\n'}

HELP_CASES = {
    "help_long": Case(("--help",)),
    "help_short": Case(("-h",)),
    "help_subcommand": Case(("help",)),
    "help_with_input": Case(("a.lini", "--help"), files=HELLO),
    "help_of_fmt": Case(("help", "fmt")),
    "help_of_serve": Case(("help", "serve")),
    "help_of_desugar": Case(("help", "desugar")),
    "help_of_highlight": Case(("help", "highlight")),
    "help_of_theme": Case(("help", "theme")),
    "help_of_help": Case(("help", "help")),
    "fmt_help_long": Case(("fmt", "--help")),
    "fmt_help_short": Case(("fmt", "-h")),
    "serve_help": Case(("serve", "--help")),
    "serve_help_short": Case(("serve", "-h")),
    "desugar_help": Case(("desugar", "--help")),
    "highlight_help": Case(("highlight", "-h")),
    "theme_help": Case(("theme", "--help")),
}

VERSION_CASES = {
    "version_long": Case(("--version",)),
    "version_short": Case(("-V",)),
    "version_with_input": Case(("-V", "a.lini"), files=HELLO),
}

INVALID_CASES = {
    "no_arguments": Case(()),
    "unknown_long_flag": Case(("--bogus", "a.lini"), files=HELLO),
    "unknown_short_flag": Case(("-x", "a.lini"), files=HELLO),
    "removed_no_defaults_flag": Case(("--no-defaults", "missing.lini")),
    "no_warn_conflicts_strict": Case(("--no-warn", "--strict", "a.lini"), files=HELLO),
    "strict_conflicts_no_warn": Case(("--strict", "--no-warn", "a.lini"), files=HELLO),
    "watch_requires_output": Case(("--watch", "a.lini"), files=HELLO),
    "watch_rejects_stdin": Case(("--watch", "-o", "out.svg", "-"), stdin='|box| "x"\n', outputs=("out.svg",)),
    "format_unknown_value": Case(("--format", "pdf", "a.lini"), files=HELLO),
    "format_uppercase_value": Case(("--format", "SVG", "a.lini"), files=HELLO),
    "format_missing_value": Case(("a.lini", "--format"), files=HELLO),
    "output_missing_value": Case(("a.lini", "-o"), files=HELLO),
    "theme_missing_value": Case(("a.lini", "--theme"), files=HELLO),
    "two_inputs": Case(("a.lini", "b.lini"), files={**HELLO, "b.lini": '|box| "y"\n'}),
    "only_flags_no_input": Case(("--check", "--strict")),
    "input_then_subcommand": Case(("a.lini", "fmt"), files=HELLO),
    "help_unknown_subcommand": Case(("help", "nope")),
    "fmt_missing_input": Case(("fmt",)),
    "fmt_unknown_flag": Case(("fmt", "--strict", "a.lini"), files=HELLO),
    "fmt_two_inputs": Case(("fmt", "a.lini", "b.lini"), files=HELLO),
    "desugar_missing_input": Case(("desugar",)),
    "desugar_rejects_check": Case(("desugar", "--check", "a.lini"), files=HELLO),
    "highlight_missing_input": Case(("highlight",)),
    "theme_two_names": Case(("theme", "dark", "light")),
    "theme_rejects_flag": Case(("theme", "--json")),
    "serve_port_not_a_number": Case(("serve", "--port", "abc", "a.lini"), files=HELLO),
    "serve_port_out_of_range": Case(("serve", "--port", "70000", "a.lini"), files=HELLO),
    "serve_port_negative": Case(("serve", "--port", "-1", "a.lini"), files=HELLO),
    "serve_port_missing_value": Case(("serve", "--port")),
    "serve_rejects_output_flag": Case(("serve", "-o", "x.svg", "a.lini"), files=HELLO),
    "serve_two_paths": Case(("serve", "a.lini", "b.lini"), files=HELLO),
    "compile_flag_before_subcommand": Case(("--strict", "fmt", "a.lini"), files=HELLO),
    "repeated_switch": Case(("--static", "--static", "a.lini"), files=HELLO),
    "repeated_output": Case(("-o", "x.svg", "-o", "y.svg", "a.lini"), files=HELLO, outputs=("x.svg", "y.svg")),
    "repeated_format": Case(("--format", "svg", "--format", "html", "a.lini"), files=HELLO),
    "repeated_theme": Case(("--theme", "dark", "--theme", "light", "a.lini"), files=HELLO),
    "repeated_fmt_check": Case(("fmt", "--check", "--check", "a.lini"), files=HELLO),
    "repeated_serve_port": Case(("serve", "--port", "1", "--port", "2", "a.lini"), files=HELLO),
    "repeated_highlight_css": Case(("highlight", "--css", "--css")),
    "misspelled_flag_suggestion": Case(("--stat", "a.lini"), files=HELLO),
    "wrong_case_flag_suggestion": Case(("--Static", "a.lini"), files=HELLO),
    "misspelled_subcommand_flag": Case(("fmt", "--stdot", "a.lini"), files=HELLO),
    "output_equals_empty": Case(("--output=", "a.lini"), files=HELLO),
    "output_empty_value": Case(("-o", "", "a.lini"), files=HELLO),
    "format_equals_empty": Case(("--format=", "a.lini"), files=HELLO),
    "help_two_subcommands": Case(("help", "fmt", "serve")),
    "theme_name_after_double_dash": Case(("theme", "--", "--x")),
}

EQUALS_CASES = {
    "output_equals_form": Case(("a.lini", "--output=out.svg"), files=HELLO, outputs=("out.svg",)),
    "format_equals_form": Case(("--format=html", "a.lini"), files=HELLO),
    "theme_equals_form": Case(("--theme=dark", "a.lini"), files=HELLO),
    "double_dash_input": Case(("-o", "out.svg", "--", "a.lini"), files=HELLO, outputs=("out.svg",)),
    "dash_prefixed_input_after_double_dash": Case(("--", "-weird.lini"), files={"-weird.lini": '|box| "w"\n'}),
    "help_flag_after_double_dash_is_a_path": Case(("--", "--help")),
    "short_output_attached_value": Case(("-oout.svg", "a.lini"), files=HELLO, outputs=("out.svg",)),
    "json_ignores_format": Case(("--json", "--format", "html", "a.lini"), files=HELLO),
    "help_wins_over_version": Case(("--help", "--version")),
    "version_wins_over_help": Case(("--version", "--help")),
    "short_help_before_subcommand": Case(("-h", "fmt")),
    "subcommand_help_ignores_input": Case(("fmt", "--help", "missing.lini")),
}


@pytest.mark.parametrize("name", sorted(HELP_CASES))
def test_help_text(run_case, golden, name):
    """CATCHES: help output that drifts from the reference — a missing or renamed
    flag, a changed description or default, wrong subcommand list, help printed
    to stderr instead of stdout, or a non-zero exit for -h/--help/help."""
    assert run_case(HELP_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(VERSION_CASES))
def test_version(run_case, golden, name):
    """CATCHES: a wrong version string or program name, version printed to stderr,
    or -V not short-circuiting before the input is read."""
    assert run_case(VERSION_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(INVALID_CASES))
def test_invalid_cli(run_case, golden, name):
    """CATCHES: invalid invocations that are accepted, that exit with a code other
    than 3, that print a different clap-style error/usage block, or that touch the
    filesystem (e.g. --watch on stdin writing the output) before rejecting."""
    assert run_case(INVALID_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(EQUALS_CASES))
def test_option_spellings(run_case, golden, name):
    """CATCHES: a parser that only accepts the space-separated `--flag value` form,
    mishandles `--flag=value`, or does not honour `--` ending option parsing."""
    assert run_case(EQUALS_CASES[name]) == golden(name)


def test_help_ignores_terminal_width(run, golden):
    """CATCHES: help text that wraps or reflows to the terminal width (COLUMNS),
    instead of the reference's fixed, unwrapped layout."""
    for columns in ("40", "200"):
        r = run(["--help"], env_overrides={"COLUMNS": columns})
        assert transcript(r, None) == golden("help_long")
