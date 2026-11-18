"""Harvested inputs transformed by structural mutations: CRLF or bare-CR line endings,
a UTF-8 byte order mark, a missing final newline, tab indentation, nesting under a YAML
key or sequence item, inside a Markdown list, blockquote, fenced div, `markdown` or
`yaml` fence, front matter, a `!markdown` scalar, or a Python Markdown comment.

The selected variants reach parsing and emission decisions that the original inputs
never hit. Each case is formatted through stdin and through path-mode `--check`, and
both complete outcomes must match the reference.
"""

import pytest

from conftest import format_both_ways, outcome

CASES = {
    'yaml_000': ('format', 'in.yaml', [], '# fmt: compact table\n- ? name\n\t: a\n\ttype: int\n- name: long_name\n\ttype: string\n'),
    'yaml_001': ('format', 'in.yaml', [], '- *alias: "\\n\\x20first\\n\\\n    Traceback:\\n\\x201: frame"\n  flow: [a,b]\n'),
    'md_002': ('format', 'in.md', [], '+\n---  ---\nx    y'),
    'md_003': ('format', 'in.md', [], '[^note]: Before `first  \n    second [x]( url )` after _outside_.\n\n[^more]: First paragraph.\n\n    Before $first\t\n      second \\$ [x]( url )$ after _outside_.'),
    'md_004': ('format', 'in.md', [], '\ufeff---\n"---"\n---\n\nBody.\n'),
    'md_005': ('format', 'in.md', [], '- <!-- fmt: template.delimiters "{{" "END" scope=file -->\n  <!-- fmt: template.delimiters "{{!" "FIN" scope=file -->\n  Before\n  {{ value END\n  after _word_ and {{ ordinary.name }}.\n\n  > Before\n  > {{ render("a\u3000b") END\n  > after _word_.\n\n  Before\n  {{! keep   this FIN\n  after _word_.\n'),
    'yaml_006': ('format', 'in.yaml', [], '# fmt: json\n? |\n\tkey\n: value\n'),
    'yaml_007': ('format', 'in.yaml', [], '# fmt: json\nbody:\t\t|\n\t{"name":"yamark"}\n'),
    'md_008': ('format', 'in.md', [], '> A `code span with spaces` after.\n>\n> A [label with spaces](dest) after.\n>\n> This ~~struck text keeps    spacing~~.\n>\n> This `unterminated code span keeps    spacing.\n>\n> This [reference][id] keeps    spacing.\n'),
    'yaml_009': ('format', 'in.yaml', [], '# fmt: compact scope=file\nitems:\n  - {name: a\n    kind: scalar\n  - {name: longer\n    kind: sequence\n'),
    'yaml_010': ('format', 'in.yaml', [], '# fmt: compact scope=file\ntags:\n[\n  - llm\n  - authoring\n  - formats\n'),
    'md_011': ('format', 'in.md', [], '> ---\n> title: "Hello"\n> body: !markdown "This is __strong__."\n> ---\n> Text __strong__.\n>\n> <!-- fmt: canonical=true scope=file -->\n'),
    'md_012': ('format', 'in.md', [], '- <!-- fmt: off -->\n  ````text\n  {{< unfinished\n  ```\n  {{% still inside the longer fence\n  ````\n  Keep   this disabled.\n  <!-- fmt: on -->\n  Format   after backtick\n  fence.\n\n  <!-- fmt: off -->\n  ~~~text\n  {{% unfinished message="\n  ~~~\n  <!-- fmt: on -->\n  Format   after tilde\n  fence.\n\n  <!-- fmt: off -->\n  <!-- ordinary comment\n  ```text\n  {{< unfinished\n  -->\n  <!-- fmt: on -->\n  Format   after HTML\n  comment.\n\n  <!-- fmt: off -->\n  <!-- ordinary comment\n  <!-- fmt: on -->\n  Format   after the existing\n  linewise directive.\n\n  <!-- fmt: off -->\n  ```text\n  <!-- fmt: on -->\n  Format   after the existing\n  fenced directive.\n'),
    'md_013': ('format', 'in.md', [], '> <!-- fmt: table -->\n> | a |\n> |---|\n'),
    'yaml_014': ('format', 'in.yaml', [], '# fmt: table\n- {\n\tname: a,\n\tdesc: "one, two"\n}\n- {\n\tname: longer,\n\tdesc: z\n}\n'),
    'md_015': ('format', 'in.md', ['--verify'], 'Intro.\n\n```yaml\n--- |-\n ab\n \n...\n```\n'),
    'md_016': ('format', 'in.md', ['--verify'], 'Intro.\n\n```yaml\nouter:\n  - value: |2-\n      first\n       \n      last\n    after: x\n```\n'),
    'md_017': ('format', 'in.md', [], '- - First. Second.\n    <span>\n    Third. Fourth.\n\n  > First. Second.\n  > <img src="x">\n  > Third. Fourth.\n\n  - First. Second.\n    </span>\n    Third. Fourth.\n\n  - <span>\n    Alpha. Beta.\n\n  > <span>\n  > Alpha. Beta.\n\n  - First. Second.\n    <pre>\n    alpha    beta\n    </pre>\n\n  > First. Second.\n  > <pre>\n  > alpha    beta\n  > </pre>\n'),
    'md_018': ('format', 'in.md', [], '\ufeff---\t---\na\tb\n---\t---\n'),
    'md_019': ('format', 'in.md', [], '---\rdescription: >\r  This is a folded scalar with enough words to rewrap into several shorter lines\r\rauthors: Tomasz Kalinowski\r---\rBody text.\r'),
    'md_020': ('format', 'in.md', [], '::: note\rBefore\r%% render("a\u3000b") %%\rafter _word_.\r:::\r\r```markdown\rBefore\r%% render("a\u3000b") %%\rafter _word_.\r```\r\r<!-- fmt: template.delimiters "%%" "%%" scope=file -->\r'),
    'yaml_021': ('format', 'in.yaml', [], 'body: !markdown |\n  ::: note\n  ```markdown\n  Before `first  \t\n    second\\\n  third [x]( url )` after _outside_.\n \t\n  Next   paragraph.\t\n  ```\n  :::\n\n  > ```markdown\n  > Before `first  \n  >   second [x]( url )` after _outside_.\n  > ```\n\n  - Example\n\n    ```markdown\n    Before `first  \n      second [x]( url )` after _outside_.\n    ```\n'),
    'py_022': ('format', 'in.py', [], '# fmt: markdown\n# <!-- fmt: -->\n# # Title\nx = 1\n'),
    'yaml_023': ('format', 'in.yaml', [], 'body: !markdown |\n  First line \t\n\n  ```text\n  kept? \t\n  ```\n  last line\t'),
    'py_024': ('format', 'in.py', [], '"""Module docstring."""\r\n\r\ndef read_source() -> str:\r\n    return run(\r\n        # fmt: r\r\n        stdin="""\r\n            f <- function(x)x+1\r\n        """,\r\n    )\r\n'),
    'yaml_025': ('format', 'in.yaml', [], '\ufeff# Lorem ipsum\nlorem: \'Lorem ipsum dolor sit amet,\n  consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\'\nipsum:\n  - "Lorem ipsum dolor\n    sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."\ndolor: [lorem,ipsum] # Dolor sit amet.\nsit: \'Lorem\n  ipsum\' # Sit amet.\n'),
    'yaml_026': ('format', 'in.yaml', [], '# fmt: markdown\n? key\n: |\n\t#\t Title ##\n'),
    'yaml_027': ('format', 'in.yaml', [], '- # fmt: markdown\n  lorem:\n    |2\n        Lorem __ipsum__.\n  ipsum: [dolor,sit]\n  ---\n  - !md\n    |2\n        Lorem __ipsum__.\n  - [dolor,sit]\n  ---\n      !markdown |2\n        Lorem __ipsum__.\n'),
    'yaml_028': ('format', 'in.yaml', [], '# fmt: table\r\n- {\r\n  name: a,\r\n  desc: "one, two"\r\n}\r\n- {\r\n  name: longer,\r\n  desc: z\r\n}\r\n'),
    'yaml_029': ('format', 'in.yaml', [], 'held: &saved # parent\n\t\'Café value\'\nquoted: "<< item >>"\nitems: [<< a,b >>]\nbody: !markdown |\n\tKeep __strong__ and << literal\tbytes >>.\nplain: !markdown |\n\tKeep __strong__ and `literal\tbytes`.\nattached: !markdown\n\t|\n\t\tKeep __attached__.\nok: [x,y]\n# fmt: template.delimiters "<<" ">>" scope=file\n# fmt: markdown canonical=true scope=file\n'),
    'yaml_030': ('format', 'in.yaml', [], '# fmt: compact scope=file\nouter:\n  ? key\n  : first line\n    second line\n  after: x\n'),
    'yaml_031': ('format', 'in.yaml', ['--verify'], '- \ufeff- one\n  ---\n  name:    value\n'),
    'md_032': ('format', 'in.md', [], '\ufeff$$ E = mc^2 + very_long_symbol\nmore math content\n$$\n'),
    'md_033': ('format', 'in.md', [], '\ufeff+---+---+\n|\n+---+---+\n'),
    'md_034': ('format', 'in.md', [], '+------+-----+\n| Name | Value |\n+======+=====+\n| a | one |\n+------+-----+\n| longer | two |\n+------+-----+'),
    'md_035': ('format', 'in.md', [], '- -   Item.\n    ~~~text\n    code\n    ~~~\n\n  -   Item.\n    <pre>\n    alpha    beta\n    </pre>\n'),
    'md_036': ('format', 'in.md', [], '- first line\t\n\tsecond line\n\n> first line\t\n> second line\n\nTerm\n: first line\t\n\t\tsecond line\n\n[^note]: first line\t\n\t\tsecond line\n'),
    'md_037': ('format', 'in.md', [], '- ::: note\n  ```markdown\n  Before `first  \t\n    second\\\n  third [x]( url )` after _outside_.\n \t\n  Next   paragraph.\t\n  ```\n  :::\n\n  > ```markdown\n  > Before `first  \n  >   second [x]( url )` after _outside_.\n  > ```\n\n  - Example\n\n    ```markdown\n    Before `first  \n      second [x]( url )` after _outside_.\n    ```\n'),
    'md_038': ('format', 'in.md', [], '> <!-- fmt: skip -->  \n> Keep   é prose.  \t\n> And   this line.   \n>\n> Format   outside. Second   sentence. \n>\n> <!-- fmt: skip -->\n> - Keep   list.  \t\n>   continuation   unchanged.  \n> - Another   item.   \n>\n> <!-- fmt: skip -->\n> > Keep   quote.  \n> > Next   line. \t\n>\n> <!-- fmt: skip -->\n> ::: {.note}  \n> Keep   prose.  \n>\n> ```text\n> code   with spaces  \n> ```\n>\n> $$\n> x + y  \n> $$\n>\n> <div>\n> HTML   with spaces  \n> </div>\n>\n> [malformed](   \n> :::  \n>\n> <!-- fmt: skip -->\n> ```markdown  \n> Keep   fence prose.  \n> ````  \n>\n> Format   after containers. \n'),
    'md_039': ('format', 'in.md', [], '- <img alt="A chat interface where a user asks an agent to explore a\n  dataset and build a first model. The agent responds by running several\n  bash tool calls with Rscript."\n  src="mcp-repl-useR-lightning-assets/chat-scenario.png" style="width:\n  100%; fig-align=\'center\'"\n  >\n'),
    'md_040': ('format', 'in.md', [], '\ufeff<img src="man/figures/README-umap-example-1.png" alt="A two-dimensional UMAP embedding of MNIST digits colored by digit label." width="100%" />\n'),
    'md_041': ('format', 'in.md', [], '- Before  $first  \n    second \\$ [x]( url )$ after _outside_ [real](  target  ).\n\n  > > Before `first\t\n  > >   second [x]( url )` after _outside_.\n\n  Before `{{ render_item() }}` after [real](  target  ).\n\n  Before `{{\n    render_item()\n  }}` after _outside_ [real](  target  ).\n\n  > > Before <tag> value.\n  > > Next [r](  t  ) _outside_.\n\n  > > Before [r](  t  ) _outside_.\n  > > > Next [r](  t  ) _outside_.\n'),
    'md_042': ('format', 'in.md', [], '- Before.\n\n  ----------  ----------\n  A           B\n  ----------  ----------\n  x  one      y  two\n  ----------  ----------\n'),
    'md_043': ('format', 'in.md', [], '- Title\n  =\n\n  Subtitle\n  -\n'),
    'md_044': ('format', 'in.md', [], '```yaml\nbody: !markdown |\n\tThis is __strong__ before the directive.\n```\n\n<!-- fmt: canonical=true scope=file -->\n'),
    'md_045': ('format', 'in.md', [], '| Include | Target |\n|---|---|\n| footer | {{< include _footer.md >}} |\n\n| Name | Value |\n|---|---|\n| title | `{{{< meta title >}}}` |'),
    'py_046': ('format', 'in.py', [], '# fmt: markdown\nx = 1 # """\n#   Title ##\n"""'),
    'yaml_047': ('format', 'in.yaml', [], '!tag key: "\\n\\x20first\\n\\\r\n  Traceback:\\n\\x201: frame"\r\nflow: [a,b]\r\n'),
    'yaml_048': ('format', 'in.yaml', [], '# fmt: json\nbody:    |\n  {"name":"yamark"}'),
    'md_049': ('format', 'in.md', [], '---\n# fmt: markdown\nlorem:\n  |2\n      Lorem __ipsum__.\nipsum: [dolor,sit]\n---\n- !md\n  |2\n      Lorem __ipsum__.\n- [dolor,sit]\n---\n    !markdown |2\n      Lorem __ipsum__.\n---\n\nBody text.\n'),
    'md_050': ('format', 'in.md', ['--verify'], 'Intro.\n\n```yaml\ntext: |-\n  \n   *** caught segfault ***\n  address 0x0\n```\n'),
}



@pytest.mark.parametrize("name", sorted(CASES))
def test_mutated_input(name, run, workdir, golden):
    """CATCHES: divergent handling of unusual-but-valid inputs: different quoting, spacing,
    preservation decisions, directive errors, verification failures, or check-mode summaries,
    since both the stdin output and the path-mode --check outcome are compared exactly."""
    kind, path, flags, text = CASES[name]
    if kind == "format":
        observed = format_both_ways(run, workdir, path, text, *flags)
    else:
        observed = {"stdin": outcome(run(["to-yaml", "--stdin-file-path", path, *flags], input=text))}
    assert observed == golden(name)
