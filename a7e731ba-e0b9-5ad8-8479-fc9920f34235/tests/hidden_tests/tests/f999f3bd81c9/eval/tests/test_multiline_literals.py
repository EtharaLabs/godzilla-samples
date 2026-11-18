"""Multiline literals behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_definition_and_footnote_content_keeps_authored_lines_1(run, workdir):
    """CATCHES: reimplementations that break "definition and footnote content keeps authored lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '-  Before `first  \n'
        '    second [x]( url )` after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_and_footnote_content_keeps_authored_lines_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_and_footnote_content_keeps_authored_lines_2(run, workdir):
    """CATCHES: reimplementations that break "definition and footnote content keeps authored lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Term\n'
        ':   Before `first  \n'
        '      second [x]( url )` after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_and_footnote_content_keeps_authored_lines_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_and_footnote_content_keeps_authored_lines_3(run, workdir):
    """CATCHES: reimplementations that break "definition and footnote content keeps authored lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Term\n'
        '   : Before `first  \n'
        '    second [x]( url )` after _outside_. Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_and_footnote_content_keeps_authored_lines_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_and_footnote_content_keeps_authored_lines_4(run, workdir):
    """CATCHES: reimplementations that break "definition and footnote content keeps authored lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Term\n'
        '   : Before `first\t\n'
        '    \tsecond [x]( url )` after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_and_footnote_content_keeps_authored_lines_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_and_footnote_content_keeps_authored_lines_5(run, workdir):
    """CATCHES: reimplementations that break "definition and footnote content keeps authored lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '[^note]: Before `first  \n'
        '    second [x]( url )` after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_and_footnote_content_keeps_authored_lines_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_and_footnote_content_keeps_authored_lines_6(run, workdir):
    """CATCHES: reimplementations that break "definition and footnote content keeps authored lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '[^note]: First paragraph.\n'
        '\n'
        '    Before `first  \n'
        '      second [x]( url )` after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_and_footnote_content_keeps_authored_lines_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_tabs_match_parser_eligibility_without_trimming_literals_1(run, workdir):
    """CATCHES: reimplementations that break "definition tabs match parser eligibility without trimming literals" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    stdin = (
        'Term\n'
        ': Before   prose.\n'
        '   \tAfter   _outside_ [real](  target  ).\n'
        '\n'
        '# Code\n'
        '\n'
        'Code\n'
        '   : Before `first  \n'
        '   \t\tsecond [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '# Math\n'
        '\n'
        'Math\n'
        '   : Before $first  \n'
        '\t   second \\$ [x]( url )$ after _outside_. Next sentence.\n'
        '\n'
        '# Ineligible continuation\n'
        '\n'
        'Short\n'
        ': Before   prose.\n'
        '  \tAfter   _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_tabs_match_parser_eligibility_without_trimming_literals_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_tabs_match_parser_eligibility_without_trimming_literals_2(run, workdir):
    """CATCHES: reimplementations that break "definition tabs match parser eligibility without trimming literals" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    stdin = (
        'Term\n'
        ': Before prose.\n'
        '  After *outside* [real](target).\n'
        '\n'
        '# Code\n'
        '\n'
        'Code\n'
        '   : Before `first  \n'
        '     \tsecond [x]( url )` after *outside* [real](target).\n'
        '\n'
        '# Math\n'
        '\n'
        'Math\n'
        '   : Before $first  \n'
        '     second \\$ [x]( url )$ after *outside*.\n'
        '     Next sentence.\n'
        '\n'
        '# Ineligible continuation\n'
        '\n'
        'Short\n'
        ': Before   prose.\n'
        '  \tAfter   _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_tabs_match_parser_eligibility_without_trimming_literals_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_definition_tabs_match_parser_eligibility_without_trimming_literals_3(run, workdir):
    """CATCHES: reimplementations that break "definition tabs match parser eligibility without trimming literals" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    stdin = (
        'Term\n'
        '   : Before   prose.\n'
        '   \u2003After   _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_tabs_match_parser_eligibility_without_trimming_literals_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_editable_link_label_breaks_normalize_before_validation_1(run, workdir):
    """CATCHES: reimplementations that break "editable link label breaks normalize before validation" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before [first\n'
        'second](  target  ) after _outside_.\n'
        '\n'
        '- Before [first\n'
        '  second](  target  ) after _outside_.\n'
        '\n'
        '> Before [first\n'
        '> second](  target  ) after _outside_.\n'
        '\n'
        'Before ![first\n'
        'second](  image.png  ) after _outside_.\n'
        '\n'
        '# Existing opaque boundaries\n'
        '\n'
        '- Before <kbd>`first\n'
        '    second`</kbd> after _outside_.\n'
        '\n'
        '- Before <kbd>$first\n'
        '    second$</kbd> after _outside_.\n'
        '\n'
        'Before [label `first\n'
        'second`](  target  ) after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'editable_link_label_breaks_normalize_before_validation_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_editable_link_label_breaks_normalize_before_validation_2(run, workdir):
    """CATCHES: reimplementations that break "editable link label breaks normalize before validation" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before [first second](target) after *outside*.\n'
        '\n'
        '- Before [first second](target) after *outside*.\n'
        '\n'
        '> Before [first second](target) after *outside*.\n'
        '\n'
        'Before ![first second](image.png) after *outside*.\n'
        '\n'
        '# Existing opaque boundaries\n'
        '\n'
        '- Before <kbd>`first\n'
        '    second`</kbd> after _outside_.\n'
        '\n'
        '- Before <kbd>$first\n'
        '    second$</kbd> after _outside_.\n'
        '\n'
        'Before [label `first\n'
        'second`](  target  ) after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'editable_link_label_breaks_normalize_before_validation_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_editable_link_label_breaks_normalize_before_validation_3(run, workdir):
    """CATCHES: reimplementations that break "editable link label breaks normalize before validation" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before [first\n'
        'second](  target  ) after _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'editable_link_label_breaks_normalize_before_validation_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_editable_link_label_breaks_normalize_before_validation_4(run, workdir):
    """CATCHES: reimplementations that break "editable link label breaks normalize before validation" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before [first\n'
        'second](  target  ) after _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before [first second](target) after _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_editable_link_label_breaks_normalize_before_validation_5(run, workdir):
    """CATCHES: reimplementations that break "editable link label breaks normalize before validation" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before [first second](target) after _outside_.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before [first second](target) after _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_editable_link_label_breaks_normalize_before_validation_6(run, workdir):
    """CATCHES: reimplementations that break "editable link label breaks normalize before validation" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '- Before [first\n'
        '  second](  target  ) after _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'- Before [first second](target) after *outside*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hard_breaks_keep_existing_markup_and_link_normalization_boundaries_1(run, workdir):
    """CATCHES: reimplementations that break "hard breaks keep existing markup and link normalization boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before <kbd>first\n'
        'second</kbd> after.  \n'
        'Next [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'hard_breaks_keep_existing_markup_and_link_normalization_boundaries_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hard_breaks_keep_existing_markup_and_link_normalization_boundaries_2(run, workdir):
    """CATCHES: reimplementations that break "hard breaks keep existing markup and link normalization boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before <kbd>first second</kbd> after. \\\n'
        'Next [real](target).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'hard_breaks_keep_existing_markup_and_link_normalization_boundaries_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:80', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_hard_breaks_keep_existing_markup_and_link_normalization_boundaries_3(run, workdir):
    """CATCHES: reimplementations that break "hard breaks keep existing markup and link normalization boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before <kbd>first   word  \n'
        'second  word</kbd> after _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'hard_breaks_keep_existing_markup_and_link_normalization_boundaries_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hard_breaks_keep_existing_markup_and_link_normalization_boundaries_4(run, workdir):
    """CATCHES: reimplementations that break "hard breaks keep existing markup and link normalization boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before <kbd>first word \\\n'
        'second word</kbd> after\n'
        '*outside*.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'hard_breaks_keep_existing_markup_and_link_normalization_boundaries_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '30', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_hard_breaks_keep_existing_markup_and_link_normalization_boundaries_5(run, workdir):
    """CATCHES: reimplementations that break "hard breaks keep existing markup and link normalization boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before <kbd>word</kbd> after.  \n'
        'Next [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'hard_breaks_keep_existing_markup_and_link_normalization_boundaries_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hard_breaks_keep_existing_markup_and_link_normalization_boundaries_6(run, workdir):
    """CATCHES: reimplementations that break "hard breaks keep existing markup and link normalization boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before <kbd>word</kbd> after. \\\n'
        'Next [real](target).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'hard_breaks_keep_existing_markup_and_link_normalization_boundaries_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '30', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_late_options_use_the_original_literal_boundaries_1(run, workdir):
    """CATCHES: reimplementations that break "late options use the original literal boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'Before  `first  \n'
        '  second [x]( url )` after _outside_ [real](  target  ). Next sentence.\n'
        '\n'
        '<!-- fmt: wrap=sentence canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'late_options_use_the_original_literal_boundaries_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_options_use_the_original_literal_boundaries_2(run, workdir):
    """CATCHES: reimplementations that break "late options use the original literal boundaries" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'Before `first  \n'
        '  second [x]( url )` after *outside* [real](target).\n'
        'Next sentence.\n'
        '\n'
        '<!-- fmt: wrap=sentence canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'late_options_use_the_original_literal_boundaries_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_support_uses_literal_boundaries_with_escapes_and_indented_openers_1(run, workdir):
    """CATCHES: reimplementations that break "list support uses literal boundaries with escapes and indented openers" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '- Before \\$ escaped then $first  \n'
        '    second \\$ [x]( url )$ after _outside_ [real](  target  ).\n'
        '\n'
        '- _Before \\` escaped_ then `first  \n'
        '    second [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '- _Before \\`` escaped_ then `first\n'
        '    second` after _outside_.\n'
        '\n'
        '# Existing tokenizer fallback\n'
        '\n'
        '- Before \\` escaped then `first\n'
        '    second` after _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_support_uses_literal_boundaries_with_escapes_and_indented_openers_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_support_uses_literal_boundaries_with_escapes_and_indented_openers_2(run, workdir):
    """CATCHES: reimplementations that break "list support uses literal boundaries with escapes and indented openers" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '- Before \\$ escaped then $first  \n'
        '    second \\$ [x]( url )$ after *outside* [real](target).\n'
        '\n'
        '- *Before \\` escaped* then `first  \n'
        '    second [x]( url )` after *outside* [real](target).\n'
        '\n'
        '- *Before \\`` escaped* then `first\n'
        '    second` after *outside*.\n'
        '\n'
        '# Existing tokenizer fallback\n'
        '\n'
        '- Before \\` escaped then `first\n'
        '    second` after _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_support_uses_literal_boundaries_with_escapes_and_indented_openers_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_support_uses_literal_boundaries_with_escapes_and_indented_openers_3(run, workdir):
    """CATCHES: reimplementations that break "list support uses literal boundaries with escapes and indented openers" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '- Before \\$ escaped then $first  \n'
        '    second \\$ [x]( url )$ after _outside_ [real](  target  ).\n'
        '\n'
        '- _Before \\` escaped_ then `first  \n'
        '    second [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '- _Before \\`` escaped_ then `first\n'
        '    second` after _outside_.\n'
        '\n'
        '# Existing tokenizer fallback\n'
        '\n'
        '- Before \\` escaped then `first\n'
        '    second` after _outside_ [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'list_support_uses_literal_boundaries_with_escapes_and_indented_openers_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_support_uses_literal_boundaries_with_escapes_and_indented_openers_4(run, workdir):
    """CATCHES: reimplementations that break "list support uses literal boundaries with escapes and indented openers" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '- Before \\$ escaped then $first  \n'
        '    second \\$ [x]( url )$ after *outside* [real](target).\n'
        '\n'
        '- *Before \\` escaped* then `first  \n'
        '    second [x]( url )` after *outside* [real](target).\n'
        '\n'
        '- *Before \\`` escaped* then `first\n'
        '    second` after *outside*.\n'
        '\n'
        '# Existing tokenizer fallback\n'
        '\n'
        '- Before \\` escaped then `first\n'
        '    second` after _outside_ [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'list_support_uses_literal_boundaries_with_escapes_and_indented_openers_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_support_uses_literal_boundaries_with_escapes_and_indented_openers_5(run, workdir):
    """CATCHES: reimplementations that break "list support uses literal boundaries with escapes and indented openers" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '- Before\n'
        '    `first  \n'
        '    second [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '- Before\n'
        '    $first  \n'
        '    second \\$ [x]( url )$ after _outside_. Next sentence.\n'
        '\n'
        '# Existing indentation boundaries\n'
        '\n'
        '- Before\n'
        '    still prose after _outside_ [real](  target  ).\n'
        '\n'
        '100. Before\n'
        '    `first\n'
        '    second` after _outside_.\n'
        '\n'
        '# Existing split-link continuation\n'
        '\n'
        '- Before [label](target\n'
        '    ) after _outside_ [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'list_support_uses_literal_boundaries_with_escapes_and_indented_openers_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_support_uses_literal_boundaries_with_escapes_and_indented_openers_6(run, workdir):
    """CATCHES: reimplementations that break "list support uses literal boundaries with escapes and indented openers" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '- Before\n'
        '  `first  \n'
        '    second [x]( url )`\n'
        '  after *outside*\n'
        '  [real](target).\n'
        '\n'
        '- Before\n'
        '  $first  \n'
        '    second \\$ [x]( url )$\n'
        '  after *outside*. Next\n'
        '  sentence.\n'
        '\n'
        '# Existing indentation boundaries\n'
        '\n'
        '- Before\n'
        '    still prose after _outside_ [real](  target  ).\n'
        '\n'
        '100. Before\n'
        '    `first\n'
        '    second` after _outside_.\n'
        '\n'
        '# Existing split-link continuation\n'
        '\n'
        '- Before [label](target)\n'
        '  after *outside*\n'
        '  [real](target).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'list_support_uses_literal_boundaries_with_escapes_and_indented_openers_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '24', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_literal_line_ending_fixtures_keep_exact_bytes_1(run, workdir):
    """CATCHES: reimplementations that break "literal line ending fixtures keep exact bytes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '::: note\r\n'
        '```markdown\r\n'
        'Before `first  \t\r\n'
        '  second\\\r\n'
        'third [x]( url )` after _outside_ [real](  target  ).\r\n'
        ' \t\r\n'
        'Next   paragraph.\t\r\n'
        '```\r\n'
        ':::\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_ending_fixtures_keep_exact_bytes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_ending_fixtures_keep_exact_bytes_2(run, workdir):
    """CATCHES: reimplementations that break "literal line ending fixtures keep exact bytes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '::: note\r\n'
        '```markdown\r\n'
        'Before `first  \t\r\n'
        '  second\\\r\n'
        'third [x]( url )` after *outside* [real](target).\r\n'
        '\r\n'
        'Next paragraph.\r\n'
        '```\r\n'
        ':::\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_ending_fixtures_keep_exact_bytes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_literal_line_ending_fixtures_keep_exact_bytes_3(run, workdir):
    """CATCHES: reimplementations that break "literal line ending fixtures keep exact bytes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '> > Before `first\t\r'
        '> >   second [x]( url )` after _outside_ [real](  target  ).\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (
        b'> > Before `first\t\r'
        b'> >   second [x]( url )` after *outside* [real](target).\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_ending_fixtures_keep_exact_bytes_4(run, workdir):
    """CATCHES: reimplementations that break "literal line ending fixtures keep exact bytes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '> > Before `first\t\r'
        '> >   second [x]( url )` after *outside* [real](target).\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (
        b'> > Before `first\t\r'
        b'> >   second [x]( url )` after *outside* [real](target).\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_literal_line_ending_fixtures_keep_exact_bytes_5(run, workdir):
    """CATCHES: reimplementations that break "literal line ending fixtures keep exact bytes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before   `first  \r\n'
        '  second\t\r'
        'third\\\n'
        'last [x]( url )` after _outside_ [real](  target  ).\r\n'
        '\r\n'
        'Before $first  \t\n'
        '  second \\$ [x]( url )\r'
        'third$ after _outside_ [real](  target  ).\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_ending_fixtures_keep_exact_bytes_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_ending_fixtures_keep_exact_bytes_6(run, workdir):
    """CATCHES: reimplementations that break "literal line ending fixtures keep exact bytes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before `first  \r\n'
        '  second\t\r'
        'third\\\n'
        'last [x]( url )` after *outside* [real](target).\r\n'
        '\r\n'
        'Before $first  \t\n'
        '  second \\$ [x]( url )\r'
        'third$ after *outside* [real](target).\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_ending_fixtures_keep_exact_bytes_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_literal_line_endings_survive_container_prefixes_and_recursive_output_1(run, workdir):
    """CATCHES: reimplementations that break "literal line endings survive container prefixes and recursive output" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before   `first  \r\n'
        '  second\t\r'
        'third\\\n'
        'last [x]( url )` after _outside_.\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_endings_survive_container_prefixes_and_recursive_output_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_endings_survive_container_prefixes_and_recursive_output_2(run, workdir):
    """CATCHES: reimplementations that break "literal line endings survive container prefixes and recursive output" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '::: note\n'
        '```markdown\n'
        'Before `first  \t\n'
        '  second\\\n'
        'third [x]( url )` after *outside*.\n'
        '\n'
        'Next paragraph.\n'
        '```\n'
        ':::\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_endings_survive_container_prefixes_and_recursive_output_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_literal_line_endings_survive_container_prefixes_and_recursive_output_3(run, workdir):
    """CATCHES: reimplementations that break "literal line endings survive container prefixes and recursive output" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '::: note\r\n'
        '```markdown\r\n'
        'Before `first  \t\r\n'
        '  second\\\r\n'
        'third [x]( url )` after _outside_.\r\n'
        ' \t\r\n'
        'Next   paragraph.\t\r\n'
        '```\r\n'
        ':::\r\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_endings_survive_container_prefixes_and_recursive_output_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_endings_survive_container_prefixes_and_recursive_output_4(run, workdir):
    """CATCHES: reimplementations that break "literal line endings survive container prefixes and recursive output" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '> > Before `first\t\r\n'
        '> >   second [x]( url )` after *outside*.\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'literal_line_endings_survive_container_prefixes_and_recursive_output_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_literal_line_endings_survive_container_prefixes_and_recursive_output_5(run, workdir):
    """CATCHES: reimplementations that break "literal line endings survive container prefixes and recursive output" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '> > Before `first\t\r'
        '> >   second [x]( url )` after _outside_.\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (
        b'> > Before `first\t\r'
        b'> >   second [x]( url )` after *outside*.\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_endings_survive_container_prefixes_and_recursive_output_6(run, workdir):
    """CATCHES: reimplementations that break "literal line endings survive container prefixes and recursive output" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '> ```markdown\n'
        '> Before `first  \n'
        '>   second [x]( url )` after *outside*.\n'
        '> ```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_line_endings_survive_container_prefixes_and_recursive_output_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_containers_keep_structural_lines_1(run, workdir):
    """CATCHES: reimplementations that break "marker only containers keep structural lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'marker_only_containers_keep_structural_lines_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_containers_keep_structural_lines_2(run, workdir):
    """CATCHES: reimplementations that break "marker only containers keep structural lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'marker_only_containers_keep_structural_lines_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '24', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_containers_keep_structural_lines_3(run, workdir):
    """CATCHES: reimplementations that break "marker only containers keep structural lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'marker_only_containers_keep_structural_lines_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_containers_keep_structural_lines_4(run, workdir):
    """CATCHES: reimplementations that break "marker only containers keep structural lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '-\n'
        '\n'
        '>\n'
        '\n'
        '> -\n'
        '\n'
        '- >\n'
        '\n'
        '```markdown\n'
        '-\n'
        '```\n'
        '\n'
        '- `  `\n'
        '\n'
        '> $  $\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'marker_only_containers_keep_structural_lines_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_containers_keep_structural_lines_5(run, workdir):
    """CATCHES: reimplementations that break "marker only containers keep structural lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '-\r\n'
        '\r\n'
        '>\r\n'
        '\r\n'
        '> -\r\n'
        '\r\n'
        '- >\r\n'
        '\r\n'
        '```markdown\r\n'
        '-\r\n'
        '```\r\n'
        '\r\n'
        '- `  `\r\n'
        '\r\n'
        '> $  $\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'marker_only_containers_keep_structural_lines_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_marker_only_containers_keep_structural_lines_6(run, workdir):
    """CATCHES: reimplementations that break "marker only containers keep structural lines" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '-\r'
        '\r'
        '>\r'
        '\r'
        '> -\r'
        '\r'
        '- >\r'
        '\r'
        '```markdown\r'
        '-\r'
        '```\r'
        '\r'
        '- `  `\r'
        '\r'
        '> $  $\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (
        b'-\r'
        b'\r'
        b'>\r'
        b'\r'
        b'> -\r'
        b'\r'
        b'- >\r'
        b'\r'
        b'```markdown\r'
        b'-\r'
        b'```\r'
        b'\r'
        b'- `  `\r'
        b'\r'
        b'> $  $\r'
    )
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_multiline_literals_preserve_bytes_and_format_surrounding_prose_1(run, workdir):
    """CATCHES: reimplementations that break "multiline literals preserve bytes and format surrounding prose" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before `first  \n'
        '  second [x]( url )` after _outside_. Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literals_preserve_bytes_and_format_surrounding_prose_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literals_preserve_bytes_and_format_surrounding_prose_2(run, workdir):
    """CATCHES: reimplementations that break "multiline literals preserve bytes and format surrounding prose" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        '`first\t\n'
        '  second [x]( url )` after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'multiline_literals_preserve_bytes_and_format_surrounding_prose_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literals_preserve_bytes_and_format_surrounding_prose_3(run, workdir):
    """CATCHES: reimplementations that break "multiline literals preserve bytes and format surrounding prose" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before  $first  \n'
        '  second \\$ [x]( url )$ after _outside_ [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'multiline_literals_preserve_bytes_and_format_surrounding_prose_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literals_preserve_bytes_and_format_surrounding_prose_4(run, workdir):
    """CATCHES: reimplementations that break "multiline literals preserve bytes and format surrounding prose" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '- Before `first  \n'
        '    second [x]( url )` after _outside_. Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literals_preserve_bytes_and_format_surrounding_prose_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literals_preserve_bytes_and_format_surrounding_prose_5(run, workdir):
    """CATCHES: reimplementations that break "multiline literals preserve bytes and format surrounding prose" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '> Before $first  \n'
        '>   second \\$ [x]( url )$ after _outside_. Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literals_preserve_bytes_and_format_surrounding_prose_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literals_preserve_bytes_and_format_surrounding_prose_6(run, workdir):
    """CATCHES: reimplementations that break "multiline literals preserve bytes and format surrounding prose" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before `first  \n'
        '  second [x]( url )` after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'multiline_literals_preserve_bytes_and_format_surrounding_prose_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_1(run, workdir):
    """CATCHES: reimplementations that break "ordinary gaps hard breaks and fallback keep their policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    stdin = (
        'Before   `first  \n'
        '  second` after.  \n'
        'Next   line.\t\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80'], input=stdin)
    assert result.stdout == (RES / 'ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_2(run, workdir):
    """CATCHES: reimplementations that break "ordinary gaps hard breaks and fallback keep their policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    stdin = (
        'Before `first  \n'
        '  second` after. \\\n'
        'Next line.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80'], input=stdin)
    assert result.stdout == (RES / 'ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:80', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_3(run, workdir):
    """CATCHES: reimplementations that break "ordinary gaps hard breaks and fallback keep their policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    stdin = (
        '100. Before $first\\\n'
        '    second [x]( url )$ after _outside_. Next sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80'], input=stdin)
    assert result.stdout == (RES / 'ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:80', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_4(run, workdir):
    """CATCHES: reimplementations that break "ordinary gaps hard breaks and fallback keep their policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    stdin = (
        'Before <kbd>first  \n'
        'second </kbd> after _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80'], input=stdin)
    assert result.stdout == (RES / 'ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_5(run, workdir):
    """CATCHES: reimplementations that break "ordinary gaps hard breaks and fallback keep their policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    stdin = (
        'Before <kbd>first \\\n'
        'second </kbd> after _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80'], input=stdin)
    assert result.stdout == (RES / 'ordinary_gaps_hard_breaks_and_fallback_keep_their_policy_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:80', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_terminal_literals_keep_document_final_newline_policy_1(run, workdir):
    """CATCHES: reimplementations that break "terminal literals keep document final newline policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before `code`'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'Before `code`\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_terminal_literals_keep_document_final_newline_policy_2(run, workdir):
    """CATCHES: reimplementations that break "terminal literals keep document final newline policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before prose'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == b'Before prose\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_terminal_literals_keep_document_final_newline_policy_3(run, workdir):
    """CATCHES: reimplementations that break "terminal literals keep document final newline policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '{{< call >}}\n'
        '\n'
        'Before `code`'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'terminal_literals_keep_document_final_newline_policy_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_terminal_literals_keep_document_final_newline_policy_4(run, workdir):
    """CATCHES: reimplementations that break "terminal literals keep document final newline policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '> ```markdown\n'
        '> Before `code`\n'
        '> ```'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'terminal_literals_keep_document_final_newline_policy_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_terminal_literals_keep_document_final_newline_policy_5(run, workdir):
    """CATCHES: reimplementations that break "terminal literals keep document final newline policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before `first  \r\n'
        '  second\t[x]( url )`'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'terminal_literals_keep_document_final_newline_policy_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_terminal_literals_keep_document_final_newline_policy_6(run, workdir):
    """CATCHES: reimplementations that break "terminal literals keep document final newline policy" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before `code`  \t'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `code`\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_1(run, workdir):
    """CATCHES: reimplementations that break "unwrapped nested quotes keep line scopes and depth changes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        '> > Before <tag> value.\n'
        '> > Next [r](  t  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_2(run, workdir):
    """CATCHES: reimplementations that break "unwrapped nested quotes keep line scopes and depth changes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        '> > Before <tag> value.\n'
        '> > Next [r](t) *outside*.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_3(run, workdir):
    """CATCHES: reimplementations that break "unwrapped nested quotes keep line scopes and depth changes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        '> > Before [r](  t  ) _outside_.\n'
        '> > > Next [r](  t  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_4(run, workdir):
    """CATCHES: reimplementations that break "unwrapped nested quotes keep line scopes and depth changes" (multiline literals); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '> > Before [r](t) *outside*.\n'
        '> > > Next [r](t) *outside*.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'unwrapped_nested_quotes_keep_line_scopes_and_depth_changes_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
