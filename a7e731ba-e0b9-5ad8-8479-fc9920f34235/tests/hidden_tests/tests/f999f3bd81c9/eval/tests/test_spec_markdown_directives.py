"""Spec markdown directives behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_markdown_active_directives_apply_to_nested_code_fences_on_first_parse(run, workdir):
    """CATCHES: reimplementations that break "markdown active directives apply to nested code fences on first parse" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: canonical=true wrap=sentence scope=from-here -->\n'
        '```markdown\n'
        'This is __strong__. This is _emphasis_.\n'
        '```\n'
        '\n'
        '```yaml\n'
        'body: !markdown |\n'
        '  This is __strong__. This is _emphasis_.\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_active_directives_apply_to_nested_code_fences_on_first_parse.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_code_fence_local_skip_accepts_scope_next(run, workdir):
    """CATCHES: reimplementations that break "markdown code fence local skip accepts scope next" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```yaml fmt: skip scope=next\n'
        'a:    1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_code_fence_local_skip_accepts_scope_next.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_code_fence_local_skip_requires_exact_supported_forms(run, workdir):
    """CATCHES: reimplementations that break "markdown code fence local skip requires exact supported forms" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```yaml fmt: skip-extra\n'
        'a:    1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_code_fence_local_skip_requires_exact_supported_forms.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_directive_errors_are_reported_1(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '<!-- fmt: -->\n'
        '# Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: invalid fmt directive: empty\n'
    assert result.returncode == 1


def test_markdown_directive_errors_are_reported_2(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '<!-- fmt: skip scope=from-here -->\n'
        '# Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: fmt: skip does not support scope=from-here\n'
    assert result.returncode == 1


def test_markdown_directive_errors_are_reported_3(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '<!-- fmt: off scope=file -->\n'
        '# Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: fmt: off does not support scope=file\n'
    assert result.returncode == 1


def test_markdown_directive_errors_are_reported_4(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '<!-- fmt: wrap=0 -->\n'
        '# Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: fmt: wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n'
    assert result.returncode == 1


def test_markdown_directive_errors_are_reported_5(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" -->\n'
        '# Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: fmt: template.delimiters requires exactly two quoted delimiter strings\n'
    assert result.returncode == 1


def test_markdown_directive_errors_are_reported_6(run, workdir):
    """CATCHES: reimplementations that break "markdown directive errors are reported" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: table -->\n'
        '| a |\n'
        '|---|\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: invalid fmt directive: table\n'
    assert result.returncode == 1


def test_markdown_directives_and_blocks(run, workdir):
    """CATCHES: reimplementations that break "markdown directives and blocks" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: canonical=true scope=file -->\n'
        'Title\n'
        '=====\n'
        'This is e.g. one sentence. This is __strong__ and _emphasis_!\n'
        '\n'
        '<!-- fmt: off -->\n'
        '#   Keep ##\n'
        '<!-- fmt: on -->\n'
        '#   Change ##\n'
        '\n'
        '   * * *\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_directives_and_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_file_scope_directives_patch_prior_markdown_code_fences(run, workdir):
    """CATCHES: reimplementations that break "markdown file scope directives patch prior markdown code fences" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```markdown\n'
        'This is __strong__ before the directive.\n'
        '```\n'
        '\n'
        '<!-- fmt: canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_file_scope_directives_patch_prior_markdown_code_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_file_scope_directives_patch_prior_rendered_blocks(run, workdir):
    """CATCHES: reimplementations that break "markdown file scope directives patch prior rendered blocks" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'This is __strong__ and _emphasis_ before the directive.\n'
        '\n'
        '<!-- fmt: canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_file_scope_directives_patch_prior_rendered_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_file_scope_directives_patch_prior_yaml_code_fence_markdown_scalars(run, workdir):
    """CATCHES: reimplementations that break "markdown file scope directives patch prior yaml code fence markdown scalars" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```yaml\n'
        'body: !markdown |\n'
        '  This is __strong__ before the directive.\n'
        '```\n'
        '\n'
        '<!-- fmt: canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_file_scope_directives_patch_prior_yaml_code_fence_markdown_scalars.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_next_directive_preserves_local_skip_code_fence_target(run, workdir):
    """CATCHES: reimplementations that break "markdown next directive preserves local skip code fence target" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        '```yaml fmt: skip\n'
        'a:    1\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_next_directive_preserves_local_skip_code_fence_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_next_format_directive_rejects_unsupported_targets_1(run, workdir):
    """CATCHES: reimplementations that break "markdown next format directive rejects unsupported targets" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        '<div>\n'
        'keep    raw\n'
        '</div>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_markdown_next_format_directive_rejects_unsupported_targets_2(run, workdir):
    """CATCHES: reimplementations that break "markdown next format directive rejects unsupported targets" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    stdin = (
        '<!-- fmt: wrap=20 scope=next -->\n'
        '- This ~~struck text keeps    spacing.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_markdown_next_format_directive_rejects_unsupported_targets_3(run, workdir):
    """CATCHES: reimplementations that break "markdown next format directive rejects unsupported targets" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    stdin = (
        '<!-- fmt: wrap=20 scope=next -->\n'
        '> This ~~struck text keeps    spacing.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_markdown_next_format_directive_rejects_unsupported_targets_4(run, workdir):
    """CATCHES: reimplementations that break "markdown next format directive rejects unsupported targets" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    stdin = (
        '<!-- fmt: wrap=20 scope=next -->\n'
        'Term\n'
        ': This ~~struck text keeps    spacing.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_markdown_next_format_directive_rejects_unsupported_targets_5(run, workdir):
    """CATCHES: reimplementations that break "markdown next format directive rejects unsupported targets" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    stdin = (
        '<!-- fmt: wrap=20 scope=next -->\n'
        'before \\LaTeX after\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_markdown_off_region_preserves_invalid_fmt_comments_until_on(run, workdir):
    """CATCHES: reimplementations that break "markdown off region preserves invalid fmt comments until on" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: off -->\n'
        '#   Keep ##\n'
        '<!-- fmt: unknown -->\n'
        '<!-- fmt: on scope=next -->\n'
        '<!-- fmt: on -->\n'
        '#   Change ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_off_region_preserves_invalid_fmt_comments_until_on.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_off_region_without_on_preserves_through_eof(run, workdir):
    """CATCHES: reimplementations that break "markdown off region without on preserves through eof" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: off -->\n'
        '<!-- fmt: on scope=next -->\n'
        '#   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_off_region_without_on_preserves_through_eof.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_skip_at_eof_is_preserved_without_error(run, workdir):
    """CATCHES: reimplementations that break "markdown skip at eof is preserved without error" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = '<!-- fmt: skip -->\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'<!-- fmt: skip -->\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_scope_next_directive_applies_to_nested_code_fence_only(run, workdir):
    """CATCHES: reimplementations that break "markdown scope next directive applies to nested code fence only" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: canonical=true scope=next -->\n'
        '```markdown\n'
        'This is __strong__.\n'
        '```\n'
        '\n'
        'This is _emphasis_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_scope_next_directive_applies_to_nested_code_fence_only.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_skip_file_short_circuits_later_invalid_fmt_comments(run, workdir):
    """CATCHES: reimplementations that break "markdown skip file short circuits later invalid fmt comments" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: skip file -->\n'
        '<!-- fmt: unknown -->\n'
        '#   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_skip_file_short_circuits_later_invalid_fmt_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_template_delimiter_directive_infers_from_here_when_isolated(run, workdir):
    """CATCHES: reimplementations that break "markdown template delimiter directive infers from here when isolated" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" ">>" -->\n'
        '\n'
        'This << keep   spacing >> paragraph.\n'
        '\n'
        'Another << keep   spacing >> paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_template_delimiter_directive_infers_from_here_when_isolated.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_template_delimiter_directive_requires_unambiguous_implicit_scope(run, workdir):
    """CATCHES: reimplementations that break "markdown template delimiter directive requires unambiguous implicit scope" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        'Intro paragraph.\n'
        '<!-- fmt: template.delimiters "<<" ">>" -->\n'
        '\n'
        'This << keep   spacing >> paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:6: error: fmt: template.delimiters needs explicit scope\n'
    assert result.returncode == 1


def test_markdown_template_delimiter_directives_accept_spaces_and_escapes_1(run, workdir):
    """CATCHES: reimplementations that break "markdown template delimiter directives accept spaces and escapes" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '<!-- fmt: template.delimiters "<< open" "close >>" -->\n'
        'This << open keep   spacing close >> paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_template_delimiter_directives_accept_spaces_and_escapes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_template_delimiter_directives_accept_spaces_and_escapes_2(run, workdir):
    """CATCHES: reimplementations that break "markdown template delimiter directives accept spaces and escapes" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '<!-- fmt: template.delimiters "[\\"" "\\"]" -->\n'
        'This [" keep   spacing "] paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_template_delimiter_directives_accept_spaces_and_escapes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_template_state_applies_inside_recursive_code_fences(run, workdir):
    """CATCHES: reimplementations that break "markdown template state applies inside recursive code fences" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" ">>" scope=from-here -->\n'
        '```markdown\n'
        '#   << keep   this >> ##\n'
        '```\n'
        '\n'
        '```yaml\n'
        'body: !markdown |\n'
        '  #   << keep   this >> ##\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'markdown_template_state_applies_inside_recursive_code_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_nested_markdown_template_delimiter_directive_infers_from_here_at_range_start(run, workdir):
    """CATCHES: reimplementations that break "nested markdown template delimiter directive infers from here at range start" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```markdown\n'
        '<!-- fmt: template.delimiters "<<" ">>" -->\n'
        '\n'
        'This << keep   spacing >> paragraph.\n'
        '\n'
        'Another << keep   spacing >> paragraph.\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'nested_markdown_template_delimiter_directive_infers_from_here_at_range_start.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unknown_markdown_html_fmt_directives_error(run, workdir):
    """CATCHES: reimplementations that break "unknown markdown html fmt directives error" (markdown directives); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '<!-- fmt: unknown -->\n'
        '# Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:6: error: invalid fmt directive: unknown\n'
    assert result.returncode == 1
