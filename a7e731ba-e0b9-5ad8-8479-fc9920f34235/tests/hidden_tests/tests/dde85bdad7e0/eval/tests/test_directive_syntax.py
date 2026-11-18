"""Exact parsing of `fmt:` directive comments in each host language.

YAML (`# fmt: ...`), Markdown (`<!-- fmt: ... -->`) and Python/R source
(`# fmt: ...`) each accept a different subset of the directive grammar. Invalid
or unsupported forms are errors for that file with a precise location; valid
forms change formatting of their target. Every case pins the complete stdout,
stderr and exit status.
"""

import pytest

from conftest import format_both_ways

YAML_BODY = "first:   1\nsecond: !markdown \"Some __strong__   text.\"\nlist: [a,b]\n"

YAML_DIRECTIVES = {
    "empty": "fmt:",
    "skip_scope_next": "fmt: skip scope=next",
    "skip_file_word": "fmt: skip file",
    "skip_scope_file": "fmt: skip scope=file",
    "skip_from_here_rejected": "fmt: skip scope=from-here",
    "skip_unknown_scope": "fmt: skip scope=bogus",
    "skip_extra_words": "fmt: skip this please",
    "off_scope_next_rejected": "fmt: off scope=next",
    "off_scope_file_rejected": "fmt: off scope=file",
    "off_unknown_scope": "fmt: off scope=later",
    "off_extra_words": "fmt: off now",
    "on_with_scope": "fmt: on scope=next",
    "markdown_file_scope_needs_option": "fmt: markdown scope=file",
    "markdown_from_here_needs_option": "fmt: markdown scope=from-here",
    "markdown_bad_wrap": "fmt: markdown wrap=wide",
    "markdown_bad_table_widths": "fmt: markdown table-widths=auto",
    "markdown_bad_canonical": "fmt: markdown canonical=maybe",
    "markdown_bad_footnotes": "fmt: markdown footnotes=sometimes",
    "markdown_unknown_option": "fmt: markdown colour=red",
    "markdown_bad_scope": "fmt: markdown scope=everywhere",
    "markdown_with_template_delimiters": 'fmt: markdown template.delimiters "<<" ">>"',
    "markdown_template_missing_close": 'fmt: markdown template.delimiters "<<"',
    "markdown_template_unquoted": "fmt: markdown template.delimiters << >>",
    "markdown_template_empty_values": 'fmt: markdown template.delimiters "" ""',
    "option_only_canonical": "fmt: canonical",
    "option_only_canonical_no": "fmt: canonical=no",
    "option_only_footnotes_preserve": "fmt: footnotes=preserve wrap=sentence",
    "option_only_unknown": "fmt: canonical=true shout=1",
    "template_one_value": 'fmt: template.delimiters "<<"',
    "template_three_values": 'fmt: template.delimiters "<<" ">>" "!!"',
    "template_unquoted_value": 'fmt: template.delimiters "<<" >>',
    "template_empty_value": 'fmt: template.delimiters "" ">>"',
    "template_bad_scope": 'fmt: template.delimiters "<<" ">>" scope=sometimes',
    "quote_glued_to_text": 'fmt: template.delimiters "<<"x ">>"',
    "quote_inside_word": 'fmt: template.delimiters a"b ">>"',
    "unterminated_quote": 'fmt: template.delimiters "<< ">>',
    "trailing_backslash_in_quote": 'fmt: template.delimiters "<<" "\\',
    "table_scope_from_here": "fmt: table scope=from-here",
    "table_scope_file": "fmt: table scope=file",
    "table_bad_scope": "fmt: table scope=bogus",
    "table_junk": "fmt: table wide",
    "table_compact_scope_file": "fmt: compact table scope=file",
    "compact_false_word": "fmt: compact false",
    "compact_equals_yes": "fmt: compact=yes",
    "compact_equals_maybe": "fmt: compact=maybe",
    "compact_option_maybe": "fmt: compact compact=maybe",
    "compact_junk": "fmt: compact please",
    "compact_bad_scope": "fmt: compact scope=forever",
    "embedded_scope_file": "fmt: embedded python scope=file",
    "embedded_two_names": "fmt: embedded python r",
    "embedded_scope_next_ok": "fmt: embedded scope=next python",
    "named_formatter_scope_from_here": "fmt: python scope=from-here",
    "named_formatter_extra_word": "fmt: python fast",
}


@pytest.mark.parametrize("name", sorted(YAML_DIRECTIVES))
def test_yaml_directive(name, run, workdir, golden):
    """CATCHES: a YAML directive parser that accepts unsupported scopes/options, rejects valid
    spellings, uses different error wording or locations, or applies the directive to the
    wrong target (skip/compact/markdown options/template delimiters)."""
    text = f"# {YAML_DIRECTIVES[name]}\n{YAML_BODY}"
    assert format_both_ways(run, workdir, "input.yaml", text) == golden(f"yaml_{name}")


MARKDOWN_BODY = "Some __strong__   text that is long enough to wrap around the default column width of seventy-two.\n\n| a | b |\n|---|---|\n| longer cell | x |\n"

MARKDOWN_DIRECTIVES = {
    "empty": "fmt:",
    "compact_table_rejected": "fmt: compact table",
    "embedded_rejected": "fmt: embedded python",
    "table_rejected": "fmt: table",
    "named_formatter_rejected": "fmt: python",
    "markdown_file_scope_needs_option": "fmt: markdown scope=file",
    "markdown_next_without_target": "fmt: markdown",
    "markdown_with_options": "fmt: markdown wrap=sentence canonical=true",
    "markdown_template_delimiters": 'fmt: markdown template.delimiters "<<" ">>" scope=file',
    "wrap_none": "fmt: wrap=none",
    "wrap_sentence_width": "fmt: wrap=sentence:30",
    "wrap_integer": "fmt: wrap=40",
    "wrap_bad": "fmt: wrap=0",
    "canonical_bare": "fmt: canonical",
    "canonical_bad": "fmt: canonical=perhaps",
    "table_widths_preserve": "fmt: table-widths=preserve",
    "footnotes_bad": "fmt: footnotes=maybe",
    "skip_scope_from_here": "fmt: skip scope=from-here",
    "off_scope_next": "fmt: off scope=next",
    "on_with_scope": "fmt: on scope=file",
    "bad_quoting": 'fmt: template.delimiters "<<',
    "unknown_option": "fmt: wrap=none sparkle=yes",
}


@pytest.mark.parametrize("name", sorted(MARKDOWN_DIRECTIVES))
def test_markdown_directive(name, run, workdir, golden):
    """CATCHES: a Markdown directive parser that accepts YAML-only directives (table, compact,
    embedded formatters), mis-scopes option directives, or reports errors with different
    text, line/column or exit status."""
    text = f"<!-- {MARKDOWN_DIRECTIVES[name]} -->\n\n{MARKDOWN_BODY}"
    assert format_both_ways(run, workdir, "input.md", text) == golden(f"markdown_{name}")


SOURCE_DIRECTIVES = {
    "empty": "fmt:",
    "compact_rejected": "fmt: compact",
    "table_rejected": "fmt: table",
    "markdown_file_scope_needs_option": "fmt: markdown scope=file",
    "markdown_comment_target": "fmt: markdown wrap=sentence",
    "named_formatter_scope_file": "fmt: python scope=file",
    "embedded_scope_from_here": "fmt: embedded r scope=from-here",
    "skip_file": "fmt: skip file",
    "off_scope_file": "fmt: off scope=file",
    "unknown_option": "fmt: wrap=none glitter=1",
    "template_two_values_needed": 'fmt: template.delimiters "<<"',
}

SOURCE_BODY = "# First sentence here.   Second   sentence follows it.\n# Third line of the comment.\nx = 1\n"


@pytest.mark.parametrize("name", sorted(SOURCE_DIRECTIVES))
@pytest.mark.parametrize("suffix", ["py", "R"])
def test_source_directive(name, suffix, run, workdir, golden):
    """CATCHES: Python/R directive handling that accepts YAML-only collection directives,
    allows broad scopes for embedded formatters, or formats the wrong comment block."""
    text = f"# {SOURCE_DIRECTIVES[name]}\n{SOURCE_BODY}"
    assert format_both_ways(run, workdir, f"script.{suffix}", text) == golden(f"source_{suffix}_{name}")


def test_quoted_delimiter_escapes(run, workdir, golden):
    """CATCHES: wrong decoding of `\\"`, `\\\\` and unknown escapes inside quoted directive
    tokens, which changes which delimiter text is preserved."""
    text = (
        '# fmt: template.delimiters "\\\\[" "]\\q" scope=file\n'
        'a:   "\\[ keep   this ]q"\n'
        'b: [x,   y]\n'
    )
    assert format_both_ways(run, workdir, "input.yaml", text) == golden("quoted_delimiter_escapes")


def test_two_file_scope_directives_merge(run, workdir, golden):
    """CATCHES: a file-scope merge that lets a later `scope=file` directive discard an earlier
    one; compaction disabled file-wide and `skip file` must both hold."""
    text = "a: [1,  2]\n# fmt: compact=false scope=file\nb:\n  - 1\n# fmt: skip file\nc:    3\n"
    assert format_both_ways(run, workdir, "input.yaml", text, "--compact") == golden("file_scope_merge")


def test_file_scope_template_then_compact_merge(run, workdir, golden):
    """CATCHES: dropping template delimiters when another file-scope directive follows."""
    text = (
        'a: "<< keep   spacing >>"\n'
        '# fmt: template.delimiters "<<" ">>" scope=file\n'
        "# fmt: compact scope=file\n"
        "b:\n  - x\n  - y\n"
    )
    assert format_both_ways(run, workdir, "input.yaml", text) == golden("file_scope_template_compact")


def test_option_only_yaml_directive_targets_markdown_scalar(run, workdir, golden):
    """CATCHES: applying a YAML option-only directive to a plain scalar, or not applying it to
    the next `!markdown` scalar (documented in the directive reference)."""
    text = '# fmt: canonical=true\nfirst: !markdown "This is __strong__."\nsecond: "This is __not__ Markdown."\n'
    assert format_both_ways(run, workdir, "input.yaml", text) == golden("option_only_targets_markdown")


def test_markdown_word_after_options_is_not_an_action(run, workdir, golden):
    """CATCHES: treating a `markdown` word that follows an option (`fmt: wrap=sentence markdown`)
    as the Markdown action; the directive stays option-only, so the plain scalar is not
    sentence-wrapped and only its redundant quotes are dropped."""
    text = "# fmt: wrap=sentence markdown\nbody: \"One sentence here.   Two sentences here.\"\n"
    assert format_both_ways(run, workdir, "input.yaml", text) == golden("options_then_markdown")


def test_markdown_directive_trailing_whitespace(run, workdir, golden):
    """CATCHES: treating trailing whitespace inside the HTML comment as an extra directive token."""
    text = "<!-- fmt: wrap=none   \t -->\n\nA   long paragraph that would otherwise be wrapped at the default column width of seventy two.\n"
    assert format_both_ways(run, workdir, "input.md", text) == golden("markdown_trailing_whitespace")


OFF_REGION_FORMS = [
    "fmt:", "fmt: markdown wrap=none", "fmt: markdown", 'fmt: template.delimiters "<<" ">>"',
    "fmt: template.delimiters open=<< close=>>", "fmt: compact table", "fmt: embedded python",
    "fmt: embedded", "fmt: table compact", "fmt: python",
    "fmt: wrap=none canonical=yes footnotes=no table-widths=preserve scope=from-here",
    "fmt: canonical", "fmt: skip file", "fmt: off scope=from-here", "fmt: wrap=bogus scope=bogus",
    'fmt: "unterminated', "fmt: skip scope=next", "fmt: skip scope=file",
]


@pytest.mark.parametrize("host", ["py", "R", "md"])
def test_directives_inside_off_region_are_preserved(host, run, workdir, golden):
    """CATCHES: rejecting or acting on malformed or unsupported directive lines inside a
    `fmt: off` region (they are preserved verbatim; only a recognised `fmt: on` resumes),
    or failing to resume formatting after `fmt: on`."""
    if host == "md":
        text = "Para   one.\n\n<!-- fmt: off -->\n" + "".join(f"<!-- {form} -->\n" for form in OFF_REGION_FORMS)
        text += "Keep   this.\n<!-- fmt: on -->\n\nPara   two.\n"
    else:
        text = "x = 1\n# fmt: off\n" + "".join(f"# {form}\n" for form in OFF_REGION_FORMS)
        text += "y    = 2\n# fmt: on\n#| a:   1\n"
    assert format_both_ways(run, workdir, f"doc.{host}", text) == golden(f"off_region_{host}")
