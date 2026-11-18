"""Edge-case inputs mined from string literals in the project's Rust unit and
integration tests, selected because each one drives formatter paths no other
case in this suite reaches (flow-collection parsing quirks, tab-indented
markers, document markers with comments, tagged core scalars, Quarto fence
headers, malformed directives, JSON-family edge cases, and `--verify` value
checks).

Every case is run twice: once through stdin with `--stdin-file-path`, and once
in path mode with `--check` on a file of the same name, and both complete
outcomes (stdout, stderr, exit status, file bytes) must match the reference.
"""

import pytest

from conftest import format_both_ways, outcome

CASES = {
    'yaml_000': ('format', 'in.yaml', ['--verify'], '# fmt: markdown\nbody:\nempty: !markdown |\ntag_only: !markdown\n'),
    'yaml_001': ('format', 'in.yaml', [], '[a: b, {c: d}]\n'),
    'md_002': ('format', 'in.md', [], '```{python echo=false}\nx = 1\n```\n\n```{r}\nx = 1\n```\n\n```{ojs}\nviewof x = Inputs.text()\n```\n\n```{code-cell} python\n:tags: [hide-input]\nx = 1\n```\n\n```{#cell .python lst-cap="Cell"}\nx = 1\n```\n\n```{code-cell} ipython3\nx = 1\n```\n'),
    'yaml_003': ('format', 'in.yaml', ['--compact'], '[\n  1,\n\n  2,\n]\n'),
    'yaml_004': ('format', 'in.yaml', [], '\t***\n'),
    'py_005': ('format', 'in.py', [], '# fmt: markdown wrap=none\nbody: |\n  #   Title ##\n  text\n\n# fmt: template.delimiters "<<" ">>"\nvalue: "<< keep   this >>"\n\n# fmt: table\n- {name: a, type: int}\n- {name: long_name, type: string}\n\nflow: [ one ,  two]\nmap: { a : b , long : value }\n'),
    'yaml_006': ('format', 'in.yaml', ['--verify'], 'A paragraph mentions literal markers: * and * * and * * * before continuing.\n\n***\n\nA paragraph mentions literal dashes: --- before continuing.\n\n---\n'),
    'yaml_007': ('format', 'in.yaml', [], '{// comment\n"unformatted":[1,2,],}\n'),
    'yaml_008': ('format', 'in.yaml', [], '[!thing &name "value", &defaults {enabled: true}, !seq [1]]\n'),
    'yaml_009': ('format', 'in.yaml', [], '\xa0# heading\n'),
    'md_010': ('format', 'in.md', [], '::: note\n'),
    'yaml_011': ('format', 'in.yaml', ['--compact'], "flag: !!bool true\nempty: !!null ~\ncount: !!int 42\nratio: !!float 1.5\nname: !!str 'true'\n"),
    'yaml_012': ('format', 'in.yaml', ['--verify'], 'flag: !!bool "TRUE"\nempty: !!null "~"\ncount: !!int "42"\nratio: !!float "1.5"\nname: !!str "true"\n'),
    'yaml_013': ('format', 'in.yaml', ['--verify'], '- lorem: {quote}Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n    Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n    Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.{quote}\n  ipsum: [dolor,sit]\n'),
    'yaml_014': ('format', 'in.yaml', ['--compact'], '- {{name: item_{index}, ratio: !!float "\\x33.14", limit: !!float "\\x31.0e\\x2d3"}}\n'),
    'yaml_015': ('format', 'in.yaml', [], '--- # empty\n... # empty end\n--- # data\nvalue\n... # data end\n'),
    'yaml_016': ('format', 'in.yaml', ['--compact'], 'Term\n: '),
    'json5_017': ('to-yaml', 'in.json5', [], '\r\n \t\r\n'),
    'r_018': ('format', 'in.R', [], '# fmt: markdown\ntext = rr"""\n#   Title ##\n"""\n'),
    'yaml_019': ('format', 'in.yaml', [], '... # data end\n'),
    'md_020': ('format', 'in.md', [], 'Before <kbd>`first\nsecond`</kbd> after _outside_.\n'),
    'py_021': ('format', 'in.py', [], '# fmt:\na: b\n'),
    'yaml_022': ('format', 'in.yaml', [], '# fmt: markdown\nvalue <- render(\n    normalize(\n        prefix,\n        "A    R markdown paragraph.\n"\n    )\n)\nx <- list(a=1,b=2)\n'),
    'jsonc_023': ('to-yaml', 'in.jsonc', [], '{"id":1}\r\n{"id":2}\r\n'),
    'py_024': ('format', 'in.py', [], '# fmt: canonical=true\nfirst: !markdown "This is __strong__."\nsecond: !markdown "This is __strong__."\n'),
    'yaml_025': ('format', 'in.yaml', [], '::: note\n```markdown\nBefore `first  \t\n  second\\\nthird [x]( url )` after _outside_.\n \t\nNext   paragraph.\t\n```\n:::\n'),
    'yaml_026': ('format', 'in.yaml', [], "{first:'a\u2028b',second:'c\u2029d',broken:}\n"),
    'yaml_027': ('format', 'in.yaml', [], '# fmt: json\nbody:    |\n  {"name":"yamark"}\n'),
    'yaml_028': ('format', 'in.yaml', [], '[![Microsoft Foundry Discord](\n  https://dcbadge.limes.pink/api/server/nTYy5BXMWG\n)](https://discord.gg/nTYy5BXMWG)\n'),
    'yaml_029': ('format', 'in.yaml', [], '[^note]: Before `first  \n    second [x]( url )` after *outside*.\n'),
    'r_030': ('format', 'in.R', [], 'text <- r"(\n'),
    'yaml_031': ('format', 'in.yaml', [], "- - !note &saved # parent\n    'Café value'\n  - [one, two]\n# fmt: skip\n- !markdown |\n  Keep __raw__  bytes.  \n# fmt: markdown canonical=true scope=file\n# fmt: compact scope=file\n"),
    'md_032': ('format', 'in.md', [], '- top item {index:04} carries lorem prose and [a long unwrappable reference](https://example.com/pathological/segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}).\n- top item {next:04} carries lorem prose and [a short reference](https://example.com/short/{next:04}).\n  - nested item {index:04} carries lorem prose and [a long unwrappable reference](https://example.com/pathological/segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}).\n\n'),
    'yaml_033': ('format', 'in.yaml', [], '\t---\n'),
    'yaml_034': ('format', 'in.yaml', [], '    "\n'),
    'yaml_035': ('format', 'in.yaml', [], '"""Module docstring."""\n\ndef read_source() -> str:\n    return run(\n        # fmt: r\n        stdin="""\n            f <- function(x) x + 1\n        """,\n    )\n'),
    'md_036': ('format', 'in.md', [], '#!/bin/sh\nfind "$1" -name \'*.yaml\' -exec perl -0pi -e \'s/probe:\\s+\\[one,two\\]/probe: [one, two]/g; s/name:\\s+/name: /g\' {} +\n'),
    'yaml_037': ('format', 'in.yaml', [], '-\n\n>\n\n> -\n\n- >\n\n```markdown\n-\n```\n\n- `  `\n\n> $  $\n'),
    'md_038': ('format', 'in.md', [], '- Before **strong**.\n  Second sentence.\n  - Nested *words*.\n    Another sentence.\n\n> Quoted **words**.\n> Another sentence.\n\n<!-- fmt: canonical=true wrap=sentence scope=file -->\n'),
    'yaml_039': ('format', 'in.yaml', [], '- {{name: item_{index}, count: !!int "\\x31_000", delta: !!int "\\x2d42"}}\n'),
    'md_040': ('format', 'in.md', [], '---\nitems:\n  - "one"\n# fmt: skip\n...\n'),
    'yaml_041': ('format', 'in.yaml', [], '------------\nA\tB\n---\t---\nx\ty\n\na\tb\n------------\n'),
    'yaml_042': ('format', 'in.yaml', [], '::: note\n'),
    'py_043': ('format', 'in.py', [], '<!-- fmt: template.delimiters "[\\"" "\\"]" -->\nThis [" keep   spacing "] paragraph.\n'),
    'yaml_044': ('format', 'in.yaml', [], 'A paragraph with `inline code spans`, [short links](https://example.com/short), <https://example.com/autolink>, $x + y$, and {#attrs} keeps every protected span while wrapping the surrounding prose.\n'),
    'md_045': ('format', 'in.md', [], '[![Microsoft Foundry Discord](\n  https://dcbadge.limes.pink/api/server/nTYy5BXMWG\n)](https://discord.gg/nTYy5BXMWG)\n'),
    'md_046': ('format', 'in.md', [], '````yaml\nouter: !markdown |\n  ```yaml\n  inner: !markdown |\n    Keep **strong** and `literal  bytes`.\n  ```\n````\n\n<!-- fmt: canonical=true scope=file -->\n'),
    'yaml_047': ('format', 'in.yaml', ['--compact'], 'flag: !!bool "TRUE"\nempty: !!null "~"\ncount: !!int "42"\nratio: !!float "1.5"\nname: !!str "true"\n'),
    'md_048': ('format', 'in.md', [], '{{ foo }} and [real](multi\nline)'),
    'yaml_049': ('format', 'in.yaml', [], '  "name": "yamark",\n'),
    'yaml_050': ('format', 'in.yaml', ['--verify'], '  - FALSE\n'),
    'yaml_051': ('format', 'in.yaml', [], '  item_{index:04}: {{name: worker-{index:04},replicas: {},ports: [8000,9000],env: {{LOG_LEVEL: info,FEATURE_FLAG: false}},resources: {{cpu: {}m,memory: {}Mi}},dependencies: [service-{:04},service-{:04}]}}\n'),
    'yaml_052': ('format', 'in.yaml', [], '![](mcp-repl-useR-lightning-assets/chat-scenario.png) { fig-alt="A chat interface where a user asks an agent to explore a dataset and build a first model. The agent responds by running several bash tool calls with Rscript." }\n'),
    'md_053': ('format', 'in.md', [], '![](mcp-repl-useR-lightning-assets/chat-scenario.png){\n  fig-alt="A chat interface where a user asks an agent to explore a dataset and build a\nfirst model. The agent responds by running several bash tool calls with Rscript."\n}\n'),
    'md_054': ('format', 'in.md', [], '#   {}\n'),
    'md_055': ('format', 'in.md', [], '# empty object\na: {}\n# empty array\nb: []\n'),
    'md_056': ('format', 'in.md', [], '# fmt: compact table\n- ? name\n  : a\n  type: int\n- name: long_name\n  type: string\n'),
    'md_057': ('format', 'in.md', [], '# fmt: custom-json\nbody:    |\n  {"name":"yamark"}\n'),
    'md_058': ('format', 'in.md', [], '# fmt: markdown\n? key\n: |\n  #   Title ##\n'),
    'yaml_059': ('format', 'in.yaml', [], '# fmt: markdown\n{wide_space}# abc de\n{wide_space}# f\n'),
    'py_060': ('format', 'in.py', [], '# fmt: template.delimiters "<<" ">>"\n# ordinary\nvalue: << keep >>\n'),
    'py_061': ('format', 'in.py', [], '# fmt: template.delimiters "<<" ">>" scope=file\na: [<< a,b >>]\n'),
    'md_062': ('format', 'in.md', [], '#!/bin/sh\nif [ "$1" = "--version" ]; then\n  echo "{version}"\n  exit 0\nfi\ntarget=\nfor arg do\n  target="$arg"\ndone\nif [ -d "$target" ]; then\n  find "$target" -name \'*.md\' -exec perl -0pi -e \'s/Generated Markdown Benchmark Document/Formatted Markdown Benchmark Document/g\' {{}} +\nelse\n  perl -0pi -e \'s/Generated Markdown Benchmark Document/Formatted Markdown Benchmark Document/g\' "$target"\nfi\n'),
    'md_063': ('format', 'in.md', [], '#!/usr/bin/env bash\nset -euo pipefail\ncase "$2" in\n  process.platform) echo linux ;;\n  process.arch) echo x64 ;;\n  *) exit 42 ;;\nesac\n'),
    'yaml_064': ('format', 'in.yaml', ['--compact'], '- [ ] first item has many words\n      that should wrap under the\n      checkbox marker\n- [x] done item has many words\n      that should wrap under the\n      checkbox marker\n- [X] also done has many words\n      that should wrap under the\n      checkbox marker\n'),
    'yaml_065': ('format', 'in.yaml', [], '- top item {index:04} carries lorem prose and [a long unwrappable reference](https://example.com/pathological/segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}).\n- top item {next:04} carries lorem prose and [a short reference](https://example.com/short/{next:04}).\n  - nested item {index:04} carries lorem prose and [a long unwrappable reference](https://example.com/pathological/segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}-segment-{index:04}).\n\n'),
    'md_066': ('format', 'in.md', [], '--- {0}\n+++ {0}\n@@ -898,7 +898,7 @@\n key_897: value\n key_898: value\n key_899: value\n-key_900: [a,b]\n+key_900: [a, b]\n key_901: value\n key_902: value\n key_903: value\n'),
    'yaml_067': ('format', 'in.yaml', ['--verify'], ': first line  \n'),
    'yaml_068': ('format', 'in.yaml', ['--verify'], '::: {.callout-note}\n'),
    'md_069': ('format', 'in.md', [], '<!-- fmt: template.delimiters "<<" ">>" scope={scope} -->\n'),
    'md_070': ('format', 'in.md', [], '<!-- ordinary\n'),
    'yaml_071': ('format', 'in.yaml', [], '? [red, blue]\n: purple\n? {left: right}\n: mirror\n'),
    'md_072': ('format', 'in.md', [], 'A             B\n-----  ------------\nx      y\n'),
    'md_073': ('format', 'in.md', [], 'Before\n<<\nkeep   this >> after _word_.\n'),
    'md_074': ('format', 'in.md', [], 'Configured yamark Git filter in {}\nUpdated {} with {added} new attribute pattern(s)\n\nNext step:\n  git add --renormalize .\n\nUndo:\n  Temporarily stage one file exactly as it appears in the working tree:\n    git -c filter.yamark-md.clean=cat add <path>\n  Permanently remove this local setup:\n    yamark git-filter teardown\n\nPer-file control:\n  Add later Git attribute lines to .git/info/attributes or .gitattributes:\n    NEWS.md -filter\n  Then use the normal formatter for that file, for example:\n    yamark format --wrap {width} NEWS.md\n  Use <!-- fmt: skip file --> inside a Markdown file to leave its contents untouched.'),
    'md_075': ('format', 'in.md', [], 'JSON Lines semantic test failed\nstdout:\n{}\nstderr:\n{}'),
    'md_076': ('format', 'in.md', [], 'Term\n: '),
    'md_077': ('format', 'in.md', [], 'This keeps ***asterisk triple***, ___underscore triple___, **_strong em_**, __*strong em*__, *__em strong__*, and _**em strong**_ exactly.\n'),
    'md_078': ('format', 'in.md', [], '[\n  ? foo\n    bar : baz,\n  : empty key entry,\n  {JSON: like}:adjacent\n]\n'),
    'md_079': ('format', 'in.md', [], '```\nliteral output\n  preserve spacing\n```\n\n```rust\nfn main() {\n    println!("hello");\n}\n```\n\n```console\n$ yamark format .\n```\n\n```mermaid\nflowchart LR\n  A --> B\n```\n'),
    'yaml_080': ('format', 'in.yaml', ['--compact'], 'defaults: &defaults {"enabled": true}\ntyped: !flags [1, 2]\n'),
    'yaml_081': ('format', 'in.yaml', [], 'dependencies:\n  - pip:\n    - -r requirements.txt\n'),
    'yaml_082': ('format', 'in.yaml', ['--compact'], 'items: !!seq [ one , two ]\nmapping: !!map { a : b }\nblock_seq: !!seq\n  - one\n  - two\nblock_map: !!map\n  a: b\nanchored: &items !!seq [ one ]\n'),
    'yaml_083': ('format', 'in.yaml', ['--compact'], 'name: &name !markdown value\nalias: *name\n'),
    'yaml_084': ('format', 'in.yaml', [], '{\n  // before a\n  "a": 1, // after a\n  "url": "https://example.test/a/*b*/", // after url: value\n  /* before nested */\n  "nested": {"b": 2 /* after b */},\n}\n'),
    'yaml_085': ('format', 'in.yaml', [], '{\n// JSON5 values\nfoo:1,\nsingle: \'don\\\'t\',\napostrophe: "don\\\'t",\nletter: "\\a",\nunderscore: "\\_",\nemoji: "\\uD83D\\uDE00",\nhex: 0X2A,\ninfinity: Infinity,\nnegativeInfinity: -Infinity,\nnan: NaN,\nescaped: {\\u0061: "\\x41"},\nleading: .5,\ntrailing: 5.,\npositive: +1,\ncontinued: \'one \\\nline\',\n}\n'),
    'yaml_086': ('format', 'in.yaml', [], '{[red, blue]: purple, {left: right}: mirror}\n'),
    'yaml_087': ('format', 'in.yaml', [], '{foo: !!str, !!str: bar, anchored: &empty}\n'),
    'yaml_088': ('format', 'in.yaml', [], "{lf:'a\\\nb',cr:'a\\\rb',crlf:'a\\\r\nb',ls:'a\\\u2028b',ps:'a\\\u2029b'}\n"),
    'md_089': ('format', 'in.md', [], '{{\n  "schema_version": 1,\n  "benchmark": "yaml-formatting",\n  "run_id": "{commit}",\n  "git": {{\n    "commit": "{commit}",\n    "short_commit": "{commit}",\n    "commit_time": "{commit_time}",\n    "dirty": false\n  }},\n  "corpus": {{\n    "kind": "yaml",\n    "shape": "representative",\n    "files": 2,\n    "items_per_file": 2,\n    "bytes": 2048\n  }},\n  "invocation": {{\n    "unit": "per-file"\n  }},\n  "results": [\n    {{\n      "formatter": "yamark",\n      "status": "ok",\n      "command": "yamark format TARGET",\n      "invocation": "per-file",\n      "operation": "write",\n      "width_profile": "default",\n      "changed_files": 2,\n      "output_bytes": 2048,\n      "repetitions": [{yamark_seconds}],\n      "median_seconds": {yamark_seconds},\n      "mean_seconds": {yamark_seconds},\n      "mb_per_second": 1.0\n    }},\n    {{\n      "formatter": "dprint-yaml",\n      "status": "ok",\n      "command": "dprint fmt TARGET",\n      "invocation": "per-file",\n      "operation": "write",\n      "width_profile": "default",\n      "changed_files": 2,\n      "output_bytes": 2048,\n      "repetitions": [0.040],\n      "median_seconds": 0.040,\n      "mean_seconds": 0.040,\n      "mb_per_second": 0.5\n    }}\n  ]\n}}\n'),
    'yaml_090': ('format', 'in.yaml', [], '{{ render("multi\nline") }}'),
    'json5_091': ('to-yaml', 'in.json5', [], "{{value:'{}\u2028tail'}}\n"),
    'md_092': ('format', 'in.md', [], '| keeps   spacing\n\n'),
    'yaml_093': ('format', 'in.yaml', [], '| name | value |\n------ | -----\nshort | one\nlong name | two\n'),
}



@pytest.mark.parametrize("name", sorted(CASES))
def test_mined_input(name, run, workdir, golden):
    """CATCHES: divergent handling of unusual-but-valid inputs: different quoting, spacing,
    preservation decisions, directive errors, verification failures, or check-mode summaries,
    since both the stdin output and the path-mode --check outcome are compared exactly."""
    kind, path, flags, text = CASES[name]
    if kind == "format":
        observed = format_both_ways(run, workdir, path, text, *flags)
    else:
        observed = {"stdin": outcome(run(["to-yaml", "--stdin-file-path", path, *flags], input=text))}
    assert observed == golden(name)
