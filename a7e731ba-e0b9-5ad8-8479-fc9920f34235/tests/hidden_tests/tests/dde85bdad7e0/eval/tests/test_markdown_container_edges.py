"""Markdown container edge shapes: blockquotes (simple, nested, rich, lazy),
footnote definitions and definition lists whose indentation, blank lines or marker
spacing push the formatter onto its fallback paths.

Each shape is formatted under column, sentence, none and narrow-column wrapping; the
reference either reflows the container or preserves it exactly, and a reimplementation
must make the same decision with the same bytes.
"""

import pytest

from conftest import format_both_ways

SHAPES = {
    'bq_indent_mismatch': '> first line of the quote that is long enough to need wrapping at the column\n > second line\n',
    'bq_blank_inside': '> first paragraph inside\n>\n> second paragraph inside the quote\n',
    'bq_trailing_blank': '> only paragraph line here\n>\n',
    'bq_deep_indent': '    > code not quote\n> real quote\n',
    'bq_nested_varying_indent': '> > a nested quote line that is long enough to wrap around the column width of seventy\n>  > b\n',
    'bq_nested_blank': '> > a\n> >\n> > b\n',
    'bq_nested_depth_change': '> > deeper quote text\n> shallower quote text continues here\n',
    'bq_nested_indented': ' > > a quoted line\n  > > b quoted line\n',
    'bq_rich_list': '> - item one that is long enough to wrap around the default column width here\n>   more\n> - item two\n',
    'bq_rich_indent_mismatch': '> - item\n  > - other\n',
    'bq_rich_deep_indent': '> # Heading\n     > deep\n',
    'bq_lazy': '> quoted start\nlazy continuation line here\n',
    'fn_short_continuation': '[^1]: footnote text that is long enough to wrap around the default column width\n  short indent continuation\n',
    'fn_no_final_newline': '[^1]: footnote text that is long enough to wrap around the default column width of 72',
    'fn_indented_four': '    [^1]: indented four spaces\n',
    'fn_blank_then_para': '[^1]: first para\n\n    second para of footnote that is long enough to wrap around the column width\n',
    'fn_tab_continuation': '[^n]: text\n\tcontinued with tab\n',
    'dl_no_space': 'Term\n:text right after colon\n',
    'dl_tab': 'Term\n:\tdefinition after tab that is long enough to wrap around the column width of seventy two\n',
    'dl_two_spaces': 'Term\n:  definition after two spaces that is long enough to wrap around the column width\n',
    'dl_continuation': 'Term\n: definition\n    continued with four spaces that is long enough to wrap around the default column\n',
    'dl_tilde': 'Term\n~ tilde definition text\n',
    'dl_indented_marker': 'Term\n  : indented marker definition\n',
}

WRAPS = {"default": [], "sentence": ["--wrap", "sentence"], "none": ["--wrap", "none"], "col30": ["--wrap", "30"]}


@pytest.mark.parametrize("wrap", sorted(WRAPS))
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_container_shape(shape, wrap, run, workdir, golden):
    """CATCHES: reflowing a container whose membership could change (indent mismatches,
    blank quote lines, depth changes, short footnote continuations, glued definition
    markers) or failing to reflow a supported one, in stdin and path --check modes."""
    observed = format_both_ways(run, workdir, "doc.md", SHAPES[shape], *WRAPS[wrap])
    assert observed == golden(f"{shape}__{wrap}")
