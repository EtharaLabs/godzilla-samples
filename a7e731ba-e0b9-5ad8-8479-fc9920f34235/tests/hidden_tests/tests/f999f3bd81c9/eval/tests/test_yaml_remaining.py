"""YAML engine edge cases: odd keys in compact/table output, layout hints, tab-indented regions,
invalid headers, preserved documents, and error propagation from embedded formatters.

Each test drives the CLI with a small YAML (or Markdown) input and pins the exact stdout, stderr,
exit status and, in path mode, the resulting file contents produced by the reference build.
"""

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

STDIN_ARGS = ["format", "--stdin-file-path", "x.yaml"]
FAILING_FORMATTER_CONFIG = (
    "[embedded.lorem]\n"
    'formatter = { command = ["python3", "fmt_bad", "{path}"], path_suffix = ".txt" }\n'
)
FAILING_FORMATTER_SCRIPT = "import sys\nsys.stdin.read()\nsys.exit(3)\n"
TAB_DIRECTIVE = "# fmt: compact=false scope=file\n"


def fmt(run, stdin, *extra):
    return run([*STDIN_ARGS, *extra], input=stdin)


# --- compact and table output ----------------------------------------------------------------


def test_compact_mode_quotes_an_empty_implicit_key(run):
    """CATCHES: an implementation that drops a `: v` line with an empty implicit key, emits it as a bare `: v` inside the flow mapping, or refuses to compact, instead of collapsing to `{'': v, b: c}` with the empty key single-quoted."""
    result = fmt(run, "a:\n  : v\n  b: c\n", "--compact")
    assert result.stdout == b"a: {'': v, b: c}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_table_quotes_empty_key_and_aligns_following_field(run):
    """CATCHES: an implementation that skips table compaction for a row whose first key is empty, or measures the empty key as zero columns, instead of writing `{'': v, b: c}` and padding the second row's `b` to the same column (`{x: 1,  b: 2}`)."""
    stdin = "# fmt: compact table\nrows:\n  - : v\n    b: c\n  - x: 1\n    b: 2\n"
    result = fmt(run, stdin)
    assert result.stdout == b"# fmt: compact table\nrows:\n  - {'': v, b: c}\n  - {x: 1,  b: 2}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_table_row_with_empty_tagged_value_leaves_rows_unaligned(run):
    """CATCHES: an implementation that aligns a `fmt: table` sequence even though one row holds an empty tagged value (`k: !!str `) that must stay byte-for-byte, or that rewrites that row, instead of leaving both rows as typed while still normalizing the later `z:   1`."""
    stdin = "# fmt: table\nrows:\n  - {k: !!str , b: 1}\n  - {x: 1, b: 2}\nz:   1\n"
    result = fmt(run, stdin)
    assert result.stdout == b"# fmt: table\nrows:\n  - {k: !!str , b: 1}\n  - {x: 1, b: 2}\nz: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- directive errors ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stdin",
    [
        "# fmt: markdown\na: [1] x\nb: 1\n",
        "# fmt: table\nitems: [a, b]]\nnext: 1\n",
        "# fmt: python\n- [1] x\n- y\n",
    ],
    ids=["markdown-value", "table-value", "embedded-item"],
)
def test_target_directive_before_unparseable_flow_value_is_an_error(run, stdin):
    """CATCHES: an implementation that silently preserves a flow collection with trailing text (`[1] x`, `[a, b]]`) when a targeting directive (`fmt: markdown`, `fmt: table`, `fmt: python`) points at it, instead of failing with `fmt directive targets unsupported YAML flow syntax` reported at line 3, column 1."""
    result = fmt(run, stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == "x.yaml:3:1: error: fmt directive targets unsupported YAML flow syntax\n"
    assert result.returncode == 1


def test_same_line_directive_on_root_scalar_continuation_is_an_error(run):
    """CATCHES: an implementation that treats `# fmt: skip` at the end of the continuation line of a multi-line root plain scalar as an ordinary comment (or as part of the scalar), instead of rejecting it with `fmt directive is not supported in this position` at line 2, column 9."""
    result = fmt(run, "hello\n  world # fmt: skip\n")
    assert result.stdout == b""
    assert result.stderr.decode() == "x.yaml:2:9: error: fmt directive is not supported in this position\n"
    assert result.returncode == 1


FENCE_2 = "  ```lorem\n  x\n  ```\n"
FENCE_4 = "    ```lorem\n    x\n    ```\n"


@pytest.mark.parametrize(
    ("stdin", "body_line"),
    [
        ("- a\n# fmt: lorem\n- |\n  x\n", 4),
        ("# fmt: lorem\na: # c\n  |\n  x\n", 4),
        ("# fmt: lorem\n- # c\n  |\n  x\n", 4),
        ("# fmt: lorem\n? a\n: |\n  x\n", 4),
        ("- k: 1\n  # fmt: lorem\n  b: |\n    x\n", 4),
        ("# fmt: lorem\n- b: |\n    x\n", 3),
        ("a:\n  # fmt: lorem\n  b: |\n    x\n", 4),
        ("!md |\n" + FENCE_2, 3),
        ("- !md |\n" + FENCE_2, 3),
        ("a: !md |\n" + FENCE_2, 3),
        ("- - !md |\n" + FENCE_4, 3),
        ("a:\n  b: !md |\n" + FENCE_4, 4),
    ],
    ids=[
        "sequence-item-literal",
        "value-after-header-comment",
        "item-after-marker-comment",
        "explicit-key-value",
        "item-mapping-second-pair",
        "item-mapping-first-pair",
        "nested-mapping-value",
        "root-markdown-fence",
        "item-markdown-fence",
        "value-markdown-fence",
        "compact-item-markdown-fence",
        "nested-value-markdown-fence",
    ],
)
def test_failing_embedded_formatter_aborts_from_every_yaml_position(run, workdir, stdin, body_line):
    """CATCHES: an implementation that only propagates a strict configured formatter's nonzero exit for simple `key: |` values and silently preserves (or drops) the scalar when it sits in a sequence item, after a header comment, under an explicit key, inside an item mapping, nested deeper, or as a ```lorem fence inside a `!md` block scalar; every position must fail with the synthetic `x.yaml.embedded.<body line>.txt` path in the message."""
    write_tree(workdir, {"yamark.toml": FAILING_FORMATTER_CONFIG, "fmt_bad": FAILING_FORMATTER_SCRIPT})
    result = fmt(run, stdin)
    path = f"x.yaml.embedded.{body_line}.txt"
    assert result.stdout == b""
    assert result.stderr.decode() == (
        f"x.yaml:1:1: error: embedded formatter failed: command `python3 fmt_bad {path}` "
        f"exited with exit status 3 for {path}\n"
    )
    assert result.returncode == 1


# --- tab-indented regions --------------------------------------------------------------------


def test_tab_indented_document_with_directive_is_formatted_around_skipped_entry(run):
    """CATCHES: an implementation that preserves the whole document once any line is tab-indented even though it contains an active `fmt:` directive, or that mangles the `a:b` scalar, the unterminated `!<tag` verbatim tag or the `>quoted` literal line, instead of only normalizing `x:   1` to `x: 1`."""
    stdin = "x:   1\n# fmt: skip\na:\n\tb: 1\nc: a:b\nd: !<tag v\ne: |\n  >quoted\n"
    result = fmt(run, stdin)
    assert result.stdout == b"x: 1\n# fmt: skip\na:\n\tb: 1\nc: a:b\nd: !<tag v\ne: |\n  >quoted\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_tab_indented_line_after_explicit_mapping_is_kept(run):
    """CATCHES: an implementation that folds the tab-indented `\\t? c` line into the preceding explicit `? a` / `: b` mapping (or rejects the document) instead of keeping it as typed and still normalizing the later `d:   1` to `d: 1`."""
    stdin = TAB_DIRECTIVE + "? a\n: b\n\t? c\nd:   1\n"
    result = fmt(run, stdin)
    assert result.stdout == (TAB_DIRECTIVE + "? a\n: b\n\t? c\nd: 1\n").encode()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    "body",
    ["a: !t\n\tb\nc:   1\n", "? a\n:\n\tb\nc:   1\n"],
    ids=["property-only-value", "empty-explicit-value"],
)
def test_tab_indented_value_after_open_header_is_kept(run, body):
    """CATCHES: an implementation that re-indents (or joins onto the header) a tab-indented value line following a property-only `a: !t` header or an empty explicit `:` value line, instead of keeping the header and the `\\tb` line verbatim and only normalizing `c:   1` to `c: 1`."""
    result = fmt(run, TAB_DIRECTIVE + body)
    assert result.stdout == (TAB_DIRECTIVE + body.replace("c:   1", "c: 1")).encode()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_file_scope_directive_skips_preserved_yaml_fence(run):
    """CATCHES: an implementation that crashes or re-formats a ```yaml fence that was preserved for its tab indentation when a later `<!-- fmt: wrap=sentence scope=file -->` re-plans earlier nested documents, instead of keeping the fence verbatim and collapsing the paragraph spaces."""
    stdin = "```yaml\na:\n\tb: 1\n```\n\nSome   text.\n\n<!-- fmt: wrap=sentence scope=file -->\n"
    result = run(["format", "--stdin-file-path", "x.md"], input=stdin)
    assert result.stdout == b"```yaml\na:\n\tb: 1\n```\n\nSome text.\n\n<!-- fmt: wrap=sentence scope=file -->\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- properties, explicit values and odd structure -------------------------------------------


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        ("a: &x\n  {k:   v}\n", b"a: &x {k: v}\n"),
        ("? a\n: &x\n  {k:   v}\n", b"? a\n: &x {k: v}\n"),
    ],
    ids=["mapping-value", "explicit-value"],
)
def test_anchored_flow_mapping_on_next_line_joins_its_header(run, stdin, expected):
    """CATCHES: an implementation that keeps a flow mapping on its own line under an anchor-only header (or loses the `&x` anchor) instead of attaching the anchor to the collection and emitting `&x {k: v}` on the header line."""
    result = fmt(run, stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        ("? a\n:\n- b\n- c\n", b"? a\n:\n  - b\n  - c\n"),
        ("? a\n: &x\n- b\n- c\n", b"? a\n: &x\n  - b\n  - c\n"),
    ],
    ids=["empty-value", "anchor-only-value"],
)
def test_indentless_sequence_under_explicit_value_is_indented(run, stdin, expected):
    """CATCHES: an implementation that leaves an indentless block sequence at column 0 under an explicit `:` value line (or treats it as a sibling of the mapping) instead of nesting it with the configured two-space indent while keeping the `&x` anchor on the `:` line."""
    result = fmt(run, stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_nested_sequence_followed_by_mapping_line_is_expanded(run):
    """CATCHES: an implementation that keeps the compact `- - a` form or drops the following `  b: 1` line, instead of moving the nested sequence onto its own indented line after a bare `-` and leaving `  b: 1` in place."""
    result = fmt(run, "- - a\n  b: 1\n")
    assert result.stdout == b"-\n  - a\n  b: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_item_mapping_followed_by_nested_sequence_line_keeps_that_line(run):
    """CATCHES: an implementation that absorbs the `  - c` line into the item mapping `a: 1` / `b: 2` (or re-indents it) instead of keeping it verbatim while still normalizing the following `-   d` item to `- d`."""
    result = fmt(run, "- a: 1\n  b: 2\n  - c\n-   d\n")
    assert result.stdout == b"- a: 1\n  b: 2\n  - c\n- d\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_root_plain_scalar_followed_by_mapping_line_stays_separate(run):
    """CATCHES: an implementation that folds the `b:   1` line into the root plain scalar `a` as a continuation line (producing `a b: 1`) instead of stopping the scalar at the mapping line and normalizing it to `b: 1`."""
    result = fmt(run, "a\nb:   1\n")
    assert result.stdout == b"a\nb: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_keys_ending_in_alias_or_anchor_characters_still_format_flow_values(run):
    """CATCHES: an implementation that treats the `*:` / `&:` key endings (`a*:`, `b&:`) as alias or anchor syntax and preserves the line, instead of normalizing the flow values to `[1, 2]` and `{c: 1}`."""
    result = fmt(run, "a*: [1,   2]\nb&: {c:   1}\n")
    assert result.stdout == b"a*: [1, 2]\nb&: {c: 1}\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- layout hints and widths -----------------------------------------------------------------


def test_flow_collapse_hint_at_end_of_file_is_kept(run):
    """CATCHES: an implementation that crashes, drops, or closes an unmatched `[` opener on the final line (no block collection follows it), instead of keeping `a: [` as typed while normalizing `z:   1` to `z: 1`."""
    result = fmt(run, "z:   1\na: [\n")
    assert result.stdout == b"z: 1\na: [\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        ("a: [\n  ? b\n  : c\n", b"a: {b: c}\n"),
        ("a: {\n  ? b\n  : c\nd:   1\n", b"a: {b: c}\nd: 1\n"),
    ],
    ids=["bracket-opener", "brace-opener"],
)
def test_flow_collapse_hint_over_explicit_keys_collapses_to_flow_mapping(run, stdin, expected):
    """CATCHES: an implementation that only honours the unmatched-opener hint before `key:` or `- item` lines, or that uses the typed bracket kind, instead of collapsing the following explicit `? b` / `: c` mapping into `{b: c}`."""
    result = fmt(run, stdin)
    assert result.stdout == expected
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_collapse_hint_under_explicit_value_collapses(run):
    """CATCHES: an implementation that ignores an unmatched `[` opener on the line after an empty explicit `:` value, instead of collapsing the following block sequence into `: [b, c]`."""
    result = fmt(run, "? a\n:\n  [\n  - b\n  - c\n")
    assert result.stdout == b"? a\n: [b, c]\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_collapse_hint_after_anchor_header_is_preserved(run):
    """CATCHES: an implementation that collapses a hinted block sequence whose header carries an anchor (`a: &x` then `[`), or drops the anchor or the opener, instead of preserving the hinted collection as typed and normalizing the following `z:   1`."""
    result = fmt(run, "a: &x\n  [\n  - b\n  - c\nz:   1\n")
    assert result.stdout == b"a: &x\n  [\n  - b\n  - c\nz: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_over_wide_flow_item_with_trailing_comment_stays_inline(run):
    """CATCHES: an implementation that expands an over-width flow sequence item to block style even though a trailing `# note` comment follows it (losing or moving the comment), instead of keeping it inline with normalized `, ` separators."""
    result = fmt(run, "- [alpha,   beta, gamma, delta] # note\n", "--line-width", "20")
    assert result.stdout == b"- [alpha, beta, gamma, delta] # note\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unclosed_template_opener_inside_flow_is_ordinary_text(run):
    """CATCHES: an implementation that treats an unterminated `<%` template opener inside a flow sequence as a template span running to the end (preserving the whole collection), instead of formatting it as ordinary text: `[<% x, b]`."""
    result = fmt(run, "a: [<% x,   b]\n")
    assert result.stdout == b"a: [<% x, b]\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_property_glued_to_flow_opener_preserves_the_collection(run):
    """CATCHES: an implementation that splits `&x{b: c}` into an anchor and a mapping (inserting a space) or rejects the file, instead of preserving that flow collection as typed while normalizing `z:   1` to `z: 1`."""
    result = fmt(run, "a: [&x{b: c}]\nz:   1\n")
    assert result.stdout == b"a: [&x{b: c}]\nz: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


# --- scalar headers and quoted scalars --------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    ["|0", "|++", ">-+", "|22", "|1 2"],
    ids=["zero-indent", "double-keep", "strip-then-keep", "two-digit-indent", "spaced-indicators"],
)
def test_invalid_block_scalar_headers_keep_their_scalar(run, header):
    """CATCHES: an implementation that accepts an invalid block header (indentation indicator 0, repeated or conflicting chomping indicators, a two-digit or space-separated indicator) and rewrites the scalar, instead of keeping `a: <header>` and its body verbatim while normalizing `b:   1`."""
    result = fmt(run, f"a: {header}\n  x\nb:   1\n")
    assert result.stdout == f"a: {header}\n  x\nb: 1\n".encode()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_block_scalar_with_less_indented_line_is_kept_verbatim(run):
    """CATCHES: an implementation that re-indents the under-indented ` y` line of a literal block scalar (to two spaces) or ends the scalar before it, instead of keeping the scalar body byte-for-byte while normalizing `b:   1`."""
    result = fmt(run, "a: |\n  x\n y\nb:   1\n")
    assert result.stdout == b"a: |\n  x\n y\nb: 1\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_crlf_line_break_in_double_quoted_scalar_is_kept(run):
    """CATCHES: an implementation that decodes an escaped CRLF line break (`\\` at the end of a CRLF line) inside a multi-line double-quoted scalar into a single line or converts it to LF, instead of keeping it while normalizing `b:   1` with the CRLF ending intact."""
    result = fmt(run, 'a: "x\\\r\n  y"\r\nb:   1\r\n')
    assert result.stdout == b'a: "x\\\r\n  y"\r\nb: 1\r\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


@pytest.mark.parametrize(
    "source",
    [
        ":a\nb:   1\n",
        'a: "x\\q\n  y"\nb:   1\n',
        'a: "x\n  y" z\nb:   1\n',
        'a: [b, "c\n  d"]\nz:   1\n',
    ],
    ids=["colon-led-line", "multiline-invalid-escape", "text-after-multiline-quote", "multiline-quote-in-flow"],
)
def test_unsupported_lines_preserve_the_whole_document(run, workdir, source):
    """CATCHES: an implementation that formats the rest of a document containing a line that starts with `:`, a multi-line double-quoted scalar with an invalid `\\q` escape, text after a multi-line quoted scalar, or a multi-line quoted scalar inside a flow collection, instead of leaving that whole file unchanged (only the sibling `y.yaml` is formatted)."""
    write_tree(workdir, {"x.yaml": source, "y.yaml": "a:   1\n"})
    result = run(["format", "x.yaml", "y.yaml"])
    assert result.stdout == b"2 files scanned, 1 formatted, 1 unchanged, 0 skipped, 0 failed\n"
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({"x.yaml": source, "y.yaml": "a: 1\n"})
