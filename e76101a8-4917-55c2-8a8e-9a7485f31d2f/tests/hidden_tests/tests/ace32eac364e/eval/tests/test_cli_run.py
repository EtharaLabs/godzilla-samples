"""`bimcraft-cli run`: options in order, scripts, errors and saving by extension."""

import re

import pytest
from conftest import normalize

WALL = 'wall {"points": [[0, 0], [4000, 0]]}'
BOX = 'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}'

# Each case: the arguments of `run`, and the files to write in the working directory first.
CASES = {
    "one_command": (["--cmd", WALL], {}),
    "shortcut_alias": (["--cmd", 'WA {"points": [[0, 0], [4000, 0]]}'], {}),
    "command_name_any_case": (["--cmd", 'Wall {"points": [[0, 0], [4000, 0]]}', "--cmd", "INSPECT"], {}),
    "command_without_params": (["--cmd", "wall"], {}),
    "bad_json": (["--cmd", "wall {bad json"], {}),
    "unknown_command": (["--cmd", "frobnicate {}"], {}),
    "comment_and_blank_lines": (["--cmd", "# a comment\n\n   \n# another", "--cmd", WALL], {}),
    "multi_line_value_fails_on_line_three": (["--cmd", WALL + '\ndoor {"at": [2000, 0]}\nnonsense {}'], {}),
    "multi_line_value_prints_each_result": (["--cmd", WALL + '\ndoor {"at": [2000, 0]}\n# done\nelements {"category": "door"}'], {}),
    "earlier_values_print_before_a_failure": (["--cmd", WALL, "--cmd", 'door {"at": [9000, 9000]}', "--cmd", "inspect"], {}),
    "undo_and_redo": (["--cmd", WALL, "--cmd", 'level {"elevation": 6000}', "--cmd", "undo", "--cmd", "redo", "--cmd", "undo",
                       "--cmd", "undo", "--cmd", "undo"], {}),
    "redo_with_nothing_to_redo": (["--cmd", "redo"], {}),
    "undo_with_nothing_to_undo": (["--cmd", "undo"], {}),
    "script_file": (["--script", "house.txt", "--cmd", 'elements {"category": "room"}'],
                    {"house.txt": "# a house\n" + BOX + '\n\ndoor {"at": [3000, 0]}\nroom {"point": [3000, 2000], "name": "Hall"}\n'}),
    "script_room_outside_walls_warns": (["--script", "room.txt"], {"room.txt": BOX + "\n# two\nroom {\"point\": [99000, 0]}\n"}),
    "script_file_failing_line_is_named": (["--script", "bad.txt", "--cmd", "inspect"],
                                          {"bad.txt": BOX + "\n# two\n\ndoor {\"at\": [99000, 0]}\nwall {}\n"}),
    "script_file_missing": (["--script", "missing.txt"], {}),
    "scripts_and_commands_run_in_order": (["--cmd", WALL, "--script", "a.txt", "--cmd", 'elements {"category": "wall"}'],
                                          {"a.txt": 'wall {"points": [[0, 1000], [4000, 1000]]}\n'}),
    "sample_prints_nothing": (["--sample", "--cmd", 'elements {"category": "room"}'], {}),
    "sample_then_inspect": (["--sample", "--cmd", "inspect"], {}),
    "unknown_option": (["--frobnicate"], {}),
    "option_with_equals_sign": (["--save=plan.png"], {}),
    "cmd_needs_a_value": (["--cmd"], {}),
    "script_needs_a_value": (["--script"], {}),
    "save_needs_a_value": (["--cmd", WALL, "--save"], {}),
    "missing_project_file": (["missing.bimcraft"], {}),
    "single_dash_is_a_file": (["-x"], {}),
    "positional_file_opens_in_order": (["--cmd", WALL, "p.bimcraft", "--cmd", "inspect"], {"p.bimcraft": None}),
    "save_without_extension_is_a_project": (["--cmd", WALL, "--save", "plain"], {}),
    "save_unknown_extension_is_a_project": (["--cmd", WALL, "--save", "notes.txt"], {}),
    "save_extension_any_case": (["--cmd", BOX, "--save", "UPPER.IFC", "--save", "Plan.Svg"], {}),
    "pdf_without_sheets": (["--cmd", WALL, "--save", "sheets.pdf"], {}),
    "save_in_order_then_fail": (["--cmd", WALL, "--save", "first.bimcraft", "--cmd", "nonsense"], {}),
}


def _setup(workdir, run, files):
    for name, text in files.items():
        if text is None:  # a project made by the program itself
            r = run(["run", "--cmd", 'wall {"points": [[0, 2000], [5000, 2000]]}', "--save", name])
            assert r.returncode == 0, r.stderr
        else:
            (workdir / name).write_text(text)


@pytest.mark.parametrize("case", sorted(CASES))
def test_run(run, workdir, golden, case):
    """CATCHES: a rewrite of `run` that handles its options out of order, prints results in a different shape, drops
    or reorders result lines, words an error differently, exits with the wrong code, or keeps going after a failure."""
    args, files = CASES[case]
    _setup(workdir, run, files)
    r = run(["run", *args])
    golden.check_run(r, f"{case}.txt")


def test_failure_before_save_writes_nothing(run, workdir, golden):
    """CATCHES: a rewrite that saves a project although a command before --save failed, or that reorders --save to the end."""
    r = run(["run", "--cmd", WALL, "--cmd", 'door {"at": [9000, 9000]}', "--save", "never.bimcraft"])
    golden.check_run(r, "failure_before_save.txt")
    assert sorted(p.name for p in workdir.iterdir()) == []


def test_save_then_failure_keeps_the_saved_file(run, workdir, golden):
    """CATCHES: a rewrite that defers --save until all commands ran, or removes what it saved when a later command fails."""
    r = run(["run", "--cmd", WALL, "--save", "first.svg", "--cmd", "nonsense"])
    golden.check_run(r, "save_then_failure.txt")
    golden.check((workdir / "first.svg").read_text(), "save_then_failure.svg")


def test_save_into_a_missing_folder(run, workdir, golden):
    """CATCHES: a rewrite that creates missing folders on save, or reports the failure without naming the path."""
    r = run(["run", "--cmd", WALL, "--save", "nodir/x.bimcraft"])
    # The temporary file the save was written to first has a random name and an absolute path.
    err = re.sub(r' at path "[^"]*"', ' at path "<TMP>"', r.stderr.decode())
    golden.check(f"exit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{err}", "save_into_missing_folder.txt")
    assert list(workdir.iterdir()) == []


def test_save_png_into_a_missing_folder(run, golden):
    """CATCHES: a rewrite that reports a failed picture export differently from the reference."""
    r = run(["run", "--cmd", WALL, "--save", "nodir/plan.png"])
    golden.check_run(r, "save_png_into_missing_folder.txt")


def test_save_ifc_into_a_missing_folder(run, golden):
    """CATCHES: a rewrite that reports a failed IFC export differently from the reference."""
    r = run(["run", "--cmd", WALL, "--save", "nodir/model.ifc"])
    golden.check_run(r, "save_ifc_into_missing_folder.txt")


def test_save_glb_into_a_missing_folder(run, golden):
    """CATCHES: a rewrite that reports a failed glTF export differently from the reference."""
    r = run(["run", "--cmd", WALL, "--save", "nodir/scene.glb"])
    golden.check_run(r, "save_glb_into_missing_folder.txt")


def test_script_with_crlf_line_endings(run, workdir, golden):
    """CATCHES: a rewrite that fails on a script saved with Windows line endings instead of trimming each line."""
    (workdir / "win.txt").write_bytes((BOX + "\r\n# c\r\n" + 'door {"at": [3000, 0]}\r\n').encode())
    r = run(["run", "--script", "win.txt", "--cmd", 'elements {"category": "door"}'])
    golden.check_run(r, "crlf_script.txt")


def test_script_that_is_not_utf8(run, workdir, golden):
    """CATCHES: a rewrite that reads a script that is not valid UTF-8 instead of refusing it with the OS reading error."""
    (workdir / "latin.txt").write_bytes(b'text {"text": "caf\xe9", "at": [0, 0]}\n')
    r = run(["run", "--script", "latin.txt"])
    golden.check_run(r, "non_utf8_script.txt")


def test_script_that_is_a_folder(run, workdir, golden):
    """CATCHES: a rewrite that treats a folder given to --script as an empty script."""
    (workdir / "folder").mkdir()
    r = run(["run", "--script", "folder"])
    golden.check_run(r, "script_is_folder.txt")


def test_saved_project_round_trips(run, workdir, golden):
    """CATCHES: a rewrite whose .bimcraft file differs from the reference's (keys, order, numbers, format version), apart
    from the random GUIDs and uid."""
    r = run(["run", "--cmd", BOX, "--cmd", 'door {"at": [3000, 0]}', "--save", "p.bimcraft"])
    golden.check_run(r, "round_trip_save.txt")
    golden.check(_norm((workdir / "p.bimcraft").read_text()), "round_trip.bimcraft")
    r = run(["run", "p.bimcraft", "--cmd", 'elements {"category": "door"}'])
    golden.check_run(r, "round_trip_open.txt")


def _norm(text):
    return normalize(text)


def test_run_with_nothing_saves_an_empty_project(run, workdir, golden):
    """CATCHES: a rewrite whose `run` with no command prints something, or whose empty project (its starter levels,
    types and settings) differs from the reference's."""
    r = run(["run", "--save", "empty.bimcraft"])
    golden.check_run(r, "empty_project_save.txt")
    golden.check(normalize((workdir / "empty.bimcraft").read_text()), "empty.bimcraft")
