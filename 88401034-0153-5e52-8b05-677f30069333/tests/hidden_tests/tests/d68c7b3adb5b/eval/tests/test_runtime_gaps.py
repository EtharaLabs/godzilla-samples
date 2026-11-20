"""Remaining reachable corners of the runtime crates, driven through the CLI: process.execve
failures and process.kill of children (lumen-runtime/src/process.rs), the node glue's GC/heap
helpers and fs/os edge errors (lumen-node/src/lib.rs), WebSocket client frames into a
Lumen.serve upgrade (lumen-web/src/websocket.rs), EventSource reconnect/fatal paths against a
scripted Python peer (lumen-web/src/sse.rs), oversized request heads (server.rs), ESM loader
resolution corners (esm.rs), worker ref/unref bookkeeping (worker.rs), the Brotli encoder's
large/skewed meta-blocks and truncated-stream errors (lumen-host/src/brotli.rs), hand-assembled
corrupt Zstandard frames (lumen-host/src/zstd.rs), fd edge cases (lumen-fs) and child_process
option coercion (lumen-node/src/child.rs).

Programs print no ports, pids, absolute paths or timings; every exchange is awaited in order so
the printed sequence never depends on scheduling.
"""

import shutil
import socket
import struct
import threading
from zlib import crc32 as zlib_crc32

import pytest

from conftest import build_addon, err, out


def write(root, files):
    """Create `files` ({relative path: text}) under `root`."""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


# ------------------------------------------------------------------------------ process.rs
def test_execve_failures_throw_os_errors_and_the_script_continues(js, golden):
    """CATCHES: a process.execve that kills or replaces the process when the image cannot be
    executed (missing file, a directory, a non-executable file) instead of throwing an Error
    carrying the OS error, or that does not coerce argv/env entries to strings first."""
    code = r"""
const fs = require('fs');
fs.writeFileSync('not-executable.sh', '#!/bin/sh\necho never\n', { mode: 0o644 });
fs.mkdirSync('a-directory');
const attempts = [
  ['missing file', './definitely/not/here', ['x', 1, true], { A: 1, B: undefined }],
  ['directory', './a-directory', [], {}],
  ['no exec bit', './not-executable.sh', ['sh'], { PATH: '/bin' }],
];
for (const [label, file, args, env] of attempts) {
  try { process.execve(file, args, env); console.log(label, 'returned'); }
  catch (e) { console.log(label, '->', e.constructor.name, e.message); }
}
console.log('script still running, pid unchanged:', typeof process.pid);
"""
    r = js(code)
    assert out(r) == golden("execve_failures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_process_kill_signals_children_and_reports_failures(js, golden):
    """CATCHES: a process.kill that cannot signal another process (a sleeping child must die by
    a named or numeric signal, signal 0 only probes and fails once the child is reaped), or that
    swallows kill(2) failures for unknown or negative signal numbers instead of throwing."""
    code = r"""
const { spawn } = require('child_process');
const waitExit = (c) => new Promise((resolve) => c.on('exit', (code) => resolve(code)));
const a = spawn('sleep', ['30']);
const b = spawn('sleep', ['30']);
console.log('probe a', process.kill(a.pid, 0));
console.log('SIGALRM to a', process.kill(a.pid, 'SIGALRM'));
console.log('a exit code', await waitExit(a), 'killed flag', a.killed);
console.log('signal 9 to b', process.kill(b.pid, 9));
console.log('b exit code', await waitExit(b));
try { process.kill(b.pid, 0); console.log('reaped child still probed'); } catch (e) { console.log('probe after exit', e.constructor.name, e.message.replace(String(b.pid), 'PID')); }
try { process.kill(process.pid, 999); } catch (e) { console.log(e.constructor.name, e.message.replace(String(process.pid), 'PID')); }
try { process.kill(process.pid, -3); } catch (e) { console.log(e.constructor.name, e.message.replace(String(process.pid), 'PID')); }
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("process_kill")
    assert (r.returncode, r.stderr) == (0, b"")


# --------------------------------------------------------------------------- lumen-node lib.rs
def test_bun_gc_and_bun_jsc_heap_helpers(js, golden):
    """CATCHES: Bun.gc/Bun.shrink or bun:jsc's gcAndSweep/fullGC/edenGC that are missing or do
    not return a collection count, a drainMicrotasks that does not run queued promise reactions
    synchronously, or heapStats/memoryUsage objects with the wrong keys or an objectCount that
    does not track allocations."""
    code = r"""
const jsc = require('bun:jsc');
console.log(['gc', 'shrink'].map((k) => `${k}:${typeof Bun[k](true)}`).join(' '),
            ['gcAndSweep', 'fullGC', 'edenGC'].map((k) => `${k}:${Number.isInteger(jsc[k]())}`).join(' '));
const log = [];
Promise.resolve('first').then((v) => log.push(`reaction ${v}`)).then(() => log.push('chained reaction'));
queueMicrotask(() => log.push('queued microtask'));
jsc.drainMicrotasks();
log.push('after drainMicrotasks');
console.log(log.join(' | '));
const before = jsc.heapStats();
const keep = Array.from({ length: 500 }, (_, i) => ({ i }));
const after = jsc.heapStats();
console.log(Object.keys(before).join(','));
console.log('objectCount grew by >= 500:', after.objectCount - before.objectCount >= 500, 'kept', keep.length);
console.log('heapSize tracks objectCount:', after.heapSize === after.objectCount * 128, after.heapCapacity === after.heapSize);
console.log(Object.keys(jsc.memoryUsage()).join(','), jsc.memoryUsage().peak >= jsc.memoryUsage().current);
"""
    r = js(code)
    assert out(r) == golden("bun_gc_jsc")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fs_and_os_edge_errors_from_the_node_glue(js, golden):
    """CATCHES: fs.mkdtempSync under a missing directory that does not fail with ENOENT,
    utimesSync/lutimesSync/statfsSync that pass a path with a NUL byte to the OS instead of
    rejecting it, a statfsSync that does not fail with ENOENT or lacks Node's numeric fields,
    an os.hostname() that is not a non-empty string when HOSTNAME is unset, or stat/readdir
    results that classify a character device or a FIFO as a file or directory."""
    code = r"""
const fs = require('fs');
const os = require('os');
try { fs.mkdtempSync('no/such/parent/tmp-'); } catch (e) { console.log('mkdtemp', e.code, e.syscall ?? 'no-syscall'); }
fs.mkdirSync('parent');
const made = fs.mkdtempSync('parent/tmp-');
console.log('mkdtemp ok', made.startsWith('parent/tmp-'), made.length > 'parent/tmp-'.length, fs.statSync(made).isDirectory());
for (const fn of ['utimesSync', 'lutimesSync', 'statfsSync']) {
  try { fs[fn]('bad\0name', 1, 2); console.log(fn, 'accepted'); } catch (e) { console.log(fn, e.constructor.name, e.message); }
}
try { fs.statfsSync('no/such/dir'); } catch (e) { console.log('statfs missing', e.code); }
const sfs = fs.statfsSync('.');
console.log('statfs keys', Object.keys(sfs).sort().join(','), sfs.bsize > 0);
const h = os.hostname();
console.log('hostname', typeof h, h.length > 0, h === h.trim());
// neither a file, a directory nor a symlink: a character device and a FIFO
const dev = fs.statSync('/dev/null');
console.log('/dev/null', dev.isFile(), dev.isDirectory(), dev.isSymbolicLink());
fs.mkdirSync('kinds');
fs.writeFileSync('kinds/file', '');
require('child_process').execFileSync('mkfifo', ['kinds/fifo']);
for (const d of fs.readdirSync('kinds', { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
  console.log('dirent', d.name, d.isFile(), d.isDirectory(), d.isSymbolicLink());
}
"""
    if shutil.which("mkfifo") is None:
        pytest.skip("mkfifo is not available")
    r = js(code)
    assert out(r) == golden("fs_os_edges")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- lumen-fs
def test_fd_reads_truncates_and_fstat_kinds(js, golden):
    """CATCHES: fd-level fs calls that mishandle zero-length reads (must read nothing and leave
    the buffer untouched), negative ftruncate lengths (clamped to 0 like Node), positional
    writes after truncation, or fstat on a directory descriptor that reports a file."""
    code = r"""
const fs = require('fs');
fs.writeFileSync('a.txt', 'hello world');
fs.mkdirSync('dir');
const fd = fs.openSync('a.txt', 'r+');
const buf = Buffer.alloc(8, 0x2e);
console.log('zero-length read', fs.readSync(fd, buf, 0, 0, 0), JSON.stringify(buf.toString()));
console.log('positional read', fs.readSync(fd, buf, 0, 5, 6), JSON.stringify(buf.toString()));
fs.ftruncateSync(fd, -5);
console.log('size after ftruncate(-5)', fs.fstatSync(fd).size);
fs.writeSync(fd, 'abc', 0);
fs.writeSync(fd, Buffer.from('XY'), 0, 2, 5);
console.log('content', JSON.stringify(fs.readFileSync('a.txt', 'latin1')));
fs.closeSync(fd);
const dfd = fs.openSync('dir', 'r');
const st = fs.fstatSync(dfd);
console.log('fstat dir', st.isDirectory(), st.isFile(), st.isSymbolicLink());
fs.closeSync(dfd);
"""
    r = js(code)
    assert out(r) == golden("fd_edges")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------- websocket.rs / server.rs
def test_websocket_client_large_frames_into_an_upgraded_server(js, golden):
    """CATCHES: a WebSocket client that mis-encodes the 64-bit extended payload length for
    messages over 64 KiB (or the 16-bit form for 126..65535 bytes), an upgraded Lumen.serve
    socket that reassembles them wrongly, or a server handle whose close()/send() after the
    connection already closed throws or reports success."""
    code = r"""
const serverLog = [];
let serverClosed;
const serverDone = new Promise((r) => (serverClosed = r));
const server = Lumen.serve((req) => {
  const ws = Lumen.upgradeWebSocket(req);
  ws.onmessage = (data, isBinary) => serverLog.push(`got ${isBinary ? "binary" : "text"} length=${data.length} ` +
    (isBinary ? `first=${data[0]} last=${data[data.length - 1]}` : `head=${data.slice(0, 6)} tail=${data.slice(-3)}`));
  ws.onclose = (code, reason, clean) => {
    serverLog.push(`onclose ${code} ${JSON.stringify(reason)} clean=${clean}`);
    serverLog.push("close() after onclose -> " + ws.close("not-a-number", "ignored"));
    serverLog.push("send() after onclose -> " + ws.send("too late"));
    serverClosed();
  };
  return new Response(null);
}, { hostname: "127.0.0.1", port: 0 });
const clientLog = [];
await new Promise((resolve) => {
  const ws = new WebSocket(`ws://127.0.0.1:${server.port}`);
  ws.onopen = () => {
    clientLog.push("open path=" + new URL(ws.url).pathname);
    ws.send("abc".repeat(25000) + "end");
    ws.send(new Uint8Array(300).map((_, i) => i & 0xff));
    ws.send(new Uint8Array(70000).fill(9).buffer);
    ws.send(new DataView(new Uint8Array([1, 2, 3, 4, 5]).buffer, 1, 3));
    ws.close(3001, "client done");
    clientLog.push("readyState after close() " + ws.readyState);
  };
  ws.onclose = (e) => { clientLog.push(`close code=${e.code} clean=${e.wasClean} readyState=${ws.readyState}`); resolve(); };
});
await serverDone;
console.log(clientLog.join("\n"));
console.log(serverLog.join("\n"));
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("websocket_large_frames")
    assert (r.returncode, r.stderr) == (0, b"")


def test_serve_answers_oversized_request_heads_with_400_and_keeps_serving(js, golden):
    """CATCHES: a Lumen.serve request parser that accepts unbounded header blocks (more than
    64 KiB) instead of answering 400 "request headers too large", or that stops accepting
    connections after rejecting one."""
    code = r"""
import net from "node:net";
const server = Lumen.serve((req) => new Response(`handled ${new URL(req.url).pathname} x-small=${req.headers.get("x-small")}`),
  { hostname: "127.0.0.1", port: 0 });
const raw = (payload) => new Promise((resolve) => {
  let got = "";
  const sock = net.connect(server.port, "127.0.0.1", () => sock.write(payload));
  sock.on("data", (d) => { got += d.toString("latin1"); });
  sock.on("error", () => {});
  sock.on("close", () => {
    const [head, body] = got.split("\r\n\r\n");
    resolve(`${head.split("\r\n")[0]} | body=${JSON.stringify(body)}`);
  });
});
const filler = Array.from({ length: 70 }, (_, i) => `X-Filler-${i}: ${"f".repeat(1000)}\r\n`).join("");
console.log(await raw(`GET /huge HTTP/1.1\r\nHost: h\r\n${filler}\r\n`));
console.log(await raw("GET /after HTTP/1.1\r\nHost: h\r\nX-Small: 1\r\n\r\n"));
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("serve_oversized_head")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------------- sse.rs
class SsePeer:
    """A scripted text/event-stream server on 127.0.0.1 in a background thread of the test
    process. `/reset` streams one event and then aborts the connection with a TCP RST once the
    client has fetched `/ack` (so the reset never races the event); a reconnect carrying
    Last-Event-ID gets one more event and then a normal end of stream (the client closes the
    EventSource on that event, so the EOF is never treated as a drop)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.acked = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self.sock.close()

    def _accept(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            lines = head.split(b"\r\n\r\n")[0].decode().split("\r\n")
            path = lines[0].split(" ")[1]
            hdrs = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:] if ":" in l)}
            last = hdrs.get("last-event-id")
            if path == "/ack":
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nack")
                self.acked.set()
            elif path == "/reset" and last is None:
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n"
                             b"retry: 5\nid: r1\ndata: before reset\n\n")
                self.acked.wait(15)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            elif path == "/reset":
                conn.sendall(f"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n"
                             f"data: after reset, Last-Event-ID was {last}\n\n".encode())
        except OSError:
            pass
        finally:
            conn.close()


@pytest.fixture
def sse_peer():
    peer = SsePeer()
    yield peer
    peer.close()


def test_eventsource_reconnects_after_a_connection_reset(js, golden, sse_peer):
    """CATCHES: an EventSource whose stream reader treats a TCP reset (ECONNRESET mid-stream) as
    fatal or ignores it, instead of firing error in CONNECTING state and reconnecting after the
    retry interval with the last event id."""
    code = r"""
const base = `http://127.0.0.1:${process.argv[2]}`;
const log = [];
await new Promise((resolve) => {
  const es = new EventSource(base + "/reset");
  es.onopen = () => log.push(`open readyState=${es.readyState}`);
  es.onerror = () => log.push(`error readyState=${es.readyState}`);
  es.onmessage = async (e) => {
    log.push(`message ${JSON.stringify(e.data)} lastEventId=${JSON.stringify(e.lastEventId)}`);
    // tell the peer the first event arrived; it then resets the stream (the ack itself is not
    // logged: its response and the reset race each other)
    if (e.data === "before reset") await (await fetch(base + "/ack")).text();
    else { es.close(); log.push(`closed readyState=${es.readyState}`); resolve(); }
  };
});
console.log(log.join("\n"));
"""
    r = js(code, name="main.mjs", args=(str(sse_peer.port),))
    assert out(r) == golden("eventsource_reset")
    assert (r.returncode, r.stderr) == (0, b"")


def test_eventsource_oversized_head_is_fatal_and_early_close_is_silent(js, golden):
    """CATCHES: an EventSource that buffers an unbounded response head (over 64 KiB) instead of
    failing permanently (error event, readyState CLOSED, no reconnect), or that still opens or
    delivers events for a stream whose close() was called before the connection completed."""
    code = r"""
import net from "node:net";
const heads = [];
let sawBoth;
const bothSeen = new Promise((r) => (sawBoth = r));
const srv = net.createServer((sock) => {
  let head = "";
  sock.on("error", () => {});
  sock.on("data", (d) => {
    head += d.toString("latin1");
    if (!head.includes("\r\n\r\n")) return;
    const path = head.split(" ")[1];
    heads.push(path);
    if (heads.length === 2) sawBoth();
    if (path === "/huge-head") {
      sock.end("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nX-Filler: " + "f".repeat(70000) + "\r\n\r\ndata: never\n\n");
    } else {
      sock.end("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\ndata: should not be seen\n\n");
    }
  });
});
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${srv.address().port}`;
await new Promise((resolve) => {
  const es = new EventSource(base + "/huge-head");
  es.onopen = () => console.log("unexpected open");
  es.onerror = () => { console.log("huge head: error, readyState", es.readyState); resolve(); };
});
const early = new EventSource(base + "/closed-early");
early.onopen = () => console.log("unexpected open after close");
early.onmessage = (e) => console.log("unexpected message", e.data);
early.close();
console.log("closed before connecting, readyState", early.readyState);
await bothSeen;
srv.close();
console.log("server saw:", heads.sort().join(", "));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("eventsource_fatal_and_early_close")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------------- esm.rs
def test_esm_loader_resolution_and_cjs_interop_corners(js, workdir, golden):
    """CATCHES: an ES module loader that mis-escapes U+2028/U+2029 in a JSON module, does not
    normalise `./` segments, cannot follow `module.exports = require('./x')` re-exports to an
    extensionless file, derives bogus named exports from computed defineProperty/__export calls,
    or gives up on packages whose
    package.json has a broken or unresolvable entry instead of falling back to index.js or a
    sibling `<name>.js` file."""
    write(workdir, {
        "data.json": '{"text": "para\u2029graph\u2028line",\t"n": 3}\r\n',
        "sub/mod.mjs": 'export const where = "sub/mod";\n',
        "impl.js": "exports.alpha = 1;\n"
                   "Object.defineProperty(exports, 'beta', { value: 2, enumerable: true });\n"
                   "Object.defineProperty(exports, key(), { value: 3, enumerable: true });\n"
                   "function key() { return 'gamma'; }\n"
                   "function __export(t, o) { Object.assign(t, o); }\n"
                   "__export(exports, makeObj());\n"
                   "function makeObj() { return { delta: 4 }; }\n",
        "reexp.cjs": "module.exports = require('./impl');\n",
        "node_modules/missing-main/package.json": '{"main": "lib/missing.js"}\n',
        "node_modules/missing-main/index.js": "module.exports = 'missing-main index.js';\n",
        "node_modules/broken-json/package.json": '{"main": "unterminated\n',
        "node_modules/broken-json/index.js": "module.exports = 'broken-json index.js';\n",
        "node_modules/sibling/README": "a package directory without an entry point\n",
        "node_modules/sibling.js": "module.exports = 'sibling.js next to the directory';\n",
        "node_modules/mapped/package.json": '{"exports": {"./feature": {"import": "./dist/nope.js"}}}\n',
    })
    code = r"""
import data from "./data.json";
import { where } from "./sub/./mod.mjs";
import reexp, * as reexpNs from "./reexp.cjs";
import missingMain from "missing-main";
import brokenJson from "broken-json";
import sibling from "sibling";
console.log(data.n, data.text.length, [...data.text].map((ch) => ch.charCodeAt(0).toString(16)).join(" "));
console.log(where, JSON.stringify(reexp), Object.keys(reexpNs).sort().join(","));
console.log(missingMain, "|", brokenJson, "|", sibling);
try { await import("mapped/feature"); console.log("mapped/feature loaded"); }
catch (e) { console.log(e.constructor.name, e.message.replace(/ \(imported from .*\)$/, "")); }
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("esm_loader_corners")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- worker.rs
def test_worker_ref_unref_bookkeeping_and_thrown_non_errors(js, workdir, golden):
    """CATCHES: worker ref()/unref() calls that crash or resurrect a worker after it exited, an
    unref'd worker whose re-armed inbox drops messages, a parentPort.ref() inside the worker's
    message handler that does not keep it alive, concurrent fs.promises reads inside a worker
    that are lost or reordered by Promise.all, process.nextTick queues that never run inside a
    worker, or a web worker whose top-level `throw null` is not reported to onerror (with the
    bare value as the message) or that stops running after it."""
    write(workdir, {
        "thrower.js": 'process.nextTick((v) => postMessage("nextTick ran in worker with " + v), 42);\n'
                      'throw null;\n',
        "data-a.txt": "alpha", "data-b.txt": "beta", "data-c.txt": "gamma", "data-d.txt": "delta",
    })
    code = r"""
const NodeWorker = require('worker_threads').Worker;
const log = [];
const keepAlive = setInterval(() => {}, 1000);
// a web worker keeps running after a top-level throw: the error arrives first, then the
// message posted by the nextTick callback queued before the throw
const thrower = new Worker('./thrower.js');
thrower.onerror = (ev) => log.push('web worker onerror: ' + ev.message);
thrower.onmessage = (ev) => {
  log.push('web worker message: ' + ev.data);
  thrower.terminate();
  nodeWorker();
};
function nodeWorker() {
  const w = new NodeWorker(`const { parentPort } = require('worker_threads');
    const fsp = require('fs/promises');
    parentPort.unref();
    parentPort.on('message', async (m) => {
      parentPort.ref();
      if (m === 'read') {
        const texts = await Promise.all(['a', 'b', 'c', 'd'].map((n) => fsp.readFile('data-' + n + '.txt', 'utf8')));
        parentPort.postMessage('read ' + texts.join('+'));
      } else parentPort.postMessage('echo ' + m);
      if (m === 'last') parentPort.close();
    });`, { eval: true });
  w.unref();
  const got = [];
  w.on('message', (m) => { got.push(m); if (got.length < 4) w.postMessage(['read', 'second', 'last'][got.length - 1]); });
  w.on('exit', (code) => {
    log.push(`node worker exit ${code} after ${got.join(', ')}`);
    log.push('ref/unref after exit: ' + [w.ref() === w, w.unref() === w].join(' '));
    clearInterval(keepAlive);
    console.log(log.join('\n'));
  });
  w.postMessage('first');
}
"""
    r = js(code)
    assert out(r) == golden("worker_ref_unref")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- brotli.rs
def test_brotli_encoder_meta_blocks_over_64_kib(js, golden):
    """CATCHES: a Brotli encoder that writes a wrong MNIBBLES/MLEN header for meta-blocks over
    64 KiB, either stored (incompressible input: the raw bytes must follow a byte-aligned
    header, since a 5-nibble MLEN leaves the header mid-byte) or Huffman-coded literals (the
    exact stream is pinned; it was checked to decode back to the input)."""
    code = r"""
const zlib = require('zlib');
const crc = (b) => (zlib.crc32(b) >>> 0).toString(16).padStart(8, "0");
// all 256 byte values equally often: incompressible for a literal-only Huffman code (stored);
// built with native copies (copyWithin doubling) to stay fast on slow builds
const stored = new Uint8Array(70000);
stored.set(Array.from({ length: 256 }, (_, i) => (i * 167) & 255));
for (let k = 256; k < stored.length; k *= 2) stored.copyWithin(k, 0, k);
const s = zlib.brotliCompressSync(stored);
console.log("stored", stored.length, "->", s.length, "header", s.subarray(0, 4).toString("hex"), "trailer", s.subarray(-1).toString("hex"),
            "raw bytes intact", crc(s.subarray(4, 4 + stored.length)) === crc(stored), stored[69999]);
// eight letters with skewed counts: compressible (Huffman-coded literals)
const letters = new TextEncoder().encode("aaaaaaaabbbbccdefgh\n".repeat(3500));
const c = zlib.brotliCompressSync(letters);
console.log("letters", letters.length, "->", c.length, "head", c.subarray(0, 6).toString("hex"), "crc", crc(c));
"""
    r = js(code)
    assert out(r) == golden("brotli_encoder_large_meta_blocks")
    assert (r.returncode, r.stderr) == (0, b"")


def test_brotli_encoder_code_length_shapes(js, golden):
    """CATCHES: a Brotli encoder that emits Huffman code lengths over 15 bits for very skewed
    (Fibonacci) symbol frequencies instead of rescaling them, or encodes a uniform 8-symbol
    alphabet (all lengths equal) with a broken single-length code-length code; both streams
    must decode back to their input."""
    code = r"""
const zlib = require('zlib');
const crc = (b) => (zlib.crc32(b) >>> 0).toString(16).padStart(8, "0");
const fib = [1, 1];
while (fib.length < 18) fib.push(fib[fib.length - 1] + fib[fib.length - 2]); // optimal depth 17 > 15
const skewed = new TextEncoder().encode(fib.map((f, i) => String.fromCharCode(65 + i).repeat(f)).join(""));
const uniform8 = Buffer.from(Array.from({ length: 4096 }, (_, i) => i & 7));
for (const [name, buf] of [["fibonacci", skewed], ["uniform8", uniform8]]) {
  const c = zlib.brotliCompressSync(buf);
  console.log(name, buf.length, "->", c.length, "head", c.subarray(0, 6).toString("hex"), "crc", crc(c), "roundtrip", crc(zlib.brotliDecompressSync(c)) === crc(buf));
}
"""
    r = js(code)
    assert out(r) == golden("brotli_encoder_code_lengths")
    assert (r.returncode, r.stderr) == (0, b"")


# -------------------------------------------------------------------------------- child.rs
def test_child_process_option_coercion_and_unref_streaming(js, golden):
    """CATCHES: a spawn that ignores a non-string cwd (it must be coerced and fail to spawn with
    the OS error), or an unref()'d child whose stdout/stderr chunks arriving after the unref
    (and after a stdin round trip) are lost."""
    code = r"""
const { spawn } = require('child_process');
try { spawn('true', [], { cwd: 4242 }); console.log('spawned'); } catch (e) { console.log(e.constructor.name, e.message); }
const keepAlive = setInterval(() => {}, 1000);
const c = spawn('sh', ['-c', 'echo one; read line; echo "two:$line"; echo three >&2']);
c.unref();
let stdout = '', stderr = '';
c.stdout.on('data', (d) => { stdout += d; if (stdout === 'one\n') c.stdin.end('from parent\n'); });
c.stderr.on('data', (d) => { stderr += d; });
// the exit status and the end of both pipes, in whatever order they arrive
const ended = (s) => new Promise((resolve) => s.on('end', resolve));
Promise.all([new Promise((resolve) => c.on('exit', resolve)), ended(c.stdout), ended(c.stderr)]).then(([code]) => {
  clearInterval(keepAlive);
  console.log('unref child exited', code, JSON.stringify(stdout), JSON.stringify(stderr));
});
"""
    r = js(code)
    assert out(r) == golden("child_coercion_unref")
    assert (r.returncode, r.stderr) == (0, b"")


# --------------------------------------------------------------------------------- zstd.rs
# Hand-assembled single-block frames (FHD 0x00, window descriptor 0x70, one compressed block).
# Every frame was checked against libzstd 1.5: the "ok" frames decode to the same bytes there and
# every other frame is rejected there too (lumen's messages are its own wording).
ZSTD_PROGRAM = r"""
const zlib = require('zlib');
for (const [name, h] of Object.entries(CASES)) {
  try {
    const d = zlib.zstdDecompressSync(Buffer.from(h, 'hex'));
    console.log(name, 'decoded', JSON.stringify(Array.from(d)), JSON.stringify(d.toString('latin1')));
  } catch (e) { console.log(name, e.constructor.name, e.message); }
}
"""

ZSTD_HUFFMAN_TREES = {
    "direct_weights_truncated": "28b52ffd00702d0000124000ff00",
    "weight_12": "28b52ffd007035000012800080c000",
    "all_zero_weights": "28b52ffd0070350000128000800000",
    "two_weight_11_code_too_long": "28b52ffd007035000012800081bb00",
    "weights_3_1_not_completable": "28b52ffd0070350000128000813100",
    "stream_overrun": "28b52ffd00703d000012c00080100100",
    "stream_leftover_bits": "28b52ffd00703d000012c00080100700",
    "ok_two_one_bit_symbols": "28b52ffd00703d000032c00080100d00",
    "four_streams_without_jump_table": "28b52ffd00704d0000864001801001020300",
}


def test_zstd_huffman_tree_descriptions_and_literal_streams(js, golden):
    """CATCHES: a Zstandard literals decoder that accepts direct Huffman weight lists running
    past the section, weights above 11, all-zero weights, weight sums needing codes over 11
    bits or that cannot be completed to a power of two, single-stream Huffman literals that
    overrun or leave bits unconsumed, or a 4-stream literals section too short for its jump
    table; plus one well-formed 1-bit tree that must decode exactly."""
    r = js("const CASES = " + repr(ZSTD_HUFFMAN_TREES).replace("'", '"') + ";\n" + ZSTD_PROGRAM)
    assert out(r) == golden("zstd_huffman_trees")
    assert (r.returncode, r.stderr) == (0, b"")


ZSTD_FSE_WEIGHTS = {
    "region_truncated": "28b52ffd00702d00001240000500",
    "accuracy_log_20": "28b52ffd00703d000012c000020f0000",
    "no_bitstream_after_table": "28b52ffd00703d000012c00002f00300",
    "initial_states_truncated": "28b52ffd007045000012000103f003ff00",
    "zero_bit_states_never_end": "28b52ffd00704d000012400104f003ffff00",
    "zero_run_past_255_symbols": "28b52ffd0070e500001200061710feffffffffffffffffffffffffffffffffffffffff1f00",
    "symbol_256_after_zero_run": "28b52ffd0070fd000012c0061a10feffffffffffffffffffffffffffffffffffffffff0d00000000",
    "final_symbol_is_number_256": "28b52ffd0070f500001280061910fefffffffffffffffffffffffffffffffffffffffffd010000",
}


def test_zstd_fse_compressed_huffman_weights(js, golden):
    """CATCHES: an FSE weight-table reader that accepts a header region longer than the
    section, accuracy logs above 6, a table with no bitstream after it or too few bits for the
    two initial states, a degenerate single-symbol table whose zero-bit states would emit
    weights forever (must stop after 255), or zero-probability runs and distributions with more
    than 256 symbols."""
    r = js("const CASES = " + repr(ZSTD_FSE_WEIGHTS).replace("'", '"') + ";\n" + ZSTD_PROGRAM)
    assert out(r) == golden("zstd_fse_weights")
    assert (r.returncode, r.stderr) == (0, b"")


ZSTD_SEQUENCES = {
    "literals_regen_262143": "28b52ffd00704d0000feffff000080100100",
    "long_sequence_count_truncated": "28b52ffd00701d000000ff01",
    "long_sequence_count_without_modes": "28b52ffd0070350000106162ff0000",
    "long_sequence_count_without_bitstream": "28b52ffd00703d0000106162ff341200",
    "offset_table_repeat_without_history": "28b52ffd0070350000106162013001",
    "match_table_repeat_without_history": "28b52ffd0070350000106162010c01",
    "initial_states_truncated": "28b52ffd0070350000106162010001",
    "fse_literal_length_table_truncated": "28b52ffd00703500001061620180f0",
    "ok_rle_tables_overlapping_copy": "28b52ffd00705500001878797a015401020004",
}


def test_zstd_literals_size_and_sequence_section_errors(js, golden):
    """CATCHES: a Zstandard block decoder that accepts a 5-byte compressed-literals header
    declaring more than 128 KiB, a 3-byte sequence count cut short or followed by no modes
    byte or no bitstream, repeat-mode offset or
    match-length tables in the first block, a sequences bitstream too short for the initial
    states or an FSE table description running past the block, or that mis-executes RLE-mode
    tables with an overlapping (offset 1) match."""
    r = js("const CASES = " + repr(ZSTD_SEQUENCES).replace("'", '"') + ";\n" + ZSTD_PROGRAM)
    assert out(r) == golden("zstd_sequences")
    assert (r.returncode, r.stderr) == (0, b"")


def test_brotli_streams_truncated_inside_headers_and_code_lengths(js, golden):
    """CATCHES: a Brotli decoder that reads past the end of a stream cut inside the meta-block
    header, inside the complex prefix code's code-length code, or inside the symbol code
    lengths (zero-filling instead of failing), or that mis-decodes the intact stream."""
    code = r"""
const zlib = require('zlib');
const fib = [1, 1];
while (fib.length < 12) fib.push(fib[fib.length - 1] + fib[fib.length - 2]);
const input = Buffer.concat(fib.map((f, i) => Buffer.alloc(f, 65 + i)));
const full = zlib.brotliCompressSync(input);
console.log('intact', full.length, zlib.brotliDecompressSync(full).equals(input));
for (const n of [1, 3, 5, 6, 7, 9, 12, 20, full.length - 1]) {
  try { zlib.brotliDecompressSync(full.subarray(0, n)); console.log(n, 'decoded'); }
  catch (e) { console.log(n, full.subarray(0, Math.min(n, 10)).toString('hex'), e.constructor.name, e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("brotli_truncations")
    assert (r.returncode, r.stderr) == (0, b"")


# -------------------------------------------------------------------------------- napi.rs
NAPI_ADDON = r"""
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
typedef void *napi_env;
typedef void *napi_value;
typedef void *napi_callback_info;
typedef void *napi_ref;
typedef int napi_status;
typedef napi_value (*napi_callback)(napi_env, napi_callback_info);
extern napi_status napi_get_cb_info(napi_env, napi_callback_info, size_t *, napi_value *, napi_value *, void **);
extern napi_status napi_has_named_property(napi_env, napi_value, const char *, bool *);
extern napi_status napi_get_value_string_utf8(napi_env, napi_value, char *, size_t, size_t *);
extern napi_status napi_get_boolean(napi_env, bool, napi_value *);
extern napi_status napi_create_int32(napi_env, int32_t, napi_value *);
extern napi_status napi_create_function(napi_env, const char *, size_t, napi_callback, void *, napi_value *);
extern napi_status napi_set_named_property(napi_env, napi_value, const char *, napi_value);
extern napi_status napi_create_reference(napi_env, napi_value, uint32_t, napi_ref *);
extern napi_status napi_delete_reference(napi_env, napi_ref);
extern napi_status napi_reference_ref(napi_env, napi_ref, uint32_t *);
extern napi_status napi_reference_unref(napi_env, napi_ref, uint32_t *);
extern napi_status napi_get_reference_value(napi_env, napi_ref, napi_value *);
extern napi_status napi_create_array(napi_env, napi_value *);
extern napi_status napi_set_element(napi_env, napi_value, uint32_t, napi_value);

static napi_value num(napi_env env, int32_t v) { napi_value r; napi_create_int32(env, v, &r); return r; }

/* has(obj, name) -> [status, result] */
static napi_value Has(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  char name[64];
  size_t len;
  napi_get_value_string_utf8(env, argv[1], name, sizeof name, &len);
  bool has = false;
  napi_status st = napi_has_named_property(env, argv[0], name, &has);
  napi_value arr, b;
  napi_create_array(env, &arr);
  napi_set_element(env, arr, 0, num(env, st));
  napi_get_boolean(env, has, &b);
  napi_set_element(env, arr, 1, b);
  return arr;
}

/* refs(value) -> [count after create, ref, unref, unref, ref, value still reachable (1/0)];
   the reference is deleted at the end, then NULL references are handed to delete/ref/unref
   (they must be ignored; their counts are reported as the last two entries). */
static napi_value Refs(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1], arr, got;
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  napi_create_array(env, &arr);
  uint32_t i = 0, count = 99;
  napi_ref ref;
  napi_create_reference(env, argv[0], 1, &ref);
  napi_set_element(env, arr, i++, num(env, 1));
  napi_reference_ref(env, ref, &count);
  napi_set_element(env, arr, i++, num(env, (int)count));
  napi_reference_unref(env, ref, &count);
  napi_set_element(env, arr, i++, num(env, (int)count));
  napi_reference_unref(env, ref, &count);
  napi_set_element(env, arr, i++, num(env, (int)count));
  napi_reference_ref(env, ref, &count);
  napi_set_element(env, arr, i++, num(env, (int)count));
  napi_get_reference_value(env, ref, &got);
  napi_set_element(env, arr, i++, got);
  napi_delete_reference(env, ref);
  napi_delete_reference(env, NULL);
  count = 99;
  napi_reference_ref(env, NULL, &count);
  napi_set_element(env, arr, i++, num(env, (int)count));
  count = 99;
  napi_reference_unref(env, NULL, &count);
  napi_set_element(env, arr, i++, num(env, (int)count));
  return arr;
}

napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  napi_value f;
  napi_create_function(env, "has", 3, Has, NULL, &f);
  napi_set_named_property(env, exports, "has", f);
  napi_create_function(env, "refs", 4, Refs, NULL, &f);
  napi_set_named_property(env, exports, "refs", f);
  return exports;
}
"""


def test_napi_has_named_property_and_reference_counting(js, workdir, golden):
    """CATCHES: an napi_has_named_property that ignores inherited properties or swallows an
    exception thrown by a Proxy trap (it must surface as a pending exception, i.e. a JS throw
    from the addon call), or reference ref/unref counts that are off, or delete/ref/unref that
    crash on NULL references instead of ignoring them."""
    build_addon(NAPI_ADDON, workdir / "addon.node")
    code = r"""
const addon = require('./addon.node');
const plain = { present: 1 };
for (const key of ['present', 'absent', 'toString']) console.log(key, JSON.stringify(addon.has(plain, key)));
const trap = new Proxy({}, {
  get() { throw new RangeError('trap refused'); },
  has() { throw new RangeError('trap refused'); },
});
try { console.log('proxy', JSON.stringify(addon.has(trap, 'x'))); }
catch (e) { console.log('proxy threw', e.constructor.name, e.message); }
const target = { tag: 'referenced object' };
const res = addon.refs(target);
console.log('refs', JSON.stringify(res.slice(0, 5)), res[5] === target, JSON.stringify(res.slice(6)));
"""
    r = js(code)
    assert out(r) == golden("napi_has_and_refs")
    assert (r.returncode, r.stderr) == (0, b"")


def test_websocket_server_side_protocol_failures_from_a_raw_peer(js, golden):
    """CATCHES: an upgraded Lumen.serve WebSocket that cannot reassemble a fragmented message
    around an interleaved ping (answered with an unmasked pong), maps a code-less close to
    anything but 1005 (echoing 1000), or tolerates over-long or fragmented control frames,
    invalid UTF-8 in text or close reasons, orphan or interleaved continuation frames, unknown
    opcodes or a length beyond the message cap instead of failing with the right close code
    (1002/1007/1009) sent unmasked to the peer and reported to onclose as unclean."""
    code = r"""
// A raw node:net client speaks RFC 6455 to a Lumen.serve upgrade, so the server's own bytes are visible.
import net from "node:net";
const serverLog = [];
let pending = 0, allClosed;
const done = new Promise((r) => (allClosed = r));
const server = Lumen.serve((req) => {
  const tag = new URL(req.url).pathname;
  const ws = Lumen.upgradeWebSocket(req);
  ws.onmessage = (data, isBinary) => serverLog.push(`${tag} message ${isBinary ? "binary " + Array.from(data).join(",") : JSON.stringify(data)}`);
  ws.onclose = (code, reason, clean) => { serverLog.push(`${tag} onclose ${code} ${JSON.stringify(reason)} clean=${clean}`); if (--pending === 0) allClosed(); };
  return new Response(null);
}, { hostname: "127.0.0.1", port: 0 });
const frame = (op, payload, { fin = true, len } = {}) => {
  const p = Buffer.from(payload), key = [0x0a, 0x0b, 0x0c, 0x0d];
  const n = len ?? p.length;
  const head = [(fin ? 0x80 : 0) | op];
  if (n < 126) head.push(0x80 | n);
  else if (n < 65536) head.push(0x80 | 126, n >> 8, n & 255);
  else head.push(0x80 | 127, 0, 0, 0, 0, (n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255);
  return Buffer.concat([Buffer.from([...head, ...key]), Buffer.from(Array.from(p, (x, i) => x ^ key[i % 4]))]);
};
const describe = (buf) => {
  const frames = [];
  while (buf.length >= 2) {
    const op = buf[0] & 0x0f, len = buf[1] & 0x7f, data = buf.subarray(2, 2 + len);
    frames.push(`op=${op} fin=${(buf[0] & 0x80) !== 0} masked=${(buf[1] & 0x80) !== 0} ` +
      (op === 8 ? `code=${data.readUInt16BE(0)} reason=${JSON.stringify(data.subarray(2).toString())}` : JSON.stringify(data.toString())));
    buf = buf.subarray(2 + len);
  }
  return frames.join(" ; ");
};
function session(path, frames) {
  pending++;
  return new Promise((resolve) => {
    let got = Buffer.alloc(0), sent = false;
    const sock = net.connect(server.port, "127.0.0.1", () => {
      sock.write(`GET ${path} HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n`);
    });
    sock.on("data", (d) => {
      got = Buffer.concat([got, d]);
      if (!sent && got.toString("latin1").includes("\r\n\r\n")) { sent = true; sock.write(Buffer.concat(frames)); }
    });
    sock.on("error", () => {});
    sock.on("close", () => {
      const text = got.toString("latin1"), end = text.indexOf("\r\n\r\n");
      resolve(`${path}: ${text.slice(0, text.indexOf("\r\n"))} | ${describe(got.subarray(end + 4))}`);
    });
  });
}
console.log(await session("/fragments", [frame(1, "fr", { fin: false }), frame(9, "ping!"), frame(0, "ag", { fin: false }), frame(0, "ment"), frame(2, [1, 2, 3]), frame(8, "")]));
console.log(await session("/long-control", [frame(9, "x".repeat(126))]));
console.log(await session("/fragmented-ping", [frame(9, "p", { fin: false })]));
console.log(await session("/bad-utf8", [frame(1, [0x68, 0xc3, 0x28])]));
console.log(await session("/bad-close-reason", [frame(8, [0x03, 0xe8, 0xff])]));
console.log(await session("/orphan-continuation", [frame(0, "tail")]));
console.log(await session("/interleaved-data", [frame(1, "a", { fin: false }), frame(2, "b")]));
console.log(await session("/unknown-opcode", [frame(5, "?")]));
console.log(await session("/too-big", [frame(2, "", { len: 40 * 1024 * 1024 })]));
await done;
for (const l of serverLog) console.log("server", l);
await server.shutdown();
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("websocket_server_protocol_failures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_esm_wrappers_for_commonjs_files_in_awkward_paths(js, workdir, golden):
    """CATCHES: an ESM-to-CommonJS bridge that embeds the CommonJS file's absolute path in the
    generated module source without escaping quotes, backslashes or newlines (the import would
    fail to parse or load the wrong file), or whose export scanner treats a defineProperty on
    an object merely named like `exports...` as a named export."""
    write(workdir, {
        "we\\ird/m.cjs": "exports.where = 'backslash directory';\n",
        "quo\"te/m.cjs": "exports.where = 'double-quote directory';\n",
        "new\nline/m.cjs": "exports.where = 'newline directory';\n",
        "lexer.cjs": "const exportsHolder = {};\n"
                     "Object.defineProperty(exportsHolder, 'notExported', { value: 1 });\n"
                     "Object.defineProperty(module.exports, 'viaModule', { value: 'm', enumerable: true });\n"
                     "exports.plain = 'p';\n",
    })
    code = r"""
import { where as a } from "./we\\ird/m.cjs";
import { where as b } from './quo"te/m.cjs';
import { where as c } from "./new\nline/m.cjs";
import * as lexer from "./lexer.cjs";
console.log(a, "|", b, "|", c);
console.log(Object.keys(lexer).sort().join(","), lexer.viaModule, lexer.plain, JSON.stringify(lexer.default));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("esm_cjs_awkward_paths")
    assert (r.returncode, r.stderr) == (0, b"")


def test_process_stdout_and_stderr_write_raw_chunks(js):
    """CATCHES: process.stdout/stderr writers that append newlines, re-encode Uint8Array/Buffer
    chunks as text (non-UTF-8 bytes must pass through untouched), do not return true from
    write(), or whose end(chunk) drops the final chunk or does not return the stream."""
    code = r"""
const w1 = process.stdout.write('text without newline|');
const w2 = process.stdout.write(new Uint8Array([0xff, 0xfe, 0x00, 0x41]));
const w3 = process.stdout.write(Buffer.from('|buffer é|'));
process.stderr.write('to stderr ');
process.stderr.write(new Uint8Array([0x80, 0x0a]));
const same = process.stdout.end('end chunk\n') === process.stdout;
console.log(w1, w2, w3, same, process.stdout.isTTY, process.stdout.fd, process.stderr.fd);
"""
    r = js(code)
    assert r.stdout == b"text without newline|\xff\xfe\x00A|buffer \xc3\xa9|end chunk\ntrue true true true false 1 2\n"
    assert (r.returncode, r.stderr) == (0, b"to stderr \x80\n")


def test_bun_jsc_serialize_and_introspection_helpers(js, golden):
    """CATCHES: bun:jsc serialize/deserialize that lose Map/Set/Date/typed-array/BigInt/cyclic
    structure, shallow memory estimates that ignore string length or typed-array bytes, a
    random seed that does not round-trip as uint32, or inert JIT hooks that do not return the
    function they were given."""
    code = r"""
const jsc = require('bun:jsc');
const cyclic = { name: 'root', list: [1, 2n ** 70n, new Date(86400000)], map: new Map([['k', new Set([1, 2])]]), bytes: new Uint16Array([1, 65535]) };
cyclic.self = cyclic;
const buf = jsc.serialize(cyclic);
const back = jsc.deserialize(buf);
console.log(back !== cyclic, back.self === back, back.name, back.list[1] === 2n ** 70n, back.list[2].toISOString());
console.log(back.map.get('k') instanceof Set, [...back.map.get('k')].join(','), back.bytes.constructor.name, Array.from(back.bytes).join(','));
console.log(jsc.estimateShallowMemoryUsageOf('abcd'), jsc.estimateShallowMemoryUsageOf(new Uint8Array(1000)), jsc.estimateShallowMemoryUsageOf(5), jsc.estimateShallowMemoryUsageOf(10n), jsc.estimateShallowMemoryUsageOf({ a: 1, b: 2 }));
jsc.setRandomSeed(-1);
console.log(jsc.getRandomSeed(), jsc.isRope('x'.repeat(100)), jsc.callerSourceOrigin());
const f = (x) => x * 2;
console.log(jsc.noInline(f) === f, jsc.noFTL(f) === f, jsc.numberOfDFGCompiles(f), jsc.totalCompileTime(), typeof jsc.optimizeNextInvocation(f));
"""
    r = js(code)
    assert out(r) == golden("bun_jsc_serialize")
    assert (r.returncode, r.stderr) == (0, b"")


def test_child_process_inherit_and_ignore_stdio(js):
    """CATCHES: spawn stdio modes that are mixed up: 'inherit' must hand the child the parent's
    own stdout/stderr (output appears in order with the parent's), 'ignore' must give the child
    /dev/null (no stream object on the parent), and per-fd arrays must be honoured."""
    code = r"""
const { spawn } = require('child_process');
const exited = (c) => new Promise((resolve) => c.on('close', (code) => resolve(code)));
console.log('parent before');
const a = spawn('sh', ['-c', 'echo child inherited stdout; echo child inherited stderr >&2; exit 3'], { stdio: 'inherit' });
console.log('inherit streams', a.stdin, a.stdout, a.stderr, 'exit', await exited(a));
const b = spawn('sh', ['-c', 'read x || echo stdin is empty; echo hidden; echo also hidden >&2'], { stdio: ['ignore', 'ignore', 'ignore'] });
console.log('ignore streams', b.stdin, b.stdout, b.stderr, 'exit', await exited(b));
const c = spawn('sh', ['-c', 'echo piped out; echo inherited err >&2'], { stdio: ['ignore', 'pipe', 'inherit'] });
let piped = '';
c.stdout.on('data', (d) => (piped += d));
// wait for both the exit status and the end of the piped stream
const [code] = await Promise.all([exited(c), new Promise((resolve) => c.stdout.on('end', resolve))]);
console.log('mixed', c.stdin, typeof c.stdout.on, c.stderr, 'exit', code, JSON.stringify(piped));
"""
    r = js(code, name="main.mjs")
    assert out(r) == ("parent before\nchild inherited stdout\ninherit streams null null null exit 3\n"
                      "ignore streams null null null exit 0\n"
                      'mixed null function null exit 0 "piped out\\n"\n')
    assert (r.returncode, err(r)) == (0, "child inherited stderr\ninherited err\n")


def test_process_kill_delivers_each_named_signal_to_a_trapping_child(js, golden):
    """CATCHES: a process.kill signal-name table with wrong numbers (each child traps exactly one
    signal and reports which one arrived), numeric signals that are not passed through, or a
    kill that returns before delivering."""
    code = r"""
import { spawn } from 'node:child_process';
async function trapped(trapName, sendAs) {
  const c = spawn('sh', ['-c', `trap 'echo caught ${trapName}; exit 4' ${trapName}; echo ready; while :; do sleep 0.02; done`]);
  let out = '';
  const exited = new Promise((resolve) => c.on('exit', resolve));
  const ended = new Promise((resolve) => c.stdout.on('end', resolve));
  // signal only once the trap is installed (the child says "ready" after `trap`)
  await new Promise((resolve) => c.stdout.on('data', (d) => { out += d; if (out === 'ready\n') resolve(); }));
  const sent = process.kill(c.pid, sendAs);
  const [code] = await Promise.all([exited, ended]);
  console.log(`${String(sendAs).padEnd(7)} -> returned ${sent}, exit ${code}, child said ${JSON.stringify(out)}`);
}
await trapped('ABRT', 'SIGABRT');
await trapped('ILL', 4);
await trapped('FPE', 'SIGFPE');
await trapped('ALRM', 'SIGALRM');
await trapped('ALRM', 14);
await trapped('TERM', 'SIGTERM');
await trapped('TERM', 15);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("kill_trapped_signals")
    assert (r.returncode, r.stderr) == (0, b"")


def test_process_stdin_streams_binary_input_byte_exact(js):
    """CATCHES: a process.stdin that decodes piped bytes as UTF-8 (corrupting non-text input such
    as lone 0x80-0xff bytes and NULs), drops or duplicates chunks, or never emits 'end'."""
    payload = bytes((i * 7 + 3) % 256 for i in range(20_000))
    code = r"""
const zlib = require('zlib');
const chunks = [];
process.stdin.on('data', (chunk) => chunks.push(chunk));
process.stdin.on('end', () => {
  const all = Buffer.concat(chunks);
  console.log('bytes', all.length, 'crc32', (zlib.crc32(all) >>> 0).toString(16).padStart(8, '0'),
              'head', all.subarray(0, 4).toString('hex'), 'tail', all.subarray(-3).toString('hex'),
              'every chunk a Buffer', chunks.every((c) => Buffer.isBuffer(c)));
});
"""
    r = js(code, input=payload)
    assert out(r) == ("bytes 20000 crc32 %08x head %s tail %s every chunk a Buffer true\n"
                      % (zlib_crc32(payload), payload[:4].hex(), payload[-3:].hex()))
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------------- lumen-timers
def test_timers_without_delays_and_cleared_before_firing(js):
    """CATCHES: setTimeout that rejects a missing or undefined delay instead of treating it as 0
    (and dropping the extra arguments), clearTimeout/clearInterval that throw on missing, unknown
    or non-numeric ids, a cleared 0 ms timer that still fires when it sits behind another due
    timer, or an interval that keeps ticking after clearing itself."""
    code = r"""
const order = [];
setTimeout(() => order.push('A (0 ms)'), 0);
const c = setTimeout(() => order.push('C must not run'), 0);
setTimeout((x, y) => order.push(`B (undefined delay) args=${x},${y}`), undefined, 1, 2);
setTimeout(() => order.push('D (no delay argument)'));
clearTimeout(c);
console.log('clear results', clearTimeout(), clearTimeout(undefined), clearInterval(-1), clearTimeout('x'), clearInterval(c));
let n = 0;
const iv = setInterval(() => {
  order.push(`interval tick ${++n}`);
  if (n === 3) { clearInterval(iv); console.log(order.join('\n')); }
}, 1);
"""
    r = js(code)
    assert out(r) == ("clear results undefined undefined undefined undefined undefined\n"
                      "A (0 ms)\nB (undefined delay) args=1,2\nD (no delay argument)\n"
                      "interval tick 1\ninterval tick 2\ninterval tick 3\n")
    assert (r.returncode, r.stderr) == (0, b"")
