"""Markdown inline transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_angle_link_destinations(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of angle link destinations; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '[text](<https://example.com>)\n'
        '\n'
        '![image](<https://example.com/image.png>)\n'
        '\n'
        '[![image](<https://example.com/image.png>)](<https://example.com>)\n'
        '\n'
        '[![image](image.png)](<https://example.com>)\n'
        '\n'
        '[![image](<https://example.com/image.png>)](https://example.com)\n'
        '\n'
        '[empty angle destination](<>)\n'
        '\n'
        '[text](<https://example.com> "Title")\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:12'], input=stdin)
    assert result.stdout == (RES / 'angle_link_destinations.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_emphasis_candidates(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of emphasis candidates; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before *x *x *x late* after.\n'
        '\n'
        'Before **x *x ***x **x late** after.\n'
        '\n'
        'Before ***x **x *x ***x late*** after.\n'
        '\n'
        'Before \\*escaped* and *x \\*x *x late* after.\n'
        '\n'
        'Before \\_escaped_ and _x \\_x _x late_ after.\n'
        '\n'
        'Before word_name and _x a_b _x late_ after.\n'
        '\n'
        'Before *\u2003 *x \xa0* late* after.\n'
        '\n'
        'Before _\u2003 _x \xa0_ late_ after.\n'
        '\n'
        'Before *x *x\n'
        '*x late* after.\n'
        '\n'
        'Before *x\n'
        'late* after.\n'
        '\n'
        'Before *x `literal *x *x` *x late* after.\n'
        '\n'
        'Before _x $literal _x \\$ _x$ _x late_ after.\n'
        '\n'
        'Before *x `literal\n'
        '*x` *x late* after.\n'
        '\n'
        'Before _x [raw _word_](target) _x late_ after.\n'
        '\n'
        'Before _x <kbd>_raw_</kbd> _x late_ after.\n'
        '\n'
        'Before _x {key="_raw_"} _x late_ after.\n'
        '\n'
        'Before _x [raw\n'
        '_word_](target) _x late_ after.\n'
        '\n'
        'Before `{{ foo }}` *x *x *x after.\n'
        '\n'
        'Before `code` *x *x *x after.\n'
        '\n'
        'Before *x *x *x after.\n'
        '\n'
        '# _\u2003_ and _outside_\n'
        '\n'
        '# _\xa0_ and _outside_\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'emphasis_candidates.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_empty_link_destinations(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of empty link destinations; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '[empty destination]()\n'
        '\n'
        '![empty image]()\n'
        '\n'
        '[![empty image]()](https://example.com)\n'
        '\n'
        '[![linked image](image.png)]()\n'
        '\n'
        '[empty with title]( "Title")\n'
        '\n'
        '[short]()\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '12'], input=stdin)
    assert result.stdout == (RES / 'empty_link_destinations.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_existing_split_link_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of existing split link wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Alpha beta gamma delta epsilon zeta eta theta iota. See [long link](\n'
        '  https://example.com/pathological/segment-00002-segment-00002-segment-00002\n'
        ') after link with trailing words here.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'existing_split_link_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_heading_emphasis_around_literals(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of heading emphasis around literals; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# _Before `_a_ [x]( url )` after_\n'
        '\n'
        '# _Before $x + _a_ [x]( url )$ after_\n'
        '\n'
        '# _Before **`_a_ [x](< url >)`** after_\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'heading_emphasis_around_literals.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_image_multiline_fig_alt_attribute(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of image multiline fig alt attribute; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '![](assets/generated/chat-heredoc-script.png) { fig-alt="A chat interface where the assistant first uses an inline Rscript bash tool call, then shows a short reasoning summary, then uses\n'
        'another bash tool call to write and run a temporary R script." }\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'image_multiline_fig_alt_attribute.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '40', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_inline_adjacency(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of inline adjacency; the exact stdout, stderr, exit status are compared."""
    stdin = (
        "ASCII possessive: `x`'s value.\n"
        '\n'
        'Curly possessive: `x`’s value.\n'
        '\n'
        "Plural possessive: `users`' value.\n"
        '\n'
        "Non-possessive suffix: `x`'t value.\n"
        '\n'
        "Bare unmatched quote: `x`' value.\n"
        '\n'
        "Unmatched opening quote: '`x` value.\n"
        '\n'
        "ASCII quoted code: '`x`' value.\n"
        '\n'
        'Curly quoted code: ‘`x`’ value.\n'
        '\n'
        "Detached quotes: before ' `x` ' after.\n"
        '\n'
        'Hyphenated suffix: `x`-like value.\n'
        '\n'
        "Emphasis possessive: *x*'s value.\n"
        '\n'
        "Link possessive: [x](https://example.com)'s value.\n"
        '\n'
        "Math possessive: $x$'s value.\n"
        '\n'
        'Adjacent code spans: (`a`,`b`).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '200'], input=stdin)
    assert result.stdout == (RES / 'inline_adjacency.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '200', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_inline_punctuation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of inline punctuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Use `events.jsonl`, cite [^2], then stop.\n'
        '\n'
        "`ir` creates the environment with `reticulate`'s uv-backed environment\n"
        'helper, sets `RETICULATE_PYTHON`, and activates the environment for\n'
        'subprocesses. Declare `reticulate` under `packages` when the R script\n'
        'loads `reticulate`.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '80'], input=stdin)
    assert result.stdout == (RES / 'inline_punctuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_inline_retain_column(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of inline retain column; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Plain text stays byte-for-byte.\n'
        '\n'
        '> Nested `code  span` and [link](target).\n'
        '\n'
        'Changed   gap [link](  target  ) outside.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', '22', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'inline_retain_column.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_inline_retain_sentence(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of inline retain sentence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before  `raw  _text_` after _word_ [link](  target  ). Next sentence.\n'
        '\n'
        '<!-- fmt: wrap=sentence canonical=true scope=file -->\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'inline_retain_sentence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_inline_retain_unwrapped(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of inline retain unwrapped; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Simple body stays exact.\n'
        '\n'
        '> Exact text stays here.\n'
        '\n'
        '> - Plain `literal  spaces` and [link](target).\n'
        '>   More   text [changed](  path  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'inline_retain_unwrapped.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_inline_rich_tokens(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of inline rich tokens; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'See [**Beginner-Friendly Examples**](./examples/README.md) before continuing with the tutorial.\n'
        '\n'
        'Read [`format.POSIXct()`](https://rdrr.io/r/base/strptime.html) before [the *emphasis* section](#emphasis) today.\n'
        '\n'
        'Press   <kbd>Cmd</kbd>   +   <kbd>K</kbd> to open the launcher.\n'
        '\n'
        'Use   ~~old option~~   new option instead.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'inline_rich_tokens.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_closing_delimiter_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of link closing delimiter wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'The goal of {cuda.ml} is to provide a simple and intuitive R interface\n'
        'for [RAPIDS cuML](https://github.com/rapidsai/cuml). RAPIDS cuML is a\n'
        'suite of GPU-accelerated machine learning libraries powered by\n'
        '[CUDA](https://en.wikipedia.org/wiki/CUDA). {cuda.ml} is under active\n'
        'development, and currently implements R interfaces for the algorithms\n'
        'listed below (which is a subset of\n'
        '[algorithms supported by RAPIDS cuML](https://github.com/rapidsai/cuml#supported-algorithms)).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'link_closing_delimiter_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_link_label_markup(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of link label markup; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'See [label [nested]](dest) in this paragraph with enough following text to require wrapping if formatting were allowed.\n'
        '\n'
        'See [**bold** label](dest) in this paragraph with enough following text to require wrapping if formatting were allowed.\n'
        '\n'
        'See ![alt [nested]](img.png) in this paragraph with enough following text to require wrapping if formatting were allowed.\n'
        '\n'
        'See ![**bold** alt](img.png) in this paragraph with enough following text to require wrapping if formatting were allowed.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'link_label_markup.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_links_footnotes_remaining(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of links footnotes remaining; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '[documentation](\n'
        '  https://example.com/docs/very/long/path\n'
        ')\n'
        '\n'
        '[![status](\n'
        '  https://img.shields.io/badge/status-ok-green.svg\n'
        ')](https://example.com/status)\n'
        '\n'
        'Read the [long guide](\n'
        '  https://example.com/guide\n'
        ') before continuing with the tutorial.\n'
        '\n'
        '[^note]: See [`library()` vs `require()`](https://yihui.org/en/2014/07/library-vs-require/) and `$x + y$`.\n'
        '\n'
        '[^long]: First paragraph of the footnote.\n'
        '\n'
        '    Second paragraph with [ **strong label** ](https://example.com).\n'
        '\n'
        '    ```{python}\n'
        '    x=1\n'
        '    print(x)\n'
        '    ```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'links_footnotes_remaining.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_ambiguous_angle_preservation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal ambiguous angle preservation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before `[a](  u  )` < value then `[b](  v  )` after [r](t).\n'
        '\n'
        'Before $![a](  u  )$ < value then $[b](  v  )$ after [r](t).\n'
        '\n'
        'Before < value `[a](  u  )` after [r](t).\n'
        '\n'
        'Before   [before](  a  ) `[x](  u  )` < value after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'literal_ambiguous_angle_preservation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_angle_compatibility(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal angle compatibility; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before <kbd title="> `">[r](  t  )</kbd> then `tail` after [s](  u  ).\n'
        '\n'
        'Before `[a](  u  )` < value then `[b](  v  )` after [r](  t  ).\n'
        '\n'
        'Before < value `[a](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[b](  u  )` after [s](  v  ).\n'
        '\n'
        'Before `<kbd title=">"> [x](  u  )` after [r](  t  ).\n'
        '\n'
        'Before $<kbd title=">"> [x](  u  )$ after [r](  t  ).\n'
        '\n'
        'Before \\< value `[x](  u  )` after [r](  t  ).\n'
        '\n'
        'Before `[x](  u  )` [a](  <target>  ) then `[y](  v  )` after [r](  t  ).\n'
        '\n'
        'Before `[x](  u  )` [a](  target  ){key="<"} then `[y](  v  )` after [r](  t  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'literal_angle_compatibility.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_cr(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal cr; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/markdown_literal_cr.md': (
            '> > Before `first\t\r'
            '> >   second [x]( url )` after _outside_ [real](  target  ).\r'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--diff', '--wrap', 'none', '--canonical', 'tests/fixtures/markdown_literal_cr.md'],
    )
    assert result.stdout == (RES / 'literal_cr.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_literal_crlf(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal crlf; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/markdown_literal_crlf.md': (
            '::: note\r\n'
            '```markdown\r\n'
            'Before `first  \t\r\n'
            '  second\\\r\n'
            'third [x]( url )` after _outside_ [real](  target  ).\r\n'
            ' \t\r\n'
            'Next   paragraph.\t\r\n'
            '```\r\n'
            ':::\r\n'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--diff', '--wrap', 'paragraph', '--canonical', 'tests/fixtures/markdown_literal_crlf.md'],
    )
    assert result.stdout == (RES / 'literal_crlf.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_literal_emphasis_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal emphasis boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# _Before <kbd title="`">raw</kbd> after_ and `code`\n'
        '\n'
        '# _Before [link](`target) after_ and `code`\n'
        '\n'
        'Before <kbd>_raw_</kbd> after _outside_ [real](  target  ).\n'
        '\n'
        'Before <42 `_raw_`> after _outside_ [real](  target  ).\n'
        '\n'
        'Before _with `{{ value }} _raw_` inside_ after [real](  target  ).\n'
        '\n'
        '- Before {{ value }} _raw_ [real](  target  ).\n'
        '\n'
        'Before *```` unmatched `[x](  url  )`* after [r](  t  ).\n'
        '\n'
        'Before `code`` [x](  url  ) tail` after [r](  t  ).\n'
        '\n'
        'Before $$[x](  url  )$$ after _outside_ [r](  t  ).\n'
        '\n'
        '# Before ``unmatched _word_` after _outside_\n'
        '\n'
        '# _Before <kbd>_raw_</kbd> after_\n'
        '\n'
        '# _Before [raw _text_](target) after_\n'
        '\n'
        '# _Before <42 _raw_> after_\n'
        '\n'
        '# _Before {key="_raw_"} after_\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_canonical(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal emphasis canonical; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Lead _Before `_a_ *b* [x](  url  )` after_ [real](  target  ).\n'
        '\n'
        '- __Before $x + __a__ **b** [x]( url )$ after__ [real](  target  ).\n'
        '\n'
        '> _Before ``_a_ ` *b*`` after_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_canonical.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal emphasis escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '# _before \\` literal_ after `code`\n'
        '\n'
        '# _before \\$ literal_ after $math$\n'
        '\n'
        '# _before \\[ literal_ after ](target)\n'
        '\n'
        '# \\`_word_\\` and \\$__word__\\$\n'
        '\n'
        '# $a \\$ _literal_ *stars* [x](  url  )$ after _outside_\n'
        '\n'
        '# _Before $a \\$ _literal_ [x]( url )$ after_\n'
        '\n'
        '# _unclosed `_literal_` then ``unmatched\n'
        '\n'
        '# _before \\`` literal_ after ``code``\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_emphasis_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_emphasis_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal emphasis wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Lead *Before `*a*` after* tail.\n'
        '\n'
        '- Lead _Before $_a_$ after_ tail.\n'
        '\n'
        '> Lead **Before `**a**` after** tail.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '16'], input=stdin)
    assert result.stdout == (RES / 'literal_emphasis_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_eof(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal eof; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/markdown_literal_eof.md': 'Before `code`',
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'tests/fixtures/markdown_literal_eof.md'])
    assert result.stdout == (RES / 'literal_eof.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_literal_hard_break_controls(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal hard break controls; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before <kbd>first   word  \n'
        'second  word</kbd> after _outside_.\n'
        '\n'
        'Before <kbd>`first  \n'
        'second`</kbd> after _outside_.\n'
        '\n'
        'Before <kbd>word</kbd> after.  \n'
        'Next [real](  target  ).\n'
        '\n'
        'Before   `first  \n'
        '  second` after.  \n'
        'Next   line.\t\n'
        '\n'
        'Before <kbd>first\n'
        'second</kbd> after.  \n'
        'Next [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '30', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'literal_hard_break_controls.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_line_endings_check(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal line endings check; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/markdown_literal_mixed_endings_formatted.md': (
            'Before `first  \r\n'
            '  second\t\r'
            'third\\\n'
            'last [x]( url )` after *outside* [real](target).\r\n'
            '\r\n'
            'Before $first  \t\n'
            '  second \\$ [x]( url )\r'
            'third$ after *outside* [real](target).\r\n'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--check', '--wrap', 'paragraph', '--canonical', 'tests/fixtures/markdown_literal_mixed_endings_formatted.md'],
    )
    assert result.stdout == b""
    assert result.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_literal_link_normalization(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal link normalization; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before `[x](  url  )` after [real](  target  ).\n'
        '\n'
        'Before `![x](  image  )` after ![real](  target  ).\n'
        '\n'
        'Before $[x](  url  )$ after [real](  target  ).\n'
        '\n'
        'Before $![x](  image  )$ after ![real](  target  ).\n'
        '\n'
        '[before](  a  ) Before ``[x](  url  ) ` ![y](  image  )`` after [real](  target  ).\n'
        '\n'
        '- Before *with `[x](  url  )` inside* after [real](  target  ).\n'
        '\n'
        '> Before **with $![x](  image  )$ inside** after ![real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == (RES / 'literal_link_normalization.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_link_normalization_narrow(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal link normalization narrow; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Before [b](  s  ). `[x](  long-link-target  )` after [r](  t  ).\n'
        '\n'
        '> Before [b](  s  ). $![x](  long-image-target  )$ after [r](  t  ).\n'
        '\n'
        '_Before_ `[x](  url  )` after [r](  t  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:16', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'literal_link_normalization_narrow.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_link_normalization_none(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal link normalization none; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before `[x](  url  )` after [real](  target  ).\n'
        'Before $![x](  image  )$ after ![real](  target  ).\n'
        '\n'
        'Before \\`[x](  url  )\\` after [real](  target  ).\n'
        'Before \\$![x](  image  )\\$ after ![real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'literal_link_normalization_none.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_link_normalization_unmatched_opener(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal link normalization unmatched opener; the exact stdout, stderr, exit status are compared."""
    stdin = 'Before *```` [raw](  u  ) ``[x](  v  )``* after [r](  t  ).\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph'], input=stdin)
    assert result.stdout == b'Before *```` [raw](u) ``[x](  v  )``* after [r](t).\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_literal_mixed_endings(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of literal mixed endings; the exact stdout, stderr, exit status and files on disk are compared."""
    files = {
        'tests/fixtures/markdown_literal_mixed_endings.md': (
            'Before   `first  \r\n'
            '  second\t\r'
            'third\\\n'
            'last [x]( url )` after _outside_ [real](  target  ).\r\n'
            '\r\n'
            'Before $first  \t\n'
            '  second \\$ [x]( url )\r'
            'third$ after _outside_ [real](  target  ).\r\n'
        ),
    }
    write_tree(workdir, files)
    result = run(
        ['format', '--diff', '--wrap', 'paragraph', '--canonical', 'tests/fixtures/markdown_literal_mixed_endings.md'],
    )
    assert result.stdout == (RES / 'literal_mixed_endings.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_multiline_link_label_preparation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline link label preparation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before [first\n'
        'second](  target  ) after _outside_.\n'
        '\n'
        '- Before [first\n'
        '  second](  target  ) after _outside_.\n'
        '\n'
        '> Before [first\n'
        '> second](  target  ) after _outside_.\n'
        '\n'
        'Before ![first\n'
        'second](  image.png  ) after _outside_.\n'
        '\n'
        '# Existing opaque boundaries\n'
        '\n'
        '- Before <kbd>`first\n'
        '    second`</kbd> after _outside_.\n'
        '\n'
        '- Before <kbd>$first\n'
        '    second$</kbd> after _outside_.\n'
        '\n'
        'Before [label `first\n'
        'second`](  target  ) after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_link_label_preparation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_column(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal column; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before `first  \n'
        '  second [x]( url )` after [real](  target  ).\n'
        '\n'
        '- Before $first\t\n'
        '    second \\$ [x]( url )$ after [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24'], input=stdin)
    assert result.stdout == (RES / 'multiline_literal_column.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_continuation_indentation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal continuation indentation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Term\n'
        '   : Before `first  \n'
        '    second [x]( url )` after _outside_. Next sentence.\n'
        '\n'
        '100. Before $first\\\n'
        '    second [x]( url )$ after _outside_. Next sentence.\n'
        '\n'
        'Term with tabs\n'
        '   : Before `first\t\n'
        '    \tsecond [x]( url )` after _outside_.\n'
        '\n'
        '-  Before `first  \n'
        '    second [x]( url )` after _outside_.\n'
        '\n'
        'Term with a wider authored gap\n'
        ':   Before `first  \n'
        '      second [x]( url )` after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literal_continuation_indentation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_footnotes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal footnotes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '[^note]: Before `first  \n'
        '    second [x]( url )` after _outside_.\n'
        '\n'
        '[^more]: First paragraph.\n'
        '\n'
        '    Before $first\t\n'
        '      second \\$ [x]( url )$ after _outside_.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literal_footnotes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_late_options(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal late options; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before  `first  \n'
        '  second [x]( url )` after _outside_ [real](  target  ). Next sentence.\n'
        '\n'
        '<!-- fmt: wrap=sentence canonical=true scope=file -->\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'multiline_literal_late_options.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_list_escapes(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal list escapes; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Before \\$ escaped then $first  \n'
        '    second \\$ [x]( url )$ after _outside_ [real](  target  ).\n'
        '\n'
        '- _Before \\` escaped_ then `first  \n'
        '    second [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '- _Before \\`` escaped_ then `first\n'
        '    second` after _outside_.\n'
        '\n'
        '# Existing tokenizer fallback\n'
        '\n'
        '- Before \\` escaped then `first\n'
        '    second` after _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literal_list_escapes.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_list_openers(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal list openers; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Before\n'
        '    `first  \n'
        '    second [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '- Before\n'
        '    $first  \n'
        '    second \\$ [x]( url )$ after _outside_. Next sentence.\n'
        '\n'
        '# Existing indentation boundaries\n'
        '\n'
        '- Before\n'
        '    still prose after _outside_ [real](  target  ).\n'
        '\n'
        '100. Before\n'
        '    `first\n'
        '    second` after _outside_.\n'
        '\n'
        '# Existing split-link continuation\n'
        '\n'
        '- Before [label](target\n'
        '    ) after _outside_ [real](  target  ).\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '24', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'multiline_literal_list_openers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_nested(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal nested; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '::: note\n'
        '```markdown\n'
        'Before `first  \t\n'
        '  second\\\n'
        'third [x]( url )` after _outside_.\n'
        ' \t\n'
        'Next   paragraph.\t\n'
        '```\n'
        ':::\n'
        '\n'
        '> ```markdown\n'
        '> Before `first  \n'
        '>   second [x]( url )` after _outside_.\n'
        '> ```\n'
        '\n'
        '- Example\n'
        '\n'
        '  ```markdown\n'
        '  Before `first  \n'
        '    second [x]( url )` after _outside_.\n'
        '  ```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'paragraph', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literal_nested.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_none(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal none; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before  $first  \n'
        '  second \\$ [x]( url )$ after _outside_ [real](  target  ).\n'
        '\n'
        '> > Before `first\t\n'
        '> >   second [x]( url )` after _outside_.\n'
        '\n'
        'Before `{{ render_item() }}` after [real](  target  ).\n'
        '\n'
        'Before `{{\n'
        '  render_item()\n'
        '}}` after _outside_ [real](  target  ).\n'
        '\n'
        '> > Before <tag> value.\n'
        '> > Next [r](  t  ) _outside_.\n'
        '\n'
        '> > Before [r](  t  ) _outside_.\n'
        '> > > Next [r](  t  ) _outside_.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none', '--canonical'], input=stdin)
    assert result.stdout == (RES / 'multiline_literal_none.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_multiline_literal_whitespace(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of multiline literal whitespace; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Before `first  \n'
        '  second [x]( url )` after _outside_. Next sentence.\n'
        '\n'
        '- Before `first  \n'
        '    second [x]( url )` after _outside_. Next sentence.\n'
        '\n'
        '> Before $first  \n'
        '>   second \\$ [x]( url )$ after _outside_. Next sentence.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:80', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'multiline_literal_whitespace.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_nested_image_link_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of nested image link wrap; the exact stdout, stderr, exit status are compared."""
    stdin = 'See [![diagram alt](images/really-really-really-long-file-name-for-the-diagram.png)](https://example.com/really/really/really/really/long/path) for details.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'nested_image_link_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_parenthesized_code_spans(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of parenthesized code spans; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '`ir` focuses on two workflows:\n'
        '\n'
        '- running or rendering self-describing scripts and\n'
        '  documents (`ir run`, `ir render`)\n'
        '- running or installing command-line tools distributed through R\n'
        '  packages (`rx`, `ir tool install`)\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'parenthesized_code_spans.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_raw_multiline_html_img(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of raw multiline html img; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '<img alt="A chat interface where a user asks an agent to explore a\n'
        'dataset and build a first model. The agent responds by running several\n'
        'bash tool calls with Rscript."\n'
        'src="mcp-repl-useR-lightning-assets/chat-scenario.png" style="width:\n'
        '100%; fig-align=\'center\'"\n'
        '>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'raw_multiline_html_img.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '40', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_raw_single_line_html_img(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of raw single line html img; the exact stdout, stderr, exit status are compared."""
    stdin = '<img src="man/figures/README-umap-example-1.png" alt="A two-dimensional UMAP embedding of MNIST digits colored by digit label." width="100%" />\n'
    result = run(['format', '--stdin-file-path', 'input.md'], input=stdin)
    assert result.stdout == b'<img src="man/figures/README-umap-example-1.png" alt="A two-dimensional UMAP embedding of MNIST digits colored by digit label." width="100%" />\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_short_link_line_boundaries_column(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of short link line boundaries column; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Short [linked words](https://example.org/guide) finish. Another sentence follows.\n'
        '\n'
        '> - Nested [link](https://example.org/nested) and words that should cross a line boundary.\\\n'
        '>   Follow-up text keeps its container prefix.\n'
        '\n'
        '<!-- fmt: wrap=sentence:36 scope=next -->\n'
        'Late policy changes this paragraph with [a link](https://example.org/late) and a final sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '48'], input=stdin)
    assert result.stdout == (RES / 'short_link_line_boundaries_column.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_short_link_line_boundaries_sentence(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of short link line boundaries sentence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Short [linked words](https://example.org/guide) finish. Another sentence follows.\n'
        '\n'
        '> - Nested [link](https://example.org/nested) and words that should cross a line boundary.\\\n'
        '>   Follow-up text keeps its container prefix.\n'
        '\n'
        '<!-- fmt: wrap=sentence:36 scope=next -->\n'
        'Late policy changes this paragraph with [a link](https://example.org/late) and a final sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence:36'], input=stdin)
    assert result.stdout == (RES / 'short_link_line_boundaries_sentence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_spaced_punctuation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of spaced punctuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'The notation \\< , \\> denotes the dot product.\n'
        '\n'
        'Deliberate punctuation gaps: ( , ) and [ ; ].\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '80'], input=stdin)
    assert result.stdout == (RES / 'spaced_punctuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_titled_link_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown inline handling of titled link wrap; the exact stdout, stderr, exit status are compared."""
    stdin = 'See [the documentation](https://example.com/really/really/really/really/long/path "A helpful title") for details.\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'titled_link_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
