"""`fmt:` directive parsing, scoping and errors across hosts, plus Python/R source targets.

Pins the exact diagnostics (`path:line:col: error: ...`) for malformed directives in
Markdown (`<!-- fmt: ... -->`), YAML (`# fmt: ...`) and Python/R (`# fmt: ...`) hosts, the
accepted value spellings, template-delimiter quoting and escapes, and the documented rules
for Python/R comment, string and hashpipe-YAML targets.
"""

import os  # noqa: F401

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

UPPER_SCRIPT = "import sys\nsys.stdout.write(sys.stdin.read().upper())\n"
MARK_SCRIPT = "import sys\nfor line in sys.stdin:\n    sys.stdout.write('|' + line.upper())\n"
UPPER_CONFIG = (
    '[embedded.up]\n'
    'formatter = { command = ["python3", "up_script", "{path}"], path_suffix = ".txt" }\n'
)


def _fmt(run, path, stdin, *extra):
    return run(["format", "--stdin-file-path", path, *extra], input=stdin)


# ---------------------------------------------------------------------------
# Python and R hosts: malformed directive comments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        ("in.py", "# fmt:\nx = 1\n", "in.py:1:1: error: invalid fmt directive: empty\n"),
        (
            "in.py",
            "def f():\n    # fmt: skip scope=nope\n    x = 1\n",
            "in.py:2:5: error: fmt: skip does not support scope=nope\n",
        ),
        ("in.py", "# fmt: skip foo bar\nx = 1\n", "in.py:1:1: error: invalid fmt: skip directive\n"),
        ("in.R", "# fmt: off scope=all\nx <- 1\n", "in.R:1:1: error: fmt: off does not support scope=all\n"),
        ("in.py", "# fmt: off now\nx = 1\n", "in.py:1:1: error: invalid fmt: off directive\n"),
        ("in.R", "# fmt: on scope=file\nx <- 1\n", "in.R:1:1: error: fmt: on does not support explicit scope\n"),
    ],
    ids=["empty", "skip-unknown-scope-indented", "skip-extra-words", "off-unknown-scope",
         "off-extra-word", "on-with-scope"],
)
def test_source_preserve_control_directive_errors(run, path, stdin, stderr):
    """CATCHES: an implementation that silently ignores malformed `# fmt:` skip/off/on comments in Python or R files instead of failing with the exact message, or that reports the column of the line start instead of the `#` column for an indented directive."""
    result = _fmt(run, path, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        (
            "in.py",
            "# fmt: markdown scope=file\nx = 1\n",
            "in.py:1:1: error: fmt: markdown with scope=file requires at least one option\n",
        ),
        (
            "in.R",
            "# fmt: markdown scope=from-here\nx <- 1\n",
            "in.R:1:1: error: fmt: markdown with scope=from-here requires at least one option\n",
        ),
        ("in.py", "# fmt: markdown color=red\nx = 1\n", "in.py:1:1: error: invalid fmt directive option: color=red\n"),
        ("in.r", "# fmt: markdown footnotes=maybe\nx <- 1\n", "in.r:1:1: error: invalid fmt: footnotes option\n"),
        ("in.py", "# fmt: markdown canonical=maybe\nx = 1\n", "in.py:1:1: error: invalid fmt: canonical option\n"),
        (
            "in.py",
            "# fmt: markdown table-widths=wide\nx = 1\n",
            "in.py:1:1: error: fmt: table-widths must be fit or preserve\n",
        ),
        (
            "in.py",
            "# fmt: compact=false scope=file\n#| a:\n#|   - 1\n",
            "in.py:1:1: error: invalid fmt directive option: compact=false\n",
        ),
    ],
    ids=["markdown-file-no-option", "markdown-from-here-no-option", "unknown-option",
         "bad-footnotes", "bad-canonical", "bad-table-widths", "yaml-only-compact-option"],
)
def test_source_markdown_directive_option_errors(run, path, stdin, stderr):
    """CATCHES: an implementation that lets a broad-scope `fmt: markdown` without options turn plain source into Markdown, accepts misspelled scopes or unknown option values, or accepts the YAML-only `compact=` option on a Python-level comment."""
    result = _fmt(run, path, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        ("in.py", "# fmt: compact\nx = 1\n", "in.py:1:1: error: invalid fmt directive: compact\n"),
        ("in.R", "# fmt: table compact\nx <- 1\n", "in.R:1:1: error: invalid fmt directive: table compact\n"),
        (
            "in.py",
            "# fmt: embedded python scope=file\nx = '''\nhi\n'''\n",
            "in.py:1:1: error: fmt: embedded does not support scope=file\n",
        ),
        (
            "in.py",
            "# fmt: embedded python r\nx = 1\n",
            "in.py:1:1: error: invalid fmt directive: embedded python r\n",
        ),
        (
            "in.py",
            "# fmt: python scope=from-here\nx = 1\n",
            "in.py:1:1: error: fmt: python does not support scope=from-here\n",
        ),
        ("in.py", "# fmt: python extra\nx = 1\n", "in.py:1:1: error: invalid fmt directive: python extra\n"),
    ],
    ids=["compact", "table", "embedded-scope-file", "embedded-two-names", "shorthand-scope-from-here",
         "shorthand-extra-word"],
)
def test_source_yaml_only_and_embedded_directive_errors(run, path, stdin, stderr):
    """CATCHES: an implementation that accepts YAML collection directives (`compact`, `table`) in Python/R comments, or that lets embedded-formatter directives take a scope other than `next` or more than one formatter name."""
    result = _fmt(run, path, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        (
            "in.py",
            "# fmt: embedded nosuch scope=next\nx = '''\nhi\n'''\n",
            "in.py:3:1: error: unknown embedded formatter: nosuch\n",
        ),
        (
            "in.R",
            "# fmt: nosuch\nx <- r\"(\nabc\n)\"\n",
            "in.R:3:1: error: unknown embedded formatter: nosuch\n",
        ),
    ],
    ids=["python-embedded-keyword", "r-shorthand"],
)
def test_source_unknown_embedded_formatter_reported_at_string_body(run, path, stdin, stderr):
    """CATCHES: an implementation that accepts an unknown formatter name in a Python/R directive, or reports it at the directive comment instead of at the first byte of the targeted string body."""
    result = _fmt(run, path, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        (
            '# fmt: template.delimiters << >> scope=file\nx = 1\n',
            "in.py:1:1: error: fmt: template.delimiters requires exactly two quoted delimiter strings\n",
        ),
        (
            '# fmt: template.delimiters "<<" scope=file\nx = 1\n',
            "in.py:1:1: error: fmt: template.delimiters requires exactly two quoted delimiter strings\n",
        ),
        (
            '# fmt: template.delimiters "" ">>" scope=file\nx = 1\n',
            "in.py:1:1: error: fmt: template.delimiters values must not be empty\n",
        ),
        ('# fmt: template.delimiters "<<"x ">>"\nx = 1\n', "in.py:1:1: error: invalid fmt directive quoting\n"),
        ('# fmt: template.delimiters a"b ">>"\nx = 1\n', "in.py:1:1: error: invalid fmt directive quoting\n"),
        ('# fmt: template.delimiters ">>" "<<\nx = 1\n', "in.py:1:1: error: invalid fmt directive quoting\n"),
        ('# fmt: template.delimiters "<<" ">>\\\nx = 1\n', "in.py:1:1: error: invalid fmt directive quoting\n"),
    ],
    ids=["unquoted", "one-value", "empty-value", "text-after-quote", "quote-inside-word", "unterminated",
         "trailing-backslash"],
)
def test_source_template_delimiter_argument_errors(run, stdin, stderr):
    """CATCHES: an implementation that accepts unquoted, empty, or single delimiter arguments, or that tolerates malformed quoting (text glued to a closing quote, a quote inside a bare word, an unterminated string, or a dangling backslash escape)."""
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


def test_source_bare_template_directive_between_code_needs_explicit_scope(run):
    """CATCHES: an implementation that guesses a scope for a bare `fmt: template.delimiters` sandwiched between code lines instead of requiring an explicit scope when it is neither isolated nor directly before a target."""
    stdin = 'x = 1\n# fmt: template.delimiters "<<" ">>"\ny = 2\n'
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == "in.py:2:1: error: fmt: template.delimiters needs explicit scope\n"
    assert result.returncode == 1


def test_source_bare_template_directive_before_another_directive_needs_explicit_scope(run):
    """CATCHES: an implementation that treats a following `# fmt: markdown` directive line as the target of a bare template directive instead of rejecting the ambiguous placement."""
    stdin = 'x = 1\n# fmt: template.delimiters "<<" ">>"\n# fmt: markdown\ny = \'\'\'\n<<a>>   b\n\'\'\'\n'
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == "in.py:2:1: error: fmt: template.delimiters needs explicit scope\n"
    assert result.returncode == 1


def test_source_bare_template_directive_targets_next_hashpipe_block(run):
    """CATCHES: an implementation that applies a bare template directive placed directly before a hashpipe block to later blocks too (or rejects it); only the next block containing `<<x>>` must be preserved byte-for-byte while the later block is formatted."""
    stdin = (
        'x = 1\n'
        '# fmt: template.delimiters "<<" ">>"\n'
        '#| a:   <<x>>\n'
        '#| b:   2\n'
        '\n'
        '#| c:   <<y>>\n'
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "bare_template_next_hashpipe.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_source_explicit_next_template_directive_in_r(run):
    """CATCHES: an implementation that ignores an explicit `scope=next` on a template directive in an R file, so the hashpipe block containing the custom delimiter would be reformatted instead of preserved."""
    stdin = (
        'x <- 1\n'
        '# fmt: template.delimiters "<<" ">>" scope=next\n'
        '#| a:   <<x>>\n'
        '#| b:   2\n'
        '\n'
        '#| c:   <<y>>\n'
    )
    result = _fmt(run, "in.R", stdin)
    assert result.stdout == (RES / "explicit_next_template_r.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Markdown host
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        ("Para text\n<!-- fmt: -->\n", "in.md:2:6: error: invalid fmt directive: empty\n"),
        ("Para text\n<!-- fmt: compact table -->\n", "in.md:2:6: error: invalid fmt directive: compact table\n"),
        ("Para text\n<!-- fmt: embedded python -->\n", "in.md:2:6: error: invalid fmt directive: embedded python\n"),
        ("Para text\n<!-- fmt: table compact -->\n", "in.md:2:6: error: invalid fmt directive: table compact\n"),
        ("Para text\n<!-- fmt: python -->\n", "in.md:2:6: error: invalid fmt directive: python\n"),
        (
            "Para text\n<!-- fmt: wrap=none scope=everywhere -->\n",
            "in.md:2:6: error: invalid fmt directive scope: everywhere\n",
        ),
        (
            "Para text\n<!-- fmt: template.delimiters open=<< close=>> -->\n",
            "in.md:2:6: error: fmt: template.delimiters requires exactly two quoted delimiter strings\n",
        ),
    ],
    ids=["empty", "compact-table", "embedded-name", "table-compact", "formatter-shorthand", "unknown-scope",
         "template-key-value"],
)
def test_markdown_rejects_non_markdown_directives_after_paragraph(run, stdin, stderr):
    """CATCHES: an implementation that treats a directive comment directly after a paragraph line as paragraph text, or that accepts empty directives, YAML-only (`table`, `compact table`) or formatter (`embedded`, `python`) directives, misspelled scopes, or `open=`/`close=` delimiter keys in a Markdown host; the error column points at `fmt:` inside the comment."""
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        (
            "<!-- fmt: markdown scope=file -->\n\nText\n",
            "in.md:1:6: error: fmt: markdown with scope=file requires at least one option\n",
        ),
        ("<!-- fmt: on scope=file -->\n\nText\n", "in.md:1:6: error: fmt: on does not support explicit scope\n"),
        (
            "<!-- fmt: skip scope=whatever -->\n\nText\n",
            "in.md:1:6: error: fmt: skip does not support scope=whatever\n",
        ),
        (
            "<!-- fmt: wrap=none colour=blue -->\n\nText\n",
            "in.md:1:6: error: invalid fmt directive option: colour=blue\n",
        ),
        ("<!-- fmt: footnotes=keep -->\n\nText\n", "in.md:1:6: error: invalid fmt: footnotes option\n"),
    ],
    ids=["markdown-file-no-option", "on-with-scope", "skip-unknown-scope", "unknown-option", "bad-footnotes"],
)
def test_markdown_directive_errors(run, stdin, stderr):
    """CATCHES: an implementation that silently ignores malformed `<!-- fmt: ... -->` comments (a broad `markdown` scope without options, a scoped `on`, an unsupported skip scope, an unknown option or value) instead of failing at the `fmt:` column with the exact message."""
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


def test_markdown_from_here_options_directly_after_paragraph(run):
    """CATCHES: an implementation that requires blank lines around a `<!-- fmt: ... -->` directive, or that applies a `scope=from-here` option set (wrap=sentence and friends) to the paragraph before the directive."""
    stdin = (
        "Para   text\n"
        "<!-- fmt: wrap=sentence table-widths=preserve canonical=yes footnotes=preserve scope=from-here -->\n"
        "Next one.  Second   one.\n"
    )
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == (RES / "markdown_from_here_after_paragraph.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_bare_canonical_next_after_paragraph(run):
    """CATCHES: an implementation that rejects a bare `canonical` flag or the redundant `markdown` word in an option-only Markdown directive, or that applies `scope=next` to the preceding paragraph rather than the following one."""
    stdin = "A __b__   text\n<!-- fmt: canonical scope=next markdown -->\nC __d__   text.\n\nE __f__.\n"
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == (RES / "markdown_bare_canonical_next.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_file_scope_options_directly_after_paragraph(run):
    """CATCHES: an implementation that applies an option-only `scope=file` directive placed directly under a paragraph line only to later content, leaving the paragraph above it unwrapped."""
    stdin = "Para   one.  Two.\n<!-- fmt: wrap=sentence scope=file -->\nThree.  Four.\n"
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == (RES / "markdown_file_scope_after_paragraph.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_target_directive_applies_to_next_block_only(run):
    """CATCHES: an implementation that lets `<!-- fmt: markdown wrap=sentence -->` (default scope next) leak into later blocks instead of applying sentence wrapping to the next paragraph only."""
    stdin = "<!-- fmt: markdown wrap=sentence -->\nOne.  Two   three.\n\nFour.  Five.\n"
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == (RES / "markdown_target_next_only.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_file_scope_markdown_directive_reaches_earlier_content(run):
    """CATCHES: an implementation that applies `fmt: markdown wrap=sentence scope=file` only after the directive; file scope must also rewrite the paragraph above it."""
    stdin = "Intro.  Here.\n\n<!-- fmt: markdown wrap=sentence scope=file -->\n\nOne.  Two.\n"
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == (RES / "markdown_file_scope_earlier.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_canonical_zero_overrides_cli_canonical(run):
    """CATCHES: an implementation that does not accept `0` as a false canonical value, or lets the `--canonical` flag win over a file-scope `canonical=0` directive, rewriting `__b__` to `**b**`."""
    stdin = "<!-- fmt: canonical=0 scope=file -->\n\nA __b__   c.\n"
    result = _fmt(run, "in.md", stdin, "--canonical")
    assert result.stdout == (RES / "markdown_canonical_zero.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        (
            '<!-- fmt: template.delimiters "[\\"" "\\"]" scope=file -->\n\nKeep ["a   b"] here   now.\n',
            "template_escape_quote.golden",
        ),
        (
            '<!-- fmt: template.delimiters "%\\\\" "\\\\%" scope=file -->\n\nKeep %\\ a   b \\% here   now.\n',
            "template_escape_backslash.golden",
        ),
        (
            '<!-- fmt: template.delimiters "<\\t" "\\q>" scope=file -->\n\nKeep <\ta   b q> here   now.\n',
            "template_escape_tab_and_unknown.golden",
        ),
        (
            '<!-- fmt: template.delimiters "<<\\n" ">>" scope=file -->\n\nKeep   <<\na   b>> here   now.\n\nOther   text.\n',
            "template_escape_newline.golden",
        ),
        (
            '<!-- fmt: template.delimiters "<<\\r\\n" ">>" scope=file -->\r\n\r\nKeep   <<\r\na   b>> here   now.\r\n\r\nOther   text.\r\n',
            "template_escape_crlf.golden",
        ),
    ],
    ids=["escaped-quote", "escaped-backslash", "tab-and-unknown-escape", "newline", "carriage-return"],
)
def test_markdown_template_delimiter_escapes(run, stdin, golden):
    """CATCHES: an implementation that does not decode `\\"`, `\\\\`, `\\t`, `\\n` and `\\r` inside quoted delimiter arguments (or that rejects an unknown escape such as `\\q` instead of keeping the escaped character), so the custom template span would not be found and the paragraph around it would be re-spaced."""
    result = _fmt(run, "in.md", stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# YAML host
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdin", "stderr"),
    [
        ("# fmt: on\na: 1\n", "in.yaml:1:1: error: fmt: on without active fmt: off\n"),
        ("# fmt: compact=maybe\na: [1, 2]\n", "in.yaml:1:1: error: invalid fmt: compact option\n"),
        ("# fmt: compact sometimes\na: [1, 2]\n", "in.yaml:1:1: error: invalid fmt: compact directive\n"),
        (
            "# fmt: table scope=from-here\n- {a: 1}\n",
            "in.yaml:1:1: error: fmt: table does not support scope=from-here\n",
        ),
        (
            "# fmt: compact table scope=file\n- {a: 1}\n",
            "in.yaml:1:1: error: fmt: table does not support scope=file\n",
        ),
        ("# fmt: table scope=later\n- {a: 1}\n", "in.yaml:1:1: error: fmt: table does not support scope=later\n"),
        ("# fmt: table wide\n- {a: 1}\n", "in.yaml:1:1: error: invalid fmt: table directive\n"),
        ("# fmt: python scope=file\na: |\n  x\n", "in.yaml:1:1: error: fmt: python does not support scope=file\n"),
        (
            "# fmt: embedded r scope=from-here\na: |\n  x\n",
            "in.yaml:1:1: error: fmt: embedded does not support scope=from-here\n",
        ),
        (
            'a: 1\n# fmt: template.delimiters "<<" ">>"\n',
            "in.yaml:2:1: error: fmt: template.delimiters needs explicit scope\n",
        ),
    ],
    ids=["stray-on", "compact-bad-bool", "compact-bad-word", "table-from-here", "compact-table-file",
         "table-unknown-scope", "table-extra-word", "shorthand-scope-file", "embedded-scope-from-here",
         "bare-template-on-last-line"],
)
def test_yaml_directive_errors(run, stdin, stderr):
    """CATCHES: an implementation that tolerates a stray `fmt: on`, non-boolean compact values, table directives with any scope other than next, embedded-formatter directives with broad scopes, or a bare template directive at the end of a YAML file with no target after it."""
    result = _fmt(run, "in.yaml", stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("stdin", "extra", "golden"),
    [
        ("# fmt: compact=false\na:\n  - 1\n  - 2\nb:\n  - 3\n", ["--compact"], "yaml_compact_eq_false.golden"),
        ("# fmt: compact compact=no\na:\n  - 1\n  - 2\nb:\n  - 3\n", ["--compact"], "yaml_compact_compact_no.golden"),
        ("# fmt: compact true\na:\n  - 1\n  - 2\nb:\n  - 3\n", [], "yaml_compact_true_word.golden"),
        (
            "a:\n  - 0\n# fmt: compact false scope=from-here\nb:\n  - 1\nc:\n  - 2\n",
            ["--compact"],
            "yaml_compact_false_from_here.golden",
        ),
    ],
    ids=["compact-eq-false", "compact-then-compact-no", "compact-true-word", "compact-false-from-here"],
)
def test_yaml_compact_directive_value_spellings(run, stdin, extra, golden):
    """CATCHES: an implementation that mis-parses the compact value spellings (`compact=false`, a later `compact=no` overriding the bare keyword, separated `true`/`false`) or that applies a next-scoped compact directive to more than one collection."""
    result = _fmt(run, "in.yaml", stdin, *extra)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        (
            "# fmt: table compact scope=next\n- name: a\n  value: 1\n- name: bbb\n  value: 22\n",
            "yaml_table_compact_scope_next.golden",
        ),
        (
            "# fmt: table compact=true\n- {name: a, value: 1}\n- {name: bbb, value: 22}\n",
            "yaml_table_compact_true.golden",
        ),
    ],
    ids=["table-compact-scope-next", "table-compact-eq-true"],
)
def test_yaml_table_compact_equivalent_spellings(run, stdin, golden):
    """CATCHES: an implementation that rejects the documented `fmt: table compact` / `fmt: table compact=true` spellings or an explicit `scope=next`, instead of collapsing block rows to flow mappings and aligning their columns."""
    result = _fmt(run, "in.yaml", stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_file_scope_directives_merge_table_widths(run):
    """CATCHES: an implementation where a second `scope=file` directive replaces the first instead of merging with it; both sentence wrapping and preserved table widths must reach Markdown scalars, including the one before the directives."""
    stdin = (
        'a: !md "One.  Two."\n'
        "# fmt: wrap=sentence scope=file\n"
        "# fmt: table-widths=preserve scope=file\n"
        "b: !md |\n"
        "  Three.  Four.\n"
        "\n"
        "  | x      | y |\n"
        "  |---|---|\n"
        "  | 1 | 2 |\n"
    )
    result = _fmt(run, "in.yaml", stdin)
    assert result.stdout == (RES / "yaml_file_scope_merge_table_widths.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_yaml_file_scope_directives_merge_footnotes(run):
    """CATCHES: an implementation that drops `footnotes=preserve` when it arrives in a second file-scope directive, so the footnote definition would be re-wrapped instead of preserved."""
    stdin = (
        "# fmt: wrap=sentence scope=file\n"
        "# fmt: footnotes=preserve scope=file\n"
        "a: !md |\n"
        "  One.  Two.[^1]\n"
        "\n"
        "  [^1]:   Foot   note.\n"
    )
    result = _fmt(run, "in.yaml", stdin)
    assert result.stdout == (RES / "yaml_file_scope_merge_footnotes.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Python / R: preserve controls, scopes and option directives
# ---------------------------------------------------------------------------


def test_python_fmt_off_skips_on_comments_inside_strings(run):
    """CATCHES: an implementation that scans line by line inside a `fmt: off` region and treats a `# fmt: on` line inside a triple-quoted string (supported or `b'''` unsupported) as the end of the region."""
    stdin = (
        "# fmt: off\n"
        "x  =  '''\n"
        "# fmt: on\n"
        "*  kept\n"
        "'''\n"
        "y = b'''\n"
        "# fmt: on\n"
        "'''\n"
        "# fmt: on\n"
        "# fmt: markdown\n"
        "z = '''\n"
        "*  a\n"
        "'''\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_off_strings.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_fmt_off_skips_on_comments_inside_strings(run):
    """CATCHES: an implementation that ends an R `fmt: off` region at a `# fmt: on` line inside a raw string, or that mistakes a one-line raw string for a multi-line one while scanning the disabled region."""
    stdin = (
        "# fmt: off\n"
        'x <- r"(\n'
        "# fmt: on\n"
        ')"\n'
        'y <- r"(a)"\n'
        "# fmt: on\n"
        "# fmt: markdown\n"
        'z <- "\n'
        "*  a\n"
        '"\n'
    )
    result = _fmt(run, "in.R", stdin)
    assert result.stdout == (RES / "r_off_strings.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_fmt_off_preserves_through_end_of_file(run, workdir):
    """CATCHES: an implementation that requires a closing `fmt: on` in Python files or formats a string inside the open-ended disabled region."""
    stdin = "# fmt: off\nx  =  '''\n*  a\n'''\n"
    (workdir / "in.py").write_text(stdin)
    result = run(["format", "--check", "in.py"])
    assert result.stdout == b""
    assert result.stderr.decode() == "1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({"in.py": stdin})


def test_python_option_only_file_scope_patches_earlier_string_target(run):
    """CATCHES: an implementation that applies a trailing option-only `# fmt: wrap=sentence scope=file` only to later content, missing the earlier marked comment block and triple-quoted string."""
    stdin = (
        "# fmt: markdown\n"
        "# One.  Two   three.\n"
        "\n"
        "# fmt: markdown\n"
        "x = '''\n"
        "Four.  Five.\n"
        "'''\n"
        "\n"
        "# fmt: wrap=sentence scope=file\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_file_scope_patches_string.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_option_only_from_here_applies_to_later_targets(run):
    """CATCHES: an implementation that treats an option-only `scope=from-here` directive as marking content, or fails to apply sentence wrapping to both later marked targets."""
    stdin = (
        "# fmt: wrap=sentence scope=from-here\n"
        "\n"
        "# fmt: markdown\n"
        "# One.  Two.\n"
        "\n"
        "# fmt: markdown\n"
        "x = '''\n"
        "Three.  Four.\n"
        "'''\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_from_here_wrap.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_markdown_marker_with_table_widths_preserve(run):
    """CATCHES: an implementation that ignores `table-widths=preserve` on a source `fmt: markdown` marker, re-fitting the table columns while it still normalizes the list marker."""
    stdin = (
        "# fmt: markdown table-widths=preserve\n"
        "x = '''\n"
        "*  item\n"
        "\n"
        "| a      | b |\n"
        "|---|---|\n"
        "| c | d |\n"
        "'''\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_table_widths_preserve.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_markdown_marker_with_canonical_and_footnotes_none(run):
    """CATCHES: an implementation that rejects a bare `canonical` flag or `footnotes=none` on a source marker, or that formats the footnote definition despite `none` requesting preservation."""
    stdin = (
        "# fmt: markdown canonical footnotes=none wrap=none\n"
        "x = '''\n"
        "A __b__   note.[^1]\n"
        "\n"
        "[^1]:   Foot   note.\n"
        "'''\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_canonical_footnotes_none.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_source_hugo_shortcode_is_not_a_default_template(run):
    """CATCHES: an implementation that treats a Hugo shortcode `{{< ... >}}` as a default `{{ }}` template span in a marked source comment, preserving the whole comment instead of formatting it."""
    stdin = "# fmt: markdown\n# A   {{< ref x >}}\n\n# fmt: markdown\n# B   {{ ref y }}\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "source_hugo_shortcode.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Python / R: comment and hashpipe prefixes
# ---------------------------------------------------------------------------


def test_python_comment_target_starting_with_bare_hash(run):
    """CATCHES: an implementation that derives the comment prefix from a bare leading `#` line (no trailing space) and then emits `#- a` / `#b c`, or adds trailing spaces to empty comment lines."""
    stdin = "# fmt: markdown\n#\n# *  a\n#\n# b   c\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_comment_bare_hash_first.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_comment_target_without_space_keeps_prefix(run):
    """CATCHES: an implementation that inserts a space after `#` when the comment block consistently uses a bare `#` prefix."""
    stdin = "# fmt: markdown\n#*  a\n#b   c\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_comment_no_space.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hashpipe_block_with_bare_pipe_lines(run):
    """CATCHES: an implementation that adds a trailing space to empty `#|` lines or that picks the bare `#|` line as the block prefix for the YAML lines."""
    stdin = "#|\n#| a:   1\n#|\n#| b:  [1,2]\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "hashpipe_bare_pipe_lines.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hashpipe_block_without_space_after_pipe(run):
    """CATCHES: an implementation that inserts a space after `#|` when every hashpipe line uses the unspaced `#|key:` prefix."""
    stdin = "#|a:   1\n#|b:  [1,2]\n"
    result = _fmt(run, "in.R", stdin)
    assert result.stdout == b"#|a: 1\n#|b: [1, 2]\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_hashpipe_block_with_inconsistent_prefix_is_an_error(run):
    """CATCHES: an implementation that formats a hashpipe block whose lines use different prefixes (here `#| ` versus `#|`) instead of rejecting it at the block start."""
    result = _fmt(run, "in.py", "#| a:   1\n#|b:  [1,2]\n")
    assert result.stdout == b""
    assert result.stderr.decode() == "in.py:1:1: error: hashpipe YAML has no target\n"
    assert result.returncode == 1


def test_hashpipe_file_scope_compact_stays_in_its_block(run):
    """CATCHES: an implementation that lets `# fmt: compact scope=file` inside one hashpipe YAML block leak to a later block in the same source file."""
    stdin = (
        "#| # fmt: compact scope=file\n"
        "#| a:\n"
        "#|   - 1\n"
        "#| b:\n"
        "#|   c: 1\n"
        "\n"
        "x = 1\n"
        "\n"
        "#| d:\n"
        "#|   - 1\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "hashpipe_scope_file_one_block.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Python / R: string targets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        (
            "in.py",
            "# fmt: markdown\nx = '''\nsay ''' here\n'''\n",
            "in.py:3:1: error: formatted Markdown conflicts with string delimiter\n",
        ),
        (
            "in.R",
            '# fmt: markdown\nx <- "\nsay "hi" here\n"\n',
            "in.R:3:1: error: formatted Markdown conflicts with string delimiter\n",
        ),
    ],
    ids=["python-triple-single", "r-double-quote"],
)
def test_markdown_string_containing_its_delimiter_is_an_error(run, path, stdin, stderr):
    """CATCHES: an implementation that writes formatted Markdown containing the string's own closing delimiter back into the literal, which would change the host program."""
    result = _fmt(run, path, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("path", "stdin", "stderr"),
    [
        ("in.py", "# fmt: markdown\nx = '''\n*  a\n", "in.py:3:5: error: fmt: markdown has no target\n"),
        ("in.py", "# fmt: markdown\nx = b'''\n*  a\n'''\n", "in.py:2:6: error: fmt: markdown has no target\n"),
        ("in.py", "# fmt: markdown\nx = u'''\nA   b\n'''\n", "in.py:2:6: error: fmt: markdown has no target\n"),
        ("in.py", "# fmt: markdown\nx = b'''\n*  a\n", "in.py:3:5: error: fmt: markdown has no target\n"),
        ("in.py", "# fmt: markdown\nx = '''", "in.py:2:7: error: fmt: markdown has no target\n"),
        ("in.R", '# fmt: markdown\nx <- r"(a)"\n', "in.R:2:6: error: fmt: markdown has no target\n"),
        ("in.R", '# fmt: markdown\nx <- r"(\n*  a\n', "in.R:3:5: error: fmt: markdown has no target\n"),
        ("in.R", '# fmt: markdown\nx <- r"(*  a', "in.R:2:12: error: fmt: markdown has no target\n"),
    ],
    ids=["python-unclosed", "python-bytes-prefix", "python-u-prefix", "python-bytes-unclosed",
         "python-opener-at-eof", "r-raw-single-line", "r-raw-unclosed", "r-raw-opener-at-eof"],
)
def test_markdown_directive_without_supported_string_target(run, path, stdin, stderr):
    """CATCHES: an implementation that formats unclosed strings, unsupported Python prefixes (`b`, `u`), single-line R raw strings, or openers on a final line without a newline instead of reporting that `fmt: markdown` has no target."""
    result = _fmt(run, path, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1


def test_python_markdown_string_empty_and_blank_bodies(run):
    """CATCHES: an implementation that inserts a blank line or fails on a marked triple-quoted string with an empty body, or that keeps blank-only body lines instead of collapsing them to an empty body."""
    stdin = "# fmt: markdown\nx = '''\n'''\n\n# fmt: markdown\ny = '''\n\n\n'''\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_empty_bodies.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_markdown_string_crlf_trailing_blank_lines(run):
    """CATCHES: an implementation that keeps blank CRLF padding lines before the closing delimiter or converts CRLF line endings to LF inside a marked string."""
    stdin = "# fmt: markdown\r\nx = '''\r\n*  a\r\n\r\n\r\n'''\r\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == b"# fmt: markdown\r\nx = '''\r\n- a\r\n'''\r\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_markdown_string_common_indent_stops_at_first_mismatch(run):
    """CATCHES: an implementation that computes the common string indentation by width rather than by identical leading characters, mishandling a line that mixes spaces and a tab."""
    stdin = (
        "def f():\n"
        "    # fmt: markdown\n"
        "    x = '''\n"
        "      Some   text.\n"
        "    \tMore   text.\n"
        "    '''\n"
    )
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_mixed_indent.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_escaped_quote_before_triple_quote_opener(run):
    """CATCHES: an implementation that ends a single-line string at an escaped quote (`\\"`) and then misses the triple-quoted target opened later on the same line."""
    stdin = "# fmt: markdown\nx = \"a\\\"b\" + '''\n*  a\n'''\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_escaped_quote_before_opener.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_opener_followed_by_whitespace_only(run):
    """CATCHES: an implementation that treats trailing spaces after the opening triple quote as Markdown body content, or strips them from the source line."""
    stdin = "# fmt: markdown\nx = '''   \n*  a\n'''\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == b"# fmt: markdown\nx = '''   \n- a\n'''\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_markdown_body_starting_on_opener_line(run):
    """CATCHES: an implementation that ignores content that begins on the same line as the opening triple quote instead of formatting it as the first Markdown line."""
    stdin = "# fmt: markdown\nx = '''*  a\n*  b\n'''\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == b"# fmt: markdown\nx = '''- a\n- b\n'''\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_r_raw_markdown_body_starting_on_opener_line(run):
    """CATCHES: an implementation that requires an R raw string opener `r"(` to end its line before treating the literal as a Markdown target."""
    stdin = '# fmt: markdown\nx <- r"(*  a\n*  b\n)"\n'
    result = _fmt(run, "in.R", stdin)
    assert result.stdout == b'# fmt: markdown\nx <- r"(- a\n- b\n)"\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "golden"),
    [
        ("# fmt: markdown\nx = Rf'''\nA  \\\\ {x}   b\n'''\n", "python_prefix_rf.golden"),
        ('# fmt: markdown\nx = fR"""\nA  \\\\ {x}   b\n"""\n', "python_prefix_fr_double.golden"),
    ],
    ids=["Rf-single", "fR-double"],
)
def test_python_mixed_case_raw_f_string_prefixes(run, stdin, golden):
    """CATCHES: an implementation that matches string prefixes case-sensitively (rejecting `Rf`/`fR`), rejects backslashes in raw f-strings, or reformats the `{x}` f-string expression."""
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Embedded formatter targets in source strings
# ---------------------------------------------------------------------------


def test_python_embedded_keyword_formats_indented_string(run, workdir):
    """CATCHES: an implementation that sends the string body to the formatter without removing its common indentation (the `|` marker would land before the spaces), or that fails to re-indent the formatter output to the body's original indentation."""
    files = {"yamark.toml": UPPER_CONFIG, "up_script": MARK_SCRIPT}
    write_tree(workdir, files)
    stdin = "def f():\n    # fmt: embedded up\n    x = '''\n      abc\n        def\n    '''\n"
    result = _fmt(run, "in.py", stdin)
    assert result.stdout == (RES / "python_embedded_keyword_indented.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_r_formatter_shorthand_targets_only_next_string(run, workdir):
    """CATCHES: an implementation that applies an R `# fmt: <name>` formatter shorthand to every following string instead of only the next raw string literal."""
    files = {"yamark.toml": UPPER_CONFIG, "up_script": UPPER_SCRIPT}
    write_tree(workdir, files)
    stdin = "# fmt: up\nx <- r\"(\n  abc\n)\"\ny <- '\nzz\n'\n"
    result = _fmt(run, "in.R", stdin)
    assert result.stdout == (RES / "r_shorthand_next_only.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_r_formatter_shorthand_with_scope_next_on_standard_string(run, workdir):
    """CATCHES: an implementation that rejects the explicit `scope=next` on a formatter shorthand in R, or that does not treat a multiline single-quoted R string as an embedded formatter target."""
    files = {"yamark.toml": UPPER_CONFIG, "up_script": UPPER_SCRIPT}
    write_tree(workdir, files)
    stdin = "# fmt: up scope=next\nx <- '\nabc\n'\n"
    result = _fmt(run, "in.R", stdin)
    assert result.stdout == (RES / "r_shorthand_scope_next_standard.golden").read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


# ---------------------------------------------------------------------------
# File kinds, CLI values and configuration names
# ---------------------------------------------------------------------------


def test_stdin_path_without_extension_is_unsupported(run):
    """CATCHES: an implementation that guesses a file kind (e.g. Markdown) for a `--stdin-file-path` with no extension instead of failing with `unsupported file type`."""
    result = _fmt(run, "README", "#   Title\n")
    assert result.stdout == b""
    assert result.stderr.decode() == "README:1:1: error: unsupported file type\n"
    assert result.returncode == 1


def test_explicit_path_without_extension_is_skipped(run, workdir):
    """CATCHES: an implementation that formats or fails on an explicitly named extensionless file instead of counting it as skipped and leaving it untouched."""
    files = {"Makefile": "a:  b\n"}
    write_tree(workdir, files)
    result = run(["format", "--check", "Makefile"])
    assert result.stdout == b""
    assert result.stderr.decode() == "1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n"
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_cli_table_widths_rejects_unknown_value(run):
    """CATCHES: an implementation that accepts an unknown `--table-widths` value (or reports it with a different message or exit status than the usage error 2)."""
    result = _fmt(run, "in.md", "a\n", "--table-widths", "wide")
    assert result.stdout == b""
    assert result.stderr.decode() == (
        "error: invalid value 'wide' for '--table-widths <TABLE_WIDTHS>': table-widths must be fit or preserve\n"
        "\n"
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    ("name", "stderr"),
    [
        ("on", "yamark.toml:1:1: error: reserved fmt directive name: on\n"),
        ('"skip file"', "yamark.toml:1:1: error: reserved fmt directive name: skip file\n"),
        ('" up"', "yamark.toml:1:1: error: embedded formatter names must be non-empty and trimmed\n"),
    ],
    ids=["on", "skip-file", "untrimmed"],
)
def test_embedded_config_rejects_reserved_and_untrimmed_names(run, workdir, name, stderr):
    """CATCHES: an implementation that lets an `[embedded]` entry shadow a reserved directive name (`on`, `off`, `skip file`, `table`) or accepts a name with surrounding whitespace."""
    files = {
        "yamark.toml": f'[embedded.{name}]\nformatter = {{ command = ["python3", "up_script", "{{path}}"], path_suffix = ".txt" }}\n',
        "up_script": UPPER_SCRIPT,
    }
    write_tree(workdir, files)
    result = run(["format", "--stdin-file-path", "in.py", "--config", "yamark.toml"], input="x = 1\n")
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)
