"""lumen-web's network and platform surface: Lumen.serve (server.rs) driven by fetch (http.rs) in
the same script, raw node:net peers that script the exact wire bytes for both sides, the RFC 6455
WebSocket client (against a scripted Python peer, which answers the upgrade without depending on
the program's own event loop) and server-side upgrade (websocket.rs, sha1.rs), EventSource (sse.rs), the URL
parser (url.rs) and the remaining WinterTC globals (encoding, base64, structuredClone, events and
abort signals, crypto.subtle.digest/sha256.rs, compression streams, performance).

Everything binds 127.0.0.1 port 0; ports never reach the output (programs mask them as PORT/DEAD),
and the "Server: lumen/<version>" / "User-Agent: lumen/<version>" defaults are masked or replaced by
the handler. Each program awaits one exchange at a time so the printed order never depends on
scheduling, and it shuts its servers down so the process exits on its own.
"""

import base64
import hashlib
import socket
import struct
import threading

import pytest

from conftest import err, out

TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"), pytest.param(("--tier=interp",), id="interp")]


# ------------------------------------------------------------------ scripted WebSocket peer
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(op, payload=b"", fin=True, rsv=0, mask=None):
    """One server->client frame (unmasked unless `mask` is given)."""
    payload = bytes(payload)
    head = bytes([(0x80 if fin else 0) | rsv | op])
    mbit = 0x80 if mask else 0
    n = len(payload)
    if n < 126:
        head += bytes([mbit | n])
    elif n < 65536:
        head += bytes([mbit | 126]) + struct.pack(">H", n)
    else:
        head += bytes([mbit | 127]) + struct.pack(">Q", n)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        head += bytes(mask)
    return head + payload


def ws_close(code, reason=b""):
    return ws_frame(8, struct.pack(">H", code) + reason)


FRAG = b"".join([
    ws_frame(1, b"fr", fin=False), ws_frame(9, b"mid"), ws_frame(10, b"unsolicited pong"), ws_frame(0, b"agm", fin=False),
    ws_frame(0, b"ent"), ws_frame(2, b"\x07" * 300), ws_frame(1, b"x" * 70000),
    ws_frame(1, b"masked by server", mask=[1, 2, 3, 4]), ws_close(1000, b"done"),
])
# Frames a server opens with, per path (the client's reaction is what the tests observe).
OPENERS = {
    "/ping": ws_frame(9, b"marco"),
    "/frag": FRAG,
    "/close4001": ws_close(4001, b"going away"),
    "/closenocode": ws_frame(8),
    "/huge": bytes([0x82, 127]) + struct.pack(">Q", 1 << 40),
    "/rsv": ws_frame(1, b"x", rsv=0x40),
    "/badutf8": ws_frame(1, b"\xc3\x28"),
    "/opcode": ws_frame(3, b"?"),
    "/cont": ws_frame(0, b"orphan"),
    "/newdata": ws_frame(1, b"a", fin=False) + ws_frame(1, b"b"),
    "/ctlfrag": ws_frame(9, b"p", fin=False),
    "/badclose": ws_frame(8, b"\x03\xe8\xff"),
}


class WsPeer:
    """A scripted RFC 6455 server on 127.0.0.1 run in a background thread of the test process, so
    it answers the upgrade immediately whatever the program under test is doing. The path picks
    the behaviour; `GET /log` returns what the server observed (after every earlier session has
    finished), one line per path."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        if hasattr(socket, "TCP_DEFER_ACCEPT"):
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_DEFER_ACCEPT, 1)
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.log = {}
        self.sessions = []
        self.lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self.sock.close()

    def _note(self, path, line):
        with self.lock:
            self.log.setdefault(path, []).append(line)

    def _accept(self):
        # The lumen client gives the upgrade response only 100 ms per read, so the handshake is
        # answered right here on the accept thread (with TCP_DEFER_ACCEPT, accept() returns once
        # the request bytes are already queued); only the frame exchange moves to a thread.
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            path = self._handshake(conn)
            if path is None:
                conn.close()
                continue
            t = threading.Thread(target=self._session, args=(conn, path), daemon=True)
            with self.lock:
                self.sessions.append(t)
            t.start()

    @staticmethod
    def _read_exact(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def _read_frame(self, conn):
        b0, b1 = self._read_exact(conn, 2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read_exact(conn, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read_exact(conn, 8))[0]
        key = self._read_exact(conn, 4) if b1 & 0x80 else None
        data = self._read_exact(conn, n)
        if key:
            data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        return b0 & 0x0F, bool(b1 & 0x80), data

    def _handshake(self, conn):
        """Answer one request; returns the path when a WebSocket session should follow."""
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(65536)
                if not chunk:
                    return None
                head += chunk
            lines = head.split(b"\r\n\r\n")[0].decode().split("\r\n")
            path = lines[0].split(" ")[1]
            hdrs = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:] if ":" in l)}
            if path == "/log":
                for t in list(self.sessions):
                    t.join(10)
                with self.lock:
                    body = "".join(f"server {p}: {' | '.join(v)}\n" for p, v in sorted(self.log.items())).encode()
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
                return None
            if path == "/echo":
                shown = [l for l in lines if not l.lower().startswith(("host:", "sec-websocket-key:"))]
                self._note(path, "handshake " + " / ".join(shown))
            if path == "/refuse":
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return None
            key = hdrs.get("sec-websocket-key", "").encode()
            accept = base64.b64encode(hashlib.sha1(key + GUID).digest()).decode()
            if path == "/badaccept":
                accept = "AAAAAAAAAAAAAAAAAAAAAAAAAAA="
            resp = "HTTP/1.1 101 Switching Protocols\r\n"
            if path == "/bighead":
                resp += "X-Filler: " + "f" * 70000 + "\r\n"
            if path != "/noupgrade":
                resp += "Upgrade: websocket\r\n"
            resp += f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n"
            offered = hdrs.get("sec-websocket-protocol")
            if path == "/echo" and offered:
                resp += f"Sec-WebSocket-Protocol: {offered.split(',')[-1].strip()}\r\n"
            if path == "/proto":
                resp += "Sec-WebSocket-Protocol: unasked\r\n"
            conn.sendall(resp.encode() + b"\r\n" + OPENERS.get(path, b""))
            if path == "/hangup":
                conn.shutdown(socket.SHUT_WR)
            return path
        except OSError:
            return None

    def _session(self, conn, path):
        try:
            while True:
                op, masked, data = self._read_frame(conn)
                if op == 8:
                    code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else "none"
                    self._note(path, f"saw close masked={masked} code={code} reason={data[2:].decode()!r}")
                    if path in ("/echo", "/ping"):
                        conn.sendall(ws_frame(8, data))
                    return
                if path == "/echo":
                    shown = data.decode() if op == 1 else list(data)
                    self._note(path, f"saw op={op} masked={masked} {shown!r}"[:120])
                    conn.sendall(ws_frame(op, data))
                elif path == "/ping" and op == 10:
                    conn.sendall(ws_frame(1, b"pong:" + data))
        except (EOFError, OSError):
            pass
        finally:
            conn.close()


@pytest.fixture
def ws_peer():
    peer = WsPeer()
    yield peer
    peer.close()


@pytest.fixture
def dead_port():
    """A loopback port held bound but never listened on: connecting to it is refused, and no other
    process can take it over while the test runs."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    yield s.getsockname()[1]
    s.close()


# session(path) connects the lumen WebSocket client to the peer (its port is argv[2]) and resolves
# with one line describing every event; serverLog() fetches what the peer observed.
WS_CLIENT = r"""
// session(path) connects to the scripted peer and resolves with one line describing every event.
const port = Number(process.argv[2]);
function session(path, protocols, onOpen) {
  return new Promise((resolve) => {
    const log = [];
    const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`, protocols);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => { log.push(`open protocol=${JSON.stringify(ws.protocol)}`); if (onOpen) onOpen(ws); };
    ws.onmessage = (e) => {
      const d = typeof e.data === "string" ? (e.data.length > 40 ? `text(${e.data.length} chars)` : JSON.stringify(e.data)) : `binary(${e.data.byteLength} bytes, first=${new Uint8Array(e.data)[0]})`;
      log.push("message " + d);
      if (ws.onnext) ws.onnext(e);
    };
    ws.onerror = (e) => log.push("error event " + e.type);
    ws.onclose = (e) => { log.push(`close code=${e.code} reason=${JSON.stringify(e.reason)} clean=${e.wasClean} state=${ws.readyState}`); resolve(`${path}: ${log.join(" | ")}`); };
  });
}
const serverLog = async () => (await fetch(`http://127.0.0.1:${port}/log`)).text();
"""


def test_serve_and_fetch_methods_headers_bodies(js, golden):
    """CATCHES: a Lumen.serve/fetch pair that loses the request method, path, percent-decoded query,
    custom request headers or the body and its implied Content-Type/Content-Length, drops
    handler-set response headers, mis-sorts Headers iteration, or returns a body for HEAD."""
    code = r"""
const server = Lumen.serve(async (req, info) => {
  const url = new URL(req.url);
  const body = req.method === "GET" || req.method === "HEAD" ? "" : await req.text();
  const echo = {
    method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams),
    custom: req.headers.get("x-custom"), accept: req.headers.get("accept"), type: req.headers.get("content-type"),
    length: req.headers.get("content-length"), body, transport: info.remoteAddr.transport, from: info.remoteAddr.hostname,
  };
  return new Response(JSON.stringify(echo), { status: 200, headers: { "content-type": "application/json", "x-reply": "yes", server: "test-server" } });
}, { hostname: "127.0.0.1", port: 0 });
const base = `http://127.0.0.1:${server.port}`;
const show = async (label, res) => {
  console.log(label, res.status, JSON.stringify(res.statusText), res.ok, res.redirected, res.url === base + new URL(res.url).pathname + new URL(res.url).search);
  console.log("  headers", JSON.stringify([...res.headers]));
  console.log("  body", await res.text());
};
await show("GET", await fetch(base + "/items?id=7&tag=a%20b", { headers: { "X-Custom": "hello", Accept: "application/json" } }));
await show("POST", await fetch(base + "/items", { method: "POST", body: "plain text body" }));
await show("PUT", await fetch(new Request(base + "/items/7", { method: "put", headers: [["content-type", "application/json"]], body: JSON.stringify({ n: 1 }) })));
await show("DELETE", await fetch(base + "/items/7", { method: "DELETE" }));
const head = await fetch(base + "/head", { method: "HEAD" });
console.log("HEAD", head.status, head.headers.get("content-length"), JSON.stringify(await head.text()));
await server.shutdown();
console.log("server finished");
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("serve_and_fetch_methods_headers_bodies")
    assert (r.returncode, r.stderr) == (0, b"")


def test_showcase_fetch_against_local_server(js, golden):
    """CATCHES: the WinterTC showcase's fetch-against-Lumen.serve round trip failing: Response.json()
    bodies not parsed back by res.json(), the request URL not reaching the handler as an
    absolute URL, or shutdown() not resolving so the process hangs."""
    code = r"""
// examples/wintertc-showcase: fetch + HTTP server
const server = Lumen.serve((request) => Response.json({ path: new URL(request.url).pathname, ok: true }), {
  hostname: "127.0.0.1",
  port: 0,
});
const res = await fetch(`http://127.0.0.1:${server.port}/hello`);
console.log("fetch JSON", JSON.stringify(await res.json()));
const again = await fetch(`http://127.0.0.1:${server.port}/second/path?ignored=1`);
console.log("fetch JSON", JSON.stringify(await again.json()), again.status, again.ok);
await server.shutdown();
console.log("shutdown resolved");
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("showcase_fetch_against_local_server")
    assert (r.returncode, r.stderr) == (0, b"")


def test_status_codes_and_reason_phrases(js, golden):
    """CATCHES: a server that sends the wrong default reason phrase for common statuses (or invents one
    for 418/599), ignores a custom statusText, emits a body or a non-zero Content-Length for
    204/304, or a client that computes Response.ok wrongly."""
    code = r"""
const server = Lumen.serve((req) => {
  const p = new URL(req.url).pathname.slice(1);
  const [code, text] = p.split("-");
  const init = { status: Number(code), headers: { server: "t" } };
  if (text) init.statusText = decodeURIComponent(text);
  return new Response(Number(code) === 204 || Number(code) === 304 ? null : `status ${code}`, init);
}, { hostname: "127.0.0.1", port: 0 });
const base = `http://127.0.0.1:${server.port}/`;
for (const p of ["200", "201", "202", "204", "304", "400", "401", "403", "404", "405", "409", "410", "418", "422", "429", "500", "501", "502", "503", "599", "200-All%20Good", "404-Nope"]) {
  const r = await fetch(base + p);
  const body = await r.text();
  console.log(p.padEnd(15), r.status, JSON.stringify(r.statusText), r.ok, r.headers.get("content-length"), JSON.stringify(body));
}
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("status_codes_and_reason_phrases")
    assert (r.returncode, r.stderr) == (0, b"")


def test_redirect_following(js, golden):
    """CATCHES: fetch redirect handling that keeps POST/PUT bodies across 301/302/303 (which must
    become GET), drops the method or body on 307/308, resolves relative Location headers against
    the wrong base, mis-reports redirected/url, follows a 3xx without Location, or loops forever
    instead of rejecting after the hop limit."""
    code = r"""
const seen = [];
const server = Lumen.serve(async (req) => {
  const url = new URL(req.url);
  const body = req.method === "GET" || req.method === "HEAD" ? "" : await req.text();
  seen.push(`${req.method} ${url.pathname}${url.search}${body ? " body=" + body : ""}`);
  const p = url.pathname;
  const go = (status, location) => new Response(null, { status, headers: { location } });
  if (p === "/301") return go(301, "/final?via=301");
  if (p === "/302") return go(302, "/final?via=302");
  if (p === "/303") return go(303, "final?via=303");
  if (p === "/307") return go(307, `http://127.0.0.1:${server.port}/final?via=307`);
  if (p === "/308") return go(308, "/final?via=308");
  if (p === "/chain/1") return go(302, "/chain/2");
  if (p === "/chain/2") return go(302, "../final?via=chain");
  if (p === "/loop") return go(302, "/loop");
  if (p === "/nolocation") return new Response("stay here", { status: 302 });
  return new Response(`${req.method} ${p}${url.search} ${body}`);
}, { hostname: "127.0.0.1", port: 0 });
const base = `http://127.0.0.1:${server.port}`;
const mask = (s) => s.split(String(server.port)).join("PORT");
for (const [path, method] of [["/301", "POST"], ["/302", "POST"], ["/303", "PUT"], ["/307", "POST"], ["/308", "PATCH"], ["/301", "GET"], ["/chain/1", "GET"], ["/nolocation", "GET"]]) {
  const init = method === "GET" ? {} : { method, body: "payload" };
  const res = await fetch(base + path, init);
  console.log(method.padEnd(5), path.padEnd(11), "->", res.status, res.redirected, mask(res.url), JSON.stringify(await res.text()));
}
try { await fetch(base + "/loop"); } catch (e) { console.log("loop:", e.name, mask(e.message)); }
console.log("server saw:"); for (const s of seen) console.log("  " + s);
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("redirect_following")
    assert (r.returncode, r.stderr) == (0, b"")


def test_request_body_kinds(js, golden):
    """CATCHES: request bodies serialised wrongly for strings (UTF-8), typed-array views with an
    offset, ArrayBuffers, URLSearchParams and Blobs (with their default Content-Type),
    synchronously-filled ReadableStreams, or FormData multipart encoding whose boundary framing
    cannot be parsed back by formData()."""
    code = r"""
const server = Lumen.serve(async (req) => {
  const type = req.headers.get("content-type") || "(none)";
  const bytes = new Uint8Array(await req.arrayBuffer());
  const text = new TextDecoder().decode(bytes).replace(/\r\n/g, "\\r\\n").replace(/----lumenFormBoundary[0-9a-f]{32}/g, "BOUNDARY");
  let parsed = "";
  if (type.startsWith("multipart/form-data")) {
    const fd = await new Response(bytes, { headers: { "content-type": type } }).formData();
    parsed = " | parsed: " + [...fd].map(([k, v]) => (typeof v === "string" ? `${k}=${v}` : `${k}=File(${v.name},${v.type},${v.size})`)).join(" ");
  }
  return new Response(`${type.replace(/boundary=.*/, "boundary=...")} | ${bytes.length} bytes | ${text}${parsed}`);
}, { hostname: "127.0.0.1", port: 0 });
const url = `http://127.0.0.1:${server.port}/upload`;
const form = new FormData();
form.append("name", "lumen");
form.append("file", new File(["file body"], "a.txt", { type: "text/plain" }));
const bodies = [
  ["string", "héllo"],
  ["Uint8Array", new Uint8Array([104, 105])],
  ["ArrayBuffer", new Uint8Array([1, 2, 3]).buffer],
  ["Int16Array view", new Int16Array([0x4142, 0x4344]).subarray(1)],
  ["URLSearchParams", new URLSearchParams({ q: "a b&c", n: "1" })],
  ["Blob", new Blob(["blob ", "parts"], { type: "text/x-blob" })],
  ["ReadableStream", new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode("streamed ")); c.enqueue("chunks"); c.close(); } })],
  ["FormData", form],
];
for (const [label, body] of bodies) {
  const res = await fetch(url, { method: "POST", body });
  console.log(label.padEnd(16), await res.text());
}
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("request_body_kinds")
    assert (r.returncode, r.stderr) == (0, b"")


def test_serve_handler_errors_and_on_error(js, golden):
    """CATCHES: Lumen.serve that crashes or hangs when a handler throws, rejects, returns a
    non-Response or an already-consumed Response, that does not log the error to stderr and
    answer 500, or that ignores the onError hook (or lets a throwing onError escape)."""
    code = r"""
// Handler failures: the default path logs to stderr and answers 500; onError can replace the response.
const get = async (port, path) => { const r = await fetch(`http://127.0.0.1:${port}${path}`); return `${r.status} ${r.statusText} | ${await r.text()}`; };
const handler = async (req) => {
  const p = new URL(req.url).pathname;
  if (p === "/throw") throw new RangeError("handler exploded");
  if (p === "/reject") return Promise.reject(new Error("async rejection"));
  if (p === "/string") return "just a string";
  if (p === "/used") { const r = new Response("once"); await r.text(); return r; }
  return new Response("fine " + p);
};
const s1 = Lumen.serve(handler, { hostname: "127.0.0.1", port: 0 });
for (const p of ["/ok", "/throw", "/reject", "/string", "/used"]) console.log("default", p.padEnd(8), await get(s1.port, p));
await s1.shutdown();
const s2 = Lumen.serve({ hostname: "127.0.0.1", port: 0, onError: (e) => new Response(`custom: ${e.name}: ${e.message}`, { status: 502 }) }, handler);
for (const p of ["/throw", "/string", "/ok"]) console.log("onError", p.padEnd(8), await get(s2.port, p));
await s2.shutdown();
const s3 = Lumen.serve(handler, { hostname: "127.0.0.1", port: 0, onError: async () => { throw new Error("onError failed too"); } });
console.log("onError throws", await get(s3.port, "/throw"));
await s3.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("serve_handler_errors_and_on_error")
    assert (r.returncode, err(r)) == (0, 'RangeError: handler exploded\nError: async rejection\nTypeError: serve handler did not return a Response\n')


def test_serve_call_forms_lifecycle_and_argument_errors(js, golden):
    """CATCHES: Lumen.serve overloads (Deno-style {fetch}, app objects whose fetch needs `this`),
    onListen, AbortSignal shutdown (including an already-aborted signal) or the finished promise
    misbehaving, a bind conflict or out-of-range port that is not reported, or a missing handler
    that is accepted."""
    code = r"""
// The serve() call forms, onListen, AbortSignal-driven shutdown, argument errors and bind conflicts.
const get = async (port, path) => { const r = await fetch(`http://127.0.0.1:${port}${path}`); return `${r.status} | ${await r.text()}`; };
let listened;
const s4 = Lumen.serve({ hostname: "127.0.0.1", port: 0, onListen: (info) => { listened = info; }, fetch: (req) => new Response("deno-style " + req.method) });
console.log("onListen", listened.hostname, typeof listened.port, listened.port === s4.port, "server.hostname", s4.hostname);
console.log("object form", await get(s4.port, "/"));
const mask = (s) => s.split(String(s4.port)).join("PORT");
try { Lumen.serve(() => new Response("dup"), { hostname: "127.0.0.1", port: s4.port }); } catch (e) { console.log("port in use:", e.name, mask(e.message)); }
await s4.shutdown();
const app = { greeting: "app-object", fetch(req) { return new Response(this.greeting + " " + new URL(req.url).pathname); } };
const s5 = Lumen.serve(Object.assign(app, { hostname: "127.0.0.1", port: 0 }));
console.log("app object", await get(s5.port, "/x"), "|", await get(s5.port, "/y"));
await s5.shutdown();
const ac = new AbortController();
const s6 = Lumen.serve(() => new Response("abortable"), { hostname: "127.0.0.1", port: 0, signal: ac.signal });
console.log("before abort", await get(s6.port, "/"));
ac.abort();
await s6.finished;
console.log("finished after abort; methods:", typeof s6.ref, typeof s6.unref, typeof s6.shutdown, s6.finished instanceof Promise);
const s7 = Lumen.serve(() => new Response("x"), { hostname: "127.0.0.1", port: 0, signal: AbortSignal.abort() });
await s7.finished;
console.log("pre-aborted signal: finished without serving");
const wild = Lumen.serve(() => new Response("bound to every interface"), { port: 0 });
console.log("default hostname", wild.hostname, await get(wild.port, "/"));
await wild.shutdown();
console.log("wildcard server shut down");
try { Lumen.serve(); } catch (e) { console.log(e.name + ": " + e.message); }
try { Lumen.serve(42); } catch (e) { console.log(e.name + ": " + e.message); }
try { Lumen.serve(() => {}, { hostname: "127.0.0.1", port: 70000 }); } catch (e) { console.log(e.name + ": " + e.message); }
try { Lumen.serve(() => {}, { hostname: "127.0.0.1", port: -1 }); } catch (e) { console.log(e.name + ": " + e.message); }
console.log("Lumen.version", typeof Lumen.version, /^\d+\.\d+\.\d+/.test(Lumen.version), Object.keys(Lumen).sort().join(","));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("serve_call_forms_lifecycle_and_argument_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fetch_parses_raw_http_responses(js, golden):
    """CATCHES: an HTTP client that mis-decodes chunked bodies (chunk extensions, trailers), cannot
    read an unframed body to EOF, over-reads past Content-Length, reads a body for HEAD/204,
    trims or combines headers wrongly, accepts a garbage status line or bad chunk size, or sends
    a malformed request (Host, Connection: close, default User-Agent, Content-Length, no
    fragment)."""
    code = r"""
// A raw node:net server scripted per path, to pin how fetch parses what comes off the wire.
import net from "node:net";
const replies = {
  "/chunked": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nX-Kind: chunked\r\n\r\n4\r\nWiki\r\n5;name=ext\r\npedia\r\nA\r\n in chunks\r\n0\r\nX-Trailer: ignored\r\n\r\n",
  "/eof": "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nno length, read until the server closes",
  "/length": "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhelloEXTRA-BYTES-IGNORED",
  "/noreason": "HTTP/1.1 299\r\nContent-Length: 2\r\n\r\nok",
  "/spaces": "HTTP/1.1 200 Very  Fine  Indeed\r\nX-Padded:   value with spaces   \r\nNoColonLine\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\nContent-Length: 0\r\n\r\n",
  "/204": "HTTP/1.1 204 No Content\r\nContent-Length: 10\r\n\r\n",
  "/head": "HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n",
  "/bad-status": "garbage\r\n\r\n",
  "/bad-chunk": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nabc\r\n0\r\n\r\n",
  "/hangup": "",
};
const heads = [];
const server = net.createServer((sock) => {
  let buf = "";
  sock.on("data", (d) => {
    buf += d.toString("latin1");
    const end = buf.indexOf("\r\n\r\n");
    if (end < 0) return;
    const head = buf.slice(0, end);
    const [method, path] = head.split(" ");
    const len = Number((/content-length: (\d+)/i.exec(head) || [0, 0])[1]);
    if (buf.length < end + 4 + len) return;
    heads.push(head.split(String(port)).join("PORT").replace(/lumen\/[\d.]+\S*/, "lumen/VERSION") + (len ? " || " + buf.slice(end + 4) : ""));
    sock.end(replies[path] ?? "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n");
    buf = "";
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const base = `http://127.0.0.1:${port}`;
const mask = (s) => s.split(String(port)).join("PORT");
for (const [path, init] of [["/chunked"], ["/eof"], ["/length"], ["/noreason"], ["/spaces"], ["/204"], ["/head", { method: "HEAD" }], ["/bad-status"], ["/bad-chunk"], ["/hangup"]]) {
  try {
    const r = await fetch(base + path, init);
    console.log(path, r.status, JSON.stringify(r.statusText), JSON.stringify([...r.headers]), JSON.stringify(await r.text()));
  } catch (e) {
    console.log(path, "rejected", e.name, JSON.stringify(mask(e.message)));
  }
}
await fetch(base + "/echo-request", { method: "post", headers: { "X-One": "1", "user-agent": "custom-agent", Host: "ignored.example", Connection: "keep-alive" }, body: "abc" }).catch(() => {});
await fetch(base + "/q?x=1&y=%20#frag").catch(() => {});
server.close();
console.log("requests as received:");
for (const h of heads) console.log("  " + JSON.stringify(h));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("fetch_parses_raw_http_responses")
    assert (r.returncode, r.stderr) == (0, b"")


def test_serve_parses_raw_http_requests(js, golden):
    """CATCHES: a server that mis-parses requests (lower-case methods, chunked request bodies,
    absolute-form and asterisk-form targets, a missing Host header), lets the handler override
    Connection/Transfer-Encoding framing, omits Content-Length, or stops serving after answering
    a malformed request with 400."""
    code = r"""
// Raw node:net clients talking to Lumen.serve, to pin request parsing and response serialisation.
import net from "node:net";
const server = Lumen.serve(async (req) => {
  const u = new URL(req.url);
  if (u.pathname === "/fixed") return new Response("abc", { headers: { "content-length": "3", server: "raw-test" } });
  const body = req.method === "GET" || req.method === "HEAD" ? "" : await req.text();
  const hdrs = [...req.headers].map(([k, v]) => `${k}=${v}`).join(";");
  return new Response(`${req.method} ${u.host === "127.0.0.1:" + server.port ? "SELF" : u.host} ${u.pathname}${u.search} [${body}] {${hdrs.split(String(server.port)).join("PORT")}}`, {
    headers: { server: "raw-test", "X-Extra": "1", connection: "keep-alive", "transfer-encoding": "gzip" },
  });
}, { hostname: "127.0.0.1", port: 0 });
const raw = (payload) => new Promise((resolve) => {
  const sock = net.connect(server.port, "127.0.0.1", () => sock.end(payload));
  let got = "";
  sock.on("data", (d) => (got += d.toString("latin1")));
  sock.on("close", () => resolve(got));
  sock.on("error", (e) => resolve("socket error " + e.code));
});
const show = (label, text) => console.log(label.padEnd(10), JSON.stringify(text.split(String(server.port)).join("PORT")));
show("simple", await raw("GET /a?b=1 HTTP/1.1\r\nHost: example.test\r\nX-Thing:  spaced  \r\n\r\n"));
show("post", await raw("post /submit HTTP/1.1\r\nHost: h\r\nContent-Length: 11\r\n\r\nhello world"));
show("chunked", await raw("PUT /up HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n4;x=y\r\ndefg\r\n0\r\n\r\n"));
show("absolute", await raw("GET http://proxy.example/full/path?q HTTP/1.1\r\nHost: other\r\n\r\n"));
show("asterisk", await raw("OPTIONS * HTTP/1.1\r\nHost: h\r\n\r\n"));
show("no-host", await raw("GET /nohost HTTP/1.0\r\n\r\n"));
show("no-body", await raw("DELETE /thing HTTP/1.1\r\nHost: h\r\n\r\n"));
show("malformed", await raw("\r\n\r\n"));
show("bad chunk", await raw("POST /x HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\nnothex\r\n"));
show("empty", await raw(""));
show("cut head", await raw("GET /cut-short HTTP/1.1\r\nHost: h\r\nX-Partial: yes\r\n"));
show("after 400", await raw("GET /still-serving HTTP/1.1\r\nHost: h\r\n\r\n"));
show("fixed len", await raw("GET /fixed HTTP/1.1\r\nHost: h\r\n\r\n"));
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("serve_parses_raw_http_requests")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fetch_error_paths(js, golden, dead_port):
    """CATCHES: fetch that resolves (or throws synchronously) for refused connections, non-http
    schemes, relative URLs, invalid ports or GET bodies, that ignores an already-aborted signal
    or its custom reason, or that does not reject an in-flight request with AbortError when its
    signal aborts."""
    code = r"""
// argv[2]: a port the test holds bound but not listening, so connecting is refused
const dead = Number(process.argv[2]);
const mask = (s) => s.split(String(dead)).join("DEAD");
const attempt = async (label, ...args) => {
  try { const r = await fetch(...args); console.log(label, "resolved", r.status); }
  catch (e) { console.log(label.padEnd(16), e.constructor.name, e.name, JSON.stringify(mask(e.message))); }
};
await attempt("refused", `http://127.0.0.1:${dead}/x`);
await attempt("refused https", `https://127.0.0.1:${dead}/secure`);
await attempt("ftp scheme", "ftp://127.0.0.1/file");
await attempt("data scheme", "data:text/plain,hi");
await attempt("relative", "/just/a/path");
await attempt("bad port", "http://127.0.0.1:99999/");
await attempt("GET with body", "http://127.0.0.1:1/", { body: "x" });
await attempt("pre-aborted", `http://127.0.0.1:${dead}/`, { signal: AbortSignal.abort() });
const ac = new AbortController(); ac.abort(new Error("custom abort reason"));
await attempt("custom reason", `http://127.0.0.1:${dead}/`, { signal: ac.signal });
const p = fetch("ftp://x/");
console.log("fetch returns a promise even on bad input:", p instanceof Promise);
await p.catch(() => {});
// abort while the request is in flight: the handler holds the response until after the abort
let release;
const held = new Promise((r) => (release = r));
let arrived;
const arrivedP = new Promise((r) => (arrived = r));
const server = Lumen.serve(async () => { arrived(); await held; return new Response("too late"); }, { hostname: "127.0.0.1", port: 0 });
const ctl = new AbortController();
const inflight = fetch(`http://127.0.0.1:${server.port}/slow`, { signal: ctl.signal });
await arrivedP;
ctl.abort();
await inflight.then((r) => console.log("in-flight resolved?", r.status), (e) => console.log("in-flight abort:", e.name, e.message, e instanceof DOMException));
release();
await server.shutdown();
console.log("server drained");
"""
    r = js(code, name="main.mjs", args=(str(dead_port),))
    assert out(r) == golden("fetch_error_paths")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_headers_request_response_api(js, golden, tier):
    """CATCHES: Headers that do not lower-case, combine, sort, trim or validate names, Request/Response
    objects with wrong defaults, cloning, body-consumption (bodyUsed, single read) or status
    validation, and broken body readers (arrayBuffer, bytes, blob, json, urlencoded and
    multipart formData, ReadableStream body)."""
    code = r"""
const errOf = (f) => { try { return "ok " + f(); } catch (e) { return `${e.name}: ${e.message}`; } };
const h = new Headers({ "Content-Type": "text/html", "X-B": " padded value  " });
h.append("x-a", "1"); h.append("X-A", "2"); h.set("x-c", "3"); h.delete("X-B");
console.log("entries", JSON.stringify([...h]), "get", h.get("X-A"), h.get("missing"), "has", h.has("CONTENT-TYPE"));
console.log("keys", [...h.keys()].join(","), "values", [...h.values()].join("|"));
const fe = []; h.forEach((v, k, self) => fe.push(`${k}:${v}:${self === h}`)); console.log("forEach", fe.join(" "));
console.log("from pairs", JSON.stringify([...new Headers([["b", "2"], ["a", "1"]])]), "copy", JSON.stringify([...new Headers(h)]));
console.log("bad name", errOf(() => new Headers({ "bad name": "x" })), "|", errOf(() => h.get("a:b")), "| bad pair", errOf(() => new Headers([["only"]])));
const req = new Request("http://example.test/path?q=1", { method: "post", headers: { "X-Req": "r" }, body: "payload" });
console.log("request", req.method, req.url, req.headers.get("x-req"), req.headers.get("content-type"), req.bodyUsed);
const clone = req.clone();
console.log("text", await req.text(), req.bodyUsed, "clone text", await clone.text(), "consume twice", await req.text().catch((e) => `${e.name}: ${e.message}`));
console.log("GET body", errOf(() => new Request("http://x.test/", { body: "nope" })), "| HEAD body", errOf(() => new Request("http://x.test/", { method: "HEAD", body: "x" })));
console.log("relative url", errOf(() => new Request("/relative")));
const derived = new Request(new Request("http://x.test/a", { method: "PUT", body: "orig" }), { headers: { "X-New": "1" } });
console.log("derived", derived.method, derived.url, derived.headers.get("x-new"), await derived.text());
const res = new Response("body text", { status: 201, statusText: "Made", headers: { "X-Res": "yes" } });
console.log("response", res.status, res.statusText, res.ok, res.headers.get("x-res"), res.headers.get("content-type"), res.url === "", res.redirected, res.bodyUsed);
const rc = res.clone();
console.log("arrayBuffer", new Uint8Array(await res.arrayBuffer()).length, "clone bytes", (await rc.bytes()).length, "clone used", errOf(() => rc.clone()));
console.log("defaults", new Response().status, JSON.stringify(new Response().statusText), new Response().body, new Response(null, { status: undefined }).status);
console.log("bad status", errOf(() => new Response("x", { status: 99 })), "|", errOf(() => new Response("x", { status: 600 })));
const err = Response.error(); console.log("error()", err.status, err.type, err.ok);
const j = Response.json({ a: [1, "two"] }, { status: 202, headers: { "content-type": "application/vnd.test+json" } });
console.log("json()", j.status, j.headers.get("content-type"), JSON.stringify(await j.json()));
console.log("json parse error", await new Response("{bad").json().catch((e) => e.name));
const blob = await new Response("blobbed", { headers: { "content-type": "text/x-test" } }).blob();
console.log("blob", blob instanceof Blob, blob.size, blob.type, await blob.text());
const fdu = await new Response("a=1&b=two+words&a=3", { headers: { "content-type": "application/x-www-form-urlencoded" } }).formData();
console.log("formData urlencoded", JSON.stringify([...fdu]));
const form = new FormData(); form.append("k", "v"); form.append("f", new File(["file text"], "f.txt", { type: "text/plain" }));
const back = await new Request("http://x.test/", { method: "POST", body: form }).formData();
const f = back.get("f");
console.log("formData multipart", back.get("k"), f instanceof File, f.name, f.type, await f.text());
console.log("formData unsupported", await new Response("x", { headers: { "content-type": "text/plain" } }).formData().catch((e) => `${e.name}: ${e.message}`));
const streamed = new Response("chunky body");
const reader = streamed.body.getReader();
const first = await reader.read(), second = await reader.read();
console.log("body stream", streamed.body === streamed.body, new TextDecoder().decode(first.value), first.done, second.done, streamed.bodyUsed, await streamed.text().catch((e) => e.message));
let iter = ""; for await (const chunk of new Response("iterated").body) iter += new TextDecoder().decode(chunk); console.log("async iterate body", iter);
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("headers_request_response_api")
    assert (r.returncode, r.stderr) == (0, b"")


def test_websocket_client_well_formed_exchanges(js, golden, ws_peer):
    """CATCHES: a WebSocket client that sends an incomplete upgrade request or unmasked frames, fails
    subprotocol negotiation, cannot reassemble fragmented messages around an interleaved ping,
    mishandles 16/64-bit payload lengths or masked server frames, does not answer pings, or
    reports the wrong code/reason/wasClean for client- and server-initiated closes (1005 when no
    code)."""
    code = r"""
console.log(await session("/echo", ["one", "two"], (ws) => {
  const sends = [() => ws.send("hi there"), () => ws.send(new Uint8Array([9, 8, 7])), () => ws.send("x".repeat(200)), () => ws.close(3001, "client done")];
  ws.onnext = () => sends.shift()();
  sends.shift()();
}));
console.log(await session("/ping", undefined, (ws) => { ws.onnext = () => ws.close(); }));
for (const path of ["/frag", "/close4001", "/closenocode"]) console.log(await session(path));
process.stdout.write(await serverLog());
"""
    r = js(WS_CLIENT + code, name="main.mjs", args=(str(ws_peer.port),))
    assert out(r) == golden("websocket_client_well_formed_exchanges")
    assert (r.returncode, r.stderr) == (0, b"")


def test_websocket_client_protocol_failures(js, golden, ws_peer):
    """CATCHES: a client that tolerates RSV bits, invalid UTF-8 (text or close reason), unknown
    opcodes, stray or interleaved continuation frames, fragmented control frames or a 2^40-byte
    length instead of failing with close code 1002/1007/1009 (echoed to the peer), or that opens
    despite a bad Sec-WebSocket-Accept, an oversized, refused or non-upgrade handshake response,
    or an unrequested subprotocol."""
    code = r"""
for (const path of ["/huge", "/rsv", "/badutf8", "/opcode", "/cont", "/newdata", "/ctlfrag", "/badclose", "/hangup", "/bighead", "/badaccept", "/refuse", "/noupgrade", "/proto"]) {
  console.log(await session(path));
}
process.stdout.write(await serverLog());
"""
    r = js(WS_CLIENT + code, name="main.mjs", args=(str(ws_peer.port),))
    assert out(r) == golden("websocket_client_protocol_failures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_websocket_constructor_and_state_errors(js, golden, dead_port):
    """CATCHES: a WebSocket constructor that accepts relative URLs, non-ws schemes, fragments or
    invalid/duplicate subprotocols, send() while CONNECTING or close() with a reserved code or
    an over-long reason that do not throw the right DOMException, or a refused connection that
    does not fire error then a 1006 CloseEvent."""
    code = r"""
const errOf = (f) => { try { f(); return "no error"; } catch (e) { return `${e.name}: ${e.message}${e instanceof DOMException ? " [DOMException]" : ""}`; } };
console.log("no url:", errOf(() => new WebSocket()));
console.log("relative:", errOf(() => new WebSocket("/socket")));
console.log("ftp scheme:", errOf(() => new WebSocket("ftp://127.0.0.1:1/")));
console.log("fragment:", errOf(() => new WebSocket("ws://127.0.0.1:1/#frag")));
console.log("bad protocol:", errOf(() => new WebSocket("ws://127.0.0.1:1/", "has space")));
console.log("empty protocol:", errOf(() => new WebSocket("ws://127.0.0.1:1/", [""])));
console.log("duplicate protocol:", errOf(() => new WebSocket("ws://127.0.0.1:1/", ["a", "a"])));
console.log("constants", WebSocket.CONNECTING, WebSocket.OPEN, WebSocket.CLOSING, WebSocket.CLOSED, new EventTarget() instanceof EventTarget);
// argv[2]: a port the test holds bound but not listening, so connecting is refused
const dead = Number(process.argv[2]);
const ws = new WebSocket(`ws://127.0.0.1:${dead}/nobody-home`);
console.log("instance", ws instanceof EventTarget, ws.readyState, ws.CONNECTING, ws.OPEN, ws.CLOSING, ws.CLOSED, ws.onopen, ws.onmessage);
console.log("send while connecting:", errOf(() => ws.send("too early")));
console.log("close(1001):", errOf(() => ws.close(1001)));
console.log("close(2999):", errOf(() => ws.close(2999)));
console.log("long reason:", errOf(() => ws.close(1000, "x".repeat(124))));
ws.binaryType = "arraybuffer";
console.log("binaryType", ws.binaryType);
const events = [];
await new Promise((resolve) => {
  ws.onerror = (e) => events.push(`onerror ${e.type} readyState=${ws.readyState}`);
  ws.addEventListener("error", () => events.push("error listener"));
  ws.onclose = (e) => { events.push(`onclose ${e.code} ${JSON.stringify(e.reason)} wasClean=${e.wasClean} ${e instanceof CloseEvent}`); resolve(); };
});
console.log(events.join(" | "));
console.log("after close: send is silently dropped:", errOf(() => ws.send("late")), "close again:", errOf(() => ws.close()));
"""
    r = js(code, name="main.mjs", args=(str(dead_port),))
    assert out(r) == golden("websocket_constructor_and_state_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_websocket_server_upgrade_wire_behaviour(js, golden):
    """CATCHES: Lumen.upgradeWebSocket that computes a wrong Sec-WebSocket-Accept, omits the
    subprotocol or lets user headers override Upgrade/Connection/Accept, mis-decodes masked
    client frames, does not answer pings with unmasked pongs, sends masked frames, does not echo
    the client's close or fail with 1002 on reserved bits, or reports the wrong
    code/reason/clean flag to onclose (1006 when the peer just disconnects)."""
    code = r"""
// A raw node:net client speaking RFC 6455 to a Lumen.serve upgrade, so the server side's own bytes
// (101 response, unmasked pong/close frames) are visible.
import net from "node:net";
const serverLog = [];
let closes = 0, allClosed;
const done = new Promise((r) => (allClosed = r));
const server = Lumen.serve((req) => {
  const ws = Lumen.upgradeWebSocket(req, { protocol: "chat", headers: { "X-Extra": "1", Connection: "keep-alive", Upgrade: "h2c", "Sec-WebSocket-Accept": "forged" } });
  const tag = new URL(req.url).pathname;
  ws.onmessage = (data, isBinary) => serverLog.push(`${tag} message ${isBinary ? "binary " + Array.from(data).join(",") : JSON.stringify(data)}`);
  ws.onclose = (code, reason, clean) => { serverLog.push(`${tag} onclose ${code} ${JSON.stringify(reason)} ${clean}`); if (++closes === 3) allClosed(); };
  return new Response(null);
}, { hostname: "127.0.0.1", port: 0 });
const masked = (op, payload, { rsv = 0 } = {}) => {
  const p = Buffer.from(payload), key = [0x11, 0x22, 0x33, 0x44];
  const out = [0x80 | rsv | op, 0x80 | p.length, ...key];
  for (let i = 0; i < p.length; i++) out.push(p[i] ^ key[i % 4]);
  return Buffer.from(out);
};
const describe = (buf) => {
  const frames = [];
  while (buf.length >= 2) {
    const len = buf[1] & 0x7f;
    const data = buf.subarray(2, 2 + len);
    frames.push(`op=${buf[0] & 0x0f} fin=${(buf[0] & 0x80) !== 0} masked=${(buf[1] & 0x80) !== 0} ` +
      ((buf[0] & 0x0f) === 8 ? `code=${data.readUInt16BE(0)} reason=${JSON.stringify(data.subarray(2).toString())}` : JSON.stringify(data.toString())));
    buf = buf.subarray(2 + len);
  }
  return frames.join(" ; ");
};
function session(path, frames) {
  return new Promise((resolve) => {
    let got = Buffer.alloc(0);
    const sock = net.connect(server.port, "127.0.0.1", () => {
      sock.write(`GET ${path} HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: chat\r\n\r\n`);
    });
    let sent = false;
    sock.on("data", (d) => {
      got = Buffer.concat([got, d]);
      const text = got.toString("latin1");
      const end = text.indexOf("\r\n\r\n");
      if (end >= 0 && !sent) { sent = true; for (const f of frames) sock.write(f); if (path === "/drop") sock.end(); }
    });
    sock.on("error", () => {});
    sock.on("close", () => {
      const text = got.toString("latin1");
      const end = text.indexOf("\r\n\r\n");
      resolve(`${path}\n  head: ${JSON.stringify(text.slice(0, end))}\n  frames: ${describe(got.subarray(end + 4))}`);
    });
  });
}
console.log(await session("/talk", [masked(1, "hello"), masked(9, "p1"), masked(2, [7, 8]), masked(10, "unsolicited"), masked(8, [0x03, 0xe8, ...Buffer.from("bye")])]));
console.log(await session("/violate", [masked(1, "ok"), masked(1, "x", { rsv: 0x20 })]));
console.log(await session("/drop", [masked(1, "then hang up")]));
await done;
for (const l of serverLog) console.log("server", l);
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("websocket_server_upgrade_wire_behaviour")
    assert (r.returncode, r.stderr) == (0, b"")


def test_websocket_server_upgrade_guards(js, golden):
    """CATCHES: Lumen.upgradeWebSocket that upgrades plain requests instead of returning null, accepts
    Request objects not delivered by Lumen.serve, or allows the same connection to be upgraded
    twice."""
    code = r"""
// The guards around Lumen.upgradeWebSocket, exercised with raw node:net clients.
import net from "node:net";
const seen = [];
const server = Lumen.serve((req) => {
  const path = new URL(req.url).pathname;
  const ws = Lumen.upgradeWebSocket(req);
  if (ws === null) return new Response(`not upgraded: ${path} upgrade=${req.headers.get("upgrade")}`);
  try { Lumen.upgradeWebSocket(req); } catch (e) { seen.push(`second upgrade: ${e.name}: ${e.message}`); }
  seen.push(`upgraded ${path} remote=${ws.remoteAddress} handle=${["send", "close", "onmessage", "onclose"].map((k) => k + ":" + typeof ws[k]).join(",")}`);
  return new Response("ignored after upgrade");
}, { hostname: "127.0.0.1", port: 0 });
const raw = (payload) => new Promise((resolve) => {
  let got = "";
  const sock = net.connect(server.port, "127.0.0.1", () => sock.write(payload));
  sock.on("data", (d) => { got += d.toString("latin1"); if (got.includes("\r\n\r\n") && got.startsWith("HTTP/1.1 101")) sock.end(); });
  sock.on("error", () => {});
  sock.on("close", () => resolve(got.split("\r\n")[0] + " ... " + (got.split("\r\n\r\n")[1] || "")));
});
console.log(await raw("GET /plain HTTP/1.1\r\nHost: h\r\n\r\n"));
console.log(await raw("GET /no-key HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"));
console.log(await raw("GET /wrong-upgrade HTTP/1.1\r\nHost: h\r\nUpgrade: h2c\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"));
console.log(await raw("GET /ws HTTP/1.1\r\nHost: h\r\nUpgrade: WebSocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"));
try { Lumen.upgradeWebSocket(new Request("http://127.0.0.1/")); } catch (e) { console.log(`foreign request: ${e.name}: ${e.message}`); }
try { Lumen.upgradeWebSocket(undefined); } catch (e) { console.log(`no request: ${e.name}: ${e.message}`); }
for (const l of seen) console.log("server:", l);
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("websocket_server_upgrade_guards")
    assert (r.returncode, r.stderr) == (0, b"")


def test_eventsource_stream_parsing_and_reconnect(js, golden):
    """CATCHES: an EventSource parser that mishandles comments, retry, named events, multi-line data,
    the single leading space, CRLF/CR line endings, id resets and data-less blocks, or that does
    not reconnect with Last-Event-ID after the stream ends, follow redirects, or fail
    permanently on a wrong Content-Type, 204 or 404."""
    code = r"""
// EventSource against Lumen.serve: each response is a complete text/event-stream body, so the client
// sees the stream end, waits `retry` ms and reconnects with Last-Event-ID.
const requests = [];
const server = Lumen.serve((req) => {
  const p = new URL(req.url).pathname;
  const last = req.headers.get("last-event-id");
  requests.push(`${p} accept=${req.headers.get("accept")} cache=${req.headers.get("cache-control")} last-event-id=${last}`);
  const sse = (body) => new Response(body, { headers: { "content-type": "text/event-stream; charset=utf-8" } });
  if (p === "/stream" && last === null) {
    return sse(": a comment line\nretry: 25\ndata: hello\n\nevent: tick\ndata: 42\n\nid: 7\ndata: line one\ndata:line two\ndata:  two spaces\n\n" +
      "data: crlf ends\r\n\r\nevent: tick\r\ndata: cr only\r\rid\ndata: id reset\n\nid: 9\n\nfield-without-colon\ndata\n\nunknown: x\nevent: final-of-first\ndata: bye\n\n");
  }
  if (p === "/stream") return sse(`data: resumed after ${last}\n\nevent: done\ndata: end\n\n`);
  if (p === "/redirect") return new Response(null, { status: 307, headers: { location: "/redirected" } });
  if (p === "/redirected") return sse("data: arrived via redirect\n\n");
  if (p === "/to-ftp") return new Response(null, { status: 302, headers: { location: "ftp://127.0.0.1/feed" } });
  if (p === "/no-location") return new Response(null, { status: 302 });
  if (p === "/loop") return new Response(null, { status: 302, headers: { location: "/loop" } });
  if (p === "/text") return new Response("data: nope\n\n", { headers: { "content-type": "text/plain" } });
  if (p === "/204") return new Response(null, { status: 204 });
  return new Response("missing", { status: 404 });
}, { hostname: "127.0.0.1", port: 0 });
const base = `http://127.0.0.1:${server.port}`;
const log = [];
await new Promise((resolve) => {
  const es = new EventSource(base + "/stream");
  log.push(`created readyState=${es.readyState} url-ok=${es.url === base + "/stream"} withCredentials=${es.withCredentials}`);
  es.onopen = () => log.push(`open readyState=${es.readyState}`);
  es.onmessage = (e) => log.push(`message ${JSON.stringify(e.data)} lastEventId=${JSON.stringify(e.lastEventId)} origin-ok=${e.origin === base}`);
  es.addEventListener("tick", (e) => log.push(`tick ${JSON.stringify(e.data)} type=${e.type}`));
  es.addEventListener("final-of-first", (e) => log.push(`final ${e.data} lastEventId=${JSON.stringify(e.lastEventId)}`));
  es.onerror = () => log.push(`error readyState=${es.readyState}`);
  es.addEventListener("done", () => { es.close(); log.push(`closed readyState=${es.readyState}`); resolve(); });
});
for (const path of ["/redirect", "/text", "/204", "/missing", "/to-ftp", "/no-location", "/loop"]) {
  await new Promise((resolve) => {
    const es = new EventSource(base + path);
    es.onmessage = (e) => { log.push(`${path} message ${e.data}`); es.close(); resolve(); };
    es.onerror = () => { log.push(`${path} error readyState=${es.readyState}`); es.close(); resolve(); };
  });
}
for (const l of log) console.log(l);
console.log("requests:"); for (const r of requests) console.log("  " + r);
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("eventsource_stream_parsing_and_reconnect")
    assert (r.returncode, r.stderr) == (0, b"")


def test_eventsource_errors_and_dribbled_stream(js, golden, dead_port):
    """CATCHES: EventSource construction that accepts relative URLs or non-http schemes, a refused
    connection that does not fire error in CONNECTING state, or a parser that cannot reassemble
    events split across many tiny TCP reads (and a request missing Accept/Cache-Control
    headers)."""
    code = r"""
import net from "node:net";
const errOf = (f) => { try { f(); return "no error"; } catch (e) { return `${e.name}: ${e.message}${e instanceof DOMException ? " (DOMException)" : ""}`; } };
console.log("relative url:", errOf(() => new EventSource("/no-base")));
console.log("ftp scheme:", errOf(() => new EventSource("ftp://127.0.0.1/x")));
console.log("no args:", errOf(() => new EventSource()));
console.log("constants", EventSource.CONNECTING, EventSource.OPEN, EventSource.CLOSED);
// argv[2]: a port the test holds bound but not listening, so connecting is refused
const deadPort = Number(process.argv[2]);
await new Promise((resolve) => {
  const es = new EventSource(`http://127.0.0.1:${deadPort}/`, { withCredentials: true });
  console.log("withCredentials", es.withCredentials);
  es.onerror = () => { console.log("refused: error event, readyState", es.readyState); es.close(); console.log("after close", es.readyState); resolve(); };
});
// a server that accepts and hangs up before sending a response head: a retriable drop
const rude = net.createServer((sock) => sock.end());
await new Promise((r) => rude.listen(0, "127.0.0.1", r));
await new Promise((resolve) => {
  const es = new EventSource(`http://127.0.0.1:${rude.address().port}/`);
  es.onerror = () => { console.log("hung up before head: error event, readyState", es.readyState); es.close(); resolve(); };
});
rude.close();
// raw server that dribbles a stream out in tiny pieces, then idles until the client closes
const heads = [];
const srv = net.createServer((sock) => {
  let head = "";
  sock.on("error", () => {});
  sock.on("data", (d) => {
    head += d.toString("latin1");
    if (!head.includes("\r\n\r\n")) return;
    heads.push(head.split("\r\n").filter((l) => l && !l.startsWith("Host:")).join(" / "));
    const body = "HTTP/1.1 200 OK\r\nContent-Type: Text/Event-Stream\r\n\r\nid: a1\ndata: piece by piece\r\n\r\nevent: custom\ndata: x\ndata: y\n\ndata: last\n\n";
    let i = 0;
    const step = () => { if (i < body.length) { sock.write(body.slice(i, i + 7)); i += 7; setTimeout(step, 2); } else sock.end(); };
    step();
  });
});
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
await new Promise((resolve) => {
  const es = new EventSource(`http://127.0.0.1:${srv.address().port}/dribble?x=1`);
  es.onmessage = (e) => { console.log("dribble message", JSON.stringify(e.data), e.lastEventId); if (e.data === "last") { es.close(); resolve(); } };
  es.addEventListener("custom", (e) => console.log("dribble custom", JSON.stringify(e.data)));
});
srv.close();
console.log("request head:", heads.join(" || "));
"""
    r = js(code, name="main.mjs", args=(str(dead_port),))
    assert out(r) == golden("eventsource_errors_and_dribbled_stream")
    assert (r.returncode, r.stderr) == (0, b"")


def test_url_component_parsing(js, golden):
    """CATCHES: a URL parser that does not lower-case scheme/host, elide default ports for
    http/https/ws/wss/ftp, keep IPv6 brackets, split userinfo, normalise dot segments while
    keeping trailing slashes, preserve existing percent-escapes, trim surrounding spaces, or
    keep opaque paths of mailto:/data:/urn: URLs verbatim."""
    code = r"""
const parts = (u) => [u.href, u.protocol, u.username, u.password, u.host, u.hostname, u.port, u.pathname, u.search, u.hash].map((x) => JSON.stringify(x)).join(" ");
for (const s of [
  "https://example.com",
  "HTTP://User:Secret@Example.COM:8080/a/b?q=1#frag",
  "http://example.com:80/default-port",
  "https://example.com:443/",
  "wss://socket.example:443/chat",
  "ws://socket.example:80",
  "ftp://files.example:21/pub",
  "ftp://files.example:2121/pub",
  "http://[::1]:9000/v6?x",
  "http://[2001:db8::7]/",
  "http://127.0.0.1:3000",
  "http://user@host.test/only-user",
  "http://x.test/a/./b/../c/./d",
  "http://x.test/a/b/..",
  "http://x.test/a/b/.",
  "http://x.test/..//../x",
  "http://x.test/trailing/",
  "http://x.test/%7Efoo/%20bar?%41=%42#%43",
  "http://x.test?only=query",
  "http://x.test#only-frag",
  "  http://trimmed.test/  ",
  "file:///etc/hosts",
  "mailto:someone@example.com?subject=hi",
  "data:text/plain,hello",
  "javascript:void(0)",
  "urn:isbn:0451450523",
  "custom+scheme://host.test/p?q#f",
  "custom://host.test:8080/x",
  "custom://host.test",
  "http://empty-port.test:/",
]) {
  console.log(parts(new URL(s)));
}
for (const s of ["https://example.com:8443/x", "ws://h.test/", "http://[::1]:81/"]) console.log("origin", new URL(s).origin);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("url_component_parsing")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_url_relative_resolution_and_setters(js, golden, tier):
    """CATCHES: relative resolution that mishandles ./ ../ (including above the root), absolute paths,
    scheme-relative //host, query-only and fragment-only references, or URL setters that do not
    re-validate, elide a default port, normalise a new pathname, or keep searchParams in sync
    with search/href."""
    code = r"""
const base = "http://example.com/a/b/c?old=1#oldfrag";
for (const rel of ["d", "./d", "../d", "../../d", "../../../../d", "/root", "//other.host/p", "?new=2", "#newfrag", "", "d?x#y", ".", "..", "d/", "https://abs.example/z"]) {
  console.log(JSON.stringify(rel).padEnd(26), new URL(rel, base).href);
}
console.log("base as URL object:", new URL("x", new URL("https://h.test/dir/file")).href);
const u = new URL("https://user:pw@shop.example:8443/cart/items?id=5&sort=asc#top");
u.hostname = "store.example"; console.log("hostname=", u.href);
u.port = "443"; console.log("port=443", u.href, JSON.stringify(u.port));
u.port = "9000"; console.log("port=9000", u.href, u.host);
u.pathname = "/checkout/step/../done"; console.log("pathname=", u.href, u.pathname);
u.search = "a=1&b=2"; console.log("search=", u.href, u.searchParams.get("b"));
u.search = ""; console.log("search=''", u.href);
u.hash = "section-2"; console.log("hash=", u.href);
u.hash = ""; console.log("hash=''", u.href);
u.href = "http://reset.example/new?k=v"; console.log("href=", u.href, u.searchParams.get("k"), u.protocol);
console.log("toString/toJSON", String(u), JSON.stringify({ u }));
console.log("canParse", URL.canParse("http://a.test"), URL.canParse("nope"), URL.canParse("rel", "http://b.test/"), "parse", URL.parse("http://p.test/x").pathname, URL.parse("::"));
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("url_relative_resolution_and_setters")
    assert (r.returncode, r.stderr) == (0, b"")


def test_url_errors_and_search_params(js, golden):
    """CATCHES: URL construction that accepts relative input without a base, missing hosts, special
    schemes without //, out-of-range or non-numeric ports, unterminated IPv6, non-ASCII hosts
    (IDNA is documented as unsupported) or bad bases, and URLSearchParams with wrong decoding
    (+, %XX, malformed %), set/delete/sort semantics or form-encoding."""
    code = r"""
const errOf = (f) => { try { return "ok " + f(); } catch (e) { return `${e.name}: ${e.message}`; } };
for (const [input, base] of [["relative/path"], ["http://"], ["http:"], ["http://host.test:99999/"], ["http://host.test:abc/"], ["http://[::1/"], ["http://bücher.example/"], ["x", "not a base"], ["", undefined]]) {
  console.log(JSON.stringify([input, base]).padEnd(36), errOf(() => new URL(input, base).href));
}
const p = new URLSearchParams("?a=1&b=two+words&a=3&c=%E2%9C%93&d=&=empty-key&bad=%zz&flag");
console.log("parsed", JSON.stringify([...p]), "size", p.size);
console.log("get", p.get("a"), JSON.stringify(p.get("missing")), "getAll", JSON.stringify(p.getAll("a")), "has", p.has("flag"), p.has("nope"));
p.append("a", "4"); p.set("b", "replaced"); p.delete("c"); p.set("a", "only");
console.log("mutated", p.toString());
const s = new URLSearchParams([["z", "last"], ["a", "2"], ["m", "x"], ["a", "1"]]);
s.sort();
console.log("sorted (stable)", s.toString());
console.log("encode", new URLSearchParams({ "sp ace": "a b", amp: "x&y=z", plus: "1+1", uni: "é✓", star: "*-._" }).toString());
console.log("copy", new URLSearchParams(s).toString() === s.toString(), "keys", [...s.keys()].join(","), "values", [...s.values()].join(","));
const seen = []; s.forEach((v, k, self) => seen.push(`${k}=${v}:${self === s}`)); console.log("forEach", seen.join(" "));
console.log("bad pair", errOf(() => new URLSearchParams([["only-one"]])));
const u = new URL("http://h.test/p?x=1#keep");
u.searchParams.append("y", "a b");
u.searchParams.set("x", "9");
console.log("live searchParams", u.href, u.search);
u.searchParams.delete("x"); u.searchParams.delete("y");
console.log("emptied", u.href);
u.search = "?q=reset";
console.log("search setter refreshes params", u.searchParams.get("q"), u.searchParams.size);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("url_errors_and_search_params")
    assert (r.returncode, r.stderr) == (0, b"")


def test_text_encoder_decoder(js, golden):
    """CATCHES: UTF-8 encoding of 2/3/4-byte sequences and U+0000 done wrongly, TextDecoder that
    ignores views/offsets, does not substitute U+FFFD for invalid or truncated input, keeps a
    BOM (or strips it under ignoreBOM), accepts invalid input in fatal mode, or accepts unknown
    labels and non-buffer inputs."""
    code = r"""
const errOf = (f) => { try { return "ok " + f(); } catch (e) { return `${e.name}: ${e.message}`; } };
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join(" ");
const te = new TextEncoder();
console.log("encoding", te.encoding, "empty", te.encode().length, te.encode("").length);
for (const s of ["A", "é", "€", "𝄞", "héllo 🌍", "\u0000\u007f\u0080߿ࠀ￿"]) console.log(JSON.stringify(s), hex(te.encode(s)));
console.log("is Uint8Array", te.encode("x") instanceof Uint8Array, "coerces", hex(te.encode(123)), hex(te.encode(null)));
const td = new TextDecoder();
console.log("decoder", td.encoding, td.fatal, td.ignoreBOM);
console.log("roundtrip", td.decode(te.encode("héllo 🌍 €")));
console.log("ArrayBuffer", td.decode(new Uint8Array([0x68, 0x69]).buffer), "Int8Array", td.decode(new Int8Array([0x41, 0x42])), "subarray", td.decode(new Uint8Array([0x61, 0x62, 0x63, 0x64]).subarray(1, 3)));
console.log("undefined", JSON.stringify(td.decode()), "empty", JSON.stringify(td.decode(new Uint8Array(0))));
console.log("replacement", JSON.stringify(td.decode(new Uint8Array([0x61, 0xff, 0x62, 0xc3]))), JSON.stringify(td.decode(new Uint8Array([0xe2, 0x82]))));
console.log("BOM stripped", JSON.stringify(td.decode(new Uint8Array([0xef, 0xbb, 0xbf, 0x68, 0x69]))), "kept with ignoreBOM", JSON.stringify(new TextDecoder("utf-8", { ignoreBOM: true }).decode(new Uint8Array([0xef, 0xbb, 0xbf, 0x68]))).length);
const fatal = new TextDecoder("utf-8", { fatal: true });
console.log("fatal", fatal.fatal, errOf(() => fatal.decode(new Uint8Array([0x61, 0x80]))), errOf(() => fatal.decode(new Uint8Array([0xc3, 0xa9]))));
console.log("labels", ["utf-8", "UTF8", "unicode-1-1-utf-8"].map((l) => new TextDecoder(l).encoding).join(","));
console.log("unsupported", errOf(() => new TextDecoder("klingon")));
console.log("not a buffer", errOf(() => td.decode("abc")));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("text_encoder_decoder")
    assert (r.returncode, r.stderr) == (0, b"")


def test_atob_btoa(js, golden):
    """CATCHES: base64 with wrong padding, a decoder that rejects unpadded input or ASCII whitespace,
    or that accepts invalid characters, impossible lengths or misplaced '=', and btoa that
    encodes characters above U+00FF instead of throwing InvalidCharacterError."""
    code = r"""
const errOf = (f) => { try { return "ok " + JSON.stringify(f()); } catch (e) { return `${e.name}: ${e.message} ${e instanceof DOMException}`; } };
for (const s of ["", "f", "fo", "foo", "foob", "fooba", "foobar", "\u0000ÿ\u0080", "round-trip"]) console.log(JSON.stringify(s), btoa(s), JSON.stringify(atob(btoa(s))));
console.log("btoa coerces", btoa(12345), btoa(null), btoa(undefined));
console.log("atob forms", JSON.stringify([atob("Zm9v"), atob("Zm9vYg"), atob("Zm9vYg=="), atob(" Zm9v\nYmFy\t"), atob("")]));
console.log("btoa non-latin1", errOf(() => btoa("€")));
for (const bad of ["Zg=", "Zm9v!", "Z", "Zm9vY", "Zm9v====", "==", "Zm=9"]) console.log("atob", JSON.stringify(bad).padEnd(12), errOf(() => atob(bad)));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("atob_btoa")
    assert (r.returncode, r.stderr) == (0, b"")


def test_structured_clone_types(js, golden):
    """CATCHES: structuredClone that shares instead of copying nested objects, Maps, Sets, Dates,
    RegExps, Errors and buffers, loses cycles, shared references, holes or BigInts, keeps
    prototypes/getters of class instances, or fails to throw DataCloneError for functions,
    symbols and promises."""
    code = r"""
const errOf = (f) => { try { f(); return "no error"; } catch (e) { return `${e.name}: ${e.message} DOMException=${e instanceof DOMException}`; } };
const shared = { tag: "shared" };
const src = {
  num: -0.5, str: "s", bool: true, nul: null, undef: undefined, big: 12345678901234567890n,
  date: new Date(86400000), re: /ab+c/gi, map: new Map([[1, "one"], [{ k: 1 }, [2]]]), set: new Set(["a", 3]),
  err: new RangeError("bad range"), arr: [1, , 3], ab: new Uint8Array([1, 2, 3]).buffer, u16: new Uint16Array([65535, 1]),
  f64: new Float64Array([0.5]), nested: { deep: { deeper: [shared, shared] } },
};
src.self = src;
const c = structuredClone(src);
console.log("distinct", c !== src, c.nested !== src.nested, c.map !== src.map, "cycle", c.self === c, "shared kept", c.nested.deep.deeper[0] === c.nested.deep.deeper[1], c.nested.deep.deeper[0] !== shared);
console.log("prims", c.num, c.str, c.bool, c.nul, c.undef, "undef key kept", "undef" in c, typeof c.big, String(c.big));
console.log("date", c.date instanceof Date, c.date.toISOString(), c.date !== src.date);
console.log("regexp", c.re instanceof RegExp, String(c.re), c.re.flags, c.re !== src.re);
console.log("map", c.map instanceof Map, c.map.size, c.map.get(1), JSON.stringify([...c.map.keys()][1]), "set", c.set instanceof Set, [...c.set].join(","));
console.log("error", c.err instanceof RangeError, c.err.name, c.err.message, c.err !== src.err);
console.log("sparse array", c.arr.length, 1 in c.arr, c.arr[2]);
console.log("buffers", c.ab instanceof ArrayBuffer, c.ab !== src.ab, Array.from(new Uint8Array(c.ab)).join(","), c.u16 instanceof Uint16Array, Array.from(c.u16).join(","), c.f64[0]);
new Uint8Array(src.ab)[0] = 99; console.log("independent bytes", new Uint8Array(c.ab)[0]);
console.log("primitives", structuredClone(7), structuredClone("x"), structuredClone(null), structuredClone(undefined));
console.log("function", errOf(() => structuredClone({ f() {} })));
console.log("symbol", errOf(() => structuredClone(Symbol("s"))));
console.log("promise", errOf(() => structuredClone(Promise.resolve(1))));
console.log("class instance becomes plain", (() => { class P { constructor() { this.x = 1; } get y() { return 2; } } const o = structuredClone(new P()); return `${o.constructor === Object} ${o.x} ${o.y}`; })());
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("structured_clone_types")
    assert (r.returncode, r.stderr) == (0, b"")


def test_events_abort_signals_dom_exception(js, golden):
    """CATCHES: EventTarget that dispatches duplicate listeners, ignores once/handleEvent/signal
    options or stopImmediatePropagation, returns the wrong value from dispatchEvent after
    preventDefault, or AbortController/AbortSignal (abort, any, timeout, throwIfAborted,
    onabort) and DOMException with the wrong reasons, names or ordering."""
    code = r"""
const log = [];
const t = new EventTarget();
const h1 = (e) => log.push(`h1 ${e.type} target=${e.target === t} current=${e.currentTarget === t} phase=${e.eventPhase}`);
const obj = { handleEvent(e) { log.push(`handleEvent ${e.type} this=${this === obj}`); } };
t.addEventListener("ping", h1);
t.addEventListener("ping", h1); // duplicate ignored
t.addEventListener("ping", obj);
t.addEventListener("ping", () => log.push("once"), { once: true });
t.addEventListener("ping", null);
t.dispatchEvent(new Event("ping"));
t.dispatchEvent(new Event("ping"));
t.removeEventListener("ping", h1);
t.dispatchEvent(new Event("ping"));
console.log(log.splice(0).join("\n"));
const s = new EventTarget();
s.addEventListener("x", (e) => { log.push("first"); e.stopImmediatePropagation(); });
s.addEventListener("x", () => log.push("never"));
const ev = new Event("x", { cancelable: true, bubbles: true });
s.addEventListener("y", (e) => e.preventDefault());
console.log("dispatch returns", s.dispatchEvent(ev), s.dispatchEvent(new Event("y", { cancelable: true })), s.dispatchEvent(new Event("y")), log.splice(0).join(","));
console.log("event fields", ev.type, ev.bubbles, ev.cancelable, ev.composed, ev.defaultPrevented, ev.isTrusted, ev.currentTarget, typeof ev.timeStamp, Event.NONE, Event.CAPTURING_PHASE, Event.AT_TARGET, Event.BUBBLING_PHASE);
const ce = new CustomEvent("custom", { detail: { n: 1 } });
console.log("CustomEvent", ce instanceof Event, ce.type, JSON.stringify(ce.detail), new CustomEvent("c").detail);
try { new Event(); } catch (e) { console.log(e.name + ": " + e.message); }
try { s.dispatchEvent({ type: "x" }); } catch (e) { console.log(e.name + ": " + e.message); }
const ac = new AbortController();
const sig = ac.signal;
sig.onabort = (e) => log.push(`onabort ${e.type}`);
sig.addEventListener("abort", () => log.push(`listener aborted=${sig.aborted}`));
const t2 = new EventTarget();
t2.addEventListener("z", () => log.push("removed by signal?"), { signal: sig });
console.log("before", sig.aborted, sig.reason, (() => { try { sig.throwIfAborted(); return "no throw"; } catch { return "threw"; } })());
ac.abort();
ac.abort("second abort ignored");
t2.dispatchEvent(new Event("z"));
console.log("after", sig.aborted, sig.reason instanceof DOMException, sig.reason.name, sig.reason.message, log.splice(0).join(" | "));
try { sig.throwIfAborted(); } catch (e) { console.log("throwIfAborted", e === sig.reason); }
const custom = new AbortController(); custom.abort({ why: "custom" }); console.log("custom reason", JSON.stringify(custom.signal.reason));
const pre = AbortSignal.abort("pre"); console.log("AbortSignal.abort", pre.aborted, pre.reason);
try { new AbortSignal(); } catch (e) { console.log(e.name + ": " + e.message); }
const a1 = new AbortController(), a2 = new AbortController();
const any = AbortSignal.any([a1.signal, a2.signal]);
a2.abort("second wins"); a1.abort("first later");
console.log("any", any.aborted, any.reason, AbortSignal.any([AbortSignal.abort("already")]).reason);
const ts = AbortSignal.timeout(5);
await new Promise((r) => ts.addEventListener("abort", r));
console.log("timeout", ts.aborted, ts.reason.name, ts.reason.message, ts.reason instanceof DOMException);
const d = new DOMException("msg here", "NotFoundError");
console.log("DOMException", d instanceof Error, d.name, d.message, String(d), new DOMException().name, JSON.stringify(new DOMException().message));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("events_abort_signals_dom_exception")
    assert (r.returncode, r.stderr) == (0, b"")


def test_crypto_digest_and_random_values(js, golden):
    """CATCHES: a SHA-256 implementation that is wrong at block-padding boundaries (55/56/63/64/65
    bytes) or for views with offsets, digest() that accepts unsupported algorithms or non-buffer
    data, and getRandomValues/randomUUID that accept float arrays, ignore the 65536-byte quota,
    or return badly-shaped v4 UUIDs."""
    code = r"""
const hex = (buf) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
const enc = new TextEncoder();
const inputs = ["", "abc", "The quick brown fox jumps over the lazy dog", "a".repeat(55), "a".repeat(56), "a".repeat(63), "a".repeat(64), "a".repeat(65), "a".repeat(1000)];
for (const s of inputs) {
  const d = await crypto.subtle.digest("SHA-256", enc.encode(s));
  console.log(JSON.stringify(s.length > 20 ? s.slice(0, 12) + `...(${s.length})` : s).padEnd(22), d instanceof ArrayBuffer, d.byteLength, hex(d));
}
console.log("object algorithm + ArrayBuffer", hex(await crypto.subtle.digest({ name: "sha-256" }, enc.encode("abc").buffer)));
console.log("view offset", hex(await crypto.subtle.digest("SHA-256", new Uint8Array([0, 97, 98, 99, 0]).subarray(1, 4))));
console.log("Int32Array", hex(await crypto.subtle.digest("SHA-256", new Int32Array([1, 2]))));
for (const alg of ["SHA-1", "SHA-512", "MD5"]) await crypto.subtle.digest(alg, enc.encode("x")).catch((e) => console.log(alg, e.name, e.message, e instanceof DOMException));
await crypto.subtle.digest("SHA-256", "not bytes").catch((e) => console.log("bad data", e.name, e.message));
const u8 = new Uint8Array(16), back = crypto.getRandomValues(u8);
console.log("getRandomValues returns its argument", back === u8, u8.length);
for (const T of [Int8Array, Uint8ClampedArray, Int16Array, Uint32Array, BigInt64Array]) console.log(T.name, crypto.getRandomValues(new T(4)).length);
for (const bad of [new Float32Array(2), new Float64Array(1), [1, 2], new DataView(new ArrayBuffer(2))]) { try { crypto.getRandomValues(bad); } catch (e) { console.log("reject", bad.constructor.name, e.name, e.message); } }
try { crypto.getRandomValues(new Uint8Array(65537)); } catch (e) { console.log("quota", e.name, e.message); }
console.log("max quota ok", crypto.getRandomValues(new Uint8Array(65536)).length);
const ids = new Set(Array.from({ length: 20 }, () => crypto.randomUUID()));
console.log("randomUUID v4 shape", [...ids].every((id) => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id)), "distinct", ids.size);
console.log("classes", crypto instanceof Crypto, crypto.subtle instanceof SubtleCrypto, typeof CryptoKey);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("crypto_digest_and_random_values")
    assert (r.returncode, r.stderr) == (0, b"")


def test_compression_streams(js, golden):
    """CATCHES: Compression/DecompressionStream that cannot inflate standard zlib, raw-deflate or gzip
    data, produces output without the gzip/zlib headers or that does not round-trip, accepts
    garbage input or unknown formats, or mishandles empty input."""
    code = r"""
const fromHex = (h) => new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));
async function through(bytes, stream) {
  const rs = new ReadableStream({ start(c) { c.enqueue(bytes.subarray(0, 5)); c.enqueue(bytes.subarray(5)); c.close(); } });
  const out = [];
  for await (const chunk of rs.pipeThrough(stream)) out.push(...chunk);
  return new Uint8Array(out);
}
const vectors = {
  deflate: "78daf348cdc9c9d751f040a2141592f3730b8a528b8b33f3f3144a528b4b50a429550500f2d12836",
  "deflate-raw": "f348cdc9c9d751f040a2141592f3730b8a528b8b33f3f3144a528b4b50a429550500",
  gzip: "1f8b0800000000000203f348cdc9c9d751f040a2141592f3730b8a528b8b33f3f3144a528b4b50a4295505002b58fc2b72000000",
};
const dec = new TextDecoder();
for (const [fmt, hex] of Object.entries(vectors)) {
  const plain = await through(fromHex(hex), new DecompressionStream(fmt));
  console.log(fmt.padEnd(11), "inflates zlib-made vector:", plain.length, JSON.stringify(dec.decode(plain).slice(0, 38)));
}
const original = new TextEncoder().encode("lumen compression round trip ".repeat(40) + "✓");
for (const fmt of ["gzip", "deflate", "deflate-raw"]) {
  const packed = await through(original, new CompressionStream(fmt));
  const unpacked = await through(packed, new DecompressionStream(fmt));
  const magic = fmt === "gzip" ? `${packed[0].toString(16)} ${packed[1].toString(16)} method=${packed[2]}` : fmt === "deflate" ? `cmf=${packed[0].toString(16)} check=${((packed[0] << 8) | packed[1]) % 31 === 0}` : "raw";
  console.log(fmt.padEnd(11), "smaller:", packed.length < original.length / 4, "header:", magic, "roundtrip:", unpacked.length === original.length && dec.decode(unpacked) === dec.decode(original));
}
for (const fmt of ["gzip", "deflate"]) {
  try { await through(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]), new DecompressionStream(fmt)); console.log("no error"); } catch (e) { console.log(fmt, "garbage:", e.name, e.message); }
}
try { new CompressionStream("brotli"); } catch (e) { console.log(e.name + ": " + e.message); }
try { new DecompressionStream("zip"); } catch (e) { console.log(e.name + ": " + e.message); }
const empty = await through(new Uint8Array(0), new CompressionStream("gzip"));
console.log("empty input gzip roundtrip:", (await through(empty, new DecompressionStream("gzip"))).length);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("compression_streams")
    assert (r.returncode, r.stderr) == (0, b"")


def test_performance_navigator_self(js, golden):
    """CATCHES: a performance clock that is not monotonic or non-numeric, a missing timeOrigin/toJSON,
    or wrong platform identity globals (self, navigator.userAgent, Performance)."""
    code = r"""
const a = performance.now(), b = performance.now();
console.log("now", typeof a, a >= 0, b >= a, "timeOrigin", typeof performance.timeOrigin, performance.timeOrigin > 1e12, performance.timeOrigin === performance.timeOrigin);
console.log("toJSON keys", Object.keys(performance.toJSON()).join(","), performance instanceof Performance, "self", self === globalThis, "userAgent", navigator.userAgent);
while (performance.now() - b < 5);
console.log("monotonic advance >= 5ms", performance.now() - b >= 5);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("performance_navigator_self")
    assert (r.returncode, r.stderr) == (0, b"")
