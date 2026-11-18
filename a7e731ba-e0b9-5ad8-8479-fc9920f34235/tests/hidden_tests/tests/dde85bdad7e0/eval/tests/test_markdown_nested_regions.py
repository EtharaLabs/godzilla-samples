"""Nested Markdown regions: YAML and Markdown fences, Quarto chunks and fenced divs.

Errors inside a nested region are reported at the host location; directives with
file scope placed at the end of the host re-plan nested regions that precede them;
local skips (`fmt: skip` fence attributes, `#| fmt: skip`, nested `skip file`) only
protect their own region. Each document is formatted with and without `--verify`.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'adjacent_divs_in_outer_div_without_final_newline': ':::: outer\n::: a\nx\n:::\n::: b\ny\n:::\n::::',
    'adjacent_top_level_divs': '::: a\nx\n:::\n::: b\ny\n:::\n',
    'blank_line_runs_without_final_newline': 'Para one.\n\n\n\nPara two.',
    'blank_line_runs_crlf': 'Para one.\r\n\r\n\r\nPara two.\r\n',
    'front_matter_cr_only': '---\ra:   1\r---\r\rBody   text.\r',
    'yaml_fence_error': 'Intro.\n\n```yaml\n# fmt: on\na: 1\n```\n',
    'markdown_fence_error': '````markdown\n<!-- fmt: wrap=bogus -->\ntext\n````\n',
    'div_error': '::: note\n<!-- fmt: on scope=file -->\n\ntext\n:::\n',
    'pandoc_simple_after_directive': '<!-- fmt: skip -->\n\n  A      B\n-----  ---\n  x      y\n\nAfter   text.\n',
    'pandoc_table_markdown_target': '<!-- fmt: markdown -->\n\n  A      B\n-----  ---\n  x      y\n',
    'gfm_table_markdown_target': '<!-- fmt: markdown -->\n\n| a | b |\n|---|---|\n| x | y |\n',
    'footnote_markdown_target': '<!-- fmt: markdown -->\n\n[^1]: note   text\n',
    'file_scope_after_nested': '```yaml\na:   [1,2]\nbody: !markdown "One   sentence. Two sentences."\n```\n\n````markdown\nSome   text. More text here.\n````\n\n::: note\nDiv   text. More div text.\n:::\n\nTop paragraph. Second sentence.\n\n<!-- fmt: wrap=sentence -->\n',
    'file_scope_canonical_after_nested': '````md\nUse __strong__ here.\n````\n\n::: aside\nAlso __this__ one.\n:::\n\n```yaml\nb: !md "__x__"\n```\n\n<!-- fmt: canonical -->\n',
    'file_scope_table_widths_after': '| a | b |\n|---|---|\n| long cell | x |\n\n````markdown\n| c | d |\n|---|---|\n| y | long cell |\n````\n\n<!-- fmt: table-widths=preserve -->\n',
    'file_scope_footnotes_after': 'Text[^1].\n\n[^1]: A   footnote   with spacing.\n\n<!-- fmt: footnotes=preserve -->\n',
    'nested_skip_file_in_fence': '````markdown\n<!-- fmt: skip file -->\nKeep   this.\n````\n\nFormat   this.\n',
    'yaml_fence_skip_attr': '```yaml fmt: skip\na:   1\n```\n\n```yaml\nb:   2\n```\n',
    'quarto_chunk_skip': '```{python}\n#| fmt: skip\n#| echo: false\nx=1\n```\n',
    'nested_fences_three_levels': '`````markdown\n````markdown\n```yaml\na:   [1,2]\n```\n````\n`````\n',
}

MODES = {"default": [], "verify": ["--verify"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_nested_region(name, mode, run, workdir, golden):
    """CATCHES: wrong error locations for directives inside nested fences/divs, late
    file-scope directives that fail to reach earlier nested regions, or local skips that
    leak into sibling regions or the host document."""
    observed = format_both_ways(run, workdir, "doc.md", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
