"""Markdown tables: GFM pipe tables (alignment, escaped pipes, empty cells, CRLF without
a final newline, cells wider than the source column), Pandoc grid tables (alignment
colons in borders and header separators, malformed borders), simple and multiline
tables, formatted with fit and preserved widths, canonical spelling, and through the
Git clean (compact tables) and smudge filters.
"""

import pytest

from conftest import format_both_ways, outcome

TABLES = {
    'grid_border_alignment': '+:-----+-----:+:----:+\n| a | b | c |\n+======+======+======+\n| 1 | 2 | 3 |\n+------+------+------+\n',
    'grid_header_separator_alignment': '+------+------+\n| a | b |\n+:=====+=====:+\n| 1 | 2 |\n+------+------+\n',
    'grid_invalid_border_marker': '+--x--+-----+\n| a | b |\n+-----+-----+\n',
    'grid_borders_without_rows': '+-----+-----+\n+-----+-----+\n',
    'grid_unterminated': '+-----+-----+\n| a | b |\n',
    'pipe_center_alignment': '| a | b | c |\n|:-:|:--|--:|\n| x | y | z |\n',
    'pipe_crlf_without_final_newline': '| a | b |\r\n|---|---|\r\n| x | y |',
    'pipe_cell_wider_than_source': '| a | b |\n|---|---|\n| very long cell | y |\n',
    'pipe_single_row': '| a | b |\n',
    'pipe_empty_cells': '| | |\n|---|---|\n| | |\n',
    'pipe_escaped_pipe_and_code': '| a \\| b | c |\n|---|---|\n| `x|y` | z |\n',
    'simple_headerless': '-----  -----\nx      y\nlonger z\n-----  -----\n',
    'simple_aligned': '  Right     Left     Center\n-------     ------ ----------\n     12     12        12\n',
    'multiline_table': '-------------------------------------------------------------\n Centered   Default           Right Left\n  Header    Aligned         Aligned Aligned\n----------- ------- --------------- -------------------------\n   First    row                12.0 Example of a row that\n                                    spans multiple lines.\n-------------------------------------------------------------\n',
}

MODES = {"fit": [], "preserve": ["--table-widths", "preserve"], "canonical": ["--canonical"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(TABLES))
def test_table_formatting(name, mode, run, workdir, golden):
    """CATCHES: wrong column fitting or alignment markers, reflowing malformed tables,
    breaking escaped pipes or code spans in cells, or ignoring `--table-widths preserve`."""
    observed = format_both_ways(run, workdir, "doc.md", TABLES[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")


@pytest.mark.parametrize("name", sorted(TABLES))
def test_table_through_git_filters(name, run, workdir, golden):
    """CATCHES: emitting padded tables from the clean filter (it must use the compact
    form, including `:---:` centre markers) or different table output from smudge; the
    path-mode `--check` summary for the same file is recorded alongside."""
    observed = {
        filter_name: outcome(run(["git-filter", filter_name, "--stdin-filename", "doc.md"], input=TABLES[name]))
        for filter_name in ("clean", "smudge")
    }
    observed["check"] = format_both_ways(run, workdir, "doc.md", TABLES[name])["check"]
    assert observed == golden(f"{name}__filters")
