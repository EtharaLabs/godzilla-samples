"""Website behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_website_documents_json_lines_as_yaml_streams_1(run, workdir):
    """CATCHES: reimplementations that break "website documents json lines as yaml streams" (website); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    stdin = (
        '{"id":1,"profile":{"name":"planner","active":true}}\n'
        '{"id":2,"profile":{"name":"researcher","active":true},"usage":{"input_tokens":640,"output_tokens":128}}\n'
        '{"id":3,"profile":{"name":"reviewer","active":true,"model":"gpt-5","region":"us","tools":["search","python"]},"events":[{"type":"tool_call","tools":["search","open","python","write"]},{"type":"usage","tokens":{"input":900,"output":240}},{"type":"completion","status":"ok"}]}\n'
    )
    result = run(
        ['format', '--wrap', '72', '--stdin-file-path', 'records.yaml', '--line-width', '80'],
        input=stdin,
    )
    assert result.stdout == (RES / 'website_documents_json_lines_as_yaml_streams_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_website_documents_json_lines_as_yaml_streams_2(run, workdir):
    """CATCHES: reimplementations that break "website documents json lines as yaml streams" (website); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    stdin = (
        '{"id":1,"profile":{"name":"planner","active":true}}\n'
        '{"id":2,"profile":{"name":"researcher","active":true},"usage":{"input_tokens":640,"output_tokens":128}}\n'
        '{"id":3,"profile":{"name":"reviewer","active":true,"model":"gpt-5","region":"us","tools":["search","python"]},"events":[{"type":"tool_call","tools":["search","open","python","write"]},{"type":"usage","tokens":{"input":900,"output":240}},{"type":"completion","status":"ok"}]}\n'
    )
    result = run(
        ['format', '--wrap', '72', '--stdin-file-path', 'records.yml', '--line-width', '80'],
        input=stdin,
    )
    assert result.stdout == (RES / 'website_documents_json_lines_as_yaml_streams_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
