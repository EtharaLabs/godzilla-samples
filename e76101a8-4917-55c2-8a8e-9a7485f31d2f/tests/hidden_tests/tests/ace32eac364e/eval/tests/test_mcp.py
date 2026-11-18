"""`bimcraft-cli mcp`: the MCP server on stdio (JSON-RPC 2.0, one message a line), its tools, its errors and its options."""

import base64
import json
import re

import pytest
from conftest import make_project, mcp_lines, normalize, png_pixels

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
BOX = {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": True}
IMAGE_RE = re.compile(r'"data":"([A-Za-z0-9+/=]+)"')


def call(n, name, arguments=None):
    msg = {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name}}
    if arguments is not None:
        msg["params"]["arguments"] = arguments
    return msg


def transcript(r) -> str:
    """The server's replies with each PNG it sent described by its pixels, then its exit code and stderr."""
    out = r.stdout.decode()
    out = IMAGE_RE.sub(lambda m: '"data":"' + png_pixels(base64.b64decode(m.group(1))).strip() + '"', out)
    return f"exit: {r.returncode}\n--- stdout\n{normalize(out)}--- stderr\n{normalize(r.stderr.decode())}"


def serve(run, messages, *args, **kw):
    return run(["mcp", *args], input=mcp_lines(messages), **kw)


def test_initialize_and_list_tools(run, golden):
    """CATCHES: a rewrite whose handshake answers a different protocol version, server info or instructions, that
    replies to a notification, or whose tool list (names, descriptions, input schemas) differs."""
    r = serve(run, [INIT, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    golden.check(transcript(r), "initialize_and_list.txt")


@pytest.mark.parametrize("version", ["2025-06-18", "2025-03-26", "2024-11-05", "1999-01-01", None])
def test_protocol_version_negotiation(run, golden, version):
    """CATCHES: a rewrite that echoes an unsupported protocol version back instead of offering its own, or that refuses
    one of the older supported versions."""
    params = {} if version is None else {"protocolVersion": version}
    r = serve(run, [{"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": params}])
    reply = json.loads(r.stdout)
    assert r.returncode == 0
    golden.check(reply["result"]["protocolVersion"] + "\n", f"version_{version}.txt")
    assert reply["result"]["serverInfo"] == {"name": "bimcraft", "title": "BIMCraft", "version": "0.10.0"}


def test_ping_blank_lines_and_notifications(run, golden):
    """CATCHES: a rewrite that answers blank lines or notifications, or loses the request ids, or stops at a blank line."""
    r = serve(run, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, "", "   ", INITIALIZED,
                    {"jsonrpc": "2.0", "id": "two", "method": "ping"}, {"jsonrpc": "2.0", "id": None, "method": "ping"}])
    golden.check(transcript(r), "ping.txt")


PROTOCOL_ERRORS = {
    "parse_error": ["{not json"],
    "empty_batch": ["[]"],
    "not_an_object": ["42"],
    "string_message": ['"hello"'],
    "missing_method": [{"jsonrpc": "2.0", "id": 3}],
    "method_not_a_string": [{"jsonrpc": "2.0", "id": 3, "method": 5}],
    "a_response_gets_no_reply": [{"jsonrpc": "2.0", "id": 3, "result": {}}, {"jsonrpc": "2.0", "id": 4, "error": {}},
                                 {"jsonrpc": "2.0", "id": 5, "method": "ping"}],
    "unknown_method": [{"jsonrpc": "2.0", "id": 3, "method": "resources/list"}],
    "tools_call_without_name": [{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {}}],
    "unknown_tool": [call(3, "teleport", {})],
    "arguments_not_an_object": [call(3, "script", "x")],
    "arguments_a_list": [call(3, "execute", [1])],
    "missing_required_argument": [call(3, "execute", {})],
    "required_argument_null": [call(3, "open", {"path": None})],
    "script_needs_text": [call(3, "script", {"atomic": True})],
    "atomic_not_a_boolean": [call(3, "script", {"text": "inspect", "atomic": "yes"})],
    "batch_of_requests": ['[{"jsonrpc":"2.0","id":1,"method":"ping"},{"jsonrpc":"2.0","method":"x"},5,'
                          '{"jsonrpc":"2.0","id":2,"method":"nope"}]'],
    "batch_of_notifications_only": ['[{"jsonrpc":"2.0","method":"notifications/initialized"}]',
                                    {"jsonrpc": "2.0", "id": 9, "method": "ping"}],
}


@pytest.mark.parametrize("case", sorted(PROTOCOL_ERRORS))
def test_protocol_errors(run, golden, case):
    """CATCHES: a rewrite that uses the wrong JSON-RPC error codes (-32700, -32600, -32601, -32602), words them
    differently, answers responses or notifications, or handles batches differently from the reference."""
    golden.check(transcript(serve(run, PROTOCOL_ERRORS[case])), f"protocol_{case}.txt")


def test_an_agent_models_a_house(run, workdir, golden):
    """CATCHES: a rewrite whose execute, script, inspect_model, query_elements and schedule tools answer with different
    text, or that does not keep the model between calls."""
    script = 'door {"at": [3000, 0]}\nwindow {"at": [6000, 2000]}\nroom {"point": [3000, 2000], "name": "Cabin"}\nfloor {}'
    big = {"name": "Big Rooms", "category": "rooms", "fields": ["Name", {"name": "Cost", "formula": "Area * 100", "total": True}],
           "filters": [{"field": "Area", "op": "greater", "value": 20}]}
    r = serve(run, [INIT, call(2, "new_model", {"name": "Cabin"}), call(3, "execute", {"command": "wall", "params": BOX}),
                    call(4, "script", {"text": script}), call(5, "inspect_model", {}), call(6, "query_elements", {"category": "door"}),
                    call(7, "schedule", {"category": "rooms"}), call(8, "schedule", big),
                    call(9, "save", {"path": "cabin.bimcraft"}), call(10, "query_elements", {"category": "wall", "limit": 1, "offset": 2})])
    golden.check(transcript(r), "model_a_house.txt")
    golden.check(normalize((workdir / "cabin.bimcraft").read_text()), "cabin.bimcraft")


def test_tool_errors_are_results_with_is_error(run, golden):
    """CATCHES: a rewrite that turns a failing command into a protocol error, or changes the model when a command fails."""
    r = serve(run, [call(1, "execute", {"command": "door", "params": {"at": [0, 0]}}),
                    call(2, "execute", {"command": "nonsense"}),
                    call(3, "script", {"text": 'wall {"points": [[0,0],[4000,0]]}\nnope'}),
                    call(4, "inspect_model"),
                    call(5, "open", {"path": "missing.bimcraft"}),
                    call(6, "save", {}),
                    call(7, "execute", {"command": "wall", "params": None})])
    golden.check(transcript(r), "tool_errors.txt")


def test_atomic_script_is_all_or_nothing_and_one_undo_step(run, golden):
    """CATCHES: a rewrite whose atomic script keeps the lines before a failure, or takes more than one undo step back."""
    r = serve(run, [call(1, "script", {"text": 'level {"elevation": 6000}\nnope', "atomic": True}),
                    call(2, "inspect_model"),
                    call(3, "script", {"text": 'level {"elevation": 6000}\nlevel {"elevation": 9000}', "atomic": True}),
                    call(4, "execute", {"command": "undo"}),
                    call(5, "script", {"text": 'level {"elevation": 6000}\nnope', "atomic": False}),
                    call(6, "script", {"text": "inspect", "atomic": None})])
    golden.check(transcript(r), "atomic_script.txt")


@pytest.mark.parametrize("flt", [None, "wall", "WA", "Manage", "zzz-nothing"])
def test_list_commands_filter(run, golden, flt):
    """CATCHES: a rewrite whose list_commands filter does not match ids, labels and shortcuts case-insensitively, or
    returns the catalog in another order or shape."""
    r = serve(run, [call(1, "list_commands", {} if flt is None else {"filter": flt})])
    golden.check(transcript(r), f"list_commands_{flt}.txt")


def test_render_plan_and_3d(run, golden):
    """CATCHES: a rewrite whose render tool sends a different picture, size or caption for a plan, a 3D view or a
    ceiling plan, or fails to report a view that does not exist."""
    r = serve(run, [call(1, "execute", {"command": "wall", "params": BOX}),
                    call(2, "render", {"width": 400, "height": 300}),
                    call(3, "render", {"view": "{3D}", "azimuth": 135, "elevation": 20, "width": 320, "height": 240}),
                    call(4, "render", {"ceiling": True, "width": 200, "height": 150}),
                    call(5, "render", {"view": "Nowhere"}),
                    call(6, "render", {"view": "Level 2", "path": "l2.png", "width": 100, "height": 80})])
    golden.check(transcript(r), "render.txt")


def test_render_a_family_preview(run, workdir, golden):
    """CATCHES: a rewrite whose family preview draws differently in 3d, plan or elevation mode, leaves something in the
    project, or does not name a family that is not there."""
    family = {"name": "Stool", "parameters": [{"name": "Height", "value": 450}], "types": {"A": {}, "B": {"Height": 460}},
              "forms": [{"profile": [[0, 0], [320, 0], [320, 320], [0, 320]], "from": 420, "to": 450, "material": "Timber"},
                        {"profile": [[20, 20], [60, 20], [60, 60], [20, 60]], "to": 420, "material": "Timber"}]}
    msgs = [call(1, "execute", {"command": "family", "params": family})]
    for n, mode in enumerate(["3d", "plan", "elevation"]):
        msgs.append(call(10 + n, "render", {"family": "Stool", "type": "A", "mode": mode, "width": 300, "height": 240}))
    msgs += [call(20, "render", {"family": "Stool", "mode": "plan", "path": "stool.png"}),
             call(21, "render", {"family": "Nowhere"}),
             call(22, "inspect_model")]
    golden.check(transcript(serve(run, msgs)), "render_family.txt")
    golden.check(png_pixels((workdir / "stool.png").read_bytes()), "stool.png.txt")


def test_server_opens_the_file_it_is_given(run, workdir, golden):
    """CATCHES: a rewrite of `mcp FILE` that does not open FILE before answering."""
    make_project(run, workdir, "house.bimcraft", ["--cmd", 'wall {"points": [[0, 0], [4000, 0]]}'])
    r = serve(run, [call(1, "inspect_model")], "house.bimcraft")
    golden.check(transcript(r), "open_file.txt")


def test_read_only_server_reads_and_refuses_changes(run, workdir, golden):
    """CATCHES: a rewrite of `mcp --read-only FILE` that lets an agent change the project, undo, replace it or write over
    its file, words the refusals differently, or does not say it is read-only in its instructions."""
    make_project(run, workdir, "house.bimcraft", ["--cmd", 'wall {"points": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]], "closed": true}',
                                                  "--cmd", 'door {"at": [2000, 0]}'])
    saved = (workdir / "house.bimcraft").read_bytes()
    msgs = [INIT, call(2, "inspect_model"), call(3, "schedule", {"category": "doors"}), call(4, "save", {"path": "copy.ifc"}),
            call(5, "execute", {"command": "wall", "params": {"points": [[0, 9000], [4000, 9000]]}}),
            call(6, "execute", {"command": "undo"}),
            call(7, "script", {"text": 'inspect\ndelete {"ids": [100002]}', "atomic": True}),
            call(8, "save", {}), call(9, "save", {"path": "house.bimcraft"}), call(10, "open", {"path": "house.bimcraft"}),
            call(11, "new_model", {}), call(12, "execute", {"command": "redo"}),
            call(13, "query_elements", {"category": "wall"})]
    r = serve(run, msgs, "--read-only", "house.bimcraft")
    golden.check(transcript(r), "read_only.txt")
    assert (workdir / "house.bimcraft").read_bytes() == saved
    assert (workdir / "copy.ifc").read_text().count("IFCDOOR(") == 1


def test_read_only_without_a_file(run, golden):
    """CATCHES: a rewrite of `mcp --read-only` with no file that lets the agent build on the empty project."""
    r = serve(run, [INIT, call(2, "execute", {"command": "level", "params": {"elevation": 6000}}), call(3, "inspect_model")],
              "--read-only")
    golden.check(transcript(r), "read_only_empty.txt")


def test_read_only_after_the_file(run, workdir, golden):
    """CATCHES: a rewrite that only accepts --read-only before FILE."""
    make_project(run, workdir, "p.bimcraft", ["--cmd", 'wall {"points": [[0, 0], [4000, 0]]}'])
    r = serve(run, [call(2, "execute", {"command": "delete", "params": {"ids": [100002]}})], "p.bimcraft", "--read-only")
    golden.check(transcript(r), "read_only_after_file.txt")


MCP_ARG_ERRORS = {
    "port_not_a_number": ["--connect", "x"],
    "port_too_large": ["--connect", "70000"],
    "connect_and_a_file": ["--connect", "1", "2"],
    "file_then_connect": ["a.bimcraft", "--connect"],
    "unknown_flag": ["--attach"],
    "short_unknown_flag": ["-r"],
    "two_files": ["a.bimcraft", "b.bimcraft"],
    "connect_twice": ["--connect", "7000", "--connect"],
    "missing_file": ["missing.bimcraft"],
    "missing_file_read_only": ["--read-only", "missing.bimcraft"],
    "missing_revit_file": ["missing.rvt"],
    "bad_project_file": ["bad.bimcraft"],
}


@pytest.mark.parametrize("case", sorted(MCP_ARG_ERRORS))
def test_mcp_argument_errors(run, workdir, golden, case):
    """CATCHES: a rewrite of `mcp` that accepts malformed arguments, a port out of range or a file it cannot open, or
    reports them without the `bimcraft-cli mcp:` prefix, on stdout, or with a zero exit code."""
    (workdir / "bad.bimcraft").write_text("{oops")
    r = run(["mcp", *MCP_ARG_ERRORS[case]], input="")
    golden.check(transcript(r), f"args_{case}.txt")


def test_mcp_open_and_new_model(run, workdir, golden):
    """CATCHES: a rewrite whose open and new_model tools do not replace the server's project, or reply differently."""
    make_project(run, workdir, "p.bimcraft", ["--cmd", 'wall {"points": [[0, 0], [4000, 0]]}'])
    r = serve(run, [call(1, "open", {"path": "p.bimcraft"}), call(2, "inspect_model"), call(3, "new_model", {"name": "Fresh"}),
                    call(4, "inspect_model"), call(5, "open", {"path": "missing.rvt"}), call(6, "new_model")])
    golden.check(transcript(r), "open_and_new.txt")


def test_mcp_open_a_fake_revit_file(run, workdir, golden):
    """CATCHES: a rewrite whose open tool imports a file named .rvt that is no Revit file, or changes the model when it fails."""
    (workdir / "fake.rvt").write_bytes(b"not a Revit file")
    r = serve(run, [call(1, "execute", {"command": "level", "params": {"elevation": 4000}}),
                    call(2, "open", {"path": "fake.rvt"}), call(3, "inspect_model")])
    golden.check(transcript(r), "open_fake_revit.txt")
