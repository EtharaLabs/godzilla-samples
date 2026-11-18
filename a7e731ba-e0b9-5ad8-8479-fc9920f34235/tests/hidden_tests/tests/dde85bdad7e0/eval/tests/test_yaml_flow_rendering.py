"""YAML flow collections and compact (block-to-flow) rendering.

Covers aliases, preserved template items, explicit keys, inner comments, anchors and
tags on nested flow collections, unbraced single-pair mappings, property-only empty
scalars, multi-line plain scalars and layout hints, under default, `--compact`, and
narrow `--compact --line-width 30` settings.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'alias_items': 'base: &b 1\nlist:\n  - *b\n  - 2\nmap:\n  x: *b\n',
    'alias_with_comment': 'base: &b 1\nlist:\n  - *b # c\n  - 2\n',
    'template_item': 'list:\n  - "{{ a }}"\n  - b\nflow: [ "{{ a }}" ,  b ]\n',
    'skip_inside': 'list:\n  # fmt: skip\n  - [ 1,2 ]\n  - b\n',
    'explicit_key_flow': 'm: {? a : b, c: d}\nn: [ {? x : y} ]\n',
    'inner_comment_flow': 'm: [1, # one\n  2]\nn: {a: 1, # c\n  b: 2}\n',
    'anchor_nested_flow': 'outer: [&a [1, 2], &m {k: v}]\n',
    'tag_nested_flow': 'outer: [!t [1, 2], !!map {k: v}, !!seq [3]]\n',
    'unbraced_pair': 'list: [a: b, c: d]\nnested: [[x: y]]\n',
    'empty_props_in_flow': 'f: [!!str , &e , x]\ng: {k: !!str , j: &q }\n',
    'block_scalar_in_seq': 'list:\n  - |\n    text\n  - b\n',
    'multiline_plain_in_flow': 'f: [one\n  two, three]\n',
    'multiline_plain_block_item': 'list:\n  - one\n    two\n  - three\n',
    'comment_after_item': 'list:\n  - a # c\n  - b\n',
    'empty_value_pair': 'm:\n  a:\n  b: 1\n',
    'null_values': 'm:\n  a: ~\n  b: null\n  c: Null\n',
    'quoted_flow_unsafe': 'list:\n  - \'a, b\'\n  - "c: d"\n  - \'[x]\'\n  - \'#h\'\n  - \' lead\'\n',
    'plain_unsafe_in_flow': 'list:\n  - a,b\n  - c]d\n  - e{f\n  - g: h\n',
    'booleans_in_flow': 'list:\n  - TRUE\n  - False\n  - yes\n  - NO\n',
    'nested_compact': 'a:\n  b:\n    c:\n      - 1\n      - 2\n    d: {e: f}\n',
    'wide_compact': 'a:\n  - xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n  - yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy\n',
    'mapping_in_seq': 'list:\n  - a: 1\n    b: 2\n  - c: 3\n',
    'seq_of_seq': 'list:\n  - - 1\n    - 2\n  - - 3\n',
    'anchored_collection': 'a: &x\n  - 1\n  - 2\nb: !t\n  k: v\n',
    'complex_keys': '? [a, b]\n: 1\n? {c: d}\n: 2\n',
    'flow_key_mapping': '{[a, b]: 1, {c: d}: 2}\n',
    'single_quote_escape': 'list:\n  - \'it\'\'s\'\n  - "say \\"x\\""\n',
    'double_quoted_escapes': 'list:\n  - "tab\\there"\n  - "nl\\nhere"\n  - "\\u00e9"\n',
    'long_flow_expand': 'items: [alpha, beta, gamma, delta, epsilon, zeta, eta, theta, iota, kappa, lambda]\n',
    'flow_trailing_comment': 'items: [1,  2] # comment\nmap: {a:  1} # c2\n',
    'flow_multiline_expand': 'items: [\n  1, 2,\n  3]\nmap: {\n  a: 1,\n  b: 2}\n',
    'flow_multiline_nested': 'outer: {\n  inner: [1,\n    2],\n  other: x}\n',
    'flow_empty_entries': 'a: []\nb: {}\nc: [ ]\nd: { }\n',
    'hint_bracket_collapse': 'tags: [\n  - a\n  - b\nmeta: {\n  k: v\n',
}

MODES = {"default": [], "compact": ["--compact"], "compact_narrow": ["--compact", "--line-width", "30"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_flow_rendering(name, mode, run, workdir, golden):
    """CATCHES: compacting collections that hold comments, block scalars, multi-line plain
    scalars or explicit keys; dropping anchors/tags/aliases; wrong quoting of flow-unsafe
    plain scalars; or wrong expand/collapse decisions at the line width."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
