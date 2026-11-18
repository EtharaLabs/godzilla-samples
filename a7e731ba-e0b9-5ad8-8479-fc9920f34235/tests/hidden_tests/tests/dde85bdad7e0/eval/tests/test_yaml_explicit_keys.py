"""YAML explicit mapping entries (`? key` / `: value`).

The value line after an explicit key may hold a quoted multi-line scalar, a multi-line
flow collection, a collapse hint, a block scalar, a compact sequence, an inline mapping,
properties only, a comment, or nothing at all; the key may itself be a collection or
block scalar. Each document is formatted plainly, with `--compact`, and with `--verify`.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'key_at_eof': 'a:  1\n? lonely key\n',
    'key_without_value_line': '? first\nsecond:   2\n',
    'quoted_multiline_value': '? key\n: "multi\n  line   quoted"\nnext:  1\n',
    'flow_multiline_value': '? key\n: [\n  1,  2]\nnext:  1\n',
    'collapse_hint_value': '? key\n: [\n  - a\n  - b\nnext:  1\n',
    'block_scalar_value': '? key\n: |\n  text\nnext:  1\n',
    'compact_sequence_value': '? key\n: - a\n  - b\nnext:  1\n',
    'inline_mapping_value': '? key\n: a:   1\n  b:   2\nnext:  1\n',
    'nested_block_value': '? key\n:\n  nested:   1\n  more:  [1,2]\nnext:  1\n',
    'property_nested_value': '? key\n: !tag\n  nested:   1\nnext:  1\n',
    'anchor_nested_value': '? key\n: &anc\n  - x\n  - y\nnext:  *anc\n',
    'comment_then_nested': '? key\n: # note\n  nested:   1\n',
    'standalone_collapse_hint': '? key\n:\n[\n  - a\n  - b\n',
    'tab_nested_value': '? key\n:\n\tnested: 1\n',
    'property_only_scalar': '? key\n: !tag\nnext:   1\n',
    'empty_value': '? key\n:\nnext:   1\n',
    'indentless_sequence_value': '? key\n:\n- a\n- b\nnext:  1\n',
    'sequence_key': '? - a\n  - b\n: value\n',
    'block_scalar_key': '? |\n  block key\n: value\n',
    'flow_key': '? [a,   b]\n: {c:   d}\n',
    'nested_explicit': 'outer:\n  ? inner key\n  : inner   value\n  plain:   1\n',
    'explicit_in_sequence': '- ? k\n  : v\n- x:   1\n',
    'explicit_with_comments': '# lead\n? key # kc\n# between\n: value # vc\n',
    'explicit_long_value': '? key\n: word word word word word word word word word word word word word word word word word word word word word word word word word \n',
    'explicit_compact': '? key\n:\n  - 1\n  - 2\n',
}

MODES = {"default": [], "compact": ["--compact"], "verify": ["--verify"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_explicit_entry(name, mode, run, workdir, golden):
    """CATCHES: losing an explicit key with no value line, mis-parsing the value line after
    `:` (flow, hint, compact sequence, inline mapping, properties, comments), attaching
    properties to the wrong node, or reformatting explicit keys that must be preserved."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
