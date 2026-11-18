"""Source files transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_python_embedded_comment_blank(run, workdir):
    """CATCHES: implementations that differ from the reference in Python/R source-file target formatting for python embedded comment blank; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# fmt: markdown\n'
        '# #   Title ##\n'
        '#\n'
        '# Body   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'python_embedded_comment_blank.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_embedded_f_string_template_line(run, workdir):
    """CATCHES: implementations that differ from the reference in Python/R source-file target formatting for python embedded f string template line; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'from textwrap import dedent\n'
        '\n'
        '# fmt: markdown\n'
        'prompt += dedent(f"""\n'
        '\n'
        '    Stage: verification with pending finding.\n'
        '\n'
        '    Pending finding:\n'
        '    {pending_finding}\n'
        '\n'
        '    Allowed dispositions are fixed.\n'
        '    """)\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'python_embedded_f_string_template_line.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_python_embedded_markdown(run, workdir):
    """CATCHES: implementations that differ from the reference in Python/R source-file target formatting for python embedded markdown; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = """\n'
        '#   Title ##\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'python_embedded_markdown.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_raw_embedded_string(run, workdir):
    """CATCHES: implementations that differ from the reference in Python/R source-file target formatting for python raw embedded string; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# fmt: markdown\n'
        'DOC = r"""\n'
        'Path C:\\tmp\\file.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'python_raw_embedded_string.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_r_hashpipe_yaml(run, workdir):
    """CATCHES: implementations that differ from the reference in Python/R source-file target formatting for r hashpipe yaml; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '#!/usr/bin/env Rapp\n'
        '#| name: demo\n'
        '#| launcher:\n'
        '#|  vanilla: true\n'
        '#|  default-packages: [base,utils]\n'
        '\n'
        'switch(\n'
        '  command <- "",\n'
        '  #| title: Summary Mode\n'
        '  #| options: {long: true, values: [a,b]}\n'
        '  summary = {}\n'
        ')\n'
    )
    result = run(['format', '--stdin-file-path', 'input.R'], input=stdin)
    assert result.stdout == (RES / 'r_hashpipe_yaml.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
