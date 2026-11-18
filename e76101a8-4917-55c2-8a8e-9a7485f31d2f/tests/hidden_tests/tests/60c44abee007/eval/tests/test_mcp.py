"""The MCP server: JSON-RPC 2.0 over stdio, one message a line, its tools on a project of its own, read-only or not."""

import json
import re

import pytest

from conftest import png_pixels

PNG_DATA_RE = re.compile(r'"data":"([A-Za-z0-9+/=]+)"')


def png_text(b64: str) -> str:
    import base64

    w, h, kind, sha = png_pixels(base64.b64decode(b64))
    return f"<png {w}x{h} {kind} pixels-sha256={sha}>"


def request(id_, method, params=None) -> str:
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


def call(id_, tool, arguments=None) -> str:
    params = {"name": tool}
    if arguments is not None:
        params["arguments"] = arguments
    return request(id_, "tools/call", params)


def serve(sc, lines, args=("mcp",)):
    """Feed `lines` to the server on its stdin and record each reply line (a picture sent back as its size and pixels)."""
    text = "\n".join(lines) + "\n"
    p = sc.run(list(args), input=text.encode(), show=False)
    sc.note(f"$ bimcraft-cli {' '.join(args)}  <<< {len(lines)} lines")
    sc.note(f"[exit {p.returncode}]")
    for line in p.stdout.decode().splitlines():
        sc.note(PNG_DATA_RE.sub(lambda m: f'"data":"{png_text(m.group(1))}"', line))
    sc.note("--- stderr")
    sc.note(p.stderr.decode())
    return p


def test_initialize_negotiates_the_protocol_version(sc):
    """CATCHES: a server that answers initialize with another protocol version than the supported one asked for (or its
    newest for one it doesn't know), other capabilities, server info or instructions, or replies to notifications."""
    serve(sc, [
        request(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}),
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        request(2, "initialize", {"protocolVersion": "2025-03-26"}),
        request(3, "initialize", {"protocolVersion": "2024-11-05"}),
        request(4, "initialize", {"protocolVersion": "1999-01-01"}),
        request("five", "initialize"),
        request(6, "ping"),
        request(None, "ping"),
    ])
    assert sc.transcript() == sc.golden()


def test_tools_list(sc):
    """CATCHES: a tool missing from tools/list, renamed, or with another description or input schema."""
    serve(sc, [request(1, "tools/list"), request(2, "tools/list", {})])
    assert sc.transcript() == sc.golden()


def test_protocol_errors(sc):
    """CATCHES: wrong JSON-RPC error codes or messages for malformed lines, empty batches, non-objects, missing methods,
    unknown methods and tools, bad arguments; a reply to a response or a notification; batches not answered as arrays."""
    serve(sc, [
        "{bad",
        "",
        "   ",
        "[]",
        "5",
        '"text"',
        '{"jsonrpc":"2.0","id":4}',
        '{"jsonrpc":"2.0","id":5,"result":{}}',
        '{"jsonrpc":"2.0","id":5,"error":{"code":1,"message":"x"}}',
        request(6, "nope"),
        request(7, "tools/call", {}),
        call(8, "teleport"),
        call(9, "execute", []),
        call(10, "execute", {}),
        call(11, "execute", {"command": None}),
        call(12, "script", {"text": "x", "atomic": "yes"}),
        call(13, "open", {}),
        call(14, "script", "text"),
        '[' + request(15, "ping") + ',{"jsonrpc":"2.0","method":"notifications/x"},5]',
        '[{"jsonrpc":"2.0","method":"notifications/x"}]',
        request(16, "tools/call", {"name": "inspect_model", "arguments": None}),
    ])
    assert sc.transcript() == sc.golden()


def test_an_agent_builds_and_checks_a_house(sc):
    """CATCHES: tools that don't reach the same commands as the CLI: wrong replies of new_model, execute, script,
    inspect_model, query_elements and schedule (with a calculated, filtered one), or save not writing the project."""
    script = "door {\"at\": [3000, 0]}\nwindow {\"at\": [6000, 2000]}\n# a comment\nroom {\"point\": [3000, 2000], \"name\": \"Cabin\"}\nfloor {}"
    serve(sc, [
        request(1, "initialize", {"protocolVersion": "2025-06-18"}),
        call(2, "new_model", {"name": "Cabin"}),
        call(3, "execute", {"command": "wall", "params": {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": True}}),
        call(4, "script", {"text": script}),
        call(5, "inspect_model", {}),
        call(6, "query_elements", {"category": "door"}),
        call(7, "query_elements", {"category": "wall", "limit": 1, "offset": 2}),
        call(8, "schedule", {"category": "rooms"}),
        call(9, "schedule", {"name": "Big Rooms", "category": "rooms",
                             "fields": ["Name", {"name": "Cost", "formula": "Area * 100", "total": True}],
                             "filters": [{"field": "Area", "op": "greater", "value": 20}]}),
        call(10, "execute", {"command": "undo"}),
        call(11, "save", {"path": "cabin.bimcraft"}),
    ])
    info = json.loads(sc.run(["info", "cabin.bimcraft"], show=False).stdout)
    sc.note("saved: " + json.dumps({k: info[k] for k in ("counts", "name")}))
    assert sc.transcript() == sc.golden()


def test_render_tool_replies(sc):
    """CATCHES: render that doesn't send the picture back inline without a path, writes none with one, describes the
    view, its size or the 3D view's angles differently, or doesn't answer a family preview or a bad view as it should."""
    serve(sc, [
        call(1, "execute", {"command": "wall", "params": {"points": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], "closed": True}}),
        call(2, "render", {"width": 160, "height": 120}),
        call(3, "render", {"view": "{3D}", "azimuth": 135, "elevation": 20, "width": 100, "height": 80, "path": "v.png"}),
        call(4, "render", {"family": "Chair", "mode": "plan", "width": 200, "height": 150, "path": "chair.png"}),
        call(5, "render", {"family": "Single Door", "mode": "elevation", "width": 120, "height": 160, "path": "door.png"}),
        call(6, "render", {"view": "Nope"}),
        call(7, "render", {"family": "Nope"}),
        call(8, "inspect_model"),
    ])
    sc.file("v.png")
    sc.file("chair.png")
    assert sc.transcript() == sc.golden()


def test_atomic_script_is_all_or_nothing_and_one_undo_step(sc):
    """CATCHES: an atomic script that keeps the lines before a failing one, or that is more than one undo step; and a
    plain script that takes back what went before its failing line."""
    count = call(0, "query_elements", {"category": "level"})
    serve(sc, [
        call(1, "script", {"text": 'level {"elevation": 6000}\ndoor {"at": [1, 1]}', "atomic": True}),
        count,
        call(2, "script", {"text": 'level {"elevation": 6000}\nlevel {"elevation": 9000}', "atomic": True}),
        call(3, "inspect_model"),
        call(4, "execute", {"command": "undo"}),
        count,
        call(5, "script", {"text": 'level {"elevation": 6000}\nnope {}', "atomic": False}),
        call(6, "script", {"text": 'level {"elevation": 12000}\nlevel {"elevation": "high"}'}),
        count,
    ])
    assert sc.transcript() == sc.golden()


def test_list_commands_filter(sc):
    """CATCHES: list_commands whose filter doesn't match part of an id, a label or a shortcut in any case, or matches
    what it shouldn't."""
    serve(sc, [
        call(1, "list_commands", {"filter": "WA"}),
        call(2, "list_commands", {"filter": "phase"}),
        call(3, "list_commands", {"filter": "Insert from"}),
        call(4, "list_commands", {"filter": "zzz"}),
    ])
    assert sc.transcript() == sc.golden()


def test_list_commands_without_filter_is_the_catalog(run):
    """CATCHES: list_commands without a filter listing other commands than `bimcraft-cli commands`."""
    p = run(["mcp"], input=call(1, "list_commands") + "\n")
    reply = json.loads(p.stdout)
    listed = json.loads(reply["result"]["content"][0]["text"])
    catalog = json.loads(run(["commands"]).stdout)
    assert (p.returncode, listed) == (0, catalog)


def test_tool_failures_are_tool_errors_that_change_nothing(sc):
    """CATCHES: a failing command answered as a protocol error instead of a tool result with isError, or one that
    changes the model; a file that isn't a Revit project opened as one."""
    sc.write("fake.rvt", "this is not a Revit file at all")
    serve(sc, [
        call(0, "open", {"path": "fake.rvt"}),
        call(1, "execute", {"command": "door", "params": {"at": [4000, 3000]}}),
        call(2, "execute", {"command": "teleport"}),
        call(3, "execute", {"command": "wall", "params": {"points": [[0, 0]]}}),
        call(4, "open", {"path": "missing.bimcraft"}),
        call(5, "save", {}),
        call(6, "schedule", {"name": "Nope"}),
        call(7, "query_elements", {"level": "Level 9"}),
        call(8, "new_model", {"language": "xx"}),
        call(9, "inspect_model"),
    ])
    assert sc.transcript() == sc.golden()


def test_server_on_a_file_opens_it_first_and_open_tool_imports_ifc(sc):
    """CATCHES: `mcp FILE` not opening the file before it answers, or the open tool not opening a project or importing
    an IFC file with the counts of what came in."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[5000,0],[5000,4000],[0,4000]], "closed": true}',
            "--cmd", 'door {"at": [2500, 0]}', "--cmd", 'room {"point": [2500, 2000], "name": "Shed"}',
            "--save", "shed.bimcraft", "--save", "shed.ifc"], show=False)
    serve(sc, [call(1, "inspect_model"), call(2, "query_elements", {"category": "room"})], args=("mcp", "shed.bimcraft"))
    serve(sc, [call(1, "open", {"path": "shed.ifc"}), call(2, "query_elements", {"category": "wall", "limit": 1}),
               call(3, "open", {"path": "shed.bimcraft"}), call(4, "save", {})])
    assert sc.transcript() == sc.golden()


def test_read_only_server_reads_and_exports_but_changes_nothing(sc):
    """CATCHES: a --read-only server that lets an agent change the project, step its history, replace it, or write over
    its file; or that refuses reading, schedules and exports to new files, or doesn't say so in its instructions."""
    sc.run(["run", "--cmd", 'wall {"points": [[0,0],[5000,0],[5000,4000],[0,4000]], "closed": true}',
            "--cmd", 'door {"at": [2500, 0]}', "--save", "shed.bimcraft"], show=False)
    before = (sc.workdir / "shed.bimcraft").read_bytes()
    serve(sc, [
        request(1, "initialize", {"protocolVersion": "2025-06-18"}),
        call(2, "inspect_model"),
        call(3, "execute", {"command": "wall", "params": {"points": [[0, 0], [0, 9000]]}}),
        call(4, "execute", {"command": "undo"}),
        call(5, "new_model"),
        call(6, "open", {"path": "shed.bimcraft"}),
        call(7, "save", {}),
        call(8, "save", {"path": "shed.bimcraft"}),
        call(9, "save", {"path": "./shed.bimcraft"}),
        call(10, "script", {"text": 'level {"elevation": 6000}'}),
        call(11, "schedule", {"category": "doors"}),
        call(12, "schedule", {"name": "Mine", "category": "walls"}),
        call(13, "save", {"path": "copy.ifc"}),
        call(14, "save", {"path": "copy.bimcraft"}),
        call(15, "execute", {"command": "autosave", "params": {"path": "shed.bimcraft"}}),
        call(16, "query_elements", {"category": "wall"}),
    ], args=("mcp", "--read-only", "shed.bimcraft"))
    sc.note(f"project file unchanged: {(sc.workdir / 'shed.bimcraft').read_bytes() == before}")
    sc.note("copy: " + json.dumps(json.loads(sc.run(["info", "copy.bimcraft"], show=False).stdout)["counts"]))
    sc.note(f"copy.ifc written: {(sc.workdir / 'copy.ifc').read_text().startswith('ISO-10303-21;')}")
    assert sc.transcript() == sc.golden()


def test_read_only_server_without_a_file(sc):
    """CATCHES: `mcp --read-only` with no file refusing to read its empty project, or letting a command change it."""
    serve(sc, [request(1, "initialize"), call(2, "execute", {"command": "level", "params": {"elevation": 4000}}),
               call(3, "query_elements", {"category": "level"}), call(4, "save", {"path": "empty.bimcraft"})],
          args=("mcp", "--read-only"))
    assert sc.transcript() == sc.golden()


@pytest.mark.parametrize(
    "args",
    [
        ["mcp", "--attach"],
        ["mcp", "-x"],
        ["mcp", "--connect", "x"],
        ["mcp", "--connect", "70000"],
        ["mcp", "--connect", "-1"],
        ["mcp", "a.bimcraft", "b.bimcraft"],
        ["mcp", "--connect", "7000", "x.bimcraft"],
        ["mcp", "x.bimcraft", "--connect"],
        ["mcp", "--connect", "7000", "--connect"],
        ["mcp", "missing.bimcraft"],
        ["mcp", "--read-only", "missing.bimcraft"],
        ["mcp", "missing.rvt"],
    ],
    ids=lambda a: "_".join(a[1:]) or "none",
)
def test_mcp_argument_errors(sc, args):
    """CATCHES: mcp accepting unknown flags, a port that isn't a number up to 65535, two files, a file with --connect,
    or a file that isn't there, instead of failing with exit status 1 and the message on stderr."""
    sc.run(args, input=b"")
    assert sc.transcript() == sc.golden()


def test_connect_without_a_window_or_to_another_port(sc):
    """CATCHES: `mcp --connect` that doesn't say no window has opened a control port when there is no bridge file, or
    connects to a port other than the one the bridge file's window listens on."""
    sc.run(["mcp", "--connect"], input=b"")
    bridge = sc.workdir.parent / "home" / ".config" / "bimcraft" / "bridge.json"
    bridge.parent.mkdir(parents=True)
    bridge.write_text('{"port": 1, "token": "secret"}')
    sc.run(["mcp", "--connect", "2"], input=b"")
    bridge.write_text('{"port": 1, "token": ""}')
    sc.run(["mcp", "--connect", "--read-only"], input=b"")
    assert sc.transcript() == sc.golden()


def test_messages_on_crlf_lines_and_many_in_a_row(sc):
    """CATCHES: a server that chokes on Windows line endings or on whitespace around a message, or stops answering after
    the first."""
    lines = [request(i, "ping") for i in range(1, 6)]
    p = sc.run(["mcp"], input=("\r\n".join(f"  {line}  " for line in lines) + "\r\n").encode(), show=False)
    sc.note(f"[exit {p.returncode}]")
    sc.note(p.stdout.decode())
    assert sc.transcript() == sc.golden()
