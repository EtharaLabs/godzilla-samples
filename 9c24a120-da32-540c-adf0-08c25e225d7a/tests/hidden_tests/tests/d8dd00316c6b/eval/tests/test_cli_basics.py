"""Command-line surface: help, version, argument errors, `-o`, `--target` and the bare-path shorthand."""

from conftest import golden_name, listing, read_golden, run_case, transcript

SHAPES = (
    "type Shape = Circle float | Rect float float\n"
    "\n"
    "let area s =\n"
    "  match s:\n"
    "    case Circle r: 3.14159 * r * r\n"
    "    case Rect w h: w * h\n"
    "\n"
    "print (area (Circle 2.0))\n"
    "print (area (Rect 2.0 3.5))\n"
)


def _transcript_matches(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


# ---------------------------------------------------------------- help / version

NO_ARGS_CASE = {"id": "no_args_prints_usage", "args": []}


def test_no_arguments_prints_usage_to_stderr(run, workdir):
    """CATCHES: a bare `pyfun` that prints nothing, prints the usage to stdout instead of
    stderr, omits a subcommand from the usage table, or exits non-zero."""
    proc, _ = run_case(run, workdir, NO_ARGS_CASE)
    assert transcript(proc) == read_golden(__file__, "no_args_prints_usage")


def test_version_flag(run):
    """CATCHES: a wrong version number, extra decoration, or the version written to stderr."""
    proc = run(["--version"])
    assert transcript(proc) == "exit: 0\n--- stdout ---\npyfun 0.10.0\n--- stderr ---\n"


# ---------------------------------------------------------------- missing arguments

MISSING_PATH_CASES = [
    {"id": "check_without_path", "args": ["check"]},
    {"id": "compile_without_path", "args": ["compile"]},
    {"id": "compile_native_without_path", "args": ["compile", "--native"]},
    {"id": "run_without_path", "args": ["run"]},
    {"id": "parse_without_path", "args": ["parse"]},
]


def test_check_without_a_path(run, workdir):
    """CATCHES: `check` with no file that panics, succeeds, or words the error differently."""
    _transcript_matches(run, workdir, MISSING_PATH_CASES[0])


def test_compile_without_a_path(run, workdir):
    """CATCHES: `compile` with no file that reads stdin, panics or exits 0 instead of
    reporting "`compile` needs a file path"."""
    _transcript_matches(run, workdir, MISSING_PATH_CASES[1])


def test_compile_with_only_a_flag(run, workdir):
    """CATCHES: an argument parser that treats `--native` as the file path."""
    _transcript_matches(run, workdir, MISSING_PATH_CASES[2])


def test_run_without_a_path(run, workdir):
    """CATCHES: `run` with no file that starts Python anyway or reports a different error."""
    _transcript_matches(run, workdir, MISSING_PATH_CASES[3])


def test_parse_without_a_path(run, workdir):
    """CATCHES: `parse` with no file that succeeds silently or reports a different error."""
    _transcript_matches(run, workdir, MISSING_PATH_CASES[4])


# ---------------------------------------------------------------- compile argument errors

COMPILE_ARG_CASES = [
    {"id": "compile_extra_positional", "files": {"ok.pyfun": "let x = 1\n"},
     "args": ["compile", "ok.pyfun", "extra.pyfun"]},
    {"id": "compile_o_without_value", "files": {"ok.pyfun": "let x = 1\n"},
     "args": ["compile", "ok.pyfun", "-o"]},
    {"id": "compile_target_without_value", "files": {"ok.pyfun": "let x = 1\n"},
     "args": ["compile", "ok.pyfun", "--target"]},
    {"id": "compile_target_unknown_version", "files": {"ok.pyfun": "let x = 1\n"},
     "args": ["compile", "ok.pyfun", "--target", "3.10"]},
]


def test_compile_rejects_a_second_path(run, workdir):
    """CATCHES: a parser that silently ignores (or compiles) a second positional argument."""
    _transcript_matches(run, workdir, COMPILE_ARG_CASES[0])


def test_compile_dash_o_needs_a_value(run, workdir):
    """CATCHES: a dangling `-o` that writes to a default file or prints to stdout."""
    _transcript_matches(run, workdir, COMPILE_ARG_CASES[1])


def test_compile_target_needs_a_value(run, workdir):
    """CATCHES: a dangling `--target` that falls back to the default target silently."""
    _transcript_matches(run, workdir, COMPILE_ARG_CASES[2])


def test_compile_target_rejects_unknown_versions(run, workdir):
    """CATCHES: accepting `--target 3.10` (or any version other than 3.11/3.12) or a
    differently worded rejection."""
    _transcript_matches(run, workdir, COMPILE_ARG_CASES[3])


FLAGS_FIRST_CASE = {"id": "compile_flags_before_path", "files": {"shapes.pyfun": SHAPES},
                    "args": ["compile", "--target", "3.12", "-o", "out.py", "shapes.pyfun"],
                    "outputs": ["out.py"]}


def test_compile_flags_may_come_before_the_path(run, workdir):
    """CATCHES: an argument parser that requires the path first, so `--target 3.12 -o out.py file`
    is rejected or writes the wrong file."""
    _transcript_matches(run, workdir, FLAGS_FIRST_CASE)


# ---------------------------------------------------------------- reading inputs

READ_CASES = [
    {"id": "compile_missing_file", "args": ["compile", "nosuch.pyfun"]},
    {"id": "check_missing_file", "args": ["check", "nosuch.pyfun"]},
    {"id": "parse_missing_file", "args": ["parse", "nosuch.pyfun"]},
    {"id": "run_missing_file", "args": ["run", "nosuch.pyfun"]},
    {"id": "shorthand_missing_file", "args": ["nosuch.pyfun"]},
    {"id": "compile_a_directory", "files": {"adir/keep.txt": "x\n"}, "args": ["compile", "adir"]},
    {"id": "check_non_utf8_file", "bytes": {"latin1.pyfun": b'let caf\xe9 = "x"\n'}, "args": ["check", "latin1.pyfun"]},
]


def test_compile_reports_a_missing_file(run, workdir):
    """CATCHES: a missing input that panics, is treated as an empty program, or is reported
    without the OS error text."""
    _transcript_matches(run, workdir, READ_CASES[0])


def test_check_reports_a_missing_file(run, workdir):
    """CATCHES: `check` printing "ok" or a different message for a file that does not exist."""
    _transcript_matches(run, workdir, READ_CASES[1])


def test_parse_reports_a_missing_file(run, workdir):
    """CATCHES: `parse` on a missing file exiting 0 or printing an empty canonical form."""
    _transcript_matches(run, workdir, READ_CASES[2])


def test_run_reports_a_missing_file(run, workdir):
    """CATCHES: `run` on a missing file launching Python or reporting a different error."""
    _transcript_matches(run, workdir, READ_CASES[3])


def test_bare_path_shorthand_reports_a_missing_file(run, workdir):
    """CATCHES: treating an unknown first argument as an unknown subcommand instead of as the
    `compile` shorthand's path."""
    _transcript_matches(run, workdir, READ_CASES[4])


def test_compile_a_directory_is_a_read_error(run, workdir):
    """CATCHES: a directory argument that is walked, compiled as a project, or crashes,
    instead of failing with the OS read error."""
    _transcript_matches(run, workdir, READ_CASES[5])


def test_check_rejects_a_file_that_is_not_utf8(run, workdir):
    """CATCHES: lossy decoding of a non-UTF-8 source (so a Latin-1 file is checked) instead
    of refusing it with the "stream did not contain valid UTF-8" read error."""
    _transcript_matches(run, workdir, READ_CASES[6])


# ---------------------------------------------------------------- shorthand and output files

SHORTHAND_COMPILES_CASE = {"id": "shorthand_compiles", "files": {"shapes.pyfun": SHAPES}, "args": ["shapes.pyfun"]}


def test_bare_path_is_compile_to_stdout(run, workdir):
    """CATCHES: a bare `pyfun file.pyfun` that type-checks only, runs the program, or emits
    Python different from `pyfun compile file.pyfun`."""
    proc = _transcript_matches(run, workdir, SHORTHAND_COMPILES_CASE)
    assert proc.stdout == run(["compile", "shapes.pyfun"]).stdout


COMPILE_DASH_O_CASE = {"id": "compile_dash_o", "files": {"shapes.pyfun": SHAPES},
        "args": ["compile", "shapes.pyfun", "-o", "shapes.py"], "outputs": ["shapes.py"]}


def test_compile_dash_o_writes_the_file_and_reports_it(run, workdir):
    """CATCHES: `-o` that still prints the Python to stdout, writes a different program than
    stdout mode, or forgets the "wrote <path>" confirmation on stderr."""
    _transcript_matches(run, workdir, COMPILE_DASH_O_CASE)
    assert (workdir / "shapes.py").read_bytes() == run(["compile", "shapes.pyfun"]).stdout


COMPILE_DASH_O_OVERWRITE_CASE = {"id": "compile_dash_o_overwrite",
        "files": {"shapes.pyfun": SHAPES, "shapes.py": "# stale output that must disappear\n" * 40},
        "args": ["compile", "shapes.pyfun", "-o", "shapes.py"], "outputs": ["shapes.py"]}


def test_compile_dash_o_overwrites_an_existing_file(run, workdir):
    """CATCHES: an `-o` that appends to, or refuses to replace, an existing output file."""
    _transcript_matches(run, workdir, COMPILE_DASH_O_OVERWRITE_CASE)


COMPILE_DASH_O_MISSING_DIR_CASE = {"id": "compile_dash_o_missing_dir", "files": {"shapes.pyfun": SHAPES},
        "args": ["compile", "shapes.pyfun", "-o", "nodir/shapes.py"]}


def test_compile_dash_o_into_a_missing_directory_fails(run, workdir):
    """CATCHES: a single-file `-o` that creates missing parent directories or reports success
    when the file could not be written."""
    _transcript_matches(run, workdir, COMPILE_DASH_O_MISSING_DIR_CASE)
    assert listing(workdir) == "shapes.pyfun\n"


COMPILE_ERROR_NO_OUTPUT_CASE = {"id": "compile_error_no_output", "files": {"bad.pyfun": 'let x = 1 + "one"\n'},
        "args": ["compile", "bad.pyfun", "-o", "bad.py"]}


def test_compile_error_writes_no_output_file(run, workdir):
    """CATCHES: a compiler that writes a partial `-o` file even though type-checking failed."""
    _transcript_matches(run, workdir, COMPILE_ERROR_NO_OUTPUT_CASE)
    assert listing(workdir) == "bad.pyfun\n"


TARGET_311_PLAIN_CASE = {"id": "target_311_plain", "files": {"shapes.pyfun": SHAPES},
        "args": ["compile", "shapes.pyfun", "--target", "3.11"]}


def test_target_311_matches_default_when_no_fstring_needs_rewriting(run, workdir):
    """CATCHES: a `--target 3.11` that changes code which has no PEP 701 f-string, or a
    `--target 3.12` that differs from the default target."""
    proc = _transcript_matches(run, workdir, TARGET_311_PLAIN_CASE)
    assert proc.stdout == run(["compile", "shapes.pyfun", "--target", "3.12"]).stdout
    assert proc.stdout == run(["compile", "shapes.pyfun"]).stdout


# ---------------------------------------------------------------- input encodings and layout

ENCODING_CASES = [
    {"id": "empty_file_compiles_to_nothing", "files": {"empty.pyfun": ""}, "args": ["compile", "empty.pyfun"]},
    {"id": "empty_file_checks", "files": {"empty.pyfun": ""}, "args": ["check", "empty.pyfun"]},
    {"id": "empty_file_parses", "files": {"empty.pyfun": "# only comments\n\n## a doc comment with no declaration\n"}, "args": ["parse", "empty.pyfun"]},
    {"id": "comments_only_file", "files": {"c.pyfun": "# just a comment\n\n# another\n"},
     "args": ["compile", "c.pyfun"]},
    {"id": "crlf_line_endings", "files": {"crlf.pyfun": SHAPES.replace("\n", "\r\n")},
     "args": ["compile", "crlf.pyfun"]},
    {"id": "no_trailing_newline", "files": {"nl.pyfun": SHAPES.rstrip("\n")}, "args": ["run", "nl.pyfun"]},
    {"id": "unicode_strings_and_comments",
     "files": {"u.pyfun": '# café ☕ — naïve\nlet greet = "héllo, wörld ✓"\nprint greet\nprint (String.len greet)\nprint (String.upper "straße")\n'},
     "args": ["run", "u.pyfun"]},
    {"id": "unicode_compile", "files": {"u.pyfun": 'let s = "日本語 ✓ \\u{1F600}"\nlet n = String.len s\n'},
     "args": ["compile", "u.pyfun"]},
    {"id": "tab_indentation", "files": {"tab.pyfun": "let f x =\n\tlet y = x + 1\n\ty * 2\nprint (f 3)\n"},
     "args": ["check", "tab.pyfun"]},
    {"id": "utf8_bom", "files": {"bom.pyfun": "\ufefflet x = 1\nprint x\n"}, "args": ["compile", "bom.pyfun"]},
]


def test_empty_file_compiles_to_empty_python(run, workdir):
    """CATCHES: an empty source that is rejected, or that emits a header/boilerplate."""
    _transcript_matches(run, workdir, ENCODING_CASES[0])


def test_empty_file_type_checks(run, workdir):
    """CATCHES: `check` on an empty file reporting an error or a different "ok" line."""
    _transcript_matches(run, workdir, ENCODING_CASES[1])


def test_comment_only_file_parses_to_nothing(run, workdir):
    """CATCHES: `parse` that echoes comments (or a dangling doc comment) into the canonical
    form, or fails on a file with no declarations, while `compile` of the same file still
    emits the placeholder `pass` statement."""
    _transcript_matches(run, workdir, ENCODING_CASES[2])
    assert transcript(run(["compile", "empty.pyfun"])) == "exit: 0\n--- stdout ---\npass\n--- stderr ---\n"


def test_comment_only_file(run, workdir):
    """CATCHES: comments that leak into the Python output or confuse the offside rule."""
    _transcript_matches(run, workdir, ENCODING_CASES[3])


def test_crlf_source_compiles_like_lf(run, workdir):
    """CATCHES: a lexer that treats `\\r` as part of a token or mis-measures indentation in a
    Windows-style file, so CRLF input fails or emits different Python than LF input."""
    proc = _transcript_matches(run, workdir, ENCODING_CASES[4])
    (workdir / "lf.pyfun").write_text(SHAPES)
    assert proc.stdout == run(["compile", "lf.pyfun"]).stdout


def test_source_without_trailing_newline_runs(run, workdir):
    """CATCHES: a lexer that needs a final newline to close the last statement or block."""
    _transcript_matches(run, workdir, ENCODING_CASES[5])


def test_unicode_strings_and_comments_run(run, workdir):
    """CATCHES: byte-oriented string handling: wrong `String.len` for multi-byte characters,
    mangled non-ASCII literals in the emitted Python, or comments that break on UTF-8."""
    _transcript_matches(run, workdir, ENCODING_CASES[6])


def test_unicode_escapes_compile(run, workdir):
    """CATCHES: `\\u{...}` escapes that are emitted verbatim or decoded to the wrong code point."""
    _transcript_matches(run, workdir, ENCODING_CASES[7])


def test_tab_indentation_is_reported(run, workdir):
    """CATCHES: silently accepting (or crashing on) tab characters in indentation instead of
    the reference's diagnostic."""
    _transcript_matches(run, workdir, ENCODING_CASES[8])


def test_byte_order_mark(run, workdir):
    """CATCHES: different handling of a leading UTF-8 byte-order mark than the reference."""
    _transcript_matches(run, workdir, ENCODING_CASES[9])


# ---------------------------------------------------------------- large and deeply nested inputs

def _many_bindings(n=3000):
    src = "".join(f"let v{i} = {i} * 2\n" for i in range(n))
    return src + "let total = List.sum [" + ", ".join(f"v{i}" for i in range(0, n, 7)) + "]\nprint total\n"


def _deep_parens(depth=150):
    return "let x = " + "(" * depth + "1" + " + 1)" * depth + "\nprint x\n"


def _elif_ladder(n=60):
    body = "".join("  " * (k + 1) + f"if n == {k} then {k}\n" + "  " * (k + 1) + "else\n" for k in range(n))
    return "let f n =\n" + body + "  " * (n + 1) + "-1\nprint (f 59)\nprint (f 99)\n"


LARGE_CASES = [
    {"id": "large_many_bindings_run", "files": {"big.pyfun": _many_bindings()}, "args": ["run", "big.pyfun"]},
    {"id": "large_many_bindings_compile", "files": {"big.pyfun": _many_bindings()}, "args": ["compile", "big.pyfun"]},
    {"id": "large_deep_parentheses", "files": {"deep.pyfun": _deep_parens()}, "args": ["run", "deep.pyfun"]},
    {"id": "large_deep_parentheses_parse", "files": {"deep.pyfun": _deep_parens()}, "args": ["parse", "deep.pyfun"]},
    {"id": "large_long_string_literal", "files": {"s.pyfun": "let s = \"" + "ab\\n" * 20000 + "\"\nprint (String.len s)\n"},
     "args": ["run", "s.pyfun"]},
    {"id": "large_nested_else_if_ladder", "files": {"ladder.pyfun": _elif_ladder()}, "args": ["compile", "ladder.pyfun"]},
    {"id": "large_nested_else_if_ladder_run", "files": {"ladder.pyfun": _elif_ladder()}, "args": ["run", "ladder.pyfun"]},
]


def test_three_thousand_bindings_run(run, workdir):
    """CATCHES: quadratic blow-ups or stack exhaustion on a long program, or a wrong sum."""
    _transcript_matches(run, workdir, LARGE_CASES[0])


def test_three_thousand_bindings_compile(run, workdir):
    """CATCHES: dropped, reordered or renamed bindings in a long program's Python."""
    _transcript_matches(run, workdir, LARGE_CASES[1])


def test_deeply_parenthesised_expression_runs(run, workdir):
    """CATCHES: a recursive-descent parser or lowering that overflows on 150 nested parens."""
    _transcript_matches(run, workdir, LARGE_CASES[2])


def test_deeply_parenthesised_expression_parses(run, workdir):
    """CATCHES: a pretty-printer that loses or adds parentheses in deep nesting."""
    _transcript_matches(run, workdir, LARGE_CASES[3])


def test_a_sixty_thousand_character_string(run, workdir):
    """CATCHES: escape handling or literal emission that breaks on very long strings."""
    _transcript_matches(run, workdir, LARGE_CASES[4])


def test_a_sixty_level_else_if_ladder_compiles_to_elif(run, workdir):
    """CATCHES: nested `else if` chains that are not flattened into `elif`, or that nest
    indentation sixty levels deep in the emitted Python."""
    _transcript_matches(run, workdir, LARGE_CASES[5])


def test_a_sixty_level_else_if_ladder_runs(run, workdir):
    """CATCHES: wrong branch selection at the bottom (and past the end) of a long ladder."""
    _transcript_matches(run, workdir, LARGE_CASES[6])


# ---------------------------------------------------------------- source from standard input

STDIN_SOURCE_CASES = [
    {"id": "compile_from_dev_stdin", "args": ["compile", "/dev/stdin"], "stdin": "let x = 1\nprint (x + 1)\n"},
    {"id": "check_from_dev_stdin", "args": ["check", "/dev/stdin"], "stdin": "let x = 1 + true\nlet y = \"a\" * 2\n"},
    {"id": "parse_from_dev_stdin", "args": ["parse", "/dev/stdin"], "stdin": "let f a b = a |> b >> b\n"},
    {"id": "dash_is_a_file_name", "args": ["compile", "-"], "stdin": "let x = 1\n"},
]


def test_compile_reads_a_program_from_dev_stdin(run, workdir):
    """CATCHES: a compiler that cannot read its source from a pipe (e.g. one that stats or
    mmaps the file and fails on /dev/stdin)."""
    _transcript_matches(run, workdir, STDIN_SOURCE_CASES[0])


def test_check_reads_a_program_from_dev_stdin(run, workdir):
    """CATCHES: diagnostics rendered without the piped source's lines under the caret."""
    _transcript_matches(run, workdir, STDIN_SOURCE_CASES[1])


def test_parse_reads_a_program_from_dev_stdin(run, workdir):
    """CATCHES: `parse` that cannot read from a pipe or prints a different canonical form."""
    _transcript_matches(run, workdir, STDIN_SOURCE_CASES[2])


def test_dash_is_not_stdin(run, workdir):
    """CATCHES: treating `-` as standard input; the reference reads a file literally named `-`."""
    _transcript_matches(run, workdir, STDIN_SOURCE_CASES[3])


# ---------------------------------------------------------------- extra arguments

EXTRA_ARG_CASES = [
    {"id": "shorthand_ignores_trailing_arguments", "files": {"one.pyfun": "print (1 + 1)\n"},
     "args": ["one.pyfun", "-o", "out.py", "--native"]},
    {"id": "check_ignores_trailing_arguments", "files": {"one.pyfun": "print (1 + 1)\n"},
     "args": ["check", "one.pyfun", "two.pyfun", "--native"]},
    {"id": "parse_ignores_trailing_arguments", "files": {"one.pyfun": "print (1 + 1)\n"},
     "args": ["parse", "one.pyfun", "-o", "x"]},
]


def test_the_shorthand_only_takes_a_path(run, workdir):
    """CATCHES: a bare-path shorthand that honours `-o`/`--native` (the reference compiles the
    path to stdout and ignores everything after it, writing no file)."""
    _transcript_matches(run, workdir, EXTRA_ARG_CASES[0])
    assert listing(workdir) == "one.pyfun\n"


def test_check_ignores_arguments_after_the_path(run, workdir):
    """CATCHES: a `check` that rejects, or also checks, arguments after its one path."""
    _transcript_matches(run, workdir, EXTRA_ARG_CASES[1])


def test_parse_ignores_arguments_after_the_path(run, workdir):
    """CATCHES: a `parse` that rejects or interprets arguments after its one path."""
    _transcript_matches(run, workdir, EXTRA_ARG_CASES[2])
    assert listing(workdir) == "one.pyfun\n"
