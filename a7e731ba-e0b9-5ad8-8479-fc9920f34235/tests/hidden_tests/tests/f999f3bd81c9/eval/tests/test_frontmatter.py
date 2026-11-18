"""Frontmatter transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_frontmatter(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'title:    Test\n'
        '---\n'
        '#   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_flow_markdown_options(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter flow markdown options; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'editor_options: {markdown: {wrap: sentence}}\n'
        '---\n'
        'One sentence. Two sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_flow_markdown_options.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_folded_scalar_trailing_blank(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter folded scalar trailing blank; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'description: >\n'
        '  This is a folded scalar with enough words to rewrap into several shorter lines\n'
        '\n'
        'authors: Tomasz Kalinowski\n'
        '---\n'
        'Body text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--prose-width', '38'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_folded_scalar_trailing_blank.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_indent_sequence(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter indent sequence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'topic:\n'
        '- item\n'
        '---\n'
        'Text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_indent_sequence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_paragraph_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter paragraph wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'editor_options: {markdown: {wrap: paragraph}}\n'
        '---\n'
        'First paragraph\n'
        'uses two source lines.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_paragraph_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_scalar_quote_simplification(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter scalar quote simplification; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'title: "Snapshot page"\n'
        'tags: [rust,yaml,formatters]\n'
        '---\n'
        '#   Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_scalar_quote_simplification.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_sentence_column_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown front-matter formatting for frontmatter sentence column wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: sentence:32\n'
        '---\n'
        'Short first. This second sentence contains enough words to wrap across the requested column. Short last.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_sentence_column_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
