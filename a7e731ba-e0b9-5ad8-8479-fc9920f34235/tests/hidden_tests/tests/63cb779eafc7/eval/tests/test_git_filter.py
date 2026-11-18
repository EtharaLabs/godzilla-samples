"""`yamark git-filter`: clean/smudge stdin filters and the setup/teardown/adopt/join/check lifecycle."""

import re

import pytest

from conftest import EXECUTABLE, GIT_ENV, assert_golden, git, make_git_repo, redact, transcript

GIT_RUN_ENV = {"GIT_CONFIG_NOSYSTEM": "1", **GIT_ENV}

PROSE = ("First sentence here. Second sentence follows it and is a bit longer than the first one, so it wraps.\n"
         "\n"
         "| a | b |\n|:---|---:|\n| long cell | x |\n")


def filter_run(run, args, text, **kwargs):
    return run(["git-filter", *args], input=text, env_overrides=GIT_RUN_ENV, **kwargs)


def repo_transcript(result, repo):
    return transcript(result, ("{{repo}}", repo), ("{{yamark}}", EXECUTABLE))


def local_config(repo, env):
    """yamark-related local config; the default executable (an absolute path to this program) becomes {{yamark}}."""
    out = git(["config", "--local", "--list"], repo, env).stdout.decode()
    lines = [line for line in out.splitlines() if "yamark" in line or line.startswith("merge.")]
    return re.sub(r"=/\S+ git-filter ", "={{yamark}} git-filter ", "\n".join(lines))


# --- clean / smudge -------------------------------------------------------------------------------


def test_clean_wraps_sentences_and_compacts_tables(run):
    """CATCHES: clean not storing one sentence per line, or not using compact pipe-table output."""
    result = filter_run(run, ["clean", "--stdin-filename", "post.md"], PROSE)
    assert (result.returncode, result.stderr) == (0, b"")
    assert result.stdout == (b"First sentence here.\nSecond sentence follows it and is a bit longer than the first "
                             b"one, so it wraps.\n\n| a | b |\n| :--- | ---: |\n| long cell | x |\n")


@pytest.mark.parametrize("width", [None, "40", "1"])
def test_smudge_wraps_columns(width, run):
    """CATCHES: smudge ignoring --markdown-wrap-at-column, using a default other than 72, or padding tables."""
    args = ["smudge", "--stdin-filename", "post.md"] + (["--markdown-wrap-at-column", width] if width else [])
    result = filter_run(run, args, PROSE)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"smudge_{width or 'default'}")


def test_clean_smudge_roundtrip(run):
    """CATCHES: clean(smudge(blob)) not reproducing a sentence-per-line blob."""
    blob = "# Title\n\nOne sentence.\nAnother sentence that is quite long and goes past the column limit easily.\n"
    smudged = filter_run(run, ["smudge", "--stdin-filename", "a.md", "--markdown-wrap-at-column", "30"], blob)
    cleaned = filter_run(run, ["clean", "--stdin-filename", "a.md"], smudged.stdout)
    assert smudged.stdout == (b"# Title\n\nOne sentence. Another sentence\nthat is quite long and goes\n"
                              b"past the column limit easily.\n")
    assert cleaned.stdout.decode() == blob


def test_filters_ignore_front_matter_markdown_options(run):
    """CATCHES: Git filters honouring editor_options.markdown (they must use their own wrapping)."""
    doc = "---\neditor_options:\n  markdown:\n    wrap: none\n---\n\nOne here. Two here.\n"
    result = filter_run(run, ["clean", "--stdin-filename", "a.md"], doc)
    assert result.stdout == b"---\neditor_options:\n  markdown:\n    wrap: none\n---\n\nOne here.\nTwo here.\n"


def test_filters_ignore_config_wrap_but_use_other_config(run, workdir):
    """CATCHES: [format].wrap overriding the filter's own wrapping, or other discovered settings (horizontal rule)
    not applying."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = \"none\"\nmarkdown_horizontal_rule = \"***\"\n")
    result = filter_run(run, ["clean", "--stdin-filename", "a.md"], "One here. Two here.\n\n---\n")
    assert result.stdout == b"One here.\nTwo here.\n\n***\n"


@pytest.mark.parametrize("name", ["a.qmd", "a.Rmd", "a.rmd", "A.MD"])
def test_filters_accept_markdown_like_paths(name, run):
    """CATCHES: rejecting Quarto/R Markdown paths or upper-case Markdown suffixes."""
    result = filter_run(run, ["clean", "--stdin-filename", name], "One. Two.\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"One.\nTwo.\n", b"")


@pytest.mark.parametrize("command", ["clean", "smudge"])
@pytest.mark.parametrize("name", ["a.yaml", "a.py", "a.txt", "README"])
def test_filters_reject_other_paths(command, name, run):
    """CATCHES: filtering YAML/source/unknown files instead of failing with 'unsupported Git filter path'."""
    result = filter_run(run, [command, "--stdin-filename", name], "a: 1\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == f"{name}:1:1: error: unsupported Git filter path\n"


def test_filter_rejects_invalid_utf8(run):
    """CATCHES: passing non-UTF-8 content through the filter instead of failing."""
    result = filter_run(run, ["smudge", "--stdin-filename", "a.md"], b"caf\xe9\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"a.md:1:1: error: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 3\n")


def test_filter_respects_skip_file(run):
    """CATCHES: filters rewriting a document marked <!-- fmt: skip file --> (while still formatting the same text
    without the directive)."""
    doc = "<!-- fmt: skip file -->\nOne.   Two.\n"
    skipped = filter_run(run, ["clean", "--stdin-filename", "a.md"], doc)
    formatted = filter_run(run, ["clean", "--stdin-filename", "a.md"], "One.   Two.\n")
    assert (skipped.stdout, formatted.stdout) == (doc.encode(), b"One.\nTwo.\n")


def test_filter_reports_directive_errors(run):
    """CATCHES: filters swallowing Markdown directive errors."""
    result = filter_run(run, ["clean", "--stdin-filename", "d/a.md"], "<!-- fmt: wrap=bad -->\nx\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == (b"d/a.md:1:6: error: fmt: wrap must be none, paragraph, sentence, a positive integer, "
                             b"or sentence:<positive integer>\n")


# --- repository helpers ----------------------------------------------------------------------------


@pytest.fixture
def repo(workdir, env):
    return make_git_repo(workdir / "repo", env, {"post.md": "First sentence. Second sentence?\n",
                                                 "notes.txt": "plain\n"}, {"core.autocrlf": "false"})


def test_not_a_repository(run, workdir):
    """CATCHES: lifecycle commands succeeding outside a Git repository or hiding git's error."""
    result = run(["git-filter", "setup"], env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == b"error: git failed: fatal: not a git repository (or any of the parent directories): .git\n"


def test_missing_repo_option_path(run, workdir):
    """CATCHES: --repo pointing at a missing directory not being reported through git's error."""
    result = run(["git-filter", "check", "--repo", "nope"], env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == b"error: git failed: fatal: cannot change to 'nope': No such file or directory\n"


# --- setup / teardown ------------------------------------------------------------------------------


def test_setup_default_patterns(run, repo, env):
    """CATCHES: setup printing a different summary, not writing the four default Markdown patterns to
    .git/info/attributes, or configuring different filter commands (clean/smudge/required/renormalize)."""
    result = run(["git-filter", "setup"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert_golden(repo_transcript(result, repo), __file__, "setup_default")
    assert (repo / ".git" / "info" / "attributes").read_text() == (
        "*.md filter=yamark-md\n*.qmd filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n")
    assert local_config(repo, env) == (
        "filter.yamark-md.clean={{yamark}} git-filter clean --stdin-filename %f\n"
        "filter.yamark-md.smudge={{yamark}} git-filter smudge --stdin-filename %f --markdown-wrap-at-column 72\n"
        "filter.yamark-md.required=true\nmerge.renormalize=true")
    assert not (repo / ".gitattributes").exists()


def test_setup_custom_width_and_executable(run, repo, env):
    """CATCHES: setup not storing --yamark / --markdown-wrap-at-column in the filter commands, or not mentioning
    the configured width in its printed advice."""
    result = run(["git-filter", "setup", "--yamark", "tools/yamark-1.0", "--markdown-wrap-at-column", "50"],
                 cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert b"    yamark format --wrap 50 NEWS.md\n" in result.stdout
    assert local_config(repo, env) == (
        "filter.yamark-md.clean=tools/yamark-1.0 git-filter clean --stdin-filename %f\n"
        "filter.yamark-md.smudge=tools/yamark-1.0 git-filter smudge --stdin-filename %f --markdown-wrap-at-column 50\n"
        "filter.yamark-md.required=true\nmerge.renormalize=true")


@pytest.mark.parametrize("exe,stored", [
    ("my yamark", "'my yamark'"),
    ("it's/yamark", "'it'\\''s/yamark'"),
    ("plain/Path_1.2-x+y", "plain/Path_1.2-x+y"),
    ("$HOME/yamark", "'$HOME/yamark'"),
])
def test_setup_shell_quotes_executable(exe, stored, run, repo, env):
    """CATCHES: storing an unquoted executable path containing shell metacharacters in the filter command (or
    quoting paths that are already shell-safe)."""
    result = run(["git-filter", "setup", "--yamark", exe], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    clean = git(["config", "--local", "filter.yamark-md.clean"], repo, env).stdout.decode()
    assert clean == f"{stored} git-filter clean --stdin-filename %f\n"


def test_setup_specific_paths_and_idempotence(run, repo, env):
    """CATCHES: setup with PATHS not writing repo-relative patterns, re-adding patterns that already exist, or
    miscounting new patterns."""
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.qmd").write_text("x\n")
    first = run(["git-filter", "setup", "--yamark", "yamark", "post.md", "docs/guide.qmd"], cwd=repo,
                env_overrides=GIT_RUN_ENV)
    second = run(["git-filter", "setup", "--yamark", "yamark", "docs/../post.md"], cwd=repo, env_overrides=GIT_RUN_ENV)
    from_subdir = run(["git-filter", "setup", "--yamark", "yamark", "guide.qmd"], cwd=repo / "docs",
                      env_overrides=GIT_RUN_ENV)
    assert first.stdout.splitlines()[1].endswith(b"/.git/info/attributes with 2 new attribute pattern(s)")
    assert second.stdout.splitlines()[1].endswith(b"/.git/info/attributes with 0 new attribute pattern(s)")
    assert from_subdir.stdout.splitlines()[1].endswith(b"/.git/info/attributes with 0 new attribute pattern(s)")
    assert (repo / ".git" / "info" / "attributes").read_text() == "post.md filter=yamark-md\ndocs/guide.qmd filter=yamark-md\n"


def test_setup_appends_after_existing_attributes(run, repo):
    """CATCHES: clobbering existing .git/info/attributes content or joining lines when it lacks a final newline."""
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.txt text\n*.md filter=yamark-md")
    result = run(["git-filter", "setup", "--yamark", "yamark"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.stdout.splitlines()[1].endswith(b"with 3 new attribute pattern(s)")
    assert (repo / ".git" / "info" / "attributes").read_text() == (
        "*.txt text\n*.md filter=yamark-md\n*.qmd filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n")


@pytest.mark.parametrize("path,message", [
    ("notes.txt", "notes.txt: unsupported Git filter path"),
    ("missing.md", "missing.md: failed to resolve path: No such file or directory (os error 2)"),
    ("with space.md", "with space.md: path contains whitespace; add this Git attribute manually"),
])
def test_setup_rejects_bad_paths(path, message, run, repo, env):
    """CATCHES: setup accepting unsupported, missing or whitespace-containing paths, or writing attributes for
    them (the filter driver config is still written before path validation)."""
    (repo / "with space.md").write_text("x\n")
    result = run(["git-filter", "setup", "--yamark", "yamark", path], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == f"error: {message}\n"
    assert not (repo / ".git" / "info" / "attributes").exists()
    assert local_config(repo, env).startswith("filter.yamark-md.clean=yamark git-filter clean")


def test_setup_rejects_path_outside_repo(run, repo, workdir):
    """CATCHES: setup writing patterns for files outside the repository."""
    (workdir / "outside.md").write_text("x\n")
    result = run(["git-filter", "setup", "--yamark", "yamark", "../outside.md"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 1
    assert redact(result.stderr.decode(), ("{{repo}}", repo)) == "error: ../outside.md: path is outside {{repo}}\n"


def test_setup_with_repo_option_from_outside(run, repo, workdir):
    """CATCHES: --repo not selecting the repository when run from another directory."""
    result = run(["git-filter", "setup", "--repo", "repo", "--yamark", "yamark"], cwd=workdir, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert redact(result.stdout.decode(), ("{{repo}}", repo)).startswith(
        "Configured yamark Git filter in {{repo}}\nUpdated {{repo}}/.git/info/attributes with 4 new attribute pattern(s)\n")


def test_setup_from_subdirectory_uses_repo_root(run, repo):
    """CATCHES: writing attributes relative to the current subdirectory instead of the repository root."""
    (repo / "sub").mkdir()
    result = run(["git-filter", "setup", "--yamark", "yamark"], cwd=repo / "sub", env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert (repo / ".git" / "info" / "attributes").read_text() == (
        "*.md filter=yamark-md\n*.qmd filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n")
    assert sorted(p.name for p in (repo / "sub").iterdir()) == []


def test_teardown_removes_setup(run, repo, env):
    """CATCHES: teardown leaving filter config behind, removing unrelated or multi-attribute lines, losing the final
    newline, or printing wrong counts."""
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text(
        "# comment filter=yamark-md\n*.txt text\n*.md   filter=yamark-md\n*.qmd filter=yamark-md diff=x\n"
        "  docs/a.md filter=yamark-md\n")
    run(["git-filter", "setup", "--yamark", "yamark"], cwd=repo, env_overrides=GIT_RUN_ENV)
    result = run(["git-filter", "teardown"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert_golden(repo_transcript(result, repo), __file__, "teardown")
    assert (repo / ".git" / "info" / "attributes").read_text() == (
        "# comment filter=yamark-md\n*.txt text\n*.qmd filter=yamark-md diff=x\n")
    assert local_config(repo, env) == ""


def test_teardown_without_setup(run, repo):
    """CATCHES: teardown failing (or reporting removals) when nothing was configured."""
    result = run(["git-filter", "teardown"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert redact(result.stdout.decode(), ("{{repo}}", repo)) == (
        "Removed yamark Git filter setup from {{repo}}\nUnset 0 local Git config value(s)\n"
        "Removed 0 yamark attribute pattern(s) from {{repo}}/.git/info/attributes\n\n"
        "Tracked files keep their current index content until staged again. Run:\n"
        "  git add --renormalize .\nif you want to restage them without the filter.\n")


def test_teardown_counts_multivalued_config(run, repo, env):
    """CATCHES: counting a multi-valued config key once instead of once per value."""
    git(["config", "--local", "--add", "merge.renormalize", "true"], repo, env)
    git(["config", "--local", "--add", "merge.renormalize", "false"], repo, env)
    result = run(["git-filter", "teardown"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.stdout.splitlines()[1] == b"Unset 2 local Git config value(s)"


def test_teardown_without_final_newline(run, repo):
    """CATCHES: adding a trailing newline that the attributes file did not have."""
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.md filter=yamark-md\n*.txt text")
    run(["git-filter", "teardown"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (repo / ".git" / "info" / "attributes").read_text() == "*.txt text"


# --- adopt -----------------------------------------------------------------------------------------


def test_adopt_normalizes_tracked_markdown(run, workdir, env):
    """CATCHES: adopt not writing shared .gitattributes patterns, not staging sentence-per-line blobs, changing the
    working-tree view, or printing a different summary."""
    repo = make_git_repo(workdir / "repo", env, {
        "a.md": "One sentence. Two sentence. A third sentence that is long enough to wrap at thirty.\n",
        "docs/b.qmd": "Alpha. Beta.\n", "notes.txt": "x. y.\n", ".gitattributes": "*.txt text\n"},
        {"core.autocrlf": "false"})
    result = run(["git-filter", "adopt", "--markdown-wrap-at-column", "30"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert_golden(repo_transcript(result, repo), __file__, "adopt")
    assert git(["status", "--porcelain"], repo, env).stdout == b"M  .gitattributes\nM  a.md\nM  docs/b.qmd\n"
    assert git(["show", ":a.md"], repo, env).stdout == (
        b"One sentence.\nTwo sentence.\nA third sentence that is long enough to wrap at thirty.\n")
    assert git(["show", ":docs/b.qmd"], repo, env).stdout == b"Alpha.\nBeta.\n"
    assert (repo / ".gitattributes").read_text() == (
        "*.txt text\n*.md filter=yamark-md\n*.qmd filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n")
    assert (repo / "a.md").read_text() == (
        "One sentence. Two sentence. A\nthird sentence that is long\nenough to wrap at thirty.\n")
    assert local_config(repo, env).splitlines()[1] == (
        "filter.yamark-md.smudge={{yamark}} git-filter smudge --stdin-filename %f --markdown-wrap-at-column 30")


def test_adopt_specific_paths(run, workdir, env):
    """CATCHES: adopt with PATHS normalizing other Markdown files or writing default patterns."""
    repo = make_git_repo(workdir / "repo", env, {"a.md": "One. Two.\n", "b.md": "Three. Four.\n"},
                         {"core.autocrlf": "false"})
    result = run(["git-filter", "adopt", "b.md"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert b"Updated .gitattributes with 1 new attribute pattern(s)\nStaged .gitattributes and 1 normalized" in \
        result.stdout
    assert (repo / ".gitattributes").read_text() == "b.md filter=yamark-md\n"
    assert git(["status", "--porcelain"], repo, env).stdout == b"A  .gitattributes\nM  b.md\n"


def test_adopt_requires_clean_worktree(run, repo):
    """CATCHES: adopting with uncommitted changes instead of refusing and listing them."""
    (repo / "new.md").write_text("x\n")
    (repo / "post.md").write_text("changed\n")
    result = run(["git-filter", "adopt"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == b"error: working tree is not clean; commit or stash changes first\n M post.md\n?? new.md\n\n"


def test_adopt_refuses_existing_local_config(run, repo, env):
    """CATCHES: adopt overwriting an existing local filter configuration."""
    git(["config", "--local", "filter.yamark-md.required", "true"], repo, env)
    result = run(["git-filter", "adopt"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stderr) == (
        1, b"error: existing local Git filter config filter.yamark-md.required is set; run yamark git-filter "
           b"teardown first\n")


def test_adopt_refuses_local_attributes(run, repo):
    """CATCHES: adopt ignoring yamark patterns already present in .git/info/attributes."""
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.md filter=yamark-md\n")
    result = run(["git-filter", "adopt"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 1
    assert redact(result.stderr.decode(), ("{{repo}}", repo)) == (
        "error: {{repo}}/.git/info/attributes already contains yamark filter attributes; run yamark git-filter "
        "teardown first\n")


def test_adopt_rolls_back_without_markdown(run, workdir, env):
    """CATCHES: adopt leaving config, .gitattributes edits or staged changes behind when no tracked Markdown file
    matches the filter."""
    repo = make_git_repo(workdir / "repo", env, {"notes.txt": "x\n", ".gitattributes": "*.txt text\n"})
    result = run(["git-filter", "adopt"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"error: no tracked Markdown files match filter=yamark-md\nRolled back yamark Git filter adoption.\n")
    assert (repo / ".gitattributes").read_text() == "*.txt text\n"
    assert local_config(repo, env) == ""
    assert git(["status", "--porcelain"], repo, env).stdout == b""


def test_adopt_rollback_removes_created_gitattributes(run, workdir, env):
    """CATCHES: leaving a newly created .gitattributes behind after a failed adoption."""
    repo = make_git_repo(workdir / "repo", env, {"notes.txt": "x\n"})
    result = run(["git-filter", "adopt"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"error: no tracked Markdown files match filter=yamark-md\nRolled back yamark Git filter adoption.\n")
    assert sorted(p.name for p in repo.iterdir()) == [".git", "notes.txt"]


def test_adopt_bad_path_rolls_back(run, repo, env):
    """CATCHES: adopt not rolling back the filter config when a requested path is invalid."""
    result = run(["git-filter", "adopt", "notes.txt"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stderr) == (
        1, b"error: notes.txt: unsupported Git filter path\nRolled back yamark Git filter adoption.\n")
    assert local_config(repo, env) == ""


# --- join / check ----------------------------------------------------------------------------------


@pytest.fixture
def adopted(workdir, env):
    """A repository whose committed Markdown blobs are already sentence-per-line with shared attributes."""
    return make_git_repo(workdir / "adopted", env, {
        ".gitattributes": "*.md filter=yamark-md\n",
        "a.md": "One sentence.\nAnother sentence that is long enough to need wrapping at a narrow width.\n",
        "sub/b.md": "Short.\n", "c.txt": "x\n"}, {"core.autocrlf": "false"})


def test_check_passes_for_normalized_blobs(run, adopted):
    """CATCHES: check failing for valid sentence-per-line blobs or miscounting checked files."""
    result = run(["git-filter", "check"], cwd=adopted, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"yamark Git filter check passed for 2 Markdown file(s).\n", b"")


def test_check_with_repo_option_and_width(run, adopted, workdir):
    """CATCHES: check ignoring --repo or --markdown-wrap-at-column."""
    result = run(["git-filter", "check", "--repo", "adopted", "--markdown-wrap-at-column", "20"], cwd=workdir,
                 env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout) == (0, b"yamark Git filter check passed for 2 Markdown file(s).\n")


def test_check_reports_roundtrip_failures(run, workdir, env):
    """CATCHES: check passing when committed blobs are not in clean form, or a different failure line format."""
    repo = make_git_repo(workdir / "repo", env, {".gitattributes": "*.md filter=yamark-md\n", "a.md": "One. Two.\n",
                                                 "b.md": "Ok.\n", "c.md": "Three.   Four.\n"})
    result = run(["git-filter", "check"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"error: a.md: roundtrip failure: clean(smudge(blob)) != blob\n"
                b"c.md: roundtrip failure: clean(smudge(blob)) != blob\n")


def test_check_requires_shared_attributes(run, repo):
    """CATCHES: check passing without a committed .gitattributes."""
    result = run(["git-filter", "check"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 1
    assert redact(result.stderr.decode(), ("{{repo}}", repo)) == (
        "error: {{repo}}/.gitattributes: failed to read shared Git attributes: No such file or directory (os error 2)\n")


def test_check_requires_yamark_attribute(run, workdir, env):
    """CATCHES: accepting a .gitattributes without filter=yamark-md (commented or other filters do not count)."""
    repo = make_git_repo(workdir / "repo", env, {".gitattributes": "# *.md filter=yamark-md\n*.md filter=lfs\n",
                                                 "a.md": "x\n"})
    result = run(["git-filter", "check"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 1
    assert redact(result.stderr.decode(), ("{{repo}}", repo)) == (
        "error: {{repo}}/.gitattributes does not contain filter=yamark-md; run yamark git-filter adopt in the "
        "maintainer checkout first\n")


def test_check_without_matching_markdown(run, workdir, env):
    """CATCHES: check passing vacuously when no tracked Markdown file has the filter attribute."""
    repo = make_git_repo(workdir / "repo", env, {".gitattributes": "docs/*.md filter=yamark-md\n", "a.md": "x\n"})
    result = run(["git-filter", "check"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stderr) == (1, b"error: no tracked Markdown files match filter=yamark-md\n")


def test_join_configures_and_smudges(run, adopted, env):
    """CATCHES: join not installing the filter driver, not writing the column-wrapped working tree, leaving the
    status dirty, or printing a different summary."""
    result = run(["git-filter", "join", "--markdown-wrap-at-column", "30"], cwd=adopted, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert redact(result.stdout.decode(), ("{{repo}}", adopted)) == (
        "Joined yamark Git filter in {{repo}}\nConfigured local filter driver and checked 2 committed Markdown "
        "file(s).\n")
    assert (adopted / "a.md").read_text() == (
        "One sentence. Another sentence\nthat is long enough to need\nwrapping at a narrow width.\n")
    assert git(["status", "--porcelain"], adopted, env).stdout == b""
    assert local_config(adopted, env).splitlines()[0] == "filter.yamark-md.clean={{yamark}} git-filter clean --stdin-filename %f"


def test_join_requires_shared_attributes(run, repo):
    """CATCHES: join proceeding in a repository that has not adopted the filter."""
    result = run(["git-filter", "join"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 1
    assert redact(result.stderr.decode(), ("{{repo}}", repo)).startswith(
        "error: {{repo}}/.gitattributes: failed to read shared Git attributes: ")


def test_join_requires_clean_worktree(run, adopted):
    """CATCHES: join running over uncommitted working-tree changes instead of refusing and listing them."""
    (adopted / "c.txt").write_text("changed\n")
    result = run(["git-filter", "join"], cwd=adopted, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stderr) == (
        1, b"error: working tree is not clean; commit or stash changes first\n M c.txt\n\n")


def test_join_refuses_when_behind_upstream(run, adopted, workdir, env):
    """CATCHES: join running on a branch that is behind its upstream instead of asking for git pull --ff-only."""
    git(["init", "-q", "--bare", "-b", "main", str(workdir / "origin.git")], workdir, env)
    git(["remote", "add", "origin", str(workdir / "origin.git")], adopted, env)
    git(["push", "-q", "-u", "origin", "main"], adopted, env)
    git(["clone", "-q", str(workdir / "origin.git"), str(workdir / "other")], workdir, env)
    (workdir / "other" / "new.md").write_text("New.\n")
    git(["add", "new.md"], workdir / "other", env)
    git(["commit", "-q", "-m", "new"], workdir / "other", env)
    git(["push", "-q", "origin", "main"], workdir / "other", env)
    git(["fetch", "-q"], adopted, env)
    result = run(["git-filter", "join"], cwd=adopted, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"error: branch is behind upstream. Run git pull --ff-only first, then run yamark git-filter join.\n")
    git(["pull", "-q", "--ff-only"], adopted, env)
    joined = run(["git-filter", "join"], cwd=adopted, env_overrides=GIT_RUN_ENV)
    assert joined.stdout.endswith(b"checked 3 committed Markdown file(s).\n")


def test_join_reports_roundtrip_failures(run, workdir, env):
    """CATCHES: join smudging blobs that are not in clean form instead of failing the round-trip check."""
    repo = make_git_repo(workdir / "repo", env, {".gitattributes": "*.md filter=yamark-md\n", "a.md": "One. Two.\n"})
    result = run(["git-filter", "join"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stderr) == (1, b"error: a.md: roundtrip failure: clean(smudge(blob)) != blob\n")


def test_teardown_leaves_unrelated_attributes_untouched(run, repo):
    """CATCHES: rewriting an attributes file that contains no yamark setup lines (including pattern-only lines)."""
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.md\n*.txt text\n   \n")
    result = run(["git-filter", "teardown"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert redact(result.stdout.decode(), ("{{repo}}", repo)).splitlines()[2] == (
        "Removed 0 yamark attribute pattern(s) from {{repo}}/.git/info/attributes")
    assert (repo / ".git" / "info" / "attributes").read_text() == "*.md\n*.txt text\n   \n"


def test_join_without_matching_markdown(run, workdir, env):
    """CATCHES: join succeeding when the shared attributes match no tracked Markdown file."""
    repo = make_git_repo(workdir / "repo", env, {".gitattributes": "docs/*.md filter=yamark-md\n", "a.md": "x\n"})
    result = run(["git-filter", "join"], cwd=repo, env_overrides=GIT_RUN_ENV)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"error: no tracked Markdown files match filter=yamark-md\n")


def test_setup_in_linked_worktree_uses_common_attributes(run, repo, workdir, env):
    """CATCHES: writing attributes into the linked worktree instead of the path Git reports for info/attributes
    (the main repository's .git/info/attributes)."""
    git(["worktree", "add", "-q", str(workdir / "wt")], repo, env)
    result = run(["git-filter", "setup", "--yamark", "yamark"], cwd=workdir / "wt", env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    lines = redact(result.stdout.decode(), ("{{wt}}", workdir / "wt"), ("{{repo}}", repo)).splitlines()
    assert lines[:2] == ["Configured yamark Git filter in {{wt}}",
                         "Updated {{repo}}/.git/info/attributes with 4 new attribute pattern(s)"]
    assert (repo / ".git" / "info" / "attributes").read_text().startswith("*.md filter=yamark-md\n")


def test_lifecycle_with_absolute_repo_option(run, repo, workdir):
    """CATCHES: --repo handling that only works for relative paths."""
    result = run(["git-filter", "teardown", "--repo", str(repo)], cwd=workdir, env_overrides=GIT_RUN_ENV)
    assert result.returncode == 0
    assert redact(result.stdout.decode(), ("{{repo}}", repo)).startswith("Removed yamark Git filter setup from {{repo}}\n")
