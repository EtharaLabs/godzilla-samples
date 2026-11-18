"""Config and diff transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_config_relative_ancestor(run, workdir):
    """CATCHES: implementations that differ from the reference in config discovery and diff presentation for config relative ancestor; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'nested/input.md': "",
    }
    write_tree(workdir, files)
    stdin = 'First sentence. Second sentence.\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin, cwd=workdir / 'nested')
    assert result.stdout == (RES / 'config_relative_ancestor.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_config_relative_explicit(run, workdir):
    """CATCHES: implementations that differ from the reference in config discovery and diff presentation for config relative explicit; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'nested/explicit.toml': (
            '[format]\n'
            'wrap = "none"\n'
        ),
    }
    write_tree(workdir, files)
    stdin = 'First sentence. Second sentence.\n'
    result = run(
        ['format', '--stdin-file-path', 'nonexistent.md', '--config', 'explicit.toml'],
        input=stdin,
        cwd=workdir / 'nested',
    )
    assert result.stdout == b'First sentence. Second sentence.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'nested' / 'nonexistent.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(
        ['format', '--check', '--config', 'explicit.toml', 'nonexistent.md'],
        cwd=workdir / 'nested',
    )
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_config_relative_nearest(run, workdir):
    """CATCHES: implementations that differ from the reference in config discovery and diff presentation for config relative nearest; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'nested/yamark.toml': (
            '[format]\n'
            'wrap = "none"\n'
        ),
    }
    write_tree(workdir, files)
    stdin = 'First sentence. Second sentence.\n'
    result = run(['format', '--stdin-file-path', 'nonexistent.md'], input=stdin, cwd=workdir / 'nested')
    assert result.stdout == b'First sentence. Second sentence.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'nested' / 'nonexistent.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'nonexistent.md'], cwd=workdir / 'nested')
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_diff_overlapping_context(run, workdir):
    """CATCHES: implementations that differ from the reference in config discovery and diff presentation for diff overlapping context; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'input.yaml': (
            'a:  1\n'
            'b: 2\n'
            'c: 3\n'
            'd: 4\n'
            'e: 5\n'
            'f:  6\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_overlapping_context.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)
