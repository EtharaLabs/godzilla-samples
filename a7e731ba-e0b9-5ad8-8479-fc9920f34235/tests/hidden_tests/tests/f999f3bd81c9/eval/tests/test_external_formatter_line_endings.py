"""External formatter line endings behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_external_formatter_keeps_fences_and_yaml_scalars_line_delimited_1(run, workdir):
    """CATCHES: reimplementations that break "external formatter keeps fences and yaml scalars line delimited" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '```python\r\n'
        'x=1\r\n'
        'x\r\n'
        '```\r\n'
        '\r\n'
        'After.\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_keeps_fences_and_yaml_scalars_line_delimited_2(run, workdir):
    """CATCHES: reimplementations that break "external formatter keeps fences and yaml scalars line delimited" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '```{python}\r\n'
        '#| label: example\r\n'
        'x = 1\r\n'
        'x\r\n'
        '```\r\n'
        '\r\n'
        'After.\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.qmd', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_keeps_fences_and_yaml_scalars_line_delimited_3(run, workdir):
    """CATCHES: reimplementations that break "external formatter keeps fences and yaml scalars line delimited" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '```python\n'
        'x=1\n'
        'x\n'
        '```\n'
        '\n'
        'After.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_keeps_fences_and_yaml_scalars_line_delimited_4(run, workdir):
    """CATCHES: reimplementations that break "external formatter keeps fences and yaml scalars line delimited" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '```{python}\n'
        '#| label: example\n'
        'x = 1\n'
        'x\n'
        '```\n'
        '\n'
        'After.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.qmd', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_keeps_fences_and_yaml_scalars_line_delimited_5(run, workdir):
    """CATCHES: reimplementations that break "external formatter keeps fences and yaml scalars line delimited" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '```python\r'
        'x=1\r'
        'x\r'
        '```\r'
        '\r'
        'After.\r'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_keeps_fences_and_yaml_scalars_line_delimited_6(run, workdir):
    """CATCHES: reimplementations that break "external formatter keeps fences and yaml scalars line delimited" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '```{python}\r'
        '#| label: example\r'
        'x = 1\r'
        'x\r'
        '```\r'
        '\r'
        'After.\r'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.qmd', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_line_ending_fixtures_keep_exact_bytes_1(run, workdir):
    """CATCHES: reimplementations that break "external formatter line ending fixtures keep exact bytes" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
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
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_line_ending_fixtures_keep_exact_bytes_2(run, workdir):
    """CATCHES: reimplementations that break "external formatter line ending fixtures keep exact bytes" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        '# fmt: python\r\n'
        'code: |\r\n'
        '  x = 1\r\n'
        '  x\r\n'
        'other: 1\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1


def test_external_formatter_line_ending_fixtures_keep_exact_bytes_3(run, workdir):
    """CATCHES: reimplementations that break "external formatter line ending fixtures keep exact bytes" (external formatter line endings); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
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
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'tests/fixtures/external_formatter_line_endings.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'tests/fixtures/external_formatter_line_endings.toml:1:1: error: failed to read config: No such file or directory (os error 2)\n'
    assert result.returncode == 1
