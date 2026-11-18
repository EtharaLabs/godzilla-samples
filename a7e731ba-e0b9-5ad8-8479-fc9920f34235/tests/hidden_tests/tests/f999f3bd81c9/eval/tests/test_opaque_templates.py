"""Opaque templates behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_explicit_preservation_and_malformed_boundaries_remain_exact_1(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation and malformed boundaries remain exact" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '<!-- fmt: skip -->\n'
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after [real](  target  ) _word_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_and_malformed_boundaries_remain_exact_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_and_malformed_boundaries_remain_exact_2(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation and malformed boundaries remain exact" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        '{{ missing after [real](  target  ) _word_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_and_malformed_boundaries_remain_exact_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_and_malformed_boundaries_remain_exact_3(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation and malformed boundaries remain exact" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '{{ render({nested: 1) }} after [real](  target  ) _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'explicit_preservation_and_malformed_boundaries_remain_exact_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_and_malformed_boundaries_remain_exact_4(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation and malformed boundaries remain exact" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        '{{ good }} and {{ missing after [real](  target  ) _word_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_and_malformed_boundaries_remain_exact_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_and_malformed_boundaries_remain_exact_5(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation and malformed boundaries remain exact" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before\n'
        '{{ good }} and stray }} after [real](  target  ) _word_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'explicit_preservation_and_malformed_boundaries_remain_exact_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_explicit_preservation_and_malformed_boundaries_remain_exact_6(run, workdir):
    """CATCHES: reimplementations that break "explicit preservation and malformed boundaries remain exact" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        '{{ good }} and $$ambiguous$$ after [real](  target  ) _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'explicit_preservation_and_malformed_boundaries_remain_exact_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_configured_tokens_remain_atomic_in_nested_containers_and_link_layout_1(run, workdir):
    """CATCHES: reimplementations that break "configured tokens remain atomic in nested containers and link layout" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 4."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
        '> - Before\n'
        '>   << render("_raw_ [x](  url  )") >>\n'
        '>   after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'configured_tokens_remain_atomic_in_nested_containers_and_link_layout_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_configured_tokens_remain_atomic_in_nested_containers_and_link_layout_2(run, workdir):
    """CATCHES: reimplementations that break "configured tokens remain atomic in nested containers and link layout" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 4."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
        '> - Before << render("_raw_ [x](  url  )") >> after *word*.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'configured_tokens_remain_atomic_in_nested_containers_and_link_layout_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_configured_tokens_remain_atomic_in_nested_containers_and_link_layout_3(run, workdir):
    """CATCHES: reimplementations that break "configured tokens remain atomic in nested containers and link layout" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 4."""
    stdin = (
        '<!-- fmt: template.delimiters "[" ")" scope=next -->\n'
        'Before [a long title](target) after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'configured_tokens_remain_atomic_in_nested_containers_and_link_layout_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_configured_tokens_remain_atomic_in_nested_containers_and_link_layout_4(run, workdir):
    """CATCHES: reimplementations that break "configured tokens remain atomic in nested containers and link layout" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 4."""
    stdin = (
        '<!-- fmt: template.delimiters "[" ")" scope=next -->\n'
        'Before\n'
        '[a long title](target)\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'configured_tokens_remain_atomic_in_nested_containers_and_link_layout_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_delimiters_and_directive_scopes_protect_tokens_1(run, workdir):
    """CATCHES: reimplementations that break "delimiters and directive scopes protect tokens" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='<<', close='>>'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        '<< render(">>", "_raw_ [x](  url  )", {a: {b: 1}}) >>\n'
        'after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before << render(">>", "_raw_ [x](  url  )", {a: {b: 1}}) >> after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiters_and_directive_scopes_protect_tokens_2(run, workdir):
    """CATCHES: reimplementations that break "delimiters and directive scopes protect tokens" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='[[', close=']]'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = 'Before [[ render("]]", "_raw_ [x](  url  )", {a: {b: 1}}) ]] after *word*.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before [[ render("]]", "_raw_ [x](  url  )", {a: {b: 1}}) ]] after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_delimiters_and_directive_scopes_protect_tokens_3(run, workdir):
    """CATCHES: reimplementations that break "delimiters and directive scopes protect tokens" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='%%', close='%%'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '- Before\n'
        '  %% render("%%", "_raw_ [x](  url  )", {a: {b: 1}}) %%\n'
        '  after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'- Before %% render("%%", "_raw_ [x](  url  )", {a: {b: 1}}) %% after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiters_and_directive_scopes_protect_tokens_4(run, workdir):
    """CATCHES: reimplementations that break "delimiters and directive scopes protect tokens" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='«', close='»'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '> Before\n'
        '> « render("»", "_raw_ [x](  url  )", {a: {b: 1}}) »\n'
        '> after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'> Before \xc2\xab render("\xc2\xbb", "_raw_ [x](  url  )", {a: {b: 1}}) \xc2\xbb after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_delimiters_and_directive_scopes_protect_tokens_5(run, workdir):
    """CATCHES: reimplementations that break "delimiters and directive scopes protect tokens" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "add_delimiters = [{open='~~', close='~~'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = '> Before ~~ render("~~", "_raw_ [x](  url  )", {a: {b: 1}}) ~~ after *word*.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'> Before ~~ render("~~", "_raw_ [x](  url  )", {a: {b: 1}}) ~~ after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_delimiters_and_directive_scopes_protect_tokens_6(run, workdir):
    """CATCHES: reimplementations that break "delimiters and directive scopes protect tokens" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    files = {
        'yamark.toml': (
            '[template]\n'
            "replace_delimiters = [{open='`%', close='%>'}]\n"
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        '`% render("%>", "_raw_ [x](  url  )", {a: {b: 1}}) %>\n'
        'after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'Before `% render("%>", "_raw_ [x](  url  )", {a: {b: 1}}) %> after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_late_delimiters_reconsider_raw_semantics_inside_the_expression_1(run, workdir):
    """CATCHES: reimplementations that break "late delimiters reconsider raw semantics inside the expression" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        'Before\n'
        '<< render(">>", "a\u3000b", "\\LaTeX") >>\n'
        'after _word_.\n'
        '\n'
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'late_delimiters_reconsider_raw_semantics_inside_the_expression_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_late_delimiters_reconsider_raw_semantics_inside_the_expression_2(run, workdir):
    """CATCHES: reimplementations that break "late delimiters reconsider raw semantics inside the expression" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        'Before << render(">>", "a\u3000b", "\\LaTeX") >> after *word*.\n'
        '\n'
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'late_delimiters_reconsider_raw_semantics_inside_the_expression_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_multiline_configured_delimiters_do_not_expand_inline_support(run, workdir):
    """CATCHES: reimplementations that break "multiline configured delimiters do not expand inline support" (opaque templates); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'replace_delimiters = [{open="<<\\n", close=">>"}]\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'Before\n'
        '<<\n'
        'keep   this >> after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_configured_delimiters_do_not_expand_inline_support.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_supported_containers_and_fragments_share_the_formatter_1(run, workdir):
    """CATCHES: reimplementations that break "supported containers and fragments share the formatter" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        '- Before\n'
        '  {{ render("keep   this") }}\n'
        '  after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'- Before {{ render("keep   this") }} after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_supported_containers_and_fragments_share_the_formatter_2(run, workdir):
    """CATCHES: reimplementations that break "supported containers and fragments share the formatter" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        '* Before\n'
        '  {{ render("keep   this") }}\n'
        '  after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'- Before {{ render("keep   this") }} after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_supported_containers_and_fragments_share_the_formatter_3(run, workdir):
    """CATCHES: reimplementations that break "supported containers and fragments share the formatter" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '> Before\n'
        '> {{ render("keep   this") }}\n'
        '> after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'> Before {{ render("keep   this") }} after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_supported_containers_and_fragments_share_the_formatter_4(run, workdir):
    """CATCHES: reimplementations that break "supported containers and fragments share the formatter" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = '> > Before {{ render("keep   this") }} after *word*.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == b'> > Before {{ render("keep   this") }} after *word*.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_supported_containers_and_fragments_share_the_formatter_5(run, workdir):
    """CATCHES: reimplementations that break "supported containers and fragments share the formatter" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Term\n'
        ':   Before\n'
        '    {{ render("keep   this") }}\n'
        '    after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'supported_containers_and_fragments_share_the_formatter_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_supported_containers_and_fragments_share_the_formatter_6(run, workdir):
    """CATCHES: reimplementations that break "supported containers and fragments share the formatter" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        '::: note\n'
        'Before {{ render("keep   this") }} after *word*.\n'
        ':::\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'supported_containers_and_fragments_share_the_formatter_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_tokens_are_opaque_under_every_wrapping_mode_1(run, workdir):
    """CATCHES: reimplementations that break "tokens are opaque under every wrapping mode" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        "{# don't   change [x](  url  ) _this_ { #}\n"
        'after _word_. Next\n'
        'line.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'tokens_are_opaque_under_every_wrapping_mode_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_tokens_are_opaque_under_every_wrapping_mode_2(run, workdir):
    """CATCHES: reimplementations that break "tokens are opaque under every wrapping mode" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = 'Before {# "quoted-looking closer #} after _word_. Next line.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before {# "quoted-looking closer #} after _word_. Next line.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'paragraph', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_tokens_are_opaque_under_every_wrapping_mode_3(run, workdir):
    """CATCHES: reimplementations that break "tokens are opaque under every wrapping mode" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after _word_. Next\n'
        'line.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'tokens_are_opaque_under_every_wrapping_mode_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_tokens_are_opaque_under_every_wrapping_mode_4(run, workdir):
    """CATCHES: reimplementations that break "tokens are opaque under every wrapping mode" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        'Before\n'
        '{{ render("}}", "say \\"hello\\"", {outer: {inner: \'a  b\'}}) }}\n'
        'after _word_. Next\n'
        'line.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '240', '--canonical'], input=stdin)
    assert result.stdout == b'Before {{ render("}}", "say \\"hello\\"", {outer: {inner: \'a  b\'}}) }} after *word*. Next line.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_tokens_are_opaque_under_every_wrapping_mode_5(run, workdir):
    """CATCHES: reimplementations that break "tokens are opaque under every wrapping mode" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        'Before {{ render("[x](  url  ) _keep_ `code` $math$") }} after *word*.\n'
        'Next line.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:240', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'tokens_are_opaque_under_every_wrapping_mode_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence:240', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_tokens_are_opaque_under_every_wrapping_mode_6(run, workdir):
    """CATCHES: reimplementations that break "tokens are opaque under every wrapping mode" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before\n'
        '{{ render("<b>  </b>", "x\\ty", "café\u3000東京") }}\n'
        'after\n'
        '*word*.\n'
        'Next\n'
        'line.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '8', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'tokens_are_opaque_under_every_wrapping_mode_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '8', '--canonical', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_transcripts_are_exact_and_idempotent_1(run, workdir):
    """CATCHES: reimplementations that break "transcripts are exact and idempotent" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 6."""
    stdin = (
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'Before {{ render("keep   this") }} after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_transcripts_are_exact_and_idempotent_2(run, workdir):
    """CATCHES: reimplementations that break "transcripts are exact and idempotent" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 6."""
    stdin = (
        'Before\n'
        "{# don't   alter this #}\n"
        'after _word_ and [link](  url  ).\n'
        '\n'
        '> Before\n'
        '> {# " _literal_ [x](  url  ) { }} ` $ < a\u3000b #}\n'
        '> after _word_.\n'
        '\n'
        '- Before\n'
        "  {# 'first #}{# second { #}\n"
        '  after _word_.\n'
        '\n'
        'Before\n'
        '{# missing closer\n'
        'after _word_.\n'
        '\n'
        'Before {#identifier}\n'
        '{# next line #}\n'
        'after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'transcripts_are_exact_and_idempotent_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_transcripts_are_exact_and_idempotent_3(run, workdir):
    """CATCHES: reimplementations that break "transcripts are exact and idempotent" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 3 of 6."""
    stdin = (
        '<!-- fmt: skip -->\n'
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after [real](  target  ) _word_.\n'
        '\n'
        '<!-- fmt: off -->\n'
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after [real](  target  ) _word_.\n'
        '<!-- fmt: on -->\n'
        '\n'
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after [real](  target  ) _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'transcripts_are_exact_and_idempotent_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_transcripts_are_exact_and_idempotent_4(run, workdir):
    """CATCHES: reimplementations that break "transcripts are exact and idempotent" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 4 of 6."""
    stdin = (
        '<!-- fmt: template.delimiters "[" ")" scope=next -->\n'
        'Before\n'
        '[a long title](target)\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'transcripts_are_exact_and_idempotent_4.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', '8', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_transcripts_are_exact_and_idempotent_5(run, workdir):
    """CATCHES: reimplementations that break "transcripts are exact and idempotent" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 5 of 6."""
    stdin = (
        '- Before {{ render("keep   this") }} after [real](target) *outside*.\n'
        '\n'
        '> Before {{ render("keep   this") }} after [real](target) *outside*.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'transcripts_are_exact_and_idempotent_5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_transcripts_are_exact_and_idempotent_6(run, workdir):
    """CATCHES: reimplementations that break "transcripts are exact and idempotent" (opaque templates); any difference in the stdout, stderr or exit status from the reference fails. Variant 6 of 6."""
    stdin = (
        'Before with {{ "foo" }} after [real](target) *outside*.\n'
        '\n'
        'Before with {{ foo | filter }} after [real](target) *outside*.\n'
        '\n'
        'Before with {{ foo({ bar }) }} after [real](target) *outside*.\n'
        '\n'
        'Before with {{{ foo }}} after [real](target) *outside*.\n'
        '\n'
        'Before with {{ foo {{ bar }} }} after [real](target) *outside*.\n'
        '\n'
        'Before with {% foo %} after [real](target) *outside*.\n'
        '\n'
        'Before with {# foo #} after [real](target) *outside*.\n'
        '\n'
        'Before with <% foo %> after [real](target) *outside*.\n'
    )
    result = run(
        ['format', '--canonical', '--wrap', 'sentence', '--stdin-file-path', 'input.md'],
        input=stdin,
    )
    assert result.stdout == (RES / 'transcripts_are_exact_and_idempotent_6.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--canonical', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
