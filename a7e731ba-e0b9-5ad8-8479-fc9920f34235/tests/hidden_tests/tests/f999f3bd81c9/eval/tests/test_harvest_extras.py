"""Additional harvested invocations reaching rarely used code paths.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_explicit_preservation_keeps_line_endings_and_eof_bytes(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '::: {.outer}\r'
        '```markdown\r'
        'Before   child. \r'
        '\r'
        '<!-- fmt: skip -->\r'
        'Keep   é prose.  \t\r'
        '\r'
        'After   child. \r'
        '```\r'
        ':::\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (
        b'::: {.outer}\r'
        b'```markdown\r'
        b'Before child.\r'
        b'\r'
        b'<!-- fmt: skip -->\r'
        b'Keep   \xc3\xa9 prose.  \t\r'
        b'\r'
        b'After child.\r'
        b'```\r'
        b':::\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_directive_errors_are_reported(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '<!-- fmt: canonical=true scope=next -->\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:40: error: fmt: markdown has no target\n'
    assert result.returncode == 1


def test_unsupported_expressions_and_contexts_keep_baseline_preservation(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Before\n'
        'with \\{{ foo }} after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_2(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Before\n'
        'with ~~{{ foo }}~~ after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Before\n'
        '\\`{{ foo }}\\` after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
