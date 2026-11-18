"""CLI modes, path traversal, configuration loading, diff output and embedded-formatter dispatch.

These tests pin down documented command-line contracts that the converted
specification suite leaves open: stdin-mode restrictions, invalid option
values, path-selection errors (missing paths, FIFOs, dangling and device
symlinks), traversal rules (hidden paths, ignore files, extension case),
non-transactional multi-file runs, exact unified-diff rendering for large and
CR/CRLF inputs, every `yamark.toml` validation error, path-scoped template
layering, and how built-in and configured embedded formatters are invoked and
how their failures are reported.
"""

import os
import subprocess

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

ARGV_ECHO = '#!/bin/sh\ncat >/dev/null\nfor a in "$@"; do printf "%s\\n" "$a"; done\n'


def fake_bin(tmp_path, env, scripts):
    """Write executable scripts into tmp_path/bin and return env overrides putting it first on PATH."""
    bin_dir = tmp_path / "bin"
    write_tree(bin_dir, scripts, executable=list(scripts))
    return {"PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"}


def empty_path(tmp_path):
    """Env overrides with a PATH that contains no formatter executables."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    return {"PATH": str(empty)}


# ---------------------------------------------------------------------------
# Command-line validation
# ---------------------------------------------------------------------------


def test_stdin_file_path_cannot_be_combined_with_paths(run, workdir):
    """CATCHES: an implementation that silently ignores PATHS (or formats them) when --stdin-file-path is also given, instead of failing with exit 2 and the documented message before touching any file."""
    files = {"b.md": "#  Title\n"}
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "a.md", "b.md"], input="#  Stdin\n")
    assert result.stdout == b""
    assert result.stderr.decode() == "error: --stdin-file-path cannot be used with PATHS\n"
    assert result.returncode == 2
    assert read_tree(workdir) == as_bytes(files)


@pytest.mark.parametrize("flag", ["--check", "--diff"])
def test_stdin_file_path_cannot_be_combined_with_check_or_diff(run, flag):
    """CATCHES: an implementation that accepts --check/--diff in stdin mode (e.g. printing a diff of stdin or exiting 1 on change) instead of rejecting the combination with exit 2 and the exact message."""
    result = run(["format", flag, "--stdin-file-path", "a.md"], input="#  Stdin\n")
    assert result.stdout == b""
    assert result.stderr.decode() == "error: --stdin-file-path cannot be used with --check or --diff\n"
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--line-width", "0"], "invalid value '0' for '--line-width <LINE_WIDTH>': value must be greater than 0"),
        (["--prose-width", "0"], "invalid value '0' for '--prose-width <PROSE_WIDTH>': value must be greater than 0"),
        (["--indent-width", "0"], "invalid value '0' for '--indent-width <INDENT_WIDTH>': value must be greater than 0"),
        (["--line-width", "1.5"], "invalid value '1.5' for '--line-width <LINE_WIDTH>': invalid positive integer: invalid digit found in string"),
        (["--line-width="], "invalid value '' for '--line-width <LINE_WIDTH>': invalid positive integer: cannot parse integer from empty string"),
        (["--wrap", "foo"], "invalid value 'foo' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>"),
        (["--wrap", "0"], "invalid value '0' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>"),
        (["--wrap", "sentence:0"], "invalid value 'sentence:0' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>"),
        (["--wrap", "Paragraph"], "invalid value 'Paragraph' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>"),
        (["--table-widths", "x"], "invalid value 'x' for '--table-widths <TABLE_WIDTHS>': table-widths must be fit or preserve"),
        (["--table-widths", "Fit"], "invalid value 'Fit' for '--table-widths <TABLE_WIDTHS>': table-widths must be fit or preserve"),
    ],
)
def test_format_rejects_invalid_option_values(run, args, message):
    """CATCHES: an implementation that accepts zero or non-integer widths, case-insensitive or zero --wrap values, or unknown --table-widths values, or that reports them with a different message or a non-2 exit status."""
    result = run(["format", "--stdin-file-path", "a.md", *args], input="#  T\n")
    assert result.stdout == b""
    assert result.stderr.decode() == f"error: {message}\n\nFor more information, try '--help'.\n"
    assert result.returncode == 2


def test_to_yaml_rejects_zero_indent_width(run):
    """CATCHES: an implementation of to-yaml that accepts --indent-width 0 (or clamps it) instead of rejecting it as a usage error with exit 2."""
    result = run(["to-yaml", "--stdin-file-path", "a.json", "--indent-width", "0"], input='{"a": 1}\n')
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: invalid value '0' for '--indent-width <INDENT_WIDTH>': value must be greater than 0\n"
        "\n"
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("args", "unknown"),
    [
        (["--bogus", "--help"], "--bogus"),
        (["-h", "--frob"], "--frob"),
        (["--help", "-x", "--y"], "-x"),
    ],
)
def test_root_help_with_unknown_flag_is_a_usage_error(run, args, unknown):
    """CATCHES: an implementation that prints root help (exit 0) when --help/-h is mixed with an unknown root flag, or that reports a later unknown flag instead of the first one."""
    result = run(args)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        f"error: unexpected argument '{unknown}' found\n"
        "\n"
        "Usage: yamark <COMMAND>\n"
        "\n"
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_root_unknown_flag_without_subcommand_is_a_usage_error(run):
    """CATCHES: an implementation that ignores an unknown root flag (or prints root help) when no subcommand is given, instead of a clap-style 'unexpected argument' error with exit 2."""
    result = run(["--bogus"])
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: unexpected argument '--bogus' found\n"
        "\n"
        "Usage: executable <COMMAND>\n"
        "\n"
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("stdin", "message"),
    [
        (b"\xff\xfe{\x00}\x00", "unsupported encoding: UTF-16 BOM"),
        (b"\xfe\xff\x00{\x00}", "unsupported encoding: UTF-16 BOM"),
        (b'{"a": "\xc3("}', "invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 7"),
    ],
)
def test_to_yaml_rejects_undecodable_stdin(run, stdin, message):
    """CATCHES: an implementation of to-yaml that decodes UTF-16 input or replaces invalid UTF-8 bytes instead of failing with a path-prefixed decoding error and exit 1."""
    result = run(["to-yaml", "--stdin-file-path", "data.json"], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == f"data.json:1:1: error: {message}\n"
    assert result.returncode == 1


@pytest.mark.parametrize("path", ["notes.txt", "data.json", "Makefile", "page.markdown"])
def test_stdin_mode_rejects_unsupported_file_types(run, path):
    """CATCHES: an implementation that passes stdin through unchanged (or skips it) for an unsupported --stdin-file-path, including JSON-family paths that path mode merely skips, instead of failing with 'unsupported file type'."""
    result = run(["format", "--stdin-file-path", path], input="#  Title\n")
    assert result.stdout == b""
    assert result.stderr.decode() == f"{path}:1:1: error: unsupported file type\n"
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# Path selection and traversal
# ---------------------------------------------------------------------------


def test_format_without_paths_formats_current_directory(run, workdir):
    """CATCHES: an implementation that requires PATHS (usage error) or formats nothing when `yamark format` is run without paths, instead of traversing the current directory and writing changed files."""
    files = {
        "a.md": "#  Title\n",
        "sub/b.yaml": "key:   value\n",
        "sub/c.yml": "ok: true\n",
        "notes.txt": "#  untouched\n",
    }
    write_tree(workdir, files)
    result = run(["format"])
    assert result.stdout == b"4 files scanned, 2 formatted, 1 unchanged, 1 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({"a.md": "# Title\n", "sub/b.yaml": "key: value\n"}))
    assert read_tree(workdir) == expected


def test_check_without_paths_checks_current_directory(run, workdir):
    """CATCHES: an implementation that treats `format --check` with no PATHS as a usage error or writes files, instead of checking the current directory, printing the summary on stderr and exiting 1."""
    files = {"a.md": "#  Title\n", "b.md": "# Fine\n"}
    write_tree(workdir, files)
    result = run(["format", "--check"])
    assert result.stdout == b""
    assert result.stderr.decode() == "2 files scanned, 1 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_without_paths_uses_dot_prefixed_paths(run, workdir):
    """CATCHES: an implementation that strips the implicit './' root from diff headers or writes files when `format --diff` runs without PATHS."""
    files = {"a.md": "#  Title\n", "z.yaml": "a:  1\n"}
    write_tree(workdir, files)
    result = run(["format", "--diff"])
    assert result.stdout == (
        b"--- ./a.md\n+++ ./a.md\n@@ -1 +1 @@\n-#  Title\n+# Title\n"
        b"--- ./z.yaml\n+++ ./z.yaml\n@@ -1 +1 @@\n-a:  1\n+a: 1\n"
    )
    assert result.stderr.decode() == "2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_single_missing_path_is_an_error_without_summary(run, workdir):
    """CATCHES: an implementation that counts a missing explicit path as skipped or failed in a summary, instead of aborting with 'path does not exist' on stderr, no stdout and exit 1."""
    result = run(["format", "missing.md"])
    assert result.stdout == b""
    assert result.stderr.decode() == "missing.md:1:1: error: path does not exist\n"
    assert result.returncode == 1
    assert read_tree(workdir) == {}


def test_missing_path_among_several_aborts_before_writing(run, workdir):
    """CATCHES: an implementation that formats the existing paths and then reports the missing one; the whole run must abort before any file is written."""
    files = {"a.md": "#  Title\n"}
    write_tree(workdir, files)
    result = run(["format", "a.md", "missing.md"])
    assert result.stdout == b""
    assert result.stderr.decode() == "missing.md:1:1: error: path does not exist\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_fifo_single_path_is_not_a_file_or_directory(run, workdir):
    """CATCHES: an implementation that opens (and blocks on) a named pipe given as the only path, or reports it as missing, instead of rejecting it as 'path is not a file or directory'."""
    os.mkfifo(workdir / "pipe.md")
    result = run(["format", "pipe.md"])
    (workdir / "pipe.md").unlink()
    assert result.stdout == b""
    assert result.stderr.decode() == "pipe.md:1:1: error: path is not a file or directory\n"
    assert result.returncode == 1
    assert read_tree(workdir) == {}


def test_fifo_among_several_paths_aborts_before_writing(run, workdir):
    """CATCHES: an implementation that skips a named pipe among several explicit paths, or writes the regular files before rejecting it."""
    files = {"a.md": "#  Title\n"}
    write_tree(workdir, files)
    os.mkfifo(workdir / "pipe.md")
    result = run(["format", "a.md", "pipe.md"])
    (workdir / "pipe.md").unlink()
    assert result.stdout == b""
    assert result.stderr.decode() == "pipe.md:1:1: error: path is not a file or directory\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_symlink_to_device_as_single_path_is_rejected(run, workdir):
    """CATCHES: an implementation that follows an explicit symlink to a character device and reads it as an empty file (reporting it unchanged) instead of rejecting it as 'path is not a file or directory'."""
    os.symlink("/dev/null", workdir / "null.md")
    result = run(["format", "null.md"])
    assert result.stdout == b""
    assert result.stderr.decode() == "null.md:1:1: error: path is not a file or directory\n"
    assert result.returncode == 1
    assert read_tree(workdir) == {}


def test_symlink_to_device_among_several_paths_is_ignored(run, workdir):
    """CATCHES: an implementation that errors on, or counts as scanned, an explicit symlink to a device when several paths are given; such a root is silently ignored and the other file is still formatted."""
    files = {"a.md": "#  Title\n"}
    write_tree(workdir, files)
    os.symlink("/dev/null", workdir / "null.md")
    result = run(["format", "a.md", "null.md"])
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({"a.md": "# Title\n"})
    assert os.readlink(workdir / "null.md") == "/dev/null"


def test_dangling_symlink_as_single_path_does_not_exist(run, workdir):
    """CATCHES: an implementation that reports a dangling symlink as 'not a file or directory' or skips it, instead of 'path does not exist' with exit 1."""
    os.symlink("missing-target.md", workdir / "dangling.md")
    result = run(["format", "dangling.md"])
    assert result.stdout == b""
    assert result.stderr.decode() == "dangling.md:1:1: error: path does not exist\n"
    assert result.returncode == 1
    assert read_tree(workdir) == {}


def test_dangling_symlink_among_several_paths_aborts(run, workdir):
    """CATCHES: an implementation that skips a dangling symlink among several explicit paths, or writes the other files, instead of aborting the run with 'path does not exist'."""
    files = {"a.md": "#  Title\n"}
    write_tree(workdir, files)
    os.symlink("missing-target.md", workdir / "dangling.md")
    result = run(["format", "a.md", "dangling.md"])
    assert result.stdout == b""
    assert result.stderr.decode() == "dangling.md:1:1: error: path does not exist\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_duplicate_explicit_paths_are_formatted_once(run, workdir):
    """CATCHES: an implementation that scans and counts the same file twice when it is named twice (or via ./ and a plain spelling)."""
    files = {"a.md": "#  Title\n"}
    write_tree(workdir, files)
    result = run(["format", "--check", "a.md", "a.md", "./a.md"])
    assert result.stdout == b""
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_overlapping_roots_keep_first_spelling_and_argument_order(run, workdir):
    """CATCHES: an implementation that sorts all candidates globally, reports a file twice when it is reachable from overlapping roots, or labels it with the later root's spelling instead of the first one seen."""
    files = {"a.md": "#  A\n", "b.md": "#  B\n", "sub/x.md": "#  X\n"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "sub", ".", "sub/x.md"])
    assert result.stdout == (
        b"--- sub/x.md\n+++ sub/x.md\n@@ -1 +1 @@\n-#  X\n+# X\n"
        b"--- ./a.md\n+++ ./a.md\n@@ -1 +1 @@\n-#  A\n+# A\n"
        b"--- ./b.md\n+++ ./b.md\n@@ -1 +1 @@\n-#  B\n+# B\n"
    )
    assert result.stderr.decode() == "3 files scanned, 3 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_output_follows_explicit_argument_order(run, workdir):
    """CATCHES: an implementation that sorts explicit file arguments by name (or emits diffs in completion order of parallel workers) instead of the order given on the command line."""
    files = {"a.md": "#  A\n", "b.md": "#  B\n", "c.yaml": "c:   3\n"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "c.yaml", "b.md", "a.md"])
    assert result.stdout == (
        b"--- c.yaml\n+++ c.yaml\n@@ -1 +1 @@\n-c:   3\n+c: 3\n"
        b"--- b.md\n+++ b.md\n@@ -1 +1 @@\n-#  B\n+# B\n"
        b"--- a.md\n+++ a.md\n@@ -1 +1 @@\n-#  A\n+# A\n"
    )
    assert result.stderr.decode() == "3 files scanned, 3 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_extension_matching_is_ascii_case_insensitive(run, workdir):
    """CATCHES: an implementation that only recognises lower-case extensions, so `.MD`, `.QMD`, `.RMD`, `.YML` and `.Py` files would be counted as skipped instead of formatted."""
    files = {
        "a.MD": "#  Upper\n",
        "b.QMD": "#  Quarto\n",
        "c.RMD": "#  R Markdown\n",
        "d.YML": "k:   v\n",
        "e.Py": "#| echo:   false\nx = 1\n",
        "f.TXT": "#  skipped\n",
    }
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"6 files scanned, 5 formatted, 0 unchanged, 1 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        "a.MD": "# Upper\n",
        "b.QMD": "# Quarto\n",
        "c.RMD": "# R Markdown\n",
        "d.YML": "k: v\n",
        "e.Py": "#| echo: false\nx = 1\n",
    }))
    assert read_tree(workdir) == expected


def test_traversal_skips_hidden_files_and_directories(run, workdir):
    """CATCHES: an implementation that walks into dot-directories or formats dot-files during directory traversal."""
    files = {
        "a.md": "#  Visible\n",
        ".hidden.md": "#  Hidden file\n",
        ".hid/b.md": "#  Hidden dir\n",
        "sub/.c.yaml": "k:   v\n",
    }
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected["a.md"] = b"# Visible\n"
    assert read_tree(workdir) == expected


def test_explicit_hidden_paths_are_selected(run, workdir):
    """CATCHES: an implementation that applies the hidden-path filter to explicitly named files or directory roots; passing a hidden path explicitly selects it."""
    files = {
        ".hidden.md": "#  Hidden file\n",
        ".hid/b.md": "#  Hidden dir\n",
        ".hid/.deeper.md": "#  Still hidden\n",
    }
    write_tree(workdir, files)
    result = run(["format", ".hidden.md", ".hid"])
    assert result.stdout == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({".hidden.md": "# Hidden file\n", ".hid/b.md": "# Hidden dir\n"}))
    assert read_tree(workdir) == expected


def test_dot_ignore_file_is_respected_without_git(run, workdir):
    """CATCHES: an implementation that ignores `.ignore` files, or only honours them inside a Git repository."""
    files = {
        ".ignore": "skip.md\nvendor/\n",
        "keep.md": "#  Keep\n",
        "skip.md": "#  Skip\n",
        "vendor/v.yaml": "k:   v\n",
    }
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected["keep.md"] = b"# Keep\n"
    assert read_tree(workdir) == expected


def test_gitignore_has_no_effect_outside_a_git_repository(run, workdir):
    """CATCHES: an implementation that applies `.gitignore` patterns even when the directory is not inside a Git repository; Git ignore rules only apply within a repository."""
    files = {".gitignore": "skip.md\n", "keep.md": "#  Keep\n", "skip.md": "#  Skip\n"}
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({"keep.md": "# Keep\n", "skip.md": "# Skip\n"}))
    assert read_tree(workdir) == expected


def test_gitignore_is_respected_inside_a_git_repository(run, workdir, env):
    """CATCHES: an implementation that does not read `.gitignore` during traversal of a Git repository, or that refuses to format an ignored file named explicitly."""
    subprocess.run(["git", "init", "-q"], cwd=workdir, env=env, check=True)
    files = {".gitignore": "skip.md\nbuild/\n", "keep.md": "#  Keep\n", "skip.md": "#  Skip\n", "build/out.md": "#  Out\n"}
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    explicit = run(["format", "skip.md"])
    assert explicit.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert explicit.stderr.decode() == ""
    assert explicit.returncode == 0
    tree = {k: v for k, v in read_tree(workdir).items() if not k.startswith(".git/")}
    expected = as_bytes(files)
    expected.update(as_bytes({"keep.md": "# Keep\n", "skip.md": "# Skip\n"}))
    assert tree == expected


def test_empty_files_are_unchanged(run, workdir):
    """CATCHES: an implementation that adds a newline to (or fails on) empty Markdown, YAML and Python files."""
    files = {"a.md": "", "b.yaml": "", "c.py": "", "d.qmd": ""}
    write_tree(workdir, files)
    result = run(["format", "--check", "."])
    assert result.stdout == b""
    assert result.stderr.decode() == "4 files scanned, 0 formatted, 4 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_undecodable_files_fail_while_others_are_written(run, workdir):
    """CATCHES: an implementation that aborts the whole run (or writes nothing) when some inputs cannot be decoded, that decodes UTF-16 BE or lossily replaces bad bytes, or that orders the errors by argument instead of by path."""
    files = {
        "be.md": b"\xfe\xff\x00#\x00 \x00T",
        "good.md": "#  Good\n",
        "lone.yaml": b"a: 1\n\x80\n",
        "trunc.md": b"# T \xe2\x82",
        "bad.py": b"ok\xc3\x28",
    }
    write_tree(workdir, files)
    result = run(["format", "trunc.md", "be.md", "good.md", "lone.yaml", "bad.py"])
    assert result.stdout == b"5 files scanned, 1 formatted, 0 unchanged, 0 skipped, 4 failed\n"
    assert result.stderr.decode() == (
        "bad.py:1:1: error: failed to read file: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 2\n"
        "be.md:1:1: error: failed to read file: unsupported encoding: UTF-16 BOM\n"
        "lone.yaml:1:1: error: failed to read file: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 5\n"
        "trunc.md:1:1: error: failed to read file: invalid UTF-8: incomplete utf-8 byte sequence from index 4\n"
    )
    assert result.returncode == 1
    expected = as_bytes(files)
    expected["good.md"] = b"# Good\n"
    assert read_tree(workdir) == expected


def test_check_mode_prints_summary_before_failures_on_stderr(run, workdir):
    """CATCHES: an implementation that prints the --check summary on stdout, prints failure diagnostics before the summary, or exits 0 when a file fails even though another is merely unchanged."""
    files = {
        "good.md": "#  Good\n",
        "bad.yaml": "# fmt: markdown\nitems: [one, two]\n",
        "fine.yaml": "ok: 1\n",
    }
    write_tree(workdir, files)
    result = run(["format", "--check", "good.md", "bad.yaml", "fine.yaml"])
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "3 files scanned, 1 formatted, 1 unchanged, 0 skipped, 1 failed\n"
        "bad.yaml:2:8: error: fmt: markdown targets a scalar value\n"
    )
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_mode_with_only_unchanged_files_prints_no_diff(run, workdir):
    """CATCHES: an implementation that prints empty diff headers for unchanged files or exits 1 from --diff when nothing would change."""
    files = {"fine.yaml": "ok: 1\n", "fine.md": "# Fine\n", "skip.txt": "#  T\n"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "fine.yaml", "fine.md", "skip.txt"])
    assert result.stdout == b""
    assert result.stderr.decode() == "3 files scanned, 0 formatted, 2 unchanged, 1 skipped, 0 failed\n"
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


# ---------------------------------------------------------------------------
# Explicit configuration with directory traversal
# ---------------------------------------------------------------------------


def test_explicit_config_replaces_discovered_configs_during_traversal(run, workdir):
    """CATCHES: an implementation that still discovers or merges a nearer yamark.toml when --config is given for a directory run; the explicit file applies to every selected path."""
    files = {
        "cfg.toml": '[format]\nwrap = "sentence"\n',
        "docs/yamark.toml": '[format]\nwrap = "none"\n',
        "docs/a.md": "One. Two.\n",
        "docs/deep/b.md": "Three. Four.\n",
    }
    write_tree(workdir, files)
    result = run(["format", "--config", "cfg.toml", "docs"])
    assert result.stdout == b"3 files scanned, 2 formatted, 0 unchanged, 1 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({"docs/a.md": "One.\nTwo.\n", "docs/deep/b.md": "Three.\nFour.\n"}))
    assert read_tree(workdir) == expected


def test_invalid_explicit_config_aborts_directory_run(run, workdir):
    """CATCHES: an implementation that formats files with defaults (or prints a summary) when the explicit --config for a directory run is invalid."""
    files = {"cfg.toml": "[format]\nbogus = 1\n", "docs/a.md": "#  Title\n", "docs/b.md": "#  Other\n"}
    write_tree(workdir, files)
    result = run(["format", "--config", "cfg.toml", "docs"])
    assert result.stdout == b""
    assert result.stderr.decode() == "cfg.toml:1:1: error: unknown format config key: format.bogus\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_config_table_widths_preserve_and_cli_override(run, workdir):
    """CATCHES: an implementation that ignores `[format].table_widths = "preserve"` or lets the config value win over an explicit --table-widths flag."""
    files = {"yamark.toml": '[format]\ntable_widths = "preserve"\n'}
    write_tree(workdir, files)
    table = "| a | b |\n|-------|---|\n| 1 | 22222 |\n"
    write_tree(workdir, {"t.md": table})
    preserved = run(["format", "--check", "t.md"])
    assert preserved.stdout == b""
    assert preserved.stderr.decode() == "1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert preserved.returncode == 0
    fitted = run(["format", "--stdin-file-path", "t.md", "--table-widths", "fit"], input=table)
    assert fitted.stdout == b"| a   | b     |\n| --- | ----- |\n| 1   | 22222 |\n"
    assert fitted.stderr.decode() == ""
    assert fitted.returncode == 0
    assert read_tree(workdir) == as_bytes({**files, "t.md": table})


# ---------------------------------------------------------------------------
# Diff rendering
# ---------------------------------------------------------------------------


def test_diff_renders_crlf_lines_without_carriage_returns(run, workdir):
    """CATCHES: an implementation that copies CRLF line endings into the unified diff body (or treats CRLF and LF lines as different) instead of emitting LF-terminated diff lines."""
    files = {"crlf.md": "#  T\r\n\r\ntext\r\n"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "crlf.md"])
    assert result.stdout == b"--- crlf.md\n+++ crlf.md\n@@ -1,3 +1,3 @@\n-#  T\n+# T\n \n text\n"
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_splits_lone_carriage_return_lines(run, workdir):
    """CATCHES: an implementation that only splits diff lines on LF, so a CR-only file would appear as one long line in the diff."""
    files = {"cr.md": "#  T\r\rtext\r"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "cr.md"])
    assert result.stdout == b"--- cr.md\n+++ cr.md\n@@ -1,3 +1,3 @@\n-#  T\n+# T\n \n text\n"
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_marks_removed_line_without_final_newline(run, workdir):
    """CATCHES: an implementation that omits the `\\ No newline at end of file` marker after a removed final line lacking a newline."""
    files = {"space.md": " "}
    write_tree(workdir, files)
    result = run(["format", "--diff", "space.md"])
    assert result.stdout == b"--- space.md\n+++ space.md\n@@ -1 +1 @@\n- \n\\ No newline at end of file\n+\n"
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_marks_context_line_without_final_newline(run, workdir):
    """CATCHES: an implementation that adds a final newline to YAML, or that drops the no-newline marker when the unterminated last line is unchanged context."""
    files = {"nn.yaml": "a:   1\r\nb: 2"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "nn.yaml"])
    assert result.stdout == b"--- nn.yaml\n+++ nn.yaml\n@@ -1,2 +1,2 @@\n-a:   1\n+a: 1\n b: 2\n\\ No newline at end of file\n"
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_of_bom_only_markdown_keeps_bom_and_adds_newline(run, workdir):
    """CATCHES: an implementation that strips a lone UTF-8 BOM from Markdown, leaves the file without a final newline, or hides the BOM bytes from the diff lines."""
    files = {"bom.md": "\ufeff"}
    write_tree(workdir, files)
    result = run(["format", "--diff", "bom.md"])
    assert result.stdout == "--- bom.md\n+++ bom.md\n@@ -1 +1 @@\n-\ufeff\n\\ No newline at end of file\n+\ufeff\n".encode()
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_large_diff_with_trailing_removal_after_resync(run, workdir):
    """CATCHES: an implementation whose large-input diff fallback mis-aligns or drops lines when the formatted side runs out first (a flow mapping collapsed after 2000+ unchanged lines), or that emits one giant hunk."""
    source = "a:   1\n" + "".join(f"k{i:04d}: v\n" for i in range(2005)) + "k: {\n  a: 1\n}\n"
    files = {"a.yaml": source}
    write_tree(workdir, files)
    result = run(["format", "--diff", "a.yaml"])
    assert result.stdout == (
        b"--- a.yaml\n+++ a.yaml\n"
        b"@@ -1,4 +1,4 @@\n-a:   1\n+a: 1\n k0000: v\n k0001: v\n k0002: v\n"
        b"@@ -2004,6 +2004,5 @@\n k2002: v\n k2003: v\n k2004: v\n-k: {\n+k:\n   a: 1\n-}\n"
    )
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_large_jsonl_stream_diff_inserts_every_document_marker(run, workdir):
    """CATCHES: an implementation whose large-input diff fallback loses the trailing insertion once the original lines are exhausted, or that renders the `---` insertions as remove/add pairs."""
    count = 1416
    source = "".join(f"{{n: {i}}}\n" for i in range(count))
    files = {"records.yaml": source}
    write_tree(workdir, files)
    result = run(["format", "--diff", "records.yaml"])
    body = "".join(f"+---\n {{n: {i}}}\n" for i in range(count))
    assert result.stdout.decode() == f"--- records.yaml\n+++ records.yaml\n@@ -1,{count} +1,{2 * count} @@\n{body}"
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


# ---------------------------------------------------------------------------
# yamark.toml validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("[bogus]\nx = 1\n", "unknown config key: bogus"),
        ("[template]\nfoo = []\n", "unknown template config key: template.foo"),
        ("[format]\ntable_widths = 3\n", "format.table_widths must be a string"),
        ('[format]\ntable_widths = "wide"\n', "format.table_widths must be fit or preserve"),
        ('[format]\nmarkdown_horizontal_rule = "___"\n', 'format.markdown_horizontal_rule must be "---" or "***"'),
        ('[template]\nadd_delimiters = [{ open = "", close = ">>" }]\n', "template.add_delimiters.open must not be empty"),
        ('[template]\nreplace_delimiters = [{ open = "<<", close = "" }]\n', "template.replace_delimiters.close must not be empty"),
    ],
)
def test_format_and_template_config_errors(run, workdir, toml, message):
    """CATCHES: an implementation that accepts unknown top-level or [template] keys, non-string or unknown table_widths, horizontal-rule markers other than --- and ***, or empty template delimiters, or that words these errors differently."""
    files = {"yamark.toml": toml}
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "in.md", "--config", "yamark.toml"], input="#  T\n")
    assert result.stdout == b""
    assert result.stderr.decode() == f"yamark.toml:1:1: error: {message}\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[embedded." py"]\nformatter = "ruff"\n', "embedded formatter names must be non-empty and trimmed"),
        ('[embedded.""]\nformatter = "ruff"\n', "embedded formatter names must be non-empty and trimmed"),
        ('[embedded.skip]\nformatter = "ruff"\n', "reserved fmt directive name: skip"),
        ('[embedded."skip file"]\nformatter = "ruff"\n', "reserved fmt directive name: skip file"),
        ('[embedded.off]\nformatter = "ruff"\n', "reserved fmt directive name: off"),
        ('[embedded.on]\nformatter = "ruff"\n', "reserved fmt directive name: on"),
        ('[embedded.table]\nformatter = "ruff"\n', "reserved fmt directive name: table"),
        ('[embedded.py]\nformatter = "ruff"\nextra = 1\n', "unknown embedded formatter entry key: extra"),
        ('[embedded.py]\nformatter = "black"\n', "unknown embedded formatter shorthand: black"),
        ('[embedded.py]\nformatter = { command = ["x", "{path}"], path_suffix = ".py", env = 1 }\n', "unknown embedded formatter key: env"),
        ('[embedded.py]\nformatter = { command = ["x", 1], path_suffix = ".py" }\n', "embedded formatter command entries must be strings"),
        ('[embedded.py]\nformatter = { command = [], path_suffix = ".py" }\n', "embedded formatter command must not be empty"),
        ('[embedded.py]\nformatter = { command = ["x", "-"], path_suffix = ".py" }\n', "embedded formatter command must contain {path} as an argv item"),
        ('[embedded.py]\nformatter = { command = ["x", "{path}", "--file={path}"], path_suffix = ".py" }\n', "{path} must be a complete argv item"),
        ('[embedded.py]\nformatter = { command = ["x", "{path}"], path_suffix = "" }\n', "embedded formatter path_suffix must not be empty"),
    ],
)
def test_embedded_formatter_config_errors(run, workdir, toml, message):
    """CATCHES: an implementation that accepts untrimmed, empty or reserved formatter names, extra entry or formatter keys, unknown shorthands, non-string or empty commands, commands without a standalone {path} item or with {path} embedded in another item, or an empty path_suffix."""
    files = {"yamark.toml": toml}
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "in.md", "--config", "yamark.toml"], input="#  T\n")
    assert result.stdout == b""
    assert result.stderr.decode() == f"yamark.toml:1:1: error: {message}\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[paths.""]\ntemplate = {}\n', "path config keys must not be empty"),
        ('[paths."../x".template]\nadd_delimiters = []\n', "path config keys must be relative and must not contain .."),
        ('[paths."docs/../x".template]\nadd_delimiters = []\n', "path config keys must be relative and must not contain .."),
        ('[paths."/abs".template]\nadd_delimiters = []\n', "path config keys must be relative and must not contain .."),
        ('[paths."docs/sub"]\nformat = 1\n', "unknown path config key: paths.docs.sub.format"),
        ("[paths.docs.template]\nfoo = 1\n", "unknown path template config key: paths.docs.template.foo"),
        ('[paths.docs.template]\nreplace_delimiters = [{ open = "", close = "x" }]\n', "paths.docs.template.replace_delimiters.open must not be empty"),
        ("[paths.docs.template]\nadd_delimiters = [1]\n", "paths.docs.template.add_delimiters entries must be tables"),
        ("[paths.docs.embedded_markdown]\nfoo = 1\n", "unknown path config key: paths.docs.embedded_markdown.foo"),
        ("[paths.docs.embedded_markdown.template]\nfoo = 1\n", "unknown path template config key: paths.docs.embedded_markdown.template.foo"),
        ("[paths.docs.embedded_markdown.template]\nreplace_delimiters = 1\n", "paths.docs.embedded_markdown.template.replace_delimiters must be an array"),
        ('[paths.docs.embedded_markdown.template]\nadd_delimiters = [{ open = "[[" }]\n', "paths.docs.embedded_markdown.template.add_delimiters.close is required"),
    ],
)
def test_paths_config_errors(run, workdir, toml, message):
    """CATCHES: an implementation that accepts empty, absolute or `..` path keys, unknown keys inside [paths.<p>], its template or embedded_markdown tables, or malformed delimiter lists there, or that forgets to rewrite `/` as `.` in the reported key context."""
    files = {"yamark.toml": toml}
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "in.md", "--config", "yamark.toml"], input="#  T\n")
    assert result.stdout == b""
    assert result.stderr.decode() == f"yamark.toml:1:1: error: {message}\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


# ---------------------------------------------------------------------------
# Path-scoped template layers
# ---------------------------------------------------------------------------

LAYERED_TOML = (
    '[template]\n'
    'add_delimiters = [{ open = "<<", close = ">>" }]\n'
    '\n'
    '[paths."docs".template]\n'
    'replace_delimiters = [{ open = "((", close = "))" }]\n'
    '\n'
    '[paths."docs/deep".template]\n'
    'add_delimiters = [{ open = "@(", close = ")@" }]\n'
)
LAYERED_MD = "A <% a   b %> x.\n\nB << a   b >> x.\n\nC (( a   b )) x.\n\nD @( a   b )@ x.\n"


def test_path_template_layers_apply_shallow_to_deep_with_replace(run, workdir):
    """CATCHES: an implementation that merges path layers in the wrong order, lets replace_delimiters keep the defaults or top-level additions, or applies a deeper layer to files outside its directory."""
    files = {"yamark.toml": LAYERED_TOML, "c.md": LAYERED_MD, "docs/b.md": LAYERED_MD, "docs/deep/a.md": LAYERED_MD}
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"4 files scanned, 3 formatted, 0 unchanged, 1 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        "c.md": "A <% a   b %> x.\n\nB << a   b >> x.\n\nC (( a b )) x.\n\nD @( a b )@ x.\n",
        "docs/b.md": "A <% a b %> x.\n\nB << a b >> x.\n\nC (( a   b )) x.\n\nD @( a b )@ x.\n",
        "docs/deep/a.md": "A <% a b %> x.\n\nB << a b >> x.\n\nC (( a   b )) x.\n\nD @( a   b )@ x.\n",
    }))
    assert read_tree(workdir) == expected


def test_stdin_virtual_path_with_dot_segments_matches_path_layers(run, workdir):
    """CATCHES: an implementation that matches [paths] keys against the raw, non-normalised virtual stdin path (or requires it to exist), so `./docs/x/../deep/new.md` would miss the docs and docs/deep layers."""
    files = {"yamark.toml": LAYERED_TOML}
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "./docs/x/../deep/new.md"], input=LAYERED_MD)
    assert result.stdout == b"A <% a b %> x.\n\nB << a b >> x.\n\nC (( a   b )) x.\n\nD @( a   b )@ x.\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_absolute_stdin_virtual_path_with_parent_segments_matches_path_layers(run, workdir):
    """CATCHES: an implementation that cannot relate an absolute, non-existent --stdin-file-path containing `..` to the discovered config directory, so the docs/deep template layers would not apply."""
    files = {"yamark.toml": LAYERED_TOML}
    write_tree(workdir, files)
    virtual = workdir.resolve() / "docs" / "other" / ".." / "deep" / "new.md"
    result = run(["format", "--stdin-file-path", str(virtual)], input=LAYERED_MD)
    assert result.stdout == b"A <% a b %> x.\n\nB << a b >> x.\n\nC (( a   b )) x.\n\nD @( a   b )@ x.\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_embedded_markdown_path_layer_replaces_and_adds_only_for_embedded_markdown(run, workdir):
    """CATCHES: an implementation that applies paths.<p>.embedded_markdown.template to ordinary Markdown files or to source files outside <p>, ignores its replace_delimiters (default `<% %>` would still preserve the comment), or drops its add_delimiters."""
    toml = (
        '[paths."src".embedded_markdown.template]\n'
        'replace_delimiters = [{ open = "((", close = "))" }]\n'
        'add_delimiters = [{ open = "@(", close = ")@" }]\n'
    )
    py = (
        "# fmt: markdown\n# A <% a   b %> x   y.\n\n"
        "# fmt: markdown\n# C (( a   b )) x   y.\n\n"
        "# fmt: markdown\n# D @( a   b )@ x   y.\n"
    )
    md = "A <% a   b %> x.\n\nC (( a   b )) x.\n\nD @( a   b )@ x.\n"
    files = {"yamark.toml": toml, "c.py": py, "src/a.py": py, "src/b.md": md}
    write_tree(workdir, files)
    result = run(["format", "."])
    assert result.stdout == b"4 files scanned, 3 formatted, 0 unchanged, 1 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        "c.py": (
            "# fmt: markdown\n# A <% a   b %> x   y.\n\n"
            "# fmt: markdown\n# C (( a b )) x y.\n\n"
            "# fmt: markdown\n# D @( a b )@ x y.\n"
        ),
        "src/a.py": (
            "# fmt: markdown\n# A <% a b %> x y.\n\n"
            "# fmt: markdown\n# C (( a   b )) x   y.\n\n"
            "# fmt: markdown\n# D @( a   b )@ x   y.\n"
        ),
        "src/b.md": "A <% a   b %> x.\n\nC (( a b )) x.\n\nD @( a b )@ x.\n",
    }))
    assert read_tree(workdir) == expected


# ---------------------------------------------------------------------------
# Embedded formatter dispatch
# ---------------------------------------------------------------------------

PRETTIER_FENCE_LANGUAGES = [
    "r", "json", "jsonc", "json5", "graphql", "gql", "graphqls", "css", "scss", "less", "postcss", "pcss",
    "html", "js", "javascript", "jsx", "ts", "typescript", "tsx",
]
FENCES_MD = "".join(f"```{lang}\nx\n```\n\n" for lang in PRETTIER_FENCE_LANGUAGES)


def test_builtin_fence_formatters_receive_documented_argv_and_suffix(run, workdir, tmp_path, env):
    """CATCHES: an implementation that maps a fence alias to the wrong built-in (e.g. gql or pcss to the wrong Prettier parser suffix), passes a different argv to air/prettier, or names the synthetic path differently than `<file>.embedded.<line><suffix>`."""
    overrides = fake_bin(tmp_path, env, {"prettier": ARGV_ECHO, "air": ARGV_ECHO})
    files = {"docs/fences.md": FENCES_MD}
    write_tree(workdir, files)
    result = run(["format", "docs/fences.md"], env_overrides=overrides)
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == {"docs/fences.md": (RES / "builtin_fence_formatters_argv.golden").read_bytes()}


def test_missing_optional_formatters_report_sorted_notes(run, workdir, tmp_path):
    """CATCHES: an implementation that fails, or omits per-fence notes, when the optional built-in air/prettier executables are missing, or that does not sort --diagnostics notes by path and line across files."""
    files = {"b.md": FENCES_MD, "a.md": "```css\nx\n```\n\n```r\ny\n```\n"}
    write_tree(workdir, files)
    result = run(["format", "--diagnostics", "."], env_overrides=empty_path(tmp_path))
    assert result.stdout == b"2 files scanned, 0 formatted, 2 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr == (RES / "missing_optional_formatters_notes.golden").read_bytes()
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_mdformat_directive_runs_mdformat_reading_stdin(run, tmp_path, env):
    """CATCHES: an implementation that invokes mdformat with a file path argument (instead of `mdformat -`) for a YAML literal marked `# fmt: mdformat`."""
    overrides = fake_bin(tmp_path, env, {"mdformat": ARGV_ECHO})
    result = run(["format", "--stdin-file-path", "in.yaml"], input="# fmt: mdformat\ntext: |\n  hello\n", env_overrides=overrides)
    assert result.stdout == b"# fmt: mdformat\ntext: |\n  -\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_config_shorthand_air_for_custom_fence_name(run, workdir, tmp_path, env):
    """CATCHES: an implementation that does not resolve a `formatter = "air"` shorthand for a custom [embedded.<name>] entry to the air argv with an `.R` synthetic path."""
    overrides = fake_bin(tmp_path, env, {"air": ARGV_ECHO})
    files = {"yamark.toml": '[embedded.rlang]\nformatter = "air"\n'}
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "in.md"], input="```rlang\nx<-1\n```\n", env_overrides=overrides)
    assert result.stdout == b"```rlang\nformat\n--stdin-file-path\nin.md.embedded.2.R\n```\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("notebook", "message"),
    [
        ("not json", "embedded formatter emitted invalid notebook JSON: expected ident at line 1 column 2"),
        ('{"cells":[{"source":"a"},{"source":"b"}]}', "embedded formatter notebook output must contain exactly one cell"),
        ('{"cells":[{"cell_type":"code"}]}', "embedded formatter notebook output cell must contain source"),
        ('{"cells":[{"source":["a\\n", 3]}]}', "embedded formatter notebook output source lines must be strings"),
        ('{"cells":[{"source":7}]}', "embedded formatter notebook output source must be a string or string array"),
    ],
)
def test_ruff_notebook_output_validation_errors(run, tmp_path, env, notebook, message):
    """CATCHES: an implementation that accepts malformed ruff notebook output (invalid JSON, several cells, a cell without source, non-string source lines or a non-string source) instead of failing the file with the exact error."""
    overrides = fake_bin(tmp_path, env, {"ruff": f"#!/bin/sh\ncat >/dev/null\nprintf '%s' '{notebook}'\n"})
    result = run(["format", "--stdin-file-path", "in.md"], input="```python\nx=1\n```\n", env_overrides=overrides)
    assert result.stdout == b""
    assert result.stderr.decode() == f"in.md:1:1: error: {message}\n"
    assert result.returncode == 1


def test_optional_formatter_nonzero_exit_without_stderr_is_a_note(run, workdir, tmp_path, env):
    """CATCHES: an implementation that treats a silent nonzero exit of an optional formatter as an error, or prints a location-bearing note, instead of preserving the chunk with a generic note shown only under --diagnostics."""
    overrides = fake_bin(tmp_path, env, {"ruff": "#!/bin/sh\ncat >/dev/null\nexit 3\n"})
    files = {"a.md": "```python\nx=1\n```\n", "b.md": "Intro.\n\n```python\ny=2\n```\n"}
    write_tree(workdir, files)
    quiet = run(["format", "a.md", "b.md"], env_overrides=overrides)
    assert quiet.stdout == b"2 files scanned, 0 formatted, 2 unchanged, 0 skipped, 0 failed\n"
    assert quiet.stderr.decode() == ""
    assert quiet.returncode == 0
    noted = run(["format", "--diagnostics", "b.md", "a.md"], env_overrides=overrides)
    assert noted.stdout == b"2 files scanned, 0 formatted, 2 unchanged, 0 skipped, 0 failed\n"
    assert noted.stderr.decode() == (
        "a.md:2:1: note: embedded formatter `ruff` failed; left chunk unchanged\n"
        "b.md:4:1: note: embedded formatter `ruff` failed; left chunk unchanged\n"
    )
    assert noted.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


@pytest.mark.parametrize(
    ("stderr_text", "note"),
    [
        ("error: Failed to parse (3:5) here", "embedded formatter `ruff` failed at formatter input 3:5; left chunk unchanged"),
        ("error: something broke (line 4)", "embedded formatter `ruff` failed; left chunk unchanged"),
        ("cell.ipynb:7:2: unexpected token", "embedded formatter `ruff` failed at formatter input 7:2; left chunk unchanged"),
    ],
)
def test_optional_formatter_failure_note_extracts_location(run, tmp_path, env, stderr_text, note):
    """CATCHES: an implementation that does not extract `(line:col)` or `:line:col:` locations from an optional formatter's stderr, or that invents one when only a bare number is present."""
    script = f"#!/bin/sh\ncat >/dev/null\necho '{stderr_text}' >&2\nexit 2\n"
    overrides = fake_bin(tmp_path, env, {"ruff": script})
    result = run(["format", "--diagnostics", "--stdin-file-path", "in.md"], input="```python\nx=1\n```\n", env_overrides=overrides)
    assert result.stdout == b"```python\nx=1\n```\n"
    assert result.stderr.decode() == f"in.md:2:1: note: {note}\n"
    assert result.returncode == 0


def test_strict_formatter_failure_reports_its_stderr(run, workdir):
    """CATCHES: an implementation that treats a nonzero exit of a configured (non-built-in) formatter as optional, or that replaces its stderr text with a generic message."""
    files = {
        "yamark.toml": '[embedded.txt]\nformatter = { command = ["sh", "fmt_script", "{path}"], path_suffix = ".txt" }\n',
        "fmt_script": "cat >/dev/null\necho 'bad input at 1:2' >&2\nexit 4\n",
        "a.md": "#  Title\n\n```txt\nabc\n```\n",
    }
    write_tree(workdir, files)
    result = run(["format", "a.md"])
    assert result.stdout == b"1 files scanned, 0 formatted, 0 unchanged, 0 skipped, 1 failed\n"
    assert result.stderr.decode() == "a.md:1:1: error: bad input at 1:2\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_strict_formatter_missing_executable_is_an_error(run, workdir, tmp_path):
    """CATCHES: an implementation that silently preserves the chunk when a configured formatter whose argv[0] is not ruff/air/mdformat/prettier cannot be found."""
    files = {
        "yamark.toml": '[embedded.txt]\nformatter = { command = ["sqlfmt-missing", "{path}"], path_suffix = ".txt" }\n',
        "a.md": "```txt\nabc\n```\n",
    }
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "a.md"], input=files["a.md"], env_overrides=empty_path(tmp_path))
    assert result.stdout == b""
    assert result.stderr.decode() == "a.md:1:1: error: failed to run embedded formatter: No such file or directory (os error 2)\n"
    assert result.returncode == 1


def test_skip_embedded_formatters_bypasses_strict_missing_formatter(run, workdir, tmp_path):
    """CATCHES: an implementation that still spawns (and fails on) a strict configured formatter under --skip-embedded-formatters, or that stops formatting the rest of the file."""
    files = {
        "yamark.toml": '[embedded.txt]\nformatter = { command = ["sqlfmt-missing", "{path}"], path_suffix = ".txt" }\n',
        "f.md": "#  T\n\n```txt\nabc\n```\n",
    }
    write_tree(workdir, files)
    result = run(["format", "--skip-embedded-formatters", "f.md"], env_overrides=empty_path(tmp_path))
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected["f.md"] = b"# T\n\n```txt\nabc\n```\n"
    assert read_tree(workdir) == expected


def test_optional_formatter_that_cannot_be_executed_is_an_error(run, tmp_path, env):
    """CATCHES: an implementation that treats every spawn failure of an optional formatter as 'missing'; only a not-found executable is optional, a non-executable one is an error."""
    bin_dir = tmp_path / "bin"
    write_tree(bin_dir, {"ruff": "#!/bin/sh\nexit 0\n"})
    (bin_dir / "ruff").chmod(0o644)
    overrides = {"PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"}
    result = run(["format", "--stdin-file-path", "in.md"], input="```python\nx=1\n```\n", env_overrides=overrides)
    assert result.stdout == b""
    assert result.stderr.decode() == "in.md:1:1: error: failed to run embedded formatter: Permission denied (os error 13)\n"
    assert result.returncode == 1


def test_successful_formatter_with_whitespace_only_stderr_is_an_error(run, tmp_path, env):
    """CATCHES: an implementation that trims formatter stderr and treats whitespace-only output as clean; any stderr from a successful formatter is an error."""
    script = "#!/bin/sh\ncat >/dev/null\nprintf '\\n' >&2\nprintf '%s' '{\"cells\":[{\"source\":\"x = 1\\n\"}]}'\n"
    overrides = fake_bin(tmp_path, env, {"ruff": script})
    result = run(["format", "--stdin-file-path", "in.md"], input="```python\nx=1\n```\n", env_overrides=overrides)
    assert result.stdout == b""
    assert result.stderr.decode() == "in.md:1:1: error: embedded formatter wrote to stderr\n"
    assert result.returncode == 1
