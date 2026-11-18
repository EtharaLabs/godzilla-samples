"""External formatters transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_cr(run, workdir):
    """CATCHES: implementations that differ from the reference in configured embedded-formatter dispatch for cr; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/external_formatter_line_endings.toml': (
            '[embedded.python]\n'
            "# Mimic Ruff's notebook output: remove only the final LF, leaving any CR.\n"
            '# Use binary streams so Python does not translate newlines on Windows.\n'
            'formatter = { command = ["python3", "-c", \'import sys; source = sys.stdin.buffer.read(); sys.stdout.buffer.write(source.replace(b"x=1", b"x = 1").removesuffix(b"\\n"))\', "{path}"], path_suffix = ".py" }\n'
        ),
        'tests/fixtures/external_formatter_cr.md': (
            '```python\r'
            'x = 1\r'
            'x\r'
            '```\r'
            '\r'
            '```{python}\r'
            'x = 1\r'
            'x\r'
            '```\r'
            '\r'
            'After.\r'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--check', '--config', 'tests/fixtures/external_formatter_line_endings.toml', 'tests/fixtures/external_formatter_cr.md'],
    )
    assert result.stdout == b""
    assert result.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_crlf_markdown(run, workdir):
    """CATCHES: implementations that differ from the reference in configured embedded-formatter dispatch for crlf markdown; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/external_formatter_line_endings.toml': (
            '[embedded.python]\n'
            "# Mimic Ruff's notebook output: remove only the final LF, leaving any CR.\n"
            '# Use binary streams so Python does not translate newlines on Windows.\n'
            'formatter = { command = ["python3", "-c", \'import sys; source = sys.stdin.buffer.read(); sys.stdout.buffer.write(source.replace(b"x=1", b"x = 1").removesuffix(b"\\n"))\', "{path}"], path_suffix = ".py" }\n'
        ),
        'tests/fixtures/external_formatter_crlf.md': (
            '```python\r\n'
            'x = 1\r\n'
            'x\r\n'
            '```\r\n'
            '\r\n'
            '```{python}\r\n'
            'x = 1\r\n'
            'x\r\n'
            '```\r\n'
            '\r\n'
            'After.\r\n'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--check', '--config', 'tests/fixtures/external_formatter_line_endings.toml', 'tests/fixtures/external_formatter_crlf.md'],
    )
    assert result.stdout == b""
    assert result.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_crlf_yaml(run, workdir):
    """CATCHES: implementations that differ from the reference in configured embedded-formatter dispatch for crlf yaml; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/external_formatter_line_endings.toml': (
            '[embedded.python]\n'
            "# Mimic Ruff's notebook output: remove only the final LF, leaving any CR.\n"
            '# Use binary streams so Python does not translate newlines on Windows.\n'
            'formatter = { command = ["python3", "-c", \'import sys; source = sys.stdin.buffer.read(); sys.stdout.buffer.write(source.replace(b"x=1", b"x = 1").removesuffix(b"\\n"))\', "{path}"], path_suffix = ".py" }\n'
        ),
        'tests/fixtures/external_formatter_crlf.yaml': (
            '# fmt: python\r\n'
            'code: |\r\n'
            '  x = 1\r\n'
            '  x\r\n'
            'other: 1\r\n'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--check', '--config', 'tests/fixtures/external_formatter_line_endings.toml', 'tests/fixtures/external_formatter_crlf.yaml'],
    )
    assert result.stdout == b""
    assert result.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_early_stdin_close(run, workdir):
    """CATCHES: implementations that differ from the reference in configured embedded-formatter dispatch for early stdin close; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/external_formatter_early_close.toml': (
            '[embedded.early]\n'
            'formatter = { command = ["python3", "-c", \'import os, sys; os.close(sys.stdin.fileno()); sys.stdout.buffer.write(b"formatted\\n")\', "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```early\n'
        'abc\n'
        '```\n'
        '\n'
        'After.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_early_close.toml'],
        input=stdin,
    )
    assert result.stdout == (RES / 'early_stdin_close.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_lf(run, workdir):
    """CATCHES: implementations that differ from the reference in configured embedded-formatter dispatch for lf; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/external_formatter_line_endings.toml': (
            '[embedded.python]\n'
            "# Mimic Ruff's notebook output: remove only the final LF, leaving any CR.\n"
            '# Use binary streams so Python does not translate newlines on Windows.\n'
            'formatter = { command = ["python3", "-c", \'import sys; source = sys.stdin.buffer.read(); sys.stdout.buffer.write(source.replace(b"x=1", b"x = 1").removesuffix(b"\\n"))\', "{path}"], path_suffix = ".py" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```python\n'
        'x=1\n'
        'x\n'
        '```\n'
        '\n'
        '```{python}\n'
        'x=1\n'
        'x\n'
        '```\n'
        '\n'
        '```yaml\n'
        '# fmt: python\n'
        'code: |\n'
        '  x=1\n'
        '  x\n'
        'other: 1\n'
        '```\n'
        '\n'
        'After.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == (RES / 'lf.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
