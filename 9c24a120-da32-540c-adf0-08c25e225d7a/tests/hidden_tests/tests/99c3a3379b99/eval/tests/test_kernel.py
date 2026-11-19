"""Black-box tests for `pyfun kernel-engine`, the framed stdio protocol behind the Jupyter kernel.

Protocol (both directions): every frame is 8 ASCII digits giving the payload's UTF-8 byte length, then
the payload. A request is frame(op) frame(payload) with op "eval" (a cell) or "type" (an expression);
the reply is frame("ok"|"error") frame(message) frame(python blob to exec). EOF on stdin ends the
engine normally. Each test writes a whole request stream to stdin and compares the exact reply stream
with the one captured from the reference binary (eval/test_resources/test_kernel/).
"""

from conftest import golden, kernel_frame, kernel_unframe


def requests(*pairs: tuple[str, str]) -> bytes:
    """Frame a sequence of (op, payload) requests into one stdin stream."""
    return b"".join(kernel_frame(op, payload) for op, payload in pairs)


def engine(run, stream: bytes):
    return run(["kernel-engine"], input=stream)


# ------------------------------------------------------------------------------------- eval op


def test_definition_echoes_type_and_identical_reentry_is_diffed_away(run):
    """CATCHES: an engine that does not echo `n : int`, or re-sends a definition's already-executed chunk
    when the identical cell is evaluated again (the second blob must be empty)."""
    r = engine(run, requests(("eval", "let n = 6 * 7"), ("eval", "let n = 6 * 7")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "definition_reentry.frames")
    assert r.stderr == b""


def test_expression_is_wrapped_in_print_and_resent_on_rerun(run):
    """CATCHES: an engine that sends an expression bare (no print), re-sends the definitions it depends
    on, or remembers the expression's statement so a rerun returns an empty blob."""
    r = engine(run, requests(("eval", "let n = 41"), ("eval", "n + 1"), ("eval", "n + 1")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "expression_rerun.frames")
    assert r.stderr == b""


def test_unit_expressions_run_bare(run):
    """CATCHES: wrapping unit-typed expressions in print (which would print `None`), or diffing away a
    repeated `c <- c + 1` reassignment that must run on every entry."""
    r = engine(
        run,
        requests(("eval", 'print "hi"'), ("eval", "()"), ("eval", "let mut c = 0"), ("eval", "c <- c + 1"),
                 ("eval", "c <- c + 1")),
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "unit_expressions.frames")
    assert r.stderr == b""


def test_mixed_cell_splits_off_the_trailing_expression(run):
    """CATCHES: an engine that rejects a cell mixing definitions with a trailing expression, or treats the
    expression as a definition so re-running the cell no longer re-sends the print."""
    cell = "let double x = x * 2\ndouble 21"
    r = engine(run, requests(("eval", cell), ("eval", cell)))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "mixed_cell.frames")
    assert r.stderr == b""


def test_earlier_expressions_in_a_cell_run_once_with_the_definitions(run):
    """CATCHES: splitting every expression out of a cell (re-running `print "setup"` on each rerun) or
    printing its unit value, instead of keeping non-trailing expressions with the definitions."""
    cell = 'print "setup"\nlet x = 1\nx + 1'
    r = engine(run, requests(("eval", cell), ("eval", cell)))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "earlier_expression.frames")
    assert r.stderr == b""


def test_multiline_trailing_expression(run):
    """CATCHES: splitting the trailing expression at its last line only, so a multi-line if/then/else
    after a definition is mis-parsed or loses its condition."""
    r = engine(run, requests(("eval", 'let y = 3\nif y > 2\nthen "big"\nelse "small"\n')))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "multiline_expression.frames")
    assert r.stderr == b""


def test_cell_with_several_definitions_echoes_each_binding_in_order(run):
    """CATCHES: echoing only the last binding of a cell, echoing `type` declarations, or echoing a
    destructuring `let` as one tuple instead of one line per bound name."""
    r = engine(run, requests(("eval", 'let (a, b) = (1, "x")\nlet c = a + 1\ntype T = U | V\nlet d = U')))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "several_definitions.frames")
    assert r.stderr == b""


def test_redefinition_sends_the_new_body(run):
    """CATCHES: chunk diffing keyed by binding name rather than by emitted text, which would never send the
    redefined `f` (the later `f 5` must run the new body)."""
    r = engine(run, requests(("eval", "let f x = x + 1"), ("eval", "let f x = x * 10"), ("eval", "f 5")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "redefinition.frames")
    assert r.stderr == b""


def test_state_accumulates_across_cells(run):
    """CATCHES: an engine that checks each cell in isolation (so `Circle`/`area` are unknown later) or
    re-sends the ADT classes with each cell that uses them."""
    r = engine(
        run,
        requests(
            ("eval", "type Shape = Circle float | Rect float float"),
            ("eval", "let area s =\n  match s:\n    case Circle r: 2.0 * r\n    case Rect w h: w * h"),
            ("eval", "area (Rect 3.0 4.0)"),
        ),
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "state_accumulates.frames")
    assert r.stderr == b""


def test_expression_infrastructure_is_remembered_but_statements_are_not(run):
    """CATCHES: re-sending the Option classes an expression pulled in (breaking isinstance identity), or
    remembering the expression's own print so the second `Some 1` sends nothing."""
    r = engine(run, requests(("eval", "Some 1"), ("eval", "Some 1")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "infrastructure.frames")
    assert r.stderr == b""


def test_empty_blank_and_comment_only_cells(run):
    """CATCHES: an engine that errors on an empty or whitespace-only cell, or that treats a comment-only
    cell differently from an empty definition group."""
    r = engine(run, requests(("eval", ""), ("eval", "  \n\n"), ("eval", "# just a comment"), ("eval", "1 + 1")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "empty_cells.frames")
    assert r.stderr == b""


def test_frame_lengths_count_utf8_bytes(run):
    """CATCHES: framing that counts characters instead of UTF-8 bytes, which desynchronises the stream as
    soon as a cell or a reply contains non-ASCII text like `héllo ✓`."""
    stream = requests(("eval", 'let s = "héllo ✓"'), ("eval", "s"), ("type", "s"))
    r = engine(run, stream)
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "utf8.frames")
    assert kernel_unframe(r.stdout)[2] == 's = "héllo ✓"\n'
    assert r.stderr == b""


# ------------------------------------------------------------------------------------ errors


def test_type_error_reports_and_leaves_session_unchanged(run):
    """CATCHES: committing an ill-typed definition (so `bad` would resolve), returning a blob with an
    error, or forgetting the earlier good definition `n` after the error."""
    r = engine(
        run,
        requests(("eval", "let n = 1"), ("eval", 'let bad = n + "x"'), ("eval", "bad"), ("eval", "n")),
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_error.frames")
    assert r.stderr == b""


def test_parse_error_is_rendered_against_the_cell(run):
    """CATCHES: parse errors numbered against the accumulated session source instead of the cell itself,
    or a parse failure that stops the engine."""
    r = engine(run, requests(("eval", "let = 3"), ("eval", "let a = 1\nlet b = (a"), ("eval", "2 * 3")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "parse_error.frames")
    assert r.stderr == b""


def test_typed_hole_blocks_compilation(run):
    """CATCHES: an engine that returns Python for a cell containing a typed hole `?`, or commits a
    definition whose body has a hole (the later `h` must be unbound)."""
    r = engine(run, requests(("eval", "let a = 1"), ("eval", "1 + ?"), ("eval", "let h = ? + 1"), ("eval", "h")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "typed_hole.frames")
    assert r.stderr == b""


def test_unknown_op_is_an_error_and_the_engine_survives(run):
    """CATCHES: an engine that exits, hangs, or desynchronises (skipping the payload frame) on an unknown
    op, instead of replying `unknown op` and serving the next request."""
    r = engine(run, requests(("frobnicate", "x"), ("", ""), ("eval", "1 + 1")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "unknown_op.frames")
    assert r.stderr == b""


# -------------------------------------------------------------------------------------- type op


def test_type_op_answers_from_the_session_without_a_blob(run):
    """CATCHES: a type op that evaluates (returns a blob), ignores session definitions, or appends a
    newline to its message the way definition echoes do."""
    r = engine(
        run,
        requests(("eval", "let double x = x * 2"), ("type", "double"), ("type", "double 2"), ("type", "List.map")),
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_op.frames")
    assert r.stderr == b""


def test_type_op_errors(run):
    """CATCHES: a type op that reports ok for a definition or an unbound name, drops lex errors next to
    parse errors, or defines `z` as a side effect of asking for its type."""
    r = engine(
        run,
        requests(("type", "let z = 1"), ("type", "zz"), ("type", '"abc'), ("type", '(1 +) + "x'), ("eval", "z")),
    )
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "type_op_errors.frames")
    assert r.stderr == b""


# -------------------------------------------------------------------------------- stream handling


def test_clean_eof_exits_zero_without_output(run):
    """CATCHES: an engine that writes a greeting or an extra reply, errors, or exits non-zero when its
    stdin is closed cleanly between requests: one reply for the one request, then a quiet exit 0
    (and with no request at all, no output whatsoever)."""
    r = engine(run, b"")
    assert (r.stdout, r.stderr, r.returncode) == (b"", b"", 0)
    r = engine(run, requests(("type", "1 + 1")))
    assert kernel_unframe(r.stdout) == ["ok", "1 + 1 : int", ""]
    assert r.stdout == kernel_frame("ok", "1 + 1 : int", "")
    assert r.stderr == b""
    assert r.returncode == 0


def test_eof_between_op_and_payload_ends_quietly(run):
    """CATCHES: an engine that answers a request whose payload frame never arrives (e.g. treating it as
    empty), or reports an error/non-zero exit for the truncated stream."""
    r = engine(run, requests(("eval", "1 + 1")) + kernel_frame("eval"))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "eof_after_op.frames")
    assert r.stderr == b""


def test_eof_inside_a_frame_header_ends_quietly(run):
    """CATCHES: an engine that crashes, hangs, or interprets a partial 4-digit header as a length when the
    stream ends in the middle of a frame header."""
    r = engine(run, requests(("eval", "1 + 1")) + b"0000")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "eof_mid_header.frames")
    assert r.stderr == b""


def test_eof_inside_a_payload_ends_quietly(run):
    """CATCHES: an engine that evaluates a truncated payload (here `eva` of a declared 10 bytes) or
    panics, instead of ending without a further reply."""
    r = engine(run, requests(("eval", "1 + 1")) + b"00000010eva")
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "eof_mid_payload.frames")
    assert r.stderr == b""


def test_non_numeric_frame_header_stops_the_engine(run):
    """CATCHES: an engine that skips a garbage header and resynchronises, answering the request that
    follows it, instead of treating the broken stream as the end of the session."""
    r = engine(run, requests(("eval", "1 + 1")) + b"abcdefgh" + requests(("eval", "2 + 2")))
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "bad_header.frames")
    assert r.stderr == b""
