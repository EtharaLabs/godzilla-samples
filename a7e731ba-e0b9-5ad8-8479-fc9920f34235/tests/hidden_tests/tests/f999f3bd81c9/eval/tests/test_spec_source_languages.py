"""Spec source languages behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_embedded_comment_markdown_blank_lines_do_not_gain_trailing_spaces(run, workdir):
    """CATCHES: reimplementations that break "embedded comment markdown blank lines do not gain trailing spaces" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '# #   Title ##\n'
        '#\n'
        '# Body text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_comment_markdown_blank_lines_do_not_gain_trailing_spaces.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_comment_markdown_wrap_width_accounts_for_prefix(run, workdir):
    """CATCHES: reimplementations that break "embedded comment markdown wrap width accounts for prefix" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '    # one two three four\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '18'], input=stdin)
    assert result.stdout == (RES / 'embedded_comment_markdown_wrap_width_accounts_for_prefix.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_comment_markdown_wrap_width_uses_visual_prefix_width(run, workdir):
    """CATCHES: reimplementations that break "embedded comment markdown wrap width uses visual prefix width" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '\u3000# abc de f\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '11'], input=stdin)
    assert result.stdout == (RES / 'embedded_comment_markdown_wrap_width_uses_visual_prefix_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_comment_sentence_column_wrap_accounts_for_prefix(run, workdir):
    """CATCHES: reimplementations that break "embedded comment sentence column wrap accounts for prefix" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '    # One short. This second sentence has more words.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence:18'], input=stdin)
    assert result.stdout == (RES / 'embedded_comment_sentence_column_wrap_accounts_for_prefix.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_markdown_string_targets_ignore_delimiter_padding_1(run, workdir):
    """CATCHES: reimplementations that break "embedded markdown string targets ignore delimiter padding" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '    #   Title ##\n'
        '    \n'
        '    """\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_markdown_string_targets_ignore_delimiter_padding_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_markdown_string_targets_ignore_delimiter_padding_2(run, workdir):
    """CATCHES: reimplementations that break "embedded markdown string targets ignore delimiter padding" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '    # Title\n'
        '    """\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_markdown_string_targets_ignore_delimiter_padding_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_markdown_string_targets_ignore_delimiter_padding_3(run, workdir):
    """CATCHES: reimplementations that break "embedded markdown string targets ignore delimiter padding" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '# fmt: markdown\n'
        'text <- "\n'
        '    #   Title ##\n'
        '    \n'
        '    "\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_markdown_string_targets_ignore_delimiter_padding_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_markdown_string_targets_ignore_delimiter_padding_4(run, workdir):
    """CATCHES: reimplementations that break "embedded markdown string targets ignore delimiter padding" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '# fmt: markdown\n'
        'text <- "\n'
        '    # Title\n'
        '    "\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_markdown_string_targets_ignore_delimiter_padding_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.r').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.r'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_markdown_string_targets_ignore_delimiter_padding_5(run, workdir):
    """CATCHES: reimplementations that break "embedded markdown string targets ignore delimiter padding" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '# fmt: markdown\n'
        'text <- r"(\n'
        '    #   Title ##\n'
        '    \n'
        '    )"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_markdown_string_targets_ignore_delimiter_padding_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_markdown_string_targets_ignore_delimiter_padding_6(run, workdir):
    """CATCHES: reimplementations that break "embedded markdown string targets ignore delimiter padding" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '# fmt: markdown\n'
        'text <- r"(\n'
        '    # Title\n'
        '    )"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_markdown_string_targets_ignore_delimiter_padding_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.r').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.r'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_python_comment_markdown_restores_prefixes_for_cr_only_lines(run, workdir):
    """CATCHES: reimplementations that break "embedded python comment markdown restores prefixes for cr only lines" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\r'
        '# one two three four\r'
        '# five six seven eight\r'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '14'], input=stdin)
    assert result.stdout == (
        b'# fmt: markdown\r'
        b'# one two\r'
        b'# three four\r'
        b'# five six\r'
        b'# seven eight\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_python_comment_markdown_target(run, workdir):
    """CATCHES: reimplementations that break "embedded python comment markdown target" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '# #   Title ##\n'
        '# This is __strong__. This is _emphasis_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'embedded_python_comment_markdown_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_python_markdown_string_keeps_closing_delimiter_at_content_indent(run, workdir):
    """CATCHES: reimplementations that break "embedded python markdown string keeps closing delimiter at content indent" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '    #   Title ##\n'
        '    """\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_python_markdown_string_keeps_closing_delimiter_at_content_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_python_markdown_string_preserves_column_zero_closing_delimiter(run, workdir):
    """CATCHES: reimplementations that break "embedded python markdown string preserves column zero closing delimiter" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '    #   Title ##\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_python_markdown_string_preserves_column_zero_closing_delimiter.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_python_markdown_string_target_accepts_escaped_opening_newline(run, workdir):
    """CATCHES: reimplementations that break "embedded python markdown string target accepts escaped opening newline" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\\\n'
        '    #   Title ##\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_python_markdown_string_target_accepts_escaped_opening_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_python_markdown_string_targets_are_dedented_and_reindented(run, workdir):
    """CATCHES: reimplementations that break "embedded python markdown string targets are dedented and reindented" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '    #   Title ##\n'
        '    This is __strong__. This is _emphasis_.\n'
        '"""\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'embedded_python_markdown_string_targets_are_dedented_and_reindented.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_python_markdown_targets_support_cr_only_line_endings(run, workdir):
    """CATCHES: reimplementations that break "embedded python markdown targets support cr only line endings" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\r'
        'DOC = """\r'
        '#   Title ##\r'
        '"""\r'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (
        b'# fmt: markdown\r'
        b'DOC = """\r'
        b'# Title\r'
        b'"""\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_r_markdown_string_keeps_closing_delimiter_at_content_indent(run, workdir):
    """CATCHES: reimplementations that break "embedded r markdown string keeps closing delimiter at content indent" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'text <- "\n'
        '    #   Title ##\n'
        '    "\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_r_markdown_string_keeps_closing_delimiter_at_content_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_directives_inside_unsupported_strings_are_ignored_1(run, workdir):
    """CATCHES: reimplementations that break "embedded source directives inside unsupported strings are ignored" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'payload = b"""\n'
        '# fmt: markdown\n'
        'this    should     not trigger\n'
        '"""\n'
        'after = 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_directives_inside_unsupported_strings_are_ignored_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_source_directives_inside_unsupported_strings_are_ignored_2(run, workdir):
    """CATCHES: reimplementations that break "embedded source directives inside unsupported strings are ignored" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'payload <- r"tag(\n'
        '# fmt: markdown\n'
        'this    should     not trigger\n'
        ')tag"\n'
        'after <- 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_directives_inside_unsupported_strings_are_ignored_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.r').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.r'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_r_markdown_string_preserves_column_zero_closing_delimiter(run, workdir):
    """CATCHES: reimplementations that break "embedded r markdown string preserves column zero closing delimiter" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'text <- "\n'
        '    #   Title ##\n'
        '"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_r_markdown_string_preserves_column_zero_closing_delimiter.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_file_scope_markdown_patches_prior_marked_targets_only(run, workdir):
    """CATCHES: reimplementations that break "embedded source file scope markdown patches prior marked targets only" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '# This is __before__.\n'
        'DOC = """\n'
        'This is __not__ marked.\n'
        '"""\n'
        '# fmt: markdown canonical=true scope=file\n'
        'x = 1\n'
        '# fmt: markdown\n'
        '# This is __after__.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_file_scope_markdown_patches_prior_marked_targets_only.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_fmt_off_ignores_directives_until_on_1(run, workdir):
    """CATCHES: reimplementations that break "embedded source fmt off ignores directives until on" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: off\n'
        '# fmt: markdown\n'
        'x = 1\n'
        '# fmt: upper\n'
        '# fmt: on\n'
        '# fmt: markdown\n'
        '# #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_fmt_off_ignores_directives_until_on_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_fmt_off_ignores_directives_until_on_2(run, workdir):
    """CATCHES: reimplementations that break "embedded source fmt off ignores directives until on" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: off\n'
        '# fmt: markdown\n'
        'x <- 1\n'
        '# fmt: upper\n'
        '# fmt: on\n'
        '# fmt: markdown\n'
        '# #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_fmt_off_ignores_directives_until_on_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_markdown_directive_errors_on_unsupported_comment_target_1(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive errors on unsupported comment target" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: markdown\n'
        '# first paragraph line\n'
        '## unsupported mixed prefix\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:2:1: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_markdown_directive_errors_on_unsupported_comment_target_2(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive errors on unsupported comment target" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: markdown\n'
        '# first paragraph line\n'
        '## unsupported mixed prefix\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.R:2:1: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_markdown_directive_ignores_quote_delimiters_in_trailing_comments_1(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive ignores quote delimiters in trailing comments" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
        '# fmt: markdown\n'
        'x = 1 # """\n'
        '#   Title ##\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:4:4: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_markdown_directive_ignores_quote_delimiters_in_trailing_comments_2(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive ignores quote delimiters in trailing comments" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        '# fmt: markdown\n'
        'x <- 1 # "\n'
        '#   Title ##\n'
        '"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.R:4:2: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_markdown_directive_ignores_quote_delimiters_in_trailing_comments_3(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive ignores quote delimiters in trailing comments" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
        '# fmt: markdown\n'
        'x <- 1 # r"(\n'
        '#   Title ##\n'
        ')"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.R:4:3: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_markdown_directive_errors_when_code_precedes_target(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive errors when code precedes target" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'x = 1\n'
        '# #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:3:15: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_markdown_directive_targets_next_string_literal_after_code_1(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive targets next string literal after code" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: markdown\n'
        'value = render(\n'
        '    normalize(\n'
        '        prefix,\n'
        '        """A    python markdown paragraph.\n'
        '"""\n'
        '    )\n'
        ')\n'
        'x={"a":1,"b":2}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '120'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_markdown_directive_targets_next_string_literal_after_code_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_markdown_directive_targets_next_string_literal_after_code_2(run, workdir):
    """CATCHES: reimplementations that break "embedded source markdown directive targets next string literal after code" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: markdown\n'
        'value <- render(\n'
        '    normalize(\n'
        '        prefix,\n'
        '        "A    R markdown paragraph.\n'
        '"\n'
        '    )\n'
        ')\n'
        'x <- list(a=1,b=2)\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', '120'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_markdown_directive_targets_next_string_literal_after_code_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_source_pending_markdown_directive_without_target_errors(run, workdir):
    """CATCHES: reimplementations that break "embedded source pending markdown directive without target errors" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'x = 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:2:6: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_embedded_source_skip_file_short_circuits_later_invalid_fmt_comments_1(run, workdir):
    """CATCHES: reimplementations that break "embedded source skip file short circuits later invalid fmt comments" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: skip file\n'
        '# fmt: upper\n'
        '# #   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_skip_file_short_circuits_later_invalid_fmt_comments_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_source_skip_file_short_circuits_later_invalid_fmt_comments_2(run, workdir):
    """CATCHES: reimplementations that break "embedded source skip file short circuits later invalid fmt comments" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: skip file\n'
        '# fmt: upper\n'
        '# #   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r'], input=stdin)
    assert result.stdout == (RES / 'embedded_source_skip_file_short_circuits_later_invalid_fmt_comments_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.r').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.r'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_string_markdown_wrap_width_accounts_for_indent(run, workdir):
    """CATCHES: reimplementations that break "embedded string markdown wrap width accounts for indent" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '    one two three four\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '18'], input=stdin)
    assert result.stdout == (RES / 'embedded_string_markdown_wrap_width_accounts_for_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_string_markdown_wrap_width_uses_visual_indent_width(run, workdir):
    """CATCHES: reimplementations that break "embedded string markdown wrap width uses visual indent width" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '\u3000abc de f\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '9'], input=stdin)
    assert result.stdout == (RES / 'embedded_string_markdown_wrap_width_uses_visual_indent_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_template_delimiter_directive_isolated_defaults_to_from_here_1(run, workdir):
    """CATCHES: reimplementations that break "embedded template delimiter directive isolated defaults to from here" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: template.delimiters "<<" ">>"\n'
        '\n'
        '# fmt: markdown\n'
        'FIRST = """\n'
        '#   <<one>> ##\n'
        '"""\n'
        '\n'
        '# fmt: markdown\n'
        'SECOND = """\n'
        '#   <<two>> ##\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_template_delimiter_directive_isolated_defaults_to_from_here_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_template_delimiter_directive_isolated_defaults_to_from_here_2(run, workdir):
    """CATCHES: reimplementations that break "embedded template delimiter directive isolated defaults to from here" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: template.delimiters "<<" ">>"\n'
        '\n'
        '# fmt: markdown\n'
        'first <- "\n'
        '#   <<one>> ##\n'
        '"\n'
        '\n'
        '# fmt: markdown\n'
        'second <- "\n'
        '#   <<two>> ##\n'
        '"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'embedded_template_delimiter_directive_isolated_defaults_to_from_here_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.R').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.R'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_python_f_string_markdown_expressions_override_generic_template_preservation(run, workdir):
    """CATCHES: reimplementations that break "python f string markdown expressions override generic template preservation" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'text = f"""\n'
        'This    has { "{{ keep   }}" } and surrounding   text.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'python_f_string_markdown_expressions_override_generic_template_preservation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_f_string_markdown_targets_preserve_only_expressions(run, workdir):
    """CATCHES: reimplementations that break "python f string markdown targets preserve only expressions" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'text = f"""\n'
        'This    has { value   +  one } and some long surrounding prose that should wrap.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '42'], input=stdin)
    assert result.stdout == (RES / 'python_f_string_markdown_targets_preserve_only_expressions.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_markdown_string_targets_require_safe_supported_literals_1(run, workdir):
    """CATCHES: reimplementations that break "python markdown string targets require safe supported literals" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        '# fmt: markdown\n'
        'text = """inline"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:2:8: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_python_markdown_string_targets_require_safe_supported_literals_2(run, workdir):
    """CATCHES: reimplementations that break "python markdown string targets require safe supported literals" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        '# fmt: markdown\n'
        'text = """\n'
        'backslash \\\\ stays unsafe\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:3:1: error: non-raw Python Markdown strings must not contain backslashes\n'
    assert result.returncode == 1


def test_python_markdown_string_targets_require_safe_supported_literals_3(run, workdir):
    """CATCHES: reimplementations that break "python markdown string targets require safe supported literals" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        '# fmt: markdown\n'
        'text = rr"""\n'
        '#   Title ##\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:2:10: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_python_markdown_string_targets_require_safe_supported_literals_4(run, workdir):
    """CATCHES: reimplementations that break "python markdown string targets require safe supported literals" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '# fmt: markdown\n'
        'text = f"""\n'
        'This    has {value}.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == (RES / 'python_markdown_string_targets_require_safe_supported_literals_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_raw_string_can_be_embedded_markdown_target(run, workdir):
    """CATCHES: reimplementations that break "r raw string can be embedded markdown target" (source languages); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'text <- r"(\n'
        '#   Title ##\n'
        ')"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'r_raw_string_can_be_embedded_markdown_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_raw_string_markdown_targets_support_brackets_and_dash_delimiters_1(run, workdir):
    """CATCHES: reimplementations that break "r raw string markdown targets support brackets and dash delimiters" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
        '# fmt: markdown\n'
        'text <- r"[\n'
        '#   Title ##\n'
        ']"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'r_raw_string_markdown_targets_support_brackets_and_dash_delimiters_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_raw_string_markdown_targets_support_brackets_and_dash_delimiters_2(run, workdir):
    """CATCHES: reimplementations that break "r raw string markdown targets support brackets and dash delimiters" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        '# fmt: markdown\n'
        'text <- r"--{\n'
        '#   Title ##\n'
        '}--"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'r_raw_string_markdown_targets_support_brackets_and_dash_delimiters_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_raw_string_markdown_targets_support_brackets_and_dash_delimiters_3(run, workdir):
    """CATCHES: reimplementations that break "r raw string markdown targets support brackets and dash delimiters" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
        '# fmt: markdown\n'
        "text <- r'--|\n"
        '#   Title ##\n'
        "|--'\n"
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'r_raw_string_markdown_targets_support_brackets_and_dash_delimiters_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_standard_markdown_string_targets_reject_backslashes_1(run, workdir):
    """CATCHES: reimplementations that break "r standard markdown string targets reject backslashes" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: markdown\n'
        'text <- "\n'
        'line with hard break  \n'
        'next line\n'
        '"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.r:3:1: error: non-raw R Markdown strings must not contain backslashes\n'
    assert result.returncode == 1


def test_r_standard_markdown_string_targets_reject_backslashes_2(run, workdir):
    """CATCHES: reimplementations that break "r standard markdown string targets reject backslashes" (source languages); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: markdown\n'
        'text <- "\n'
        'backslash \\\\ stays unsafe\n'
        '"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.r:3:1: error: non-raw R Markdown strings must not contain backslashes\n'
    assert result.returncode == 1
