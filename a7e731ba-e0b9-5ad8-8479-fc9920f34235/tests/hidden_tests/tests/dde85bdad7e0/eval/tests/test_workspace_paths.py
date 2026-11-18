"""Path-mode formatting: traversal, ignore files, special files, encodings, summaries,
`--check`/`--diff` output and the linear fallback of the unified diff renderer.

Each test builds a small tree in the temporary working directory, runs `yamark
format` with relative paths, and compares stdout, stderr, exit status and the
bytes of every file afterwards.
"""

import os
import subprocess

import pytest

from conftest import outcome


def _tree(workdir, files):
    for name, data in files.items():
        path = workdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)


def _observe(result, workdir):
    observed = outcome(result)
    observed["stderr"] = observed["stderr"].replace(str(workdir), "<workdir>")
    observed["files"] = {
        str(p.relative_to(workdir)): p.read_bytes().decode("utf-8", errors="surrogateescape")
        for p in sorted(workdir.rglob("*"))
        if p.is_file() and not p.is_symlink() and ".git" not in p.relative_to(workdir).parts
    }
    return observed


BASIC = {
    "a.yaml": "a:   1\nlist: [x,y]\n",
    "b.md": "Some   text   here.\n",
    "c.py": "#| key:   value\nx = 1\n",
    "notes.txt": "not   formatted\n",
    "nested/d.yml": "d:    [1,2]\n",
    "nested/e.qmd": "#   Title\n",
    "nested/ok.yaml": "ok: 1\n",
    ".hidden/f.yaml": "f:   1\n",
    ".dot.yaml": "g:   1\n",
    "data.json": "{\"a\":1}\n",
}


@pytest.mark.parametrize("mode", ["write", "check", "diff"])
def test_directory_traversal_modes(mode, run, workdir, golden):
    """CATCHES: wrong traversal (formatting hidden paths, JSON or unsupported files), wrong
    summary counts or stream (stdout for write, stderr for check/diff), wrong exit status,
    or writing files in check/diff mode."""
    _tree(workdir, BASIC)
    flags = {"write": [], "check": ["--check"], "diff": ["--diff"]}[mode]
    result = run(["format", *flags, "."])
    assert _observe(result, workdir) == golden(f"traversal_{mode}")


def test_format_without_paths_uses_current_directory(run, workdir, golden):
    """CATCHES: `yamark format` with no PATHS doing nothing instead of formatting the
    current directory."""
    _tree(workdir, BASIC)
    result = run(["format", "--check"])
    assert _observe(result, workdir) == golden("no_paths_check")


def test_explicit_hidden_path_is_formatted(run, workdir, golden):
    """CATCHES: skipping a hidden directory or file even when it is passed explicitly."""
    _tree(workdir, BASIC)
    result = run(["format", ".hidden", ".dot.yaml"])
    assert _observe(result, workdir) == golden("explicit_hidden")


def test_single_directory_argument(run, workdir, golden):
    """CATCHES: treating `yamark format DIR` (single positional argument) differently from
    the general path list."""
    _tree(workdir, BASIC)
    result = run(["format", "nested"])
    assert _observe(result, workdir) == golden("single_directory")


def test_ignore_file_is_respected_without_git(run, workdir, golden):
    """CATCHES: ignoring `.ignore` files during traversal."""
    _tree(workdir, {**BASIC, ".ignore": "nested/\n*.md\n"})
    result = run(["format", "--check", "."])
    assert _observe(result, workdir) == golden("dot_ignore")


def test_gitignore_is_respected_in_repository(run, workdir, tool_bin, golden):
    """CATCHES: ignoring `.gitignore` inside a Git repository during traversal."""
    _tree(workdir, {**BASIC, ".gitignore": "a.yaml\nnested/d.yml\n"})
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True, capture_output=True,
                   env={"PATH": str(tool_bin), "HOME": str(workdir.parent / "home"), "GIT_CONFIG_NOSYSTEM": "1"})
    result = run(["format", "--check", "."], env_overrides={"GIT_CONFIG_NOSYSTEM": "1"})
    assert _observe(result, workdir) == golden("gitignore_repo")


def test_global_git_ignore_is_respected(run, workdir, env, golden):
    """CATCHES: ignoring the user's global Git ignore file (`$HOME/.config/git/ignore`)."""
    home = workdir.parent / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("*.yml\nb.md\n")
    _tree(workdir, BASIC)
    (workdir / ".git").mkdir()
    result = run(["format", "--check", "."], env_overrides={"GIT_CONFIG_NOSYSTEM": "1"})
    assert _observe(result, workdir) == golden("global_gitignore")


def test_explicit_ignored_file_is_formatted(run, workdir, golden):
    """CATCHES: applying ignore rules to a file named explicitly on the command line."""
    _tree(workdir, {**BASIC, ".ignore": "a.yaml\n"})
    result = run(["format", "a.yaml", "b.md"])
    assert _observe(result, workdir) == golden("explicit_ignored")


def test_nonexistent_single_path(run, workdir, golden):
    """CATCHES: a missing single path not reported as `path does not exist` with status 1."""
    result = run(["format", "missing.yaml"])
    assert _observe(result, workdir) == golden("missing_single")


def test_nonexistent_path_among_several(run, workdir, golden):
    """CATCHES: continuing silently, or formatting earlier files, when one of several PATHS
    does not exist."""
    _tree(workdir, BASIC)
    result = run(["format", "a.yaml", "missing.yaml"])
    assert _observe(result, workdir) == golden("missing_among_several")


def test_broken_symlink_single(run, workdir, golden):
    """CATCHES: following a dangling symlink instead of reporting that the path does not exist."""
    os.symlink("nowhere.yaml", workdir / "link.yaml")
    result = run(["format", "link.yaml"])
    assert _observe(result, workdir) == golden("broken_symlink_single")


def test_broken_symlink_among_several(run, workdir, golden):
    """CATCHES: wrong handling of a dangling symlink passed together with other paths."""
    _tree(workdir, BASIC)
    os.symlink("nowhere.yaml", workdir / "link.yaml")
    result = run(["format", "b.md", "link.yaml"])
    assert _observe(result, workdir) == golden("broken_symlink_several")


def test_symlinked_directory_argument(run, workdir, golden):
    """CATCHES: not descending into a directory passed through a symlink among several PATHS,
    or formatting the same file twice when it is reachable twice."""
    _tree(workdir, BASIC)
    os.symlink("nested", workdir / "alias")
    result = run(["format", "--check", "alias", "nested/d.yml", "b.md"])
    assert _observe(result, workdir) == golden("symlink_directory")


def test_symlink_inside_directory_is_not_followed(run, workdir, golden):
    """CATCHES: following symlinks found during directory traversal."""
    _tree(workdir, {"real/a.yaml": "a:   1\n", "tree/b.yaml": "b:   2\n"})
    os.symlink("../real", workdir / "tree" / "linked")
    os.symlink("../real/a.yaml", workdir / "tree" / "file.yaml")
    result = run(["format", "--check", "tree"])
    assert _observe(result, workdir) == golden("symlink_not_followed")


def test_duplicate_paths_are_formatted_once(run, workdir, golden):
    """CATCHES: counting or formatting a file twice when it is passed twice or reached both
    explicitly and through its directory."""
    _tree(workdir, BASIC)
    result = run(["format", "--check", "a.yaml", "./a.yaml", "."])
    assert _observe(result, workdir) == golden("duplicates")


def test_fifo_single_path(run, workdir, golden):
    """CATCHES: trying to read a FIFO passed as the only path instead of rejecting it as
    `path is not a file or directory`."""
    os.mkfifo(workdir / "pipe.yaml")
    result = run(["format", "pipe.yaml"])
    assert _observe(result, workdir) == golden("fifo_single")


def test_fifo_among_several(run, workdir, golden):
    """CATCHES: wrong error for a FIFO passed with other PATHS."""
    _tree(workdir, BASIC)
    os.mkfifo(workdir / "pipe.yaml")
    result = run(["format", "a.yaml", "pipe.yaml"])
    assert _observe(result, workdir) == golden("fifo_several")


def test_symlink_to_device_single(run, workdir, golden):
    """CATCHES: following a symlink to a character device instead of rejecting it."""
    os.symlink("/dev/null", workdir / "null.yaml")
    result = run(["format", "null.yaml"])
    assert _observe(result, workdir) == golden("device_symlink")


def test_unsupported_single_file_is_skipped(run, workdir, golden):
    """CATCHES: failing (instead of counting as skipped) for an explicitly named file with an
    unsupported extension."""
    _tree(workdir, BASIC)
    result = run(["format", "notes.txt"])
    assert _observe(result, workdir) == golden("unsupported_single")


@pytest.mark.parametrize(
    "name, data",
    [
        ("utf16_le.yaml", "a: 1\n".encode("utf-16")),
        ("utf16_be.yaml", b"\xfe\xff\x00a\x00:\x00 \x001\x00\n"),
        ("latin1.md", "Caf\xe9   au lait.\n".encode("latin-1")),
    ],
)
def test_undecodable_files_fail(name, data, run, workdir, golden):
    """CATCHES: lossy decoding of UTF-16 or invalid UTF-8 files in path mode instead of a
    per-file failure that leaves the bytes untouched."""
    _tree(workdir, {name: data, "ok.yaml": "ok:   1\n"})
    result = run(["format", "."])
    assert _observe(result, workdir) == golden(f"undecodable_{name.replace('.', '_')}")


def test_failure_does_not_stop_other_files(run, workdir, golden):
    """CATCHES: aborting the run (or leaving the summary out) when one file fails to format;
    other files must still be written and the run exits 1."""
    _tree(workdir, {"bad.yaml": "# fmt: on\na:   1\n", "good.yaml": "b:   2\n", "z.md": "#  Z\n"})
    result = run(["format", "."])
    assert _observe(result, workdir) == golden("partial_failure")


def test_diagnostics_in_path_mode(run, workdir, tool_bin, golden):
    """CATCHES: omitting `--diagnostics` notes in path mode, or ordering them differently
    (diagnostics are sorted by path, line, column and severity)."""
    _tree(workdir, {"b.md": "```python\nx=1\n```\n", "a.md": "```r\nx<-1\n```\n\n```python\ny=2\n```\n"})
    result = run(["format", "--diagnostics", "--check", "."], env_overrides={"PATH": str(tool_bin)})
    assert _observe(result, workdir) == golden("diagnostics_sorted")


def test_explicit_config_applies_to_traversal(run, workdir, golden):
    """CATCHES: ignoring `--config` for files found by directory traversal, or still using a
    nearer discovered yamark.toml."""
    _tree(workdir, {"conf/x.toml": "[format]\ncompact = true\n", "docs/yamark.toml": "[format]\ncompact = false\n",
                    "docs/a.yaml": "a:\n  - 1\n  - 2\n"})
    result = run(["format", "--config", "conf/x.toml", "docs"])
    assert _observe(result, workdir) == golden("explicit_config_traversal")


def test_invalid_discovered_config_during_traversal(run, workdir, golden):
    """CATCHES: skipping files under a broken yamark.toml silently during traversal."""
    _tree(workdir, {"docs/yamark.toml": "[format]\nwrap = 3.5\n", "docs/a.yaml": "a:   1\n", "b.yaml": "b:   2\n"})
    result = run(["format", "."])
    assert _observe(result, workdir) == golden("invalid_config_traversal")


def test_nearest_config_per_directory(run, workdir, golden):
    """CATCHES: using one config for the whole run instead of the nearest yamark.toml for
    each file (without merging ancestors)."""
    _tree(workdir, {
        "yamark.toml": "[format]\nwrap = 'none'\n",
        "a.md": "One sentence. Another sentence that is long enough to wrap at a column of thirty.\n",
        "sub/yamark.toml": "[format]\nwrap = 'sentence'\n",
        "sub/b.md": "One sentence. Another sentence.\n",
        "sub/deeper/c.md": "One sentence. Another sentence.\n",
    })
    result = run(["format", "."])
    assert _observe(result, workdir) == golden("nearest_config")


def test_empty_directory(run, workdir, golden):
    """CATCHES: failing or printing a non-zero scan count for an empty directory."""
    (workdir / "empty").mkdir()
    result = run(["format", "--check", "empty"])
    assert _observe(result, workdir) == golden("empty_directory")


def test_check_and_diff_conflict(run, workdir, golden):
    """CATCHES: accepting `--check` together with `--diff`."""
    _tree(workdir, BASIC)
    result = run(["format", "--check", "--diff", "a.yaml"])
    assert _observe(result, workdir) == golden("check_diff_conflict")


# ----------------------------------------------------------------------------- diff rendering


def test_diff_whitespace_only_markdown(run, workdir, golden):
    """CATCHES: leaving trailing spaces on a whitespace-only Markdown line, or rendering the
    single-line hunk header with explicit counts (`@@ -1 +1 @@` is expected)."""
    _tree(workdir, {"blank.md": "   \n", "tabs.md": "\t\n", "empty.md": "\n\n\n"})
    result = run(["format", "--diff", "blank.md", "tabs.md", "empty.md"])
    assert _observe(result, workdir) == golden("diff_whitespace_only")


def test_diff_crlf_and_missing_final_newline(run, workdir, golden):
    """CATCHES: diff output that mishandles CRLF lines or a final line without a newline."""
    _tree(workdir, {"a.yaml": "a:   1\r\nb:   2\r\nc:   3"})
    result = run(["format", "--diff", "a.yaml"])
    assert _observe(result, workdir) == golden("diff_crlf_noeol")


def test_diff_multiple_hunks_and_files(run, workdir, golden):
    """CATCHES: merging distant changes into one hunk, wrong context length, or wrong file
    ordering across several changed files."""
    lines = "".join(f"key{i}: value\n" for i in range(30))
    _tree(workdir, {"b.yaml": "first:  1\n" + lines + "last:   2\n", "a.yaml": "x:   1\n", "c.yaml": "ok: 1\n"})
    result = run(["format", "--diff", "c.yaml", "b.yaml", "a.yaml"])
    assert _observe(result, workdir) == golden("diff_multiple")


def test_linear_diff_alternating_changes(run, workdir, golden):
    """CATCHES: a diff renderer that falls back differently (or wrongly) for large inputs:
    thousands of alternating changed/unchanged lines exceed the quadratic budget and use
    the bounded linear matcher."""
    text = "".join(f"k{i}:  v\nok{i}: v\n" for i in range(2100))
    _tree(workdir, {"big.yaml": text})
    result = run(["format", "--diff", "big.yaml"])
    assert _observe(result, workdir) == golden("linear_alternating")


def test_linear_diff_trailing_removals(run, workdir, golden):
    """CATCHES: losing the trailing removed lines in the linear diff fallback."""
    text = "".join(f"Line   {i}\n\n" for i in range(2100)) + "\n\n\n\nEnd.\n"
    _tree(workdir, {"big.md": text})
    result = run(["format", "--diff", "big.md"])
    assert _observe(result, workdir) == golden("linear_trailing_removals")


def test_linear_diff_trailing_additions(run, workdir, golden):
    """CATCHES: losing trailing added lines in the linear diff fallback (block expansion of
    a long flow sequence at the end of a large file)."""
    text = "".join(f"k{i}:  v\n" for i in range(2100)) + "tail: [" + ", ".join(f"item{i}" for i in range(30)) + "]\n"
    _tree(workdir, {"big.yaml": text})
    result = run(["format", "--diff", "big.yaml"])
    assert _observe(result, workdir) == golden("linear_trailing_additions")
