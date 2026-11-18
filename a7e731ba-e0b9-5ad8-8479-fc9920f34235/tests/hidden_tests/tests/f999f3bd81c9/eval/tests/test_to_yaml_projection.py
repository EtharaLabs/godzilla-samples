"""JSON-family to YAML projection (`yamark to-yaml`).

Pins the per-dialect grammar (.json, .jsonc, .json5, .jsonl/.ndjson), comment
projection, string escaping and quoting, number normalisation, layout options,
configuration, and the exact line:column of every error class.
"""

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)

BIG_JSON = (
    '{"name": "example", "tags": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"], '
    '"nested": {"inner": {"x": 1, "y": [1, 2, {"z": true}]}, "list": [{"a": 1}, {"b": 2}]}, '
    '"s": "multi\\nline\\n"}\n'
)
PROSE = '{"a": "' + "lorem ipsum " * 15 + 'end"}\n'
JSONC_COMMENTED = (
    '/* c */ {"a": [1, 2, 3], "b": {"x": 1, "y": 2}, "c": [{"p": 1}, {"q": 2}], "d": [[1, 2], [3]]}\n'
)
JSON5_COMMENTED = "// c\n{a: [1, 2, 3], b: {x: 1, y: 2}, c: [{p: 1}, {q: 2}], d: [[1, 2], [3]]}\n"
COMPACT_YAML = b"# c\na: [1, 2, 3]\nb: {x: 1, y: 2}\nc: [{p: 1}, {q: 2}]\nd: [[1, 2], [3]]\n"


def project(run, path, stdin, *extra):
    return run(["to-yaml", "--stdin-file-path", path, *extra], input=stdin)


# --- strict JSON -----------------------------------------------------------


def test_json_booleans_null_and_nested_collections(run, workdir):
    """CATCHES: an implementation that renders JSON true/false/null as YAML strings or other spellings (True, ~), drops empty nested [] / {} values, or expands a mapping that fits the default 80-column line into block style for every nested collection."""
    stdin = (
        '{\n  "t": true,\n  "f": false,\n  "n": null,\n'
        '  "list": [true, false, null, 1, -2.5e3, "s"],\n'
        '  "obj": {"x": {"y": [[], {}]}}\n}\n'
    )
    result = project(run, "input.json", stdin)
    assert result.stdout == (
        b"t: true\nf: false\nn: null\nlist: [true, false, null, 1, -2.5e3, s]\nobj: {x: {y: [[], {}]}}\n"
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_strings_that_yaml_would_misread_are_quoted(run, workdir):
    """CATCHES: an implementation that emits strings like "true", "null", "~", "123", "0x1F", ".inf", "#x", "- a", " lead", "trail " or indicator-led text as plain scalars (changing their YAML type or meaning), or that needlessly quotes YAML-1.1-only words like yes/no/on, dates, and "?x"."""
    stdin = (
        '["true", "false", "null", "Null", "~", "123", "1.5", "0x1F", "-", "#x", "- a", ": b", " lead", '
        '"trail ", "", "a: b", "a #b", "yes", "no", "on", "@x", "`x", "!x", "&x", "*x", "|x", ">x", "%x", '
        '"[x", "]x", "{x", "}x", ",x", "?x", "\'x", "\\"x", ".inf", "1e3", "2001-01-01"]\n'
    )
    result = project(run, "input.json", stdin)
    assert result.stdout == (RES / "json_string_quoting.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_control_characters_and_line_separators_use_yaml_escapes(run, workdir):
    """CATCHES: an implementation that writes decoded control characters raw, uses \\u escapes where YAML has short forms (\\0 \\a \\b \\e \\N \\_ \\L \\P), leaves raw U+2028/U+0085 unescaped in output, or fails to quote keys that contain control characters or are reserved words, digits, or empty (while a key like `a b` stays plain)."""
    stdin = (
        '{"\\u0000k": "\\b\\f\\t\\r\\u0000\\u0007\\u001b\\u0085\\u00a0\\u2028\\u2029\\u007f\\u009f'
        '\\ufffe\\uffff\\u0001\\u001f\\"\\\\\\/", "k\\tk": 2, "true": 3, "1": 4, "a b": 5, '
        '"": "x\u2028y\u0085z"}\n'
    )
    result = project(run, "input.json", stdin)
    assert result.stdout.decode() == (
        '"\\0k": "\\b\\f\\t\\r\\0\\a\\e\\N\\_\\L\\P\\x7F\\x9F\\uFFFE\\uFFFF\\u0001\\u001F\\"\\\\/"\n'
        '"k\\tk": 2\n'
        '"true": 3\n'
        '"1": 4\n'
        "a b: 5\n"
        '"": "x\\Ly\\Nz"\n'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_multiline_strings_become_literal_blocks_with_exact_chomping(run, workdir):
    """CATCHES: an implementation that chooses the wrong chomping indicator (|- for no final newline, |+ for several), omits the explicit indentation indicator (|2-) when the first line starts with spaces, or strips trailing spaces and tabs inside literal block lines."""
    stdin = '["first\\nsecond", "  indented\\nline", "trailing \\nspace", "tab\\tin\\nline", "end\\n\\n\\n"]\n'
    result = project(run, "input.json", stdin, "--line-width", "20")
    assert result.stdout == (RES / "json_literal_blocks.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_line_width_expands_only_collections_that_do_not_fit(run, workdir):
    """CATCHES: an implementation that ignores --line-width when choosing flow versus block layout, expands every nested collection once the root is too wide (instead of keeping `inner: {...}` flow when it fits), or keeps a multi-line string escaped instead of switching to a `|` literal block."""
    result = project(run, "input.json", BIG_JSON, "--line-width", "40")
    assert result.stdout == (RES / "json_line_width_40.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_long_string_folds_at_prose_width(run, workdir):
    """CATCHES: an implementation that folds long strings at --line-width (80) instead of --prose-width, or that emits a folded block without the strip chomping indicator (>-)."""
    result = project(run, "input.json", PROSE, "--prose-width", "30")
    assert result.stdout == (RES / "json_prose_width_30.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_prose_width_wider_than_line_width_keeps_one_plain_line(run, workdir):
    """CATCHES: an implementation that folds or quotes a long string because it exceeds --line-width even though --prose-width allows it on one line."""
    result = project(run, "input.json", PROSE, "--prose-width", "200", "--line-width", "60")
    assert result.stdout == b"a: " + b"lorem ipsum " * 15 + b"end\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        pytest.param(
            '{"s": "\\ud800"}\n',
            "input.json:1:8: error: invalid JSON: Invalid unicode escape sequence. "
            "'d800 (unpaired high surrogate)' is not a valid UTF8 character\n",
            id="lone-high-surrogate",
        ),
        pytest.param(
            '{\n  "a": [\n' + "[" * 300 + "]" * 300 + "]}\n",
            "input.json:3:255: error: invalid JSON: nesting exceeds 256 levels\n",
            id="nesting-on-third-line",
        ),
        pytest.param(
            '\ufeff{"a": 1}\n',
            "input.json:1:1: error: invalid JSON: Unexpected token\n",
            id="utf8-bom",
        ),
        pytest.param(
            "\ufeff{}".encode("utf-16-le"),
            "input.json:1:1: error: unsupported encoding: UTF-16 BOM\n",
            id="utf16-bom",
        ),
        pytest.param(
            b'{"a": "\xff"}',
            "input.json:1:1: error: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 7\n",
            id="invalid-utf8",
        ),
        pytest.param(
            '{"a": 1} // c\n',
            "input.json:1:10: error: invalid JSON: Comments are not allowed\n",
            id="comment",
        ),
    ],
)
def test_json_rejects_invalid_input_with_position(run, workdir, stdin, stderr):
    """CATCHES: an implementation that accepts lone surrogate escapes, a UTF-8 BOM, or comments in strict .json; counts nesting columns from the start of input instead of the current line; or reports encoding errors with a different message or position."""
    result = project(run, "input.json", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


# --- JSONC -----------------------------------------------------------------


def test_jsonc_without_comments_accepts_trailing_commas_and_stays_flow(run, workdir):
    """CATCHES: an implementation that rejects JSONC trailing commas, or that switches comment-free JSONC to the line-per-entry block layout used for commented input."""
    result = project(run, "input.jsonc", '{"a": [1, 2,], "b": true,}\n')
    assert result.stdout == b"{a: [1, 2], b: true}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_crlf_comments_and_comment_markers_inside_strings(run, workdir):
    """CATCHES: an implementation that leaves carriage returns in projected comments, keeps the leading `*` of block-comment continuation lines, drops the empty last line of a multi-line block comment, or treats `//` inside a string (after an escaped quote) as a comment."""
    stdin = (
        '{\r\n  // c1\r\n  "a": 1, /* c2\r\n   * c3\r\n   */\r\n'
        '  "s": "x // y \\" z"\r\n}\r\n'
    )
    result = project(run, "input.jsonc", stdin)
    assert result.stdout == b'# c1\na: 1\n# c2\n# c3\n#\ns: x // y " z\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_lone_carriage_return_ends_comment_lines(run, workdir):
    """CATCHES: an implementation that does not treat a lone CR as a line break inside JSONC line and block comments, so the following text is swallowed into the comment or emitted as a raw CR."""
    result = project(run, "input.jsonc", '// lone cr\r/* a\rb */ {"a": 1}\n')
    assert result.stdout == b"# lone cr\n# a\n# b\na: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_unicode_line_separators_end_comment_lines(run, workdir):
    """CATCHES: an implementation that keeps U+2028/U+2029 inside a JSONC comment instead of treating them as line breaks (ending a line comment and splitting a block comment)."""
    stdin = '{\n  // sep\u2028"a": 1,\n  /* p\u2029q */ "b": 2\n}\n'
    result = project(run, "input.jsonc", stdin)
    assert result.stdout == b"# sep\na: 1\n# p\n# q\nb: 2\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_next_line_splits_block_comment_and_string_separator_is_escaped(run, workdir):
    """CATCHES: an implementation that keeps U+0085 inside a projected block comment rather than splitting the comment there, that treats a raw U+2028 inside a JSONC string as a line break instead of escaping it as \\L, or that merges a preceding LF-terminated line comment into the next comment."""
    result = project(run, "input.jsonc", '// lead\n/* a\u0085b */ {"a": "x\u2028y"}\n')
    assert result.stdout == b'# lead\n# a\n# b\na: "x\\Ly"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_comments_inside_empty_containers_and_nested_sequences(run, workdir):
    """CATCHES: an implementation that loses comments written inside empty [] or {} values, or that renders nested sequences / mappings inside a sequence on the dash line instead of the bare `-` followed by an indented block."""
    stdin = (
        '{\n  "a": [ /* in empty */ ],\n  "b": { // in empty obj\n  },\n'
        '  "c": [[1, 2], [3]],\n  "d": [{"x": 1}, []]\n}\n'
    )
    result = project(run, "input.jsonc", stdin)
    assert result.stdout == (
        b"# in empty\na: []\n# in empty obj\nb: {}\nc:\n  -\n    - 1\n    - 2\n  -\n    - 3\n"
        b"d:\n  -\n    x: 1\n  - []\n"
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_block_mapping_quotes_reserved_and_non_identifier_keys(run, workdir):
    """CATCHES: an implementation that writes block mapping keys such as true, `a b` or `1x` unquoted in commented JSONC output, or attaches a trailing line comment to the wrong member."""
    stdin = '{\n  "true": 1, // c\n  "a b": 2,\n  "1x": 3\n}\n'
    result = project(run, "input.jsonc", stdin)
    assert result.stdout == b'"true": 1\n# c\n"a b": 2\n"1x": 3\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_comment_text_is_neutralized_and_escaped(run, workdir):
    """CATCHES: an implementation that copies a `fmt: off` comment verbatim (turning it into an active yamark directive instead of prefixing `[jsonc]`), or writes control characters, U+0085 and U+FFFE raw into YAML comments instead of \\xNN / \\uNNNN escapes."""
    stdin = '// fmt: off\n// bad \u0001 \u007f \u0085 \ufffe ok \U0001F600\n{"a": 1}\n'
    result = project(run, "input.jsonc", stdin)
    assert result.stdout.decode() == "# [jsonc] fmt: off\n# bad \\x01 \\x7F \\x85 \\uFFFE ok \U0001F600\na: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_empty_block_comment_and_comments_around_colon(run, workdir):
    """CATCHES: an implementation that drops an empty `/**/` comment (instead of emitting a bare `#`) or loses comments placed between a key, its colon, and its value."""
    result = project(run, "input.jsonc", '/**/\n{\n  "a" /* k */ : /* v */ 1\n}\n')
    assert result.stdout == b"#\n# k\n# v\na: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_comments_before_between_and_after_array_items(run, workdir):
    """CATCHES: an implementation that reorders array comments relative to items, or drops a comment that follows the last element before the closing bracket."""
    result = project(run, "input.jsonc", "[\n  // first\n  1,\n  2 // second\n  // end\n]\n")
    assert result.stdout == b"# first\n- 1\n- 2\n# second\n# end\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("path", "stdin", "expected"),
    [
        pytest.param("input.jsonc", "[ // c\n]\n", b"# c\n[]\n", id="jsonc-array"),
        pytest.param("input.jsonc", "{ /* c */ }\n", b"# c\n{}\n", id="jsonc-object"),
        pytest.param("input.json5", "[ // c\n]\n", b"# c\n[]\n", id="json5-array"),
        pytest.param("input.json5", "{ /* c */ }\n", b"# c\n{}\n", id="json5-object"),
        pytest.param("input.jsonc", '// lead\n"top"\n// trail\n', b"# lead\ntop\n# trail\n", id="jsonc-scalar"),
        pytest.param("input.json5", "/* only */ null\n", b"# only\nnull\n", id="json5-null"),
    ],
)
def test_commented_root_values(run, workdir, path, stdin, expected):
    """CATCHES: an implementation that drops the comment inside an empty root collection or around a root scalar, emits nothing / `null` instead of the explicit [] or {} after the comment, or rejects a commented scalar document."""
    result = project(run, path, stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("path", "stdin", "extra", "golden"),
    [
        pytest.param("input.jsonc", JSONC_COMMENTED, (), "jsonc_block.golden", id="jsonc-block"),
        pytest.param("input.jsonc", JSONC_COMMENTED, ("--compact",), "jsonc_compact.golden", id="jsonc-compact"),
        pytest.param("input.json5", JSON5_COMMENTED, ("--compact",), "json5_compact.golden", id="json5-compact"),
    ],
)
def test_commented_documents_are_block_unless_compact(run, workdir, path, stdin, extra, golden):
    """CATCHES: an implementation that keeps commented JSONC/JSON5 collections in flow style without --compact, or ignores --compact and leaves small eligible block collections expanded."""
    result = project(run, path, stdin, *extra)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_nesting_error_counts_crlf_as_one_line_break(run, workdir):
    """CATCHES: an implementation that counts CRLF as two line breaks (or none) when reporting the line:column of a JSONC nesting error, or that allows nesting deeper than 256 levels."""
    stdin = '\r\n{\r\n  "a": [\r\n' + "[" * 300 + "]" * 300 + "]}\r\n"
    result = project(run, "input.jsonc", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == "input.jsonc:4:255: error: invalid JSONC: nesting exceeds 256 levels\n"
    assert result.returncode == 1


# --- JSON5 -----------------------------------------------------------------


def test_json5_reserved_words_and_unicode_identifiers_as_keys(run, workdir):
    """CATCHES: an implementation that rejects true/false/null/Infinity/NaN as JSON5 keys or leaves true/false/null unquoted in YAML, or mishandles identifiers with $, _, ZWNJ, combining marks, Arabic-Indic digits, connector punctuation, modifier letters, and \\u escapes."""
    stdin = (
        "{true: 1, false: 2, null: 3, Infinity: 4, NaN: 5, $: 6, _: 7, ab$_1: 8, a\\u200cb: 9, "
        "c\\u0301: 10, d\\u0660: 11, e\\u203f: 12, \\u02b0x: 13, \\u0061\\u0062: 14}\n"
    )
    result = project(run, "input.json5", stdin)
    assert result.stdout == (RES / "json5_keys.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_unary_operator_with_comments_before_operand(run, workdir):
    """CATCHES: an implementation that rejects comments between a unary sign and its number, loses those comments, or keeps a unary plus in the YAML number."""
    result = project(run, "input.json5", "{a: - /* c */ 1, b: + // d\n 2}\n")
    assert result.stdout == b"# c\na: -1\n# d\nb: 2\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_number_spellings_are_normalized_for_yaml(run, workdir):
    """CATCHES: an implementation that keeps `0X`, leading/trailing decimal points, unary plus, Infinity/NaN, or a negative hexadecimal literal verbatim (which YAML would read as strings), negates NaN, or truncates large negative hexadecimal values instead of converting them exactly to decimal."""
    stdin = (
        "{a: -NaN, b: +Infinity, c: -0X1f, d: 0Xab, e: +.5, f: -5., g: .5e1, h: 5.E2, i: -0x0, "
        "j: 1e3, k: -.5e-2, l: 0x" + "F" * 40 + ", m: -0x" + "F" * 40 + "}\n"
    )
    result = project(run, "input.json5", stdin)
    assert result.stdout == (
        b"a: .nan\nb: .inf\nc: -31\nd: 0xab\ne: 0.5\nf: -5.0\ng: 0.5e1\nh: 5.0E2\ni: -0\nj: 1e3\n"
        b"k: -0.5e-2\nl: 0x" + b"F" * 40 + b"\nm: -1461501637330902918203684832716283019655932542975\n"
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_line_and_paragraph_separators(run, workdir):
    """CATCHES: an implementation that does not treat U+2028/U+2029 as JSON5 line terminators in comments and whitespace, or that does not escape them as \\L and \\P when they appear raw inside strings."""
    stdin = "// c\u2028/* p\u2029q */ {a: 'x\u2028y',\u2028b: 'x\u2029y'}\n"
    result = project(run, "input.json5", stdin)
    assert result.stdout == b'# c\n# p\n# q\na: "x\\Ly"\nb: "x\\Py"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_line_continuations_are_removed(run, workdir):
    """CATCHES: an implementation that keeps the escaped line break of a JSON5 line continuation, or only supports LF continuations and not CRLF, CR, U+2028 and U+2029."""
    stdin = "{a: 'x\\\ny', b: 'x\\\r\ny', c: 'x\\\ry', d: 'x\\\u2028y', e: 'x\\\u2029y'}\n"
    result = project(run, "input.json5", stdin)
    assert result.stdout == b"{a: xy, b: xy, c: xy, d: xy, e: xy}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_string_escapes_are_decoded(run, workdir):
    """CATCHES: an implementation that mis-decodes JSON5 escapes (\\0 not followed by a digit, \\v, \\/, escaped quotes of the other kind, \\u2028, \\u0085, \\u00a0) or quotes a lone `"` value with double quotes instead of single quotes."""
    stdin = (
        "{a: '\\u0000\\u0007\\u001b\\0x', b: 'x\\u2028y\\u0085z\\u00a0w', c: \"\\'\", d: '\\\"', "
        "e: 'tab\\there\\nnext\\r\\b\\f\\v\\/\\\\'}\n"
    )
    result = project(run, "input.json5", stdin)
    assert result.stdout.decode() == (
        'a: "\\0\\a\\e\\0x"\n'
        'b: "x\\Ly\\Nz\\_w"\n'
        "c: \"'\"\n"
        "d: '\"'\n"
        'e: "tab\\there\\nnext\\r\\b\\f\\v/\\\\"\n'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_literals_and_arrays_without_comments_stay_flow(run, workdir):
    """CATCHES: an implementation that mis-projects JSON5 null/true/false, quotes single-quoted strings that YAML can carry plain, or expands comment-free JSON5 arrays into block style when the document fits on one line."""
    result = project(run, "input.json5", "{a: null, b: true, c: false, d: [1, [2, 'x']], e: []}\n")
    assert result.stdout == b"{a: null, b: true, c: false, d: [1, [2, x]], e: []}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_flow_mapping_keys(run, workdir):
    """CATCHES: an implementation that leaves "true" unquoted, fails to quote digit-led or empty keys, or rejects non-ASCII identifier letters when projecting a comment-free JSON5 object."""
    stdin = "{'a b': 1, \"true\": 2, '1': 3, '': 4, '\u0100': 5, '\u00e9': 6}\n"
    result = project(run, "input.json5", stdin)
    assert result.stdout.decode() == '{a b: 1, "true": 2, "1": 3, "": 4, \u0100: 5, \u00e9: 6}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_comments_in_and_after_empty_collections(run, workdir):
    """CATCHES: an implementation that drops comments written inside empty [] / {} member values or sequence items, or that renders a non-empty nested collection inside a sequence on the dash line."""
    stdin = (
        "{\n  a: [ /* c */ ],\n  b: { // d\n  },\n  c: [],\n  d: [\n    [], // after empty\n"
        "    {},\n    [ /* in */ ],\n    [1, 2],\n    {x: 1},\n  ],\n}\n"
    )
    result = project(run, "input.json5", stdin)
    assert result.stdout == (
        b"# c\na: []\n# d\nb: {}\nc: []\nd:\n  - []\n  # after empty\n  - {}\n  # in\n  - []\n"
        b"  -\n    - 1\n    - 2\n  -\n    x: 1\n"
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_comment_text_is_neutralized_and_escaped(run, workdir):
    """CATCHES: an implementation that leaves a JSON5 `fmt: skip` comment active (instead of prefixing `[json5]`), writes control characters raw into YAML comments, or treats U+0085 the same way in line and block comments (it splits only block comments)."""
    stdin = "// fmt: skip\n// \u0001 \u007f \ufffe \U0001F600\n/* a\u0085b */ // c\u0085d\n{a: 1}\n"
    result = project(run, "input.json5", stdin)
    assert result.stdout.decode() == (
        "# [json5] fmt: skip\n# \\x01 \\x7F \\uFFFE \U0001F600\n# a\n# b\n# c\\x85d\na: 1\n"
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_crlf_comments(run, workdir):
    """CATCHES: an implementation that keeps carriage returns in comments projected from CRLF JSON5, or keeps the `*` prefix of block-comment continuation lines."""
    stdin = "{\r\n  // c\r\n  a: 1,\r\n  /* m\r\n   * n\r\n   */\r\n  b: 2,\r\n}\r\n"
    result = project(run, "input.json5", stdin)
    assert result.stdout == b"# c\na: 1\n# m\n# n\n#\nb: 2\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_comments_around_commas_keep_source_order(run, workdir):
    """CATCHES: an implementation that drops or reorders comments placed after a comma, before a comma on the next line, or between a value and its comma."""
    stdin = "{a: 1,\n// x\nb: 2 // y\n, c: 3 /* z */, /* w */ d: 4}\n"
    result = project(run, "input.json5", stdin)
    assert result.stdout == b"a: 1\n# x\nb: 2\n# y\nc: 3\n# z\n# w\nd: 4\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_accepts_byte_order_mark(run, workdir):
    """CATCHES: an implementation that applies the strict-JSON BOM rejection to JSON5, where U+FEFF is whitespace."""
    result = project(run, "input.json5", "\ufeff{a: 1}\n")
    assert result.stdout == b"{a: 1}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        pytest.param("{a: '\\u12'}\n", "1:6: error: invalid JSON5: invalid Unicode escape sequence\n", id="unicode-escape"),
        pytest.param(
            "{a: '\\uDC00'}\n",
            "1:6: error: invalid JSON5: lone low surrogate in Unicode escape sequence\n",
            id="lone-low-surrogate",
        ),
        pytest.param(
            "{a: '\\uD800\\uZZZZ'}\n",
            "1:12: error: invalid JSON5: invalid low surrogate in Unicode escape sequence\n",
            id="high-surrogate-then-bad-hex",
        ),
        pytest.param(
            "{a: '\\01'}\n",
            "1:6: error: invalid JSON5: legacy numeric escape sequences are not supported\n",
            id="zero-then-digit",
        ),
        pytest.param(
            "{a\\uD800: 1}\n",
            "1:3: error: invalid JSON5: surrogate escapes are not valid in identifiers\n",
            id="identifier-surrogate",
        ),
        pytest.param(
            "{a\\u0020: 1}\n",
            "1:3: error: invalid JSON5: escaped character is not valid in a JSON5 IdentifierName\n",
            id="identifier-space",
        ),
        pytest.param(
            "{a: '\\uD800'}\n",
            "1:6: error: invalid JSON5: lone high surrogate in Unicode escape sequence\n",
            id="lone-high-surrogate",
        ),
        pytest.param("{\u0085a: 1}\n", "1:2: error: invalid JSON5: U+0085 is not JSON5 whitespace\n", id="next-line"),
        pytest.param("", "1:1: error: invalid JSON5: Unexpected EOF. Was expecting value.\n", id="empty"),
        pytest.param("{a: 'x\\", "1:5: error: invalid JSON5: Unterminated string starting at\n", id="unterminated-string"),
        pytest.param(
            "{a: '\\xZZ',\u2028b: 1}\n",
            "1:6: error: invalid JSON5: invalid hexadecimal escape sequence\n",
            id="position-before-raw-separator",
        ),
        pytest.param(
            "[\u2028,]\n",
            '2:1: error: invalid JSON5: Unexpected token of type Comma: ","\n',
            id="token-right-after-raw-separator",
        ),
        pytest.param(
            "{a: '\\uD800\u2028'}\n",
            "1:12: error: invalid JSON5: invalid low surrogate in Unicode escape sequence\n",
            id="raw-separator-after-high-surrogate",
        ),
        pytest.param(
            "{a: 'x\u2028', \nb: '\\xZZ'}\n",
            "3:5: error: invalid JSON5: invalid hexadecimal escape sequence\n",
            id="position-after-raw-separator",
        ),
    ],
)
def test_json5_rejects_invalid_input_with_position(run, workdir, stdin, stderr):
    """CATCHES: an implementation that accepts invalid hex/Unicode escapes, lone or mismatched surrogates, `\\0` followed by a digit, surrogate or non-identifier escapes in keys, or U+0085 whitespace in JSON5; or that reports error columns in bytes / escaped text rather than source characters, or does not count a raw U+2028 as a line break in error positions."""
    result = project(run, "input.json5", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == "input.json5:" + stderr
    assert result.returncode == 1


# --- JSON Lines ------------------------------------------------------------


def test_ndjson_crlf_records_of_every_kind(run, workdir):
    """CATCHES: an implementation that omits the `---` marker before each record, keeps CR line endings, or rejects scalar records (true, null, strings) in NDJSON."""
    result = project(run, "input.ndjson", 'true\r\nnull\r\n"x"\r\n{"b": [1,{"c":2}]}\r\n')
    assert result.stdout == b"---\ntrue\n---\nnull\n---\nx\n---\n{b: [1, {c: 2}]}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonl_layout_is_decided_per_record(run, workdir):
    """CATCHES: an implementation that applies one flow/block decision to the whole JSON Lines stream, or folds long record strings at --line-width instead of --prose-width."""
    stdin = '{"a": [1, 2, 3], "b": {"x": 1}}\n{"c": "' + "word " * 20 + 'end"}\n'
    result = project(run, "records.jsonl", stdin, "--line-width", "30")
    assert result.stdout == (RES / "jsonl_wide.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        pytest.param('{"a": 1}\n\n', "2:1: error: invalid JSON Lines: records cannot be blank\n", id="trailing-blank-line"),
        pytest.param(
            '{"a": 1}\n   \n{"b": 2}\n',
            "2:1: error: invalid JSON Lines: records cannot be blank\n",
            id="whitespace-only-line",
        ),
        pytest.param(
            '{"a": 1}\n' + "[" * 300 + "]" * 300 + "\n",
            "2:257: error: invalid JSON: nesting exceeds 256 levels\n",
            id="nesting-on-second-record",
        ),
        pytest.param('{"a": 1}\n{"b": [1,', "2:7: error: invalid JSON: Unterminated array\n", id="parse-error-on-second-record"),
        pytest.param("", "1:1: error: invalid JSON Lines: expected a JSON value\n", id="empty"),
    ],
)
def test_jsonl_rejects_invalid_records_with_line_number(run, workdir, stdin, stderr):
    """CATCHES: an implementation that skips blank or whitespace-only JSON Lines records, reports record errors relative to the record instead of the whole input, or accepts empty input."""
    result = project(run, "input.jsonl", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == "input.jsonl:" + stderr
    assert result.returncode == 1


# --- path hints and configuration -------------------------------------------


def test_extension_matching_is_case_insensitive(run, workdir):
    """CATCHES: an implementation that matches JSON-family extensions case-sensitively and rejects an upper-case `.JSONL` path hint."""
    result = project(run, "data.JSONL", "1\n")
    assert result.stdout == b"---\n1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_config_compact_is_discovered_from_the_path_hint_directory(run, workdir):
    """CATCHES: an implementation that discovers yamark.toml from the current directory instead of the --stdin-file-path directory, or ignores `[format] compact` for to-yaml."""
    write_tree(workdir, {"sub/yamark.toml": "[format]\ncompact = true\n"})
    result = project(run, "sub/data.jsonc", JSONC_COMMENTED)
    assert result.stdout == COMPACT_YAML
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_flag_overrides_config_compact_false(run, workdir):
    """CATCHES: an implementation that lets `compact = false` in the explicit --config file disable the --compact flag."""
    write_tree(workdir, {"cfg/yamark.toml": "[format]\ncompact = false\n"})
    result = project(run, "input.jsonc", JSONC_COMMENTED, "--config", "cfg/yamark.toml", "--compact")
    assert result.stdout == COMPACT_YAML
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_invalid_explicit_config_is_reported(run, workdir):
    """CATCHES: an implementation that ignores unknown keys in a --config file for to-yaml, or prints partial YAML before failing."""
    write_tree(workdir, {"yamark.toml": "[format]\nbogus = 1\n"})
    result = project(run, "input.json", '{"a": 1}\n', "--config", "yamark.toml")
    assert result.stdout == b""
    assert result.stderr.decode() == "yamark.toml:1:1: error: unknown format config key: format.bogus\n"
    assert result.returncode == 1


def test_configured_template_delimiters_do_not_preserve_projected_flow(run, workdir):
    """CATCHES: an implementation that applies configured template delimiters to projected JSON data, preserving the generated flow mapping verbatim instead of formatting it."""
    write_tree(workdir, {"yamark.toml": '[template]\nadd_delimiters = [{ open = "<<", close = ">>" }]\n'})
    result = project(run, "input.json", '{"a": "<< x >>", "b": ["{{ y }}", "z"]}\n')
    assert result.stdout == b'{a: << x >>, b: ["{{ y }}", z]}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
