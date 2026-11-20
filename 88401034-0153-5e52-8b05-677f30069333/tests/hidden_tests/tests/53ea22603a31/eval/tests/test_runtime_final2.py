"""Final runtime gap pass (data-processing natives): WebAssembly float<->int conversions and traps of
the interpreter (which does not validate function bodies), host-import multi-value results,
bun:sqlite statements that outlive their database, and crafted Brotli streams exercising decoder
corners (metadata blocks, block-type switching, static-dictionary transforms) and its error
messages."""

from conftest import check_script, resources_for

G = resources_for(__file__)

WASM_HELPERS = r'''
const U = (n) => { const o = []; do { let b = n & 0x7f; n >>>= 7; if (n) b |= 0x80; o.push(b); } while (n); return o; };
const STR = (s) => { const b = [...new TextEncoder().encode(s)]; return [...U(b.length), ...b]; };
const VEC = (items) => [...U(items.length), ...items.flat()];
const sec = (id, items) => { const c = VEC(items); return [id, ...U(c.length), ...c]; };
const HDR = [0x00, 0x61, 0x73, 0x6d, 1, 0, 0, 0];
const I32 = 0x7f, I64 = 0x7e, F32 = 0x7d, F64 = 0x7c;
const fn = (params, results) => [0x60, ...VEC(params.map((p) => [p])), ...VEC(results.map((r) => [r]))];
const body = (locals, code) => { const b = [...VEC(locals.map(([n, t]) => [...U(n), t])), ...code, 0x0b]; return [...U(b.length), ...b]; };
const exp = (name, kind, idx) => [...STR(name), kind, ...U(idx)];
const show = (label, f) => {
  try { const v = f(); console.log(label, typeof v === 'bigint' ? v + 'n' : Object.is(v, -0) ? '-0' : String(v)); }
  catch (e) { console.log(label, e.name + ': ' + e.message, e instanceof WebAssembly.RuntimeError); }
};
'''


def test_wasm_float_int_conversions_saturate_instead_of_trapping(run, workdir):
    """CATCHES: wrong results for i32.trunc_f32_s/u and i64.trunc_f64_u on in-range values (toward-zero
    truncation, -0.5 -> 0), f32.convert_i32_s not rounding to nearest-even float (16777217 ->
    16777216, 2147483647 -> 2147483648), or f32.reinterpret_i32 / i32.reinterpret_f32 not
    round-tripping NaN payloads and infinity bit patterns. Pins a reference deviation from the spec:
    the non-saturating truncations do NOT trap on NaN/overflow but saturate (NaN -> 0, too large ->
    max, negative -> 0 for unsigned), with i64 results as BigInts wrapping into the signed range."""
    check_script(run, workdir, G, "wasm_float_int_conversions", WASM_HELPERS + r'''
const types = [fn([F32], [I32]), fn([F64], [I64]), fn([I32], [F32]), fn([I32], [I32])];
const funcs = [
  [0, body([], [0x20, 0, 0xa8])],        // i32.trunc_f32_s
  [0, body([], [0x20, 0, 0xa9])],        // i32.trunc_f32_u
  [1, body([], [0x20, 0, 0xb1])],        // i64.trunc_f64_u
  [2, body([], [0x20, 0, 0xb2])],        // f32.convert_i32_s
  [3, body([], [0x20, 0, 0xbe, 0xbc])],  // i32.reinterpret_f32(f32.reinterpret_i32(x))
];
const names = ['trunc_f32_s', 'trunc_f32_u', 'trunc_f64_u', 'convert_i32_s', 'reinterpret'];
const bytes = new Uint8Array([...HDR, ...sec(1, types), ...sec(3, funcs.map((f) => U(f[0]))),
  ...sec(7, names.map((n, i) => exp(n, 0, i))), ...sec(10, funcs.map((f) => f[1]))]);
console.log('valid', WebAssembly.validate(bytes));
const { exports: e } = new WebAssembly.Instance(new WebAssembly.Module(bytes));
for (const x of [3.9, -3.9, -0.5, 2147483648, -2147483649, NaN, Infinity, -Infinity]) show('i32.trunc_f32_s ' + x, () => e.trunc_f32_s(x));
for (const x of [3.9, -1, 4294967296, NaN, 1e10]) show('i32.trunc_f32_u ' + x, () => e.trunc_f32_u(x));
for (const x of [12345.678, 1e19, -1, 2 ** 64, NaN]) show('i64.trunc_f64_u ' + x, () => e.trunc_f64_u(x));
for (const x of [0, 16777217, -16777217, 2147483647, -2147483648]) show('f32.convert_i32_s ' + x, () => e.convert_i32_s(x));
for (const x of [0x7fc00001, 0x7f800000, -1, 1, 0x3f800000]) show('reinterpret ' + x, () => e.reinterpret(x));
''')


def test_wasm_unvalidated_bodies_traps_and_host_results(run, workdir):
    """CATCHES: i64.div_s/div_u by zero not trapping with RuntimeError 'wasm: integer divide by zero'
    (and INT64_MIN / -1 with 'wasm: integer overflow'), a `br` deeper than the control stack not
    trapping with 'wasm: branch depth out of range', data.drop not failing as 'wasm: unsupported 0xfc
    op 9', a zero-length code body ('unexpected end of input') or one whose declared size overruns
    the section ('bad code body') not being CompileErrors, and host imports with two results not
    taking the first two array elements (missing ones read as 0, non-arrays as [0, 0]). Pins that
    the reference does not validate function bodies: validate() accepts a stray `end` (execution
    stops there) and an `else` without `if` (ignored)."""
    check_script(run, workdir, G, "wasm_unvalidated_bodies_and_traps", WASM_HELPERS + r'''
const types = [fn([], [I32, I32]), fn([], [I32]), fn([I64, I64], [I64])];
const funcs = [
  [2, body([], [0x20, 0, 0x20, 1, 0x7f])],                    // i64.div_s
  [2, body([], [0x20, 0, 0x20, 1, 0x80])],                    // i64.div_u
  [1, body([], [0xfc, 9, 0, 0x41, 5])],                       // data.drop 0; i32.const 5
  [1, body([], [0x41, 7, 0x0b, 0x41, 9])],                    // i32.const 7; end; i32.const 9
  [1, body([], [0x41, 1, 0x05, 0x41, 2, 0x0b, 0x41, 3])],     // i32.const 1; else; i32.const 2; end; ...
  [1, body([], [0x02, 0x40, 0x0c, 3, 0x0b, 0x41, 1])],        // block; br 3; end
  [1, body([], [0x10, 0, 0x6a])],                             // call $pair; i32.add
];
const names = ['div_s', 'div_u', 'data_drop', 'stray_end', 'else_without_if', 'br_too_deep', 'sum_pair'];
const imp = [...STR('env'), ...STR('pair'), 0, 0];
const bytes = new Uint8Array([...HDR, ...sec(1, types), ...sec(2, [imp]), ...sec(3, funcs.map((f) => U(f[0]))),
  ...sec(5, [[0, 1]]), ...sec(7, [...names.map((n, i) => exp(n, 0, i + 1)), exp('pair', 0, 0)]),
  ...sec(10, funcs.map((f) => f[1])), ...sec(11, [[1, 2, 0x68, 0x69]])]);
console.log('valid', WebAssembly.validate(bytes));
let ret;
const { exports: e } = new WebAssembly.Instance(new WebAssembly.Module(bytes), { env: { pair: () => ret } });
show('div_s -7/2', () => e.div_s(-7n, 2n));
show('div_s by zero', () => e.div_s(1n, 0n));
show('div_u by zero', () => e.div_u(1n, 0n));
show('div_s overflow', () => e.div_s(-(2n ** 63n), -1n));
for (const n of ['data_drop', 'stray_end', 'else_without_if', 'br_too_deep']) show(n, () => e[n]());
for (const r of [[20, 22], [5], [1, 2, 3], 7, null, new Set([4, 5])]) {
  ret = r;
  show('pair returns ' + (r instanceof Set ? 'Set' : JSON.stringify(r)), () => e.sum_pair() + ' direct=' + JSON.stringify(e.pair()));
}
const tryMod = (label, b) => {
  try { new WebAssembly.Module(new Uint8Array(b)); console.log(label, 'compiled', WebAssembly.validate(new Uint8Array(b))); }
  catch (err) { console.log(label, err.name + ': ' + err.message, WebAssembly.validate(new Uint8Array(b))); }
};
tryMod('zero-size body', [...HDR, ...sec(1, types), ...sec(3, [U(1)]), 10, 2, 1, 0]);
tryMod('overlong body', [...HDR, ...sec(1, types), ...sec(3, [U(1)]), 10, 3, 1, 9, 0]);
''')


def test_sqlite_statements_outliving_their_database(run, workdir):
    """CATCHES: statements created with db.prepare() (not cached by db.query()) staying usable after
    db.close(): every execution method (get with and without parameters, all, values, run, iterate)
    must throw Error 'Statement has finalized' (also after finalize()), while toString() still
    returns the SQL, columnNames keeps the names read before the close and finalize() stays a silent
    no-op (also repeated); a cached db.query() statement behaves the same after close."""
    check_script(run, workdir, G, "sqlite_statements_outliving_db", r'''
const { Database } = require("bun:sqlite");
const fail = (label, f) => { try { console.log(label, "ok", JSON.stringify(f())); } catch (e) { console.log(label, e.constructor.name, e.code, "|", e.message); } };
const db = new Database(":memory:");
db.run("CREATE TABLE t (a INTEGER)");
db.run("INSERT INTO t VALUES (1), (2)");
const withParam = db.prepare("SELECT ?1 AS x");
const plain = db.prepare("SELECT a FROM t ORDER BY a");
const cached = db.query("SELECT count(*) AS n FROM t");
fail("before close", () => [withParam.get(5), plain.all(), cached.get()]);
db.close();
fail("get with param", () => withParam.get(6));
fail("get", () => plain.get());
fail("all", () => plain.all());
fail("values", () => plain.values());
fail("run", () => plain.run());
fail("iterate", () => [...plain.iterate()]);
fail("columnNames", () => plain.columnNames);
fail("toString", () => plain.toString());
fail("finalize", () => plain.finalize());
fail("finalize again", () => plain.finalize());
fail("get after finalize", () => plain.get());
fail("cached get", () => cached.get());
fail("cached finalize", () => cached.finalize());
''', filename="sqlite_after_close.cjs")


# ---- Brotli / Zstandard decoders: hand-assembled streams ------------------------------------------

BROTLI_ASSEMBLER = r'''
const zlib = require('zlib');
class BW {
  constructor() { this.out = []; this.acc = 0; this.n = 0; }
  w(v, n) { for (let i = 0; i < n; i++) { this.acc |= ((Math.floor(v / 2 ** i)) & 1) << this.n; if (++this.n === 8) { this.out.push(this.acc); this.acc = 0; this.n = 0; } } return this; }
  code(c, n) { for (let i = n - 1; i >= 0; i--) this.w((c >> i) & 1, 1); return this; }
  align() { if (this.n) this.w(0, 8 - this.n); return this; }
  bytes(arr) { for (const b of arr) this.w(b, 8); return this; }
  done() { const o = this.out.slice(); if (this.n) o.push(this.acc); return Buffer.from(o); }
}
const bitLen = (x) => { let n = 0; while (x) { x >>= 1; n++; } return n; };
// Simple prefix code (RFC 7932 3.4) over `alphabet`; returns sym -> [code, len] for writing.
const simple = (bw, alphabet, syms, treeSelect = 0) => {
  bw.w(1, 2).w(syms.length - 1, 2);
  for (const s of syms) bw.w(s, bitLen(alphabet - 1));
  const lens = new Map();
  if (syms.length === 1) lens.set(syms[0], 0);
  else if (syms.length === 2) syms.forEach((s) => lens.set(s, 1));
  else if (syms.length === 3) { lens.set(syms[0], 1); lens.set(syms[1], 2); lens.set(syms[2], 2); }
  else { bw.w(treeSelect, 1); syms.forEach((s, i) => lens.set(s, treeSelect ? [1, 2, 3, 3][i] : 2)); }
  const table = new Map();
  let code = 0;
  for (let len = 1; len <= 3; len++) {
    for (const s of [...lens.keys()].filter((k) => lens.get(k) === len).sort((a, b) => a - b)) table.set(s, [code++, len]);
    code <<= 1;
  }
  for (const [s, l] of lens) if (l === 0) table.set(s, [0, 0]);
  return table;
};
const put = (bw, table, sym) => { const e = table.get(sym); if (!e) throw new Error('no code for ' + sym); bw.code(e[0], e[1]); };
const varlen = (bw, v) => { if (v === 0) return bw.w(0, 1); const n = bitLen(v) - 1; bw.w(1, 1).w(n, 3); if (n) bw.w(v - (1 << n), n); return bw; };
const INS_OFF = [0, 1, 2, 3, 4, 5, 6, 8, 10, 14, 18, 26, 34, 50, 66, 98, 130, 194, 322, 578, 1090, 2114, 6210, 22594];
const INS_EXTRA = [0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 12, 14, 24];
const COPY_OFF = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 18, 22, 30, 38, 54, 70, 102, 134, 198, 326, 582, 1094, 2118];
const COPY_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 24];
const CELL_POS = [0, 1, 0, 1, 8, 9, 2, 16, 10, 17, 18];
const lenCode = (offs, extras, v) => { for (let c = offs.length - 1; c >= 0; c--) if (offs[c] <= v) return [c, v - offs[c], extras[c]]; throw new Error('bad length ' + v); };
const cmdSym = (ic, cc) => {
  for (let cell = 2; cell < 11; cell++) {
    const pos = CELL_POS[cell];
    if ((pos & 0x18) === (ic & 0x18) && ((pos << 3) & 0x18) === (cc & 0x18)) return cell * 64 + ((ic & 7) << 3) + (cc & 7);
  }
  throw new Error('no cell');
};
// Distance codes >= 16 for NPOSTFIX = NDIRECT = 0: [symbol, extra value, extra bits].
const DIST = [];
{ let nbits = 1, half = 0; for (let i = 16; i < 64; i++) { DIST.push([i, ((2 + half) << nbits) - 4 + 1, nbits]); nbits += half; half ^= 1; } }
const distCode = (d) => { for (const [s, off, nb] of DIST) if (d >= off && d < off + 2 ** nb) return [s, d - off, nb]; throw new Error('bad distance ' + d); };
// One compressed meta-block. cmds: { lits: 'text', copy: n, dist: d | { short: sym } }.
// The final command may omit copy (its copy length is then the minimum 4 and never used).
const metaBlock = (bw, { last = true, mlen, cmds, cmdTypes = null, distTypes = null }) => {
  bw.w(last ? 1 : 0, 1);
  if (last) bw.w(0, 1);
  bw.w(0, 2).w(mlen - 1, 16);
  if (!last) bw.w(0, 1);
  const enc = cmds.map((c) => {
    const lits = Buffer.from(c.lits || '', 'latin1');
    const [ic, ie, ib] = lenCode(INS_OFF, INS_EXTRA, lits.length);
    const [cc, ce, cb] = lenCode(COPY_OFF, COPY_EXTRA, c.copy === undefined ? 4 : c.copy);
    let ds = null;
    if (c.dist !== undefined) ds = typeof c.dist === 'object' ? [c.dist.short, 0, 0] : distCode(c.dist);
    return { lits, sym: cmdSym(ic, cc), ie, ib, ce, cb, ds };
  });
  const uniq = (xs) => [...new Set(xs)];
  // block types: literal 1; command / distance optionally 2 with a switch schedule
  bw.w(0, 1);
  const blockState = (spec) => {
    if (!spec) { bw.w(0, 1); return null; }
    varlen(bw, spec.types - 1);
    const typeTable = simple(bw, spec.types + 2, spec.typeSyms);
    const lenTable = simple(bw, 26, [0]);
    bw.w(spec.first - 1, 2);
    return { typeTable, lenTable, ...spec, left: spec.first, k: 0 };
  };
  const cmdState = blockState(cmdTypes);
  const distState = blockState(distTypes);
  bw.w(0, 6);                 // NPOSTFIX = 0, NDIRECT = 0
  bw.w(0, 2);                 // context mode of the one literal block type
  bw.w(0, 1); bw.w(0, 1);     // NTREESL = 1, NTREESD = 1
  const litSyms = uniq(enc.flatMap((e) => [...e.lits]));
  const litTable = simple(bw, 256, litSyms.length ? litSyms : [0]);
  const cmdTables = [];
  for (let t = 0; t < (cmdTypes ? cmdTypes.types : 1); t++) cmdTables.push(simple(bw, 704, uniq(enc.map((e) => e.sym))));
  const distSyms = uniq(enc.filter((e) => e.ds).map((e) => e.ds[0]));
  const distTable = simple(bw, 64, distSyms.length ? distSyms : [16]);
  const switchIfNeeded = (st) => {
    if (!st) return;
    if (st.left === 0) { const [tsym, len] = st.switches[st.k++]; put(bw, st.typeTable, tsym); bw.w(len - 1, 2); st.left = len; }
    st.left--;
  };
  for (const e of enc) {
    switchIfNeeded(cmdState);
    put(bw, cmdTables[0], e.sym);
    bw.w(e.ie, e.ib); bw.w(e.ce, e.cb);
    for (const b of e.lits) put(bw, litTable, b);
    if (e.ds) { switchIfNeeded(distState); put(bw, distTable, e.ds[0]); bw.w(e.ds[1], e.ds[2]); }
  }
};
const header = () => new BW().w(0, 1); // WBITS = 16
const tryDecode = (label, buf) => {
  try { const out = zlib.brotliDecompressSync(buf); console.log(label, '->', out.length, 'bytes', out.toString('hex'), JSON.stringify(out.toString())); }
  catch (e) { console.log(label, '->', e.name + ': ' + e.message); }
};
'''


def test_brotli_decoder_crafted_streams(run, workdir):
    """CATCHES: a Brotli decoder that only handles encoder-typical streams. Hand-assembled streams
    (all valid ones decode identically with the reference libbrotli) cover static-dictionary words
    under transforms the encoder rarely emits -- uppercase-first/-all on 2- and 3-byte UTF-8 words
    (the reference's byte-XOR quirk turns U+2019 into U+201C and mangles CJK), omit-first-1/3/9 (the
    last yielding an empty word) -- command and distance block-type switching with every type code
    (previous, second-to-last+1 with wrap-around, explicit), an inverse-MTF literal context map
    without run-length codes, and empty/skipped metadata meta-blocks (one ending the stream). Also
    pins the exact error text for an out-of-range simple-code symbol, a duplicate simple-code symbol,
    a truncated code-length code, a zero run past the alphabet, an over-subscribed complex code, a
    context-map run overflow, a short distance code yielding 0, a 2-byte dictionary copy, transform
    index 121 and a copy running past the meta-block length."""
    check_script(run, workdir, G, "brotli_decoder_crafted_streams", BROTLI_ASSEMBLER + r'''
// ---- valid streams ----
{ // static-dictionary transforms across two meta-blocks
  const bw = header();
  let out = 0;
  const ref = (w, t, shift, written) => { out += 1; const c = { lits: '|', copy: shift === 10 ? 4 : shift === 11 ? 6 : 5, dist: out + 1 + w + t * (1 << shift) }; out += written; return c; };
  const a = [ref(939, 9, 10, 4), ref(939, 44, 10, 4), ref(527, 9, 10, 4), ref(527, 44, 10, 4)];
  const startB = out;
  metaBlock(bw, { last: false, mlen: out, cmds: a });
  const b = [];
  b.push({ lits: '|', copy: 6, dist: (out += 1) + 1 + 628 + 44 * 2048 }); out += 6;
  b.push({ lits: '|', copy: 5, dist: (out += 1) + 1 + 0 + 3 * 1024 }); out += 4;
  b.push({ lits: '|', copy: 5, dist: (out += 1) + 1 + 0 + 26 * 1024 }); out += 2;
  b.push({ lits: '|', copy: 4, dist: (out += 1) + 1 + 0 + 54 * 1024 }); out += 0;
  b.push({ lits: '|' }); out += 1;
  metaBlock(bw, { last: true, mlen: out - startB, cmds: b });
  const buf = bw.done();
  tryDecode('transforms', buf);
}
{ // command and distance block-type switching
  const bw = header();
  const cmds = [];
  for (let i = 0; i < 6; i++) cmds.push({ lits: 'xy'[i % 2], copy: 4, dist: 1 });
  cmds.push({ lits: '.' });
  metaBlock(bw, { mlen: 6 * 5 + 1, cmds,
    cmdTypes: { types: 2, typeSyms: [0, 1, 2, 3], first: 1, switches: [[1, 1], [0, 2], [1, 1], [1, 1], [3, 1], [2, 1]] },
    distTypes: { types: 3, typeSyms: [0, 1, 3, 4], first: 2, switches: [[1, 1], [4, 1], [0, 1], [1, 2]] } });
  tryDecode('block switches', bw.done());
}
{ // literal context map without RLE codes, inverse-MTF coded
  const bw = header();
  bw.w(1, 1).w(0, 1).w(0, 2).w(6 - 1, 16);    // last, MLEN 6
  bw.w(0, 1).w(0, 1).w(0, 1).w(0, 6).w(0, 2); // 1 type each, NPOSTFIX/NDIRECT 0, LSB6 context mode
  varlen(bw, 1);                               // NTREESL = 2
  bw.w(0, 1);                                  // RLEMAX = 0
  simple(bw, 2, [1]);                          // every context -> 1 (before IMTF)
  bw.w(1, 1);                                  // IMTF
  varlen(bw, 0);                               // NTREESD = 1
  simple(bw, 256, [0x62]); simple(bw, 256, [0x61]);
  simple(bw, 704, [128 + (6 << 3)]);           // insert code 6 (6 + 1 extra bit), copy code 0
  simple(bw, 64, [16]);
  bw.w(0, 1);                                  // insert extra bit -> 6 literals
  tryDecode('context map', bw.done());
}
{ // metadata meta-blocks (skipped payload), the last one ending the stream
  const bw = header();
  bw.w(0, 1).w(3, 2).w(0, 1).w(0, 2).align();                      // empty metadata, not last
  metaBlock(bw, { last: false, mlen: 5, cmds: [{ lits: 'hello' }] });
  bw.w(1, 1).w(0, 1).w(3, 2).w(0, 1).w(1, 2).w(2, 8).align().bytes([0x41, 0x42, 0x43]);
  tryDecode('metadata', bw.done());
}
// ---- errors ----
const pre = (mlen) => header().w(1, 1).w(0, 1).w(0, 2).w(mlen - 1, 16).w(0, 1).w(0, 1).w(0, 1).w(0, 6).w(0, 2).w(0, 1).w(0, 1);
{ const bw = pre(1); simple(bw, 256, [0x41]); bw.w(1, 2).w(0, 2).w(1000, 10); tryDecode('command symbol 1000', bw.done()); }
{ const bw = pre(1); bw.w(1, 2).w(1, 2).w(0x41, 8).w(0x41, 8); tryDecode('duplicate literal symbol', bw.done()); }
{ const bw = pre(1); bw.w(0, 2); tryDecode('truncated code-length code', bw.done()); }
{ const bw = pre(1); bw.w(0, 2).w(7, 4).w(0, 2).w(0, 2).w(0, 2).w(0, 2).w(0, 2).w(7, 4);
  for (let i = 0; i < 3; i++) bw.code(1, 1).w(7, 3);
  tryDecode('zero run past alphabet', bw.done()); }
{ const bw = pre(1); bw.w(0, 2).w(7, 4).w(7, 4); bw.code(0, 1).code(1, 1).code(0, 1); tryDecode('over-subscribed code', bw.done()); }
{ const bw = header().w(1, 1).w(0, 1).w(0, 2).w(0, 16).w(0, 1).w(0, 1).w(0, 1).w(0, 6).w(0, 2);
  varlen(bw, 1); bw.w(1, 1).w(5, 4); simple(bw, 8, [6]); bw.w(1, 6); tryDecode('context map run overflow', bw.done()); }
{ const bw = header(); metaBlock(bw, { mlen: 8, cmds: [{ lits: 'ab', copy: 2, dist: 1 }, { lits: '', copy: 2, dist: { short: 4 } }, { lits: 'zz' }] }); tryDecode('short distance to 0', bw.done()); }
{ const bw = header(); metaBlock(bw, { mlen: 8, cmds: [{ lits: 'ab', copy: 2, dist: 100 }, { lits: 'zz' }] }); tryDecode('2-byte dictionary copy', bw.done()); }
{ const bw = header(); metaBlock(bw, { mlen: 8, cmds: [{ lits: 'ab', copy: 4, dist: 3 + (121 << 10) }, { lits: 'zz' }] }); tryDecode('transform 121', bw.done()); }
{ const bw = header(); metaBlock(bw, { mlen: 3, cmds: [{ lits: 'a', copy: 4, dist: 1 }] }); tryDecode('copy past MLEN', bw.done()); }
''', filename="brotli_crafted.cjs")


def test_zstd_decoder_crafted_frame_errors(run, workdir):
    """CATCHES: a Zstandard decoder not rejecting, with the reference's exact messages, a compressed
    literals header announcing 196608 regenerated bytes ('literals section too large'), a block
    whose 3-byte sequence count (0xFF prefix) is followed by reserved mode bits, FSE table
    descriptions with accuracy log 20 (literal lengths and match lengths), an FSE description
    running past the end of the block, offset distributions whose zero-runs or symbols exceed the
    32-symbol alphabet ('too many symbols in FSE distribution' while reading, 'corrupted FSE
    distribution' when the last symbol lands past it), a sequences bitstream without bits for the
    initial states, and FSE-compressed Huffman weights whose distribution fills the whole region or
    leaves no bits for the two weight states ('truncated Huffman weights bitstream')."""
    check_script(run, workdir, G, "zstd_decoder_crafted_frame_errors", r'''
const zlib = require('zlib');
const frame = (blocks) => {
  const out = [0x28, 0xb5, 0x2f, 0xfd, 0x20, 0x00];
  blocks.forEach((b, i) => {
    const h = (i === blocks.length - 1 ? 1 : 0) | (2 << 1) | (b.length << 3);
    out.push(h & 255, (h >> 8) & 255, (h >> 16) & 255, ...b);
  });
  return Buffer.from(out);
};
const le = (v, n) => Array.from({ length: n }, (_, i) => Number((BigInt(v) >> BigInt(8 * i)) & 255n));
const litHeader = (type, fmt, regen, comp) => {
  if (fmt === 0) return le(type | (fmt << 2) | (regen << 4) | (comp << 14), 3);
  return le(BigInt(type | (fmt << 2)) | (BigInt(regen) << 4n) | (BigInt(comp) << 22n), 5);
};
const t = (label, blocks) => { try { const o = zlib.zstdDecompressSync(frame(blocks)); console.log(label, 'ok', o.length, o.toString('hex')); } catch (e) { console.log(label, e.name + ': ' + e.message); } };
t('huge compressed literals', [litHeader(2, 3, 0x30000, 1)]);
t('3-byte sequence count', [[0x00, 255, 0x10, 0x00, 0x01]]);
t('FSE accuracy log 20', [[0x00, 1, 0x80, 0x0f]]);
t('FSE description past block', [[0x00, 1, 0x80, 0x00]]);
t('no bits for initial states', [[0x00, 1, 0x00, 0x01]]);
t('weights distribution fills region', [[...litHeader(2, 0, 1, 2), 0x01, 0x00]]);
t('no bits for weight states', [[...litHeader(2, 0, 1, 4), 0x03, 0xf0, 0x03, 0x01]]);
// Forward LSB-first bit writer for FSE table descriptions (RFC 8878 4.1.1).
const fseDescription = (log, items) => {
  const bits = [];
  const w = (v, n) => { for (let i = 0; i < n; i++) bits.push((v >> i) & 1); };
  w(log - 5, 4);
  let remaining = (1 << log) + 1, threshold = 1 << log, nbits = log + 1;
  for (const it of items) {
    if (it.reps) { for (const r of it.reps) w(r, 2); continue; }
    const v = it.v, max = 2 * threshold - 1 - remaining;
    if (v < max) w(v, nbits - 1);
    else w(v < threshold ? v : v + max, nbits);
    remaining -= Math.abs(v - 1);
    while (remaining > 1 && remaining < threshold) { threshold >>= 1; nbits--; }
  }
  const bytes = [];
  for (let i = 0; i < bits.length; i += 8) bytes.push(bits.slice(i, i + 8).reduce((a, b, k) => a | (b << k), 0));
  return bytes;
};
const OF = (desc) => [[0x00, 1, 0x20, ...desc, 0x01]]; // raw empty literals, 1 sequence, offsets FSE_Compressed
t('offset zero-run past 32 symbols', OF(fseDescription(5, [{ v: 1 }, { reps: Array(11).fill(3) }])));
t('offset symbol count over limit', OF(fseDescription(5, [{ v: 1 }, { reps: [...Array(10).fill(3), 2] }, { v: 2 }])));
t('offset last symbol past limit', OF(fseDescription(5, [{ v: 1 }, { reps: [...Array(10).fill(3), 1] }, { v: 33 }])));
t('match-length accuracy log 20', [[0x00, 1, 0x08, 0x0f]]);
''', filename="zstd_crafted.cjs")


def test_aes_gcm_counter_carry_for_ghash_derived_ivs(run, workdir):
    """CATCHES: AES-GCM implementations whose inc32 of the pre-counter block J0 does not carry
    between bytes. For 16-byte IVs J0 comes from GHASH; the two IVs used here yield J0 values ending
    in ...7bff and ...ffff, so the first counter needs a one- and two-byte carry (a wrong carry
    changes every ciphertext byte and the tag). Chunked update() calls (17 + 25 bytes) and AAD are
    used; the expected values agree with OpenSSL, and decryption must round-trip."""
    check_script(run, workdir, G, "aes_gcm_counter_carry", r'''
const crypto = require('crypto');
const key = Buffer.from('000102030405060708090a0b0c0d0e0f', 'hex');
const pt = Buffer.from('GCM counter carry check: forty-two bytes!!');
for (const ivHex of ['6c756d656e2d69760000000000000091', '6c756d656e2d69760000000000003cfe']) {
  const iv = Buffer.from(ivHex, 'hex');
  const c = crypto.createCipheriv('aes-128-gcm', key, iv);
  c.setAAD(Buffer.from('aad'));
  const ct = Buffer.concat([c.update(pt.subarray(0, 17)), c.update(pt.subarray(17)), c.final()]);
  const tag = c.getAuthTag();
  const d = crypto.createDecipheriv('aes-128-gcm', key, iv);
  d.setAAD(Buffer.from('aad'));
  d.setAuthTag(tag);
  const back = Buffer.concat([d.update(ct), d.final()]).toString();
  console.log(ivHex.slice(-4), ct.length, ct.toString('hex'));
  console.log('  tag', tag.toString('hex'), 'round trip', back === pt.toString());
}
''', filename="gcm_carry.cjs")
