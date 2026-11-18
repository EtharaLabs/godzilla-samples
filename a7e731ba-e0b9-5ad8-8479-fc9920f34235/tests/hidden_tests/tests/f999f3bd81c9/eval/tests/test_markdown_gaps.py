"""Markdown formatting gaps: tables, headings, front matter, fences and inline edge cases.

Each test runs `yamark format` (or `git-filter clean`) on a small Markdown input and
compares the exact stdout, stderr, exit status and written files with the reference
implementation. Inputs exercise documented Markdown behaviour that the converted CLI
specifications do not reach: pipe-table `--table-widths preserve`, Pandoc grid/simple/
multiline table edge cases, heading attributes, document Markdown options in front
matter, roman-numeral list markers, definition lists, nested blockquotes, Quarto chunk
header promotion and `fmt: skip` forms, raw HTML/math boundaries, citations, long links
and image attributes, and line-ending/BOM handling.
"""

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)


def test_pipe_table_preserve_uses_display_width_for_wide_characters(run, workdir):
    """CATCHES: an implementation that measures CJK cells in characters instead of terminal display columns when re-padding a pipe table in preserve mode, or that fails to add the missing final newline after the last row."""
    stdin = (
        '| 名前 | v |\n'
        '|------|---|\n'
        '|   東京 |x  |'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--table-widths', 'preserve'], input=stdin)
    assert result.stdout == (RES / 'pipe_table_preserve_uses_display_width_for_wide_characters.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_table_preserve_keeps_crlf_line_endings(run, workdir):
    """CATCHES: an implementation that rewrites CRLF table rows with LF in preserve mode, or that does not centre the normalized `x y` cell under a `:-:` delimiter."""
    stdin = (
        '| a | b |\r\n'
        '|:-:|--:|\r\n'
        '| x  y | z |\r\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--table-widths', 'preserve'], input=stdin)
    assert result.stdout == (RES / 'pipe_table_preserve_keeps_crlf_line_endings.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_table_fit_at_end_of_file_without_newline(run, workdir):
    """CATCHES: an implementation that drops or mangles the last row of a pipe table that ends the file without a trailing newline, instead of fitting the table and ending the output with a newline."""
    stdin = (
        '| a | b |\n'
        '|---|---|\n'
        '| x | y |'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pipe_table_fit_at_end_of_file_without_newline.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_table_widths_directive_scope_next_applies_to_one_table(run, workdir):
    """CATCHES: an implementation that applies a `<!-- fmt: table-widths=preserve scope=next -->` directive to every following table instead of only the next one."""
    stdin = (
        '<!-- fmt: table-widths=preserve scope=next -->\n'
        '| a      | b |\n'
        '|--------|---|\n'
        '| x | y |\n'
        '\n'
        '| a      | b |\n'
        '|--------|---|\n'
        '| x | y |\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pipe_table_widths_directive_scope_next_applies_to_one_table.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_table_widths_directive_from_here_switches_back_to_fit(run, workdir):
    """CATCHES: an implementation that ignores `table-widths=preserve scope=from-here` for later tables, or that does not resume fitting after a later `table-widths=fit scope=from-here` directive."""
    stdin = (
        '| a      | b |\n'
        '|--------|---|\n'
        '| x | y |\n'
        '\n'
        '<!-- fmt: table-widths=preserve scope=from-here -->\n'
        '| a      | b |\n'
        '|--------|---|\n'
        '| x | y |\n'
        '\n'
        '<!-- fmt: table-widths=fit scope=from-here -->\n'
        '| a      | b |\n'
        '|--------|---|\n'
        '| x | y |\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pipe_table_widths_directive_from_here_switches_back_to_fit.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_table_widths_front_matter_preserve(run, workdir):
    """CATCHES: an implementation that ignores `editor_options.markdown.table-widths: preserve` in front matter and refits the table body."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    table-widths: preserve\n'
        '---\n'
        '| a      | b |\n'
        '|--------|---|\n'
        '| x   y | z |\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pipe_table_widths_front_matter_preserve.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_table_widths_config_preserve(run, workdir):
    """CATCHES: an implementation that ignores `[format].table_widths = "preserve"` from yamark.toml when formatting a pipe table in path mode."""
    write_tree(workdir, {
        'yamark.toml': (
            '[format]\n'
            'table_widths = "preserve"\n'
        ),
        'x.md': (
            '| a      | b |\n'
            '|--------|---|\n'
            '| x   y | z |\n'
        ),
    })
    result = run(['format', 'x.md'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({
        'x.md': (RES / 'pipe_table_widths_config_preserve.x.md.golden').read_bytes(),
        'yamark.toml': (
            '[format]\n'
            'table_widths = "preserve"\n'
        ),
    })


def test_pipe_table_widths_cli_fit_overrides_config_preserve(run, workdir):
    """CATCHES: an implementation that lets `[format].table_widths = "preserve"` win over an explicit `--table-widths fit` on the command line."""
    write_tree(workdir, {
        'yamark.toml': (
            '[format]\n'
            'table_widths = "preserve"\n'
        ),
        'x.md': (
            '| a      | b |\n'
            '|--------|---|\n'
            '| x | y |\n'
        ),
    })
    result = run(['format', 'x.md', '--table-widths', 'fit'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({
        'x.md': (RES / 'pipe_table_widths_cli_fit_overrides_config_preserve.x.md.golden').read_bytes(),
        'yamark.toml': (
            '[format]\n'
            'table_widths = "preserve"\n'
        ),
    })


def test_git_filter_clean_compact_table_keeps_right_and_center_markers(run, workdir):
    """CATCHES: an implementation whose compact (git-filter clean) pipe-table delimiter row drops the colons or spacing for right (`---:`) and centre (`:---:`) aligned columns."""
    stdin = (
        '| a | b | c |\n'
        '|---:|:-:|:--|\n'
        '| x | y | z |\n'
    )
    result = run(['git-filter', 'clean', '--stdin-filename', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'git_filter_clean_compact_table_keeps_right_and_center_markers.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pandoc_simple_table_without_final_newline(run, workdir):
    """CATCHES: an implementation that fails to fit a Pandoc simple table that ends the file without a newline (it must shrink the dashes to 3 and add the final newline)."""
    stdin = (
        'a     b\n'
        '----  ----\n'
        'x     y'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pandoc_simple_table_without_final_newline.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pandoc_simple_table_trailing_whitespace_on_separator(run, workdir):
    """CATCHES: an implementation that stops recognising a Pandoc simple table, or keeps the trailing blanks, when the dashed separator line has trailing spaces."""
    stdin = (
        'a     b\n'
        '----  ----   \n'
        'x     y\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pandoc_simple_table_trailing_whitespace_on_separator.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pandoc_simple_table_centered_header_fit(run, workdir):
    """CATCHES: an implementation that loses Pandoc centre alignment (header indented and shorter than its dashes) when fitting a simple table; the centred column must stay two columns wider than its header."""
    stdin = (
        '  Name     Value\n'
        '---------  -----\n'
        'x  y\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pandoc_simple_table_centered_header_fit.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pandoc_simple_table_preserve_keeps_header_padding_that_sets_alignment(run, workdir):
    """CATCHES: an implementation that collapses the internal double space of a header cell flush with its dashes in preserve mode (which would change Pandoc's default alignment to left) while still canonicalizing `_a_` to `*a*`."""
    stdin = (
        '_a_  b  Value\n'
        '------  -----\n'
        'x       y\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--table-widths', 'preserve', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'pandoc_simple_table_preserve_keeps_header_padding_that_sets_alignment.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pandoc_simple_table_preserve_header_flush_is_unchanged(run, workdir):
    """CATCHES: an implementation that normalizes the internal spaces of a flush header cell in preserve mode, altering the authored table."""
    stdin = (
        'a    b  Value\n'
        '------  -----\n'
        'x       y\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--table-widths', 'preserve'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', '--table-widths', 'preserve', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_pandoc_tables_split_on_repeated_separators(run, workdir):
    """CATCHES: an implementation that treats four separator lines as one headed multiline table instead of a headerless table followed by a simple table, as Pandoc does."""
    stdin = (
        '----  ----\n'
        'a     b\n'
        '----  ----\n'
        'x     y\n'
        '----  ----\n'
        'z     w\n'
        '----  ----\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'pandoc_tables_split_on_repeated_separators.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_grid_table_border_alignment_colons_are_kept(run, workdir):
    """CATCHES: an implementation that drops `:` alignment markers from the top border of a grid table when fitting widths (left `:--`, right `--:` and centre `:-:`)."""
    stdin = (
        '+:-----+-----:+:----:+\n'
        '| a | b | c |\n'
        '+======+======+======+\n'
        '| x | y | z |\n'
        '+------+------+------+\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'grid_table_border_alignment_colons_are_kept.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_grid_table_without_final_newline(run, workdir):
    """CATCHES: an implementation that fails to fit a grid table that ends the file without a newline after its closing border."""
    stdin = (
        '+-----+-----+\n'
        '| a | b |\n'
        '+=====+=====+\n'
        '| x | y |\n'
        '+-----+-----+'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'grid_table_without_final_newline.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_grid_table_without_closing_border_is_preserved(run, workdir):
    """CATCHES: an implementation that rewrites (or invents a closing border for) a grid table whose last row has no closing border."""
    stdin = (
        '+-----+-----+\n'
        '| a | b |\n'
        '+=====+=====+\n'
        '| x | y |\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_grid_table_with_empty_section_is_preserved(run, workdir):
    """CATCHES: an implementation that fits a grid table containing two consecutive borders (an empty section) instead of preserving it."""
    stdin = (
        '+-----+-----+\n'
        '| a | b |\n'
        '+=====+=====+\n'
        '+-----+-----+\n'
        '| x | y |\n'
        '+-----+-----+\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_grid_table_row_wider_than_border_by_display_width_is_preserved(run, workdir):
    """CATCHES: an implementation that counts characters instead of display columns: `東京都` is 3 characters but 6 columns, wider than its 4-column border, so the grid table must be preserved."""
    stdin = (
        '+----+----+\n'
        '| 名前 | v |\n'
        '+====+====+\n'
        '| 東京都 | x |\n'
        '+----+----+\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_grid_table_with_invalid_border_is_not_a_table(run, workdir):
    """CATCHES: an implementation that accepts a grid border containing a non-dash character (`-x---`) as a table border and reformats the block."""
    stdin = (
        '+-----+-x---+\n'
        '| a | b |\n'
        '+=====+=====+\n'
        '| x | y |\n'
        '+-----+-----+\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_seven_hashes_is_a_paragraph(run, workdir):
    """CATCHES: an implementation that treats `#######` (seven hashes) as a heading instead of paragraph text whose spaces are normalized."""
    stdin = '####### not a heading   text\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'####### not a heading text\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_hash_without_space_is_a_paragraph(run, workdir):
    """CATCHES: an implementation that treats `#hashtag` (no space after the hashes) as an ATX heading and inserts a space."""
    stdin = '#hashtag   text\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'#hashtag text\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_atx_closing_hashes_with_trailing_spaces_are_removed(run, workdir):
    """CATCHES: an implementation that keeps the optional closing `##` sequence when it is followed by trailing spaces."""
    stdin = '##   Title   ##   \n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'## Title\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_heading_unnumbered_attribute_is_kept(run, workdir):
    """CATCHES: an implementation that rejects the Pandoc unnumbered `{-}` heading attribute or fails to normalize the spacing before it."""
    stdin = '#  Intro   {-}\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'# Intro {-}\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_heading_closing_hashes_before_attribute_are_removed(run, workdir):
    """CATCHES: an implementation that keeps closing hashes between the heading text and a trailing attribute block, or that does not collapse spaces inside `{#id   .cls}`."""
    stdin = '#  Intro  ##   {#id   .cls}\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'# Intro {#id .cls}\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_heading_attribute_with_single_quotes_is_kept_verbatim(run, workdir):
    """CATCHES: an implementation that normalizes the inside of a heading attribute containing a single-quoted value; only the space before it may change."""
    stdin = "#  Intro   {key='v'   .x}\n"
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b"# Intro {key='v'   .x}\n"
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_heading_attribute_with_unclosed_double_quote_is_kept_verbatim(run, workdir):
    """CATCHES: an implementation that collapses spaces inside an attribute block with an unterminated double quote."""
    stdin = '#  Intro   {key="v   w}\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'# Intro {key="v   w}\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pandoc_block_attribute_line_stays_separate(run, workdir):
    """CATCHES: an implementation that joins a standalone `{-}` attribute line into the following paragraph."""
    stdin = (
        '{-}\n'
        'some text   here\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'{-}\nsome text here\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_invalid_block_attribute_line_joins_paragraph(run, workdir):
    """CATCHES: an implementation that treats `{key="a b}` (unterminated quote) as a block attribute line instead of ordinary paragraph text."""
    stdin = (
        '{key="a b}\n'
        'some text   here\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'{key="a b} some text here\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_legacy_editor_markdown_wrap(run, workdir):
    """CATCHES: an implementation that ignores the compatibility `editor.markdown.wrap` table when `editor_options.markdown` is absent."""
    stdin = (
        '---\n'
        'editor:\n'
        '  markdown:\n'
        '    wrap: sentence\n'
        '---\n'
        'One.  Two sentence here.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_legacy_editor_markdown_wrap.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_legacy_editor_markdown_unknown_key_ignored(run, workdir):
    """CATCHES: an implementation that errors on, or changes the wrap mode because of, an unknown key under `editor.markdown`."""
    stdin = (
        '---\n'
        'editor:\n'
        '  markdown:\n'
        '    other: 1\n'
        '---\n'
        'One.  Two sentence here.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_legacy_editor_markdown_unknown_key_ignored.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_footnotes_preserve(run, workdir):
    """CATCHES: an implementation that ignores `footnotes: preserve` in front matter and reformats the footnote definition."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    footnotes: preserve\n'
        '---\n'
        'Text[^1].\n'
        '\n'
        '[^1]:   A   note  with   spaces.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_front_matter_unrecognized_footnotes_value_is_ignored(run, workdir):
    """CATCHES: an implementation that treats an unrecognized `footnotes: maybe` value as preserve (or errors) instead of ignoring it while still applying `wrap: 20`."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    footnotes: maybe\n'
        '    wrap: 20\n'
        '---\n'
        'Text[^1] with some words to wrap here.\n'
        '\n'
        '[^1]:   A   note  with   spaces.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_unrecognized_footnotes_value_is_ignored.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_unrecognized_canonical_value_keeps_base(run, workdir):
    """CATCHES: an implementation that treats `canonical: perhaps` as false; unrecognized values are ignored so the `--canonical` base setting still applies."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    canonical: perhaps\n'
        '    wrap: none\n'
        '---\n'
        'This is __strong__.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'front_matter_unrecognized_canonical_value_keeps_base.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_scalar_editor_options_markdown_blocks_legacy_table(run, workdir):
    """CATCHES: an implementation that falls back to `editor.markdown` when `editor_options.markdown` exists but is a scalar rather than a mapping."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown: none\n'
        'editor:\n'
        '  markdown:\n'
        '    wrap: 20\n'
        '---\n'
        'This paragraph has quite a few   words in it.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_scalar_editor_options_markdown_blocks_legacy_table.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_non_scalar_wrap_is_ignored(run, workdir):
    """CATCHES: an implementation that errors on, or misreads, a sequence value for `wrap` instead of ignoring it while still applying `canonical: true`."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: [20]\n'
        '    canonical: true\n'
        '---\n'
        'This paragraph __has__ quite a few words in it.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_non_scalar_wrap_is_ignored.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_flow_mapping_options(run, workdir):
    """CATCHES: an implementation that only reads block-style `editor_options.markdown` and ignores the same options written as a flow mapping."""
    stdin = (
        '---\n'
        'editor_options: {markdown: {wrap: 20, canonical: yes}}\n'
        '---\n'
        'This paragraph __has__ quite a few words in it.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_flow_mapping_options.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unclosed_front_matter_is_not_yaml(run, workdir):
    """CATCHES: an implementation that treats a leading `---` without a closing marker as front matter instead of a thematic break followed by a paragraph."""
    stdin = (
        '---\n'
        'title: x\n'
        'Some   text\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'---\ntitle: x Some text\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_bom_before_front_matter_is_preserved(run, workdir):
    """CATCHES: an implementation that drops the UTF-8 BOM in front of the opening front-matter marker, or fails to recognize front matter after a BOM."""
    stdin = (
        '\ufeff---\n'
        'title:   x\n'
        '---\n'
        '# Head   ing\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'bom_before_front_matter_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_at_end_of_file_without_newline(run, workdir):
    """CATCHES: an implementation that loses the closing `---` marker, or emits no final newline, when the front matter ends the file without a line ending."""
    stdin = (
        '---\n'
        'title:   x\n'
        '---'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'front_matter_at_end_of_file_without_newline.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_roman_numeral_list_markers(run, workdir):
    """CATCHES: an implementation that does not recognize multi-letter roman numeral list markers (`xiv.`, `(xl)`, `MCM.`, `LX)`) and wraps their continuation lines without indenting them to the item content."""
    stdin = (
        'xiv. This item text is long enough to wrap around\n'
        '\n'
        '(xl) Another item text that is long enough to wrap\n'
        '\n'
        'MCM. This item text is long enough to wrap around\n'
        '\n'
        'LX) Another item text that is long enough to wrap\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'roman_numeral_list_markers.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_long_parenthesized_word_is_not_a_list_marker(run, workdir):
    """CATCHES: an implementation that accepts `(abcdefghi)` (nine letters, not a roman numeral) as a parenthesized list marker and indents the continuation."""
    stdin = '(abcdefghi) This item text is long enough to wrap around\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == b'(abcdefghi) This item text is\nlong enough to wrap around\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_list_followed_by_trailing_blank_lines(run, workdir):
    """CATCHES: an implementation that strips the trailing blank lines after a final list item at the end of the document."""
    stdin = (
        '- item   one\n'
        '\n'
        '\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'list_followed_by_trailing_blank_lines.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_list_item_with_setext_child_is_preserved(run, workdir):
    """CATCHES: an implementation that reflows a list item whose content contains a setext heading underline, which the list formatter cannot represent."""
    stdin = (
        '- item   one\n'
        '  Child   heading\n'
        '  ---\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_list_item_with_quoted_list_child_is_preserved(run, workdir):
    """CATCHES: an implementation that reflows a list item containing a blockquote whose body is itself a list."""
    stdin = (
        '- item   one\n'
        '  > - quoted   list\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_definition_list_with_two_definitions(run, workdir):
    """CATCHES: an implementation that only formats the first `:` definition of a term and leaves a second definition (after a blank line) unwrapped."""
    stdin = (
        'Term\n'
        ':   First definition with several words to wrap.\n'
        '\n'
        ':   Second definition with several words to wrap.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'definition_list_with_two_definitions.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_definition_list_with_two_terms(run, workdir):
    """CATCHES: an implementation that stops the definition list after the first term instead of formatting the following term and definition too."""
    stdin = (
        'Term one\n'
        ':   First definition with several words to wrap.\n'
        '\n'
        'Term two\n'
        ':   Second definition with several words to wrap.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'definition_list_with_two_terms.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_definition_list_followed_by_trailing_blank_lines(run, workdir):
    """CATCHES: an implementation that removes the trailing blank lines after a definition list at the end of the document."""
    stdin = (
        'Term\n'
        ':   def   one\n'
        '\n'
        '\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'definition_list_followed_by_trailing_blank_lines.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_definition_list_with_code_fence_is_preserved(run, workdir):
    """CATCHES: an implementation that normalizes the marker spacing of a definition whose content opens a code fence."""
    stdin = (
        'Term\n'
        ':   ```\n'
        '    code\n'
        '    ```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_nested_blockquote_varying_indent_wrap_none(run, workdir):
    """CATCHES: an implementation that rejects nested quotes whose lines differ in leading indentation, or that re-indents them, under `--wrap none`."""
    stdin = (
        '> > deep   one\n'
        ' > > deep   two\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'> > deep one\n > > deep two\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_nested_blockquote_varying_depth_wrap_none(run, workdir):
    """CATCHES: an implementation that merges quote lines of different nesting depth into one scope, instead of normalizing each line separately with its own `> > ` or `> > > ` prefix."""
    stdin = (
        '> > deep   one\n'
        '> > > deeper   two\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'> > deep one\n> > > deeper two\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_nested_blockquote_with_empty_line_wrap_none(run, workdir):
    """CATCHES: an implementation that drops or adds spaces on an empty `> >` separator line of a nested blockquote."""
    stdin = (
        '> > deep   one\n'
        '> >\n'
        '> > deep   two\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'nested_blockquote_with_empty_line_wrap_none.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_blockquote_with_inconsistent_indent_is_preserved(run, workdir):
    """CATCHES: an implementation that reflows a blockquote whose lines use different leading indentation."""
    stdin = (
        '> quote   one\n'
        ' > quote   two\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_blockquote_list_with_inconsistent_indent_is_preserved(run, workdir):
    """CATCHES: an implementation that reformats a blockquote containing a list when the quote markers are indented differently."""
    stdin = (
        '> - item   one\n'
        ' > - item   two\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_footnote_with_underindented_continuation(run, workdir):
    """CATCHES: an implementation that treats a one-space-indented line after a footnote definition as a footnote continuation instead of a separate paragraph."""
    stdin = (
        '[^1]: Note   text\n'
        ' continuation\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'[^1]: Note text\ncontinuation\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_quarto_promotion_skipped_for_quoted_option(run, workdir):
    """CATCHES: an implementation that promotes a long Quarto chunk header to `#|` lines even though one option value is quoted."""
    stdin = (
        "```{bash, echo=FALSE, warning=FALSE, message=FALSE, fig.cap='A caption', x=1}\n"
        'ls\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_quarto_promotion_skipped_for_value_with_spaces(run, workdir):
    """CATCHES: an implementation that promotes a long chunk header whose option value contains whitespace (`fig.width = 10 cm`)."""
    stdin = (
        '```{bash, echo=FALSE, warning=FALSE, message=FALSE, fig.width = 10 cm, x=1, y=2}\n'
        'ls\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_quarto_promotion_skipped_for_invalid_key(run, workdir):
    """CATCHES: an implementation that promotes a long chunk header containing an option key with a `/` character."""
    stdin = (
        '```{bash, echo=FALSE, warning=FALSE, message=FALSE, fig/width=10, xxxxx=1, y=2}\n'
        'ls\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_quarto_promotion_skipped_without_language(run, workdir):
    """CATCHES: an implementation that promotes a long chunk header with no language before the first comma."""
    stdin = (
        '```{, echo=FALSE, warning=FALSE, message=FALSE, fig.width=10, xxxxx=1, y=2}\n'
        'ls\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_fence_redundant_language_class_is_removed(run, workdir):
    """CATCHES: an implementation that keeps a redundant `{.bash}` attribute block that only repeats the bare fence language, instead of reducing the opening to ```` ```bash ````."""
    stdin = (
        '```bash {.bash}\n'
        'ls\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'fence_redundant_language_class_is_removed.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_fence_empty_braces_is_not_a_yaml_fence(run, workdir):
    """CATCHES: an implementation that treats a fence with empty `{}` info as YAML (or rewrites the info) and reformats the body."""
    stdin = (
        '```{}\n'
        'a:   1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_fence_info_compact_fmt_skip_token(run, workdir):
    """CATCHES: an implementation that only recognizes `fmt: skip` with a space in a fence info string and formats a ```` ```yaml fmt:skip ```` fence."""
    stdin = (
        '```yaml fmt:skip\n'
        'a:   1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_fence_info_fmt_skip_with_extra_token_still_formats(run, workdir):
    """CATCHES: an implementation that treats `fmt: skip extra` (trailing unknown token) in a fence info string as a skip directive."""
    stdin = (
        '```yaml fmt: skip extra\n'
        'a:   1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'fence_info_fmt_skip_with_extra_token_still_formats.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_quarto_hashpipe_compact_fmt_skip(run, workdir):
    """CATCHES: an implementation that only accepts `#| fmt: skip` with a space and formats a chunk marked `#| fmt:skip`."""
    stdin = (
        '```{yaml}\n'
        '#| fmt:skip\n'
        'a:   1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_quarto_hashpipe_fmt_skip_after_other_options(run, workdir):
    """CATCHES: an implementation that only checks the first `#|` line for `fmt: skip scope=next` instead of the whole initial option block."""
    stdin = (
        '```{yaml}\n'
        '#| label: x\n'
        '#| fmt: skip scope=next\n'
        'a:   1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_fence_generic_info_whitespace_is_collapsed(run, workdir):
    """CATCHES: an implementation that leaves runs of spaces in a plain fence info string (```` ```   text    extra   words ````)."""
    stdin = (
        '```   text    extra   words\n'
        'hi\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'fence_generic_info_whitespace_is_collapsed.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unclosed_quarto_div_is_preserved(run, workdir):
    """CATCHES: an implementation that formats the body of a `:::` div that never closes."""
    stdin = (
        '::: {.callout-note}\n'
        'Some   text   here.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.qmd'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.qmd': stdin})
    checked = run(['format', '--check', 'x.qmd'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.qmd': stdin})


def test_html_block_ends_only_at_matching_closing_tag(run, workdir):
    """CATCHES: an implementation that ends a `<details>` raw HTML block at `</detailsx>` (a different tag name) instead of the real `</details>`."""
    stdin = (
        '<details>\n'
        '<summary>x</summary>\n'
        'Some   text </detailsx> here\n'
        '</details>\n'
        '\n'
        'After   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'html_block_ends_only_at_matching_closing_tag.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_multiline_self_closing_tag_start_is_preserved(run, workdir):
    """CATCHES: an implementation that formats the line after an unterminated `<br/` tag instead of preserving the raw HTML tag lines."""
    stdin = (
        '<br/\n'
        'more   text\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_bare_closing_angle_slash_is_paragraph_text(run, workdir):
    """CATCHES: an implementation that treats a lone `</` line as the start of an HTML block instead of paragraph text."""
    stdin = (
        'Some text\n'
        '</\n'
        '\n'
        'After   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'bare_closing_angle_slash_is_paragraph_text.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_html_declaration_and_processing_instruction_interrupt_paragraph(run, workdir):
    """CATCHES: an implementation that joins `<!DOCTYPE html>` or `<?xml ...?>` lines into the preceding paragraph."""
    stdin = (
        'Text   here\n'
        '<!DOCTYPE html>\n'
        '\n'
        'More   text\n'
        '<?xml version="1.0"?>\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'html_declaration_and_processing_instruction_interrupt_paragraph.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_single_line_display_math_is_preserved(run, workdir):
    """CATCHES: an implementation that treats `$$ ... $$` on one line as an unterminated display-math block and preserves the following paragraph too."""
    stdin = (
        '$$ x   =   1 $$\n'
        'Some   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'$$ x   =   1 $$\nSome text.\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unclosed_display_math_preserves_to_end(run, workdir):
    """CATCHES: an implementation that formats the content after an unterminated `$$` display-math opener."""
    stdin = (
        'Text.\n'
        '\n'
        '$$\n'
        'x   =   1\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_table_caption_continuation_is_preserved(run, workdir):
    """CATCHES: an implementation that reflows an indented continuation of a `Table:` caption line."""
    stdin = (
        'Table: A   caption\n'
        '  continued   caption\n'
        '\n'
        'After.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_incomplete_grid_table_lines_are_preserved(run, workdir):
    """CATCHES: an implementation that formats lines following a `+---+` border that never closes as a grid table, or joins them into a paragraph."""
    stdin = (
        '+---+---+\n'
        '| a | b |\n'
        '===\n'
        '\n'
        'After   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'incomplete_grid_table_lines_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_multiline_citation_is_joined_into_one_token(run, workdir):
    """CATCHES: an implementation that leaves a Pandoc citation split across lines (`[see\n@doe99, p. 33; -@smith04]`) or breaks it again while wrapping."""
    stdin = (
        'Some words here [see\n'
        '@doe99, p. 33; -@smith04] and more words to wrap\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'multiline_citation_is_joined_into_one_token.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_multiline_bracket_with_empty_citation_part_is_preserved(run, workdir):
    """CATCHES: an implementation that accepts `[see\n@doe99;; @x]` (empty citation part) as a citation and reflows the paragraph."""
    stdin = (
        'Some words here [see\n'
        '@doe99;; @x] and more words to wrap here\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', '--wrap', '30', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    assert read_tree(workdir) == as_bytes({'x.md': stdin})


def test_link_with_single_quoted_title_stays_atomic(run, workdir):
    """CATCHES: an implementation that splits a link with a single-quoted title across lines or breaks inside it when wrapping."""
    stdin = "See [a link](http://example.com/a/very/long/path 'Title') here and words.\n"
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'link_with_single_quoted_title_stays_atomic.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_long_image_attributes_move_to_own_line(run, workdir):
    """CATCHES: an implementation that leaves an over-width image attribute block (without `fig-alt`) on the image line instead of moving it inside `{` / `}` lines."""
    stdin = '![cap](img.png){#fig-a width=50% height=20% .class-name}\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'long_image_attributes_move_to_own_line.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_image_fig_alt_with_overlong_word_is_not_wrapped(run, workdir):
    """CATCHES: an implementation that wraps fig-alt text containing a word wider than the available width."""
    stdin = '![cap](img.png){#fig-a fig-alt="Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa short"}\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'image_fig_alt_with_overlong_word_is_not_wrapped.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_image_fig_alt_must_start_attribute_token(run, workdir):
    """CATCHES: an implementation that matches `fig-alt="` inside `xfig-alt="x"` instead of requiring it to start an attribute token."""
    stdin = '![cap](img.png){#fig-a xfig-alt="x" fig-alt="A long alt text that should wrap across lines"}\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'image_fig_alt_must_start_attribute_token.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_long_link_with_attribute_splits_destination(run, workdir):
    """CATCHES: an implementation that cannot split a long link destination when the link carries a trailing `{.cls   #id}` attribute, or that does not normalize that attribute."""
    stdin = 'See [label](http://example.com/a/very/long/path/to/somewhere){.cls   #id} more words\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'long_link_with_attribute_splits_destination.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_long_link_with_word_suffix_is_not_split(run, workdir):
    """CATCHES: an implementation that splits a long link destination even though the link is glued to trailing word characters (`)abc`)."""
    stdin = 'See [label](http://example.com/a/very/long/path/to/somewhere)abc more words\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'long_link_with_word_suffix_is_not_split.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_image_with_non_attribute_braces_splits_destination(run, workdir):
    """CATCHES: an implementation that treats `{just some words}` after an image as Pandoc attributes and moves it to its own block."""
    stdin = '![cap](img.png){just some words here that are long}\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / 'image_with_non_attribute_braces_splits_destination.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_email_autolink_is_protected_from_canonical_emphasis(run, workdir):
    """CATCHES: an implementation that does not recognize `<first_last_x+tag@example.com>` as an email autolink and rewrites its underscores as emphasis under `--canonical`, or that breaks it while wrapping."""
    stdin = 'Mail <first_last_x+tag@example.com> or _x_   to reach us now\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--canonical', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'email_autolink_is_protected_from_canonical_emphasis.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_self_closing_inline_tag_does_not_open_protected_html_span(run, workdir):
    """CATCHES: an implementation that treats a self-closing `<span/>` as the opener of a paired inline HTML span (protecting `_x_` up to `</span>`), while a real `<b> ... </b>` pair must stay protected under `--canonical`."""
    stdin = 'Text <span/> _x_ </span>   y and <b> _z_ </b> end\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--canonical'], input=stdin)
    assert result.stdout == b'Text <span/> *x* </span> y and <b> _z_ </b> end\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_mixed_thematic_break_characters_are_text(run, workdir):
    """CATCHES: an implementation that treats `-*-` (mixed markers) as a thematic break and rewrites it to `---`."""
    stdin = (
        'Text   here\n'
        '\n'
        '-*-\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'mixed_thematic_break_characters_are_text.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_spaced_asterisks_stay_on_one_line(run, workdir):
    """CATCHES: an implementation that wraps before a lone `*` (which would start a list item or emphasis at line start) instead of keeping the spaced asterisks on the current line."""
    stdin = 'Some text * star * here * there words\n'
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '12'], input=stdin)
    assert result.stdout == b'Some text * star * here * there\nwords\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
