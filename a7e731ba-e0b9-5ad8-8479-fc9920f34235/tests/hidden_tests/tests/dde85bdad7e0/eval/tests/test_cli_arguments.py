"""Command-line parsing: help output, argument conflicts, invalid option values and stdin
decoding errors, each with exact stdout, stderr and exit status.
"""

import pytest

from conftest import format_both_ways, outcome

HELP_INVOCATIONS = {
    "root_long": ["--help"],
    "root_short": ["-h"],
    "help_subcommand": ["help"],
    "help_format": ["help", "format"],
    "format_long": ["format", "--help"],
    "format_short": ["format", "-h"],
    "to_yaml_help": ["to-yaml", "--help"],
    "git_filter_help": ["git-filter", "--help"],
    "git_filter_short": ["git-filter", "-h"],
    "git_filter_adopt_help": ["git-filter", "adopt", "--help"],
    "git_filter_smudge_help": ["git-filter", "smudge", "--help"],
}


@pytest.mark.parametrize("name", sorted(HELP_INVOCATIONS))
def test_help_output(name, run, golden):
    """CATCHES: missing or reworded help text, wrong long/short help selection, or a non-zero
    exit status for help requests."""
    assert outcome(run(HELP_INVOCATIONS[name])) == golden(f"help_{name}")


ERROR_INVOCATIONS = {
    "no_arguments": [],
    "unknown_subcommand": ["render"],
    "help_with_unknown_flag": ["--help", "--bogus"],
    "short_help_with_unknown_flag": ["-h", "--nope"],
    "unknown_flag_alone": ["--bogus"],
    "version_flag": ["--version"],
    "format_unknown_flag": ["format", "--colour", "x.yaml"],
    "stdin_path_with_paths": ["format", "--stdin-file-path", "a.yaml", "b.yaml"],
    "stdin_path_with_check": ["format", "--stdin-file-path", "a.yaml", "--check"],
    "stdin_path_with_diff": ["format", "--diff", "--stdin-file-path", "a.yaml"],
    "stdin_path_missing_value": ["format", "--stdin-file-path"],
    "wrap_invalid": ["format", "--wrap", "wide", "--stdin-file-path", "a.md"],
    "wrap_zero": ["format", "--wrap", "0", "--stdin-file-path", "a.md"],
    "wrap_sentence_zero": ["format", "--wrap", "sentence:0", "--stdin-file-path", "a.md"],
    "wrap_sentence_junk": ["format", "--wrap", "sentence:x", "--stdin-file-path", "a.md"],
    "line_width_zero": ["format", "--line-width", "0", "--stdin-file-path", "a.yaml"],
    "line_width_negative": ["format", "--line-width", "-3", "--stdin-file-path", "a.yaml"],
    "line_width_text": ["format", "--line-width", "wide", "--stdin-file-path", "a.yaml"],
    "prose_width_zero": ["format", "--prose-width", "0", "--stdin-file-path", "a.yaml"],
    "indent_width_zero": ["format", "--indent-width", "0", "--stdin-file-path", "a.yaml"],
    "table_widths_invalid": ["format", "--table-widths", "auto", "--stdin-file-path", "a.md"],
    "to_yaml_missing_path": ["to-yaml"],
    "to_yaml_line_width_zero": ["to-yaml", "--stdin-file-path", "a.json", "--line-width", "0"],
    "to_yaml_with_paths": ["to-yaml", "--stdin-file-path", "a.json", "extra.json"],
    "git_filter_no_subcommand": ["git-filter"],
    "git_filter_clean_missing_filename": ["git-filter", "clean"],
    "git_filter_smudge_bad_width": ["git-filter", "smudge", "--stdin-filename", "a.md", "--markdown-wrap-at-column", "x"],
    "git_filter_unknown": ["git-filter", "explode"],
}


@pytest.mark.parametrize("name", sorted(ERROR_INVOCATIONS))
def test_argument_errors(name, run, golden):
    """CATCHES: accepting conflicting or invalid arguments, different error wording, or a
    usage-error exit status other than the reference's (2 for parse errors)."""
    assert outcome(run(ERROR_INVOCATIONS[name], input="a:   1\n")) == golden(f"error_{name}")


@pytest.mark.parametrize(
    "path",
    ["notes.txt", "Makefile", "data.json", "archive.tar.gz", "README.MD", "config.YML", "script.PY", "analysis.r", "doc.RMD"],
)
def test_stdin_path_extension_dispatch(path, run, golden):
    """CATCHES: wrong file-type selection for `--stdin-file-path` (case-insensitive suffixes;
    unsupported suffixes, including JSON, must be an error in stdin mode)."""
    text = "#| label:   [a,b]\nkey:   [a,b]\n# Heading   text\n"
    assert outcome(run(["format", "--stdin-file-path", path], input=text)) == golden(f"dispatch_{path.replace('.', '_')}")


@pytest.mark.parametrize(
    "name, data",
    [
        ("utf16_le_bom", b"\xff\xfea\x00:\x00"),
        ("utf16_be_bom", b"\xfe\xff\x00a\x00:"),
        ("invalid_utf8", b"a: caf\xe9\n"),
        ("truncated_utf8", b"a: \xe2\x82"),
        ("utf8_bom_ok", "\ufeffa:   1\n".encode()),
    ],
)
def test_stdin_decoding(name, data, run, workdir, golden):
    """CATCHES: lossy decoding of stdin or files, accepting UTF-16 input, or rejecting a UTF-8
    BOM (which must be preserved), in stdin mode and in path-mode --check."""
    assert format_both_ways(run, workdir, "in.yaml", data) == golden(f"decode_{name}")


def test_paths_starting_with_dash_after_separator(run, workdir, golden):
    """CATCHES: treating a `--`-separated path that begins with `-` as an option."""
    (workdir / "-odd.yaml").write_text("a:   1\n")
    result = run(["format", "--", "-odd.yaml"])
    assert outcome(result, workdir, ["-odd.yaml"]) == golden("dash_path")


def test_options_after_paths(run, workdir, golden):
    """CATCHES: rejecting options that follow positional PATHS."""
    (workdir / "a.yaml").write_text("a:\n  - 1\n  - 2\n")
    result = run(["format", "a.yaml", "--compact", "--check"])
    assert outcome(result, workdir, ["a.yaml"]) == golden("options_after_paths")


def test_wrap_option_forms(run, golden):
    """CATCHES: misparsing the documented `--wrap` forms (`paragraph`, `sentence:<n>`, integer)."""
    text = "First sentence is here. Second sentence follows it and is a bit longer than that.\nThird line.\n"
    observed = {
        form: outcome(run(["format", "--stdin-file-path", "a.md", "--wrap", form], input=text))
        for form in ["paragraph", "sentence", "sentence:25", "25", "none"]
    }
    assert observed == golden("wrap_forms")


@pytest.mark.parametrize(
    "args",
    [
        ["format", "--stdin-file-path", "in.yaml"],
        ["to-yaml", "--stdin-file-path", "in.json"],
        ["git-filter", "clean", "--stdin-filename", "in.md"],
    ],
    ids=["format", "to_yaml", "git_filter_clean"],
)
def test_stdout_write_failure(args, workdir, env, golden):
    """CATCHES: ignoring a failed stdout write (here /dev/full) instead of reporting
    `failed to write stdout` against the input path with exit status 1."""
    from conftest import run_with_stdout_file

    text = '{"a":   1}\n' if args[0] == "to-yaml" else "a:   1\n"
    result = run_with_stdout_file(args, "/dev/full", input=text, cwd=workdir, env=env)
    observed = {"stderr": result.stderr.decode(), "status": result.returncode}
    assert observed == golden(f"stdout_full_{args[0]}")
