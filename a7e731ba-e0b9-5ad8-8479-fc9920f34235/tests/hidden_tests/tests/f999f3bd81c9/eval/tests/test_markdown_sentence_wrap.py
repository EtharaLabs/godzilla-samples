"""Markdown sentence wrap transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_asterisk_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of asterisk boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'One sentence. * two words. * three words. Last sentence.\n'
        '\n'
        'Code `*`. Opening sentence. * More prose.\n'
        '\n'
        'HTML <span title="*">x</span>. Opening sentence. * value.\n'
        '\n'
        'Literal \\*. Opening sentence. * value.\n'
        '\n'
        'Literal \\* here. Opening sentence. * value.\n'
        '\n'
        'Escaped \\\\*. Opening sentence. * value.\n'
        '\n'
        'Math \\(x \\* y\\). Opening sentence. * value.\n'
        '\n'
        'Comment <!-- * -->. Opening sentence. * value.\n'
        '\n'
        'Em *x*. Opening sentence. * value.\n'
        '\n'
        'Strong **x**. Opening sentence. * value.\n'
        '\n'
        'Nested **x *y* z**. Opening sentence. * value.\n'
        '\n'
        'Math *$x * y$*. Opening sentence. * value.\n'
        '\n'
        'Unmatched *x. Opening sentence. * value.\n'
        '\n'
        'Em *unmatched \\(*. Opening sentence. (b) value.\n'
        '\n'
        'HTML *<!-- \\> -->*. Opening sentence. * value.\n'
        '\n'
        'Em *x * y*. Opening sentence. * value.\n'
        '\n'
        'Math 2 * 3. Opening sentence. * value.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'asterisk_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_block_starts(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of block starts; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Intro line\n'
        'continues. Pick one. - other thing.\n'
        '\n'
        '> Options: (a) keep it. (b) drop it.\n'
        '\n'
        '[^note]: Steps: first. - second.\n'
        '\n'
        'Intro line\n'
        'continues. > still prose.\n'
        '\n'
        'Intro line\n'
        'continues. # still prose.\n'
        '\n'
        'Before break. Safe sentence.\\\n'
        'More prose. - still prose. Last sentence.\n'
        '\n'
        'Opening sentence. Pick one. - unfinished\n'
        '\n'
        'Ordinary first. `- literal marker`. Next sentence.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        '- Preserve   spacing. - still prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'block_starts.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_block_candidates(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column block candidates; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening. Table: caption text. Finish.\n'
        '\n'
        'Opening. [label]: target. Finish.\n'
        '\n'
        'Opening. : definition text. Finish.\n'
        '\n'
        'Opening. | table text. Finish.\n'
        '\n'
        'Opening. ~~~ literal fence. Finish.\n'
        '\n'
        'Opening. ___ literal rule. Finish.\n'
        '\n'
        'Opening. \\[ literal math. Finish.\n'
        '\n'
        'Opening. Ordinary words stay prose. Finish.\n'
        '\n'
        'Opening. Élan stays prose. Finish.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'column_block_candidates.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_emphasis_repairs(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column emphasis repairs; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before. *** *word*\n'
        '\n'
        'Opening. Safe sentence. *** *word*\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:72'], input=stdin)
    assert result.stdout == (RES / 'column_emphasis_repairs.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_escaped_punctuation(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column escaped punctuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening. Something 2. Later.\n'
        '\n'
        'Opening. 2. Later.\n'
        '\n'
        'Version 2. Later.\n'
        '\n'
        'Opening. Something 2. 3. Later.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:10'], input=stdin)
    assert result.stdout == (RES / 'column_escaped_punctuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_footnote_prefix(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column footnote prefix; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '[^note]:\n'
        '    1234567890 123456789\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:20'], input=stdin)
    assert result.stdout == (RES / 'column_footnote_prefix.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_marker_only(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column marker only; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Version 1.12 ships now. 2. Later.\n'
        '\n'
        '- Choose first. b. Later.\n'
        '\n'
        '- Choose first. ii. Later.\n'
        '\n'
        'Safe first. This second sentence contains enough words to wrap.\n'
        '\n'
        'First. [link](url) text. Later [x]: text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'column_marker_only.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_math_contents(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column math contents; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening. $$x + y$$ remains math.\n'
        '\n'
        'Text \\(a\\\\) + b\\) end.\n'
        '\n'
        'Text *use \\(x^* + 2\\) here*.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:12'], input=stdin)
    assert result.stdout == (RES / 'column_math_contents.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_nested_headings(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column nested headings; the exact stdout, stderr, exit status are compared."""
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
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:12'], input=stdin)
    assert result.stdout == (RES / 'column_nested_headings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_prefixes(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column prefixes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Short first. This second sentence contains enough words to wrap.\n'
        '\n'
        '> Short first. This second sentence contains enough words to wrap.\n'
        '\n'
        '- Parent\n'
        '  - 12345678901234 123456789012345\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'column_prefixes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_unsafe_breaks(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column unsafe breaks; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Opening sentence. First sentence. 2. More prose. Last sentence.\n'
        '\n'
        '- Opening sentence. First sentence. ii. More prose. Last sentence.\n'
        '\n'
        '- Opening. Next words. - more. Finish.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:12'], input=stdin)
    assert result.stdout == (RES / 'column_unsafe_breaks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_column_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of column wrap; the exact stdout, stderr, exit status are compared."""
    stdin = 'Short first. This second sentence contains enough words to wrap across the requested column. Short last.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'column_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_markers(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of definition markers; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Term sentence. ~ definition-looking prose. Last sentence.\n'
        '\n'
        'Term sentence. ~word stays prose. Last sentence.\n'
        '\n'
        'Term sentence. ~~struck text~~ stays prose. Last sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'definition_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_punctuation(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of escaped punctuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening sentence. 2\\. Later. Last sentence.\n'
        '\n'
        'Escaped period\\. Still one sentence. Last sentence.\n'
        '\n'
        'Escaped exclamation\\! Still one sentence. Last sentence.\n'
        '\n'
        'Escaped question\\? Still one sentence. Last sentence.\n'
        '\n'
        'Quoted "period\\." Still one sentence. Last sentence.\n'
        '\n'
        'Even backslashes\\\\. Next sentence.\n'
        '\n'
        'Odd backslashes\\\\\\. Still one sentence. Last sentence.\n'
        '\n'
        'Opening sentence. Version 2. Later.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_punctuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_html_tag_math_openers(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of html tag math openers; the exact stdout, stderr, exit status are compared."""
    stdin = 'HTML <img title="\\(" src="x">. Opening sentence. (b) value.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'html_tag_math_openers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_markers(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of list markers; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Options: (a) keep it. (b) drop it. Next option.\n'
        '- Steps: first. - second. + third. Finish.\n'
        '- Version 1.12 ships now. 2. Later.\n'
        '\n'
        '- Parent\n'
        '  - First choice. (ii) Second choice. Last choice.\n'
        '\n'
        '- First sentence. Second sentence.\n'
        '  - Actual nested item. Another sentence.\n'
        '\n'
        '- Escaped markers. \\- still prose. \\(b) still prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_marker_only(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of marker only; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Version 1.12 ships now. 2. Later.\n'
        '\n'
        '- Choose first. b. Later.\n'
        '\n'
        '- Choose first. ii. Later.\n'
        '\n'
        '- Version 1.12 ships now. 2.\n'
        '\n'
        'Safe first. Version 1.12 ships now.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'marker_only.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_meaning_sensitive(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of meaning sensitive; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening sentence. <!-- hidden --> More prose. Last sentence.\n'
        '\n'
        'Opening sentence. <div>inline HTML.</div> More prose. Last sentence.\n'
        '\n'
        'Opening sentence. $$x + y$$ remains math. Last sentence.\n'
        '\n'
        'Opening sentence. `- literal marker`. Last sentence.\n'
        '\n'
        'The operator <! means mismatch. Next sentence.\n'
        '\n'
        'The operator <? means a query. Next sentence.\n'
        '\n'
        'Term\n'
        '~ Definition sentence. Another sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'meaning_sensitive.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parenthesized_marker_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of parenthesized marker escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening. (b) value \\) remains prose.\n'
        '\n'
        'Opening. (ii) value \\) remains prose.\n'
        '\n'
        '- Opening. (2) value \\) remains prose.\n'
        '\n'
        '> Opening. (B) value \\) remains prose.\n'
        '\n'
        'Keep \\(b) + y\\) as math. Last sentence.\n'
        '\n'
        'Keep \\(a (b\\) as math. Last sentence.\n'
        '\n'
        'Opening \\( remains prose. (b) value. Last sentence.\n'
        '\n'
        'Opening \\( remains prose. 2) value. Last sentence.\n'
        '\n'
        'Code `\\(`. Opening sentence. (b) value.\n'
        '\n'
        'Code `\\\\(`. Opening sentence. 2) value.\n'
        '\n'
        'Closed \\(x + y\\). Opening sentence. (b) value.\n'
        '\n'
        'Closed \\(x + y\\). Opening sentence. 2) value.\n'
        '\n'
        'Escaped \\\\( remains prose. (b) value.\n'
        '\n'
        'Opening sentence. (b) value. Later \\( remains open.\n'
        '\n'
        '*Code `\\(`*. Opening sentence. (b) value.\n'
        '\n'
        'Code `\\(`.\\\n'
        'Opening sentence. (b) value.\n'
        '\n'
        'Closed \\(x + y\\).\\\n'
        'Opening sentence. (b) value.\n'
        '\n'
        'Unmatched \\( stays open.\\\n'
        'Opening sentence. (b) value. Last sentence.\n'
        '\n'
        'HTML <span title="\\(">x</span>. Opening sentence. (b) value.\n'
        '\n'
        'Link [text][\\(]. Opening sentence. (b) value.\n'
        '\n'
        'Attribute [text]{title="\\("}. Opening sentence. (b) value.\n'
        '\n'
        'Span [unmatched \\(]{.class}. Opening sentence. (b) value.\n'
        '\n'
        'Command \\text{\\(}. Opening sentence. (b) value.\n'
        '\n'
        'Autolink <https://example.com/\\(>. Opening sentence. (b) value.\n'
        '\n'
        '*HTML <span title="\\(">x</span>*. Opening sentence. (b) value.\n'
        '\n'
        'HTML <span>\\(</span>. Opening sentence. (b) value.\n'
        '\n'
        '*Unmatched \\(*. Opening sentence. (b) value.\n'
        '\n'
        '~~Unmatched \\(~~. Opening sentence. (b) value.\n'
        '\n'
        'Braces {\\(}. Opening sentence. (b) value.\n'
        '\n'
        'HTML <span title="\\(">x</span>.\\\n'
        'Opening sentence. (b) value.\n'
        '\n'
        'HTML <span title="\\(">x</span>. Unmatched \\( stays open. (b) value. Last sentence.\n'
        '\n'
        'Braces [text]{not an=attribute \\(}. Opening sentence. (b) value.\n'
        '\n'
        'Bracket [unmatched \\(]. Opening sentence. (b) value.\n'
        '\n'
        'Bracket [unmatched \\(][missing]. Opening sentence. (b) value.\n'
        '\n'
        'Bracket [escaped \\\\(]. Opening sentence. (b) value.\n'
        '\n'
        'Link [text](https://example.com "\\("). Opening sentence. (b) value.\n'
        '\n'
        'Link [x](a). Opening sentence. (b) value.\n'
        '\n'
        'Citation [@key]. Opening sentence. (b) value.\n'
        '\n'
        'Comment <!-- > \\( -->. Opening sentence. (b) value.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'parenthesized_marker_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_reference_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of reference boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening. [x] text ]: still prose.\n'
        '\n'
        'Opening. [x]: target. Last sentence.\n'
        '\n'
        'Opening. [x\\]]: target. Last sentence.\n'
        '\n'
        'Opening. [x\\]] text ]: still prose.\n'
        '\n'
        'Opening. [^x] text ]: still prose.\n'
        '\n'
        '[ref]: https://example.com\n'
        '  "title   spacing"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'reference_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_setext_candidates(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of setext candidates; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Opening. - word. --\n'
        '\n'
        'Opening. - word. ==\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'setext_candidates.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_shortcode_math_opener(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of shortcode math opener; the exact stdout, stderr, exit status are compared."""
    stdin = 'Opening {{< foo "\\(" >}}. First. (b) value.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:12'], input=stdin)
    assert result.stdout == (RES / 'shortcode_math_opener.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_wrap_list_split_link(run, workdir):
    """CATCHES: implementations that differ from the reference in sentence-per-line Markdown wrapping of wrap list split link; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- [posit-dev/mcp-repl](https://github.com/posit-dev/mcp-repl) for\n'
        '  persistent worker, sandbox, output, and native R frontend patterns;\n'
        "- [Positron's Data Explorer](\n"
        '    https://positron.posit.co/data-explorer.html\n'
        '  ) and [Plots pane](https://positron.posit.co/plots-pane.html) for\n'
        '  human-facing ephemeral data exploration and full-scale plot\n'
        '  inspection.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'wrap_list_split_link.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
