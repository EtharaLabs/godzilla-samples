"""Wrapping must never move a token to the start of a line where it would begin a new
Markdown block (list markers, headings, quotes, table pipes, thematic breaks, fences,
setext underlines, footnote definitions, raw HTML, ordered markers like `1986.`). The
reference repairs such breaks (escaping or re-flowing); a reimplementation must make the
same choices at every width, in paragraphs, list items and blockquotes.
"""

import pytest

from conftest import format_both_ways

TOKENS = ['-', '+', '*', '1.', '2)', '#', '##', '>', '|', ':', '***', '---', '===', '~~~', '```', '<div>', '[^1]:', '- [ ]', '\\*', '**x**', '`code`', '$x$', '{{ t }}', '<!-- c -->', '1986.', '*a*', '__b__']

WIDTHS = ["8", "12", "sentence:12"]

CONTAINERS = {"paragraph": "", "list_item": "- ", "blockquote": "> "}


@pytest.mark.parametrize("container", sorted(CONTAINERS))
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("index", range(len(TOKENS)))
def test_wrap_never_starts_block(index, width, container, run, workdir, golden):
    """CATCHES: wrapping that leaves a block-starting token (`-`, `1.`, `#`, `>`, `|`,
    `---`, fences, `[^1]:` ...) at the start of a continuation line, or repairs it
    differently (escape vs. re-flow) from the reference."""
    token = TOKENS[index]
    text = CONTAINERS[container] + f"Short {token} words {token} here {token} and {token} there {token} end.\n"
    observed = format_both_ways(run, workdir, "doc.md", text, "--wrap", width)
    assert observed == golden(f"token{index:02d}__{width.replace(':', '_')}__{container}")
