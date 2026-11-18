"""`yamark format` option values and their effect on stdin formatting."""

import pytest

from conftest import assert_golden, transcript

PROSE = (
    "This is a long paragraph. It has several sentences that go on for a while, so that wrapping at different "
    "widths produces visibly different output! Does it? Yes, it does, e.g. here.\n"
    "Second line of the same paragraph.\n"
    "\n"
    "* A list item that is also rather long and should wrap when the column is narrow enough for that.\n"
    "\n"
    "> A quoted paragraph that is long enough to wrap at the default column of seventy-two characters.\n"
)

WRAP_VALUES = ["72", "30", "1", "none", "paragraph", "sentence", "sentence:40", "sentence:1", "072", "+50",
               "sentence:+30"]


@pytest.mark.parametrize("wrap", WRAP_VALUES)
def test_wrap_values(wrap, run):
    """CATCHES: wrong wrapping for each documented --wrap value (column N, none, paragraph, sentence,
    sentence:N), mishandled list/blockquote prefixes when reducing the column, or rejecting integer spellings
    the reference accepts (leading zero or plus sign)."""
    result = run(["format", "--stdin-file-path", "doc.md", "--wrap", wrap], input=PROSE)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, "wrap_" + wrap.replace(":", "_").replace("+", "plus"))


def test_default_wrap_is_column_72(run):
    """CATCHES: a default Markdown wrap other than column 72 (the documented default)."""
    default = run(["format", "--stdin-file-path", "doc.md"], input=PROSE)
    explicit = run(["format", "--stdin-file-path", "doc.md", "--wrap", "72"], input=PROSE)
    assert default.returncode == 0
    assert default.stdout == explicit.stdout
    assert default.stdout.splitlines()[0] == b"This is a long paragraph. It has several sentences that go on for a"


INVALID_VALUES = {
    "wrap_word": ["--wrap", "bogus"],
    "wrap_zero": ["--wrap", "0"],
    "wrap_capitalized": ["--wrap", "Sentence"],
    "wrap_upper": ["--wrap", "PARAGRAPH"],
    "wrap_sentence_empty": ["--wrap", "sentence:"],
    "wrap_sentence_zero": ["--wrap", "sentence:0"],
    "wrap_sentence_word": ["--wrap", "sentence:abc"],
    "wrap_leading_space": ["--wrap", " 72"],
    "wrap_overflow": ["--wrap", "18446744073709551616"],
    "wrap_negative_equals": ["--wrap=-5"],
    "wrap_empty": ["--wrap", ""],
    "table_widths_word": ["--table-widths", "wide"],
    "table_widths_case": ["--table-widths", "Fit"],
    "table_widths_empty": ["--table-widths="],
    "line_width_zero": ["--line-width", "0"],
    "line_width_word": ["--line-width", "abc"],
    "line_width_empty": ["--line-width", ""],
    "line_width_decimal": ["--line-width", "1.5"],
    "line_width_overflow": ["--line-width", "18446744073709551616"],
    "line_width_space": ["--line-width", " 3"],
    "prose_width_zero": ["--prose-width", "0"],
    "prose_width_word": ["--prose-width", "wide"],
    "indent_width_zero": ["--indent-width", "0"],
    "indent_width_word": ["--indent-width", "x"],
    "indent_width_negative_equals": ["--indent-width=-2"],
}


@pytest.mark.parametrize("name", sorted(INVALID_VALUES))
def test_invalid_option_value(name, run):
    """CATCHES: accepting invalid option values (zero widths, words, wrong case, empty strings, overflowing
    integers), exiting with a status other than 2, or wording the clap-style 'invalid value' error differently
    (including the specific parser message such as 'value must be greater than 0')."""
    result = run(["format", "--stdin-file-path", "doc.md", *INVALID_VALUES[name]], input="x\n")
    assert result.returncode == 2
    assert result.stdout == b""
    assert_golden(transcript(result), __file__, f"invalid_{name}")


def test_wrap_error_message_lists_accepted_values(run):
    """CATCHES: a --wrap error that does not list every accepted form."""
    result = run(["format", "--stdin-file-path", "doc.md", "--wrap", "fast"], input="x\n")
    assert result.returncode == 2
    assert result.stderr == (
        b"error: invalid value 'fast' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive "
        b"integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n")


def test_zero_line_width_message(run):
    """CATCHES: a zero width reported as a parse failure instead of 'value must be greater than 0'."""
    result = run(["format", "--line-width", "0"])
    assert result.returncode == 2
    assert result.stderr == (b"error: invalid value '0' for '--line-width <LINE_WIDTH>': value must be greater "
                             b"than 0\n\nFor more information, try '--help'.\n")


YAML = (
    "root:\n"
    "    list: [alpha, beta, gamma, delta, epsilon, zeta]\n"
    "    nested:\n"
    "        key: value\n"
    "        other: {a: 1, b: 2}\n"
    "    text: \"This is a long prose string that should be represented as a folded block scalar so diffs "
    "reveal changes.\"\n"
    "    seq:\n"
    "      - one\n"
    "      - two\n"
)

YAML_OPTIONS = {
    "defaults": [],
    "line_width_40": ["--line-width", "40"],
    "line_width_20": ["--line-width", "20"],
    "prose_width_30": ["--prose-width", "30"],
    "prose_width_200": ["--prose-width", "200"],
    "indent_width_4": ["--indent-width", "4"],
    "indent_width_3": ["--indent-width", "3"],
    "compact": ["--compact"],
    "compact_line_width_30": ["--compact", "--line-width", "30"],
    "compact_indent_4": ["--compact", "--indent-width", "4"],
    "equals_syntax": ["--line-width=40", "--indent-width=4"],
}


@pytest.mark.parametrize("name", sorted(YAML_OPTIONS))
def test_yaml_layout_options(name, run):
    """CATCHES: --line-width not controlling when flow collections expand to block style, --prose-width not
    controlling folded scalar wrapping, --indent-width not setting block indentation, --compact not collapsing
    eligible block collections when they fit, or `--opt=value` syntax being rejected."""
    result = run(["format", "--stdin-file-path", "config.yaml", *YAML_OPTIONS[name]], input=YAML)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"yaml_{name}")


def test_yaml_defaults_match_documented_values(run):
    """CATCHES: YAML defaults that differ from --line-width 80, --prose-width 72 and --indent-width 2."""
    default = run(["format", "--stdin-file-path", "config.yaml"], input=YAML)
    explicit = run(["format", "--stdin-file-path", "config.yaml", "--line-width", "80", "--prose-width", "72",
                    "--indent-width", "2"], input=YAML)
    assert default.returncode == 0
    assert default.stdout == explicit.stdout
    assert default.stdout.startswith(b"root:\n  list: [alpha, beta, gamma, delta, epsilon, zeta]\n")


TABLE = (
    "Intro   text   before the tables.\n"
    "\n"
    "| Name | Description |\n"
    "|:-----|-----:|\n"
    "| A | Short text |\n"
    "| Longer name | x |\n"
    "\n"
    "+----------+------------------+\n"
    "| Name     | Description      |\n"
    "+==========+==================+\n"
    "| A        | Short text       |\n"
    "+----------+------------------+\n"
)


@pytest.mark.parametrize("widths", [None, "fit", "preserve"])
def test_table_widths(widths, run):
    """CATCHES: --table-widths fit not resizing pipe/grid columns to their contents, preserve not keeping
    source separator lengths, a default other than fit, or lost column alignment markers."""
    args = ["format", "--stdin-file-path", "doc.md"] + (["--table-widths", widths] if widths else [])
    result = run(args, input=TABLE)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"table_{widths or 'default'}")


EMPHASIS = "This is __strong__ and _emphasis_, but snake_case_word stays.\n\nA *star*   and **bold** too.\n"


@pytest.mark.parametrize("canonical", [False, True])
def test_canonical(canonical, run):
    """CATCHES: --canonical not rewriting _emphasis_/__strong__ to */** spellings, rewriting intraword
    underscores, or canonicalizing without the flag."""
    args = ["format", "--stdin-file-path", "doc.md"] + (["--canonical"] if canonical else [])
    result = run(args, input=EMPHASIS)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"canonical_{canonical}")


FOOTNOTES = (
    "Text   with a note.[^1]\n"
    "\n"
    "[^1]:   This footnote definition is long enough that wrapping at the default column changes its layout "
    "noticeably.\n"
)


@pytest.mark.parametrize("preserve", [False, True])
def test_preserve_footnotes(preserve, run):
    """CATCHES: footnote definitions not wrapped by default, or --preserve-footnotes not keeping them
    byte-for-byte."""
    args = ["format", "--stdin-file-path", "doc.md", "--wrap", "40"] + (["--preserve-footnotes"] if preserve else [])
    result = run(args, input=FOOTNOTES)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"footnotes_{preserve}")


def test_preserve_footnotes_overrides_front_matter(run):
    """CATCHES: front matter `footnotes: wrap` defeating --preserve-footnotes (the flag is the final exception)."""
    doc = "---\neditor_options:\n  markdown:\n    footnotes: wrap\n---\n" + FOOTNOTES
    result = run(["format", "--stdin-file-path", "doc.md", "--wrap", "40", "--preserve-footnotes"], input=doc)
    assert result.returncode == 0
    assert result.stdout.decode() == ("---\neditor_options:\n  markdown:\n    footnotes: wrap\n---\n"
                                      "Text with a note.[^1]\n\n" + FOOTNOTES.split("\n\n")[1])


def test_wrap_flag_overrides_front_matter_only_below_it(run):
    """CATCHES: front matter wrap options being ignored, or an explicit --wrap overriding the document's own
    editor_options (front matter overrides the base setting)."""
    doc = ("---\neditor_options:\n  markdown:\n    wrap: sentence\n---\n"
           "First sentence here. Second sentence follows it closely.\n")
    result = run(["format", "--stdin-file-path", "doc.md", "--wrap", "none"], input=doc)
    assert result.returncode == 0
    assert result.stdout == (b"---\neditor_options:\n  markdown:\n    wrap: sentence\n---\n"
                             b"First sentence here.\nSecond sentence follows it closely.\n")


def test_options_in_any_order(run):
    """CATCHES: rejecting options placed after --stdin-file-path or interleaved in another order."""
    first = run(["format", "--wrap", "sentence", "--stdin-file-path", "doc.md", "--canonical"], input=EMPHASIS)
    second = run(["format", "--canonical", "--stdin-file-path", "doc.md", "--wrap", "sentence"], input=EMPHASIS)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout == (b"This is **strong** and *emphasis*, but snake_case_word stays.\n\n"
                                             b"A *star* and **bold** too.\n")
