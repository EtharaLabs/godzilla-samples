"""Yaml multiline transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_indented_root(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of indented root; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# Lorem ipsum\n'
        "    ' Lorem ipsum\n"
        '\n'
        "      dolor sit amet'\n"
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'indented_root.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_comments(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of parent comments; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: # Lorem ipsum\n'
        '  # Dolor sit amet.\n'
        "  'Lorem ipsum\n"
        "    dolor sit amet.'\n"
        'ipsum:\n'
        '  - # Sed do eiusmod.\n'
        '    # Tempor incididunt.\n'
        '    "Lorem ipsum\n'
        '      dolor sit amet."\n'
        'dolor: [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'parent_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_entries(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of parent entries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem:\n'
        "  'Lorem ipsum\n"
        "    {{ dolor }} sit amet.'\n"
        'ipsum:\n'
        '  -\n'
        '    "Lorem ipsum\n'
        '      {{ dolor }} sit amet."\n'
        'dolor: [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'parent_entries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_late_markdown(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of parent late markdown; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# fmt: markdown\n'
        'lorem:\n'
        '\n'
        "  'Lorem __ipsum__\n"
        "    dolor sit amet.'\n"
        '# fmt: markdown canonical=true scope=file\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'parent_late_markdown.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_markdown_properties(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of parent markdown properties; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: &ipsum\n'
        "  !md 'Lorem __ipsum__\n"
        "    dolor sit amet.'\n"
        'ipsum: *ipsum\n'
        'dolor: !md\n'
        "  &sit 'Lorem __ipsum__\n"
        "    dolor sit amet.'\n"
        'sit: *sit\n'
        'amet: !md &elit\n'
        "  'Lorem __ipsum__\n"
        "    dolor sit amet.'\n"
        'elit: *elit\n'
        'sed: [lorem,ipsum]\n'
        '---\n'
        '- !md\n'
        "  &ipsum 'Lorem __ipsum__\n"
        "    dolor sit amet.'\n"
        '- *ipsum\n'
        '- [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'parent_markdown_properties.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parent_properties(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of parent properties; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: &ipsum\n'
        "  'Lorem ipsum\n"
        "    dolor sit amet.'\n"
        'dolor: *ipsum\n'
        'sit: !!str\n'
        '  "Lorem ipsum\n'
        '    dolor sit amet."\n'
        'amet: &consectetur\n'
        "  !!str 'Lorem ipsum\n"
        "    dolor sit amet.'\n"
        'adipiscing: !!str\n'
        "  &elit 'Lorem ipsum\n"
        "    dolor sit amet.'\n"
        'sed: [lorem,ipsum]\n'
        '---\n'
        '- &ipsum\n'
        "  'Lorem ipsum\n"
        "    dolor sit amet.'\n"
        '- *ipsum\n'
        '- !lorem\n'
        "  'Lorem ipsum\n"
        "    dolor sit amet.'\n"
        '- [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'lorem.yaml'], input=stdin)
    assert result.stdout == (RES / 'parent_properties.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_plain_prose(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of plain prose; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# Lorem ipsum\n'
        'lorem: Lorem ipsum dolor sit amet,\n'
        '  consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n'
        'ipsum:\n'
        '  - Lorem ipsum dolor\n'
        '    sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n'
        'dolor: [lorem,ipsum] # Dolor sit amet.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '40'], input=stdin)
    assert result.stdout == (RES / 'plain_prose.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_quoted_prose(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of quoted prose; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# Lorem ipsum\n'
        "lorem: 'Lorem ipsum dolor sit amet,\n"
        "  consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'\n"
        'ipsum:\n'
        '  - "Lorem ipsum dolor\n'
        '    sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."\n'
        'dolor: [lorem,ipsum] # Dolor sit amet.\n'
        "sit: 'Lorem\n"
        "  ipsum' # Sit amet.\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '40'], input=stdin)
    assert result.stdout == (RES / 'quoted_prose.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_root_trivia(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of root trivia; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '---\n'
        '# Lorem ipsum\n'
        '|2-\n'
        '   Lorem ipsum\n'
        '  dolor sit amet\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'root_trivia.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_scalar_comments(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of scalar comments; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# Lorem ipsum\n'
        'lorem: Lorem ipsum dolor sit amet,\n'
        '  consectetur adipiscing elit. # Sed do eiusmod.\n'
        "ipsum: 'Lorem ipsum dolor sit amet,\n"
        "  consectetur adipiscing elit.' # Sed do eiusmod.\n"
        'dolor: [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--prose-width', '36'], input=stdin)
    assert result.stdout == (RES / 'scalar_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_tagged_plain(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of tagged plain; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem: !!str &ipsum Lorem ipsum\n'
        '  dolor sit amet.\n'
        'dolor: *ipsum\n'
        'sit: [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'tagged_plain.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_template_indent(run, workdir):
    """CATCHES: implementations that differ from the reference in YAML multiline scalar handling of template indent; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'lorem:\n'
        "    ipsum: 'Lorem ipsum\n"
        "      {{ dolor }} sit amet.'\n"
        '    dolor: [lorem,ipsum]\n'
        'sit: [lorem,ipsum]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'template_indent.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
