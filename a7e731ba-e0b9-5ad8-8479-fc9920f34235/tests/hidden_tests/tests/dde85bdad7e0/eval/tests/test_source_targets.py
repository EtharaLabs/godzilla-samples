"""Python and R source targets: hashpipe (`#|`) YAML blocks, `fmt: markdown` comment
blocks and string literals, embedded-formatter string targets, and file-scope option
directives that re-plan earlier targets.

Each source is formatted with and without `--verify`, both through stdin and through
path-mode `--check`, so prefix handling, target validation errors and the exact
surrounding-code preservation must all match the reference.
"""

import pytest

from conftest import format_both_ways

PYTHON = {
    'off_region_skips_strings': '# fmt: off\nx = """\n# fmt: on\n"""\ny = b"""\n# fmt: on\n"""\nz   = 1\n# fmt: on\n#| a:   1\n',
    'empty_markdown_string': '# fmt: markdown\nx = """\n\n"""\n',
    'mixed_indent_markdown_string': '# fmt: markdown\ndef f():\n    x = """\n    Some   text.\n\tMore   text.\n    """\n',
    'indented_markdown_string': '# fmt: markdown\ndef f():\n    x = """\n        Some   text   that is long enough to need wrapping at the default prose width of the formatter.\n\n        - item   one\n    """\n',
    'padded_delimiters': '# fmt: markdown\nx = """   \nSome   text.\n   """\n',
    'markdown_string_template_delims': '# fmt: markdown\nx = """\nKeep {{ a   b }} and {% c   d %} here.\n"""\n',
    'fstring_braces': '# fmt: markdown\nx = f"""\nKeep {a   +   b} and {{literal   braces}} here.\n"""\n',
    'rf_prefix': '# fmt: markdown\nx = rf"""\nKeep {a} and \\n   raw.\n"""\n',
    'uppercase_fr_prefix': '# fmt: markdown\nx = FR"""\nKeep {a}   raw.\n"""\n',
    'single_quote_triple': "# fmt: markdown\nx = '''\nSome   text.\n'''\n",
    'closing_on_text_line': '# fmt: markdown\nx = """\nSome   text."""\n',
    'comment_markdown_list': '# fmt: markdown\n# - item   one\n# - item   two\n#\n#   continued\nx = 1\n',
    'comment_markdown_indented': 'def f():\n    # fmt: markdown\n    # Some   text   here.\n    pass\n',

    'hashpipe_empty_middle': '#| a:   1\n#|\n#| b:  [1,2]\nx = 1\n',
    'hashpipe_empty_first': '#|\n#| a:   1\nx = 1\n',
    'hashpipe_indent_mismatch': '#| a:   1\n  #| b:   2\nx = 1\n',
    'hashpipe_prefix_mismatch': '#| a:   1\n#|b:   2\nx = 1\n',
    'hashpipe_invalid_yaml': '#| a: [1, 2\n#| b: 3\nx = 1\n',
    'hashpipe_tab': '#|\ta: 1\nx = 1\n',
    'hashpipe_then_file_delta': '#| a:   [1,2]\nx = 1\n# fmt: wrap=none\n',
    'md_comment_empty_first': '# fmt: markdown\n#\n# Some   text   here that is long enough to wrap around the default width of seventy-two.\nx = 1\n',
    'md_comment_empty_mid': '# fmt: markdown\n# First para.\n#\n# Second   para.\nx = 1\n',
    'md_comment_prefix_mismatch': '# fmt: markdown\n# First para.\n## Second para.\nx = 1\n',
    'unknown_string_formatter': '# fmt: nosuch\nx = """\nabc\n"""\n',
    'unknown_string_formatter_r': '# fmt: nosuch\nx <- "\nabc\n"\n',
    'md_string_then_file_delta': '# fmt: markdown\nx = """\nSome   *text* here.\n"""\n# fmt: wrap=sentence\n',
    'md_comment_then_file_delta': '# fmt: markdown\n# Some   text. Another sentence.\nx = 1\n# fmt: wrap=sentence\n',
    'skip_over_strings': "# fmt: skip\nx = '''\n# fmt: markdown\n'''\n# fmt: markdown\n# Some   text.\n",
    'skip_target_string': '# fmt: skip\ns = """\nkeep   this\n"""\n#| a:   1\n',
    'fstring_markdown': '# fmt: markdown\nx = f"""\nHello   {name}   and {{literal}}.\n"""\n',
    'raw_string_markdown': '# fmt: markdown\nx = r"""\nSome   \\text here.\n"""\n',
    'nonraw_backslash': '# fmt: markdown\nx = """\nSome \\\\ text.\n"""\n',
    'single_line_string': '# fmt: markdown\nx = """one line"""\n',
    'bytes_prefix': '# fmt: markdown\nx = b"""\ntext\n"""\n',
    'md_comment_trailing_code': '# fmt: markdown\n# text   here\nx = 1  # trailing\n',
    'directive_no_target_eof': 'x = 1\n# fmt: markdown\n',
    'off_on_region': '# fmt: off\n#| a:   1\n# fmt: on\n#| b:   2\n',
    'verify_hashpipe_and_markdown': '#| a:   1\n# fmt: markdown\n# Some   text\nx = 1\n# fmt: wrap=sentence\n',
}

R_SOURCES = {
    'off_region_skips_strings': '# fmt: off\nx <- "\n# fmt: on\n"\ny <- r"(\n# fmt: on\n)"\nz   = 1\n# fmt: on\n#| a:   1\n',

    'r_raw_string': '# fmt: markdown\nx <- r"(\nSome   text   here.\n)"\n',
    'r_raw_dashes': '# fmt: markdown\nx <- R"--[\nSome   text.\n]--"\n',
    'r_single_quote': "# fmt: markdown\nx <- '\nSome   text.\n'\n",
    'r_backslash': '# fmt: markdown\nx <- "\nSome \\\\ text.\n"\n',
    'r_hashpipe': '#| label: fig-x\n#| fig-cap:   "A caption"\nplot(1)\n',
    'r_unterminated_raw': '# fmt: markdown\nx <- r"(\nSome text.\n',
}

MODES = {"plain": [], "verify": ["--verify"], "sentence": ["--wrap", "sentence"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(PYTHON))
def test_python_source(name, mode, run, workdir, golden):
    """CATCHES: wrong hashpipe/comment prefix reconstruction (empty `#|`/`#` lines, prefix
    mismatches), formatting code outside targets, accepting unsupported string targets
    (bytes, single-line, non-raw backslashes), or wrong errors for unknown formatters."""
    observed = format_both_ways(run, workdir, "script.py", PYTHON[name], *MODES[mode])
    assert observed == golden(f"py_{name}__{mode}")


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(R_SOURCES))
def test_r_source(name, mode, run, workdir, golden):
    """CATCHES: wrong recognition of R raw strings (`r"(...)"`, `R"--[...]--"`), quote styles,
    backslash rejection in non-raw strings, or hashpipe chunk-option formatting in R."""
    observed = format_both_ways(run, workdir, "script.R", R_SOURCES[name], *MODES[mode])
    assert observed == golden(f"r_{name}__{mode}")
