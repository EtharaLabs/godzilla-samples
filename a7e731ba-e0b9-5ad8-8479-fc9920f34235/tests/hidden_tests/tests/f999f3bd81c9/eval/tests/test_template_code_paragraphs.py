"""Template code paragraphs behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_ambiguous_math_boundaries_do_not_enable_template_reflow_1(run, workdir):
    """CATCHES: reimplementations that break "ambiguous math boundaries do not enable template reflow" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        'with `{{ foo }}` and $a \\$ [x](  url  ) _math_$. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_math_boundaries_do_not_enable_template_reflow_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_math_boundaries_do_not_enable_template_reflow_2(run, workdir):
    """CATCHES: reimplementations that break "ambiguous math boundaries do not enable template reflow" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        'with `{{ foo }}` and $a \\$ [x](  url  ) _math_$. After\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'ambiguous_math_boundaries_do_not_enable_template_reflow_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_math_boundaries_do_not_enable_template_reflow_3(run, workdir):
    """CATCHES: reimplementations that break "ambiguous math boundaries do not enable template reflow" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        'with `{{ foo }}` and $a \\$ [x](  url  ) _math_$. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_math_boundaries_do_not_enable_template_reflow_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '24', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_math_boundaries_do_not_enable_template_reflow_4(run, workdir):
    """CATCHES: reimplementations that break "ambiguous math boundaries do not enable template reflow" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        'with $$`{{ foo }}`$$. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_math_boundaries_do_not_enable_template_reflow_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_math_boundaries_do_not_enable_template_reflow_5(run, workdir):
    """CATCHES: reimplementations that break "ambiguous math boundaries do not enable template reflow" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        'with $$`{{ foo }}`$$. After\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'ambiguous_math_boundaries_do_not_enable_template_reflow_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_math_boundaries_do_not_enable_template_reflow_6(run, workdir):
    """CATCHES: reimplementations that break "ambiguous math boundaries do not enable template reflow" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        'with $$`{{ foo }}`$$. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_math_boundaries_do_not_enable_template_reflow_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '24', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph_1(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` and {{ outside }} after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph_2(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo` and `bar }}` after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:16'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph_3(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }} after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph_4(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        '_with `{{ foo }}` inside_ after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph_5(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        '[link](target){key="`{{ foo }}`"} after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ambiguous_or_non_code_templates_keep_the_original_paragraph_6(run, workdir):
    """CATCHES: reimplementations that break "ambiguous or non code templates keep the original paragraph" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` <http://example.com> after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'ambiguous_or_non_code_templates_keep_the_original_paragraph_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_code_templates_respect_explicit_hard_breaks_1(run, workdir):
    """CATCHES: reimplementations that break "code templates respect explicit hard breaks" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        'Before\n'
        '`{{ foo }}`  \n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'code_templates_respect_explicit_hard_breaks_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_code_templates_respect_explicit_hard_breaks_2(run, workdir):
    """CATCHES: reimplementations that break "code templates respect explicit hard breaks" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        'Before\n'
        '`{{ foo }}` \\\n'
        'after [real](target).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'code_templates_respect_explicit_hard_breaks_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_code_templates_respect_explicit_hard_breaks_3(run, workdir):
    """CATCHES: reimplementations that break "code templates respect explicit hard breaks" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        'Before\n'
        '`{{ foo }}`  \n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'code_templates_respect_explicit_hard_breaks_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_code_templates_respect_explicit_hard_breaks_4(run, workdir):
    """CATCHES: reimplementations that break "code templates respect explicit hard breaks" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        'Before `{{ foo }}` \\\n'
        'after [real](target).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'code_templates_respect_explicit_hard_breaks_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_complete_code_templates_use_normal_paragraph_options_1(run, workdir):
    """CATCHES: reimplementations that break "complete code templates use normal paragraph options" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        'with `${{ foo }} [x](  url  ) _literal_`. After\n'
        '[real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'complete_code_templates_use_normal_paragraph_options_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_code_templates_use_normal_paragraph_options_2(run, workdir):
    """CATCHES: reimplementations that break "complete code templates use normal paragraph options" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        'with `{% foo %} [x](  url  ) _literal_`. After\n'
        '[real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'complete_code_templates_use_normal_paragraph_options_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_code_templates_use_normal_paragraph_options_3(run, workdir):
    """CATCHES: reimplementations that break "complete code templates use normal paragraph options" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        'with `<% foo %> [x](  url  ) _literal_`. After\n'
        '[real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'complete_code_templates_use_normal_paragraph_options_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_code_templates_use_normal_paragraph_options_4(run, workdir):
    """CATCHES: reimplementations that break "complete code templates use normal paragraph options" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        'with `{{ one }} {{ two }}` and `{{ three }}`. After\n'
        '[real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'complete_code_templates_use_normal_paragraph_options_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_code_templates_use_normal_paragraph_options_5(run, workdir):
    """CATCHES: reimplementations that break "complete code templates use normal paragraph options" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        'with ```{{ foo }} `` [x](  url  ) _literal_```. After\n'
        '[real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'complete_code_templates_use_normal_paragraph_options_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_code_templates_use_normal_paragraph_options_6(run, workdir):
    """CATCHES: reimplementations that break "complete code templates use normal paragraph options" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
        'Before\n'
        'with `[[ foo ]] [x](  url  ) _literal_`. After\n'
        '[real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'complete_code_templates_use_normal_paragraph_options_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_containers_reflow_while_heading_guards_remain_1(run, workdir):
    """CATCHES: reimplementations that break "containers reflow while heading guards remain" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '# Before `{{ foo }}` after [real](  target  ).\n'
        '\n'
        'Following\n'
        'paragraph. Next\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'containers_reflow_while_heading_guards_remain_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_containers_reflow_while_heading_guards_remain_2(run, workdir):
    """CATCHES: reimplementations that break "containers reflow while heading guards remain" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '# Before `{{ foo }}` after [real](  target  ).\n'
        '\n'
        'Following paragraph.\n'
        'Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'containers_reflow_while_heading_guards_remain_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_containers_reflow_while_heading_guards_remain_3(run, workdir):
    """CATCHES: reimplementations that break "containers reflow while heading guards remain" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '- Before `{{ foo }}` after [real](  target  ).\n'
        '\n'
        'Following\n'
        'paragraph. Next\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'containers_reflow_while_heading_guards_remain_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_containers_reflow_while_heading_guards_remain_4(run, workdir):
    """CATCHES: reimplementations that break "containers reflow while heading guards remain" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '> Before `{{ foo }}` after [real](  target  ).\n'
        '\n'
        'Following\n'
        'paragraph. Next\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'containers_reflow_while_heading_guards_remain_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_containers_reflow_while_heading_guards_remain_5(run, workdir):
    """CATCHES: reimplementations that break "containers reflow while heading guards remain" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '> Before `{{ foo }}` after [real](target).\n'
        '\n'
        'Following paragraph.\n'
        'Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'containers_reflow_while_heading_guards_remain_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_containers_reflow_while_heading_guards_remain_6(run, workdir):
    """CATCHES: reimplementations that break "containers reflow while heading guards remain" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '[^note]: Before `{{ foo }}` after [real](  target  ).\n'
        '\n'
        'Following\n'
        'paragraph. Next\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'containers_reflow_while_heading_guards_remain_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_angles_and_consumed_links_do_not_open_code_1(run, workdir):
    """CATCHES: reimplementations that break "escaped angles and consumed links do not open code" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` with \\< value. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_angles_and_consumed_links_do_not_open_code_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_angles_and_consumed_links_do_not_open_code_2(run, workdir):
    """CATCHES: reimplementations that break "escaped angles and consumed links do not open code" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before `{{ foo }}` with \\< value.\n'
        'After sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_angles_and_consumed_links_do_not_open_code_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_escaped_angles_and_consumed_links_do_not_open_code_3(run, workdir):
    """CATCHES: reimplementations that break "escaped angles and consumed links do not open code" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` with [a](  <target>  ). After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_angles_and_consumed_links_do_not_open_code_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_angles_and_consumed_links_do_not_open_code_4(run, workdir):
    """CATCHES: reimplementations that break "escaped angles and consumed links do not open code" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before `{{ foo }}` with [a](<target>).\n'
        'After sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_angles_and_consumed_links_do_not_open_code_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_escaped_angles_and_consumed_links_do_not_open_code_5(run, workdir):
    """CATCHES: reimplementations that break "escaped angles and consumed links do not open code" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` with [a](  `target  ). After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_angles_and_consumed_links_do_not_open_code_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_angles_and_consumed_links_do_not_open_code_6(run, workdir):
    """CATCHES: reimplementations that break "escaped angles and consumed links do not open code" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before `{{ foo }}` with [a](`target).\n'
        'After sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'escaped_angles_and_consumed_links_do_not_open_code_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_configured_delimiters_and_replacements_keep_their_meaning_1(run, workdir):
    """CATCHES: reimplementations that break "configured delimiters and replacements keep their meaning" (template code paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        'with `[[ foo ]]`. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'configured_delimiters_and_replacements_keep_their_meaning_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_configured_delimiters_and_replacements_keep_their_meaning_2(run, workdir):
    """CATCHES: reimplementations that break "configured delimiters and replacements keep their meaning" (template code paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before with `[[ foo ]]`.\n'
        'After sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'configured_delimiters_and_replacements_keep_their_meaning_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_configured_delimiters_and_replacements_keep_their_meaning_3(run, workdir):
    """CATCHES: reimplementations that break "configured delimiters and replacements keep their meaning" (template code paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        'with `{{ foo }}` [[ outside ]]. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'configured_delimiters_and_replacements_keep_their_meaning_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_configured_delimiters_and_replacements_keep_their_meaning_4(run, workdir):
    """CATCHES: reimplementations that break "configured delimiters and replacements keep their meaning" (template code paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "replace_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        'with `[[ foo ]]` and {{ ordinary }}. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'configured_delimiters_and_replacements_keep_their_meaning_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_configured_delimiters_and_replacements_keep_their_meaning_5(run, workdir):
    """CATCHES: reimplementations that break "configured delimiters and replacements keep their meaning" (template code paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "replace_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before with `[[ foo ]]` and {{ ordinary }}.\n'
        'After sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'configured_delimiters_and_replacements_keep_their_meaning_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_configured_delimiters_and_replacements_keep_their_meaning_6(run, workdir):
    """CATCHES: reimplementations that break "configured delimiters and replacements keep their meaning" (template code paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'replace_delimiters = []\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        'with {{ ordinary }}. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'configured_delimiters_and_replacements_keep_their_meaning_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_explicit_targets_keep_other_rejections_and_skip_precedence_1(run, workdir):
    """CATCHES: reimplementations that break "explicit targets keep other rejections and skip precedence" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before `{{ foo }}` < value.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_explicit_targets_keep_other_rejections_and_skip_precedence_2(run, workdir):
    """CATCHES: reimplementations that break "explicit targets keep other rejections and skip precedence" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '<!-- fmt: skip file -->\n'
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before `{{ foo }}` < value.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'explicit_targets_keep_other_rejections_and_skip_precedence_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_targets_keep_other_rejections_and_skip_precedence_3(run, workdir):
    """CATCHES: reimplementations that break "explicit targets keep other rejections and skip precedence" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before `{{ foo` }}.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_explicit_targets_keep_other_rejections_and_skip_precedence_4(run, workdir):
    """CATCHES: reimplementations that break "explicit targets keep other rejections and skip precedence" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before {{ foo }}.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'explicit_targets_keep_other_rejections_and_skip_precedence_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_targets_keep_other_rejections_and_skip_precedence_5(run, workdir):
    """CATCHES: reimplementations that break "explicit targets keep other rejections and skip precedence" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '<!-- fmt: skip file -->\n'
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before {{ foo }}.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'explicit_targets_keep_other_rejections_and_skip_precedence_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_targets_keep_other_rejections_and_skip_precedence_6(run, workdir):
    """CATCHES: reimplementations that break "explicit targets keep other rejections and skip precedence" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before \\LaTeX.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: fmt: markdown targets an unsupported Markdown block\n'
    assert result.returncode == 1


def test_frontmatter_options_and_existing_child_documents_use_the_same_planner_1(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options and existing child documents use the same planner" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: sentence\n'
        '---\n'
        'Before\n'
        'with `{{ foo }}`. After\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_and_existing_child_documents_use_the_same_planner_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_options_and_existing_child_documents_use_the_same_planner_2(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options and existing child documents use the same planner" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: sentence\n'
        '---\n'
        'Before with `{{ foo }}`.\n'
        'After sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_and_existing_child_documents_use_the_same_planner_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_options_and_existing_child_documents_use_the_same_planner_3(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options and existing child documents use the same planner" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '::: {.callout-note}\n'
        'Before\n'
        'with `{{ foo }}`. After\n'
        'sentence.\n'
        ':::\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_and_existing_child_documents_use_the_same_planner_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_options_and_existing_child_documents_use_the_same_planner_4(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options and existing child documents use the same planner" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '::: {.callout-note}\n'
        'Before with `{{ foo }}`.\n'
        'After sentence.\n'
        ':::\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_and_existing_child_documents_use_the_same_planner_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_frontmatter_options_and_existing_child_documents_use_the_same_planner_5(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options and existing child documents use the same planner" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '```markdown\n'
        'Before\n'
        'with `{{ foo }}`. After\n'
        'sentence.\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_and_existing_child_documents_use_the_same_planner_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_frontmatter_options_and_existing_child_documents_use_the_same_planner_6(run, workdir):
    """CATCHES: reimplementations that break "frontmatter options and existing child documents use the same planner" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '```markdown\n'
        'Before with `{{ foo }}`.\n'
        'After sentence.\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'frontmatter_options_and_existing_child_documents_use_the_same_planner_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_host_guards_still_preserve_template_bearing_markdown_1(run, workdir):
    """CATCHES: reimplementations that break "host guards still preserve template bearing markdown" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    stdin = (
        'body: !markdown |\n'
        '  Before\n'
        '  with `{{ foo }}`. After\n'
        '  sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'host_guards_still_preserve_template_bearing_markdown_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_host_guards_still_preserve_template_bearing_markdown_2(run, workdir):
    """CATCHES: reimplementations that break "host guards still preserve template bearing markdown" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    stdin = 'body: !markdown "Before with `{{ foo }}`. After sentence."\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'body: !markdown "Before with `{{ foo }}`. After sentence."\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_host_guards_still_preserve_template_bearing_markdown_3(run, workdir):
    """CATCHES: reimplementations that break "host guards still preserve template bearing markdown" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    stdin = (
        '# fmt: markdown\n'
        'text = """\n'
        'Before\n'
        'with `{{ foo }}`. After\n'
        'sentence.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'host_guards_still_preserve_template_bearing_markdown_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_host_guards_still_preserve_template_bearing_markdown_4(run, workdir):
    """CATCHES: reimplementations that break "host guards still preserve template bearing markdown" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    stdin = (
        '# fmt: markdown\n'
        '# Before\n'
        '# with `{{ foo }}`. After\n'
        '# sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'host_guards_still_preserve_template_bearing_markdown_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_host_guards_still_preserve_template_bearing_markdown_5(run, workdir):
    """CATCHES: reimplementations that break "host guards still preserve template bearing markdown" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    stdin = (
        '# fmt: markdown\n'
        'x <- r"(\n'
        'Before\n'
        'with `{{ foo }}`. After\n'
        'sentence.\n'
        ')"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'host_guards_still_preserve_template_bearing_markdown_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.R').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.R'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_late_delimiters_recheck_original_code_ranges_and_explicit_targets_1(run, workdir):
    """CATCHES: reimplementations that break "late delimiters recheck original code ranges and explicit targets" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        '`[[ foo ]]`. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'late_delimiters_recheck_original_code_ranges_and_explicit_targets_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_delimiters_recheck_original_code_ranges_and_explicit_targets_2(run, workdir):
    """CATCHES: reimplementations that break "late delimiters recheck original code ranges and explicit targets" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` and `[[ bar ]]`. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'late_delimiters_recheck_original_code_ranges_and_explicit_targets_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_delimiters_recheck_original_code_ranges_and_explicit_targets_3(run, workdir):
    """CATCHES: reimplementations that break "late delimiters recheck original code ranges and explicit targets" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }}` and [[ outside ]]. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'late_delimiters_recheck_original_code_ranges_and_explicit_targets_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_delimiters_recheck_original_code_ranges_and_explicit_targets_4(run, workdir):
    """CATCHES: reimplementations that break "late delimiters recheck original code ranges and explicit targets" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before\n'
        '`[[ foo ]]`. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'late_delimiters_recheck_original_code_ranges_and_explicit_targets_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_delimiters_recheck_original_code_ranges_and_explicit_targets_5(run, workdir):
    """CATCHES: reimplementations that break "late delimiters recheck original code ranges and explicit targets" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before\n'
        '`{{ foo }}` and `[[ bar ]]`. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'late_delimiters_recheck_original_code_ranges_and_explicit_targets_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_delimiters_recheck_original_code_ranges_and_explicit_targets_6(run, workdir):
    """CATCHES: reimplementations that break "late delimiters recheck original code ranges and explicit targets" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'Before\n'
        '`{{ foo }}` and [[ outside ]]. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'late_delimiters_recheck_original_code_ranges_and_explicit_targets_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_overwide_code_templates_remain_atomic_1(run, workdir):
    """CATCHES: reimplementations that break "overwide code templates remain atomic" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before `{{ foo }} [x](  long-target  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'overwide_code_templates_remain_atomic_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_overwide_code_templates_remain_atomic_2(run, workdir):
    """CATCHES: reimplementations that break "overwide code templates remain atomic" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before `{{ foo }} [x](  long-target  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'overwide_code_templates_remain_atomic_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_overwide_code_templates_remain_atomic_3(run, workdir):
    """CATCHES: reimplementations that break "overwide code templates remain atomic" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '`{{ foo }} [x](  long-target  )`\n'
        'after [r](t).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:16'], input=stdin)
    assert result.stdout == (RES / 'overwide_code_templates_remain_atomic_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_overwide_code_templates_remain_atomic_4(run, workdir):
    """CATCHES: reimplementations that break "overwide code templates remain atomic" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before ``<% foo %> ![x](  long-target  ) ` `` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'overwide_code_templates_remain_atomic_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_overwide_code_templates_remain_atomic_5(run, workdir):
    """CATCHES: reimplementations that break "overwide code templates remain atomic" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before ``<% foo %> ![x](  long-target  ) ` `` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'overwide_code_templates_remain_atomic_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_overwide_code_templates_remain_atomic_6(run, workdir):
    """CATCHES: reimplementations that break "overwide code templates remain atomic" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        '``<% foo %> ![x](  long-target  ) ` ``\n'
        'after [r](t).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:16'], input=stdin)
    assert result.stdout == (RES / 'overwide_code_templates_remain_atomic_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_scoped_delimiters_and_skip_keep_their_boundaries_1(run, workdir):
    """CATCHES: reimplementations that break "scoped delimiters and skip keep their boundaries" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '<!-- fmt: template.delimiters "[[" "]]" scope=from-here -->\n'
        'Before\n'
        '`[[ foo ]]`. After\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        'Before\n'
        '`{{ foo }}`. After\n'
        'sentence.\n'
        '\n'
        'Following\n'
        'paragraph. Next\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'scoped_delimiters_and_skip_keep_their_boundaries_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_scoped_delimiters_and_skip_keep_their_boundaries_2(run, workdir):
    """CATCHES: reimplementations that break "scoped delimiters and skip keep their boundaries" (template code paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '<!-- fmt: template.delimiters "[[" "]]" scope=from-here -->\n'
        'Before `[[ foo ]]`.\n'
        'After sentence.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        'Before\n'
        '`{{ foo }}`. After\n'
        'sentence.\n'
        '\n'
        'Following paragraph.\n'
        'Next sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'scoped_delimiters_and_skip_keep_their_boundaries_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
