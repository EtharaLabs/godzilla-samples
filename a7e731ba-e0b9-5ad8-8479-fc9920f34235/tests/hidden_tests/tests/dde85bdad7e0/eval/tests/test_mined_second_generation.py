"""Second-generation variants of this suite's own targeted inputs: option changes
(`--compact`, `--line-width 30`, `--wrap sentence/none/30`, `--canonical`,
`--prose-width 20`, `--verify`) and structural mutations (line endings, BOM, tabs,
nesting under YAML keys, lists, quotes, fences or front matter), selected because
each reaches a branch none of the original inputs reach.

Each case is formatted through stdin and through path-mode `--check`, and both
complete outcomes must match the reference.
"""

import pytest

from conftest import format_both_ways, outcome

CASES = {
    'yaml_000': ('format', 'in.yaml', [], '# fmt: table\n- {name: a, # c\n\ttype: b}\n- {name: bb, type: c}\n'),
    'yaml_001': ('format', 'in.yaml', [], '- ? [a, b]\n  : 1\n  ? {c: d}\n  : 2\n'),
    'md_002': ('format', 'in.md', [], '- Before.\n\n\t----------\t----------\n\tA\t\t\t\t\t B\n\t----------\t----------\n\tx\tone\t\t\ty\ttwo\n\t----------\t----------\n'),
    'yaml_003': ('format', 'in.yaml', [], "- - !note &saved # parent\n\t\t'Café value'\n\t- [one, two]\n# fmt: skip\n- !markdown |\n\tKeep __raw__\tbytes.\t\n# fmt: markdown canonical=true scope=file\n# fmt: compact scope=file\n"),
    'yaml_004': ('format', 'in.yaml', [], '# fmt: compact scope=file\n? key\n:\n\tnested: 1\n'),
    'yaml_005': ('format', 'in.yaml', ['--compact'], '- \ufeff- one\n  ---\n  name:    value\n'),
    'yaml_006': ('format', 'in.yaml', ['--compact'], '[1,\x852]'),
    'yaml_008': ('format', 'in.yaml', [], '- -\n\n  >\n\n  > -\n\n  - >\n\n  ```markdown\n  -\n  ```\n\n  - `  `\n\n  > $  $\n'),
    'md_009': ('format', 'in.md', [], '---\n: first line  \n---\n\nBody text.\n'),
    'md_010': ('format', 'in.md', [], '+\r\n---  ---\r\nx    y'),
    'md_011': ('format', 'in.md', ['--wrap', '30'], '---\ntitle: Yamark\nbody-classes: yamark-home\ntoc: false\n---\n\n```{r}\n#| label: setup-homepage-examples\n#| include: false\nsource("_yamark-build.R")\n\nget_chunk <- function(label) {\n  paste(knitr::knit_code$get(label), collapse = "\\n")\n}\n\nemit_before_after <- function(label, stdin_file_path = "example.md") {\n  before <- get_chunk(label)\n  after <- yamark_format(before, stdin_file_path = stdin_file_path)\n\n  writeLines(c(\n    ":::: {.before-after}",\n    "::: {.before-after-pane #demo-before}",\n    \'**Before** <label class="softwrap-toggle"><input type="checkbox" id="demo-softwrap-toggle"> soft wrap</label>\',\n    "",\n    markdown_fence(before),\n    "",\n    ":::",\n    "",\n    "::: {.before-after-pane}",\n    "**After**",\n    "",\n    markdown_fence(after),\n    ":::",\n    "::::"\n  ))\n}\n```\n\n::: {.hero-shell}\n::: {.hero-copy}\n::: {.hero-kicker}\n![](assets/favicon.svg){.hero-mark}\n:::\n\n<h1 class="hero-thesis">A fast formatter for YAML and Markdown.</h1>\n\nYamark formats whole files and embedded content with the consistency we expect\nfrom code, keeping source readable and changes easy to review.\n\n::: {.hero-actions}\n[Install](usage.qmd#install){.hero-button .primary}\n[See examples](examples.qmd){.hero-button}\n:::\n\n::: {.hero-command}\n<span>Run directly from PyPI</span>\n`uvx yamark format`\n:::\n:::\n:::\n\n::: {.workflow-strip}\n::: {.workflow-item}\n**Format**\n\nRewrite supported files in place.\n:::\n\n::: {.workflow-item}\n**Check**\n\nUse non-mutating CI and diff modes.\n:::\n\n::: {.workflow-item}\n**Embed**\n\nFormat marked Markdown in YAML, Python, or R.\n:::\n\n::: {.workflow-item}\n**Recurse**\n\nFormat nested YAML and Markdown inside fenced blocks.\n:::\n:::\n\n## A quick example\n\nA short Markdown file with YAML front matter - a native document format for LLM\nwork. It combines software-readable structure with natural language for prompts,\nskills, reference documents, and generated output. The Before pane shows the\nunformatted source; the After pane shows what `yamark format` writes back.\n\n```{cat}\n#| label: example-text\n#| include: false\n---\ntitle: Why YAML + Markdown?\ndescription: The source languages of LLM work - structured fields for tools alongside instructions, examples, and context for models.\ntags: [llm,authoring,formats]\n---\n\n#   Why YAML + Markdown? ##\n\nWhen LLMs become part of a software system, YAML and Markdown start to feel like programming languages. YAML defines named fields tools can act on; Markdown carries the instructions, examples, and context that shape model behavior. Together they create a shared source file that stays readable to people and models, exposes explicit structure to software, produces clear diffs, and renders directly.\n\nWhere the combination shines:\n\n- Agent skills and prompt files keep names, versions, and tool metadata beside the instructions they describe.\n  - The Markdown body can carry code samples and nested structures with their own syntax and indentation.\n- Reference documents stay readable to authors and models without a separate source format or build step.\n- Tool inputs and model outputs survive chat, Git, and documentation pipelines as recognizable text.\n- One source can render as HTML or PDF and travel unchanged as agent context.\n```\n\n```{r}\n#| label: render-example-text\n#| echo: false\n#| results: asis\nemit_before_after("example-text")\n```\n\nToggle soft wrap on the Before pane to inspect the input\'s physical lines.\nYamark wraps and indents each region according to its own grammar.\n\n```{=html}\n<script>\n(function () {\n  var toggle = document.getElementById(\'demo-softwrap-toggle\');\n  var pane = document.getElementById(\'demo-before\');\n  if (!toggle || !pane) return;\n  var apply = function () { pane.classList.toggle(\'soft-wrap\', toggle.checked); };\n  toggle.addEventListener(\'change\', apply);\n  apply();\n})();\n</script>\n```\n\n## Performance\n\n```{r}\n#| label: setup-home-benchmarks\n#| include: false\nsource("_benchmark-data.R")\n```\n\n`r benchmark_headline()`\n\n```{r}\n#| label: homepage-benchmark-field\n#| echo: false\n#| results: asis\n\nwrite_benchmark_chart(\n  id = "homepage-benchmark-field",\n  title = "Elapsed time across formatter CLIs",\n  subtitle = paste(\n    "Every formatter in the checked-in comparison.",\n    "Median wall time; lower is better.",\n    "All four panels share a logarithmic seconds scale."\n  ),\n  rows = benchmark_full_field_rows()\n)\n```\n\nThe [Benchmarks](benchmarks.qmd) page includes detailed tables, methodology,\nchecked-in results, and reproduction commands.\n'),
    'md_012': ('format', 'in.md', ['--wrap', '30'], '```{python echo=false}\nx = 1\n```\n\n```{r}\nx = 1\n```\n\n```{ojs}\nviewof x = Inputs.text()\n```\n\n```{code-cell} python\n:tags: [hide-input]\nx = 1\n```\n\n```{#cell .python lst-cap="Cell"}\nx = 1\n```\n\n```{code-cell} ipython3\nx = 1\n```\n'),
    'yaml_013': ('format', 'in.yaml', [], '# fmt: compact scope=file\ntags:\n[\n\t- llm\n\t- authoring\n\t- formats\n'),
    'md_014': ('format', 'in.md', [], '---\n? [a,   b]\n: {c:   d}\n---\n\nBody text.\n'),
}



@pytest.mark.parametrize("name", sorted(CASES))
def test_second_generation_input(name, run, workdir, golden):
    """CATCHES: divergent handling of unusual-but-valid inputs: different quoting, spacing,
    preservation decisions, directive errors, verification failures, or check-mode summaries,
    since both the stdin output and the path-mode --check outcome are compared exactly."""
    kind, path, flags, text = CASES[name]
    if kind == "format":
        observed = format_both_ways(run, workdir, path, text, *flags)
    else:
        observed = {"stdin": outcome(run(["to-yaml", "--stdin-file-path", path, *flags], input=text))}
    assert observed == golden(name)
