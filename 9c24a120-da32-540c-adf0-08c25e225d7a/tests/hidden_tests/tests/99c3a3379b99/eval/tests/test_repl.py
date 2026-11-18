"""Black-box tests for `pyfun repl`: the line-oriented session over one long-lived python3 worker.

Each test pipes a whole session into stdin and compares the exact stdout (banner, `pyfun> ` and
`...... ` prompts included), the exact stderr and the exit code against output captured from the
reference binary (eval/test_resources/test_repl/).
"""

import os
import re
import shutil

import pytest

from conftest import golden

# A traceback's frame lines (`  File "<string>", line 15, in <module>`, plus source/caret lines on
# Pythons that can show them) vary across Python versions; its header and final exception line do not.
TRACEBACK_HEADER = b"Traceback (most recent call last):"
# The text after these prefixes is an OS / runtime I/O error description (e.g. an EOF or a broken
# pipe), so tests pin the prefix and the line structure, not the wording of the I/O error.
IO_ERROR_LINE = re.compile(
    rb"^(python worker error|python worker failed again|cannot start python worker"
    rb"|cannot restart python worker|input error): .*$",
    re.M,
)


def without_traceback_frames(stdout: bytes) -> bytes:
    """Drop the indented frame lines of every Python traceback, keeping its header and exception line."""
    kept, in_traceback = [], False
    for line in stdout.split(b"\n"):
        if line.endswith(TRACEBACK_HEADER):
            in_traceback = True
        elif in_traceback and line.startswith(b" "):
            continue
        else:
            in_traceback = False
        kept.append(line)
    return b"\n".join(kept)


def without_io_error_detail(stderr: bytes) -> bytes:
    """`python worker error: failed to fill whole buffer` -> `python worker error: <detail>`."""
    return IO_ERROR_LINE.sub(rb"\1: <detail>", stderr)


# Bindings that let an entry kill the worker process (`die`) or remember state across worker
# lifetimes in the filesystem (`exists`/`mkdir` on a marker directory in the work dir).
CRASH_EXTERNS = (
    b"extern import os.path\n"
    b"extern exists: string -> bool = os.path.exists\n"
    b"extern mkdir: string -> unit = os.mkdir\n"
    b"extern die: int -> unit = os._exit\n"
)


# ----------------------------------------------------------------------------- session basics


def test_eof_at_first_prompt_prints_newline_and_exits_zero(run):
    """CATCHES: a REPL that omits the banner, exits non-zero on Ctrl-D, or does not end the line after the
    final `pyfun> ` prompt when stdin closes immediately."""
    r = run(["repl"], input=b"")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "eof_immediately.stdout")
    assert r.stderr == b""


@pytest.mark.parametrize("command", [":quit", ":q", ":exit", "   :q   "])
def test_quit_commands_stop_reading_input(run, command):
    """CATCHES: a REPL missing one of the :quit/:q/:exit aliases, not trimming the entry, keeping on reading
    (and evaluating `1 + 1`) after a quit, or printing a newline on quit as it does on EOF."""
    r = run(["repl"], input=f"{command}\n1 + 1\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "quit.stdout")
    assert r.stderr == b""


@pytest.mark.parametrize("command", [":help", ":h", ":?"])
def test_help_aliases_print_the_command_list(run, command):
    """CATCHES: a missing :h or :? alias, or help text that differs from the reference listing of
    :type, :{ ... :}, :reset, :help and :quit."""
    r = run(["repl"], input=f"{command}\n:quit\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "help.stdout")
    assert r.stderr == b""


def test_blank_lines_just_reprompt(run):
    """CATCHES: a REPL that treats empty or whitespace-only lines as an (erroneous) entry, prints something
    for them, or stops reading, instead of silently showing the prompt again."""
    r = run(["repl"], input=b"\n   \n\t\t\n2 * 21\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "blank_lines.stdout")
    assert r.stderr == b""


def test_unknown_commands_are_reported_by_name(run):
    """CATCHES: an unknown-command message that echoes the arguments, matches commands case-insensitively
    (`:QUIT`), goes to stderr, or ends the session."""
    r = run(["repl"], input=b":bogus\n:typo some args\n:QUIT\n1 + 1\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "unknown_command.stdout")
    assert r.stderr == b""


def test_bare_colon_is_ignored(run):
    """CATCHES: a REPL that reports a bare `:` (or `:` followed by spaces) as an unknown command or tries
    to evaluate it as code, instead of ignoring it."""
    r = run(["repl"], input=b":\n:    \n1 + 1\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "bare_colon.stdout")
    assert r.stderr == b""


# ------------------------------------------------------------------------------------- :type


def test_type_command_shows_inferred_types_without_evaluating(run):
    """CATCHES: :type/:t that evaluates the expression (printing `side`), mis-trims its argument, or
    renders types (curried, polymorphic, operator sections, partial application) differently."""
    r = run(
        ["repl"],
        input=b':type 1 + 2\n:t "s"\n:type   List.map  \n:type (+)\n:type (==)\n:type (+) 1\n'
        b':type print "side"\n:type ()\n:q\n',
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_command.stdout")
    assert r.stderr == b""


def test_type_without_argument_prints_usage(run):
    """CATCHES: :type or :t with no (or only blank) argument that crashes, analyzes an empty program, or
    prints anything other than the usage line."""
    r = run(["repl"], input=b":type\n:t\n:type    \n:q\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_usage.stdout")
    assert r.stderr == b""


def test_type_of_a_definition_is_not_an_expression(run):
    """CATCHES: :type on a `let`/`type`/`extern` definition that echoes a binding's type or silently prints
    nothing, rather than the "could not determine a type" hint naming the input."""
    r = run(
        ["repl"],
        input=b":type let x = 1\n:type type T = A | B\n"
        b":type extern pure m: List float -> float = statistics.mean\nx\n:q\n",
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_non_expression.stdout")
    assert r.stderr == golden(__file__, "type_non_expression.stderr")


def test_type_sees_session_definitions_and_redefinitions(run):
    """CATCHES: :type that checks against an empty session, or against a stale one that keeps the first
    definition of a name after it has been redefined with another type."""
    r = run(["repl"], input=b'let double = (*) 2\n:type double\n:t double 4\nlet double = "text"\n:type double\n:q\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_session.stdout")
    assert r.stderr == b""


def test_type_error_in_type_command_is_rendered_on_stderr(run):
    """CATCHES: :type that prints a type for an ill-typed expression, renders the diagnostic on stdout, or
    numbers its line against the bare expression rather than the session source."""
    r = run(["repl"], input=b"let n = 1\n:type n + true\n:type n\n:q\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_error.stdout")
    assert r.stderr == golden(__file__, "type_error.stderr")


def test_type_reports_lex_and_parse_errors_in_source_order(run):
    """CATCHES: an analyzer that drops lex errors when a parse error exists (or vice versa), or lists all lex
    errors before parse errors instead of sorting every syntax error by position."""
    r = run(["repl"], input=b':type (1 +) + "x\n:type 1 + $\n:type "abc\n:q\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_syntax_errors.stdout")
    assert r.stderr == golden(__file__, "type_syntax_errors.stderr")


# ------------------------------------------------------------------------- evaluation & definitions


def test_expression_values_print_as_python_values(run):
    """CATCHES: a REPL that prints values in Pyfun syntax or as repr strings, drops the value of an
    expression, or runs Python with wrong semantics (true division, tuples, ADTs, records)."""
    r = run(
        ["repl"],
        input=b'1 + 2 * 3\n"text"\n[1, 2, 3]\n(1, "a", true)\n2.5 * 2.0\n7 / 2\nSome 3\nNone\n'
        b"type Pt = { x: int, y: int }\nPt { x = 1, y = 2 }\n",
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "expression_values.stdout")
    assert r.stderr == b""


def test_definitions_echo_their_inferred_types(run):
    """CATCHES: a REPL that does not echo `name : type` for each `let`, echoes for `type`/`extern`
    declarations, or renders generalized/curried function types differently."""
    r = run(
        ["repl"],
        input=b'let inc x = x + 1\nlet s = "a"\nlet xs = [1.5]\nlet pair = (1, true)\n'
        b"let compose f g x = f (g x)\ntype Shape = Circle float | Square float\n"
        b"extern pure mean: List float -> float = statistics.mean\nmean [1.0, 2.0, 4.5]\ninc 41\n",
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "definition_echoes.stdout")
    assert r.stderr == b""


def test_destructuring_definition_echoes_one_line_per_name(run):
    """CATCHES: a destructuring `let` that echoes only the first name, the whole pattern, or the tuple type,
    instead of one `name : type` line per bound name in pattern order (wildcards skipped)."""
    r = run(
        ["repl"],
        input=b"let ((m, n), k) = ((1, 2.5), true)\nlet (q, _) = (1, 2)\n"
        b'type P = { x: int, y: string }\nlet P { x, y } = P { x = 7, y = "s" }\n'
        b"let P { x = a, y = _ } = P { x = 3, y = \"t\" }\n(m, n, k, q, x, y, a)\n",
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "destructuring.stdout")
    assert r.stderr == b""


def test_definition_effect_runs_once_at_entry(run):
    """CATCHES: the stateless model that re-executes every accumulated definition (re-printing `boot`) on
    each later entry, or one that defers a definition's effect until first use."""
    r = run(["repl"], input=b'let g = print "boot"\n1 + 1\n2 + 2\ng\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "effect_once.stdout")
    assert r.stderr == b""


def test_unit_expressions_print_only_their_effects(run):
    """CATCHES: wrapping every expression in print, so unit-typed entries print a stray `None` (or `()`)
    after their effect or on their own."""
    r = run(["repl"], input=b'print "hello repl"\n()\nlet u = ()\nu\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "unit_expressions.stdout")
    assert r.stderr == b""


def test_top_level_mutable_state_persists_across_entries(run):
    """CATCHES: a REPL that recreates the namespace per entry or re-runs `let mut n = 0`, so reassignments
    entered separately do not accumulate (n * 10 would not be 20)."""
    r = run(["repl"], input=b"let mut n = 0\nn <- n + 1\nn <- n + 1\nn * 10\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "mutable_state.stdout")
    assert r.stderr == b""


def test_reentered_expression_runs_again(run):
    """CATCHES: chunk diffing that also remembers an expression's own statements, so entering the same
    expression (or the same print) a second time prints nothing."""
    r = run(["repl"], input=b'let x = 20\nx + 22\nx + 22\nprint "again"\nprint "again"\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "reentered_expression.stdout")
    assert r.stderr == b""


def test_identical_redefinition_skips_effect_until_reset(run):
    """CATCHES: a REPL that re-executes an identical re-entered definition (printing `boot` twice), or a
    :reset that leaves the executed-chunk memory behind so the effect never runs again."""
    r = run(["repl"], input=b'let g = print "boot"\nlet g = print "boot"\n:reset\nlet g = print "boot"\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "identical_redefinition.stdout")
    assert r.stderr == b""


def test_redefinition_rebinds_the_name(run):
    """CATCHES: a REPL that keeps executing the first definition of `f` after it is redefined, or rejects a
    redefinition that changes the binding's type."""
    r = run(["repl"], input=b'let f x = x + 1\nf 5\nlet f x = x * 10\nf 5\nlet f = "now a string"\nf\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "redefinition.stdout")
    assert r.stderr == b""


def test_reset_forgets_all_definitions(run):
    """CATCHES: a :reset that does not clear the accumulated definitions (so `inc` still resolves) or that
    breaks the session so new definitions no longer evaluate."""
    r = run(["repl"], input=b"let inc x = x + 1\n:reset\ninc 1\nlet inc x = x + 2\ninc 1\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "reset.stdout")
    assert r.stderr == golden(__file__, "reset.stderr")


def test_ill_typed_definition_is_rejected_and_session_unchanged(run):
    """CATCHES: committing a definition that fails to type-check (so `y` would resolve), or poisoning the
    session so the next well-typed entries stop working."""
    r = run(["repl"], input=b"let x = 5\nlet y = x + true\ny\nx + 1\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "ill_typed_definition.stdout")
    assert r.stderr == golden(__file__, "ill_typed_definition.stderr")


def test_ill_typed_expression_is_rejected(run):
    """CATCHES: evaluating an expression despite a type error (Python would raise TypeError on `s + 1`), or
    rendering the error against the wrong line of the session source."""
    r = run(["repl"], input=b'let s = "a"\ns + 1\nString.upper s\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "ill_typed_expression.stdout")
    assert r.stderr == golden(__file__, "ill_typed_expression.stderr")


def test_parse_errors_are_rendered_against_the_entry(run):
    """CATCHES: parse errors reported with session-relative line numbers, sent to stdout, or ending the
    session; the entry is parsed on its own so the caret points into line 1."""
    r = run(["repl"], input=b"let a = 1\nlet = 3\n1 +\nlet t = (1, 2\na + 1\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "parse_errors.stdout")
    assert r.stderr == golden(__file__, "parse_errors.stderr")


def test_typed_hole_blocks_compilation(run):
    """CATCHES: a REPL that evaluates a program containing a typed hole `?`, or commits a definition whose
    body still has a hole (the later `h` must be unbound)."""
    r = run(["repl"], input=b"let a = 1\n1 + ?\nlet h = ? + 1\nh\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "typed_hole.stdout")
    assert r.stderr == golden(__file__, "typed_hole.stderr")


def test_adt_values_keep_class_identity_across_entries(run):
    """CATCHES: re-sending an ADT's class definitions to the worker on later entries, which breaks
    isinstance identity so the stored `Red` no longer matches its constructor pattern."""
    r = run(
        ["repl"],
        input=b"type Color = Red | Green\nlet c = Red\n:{\nmatch c:\n"
        b'    case Red: print "red branch"\n    case Green: print "green branch"\n:}\nc\n[Red, Green]\n',
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "adt_identity.stdout")
    assert r.stderr == b""


def test_opaque_type_wraps_and_unwraps_across_entries(run):
    """CATCHES: an opaque type whose echo shows the underlying type, or whose value does not flow through the
    worker erased (the match must unwrap the bare string)."""
    r = run(
        ["repl"],
        input=b'opaque type UserId = string\nlet u = UserId "ana"\n:{\nmatch u:\n'
        b'    case UserId s: print (String.concat "id " s)\n:}\nu\n',
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "opaque_type.stdout")
    assert r.stderr == b""


# ------------------------------------------------------------------------------- :{ ... :} blocks


def test_block_groups_mutually_recursive_definitions(run):
    """CATCHES: a REPL without `:{ ... :}` blocks, or one that checks block lines one at a time so the
    mutually recursive isEven/isOdd fail with an unbound name."""
    r = run(
        ["repl"],
        input=b":{\nlet isEven n = if n == 0 then true else isOdd (n - 1)\n"
        b"let isOdd n = if n == 0 then false else isEven (n - 1)\n:}\nisEven 10\nisOdd 7\n",
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "block_mutual_recursion.stdout")
    assert r.stderr == b""


def test_block_can_hold_a_multiline_expression(run):
    """CATCHES: a block that is always treated as definitions, or loses its line breaks, so a multi-line
    if/then/else expression is not evaluated and printed."""
    r = run(["repl"], input=b':{\nif 1 < 2\nthen "yes"\nelse "no"\n:}\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "block_expression.stdout")
    assert r.stderr == b""


def test_block_ended_by_eof_is_still_evaluated(run):
    """CATCHES: discarding a block that reaches end of input without `:}`, or hanging/erroring at EOF
    inside a block instead of evaluating it and then exiting normally."""
    r = run(["repl"], input=b":{\nlet a = 1\nlet b = a + 1")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "block_eof.stdout")
    assert r.stderr == b""


def test_empty_blocks_are_ignored(run):
    """CATCHES: a REPL that evaluates an empty or blank-only block (reporting a parse error or printing
    output) rather than silently returning to the prompt."""
    r = run(["repl"], input=b":{\n:}\n:{\n   \n\n:}\n:quit\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "block_empty.stdout")
    assert r.stderr == b""


def test_block_markers_tolerate_surrounding_whitespace(run):
    """CATCHES: block open/close markers compared without trimming, so `  :{  ` is an unknown command or
    `   :}   ` is swallowed into the block body."""
    r = run(["repl"], input=b"  :{  \nlet a = 1\nlet b = 2\n   :}   \na + b\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "block_whitespace.stdout")
    assert r.stderr == b""


# ------------------------------------------------------------------------------ the python worker


def test_python_exception_is_shown_and_worker_survives(run):
    """CATCHES: a REPL that loses a runtime exception's traceback, sends it to its own stderr, or treats
    the exception as a dead worker (restart warning) instead of continuing with state intact."""
    r = run(
        ["repl"],
        input=b'extern parseInt: string -> int = int\nlet base = 1\nparseInt "oops"\nparseInt "42" + base\n',
    )
    assert r.returncode == 0
    assert without_traceback_frames(r.stdout) == golden(__file__, "python_exception.stdout")
    assert r.stderr == b""


def test_dead_worker_is_respawned_and_definitions_rerun(run, workdir):
    """CATCHES: a REPL that gives up when its python worker dies, or respawns it without re-running the
    accumulated definitions (no second `boot`, `crashOnce` unbound) or without the restart warning."""
    session = CRASH_EXTERNS + (
        b'let g = print "boot"\n:{\nlet crashOnce path =\n  if exists path then print "survived"\n'
        b'  else\n    mkdir path\n    die 3\n:}\ncrashOnce "marker"\ncrashOnce "marker"\n1 + 1\n'
    )
    r = run(["repl"], input=session)
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "worker_respawn.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "worker_respawn.stderr")
    assert sorted(os.listdir(workdir)) == ["marker"]


def test_worker_dying_again_on_retry_is_reported(run):
    """CATCHES: retrying a worker-killing entry in a loop, or silently dropping the failure of the single
    retry instead of reporting `python worker failed again`."""
    r = run(["repl"], input=b'extern die: int -> unit = os._exit\nlet g = print "boot"\nlet base = 10\nbase + 1\ndie 3\n')
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "worker_failed_again.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "worker_failed_again.stderr")


def test_worker_dying_on_first_use_reports_cannot_start(run):
    """CATCHES: treating a worker that never answered its first request like a restartable one (restart
    warning, retry) or aborting the session instead of reporting `cannot start python worker`."""
    r = run(
        ["repl"],
        input=b':{\nextern die: int -> unit = os._exit\nprint "about to exit"\ndie 3\n:}\n1 + 1\n',
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "worker_cannot_start.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "worker_cannot_start.stderr")


def test_worker_death_without_definitions_skips_rebuild(run):
    """CATCHES: printing the `definitions re-executed` warning (or re-running anything) when no definition
    has been accumulated yet and the worker dies."""
    r = run(
        ["repl"],
        input=b'1 + 1\n:{\nextern die: int -> unit = os._exit\nprint "about to exit"\ndie 3\n:}\n2 + 2\n',
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "worker_no_rebuild.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "worker_no_rebuild.stderr")


def test_worker_dying_while_rebuilding_is_reported(run, workdir):
    """CATCHES: ignoring a failure while re-running the definitions in a respawned worker, or retrying the
    entry anyway, instead of reporting `cannot restart python worker`."""
    session = CRASH_EXTERNS + (
        b':{\nlet setup =\n  if exists "marker" then die 4\n  else mkdir "marker"\n:}\n'
        b'print "before crash"\ndie 3\n'
    )
    r = run(["repl"], input=session)
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "worker_cannot_restart.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "worker_cannot_restart.stderr")
    assert sorted(os.listdir(workdir)) == ["marker"]


def test_garbage_on_worker_stdout_is_a_protocol_error(run):
    """CATCHES: a worker client that trusts a non-numeric reply header (or hangs on it) rather than treating
    it as a broken worker: discard, respawn, re-run definitions and retry."""
    r = run(
        ["repl"],
        input=b'extern type Bytes\nextern pure encode: string -> Bytes = .encode()\n'
        b'extern rawWrite: int -> Bytes -> int = os.write\nlet g = print "boot"\n'
        b'rawWrite 1 (encode "garbage!")\n1 + 1\n',
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "worker_bad_header.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "worker_bad_header.stderr")


def test_missing_python_interpreter_is_an_error(run, tmp_path):
    """CATCHES: a REPL that starts (printing the banner) or exits 0 without any Python interpreter, or that
    reports the problem on stdout or without naming the interpreters it tried."""
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    r = run(["repl"], input=b"1 + 1\n", env_overrides={"PATH": str(empty_bin)})
    assert r.returncode == 1
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "no_python.stderr")


def test_python_is_preferred_over_python3(run, tmp_path):
    """CATCHES: an interpreter lookup that tries `python3` before `python` (here python3 is a broken stub),
    or that only ever looks for `python3`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real = shutil.which("python3")
    assert real is not None
    (bin_dir / "python").symlink_to(os.path.realpath(real))
    stub = bin_dir / "python3"
    stub.write_text("#!/bin/sh\necho 'stub python3 must not run' >&2\nexit 1\n")
    stub.chmod(0o755)
    r = run(["repl"], input=b"1 + 1\nlet x = Some 2\nx\n", env_overrides={"PATH": str(bin_dir)})
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "prefers_python.stdout")
    assert r.stderr == b""


def test_invalid_utf8_input_ends_the_session(run):
    """CATCHES: a REPL that crashes (non-zero exit, panic) or evaluates garbage when a line of stdin is not
    valid UTF-8, instead of reporting an input error and ending the session cleanly."""
    r = run(["repl"], input=b"1 + 1\n\xff\xfe\n2 + 2\n")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "invalid_utf8.stdout")
    assert without_io_error_detail(r.stderr) == golden(__file__, "invalid_utf8.stderr")
