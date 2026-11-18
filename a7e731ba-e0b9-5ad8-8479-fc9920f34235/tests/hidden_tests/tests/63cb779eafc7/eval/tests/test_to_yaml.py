"""`yamark to-yaml`: JSON-family projection to YAML, dialect selection, options and errors."""

import pytest

from conftest import assert_golden, transcript

CASES = {
    # strict JSON
    "json_object": ("json", '{"name": "yamark", "version": 1, "tags": ["a", "b"], "nested": {"x": null}}'),
    "json_scalars": ("json", '[true, false, null, 0, -1.5e+10, 1E-3, "", "plain"]'),
    "json_number_spelling": ("json", '{"a": 1.0, "b": 1e3, "c": -0, "d": 12345678901234567890123}'),
    "json_string_escapes": ("json", r'{"s": "tab\tnl\ncr\rq\"bs\\sl\/u\u00e9\u0001\u007f\u0085\u00a0\u2028\uffff"}'),
    "json_surrogate_pair": ("json", r'["\ud83d\ude00"]'),
    "json_keys_needing_quotes": ("json", '{"null": 1, "True": 2, "1st": 3, "with space": 4, "dash-ok": 5, "_u": 6, '
                                         '"a:b": 7, "": 8, "é": 9}'),
    "json_duplicate_keys": ("json", '{"a": 1, "a": 2, "b": {"c": 1, "c": 2}}'),
    "json_empty_containers": ("json", '{"a": [], "b": {}, "c": [[], {}]}'),
    "json_root_scalar": ("json", '"just a string"'),
    "json_root_number": ("json", '42'),
    "json_long_string": ("json", '{"description": "This is a long prose string that should be represented as a '
                                 'folded block scalar so that readers can review it comfortably."}'),
    "json_multiline_string": ("json", '{"text": "line one\\nline two\\n"}'),
    "json_template_text": ("json", '{"a": "{{ not a template }}", "b": ["{% x %}", "<% y %>"]}'),
    "json_wide_array": ("json", '{"items": ["alpha-value-one", "alpha-value-two", "alpha-value-three", '
                                '"alpha-value-four", "alpha-value-five"]}'),
    "json_whitespace_layout": ("json", '\n\n  {\n"a"\n:\n1\n}\n\n'),
    "json_crlf": ("json", '{\r\n  "a": 1,\r\n  "b": [1, 2]\r\n}\r\n'),
    # JSON errors
    "json_trailing_comma": ("json", '[1, 2,]'),
    "json_comment_rejected": ("json", '// c\n{"a": 1}'),
    "json_single_quotes_rejected": ("json", "{'a': 1}"),
    "json_unquoted_key_rejected": ("json", '{a: 1}'),
    "json_empty_input": ("json", ''),
    "json_whitespace_input": ("json", '  \n'),
    "json_two_values": ("json", '1 2'),
    "json_unterminated_string": ("json", '{"a": "b'),
    "json_lone_surrogate": ("json", r'"\ud800"'),
    "json_bad_escape": ("json", r'"\q"'),
    "json_hex_rejected": ("json", '0x10'),
    "json_plus_rejected": ("json", '+1'),
    "json_too_deep": ("json", "[" * 257 + "]" * 257),
    "json_max_depth": ("json", "[" * 256 + "]" * 256),
    "json_deep_on_line_three": ("json", "\n\n" + "{\"a\":" * 257 + "1" + "}" * 257),
    "json_brackets_in_strings_not_nesting": ("json", '["' + "[" * 300 + '"]'),
    # JSONC
    "jsonc_comments": ("jsonc", '// leading\n{\n  // before a\n  "a": 1, // after a\n  /* block\n   * more */\n'
                                '  "b": [1, /* in array */ 2,],\n  "c": {}, // empty\n  "d": [] /* empty array */\n}\n'
                                '// trailing\n'),
    "jsonc_no_comments": ("jsonc", '{"a": [1, 2,], "b": {"c": true,},}'),
    "jsonc_nested_comments": ("jsonc", '{\n  "outer": {\n    // inner comment\n    "x": [\n      // first\n'
                                       '      {"y": 1},\n      [2]\n    ]\n  }\n}\n'),
    "jsonc_empty_container_comments": ("jsonc", '{"a": [ /* inside */ ], "b": { // inside obj\n}}'),
    "jsonc_fmt_comment_marked": ("jsonc", '// fmt: skip\n{"a": 1}\n'),
    "jsonc_comment_control_chars": ("jsonc", '// bell \u0007 del \u007f nel \u0085 ls \u2028 x\n1\n'),
    "jsonc_block_comment_control_chars": ("jsonc", '/* bell \u0007 del \u007f nel \u0085 bom \ufffe x */ 1\n'),
    "json5_comment_control_chars": ("json5", '/* bell \u0007 c1 \u0090 nonchar \uffff */ [1] // tab\there\n'),
    "jsonc_cr_line_comment": ("jsonc", '// first\r1\r'),
    "jsonc_crlf_comments": ("jsonc", '// first\r\n{"a": 1 /* x\r\n y */}\r\n'),
    "jsonc_line_separator_in_comment": ("jsonc", '/* a\u2029b */ [1]'),
    "jsonc_root_scalar_comment": ("jsonc", '/* c */ "s" // t\n'),
    "jsonc_quoted_key_comment": ("jsonc", '{\n  "with space": 1, // c\n  "null": 2\n}'),
    "jsonc_string_with_slashes": ("jsonc", '{"url": "http://example.com/*x*/"} // real\n'),
    "jsonc_unquoted_key_rejected": ("jsonc", '{a: 1}'),
    "jsonc_single_quote_rejected": ("jsonc", "['a']"),
    "jsonc_hex_rejected": ("jsonc", '[0x1]'),
    "jsonc_empty": ("jsonc", '// only a comment\n'),
    "jsonc_too_deep": ("jsonc", "/* [ */" + "[" * 257 + "]" * 257),
    "jsonc_escaped_quote_in_string": ("jsonc", '["a\\"// not comment", 1] // c\n'),
    # JSON5
    "json5_values": ("json5", '[1, null, true, false, "s", \'single\', -0, 0.0]'),
    "json5_numbers": ("json5", '{n: +1, m: -0x1F, h: 0X1f, i: Infinity, j: -Infinity, k: NaN, l: -NaN, p: .5, '
                               'q: 5., r: 1e3, s: -.5e-2, t: +.5, u: +Infinity, v: 0xABCDEF}'),
    "json5_big_negative_hex": ("json5", '[-0xFFFFFFFFFFFFFFFFFFFF, -0x0, 0x0]'),
    "json5_escapes": ("json5", "{c: 'it\\'s', d: \"q\\\"\\\\\\/\\b\\f\\n\\r\\t\\v\\0\", e: '\\x41\\u0042\\uD83D\\uDE00',"
                               " f: '\\a\\c\\e'}"),
    "json5_line_continuation": ("json5", "['a\\\nb', 'c\\\r\nd', 'e\\\rf', 'g\\\u2028h']"),
    "json5_reserved_word_keys": ("json5", '{null: 1, true: 2, Infinity: 3, NaN: 4, false: 5}'),
    "json5_identifier_keys": ("json5", '{$dollar: 1, _under: 2, caf\u00e9: 3, a\\u0062c: 4, \\u0061x: 5}'),
    "json5_comments": ("json5", '// lead\n{\n  // c1\n  a: 1, /* c2 */\n  b: [ // c3\n    1, // c4\n    2,\n  ], // c5\n'
                                '  /* multi\n   * line */\n  c: {}, // c6\n}\n// tail\n'),
    "json5_comment_in_empty_containers": ("json5", '{a: [ /* x */ ], b: { // y\n}, c: [\n// z\n]}'),
    "json5_comment_before_unary": ("json5", '[- /* c */ 1, + // d\n 2]'),
    "json5_block_comment_root": ("json5", '/* only */ 7'),
    "json5_trailing_commas": ("json5", '{a: [1, 2,], b: {c: 3,},}'),
    "json5_line_separators": ("json5", '[1,\u20282,\u20293]'),
    "json5_line_separator_in_string": ("json5", '["a\u2028b", \'c\u2029d\']'),
    "json5_line_separator_in_comments": ("json5", '// a\u2028[1, /* b\u2029c */ 2]'),
    "json5_whitespace_forms": ("json5", '\ufeff\t\u000b\u000c\u00a0[1,\u30002]'),
    "json5_nested_mixed": ("json5", "{list: [{a: 1}, [2, [3]], 'x'], obj: {deep: {deeper: {}}}}"),
    "json5_comment_empty_object_root": ("json5", '// c\n{}'),
    "json5_comment_empty_array_root": ("json5", '[] // c\n'),
    "json5_comment_nested_arrays": ("json5", '// c\n[[], {}, [1, [2, {a: []}]], {b: {}}, /* d */ 3]'),
    "json5_comment_object_members": ("json5", '{\n  a: [], // empty\n  b: [1, [2]],\n  c: {d: {e: 1}} /* end */\n}'),
    "json5_comment_last_item_no_comma": ("json5", '[\n  1, // one\n  2 // two\n]'),
    "json5_comment_object_last_member": ("json5", '{a: 1, // one\n b: 2 // two\n}'),
    "json5_block_comment_star_lines": ("json5", '/**\n * Doc comment\n *\n * more\n */\n{a: 1}'),
    "json5_crlf_comments": ("json5", '// first\r\n{a: 1, // x\r\n b: 2}\r\n'),
    "json5_cr_comments": ("json5", '// first\r{a: 1}\r'),
    "json5_fmt_comment_marked": ("json5", '// fmt: off\n[1]'),
    # JSON5 errors
    "json5_identifier_escape_not_u": ("json5", '{a\\x41: 1}'),
    "json5_identifier_escape_bad_hex": ("json5", '{a\\u00G1: 1}'),
    "json5_identifier_escape_surrogate": ("json5", '{a\\uD800: 1}'),
    "json5_bad_low_surrogate_hex": ("json5", '"\\uD800\\uZZZZ"'),
    "json5_unterminated_after_line_separator": ("json5", '"a\u2028b'),
    "json5_error_after_string_line_separator": ("json5", '["a\u2028b", @]'),
    "json5_legacy_octal": ("json5", '"\\1"'),
    "json5_legacy_zero_digit": ("json5", '"\\01"'),
    "json5_nel_whitespace": ("json5", '\u0085 1'),
    "json5_nel_after_value": ("json5", '[1]\u0085'),
    "json5_bad_identifier_escape": ("json5", '{\\u0030a: 1}'),
    "json5_bad_identifier_part_escape": ("json5", '{a\\u0020b: 1}'),
    "json5_double_unary": ("json5", '+-1'),
    "json5_unary_string": ("json5", '[-"a"]'),
    "json5_lone_high_surrogate": ("json5", '"\\uD800"'),
    "json5_lone_low_surrogate": ("json5", '"\\uDC00"'),
    "json5_bad_low_surrogate": ("json5", '"\\uD800\\u0041"'),
    "json5_bad_hex_escape": ("json5", '"\\xZZ"'),
    "json5_short_unicode_escape": ("json5", '"\\u12"'),
    "json5_numeric_key": ("json5", '{1: 2}'),
    "json5_double_comma": ("json5", '[1,,]'),
    "json5_bare_identifier_value": ("json5", '[ident]'),
    "json5_unterminated": ("json5", '{a: 1'),
    "json5_empty": ("json5", ''),
    "json5_too_deep": ("json5", "[" * 257 + "]" * 257),
    "json5_error_after_line_separator": ("json5", '[1,\u2028\u2028 @]'),
    "json5_unterminated_escape": ("json5", "'abc\\"),
    # JSON Lines
    "jsonl_records": ("jsonl", '{"a": 1}\n[1, 2]\n"s"\n3\nnull\n'),
    "jsonl_no_trailing_newline": ("jsonl", '{"a": 1}\n{"b": 2}'),
    "jsonl_crlf": ("jsonl", '{"a": 1}\r\n{"b": [1, 2]}\r\n'),
    "jsonl_long_record": ("jsonl", '{"items": ["alpha-value-one", "alpha-value-two", "alpha-value-three", '
                                   '"alpha-value-four", "alpha-value-five"]}\n{"x": 1}\n'),
    "jsonl_blank_record": ("jsonl", '{"a": 1}\n\n{"b": 2}\n'),
    "jsonl_whitespace_record": ("jsonl", '{"a": 1}\n   \n'),
    "jsonl_empty": ("jsonl", ''),
    "jsonl_invalid_second_record": ("jsonl", '{"a": 1}\n{"b": }\n'),
    "jsonl_multiline_record": ("jsonl", '{"a":\n1}\n'),
    "jsonl_too_deep_on_line_two": ("jsonl", '1\n' + "[" * 257 + "]" * 257 + "\n"),
    "ndjson_records": ("ndjson", '{"event": "start", "ok": true}\n{"event": "stop", "ok": false}\n'),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_to_yaml_projection(name, run):
    """CATCHES: wrong YAML projection of JSON-family input (key order, duplicate keys, number spellings, string
    escaping, quoting of keys, comment placement, JSON5 normalization of hex/Infinity/NaN/decimal points, JSONL
    document markers) or wrong dialect-specific errors and their `path:line:column` locations."""
    ext, text = CASES[name]
    result = run(["to-yaml", "--stdin-file-path", f"data.{ext}"], input=text)
    assert_golden(transcript(result), __file__, f"case_{name}")


@pytest.mark.parametrize("ext", ["json", "jsonc", "json5", "jsonl", "ndjson", "JSON", "Json5", "JSONL", "NDJSON"])
def test_dialect_suffixes(ext, run):
    """CATCHES: rejecting any documented JSON-family suffix (matched case-insensitively)."""
    result = run(["to-yaml", "--stdin-file-path", f"in.{ext}"], input='{"a": [1, 2]}\n')
    expected = b"---\n{a: [1, 2]}\n" if ext.lower() in ("jsonl", "ndjson") else b"{a: [1, 2]}\n"
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, b"")


@pytest.mark.parametrize("path", ["data.yaml", "data.md", "data", "data.txt", "data.json.bak"])
def test_unsupported_suffix(path, run):
    """CATCHES: projecting input whose path hint is not a JSON-family suffix instead of failing with exit 1 and
    the documented requirement message."""
    result = run(["to-yaml", "--stdin-file-path", path], input='{"a": 1}')
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == (f"{path}:1:1: error: JSON-to-YAML projection requires a .json, .jsonc, .json5, "
                                      ".jsonl, or .ndjson source path\n")


def test_dialects_differ_for_same_input(run):
    """CATCHES: using one lenient parser for every suffix: JSON5 syntax is rejected by .json and .jsonc."""
    text = "{a: 1, // c\n b: 'x',}"
    results = {ext: run(["to-yaml", "--stdin-file-path", f"d.{ext}"], input=text) for ext in ("json", "jsonc", "json5")}
    assert results["json5"].stdout == b"a: 1\n# c\nb: x\n"
    assert results["json"].returncode == 1
    assert results["jsonc"].returncode == 1
    assert results["json"].stderr.startswith(b"d.json:1:2: error: invalid JSON: ")
    assert results["jsonc"].stderr.startswith(b"d.jsonc:1:2: error: invalid JSONC: ")


def test_path_is_not_read_or_written(run, workdir):
    """CATCHES: reading the path hint from disk instead of stdin or writing output to it."""
    (workdir / "d.json").write_text('{"disk": true}')
    result = run(["to-yaml", "--stdin-file-path", "d.json"], input='{"stdin": true}')
    assert (result.returncode, result.stdout) == (0, b"{stdin: true}\n")
    assert (workdir / "d.json").read_text() == '{"disk": true}'


def test_invalid_utf8_input(run):
    """CATCHES: lossy decoding of non-UTF-8 JSON input instead of failing with the byte index of the error."""
    result = run(["to-yaml", "--stdin-file-path", "d.json"], input=b'["\xe9"]')
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"d.json:1:1: error: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 2\n")


def test_utf16_input(run):
    """CATCHES: decoding UTF-16 JSON instead of rejecting the UTF-16 byte order mark."""
    result = run(["to-yaml", "--stdin-file-path", "d.json"], input=b'\xff\xfe[\x00]\x00')
    assert (result.returncode, result.stderr) == (1, b"d.json:1:1: error: unsupported encoding: UTF-16 BOM\n")


SAMPLE = ('{"title": "Formatter snapshots", "description": "This is a long prose string that should be represented '
          'as a folded block scalar so diffs reveal changes.", "tags": ["yaml", "snapshots", "regression-tests"], '
          '"nested": {"list": [1, 2], "map": {"k": "v"}}}')


@pytest.mark.parametrize("name,args", [
    ("defaults", []),
    ("line_width_30", ["--line-width", "30"]),
    ("prose_width_30", ["--prose-width", "30"]),
    ("indent_width_4", ["--indent-width", "4"]),
    ("compact", ["--compact"]),
    ("compact_wide", ["--compact", "--line-width", "200"]),
])
def test_to_yaml_layout_options(name, args, run):
    """CATCHES: to-yaml ignoring --line-width, --prose-width, --indent-width or --compact."""
    result = run(["to-yaml", "--stdin-file-path", "d.json", *args], input=SAMPLE)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"options_{name}")


@pytest.mark.parametrize("args", [["--line-width", "0"], ["--prose-width", "x"], ["--indent-width", ""]],
                         ids=["line", "prose", "indent"])
def test_to_yaml_invalid_widths(args, run):
    """CATCHES: accepting zero or non-numeric widths for to-yaml."""
    result = run(["to-yaml", "--stdin-file-path", "d.json", *args], input="1")
    assert (result.returncode, result.stdout) == (2, b"")
    assert_golden(transcript(result), __file__, "invalid_" + args[0].strip("-"))


def test_to_yaml_uses_config_compact(run, workdir):
    """CATCHES: to-yaml ignoring the discovered yamark.toml [format].compact setting."""
    (workdir / "yamark.toml").write_text("[format]\ncompact = true\n")
    result = run(["to-yaml", "--stdin-file-path", "d.json"], input='{"a": {"b": [1, 2]}}')
    assert (result.returncode, result.stdout, result.stderr) == (0, b"{a: {b: [1, 2]}}\n", b"")


def test_to_yaml_ignores_config_template_delimiters(run, workdir):
    """CATCHES: treating delimiter text in JSON strings as YAML templates (projection clears template
    delimiters even when the config adds some), which would preserve quotes/flow style."""
    (workdir / "yamark.toml").write_text("[template]\nadd_delimiters = [{open=\"<<\", close=\">>\"}]\n")
    result = run(["to-yaml", "--stdin-file-path", "d.json"], input='{"a": "<< x >>", "b": "w {{ v }}"}')
    assert (result.returncode, result.stdout) == (0, b"{a: << x >>, b: \"w {{ v }}\"}\n")


def test_to_yaml_explicit_config(run, workdir):
    """CATCHES: to-yaml not honouring --config, or not reporting an invalid explicit config."""
    (workdir / "good.toml").write_text("[format]\ncompact = true\n")
    (workdir / "bad.toml").write_text("bogus = 1\n")
    good = run(["to-yaml", "--stdin-file-path", "d.json", "--config", "good.toml"], input='{"a": {"b": 1}}')
    bad = run(["to-yaml", "--stdin-file-path", "d.json", "--config", "bad.toml"], input='{"a": {"b": 1}}')
    assert (good.returncode, good.stdout) == (0, b"{a: {b: 1}}\n")
    assert (bad.returncode, bad.stdout, bad.stderr) == (1, b"", b"bad.toml:1:1: error: unknown config key: bogus\n")


def test_to_yaml_does_not_run_embedded_formatters(run, workdir):
    """CATCHES: dispatching configured embedded formatters for projected YAML (projection never runs them)."""
    (workdir / "yamark.toml").write_text(
        "[embedded.python]\nformatter = { command = [\"false\", \"{path}\"], path_suffix = \".py\" }\n")
    result = run(["to-yaml", "--stdin-file-path", "d.jsonc"], input='// fmt: python\n{"code": "x=1\\n"}\n')
    assert_golden(transcript(result), __file__, "no_embedded_formatters")


def test_to_yaml_is_not_format(run, workdir):
    """CATCHES: `yamark format` rewriting JSON files; JSON-family files are skipped in path mode."""
    (workdir / "d.json").write_text('{"a":1}')
    result = run(["format", "d.json"])
    assert (result.returncode, result.stdout) == (0, b"1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n")
    assert (workdir / "d.json").read_text() == '{"a":1}'
