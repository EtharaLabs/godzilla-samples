"""Shortcodes behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_shortcode_bytes_survive_line_endings_eof_and_nested_documents_1(run, workdir):
    """CATCHES: reimplementations that break "shortcode bytes survive line endings eof and nested documents" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = '{{< call   arg="é >}} \\" still quoted"  >}}'
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'{{< call   arg="\xc3\xa9 >}} \\" still quoted"  >}}'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_bytes_survive_line_endings_eof_and_nested_documents_2(run, workdir):
    """CATCHES: reimplementations that break "shortcode bytes survive line endings eof and nested documents" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '::: {.outer}\n'
        '```markdown\n'
        '{{< missing\n'
        'Keep   this.  \t\n'
        '\n'
        '<!-- fmt: on -->\n'
        'Still   opaque.  \n'
        '```\n'
        ':::\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'paragraph'],
        input=stdin,
    )
    assert result.stdout == (RES / 'shortcode_bytes_survive_line_endings_eof_and_nested_documents_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_bytes_survive_line_endings_eof_and_nested_documents_3(run, workdir):
    """CATCHES: reimplementations that break "shortcode bytes survive line endings eof and nested documents" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '```markdown\n'
        '{{% call\n'
        "arg='\\' %}} still   quoted'  \t\n"
        'raw=`\\`\n'
        '%}}\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'shortcode_bytes_survive_line_endings_eof_and_nested_documents_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', '20', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_bytes_survive_line_endings_eof_and_nested_documents_4(run, workdir):
    """CATCHES: reimplementations that break "shortcode bytes survive line endings eof and nested documents" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '\ufeff{{< missing\r\n'
        'Keep   this.  \t\r\n'
        '\r\n'
        '<!-- fmt: on -->\r\n'
        'Still   opaque.  '
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'paragraph'],
        input=stdin,
    )
    assert result.stdout == (RES / 'shortcode_bytes_survive_line_endings_eof_and_nested_documents_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_bytes_survive_line_endings_eof_and_nested_documents_5(run, workdir):
    """CATCHES: reimplementations that break "shortcode bytes survive line endings eof and nested documents" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '::: {.outer}\r\n'
        '```markdown\r\n'
        '{{< missing\r\n'
        'Keep   this.  \t\r\n'
        '\r\n'
        '<!-- fmt: on -->\r\n'
        'Still   opaque.  \r\n'
        '```\r\n'
        ':::\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'shortcode_bytes_survive_line_endings_eof_and_nested_documents_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', '20', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_bytes_survive_line_endings_eof_and_nested_documents_6(run, workdir):
    """CATCHES: reimplementations that break "shortcode bytes survive line endings eof and nested documents" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '\ufeff{{% call arg="unterminated\r'
        '%}}\r'
        '<!-- fmt: skip file -->\r'
        'Keep   this.  \r'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'paragraph'],
        input=stdin,
    )
    assert result.stdout == (
        b'\xef\xbb\xbf{{% call arg="unterminated\r'
        b'%}}\r'
        b'<!-- fmt: skip file -->\r'
        b'Keep   this.  \r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_transcript_outputs_are_idempotent_1(run, workdir):
    """CATCHES: reimplementations that break "shortcode transcript outputs are idempotent" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '{{< notice >}}\n'
        '\n'
        'First sentence.\n'
        'Second sentence.\n'
        '\n'
        '{{< /notice >}}\n'
        '\n'
        '{{% outer %}}\n'
        '{{< raw >}}\n'
        'Format this body.\n'
        '{{% verbatim %}}\n'
        'Nested ordinary Markdown.\n'
        '{{< /raw >}}\n'
        '{{% /different %}}\n'
        '{{% /verbatim %}}\n'
        '{{% /outer %}}\n'
        '\n'
        '{{< something.inline />}}\n'
        'After the self-closing call.\n'
        '{{% single /%}}\n'
        '{{< /orphan >}}\n'
        '{{% /orphan %}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'shortcode_transcript_outputs_are_idempotent_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_transcript_outputs_are_idempotent_2(run, workdir):
    """CATCHES: reimplementations that break "shortcode transcript outputs are idempotent" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '::: {.note}\n'
        '{{< call   \n'
        'message="keep   spacing"   \n'
        '>}}\n'
        'Keep   this body.\n'
        ':::\n'
        '\n'
        '<!-- fmt: skip -->\n'
        '{{< skipped   token >}}\n'
        'Format after the token.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '{{% notice message="\n'
        '<!-- fmt: on -->\n'
        '%}} still quoted" %}} Keep this body.\n'
        '{{% /notice %}}\n'
        '<!-- fmt: on -->\n'
        'Format this paragraph.\n'
        '\n'
        '{{< data message="\n'
        '<!-- fmt: skip file -->\n'
        '<!-- fmt: invalid -->\n'
        '" >}}\n'
        '<!-- fmt: skip -->\n'
        'Keep   this\n'
        'paragraph.\n'
        '\n'
        'Format this one.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '{{< whole >}}\n'
        'Keep   the whole\n'
        'body.\n'
        '{{< /whole >}}\n'
        '<!-- fmt: on -->\n'
        'Resume formatting.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'shortcode_transcript_outputs_are_idempotent_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_transcript_outputs_are_idempotent_3(run, workdir):
    """CATCHES: reimplementations that break "shortcode transcript outputs are idempotent" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '<!-- fmt: off -->\n'
        '<div>\n'
        '{{< unfinished\n'
        '</div>\n'
        '<!-- fmt: on -->\n'
        'Format after disabled HTML.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '$$\n'
        '{{% unfinished\n'
        '$$\n'
        '<!-- fmt: on -->\n'
        'Format after disabled display math.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'shortcode_transcript_outputs_are_idempotent_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_transcript_outputs_are_idempotent_4(run, workdir):
    """CATCHES: reimplementations that break "shortcode transcript outputs are idempotent" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '\ufeff   {{% notice   \n'
        'message="quoted %}} keeps   spacing"  \t\n'
        '%}}\n'
        'Format this paragraph as Markdown.\n'
        'Second sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'shortcode_transcript_outputs_are_idempotent_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_transcript_outputs_are_idempotent_5(run, workdir):
    """CATCHES: reimplementations that break "shortcode transcript outputs are idempotent" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before the token.\n'
        '\n'
        '{{< missing\n'
        'No   delimiter here.\n'
        '\n'
        '<!-- fmt: on -->\n'
        'Keep   everything\n'
        'through the end.   \n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'shortcode_transcript_outputs_are_idempotent_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_shortcode_transcript_outputs_are_idempotent_6(run, workdir):
    """CATCHES: reimplementations that break "shortcode transcript outputs are idempotent" (shortcodes); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Ordinary prose with `{{< inline >}}` and {{ value }}.\n'
        '\n'
        'Before {{< inline >}} after.\n'
        '\n'
        '{{< single >}} Mixed   token/prose stays.\n'
        'Following prose formats.\n'
        '\n'
        '- {{< list >}} Keep list continuation.\n'
        '\n'
        '> {{% quote %}}\n'
        '> Keep   quote continuation.\n'
        '\n'
        '<div>\n'
        'Keep   this HTML body.\n'
        '</div>\n'
        '\n'
        '<img\n'
        'alt="Keep   this HTML argument"\n'
        'src="image.png">\n'
        '\n'
        '```text\n'
        '{{< fenced >}}\n'
        'Keep   this code.\n'
        '```\n'
        '\n'
        'After everything.\n'
        '\n'
        '## {{< title >}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'shortcode_transcript_outputs_are_idempotent_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
