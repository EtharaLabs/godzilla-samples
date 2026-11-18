"""Core edge cases: blank inputs per file type, every --wrap form, invalid option
values, YAML width/indent options, Unicode display width, very large inputs,
extension case-insensitivity and mixed multi-file runs.

Expected values were recorded from the reference binary.
"""

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)

BLANK_CASES = [
    ('in.md', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.md', b'\n', b'\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.md', b'\n\n\n', b'\n\n\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.md', b'   \n', b'\n', '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n', 1),
    ('in.md', b'\r\n', b'\r\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.md', b'\r', b'\r', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.md', b' ', b'\n', '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n', 1),
    ('in.md', b'\t\n', b'\n', '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n', 1),
    ('in.qmd', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.qmd', b'   \n', b'\n', '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n', 1),
    ('in.Rmd', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.Rmd', b'   \n', b'\n', '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n', 1),
    ('in.rmd', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.rmd', b'   \n', b'\n', '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n', 1),
    ('in.yaml', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b'\n', b'\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b'\n\n\n', b'\n\n\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b'   \n', b'   \n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b'\r\n', b'\r\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b'\r', b'\r', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b' ', b' ', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yaml', b'\t\n', b'\t\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yml', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.yml', b'   \n', b'   \n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'\n', b'\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'\n\n\n', b'\n\n\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'   \n', b'   \n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'\r\n', b'\r\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'\r', b'\r', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b' ', b' ', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.py', b'\t\n', b'\t\n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.R', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.R', b'   \n', b'   \n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.r', b'', b'', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
    ('in.r', b'   \n', b'   \n', '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n', 0),
]


@pytest.mark.parametrize("name, data, expected, check_stderr, check_status", BLANK_CASES)
def test_blank_and_whitespace_only_inputs(run, workdir, name, data, expected, check_stderr, check_status):
    """CATCHES: implementations that crash, add or drop newlines, or treat whitespace-only documents
    inconsistently: Markdown normalises whitespace-only lines to bare newlines while YAML and Python/R
    sources keep the bytes; empty input stays empty; and `--check` on the same bytes must agree."""
    result = run(["format", "--stdin-file-path", name], input=data)
    assert result.stdout == expected
    assert result.stderr == b""
    assert result.returncode == 0
    (workdir / name).write_bytes(data)
    checked = run(["format", "--check", name])
    assert checked.stdout == b""
    assert checked.stderr.decode() == check_stderr
    assert checked.returncode == check_status
    assert read_tree(workdir) == {name: data}


PARAGRAPH = '#   Wrap   forms   #\n\nAlpha   beta gamma. Delta epsilon zeta eta theta iota kappa lambda! Mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega? End.\n'

WRAP_CASES = [
    ('1', b'# Wrap forms\n\nAlpha\nbeta\ngamma.\nDelta\nepsilon\nzeta\neta\ntheta\niota\nkappa\nlambda!\nMu\nnu\nxi\nomicron\npi\nrho\nsigma\ntau\nupsilon\nphi\nchi\npsi\nomega?\nEnd.\n'),
    ('5', b'# Wrap forms\n\nAlpha\nbeta\ngamma.\nDelta\nepsilon\nzeta\neta\ntheta\niota\nkappa\nlambda!\nMu nu\nxi\nomicron\npi\nrho\nsigma\ntau\nupsilon\nphi\nchi\npsi\nomega?\nEnd.\n'),
    ('20', b'# Wrap forms\n\nAlpha beta gamma.\nDelta epsilon zeta\neta theta iota kappa\nlambda! Mu nu xi\nomicron pi rho sigma\ntau upsilon phi chi\npsi omega? End.\n'),
    ('40', b'# Wrap forms\n\nAlpha beta gamma. Delta epsilon zeta eta\ntheta iota kappa lambda! Mu nu xi\nomicron pi rho sigma tau upsilon phi chi\npsi omega? End.\n'),
    ('72', b'# Wrap forms\n\nAlpha beta gamma. Delta epsilon zeta eta theta iota kappa lambda! Mu nu\nxi omicron pi rho sigma tau upsilon phi chi psi omega? End.\n'),
    ('10000', b'# Wrap forms\n\nAlpha beta gamma. Delta epsilon zeta eta theta iota kappa lambda! Mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega? End.\n'),
    ('none', b'# Wrap forms\n\nAlpha   beta gamma. Delta epsilon zeta eta theta iota kappa lambda! Mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega? End.\n'),
    ('paragraph', b'# Wrap forms\n\nAlpha beta gamma. Delta epsilon zeta eta theta iota kappa lambda! Mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega? End.\n'),
    ('sentence', b'# Wrap forms\n\nAlpha beta gamma.\nDelta epsilon zeta eta theta iota kappa lambda!\nMu nu xi omicron pi rho sigma tau upsilon phi chi psi omega?\nEnd.\n'),
    ('sentence:1', b'# Wrap forms\n\nAlpha\nbeta\ngamma.\nDelta\nepsilon\nzeta\neta\ntheta\niota\nkappa\nlambda!\nMu\nnu\nxi\nomicron\npi\nrho\nsigma\ntau\nupsilon\nphi\nchi\npsi\nomega?\nEnd.\n'),
    ('sentence:30', b'# Wrap forms\n\nAlpha beta gamma.\nDelta epsilon zeta eta theta\niota kappa lambda!\nMu nu xi omicron pi rho sigma\ntau upsilon phi chi psi omega?\nEnd.\n'),
]


@pytest.mark.parametrize("wrap, expected", WRAP_CASES)
def test_every_wrap_form_on_one_paragraph(run, wrap, expected):
    """CATCHES: wrong handling of any documented --wrap value: column widths (including a width smaller than
    every word and a huge width), `none` and `paragraph` joining lines, `sentence` breaking only at sentence
    ends, and `sentence:<n>` combining both; collapsing of repeated spaces is also pinned."""
    result = run(["format", "--stdin-file-path", "p.md", "--wrap", wrap], input=PARAGRAPH)
    assert result.stdout == expected
    assert result.stderr == b""
    assert result.returncode == 0


INVALID_VALUES = [
    ('--wrap', '0', 'a.md', "error: invalid value '0' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', 'sentence:0', 'a.md', "error: invalid value 'sentence:0' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', 'abc', 'a.md', "error: invalid value 'abc' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', '', 'a.md', "error: invalid value '' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', 'sentence:', 'a.md', "error: invalid value 'sentence:' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', '72.5', 'a.md', "error: invalid value '72.5' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', ' 72', 'a.md', "error: invalid value ' 72' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', 'Sentence', 'a.md', "error: invalid value 'Sentence' for '--wrap <WRAP>': wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n\nFor more information, try '--help'.\n"),
    ('--wrap', '-1', 'a.md', "error: unexpected argument '-1' found\n\n  tip: to pass '-1' as a value, use '-- -1'\n\nUsage: executable format [OPTIONS] [PATHS]...\n\nFor more information, try '--help'.\n"),
    ('--line-width', '0', 'a.yaml', "error: invalid value '0' for '--line-width <LINE_WIDTH>': value must be greater than 0\n\nFor more information, try '--help'.\n"),
    ('--line-width', 'x', 'a.yaml', "error: invalid value 'x' for '--line-width <LINE_WIDTH>': invalid positive integer: invalid digit found in string\n\nFor more information, try '--help'.\n"),
    ('--line-width', '99999999999999999999999', 'a.yaml', "error: invalid value '99999999999999999999999' for '--line-width <LINE_WIDTH>': invalid positive integer: number too large to fit in target type\n\nFor more information, try '--help'.\n"),
    ('--prose-width', '0', 'a.yaml', "error: invalid value '0' for '--prose-width <PROSE_WIDTH>': value must be greater than 0\n\nFor more information, try '--help'.\n"),
    ('--prose-width', '1.5', 'a.yaml', "error: invalid value '1.5' for '--prose-width <PROSE_WIDTH>': invalid positive integer: invalid digit found in string\n\nFor more information, try '--help'.\n"),
    ('--indent-width', '0', 'a.yaml', "error: invalid value '0' for '--indent-width <INDENT_WIDTH>': value must be greater than 0\n\nFor more information, try '--help'.\n"),
    ('--indent-width', 'two', 'a.yaml', "error: invalid value 'two' for '--indent-width <INDENT_WIDTH>': invalid positive integer: invalid digit found in string\n\nFor more information, try '--help'.\n"),
    ('--table-widths', 'FIT', 'a.md', "error: invalid value 'FIT' for '--table-widths <TABLE_WIDTHS>': table-widths must be fit or preserve\n\nFor more information, try '--help'.\n"),
    ('--table-widths', '', 'a.md', "error: invalid value '' for '--table-widths <TABLE_WIDTHS>': table-widths must be fit or preserve\n\nFor more information, try '--help'.\n"),
    ('--table-widths', 'auto', 'a.md', "error: invalid value 'auto' for '--table-widths <TABLE_WIDTHS>': table-widths must be fit or preserve\n\nFor more information, try '--help'.\n"),
]


@pytest.mark.parametrize("option, value, path, stderr", INVALID_VALUES)
def test_invalid_option_values_are_usage_errors(run, option, value, path, stderr):
    """CATCHES: accepting zero, negative, fractional, padded, empty, misspelled or overflowing values for the
    width/indent/wrap/table-width options, or reporting them with a different message or an exit status other
    than 2 (usage error) before reading stdin."""
    result = run(["format", "--stdin-file-path", path, option, value], input="x: 1\n")
    assert result.stdout == b""
    assert result.stderr.decode() == stderr
    assert result.returncode == 2


YAML_DOC = (
    'root:\n'
    "    key: {a: 1, b: [x, y, z], c: {d: 'nested value'}}\n"
    '    list:\n'
    '    - one\n'
    '    -   two: 2\n'
    '        three: [3, 33]\n'
    '    long: "The quick brown fox jumps over the lazy dog while the five boxing wizards jump quickly."\n'
    'flow: [alpha, beta, gamma, delta, epsilon, zeta, eta, theta, iota, kappa, lambda]\n'
)

YAML_OPTION_CASES = [
    ([], 'yaml_options_default.golden'),
    (['--indent-width', '1'], 'yaml_options_indent_width_1.golden'),
    (['--indent-width', '3'], 'yaml_options_indent_width_3.golden'),
    (['--indent-width', '4'], 'yaml_options_indent_width_4.golden'),
    (['--indent-width', '8'], 'yaml_options_indent_width_8.golden'),
    (['--line-width', '1'], 'yaml_options_line_width_1.golden'),
    (['--line-width', '30'], 'yaml_options_line_width_30.golden'),
    (['--line-width', '200'], 'yaml_options_line_width_200.golden'),
    (['--prose-width', '1'], 'yaml_options_prose_width_1.golden'),
    (['--prose-width', '30'], 'yaml_options_prose_width_30.golden'),
    (['--prose-width', '500'], 'yaml_options_prose_width_500.golden'),
    (['--compact'], 'yaml_options_compact.golden'),
    (['--compact', '--line-width', '40'], 'yaml_options_compact_line_width_40.golden'),
    (['--indent-width', '4', '--line-width', '40', '--prose-width', '40'], 'yaml_options_indent_width_4_line_width_40_prose_width_40.golden'),
]


@pytest.mark.parametrize("options, golden", YAML_OPTION_CASES)
def test_yaml_width_and_indent_options(run, options, golden):
    """CATCHES: YAML emission that ignores or misapplies --indent-width (block indentation of mappings and
    sequences), --line-width (when flow collections expand to block style), --prose-width (folding of long
    prose scalars) or --compact (block collections collapsing to flow when they fit)."""
    result = run(["format", "--stdin-file-path", "doc.yaml", *options], input=YAML_DOC)
    assert result.stdout == (RES / golden).read_bytes()
    assert result.stderr == b""
    assert result.returncode == 0


UNICODE_CASES = [
    pytest.param(['--wrap', '20'], '日本語の文章はとても長いです 日本語の文章はとても長いです 日本語 の 文章 は とても 長い です\n', b'\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x81\xae\xe6\x96\x87\xe7\xab\xa0\xe3\x81\xaf\xe3\x81\xa8\xe3\x81\xa6\xe3\x82\x82\xe9\x95\xb7\xe3\x81\x84\xe3\x81\xa7\xe3\x81\x99\n\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x81\xae\xe6\x96\x87\xe7\xab\xa0\xe3\x81\xaf\xe3\x81\xa8\xe3\x81\xa6\xe3\x82\x82\xe9\x95\xb7\xe3\x81\x84\xe3\x81\xa7\xe3\x81\x99 \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e \xe3\x81\xae\n\xe6\x96\x87\xe7\xab\xa0 \xe3\x81\xaf \xe3\x81\xa8\xe3\x81\xa6\xe3\x82\x82 \xe9\x95\xb7\xe3\x81\x84 \xe3\x81\xa7\xe3\x81\x99\n', id='cjk_markdown_display_width'),
    pytest.param(['--wrap', '20'], 'Emoji 😀😀😀 wrap 👩\u200d👩\u200d👧\u200d👦 family éé combining text here\n', b'Emoji \xf0\x9f\x98\x80\xf0\x9f\x98\x80\xf0\x9f\x98\x80 wrap\n\xf0\x9f\x91\xa9\xe2\x80\x8d\xf0\x9f\x91\xa9\xe2\x80\x8d\xf0\x9f\x91\xa7\xe2\x80\x8d\xf0\x9f\x91\xa6 family \xc3\xa9\xc3\xa9\ncombining text here\n', id='emoji_zwj_and_combining'),
    pytest.param(['--wrap', '20'], '#   No-break   spaces\n\nnon\xa0breaking\xa0space\xa0words stay together please ok\n', b'# No-break spaces\n\nnon\xc2\xa0breaking\xc2\xa0space\xc2\xa0words stay together please ok\n', id='nbsp_joined_words'),
    pytest.param(['--wrap', '20'], 'tab\tseparated\twords in a paragraph here\n', b'tab separated words\nin a paragraph here\n', id='tabs_inside_paragraph'),
    pytest.param(['--wrap', '20'], 'עברית מימין לשמאל and English mixed together\n', b'\xd7\xa2\xd7\x91\xd7\xa8\xd7\x99\xd7\xaa \xd7\x9e\xd7\x99\xd7\x9e\xd7\x99\xd7\x9f \xd7\x9c\xd7\xa9\xd7\x9e\xd7\x90\xd7\x9c\nand English mixed\ntogether\n', id='rtl_mixed_text'),
    pytest.param(['--wrap', '16'], '#   全角の見出し   #\n\n*   リスト項目は長いので折り返されます 次の項目\n', b'# \xe5\x85\xa8\xe8\xa7\x92\xe3\x81\xae\xe8\xa6\x8b\xe5\x87\xba\xe3\x81\x97\n\n- \xe3\x83\xaa\xe3\x82\xb9\xe3\x83\x88\xe9\xa0\x85\xe7\x9b\xae\xe3\x81\xaf\xe9\x95\xb7\xe3\x81\x84\xe3\x81\xae\xe3\x81\xa7\xe6\x8a\x98\xe3\x82\x8a\xe8\xbf\x94\xe3\x81\x95\xe3\x82\x8c\xe3\x81\xbe\xe3\x81\x99\n  \xe6\xac\xa1\xe3\x81\xae\xe9\xa0\x85\xe7\x9b\xae\n', id='fullwidth_heading_and_list'),
    pytest.param([], 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx short words follow the very long token\n', b'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\nshort words follow the very long token\n', id='overlong_word'),
]


@pytest.mark.parametrize("args, text, expected", UNICODE_CASES)
def test_markdown_wrapping_uses_display_width(run, args, text, expected):
    """CATCHES: wrapping that counts bytes or code points instead of terminal display width (CJK and emoji
    are two columns, ZWJ sequences and combining marks do not split), breaks at no-break spaces, keeps tabs
    between words, or splits an over-long token."""
    result = run(["format", "--stdin-file-path", "u.md", *args], input=text)
    assert result.stdout == expected
    assert result.stderr == b""
    assert result.returncode == 0



def test_yaml_prose_width_with_wide_characters(run):
    """CATCHES: folding YAML prose by display width or bytes; the reference folds CJK prose scalars at
    --prose-width counted in characters and emits a `>-` block."""
    result = run(["format", "--stdin-file-path", "u.yaml", "--prose-width", "20"], input='k: "日本語の文章はとても長いです 日本語の文章はとても長いです 日本語 の 文章"\n')
    assert result.stdout == b'k: >-\n  \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x81\xae\xe6\x96\x87\xe7\xab\xa0\xe3\x81\xaf\xe3\x81\xa8\xe3\x81\xa6\xe3\x82\x82\xe9\x95\xb7\xe3\x81\x84\xe3\x81\xa7\xe3\x81\x99\n  \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\xe3\x81\xae\xe6\x96\x87\xe7\xab\xa0\xe3\x81\xaf\xe3\x81\xa8\xe3\x81\xa6\xe3\x82\x82\xe9\x95\xb7\xe3\x81\x84\xe3\x81\xa7\xe3\x81\x99 \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e \xe3\x81\xae\n  \xe6\x96\x87\xe7\xab\xa0\n'
    assert result.stderr == b""
    assert result.returncode == 0



LARGE_PARAGRAPH = 'Alpha   beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega.\n'
LARGE_PARAGRAPH_FORMATTED = b'Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi\nomicron pi rho sigma tau upsilon phi chi psi omega.\n'


def test_large_markdown_document_formats_every_paragraph(run):
    """CATCHES: implementations that truncate, time out on, or format inconsistently a ~380 KB Markdown file of
    3000 identical paragraphs; every paragraph must be rewrapped exactly like a single one."""
    result = run(["format", "--stdin-file-path", "big.md"], input="\n".join([LARGE_PARAGRAPH] * 3000))
    assert result.stdout == b"\n".join([LARGE_PARAGRAPH_FORMATTED] * 3000)
    assert result.stderr == b""
    assert result.returncode == 0


def test_large_yaml_mapping_normalises_every_entry(run, workdir):
    """CATCHES: YAML handling that degrades on 5000 entries (dropping, reordering or differently spacing
    later keys) or writes a file in path mode with different bytes than stdin mode."""
    source = "".join("key_%d:   {a: 1,   b: [x,y]}\n" % i for i in range(5000))
    expected = "".join("key_%d: {a: 1, b: [x, y]}\n" % i for i in range(5000)).encode()
    result = run(["format", "--stdin-file-path", "big.yaml"], input=source)
    assert result.stdout == expected
    assert result.stderr == b""
    assert result.returncode == 0
    write_tree(workdir, {"big.yaml": source})
    written = run(["format", "big.yaml"])
    assert written.stdout == b"1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n"
    assert written.stderr == b""
    assert written.returncode == 0
    assert read_tree(workdir) == {"big.yaml": expected}


def test_hundred_kilobyte_word_is_never_split(run):
    """CATCHES: wrapping that splits a 100 000-character token or loses the following word; the token stays
    on its own line and the next word moves to the following line."""
    result = run(["format", "--stdin-file-path", "big.md"], input="word" * 25000 + " tail\n")
    assert result.stdout == ("word" * 25000 + "\ntail\n").encode()
    assert result.stderr == b""
    assert result.returncode == 0



EXT_FILES = {'a.MD': '#   A\n', 'b.Yaml': 'b:    1\n', 'c.YML': 'c:    [1,2]\n', 'd.Py': '#| d:    1\nx = 1\n', 'e.QMD': '#   E\n', 'f.RMD': '#   F\n', 'g.rMd': '#   G\n', 'h.R': '#| h:    1\n', 'i.r': '#| i:    1\n', 'j.JSON': '{"j":   1}\n', 'k.markdown': '#   K\n', 'l.yaml.txt': 'l:    1\n', 'm.Qmd~': '#   M\n', 'noext': '#   N\n'}


def test_extension_matching_is_ascii_case_insensitive_and_others_are_skipped(run, workdir):
    """CATCHES: extension matching that is case-sensitive (missing .MD/.Yaml/.YML/.Py/.QMD/.RMD) or too loose
    (formatting .markdown, .json, .yaml.txt, backup `~` files or extension-less files); unsupported files must
    be counted as skipped and left byte-identical."""
    write_tree(workdir, EXT_FILES)
    result = run(["format", "."])
    assert result.stdout == b'14 files scanned, 9 formatted, 0 unchanged, 5 skipped, 0 failed\n'
    assert result.stderr == b''
    assert result.returncode == 0
    assert read_tree(workdir) == {'a.MD': b'# A\n', 'b.Yaml': b'b: 1\n', 'c.YML': b'c: [1, 2]\n', 'd.Py': b'#| d: 1\nx = 1\n', 'e.QMD': b'# E\n', 'f.RMD': b'# F\n', 'g.rMd': b'# G\n', 'h.R': b'#| h: 1\n', 'i.r': b'#| i: 1\n', 'j.JSON': b'{"j":   1}\n', 'k.markdown': b'#   K\n', 'l.yaml.txt': b'l:    1\n', 'm.Qmd~': b'#   M\n', 'noext': b'#   N\n'}



def test_mixed_multi_file_run_write_mode(run, workdir):
    """CATCHES: write-mode multi-path runs that stop at the first failure, write files they should not
    (check/diff must never write; write mode must still write the other changed files), miscount the summary,
    print diffs or diagnostics in a different order, or use the wrong exit status when one file fails."""
    write_tree(workdir, {'docs/changed.md': '#   Changed   heading\n', 'docs/clean.md': '# Clean\n', 'docs/broken.yaml': '# fmt: off\na:   1\n', 'docs/notes.txt': 'keep   me\n', 'conf/settings.yaml': 'x:    [1,2]\n', 'conf/ok.yml': 'y: 1\n'})
    result = run(['format', 'docs', 'conf'])
    assert result.stdout == b'6 files scanned, 2 formatted, 2 unchanged, 1 skipped, 1 failed\n'
    assert result.stderr.decode() == 'docs/broken.yaml:2:7: error: unterminated fmt: off\n'
    assert result.returncode == 1
    assert read_tree(workdir) == {'docs/changed.md': b'# Changed heading\n', 'docs/clean.md': b'# Clean\n', 'docs/broken.yaml': b'# fmt: off\na:   1\n', 'docs/notes.txt': b'keep   me\n', 'conf/settings.yaml': b'x: [1, 2]\n', 'conf/ok.yml': b'y: 1\n'}



def test_mixed_multi_file_run_check_mode(run, workdir):
    """CATCHES: check-mode multi-path runs that stop at the first failure, write files they should not
    (check/diff must never write; write mode must still write the other changed files), miscount the summary,
    print diffs or diagnostics in a different order, or use the wrong exit status when one file fails."""
    write_tree(workdir, {'docs/changed.md': '#   Changed   heading\n', 'docs/clean.md': '# Clean\n', 'docs/broken.yaml': '# fmt: off\na:   1\n', 'docs/notes.txt': 'keep   me\n', 'conf/settings.yaml': 'x:    [1,2]\n', 'conf/ok.yml': 'y: 1\n'})
    result = run(['format', '--check', 'docs', 'conf'])
    assert result.stdout == b''
    assert result.stderr.decode() == '6 files scanned, 2 formatted, 2 unchanged, 1 skipped, 1 failed\ndocs/broken.yaml:2:7: error: unterminated fmt: off\n'
    assert result.returncode == 1
    assert read_tree(workdir) == {'docs/changed.md': b'#   Changed   heading\n', 'docs/clean.md': b'# Clean\n', 'docs/broken.yaml': b'# fmt: off\na:   1\n', 'docs/notes.txt': b'keep   me\n', 'conf/settings.yaml': b'x:    [1,2]\n', 'conf/ok.yml': b'y: 1\n'}



def test_mixed_multi_file_run_diff_mode(run, workdir):
    """CATCHES: diff-mode multi-path runs that stop at the first failure, write files they should not
    (check/diff must never write; write mode must still write the other changed files), miscount the summary,
    print diffs or diagnostics in a different order, or use the wrong exit status when one file fails."""
    write_tree(workdir, {'docs/changed.md': '#   Changed   heading\n', 'docs/clean.md': '# Clean\n', 'docs/broken.yaml': '# fmt: off\na:   1\n', 'docs/notes.txt': 'keep   me\n', 'conf/settings.yaml': 'x:    [1,2]\n', 'conf/ok.yml': 'y: 1\n'})
    result = run(['format', '--diff', 'docs', 'conf'])
    assert result.stdout == b'--- docs/changed.md\n+++ docs/changed.md\n@@ -1 +1 @@\n-#   Changed   heading\n+# Changed heading\n--- conf/settings.yaml\n+++ conf/settings.yaml\n@@ -1 +1 @@\n-x:    [1,2]\n+x: [1, 2]\n'
    assert result.stderr.decode() == '6 files scanned, 2 formatted, 2 unchanged, 1 skipped, 1 failed\ndocs/broken.yaml:2:7: error: unterminated fmt: off\n'
    assert result.returncode == 1
    assert read_tree(workdir) == {'docs/changed.md': b'#   Changed   heading\n', 'docs/clean.md': b'# Clean\n', 'docs/broken.yaml': b'# fmt: off\na:   1\n', 'docs/notes.txt': b'keep   me\n', 'conf/settings.yaml': b'x:    [1,2]\n', 'conf/ok.yml': b'y: 1\n'}
