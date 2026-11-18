"""`bimcraft-cli mcp --connect [PORT]`: the MCP server working on a window's project through its control port.

A window is played here by a small server on 127.0.0.1 that answers the bridge protocol (one JSON request a line, each with
the token from bridge.json beside the favorites; one `{"ok": ...}` or `{"error": ...}` reply a line), so what the CLI sends
and how it reports what the window says can be checked exactly."""

import json
import socket
import threading

import pytest
from conftest import mcp_lines, normalize

TOKEN = "f00dfeedcafe0123456789abcdef0001"
HELLO = {"app": "bimcraft", "version": "0.10.0", "project": "Window Project", "read_only": False}


class FakeWindow:
    """A control port that answers each request line with what `answer(request)` gives, a dict or a raw line (None hangs up)."""

    def __init__(self, answer):
        self.answer = answer
        self.requests = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        self.listener.settimeout(150)
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        with conn, conn.makefile("rwb") as f:
            for line in f:
                request = json.loads(line)
                self.requests.append(request)
                reply = self.answer(request)
                if reply is None:
                    break
                f.write((reply if isinstance(reply, str) else json.dumps(reply)).encode() + b"\n")
                f.flush()
        self.listener.close()

    def recorded(self) -> str:
        self.thread.join(10)
        return "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.requests)


def window(hello=HELLO, results=None):
    """A window that says `hello`, then answers each execute or script with the next of `results` (as `ok`)."""
    queue = list(results or [])

    def answer(req):
        if req.get("token") != TOKEN:
            return {"error": "the token is missing or wrong: the window's bridge file has it"}
        if req.get("op") == "hello":
            return {"ok": hello}
        return queue.pop(0) if queue else None

    return FakeWindow(answer)


def bridge(workdir, port, token=TOKEN, folder="cfg"):
    d = workdir / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "bridge.json").write_text(json.dumps({"port": port, "token": token}))
    return {"BIMCRAFT_FAVORITES": f"{folder}/favorites.json"}


def call(n, name, arguments=None):
    return {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}


def transcript(r, port=None, home=None) -> str:
    text = f"exit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}"
    if port is not None:
        text = text.replace(f"port {port}", "port <PORT>").replace(f"--control {port}", "--control <PORT>")
    if home is not None:
        text = text.replace(home, "<HOME>")
    return normalize(text)


def test_tools_run_on_the_window(run, workdir, golden):
    """CATCHES: a rewrite of --connect that does not say hello first, leaves the token out of a request, sends execute,
    script or a tool's command in another shape, or reports the window's answers differently."""
    w = window(results=[{"ok": {"ids": [100002]}}, {"ok": [{"host": 100002, "id": 100003}]}, {"ok": {"counts": {"wall": 1}}},
                        {"ok": {"count": 0, "elements": []}}, {"ok": {"rows": []}}, {"ok": {"format": "IFC4", "path": "x.ifc"}},
                        {"error": "door: no wall at [0, 0] on Level 1"}])
    env = bridge(workdir, w.port)
    msgs = [INIT, call(2, "execute", {"command": "wall", "params": {"points": [[0, 0], [4000, 0]]}}),
            call(3, "script", {"text": 'door {"at": [2000, 0]}', "atomic": True}), call(4, "inspect_model"),
            call(5, "query_elements", {"category": "door"}), call(6, "schedule", {"category": "doors"}),
            call(7, "save", {"path": "x.ifc"}), call(8, "execute", {"command": "door", "params": {"at": [0, 0]}})]
    r = run(["mcp", "--connect"], input=mcp_lines(msgs), env_overrides=env)
    golden.check(transcript(r, w.port), "tools_on_window.txt")
    golden.check(w.recorded(), "tools_on_window.requests")


def test_the_port_given_must_be_the_windows(run, workdir, golden):
    """CATCHES: a rewrite that connects to a port given on the command line although bridge.json holds another
    window's port and token."""
    w = window(results=[{"ok": {"counts": {}}}])
    env = bridge(workdir, w.port)
    r = run(["mcp", "--connect", str(w.port)], input=mcp_lines([call(2, "inspect_model")]), env_overrides=env)
    golden.check(transcript(r, w.port), "port_matches.txt")
    other = 1 if w.port != 1 else 2
    r = run(["mcp", "--connect", str(other)], input="", env_overrides=env)
    golden.check(transcript(r, w.port).replace(f"not {other}", "not <OTHER>").replace(f"--control {other}", "--control <OTHER>"),
                 "port_mismatch.txt")


def test_starting_and_opening_projects_is_left_to_the_window(run, workdir, golden):
    """CATCHES: a rewrite whose new_model or open tools replace the window's project (or ask the window to) instead of
    refusing with the reference's words."""
    w = window(results=[{"ok": {"counts": {"wall": 4}}}])
    env = bridge(workdir, w.port)
    msgs = [call(2, "new_model"), call(3, "open", {"path": "house.bimcraft"}), call(4, "open", {"path": "house.rvt"}),
            call(5, "inspect_model"), call(6, "list_commands", {"filter": "undo"})]
    r = run(["mcp", "--connect"], input=mcp_lines(msgs), env_overrides=env)
    golden.check(transcript(r, w.port), "no_new_or_open.txt")
    golden.check(w.recorded(), "no_new_or_open.requests")


def test_read_only_connection_asks_the_window_to_only_read(run, workdir, golden):
    """CATCHES: a rewrite of `--connect --read-only` that does not add `"read_only": true` to each request, or does not
    say in its instructions that the project is read-only."""
    w = window(results=[{"error": "`wall` would change the project"}, {"ok": [{"counts": {}}]}])
    env = bridge(workdir, w.port)
    msgs = [INIT, call(2, "execute", {"command": "wall", "params": {"points": [[0, 0], [4000, 0]]}}), call(3, "script", {"text": "inspect"})]
    r = run(["mcp", "--read-only", "--connect"], input=mcp_lines(msgs), env_overrides=env)
    golden.check(transcript(r, w.port), "read_only_connect.txt")
    golden.check(w.recorded(), "read_only_connect.requests")


def test_a_window_that_lets_agents_only_read(run, workdir, golden):
    """CATCHES: a rewrite that ignores a window's hello saying it lets agents only read, and so leaves the read-only note
    out of its instructions."""
    w = window(hello={**HELLO, "read_only": True}, results=[])
    env = bridge(workdir, w.port)
    r = run(["mcp", "--connect"], input=mcp_lines([INIT]), env_overrides=env)
    golden.check(transcript(r, w.port), "window_read_only.txt")


def test_a_window_that_closes_is_a_tool_error_and_the_server_goes_on(run, workdir, golden):
    """CATCHES: a rewrite whose server exits or hangs when the window goes away, instead of answering the tool call with
    an error and going on to answer ping."""
    w = window(results=[])  # hangs up at the first request after hello
    env = bridge(workdir, w.port)
    msgs = [call(2, "inspect_model"), call(3, "inspect_model"), {"jsonrpc": "2.0", "id": 4, "method": "ping"}]
    r = run(["mcp", "--connect"], input=mcp_lines(msgs), env_overrides=env)
    text = transcript(r, w.port)
    # Whether the second request finds the connection reset or merely closed depends on timing; the start is fixed.
    lines = text.splitlines()
    i = next(i for i, line in enumerate(lines) if line.startswith('{"id":3,'))
    said = json.loads(lines[i])["result"]["content"][0]["text"]
    assert said.startswith("the window closed the connection"), said
    lines[i] = "<CLOSED>"
    golden.check("\n".join(lines) + "\n", "window_closed.txt")


STARTUP_FAILURES = {
    "reply_not_json": "HTTP/1.1 400 Bad Request",
    "reply_neither_ok_nor_error": {"something": 1},
    "not_a_bimcraft_window": {"ok": {"app": "other"}},
    "error_on_hello": {"error": "the token is missing or wrong: the window's bridge file has it"},
    "hangs_up_on_hello": None,
}


@pytest.mark.parametrize("case", sorted(STARTUP_FAILURES))
def test_a_port_that_is_no_window(run, workdir, golden, case):
    """CATCHES: a rewrite that starts serving although what answers the port is no BIMCraft window, or reports why in other
    words, on stdout, or with a zero exit code."""
    w = FakeWindow(lambda req: STARTUP_FAILURES[case])
    env = bridge(workdir, w.port)
    r = run(["mcp", "--connect"], input=mcp_lines([INIT]), env_overrides=env)
    golden.check(transcript(r, w.port), f"startup_{case}.txt")


def test_no_window_answers_the_port(run, workdir, golden):
    """CATCHES: a rewrite that does not explain that nothing listens on the bridge file's port (a window that closed)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = bridge(workdir, port)
    r = run(["mcp", "--connect"], input="", env_overrides=env)
    golden.check(transcript(r, port), "nobody_listens.txt")


BAD_BRIDGE_FILES = {
    "not_json": "port 7000",
    "no_token": '{"port": 7000}',
    "empty_token": '{"port": 7000, "token": ""}',
    "port_too_large": '{"port": 70000, "token": "x"}',
    "port_a_string": '{"port": "7000", "token": "x"}',
    "empty_file": "",
}


@pytest.mark.parametrize("case", sorted(BAD_BRIDGE_FILES))
def test_a_bridge_file_that_names_no_window(run, workdir, golden, case):
    """CATCHES: a rewrite that tries to connect with a damaged bridge.json instead of saying no window has opened a port."""
    (workdir / "cfg").mkdir()
    (workdir / "cfg" / "bridge.json").write_text(BAD_BRIDGE_FILES[case])
    r = run(["mcp", "--connect"], input="", env_overrides={"BIMCRAFT_FAVORITES": "cfg/favorites.json"})
    golden.check(transcript(r), f"bad_bridge_{case}.txt")


def test_where_the_bridge_file_is_looked_for(run, workdir, env, golden):
    """CATCHES: a rewrite that looks for bridge.json somewhere other than beside the favorites: BIMCRAFT_FAVORITES's folder,
    else $XDG_CONFIG_HOME/bimcraft, else ~/.config/bimcraft, with an empty variable counting as unset."""
    home = env["HOME"]
    out = []
    for name, overrides in [
        ("favorites variable", {"BIMCRAFT_FAVORITES": "mine/fav.json", "XDG_CONFIG_HOME": "xdg"}),
        ("favorites variable empty", {"BIMCRAFT_FAVORITES": "", "XDG_CONFIG_HOME": "xdg"}),
        ("xdg", {"XDG_CONFIG_HOME": "xdg"}),
        ("xdg empty", {"XDG_CONFIG_HOME": ""}),
        ("home only", {}),
        ("nothing", {"HOME": ""}),
    ]:
        r = run(["mcp", "--connect"], input="", env_overrides=overrides)
        out.append(f"## {name}\n" + transcript(r, home=home))
    golden.check("".join(out), "bridge_search.txt")


def test_the_bridge_file_in_xdg_config_home_is_used(run, workdir, golden):
    """CATCHES: a rewrite that does not read bridge.json from $XDG_CONFIG_HOME/bimcraft when BIMCRAFT_FAVORITES is unset."""
    w = window(results=[{"ok": {"counts": {"level": 2}}}])
    bridge(workdir, w.port, folder="xdg/bimcraft")
    r = run(["mcp", "--connect"], input=mcp_lines([call(2, "inspect_model")]), env_overrides={"XDG_CONFIG_HOME": "xdg"})
    golden.check(transcript(r, w.port), "xdg_bridge.txt")
    golden.check(w.recorded(), "xdg_bridge.requests")


def test_the_bridge_file_in_home_config_is_used(run, workdir, env, golden):
    """CATCHES: a rewrite that does not fall back to ~/.config/bimcraft/bridge.json."""
    from pathlib import Path
    w = window(results=[{"ok": {"counts": {"level": 2}}}])
    d = Path(env["HOME"]) / ".config" / "bimcraft"
    d.mkdir(parents=True)
    (d / "bridge.json").write_text(json.dumps({"port": w.port, "token": TOKEN}))
    r = run(["mcp", "--connect"], input=mcp_lines([call(2, "inspect_model")]))
    golden.check(transcript(r, w.port), "home_bridge.txt")


def test_render_through_the_window(run, workdir, golden):
    """CATCHES: a rewrite whose render tool asks the window with a different set of keys, or captions its reply
    differently (a 3D view's angles, a written path)."""
    w = window(results=[{"ok": {"kind": "3D view", "view": "{3D}", "azimuth": 135.0, "elevation": 20.0, "width": 320, "height": 240,
                                "pngBase64": "iVBORw0KGgo="}},
                        {"ok": {"kind": "plan", "view": "Level 1", "width": 100, "height": 80, "path": "plan.png"}},
                        {"ok": {"view": "A101"}},
                        {"error": "render: there's no view `Nowhere`"}])
    env = bridge(workdir, w.port)
    msgs = [call(2, "render", {"view": "{3D}", "azimuth": 135, "elevation": 20, "width": 320, "height": 240}),
            call(3, "render", {"path": "plan.png", "width": 100, "height": 80}), call(4, "render", {"view": "A101"}),
            call(5, "render", {"view": "Nowhere"})]
    r = run(["mcp", "--connect"], input=mcp_lines(msgs), env_overrides=env)
    golden.check(transcript(r, w.port), "render_window.txt")
    golden.check(w.recorded(), "render_window.requests")
