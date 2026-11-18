"""Path mode of `yamark format`: write/check/diff modes, summaries, traversal, ignores and failures."""

import os

import pytest

from conftest import assert_golden, git, transcript

UNFORMATTED = "a:  1\nb:   [1,2]\n"
FORMATTED = "a: 1\nb: [1, 2]\n"


def write(root, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())


def test_write_mode_rewrites_file_and_prints_summary_on_stdout(run, workdir):
    """CATCHES: write mode not rewriting changed files, printing the summary to stderr, or using different
    summary wording/counts."""
    write(workdir, {"a.yaml": UNFORMATTED})
    result = run(["format", "a.yaml"])
    assert (result.returncode, result.stderr) == (0, b"")
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert (workdir / "a.yaml").read_text() == FORMATTED


def test_write_mode_unchanged_file(run, workdir):
    """CATCHES: counting an already formatted file as formatted, or touching it."""
    write(workdir, {"a.yaml": FORMATTED})
    result = run(["format", "a.yaml"])
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n", b"")


def test_check_mode_reports_on_stderr_and_exits_1(run, workdir):
    """CATCHES: --check writing files, printing the summary to stdout, or exiting 0 when a file would change."""
    write(workdir, {"a.yaml": UNFORMATTED, "b.yaml": FORMATTED})
    result = run(["format", "--check", "a.yaml", "b.yaml"])
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == b"2 files scanned, 1 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert (workdir / "a.yaml").read_text() == UNFORMATTED


def test_check_mode_clean_exits_0(run, workdir):
    """CATCHES: --check exiting nonzero when nothing would change."""
    write(workdir, {"a.yaml": FORMATTED, "b.md": "# Title\n"})
    result = run(["format", "--check", "."])
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"", b"2 files scanned, 0 formatted, 2 unchanged, 0 skipped, 0 failed\n")


def test_diff_mode_prints_unified_diff(run, workdir):
    """CATCHES: --diff writing files, a different unified diff header/hunk format, diffs on stderr, or a
    missing summary on stderr / exit status other than 1."""
    write(workdir, {"a.yaml": UNFORMATTED, "c.md": "#   Title\n\nSome   text.\n"})
    result = run(["format", "--diff", "a.yaml", "c.md"])
    assert result.returncode == 1
    assert result.stdout == (b"--- a.yaml\n+++ a.yaml\n@@ -1,2 +1,2 @@\n-a:  1\n-b:   [1,2]\n+a: 1\n+b: [1, 2]\n"
                             b"--- c.md\n+++ c.md\n@@ -1,3 +1,3 @@\n-#   Title\n+# Title\n \n-Some   text.\n"
                             b"+Some text.\n")
    assert result.stderr == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert (workdir / "a.yaml").read_text() == UNFORMATTED


def test_diff_mode_no_changes(run, workdir):
    """CATCHES: --diff printing empty diff headers or exiting 1 when nothing changes."""
    write(workdir, {"a.yaml": FORMATTED})
    result = run(["format", "--diff", "a.yaml"])
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"", b"1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n")


def test_diff_no_newline_at_end_of_file(run, workdir):
    """CATCHES: diffs that drop the '\\ No newline at end of file' marker for inputs without a final newline."""
    write(workdir, {"a.yaml": "a:  1"})
    result = run(["format", "--diff", "a.yaml"])
    assert result.returncode == 1
    assert_golden(transcript(result), __file__, "diff_no_final_newline")


def test_diff_hunks_and_context(run, workdir):
    """CATCHES: wrong hunk ranges, context lengths (3 lines), separate vs merged hunks, or line numbering in
    multi-hunk unified diffs."""
    lines = [f"k{i}:  {i}" if i in (2, 20, 40) else f"k{i}: {i}" for i in range(1, 46)]
    write(workdir, {"long.yaml": "\n".join(lines) + "\n"})
    result = run(["format", "--diff", "long.yaml"])
    assert result.returncode == 1
    assert_golden(transcript(result), __file__, "diff_hunks")


def test_diff_line_count_changes(run, workdir):
    """CATCHES: wrong hunk counts when formatting adds or removes lines (block expansion of a flow list)."""
    write(workdir, {"a.yaml": "before: 1\nitems: [alpha-value-one, alpha-value-two, alpha-value-three, "
                              "alpha-value-four, alpha-value-five]\nafter: 2\n"})
    result = run(["format", "--diff", "a.yaml"])
    assert_golden(transcript(result), __file__, "diff_expansion")


def test_diff_crlf_input(run, workdir):
    """CATCHES: diff output that leaks carriage returns or miscounts CRLF lines."""
    write(workdir, {"a.yaml": b"a:  1\r\nb: 2\r\n"})
    result = run(["format", "--diff", "a.yaml"])
    assert result.stdout == b"--- a.yaml\n+++ a.yaml\n@@ -1,2 +1,2 @@\n-a:  1\n+a: 1\n b: 2\n"
    assert result.returncode == 1


def test_default_path_is_current_directory(run, workdir):
    """CATCHES: `yamark format` without paths doing nothing, or formatting something other than '.'
    (diagnostic and diff paths are reported with a './' prefix)."""
    write(workdir, {"a.yaml": UNFORMATTED, "sub/b.yaml": UNFORMATTED})
    result = run(["format", "--diff"])
    assert result.returncode == 1
    assert result.stdout.startswith(b"--- ./a.yaml\n+++ ./a.yaml\n")
    assert b"--- ./sub/b.yaml\n" in result.stdout
    assert result.stderr == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"


def test_directory_traversal_counts_and_order(run, workdir):
    """CATCHES: wrong scanned/skipped/failed counts, unsorted traversal order, missing './' prefixes, failure
    diagnostics not printed after the summary, or failures not producing exit 1 in write mode."""
    write(workdir, {
        "b.yaml": UNFORMATTED, "a.yml": FORMATTED, "c.md": "# T\n", "notes.txt": "x", "d.json": "{\"a\":1}",
        "sub/deep/s.yaml": UNFORMATTED, "sub/u16.yaml": b"\xff\xfeh\x00", "sub/latin.yaml": b"k: \xff\n",
        "z.R": "x <- 1\n", "y.py": "x = 1\n",
    })
    result = run(["format"])
    assert_golden(transcript(result), __file__, "traversal_write")
    assert (workdir / "b.yaml").read_text() == FORMATTED
    assert (workdir / "sub/deep/s.yaml").read_text() == FORMATTED


def test_check_and_diff_report_same_failures(run, workdir):
    """CATCHES: --check/--diff runs that hide read failures or print them in a different order."""
    write(workdir, {"ok.yaml": UNFORMATTED, "z/latin.md": b"\xe9t\xe9\n", "a/u16.md": b"\xfe\xff\x00a"})
    check = run(["format", "--check", "."])
    diff = run(["format", "--diff", "."])
    assert_golden(transcript(check) + "=== diff\n" + transcript(diff), __file__, "failures_check_diff")


def test_hidden_paths_skipped_unless_explicit(run, workdir):
    """CATCHES: traversing hidden files/directories, or refusing an explicitly named hidden path."""
    write(workdir, {".hidden/h.yaml": UNFORMATTED, ".dot.yaml": UNFORMATTED, "v.yaml": FORMATTED})
    walked = run(["format", "--check"])
    explicit = run(["format", "--check", ".hidden", ".dot.yaml"])
    assert (walked.returncode, walked.stderr) == (0, b"1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n")
    assert (explicit.returncode, explicit.stderr) == (
        1, b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n")


def test_dot_ignore_file_respected_without_git(run, workdir):
    """CATCHES: ignoring `.ignore` files, or applying `.gitignore` outside a Git repository."""
    write(workdir, {"keep.yaml": UNFORMATTED, "ign.yaml": UNFORMATTED, "ign2.yaml": UNFORMATTED,
                    ".gitignore": "ign.yaml\n", ".ignore": "ign2.yaml\n"})
    result = run(["format", "--diff"])
    assert result.stdout.count(b"--- ") == 2
    assert b"--- ./ign2.yaml" not in result.stdout
    assert b"--- ./ign.yaml\n" in result.stdout
    assert result.stderr == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"


def test_gitignore_respected_inside_git_repo(run, workdir, env):
    """CATCHES: not honouring .gitignore inside a Git repository, or honouring it for explicitly named files."""
    write(workdir, {"keep.yaml": UNFORMATTED, "ign.yaml": UNFORMATTED, "d/x.yaml": UNFORMATTED,
                    ".gitignore": "ign.yaml\n", "d/.gitignore": "x.yaml\n"})
    git(["-c", "init.defaultBranch=main", "init", "-q"], workdir, env)
    walked = run(["format", "--check"])
    nested = run(["format", "--check", "d"])
    explicit = run(["format", "--check", "ign.yaml", "d/x.yaml"])
    assert walked.stderr == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert (nested.returncode, nested.stderr) == (0, b"0 files scanned, 0 formatted, 0 unchanged, 0 skipped, 0 failed\n")
    assert explicit.stderr == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"


def test_git_info_exclude_respected(run, workdir, env):
    """CATCHES: ignoring .git/info/exclude patterns during traversal."""
    write(workdir, {"keep.yaml": UNFORMATTED, "skip.yaml": UNFORMATTED})
    git(["-c", "init.defaultBranch=main", "init", "-q"], workdir, env)
    (workdir / ".git" / "info").mkdir(exist_ok=True)
    (workdir / ".git" / "info" / "exclude").write_text("skip.yaml\n")
    result = run(["format", "--diff"])
    assert result.stdout == b"--- ./keep.yaml\n+++ ./keep.yaml\n@@ -1,2 +1,2 @@\n-a:  1\n-b:   [1,2]\n+a: 1\n+b: [1, 2]\n"


def test_global_git_ignore_respected(run, workdir, env, tmp_path):
    """CATCHES: ignoring the global Git ignore file ($HOME/.config/git/ignore and core.excludesFile)."""
    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("global.yaml\n")
    (home / "custom-ignore").write_text("custom.yaml\n")
    write(workdir, {"keep.yaml": UNFORMATTED, "global.yaml": UNFORMATTED, "custom.yaml": UNFORMATTED})
    git(["-c", "init.defaultBranch=main", "init", "-q"], workdir, env)
    xdg = run(["format", "--check"])
    (home / ".config" / "git" / "ignore").unlink()
    (home / ".gitconfig").write_text(f"[core]\n\texcludesFile = {home / 'custom-ignore'}\n")
    excludes = run(["format", "--check"])
    assert xdg.stderr == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert excludes.stderr == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert (xdg.returncode, excludes.returncode) == (1, 1)
    diff = run(["format", "--diff"])
    assert sorted(line for line in diff.stdout.split(b"\n") if line.startswith(b"--- ")) == [
        b"--- ./global.yaml", b"--- ./keep.yaml"]


def test_xdg_config_home_git_ignore(run, workdir, env, tmp_path):
    """CATCHES: ignoring $XDG_CONFIG_HOME/git/ignore as the global Git ignore location."""
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    (xdg / "git" / "ignore").write_text("skip.yaml\n")
    write(workdir, {"keep.yaml": UNFORMATTED, "skip.yaml": UNFORMATTED})
    git(["-c", "init.defaultBranch=main", "init", "-q"], workdir, env)
    result = run(["format", "--check"], env_overrides={"XDG_CONFIG_HOME": str(xdg)})
    assert (result.returncode, result.stderr) == (1, b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n")


def test_unsupported_explicit_file_is_skipped(run, workdir):
    """CATCHES: failing (instead of counting as skipped) when an unsupported extension is named explicitly."""
    write(workdir, {"notes.txt": "x", "data.json": "{\"a\": 1}", "Makefile": "all:\n"})
    result = run(["format", "--check", "notes.txt", "data.json", "Makefile"])
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"", b"3 files scanned, 0 formatted, 0 unchanged, 3 skipped, 0 failed\n")


@pytest.mark.parametrize("name", ["README.MD", "notes.Qmd", "a.RMD", "b.rmd", "c.YAML", "d.Yml", "e.R", "f.PY",
                                  "g.markdown", "h.yamlx", "noext", ".yaml"])
def test_extension_matching_is_ascii_case_insensitive(name, run, workdir):
    """CATCHES: case-sensitive extension matching, or treating unsupported extensions (.markdown, .yamlx,
    no extension, a bare dotfile) as formattable."""
    content = {"md": "#   T\n", "qmd": "#   T\n", "rmd": "#   T\n", "yaml": "a:  1\n", "yml": "a:  1\n",
               "r": "#| a:  1\nx <- 1\n", "py": "#| a:  1\nx = 1\n"}
    ext = name.rsplit(".", 1)[-1].lower() if "." in name[1:] else ""
    write(workdir, {name: content.get(ext, "a:  1\n")})
    result = run(["format", "--check", name])
    assert_golden(transcript(result), __file__, "ext_" + name.replace(".", "_"))


def test_missing_path_aborts_run(run, workdir):
    """CATCHES: continuing after a nonexistent path (or writing earlier files); the reference reports
    'path does not exist', prints no summary and exits 1."""
    write(workdir, {"a.yaml": UNFORMATTED})
    result = run(["format", "a.yaml", "missing.yaml"])
    assert (result.returncode, result.stdout, result.stderr) == (1, b"", b"missing.yaml:1:1: error: path does not exist\n")
    assert (workdir / "a.yaml").read_text() == UNFORMATTED


def test_missing_single_path(run):
    """CATCHES: a different message or status for one missing path (including a missing directory)."""
    result = run(["format", "--check", "nothere/"])
    assert (result.returncode, result.stdout, result.stderr) == (1, b"", b"nothere/:1:1: error: path does not exist\n")


def test_three_argument_shortcut_matches_full_parser(run, workdir):
    """CATCHES: `yamark format PATH` behaving differently from the general form, including for a path that
    happens to be named like a subcommand ('help')."""
    write(workdir, {"a.yaml": UNFORMATTED})
    short = run(["format", "a.yaml"])
    assert (short.returncode, short.stdout) == (0, b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n")
    named_help = run(["format", "help"])
    assert (named_help.returncode, named_help.stdout, named_help.stderr) == (
        1, b"", b"help:1:1: error: path does not exist\n")


def test_double_dash_allows_dash_prefixed_paths(run, workdir):
    """CATCHES: rejecting `--` before a path that starts with '-' or treating it as an option."""
    write(workdir, {"-x.yaml": UNFORMATTED})
    result = run(["format", "--check", "--", "-x.yaml"])
    assert (result.returncode, result.stderr) == (1, b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n")


def test_duplicate_paths_are_deduplicated(run, workdir):
    """CATCHES: formatting (and counting) the same file twice when it is named repeatedly or via ./ and a parent
    directory."""
    write(workdir, {"d/a.yaml": UNFORMATTED})
    result = run(["format", "--diff", "d/a.yaml", "./d/a.yaml", "d"])
    assert result.stdout == b"--- d/a.yaml\n+++ d/a.yaml\n@@ -1,2 +1,2 @@\n-a:  1\n-b:   [1,2]\n+a: 1\n+b: [1, 2]\n"
    assert result.stderr == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"


def test_symlinks(run, workdir):
    """CATCHES: following symlinks during traversal, refusing explicitly named symlinks to files or directories,
    or formatting a file twice when reached through a link and its real path."""
    write(workdir, {"real/r.yaml": UNFORMATTED})
    os.symlink("real", workdir / "linkdir")
    os.symlink("real/r.yaml", workdir / "link.yaml")
    walked = run(["format", "--check"])
    file_link = run(["format", "--diff", "link.yaml"])
    dir_link = run(["format", "--check", "linkdir"])
    both = run(["format", "--check", "link.yaml", "real/r.yaml", "real"])
    assert walked.stderr == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert file_link.stdout.startswith(b"--- link.yaml\n+++ link.yaml\n")
    assert dir_link.stderr == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert both.stderr == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"


def test_symlink_write_updates_target(run, workdir):
    """CATCHES: replacing a symlink with a regular file instead of writing through it."""
    write(workdir, {"real.yaml": UNFORMATTED})
    os.symlink("real.yaml", workdir / "link.yaml")
    result = run(["format", "link.yaml"])
    assert result.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert os.path.islink(workdir / "link.yaml")
    assert (workdir / "real.yaml").read_text() == FORMATTED


def test_dangling_symlink(run, workdir):
    """CATCHES: treating a dangling symlink as skipped instead of 'path does not exist'."""
    os.symlink("missing.yaml", workdir / "dangling.yaml")
    write(workdir, {"ok.yaml": FORMATTED})
    single = run(["format", "--check", "dangling.yaml"])
    multi = run(["format", "--check", "ok.yaml", "dangling.yaml"])
    assert (single.returncode, single.stderr) == (1, b"dangling.yaml:1:1: error: path does not exist\n")
    assert (multi.returncode, multi.stderr) == (1, b"dangling.yaml:1:1: error: path does not exist\n")


def test_special_file_rejected(run, workdir):
    """CATCHES: hanging on or reading a FIFO instead of rejecting it as 'not a file or directory'."""
    os.mkfifo(workdir / "pipe.yaml")
    write(workdir, {"ok.yaml": FORMATTED})
    single = run(["format", "--check", "pipe.yaml"])
    multi = run(["format", "--check", "ok.yaml", "pipe.yaml"])
    expected = b"pipe.yaml:1:1: error: path is not a file or directory\n"
    assert (single.returncode, single.stdout, single.stderr) == (1, b"", expected)
    assert (multi.returncode, multi.stdout, multi.stderr) == (1, b"", expected)


def test_symlink_to_special_file_rejected(run, workdir):
    """CATCHES: following an explicit symlink to a FIFO instead of rejecting it."""
    os.mkfifo(workdir / "pipe")
    os.symlink("pipe", workdir / "pipe.yaml")
    result = run(["format", "--check", "pipe.yaml"])
    assert (result.returncode, result.stderr) == (1, b"pipe.yaml:1:1: error: path is not a file or directory\n")


def test_partial_failure_still_writes_other_files(run, workdir):
    """CATCHES: treating a multi-file write run as transactional, or not reporting the failing file's parse
    error after the summary with exit 1."""
    write(workdir, {"a.yaml": UNFORMATTED, "b.yaml": "key:  1\n# fmt: skip\n", "c.md": "#   T\n"})
    result = run(["format", "a.yaml", "b.yaml", "c.md"])
    assert_golden(transcript(result), __file__, "partial_failure")
    assert (workdir / "a.yaml").read_text() == FORMATTED
    assert (workdir / "c.md").read_text() == "# T\n"
    assert (workdir / "b.yaml").read_text() == "key:  1\n# fmt: skip\n"


def test_single_file_read_failures(run, workdir):
    """CATCHES: different messages for non-UTF-8 and UTF-16 inputs named explicitly, or not counting them as
    failed (exit 1, summary first, then the error)."""
    write(workdir, {"latin.md": b"caf\xe9\n", "u16.yaml": b"\xff\xfea\x00"})
    latin = run(["format", "latin.md"])
    u16 = run(["format", "--check", "u16.yaml"])
    assert (latin.returncode, latin.stdout, latin.stderr) == (
        1, b"1 files scanned, 0 formatted, 0 unchanged, 0 skipped, 1 failed\n",
        b"latin.md:1:1: error: failed to read file: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 3\n")
    assert (u16.returncode, u16.stdout, u16.stderr) == (
        1, b"", b"1 files scanned, 0 formatted, 0 unchanged, 0 skipped, 1 failed\n"
                b"u16.yaml:1:1: error: failed to read file: unsupported encoding: UTF-16 BOM\n")


def test_utf8_bom_in_path_mode(run, workdir):
    """CATCHES: stripping or duplicating a UTF-8 byte order mark when rewriting Markdown, or rewriting a
    BOM-prefixed YAML root (the reference leaves it unchanged)."""
    write(workdir, {"bom.yaml": b"\xef\xbb\xbfa:  1\nb:   [1,2]\n", "bom.md": b"\xef\xbb\xbf#   T\n\ntext   here\n"})
    result = run(["format", "bom.yaml", "bom.md"])
    assert (result.returncode, result.stdout) == (0, b"2 files scanned, 1 formatted, 1 unchanged, 0 skipped, 0 failed\n")
    assert (workdir / "bom.yaml").read_bytes() == b"\xef\xbb\xbfa:  1\nb:   [1,2]\n"
    assert (workdir / "bom.md").read_bytes() == b"\xef\xbb\xbf# T\n\ntext here\n"


def test_crlf_preserved_in_path_mode(run, workdir):
    """CATCHES: converting CRLF line endings to LF when rewriting files."""
    write(workdir, {"a.yaml": b"a:  1\r\nb:   2\r\n", "b.md": b"#   T\r\n\r\ntext   here\r\n"})
    result = run(["format", "."])
    assert result.stdout == b"2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert (workdir / "a.yaml").read_bytes() == b"a: 1\r\nb: 2\r\n"
    assert_golden((workdir / "b.md").read_bytes().decode(), __file__, "crlf_markdown")


def test_diagnostics_in_path_mode(run, workdir):
    """CATCHES: --diagnostics notes not printed after the summary in path mode, or printed without it, or
    unsorted by path."""
    write(workdir, {"b.yaml": "x: 1\n", "a.yaml": "a:  1\n", "c.md": "text\n"})
    result = run(["format", "--check", "--diagnostics", "."])
    assert_golden(transcript(result), __file__, "diagnostics_check")


def test_empty_directory(run, workdir):
    """CATCHES: failing or printing nothing for an empty directory (the summary still prints zero counts)."""
    (workdir / "empty").mkdir()
    result = run(["format", "empty"])
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"0 files scanned, 0 formatted, 0 unchanged, 0 skipped, 0 failed\n", b"")


def test_empty_file(run, workdir):
    """CATCHES: rewriting or failing on empty Markdown and YAML files."""
    write(workdir, {"e.md": "", "e.yaml": ""})
    result = run(["format", "--check", "e.md", "e.yaml"])
    assert (result.returncode, result.stderr) == (0, b"2 files scanned, 0 formatted, 2 unchanged, 0 skipped, 0 failed\n")


def test_many_files_keep_input_order(run, workdir):
    """CATCHES: nondeterministic (worker-completion) ordering of diffs when many files are formatted in
    parallel; diffs must follow traversal order."""
    files = {f"f{i:03d}.yaml": f"k{i}:  {i}\n" for i in range(60)}
    write(workdir, files)
    result = run(["format", "--diff", "."])
    headers = [line for line in result.stdout.split(b"\n") if line.startswith(b"--- ")]
    assert headers == [f"--- ./f{i:03d}.yaml".encode() for i in range(60)]
    assert result.stderr == b"60 files scanned, 60 formatted, 0 unchanged, 0 skipped, 0 failed\n"


def test_explicit_paths_keep_argument_order(run, workdir):
    """CATCHES: sorting explicitly named roots instead of processing them in argument order."""
    write(workdir, {"z.yaml": UNFORMATTED, "a.yaml": UNFORMATTED, "m/b.yaml": UNFORMATTED})
    result = run(["format", "--diff", "z.yaml", "m", "a.yaml"])
    headers = [line for line in result.stdout.split(b"\n") if line.startswith(b"--- ")]
    assert headers == [b"--- z.yaml", b"--- m/b.yaml", b"--- a.yaml"]


def test_absolute_paths_in_diff_headers(run, workdir):
    """CATCHES: rewriting absolute paths given on the command line into relative ones in diff headers."""
    write(workdir, {"a.yaml": UNFORMATTED})
    result = run(["format", "--diff", str(workdir / "a.yaml")])
    real = str(workdir / "a.yaml").encode()
    assert result.stdout.startswith(b"--- " + real + b"\n+++ " + real + b"\n@@ -1,2 +1,2 @@\n")


def test_large_diff_uses_linear_alignment(run, workdir):
    """CATCHES: wrong hunks for large files whose changed region exceeds the quadratic diff budget (first and last
    lines changed, a changed block longer than the 64-line sync window, and a line-count change), or quadratic
    blowups that time out."""
    lines = []
    for i in range(2100):
        if i == 1500:
            lines.append("items: [alpha-value-one, alpha-value-two, alpha-value-three, alpha-value-four, alpha-value-five]")
        elif i in (0, 2099) or 1000 <= i < 1070 or 1800 <= i < 1803:
            lines.append(f"k{i}:  {i}")
        else:
            lines.append(f"k{i}: {i}")
    write(workdir, {"big.yaml": "\n".join(lines) + "\n"})
    result = run(["format", "--diff", "big.yaml"])
    assert result.returncode == 1
    assert_golden(transcript(result), __file__, "diff_linear")


def test_large_diff_with_repeated_lines(run, workdir):
    """CATCHES: misaligned linear diffs when many identical lines make several sync points possible."""
    lines = []
    for i in range(2200):
        if i % 3 == 0:
            lines.append("- same")
        elif 700 <= i < 780:
            lines.append(f"-   v{i}")
        else:
            lines.append(f"- v{i}")
    lines[0] = "-    first"
    lines[-1] = "-    last"
    write(workdir, {"rep.yaml": "\n".join(lines) + "\n"})
    result = run(["format", "--diff", "rep.yaml"])
    assert result.returncode == 1
    assert_golden(transcript(result), __file__, "diff_linear_repeated")


def test_symlink_to_special_file_ignored_among_several_roots(run, workdir):
    """CATCHES: failing (or counting the entry) for a symlink to a FIFO when several roots are given; unlike a
    single explicit path, the reference silently ignores it while formatting the other roots."""
    os.mkfifo(workdir / "pipe")
    os.symlink("pipe", workdir / "pipe.yaml")
    write(workdir, {"ok.yaml": UNFORMATTED})
    first = run(["format", "--check", "pipe.yaml", "ok.yaml"])
    last = run(["format", "--check", "ok.yaml", "pipe.yaml"])
    expected = (1, b"", b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n")
    assert (first.returncode, first.stdout, first.stderr) == expected
    assert (last.returncode, last.stdout, last.stderr) == expected


def test_explicit_config_applies_to_every_traversed_file(run, workdir):
    """CATCHES: using discovered configs instead of the explicit --config for files found by directory traversal."""
    write(workdir, {"explicit.toml": "[format]\nwrap = \"sentence\"\n", "d/yamark.toml": "[format]\nwrap = \"none\"\n",
                    "d/a.md": "One here. Two here.\n", "d/sub/b.md": "Three here. Four here.\n"})
    result = run(["format", "--config", "explicit.toml", "d"])
    assert (result.returncode, result.stdout) == (0, b"3 files scanned, 2 formatted, 0 unchanged, 1 skipped, 0 failed\n")
    assert (workdir / "d/a.md").read_text() == "One here.\nTwo here.\n"
    assert (workdir / "d/sub/b.md").read_text() == "Three here.\nFour here.\n"


def test_non_utf8_and_unicode_file_names(run, workdir):
    """CATCHES: crashing on non-UTF-8 file names, not displaying them lossily (U+FFFD) in diff headers and
    diagnostics, or traversing in an order other than byte order of the names."""
    (workdir / "café ü.yaml").write_text("a:  1\n")
    with open(os.path.join(os.fsencode(workdir), b"\xff bad.yaml"), "wb") as handle:
        handle.write(b"a:  1\n")
    with open(os.path.join(os.fsencode(workdir), b"\xfe.yaml"), "wb") as handle:
        handle.write(b"a:  1\n# fmt: skip\n")
    diff = run(["format", "--diff", "."])
    assert diff.returncode == 1
    assert diff.stdout.decode() == (
        "--- ./café ü.yaml\n+++ ./café ü.yaml\n@@ -1 +1 @@\n-a:  1\n+a: 1\n"
        "--- ./� bad.yaml\n+++ ./� bad.yaml\n@@ -1 +1 @@\n-a:  1\n+a: 1\n")
    assert diff.stderr.decode() == ("3 files scanned, 2 formatted, 0 unchanged, 0 skipped, 1 failed\n"
                                    "./�.yaml:2:12: error: fmt: skip has no target\n")
