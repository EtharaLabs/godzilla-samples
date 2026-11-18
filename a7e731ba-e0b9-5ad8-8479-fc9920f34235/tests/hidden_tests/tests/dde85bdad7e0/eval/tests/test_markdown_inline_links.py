"""Markdown inline tokens that wrapping must treat atomically or preserve: Pandoc
citations (including labels split across lines), inline and reference links with
double-quoted, single-quoted and parenthesised titles, unsupported titles and
destinations, long link targets, nested brackets, autolinks, code and math spans.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'citations': 'As shown [@smith2020] and [-@jones; see @doe, p. 3] and [@a; @b] plus [not @ a] and [;@x] and [@] and [\\@esc] in a sentence long enough to wrap around the configured column width.\n',
    'citation_boundaries': 'Mail me at a@b.com or [see foo@bar] or [(@paren)] then [@key_with-dash:colon] here and some more words to wrap.\n',
    'link_titles': 'See [double](http://example.com/path "Double Title") and [single](http://example.com \'Single\') and [paren](http://example.com (Paren)) for details and more words.\n',
    'link_title_unsupported': 'See [esc](http://e.com "a \\" b") and [nl](http://e.com "a\nb") and [bs](http://e.com/a\\b) and [q](http://e.com/\'q\') and [bad](http://e.com "x" y) end.\n',
    'long_link_split': 'Read [this very long link label](https://example.com/a/very/long/path/that/keeps/going "An extremely long title that will not fit") today.\n',
    'empty_link_target': 'An [empty]() link and [space]( ) link in prose that is long enough to wrap around here.\n',
    'reference_links': 'Use [label][ref] and [label] [ref2] and [shortcut] and [^note] here, [multi\nline][ref].\n\n[ref]: http://x\n[ref2]: http://y\n[shortcut]: http://z\n[^note]: footnote\n',
    'nested_brackets': 'Text [outer [inner] text](http://x) and ![img [alt]](i.png) and [a]](b) done.\n',
    'autolinks_and_code': 'Visit <https://example.com/very/long/autolink/path> and `code with [brackets](x)` and $math [x](y)$ ok.\n',
    'parens_in_destination': 'See [link](http://x.com/a_(b)_c) and [q](http://x.com/"q") and [deep](http://x.com/((a))) end of text.\n',
    'multiline_citation': 'Some text that is fairly long [see\n@smith2020, p. 3] and more text after it to wrap.\n',
    'multiline_suppressed_citations': 'Text [-@a;\n@b] here and then a lot of additional words for wrapping.\n',
    'multiline_late_marker': 'Text [x\n-@y] and words words words words words words words words.\n',
    'multiline_escaped_at': 'Text [\\@x\ny] and words words words words words words words words.\n',
    'multiline_no_boundary': 'Text [a@b\nc] and words words words words words words words words.\n',
    'multiline_empty_part': 'Text [@a;\n;@b] and words words words words words words words words.\n',
    'multiline_bare_at': 'Text [@\nx] and words words words words words words words words.\n',
    'multiline_paren_boundary': 'Text [(@a)\nx] and words words words words words words words words.\n',
    'citation_in_list': '- Item with [see\n  @key] reference and more words to wrap the item text.\n',
    'footnote_reference_wrap': 'A sentence with a footnote[^long-footnote-name] reference and more words here.\n\n[^long-footnote-name]: The note.\n',
}

WRAPS = {"default": [], "col30": ["--wrap", "30"], "sentence": ["--wrap", "sentence"], "none": ["--wrap", "none"], "canonical": ["--canonical"]}


@pytest.mark.parametrize("wrap", sorted(WRAPS))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_inline_tokens(name, wrap, run, workdir, golden):
    """CATCHES: breaking a line inside a citation, link label, link target or title; joining
    labels that must stay split; rewriting unsupported link titles/destinations; or wrong
    recognition of `@key` citation markers and their boundaries."""
    observed = format_both_ways(run, workdir, "doc.md", DOCUMENTS[name], *WRAPS[wrap])
    assert observed == golden(f"{name}__{wrap}")
