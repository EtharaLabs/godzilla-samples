"""Literal emphasis behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_literal_emphasis_cases_are_exact_and_idempotent_1(run, workdir):
    """CATCHES: reimplementations that break "literal emphasis cases are exact and idempotent" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '# _Before `_a_ [x]( url )` after_\n'
        '\n'
        '# _Before $x + _a_ [x]( url )$ after_\n'
        '\n'
        '# _Before **`_a_ [x](< url >)`** after_\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'literal_emphasis_cases_are_exact_and_idempotent_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_cases_are_exact_and_idempotent_2(run, workdir):
    """CATCHES: reimplementations that break "literal emphasis cases are exact and idempotent" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Lead _Before `_a_ *b* [x](  url  )` after_ [real](  target  ).\n'
        '\n'
        '- __Before $x + __a__ **b** [x]( url )$ after__ [real](  target  ).\n'
        '\n'
        '> _Before ``_a_ ` *b*`` after_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_cases_are_exact_and_idempotent_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_cases_are_exact_and_idempotent_3(run, workdir):
    """CATCHES: reimplementations that break "literal emphasis cases are exact and idempotent" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '# _before \\` literal_ after `code`\n'
        '\n'
        '# _before \\$ literal_ after $math$\n'
        '\n'
        '# _before \\[ literal_ after ](target)\n'
        '\n'
        '# \\`_word_\\` and \\$__word__\\$\n'
        '\n'
        '# $a \\$ _literal_ *stars* [x](  url  )$ after _outside_\n'
        '\n'
        '# _Before $a \\$ _literal_ [x]( url )$ after_\n'
        '\n'
        '# _unclosed `_literal_` then ``unmatched\n'
        '\n'
        '# _before \\`` literal_ after ``code``\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_cases_are_exact_and_idempotent_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_cases_are_exact_and_idempotent_4(run, workdir):
    """CATCHES: reimplementations that break "literal emphasis cases are exact and idempotent" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '# _Before <kbd title="`">raw</kbd> after_ and `code`\n'
        '\n'
        '# _Before [link](`target) after_ and `code`\n'
        '\n'
        'Before <kbd>_raw_</kbd> after _outside_ [real](  target  ).\n'
        '\n'
        'Before <42 `_raw_`> after _outside_ [real](  target  ).\n'
        '\n'
        'Before _with `{{ value }} _raw_` inside_ after [real](  target  ).\n'
        '\n'
        '- Before {{ value }} _raw_ [real](  target  ).\n'
        '\n'
        'Before *```` unmatched `[x](  url  )`* after [r](  t  ).\n'
        '\n'
        'Before `code`` [x](  url  ) tail` after [r](  t  ).\n'
        '\n'
        'Before $$[x](  url  )$$ after _outside_ [r](  t  ).\n'
        '\n'
        '# Before ``unmatched _word_` after _outside_\n'
        '\n'
        '# _Before <kbd>_raw_</kbd> after_\n'
        '\n'
        '# _Before [raw _text_](target) after_\n'
        '\n'
        '# _Before <42 _raw_> after_\n'
        '\n'
        '# _Before {key="_raw_"} after_\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_cases_are_exact_and_idempotent_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_cases_are_exact_and_idempotent_5(run, workdir):
    """CATCHES: reimplementations that break "literal emphasis cases are exact and idempotent" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Lead *Before `*a*` after* tail.\n'
        '\n'
        '- Lead _Before $_a_$ after_ tail.\n'
        '\n'
        '> Lead **Before `**a**` after** tail.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'literal_emphasis_cases_are_exact_and_idempotent_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_cases_are_exact_and_idempotent_6(run, workdir):
    """CATCHES: reimplementations that break "literal emphasis cases are exact and idempotent" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before *x *x *x late* after.\n'
        '\n'
        'Before **x *x ***x **x late** after.\n'
        '\n'
        'Before ***x **x *x ***x late*** after.\n'
        '\n'
        'Before \\*escaped* and *x \\*x *x late* after.\n'
        '\n'
        'Before \\_escaped_ and _x \\_x _x late_ after.\n'
        '\n'
        'Before word_name and _x a_b _x late_ after.\n'
        '\n'
        'Before *\u2003 *x \xa0* late* after.\n'
        '\n'
        'Before _\u2003 _x \xa0_ late_ after.\n'
        '\n'
        'Before *x *x\n'
        '*x late* after.\n'
        '\n'
        'Before *x\n'
        'late* after.\n'
        '\n'
        'Before *x `literal *x *x` *x late* after.\n'
        '\n'
        'Before _x $literal _x \\$ _x$ _x late_ after.\n'
        '\n'
        'Before *x `literal\n'
        '*x` *x late* after.\n'
        '\n'
        'Before _x [raw _word_](target) _x late_ after.\n'
        '\n'
        'Before _x <kbd>_raw_</kbd> _x late_ after.\n'
        '\n'
        'Before _x {key="_raw_"} _x late_ after.\n'
        '\n'
        'Before _x [raw\n'
        '_word_](target) _x late_ after.\n'
        '\n'
        'Before `{{ foo }}` *x *x *x after.\n'
        '\n'
        'Before `code` *x *x *x after.\n'
        '\n'
        'Before *x *x *x after.\n'
        '\n'
        '# _\u2003_ and _outside_\n'
        '\n'
        '# _\xa0_ and _outside_\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_cases_are_exact_and_idempotent_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_noncanonical_literal_contents_and_surrounding_emphasis_stay_exact_1(run, workdir):
    """CATCHES: reimplementations that break "noncanonical literal contents and surrounding emphasis stay exact" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '# _Before `_a_ *b* [x]( url )` after_\n'
        '\n'
        'Lead `_a_ *b*` and $a \\$ __b__ **c**$ after _outside_ [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'noncanonical_literal_contents_and_surrounding_emphasis_stay_exact_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_noncanonical_literal_contents_and_surrounding_emphasis_stay_exact_2(run, workdir):
    """CATCHES: reimplementations that break "noncanonical literal contents and surrounding emphasis stay exact" (literal emphasis); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '# _Before `_a_ *b* [x]( url )` after_\n'
        '\n'
        'Lead `_a_ *b*` and $a \\$ __b__ **c**$ after _outside_ [real](target).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'noncanonical_literal_contents_and_surrounding_emphasis_stay_exact_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
