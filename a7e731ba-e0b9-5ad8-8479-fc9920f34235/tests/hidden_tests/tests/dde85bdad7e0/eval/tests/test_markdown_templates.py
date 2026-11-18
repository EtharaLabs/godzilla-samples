"""Template delimiters in Markdown: default `{{ }}`, `{% %}`, `{# #}`, `<% %>` spans as
opaque words, quoted closers, nested braces, multi-line and unterminated expressions,
templates inside links and emphasis, and `fmt: template.delimiters` with next, inferred,
and late file scopes re-planning paragraphs, lists, quotes, footnotes, definition lists
and nested fences (tables and headings keep their own policy).
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'late_template_paragraph_list_quote': 'Keep << a   b >> here   and there.\n\n- item << c   d >>   x\n\n> quote << e   f >>   y\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'late_template_table': '| a | << x   y >> |\n|---|---|\n| 1 | 2 |\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'heading_with_template': '#   Title {{ x   y }}\n\nSetext {{ a  b }}\n===\n\n##   Plain   heading\n',
    'heading_late_template': '#   Title << x   y >>\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'skip_file_at_end': 'Some   text.\n\n<!-- fmt: skip file -->\n',
    'late_template_raw_html': 'Text <span>a << b >> c</span>   here.\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'late_template_definition_list': 'Term << x >>\n: definition << y   z >>   text\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'late_template_nested_fence': '````markdown\nKeep << a   b >> here.\n````\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'late_template_footnote': 'Text[^1].\n\n[^1]: Note << a   b >>   text.\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
    'default_delimiters': 'Before {{ render("keep   this") }} then {% if x   y %} and {# a  comment #} plus <% erb   code %> after the text.\n',
    'template_only_line': 'Before\n{{ render("keep   this") }}\nafter.\n',
    'quoted_closer_inside': 'A {{ say("}} not end") }} and {{ \'a }} b\' }} tail text here.\n',
    'comment_first_closer': 'A {# x "#} y" #} rest of   the line.\n',
    'nested_braces': "Value {{ {'a': {'b': 1}} }} end   of   line.\n",
    'multiline_expression': 'Start {{ first\n  second }} end   text.\n',
    'template_in_link': 'See [{{ name }}](http://x/{{ id }}) and *{{ em   x }}* here.\n',
    'unterminated_template': 'Open {{ never closed and   more   text here.\n',
    'next_scope_template': '<!-- fmt: template.delimiters "[[" "]]" scope=next -->\nKeep [[ a   b ]] here.\n\nNot [[ c   d ]] here.\n',
    'inferred_scope_template': 'Intro   text.\n\n<!-- fmt: template.delimiters "[[" "]]" -->\n\nKeep [[ a   b ]] here.\n\nAnd [[ c   d ]] too.\n',
    'template_needs_explicit_scope': 'Intro   text.\n<!-- fmt: template.delimiters "[[" "]]" -->\nKeep [[ a   b ]] here.\n',
}

WRAPS = {"default": [], "sentence": ["--wrap", "sentence"], "col30": ["--wrap", "30"]}


@pytest.mark.parametrize("wrap", sorted(WRAPS))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_markdown_templates(name, wrap, run, workdir, golden):
    """CATCHES: collapsing spaces inside template spans, ending a span at a quoted closer,
    keeping template-only line placement, applying late delimiters too narrowly or to
    tables/headings, or mis-scoping a bare `template.delimiters` directive."""
    observed = format_both_ways(run, workdir, "doc.md", DOCUMENTS[name], *WRAPS[wrap])
    assert observed == golden(f"{name}__{wrap}")
