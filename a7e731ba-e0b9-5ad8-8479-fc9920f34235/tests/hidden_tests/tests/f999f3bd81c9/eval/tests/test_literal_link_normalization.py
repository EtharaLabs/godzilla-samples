"""Literal link normalization behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_angle_inputs_preserve_links_during_normalization_1(run, workdir):
    """CATCHES: reimplementations that break "angle inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before <kbd title="`">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <kbd title="`">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_angle_inputs_preserve_links_during_normalization_2(run, workdir):
    """CATCHES: reimplementations that break "angle inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before <kbd title="`">[r](  t  )</kbd> then `tail` after [s]( u ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before <kbd title="`">[r](  t  )</kbd> then `tail` after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_angle_inputs_preserve_links_during_normalization_3(run, workdir):
    """CATCHES: reimplementations that break "angle inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before <http://a/`> [r](  t  ) then `tail` after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240', '--canonical'], input=stdin)
    assert result.stdout == b'Before <http://a/`> [r]( t ) then `tail` after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angle_inputs_preserve_links_during_normalization_4(run, workdir):
    """CATCHES: reimplementations that break "angle inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before <kbd title="$">[r](  t  )</kbd> then $tail$ after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <kbd title="$">[r](  t  )</kbd> then $tail$ after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_angle_inputs_preserve_links_during_normalization_5(run, workdir):
    """CATCHES: reimplementations that break "angle inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before <kbd title="$">[r](  t  )</kbd> then $tail$ after [s]( u ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before <kbd title="$">[r](  t  )</kbd> then $tail$ after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_angle_inputs_preserve_links_during_normalization_6(run, workdir):
    """CATCHES: reimplementations that break "angle inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before <http://a/$> [r](  t  ) then $tail$ after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240', '--canonical'], input=stdin)
    assert result.stdout == b'Before <http://a/$> [r]( t ) then $tail$ after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angles_consumed_by_links_and_attributes_keep_literal_protection_1(run, workdir):
    """CATCHES: reimplementations that break "angles consumed by links and attributes keep literal protection" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before `[x](  u  )` [a](  <target>  ) then `[y](  v  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `[x](  u  )` [a](<target>) then `[y](  v  )` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angles_consumed_by_links_and_attributes_keep_literal_protection_2(run, workdir):
    """CATCHES: reimplementations that break "angles consumed by links and attributes keep literal protection" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before `[x](  u  )` [a](  <target>  ) then `[y](  v  )` after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `[x](  u  )` [a](<target>) then `[y](  v  )` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angles_consumed_by_links_and_attributes_keep_literal_protection_3(run, workdir):
    """CATCHES: reimplementations that break "angles consumed by links and attributes keep literal protection" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before `[x](  u  )` [a](  target  ){key="<"} then `[y](  v  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `[x](  u  )` [a](target){key="<"} then `[y](  v  )` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angles_consumed_by_links_and_attributes_keep_literal_protection_4(run, workdir):
    """CATCHES: reimplementations that break "angles consumed by links and attributes keep literal protection" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before `[x](  u  )` [a](  target  ){key="<"} then `[y](  v  )` after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `[x](  u  )` [a](target){key="<"} then `[y](  v  )` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angles_consumed_by_links_and_attributes_keep_literal_protection_5(run, workdir):
    """CATCHES: reimplementations that break "angles consumed by links and attributes keep literal protection" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before `[x](  u  )` [a][<target>] then `[y](  v  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `[x](  u  )` [a][<target>] then `[y](  v  )` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angles_consumed_by_links_and_attributes_keep_literal_protection_6(run, workdir):
    """CATCHES: reimplementations that break "angles consumed by links and attributes keep literal protection" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before `[x](  u  )` [a][<target>] then `[y](  v  )` after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `[x](  u  )` [a][<target>] then `[y](  v  )` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angle_compatibility_respects_literals_and_escapes_1(run, workdir):
    """CATCHES: reimplementations that break "angle compatibility respects literals and escapes" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before `<!-- > [x](  v  ) -->` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `<!-- > [x](  v  ) -->` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angle_compatibility_respects_literals_and_escapes_2(run, workdir):
    """CATCHES: reimplementations that break "angle compatibility respects literals and escapes" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before `<kbd title="<!--">[x](  v  )</kbd> -->` after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `<kbd title="<!--">[x](  v  )</kbd> -->` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angle_compatibility_respects_literals_and_escapes_3(run, workdir):
    """CATCHES: reimplementations that break "angle compatibility respects literals and escapes" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before <!--> `[x](  v  )` after [r]( t ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before <!--> `[x](  v  )` after [r]( t ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_angle_compatibility_respects_literals_and_escapes_4(run, workdir):
    """CATCHES: reimplementations that break "angle compatibility respects literals and escapes" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before $<!-- > [x](  v  ) -->$ after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before $<!-- > [x](  v  ) -->$ after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angle_compatibility_respects_literals_and_escapes_5(run, workdir):
    """CATCHES: reimplementations that break "angle compatibility respects literals and escapes" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before $<kbd title="<!--">[x](  v  )</kbd> -->$ after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before $<kbd title="<!--">[x](  v  )</kbd> -->$ after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_angle_compatibility_respects_literals_and_escapes_6(run, workdir):
    """CATCHES: reimplementations that break "angle compatibility respects literals and escapes" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before <!--> $[x](  v  )$ after [r]( t ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before <!--> $[x](  v  )$ after [r]( t ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_comment_inputs_preserve_links_during_normalization_1(run, workdir):
    """CATCHES: reimplementations that break "comment inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before <!-- ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!-- ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_comment_inputs_preserve_links_during_normalization_2(run, workdir):
    """CATCHES: reimplementations that break "comment inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before <!-- > ` --> [r](  t  ) then `tail after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_comment_inputs_preserve_links_during_normalization_3(run, workdir):
    """CATCHES: reimplementations that break "comment inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before <!-- > `[x](  v  ) ![i](  p  )` --> [r](  t  ) then `[code](  c  )`.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!-- > `[x](  v  ) ![i](  p  )` --> [r](  t  ) then `[code](  c  )`.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_comment_inputs_preserve_links_during_normalization_4(run, workdir):
    """CATCHES: reimplementations that break "comment inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before <!-- $ --> [r](  t  ) then $tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!-- $ --> [r](  t  ) then $tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_comment_inputs_preserve_links_during_normalization_5(run, workdir):
    """CATCHES: reimplementations that break "comment inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before <!-- > $ --> [r](  t  ) then $tail after [s](  u  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before <!-- > $ --> [r](  t  ) then $tail after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_comment_inputs_preserve_links_during_normalization_6(run, workdir):
    """CATCHES: reimplementations that break "comment inputs preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before <!-- > $[x](  v  ) ![i](  p  )$ --> [r](  t  ) then $[code](  c  )$.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!-- > $[x](  v  ) ![i](  p  )$ --> [r](  t  ) then $[code](  c  )$.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_declaration_and_backtick_reports_keep_their_baseline_cli_output_1(run, workdir):
    """CATCHES: reimplementations that break "declaration and backtick reports keep their baseline cli output" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before <!DOCTYPE x "`"> [r](  t  ) then `tail` after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!DOCTYPE x "`"> [r](  t  ) then `tail` after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_declaration_and_backtick_reports_keep_their_baseline_cli_output_2(run, workdir):
    """CATCHES: reimplementations that break "declaration and backtick reports keep their baseline cli output" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before `code`` [x](url) tail` after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `code`` [x](url) tail` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_declaration_and_backtick_reports_keep_their_baseline_cli_output_3(run, workdir):
    """CATCHES: reimplementations that break "declaration and backtick reports keep their baseline cli output" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before `code`` [x](  url  ) tail` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before `code`` [x](url) tail` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_declaration_and_backtick_reports_keep_their_baseline_cli_output_4(run, workdir):
    """CATCHES: reimplementations that break "declaration and backtick reports keep their baseline cli output" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before *```` unmatched `code`` [x](url) tail`* after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'Before *```` unmatched `code`` [x](url) tail`* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_declaration_and_backtick_reports_keep_their_baseline_cli_output_5(run, workdir):
    """CATCHES: reimplementations that break "declaration and backtick reports keep their baseline cli output" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before *```` unmatched `code`` [x](  url  ) tail`* after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before *```` unmatched `code`` [x](url) tail`* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_declaration_and_backtick_reports_keep_their_baseline_cli_output_6(run, workdir):
    """CATCHES: reimplementations that break "declaration and backtick reports keep their baseline cli output" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before *```` unmatched `[x](  url  )`* after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before *```` unmatched `[x](  url  )`* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_link_normalization_keeps_escaped_and_unsupported_controls_1(run, workdir):
    """CATCHES: reimplementations that break "link normalization keeps escaped and unsupported controls" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before \\`[x](  url  )\\` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before \\`[x](url)\\` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_keeps_escaped_and_unsupported_controls_2(run, workdir):
    """CATCHES: reimplementations that break "link normalization keeps escaped and unsupported controls" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before \\$![x](url)\\$ after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'Before \\$![x](url)\\$ after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_link_normalization_keeps_escaped_and_unsupported_controls_3(run, workdir):
    """CATCHES: reimplementations that break "link normalization keeps escaped and unsupported controls" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before ``[x](  url  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'Before ``[x](  url  )` after [r](  t  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_link_normalization_keeps_escaped_and_unsupported_controls_4(run, workdir):
    """CATCHES: reimplementations that break "link normalization keeps escaped and unsupported controls" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before [x](  two words  ) after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before [x](  two words  ) after [r](  t  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_link_normalization_keeps_escaped_and_unsupported_controls_5(run, workdir):
    """CATCHES: reimplementations that break "link normalization keeps escaped and unsupported controls" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before \\``[x](url)\\`` after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'Before \\``[x](url)\\`` after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_link_normalization_keeps_escaped_and_unsupported_controls_6(run, workdir):
    """CATCHES: reimplementations that break "link normalization keeps escaped and unsupported controls" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before *``[x](  url  )`* after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before *``[x](url)`* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_preserves_recognized_literals_1(run, workdir):
    """CATCHES: reimplementations that break "link normalization preserves recognized literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '[before](  a  ) ![before](  b  )\n'
        'Before `[x](  url  )` after [real](  target  ) ![real](  image  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_preserves_recognized_literals_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_preserves_recognized_literals_2(run, workdir):
    """CATCHES: reimplementations that break "link normalization preserves recognized literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '> [before](  a  ) ![before](  b  )\n'
        '> Before `![x](  image  )` after [real](  target  ) ![real](  image  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'> [before](a) ![before](b) Before `![x](  image  )` after [real](target) ![real](image) _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_preserves_recognized_literals_3(run, workdir):
    """CATCHES: reimplementations that break "link normalization preserves recognized literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '- [before](  a  ) ![before](  b  )\n'
        '  Before ```[x](  url  ) `` ![y](  image  )``` after [real](  target  ) ![real](  image  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'- [before](a) ![before](b) Before ```[x](  url  ) `` ![y](  image  )``` after [real](target) ![real](image) _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_preserves_recognized_literals_4(run, workdir):
    """CATCHES: reimplementations that break "link normalization preserves recognized literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '[before](  a  ) ![before](  b  )\n'
        'Before $![x](  image  )$ after [real](  target  ) ![real](  image  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_preserves_recognized_literals_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_preserves_recognized_literals_5(run, workdir):
    """CATCHES: reimplementations that break "link normalization preserves recognized literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '> [before](  a  ) ![before](  b  )\n'
        '> Before $a \\$ [x](  url  ) ![y](  image  )$ after [real](  target  ) ![real](  image  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'> [before](a) ![before](b) Before $a \\$ [x](  url  ) ![y](  image  )$ after [real](target) ![real](image) _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_preserves_recognized_literals_6(run, workdir):
    """CATCHES: reimplementations that break "link normalization preserves recognized literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '- [before](  a  ) ![before](  b  )\n'
        '  Before **with $![x](  image  )$ inside** after [real](  target  ) ![real](  image  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'- [before](a) ![before](b) Before **with $![x](  image  )$ inside** after [real](target) ![real](image) _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_wraps_around_overwide_literals_1(run, workdir):
    """CATCHES: reimplementations that break "link normalization wraps around overwide literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before [b](  s  ). `[x](  long-link-target  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_wraps_around_overwide_literals_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_wraps_around_overwide_literals_2(run, workdir):
    """CATCHES: reimplementations that break "link normalization wraps around overwide literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = '- Before [b](  s  ). `[x](  long-link-target  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_wraps_around_overwide_literals_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_wraps_around_overwide_literals_3(run, workdir):
    """CATCHES: reimplementations that break "link normalization wraps around overwide literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = '> Before [b](  s  ). `[x](  long-link-target  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_wraps_around_overwide_literals_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_wraps_around_overwide_literals_4(run, workdir):
    """CATCHES: reimplementations that break "link normalization wraps around overwide literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before [b](  s  ). $![x](  long-image-target  )$ after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_wraps_around_overwide_literals_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_wraps_around_overwide_literals_5(run, workdir):
    """CATCHES: reimplementations that break "link normalization wraps around overwide literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = '- Before [b](  s  ). $![x](  long-image-target  )$ after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_wraps_around_overwide_literals_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_normalization_wraps_around_overwide_literals_6(run, workdir):
    """CATCHES: reimplementations that break "link normalization wraps around overwide literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = '> Before [b](  s  ). $![x](  long-image-target  )$ after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'link_normalization_wraps_around_overwide_literals_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_targets_and_attributes_do_not_open_literals_1(run, workdir):
    """CATCHES: reimplementations that break "link targets and attributes do not open literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before [a](  `x  ) [b](  target  ) [c](  `y  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before [a](`x) [b](target) [c](`y).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_targets_and_attributes_do_not_open_literals_2(run, workdir):
    """CATCHES: reimplementations that break "link targets and attributes do not open literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before [a](  x  ){key="`"} [b](  target  ) [c](  y  ){key="`"}.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'Before [a](x){key="`"} [b](target) [c](y){key="`"}.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_targets_and_attributes_do_not_open_literals_3(run, workdir):
    """CATCHES: reimplementations that break "link targets and attributes do not open literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before ![a](`x) [b](target) ![c](`y).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before ![a](`x) [b](target) ![c](`y).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_link_targets_and_attributes_do_not_open_literals_4(run, workdir):
    """CATCHES: reimplementations that break "link targets and attributes do not open literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before [a](  $x  ) [b](  target  ) [c](  $y  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before [a]($x) [b](target) [c]($y).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_targets_and_attributes_do_not_open_literals_5(run, workdir):
    """CATCHES: reimplementations that break "link targets and attributes do not open literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before [a](  x  ){key="$"} [b](  target  ) [c](  y  ){key="$"}.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'Before [a](x){key="$"} [b](target) [c](y){key="$"}.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_targets_and_attributes_do_not_open_literals_6(run, workdir):
    """CATCHES: reimplementations that break "link targets and attributes do not open literals" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before ![a]($x) [b](target) ![c]($y).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before ![a]($x) [b](target) ![c]($y).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angle_preservation_does_not_disable_other_paragraphs_1(run, workdir):
    """CATCHES: reimplementations that break "raw angle preservation does not disable other paragraphs" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'raw_angle_preservation_does_not_disable_other_paragraphs_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_preservation_does_not_disable_other_paragraphs_2(run, workdir):
    """CATCHES: reimplementations that break "raw angle preservation does not disable other paragraphs" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'raw_angle_preservation_does_not_disable_other_paragraphs_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_preservation_does_not_disable_other_paragraphs_3(run, workdir):
    """CATCHES: reimplementations that break "raw angle preservation does not disable other paragraphs" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'raw_angle_preservation_does_not_disable_other_paragraphs_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_preservation_does_not_disable_other_paragraphs_4(run, workdir):
    """CATCHES: reimplementations that break "raw angle preservation does not disable other paragraphs" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'raw_angle_preservation_does_not_disable_other_paragraphs_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_preservation_does_not_disable_other_paragraphs_5(run, workdir):
    """CATCHES: reimplementations that break "raw angle preservation does not disable other paragraphs" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == (RES / 'raw_angle_preservation_does_not_disable_other_paragraphs_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_preservation_does_not_disable_other_paragraphs_6(run, workdir):
    """CATCHES: reimplementations that break "raw angle preservation does not disable other paragraphs" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'raw_angle_preservation_does_not_disable_other_paragraphs_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_spellings_preserve_links_during_normalization_1(run, workdir):
    """CATCHES: reimplementations that break "raw angle spellings preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before <!DOCTYPE x "`"> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!DOCTYPE x "`"> [r](  t  ) then `tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angle_spellings_preserve_links_during_normalization_2(run, workdir):
    """CATCHES: reimplementations that break "raw angle spellings preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before <42 `> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before <42 `> [r](  t  ) then `tail after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_spellings_preserve_links_during_normalization_3(run, workdir):
    """CATCHES: reimplementations that break "raw angle spellings preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before <42> `[x](  u  )` after [r]( t ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before <42> `[x](  u  )` after [r]( t ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angle_spellings_preserve_links_during_normalization_4(run, workdir):
    """CATCHES: reimplementations that break "raw angle spellings preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before <!DOCTYPE x "$"> [r](  t  ) then $tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <!DOCTYPE x "$"> [r](  t  ) then $tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angle_spellings_preserve_links_during_normalization_5(run, workdir):
    """CATCHES: reimplementations that break "raw angle spellings preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before <42 $> [r](  t  ) then $tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before <42 $> [r](  t  ) then $tail after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_angle_spellings_preserve_links_during_normalization_6(run, workdir):
    """CATCHES: reimplementations that break "raw angle spellings preserve links during normalization" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before <42> $[x](  u  )$ after [r]( t ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before <42> $[x](  u  )$ after [r]( t ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angles_preserve_the_entire_normalization_input_1(run, workdir):
    """CATCHES: reimplementations that break "raw angles preserve the entire normalization input" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before `[keep](  u  )` < x <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `[keep](  u  )` < x <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angles_preserve_the_entire_normalization_input_2(run, workdir):
    """CATCHES: reimplementations that break "raw angles preserve the entire normalization input" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before `[a](  u  )` <kbd> then `[b](  v  )` after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'Before `[a](  u  )` <kbd> then `[b](  v  )` after [r](  t  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angles_preserve_the_entire_normalization_input_3(run, workdir):
    """CATCHES: reimplementations that break "raw angles preserve the entire normalization input" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before `[a](  u  )` <kbd> then `[b](  v  )` after [r]( t ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before `[a](  u  )` <kbd> then `[b](  v  )` after [r]( t ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angles_preserve_the_entire_normalization_input_4(run, workdir):
    """CATCHES: reimplementations that break "raw angles preserve the entire normalization input" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before `[a](  u  )` < value then `[b](  v  )` after [r]( t ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `[a](  u  )` < value then `[b](  v  )` after [r]( t ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angles_preserve_the_entire_normalization_input_5(run, workdir):
    """CATCHES: reimplementations that break "raw angles preserve the entire normalization input" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before `[keep](  u  )` < x <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before `[keep](  u  )` < x <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_angles_preserve_the_entire_normalization_input_6(run, workdir):
    """CATCHES: reimplementations that break "raw angles preserve the entire normalization input" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before `[keep](  u  )` < x <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `[keep](  u  )` < x <!-- > ` --> [r](  t  ) then `tail after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_review_examples_preserve_ambiguous_links_1(run, workdir):
    """CATCHES: reimplementations that break "review examples preserve ambiguous links" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before <kbd title="> `">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before <kbd title="> `">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_review_examples_preserve_ambiguous_links_2(run, workdir):
    """CATCHES: reimplementations that break "review examples preserve ambiguous links" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before <kbd title="> `">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before <kbd title="> `">[r](  t  )</kbd> then `tail` after [s]( u ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_review_examples_preserve_ambiguous_links_3(run, workdir):
    """CATCHES: reimplementations that break "review examples preserve ambiguous links" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'a < b <kbd title="`">[r](  t  )</kbd> then `tail`\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'a < b <kbd title="`">[r](  t  )</kbd> then `tail`\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_review_examples_preserve_ambiguous_links_4(run, workdir):
    """CATCHES: reimplementations that break "review examples preserve ambiguous links" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'a < b <kbd title="`">[r](  t  )</kbd> then `tail`\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'a < b <kbd title="`">[r](  t  )</kbd> then `tail`\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_review_examples_preserve_ambiguous_links_5(run, workdir):
    """CATCHES: reimplementations that break "review examples preserve ambiguous links" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before <!-- ` --> [r](  t  ) then `tail` after [s](  u  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before <!-- ` --> [r](  t  ) then `tail` after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_review_examples_preserve_ambiguous_links_6(run, workdir):
    """CATCHES: reimplementations that break "review examples preserve ambiguous links" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before <!-- $ --> [r](  t  ) then $tail$ after [s](  u  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'Before <!-- $ --> [r](  t  ) then $tail$ after [s](  u  ).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_template_contents_stay_exact_while_surrounding_links_reflow_1(run, workdir):
    """CATCHES: reimplementations that break "template contents stay exact while surrounding links reflow" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before `[x](  url  ) {{ value }}` after [r](  t  ) _outside_.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before `[x](  url  ) {{ value }}` after [r](t) _outside_.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_contents_stay_exact_while_surrounding_links_reflow_2(run, workdir):
    """CATCHES: reimplementations that break "template contents stay exact while surrounding links reflow" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        '`[x](  url  ) {{ value }}`\n'
        'after [r](t)\n'
        '_outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'template_contents_stay_exact_while_surrounding_links_reflow_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_template_contents_stay_exact_while_surrounding_links_reflow_3(run, workdir):
    """CATCHES: reimplementations that break "template contents stay exact while surrounding links reflow" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = '- Before $![x](  url  )$ {{ value }} after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'- Before $![x](  url  )$ {{ value }} after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_contents_stay_exact_while_surrounding_links_reflow_4(run, workdir):
    """CATCHES: reimplementations that break "template contents stay exact while surrounding links reflow" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = '> Before `[x](  url  )` {{ value }} after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'> Before `[x](  url  )` {{ value }} after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_contents_stay_exact_while_surrounding_links_reflow_5(run, workdir):
    """CATCHES: reimplementations that break "template contents stay exact while surrounding links reflow" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '> Before\n'
        '> `[x](  url  )`\n'
        '> {{ value }}\n'
        '> after [r](t).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'template_contents_stay_exact_while_surrounding_links_reflow_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '16', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_template_contents_stay_exact_while_surrounding_links_reflow_6(run, workdir):
    """CATCHES: reimplementations that break "template contents stay exact while surrounding links reflow" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
        'Before `[x](  url  )` << value >> after [r](  t  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'template_contents_stay_exact_while_surrounding_links_reflow_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unmatched_backtick_run_keeps_later_literals_and_links_distinct_1(run, workdir):
    """CATCHES: reimplementations that break "unmatched backtick run keeps later literals and links distinct" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = 'Before *```` [raw](  u  ) ``[x](  v  )``* after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unmatched_backtick_run_keeps_later_literals_and_links_distinct_2(run, workdir):
    """CATCHES: reimplementations that break "unmatched backtick run keeps later literals and links distinct" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unmatched_backtick_run_keeps_later_literals_and_links_distinct_3(run, workdir):
    """CATCHES: reimplementations that break "unmatched backtick run keeps later literals and links distinct" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = 'Before *```` [raw](  u  ) ``[x](  v  )``* after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unmatched_backtick_run_keeps_later_literals_and_links_distinct_4(run, workdir):
    """CATCHES: reimplementations that break "unmatched backtick run keeps later literals and links distinct" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = 'Before *```` [raw](  u  ) ``[x](  v  )``* after [r](  t  ).\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unmatched_backtick_run_keeps_later_literals_and_links_distinct_5(run, workdir):
    """CATCHES: reimplementations that break "unmatched backtick run keeps later literals and links distinct" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = 'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240'], input=stdin)
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '240', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unmatched_backtick_run_keeps_later_literals_and_links_distinct_6(run, workdir):
    """CATCHES: reimplementations that break "unmatched backtick run keeps later literals and links distinct" (literal link normalization); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = 'Before *```` [raw](  u  ) ``[x](  v  )``* after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240'], input=stdin)
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
