"""Spec markdown syntax behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_bom_crlf_and_preserve_footnotes_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "bom crlf and preserve footnotes are preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '\ufeff#   Title ##\r\n'
        '\r\n'
        '[^a]: keep   spacing. Keep one line.\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--preserve-footnotes'],
        input=stdin,
    )
    assert result.stdout == (RES / 'bom_crlf_and_preserve_footnotes_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_ambiguous_nested_container_continuations_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "markdown ambiguous nested container continuations are preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- foo\n'
        '  - bar\n'
        '\n'
        '    is this a top level code quote or a 2nd paragraph on the previous list?\n'
        '\n'
        '* > * this is a list (quote (list))\n'
        '    > is this prose or is this a 2nd blockquote ?\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '28'], input=stdin)
    assert result.stdout == (RES / 'markdown_ambiguous_nested_container_continuations_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '28', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_canonical_preserves_intraword_underscores_and_code_spans(run, workdir):
    """CATCHES: reimplementations that break "markdown canonical preserves intraword underscores and code spans" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'This keeps foo_bar_baz and `code_value` but changes _emphasis_.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'This keeps foo_bar_baz and `code_value` but changes *emphasis*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_canonical_preserves_paired_inline_html_content_in_headings(run, workdir):
    """CATCHES: reimplementations that break "markdown canonical preserves paired inline html content in headings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '# <span>_x_</span> and _y_\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'# <span>_x_</span> and *y*\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_canonical_preserves_non_emphasis_inline_tokens(run, workdir):
    """CATCHES: reimplementations that break "markdown canonical preserves non emphasis inline tokens" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'Keep [x](/_path_) ![alt](/_img_) <https://example.com/_id_> {{< relref "_slug_" >}} but change _emphasis_.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'Keep [x](/_path_) ![alt](/_img_) <https://example.com/_id_> {{< relref "_slug_" >}} but change *emphasis*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_canonical_preserves_reference_style_links_in_headings(run, workdir):
    """CATCHES: reimplementations that break "markdown canonical preserves reference style links in headings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '# [__a__][id] and __x__\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'# [__a__][id] and **x**\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_canonical_preserves_unsupported_inline_spans_in_headings(run, workdir):
    """CATCHES: reimplementations that break "markdown canonical preserves unsupported inline spans in headings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '# ~~_keep_~~ and _change_\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'# ~~_keep_~~ and *change*\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_canonical_preserves_unsupported_underscore_constructs(run, workdir):
    """CATCHES: reimplementations that break "markdown canonical preserves unsupported underscore constructs" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'This _literal marker stays.\n'
        '\n'
        'This __strong marker stays.\n'
        '\n'
        'This literal_ marker stays.\n'
        '\n'
        'This literal__ marker stays.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'markdown_canonical_preserves_unsupported_underscore_constructs.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_code_fence_info_normalizes_attribute_language_forms(run, workdir):
    """CATCHES: reimplementations that break "markdown code fence info normalizes attribute language forms" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '``` {.haskell .numberLines}\n'
        'main = pure ()\n'
        '```\n'
        '\n'
        '```haskell {.haskell .numberLines #sort}\n'
        'main = pure ()\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_code_fence_info_normalizes_attribute_language_forms.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_code_fence_info_removes_duplicate_bare_language_after_class(run, workdir):
    """CATCHES: reimplementations that break "markdown code fence info removes duplicate bare language after class" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```{.yaml yaml}\n'
        'a:    1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_code_fence_info_removes_duplicate_bare_language_after_class.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_display_math_with_inline_delimiters_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "markdown display math with inline delimiters is preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '$$ E = mc^2 + very_long_symbol\n'
        'more math content\n'
        '$$\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'markdown_display_math_with_inline_delimiters_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '12', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_heading_attributes_normalize_without_preceding_space(run, workdir):
    """CATCHES: reimplementations that break "markdown heading attributes normalize without preceding space" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '## Title{.a  .b }\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b'## Title {.a .b}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_existing_indented_split_links_preserve_split_style(run, workdir):
    """CATCHES: reimplementations that break "markdown existing indented split links preserve split style" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'A [compact label](\n'
        '  https://example.com/a/very/long/destination/path\n'
        ') after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_existing_indented_split_links_preserve_split_style.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_existing_split_links_normalize_label_without_changing_split_style(run, workdir):
    """CATCHES: reimplementations that break "markdown existing split links normalize label without changing split style" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'A [ label   text ](\n'
        'https://example.com/a/very/long/destination/path\n'
        ') after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_existing_split_links_normalize_label_without_changing_split_style.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_generated_split_links_keep_surrounding_paragraph_text(run, workdir):
    """CATCHES: reimplementations that break "markdown generated split links keep surrounding paragraph text" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'See [the documentation](https://example.com/really/really/really/really/long/path "A helpful title") for details.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'markdown_generated_split_links_keep_surrounding_paragraph_text.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_generated_split_links_split_title_from_destination_when_needed(run, workdir):
    """CATCHES: reimplementations that break "markdown generated split links split title from destination when needed" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'See [docs](https://e.co/path "short title") after.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '32'], input=stdin)
    assert result.stdout == (RES / 'markdown_generated_split_links_split_title_from_destination_when_needed.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_heading_closing_hashes_before_attributes_can_leave_empty_headings(run, workdir):
    """CATCHES: reimplementations that break "markdown heading closing hashes before attributes can leave empty headings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# # {#id}\n'
        '### ### {#id}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_heading_closing_hashes_before_attributes_can_leave_empty_headings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_heading_closing_hashes_are_removed_before_attributes(run, workdir):
    """CATCHES: reimplementations that break "markdown heading closing hashes are removed before attributes" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '# Title ### {#id}\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b'# Title {#id}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_heading_closing_hashes_can_leave_empty_headings(run, workdir):
    """CATCHES: reimplementations that break "markdown heading closing hashes can leave empty headings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# #\n'
        '### ###\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_heading_closing_hashes_can_leave_empty_headings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_hugo_shortcode_tokens_leave_the_body_as_markdown(run, workdir):
    """CATCHES: reimplementations that break "markdown hugo shortcode tokens leave the body as markdown" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '{{< notice >}}\n'
        'This    Markdown body formats normally.\n'
        '{{< /notice >}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_hugo_shortcode_tokens_leave_the_body_as_markdown.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_hugo_shortcodes_are_not_generic_template_spans(run, workdir):
    """CATCHES: reimplementations that break "markdown hugo shortcodes are not generic template spans" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'Before {{< ref "target" >}} after    text.\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b'Before {{< ref "target" >}} after text.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_inline_footnote_refs_stay_attached_to_preceding_punctuation(run, workdir):
    """CATCHES: reimplementations that break "markdown inline footnote refs stay attached to preceding punctuation" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'This has a footnote.[^id]\n'
        '\n'
        '[^id]: preserved\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--preserve-footnotes'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_inline_footnote_refs_stay_attached_to_preceding_punctuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--preserve-footnotes', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_inline_validation_ignores_code_span_content(run, workdir):
    """CATCHES: reimplementations that break "markdown inline validation ignores code span content" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'This  has `code <x>` and  spaces.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == b'This has `code <x>` and spaces.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_links_support_nested_image_labels_when_simple(run, workdir):
    """CATCHES: reimplementations that break "markdown links support nested image labels when simple" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'A [ ![ alt   text ](img.png)   label ](dest) after.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'A [![alt text](img.png) label](dest) after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_links_with_escaped_targets_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "markdown links with escaped targets are preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'A [  label  ](a\\)b) and [  title  ](dest "a \\"title\\"") after.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'A [  label  ](a\\)b) and [  title  ](dest "a \\"title\\"") after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_long_fig_alt_attributes_preserve_document_line_endings_1(run, workdir):
    """CATCHES: reimplementations that break "markdown long fig alt attributes preserve document line endings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = '![](quarto.png){fig-alt="Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"}\r\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '48'], input=stdin)
    assert result.stdout == (RES / 'markdown_long_fig_alt_attributes_preserve_document_line_endings_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_long_fig_alt_attributes_preserve_document_line_endings_2(run, workdir):
    """CATCHES: reimplementations that break "markdown long fig alt attributes preserve document line endings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = '![](quarto.png){fig-alt="Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"}\r'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '48'], input=stdin)
    assert result.stdout == (
        b'![](quarto.png){\r'
        b'  fig-alt="Alpha beta gamma delta epsilon zeta\r'
        b'eta theta iota kappa lambda mu"\r'
        b'}\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_long_links_split_destination_onto_own_line(run, workdir):
    """CATCHES: reimplementations that break "markdown long links split destination onto own line" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'A [compact label](https://example.com/a/very/long/destination/path) after.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'markdown_long_links_split_destination_onto_own_line.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_preserves_non_ascii_whitespace_before_block_markers(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves non ascii whitespace before block markers" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '\xa0# heading\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b'\xc2\xa0# heading\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_output_trims_trailing_whitespace_and_ends_with_newline(run, workdir):
    """CATCHES: reimplementations that break "markdown output trims trailing whitespace and ends with newline" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'First line \t\n'
        '\n'
        '```text\n'
        'kept? \t\n'
        '```\n'
        'last line\t'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_output_trims_trailing_whitespace_and_ends_with_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_block_attribute_lines_with_key_value_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc block attribute lines with key value are preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Paragraph before with enough words.\n'
        '{width=50%}\n'
        'Following paragraph with enough words.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_block_attribute_lines_with_key_value_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_citations_are_supported_inline_tokens(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc citations are supported inline tokens" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Alpha beta [see @doe2020] gamma delta epsilon.\n'
        '\n'
        'Alpha beta [-@doe2020] gamma delta epsilon.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '25'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_citations_are_supported_inline_tokens.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_parenthesized_link_titles_are_supported(run, workdir):
    """CATCHES: reimplementations that break "markdown parenthesized link titles are supported" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'A [  label  ](https://example.com (a title)) after.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'A [label](https://example.com (a title)) after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_preserves_prose_that_looks_like_unsupported_ordered_markers(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves prose that looks like unsupported ordered markers" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'And. this is a paragraph that should stay as prose.\n'
        '\n'
        '(abc) this is also prose that should not be a list.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_prose_that_looks_like_unsupported_ordered_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_preserves_quarto_inline_attribute_at_heading_end(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto inline attribute at heading end" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# [text]{.class}\n'
        '# `code`{.class}\n'
        '# [link](dest){.class}\n'
        '# ![alt](img){.class}\n'
        '# [@cite]{.class}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_quarto_inline_attribute_at_heading_end.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_inline_html_at_paragraph_start(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto inline html at paragraph start" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '<span>raw</span> text\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'<span>raw</span> text\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_raw_tex_separator_1(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto raw tex separator" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    stdin = (
        'before \\LaTeX\n'
        'after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_quarto_raw_tex_separator_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_raw_tex_separator_2(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto raw tex separator" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    stdin = 'before words \\LaTeX after words\n'
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '20'], input=stdin)
    assert result.stdout == b'before words \\LaTeX after words\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_raw_tex_separator_3(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto raw tex separator" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    stdin = (
        '- before \\LaTeX\n'
        '  after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_quarto_raw_tex_separator_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_raw_tex_separator_4(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto raw tex separator" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    stdin = (
        '> before \\LaTeX\n'
        '> after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_quarto_raw_tex_separator_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_raw_tex_separator_5(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto raw tex separator" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    stdin = (
        'Text.[^x]\n'
        '\n'
        '[^x]: before \\LaTeX\n'
        '  after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_quarto_raw_tex_separator_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_tab_indented_code_1(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto tab indented code" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = '\tcode\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'\tcode\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_tab_indented_code_2(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto tab indented code" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '\tTitle\n'
        '\t====\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_quarto_tab_indented_code_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_tab_indented_code_3(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto tab indented code" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = '\t***\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'\t***\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_tab_indented_code_4(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto tab indented code" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = '\t> code\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'\t> code\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_tab_indented_code_5(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto tab indented code" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = '  \t> code\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'  \t> code\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_tab_indented_code_6(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto tab indented code" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = ' \t- item\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b' \t- item\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_unicode_whitespace_1(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto unicode whitespace" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = 'alpha\xa0beta\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'alpha\xc2\xa0beta\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_unicode_whitespace_2(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto unicode whitespace" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = '# alpha\xa0\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'# alpha\xc2\xa0\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_unicode_whitespace_3(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto unicode whitespace" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = '- \xa0alpha beta\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'- \xc2\xa0alpha beta\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_unicode_whitespace_4(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto unicode whitespace" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = '> \xa0alpha beta\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'> \xc2\xa0alpha beta\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_quarto_chunk_header_promotion_preserves_document_line_endings_1(run, workdir):
    """CATCHES: reimplementations that break "markdown quarto chunk header promotion preserves document line endings" (markdown syntax); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    files = {
        'yamark.toml': (
            '[embedded.r]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())", "{path}"], path_suffix = ".R" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```{r, echo=FALSE, fig.width=8}\r\n'
        '1 + 1\r\n'
        '```\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.qmd', '--wrap', '24', '--config', 'yamark.toml'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_quarto_chunk_header_promotion_preserves_document_line_endings_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_markdown_quarto_chunk_header_promotion_preserves_document_line_endings_2(run, workdir):
    """CATCHES: reimplementations that break "markdown quarto chunk header promotion preserves document line endings" (markdown syntax); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    files = {
        'yamark.toml': (
            '[embedded.r]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())", "{path}"], path_suffix = ".R" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```{r, echo=FALSE, fig.width=8}\r'
        '1 + 1\r'
        '```\r'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.qmd', '--wrap', '24', '--config', 'yamark.toml'],
        input=stdin,
    )
    assert result.stdout == (
        b'```{r}\r'
        b'#| echo: false\r'
        b'#| fig.width: 8\r'
        b'1 + 1\r'
        b'```\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_markdown_quarto_chunk_headers_are_promoted_to_option_lines(run, workdir):
    """CATCHES: reimplementations that break "markdown quarto chunk headers are promoted to option lines" (markdown syntax); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.r]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())", "{path}"], path_suffix = ".R" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```{r, echo=FALSE, fig.width=8}\n'
        '1 + 1\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.qmd', '--wrap', '24', '--config', 'yamark.toml'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_quarto_chunk_headers_are_promoted_to_option_lines.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_markdown_quarto_divs_format_supported_children(run, workdir):
    """CATCHES: reimplementations that break "markdown quarto divs format supported children" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '::: {.callout-note}\n'
        '#   Keep ##\n'
        'text   with   spacing\n'
        ':::\n'
        '\n'
        '#   Change ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_quarto_divs_format_supported_children.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_quoted_link_titles_are_supported(run, workdir):
    """CATCHES: reimplementations that break "markdown quoted link titles are supported" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'A [  label  ](https://example.com "a title") after.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'A [label](https://example.com "a title") after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_reference_style_links_preserve_source_spelling_1(run, workdir):
    """CATCHES: reimplementations that break "markdown reference style links preserve source spelling" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = 'This [![ alt text ](img.png)][fixture-docs] keeps    spacing.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'This [![ alt text ](img.png)][fixture-docs] keeps spacing.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_reference_style_links_preserve_source_spelling_2(run, workdir):
    """CATCHES: reimplementations that break "markdown reference style links preserve source spelling" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = 'This [![ alt text ](img.png)][fixture-docs] keeps    spacing.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'This [![ alt text ](img.png)][fixture-docs] keeps    spacing.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_simple_link_and_image_labels_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "markdown simple link and image labels are normalized" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'A [ label   text ](dest) and ![ alt   text ](img.png){ fig-alt="A   figure" }.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'A [label text](dest) and ![alt text](img.png){fig-alt="A figure"}.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_risky_blocks_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "markdown risky blocks are preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '    code   keeps   spacing\n'
        '\n'
        '$$\n'
        'x   +   y\n'
        '$$\n'
        '\n'
        '<!-- ordinary\n'
        'html comment -->\n'
        '\n'
        '{{< shortcode param="keep   spacing" >}}\n'
        '\n'
        '| pandoc line   block\n'
        '| keeps   spacing\n'
        '\n'
        '[ref]: http://example.com/a   "title"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_risky_blocks_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_setext_headings_accept_single_character_underlines(run, workdir):
    """CATCHES: reimplementations that break "markdown setext headings accept single character underlines" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Title\n'
        '=\n'
        '\n'
        'Subtitle\n'
        '-\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_setext_headings_accept_single_character_underlines.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_single_line_raw_tex_preserves_only_that_line(run, workdir):
    """CATCHES: reimplementations that break "markdown single line raw tex preserves only that line" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '\\begin{note} keep    raw \\end{note}\n'
        'This paragraph should wrap to sentence. This one too.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_single_line_raw_tex_preserves_only_that_line.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_spaced_image_fig_alt_attribute_is_normalized_for_pandoc(run, workdir):
    """CATCHES: reimplementations that break "markdown spaced image fig alt attribute is normalized for pandoc" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '![](mcp-repl-useR-lightning-assets/chat-scenario.png) { fig-alt="A chat interface where a user asks an agent to explore a dataset and build a first model. The agent responds by running several bash tool calls with Rscript." }\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '88'], input=stdin)
    assert result.stdout == (RES / 'markdown_spaced_image_fig_alt_attribute_is_normalized_for_pandoc.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_structured_blocks_preserve_unsupported_inline_source(run, workdir):
    """CATCHES: reimplementations that break "markdown structured blocks preserve unsupported inline source" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- This ~~struck text keeps    spacing~~.\n'
        '\n'
        '> This ~~struck text keeps    spacing~~.\n'
        '\n'
        'Term\n'
        ': This ~~struck text keeps    spacing~~.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_structured_blocks_preserve_unsupported_inline_source.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_template_spans_preserve_headings(run, workdir):
    """CATCHES: reimplementations that break "markdown template spans preserve headings" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '#   Title {{ keep   spacing }}   ##\n'
        '\n'
        'Setext {{ keep   spacing }}\n'
        '====\n'
        '\n'
        '#   Normal ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_template_spans_preserve_headings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unknown_markdown_code_fences_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "unknown markdown code fences are preserved" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```unknown    {#cell}\n'
        'body\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'unknown_markdown_code_fences_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unmatched_markdown_code_fence_is_preserved_as_raw_source(run, workdir):
    """CATCHES: reimplementations that break "unmatched markdown code fence is preserved as raw source" (markdown syntax); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```yaml\n'
        'a:    b\n'
        '# still inside the unmatched fence\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'unmatched_markdown_code_fence_is_preserved_as_raw_source.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
