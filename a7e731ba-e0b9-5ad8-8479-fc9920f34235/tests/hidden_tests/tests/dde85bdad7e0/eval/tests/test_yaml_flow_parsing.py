"""YAML flow-collection parsing: implicit single-pair entries (`[: v]`, `[k: v]`), key-only
pairs, collection keys, aliases and anchors inside flow, comments inside multi-line flow,
glued properties, quotes inside plain keys, partial or keyed template spans, adjacent
colons, trailing commas and deep nesting, under default, `--compact` and narrow widths.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'empty_key_entry': 'f: [ : value , x ]\n',
    'tagged_empty_key_entry': 'f: [ !t : value ]\n',
    'key_only_pairs': 'm: { a , b: 1 , c }\n',
    'flow_key_collection_entry': 'f: [ [a, b]: c , {d: e}: f ]\n',
    'aliases_in_flow': 'base: &b 1\nf: [ *b , x , *b ]\nm: { k: *b }\n',
    'anchors_in_flow': 'f: [ &a 1 , &b [2] , &c {x: 1} ]\n',
    'comment_after_scalar_multiline': 'f: [a # c\n  , b]\n',
    'comment_between_entries_multiline': 'f: [1,\n  # comment\n  2]\n',
    'table_inner_comment': '# fmt: table\n- {name: a, # c\n  type: b}\n- {name: bb, type: c}\n',
    'table_multiline_rows': '# fmt: table\n- {\n  name: a,\n  type: "one, two"\n}\n- {\n  name: longer,\n  type: x\n}\n',
    'property_glued': 'f: [ !t"x" , &a\'y\' ]\n',
    'quote_inside_plain_key': 'f: [ a"b: c , d\'e: f ]\n',
    'single_quote_escape_key': "f: [ 'it''s': v ]\n",
    'double_quote_escape_key': 'f: [ "a\\"b": v ]\n',
    'partial_template': 'f: [ {% a , b ]\nm: [ {{ c }} , d ]\n',
    'template_key': 'f: [ {{ k }}: v , x ]\n',
    'nested_implicit_pairs': 'f: [ [a: b] , {c: [d: e]} ]\n',
    'colon_adjacent': 'f: [ a:b , c: d , "e":f ]\n',
    'url_values': "f: [ http://x.y/z , 'a: b' ]\n",
    'multiline_plain_entry': 'f: [ one\n  two , three ]\n',
    'flow_trailing_comma': 'f: [ a , b , ]\nm: { a: 1 , }\n',
    'empty_entries': 'f: [ , ]\n',
    'deep_nesting': 'f: [[[[[[1]]]]]]\n',
    'complex_compact_multiline': 'a:\n  - {x: 1, # c\n     y: 2}\n  - [1,\n     2]\n',
}

MODES = {"default": [], "compact": ["--compact"], "narrow": ["--line-width", "20"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_flow_parsing(name, mode, run, workdir, golden):
    """CATCHES: mis-parsing flow entries (implicit pairs, empty keys, key-only pairs, aliases),
    normalising flows that hold comments, glued properties or partial templates, or wrong
    spacing/quoting decisions after parsing."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
