"""Document-level Markdown options read from YAML front matter:
`editor_options.markdown.{wrap,canonical,footnotes,table-widths}` (or `editor.markdown`)
apply to the body. Invalid or unknown values are ignored; quoted keys and flow mappings
are read; non-mapping or non-scalar entries contribute nothing. A valid document setting
takes precedence over an explicit `--wrap`.
"""

import pytest

from conftest import format_both_ways

BODY = '\n\nFirst sentence here. Second sentence follows and is long enough to wrap at a narrow column.\n\nUse __strong__ text.\n\n| a | b |\n|---|---|\n| long cell | x |\n\nText[^1].\n\n[^1]: A   footnote   text.\n'

FRONT_MATTER = {
    'editor_options_sentence': 'editor_options:\n  markdown:\n    wrap: sentence',
    'editor_options_column': 'editor_options:\n  markdown:\n    wrap: 30',
    'editor_options_none': 'editor_options:\n  markdown:\n    wrap: none',
    'editor_markdown_path': 'editor:\n  markdown:\n    wrap: sentence',
    'editor_options_wins_over_editor': 'editor_options:\n  markdown:\n    wrap: none\neditor:\n  markdown:\n    wrap: sentence',
    'canonical_true': 'editor_options:\n  markdown:\n    canonical: true',
    'canonical_yes': 'editor_options:\n  markdown:\n    canonical: yes',
    'canonical_no': 'editor_options:\n  markdown:\n    canonical: no',
    'canonical_zero': 'editor_options:\n  markdown:\n    canonical: 0',
    'canonical_invalid': 'editor_options:\n  markdown:\n    canonical: maybe',
    'footnotes_preserve': 'editor_options:\n  markdown:\n    footnotes: preserve',
    'footnotes_format': 'editor_options:\n  markdown:\n    footnotes: format',
    'footnotes_invalid': 'editor_options:\n  markdown:\n    footnotes: sometimes',
    'table_widths_preserve': 'editor_options:\n  markdown:\n    table-widths: preserve',
    'table_widths_invalid': 'editor_options:\n  markdown:\n    table-widths: auto',
    'unknown_option_ignored': 'editor_options:\n  markdown:\n    colour: red\n    wrap: sentence',
    'wrap_invalid_ignored': 'editor_options:\n  markdown:\n    wrap: wide',
    'wrap_sentence_width': 'editor_options:\n  markdown:\n    wrap: "sentence:30"',
    'quoted_keys_and_values': '"editor_options":\n  \'markdown\':\n    "wrap": \'sentence\'',
    'markdown_not_mapping': 'editor_options:\n  markdown: sentence',
    'markdown_flow_mapping': 'editor_options:\n  markdown: {wrap: sentence, canonical: true}',
    'nested_value_not_scalar': 'editor_options:\n  markdown:\n    wrap:\n      - sentence',
    'no_markdown_options': 'title: Plain\nauthor: Someone',
}


@pytest.mark.parametrize("cli_wrap", [False, True], ids=["document", "cli_wrap"])
@pytest.mark.parametrize("name", sorted(FRONT_MATTER))
def test_front_matter_options(name, cli_wrap, run, workdir, golden):
    """CATCHES: ignoring front-matter Markdown options, reading the wrong option path,
    accepting invalid values, failing to read quoted keys or flow mappings, or letting an
    explicit `--wrap` override a valid document setting (the document setting wins)."""
    text = "---\n" + FRONT_MATTER[name] + "\n---" + BODY
    flags = ["--wrap", "20"] if cli_wrap else []
    observed = format_both_ways(run, workdir, "doc.md", text, *flags)
    assert observed == golden(f"{name}__{'cli' if cli_wrap else 'doc'}")
