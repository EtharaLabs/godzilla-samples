"""Header normalisation when a YAML block scalar is rewritten by an embedded formatter.

When `# fmt: <name>` sends a literal block scalar through an external formatter,
Yamark re-renders the value header (properties, indicator, chomping, trailing
comment). The header is normalised like a simple `key: value` line: the first
unquoted `:` outside brackets gets exactly one following space, and a flow-looking
remainder has its items re-spaced. These tests pin that exact spelling.
"""

import pytest

from conftest import format_both_ways, outcome

UPPER_CONFIG = """[embedded.up]
formatter = { command = ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())", "{path}"], path_suffix = ".txt" }
"""

STRIP_CONFIG = """[embedded.strip]
formatter = { command = ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read().rstrip('\\\\n'))", "{path}"], path_suffix = ".txt" }
"""

KEEP_CONFIG = """[embedded.keep]
formatter = { command = ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read().rstrip('\\\\n') + '\\\\n\\\\n\\\\n')", "{path}"], path_suffix = ".txt" }
"""


def _format_yaml(run, workdir, tool_bin, text, config=UPPER_CONFIG, *extra):
    (workdir / "yamark.toml").write_text(config)
    return run(
        ["format", "--stdin-file-path", "input.yaml", *extra],
        input=text,
        env_overrides={"PATH": str(tool_bin)},
    )


def test_comment_with_flow_sequence_is_respaced(run, workdir, tool_bin, golden):
    """CATCHES: an implementation that copies the block header comment verbatim instead of
    normalising `see: [a,b ,  c]` to `see: [a, b, c]` when the embedded formatter runs."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: | # see: [a,b ,  c]\n  hello\n")
    assert outcome(result) == golden("comment_flow_sequence")


def test_comment_with_flow_mapping_is_respaced(run, workdir, tool_bin, golden):
    """CATCHES: wrong flow-mapping normalisation in the header comment: pairs must become
    `a: 1` and bare items stay bare (`{a: 1, b, c: 2}`)."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: | # map: {a:1,  b , c :2}\n  hello\n")
    assert outcome(result) == golden("comment_flow_mapping")


def test_comment_colon_gains_single_space(run, workdir, tool_bin, golden):
    """CATCHES: an implementation that leaves `note:x` alone; the reference inserts one space
    after the first unquoted colon in the rendered header."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: | # note:x\n  hello\n")
    assert outcome(result) == golden("comment_colon_space")


def test_comment_ending_in_colon_has_no_trailing_space(run, workdir, tool_bin, golden):
    """CATCHES: emitting `trailing: ` with a dangling space when nothing follows the colon in
    the header comment."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: | # trailing:\n  hello\n")
    assert outcome(result) == golden("comment_trailing_colon")


def test_verbatim_tag_colon_is_split(run, workdir, tool_bin, golden):
    """CATCHES: a rewrite that special-cases verbatim tags; the reference treats the first colon
    in `!<tag:yaml.org,2002:str>` as a mapping colon and emits `!<tag: yaml.org,2002:str>`."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: !<tag:yaml.org,2002:str> |\n  hello\n")
    assert outcome(result) == golden("verbatim_tag")


def test_single_quoted_escape_before_colon(run, workdir, tool_bin, golden):
    """CATCHES: a quote scanner that ends a single-quoted run at the doubled `''` escape and so
    splits at the wrong colon in `'it''s': [x,y]`."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: | # 'it''s': [x,y]\n  hello\n")
    assert outcome(result) == golden("single_quote_escape")


def test_double_quoted_escape_before_colon(run, workdir, tool_bin, golden):
    """CATCHES: a quote scanner that ends a double-quoted run at an escaped `\\"`, which would
    split inside the quoted key instead of after it."""
    result = _format_yaml(run, workdir, tool_bin, '# fmt: up\ncode: | # "q\\"x:": {k:v}\n  hello\n')
    assert outcome(result) == golden("double_quote_escape")


def test_cr_only_line_endings_survive_header_rewrite(run, workdir, tool_bin, golden):
    """CATCHES: header rewriting that drops or converts a bare CR line ending to LF."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\rcode: | # a:b\r  hello\r")
    assert outcome(result) == golden("cr_endings")


def test_crlf_line_endings_survive_header_rewrite(run, workdir, tool_bin, golden):
    """CATCHES: header rewriting that loses the CR of a CRLF line ending."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\r\ncode: | # a:b\r\n  hello\r\n")
    assert outcome(result) == golden("crlf_endings")


def test_sequence_item_header_is_normalised(run, workdir, tool_bin, golden):
    """CATCHES: sequence-item block scalars that skip header normalisation (`- | # a: [1, 2]`)."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\n- | # a:[1,2]\n  hello\n")
    assert outcome(result) == golden("sequence_item")


def test_anchor_is_kept_before_indicator(run, workdir, tool_bin, golden):
    """CATCHES: losing or reordering the anchor property when the header is re-rendered."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode: &anc | # a:[1,2]\n  hello\n")
    assert outcome(result) == golden("anchor")


def test_extra_spaces_around_indicator_collapse(run, workdir, tool_bin, golden):
    """CATCHES: keeping the source spacing `code:   |   # note`; the reference emits `code: | # note`."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: up\ncode:   |   # note\n  hello\n")
    assert outcome(result) == golden("indicator_spacing")


def test_output_without_final_newline_uses_clip_chomp(run, workdir, tool_bin, golden):
    """CATCHES: emitting `|-` or keeping the source `|+` when the formatter drops only the final
    newline; the reference restores the line ending and emits a plain clip `|` header."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: strip\ncode: |+ # c:d\n  hello\n\n", STRIP_CONFIG)
    assert outcome(result) == golden("strip_chomp")


def test_output_with_blank_tail_switches_to_keep_chomp(run, workdir, tool_bin, golden):
    """CATCHES: dropping the `-` but not adding a keep indicator when the formatter output ends
    with several newlines; the reference inserts `+` after the space before the comment
    (`| +# c: d`) and keeps the blank tail lines."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: keep\ncode: |- # c:d\n  hello\nnext: 1\n", KEEP_CONFIG)
    assert outcome(result) == golden("keep_chomp")


def test_explicit_indent_indicator_is_retained(run, workdir, tool_bin, golden):
    """CATCHES: dropping the explicit indentation indicator digit while rewriting chomping."""
    result = _format_yaml(run, workdir, tool_bin, "# fmt: strip\ncode: |2 # n:1\n   hello\n", STRIP_CONFIG)
    assert outcome(result) == golden("indent_indicator")


POSITION_CONFIG = UPPER_CONFIG + """[embedded.missing]
formatter = { command = ["ruff", "{path}"], path_suffix = ".txt" }
"""

POSITIONS = {
    "root_block_scalar": "# fmt: up\n|\n  hello\n",
    "root_tagged_block_scalar": "# fmt: up\n!!str |\n  hello\n",
    "document_marker_block_scalar": "# fmt: up\n--- |\n  hello\n",
    "nested_mapping_value": "# fmt: up\nouter:\n  code: |\n    hello\n",
    "nested_sequence_item": "# fmt: up\n- - |\n    hello\n",
    "tag_on_parent_line": "# fmt: up\nkey: !t\n  |\n  hello\n",
    "comment_on_parent_line": "# fmt: up\nkey: # c\n  |\n  hello\n",
    "comment_on_sequence_marker": "# fmt: up\n- # c\n  |\n  hello\n",
    "explicit_key_value": "# fmt: up\n? k\n: |\n  hello\n",
    "missing_optional_root": "# fmt: missing\n|\n  hello\n",
    "missing_optional_mapping": "# fmt: missing\ncode:   |\n  hello\nother:   [1,2]\n",
    "missing_optional_sequence": "# fmt: missing\n- |\n  hello\n-   [1,2]\n",
}


@pytest.mark.parametrize("diagnostics", [False, True], ids=["quiet", "diagnostics"])
@pytest.mark.parametrize("name", sorted(POSITIONS))
def test_external_scalar_positions(name, diagnostics, run, workdir, tool_bin, golden):
    """CATCHES: running the embedded formatter only for mapping values (not root, nested or
    explicit-key scalars), moving parent-line tags/comments, or (for a missing optional
    formatter) failing to preserve the whole entry and emit the note only with --diagnostics."""
    extra = ["--diagnostics"] if diagnostics else []
    (workdir / "yamark.toml").write_text(POSITION_CONFIG)
    observed = format_both_ways(
        run, workdir, "input.yaml", POSITIONS[name], *extra, env_overrides={"PATH": str(tool_bin)}
    )
    assert observed == golden(f"position_{name}__{'diag' if diagnostics else 'quiet'}")


BODY_SHAPES = {
    "external_empty_body": "# fmt: up\ncode: |\nnext:   1\n",
    "external_blank_body": "# fmt: up\ncode: |\n\n\nnext:   1\n",
    "external_header_at_eof": "# fmt: up\ncode: |",
    "external_body_without_final_newline": "# fmt: up\ncode: |\n  hello",
    "external_root_empty": "# fmt: up\n|\n",
    "markdown_root_block": "# fmt: markdown\n|\n  Some   *text*   here.\n",
    "markdown_root_tagged": "!markdown |\n  Some   *text*   here.\n",
    "markdown_root_folded": "# fmt: markdown\n>\n  Some   *text*   here.\n",
    "markdown_block_without_final_newline": "body: !markdown |\n  Some   text",
    "markdown_block_dedented_comment": "body: !markdown |\n    Some   text\n  # comment\nnext: 1\n",
    "markdown_block_explicit_indent": "body: !markdown |4\n      Some   text\n    more\n",
    "markdown_empty_block": "body: !markdown |\nnext: 1\n",
}


@pytest.mark.parametrize("name", sorted(BODY_SHAPES))
def test_block_scalar_body_shapes(name, run, workdir, tool_bin, golden):
    """CATCHES: wrong chomping for empty or blank formatter output (`|-` / `|+`), dropping the
    header at EOF, not restoring a final newline, or mis-indenting Markdown block scalars at
    the root, with explicit indentation indicators, or before a dedented comment."""
    (workdir / "yamark.toml").write_text(UPPER_CONFIG)
    observed = format_both_ways(run, workdir, "input.yaml", BODY_SHAPES[name], env_overrides={"PATH": str(tool_bin)})
    assert observed == golden(f"body_{name}")
