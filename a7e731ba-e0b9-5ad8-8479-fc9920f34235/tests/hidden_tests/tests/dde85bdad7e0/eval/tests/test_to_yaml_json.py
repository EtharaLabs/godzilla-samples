"""`yamark to-yaml` for strict JSON, JSONC, JSON Lines and NDJSON input.

The file suffix selects one exact grammar. Strict JSON and JSON Lines reject
comments and trailing commas; JSONC accepts them and turns comments into YAML
comments, emitting block layout whenever a comment exists. Strings are decoded
and re-emitted with YAML escapes; number spellings are preserved.
"""

import pytest

from conftest import outcome


def _to_yaml(run, path, text, *extra):
    return run(["to-yaml", "--stdin-file-path", path, *extra], input=text)


JSON_CASES = {
    "control_character_escapes": '["\\u0000\\u0007\\b\\t\\n\\u000b\\f\\r\\u001b\\"\\\\", "\\u0085\\u00a0\\u2028\\u2029", "\\u007f\\u0090\\ufffe\\uffff\\u0001\\u001f"]',
    "number_spellings_preserved": '[1.0E+10, -0.0, 1e400, 0.000001, 10, -7]',
    "nested_values": '{"a": {"b": [1, {"c": null}], "d": true, "e": false}, "f": "text"}',
    "keys_are_simplified_or_quoted": '{"plain": 1, "with space": 2, "1st": 3, "null": 4, "True": 5, "caf\\u00e9": 6, "dash-key": 7, "_u": 8, "": 9}',
    "unicode_and_quote_strings": '["it\'s", "say \\"hi\\"", "tab\\there", "\\ud83d\\ude00"]',
    "root_scalar_string": '"just a string"',
    "root_scalar_number": "  42  ",
    "long_line_expands_to_block": '{"description": "' + "lorem ipsum " * 8 + '", "items": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]}',
    "empty_collections": '{"a": {}, "b": [], "c": [{}, []]}',
}


@pytest.mark.parametrize("name", sorted(JSON_CASES))
def test_strict_json_projection(name, run, golden):
    """CATCHES: wrong YAML escapes for control/special characters, altered number spellings,
    wrong key quoting, or wrong flow/block layout when projecting strict JSON to YAML."""
    assert outcome(_to_yaml(run, "data.json", JSON_CASES[name])) == golden(f"json_{name}")


JSON_ERRORS = {
    "trailing_comma": '{"a": 1,}',
    "line_comment": '// c\n{"a": 1}',
    "single_quotes": "['x']",
    "empty_input": "",
    "whitespace_only": "  \n",
    "nesting_too_deep": "[" * 257 + "]" * 257,
    "nesting_inside_strings_ignored_then_too_deep": '["[[[[", ' + "[" * 256 + "]" * 256 + "]",
    "error_on_third_line": '{\n  "a": 1,\n  "b": tru\n}',
    "unquoted_key": "{a: 1}",
    "hexadecimal": "[0x10]",
}


@pytest.mark.parametrize("name", sorted(JSON_ERRORS))
def test_strict_json_errors(name, run, golden):
    """CATCHES: accepting JSONC/JSON5 extensions in strict JSON, or reporting a different
    diagnostic text, line, column or exit status for invalid JSON."""
    assert outcome(_to_yaml(run, "data.json", JSON_ERRORS[name])) == golden(f"json_error_{name}")


JSONC_CASES = {
    "no_comments_stays_flow": '{"a": [1, 2,], "b": {"c": 3,},}',
    "line_and_block_comments": '// header\n{\n  /* key comment */\n  "a": 1, // trailing a\n  "b": [\n    1, // one\n    2\n  ]\n}\n// footer\n',
    "multiline_block_comment_stars": '/*\n * first line\n *   indented\n *\n */\n[1]',
    "fmt_comment_is_namespaced": '// fmt: skip\n{"a": 1}',
    "empty_containers_with_comments": '{\n  "obj": { /* inside obj */ },\n  "arr": [ // inside arr\n  ],\n  "list": [\n    [ /* inner empty */ ],\n    {}\n  ]\n}',
    "nested_block_layout": '// c\n{"outer": {"inner": [1, [2, 3], {"k": "v"}]}, "after": null}',
    "cr_only_comment_breaks": '// first\r// second\r[1, /* a\rb */ 2]',
    "separator_comment_breaks": '// first\u2028// second\u2029[1]',
    "crlf_comment_breaks": '// first\r\n/* a\r\nb */\r\n[1]',
    "unsafe_comment_characters": '// bell \u0007 del \u007f c1 \u0085 nbsp \u00a0 bom \ufeff nonchar \uffff end\n[1]',
    "string_with_comment_markers": '// c\n["// not a comment", "/* nor this */", "esc \\" // still string"]',
    "comment_between_key_and_value": '{"a" /* after key */ : /* before value */ 1}',
    "empty_comment": '//\n/**/\n[1]',
    "keys_quoted_in_block_layout": '// c\n{"plain": 1, "has space": 2, "null": 3, "caf\\u00e9": 4, "x-y_z9": 5, "9": 6}',
    "root_scalar_with_comment": '// note\n"value"',
    "nesting_markers_in_comments_ignored": "/* [[[[ */ // {{{{\n" + "[" * 40 + "]" * 40,
}


@pytest.mark.parametrize("name", sorted(JSONC_CASES))
def test_jsonc_projection(name, run, golden):
    """CATCHES: dropping or misplacing JSONC comments, not prefixing `fmt:` comments with
    `[jsonc]`, mishandling CR-only/U+2028 comment line breaks, failing to escape characters
    YAML forbids in comments, or wrong block-layout indentation."""
    assert outcome(_to_yaml(run, "data.jsonc", JSONC_CASES[name])) == golden(f"jsonc_{name}")


JSONC_ERRORS = {
    "single_quotes_rejected": "['x']",
    "unquoted_key_rejected": "{a: 1}",
    "hexadecimal_rejected": "[0x1]",
    "unary_plus_rejected": "[+1]",
    "nesting_too_deep": "// deep\n" + "[" * 257 + "]" * 257,
    "empty_input": "",
    "comment_only": "// only\n",
    "unterminated_block_comment": "[1] /* open",
}


@pytest.mark.parametrize("name", sorted(JSONC_ERRORS))
def test_jsonc_errors(name, run, golden):
    """CATCHES: accepting JSON5-only syntax in JSONC, a wrong nesting limit, or a wrong
    diagnostic/exit status for invalid JSONC input."""
    assert outcome(_to_yaml(run, "data.jsonc", JSONC_ERRORS[name])) == golden(f"jsonc_error_{name}")


JSONL_CASES = {
    "records_get_document_markers": '{"a": 1}\n[1, 2]\n"text"\nnull\n',
    "crlf_records": '{"a": 1}\r\n{"b": 2}\r\n',
    "no_final_newline": '{"a": 1}\n{"b": 2}',
    "single_record": '{"only": true}\n',
    "wide_record_expands": '{"key": "' + "value " * 20 + '", "n": 1}\n{"short": 1}\n',
}


@pytest.mark.parametrize("name", sorted(JSONL_CASES))
def test_json_lines_projection(name, run, golden):
    """CATCHES: missing `---` before each record (including the first), merging records,
    or mishandling CRLF and a missing final newline in JSON Lines."""
    assert outcome(_to_yaml(run, "data.jsonl", JSONL_CASES[name])) == golden(f"jsonl_{name}")


JSONL_ERRORS = {
    "empty_input": "",
    "blank_record_in_middle": '{"a": 1}\n\n{"b": 2}\n',
    "whitespace_record": '{"a": 1}\n   \n',
    "invalid_second_record": '{"a": 1}\n{"b": }\n',
    "multiline_record": '{\n"a": 1}\n',
    "comment_record": '// c\n{"a": 1}\n',
    "nesting_on_second_record": '[1]\n' + "[" * 257 + "]" * 257 + "\n",
}


@pytest.mark.parametrize("name", sorted(JSONL_ERRORS))
def test_json_lines_errors(name, run, golden):
    """CATCHES: accepting blank or multi-line JSON Lines records, or reporting errors on the
    wrong line (the record's physical line must be used)."""
    assert outcome(_to_yaml(run, "data.jsonl", JSONL_ERRORS[name])) == golden(f"jsonl_error_{name}")


def test_ndjson_suffix_uses_json_lines(run, golden):
    """CATCHES: treating `.ndjson` as anything but JSON Lines (it must emit a marker per record)."""
    assert outcome(_to_yaml(run, "events.ndjson", '{"e": 1}\n{"e": 2}\n')) == golden("ndjson")


def test_uppercase_json_suffix(run, golden):
    """CATCHES: case-sensitive suffix matching; `DATA.JSONC` must select JSONC and keep comments."""
    assert outcome(_to_yaml(run, "DATA.JSONC", '// c\n{"a": 1,}')) == golden("uppercase_jsonc")


def test_unsupported_suffix_is_rejected(run, golden):
    """CATCHES: guessing a grammar for a non-JSON suffix instead of failing with the documented
    list of accepted extensions."""
    assert outcome(_to_yaml(run, "data.yaml", '{"a": 1}')) == golden("unsupported_suffix")


def test_missing_suffix_is_rejected(run, golden):
    """CATCHES: accepting a path with no extension for JSON-to-YAML projection."""
    assert outcome(_to_yaml(run, "data", '{"a": 1}')) == golden("missing_suffix")


def test_utf16_bom_is_rejected(run, golden):
    """CATCHES: attempting to decode UTF-16 input instead of rejecting its byte order mark."""
    assert outcome(_to_yaml(run, "data.json", '\ufeff{"a": 1}'.encode("utf-16-le"))) == golden("utf16_bom")


def test_invalid_utf8_is_rejected(run, golden):
    """CATCHES: lossy decoding of invalid UTF-8 stdin instead of a precise error."""
    assert outcome(_to_yaml(run, "data.json", b'{"a": "\xff"}')) == golden("invalid_utf8")


def test_json_template_delimiters_are_data(run, golden):
    """CATCHES: treating `{{ }}` text inside projected JSON strings as active template syntax,
    which would preserve or mangle the generated flow collection."""
    text = '{"greeting": "{{ name }}", "list": ["{% if %}", "<% x %>"]}'
    assert outcome(_to_yaml(run, "data.json", text)) == golden("template_text_is_data")


def test_json_fmt_text_in_strings_is_data(run, golden):
    """CATCHES: scanning projected JSON strings for formatter directives or Markdown."""
    text = '{"a": "# fmt: skip", "b": "<!-- fmt: off -->", "c": "**bold**  text"}'
    assert outcome(_to_yaml(run, "data.json", text)) == golden("fmt_text_is_data")


def test_to_yaml_respects_prose_width(run, golden):
    """CATCHES: ignoring `--prose-width` for long projected prose strings, which the YAML
    formatter folds into a block scalar at that width."""
    text = '{"text": "' + " ".join(["This sentence is plain prose."] * 6) + '"}'
    assert outcome(_to_yaml(run, "data.json", text, "--prose-width", "40")) == golden("prose_width")


def test_to_yaml_uses_config_compact(run, workdir, golden):
    """CATCHES: ignoring `[format] compact = true` from the discovered yamark.toml in to-yaml."""
    (workdir / "yamark.toml").write_text("[format]\ncompact = true\n")
    text = '// c\n{"a": [1, 2], "b": {"c": "d"}}'
    assert outcome(_to_yaml(run, "data.jsonc", text)) == golden("config_compact")


def test_to_yaml_rejects_invalid_config(run, workdir, golden):
    """CATCHES: silently ignoring an invalid discovered yamark.toml during to-yaml."""
    (workdir / "yamark.toml").write_text("[format]\nbogus = 1\n")
    observed = outcome(_to_yaml(run, "data.json", '{"a": 1}'))
    observed["stderr"] = observed["stderr"].replace(str(workdir), "<workdir>")
    assert observed == golden("config_invalid")


JSONC_MORE = {
    "escapes_while_normalizing_cr": '{"a": "x\\"y", "b": "back\\\\slash"}\r\n// c\r\n',
    "lf_comment_while_normalizing_cr": '// c\n[1, /* x */ 2]\r\n',
    "root_empty_array_after_comment": "// c\n[]",
    "root_empty_object_after_comment": "// c\n{}",
    "root_empty_array_inner_comment": "[ // inside\n]",
    "comment_after_value_same_line": '{"a": 1 /* after */, "b": [2 /* in */]}',
    "comments_in_every_position": '/* a */ { /* b */ "k" /* c */ : /* d */ [ /* e */ 1 /* f */ , /* g */ 2 /* h */ ] /* i */ } /* j */',
    "root_string_escape_then_cr": '"abc\\\\"\r',
}


@pytest.mark.parametrize("name", sorted(JSONC_MORE))
def test_jsonc_more_shapes(name, run, golden):
    """CATCHES: mis-scanning string escapes or LF-terminated comments while CR/separator
    normalisation is active, wrong root `[]`/`{}` emission after comments, or dropped or
    reordered comments around keys, colons, items and closers."""
    assert outcome(_to_yaml(run, "data.jsonc", JSONC_MORE[name])) == golden(f"jsonc_more_{name}")
