"""Examples and snippets from the user documentation (website/*.qmd).

Each documented input is formatted the way the docs build does (`format --wrap 72
--stdin-file-path <name> ...` for the before/after showcases, plain
`format --stdin-file-path` for static snippets) and compared exactly with the
reference output. Snippets that are already formatted are also checked in path
mode with `--check`.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_showcase_markdown_frontmatter(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-markdown-frontmatter` before/after example (examples.qmd, `example.md`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '---\n'
        'name: review-pr\n'
        "description: Review a pull request and recommend changes inline with the project's style guide, focusing on correctness, readability, and tests.\n"
        'tags: [review,pull-request,code]\n'
        '---\n'
        '\n'
        '#   Review ##\n'
        '\n'
        'Read the diff and flag anything that violates the style guide, has obvious correctness issues, or looks untested. Prefer specific suggestions over vague concerns.\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'example.md'], input=stdin)
    assert result.stdout == (RES / 'showcase_markdown_frontmatter.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_markdown_yaml_scalars(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-markdown-yaml-scalars` before/after example (examples.qmd, `prompts.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        'agents:\n'
        '  reviewer:\n'
        '    instructions: !markdown "Focus on correctness and tests. Flag any change that lacks a regression test. Prefer concrete suggestions: name the function, name the case."\n'
        '  summarizer:\n'
        '    # fmt: markdown\n'
        '    instructions: |\n'
        '      You write release notes.\n'
        '\n'
        '      - One bullet per user-visible change.\n'
        '      - No internal refactors.\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'prompts.yaml'], input=stdin)
    assert result.stdout == (RES / 'showcase_markdown_yaml_scalars.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_yaml_python_scalar(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-yaml-python-scalar` before/after example (examples.qmd, `embedded-python.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '# fmt: python\n'
        'preflight: |\n'
        '  def check(items):return all(x>0 for x in items)\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'embedded-python.yaml'], input=stdin)
    assert result.stdout == (RES / 'showcase_yaml_python_scalar.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'embedded-python.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'embedded-python.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_showcase_yaml_scalars(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-yaml-scalars` before/after example (examples.qmd, `scalars.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        'title: "hello"\n'
        'boolish: "true"\n'
        'body: "alpha\\nbeta\\n"\n'
        'summary: "This package formats YAML front matter and configuration files while preserving semantics, comments, and repository-friendly diffs."\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'scalars.yaml'], input=stdin)
    assert result.stdout == (RES / 'showcase_yaml_scalars.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_markdown_links_footnotes(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-markdown-links-footnotes` before/after example (examples.qmd, `links.md`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        'Please be mindful of our [code of conduct](https://github.com/quarto-dev/quarto-cli/blob/main/.github/CODE_OF_CONDUCT.md) as you interact with other community members.\n'
        '\n'
        'Body text with a footnote.[^long]\n'
        '\n'
        '[^long]: This footnote explains that comments were removed because people used comments to hold parsing directives and enough extra words to wrap.\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'links.md'], input=stdin)
    assert result.stdout == (RES / 'showcase_markdown_links_footnotes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_markdown_table(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-markdown-table` before/after example (examples.qmd, `table.md`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '| package | label |\n'
        '|---|---|\n'
        '| dplyr | tidy |\n'
        '| tidyr | pivoting |\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'table.md'], input=stdin)
    assert result.stdout == (RES / 'showcase_markdown_table.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_hashpipe_yaml(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-hashpipe-yaml` before/after example (examples.qmd, `example.R`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '#| name: demo\n'
        '#| launcher:\n'
        '#|  vanilla: true\n'
        '#|  default-packages: [base,utils]\n'
        '\n'
        'main <- function() NULL\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'example.R'], input=stdin)
    assert result.stdout == (RES / 'showcase_hashpipe_yaml.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_python_markdown_string(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-python-markdown-string` before/after example (examples.qmd, `prompt.py`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '# fmt: markdown\n'
        'REVIEW_PROMPT = """\n'
        '# Review\n'
        '\n'
        'Read the diff and flag anything that violates the style guide, has obvious correctness issues, or looks untested.\n'
        '\n'
        '-   Prefer specific suggestions over vague concerns.\n'
        '-   Name the function and the case.\n'
        '"""\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'prompt.py'], input=stdin)
    assert result.stdout == (RES / 'showcase_python_markdown_string.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_python_markdown_comments(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-python-markdown-comments` before/after example (examples.qmd, `comments.py`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '# fmt: markdown\n'
        '# #   Filters\n'
        '#\n'
        '# Apply one or more filters. Put the most specific filter first.\n'
        '#\n'
        '# -   Each filter is a single expression.\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'comments.py'], input=stdin)
    assert result.stdout == (RES / 'showcase_python_markdown_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_r_markdown_string(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-r-markdown-string` before/after example (examples.qmd, `help.R`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '# fmt: markdown\n'
        'help_text <- r"(\n'
        '# Filters\n'
        '\n'
        'Apply one or more filters. Filters are evaluated top-to-bottom; the first match wins, so put the most specific filter first.\n'
        '\n'
        '-   Each filter is a single expression.\n'
        '-   Multiple filters combine with AND.\n'
        ')"\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'help.R'], input=stdin)
    assert result.stdout == (RES / 'showcase_r_markdown_string.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_json_lines_yaml_stream(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-json-lines-yaml-stream` before/after example (examples.qmd, `records.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '{"id":1,"profile":{"name":"planner","active":true}}\n'
        '{"id":2,"profile":{"name":"researcher","active":true},"usage":{"input_tokens":640,"output_tokens":128}}\n'
        '{"id":3,"profile":{"name":"reviewer","active":true,"model":"gpt-5","region":"us","tools":["search","python"]},"events":[{"type":"tool_call","tools":["search","open","python","write"]},{"type":"usage","tokens":{"input":900,"output":240}},{"type":"completion","status":"ok"}]}\n'
    )
    result = run(
        ['format', '--wrap', '72', '--stdin-file-path', 'records.yaml', '--line-width', '80'],
        input=stdin,
    )
    assert result.stdout == (RES / 'showcase_json_lines_yaml_stream.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_flow_table(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-flow-table` before/after example (examples.qmd, `table.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '# fmt: table\n'
        '- {name: alpha,type: string,default: [one,two],description: "Short"}\n'
        '- {name: beta,type: int,default: 0,description: "Number"}\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'table.yaml'], input=stdin)
    assert result.stdout == (RES / 'showcase_flow_table.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_compact_collections(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-compact-collections` before/after example (examples.qmd, `compact.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        'tags:\n'
        '  - yaml\n'
        '  - markdown\n'
        '  - docs\n'
        'package:\n'
        '  name: yamark\n'
        '  language: rust\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'compact.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'showcase_compact_collections.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_collapse_inline_bracket(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-collapse-inline-bracket` before/after example (examples.qmd, `repair.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        'tags: [\n'
        '  - yaml\n'
        '  - markdown\n'
        '  - docs\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'repair.yaml'], input=stdin)
    assert result.stdout == b'tags: [yaml, markdown, docs]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_collapse_detached_bracket(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-collapse-detached-bracket` before/after example (examples.qmd, `repair-detached.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        'tags:\n'
        '[\n'
        '  - yaml\n'
        '  - markdown\n'
        '  - docs\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'repair-detached.yaml'], input=stdin)
    assert result.stdout == b'tags: [yaml, markdown, docs]\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_expand_flow_newline(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-expand-flow-newline` before/after example (examples.qmd, `expand.yaml`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '- {a: b,\n'
        '   c: d}\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'expand.yaml'], input=stdin)
    assert result.stdout == (RES / 'showcase_expand_flow_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_recursive_markdown_fences(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-recursive-markdown-fences` before/after example (examples.qmd, `recursive.md`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '```yaml\n'
        '# fmt: table\n'
        '- {name: a,type: int,default: 0}\n'
        '- {name: long_name,type: string,default: ""}\n'
        '```\n'
        '\n'
        '````markdown\n'
        '#   Inner\n'
        '\n'
        '```yaml\n'
        'items: [a,b]\n'
        '```\n'
        '````\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'recursive.md'], input=stdin)
    assert result.stdout == (RES / 'showcase_recursive_markdown_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_showcase_prettier_fences(run, workdir):
    """CATCHES: implementations whose output for the documented `showcase-prettier-fences` before/after example (examples.qmd, `web.md`) differs from what the reference writes; stdout, stderr and exit status must match exactly."""
    stdin = (
        '```json\n'
        '{"name":"yamark","tags":["yaml","markdown","formatter"],"engines":{"node":">=18"}}\n'
        '```\n'
        '\n'
        '```ts\n'
        'function format(input:string):string{return input.trim()}\n'
        '```\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'web.md'], input=stdin)
    assert result.stdout == (RES / 'showcase_prettier_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'web.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'web.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_homepage_example_text(run, workdir):
    """CATCHES: implementations that format the homepage YAML-front-matter + Markdown example differently from the reference (front matter quoting/flow spacing, heading cleanup, column-72 wrapping, nested list indentation)."""
    stdin = (
        '---\n'
        'title: Why YAML + Markdown?\n'
        'description: The source languages of LLM work - structured fields for tools alongside instructions, examples, and context for models.\n'
        'tags: [llm,authoring,formats]\n'
        '---\n'
        '\n'
        '#   Why YAML + Markdown? ##\n'
        '\n'
        'When LLMs become part of a software system, YAML and Markdown start to feel like programming languages. YAML defines named fields tools can act on; Markdown carries the instructions, examples, and context that shape model behavior. Together they create a shared source file that stays readable to people and models, exposes explicit structure to software, produces clear diffs, and renders directly.\n'
        '\n'
        'Where the combination shines:\n'
        '\n'
        '- Agent skills and prompt files keep names, versions, and tool metadata beside the instructions they describe.\n'
        '  - The Markdown body can carry code samples and nested structures with their own syntax and indentation.\n'
        '- Reference documents stay readable to authors and models without a separate source format or build step.\n'
        '- Tool inputs and model outputs survive chat, Git, and documentation pipelines as recognizable text.\n'
        '- One source can render as HTML or PDF and travel unchanged as agent context.\n'
    )
    result = run(['format', '--wrap', '72', '--stdin-file-path', 'example.md'], input=stdin)
    assert result.stdout == (RES / 'homepage_example_text.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directives_yaml_snippet_line_32(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:32 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: markdown wrap=sentence\n'
        'description: "Explain the project in a few clear sentences."\n'
        'other_value: "This is ordinary YAML, not Markdown."\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_32.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directives_yaml_snippet_line_41(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:41 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        'instructions: !markdown |\n'
        '  # Review\n'
        '\n'
        '  Read the diff and report concrete correctness issues.\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_41.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_yaml_snippet_line_51(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:51 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: python\n'
        'script: |\n'
        '  def check(items):return all(item > 0 for item in items)\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_51.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_yaml_snippet_line_60(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:60 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: table\n'
        '- {name: alpha, type: string, default: ""}\n'
        '- {name: beta, type: integer, default: 0}\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_60.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directives_python_snippet_line_71(run, workdir):
    """CATCHES: implementations that treat the documented python snippet at directives.qmd:71 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: markdown wrap=sentence\n'
        'REVIEW_PROMPT = """\n'
        '# Review\n'
        '\n'
        'Read the diff and report concrete correctness issues. Prefer specific examples.\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.py'], input=stdin)
    assert result.stdout == (RES / 'directives_python_snippet_line_71.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directives_python_snippet_line_85(run, workdir):
    """CATCHES: implementations that treat the documented python snippet at directives.qmd:85 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: markdown\n'
        '# # Filters\n'
        '#\n'
        '# Apply the most specific filter first.\n'
        '#\n'
        '# - Each filter is a single expression.\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.py'], input=stdin)
    assert result.stdout == (RES / 'directives_python_snippet_line_85.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_python_snippet_line_96(run, workdir):
    """CATCHES: implementations that treat the documented python snippet at directives.qmd:96 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: r\n'
        'analysis = """\n'
        'f <- function(x) x + 1\n'
        '"""\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.py'], input=stdin)
    assert result.stdout == (RES / 'directives_python_snippet_line_96.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.py').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.py'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_r_snippet_line_108(run, workdir):
    """CATCHES: implementations that treat the documented r snippet at directives.qmd:108 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: markdown wrap=sentence\n'
        'help_text <- r"(\n'
        '# Filters\n'
        '\n'
        'Apply the most specific filter first. Explain why a filter matched.\n'
        ')"\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.R'], input=stdin)
    assert result.stdout == (RES / 'directives_r_snippet_line_108.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_directives_r_snippet_line_119(run, workdir):
    """CATCHES: implementations that treat the documented r snippet at directives.qmd:119 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: markdown\n'
        '# # Filters\n'
        '#\n'
        '# Apply the most specific filter first.\n'
        '#\n'
        '# - Each filter is a single expression.\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.R'], input=stdin)
    assert result.stdout == (RES / 'directives_r_snippet_line_119.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.R').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.R'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_yaml_snippet_line_131(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:131 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: r\n'
        'analysis: |\n'
        '  f <- function(x)x+1\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_131.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_yaml_snippet_line_151(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:151 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        'normal: [1, 2, 3]\n'
        '# fmt: skip\n'
        'manual:\n'
        '    -   [ 1,2,3]\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_151.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_markdown_snippet_line_160(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at directives.qmd:160 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '<!-- fmt: off -->\n'
        '#   Keep this heading ##\n'
        '\n'
        '<!-- fmt: on -->\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == (RES / 'directives_markdown_snippet_line_160.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_markdown_snippet_line_176(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at directives.qmd:176 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = '<!-- fmt: skip file -->\n'
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == b'<!-- fmt: skip file -->\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_markdown_snippet_line_191(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at directives.qmd:191 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '<!-- fmt: table-widths=preserve scope=next -->\n'
        '+----------+------------------+\n'
        '| Name     | Description      |\n'
        '+==========+==================+\n'
        '| A        | Short text       |\n'
        '+----------+------------------+\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == (RES / 'directives_markdown_snippet_line_191.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_markdown_snippet_line_214(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at directives.qmd:214 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = '<!-- fmt: wrap=sentence:72 scope=file -->\n'
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == b'<!-- fmt: wrap=sentence:72 scope=file -->\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_markdown_snippet_line_222(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at directives.qmd:222 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = '<!-- fmt: canonical=true footnotes=preserve scope=file -->\n'
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == b'<!-- fmt: canonical=true footnotes=preserve scope=file -->\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_yaml_snippet_line_229(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:229 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = '# fmt: compact=false scope=file\n'
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == b'# fmt: compact=false scope=file\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_directives_yaml_snippet_line_237(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at directives.qmd:237 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: canonical=true\n'
        'first: !markdown "This is __strong__ Markdown."\n'
        'second: "This is ordinary YAML text."\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'directives_yaml_snippet_line_237.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_reference_directives_yaml_snippet_line_51(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at reference-directives.qmd:51 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: skip\n'
        'manual: [[ 1,2,3], [4,5,6]]\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'reference_directives_yaml_snippet_line_51.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_reference_directives_markdown_snippet_line_56(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at reference-directives.qmd:56 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '<!-- fmt: off -->\n'
        '*   keep\n'
        '    this\n'
        '    list\n'
        '<!-- fmt: on -->\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == (RES / 'reference_directives_markdown_snippet_line_56.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_reference_directives_yaml_snippet_line_83(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at reference-directives.qmd:83 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '# fmt: canonical=true\n'
        'first: !markdown "This is __strong__."\n'
        'second: "This is __not__ Markdown."\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'reference_directives_yaml_snippet_line_83.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_reference_directives_yaml_snippet_line_148(run, workdir):
    """CATCHES: implementations that treat the documented yaml snippet at reference-directives.qmd:148 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = 'body: !markdown "A paragraph with [a link](https://example.com)."\n'
    result = run(['format', '--stdin-file-path', 'snippet.yaml'], input=stdin)
    assert result.stdout == (RES / 'reference_directives_yaml_snippet_line_148.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_reference_config_markdown_snippet_line_83(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at reference-config.qmd:83 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        'Before\n'
        '{{ render("keep   this") }}\n'
        'after.\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == b'Before {{ render("keep   this") }} after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_reference_config_markdown_snippet_line_91(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at reference-config.qmd:91 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = 'Before {{ render("keep   this") }} after.\n'
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == b'Before {{ render("keep   this") }} after.\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_reference_options_markdown_snippet_line_50(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at reference-options.qmd:50 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '<!-- fmt: table-widths=preserve scope=next -->\n'
        '+----------+------------------+\n'
        '| Name     | Description      |\n'
        '+==========+==================+\n'
        '| A        | Short text       |\n'
        '+----------+------------------+\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == (RES / 'reference_options_markdown_snippet_line_50.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'snippet.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'snippet.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_reference_options_markdown_snippet_line_121(run, workdir):
    """CATCHES: implementations that treat the documented markdown snippet at reference-options.qmd:121 differently from the reference (formatting it when it should be preserved or vice versa, or producing different bytes or diagnostics)."""
    stdin = (
        '---\n'
        'editor_options:\n'
        '  markdown:\n'
        '    wrap: sentence:72\n'
        '    canonical: true\n'
        '    footnotes: preserve\n'
        '    table-widths: preserve\n'
        '---\n'
        'This is __strong__. This is _emphasis_.\n'
    )
    result = run(['format', '--stdin-file-path', 'snippet.md'], input=stdin)
    assert result.stdout == (RES / 'reference_options_markdown_snippet_line_121.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
