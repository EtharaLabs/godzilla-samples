"""YAML scalar formatting gaps: escapes, quoting, core tags, folded/literal layout, and embedded targets.

Each test formats YAML through `format --stdin-file-path x.yaml` (or a path) and pins the exact
stdout, stderr and exit status that the reference implementation produces for one scalar rule.
"""

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

STDIN_ARGS = ["format", "--stdin-file-path", "x.yaml"]
LONG = "This package formats YAML front matter and configuration files while preserving semantics and comments."
SPACED = "Alpha beta  gamma delta epsilon zeta  eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau"
UPPER_SCRIPT = "import sys\nsys.stdout.write(sys.stdin.read().upper())\n"


def embedded_config(script_name):
    return (
        "[embedded.lorem]\n"
        f'formatter = {{ command = ["python3", "{script_name}", "{{path}}"], path_suffix = ".txt" }}\n'
    )


def writer_script(text):
    return f"import sys\nsys.stdin.read()\nsys.stdout.write({text!r})\n"


def fmt(run, stdin, *extra):
    return run([*STDIN_ARGS, *extra], input=stdin)


# --- double-quoted escapes -------------------------------------------------------------------


def test_control_escapes_stay_double_quoted_and_escaped_slash_is_simplified(run):
    """CATCHES: an implementation that drops or rewrites the \\0 \\a \\b \\v \\f \\r \\e escapes (or emits raw control bytes) instead of re-escaping them, or that keeps the redundant `\\/` escape instead of normalising it to `/`."""
    result = fmt(run, 'a: "\\0\\a\\b\\v\\f\\r\\e\\/\\\\"\n')
    assert result.stdout == b'a: "\\0\\a\\b\\v\\f\\r\\e/\\\\"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hex_and_unicode_escapes_decode_to_a_plain_scalar(run):
    """CATCHES: an implementation that does not decode \\U (8-digit), \\x and \\u escapes, or keeps the quotes when the decoded text (emoji, `A`, `é`) is a safe plain string."""
    result = fmt(run, 'a: "\\U0001F600 \\x41 \\u00e9"\n')
    assert result.stdout == "a: \U0001F600 A \u00e9\n".encode()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unsupported_named_escapes_keep_their_source_spelling(run):
    """CATCHES: an implementation that decodes the \\N \\_ \\L \\P and escaped-space forms itself (changing their spelling or quoting) instead of leaving such strings byte-for-byte, while still unquoting the ordinary sibling string."""
    result = fmt(run, 'a: "\\N\\_\\L\\P"\nb: "x\\ y"\nc: "plain"\n')
    assert result.stdout == b'a: "\\N\\_\\L\\P"\nb: "x\\ y"\nc: plain\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_line_break_followed_by_blank_line_becomes_one_literal_newline(run):
    """CATCHES: an implementation that mis-decodes an escaped physical line break followed by an empty line (e.g. producing two newlines or a space) instead of the single newline that yields a `|-` block with lines `a` and `b`."""
    result = fmt(run, 'a: "a\\\n\n  b"\n')
    assert result.stdout == b"a: |-\n  a\n  b\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_carriage_return_keeps_double_quotes(run):
    """CATCHES: an implementation that converts a value containing an escaped \\r\\n into a literal block (which cannot represent a carriage return) instead of keeping it double-quoted."""
    result = fmt(run, "a: \"a\\r\\nb\"\nb: 'x'\n")
    assert result.stdout == b'a: "a\\r\\nb"\nb: x\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_control_character_with_newline_keeps_double_quotes(run):
    """CATCHES: an implementation that converts a string with an escaped \\x01 control character plus \\n into a literal block (writing a raw control byte) instead of keeping the escaped double-quoted form."""
    result = fmt(run, "a: \"a\\x01\\nb\"\nb: 'x'\n")
    assert result.stdout == b'a: "a\\x01\\nb"\nb: x\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_leading_spaces_and_two_trailing_newlines_use_indent_and_keep_indicators(run):
    """CATCHES: an implementation that converts `"  foo\\n\\n"` to a literal block without the explicit indentation indicator and `+` keep chomping (`|2+`), which would lose the leading spaces or the extra trailing newline."""
    result = fmt(run, 'a: "  foo\\n\\n"\nb: 1\n')
    assert result.stdout == b"a: |2+\n    foo\n\nb: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_three_trailing_newlines_use_keep_chomping_with_two_blank_lines(run):
    """CATCHES: an implementation that emits `|` or `|-` (clip/strip) for a value ending in three newlines, or writes the wrong number of trailing blank lines before the next key."""
    result = fmt(run, 'a: "foo\\n\\n\\n"\nb: 1\n')
    assert result.stdout == (RES / "keep_three.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_indent_indicator_is_impossible_at_indent_width_ten_so_quotes_stay(run):
    """CATCHES: an implementation that emits a literal block with indentation indicator 10 (only 1-9 are valid YAML) for a value whose first line starts with spaces, instead of keeping it double-quoted."""
    result = fmt(run, "a: \"  lead\\nfoo\"\nb: 'x'\n", "--indent-width", "10")
    assert result.stdout == b'a: "  lead\\nfoo"\nb: x\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_double_quoted_scalar_with_trailing_spaces_is_moved_verbatim(run):
    """CATCHES: an implementation that reflows or trims a multi-line double-quoted scalar (spaces before the physical break) or shifts its continuation line left when the parent mapping is reindented."""
    result = fmt(run, 'x:\n    a: "foo  \n      bar"\n')
    assert result.stdout == b'x:\n  a: "foo  \n      bar"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_double_quoted_scalar_with_tab_before_break_is_moved_verbatim(run):
    """CATCHES: an implementation that mishandles a tab before a physical line break inside a double-quoted scalar (rewriting it, or failing) when the parent mapping is reindented."""
    result = fmt(run, 'x:\n    a: "foo\t\n      bar"\n')
    assert result.stdout == b'x:\n  a: "foo\t\n      bar"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- quoting and plain safety ----------------------------------------------------------------


def test_quoted_strings_are_simplified_only_when_plain_is_safe(run):
    """CATCHES: an implementation that keeps safe quoted strings quoted in block context, or that unquotes flow entries containing quote characters, or prefers the longer single-quoted spelling `'it''s'` over `"it's"`."""
    result = fmt(run, "a: 'it''s'\nb: 'say \"hi\"'\nc: \"it's \\\"q\\\"\"\nd: [\"it's\", 'say \"hi\"']\n")
    assert result.stdout == (RES / "quote_simplify.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml11_boolean_spellings_are_plain_strings_in_yaml12(run):
    """CATCHES: an implementation that applies YAML 1.1 rules and keeps quotes around yes/No/on/OFF/y, instead of treating them as YAML 1.2 strings that are safe to emit plain."""
    result = fmt(run, 'a: "yes"\nb: "No"\nc: "on"\nd: "OFF"\ne: "y"\n')
    assert result.stdout == (RES / "yaml11_bools.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_numeric_null_and_boolean_lookalike_strings_keep_their_quotes(run):
    """CATCHES: an implementation that unquotes strings a YAML 1.2 core reader would load as int/float/null/bool (017, 0o17, 1.0, -0, +12, .5, 5., 1e3, 0x1F, 0X1F, ~, NULL, False), or keeps quotes on near misses (1.0.0, 0x1G, 1e, nulls)."""
    stdin = (
        'f: "017"\nh: "0o17"\nj: "1.0"\nk: "-0"\nl: "+12"\nm: ".5"\nn: "5."\no: "1e3"\n'
        'p: "0x1F"\nq: "0X1F"\nr: "~"\ns: "NULL"\nt: "False"\n'
        'u: "1.0.0"\nv: "0x1G"\nw: "1e"\nx: "nulls"\n'
    )
    result = fmt(run, stdin)
    assert result.stdout == (RES / "numeric_lookalikes.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_timestamp_and_sexagesimal_strings_are_unquoted(run):
    """CATCHES: an implementation that keeps quotes on YAML 1.1 timestamps and base-60 numbers, which the YAML 1.2 core schema reads as plain strings."""
    stdin = 'g: "2001-12-14"\nh: "2001-12-14t21:59:43.10-05:00"\ni: "1:30"\nj: "190:20:30"\n'
    result = fmt(run, stdin)
    assert result.stdout == (RES / "timestamp_sexagesimal.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_whitespace_edges_and_indicator_sequences_decide_quoting(run):
    """CATCHES: an implementation that unquotes empty strings, leading/trailing spaces, `: ` or ` #` sequences, or a leading `- `, or conversely keeps quotes on safe `a#b` and `-x`."""
    stdin = 's: ""\nt: " lead"\nu: "trail "\nv: "a: b"\nw: "a #b"\nx: "a#b"\ny: "- x"\nz: "-x"\n'
    result = fmt(run, stdin)
    assert result.stdout == (RES / "whitespace_indicators.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_anchored_plain_scalars_with_reserved_indicators_are_single_quoted(run):
    """CATCHES: an implementation that leaves anchored plain values starting with the reserved `@` or backtick indicators unquoted (or drops the anchor), or quotes an ordinary anchored plain value."""
    result = fmt(run, "a: &x @foo\nb: &y `cmd`\nc: &z plain\n")
    assert result.stdout == b"a: &x '@foo'\nb: &y '`cmd`'\nc: &z plain\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_strings_with_valid_underscore_numbers_keep_quotes(run):
    """CATCHES: an implementation that disagrees on underscore digit grouping: `1_000`, `0b1_0`, `0o1_7` are numbers (quotes kept) while `1__0`, `0x_1`, `1_`, `_1` are strings that become plain."""
    result = fmt(run, 'a: ["1_000", "0b1_0", "1__0", "0x_1", "1_", "_1", "0o1_7"]\n')
    assert result.stdout == b'a: ["1_000", "0b1_0", 1__0, 0x_1, 1_, _1, "0o1_7"]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_long_escaped_integer_string_keeps_quotes_after_decoding(run):
    """CATCHES: an implementation that classifies only short values as numeric and unquotes a 21-digit integer-looking string after decoding its leading \\x31 escape."""
    result = fmt(run, 'a: ["\\x3112345678901234567890"]\n')
    assert result.stdout == b'a: ["112345678901234567890"]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_numeric_and_null_lookalikes_decode_but_keep_quotes(run):
    """CATCHES: an implementation that classifies a string before decoding its escapes, unquoting values such as `0x1F`, `1e3`, `.inf`, `1_000`, `-.5`, `~` and `Null` that were spelled with \\x escapes."""
    result = fmt(run, 'a: ["\\x30x1F", "1\\x653", "\\x2einf", "1\\x5f000", "\\x2d.5", "\\x7e", "N\\x75ll"]\n')
    assert result.stdout == b'a: ["0x1F", "1e3", ".inf", "1_000", "-.5", "~", "Null"]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_control_and_noncharacter_escapes_use_canonical_uppercase_forms(run):
    """CATCHES: an implementation that writes lowercase hex (`\\x7f`, `\\ufeff`), keeps `\\u0085` instead of the short `\\x85`, or emits the raw characters for BOM/noncharacter/control values in flow strings."""
    result = fmt(run, 'a: ["\\ufeffx", "a\\x01b", "\\x7f", "\\u0085", "\\ufffe"]\n')
    assert result.stdout == b'a: ["\\uFEFFx", "a\\x01b", "\\x7F", "\\x85", "\\uFFFE"]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_bom_and_next_line_characters_in_single_quotes_become_escaped(run):
    """CATCHES: an implementation that keeps a raw U+FEFF or U+0085 inside a single-quoted flow string instead of switching to double quotes with `\\uFEFF` and `\\x85` escapes."""
    result = fmt(run, "a: ['a\ufeffb', 'a\u0085b', x]\n")
    assert result.stdout == b'a: ["a\\uFEFFb", "a\\x85b", x]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0



def test_flow_escaped_line_break_joins_words_when_expanding_to_block(run):
    """CATCHES: an implementation that decodes an escaped line break in a double-quoted flow entry as a space or newline (the value is `ab`), or keeps the physically multiline flow sequence inline."""
    result = fmt(run, 'a: ["a\\\n  b",  x]\n')
    assert result.stdout == b"a:\n  - ab\n  - x\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0

# --- explicit core tags ----------------------------------------------------------------------


def test_flow_core_tags_with_escaped_values_are_normalized(run):
    """CATCHES: an implementation that fails to decode escapes before validating explicit !!bool/!!null/!!int/!!float values, or unquotes a !!str value containing a comma inside a flow sequence."""
    result = fmt(run, 'a: [!!bool "tru\\u0065", !!null "nul\\x6c", !!int "1\\x32", !!float "1\\x2e5", !!str "a\\x2cb"]\n')
    assert result.stdout == b"a: [!!bool true, !!null null, !!int 12, !!float 1.5, !!str 'a,b']\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_core_tags_with_escaped_uppercase_values_use_yaml12_spellings(run):
    """CATCHES: an implementation that keeps `FALSE`/`NULL` spellings or normalises the `~` null to `null` for escaped values under explicit !!bool and !!null tags."""
    result = fmt(run, 'a: [!!bool "F\\x41LSE", !!null "\\x7e", !!null "N\\x55LL"]\n')
    assert result.stdout == b"a: [!!bool false, !!null ~, !!null null]\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_bool_tag_with_non_boolean_escaped_value_preserves_collection(run):
    """CATCHES: an implementation that unquotes `!!bool "ye\\x73"` (YAML 1.2 has no `yes` boolean) or the non-ASCII `"tr\\u00fce"`, or partially reformats the flow collections' spacing instead of preserving them verbatim."""
    result = fmt(run, "a: [!!bool \"ye\\x73\",   x]\nb: 'y'\nc: [!!bool \"tr\\u00fce\",  x]\n")
    assert result.stdout == b'a: [!!bool "ye\\x73",   x]\nb: y\nc: [!!bool "tr\\u00fce",  x]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_null_tag_with_non_null_escaped_value_preserves_collection(run):
    """CATCHES: an implementation that rewrites `!!null "n\\x6fne"` (not a null spelling) to plain or null, or normalises the surrounding flow spacing instead of preserving the collection."""
    result = fmt(run, "a: [!!null \"n\\x6fne\",   x]\nb: 'y'\n")
    assert result.stdout == b'a: [!!null "n\\x6fne",   x]\nb: y\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_str_tag_values_are_quoted_only_when_needed(run):
    """CATCHES: an implementation that unquotes a !!str value containing a tab, keeps `\\x41` escaped instead of plain `A`, or emits the digit string `12` plain (it must stay quoted as `'12'`)."""
    result = fmt(run, 'a: [!!str "a\\tb", !!str "\\x41", !!str "1\\x32"]\n')
    assert result.stdout == b"a: [!!str \"a\\tb\", !!str A, !!str '12']\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_single_quoted_core_tag_values_are_unquoted(run):
    """CATCHES: an implementation that keeps single quotes around valid explicitly tagged core values or spells an empty !!null value as `''` instead of `null`."""
    result = fmt(run, "a: [!!str 'x', !!int '12', !!float '1.5', !!bool 'true', !!null '']\n")
    assert result.stdout == b"a: [!!str x, !!int 12, !!float 1.5, !!bool true, !!null null]\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_overwidth_tagged_flow_sequence_expands_with_normalized_values(run):
    """CATCHES: an implementation that leaves an over-width flow sequence of tagged scalars inline, or loses tag normalisation (null/'' -> null, "true" -> true, 12 under !!str -> '12') when expanding it to block style."""
    stdin = (
        "a: [!!bool false, !!null null, !!null '', !!int 12, !!float 1.5, !!str 12, !!bool \"true\", "
        "!!null \"~\", !!int \"12\", !!float \"1.5\", !!str \"x\", !!str \"a, b\"]\n"
    )
    result = fmt(run, stdin)
    assert result.stdout == (RES / "overwidth_tagged_flow.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_flow_with_tag_on_its_own_line_expands_to_block(run):
    """CATCHES: an implementation that keeps a physically multiline flow sequence inline, or loses the !!str tag written on the line before its value when expanding to a block sequence."""
    result = fmt(run, "a: [!!str\n  x, y]\n")
    assert result.stdout == b"a:\n  - !!str x\n  - y\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_flow_tag_then_anchor_keeps_property_order(run):
    """CATCHES: an implementation that reorders `!!str &a` to `&a !!str` (or drops one property) when a multiline flow entry is expanded to block style."""
    result = fmt(run, "a: [!!str &a\n  x, y]\n")
    assert result.stdout == b"a:\n  - !!str &a x\n  - y\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_flow_anchor_then_tag_keeps_property_order(run):
    """CATCHES: an implementation that reorders `&a !!str` to `!!str &a` (or drops one property) when a multiline flow entry is expanded to block style."""
    result = fmt(run, "a: [&a !!str\n  x, y]\n")
    assert result.stdout == b"a:\n  - &a !!str x\n  - y\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_core_tags_with_mismatched_values_are_left_unchanged(run):
    """CATCHES: an implementation that 'normalises' values that do not match their core tag (`!!bool maybe`, `!!null nope`, `!!bool "yes"`) or reformats a flow collection containing one."""
    result = fmt(run, "a: [!!bool maybe,  x]\nb: !!bool maybe\nc: !!null nope\nd: !!bool \"yes\"\ne: 'z'\n")
    assert result.stdout == (RES / "core_tag_mismatch.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_float_and_int_tags_unquote_only_valid_spellings(run):
    """CATCHES: an implementation with a different float grammar: 1e5, 1_000.5, .inf, .NaN and 1.5e-3 must unquote under !!float and 1_000 under !!int, while 1x, the signed -.NaN, + and the integer-looking 12 stay quoted under !!float."""
    stdin = (
        'a: !!float "1e5"\nb: !!float "1x"\nc: !!int "1_000"\nd: !!float "1_000.5"\ne: !!float ".inf"\n'
        'f: !!float "-.NaN"\ng: !!float "1.5e-3"\nh: !!float "+"\ni: !!float "12"\nj: !!float ".NaN"\n'
    )
    result = fmt(run, stdin)
    assert result.stdout == (RES / "tagged_quoted_floats.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_entry_with_empty_custom_tag_preserves_collection(run):
    """CATCHES: an implementation that drops an empty custom-tagged flow entry, invents a value for it, or normalises the spacing of flow collections holding custom-tagged entries."""
    result = fmt(run, "a: [!custom ,   x]\nb: 'y'\nc: [!custom x,   y]\n")
    assert result.stdout == b"a: [!custom ,   x]\nb: y\nc: [!custom x,   y]\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- folded prose ----------------------------------------------------------------------------


def test_long_root_quoted_string_folds_at_root_indentation(run):
    """CATCHES: an implementation that does not fold a long root-level quoted scalar, or indents the folded body by something other than the indent width (2) below a root `>-` header."""
    result = fmt(run, '"' + LONG + '"\n')
    assert result.stdout == (RES / "root_long_quoted.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_long_string_without_spaces_is_unquoted_but_not_folded(run):
    """CATCHES: an implementation that emits a one-line `>-` block (or splits inside a word) for a 90-character value with no break opportunities instead of the plain scalar."""
    value = "x" * 90
    result = fmt(run, f'a: "{value}"\n')
    assert result.stdout == f"a: {value}\n".encode()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_block_with_indentation_indicator_is_not_rewrapped(run):
    """CATCHES: an implementation that rewraps a long folded scalar whose header carries an explicit indentation indicator (`>2`), which would change the header or body indentation."""
    result = fmt(run, "a: >2\n   " + LONG + "\nz: 'q'\n")
    assert result.stdout == (RES / "folded_indent_indicator.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_block_containing_a_tab_is_not_rewrapped(run):
    """CATCHES: an implementation that rewraps folded prose containing a tab (folding could move the tab or alter whitespace) instead of keeping the body unchanged."""
    result = fmt(run, "a: >\n  foo\tbar " + LONG + "\nz: 'q'\n")
    assert result.stdout == (RES / "folded_tab.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_block_with_leading_blank_line_is_not_rewrapped(run):
    """CATCHES: an implementation that drops the leading blank line of a folded scalar (it decodes to a leading newline) while rewrapping the long prose that follows."""
    result = fmt(run, "a: >\n\n  " + LONG + "\nz: 'q'\n")
    assert result.stdout == (RES / "folded_leading_blank.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_block_with_paragraph_break_is_not_rewrapped(run):
    """CATCHES: an implementation that rewraps multi-paragraph folded scalars, merging or reflowing across the blank line that encodes a newline."""
    result = fmt(run, "a: >\n  " + LONG + "\n\n  second\nz: 'q'\n")
    assert result.stdout == (RES / "folded_paragraphs.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_block_with_more_indented_line_is_not_rewrapped(run):
    """CATCHES: an implementation that rewraps a folded scalar containing a more-indented line, whose line break is preserved by YAML and would be lost by refolding."""
    result = fmt(run, "a: >\n  " + LONG + "\n    more\nz: 'q'\n")
    assert result.stdout == (RES / "folded_more_indented.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_block_with_trailing_spaces_is_not_rewrapped(run):
    """CATCHES: an implementation that strips trailing spaces from a folded line (they are part of the value) while rewrapping it."""
    result = fmt(run, "a: >\n  " + LONG + "  \nz: 'q'\n")
    assert result.stdout == (RES / "folded_trailing_spaces.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_simple_long_folded_block_is_rewrapped_at_prose_width(run):
    """CATCHES: an implementation that ignores `--prose-width 40` for an existing simple folded scalar, or changes its `>` header to `>-` while rewrapping."""
    result = fmt(run, "a: >\n  " + LONG + "\nz: 'q'\n", "--prose-width", "40")
    assert result.stdout == (RES / "folded_simple_rewrap.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folding_never_breaks_at_double_spaces(run):
    """CATCHES: an implementation that breaks lines at one of two adjacent spaces (which would change the folded value) instead of only at single spaces, at `--prose-width 20`."""
    result = fmt(run, f'a: "{SPACED}"\n', "--prose-width", "20")
    assert result.stdout == (RES / "prose_width_double_spaces.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_prose_width_counts_characters_not_bytes(run):
    """CATCHES: an implementation that measures `--prose-width 30` in UTF-8 bytes, wrapping two-byte `é` words after two or three words per line instead of five."""
    words = " ".join(["\u00e9" * 5] * 14)
    result = fmt(run, f'a: "{words}"\n', "--prose-width", "30")
    assert result.stdout == (RES / "prose_width_multibyte.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_sequence_item_block_bodies_follow_indent_width_four(run):
    """CATCHES: an implementation that indents literal or folded bodies created for sequence items by 2 instead of the configured `--indent-width 4`."""
    result = fmt(run, f'- "foo\\nbar"\n- "{SPACED}"\n', "--indent-width", "4")
    assert result.stdout == (RES / "sequence_indent4.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_plain_continuation_keeps_whitespace_line_shorter_than_shift(run):
    """CATCHES: an implementation that crashes on, or strips, a one-space line inside a multi-line plain scalar when the parent mapping is dedented by two columns."""
    result = fmt(run, "a:\n    b: foo\n \n       bar\n")
    assert result.stdout == b"a:\n  b: foo\n \n     bar\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_nested_empty_literal_body_is_reindented_with_its_parent(run):
    """CATCHES: an implementation that refuses or corrupts an empty literal scalar (`|` with no body) when its enclosing mapping is reindented from 4 to 2 spaces."""
    result = fmt(run, "a:\n    b: |\n    c: 1\n")
    assert result.stdout == b"a:\n  b: |\n  c: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_crlf_quoted_newline_becomes_crlf_literal_block(run):
    """CATCHES: an implementation that writes LF line endings for the new literal block body in a CRLF document."""
    result = fmt(run, "a: \"foo\\nbar\"\r\nb: 'x'\r\n")
    assert result.stdout == b"a: |-\r\n  foo\r\n  bar\r\nb: x\r\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_cr_only_quoted_newline_becomes_cr_literal_block(run):
    """CATCHES: an implementation that does not detect old-Mac CR line endings and writes LF (or CRLF) lines when converting a quoted newline to a literal block."""
    result = fmt(run, "a: \"foo\\nbar\"\rb: 'x'\r")
    assert result.stdout == b"a: |-\r  foo\r  bar\rb: x\r"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- embedded formatters on root and mapping literal scalars ----------------------------------


def test_root_literal_scalar_is_formatted_by_embedded_formatter(run, workdir):
    """CATCHES: an implementation that only honours `# fmt: <name>` on mapping or sequence values and leaves a root-level literal scalar unformatted."""
    files = {"yamark.toml": embedded_config("fmt_upper"), "fmt_upper": UPPER_SCRIPT}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\n|\n  hello\n  world\n")
    assert result.stdout == (RES / "root_external.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_root_literal_with_empty_formatter_output_gets_strip_chomping(run, workdir):
    """CATCHES: an implementation that keeps the `|` header (or adds a blank body line) when the embedded formatter returns nothing, instead of the `|-` header with no body."""
    files = {"yamark.toml": embedded_config("fmt_s"), "fmt_s": writer_script("")}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\n|\n  hello\n")
    assert result.stdout == b"# fmt: lorem\n|-\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_root_literal_with_extra_trailing_newlines_gets_keep_chomping(run, workdir):
    """CATCHES: an implementation that keeps clip chomping (`|`) or trims the blank lines when the embedded formatter output ends with several newlines, instead of switching to `|+`."""
    files = {"yamark.toml": embedded_config("fmt_s"), "fmt_s": writer_script("HI\n\n\n")}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\n|\n  hello\n")
    assert result.stdout == b"# fmt: lorem\n|+\n  HI\n\n\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_formatter_output_without_final_newline_turns_strip_header_into_clip(run, workdir):
    """CATCHES: an implementation that keeps the source `|-` header or emits a body without a final newline when the embedded formatter output lacks one, instead of appending a newline and using clip `|`."""
    files = {"yamark.toml": embedded_config("fmt_s"), "fmt_s": writer_script("HI")}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\n|-\n  hello\n")
    assert result.stdout == b"# fmt: lorem\n|\n  HI\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_root_empty_literal_with_formatter_becomes_strip_header(run, workdir):
    """CATCHES: an implementation that fails, or keeps the clip header, for a root literal scalar with no body when its embedded formatter returns empty output."""
    files = {"yamark.toml": embedded_config("fmt_upper"), "fmt_upper": UPPER_SCRIPT}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\n|\n")
    assert result.stdout == b"# fmt: lorem\n|-\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_blank_mapping_literal_body_is_replaced_by_formatter_output(run, workdir):
    """CATCHES: an implementation that cannot infer a body indentation for a literal scalar containing only blank lines and so mis-indents (or drops) the embedded formatter's output."""
    files = {"yamark.toml": embedded_config("fmt_s"), "fmt_s": writer_script("X\n")}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\na: |\n\n\nb: 1\n")
    assert result.stdout == b"# fmt: lorem\na: |\n  X\nb: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_literal_header_at_end_of_input_without_newline(run, workdir):
    """CATCHES: an implementation that appends a newline (or crashes) for a `|` header ending the input without a line break whose embedded formatter returns empty output; the result is `a: |-` with no newline."""
    files = {"yamark.toml": embedded_config("fmt_upper"), "fmt_upper": UPPER_SCRIPT}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\na: |")
    assert result.stdout == b"# fmt: lorem\na: |-"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_root_formatted_literal_keeps_crlf_line_endings(run, workdir):
    """CATCHES: an implementation that writes LF line endings for the header or body of a CRLF root literal scalar after running its embedded formatter."""
    files = {"yamark.toml": embedded_config("fmt_upper"), "fmt_upper": UPPER_SCRIPT}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\r\n|\r\n  hello\r\n")
    assert result.stdout == b"# fmt: lorem\r\n|\r\n  HELLO\r\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_mapping_keep_literal_stays_keep_for_one_trailing_blank_line(run, workdir):
    """CATCHES: an implementation that converts `|+` to `|` or drops the blank line when the embedded formatter output ends with exactly two newlines."""
    files = {"yamark.toml": embedded_config("fmt_s"), "fmt_s": writer_script("HI\n\n")}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\na: |+\n  hello\n\n")
    assert result.stdout == b"# fmt: lorem\na: |+\n  HI\n\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_root_literal_indentation_indicator_is_kept_for_formatter_output(run, workdir):
    """CATCHES: an implementation that drops the `|2` indentation indicator or re-indents the formatted body to the default width, changing the value's leading space."""
    files = {"yamark.toml": embedded_config("fmt_upper"), "fmt_upper": UPPER_SCRIPT}
    write_tree(workdir, files)
    result = fmt(run, "# fmt: lorem\n|2\n   hello\n")
    assert result.stdout == b"# fmt: lorem\n|2\n   HELLO\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_root_literal_with_missing_optional_ruff_is_preserved_with_note(run, tmp_path):
    """CATCHES: an implementation that fails, or rewrites the scalar, when the optional built-in python formatter `ruff` is missing for a root literal scalar, or omits the --diagnostics note naming it."""
    (tmp_path / "emptybin").mkdir()
    result = run(
        [*STDIN_ARGS, "--diagnostics"],
        input="# fmt: python\n|\n  x=1\n",
        env_overrides={"PATH": str(tmp_path / "emptybin")},
    )
    assert result.stdout == b"# fmt: python\n|\n  x=1\n"
    assert result.stderr.decode() == (
        "x.yaml:3:1: note: missing optional embedded formatter `ruff`; preserved source\n"
        "x.yaml:1:1: note: yaml trace: source_scans=1 parse_passes=1 source_lines=3 yaml_scanned_lines=3 "
        "yaml_semantic_nodes=1 planned_rendered_scalars=0 planned_rendered_flow_collections=0 "
        "planned_rendered_block_flow_collections=0 emitted_bytes=22 emitted_nodes=1\n"
    )
    assert result.returncode == 0


# --- Markdown-valued scalars -----------------------------------------------------------------


def test_root_md_tagged_quoted_scalar_becomes_literal_markdown(run):
    """CATCHES: an implementation that leaves a root-level `!md` quoted scalar quoted, or fails to normalise its Markdown (collapsing the run of spaces) into a literal block indented by 2."""
    result = fmt(run, '!md "Some *text*   here."\n')
    assert result.stdout == b"!md |\n  Some *text* here.\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_root_long_markdown_tagged_scalar_wraps_in_a_literal_block(run):
    """CATCHES: an implementation that emits a folded `>` block (or a single long line) for long root `!markdown` prose instead of a literal block wrapped at the Markdown width."""
    stdin = (
        '!markdown "This package formats YAML front matter and configuration files while preserving '
        'semantics, comments, and diffs."\n'
    )
    result = fmt(run, stdin)
    assert result.stdout == (RES / "root_markdown_long.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_strip_literal_at_end_of_input_gains_final_newline(run):
    """CATCHES: an implementation that leaves the formatted Markdown body without a line break when a `|-` Markdown scalar ends the input without one, or fails to normalise its inline spacing."""
    result = fmt(run, "a: !md |-\n  Some   *text*")
    assert result.stdout == b"a: !md |-\n  Some *text*\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_directive_with_sentence_wrap_targets_only_next_scalar(run):
    """CATCHES: an implementation that ignores `wrap=sentence` on a `# fmt: markdown` directive, or applies it to the following sibling scalar as well."""
    stdin = (
        "# fmt: markdown wrap=sentence\n"
        'a: "First sentence here. Second one here."\n'
        'b: "First sentence here. Second one here."\n'
    )
    result = fmt(run, stdin)
    assert result.stdout == (RES / "markdown_sentence.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_directive_canonical_turns_folded_list_into_literal(run):
    """CATCHES: an implementation that keeps a Markdown list in a folded `>` scalar (folding would join the items) or ignores `canonical`, leaving `*` bullets instead of `-`."""
    result = fmt(run, "# fmt: markdown wrap=none canonical\na: >\n  * item one\n  * item two\n")
    assert result.stdout == (RES / "markdown_canonical_folded.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
