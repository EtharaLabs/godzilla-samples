"""Spec markdown wrapping behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_markdown_column_wrapping_uses_dominant_crlf_without_final_newline(run, workdir):
    """CATCHES: reimplementations that break "markdown column wrapping uses dominant crlf without final newline" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Intro line\r\n'
        'This paragraph has enough words to wrap'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_column_wrapping_uses_dominant_crlf_without_final_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_existing_split_links_reflow_when_wrapping(run, workdir):
    """CATCHES: reimplementations that break "markdown existing split links reflow when wrapping" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'A\n'
        '[compact label](\n'
        'https://example.com/a/very/long/destination/path\n'
        ')\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'markdown_existing_split_links_reflow_when_wrapping.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_footnote_at_eof_without_final_newline_wraps(run, workdir):
    """CATCHES: reimplementations that break "markdown footnote at eof without final newline wraps" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '[^long]: This footnote explains that comments were removed because  people used comments to hold parsing directives and enough extra words  to wrap.'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_footnote_at_eof_without_final_newline_wraps.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_hard_break_spaces_convert_to_backslash_by_default(run, workdir):
    """CATCHES: reimplementations that break "markdown hard break spaces convert to backslash by default" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'line with hard break  \n'
        'next line\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_hard_break_spaces_convert_to_backslash_by_default.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_hard_break_paragraph_segments_are_wrapped(run, workdir):
    """CATCHES: reimplementations that break "markdown hard break paragraph segments are wrapped" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'alpha  \n'
        'This long prose line should wrap after hard break and preserve semantics.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'markdown_hard_break_paragraph_segments_are_wrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_hard_break_wrap_none_preserves_soft_line_boundaries(run, workdir):
    """CATCHES: reimplementations that break "markdown hard break wrap none preserves soft line boundaries" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'alpha\n'
        'beta  \n'
        'gamma\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_hard_break_wrap_none_preserves_soft_line_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_hard_breaks_inside_structured_blocks_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "markdown hard breaks inside structured blocks are normalized" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- first line  \n'
        '  second line\n'
        '\n'
        '> first line  \n'
        '> second line\n'
        '\n'
        'Term\n'
        ': first line  \n'
        '    second line\n'
        '\n'
        '[^note]: first line  \n'
        '    second line\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_hard_breaks_inside_structured_blocks_are_normalized.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_inline_code_suffix_stays_attached_when_wrapping(run, workdir):
    """CATCHES: reimplementations that break "markdown inline code suffix stays attached when wrapping" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'Use `NA`s when values are missing in this paragraph.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_inline_code_suffix_stays_attached_when_wrapping.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_link_definitions_are_preserved_and_inline_html_wraps(run, workdir):
    """CATCHES: reimplementations that break "markdown link definitions are preserved and inline html wraps" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '[ref]: https://example.com\n'
        '  "title   spacing"\n'
        '\n'
        'Use <span>keep    spacing</span> here.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_link_definitions_are_preserved_and_inline_html_wraps.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_long_fig_alt_attributes_split_and_wrap_when_safe(run, workdir):
    """CATCHES: reimplementations that break "markdown long fig alt attributes split and wrap when safe" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '![](quarto.png){fig-alt="Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"}\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '48'], input=stdin)
    assert result.stdout == (RES / 'markdown_long_fig_alt_attributes_split_and_wrap_when_safe.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_sentence_column_wrap_is_idempotent_and_preserves_crlf_1(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wrap is idempotent and preserves crlf" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = 'Short first. This second sentence contains enough words to wrap across the requested column. Short last.\r\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'markdown_sentence_column_wrap_is_idempotent_and_preserves_crlf_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_sentence_column_wrap_is_idempotent_and_preserves_crlf_2(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wrap is idempotent and preserves crlf" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'Short first.\r\n'
        'This second sentence contains\r\n'
        'enough words to wrap across the\r\n'
        'requested column.\r\n'
        'Short last.\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'markdown_sentence_column_wrap_is_idempotent_and_preserves_crlf_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:32', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_sentence_column_wrap_rejects_invalid_widths_1(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wrap rejects invalid widths" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = 'One sentence. Another sentence.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:0'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: invalid value 'sentence:0' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n"
        '\n'
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_markdown_sentence_column_wrap_rejects_invalid_widths_2(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wrap rejects invalid widths" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = 'One sentence. Another sentence.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: invalid value 'sentence:' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n"
        '\n'
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_markdown_sentence_column_wrap_rejects_invalid_widths_3(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wrap rejects invalid widths" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = 'One sentence. Another sentence.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:nope'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: invalid value 'sentence:nope' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n"
        '\n'
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_markdown_sentence_column_wrap_rejects_invalid_widths_4(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wrap rejects invalid widths" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = 'One sentence. Another sentence.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:24:32'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: invalid value 'sentence:24:32' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n"
        '\n'
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_markdown_wrapping_allows_angle_autolink_continuation_lines(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping allows angle autolink continuation lines" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: wrap=20 scope=next -->\n'
        'Send mail to <a@example.com> for follow up.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_allows_angle_autolink_continuation_lines.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_1(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes ordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    stdin = 'preamble 1. marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '10'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_2(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes ordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    stdin = 'preamble 1) marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '10'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_3(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes ordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    stdin = 'preamble a. marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '10'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_4(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes ordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    stdin = 'preamble i. marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '10'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_5(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes ordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    stdin = 'preamble (a) marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '10'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_ordered_markers_when_no_safe_break_fits_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_quote_markers_when_no_safe_break_fits(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes quote markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'preamble > marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '9'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_quote_markers_when_no_safe_break_fits.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_unordered_markers_when_no_safe_break_fits_1(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes unordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = 'preamble + marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '9'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_unordered_markers_when_no_safe_break_fits_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_unordered_markers_when_no_safe_break_fits_2(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes unordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = 'preamble - marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '9'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_unordered_markers_when_no_safe_break_fits_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_escapes_unordered_markers_when_no_safe_break_fits_3(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping escapes unordered markers when no safe break fits" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = 'preamble * marker remains prose after wrapping.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '9'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_escapes_unordered_markers_when_no_safe_break_fits_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_keeps_emphasis_spans_together(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping keeps emphasis spans together" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'This is *very important phrase* after words.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '18'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_keeps_emphasis_spans_together.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_keeps_latex_commands_with_balanced_braces_together(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping keeps latex commands with balanced braces together" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'This uses \\command{alpha beta gamma} after words.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_keeps_latex_commands_with_balanced_braces_together.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_keeps_line_start_autolinks_in_prose(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping keeps line start autolinks in prose" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'First paragraph.\n'
        '<https://example.com/>.\n'
        '\n'
        'Contact us.\n'
        '<a@example.com>.\n'
        '\n'
        'Second paragraph should wrap into multiple lines now.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_keeps_line_start_autolinks_in_prose.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_preserves_inline_tokens_and_unsupported_inline_source(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping preserves inline tokens and unsupported inline source" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'A `code span with spaces` after.\n'
        '\n'
        'A [label with spaces](dest) after.\n'
        '\n'
        'This ~~struck text keeps    spacing~~.\n'
        '\n'
        'This `unterminated code span keeps    spacing.\n'
        '\n'
        'This [reference][id] keeps    spacing.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '18'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_preserves_inline_tokens_and_unsupported_inline_source.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wrapping_preserves_paragraphs_when_new_lines_would_start_blocks(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping preserves paragraphs when new lines would start blocks" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'Alpha --- beta\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '5'], input=stdin)
    assert result.stdout == b'Alpha --- beta\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '5', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_wrapping_wraps_reference_style_links_as_atomic_tokens(run, workdir):
    """CATCHES: reimplementations that break "markdown wrapping wraps reference style links as atomic tokens" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'This paragraph links to [yamark](https://example.com/yamark) and uses a reference [fixture][fixture-docs] before a footnote.[^long]\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '80'], input=stdin)
    assert result.stdout == (RES / 'markdown_wrapping_wraps_reference_style_links_as_atomic_tokens.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_wraps_raw_looking_text_inside_protected_inline_spans(run, workdir):
    """CATCHES: reimplementations that break "markdown wraps raw looking text inside protected inline spans" (markdown wrapping); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'This paragraph includes `C:\\Users\xa0name`, [link \\alpha](dest), $\\beta + x$, and <span>HTML\xa0text</span> while enough words remain to wrap safely.\n'
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_wraps_raw_looking_text_inside_protected_inline_spans.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
