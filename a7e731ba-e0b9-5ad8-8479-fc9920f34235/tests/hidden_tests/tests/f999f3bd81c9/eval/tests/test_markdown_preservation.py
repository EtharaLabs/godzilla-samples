"""Markdown preservation transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_bom_blank_directive_scope(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of bom blank directive scope; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '\ufeff\n'
        '<!-- fmt: template.delimiters "<<" ">>" -->\n'
        '\n'
        'Some <<x>>   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'bom_blank_directive_scope.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_bom_blank_first_line_break(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of bom blank first line break; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '\ufeff   \n'
        '---\n'
        '\n'
        'Some   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'bom_blank_first_line_break.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_bom_blank_first_line_paragraph(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of bom blank first line paragraph; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '\ufeff   \n'
        'Some   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'bom_blank_first_line_paragraph.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_bom_only_first_line_break(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of bom only first line break; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '\ufeff\n'
        '---\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'bom_only_first_line_break.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_feff_content_setext(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of feff content setext; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Intro\n'
        '\n'
        '\ufeff\n'
        '---\n'
        '\n'
        '\ufeff   \n'
        'Next   line.\n'
        '\n'
        '> \ufeff\n'
        '> ---\n'
        '>\n'
        '> Quoted.\n'
        '\n'
        'Text[^1].\n'
        '\n'
        '[^1]: Note.\n'
        '\n'
        '    \ufeff\n'
        '    ---\n'
        '\n'
        '    More.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'feff_content_setext.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_preserved_cleanup_controls(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of preserved cleanup controls; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '    code   still copied  \t\n'
        '\n'
        '<div>\n'
        'HTML   still copied  \t\n'
        '</div>  \n'
        '\n'
        'Before {{ value }}   prose.  \t\n'
        '\n'
        'Before <widget>   unsupported prose.  \t\n'
        '\n'
        '```text\n'
        'code   still copied  \t\n'
        '```\n'
        '\n'
        '::: {.note}\n'
        'Before {{ value }}   nested prose.  \t\n'
        '\n'
        '    nested   code  \t\n'
        ':::\n'
        '\n'
        'Before   `{{\n'
        '  render(customer.address)  \t\n'
        '}}` after template.  \t\n'
        '\n'
        '> {{% quote %}}\n'
        '> Keep   unsupported continuation.  \t\n'
        '\n'
        'Format   ordinary prose. Second   sentence.  \t\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_cleanup_controls.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_preserved_nested_fragments(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of preserved nested fragments; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '::: {.outer}\n'
        'Before   child. \n'
        '\n'
        '```markdown\n'
        '<!-- fmt: skip file -->\n'
        'Keep   child prose.  \t\n'
        '`unclosed   code  \n'
        '<div malformed  \n'
        '```\n'
        '\n'
        'After   child. \n'
        ':::\n'
        '\n'
        '````markdown\n'
        'Before   div. \n'
        '\n'
        '::: {.inner}\n'
        '<!-- fmt: skip file -->\n'
        'Keep   child without shortcodes.  \n'
        '$$ unclosed   math  \t\n'
        ':::\n'
        '\n'
        'After   div. \n'
        '````\n'
        '\n'
        '::: {.outer}\n'
        '```markdown\n'
        'Before   skipped node. \n'
        '\n'
        '<!-- fmt: skip -->\n'
        'Keep   nested paragraph.  \t\n'
        '\n'
        'After   skipped node. \n'
        '```\n'
        ':::\n'
        '\n'
        'Format   outside. \n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_nested_fragments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_preserved_nodes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of preserved nodes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->  \n'
        'Keep   é prose.  \t\n'
        'And   this line.   \n'
        '\n'
        'Format   outside. Second   sentence. \n'
        '\n'
        '<!-- fmt: skip -->\n'
        '- Keep   list.  \t\n'
        '  continuation   unchanged.  \n'
        '- Another   item.   \n'
        '\n'
        '<!-- fmt: skip -->\n'
        '> Keep   quote.  \n'
        '> Next   line. \t\n'
        '\n'
        '<!-- fmt: skip -->\n'
        '::: {.note}  \n'
        'Keep   prose.  \n'
        '\n'
        '```text\n'
        'code   with spaces  \n'
        '```\n'
        '\n'
        '$$\n'
        'x + y  \n'
        '$$\n'
        '\n'
        '<div>\n'
        'HTML   with spaces  \n'
        '</div>\n'
        '\n'
        '[malformed](   \n'
        ':::  \n'
        '\n'
        '<!-- fmt: skip -->\n'
        '```markdown  \n'
        'Keep   fence prose.  \n'
        '````  \n'
        '\n'
        'Format   after containers. \n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_nodes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_preserved_off(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of preserved off; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Format   before. \n'
        '\n'
        '<!-- fmt: off -->  \n'
        'Keep   prose.  \t\n'
        '\n'
        '{{< unclosed arg="  \n'
        '```markdown  \n'
        '<div>  \n'
        '$$  \n'
        '<!-- fmt: on -->  \n'
        'Format   after. Second   sentence. \n'
        '\n'
        '<!-- fmt: off -->\n'
        '[malformed](  \t\n'
        '    code   at EOF.  \t\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_off.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_skip(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of skip; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '#   Keep ##\n'
        '\n'
        '#   Change ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'skip.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_skip_html_comment_trivia(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of skip html comment trivia; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '<!-- ordinary comment -->\n'
        '\n'
        '#   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'skip_html_comment_trivia.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_skip_paired_html_raw_target(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of skip paired html raw target; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '<section>\n'
        'raw\n'
        '</section>\n'
        '\n'
        '#   Change ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'skip_paired_html_raw_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_skip_quarto_div_raw_target(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of skip quarto div raw target; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '::: {.callout-note}\n'
        'raw\n'
        ':::\n'
        '\n'
        '#   Change ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'skip_quarto_div_raw_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_skip_raw_target(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown byte preservation and fmt: skip/off handling of skip raw target; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '    code block\n'
        '\n'
        '#   Change ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'skip_raw_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
