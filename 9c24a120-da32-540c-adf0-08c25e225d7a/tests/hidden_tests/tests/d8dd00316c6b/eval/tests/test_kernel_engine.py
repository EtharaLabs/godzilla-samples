"""`pyfun kernel-engine`: the session engine behind the Jupyter kernel, spoken to over stdio.

Requests are `frame(op) frame(payload)` and every reply is `frame(status)
frame(message) frame(blob)`, a frame being 8 ASCII digits (the byte length) then the
UTF-8 bytes. Each test sends a whole session and compares the engine's entire
stdout byte-for-byte with the reference.
"""

from conftest import golden_name, read_golden, run_case, transcript


def frame(text: str) -> str:
    return f"{len(text.encode('utf-8')):08}{text}"


def session(*requests) -> str:
    return "".join(frame(op) + frame(payload) for op, payload in requests)


def _case(id, *requests, raw=None):
    return {"id": id, "args": ["kernel-engine"], "stdin": raw if raw is not None else session(*requests)}


def _check(run, workdir, case):
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


DEFINITION_CASE = _case("definition_echo_and_diff", ("eval", "let n = 6 * 7"), ("eval", "let n = 6 * 7"))
EXPRESSION_CASE = _case("expression_wrapped_in_print", ("eval", "let n = 41"), ("eval", "n + 1"), ("eval", "n + 1"))
UNIT_CASE = _case("unit_expression_runs_bare", ("eval", "print \"hi\""), ("eval", "()"))
MIXED_CASE = _case("mixed_cell_splits_trailing_expression",
                   ("eval", "let double x = x * 2\ndouble 21"), ("eval", "let double x = x * 2\ndouble 21"))
TYPE_ERROR_CASE = _case("type_error_changes_nothing",
                        ("eval", "let n = 1"), ("eval", "let bad = n + \"x\""), ("eval", "bad"), ("eval", "n"))
PARSE_ERROR_CASE = _case("parse_error_rendered_against_cell", ("eval", "let = 3"))
STATE_CASE = _case("state_accumulates",
                   ("eval", "type Shape = Circle float | Rect float float"),
                   ("eval", "let area s =\n  match s:\n    case Circle r: 2.0 * r\n    case Rect w h: w * h"),
                   ("eval", "area (Rect 3.0 4.0)"))
INFRA_CASE = _case("infrastructure_remembered", ("eval", "Some 1"), ("eval", "Some 1"), ("eval", "List.map (fun x -> x) [None]"))
TYPE_OP_CASE = _case("type_op",
                     ("eval", "let double x = x * 2"), ("type", "double"), ("type", "double 2.5"),
                     ("type", "let q = 1"), ("type", "nope + 1"))
UNKNOWN_OP_CASE = _case("unknown_op_survives", ("frobnicate", "x"), ("eval", "1 + 1"))
EXPR_ERROR_CASE = _case("trailing_expression_error", ("eval", "let ok = 1\nok + true"), ("eval", "ok"))
DESTRUCTURE_CASE = _case("destructuring_echo", ("eval", "let (a, b) = (1, \"two\")\nlet c = [a]"))
MULTI_EXPR_CASE = _case("earlier_expressions_run_with_definitions",
                        ("eval", "print \"first\"\nlet x = 2\nprint \"second\"\nx * 5"))
UNICODE_CASE = _case("unicode_payload_lengths_are_bytes", ("eval", "let s = \"héllo ✓\"\nString.len s"))
EMPTY_CELL_CASE = _case("empty_and_comment_cells", ("eval", ""), ("eval", "# just a comment\n"))
EOF_MID_FRAME_CASE = _case("eof_inside_a_frame", raw=session(("eval", "let a = 1")) + frame("eval") + "0000")
BAD_HEADER_CASE = _case("bad_frame_header", raw=session(("eval", "let b = 2")) + "notdigitsxxxx" + session(("eval", "b")))
EOF_AFTER_OP_CASE = _case("eof_after_op", raw=session(("type", "1.5 * 2.0")) + frame("eval"))


def test_a_definition_echoes_and_is_compiled_once(run, workdir):
    """CATCHES: re-sending already-executed chunks for an identical definition, or a wrong
    `n : int` echo or frame length."""
    _check(run, workdir, DEFINITION_CASE)


def test_an_expression_is_printed_and_reruns(run, workdir):
    """CATCHES: an expression whose blob lacks the `print(...)` wrapper, re-includes the
    definitions, or is deduplicated so re-running the cell does nothing."""
    _check(run, workdir, EXPRESSION_CASE)


def test_a_unit_expression_is_not_wrapped(run, workdir):
    """CATCHES: wrapping a unit-typed expression in an extra `print`, printing `None`."""
    _check(run, workdir, UNIT_CASE)


def test_a_mixed_cell_splits_off_the_trailing_expression(run, workdir):
    """CATCHES: treating a cell's trailing expression as a definition (so re-running the cell
    does not re-evaluate it) or re-sending the cell's definitions."""
    _check(run, workdir, MIXED_CASE)


def test_a_type_error_is_reported_and_changes_nothing(run, workdir):
    """CATCHES: committing a rejected definition, or an error reply carrying a blob."""
    _check(run, workdir, TYPE_ERROR_CASE)


def test_a_parse_error_is_rendered_against_the_cell(run, workdir):
    """CATCHES: a parse error rendered against the accumulated session instead of the cell."""
    _check(run, workdir, PARSE_ERROR_CASE)


def test_state_accumulates_across_cells(run, workdir):
    """CATCHES: forgetting earlier cells' types, or re-sending class definitions."""
    _check(run, workdir, STATE_CASE)


def test_infrastructure_chunks_are_remembered(run, workdir):
    """CATCHES: re-sending `class Some`/helper chunks on every evaluation, which breaks
    `isinstance` identity in the caller's namespace."""
    _check(run, workdir, INFRA_CASE)


def test_the_type_op_answers_without_a_blob(run, workdir):
    """CATCHES: a `type` op that evaluates, returns a blob, accepts a definition, or renders
    errors differently."""
    _check(run, workdir, TYPE_OP_CASE)


def test_an_unknown_op_is_an_error_and_the_engine_survives(run, workdir):
    """CATCHES: an engine that exits or desynchronises its framing on an unknown op."""
    _check(run, workdir, UNKNOWN_OP_CASE)


def test_a_trailing_expression_error_rejects_the_cell(run, workdir):
    """CATCHES: replying ok for a cell whose trailing expression is ill-typed."""
    _check(run, workdir, EXPR_ERROR_CASE)


def test_a_destructuring_definition_echoes_each_name(run, workdir):
    """CATCHES: echoing only one name for a tuple destructuring."""
    _check(run, workdir, DESTRUCTURE_CASE)


def test_earlier_expressions_stay_with_the_definitions(run, workdir):
    """CATCHES: splitting off any expression but the last one, or dropping one of them."""
    _check(run, workdir, MULTI_EXPR_CASE)


def test_frame_lengths_count_bytes_not_characters(run, workdir):
    """CATCHES: framing by character count, which breaks for non-ASCII payloads."""
    _check(run, workdir, UNICODE_CASE)


def test_empty_and_comment_only_cells(run, workdir):
    """CATCHES: an error (or a crash) for a cell with nothing to evaluate."""
    _check(run, workdir, EMPTY_CELL_CASE)


def test_eof_inside_a_frame_ends_quietly(run, workdir):
    """CATCHES: a panic or non-zero exit when the input stops in the middle of a header,
    or losing the reply to the request that preceded it."""
    _check(run, workdir, EOF_MID_FRAME_CASE)


def test_a_bad_frame_header_ends_quietly(run, workdir):
    """CATCHES: a panic on a non-numeric frame header, or an engine that tries to resync and
    answers the request after it."""
    _check(run, workdir, BAD_HEADER_CASE)


def test_eof_after_the_op_frame_ends_quietly(run, workdir):
    """CATCHES: replying to (or crashing on) a request whose payload frame never arrives."""
    _check(run, workdir, EOF_AFTER_OP_CASE)
