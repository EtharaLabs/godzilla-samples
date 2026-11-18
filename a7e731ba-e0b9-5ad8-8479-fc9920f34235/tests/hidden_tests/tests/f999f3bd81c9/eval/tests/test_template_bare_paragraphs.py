"""Template bare paragraphs behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_heading_guards_and_explicit_hard_breaks_keep_their_boundaries_1(run, workdir):
    """CATCHES: reimplementations that break "heading guards and explicit hard breaks keep their boundaries" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = '# Before {{ foo }} after [real](  target  ) _outside_.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'# Before {{ foo }} after [real](  target  ) _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_heading_guards_and_explicit_hard_breaks_keep_their_boundaries_2(run, workdir):
    """CATCHES: reimplementations that break "heading guards and explicit hard breaks keep their boundaries" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = '- Before {{ foo }} after [real](  target  ) _outside_.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'- Before {{ foo }} after [real](target) *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_heading_guards_and_explicit_hard_breaks_keep_their_boundaries_3(run, workdir):
    """CATCHES: reimplementations that break "heading guards and explicit hard breaks keep their boundaries" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = '- Before {{ foo }} after [real](target) *outside*.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'- Before {{ foo }} after [real](target) *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_heading_guards_and_explicit_hard_breaks_keep_their_boundaries_4(run, workdir):
    """CATCHES: reimplementations that break "heading guards and explicit hard breaks keep their boundaries" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = '> Before {{ foo }} after [real](  target  ) _outside_.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'> Before {{ foo }} after [real](target) *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_heading_guards_and_explicit_hard_breaks_keep_their_boundaries_5(run, workdir):
    """CATCHES: reimplementations that break "heading guards and explicit hard breaks keep their boundaries" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = '> Before {{ foo }} after [real](target) *outside*.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'> Before {{ foo }} after [real](target) *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_heading_guards_and_explicit_hard_breaks_keep_their_boundaries_6(run, workdir):
    """CATCHES: reimplementations that break "heading guards and explicit hard breaks keep their boundaries" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        '{{ foo }}  \n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'heading_guards_and_explicit_hard_breaks_keep_their_boundaries_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_expressions_keep_exact_bytes_under_paragraph_options_1(run, workdir):
    """CATCHES: reimplementations that break "complete expressions keep exact bytes under paragraph options" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'First\n'
        "sentence with {{ 'foo' }} and [real](  target  ). Second\n"
        'sentence with _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'complete_expressions_keep_exact_bytes_under_paragraph_options_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_expressions_keep_exact_bytes_under_paragraph_options_2(run, workdir):
    """CATCHES: reimplementations that break "complete expressions keep exact bytes under paragraph options" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'First sentence with {{ .foo }} and [real](target). Second sentence with _outside_.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'First sentence with {{ .foo }} and [real](target). Second sentence with _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_complete_expressions_keep_exact_bytes_under_paragraph_options_3(run, workdir):
    """CATCHES: reimplementations that break "complete expressions keep exact bytes under paragraph options" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'First\n'
        'sentence with {{ foo + bar }} and [real](  target  ). Second\n'
        'sentence with _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'First sentence with {{ foo + bar }} and [real](target). Second sentence with *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_expressions_keep_exact_bytes_under_paragraph_options_4(run, workdir):
    """CATCHES: reimplementations that break "complete expressions keep exact bytes under paragraph options" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'First\n'
        'sentence with {{ foo }} {# other #} and [real](  target  ). Second\n'
        'sentence with _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'complete_expressions_keep_exact_bytes_under_paragraph_options_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_complete_expressions_keep_exact_bytes_under_paragraph_options_5(run, workdir):
    """CATCHES: reimplementations that break "complete expressions keep exact bytes under paragraph options" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'First sentence with {{ foo }}/tail and [real](target). Second sentence with _outside_.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'First sentence with {{ foo }}/tail and [real](target). Second sentence with _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_complete_expressions_keep_exact_bytes_under_paragraph_options_6(run, workdir):
    """CATCHES: reimplementations that break "complete expressions keep exact bytes under paragraph options" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'First\n'
        'sentence with {{\t_user9.Name_2\t }} and [real](  target  ). Second\n'
        'sentence with _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'First sentence with {{\t_user9.Name_2\t }} and [real](target). Second sentence with *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hosts_keep_their_bare_template_guards_1(run, workdir):
    """CATCHES: reimplementations that break "hosts keep their bare template guards" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        'body: !markdown |\n'
        '  Before\n'
        '  with {{ foo }}. After\n'
        '  sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'hosts_keep_their_bare_template_guards_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_hosts_keep_their_bare_template_guards_2(run, workdir):
    """CATCHES: reimplementations that break "hosts keep their bare template guards" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = 'body: !markdown "Before with {{ foo }}. After sentence."\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'body: !markdown "Before with {{ foo }}. After sentence."\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_hosts_keep_their_bare_template_guards_3(run, workdir):
    """CATCHES: reimplementations that break "hosts keep their bare template guards" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        '# fmt: markdown\n'
        'text = """\n'
        'Before\n'
        'with {{ foo }}. After\n'
        'sentence.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'hosts_keep_their_bare_template_guards_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_hosts_keep_their_bare_template_guards_4(run, workdir):
    """CATCHES: reimplementations that break "hosts keep their bare template guards" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '# fmt: markdown\n'
        'x <- r"(\n'
        'Before\n'
        'with {{ foo }}. After\n'
        'sentence.\n'
        ')"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'hosts_keep_their_bare_template_guards_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.R').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.R'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_delimiter_configuration_and_late_policy_use_original_source_1(run, workdir):
    """CATCHES: reimplementations that break "delimiter configuration and late policy use original source" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First\n'
        'with {{   foo   }}. Second\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'delimiter_configuration_and_late_policy_use_original_source_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiter_configuration_and_late_policy_use_original_source_2(run, workdir):
    """CATCHES: reimplementations that break "delimiter configuration and late policy use original source" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'First\n'
        'with {{   foo   }}. Second\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "{{" "}}" scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'delimiter_configuration_and_late_policy_use_original_source_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiter_configuration_and_late_policy_use_original_source_3(run, workdir):
    """CATCHES: reimplementations that break "delimiter configuration and late policy use original source" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "replace_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First with {{ foo }} `[[ other ]]`.\n'
        'Second sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'delimiter_configuration_and_late_policy_use_original_source_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_delimiter_configuration_and_late_policy_use_original_source_4(run, workdir):
    """CATCHES: reimplementations that break "delimiter configuration and late policy use original source" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'replace_delimiters = []\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First\n'
        'with {{   foo   }}. Second\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'delimiter_configuration_and_late_policy_use_original_source_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiter_configuration_and_late_policy_use_original_source_5(run, workdir):
    """CATCHES: reimplementations that break "delimiter configuration and late policy use original source" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'replace_delimiters = []\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'First\n'
        'with {{   foo   }}. Second\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "{{" "}}" scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'delimiter_configuration_and_late_policy_use_original_source_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiter_configuration_and_late_policy_use_original_source_6(run, workdir):
    """CATCHES: reimplementations that break "delimiter configuration and late policy use original source" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "replace_delimiters = [{open='{{', close='}}'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First with {{ foo }} `[[ other ]]`.\n'
        'Second sentence.\n'
        '\n'
        '<!-- fmt: template.delimiters "[[" "]]" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'delimiter_configuration_and_late_policy_use_original_source_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_late_policy_changes_reconsider_placement_without_changing_target_precedence_1(run, workdir):
    """CATCHES: reimplementations that break "late policy changes reconsider placement without changing target precedence" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'replace_delimiters = []\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '<!-- fmt: wrap=8 scope=next -->\n'
        'Before {{ foo }} after.\n'
        '\n'
        '<!-- fmt: template.delimiters "{{" "}}" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'late_policy_changes_reconsider_placement_without_changing_target_precedence_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_late_policy_changes_reconsider_placement_without_changing_target_precedence_2(run, workdir):
    """CATCHES: reimplementations that break "late policy changes reconsider placement without changing target precedence" (template bare paragraphs); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'replace_delimiters = []\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '<!-- fmt: wrap=8 scope=next -->\n'
        'Before\n'
        '{{ foo }}\n'
        'after.\n'
        '\n'
        '<!-- fmt: template.delimiters "{{" "}}" scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'late_policy_changes_reconsider_placement_without_changing_target_precedence_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_late_policy_changes_reconsider_placement_without_changing_target_precedence_3(run, workdir):
    """CATCHES: reimplementations that break "late policy changes reconsider placement without changing target precedence" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        'Before\n'
        'with {{ foo }} after [real](  target  ).\n'
        '\n'
        '<!-- fmt: wrap=sentence scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'late_policy_changes_reconsider_placement_without_changing_target_precedence_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_policy_changes_reconsider_placement_without_changing_target_precedence_4(run, workdir):
    """CATCHES: reimplementations that break "late policy changes reconsider placement without changing target precedence" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        'Before with {{ foo }} after [real](target).\n'
        '\n'
        '<!-- fmt: wrap=sentence scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'late_policy_changes_reconsider_placement_without_changing_target_precedence_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_punctuation_and_paragraph_boundaries_are_inline_placements_1(run, workdir):
    """CATCHES: reimplementations that break "punctuation and paragraph boundaries are inline placements" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }}. After\n'
        'prose.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before with {{ foo }}. After prose.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_punctuation_and_paragraph_boundaries_are_inline_placements_2(run, workdir):
    """CATCHES: reimplementations that break "punctuation and paragraph boundaries are inline placements" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }}, After\n'
        'prose.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before with {{ foo }}, After prose.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_punctuation_and_paragraph_boundaries_are_inline_placements_3(run, workdir):
    """CATCHES: reimplementations that break "punctuation and paragraph boundaries are inline placements" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }}; After\n'
        'prose.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before with {{ foo }}; After prose.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_punctuation_and_paragraph_boundaries_are_inline_placements_4(run, workdir):
    """CATCHES: reimplementations that break "punctuation and paragraph boundaries are inline placements" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before with {{ foo }}: After prose.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before with {{ foo }}: After prose.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_punctuation_and_paragraph_boundaries_are_inline_placements_5(run, workdir):
    """CATCHES: reimplementations that break "punctuation and paragraph boundaries are inline placements" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before with {{ foo }}! After prose.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before with {{ foo }}! After prose.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_punctuation_and_paragraph_boundaries_are_inline_placements_6(run, workdir):
    """CATCHES: reimplementations that break "punctuation and paragraph boundaries are inline placements" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before with {{ foo }}? After prose.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before with {{ foo }}? After prose.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_source_and_planned_template_only_lines_follow_wrapping_mode_1(run, workdir):
    """CATCHES: reimplementations that break "source and planned template only lines follow wrapping mode" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        '{{ foo }}\n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'source_and_planned_template_only_lines_follow_wrapping_mode_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_source_and_planned_template_only_lines_follow_wrapping_mode_2(run, workdir):
    """CATCHES: reimplementations that break "source and planned template only lines follow wrapping mode" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        '{{ foo }}\n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before {{ foo }} after [real](target).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_source_and_planned_template_only_lines_follow_wrapping_mode_3(run, workdir):
    """CATCHES: reimplementations that break "source and planned template only lines follow wrapping mode" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '{{ foo }}\n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'Before {{ foo }} after [real](target).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_source_and_planned_template_only_lines_follow_wrapping_mode_4(run, workdir):
    """CATCHES: reimplementations that break "source and planned template only lines follow wrapping mode" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        '{{ foo }}\n'
        'after\n'
        '[real](\n'
        '  target\n'
        ').\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'source_and_planned_template_only_lines_follow_wrapping_mode_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '12', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_source_and_planned_template_only_lines_follow_wrapping_mode_5(run, workdir):
    """CATCHES: reimplementations that break "source and planned template only lines follow wrapping mode" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        '{{ foo }}\n'
        'after\n'
        '[real](\n'
        '  target\n'
        ').\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:12'], input=stdin)
    assert result.stdout == (RES / 'source_and_planned_template_only_lines_follow_wrapping_mode_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:12', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_source_and_planned_template_only_lines_follow_wrapping_mode_6(run, workdir):
    """CATCHES: reimplementations that break "source and planned template only lines follow wrapping mode" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before {{   user.name   }} after\n'
        'some more prose with [real](t).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '36'], input=stdin)
    assert result.stdout == (RES / 'source_and_planned_template_only_lines_follow_wrapping_mode_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '36', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_target_skip_frontmatter_and_child_documents_keep_their_policies_1(run, workdir):
    """CATCHES: reimplementations that break "target skip frontmatter and child documents keep their policies" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First\n'
        'with {{ foo }}. Second\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'target_skip_frontmatter_and_child_documents_keep_their_policies_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_target_skip_frontmatter_and_child_documents_keep_their_policies_2(run, workdir):
    """CATCHES: reimplementations that break "target skip frontmatter and child documents keep their policies" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'First with {{ foo }}.\n'
        'Second sentence.\n'
        '\n'
        '<!-- fmt: wrap=sentence scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'target_skip_frontmatter_and_child_documents_keep_their_policies_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_target_skip_frontmatter_and_child_documents_keep_their_policies_3(run, workdir):
    """CATCHES: reimplementations that break "target skip frontmatter and child documents keep their policies" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '::: {.callout-note}\n'
        'First\n'
        'with {{ foo }}. Second\n'
        'sentence.\n'
        ':::\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'target_skip_frontmatter_and_child_documents_keep_their_policies_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_target_skip_frontmatter_and_child_documents_keep_their_policies_4(run, workdir):
    """CATCHES: reimplementations that break "target skip frontmatter and child documents keep their policies" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '```markdown\n'
        'First with {{ foo }}.\n'
        'Second sentence.\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'target_skip_frontmatter_and_child_documents_keep_their_policies_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_target_skip_frontmatter_and_child_documents_keep_their_policies_5(run, workdir):
    """CATCHES: reimplementations that break "target skip frontmatter and child documents keep their policies" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '<!-- fmt: skip -->\n'
        'First\n'
        'with {{ foo }}. Second\n'
        'sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'target_skip_frontmatter_and_child_documents_keep_their_policies_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_target_skip_frontmatter_and_child_documents_keep_their_policies_6(run, workdir):
    """CATCHES: reimplementations that break "target skip frontmatter and child documents keep their policies" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: skip file -->\n'
        '<!-- fmt: wrap=8 scope=next -->\n'
        'Before {{ foo }} < value.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'target_skip_frontmatter_and_child_documents_keep_their_policies_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_1(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }} {{< ref target >}} after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_2(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }} and {{ unmatched after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:16'], input=stdin)
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_3(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        'with _{{ foo }}_ after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_4(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }} < value after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_5(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo\n'
        '.bar }} after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unsupported_expressions_and_contexts_keep_baseline_preservation_6(run, workdir):
    """CATCHES: reimplementations that break "unsupported expressions and contexts keep baseline preservation" (template bare paragraphs); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        'with {{ foo }} and \\LaTeX after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'unsupported_expressions_and_contexts_keep_baseline_preservation_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
