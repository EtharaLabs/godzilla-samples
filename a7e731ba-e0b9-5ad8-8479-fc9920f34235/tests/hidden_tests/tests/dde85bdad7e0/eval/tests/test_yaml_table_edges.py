"""`# fmt: table` and `# fmt: compact table` on YAML sequences of mappings.

Rows align into padded flow mappings only when every row is a supported mapping;
comments between rows split alignment groups, and comments, templates, missing
values, scalars or nested block collections inside rows make the reference keep the
source layout. Keys that are not plain-safe are quoted inside the generated flow rows.
"""

import pytest

from conftest import format_both_ways

TABLES = {
    'comment_between_rows': '# fmt: table\n- {name: a, type: int}\n# section two\n- {name: long_name, type: string}\n- {name: b, type: x}\n',
    'blank_between_rows': '# fmt: table\n- {name: a, type: int}\n\n- {name: long_name, type: string}\n',
    'compact_nested_mapping': '# fmt: compact table\n- name: a\n  meta:\n    k: 1\n    j: 2\n- name: long_name\n  meta:\n    k: 3\n',
    'compact_nested_sequence': '# fmt: compact table\n- name: a\n  tags:\n    - x\n    - y\n- name: long_name\n  tags:\n    - z\n',
    'compact_nested_sequence_comment': '# fmt: compact table\n- name: a\n  tags:\n    - x # why\n    - y\n- name: b\n  tags:\n    - z\n',
    'compact_nested_mapping_comment': '# fmt: compact table\n- name: a\n  meta:\n    k: 1 # why\n- name: b\n  meta:\n    k: 2\n',
    'compact_nested_mapping_leading_comment': '# fmt: compact table\n- name: a\n  meta:\n    # lead\n    k: 1\n- name: b\n  meta:\n    k: 2\n',
    'compact_pair_comment': '# fmt: compact table\n- name: a # first\n  type: int\n- name: b\n  type: str\n',
    'compact_pair_leading_comment': '# fmt: compact table\n- name: a\n  # about type\n  type: int\n- name: b\n  type: str\n',
    'compact_template_value': '# fmt: compact table\n- name: "{{ x }}"\n  type: int\n- name: b\n  type: str\n',
    'flow_template_value': '# fmt: table\n- {name: "{{ x }}", type: int}\n- {name: b, type: str}\n',
    'compact_nested_template': '# fmt: compact table\n- name: a\n  meta:\n    k: "{{ x }}"\n- name: b\n  meta:\n    k: 2\n',
    'compact_missing_value': '# fmt: compact table\n- name:\n  type: int\n- name: b\n  type: str\n',
    'compact_nested_missing_value': '# fmt: compact table\n- name: a\n  meta:\n    k:\n- name: b\n  meta:\n    k: 2\n',
    'compact_quoted_keys': '# fmt: compact table\n- "a b": 1\n  \'c: d\': 2\n  "#x": 3\n- "a b": 10\n  \'c: d\': 20\n  "#x": 30\n',
    'compact_complex_key': '# fmt: compact table\n- ? [a, b]\n  : 1\n- ? [c]\n  : 2\n',
    'flow_nested_flow': '# fmt: table\n- {name: a, meta: {k: 1}}\n- {name: bb, meta: {k: 22}}\n',
    'flow_nested_seq': '# fmt: table\n- {name: a, tags: [x, y]}\n- {name: bb, tags: []}\n',
    'flow_empty_row': '# fmt: table\n- {}\n- {name: a}\n',
    'compact_empty_nested_flow': '# fmt: compact table\n- name: a\n  meta: {}\n- name: bb\n  meta: []\n',
    'scalar_row': '# fmt: table\n- {name: a}\n- plain\n',
    'compact_scalar_row': '# fmt: compact table\n- name: a\n- plain\n',
    'flow_row_comment': '# fmt: table\n- {name: a, type: int} # first\n- {name: long, type: str}\n',
    'flow_row_inner_comment': '# fmt: table\n- {name: a, # inner\n   type: int}\n- {name: long, type: str}\n',
    'compact_anchor_value': '# fmt: compact table\n- name: &n a\n  type: int\n- name: *n\n  type: str\n',
    'compact_tagged_value': '# fmt: compact table\n- name: !t a\n  type: int\n- name: b\n  type: !!str 1\n',
    'flow_quoted_key': '# fmt: table\n- {"a b": 1, \'c\': 2}\n- {"a b": 10, \'c\': 20}\n',
    'compact_multiline_scalar': '# fmt: compact table\n- name: a\n  text: |\n    block\n- name: b\n  text: x\n',
    'compact_nested_deep': '# fmt: compact table\n- name: a\n  meta:\n    inner:\n      k: 1\n- name: b\n  meta:\n    inner:\n      k: 2\n',
    'compact_skip_value': '# fmt: compact table\n- name: a\n  # fmt: skip\n  type:   int\n- name: b\n  type: str\n',
    'table_inline_comment_parent': 'rows: # fmt: table\n  - {name: a, type: int}\n  - {name: long_name, type: string}\n',
    'compact_table_inline_parent': 'rows: # fmt: compact table\n  - name: a\n    type: int\n  - name: long_name\n    type: string\n',
    'table_inline_populated_parent': 'rows: [1] # fmt: table\n',
    'table_wide_rows': '# fmt: table\n- {name: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: int, extra: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}\n- {name: c, type: d, extra: e}\n',
    'table_unicode_widths': '# fmt: table\n- {name: café, type: 日本語}\n- {name: a, type: b}\n',
}

WIDTHS = {"default": [], "narrow": ["--line-width", "40"]}


@pytest.mark.parametrize("width", sorted(WIDTHS))
@pytest.mark.parametrize("name", sorted(TABLES))
def test_table_directive(name, width, run, workdir, golden):
    """CATCHES: aligning rows across a comment boundary, compacting rows that contain
    comments/templates/nested block collections/missing values, wrong padding after the
    first field, wrong key quoting, or wrong errors for a populated parent with an inline
    table directive."""
    observed = format_both_ways(run, workdir, "rows.yaml", TABLES[name], *WIDTHS[width])
    assert observed == golden(f"{name}__{width}")
