"""Black-box tests for `yamark git-filter`: the clean/smudge codecs and the repository lifecycle.

`clean` stores Markdown sentence-per-line and `smudge` writes it column-wrapped, both with
compact pipe tables. `adopt`, `join`, `check`, `setup`, and `teardown` are exercised against real
Git repositories created inside the test's work directory. Git runs with the fixture environment
(temporary HOME, no system config) and every repository sets its identity, `commit.gpgSign=false`
and `core.autocrlf=false` locally. A `yamark` symlink to the binary under test is placed on PATH so
filter commands stored as `--yamark yamark` resolve to it. Absolute repository paths in messages are
replaced by `{repo}`; commit hashes and dates are never asserted.
"""

import os
import shutil
import subprocess

import pytest

from conftest import EXECUTABLE, as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

CANONICAL = "First sentence.\nSecond sentence?\n"
WRAPPED = "First sentence. Second sentence?\n"
DEFAULT_PATTERNS = "*.md filter=yamark-md\n*.qmd filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n"
ROUNDTRIP_FAILURE = ": roundtrip failure: clean(smudge(blob)) != blob"
CONFIG_LOCKED = "error: git config failed: error: could not lock config file .git/config: File exists\n"


# --------------------------------------------------------------------------------------- helpers
@pytest.fixture
def genv(tmp_path, env):
    """Fixture env plus a `yamark` command on PATH and no system-wide Git configuration."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "yamark").symlink_to(EXECUTABLE)
    return {**env, "PATH": f"{bindir}{os.pathsep}{env['PATH']}", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(tmp_path)}


@pytest.fixture
def yamark(run, genv):
    """Run the binary under test with the Git-aware environment."""

    def _yamark(*args, cwd=None, input=None):
        overrides = {key: genv[key] for key in ("PATH", "GIT_CONFIG_NOSYSTEM", "GIT_CEILING_DIRECTORIES")}
        return run(list(args), cwd=cwd, input=input, env_overrides=overrides)

    return _yamark


def git(genv, cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, env=genv, capture_output=True, stdin=subprocess.DEVNULL,
                            timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def init_repo(genv, root, config=()):
    root.mkdir(parents=True, exist_ok=True)
    git(genv, root, "init", "-q", "-b", "main")
    settings = (("user.name", "Git Filter Test"), ("user.email", "git-filter@example.test"),
                ("commit.gpgSign", "false"), ("core.autocrlf", "false"), *config)
    for key, value in settings:
        git(genv, root, "config", key, value)


def make_repo(genv, root, files, config=()):
    """Create a repository at root, write files, and commit them."""
    init_repo(genv, root, config)
    write_tree(root, files)
    git(genv, root, "add", ".")
    git(genv, root, "commit", "-q", "-m", "fixture")


def filter_config(genv, repo):
    """The local yamark filter driver and merge settings, as `git config --get-regexp` prints them."""
    result = subprocess.run(["git", "config", "--local", "--get-regexp", r"^(filter\.yamark-md\.|merge\.renormalize)"],
                            cwd=repo, env=genv, capture_output=True, stdin=subprocess.DEVNULL, timeout=20)
    return result.stdout.decode()


def expected_config(width, command="yamark"):
    return (
        f"filter.yamark-md.clean {command} git-filter clean --stdin-filename %f\n"
        f"filter.yamark-md.smudge {command} git-filter smudge --stdin-filename %f --markdown-wrap-at-column {width}\n"
        "filter.yamark-md.required true\n"
        "merge.renormalize true\n"
    )


def blob(genv, repo, spec):
    """Bytes of a blob such as `:path` (index) or `HEAD:path`."""
    return git(genv, repo, "show", spec)


def status(genv, repo):
    return git(genv, repo, "status", "--porcelain").decode()


def worktree(repo):
    """Working-tree files outside .git as {posix path: bytes}."""
    return {name: data for name, data in read_tree(repo).items() if not name.startswith(".git/")}


def norm(data, repo):
    """Decode output and replace the absolute repository path with {repo}."""
    return data.decode().replace(str(repo.resolve()), "{repo}")


def setup_summary(added, width=72, attributes="{repo}/.git/info/attributes", root="{repo}"):
    return (
        f"Configured yamark Git filter in {root}\n"
        f"Updated {attributes} with {added} new attribute pattern(s)\n"
        "\n"
        "Next step:\n"
        "  git add --renormalize .\n"
        "\n"
        "Undo:\n"
        "  Temporarily stage one file exactly as it appears in the working tree:\n"
        "    git -c filter.yamark-md.clean=cat add <path>\n"
        "  Permanently remove this local setup:\n"
        "    yamark git-filter teardown\n"
        "\n"
        "Per-file control:\n"
        "  Add later Git attribute lines to .git/info/attributes or .gitattributes:\n"
        "    NEWS.md -filter\n"
        "  Then use the normal formatter for that file, for example:\n"
        f"    yamark format --wrap {width} NEWS.md\n"
        "  Use <!-- fmt: skip file --> inside a Markdown file to leave its contents untouched.\n"
    )


def teardown_summary(unset, removed, root="{repo}"):
    return (
        f"Removed yamark Git filter setup from {root}\n"
        f"Unset {unset} local Git config value(s)\n"
        f"Removed {removed} yamark attribute pattern(s) from {root}/.git/info/attributes\n"
        "\n"
        "Tracked files keep their current index content until staged again. Run:\n"
        "  git add --renormalize .\n"
        "if you want to restage them without the filter.\n"
    )


def adopt_summary(added, staged, root="{repo}"):
    return (
        f"Adopted yamark Git filter in {root}\n"
        f"Updated .gitattributes with {added} new attribute pattern(s)\n"
        f"Staged .gitattributes and {staged} normalized Markdown file(s).\n"
        "\n"
        "Review and commit with:\n"
        "  git diff --cached\n"
        '  git commit -m "Normalize Markdown with yamark Git filter"\n'
    )


def join_summary(checked, root="{repo}"):
    return (
        f"Joined yamark Git filter in {root}\n"
        f"Configured local filter driver and checked {checked} committed Markdown file(s).\n"
    )


# --------------------------------------------------------------------------- clean / smudge codecs
FRONT_MATTER_DOC = (
    "---\n"
    'title:   "Filter test"\n'
    "tags: [a,   b]\n"
    "editor_options:\n"
    "  markdown:\n"
    "    wrap: none\n"
    "    canonical: true\n"
    "---\n"
    "\n"
    "This is __strong__ and _emphasis_. The second sentence is long enough that a narrow column has to wrap it twice.\n"
)
FRONT_MATTER_HEAD = (
    "---\n"
    "title: Filter test\n"
    "tags: [a, b]\n"
    "editor_options:\n"
    "  markdown:\n"
    "    wrap: none\n"
    "    canonical: true\n"
    "---\n"
    "\n"
)


def test_filters_ignore_front_matter_markdown_options(run):
    """CATCHES: clean/smudge filters that honour `editor_options.markdown` (wrap: none / canonical: true) from
    front matter, leaving prose unsplit or unwrapped or rewriting __strong__ to **strong**, or that skip
    formatting the YAML front matter itself."""
    result = run(["git-filter", "clean", "--stdin-filename", "docs/post.md"], input=FRONT_MATTER_DOC)
    assert result.stdout.decode() == FRONT_MATTER_HEAD + (
        "This is __strong__ and _emphasis_.\n"
        "The second sentence is long enough that a narrow column has to wrap it twice.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "post.md", "--markdown-wrap-at-column", "30"],
                 input=FRONT_MATTER_DOC)
    assert result.stdout.decode() == FRONT_MATTER_HEAD + (
        "This is __strong__ and\n"
        "_emphasis_. The second\n"
        "sentence is long enough that a\n"
        "narrow column has to wrap it\n"
        "twice.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0


def test_filters_write_compact_pipe_tables(run):
    """CATCHES: filters that pad pipe-table cells to aligned column widths (the `format` default) instead of
    compact `| a | b |` rows with `:---`/`---:`/`:---:` delimiters, that drop alignment markers or the escaped
    pipe inside a code span, or that wrap table rows at a narrow column."""
    source = (
        "Before the table. After words.\n"
        "\n"
        "| Name      | Score | Notes                |\n"
        "|:----------|------:|:--------------------:|\n"
        "| Alice     |    10 | first, very long one |\n"
        "| Bob       |     7 | `a \\| b`             |\n"
    )
    table = (
        "| Name | Score | Notes |\n"
        "| :--- | ---: | :---: |\n"
        "| Alice | 10 | first, very long one |\n"
        "| Bob | 7 | `a \\| b` |\n"
    )
    result = run(["git-filter", "clean", "--stdin-filename", "table.md"], input=source)
    assert result.stdout.decode() == "Before the table.\nAfter words.\n\n" + table
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "table.md", "--markdown-wrap-at-column", "20"],
                 input=source)
    assert result.stdout.decode() == "Before the table.\nAfter words.\n\n" + table
    assert result.stderr == b""
    assert result.returncode == 0


def test_filters_wrap_lists_and_quotes(run):
    """CATCHES: filters that only handle top-level paragraphs: clean must align continuation sentences with
    the list item text (nested items deeper) and keep `> ` on quote lines; smudge must count the marker and
    quote prefix when wrapping at the column."""
    source = (
        "- First item has two sentences. The second one is here.\n"
        "  - Nested item. Also two sentences in it for wrapping.\n"
        "- Second item\n"
        "\n"
        "1. Ordered one. Ordered two.\n"
        "2. Next\n"
        "\n"
        "> Quoted text. Another quoted sentence that is somewhat long.\n"
    )
    result = run(["git-filter", "clean", "--stdin-filename", "lists.qmd"], input=source)
    assert result.stdout.decode() == (
        "- First item has two sentences.\n"
        "  The second one is here.\n"
        "  - Nested item.\n"
        "    Also two sentences in it for wrapping.\n"
        "- Second item\n"
        "\n"
        "1. Ordered one.\n"
        "   Ordered two.\n"
        "2. Next\n"
        "\n"
        "> Quoted text.\n"
        "> Another quoted sentence that is somewhat long.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "lists.qmd", "--markdown-wrap-at-column", "30"],
                 input=result.stdout)
    assert result.stdout.decode() == (
        "- First item has two\n"
        "  sentences. The second one is\n"
        "  here.\n"
        "  - Nested item. Also two\n"
        "    sentences in it for\n"
        "    wrapping.\n"
        "- Second item\n"
        "\n"
        "1. Ordered one. Ordered two.\n"
        "2. Next\n"
        "\n"
        "> Quoted text. Another quoted\n"
        "> sentence that is somewhat\n"
        "> long.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0


def test_filters_keep_code_and_format_yaml_fences(run):
    """CATCHES: filters that sentence-split or rewrap text inside code fences (```text or ~~~), or that leave
    embedded ```yaml fences unformatted (`key:   value` must become `key: value`)."""
    source = (
        "Text before. More text.\n"
        "\n"
        "```text\n"
        "Keep   this.   Exactly as is.\n"
        "```\n"
        "\n"
        "```yaml\n"
        "key:   value\n"
        "list: [1,   2]\n"
        "```\n"
        "\n"
        "~~~\n"
        "Tilde fence. Untouched.\n"
        "~~~\n"
    )
    fences = (
        "\n"
        "```text\n"
        "Keep   this.   Exactly as is.\n"
        "```\n"
        "\n"
        "```yaml\n"
        "key: value\n"
        "list: [1, 2]\n"
        "```\n"
        "\n"
        "~~~\n"
        "Tilde fence. Untouched.\n"
        "~~~\n"
    )
    result = run(["git-filter", "clean", "--stdin-filename", "fences.Rmd"], input=source)
    assert result.stdout.decode() == "Text before.\nMore text.\n" + fences
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "fences.Rmd"], input=source)
    assert result.stdout.decode() == "Text before. More text.\n" + fences
    assert result.stderr == b""
    assert result.returncode == 0


def test_filters_keep_crlf_line_endings(run):
    """CATCHES: filters that emit LF for inserted or rewrapped line breaks (or for every line) when the input
    uses CRLF, or that leave a stray CR inside a joined paragraph."""
    result = run(["git-filter", "clean", "--stdin-filename", "crlf.md"],
                 input=b"# Title\r\n\r\nOne sentence here. Two sentences here.\r\n\r\n- Item one. Item two.\r\n")
    assert result.stdout == (
        b"# Title\r\n\r\nOne sentence here.\r\nTwo sentences here.\r\n\r\n- Item one.\r\n  Item two.\r\n")
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "crlf.md", "--markdown-wrap-at-column", "24"],
                 input=b"One sentence here.\r\nTwo sentences here.\r\nThree more words.\r\n")
    assert result.stdout == b"One sentence here. Two\r\nsentences here. Three\r\nmore words.\r\n"
    assert result.stderr == b""
    assert result.returncode == 0


LONG_PARAGRAPH = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et "
    "dolore magna aliqua.\nUt enim ad minim veniam, quis nostrud exercitation ullamco laboris.\n"
)


def test_smudge_wraps_at_column_72_by_default(run):
    """CATCHES: a smudge filter whose default --markdown-wrap-at-column is not 72, or that keeps the stored
    sentence-per-line breaks instead of refilling the paragraph."""
    result = run(["git-filter", "smudge", "--stdin-filename", "long.md"], input=LONG_PARAGRAPH)
    assert result.stdout.decode() == (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod\n"
        "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim\n"
        "veniam, quis nostrud exercitation ullamco laboris.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0


@pytest.mark.parametrize(
    "args",
    [
        ["clean", "--stdin-filename", "config/notes.yaml"],
        ["smudge", "--stdin-filename", "page.markdown", "--markdown-wrap-at-column", "40"],
    ],
    ids=["yaml", "markdown-extension"],
)
def test_filters_reject_non_markdown_paths(run, args):
    """CATCHES: a filter that formats YAML files (supported by `format` but not the Git filter), treats a
    `.markdown` name as Markdown, or passes stdin through instead of failing with
    `<path>:1:1: error: unsupported Git filter path` and exit status 1."""
    result = run(["git-filter", *args], input="One. Two sentences here.\n")
    assert result.stdout == b""
    assert result.stderr.decode() == f"{args[2]}:1:1: error: unsupported Git filter path\n"
    assert result.returncode == 1


def test_filters_match_markdown_extensions_case_insensitively(run):
    """CATCHES: a filter that compares extensions case-sensitively and rejects upper-case `.MD` or `.QMD`
    names, which the documented ASCII case-insensitive extension matching accepts."""
    result = run(["git-filter", "clean", "--stdin-filename", "NOTES.MD"], input="Alpha beta. Gamma delta.\n")
    assert result.stdout == b"Alpha beta.\nGamma delta.\n"
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "Report.QMD", "--markdown-wrap-at-column", "30"],
                 input="Alpha beta.\nGamma delta.\n")
    assert result.stdout == b"Alpha beta. Gamma delta.\n"
    assert result.stderr == b""
    assert result.returncode == 0


def test_clean_rejects_invalid_utf8_input(run):
    """CATCHES: a clean filter that lossily decodes invalid UTF-8 (writing U+FFFD into the index) or copies
    the bytes through, instead of failing with a path-prefixed invalid UTF-8 error."""
    result = run(["git-filter", "clean", "--stdin-filename", "docs/latin1.md"], input=b"Caf\xe9 au lait. Second.\n")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "docs/latin1.md:1:1: error: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 3\n")
    assert result.returncode == 1


def test_filters_honour_skip_file_and_scoped_wrap_directives(run):
    """CATCHES: a filter that ignores `<!-- fmt: skip file -->` (the documented per-file opt-out while still
    passing through the filter) or `<!-- fmt: wrap=none scope=next -->`, or that applies the scoped
    directive beyond the next paragraph."""
    skipped = "<!-- fmt: skip file -->\nKeep  this. Exactly   as is.\n\n|  a  | b |\n|---|---|\n"
    result = run(["git-filter", "clean", "--stdin-filename", "skip.md"], input=skipped)
    assert result.stdout.decode() == skipped
    assert result.stderr == b""
    assert result.returncode == 0

    scoped = (
        "<!-- fmt: wrap=none scope=next -->\n"
        "First one here. Second one here and it is a much longer sentence.\n"
        "\n"
        "Third one here. Fourth one here and it is also a longer sentence.\n"
    )
    result = run(["git-filter", "clean", "--stdin-filename", "scoped.md"], input=scoped)
    assert result.stdout.decode() == (
        "<!-- fmt: wrap=none scope=next -->\n"
        "First one here. Second one here and it is a much longer sentence.\n"
        "\n"
        "Third one here.\n"
        "Fourth one here and it is also a longer sentence.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "smudge", "--stdin-filename", "scoped.md", "--markdown-wrap-at-column", "30"],
                 input=scoped)
    assert result.stdout.decode() == (
        "<!-- fmt: wrap=none scope=next -->\n"
        "First one here. Second one here and it is a much longer sentence.\n"
        "\n"
        "Third one here. Fourth one\n"
        "here and it is also a longer\n"
        "sentence.\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0


def test_clean_discovers_config_beside_stdin_filename(run, workdir):
    """CATCHES: a filter that ignores the `yamark.toml` found beside --stdin-filename (here a `***` rule
    marker and preserved table widths in docs/) or that applies it to files outside that directory."""
    write_tree(workdir, {"docs/yamark.toml": '[format]\nmarkdown_horizontal_rule = "***"\ntable_widths = "preserve"\n'})
    source = "Alpha. Beta.\n\n- - -\n\n|  a   | b |\n|------|---|\n| 1 | 2 |\n"
    result = run(["git-filter", "clean", "--stdin-filename", "docs/page.md"], input=source)
    assert result.stdout.decode() == "Alpha.\nBeta.\n\n***\n\n| a    | b |\n|------|---|\n| 1 | 2 |\n"
    assert result.stderr == b""
    assert result.returncode == 0

    result = run(["git-filter", "clean", "--stdin-filename", "page.md"], input=source)
    assert result.stdout.decode() == "Alpha.\nBeta.\n\n---\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert result.stderr == b""
    assert result.returncode == 0


# ------------------------------------------------------------------------------------------- setup
def test_setup_configures_driver_and_local_attributes(yamark, genv, workdir):
    """CATCHES: a setup that writes patterns to the shared .gitattributes instead of .git/info/attributes,
    forgets filter.yamark-md.required or merge.renormalize, uses another pattern list than *.md, *.qmd,
    *.Rmd and *.rmd, renormalizes tracked files itself, or stores clean/smudge commands that fail when Git
    runs them on `git add` and checkout."""
    make_repo(genv, workdir, {"guide.md": LONG_PARAGRAPH, "notes.txt": "Plain. Text.\n"})
    result = yamark("git-filter", "setup", "--yamark", "yamark", "--markdown-wrap-at-column", "40")
    assert norm(result.stdout, workdir) == setup_summary(4, width=40)
    assert result.stderr == b""
    assert result.returncode == 0
    assert filter_config(genv, workdir) == expected_config(40)
    assert (workdir / ".git/info/attributes").read_text() == DEFAULT_PATTERNS
    assert worktree(workdir) == as_bytes({"guide.md": LONG_PARAGRAPH, "notes.txt": "Plain. Text.\n"})
    assert blob(genv, workdir, ":guide.md") == LONG_PARAGRAPH.encode()

    (workdir / "guide.md").write_text(
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Ut enim ad minim veniam, quis nostrud.\n")
    git(genv, workdir, "add", "guide.md")
    assert blob(genv, workdir, ":guide.md") == (
        b"Lorem ipsum dolor sit amet, consectetur adipiscing elit.\nUt enim ad minim veniam, quis nostrud.\n")
    (workdir / "guide.md").unlink()
    git(genv, workdir, "checkout", "--", "guide.md")
    assert (workdir / "guide.md").read_bytes() == (
        b"Lorem ipsum dolor sit amet, consectetur\nadipiscing elit. Ut enim ad minim\nveniam, quis nostrud.\n")
    assert status(genv, workdir) == "M  guide.md\n"


def test_setup_with_paths_writes_repository_relative_patterns(yamark, genv, workdir):
    """CATCHES: a setup that writes the paths as typed (relative to the caller or absolute) instead of
    repository-relative patterns, or that resolves PATHS against --repo rather than the current directory."""
    repo = workdir / "repo"
    make_repo(genv, repo, {"docs/a.md": WRAPPED, "b.qmd": WRAPPED, "c.Rmd": WRAPPED})
    result = yamark("git-filter", "setup", "--repo", "repo", "--yamark", "yamark",
                    "repo/docs/a.md", "repo/./b.qmd", str(repo / "c.Rmd"))
    assert norm(result.stdout, repo) == setup_summary(3)
    assert result.stderr == b""
    assert result.returncode == 0
    assert (repo / ".git/info/attributes").read_text() == (
        "docs/a.md filter=yamark-md\nb.qmd filter=yamark-md\nc.Rmd filter=yamark-md\n")
    assert filter_config(genv, repo) == expected_config(72)


def test_setup_appends_only_missing_patterns(yamark, genv, workdir):
    """CATCHES: a setup that duplicates patterns already present, overwrites user lines, or glues the first
    new pattern onto an existing last line that lacks a trailing newline; a rerun must add nothing."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    attributes = workdir / ".git/info/attributes"
    attributes.write_bytes(b"*.qmd filter=yamark-md\n*.txt text")
    result = yamark("git-filter", "setup", "--yamark", "yamark")
    assert norm(result.stdout, workdir) == setup_summary(3)
    assert result.stderr == b""
    assert result.returncode == 0
    assert attributes.read_bytes() == (
        b"*.qmd filter=yamark-md\n*.txt text\n*.md filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n")

    result = yamark("git-filter", "setup", "--yamark", "yamark")
    assert norm(result.stdout, workdir) == setup_summary(0)
    assert result.stderr == b""
    assert result.returncode == 0
    assert attributes.read_bytes() == (
        b"*.qmd filter=yamark-md\n*.txt text\n*.md filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n")
    assert filter_config(genv, workdir) == expected_config(72)


def test_setup_shell_quotes_the_yamark_path(yamark, genv, workdir):
    """CATCHES: a setup that quotes executable paths made only of letters, digits, `/`, `.`, `_`, `-` and
    `+`, or that stores a path containing spaces or quotes unquoted (so Git's shell splits it) or quoted
    incorrectly; Git must be able to run the stored clean command."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    result = yamark("git-filter", "setup", "--yamark", "/opt/tools-1.0/ya_mark+x")
    assert norm(result.stdout, workdir) == setup_summary(4)
    assert result.stderr == b""
    assert result.returncode == 0
    assert filter_config(genv, workdir) == expected_config(72, "/opt/tools-1.0/ya_mark+x")

    tool = workdir.parent / "tool dir" / "ya'mark"
    tool.parent.mkdir()
    tool.symlink_to(EXECUTABLE)
    result = yamark("git-filter", "setup", "--yamark", str(tool), "--markdown-wrap-at-column", "50")
    assert norm(result.stdout, workdir) == setup_summary(0, width=50)
    assert result.stderr == b""
    assert result.returncode == 0
    quoted = "'" + str(tool).replace("'", "'\\''") + "'"
    assert filter_config(genv, workdir) == expected_config(50, quoted)
    git(genv, workdir, "add", "--renormalize", ".")
    assert blob(genv, workdir, ":post.md") == CANONICAL.encode()


@pytest.mark.parametrize(
    "path, message",
    [
        ("repo/notes.txt", "repo/notes.txt: unsupported Git filter path"),
        ("outside.md", "outside.md: path is outside {repo}"),
        ("repo/with space.md", "with space.md: path contains whitespace; add this Git attribute manually"),
    ],
    ids=["unsupported", "outside", "whitespace"],
)
def test_setup_rejects_unusable_paths(yamark, genv, workdir, path, message):
    """CATCHES: a setup that accepts non-Markdown, out-of-repository, or whitespace-containing paths
    (which cannot be written as one attribute pattern) instead of failing without touching info/attributes;
    the driver config is already written when the path is rejected."""
    repo = workdir / "repo"
    make_repo(genv, repo, {"notes.txt": "Notes.\n", "with space.md": WRAPPED})
    write_tree(workdir, {"outside.md": WRAPPED})
    attributes_before = read_tree(repo / ".git/info")
    result = yamark("git-filter", "setup", "--repo", "repo", "--yamark", "yamark", path)
    assert result.stdout == b""
    assert norm(result.stderr, repo) == f"error: {message}\n"
    assert result.returncode == 1
    assert read_tree(repo / ".git/info") == attributes_before
    assert filter_config(genv, repo) == expected_config(72)


def test_setup_rejects_non_utf8_markdown_path(yamark, genv, workdir):
    """CATCHES: a setup that writes a lossily decoded pattern for a filename whose bytes are not UTF-8
    instead of refusing with a `path is not valid UTF-8` error."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    name = os.fsdecode(b"caf\xe9.md")
    (workdir / name).write_text(WRAPPED)
    result = yamark("git-filter", "setup", "--yamark", "yamark", name)
    assert result.stdout == b""
    assert result.stderr.decode() == "error: caf�.md: path is not valid UTF-8\n"
    assert result.returncode == 1
    assert filter_config(genv, workdir) == expected_config(72)
    assert (workdir / ".git/info/attributes").exists() is False


def test_setup_rejects_the_repository_root_as_a_path(yamark, genv, workdir):
    """CATCHES: a setup that writes an empty attribute pattern when the path given resolves to the repository
    root itself (here a repository directory named `notes.md`)."""
    repo = workdir / "notes.md"
    make_repo(genv, repo, {"post.md": WRAPPED})
    result = yamark("git-filter", "setup", "--repo", "notes.md", "--yamark", "yamark", "notes.md")
    assert result.stdout == b""
    assert result.stderr.decode() == "error: cannot configure a Git filter for the repository root\n"
    assert result.returncode == 1
    assert filter_config(genv, repo) == expected_config(72)


def test_setup_in_linked_worktree_uses_common_info_attributes(yamark, genv, workdir):
    """CATCHES: a setup that writes `<worktree>/.git/info/attributes` (where `.git` is a file in a linked
    worktree) instead of the attributes path Git reports for the shared repository."""
    main = workdir / "main"
    make_repo(genv, main, {"post.md": WRAPPED})
    git(genv, main, "worktree", "add", "-q", "../linked")
    linked = workdir / "linked"
    result = yamark("git-filter", "setup", "--yamark", "yamark", cwd=linked)
    expected = setup_summary(4, attributes=f"{main.resolve()}/.git/info/attributes", root=str(linked.resolve()))
    assert result.stdout.decode() == expected
    assert result.stderr == b""
    assert result.returncode == 0
    assert (main / ".git/info/attributes").read_text() == DEFAULT_PATTERNS
    assert (linked / ".git").is_file() is True


def test_setup_reports_locked_git_config(yamark, genv, workdir):
    """CATCHES: a setup that ignores a failing `git config` write (here a stale .git/config.lock) and reports
    success, instead of printing Git's error and exiting 1."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    (workdir / ".git/config.lock").write_text("")
    result = yamark("git-filter", "setup", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == CONFIG_LOCKED
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""


@pytest.mark.parametrize(
    "args, config",
    [
        (["setup", "--yamark", "yamark"], expected_config(72)),
        (["adopt", "--yamark", "yamark"], ""),
        (["teardown"], ""),
    ],
    ids=["setup", "adopt", "teardown"],
)
def test_commands_report_non_utf8_info_attributes(yamark, genv, workdir, args, config):
    """CATCHES: setup, adopt, or teardown that silently replaces, ignores, or lossily rewrites a
    .git/info/attributes file that is not valid UTF-8, instead of reporting its path and leaving it intact
    (setup has already written the driver config at that point)."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    attributes = workdir / ".git/info/attributes"
    attributes.write_bytes(b"*.md filter=yamark-md\n*.txt text # caf\xe9\n")
    result = yamark("git-filter", *args)
    assert result.stdout == b""
    assert norm(result.stderr, workdir) == (
        "error: {repo}/.git/info/attributes: failed to read attributes: stream did not contain valid UTF-8\n")
    assert result.returncode == 1
    assert attributes.read_bytes() == b"*.md filter=yamark-md\n*.txt text # caf\xe9\n"
    assert filter_config(genv, workdir) == config
    assert worktree(workdir) == as_bytes({"post.md": WRAPPED})


# ---------------------------------------------------------------------------------------- teardown
def test_teardown_removes_setup_lines_and_config(yamark, genv, workdir):
    """CATCHES: a teardown that removes lines with extra attributes or commented-out filter lines (only bare
    `<pattern> filter=yamark-md` lines are setup lines), keeps a driver value, unsets unrelated filters, or
    counts keys instead of values (a second clean command is one more value)."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    result = yamark("git-filter", "setup", "--yamark", "yamark", "--markdown-wrap-at-column", "50")
    assert result.returncode == 0
    git(genv, workdir, "config", "--add", "filter.yamark-md.clean", "second value")
    git(genv, workdir, "config", "filter.other.clean", "cat")
    attributes = workdir / ".git/info/attributes"
    attributes.write_text(
        "*.txt text\n"
        "# docs/*.md filter=yamark-md\n"
        + DEFAULT_PATTERNS
        + "NEWS.md filter=yamark-md diff=markdown\n"
        "   notes/*.md   filter=yamark-md   \n"
        "*.md\n"
    )
    result = yamark("git-filter", "teardown")
    assert norm(result.stdout, workdir) == teardown_summary(5, 5)
    assert result.stderr == b""
    assert result.returncode == 0
    assert attributes.read_text() == (
        "*.txt text\n"
        "# docs/*.md filter=yamark-md\n"
        "NEWS.md filter=yamark-md diff=markdown\n"
        "*.md\n"
    )
    assert filter_config(genv, workdir) == ""
    assert git(genv, workdir, "config", "--get", "filter.other.clean") == b"cat\n"


def test_teardown_rewrites_local_attributes_only_when_patterns_exist(yamark, genv, workdir):
    """CATCHES: a teardown that fails or creates an empty .git/info/attributes when nothing is configured,
    rewrites a file without setup lines, appends a final newline the file never had, or leaves an empty
    line where the removed last pattern used to be."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    shutil.rmtree(workdir / ".git/info", ignore_errors=True)
    result = yamark("git-filter", "teardown")
    assert norm(result.stdout, workdir) == teardown_summary(0, 0)
    assert result.stderr == b""
    assert result.returncode == 0
    assert (workdir / ".git/info").exists() is False

    attributes = workdir / ".git/info/attributes"
    attributes.parent.mkdir()
    attributes.write_bytes(b"*.md diff=markdown")
    result = yamark("git-filter", "teardown")
    assert norm(result.stdout, workdir) == teardown_summary(0, 0)
    assert result.stderr == b""
    assert result.returncode == 0
    assert attributes.read_bytes() == b"*.md diff=markdown"

    attributes.write_bytes(b"*.qmd filter=yamark-md\nx.txt text\n*.md filter=yamark-md")
    result = yamark("git-filter", "teardown")
    assert norm(result.stdout, workdir) == teardown_summary(0, 2)
    assert result.stderr == b""
    assert result.returncode == 0
    assert attributes.read_bytes() == b"x.txt text"


def test_teardown_keeps_shared_gitattributes(yamark, genv, workdir):
    """CATCHES: a teardown that also strips committed `filter=yamark-md` rules from .gitattributes, which
    the documentation says must be edited directly."""
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})
    git(genv, workdir, "config", "filter.yamark-md.required", "true")
    result = yamark("git-filter", "teardown", "--repo", ".")
    assert norm(result.stdout, workdir) == teardown_summary(1, 0)
    assert result.stderr == b""
    assert result.returncode == 0
    assert worktree(workdir) == as_bytes({".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})
    assert status(genv, workdir) == ""


def test_teardown_reports_locked_git_config(yamark, genv, workdir):
    """CATCHES: a teardown that reports success when `git config --unset-all` fails (stale config lock),
    or that removes attribute lines before the config is unset."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    git(genv, workdir, "config", "filter.yamark-md.clean", "yamark git-filter clean --stdin-filename %f")
    (workdir / ".git/info/attributes").write_text(DEFAULT_PATTERNS)
    (workdir / ".git/config.lock").write_text("")
    result = yamark("git-filter", "teardown")
    assert result.stdout == b""
    assert result.stderr.decode() == CONFIG_LOCKED
    assert result.returncode == 1
    assert (workdir / ".git/info/attributes").read_text() == DEFAULT_PATTERNS


# ------------------------------------------------------------------------------------------- adopt
@pytest.mark.parametrize(
    "config, attributes, source",
    [
        ((("core.autocrlf", "true"),), "*.md text\n", "First sentence. Second sentence?\r\n"),
        ((), "*.md text eol=crlf\n", "First sentence. Second sentence?\r\n"),
    ],
    ids=["autocrlf", "eol-crlf"],
)
def test_adopt_normalizes_index_and_keeps_checkout_line_endings(yamark, genv, workdir, config, attributes, source):
    """CATCHES: an adopt that writes formatted blob bytes straight into the working tree (losing the CRLF
    line endings that core.autocrlf or eol=crlf require), stores CRLF blobs in the index, or leaves the
    working tree dirty after staging .gitattributes and the normalized Markdown."""
    make_repo(genv, workdir, {".gitattributes": attributes, "post.md": source}, config)
    result = yamark("git-filter", "adopt", "--yamark", "yamark", "--markdown-wrap-at-column", "32")
    assert norm(result.stdout, workdir) == adopt_summary(4, 1)
    assert result.stderr == b""
    assert result.returncode == 0
    assert status(genv, workdir) == "M  .gitattributes\nM  post.md\n"
    assert blob(genv, workdir, ":.gitattributes") == (attributes + DEFAULT_PATTERNS).encode()
    assert blob(genv, workdir, ":post.md") == CANONICAL.encode()
    assert worktree(workdir) == as_bytes({".gitattributes": attributes + DEFAULT_PATTERNS, "post.md": source})
    assert filter_config(genv, workdir) == expected_config(32)


def test_adopt_handles_quoted_and_delimiter_filenames(yamark, genv, workdir):
    """CATCHES: an adopt that parses Git's quoted, line-oriented path output (breaking on non-ASCII names,
    spaces, tabs, newlines, quotes, or backslashes) instead of NUL-separated native names, or that touches
    tracked non-Markdown files."""
    names = ["café.md", "with space.md", "line\nbreak.md", "tab\tname.md", 'quote"name.md', "back\\slash.md"]
    files = {name: WRAPPED for name in names}
    make_repo(genv, workdir, {**files, "notes.txt": "Plain. Text.\n"}, (("core.quotePath", "true"),))
    result = yamark("git-filter", "adopt", "--yamark", "yamark", "--markdown-wrap-at-column", "32")
    assert norm(result.stdout, workdir) == adopt_summary(4, 6)
    assert result.stderr == b""
    assert result.returncode == 0
    assert [blob(genv, workdir, f":{name}") for name in names] == [CANONICAL.encode()] * 6
    assert blob(genv, workdir, ":notes.txt") == b"Plain. Text.\n"
    assert worktree(workdir) == as_bytes({**files, "notes.txt": "Plain. Text.\n", ".gitattributes": DEFAULT_PATTERNS})
    assert git(genv, workdir, "diff", "--name-only", "-z") == b""


def test_native_filenames_survive_adopt_check_teardown_and_join(yamark, genv, workdir):
    """CATCHES: lifecycle commands that decode filenames as UTF-8 or parse Git's quoted (core.quotePath=true)
    output, so a Markdown file named with byte 0xFF is skipped, misnamed, or corrupted, or a binary file with
    a non-UTF-8 name is modified during adopt, check, teardown, or join."""
    markdown = ["regular.md", os.fsdecode(b"post-\xff.md")]
    binary_name = os.fsdecode(b"unrelated-\xfe.bin")
    binary = b"\0\xff\n\x80\r"
    init_repo(genv, workdir, (("core.quotePath", "true"),))
    for name in markdown:
        (workdir / name).write_text(WRAPPED)
    (workdir / binary_name).write_bytes(binary)
    git(genv, workdir, "add", ".")
    git(genv, workdir, "commit", "-q", "-m", "fixture")

    def files(worktree_text):
        return {
            "index": [blob(genv, workdir, f":{name}") for name in [*markdown, binary_name]],
            "worktree": [(workdir / name).read_bytes() for name in [*markdown, binary_name]],
            "expected": [CANONICAL.encode(), CANONICAL.encode(), binary, worktree_text, worktree_text, binary],
        }

    result = yamark("git-filter", "adopt", "--yamark", "yamark", "--markdown-wrap-at-column", "32")
    assert (norm(result.stdout, workdir), result.stderr, result.returncode) == (adopt_summary(4, 2), b"", 0)
    state = files(WRAPPED.encode())
    assert state["index"] + state["worktree"] == state["expected"]
    git(genv, workdir, "commit", "-q", "-m", "adopt")

    result = yamark("git-filter", "check", "--markdown-wrap-at-column", "32")
    assert (result.stdout, result.stderr, result.returncode) == (
        b"yamark Git filter check passed for 2 Markdown file(s).\n", b"", 0)

    result = yamark("git-filter", "teardown")
    assert (norm(result.stdout, workdir), result.stderr, result.returncode) == (teardown_summary(4, 0), b"", 0)
    for name in markdown:
        (workdir / name).unlink()
    git(genv, workdir, "checkout-index", "--force", "--all")
    state = files(CANONICAL.encode())
    assert state["index"] + state["worktree"] == state["expected"]
    assert status(genv, workdir) == ""

    result = yamark("git-filter", "join", "--yamark", "yamark", "--markdown-wrap-at-column", "32")
    assert (norm(result.stdout, workdir), result.stderr, result.returncode) == (join_summary(2), b"", 0)
    state = files(WRAPPED.encode())
    assert state["index"] + state["worktree"] == state["expected"]
    assert status(genv, workdir) == ""


def test_adopt_with_paths_filters_only_those_files(yamark, genv, workdir):
    """CATCHES: an adopt that ignores PATHS and installs the default patterns, or that renormalizes Markdown
    files outside the selected paths."""
    make_repo(genv, workdir, {"docs/post.md": WRAPPED, "other.md": WRAPPED})
    result = yamark("git-filter", "adopt", "--yamark", "yamark", "--markdown-wrap-at-column", "32", "docs/post.md")
    assert norm(result.stdout, workdir) == adopt_summary(1, 1)
    assert result.stderr == b""
    assert result.returncode == 0
    assert status(genv, workdir) == "A  .gitattributes\nM  docs/post.md\n"
    assert blob(genv, workdir, ":docs/post.md") == CANONICAL.encode()
    assert blob(genv, workdir, ":other.md") == WRAPPED.encode()
    assert worktree(workdir) == as_bytes({
        ".gitattributes": "docs/post.md filter=yamark-md\n", "docs/post.md": WRAPPED, "other.md": WRAPPED})


def test_adopt_respects_existing_attribute_rules(yamark, genv, workdir):
    """CATCHES: an adopt that re-adds patterns already present, normalizes a file excluded by a later
    `NEWS.md -filter` rule, or selects files by extension alone (README.MD does not match the
    case-sensitive `*.md` attribute pattern)."""
    attributes = "*.md filter=yamark-md\nNEWS.md -filter\n"
    files = {".gitattributes": attributes, "post.md": WRAPPED, "NEWS.md": WRAPPED, "README.MD": WRAPPED,
             "guide.qmd": WRAPPED}
    make_repo(genv, workdir, files)
    result = yamark("git-filter", "adopt", "--yamark", "yamark", "--markdown-wrap-at-column", "32")
    assert norm(result.stdout, workdir) == adopt_summary(3, 2)
    assert result.stderr == b""
    assert result.returncode == 0
    assert status(genv, workdir) == "M  .gitattributes\nM  guide.qmd\nM  post.md\n"
    new_attributes = attributes + "*.qmd filter=yamark-md\n*.Rmd filter=yamark-md\n*.rmd filter=yamark-md\n"
    assert worktree(workdir) == as_bytes({**files, ".gitattributes": new_attributes})
    assert [blob(genv, workdir, f":{name}") for name in ["post.md", "guide.qmd", "NEWS.md", "README.MD"]] == [
        CANONICAL.encode(), CANONICAL.encode(), WRAPPED.encode(), WRAPPED.encode()]


def test_adopt_refuses_dirty_worktree(yamark, genv, workdir):
    """CATCHES: an adopt that proceeds over uncommitted edits or untracked files (which renormalization
    would mix into the adoption commit) instead of refusing and listing `git status --porcelain`."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    write_tree(workdir, {"post.md": "Edited sentence. Another.\n", "new.md": "Draft.\n"})
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: working tree is not clean; commit or stash changes first\n M post.md\n?? new.md\n\n")
    assert result.returncode == 1
    assert worktree(workdir) == as_bytes({"post.md": "Edited sentence. Another.\n", "new.md": "Draft.\n"})
    assert filter_config(genv, workdir) == ""


def test_adopt_refuses_existing_local_config(yamark, genv, workdir):
    """CATCHES: an adopt that silently overwrites an existing local merge.renormalize setting (here `false`)
    instead of refusing and asking the user to run teardown first."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    git(genv, workdir, "config", "merge.renormalize", "false")
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: existing local Git filter config merge.renormalize is set; run yamark git-filter teardown first\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == "merge.renormalize false\n"
    assert worktree(workdir) == as_bytes({"post.md": WRAPPED})


def test_adopt_refuses_local_info_attributes(yamark, genv, workdir):
    """CATCHES: an adopt that ignores yamark patterns left in .git/info/attributes by a local setup, which
    would keep filtering after the shared rules change."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    (workdir / ".git/info/attributes").write_text("# local\n*.txt text\ndocs/*.md filter=yamark-md\n")
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert norm(result.stderr, workdir) == (
        "error: {repo}/.git/info/attributes already contains yamark filter attributes; "
        "run yamark git-filter teardown first\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert worktree(workdir) == as_bytes({"post.md": WRAPPED})


def test_adopt_without_tracked_markdown_rolls_back(yamark, genv, workdir):
    """CATCHES: an adopt that leaves the driver config or a modified .gitattributes behind when no tracked
    Markdown file matches (README.MD is not matched by `*.md`), instead of restoring the previous
    .gitattributes bytes, unsetting the config, and reporting the rollback."""
    files = {".gitattributes": "*.txt text\n", "notes.txt": "Plain. Text.\n", "README.MD": WRAPPED}
    make_repo(genv, workdir, files)
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: no tracked Markdown files match filter=yamark-md\nRolled back yamark Git filter adoption.\n")
    assert result.returncode == 1
    assert worktree(workdir) == as_bytes(files)
    assert filter_config(genv, workdir) == ""
    assert status(genv, workdir) == ""


def test_adopt_in_repository_without_commits_reports_failed_rollback(yamark, genv, workdir):
    """CATCHES: an adopt that hides rollback errors (here `git reset` and `git checkout` fail because there
    is no HEAD) instead of reporting each failure and asking the user to review the repository, while still
    removing the created .gitattributes and config."""
    init_repo(genv, workdir)
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: no tracked Markdown files match filter=yamark-md\n"
        "Rollback failed: git failed: fatal: ambiguous argument 'HEAD': unknown revision or path not in the "
        "working tree.\n"
        "Use '--' to separate paths from revisions, like this:\n"
        "'git <command> [<revision>...] -- [<file>...]'\n"
        "git failed: error: pathspec '.' did not match any file(s) known to git\n"
        "Review the repository before continuing.\n"
    )
    assert result.returncode == 1
    assert worktree(workdir) == {}
    assert filter_config(genv, workdir) == ""


def test_adopt_roundtrip_failure_rolls_back(yamark, genv, workdir):
    """CATCHES: an adopt that stages normalized blobs without verifying clean(smudge(blob)) == blob; a
    non-idempotent embedded formatter must make adoption fail, unstage everything, and remove the new
    .gitattributes and driver config."""
    files = {
        "yamark.toml": (
            '[embedded.python]\nformatter = { command = ["python3", "grow", "{path}"], path_suffix = ".py" }\n'),
        "grow": 'import sys\nsys.stdout.write(sys.stdin.read() + "# again\\n")\n',
        "post.md": "Intro. Text.\n\n```python\nx = 1\n```\n",
    }
    make_repo(genv, workdir, files)
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == f"error: post.md{ROUNDTRIP_FAILURE}\nRolled back yamark Git filter adoption.\n"
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert git(genv, workdir, "diff", "--cached", "--name-only") == b""
    # The rollback checkout runs while the filter is still configured, so the file is re-smudged once.
    assert worktree(workdir) == as_bytes({**files, "post.md": "Intro. Text.\n\n```python\nx = 1\n# again\n```\n"})


def test_adopt_rolls_back_when_smudged_checkout_is_dirty(yamark, genv, tmp_path, workdir):
    """CATCHES: an adopt that only verifies the codec in-process and does not check `git diff` after writing
    the smudged checkout; a smudge command that adds text must make adoption fail and roll back."""
    wrapper = tmp_path / "bin" / "yamark-wrap"
    wrapper.write_text('#!/bin/sh\nif [ "$2" = smudge ]; then yamark "$@"; printf "\\nWorking tree only.\\n"; '
                       'else exec yamark "$@"; fi\n')
    wrapper.chmod(0o755)
    make_repo(genv, workdir, {"post.md": "Intro. Text.\n"})
    result = yamark("git-filter", "adopt", "--yamark", "yamark-wrap")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: checkout form is not clean after smudge\nunstaged files:\npost.md\n\n"
        "Rolled back yamark Git filter adoption.\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert git(genv, workdir, "diff", "--cached", "--name-only") == b""
    assert worktree(workdir) == as_bytes({"post.md": "Intro. Text.\n\nWorking tree only.\n"})


def test_adopt_rejects_non_utf8_gitattributes(yamark, genv, workdir):
    """CATCHES: an adopt that rewrites a .gitattributes file it cannot read as UTF-8 (losing bytes) instead
    of failing before any change."""
    make_repo(genv, workdir, {".gitattributes": b"*.md text # caf\xe9\n", "post.md": WRAPPED})
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert norm(result.stderr, workdir) == (
        "error: {repo}/.gitattributes: failed to read file: stream did not contain valid UTF-8\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert worktree(workdir) == as_bytes({".gitattributes": b"*.md text # caf\xe9\n", "post.md": WRAPPED})


def test_adopt_rolls_back_when_gitattributes_is_ignored(yamark, genv, workdir):
    """CATCHES: an adopt that force-adds an ignored .gitattributes or keeps going after `git add` fails,
    instead of reporting Git's error, deleting the .gitattributes it created, and unsetting the config."""
    files = {".gitignore": ".gitattributes\n", "post.md": WRAPPED}
    make_repo(genv, workdir, files)
    result = yamark("git-filter", "adopt", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: git failed: The following paths are ignored by one of your .gitignore files:\n"
        ".gitattributes\n"
        "hint: Use -f if you really want to add them.\n"
        "hint: Turn this message off by running\n"
        'hint: "git config advice.addIgnoredFile false"\n'
        "Rolled back yamark Git filter adoption.\n"
    )
    assert result.returncode == 1
    assert worktree(workdir) == as_bytes(files)
    assert filter_config(genv, workdir) == ""
    assert status(genv, workdir) == ""


def test_adopt_rejects_non_utf8_yamark_and_rolls_back(yamark, genv, workdir):
    """CATCHES: an adopt that stores a lossily decoded --yamark path, or that leaves .gitattributes or
    config behind after rejecting it instead of rolling back."""
    make_repo(genv, workdir, {"post.md": WRAPPED})
    result = yamark("git-filter", "adopt", "--yamark", os.fsdecode(b"bin/ya\xffmark"))
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: bin/ya�mark: path is not valid UTF-8\nRolled back yamark Git filter adoption.\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert worktree(workdir) == as_bytes({"post.md": WRAPPED})
    assert status(genv, workdir) == ""


def test_adopt_defaults_to_running_executable_with_repo_option(run, genv, workdir):
    """CATCHES: an adopt without --yamark that stores a command Git cannot run (e.g. a bare `yamark`, which
    is not on PATH here) or ignores --repo/--markdown-wrap-at-column; the stored commands must normalize and
    smudge."""
    repo = workdir / "repo"
    make_repo(genv, repo, {"guide.md": LONG_PARAGRAPH})
    overrides = {key: genv[key] for key in ("GIT_CONFIG_NOSYSTEM", "GIT_CEILING_DIRECTORIES")}
    result = run(["git-filter", "adopt", "--repo", "repo", "--markdown-wrap-at-column", "40"], env_overrides=overrides)
    assert norm(result.stdout, repo) == adopt_summary(4, 1)
    assert result.stderr == b""
    assert result.returncode == 0
    assert blob(genv, repo, ":guide.md") == LONG_PARAGRAPH.encode()
    assert (repo / "guide.md").read_text() == (
        "Lorem ipsum dolor sit amet, consectetur\n"
        "adipiscing elit, sed do eiusmod tempor\n"
        "incididunt ut labore et dolore magna\n"
        "aliqua. Ut enim ad minim veniam, quis\n"
        "nostrud exercitation ullamco laboris.\n"
    )
    clean = git(genv, repo, "config", "--get", "filter.yamark-md.clean").decode()
    smudge = git(genv, repo, "config", "--get", "filter.yamark-md.smudge").decode()
    assert clean.endswith(" git-filter clean --stdin-filename %f\n")
    assert smudge == clean.replace(" git-filter clean --stdin-filename %f",
                                   " git-filter smudge --stdin-filename %f --markdown-wrap-at-column 40")
    assert status(genv, repo) == "A  .gitattributes\n"


# -------------------------------------------------------------------------------------------- join
@pytest.mark.parametrize(
    "config, attributes, committed, checkout",
    [
        ((("core.autocrlf", "true"),), "*.md filter=yamark-md\n", "First sentence.\r\nSecond sentence?\r\n",
         "First sentence. Second sentence?\r\n"),
        ((("core.autocrlf", "true"),), "*.md text eol=lf filter=yamark-md\n", CANONICAL, WRAPPED),
    ],
    ids=["autocrlf", "eol-lf-over-autocrlf"],
)
def test_join_writes_wrapped_checkout_and_stays_clean(yamark, genv, workdir, config, attributes, committed, checkout):
    """CATCHES: a join that does not install the driver, writes LF where core.autocrlf expects CRLF (or CRLF
    despite eol=lf), or leaves `git status --porcelain` dirty after rewriting the working tree."""
    make_repo(genv, workdir, {".gitattributes": attributes, "post.md": committed}, config)
    result = yamark("git-filter", "join", "--yamark", "yamark", "--markdown-wrap-at-column", "32")
    assert norm(result.stdout, workdir) == join_summary(1)
    assert result.stderr == b""
    assert result.returncode == 0
    assert status(genv, workdir) == ""
    assert worktree(workdir) == as_bytes({".gitattributes": attributes, "post.md": checkout})
    assert blob(genv, workdir, ":post.md") == CANONICAL.encode()
    assert filter_config(genv, workdir) == expected_config(32)


def test_join_refuses_when_behind_upstream_until_fast_forwarded(yamark, genv, workdir):
    """CATCHES: a join that runs on a branch behind its upstream (before the adoption commit arrives)
    instead of telling the user to `git pull --ff-only` first, or that keeps refusing once the branch has
    caught up with an upstream that is still configured."""
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})
    git(genv, workdir, "branch", "upstream")
    git(genv, workdir, "checkout", "-q", "upstream")
    write_tree(workdir, {"later.md": "Alpha beta.\nGamma delta.\n"})
    git(genv, workdir, "add", "later.md")
    git(genv, workdir, "commit", "-q", "-m", "later")
    git(genv, workdir, "checkout", "-q", "main")
    git(genv, workdir, "branch", "-q", "--set-upstream-to=upstream")
    result = yamark("git-filter", "join", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: branch is behind upstream. Run git pull --ff-only first, then run yamark git-filter join.\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert worktree(workdir) == as_bytes({".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})

    git(genv, workdir, "merge", "-q", "--ff-only", "upstream")
    result = yamark("git-filter", "join", "--yamark", "yamark", "--markdown-wrap-at-column", "50")
    assert norm(result.stdout, workdir) == join_summary(2)
    assert result.stderr == b""
    assert result.returncode == 0
    assert worktree(workdir) == as_bytes({".gitattributes": "*.md filter=yamark-md\n", "post.md": WRAPPED,
                                          "later.md": "Alpha beta. Gamma delta.\n"})
    assert status(genv, workdir) == ""
    assert filter_config(genv, workdir) == expected_config(50)


def test_join_requires_shared_yamark_attributes(yamark, genv, workdir):
    """CATCHES: a join that installs the driver in a repository that has not adopted the filter, or counts
    commented-out rules, other filters, or a bare `filter=yamark-md` token without a pattern as adoption."""
    attributes = "# *.md filter=yamark-md\n*.md filter=other\nfilter=yamark-md\n"
    make_repo(genv, workdir, {".gitattributes": attributes, "post.md": WRAPPED})
    result = yamark("git-filter", "join", "--yamark", "yamark")
    assert result.stdout == b""
    assert norm(result.stderr, workdir) == (
        "error: {repo}/.gitattributes does not contain filter=yamark-md; run yamark git-filter adopt in the "
        "maintainer checkout first\n")
    assert result.returncode == 1
    assert filter_config(genv, workdir) == ""
    assert worktree(workdir) == as_bytes({".gitattributes": attributes, "post.md": WRAPPED})


def test_check_and_join_require_matching_tracked_markdown(yamark, genv, workdir):
    """CATCHES: check or join reporting success when the shared rules select no tracked Markdown file
    (non-Markdown or untracked matches do not count), or a join that rolls back the driver config it has
    already written (join does not roll back)."""
    make_repo(genv, workdir, {".gitattributes": "*.qmd filter=yamark-md\n*.txt filter=yamark-md\n",
                              "post.md": WRAPPED, "notes.txt": WRAPPED})
    write_tree(workdir, {"draft.qmd": CANONICAL})
    result = yamark("git-filter", "check")
    assert result.stdout == b""
    assert result.stderr.decode() == "error: no tracked Markdown files match filter=yamark-md\n"
    assert result.returncode == 1

    (workdir / "draft.qmd").unlink()
    result = yamark("git-filter", "join", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == "error: no tracked Markdown files match filter=yamark-md\n"
    assert result.returncode == 1
    assert filter_config(genv, workdir) == expected_config(72)


def test_join_reports_noncanonical_committed_blob(yamark, genv, workdir):
    """CATCHES: a join that rewrites the working tree from committed blobs that are not in clean form,
    instead of failing the clean(smudge(blob)) == blob check before touching any file."""
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n", "ok.md": CANONICAL, "post.md": WRAPPED})
    result = yamark("git-filter", "join", "--yamark", "yamark")
    assert result.stdout == b""
    assert result.stderr.decode() == f"error: post.md{ROUNDTRIP_FAILURE}\n"
    assert result.returncode == 1
    assert filter_config(genv, workdir) == expected_config(72)
    assert worktree(workdir) == as_bytes({".gitattributes": "*.md filter=yamark-md\n", "ok.md": CANONICAL,
                                          "post.md": WRAPPED})


def test_join_reports_failing_smudge_command(yamark, genv, tmp_path, workdir):
    """CATCHES: a join that writes formatted bytes itself instead of checking out through Git's configured
    smudge command, or that ignores the failure of that command and reports success."""
    wrapper = tmp_path / "bin" / "yamark-broken"
    wrapper.write_text('#!/bin/sh\nif [ "$2" = smudge ]; then echo "smudge broke" >&2; exit 3; fi\nexec yamark "$@"\n')
    wrapper.chmod(0o755)
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})
    result = yamark("git-filter", "join", "--yamark", "yamark-broken")
    command = "yamark-broken git-filter smudge --stdin-filename %f --markdown-wrap-at-column 72"
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: git failed: smudge broke\n"
        f"error: external filter '{command}' failed 3\n"
        f"error: external filter '{command}' failed\n"
        "fatal: post.md: smudge filter yamark-md failed\n"
    )
    assert result.returncode == 1
    assert filter_config(genv, workdir) == expected_config(72, "yamark-broken")
    assert worktree(workdir) == as_bytes({".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})


# ------------------------------------------------------------------------------------------- check
def test_check_reads_committed_blobs_only(yamark, genv, workdir):
    """CATCHES: a check that validates the index or working tree instead of HEAD, or that needs a local
    filter driver; noncanonical staged and unstaged edits must not affect the result."""
    files = {".gitattributes": "*.md filter=yamark-md\n*.qmd filter=yamark-md\n", "a.md": CANONICAL,
             "docs/b.qmd": "Alpha beta.\nGamma delta.\n", "notes.txt": WRAPPED}
    make_repo(genv, workdir, files)
    write_tree(workdir, {"a.md": WRAPPED})
    git(genv, workdir, "add", "a.md")
    write_tree(workdir, {"docs/b.qmd": "Alpha beta. Gamma delta.\n"})
    result = yamark("git-filter", "check")
    assert result.stdout == b"yamark Git filter check passed for 2 Markdown file(s).\n"
    assert result.stderr == b""
    assert result.returncode == 0
    assert status(genv, workdir) == "M  a.md\n M docs/b.qmd\n"
    assert filter_config(genv, workdir) == ""


def test_check_lists_every_failing_file(yamark, genv, workdir):
    """CATCHES: a check that stops at the first failure or reports files in a different order; every
    noncanonical committed Markdown blob must be listed, one per line, after a single `error: ` prefix."""
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n", "a.md": WRAPPED, "b.md": CANONICAL,
                              "c/d.md": "One. Two.\n\n\n\nThree.\n", "z.txt": WRAPPED})
    result = yamark("git-filter", "check", "--markdown-wrap-at-column", "40")
    assert result.stdout == b""
    assert result.stderr.decode() == f"error: a.md{ROUNDTRIP_FAILURE}\nc/d.md{ROUNDTRIP_FAILURE}\n"
    assert result.returncode == 1


def test_check_discovers_config_beside_files_with_repo_option(yamark, genv, workdir):
    """CATCHES: a check that discovers yamark.toml relative to the caller's directory instead of beside each
    tracked file, so `***` rules configured in docs/yamark.toml would be reported as roundtrip failures."""
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n",
                              "docs/yamark.toml": '[format]\nmarkdown_horizontal_rule = "***"\n',
                              "docs/post.md": "***\n", "caller/.keep": ""})
    result = yamark("git-filter", "check", "--repo", "..", cwd=workdir / "caller")
    assert result.stdout == b"yamark Git filter check passed for 1 Markdown file(s).\n"
    assert result.stderr == b""
    assert result.returncode == 0

    write_tree(workdir, {"docs/yamark.toml": ""})
    git(genv, workdir, "commit", "-q", "-am", "drop config")
    result = yamark("git-filter", "check", "--repo", "..", cwd=workdir / "caller")
    assert result.stdout == b""
    assert result.stderr.decode() == f"error: docs/post.md{ROUNDTRIP_FAILURE}\n"
    assert result.returncode == 1


def test_check_requires_shared_gitattributes(yamark, genv, workdir):
    """CATCHES: a check that passes vacuously (or falls back to .git/info/attributes) when the repository has
    no shared .gitattributes file, instead of failing with the read error."""
    make_repo(genv, workdir, {"post.md": CANONICAL})
    (workdir / ".git/info/attributes").write_text("*.md filter=yamark-md\n")
    result = yamark("git-filter", "check")
    assert result.stdout == b""
    assert norm(result.stderr, workdir) == (
        "error: {repo}/.gitattributes: failed to read shared Git attributes: No such file or directory (os error 2)\n")
    assert result.returncode == 1


def test_check_rejects_non_utf8_committed_blob(yamark, genv, workdir):
    """CATCHES: a check that lossily decodes a Latin-1 Markdown blob (and so passes or reports a roundtrip
    failure) instead of failing with a UTF-8 decoding error."""
    make_repo(genv, workdir, {".gitattributes": "*.md filter=yamark-md\n", "post.md": b"Caf\xe9 au lait.\n"})
    result = yamark("git-filter", "check")
    assert result.stdout == b""
    assert result.stderr.decode() == "error: git output was not UTF-8: invalid utf-8 sequence of 1 bytes from index 3\n"
    assert result.returncode == 1


def test_check_validates_markdown_with_non_utf8_names(yamark, genv, workdir):
    """CATCHES: a check that skips Markdown files whose names are not UTF-8 (or chokes on an unrelated
    non-UTF-8 binary name) instead of validating them and naming the noncanonical one with U+FFFD."""
    init_repo(genv, workdir, (("core.quotePath", "true"),))
    write_tree(workdir, {".gitattributes": "*.md filter=yamark-md\n", "post.md": CANONICAL})
    (workdir / os.fsdecode(b"unrelated-\xff.bin")).write_text("unrelated file\n")
    (workdir / os.fsdecode(b"post-\xff.md")).write_text(WRAPPED)
    git(genv, workdir, "add", ".")
    git(genv, workdir, "commit", "-q", "-m", "fixture")
    result = yamark("git-filter", "check", "--markdown-wrap-at-column", "32")
    assert result.stdout == b""
    assert result.stderr.decode() == f"error: post-�.md{ROUNDTRIP_FAILURE}\n"
    assert result.returncode == 1
