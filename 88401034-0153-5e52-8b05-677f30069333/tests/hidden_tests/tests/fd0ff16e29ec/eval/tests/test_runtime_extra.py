"""Runtime edge paths beyond the main runtime modules, all loopback-only and deterministic:

- node:net / node:dgram error codes (refused, EADDRNOTAVAIL, EPIPE, EACCES broadcast, oversized
  datagrams), unref'd re-arming and multicast argument validation (no multicast group is ever joined).
- bun:sqlite result codes, setCustomSQLite with real/bogus libraries, SQLite out-of-memory.
- bun:ffi JSCallback marshalling and cc() driven by a fake compiler script (no C toolchain needed).
- Lumen.upgradeWebSocket server-side send/close, an idle WebSocket client, EventSource and
  Lumen.serve against peers that reset connections, fetch chunked-body limits.
- Smaller native paths: seeded xxHash3, malformed argon2 PHC strings, AES-GCM with non-96-bit IVs,
  WebAssembly export kinds, worker_threads parentPort ref toggling, child_process unref/cwd.

Servers bind 127.0.0.1 (or a unix socket in the work dir) with OS-chosen ports that are never
printed; scripted peers run in threads of the test process. "Non-local address" cases use
192.0.2.1 (TEST-NET-1), which fails locally with EADDRNOTAVAIL without touching any network.
"""

import base64
import hashlib
import re
import socket
import struct
import threading
import time

import pytest

from conftest import golden, scaled, write_files

# Engine tiers for programs whose JS glue does real work (all tiers share one golden).
TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


def _check(r, name, stderr=b""):
    assert (r.returncode, r.stderr) == (0, stderr), r.stderr
    assert r.stdout == golden(__file__, name)


# ---------------------------------------------------------------------------------------------
# node:net / node:dgram
# ---------------------------------------------------------------------------------------------

PROG_NET_ERRORS_UNREF = r"""
const net = require("net");
const dgram = require("dgram");
const out = (...a) => console.log(...a);
const steps = [];
const next = () => { const f = steps.shift(); if (f) f(); else out("all steps done"); };
steps.push(() => {
  // ECONNREFUSED: connect to the local port of an established client socket (bound, but nothing
  // listens on it), through the native connect loop.
  const s = net.createServer((sock) => sock.on("close", () => s.close()));
  s.listen(0, "127.0.0.1", () => {
    const holder = net.connect(s.address().port, "127.0.0.1", () => {
      const port = holder.address().port;
      const c = net.connect(port, "127.0.0.1");
      c.on("error", (e) => out("refused", e.name, e.code, e.syscall, e.address, e.port === port, e.message.replace(String(port), "PORT")));
      c.on("close", (h) => { out("refused close hadError", h, c.destroyed); holder.end(); });
    });
    holder.on("close", () => next());
  });
});
steps.push(() => {
  const s = net.createServer();
  s.on("error", (e) => { out("listen non-local", e.code, e.syscall, e.address, e.port, e.message, s.listening); next(); });
  s.listen(0, "192.0.2.1", () => out("unexpected listen"));
});
steps.push(() => {
  // A half-open unix client writing after its peer is gone gets EPIPE from the native write.
  const server = net.createServer((sock) => sock.destroy());
  server.listen("p.sock", () => {
    const c = net.connect({ path: "p.sock", allowHalfOpen: true });
    c.on("end", () => {
      out("half-open client saw end", c.writable);
      c.write("after peer closed", (err) => { out("write cb", err.name, err.code, err.syscall, err.message); c.destroy(); });
    });
    c.on("error", (e) => out("client error", e.code, e.message));
    c.on("close", (h) => { out("client close", h); server.close(next); });
  });
});
steps.push(() => {
  // An unref'd server re-arms its accept unref'd; an unref'd client re-arms its reads unref'd.
  // A long ref'd timer keeps the loop alive while only unref'd handles are waiting.
  const keep = setTimeout(() => out("keep-alive timer fired?!"), 60000);
  const server = net.createServer((sock) => {
    sock.write("t1;");
    setTimeout(() => { sock.write("t2;"); setTimeout(() => sock.end("t3;"), 5); }, 5);
  });
  server.listen(0, "127.0.0.1", () => {
    server.unref(); server.ref(); server.unref();
    const c = net.connect(server.address().port, "127.0.0.1", () => { c.unref(); c.ref(); c.unref(); });
    let got = "";
    c.on("data", (d) => { got += d; });
    c.on("end", () => out("unref'd client got", got));
    c.on("close", () => { server.ref(); server.close(() => { clearTimeout(keep); out("unref'd server closed"); next(); }); });
  });
});
steps.push(() => {
  const u = dgram.createSocket("udp4");
  u.on("error", (e) => { out("udp bind non-local", e.code, e.syscall, e.address, e.port, e.message); next(); });
  u.bind(0, "192.0.2.1", () => out("unexpected bind"));
});
steps.push(() => {
  const v = dgram.createSocket("udp4");
  v.bind(0, "127.0.0.1", () => {
    v.send("x", 9, "127.255.255.255", (err, n) => {
      out("broadcast without SO_BROADCAST", err.name, err.code, err.syscall, err.address, err.port, err.message, n);
      v.send(Buffer.alloc(70000), 9, "127.0.0.1", (err2, n2) => {
        out("oversized datagram", err2.code, err2.syscall, err2.message, n2);
        v.send("no callback", 9, "127.255.255.255");
        v.once("error", (e3) => { out("error event", e3.code, e3.message); v.close(next); });
      });
    });
  });
});
steps.push(() => {
  const a = dgram.createSocket("udp4"), b = dgram.createSocket("udp4");
  const keep = setTimeout(() => out("keep-alive timer fired?!"), 60000);
  a.bind(0, "127.0.0.1", () => {
    a.unref();
    const got = [];
    a.on("message", (m) => {
      got.push(String(m));
      if (got.length === 2) { clearTimeout(keep); out("unref'd socket received", got.join(",")); a.close(); b.close(next); }
    });
    b.send("one", a.address().port, "127.0.0.1", () => b.send("two", a.address().port, "127.0.0.1"));
  });
});
steps.push(() => {
  // Multicast membership argument validation only (no group is ever joined).
  const u = dgram.createSocket("udp4");
  u.bind(0, "127.0.0.1", () => {
    const tries = [
      ["ssm group not multicast", () => u.addSourceSpecificMembership("127.0.0.1", "10.1.2.3")],
      ["ssm bad interface", () => u.addSourceSpecificMembership("127.0.0.1", "232.1.1.1", "not-an-ip")],
      ["drop ssm bad source", () => u.dropSourceSpecificMembership("nope", "232.1.1.1")],
      ["drop ssm not multicast", () => u.dropSourceSpecificMembership("127.0.0.1", "127.0.0.2", "127.0.0.1")],
      ["drop ssm bad interface", () => u.dropSourceSpecificMembership("127.0.0.1", "232.1.1.1", "999.1.1.1")],
      ["add bad interface", () => u.addMembership("239.1.2.3", "eth-zero")],
      ["drop bad interface", () => u.dropMembership("239.1.2.3", "1.2.3")],
      ["multicast interface not local", () => u.setMulticastInterface("192.0.2.1")],
    ];
    for (const [label, f] of tries) {
      try { f(); out(label, "ok"); } catch (e) { out(label, e.name, e.code, e.syscall, e.message); }
    }
    u.close(next);
  });
});
next();
"""


def test_net_dgram_error_codes_and_unref_rearm(run):
    """CATCHES: node:net/dgram implementations that report refused connects, non-local binds
    (EADDRNOTAVAIL), EPIPE on a half-open unix socket, broadcast sends without SO_BROADCAST (EACCES)
    or oversized datagrams with different code/syscall/message shapes, lose data on unref'd sockets
    and servers, or accept invalid multicast group/source/interface arguments."""
    r = run(["-e", PROG_NET_ERRORS_UNREF], timeout=30)
    _check(r, "net_errors_unref")


PROG_UNCAUGHT_LISTEN_ERROR = r"""
const net = require("net");
require("fs").writeFileSync("taken", "a regular file, not a socket");
net.createServer().listen("taken", () => console.log("unexpected"));
setTimeout(() => console.log("loop still running after the unhandled 'error'"), 30);
"""


def test_unhandled_server_error_event_is_reported_not_fatal(run, workdir):
    """CATCHES: runtimes that crash (or stay silent) when a net.Server emits 'error' with no listener:
    the reference reports it as an uncaught promise error on stderr, keeps the event loop running
    and still exits 0."""
    r = run(["-e", PROG_UNCAUGHT_LISTEN_ERROR])
    assert r.returncode == 0
    assert r.stderr == b"Uncaught (in promise) Error: listen EADDRINUSE taken\n"
    assert r.stdout == b"loop still running after the unhandled 'error'\n"


# ---------------------------------------------------------------------------------------------
# bun:sqlite
# ---------------------------------------------------------------------------------------------

PROG_SQLITE_CODES = r"""
const { Database } = require("bun:sqlite");
const out = (...a) => console.log(...a);
const err = (label, f) => { try { const v = f(); out(label, "ok", JSON.stringify(v)); } catch (e) { out(label, e.name, e.code, e.errno, JSON.stringify(e.message)); } };
const db = new Database();
err("empty values", () => db.query("SELECT '' AS t, x'' AS b, zeroblob(0) AS z, typeof('') AS tt, typeof(x'') AS bt, length(x'') AS bl").get());
err("empty values arr", () => db.query("SELECT '' AS t, x'' AS b").values());
err("blob class", () => { const r = db.query("SELECT x'' AS b, x'00ff' AS c").get(); return [Object.prototype.toString.call(r.b), r.b.length, Array.from(r.c)]; });
err("named + positional", () => db.query("SELECT $a AS a, ? AS b, :c AS c, @d AS d").get({ $a: 1, ":c": 3, "@d": "four" }));
err("toobig", () => db.query("SELECT zeroblob(2000000000) AS z").get());
err("toobig randomblob", () => db.query("SELECT length(randomblob(2000000000)) AS n").get());
db.run("CREATE TABLE r (x)");
db.run("INSERT INTO r (rowid, x) VALUES (1, 'a')");
err("rowid", () => db.run("INSERT INTO r (rowid, x) VALUES (1, 'b')"));
err("rowid prepared", () => db.prepare("INSERT INTO r (rowid, x) VALUES (?, ?)").run(1, "c"));
const full = new Database();
full.run("PRAGMA max_page_count = 3");
full.run("CREATE TABLE f (v)");
err("full", () => { for (let i = 0; i < 100; i++) full.run("INSERT INTO f VALUES (randomblob(1000))"); });
err("full count", () => full.query("SELECT count(*) AS n FROM f").get());
db.run("CREATE TABLE l (v)"); db.run("INSERT INTO l VALUES (1), (2), (3)");
const it = db.query("SELECT v FROM l").iterate();
out("iterate first", JSON.stringify(it.next()));
err("locked", () => db.run("DROP TABLE l"));
it.return();
err("unlocked", () => db.run("DROP TABLE l"));
const src = new Database();
src.run("CREATE TABLE c (v TEXT)"); src.run("INSERT INTO c VALUES ('hello')");
const bytes = src.serialize();
const bad = Buffer.from(bytes); bad.fill(0xff, 4096, 4096 + 16);
err("corrupt", () => Database.deserialize(bad).query("SELECT * FROM c").all());
err("intact", () => Database.deserialize(bytes).query("SELECT * FROM c").all());
// A process-wide heap limit below current usage: every later SQLite allocation fails.
const keep = db.query("SELECT 6 * 7 AS v");
err("keep", () => keep.get());
err("hard_heap_limit", () => db.query("PRAGMA hard_heap_limit = 1").get());
err("nomem prepare", () => db.query("SELECT 1 AS x").get());
err("nomem cached", () => keep.get());
err("nomem exec", () => db.run("CREATE TABLE t (v)"));
err("nomem open memory", () => new Database());
err("nomem open file", () => new Database("x.db"));
out("x.db exists", require("fs").existsSync("x.db"));
"""

PROG_SQLITE_FILE_CODES = r"""
const { Database } = require("bun:sqlite");
const fs = require("fs");
const out = (...a) => console.log(...a);
const err = (label, f) => { try { const v = f(); out(label, "ok", JSON.stringify(v)); } catch (e) { out(label, e.name, e.code, e.errno, JSON.stringify(e.message)); } };
fs.mkdirSync("dir.db");
err("directory read-write", () => new Database("dir.db").query("SELECT * FROM sqlite_master").all());
err("directory read-only", () => new Database("dir.db", { readonly: true }).query("SELECT * FROM sqlite_master").all());
const mem = new Database();
err("vacuum into missing dir", () => mem.run("VACUUM INTO 'nope/x.db'"));
err("attach directory", () => mem.run("ATTACH 'dir.db' AS d"));
err("rtree constraint", () => { mem.run("CREATE VIRTUAL TABLE rt USING rtree(id, x0, x1)"); return mem.run("INSERT INTO rt VALUES (1, 5, 1)"); });
const moved = new Database("m.db"); moved.run("CREATE TABLE t (a)"); moved.run("INSERT INTO t VALUES (1)");
fs.renameSync("m.db", "moved.db");
err("write after rename", () => moved.run("INSERT INTO t VALUES (2)"));
err("read after rename", () => moved.query("SELECT count(*) AS n FROM t").get());
const gone = new Database("u.db"); gone.run("CREATE TABLE t (a)");
fs.unlinkSync("u.db");
err("write after unlink", () => gone.run("INSERT INTO t VALUES (2)"));
out("files", fs.readdirSync(".").sort().join(","));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_bun_sqlite_more_result_codes_and_nomem(run, workdir, tier):
    """CATCHES: bun:sqlite SQLiteError code/errno/message mapping gaps (TOOBIG, CONSTRAINT_ROWID, FULL,
    LOCKED, CORRUPT, NOMEM incl. failed opens), empty TEXT/BLOB column decoding, positional '?'
    parameters inside a named-dict binding, and cached statements surviving allocation failure."""
    _check(run([*tier, "-e", PROG_SQLITE_CODES]), "sqlite_codes")


def test_bun_sqlite_file_level_result_codes(run, workdir):
    """CATCHES: bun:sqlite mapping of file-level failures: a directory opened read-write (CANTOPEN) vs
    read-only (IOERR_READ 266), VACUUM INTO / ATTACH of unusable paths, plain SQLITE_CONSTRAINT from
    an rtree check, and writes after the database file was renamed or unlinked (errno 1032, which
    the reference names SQLITE_READONLY_RECOVERY)."""
    _check(run(["-e", PROG_SQLITE_FILE_CODES]), "sqlite_file_codes")


SQLITE_CUSTOM_MAIN = r"""
const fs = require("fs");
const cp = require("child_process");
const { Database } = require("bun:sqlite");
const out = (...a) => console.log(...a);
new Database().close(); // loads the system libsqlite3 so /proc/self/maps names it
const mapped = fs.readFileSync("/proc/self/maps", "utf8").split("\n").map((l) => l.trim().split(/\s+/)[5]).filter(Boolean);
fs.symlinkSync(mapped.find((p) => /\/libsqlite3\.so/.test(p)), "sq.so");
fs.symlinkSync(mapped.find((p) => /\/libc\.so/.test(p) || /\/libc-[0-9.]+\.so/.test(p)), "notsqlite.so");
fs.writeFileSync("junk.so", "this is not an ELF shared object\n".repeat(64));
for (const lib of ["./sq.so", "./notsqlite.so", "./junk.so", "./missing.so"]) {
  const r = cp.spawnSync(process.execPath, ["child.js", lib], { encoding: "utf8" });
  out(lib, "-> status", r.status, "stderr", JSON.stringify(r.stderr));
  for (const line of r.stdout.trim().split("\n")) out("   ", line);
}
"""

SQLITE_CUSTOM_CHILD = r"""
const { Database } = require("bun:sqlite");
const lib = process.argv[2];
try {
  console.log("setCustomSQLite returned", JSON.stringify(Database.setCustomSQLite(lib)));
  const db = new Database();
  console.log("opened", typeof db.query("SELECT sqlite_version() AS v").get().v, db.query("SELECT 6 * 7 AS x").get().x);
  try { Database.setCustomSQLite(lib); } catch (e) { console.log("again:", e.message); }
} catch (e) { console.log("error", e.name, e.message); }
"""


def test_bun_sqlite_set_custom_sqlite_library(run, workdir):
    """CATCHES: Database.setCustomSQLite that ignores the configured library (a real libsqlite3 via a
    relative symlink must load and work), or that reports different errors for a library lacking the
    sqlite3 symbols, a non-ELF file, or a missing path, or allows re-configuration after opening."""
    write_files(workdir, {"main.js": SQLITE_CUSTOM_MAIN, "child.js": SQLITE_CUSTOM_CHILD})
    _check(run(["main.js"], timeout=30), "sqlite_custom")


# ---------------------------------------------------------------------------------------------
# bun:ffi
# ---------------------------------------------------------------------------------------------

PROG_FFI_CALLBACKS = r"""
const { dlopen, ptr, CString, JSCallback, CFunction } = require("bun:ffi");
const out = (...a) => console.log(...a);
const show = (v) => JSON.stringify(v, (k, x) => (typeof x === "bigint" ? x + "n" : x));
const t = (label, f) => { try { out(label, show(f())); } catch (e) { out(label, "ERR", e.name, e.message); } };
// Callback argument decoding for every integer register class (fed one all-ones-ish u64 and 0).
for (const ty of ["i8", "u8", "i16", "u16", "u32", "bool", "u64", "char", "ptr", "i64", "u64_fast"]) {
  const seen = [];
  const cb = new JSCallback((x) => { seen.push(typeof x + ":" + String(x)); return 0; }, { args: [ty], returns: "i32" });
  const f = CFunction({ ptr: cb.ptr, args: ["u64"], returns: "i32" });
  f(0xffffffffffffff85n); f(0n);
  out("arg", ty, seen.join(" "));
  cb.close();
}
// Callback return encoding.
const rets = [
  ["ptr from number", () => 1234, "ptr", "u64"],
  ["ptr from string", () => "str", "ptr", "u64"],
  ["ptr from null", () => null, "ptr", "u64"],
  ["bool true", () => true, "i32", "i32"],
  ["bool false", () => false, "u8", "i32"],
  ["bigint", () => -5n, "i64", "i64"],
  ["float to int", () => 7.9, "i32", "i32"],
  ["string to int", () => "12", "i32", "i32"],
  ["undefined", () => undefined, "i32", "i32"],
];
for (const [label, fn, ret, read] of rets) {
  const cb = new JSCallback(fn, { args: [], returns: ret });
  t("ret " + label, () => CFunction({ ptr: cb.ptr, returns: read })());
  cb.close();
}
const typed = new JSCallback(() => new Uint8Array(4), { args: [], returns: "ptr" });
t("ret ptr from typed array", () => typeof CFunction({ ptr: typed.ptr, returns: "ptr" })());
typed.close();
const thrower = new JSCallback(() => { throw new RangeError("inside callback"); }, { args: [], returns: "i32" });
t("throwing callback returns", () => CFunction({ ptr: thrower.ptr, returns: "i32" })());
thrower.close();
const cb3 = new JSCallback((a, b, c) => a * 100 + b * 10 + c, { args: ["i32", "i32", "i32"], returns: "i32" });
const cf = CFunction({ ptr: cb3.ptr, args: ["i32", "i32", "i32"], returns: "i32" });
t("before close", () => cf(1, 2, 3));
cb3.close();
t("after close", () => cf(1, 2, 3));
t("ptr after close", () => cb3.ptr);
const pool = [];
const sig = { args: ["i32", "i32", "i32", "i32", "i32"], returns: "i32" };
t("pool", () => { for (let i = 0; i < 20; i++) pool.push(new JSCallback(() => i, sig)); });
t("pool size", () => pool.length);
t("other arity still free", () => { const c = new JSCallback(() => 5, { args: ["i32"], returns: "i32" }); const v = CFunction({ ptr: c.ptr, args: ["i32"], returns: "i32" })(0); c.close(); return v; });
for (const p of pool) p.close();
t("pool reuse after close", () => { const c = new JSCallback((a) => a + 1, sig); const v = CFunction({ ptr: c.ptr, ...sig })(41, 0, 0, 0, 0); c.close(); return v; });
const libc = dlopen("libc.so.6", { free: { args: ["ptr"], returns: "void" }, abs: { args: ["i32"], returns: 99 } });
t("free(true) passes NULL", () => libc.symbols.free(true));
t("unknown numeric return type", () => libc.symbols.abs(-5));
t("object type spec", () => dlopen("libc.so.6", { abs: { args: [{}], returns: "i32" } }));
t("tagged type spec", () => dlopen("libc.so.6", { abs: { args: [{ tag: "i32" }], returns: { tag: "i32" } } }).symbols.abs(-3));
t("CString of string", () => String(new CString("0")));
t("CString of true (NULL)", () => String(new CString(true)));
const odd = new JSCallback((x) => { out("  raw arg", typeof x, String(x)); return 1; }, { args: [99], returns: "i32" });
t("unknown numeric arg code", () => CFunction({ ptr: odd.ptr, args: ["u64"], returns: "i32" })(77n));
odd.close();
// A thunk entered from a foreign native thread has no engine to run on: it returns 0 untouched.
const threads = dlopen("libc.so.6", {
  pthread_create: { args: ["ptr", "ptr", "function", "ptr"], returns: "i32" },
  pthread_join: { args: ["u64", "ptr"], returns: "i32" },
});
let ranOnThread = false;
const start = new JSCallback(() => { ranOnThread = true; return 1234; }, { args: ["ptr"], returns: "ptr" });
const tid = new BigUint64Array(1), result = new BigUint64Array([99n]);
t("pthread_create", () => threads.symbols.pthread_create(ptr(tid), null, start.ptr, null));
t("pthread_join", () => threads.symbols.pthread_join(tid[0], ptr(result)));
t("foreign-thread result / JS ran", () => [result[0], ranOnThread]);
start.close();
threads.close();
libc.close();
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_bun_ffi_jscallback_marshalling(run, tier):
    """CATCHES: bun:ffi JSCallback thunks that decode i8/u8/i16/u16/u32/bool/u64/char/ptr/i64 arguments
    or pointer/bool/bigint/float/string returns differently, propagate (rather than report on stderr
    and return 0 for) exceptions thrown by the callback, crash when a closed callback's thunk is
    called or entered from a foreign pthread, or mis-handle the 16-slot per-arity callback pool and
    odd type specs."""
    r = run([*tier, "-e", PROG_FFI_CALLBACKS])
    _check(r, "ffi_callbacks", stderr=b"uncaught exception in bun:ffi JSCallback: RangeError: inside callback\n")


PROG_FFI_CC = r"""
const fs = require("fs");
const { cc, dlopen } = require("bun:ffi");
const out = (...a) => console.log(...a);
dlopen("libm.so.6", {}).close();
const libm = fs.readFileSync("/proc/self/maps", "utf8").split("\n").map((l) => l.trim().split(/\s+/)[5]).filter(Boolean).find((p) => /\/libm\.so/.test(p));
fs.writeFileSync("src.c", "double twice(double x) { return 2 * x; }\n");
// A stand-in compiler: log the argv it was given, then "produce" the library by copying libm.
fs.writeFileSync("fakecc", `#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; echo "arg: -o OUTPUT" >> args.log; shift; else echo "arg: $1" >> args.log; fi
  shift
done
cp "${libm}" "$out"
`);
fs.chmodSync("fakecc", 0o755);
const lib = cc({ source: "src.c", flags: ["-DX=1", "-Wall"], define: { FOO: "1", BAR: "" }, library: ["m"], symbols: { sqrt: { args: ["f64"], returns: "f64" }, floor: { args: ["f64"], returns: "f64" } } });
out("compiled library symbols", lib.symbols.sqrt(81), lib.symbols.floor(-2.5));
lib.close();
for (const line of fs.readFileSync("args.log", "utf8").trim().split("\n")) out(line);
const lib2 = cc({ source: new URL("file://" + process.cwd() + "/src.c"), flags: "-g", symbols: {} });
out("second compile", typeof lib2.close, JSON.stringify(Object.keys(lib2.symbols)));
lib2.close();
out("argv of second compile", fs.readFileSync("args.log", "utf8").trim().split("\n").slice(10).join(" | ").replace(/arg: \/\S+\/src\.c/, "arg: ABS/src.c"));
"""

PROG_FFI_CC_FAIL = r"""
const fs = require("fs");
const { cc } = require("bun:ffi");
fs.writeFileSync("src.c", "int x;\n");
fs.writeFileSync("badcc", "#!/bin/sh\necho 'src.c:1: error: nope' >&2\nexit 1\n");
fs.chmodSync("badcc", 0o755);
try { cc({ source: "src.c", symbols: {} }); } catch (e) { console.log("cc failed:", e.name, e.message); }
"""


def test_bun_ffi_cc_with_fake_compiler(run, workdir):
    """CATCHES: bun:ffi cc() drivers that pass a different compiler argv (-shared -fPIC -O2 source, then
    flags/defines/libraries, -o output), ignore $CC, accept URL sources or scalar flags differently,
    or do not dlopen the produced library and bind the requested symbols."""
    write_files(workdir, {"main.js": PROG_FFI_CC})
    _check(run(["main.js"], env_overrides={"CC": "./fakecc"}), "ffi_cc")
    assert sorted(p.name for p in workdir.iterdir()) == ["args.log", "fakecc", "main.js", "src.c"]


def test_bun_ffi_cc_all_compilers_fail(run, workdir):
    """CATCHES: cc() error reporting that drops the failing compiler's stderr or the per-candidate
    spawn errors: with $CC failing and no cc/clang on PATH the message must list all three attempts
    (and only cc/clang when $CC is unset)."""
    write_files(workdir, {"main.js": PROG_FFI_CC_FAIL})
    r = run(["main.js"], env_overrides={"CC": "./badcc", "PATH": "/nonexistent-lumen-test-dir"})
    _check(r, "ffi_cc_fail")
    r = run(["main.js"], env_overrides={"PATH": "/nonexistent-lumen-test-dir"})
    _check(r, "ffi_cc_fail_no_cc")


# ---------------------------------------------------------------------------------------------
# Lumen.upgradeWebSocket: server-side send()/close() driven by a raw client in the test process
# ---------------------------------------------------------------------------------------------
# The reference reader thread holds the socket lock while it blocks in read(), so a server-side
# send() only proceeds promptly while the reader is still working through already-buffered
# frames. The client therefore sends each scenario's frames in ONE write, and the server only
# sends/closes from handlers of messages that are followed by at least one more buffered frame.

def _masked_frame(op, payload=b"", fin=True):
    if isinstance(payload, str):
        payload = payload.encode()
    mask = b"\x11\x22\x33\x44"
    n = len(payload)
    b0 = (0x80 if fin else 0) | op
    head = bytes([b0, 0x80 | n]) if n < 126 else bytes([b0, 0x80 | 126]) + struct.pack(">H", n)
    return head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))


def _frames(sock, buf=b""):
    """Yield (fin, op, masked, payload) for each frame the server sends, until EOF."""
    while True:
        while len(buf) >= 2:
            n, off = buf[1] & 0x7F, 2
            if n == 126:
                if len(buf) < 4:
                    break
                n, off = struct.unpack(">H", buf[2:4])[0], 4
            elif n == 127:
                if len(buf) < 10:
                    break
                n, off = struct.unpack(">Q", buf[2:10])[0], 10
            masked = bool(buf[1] & 0x80)
            start = off + (4 if masked else 0)
            if len(buf) < start + n:
                break
            payload = buf[start:start + n]
            if masked:
                payload = bytes(c ^ buf[off + i % 4] for i, c in enumerate(payload))
            yield bool(buf[0] & 0x80), buf[0] & 0x0F, masked, payload
            buf = buf[start + n:]
        chunk = sock.recv(65536)
        if not chunk:
            return
        buf += chunk


def _describe_frame(fin, op, masked, payload):
    if op == 8:
        body = f"code={struct.unpack('>H', payload[:2])[0]} reason={payload[2:].decode()!r}" if len(payload) >= 2 else "(empty)"
    elif op == 1:
        text = payload.decode()
        body = f"text len={len(text)} first={text[:1]!r}" if len(text) > 40 else f"text {text!r}"
    else:
        body = "bytes " + ",".join(map(str, payload))
    return f"fin={int(fin)} op={op} masked={int(masked)} {body}"


def _wait_for_file(path, done, timeout=scaled(15)):
    """Poll for a marker file the program writes; give up once the program has exited."""
    deadline = time.monotonic() + timeout
    while not path.exists():
        if done.is_set() or time.monotonic() > deadline:
            return False
        time.sleep(0.005)
    return True


def _ws_session(port, path, batch, on_close, log):
    s = socket.create_connection(("127.0.0.1", port), timeout=scaled(15))
    try:
        key = base64.b64encode(path.encode().ljust(16, b"-")[:16]).decode()
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: test\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = s.recv(65536)
            if not chunk:
                log.append(f"{path} EOF during handshake")
                return
            head += chunk
        head, rest = head.split(b"\r\n\r\n", 1)
        log.append(f"{path} response head: " + " | ".join(head.decode().split("\r\n")))
        s.sendall(batch)
        for frame in _frames(s, rest):
            log.append(f"{path} " + _describe_frame(*frame))
            if frame[1] == 8:
                s.sendall(on_close)
        log.append(f"{path} EOF")
    finally:
        s.close()


PROG_WS_SERVER_SEND = r"""
import fs from "node:fs";
const L = (...a) => console.log(...a);
const guard = setTimeout(() => { L("timed out waiting for the client"); process.exit(3); }, 15000);
const logs = { "/a": [], "/b": [] };
let closed = 0;
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, (req) => {
  const path = new URL(req.url).pathname;
  const ws = Lumen.upgradeWebSocket(req);
  const log = (...a) => logs[path].push(a.join(" "));
  ws.onmessage = (data, isBinary) => {
    log("got", isBinary ? "binary " + Array.from(data).join(",") : JSON.stringify(data));
    if (data === "a1") {
      log("send text ->", ws.send("echo:a1"));
      log("send bytes ->", ws.send(new Uint8Array([1, 2, 3])));
      log("send 200 chars ->", ws.send("m".repeat(200)));
      log("send 70000 chars ->", ws.send("L".repeat(70000)));
      log("send number ->", ws.send(42));
    } else if (data === "a2") {
      ws.close(4002, "server bye");
      log("send after close() ->", ws.send("late"));
      ws.close(4003, "second close ignored");
    } else if (data === "a3") {
      log("send while closing ->", ws.send("still closing"));
    } else if (data === "b1") {
      ws.close(4005, "closing b");
    }
  };
  ws.onclose = (code, reason, clean) => {
    log("onclose", code, JSON.stringify(reason), clean);
    log("send after onclose ->", ws.send("x"));
    ws.close(4006, "after onclose");
    if (++closed === 2) finish();
  };
  return new Response("ignored after upgrade");
});
fs.writeFileSync("port.tmp", String(server.port));
fs.renameSync("port.tmp", "port.txt");
async function finish() {
  clearTimeout(guard);
  for (const p of ["/a", "/b"]) for (const line of logs[p]) L(p, line);
  await server.shutdown();
  L("server shut down");
}
"""


def test_websocket_server_side_send_and_close(run, workdir):
    """CATCHES: Lumen.upgradeWebSocket handles whose send() does not emit unmasked text/binary frames
    with 7-bit, 16-bit and 64-bit lengths, whose close() does not send the code/reason once (later
    sends return false, later closes are ignored), or that mishandle the peer's close echo or a
    protocol violation arriving after the server already sent its close frame."""
    write_files(workdir, {"t.mjs": PROG_WS_SERVER_SEND})
    log = []
    done = threading.Event()

    def client():
        if not _wait_for_file(workdir / "port.txt", done):
            return
        port = int((workdir / "port.txt").read_text())
        _ws_session(port, "/a", b"".join(_masked_frame(1, m) for m in ["a1", "a2", "a3", "pad"]),
                    _masked_frame(8, struct.pack(">H", 4002) + b"client echo"), log)
        _ws_session(port, "/b", _masked_frame(1, "b1") + _masked_frame(1, "pad"), _masked_frame(3, "bad op"), log)

    t = threading.Thread(target=client, daemon=True)
    t.start()
    r = run(["t.mjs"], timeout=30)
    done.set()
    t.join(10)
    _check(r, "ws_server_send")
    assert ("\n".join(log) + "\n").encode() == golden(__file__, "ws_server_send_client")


# ---------------------------------------------------------------------------------------------
# EventSource against a scripted peer that resets the connection (SO_LINGER 0 -> RST)
# ---------------------------------------------------------------------------------------------

class ResettingSsePeer:
    """Serves text/event-stream responses; '/reset' resets the first connection after one event."""

    def __init__(self, workdir):
        self.workdir = workdir
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]
        self.lock = threading.Lock()
        self.heads = []
        self.resets = 0
        threading.Thread(target=self._loop, daemon=True).start()

    def close(self):
        self.listener.close()

    def _loop(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(scaled(15))
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            head = data.split(b"\r\n\r\n")[0].decode()
            path = head.split(" ")[1]
            with self.lock:
                self.heads.append(" | ".join(line for line in head.split("\r\n") if not line.lower().startswith("host:")))
                first = path == "/reset" and self.resets == 0
                resetting = first or path in ("/close-then-reset", "/close-now")
                if resetting:
                    self.resets += 1
            ok = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n"
            if resetting:
                conn.sendall(ok + b"retry: 20\nid: 7\ndata: before reset\n\n")
                if path == "/close-then-reset":  # reset only once the client has called close()
                    deadline = time.monotonic() + scaled(10)
                    while not (self.workdir / "es-closed").exists() and time.monotonic() < deadline:
                        time.sleep(0.005)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            else:
                conn.sendall(ok + b"data: after reconnect\n\n")
        except OSError:
            return
        finally:
            conn.close()


PROG_SSE_RESET = r"""
import fs from "node:fs";
const L = (...a) => console.log(...a);
const port = process.argv[2];
await new Promise((resolve) => {
  const es = new EventSource(`http://127.0.0.1:${port}/reset`);
  es.onopen = () => L("reset: open", es.readyState);
  es.onerror = () => L("reset: error event, readyState", es.readyState);
  es.onmessage = (e) => {
    L("reset: message", JSON.stringify(e.data), "lastEventId", JSON.stringify(e.lastEventId));
    if (e.data === "after reconnect") { es.close(); L("reset: closed", es.readyState); setTimeout(resolve, 20); }
  };
});
await new Promise((resolve) => {
  const es = new EventSource(`http://127.0.0.1:${port}/close-then-reset`);
  es.onerror = () => L("close-then-reset: unexpected error event");
  es.onmessage = (e) => {
    L("close-then-reset: message", JSON.stringify(e.data));
    // Close while the next read is parked in the kernel; the peer resets only after that.
    setTimeout(() => { es.close(); L("close-then-reset: closed", es.readyState); fs.writeFileSync("es-closed", ""); setTimeout(resolve, 50); }, 30);
  };
});
await new Promise((resolve) => {
  const es = new EventSource(`http://127.0.0.1:${port}/close-now`);
  es.onerror = () => L("close-now: unexpected error event");
  es.onmessage = (e) => { L("close-now: message", JSON.stringify(e.data)); es.close(); setTimeout(resolve, 50); };
});
L("done");
"""


def test_eventsource_reconnects_after_connection_reset(run, workdir):
    """CATCHES: EventSource clients that treat a TCP reset as fatal (instead of an error event plus a
    reconnect carrying Last-Event-ID after the server's retry delay), lose the event that arrived
    before the reset, or still fire error events for a reset that follows close()."""
    peer = ResettingSsePeer(workdir)
    try:
        write_files(workdir, {"t.mjs": PROG_SSE_RESET})
        r = run(["t.mjs", str(peer.port)], timeout=30)
    finally:
        peer.close()
    _check(r, "sse_reset")
    with peer.lock:
        heads = ("\n".join(sorted(peer.heads)) + "\n").encode()
    assert heads == golden(__file__, "sse_reset_peer")


# ---------------------------------------------------------------------------------------------
# Smaller native paths: hashing, passwords, GCM IV handling, wasm export kinds, workers, children
# ---------------------------------------------------------------------------------------------

PROG_HASH_PASSWORD_EDGES = r"""
const out = (...a) => console.log(...a);
const pat = (n) => { const b = new Uint8Array(n); for (let i = 0; i < n; i++) b[i] = (i * 131 + 17) & 0xff; return b; };
// Inputs above 240 bytes take xxHash3's long (striped) path, where a non-zero seed derives a
// custom secret.
for (const n of [241, 300, 1024, 1025, 4096, 5000]) {
  out("xxHash3 seeded", n, [0n, 1n, 0xdeadbeefn, 2n ** 64n - 1n].map((s) => Bun.hash.xxHash3(pat(n), s).toString(16)).join(" "));
}
const P = Bun.password;
const h = P.hashSync("pw", { algorithm: "argon2id", memoryCost: 16, timeCost: 1 });
const noVersion = h.replace("$v=19$", "$");
out("argon2 without v= segment", noVersion.split("$").length, P.verifySync("pw", noVersion), P.verifySync("nope", noVersion));
const [, alg, ver, params, salt, hash] = h.split("$");
const cases = {
  "salt length 1 mod 4": `$${alg}$${ver}$${params}$abcde$${hash}`,
  "salt bad character": `$${alg}$${ver}$${params}$ab!d$${hash}`,
  "hash bad character": `$${alg}$${ver}$${params}$${salt}$${hash.slice(0, -1)}*`,
  "leading junk": `x$${alg}$${ver}$${params}$${salt}$${hash}`,
  "unknown version": `$${alg}$v=18$${params}$${salt}$${hash}`,
  "missing parts": `$${alg}$${ver}`,
  "non-numeric param": `$${alg}$${ver}$m=16,t=x,p=1$${salt}$${hash}`,
};
for (const [label, s] of Object.entries(cases)) {
  try { out(label, P.verifySync("pw", s)); } catch (e) { out(label, e.name, e.message); }
}
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_bun_hash_seeded_long_and_password_malformed_phc(run, tier):
    """CATCHES: xxHash3 long-input hashing that ignores the seed-derived secret (inputs > 240 bytes),
    argon2 verification that requires the optional v= segment, or malformed PHC strings (bad base64
    lengths/characters, junk prefix, unknown version, bad params) reported with different errors."""
    _check(run([*tier, "-e", PROG_HASH_PASSWORD_EDGES], timeout=30), "hash_password_edges")


PROG_GCM_IVS = r"""
const c = require("crypto");
const out = (...a) => console.log(...a);
const key = Buffer.alloc(16, 7);
const roundTrip = (label, iv, aad, pt) => {
  const ci = c.createCipheriv("aes-128-gcm", key, iv);
  if (aad) ci.setAAD(aad);
  const ct = Buffer.concat([ci.update(pt), ci.final()]);
  const tag = ci.getAuthTag();
  const d = c.createDecipheriv("aes-128-gcm", key, iv);
  if (aad) d.setAAD(aad);
  d.setAuthTag(tag);
  const back = Buffer.concat([d.update(ct), d.final()]).toString();
  out(label, iv.length, ct.toString("hex"), tag.toString("hex"), JSON.stringify(back));
};
// With this key, IV 00..0069 hashes to a J0 whose low byte is 0xff, so inc32(J0) carries.
roundTrip("8-byte iv, J0 low byte wraps", Buffer.from("0000000000000069", "hex"), null, Buffer.from("counter carry across a byte boundary!!"));
roundTrip("13-byte iv with aad", Buffer.from("000102030405060708090a0b0c", "hex"), Buffer.from("header"), Buffer.from("thirteen"));
roundTrip("1-byte iv, empty plaintext", Buffer.from([0x42]), null, Buffer.from(""));
roundTrip("16-byte iv", Buffer.alloc(16, 0xab), Buffer.from("aad"), Buffer.from("sixteen byte iv path"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_crypto_gcm_non_96_bit_ivs(run, tier):
    """CATCHES: AES-GCM implementations that only handle 12-byte IVs: J0 must be GHASH-derived (with
    zero padding) for 1/8/13/16-byte IVs, and inc32 must carry across the counter's low byte (in
    every engine tier, since the streaming GCTR/keystream glue runs in JS)."""
    _check(run([*tier, "-e", PROG_GCM_IVS]), "gcm_ivs")


PROG_WASM_EXPORT_KINDS = r"""
const out = (...a) => console.log(...a);
// (module (type (func)) (func) (table 1 funcref) (memory 1)
//   (global i32 (i32.const 42)) (global (mut i64) (i64.const 7))
//   (export "f" (func 0)) (export "t" (table 0)) (export "m" (memory 0))
//   (export "g" (global 0)) (export "h" (global 1)))
const bytes = new Uint8Array([0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,
  0x01, 0x04, 0x01, 0x60, 0x00, 0x00,
  0x03, 0x02, 0x01, 0x00,
  0x04, 0x04, 0x01, 0x70, 0x00, 0x01,
  0x05, 0x03, 0x01, 0x00, 0x01,
  0x06, 0x0b, 0x02, 0x7f, 0x00, 0x41, 0x2a, 0x0b, 0x7e, 0x01, 0x42, 0x07, 0x0b,
  0x07, 0x15, 0x05, 0x01, 0x66, 0x00, 0x00, 0x01, 0x74, 0x01, 0x00, 0x01, 0x6d, 0x02, 0x00, 0x01, 0x67, 0x03, 0x00, 0x01, 0x68, 0x03, 0x01,
  0x0a, 0x04, 0x01, 0x02, 0x00, 0x0b]);
const mod = new WebAssembly.Module(bytes);
out("exports", JSON.stringify(WebAssembly.Module.exports(mod)));
out("imports", JSON.stringify(WebAssembly.Module.imports(mod)));
const e = new WebAssembly.Instance(mod, {}).exports;
out("instances", typeof e.f, e.t instanceof WebAssembly.Table, e.m instanceof WebAssembly.Memory, e.g instanceof WebAssembly.Global, e.h instanceof WebAssembly.Global);
out("values", e.f(), e.g.value, typeof e.h.value, String(e.h.value), e.t.length, e.m.buffer.byteLength);
try { e.g.value = 5; out("set immutable accepted", e.g.value); } catch (er) { out("set immutable", er.name, er.message); }
out("grow", e.m.grow(1), e.m.buffer.byteLength, typeof e.t.get(0));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_wasm_module_export_kinds(run, tier):
    """CATCHES: WebAssembly.Module.exports() descriptors with wrong kind strings for table/memory/global
    exports, instance exports not wrapped as Table/Memory/Global objects, wrong i32/i64 global values,
    or immutable globals accepting writes."""
    _check(run([*tier, "-e", PROG_WASM_EXPORT_KINDS]), "wasm_export_kinds")


WORKER_REF_FILES = {
    "worker.js": r"""const { parentPort } = require("worker_threads");
parentPort.on("message", (m) => {
  parentPort.postMessage("echo " + m);
  if (m === "bye") parentPort.close();
});
// Unref the armed inbox, then re-ref it from a timer (outside any message dispatch).
parentPort.unref();
setTimeout(() => { parentPort.ref(); parentPort.postMessage("timer re-ref'd the port"); }, 20);
""",
    "worker2.js": r"""const { parentPort } = require("worker_threads");
const second = (m) => {
  parentPort.postMessage("second handler: " + m);
  parentPort.off("message", second); // no 'message' listener left: the worker may now exit
};
const first = (m) => {
  parentPort.off("message", first);
  parentPort.on("message", second);
  parentPort.postMessage("first handler: " + m);
};
parentPort.on("message", first);
""",
    "main.js": r"""const { Worker } = require("worker_threads");
const out = (...a) => console.log(...a);
const w = new Worker(__dirname + "/worker.js");
w.on("message", (m) => { out("main got", m); if (m.startsWith("timer")) w.postMessage("bye"); });
w.on("exit", (code) => {
  out("worker exited", code);
  const w2 = new Worker(__dirname + "/worker2.js");
  w2.on("message", (m) => { out("main got", m); if (m.startsWith("first")) w2.postMessage("b"); });
  w2.on("exit", (c2) => out("worker2 exited", c2));
  w2.postMessage("a");
});
""",
}


def test_worker_parent_port_ref_and_listener_toggling(run, workdir):
    """CATCHES: worker_threads parentPort ref semantics: unref()/ref() on an armed inbox, close() letting
    the worker exit, and swapping 'message' listeners (removing the last one releases the worker,
    adding one re-holds it) without losing or duplicating messages."""
    write_files(workdir, WORKER_REF_FILES)
    _check(run(["main.js"], timeout=30), "worker_ref")


PROG_CHILD_AND_FS_EDGES = r"""
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const net = require("net");
const out = (...a) => console.log(...a);
fs.writeFileSync("bad.js", Buffer.from('module.exports = "\xff\xfe";\n', "latin1"));
try { require("./bad.js"); out("loaded?!"); } catch (e) { out("require invalid UTF-8", e.name, e.code, e.message.replaceAll(process.cwd(), "CWD")); }
const p = os.getPriority();
out("setPriority to current", os.setPriority(p), os.getPriority() === p, os.setPriority(0, p));
try { const r = cp.spawnSync("pwd", [], { cwd: { toString() { return "sub"; } } }); out("cwd object", r.status, JSON.stringify(String(r.stdout).trim().split("/").pop())); } catch (e) { out("cwd object threw", e.name, e.message); }
try { cp.spawnSync("pwd", [], { cwd: 12345 }); out("cwd number ok?!"); } catch (e) { out("cwd number", e.name, e.code, e.message); }
const keep = setTimeout(() => out("keep-alive fired?!"), 30000);
const c = cp.spawn("sh", ["-c", "echo one; sleep 0.05; echo two; sleep 0.05; echo three"]);
c.unref();
let got = "";
c.stdout.on("data", (d) => (got += d));
const ended = new Promise((resolve) => c.stdout.on("end", resolve));
const exited = new Promise((resolve) => c.on("exit", resolve));
Promise.all([ended, exited]).then(([, code]) => {
  out("unref'd child stdout", JSON.stringify(got), "exit code", code);
  const server = net.createServer().listen("sock", () => {
    out("dirents", JSON.stringify(fs.readdirSync(".", { withFileTypes: true }).map((d) => [d.name, d.isFile(), d.isDirectory(), d.isSocket(), d.isSymbolicLink()]).sort()));
    server.close(() => clearTimeout(keep));
  });
});
"""


def test_child_unref_reads_cwd_coercion_and_dirent_kinds(run, workdir):
    """CATCHES: child_process unref() that drops stdout data read after unref, cwd options that are
    not string-coerced (objects) or that fail differently (numbers), os.setPriority success paths,
    module loads of invalid UTF-8 sources, and readdir withFileTypes on a unix socket entry."""
    (workdir / "sub").mkdir()
    _check(run(["-e", PROG_CHILD_AND_FS_EDGES], timeout=30), "child_fs_edges")


# ---------------------------------------------------------------------------------------------
# fetch: chunked response framing limits (raw node:net server in the same program)
# ---------------------------------------------------------------------------------------------

PROG_FETCH_CHUNK_LIMITS = r"""
import net from "node:net";
const L = (...a) => console.log(...a);
const replies = {
  "/over-limit": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2000001\r\n",
  "/at-limit-truncated": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n10\r\n0123456789abcdef\r\n1FFFFF0\r\n",
  "/bad-size": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n",
  "/extensions-and-trailer": "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5;name=val\r\nhello\r\n1\r\n!\r\n0\r\nX-Trailer: t\r\n\r\n",
};
const srv = net.createServer((sock) => {
  sock.on("error", () => {});
  let head = "";
  sock.on("data", (d) => {
    head += d;
    if (!head.includes("\r\n\r\n")) return;
    sock.end(replies[head.split(" ")[1]]);
  });
});
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
const port = srv.address().port;
for (const p of Object.keys(replies)) {
  try { const r = await fetch(`http://127.0.0.1:${port}${p}`); L(p, r.status, JSON.stringify(await r.text())); } catch (e) { L(p, e.name, e.message.replaceAll(String(port), "PORT")); }
}
srv.close();
"""


def test_fetch_chunked_body_limits(run, workdir):
    """CATCHES: fetch clients whose chunked decoder accepts a chunk that would push the body past the
    32 MiB cap (instead of failing before reading it), rejects a body of exactly the cap, or reports
    truncated/bad chunk sizes and chunk extensions/trailers differently."""
    write_files(workdir, {"t.mjs": PROG_FETCH_CHUNK_LIMITS})
    _check(run(["t.mjs"], timeout=30), "fetch_chunk_limits")


# ---------------------------------------------------------------------------------------------
# Lumen.serve: a client that resets its connection before the response is written
# ---------------------------------------------------------------------------------------------

PROG_SERVE_CLIENT_RESET = r"""
import fs from "node:fs";
const L = (...a) => console.log(...a);
const guard = setTimeout(() => { L("timed out"); process.exit(3); }, 15000);
const waitFor = async (file) => { while (!fs.existsSync(file)) await new Promise((r) => setTimeout(r, 5)); };
const server = Lumen.serve({ hostname: "127.0.0.1", port: 0 }, async (req) => {
  const path = new URL(req.url).pathname;
  L("handler", req.method, path);
  if (path === "/reset-me") {
    fs.writeFileSync("handler-started", "");
    await waitFor("client-reset");
    return new Response("x".repeat(50000)); // the write fails: the peer already reset
  }
  setTimeout(async () => { await server.shutdown(); clearTimeout(guard); L("server shut down"); }, 30);
  return new Response("still serving", { headers: { "x-after": "reset" } });
});
fs.writeFileSync("port.tmp", String(server.port));
fs.renameSync("port.tmp", "port.txt");
"""


def test_serve_survives_client_reset_before_response(run, workdir):
    """CATCHES: Lumen.serve implementations that crash, log, or stop accepting when writing a response
    to a client that already reset the connection, instead of silently dropping that response and
    serving the next request normally."""
    write_files(workdir, {"t.mjs": PROG_SERVE_CLIENT_RESET})
    seen = []
    done = threading.Event()

    def client():
        if not _wait_for_file(workdir / "port.txt", done):
            return
        port = int((workdir / "port.txt").read_text())
        a = socket.create_connection(("127.0.0.1", port), timeout=scaled(15))
        a.sendall(b"GET /reset-me HTTP/1.1\r\nHost: x\r\n\r\n")
        if not _wait_for_file(workdir / "handler-started", done):
            return
        a.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        a.close()
        (workdir / "client-reset").write_text("")
        b = socket.create_connection(("127.0.0.1", port), timeout=scaled(15))
        b.sendall(b"GET /after HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        data = b""
        while True:
            chunk = b.recv(65536)
            if not chunk:
                break
            data += chunk
        b.close()
        head, body = data.split(b"\r\n\r\n", 1)
        lines = head.decode().split("\r\n")
        seen.append(lines[0])
        seen.extend(sorted(line for line in lines[1:] if line.split(":")[0].lower() in ("x-after", "content-length", "content-type")))
        seen.append("body " + body.decode())

    t = threading.Thread(target=client, daemon=True)
    t.start()
    r = run(["t.mjs"], timeout=30)
    done.set()
    t.join(10)
    _check(r, "serve_client_reset")
    assert seen == ["HTTP/1.1 200 OK", "Content-Length: 13", "content-type: text/plain;charset=UTF-8", "x-after: reset", "body still serving"]


# ---------------------------------------------------------------------------------------------
# WebSocket client idling past its socket read timeout (scripted peer in the test process)
# ---------------------------------------------------------------------------------------------

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class EchoAfterIdlePeer:
    """Upgrades every connection; answers the first text frame with 'pong:<text>' then closes."""

    def __init__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]
        self.lock = threading.Lock()
        self.log = []
        threading.Thread(target=self._loop, daemon=True).start()

    def close(self):
        self.listener.close()

    def _loop(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(scaled(15))
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            head, rest = data.split(b"\r\n\r\n", 1)
            key = re.search(rb"(?im)^sec-websocket-key: *(.*?)\s*$", head).group(1)
            accept = base64.b64encode(hashlib.sha1(key + WS_GUID).digest())
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            for fin, op, masked, payload in _frames(conn, rest):
                with self.lock:
                    self.log.append(_describe_frame(fin, op, masked, payload))
                if op == 1:
                    conn.sendall(bytes([0x81, 5 + len(payload)]) + b"pong:" + payload
                                 + bytes([0x88, 5]) + struct.pack(">H", 1000) + b"bye")
                if op == 8:
                    return
        except OSError:
            return
        finally:
            conn.close()


PROG_WS_IDLE = r"""
const L = (...a) => console.log(...a);
const port = process.argv[2];
// Retry only while the opening handshake itself fails (the client's handshake read is short).
const connect = (attempts) => new Promise((resolve) => {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/idle`);
  ws.onopen = () => { ws.onclose = null; resolve(ws); };
  ws.onclose = () => (attempts > 1 ? connect(attempts - 1).then(resolve) : resolve(null));
});
const ws = await connect(8);
L("open", ws.readyState);
await new Promise((r) => setTimeout(r, 350)); // idle well past the reader's 100 ms socket timeout
L("still open after idling", ws.readyState);
ws.onmessage = (e) => L("message", JSON.stringify(e.data));
await new Promise((resolve) => {
  ws.onclose = (e) => { L("close", e.code, JSON.stringify(e.reason), e.wasClean, ws.readyState); resolve(); };
  ws.send("after idle");
});
"""


def test_websocket_client_survives_idle_read_timeouts(run, workdir):
    """CATCHES: WebSocket clients whose short socket read timeout tears down (or corrupts) an open but
    idle connection instead of retrying the read, so a message sent after a quiet period still gets
    its reply and the server's close is echoed with the same code."""
    peer = EchoAfterIdlePeer()
    try:
        write_files(workdir, {"t.mjs": PROG_WS_IDLE})
        r = run(["t.mjs", str(peer.port)], timeout=30)

        def close_echo_seen():
            with peer.lock:
                return any("op=8" in line for line in peer.log)

        # The client's close echo may still be in flight when the program exits.
        deadline = time.monotonic() + scaled(5)
        while b"close 1000" in r.stdout and not close_echo_seen() and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        peer.close()
    _check(r, "ws_idle")
    with peer.lock:
        assert peer.log == ["fin=1 op=1 masked=1 text 'after idle'", "fin=1 op=8 masked=1 code=1000 reason=''"]
