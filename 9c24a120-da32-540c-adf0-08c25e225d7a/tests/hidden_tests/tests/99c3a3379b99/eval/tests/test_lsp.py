"""Black-box tests of the language server, `pyfun lsp` (README "Editor support", DESIGN.md §9).

Every test pipes one complete JSON-RPC session (`Content-Length` framing) into `pyfun lsp` on stdin
and compares the decoded responses with a golden captured from the reference binary under
eval/test_resources/test_lsp/. Sessions whose features read sibling files from disk use `file://`
URIs inside the test's workdir; that absolute directory is normalised to `/WORKDIR` (so
`file:///WORKDIR/main.pyfun`) before comparing, and everything else is compared exactly.
"""

import json

from conftest import golden, lsp_frame, lsp_unframe, write_files

SHUTDOWN = {"jsonrpc": "2.0", "id": 99, "method": "shutdown"}
EXIT = {"jsonrpc": "2.0", "method": "exit"}
INITIALIZE = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}


# ------------------------------------------------------------------------------------------ helpers

def expected(name):
    """The golden `name` (decoded when it is a `.json` list of messages, raw bytes otherwise)."""
    data = golden(__file__, name)
    return json.loads(data) if name.endswith(".json") else data


def session(*messages, finish=True) -> bytes:
    """Frame every message (dicts are JSON-encoded, bytes are sent verbatim) and, unless
    `finish=False`, end with `shutdown` + `exit`."""
    out = b""
    for message in messages:
        out += message if isinstance(message, bytes) else lsp_frame(message)
    if finish:
        out += lsp_frame(SHUTDOWN) + lsp_frame(EXIT)
    return out


def normalised(value, workdir):
    """`value` with the workdir's absolute (URI-encoded) path replaced by `/WORKDIR`, in keys too."""
    prefix = workdir.as_uri()[len("file://"):]
    if isinstance(value, str):
        return value.replace(prefix, "/WORKDIR")
    if isinstance(value, list):
        return [normalised(v, workdir) for v in value]
    if isinstance(value, dict):
        return {k.replace(prefix, "/WORKDIR"): normalised(v, workdir) for k, v in value.items()}
    return value


def replies(r, workdir):
    """The server's decoded outgoing messages, in order, with the workdir normalised."""
    return normalised(lsp_unframe(r.stdout), workdir)


def uri(workdir, rel):
    """A `file://` URI for `rel` (already URI-encoded) inside the workdir."""
    return workdir.as_uri() + "/" + rel


def where(text, needle, nth=1, plus=0):
    """LSP position {line, character} (UTF-16 columns) of the `nth` occurrence of `needle` in `text`,
    shifted `plus` characters into it."""
    idx = -1
    for _ in range(nth):
        idx = text.index(needle, idx + 1)
    idx += plus
    before = text[:idx]
    line = before.count("\n")
    column = before[before.rfind("\n") + 1:]
    return {"line": line, "character": len(column.encode("utf-16-le")) // 2}


def notify(method, params):
    return {"jsonrpc": "2.0", "method": method, "params": params}


def request(id_, method, params=None):
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return message


def did_open(doc, text):
    return notify("textDocument/didOpen",
                  {"textDocument": {"uri": doc, "languageId": "pyfun", "version": 1, "text": text}})


def did_change(doc, *texts):
    return notify("textDocument/didChange",
                  {"textDocument": {"uri": doc, "version": 2}, "contentChanges": [{"text": t} for t in texts]})


def did_close(doc):
    return notify("textDocument/didClose", {"textDocument": {"uri": doc}})


def at(id_, method, doc, position, **extra):
    return request(id_, method, {"textDocument": {"uri": doc}, "position": position, **extra})


def hover(id_, doc, position):
    return at(id_, "textDocument/hover", doc, position)


def definition(id_, doc, position):
    return at(id_, "textDocument/definition", doc, position)


def references(id_, doc, position, include=None):
    extra = {} if include is None else {"context": {"includeDeclaration": include}}
    return at(id_, "textDocument/references", doc, position, **extra)


def prepare_rename(id_, doc, position):
    return at(id_, "textDocument/prepareRename", doc, position)


def rename(id_, doc, position, new_name):
    return at(id_, "textDocument/rename", doc, position, newName=new_name)


def completion(id_, doc, position):
    return at(id_, "textDocument/completion", doc, position)


def document_symbol(id_, doc):
    return request(id_, "textDocument/documentSymbol", {"textDocument": {"uri": doc}})


def workspace_symbol(id_, query):
    return request(id_, "workspace/symbol", {"query": query})


def raw_frame(body: bytes, header: bytes = None) -> bytes:
    """A frame with a hand-written header block (default: the standard one) around raw `body` bytes."""
    if header is None:
        header = b"Content-Length: %d\r\n\r\n" % len(body)
    return header + body


# ------------------------------------------------------------------------- protocol and framing

def test_initialize_reply_is_byte_exact(run):
    """CATCHES: an initialize result that drops or renames a capability (sync kind, rename prepare
    support, completion/symbol providers), changes serverInfo, emits `1.0` instead of `1`, or frames
    the reply with a wrong Content-Length or non-compact JSON."""
    r = run(["lsp"], input=session(
        request(1, "initialize", {"processId": None, "rootUri": None, "capabilities": {}}),
        notify("initialized", {}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert r.stdout == expected("initialize.bin")


def test_exit_stops_the_server_before_later_messages(run, workdir):
    """CATCHES: a server that keeps reading after the `exit` notification (answering the requests
    queued behind it) or that answers `shutdown` with something other than a null result."""
    doc = "untitled:after-exit"
    r = run(["lsp"], input=session(
        INITIALIZE,
        request(1, "shutdown"),
        EXIT,
        did_open(doc, "let n = 1"),
        hover(2, doc, {"line": 0, "character": 4}),
        finish=False,
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("exit_stops.json")


def test_end_of_input_without_exit_terminates_cleanly(run, workdir):
    """CATCHES: a server that hangs, crashes or exits non-zero when stdin reaches EOF without an
    `exit` notification, or that drops the replies written before EOF."""
    r = run(["lsp"], input=session(INITIALIZE, request(5, "shutdown"), finish=False))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("eof_without_exit.json")


def test_unknown_request_errors_but_unknown_notification_is_ignored(run, workdir):
    """CATCHES: answering an unknown notification (no id), not replying to an unknown request with
    the JSON-RPC -32601 `method not found` error, or replying to id-bearing messages that have no
    string `method` (client responses, non-object messages)."""
    r = run(["lsp"], input=session(
        request(1, "textDocument/formatting", {"textDocument": {"uri": "untitled:x"}}),
        notify("$/cancelRequest", {"id": 1}),
        notify("workspace/didChangeConfiguration", {"settings": {}}),
        {"jsonrpc": "2.0", "id": 2, "result": {"applied": True}},
        {"jsonrpc": "2.0", "id": 3, "method": 42},
        [1, 2, 3],
        "42",
        request("abc", "workspace/executeCommand", {"command": "x"}),
        {"jsonrpc": "2.0", "id": None, "method": "custom/thing"},
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("unknown_methods.json")


def test_malformed_json_frames_are_skipped(run, workdir):
    """CATCHES: a JSON reader that crashes, stops, or half-accepts invalid bodies (trailing data,
    missing commas/colons, bad escapes, broken \\u escapes and surrogates, bad literals/numbers)
    instead of ignoring the frame and serving the following valid requests."""
    bad = [
        b'{"jsonrpc":"2.0","id":1,"method":"shutdown"} trailing',
        b'{"jsonrpc":"2.0","id":2,"method":"shutdown"',
        b'{"jsonrpc":"2.0" "id":3,"method":"shutdown"}',
        b'{"id" 4,"method":"shutdown"}',
        b'{"id":5,"method":"shutdown",}',
        b'{id:6}',
        b'[1 2]',
        b'[1,',
        b'"\\q"',
        b'"unterminated',
        b'"\\u12"',
        b'"\\uZZZZ"',
        b'"\\ud83dx"',
        b'"\\udc00"',
        b'tru',
        b'fals',
        b'nul',
        b'-',
        b'1.2.3',
        b'@',
        b'',
        b'   ',
    ]
    r = run(["lsp"], input=session(
        *[raw_frame(body) for body in bad],
        request(7, "shutdown"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("malformed_json.json")


def test_request_ids_and_escapes_echo_byte_exact(run):
    """CATCHES: a JSON layer that mangles echoed ids: wrong number formatting (`2.5`, `1e3` -> `1000`,
    negatives), booleans/null not round-tripped, lost escapes (\\" \\\\ \\/ \\b \\f \\n \\r \\t \\u00e9, surrogate pairs) or control
    characters written raw instead of as \\u00XX escapes."""
    ids = [
        b'7', b'-3', b'2.5', b'1e3', b'0.125', b'null', b'false', b'true', b'"plain"',
        b'"q\\"uote \\\\ slash\\/ \\b\\f\\n\\r\\t \\u00e9 \\ud83d\\ude00 \\u0001\\u001f"',
        "\"caf\u00e9 \u2603 \U0001F600\"".encode(),
    ]
    frames = [raw_frame(b'{"jsonrpc":"2.0","id":%s,"method":"shutdown"}' % i) for i in ids]
    r = run(["lsp"], input=session(*frames, finish=False) + lsp_frame(EXIT))
    assert r.returncode == 0
    assert r.stderr == b""
    assert r.stdout == expected("id_echo.bin")


def test_whitespace_and_nested_json_values_are_parsed(run, workdir):
    """CATCHES: a JSON parser that rejects insignificant whitespace (spaces, tabs, CR/LF between
    tokens), empty objects/arrays, nested arrays of mixed literals, or exponent/negative numbers in
    params — so a pretty-printing client could not talk to the server."""
    body = (b'{\r\n\t"jsonrpc" : "2.0" ,\n  "id" : 4 ,\n  "method" : "initialize" ,\n'
            b'  "params" : { "capabilities" : { } , "workspaceFolders" : [ ] ,\n'
            b'    "initializationOptions" : [ true , false , null , -1.5e2 , 3E-1 , [ [ ] , { "k" : "v" } ] ]'
            b' }\n}\n')
    r = run(["lsp"], input=session(raw_frame(body)))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("whitespace_json.json")


def test_missing_content_length_header_ends_the_session(run, workdir):
    """CATCHES: a framing reader that guesses a body length (or crashes) when a header block has no
    `Content-Length`; the reference stops reading there and exits 0, so later frames get no reply."""
    r = run(["lsp"], input=session(
        INITIALIZE,
        raw_frame(b'{"jsonrpc":"2.0","id":1,"method":"shutdown"}', header=b"Content-Type: application/json\r\n\r\n"),
        request(2, "shutdown"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("missing_content_length.json")


def test_truncated_body_is_reported_as_a_server_error(run, workdir):
    """CATCHES: silently succeeding (exit 0) or hanging when stdin ends in the middle of a body
    whose Content-Length promises more bytes; the reference fails with an `lsp server error`."""
    r = run(["lsp"], input=session(INITIALIZE, finish=False)
            + b'Content-Length: 500\r\n\r\n{"jsonrpc":"2.0","id":1,"method":"shutdown"}')
    assert r.returncode == 1
    assert r.stderr == b"error: lsp server error: failed to fill whole buffer\n"
    assert replies(r, workdir) == expected("truncated_body.json")


def test_header_variants_are_accepted(run, workdir):
    """CATCHES: a header parser that only accepts exactly `Content-Length: N\\r\\n\\r\\n`: extra
    headers (Content-Type), bare LF line endings and padding around the length must all work, and
    invalid UTF-8 in a body is decoded lossily rather than dropping the frame."""
    shutdown = b'{"jsonrpc":"2.0","id":1,"method":"shutdown"}'
    opened = b'{"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":' \
             b'{"uri":"untitled:bytes","text":"let s = \\"\xff\xfe\\"\\nlet n = s + 1"}}}'
    r = run(["lsp"], input=session(
        raw_frame(shutdown, header=b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
                                   b"Content-Length: %d\r\n\r\n" % len(shutdown)),
        raw_frame(shutdown.replace(b"1", b"2"), header=b"Content-Length: %d\n\n" % len(shutdown)),
        raw_frame(shutdown.replace(b"1", b"3"), header=b"Content-Length:    %d   \r\n\r\n" % len(shutdown)),
        raw_frame(opened),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("header_variants.json")


# ------------------------------------------------------------------------------------- diagnostics

def test_clean_document_publishes_empty_diagnostics(run, workdir):
    """CATCHES: a server that publishes nothing on didOpen, publishes for the wrong URI, or reports
    spurious diagnostics (or holes) for a program that type-checks cleanly."""
    doc = "untitled:clean"
    r = run(["lsp"], input=session(INITIALIZE, notify("initialized", {}),
                                   did_open(doc, "let add a b = a + b\nlet seven = add 3 4\nprint seven")))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("diag_clean.json")


def test_type_errors_are_published_as_errors_with_ranges(run, workdir):
    """CATCHES: wrong severity (must be 1 = Error), missing `source: pyfun`, wrong message text,
    byte offsets reported instead of line/UTF-16 columns, or only the first of several type errors
    being published."""
    doc = "untitled:bad"
    text = "let r = 1 + true\nlet s = \"éé\" + 1\nlet pure p x = print x\nlet u = undefinedName"
    r = run(["lsp"], input=session(did_open(doc, text)))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("diag_type_errors.json")


def test_parse_error_keeps_the_rest_of_the_file_navigable(run, workdir):
    """CATCHES: a non-resilient analysis that blanks the whole file on a syntax error: the syntax
    diagnostic must be published (type errors suppressed) while hover, definition and the outline
    still work on the items that parsed, and rename/prepareRename are refused."""
    doc = "untitled:partial"
    text = "let good = 1\nlet bad =\nlet also = good + true"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "good")),
        definition(2, doc, where(text, "good", 2)),
        document_symbol(3, doc),
        prepare_rename(4, doc, where(text, "good")),
        rename(5, doc, where(text, "good"), "fine"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("diag_parse_error.json")


def test_lex_error_is_diagnosed_without_losing_earlier_items(run, workdir):
    """CATCHES: a lexer error (unterminated string, stray character) that aborts analysis: each lex
    error must be published, sorted by position, and hover must still work on the clean item."""
    doc = "untitled:lexerr"
    text = "let good = 1\nlet odd = 2 $ 3\nlet s = \"oops"
    r = run(["lsp"], input=session(did_open(doc, text), hover(1, doc, where(text, "good"))))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("diag_lex_error.json")


def test_typed_holes_are_information_and_hover_their_type(run, workdir):
    """CATCHES: publishing typed holes as errors (they must be severity 3 = Information), dropping
    the hole's inferred type / suggestions from the message, or hover not showing the hole's type."""
    doc = "untitled:holes"
    text = "let f = ?body + 1\nlet g = String.concat ? \"x\""
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "?body", plus=1)),
        hover(2, doc, where(text, "? ")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("diag_holes.json")


def test_holes_are_not_published_while_the_file_has_syntax_errors(run, workdir):
    """CATCHES: publishing hole notes (or type errors) alongside syntax errors; until the file
    parses only the syntax diagnostics are reported, and holes reappear once it is fixed."""
    doc = "untitled:holes-broken"
    r = run(["lsp"], input=session(
        did_open(doc, "let f = ?body + 1\nlet broken ="),
        did_change(doc, "let f = ?body + 1"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("diag_holes_broken.json")


def test_did_change_republishes_from_the_last_full_text(run, workdir):
    """CATCHES: ignoring didChange, applying the first instead of the last content change of a
    full-sync notification, or serving hover from a stale cached analysis of the old text."""
    doc = "untitled:edit"
    r = run(["lsp"], input=session(
        did_open(doc, "let n = 1"),
        hover(1, doc, {"line": 0, "character": 4}),
        did_change(doc, "let n = 1 + true", "let n = \"text\"\nlet m = n + 1"),
        hover(2, doc, {"line": 0, "character": 4}),
        did_change(doc, "let n = 2.5"),
        hover(3, doc, {"line": 0, "character": 4}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("did_change.json")


def test_incomplete_document_notifications_are_ignored(run, workdir):
    """CATCHES: crashing or publishing on didOpen without text, didChange without (or with empty)
    contentChanges or without a URI, didClose without a URI; such a document must stay unknown."""
    doc = "untitled:never"
    r = run(["lsp"], input=session(
        notify("textDocument/didOpen", {"textDocument": {"uri": doc}}),
        notify("textDocument/didOpen", {"textDocument": {"text": "let n = 1"}}),
        notify("textDocument/didOpen", {}),
        notify("textDocument/didChange", {"textDocument": {"uri": doc}}),
        notify("textDocument/didChange", {"textDocument": {"uri": doc}, "contentChanges": []}),
        notify("textDocument/didChange", {"textDocument": {"uri": doc}, "contentChanges": "let n = 1"}),
        notify("textDocument/didChange", {"textDocument": {"uri": doc}, "contentChanges": [{"range": None}]}),
        notify("textDocument/didChange", {"contentChanges": [{"text": "let n = 1"}]}),
        notify("textDocument/didClose", {"textDocument": {}}),
        notify("textDocument/didClose", {}),
        hover(1, doc, {"line": 0, "character": 4}),
        document_symbol(2, doc),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("incomplete_notifications.json")


def test_did_change_of_an_unopened_document_opens_it(run, workdir):
    """CATCHES: a server that drops a full-sync didChange for a URI it has not seen opened; the
    reference stores the text and publishes diagnostics for it like an open."""
    doc = "untitled:late"
    r = run(["lsp"], input=session(
        did_change(doc, "let x = 1 + true"),
        hover(1, doc, {"line": 0, "character": 4}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("change_unopened.json")


def test_did_close_clears_diagnostics_and_forgets_the_document(run, workdir):
    """CATCHES: not clearing diagnostics on close (an empty publishDiagnostics is required), or
    still answering hover/definition/references/symbols/rename from the closed buffer."""
    doc = "untitled:closing"
    text = "let one = 1 + true\nlet two = one"
    use = where(text, "one", 2)
    r = run(["lsp"], input=session(
        did_open(doc, text),
        did_close(doc),
        hover(1, doc, use),
        definition(2, doc, use),
        references(3, doc, use),
        document_symbol(4, doc),
        prepare_rename(5, doc, use),
        rename(6, doc, use, "uno"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("did_close.json")


# ------------------------------------------------------------------------------------------- hover

def test_hover_shows_types_with_effect_lines(run, workdir):
    """CATCHES: hover that hides effects: an impure function must show its `->{io}` arrow and a
    dedicated `**Effect:**` line (also for async, an effect on a curried inner arrow, and an
    extern), while a pure function gets no effect line."""
    doc = "untitled:effects"
    text = ("let greet name = print name\n"
            "let add a b = a + b\n"
            "let later x = async { return x }\n"
            "let shout prefix msg = print (String.concat prefix msg)\n"
            "extern ask: string ->{io} string = input\n"
            "let answer = ask \"name? \"\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "greet")),
        hover(2, doc, where(text, "add")),
        hover(3, doc, where(text, "later")),
        hover(4, doc, where(text, "shout")),
        hover(5, doc, where(text, "ask", 2)),
        hover(6, doc, where(text, "answer")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("hover_effects.json")


def test_hover_picks_the_narrowest_expression(run, workdir):
    """CATCHES: hover returning the enclosing binding's type instead of the innermost node under the
    cursor (parameter binder, parameter use, literal, sub-application), or a non-null result on
    whitespace / operators / past the end of the document."""
    doc = "untitled:narrow"
    text = "let inc n = n + 1\nlet ratio = inc 2 > 1\n"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "n =")),
        hover(2, doc, where(text, "n +")),
        hover(3, doc, where(text, "1\n")),
        hover(4, doc, where(text, "inc 2")),
        hover(5, doc, where(text, "2 >")),
        hover(6, doc, where(text, " = n")),
        hover(7, doc, {"line": 0, "character": 400}),
        hover(8, doc, {"line": 40, "character": 0}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("hover_narrowest.json")


def test_hover_appends_doc_comments(run, workdir):
    """CATCHES: hover ignoring `##` doc comments, attaching them only at the declaration (not at
    references), collapsing multi-line docs (each break must become a Markdown hard break), or
    returning null for a documented type/extern that has no inferred-type entry."""
    doc = "untitled:docs"
    text = ("## Doubles a number.\n## Works on ints.\nlet double x = x * 2\n"
            "let r = double 4\n"
            "## A 2D point.\ntype Point = { x: int, y: int }\n"
            "## A traffic signal.\ntype Signal = Walk | Wait\n"
            "## Square root, from Python.\nextern root: float -> float = math.sqrt\n"
            "type Plain = Plain int\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "double")),
        hover(2, doc, where(text, "double", 2)),
        hover(3, doc, where(text, "r =")),
        hover(4, doc, where(text, "Point")),
        hover(5, doc, where(text, "Signal")),
        hover(6, doc, where(text, "root:")),
        hover(7, doc, where(text, "Plain")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("hover_docs.json")


def test_hover_documents_builtins_unless_shadowed(run, workdir):
    """CATCHES: hover missing the built-in documentation of a qualified member (`List.contains`) or a
    global prelude function (`fst`), or showing the prelude's doc for a user definition that
    shadows a built-in name (`max`)."""
    doc = "untitled:builtins"
    text = ("let hit = List.contains 1 [1, 2]\n"
            "let a = fst (1, 2)\n"
            "## Mine.\nlet max a = a\n"
            "let n = max 1\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "contains")),
        hover(2, doc, where(text, "fst")),
        hover(3, doc, where(text, "max", 2)),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("hover_builtins.json")


def test_positions_count_utf16_code_units(run, workdir):
    """CATCHES: treating LSP `character` as bytes or Unicode scalars: after an astral emoji (2 UTF-16
    units, 4 bytes) and `é` (1 unit, 2 bytes) hover/definition must land on the right identifier and
    reply with UTF-16 ranges."""
    doc = "untitled:utf16"
    text = "let n = 5\nlet pair = (\"\U0001F600é\", n)\nlet bad = (\"\U0001F600\", 1 + true)"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "n)")),
        definition(2, doc, where(text, "n)")),
        hover(3, doc, where(text, "\U0001F600é", plus=1)),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("utf16_positions.json")


def test_position_requests_without_a_usable_document_return_empty(run, workdir):
    """CATCHES: crashing or answering with stale data when a request lacks params / position /
    textDocument, or names a document that was never opened: hover, definition and prepareRename
    must reply null, references and documentSymbol an empty array."""
    doc = "untitled:known"
    r = run(["lsp"], input=session(
        did_open(doc, "let n = 1"),
        request(1, "textDocument/hover"),
        request(2, "textDocument/hover", {"textDocument": {"uri": doc}}),
        hover(3, "untitled:unknown", {"line": 0, "character": 4}),
        request(4, "textDocument/definition", {"textDocument": {"uri": doc}}),
        definition(5, "untitled:unknown", {"line": 0, "character": 4}),
        request(6, "textDocument/references", {"position": {"line": 0, "character": 4}}),
        references(7, "untitled:unknown", {"line": 0, "character": 4}),
        request(8, "textDocument/prepareRename", {"textDocument": {"uri": doc}}),
        request(9, "textDocument/rename", {"textDocument": {"uri": doc}, "position": {"line": 0, "character": 4}}),
        request(10, "textDocument/documentSymbol", {}),
        hover(11, doc, {"line": "zero", "character": None}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("missing_params.json")


# -------------------------------------------------------------------------------------- definition

LOCALS = """let total xs = List.fold (fun acc x -> acc + x) 0 xs
let evens = seq {
  for n in [1, 2, 3]:
    yield n * 2
}
let describe o =
  match o:
    case Some (v as w): v + w
    case None: 0
let msg name = f"hi {name}"
let countdown k = if k == 0 then 0 else countdown (k - 1)
let checked ok v =
  result {
    let! x = if ok then Ok v else Error 0
    let y = x + 1
    return y
  }
let block a =
  let b = a * 2
  let (c, d) = (b, b)
  c + d
let (w, h) = (3, 4)
let area = w * h
"""


def test_definition_of_locals_and_top_level_values(run, workdir):
    """CATCHES: a name resolver without lexical scopes: lambda/for/match/`as`/CE (`let!`, `let`) and
    block-local binders, interpolation holes, destructured elements and recursive calls must each
    jump to their own binder or definition span, not to an outer name or the whole binding."""
    doc = uri(workdir, "nodisk/locals.pyfun")
    text = LOCALS
    r = run(["lsp"], input=session(
        did_open(doc, text),
        definition(1, doc, where(text, "acc + x")),
        definition(2, doc, where(text, "x) 0")),
        definition(3, doc, where(text, "xs\n")),
        definition(4, doc, where(text, "n * 2")),
        definition(5, doc, where(text, "v + w")),
        definition(6, doc, where(text, "w\n    case")),
        definition(7, doc, where(text, "name}")),
        definition(8, doc, where(text, "countdown (k")),
        definition(9, doc, where(text, "x + 1")),
        definition(10, doc, where(text, "y\n  }")),
        definition(11, doc, where(text, "c + d")),
        definition(12, doc, where(text, "d\n")),
        definition(13, doc, where(text, "b, b)", plus=3)),
        definition(14, doc, where(text, "h\n")),
        definition(15, doc, where(text, "o =")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("definition_locals.json")


def test_definition_of_constructors_types_and_builtins(run, workdir):
    """CATCHES: go-to-definition that cannot reach constructors (construction and pattern uses),
    user types in annotations and record tags, or active-pattern cases; or that invents a location
    for a built-in (`print`, `int`, `Some`) or for whitespace instead of returning null."""
    doc = uri(workdir, "nodisk/types.pyfun")
    text = ("type Shape = Circle float | Square float\n"
            "type Box = { item: Shape, count: int }\n"
            "let unit = Circle 1.0\n"
            "let size s =\n  match s:\n    case Circle r: r\n    case Square w: w\n"
            "let b = Box { item = unit, count = 1 }\n"
            "let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n"
            "let parity n =\n  match n:\n    case Even: \"even\"\n    case Odd: \"odd\"\n"
            "let shown = print (Some 1)\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        definition(1, doc, where(text, "Circle 1.0")),
        definition(2, doc, where(text, "Square w")),
        definition(3, doc, where(text, "Shape,")),
        definition(4, doc, where(text, "Box {")),
        definition(5, doc, where(text, "Even:")),
        definition(6, doc, where(text, "Odd\n")),
        definition(7, doc, where(text, "unit,")),
        definition(8, doc, where(text, "print")),
        definition(9, doc, where(text, "Some 1")),
        definition(10, doc, where(text, "int }")),
        definition(11, doc, where(text, "  match s")),
        definition(12, doc, where(text, "Shape =")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("definition_types.json")


SINK = """extern type Conn
extern open_: (int, string) -> Conn = tuple
extern parseInt: string -> int = int
type Point = { x: int, y: int }
type Color = Red | Green | Blue
measure m
module Geom =
  let square s = s * s
let scaled a b =
  let mut acc = a
  acc <- acc + b
  acc
let classify c =
  match c:
    case Red | Green: 1
    case Blue: 2
let ends xs d =
  match xs:
    case [first, *mid, last]: first + last + List.len mid
    case _: d
let sumPair t =
  match t:
    case (p, q) if p > q: p - q
    case (p, q): q - p
let either t =
  match t:
    case (0, k) | (k, 0): k
    case _: 0
let px pt =
  match pt:
    case Point { x = vx, y = vy }: vx + vy
let moved pt = { pt with x = pt.x + 1 }
let between lo v hi = lo < v < hi
let neg n = -n
let flipb b = not b
let inc = (+) 1
let piped v = v |> inc |> Geom.square
let composed = inc >> Geom.square
let measured = 5<m>
let parsed s = try (parseInt s)
let gen xs =
  seq {
    yield! xs
    yield 0
  }
let chained =
  result {
    do! Ok ()
    return! Ok 1
  }
print (scaled 1 2)
"""


def test_navigation_reaches_into_every_expression_and_pattern_form(run, workdir):
    """CATCHES: a resolver walk that skips some syntax: names inside in-file module members, `<-`
    assignments, list patterns (prefix, `*rest`, suffix), or-patterns, guards, record patterns and
    updates, field access, comparison chains, unary ops, pipes/composition, `try`, unit
    annotations, `yield!`/`do!`/`return!` and top-level expressions must resolve to their binders,
    and type uses inside tuple types and extern signatures must be found."""
    doc = uri(workdir, "nodisk/sink.pyfun")
    text = SINK
    targets = [("s * s", 1, 0), ("acc + b", 1, 0), ("first +", 1, 0), ("mid\n", 1, 0), ("last +", 1, 0),
               ("_: d", 1, 3), ("q:", 1, 0), ("k\n", 1, 0), ("vx +", 1, 0), ("pt.x", 1, 0), ("v < hi", 1, 0),
               ("-n", 1, 1), ("not b", 1, 4), ("inc |>", 1, 0), ("xs\n", 1, 0), ("s)", 1, 0),
               ("scaled 1", 1, 0), ("vy\n", 1, 0), ("Geom.square\nlet composed", 1, 6)]
    requests = [definition(i, doc, where(text, needle, nth, plus))
                for i, (needle, nth, plus) in enumerate(targets, start=1)]
    r = run(["lsp"], input=session(
        did_open(doc, text),
        *requests,
        references(50, doc, where(text, "Conn", 2)),
        references(51, doc, where(text, "inc")),
        references(52, doc, where(text, "Point {")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("navigation_all_forms.json")


GEOMETRY = "## Area of a rectangle.\nlet area w h = w * h\ntype Point = { x: int, y: int }\n"
MAIN_GEOMETRY = ("import Geometry\n"
                 "let floor = Geometry.area 4 5\n"
                 "let p = Geometry.Point { x = 1, y = 2 }\n"
                 "let q = Geometry . area 1 2\n")


def test_definition_jumps_across_files_to_a_sibling_on_disk(run, workdir):
    """CATCHES: cross-file navigation that ignores imports: `Geometry.area` and the qualified record
    tag `Geometry.Point` must resolve to geometry.pyfun (read from disk next to the document), and
    hover on the qualified use must show the imported type without any `not a member` error."""
    write_files(workdir, {"geometry.pyfun": GEOMETRY})
    doc = uri(workdir, "main.pyfun")
    text = MAIN_GEOMETRY
    r = run(["lsp"], input=session(
        did_open(doc, text),
        definition(1, doc, where(text, "area 4")),
        definition(2, doc, where(text, "Geometry.area", plus=2)),
        definition(3, doc, where(text, "Point {")),
        definition(4, doc, where(text, "area 1")),
        hover(5, doc, where(text, "area 4")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("definition_cross_file.json")


def test_definition_and_references_of_imported_types(run, workdir):
    """CATCHES: type navigation that stays in-file: a bare imported type (`Placed`), a qualified
    annotation (`Shapes.Placed`) and a qualified record tag must jump to shapes.pyfun, while a type
    declared locally resolves locally even when the import declares the same name; references of an
    imported sum type list its declaration and the importer's uses."""
    write_files(workdir, {"shapes.pyfun": "type Placed = { row: int, col: int }\ntype Kind = Dot | Dash\n"
                                          "type Line = { len: int }\n"})
    doc = uri(workdir, "main.pyfun")
    text = ("import Shapes\n"
            "type Holder = { item: Shapes.Placed, spare: Placed, kind: Kind }\n"
            "let p = Shapes.Placed { row = 1, col = 2 }\n"
            "type Line = { width: int }\n"
            "type Seg = { l: Line }\n")
    write_files(workdir, {"main.pyfun": text})
    r = run(["lsp"], input=session(
        did_open(doc, text),
        definition(1, doc, where(text, "Placed,")),
        definition(2, doc, where(text, "Placed, kind")),
        definition(3, doc, where(text, "Placed {")),
        definition(4, doc, where(text, "Kind }")),
        definition(5, doc, where(text, "Line }")),
        definition(6, doc, where(text, "Holder")),
        references(7, doc, where(text, "Kind }")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("definition_imported_types.json")


def test_definition_prefers_an_open_buffer_over_the_disk_file(run, workdir):
    """CATCHES: cross-file features that always read the disk: when the imported module is open in
    the editor its unsaved buffer (where `area` moved to line 2) must be used for go-to-definition
    and for the import-aware type check."""
    write_files(workdir, {"geometry.pyfun": "let area w h = w * h\n"})
    geometry = uri(workdir, "geometry.pyfun")
    doc = uri(workdir, "main.pyfun")
    text = "import Geometry\nlet floor = Geometry.area \"a\"\n"
    r = run(["lsp"], input=session(
        did_open(geometry, "# moved\n\nlet area s = String.upper s\n"),
        did_open(doc, text),
        definition(1, doc, where(text, "area")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("definition_open_buffer.json")


def test_definition_into_a_missing_or_broken_module_returns_null(run, workdir):
    """CATCHES: inventing a location (or crashing) when the imported sibling file is missing, does
    not parse, or lacks the member; such qualified uses (values, record tags, constructor patterns)
    are reported as errors instead."""
    write_files(workdir, {"broken.pyfun": "let x =\n", "small.pyfun": "let y = 1\n"})
    doc = uri(workdir, "main.pyfun")
    text = ("import Missing\nimport Broken\nimport Small\n"
            "let a = Missing.thing\nlet b = Broken.x\nlet c = Small.z\nlet d = Small.y\n"
            "let p = Missing.Point { x = 1 }\n"
            "let f s =\n  match s:\n    case Missing.Circle r: r\n    case _: 0\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        definition(1, doc, where(text, "thing")),
        definition(2, doc, where(text, "Broken.x", plus=7)),
        definition(3, doc, where(text, "Small.z", plus=6)),
        definition(4, doc, where(text, "Small.y", plus=6)),
        definition(5, doc, where(text, "Point")),
        definition(6, doc, where(text, "Circle")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("definition_missing_module.json")


# -------------------------------------------------------------------------------------- references

def test_references_of_a_top_level_value_in_one_file(run, workdir):
    """CATCHES: find-references that ignores `includeDeclaration` (true, false, or omitted = true),
    only works from a use (not from the definition name), or misses uses inside nested expressions
    and interpolation holes."""
    doc = uri(workdir, "nodisk/refs.pyfun")
    text = "let one = 1\nlet two = one + one\nlet three = f\"{one}{two}\"\n"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        references(1, doc, where(text, "one"), include=True),
        references(2, doc, where(text, "one"), include=False),
        references(3, doc, where(text, "one", 3)),
        references(4, doc, where(text, "two", 2), include=False),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_value.json")


def test_references_of_locals_stay_within_their_scope(run, workdir):
    """CATCHES: treating locals as module names: a parameter's references must not include a
    same-named top-level value or a shadowing inner binder, and pattern / CE binders must be found
    from either the binder or a use."""
    doc = uri(workdir, "nodisk/locals.pyfun")
    text = ("let x = 10\n"
            "let add x y = x + y + x\n"
            "let pick o =\n  match o:\n    case Some x: x * x\n    case None: x\n"
            "let ce = result {\n  let! v = Ok 1\n  return v + v\n}\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        references(1, doc, where(text, "x y")),
        references(2, doc, where(text, "x\n", 1), include=False),
        references(3, doc, where(text, "x * x", plus=4)),
        references(4, doc, where(text, "v = Ok")),
        references(5, doc, where(text, "x = 10")),
        references(6, doc, where(text, " = 10")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_locals.json")


def test_references_of_a_type_in_one_file(run, workdir):
    """CATCHES: type find-references that misses annotation uses (record fields, variant payloads,
    extern signatures, opaque underlying types) or bare record tags, or that ignores
    `includeDeclaration`; a built-in type (`List`) yields only its annotation uses."""
    doc = uri(workdir, "nodisk/types.pyfun")
    text = ("type Shape = Mk int\n"
            "type Box = { it: Shape, more: List Shape }\n"
            "type Wrap = Wrapped Shape\n"
            "opaque type Id = Shape\n"
            "extern show: Shape -> string = str\n"
            "let b = Box { it = Mk 1, more = [] }\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        references(1, doc, where(text, "Shape")),
        references(2, doc, where(text, "Shape }"), include=False),
        references(3, doc, where(text, "Box {")),
        references(4, doc, where(text, "List")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_type.json")


def test_references_of_a_value_span_the_project(run, workdir):
    """CATCHES: find-references limited to the open file: a top-level value must be found in its
    defining module (declaration + bare uses) and as the member part of every qualified use in other
    project files on disk, whichever file the request comes from; a missing member has none."""
    write_files(workdir, {
        "geometry.pyfun": "let area w h = w * h\nlet square x = area x x\n",
        "main.pyfun": "import Geometry\nlet floor = Geometry.area 4 5\n",
        "other.pyfun": "import Geometry\nlet a = Geometry.area 1 1\nlet b = Geometry.square 2\n",
        "notes.txt": "Geometry.area is mentioned here but this is not a module\n",
        "dir.pyfun/inner.pyfun": "import Geometry\nlet hidden = Geometry.area 0 0\n",
    })
    main = uri(workdir, "main.pyfun")
    geometry = uri(workdir, "geometry.pyfun")
    main_text = "import Geometry\nlet floor = Geometry.area 4 5\nlet z = Geometry.nope\n"
    geometry_text = "let area w h = w * h\nlet square x = area x x\n"
    r = run(["lsp"], input=session(
        did_open(main, main_text),
        references(1, main, where(main_text, "area"), include=True),
        references(2, main, where(main_text, "area"), include=False),
        did_open(geometry, geometry_text),
        references(3, geometry, where(geometry_text, "area", 2)),
        references(4, main, where(main_text, "floor")),
        references(5, main, where(main_text, "nope")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_project_value.json")


SHAPE = "type Shape = Circle float | Rect float float\n"
MAIN_SHAPE = ("import Shape\n"
              "let c = Shape.Circle 2.0\n"
              "let describe x =\n  match x:\n    case Shape.Circle r: r\n    case Shape.Rect w h: w\n")


def test_references_of_a_constructor_include_patterns_across_files(run, workdir):
    """CATCHES: constructor references that only see construction expressions: qualified pattern
    uses (`case Shape.Circle r`) in importers and the declaration in the defining file must be
    listed too."""
    write_files(workdir, {"shape.pyfun": SHAPE, "main.pyfun": MAIN_SHAPE})
    main = uri(workdir, "main.pyfun")
    text = MAIN_SHAPE
    r = run(["lsp"], input=session(
        did_open(main, text),
        references(1, main, where(text, "Circle")),
        references(2, main, where(text, "Rect"), include=False),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_constructor.json")


SHAPES = "type Placed = { row: int, col: int }\nlet origin = Placed { row = 0, col = 0 }\n"
MAIN_SHAPES = ("import Shapes\n"
               "type Holder = { item: Shapes.Placed, spare: Placed }\n"
               "let p = Shapes.Placed { row = 1, col = 2 }\n"
               "let at h =\n  match h:\n    case Shapes.Placed { row = r, col = c }: r + c\n"
               "let o = Shapes.origin\n")


def test_references_of_a_record_type_span_the_project(run, workdir):
    """CATCHES: type references that stay in-file: the declaration, bare record tags in the declaring
    file, and in an importer the qualified annotation (member part only), the bare annotation, and
    qualified record tags in expressions and patterns must all be found."""
    write_files(workdir, {"shapes.pyfun": SHAPES, "main.pyfun": MAIN_SHAPES, "dir.pyfun/x.pyfun": "let x = 1\n"})
    main = uri(workdir, "main.pyfun")
    shapes = uri(workdir, "shapes.pyfun")
    text = MAIN_SHAPES
    r = run(["lsp"], input=session(
        did_open(main, text),
        references(1, main, where(text, "Placed")),
        references(2, main, where(text, "Placed }"), include=False),
        did_open(shapes, SHAPES),
        references(3, shapes, where(SHAPES, "Placed {")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_project_type.json")


def test_references_on_nothing_are_empty(run, workdir):
    """CATCHES: returning spurious locations for whitespace, literals or keywords, or failing to list
    the in-file uses of a built-in function (which has no declaration of its own to include)."""
    doc = uri(workdir, "nodisk/none.pyfun")
    text = "let n = 1\nlet m = print n\n"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        references(1, doc, where(text, " = 1")),
        references(2, doc, where(text, "1")),
        references(3, doc, where(text, "let", 2)),
        references(4, doc, where(text, "print")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("references_nothing.json")


# ------------------------------------------------------------------------------------------ rename

def test_prepare_rename_reports_the_editable_range(run, workdir):
    """CATCHES: prepareRename that accepts everything or nothing: it must return the identifier's
    range for a top-level value, a local and a user type, and null for built-ins (`print`, `List`),
    constructors outside a project, keywords and whitespace."""
    doc = uri(workdir, "nodisk/prep.pyfun")
    text = ("type Color = Red | Green\n"
            "type Box = { items: List Color }\n"
            "let one = 1\n"
            "let pick c = match c:\n  case Red: one\n  case Green: one + 1\n"
            "let shown = print one\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        prepare_rename(1, doc, where(text, "one")),
        prepare_rename(2, doc, where(text, "one", 2, plus=2)),
        prepare_rename(3, doc, where(text, "c =")),
        prepare_rename(4, doc, where(text, "Color }")),
        prepare_rename(5, doc, where(text, "Color =")),
        prepare_rename(6, doc, where(text, "List")),
        prepare_rename(7, doc, where(text, "print")),
        prepare_rename(8, doc, where(text, "Red:")),
        prepare_rename(9, doc, where(text, "match")),
        prepare_rename(10, doc, where(text, " = 1")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("prepare_rename.json")


def test_rename_values_and_locals_in_one_file(run, workdir):
    """CATCHES: a rename that misses occurrences (declaration, every use, interpolation holes), edits
    a shadowing binder of the same name, or emits edits for the wrong document URI."""
    doc = uri(workdir, "nodisk/rn.pyfun")
    text = ("let one = 1\nlet two = one + one\nlet s = f\"{one}\"\n"
            "let f one = one * 2\n"
            "let g x =\n  let y = x + 1\n  y * y\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        rename(1, doc, where(text, "one"), "uno"),
        rename(2, doc, where(text, "one * 2"), "n"),
        rename(3, doc, where(text, "y * y"), "z_1"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_in_file.json")


def test_rename_rejects_invalid_new_names_and_non_renameable_symbols(run, workdir):
    """CATCHES: renames that could break the program: a value renamed to a keyword, an uppercase or
    malformed identifier, a constructor or built-in renamed outside a project, or a type renamed to
    a lowercase name must all be refused with a null result."""
    doc = uri(workdir, "nodisk/bad.pyfun")
    text = "type Color = Red | Green\nlet one = 1\nlet c = Red\nlet two = one + 1\nlet p = print two\n"
    target = where(text, "one")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        rename(1, doc, target, "match"),
        rename(2, doc, target, "Uno"),
        rename(3, doc, target, ""),
        rename(4, doc, target, "1x"),
        rename(5, doc, target, "o-ne"),
        rename(6, doc, target, "\u00fcno"),
        rename(7, doc, where(text, "Red", 2), "Crimson"),
        rename(8, doc, where(text, "print"), "say"),
        rename(9, doc, where(text, "Color"), "colour"),
        rename(10, doc, where(text, "Color"), "Hue"),
        rename(11, doc, where(text, " = 1"), "fine"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_invalid.json")


def test_rename_a_type_in_one_file(run, workdir):
    """CATCHES: a type rename that only rewrites the declaration, misses annotation uses in record
    fields / variant payloads / bare record tags, or rewrites a same-named constructor."""
    doc = uri(workdir, "nodisk/ty.pyfun")
    text = ("type Shape = Mk int\n"
            "type Box = { it: Shape }\n"
            "type Tag = Shape Shape\n"
            "let b = Box { it = Mk 1 }\n")
    r = run(["lsp"], input=session(
        did_open(doc, text),
        rename(1, doc, where(text, "Shape }"), "Figure"),
        rename(2, doc, where(text, "Box {"), "Crate"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_type_in_file.json")


def test_rename_a_value_across_project_files(run, workdir):
    """CATCHES: rename limited to the open file: renaming `Geometry.area` must edit its definition
    and bare uses in geometry.pyfun and only the member part of each qualified use elsewhere (also
    `Geometry . area` with spaces); prepareRename must return just the member range."""
    write_files(workdir, {
        "geometry.pyfun": GEOMETRY + "let square x = area x x\n",
        "main.pyfun": MAIN_GEOMETRY,
        "geometry.txt": "let area = 1\n",
    })
    main = uri(workdir, "main.pyfun")
    text = MAIN_GEOMETRY
    r = run(["lsp"], input=session(
        did_open(main, text),
        prepare_rename(1, main, where(text, "Geometry.area", plus=3)),
        rename(2, main, where(text, "Geometry.area", plus=3), "surface"),
        rename(3, main, where(text, "area 1"), "Surface"),
        prepare_rename(4, main, where(text, "floor")),
        rename(5, main, where(text, "floor"), "ground"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_project_value.json")


def test_rename_a_constructor_across_project_files(run, workdir):
    """CATCHES: constructor renames that skip pattern uses or the declaration in the defining file,
    or that let a constructor be renamed to a lowercase (value) name."""
    write_files(workdir, {"shape.pyfun": SHAPE, "main.pyfun": MAIN_SHAPE})
    main = uri(workdir, "main.pyfun")
    text = MAIN_SHAPE
    r = run(["lsp"], input=session(
        did_open(main, text),
        prepare_rename(1, main, where(text, "Circle")),
        rename(2, main, where(text, "Circle"), "Disk"),
        rename(3, main, where(text, "Circle"), "disk"),
        rename(4, main, where(text, "Rect"), "Box"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_project_constructor.json")


def test_rename_a_record_type_across_project_files(run, workdir):
    """CATCHES: a cross-file type rename that misses the declaration, bare tags in the declaring
    file, qualified annotations/tags (member part only) or bare uses in importers; after the edit
    go-to-definition from the importer must still land in the declaring file."""
    write_files(workdir, {"shapes.pyfun": SHAPES, "main.pyfun": MAIN_SHAPES})
    main = uri(workdir, "main.pyfun")
    text = MAIN_SHAPES
    r = run(["lsp"], input=session(
        did_open(main, text),
        prepare_rename(1, main, where(text, "Placed", plus=2)),
        rename(2, main, where(text, "Placed", plus=2), "Tile"),
        rename(3, main, where(text, "Placed }"), "tile"),
        prepare_rename(4, main, where(text, "Placed {")),
        definition(5, main, where(text, "Placed }", plus=2)),
        prepare_rename(6, main, where(text, "Placed }")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_project_type.json")


def test_rename_of_an_imported_type_skips_a_local_type_of_the_same_name(run, workdir):
    """CATCHES: a type rename that ignores shadowing: renaming the imported `Shapes.Placed` must not
    touch the importer's own `type Placed` or its bare uses, and renaming the local one must not
    touch shapes.pyfun."""
    write_files(workdir, {
        "shapes.pyfun": "type Placed = { row: int }\n",
        "main.pyfun": "import Shapes\ntype Placed = { col: int }\ntype Holder = { a: Placed, b: Shapes.Placed }\n",
    })
    main = uri(workdir, "main.pyfun")
    text = "import Shapes\ntype Placed = { col: int }\ntype Holder = { a: Placed, b: Shapes.Placed }\n"
    r = run(["lsp"], input=session(
        did_open(main, text),
        rename(1, main, where(text, "Shapes.Placed", plus=9), "Tile"),
        rename(2, main, where(text, "Placed, b"), "Spot"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_shadowed_type.json")


def test_rename_is_refused_when_a_project_file_does_not_parse(run, workdir):
    """CATCHES: a half-done project-wide rename: if any .pyfun file in the directory fails to parse
    (it might hide an occurrence) rename of a value, constructor or type must return null rather
    than rewriting only the files that parsed, while references still list the parsed files."""
    write_files(workdir, {
        "geometry.pyfun": "let area w h = w * h\ntype Kind = Flat | Tall\ntype Spot = { x: int }\n",
        "main.pyfun": "import Geometry\nlet a = Geometry.area 1 2\nlet k = Geometry.Flat\n"
                      "type T = { s: Geometry.Spot }\n",
        "zbroken.pyfun": "let oops =\n",
    })
    main = uri(workdir, "main.pyfun")
    geometry = uri(workdir, "geometry.pyfun")
    text = "import Geometry\nlet a = Geometry.area 1 2\nlet k = Geometry.Flat\ntype T = { s: Geometry.Spot }\n"
    geometry_text = "let area w h = w * h\ntype Kind = Flat | Tall\ntype Spot = { x: int }\n"
    r = run(["lsp"], input=session(
        did_open(main, text),
        rename(1, main, where(text, "area"), "surface"),
        prepare_rename(2, main, where(text, "area")),
        rename(3, main, where(text, "Flat"), "Level"),
        rename(4, main, where(text, "Spot"), "Place"),
        prepare_rename(5, main, where(text, "Spot")),
        references(6, main, where(text, "area")),
        did_open(geometry, geometry_text),
        prepare_rename(7, geometry, where(geometry_text, "area")),
        rename(8, geometry, where(geometry_text, "area"), "surface"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("rename_refused_broken_project.json")


# ------------------------------------------------------------------------- completion and symbols

ALL_KINDS = """import Geometry
extern import math
## Square root.
extern root: float -> float = math.sqrt
extern type Conn
opaque type UserId = string
type Color = Red | Green
type Point = { x: int, y: Conn }
measure m
let (w, h) = (3, 4)
let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
module Geom =
  let square x = x * x
  let (a, b) = (1, 2)
let _ = 1
let print = 5
"""


def test_completion_offers_user_symbols_then_builtins(run, workdir):
    """CATCHES: completion that omits user definitions of any kind (values, destructured names,
    externs, types, records, constructors, measures, active-pattern cases, in-file module members,
    imports), uses wrong CompletionItemKinds, lists a shadowed built-in twice, or drops the
    signatures/docs of prelude functions, qualified module members, constructors and keywords."""
    doc = uri(workdir, "nodisk/kinds.pyfun")
    r = run(["lsp"], input=session(did_open(doc, ALL_KINDS), completion(1, doc, {"line": 15, "character": 0})))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("completion_all_kinds.json")


def test_completion_without_a_document_offers_only_builtins(run, workdir):
    """CATCHES: a completion handler that fails (or returns nothing) when the document is unknown:
    the static prelude/builtin/keyword list (with signatures and docs) must still be offered."""
    r = run(["lsp"], input=session(
        completion(1, "untitled:none", {"line": 0, "character": 0}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("completion_static.json")


def test_document_symbols_outline_every_kind_of_definition(run, workdir):
    """CATCHES: an outline with wrong SymbolKinds (Function 12, Enum 10, EnumMember 22, Struct 23,
    Number 16, Module 2), missing destructured names / module members / active-pattern cases, or
    ranges that cover the whole declaration instead of the name where the name has its own span."""
    doc = uri(workdir, "nodisk/kinds.pyfun")
    r = run(["lsp"], input=session(did_open(doc, ALL_KINDS), document_symbol(1, doc)))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("document_symbols.json")


def test_workspace_symbols_search_the_project_directory(run, workdir):
    """CATCHES: workspace/symbol limited to open files or to an exact-case match: it must scan every
    .pyfun file in the open document's directory (open buffer text over disk), filter by a
    case-insensitive substring, skip unparseable files, non-.pyfun files and unreadable entries."""
    write_files(workdir, {
        "geometry.pyfun": "let area w h = w * h\nlet square x = area x x\n",
        "main.pyfun": "import Geometry\nlet floor = 1\n",
        "broken.pyfun": "let areaBroken =\n",
        "notes.txt": "let areaNotes = 1\n",
        "shapes.pyfun": "type Shape = Circle float | Area float\n",
        "dir.pyfun/inner.pyfun": "let hidden = 1\n",
    })
    main = uri(workdir, "main.pyfun")
    r = run(["lsp"], input=session(
        did_open(main, "import Geometry\nlet floorArea = Geometry.area 2 3\n"),
        did_open(uri(workdir, "geometry.pyfun"), "let area w h = w * h\nlet square x = area x x\n"),
        workspace_symbol(1, "AREA"),
        workspace_symbol(2, ""),
        request(3, "workspace/symbol", {}),
        workspace_symbol(4, "zzz"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("workspace_symbols.json")


def test_workspace_symbols_skip_non_file_and_missing_directories(run, workdir):
    """CATCHES: workspace/symbol crashing or inventing results for open documents that have no
    directory on disk (an `untitled:` URI, a file URI whose directory does not exist) or when no
    document is open at all."""
    r = run(["lsp"], input=session(
        workspace_symbol(1, ""),
        did_open("untitled:Untitled-1", "let alpha = 1\n"),
        did_open(uri(workdir, "missing/dir/x.pyfun"), "let beta = 2\n"),
        workspace_symbol(2, ""),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("workspace_symbols_empty.json")


# ---------------------------------------------------------------------------------------------- URIs

def test_percent_encoded_uris_resolve_siblings_and_keep_the_client_encoding(run, workdir):
    """CATCHES: URI handling that does not percent-decode (`my%20proj` must find the directory
    `my proj`, `%61` decodes to `a`), mangles an invalid escape (`%zz` stays literal), or re-encodes
    the sibling URIs it returns instead of keeping the client's spelling (a buffer opened as
    `C%61ps/m%61in.pyfun` keeps its own type references even though disk `Caps/main.pyfun` differs)."""
    write_files(workdir, {
        "my proj/geometry.pyfun": "let area w h = w * h\n",
        "x%zz/geometry.pyfun": "let volume x = x\n",
        "Caps/geometry.pyfun": "let area w h = w + h\n",
        "Caps/main.pyfun": "let floor = 0\n",
    })
    spaced = uri(workdir, "my%20proj/main.pyfun")
    literal = uri(workdir, "x%zz/main.pyfun")
    escaped = uri(workdir, "C%61ps/m%61in.pyfun")
    r = run(["lsp"], input=session(
        did_open(spaced, "import Geometry\nlet floor = Geometry.area 4 5\n"),
        definition(1, spaced, {"line": 1, "character": 22}),
        did_open(literal, "import Geometry\nlet v = Geometry.volume 2\n"),
        definition(2, literal, {"line": 1, "character": 18}),
        did_open(escaped, "import Geometry\nlet floor = Geometry.area 4 5\ntype Local = { v: int }\ntype Use = { l: Local }\n"),
        hover(3, escaped, {"line": 1, "character": 22}),
        references(4, escaped, {"line": 3, "character": 17}),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("uri_percent_encoding.json")


def test_localhost_authority_file_uris_are_resolved(run, workdir):
    """CATCHES: a URI-to-path conversion that only accepts `file:///`: `file://localhost/...` must
    read sibling modules from disk (clean import-aware diagnostics, cross-file definition) and the
    returned locations must keep the `localhost` spelling."""
    write_files(workdir, {"geometry.pyfun": "let area w h = w * h\n"})
    doc = "file://localhost" + workdir.as_uri()[len("file://"):] + "/main.pyfun"
    text = "import Geometry\nlet floor = Geometry.area 4 5\n"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        definition(1, doc, where(text, "area")),
        references(2, doc, where(text, "area")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("uri_localhost.json")


def test_non_file_uris_get_in_file_features_only(run, workdir):
    """CATCHES: features that require a file path: an `untitled:` document must still get
    diagnostics, hover, in-file references/rename and an outline, while its imports simply do not
    resolve (no crash, a `not a member` diagnostic)."""
    doc = "untitled:Untitled-1"
    text = "import Geometry\nlet one = 1\nlet two = one + one\nlet g = Geometry.area 1 2\n"
    r = run(["lsp"], input=session(
        did_open(doc, text),
        hover(1, doc, where(text, "two")),
        references(2, doc, where(text, "one")),
        prepare_rename(3, doc, where(text, "one")),
        rename(4, doc, where(text, "one"), "uno"),
        definition(5, doc, where(text, "area")),
        document_symbol(6, doc),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("uri_untitled.json")


# ------------------------------------------------------------------------ imports and the cache

def test_editing_an_imported_buffer_reanalyzes_its_dependent(run, workdir):
    """CATCHES: a stale analysis cache: after an edit to the open imported buffer geometry.pyfun the
    dependent main.pyfun (itself unchanged) must be re-checked, so hover shows the new imported type
    and diagnostics follow the import; a content-identical edit changes nothing."""
    geometry = uri(workdir, "proj/geometry.pyfun")
    main = uri(workdir, "proj/main.pyfun")
    text = "import Geometry\nlet r = Geometry.area\n"
    at_area = where(text, "area")
    r = run(["lsp"], input=session(
        did_open(geometry, "let area w h = w * h"),
        did_open(main, text),
        hover(1, main, at_area),
        did_change(geometry, "let area s = String.upper s"),
        hover(2, main, at_area),
        did_change(geometry, "let area s = String.upper s"),
        hover(3, main, at_area),
        did_change(geometry, "let volume x = x"),
        hover(4, main, at_area),
        did_change(main, text),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("import_buffer_edit.json")


def test_closing_an_imported_buffer_falls_back_to_the_disk_file(run, workdir):
    """CATCHES: a cache keyed only on the dependent's version, or one that keeps reading a closed
    buffer: once geometry.pyfun's open buffer is closed the dependent must be re-checked against the
    (different) file on disk."""
    write_files(workdir, {"geometry.pyfun": "let area w h = w * h\n"})
    geometry = uri(workdir, "geometry.pyfun")
    main = uri(workdir, "main.pyfun")
    text = "import Geometry\nlet r = Geometry.area\n"
    r = run(["lsp"], input=session(
        did_open(geometry, "let area s = String.upper s\n"),
        did_open(main, text),
        hover(1, main, where(text, "area")),
        did_close(geometry),
        hover(2, main, where(text, "area")),
        hover(3, main, where(text, "r =")),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("import_buffer_closed.json")


def test_transitive_and_shared_imports_resolve(run, workdir):
    """CATCHES: import resolution that stops at one level or breaks on a diamond: main imports Left
    and Right, both import Base (from disk); every qualified use type-checks and hovers with the
    re-exported types, and a second dependent reuses the same interfaces."""
    write_files(workdir, {
        "base.pyfun": "let unit = 1\nlet scale k = k * 10\n",
        "left.pyfun": "import Base\nlet l = Base.scale Base.unit\n",
        "right.pyfun": "import Base\nlet rr = Base.scale 2\nlet label = \"right\"\n",
    })
    main = uri(workdir, "main.pyfun")
    other = uri(workdir, "other.pyfun")
    text = "import Left\nimport Right\nimport Base\nlet total = Left.l + Right.rr + Base.unit\nlet s = Right.label\n"
    r = run(["lsp"], input=session(
        did_open(main, text),
        hover(1, main, where(text, "total")),
        hover(2, main, where(text, "label")),
        did_open(other, "import Right\nimport Left\nlet x = Right.rr + Left.l\nlet bad = Right.nope\n"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("import_transitive.json")


def test_cyclic_imports_do_not_hang_and_are_checked_per_entry(run, workdir):
    """CATCHES: import resolution that recurses forever (or crashes) on a cycle, or that reuses an
    interface computed from the other side of the cycle: alpha <-> beta must each be checked with
    the cycle broken at their own import, on disk and in open buffers."""
    write_files(workdir, {
        "alpha.pyfun": "import Beta\nlet a = 1\nlet viaBeta = Beta.b\n",
        "beta.pyfun": "import Alpha\nlet b = Alpha.a + 1\n",
        "gamma.pyfun": "import Alpha\nlet g = Alpha.a\n",
    })
    alpha = uri(workdir, "alpha.pyfun")
    beta = uri(workdir, "beta.pyfun")
    main = uri(workdir, "main.pyfun")
    r = run(["lsp"], input=session(
        did_open(main, "import Gamma\nimport Alpha\nlet m = Gamma.g + Alpha.a\n"),
        did_open(alpha, "import Beta\nlet a = 1\nlet viaBeta = Beta.b\n"),
        did_open(beta, "import Alpha\nlet b = Alpha.a + 1\n"),
        hover(1, alpha, {"line": 2, "character": 5}),
        did_change(main, "import Gamma\nimport Alpha\nlet m = Gamma.g + Alpha.a\n"),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("import_cycle.json")


def test_unreadable_or_broken_imports_are_skipped(run, workdir):
    """CATCHES: crashing or resolving garbage when an import names a directory instead of a file, a
    file that does not parse, or a module that is missing; fixing the broken file in an open buffer
    must make the dependent's uses resolve on its next analysis."""
    write_files(workdir, {
        "folder.pyfun/keep.txt": "not a module\n",
        "broken.pyfun": "let x =\n",
    })
    main = uri(workdir, "main.pyfun")
    text = "import Folder\nimport Broken\nimport Absent\nlet a = Broken.x\nlet b = Folder.y\n"
    r = run(["lsp"], input=session(
        did_open(main, text),
        did_open(uri(workdir, "broken.pyfun"), "let x = 41 + 1\n"),
        hover(1, main, where(text, "Broken.x", plus=7)),
        did_change(main, text),
    ))
    assert r.returncode == 0
    assert r.stderr == b""
    assert replies(r, workdir) == expected("import_unreadable.json")
