"""Remaining reachable gaps across the CLI front end, source-language planning, config path layers,
directive template scanning, the large-input diff fallback and path-less diagnostics.

Covers: root `--help`/`-h`/`help` rendering (cli.rs), file-scope directives after hashpipe YAML and
embedded-Markdown directive errors in Python sources, R lines that merely look like legacy raw-string
openers (source_lang.rs), `paths.<p>.embedded_markdown` tables with only `replace_delimiters` or no
`template` table (config.rs), inline Hugo shortcodes ending exactly at EOF (directives.rs), the linear
diff resync ignoring stale earlier matches (workspace/diff.rs), and the path-less `1:1:` diagnostic
for a directory-walk failure (diagnostic.rs).
"""

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)


# ---------------------------------------------------------------------------
# Root help (documented on website/cli-help.qmd)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("args", [["--help"], ["-h", "--help"], ["--help", "-h"]])
def test_root_long_help(run, args):
    """CATCHES: an implementation that prints the short summary when --help is combined with -h (long help must win in either order), omits the long_about line pointing at `yamark <COMMAND> --help`, uses the binary file name instead of `yamark` in the usage line, or drops the trailing blank line after the help text."""
    result = run(args)
    assert result.stdout == (RES / "root_long_help.golden").read_bytes()
    assert result.stderr == b""
    assert result.returncode == 0


def test_root_short_help(run):
    """CATCHES: an implementation that treats -h like --help (printing the long_about paragraph and the multi-line option description) instead of the one-line summary with "(see more with '--help')", or that exits non-zero or writes help to stderr."""
    result = run(["-h"])
    assert result.stdout == (RES / "root_short_help.golden").read_bytes()
    assert result.stderr == b""
    assert result.returncode == 0


@pytest.mark.parametrize("args", [["help"], ["--help", "format"]])
def test_root_help_via_parser_uses_binary_name(run, args):
    """CATCHES: an implementation that prints `format` help for `--help format` instead of root help, that exits 2 for the `help` subcommand, or that renders this parser-generated help with the `yamark` name and an extra blank line like the dedicated --help path (here the usage line names the invoked binary and no blank line follows)."""
    result = run(args)
    assert result.stdout == (RES / "help_subcommand.golden").read_bytes()
    assert result.stdout.decode().splitlines()[4] == "Usage: executable <COMMAND>"
    assert result.stderr == b""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("args", "unknown"),
    [
        (["--help", "--bogus"], "--bogus"),
        (["-h", "--help", "--bogus", "--other"], "--bogus"),
    ],
)
def test_root_help_after_flags_with_unknown_flag_is_usage_error(run, args, unknown):
    """CATCHES: an implementation that prints help when --help/-h precede an unknown root flag instead of rejecting the first unknown flag with exit 2 and the `yamark` usage line."""
    result = run(args)
    assert result.stdout == b""
    assert result.stderr.decode() == (
        f"error: unexpected argument '{unknown}' found\n"
        "\n"
        "Usage: yamark <COMMAND>\n"
        "\n"
        "For more information, try '--help'.\n"
    )
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Python and R source planning
# ---------------------------------------------------------------------------


def test_python_file_scope_wrap_after_hashpipe_and_comment_applies_backwards(run):
    """CATCHES: an implementation that only applies a source-file `# fmt: wrap=none` (default scope=file) to later targets, so the earlier Markdown comment gets rewrapped at 72 columns, or that lets the Markdown option leak into the hashpipe YAML block (which must still be normalised to `echo: true`)."""
    words = " ".join(["word"] * 20)
    source = (
        "#| echo:   true\n#| label: x\n\n"
        f"# fmt: markdown\n# {words}\n# more   *text*\n\n"
        "# fmt: wrap=none\n"
    )
    result = run(["format", "--stdin-file-path", "a.py"], input=source)
    assert result.stdout.decode() == (
        "#| echo: true\n#| label: x\n\n"
        f"# fmt: markdown\n# {words}\n# more   *text*\n\n"
        "# fmt: wrap=none\n"
    )
    assert result.stderr == b""
    assert result.returncode == 0


def test_python_markdown_comment_with_invalid_nested_directive_fails(run):
    """CATCHES: an implementation that copies a marked Markdown comment unchanged when it contains an invalid `<!-- fmt: ... -->` directive instead of failing, or that reports the error at host-file coordinates (3:8) rather than the embedded-body position 2:6 the reference reports."""
    source = "x = 1\n\n# fmt: markdown\n# Text\n# <!-- fmt: bogus -->\n"
    result = run(["format", "--stdin-file-path", "a.py"], input=source)
    assert result.stdout == b""
    assert result.stderr.decode() == "a.py:2:6: error: invalid fmt directive: bogus\n"
    assert result.returncode == 1


def test_python_markdown_string_with_invalid_nested_scope_fails(run):
    """CATCHES: an implementation that ignores an unsupported scope on a Markdown directive nested in a marked triple-quoted string (it must fail with 'fmt: skip does not support scope=bogus'), or that reports the error at host-file line 7 instead of the embedded-body position 3:6."""
    source = 'x = 1\n\n# fmt: markdown\ny = """\nText\n\n<!-- fmt: skip scope=bogus -->\n"""\n'
    result = run(["format", "--stdin-file-path", "a.py"], input=source)
    assert result.stdout == b""
    assert result.stderr.decode() == "a.py:3:6: error: fmt: skip does not support scope=bogus\n"
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            'x <- c("bar", "for")\n# fmt: markdown\n# Some   *text*\n',
            'x <- c("bar", "for")\n# fmt: markdown\n# Some *text*\n',
        ),
        (
            'x <- paste("bar", f(1))\n# fmt: markdown\n# Some   *text*\n',
            'x <- paste("bar", f(1))\n# fmt: markdown\n# Some *text*\n',
        ),
        (
            'label <- paste0("Year", format(\n  # fmt: markdown\n  # Some   *text*\n  Sys.Date()\n))\n',
            'label <- paste0("Year", format(\n  # fmt: markdown\n  # Some *text*\n  Sys.Date()\n))\n',
        ),
    ],
    ids=["r-quote-without-paren", "r-quote-paren-with-args", "r-quote-open-call"],
)
def test_r_string_ending_in_r_quote_is_not_a_raw_string(run, before, after):
    """CATCHES: an implementation that treats any `r"` (here the end of the ordinary strings "bar"/"for"/"Year") followed by text and `(` as a raw-string opener, swallowing the following or enclosed Markdown comment as unsupported raw text instead of formatting it while preserving the surrounding R code."""
    result = run(["format", "--stdin-file-path", "a.R"], input=before)
    assert result.stdout.decode() == after
    assert result.stderr == b""
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# [paths.<p>.embedded_markdown] layers
# ---------------------------------------------------------------------------


def test_embedded_markdown_replace_only_discards_top_level_template(run, workdir):
    """CATCHES: an implementation whose paths.<p>.embedded_markdown.template.replace_delimiters (without add_delimiters) does not discard the top-level [template] delimiters for embedded Markdown under <p>, or that applies the path layer outside <p>; @( )@ must stay a template only outside p and !( )! only inside p."""
    toml = (
        '[template]\nadd_delimiters = [{ open = "@(", close = ")@" }]\n\n'
        '[paths."p".embedded_markdown.template]\nreplace_delimiters = [{ open = "!(", close = ")!" }]\n'
    )
    first = '# fmt: markdown\nx = """\nFirst   @(a   b)@   *one*.\n"""\n'
    second = '# fmt: markdown\nx = """\nSecond   !(c   d)!   *two*.\n"""\n'
    files = {"yamark.toml": toml, "p/a.py": first, "p/b.py": second, "q/a.py": first, "q/b.py": second}
    write_tree(workdir, files)
    result = run(["format", "p/a.py", "p/b.py", "q/a.py", "q/b.py"])
    assert result.stdout == b"4 files scanned, 2 formatted, 2 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr == b""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected["p/a.py"] = b'# fmt: markdown\nx = """\nFirst @(a b)@ *one*.\n"""\n'
    expected["q/b.py"] = b'# fmt: markdown\nx = """\nSecond !(c d)! *two*.\n"""\n'
    assert read_tree(workdir) == expected


def test_empty_embedded_markdown_path_table_keeps_default_delimiters(run, workdir):
    """CATCHES: an implementation that rejects an empty [paths.<p>.embedded_markdown] table (no template key), or that treats it as an empty replacement so the default {{ }} delimiters stop preserving a marked comment containing a template."""
    files = {
        "yamark.toml": '[paths."p".embedded_markdown]\n',
        "p/a.py": "# fmt: markdown\n# Some   *text*\n",
        "p/b.py": "# fmt: markdown\n# Keep   {{ a   b }}\n",
    }
    write_tree(workdir, files)
    result = run(["format", "p/a.py", "p/b.py"])
    assert result.stdout == b"2 files scanned, 1 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr == b""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected["p/a.py"] = b"# fmt: markdown\n# Some *text*\n"
    assert read_tree(workdir) == expected


# ---------------------------------------------------------------------------
# Hugo shortcodes ending exactly at end of input
# ---------------------------------------------------------------------------


def test_markdown_inline_shortcode_at_eof_without_newline_is_formatted(run):
    """CATCHES: an implementation that treats an inline `{{< ... >}}` Hugo shortcode as a generic `{{ }}` template when it ends exactly at end of input (preserving the paragraph's extra spaces), or that leaves the Markdown file without a final newline."""
    result = run(["format", "--stdin-file-path", "a.md"], input='See   {{< ref "x" >}}')
    assert result.stdout == b'See {{< ref "x" >}}\n'
    assert result.stderr == b""
    assert result.returncode == 0


def test_python_comment_shortcode_at_eof_formats_but_generic_template_preserves(run, workdir):
    """CATCHES: an implementation that preserves a marked Python Markdown comment ending at EOF in a Hugo `{{< >}}` shortcode as if it were a `{{ }}` template (only the generic template must preserve the whole comment), or that appends a newline to a source file that had none."""
    files = {
        "a.py": '# fmt: markdown\n# See   {{< ref "x" >}}',
        "b.py": "# fmt: markdown\n# See   {{ ref }}",
    }
    write_tree(workdir, files)
    result = run(["format", "a.py", "b.py"])
    assert result.stdout == b"2 files scanned, 1 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr == b""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected["a.py"] = b'# fmt: markdown\n# See {{< ref "x" >}}'
    assert read_tree(workdir) == expected


# ---------------------------------------------------------------------------
# Large-input diff fallback
# ---------------------------------------------------------------------------


def test_large_diff_resync_ignores_text_seen_earlier_in_formatted_output(run, workdir):
    """CATCHES: an implementation whose large-input (linear) diff fallback resynchronises on an occurrence of a line that lies before the current output position (the standalone `alpha` paragraph) when a later `alpha` line is reflowed into `alpha beta`, producing misaligned or negative-length hunks instead of the plain remove/add blocks."""
    count = 1900
    source = (
        "#  T\n\n"
        + "".join(f"*   a{k}\n" for k in range(70))
        + "\nalpha\n\n"
        + "".join(f"*   b{k}\n" for k in range(70))
        + "\nalpha\nbeta\n\n"
        + "".join(f"*   c{k}\n" for k in range(count))
    )
    files = {"a.md": source}
    write_tree(workdir, files)
    result = run(["format", "--diff", "a.md"])

    def block(prefix, name, size, marker):
        return "".join(f"{prefix}{marker}{name}{k}\n" for k in range(size))

    assert result.stdout.decode() == (
        "--- a.md\n+++ a.md\n"
        f"@@ -1,{149 + count} +1,{148 + count} @@\n"
        "-#  T\n+# T\n \n"
        + block("-", "a", 70, "*   ") + block("+", "a", 70, "- ")
        + " \n alpha\n \n"
        + block("-", "b", 70, "*   ") + block("+", "b", 70, "- ")
        + " \n-alpha\n-beta\n+alpha beta\n \n"
        + block("-", "c", count, "*   ") + block("+", "c", count, "- ")
    )
    assert result.stderr.decode() == "1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


# ---------------------------------------------------------------------------
# Directory-walk failure (path-less diagnostic)
# ---------------------------------------------------------------------------
