"""`pyfun repl`: the interactive loop driven through stdin — prompts, type echoes,
`:commands`, multi-line blocks, persistent state, rejected entries and worker failures."""

from conftest import golden_name, read_golden, run_case, transcript


def _repl(id, script, env=None):
    case = {"id": id, "args": ["repl"], "stdin": script}
    if env:
        case["env"] = env
    return case


def _check(run, workdir, case):
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


ECHO_CASE = _repl("definition_types_echo", "let double = (*) 2\n:type double\nlet greet name = f\"hi {name}\"\n:quit\n")
EVAL_CASE = _repl("expressions_evaluate", "let double = (*) 2\ndouble 21\n1 + 2 * 3\n\"text\"\n[1, 2] |> List.map double\n:quit\n")
ERROR_CASE = _repl("type_error_not_committed", "let x = 5\nlet y = x + true\ny\nx\n:quit\n")
MULTILINE_CASE = _repl("multiline_mutual_recursion", (
    ":{\n"
    "let isEven n = if n == 0 then true else isOdd (n - 1)\n"
    "let isOdd n = if n == 0 then false else isEven (n - 1)\n"
    ":}\n"
    "isEven 10\n"
    "isOdd 7\n"
    ":quit\n"
))
EFFECT_ONCE_CASE = _repl("definition_effect_runs_once", "let g = print \"boot\"\n1 + 1\n2 + 2\n:quit\n")
MUT_CASE = _repl("top_level_mut_persists", "let mut n = 0\nn <- n + 1\nn <- n + 1\nn * 10\n:quit\n")
REENTER_CASE = _repl("reentered_expression_reruns", "let x = 20\nprint (x + 22)\nprint (x + 22)\n:quit\n")
REDEFINE_CASE = _repl("redefinition_changes_behaviour", "let f x = x + 1\nf 5\nlet f x = x * 10\nf 5\n:quit\n")
RESET_CASE = _repl("reset_forgets_definitions", "let inc x = x + 1\n:reset\ninc 1\nlet inc x = x - 1\ninc 1\n:quit\n")
ADT_CASE = _repl("adt_identity_across_entries", (
    "type Color = Red | Green\n"
    "let c = Red\n"
    ":{\n"
    "match c:\n"
    "    case Red: print \"red branch\"\n"
    "    case Green: print \"green branch\"\n"
    ":}\n"
    "c\n"
    ":quit\n"
))
HELP_CASE = _repl("help_and_unknown_commands", ":help\n:h\n:?\n:frobnicate now\n:\n:type\n:quit\n")
EOF_CASE = _repl("eof_ends_the_session", "let a = 1\na + 1")
QUIT_ALIASES_CASE = _repl("exit_alias_stops_reading", "1 + 1\n:exit\n2 + 2\n")
Q_ALIAS_CASE = _repl("q_alias_stops_reading", "3 * 3\n:q\n4 * 4\n")
PARSE_ERROR_CASE = _repl("parse_error_entry", "let = 4\nlet ok = 1\nok\n:quit\n")
RUNTIME_ERROR_CASE = _repl("runtime_error_traceback", "let half x = x / 0\nhalf 4\n\"still alive\"\n:quit\n")
UNIT_CASE = _repl("unit_expression_prints_nothing_extra", "print \"side effect\"\n()\nlet u = ()\nu\n:quit\n")
DESTRUCTURE_CASE = _repl("destructuring_echoes_each_name", "let (a, b) = (1, \"s\")\nlet [x, y] = [1.5, 2.5]\na + 1\nx + y\n:quit\n")
TYPE_CMD_CASE = _repl("type_command_shapes", (
    "let id x = x\n"
    ":type id\n"
    ":t (+)\n"
    ":type Some 3\n"
    ":type print\n"
    ":type let z = 1\n"
    ":type 1 + true\n"
    ":quit\n"
))
BLOCK_EOF_CASE = _repl("block_closed_by_eof", ":{\nlet late = 41\nprint (late + 1)\n")
EMPTY_BLOCK_CASE = _repl("empty_block_is_ignored", ":{\n\n:}\n1 + 1\n:quit\n")
BLANK_LINES_CASE = _repl("blank_lines_are_skipped", "\n   \n\t\nlet v = 3\n\n v * 3 \n:quit\n")
RECORD_CASE = _repl("records_and_options", (
    "type P = { name: string, age: int }\n"
    "let p = P { name = \"Ada\", age = 36 }\n"
    "{ p with age = 37 }\n"
    "Map.tryFind \"k\" (Map.ofList [(\"k\", 1)])\n"
    "List.head []\n"
    ":quit\n"
))
WORKER_DIES_CASE = _repl("worker_death_and_restart", (
    "extern die : int -> unit = os._exit\n"
    "let z = 7\n"
    "z * 2\n"
    "die 3\n"
    "z * 3\n"
    ":quit\n"
))
NO_PYTHON_CASE = _repl("no_python_interpreter", "1 + 1\n", env={"PATH": "{workdir}/no-bin"})


def test_definitions_echo_their_inferred_types(run, workdir):
    """CATCHES: a REPL that does not echo `name : type` for new bindings (GHCi-style), or
    prints wrong inferred types (e.g. for an operator section or an f-string function)."""
    _check(run, workdir, ECHO_CASE)


def test_expressions_are_evaluated_and_printed(run, workdir):
    """CATCHES: expressions that are type-checked but not run, values printed with the wrong
    Python repr, or prompts missing between entries."""
    _check(run, workdir, EVAL_CASE)


def test_an_ill_typed_definition_is_not_committed(run, workdir):
    """CATCHES: committing a rejected definition to the session, so a later use of `y`
    finds it instead of reporting an unbound name."""
    _check(run, workdir, ERROR_CASE)


def test_a_multiline_block_checks_mutual_recursion_together(run, workdir):
    """CATCHES: missing `......` continuation prompts, or checking the block's definitions
    one at a time so mutually recursive functions cannot be entered."""
    _check(run, workdir, MULTILINE_CASE)


def test_a_definitions_effect_runs_once(run, workdir):
    """CATCHES: re-running every accumulated definition (and its `print`) on each entry
    instead of executing only the new chunks."""
    _check(run, workdir, EFFECT_ONCE_CASE)


def test_top_level_mutable_state_persists(run, workdir):
    """CATCHES: a fresh Python process per entry, which loses `let mut` updates."""
    _check(run, workdir, MUT_CASE)


def test_a_reentered_expression_runs_again(run, workdir):
    """CATCHES: deduplicating an expression's own statements so re-entering it is a no-op."""
    _check(run, workdir, REENTER_CASE)


def test_redefining_a_function_rebinds_it(run, workdir):
    """CATCHES: keeping the first definition of `f` after it is re-entered with a new body."""
    _check(run, workdir, REDEFINE_CASE)


def test_reset_forgets_definitions(run, workdir):
    """CATCHES: a `:reset` that keeps type-level or runtime state from before the reset."""
    _check(run, workdir, RESET_CASE)


def test_adt_classes_keep_their_identity_across_entries(run, workdir):
    """CATCHES: re-sending class definitions on each entry, which breaks `isinstance`
    identity so a match on an earlier value falls through."""
    _check(run, workdir, ADT_CASE)


def test_help_and_unknown_commands(run, workdir):
    """CATCHES: a different `:help` text or aliases (`:h`, `:?`), an unknown command that is
    evaluated as code, or a bare `:type` without the usage line."""
    _check(run, workdir, HELP_CASE)


def test_end_of_input_ends_the_session(run, workdir):
    """CATCHES: a REPL that hangs or errors at EOF, or does not evaluate a final line that has
    no trailing newline."""
    _check(run, workdir, EOF_CASE)


def test_exit_stops_reading_input(run, workdir):
    """CATCHES: `:exit` not recognised as a quit alias, so later lines are still evaluated."""
    _check(run, workdir, QUIT_ALIASES_CASE)


def test_q_stops_reading_input(run, workdir):
    """CATCHES: `:q` not recognised as a quit alias, so later lines are still evaluated."""
    _check(run, workdir, Q_ALIAS_CASE)


def test_a_parse_error_is_reported_and_the_session_continues(run, workdir):
    """CATCHES: a parse error that ends the session or is rendered with a different span."""
    _check(run, workdir, PARSE_ERROR_CASE)


def test_a_runtime_error_prints_the_traceback_and_continues(run, workdir):
    """CATCHES: a Python exception that kills the session or is swallowed silently."""
    _check(run, workdir, RUNTIME_ERROR_CASE)


def test_unit_expressions_print_no_value(run, workdir):
    """CATCHES: printing `None` for unit-typed expressions, or dropping their side effect."""
    _check(run, workdir, UNIT_CASE)


def test_destructuring_definitions_echo_every_name(run, workdir):
    """CATCHES: echoing only the first name bound by a tuple or list destructuring."""
    _check(run, workdir, DESTRUCTURE_CASE)


def test_type_command_on_various_inputs(run, workdir):
    """CATCHES: a `:type` that evaluates its argument, shows the wrong (or an un-generalised)
    type, accepts a definition, or reports type errors differently."""
    _check(run, workdir, TYPE_CMD_CASE)


def test_a_block_left_open_at_eof_is_still_evaluated(run, workdir):
    """CATCHES: discarding an unterminated `:{` block when input ends."""
    _check(run, workdir, BLOCK_EOF_CASE)


def test_an_empty_block_is_ignored(run, workdir):
    """CATCHES: an empty `:{ :}` block that is reported as an error or breaks the session."""
    _check(run, workdir, EMPTY_BLOCK_CASE)


def test_blank_lines_are_skipped_and_entries_trimmed(run, workdir):
    """CATCHES: blank or whitespace-only lines treated as entries, or untrimmed entries
    whose leading space breaks the offside rule."""
    _check(run, workdir, BLANK_LINES_CASE)


def test_records_and_options_print_with_their_repr(run, workdir):
    """CATCHES: wrong reprs for records, updated records, `Some`/`None_`, or a crash on a
    total stdlib call that returns `None`."""
    _check(run, workdir, RECORD_CASE)


def test_a_dead_worker_is_restarted(run, workdir):
    """CATCHES: a REPL that hangs or crashes when its Python worker exits, or reports the
    restart differently."""
    _check(run, workdir, WORKER_DIES_CASE)


def test_no_python_interpreter_is_reported(run, workdir):
    """CATCHES: a REPL that starts its banner (or crashes) without any Python available."""
    _check(run, workdir, NO_PYTHON_CASE)
