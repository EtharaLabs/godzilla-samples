"""YAML block-structure edges: explicit keys that are compact sequences, inline
mappings, empty or commented; tab characters that end a block when a directive forces
parsing; irregular dedents; a byte order mark at the start of a later line; standalone
`[`/`{` collapse hints; incomplete flow collections; quoted keys in compact tables; and
sequences of `---`/`...` document markers that produce empty documents.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'consecutive_start_markers': '---\n---\na:   1\n',
    'start_markers_with_comments': '--- # one\n--- # two\na:   [1,2]\n',
    'start_end_start_empty': '---\n...\n---\n...\n',
    'repeated_end_markers': 'a:   1\n...\n...\n',
    'only_start_marker': '---\n',
    'only_end_marker': '...\n',
    'trailing_start_marker': 'a:   1\n---\n',
    'start_marker_with_tag_then_start': '--- !tag\n---\nb:   2\n',
    'end_then_content_without_start': 'a:   1\n...\nb:   2\n',
    'directive_then_markers': '%YAML 1.2\n---\n---\nc:   3\n',

    'explicit_compact_sequence_key': '? - a\n  - b\n: value\nz:   1\n',
    'explicit_inline_mapping_key': '? a: b\n  c: d\n: value\nz:   1\n',
    'explicit_empty_key_with_nested_block': '?\n  k: v\n: value\nz:   1\n',
    'explicit_empty_key_only': '?\n: value\nz:   1\n',
    'explicit_key_comment_then_key': '? # c\n  key\n: v\n',
    'explicit_tagged_flow_key': '? !t [a,   b]\n: v\n',
    'tab_breaks_mapping_with_directive': '# fmt: compact\na:\n  b:   1\n\tc: 2\nd:   [1,2]\n',
    'tab_breaks_after_pair_with_directive': '# fmt: compact\na:   1\n\tb: 2\n',
    'tab_breaks_sequence_with_directive': '# fmt: compact\n- a\n\t- b\n- c\n',
    'tab_inside_block_scalar_with_directive': '# fmt: compact\na: |\n  x\n\ty\nb:   1\n',
    'irregular_dedent': 'a:\n    b:   1\n  c:   2\nd:   3\n',
    'bom_at_line_start_mid_file': 'a:   1\n\ufeffb:   2\n',
    'standalone_bracket_hint': 'a:\n[\n  - x\n  - y\nb:   1\n',
    'standalone_brace_hint': 'a:\n{\n  k: v\n  j: w\nb:   1\n',
    'incomplete_flow_root': '[a, b\n',
    'incomplete_flow_value': 'a: [1, 2\nb:   1\n',
    'root_scalar_with_comment': 'plain   value   # comment\n',
    'table_quoted_keys_compact': '# fmt: compact table\n- \'a: b\': 1\n  "#c": 2\n- \'a: b\': 10\n  "#c": 20\n',
}

MODES = {"default": [], "compact": ["--compact"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_structure_edge(name, mode, run, workdir, golden):
    """CATCHES: mis-parsing explicit-key shapes, continuing a block across a tab-indented
    line, mishandling irregular dedents or mid-file BOMs, ignoring standalone collapse
    hints, or rewriting incomplete flow collections."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
