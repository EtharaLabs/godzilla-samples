"""Nested list continuation behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_ambiguous_list_continuations_are_preserved_across_wrap_modes_1(run, workdir):
    """CATCHES: reimplementations that break "ambiguous list continuations are preserved across wrap modes" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '-   First.\n'
        '  - Second.\n'
        ' After.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_list_continuations_are_preserved_across_wrap_modes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_list_continuations_are_preserved_across_wrap_modes_2(run, workdir):
    """CATCHES: reimplementations that break "ambiguous list continuations are preserved across wrap modes" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '-   First.\n'
        '  - Second.\n'
        ' After.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_list_continuations_are_preserved_across_wrap_modes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_list_continuations_are_preserved_across_wrap_modes_3(run, workdir):
    """CATCHES: reimplementations that break "ambiguous list continuations are preserved across wrap modes" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '-\n'
        '\n'
        ' First.\n'
        '\n'
        '-\n'
        '\n'
        ' - Second.\n'
        '\n'
        '  Continuation first. Continuation second.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_list_continuations_are_preserved_across_wrap_modes_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_list_continuations_are_preserved_across_wrap_modes_4(run, workdir):
    """CATCHES: reimplementations that break "ambiguous list continuations are preserved across wrap modes" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '-   Item.\n'
        '  ~~~text\n'
        '  code\n'
        '  ~~~\n'
        '\n'
        '-   Item.\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_list_continuations_are_preserved_across_wrap_modes_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_list_continuations_are_preserved_across_wrap_modes_5(run, workdir):
    """CATCHES: reimplementations that break "ambiguous list continuations are preserved across wrap modes" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '-   Item.\n'
        '  ~~~text\n'
        '  code\n'
        '  ~~~\n'
        '\n'
        '-   Item.\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_list_continuations_are_preserved_across_wrap_modes_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_list_continuations_are_preserved_across_wrap_modes_6(run, workdir):
    """CATCHES: reimplementations that break "ambiguous list continuations are preserved across wrap modes" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '  - One.\n'
        '- Two.\n'
        '\n'
        '  Title\n'
        '  ===\n'
        '\n'
        '  - One.\n'
        '- Two.\n'
        '\n'
        '  Title\n'
        '  ---\n'
        '\n'
        '  - One.\n'
        '- Two.\n'
        '\n'
        '  # Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_list_continuations_are_preserved_across_wrap_modes_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_boundaries_preserve_block_and_inline_contents_1(run, workdir):
    """CATCHES: reimplementations that break "list boundaries preserve block and inline contents" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '-   First.\n'
        '  - Second.\n'
        ' ~~~text\n'
        'alpha    beta\n'
        ' ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' ~~~text\n'
        'alpha    beta\n'
        ' ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' ```text\n'
        'alpha    beta\n'
        ' ```\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' <pre>\n'
        'alpha    beta\n'
        ' </pre>\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' <!--\n'
        'alpha    beta\n'
        ' -->\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' $$\n'
        'alpha    beta\n'
        ' $$\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_boundaries_preserve_block_and_inline_contents_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_boundaries_preserve_block_and_inline_contents_2(run, workdir):
    """CATCHES: reimplementations that break "list boundaries preserve block and inline contents" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '-   First.\n'
        '  - Second.\n'
        ' ~~~text\n'
        'alpha    beta\n'
        ' ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' ~~~text\n'
        'alpha    beta\n'
        ' ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' ```text\n'
        'alpha    beta\n'
        ' ```\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' <pre>\n'
        'alpha    beta\n'
        ' </pre>\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' <!--\n'
        'alpha    beta\n'
        ' -->\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' $$\n'
        'alpha    beta\n'
        ' $$\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'list_boundaries_preserve_block_and_inline_contents_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_boundaries_preserve_block_and_inline_contents_3(run, workdir):
    """CATCHES: reimplementations that break "list boundaries preserve block and inline contents" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '-   First.\r\n'
        '  - Second.\r\n'
        ' ~~~text\r\n'
        'alpha    beta\r\n'
        ' ~~~\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' ~~~text\r\n'
        'alpha    beta\r\n'
        ' ~~~\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' ```text\r\n'
        'alpha    beta\r\n'
        ' ```\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' <pre>\r\n'
        'alpha    beta\r\n'
        ' </pre>\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' <!--\r\n'
        'alpha    beta\r\n'
        ' -->\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' $$\r\n'
        'alpha    beta\r\n'
        ' $$\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'list_boundaries_preserve_block_and_inline_contents_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_boundaries_preserve_block_and_inline_contents_4(run, workdir):
    """CATCHES: reimplementations that break "list boundaries preserve block and inline contents" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '-   First.\r'
        '  - Second.\r'
        ' ~~~text\r'
        'alpha    beta\r'
        ' ~~~\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' ~~~text\r'
        'alpha    beta\r'
        ' ~~~\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' ```text\r'
        'alpha    beta\r'
        ' ```\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' <pre>\r'
        'alpha    beta\r'
        ' </pre>\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' <!--\r'
        'alpha    beta\r'
        ' -->\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' $$\r'
        'alpha    beta\r'
        ' $$\r'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_boundaries_preserve_block_and_inline_contents_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_boundaries_preserve_block_and_inline_contents_5(run, workdir):
    """CATCHES: reimplementations that break "list boundaries preserve block and inline contents" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '-   First.\r'
        '  - Second.\r'
        ' ~~~text\r'
        'alpha    beta\r'
        ' ~~~\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' ~~~text\r'
        'alpha    beta\r'
        ' ~~~\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' ```text\r'
        'alpha    beta\r'
        ' ```\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' <pre>\r'
        'alpha    beta\r'
        ' </pre>\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' <!--\r'
        'alpha    beta\r'
        ' -->\r'
        '\r'
        ' - First.\r'
        '- Second.\r'
        ' $$\r'
        'alpha    beta\r'
        ' $$\r'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'list_boundaries_preserve_block_and_inline_contents_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_boundaries_preserve_block_and_inline_contents_6(run, workdir):
    """CATCHES: reimplementations that break "list boundaries preserve block and inline contents" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        ' - First.\r\n'
        '- Second.\r\n'
        ' Heading\r\n'
        ' ===\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' Heading\r\n'
        ' ---\r\n'
        '\r\n'
        '-    First.\r\n'
        '    Prose.\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        ' After.\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        '  ~~~text\r\n'
        '  alpha    beta\r\n'
        '  ~~~\r\n'
        '\r\n'
        ' - First.\r\n'
        '- Second.\r\n'
        '  <pre>\r\n'
        '  alpha    beta\r\n'
        '  </pre>\r\n'
        '\r\n'
        ' - First.\r\n'
        '- `Second.\r\n'
        ' ~~~text\r\n'
        ' alpha    beta\r\n'
        ' end`\r\n'
        '\r\n'
        ' - First.\r\n'
        '- `Second.\r\n'
        ' <pre>\r\n'
        ' alpha    beta\r\n'
        ' end`\r\n'
        '\r\n'
        ' - First.\r\n'
        '- [Second](\r\n'
        ' <pre>\r\n'
        ' )\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_boundaries_preserve_block_and_inline_contents_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_mixed_list_regions_leave_outside_prose_formattable_1(run, workdir):
    """CATCHES: reimplementations that break "mixed list regions leave outside prose formattable" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '- Item.\n'
        ' ~~~text\n'
        ' `\n'
        ' ~~~\n'
        '- `First.    Second.\n'
        ' <pre>\n'
        ' alpha    beta\n'
        ' end`\n'
        '\n'
        'Outside first. Outside second.\n'
        '\n'
        '- Item.\n'
        ' ~~~text\n'
        ' alpha    beta\n'
        ' ~~~\n'
        '- Next.\n'
        ' <pre>\n'
        ' gamma    delta\n'
        ' </pre>\n'
        'Outside third. Outside fourth.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'mixed_list_regions_leave_outside_prose_formattable_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_mixed_list_regions_leave_outside_prose_formattable_2(run, workdir):
    """CATCHES: reimplementations that break "mixed list regions leave outside prose formattable" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '- Item.\n'
        ' ~~~text\n'
        ' `\n'
        ' ~~~\n'
        '- `First.    Second.\n'
        ' <pre>\n'
        ' alpha    beta\n'
        ' end`\n'
        '\n'
        'Outside first.\n'
        'Outside second.\n'
        '\n'
        '- Item.\n'
        ' ~~~text\n'
        ' alpha    beta\n'
        ' ~~~\n'
        '- Next.\n'
        ' <pre>\n'
        ' gamma    delta\n'
        ' </pre>\n'
        'Outside third.\n'
        'Outside fourth.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'mixed_list_regions_leave_outside_prose_formattable_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_mixed_list_regions_leave_outside_prose_formattable_3(run, workdir):
    """CATCHES: reimplementations that break "mixed list regions leave outside prose formattable" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '- Item.\r\n'
        ' ~~~text\r\n'
        ' `\r\n'
        ' ~~~\r\n'
        '- `First.    Second.\r\n'
        ' <pre>\r\n'
        ' alpha    beta\r\n'
        ' end`\r\n'
        '\r\n'
        'Outside first. Outside second.\r\n'
        '\r\n'
        '- Item.\r\n'
        ' ~~~text\r\n'
        ' alpha    beta\r\n'
        ' ~~~\r\n'
        '- Next.\r\n'
        ' <pre>\r\n'
        ' gamma    delta\r\n'
        ' </pre>\r\n'
        'Outside third. Outside fourth.\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'mixed_list_regions_leave_outside_prose_formattable_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_mixed_list_regions_leave_outside_prose_formattable_4(run, workdir):
    """CATCHES: reimplementations that break "mixed list regions leave outside prose formattable" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '- Item.\r\n'
        ' ~~~text\r\n'
        ' `\r\n'
        ' ~~~\r\n'
        '- `First.    Second.\r\n'
        ' <pre>\r\n'
        ' alpha    beta\r\n'
        ' end`\r\n'
        '\r\n'
        'Outside first.\r\n'
        'Outside second.\r\n'
        '\r\n'
        '- Item.\r\n'
        ' ~~~text\r\n'
        ' alpha    beta\r\n'
        ' ~~~\r\n'
        '- Next.\r\n'
        ' <pre>\r\n'
        ' gamma    delta\r\n'
        ' </pre>\r\n'
        'Outside third.\r\n'
        'Outside fourth.\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'mixed_list_regions_leave_outside_prose_formattable_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_mixed_list_regions_leave_outside_prose_formattable_5(run, workdir):
    """CATCHES: reimplementations that break "mixed list regions leave outside prose formattable" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '- Item.\r'
        ' ~~~text\r'
        ' `\r'
        ' ~~~\r'
        '- `First.    Second.\r'
        ' <pre>\r'
        ' alpha    beta\r'
        ' end`\r'
        '\r'
        'Outside first. Outside second.\r'
        '\r'
        '- Item.\r'
        ' ~~~text\r'
        ' alpha    beta\r'
        ' ~~~\r'
        '- Next.\r'
        ' <pre>\r'
        ' gamma    delta\r'
        ' </pre>\r'
        'Outside third. Outside fourth.\r'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'mixed_list_regions_leave_outside_prose_formattable_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_mixed_list_regions_leave_outside_prose_formattable_6(run, workdir):
    """CATCHES: reimplementations that break "mixed list regions leave outside prose formattable" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '- Item.\r'
        ' ~~~text\r'
        ' `\r'
        ' ~~~\r'
        '- `First.    Second.\r'
        ' <pre>\r'
        ' alpha    beta\r'
        ' end`\r'
        '\r'
        'Outside first.\r'
        'Outside second.\r'
        '\r'
        '- Item.\r'
        ' ~~~text\r'
        ' alpha    beta\r'
        ' ~~~\r'
        '- Next.\r'
        ' <pre>\r'
        ' gamma    delta\r'
        ' </pre>\r'
        'Outside third.\r'
        'Outside fourth.\r'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'mixed_list_regions_leave_outside_prose_formattable_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_outer_list_continuations_keep_line_endings_and_are_idempotent_1(run, workdir):
    """CATCHES: reimplementations that break "outer list continuations keep line endings and are idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '- Item with a nested list:\n'
        '  - nested one\n'
        '  - nested two\n'
        '\n'
        '  Paragraph that continues the outer item.\n'
        '- Next item.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'outer_list_continuations_keep_line_endings_and_are_idempotent_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_outer_list_continuations_keep_line_endings_and_are_idempotent_2(run, workdir):
    """CATCHES: reimplementations that break "outer list continuations keep line endings and are idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '- Item with a nested list:\n'
        '  - nested one\n'
        '  - nested two\n'
        '\n'
        '  Paragraph that continues the outer item.\n'
        '- Next item.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'outer_list_continuations_keep_line_endings_and_are_idempotent_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:32', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_outer_list_continuations_keep_line_endings_and_are_idempotent_3(run, workdir):
    """CATCHES: reimplementations that break "outer list continuations keep line endings and are idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '- Item with a nested list:\r\n'
        '  - nested one\r\n'
        '  - nested two\r\n'
        '\r\n'
        '  Paragraph that continues the outer item.\r\n'
        '- Next item.\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'outer_list_continuations_keep_line_endings_and_are_idempotent_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_outer_list_continuations_keep_line_endings_and_are_idempotent_4(run, workdir):
    """CATCHES: reimplementations that break "outer list continuations keep line endings and are idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '- Item with a nested list:\r\n'
        '  - nested one\r\n'
        '  - nested two\r\n'
        '\r\n'
        '  Paragraph that continues the outer item.\r\n'
        '- Next item.\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (RES / 'outer_list_continuations_keep_line_endings_and_are_idempotent_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:32', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_outer_list_continuations_keep_line_endings_and_are_idempotent_5(run, workdir):
    """CATCHES: reimplementations that break "outer list continuations keep line endings and are idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '- Item with a nested list:\r'
        '  - nested one\r'
        '  - nested two\r'
        '\r'
        '  Paragraph that continues the outer item.\r'
        '- Next item.\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (
        b'- Item with a nested list:\r'
        b'  - nested one\r'
        b'  - nested two\r'
        b'\r'
        b'  Paragraph that continues the outer item.\r'
        b'- Next item.\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_outer_list_continuations_keep_line_endings_and_are_idempotent_6(run, workdir):
    """CATCHES: reimplementations that break "outer list continuations keep line endings and are idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '- Item with a nested list:\r'
        '  - nested one\r'
        '  - nested two\r'
        '\r'
        '  Paragraph that continues the outer item.\r'
        '- Next item.\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:32'], input=stdin)
    assert result.stdout == (
        b'- Item with a nested list:\r'
        b'  - nested one\r'
        b'  - nested two\r'
        b'\r'
        b'  Paragraph that continues the outer item.\r'
        b'- Next item.\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:32', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_nested_list_boundary_transcript_is_idempotent(run, workdir):
    """CATCHES: reimplementations that break "nested list boundary transcript is idempotent" (nested list continuation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- Parent.\n'
        '\n'
        '  - Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '- Next.\n'
        '\n'
        '- Parent.\n'
        '  - Child one.\n'
        '\n'
        '  - Child two.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '- Next.\n'
        '\n'
        '- Parent.\n'
        '  - Child.\n'
        '    - Grandchild.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '\n'
        'Outside first.\n'
        'Outside second.\n'
        '\n'
        '- Parent.\n'
        '  - [ ] Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '\n'
        '- [ ] Parent.\n'
        '  - [ ] Child.\n'
        '\n'
        '      Outer first. Outer second.\n'
        '\n'
        '  - Indented first.\n'
        '- Parent.\n'
        '  - Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '\n'
        '- First.\n'
        ' - Second.\n'
        '\n'
        'Outside first.\n'
        'Outside second.\n'
        '\n'
        '-\n'
        ' - Second.\n'
        '\n'
        '  Outside first. Outside second.\n'
        '\n'
        '- First.\n'
        '  - Child.\n'
        '10. Second.\n'
        '\n'
        'Outside first.\n'
        'Outside second.\n'
        '\n'
        '10. First.\n'
        '- Second.\n'
        '  - Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'nested_list_boundary_transcript_is_idempotent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
