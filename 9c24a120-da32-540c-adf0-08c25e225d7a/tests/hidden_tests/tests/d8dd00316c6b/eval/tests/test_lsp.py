"""`pyfun lsp`: the language server over stdio (Content-Length framed JSON-RPC).

Each test sends a whole session (initialize ... shutdown, exit) and compares every
message the server writes, pretty-printed in the order and key order it was sent.
`{root}` stands for the `file://` URI of the test's working directory. Documents
that need no project directory use `untitled:` URIs (an unsaved editor buffer), so
nothing outside the working directory is ever consulted.
"""

import json

from conftest import case_transcript, golden_name, lsp_frame, read_golden, run_case

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
INITIALIZED = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
SHUTDOWN = {"jsonrpc": "2.0", "id": 99, "method": "shutdown"}
EXIT = {"jsonrpc": "2.0", "method": "exit"}


def did_open(uri, text):
    return {"jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "pyfun", "version": 1, "text": text}}}


def did_change(uri, *texts):
    return {"jsonrpc": "2.0", "method": "textDocument/didChange",
            "params": {"textDocument": {"uri": uri, "version": 2},
                       "contentChanges": [{"text": t} for t in texts]}}


def did_close(uri):
    return {"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {"textDocument": {"uri": uri}}}


def request(id, method, uri, line, character, **extra):
    params = {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}, **extra}
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


def pos(text, needle, nth=0, delta=0):
    """LSP (line, UTF-16 character) of the `nth` occurrence of `needle` in `text`, plus `delta`."""
    i = -1
    for _ in range(nth + 1):
        i = text.index(needle, i + 1)
    i += delta
    before = text[:i]
    line_start = before.rfind("\n") + 1
    return before.count("\n"), len(before[line_start:].encode("utf-16-le")) // 2


def at(id, method, uri, text, needle, nth=0, delta=0, **extra):
    """A position request whose cursor sits on `needle` (its first character plus `delta`)."""
    line, character = pos(text, needle, nth, delta)
    return request(id, method, uri, line, character, **extra)


def hover(id, uri, text, needle, nth=0, delta=0):
    return at(id, "textDocument/hover", uri, text, needle, nth, delta)


def definition(id, uri, text, needle, nth=0, delta=0):
    return at(id, "textDocument/definition", uri, text, needle, nth, delta)


def references(id, uri, text, needle, nth=0, delta=0, include=None):
    extra = {} if include is None else {"context": {"includeDeclaration": include}}
    return at(id, "textDocument/references", uri, text, needle, nth, delta, **extra)


def prepare_rename(id, uri, text, needle, nth=0, delta=0):
    return at(id, "textDocument/prepareRename", uri, text, needle, nth, delta)


def rename(id, uri, text, needle, new_name, nth=0, delta=0):
    return at(id, "textDocument/rename", uri, text, needle, nth, delta, newName=new_name)


def plain(id, method, params):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


def session(id, *messages, files=None):
    return {"id": id, "files": files or {}, "args": ["lsp"], "lsp": [INIT, INITIALIZED, *messages, SHUTDOWN, EXIT]}


def raw_session(id, *messages, files=None):
    """A session without the implicit initialize/shutdown/exit framing around it."""
    return {"id": id, "files": files or {}, "args": ["lsp"], "lsp": list(messages)}


def _check(run, workdir, case):
    proc, _ = run_case(run, workdir, case)
    assert case_transcript(proc, case, workdir) == read_golden(__file__, golden_name(case["id"]))
    return proc


# ============================================================== sources

NAV = (
    "## Primary colours, more or less.\n"
    "type Color = Red | Green\n"
    "type Box = { it: Color, n: int }\n"
    "extern root2 : float -> float = math.sqrt\n"
    "measure m\n"
    "let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n"
    "module Geo =\n"
    "  let pi = 3.0\n"
    "  let area r = pi * r * r\n"
    "let one = 1\n"
    "let (a, b) = (one, 2)\n"
    "let add x y =\n"
    "  let z = x + y\n"
    "  z * one\n"
    "let pick c =\n"
    "  match c:\n"
    "    case Red: \"r\"\n"
    "    case Green: \"g\"\n"
    "let parity k =\n"
    "  match k:\n"
    "    case Even: \"even\"\n"
    "    case Odd: \"odd\"\n"
    "let mk = Box { it = Red, n = add a b }\n"
    "let go = result {\n"
    "  let! v = Ok 1\n"
    "  return v + one\n"
    "}\n"
    "let big = Geo.area 2.0\n"
    "let fn = fun q -> q + a\n"
    "let lst xs =\n"
    "  match xs:\n"
    "    case [h, *rest] as whole: h\n"
    "    case _: 0\n"
    "let root = root2 4.0\n"
    "let unbox bx =\n"
    "  match bx:\n"
    "    case Box { it, n }: n\n"
    "let total = List.fold (fun acc x -> acc + x) 0 [a, b]\n"
)
NAV_URI = "untitled:nav.pyfun"

GEOMETRY = (
    "## The area of a rectangle.\n"
    "let area w h = w * h\n"
    "type Shape = Circle float | Rect float float\n"
    "type Point = { x: int, y: int }\n"
    "let origin = Point { x = 0, y = 0 }\n"
    "let describe s =\n"
    "  match s:\n"
    "    case Circle r: r\n"
    "    case Rect w h: w * h\n"
)
MAIN = (
    "import Geometry\n"
    "let floor = Geometry.area 4 5\n"
    "let c = Geometry.Circle 2.0\n"
    "let p = Geometry.Point { x = 1, y = 2 }\n"
    "type Holder = { at: Geometry.Point, spare: Point }\n"
    "let size s =\n"
    "  match s:\n"
    "    case Geometry.Circle r: r\n"
    "    case Geometry.Rect w h: w\n"
    "let twice = floor + floor\n"
    "let px q =\n"
    "  match q:\n"
    "    case Geometry.Point { x, y }: x + y\n"
)
PROJECT = {"geometry.pyfun": GEOMETRY, "main.pyfun": MAIN}
# A directory whose name looks like a module file: project scans must skip it.
PROJECT_PLUS = {**PROJECT, "weird.pyfun/keep.txt": ""}
MAIN_URI = "{root}/main.pyfun"
GEO_URI = "{root}/geometry.pyfun"


# ============================================================== protocol and framing

HOVER_CASE = session(
    "initialize_diagnostics_hover",
    did_open("file:///t.pyfun", "let add a b = a + b"),
    request(2, "textDocument/hover", "file:///t.pyfun", 0, 4),
)


def test_initialize_diagnostics_and_hover(run, workdir):
    """CATCHES: different advertised capabilities, a missing publishDiagnostics on open, or
    a hover that does not show the inferred curried signature."""
    _check(run, workdir, HOVER_CASE)


UNKNOWN_METHODS_CASE = session(
    "unknown_request_and_notification",
    plain(2, "textDocument/formatting", {"textDocument": {"uri": "untitled:x.pyfun"}}),
    {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 2}},
    {"jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": {"settings": {}}},
    plain("req-7", "custom/thing", {}),
    {"jsonrpc": "2.0", "id": 8, "method": "initialized", "params": {}},
)


def test_unknown_requests_get_method_not_found(run, workdir):
    """CATCHES: a server that ignores an unknown request (leaving the client waiting),
    answers an unknown notification, or uses a different JSON-RPC error code/message."""
    _check(run, workdir, UNKNOWN_METHODS_CASE)


ID_SHAPES_CASE = session(
    "request_ids_are_echoed_verbatim",
    plain("abc", "shutdown", {}),
    plain(-3, "shutdown", {}),
    plain(2.5, "shutdown", {}),
    plain(0, "shutdown", {}),
    plain(1e3, "shutdown", {}),
    plain(None, "nope/none", {}),
    plain([1, "two", None, True, False], "nope/array", {}),
    plain({"k": [{"n": -0.25}]}, "nope/object", {}),
)


def test_request_ids_of_every_json_type_are_echoed(run, workdir):
    """CATCHES: ids coerced to integers (2.5 printed as 2), floats printed with a trailing
    `.0`, string or structured ids dropped, or `null` ids omitted from the response."""
    _check(run, workdir, ID_SHAPES_CASE)


EXIT_STOPS_CASE = raw_session(
    "exit_stops_the_server",
    INIT,
    did_open("untitled:e.pyfun", "let x = 1"),
    SHUTDOWN,
    EXIT,
    plain(5, "textDocument/hover", {"textDocument": {"uri": "untitled:e.pyfun"},
                                     "position": {"line": 0, "character": 4}}),
)


def test_exit_stops_reading_further_messages(run, workdir):
    """CATCHES: a server that keeps answering requests after the `exit` notification, or
    returns something other than `null` for `shutdown`."""
    _check(run, workdir, EXIT_STOPS_CASE)


EOF_WITHOUT_EXIT_CASE = raw_session(
    "eof_without_exit",
    INIT,
    did_open("untitled:e.pyfun", "let x = 1"),
    hover(2, "untitled:e.pyfun", "let x = 1", "x"),
)


def test_end_of_input_without_exit_is_a_clean_stop(run, workdir):
    """CATCHES: a server that hangs, errors, or exits non-zero when stdin closes before
    any `exit` notification."""
    _check(run, workdir, EOF_WITHOUT_EXIT_CASE)


MALFORMED_BODIES = [
    b"not json at all",
    b"{\"jsonrpc\": \"2.0\", \"id\": 3",
    b"{\"a\" 1}",
    b"{1: 2}",
    b"[1, 2",
    b"[1 2]",
    b"{\"a\": tru}",
    b"{\"a\": nul}",
    b"{\"a\": -}",
    b"{\"a\": 1.2.3}",
    b"{\"a\": \"\\x\"}",
    b"{\"a\": \"\\u12\"}",
    b"{\"a\": \"\\uzzzz\"}",
    b"{\"a\": \"\\ud83d\"}",
    b"{\"a\": \"\\ud83dx\"}",
    b"{\"a\": \"\\udc00\"}",
    b"{\"a\": \"unterminated",
    b"{\"a\": 1} trailing",
    b"",
    b"   ",
    b"@",
    b"{\"a\": }",
    b"{\"a\": 1 \"b\": 2}",
    b"\"\\u1",
    b"[\"no end",
]
MALFORMED_CASE = session(
    "malformed_frames_are_ignored",
    *[lsp_frame(body) for body in MALFORMED_BODIES],
    plain(2, "shutdown", {}),
)


def test_malformed_json_frames_are_skipped(run, workdir):
    """CATCHES: a server that crashes, replies with a parse error, or stops serving after a
    frame whose body is not valid JSON (bad literals, numbers, escapes, lone surrogates,
    truncated strings, trailing characters, empty bodies)."""
    _check(run, workdir, MALFORMED_CASE)


ESCAPED_TEXT = json.dumps(
    {"jsonrpc": "2.0", "method": "textDocument/didOpen",
     "params": {"textDocument": {"uri": "untitled:esc.pyfun",
                                 "text": "let s = \"caf\u00e9 \U0001F600\"\nlet t\t= 1 + true\n# a/b\b\f\r\n"}}},
    ensure_ascii=True,
).encode("ascii")
ESCAPES_CASE = session(
    "json_string_escapes_decode",
    lsp_frame(ESCAPED_TEXT.replace(b"a/b", b"a\\/b")),
    lsp_frame(b' { "jsonrpc" : "2.0" , "id" : 2 , "method" : "textDocument/hover" , "params" : { '
              b'"textDocument" : { "uri" : "untitled:esc.pyfun" } , "position" : { "line" : 0 , '
              b'"character" : 9 } , "extra" : [ [ ] , { } , [ 1 , -2.5e3 , 1E-2 , true , false , null ] ] } } '),
    lsp_frame(b'{"jsonrpc":"2.0","id":3,"method":"textDocument/documentSymbol",'
              b'"params":{"textDocument":{"uri":"untitled:esc.pyfun"}}}'),
)


def test_json_escapes_and_whitespace_are_decoded(run, workdir):
    """CATCHES: a JSON reader that mishandles `\\u` escapes, surrogate pairs, `\\t`/`\\b`/`\\f`/
    `\\r` escapes, insignificant whitespace or nested empty containers, so the document text
    (and every position derived from it) differs from what the client sent."""
    _check(run, workdir, ESCAPES_CASE)


CONTROL_TEXT = "let s = \"tab\\there\"\nlet bad = \"a\" + 1\n"
RAW_OUTPUT_CASE = raw_session(
    "raw_output_bytes",
    INIT,
    did_open("untitled:raw.pyfun", CONTROL_TEXT),
    plain("q\"uote\\back\nnl\rcr\ttab\u0001ctl\u00e9", "nope/escapes", {}),
    hover(3, "untitled:raw.pyfun", CONTROL_TEXT, "s"),
    SHUTDOWN,
    EXIT,
)


def test_raw_output_framing_and_string_escaping(run, workdir):
    """CATCHES: Content-Length headers that count characters instead of bytes, missing
    `\\r\\n\\r\\n` separators, extra whitespace in the JSON, or string escaping that differs
    for quotes, backslashes, newlines, tabs and control characters (which must be `\\u0001`)."""
    proc = _check(run, workdir, RAW_OUTPUT_CASE)
    assert proc.stdout.decode("utf-8") == read_golden(__file__, "raw_output_bytes.stdout")


MISSING_LENGTH_CASE = raw_session(
    "missing_content_length_ends_the_session",
    INIT,
    b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n{}",
    plain(2, "shutdown", {}),
)


def test_a_frame_without_content_length_ends_the_session(run, workdir):
    """CATCHES: a reader that guesses a body length, or keeps going, when a header block has
    no Content-Length."""
    _check(run, workdir, MISSING_LENGTH_CASE)


SHUTDOWN_4 = {"jsonrpc": "2.0", "id": 4, "method": "shutdown"}
EXTRA_HEADERS_CASE = raw_session(
    "extra_headers_are_tolerated",
    b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n" + lsp_frame(json.dumps(INIT).encode()),
    b"X-Custom: 1\r\nContent-Length:   " + str(len(json.dumps(SHUTDOWN))).encode() + b"  \r\nX-Other: 2\r\n\r\n"
    + json.dumps(SHUTDOWN).encode(),
    b"Content-Length: " + str(len(json.dumps(SHUTDOWN_4))).encode() + b"\n\n" + json.dumps(SHUTDOWN_4).encode(),
    EXIT,
)


def test_extra_headers_and_bare_newlines_are_tolerated(run, workdir):
    """CATCHES: a header parser that rejects a Content-Type header, header order other than
    Content-Length first, padded values, or `\\n`-only line endings."""
    _check(run, workdir, EXTRA_HEADERS_CASE)


BAD_LENGTH_CASE = raw_session(
    "non_numeric_content_length",
    INIT,
    b"Content-Length: lots\r\n\r\n{}",
    plain(2, "shutdown", {}),
)


def test_a_non_numeric_content_length_ends_the_session(run, workdir):
    """CATCHES: a reader that treats an unparseable Content-Length as zero and continues."""
    _check(run, workdir, BAD_LENGTH_CASE)


TRUNCATED_BODY_CASE = raw_session(
    "eof_inside_a_body",
    INIT,
    b"Content-Length: 500\r\n\r\n{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"shutdown\"}",
)


def test_end_of_input_inside_a_body_is_an_error(run, workdir):
    """CATCHES: a server that silently accepts a truncated body (or panics) instead of
    reporting `lsp server error` and exiting non-zero."""
    _check(run, workdir, TRUNCATED_BODY_CASE)


# ============================================================== diagnostics

DIAG_TYPE_ERROR_TEXT = "let x = 1 + true\nlet y = \"s\" + 2\nlet ok = 3\n"
DIAG_TYPE_ERROR_CASE = session(
    "diagnostics_for_type_errors",
    did_open("untitled:bad.pyfun", DIAG_TYPE_ERROR_TEXT),
)


def test_type_errors_are_published_with_ranges(run, workdir):
    """CATCHES: diagnostics with the wrong range, severity, source or message, or only the
    first of several errors published."""
    _check(run, workdir, DIAG_TYPE_ERROR_CASE)


PARTIAL_TEXT = "let good = 1\nlet bad =\nlet also = good + 2\n"
PARTIAL_CASE = session(
    "half_typed_file_still_serves",
    did_open("untitled:partial.pyfun", PARTIAL_TEXT),
    hover(2, "untitled:partial.pyfun", PARTIAL_TEXT, "good"),
    hover(3, "untitled:partial.pyfun", PARTIAL_TEXT, "also"),
    plain(4, "textDocument/documentSymbol", {"textDocument": {"uri": "untitled:partial.pyfun"}}),
    definition(5, "untitled:partial.pyfun", PARTIAL_TEXT, "good", nth=1),
    prepare_rename(6, "untitled:partial.pyfun", PARTIAL_TEXT, "good"),
    rename(7, "untitled:partial.pyfun", PARTIAL_TEXT, "good", "fine"),
)


def test_a_half_typed_file_still_diagnoses_hovers_and_outlines(run, workdir):
    """CATCHES: an analysis that gives up on a parse error (no hover, no symbols, no
    definition) instead of recovering, or that allows rename on a file that does not
    fully parse (an unsound rewrite)."""
    _check(run, workdir, PARTIAL_CASE)


LEX_ERROR_TEXT = "let good = 1\nlet s = \"oops\n"
LEX_ERROR_CASE = session(
    "lex_error_keeps_the_file",
    did_open("untitled:lex.pyfun", LEX_ERROR_TEXT),
    hover(2, "untitled:lex.pyfun", LEX_ERROR_TEXT, "good"),
)


def test_a_lex_error_does_not_blank_the_file(run, workdir):
    """CATCHES: an unterminated string that wipes out analysis of the lines before it."""
    _check(run, workdir, LEX_ERROR_CASE)


HOLE_CASE = session(
    "typed_holes_are_information",
    did_open("untitled:hole.pyfun", "let f x = x + 1\nlet r = f ?\n"),
    hover(2, "untitled:hole.pyfun", "let f x = x + 1\nlet r = f ?\n", "?"),
)


def test_typed_holes_publish_at_information_severity(run, workdir):
    """CATCHES: holes reported as errors (severity 1) instead of information (3), or a hole
    whose hover and message do not show the type the context expects."""
    _check(run, workdir, HOLE_CASE)


CHANGE_CASE = session(
    "did_change_republishes",
    did_open("untitled:c.pyfun", "let n = 1\n"),
    did_change("untitled:c.pyfun", "let n = true + 1\n"),
    did_change("untitled:c.pyfun", "let n = 1 + true\n", "let n = 2.5\n"),
    hover(2, "untitled:c.pyfun", "let n = 2.5\n", "n"),
    {"jsonrpc": "2.0", "method": "textDocument/didChange",
     "params": {"textDocument": {"uri": "untitled:c.pyfun"}, "contentChanges": []}},
    {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {"contentChanges": [{"text": "x"}]}},
    hover(3, "untitled:c.pyfun", "let n = 2.5\n", "n"),
)


def test_did_change_republishes_from_the_last_content_change(run, workdir):
    """CATCHES: applying the first instead of the last full-text change, serving a stale
    cached analysis after an edit, or replying to a malformed didChange."""
    _check(run, workdir, CHANGE_CASE)


CLOSE_CASE = session(
    "did_close_clears_diagnostics",
    did_open("untitled:z.pyfun", "let z = 1 + true\n"),
    did_close("untitled:z.pyfun"),
    hover(2, "untitled:z.pyfun", "let z = 1 + true\n", "z"),
    plain(3, "textDocument/documentSymbol", {"textDocument": {"uri": "untitled:z.pyfun"}}),
    {"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": "untitled:q.pyfun"}}},
)


def test_did_close_clears_diagnostics_and_forgets_the_document(run, workdir):
    """CATCHES: a close that leaves stale diagnostics in the editor, keeps serving hover for
    the closed buffer, or replies to malformed open/close notifications."""
    _check(run, workdir, CLOSE_CASE)


UNOPENED_CASE = session(
    "requests_on_unopened_documents",
    hover(2, "untitled:never.pyfun", "x", "x"),
    definition(3, "untitled:never.pyfun", "x", "x"),
    references(4, "untitled:never.pyfun", "x", "x"),
    prepare_rename(5, "untitled:never.pyfun", "x", "x"),
    rename(6, "untitled:never.pyfun", "x", "x", "y"),
    plain(7, "textDocument/documentSymbol", {"textDocument": {"uri": "untitled:never.pyfun"}}),
    plain(8, "textDocument/hover", {"textDocument": {"uri": "untitled:never.pyfun"}}),
    plain(9, "textDocument/definition", {}),
    plain(10, "textDocument/references", {"position": {"line": 0, "character": 0}}),
    plain(11, "textDocument/rename", {"textDocument": {"uri": "untitled:never.pyfun"},
                                      "position": {"line": 0, "character": 0}}),
    plain(12, "textDocument/documentSymbol", {}),
)


def test_requests_on_unknown_documents_return_empty_results(run, workdir):
    """CATCHES: a crash or an error response (instead of `null` / `[]`) for requests about a
    document that was never opened, or that lack their position or text document."""
    _check(run, workdir, UNOPENED_CASE)


# ============================================================== hover

HOVER_TEXT = (
    "## Adds two numbers.\n"
    "## Second line of the doc.\n"
    "let pure add a b = a + b\n"
    "type Point = { x: float, y: float }\n"
    "let p = Point { x = 1.0, y = 2.0 }\n"
    "let shout s = print (String.upper s)\n"
    "measure m\n"
    "measure s\n"
    "let speed = 100.0<m> / 10.0<s>\n"
    "let check ok v =\n"
    "  result {\n"
    "    let! x = if ok then Ok v else Error \"bad\"\n"
    "    return x + 1\n"
    "  }\n"
    "let go = async { return 1 }\n"
    "let f o =\n"
    "  match o:\n"
    "    case Some y: y\n"
    "    case None: 0\n"
    "let n = List.contains 1 [1]\n"
    "let t = fst (1, 2)\n"
    "let twice g z = g (g z)\n"
    "let names = [\"a\", \"b\"] |> List.map String.upper\n"
)
HU = "untitled:hover.pyfun"


def _hover_case(id, *needles):
    msgs = [did_open(HU, HOVER_TEXT)]
    for i, needle in enumerate(needles):
        msgs.append(hover(i + 2, HU, HOVER_TEXT, *needle) if isinstance(needle, tuple)
                    else hover(i + 2, HU, HOVER_TEXT, needle))
    return session(id, *msgs)


HOVER_DOC_CASE = _hover_case("hover_doc_comment", "add", ("add", 0, 2), ("a + b", 0, 0))
HOVER_RECORD_CASE = _hover_case("hover_record_literal", "Point {", ("x = 1.0", 0, 4), "p =")
HOVER_EFFECT_CASE = _hover_case("hover_effects", "shout", "print", ("String.upper", 0, 7), "go =")
HOVER_UNITS_CASE = _hover_case("hover_units", "speed", "100.0", ("10.0", 0, 0))
HOVER_CE_CASE = _hover_case("hover_computation_expression", "ok v", ("x = if", 0, 0), ("x + 1", 0, 0), "result {")
HOVER_MATCH_CASE = _hover_case("hover_match_capture", ("y: y", 0, 3), ("f o", 0, 2), ("None", 0, 0))
HOVER_BUILTIN_CASE = _hover_case("hover_builtin_docs", ("contains", 0, 0), ("List.contains", 0, 0), "fst", ("map", 0, 0))
HOVER_POLY_CASE = _hover_case("hover_polymorphic_function", "twice", ("g (g", 0, 0), ("z)", 0, 0))
HOVER_NOTHING_CASE = _hover_case("hover_on_nothing", ("measure m", 0, 0), ("Second line", 0, 0), ("Point =", 0, 0))


def test_hover_appends_a_multiline_doc_comment(run, workdir):
    """CATCHES: hover that drops the `##` doc comment of a declaration, joins its lines
    without Markdown hard breaks, or shows the wrong curried type for `add` and `a`."""
    _check(run, workdir, HOVER_DOC_CASE)


def test_hover_on_a_record_literal_and_its_fields(run, workdir):
    """CATCHES: hover that picks the widest instead of the narrowest node, or shows a field
    value with the record's type."""
    _check(run, workdir, HOVER_RECORD_CASE)


def test_hover_shows_a_dedicated_effect_line(run, workdir):
    """CATCHES: a missing `**Effect:** io` line for an impure function or builtin, an effect
    line on a pure one, or `async` not reported for an async block."""
    _check(run, workdir, HOVER_EFFECT_CASE)


def test_hover_shows_units_of_measure(run, workdir):
    """CATCHES: hover that erases units (`float` instead of `float<m/s>`) or renders the unit
    algebra differently."""
    _check(run, workdir, HOVER_UNITS_CASE)


def test_hover_inside_a_result_block(run, workdir):
    """CATCHES: CE-bound names (`let!`) hovered with the wrapped type instead of the payload
    type, or parameters typed differently inside a CE."""
    _check(run, workdir, HOVER_CE_CASE)


def test_hover_on_match_captures(run, workdir):
    """CATCHES: a pattern capture hovered with the scrutinee's type, or the Option scrutinee
    shown with the wrong type argument."""
    _check(run, workdir, HOVER_MATCH_CASE)


def test_hover_documents_builtin_members(run, workdir):
    """CATCHES: built-in members (`List.contains`, `List.map`) and global builtins (`fst`)
    hovered without their one-line documentation or with the wrong signature."""
    _check(run, workdir, HOVER_BUILTIN_CASE)


def test_hover_on_a_polymorphic_higher_order_function(run, workdir):
    """CATCHES: un-generalised or wrongly named type variables in a hovered signature."""
    _check(run, workdir, HOVER_POLY_CASE)


def test_hover_where_no_type_is_recorded(run, workdir):
    """CATCHES: hover that invents a type for a declaration keyword, a comment, or a type
    name (which must be `null`)."""
    _check(run, workdir, HOVER_NOTHING_CASE)


DOC_ONLY_TEXT = (
    "## A colour the palette knows.\n"
    "type Color = Red | Green\n"
    "## Python's square root.\n"
    "extern root : float -> float = math.sqrt\n"
    "## My own fst, not the builtin.\n"
    "let fst p = 42\n"
    "let k = fst 0\n"
    "let r = root 2.0\n"
)
DOC_ONLY_CASE = session(
    "hover_doc_without_type",
    did_open("untitled:doc.pyfun", DOC_ONLY_TEXT),
    hover(2, "untitled:doc.pyfun", DOC_ONLY_TEXT, "Color"),
    hover(3, "untitled:doc.pyfun", DOC_ONLY_TEXT, "root :"),
    hover(4, "untitled:doc.pyfun", DOC_ONLY_TEXT, "fst", nth=1),
    hover(5, "untitled:doc.pyfun", DOC_ONLY_TEXT, "root 2.0"),
    hover(6, "untitled:doc.pyfun", DOC_ONLY_TEXT, "Red"),
)


def test_hover_on_documented_declarations_without_a_type(run, workdir):
    """CATCHES: a type or extern name whose doc comment is not shown on hover, or a builtin's
    documentation winning over the user's own `##` doc for a shadowing declaration."""
    _check(run, workdir, DOC_ONLY_CASE)


UTF16_TEXT = "let t = \"x\"\nlet s = String.concat \"\U0001F600 é\" t\nlet after = s\n"
UTF16_CASE = session(
    "hover_utf16_positions",
    did_open("untitled:u.pyfun", UTF16_TEXT),
    hover(2, "untitled:u.pyfun", UTF16_TEXT, "t\n"),
    hover(3, "untitled:u.pyfun", UTF16_TEXT, "\U0001F600"),
    definition(7, "untitled:u.pyfun", UTF16_TEXT, "t\n"),
    request(4, "textDocument/hover", "untitled:u.pyfun", 0, 99),
    request(5, "textDocument/hover", "untitled:u.pyfun", 50, 0),
    plain(6, "textDocument/documentSymbol", {"textDocument": {"uri": "untitled:u.pyfun"}}),
)


def test_positions_are_utf16_columns(run, workdir):
    """CATCHES: byte or code-point columns instead of UTF-16 units (an emoji counts two), or
    out-of-range positions that crash instead of clamping to the line / document end."""
    _check(run, workdir, UTF16_CASE)


# ============================================================== go-to-definition (in file)

def _nav_case(id, method, *targets):
    msgs = [did_open(NAV_URI, NAV)]
    for i, t in enumerate(targets):
        needle, nth, delta = t if isinstance(t, tuple) else (t, 0, 0)
        msgs.append(at(i + 2, method, NAV_URI, NAV, needle, nth, delta))
    return session(id, *msgs)


DEF_VALUES_CASE = _nav_case("definition_of_values", "textDocument/definition",
                            ("one", 1, 0), ("z * one", 0, 4), ("add a b", 0, 0), ("a b }", 0, 0), ("b }", 0, 0))
DEF_LOCALS_CASE = _nav_case("definition_of_locals", "textDocument/definition",
                            ("z * one", 0, 0), ("x + y", 0, 0), ("y\n", 0, 0), ("v + one", 0, 0),
                            ("q + a", 0, 0), ("h\n", 0, 0), ("acc + x", 0, 0), ("x) 0", 0, 0))
DEF_CTORS_CASE = _nav_case("definition_of_constructors_and_types", "textDocument/definition",
                           ("Red:", 0, 0), ("Green:", 0, 0), ("Red, n", 0, 0), ("Even:", 0, 0), ("Odd:", 0, 0),
                           ("Box {", 0, 0), ("Color, n", 0, 0), ("Box { it, n }", 0, 0), ("Even else", 0, 0))
DEF_OTHERS_CASE = _nav_case("definition_of_externs_and_builtins", "textDocument/definition",
                            ("root2 4.0", 0, 0), ("List.fold", 0, 0), ("Geo.area", 0, 4), ("Ok 1", 0, 0),
                            ("int }", 0, 0), ("pi *", 0, 0), ("one = 1", 0, 0), ("n }: n", 0, 5), ("\n", 0, 0))


def test_definition_of_top_level_values(run, workdir):
    """CATCHES: go-to-definition that lands on the whole declaration instead of the name, or
    misses the elements of a destructuring `let (a, b)`."""
    _check(run, workdir, DEF_VALUES_CASE)


def test_definition_of_locals(run, workdir):
    """CATCHES: a resolver that ignores lexical scope, so block lets, parameters, pattern
    captures, CE `let!` binders, lambda and list-pattern variables jump to the wrong place."""
    _check(run, workdir, DEF_LOCALS_CASE)


def test_definition_of_constructors_types_and_active_patterns(run, workdir):
    """CATCHES: constructor patterns, active-pattern cases, record tags and type annotations
    that do not jump to their declaration's name span."""
    _check(run, workdir, DEF_CTORS_CASE)


def test_definition_of_externs_builtins_and_module_members(run, workdir):
    """CATCHES: builtins that jump somewhere (must be `null`), an extern use that does not
    reach its declaration, or in-file module members resolved wrongly."""
    _check(run, workdir, DEF_OTHERS_CASE)


# ============================================================== references and rename (in file)

REFS_LOCAL_CASE = session(
    "references_in_file",
    did_open(NAV_URI, NAV),
    references(2, NAV_URI, NAV, "one", nth=1),
    references(3, NAV_URI, NAV, "one", nth=1, include=False),
    references(4, NAV_URI, NAV, "x + y"),
    references(5, NAV_URI, NAV, "x y =", include=False),
    references(6, NAV_URI, NAV, "Red", include=True),
    references(7, NAV_URI, NAV, "Color"),
    references(8, NAV_URI, NAV, "Color", nth=1, include=False),
    references(9, NAV_URI, NAV, "Box", nth=1),
    references(10, NAV_URI, NAV, "List.fold"),
    references(11, NAV_URI, NAV, "\n"),
    references(12, NAV_URI, NAV, "v + one"),
)


def test_references_in_a_single_document(run, workdir):
    """CATCHES: find-references that ignores `includeDeclaration`, misses pattern or
    construction uses of a constructor, mixes up a parameter with a same-named global, or
    returns locations out of source order."""
    _check(run, workdir, REFS_LOCAL_CASE)


PREPARE_IN_FILE_CASE = session(
    "prepare_rename_in_file",
    did_open(NAV_URI, NAV),
    prepare_rename(2, NAV_URI, NAV, "one", nth=1),
    prepare_rename(3, NAV_URI, NAV, "z * one"),
    prepare_rename(4, NAV_URI, NAV, "Red", nth=1),
    prepare_rename(5, NAV_URI, NAV, "Color", nth=1),
    prepare_rename(6, NAV_URI, NAV, "int }"),
    prepare_rename(7, NAV_URI, NAV, "List.fold"),
    prepare_rename(8, NAV_URI, NAV, "root2 4.0"),
    prepare_rename(9, NAV_URI, NAV, "\n"),
)


def test_prepare_rename_in_a_single_document(run, workdir):
    """CATCHES: prepareRename that offers to rename builtins, built-in types, constructors or
    externs outside a project, or returns a range other than the identifier under the cursor."""
    _check(run, workdir, PREPARE_IN_FILE_CASE)


RENAME_IN_FILE_CASE = session(
    "rename_in_file",
    did_open(NAV_URI, NAV),
    rename(2, NAV_URI, NAV, "one", "uno", nth=1),
    rename(3, NAV_URI, NAV, "z * one", "sum"),
    rename(4, NAV_URI, NAV, "Color", "Hue", nth=1),
    rename(5, NAV_URI, NAV, "Color", "hue"),
    rename(6, NAV_URI, NAV, "Red", "Crimson", nth=1),
    rename(7, NAV_URI, NAV, "one", "Uno", nth=1),
    rename(8, NAV_URI, NAV, "one", "match", nth=1),
    rename(9, NAV_URI, NAV, "one", "9lives", nth=1),
    rename(10, NAV_URI, NAV, "one", "", nth=1),
    rename(11, NAV_URI, NAV, "one", "with-dash", nth=1),
    rename(12, NAV_URI, NAV, "Color", "Let", nth=1),
    rename(13, NAV_URI, NAV, "int }", "Integer"),
    rename(14, NAV_URI, NAV, "List.fold", "folder"),
    plain(15, "textDocument/rename", {"textDocument": {"uri": NAV_URI}, "position": {"line": 9, "character": 4}}),
)


def test_rename_in_a_single_document(run, workdir):
    """CATCHES: renames that miss an occurrence, accept invalid new names (uppercase for a
    value, lowercase for a type, keywords, leading digits, punctuation, empty), rename a
    constructor or builtin outside a project, or omit the declaration edit."""
    _check(run, workdir, RENAME_IN_FILE_CASE)


# ============================================================== completion and symbols

COMPLETION_TEXT = (
    "import Geometry\n"
    "type Color = Red | Green\n"
    "type Box = { it: int }\n"
    "extern root : float -> float = math.sqrt\n"
    "measure m\n"
    "let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n"
    "let print x = x\n"
    "let main = Li\n"
)
COMPLETION_CASE = session(
    "completion_user_symbols_then_builtins",
    did_open("untitled:comp.pyfun", COMPLETION_TEXT),
    request(2, "textDocument/completion", "untitled:comp.pyfun", 7, 13),
)
COMPLETION_NO_DOC_CASE = session(
    "completion_without_a_document",
    plain(2, "textDocument/completion", {"textDocument": {"uri": "untitled:missing.pyfun"},
                                         "position": {"line": 0, "character": 0}}),
)


def test_completion_lists_user_symbols_first_then_the_prelude(run, workdir):
    """CATCHES: completion that omits user symbols of some kind (types, records, constructors,
    externs, measures, imports, active-pattern cases), uses different CompletionItemKinds,
    duplicates a user name that shadows a builtin, or drops builtin signatures and docs."""
    _check(run, workdir, COMPLETION_CASE)


def test_completion_without_a_document_offers_the_static_set(run, workdir):
    """CATCHES: completion that fails (instead of offering prelude, members, constructors,
    types and keywords) when the document is unknown."""
    _check(run, workdir, COMPLETION_NO_DOC_CASE)


SYMBOLS_CASE = session(
    "document_symbols_outline",
    did_open(NAV_URI, NAV),
    plain(2, "textDocument/documentSymbol", {"textDocument": {"uri": NAV_URI}}),
    did_open("untitled:imp.pyfun", "import Geometry\nimport Store\nlet (p, q) = (1, 2)\nlet r = p + q\n"),
    plain(3, "textDocument/documentSymbol", {"textDocument": {"uri": "untitled:imp.pyfun"}}),
)


def test_document_symbols_outline_every_kind_of_definition(run, workdir):
    """CATCHES: an outline missing constructors, records, externs, measures, active-pattern
    cases, qualified in-file module members, imports or destructured names, or using other
    SymbolKind codes."""
    _check(run, workdir, SYMBOLS_CASE)


# ============================================================== projects: import-aware analysis

IMPORT_DIAG_CASE = session(
    "import_aware_diagnostics",
    did_open(MAIN_URI, MAIN),
    did_open("{root}/other.pyfun", "import Geometry\nlet bad = Geometry.area 1 \"x\"\nlet gone = Geometry.missing\n"),
    did_open("{root}/lonely.pyfun", "import Nowhere\nlet v = Nowhere.thing\n"),
    hover(2, "{root}/lonely.pyfun", "import Nowhere\nlet v = Nowhere.thing\n", "v ="),
    hover(3, "{root}/lonely.pyfun", "import Nowhere\nlet v = Nowhere.thing\n", "thing"),
    files=PROJECT,
)


def test_imports_are_resolved_from_sibling_files(run, workdir):
    """CATCHES: an LSP that flags every qualified use of an imported module as "not a member",
    misses a genuine cross-module type error, or crashes on a missing sibling module."""
    _check(run, workdir, IMPORT_DIAG_CASE)


TRANSITIVE_FILES = {
    "base.pyfun": "let unit = 10\n",
    "mid.pyfun": "import Base\nlet scaled k = k * Base.unit\n",
    "app.pyfun": "import Mid\nlet v = Mid.scaled 3\n",
    "app2.pyfun": "import Mid\nimport Base\nlet w = Mid.scaled Base.unit\n",
    "broken.pyfun": "let = 1\n",
    "uses_broken.pyfun": "import Broken\nlet b = Broken.x\n",
}
TRANSITIVE_CASE = session(
    "transitive_and_broken_imports",
    did_open("{root}/app2.pyfun", TRANSITIVE_FILES["app2.pyfun"]),
    did_open("{root}/app.pyfun", TRANSITIVE_FILES["app.pyfun"]),
    hover(2, "{root}/app2.pyfun", TRANSITIVE_FILES["app2.pyfun"], "w ="),
    did_open("{root}/uses_broken.pyfun", TRANSITIVE_FILES["uses_broken.pyfun"]),
    files=TRANSITIVE_FILES,
)


def test_transitive_imports_and_an_unparseable_import(run, workdir):
    """CATCHES: imports of imports not resolved, a module imported along two paths analysed
    inconsistently, or an import that fails to parse breaking the importer's analysis."""
    _check(run, workdir, TRANSITIVE_CASE)


CYCLE_FILES = {"alpha.pyfun": "import Beta\nlet a = 1\n", "beta.pyfun": "import Alpha\nlet b = Alpha.a + 1\n"}
CYCLE_CASE = session(
    "cyclic_imports",
    did_open("{root}/alpha.pyfun", CYCLE_FILES["alpha.pyfun"]),
    did_open("{root}/beta.pyfun", CYCLE_FILES["beta.pyfun"]),
    hover(2, "{root}/beta.pyfun", CYCLE_FILES["beta.pyfun"], "b ="),
    did_change("{root}/alpha.pyfun", "import Beta\nlet a = 2.5\n"),
    hover(3, "{root}/beta.pyfun", CYCLE_FILES["beta.pyfun"], "b ="),
    files=CYCLE_FILES,
)


def test_cyclic_imports_are_analysed_without_looping(run, workdir):
    """CATCHES: an infinite loop on an import cycle, or a cycle-dependent result cached and
    served stale after one side of the cycle changes."""
    _check(run, workdir, CYCLE_CASE)


BUFFER_FIRST_CASE = session(
    "open_import_buffer_wins_and_invalidates",
    did_open(GEO_URI, "let area w h = w * h * 0.5\n"),
    did_open(MAIN_URI, MAIN),
    hover(2, MAIN_URI, MAIN, "floor"),
    did_change(GEO_URI, "let volume v = v\n"),
    hover(3, MAIN_URI, MAIN, "floor"),
    did_change(MAIN_URI, MAIN),
    did_close(GEO_URI),
    hover(4, MAIN_URI, MAIN, "floor"),
    did_change(MAIN_URI, MAIN),
    files=PROJECT,
)


def test_an_open_import_buffer_wins_over_disk_and_invalidates_dependents(run, workdir):
    """CATCHES: imports read from disk while the editor holds unsaved edits, a dependent's
    cached analysis not invalidated when its import's buffer changes, or not falling back
    to the disk copy once the import's buffer is closed."""
    _check(run, workdir, BUFFER_FIRST_CASE)


SHARED_EXPORTS_CASE = session(
    "exports_shared_between_documents",
    did_open("{root}/one.pyfun", "import Geometry\nlet x = Geometry.area 1 2\n"),
    did_open("{root}/two.pyfun", "import Geometry\nlet y = Geometry.area 3.0 4.0\n"),
    hover(2, "{root}/two.pyfun", "import Geometry\nlet y = Geometry.area 3.0 4.0\n", "y ="),
    hover(3, "{root}/one.pyfun", "import Geometry\nlet x = Geometry.area 1 2\n", "Geometry.area", delta=9),
    files={"geometry.pyfun": GEOMETRY},
)


def test_two_documents_share_an_imported_interface(run, workdir):
    """CATCHES: an imported module's interface computed once and then reused with the wrong
    instantiation (let-polymorphism lost across documents)."""
    _check(run, workdir, SHARED_EXPORTS_CASE)


# ============================================================== projects: navigation

XDEF_CASE = session(
    "definition_across_files",
    did_open(MAIN_URI, MAIN),
    definition(2, MAIN_URI, MAIN, "Geometry.area", delta=10),
    definition(3, MAIN_URI, MAIN, "Geometry.Circle", delta=10),
    definition(4, MAIN_URI, MAIN, "Geometry.Point", delta=10),
    definition(5, MAIN_URI, MAIN, "Geometry.Point", nth=1, delta=10),
    definition(6, MAIN_URI, MAIN, "Point }"),
    definition(7, MAIN_URI, MAIN, "floor", nth=1),
    definition(8, MAIN_URI, MAIN, "Holder"),
    definition(9, MAIN_URI, MAIN, "Geometry.Rect", delta=10),
    definition(10, MAIN_URI, MAIN, "Geometry.Point {", nth=1, delta=10),
    definition(11, MAIN_URI, MAIN, "x + y"),
    hover(12, MAIN_URI, MAIN, "Geometry.area", delta=10),
    hover(13, MAIN_URI, MAIN, "Geometry.Point", nth=1, delta=10),
    files=PROJECT,
)


def test_definition_jumps_across_files(run, workdir):
    """CATCHES: qualified references (`Geometry.area`, constructors, record tags, qualified and
    bare type annotations) that do not jump into the imported module's file, or local names
    that wrongly leave the current file."""
    _check(run, workdir, XDEF_CASE)


XDEF_BUFFER_CASE = session(
    "definition_across_files_uses_open_buffer",
    did_open(GEO_URI, "\n\n## moved down\nlet area w h = w * h\ntype Point = { x: int, y: int }\n"),
    did_open(MAIN_URI, MAIN),
    definition(2, MAIN_URI, MAIN, "Geometry.area", delta=10),
    definition(3, MAIN_URI, MAIN, "Point }"),
    definition(4, MAIN_URI, MAIN, "Geometry.Circle", delta=10),
    files=PROJECT,
)


def test_cross_file_definition_reads_the_open_buffer(run, workdir):
    """CATCHES: cross-file jumps computed from the disk copy while the target file is open
    with different (unsaved) content, or a jump to a member that no longer exists."""
    _check(run, workdir, XDEF_BUFFER_CASE)


XREFS_CASE = session(
    "references_across_files",
    did_open(MAIN_URI, MAIN),
    references(2, MAIN_URI, MAIN, "Geometry.area", delta=10),
    references(3, MAIN_URI, MAIN, "Geometry.area", delta=10, include=False),
    references(4, MAIN_URI, MAIN, "Geometry.Circle", delta=10),
    references(5, MAIN_URI, MAIN, "Geometry.Point", delta=10),
    references(6, MAIN_URI, MAIN, "Point }", include=False),
    references(7, MAIN_URI, MAIN, "floor"),
    did_open(GEO_URI, GEOMETRY),
    references(8, GEO_URI, GEOMETRY, "area w h"),
    references(9, GEO_URI, GEOMETRY, "Rect float"),
    references(10, GEO_URI, GEOMETRY, "Point =", include=False),
    files=PROJECT_PLUS,
)


def test_references_span_the_project(run, workdir):
    """CATCHES: find-references limited to the open file, missing pattern uses of an imported
    constructor, qualified uses whose range covers the `Geometry.` qualifier, or record tags
    and bare/qualified annotations of a type left out."""
    _check(run, workdir, XREFS_CASE)


XRENAME_CASE = session(
    "rename_across_files",
    did_open(MAIN_URI, MAIN),
    prepare_rename(2, MAIN_URI, MAIN, "Geometry.area", delta=10),
    rename(3, MAIN_URI, MAIN, "Geometry.area", "surface", delta=10),
    prepare_rename(4, MAIN_URI, MAIN, "Geometry.Circle", delta=10),
    rename(5, MAIN_URI, MAIN, "Geometry.Circle", "Disk", delta=10),
    rename(6, MAIN_URI, MAIN, "Geometry.Circle", "disk", delta=10),
    rename(7, MAIN_URI, MAIN, "Geometry.area", "Surface", delta=10),
    prepare_rename(8, MAIN_URI, MAIN, "floor"),
    rename(9, MAIN_URI, MAIN, "floor", "ground"),
    files=PROJECT_PLUS,
)


def test_rename_values_and_constructors_across_files(run, workdir):
    """CATCHES: a rename that edits only the open file, rewrites the `Geometry.` qualifier,
    misses constructor patterns, or lets a value become a constructor (and vice versa)."""
    _check(run, workdir, XRENAME_CASE)


XRENAME_TYPE_CASE = session(
    "rename_types_across_files",
    did_open(MAIN_URI, MAIN),
    prepare_rename(2, MAIN_URI, MAIN, "Geometry.Point", nth=1, delta=10),
    rename(3, MAIN_URI, MAIN, "Geometry.Point", "Spot", nth=1, delta=10),
    prepare_rename(4, MAIN_URI, MAIN, "Point }"),
    rename(5, MAIN_URI, MAIN, "Point }", "spot"),
    rename(6, MAIN_URI, MAIN, "Geometry.Point", "Spot", delta=10),
    prepare_rename(7, MAIN_URI, MAIN, "Holder"),
    rename(8, MAIN_URI, MAIN, "Holder", "Keeper"),
    files=PROJECT_PLUS,
)


def test_rename_types_across_files(run, workdir):
    """CATCHES: a type rename that misses the declaring file, qualified annotations, bare
    annotations, or record tags, or that accepts a lowercase type name."""
    _check(run, workdir, XRENAME_TYPE_CASE)


SHADOW_FILES = {
    "shapes.pyfun": "type Placed = { row: int }\n",
    "main.pyfun": "import Shapes\ntype Placed = { col: int }\ntype Holder = { a: Placed, b: Shapes.Placed }\n",
}
SHADOW_CASE = session(
    "local_type_shadows_imported",
    did_open(MAIN_URI, SHADOW_FILES["main.pyfun"]),
    rename(2, MAIN_URI, SHADOW_FILES["main.pyfun"], "Shapes.Placed", "Tile", delta=7),
    rename(3, MAIN_URI, SHADOW_FILES["main.pyfun"], "Placed,", "Spot"),
    references(4, MAIN_URI, SHADOW_FILES["main.pyfun"], "Placed =", include=True),
    files=SHADOW_FILES,
)


def test_a_local_type_shadows_an_imported_one(run, workdir):
    """CATCHES: renaming the imported `Shapes.Placed` also rewriting the local `Placed` (or
    the reverse), i.e. type identity decided by bare name instead of declaring module."""
    _check(run, workdir, SHADOW_CASE)


STRICT_FILES = {**PROJECT, "zbroken.pyfun": "import Geometry\nlet y = (Geometry.area 1\n"}
STRICT_CASE = session(
    "rename_refused_when_a_project_file_does_not_parse",
    did_open(MAIN_URI, MAIN),
    references(2, MAIN_URI, MAIN, "Geometry.area", delta=10),
    prepare_rename(3, MAIN_URI, MAIN, "Geometry.area", delta=10),
    rename(4, MAIN_URI, MAIN, "Geometry.area", "surface", delta=10),
    rename(5, MAIN_URI, MAIN, "Point }", "Spot"),
    prepare_rename(6, MAIN_URI, MAIN, "Point }"),
    files=STRICT_FILES,
)


def test_rename_is_refused_when_another_project_file_does_not_parse(run, workdir):
    """CATCHES: a cross-file rename that silently skips a file it cannot parse (an incomplete,
    unsound rewrite) instead of refusing, while find-references still works best-effort."""
    _check(run, workdir, STRICT_CASE)


WSYM_FILES = {
    **PROJECT_PLUS,
    "zbroken.pyfun": "let = 1\n",
    "notes.txt": "let ignored = 1\n",
    "sub/deeper.pyfun": "let hidden = 1\n",
}
WSYM_CASE = session(
    "workspace_symbols",
    did_open(MAIN_URI, MAIN),
    did_open(GEO_URI, GEOMETRY + "let areaBuffered = 1\n"),
    did_open("untitled:loose.pyfun", "let area51 = 1\n"),
    did_open("{root}/ghost/x.pyfun", "let areaGhost = 1\n"),
    plain(2, "workspace/symbol", {"query": "AREA"}),
    plain(3, "workspace/symbol", {"query": ""}),
    plain(4, "workspace/symbol", {}),
    plain(5, "workspace/symbol", {"query": "zzz"}),
    files=WSYM_FILES,
)


def test_workspace_symbols_search_the_project_directory(run, workdir):
    """CATCHES: workspace symbols limited to open documents, a case-sensitive query, files in
    subdirectories or other extensions included, unparseable files not skipped, duplicate
    results for two open files of one directory, or the disk copy used over an open buffer."""
    _check(run, workdir, WSYM_CASE)


SPACE_FILES = {"my dir/geometry.pyfun": GEOMETRY, "my dir/main.pyfun": MAIN}
SPACE_URI = "{root}/my%20dir/main.pyfun"
SPACE_CASE = session(
    "percent_encoded_project_directory",
    did_open(SPACE_URI, MAIN),
    definition(2, SPACE_URI, MAIN, "Geometry.area", delta=10),
    references(3, SPACE_URI, MAIN, "Geometry.area", delta=10),
    plain(4, "workspace/symbol", {"query": "desc"}),
    files=SPACE_FILES,
)


def test_percent_encoded_uris_resolve_to_the_directory(run, workdir):
    """CATCHES: URIs used as paths without percent-decoding (`my%20dir`), so imports,
    cross-file jumps and workspace symbols fail in a directory whose name has a space."""
    _check(run, workdir, SPACE_CASE)



TAG_FILES = {"tag.pyfun": "type Wrap = Wrap int\nlet w0 = Wrap 0\n",
             "user.pyfun": "import Tag\nlet w = Tag.Wrap 1\nlet un x =\n  match x:\n    case Tag.Wrap n: n\n"}
TAG_USER = TAG_FILES["user.pyfun"]
TAG_CASE = session(
    "constructor_sharing_its_type_name",
    did_open("{root}/user.pyfun", TAG_USER),
    definition(2, "{root}/user.pyfun", TAG_USER, "Tag.Wrap", delta=4),
    references(3, "{root}/user.pyfun", TAG_USER, "Tag.Wrap", delta=4),
    prepare_rename(4, "{root}/user.pyfun", TAG_USER, "Tag.Wrap", delta=4),
    rename(5, "{root}/user.pyfun", TAG_USER, "Tag.Wrap", "Boxed", delta=4),
    files=TAG_FILES,
)


def test_a_qualified_constructor_named_like_its_type_is_a_constructor(run, workdir):
    """CATCHES: `Tag.Wrap 1` (a constructor sharing its sum type's name) treated as a type
    reference, so navigation, references and rename act on the type instead of the
    constructor's construction and pattern uses."""
    _check(run, workdir, TAG_CASE)


# ============================================================== every syntactic form

SINK = (
    "extern import math\n"
    "extern pair : (int, int) -> List int = divmod\n"
    "opaque type UserId = string\n"
    "type Shape = Circle float | Rect float float\n"
    "type Cell = { pos: (int, int), tags: List string, f: int -> int }\n"
    "measure m\n"
    "let k = 2\n"
    "let mut counter = 0\n"
    "let uses n =\n"
    "  let a = if k > n then -k else k\n"
    "  let b = 1 < k < 10\n"
    "  let c = (k, [k, k])\n"
    "  let d = f\"k is {k}\"\n"
    "  let e = k |> (fun x -> x + k)\n"
    "  let g = (fun x -> x * k) >> (fun y -> y - k)\n"
    "  let h = (+) k\n"
    "  let t = try (pair (k, n))\n"
    "  let dist = 5.0<m>\n"
    "  a\n"
    "let rec2 cell = { cell with tags = [String.fromInt k] }\n"
    "let field cell = cell.pos\n"
    "let bump u =\n"
    "  counter <- counter + k\n"
    "let pats v =\n"
    "  match v:\n"
    "    case (0, _): k\n"
    "    case (1, 2): k\n"
    "    case (_, w) if w > k: k\n"
    "    case _: 0\n"
    "let strs s =\n"
    "  match s:\n"
    "    case \"a\": k\n"
    "    case _: 0\n"
    "let lists xs =\n"
    "  match xs:\n"
    "    case [*init, last]: last + k\n"
    "    case []: k\n"
    "let ors s =\n"
    "  match s:\n"
    "    case Circle _ | Rect _ _: k\n"
    "let bools b =\n"
    "  match b:\n"
    "    case true: k\n"
    "    case false: 0\n"
    "let sq = seq {\n"
    "  yield k\n"
    "  yield! Seq.ofList [k, k]\n"
    "  for i in [1, 2]:\n"
    "    yield i + k\n"
    "}\n"
    "let opt = option {\n"
    "  let! x = Some k\n"
    "  let y = x + k\n"
    "  return y\n"
    "}\n"
    "let ret = result {\n"
    "  do! Ok ()\n"
    "  return! Ok k\n"
    "}\n"
    "let cells c =\n"
    "  match c:\n"
    "    case Cell { pos, tags, f }: f k\n"
    "extern type Conn\n"
    "print k\n"
)
SU = "untitled:sink.pyfun"

SINK_REFS_CASE = session(
    "references_through_every_construct",
    did_open(SU, SINK),
    references(2, SU, SINK, "k = 2"),
    references(3, SU, SINK, "counter", include=True),
)
SINK_RENAME_CASE = session(
    "rename_through_every_construct",
    did_open(SU, SINK),
    rename(2, SU, SINK, "k = 2", "kay"),
)
SINK_DEFS_CASE = session(
    "definitions_of_pattern_and_ce_binders",
    did_open(SU, SINK),
    definition(2, SU, SINK, "w > k"),
    definition(3, SU, SINK, "last + k"),
    definition(4, SU, SINK, "i + k"),
    definition(5, SU, SINK, "x + k", nth=1),
    definition(6, SU, SINK, "y\n}"),
    definition(7, SU, SINK, "f k"),
    definition(8, SU, SINK, "cell.pos"),
    definition(9, SU, SINK, "n))"),
    definition(10, SU, SINK, "x * k"),
    definition(11, SU, SINK, "y - k"),
    definition(12, SU, SINK, "Cell {", nth=0),
    definition(13, SU, SINK, "Circle _"),
    definition(14, SU, SINK, "UserId"),
)
SINK_HOVERS_CASE = session(
    "hover_on_every_construct",
    did_open(SU, SINK),
    *[hover(i + 2, SU, SINK, needle) for i, needle in enumerate(
        ["a =", "b =", "c =", "d =", "e =", "g =", "h =", "t =", "dist", "rec2", "field", "bump",
         "sq =", "opt =", "ret =", "cells", "counter <-", "init", "{ cell with", "f\"k is", "|> (fun",
         "try (", "(+)", ">> (fun", "-k", "1 < k"])],
)
SINK_SYMBOLS_CASE = session(
    "document_symbols_of_every_declaration_kind",
    did_open(SU, SINK),
    plain(2, "textDocument/documentSymbol", {"textDocument": {"uri": SU}}),
)


def test_references_reach_every_expression_form(run, workdir):
    """CATCHES: a resolver that skips some syntax when collecting references (if/else, unary
    minus, chained comparisons, tuples, lists, f-string holes, pipes, composition, operator
    sections, try, record update, assignment, guards, CE yield/for/let!/do!/return!)."""
    _check(run, workdir, SINK_REFS_CASE)


def test_rename_rewrites_every_expression_form(run, workdir):
    """CATCHES: a rename that misses occurrences inside any expression form, rewrites a
    shadowing local, or emits overlapping edits."""
    _check(run, workdir, SINK_RENAME_CASE)


def test_definitions_of_pattern_and_ce_binders(run, workdir):
    """CATCHES: guard variables, list-rest and suffix patterns, `for` targets, option-CE
    binders, record-pattern fields and lambda parameters resolving to the wrong binder."""
    _check(run, workdir, SINK_DEFS_CASE)


def test_hover_on_every_construct(run, workdir):
    """CATCHES: hover types that differ for tuples, f-strings, composition, operator
    sections, `try` (Result ... Exception), unit literals, seq/option/result blocks, record
    updates, field access or mutable assignment."""
    _check(run, workdir, SINK_HOVERS_CASE)


def test_document_symbols_of_every_declaration_kind(run, workdir):
    """CATCHES: opaque types, records with function and tuple fields, measures, mutable lets
    or externs with tuple signatures missing from (or misclassified in) the outline, or an
    `extern import` wrongly listed as a symbol."""
    _check(run, workdir, SINK_SYMBOLS_CASE)


EDGE = (
    "import Geometry\n"
    "let n = 1\n"
    "type T = { m: Mystery, s: Geometry.Shape, b: Shape }\n"
    "let a = Geometry.area 1 2\n"
)
# `Geometry.pyfun` also names module `Geometry` (the stem with its first letter
# uppercased) but declares neither `area` nor `Shape`.
EDGE_FILES = {"geometry.pyfun": GEOMETRY, "Geometry.pyfun": "let unrelated = 1\n", "edge.pyfun": EDGE}
EDGE_CASE = session(
    "project_scan_edge_cases",
    did_open("{root}/edge.pyfun", EDGE),
    references(2, "{root}/edge.pyfun", EDGE, "Mystery"),
    references(3, "{root}/edge.pyfun", EDGE, "Geometry.Shape", delta=9),
    references(4, "{root}/edge.pyfun", EDGE, "Shape }"),
    references(5, "{root}/edge.pyfun", EDGE, "Geometry.area", delta=9),
    rename(6, "{root}/edge.pyfun", EDGE, "Geometry.Shape", "Figure", delta=9),
    files=EDGE_FILES,
)


def test_project_scans_with_an_unknown_type_and_a_second_file_for_the_module(run, workdir):
    """CATCHES: an unknown bare type in a project file treated as imported, a sum type's
    references missing its bare or qualified annotation uses, or a scan that stops (or
    crashes) at a second file whose stem names the same module but lacks the symbol."""
    _check(run, workdir, EDGE_CASE)


DECLARING_SIDE_CASE = session(
    "navigation_from_the_declaring_file",
    did_open(GEO_URI, GEOMETRY),
    definition(2, GEO_URI, GEOMETRY, "Point {"),
    definition(3, GEO_URI, GEOMETRY, "Circle r"),
    definition(4, GEO_URI, GEOMETRY, "w * h", nth=1),
    prepare_rename(5, GEO_URI, GEOMETRY, "area w h"),
    rename(6, GEO_URI, GEOMETRY, "area w h", "surface"),
    references(7, GEO_URI, GEOMETRY, "Circle float", include=False),
    prepare_rename(8, GEO_URI, GEOMETRY, "Circle float"),
    rename(9, GEO_URI, GEOMETRY, "Shape =", "Figure"),
    rename(10, GEO_URI, GEOMETRY, "r: r", "radius", delta=3),
    files=PROJECT,
)


def test_navigation_and_rename_from_the_declaring_file(run, workdir):
    """CATCHES: cross-file rename/references that only work from the importing side, a
    declaring file's own record tag jumping elsewhere, or a local in a project file
    renamed project-wide."""
    _check(run, workdir, DECLARING_SIDE_CASE)


REOPEN_CASE = session(
    "reopen_replaces_the_document",
    did_open("untitled:r.pyfun", "let v = 1\n"),
    hover(2, "untitled:r.pyfun", "let v = 1\n", "v"),
    did_open("untitled:r.pyfun", "let v = \"now a string\"\nlet w = v\n"),
    hover(3, "untitled:r.pyfun", "let v = 1\n", "v"),
    definition(4, "untitled:r.pyfun", "let v = \"now a string\"\nlet w = v\n", "v\n"),
)


def test_reopening_a_document_replaces_its_text(run, workdir):
    """CATCHES: a second didOpen of the same URI that is ignored, or a cached analysis of
    the first text served after the document was reopened."""
    _check(run, workdir, REOPEN_CASE)


RICH_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "processId": None, "rootUri": "file:///nowhere", "clientInfo": {"name": "test-client", "version": "1.0"},
    "capabilities": {"textDocument": {"hover": {"contentFormat": ["markdown", "plaintext"]},
                                      "synchronization": {"didSave": True, "willSave": False}},
                     "workspace": {"workspaceFolders": True}, "experimental": {"ratio": 0.75, "list": [[], {}]}},
    "trace": "off", "workspaceFolders": [{"uri": "file:///nowhere", "name": "nowhere"}]}}
RICH_INIT_CASE = raw_session("initialize_with_client_capabilities", RICH_INIT, INITIALIZED, SHUTDOWN, EXIT)


def test_initialize_ignores_client_capabilities(run, workdir):
    """CATCHES: a server whose initialize result depends on (or chokes on) a realistic,
    deeply nested client capabilities object."""
    _check(run, workdir, RICH_INIT_CASE)


LARGE_TEXT = "".join(f"let f{i} x = x + {i}\n" for i in range(1500)) + "let last = f1499 (f0 1)\n"
LARGE_CASE = session(
    "large_document",
    did_open("untitled:large.pyfun", LARGE_TEXT),
    hover(2, "untitled:large.pyfun", LARGE_TEXT, "last"),
    definition(3, "untitled:large.pyfun", LARGE_TEXT, "f1499 (", nth=0),
    references(4, "untitled:large.pyfun", LARGE_TEXT, "f0 1"),
    plain(5, "workspace/symbol", {"query": "f149"}),
)


def test_a_large_document(run, workdir):
    """CATCHES: positions miscomputed far into a long document, or a server too slow to
    answer for a 1500-definition file."""
    _check(run, workdir, LARGE_CASE)


PARTIAL_COMPLETION_TEXT = "type Mood = Glad | Sad\nlet cheer = 1\nlet broken = (\n"
PARTIAL_COMPLETION_CASE = session(
    "completion_on_a_broken_document",
    did_open("untitled:pc.pyfun", PARTIAL_COMPLETION_TEXT),
    request(2, "textDocument/completion", "untitled:pc.pyfun", 2, 14),
)


def test_completion_on_a_document_that_does_not_parse(run, workdir):
    """CATCHES: completion that drops the user symbols recovered from a partially parsed
    document instead of offering them ahead of the prelude."""
    _check(run, workdir, PARTIAL_COMPLETION_CASE)


BROKEN_IMPORT_BUFFER_CASE = session(
    "unparseable_import_buffer",
    did_open(GEO_URI, "let area w h =\n"),
    did_open(MAIN_URI, MAIN),
    did_change(GEO_URI, GEOMETRY),
    did_change(MAIN_URI, MAIN),
    files=PROJECT,
)


def test_an_unparseable_import_buffer_and_its_repair(run, workdir):
    """CATCHES: an importer that keeps stale (or crashes on) diagnostics when the imported
    file's open buffer does not parse, or is not re-analysed once that buffer is fixed."""
    _check(run, workdir, BROKEN_IMPORT_BUFFER_CASE)


MIXED_DIAG_CASE = session(
    "errors_before_holes",
    did_open("untitled:mixed.pyfun", "let a = ? + 1\nlet b = 1 + true\nlet c = String.len ?\n"),
)


def test_errors_are_published_before_hole_notes(run, workdir):
    """CATCHES: hole notes interleaved with or ahead of errors, or a hole suppressed by a
    type error elsewhere in the file."""
    _check(run, workdir, MIXED_DIAG_CASE)


WRONG_TYPES_CASE = session(
    "params_of_the_wrong_json_type",
    did_open("untitled:w.pyfun", "let v = 1\nlet w = v\n"),
    plain(2, "textDocument/hover", 5),
    plain(3, "textDocument/hover", {"textDocument": {"uri": 7}, "position": {"line": 0, "character": 4}}),
    plain(4, "textDocument/hover", {"textDocument": {"uri": "untitled:w.pyfun"},
                                    "position": {"line": "one", "character": 4}}),
    plain(5, "textDocument/definition", {"textDocument": {"uri": "untitled:w.pyfun"},
                                         "position": {"line": 1.0, "character": 8.9}}),
    {"jsonrpc": "2.0", "method": "textDocument/didChange",
     "params": {"textDocument": {"uri": "untitled:w.pyfun"}, "contentChanges": "let v = 2"}},
    plain(6, "workspace/symbol", {"query": 12}),
    plain(7, "textDocument/references", {"textDocument": {"uri": "untitled:w.pyfun"},
                                         "position": {"line": 0, "character": 4},
                                         "context": {"includeDeclaration": "yes"}}),
    plain(8, "textDocument/rename", {"textDocument": {"uri": "untitled:w.pyfun"},
                                     "position": {"line": 0, "character": 4}, "newName": 3}),
)


def test_params_of_the_wrong_json_type_are_tolerated(run, workdir):
    """CATCHES: a server that crashes on wrongly typed params instead of treating them as
    absent (non-object params, numeric URIs, string line numbers default to 0, fractional
    positions truncate, a non-array contentChanges is ignored, a non-boolean
    includeDeclaration counts as false)."""
    _check(run, workdir, WRONG_TYPES_CASE)


BUFFER_REFS_CASE = session(
    "references_read_open_importer_buffers",
    did_open(MAIN_URI, MAIN + "let more = Geometry.area 9 9\n"),
    did_open(GEO_URI, GEOMETRY),
    references(2, GEO_URI, GEOMETRY, "area w h"),
    rename(3, GEO_URI, GEOMETRY, "area w h", "surface"),
    files=PROJECT,
)


def test_project_references_read_open_buffers_over_disk(run, workdir):
    """CATCHES: project-wide references and rename computed from the disk copy of an importer
    that is open with unsaved uses, so the editor's newest occurrences are missed."""
    _check(run, workdir, BUFFER_REFS_CASE)
