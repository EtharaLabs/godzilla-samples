"""Markdown blocks transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_code_fence_attributes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of code fence attributes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '``` {.bash filename="Terminal"}\n'
        'quarto render\n'
        '```\n'
        '\n'
        '``` {=typst}\n'
        '#pagebreak()\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'code_fence_attributes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_code_fence_info(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of code fence info; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '```{.markdown .markdown}\n'
        '#   Title ##\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'code_fence_info.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_emission_sibling_states(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of emission sibling states; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First  [link](https://example.org/a) and `literal  spaces`.\n'
        '\n'
        'Second  [site](https://example.org/b) has more words.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        'Keep   spaces.\n'
        '\n'
        'Last   `code  span` and [end](https://example.org/c).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'emission_sibling_states.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_yaml_finalize(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of frontmatter yaml finalize; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        'title: "Hello"\n'
        'body: !markdown "This is __strong__."\n'
        '---\n'
        'Text __strong__.\n'
        '\n'
        '<!-- fmt: canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_yaml_finalize.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_heading(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of heading; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '#   Title ##\n'
        '\n'
        '## R Is Rich in  Interactive Surfaces\n'
        '\n'
        'A   short   paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'heading.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_heading_unicode_attribute(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of heading unicode attribute; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# Café{#id}\n'
        '\n'
        '## 東京{.city}\n'
        '\n'
        '# [Café](https://example.com){#link}\n'
        '\n'
        '# `Café`{.code}\n'
        '\n'
        '# [unfinished [Café](https://example.com){#link}\n'
        '\n'
        '# [unfinished [a\\]b][réf]{#link}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'heading_unicode_attribute.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_yaml_template_after_layout(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of late yaml template after layout; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '```yaml\n'
        'held: &saved # parent\n'
        "  'Café value'\n"
        'quoted: "<< item >>"\n'
        'items: [<< a,b >>]\n'
        'body: !markdown |\n'
        '  Keep __strong__ and << literal  bytes >>.\n'
        'plain: !markdown |\n'
        '  Keep __strong__ and `literal  bytes`.\n'
        'attached: !markdown\n'
        '  |\n'
        '    Keep __attached__.\n'
        'ok: [x,y]\n'
        '```\n'
        '\n'
        '<!-- fmt: canonical=true scope=file -->\n'
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--line-width', '12', '--wrap', 'none'],
        input=stdin,
    )
    assert result.stdout == (RES / 'late_yaml_template_after_layout.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_yaml_template_policy(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of late yaml template policy; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '```yaml\n'
        'held: &saved # parent\n'
        "  'Café value'\n"
        'quoted: "<< item >>"\n'
        'items: [<< a,b >>]\n'
        'body: !markdown |\n'
        '  Keep __strong__ and << literal  bytes >>.\n'
        'plain: !markdown |\n'
        '  Keep __strong__ and `literal  bytes`.\n'
        'attached: !markdown\n'
        '  |\n'
        '    Keep __attached__.\n'
        'ok: [x,y]\n'
        '```\n'
        '\n'
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
        '<!-- fmt: canonical=true scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--line-width', '12', '--wrap', 'none'],
        input=stdin,
    )
    assert result.stdout == (RES / 'late_yaml_template_policy.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_layout_only_policies(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown block formatting of yaml layout only policies; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '```yaml\n'
        'held: &saved # parent\n'
        "  'Café value'\n"
        'templated: ["{{ keep   bytes }}",  1]\n'
        'body: !markdown |\n'
        '  Keep __strong__.\n'
        '  Continue on another line.\n'
        'attached: !markdown\n'
        '  |\n'
        '    Keep __attached__.\n'
        'ok: [x,y]\n'
        '```\n'
        '\n'
        '<!-- fmt: canonical=true wrap=paragraph scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'yaml_layout_only_policies.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
