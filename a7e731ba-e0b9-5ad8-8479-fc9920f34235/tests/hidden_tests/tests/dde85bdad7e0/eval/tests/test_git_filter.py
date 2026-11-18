"""`yamark git-filter`: clean/smudge filters and the adopt/join/check/setup/teardown
repository helpers.

Clean always uses sentence wrapping with compact pipe tables; smudge wraps at the
given column. The repository helpers configure `filter.yamark-md.*` in the local
Git config, edit `.gitattributes` or `.git/info/attributes`, renormalise tracked
Markdown and verify that committed blobs round-trip. Each test records stdout,
stderr, exit status, `git status --porcelain`, index and worktree bytes, the local
filter configuration and the info/attributes file. The temporary repository path
and the executable path are replaced by `<repo>` and `<yamark>`.
"""

import os
import re
import subprocess

import pytest

from conftest import EXECUTABLE, outcome

FILTER_ATTRS = "*.md filter=yamark-md\n*.qmd filter=yamark-md\n"
STORED_EXE = re.compile(r"/[^\s']*/executable git-filter")


def _git_env(env, tool_bin):
    return {**env, "PATH": str(tool_bin), "GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo, env, *args, input=None):
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, input=input, check=True)


def _make_repo(workdir, env, files, config=None):
    repo = workdir / "repo"
    repo.mkdir()
    _git(repo, env, "init", "-q")
    for key, value in {
        "user.name": "Suite",
        "user.email": "suite@example.test",
        "commit.gpgSign": "false",
        "core.autocrlf": "false",
        **(config or {}),
    }.items():
        _git(repo, env, "config", key, value)
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
    _git(repo, env, "add", ".")
    _git(repo, env, "commit", "-q", "-m", "fixture")
    return repo


def _snapshot(repo, env, result, files):
    real_exe = os.path.realpath(EXECUTABLE)

    def norm(text):
        text = text.replace(str(repo.resolve()), "<repo>").replace(str(repo), "<repo>")
        text = text.replace(real_exe, "<yamark>").replace(str(EXECUTABLE), "<yamark>")
        # The default filter command embeds the running binary's absolute location.
        return STORED_EXE.sub("<yamark> git-filter", text)

    observed = outcome(result)
    observed["stdout"] = norm(observed["stdout"])
    observed["stderr"] = norm(observed["stderr"])
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, env=env, capture_output=True)
    observed["git_status"] = status.stdout.decode()
    config = subprocess.run(
        ["git", "config", "--local", "--get-regexp", r"^(filter\.yamark-md|merge)\."],
        cwd=repo, env=env, capture_output=True,
    )
    observed["filter_config"] = norm(config.stdout.decode())
    info = repo / ".git" / "info" / "attributes"
    observed["info_attributes"] = (
        "<directory>" if info.is_dir() else info.read_text() if info.exists() else None
    )
    observed["index"] = {}
    observed["worktree"] = {}
    for name in files:
        shown = subprocess.run(["git", "show", f":{name}"], cwd=repo, env=env, capture_output=True)
        observed["index"][name] = shown.stdout.decode() if shown.returncode == 0 else None
        path = repo / name
        observed["worktree"][name] = path.read_bytes().decode() if path.exists() else None
    return observed


@pytest.fixture
def git_env(env, tool_bin):
    return _git_env(env, tool_bin)


def _run_in(run, repo, git_env, *args, cwd=None):
    return run(list(args), cwd=cwd or repo, env_overrides={"PATH": git_env["PATH"], "GIT_CONFIG_NOSYSTEM": "1"})


# ----------------------------------------------------------------------------- clean / smudge

FILTER_INPUTS = {
    "sentences": "First sentence. Second sentence? Third one!\n",
    "table": (
        "| name        | value |\n| :---------- | ----: |\n| a           |     1 |\n| longer name |    22 |\n\n"
        "The table above is padded for reading. Clean compacts it again.\n"
    ),
    "frontmatter_options_ignored": (
        "---\ntitle: x\neditor_options:\n  markdown:\n    wrap: none\n---\n\n"
        "One sentence that is long enough to wrap. Two sentences that also wrap.\n"
    ),
    "long_paragraph": "This is a long paragraph that keeps going well past the column limit so it must wrap somewhere sensible. Then a second sentence.\n",
    "list_and_quote": "- item one is long enough to wrap. item two follows it.\n\n> quoted one is long enough to wrap. quoted two follows.\n",
}


@pytest.mark.parametrize("name", sorted(FILTER_INPUTS))
def test_clean_filter(name, run, golden):
    """CATCHES: a clean filter that does not use sentence wrapping, honours front-matter
    Markdown options, or pads pipe tables instead of emitting the compact form."""
    result = run(["git-filter", "clean", "--stdin-filename", "post.md"], input=FILTER_INPUTS[name])
    assert outcome(result) == golden(f"clean_{name}")


@pytest.mark.parametrize("name", sorted(FILTER_INPUTS))
def test_smudge_filter(name, run, golden):
    """CATCHES: a smudge filter that ignores `--markdown-wrap-at-column` or applies sentence
    wrapping instead of column wrapping."""
    result = run(
        ["git-filter", "smudge", "--stdin-filename", "post.md", "--markdown-wrap-at-column", "30"],
        input=FILTER_INPUTS[name],
    )
    assert outcome(result) == golden(f"smudge_{name}")


def test_smudge_default_width(run, golden):
    """CATCHES: a smudge filter whose default `--markdown-wrap-at-column` is not 72 columns."""
    text = "word " * 30 + "\n"
    result = run(["git-filter", "smudge", "--stdin-filename", "notes.qmd"], input=text)
    assert outcome(result) == golden("smudge_default_width")


@pytest.mark.parametrize("filename", ["notes.txt", "data.yaml", "README"])
def test_filter_rejects_non_markdown_paths(filename, run, golden):
    """CATCHES: filtering non-Markdown files (YAML, text, no extension) instead of failing
    with `unsupported Git filter path`."""
    result = run(["git-filter", "clean", "--stdin-filename", filename], input="a:  1\n")
    assert outcome(result) == golden(f"reject_{filename.replace('.', '_')}")


def test_filter_accepts_rmd(run, golden):
    """CATCHES: case-sensitive Markdown suffix matching in the filters (`.Rmd`)."""
    result = run(["git-filter", "clean", "--stdin-filename", "doc.Rmd"], input="First sentence. Second sentence.\n")
    assert outcome(result) == golden("clean_rmd")


# ----------------------------------------------------------------------------- setup / teardown


def test_setup_configures_driver_and_info_attributes(run, workdir, git_env, golden):
    """CATCHES: setup writing the shared .gitattributes instead of .git/info/attributes,
    wrong clean/smudge commands, a missing `required`/`merge.renormalize` setting, or a
    different summary text."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "setup", "--markdown-wrap-at-column", "50")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("setup_default")


def test_setup_twice_adds_no_duplicate_patterns(run, workdir, git_env, golden):
    """CATCHES: appending duplicate attribute patterns when setup runs again."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    _run_in(run, repo, git_env, "git-filter", "setup")
    result = _run_in(run, repo, git_env, "git-filter", "setup")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("setup_twice")


def test_setup_with_specific_paths(run, workdir, git_env, golden):
    """CATCHES: ignoring explicit PATHS and writing the default Markdown patterns instead."""
    repo = _make_repo(workdir, git_env, {"docs/a.md": "A. B.\n", "NEWS.md": "C. D.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "setup", "docs/a.md", "NEWS.md")
    assert _snapshot(repo, git_env, result, ["docs/a.md", "NEWS.md"]) == golden("setup_paths")


def test_setup_custom_yamark_path_is_shell_quoted(run, workdir, git_env, golden):
    """CATCHES: storing a custom `--yamark` path with spaces or quotes unquoted in the
    filter commands."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "setup", "--yamark", "/opt/my tools/it's/yamark")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("setup_quoted_yamark")


def test_teardown_after_setup(run, workdir, git_env, golden):
    """CATCHES: teardown leaving filter config or yamark attribute lines behind, or reporting
    wrong counts."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    _run_in(run, repo, git_env, "git-filter", "setup")
    result = _run_in(run, repo, git_env, "git-filter", "teardown")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("teardown_after_setup")


def test_teardown_without_setup(run, workdir, git_env, golden):
    """CATCHES: teardown failing (instead of reporting zero removals) in an unconfigured repo."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "teardown")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("teardown_without_setup")


def test_teardown_keeps_unrelated_attribute_lines(run, workdir, git_env, golden):
    """CATCHES: teardown deleting user attribute lines that are not yamark filter patterns."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    info = repo / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "attributes").write_text("*.png binary\n*.md filter=yamark-md\nNEWS.md -filter\n")
    _git(repo, git_env, "config", "filter.yamark-md.clean", "x")
    result = _run_in(run, repo, git_env, "git-filter", "teardown")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("teardown_unrelated_lines")


# ----------------------------------------------------------------------------- adopt


def test_adopt_normalizes_and_stages(run, workdir, git_env, golden):
    """CATCHES: adopt not staging .gitattributes plus renormalised Markdown, writing clean
    (sentence-wrapped) text to the worktree instead of smudged text, or wrong summary."""
    files = {"post.md": "First sentence. Second sentence that is fairly long.\n", "notes.qmd": "A. B.\n", "other.txt": "x\n"}
    repo = _make_repo(workdir, git_env, files)
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "--markdown-wrap-at-column", "30")
    assert _snapshot(repo, git_env, result, [".gitattributes", *files]) == golden("adopt_default")


def test_adopt_specific_paths(run, workdir, git_env, golden):
    """CATCHES: adopt renormalising every Markdown file when only some PATHS were requested."""
    files = {"a.md": "One. Two.\n", "b.md": "Three. Four.\n"}
    repo = _make_repo(workdir, git_env, files)
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "a.md")
    assert _snapshot(repo, git_env, result, [".gitattributes", *files]) == golden("adopt_paths")


def test_adopt_refuses_dirty_worktree(run, workdir, git_env, golden):
    """CATCHES: adopt proceeding with uncommitted changes instead of failing with the status listing."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    (repo / "post.md").write_text("changed. text.\n")
    result = _run_in(run, repo, git_env, "git-filter", "adopt")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("adopt_dirty")


def test_adopt_without_markdown_rolls_back(run, workdir, git_env, golden):
    """CATCHES: leaving config/attribute changes behind when adopt finds no Markdown files;
    the reference reports the error and rolls back."""
    repo = _make_repo(workdir, git_env, {"data.yaml": "a: 1\n"})
    result = _run_in(run, repo, git_env, "git-filter", "adopt")
    assert _snapshot(repo, git_env, result, [".gitattributes", "data.yaml"]) == golden("adopt_no_markdown")


def test_adopt_refuses_existing_local_setup(run, workdir, git_env, golden):
    """CATCHES: adopt silently replacing a local `git-filter setup` instead of refusing."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    _run_in(run, repo, git_env, "git-filter", "setup")
    result = _run_in(run, repo, git_env, "git-filter", "adopt")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("adopt_local_setup")


def test_adopt_with_existing_gitattributes(run, workdir, git_env, golden):
    """CATCHES: overwriting existing .gitattributes content or duplicating present patterns."""
    files = {".gitattributes": "*.png binary\n*.md filter=yamark-md\n", "post.md": "A. B.\n"}
    repo = _make_repo(workdir, git_env, files)
    result = _run_in(run, repo, git_env, "git-filter", "adopt")
    assert _snapshot(repo, git_env, result, list(files)) == golden("adopt_existing_attributes")


def test_adopt_from_subdirectory_with_repo_option(run, workdir, git_env, golden):
    """CATCHES: ignoring `--repo` and using the current directory as the repository."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n", "sub/keep.txt": "k\n"})
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "--repo", "..", cwd=repo / "sub")
    assert _snapshot(repo, git_env, result, [".gitattributes", "post.md"]) == golden("adopt_repo_option")


# ----------------------------------------------------------------------------- join / check


def _adopted_repo(workdir, git_env, files):
    repo = _make_repo(workdir, git_env, {".gitattributes": FILTER_ATTRS, **files})
    return repo


def test_join_configures_and_smudges(run, workdir, git_env, golden):
    """CATCHES: join not configuring the driver, not verifying committed blobs, or leaving
    the worktree in clean (unsmudged) form."""
    repo = _adopted_repo(workdir, git_env, {"post.md": "First sentence.\nSecond sentence.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "join", "--markdown-wrap-at-column", "60")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("join_default")


def test_join_requires_shared_attributes(run, workdir, git_env, golden):
    """CATCHES: join succeeding in a repository whose .gitattributes never adopted the filter."""
    repo = _make_repo(workdir, git_env, {"post.md": "A.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "join")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("join_no_attributes")


def test_join_refuses_dirty_worktree(run, workdir, git_env, golden):
    """CATCHES: join running over uncommitted or untracked changes instead of refusing with the status listing."""
    repo = _adopted_repo(workdir, git_env, {"post.md": "A.\n"})
    (repo / "new.md").write_text("untracked\n")
    result = _run_in(run, repo, git_env, "git-filter", "join")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("join_dirty")


def test_join_rejects_noncanonical_committed_blob(run, workdir, git_env, golden):
    """CATCHES: join accepting committed Markdown that does not round-trip through clean."""
    repo = _adopted_repo(workdir, git_env, {"post.md": "One sentence. Two sentences on one line.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "join")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("join_noncanonical")


def test_check_passes_for_canonical_blobs(run, workdir, git_env, golden):
    """CATCHES: check failing or miscounting when every committed blob is already clean."""
    repo = _adopted_repo(workdir, git_env, {"a.md": "One.\nTwo.\n", "b.qmd": "Three.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "check")
    assert _snapshot(repo, git_env, result, ["a.md", "b.qmd"]) == golden("check_pass")


def test_check_reports_noncanonical_blobs(run, workdir, git_env, golden):
    """CATCHES: check passing (or reporting different paths/messages) when committed blobs
    are not in clean form."""
    files = {"a.md": "One. Two.\n", "b.md": "| a | b |\n|---|---|\n| x | y |\n", "c.md": "Fine.\n"}
    repo = _adopted_repo(workdir, git_env, files)
    result = _run_in(run, repo, git_env, "git-filter", "check")
    assert _snapshot(repo, git_env, result, list(files)) == golden("check_fail")


def test_check_without_attributes(run, workdir, git_env, golden):
    """CATCHES: check succeeding in a repository without yamark attributes."""
    repo = _make_repo(workdir, git_env, {"a.md": "One.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "check")
    assert _snapshot(repo, git_env, result, ["a.md"]) == golden("check_no_attributes")


def test_check_with_no_matching_files(run, workdir, git_env, golden):
    """CATCHES: check passing vacuously when attributes exist but no tracked file matches."""
    repo = _make_repo(workdir, git_env, {".gitattributes": FILTER_ATTRS, "data.yaml": "a: 1\n"})
    result = _run_in(run, repo, git_env, "git-filter", "check")
    assert _snapshot(repo, git_env, result, ["data.yaml"]) == golden("check_no_files")


def test_check_outside_repository(run, workdir, git_env, golden):
    """CATCHES: a repository helper that does not fail cleanly outside a Git repository."""
    outside = workdir / "plain"
    outside.mkdir()
    result = run(["git-filter", "check"], cwd=outside, env_overrides={"PATH": git_env["PATH"], "GIT_CONFIG_NOSYSTEM": "1", "GIT_CEILING_DIRECTORIES": str(workdir)})
    observed = outcome(result)
    observed["stderr"] = observed["stderr"].replace(str(outside), "<dir>")
    assert observed == golden("check_outside_repo")


# ----------------------------------------------------------------------------- unusual paths and line endings


def _add_index_only_file(repo, env, name_bytes, contents):
    """Stage a file whose name is not valid UTF-8 without creating it in the worktree."""
    blob = _git(repo, env, "hash-object", "-w", "--stdin", input=contents.encode()).stdout.decode().strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo", "100644", blob, os.fsdecode(name_bytes)],
                   cwd=repo, env=env, check=True, capture_output=True)
    subprocess.run(["git", "update-index", "--skip-worktree", "--", os.fsdecode(name_bytes)],
                   cwd=repo, env=env, check=True, capture_output=True)


def _commit_all(repo, env):
    _git(repo, env, "commit", "-q", "-m", "index-only files")


def test_check_with_non_utf8_markdown_name(run, workdir, git_env, golden):
    """CATCHES: rejecting or skipping committed Markdown whose path is not valid UTF-8; the
    reference checks it like any other tracked file (and ignores unrelated binary names)."""
    repo = _make_repo(workdir, git_env, {".gitattributes": "*.md filter=yamark-md\n", "post.md": "First.\nSecond?\n"},
                      config={"core.quotePath": "true"})
    _add_index_only_file(repo, git_env, b"unrelated-\xff.bin", "unrelated file\n")
    _add_index_only_file(repo, git_env, b"post-\xff.md", "First.\nSecond?\n")
    _commit_all(repo, git_env)
    result = _run_in(run, repo, git_env, "git-filter", "check")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("check_non_utf8")


def test_check_with_non_utf8_noncanonical_markdown(run, workdir, git_env, golden):
    """CATCHES: wrong failure reporting for a non-UTF-8 Markdown path whose blob does not
    round-trip (the error must name the path as Git quotes it)."""
    repo = _make_repo(workdir, git_env, {".gitattributes": "*.md filter=yamark-md\n", "post.md": "First.\nSecond?\n"},
                      config={"core.quotePath": "true"})
    _add_index_only_file(repo, git_env, b"post-\xff.md", "First sentence. Second sentence?\n")
    _commit_all(repo, git_env)
    result = _run_in(run, repo, git_env, "git-filter", "check")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("check_non_utf8_noncanonical")


def test_adopt_with_unrelated_non_utf8_file(run, workdir, git_env, golden):
    """CATCHES: adopt failing on an unrelated tracked file with a non-UTF-8 name."""
    repo = _make_repo(workdir, git_env, {"post.md": "First sentence. Second sentence?\n"}, config={"core.quotePath": "true"})
    _add_index_only_file(repo, git_env, b"unrelated-\xff.bin", "unrelated file\n")
    _commit_all(repo, git_env)
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "--markdown-wrap-at-column", "32")
    assert _snapshot(repo, git_env, result, [".gitattributes", "post.md"]) == golden("adopt_non_utf8_unrelated")


def test_adopt_unicode_and_space_paths(run, workdir, git_env, golden):
    """CATCHES: mishandling Markdown paths containing non-ASCII characters or spaces."""
    files = {"café.md": "First sentence. Second sentence?\n", "with space.md": "Third sentence. Fourth sentence?\n"}
    repo = _make_repo(workdir, git_env, files, config={"core.quotePath": "true"})
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "--markdown-wrap-at-column", "32")
    assert _snapshot(repo, git_env, result, [".gitattributes", *files]) == golden("adopt_unicode_paths")


@pytest.mark.parametrize(
    "case",
    ["autocrlf_true", "eol_crlf_attribute", "eol_lf_attribute"],
)
def test_adopt_line_endings(case, run, workdir, git_env, golden):
    """CATCHES: staging CRLF bytes into the index, or writing the wrong line endings back
    to the worktree, when autocrlf or an explicit `eol` attribute is in effect."""
    if case == "autocrlf_true":
        files = {".gitattributes": "*.md text\n", "post.md": "First sentence. Second sentence?\r\n"}
        config = {"core.autocrlf": "true"}
    elif case == "eol_crlf_attribute":
        files = {".gitattributes": "*.md text eol=crlf\n", "post.md": "First sentence. Second sentence?\r\n"}
        config = {}
    else:
        files = {".gitattributes": "*.md text eol=lf\n", "post.md": "First sentence. Second sentence?\n"}
        config = {"core.autocrlf": "true"}
    repo = _make_repo(workdir, git_env, files, config=config)
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "--markdown-wrap-at-column", "32")
    assert _snapshot(repo, git_env, result, list(files)) == golden(f"adopt_{case}")


def test_join_with_autocrlf(run, workdir, git_env, golden):
    """CATCHES: join leaving a dirty CRLF checkout when core.autocrlf=true."""
    files = {".gitattributes": "*.md filter=yamark-md\n", "post.md": "First sentence.\r\nSecond sentence?\r\n"}
    repo = _make_repo(workdir, git_env, files, config={"core.autocrlf": "true"})
    result = _run_in(run, repo, git_env, "git-filter", "join", "--markdown-wrap-at-column", "32")
    assert _snapshot(repo, git_env, result, list(files)) == golden("join_autocrlf")


def test_check_uses_nearest_yamark_toml(run, workdir, git_env, golden):
    """CATCHES: ignoring the committed file's yamark.toml (`markdown_horizontal_rule`) during
    the round-trip check run from another directory with `--repo`."""
    files = {".gitattributes": "*.md filter=yamark-md\n", "docs/yamark.toml": "[format]\nmarkdown_horizontal_rule = \"***\"\n",
             "docs/post.md": "***\n", "caller/.keep": ""}
    repo = _make_repo(workdir, git_env, files)
    result = _run_in(run, repo, git_env, "git-filter", "check", "--repo", "..", cwd=repo / "caller")
    assert _snapshot(repo, git_env, result, ["docs/post.md"]) == golden("check_repo_config")


# ----------------------------------------------------------------------------- more refusal paths


@pytest.mark.parametrize("command", ["setup", "teardown", "adopt", "join"])
def test_repository_commands_outside_repository(command, run, workdir, git_env, golden):
    """CATCHES: setup/teardown/adopt/join not failing cleanly (status 1, Git's message) when
    run outside any Git repository."""
    outside = workdir / "plain"
    outside.mkdir()
    result = run(["git-filter", command], cwd=outside,
                 env_overrides={"PATH": git_env["PATH"], "GIT_CONFIG_NOSYSTEM": "1", "GIT_CEILING_DIRECTORIES": str(workdir)})
    observed = outcome(result)
    observed["stderr"] = observed["stderr"].replace(str(outside), "<dir>")
    assert observed == golden(f"outside_repo_{command}")


def test_join_with_attributes_lacking_yamark(run, workdir, git_env, golden):
    """CATCHES: join accepting a shared .gitattributes that has no yamark filter patterns."""
    repo = _make_repo(workdir, git_env, {".gitattributes": "*.png binary\n", "post.md": "A.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "join")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("join_attributes_without_yamark")


def test_join_without_markdown_files(run, workdir, git_env, golden):
    """CATCHES: join succeeding vacuously when no tracked file matches the filter."""
    repo = _make_repo(workdir, git_env, {".gitattributes": FILTER_ATTRS, "data.yaml": "a: 1\n"})
    result = _run_in(run, repo, git_env, "git-filter", "join")
    assert _snapshot(repo, git_env, result, ["data.yaml"]) == golden("join_no_markdown")


def test_adopt_refuses_local_info_attributes(run, workdir, git_env, golden):
    """CATCHES: adopt ignoring yamark patterns already present in .git/info/attributes."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.md filter=yamark-md\n")
    result = _run_in(run, repo, git_env, "git-filter", "adopt")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("adopt_local_info_attributes")


def test_join_refuses_when_behind_upstream(run, workdir, git_env, golden):
    """CATCHES: join running on a branch that is behind its upstream instead of asking for
    `git pull --ff-only` first."""
    origin = _make_repo(workdir, git_env, {".gitattributes": FILTER_ATTRS, "post.md": "One.\n"})
    clone = workdir / "clone"
    _git(workdir, git_env, "clone", "-q", str(origin), str(clone))
    for key, value in {"user.name": "Suite", "user.email": "suite@example.test", "commit.gpgSign": "false"}.items():
        _git(clone, git_env, "config", key, value)
    (origin / "post.md").write_text("One.\nTwo.\n")
    _git(origin, git_env, "commit", "-q", "-am", "advance")
    _git(clone, git_env, "fetch", "-q")
    result = _run_in(run, clone, git_env, "git-filter", "join")
    observed = _snapshot(clone, git_env, result, ["post.md"])
    assert observed == golden("join_behind_upstream")


def test_setup_with_non_utf8_yamark_path(run, workdir, git_env, golden):
    """CATCHES: storing a `--yamark` path that is not valid UTF-8 instead of rejecting it."""
    repo = _make_repo(workdir, git_env, {"post.md": "A.\n"})
    bad = os.fsdecode(b"/opt/bin-\xff/yamark")
    result = _run_in(run, repo, git_env, "git-filter", "setup", "--yamark", bad)
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("setup_non_utf8_yamark")


def test_adopt_with_narrow_smudge_width(run, workdir, git_env, golden):
    """CATCHES: adopt mis-staging the clean form or mis-smudging the worktree when the smudge
    width is tiny (5 columns) and the file mixes a pipe table with prose."""
    files = {"post.md": "| a |\n|---|\n| x |\n\nAn ordinary paragraph of several words.\n"}
    repo = _make_repo(workdir, git_env, files)
    result = _run_in(run, repo, git_env, "git-filter", "adopt", "--markdown-wrap-at-column", "5")
    assert _snapshot(repo, git_env, result, [".gitattributes", "post.md"]) == golden("adopt_roundtrip_narrow")


# ----------------------------------------------------------------------------- attribute files


@pytest.mark.parametrize(
    "name, path",
    [
        ("non_markdown", "notes.txt"),
        ("missing", "missing.md"),
        ("outside", "../outside.md"),
        ("whitespace", "with space.md"),
        ("nested_ok", "docs/./guide.md"),
    ],
)
def test_setup_path_validation(name, path, run, workdir, git_env, golden):
    """CATCHES: accepting non-Markdown, missing, outside-repository or whitespace-containing
    PATHS for `setup` (or mis-normalising a valid nested path into its attribute pattern)."""
    (workdir / "outside.md").write_text("x\n")
    repo = _make_repo(workdir, git_env, {"notes.txt": "n\n", "with space.md": "w\n", "docs/guide.md": "g\n"})
    result = _run_in(run, repo, git_env, "git-filter", "setup", path)
    observed = _snapshot(repo, git_env, result, ["docs/guide.md"])
    observed["stderr"] = observed["stderr"].replace(str(workdir), "<workdir>")
    assert observed == golden(f"setup_path_{name}")


def test_setup_appends_to_attributes_without_final_newline(run, workdir, git_env, golden):
    """CATCHES: gluing a new pattern onto an existing attributes line that lacks a newline."""
    repo = _make_repo(workdir, git_env, {"post.md": "A.\n"})
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.png binary")
    result = _run_in(run, repo, git_env, "git-filter", "setup", "post.md")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("setup_append_no_newline")


def test_teardown_line_matching_rules(run, workdir, git_env, golden):
    """CATCHES: teardown removing commented, multi-attribute or pattern-only lines; only lines
    of exactly `<pattern> filter=yamark-md` are yamark setup lines."""
    repo = _make_repo(workdir, git_env, {"post.md": "A.\n"})
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text(
        "# *.md filter=yamark-md\n\n*.md\n*.qmd filter=yamark-md diff\n  docs/*.md filter=yamark-md\n*.Rmd filter=yamark-md"
    )
    result = _run_in(run, repo, git_env, "git-filter", "teardown")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("teardown_matching_rules")


@pytest.mark.parametrize("command", ["setup", "teardown", "adopt"])
def test_info_attributes_is_a_directory(command, run, workdir, git_env, golden):
    """CATCHES: ignoring read failures of .git/info/attributes (here a directory) instead of
    reporting `failed to read attributes`."""
    repo = _make_repo(workdir, git_env, {"post.md": "A.\n"})
    (repo / ".git" / "info" / "attributes").mkdir(parents=True)
    result = _run_in(run, repo, git_env, "git-filter", command)
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden(f"info_attributes_dir_{command}")


def test_join_ignores_commented_shared_attribute(run, workdir, git_env, golden):
    """CATCHES: counting a commented-out `filter=yamark-md` line in .gitattributes as adoption."""
    repo = _make_repo(workdir, git_env, {".gitattributes": "# *.md filter=yamark-md\n", "post.md": "A.\n"})
    result = _run_in(run, repo, git_env, "git-filter", "join")
    assert _snapshot(repo, git_env, result, ["post.md"]) == golden("join_commented_attribute")


# ----------------------------------------------------------------------------- environment edges


@pytest.mark.parametrize("command", ["check", "setup", "teardown", "adopt", "join"])
def test_git_missing_from_path(command, run, workdir, git_env, tool_bin, golden):
    """CATCHES: crashing or reporting a different error when the `git` executable cannot be
    found; the reference fails with `failed to run git` and status 1."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    nogit = workdir / "nogit"
    nogit.mkdir()
    result = run(["git-filter", command], cwd=repo, env_overrides={"PATH": str(nogit)})
    assert outcome(result) == golden(f"git_missing_{command}")


def test_setup_and_teardown_in_linked_worktree(run, workdir, git_env, golden):
    """CATCHES: resolving `.git/info/attributes` relative to a linked worktree instead of the
    absolute common Git directory that Git reports."""
    repo = _make_repo(workdir, git_env, {"post.md": "A. B.\n"})
    _git(repo, git_env, "worktree", "add", "-q", str(workdir / "wt"))
    wt = workdir / "wt"
    setup = _run_in(run, wt, git_env, "git-filter", "setup")
    teardown = _run_in(run, wt, git_env, "git-filter", "teardown")

    def norm(text):
        return text.replace(str(wt), "<worktree>").replace(str(repo), "<repo>")

    observed = {
        name: {**outcome(result), "stdout": norm(outcome(result)["stdout"])}
        for name, result in (("setup", setup), ("teardown", teardown))
    }
    info = repo / ".git" / "info" / "attributes"
    observed["info_attributes_after"] = info.read_text() if info.exists() else None
    assert observed == golden("linked_worktree")
