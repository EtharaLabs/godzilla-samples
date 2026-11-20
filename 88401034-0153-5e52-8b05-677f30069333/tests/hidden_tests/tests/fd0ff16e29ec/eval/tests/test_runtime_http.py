"""Network-backed web APIs over loopback only: Lumen.serve (HTTP/1.1 server), fetch (HTTP client),
EventSource (server-sent events) and WebSocket (client + Lumen.upgradeWebSocket server side).

Every server binds 127.0.0.1 with port 0 (OS-chosen); ports never appear in the output (they are
masked as PORT where an error message would contain them). Raw HTTP/SSE peers are written with
node:net inside the same program; the WebSocket client wire tests use a scripted peer running in
a thread of the test process instead, because the reference client allows only ~100 ms for the
opening-handshake response and a peer living in the same (possibly busy) event loop could miss it.

Note: the reference runs blocking accepts/reads on a 4-thread pool, so each program keeps at most a
couple of Lumen.serve listeners alive at a time.
"""

import base64
import hashlib
import json
import re
import socket
import struct
import threading
import time

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

PRELUDE = r"""
const L = (...a) => console.log(...a);
const mask = (s, port) => (port ? String(s).replaceAll(String(port), "PORT") : String(s)).replace(/lumen\/[0-9][0-9A-Za-z.+-]*/g, "lumen/VER");
"""

# Raw TCP helpers (node:net) shared by the raw-server tests.
RAW_HELPERS = r"""
import net from "node:net";
const te = new TextEncoder(), td = new TextDecoder();
const cat = (...parts) => { const n = parts.reduce((a, p) => a + p.length, 0); const o = new Uint8Array(n); let k = 0; for (const p of parts) { o.set(p, k); k += p.length; } return o; };
const headEnd = (b) => { for (let i = 0; i + 3 < b.length; i++) if (b[i] === 13 && b[i + 1] === 10 && b[i + 2] === 13 && b[i + 3] === 10) return i; return -1; };
// Start a raw TCP server; onHead(sock, headText, rest) runs once the request head has arrived.
const rawServer = (onHead, onData) => new Promise((resolve) => {
  const srv = net.createServer((sock) => {
    let buf = new Uint8Array(0), seen = false;
    sock.on("error", () => {});
    sock.on("data", (d) => {
      buf = cat(buf, new Uint8Array(d));
      if (!seen) {
        const i = headEnd(buf);
        if (i < 0) return;
        seen = true;
        const head = td.decode(buf.subarray(0, i));
        buf = buf.slice(i + 4);
        onHead(sock, head, buf);
        if (onData) buf = onData(sock, buf) ?? buf;
      } else if (onData) {
        buf = onData(sock, buf) ?? buf;
      }
    });
  });
  srv.listen(0, "127.0.0.1", () => resolve({ srv, port: srv.address().port }));
});
"""

WS_HELPERS = r"""
const frame = (op, payload, { fin = true, rsv = 0 } = {}) => {
  const p = typeof payload === "string" ? te.encode(payload) : new Uint8Array(payload);
  const n = p.length, b0 = (fin ? 0x80 : 0) | rsv | op;
  return cat(new Uint8Array(n < 126 ? [b0, n] : [b0, 126, n >> 8, n & 255]), p);
};
// Parse complete frames out of buf (unmasking masked ones); returns the unconsumed rest.
const takeFrames = (buf, onFrame) => {
  for (;;) {
    if (buf.length < 2) return buf;
    let len = buf[1] & 0x7f, off = 2;
    if (len === 126) { if (buf.length < 4) return buf; len = (buf[2] << 8) | buf[3]; off = 4; }
    const masked = (buf[1] & 0x80) !== 0;
    const total = off + (masked ? 4 : 0) + len;
    if (buf.length < total) return buf;
    const payload = buf.slice(off + (masked ? 4 : 0), total);
    if (masked) for (let i = 0; i < payload.length; i++) payload[i] ^= buf[off + (i % 4)];
    onFrame({ fin: (buf[0] & 0x80) !== 0, op: buf[0] & 0x0f, masked, payload });
    buf = buf.slice(total);
  }
};
const describeFrame = (f) => `op=${f.op} masked=${f.masked} ` + (f.op === 8 ? (f.payload.length >= 2 ? ((f.payload[0] << 8) | f.payload[1]) + ":" + JSON.stringify(td.decode(f.payload.subarray(2))) : "(no code)") : JSON.stringify(td.decode(f.payload)));
"""


def _run_prog(run, workdir, src, tier=(), raw=False, ws=False):
    prog = (RAW_HELPERS if raw or ws else "") + (WS_HELPERS if ws else "") + PRELUDE + src
    write_files(workdir, {"t.mjs": prog})
    return run([*tier, "t.mjs"], timeout=30)


def _check(r, name, stderr=b""):
    assert (r.returncode, r.stderr) == (0, stderr)
    assert r.stdout == golden(__file__, name)


# ---------------------------------------------------------------------------------------------
# Lumen.serve + fetch
# ---------------------------------------------------------------------------------------------

PROG_SERVE_FETCH = r"""
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0, onListen(info) { L("listening", info.hostname, typeof info.port); } }, async (req, info) => {
  const u = new URL(req.url);
  switch (u.pathname) {
    case "/echo": {
      const body = req.method === "GET" || req.method === "HEAD" ? null : await req.text();
      return Response.json({ method: req.method, path: u.pathname, q: u.search, ct: req.headers.get("content-type"), xh: req.headers.get("x-h"), cl: req.headers.get("content-length"), body,
        ua: mask(req.headers.get("user-agent"), 0), hostOk: req.headers.get("host") === u.host, conn: req.headers.get("connection"), remote: info.remoteAddr.hostname }, { headers: { "x-multi": "a" } });
    }
    case "/redirect": return new Response(null, { status: 302, headers: { location: "/echo?from=302" } });
    case "/r303": return new Response(null, { status: 303, headers: { location: "/echo?from=303" } });
    case "/r307": return new Response(null, { status: 307, headers: { location: "echo?from=307" } });
    case "/r308": return new Response(null, { status: 308, headers: { location: `http://${u.host}/echo?from=308` } });
    case "/loop": return new Response(null, { status: 307, headers: { location: "/loop" } });
    case "/noloc": return new Response("no location", { status: 301 });
    case "/custom": return new Response("c", { status: 299, statusText: "Custom Text", headers: { Server: "mine", "Content-Length": "1", Connection: "keep-alive", "Transfer-Encoding": "chunked" } });
    case "/throw": throw new Error("handler exploded");
    case "/notresp": return "string";
    case "/empty": return new Response(null, { status: 204 });
    case "/bin": return new Response(new Uint8Array([0, 1, 254, 255]));
    case "/form": { const fd = await req.formData(); return Response.json([...fd].map(([k, v]) => [k, typeof v === "string" ? v : v.name + ":" + v.size + ":" + v.type])); }
    case "/consumed": { const r = new Response("once"); await r.text(); return r; }
    default: return new Response("not found", { status: 404 });
  }
});
const base = `http://127.0.0.1:${server.port}`;
const show = async (label, p) => { try { const r = await p; L(label, r.status, JSON.stringify(r.statusText), r.redirected, mask(r.url, server.port), JSON.stringify(await r.text())); } catch (e) { L(label, e.name, mask(e.message, server.port)); } };
let r = await fetch(base + "/echo?a=1", { method: "POST", body: "payload", headers: { "X-H": "hv" } });
L("headers", r.status, r.ok, r.url === base + "/echo?a=1", r.headers.get("x-multi"), r.headers.get("content-type"), r.headers.get("content-length"), r.headers.get("connection"), mask(r.headers.get("server"), 0));
L("echo", await r.text());
await show("get", fetch(base + "/echo"));
await show("302 POST->GET", fetch(base + "/redirect", { method: "POST", body: "dropped" }));
await show("303 PUT->GET", fetch(base + "/r303", { method: "PUT", body: "x" }));
await show("307 keeps", fetch(base + "/r307", { method: "POST", body: "kept" }));
await show("308 keeps", fetch(base + "/r308", { method: "PATCH", body: "kept8" }));
await show("301 no location", fetch(base + "/noloc"));
await show("redirect loop", fetch(base + "/loop"));
await show("custom status", fetch(base + "/custom"));
r = await fetch(base + "/custom"); L("custom headers", JSON.stringify([...r.headers]));
await show("handler throws", fetch(base + "/throw"));
await show("not a Response", fetch(base + "/notresp"));
await show("used body", fetch(base + "/consumed"));
await show("204", fetch(base + "/empty"));
await show("HEAD", fetch(base + "/echo", { method: "HEAD" }));
await show("404", fetch(base + "/nope"));
r = await fetch(base + "/bin"); L("binary", (await r.bytes()).join(), r.headers.get("content-type"));
r = await fetch(new Request(base + "/echo", { method: "PATCH", body: new URLSearchParams("k=v w") })); L("urlencoded", JSON.stringify(await r.json()));
r = await fetch(base + "/echo", { method: "PUT", body: new Uint8Array([104, 105]) }); L("bytes body", JSON.stringify(await r.json()));
const fd = new FormData(); fd.append("name", "lumen"); fd.append("f", new File(["12345"], "five.bin", { type: "app/bin" }));
r = await fetch(base + "/form", { method: "POST", body: fd }); L("multipart", await r.text());
r = await fetch(base + "/echo", { method: "POST", body: new ReadableStream({ start(c) { c.enqueue("str"); c.enqueue(new Uint8Array([101, 97, 109])); c.close(); } }) }); L("stream body", (await r.json()).body);
const ac = new AbortController(); ac.abort();
await show("pre-aborted", fetch(base + "/echo", { signal: ac.signal }));
await show("custom reason", fetch(base + "/echo", { signal: AbortSignal.abort(new RangeError("mine")) }));
await show("data url", fetch("data:text/plain,hi"));
await show("ftp", fetch("ftp://x/"));
await show("invalid url", fetch("nope"));
await show("GET body", fetch(base + "/echo", { body: "x" }));
await server.shutdown();
L("shutdown done");
"""

SERVE_FETCH_STDERR = b"Error: handler exploded\nTypeError: serve handler did not return a Response\n"


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_serve_and_fetch_roundtrip(run, workdir, tier):
    """CATCHES: fetch/Lumen.serve bugs: request bodies/headers not delivered, wrong redirect method rewriting
    (302/303 -> GET, 307/308 preserve), missing redirect limit, handler errors not mapped to 500 (and logged),
    statusText/redirected/url fields, or abort/unsupported-scheme rejections differing from the reference."""
    _check(_run_prog(run, workdir, PROG_SERVE_FETCH, tier), "serve_fetch", SERVE_FETCH_STDERR)


PROG_REASON_PHRASES = r"""
const statuses = [200, 201, 202, 203, 204, 206, 301, 302, 303, 304, 307, 308, 400, 401, 403, 404, 405, 409, 410, 418, 422, 429, 500, 501, 502, 503, 504, 599];
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, (req) => {
  const st = Number(new URL(req.url).searchParams.get("s"));
  return new Response(st === 204 || st === 304 ? null : "b", { status: st });
});
const out = [];
for (const s of statuses) {
  const r = await fetch(`http://127.0.0.1:${server.port}/?s=${s}`);
  out.push(`${r.status}:${JSON.stringify(r.statusText)}:${r.ok ? "ok" : "-"}:${(await r.text()).length}`);
}
L(out.join("\n"));
await server.shutdown();
"""


def test_serve_default_reason_phrases(run, workdir):
    """CATCHES: servers that send a different default reason phrase (or none) for a status code, or clients
    that misparse the status line / mishandle bodiless 3xx responses without a Location header."""
    _check(_run_prog(run, workdir, PROG_REASON_PHRASES), "reason_phrases")


PROG_SERVE_OPTIONS = r"""
const get = async (s, p = "/") => { const r = await fetch(`http://127.0.0.1:${s.port}${p}`); return `${r.status} ${await r.text()}`; };
const one = async (label, s, paths = ["/"]) => { for (const p of paths) L(label, await get(s, p)); await s.shutdown(); };
await one("fn+opts", Lumen.serve((req) => new Response("fn-only"), { hostname: "127.0.0.1", port: 0, onListen: (i) => L("onListen", Object.keys(i).join(), i.hostname, typeof i.port) }));
await one("deno object", Lumen.serve({ hostname: "127.0.0.1", port: 0, fetch: (req) => new Response("deno-object"), onError: () => new Response("never") }));
const app = { fetch(req) { if (new URL(req.url).pathname === "/boom") throw new Error("app boom"); return new Response("app:" + (this === app)); }, onError() { return new Response("app onError must be ignored"); }, hostname: "127.0.0.1", port: 0 };
await one("app", Lumen.serve(app), ["/", "/boom"]);
await one("onError", Lumen.serve((req) => { throw new RangeError("handled"); }, { hostname: "127.0.0.1", port: 0, onError: (err) => new Response(`onError saw ${err.name}: ${err.message}`, { status: 503 }) }));
await one("onError throws", Lumen.serve((req) => { throw new Error("x"); }, { hostname: "127.0.0.1", port: 0, onError: () => { throw new Error("onError itself failed"); } }));
await one("async handler", Lumen.serve({ hostname: "127.0.0.1", port: 0 }, async (req, info) => { await new Promise((r) => setTimeout(r, 1)); return Response.json({ m: req.method, remote: info.remoteAddr.hostname, transport: info.remoteAddr.transport, portType: typeof info.remoteAddr.port }); }));
const s1 = Lumen.serve(() => new Response("x"), { hostname: "127.0.0.1", port: 0 });
L("server object", Object.keys(s1).join(), s1.hostname, typeof s1.port, s1.ref(), s1.unref(), s1.finished instanceof Promise);
for (const bad of [[], [42], ["str"], [{}], [null]]) { try { Lumen.serve(...bad); L("no error"); } catch (e) { L(e.name, e.message); } }
try { Lumen.serve(() => new Response(""), { hostname: "127.0.0.1", port: s1.port }); L("bound twice?"); } catch (e) { L("in use:", e.name, mask(e.message, s1.port)); }
for (const port of [70000, -1]) { try { Lumen.serve(() => new Response(""), { hostname: "127.0.0.1", port }); } catch (e) { L(e.name, e.message); } }
const port1 = s1.port;
await s1.shutdown();
L("shutdown twice", await s1.shutdown());
try { await fetch(`http://127.0.0.1:${port1}/`); } catch (e) { L("after shutdown:", e.name, mask(e.message, port1)); }
const ac = new AbortController();
const s7 = Lumen.serve(() => new Response("signal"), { hostname: "127.0.0.1", port: 0, signal: ac.signal });
L("signal server", await get(s7));
ac.abort();
await s7.finished; L("finished after abort");
const s8 = Lumen.serve(() => new Response(""), { hostname: "127.0.0.1", port: 0, signal: AbortSignal.abort() });
await s8.finished; L("pre-aborted signal finished");
"""


def test_serve_call_forms_options_and_lifecycle(run, workdir):
    """CATCHES: Lumen.serve argument-form handling (handler+options, options+handler, Deno object form, app
    objects whose onError must be ignored), onError fallbacks, bind errors, AbortSignal-driven shutdown and
    the finished promise behaving differently from the reference."""
    _check(_run_prog(run, workdir, PROG_SERVE_OPTIONS), "serve_options", b"Error: app boom\n")


PROG_SERVE_RAW = r"""
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, async (req) => {
  const body = req.method === "GET" || req.method === "HEAD" ? "" : await req.text();
  const hdrs = [...req.headers].map(([k, v]) => `${k}=${v}`).join(";");
  return new Response(`${req.method} ${mask(req.url, server.port)} body=${JSON.stringify(body)} headers=${mask(hdrs, server.port)}`,
    { headers: { "X-Custom": "v", Connection: "keep-alive", "Transfer-Encoding": "chunked" } });
});
const raw = (data) => new Promise((resolve) => {
  const s = net.connect(server.port, "127.0.0.1", () => s.write(data));
  let buf = "";
  s.on("data", (d) => (buf += d.toString()));
  s.on("end", () => resolve(mask(buf, server.port)));
  s.on("error", (e) => resolve("ERR " + e.message));
});
const cases = [
  "POST /c HTTP/1.1\r\nHost: h.test\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n2;ext=1\r\nde\r\n0\r\nTrailer: t\r\n\r\n",
  "get rel/path HTTP/1.1\r\nHost: h.test\r\n\r\n",
  "GET http://abs.test/x?q HTTP/1.1\r\nHost: ignored.test\r\n\r\n",
  "PUT /nohost HTTP/1.1\r\nContent-Length: 4\r\nX-Dup: 1\r\nX-Dup: 2\r\nNoColonLine\r\n\r\nWXYZ",
  "DELETE /nolen HTTP/1.1\r\nHost: h\r\n\r\nignored-without-length",
  "OPTIONS * HTTP/1.1\r\nHost: h\r\n\r\n",
  "POST /chunkbad HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n",
  "\r\n",
  "GET /lf-only HTTP/1.1\nHost: lf.test\n\n",
  "GET /big HTTP/1.1\r\nX-Big: " + "a".repeat(70000) + "\r\n\r\n",
];
for (const c of cases) L(JSON.stringify(c.slice(0, 24)), "=>", JSON.stringify(await raw(c)));
// Half-close right after sending: an empty request, and a body shorter than its Content-Length.
const halfClose = (data) => new Promise((resolve) => {
  const s = net.connect(server.port, "127.0.0.1", () => { if (data) s.write(data); s.end(); });
  let buf = "";
  s.on("data", (d) => (buf += d.toString()));
  s.on("close", () => resolve(mask(buf, server.port)));
  s.on("error", () => {});
});
L("empty request =>", JSON.stringify(await halfClose("")));
L("short body =>", JSON.stringify(await halfClose("POST /short HTTP/1.1\r\nHost: h\r\nContent-Length: 10\r\n\r\nabc")));
L("eof inside head =>", JSON.stringify(await halfClose("GET /eof-in-head HTTP/1.1\r\nHost: h\r\n")));
await server.shutdown();
"""


def test_serve_raw_http_wire_format(run, workdir):
    """CATCHES: HTTP/1.1 server parsing differences (chunked request bodies with extensions/trailers,
    origin/absolute/relative request targets, missing Host, lowercase methods, LF-only lines) and response
    serialization (framing headers owned by the server, Content-Length, Server, Connection: close, 400s)."""
    _check(_run_prog(run, workdir, PROG_SERVE_RAW, raw=True), "serve_raw")


PROG_FETCH_RAW = r"""
const responses = {
  "/chunked": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nX-T: 1\r\n\r\n4\r\nWiki\r\n5;ext=1\r\npedia\r\nE\r\n in\r\n\r\nchunks.\r\n0\r\nTrailer: x\r\n\r\n",
  "/eof": "HTTP/1.1 200 Fine Thanks\r\nContent-Type: text/plain\r\n\r\nread until the server closes",
  "/len": "HTTP/1.1 201 Created\r\nContent-Length: 5\r\nX-Spaced:    padded value   \r\nX-Dup: a\r\nX-Dup: b\r\n\r\nhelloEXTRA",
  "/badstatus": "HTTP/1.1 abc\r\n\r\n",
  "/badchunk": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nxyz\r\n",
  "/short": "HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nabc",
  "/304": "HTTP/1.1 304 Not Modified\r\nContent-Length: 99\r\n\r\n",
  "/head": "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n",
  "/moved": "HTTP/1.1 301 Moved\r\nLocation: ../final/dest?x=1\r\n\r\n",
  "/final/dest": "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndone",
  "/nostatus-text": "HTTP/1.1 202\r\nContent-Length: 0\r\n\r\n",
  "/lowercase": "http/1.0 200 ok\r\ncontent-length: 2\r\n\r\nhi",
  "/silent": "",
  "/redirect-no-location": "HTTP/1.1 302 Found\r\nContent-Length: 3\r\n\r\nabc",
};
const requests = [];
const { srv, port } = await rawServer((sock, head) => {
  const path = head.split(" ")[1].split("?")[0];
  requests.push(mask(head, port));
  sock.end(responses[path] ?? "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n");
});
const base = `http://127.0.0.1:${port}`;
const show = async (label, p) => {
  try { const r = await p; L(label, r.status, JSON.stringify(r.statusText), r.redirected, mask(r.url, port), JSON.stringify([...r.headers]), JSON.stringify(await r.text())); }
  catch (e) { L(label, e.name, JSON.stringify(mask(e.message, port))); }
};
await show("chunked", fetch(base + "/chunked"));
await show("eof", fetch(base + "/eof"));
await show("content-length", fetch(base + "/len"));
await show("bad status", fetch(base + "/badstatus"));
await show("bad chunk", fetch(base + "/badchunk"));
await show("short body", fetch(base + "/short"));
await show("304", fetch(base + "/304"));
await show("HEAD", fetch(base + "/head", { method: "HEAD" }));
await show("relative redirect", fetch(base + "/moved"));
await show("no reason", fetch(base + "/nostatus-text"));
await show("lowercase", fetch(base + "/lowercase"));
await show("silent", fetch(base + "/silent"));
await show("302 without location", fetch(base + "/redirect-no-location"));
await show("post", fetch(base + "/len?q=1", { method: "POST", body: "abc", headers: { "X-B": "1", "x-a": "2", "User-Agent": "custom-ua", Host: "ignored", Connection: "keep-alive" } }));
L("request heads:");
for (const h of requests) L("  " + JSON.stringify(h));
srv.close();
"""


def test_fetch_against_raw_http_server(run, workdir):
    """CATCHES: fetch HTTP/1.1 client bugs: chunked decoding (extensions, trailers), read-to-EOF bodies,
    Content-Length truncation, bodiless 304/HEAD, relative Location resolution, malformed status line or
    chunk errors, and the exact request head (Host, Connection: close, default User-Agent, Content-Length)."""
    _check(_run_prog(run, workdir, PROG_FETCH_RAW, raw=True), "fetch_raw")


PROG_FETCH_ABORT_INFLIGHT = r"""
let release;
const gate = new Promise((r) => (release = r));
const ac = new AbortController();
const { srv, port } = await rawServer(async (sock, head) => {
  L("server got request", head.split("\r\n")[0]);
  ac.abort(new DOMException("stopped by test", "AbortError")); // abort while the request is in flight
  await gate;
  sock.end("HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nlate");
});
const p = fetch(`http://127.0.0.1:${port}/slow`, { signal: ac.signal });
try { await p; L("resolved?"); } catch (e) { L("rejected", e.name, e.message); }
release();
// A later request on a fresh signal still works and is unaffected by the earlier abort.
const ok = await fetch(`http://127.0.0.1:${port}/again`);
L("second", ok.status, await ok.text());
srv.close();
"""


def test_fetch_abort_while_in_flight(run, workdir):
    """CATCHES: fetch implementations that ignore an AbortSignal fired after the request was sent (or
    resolve with the late response), or that use a generic reason instead of the signal's reason."""
    _check(_run_prog(run, workdir, PROG_FETCH_ABORT_INFLIGHT, raw=True), "fetch_abort")


# ---------------------------------------------------------------------------------------------
# EventSource
# ---------------------------------------------------------------------------------------------

PROG_EVENTSOURCE = r"""
let hits = 0;
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, (req) => {
  const u = new URL(req.url);
  if (u.pathname === "/events") {
    hits++;
    if (hits === 1) {
      return new Response(
        ": comment line\n" +
        "retry: 20\n" +
        "data: first\n\n" +
        "event: custom\r\ndata: line1\r\ndata:line2\r\nid: 7\r\n\r\n" +
        "id: 8\n\n" +
        "data:  two spaces\rignored-field: x\r\r" +
        "field-no-colon\ndata\n\n" +
        "retry: soon\nid: 9\nevent: \ndata: ünïcode ✓\n\n" +
        "data: partial-never-dispatched",
        { headers: { "content-type": "Text/Event-Stream; charset=utf-8" } });
    }
    return new Response(`data: reconnected lei=${req.headers.get("last-event-id")} accept=${req.headers.get("accept")} cache=${req.headers.get("cache-control")}\n\n`, { headers: { "content-type": "text/event-stream" } });
  }
  if (u.pathname === "/html") return new Response("<p>", { headers: { "content-type": "text/html" } });
  if (u.pathname === "/204") return new Response(null, { status: 204 });
  if (u.pathname === "/500") return new Response("err", { status: 500 });
  if (u.pathname === "/redir") return new Response(null, { status: 302, headers: { location: "/target" } });
  if (u.pathname === "/target") return new Response("data: via redirect\n\n", { headers: { "content-type": "text/event-stream" } });
  if (u.pathname === "/noloc") return new Response(null, { status: 307 });
  return new Response("nf", { status: 404 });
});
const base = `http://127.0.0.1:${server.port}`;
const es = new EventSource(base + "/events", { withCredentials: 1 });
L("init", es.readyState, es.url === base + "/events", es.withCredentials, EventSource.CONNECTING, EventSource.OPEN, EventSource.CLOSED, es.CLOSED, es.onmessage, es instanceof EventTarget);
await new Promise((resolve) => {
  es.onopen = (e) => L("open", es.readyState, e.type);
  es.onmessage = (e) => { L("message", JSON.stringify(e.data), JSON.stringify(e.lastEventId), e.origin === base, e.type, e instanceof MessageEvent); if (e.data.startsWith("reconnected")) { es.close(); resolve(); } };
  es.addEventListener("custom", (e) => L("custom", JSON.stringify(e.data), e.lastEventId));
  es.addEventListener("message", (e) => L("  (listener saw it too)"));
  es.onerror = (e) => L("error, readyState", es.readyState, e.type);
});
L("closed state", es.readyState);
const once = (path, closeOnError = true) => new Promise((resolve) => {
  const s = new EventSource(base + path);
  s.onerror = () => { L(path, "error readyState", s.readyState); if (closeOnError) s.close(); resolve(); };
  s.onopen = () => L(path, "opened");
  s.onmessage = (e) => { L(path, "msg", e.data); s.close(); resolve(); };
});
for (const p of ["/html", "/204", "/500", "/noloc", "/redir"]) await once(p);
const early = new EventSource(base + "/events"); early.onopen = () => L("must not open"); early.close(); L("closed before open", early.readyState);
for (const bad of [["ftp://x/"], ["bad url"], [], ["ws://h/"]]) { try { new EventSource(...bad); L("no error"); } catch (e) { L(e.name, e.message); } }
await new Promise((r) => setTimeout(r, 20));
await server.shutdown();
L("done");
"""


def test_eventsource_parsing_dispatch_and_reconnect(run, workdir):
    """CATCHES: SSE parser bugs (comments, CR/LF/CRLF line ends, single leading space, multi-line data,
    event/id/retry fields, unterminated trailing events), Last-Event-ID on reconnect, fatal handling of
    wrong content types/204/HTTP errors, redirects, and constructor validation."""
    _check(_run_prog(run, workdir, PROG_EVENTSOURCE), "eventsource")


PROG_EVENTSOURCE_RAW = r"""
const bodies = {
  "/a": "\ufeffdata: after bom\n\nid: x\u0000y\ndata: nul id ignored\n\ndata: a\ndata:\ndata: c\n\nevent: named\nid\ndata: id reset\n\n:\n\ndata\n\n",
};
const heads = [];
const { srv, port } = await rawServer((sock, head) => {
  heads.push(mask(head, port));
  const path = head.split(" ")[1].split("?")[0];
  if (path === "/a") sock.end("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n" + bodies["/a"]);
  else if (path === "/again") sock.end("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream;charset=UTF-8\r\n\r\ndata: second connection\n\n");
  else sock.end("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n");
});
const base = `http://127.0.0.1:${port}`;
await new Promise((resolve) => {
  const es = new EventSource(base + "/a?q=1");
  const seen = [];
  const log = (e) => seen.push(`${e.type}:${JSON.stringify(e.data)}:${JSON.stringify(e.lastEventId)}`);
  es.onmessage = log;
  es.addEventListener("named", log);
  es.onerror = () => { L(seen.join("\n")); L("error after stream end, readyState", es.readyState); es.close(); resolve(); };
});
await new Promise((resolve) => {
  const es = new EventSource(base + "/again");
  es.onmessage = (e) => { L("second", e.data, JSON.stringify(e.lastEventId)); es.close(); resolve(); };
});
L("request heads:");
for (const h of heads) L("  " + JSON.stringify(h));
srv.close();
"""


def test_eventsource_raw_stream_edge_cases(run, workdir):
    """CATCHES: SSE clients that strip a leading BOM differently, accept ids containing NUL, mishandle empty
    data lines / bare field names / id resets, or send a different request head (Accept, Cache-Control,
    Connection, Last-Event-ID) than the reference."""
    _check(_run_prog(run, workdir, PROG_EVENTSOURCE_RAW, raw=True), "eventsource_raw")


# ---------------------------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------------------------

PROG_WS_LUMEN_SERVER = r"""
let allReceived;
const received = new Promise((r) => (allReceived = r));
// Server-side events are recorded per connection attempt (see the retry below) and printed at the end.
const slog = {}, counts = {};
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, (req) => {
  const u = new URL(req.url);
  if (u.pathname === "/plain") {
    L("server: upgrade on non-websocket request ->", Lumen.upgradeWebSocket(req));
    return new Response("plain");
  }
  const attempt = u.searchParams.get("attempt");
  const log = (...a) => (slog[attempt] ??= []).push(a.join(" "));
  const ws = Lumen.upgradeWebSocket(req, { protocol: u.searchParams.get("proto") || "", headers: [["X-Extra", "1"]] });
  log("upgraded", u.pathname, typeof ws.send, typeof ws.close, ws.remoteAddress);
  try { Lumen.upgradeWebSocket(req); } catch (e) { log("double upgrade", e.name, e.message); }
  ws.onmessage = (data, isBinary) => {
    log("got", isBinary ? "binary:" + Array.from(data).join(",") + ":" + data.constructor.name : data.length > 50 ? `text of length ${data.length} (${data[0]})` : "text:" + JSON.stringify(data));
    counts[attempt] = (counts[attempt] ?? 0) + 1;
    if (counts[attempt] === 8) allReceived();
  };
  ws.onclose = (code, reason, clean) => log("onclose", code, JSON.stringify(reason), clean);
  return new Response("ignored after upgrade");
});
const base = `ws://127.0.0.1:${server.port}`;
try { Lumen.upgradeWebSocket(new Request("http://x/")); } catch (e) { L(e.name, e.message); }
try { Lumen.upgradeWebSocket(null); } catch (e) { L(e.name, e.message); }
L("plain fetch", await (await fetch(`http://127.0.0.1:${server.port}/plain`)).text());
// The reference client gives up on the opening handshake after a short read timeout, so retry the
// connection (with a fresh attempt id) if it never opened.
const connect = (n) => new Promise((resolve) => {
  const ws = new WebSocket(`${base}/sock?proto=chat&attempt=${n}`, ["chat", "superchat"]);
  if (n === 1) {
    L("connecting", ws.readyState, ws.url === base + "/sock?proto=chat&attempt=1", ws.binaryType, JSON.stringify(ws.protocol), JSON.stringify(ws.extensions), ws.bufferedAmount);
    L("constants", WebSocket.CONNECTING, WebSocket.OPEN, WebSocket.CLOSING, WebSocket.CLOSED, ws.OPEN, ws.CLOSED);
    try { ws.send("too early"); } catch (e) { L(e.name, e.message); }
  }
  ws.onopen = (e) => { ws.onclose = null; L("client open", e.type, ws.readyState, ws.protocol); resolve([ws, n]); };
  ws.onclose = () => (n < 5 ? connect(n + 1).then(resolve) : resolve([null, n]));
});
const [ws, attempt] = await connect(1);
await new Promise((resolve) => {
  ws.onmessage = (e) => L("client unexpected message", e.data);
  ws.addEventListener("close", (e) => { L("client close", e.code, JSON.stringify(e.reason), e.wasClean, ws.readyState, e instanceof CloseEvent); resolve(); });
  ws.onerror = () => L("client error");
  ws.send("hello");
  ws.send(new Uint8Array([1, 2, 3]));
  ws.send(new Uint16Array([0x0201]).buffer);
  ws.send(new DataView(new Uint8Array([9, 8, 7, 6]).buffer, 1, 2));
  ws.send(42);
  ws.send(new Blob(["blobdata"]));
  ws.send("m".repeat(200));
  ws.send("L".repeat(70000));
  received.then(() => { ws.close(4001, "client bye"); L("after close()", ws.readyState); ws.close(); ws.send("ignored while closing"); });
});
ws.send("after close ignored");
try { ws.binaryType = "text"; } catch (e) { L(e.name, e.message); }
ws.binaryType = "arraybuffer"; L("binaryType", ws.binaryType);
for (let i = 0; i < 300 && !(slog[attempt] ?? []).some((l) => l.startsWith("onclose")); i++) await new Promise((r) => setTimeout(r, 10));
L("server saw:");
for (const line of slog[attempt]) L("  " + line);
await server.shutdown();
L("done");
"""


def test_websocket_client_to_lumen_upgrade_server(run, workdir):
    """CATCHES: WebSocket client/server bugs: subprotocol negotiation, send() of strings/views/ArrayBuffers/
    Blobs not arriving intact at a Lumen.upgradeWebSocket handler, readyState transitions, close code/reason
    propagation in both directions, and upgradeWebSocket misuse errors."""
    _check(_run_prog(run, workdir, PROG_WS_LUMEN_SERVER), "ws_lumen_server")


# ---------------------------------------------------------------------------------------------
# A scripted WebSocket peer that runs in the test process (a Python thread), for client-side wire
# tests. The reference client reads the opening-handshake response with a ~100 ms per-read timeout,
# so a peer written in JS inside the same busy event loop would make these tests timing-sensitive.
# ---------------------------------------------------------------------------------------------

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_frame(op, payload=b"", fin=True, rsv=0):
    if isinstance(payload, str):
        payload = payload.encode()
    b0 = (0x80 if fin else 0) | rsv | op
    n = len(payload)
    head = bytes([b0, n]) if n < 126 else bytes([b0, 126]) + struct.pack(">H", n)
    return head + payload


def _ws_close(code, reason=""):
    return _ws_frame(8, struct.pack(">H", code) + reason.encode())


def _ws_read_frames(conn, buf):
    """Yield (op, masked, payload) for each client frame until EOF."""
    while True:
        while True:
            if len(buf) >= 2:
                n = buf[1] & 0x7F
                off = 2
                if n == 126 and len(buf) >= 4:
                    n = struct.unpack(">H", buf[2:4])[0]
                    off = 4
                masked = bool(buf[1] & 0x80)
                total = off + (4 if masked else 0) + n
                if (buf[1] & 0x7F) != 126 or len(buf) >= 4:
                    if len(buf) >= total:
                        payload = buf[off + (4 if masked else 0):total]
                        if masked:
                            m = buf[off:off + 4]
                            payload = bytes(c ^ m[i % 4] for i, c in enumerate(payload))
                        yield buf[0] & 0x0F, masked, payload
                        buf = buf[total:]
                        continue
            break
        chunk = conn.recv(65536)
        if not chunk:
            return
        buf += chunk


def _describe(op, masked, payload):
    if op == 8:
        body = f"{struct.unpack('>H', payload[:2])[0]}:{json.dumps(payload[2:].decode(), ensure_ascii=False)}" if len(payload) >= 2 else "(no code)"
    else:
        body = json.dumps(payload.decode(errors="replace"), ensure_ascii=False)
    return f"op={op} masked={str(masked).lower()} {body}"


RAW_SCRIPT = (_ws_frame(1, "hello") + _ws_frame(2, b"\x01\x02\x03") + _ws_frame(1, "frag", fin=False)
              + _ws_frame(0, "men", fin=False) + _ws_frame(0, "ted ✓") + _ws_frame(9, "p1") + _ws_frame(10, "unsolicited")
              + _ws_frame(1, "x" * 300) + _ws_frame(2, b"", fin=False) + _ws_frame(0, b"\x04\x05") + _ws_frame(1, "")
              + _ws_frame(1, "bye"))

# Frames sent right after a successful handshake, per scenario path.
AFTER_OPEN = {
    "/badop": _ws_frame(3, "x"),
    "/badutf8": _ws_frame(1, b"a\xff"),
    "/rsv": _ws_frame(1, "x", rsv=0x40),
    "/ctrlfrag": _ws_frame(9, "p", fin=False),
    "/cont": _ws_frame(0, "x"),
    "/interleave": _ws_frame(1, "a", fin=False) + _ws_frame(2, "b"),
    "/toobig": bytes([0x82, 127, 0, 0, 0, 1, 0, 0, 0, 0]),
    "/badreason": _ws_frame(8, b"\x03\xe8\xff"),
    "/nocode": _ws_frame(8, b""),
    "/closed-early": _ws_frame(8, b"\x0f\xa1"),
    "/live": _ws_frame(8, b""),
}


class ScriptedWsPeer:
    """Accepts loopback connections and plays the scenario named by the request path."""

    def __init__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(32)
        self.port = self.listener.getsockname()[1]
        self.lock = threading.Lock()
        self.log = []  # (path, line) for frames received from the client
        self.request_heads = {}
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def close(self):
        self.listener.close()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _record(self, path, line):
        with self.lock:
            self.log.append((path, line))

    def _serve(self, conn):
        try:
            conn.settimeout(15)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            head, rest = data.split(b"\r\n\r\n", 1)
            head = head.decode()
            path = head.split(" ")[1].split("?")[0]
            key = re.search(r"(?im)^sec-websocket-key: *(.*?)\s*$", head).group(1)
            accept = base64.b64encode(hashlib.sha1(key.encode() + WS_GUID).digest()).decode()
            ok = f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n"
            if path == "/raw":
                with self.lock:
                    self.request_heads.setdefault(path, " | ".join(
                        line for line in head.split("\r\n") if not re.match(r"(?i)(host|sec-websocket-key):", line)))
                proto = re.search(r"(?im)^sec-websocket-protocol: *(.*?)\s*$", head)
                extra = f"Sec-WebSocket-Protocol: {proto.group(1).split(',')[1].strip()}\r\n" if proto else ""
                conn.sendall((ok + extra + "\r\n").encode() + RAW_SCRIPT)
                for op, masked, payload in _ws_read_frames(conn, rest):
                    self._record(path, _describe(op, masked, payload))
                    if op == 1 and payload == b"ack":
                        conn.sendall(_ws_close(4000, "done ✓"))
                    if op == 8:
                        return
            elif path in AFTER_OPEN:
                conn.sendall((ok + "\r\n").encode() + AFTER_OPEN[path])
                for op, masked, payload in _ws_read_frames(conn, rest):
                    if path != "/live":
                        self._record(path, _describe(op, masked, payload))
                    if op == 8:
                        return
            elif path == "/drop":
                conn.sendall((ok + "\r\n").encode())
                conn.shutdown(socket.SHUT_WR)
            elif path == "/404":
                conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            elif path == "/badaccept":
                conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: AAAA\r\n\r\n")
            elif path == "/noupgrade":
                conn.sendall(f"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode())
            elif path == "/badproto":
                conn.sendall((ok + "Sec-WebSocket-Protocol: other\r\n\r\n").encode())
            elif path == "/toolarge":
                conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nX-Pad: " + b"p" * 70000 + b"\r\n\r\n")
        except OSError:
            pass
        finally:
            conn.close()

    def server_log(self, path_order):
        with self.lock:
            lines = [f"{p} {line}" for p in path_order for (q, line) in self.log if q == p]
        return ("\n".join(lines) + "\n").encode()


def _wait_until(predicate, timeout=5.0):
    """Poll until predicate() holds (frames the client sent just before exiting may still be queued)."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)


@pytest.fixture
def ws_peer():
    peer = ScriptedWsPeer()
    yield peer
    peer.close()


def _run_with_port(run, workdir, src, port):
    write_files(workdir, {"t.mjs": PRELUDE + "const PEER_PORT = Number(process.argv[2]);\n" + src})
    return run(["t.mjs", str(port)], timeout=30)


PROG_WS_RAW_FRAMES = r"""
// Retry only if the opening handshake itself failed; once open, every frame is handled exactly once.
const connect = (attempts) => new Promise((resolve) => {
  const ws = new WebSocket(`ws://127.0.0.1:${PEER_PORT}/raw?x=1`, ["one", "two"]);
  ws.onopen = () => { ws.onclose = null; resolve(ws); };
  ws.onclose = () => (attempts > 1 ? connect(attempts - 1).then(resolve) : resolve(null));
});
const ws = await connect(5);
await new Promise((resolve) => {
  L("client open, protocol", ws.protocol, ws.readyState, ws.url === `ws://127.0.0.1:${PEER_PORT}/raw?x=1`);
  ws.onmessage = (e) => {
    const d = e.data;
    if (typeof d === "string") L("text", d.length > 20 ? "len " + d.length : JSON.stringify(d));
    else if (d instanceof ArrayBuffer) L("arraybuffer", new Uint8Array(d).join() || "(empty)");
    else { L("blob", Object.prototype.toString.call(d), d.size); ws.binaryType = "arraybuffer"; }
    if (d === "bye") ws.send("ack");
  };
  ws.onclose = (e) => { L("client close", e.code, JSON.stringify(e.reason), e.wasClean, ws.readyState); resolve(); };
  ws.onerror = () => L("client error");
});
"""


def test_websocket_client_frames_from_scripted_peer(run, workdir, ws_peer):
    """CATCHES: WebSocket client frame decoding bugs: fragmented text/binary reassembly, 16-bit extended
    lengths, empty messages, Blob vs ArrayBuffer binaryType delivery, transparent (masked) ping->pong replies,
    unsolicited pongs, the client's request head, and the close-frame echo carrying the peer's code."""
    r = _run_with_port(run, workdir, PROG_WS_RAW_FRAMES, ws_peer.port)
    _check(r, "ws_raw_frames")
    _wait_until(lambda: b"op=8" in ws_peer.server_log(["/raw"]))  # the close echo may still be in flight
    seen = ("request: " + ws_peer.request_heads["/raw"] + "\n").encode() + ws_peer.server_log(["/raw"])
    assert seen == golden(__file__, "ws_raw_frames_peer")


WS_ERROR_PATHS = ["/badop", "/badutf8", "/rsv", "/ctrlfrag", "/cont", "/interleave", "/toobig", "/badreason", "/nocode",
                  "/drop", "/closed-early", "/404", "/badaccept", "/noupgrade", "/badproto", "/toolarge"]

PROG_WS_ERRORS = r"""
const paths = %PATHS%;
const opensFirst = new Set(paths.slice(0, 11));
const attempt = (path, tries) => new Promise((resolve) => {
  const ws = new WebSocket(`ws://127.0.0.1:${PEER_PORT}${path}`, path === "/badproto" ? "mine" : undefined);
  const events = [];
  ws.onopen = () => events.push("open");
  ws.onmessage = (e) => events.push("message:" + e.data);
  ws.onerror = (e) => events.push("error(" + e.type + ")");
  // close() while still CONNECTING: the reference still reports "open" once the handshake lands, and
  // never sends its own close frame (so the peer's close is not echoed either).
  if (path === "/closed-early") { ws.close(); events.push("close() while " + ws.readyState); }
  ws.onclose = (e) => {
    events.push(`close(${e.code},${JSON.stringify(e.reason)},${e.wasClean})`);
    // A handshake that timed out never opened: retry (the reference's handshake read timeout is short).
    if (opensFirst.has(path) && !events.includes("open") && tries > 1) return attempt(path, tries - 1).then(resolve);
    L(path.padEnd(13), events.join(" "), "readyState", ws.readyState);
    resolve();
  };
});
for (const path of paths) await attempt(path, 5);
// Constructor / method validation.
for (const args of [["http://x/"], ["ws://x/#frag"], ["not a url"], ["ws://x/", ["a", "a"]], ["ws://x/", [""]], ["ws://x/", "a b"], ["ws://x/", ["ok", "x,y"]], []]) {
  try { new WebSocket(...args); L("constructed?"); } catch (e) { L("ctor", JSON.stringify(args), e.name, e.message); }
}
const live = new WebSocket(`ws://127.0.0.1:${PEER_PORT}/live`);
await new Promise((resolve) => { live.onopen = resolve; live.onclose = resolve; });
for (const args of [[999], [1001], [2999], [5000], [1000, "x".repeat(124)], [3000, "é".repeat(62)]]) {
  try { live.close(...args); L("close accepted", JSON.stringify(args).slice(0, 20)); } catch (e) { L("close", JSON.stringify(args).slice(0, 20), e.name, e.message); }
}
"""


def test_websocket_protocol_errors_and_validation(run, workdir, ws_peer):
    """CATCHES: WebSocket clients that don't fail the connection with the reference close codes/reasons for
    protocol violations (unknown opcode, bad UTF-8, RSV bits, fragmented control frames, oversize frames),
    accept bad handshakes (status, accept key, missing Upgrade, unrequested subprotocol, oversized head),
    send different close frames back, or validate URLs/subprotocols/close codes differently."""
    src = PROG_WS_ERRORS.replace("%PATHS%", json.dumps(WS_ERROR_PATHS))
    r = _run_with_port(run, workdir, src, ws_peer.port)
    _check(r, "ws_errors")
    _wait_until(lambda: all(f"{p} op=8".encode() in ws_peer.server_log(WS_ERROR_PATHS) for p in WS_ERROR_PATHS[:9]))
    assert ws_peer.server_log(WS_ERROR_PATHS) == golden(__file__, "ws_errors_peer")


PROG_WS_RAW_CLIENT = r"""
const maskFrame = (op, payload, { fin = true } = {}) => {
  const p = typeof payload === "string" ? te.encode(payload) : new Uint8Array(payload);
  const m = [0x11, 0x22, 0x33, 0x44];
  return cat(new Uint8Array([(fin ? 0x80 : 0) | op, 0x80 | p.length, ...m]), p.map((b, i) => b ^ m[i % 4]));
};
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, (req) => {
  const u = new URL(req.url);
  const opts = u.pathname === "/a" ? { protocol: "chat", headers: { "X-Extra": "1", Upgrade: "ignored", "Sec-WebSocket-Accept": "ignored" } }
    : u.pathname === "/b" ? { headers: new Headers({ "X-From-Headers": "yes" }) } : {};
  const ws = Lumen.upgradeWebSocket(req, opts);
  if (!ws) return new Response("upgrade required", { status: 426 });
  ws.onmessage = (data, isBinary) => L(`server ${u.pathname} got`, isBinary ? "binary:" + Array.from(data).join(",") : "text:" + JSON.stringify(data));
  ws.onclose = (code, reason, clean) => L(`server ${u.pathname} onclose`, code, JSON.stringify(reason), clean);
  return new Response("ignored");
});
const client = (path, key, frames, { endAfter = false } = {}) => new Promise((resolve) => {
  const s = net.connect(server.port, "127.0.0.1", () => {
    s.write(`GET ${path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n` + (key ? `Sec-WebSocket-Key: ${key}\r\n` : "") + "Sec-WebSocket-Version: 13\r\n\r\n");
  });
  let buf = new Uint8Array(0), head = null; const got = [];
  s.on("data", (d) => {
    buf = cat(buf, new Uint8Array(d));
    if (head === null) {
      const i = headEnd(buf); if (i < 0) return;
      head = mask(td.decode(buf.subarray(0, i)), server.port); buf = buf.slice(i + 4);
      L(path, "response head", JSON.stringify(head));
      if (!head.startsWith("HTTP/1.1 101")) { L(path, "body", JSON.stringify(td.decode(buf))); return; }
      s.write(frames);
      if (endAfter) s.end();
    }
    buf = takeFrames(buf, (f) => { got.push(describeFrame(f)); if (f.op === 8) s.end(); });
  });
  s.on("error", () => {});
  s.on("close", () => { L(path, "frames from server:", got.join(" ; ") || "(none)"); resolve(); });
});
// RFC 6455 sample key -> the well-known accept value (exercises the SHA-1 + base64 path).
await client("/a", "dGhlIHNhbXBsZSBub25jZQ==", cat(maskFrame(1, "hi"), maskFrame(2, [1, 2]), maskFrame(9, "pp"), maskFrame(1, "fr", { fin: false }), maskFrame(0, "ag"), frame(1, "unmasked ok"), maskFrame(8, cat(new Uint8Array([0x03, 0xe8]), te.encode("bye")))));
await client("/b", "x3JJHMbDL1EzLkh9GBhXDw==", cat(maskFrame(3, "bad")));
await client("/c", "AQIDBAUGBwgJCgsMDQ4PEA==", cat(maskFrame(1, "then drop")), { endAfter: true });
await client("/d", "AQIDBAUGBwgJCgsMDQ4PEA==", cat(maskFrame(8, [])));
await client("/nokey", null, new Uint8Array(0));
await server.shutdown();
L("done");
"""


def test_websocket_raw_client_to_lumen_upgrade_server(run, workdir):
    """CATCHES: Lumen.upgradeWebSocket server-side bugs: wrong Sec-WebSocket-Accept (SHA-1/base64), extra
    headers overriding handshake-critical ones, masked frames not unmasked, fragmented messages, pings not
    answered with unmasked pongs, close/fail/io paths reporting different codes, or non-upgrade fallthrough."""
    _check(_run_prog(run, workdir, PROG_WS_RAW_CLIENT, ws=True), "ws_raw_client")


PROG_NET_FAILURES = r"""
// A port that was just released: connections are refused.
const tmp = Lumen.serve(() => new Response(""), { hostname: "127.0.0.1", port: 0 });
const deadPort = tmp.port;
await tmp.shutdown();
const es = new EventSource(`http://127.0.0.1:${deadPort}/`);
await new Promise((resolve) => { es.onerror = () => { L("eventsource refused: readyState", es.readyState); es.close(); L("after close", es.readyState); resolve(); }; });
const ws = new WebSocket(`ws://127.0.0.1:${deadPort}/`);
await new Promise((resolve) => { ws.onerror = (e) => L("websocket refused:", e.type, ws.readyState); ws.onclose = (e) => { L("websocket close", e.code, e.wasClean, ws.readyState); resolve(); }; });
// The TLS schemes fail at connect time too (no TLS handshake is attempted against a closed port).
try { await fetch(`https://127.0.0.1:${deadPort}/x`); } catch (e) { L("https refused", e.name, mask(e.message, deadPort)); }
try { await fetch(`http://127.0.0.1:${deadPort}/x`); } catch (e) { L("http refused", e.name, mask(e.message, deadPort)); }
const wss = new WebSocket(`wss://127.0.0.1:${deadPort}/`);
await new Promise((resolve) => { wss.onclose = (e) => { L("wss refused", e.code, wss.url === `wss://127.0.0.1:${deadPort}/`); resolve(); }; });
const ess = new EventSource(`https://127.0.0.1:${deadPort}/`);
await new Promise((resolve) => { ess.onerror = () => { L("https eventsource refused", ess.readyState); ess.close(); resolve(); }; });
// SSE redirect loop, a stream the client closes mid-way, and a server that hangs up with no response.
let streamed = 0;
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, (req) => {
  const path = new URL(req.url).pathname;
  if (path === "/loop") return new Response(null, { status: 307, headers: { location: "/loop" } });
  if (path === "/stream") { streamed++; return new Response("retry: 1\ndata: one\n\ndata: two\n\n", { headers: { "content-type": "text/event-stream" } }); }
  return new Response("?", { status: 404 });
});
const base = `http://127.0.0.1:${server.port}`;
await new Promise((resolve) => { const s = new EventSource(base + "/loop"); s.onerror = () => { L("redirect loop: readyState", s.readyState); resolve(); }; });
await new Promise((resolve) => {
  const s = new EventSource(base + "/stream");
  s.onmessage = (e) => { L("stream message", e.data); s.close(); L("closed inside onmessage", s.readyState); setTimeout(resolve, 30); };
  s.onerror = () => L("unexpected error event");
});
L("connections made", streamed);
await server.shutdown();
const { srv, port } = await rawServer((sock, head) => {
  const path = head.split(" ")[1];
  if (path === "/to-ftp") sock.end("HTTP/1.1 302 Found\r\nLocation: ftp://elsewhere/\r\n\r\n");
  else if (path === "/huge-head") sock.end("HTTP/1.1 200 OK\r\nX-Pad: " + "p".repeat(70000) + "\r\n\r\n");
  else sock.end();
});
for (const p of ["/to-ftp", "/huge-head"]) {
  await new Promise((resolve) => { const s = new EventSource(`http://127.0.0.1:${port}${p}`); s.onerror = () => { L(p, "readyState", s.readyState); s.close(); resolve(); }; });
}
await new Promise((resolve) => { const s = new EventSource(`http://127.0.0.1:${port}/`); s.onerror = () => { L("hang-up: readyState", s.readyState); s.close(); resolve(); }; });
try { await fetch(`http://127.0.0.1:${port}/`); } catch (e) { L("fetch hang-up", e.name, mask(e.message, port)); }
await new Promise((resolve) => { const w = new WebSocket(`ws://127.0.0.1:${port}/`); w.onclose = (e) => { L("ws hang-up", e.code, e.wasClean); resolve(); }; });
srv.close();
"""


def test_network_failure_paths(run, workdir):
    """CATCHES: EventSource/WebSocket/fetch implementations that report refused connections, redirect loops,
    or servers hanging up without a response differently (wrong readyState, missing error/close events,
    retrying fatal errors, or different fetch error messages)."""
    _check(_run_prog(run, workdir, PROG_NET_FAILURES, raw=True), "net_failures")
