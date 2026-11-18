"""Spec markdown tables behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_markdown_gfm_pipe_tables_allow_body_rows_without_leading_pipes(run, workdir):
    """CATCHES: reimplementations that break "markdown gfm pipe tables allow body rows without leading pipes" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| name | value |\n'
        '------ | -----\n'
        'short | one\n'
        'long name | two\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_gfm_pipe_tables_allow_body_rows_without_leading_pipes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_definition_list_continuations_are_wrapped_under_definition_indent(run, workdir):
    """CATCHES: reimplementations that break "markdown definition list continuations are wrapped under definition indent" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Term\n'
        ':   first line has    spacing\n'
        '    continuation line has many words that should wrap\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'markdown_definition_list_continuations_are_wrapped_under_definition_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_grid_tables_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc grid tables are normalized" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '+------+-----+\n'
        '| Name | Value |\n'
        '+======+=====+\n'
        '| a | one |\n'
        '+------+-----+\n'
        '| longer | two |\n'
        '+------+-----+\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_grid_tables_are_normalized.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_definition_list_keeps_indented_paragraph_after_blank(run, workdir):
    """CATCHES: reimplementations that break "markdown definition list keeps indented paragraph after blank" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Term\n'
        ': definition one\n'
        '\n'
        '  second paragraph\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_definition_list_keeps_indented_paragraph_after_blank.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_definition_lists_with_unsupported_continuations_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "markdown definition lists with unsupported continuations are preserved" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Term\n'
        ': definition    first line\n'
        '    ```r\n'
        '    x <- 1\n'
        '    ```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_definition_lists_with_unsupported_continuations_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_grid_tables_with_multiline_rows_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc grid tables with multiline rows are normalized" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '+------+-----+\n'
        '| Name | Value |\n'
        '|      | Extra |\n'
        '+======+=====+\n'
        '| a | one |\n'
        '|   | two |\n'
        '+------+-----+\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_grid_tables_with_multiline_rows_are_normalized.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_grid_tables_preserve_unrepresentable_rows(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc grid tables preserve unrepresentable rows" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '+---+---+\n'
        '| too wide | B |\n'
        '+===+===+\n'
        '| x | y |\n'
        '+---+---+\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_grid_tables_preserve_unrepresentable_rows.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_1(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc headerless tables keep their borders and following blocks" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '------  ------\n'
        'a  b    c\n'
        '------  ------\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_2(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc headerless tables keep their borders and following blocks" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '------  ------\n'
        'a b     c\n'
        '------  ------\n'
        'Table: keep    caption spacing\n'
        '\n'
        'First sentence.\n'
        'Second sentence.\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--table-widths', 'preserve', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_3(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc headerless tables keep their borders and following blocks" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '------  ------\n'
        'a  b    c\n'
        '        d\n'
        '\n'
        'e       f\n'
        '------  ------\n'
        ': keep    caption spacing\n'
        '\n'
        'First sentence. Second sentence.\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_4(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc headerless tables keep their borders and following blocks" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '------  ------\r\n'
        'a  b    c\r\n'
        '------  ------\r\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_5(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc headerless tables keep their borders and following blocks" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '------  ------\r\n'
        'a b     c\r\n'
        '------  ------\r\n'
        'Table: keep    caption spacing\r\n'
        '\r\n'
        'First sentence.\r\n'
        'Second sentence.\r\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--table-widths', 'preserve', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_6(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc headerless tables keep their borders and following blocks" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '------  ------\r\n'
        'a  b    c\r\n'
        '        d\r\n'
        '\r\n'
        'e       f\r\n'
        '------  ------\r\n'
        ': keep    caption spacing\r\n'
        '\r\n'
        'First sentence. Second sentence.\r\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_headerless_tables_keep_their_borders_and_following_blocks_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_multiline_tables_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc multiline tables are normalized" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '----------  ----------\n'
        'Name        Value\n'
        '----------  ----------\n'
        'short       one\n'
        '\n'
        'long name   two\n'
        '----------  ----------\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_multiline_tables_are_normalized.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_multiline_tables_with_continuous_bounds_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc multiline tables with continuous bounds are normalized" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '-------------------------------------------------------------\n'
        'Centered   Default           Right Left\n'
        'Header     Aligned         Aligned Aligned\n'
        '---------  -------  -------------- -------------------------\n'
        'First      row                12.0 Example of a row that\n'
        '                                   spans multiple lines.\n'
        '\n'
        'Second     row                 5.0 Another row.\n'
        '-------------------------------------------------------------\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_multiline_tables_with_continuous_bounds_are_normalized.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_simple_tables_and_definition_lists_are_formatted(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc simple tables and definition lists are formatted" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Name        Value\n'
        '----------  -----\n'
        'short       one\n'
        'long name   two\n'
        '\n'
        'Term\n'
        ':   definition with    spacing\n'
        '\n'
        '<section>\n'
        '#   Keep ##\n'
        '</section>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_simple_tables_and_definition_lists_are_formatted.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_simple_tables_format_optional_closing_separator(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc simple tables format optional closing separator" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Name        Value\n'
        '----------  -----\n'
        'short       one\n'
        'long name   two\n'
        '----------  -----\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_simple_tables_format_optional_closing_separator.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_table_cells_apply_canonical_inline_formatting(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc table cells apply canonical inline formatting" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Name        Value\n'
        '----------  -----\n'
        '_x_         __y__\n'
        '\n'
        '+------+-----+\n'
        '| Name | Value |\n'
        '+======+=====+\n'
        '| _x_ | __y__ |\n'
        '+------+-----+\n'
        '\n'
        '----------  ----------\n'
        'Name        Value\n'
        '----------  ----------\n'
        '_x_         __y__\n'
        '----------  ----------\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_table_cells_apply_canonical_inline_formatting.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_expand_tabs_before_splitting_cells_1(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables expand tabs before splitting cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'A\tB\n'
        '---\t---\n'
        'x\ty\n'
    )
    result = run(['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_expand_tabs_before_splitting_cells_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_expand_tabs_before_splitting_cells_2(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables expand tabs before splitting cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'A   B\r\n'
        '--- ---\r\n'
        'x   y\r\n'
    )
    result = run(['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_expand_tabs_before_splitting_cells_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--table-widths', 'preserve', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_tables_expand_tabs_before_splitting_cells_3(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables expand tabs before splitting cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'A       B\n'
        '---     ---\n'
        'x       y\n'
    )
    result = run(['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_expand_tabs_before_splitting_cells_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--table-widths', 'preserve', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_tables_expand_tabs_before_splitting_cells_4(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables expand tabs before splitting cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '--- ---\n'
        'a   b\n'
        '--- ---\n'
    )
    result = run(['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_expand_tabs_before_splitting_cells_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--table-widths', 'preserve', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_tables_expand_tabs_before_splitting_cells_5(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables expand tabs before splitting cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '------------\n'
        'A\tB\n'
        '---\t---\n'
        'x\ty\n'
        '\n'
        'a\tb\n'
        '------------\n'
    )
    result = run(['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_expand_tabs_before_splitting_cells_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_expand_tabs_before_splitting_cells_6(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables expand tabs before splitting cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '+-------+-------+\n'
        '| A\t\t| B\t\t|\n'
        '+=======+=======+\n'
        '| x\t\t| y\t\t|\n'
        '+-------+-------+\n'
    )
    result = run(['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_expand_tabs_before_splitting_cells_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_table_captions_stop_table_parsing_1(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc table captions stop table parsing" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'Name        Value\n'
        '----------  -----\n'
        'short       one\n'
        'long name   two\n'
        'Table: keep    caption spacing\n'
        '\n'
        'Term\n'
        ':   definition with    spacing\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_table_captions_stop_table_parsing_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_table_captions_stop_table_parsing_2(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc table captions stop table parsing" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'Name        Value\n'
        '----------  -----\n'
        'short       one\n'
        'long name   two\n'
        ': keep    caption spacing\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_table_captions_stop_table_parsing_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_handle_incomplete_grid_markers_1(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables handle incomplete grid markers" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '+\n'
        '---  ---\n'
        'x    y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_handle_incomplete_grid_markers_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_tables_handle_incomplete_grid_markers_2(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables handle incomplete grid markers" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '+---+---+\n'
        '|\n'
        '+---+---+\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pandoc_tables_handle_incomplete_grid_markers_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_pandoc_tables_preserve_alignment_and_widths_1(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables preserve alignment and widths" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'A             B\n'
        '-----  ------------\n'
        'x      y\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', '20'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_tables_preserve_alignment_and_widths_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_preserve_alignment_and_widths_2(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables preserve alignment and widths" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'A             B\n'
        '-----  ------------\n'
        'x      y\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', '72'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_tables_preserve_alignment_and_widths_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_preserve_alignment_and_widths_3(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables preserve alignment and widths" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '+----------+------------------+\n'
        '| A        | B                |\n'
        '+==========+==================+\n'
        '| x  one   | y  two           |\n'
        '+----------+------------------+\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', '20'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_tables_preserve_alignment_and_widths_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_preserve_alignment_and_widths_4(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables preserve alignment and widths" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '+----------+------------------+\n'
        '| A        | B                |\n'
        '+==========+==================+\n'
        '| x  one   | y  two           |\n'
        '+----------+------------------+\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', '72'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_tables_preserve_alignment_and_widths_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_preserve_alignment_and_widths_5(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables preserve alignment and widths" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before.\n'
        '\n'
        '----------  ----------\n'
        'A           B\n'
        '----------  ----------\n'
        'x  one      y  two\n'
        '----------  ----------\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', '20'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_tables_preserve_alignment_and_widths_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pandoc_tables_preserve_alignment_and_widths_6(run, workdir):
    """CATCHES: reimplementations that break "markdown pandoc tables preserve alignment and widths" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before.\n'
        '\n'
        '----------  ----------\n'
        'A           B\n'
        '----------  ----------\n'
        'x  one      y  two\n'
        '----------  ----------\n'
    )
    result = run(
        ['format', '--table-widths', 'preserve', '--stdin-file-path', 'input.qmd', '--wrap', '72'],
        input=stdin,
    )
    assert result.stdout == (RES / 'markdown_pandoc_tables_preserve_alignment_and_widths_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_table_cells_apply_canonical_inline_formatting(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe table cells apply canonical inline formatting" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| name | value |\n'
        '| --- | --- |\n'
        '| _x_ | __y__ |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_table_cells_apply_canonical_inline_formatting.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_table_fit_width_aligns_delimiter_cells(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe table fit width aligns delimiter cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| name | value |\n'
        '| --- | --- |\n'
        '| short | one |\n'
        '| long name | two |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_table_fit_width_aligns_delimiter_cells.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_table_fit_width_aligns_right_and_center_data_cells(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe table fit width aligns right and center data cells" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| item | count | state |\n'
        '| :--- | ---: | :---: |\n'
        '| a | 1 | ok |\n'
        '| longer | 1000 | yes |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_table_fit_width_aligns_right_and_center_data_cells.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_tables_ignore_normal_compact_options_1(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe tables ignore normal compact options" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '| a | long |\n'
        '|---|:---:|\n'
        '| 1 | two |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--compact'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_tables_ignore_normal_compact_options_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_tables_ignore_normal_compact_options_2(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe tables ignore normal compact options" (markdown tables); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'compact = true\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '| a | long |\n'
        '|---|:---:|\n'
        '| 1 | two |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_tables_ignore_normal_compact_options_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_markdown_pipe_tables_preserve_cr_line_endings(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe tables preserve cr line endings" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| a | long |\r'
        '|---|:---:|\r'
        '| 1 | two |\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (
        b'| a   | long  |\r'
        b'| --- | :---: |\r'
        b'| 1   |  two  |\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_tables_preserve_escaped_pipes_and_align_when_wide(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe tables preserve escaped pipes and align when wide" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| item | value |\n'
        '| --- | --- |\n'
        '| a\\|b | 文 |\n'
        '\n'
        '| key | description |\n'
        '| --- | --- |\n'
        '| first | this cell is intentionally long enough to exceed the fit to width threshold when the table formatter would otherwise pad the shorter header column |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_tables_preserve_escaped_pipes_and_align_when_wide.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_tables_preserve_crlf_line_endings(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe tables preserve crlf line endings" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| a | long |\r\n'
        '|---|:---:|\r\n'
        '| 1 | two |\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_tables_preserve_crlf_line_endings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_pipe_tables_use_unicode_display_width(run, workdir):
    """CATCHES: reimplementations that break "markdown pipe tables use unicode display width" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| a | b |\n'
        '| --- | --- |\n'
        '| ééé | x |\n'
        '| bbbb | y |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_pipe_tables_use_unicode_display_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_preserves_inconsistent_pipe_tables(run, workdir):
    """CATCHES: reimplementations that break "markdown preserves inconsistent pipe tables" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| A |\n'
        '| --- |\n'
        '| x | y |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd'], input=stdin)
    assert result.stdout == (RES / 'markdown_preserves_inconsistent_pipe_tables.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_tables_lists_blockquotes_and_fences(run, workdir):
    """CATCHES: reimplementations that break "markdown tables lists blockquotes and fences" (markdown tables); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '| a | long |\n'
        '|---|:---:|\n'
        '| 1 | two |\n'
        '\n'
        '*  item with    extra spaces\n'
        '>quote    text\n'
        '\n'
        '```yaml\n'
        'a:    b\n'
        '```\n'
        '\n'
        '```yaml fmt: skip\n'
        'a:    b\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_tables_lists_blockquotes_and_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
