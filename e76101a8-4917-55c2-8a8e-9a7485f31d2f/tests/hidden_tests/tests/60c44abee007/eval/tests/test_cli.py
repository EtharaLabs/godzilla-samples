"""The command line itself: usage, options, scripts, the order `run` does things in, and its errors."""

import json

from conftest import out, err


def test_usage_without_arguments(sc):
    """CATCHES: a rewrite that prints no usage, prints it to stdout instead of stderr, or exits 0 when given nothing."""
    sc.run([])
    assert sc.transcript() == sc.golden()


def test_version_and_extra_argument(sc):
    """CATCHES: --version printing another release string, or --version followed by anything being accepted."""
    sc.run(["--version"])
    sc.run(["--version", "extra"])
    assert sc.transcript() == sc.golden()


def test_run_unknown_option_names_it_with_usage(sc):
    """CATCHES: an unknown `run` option being ignored, or the error not naming the option in backticks before the usage."""
    sc.run(["run", "--frobnicate"])
    assert sc.transcript() == sc.golden()


def test_run_options_that_need_a_value(sc):
    """CATCHES: --save, --cmd or --script without a value being accepted silently instead of saying it needs a value."""
    sc.run(["run", "--save"])
    sc.run(["run", "--cmd"])
    sc.run(["run", "--script"])
    assert sc.transcript() == sc.golden()


def test_bad_subcommand_shapes_print_usage(sc):
    """CATCHES: info with no file, convert with one argument, or commands with an extra argument being accepted."""
    sc.run(["info"])
    sc.run(["convert", "only.bimcraft"])
    sc.run(["commands", "extra"])
    sc.run(["frobnicate"])
    assert sc.transcript() == sc.golden()


def test_readme_script_builds_a_house(sc):
    """CATCHES: wrong ids, marks, offsets or room and floor areas for the README's six-line house, or a result line per
    command missing or out of order."""
    sc.cmds(
        'wall {"points": [[0,0],[8000,0],[8000,6000],[0,6000]], "closed": true, "type": "Exterior - 300mm"}',
        'door {"at": [2000, 0]}',
        'window {"at": [8000, 3000]}',
        'room {"point": [4000, 3000], "name": "Living"}',
        "floor {}",
        "roof {}",
    )
    assert sc.transcript() == sc.golden()


def test_script_file_with_comments_blank_lines_and_bare_ids(sc):
    """CATCHES: a script reader that chokes on `#` comments, blank or indented lines, or a command with no JSON after it."""
    sc.write(
        "house.txt",
        "# a small house\n"
        "\n"
        '   wall {"points": [[0,0],[5000,0],[5000,4000],[0,4000]], "closed": true}\n'
        "   # indented comment\n"
        'room {"point": [2500, 2000], "name": "Hall"}\n'
        "floor\n"
        "\t\n"
        "inspect\n",
    )
    p = sc.run(["run", "--script", "house.txt"], show=False)
    lines = out(p).splitlines()
    sc.note(f"exit {p.returncode}, {len(lines)} lines")
    sc.note("\n".join(lines[:3]))
    inspect = json.loads(lines[3])
    sc.note(json.dumps({k: inspect[k] for k in ("counts", "history", "levels", "name", "warnings")}, sort_keys=True))
    assert sc.transcript() == sc.golden()


def test_failing_script_line_is_named_and_nothing_of_the_script_is_printed(sc):
    """CATCHES: a script that keeps going after a failing line, prints the results of the lines before it, or names the
    wrong line number (comments and blank lines count)."""
    sc.write(
        "bad.txt",
        '# first\nwall {"points": [[0,0],[4000,0]]}\n\ndoor {"at": [9000, 9000]}\nwall {"points": [[0,0],[0,4000]]}\n',
    )
    sc.run(["run", "--cmd", 'level {"elevation": 6000}', "--script", "bad.txt", "--cmd", "inspect {}"])
    assert sc.transcript() == sc.golden()


def test_bad_json_after_a_command(sc):
    """CATCHES: malformed JSON parameters being treated as empty, or the error not giving serde's position and the id."""
    sc.cmds('wall {"points": [[0,0],[1000,0]]')
    sc.cmds("wall {points: 1}")
    sc.cmds("wall [1, 2]")
    assert sc.transcript() == sc.golden()


def test_unknown_command_and_missing_script_file(sc):
    """CATCHES: an unknown command id passing silently, or a missing --script file not reported with its path."""
    sc.cmds("bogus {}")
    sc.run(["run", "--script", "missing.txt"])
    assert sc.transcript() == sc.golden()


def test_aliases_and_case_insensitive_ids(sc):
    """CATCHES: Revit-style shortcuts (WA, DR, RM, LL) or upper-case command ids not resolving to their commands."""
    sc.cmds(
        'WA {"points": [[0,0],[6000,0],[6000,5000],[0,5000]], "closed": true}',
        'dr {"at": [3000, 0]}',
        'Wall {"points": [[3000,0],[3000,5000]]}',
        'RM {"point": [1500, 2500]}',
        'LL {"elevation": 6000}',
        'ELEMENTS {"category": "room"}',
    )
    assert sc.transcript() == sc.golden()


def test_results_print_as_each_argument_runs_until_a_failure(sc):
    """CATCHES: buffering every result until the end, or printing nothing when a later --cmd fails; the earlier lines must
    reach stdout and the failure stderr with exit status 1."""
    sc.cmds('wall {"points": [[0,0],[4000,0]]}', 'level {"elevation": 3500, "name": "Mezzanine"}',
            'door {"at": [100000, 0]}', 'level {"elevation": 9000}')
    assert sc.transcript() == sc.golden()


def test_multiple_commands_in_one_cmd_value(sc):
    """CATCHES: a --cmd value treated as a single command instead of a script of several lines."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}\nwall {"points": [[4000,0],[4000,3000]]}\n# done\ninspect {}'],
           show=False)
    p = sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}\nwall {"points": [[4000,0],[4000,3000]]}\nelements {"category": "wall"}'])
    assert p.returncode == 0
    assert sc.transcript() == sc.golden()


def test_commands_catalog_matches(run):
    """CATCHES: a command missing from the catalog, renamed, given other shortcuts, labels, menus or parameter docs."""
    from conftest import read_golden

    p = run(["commands"])
    assert (p.returncode, err(p)) == (0, "")
    assert out(p) == read_golden(__file__, "commands.golden")


def test_save_without_path_on_a_new_project(sc):
    """CATCHES: `save {}` on a project that was never saved writing somewhere instead of asking for a path."""
    sc.cmds('wall {"points": [[0,0],[4000,0]]}', "save {}")
    assert sc.transcript() == sc.golden()


def test_save_unknown_extension(sc):
    """CATCHES: a --save path with an unsupported extension writing a file or failing with an unhelpful message."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[4000,0]]}', "--save", "house.dwg"])
    sc.run(["run", "--save", "house"])
    sc.files()
    assert sc.transcript() == sc.golden()
