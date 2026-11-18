"""Markdown engine edge cases not reached by the converted specifications or earlier gap modules.

Each test runs `yamark format` on a small Markdown (or marked Python/YAML) input and compares
the exact stdout, stderr and exit status with the reference implementation. Inputs cover
explicit `fmt:` targets on tables and footnotes, directive errors inside nested regions,
paragraph interruption rules, Python f-string replacement-field lines, ATX closing hashes,
Pandoc table detection boundaries, MyST `{code-cell}` fences, embedded-formatter failures
propagated out of nested regions, renderer preambles at end of file, canonical headings,
autolink/HTML boundaries, link normalization limits, column/sentence layout repairs, long
link and image splitting, `paragraph`/`none` wrapping details, footnote, list, blockquote and
definition-list container boundaries, template recognition limits, CRLF tables without a final
newline, late file-scope template delimiters and front matter with empty mapping keys.
"""

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

UNCHANGED = '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
NEXT_TARGET = '<!-- fmt: wrap=sentence scope=next -->\n'
FAILING_PYTHON = (
    '[embedded.python]\n'
    'formatter = { command = ["python3", "-c", "import sys; sys.exit(7)", "{path}"], path_suffix = ".py" }\n'
)
SPACING_PYTHON = (
    '[embedded.python]\n'
    'formatter = { command = ["python3", "-c", "import sys; d = sys.stdin.read(); '
    'sys.stdout.write(d.replace(\'=\', \' = \'))", "{path}"], path_suffix = ".py" }\n'
)
UPPERCASE_PYTHON = (
    '[embedded.python]\n'
    'formatter = { command = ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())", '
    '"{path}"], path_suffix = ".py" }\n'
)


# --- explicit targets and directive errors -------------------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(
            '+--------+-----+\n| a      | b   |\n+========+=====+\n| \\LaTeX | 2   |\n+--------+-----+\n',
            id="grid-table",
        ),
        pytest.param('-------------\nA     B\n----- -----\n\\LaTeX   x\n\n-------------\n', id="multiline-table"),
        pytest.param('A     B\n----- -----\n\\LaTeX   x\n', id="simple-table"),
        pytest.param('| a | b |\n|---|---|\n| \\LaTeX | x |\n', id="pipe-table"),
        pytest.param('[^1]: before \\LaTeX after\n', id="footnote"),
    ],
)
def test_next_target_on_raw_tex_table_or_footnote_is_rejected(run, workdir, block):
    """CATCHES: an implementation that silently copies a grid, multiline, simple or pipe table (or a footnote definition) containing a raw TeX command when a `scope=next` Markdown directive explicitly targets it, instead of failing with "fmt: markdown targets an unsupported Markdown block" at the block's first line."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=NEXT_TARGET + block)
    assert result.stdout == b''
    assert result.stderr.decode() == 'x.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_pending_target_at_end_of_quarto_div_is_an_error(run, workdir):
    """CATCHES: an implementation that lets a `scope=next` directive on the last line of a Quarto div body apply to content after the div (or ignore it) instead of reporting "fmt: markdown has no target" at the end of the directive line inside the div."""
    stdin = (
        '::: note\n'
        'Text   here.\n'
        '<!-- fmt: canonical=true scope=next -->\n'
        ':::\n'
    )
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'x.md:3:40: error: fmt: markdown has no target\n'
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        pytest.param('::: note\n<!-- fmt: bogus -->\n:::\n', 'x.md:2:6: error: invalid fmt directive: bogus\n', id="quarto-div"),
        pytest.param(
            'Intro.\n\n```markdown\n<!-- fmt: bogus -->\n```\n',
            'x.md:4:6: error: invalid fmt directive: bogus\n',
            id="markdown-fence",
        ),
        pytest.param(
            '```yaml\n# fmt: bogus\na: 1\n```\n',
            'x.md:2:1: error: unknown embedded formatter: bogus\n',
            id="yaml-fence",
        ),
    ],
)
def test_directive_errors_inside_nested_regions_are_reported(run, workdir, stdin, stderr):
    """CATCHES: an implementation that skips or copies a Quarto div, Markdown fence or YAML fence whose body contains an invalid `fmt:` directive instead of failing with the nested directive's error at its position in the outer file."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


# --- paragraph boundaries ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        pytest.param('Para   text\n- item   one\n', b'Para text\n- item one\n', id="list-item"),
        pytest.param('Para   text\n    indented   more\n', b'Para text\n    indented   more\n', id="four-space-indent"),
        pytest.param('Para   text\nTable:   caption   here\n', b'Para text\nTable:   caption   here\n', id="table-caption"),
    ],
)
def test_paragraph_ends_before_list_item_indented_line_or_caption(run, workdir, stdin, expected):
    """CATCHES: an implementation that joins a directly following list item, four-space-indented line or `Table:` caption into the preceding paragraph (CommonMark lazy continuation) instead of ending the paragraph there and keeping the indented/caption line byte-for-byte."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("field", "golden"),
    [
        pytest.param('{value:{width}}', 'fstring_nested_braces.golden', id="balanced-nested"),
        pytest.param('{value:{width}', 'fstring_unbalanced.golden', id="unbalanced"),
    ],
)
def test_python_fstring_replacement_field_line_with_nested_braces(run, workdir, field, golden):
    """CATCHES: an implementation that only recognises flat `{name}` lines as standalone f-string replacement fields (joining `{value:{width}}` into the surrounding prose), or that treats an unbalanced `{value:{width}` line as standalone instead of reflowing it with the paragraph."""
    stdin = '# fmt: markdown\nx = f"""\nSome   text here.\n' + field + '\nMore   text.\n"""\n'
    result = run(['format', '--stdin-file-path', 'x.py'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_atx_closing_hashes_need_a_preceding_space(run, workdir):
    """CATCHES: an implementation that strips `#` characters glued to the heading text (`# C#` becoming `# C`, `## Learn F##` becoming `## Learn F`) as if they were a closing sequence."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='#   C#\n\n##   Learn F##   \n')
    assert result.stdout == (RES / 'heading_hash_suffix.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_empty_brace_line_joins_paragraph(run, workdir):
    """CATCHES: an implementation that treats a `{  }` line with no attribute tokens as a standalone Pandoc block attribute (splitting the paragraph) instead of reflowing it as prose."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='Para   text\n{  }\nmore   text\n')
    assert result.stdout == b'Para text {  } more text\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unclosed_html_block_is_preserved_to_end_of_file(run, workdir):
    """CATCHES: an implementation that ends an unclosed `<details>` HTML block at the next blank line and reflows the following text, instead of keeping everything after the opening tag byte-for-byte."""
    stdin = 'Before   text.\n\n<details>\nSome   text\n\nMore   text\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'unclosed_html_block.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        pytest.param('<a:b>   more', b'Para text\n<a:b>   more\n', id="one-letter-scheme-is-html"),
        pytest.param('<a_b:c>   more', b'Para text\n<a_b:c>   more\n', id="underscore-scheme-is-html"),
        pytest.param('<1a:b>   more', b'Para text <1a:b> more\n', id="digit-start-is-text"),
    ],
)
def test_autolink_scheme_rules_decide_html_block_starts(run, workdir, line, expected):
    """CATCHES: an implementation that accepts one-character or underscore-containing URI schemes as CommonMark autolinks (so `<a:b>` / `<a_b:c>` would join the paragraph), or that treats `<1a:b>` (not a tag name) as an HTML block start instead of paragraph text."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='Para   text\n' + line + '\n')
    assert result.stdout == expected
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- Pandoc and pipe table detection ----------------------------------------------------------


def test_grid_rows_without_closing_border_at_eof_are_preserved(run, workdir):
    """CATCHES: an implementation that formats (or reflows) `+---+` followed only by `|` rows up to end of file as a grid table instead of preserving the unterminated rows."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='#   Rows\n\n+-----+\n| a   |\n| b   |\n')
    assert result.stdout == (RES / 'grid_rows_to_eof.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param(
            '-------------\n----- -----\nA     B\n-------------\n', 'multiline_inner_first.golden', id="inner-separator-before-header"
        ),
        pytest.param(
            '-------------\nA     B\n=============\n----- -----\n', 'multiline_outer_twice.golden', id="second-outer-bound-before-separator"
        ),
    ],
)
def test_malformed_continuous_multiline_bounds_fall_back(run, workdir, stdin, golden):
    """CATCHES: an implementation that accepts a multiline table whose column separator appears before any header line, or whose header is closed by a second outer `====` bound, instead of falling back to simple-table and setext/thematic-break handling."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_pipe_row_followed_by_bare_bar_is_not_a_table(run, workdir):
    """CATCHES: an implementation that treats a lone `|` line as a pipe-table delimiter row (it has no dashes) and formats the two lines as a table."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='#   Pipes\n\n| a   |\n|\n')
    assert result.stdout == (RES / 'pipe_bar_only_delimiter.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_indented_pandoc_table_shape_keeps_following_flush_line(run, workdir):
    """CATCHES: an implementation that ends an indented code block shaped like a simple table at the first non-indented line (reflowing `flush   line`) instead of preserving the whole run up to the blank line."""
    stdin = '    A     B\n    ----- -----\nflush   line\n\nAfter   text.\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'indented_pandoc_table.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('#   Grid\n\n+---++---+\n| a  || b |\n+---++---+\n', 'grid_empty_column_part.golden', id="empty-part"),
        pytest.param('#   Grid\n\n+---+:::+\n| a | b |\n+---+:::+\n', 'grid_colon_column_part.golden', id="colon-only-part"),
    ],
)
def test_grid_border_with_empty_or_colon_only_column_is_preserved(run, workdir, stdin, golden):
    """CATCHES: an implementation that formats a grid table whose border contains an empty `++` column or a colon-only `:::` column (no dashes) instead of keeping the table verbatim."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('| a | b |\r\n|---|---|\r\n| 1 | 2 |', 'crlf_pipe_eof.golden', id="pipe"),
        pytest.param('+-----+-----+\r\n| a | b |\r\n+-----+-----+', 'crlf_grid_eof.golden', id="grid"),
        pytest.param('a     b\r\n----- -----\r\n1     2', 'crlf_simple_eof.golden', id="simple"),
        pytest.param('-------------\r\nA     B\r\n----- -----\r\n1     2\r\n-------------', 'crlf_multiline_eof.golden', id="multiline"),
    ],
)
def test_crlf_table_without_final_newline_gets_crlf_terminator(run, workdir, stdin, golden):
    """CATCHES: an implementation that leaves a dangling `\\r`, mixes in `\\n`, or omits the final line ending when fitting a CRLF pipe, grid, simple or multiline table that ends the file without a newline."""
    write_tree(workdir, {'x.md': stdin})
    result = run(['format', 'x.md'])
    assert result.stdout.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    assert read_tree(workdir) == {'x.md': (RES / golden).read_bytes()}


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('#   T\n\n| a | b |\n|---|---|\n| \\LaTeX | 2 |\n', 'pipe_table_latex.golden', id="pipe"),
        pytest.param('#   T\n\na     b\n----- -----\n\\LaTeX     2\n', 'simple_table_latex.golden', id="simple"),
    ],
)
def test_table_with_raw_tex_command_is_preserved(run, workdir, stdin, golden):
    """CATCHES: an implementation that fits a pipe or simple table whose cell contains a raw TeX command (`\\LaTeX`) instead of preserving the table byte-for-byte while still formatting the heading."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- fences ------------------------------------------------------------------------------------


def test_code_cell_yaml_fence_is_formatted_as_yaml(run, workdir):
    """CATCHES: an implementation that does not read the language after a MyST `{code-cell}` info string, leaving a `{code-cell} yaml` fence body unformatted."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='```{code-cell} yaml\na:   1\nb:   [x,y]\n```\n')
    assert result.stdout == (RES / 'code_cell_yaml.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_code_cell_without_language_is_kept(run, workdir):
    """CATCHES: an implementation that guesses a language (or rewrites the body) for a bare `{code-cell}` fence instead of preserving it while formatting the surrounding prose."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='```{code-cell}\na:   1\n```\n\nAfter   text.\n')
    assert result.stdout == (RES / 'code_cell_no_language.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('```{code-cell} python\n:tags: [x]\n:other: y\nx = 1\n```\n', 'code_cell_python.golden', id="python"),
        pytest.param('```{code-cell} ipython3\n:tags: [x]\nx = 1\n```\n', 'code_cell_ipython3.golden', id="ipython3-alias"),
    ],
)
def test_code_cell_options_are_not_sent_to_formatter(run, workdir, stdin, golden):
    """CATCHES: an implementation that passes MyST `:option:` lines at the top of a `{code-cell} python` (or `ipython3`) fence to the embedded formatter (the uppercasing formatter would turn `:tags:` into `:TAGS:`), or that does not map `ipython3` to the Python formatter."""
    write_tree(workdir, {'yamark.toml': UPPERCASE_PYTHON})
    result = run(['format', '--config', 'yamark.toml', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('```yaml\na:   1\n``` not-close\nb:   2\n```\n', 'yaml_fence_inner_backticks.golden', id="info-after-marker"),
        pytest.param('````yaml\na:   1\n```\nb:   2\n````\n', 'yaml_fence_shorter_inner.golden', id="shorter-marker"),
    ],
)
def test_non_closing_backtick_line_stays_inside_yaml_fence(run, workdir, stdin, golden):
    """CATCHES: an implementation that closes a YAML fence at a backtick line that has trailing info text or fewer backticks than the opener, instead of keeping it as (quoted) YAML content of the fence."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('#   Fences\n\n```yaml {.yaml title="x"}\na:   1\n```\n', 'bare_language_quoted_attr.golden', id="quoted-attribute"),
        pytest.param('#   Fences\n\n```#x {.x}\nhi\n```\n', 'bare_language_hash.golden', id="hash-language"),
    ],
)
def test_fence_info_with_quotes_or_hash_language_is_not_normalized(run, workdir, stdin, golden):
    """CATCHES: an implementation that drops the redundant `.yaml` class from `yaml {.yaml title="x"}` even though the attributes contain quotes, or that treats `#x` as a language and rewrites `#x {.x}`."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- embedded formatters inside nested regions --------------------------------------------------


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        pytest.param(
            'x.md',
            '````markdown\n```python\nx=1\n```\n````\n',
            'x.md:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.md.embedded.3.py` exited with exit status 7 for x.md.embedded.3.py\n',
            id="markdown-fence",
        ),
        pytest.param(
            'x.md',
            '::: note\n```python\nx=1\n```\n:::\n',
            'x.md:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.md.embedded.3.py` exited with exit status 7 for x.md.embedded.3.py\n',
            id="quarto-div",
        ),
        pytest.param(
            'x.md',
            '---\n# fmt: python\ncode: |\n  x=1\n---\n\nBody\n',
            'x.md:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.md.embedded.4.py` exited with exit status 7 for x.md.embedded.4.py\n',
            id="front-matter-scalar",
        ),
        pytest.param(
            'x.md',
            '```yaml\n# fmt: python\ncode: |\n  x=1\n```\n',
            'x.md:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.md.embedded.4.py` exited with exit status 7 for x.md.embedded.4.py\n',
            id="yaml-fence-scalar",
        ),
        pytest.param(
            'x.py',
            '# fmt: markdown\nx = """\n```python\ny=1\n```\n"""\n',
            'x.py:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.py.embedded.2.py` exited with exit status 7 for x.py.embedded.2.py\n',
            id="python-markdown-string",
        ),
        pytest.param(
            'x.py',
            '# fmt: markdown\n# ```python\n# y=1\n# ```\nz = 1\n',
            'x.py:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.py.embedded.2.py` exited with exit status 7 for x.py.embedded.2.py\n',
            id="python-markdown-comment",
        ),
        pytest.param(
            'x.py',
            '#| # fmt: python\n#| code: |\n#|   y=1\nz = 1\n',
            'x.py:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) x.py.embedded.3.py` exited with exit status 7 for x.py.embedded.3.py\n',
            id="hashpipe-yaml-scalar",
        ),
    ],
)
def test_failing_formatter_inside_nested_region_fails_the_file(run, workdir, path, stdin, stderr):
    """CATCHES: an implementation that swallows an embedded-formatter failure when the failing fence or scalar sits inside a Markdown fence, Quarto div, front matter, YAML fence, marked Python string/comment or hashpipe block (printing partially formatted output) instead of failing the whole file with the formatter error and exit status 1."""
    write_tree(workdir, {'yamark.toml': FAILING_PYTHON})
    result = run(['format', '--config', 'yamark.toml', '--stdin-file-path', path], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


def test_renderer_preamble_only_block_scalar_at_eof(run, workdir):
    """CATCHES: an implementation that sends a `#|` renderer preamble to the (uppercasing) embedded formatter, drops it when it is the whole formatter-target block scalar at end of file without a newline, or keeps clip chomping `|` (which would add a final newline to the value) instead of switching to `|-`."""
    write_tree(workdir, {'yamark.toml': UPPERCASE_PYTHON})
    result = run(
        ['format', '--config', 'yamark.toml', '--stdin-file-path', 'x.yaml'],
        input='# fmt: python\ncode: |\n  #| label: x',
    )
    assert result.stdout == b'# fmt: python\ncode: |-\n  #| label: x'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_renderer_preamble_then_code_at_eof(run, workdir):
    """CATCHES: an implementation that sends the `#|` preamble line to the uppercasing embedded formatter (yielding `#| LABEL: X`), or that fails to format the code after the preamble (and terminate it) in a block scalar ending the file without a newline."""
    write_tree(workdir, {'yamark.toml': UPPERCASE_PYTHON})
    result = run(
        ['format', '--config', 'yamark.toml', '--stdin-file-path', 'x.yaml'],
        input='# fmt: python\ncode: |\n  #| label: x\n  y=1',
    )
    assert result.stdout == (RES / 'preamble_then_code_at_eof.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_python_string_formatter_body_starting_on_opening_line(run, workdir):
    """CATCHES: an implementation that refuses a `# fmt: python` triple-quoted string whose code starts right after the opening quotes, or that loses the line ending between the formatted lines."""
    write_tree(workdir, {'yamark.toml': SPACING_PYTHON})
    result = run(
        ['format', '--config', 'yamark.toml', '--stdin-file-path', 'x.py'],
        input='# fmt: python\nx = """y=1\nz=2\n"""\n',
    )
    assert result.stdout == (RES / 'py_string_body_on_opening_line.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- canonical headings and inline normalization ---------------------------------------------


def test_canonical_heading_stops_at_unclosed_strikethrough(run, workdir):
    """CATCHES: an implementation whose `--canonical` pass keeps converting `__bold__` to `**bold**` after an unclosed `~~` in a heading, instead of leaving the rest of that heading verbatim (other headings still canonicalize)."""
    result = run(
        ['format', '--stdin-file-path', 'x.md', '--canonical'],
        input='#   Use ~~strike and __bold__\n\n#   Plain __bold__\n',
    )
    assert result.stdout == (RES / 'canonical_heading_unclosed_strike.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_canonical_heading_html_span_ends_at_matching_tag(run, workdir):
    """CATCHES: an implementation that ends an inline `<span>` at the first closing tag of any name (`</b>`), canonicalizing `__y__` inside the span, instead of protecting the span up to its matching `</span>`."""
    result = run(
        ['format', '--stdin-file-path', 'x.md', '--canonical'],
        input='#   A <span>x</b> __y__</span> __z__\n',
    )
    assert result.stdout == b'# A <span>x</b> __y__</span> **z**\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        pytest.param("See [a](  x  ){  .c   key='v' } now.\n", b"See [a](x){  .c   key='v' } now.\n", id="single-quoted-value"),
        pytest.param('See [a](  x  ){ } now.\n', b'See [a](x){ } now.\n', id="empty-attribute"),
    ],
)
def test_unsupported_link_attribute_is_kept_verbatim(run, workdir, stdin, expected):
    """CATCHES: an implementation that collapses spacing inside a link attribute block containing a single-quoted value, or rewrites an empty `{ }` attribute, while it still normalizes the link destination."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        pytest.param('Text   *{x} [a](  b  )*   end.\n', b'Text *{x} [a](b)* end.\n', id="braces-before-link"),
        pytest.param('Text   *[a][b] [c](  d  )*   end.\n', b'Text *[a][b] [c](d)* end.\n', id="reference-before-link"),
    ],
)
def test_links_inside_emphasis_are_normalized_after_protected_spans(run, workdir, stdin, expected):
    """CATCHES: an implementation that stops normalizing link destinations inside emphasis once it meets a `{...}` span or a reference-style `[a][b]` link, leaving `[a](  b  )` with its padding."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    "stdin",
    [
        pytest.param('See [a \\ b](  z  ) now   ok.\n', id="backslash"),
        pytest.param('See [a ` b](  z  ) now   ok.\n', id="backtick"),
        pytest.param('See [a $ b](  z  ) now   ok.\n', id="dollar"),
        pytest.param('See [a < b](  z  ) now   ok.\n', id="less-than"),
    ],
)
def test_link_label_with_unpaired_inline_marker_preserves_paragraph(run, workdir, stdin):
    """CATCHES: an implementation that normalizes a link whose label contains an unpaired backslash, backtick, dollar or `<` (whose meaning depends on later text), changing `](  z  )` or the paragraph spacing, instead of leaving the whole paragraph unchanged."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == UNCHANGED
    assert checked.returncode == 0


# --- layout --------------------------------------------------------------------------------------


@pytest.mark.parametrize("wrap", ["sentence", "20"])
def test_backslash_only_line_after_hard_break_is_dropped(run, workdir, wrap):
    """CATCHES: an implementation that keeps a line consisting only of a backslash hard break (an empty hard-break segment) between two sentences, instead of emitting just `First.\\` and `Second.`."""
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', wrap], input='First.\\\n\\\nSecond.\n')
    assert result.stdout == b'First.\\\nSecond.\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    "stdin",
    [
        pytest.param('aaaaaaaaaa ~ bbbbbbbbb\n', id="mid-paragraph"),
        pytest.param('aaaaaaaaaa ~\n', id="end-of-paragraph"),
    ],
)
def test_tilde_word_that_would_start_definition_keeps_line_overlong(run, workdir, stdin):
    """CATCHES: an implementation that wraps at column 10 and puts `~` at the start of a line (turning it into a Pandoc definition marker) or escapes it, instead of declining to wrap the paragraph."""
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '10'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    write_tree(workdir, {'x.md': stdin})
    checked = run(['format', '--check', '--wrap', '10', 'x.md'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == UNCHANGED
    assert checked.returncode == 0


def test_nested_image_link_keeps_short_outer_target_on_closing_line(run, workdir):
    """CATCHES: an implementation that also splits the short outer target of a linked image (`)](a.html)` fits in 30 columns) onto separate lines after splitting the long image destination."""
    result = run(
        ['format', '--stdin-file-path', 'x.md', '--wrap', '30'],
        input='[![alt](averyveryverylongimagepath.png)](a.html)\n',
    )
    assert result.stdout == (RES / 'nested_image_link_close_fits.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param(
            'See <http://x.y> and [a](  http://example.com/very/long/path/here  ) end\n',
            'autolink_blocks_target_normalization.golden',
            id="padded-target",
        ),
        pytest.param(
            'See <http://x.y> and [a](http://example.com/very/long/path/here){.c   #i} end\n',
            'autolink_blocks_attr_normalization.golden',
            id="unnormalized-attribute",
        ),
        pytest.param(
            'See <http://x.y> and [ a](http://example.com/very/long/path/here) end\n',
            'autolink_blocks_label_normalization.golden',
            id="padded-label",
        ),
    ],
)
def test_autolink_paragraph_keeps_unnormalized_long_link_whole(run, workdir, stdin, golden):
    """CATCHES: an implementation that normalizes or splits a long link's destination across lines in a paragraph that also contains an autolink (where link normalization is disabled), instead of moving the unnormalized link to its own overlong line."""
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('See [averyveryverylonglabeltextxx][ref] end\n', 'long_reference_link.golden', id="reference-link"),
        pytest.param('See ![a](b.png){width=50% height=20%}xyz end\n', 'image_attr_trailing_text.golden', id="image-attribute-with-trailing-text"),
    ],
)
def test_overlong_unsplittable_link_token_gets_own_line(run, workdir, stdin, golden):
    """CATCHES: an implementation that tries to split a long reference-style link (no `(` destination) or an image attribute block followed by non-punctuation text, instead of keeping the token whole on its own line."""
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', '30'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("width", "stdin", "golden"),
    [
        pytest.param('30', '![cap](img.png){#fig-a fig-alt="short words"}\n', 'fig_alt_one_line.golden', id="alt-fits-one-line"),
        pytest.param(
            '40',
            '![cap](img.png){#fig-abc fig-alt="Averyveryverylongword more words"}\n',
            'fig_alt_first_word_long.golden',
            id="first-word-too-wide",
        ),
    ],
)
def test_fig_alt_not_rewrapped_when_wrapping_does_not_help(run, workdir, width, stdin, golden):
    """CATCHES: an implementation that splits fig-alt text across lines when it already fits on one attribute line, or when its first word does not fit after the `fig-alt="` prefix, instead of moving the attributes unchanged onto one line between `{` and `}`."""
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', width], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_paragraph_mode_escapes_leading_tilde_marker_but_none_mode_does_not(run, workdir):
    """CATCHES: an implementation that leaves a paragraph starting with `~ ` unescaped under `--wrap paragraph` (where the joined line would read as a definition marker), or that adds the escape under `--wrap none`."""
    result = run(['format', '--stdin-file-path', 'x.md', '--wrap', 'paragraph'], input='~ foo   bar\n')
    assert result.stdout == b'\\~ foo bar\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    untouched = run(['format', '--stdin-file-path', 'x.md', '--wrap', 'none'], input='~ foo   bar \n')
    assert untouched.stdout == b'~ foo   bar\n'
    assert untouched.stderr.decode() == ''
    assert untouched.returncode == 0


def test_wrap_none_trims_trailing_space_inside_multiline_html_span(run, workdir):
    """CATCHES: an implementation that keeps trailing whitespace at a soft break inside a multi-line inline `<span>` under `--wrap none`, or that collapses the authored spacing it must preserve."""
    result = run(
        ['format', '--stdin-file-path', 'x.md', '--wrap', 'none'],
        input='Some   <span>a   b \nc   d</span>   lines.\n',
    )
    assert result.stdout == b'Some   <span>a   b\nc   d</span>   lines.\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- containers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('[^1]:\n    Para   one.\n    - item', 'footnote_eof_recursive.golden', id="block-body"),
        pytest.param('[^1]: Text   here.\n\n    More   text.', 'footnote_eof_blank.golden', id="blank-separated"),
        pytest.param('[^1]: Text   here.\r\n\r\n    More   `code`', 'footnote_eof_code_crlf.golden', id="crlf-with-code"),
    ],
)
def test_multiblock_footnote_at_eof_without_newline(run, workdir, stdin, golden):
    """CATCHES: an implementation that leaves a multi-block footnote that ends the file without a newline unterminated, terminates it with `\\n` in a CRLF file, or mangles the trailing inline code span while re-indenting the body."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_footnote_followed_only_by_blank_lines(run, workdir):
    """CATCHES: an implementation that drops the trailing blank lines after a final footnote definition, or extends the footnote over them, instead of formatting the definition and keeping the blank lines."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='[^1]: Note   text\n\n\n')
    assert result.stdout == (RES / 'footnote_trailing_blank_lines.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_footnote_continuation_below_label_indent_is_preserved(run, workdir):
    """CATCHES: an implementation that reflows a footnote indented by one space whose continuation line is indented less than the label's content (2 instead of 3 spaces), instead of preserving the definition."""
    stdin = ' [^1]: Note   text\n  more   text\n\nAfter   text.\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / 'footnote_indented_label_short_continuation.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_blockquote_fragment_formats_around_preserved_paragraph(run, workdir):
    """CATCHES: an implementation that preserves a whole multi-paragraph blockquote because one paragraph contains an incomplete `{{` template, or that drops the preserved paragraph, instead of keeping that paragraph verbatim and formatting the next one."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='> a   {{ x   b\n>\n> c   d\n')
    assert result.stdout == (RES / 'quote_fragment_preserved_paragraph.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param(
            '- a   `x\n  y`   b\n\n  Heading\n  -------\n\nAfter   text.\n', 'list_setext_child_with_literal.golden', id="setext-child-with-multiline-code"
        ),
        pytest.param('- a   b\n  >\tquoted\n\nAfter   text.\n', 'list_quote_child_tab.golden', id="quote-child-tab"),
        pytest.param('- a   b\n  >     quoted\n\nAfter   text.\n', 'list_quote_child_wide_gap.golden', id="quote-child-five-spaces"),
        pytest.param('- a   b\n\n  ```\n code\n  ```\n\nAfter   text.\n', 'list_fence_underindented.golden', id="fence-child-underindented"),
    ],
)
def test_list_with_unsupported_child_is_preserved(run, workdir, stdin, golden):
    """CATCHES: an implementation that reflows a list whose child is a setext heading (even when another line holds a multi-line code span), a quote child with a tab or code-indented body after `>`, or a fenced child with an under-indented line, instead of preserving the list and formatting only the following paragraph."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_list_with_unclosed_fence_child_formats_item_text(run, workdir):
    """CATCHES: an implementation that preserves (or reflows into) an unclosed fenced child that runs to the end of the list, instead of reflowing the item text and keeping the fence body verbatim."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='- a   b\n\n  ```\n  code\n')
    assert result.stdout == (RES / 'list_fence_unclosed.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_task_item_continuation_within_checkbox_indent_joins_item(run, workdir):
    """CATCHES: an implementation that only accepts task-list continuation lines at exactly the content column (6 for `- [ ] `), preserving lines indented 7 or 8 spaces, instead of joining any line indented within the checkbox continuation range."""
    stdin = '- [ ] task   one\n       more   text\n- [x] done   two\n        more   text\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == b'- [ ] task one more text\n- [x] done two more text\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('Term\n~ def   one\n~x\n', 'definition_tilde_without_space.golden', id="tilde"),
        pytest.param('Term\n: def   one\n:x\n\nAfter   text.\n', 'definition_colon_without_space.golden', id="colon"),
    ],
)
def test_definition_marker_without_following_space(run, workdir, stdin, golden):
    """CATCHES: an implementation that treats `~x` or `:x` (no space after the marker) as another definition, or that reformats the `:`-style list containing a raw `:x` line instead of preserving it (a `~x` line is kept as text while the definition still formats)."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- link targets, math and templates that keep a paragraph verbatim --------------------------


@pytest.mark.parametrize(
    ("paragraph", "golden"),
    [
        pytest.param('See [a](  x\\y   "t"  ) now   ok.\n', 'link_dest_backslash_title.golden', id="backslash-destination"),
        pytest.param('See [a](  x"y   "t"  ) now   ok.\n', 'link_dest_quote.golden', id="quote-in-destination"),
        pytest.param('See [a](b and   more\n', 'link_unclosed_dest.golden', id="unclosed-destination"),
        pytest.param('See [a](x  "t" y) now   ok.\n', 'link_title_trailing_text.golden', id="text-after-title"),
        pytest.param('See [a](x  (t(u))) now   ok.\n', 'link_title_nested_paren.golden', id="nested-paren-title"),
    ],
)
def test_unsupported_link_target_preserves_paragraph(run, workdir, paragraph, golden):
    """CATCHES: an implementation that normalizes padding in a link whose destination contains a backslash or quote, is unclosed, has text after its title, or has a parenthesized title with nested parentheses, instead of leaving the paragraph's bytes unchanged (the heading above still formats)."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='#   Links\n\n' + paragraph)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param('#   Money\n\nCosts $5   now café.\n', 'unmatched_dollar.golden', id="unmatched-dollar"),
        pytest.param('#   Strike\n\nSee ~~   ~~ more   text.\n', 'blank_strikethrough.golden', id="blank-strikethrough"),
        pytest.param('#   Refs\n\nSee [a][b\nc]   more.\n', 'reference_label_newline.golden', id="reference-label-newline"),
        pytest.param('#   Tmpl\n\nBefore {{ foo   café.\n', 'incomplete_template_non_ascii.golden', id="incomplete-template"),
    ],
)
def test_ambiguous_inline_syntax_preserves_paragraph(run, workdir, stdin, golden):
    """CATCHES: an implementation that reflows a paragraph containing an unmatched `$`, a whitespace-only `~~   ~~`, a reference label split across lines, or an incomplete `{{` template next to non-ASCII text, instead of keeping the paragraph byte-for-byte."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("paragraph", "golden"),
    [
        pytest.param('Use {{ x }} and \\{{ y }}   here.\n', 'template_escaped_second.golden', id="escaped-template"),
        pytest.param('Use {{ x }} and \\`code`   here.\n', 'template_escaped_backtick.golden', id="escaped-backtick"),
        pytest.param('Use {{ x }} and ~~open   text.\n', 'template_unclosed_strike.golden', id="unclosed-strikethrough"),
    ],
)
def test_template_paragraph_with_ambiguous_markup_is_preserved(run, workdir, paragraph, golden):
    """CATCHES: an implementation that reflows a paragraph containing a `{{ x }}` template when it also contains an escaped `\\{{` opener, an escaped backtick or an unclosed `~~`, instead of keeping the whole paragraph verbatim."""
    result = run(['format', '--stdin-file-path', 'x.md'], input='#   Tmpl\n\n' + paragraph)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        pytest.param(
            '#   Title   <<x>>\n\nA   b\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
            'late_template_atx_heading.golden',
            id="atx",
        ),
        pytest.param(
            'Title   <<x>>\n===\n\nA   b\n\n<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n',
            'late_template_setext_heading.golden',
            id="setext",
        ),
    ],
)
def test_late_file_scope_template_delimiters_preserve_earlier_heading(run, workdir, stdin, golden):
    """CATCHES: an implementation that applies a `scope=file` template-delimiter directive only to blocks after it, normalizing (or converting to ATX) an earlier heading that contains `<<x>>`, instead of preserving that heading while still formatting the paragraph."""
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


# --- front matter --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("empty_key", "golden"),
    [
        pytest.param(': orphan\n', 'front_matter_empty_key.golden', id="implicit"),
        pytest.param('?\n: orphan\n', 'front_matter_explicit_empty_key.golden', id="explicit"),
    ],
)
def test_front_matter_empty_key_does_not_hide_editor_options(run, workdir, empty_key, golden):
    """CATCHES: an implementation that stops reading front matter (ignoring `editor_options.markdown.wrap: sentence`) when the mapping also has a pair with an empty implicit or explicit key, instead of applying sentence wrapping to the body."""
    stdin = '---\neditor_options:\n  markdown:\n    wrap: sentence\n' + empty_key + '---\n\nA   b.  C d.\n'
    result = run(['format', '--stdin-file-path', 'x.md'], input=stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
