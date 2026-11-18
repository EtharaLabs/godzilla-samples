"""Spec markdown containers behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_markdown_alphabetic_roman_and_parenthesized_ordered_lists_are_formatted(run, workdir):
    """CATCHES: reimplementations that break "markdown alphabetic roman and parenthesized ordered lists are formatted" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'a.  alphabetic    item\n'
        'IV)  roman    item\n'
        '(1)  parenthesized    item\n'
        '(a)  parenthesized    alphabetic    item\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_alphabetic_roman_and_parenthesized_ordered_lists_are_formatted.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_blockquotes_format_reachable_child_code_fences(run, workdir):
    """CATCHES: reimplementations that break "markdown blockquotes format reachable child code fences" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '> quoted intro\n'
        '> ```python\n'
        '> x   =   1\n'
        '> ```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_blockquotes_format_reachable_child_code_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_blockquotes_preserve_nested_lists_when_not_safely_wrappable(run, workdir):
    """CATCHES: reimplementations that break "markdown blockquotes preserve nested lists when not safely wrappable" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '> - item\n'
        '>   - nested\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_blockquotes_preserve_nested_lists_when_not_safely_wrappable.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_blockquotes_with_multiple_paragraphs_wrap_inside_quote_markers(run, workdir):
    """CATCHES: reimplementations that break "markdown blockquotes with multiple paragraphs wrap inside quote markers" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '> First paragraph has many words that should wrap.\n'
        '>\n'
        '> Second paragraph has many words that should wrap.\n'
        '>\n'
        '> Third paragraph has many words that should wrap.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '28'], input=stdin)
    assert result.stdout == (RES / 'markdown_blockquotes_with_multiple_paragraphs_wrap_inside_quote_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_footnote_block_bodies_are_formatted_recursively(run, workdir):
    """CATCHES: reimplementations that break "markdown footnote block bodies are formatted recursively" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '[^note]:\n'
        '    #   Nested title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_footnote_block_bodies_are_formatted_recursively.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_footnotes_and_heading_attributes_are_formatted(run, workdir):
    """CATCHES: reimplementations that break "markdown footnotes and heading attributes are formatted" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '#   Title   { #id   .class }   ##\n'
        '\n'
        '[^note]: This is a footnote with many words to wrap.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'markdown_footnotes_and_heading_attributes_are_formatted.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_footnotes_with_multiple_paragraphs_are_wrapped_as_block_bodies(run, workdir):
    """CATCHES: reimplementations that break "markdown footnotes with multiple paragraphs are wrapped as block bodies" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '[^note]: First paragraph has many words that should wrap.\n'
        '\n'
        '    Second paragraph has many words that should wrap.\n'
        '\n'
        '    Third paragraph has many words that should wrap.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '28'], input=stdin)
    assert result.stdout == (RES / 'markdown_footnotes_with_multiple_paragraphs_are_wrapped_as_block_bodies.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_list_continuation_lines_aligned_with_wide_marker_gap_are_wrapped(run, workdir):
    """CATCHES: reimplementations that break "markdown list continuation lines aligned with wide marker gap are wrapped" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '-   alpha beta\n'
        '    gamma delta epsilon\n'
        '\n'
        '3.  alpha beta\n'
        '    gamma delta\n'
        '    epsilon zeta\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_list_continuation_lines_aligned_with_wide_marker_gap_are_wrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_list_continuation_lines_stay_inside_items(run, workdir):
    """CATCHES: reimplementations that break "markdown list continuation lines stay inside items" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- first item has many words\n'
        '  continuation    paragraph has many words\n'
        '- second item\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'markdown_list_continuation_lines_stay_inside_items.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_list_second_paragraph_shares_item_indent(run, workdir):
    """CATCHES: reimplementations that break "markdown list second paragraph shares item indent" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '-   First paragraph has many words that should wrap under the marker.\n'
        '\n'
        '    Second   paragraph has many words that should share the same list item indent.\n'
        '-   Next item stays here.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '28'], input=stdin)
    assert result.stdout == (RES / 'markdown_list_second_paragraph_shares_item_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_lists_and_blockquotes_reflow_multiline_paragraphs(run, workdir):
    """CATCHES: reimplementations that break "markdown lists and blockquotes reflow multiline paragraphs" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- This item has many words\n'
        '  that should be treated as a single paragraph for wrapping.\n'
        '\n'
        '> This quote has many words\n'
        '> that should be treated as a single paragraph for wrapping.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_and_blockquotes_reflow_multiline_paragraphs.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_lists_and_blockquotes_wrap_under_their_markers(run, workdir):
    """CATCHES: reimplementations that break "markdown lists and blockquotes wrap under their markers" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- first item has many words that should wrap under marker\n'
        '> quoted text has many words that should wrap\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_and_blockquotes_wrap_under_their_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_lists_format_simple_nested_blockquotes(run, workdir):
    """CATCHES: reimplementations that break "markdown lists format simple nested blockquotes" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- item\n'
        '  > nested quote has many words\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_format_simple_nested_blockquotes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_lists_format_reachable_child_code_fences(run, workdir):
    """CATCHES: reimplementations that break "markdown lists format reachable child code fences" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- item\n'
        '-\n'
        '  ```python\n'
        '  x   =   1\n'
        '  ```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_format_reachable_child_code_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_lists_preserve_cr_line_endings(run, workdir):
    """CATCHES: reimplementations that break "markdown lists preserve cr line endings" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '*  first    item\r'
        '*  second    item\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (
        b'- first item\r'
        b'- second item\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_lists_preserve_unsupported_child_blocks(run, workdir):
    """CATCHES: reimplementations that break "markdown lists preserve unsupported child blocks" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- item with code\n'
        '    x   =   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_preserve_unsupported_child_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_lists_with_multiple_paragraphs_share_item_indent(run, workdir):
    """CATCHES: reimplementations that break "markdown lists with multiple paragraphs share item indent" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- First paragraph has many words that should wrap.\n'
        '\n'
        '  Second paragraph has many words that should wrap.\n'
        '\n'
        '  Third paragraph has many words that should wrap.\n'
        '- Next item stays here.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '28'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_with_multiple_paragraphs_share_item_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_lists_wrap_items_with_nested_lists(run, workdir):
    """CATCHES: reimplementations that break "markdown lists wrap items with nested lists" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- parent item has many words that should wrap before nested children\n'
        '  - nested item has many words that should wrap under nested marker\n'
        '- sibling item has many words that should wrap too\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '36'], input=stdin)
    assert result.stdout == (RES / 'markdown_lists_wrap_items_with_nested_lists.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_multiline_footnotes_are_wrapped_as_footnote_bodies(run, workdir):
    """CATCHES: reimplementations that break "markdown multiline footnotes are wrapped as footnote bodies" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '[^note]: This is a footnote with\n'
        '    continuation    words that should wrap.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'markdown_multiline_footnotes_are_wrapped_as_footnote_bodies.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_sentence_column_wraps_continuations_in_lists_with_nested_lists(run, workdir):
    """CATCHES: reimplementations that break "markdown sentence column wraps continuations in lists with nested lists" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- parent item.\n'
        '  This continuation sentence has many words that should wrap.\n'
        '  - nested item has many words that should wrap too.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:40'], input=stdin)
    assert result.stdout == (RES / 'markdown_sentence_column_wraps_continuations_in_lists_with_nested_lists.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_simple_nested_blockquotes_normalize_markers(run, workdir):
    """CATCHES: reimplementations that break "markdown simple nested blockquotes normalize markers" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '>>nested quote    text\n'
        '> > already    nested\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_simple_nested_blockquotes_normalize_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_preserves_quarto_blockquoted_indented_code_1(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto blockquoted indented code" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = '>     code\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'>     code\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_blockquoted_indented_code_2(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto blockquoted indented code" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = '> >     code\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'> >     code\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_blockquoted_indented_code_3(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto blockquoted indented code" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = '>>     code\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'>>     code\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_preserves_quarto_blockquoted_indented_code_4(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves quarto blockquoted indented code" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = '>   \tcode\n'
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == b'>   \tcode\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_simple_nested_blockquotes_wrap_under_nested_markers(run, workdir):
    """CATCHES: reimplementations that break "markdown simple nested blockquotes wrap under nested markers" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '>> nested quote has many words that should keep quote depth\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '22'], input=stdin)
    assert result.stdout == (RES / 'markdown_simple_nested_blockquotes_wrap_under_nested_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_task_lists_wrap_under_checkbox_content(run, workdir):
    """CATCHES: reimplementations that break "markdown task lists wrap under checkbox content" (markdown containers); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- [ ] first item has many words that should wrap under the checkbox marker\n'
        '- [x] done item has many words that should wrap under the checkbox marker\n'
        '- [X] also done has many words that should wrap under the checkbox marker\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '32'], input=stdin)
    assert result.stdout == (RES / 'markdown_task_lists_wrap_under_checkbox_content.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
