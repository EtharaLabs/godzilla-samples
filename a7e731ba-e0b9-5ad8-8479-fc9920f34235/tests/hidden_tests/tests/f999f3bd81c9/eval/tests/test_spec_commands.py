"""Spec commands behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_bom_prefixed_first_line_directives_apply_1(run, workdir):
    """CATCHES: reimplementations that break "bom prefixed first line directives apply" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        '\ufeff# fmt: skip file\n'
        'a:    b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'bom_prefixed_first_line_directives_apply_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_bom_prefixed_first_line_directives_apply_2(run, workdir):
    """CATCHES: reimplementations that break "bom prefixed first line directives apply" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        '\ufeff<!-- fmt: skip file -->\n'
        '#   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'bom_prefixed_first_line_directives_apply_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_bom_prefixed_first_line_directives_apply_3(run, workdir):
    """CATCHES: reimplementations that break "bom prefixed first line directives apply" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        '\ufeff# fmt: markdown\n'
        '# #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'bom_prefixed_first_line_directives_apply_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_bom_prefixed_first_line_directives_apply_4(run, workdir):
    """CATCHES: reimplementations that break "bom prefixed first line directives apply" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '\ufeff# fmt: markdown\n'
        '# #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.r', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'bom_prefixed_first_line_directives_apply_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_diff_mode_prints_contextual_unified_hunks(run, workdir):
    """CATCHES: reimplementations that break "diff mode prints contextual unified hunks" (commands); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'input.yaml': (
            'top: one\n'
            'a: 1\n'
            'b: 2\n'
            'c: 3\n'
            'd: 4\n'
            'e: 5\n'
            'f: 6\n'
            'items: [a,b]\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.yaml'])
    assert result.stdout == (RES / 'diff_mode_prints_contextual_unified_hunks.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_mode_reports_missing_final_newline_changes(run, workdir):
    """CATCHES: reimplementations that break "diff mode reports missing final newline changes" (commands); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'input.md': '# Title',
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'input.md'])
    assert result.stdout == (RES / 'diff_mode_reports_missing_final_newline_changes.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_diff_mode_resyncs_after_large_fallback_insertions(run, workdir):
    """CATCHES: reimplementations that break "diff mode resyncs after large fallback insertions" (commands); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        # An unspaced 100-item flow sequence, 3000 plain keys, then a short flow sequence.
        'large.yaml': f'items: [{",".join(f"item_{i}" for i in range(100))}]\n'
        + ''.join(f'key_{i}: value\n' for i in range(3000)) + 'second: [c,d]\n',
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', '--line-width', '40', 'large.yaml'])
    assert result.stdout == (RES / 'diff_mode_resyncs_after_large_fallback_insertions.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_format_rejects_unsupported_fast_option(run, workdir):
    """CATCHES: reimplementations that break "format rejects unsupported fast option" (commands); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '# Title\n'
    result = run(['format', '--fast', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: unexpected argument '--fast' found\n"
        '\n'
        "  tip: to pass '--fast' as a value, use '-- --fast'\n"
        '\n'
        'Usage: executable format [OPTIONS] [PATHS]...\n'
        '\n'
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_diff_mode_handles_large_inputs_without_quadratic_memory(run, workdir):
    """CATCHES: reimplementations that break "diff mode handles large inputs without quadratic memory" (commands); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        # 24 000 `key_<i>: value` lines with one unformatted flow sequence in the middle.
        'large.yaml': ''.join(f'key_{i}: value\n' for i in range(12000)) + 'items: [a,b]\n'
        + ''.join(f'key_{i}: value\n' for i in range(12000, 24000)),
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'large.yaml'])
    assert result.stdout == (RES / 'diff_mode_handles_large_inputs_without_quadratic_memory.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_git_filter_formats_only_markdown_1(run, workdir):
    """CATCHES: reimplementations that break "git filter formats only markdown" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = 'One sentence. Two sentences.\n'
    result = run(['git-filter', 'clean', '--stdin-filename', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'git_filter_formats_only_markdown_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_git_filter_formats_only_markdown_2(run, workdir):
    """CATCHES: reimplementations that break "git filter formats only markdown" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        '| a | long |\n'
        '|---|:---:|\n'
        '| 1 | two |\n'
    )
    result = run(['git-filter', 'clean', '--stdin-filename', 'table.md'], input=stdin)
    assert result.stdout == (RES / 'git_filter_formats_only_markdown_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_git_filter_formats_only_markdown_3(run, workdir):
    """CATCHES: reimplementations that break "git filter formats only markdown" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = '#   Title ##\n'
    result = run(['git-filter', 'clean', '--stdin-filename', 'input.txt'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.txt:1:1: error: unsupported Git filter path\n'
    assert result.returncode == 1


def test_diff_mode_handles_repeated_large_fallback_syncs_without_hanging(run, workdir):
    """CATCHES: reimplementations that break "diff mode handles repeated large fallback syncs without hanging" (commands); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        # 400 blocks of an unspaced 128-item flow sequence followed by a plain key.
        'large.yaml': ''.join(
            f'items_{k}: [{",".join(f"item_{i}" for i in range(128))}]\nkey_{k}: value\n' for k in range(400)
        ),
        'diff.out': "",
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', '--line-width', '40', 'large.yaml'])
    assert result.stdout == (RES / 'diff_mode_handles_repeated_large_fallback_syncs_without_hanging.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_stdin_encoding_errors_are_targeted_1(run, workdir):
    """CATCHES: reimplementations that break "stdin encoding errors are targeted" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = b'\xff\xfe\x00\x00'
    result = run(['format', '--stdin-file-path', 'bad.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'bad.md:1:1: error: unsupported encoding: UTF-16 BOM\n'
    assert result.returncode == 1


def test_stdin_encoding_errors_are_targeted_2(run, workdir):
    """CATCHES: reimplementations that break "stdin encoding errors are targeted" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = b'\xff'
    result = run(['format', '--stdin-file-path', 'bad.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'bad.md:1:1: error: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 0\n'
    assert result.returncode == 1


def test_to_yaml_accepts_stdin_only(run, workdir):
    """CATCHES: reimplementations that break "to yaml accepts stdin only" (commands); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '{}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.json', 'other.json'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: unexpected argument 'other.json' found\n"
        '\n'
        'Usage: executable to-yaml [OPTIONS] --stdin-file-path <PATH>\n'
        '\n'
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


def test_to_yaml_json5_rejects_excessive_nesting_without_aborting(run, workdir):
    """CATCHES: reimplementations that break "to yaml json5 rejects excessive nesting without aborting" (commands); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[/* comment */0]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]'
    result = run(['to-yaml', '--stdin-file-path', 'input.json5'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.json5:1:257: error: invalid JSON5: nesting exceeds 256 levels\n'
    assert result.returncode == 1


def test_to_yaml_json5_rejects_repeated_unary_operators_without_aborting(run, workdir):
    """CATCHES: reimplementations that break "to yaml json5 rejects repeated unary operators without aborting" (commands); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = "+" * 10000 + "1"  # 10 000 unary plus signs
    result = run(['to-yaml', '--stdin-file-path', 'input.json5'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.json5:1:2: error: invalid JSON5: Only one unary operator is allowed\n'
    assert result.returncode == 1


def test_to_yaml_jsonc_parser_inputs_reject_excessive_nesting_without_aborting_1(run, workdir):
    """CATCHES: reimplementations that break "to yaml jsonc parser inputs reject excessive nesting without aborting" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = "[" * 10000 + "0" + "]" * 10000  # 10 000 nested arrays
    result = run(['to-yaml', '--stdin-file-path', 'input.json'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.json:1:257: error: invalid JSON: nesting exceeds 256 levels\n'
    assert result.returncode == 1


def test_to_yaml_jsonc_parser_inputs_reject_excessive_nesting_without_aborting_2(run, workdir):
    """CATCHES: reimplementations that break "to yaml jsonc parser inputs reject excessive nesting without aborting" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = "[" * 10000 + "0" + "]" * 10000  # 10 000 nested arrays
    result = run(['to-yaml', '--stdin-file-path', 'input.jsonc'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.jsonc:1:257: error: invalid JSONC: nesting exceeds 256 levels\n'
    assert result.returncode == 1


def test_to_yaml_jsonc_parser_inputs_reject_excessive_nesting_without_aborting_3(run, workdir):
    """CATCHES: reimplementations that break "to yaml jsonc parser inputs reject excessive nesting without aborting" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = "[" * 10000 + "0" + "]" * 10000  # 10 000 nested arrays
    result = run(['to-yaml', '--stdin-file-path', 'input.jsonl'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.jsonl:1:257: error: invalid JSON: nesting exceeds 256 levels\n'
    assert result.returncode == 1


def test_to_yaml_jsonc_parser_inputs_reject_excessive_nesting_without_aborting_4(run, workdir):
    """CATCHES: reimplementations that break "to yaml jsonc parser inputs reject excessive nesting without aborting" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = "[" * 10000 + "0" + "]" * 10000  # 10 000 nested arrays
    result = run(['to-yaml', '--stdin-file-path', 'input.ndjson'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.ndjson:1:257: error: invalid JSON: nesting exceeds 256 levels\n'
    assert result.returncode == 1


def test_to_yaml_rejects_native_source_types_1(run, workdir):
    """CATCHES: reimplementations that break "to yaml rejects native source types" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = '{}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:1: error: JSON-to-YAML projection requires a .json, .jsonc, .json5, .jsonl, or .ndjson source path\n'
    assert result.returncode == 1


def test_to_yaml_rejects_native_source_types_2(run, workdir):
    """CATCHES: reimplementations that break "to yaml rejects native source types" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = '{}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:1: error: JSON-to-YAML projection requires a .json, .jsonc, .json5, .jsonl, or .ndjson source path\n'
    assert result.returncode == 1


def test_to_yaml_rejects_native_source_types_3(run, workdir):
    """CATCHES: reimplementations that break "to yaml rejects native source types" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = '{}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.py'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.py:1:1: error: JSON-to-YAML projection requires a .json, .jsonc, .json5, .jsonl, or .ndjson source path\n'
    assert result.returncode == 1


def test_to_yaml_rejects_native_source_types_4(run, workdir):
    """CATCHES: reimplementations that break "to yaml rejects native source types" (commands); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = '{}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.r'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.r:1:1: error: JSON-to-YAML projection requires a .json, .jsonc, .json5, .jsonl, or .ndjson source path\n'
    assert result.returncode == 1
