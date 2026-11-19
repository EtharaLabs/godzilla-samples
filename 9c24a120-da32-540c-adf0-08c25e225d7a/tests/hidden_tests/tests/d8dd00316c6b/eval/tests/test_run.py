"""`pyfun run`: compile, then execute with Python — stdin, argv, exit status, working
directory, files the program writes, and interpreter selection."""

from conftest import case_transcript, golden_name, read_golden, run_case

ARGV = (
    "extern import sys\n"
    "extern getArgv : unit -> List string = sys.argv.copy\n"
    "print (List.drop 1 (getArgv ()))\n"
)

# The staged script lives in a per-process temporary directory; only that prefix varies.
STAGED = [(r'File "[^"]*/pyfun_run_\d+/', 'File "<staged>/')]


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert case_transcript(proc, case) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


# ---------------------------------------------------------------- argv

ARGV_BARE_CASE = {"id": "argv_bare", "files": {"argv.pyfun": ARGV},
                  "args": ["run", "argv.pyfun", "hello", "42"]}
ARGV_SEPARATOR_CASE = {"id": "argv_separator", "files": {"argv.pyfun": ARGV},
                       "args": ["run", "argv.pyfun", "--", "hello", "42"]}
ARGV_FLAGS_CASE = {"id": "argv_flag_like", "files": {"argv.pyfun": ARGV},
                   "args": ["run", "argv.pyfun", "-o", "--help", "--target", "3.11", "--native"]}
ARGV_DOUBLE_SEPARATOR_CASE = {"id": "argv_double_separator", "files": {"argv.pyfun": ARGV},
                              "args": ["run", "argv.pyfun", "--", "--", "x y", ""]}
ARGV_NONE_CASE = {"id": "argv_none", "files": {"argv.pyfun": ARGV}, "args": ["run", "argv.pyfun"]}
ARGV0_CASE = {
    "id": "argv0_is_staged_script",
    "files": {"prog.pyfun": (
        "extern import sys\n"
        "extern import os.path\n"
        "extern pure base : string -> string = os.path.basename\n"
        "extern getArgv : unit -> List string = sys.argv.copy\n"
        "match getArgv ():\n"
        "  case [first, *_]: print (base first)\n"
        "  case []: print \"no argv\"\n"
    )},
    "args": ["run", "prog.pyfun"],
}


def test_arguments_after_the_path_reach_sys_argv(run, workdir):
    """CATCHES: `run` dropping program arguments or passing pyfun's own arguments
    (`run`, the path) to the program."""
    _check(run, workdir, ARGV_BARE_CASE)


def test_a_leading_separator_is_consumed(run, workdir):
    """CATCHES: forwarding the optional `--` separator into `sys.argv`."""
    _check(run, workdir, ARGV_SEPARATOR_CASE)


def test_flag_like_arguments_belong_to_the_program(run, workdir):
    """CATCHES: interpreting `-o`, `--help`, `--target` or `--native` after the path as
    pyfun options instead of forwarding them verbatim."""
    _check(run, workdir, ARGV_FLAGS_CASE)


def test_only_the_first_separator_is_consumed(run, workdir):
    """CATCHES: stripping every `--`, splitting arguments on spaces, or dropping empty
    arguments."""
    _check(run, workdir, ARGV_DOUBLE_SEPARATOR_CASE)


def test_no_program_arguments(run, workdir):
    """CATCHES: a `run` that invents arguments when none are given."""
    _check(run, workdir, ARGV_NONE_CASE)


def test_argv0_is_the_staged_main_script(run, workdir):
    """CATCHES: staging the program under the source's own name (which could shadow a
    stdlib module) instead of `_pyfun_main.py`."""
    _check(run, workdir, ARGV0_CASE)


# ---------------------------------------------------------------- stdin

STDIN_CASE = {
    "id": "stdin_reaches_input",
    "files": {"greet.pyfun": (
        "let main =\n"
        "  let name = input \"name? \"\n"
        "  let age = input \"age? \"\n"
        "  print f\"hi {name}, next year you are {Option.withDefault 0 (String.toInt age) + 1}\"\n"
        "main\n"
    )},
    "args": ["run", "greet.pyfun"],
    "stdin": "simon\n41\n",
}
STDIN_LINES_CASE = {
    "id": "stdin_read_all",
    "files": {"wc.pyfun": (
        "extern import sys\n"
        "extern readAll : unit -> string = sys.stdin.read\n"
        "let text = readAll ()\n"
        "let ls = String.split \"\\n\" (String.strip text)\n"
        "print (List.len ls)\n"
        "print (List.map String.upper ls)\n"
    )},
    "args": ["run", "wc.pyfun"],
    "stdin": "alpha\nbeta\ngamma delta\n",
}
STDIN_EOF_CASE = {
    "id": "stdin_eof_traceback",
    "files": {"ask.pyfun": "let name = input \"who? \"\nprint name\n"},
    "args": ["run", "ask.pyfun"],
    "normalize": STAGED,
}


def test_the_program_reads_its_own_stdin(run, workdir):
    """CATCHES: piping the emitted source to `python -`, which spends the program's stdin on
    its own source so `input` sees the wrong text or EOF."""
    _check(run, workdir, STDIN_CASE)


def test_the_program_can_read_all_of_stdin(run, workdir):
    """CATCHES: a runner that does not pass stdin through or truncates it."""
    _check(run, workdir, STDIN_LINES_CASE)


def test_input_at_eof_fails_with_the_python_traceback(run, workdir):
    """CATCHES: swallowing the program's EOFError, or exiting 0 when the program crashed."""
    _check(run, workdir, STDIN_EOF_CASE)


# ---------------------------------------------------------------- exit status and errors

RUNTIME_ERROR_CASE = {
    "id": "runtime_error",
    "files": {"rt.pyfun": "let divide a b = a / b\nprint \"start\"\nlet boom = divide 1 0\nprint \"never\"\n"},
    "args": ["run", "rt.pyfun"],
    "normalize": STAGED,
}
SYS_EXIT_CASE = {
    "id": "sys_exit_nonzero",
    "files": {"exit.pyfun": (
        "extern import sys\n"
        "extern quit : int -> unit = sys.exit\n"
        "print \"before\"\n"
        "quit 3\n"
        "print \"after\"\n"
    )},
    "args": ["run", "exit.pyfun"],
}
SYS_EXIT_ZERO_CASE = {
    "id": "sys_exit_zero",
    "files": {"exit0.pyfun": (
        "extern import sys\n"
        "extern quit : int -> unit = sys.exit\n"
        "print \"done\"\n"
        "quit 0\n"
    )},
    "args": ["run", "exit0.pyfun"],
}
ILL_TYPED_CASE = {
    "id": "ill_typed_does_not_run",
    "files": {"bad.pyfun": "print \"side effect\"\nlet add a b = a + b\nlet r = add 1 true\n"},
    "args": ["run", "bad.pyfun"],
}
PARSE_ERROR_CASE = {
    "id": "parse_error_does_not_run",
    "files": {"bad.pyfun": "print \"side effect\"\nlet = 3\n"},
    "args": ["run", "bad.pyfun"],
}
STDERR_CASE = {
    "id": "program_stderr",
    "files": {"err.pyfun": (
        "extern import sys\n"
        "extern warn : string -> unit = sys.stderr.write\n"
        "print \"to stdout\"\n"
        "warn \"to stderr\\n\"\n"
    )},
    "args": ["run", "err.pyfun"],
}


def test_a_runtime_error_exits_non_zero_with_the_traceback(run, workdir):
    """CATCHES: a `run` that exits 0 after an uncaught Python exception, hides the
    traceback, or loses the output printed before the failure."""
    _check(run, workdir, RUNTIME_ERROR_CASE)


def test_a_non_zero_sys_exit_makes_run_fail(run, workdir):
    """CATCHES: ignoring the program's exit status (exit 0 after `sys.exit(3)`)."""
    _check(run, workdir, SYS_EXIT_CASE)


def test_sys_exit_zero_is_success(run, workdir):
    """CATCHES: a runner that treats any `SystemExit` (even `sys.exit(0)`) as a failure and
    exits non-zero."""
    _check(run, workdir, SYS_EXIT_ZERO_CASE)


def test_ill_typed_code_never_runs(run, workdir):
    """CATCHES: running a program before (or despite) type-checking, so its top-level
    `print` executes even though the file has a type error."""
    _check(run, workdir, ILL_TYPED_CASE)


def test_a_parse_error_never_runs(run, workdir):
    """CATCHES: running a program that does not parse, or a different parse diagnostic."""
    _check(run, workdir, PARSE_ERROR_CASE)


def test_program_stderr_is_passed_through(run, workdir):
    """CATCHES: a runner that merges, drops or reorders the program's stderr."""
    _check(run, workdir, STDERR_CASE)


# ---------------------------------------------------------------- working directory and files

CWD_CASE = {
    "id": "relative_paths_use_the_callers_cwd",
    "files": {
        "data.txt": "payload line 1\npayload line 2\n",
        "src/reader.pyfun": (
            "extern readFile : string -> string = pathlib.Path.read_text\n"
            "extern pure path : string -> string = pathlib.Path\n"
            "print (readFile (path \"data.txt\"))\n"
        ),
    },
    "args": ["run", "src/reader.pyfun"],
}
WRITES_FILE_CASE = {
    "id": "program_writes_a_file",
    "files": {"writer.pyfun": (
        "extern writeFile : string -> string -> int = pathlib.Path.write_text\n"
        "extern pure path : string -> string = pathlib.Path\n"
        "let lines = List.map (fun n -> f\"line {n}: {n * n}\") (List.range 1 6)\n"
        "let n = writeFile (path \"out.txt\") (String.join \"\\n\" lines)\n"
        "print f\"wrote {n} characters\"\n"
    )},
    "args": ["run", "writer.pyfun"],
    "outputs": ["out.txt"],
}
SUBDIR_CASE = {
    "id": "run_from_a_subdirectory",
    "files": {"app/hello.pyfun": "print \"hello from a subdirectory\"\n"},
    "cwd": "app",
    "args": ["run", "hello.pyfun"],
}
NAMED_LIKE_STDLIB_CASE = {
    "id": "source_named_like_a_stdlib_module",
    "files": {"json.pyfun": (
        "extern dumps : List int -> string = json.dumps\n"
        "print (dumps [1, 2, 3])\n"
    )},
    "args": ["run", "json.pyfun"],
}


def test_relative_paths_resolve_against_the_callers_directory(run, workdir):
    """CATCHES: running the program from its staging directory (or the source's directory)
    instead of the caller's working directory."""
    _check(run, workdir, CWD_CASE)


def test_files_written_by_the_program_land_in_the_working_directory(run, workdir):
    """CATCHES: a runner that changes directory before executing, so the program's output
    file is written elsewhere, or a program whose computed contents differ."""
    _check(run, workdir, WRITES_FILE_CASE)


def test_run_from_a_subdirectory(run, workdir):
    """CATCHES: path handling that only works when the source is in the top directory."""
    _check(run, workdir, SUBDIR_CASE)


def test_a_source_named_json_does_not_shadow_the_json_module(run, workdir):
    """CATCHES: staging `json.pyfun` as `json.py`, which shadows the stdlib module the
    program's extern imports."""
    _check(run, workdir, NAMED_LIKE_STDLIB_CASE)


# ---------------------------------------------------------------- interpreter selection

FAKE_PY = (
    "#!/bin/sh\n"
    "echo \"[fake interpreter] $# args\" >&2\n"
    "exec python3 \"$@\"\n"
)
PYFUN_PYTHON_CASE = {
    "id": "pyfun_python_selects_the_interpreter",
    "files": {"bin/fakepy": FAKE_PY, "hi.pyfun": "print \"hi\"\n"},
    "executables": ["bin/fakepy"],
    "env": {"PYFUN_PYTHON": "{workdir}/bin/fakepy"},
    "args": ["run", "hi.pyfun", "a", "b"],
}
PYFUN_PYTHON_EMPTY_CASE = {
    "id": "empty_pyfun_python_falls_back",
    "files": {"hi.pyfun": "print \"hi\"\n"},
    "env": {"PYFUN_PYTHON": ""},
    "args": ["run", "hi.pyfun"],
}
PYFUN_PYTHON_MISSING_CASE = {
    "id": "pyfun_python_missing",
    "files": {"hi.pyfun": "print \"hi\"\n"},
    "env": {"PYFUN_PYTHON": "./no-such-python"},
    "args": ["run", "hi.pyfun"],
}
NO_PYTHON_CASE = {
    "id": "no_python_on_path",
    "files": {"hi.pyfun": "print \"hi\"\n"},
    "env": {"PATH": "{workdir}/empty-bin"},
    "args": ["run", "hi.pyfun"],
}


def test_pyfun_python_picks_the_interpreter(run, workdir):
    """CATCHES: ignoring `PYFUN_PYTHON`, or invoking the interpreter with extra or
    missing arguments (the script path plus each program argument)."""
    _check(run, workdir, PYFUN_PYTHON_CASE)


def test_an_empty_pyfun_python_falls_back_to_path(run, workdir):
    """CATCHES: treating an empty `PYFUN_PYTHON` as an interpreter name."""
    _check(run, workdir, PYFUN_PYTHON_EMPTY_CASE)


def test_an_unrunnable_interpreter_is_reported(run, workdir):
    """CATCHES: a missing interpreter that panics or exits 0 instead of reporting that it
    "did not finish"."""
    _check(run, workdir, PYFUN_PYTHON_MISSING_CASE)


def test_no_python_on_path_is_reported(run, workdir):
    """CATCHES: a `run` that crashes, or words the error differently, when neither `python`
    nor `python3` can be found."""
    _check(run, workdir, NO_PYTHON_CASE)


# ---------------------------------------------------------------- notes

TAIL_NOTE_CASE = {
    "id": "lowering_note_is_printed_before_running",
    "files": {"collect.pyfun": (
        "let collect n acc =\n"
        "  if n == 0 then acc\n"
        "  else\n"
        "    let f = fun x -> x + n\n"
        "    collect (n - 1) (f acc)\n"
        "print (collect 10 0)\n"
    )},
    "args": ["run", "collect.pyfun"],
}


def test_lowering_notes_go_to_stderr_and_the_program_still_runs(run, workdir):
    """CATCHES: dropping the "note:" lines, printing them on stdout, or refusing to run a
    program that only produced notes."""
    _check(run, workdir, TAIL_NOTE_CASE)
