"""Config discovery behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_relative_file_and_directory_paths_discover_ancestor_config_1(run, workdir):
    """CATCHES: reimplementations that break "relative file and directory paths discover ancestor config" (config discovery); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'nested/input.md': 'First sentence. Second sentence.\n',
        'nested/second.md': 'First sentence. Second sentence.\n',
    }
    write_tree(workdir, files, dirs=['nested'])
    result = run(['format', 'input.md'], cwd=workdir / 'nested')
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'nested/input.md': (
            'First sentence.\n'
            'Second sentence.\n'
        ),
    }))
    assert read_tree(workdir) == expected


def test_relative_file_and_directory_paths_discover_ancestor_config_2(run, workdir):
    """CATCHES: reimplementations that break "relative file and directory paths discover ancestor config" (config discovery); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'nested/input.md': 'First sentence. Second sentence.\n',
        'nested/second.md': 'First sentence. Second sentence.\n',
    }
    write_tree(workdir, files, dirs=['nested'])
    result = run(['format', 'input.md', 'second.md'], cwd=workdir / 'nested')
    assert result.stdout == b'2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'nested/input.md': (
            'First sentence.\n'
            'Second sentence.\n'
        ),
        'nested/second.md': (
            'First sentence.\n'
            'Second sentence.\n'
        ),
    }))
    assert read_tree(workdir) == expected


def test_relative_file_and_directory_paths_discover_ancestor_config_3(run, workdir):
    """CATCHES: reimplementations that break "relative file and directory paths discover ancestor config" (config discovery); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'nested/input.md': 'First sentence. Second sentence.\n',
        'nested/second.md': 'First sentence. Second sentence.\n',
    }
    write_tree(workdir, files, dirs=['nested'])
    result = run(['format', '.'], cwd=workdir / 'nested')
    assert result.stdout == b'2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'nested/input.md': (
            'First sentence.\n'
            'Second sentence.\n'
        ),
        'nested/second.md': (
            'First sentence.\n'
            'Second sentence.\n'
        ),
    }))
    assert read_tree(workdir) == expected
