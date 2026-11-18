"""Spec yaml collections behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_yaml_block_mapping_sequence_items_are_structural(run, workdir):
    """CATCHES: reimplementations that break "yaml block mapping sequence items are structural" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: compact table\n'
        '- name: a\n'
        '  type: int\n'
        '- name: long_name\n'
        '  type: string\n'
        '\n'
        'items:\n'
        '  - name: keep\n'
        '    value: [ one , two]\n'
        '\n'
        '# fmt: table\n'
        '- name: preserve\n'
        '  type: block\n'
        'after: done\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_block_mapping_sequence_items_are_structural.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_1(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed flow and mapping roots are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = '\ufeff[a,b,{x: y}]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'\xef\xbb\xbf[a,b,{x: y}]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_2(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed flow and mapping roots are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = '\ufeff[a,b,{x: y}]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == b'\xef\xbb\xbf[a,b,{x: y}]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_3(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed flow and mapping roots are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = '\ufeff[a,b,{x: y}]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--canonical'], input=stdin)
    assert result.stdout == b'\xef\xbb\xbf[a,b,{x: y}]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_4(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed flow and mapping roots are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '\ufeffa: 1\n'
        'b: [2,3]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_5(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed flow and mapping roots are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '\ufeffa: 1\n'
        'b: [2,3]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_6(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed flow and mapping roots are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '\ufeffa: 1\n'
        'b: [2,3]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_flow_and_mapping_roots_are_preserved_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_root_block_scalars_and_sequences_are_preserved_1(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed root block scalars and sequences are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
        '\ufeff|-\n'
        '  first\n'
        '  second\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_root_block_scalars_and_sequences_are_preserved_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_root_block_scalars_and_sequences_are_preserved_2(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed root block scalars and sequences are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        '\ufeff- |-\n'
        '  first\n'
        '- after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_root_block_scalars_and_sequences_are_preserved_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_bom_prefixed_root_block_scalars_and_sequences_are_preserved_3(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed root block scalars and sequences are preserved" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
        '\ufeff- - |-\n'
        '    first\n'
        '  - after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_root_block_scalars_and_sequences_are_preserved_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_collapses_sequence_item_collections_when_they_fit(run, workdir):
    """CATCHES: reimplementations that break "yaml compact collapses sequence item collections when they fit" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items:\n'
        '  -\n'
        '    name: yamark\n'
        '    language: rust\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'items: [{name: yamark, language: rust}]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_bom_prefixed_root_mapping_preserves_block_scalar_body(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed root mapping preserves block scalar body" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '\ufeffvalue: |-\n'
        '  first\n'
        '  second\n'
        'after: y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_root_mapping_preserves_block_scalar_body.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_expands_sequence_item_collections_when_sequence_is_too_wide(run, workdir):
    """CATCHES: reimplementations that break "yaml compact expands sequence item collections when sequence is too wide" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items:\n'
        '  -\n'
        '    name: yamark\n'
        '    language: rust\n'
        '  -\n'
        '    name: yamark\n'
        '    language: rust\n'
        '  -\n'
        '    name: yamark\n'
        '    language: rust\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'yaml_compact_expands_sequence_item_collections_when_sequence_is_too_wide.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_compact_keeps_single_line_sequence_mappings_in_block_style_1(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single line sequence mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '- extends: workspace\n'
        '- extends: other\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--indent-width', '2'],
        input=stdin,
    )
    assert result.stdout == (RES / 'yaml_compact_keeps_single_line_sequence_mappings_in_block_style_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', '--indent-width', '2', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_keeps_single_line_sequence_mappings_in_block_style_2(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single line sequence mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '- extends: workspace\n'
        '- extends: other\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--indent-width', '4'],
        input=stdin,
    )
    assert result.stdout == (RES / 'yaml_compact_keeps_single_line_sequence_mappings_in_block_style_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_keeps_single_pair_root_mappings_in_block_style_1(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single pair root mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'extends: workspace\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'extends: workspace\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_keeps_single_pair_root_mappings_in_block_style_2(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single pair root mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'extends: :workspace\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'extends: :workspace\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_keeps_single_pair_root_mappings_in_block_style_3(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single pair root mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'extends: [ one , two ]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'extends: [one, two]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_compact_keeps_single_pair_root_mappings_in_block_style_4(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single pair root mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'extends: [one, two]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'extends: [one, two]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_keeps_single_pair_root_mappings_in_block_style_5(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single pair root mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '---\n'
        'extends: workspace\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'yaml_compact_keeps_single_pair_root_mappings_in_block_style_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_keeps_single_pair_root_mappings_in_block_style_6(run, workdir):
    """CATCHES: reimplementations that break "yaml compact keeps single pair root mappings in block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'extends: workspace\r\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'extends: workspace\r\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_quotes_plain_scalars_that_are_unsafe_in_flow_context(run, workdir):
    """CATCHES: reimplementations that break "yaml compact quotes plain scalars that are unsafe in flow context" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'item:\n'
        '  text: a, b\n'
        '  label: colon: value\n'
        '  hash: a\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b"item: {text: 'a, b', label: 'colon: value', hash: a}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_compact_quotes_plain_scalars_with_control_characters(run, workdir):
    """CATCHES: reimplementations that break "yaml compact quotes plain scalars with control characters" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'item:\n'
        '  text: !!str a\x07b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'item: {text: !!str "a\\ab"}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_compact_table_preserves_block_mappings_with_explicit_keys(run, workdir):
    """CATCHES: reimplementations that break "yaml compact table preserves block mappings with explicit keys" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: compact table\n'
        '- ? name\n'
        '  : a\n'
        '  type: int\n'
        '- name: long_name\n'
        '  type: string\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_compact_table_preserves_block_mappings_with_explicit_keys.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_respects_line_width(run, workdir):
    """CATCHES: reimplementations that break "yaml compact respects line width" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'package:\n'
        '  name: yamark\n'
        '  language: rust\n'
        '  license: MIT\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '50'],
        input=stdin,
    )
    assert result.stdout == (RES / 'yaml_compact_respects_line_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', '--line-width', '50', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_compact_still_collapses_single_pair_mappings_when_it_saves_a_line_1(run, workdir):
    """CATCHES: reimplementations that break "yaml compact still collapses single pair mappings when it saves a line" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'task:\n'
        '  extends: workspace\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'task: {extends: workspace}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_compact_still_collapses_single_pair_mappings_when_it_saves_a_line_2(run, workdir):
    """CATCHES: reimplementations that break "yaml compact still collapses single pair mappings when it saves a line" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '-\n'
        '  extends: workspace\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'- {extends: workspace}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_escaped_newline_quoted_inline_sequence_mapping_uses_literal_block(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped newline quoted inline sequence mapping uses literal block" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'outer:\n'
        '  - text: "\\n\\x20first\\n\\\n'
        '      Traceback:\\n\\x201: frame"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_escaped_newline_quoted_inline_sequence_mapping_uses_literal_block.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_deep_nested_flow_collections_expand_when_lines_stay_wide(run, workdir):
    """CATCHES: reimplementations that break "yaml deep nested flow collections expand when lines stay wide" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'config: {outer: {alpha: [one, two, three], beta: [four, five, six]}}\n'
        'items: [[alpha, beta, gamma], [delta, epsilon, zeta]]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '22'], input=stdin)
    assert result.stdout == (RES / 'yaml_deep_nested_flow_collections_expand_when_lines_stay_wide.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_detached_unmatched_flow_opener_after_empty_mapping_value_collapses_child_collection(run, workdir):
    """CATCHES: reimplementations that break "yaml detached unmatched flow opener after empty mapping value collapses child collection" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'tags:\n'
        '[\n'
        '  - llm\n'
        '  - authoring\n'
        '  - formats\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'tags: [llm, authoring, formats]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_escaped_newline_quoted_sequence_scalars_with_colons_emit_literal_blocks(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped newline quoted sequence scalars with colons emit literal blocks" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'messages:\n'
        '  - "Lorem ipsum: dolor sit amet\\nConsectetur adipiscing elit"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_escaped_newline_quoted_sequence_scalars_with_colons_emit_literal_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_explicit_flow_pairs_preserve_source_spelling(run, workdir):
    """CATCHES: reimplementations that break "yaml explicit flow pairs preserve source spelling" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'map: {? explicit: entry}\n'
        'seq: [? key: value]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_explicit_flow_pairs_preserve_source_spelling.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_explicit_mapping_values_are_formatted_and_targetable_1(run, workdir):
    """CATCHES: reimplementations that break "yaml explicit mapping values are formatted and targetable" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '? key\n'
        ': [ one ,  two]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_explicit_mapping_values_are_formatted_and_targetable_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_explicit_mapping_values_are_formatted_and_targetable_2(run, workdir):
    """CATCHES: reimplementations that break "yaml explicit mapping values are formatted and targetable" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: markdown\n'
        '? key\n'
        ': |\n'
        '  #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_explicit_mapping_values_are_formatted_and_targetable_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_flow_collections_are_parsed_before_formatting(run, workdir):
    """CATCHES: reimplementations that break "yaml flow collections are parsed before formatting" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'flow: [ one , [ two , three ], { name : "a, b", tags: [x, y] } ] # keep\n'
        'map: { a : [ one , two ], b : { c : d } }\n'
        '\n'
        '# fmt: table\n'
        '- {name: a, desc: "one, two"}\n'
        '- {name: longer, desc: z}\n'
        '\n'
        '# fmt: table\n'
        '- {name: a, type: int, default: 1}\n'
        '- {name: long_name, type: string, default: two}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_flow_collections_are_parsed_before_formatting.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_flow_collections_expand_when_they_exceed_line_width(run, workdir):
    """CATCHES: reimplementations that break "yaml flow collections expand when they exceed line width" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items: [one, two, three, four]\n'
        'config: {name: yamark, language: rust}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '18'], input=stdin)
    assert result.stdout == (RES / 'yaml_flow_collections_expand_when_they_exceed_line_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_flow_sequence_implicit_collection_keys_preserve_structure(run, workdir):
    """CATCHES: reimplementations that break "yaml flow sequence implicit collection keys preserve structure" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'items: [{a: b}: c, [x, y]: z]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'items: [{a: b}: c, [x, y]: z]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_flow_strings_preserve_boundary_whitespace(run, workdir):
    """CATCHES: reimplementations that break "yaml flow strings preserve boundary whitespace" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'items: [" foo", "foo "]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'items: [" foo", "foo "]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_json_lines_inserts_initial_markers_and_preserves_crlf_1(run, workdir):
    """CATCHES: reimplementations that break "yaml json lines inserts initial markers and preserves crlf" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '{"id":1}\r\n'
        '{"id":2}\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_json_lines_inserts_initial_markers_and_preserves_crlf_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_json_lines_inserts_initial_markers_and_preserves_crlf_2(run, workdir):
    """CATCHES: reimplementations that break "yaml json lines inserts initial markers and preserves crlf" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '---\r\n'
        '{id: 1}\r\n'
        '---\r\n'
        '{id: 2}\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_json_lines_inserts_initial_markers_and_preserves_crlf_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_indent_width_applies_to_nested_sequence_expansion(run, workdir):
    """CATCHES: reimplementations that break "yaml indent width applies to nested sequence expansion" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'root:\n'
        '  items: [one, two, three]\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--line-width', '14', '--indent-width', '4'],
        input=stdin,
    )
    assert result.stdout == (RES / 'yaml_indent_width_applies_to_nested_sequence_expansion.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_multiline_flow_collections_are_structural(run, workdir):
    """CATCHES: reimplementations that break "yaml multiline flow collections are structural" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: table\n'
        '- {\n'
        '  name: a,\n'
        '  desc: "one, two"\n'
        '}\n'
        '- {\n'
        '  name: longer,\n'
        '  desc: z\n'
        '}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_multiline_flow_collections_are_structural.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nested_compact_sequence_mapping_preserves_structure(run, workdir):
    """CATCHES: reimplementations that break "yaml nested compact sequence mapping preserves structure" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- - key: "value"\n'
        '    empty: ~\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_nested_compact_sequence_mapping_preserves_structure.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_multiline_quoted_flow_scalar_expands_without_final_newline(run, workdir):
    """CATCHES: reimplementations that break "yaml multiline quoted flow scalar expands without final newline" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'items: ["alpha\\nbeta"]'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (RES / 'yaml_multiline_quoted_flow_scalar_expands_without_final_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nested_flow_collections_expand_when_outer_expansion_leaves_wide_lines(run, workdir):
    """CATCHES: reimplementations that break "yaml nested flow collections expand when outer expansion leaves wide lines" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'config: {a: [alpha, beta, gamma]}\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '24'], input=stdin)
    assert result.stdout == (RES / 'yaml_nested_flow_collections_expand_when_outer_expansion_leaves_wide_lines.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nested_sequence_folded_scalar_uses_child_indent(run, workdir):
    """CATCHES: reimplementations that break "yaml nested sequence folded scalar uses child indent" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '- - This is a long prose scalar with enough words to fold into a block scalar safely\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '30'], input=stdin)
    assert result.stdout == (RES / 'yaml_nested_sequence_folded_scalar_uses_child_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_newline_inside_flow_mapping_expands_it_to_block_style(run, workdir):
    """CATCHES: reimplementations that break "yaml newline inside flow mapping expands it to block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- {a: b,\n'
        '   c: d}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_newline_inside_flow_mapping_expands_it_to_block_style.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_newline_inside_flow_sequence_expands_it_to_block_style(run, workdir):
    """CATCHES: reimplementations that break "yaml newline inside flow sequence expands it to block style" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items: [one,\n'
        '  two,\n'
        '  [three, four]]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_newline_inside_flow_sequence_expands_it_to_block_style.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_keeps_sequence_mapping_keys_aligned(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent keeps sequence mapping keys aligned" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- first: ~\n'
        '  second: []\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_keeps_sequence_mapping_keys_aligned.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--indent-width', '4', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_1(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline quoted sequence mapping scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'outer:\n'
        "  - value: 'first\n"
        '      second\n'
        "      third'\n"
        '    after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_2(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline quoted sequence mapping scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'outer:\r\n'
        "  - value: 'first\r\n"
        '      second\r\n'
        "      third'\r\n"
        '    after: x\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_3(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline quoted sequence mapping scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'outer:\r'
        "  - value: 'first\r"
        '      second\r'
        "      third'\r"
        '    after: x\r'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (
        b'outer:\r'
        b"    - value: 'first\r"
        b'        second\r'
        b"        third'\r"
        b'      after: x\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_4(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline quoted sequence mapping scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'outer:\n'
        '  - value: "first\n'
        '      second\n'
        '      third"\n'
        '    after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_5(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline quoted sequence mapping scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'outer:\r\n'
        '  - value: "first\r\n'
        '      second\r\n'
        '      third"\r\n'
        '    after: x\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_quoted_sequence_mapping_scalar_6(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline quoted sequence mapping scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'outer:\r'
        '  - value: "first\r'
        '      second\r'
        '      third"\r'
        '    after: x\r'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (
        b'outer:\r'
        b'    - value: "first\r'
        b'        second\r'
        b'        third"\r'
        b'      after: x\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_nested_sequence_block_scalar(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents nested sequence block scalar" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- - |-\n'
        '    first\n'
        '    second\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_nested_sequence_block_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_root_flow_collection_expands_when_it_exceeds_line_width(run, workdir):
    """CATCHES: reimplementations that break "yaml root flow collection expands when it exceeds line width" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '[one, two, three, four]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '10'], input=stdin)
    assert result.stdout == (RES / 'yaml_root_flow_collection_expands_when_it_exceeds_line_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_sequence_item_explicit_mapping_with_flow_key_preserves_structure(run, workdir):
    """CATCHES: reimplementations that break "yaml sequence item explicit mapping with flow key preserves structure" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- ? [a,b]\n'
        '  : [c,d]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_sequence_item_explicit_mapping_with_flow_key_preserves_structure.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_sequence_entry_flow_collection_expands_when_it_exceeds_line_width(run, workdir):
    """CATCHES: reimplementations that break "yaml sequence entry flow collection expands when it exceeds line width" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items:\n'
        '  - [one, two, three, four]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '16'], input=stdin)
    assert result.stdout == (RES / 'yaml_sequence_entry_flow_collection_expands_when_it_exceeds_line_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_sequence_item_mapping_plain_prose_scalars_fold_with_valid_body_indent(run, workdir):
    """CATCHES: reimplementations that break "yaml sequence item mapping plain prose scalars fold with valid body indent" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '- description: This is a long prose scalar with enough words to fold into a block scalar safely\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '42'], input=stdin)
    assert result.stdout == (RES / 'yaml_sequence_item_mapping_plain_prose_scalars_fold_with_valid_body_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_sequence_item_mapping_prose_scalars_fold_with_valid_body_indent(run, workdir):
    """CATCHES: reimplementations that break "yaml sequence item mapping prose scalars fold with valid body indent" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '- description: "This is a long prose scalar with enough words to fold into a block scalar safely"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '42'], input=stdin)
    assert result.stdout == (RES / 'yaml_sequence_item_mapping_prose_scalars_fold_with_valid_body_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_sequence_mapping_block_scalar_stops_before_sibling_pair(run, workdir):
    """CATCHES: reimplementations that break "yaml sequence mapping block scalar stops before sibling pair" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- value: |-\n'
        '    first\n'
        '    second\n'
        '  empty: ~\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_sequence_mapping_block_scalar_stops_before_sibling_pair.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unmatched_flow_mapping_opener_at_sequence_item_start_collapses_block_mapping_row(run, workdir):
    """CATCHES: reimplementations that break "yaml unmatched flow mapping opener at sequence item start collapses block mapping row" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items:\n'
        '  - {name: a\n'
        '    kind: scalar\n'
        '  - {name: longer\n'
        '    kind: sequence\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_unmatched_flow_mapping_opener_at_sequence_item_start_collapses_block_mapping_row.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_unmatched_flow_sequence_opener_at_mapping_value_start_collapses_block_sequence(run, workdir):
    """CATCHES: reimplementations that break "yaml unmatched flow sequence opener at mapping value start collapses block sequence" (yaml collections); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'tags: [\n'
        '  - llm\n'
        '  - authoring\n'
        '  - formats\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'tags: [llm, authoring, formats]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
