"""Spec yaml directives behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_yaml_bom_prefixed_opaque_root_rejects_same_line_directives(run, workdir):
    """CATCHES: reimplementations that break "yaml bom prefixed opaque root rejects same line directives" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '\ufeff- value # fmt: skip\n'
        '- next\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:1: error: formatting this BOM-prefixed YAML root is unsupported\n'
    assert result.returncode == 1


def test_yaml_compact_directive_accepts_existing_flow_collection_target(run, workdir):
    """CATCHES: reimplementations that break "yaml compact directive accepts existing flow collection target" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: compact\n'
        'flow: [ one ,  two]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_compact_directive_accepts_existing_flow_collection_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_broad_markdown_scope_sets_options_without_marking_unmarked_scalars(run, workdir):
    """CATCHES: reimplementations that break "yaml broad markdown scope sets options without marking unmarked scalars" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown canonical=true scope=file\n'
        'plain: "This is __not__ markdown."\n'
        '# fmt: markdown\n'
        'body: "This is __strong__."\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_broad_markdown_scope_sets_options_without_marking_unmarked_scalars.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_directive_errors_are_reported_1(run, workdir):
    """CATCHES: reimplementations that break "yaml directive errors are reported" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '# fmt:\n'
        'a: b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:1: error: invalid fmt directive: empty\n'
    assert result.returncode == 1


def test_yaml_directive_errors_are_reported_2(run, workdir):
    """CATCHES: reimplementations that break "yaml directive errors are reported" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '# fmt: off\n'
        '# fmt: off\n'
        'a:    b\n'
        '# fmt: on\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:2:1: error: nested fmt: off\n'
    assert result.returncode == 1


def test_yaml_directive_errors_are_reported_3(run, workdir):
    """CATCHES: reimplementations that break "yaml directive errors are reported" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '# fmt: skip scope=from-here\n'
        'a: b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:1: error: fmt: skip does not support scope=from-here\n'
    assert result.returncode == 1


def test_yaml_directive_errors_are_reported_4(run, workdir):
    """CATCHES: reimplementations that break "yaml directive errors are reported" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '# fmt: template.delimiters "<<" ">>"\n'
        '# ordinary\n'
        'value: << keep >>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:1: error: fmt: template.delimiters needs explicit scope\n'
    assert result.returncode == 1


def test_yaml_directive_errors_are_reported_5(run, workdir):
    """CATCHES: reimplementations that break "yaml directive errors are reported" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '# fmt: custom\n'
        'body: |\n'
        '  inline\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:1: error: unknown embedded formatter: custom\n'
    assert result.returncode == 1


def test_yaml_directive_errors_are_reported_6(run, workdir):
    """CATCHES: reimplementations that break "yaml directive errors are reported" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'name: value # fmt: skip\n'
        'next: value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:1:13: error: fmt directive is not supported in this position\n'
    assert result.returncode == 1


def test_yaml_empty_markdown_scalars_emit_empty_string(run, workdir):
    """CATCHES: reimplementations that break "yaml empty markdown scalars emit empty string" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'body:\n'
        'empty: !markdown |\n'
        'tag_only: !markdown\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_empty_markdown_scalars_emit_empty_string.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_compact_directive_collapses_next_collection_target(run, workdir):
    """CATCHES: reimplementations that break "yaml compact directive collapses next collection target" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'root:\n'
        '  # fmt: compact\n'
        '  nested:\n'
        '    name: yamark\n'
        '    language: rust\n'
        '  keep:\n'
        '    name: unchanged\n'
        '    language: yaml\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_compact_directive_collapses_next_collection_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_file_scope_directives_patch_prior_ast_nodes(run, workdir):
    """CATCHES: reimplementations that break "yaml file scope directives patch prior ast nodes" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !markdown |\n'
        '  << keep   spacing >>\n'
        'items:\n'
        '  - one\n'
        '  - two\n'
        '\n'
        '# fmt: template.delimiters "<<" ">>" scope=file\n'
        '# fmt: compact scope=file\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_file_scope_directives_patch_prior_ast_nodes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_flow_collections_with_active_template_spans_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml flow collections with active template spans are preserved" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: template.delimiters "<<" ">>" scope=file\n'
        'a: [<< a,b >>]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_flow_collections_with_active_template_spans_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_file_scope_markdown_options_patch_prior_markdown_scalars(run, workdir):
    """CATCHES: reimplementations that break "yaml file scope markdown options patch prior markdown scalars" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !markdown |\n'
        '  This is __strong__ before the directive.\n'
        '# fmt: markdown\n'
        'other: |\n'
        '  This is __marked__ before the directive.\n'
        '\n'
        '# fmt: markdown canonical=true scope=file\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'yaml_file_scope_markdown_options_patch_prior_markdown_scalars.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_hugo_shortcode_like_scalars_are_template_spans(run, workdir):
    """CATCHES: reimplementations that break "yaml hugo shortcode like scalars are template spans" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'template: "{{< keep   this >}}"\n'
        'tags: [docs,yaml]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_hugo_shortcode_like_scalars_are_template_spans.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_inline_markdown_scalar_is_converted_to_literal_block(run, workdir):
    """CATCHES: reimplementations that break "yaml inline markdown scalar is converted to literal block" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown wrap=sentence canonical=true\n'
        'body: This is __strong__. This is _emphasis_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_inline_markdown_scalar_is_converted_to_literal_block.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_inline_markdown_scalar_uses_dominant_line_ending_without_final_newline(run, workdir):
    """CATCHES: reimplementations that break "yaml inline markdown scalar uses dominant line ending without final newline" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown wrap=none\r\n'
        'body: This is __strong__ text.'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_inline_markdown_scalar_uses_dominant_line_ending_without_final_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_markdown_directive_rejects_alias_targets(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown directive rejects alias targets" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'anchor: &anchor value\n'
        '# fmt: markdown\n'
        'body: *anchor\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:3:7: error: fmt: markdown targets a scalar value\n'
    assert result.returncode == 1


def test_yaml_inline_markdown_scalars_use_decoded_scalar_values(run, workdir):
    """CATCHES: reimplementations that break "yaml inline markdown scalars use decoded scalar values" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown wrap=none canonical=true\n'
        'body: "This is __strong__ text."\n'
        'empty: !markdown ""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_inline_markdown_scalars_use_decoded_scalar_values.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_markdown_block_scalars_reindent_formatted_paragraphs(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown block scalars reindent formatted paragraphs" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !markdown |\n'
        '  This   paragraph has enough words to wrap across lines and keep YAML indentation.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', '28'], input=stdin)
    assert result.stdout == (RES / 'yaml_markdown_block_scalars_reindent_formatted_paragraphs.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_markdown_directive_rejects_explicit_block_scalar_keys(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown directive rejects explicit block scalar keys" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        '? |\n'
        '  key\n'
        ': value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:2:1: error: fmt: markdown targets a scalar value\n'
    assert result.returncode == 1


def test_yaml_markdown_directive_rejects_flow_collection_targets(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown directive rejects flow collection targets" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'items: [one, two]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:2:8: error: fmt: markdown targets a scalar value\n'
    assert result.returncode == 1


def test_yaml_markdown_folded_scalars_are_emitted_as_literal_blocks(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown folded scalars are emitted as literal blocks" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !markdown >\n'
        '  #   Title ##\n'
        '  This is __strong__.\n'
        '\n'
        '# fmt: markdown wrap=none\n'
        'other: >\n'
        '  A paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'yaml_markdown_folded_scalars_are_emitted_as_literal_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_markdown_scalar_template_delimiter_directive_infers_from_here_at_range_start(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown scalar template delimiter directive infers from here at range start" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !markdown |\n'
        '  <!-- fmt: template.delimiters "<<" ">>" -->\n'
        '\n'
        '  This << keep   spacing >> paragraph.\n'
        '\n'
        '  Another << keep   spacing >> paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'yaml_markdown_scalar_template_delimiter_directive_infers_from_here_at_range_start.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_markdown_tag_formats_block_scalar(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown tag formats block scalar" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !markdown |\n'
        '  #   Title ##\n'
        '  This is __strong__. This is _emphasis_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'yaml_markdown_tag_formats_block_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_markdown_template_flow_and_table_directives(run, workdir):
    """CATCHES: reimplementations that break "yaml markdown template flow and table directives" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown wrap=none\n'
        'body: |\n'
        '  #   Title ##\n'
        '  text\n'
        '\n'
        '# fmt: template.delimiters "<<" ">>"\n'
        'value: "<< keep   this >>"\n'
        '\n'
        '# fmt: table\n'
        '- {name: a, type: int}\n'
        '- {name: long_name, type: string}\n'
        '\n'
        'flow: [ one ,  two]\n'
        'map: { a : b , long : value }\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_markdown_template_flow_and_table_directives.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_md_tag_formats_block_scalar(run, workdir):
    """CATCHES: reimplementations that break "yaml md tag formats block scalar" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'body: !md |\n'
        '  #   Title ##\n'
        '  This is __strong__. This is _emphasis_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'yaml_md_tag_formats_block_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_nested_markdown_block_scalar_header_comments_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml nested markdown block scalar header comments are preserved" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'body: | # markdown\n'
        '  #   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'yaml_nested_markdown_block_scalar_header_comments_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_option_only_markdown_directive_defaults_to_next_scope(run, workdir):
    """CATCHES: reimplementations that break "yaml option only markdown directive defaults to next scope" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: canonical=true\n'
        'first: !markdown "This is __strong__."\n'
        'second: !markdown "This is __strong__."\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'yaml_option_only_markdown_directive_defaults_to_next_scope.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_same_line_table_directive_targets_empty_parent_sequence(run, workdir):
    """CATCHES: reimplementations that break "yaml same line table directive targets empty parent sequence" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'items: # fmt: table\n'
        '  - {name: a, type: int}\n'
        '  - {name: long_name, type: string}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_same_line_table_directive_targets_empty_parent_sequence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_tab_indentation_after_unrelated_file_scope_directive_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml tab indentation after unrelated file scope directive is preserved" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: compact scope=file\n'
        'items:\n'
        '  - a\n'
        '  - b\n'
        '\troot:\n'
        '\t  child: value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_tab_indentation_after_unrelated_file_scope_directive_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_tab_indentation_rejects_active_scalar_directive_target(run, workdir):
    """CATCHES: reimplementations that break "yaml tab indentation rejects active scalar directive target" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: markdown\n'
        'key:\n'
        '\tchild: value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:3:1: error: tabs in YAML indentation are unsupported\n'
    assert result.returncode == 1


def test_yaml_tab_indentation_with_preservation_directive_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml tab indentation with preservation directive is preserved" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: skip\n'
        'root:\n'
        '\tchild: value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_tab_indentation_with_preservation_directive_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_tab_indentation_without_directives_is_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml tab indentation without directives is preserved" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '\tname: value\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'\tname: value\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_table_directive_flow_sequence_targets_are_preserved(run, workdir):
    """CATCHES: reimplementations that break "yaml table directive flow sequence targets are preserved" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: table\n'
        '[{name: a,type: int}]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_table_directive_flow_sequence_targets_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_table_directives_align_supported_row_comments(run, workdir):
    """CATCHES: reimplementations that break "yaml table directives align supported row comments" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: table\n'
        '- {name: a, type: int} # first\n'
        '- {name: long_name, type: string} # second\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_table_directives_align_supported_row_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_table_directives_wait_for_sequence_targets(run, workdir):
    """CATCHES: reimplementations that break "yaml table directives wait for sequence targets" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: table\n'
        'note:    keep\n'
        'rows:\n'
        '  - {name: a, type: int}\n'
        '  - {name: long_name, type: string}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_table_directives_wait_for_sequence_targets.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_table_directives_without_sequence_targets_error_1(run, workdir):
    """CATCHES: reimplementations that break "yaml table directives without sequence targets error" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: table\n'
        'name: value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:2:12: error: fmt: table has no target\n'
    assert result.returncode == 1


def test_yaml_table_directives_without_sequence_targets_error_2(run, workdir):
    """CATCHES: reimplementations that break "yaml table directives without sequence targets error" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: compact table\n'
        'name: value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:2:12: error: fmt: compact table has no target\n'
    assert result.returncode == 1


def test_yaml_template_delimiter_directives_accept_spaces_and_escapes_1(run, workdir):
    """CATCHES: reimplementations that break "yaml template delimiter directives accept spaces and escapes" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# fmt: template.delimiters "<< open" "close >>"\n'
        'value: "<< open keep   this close >>"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_template_delimiter_directives_accept_spaces_and_escapes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_template_delimiter_directives_accept_spaces_and_escapes_2(run, workdir):
    """CATCHES: reimplementations that break "yaml template delimiter directives accept spaces and escapes" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# fmt: template.delimiters "[\\"" "\\"]"\n'
        'value: \'[" keep   this "]\'\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_template_delimiter_directives_accept_spaces_and_escapes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_yaml_template_span_preserves_only_unsafe_scalar(run, workdir):
    """CATCHES: reimplementations that break "yaml template span preserves only unsafe scalar" (yaml directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'title:    Test\n'
        'template: "{{ keep   this }}"\n'
        'tags: [docs,yaml]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'yaml_template_span_preserves_only_unsafe_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
