"""Spec yaml scalars behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_yaml_block_plain_scalar_moved_inline_preserves_continuation_indent_1(run, workdir):
    """CATCHES: reimplementations that break "yaml block plain scalar moved inline preserves continuation indent" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'Warning:\n'
        '  This is an error message\n'
        '  for the log file\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_block_plain_scalar_moved_inline_preserves_continuation_indent_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_block_plain_scalar_moved_inline_preserves_continuation_indent_2(run, workdir):
    """CATCHES: reimplementations that break "yaml block plain scalar moved inline preserves continuation indent" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'comments:\n'
        '    Late afternoon is best.\n'
        '    Backup contact is Nancy\n'
        '    Billsmer @ 338-4338.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_block_plain_scalar_moved_inline_preserves_continuation_indent_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_block_scalar_header_comments_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml block scalar header comments are preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: | # markdown\n'
        '  # Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_block_scalar_header_comments_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_block_scalar_removes_indentation_from_blank_lines(run, workdir):
    """CATCHES: reimplementations that break "yaml block scalar removes indentation from blank lines" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'text: |-\n'
        '  \n'
        '  [running]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_block_scalar_removes_indentation_from_blank_lines.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_bom_prefixed_opaque_root_stops_at_next_document_1(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed opaque root stops at next document" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '\ufeff- one\n'
        '---\n'
        'name:    value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_opaque_root_stops_at_next_document_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_bom_prefixed_opaque_root_stops_at_next_document_2(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed opaque root stops at next document" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '\ufeff|-\n'
        '  first\n'
        '---\n'
        'name:    value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_bom_prefixed_opaque_root_stops_at_next_document_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_core_collection_tags_are_removed_when_syntax_implies_type(run, workdir):
    """CATCHES: reimplementations that break "yaml core collection tags are removed when syntax implies type" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items: !!seq [ one , two ]\n'
        'mapping: !!map { a : b }\n'
        'block_seq: !!seq\n'
        '  - one\n'
        '  - two\n'
        'block_map: !!map\n'
        '  a: b\n'
        'anchored: &items !!seq [ one ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_core_collection_tags_are_removed_when_syntax_implies_type.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_custom_collection_tag_and_anchor_order_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml custom collection tag and anchor order is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'flow: &defaults !settings { name : yamark }\n'
        'block: &flags !settings\n'
        '  enabled: true\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_custom_collection_tag_and_anchor_order_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_document_markers_with_inline_content_parse_the_inline_root(run, workdir):
    """CATCHES: reimplementations that break "yaml document markers with inline content parse the inline root" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '--- !!map\n'
        'name:    value\n'
        '--- [ one , two ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_document_markers_with_inline_content_parse_the_inline_root.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_escaped_final_newline_quoted_scalars_emit_clipped_literal_blocks(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped final newline quoted scalars emit clipped literal blocks" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'text: "line\\n"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_escaped_final_newline_quoted_scalars_emit_clipped_literal_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_escaped_newline_quoted_scalar_with_leading_spaces_uses_literal_block(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped newline quoted scalar with leading spaces uses literal block" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'result:\n'
        '  content:\n'
        '    - type: text\n'
        '      text: "\\n\\x20*** caught segfault ***\\n\\\n'
        "        address 0x0, cause 'invalid permissions'\\n\\n\\\n"
        '        Traceback:\\n\\x201: tools::pskill(Sys.getpid(), signal = 11L)\\n\\n\\\n'
        '        Possible actions:\\n\\\n'
        '        1: abort (with core dump, if enabled)\\n\\\n'
        '        2: normal R exit\\n\\\n'
        '        3: exit R without saving workspace\\n\\\n'
        '        4: exit R saving workspace\\n\\\n'
        '        Selection: R is aborting now ...\\n\\\n'
        '        worker sideband read failed: worker sideband closed"\n'
        '  isError: true\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_escaped_newline_quoted_scalar_with_leading_spaces_uses_literal_block.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_escaped_newline_quoted_scalars_emit_literal_blocks(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped newline quoted scalars emit literal blocks" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'text: "line one\\nline two"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_escaped_newline_quoted_scalars_emit_literal_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_escaped_non_printable_strings_remain_quoted_1(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped non printable strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = 'value: "\\uFEFF"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'value: "\\uFEFF"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_escaped_non_printable_strings_remain_quoted_2(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped non printable strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = 'value: "\\uFFFE"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'value: "\\uFFFE"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_escaped_non_printable_strings_remain_quoted_3(run, workdir):
    """CATCHES: reimplementations that break "yaml escaped non printable strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = 'value: "\\uFFFF"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'value: "\\uFFFF"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_existing_folded_prose_scalars_are_rewrapped(run, workdir):
    """CATCHES: reimplementations that break "yaml existing folded prose scalars are rewrapped" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'description: >-\n'
        '  This is a folded scalar with enough words to rewrap into several shorter lines\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '38'], input=stdin)
    assert result.stdout == (RES / 'yaml_existing_folded_prose_scalars_are_rewrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_explicit_core_scalar_tags_are_normalized_when_safe(run, workdir):
    """CATCHES: reimplementations that break "yaml explicit core scalar tags are normalized when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'flag: !!bool TRUE\n'
        'empty: !!null ~\n'
        'name: !!str true\n'
        'tabbed: !!str a\tb\n'
        'items: [!!bool FALSE, !!null Null, !!str false]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_explicit_core_scalar_tags_are_normalized_when_safe.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_explicit_core_scalar_tags_normalize_quoted_values_when_safe(run, workdir):
    """CATCHES: reimplementations that break "yaml explicit core scalar tags normalize quoted values when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'flag: !!bool "TRUE"\n'
        'empty: !!null "~"\n'
        'count: !!int "42"\n'
        'ratio: !!float "1.5"\n'
        'name: !!str "true"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_explicit_core_scalar_tags_normalize_quoted_values_when_safe.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_generated_quotes_prefer_fewer_escapes(run, workdir):
    """CATCHES: reimplementations that break "yaml generated quotes prefer fewer escapes" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'values:\n'
        "  - a'b, c\n"
        '  - a"b, c\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'values: ["a\'b, c", \'a"b, c\']\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_explicit_string_tagged_quoted_prose_scalars_are_folded_and_wrapped(run, workdir):
    """CATCHES: reimplementations that break "yaml explicit string tagged quoted prose scalars are folded and wrapped" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'description: !!str "This is a long prose scalar with enough words to fold into a block scalar safely"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '42'], input=stdin)
    assert result.stdout == (RES / 'yaml_explicit_string_tagged_quoted_prose_scalars_are_folded_and_wrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_indicator_prefixed_escaped_strings_use_unquoted_width(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed escaped strings use unquoted width" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '["\\x3aworkspace"]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '12'], input=stdin)
    assert result.stdout == b'[:workspace]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_indicator_prefixed_strings_stay_plain_when_safe_1(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed strings stay plain when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'extends: :workspace\n'
        'name: app\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '120'],
        input=stdin,
    )
    assert result.stdout == b'{extends: :workspace, name: app}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_indicator_prefixed_strings_stay_plain_when_safe_2(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed strings stay plain when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = '{extends: :workspace, name: app}\n'
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '120'],
        input=stdin,
    )
    assert result.stdout == b'{extends: :workspace, name: app}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', '--line-width', '120', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_indicator_prefixed_strings_stay_plain_when_safe_3(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed strings stay plain when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = '[":workspace", \'?query\', "-option"]\n'
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '120'],
        input=stdin,
    )
    assert result.stdout == b'[:workspace, ?query, -option]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_indicator_prefixed_strings_stay_plain_when_safe_4(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed strings stay plain when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = '{":workspace": value, "?query": result}\n'
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '120'],
        input=stdin,
    )
    assert result.stdout == b'{:workspace: value, ?query: result}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_indicator_prefixed_strings_stay_plain_when_safe_5(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed strings stay plain when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = '{:workspace: value, ?query: result}\n'
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '120'],
        input=stdin,
    )
    assert result.stdout == b'{:workspace: value, ?query: result}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', '--line-width', '120', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_indicator_prefixed_strings_stay_plain_when_safe_6(run, workdir):
    """CATCHES: reimplementations that break "yaml indicator prefixed strings stay plain when safe" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = '["?", "-", ": value", "? value", "- value"]\n'
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '120'],
        input=stdin,
    )
    assert result.stdout == b'["?", "-", ": value", "? value", "- value"]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', '--line-width', '120', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_inline_comments_are_metadata_not_scalar_content(run, workdir):
    """CATCHES: reimplementations that break "yaml inline comments are metadata not scalar content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: skip\n'
        'root: # keep root with child\n'
        '  child:    value\n'
        'other: [ one ,  two ] # keep flow comment\n'
        'items:\n'
        '- item # keep scalar comment\n'
        '- # keep empty item comment\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_inline_comments_are_metadata_not_scalar_content.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_later_document_line_leading_fe_ff_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml later document line leading fe ff is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'first:    one\n'
        '---\n'
        '\ufeffsecond:    two\n'
        'after: y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_later_document_line_leading_fe_ff_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_literal_block_conversion_uses_configured_indent_indicator(run, workdir):
    """CATCHES: reimplementations that break "yaml literal block conversion uses configured indent indicator" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'outer:\n'
        '  text: "\\x20first\\nsecond"\n'
    )
    result = run(['format', '--indent-width', '4', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_literal_block_conversion_uses_configured_indent_indicator.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_literal_block_conversion_uses_indent_indicator_for_leading_spaces(run, workdir):
    """CATCHES: reimplementations that break "yaml literal block conversion uses indent indicator for leading spaces" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'mixed: "\\u0020\\u0020first\\nsecond"\n'
        'both: "\\u0020\\u0020first\\n\\u0020\\u0020second"\n'
        'escape_heavy: "\\u0020\\u0020{\\"python\\":\\"print(\\u0027hello\\u0027)\\"}"\n'
        'nested:\n'
        '  - value: "\\u0020\\u0020first\\nsecond"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_literal_block_conversion_uses_indent_indicator_for_leading_spaces.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_long_safe_prose_scalars_are_folded_and_wrapped(run, workdir):
    """CATCHES: reimplementations that break "yaml long safe prose scalars are folded and wrapped" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'description: This is a long prose scalar with enough words to fold into a block scalar safely\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '42'], input=stdin)
    assert result.stdout == (RES / 'yaml_long_safe_prose_scalars_are_folded_and_wrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_long_safe_quoted_prose_scalars_are_folded_and_wrapped(run, workdir):
    """CATCHES: reimplementations that break "yaml long safe quoted prose scalars are folded and wrapped" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'description: "This is a long prose scalar with enough words to fold into a block scalar safely"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '42'], input=stdin)
    assert result.stdout == (RES / 'yaml_long_safe_quoted_prose_scalars_are_folded_and_wrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_newline_only_quoted_scalar_remains_quoted(run, workdir):
    """CATCHES: reimplementations that break "yaml newline only quoted scalar remains quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'value: "\\n"\n'
        'after: after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_newline_only_quoted_scalar_remains_quoted.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_nondefault_indent_preserves_space_only_block_scalar_content(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent preserves space only block scalar content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '- |-\n'
        '  first\n'
        '   \n'
        '  last\n'
        '- after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_preserves_space_only_block_scalar_content.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_cr_only_block_scalar_body(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents cr only block scalar body" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'outer:\r'
        '  value: |-\r'
        '  \r'
        '    first\r'
        '    second\r'
        '  after: x\r'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (
        b'outer:\r'
        b'    value: |-\r'
        b'\r'
        b'        first\r'
        b'        second\r'
        b'    after: x\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_non_ascii_whitespace_is_scalar_content(run, workdir):
    """CATCHES: reimplementations that break "yaml non ascii whitespace is scalar content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'trailing: foo\xa0\n'
        'leading: \xa0foo\n'
        'core_like: \xa0null\xa0\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_non_ascii_whitespace_is_scalar_content.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_preserves_explicit_block_indent_and_space_content(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent preserves explicit block indent and space content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'outer:\n'
        '  - value: |2-\n'
        '      first\n'
        '       \n'
        '      last\n'
        '    after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_preserves_explicit_block_indent_and_space_content.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_plain_scalar_1(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline plain scalar" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
        'outer:\n'
        '  value: first line\n'
        '    second line\n'
        '    third line\n'
        '  after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_plain_scalar_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_plain_scalar_2(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline plain scalar" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        'outer:\r\n'
        '  value: first line\r\n'
        '    second line\r\n'
        '    third line\r\n'
        '  after: x\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_plain_scalar_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_plain_scalar_3(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline plain scalar" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
        'outer:\r'
        '  value: first line\r'
        '    second line\r'
        '    third line\r'
        '  after: x\r'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (
        b'outer:\r'
        b'    value: first line\r'
        b'      second line\r'
        b'      third line\r'
        b'    after: x\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_scalar_variants_1(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline scalar variants" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        'outer:\n'
        '  tagged: !tag first line\n'
        '    second line\n'
        '  anchored: &value first line\n'
        '    second line\n'
        '  after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_scalar_variants_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_scalar_variants_2(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline scalar variants" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        'outer:\n'
        '  value: first line\n'
        '    \n'
        '    third line\n'
        '  after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_scalar_variants_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_scalar_variants_3(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline scalar variants" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        'outer:\n'
        '  ? key\n'
        '  : first line\n'
        '    second line\n'
        '  after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_scalar_variants_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_multiline_scalar_variants_4(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents multiline scalar variants" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        'outer:\n'
        '  - value: first line\n'
        '      second line\n'
        '      third line\n'
        '    after: x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_multiline_scalar_variants_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nondefault_indent_reindents_nested_block_scalar_body(run, workdir):
    """CATCHES: reimplementations that break "yaml nondefault indent reindents nested block scalar body" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'outer:\n'
        '  value: |-\n'
        '    line\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'yaml_nondefault_indent_reindents_nested_block_scalar_body.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_plain_core_booleans_normalize_and_tilde_null_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml plain core booleans normalize and tilde null is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'flag: TRUE\n'
        'disabled: False\n'
        'empty: ~\n'
        'items: [ TRUE , Null ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_plain_core_booleans_normalize_and_tilde_null_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_property_only_nodes_and_commented_markers_preserve_source_spelling(run, workdir):
    """CATCHES: reimplementations that break "yaml property only nodes and commented markers preserve source spelling" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '--- # document\n'
        'root: !!str\n'
        'seq:\n'
        '  - &empty\n'
        'flow: {foo: !!str, anchored: &empty}\n'
        '... # end\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_property_only_nodes_and_commented_markers_preserve_source_spelling.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_block_scalars_preserve_exact_content_1(run, workdir):
    """CATCHES: reimplementations that break "yaml root block scalars preserve exact content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
        '|-\n'
        '  #\n'
        '  value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_root_block_scalars_preserve_exact_content_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_block_scalars_preserve_exact_content_2(run, workdir):
    """CATCHES: reimplementations that break "yaml root block scalars preserve exact content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        '|-\n'
        '  value \n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_root_block_scalars_preserve_exact_content_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_block_scalars_preserve_exact_content_3(run, workdir):
    """CATCHES: reimplementations that break "yaml root block scalars preserve exact content" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
        '!generated |-\n'
        '  value\t\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_root_block_scalars_preserve_exact_content_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_document_marker_strings_remain_quoted_1(run, workdir):
    """CATCHES: reimplementations that break "yaml root document marker strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    stdin = '"---"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'"---"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_document_marker_strings_remain_quoted_2(run, workdir):
    """CATCHES: reimplementations that break "yaml root document marker strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    stdin = '"--- x"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'"--- x"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_document_marker_strings_remain_quoted_3(run, workdir):
    """CATCHES: reimplementations that break "yaml root document marker strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    stdin = '"..."\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'"..."\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_document_marker_strings_remain_quoted_4(run, workdir):
    """CATCHES: reimplementations that break "yaml root document marker strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    stdin = '"... x"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'"... x"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_root_document_marker_strings_remain_quoted_5(run, workdir):
    """CATCHES: reimplementations that break "yaml root document marker strings remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    stdin = '--- "---"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'--- ---\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_short_folded_prose_scalars_are_rewrapped_only_in_canonical_mode_1(run, workdir):
    """CATCHES: reimplementations that break "yaml short folded prose scalars are rewrapped only in canonical mode" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'description: >\n'
        '  Manage a simple todo\n'
        '  list.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_short_folded_prose_scalars_are_rewrapped_only_in_canonical_mode_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_short_folded_prose_scalars_are_rewrapped_only_in_canonical_mode_2(run, workdir):
    """CATCHES: reimplementations that break "yaml short folded prose scalars are rewrapped only in canonical mode" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'description: >\n'
        '  Manage a simple todo\n'
        '  list.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'yaml_short_folded_prose_scalars_are_rewrapped_only_in_canonical_mode_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_strings_ending_in_colon_remain_quoted_1(run, workdir):
    """CATCHES: reimplementations that break "yaml strings ending in colon remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = '- "foo:"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'- "foo:"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_strings_ending_in_colon_remain_quoted_2(run, workdir):
    """CATCHES: reimplementations that break "yaml strings ending in colon remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = 'value: "foo:"\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'value: "foo:"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_strings_ending_in_colon_remain_quoted_3(run, workdir):
    """CATCHES: reimplementations that break "yaml strings ending in colon remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = 'items: ["foo:"]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'items: ["foo:"]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_strings_ending_in_colon_remain_quoted_4(run, workdir):
    """CATCHES: reimplementations that break "yaml strings ending in colon remain quoted" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = 'metadata: {value: "foo:"}\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'metadata: {value: "foo:"}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_tab_indentation_with_fmt_comment_in_block_scalar_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml tab indentation with fmt comment in block scalar is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'root: |\n'
        '\t# fmt: markdown\n'
        '\t#   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_tab_indentation_with_fmt_comment_in_block_scalar_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_tab_indentation_with_fmt_text_in_scalar_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml tab indentation with fmt text in scalar is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'root:\n'
        '\tchild: "this fmt: text is data"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_tab_indentation_with_fmt_text_in_scalar_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_unsafe_plain_strings_are_quoted_in_block_context(run, workdir):
    """CATCHES: reimplementations that break "yaml unsafe plain strings are quoted in block context" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = 'key:  a\tb\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'key: "a\\tb"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_utf8_bom_is_preserved_1(run, workdir):
    """CATCHES: reimplementations that break "yaml utf8 bom is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = '\ufeffname:    value\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'\xef\xbb\xbfname:    value\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_utf8_bom_is_preserved_2(run, workdir):
    """CATCHES: reimplementations that break "yaml utf8 bom is preserved" (yaml scalars); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = '\ufeffvalue\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'\xef\xbb\xbfvalue\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
