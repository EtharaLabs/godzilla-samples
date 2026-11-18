"""Markdown shortcodes transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_bom_angle(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for bom angle; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '\ufeff{{< notice   \n'
        'message="quoted >}} keeps   spacing"  \t\n'
        '>}}\n'
        'Format   this paragraph\n'
        'as Markdown. Second\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'bom_angle.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_bom_percent(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for bom percent; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '\ufeff   {{% notice   \n'
        'message="quoted %}} keeps   spacing"  \t\n'
        '%}}\n'
        'Format   this paragraph\n'
        'as Markdown. Second\n'
        'sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'bom_percent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directives(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for directives; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: skip -->\n'
        '::: {.note}\n'
        '{{< call   \n'
        'message="keep   spacing"   \n'
        '>}}\n'
        'Keep   this body.\n'
        ':::\n'
        '\n'
        '<!-- fmt: skip -->\n'
        '{{< skipped   token >}}\n'
        'Format   after the token.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '{{% notice message="\n'
        '<!-- fmt: on -->\n'
        '%}} still   quoted"\n'
        '%}}\n'
        'Keep   this\n'
        'body.\n'
        '{{% /notice %}}\n'
        '<!-- fmt: on -->\n'
        'Format   this\n'
        'paragraph.\n'
        '\n'
        '{{< data message="\n'
        '<!-- fmt: skip file -->\n'
        '<!-- fmt: invalid -->\n'
        '" >}}\n'
        '<!-- fmt: skip -->\n'
        'Keep   this\n'
        'paragraph.\n'
        '\n'
        'Format   this one.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '{{< whole >}}\n'
        'Keep   the whole\n'
        'body.\n'
        '{{< /whole >}}\n'
        '<!-- fmt: on -->\n'
        'Resume   formatting.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'directives.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_disabled_html_math(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for disabled html math; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: off -->\n'
        '<div>\n'
        '{{< unfinished\n'
        '</div>\n'
        '<!-- fmt: on -->\n'
        'Format   after disabled\n'
        'HTML.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '$$\n'
        '{{% unfinished\n'
        '$$\n'
        '<!-- fmt: on -->\n'
        'Format   after disabled\n'
        'display math.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'disabled_html_math.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_disabled_indented_code(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for disabled indented code; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: off -->\n'
        '\t{{< unfinished\n'
        '<!-- fmt: on -->\n'
        'Format   after tab\n'
        'indented code.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '  \t{{% unfinished\n'
        '<!-- fmt: on -->\n'
        'Format   after mixed\n'
        'indentation.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '    {{< unfinished\n'
        '<!-- fmt: on -->\n'
        'Format   after four\n'
        'spaces.\n'
        '\n'
        '\t{{% unfinished\n'
        'Format   after enabled\n'
        'indented code.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'disabled_indented_code.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_disabled_raw_blocks(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for disabled raw blocks; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<!-- fmt: off -->\n'
        '````text\n'
        '{{< unfinished\n'
        '```\n'
        '{{% still inside the longer fence\n'
        '````\n'
        'Keep   this disabled.\n'
        '<!-- fmt: on -->\n'
        'Format   after backtick\n'
        'fence.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '~~~text\n'
        '{{% unfinished message="\n'
        '~~~\n'
        '<!-- fmt: on -->\n'
        'Format   after tilde\n'
        'fence.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '<!-- ordinary comment\n'
        '```text\n'
        '{{< unfinished\n'
        '-->\n'
        '<!-- fmt: on -->\n'
        'Format   after HTML\n'
        'comment.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '<!-- ordinary comment\n'
        '<!-- fmt: on -->\n'
        'Format   after the existing\n'
        'linewise directive.\n'
        '\n'
        '<!-- fmt: off -->\n'
        '```text\n'
        '<!-- fmt: on -->\n'
        'Format   after the existing\n'
        'fenced directive.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'disabled_raw_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_independent_tokens(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for independent tokens; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{{< notice >}}\n'
        '\n'
        'First\n'
        'sentence. Second\n'
        'sentence.\n'
        '\n'
        '{{< /notice >}}\n'
        '\n'
        '{{% outer %}}\n'
        '{{< raw >}}\n'
        'Format   this\n'
        'body.\n'
        '{{% verbatim %}}\n'
        'Nested   ordinary\n'
        'Markdown.\n'
        '{{< /raw >}}\n'
        '{{% /different %}}\n'
        '{{% /verbatim %}}\n'
        '{{% /outer %}}\n'
        '\n'
        '{{< something.inline />}}\n'
        'After   the self-closing\n'
        'call.\n'
        '{{% single /%}}\n'
        '{{< /orphan >}}\n'
        '{{% /orphan %}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'independent_tokens.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_tokens(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for multiline tokens; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{{< notice   \n'
        'message="quoted >}} and \\" escapes keep   spacing"\n'
        "other='quoted \\' >}} stays' raw=`backslash \\`   \n"
        '>}}\n'
        'Format   this paragraph\n'
        'as Markdown.\n'
        '\n'
        '{{% notice\n'
        'message="{{< nested-looking >}} and %}} stay   data"\n'
        '%}}\n'
        'Format   another\n'
        'paragraph.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'multiline_tokens.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_nested_skip_file(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for nested skip file; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '```markdown\n'
        '<!-- fmt: skip file -->\n'
        '{{< notice\n'
        'message="keep   spacing"  \n'
        '>}}\n'
        'Keep   this body.  \n'
        '```\n'
        '\n'
        'Format   outside the fence.\n'
        '\n'
        '::: {.note}\n'
        '<!-- fmt: skip file -->\n'
        '{{% notice\n'
        'message="keep   spacing"  \n'
        '%}}\n'
        'Keep   this body.  \n'
        ':::\n'
        '\n'
        'Format   outside the div.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'nested_skip_file.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_placement_controls(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for placement controls; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Ordinary   prose with `{{< inline >}}` and {{ value }}.\n'
        '\n'
        'Before {{< inline >}} after.\n'
        '\n'
        '{{< single >}} Mixed   token/prose stays.   \n'
        'Following   prose formats.\n'
        '\n'
        '- {{< list >}}\n'
        '  Keep   list continuation.\n'
        '\n'
        '> {{% quote %}}\n'
        '> Keep   quote continuation.\n'
        '\n'
        '<div>\n'
        'Keep   this HTML body.\n'
        '</div>\n'
        '\n'
        '<img\n'
        'alt="Keep   this HTML argument"\n'
        'src="image.png">\n'
        '\n'
        '```text\n'
        '{{< fenced >}}\n'
        'Keep   this code.\n'
        '```\n'
        '\n'
        'After   everything.\n'
        '\n'
        '{{< title >}}\n'
        '---\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'placement_controls.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_quoted_closing_delimiter(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for quoted closing delimiter; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{{% notice\n'
        'message="quoted %}} keeps   its spacing"\n'
        '%}}\n'
        'Format   this paragraph\n'
        'as Markdown.\n'
    )
    result = run(
        ['format', '--canonical', '--wrap', 'sentence', '--stdin-file-path', 'input.md'],
        input=stdin,
    )
    assert result.stdout == (RES / 'quoted_closing_delimiter.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unterminated_fragments(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for unterminated fragments; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '::: {.callout-note}\n'
        'Before   the token.\n'
        '\n'
        '{{% notice message="unterminated\n'
        '%}}\n'
        '<!-- fmt: on -->\n'
        'Keep   this body.   \n'
        ':::\n'
        '\n'
        'Outside   the fragment.\n'
        '\n'
        '```markdown\n'
        '{{< unfinished\n'
        'Keep   this line.   \n'
        '```\n'
        '\n'
        'Format   after the fence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'unterminated_fragments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unterminated_token(run, workdir):
    """CATCHES: implementations that differ from the reference in Hugo shortcode token preservation for unterminated token; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before   the token.\n'
        '\n'
        '{{< missing\n'
        'No   delimiter here.\n'
        '\n'
        '<!-- fmt: on -->\n'
        'Keep   everything\n'
        'through the end.   \n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'unterminated_token.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
