"""Markdown column wrap transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_column_asterisk_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column asterisk escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Literal \\* star \\* here.\n'
        '\n'
        'One sentence. * two words. * three words. Last sentence.\n'
        '\n'
        'Literal \\* \\(x * y\\)\n'
        '\n'
        'Literal \\* $x * y$\n'
        '\n'
        'Literal \\* $$x * y$$\n'
        '\n'
        'Literal \\* *x*.\n'
        '\n'
        'Math 2 * 3. Opening sentence. * value.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'column_asterisk_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_backslash_math_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column backslash math escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Keep \\(b) + y\\) as math.\n'
        '\n'
        'Keep \\(a (b\\) as math.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'column_backslash_math_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_emphasis_math_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column emphasis math escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Text *use \\(x^* + 2\\) here*.\n'
        '\n'
        'Text **use \\(x^** + 2\\) here**.\n'
        '\n'
        'Text _use \\(x^_ + 2\\) here_.\n'
        '\n'
        'Text *use \\(x\\\\) + y^* + 2\\) here*.\n'
        '\n'
        'Text *use \\(x^* + 2\\) here*. Outside 2\\) remains prose.\n'
        '\n'
        'Text *use $x^* + 2$ here*.\n'
        '\n'
        'Text *use `\\(x^* + 2\\)` here*.\n'
        '\n'
        'Text *use \\\\(x^* + 2\\) here*.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_emphasis_math_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_emphasis_repairs(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column emphasis repairs; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'something * *** |\n'
        '\n'
        'Costs* *include taxes* (b) details.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'column_emphasis_repairs.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_escape_width(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column escape width; the exact stdout, stderr, exit status are compared."""
    stdin = 'preamble (a) marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '10'], input=stdin)
    assert result.stdout == (RES / 'column_escape_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_final_marker_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column final marker escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before text 2\\.\n'
        '\n'
        'Before text 2.\n'
        '\n'
        'Ordinary div\\.\n'
        '\n'
        'Ordinary div.\n'
        '\n'
        '- Ordinary 1\\.\n'
        '\n'
        '- Ordinary 1.\n'
        '\n'
        'Before text 2\\.\\\n'
        'more prose.\n'
        '\n'
        'Before text 2.\\\n'
        'more prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'column_final_marker_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_hard_break_asterisk_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column hard break asterisk escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Note \\*\\\n'
        '*Emphasis* text.\n'
        '\n'
        'Note \\* \\\n'
        '*Emphasis* text.\n'
        '\n'
        'Note \\*  \n'
        '*Emphasis* text.\n'
        '\n'
        'Note \\*\\\n'
        'ordinary prose.\n'
        '\n'
        'Note \\*\\\n'
        '`*` text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_hard_break_asterisk_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_hard_break_marker_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column hard break marker escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Ordinary 1\\.  \n'
        '  more prose.\n'
        '\n'
        '- Ordinary 1\\. \\\n'
        '  more prose.\n'
        '\n'
        '- Ordinary 1\\.\\\n'
        '  more prose.\n'
        '\n'
        '- Ordinary 1\\.\n'
        '\n'
        '- Brief 1\\.  \n'
        '  done.\n'
        '\n'
        'Ordinary 1\\.  \n'
        'more prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'column_hard_break_marker_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_inline_html_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column inline html escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before <span \\> after.\n'
        '\n'
        'Before <span title="sample" \\> after.\n'
        '\n'
        'Before </span \\> after.\n'
        '\n'
        '- Before <span \\> after.\n'
        '\n'
        '> Before <span \\> after.\n'
        '\n'
        'Before. \\> literal blockquote marker.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_inline_html_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_literal_marker_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column literal marker escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- First sentence. - More prose.\n'
        '\n'
        '- First sentence.\n'
        '  \\- More prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'column_literal_marker_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_math_sensitive_emphasis(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column math sensitive emphasis; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Text *use \\(x^* + 2\\) here* and *more*.\n'
        '\n'
        'Text **use \\(x^** + 2\\) here** and **more**.\n'
        '\n'
        'Text *use `\\(x^*` + 2\\) here* and *more*.\n'
        '\n'
        'Text *use $x^* + 2$ here* and *more*.\n'
        '\n'
        'Text *simple emphasis* and *more*.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'column_math_sensitive_emphasis.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_nested_headings(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column nested headings; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '> # Title \\#\n'
        '\n'
        '- # Title \\#\n'
        '\n'
        '> > ## Nested \\#\n'
        '\n'
        '- Parent\n'
        '  > # Title \\#\n'
        '\n'
        '- Parent\n'
        '  ## Title \\#\n'
        '\n'
        '> Title\n'
        '> -----\n'
        '\n'
        '- Title\n'
        '  =====\n'
        '\n'
        '> > Title\n'
        '> > -----\n'
        '\n'
        '> Before. # still prose.\n'
        '\n'
        '- Before. # still prose.\n'
        '\n'
        '> #not a heading. Next sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_nested_headings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_column_opaque_html_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column opaque html escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before <!-- \\> --> after.\n'
        '\n'
        'Before <!-- > \\# --> after.\n'
        '\n'
        'Before <?pi > \\# ?> after.\n'
        '\n'
        'Before <![CDATA[ > \\# ]]> after.\n'
        '\n'
        'Before <!DOCTYPE \\# > after.\n'
        '\n'
        'Before *<!-- \\> -->* after.\n'
        '\n'
        'Before <span><!-- \\> --></span> after.\n'
        '\n'
        'Escaped \\<!-- \\> --> after.\n'
        '\n'
        'Before. \\> literal blockquote marker.\n'
        '\n'
        'HTML <span title="<!--">x</span>.\n'
        'Opening sentence.\n'
        '\\- value.\n'
        '\n'
        'Code `<!--`.\n'
        'Opening sentence.\n'
        '\\- value.\n'
        '\n'
        'The operator <! means mismatch.\n'
        'Next sentence.\n'
        '\n'
        'The operator <? means a query.\n'
        'Next sentence.\n'
        '\n'
        'Before <!-- \\> without a closer.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_opaque_html_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_ordered_marker_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column ordered marker escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- First prose. 2) More prose.\n'
        '\n'
        '- First prose. (b) More prose.\n'
        '\n'
        'Last div.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'column_ordered_marker_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_preserved_html_literals(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column preserved html literals; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before   `a  \n'
        'b` <!-- comment --> after. \n'
        '\n'
        'Before <!-- comment --> `a  \n'
        'b` after.\n'
        '\n'
        'Before `a\t\n'
        'b` <input value="a > \\- b"> after.\n'
        '\n'
        '> Before `a  \n'
        '> b` <!-- comment --> after.\n'
        '\n'
        '- Before `a  \n'
        '  b` <!-- comment --> after.\n'
        '\n'
        '::: {.note}\n'
        'Before `a  \n'
        'b` <!-- comment --> after.\n'
        ':::\n'
        '\n'
        'Outside   `a  \n'
        'b` after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_preserved_html_literals.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_quoted_html_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column quoted html escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before <input value="a > \\- b"> after.\n'
        '\n'
        "Before <input value='a > \\- b'> after.\n"
        '\n'
        'Before <input value=\'a " > \\# b\' /> after.\n'
        '\n'
        'Before <span title="a > \\- b">inside</span> after.\n'
        '\n'
        'Before *<input value="a > \\- b">* after.\n'
        '\n'
        'Before <kbd title="> `">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
        '\n'
        'Before <input value="plain">\n'
        'continues after.\n'
        '\n'
        'Before `<input value="a > \\- b">`\n'
        'continues after.\n'
        '\n'
        'Before. \\- ordinary prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_quoted_html_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_raw_tex_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column raw tex escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Text \\begin{math}a \\# b\\end{math} end.\n'
        '\n'
        'Text \\begin{math}a + b \\begin{nested}\\#\\end{nested}\\end{math} end.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_raw_tex_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_column_sentence_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column sentence escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening sentence.\n'
        'Pick one.\n'
        '\\- unfinished\n'
        '\n'
        '> Options: (a) keep it.\n'
        '> (b\\) drop it.\n'
        '\n'
        '- Version 1.12 ships now.\n'
        '  2\\. Later.\n'
        '\n'
        '\\- Literal marker at paragraph start.\n'
        '\n'
        'Keep \\*literal emphasis\\* and `\\- literal code` unchanged.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'column_sentence_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_trailing_asterisk_repairs(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of column trailing asterisk repairs; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Costs* *include taxes* (b) details.\n'
        '\n'
        'Costs\\* *include taxes* (b) details.\n'
        '\n'
        '*Costs* *include taxes* (b) details.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '23'], input=stdin)
    assert result.stdout == (RES / 'column_trailing_asterisk_repairs.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_default_column_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of default column wrap; the exact stdout, stderr, exit status are compared."""
    stdin = 'Short first. This second sentence is deliberately long enough that it must wrap before reaching the configured default column of seventy-two characters. Short last.\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'default_column_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directive_paragraph_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of directive paragraph wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: wrap=paragraph scope=next -->\n'
        'First sentence. Second sentence\n'
        'continues here.\n'
        '\n'
        'Third sentence. Fourth sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'directive_paragraph_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directive_sentence_column_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of directive sentence column wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: wrap=sentence:32 scope=next -->\n'
        'Short first. This second sentence contains enough words to wrap across the requested column. Short last.\n'
        '\n'
        'This following paragraph stays on its existing line. It is not sentence wrapped.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'directive_sentence_column_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_marker_only_column(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of marker only column; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'marker_only_column.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '24', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_none(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of marker only none; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'marker_only_none.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_paragraph(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of marker only paragraph; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'marker_only_paragraph.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_sentence(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of marker only sentence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'marker_only_sentence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_paragraph_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown column/paragraph wrapping of paragraph wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First sentence. Second sentence\n'
        'continues on the next source line.\n'
        '\n'
        'Second paragraph\n'
        'stays separate.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'paragraph_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
