"""Diff output behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_diff_context_produces_applicable_patches_1(run, workdir):
    """CATCHES: reimplementations that break "diff context produces applicable patches" (diff output); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    files = {
        'input.yaml': (
            'first:  changed\n'
            'last:  changed\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_context_produces_applicable_patches_1.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_context_produces_applicable_patches_2(run, workdir):
    """CATCHES: reimplementations that break "diff context produces applicable patches" (diff output); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    files = {
        'input.yaml': (
            'first:  changed\n'
            'context0: unchanged\n'
            'last:  changed\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_context_produces_applicable_patches_2.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_context_produces_applicable_patches_3(run, workdir):
    """CATCHES: reimplementations that break "diff context produces applicable patches" (diff output); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    files = {
        'input.yaml': (
            'first:  changed\n'
            'context0: unchanged\n'
            'context1: unchanged\n'
            'context2: unchanged\n'
            'last:  changed\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_context_produces_applicable_patches_3.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_context_produces_applicable_patches_4(run, workdir):
    """CATCHES: reimplementations that break "diff context produces applicable patches" (diff output); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    files = {
        'input.yaml': (
            'first:  changed\n'
            'context0: unchanged\n'
            'context1: unchanged\n'
            'context2: unchanged\n'
            'context3: unchanged\n'
            'context4: unchanged\n'
            'last:  changed\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_context_produces_applicable_patches_4.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_context_produces_applicable_patches_5(run, workdir):
    """CATCHES: reimplementations that break "diff context produces applicable patches" (diff output); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    files = {
        'input.yaml': (
            'first:  changed\n'
            'context0: unchanged\n'
            'context1: unchanged\n'
            'context2: unchanged\n'
            'context3: unchanged\n'
            'context4: unchanged\n'
            'context5: unchanged\n'
            'context6: unchanged\n'
            'last:  changed\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_context_produces_applicable_patches_5.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_context_produces_applicable_patches_6(run, workdir):
    """CATCHES: reimplementations that break "diff context produces applicable patches" (diff output); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    files = {
        'input.yaml': (
            'first:  changed\n'
            'context0: unchanged\n'
            'context1: unchanged\n'
            'context2: unchanged\n'
            'context3: unchanged\n'
            'context4: unchanged\n'
            'context5: unchanged\n'
            'context6: unchanged\n'
            'context7: unchanged\n'
            'context8: unchanged\n'
            'last:  changed\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_context_produces_applicable_patches_6.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)
