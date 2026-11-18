"""Help screens, usage errors, unknown commands and exit codes of the command-line surface."""

import pytest

from conftest import assert_golden, transcript

HELP_SCREENS = {
    "root_long": ["--help"],
    "root_short": ["-h"],
    "root_long_and_short": ["--help", "-h"],
    "root_short_twice": ["-h", "-h"],
    "help_command": ["help"],
    "help_format": ["help", "format"],
    "help_to_yaml": ["help", "to-yaml"],
    "help_git_filter": ["help", "git-filter"],
    "help_help": ["help", "help"],
    "help_git_filter_clean": ["help", "git-filter", "clean"],
    "help_git_filter_smudge": ["help", "git-filter", "smudge"],
    "format_long": ["format", "--help"],
    "format_short": ["format", "-h"],
    "to_yaml_long": ["to-yaml", "--help"],
    "to_yaml_short": ["to-yaml", "-h"],
    "git_filter_long": ["git-filter", "--help"],
    "git_filter_short": ["git-filter", "-h"],
    "git_filter_help_adopt": ["git-filter", "help", "adopt"],
    "git_filter_help_command": ["git-filter", "help"],
    "clean_long": ["git-filter", "clean", "--help"],
    "smudge_long": ["git-filter", "smudge", "--help"],
    "adopt_long": ["git-filter", "adopt", "--help"],
    "adopt_short": ["git-filter", "adopt", "-h"],
    "join_long": ["git-filter", "join", "--help"],
    "check_long": ["git-filter", "check", "--help"],
    "setup_long": ["git-filter", "setup", "--help"],
    "teardown_long": ["git-filter", "teardown", "--help"],
    "teardown_short": ["git-filter", "teardown", "-h"],
    "long_help_before_subcommand": ["--help", "format"],
    "short_help_before_subcommand": ["-h", "format"],
    "help_flag_then_other_flags": ["format", "--help", "--check", "--wrap", "bogus"],
}


@pytest.mark.parametrize("name", sorted(HELP_SCREENS))
def test_help_screen(name, run):
    """CATCHES: help text that differs in wording, option order, defaults shown ([default: 72], [default: fit],
    [default: 80]...), program name in the usage line, blank-line layout, short (-h) vs long (--help) variants,
    the extra trailing newline of the root help, or a help screen written to stderr / with a nonzero status."""
    assert_golden(transcript(run(HELP_SCREENS[name])), __file__, f"help_{name}")


USAGE_ERRORS = {
    "no_arguments": [],
    "git_filter_without_subcommand": ["git-filter"],
    "version_flag": ["--version"],
    "short_version_flag": ["-V"],
    "unknown_subcommand": ["bogus"],
    "help_unknown_subcommand": ["help", "bogus"],
    "git_filter_unknown_subcommand": ["git-filter", "bogus"],
    "unknown_flag_with_long_help": ["--foo", "--help"],
    "long_help_with_unknown_flag": ["--help", "--foo"],
    "short_help_with_unknown_flag": ["-h", "-x"],
    "root_unknown_flag_only": ["--frobnicate"],
    "format_unknown_long_flag": ["format", "--bogus"],
    "format_unknown_short_flag": ["format", "-x"],
    "format_negative_number": ["format", "--line-width", "-1"],
    "format_check_and_diff": ["format", "--check", "--diff"],
    "format_diff_and_check": ["format", "--diff", "--check", "a.md"],
    "format_check_twice": ["format", "--check", "--check"],
    "format_wrap_twice": ["format", "--wrap", "none", "--wrap", "sentence"],
    "format_wrap_missing_value": ["format", "--wrap"],
    "format_config_missing_value": ["format", "--config"],
    "format_stdin_path_missing_value": ["format", "--stdin-file-path"],
    "format_equals_value_for_flag": ["format", "--check=yes"],
    "to_yaml_missing_path": ["to-yaml"],
    "to_yaml_missing_path_value": ["to-yaml", "--stdin-file-path"],
    "to_yaml_rejects_wrap": ["to-yaml", "--stdin-file-path", "a.json", "--wrap", "none"],
    "to_yaml_rejects_positional": ["to-yaml", "--stdin-file-path", "a.json", "extra.json"],
    "to_yaml_rejects_check": ["to-yaml", "--stdin-file-path", "a.json", "--check"],
    "clean_missing_filename": ["git-filter", "clean"],
    "smudge_missing_filename": ["git-filter", "smudge"],
    "clean_rejects_width": ["git-filter", "clean", "--stdin-filename", "a.md", "--markdown-wrap-at-column", "40"],
    "smudge_zero_width": ["git-filter", "smudge", "--stdin-filename", "a.md", "--markdown-wrap-at-column", "0"],
    "smudge_text_width": ["git-filter", "smudge", "--stdin-filename", "a.md", "--markdown-wrap-at-column", "wide"],
    "adopt_zero_width": ["git-filter", "adopt", "--markdown-wrap-at-column", "0"],
    "join_rejects_paths": ["git-filter", "join", "a.md"],
    "check_rejects_yamark": ["git-filter", "check", "--yamark", "yamark"],
    "teardown_rejects_width": ["git-filter", "teardown", "--markdown-wrap-at-column", "72"],
    "setup_missing_repo_value": ["git-filter", "setup", "--repo"],
}


@pytest.mark.parametrize("name", sorted(USAGE_ERRORS))
def test_usage_error(name, run):
    """CATCHES: argument-parsing errors with the wrong exit status (must be 2), wrong stream (stderr, nothing on
    stdout), different error wording, missing 'tip:' lines, a different usage line, or accepting arguments
    and flags that the subcommand does not define (or that conflict, like --check with --diff)."""
    result = run(USAGE_ERRORS[name])
    assert result.returncode == 2
    assert result.stdout == b""
    assert_golden(transcript(result), __file__, f"usage_{name}")


def test_root_long_help_exact_text(run):
    """CATCHES: a root --help that drops the 'Run `yamark <COMMAND> --help`' hint, uses the binary's file name
    instead of 'yamark' in the usage line, or omits the trailing blank line printed after the help body."""
    result = run(["--help"])
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.startswith(
        b"A fast formatter for YAML and Markdown.\n\nRun `yamark <COMMAND> --help` for command-level help.\n\n"
        b"Usage: yamark <COMMAND>\n\n")
    assert result.stdout.endswith(b"  -h, --help\n          Print help (see a summary with '-h')\n\n")


def test_root_short_help_points_to_long_help(run):
    """CATCHES: a root -h that prints the long description or omits the "(see more with '--help')" hint."""
    result = run(["-h"])
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout == (
        b"A fast formatter for YAML and Markdown.\n\nUsage: yamark <COMMAND>\n\nCommands:\n"
        b"  format      \n"
        b"  to-yaml     Convert JSON-family input from stdin to formatted YAML\n"
        b"  git-filter  Git clean/smudge filter helpers for Markdown files\n"
        b"  help        Print this message or the help of the given subcommand(s)\n\n"
        b"Options:\n  -h, --help  Print help (see more with '--help')\n\n")


def test_no_arguments_prints_short_help_to_stderr(run):
    """CATCHES: running without a command succeeding, printing to stdout, or not showing the command list."""
    result = run([])
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == (
        b"A fast formatter for YAML and Markdown.\n\nUsage: executable <COMMAND>\n\nCommands:\n"
        b"  format      \n"
        b"  to-yaml     Convert JSON-family input from stdin to formatted YAML\n"
        b"  git-filter  Git clean/smudge filter helpers for Markdown files\n"
        b"  help        Print this message or the help of the given subcommand(s)\n\n"
        b"Options:\n  -h, --help  Print help (see more with '--help')\n")


def test_version_flag_is_not_supported(run):
    """CATCHES: rewrites that add a --version flag (the reference rejects it as an unexpected argument)."""
    result = run(["--version"])
    assert (result.returncode, result.stdout) == (2, b"")
    assert result.stderr == (b"error: unexpected argument '--version' found\n\nUsage: executable <COMMAND>\n\n"
                             b"For more information, try '--help'.\n")


def test_format_help_lists_defaults(run):
    """CATCHES: wrong documented defaults for wrap (72), table widths (fit), line width (80), prose width (72)
    and indent width (2) in `format --help`."""
    result = run(["format", "--help"])
    assert result.returncode == 0
    lines = result.stdout.decode().splitlines()
    assert "      --wrap <WRAP>                  [default: 72]" in lines
    assert ("      --table-widths <TABLE_WIDTHS>  Table widths: fit contents or preserve source widths "
            "[default: fit]") in lines
    assert "      --line-width <LINE_WIDTH>      [default: 80]" in lines
    assert "      --prose-width <PROSE_WIDTH>    [default: 72]" in lines
    assert "      --indent-width <INDENT_WIDTH>  [default: 2]" in lines


def test_format_help_hides_internal_verify_flag(run):
    """CATCHES: a release build that exposes internal switches in `format --help`; the option list must be
    exactly the documented set in this order."""
    result = run(["format", "--help"])
    options = [line.split()[0] for line in result.stdout.decode().splitlines() if line.startswith("      --")]
    assert options == ["--check", "--diff", "--diagnostics", "--stdin-file-path", "--config", "--wrap",
                       "--table-widths", "--canonical", "--preserve-footnotes", "--line-width", "--prose-width",
                       "--indent-width", "--compact", "--skip-embedded-formatters"]


COLOR_ENV = {"NO_COLOR": "", "CLICOLOR_FORCE": "1"}


@pytest.mark.parametrize("args", [["--help"], ["format", "-h"], ["git-filter", "adopt", "--help"]],
                         ids=["root", "format", "adopt"])
def test_forced_color_help(args, run):
    """CATCHES: help styling that differs when colors are forced (CLICOLOR_FORCE=1, as the documentation build
    does): bright-blue bold headings, cyan bold literals, bright-black placeholders and their reset codes."""
    result = run(args, env_overrides=COLOR_ENV)
    assert_golden(transcript(result), __file__, "color_" + "_".join(a.strip("-") for a in args))


def test_forced_color_usage_error(run):
    """CATCHES: error messages that are not styled (red bold 'error:', yellow argument, green tip) when colors
    are forced, or that keep styling when NO_COLOR is set."""
    colored = run(["format", "--bogus"], env_overrides=COLOR_ENV)
    assert colored.returncode == 2
    assert colored.stderr == (
        b"\x1b[1m\x1b[31merror:\x1b[0m unexpected argument '\x1b[33m--bogus\x1b[0m' found\n\n"
        b"  \x1b[32mtip:\x1b[0m to pass '\x1b[33m--bogus\x1b[0m' as a value, use '\x1b[32m-- --bogus\x1b[0m'\n\n"
        b"\x1b[1m\x1b[94mUsage:\x1b[0m \x1b[1m\x1b[36mexecutable format\x1b[0m \x1b[90m[OPTIONS]\x1b[0m "
        b"\x1b[90m[PATHS]...\x1b[0m\n\n"
        b"For more information, try '\x1b[1m\x1b[36m--help\x1b[0m'.\n")
    plain = run(["format", "--bogus"], env_overrides={"CLICOLOR_FORCE": "1", "NO_COLOR": "1"})
    assert b"\x1b[" not in plain.stderr
    assert plain.stderr.startswith(b"error: unexpected argument '--bogus' found\n")


@pytest.mark.parametrize("args", [["--help"], ["-h"]], ids=["long", "short"])
def test_help_to_closed_stdout(args, workdir, env):
    """CATCHES: crashing (or exiting 0) when the root help cannot be written because stdout is closed; the
    reference reports 'failed to print help' with the OS error and exits 1."""
    from conftest import run_with_closed_stdout
    result = run_with_closed_stdout(args, cwd=workdir, env=env)
    assert (result.returncode, result.stderr) == (1, b"error: failed to print help: Broken pipe (os error 32)\n")


def test_help_ignores_terminal_width_variables(run):
    """CATCHES: wrapping help text to $COLUMNS when stdout is not a terminal (the layout must stay identical)."""
    narrow = run(["format", "--help"], env_overrides={"COLUMNS": "40"})
    wide = run(["format", "--help"], env_overrides={"COLUMNS": "200"})
    assert narrow.returncode == wide.returncode == 0
    assert narrow.stdout == wide.stdout
    assert b"      --table-widths <TABLE_WIDTHS>  Table widths: fit contents or preserve source widths [default: fit]\n" \
        in narrow.stdout
