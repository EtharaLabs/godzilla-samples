"""To yaml transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_json(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json; the exact stdout, stderr, exit status are compared."""
    stdin = '{"first":1,"emoji":"\\uD83D\\uDE00","a":-0,"a":1e+02,"big":123456789012345678901234567890}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.json', '--line-width', '40'], input=stdin)
    assert result.stdout == (RES / 'json.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json5; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{\n'
        '  // JSON5 values\n'
        '  foo:1,\n'
        "  single: 'don\\'t',\n"
        '  apostrophe: "don\\\'t",\n'
        '  letter: "\\a",\n'
        '  underscore: "\\_",\n'
        '  emoji: "\\uD83D\\uDE00",\n'
        '  hex: 0X2A,\n'
        '  infinity: Infinity,\n'
        '  negativeInfinity: -Infinity,\n'
        '  nan: NaN,\n'
        '  \\u0061: "\\x41",\n'
        '}\n'
    )
    result = run(['to-yaml', '--stdin-file-path', 'input.json5', '--line-width', '40'], input=stdin)
    assert result.stdout == (RES / 'json5.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json5_invalid(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json5 invalid; the exact stdout, stderr, exit status are compared."""
    stdin = '{"value": "\\1"}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.json5'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.json5:1:12: error: invalid JSON5: legacy numeric escape sequences are not supported\n'
    assert result.returncode == 1


def test_json_folded_prose(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json folded prose; the exact stdout, stderr, exit status are compared."""
    stdin = '{"summary":"Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.","prompt-history":{"global":["Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.","Donec vitae sapien."]},"status":"Completed."}\n'
    result = run(
        ['to-yaml', '--stdin-file-path', 'input.json', '--line-width', '42', '--prose-width', '42'],
        input=stdin,
    )
    assert result.stdout == (RES / 'json_folded_prose.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_invalid(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json invalid; the exact stdout, stderr, exit status are compared."""
    stdin = '{"a":}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.json'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.json:1:6: error: invalid JSON: Unexpected close brace\n'
    assert result.returncode == 1


def test_json_sequence_mapping(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json sequence mapping; the exact stdout, stderr, exit status are compared."""
    stdin = '{"schema_version":1,"connectors":[{"id":"synthetic_connector","name":"% Example","status":"active"}],"groups":[["alpha-value","beta-value","gamma-value","delta-value"]]}\n'
    result = run(
        ['to-yaml', '--stdin-file-path', 'input.json', '--line-width', '40', '--indent-width', '4'],
        input=stdin,
    )
    assert result.stdout == (RES / 'json_sequence_mapping.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_json_template_text(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for json template text; the exact stdout, stderr, exit status are compared."""
    stdin = '{"payload":{"label":"{{ lorem ipsum }}","description":"Lorem ipsum dolor sit amet.\\n{{ lorem ipsum }}\\nConsectetur adipiscing elit.","items":["Sed do eiusmod tempor.","Ut labore et dolore."]}}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.json', '--line-width', '40'], input=stdin)
    assert result.stdout == (RES / 'json_template_text.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for jsonc; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{\n'
        '  // before a\n'
        '  "a": 1, // after a\n'
        '  "text": "http://x/*y*/",\n'
        '  /* before nested */\n'
        '  "nested": {"b": 2 /* after b */},\n'
        '}\n'
    )
    result = run(['to-yaml', '--stdin-file-path', 'input.jsonc', '--line-width', '40'], input=stdin)
    assert result.stdout == (RES / 'jsonc.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonc_invalid(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for jsonc invalid; the exact stdout, stderr, exit status are compared."""
    stdin = '{"a": 1 /* unterminated}\n'
    result = run(['to-yaml', '--stdin-file-path', 'input.jsonc'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.jsonc:1:9: error: invalid JSONC: Unterminated comment block\n'
    assert result.returncode == 1


def test_jsonl(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for jsonl; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '{"a":1}\n'
        '[2,3]\n'
        '"four"\n'
    )
    result = run(['to-yaml', '--stdin-file-path', 'records.ndjson'], input=stdin)
    assert result.stdout == (RES / 'jsonl.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_jsonl_multiline(run, workdir):
    """CATCHES: implementations that differ from the reference in JSON-family to YAML projection for jsonl multiline; the exact stdout, stderr, exit status are compared."""
    stdin = '{"payload":{"client":"Example Desktop","cwd":"/workspace/example","summary":"Ut enim ad minim veniam.\\nQuis nostrud exercitation ullamco laboris.\\n","input-messages":["Lorem ipsum: dolor sit amet, consectetur adipiscing elit.\\n\\nSed do eiusmod tempor incididunt ut labore."]}}\n'
    result = run(['to-yaml', '--stdin-file-path', 'events.jsonl', '--line-width', '40'], input=stdin)
    assert result.stdout == (RES / 'jsonl_multiline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
