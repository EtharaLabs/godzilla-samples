"""Markdown list and definition-list structure: blank-line continuations, second
definitions and terms, quote/fence/raw/heading children of list items, task-list
continuations, wide ordered markers, mixed nested markers and lazy continuations,
under column, sentence and narrow wrapping.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'deflist_trailing_blank': 'Term\n: definition text here\n\n',
    'deflist_second_definition': 'Term\n: first   definition\n\n: second   definition\n',
    'deflist_second_term': 'Term\n: definition   one\n\nTerm two\n: definition   two\n',
    'deflist_continuation_paragraph': 'Term\n: definition\n\n    continued   paragraph that is long enough to wrap at the default column width.\n',
    'deflist_then_paragraph': 'Term\n: definition\n\nPlain   paragraph.\n',
    'list_quote_child': '- item text\n  > quoted   child line\n- next\n',
    'list_quote_child_list': '- item\n  > - nested list in quote\n- next\n',
    'list_quote_child_fence': '- item\n  > ```\n  > code\n  > ```\n',
    'list_quote_deep_indent': '- item\n      > deep quote\n',
    'task_continuation': '- [ ] task item with words\n      continuation aligned to text\n- [x] done\n',
    'list_trailing_blank': '- item one\n- item two\n\n',
    'list_blank_then_indented': '- item one\n\n      indented code-like\n- item two\n',
    'list_raw_html_child': '- item\n    <div>raw</div>\n',
    'list_child_heading_multiline_code': '- item `code\n  # not heading` text\n',
    'list_setext_child': '- item\n  Title\n  ===\n',
    'ordered_list_wide': '1.  first   item\n2.  second\n10. tenth item text\n',
    'nested_lists_mixed_markers': '- a\n  * b\n    + c   text\n',
    'list_lazy_continuation': '- item text\nlazy   continuation line\n',
}

WRAPS = {"default": [], "sentence": ["--wrap", "sentence"], "col20": ["--wrap", "20"]}


@pytest.mark.parametrize("wrap", sorted(WRAPS))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_list_structure(name, wrap, run, workdir, golden):
    """CATCHES: wrong list/definition membership after blank lines, reflowing items whose
    children (quotes, fences, raw HTML, headings) must stay put, wrong continuation
    indentation for task items or wide ordered markers, or lost lazy continuations."""
    observed = format_both_ways(run, workdir, "doc.md", DOCUMENTS[name], *WRAPS[wrap])
    assert observed == golden(f"{name}__{wrap}")
