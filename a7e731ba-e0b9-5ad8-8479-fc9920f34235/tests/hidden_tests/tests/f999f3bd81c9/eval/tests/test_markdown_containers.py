"""Markdown containers transcripts.

Converted from the project's CLI transcript cases: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_blockquote_rich_children(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of blockquote rich children; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '> | Term | Meaning |\n'
        '> |---|---|\n'
        '> | ML | Machine learning |\n'
        '\n'
        '> ```bash\n'
        '> quarto preview\n'
        '> ```\n'
        '\n'
        '> - first item\n'
        '> - second item\n'
        '>\n'
        '> Final sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'blockquote_rich_children.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_container_inline_html(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of container inline html; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- First. Second.\n'
        '  <span>\n'
        '  Third. Fourth.\n'
        '\n'
        '> First. Second.\n'
        '> <img src="x">\n'
        '> Third. Fourth.\n'
        '\n'
        '- First. Second.\n'
        '  </span>\n'
        '  Third. Fourth.\n'
        '\n'
        '- <span>\n'
        '  Alpha. Beta.\n'
        '\n'
        '> <span>\n'
        '> Alpha. Beta.\n'
        '\n'
        '- First. Second.\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
        '\n'
        '> First. Second.\n'
        '> <pre>\n'
        '> alpha    beta\n'
        '> </pre>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'container_inline_html.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_container_literal_block_markers(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of container literal block markers; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- First. Second. `code\n'
        '  # heading\n'
        '  end`\n'
        '\n'
        '> First. Second. `code\n'
        '> Title\n'
        '> ===\n'
        '> end`\n'
        '\n'
        '- First. Second. `code\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
        '  end`\n'
        '\n'
        '> First. Second. `code\n'
        '> <pre>\n'
        '> alpha    beta\n'
        '> </pre>\n'
        '> end`\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'container_literal_block_markers.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_container_raw_html_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of container raw html boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- First. Second.\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
        '\n'
        '> First. Second.\n'
        '> <pre>\n'
        '> alpha    beta\n'
        '> </pre>\n'
        '\n'
        'Outside. Another sentence.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'container_raw_html_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_definition_tab_continuations(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of definition tab continuations; the exact stdout, stderr, exit status are compared."""
    stdin = (
        'Term\n'
        ': Before   prose.\n'
        '   \tAfter   _outside_ [real](  target  ).\n'
        '\n'
        '# Code\n'
        '\n'
        'Code\n'
        '   : Before `first  \n'
        '   \t\tsecond [x]( url )` after _outside_ [real](  target  ).\n'
        '\n'
        '# Math\n'
        '\n'
        'Math\n'
        '   : Before $first  \n'
        '\t   second \\$ [x]( url )$ after _outside_. Next sentence.\n'
        '\n'
        '# Ineligible continuation\n'
        '\n'
        'Short\n'
        ': Before   prose.\n'
        '  \tAfter   _outside_ [real](  target  ).\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--canonical'],
        input=stdin,
    )
    assert result.stdout == (RES / 'definition_tab_continuations.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_div_shortcode_math(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of div shortcode math; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '::: {.callout-tip}\n'
        '## Learn more\n'
        '{{< meta title >}}\n'
        '\n'
        '```{=html}\n'
        '<div class="raw">HTML</div>\n'
        '```\n'
        '\n'
        'This paragraph is intentionally long enough to be considered for wrapping by the markdown formatter inside a fenced div.\n'
        ':::\n'
        '\n'
        ':::: columns\n'
        '::: {.column width="50%"}\n'
        '| a | b |\n'
        '|---|---|\n'
        '| 1 | 2 |\n'
        ':::\n'
        '::: {.column width="50%"}\n'
        'This paragraph is intentionally long enough to be considered for wrapping by the markdown formatter inside a nested div.\n'
        ':::\n'
        '::::\n'
        '\n'
        'This paragraph is intentionally long enough to be considered for wrapping before an opaque shortcode block.\n'
        '\n'
        '{{< meta title >}}\n'
        '\n'
        'This paragraph is intentionally long enough to be considered for wrapping after an opaque shortcode block.\n'
        '\n'
        '{{% notice %}}\n'
        'Do   not format this body.\n'
        '{{% /notice %}}\n'
        '\n'
        '$$\n'
        '\\begin{aligned}\n'
        'a^2 + b^2 &= c^2\n'
        '\\end{aligned}\n'
        '$$\n'
        '\n'
        '\\[\n'
        'E = mc^2\n'
        '\\]\n'
        '\n'
        '\\begin{equation}\n'
        'x = y\n'
        '\\end{equation}\n'
        '\n'
        '- Use the identity:\n'
        '\n'
        '  $$\n'
        '  x^2 + 2x + 1 = (x + 1)^2\n'
        '  $$\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '40'], input=stdin)
    assert result.stdout == (RES / 'div_shortcode_math.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_child_headings(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list child headings; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '  - One.\n'
        '- Two.\n'
        '\n'
        '  Title\n'
        '  ===\n'
        '\n'
        '  - One.\n'
        '- Two.\n'
        '\n'
        '  Title\n'
        '  ---\n'
        '\n'
        '  - One.\n'
        '- Two.\n'
        '\n'
        '  # Title\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_child_headings.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_child_raw_blocks(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list child raw blocks; the exact stdout, stderr, exit status are compared."""
    stdin = (
        ' - First.\n'
        '- Second.\n'
        ' Heading\n'
        ' ===\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' Heading\n'
        ' ---\n'
        '\n'
        '-    First.\n'
        '    Prose.\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' After.\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        '  ~~~text\n'
        '  alpha    beta\n'
        '  ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
        '\n'
        ' - First.\n'
        '- `Second.\n'
        ' ~~~text\n'
        ' alpha    beta\n'
        ' end`\n'
        '\n'
        ' - First.\n'
        '- `Second.\n'
        ' <pre>\n'
        ' alpha    beta\n'
        ' end`\n'
        '\n'
        ' - First.\n'
        '- [Second](\n'
        ' <pre>\n'
        ' )\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_child_raw_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_empty_item_pandoc_continuation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list empty item pandoc continuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-\n'
        '\n'
        ' First.\n'
        '\n'
        '-\n'
        '\n'
        ' - Second.\n'
        '\n'
        '  Continuation first. Continuation second.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.qmd', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_empty_item_pandoc_continuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.qmd').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.qmd'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_following_raw_blocks(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list following raw blocks; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-   First.\n'
        '  - Second.\n'
        ' ~~~text\n'
        'alpha    beta\n'
        ' ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' ~~~text\n'
        'alpha    beta\n'
        ' ~~~\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' ```text\n'
        'alpha    beta\n'
        ' ```\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' <pre>\n'
        'alpha    beta\n'
        ' </pre>\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' <!--\n'
        'alpha    beta\n'
        ' -->\n'
        '\n'
        ' - First.\n'
        '- Second.\n'
        ' $$\n'
        'alpha    beta\n'
        ' $$\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_following_raw_blocks.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_grid_table_child(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list grid table child; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '1.  Intro text.\n'
        '\n'
        '    +------+------+\n'
        '    | A    | B    |\n'
        '    +======+======+\n'
        '    | x    | y    |\n'
        '    +------+------+\n'
        '\n'
        '    After table.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--skip-embedded-formatters'], input=stdin)
    assert result.stdout == (RES / 'list_grid_table_child.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_heading_literal_controls(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list heading literal controls; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item.\n'
        '  ~~~yaml\n'
        '  # comment\n'
        '  x: [1,2]\n'
        '  ~~~\n'
        '\n'
        '- Item.\n'
        '  ~~~markdown\n'
        '  Title\n'
        '  ===\n'
        '  ~~~\n'
        '\n'
        '- First. Second. `code\n'
        '  # heading\n'
        '  end`\n'
        '\n'
        '- First. Second. `code\n'
        '  Title\n'
        '  ===\n'
        '  end`\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_heading_literal_controls.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_mixed_region_boundary(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list mixed region boundary; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item.\n'
        ' ~~~text\n'
        ' `\n'
        ' ~~~\n'
        '- `First.    Second.\n'
        ' <pre>\n'
        ' alpha    beta\n'
        ' end`\n'
        '\n'
        'Outside first. Outside second.\n'
        '\n'
        '- Item.\n'
        ' ~~~text\n'
        ' alpha    beta\n'
        ' ~~~\n'
        '- Next.\n'
        ' <pre>\n'
        ' gamma    delta\n'
        ' </pre>\n'
        'Outside third. Outside fourth.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_mixed_region_boundary.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_paragraph_after_fence(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list paragraph after fence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item. Second\n'
        '  wrapped.\n'
        '\n'
        '  ```text\n'
        '  keep  code\n'
        '  ```\n'
        '\n'
        '  After. Second\n'
        '  paragraph.\n'
        '\n'
        '- Sibling. Second\n'
        '  wrapped.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_paragraph_after_fence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_rich_children(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list rich children; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Install dependencies:\n'
        '\n'
        '  ```bash\n'
        '  npm install\n'
        '  ```\n'
        '\n'
        '- Run the app.\n'
        '\n'
        '1. Load data.\n'
        '1. Build a table:\n'
        '\n'
        '   | a | b |\n'
        '   |---|---|\n'
        '   | 1 | 2 |\n'
        '\n'
        '- Tip:\n'
        '  > Quote inside a list.\n'
        '- Continue.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'list_rich_children.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_shifted_sibling_lazy_continuation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list shifted sibling lazy continuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-   First.\n'
        '  - Second.\n'
        ' After.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_shifted_sibling_lazy_continuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_unicode_continuation(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list unicode continuation; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item.\n'
        ' \xa0Continuation line.\n'
        '\n'
        '# Separate paragraph\n'
        '\n'
        '- Item.\n'
        '\n'
        ' \xa0Continuation paragraph.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_unicode_continuation.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', '--skip-embedded-formatters', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_list_wide_marker_child_code_boundary(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list wide marker child code boundary; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '*   Bullet outer.\n'
        '\n'
        '      - Nested. More\n'
        '        words.\n'
        '\n'
        'Outside bullet. Second.\n'
        '\n'
        '1.  Ordered outer.\n'
        '\n'
        '       - Nested. More\n'
        '         words.\n'
        '\n'
        'Outside ordered. Second.\n'
        '\n'
        '*   Fence outer.\n'
        '\n'
        '      ```text\n'
        '      keep  code\n'
        '      ```\n'
        '\n'
        '    After. Second.\n'
        '\n'
        'Outside fence. Second.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_wide_marker_child_code_boundary.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_wide_marker_div_blank_line(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list wide marker div blank line; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '1.  Intro text. Second\n'
        '    sentence.\n'
        '\n'
        '    ::: {.note}\n'
        '    Inside div.\n'
        '\n'
        '    After blank. Second\n'
        '    sentence.\n'
        '    :::\n'
        '\n'
        '- Bullet. Second\n'
        '  sentence.\n'
        '\n'
        '  ::: {.outer}\n'
        '  Outer. Second\n'
        '  sentence.\n'
        '\n'
        '  ::: {.inner}\n'
        '  Inner.\n'
        '\n'
        '  Inner after blank. Second\n'
        '  sentence.\n'
        '  :::\n'
        '\n'
        '  Outer after blank.\n'
        '  :::\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_wide_marker_div_blank_line.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_wide_marker_nested_wrap(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list wide marker nested wrap; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '*   Outer.\n'
        '\n'
        '    - Nested. Second\n'
        '      wrapped.\n'
        '\n'
        '*   Other. Second\n'
        '    wrapped.\n'
        '\n'
        '1.  Numbered.\n'
        '\n'
        '    - Nested. Second\n'
        '      wrapped.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'list_wide_marker_nested_wrap.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_list_wide_marker_raw_boundary(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of list wide marker raw boundary; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '-   Item.\n'
        '  ~~~text\n'
        '  code\n'
        '  ~~~\n'
        '\n'
        '-   Item.\n'
        '  <pre>\n'
        '  alpha    beta\n'
        '  </pre>\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'list_wide_marker_raw_boundary.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_nested_list_continuation_boundaries(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of nested list continuation boundaries; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Parent.\n'
        '\n'
        '  - Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '- Next.\n'
        '\n'
        '- Parent.\n'
        '  - Child one.\n'
        '\n'
        '  - Child two.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '- Next.\n'
        '\n'
        '- Parent.\n'
        '  - Child.\n'
        '    - Grandchild.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '\n'
        'Outside first. Outside second.\n'
        '\n'
        '- Parent.\n'
        '  - [ ] Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '\n'
        '- [ ] Parent.\n'
        '  - [ ] Child.\n'
        '\n'
        '      Outer first. Outer second.\n'
        '\n'
        '  - Indented first.\n'
        '- Parent.\n'
        '  - Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
        '\n'
        '- First.\n'
        ' - Second.\n'
        '\n'
        '  Outside first. Outside second.\n'
        '\n'
        '-\n'
        ' - Second.\n'
        '\n'
        '  Outside first. Outside second.\n'
        '\n'
        '- First.\n'
        '  - Child.\n'
        '10. Second.\n'
        '\n'
        '  Outside first. Outside second.\n'
        '\n'
        '10. First.\n'
        '- Second.\n'
        '  - Child.\n'
        '\n'
        '  Outer first. Outer second.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'nested_list_continuation_boundaries.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_nested_list_continuation_column(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of nested list continuation column; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item with a nested list:\n'
        '  - nested one\n'
        '  - nested two\n'
        '\n'
        '  Paragraph that continues the outer item.\n'
        '- Next item.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', '72'], input=stdin)
    assert result.stdout == (RES / 'nested_list_continuation_column.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', '72', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_nested_list_continuation_none(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of nested list continuation none; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item with a nested list:\n'
        '  - nested one\n'
        '  - nested two\n'
        '\n'
        '  Paragraph that continues the outer item.\n'
        '- Next item.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'none'], input=stdin)
    assert result.stdout == (RES / 'nested_list_continuation_none.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'none', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_nested_list_continuation_sentence(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of nested list continuation sentence; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- Item with a nested list:\n'
        '  - nested one\n'
        '  - nested two\n'
        '\n'
        '  Paragraph that continues the outer item.\n'
        '- Next item.\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence'], input=stdin)
    assert result.stdout == (RES / 'nested_list_continuation_sentence.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--wrap', 'sentence', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_task_list_indented_code_after_blank(run, workdir):
    """CATCHES: implementations that differ from the reference in Markdown container (list/blockquote/div/definition) formatting of task list indented code after blank; the exact stdout, stderr, exit status are compared."""
    stdin = (
        '- [ ] Item.\n'
        '\n'
        '      ```\n'
        '      code\n'
        '      ```\n'
        '\n'
        '      First. Second.\n'
        '\n'
        'Outside. Second.\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--wrap', 'sentence', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'task_list_indented_code_after_blank.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
