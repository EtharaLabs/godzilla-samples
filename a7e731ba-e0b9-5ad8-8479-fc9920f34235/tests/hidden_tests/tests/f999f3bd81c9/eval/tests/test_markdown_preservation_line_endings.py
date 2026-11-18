"""Markdown preservation line endings behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_explicit_preservation_keeps_line_endings_and_eof_bytes_1(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '<!-- fmt: skip -->\n'
        'Keep   é prose.  \t'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_keeps_line_endings_and_eof_bytes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_keeps_line_endings_and_eof_bytes_2(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '<!-- fmt: skip file -->\n'
        'Keep   é prose.  \t'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_keeps_line_endings_and_eof_bytes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_keeps_line_endings_and_eof_bytes_3(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '<!-- fmt: skip -->\r\n'
        'Keep   é prose.  \t'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_keeps_line_endings_and_eof_bytes_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_keeps_line_endings_and_eof_bytes_4(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '<!-- fmt: skip file -->\r\n'
        'Keep   é prose.  \t\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_keeps_line_endings_and_eof_bytes_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_keeps_line_endings_and_eof_bytes_5(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '<!-- fmt: skip -->\r'
        'Keep   é prose.  \t\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (
        b'<!-- fmt: skip -->\r'
        b'Keep   \xc3\xa9 prose.  \t\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_keeps_line_endings_and_eof_bytes_6(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation keeps line endings and eof bytes" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: skip file -->\r'
        'Keep   é prose.  \t\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (
        b'<!-- fmt: skip file -->\r'
        b'Keep   \xc3\xa9 prose.  \t\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_preserved_transcripts_are_idempotent_1(run, workdir):
    """CATCHES: reimplementations that break "preserved transcripts are idempotent" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        '<!-- fmt: skip -->  \n'
        'Keep   é prose.  \t\n'
        'And   this line.   \n'
        '\n'
        'Format outside.\n'
        'Second sentence.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        '- Keep   list.  \t\n'
        '  continuation   unchanged.  \n'
        '- Another   item.   \n'
        '\n'
        '<!-- fmt: skip -->\n'
        '> Keep   quote.  \n'
        '> Next   line. \t\n'
        '\n'
        '<!-- fmt: skip -->\n'
        '::: {.note}  \n'
        'Keep   prose.  \n'
        '\n'
        '```text\n'
        'code   with spaces  \n'
        '```\n'
        '\n'
        '$$\n'
        'x + y  \n'
        '$$\n'
        '\n'
        '<div>\n'
        'HTML   with spaces  \n'
        '</div>\n'
        '\n'
        '[malformed](   \n'
        ':::  \n'
        '\n'
        '<!-- fmt: skip -->\n'
        '```markdown  \n'
        'Keep   fence prose.  \n'
        '````  \n'
        '\n'
        'Format after containers.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_transcripts_are_idempotent_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_preserved_transcripts_are_idempotent_2(run, workdir):
    """CATCHES: reimplementations that break "preserved transcripts are idempotent" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        '::: {.outer}\n'
        'Before child.\n'
        '\n'
        '```markdown\n'
        '<!-- fmt: skip file -->\n'
        'Keep   child prose.  \t\n'
        '`unclosed   code  \n'
        '<div malformed  \n'
        '```\n'
        '\n'
        'After child.\n'
        ':::\n'
        '\n'
        '````markdown\n'
        'Before div.\n'
        '\n'
        '::: {.inner}\n'
        '<!-- fmt: skip file -->\n'
        'Keep   child without shortcodes.  \n'
        '$$ unclosed   math  \t\n'
        ':::\n'
        '\n'
        'After div.\n'
        '````\n'
        '\n'
        '::: {.outer}\n'
        '```markdown\n'
        'Before skipped node.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        'Keep   nested paragraph.  \t\n'
        '\n'
        'After skipped node.\n'
        '```\n'
        ':::\n'
        '\n'
        'Format outside.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_transcripts_are_idempotent_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_preserved_transcripts_are_idempotent_3(run, workdir):
    """CATCHES: reimplementations that break "preserved transcripts are idempotent" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        'Format before.\n'
        '\n'
        '<!-- fmt: off -->  \n'
        'Keep   prose.  \t\n'
        '\n'
        '{{< unclosed arg="  \n'
        '```markdown  \n'
        '<div>  \n'
        '$$  \n'
        '<!-- fmt: on -->  \n'
        'Format after.\n'
        'Second sentence.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '[malformed](  \t\n'
        '    code   at EOF.  \t\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_transcripts_are_idempotent_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_preserved_transcripts_are_idempotent_4(run, workdir):
    """CATCHES: reimplementations that break "preserved transcripts are idempotent" (markdown preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '    code   still copied\n'
        '\n'
        '<div>\n'
        'HTML   still copied\n'
        '</div>\n'
        '\n'
        'Before {{ value }} prose.\n'
        '\n'
        'Before <widget> unsupported prose.\n'
        '\n'
        '```text\n'
        'code   still copied\n'
        '```\n'
        '\n'
        '::: {.note}\n'
        'Before {{ value }} nested prose.\n'
        '\n'
        '    nested   code\n'
        ':::\n'
        '\n'
        'Before   `{{\n'
        '  render(customer.address)\n'
        '}}` after template.\n'
        '\n'
        '> {{% quote %}}\n'
        '> Keep   unsupported continuation.\n'
        '\n'
        'Format ordinary prose.\n'
        'Second sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'preserved_transcripts_are_idempotent_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
