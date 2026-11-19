"""`check`, `compile`, `run` and `parse` on a single file (no `import`s): output streams, flags,
diagnostics rendering, exit codes, output files and the Python interpreter selection of `run`."""

import os
import stat

import pytest

from conftest import golden, write_files

ADD = "let add a b = a + b\nprint (add 1 2)\n"
ADD_PY = b"def add(a, b):\n    return a + b\nprint(add(1, 2))\n"

TWO_ERRORS = 'let a = 1 + "x"\nlet b = true + 1\n'

SHAPES = """type Shape = Circle float | Rect float float

let area s =
  match s:
    case Circle r: 3.14159 * r * r
    case Rect w h: w * h

let who = "Ada"
print f"{who}: {area (Rect 2.0 3.0)}"
"""

# A self tail call kept recursive because a closure captures a parameter: lowering reports a note.
NOTE_PROG = """let collect n acc =
  if n == 0 then acc
  else collect (n - 1) (List.concat acc [fun k -> n])
let fns = collect 3 []
print (List.len fns)
"""
NOTE_LINE = b"note: `collect` calls itself in tail position but keeps its recursive form: a closure in it captures `n`\n"

ARGV_PROG = """extern import sys
extern getArgv : unit -> List string = sys.argv.copy
print (List.drop 1 (getArgv ()))
"""


def write(workdir, text, name="prog.pyfun"):
    (workdir / name).write_text(text, encoding="utf-8")


def make_script(path, body):
    """An executable /bin/sh script (used as a stand-in interpreter via PYFUN_PYTHON)."""
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ====================================================================== check


def test_check_clean_program_reports_ok_on_stderr(run, workdir):
    """CATCHES: printing the success line on stdout, a different wording than `ok: no type errors`, or a
    non-zero exit for a well-typed file."""
    write(workdir, ADD)
    r = run(["check", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == b"ok: no type errors\n"
    assert r.returncode == 0


@pytest.mark.parametrize("text", ["", "# only a comment\n", "\n\n\n"])
def test_check_empty_or_comment_only_file_is_ok(run, workdir, text):
    """CATCHES: rejecting an empty or comment-only module (it is a valid, empty program)."""
    write(workdir, text)
    r = run(["check", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"ok: no type errors\n", 0)


def test_check_reports_every_type_error_with_a_count(run, workdir):
    """CATCHES: stopping at the first type error, missing the blank line between diagnostics, a wrong
    `--> line:col`, caret width or excerpt, or a wrong pluralised summary (`2 errors`)."""
    write(workdir, TWO_ERRORS)
    r = run(["check", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "check_two_errors.golden")
    assert r.returncode == 1


def test_check_single_error_summary_is_singular(run, workdir):
    """CATCHES: `1 errors` (wrong pluralisation) or a missing blank line before the summary."""
    write(workdir, "let r = 1 + true\n")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b"error: expected int, found bool\n --> 1:13\n  |\n1 | let r = 1 + true\n"
                        b"  |             ^^^^\n\n1 error\n")
    assert (r.stdout, r.returncode) == (b"", 1)


def test_check_parse_error_has_no_summary_line(run, workdir):
    """CATCHES: appending an error count to a syntax error, or reporting it as a type error; a parse
    failure is one rendered diagnostic and exit 1."""
    write(workdir, "let x = (1 +\n")
    r = run(["check", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "check_parse_error.golden")
    assert r.returncode == 1


def test_check_lex_error_unterminated_string(run, workdir):
    """CATCHES: a lexer that accepts an unterminated string literal, or underlines a different span
    than from the opening quote to the end of the line."""
    write(workdir, 'let s = "abc\n')
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b'error: unterminated string literal\n --> 1:9\n  |\n1 | let s = "abc\n'
                        b"  |         ^^^^\n")
    assert (r.stdout, r.returncode) == (b"", 1)


def test_check_typed_holes_are_notes_that_still_fail(run, workdir):
    """CATCHES: treating typed holes as errors (or ignoring them): each hole is a `note:` with its type
    and suggestions, listed after the errors, and both counts (`1 error`, `2 unfilled holes`) are
    printed with a non-zero exit."""
    write(workdir, "let h = ?x + 1\nlet bad = 1 + true\nlet g = ? + 2\n")
    r = run(["check", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "check_holes_and_error.golden")
    assert r.returncode == 1


def test_check_single_hole_without_errors(run, workdir):
    """CATCHES: exiting 0 when the only finding is a hole, or printing an `0 errors` line; a lone hole
    gives just the note and `1 unfilled hole`."""
    write(workdir, 'let greet name = String.concat ?prefix name\n')
    r = run(["check", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "check_one_hole.golden")
    assert r.returncode == 1


def test_check_columns_and_carets_count_bytes(run, workdir):
    """CATCHES: computing the reported column and caret indentation in characters instead of UTF-8
    bytes: two two-byte characters before the error move it to column 22."""
    write(workdir, 'let s = ("\u00e9\u00e9", 1 + true)\n')
    r = run(["check", "prog.pyfun"])
    assert r.stderr == ('error: expected int, found bool\n --> 1:22\n  |\n1 | let s = ("\u00e9\u00e9", 1 + true)\n'
                        "  |                      ^^^^\n\n1 error\n").encode()
    assert r.returncode == 1


def test_check_caret_width_counts_bytes_of_a_multibyte_span(run, workdir):
    """CATCHES: underlining a span by its character length: the string `"日本"` is 8 bytes, so it gets
    8 carets."""
    write(workdir, 'let s = "\u65e5\u672c" + 1\n')
    r = run(["check", "prog.pyfun"])
    assert r.stderr == ('error: `+` is numeric and does not concatenate strings \u2014 use `String.concat a b`\n'
                        ' --> 1:9\n  |\n1 | let s = "\u65e5\u672c" + 1\n  |         ^^^^^^^^\n\n1 error\n').encode()
    assert r.returncode == 1


def test_check_accepts_crlf_line_endings(run, workdir):
    """CATCHES: a lexer that chokes on `\\r\\n` line endings, or leaks the `\\r` into the excerpt line or the
    reported line/column."""
    write(workdir, "let a = 1\r\nlet b = a + true\r\n")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b"error: expected int, found bool\n --> 2:13\n  |\n2 | let b = a + true\n"
                        b"  |             ^^^^\n\n1 error\n")
    assert r.returncode == 1


def test_check_error_on_a_line_without_trailing_newline(run, workdir):
    """CATCHES: an off-by-one at end of file: the last line has no newline yet is excerpted in full."""
    write(workdir, "let a = 1\nlet b = a + true")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b"error: expected int, found bool\n --> 2:13\n  |\n2 | let b = a + true\n"
                        b"  |             ^^^^\n\n1 error\n")
    assert r.returncode == 1


def test_check_wide_line_numbers_widen_the_gutter(run, workdir):
    """CATCHES: a fixed-width gutter: an error on line 12 widens the `|` margin to the line number's width."""
    write(workdir, "let a = 1\n" * 11 + "let b = a + true\n")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == golden(__file__, "check_line12.golden")
    assert r.returncode == 1


def test_check_multiline_span_is_clamped_to_its_first_line(run, workdir):
    """CATCHES: underlining a multi-line span (a whole `match`) past the end of its first line, or
    excerpting more than that one line: the carets stop at the end of `match t:`."""
    write(workdir, "type T = A | B\nlet f t =\n  match t:\n    case A: 1\n")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b"error: non-exhaustive match: `B` is not matched\n --> 3:3\n  |\n3 |   match t:\n"
                        b"  |   ^^^^^^^^\n\n1 error\n")
    assert (r.stdout, r.returncode) == (b"", 1)


def test_check_error_at_end_of_input_on_the_same_line(run, workdir):
    """CATCHES: a zero-width span at end of file rendered with no caret or at the wrong column: it gets
    one caret just past the last character."""
    write(workdir, "let x =")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b"error: expected an expression, found end of input\n --> 1:8\n  |\n1 | let x =\n"
                        b"  |        ^\n")
    assert (r.stdout, r.returncode) == (b"", 1)


def test_check_error_at_end_of_input_after_a_newline(run, workdir):
    """CATCHES: locating an end-of-input error on the last non-empty line; after a trailing newline it is
    line 2, column 1, with an empty excerpt."""
    write(workdir, "let f x =\n")
    r = run(["check", "prog.pyfun"])
    assert r.stderr == (b"error: expected an expression, found end of input\n --> 2:1\n  |\n2 | \n  | ^\n")
    assert (r.stdout, r.returncode) == (b"", 1)


def test_check_does_not_write_anything(run, workdir):
    """CATCHES: `check` emitting Python or other files; it only reports."""
    write(workdir, SHAPES)
    r = run(["check", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"ok: no type errors\n", 0)
    assert sorted(p.name for p in workdir.iterdir()) == ["prog.pyfun"]


def test_check_reads_a_path_in_a_subdirectory(run, workdir):
    """CATCHES: resolving the input against anything but the working directory."""
    write_files(workdir, {"src/app/prog.pyfun": ADD})
    r = run(["check", "src/app/prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"ok: no type errors\n", 0)


# ====================================================================== compile


def test_compile_prints_python_to_stdout(run, workdir):
    """CATCHES: wrapping the output in banners, writing notes/success lines when there is nothing to
    say, or emitting different Python for a curried two-argument function and a direct call."""
    write(workdir, ADD)
    r = run(["compile", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (ADD_PY, b"", 0)


def test_compile_shapes_example(run, workdir):
    """CATCHES: differences in the lowering of an ADT to frozen dataclasses, a `match` to `match`/`case`,
    and an f-string, for the README's flagship example."""
    write(workdir, SHAPES)
    r = run(["compile", "prog.pyfun"])
    assert r.stdout == golden(__file__, "shapes_default.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


def test_compile_target_312_is_the_default(run, workdir):
    """CATCHES: `--target 3.12` producing anything other than the default emission."""
    write(workdir, SHAPES)
    r = run(["compile", "prog.pyfun", "--target", "3.12"])
    assert r.stdout == golden(__file__, "shapes_default.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


def test_compile_target_311_avoids_pep701_fstrings(run, workdir):
    """CATCHES: ignoring `--target 3.11`: nested same-quote f-string expressions must be rewritten so the
    output parses on Python 3.11/PyPy."""
    write(workdir, 'let xs = ["a", "b"]\nprint f"items: {String.join ", " xs}!"\n')
    default = run(["compile", "prog.pyfun"])
    old = run(["compile", "prog.pyfun", "--target", "3.11"])
    assert default.stdout == golden(__file__, "fstring_312.golden")
    assert old.stdout == golden(__file__, "fstring_311.golden")
    assert (default.stderr, default.returncode, old.stderr, old.returncode) == (b"", 0, b"", 0)


def test_compile_native_lowers_matches_to_isinstance_ladders(run, workdir):
    """CATCHES: ignoring `--native`, or a native mode that still emits `match` statements or omits the
    inferred annotations and the union alias of the sum type."""
    write(workdir, SHAPES)
    r = run(["compile", "prog.pyfun", "--native"])
    assert r.stdout == golden(__file__, "shapes_native.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


@pytest.mark.parametrize("order", [
    ["compile", "--native", "--target", "3.11", "prog.pyfun"],
    ["compile", "prog.pyfun", "--target", "3.11", "--native"],
    ["compile", "--target", "3.11", "prog.pyfun", "--native"],
])
def test_compile_native_and_target_combine_in_any_order(run, workdir, order):
    """CATCHES: flags that only work in one position, or `--native` and `--target 3.11` overriding each
    other instead of combining."""
    write(workdir, 'type T = A int | B\nlet show t =\n  match t:\n    case A n: f"A {n}"\n    case B: "B"\n'
                   'print (show (A 1))\n')
    r = run(order)
    assert r.stdout == golden(__file__, "native_311.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


def test_compile_last_target_wins(run, workdir):
    """CATCHES: the first `--target` sticking, or a repeated flag being rejected."""
    write(workdir, 'let xs = ["a", "b"]\nprint f"items: {String.join ", " xs}!"\n')
    r = run(["compile", "prog.pyfun", "--target", "3.11", "--target", "3.12"])
    assert r.stdout == golden(__file__, "fstring_312.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


@pytest.mark.parametrize("flag", ["-o", "--output"])
def test_compile_output_file(run, workdir, flag):
    """CATCHES: `-o`/`--output` printing the Python to stdout as well, a different confirmation line
    than `wrote <path>` on stderr, or file contents that differ from the stdout form."""
    write(workdir, ADD)
    r = run(["compile", "prog.pyfun", flag, "prog.py"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"wrote prog.py\n", 0)
    assert (workdir / "prog.py").read_bytes() == ADD_PY


def test_compile_output_flag_before_the_path(run, workdir):
    """CATCHES: requiring the path first: `-o out.py` may come before the input."""
    write(workdir, ADD)
    r = run(["compile", "-o", "out.py", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"wrote out.py\n", 0)
    assert (workdir / "out.py").read_bytes() == ADD_PY


def test_compile_output_overwrites_an_existing_file(run, workdir):
    """CATCHES: appending to, or refusing to replace, an existing output file."""
    write(workdir, ADD)
    (workdir / "out.py").write_text("stale contents that must disappear\n" * 20)
    r = run(["compile", "prog.pyfun", "-o", "out.py"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"wrote out.py\n", 0)
    assert (workdir / "out.py").read_bytes() == ADD_PY


def test_compile_last_output_wins(run, workdir):
    """CATCHES: writing every `-o` target, or the first one, when `-o` is repeated."""
    write(workdir, ADD)
    r = run(["compile", "prog.pyfun", "-o", "first.py", "-o", "second.py"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"wrote second.py\n", 0)
    assert sorted(p.name for p in workdir.iterdir()) == ["prog.pyfun", "second.py"]
    assert (workdir / "second.py").read_bytes() == ADD_PY


def test_compile_output_into_an_existing_subdirectory(run, workdir):
    """CATCHES: mangling a nested `-o` path, or echoing something other than the path as given."""
    write(workdir, ADD)
    (workdir / "build").mkdir()
    r = run(["compile", "prog.pyfun", "-o", "build/prog.py"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"wrote build/prog.py\n", 0)
    assert (workdir / "build" / "prog.py").read_bytes() == ADD_PY


def test_compile_output_into_missing_directory_fails(run, workdir):
    """CATCHES: silently creating parent directories for a single-file `-o` (the reference does not), or
    reporting the failure without the OS error."""
    write(workdir, ADD)
    r = run(["compile", "prog.pyfun", "-o", "build/out.py"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot write build/out.py: No such file or directory (os error 2)\n"
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["prog.pyfun"]


def test_compile_output_onto_a_directory_fails(run, workdir):
    """CATCHES: treating a single-module `-o` naming an existing directory as a project output dir."""
    write(workdir, ADD)
    (workdir / "out").mkdir()
    r = run(["compile", "prog.pyfun", "-o", "out"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot write out: Is a directory (os error 21)\n"
    assert r.returncode == 1


def test_compile_type_error_reports_only_the_first_error(run, workdir):
    """CATCHES: `compile` printing every error with a count like `check`, or emitting partial Python; it
    renders the first type error alone and exits 1 with nothing on stdout."""
    write(workdir, TWO_ERRORS)
    r = run(["compile", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "compile_first_error.golden")
    assert r.returncode == 1


def test_compile_error_does_not_create_the_output_file(run, workdir):
    """CATCHES: creating or truncating the `-o` file before the program has type-checked."""
    write(workdir, TWO_ERRORS)
    r = run(["compile", "prog.pyfun", "-o", "out.py"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "compile_first_error.golden")
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["prog.pyfun"]


def test_compile_refuses_a_typed_hole(run, workdir):
    """CATCHES: lowering a program that still contains a typed hole (there is no value to emit)."""
    write(workdir, "let f x = ?todo + x\n")
    r = run(["compile", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "compile_hole.golden")
    assert r.returncode == 1


def test_compile_reports_lowering_notes_on_stderr(run, workdir):
    """CATCHES: dropping lowering notes, printing them on stdout inside the Python, or rewording the
    tail-call note; the Python itself still goes to stdout and the exit status is 0."""
    write(workdir, NOTE_PROG)
    r = run(["compile", "prog.pyfun"])
    assert r.stdout == golden(__file__, "note_prog.golden")
    assert r.stderr == NOTE_LINE
    assert r.returncode == 0


def test_compile_notes_are_printed_before_the_wrote_line(run, workdir):
    """CATCHES: losing notes when compiling to a file, or printing them after the `wrote` line."""
    write(workdir, NOTE_PROG)
    r = run(["compile", "prog.pyfun", "-o", "out.py"])
    assert r.stdout == b""
    assert r.stderr == NOTE_LINE + b"wrote out.py\n"
    assert (workdir / "out.py").read_bytes() == golden(__file__, "note_prog.golden")
    assert r.returncode == 0


def test_compile_empty_file_emits_pass(run, workdir):
    """CATCHES: emitting an empty file for an empty program; the reference emits a lone `pass`."""
    write(workdir, "")
    r = run(["compile", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"pass\n", b"", 0)


def test_compile_parse_error(run, workdir):
    """CATCHES: a parse error rendered differently by `compile` than by `check`."""
    write(workdir, "let x = (1 +\n")
    r = run(["compile", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "check_parse_error.golden")
    assert r.returncode == 1


def test_compile_single_file_inlines_the_option_classes(run, workdir):
    """CATCHES: a single file importing a `_pyfun_rt` runtime module (only projects use one): the
    Option classes are emitted inline."""
    write(workdir, "let x = Some 1\nprint (Option.withDefault 0 x)\n")
    r = run(["compile", "prog.pyfun"])
    assert r.stdout == golden(__file__, "option_inline.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


# ====================================================================== run


def test_run_executes_the_program(run, workdir):
    """CATCHES: `run` printing the compiled Python instead of executing it, or adding output of its own."""
    write(workdir, SHAPES)
    r = run(["run", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"Ada: 6.0\n", b"", 0)


@pytest.mark.parametrize("extra, expected", [
    ([], b"[]\n"),
    (["hello", "42"], b"['hello', '42']\n"),
    (["--", "hello", "42"], b"['hello', '42']\n"),
    (["--", "--", "x"], b"['--', 'x']\n"),
    (["a", "--", "b"], b"['a', '--', 'b']\n"),
    (["--"], b"[]\n"),
    (["-o", "--help", "--native"], b"['-o', '--help', '--native']\n"),
])
def test_run_forwards_program_arguments(run, workdir, extra, expected):
    """CATCHES: swallowing or reinterpreting arguments after the path: they reach `sys.argv[1:]`
    verbatim (even pyfun's own flags), and only one *leading* `--` is consumed as a separator."""
    write(workdir, ARGV_PROG)
    r = run(["run", "prog.pyfun", *extra])
    assert (r.stdout, r.stderr, r.returncode) == (expected, b"", 0)


def test_run_stages_the_program_as_pyfun_main(run, workdir):
    """CATCHES: staging the script under the source's own name (a `json.pyfun` would then shadow the
    stdlib `json` it imports) or anywhere but a private temp directory holding only the script."""
    write(workdir, """extern import sys
extern import os
extern getArgv : unit -> List string = sys.argv.copy
extern pure baseName : string -> string = os.path.basename
extern pure dirName : string -> string = os.path.dirname
extern listDir : string -> List string = os.listdir
extern pure dumps : List string -> string = json.dumps
let script = Option.withDefault "" (List.head (getArgv ()))
print (baseName script)
print (dumps (listDir (dirName script)))
""", name="json.pyfun")
    r = run(["run", "json.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b'_pyfun_main.py\n["_pyfun_main.py"]\n', b"", 0)


def test_run_cleans_up_its_temp_directory(run, workdir):
    """CATCHES: leaving the staged script behind in the temp directory (`TMPDIR`) after the run."""
    write(workdir, ADD)
    (workdir / "tmp").mkdir()
    r = run(["run", "prog.pyfun"], env_overrides={"TMPDIR": str(workdir / "tmp")})
    assert (r.stdout, r.stderr, r.returncode) == (b"3\n", b"", 0)
    assert sorted(p.name for p in (workdir / "tmp").iterdir()) == []


def test_run_reports_an_unusable_temp_directory(run, workdir):
    """CATCHES: crashing (or running from somewhere else) when the temp directory cannot be created."""
    write(workdir, ADD)
    (workdir / "notadir").write_text("a file, not a directory\n")
    r = run(["run", "prog.pyfun"], env_overrides={"TMPDIR": str(workdir / "notadir")})
    assert r.stdout == b""
    assert r.stderr == b"error: cannot create temp dir: Not a directory (os error 20)\n"
    assert r.returncode == 1


def test_run_keeps_the_callers_working_directory(run, workdir):
    """CATCHES: running the program from its staging directory, so relative paths in the program would
    no longer mean what they meant on the command line."""
    write_files(workdir, {"data/payload.txt": "payload from the caller's directory\n", "prog.pyfun": """
extern readFile : string -> string = pathlib.Path.read_text
extern pure path : string -> string = pathlib.Path
print (readFile (path "data/payload.txt"))
"""})
    r = run(["run", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"payload from the caller's directory\n\n", b"", 0)


def test_run_gives_the_program_its_stdin(run, workdir):
    """CATCHES: feeding the program's source through stdin (`python -`), which would leave nothing for
    the program's own `input` calls."""
    write(workdir, """extern readLine : string -> string = builtins.input
let name = readLine "name? "
print f"hi {name}"
""")
    r = run(["run", "prog.pyfun"], input="bob\n")
    assert (r.stdout, r.stderr, r.returncode) == (b"name? hi bob\n", b"", 0)


def test_run_passes_the_programs_stderr_through(run, workdir):
    """CATCHES: capturing or merging the program's stderr into stdout; both streams are inherited."""
    write(workdir, 'extern import sys\nextern warn : string -> int = sys.stderr.write\nlet n = warn "to stderr\\n"\n'
                   'print "to stdout"\n')
    r = run(["run", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"to stdout\n", b"to stderr\n", 0)


def test_run_entry_in_a_subdirectory(run, workdir):
    """CATCHES: resolving the program path against the staging directory, or changing into the source's
    directory, when the entry is given as `src/prog.pyfun`."""
    write_files(workdir, {"src/prog.pyfun": ARGV_PROG})
    r = run(["run", "src/prog.pyfun", "one"])
    assert (r.stdout, r.stderr, r.returncode) == (b"['one']\n", b"", 0)


def test_run_failing_program_exits_one(run, workdir):
    """CATCHES: propagating the program's own exit status (3) instead of the reference's 1, or exiting 0
    when the program fails; output produced before the failure still appears."""
    write(workdir, 'extern quit : int -> unit = sys.exit\nprint "before"\nquit 3\n')
    r = run(["run", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"before\n", b"", 1)


def test_run_refuses_ill_typed_programs(run, workdir):
    """CATCHES: running a program that does not type-check; the compiler is the gatekeeper and nothing
    executes (the `print` before the error must not run)."""
    write(workdir, 'print "must not run"\nlet r = 1 + true\n')
    r = run(["run", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == (b"error: expected int, found bool\n --> 2:13\n  |\n2 | let r = 1 + true\n"
                        b"  |             ^^^^\n")
    assert r.returncode == 1


def test_run_refuses_a_typed_hole(run, workdir):
    """CATCHES: running a program that still has a typed hole; `run` reports it like `compile` does."""
    write(workdir, "let f x = ?todo + x\nprint (f 1)\n")
    r = run(["run", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "compile_hole.golden")
    assert r.returncode == 1


def test_run_type_checks_before_looking_for_python(run, workdir):
    """CATCHES: looking up the interpreter before type-checking: with no Python at all, an ill-typed
    program still gets its type error, not the missing-interpreter error."""
    write(workdir, "let r = 1 + true\n")
    (workdir / "emptybin").mkdir()
    r = run(["run", "prog.pyfun"], env_overrides={"PATH": str(workdir / "emptybin")})
    assert r.stdout == b""
    assert r.stderr == (b"error: expected int, found bool\n --> 1:13\n  |\n1 | let r = 1 + true\n"
                        b"  |             ^^^^\n")
    assert r.returncode == 1


def test_run_reports_notes_before_running(run, workdir):
    """CATCHES: hiding lowering notes during `run` or printing them on stdout among the program output."""
    write(workdir, NOTE_PROG)
    r = run(["run", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"3\n", NOTE_LINE, 0)


def test_run_uses_pyfun_python(run, workdir):
    """CATCHES: ignoring the documented `PYFUN_PYTHON` variable: the named interpreter is the one that
    runs the staged script, with the program's arguments after it."""
    write(workdir, ADD)
    make_script(workdir / "mypython", 'echo "custom interpreter, $# args, last: $2" >&2\nexec python3 "$@"\n')
    r = run(["run", "prog.pyfun", "x"], env_overrides={"PYFUN_PYTHON": str(workdir / "mypython")})
    assert (r.stdout, r.stderr, r.returncode) == (b"3\n", b"custom interpreter, 2 args, last: x\n", 0)


def test_run_empty_pyfun_python_falls_back_to_path(run, workdir):
    """CATCHES: treating an empty `PYFUN_PYTHON` as an interpreter name instead of falling back to
    `python`/`python3` on PATH."""
    write(workdir, ADD)
    r = run(["run", "prog.pyfun"], env_overrides={"PYFUN_PYTHON": ""})
    assert (r.stdout, r.stderr, r.returncode) == (b"3\n", b"", 0)


def test_run_missing_pyfun_python_reports_the_os_error(run, workdir):
    """CATCHES: falling back silently when `PYFUN_PYTHON` names a missing program, or not quoting it."""
    write(workdir, ADD)
    r = run(["run", "prog.pyfun"], env_overrides={"PYFUN_PYTHON": "./no-such-python"})
    assert r.stdout == b""
    assert r.stderr == b"error: `./no-such-python` did not finish: No such file or directory (os error 2)\n"
    assert r.returncode == 1


def test_run_without_any_python_on_path(run, workdir):
    """CATCHES: a crash or a vague message when neither `python` nor `python3` is on PATH; the program
    still type-checks first."""
    write(workdir, ADD)
    (workdir / "emptybin").mkdir()
    r = run(["run", "prog.pyfun"], env_overrides={"PATH": str(workdir / "emptybin")})
    assert r.stdout == b""
    assert r.stderr == b"error: no Python interpreter found on PATH (tried `python`, `python3`)\n"
    assert r.returncode == 1


def test_run_prefers_python_over_python3(run, workdir):
    """CATCHES: probing `python3` before `python`: when both are on PATH the first candidate, `python`,
    runs the program."""
    write(workdir, ADD)
    bindir = workdir / "bin"
    bindir.mkdir()
    real = None
    for d in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep):
        if os.access(os.path.join(d, "python3"), os.X_OK):
            real = os.path.join(d, "python3")
            break
    assert real is not None, "python3 must be available to run this test"
    make_script(bindir / "python", f'echo "via python" >&2\nexec {real} "$@"\n')
    make_script(bindir / "python3", 'echo "via python3" >&2\nexit 7\n')
    r = run(["run", "prog.pyfun"], env_overrides={"PATH": str(bindir)})
    assert (r.stdout, r.stderr, r.returncode) == (b"3\n", b"via python\n", 0)


# ====================================================================== parse


def test_parse_prints_the_canonical_form(run, workdir):
    """CATCHES: a pretty-printer that does not fully parenthesise applications and operators, re-indents
    match arms differently, or prints the f-string/ADT forms differently."""
    write(workdir, SHAPES)
    r = run(["parse", "prog.pyfun"])
    assert r.stdout == golden(__file__, "shapes_parse.golden")
    assert (r.stderr, r.returncode) == (b"", 0)


def test_parse_is_a_fixed_point(run, workdir):
    """CATCHES: a canonical form that is not stable: parsing the printed form must print it unchanged."""
    write(workdir, SHAPES)
    first = run(["parse", "prog.pyfun"])
    (workdir / "again.pyfun").write_bytes(first.stdout)
    second = run(["parse", "again.pyfun"])
    assert second.stdout == first.stdout == golden(__file__, "shapes_parse.golden")
    assert (second.stderr, second.returncode) == (b"", 0)


def test_parse_does_not_type_check(run, workdir):
    """CATCHES: `parse` rejecting a syntactically valid but ill-typed program; it only parses."""
    write(workdir, 'let x = 1 + "s"\n')
    r = run(["parse", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b'let x = (1 + "s")\n', b"", 0)


def test_parse_empty_file_prints_nothing(run, workdir):
    """CATCHES: printing a blank line or `pass` for an empty (or comment-only) module (that is compile's
    job), while a one-binding module prints exactly that binding."""
    write(workdir, "")
    r = run(["parse", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"", 0)
    write(workdir, "# a comment and nothing else\n")
    r = run(["parse", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"", 0)
    write(workdir, "let x   =  1 # trailing comment\n")
    r = run(["parse", "prog.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"let x = 1\n", b"", 0)


def test_parse_reports_syntax_errors(run, workdir):
    """CATCHES: a `parse` that prints a partial tree, or renders the syntax error differently than `check`."""
    write(workdir, "let x = (1 +\n")
    r = run(["parse", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "check_parse_error.golden")
    assert r.returncode == 1
