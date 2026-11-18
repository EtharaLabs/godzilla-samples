"""Spec yaml preservation behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_unsupported_flow_values_preserve_container_prefixes_1(run, workdir):
    """CATCHES: reimplementations that break "unsupported flow values preserve container prefixes" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'top: [a,b]\n'
        'sequence:\n'
        "  - [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_values_preserve_container_prefixes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unsupported_flow_values_preserve_container_prefixes_2(run, workdir):
    """CATCHES: reimplementations that break "unsupported flow values preserve container prefixes" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'top: [a, b]\n'
        'sequence:\n'
        "  - [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_values_preserve_container_prefixes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_flow_values_preserve_container_prefixes_3(run, workdir):
    """CATCHES: reimplementations that break "unsupported flow values preserve container prefixes" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'top: [a,b]\n'
        'sequence:\n'
        '  -\n'
        "    [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_values_preserve_container_prefixes_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unsupported_flow_values_preserve_container_prefixes_4(run, workdir):
    """CATCHES: reimplementations that break "unsupported flow values preserve container prefixes" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'top: [a,b]\n'
        'nested:\n'
        "  [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_values_preserve_container_prefixes_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unsupported_flow_values_preserve_container_prefixes_5(run, workdir):
    """CATCHES: reimplementations that break "unsupported flow values preserve container prefixes" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'top: [a, b]\n'
        'nested:\n'
        "  [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_values_preserve_container_prefixes_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_flow_values_preserve_container_prefixes_6(run, workdir):
    """CATCHES: reimplementations that break "unsupported flow values preserve container prefixes" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'top: [a,b]\n'
        '? explicit\n'
        ": [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_values_preserve_container_prefixes_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_diagnostics_report_fast_path_trace_counters(run, workdir):
    """CATCHES: reimplementations that break "yaml diagnostics report fast path trace counters" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'name: yamark\n'
    result = run(['format', '--diagnostics', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'name: yamark\n'
    assert result.stderr.decode() == 'input.yaml:1:1: note: yaml trace: source_scans=1 parse_passes=1 source_lines=1 yaml_scanned_lines=1 yaml_semantic_nodes=3 planned_rendered_scalars=2 planned_rendered_flow_collections=0 planned_rendered_block_flow_collections=0 emitted_bytes=13 emitted_nodes=2\n'
    assert result.returncode == 0


def test_yaml_diagnostics_report_verified_output_reparse(run, workdir):
    """CATCHES: reimplementations that break "yaml diagnostics report verified output reparse" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'name:   yamark\n'
    result = run(['format', '--diagnostics', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'name: yamark\n'
    assert result.stderr.decode() == 'input.yaml:1:1: note: yaml trace: source_scans=1 parse_passes=1 source_lines=1 yaml_scanned_lines=1 yaml_semantic_nodes=3 planned_rendered_scalars=2 planned_rendered_flow_collections=0 planned_rendered_block_flow_collections=0 emitted_bytes=13 emitted_nodes=2\n'
    assert result.returncode == 0


def test_yaml_diagnostics_skip_output_reparse_by_default(run, workdir):
    """CATCHES: reimplementations that break "yaml diagnostics skip output reparse by default" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'name:   yamark\n'
    result = run(['format', '--diagnostics', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'name: yamark\n'
    assert result.stderr.decode() == 'input.yaml:1:1: note: yaml trace: source_scans=1 parse_passes=1 source_lines=1 yaml_scanned_lines=1 yaml_semantic_nodes=3 planned_rendered_scalars=2 planned_rendered_flow_collections=0 planned_rendered_block_flow_collections=0 emitted_bytes=13 emitted_nodes=2\n'
    assert result.returncode == 0


def test_yaml_skip_file_short_circuits_later_invalid_leading_fmt_comments(run, workdir):
    """CATCHES: reimplementations that break "yaml skip file short circuits later invalid leading fmt comments" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: skip file\n'
        '# fmt: unknown\n'
        'a:    b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_skip_file_short_circuits_later_invalid_leading_fmt_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_flow_syntax_is_preserved_without_directives(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported flow syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'flow: {\n'
        '  a:    b, # comment\n'
        '  c:    d\n'
        '}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_flow_syntax_is_preserved_without_directives.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_skip_preserves_nested_target_node_with_leading_trivia(run, workdir):
    """CATCHES: reimplementations that break "yaml skip preserves nested target node with leading trivia" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: skip\n'
        'root:\n'
        '  name:    keep\n'
        '  tags: [keep,spacing]\n'
        'other:    change\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_skip_preserves_nested_target_node_with_leading_trivia.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_unsupported_implicit_block_scalar_indent_is_preserved_1(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported implicit block scalar indent is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'text: |-\n'
        '  \n'
        '   *** caught segfault ***\n'
        '  address 0x0\n'
    )
    result = run(['format', '--skip-embedded-formatters', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_implicit_block_scalar_indent_is_preserved_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--skip-embedded-formatters', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_implicit_block_scalar_indent_is_preserved_2(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported implicit block scalar indent is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'text: |-\n'
        '  \n'
        '   *** caught segfault ***\n'
        '  address 0x0\n'
    )
    result = run(
        ['format', '--skip-embedded-formatters', '--stdin-file-path', 'input.yaml', '--indent-width', '4'],
        input=stdin,
    )
    assert result.stdout == (RES / 'yaml_unsupported_implicit_block_scalar_indent_is_preserved_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--skip-embedded-formatters', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_1(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported root mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        '&anchor key: "\\n\\x20first\\n\\\n'
        '  Traceback:\\n\\x201: frame"\n'
        'flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_2(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported root mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        '!tag key: "\\n\\x20first\\n\\\n'
        '  Traceback:\\n\\x201: frame"\n'
        'flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_3(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported root mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        '*alias: "\\n\\x20first\\n\\\n'
        '  Traceback:\\n\\x201: frame"\n'
        'flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_4(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported root mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '? key: "\\n\\x20first\\n\\\n'
        '  Traceback:\\n\\x201: frame"\n'
        'flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_root_mapping_with_multiline_quote_is_preserved_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_leading_block_scalar_blank_indent_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported leading block scalar blank indent is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'text: |-\n'
        '    \n'
        '  content\n'
    )
    result = run(['format', '--indent-width', '4', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_leading_block_scalar_blank_indent_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_1(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported sequence mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        'outer:\n'
        '  - ? key: "\\n\\x20first\\n\\\n'
        '      Traceback:\\n\\x201: frame"\n'
        '    flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_2(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported sequence mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        'outer:\n'
        '  - ?key: "\\n\\x20first\\n\\\n'
        '      Traceback:\\n\\x201: frame"\n'
        '    flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_3(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported sequence mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        'outer:\n'
        '  - &anchor key : "\\n\\x20first\\n\\\n'
        '      Traceback:\\n\\x201: frame"\n'
        '    flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_4(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported sequence mapping with multiline quote is preserved" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        'outer:\n'
        '  - !tag key : "\\n\\x20first\\n\\\n'
        '      Traceback:\\n\\x201: frame"\n'
        '    flow: [a,b]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_sequence_mapping_with_multiline_quote_is_preserved_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_suite_syntax_is_preserved_without_directives_1(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported suite syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '%FOO  bar baz # Should be ignored\n'
        '---\n'
        '"foo"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_suite_syntax_is_preserved_without_directives_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_suite_syntax_is_preserved_without_directives_2(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported suite syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '--- |-\n'
        ' ab\n'
        ' \n'
        '...\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_suite_syntax_is_preserved_without_directives_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_suite_syntax_is_preserved_without_directives_3(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported suite syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'key ends with two colons::: value\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'key ends with two colons::: value\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_suite_syntax_is_preserved_without_directives_4(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported suite syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'key: &anchor\n'
        ' !!map\n'
        '  a: b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_suite_syntax_is_preserved_without_directives_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_suite_syntax_is_preserved_without_directives_5(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported suite syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'a: &:@*!$"<foo>: scalar a\n'
        'b: *:@*!$"<foo>:\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_suite_syntax_is_preserved_without_directives_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsupported_suite_syntax_is_preserved_without_directives_6(run, workdir):
    """CATCHES: reimplementations that break "yaml unsupported suite syntax is preserved without directives" (yaml preservation); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        "'implicit block key' : [\n"
        "  'implicit flow key' : value,\n"
        ' ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unsupported_suite_syntax_is_preserved_without_directives_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
