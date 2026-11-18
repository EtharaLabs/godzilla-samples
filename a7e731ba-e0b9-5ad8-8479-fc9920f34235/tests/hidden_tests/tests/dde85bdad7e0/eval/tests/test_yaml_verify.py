"""`--verify`: the formatted YAML is reparsed and compared with the input value, and
output that is invalid or changes the value is rejected (status 1, file untouched).

Covers folded and literal block scalars (leading blanks, more-indented lines, keep/strip
chomping, indentation indicators), tagged and quoted core values, empty values,
explicit keys, byte-order-mark characters inside scalars, aliases, tagged collections,
multi-document streams and multi-line quoted scalars, at default and narrow prose
widths and with `--compact`.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'folded_leading_blank': 'a: >\n\n  word word word word word word word word word word word word word word word word word word word word \nb: [1,2]\n',
    'folded_more_indented': 'a: >\n  word word word word word word word word word word word word word word word word word word word word \n\n    indented line\n\n  word word word word word word word word word word word word word word word word word word word word \nb: [1,2]\n',
    'folded_more_indented_adjacent': 'a: >\n  word word word word word word word word word word word word word word word word word word word word \n    indented line\n  word word word word word word word word word word word word word word word word word word word word \nb: [1,2]\n',
    'folded_keep': 'a: >+\n  word word word word word word word word word word word word word word word word word word word word \n\n\nb: [1,2]\n',
    'folded_strip': 'a: >-\n  word word word word word word word word word word word word word word word word word word word word \n\nb: [1,2]\n',
    'folded_trailing_blanks_only': 'a: >\n  word word word word word word word word word word word word word word word word word word word word \n\n\n\n',
    'literal_keep': 'a: |+\n  x\n\n\nb: [1,2]\n',
    'literal_indent_indicator': 'a: |2\n    x\n  y\nb: [1,2]\n',
    'literal_only_blank': 'a: |\n\n\nb: [1,2]\n',
    'quoted_null_tag': "a: !!null ''\nb: [1,2]\n",
    'quoted_bool_tag_odd': "a: !!bool 'yes'\nb: [1,2]\n",
    'bool_variants': 'a: [True, FALSE]\nb: TRUE\nc:  1\n',
    'nested_empty_values': 'a:\n  b:\n  c: [1,2]\n? d\n',
    'explicit_without_values': '? a\n? b\nc: [1,2]\n',
    'bom_inside_plain_scalar': 'a: x\ufeffy\nb: [1,2]\n',
    'bom_inside_block_scalar': 'a: |\n  x\ufeffy\nb: [1,2]\n',
    'anchor_alias': 'a: &x [1,2]\nb: *x\nc: [3,4]\n',
    'tagged_collections': 'a: !!seq [1,2]\nb: !!map {c: d}\nc: !custom [ 1 , 2 ]\n',
    'multi_document': 'a: [1,2]\n---\nb: [3,4]\n...\n---\n',
    'quoted_multiline': 'a: "one\n  two"\nb: \'three\n\n  four\'\nc: [1,2]\n',
}

MODES = {"verify": ["--verify"], "verify_narrow": ["--verify", "--prose-width", "30"], "verify_compact": ["--verify", "--compact"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_verified_formatting(name, mode, run, workdir, golden):
    """CATCHES: a verifier that accepts value-changing output (e.g. a dropped `!!null ""`
    tag value or a BOM character inside a plain scalar) or rejects value-preserving
    rewrites such as folded-scalar rewrapping, chomping changes and core normalisation."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
