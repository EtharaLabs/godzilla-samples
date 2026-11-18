"""Markdown templates transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_opaque_template_backtick(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template backtick; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: template.delimiters "`%" "%>" scope=file -->\n'
        'Before\n'
        '`% keep   this %>\n'
        'after _word_ and `code   stays`.\n'
        '\n'
        '- Before\n'
        '  `% render("a\u3000b", "%>") %>\n'
        '  after [link](  url  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_backtick.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        '{{ render("unterminated }} after [real](  target  ) _word_.\n'
        '\n'
        'Before\n'
        '{{ render({nested: 1) }} after [real](  target  ) _word_.\n'
        '\n'
        'Before\n'
        '{{ render("multi\n'
        'line") }} after [real](  target  ) _word_.\n'
        '\n'
        'Before\n'
        '{{ render("[x](  url  ) _raw_") }} with `[x](  url  ) _code_` and $[x](  url  )$ after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_brackets(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template brackets; the exact stdout, stderr, exit status are compared."""
    stdin = '[outer [outer [label]]] <% keep   this %>\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'opaque_template_brackets.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_comments(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template comments; the exact stdout, stderr, exit status are compared."""
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
    assert result.stdout == (RES / 'opaque_template_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_configured(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template configured; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: template.delimiters "<<" ">>" scope=file -->\n'
        'Before\n'
        '<< render(">>", "_keep_ [x](  url  )") >>\n'
        'after _outside_.\n'
        '\n'
        '> - Before\n'
        '>   << render("_raw_ [x](  url  )") >>\n'
        '>   after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_configured.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_configured_atomic(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template configured atomic; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: template.delimiters "[" ")" scope=next -->\n'
        'Before [a long title](target) after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', '8'], input=stdin)
    assert result.stdout == (RES / 'opaque_template_configured_atomic.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_containers(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template containers; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Before\n'
        '  {{ render("keep   this") }}\n'
        '  after [real](  target  ) _outside_.\n'
        '\n'
        '> Before\n'
        '> {{ render("keep   this") }}\n'
        '> after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_containers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_contents(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template contents; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        'with {{ render("}}", "keep   this") }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{ render("say \\"}}\\"", \'it\\\'s   here\') }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{ render({outer: {inner: "a   b"}}) }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with prefix{{ render("[x](  url  ) _keep_ **this** `code`") }}suffix, after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{ first("a   b") }} and {{ second("c   d") }} after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_contents.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_hard_breaks(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template hard breaks; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        '{{ render("keep   this") }}  \n'
        'after.\n'
        '\n'
        'Before\\\n'
        '{{ render("keep   this") }}\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'opaque_template_hard_breaks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_late_raw(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template late raw; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '::: note\n'
        'Before\n'
        '%% render("a\u3000b") %%\n'
        'after _word_.\n'
        ':::\n'
        '\n'
        '```markdown\n'
        'Before\n'
        '%% render("a\u3000b") %%\n'
        'after _word_.\n'
        '```\n'
        '\n'
        '<!-- fmt: template.delimiters "%%" "%%" scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_late_raw.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_none(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template none; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before   _word_\n'
        '{{ render("_keep_ [x](  url  )") }}\n'
        'after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'opaque_template_none.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_overlapping(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template overlapping; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: template.delimiters "{{" "END" scope=file -->\n'
        '<!-- fmt: template.delimiters "{{!" "FIN" scope=file -->\n'
        'Before\n'
        '{{ value END\n'
        'after _word_ and {{ ordinary.name }}.\n'
        '\n'
        '> Before\n'
        '> {{ render("a\u3000b") END\n'
        '> after _word_.\n'
        '\n'
        'Before\n'
        '{{! keep   this FIN\n'
        'after _word_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--canonical', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'opaque_template_overlapping.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_placement(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template placement; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == b'Before {{ render("keep   this") }} after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_preservation(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template preservation; the exact stdout, stderr, exit status are compared."""
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
    assert result.stdout == (RES / 'opaque_template_preservation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_opaque_template_width(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for opaque template width; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before {{ customer.name }} after.\n'
        '\n'
        'Before supercalifragilisticexpialidocious after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '20'], input=stdin)
    assert result.stdout == (RES / 'opaque_template_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_table_template_spans(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for table template spans; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '| Include | Target |\n'
        '|---|---|\n'
        '| footer | {{< include _footer.md >}} |\n'
        '\n'
        '| Name | Value |\n'
        '|---|---|\n'
        '| title | `{{{< meta title >}}}` |\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'table_template_spans.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_basic(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare basic; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with {{ foo }}. Second\n'
        'sentence.\n'
    )
    result = run(['format', '--wrap', 'sentence', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_bare_basic.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_canonical(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare canonical; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with {{   user.name   }} and [real](  target  ). Second\n'
        'sentence with _outside_.\n'
    )
    result = run(
        ['format', '--canonical', '--wrap', 'sentence', '--stdin-file-path', 'input.md'],
        input=stdin,
    )
    assert result.stdout == (RES / 'template_bare_canonical.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_column(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare column; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before {{   user.name   }} after some more\n'
        'prose with [real](  t  ).\n'
    )
    result = run(['format', '--wrap', '36', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_bare_column.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_complex(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare complex; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        'with {{ "foo" }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{ foo | filter }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{ foo({ bar }) }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{{ foo }}} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {{ foo {{ bar }} }} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {% foo %} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with {# foo #} after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        'with <% foo %> after [real](  target  ) _outside_.\n'
    )
    result = run(
        ['format', '--canonical', '--wrap', 'sentence', '--stdin-file-path', 'input.md'],
        input=stdin,
    )
    assert result.stdout == (RES / 'template_bare_complex.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_mixed(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare mixed; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with {{ foo }} and `{{ complex | filter }} [x](  url  )`. Second\n'
        'sentence with _outside_.\n'
    )
    result = run(
        ['format', '--canonical', '--wrap', 'sentence', '--stdin-file-path', 'input.md'],
        input=stdin,
    )
    assert result.stdout == (RES / 'template_bare_mixed.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_narrow(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare narrow; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        'with {{   user.name   }} after [real](  target  ) _outside_.\n'
    )
    result = run(['format', '--canonical', '--wrap', '12', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_bare_narrow.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_standalone(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare standalone; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        '{{ foo }}\n'
        'after [real](  target  ) _outside_.\n'
        '\n'
        'Before\n'
        '{{ foo }} {{ bar }}\n'
        'after.\n'
    )
    result = run(
        ['format', '--canonical', '--wrap', 'sentence', '--stdin-file-path', 'input.md'],
        input=stdin,
    )
    assert result.stdout == (RES / 'template_bare_standalone.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_bare_target(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template bare target; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First\n'
        'with {{ foo }} and [real](  target  ). Second\n'
        'sentence.\n'
        '\n'
        '<!-- fmt: skip -->\n'
        'First\n'
        'with {{ foo }} and [real](  target  ). Second\n'
        'sentence.\n'
    )
    result = run(['format', '--wrap', 'none', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_bare_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_code_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template code boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with `{{ foo }}` and {{ outside }}. Second\n'
        'sentence.\n'
        '\n'
        'First\n'
        'sentence with `{{ foo }}` < value and [real](  target  ). Second\n'
        'sentence.\n'
        '\n'
        'First\n'
        'sentence with `{{ foo` }}. Second\n'
        'sentence.\n'
        '\n'
        'First\n'
        'sentence with `{{ foo` and `bar }}`. Second\n'
        'sentence.\n'
        '\n'
        'Following\n'
        'paragraph with [real](  target  ). Next\n'
        'sentence.\n'
    )
    result = run(['format', '--wrap', 'sentence', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_code_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_code_issue_2(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template code issue 2; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with `${{ foo }}`. Second\n'
        'sentence.\n'
    )
    result = run(['format', '--wrap', 'sentence', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_code_issue_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_code_links(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template code links; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with `{{ foo }} [x](  url  )`. Second\n'
        'sentence with [real](  target  ).\n'
    )
    result = run(['format', '--wrap', 'sentence', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_code_links.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_code_narrow(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template code narrow; the exact stdout, stderr, exit status are compared."""
    stdin = 'Before `{{ foo }} ![x](  long-image-target  ) _literal_` after [real](  t  ).\n'
    result = run(['format', '--wrap', '16', '--stdin-file-path', 'input.md', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'template_code_narrow.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_code_nested_markup(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template code nested markup; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        '*`<% keep   this %>`* after.\n'
        '\n'
        'Before\n'
        '[`<% keep   this %>`](url) after.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'template_code_nested_markup.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_template_code_target(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template code target; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: wrap=sentence scope=next -->\n'
        'First\n'
        'sentence with `<% foo %>`. Second\n'
        'sentence with [real](  target  ).\n'
    )
    result = run(['format', '--wrap', 'none', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_code_target.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_container_continuations(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template container continuations; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- {{ render_item() }}\n'
        '  Follow-up prose.\n'
        '\n'
        '> {{ render_item() }}\n'
        '> Follow-up prose.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'template_container_continuations.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_html_paragraph_boundary(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template html paragraph boundary; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before\n'
        '<span>{{ foo }}</span> after.\n'
        '\n'
        'Following\n'
        'prose.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'template_html_paragraph_boundary.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_mismatched_backticks(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template mismatched backticks; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'First\n'
        'sentence with ``{{ keep   this }}```. Second\n'
        'sentence.\n'
    )
    result = run(['format', '--wrap', 'sentence', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_mismatched_backticks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_template_multiline_code_wrapping(run, workdir):
    """CATCHES: implementations that differ from the reference in template-span handling in Markdown for template multiline code wrapping; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before   `{{\n'
        '  render(customer.delivery_address)\n'
        '}}` after the template and more prose.\n'
    )
    result = run(['format', '--wrap', '20', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'template_multiline_code_wrapping.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '20', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
