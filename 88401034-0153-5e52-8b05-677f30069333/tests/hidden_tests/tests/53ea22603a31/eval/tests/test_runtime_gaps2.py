"""Second-wave host-layer gaps: os priority/hostname, link-level fs time/ownership calls, fs error and
file-type mapping quirks, fd-based fs calls, bun:jsc microtask draining and GC hooks, rarer SQLite
result codes and custom-library loading, and WebAssembly i64/saturating ops, export kinds and binary
format corner cases."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

TRY = r'''
const tryIt = (label, f) => {
  try { const v = f(); console.log(label, v === undefined ? 'undefined' : JSON.stringify(v)); }
  catch (e) { console.log(label, e.name + ': ' + e.message, '|', e.code, e.syscall); }
};
'''


# ---- os / fs -----------------------------------------------------------------------------------

def test_os_hostname_and_priority_roundtrip(run, workdir):
    """CATCHES: os.hostname() not returning a stable non-empty string, os.getPriority() (no argument,
    pid 0 and the own pid) not returning the same integer nice value in [-20, 19], or os.setPriority()
    refusing to set the current value again (always permitted) or returning something other than
    undefined. Values are host-specific, so only shapes and consistency are asserted."""
    check_script(run, workdir, G, "os_hostname_priority", TRY + r'''
const os = require('os');
const h = os.hostname();
console.log('hostname', typeof h, h.length > 0, h === os.hostname(), h.trim() === h);
const p = os.getPriority();
console.log('priority', typeof p, Number.isInteger(p), p >= -20 && p <= 19, os.getPriority(0) === p, os.getPriority(process.pid) === p);
tryIt('setPriority(current)', () => os.setPriority(p));
tryIt('setPriority(0, current)', () => os.setPriority(0, os.getPriority(0)));
tryIt('unchanged', () => os.getPriority() === p);
''')


def test_fs_symlink_level_times_and_ownership(run, workdir):
    """CATCHES: fs.lutimesSync following the symlink (it must change the link's own times and leave the
    target's alone), lchownSync to the caller's own ids failing, missing paths not raising ENOENT with
    the reference's message/code/syscall ('lutime'/'lchown'), or NUL bytes in utimes/statfs paths not
    being rejected with 'path contains a NUL byte'."""
    check_script(run, workdir, G, "fs_symlink_times_ownership", TRY + r'''
const fs = require('fs');
fs.writeFileSync('target.txt', 'data');
fs.utimesSync('target.txt', 50, 60);
fs.symlinkSync('target.txt', 'link');
tryIt('lutimes', () => fs.lutimesSync('link', 1000, 2000));
const ls = fs.lstatSync('link'), ts = fs.statSync('target.txt');
console.log('link times', ls.atimeMs, ls.mtimeMs, 'target times', ts.atimeMs, ts.mtimeMs);
tryIt('lutimes-missing', () => fs.lutimesSync('nope', 1, 1));
tryIt('lchown-own', () => fs.lchownSync('link', process.getuid(), process.getgid()));
tryIt('lchown-missing', () => fs.lchownSync('nope', 0, 0));
tryIt('utimes-nul', () => fs.utimesSync('a\0b', 1, 1));
tryIt('statfs-nul', () => fs.statfsSync('a\0b'));
console.log('still a link', fs.lstatSync('link').isSymbolicLink(), fs.readlinkSync('link'));
''')


def test_fs_directory_and_device_error_mapping(run, workdir):
    """CATCHES: different error mapping for directory misuse (EISDIR texts for writeFile/unlink/open,
    'cannot read' with code EIO for readFileSync of a directory, EIO for copyFile of a directory, EISDIR
    for renaming a file over a directory), chmod of a missing file not raising ENOENT, and file-type
    classification of /dev/null. Pins reference quirks: mkdirSync(existingFile, {recursive: true})
    returns undefined instead of throwing EEXIST while mkdirSync(existingDir, {recursive: true})
    returns the path although nothing was created, and a character device is reported as neither file,
    directory, symlink, FIFO, block nor character device."""
    check_script(run, workdir, G, "fs_directory_device_errors", TRY + r'''
const fs = require('fs');
fs.writeFileSync('target.txt', 'data');
fs.mkdirSync('adir');
const dn = fs.lstatSync('/dev/null');
console.log('devnull', dn.isFile(), dn.isDirectory(), dn.isSymbolicLink(), dn.isCharacterDevice(), dn.isFIFO(), dn.isBlockDevice());
tryIt('mkdir-recursive-on-file', () => fs.mkdirSync('target.txt', { recursive: true }));
tryIt('mkdir-on-file', () => fs.mkdirSync('target.txt'));
tryIt('mkdir-recursive-existing-dir', () => fs.mkdirSync('adir', { recursive: true }));
tryIt('write-dir', () => fs.writeFileSync('adir', 'x'));
tryIt('unlink-dir', () => fs.unlinkSync('adir'));
tryIt('read-dir', () => fs.readFileSync('adir'));
tryIt('open-dir-write', () => fs.openSync('adir', 'w'));
tryIt('copy-dir', () => fs.copyFileSync('adir', 'b'));
tryIt('rename-file-over-dir', () => fs.renameSync('target.txt', 'adir'));
tryIt('chmod-missing', () => fs.chmodSync('nope', 0o644));
console.log('target intact', fs.readFileSync('target.txt', 'utf8'), fs.statSync('adir').isDirectory());
''')


def test_fs_classifies_unix_socket_entries(run, workdir):
    """CATCHES: readdirSync({withFileTypes: true}) / lstatSync mishandling a non-regular, non-directory
    entry (a unix-domain socket created by a listening net server): it must be listed, with every
    is*() predicate false in the reference (no isSocket() classification) and size 0, and closing the
    server must remove the socket file."""
    check_script(run, workdir, G, "fs_unix_socket_entry", r'''
const net = require('net'), fs = require('fs');
fs.writeFileSync('file.txt', 'x');
fs.mkdirSync('dir');
const srv = net.createServer().listen('sock', () => {
  const ents = fs.readdirSync('.', { withFileTypes: true }).filter((d) => !d.name.endsWith('.js')).sort((a, b) => a.name < b.name ? -1 : 1);
  for (const d of ents) console.log(d.name, d.isFile(), d.isDirectory(), d.isSymbolicLink(), d.isSocket(), d.isFIFO());
  const st = fs.lstatSync('sock');
  console.log('lstat sock', st.isFile(), st.isDirectory(), st.isSocket(), st.isFIFO(), st.size);
  srv.close(() => console.log('closed; socket file still present:', fs.existsSync('sock')));
});
''')


def test_fs_fd_level_calls(run, workdir):
    """CATCHES: fd-based fs calls diverging: openSync without flags not opening read-only, readSync with
    length 0 not returning 0 or with a position not reading from it, fchownSync to the caller's own ids
    failing, fstatSync of a directory/character-device fd misclassifying it, writeSync of a string not
    returning the byte count (a number is rejected with the reference's TypeError), ftruncateSync with a
    negative length truncating to 0, and futimesSync not setting mtime; the file's final contents are
    checked too."""
    r = check_script(run, workdir, G, "fs_fd_level_calls", TRY + r'''
const fs = require('fs');
fs.writeFileSync('a.txt', 'hello world');
fs.mkdirSync('d');
const fd = fs.openSync('a.txt');
tryIt('read-zero', () => fs.readSync(fd, Buffer.alloc(4), 0, 0, 0));
const b = Buffer.alloc(5);
tryIt('read-pos', () => [fs.readSync(fd, b, 0, 5, 6), b.toString()]);
tryIt('write-readonly', () => fs.writeSync(fd, 'x'));
tryIt('fchown-own', () => fs.fchownSync(fd, process.getuid(), process.getgid()));
fs.closeSync(fd);
const dfd = fs.openSync('d', 'r');
tryIt('fstat-dir', () => { const s = fs.fstatSync(dfd); return [s.isDirectory(), s.isFile()]; });
fs.closeSync(dfd);
const nfd = fs.openSync('/dev/null', 'r');
tryIt('fstat-devnull', () => { const s = fs.fstatSync(nfd); return [s.isDirectory(), s.isFile(), s.isCharacterDevice()]; });
fs.closeSync(nfd);
const wfd = fs.openSync('w.txt', 'w+');
tryIt('write-str', () => fs.writeSync(wfd, 'abcdef'));
tryIt('write-num', () => fs.writeSync(wfd, 12345));
tryIt('ftruncate-3', () => fs.ftruncateSync(wfd, 3));
tryIt('size-3', () => fs.fstatSync(wfd).size);
tryIt('write-pos', () => fs.writeSync(wfd, 'XY', 1));
tryIt('futimes', () => fs.futimesSync(wfd, 100, 200));
tryIt('mtime', () => fs.fstatSync(wfd).mtimeMs);
fs.closeSync(wfd);
console.log('w.txt', JSON.stringify(fs.readFileSync('w.txt', 'utf8')));
const tfd = fs.openSync('t.txt', 'w');
fs.writeSync(tfd, 'gone');
tryIt('ftruncate-negative', () => fs.ftruncateSync(tfd, -5));
fs.closeSync(tfd);
console.log('t.txt size', fs.statSync('t.txt').size);
''')
    assert (workdir / "w.txt").read_bytes() == b"aXY"
    assert (workdir / "t.txt").read_bytes() == b""
    assert r.returncode == 0


# ---- bun:jsc -----------------------------------------------------------------------------------

def test_bun_jsc_drain_microtasks_and_gc_hooks(run, workdir):
    """CATCHES: bun:jsc drainMicrotasks() not running queued promise jobs and queueMicrotask callbacks
    synchronously at the call site (in FIFO order, including jobs they enqueue) while leaving
    process.nextTick callbacks for later; Bun.gc/shrink and jsc fullGC/edenGC/gcAndSweep not returning
    non-negative integer counts; heapStats()/memoryUsage() key sets; or a forced GC after dropping
    cyclic garbage not lowering heapStats().objectCount."""
    check_script(run, workdir, G, "bun_jsc_drain_gc", r'''
const jsc = require('bun:jsc');
const order = [];
Promise.resolve().then(() => order.push('then-1')).then(() => order.push('then-2'));
queueMicrotask(() => order.push('qm'));
process.nextTick(() => order.push('tick'));
order.push('before-drain');
jsc.drainMicrotasks();
order.push('after-drain');
setTimeout(() => console.log('order', order.join(' ')), 0);
const counts = [Bun.gc(true), jsc.fullGC(), jsc.edenGC(), jsc.gcAndSweep(), Bun.shrink()];
console.log('gc counts', counts.map((n) => typeof n + ':' + (Number.isInteger(n) && n >= 0)).join(' '));
const hs = jsc.heapStats();
console.log('heapStats', Object.keys(hs).join(','), hs.objectCount > 0, hs.heapSize === hs.objectCount * 128);
let junk = [];
for (let i = 0; i < 200; i++) { const a = { i }; const b = { a }; a.b = b; junk.push(a); }
const before = jsc.heapStats().objectCount;
junk = null;
Bun.gc(true);
console.log('objectCount dropped', jsc.heapStats().objectCount < before);
const mu = jsc.memoryUsage();
console.log('memoryUsage', Object.keys(mu).join(','), mu.peak >= mu.current, Number.isInteger(mu.pageFaults));
''')


# ---- bun:sqlite --------------------------------------------------------------------------------

SQL_PRELUDE = r'''
const { Database, constants } = require("bun:sqlite");
const show = (v) => JSON.stringify(v, (k, x) => typeof x === "bigint" ? x + "n" : x instanceof Uint8Array ? "u8:" + Array.from(x).join(",") : x);
const fail = (label, f) => {
  try { console.log(label, "ok", show(f())); }
  catch (e) { console.log(label, e.constructor.name, e.name, e.code, e.errno, "|", e.message); }
};
'''


def test_sqlite_rowid_locked_full_codes(run, workdir):
    """CATCHES: SQLiteError codes/errnos for less common failures: a duplicate explicit rowid on a table
    without INTEGER PRIMARY KEY must be SQLITE_CONSTRAINT_ROWID (2579, not PRIMARYKEY), dropping a table
    while iterating it SQLITE_LOCKED (6) 'database table is locked', exceeding max_page_count
    SQLITE_FULL (13) 'database or disk is full'; also that the failed statements leave the data intact
    and that a deserialized garbage image only fails once a page is actually read (SQLITE_NOTADB)."""
    check_script(run, workdir, G, "sqlite_rowid_locked_full", SQL_PRELUDE + r'''
const db = new Database();
db.run("CREATE TABLE r (x)");
db.run("INSERT INTO r(rowid, x) VALUES (1, 'a')");
fail("rowid-dup", () => db.run("INSERT INTO r(rowid, x) VALUES (1, 'b')"));
fail("rowid-after", () => db.query("SELECT rowid, x FROM r").all());
db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, v)");
db.run("INSERT INTO t VALUES (1, 'one'), (2, 'two'), (3, 'three')");
fail("locked", () => { const seen = []; for (const row of db.query("SELECT * FROM t").iterate()) { seen.push(row.id); db.run("DROP TABLE t"); } return seen; });
fail("table-survives", () => db.query("SELECT count(*) AS n FROM t").get());
const small = new Database();
small.run("PRAGMA max_page_count = 2");
fail("full", () => { small.run("CREATE TABLE big (b)"); small.run("INSERT INTO big VALUES (zeroblob(100000))"); });
fail("full-after", () => small.query("SELECT count(*) AS n FROM big").get());
fail("garbage-image-select-1", () => new Database(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8])).query("SELECT 1 AS one").all());
fail("garbage-image-master", () => Database.deserialize(Buffer.from("SQLite format 3\0garbage garbage garbage")).query("SELECT * FROM sqlite_master").all());
''')


def test_sqlite_custom_library_load_failure(run, workdir):
    """CATCHES: Database.setCustomSQLite accepting an existing non-library file before any database is
    open (it returns undefined, may be called again) but then every Database construction failing with
    'bun:sqlite unavailable: could not load custom libsqlite3 '<path>' (<dlopen error>)' -- an ELF-less
    text file gives the dynamic loader's 'invalid ELF header' -- instead of silently using the system
    library."""
    write_files(workdir, {"fake-sqlite.so": "this is not a shared library, just text long enough for an ELF header check\n"})
    check_script(run, workdir, G, "sqlite_custom_library_failure", r'''
const { Database } = require("bun:sqlite");
const fail = (label, f) => { try { console.log(label, "ok", String(f())); } catch (e) { console.log(label, e.constructor.name, e.code, "|", e.message); } };
fail("set-custom", () => Database.setCustomSQLite("./fake-sqlite.so"));
fail("open-memory", () => new Database());
fail("open-again", () => new Database(":memory:"));
fail("set-again", () => Database.setCustomSQLite("./fake-sqlite.so"));
''')


def test_sqlite_corrupt_image_and_heap_limit(run, workdir):
    """CATCHES: a corrupted serialized image (an invalid b-tree page type byte on the table's root page) not
    failing on first read with SQLITE_CORRUPT (11) 'database disk image is malformed' while the intact
    image round-trips its rows, or an allocation beyond `PRAGMA hard_heap_limit` not surfacing as
    SQLITE_NOMEM (7) 'out of memory'."""
    check_script(run, workdir, G, "sqlite_corrupt_and_nomem", SQL_PRELUDE + r'''
const db = new Database();
db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)");
for (let i = 0; i < 5; i++) db.run("INSERT INTO t (v) VALUES (?)", ["row " + i]);
const img = db.serialize();
console.log("image", img.length, img[4096]);
fail("intact", () => new Database(Uint8Array.from(img)).query("SELECT id, v FROM t WHERE id > 3").all());
const badType = Uint8Array.from(img);
badType[4096] = 0;
fail("corrupt-page-type", () => new Database(badType).query("SELECT * FROM t").all());
fail("original-untouched", () => db.query("SELECT count(*) AS n FROM t").get());
const m = new Database();
fail("hard-heap-limit", () => { m.run("PRAGMA hard_heap_limit = 200000"); return m.query("SELECT length(randomblob(5000000)) AS n").get(); });
''')


# ---- WebAssembly -------------------------------------------------------------------------------

WASM_HELPERS = r'''
const U = (n) => { const o = []; do { let b = n & 0x7f; n >>>= 7; if (n) b |= 0x80; o.push(b); } while (n); return o; };
const S = (v) => { let n = BigInt(v); const o = []; for (;;) { const b = Number(n & 0x7fn); n >>= 7n; if ((n === 0n && !(b & 0x40)) || (n === -1n && (b & 0x40))) { o.push(b); return o; } o.push(b | 0x80); } };
const STR = (s) => { const b = [...new TextEncoder().encode(s)]; return [...U(b.length), ...b]; };
const VEC = (items) => [...U(items.length), ...items.flat()];
const sec = (id, items) => { const c = VEC(items); return [id, ...U(c.length), ...c]; };
const HDR = [0x00, 0x61, 0x73, 0x6d, 1, 0, 0, 0];
const I32 = 0x7f, I64 = 0x7e, F32 = 0x7d, F64 = 0x7c, EXTERN = 0x6f, FUNCREF = 0x70;
const fn = (params, results) => [0x60, ...VEC(params.map((p) => [p])), ...VEC(results.map((r) => [r]))];
const body = (locals, code) => { const b = [...VEC(locals.map(([n, t]) => [...U(n), t])), ...code, 0x0b]; return [...U(b.length), ...b]; };
const exp = (name, kind, idx) => [...STR(name), kind, ...U(idx)];
'''


def test_wasm_i64_ops_saturation_and_export_kinds(run, workdir):
    """CATCHES: wrong i64 signed/unsigned comparisons (gt_s, le_s, ge_u), i64.rem_u treating operands as
    signed, wrong i64 and/or/xor, i32.trunc_sat_f32_u / i64.trunc_sat_f64_s not saturating (negative to
    0, huge to max, NaN to 0, i64 limits as exact BigInts), f32/f64/externref locals not defaulting to
    zero/null, externref parameters rejecting arbitrary JS values, i64.store/i32.load16_u little-endian
    layout, memory.grow beyond 65536 pages not returning -1, Module.exports kinds for table/memory/
    global. Pins a reference quirk: exported globals are read-only from JS even when declared mutable."""
    check_script(run, workdir, G, "wasm_i64_saturation_exports", WASM_HELPERS + r'''
const types = [fn([I64, I64], [I32]), fn([I64, I64], [I64]), fn([F32], [I32]), fn([F64], [I64]), fn([], [F64]),
               fn([EXTERN], [I32]), fn([I32], [I32]), fn([], [I32])];
const funcs = [
  [0, body([], [0x20, 0, 0x20, 1, 0x55])],                                    // i64.gt_s
  [0, body([], [0x20, 0, 0x20, 1, 0x57])],                                    // i64.le_s
  [0, body([], [0x20, 0, 0x20, 1, 0x5a])],                                    // i64.ge_u
  [1, body([], [0x20, 0, 0x20, 1, 0x82])],                                    // i64.rem_u
  [1, body([], [0x20, 0, 0x20, 1, 0x83, 0x20, 1, 0x84, 0x20, 0, 0x85])],      // ((a & b) | b) ^ a
  [2, body([], [0x20, 0, 0xfc, 1])],                                          // i32.trunc_sat_f32_u
  [3, body([], [0x20, 0, 0xfc, 6])],                                          // i64.trunc_sat_f64_s
  [4, body([[1, F32], [1, F64]], [0x01, 0x20, 0, 0xbb, 0x20, 1, 0xa0])],      // promote(f32 local) + f64 local
  [5, body([[1, EXTERN], [2, I32]], [0x01, 0x20, 2, 0x41, 9, 0x6a])],         // externref param/local, i32 local + 9
  [6, body([], [0x41, 0, 0x20, 0, 0xad, 0x37, 3, 0, 0x41, 0, 0x2f, 1, 0, 0x41, 2, 0x2f, 1, 0, 0x6a, 0x41, 4, 0x28, 2, 0, 0x6a])],
  [7, body([], [0x41, ...S(70000), 0x40, 0])],                                // memory.grow 70000
];
const names = ['gt_s', 'le_s', 'ge_u', 'rem_u', 'bits', 'sat_f32_u', 'sat_f64_s', 'zero_locals', 'ext', 'store_load16', 'grow_huge'];
const bytes = new Uint8Array([...HDR,
  ...sec(1, types), ...sec(3, funcs.map((f) => U(f[0]))), ...sec(4, [[FUNCREF, 0, 2]]), ...sec(5, [[0, 1]]),
  ...sec(6, [[F64, 0, 0x44, ...new Uint8Array(new Float64Array([2.5]).buffer), 0x0b], [I32, 1, 0x41, 7, 0x0b]]),
  ...sec(7, [...names.map((n, i) => exp(n, 0, i)), exp('tbl', 1, 0), exp('mem', 2, 0), exp('g', 3, 0), exp('mg', 3, 1)]),
  ...sec(10, funcs.map((f) => f[1]))]);
console.log('valid', WebAssembly.validate(bytes));
const mod = new WebAssembly.Module(bytes);
console.log(WebAssembly.Module.exports(mod).map((e) => e.name + ':' + e.kind).join(' '));
const { exports: e } = new WebAssembly.Instance(mod);
console.log('cmp', e.gt_s(-1n, -2n), e.gt_s(-2n, -1n), e.le_s(5n, 5n), e.le_s(6n, 5n), e.ge_u(-1n, 1n), e.ge_u(1n, -1n));
const r = [e.rem_u(-1n, 10n), e.rem_u(17n, 5n), e.bits(0b1100n, 0b1010n)];
console.log('i64', r.map((x) => typeof x + ':' + x).join(' '));
console.log('sat_f32_u', e.sat_f32_u(-5), e.sat_f32_u(1e20), e.sat_f32_u(NaN), e.sat_f32_u(3.9));
console.log('sat_f64_s', String(e.sat_f64_s(-1e300)), String(e.sat_f64_s(1e300)), String(e.sat_f64_s(NaN)), String(e.sat_f64_s(-7.9)));
console.log('locals', e.zero_locals(), e.ext(null), e.ext({ any: 'object' }), e.ext(undefined), e.ext('str'));
console.log('memory', e.store_load16(0x12345678), e.grow_huge(), e.mem.buffer.byteLength);
console.log('globals', e.g.value, e.mg.value, e.tbl.length, e.tbl.get(0));
for (const [label, g] of [['immutable', e.g], ['mutable', e.mg]]) {
  try { g.value = 1; console.log(label, 'set ok', g.value); } catch (err) { console.log(label, err.name + ': ' + err.message, g.value); }
}
''')


def test_wasm_binary_format_corners(run, workdir):
    """CATCHES: the binary decoder's handling of a DataCount section (the reference orders sections by
    numeric id, so DataCount in its spec position before Data is rejected with 'sections out of order'
    while one after Data is accepted), passive data segments being copied into memory at
    instantiation, an unknown data segment kind not failing as 'unsupported data segment kind 3',
    over-long unsigned and signed LEB128 immediates not failing as 'LEB128 overflow', and externref
    globals initialised by ref.null reading back as null; validate() must agree with compilation."""
    check_script(run, workdir, G, "wasm_binary_format_corners", WASM_HELPERS + r'''
const tryMod = (label, bytes) => {
  const u8 = new Uint8Array(bytes);
  try { const m = new WebAssembly.Module(u8); console.log(label, 'ok', WebAssembly.validate(u8), JSON.stringify(WebAssembly.Module.exports(m))); return m; }
  catch (e) { console.log(label, e.name + ': ' + e.message, WebAssembly.validate(u8), e instanceof WebAssembly.CompileError); }
};
const mem = [5, 3, 1, 0, 1];
const passiveData = [11, 6, 1, 1, 3, 0x61, 0x62, 0x63];
tryMod('datacount-before-data', [...HDR, ...mem, 12, 1, 1, ...passiveData]);
const m = tryMod('datacount-after-data', [...HDR, ...mem, 7, 5, 1, 1, 0x6d, 2, 0, ...passiveData, 12, 1, 1]);
const inst = new WebAssembly.Instance(m);
console.log('passive not copied', Array.from(new Uint8Array(inst.exports.m.buffer, 0, 4)).join(','), inst.exports.m.buffer.byteLength);
tryMod('bad-data-kind', [...HDR, ...mem, 11, 4, 1, 3, 0, 0]);
tryMod('uleb-overflow', [...HDR, 1, 11, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01]);
tryMod('sleb-overflow', [...HDR, 6, 16, 1, I64, 0, 0x42, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01, 0x0b]);
const g = tryMod('externref-global', [...HDR, 6, 6, 1, EXTERN, 0, 0xd0, EXTERN, 0x0b, 7, 5, 1, 1, 0x72, 3, 0]);
console.log('externref value', String(new WebAssembly.Instance(g).exports.r.value));
''')
