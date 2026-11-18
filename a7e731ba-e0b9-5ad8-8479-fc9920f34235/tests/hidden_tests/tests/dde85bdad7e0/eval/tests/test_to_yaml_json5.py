"""`yamark to-yaml --stdin-file-path x.json5`: JSON5 projection to formatted YAML.

The reference decodes every JSON5 string escape itself, normalises numbers that
YAML would read differently, keeps comments as YAML comments (switching to block
layout when any comment exists), quotes keys that are not IdentifierNames or are
YAML reserved words, and reports precise line:column diagnostics for invalid input.
"""

import pytest

from conftest import outcome


def _to_yaml(run, text, *extra, path="input.json5"):
    return run(["to-yaml", "--stdin-file-path", path, *extra], input=text)


STRING_CASES = {
    "simple_escapes": r"""{a: 'it\'s', b: "q\"", c: '\\', d: '\/', e: '\b\f\v', f: 'x\ny\rz\t', g: '\0', h: '\x41B', i: '\q'}""",
    "surrogate_pair_escape": r"""["\uD83D\uDE00 smile"]""",
    "bmp_unicode_escape": r"""["caf\u00e9 \u2603"]""",
    "line_continuations": "['one \\\ntwo', 'three \\\r\nfour', 'five \\\rsix']",
    "separator_continuations": "['a\\\u2028b', 'c\\\u2029d']",
    "raw_separators_in_strings": "['a\u2028b', \"c\u2029d\"]",
    "raw_separators_outside_strings": "[1,\u20282,\u20293]",
    "special_looking_strings": "['true', 'null', '123', '', ' lead', 'a: b', '#x', '- y', 'multi\\nline']",
    "long_string_stays_double_quoted": "{a: '" + "word " * 30 + "'}",
    "root_string_with_comments": "/* c */ 'hello' // d",
    "single_quoted_containing_double": "['say \"hi\"', \"it's\"]",
}


@pytest.mark.parametrize("name", sorted(STRING_CASES))
def test_string_decoding(name, run, golden):
    """CATCHES: wrong decoding of JSON5 string escapes (\\v, \\0, \\x, surrogate pairs,
    escaped line terminators, U+2028/U+2029) or wrong YAML quoting of the decoded value,
    since the complete YAML output must match the reference byte for byte."""
    assert outcome(_to_yaml(run, STRING_CASES[name])) == golden(f"string_{name}")


NUMBER_CASES = {
    "decimal_point_forms": "[.5, 5., -.25, +3.]",
    "exponents_keep_spelling": "[1e3, 1.5E-2, .5e1, 5.e+2]",
    "hexadecimal_prefixes": "[0x1F, 0X1f, 0XAB]",
    "negative_hexadecimal_becomes_decimal": "[-0x1F, -0XFF, -0xFFFFFFFFFFFFFFFFFFFF]",
    "unary_plus_dropped": "[+1, +0x10, +.5]",
    "infinity_and_nan": "[Infinity, -Infinity, +Infinity, NaN, -NaN, +NaN]",
    "unary_with_comments": "[- /* c */ 1, + // d\n 2]",
    "plain_integers": "[0, -0, 10, 12345678901234567890]",
}


@pytest.mark.parametrize("name", sorted(NUMBER_CASES))
def test_number_normalisation(name, run, golden):
    """CATCHES: emitting JSON5 number spellings that YAML would misread (leading/trailing
    decimal points, 0X prefixes, unary plus, Infinity/NaN) or keeping a negative
    hexadecimal literal that YAML would treat as a string."""
    assert outcome(_to_yaml(run, NUMBER_CASES[name])) == golden(f"number_{name}")


KEY_CASES = {
    "identifier_names": "{$x: 1, _y: 2, ab: 3, caf\u00e9: 4, \u00e1: 5, x\u0663: 6, a\u200db: 7}",
    "reserved_word_keys": "{null: 1, true: 2, false: 3, Infinity: 4, NaN: 5, NULL: 6, True: 7}",
    "quoted_keys": "{'a b': 1, \"\": 2, '1x': 3, 'z': 4, 'k:v': 5}",
    "escaped_identifier_key": r"""{\u0061bc: 1, a\u0062: 2}""",
    "duplicate_keys_keep_order": "{b: 1, a: 2, b: 3}",
}


@pytest.mark.parametrize("name", sorted(KEY_CASES))
def test_mapping_keys(name, run, golden):
    """CATCHES: quoting keys that are valid IdentifierNames, failing to quote reserved words
    (null/true/false in any case) or non-identifier keys, mishandling escaped identifier keys,
    or reordering/deduplicating members."""
    assert outcome(_to_yaml(run, KEY_CASES[name])) == golden(f"key_{name}")


COMMENT_CASES = {
    "block_layout_with_comments": (
        "/* leading\n * star line\n   plain line */\n{\n  // member\n  a: 1, // after a\n"
        "  b: [ // open\n    1, /* one */\n    2,\n    // tail\n  ],\n  c: {}, // empty obj\n"
        "  d: [], /* empty arr */\n  e: { // only comment\n  },\n  f: [\n    // only comment\n  ],\n}\n"
        "// trailing\n"
    ),
    "nested_collections_with_comment": "// c\n[[1, 2], [], {}, [[3]], {a: [4, {b: 5}]}, 'x']",
    "comments_around_separators": "[1, // a\n /* b */ 2]",
    "comments_inside_member": "{a /* k */ : /* v */ 1 /* after */, /* next */ b: 2}",
    "crlf_comment": "{\r\n  a: 1, // x\r\n}\r\n",
    "control_characters_in_comment": "// tab\there \u0007 bell\n[1]",
    "separators_in_comments": "// note\u2028[1, /* x\u2029y */ 2]",
    "block_comment_on_own_lines": "{\n  /*\n   * first\n   *\n   * second\n   */\n  a: 1\n}",
    "comment_before_nested_object": "{\n  outer: // c\n  {inner: {deep: true}},\n}",
    "comment_in_nested_array_item": "[\n  [ // inner\n    1,\n  ],\n]",
}


@pytest.mark.parametrize("name", sorted(COMMENT_CASES))
def test_comment_projection(name, run, golden):
    """CATCHES: dropping or misplacing JSON5 comments, not switching to block layout when
    comments exist, wrong `-`/nested indentation in block layout, or failing to escape
    control characters that cannot appear in a YAML comment."""
    assert outcome(_to_yaml(run, COMMENT_CASES[name])) == golden(f"comment_{name}")


ERROR_CASES = {
    "lone_high_surrogate": r"""["\uD83D x"]""",
    "high_surrogate_then_text": r"""["\uD83DA"]""",
    "high_surrogate_bad_low_hex": r"""["\uD83D\uZZZZ"]""",
    "high_surrogate_non_low_pair": r"""["\uD83D\u0041"]""",
    "lone_low_surrogate": r"""["ok", "\uDE00"]""",
    "legacy_zero_digit_escape": r"""['\01']""",
    "legacy_digit_escape": r"""['\7']""",
    "bad_hex_escape": r"""['\xZ1']""",
    "bad_unicode_escape": r"""['\u12G4']""",
    "next_line_character_outside_strings": "[1,\u00852]",
    "double_unary": "[- -1]",
    "identifier_surrogate_escape": r"""{\uD800: 1}""",
    "identifier_non_unicode_escape": r"""{\x61: 1}""",
    "invalid_identifier_start": r"""{1a: 1}""",
    "nesting_too_deep": "[" * 257 + "]" * 257,
    "unterminated_string": "{a: 'x}",
    "trailing_garbage": "{} x",
    "empty_input": "",
    "comment_only_input": "// nothing\n",
    "bare_identifier_value": "{a: b}",
    "unary_on_string": "[-'x']",
    "error_after_line_separator": "[\u2028\u2028'\\uDE00']",
    "error_on_later_line": "{\n  a: 1,\n  b: '\\9',\n}",
}


@pytest.mark.parametrize("name", sorted(ERROR_CASES))
def test_invalid_json5_diagnostics(name, run, golden):
    """CATCHES: accepting invalid JSON5 (lone surrogates, legacy octal escapes, U+0085 as
    whitespace, stacked unary operators, >256 nesting) or reporting the wrong message,
    line or column, or a wrong exit status, since stderr and status must match exactly."""
    assert outcome(_to_yaml(run, ERROR_CASES[name])) == golden(f"error_{name}")


def test_nesting_at_limit_is_accepted(run, golden):
    """CATCHES: an off-by-one nesting limit; exactly 256 nested arrays must still convert."""
    assert outcome(_to_yaml(run, "[" * 256 + "]" * 256)) == golden("nesting_at_limit")


def test_extension_is_case_insensitive(run, golden):
    """CATCHES: selecting the JSON5 grammar only for a lowercase `.json5` suffix; `.JSON5`
    must accept identifiers and single quotes too."""
    assert outcome(_to_yaml(run, "{a: 'x', b: .5}", path="DATA.JSON5")) == golden("uppercase_extension")


def test_line_width_expands_long_flow(run, golden):
    """CATCHES: ignoring `--line-width` for the projected YAML; a flow mapping wider than
    the limit must expand to block style."""
    text = "{alpha: 'one', beta: 'two', gamma: [1, 2, 3], delta: {x: 1}}"
    assert outcome(_to_yaml(run, text, "--line-width", "30")) == golden("line_width_expand")


def test_indent_width_applies_to_projection(run, golden):
    """CATCHES: ignoring `--indent-width` when the projected YAML expands to block style."""
    text = "{outer: {inner: {leaf: 'value that is long enough to expand the flow mapping'}}}"
    assert outcome(_to_yaml(run, text, "--indent-width", "4", "--line-width", "40")) == golden("indent_width")


def test_compact_keeps_short_collections_in_flow(run, golden):
    """CATCHES: ignoring `--compact` for to-yaml: block collections produced from commented
    JSON5 must collapse back to flow style where they fit."""
    text = "{\n  // keep\n  a: [1, 2],\n  b: {c: 1},\n}"
    assert outcome(_to_yaml(run, text, "--compact")) == golden("compact")


MORE_CASES = {
    "nulls_flow": "[null, {a: null}]",
    "nulls_block": "// c\n[null, {a: null}]",
    "root_empty_object_comment": "// c\n{}",
    "root_empty_array_comment": "// c\n[]",
    "root_empty_object_inner_comment": "{ // inside\n}",
    "root_empty_array_inner_comment": "[ /* inside */ ]",
    "nested_empty_collections_with_comments": "// c\n[[ // a\n], { /* b */ }]",
    "identifier_escape_surrogate_after_start": r"{a\uD800: 1}",
    "identifier_escape_bad_after_start": r"{a\x62: 1}",
    "identifier_joiners_and_marks": "{a\u200cb: 1, c\u200dd: 2, é: 3, f_‿: 4}",
    "error_right_after_line_separator": "[\u2028@]",
    "error_after_separator_in_string": "['a\u2028b', \\1]",
    "error_after_separator_in_comment": "// x\u2029@",
    "utf8_bom_is_ignored": "\ufeff{a: 1}",
    "crlf_continuation_then_separator": "['a\\\r\nb\u2028c']",
    "escaped_key_bmp": "{'\\u00e9t\\u00e9': 1}",
    "hex_zero_with_signs": "[-0x0, +0x0, -0x00ff]",
    "trailing_commas_everywhere": "{a: [1, 2,], b: {c: 3,},}",
    "block_comment_spanning_lines_inline": "[1 /* a\n b */, 2]",
}


@pytest.mark.parametrize("name", sorted(MORE_CASES))
def test_more_json5_shapes(name, run, golden):
    """CATCHES: wrong `null` emission, wrong `{}`/`[]` placement after comments in block layout,
    wrong identifier-part validation for escaped or joiner characters, or error positions
    that do not map back across replaced U+2028/U+2029 separators."""
    assert outcome(_to_yaml(run, MORE_CASES[name])) == golden(f"more_{name}")
