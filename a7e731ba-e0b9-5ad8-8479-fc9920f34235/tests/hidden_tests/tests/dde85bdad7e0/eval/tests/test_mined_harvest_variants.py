"""Harvested inputs under third-generation mutations and options (doubled spaces,
blank-line insertion, per-line comments, CRLF+tabs, nesting in lists, quotes, Markdown
scalars or front matter; indent widths 3/4, 10-column widths, `sentence:30`), kept
only where they reach Markdown layout and block-scalar branches nothing else reaches.

Each case is formatted through stdin and through path-mode `--check`, and both
complete outcomes must match the reference.
"""

import pytest

from conftest import format_both_ways, outcome

CASES = {
    'md_000': ('format', 'in.md', ['--wrap', '10'], 'Literal \\* star \\* here.\n\nOne sentence. * two words. * three words. Last sentence.\n\nLiteral \\* \\(x * y\\)\n\nLiteral \\* $x * y$\n\nLiteral \\* $$x * y$$\n\nLiteral \\* *x*.\n\nMath 2 * 3. Opening sentence. * value.\n'),
    'md_001': ('format', 'in.md', [], '#  Title  ###  {#id}\n'),
    'md_002': ('format', 'in.md', ['--wrap', '10'], '# _Before <kbd title="`">raw</kbd> after_ and `code`\n\n# _Before [link](`target) after_ and `code`\n\nBefore <kbd>_raw_</kbd> after _outside_ [real](  target  ).\n\nBefore <42 `_raw_`> after _outside_ [real](  target  ).\n\nBefore _with `{{ value }} _raw_` inside_ after [real](  target  ).\n\n- Before {{ value }} _raw_ [real](  target  ).\n\nBefore *```` unmatched `[x](  url  )`* after [r](  t  ).\n\nBefore `code`` [x](  url  ) tail` after [r](  t  ).\n\nBefore $$[x](  url  )$$ after _outside_ [r](  t  ).\n\n# Before ``unmatched _word_` after _outside_\n\n# _Before <kbd>_raw_</kbd> after_\n\n# _Before [raw _text_](target) after_\n\n# _Before <42 _raw_> after_\n\n# _Before {key="_raw_"} after_\n'),
    'md_003': ('format', 'in.md', ['--wrap', 'sentence:30'], 'A [ ![ alt   text ](img.png)   label ](dest) after.\n'),
    'md_004': ('format', 'in.md', ['--wrap', '10'], 'One sentence. * two words. * three words. Last sentence.\n\nCode `*`. Opening sentence. * More prose.\n\nHTML <span title="*">x</span>. Opening sentence. * value.\n\nLiteral \\*. Opening sentence. * value.\n\nLiteral \\* here. Opening sentence. * value.\n\nEscaped \\\\*. Opening sentence. * value.\n\nMath \\(x \\* y\\). Opening sentence. * value.\n\nComment <!-- * -->. Opening sentence. * value.\n\nEm *x*. Opening sentence. * value.\n\nStrong **x**. Opening sentence. * value.\n\nNested **x *y* z**. Opening sentence. * value.\n\nMath *$x * y$*. Opening sentence. * value.\n\nUnmatched *x. Opening sentence. * value.\n\nEm *unmatched \\(*. Opening sentence. (b) value.\n\nHTML *<!-- \\> -->*. Opening sentence. * value.\n\nEm *x * y*. Opening sentence. * value.\n\nMath 2 * 3. Opening sentence. * value.\n'),
    'yaml_005': ('format', 'in.yaml', ['--indent-width', '3', '--compact'], 'text: |-\n  \n   *** caught segfault ***\n  address 0x0\n'),
}



@pytest.mark.parametrize("name", sorted(CASES))
def test_harvest_variant_input(name, run, workdir, golden):
    """CATCHES: divergent handling of unusual-but-valid inputs: different quoting, spacing,
    preservation decisions, directive errors, verification failures, or check-mode summaries,
    since both the stdin output and the path-mode --check outcome are compared exactly."""
    kind, path, flags, text = CASES[name]
    if kind == "format":
        observed = format_both_ways(run, workdir, path, text, *flags)
    else:
        observed = {"stdin": outcome(run(["to-yaml", "--stdin-file-path", path, *flags], input=text))}
    assert observed == golden(name)
