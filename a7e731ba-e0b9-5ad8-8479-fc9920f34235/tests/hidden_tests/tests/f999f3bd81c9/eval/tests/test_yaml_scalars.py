"""Yaml scalars transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_dedented_block_comment_skip(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for dedented block comment skip; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem:\n'
        '  |\n'
        '    Lorem ipsum.\n'
        '  # fmt: skip scope=file\n'
        'ipsum: [dolor,sit]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'dedented_block_comment_skip.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'lorem.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'lorem.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_dedented_block_empty_formatter(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for dedented block empty formatter; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/external_formatter_empty.toml': (
            '[embedded.lorem]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdin.buffer.read()", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: embedded lorem\n'
        'lorem: |\n'
        '    Lorem ipsum.\n'
        '  # Dolor sit amet.\n'
        'ipsum: [dolor,sit]\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'lorem.yaml', '--config', 'tests/fixtures/external_formatter_empty.toml'],
        input=stdin,
    )
    assert result.stdout == b""
    assert result.stderr.decode() == 'lorem.yaml:2:8: error: blank embedded output would absorb a following YAML comment\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_dedented_block_markdown_comment(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for dedented block markdown comment; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: !md\n'
        '  |\n'
        '    Lorem __ipsum__.\n'
        '  # Dolor sit amet.\n'
        'ipsum: [dolor,sit]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--canonical', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'dedented_block_markdown_comment.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escape_heavy_scalar(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for escape heavy scalar; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'output:\n'
        '  jsonrpc: "2.0"\n'
        '  id: 3\n'
        '  result:\n'
        '    content:\n'
        '      - type: text\n'
        '        text: "{\\"python\\":\\"print(\'hello\')\\",\\"wait_ms\\":0}"\n'
        '    isError: false\n'
        'json_without_apostrophes: "{\\"wait_ms\\":0}"\n'
        'flow: {text: "{\\"python\\":\\"print(\'hello\')\\",\\"wait_ms\\":0}"}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'escape_heavy_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_escaped_radix_scalar_width(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for escaped radix scalar width; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '["\\x30xFF", abc]\n'
        '---\n'
        '["\\x30o77", abc]\n'
        '---\n'
        '["\\x30b11", abc]\n'
        '---\n'
        '[!!str "\\x30XAF", abc]\n'
        '---\n'
        '["\\x30xyz", abc]\n'
        '---\n'
        '["0xFF", abc]\n'
        '---\n'
        '["\\x30xFF"]\n'
        '---\n'
        '["\\x30abc", abc]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '12'], input=stdin)
    assert result.stdout == (RES / 'escaped_radix_scalar_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_scalar_following_comment(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for flow scalar following comment; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'literal: ["line one\\nline two"\n'
        ']\n'
        '    # outside literal\n'
        "folded: {prose: 'Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod.'\n"
        '}\n'
        '\n'
        '    # outside folded\n'
        'sibling: [x,y]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '36'], input=stdin)
    assert result.stdout == (RES / 'flow_scalar_following_comment.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_flow_scalar_quote_simplification(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for flow scalar quote simplification; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'items: ["hello", \'hello world\', "true", "a: b", "a # b", "x,y"]\n'
        'metadata: {name: "alpha", label: \'hello world\', flag: "true"}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'flow_scalar_quote_simplification.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_folded_scalar_preserves_repeated_spaces(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for folded scalar preserves repeated spaces; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'description: >-\n'
        '  Lorem ipsum    dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '14'], input=stdin)
    assert result.stdout == (RES / 'folded_scalar_preserves_repeated_spaces.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_inline_markdown_following_comments(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for inline markdown following comments; the exact stdout, stderr, exit status are compared."""
    stdin = (
        "lorem: !md 'Lorem __ipsum__.'\n"
        '  # Outside the scalar.\n'
        'ipsum: [dolor,sit]\n'
        '---\n'
        '# fmt: markdown\n'
        'lorem: "Lorem __ipsum__."\n'
        '\n'
        '    # Outside the scalar.\n'
        'ipsum: [dolor,sit]\n'
        '---\n'
        'lorem: !md Lorem __ipsum__.\n'
        ' # Outside the scalar.\n'
        'ipsum: [dolor,sit]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'inline_markdown_following_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_markdown_code_span_block_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for markdown code span block boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'paragraphs: !markdown "Before `\\n\\n<% keep   this %>\\nafter `"\n'
        'heading: !markdown "Before `\\n====\\n<% keep   this %>\\nafter `"\n'
        'subheading: !markdown "Before `\\n--\\n<% keep   this %>\\nafter `"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'markdown_code_span_block_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_markdown_scalar_diagnostic(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for markdown scalar diagnostic; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: !md |\n'
        '  <!-- fmt: lorem -->\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'lorem.yaml:2:8: error: invalid fmt directive: lorem\n'
    assert result.returncode == 1


def test_nonfinite_spelling_preservation(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for nonfinite spelling preservation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'positive:\n'
        '  - .inf\n'
        '  - .Inf\n'
        '  - .INF\n'
        '  - +.inf\n'
        '  - +.Inf\n'
        '  - +.INF\n'
        'negative: [-.inf, -.Inf, -.INF]\n'
        'nan: [.nan, .NaN, .NAN]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'nonfinite_spelling_preservation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_parent_markdown_comments(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for parent markdown comments; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: !md # Lorem ipsum\n'
        '  # Dolor sit amet.\n'
        "  'Lorem __ipsum__\n"
        "    dolor sit amet.'\n"
        'ipsum: [dolor,sit]\n'
        '---\n'
        'lorem:\n'
        '    ipsum: !md # Lorem ipsum\n'
        "      'Lorem __ipsum__\n"
        "        dolor sit amet.'\n"
        '    dolor: [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'parent_markdown_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_tag_block_markdown(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for parent tag block markdown; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: !md\n'
        '  |\n'
        '    Lorem __ipsum__.\n'
        'ipsum: !markdown &dolor\n'
        '  >-\n'
        '    Lorem __ipsum__ dolor sit amet.\n'
        'sit: *dolor\n'
        'amet: [lorem,ipsum]\n'
        '---\n'
        '- !md &ipsum\n'
        '  |\n'
        '    Lorem __ipsum__.\n'
        '- *ipsum\n'
        '- !markdown\n'
        '  >-\n'
        '    Lorem __ipsum__ dolor sit amet.\n'
        '- [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--canonical', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'parent_tag_block_markdown.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_tag_markdown_skip(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for parent tag markdown skip; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: !md\n'
        '  # fmt: skip\n'
        '  |\n'
        '    <!-- fmt: lorem -->\n'
        'ipsum: [dolor,sit]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'parent_tag_markdown_skip.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_plain_scalar_repeated_spaces(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for plain scalar repeated spaces; the exact stdout, stderr, exit status are compared."""
    stdin = 'foo: bar   baz baz\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '8'], input=stdin)
    assert result.stdout == (RES / 'plain_scalar_repeated_spaces.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_quoted_following_comment(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for quoted following comment; the exact stdout, stderr, exit status are compared."""
    stdin = (
        "literal: 'line one\n"
        '\n'
        "  line two'\n"
        '  # outside literal\n'
        "folded: 'Lorem ipsum dolor sit amet,\n"
        "  consectetur adipiscing elit, sed do eiusmod.'\n"
        '\n'
        '    # outside folded\n'
        "safe: 'line one\n"
        '\n'
        "  line two'\n"
        ' # outside safe\n'
        'sibling: [x,y]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '36'], input=stdin)
    assert result.stdout == (RES / 'quoted_following_comment.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_quoted_low_indent_continuation(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for quoted low indent continuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        "    'hello\n"
        "world'\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'quoted_low_indent_continuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_scalar_quote_simplification(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for scalar quote simplification; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'title: "hello"\n'
        "subtitle: 'hello world'\n"
        'boolish: "true"\n'
        'nullish: "null"\n'
        'empty: ""\n'
        'leading: " space"\n'
        'trailing: "space "\n'
        'tabbed: "a\\tb"\n'
        'colon: "a: b"\n'
        'comment: "a # b"\n'
        "hex: '0x2A'\n"
        "octal: '0o52'\n"
        'flow_sequence_text: "[one]"\n'
        'flow_sequence_close_text: "]one"\n'
        'flow_mapping_text: "{one}"\n'
        'flow_mapping_close_text: "}one"\n'
        'flow_separator_text: ",one"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'scalar_quote_simplification.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_tab_leading_literal(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for tab leading literal; the exact stdout, stderr, exit status are compared."""
    stdin = (
        "lorem: '\tLorem\n"
        '\n'
        "  ipsum'\n"
        'dolor: [sit,amet]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'tab_leading_literal.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_table_scalar_quote_simplification(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for table scalar quote simplification; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# fmt: table\n'
        '- {name: alpha,type: string,description: "Short",danger: "true"}\n'
        '- {name: beta,type: int,description: "Number",danger: "a: b"}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'table_scalar_quote_simplification.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_tilde_null_preservation(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML scalar formatting for tilde null preservation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'block: ~\n'
        'sequence:\n'
        '  - ~\n'
        'flow: [~, {value: ~}]\n'
        'explicit: !!null ~\n'
        'quoted: !!null "~"\n'
        'mapping:\n'
        '  ~: ~\n'
        'canonical: Null\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'tilde_null_preservation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
