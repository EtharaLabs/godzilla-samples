"""Yaml collections transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_compact_multiline_plain(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact multiline plain; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'items:\n'
        '  - first\n'
        '    continuation\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'compact_multiline_plain.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_compact_multiline_quote_characters(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact multiline quote characters; the exact stdout, stderr, exit status are compared."""
    stdin = (
        "- lorem: 'lorem''ipsum\n"
        "    dolor'\n"
        '  ipsum: "lorem\\"ipsum\n'
        '    dolor"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'- {lorem: "lorem\'ipsum dolor", ipsum: \'lorem"ipsum dolor\'}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_multiline_quotes(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact multiline quotes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- "lorem\n'
        '  ipsum"\n'
        "- 'dolor\n"
        "  sit amet'\n"
        "- 'consectetur\n"
        '\n'
        "  adipiscing'\n"
        '- "elit\\\n'
        '  sed"\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == b'[lorem ipsum, dolor sit amet, "consectetur\\nadipiscing", elitsed]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_root(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact root; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'name: a\n'
        'type: int\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '80'],
        input=stdin,
    )
    assert result.stdout == b'{name: a, type: int}\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_root_collection_children(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact root collection children; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- {lorem: ipsum, dolor: sit}\n'
        '- [lorem, ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'compact_root_collection_children.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--compact', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_compact_root_sequence(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact root sequence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- alpha\n'
        '- beta\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '80'],
        input=stdin,
    )
    assert result.stdout == b'[alpha, beta]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_compact_sequence_preserved_entry(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for compact sequence preserved entry; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- - # Lorem ipsum\n'
        "    'Lorem ipsum\n"
        "      dolor sit amet.'\n"
        '  - [lorem,ipsum]\n'
        '- [dolor,sit]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'compact_sequence_preserved_entry.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_dash_prefixed_mapping_keys(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for dash prefixed mapping keys; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-1:\n'
        '  lorem ipsum\n'
        '---\n'
        '-lorem:\n'
        '  dolor sit\n'
        '---\n'
        '- -1:\n'
        '    lorem ipsum\n'
        '  -ipsum: [dolor,sit]\n'
        '- [amet,elit]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--prose-width', '12'], input=stdin)
    assert result.stdout == (RES / 'dash_prefixed_mapping_keys.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_explicit_parent_indent(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for explicit parent indent; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# fmt: markdown\n'
        'lorem:\n'
        '  |2\n'
        '      Lorem __ipsum__.\n'
        'ipsum: [dolor,sit]\n'
        '---\n'
        '- !md\n'
        '  |2\n'
        '      Lorem __ipsum__.\n'
        '- [dolor,sit]\n'
        '---\n'
        '    !markdown |2\n'
        '      Lorem __ipsum__.\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--canonical', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'explicit_parent_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_finalize_inline_only(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for finalize inline only; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'plain: [one,two]\n'
        'body: !markdown "This is __strong__."\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'finalize_inline_only.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_finalize_nested_late(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for finalize nested late; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'plain: [one,two]\n'
        '# fmt: markdown\n'
        'inline: "This is __strong__."\n'
        'block: !markdown |\n'
        '  This is __strong__ too.\n'
        '# fmt: skip\n'
        'skipped: !markdown |\n'
        '  Keep __raw__  here.\n'
        '# fmt: markdown canonical=true scope=file\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'finalize_nested_late.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_lines_flat_over_width(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for json lines flat over width; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{"id":1,"alpha":1,"beta":2,"gamma":3,"delta":4,"epsilon":5,"zeta":6,"eta":7,"theta":8}\n'
        '{"id":2,"alpha":1,"beta":2,"gamma":3,"delta":4,"epsilon":5,"zeta":6,"eta":7,"theta":8}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '80'], input=stdin)
    assert result.stdout == (RES / 'json_lines_flat_over_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_lines_flat_under_width(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for json lines flat under width; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{"id":1,"name":"Ada","active":true}\n'
        '{"id":2,"name":"Grace","active":false}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '80'], input=stdin)
    assert result.stdout == (RES / 'json_lines_flat_under_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_lines_nested_over_width(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for json lines nested over width; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{"id":1,"profile":{"alpha":1,"beta":2,"gamma":3,"delta":4,"epsilon":5,"zeta":6,"eta":7,"theta":8,"iota":9}}\n'
        '{"id":2,"profile":{"alpha":1,"beta":2,"gamma":3,"delta":4,"epsilon":5,"zeta":6,"eta":7,"theta":8,"iota":9}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '80'], input=stdin)
    assert result.stdout == (RES / 'json_lines_nested_over_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_lines_nested_under_width(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for json lines nested under width; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{"id":1,"profile":{"name":"Lin","active":true}}\n'
        '{"id":2,"profile":{"name":"Sam","active":false}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '80'], input=stdin)
    assert result.stdout == (RES / 'json_lines_nested_under_width.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_lines_primitive_boundary(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for json lines primitive boundary; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '1\n'
        '2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '80'], input=stdin)
    assert result.stdout == (RES / 'json_lines_primitive_boundary.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--line-width', '80', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_late_template_policy(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for late template policy; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'held: &saved # parent\n'
        "  'Café value'\n"
        'quoted: "<< item >>"\n'
        'items: [<< a,b >>]\n'
        'body: !markdown |\n'
        '  Keep __strong__ and << literal  bytes >>.\n'
        'plain: !markdown |\n'
        '  Keep __strong__ and `literal  bytes`.\n'
        'attached: !markdown\n'
        '  |\n'
        '    Keep __attached__.\n'
        'ok: [x,y]\n'
        '# fmt: template.delimiters "<<" ">>" scope=file\n'
        '# fmt: markdown canonical=true scope=file\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml', '--line-width', '12', '--wrap', 'none'],
        input=stdin,
    )
    assert result.stdout == (RES / 'late_template_policy.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_layout_only_policies(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for layout only policies; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'held: &saved # parent\n'
        "  'Café value'\n"
        'templated: ["{{ keep   bytes }}",  1]\n'
        'items:\n'
        '  - one\n'
        '  - two\n'
        'body: !markdown |\n'
        '  Keep __strong__.\n'
        '  Continue on another line.\n'
        '# fmt: compact scope=file\n'
        '# fmt: markdown canonical=true wrap=paragraph scope=file\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'layout_only_policies.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_sequence_mapping_nested_mapping(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for sequence mapping nested mapping; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'output:\n'
        '  jsonrpc: "2.0"\n'
        '  id: 2\n'
        '  result:\n'
        '    tools:\n'
        '      - name: console\n'
        '        description: Echo the supplied arguments.\n'
        '        inputSchema:\n'
        '          $schema: "https://json-schema.org/draft/2020-12/schema"\n'
        '          additionalProperties: true\n'
        '          type: object\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'sequence_mapping_nested_mapping.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_spacing(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for spacing; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'a:    b\n'
        'list:\n'
        '-    item\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'spacing.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_unsupported_flow_value_prefix(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML collection layout for unsupported flow value prefix; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'top: [a,b]\n'
        "mapping: [it's quoted]\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'unsupported_flow_value_prefix.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
