"""YAML preservation edges: UTF-8 byte order marks (a BOM-prefixed stream is kept
byte-for-byte unless an active directive requires formatting), `fmt: skip` / `fmt: off`
on sequence items and mappings, lifecycle errors (targetless skip, stray or nested
off/on), and `skip file` scoping in multi-document streams (it covers the whole physical file).
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'bom_root_pair_with_later_directive': '\ufeffa:   1\n# fmt: compact\nb:\n  - 1\n',
    'bom_flow_root_with_later_directive': '\ufeff[1,  2]\n# fmt: compact\n',
    'bom_sequence_root_with_later_directive': '\ufeff-   a\n# fmt: compact\n- - b\n  - c\n',
    'bom_quoted_root_with_skip': '\ufeff"x"\n# fmt: skip\n',
    'bom_crlf_root_with_later_directive': '\ufeffa:   1\r\n# fmt: compact\r\nb:\r\n  - 1\r\n',
    'sequence_item_empty_markdown_target': '# fmt: markdown\n-\n- x\n',
    'sequence_item_empty_markdown_tag': '- !markdown\n- y:   1\n',
    'explicit_entry_missing_optional_formatter': '# fmt: missing\n? k\n: |\n  x\nz:   1\n',
    'explicit_entry_comment_on_value_line': '? k\n: # c\n  value\n',
    'explicit_entry_tag_on_value_line': '? k\n: !t\n  value\n',
    'off_region_nested_pairs': 'a:\n  b:   1\n  # fmt: off\n  c:   [1,2]\n  d:\n    e:   1\n  # fmt: on\n  f:   2\n',
    'off_region_sequence_items': '- a:   1\n# fmt: off\n- b:   [1,2]\n- - x\n  -   y\n# fmt: on\n- c:   3\n',
    'bom_plain': '\ufeffa:   1\n',
    'bom_directive': '\ufeff# fmt: compact\na:\n  - 1\n',
    'bom_flow': '\ufeff[1,  2]\n',
    'bom_comment_first': '\ufeff# c\na:   1\n',
    'bom_doc_marker': '\ufeff---\na:   1\n',
    'bom_seq': '\ufeff- a\n-   b\n',
    'bom_markdown_scalar': '\ufeffbody: !markdown "x   y"\n',
    'bom_crlf': '\ufeff# fmt: compact\r\na:\r\n  - 1\r\n',
    'skip_seq_item_block': 'list:\n  # fmt: skip\n  - a:   1\n    b:   2\n  - c:   3\n',
    'skip_seq_item_tagged': 'list:\n  # fmt: skip\n  - !t\n    a:   1\n  - c:   3\n',
    'skip_seq_item_comment': 'list:\n  # fmt: skip\n  - # note\n    a:   1\n  - c:   3\n',
    'skip_seq_item_nested_seq': 'list:\n  # fmt: skip\n  - - x\n    -   y\n  - c:   3\n',
    'skip_second_item': 'list:\n  - a:   1\n  # fmt: skip\n  - b:   [1,2]\n  - c:   3\n',
    'off_on_seq': 'list:\n  # fmt: off\n  - a:   1\n  # fmt: on\n  - b:   2\n',
    'off_on_mapping': 'a:   1\n# fmt: off\nb:   [1,2]\nc:    3\n# fmt: on\nd:   [3,4]\n',
    'off_without_on': 'a:   1\n# fmt: off\nb:   2\n',
    'skip_without_target': 'a:   1\n# fmt: skip\n',
    'nested_off': '# fmt: off\na: 1\n# fmt: off\nb: 2\n# fmt: on\n',
    'table_not_planned': '# fmt: table\n# lead\n- {a: 1}\n- plain\n',
    'table_compact_comment_first': '# fmt: compact table\n# first comment\n- a: 1\n  b: x\n- a: 22\n  b: y # c\n',
    'skip_file_mid_document': 'a:   1\n# fmt: skip file\nb:   2\n',
    'skip_in_second_document': 'a:   1\n---\n# fmt: skip file\nb:   2\n---\nc:   3\n',
}

MISSING_FORMATTER_CONFIG = '[embedded.missing]\nformatter = { command = ["ruff", "{path}"], path_suffix = ".txt" }\n'

MODES = {"default": [], "compact": ["--compact"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_preservation_edge(name, mode, run, workdir, tool_bin, golden):
    """CATCHES: formatting BOM-prefixed YAML without an active directive (or dropping the
    BOM when it is formatted), preserving too much or too little around skip/off regions,
    accepting invalid off/on lifecycles, or scoping `skip file` differently in a multi-document
    stream (the reference preserves the whole physical file)."""
    (workdir / "yamark.toml").write_text(MISSING_FORMATTER_CONFIG)
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode], env_overrides={"PATH": str(tool_bin)})
    assert observed == golden(f"{name}__{mode}")
