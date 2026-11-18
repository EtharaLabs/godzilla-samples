"""`--canonical` Markdown spelling (`__x__` -> `**x**`, setext -> ATX headings, two-space
hard breaks -> backslash) and the inline constructs it must leave alone: code and math
spans, inline HTML and comments, link labels/titles, autolinks (scheme and e-mail
forms), attribute braces, templates, escaped markers and unclosed strikethrough.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'unclosed_strikethrough': 'Some ~~struck text without a closing marker and __strong__ words to canonicalize here.\n',
    'closed_strikethrough': 'Some ~~struck __strong__~~ text and __strong__ words.\n',
    'autolink_schemes': 'Links <a_b:x> <x+y.z-w:path> <mailto:a@b.c> <http://e x> <ab:c<d> end of text.\n',
    'email_autolinks': "Mail <first.last+tag@example.com> or <a!b#c$d%e&f'g*h@ex.com> or <bad@> or <@bad> or <a@b..c> ok.\n",
    'braces_attributes_templates': 'Use {.class #id} and [span]{.mark} and __strong__ with {{ tmpl }} and [ref][x] here.\n\n[x]: http://x\n',
    'nested_emphasis': '__a *b* c__ and *__d__* and ___e___ and __f__g and _h_ and __ spaced __.\n',
    'escaped_markers': '\\__not strong\\__ and \\*not em\\* and __real__ ok.\n',
    'code_spans': '`__code__` and ``x ` y`` and __bold `code`__ end.\n',
    'inline_html_and_comments': '<b>__x__</b> and <!-- __c__ --> and __y__.\n',
    'math_spans': '$__x__$ and $$__y__$$ and __z__.\n',
    'headings': '#   __Title__   ##\n\nSetext __x__\n---\n',
    'hard_breaks': 'Line one  \nLine two\\\nLine three __x__\n',
    'links_and_images': '[__label__](http://x "__t__") and ![__alt__](i.png) and <http://__x__>.\n',
}

MODES = {"canonical": ["--canonical"], "canonical_col20": ["--canonical", "--wrap", "20"], "sentence": ["--wrap", "sentence"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_canonical_markdown(name, mode, run, workdir, golden):
    """CATCHES: canonicalising emphasis inside code, math, HTML, link labels or autolinks;
    misreading autolink/e-mail syntax; or a different canonical form for headings, hard
    breaks and nested emphasis."""
    observed = format_both_ways(run, workdir, "doc.md", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
