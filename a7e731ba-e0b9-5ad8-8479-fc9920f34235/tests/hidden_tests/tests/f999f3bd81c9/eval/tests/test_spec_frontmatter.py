"""Spec frontmatter behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_frontmatter_editor_options_markdown_does_not_merge_editor_markdown_keys(run, workdir):
    """CATCHES: reimplementations that break "frontmatter editor options markdown does not merge editor markdown keys" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: none\n'
        'editor:\n'
        '  markdown:\n'
        '    canonical: true\n'
        '---\n'
        'This is __strong__.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_editor_options_markdown_does_not_merge_editor_markdown_keys.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_cli_preserve_footnotes_overrides_frontmatter_footnote_formatting(run, workdir):
    """CATCHES: reimplementations that break "cli preserve footnotes overrides frontmatter footnote formatting" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    footnotes: wrap\n'
        '---\n'
        '[^note]: keep   spacing. Keep one line.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', '20', '--preserve-footnotes'],
        input=stdin,
    )
    assert result.stdout == (RES / 'cli_preserve_footnotes_overrides_frontmatter_footnote_formatting.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', '--preserve-footnotes', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_closing_marker_ignores_indented_block_scalar_lines(run, workdir):
    """CATCHES: reimplementations that break "frontmatter closing marker ignores indented block scalar lines" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'description: |\n'
        '  ---\n'
        '  body\n'
        '---\n'
        '#   Title ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_closing_marker_ignores_indented_block_scalar_lines.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_editor_options_markdown_overrides_editor_markdown(run, workdir):
    """CATCHES: reimplementations that break "frontmatter editor options markdown overrides editor markdown" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: none\n'
        'editor:\n'
        '  markdown:\n'
        '    wrap: sentence\n'
        '---\n'
        'This is one sentence. This is another sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_editor_options_markdown_overrides_editor_markdown.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_markdown_options_only_use_supported_paths(run, workdir):
    """CATCHES: reimplementations that break "frontmatter markdown options only use supported paths" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'params:\n'
        '  wrap: sentence\n'
        '---\n'
        'This is one sentence. This is another sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_markdown_options_only_use_supported_paths.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_options_drive_markdown_body(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options drive markdown body" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'title:    Test\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: sentence\n'
        '    canonical: true\n'
        '---\n'
        'This is __strong__. This is _emphasis_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_drive_markdown_body.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_options_drive_recursive_code_fence_markdown(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options drive recursive code fence markdown" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: sentence\n'
        '    canonical: true\n'
        '---\n'
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
    assert result.stdout == (RES / 'frontmatter_options_drive_recursive_code_fence_markdown.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_skip_file_preserves_entire_markdown_document(run, workdir):
    """CATCHES: reimplementations that break "frontmatter skip file preserves entire markdown document" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        '# fmt: skip file\n'
        'title:    Test\n'
        '---\n'
        '#   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_skip_file_preserves_entire_markdown_document.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_skip_file_short_circuits_later_invalid_markdown_directives(run, workdir):
    """CATCHES: reimplementations that break "frontmatter skip file short circuits later invalid markdown directives" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        '# fmt: skip file\n'
        'title:    Test\n'
        '---\n'
        '<!-- fmt: unknown -->\n'
        '#   Keep ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_skip_file_short_circuits_later_invalid_markdown_directives.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_template_delimiter_directive_infers_from_here_at_range_start(run, workdir):
    """CATCHES: reimplementations that break "frontmatter template delimiter directive infers from here at range start" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        '# fmt: template.delimiters "<<" ">>"\n'
        '\n'
        'title: "<< keep   this >>"\n'
        '---\n'
        'Body.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_template_delimiter_directive_infers_from_here_at_range_start.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_template_span_preserves_only_unsafe_yaml_scalar(run, workdir):
    """CATCHES: reimplementations that break "frontmatter template span preserves only unsafe yaml scalar" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'title:    Test\n'
        'template: "{{ keep   this }}"\n'
        'tags: [docs,frontmatter]\n'
        '---\n'
        '#   Body ##\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_template_span_preserves_only_unsafe_yaml_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_wrapper_markers_are_normalized(run, workdir):
    """CATCHES: reimplementations that break "frontmatter wrapper markers are normalized" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---   \n'
        'title:    Test\n'
        '---   \n'
        'Body.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_wrapper_markers_are_normalized.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_front_matter_preserves_block_scalar_trailing_spaces(run, workdir):
    """CATCHES: reimplementations that break "markdown front matter preserves block scalar trailing spaces" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '---\n'
        'value: |\n'
        '  first \n'
        '   second \n'
        '  third\n'
        '---\n'
        '\n'
        'Body.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_front_matter_preserves_block_scalar_trailing_spaces.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_front_matter_uses_yaml_scalar_safety_1(run, workdir):
    """CATCHES: reimplementations that break "markdown front matter uses yaml scalar safety" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '---\n'
        '"---"\n'
        '---\n'
        '\n'
        'Body.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_front_matter_uses_yaml_scalar_safety_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_front_matter_uses_yaml_scalar_safety_2(run, workdir):
    """CATCHES: reimplementations that break "markdown front matter uses yaml scalar safety" (frontmatter); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '---\n'
        'mixed: "\\u0020\\u0020first\\nsecond"\n'
        'colon: "foo:"\n'
        '---\n'
        '\n'
        'Body.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'markdown_front_matter_uses_yaml_scalar_safety_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
