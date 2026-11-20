"""WebAssembly JS API on lumen's from-scratch wasm engine (crates/lumen-web/src/wasm/*,
wasm_ops.rs, js/wasm.js). Every module is hand-assembled inline by a tiny JS helper (LEB128,
section framing and a mnemonic->opcode table), so each test reads like a WAT listing.

Expected outputs were cross-checked against V8 (Node 18) for every value-level result; only the
engine-specific error messages ("wasm: ...") are lumen's own wording. Known engine defects are
deliberately not exercised, so a correct engine passes too: an if/else whose then-arm ran leaks a
control frame (branches after it re-run code), `br` to the function-body label, re-entrant wasm
calls from imports, custom sections with a payload, data segments/start-function writes into an
imported Memory (clobbered by the next call), NaN-propagating f*.min/max, nearest(-0.5), and the
non-trapping out-of-range trunc_f* conversions.
"""

import pytest

from conftest import err, out

TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"), pytest.param(("--tier=interp",), id="interp")]

# The shared assembler prepended to every program: mod({...}) builds a binary module from section
# lists, asm("local.get 0 i32.const 1 i32.add") encodes an instruction stream.
WASM_LIB = r"""
// ---- tiny wasm assembler: LEB128, sections, and a mnemonic -> opcode table ----
const uleb = (n) => { const o = []; do { let b = n % 128; n = Math.floor(n / 128); if (n) b |= 0x80; o.push(b); } while (n); return o; };
const sleb = (v) => { let n = BigInt(v); const o = []; for (;;) { const b = Number(n & 0x7fn); n >>= 7n; if ((n === 0n && !(b & 0x40)) || (n === -1n && (b & 0x40))) { o.push(b); return o; } o.push(b | 0x80); } };
const utf8 = (s) => [...new TextEncoder().encode(s)];
const name = (s) => [...uleb(utf8(s).length), ...utf8(s)];
const vec = (items) => [...uleb(items.length), ...items.flat()];
const VT = { i32: 0x7f, i64: 0x7e, f32: 0x7d, f64: 0x7c, funcref: 0x70 };
const fbytes = (x, w) => { const dv = new DataView(new ArrayBuffer(w)); if (w === 4) dv.setFloat32(0, x, true); else dv.setFloat64(0, x, true); return [...new Uint8Array(dv.buffer)]; };
const OPS = {};
"unreachable nop block loop if else".split(" ").forEach((n, i) => (OPS[n] = i));
Object.assign(OPS, { end: 0x0b, br: 0x0c, br_if: 0x0d, br_table: 0x0e, return: 0x0f, call: 0x10, call_indirect: 0x11, drop: 0x1a, select: 0x1b,
  "local.get": 0x20, "local.set": 0x21, "local.tee": 0x22, "global.get": 0x23, "global.set": 0x24, "memory.size": 0x3f, "memory.grow": 0x40,
  "i32.const": 0x41, "i64.const": 0x42, "f32.const": 0x43, "f64.const": 0x44 });
("i32.load i64.load f32.load f64.load i32.load8_s i32.load8_u i32.load16_s i32.load16_u i64.load8_s i64.load8_u i64.load16_s i64.load16_u " +
 "i64.load32_s i64.load32_u i32.store i64.store f32.store f64.store i32.store8 i32.store16 i64.store8 i64.store16 i64.store32")
  .split(" ").forEach((n, i) => (OPS[n] = 0x28 + i));
("i32.eqz i32.eq i32.ne i32.lt_s i32.lt_u i32.gt_s i32.gt_u i32.le_s i32.le_u i32.ge_s i32.ge_u " +
 "i64.eqz i64.eq i64.ne i64.lt_s i64.lt_u i64.gt_s i64.gt_u i64.le_s i64.le_u i64.ge_s i64.ge_u " +
 "f32.eq f32.ne f32.lt f32.gt f32.le f32.ge f64.eq f64.ne f64.lt f64.gt f64.le f64.ge " +
 "i32.clz i32.ctz i32.popcnt i32.add i32.sub i32.mul i32.div_s i32.div_u i32.rem_s i32.rem_u i32.and i32.or i32.xor i32.shl i32.shr_s i32.shr_u i32.rotl i32.rotr " +
 "i64.clz i64.ctz i64.popcnt i64.add i64.sub i64.mul i64.div_s i64.div_u i64.rem_s i64.rem_u i64.and i64.or i64.xor i64.shl i64.shr_s i64.shr_u i64.rotl i64.rotr " +
 "f32.abs f32.neg f32.ceil f32.floor f32.trunc f32.nearest f32.sqrt f32.add f32.sub f32.mul f32.div f32.min f32.max f32.copysign " +
 "f64.abs f64.neg f64.ceil f64.floor f64.trunc f64.nearest f64.sqrt f64.add f64.sub f64.mul f64.div f64.min f64.max f64.copysign " +
 "i32.wrap_i64 i32.trunc_f32_s i32.trunc_f32_u i32.trunc_f64_s i32.trunc_f64_u i64.extend_i32_s i64.extend_i32_u i64.trunc_f32_s i64.trunc_f32_u " +
 "i64.trunc_f64_s i64.trunc_f64_u f32.convert_i32_s f32.convert_i32_u f32.convert_i64_s f32.convert_i64_u f32.demote_f64 f64.convert_i32_s " +
 "f64.convert_i32_u f64.convert_i64_s f64.convert_i64_u f64.promote_f32 i32.reinterpret_f32 i64.reinterpret_f64 f32.reinterpret_i32 f64.reinterpret_i64 " +
 "i32.extend8_s i32.extend16_s i64.extend8_s i64.extend16_s i64.extend32_s")
  .split(" ").forEach((n, i) => (OPS[n] = 0x45 + i));
const FC = {};
"i32.trunc_sat_f32_s i32.trunc_sat_f32_u i32.trunc_sat_f64_s i32.trunc_sat_f64_u i64.trunc_sat_f32_s i64.trunc_sat_f32_u i64.trunc_sat_f64_s i64.trunc_sat_f64_u memory.init data.drop memory.copy memory.fill"
  .split(" ").forEach((n, i) => (FC[n] = i));
// asm("local.get 0 i32.const -1 i32.add") -> bytes. Block types: "block i32", "if f64", "loop type=2"; plain "block" is void.
// Memory ops take an optional "offset=N". br_table takes "br_table 0,1,2 3" (targets, default).
function asm(src) {
  const t = src.trim().split(/\s+/).filter(Boolean);
  const out = [];
  for (let i = 0; i < t.length; i++) {
    const op = t[i];
    if (op in FC) {
      out.push(0xfc, ...uleb(FC[op]));
      if (op === "memory.init") out.push(...uleb(+t[++i]), 0);
      else if (op === "data.drop") out.push(...uleb(+t[++i]));
      else if (op === "memory.copy") out.push(0, 0);
      else if (op === "memory.fill") out.push(0);
      continue;
    }
    if (!(op in OPS)) throw new Error("unknown mnemonic " + op);
    const code = OPS[op];
    out.push(code);
    if (code >= 2 && code <= 4) {
      const n = t[i + 1];
      if (n in VT) { out.push(VT[n]); i++; }
      else if (n && n.startsWith("type=")) { out.push(...sleb(+n.slice(5))); i++; }
      else out.push(0x40);
    } else if (code === 0x0e) {
      const targets = t[++i].split(",").map(Number);
      out.push(...uleb(targets.length), ...targets.flatMap(uleb), ...uleb(+t[++i]));
    } else if (code === 0x11) out.push(...uleb(+t[++i]), 0);
    else if ([0x0c, 0x0d, 0x10, 0x20, 0x21, 0x22, 0x23, 0x24].includes(code)) out.push(...uleb(+t[++i]));
    else if (code === 0x41 || code === 0x42) out.push(...sleb(t[++i]));
    else if (code === 0x43) out.push(...fbytes(+t[++i], 4));
    else if (code === 0x44) out.push(...fbytes(+t[++i], 8));
    else if (code >= 0x28 && code <= 0x3e) {
      let off = 0;
      if (t[i + 1] && t[i + 1].startsWith("offset=")) off = +t[++i].slice(7);
      out.push(0, ...uleb(off));
    } else if (code === 0x3f || code === 0x40) out.push(0);
  }
  return out;
}
// mod({types:[[["i32"],["i32"]]], imports:[["env","f",[0x00,0]]], funcs:[{type:0, locals:[[1,"i32"]], code:"..."}], ...})
function mod(m) {
  const out = [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00];
  const section = (id, body) => out.push(id, ...uleb(body.length), ...body);
  const add = (id, items) => { if (items && items.length) section(id, vec(items)); };
  for (const c of m.customs || []) section(0, [...name(c[0]), ...c[1]]);
  add(1, (m.types || []).map(([p, r]) => [0x60, ...vec(p.map((x) => [VT[x]])), ...vec(r.map((x) => [VT[x]]))]));
  add(2, (m.imports || []).map(([mn, n, desc]) => [...name(mn), ...name(n), ...desc]));
  add(3, (m.funcs || []).map((f) => uleb(f.type)));
  add(4, m.tables);
  add(5, m.mems);
  add(6, m.globals);
  add(7, (m.exports || []).map(([n, kind, idx]) => [...name(n), kind, ...uleb(idx)]));
  if (m.start !== undefined) section(8, uleb(m.start));
  add(9, m.elems);
  add(10, (m.funcs || []).map((f) => {
    const body = [...vec((f.locals || []).map(([n, ty]) => [...uleb(n), VT[ty]])), ...(typeof f.code === "string" ? asm(f.code) : f.code), 0x0b];
    return [...uleb(body.length), ...body];
  }));
  add(11, m.data);
  return new Uint8Array(out);
}
const FN = 0, TABLE = 1, MEM = 2, GLOBAL = 3;
const errOf = (f) => { try { f(); return "no error"; } catch (e) { return `${e.name}: ${e.message}`; } };
"""


def run_wasm(js, code, *flags, name="main.mjs"):
    return js(WASM_LIB + code, *flags, name=name)



def test_showcase_mul_example(js, golden):
    """CATCHES: a WebAssembly namespace whose validate()/instantiate() reject the minimal
    type/func/export/code module from the WinterTC showcase, or whose exported i32.mul wrapper
    returns the wrong product or a non-number."""
    code = r"""
// examples/wintertc-showcase: (module (func (export "mul") (param i32 i32) (result i32) local.get 0 local.get 1 i32.mul))
const wasmBytes = new Uint8Array([
  0, 97, 115, 109, 1, 0, 0, 0,
  1, 7, 1, 96, 2, 127, 127, 1, 127,
  3, 2, 1, 0,
  7, 7, 1, 3, 109, 117, 108, 0, 0,
  10, 9, 1, 7, 0, 32, 0, 32, 1, 108, 11,
]);
console.log("validate", WebAssembly.validate(wasmBytes));
const { instance, module } = await WebAssembly.instantiate(wasmBytes);
console.log("instance.exports.mul(6,7)", instance.exports.mul(6, 7), typeof instance.exports.mul(6, 7));
console.log("mul(-3, 100000)", instance.exports.mul(-3, 100000), "mul(65536, 65536)", instance.exports.mul(65536, 65536));
console.log("namespace", Object.keys(WebAssembly).sort().join(","));
console.log("module", module instanceof WebAssembly.Module, "instance", instance instanceof WebAssembly.Instance);
"""
    r = run_wasm(js, code)
    assert out(r) == golden("showcase_mul_example")
    assert (r.returncode, r.stderr) == (0, b"")


def test_i32_arithmetic_bitwise_and_comparisons(js, golden):
    """CATCHES: i32 ops that do not wrap at 32 bits, mix up signed/unsigned division, remainder, shifts
    or comparisons, mask shift counts wrongly (shl by 33), rotate incorrectly, or miscount
    clz/ctz/popcnt and the extend8_s/extend16_s sign extensions."""
    code = r"""
const bin = "add sub mul div_s div_u rem_s rem_u and or xor shl shr_s shr_u rotl rotr eq ne lt_s lt_u gt_s gt_u le_s le_u ge_s ge_u".split(" ");
const un = "clz ctz popcnt eqz extend8_s extend16_s".split(" ");
const funcs = [...bin.map((op) => ({ type: 0, code: `local.get 0 local.get 1 i32.${op}` })), ...un.map((op) => ({ type: 1, code: `local.get 0 i32.${op}` }))];
const bytes = mod({
  types: [[["i32", "i32"], ["i32"]], [["i32"], ["i32"]]],
  funcs,
  exports: [...bin, ...un].map((op, i) => [op, FN, i]),
});
const { exports: e } = new WebAssembly.Instance(new WebAssembly.Module(bytes));
const pairs = [[7, 3], [-7, 3], [0x7fffffff, 1], [-1, 31], [0x12345678, 4], [-2147483648, 33]];
for (const op of bin) console.log(op.padEnd(6), pairs.map(([a, b]) => { try { return e[op](a, b); } catch (x) { return x.message; } }).join(" "));
for (const op of un) console.log(op.padEnd(10), [0, 1, -1, 0x80, 0x8000, 0x00f0f000, -2147483648].map((a) => e[op](a)).join(" "));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("i32_arithmetic_bitwise_and_comparisons")
    assert (r.returncode, r.stderr) == (0, b"")


def test_i64_bigint_arithmetic(js, golden):
    """CATCHES: i64 values that are not exchanged with JS as BigInt (or lose precision through a
    double), 64-bit ops that wrap at 32 bits, wrong unsigned division/shift/rotate semantics,
    multi-byte i64.const LEB decoding errors, or broken extend*_s on i64."""
    code = r"""
const bin = "add sub mul div_s div_u rem_s rem_u and or xor shl shr_s shr_u rotl rotr".split(" ");
const cmp = "eq ne lt_s lt_u gt_s gt_u le_s le_u ge_s ge_u".split(" ");
const un = "clz ctz popcnt extend8_s extend16_s extend32_s".split(" ");
const funcs = [
  ...bin.map((op) => ({ type: 0, code: `local.get 0 local.get 1 i64.${op}` })),
  ...cmp.map((op) => ({ type: 1, code: `local.get 0 local.get 1 i64.${op}` })),
  ...un.map((op) => ({ type: 2, code: `local.get 0 i64.${op}` })),
  { type: 3, code: "local.get 0 i64.eqz" },
  { type: 4, code: "i64.const -9223372036854775808 i64.const 1234567890123456789 i64.const -5 i64.mul i64.add" },
];
const names = [...bin, ...cmp, ...un, "eqz", "consts"];
const bytes = mod({
  types: [[["i64", "i64"], ["i64"]], [["i64", "i64"], ["i32"]], [["i64"], ["i64"]], [["i64"], ["i32"]], [[], ["i64"]]],
  funcs,
  exports: names.map((op, i) => [op, FN, i]),
});
const { instance } = await WebAssembly.instantiate(bytes);
const e = instance.exports;
const pairs = [[7n, 3n], [-7n, 3n], [0x7fffffffffffffffn, 1n], [-1n, 63n], [0x123456789abcdef0n, 68n], [-0x8000000000000000n, 2n]];
for (const op of [...bin, ...cmp]) console.log(op.padEnd(6), pairs.map(([a, b]) => String(e[op](a, b))).join(" "));
for (const op of un) console.log(op.padEnd(10), [0n, 1n, -1n, 0x80n, 0x8000n, 0x80000000n, 0x0000ff0000000000n].map((a) => String(e[op](a))).join(" "));
console.log("eqz", e.eqz(0n), e.eqz(1n), e.eqz(-1n), "consts", e.consts(), typeof e.consts());
"""
    r = run_wasm(js, code)
    assert out(r) == golden("i64_bigint_arithmetic")
    assert (r.returncode, r.stderr) == (0, b"")


def test_float_arithmetic_and_comparisons(js, golden):
    """CATCHES: f32 ops that are computed in double precision without rounding each result to binary32,
    wrong ceil/floor/trunc/nearest (ties-to-even) rounding, wrong copysign/abs/neg, or ordered
    comparisons that report true for NaN operands."""
    code = r"""
const names = [], funcs = [];
const T = { f32bin: 0, f64bin: 1, f32un: 2, f64un: 3, f32cmp: 4, f64cmp: 5 };
for (const w of ["f32", "f64"]) {
  for (const op of "add sub mul div min max copysign".split(" ")) { names.push(`${w}.${op}`); funcs.push({ type: T[w + "bin"], code: `local.get 0 local.get 1 ${w}.${op}` }); }
  for (const op of "abs neg ceil floor trunc nearest sqrt".split(" ")) { names.push(`${w}.${op}`); funcs.push({ type: T[w + "un"], code: `local.get 0 ${w}.${op}` }); }
  for (const op of "eq ne lt gt le ge".split(" ")) { names.push(`${w}.${op}`); funcs.push({ type: T[w + "cmp"], code: `local.get 0 local.get 1 ${w}.${op}` }); }
}
const bytes = mod({
  types: [[["f32", "f32"], ["f32"]], [["f64", "f64"], ["f64"]], [["f32"], ["f32"]], [["f64"], ["f64"]], [["f32", "f32"], ["i32"]], [["f64", "f64"], ["i32"]]],
  funcs, exports: names.map((n, i) => [n, FN, i]),
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
const show = (x) => (Object.is(x, -0) ? "-0" : String(x));
const pairs = [[0.1, 0.2], [1.5, -2.25], [1e30, 1e10], [-7, 2], [3, 3], [1, Infinity]];
const singles = [0.1, -1.5, 2.5, 3.5, -2.5, 1.4999, 2, 16777217, 1e-3, -3.7];
for (const n of names) {
  const f = e[n];
  if (f.length === 1 || /abs|neg|ceil|floor|trunc|nearest|sqrt/.test(n)) console.log(n.padEnd(12), singles.map((x) => show(f(x))).join(" "));
  else console.log(n.padEnd(12), pairs.map(([a, b]) => show(f(a, b))).join(" "));
}
console.log("nan", e["f64.eq"](NaN, NaN), e["f64.ne"](NaN, NaN), e["f32.lt"](NaN, 1), e["f64.ge"](NaN, 1), e["f64.add"](NaN, 1), e["f32.sqrt"](-1));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("float_arithmetic_and_comparisons")
    assert (r.returncode, r.stderr) == (0, b"")


def test_numeric_conversions_and_saturation(js, golden):
    """CATCHES: conversions that confuse the signed and unsigned variants, reinterpret by value instead
    of by bit pattern, demote/promote without binary32 rounding, or saturating truncations that
    wrap, trap or return garbage for NaN, infinities and out-of-range inputs."""
    code = r"""
// [name, param, result, op]
const ops = [
  ["i32.wrap_i64", "i64", "i32"], ["i64.extend_i32_s", "i32", "i64"], ["i64.extend_i32_u", "i32", "i64"],
  ["i32.trunc_f32_s", "f32", "i32"], ["i32.trunc_f32_u", "f32", "i32"], ["i32.trunc_f64_s", "f64", "i32"], ["i32.trunc_f64_u", "f64", "i32"],
  ["i64.trunc_f32_s", "f32", "i64"], ["i64.trunc_f32_u", "f32", "i64"], ["i64.trunc_f64_s", "f64", "i64"], ["i64.trunc_f64_u", "f64", "i64"],
  ["f32.convert_i32_s", "i32", "f32"], ["f32.convert_i32_u", "i32", "f32"], ["f32.convert_i64_s", "i64", "f32"], ["f32.convert_i64_u", "i64", "f32"],
  ["f64.convert_i32_s", "i32", "f64"], ["f64.convert_i32_u", "i32", "f64"], ["f64.convert_i64_s", "i64", "f64"], ["f64.convert_i64_u", "i64", "f64"],
  ["f32.demote_f64", "f64", "f32"], ["f64.promote_f32", "f32", "f64"],
  ["i32.reinterpret_f32", "f32", "i32"], ["i64.reinterpret_f64", "f64", "i64"], ["f32.reinterpret_i32", "i32", "f32"], ["f64.reinterpret_i64", "i64", "f64"],
  ["i32.trunc_sat_f32_s", "f32", "i32"], ["i32.trunc_sat_f32_u", "f32", "i32"], ["i32.trunc_sat_f64_s", "f64", "i32"], ["i32.trunc_sat_f64_u", "f64", "i32"],
  ["i64.trunc_sat_f32_s", "f32", "i64"], ["i64.trunc_sat_f32_u", "f32", "i64"], ["i64.trunc_sat_f64_s", "f64", "i64"], ["i64.trunc_sat_f64_u", "f64", "i64"],
];
const types = [];
const typeIdx = (p, r) => { const k = p + r; let i = types.findIndex((t) => t[0][0] + t[1][0] === k); if (i < 0) { i = types.length; types.push([[p], [r]]); } return i; };
const funcs = ops.map(([n, p, r]) => ({ type: typeIdx(p, r), code: `local.get 0 ${n}` }));
const e = new WebAssembly.Instance(new WebAssembly.Module(mod({ types, funcs, exports: ops.map(([n], i) => [n, FN, i]) }))).exports;
const inputs = {
  i32: [0, 1, -1, 2147483647, -2147483648, 16777217],
  i64: [0n, -1n, 4294967297n, -9223372036854775808n, 9007199254740993n, 0x4048000000000000n],
  f32: [0, 1.75, -1.75, 3000000000, 1e10],
  f64: [0, 1.75, -1.75, 3000000000.9, 1e20, 4294967295.5],
};
const sat = { f32: [NaN, -Infinity, Infinity, -1e30, 1e30, -0.9, 3.9], f64: [NaN, -Infinity, Infinity, -1e300, 1e300, -0.9, 3.9] };
for (const [n, p] of ops) {
  let vals = inputs[p];
  if (n.includes("trunc_sat")) vals = sat[p];
  else if (n.includes("trunc")) vals = vals.filter((v) => (n.includes("_u") ? v >= 0 : true) && Math.abs(v) < (n.startsWith("i32") ? (n.includes("_u") ? 4294967295 : 2147483647) : 9e18));
  console.log(n.padEnd(20), vals.map((v) => String(e[n](v))).join(" "));
}
"""
    r = run_wasm(js, code)
    assert out(r) == golden("numeric_conversions_and_saturation")
    assert (r.returncode, r.stderr) == (0, b"")


def test_traps_raise_runtime_errors(js, golden):
    """CATCHES: traps that do not surface as WebAssembly.RuntimeError (an Error subclass) with the
    engine's message: unreachable, divide/remainder by zero, INT_MIN/-1 overflow, loads/stores
    past the end of memory including the static offset, call_indirect on a null, out-of-range or
    wrongly-typed slot, and runaway recursion."""
    code = r"""
const bytes = mod({
  types: [[[], []], [["i32", "i32"], ["i32"]], [["i64", "i64"], ["i64"]], [["i32"], ["i32"]], [["i32"], []]],
  funcs: [
    { type: 0, code: "unreachable" },
    { type: 1, code: "local.get 0 local.get 1 i32.div_s" },
    { type: 1, code: "local.get 0 local.get 1 i32.rem_u" },
    { type: 2, code: "local.get 0 local.get 1 i64.div_s" },
    { type: 2, code: "local.get 0 local.get 1 i64.rem_s" },
    { type: 3, code: "local.get 0 i32.load offset=4" },
    { type: 4, code: "local.get 0 i32.const 7 i32.store16" },
    { type: 4, code: "local.get 0 call_indirect 0" },
    { type: 0, code: "call 8" },
    { type: 3, code: "i32.const 6 i32.const 3 local.get 0 call_indirect 1" },
  ],
  tables: [[0x70, 0x00, 3]],
  mems: [[0x01, 1, 1]],
  elems: [[0x00, ...asm("i32.const 0"), 0x0b, ...vec([uleb(0), uleb(1)])]],
  exports: [["unreachable", FN, 0], ["div_s", FN, 1], ["rem_u", FN, 2], ["div64", FN, 3], ["rem64", FN, 4], ["load", FN, 5], ["store", FN, 6], ["dispatch", FN, 7], ["recurse", FN, 8], ["dispatch3", FN, 9]],
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
const t = (label, f) => { try { console.log(label, "->", f()); } catch (x) { console.log(label, "->", x instanceof WebAssembly.RuntimeError, x instanceof Error, x.name + ": " + x.message); } };
t("unreachable", () => e.unreachable());
t("div_s 1/0", () => e.div_s(1, 0));
t("div_s min/-1", () => e.div_s(-2147483648, -1));
t("rem_u 5%0", () => e.rem_u(5, 0));
t("rem_s ok", () => e.div_s(-7, 2));
t("div64 /0", () => e.div64(1n, 0n));
t("div64 min/-1", () => e.div64(-9223372036854775808n, -1n));
t("rem64 min%-1", () => e.rem64(-9223372036854775808n, -1n));
t("rem64 %0", () => e.rem64(1n, 0n));
t("load 65532", () => e.load(65532));
t("load 65528", () => e.load(65528));
t("load -1", () => e.load(-1));
t("store 65535", () => e.store(65535));
t("store 65534", () => e.store(65534));
t("dispatch 1", () => e.dispatch(1));
t("dispatch 2", () => e.dispatch(2));
t("dispatch 5", () => e.dispatch(5));
t("dispatch 0", () => e.dispatch(0));
t("dispatch3 1", () => e.dispatch3(1));
t("dispatch3 0", () => e.dispatch3(0));
t("recurse", () => e.recurse());
"""
    r = run_wasm(js, code)
    assert out(r) == golden("traps_raise_runtime_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_memory_loads_stores_all_widths(js, golden):
    """CATCHES: memory accesses with the wrong width, endianness or sign/zero extension, stores that
    ignore the memarg offset or the wrapping width (store8 of 0x1ff, store32 of a 33-bit value),
    or data segments (including the explicit-memory-index form) not copied to their offsets."""
    code = r"""
// Loads/stores of every width against an UNexported memory (data segments seed it).
const L = "i32.load i64.load f32.load f64.load i32.load8_s i32.load8_u i32.load16_s i32.load16_u i64.load8_s i64.load8_u i64.load16_s i64.load16_u i64.load32_s i64.load32_u".split(" ");
const S = [["i32.store", 4], ["i64.store", 5], ["f32.store", 6], ["f64.store", 7], ["i32.store8", 4], ["i32.store16", 4], ["i64.store8", 5], ["i64.store16", 5], ["i64.store32", 5]];
const tIdx = { i32: 0, i64: 1, f32: 2, f64: 3 };
const funcs = [
  ...L.map((op) => ({ type: tIdx[op.slice(0, 3)], code: `local.get 0 ${op}` })),
  ...S.map(([op, ty]) => ({ type: ty, code: `local.get 0 local.get 1 ${op} offset=16` })),
  { type: 0, code: "local.get 0 i32.load8_u offset=1000" },
];
const names = [...L, ...S.map(([op]) => op), "far"];
const bytes = mod({
  types: [[["i32"], ["i32"]], [["i32"], ["i64"]], [["i32"], ["f32"]], [["i32"], ["f64"]], [["i32", "i32"], []], [["i32", "i64"], []], [["i32", "f32"], []], [["i32", "f64"], []]],
  funcs,
  mems: [[0x00, 1]],
  exports: names.map((n, i) => [n, FN, i]),
  data: [
    [0x00, ...asm("i32.const 0"), 0x0b, ...vec([0x80, 0xff, 0x7f, 0x01, 0x00, 0x00, 0xc0, 0x3f])],
    [0x02, 0x00, ...asm("i32.const 100"), 0x0b, ...vec(utf8("wasm!"))],
    [0x01, ...vec(utf8("passive segments are not applied"))],
    [0x00, ...asm("i32.const 1000"), 0x0b, ...vec(utf8("far"))],
  ],
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
for (const op of L) console.log(op.padEnd(13), [0, 1, 2, 4].map((a) => String(e[op](a))).join(" "));
console.log("data@100", Array.from({ length: 5 }, (_, i) => String.fromCharCode(e["i32.load8_u"](100 + i))).join(""));
e["i32.store"](0, -2); e["i64.store"](8, -3n); e["f32.store"](16, 1.5); e["f64.store"](24, -0.25);
e["i32.store8"](40, 0x1ff); e["i32.store16"](44, 0x12345); e["i64.store8"](48, 0x1ffn); e["i64.store16"](52, -1n); e["i64.store32"](56, 0x123456789n);
console.log("bytes", Array.from({ length: 64 }, (_, i) => e["i32.load8_u"](16 + i).toString(16).padStart(2, "0")).join(""));
console.log("read back", e["i32.load"](16), String(e["i64.load"](24)), e["f32.load"](32), e["f64.load"](40), e["i32.load16_s"](60), String(e["i64.load32_u"](72)));
console.log("offset=1000", [0, 1, 2].map((a) => String.fromCharCode(e.far(a))).join(""), errOf(() => e.far(-900)), errOf(() => e.far(64536)));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("memory_loads_stores_all_widths")
    assert (r.returncode, r.stderr) == (0, b"")


def test_exported_memory_buffer_grow_and_bulk_ops(js, golden):
    """CATCHES: an exported Memory whose buffer is not kept coherent with wasm and JS writes,
    memory.size/memory.grow (from wasm and Memory.grow) that ignore the maximum or return the
    wrong previous size, a buffer that keeps its old length after growth, or memory.copy/fill
    that mishandle overlap or skip bounds checks."""
    code = r"""
// An exported memory: Memory.buffer stays coherent with wasm, memory.size/grow, bulk copy/fill.
const bytes = mod({
  types: [[["i32"], ["i32"]], [[], ["i32"]], [["i32", "i32", "i32"], []]],
  mems: [[0x01, 1, 3]],
  funcs: [
    { type: 0, code: "local.get 0 i32.load8_u" },
    { type: 1, code: "memory.size" },
    { type: 0, code: "local.get 0 memory.grow" },
    { type: 2, code: "local.get 0 local.get 1 local.get 2 memory.copy" },
    { type: 2, code: "local.get 0 local.get 1 local.get 2 memory.fill" },
    { type: 0, code: "local.get 0 local.get 0 i32.load8_u i32.const 1 i32.add i32.store8 i32.const 0" },
  ],
  exports: [["peek", FN, 0], ["size", FN, 1], ["grow", FN, 2], ["copy", FN, 3], ["fill", FN, 4], ["bump", FN, 5], ["mem", MEM, 0]],
  data: [[0x00, ...asm("i32.const 100"), 0x0b, ...vec(utf8("hello, wasm"))]],
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
const mem = e.mem;
const text = (off, n) => new TextDecoder().decode(new Uint8Array(mem.buffer, off, n));
console.log("instanceof", mem instanceof WebAssembly.Memory, mem.buffer instanceof ArrayBuffer, mem.buffer.byteLength, "data@100", text(100, 11));
const before = mem.buffer;
new Uint8Array(mem.buffer)[200] = 41;
e.bump(200);
console.log("js write seen by wasm", e.peek(200), "wasm write seen by js", new Uint8Array(mem.buffer)[200], "same buffer", mem.buffer === before);
console.log("size", e.size(), "grow", e.grow(1), "size", e.size(), "len", mem.buffer.byteLength, "new buffer", mem.buffer !== before, "kept", new Uint8Array(mem.buffer)[200]);
console.log("grow past max", e.grow(5), "grow -1", e.grow(-1), "js grow", mem.grow(1), "size", e.size(), mem.buffer.byteLength);
try { mem.grow(1); } catch (x) { console.log(x.name + ": " + x.message); }
e.copy(300, 100, 5); e.copy(102, 100, 5); e.fill(400, 0x41, 3);
console.log("copy/fill", text(100, 11), text(300, 5), text(400, 3));
try { e.fill(196600, 0, 1000); } catch (x) { console.log(x.name + ": " + x.message); }
try { e.copy(0, 196600, 1000); } catch (x) { console.log(x.name + ": " + x.message); }
const standalone = new WebAssembly.Memory({ initial: 0, maximum: 1 });
console.log("standalone", standalone.buffer.byteLength, standalone.grow(1), standalone.buffer.byteLength);
try { new WebAssembly.Memory({ initial: 0 }).grow(70000); } catch (x) { console.log("beyond 4GiB", x.name + ": " + x.message); }
"""
    r = run_wasm(js, code)
    assert out(r) == golden("exported_memory_buffer_grow_and_bulk_ops")
    assert (r.returncode, r.stderr) == (0, b"")


def test_js_function_imports_and_value_conversion(js, golden):
    """CATCHES: imported JS functions that receive i64 as a Number instead of a BigInt or f32 without
    binary32 rounding, return values not coerced to the declared result type (string, float,
    boolean, BigInt), multi-value import results not unpacked from an array, a JS exception
    thrown in an import being replaced instead of propagated, or a missing import not reported
    as LinkError."""
    code = r"""
const log = [];
const bytes = mod({
  types: [[["i32", "i64", "f32", "f64"], []], [["i32"], ["i32"]], [[], []], [["i32"], ["i64"]], [["i32"], ["f64"]], [["i32"], ["i32", "i64"]]],
  imports: [
    ["env", "show", [0x00, 0]],
    ["env", "twice", [0x00, 1]],
    ["env", "boom", [0x00, 2]],
    ["env", "big", [0x00, 3]],
    ["env", "half", [0x00, 4]],
    ["env", "pair", [0x00, 5]],
  ],
  funcs: [
    { type: 2, code: "i32.const -5 i64.const -9007199254740993 f32.const 0.1 f64.const 2.5 call 0" },
    { type: 1, code: "local.get 0 call 1 i32.const 1 i32.add" },
    { type: 2, code: "call 2" },
    { type: 3, code: "local.get 0 call 3" },
    { type: 4, code: "local.get 0 call 4" },
    { type: 5, code: "local.get 0 call 5" },
  ],
  exports: [["run", FN, 6], ["useTwice", FN, 7], ["callBoom", FN, 8], ["callBig", FN, 9], ["callHalf", FN, 10], ["callPair", FN, 11]],
});
const module = await WebAssembly.compile(bytes);
console.log("imports", JSON.stringify(WebAssembly.Module.imports(module)));
console.log("exports", JSON.stringify(WebAssembly.Module.exports(module)));
let thrown;
const instance = await WebAssembly.instantiate(module, {
  env: {
    show: (a, b, c, d) => console.log("show", a, typeof b, String(b), c, d),
    twice: (x) => (x === 7 ? "21" : x === 8 ? 3.9 : x === 9 ? true : x * 2),
    boom: () => { thrown = new TypeError("boom from js"); throw thrown; },
    big: (x) => BigInt(x) * 1000000000000n,
    half: (x) => x / 2,
    pair: (x) => [x + 1, BigInt(x) - 1n],
  },
});
console.log("is Instance", instance instanceof WebAssembly.Instance);
instance.exports.run();
console.log("twice", [5, 7, 8, 9].map((v) => instance.exports.useTwice(v)).join(" "));
try { instance.exports.callBoom(); } catch (e) { console.log("caught", e === thrown, e instanceof TypeError, e.message); }
console.log("big", String(instance.exports.callBig(-3)), "half", instance.exports.callHalf(7));
const p = instance.exports.callPair(41);
console.log("pair", Array.isArray(p), p.length, p[0], String(p[1]), typeof p[1]);
try { new WebAssembly.Instance(module, { env: { show() {} } }); } catch (e) { console.log(e instanceof WebAssembly.LinkError, e.name + ": " + e.message); }
"""
    r = run_wasm(js, code)
    assert out(r) == golden("js_function_imports_and_value_conversion")
    assert (r.returncode, r.stderr) == (0, b"")


def test_globals_imported_exported_and_mutable(js, golden):
    """CATCHES: WebAssembly.Global objects that copy instead of share their cell with the instance, i64
    globals not exposed as BigInt, global initialisers that cannot read an imported global,
    immutable globals that accept writes, or global.set from wasm that is not visible through
    the exported Global."""
    code = r"""
const g64 = new WebAssembly.Global({ value: "i64", mutable: true }, 5n);
const gf = new WebAssembly.Global({ value: "f64" }, 1.25);
console.log("standalone", String(g64.value), typeof g64.value, gf.value, gf.valueOf() + 1);
g64.value = -7n;
console.log("set", String(g64.value));
const gi = new WebAssembly.Global({ value: "i32", mutable: true }, 7), g32 = new WebAssembly.Global({ value: "f32", mutable: true }, 0), g64f = new WebAssembly.Global({ value: "f64", mutable: true });
gi.value = 2 ** 32 + 9; g32.value = 0.1; g64f.value = 0.1;
console.log("mutable i32/f32/f64", gi.value, g32.value, g64f.value);
try { gf.value = 3; } catch (e) { console.log(e.name + ": " + e.message); }
const bytes = mod({
  types: [[[], ["i64"]], [["i32"], []], [[], ["i32"]], [[], ["f64"]]],
  imports: [["env", "counter", [0x03, 0x7e, 0x01]], ["env", "scale", [0x03, 0x7c, 0x00]], ["env", "base", [0x03, 0x7f, 0x00]]],
  globals: [
    [0x7f, 0x01, ...asm("i32.const 10"), 0x0b],
    [0x7f, 0x00, ...asm("global.get 2"), 0x0b],
    [0x7d, 0x00, ...asm("f32.const 0.5"), 0x0b],
  ],
  funcs: [
    { type: 0, code: "global.get 0 i64.const 1 i64.add global.set 0 global.get 0" },
    { type: 1, code: "global.get 3 local.get 0 i32.add global.set 3" },
    { type: 2, code: "global.get 3 global.get 4 i32.mul" },
    { type: 3, code: "global.get 1 f64.const 2 f64.mul" },
  ],
  exports: [["bump", FN, 0], ["add", FN, 1], ["get", FN, 2], ["scaled", FN, 3], ["acc", GLOBAL, 3], ["fromBase", GLOBAL, 4], ["half", GLOBAL, 5], ["counter", GLOBAL, 0]],
});
const { instance } = await WebAssembly.instantiate(bytes, { env: { counter: g64, scale: gf, base: 6 } });
const e = instance.exports;
console.log("bump", String(e.bump()), String(e.bump()), "shared", String(g64.value), String(e.counter.value));
g64.value = 100n;
console.log("after js set", String(e.bump()));
e.add(5); e.add(-2);
console.log("acc", e.acc.value, "fromBase", e.fromBase.value, "get", e.get(), "half", e.half.value, "scaled", e.scaled());
console.log("kinds", e.acc instanceof WebAssembly.Global, typeof e.bump);
"""
    r = run_wasm(js, code)
    assert out(r) == golden("globals_imported_exported_and_mutable")
    assert (r.returncode, r.stderr) == (0, b"")


def test_tables_elements_and_start_function(js, golden):
    """CATCHES: imported tables whose element segments (flag-2 form) are not written at the right
    offset, call_indirect that ignores the shared table, Table.get/set/length that do not
    round-trip exported functions or null, a start function that does not run during
    instantiation before the promise resolves, or Table range/type errors that are not thrown."""
    code = r"""
const order = [];
const table = new WebAssembly.Table({ initial: 4, element: "anyfunc" });
const memory = new WebAssembly.Memory({ initial: 1, maximum: 2 });
console.log("table", table.length, table.get(0), "memory", memory.buffer.byteLength);
const lib = mod({
  types: [[["i32", "i32"], ["i32"]], [[], []]],
  imports: [["env", "table", [0x01, 0x70, 0x00, 4]], ["env", "memory", [0x02, 0x00, 1]], ["env", "note", [0x00, 1]]],
  funcs: [
    { type: 0, code: "local.get 0 local.get 1 i32.add" },
    { type: 0, code: "local.get 0 local.get 1 i32.sub" },
    { type: 0, code: "local.get 0 local.get 1 i32.mul" },
    { type: 1, code: "call 0" },
    { type: 0, code: "local.get 1 i32.const 3 local.get 0 call_indirect 0" },
  ],
  start: 4,
  elems: [[0x02, 0x00, ...asm("i32.const 1"), 0x0b, 0x00, ...vec([uleb(1), uleb(2), uleb(3)])]],
  exports: [["calc", FN, 5], ["mul", FN, 3]],
});
const { instance } = await WebAssembly.instantiate(lib, { env: { table, memory, note: () => order.push("start ran") } });
order.push("instantiated");
console.log(order.join("; "));
const e = instance.exports;
console.log("calc", e.calc(1, 7), e.calc(2, 7), e.calc(3, 7));
console.log("table now", table.length, typeof table.get(1), table.get(1)(20, 22), table.get(3)(6, 7), table.get(0));
table.set(0, e.mul);
console.log("after set", e.calc(0, 9), table.get(0)(3, 4));
table.set(2, null);
try { e.calc(2, 1); } catch (x) { console.log(x.name + ": " + x.message); }
try { table.set(10, null); } catch (x) { console.log(x.name + ": " + x.message); }
try { table.get(10); } catch (x) { console.log(x.name + ": " + x.message); }
try { table.set(1, () => 1); } catch (x) { console.log(x.name + ": " + x.message); }
"""
    r = run_wasm(js, code)
    assert out(r) == golden("tables_elements_and_start_function")
    assert (r.returncode, r.stderr) == (0, b"")


def test_cross_instance_memory_and_instantiate_overloads(js, golden):
    """CATCHES: instances of one Module that share globals or memory, an exported Memory that cannot be
    imported by a second module (or is copied rather than shared), Module.exports/imports
    descriptors with wrong kinds, or instantiate() returning the wrong shape for a Module versus
    raw bytes."""
    code = r"""
// producer exports memory + a counter; consumer imports the producer's memory
const producer = mod({
  types: [[["i32", "i32"], []], [[], ["i32"]]],
  mems: [[0x00, 1]],
  globals: [[0x7f, 0x01, ...asm("i32.const 0"), 0x0b]],
  funcs: [
    { type: 0, code: "local.get 0 local.get 1 i32.store" },
    { type: 1, code: "global.get 0 i32.const 1 i32.add global.set 0 global.get 0" },
  ],
  exports: [["memory", MEM, 0], ["put", FN, 0], ["tick", FN, 1]],
});
const consumer = mod({
  types: [[["i32"], ["i32"]]],
  imports: [["lib", "memory", [0x02, 0x00, 1]]],
  funcs: [{ type: 0, code: "local.get 0 i32.load local.get 0 i32.load offset=4 i32.add" }],
  exports: [["sum2", FN, 0]],
});
const pm = new WebAssembly.Module(producer);
const a = new WebAssembly.Instance(pm), b = new WebAssembly.Instance(pm);
console.log("independent", a.exports.tick(), a.exports.tick(), a.exports.tick(), b.exports.tick());
a.exports.put(8, 40); a.exports.put(12, 2);
const c = new WebAssembly.Instance(new WebAssembly.Module(consumer), { lib: { memory: a.exports.memory } });
console.log("shared", c.exports.sum2(8), "b untouched", new Int32Array(b.exports.memory.buffer)[2], "a view", new Int32Array(a.exports.memory.buffer)[2]);
console.log("Module.exports", WebAssembly.Module.exports(pm).map((d) => d.kind + ":" + d.name).join(","), "imports", WebAssembly.Module.imports(new WebAssembly.Module(consumer)).map((d) => `${d.module}.${d.name}:${d.kind}`).join(","));
console.log("customSections", JSON.stringify(WebAssembly.Module.customSections(pm, "name")));
const r = await WebAssembly.instantiate(pm);
console.log("instantiate(Module) returns Instance:", r instanceof WebAssembly.Instance, "module" in r);
const r2 = await WebAssembly.instantiate(producer);
console.log("instantiate(bytes):", Object.keys(r2).sort().join(","), r2.module instanceof WebAssembly.Module);
"""
    r = run_wasm(js, code)
    assert out(r) == golden("cross_instance_memory_and_instantiate_overloads")
    assert (r.returncode, r.stderr) == (0, b"")


def test_control_flow_blocks_loops_branches(js, golden):
    """CATCHES: an interpreter with wrong branch targets or label arity: loop/br_if back-edges,
    br_table default arm, values carried out of a block by br_if, early return from a loop,
    select operand order, multi-value returns and block parameters, if without else in both
    directions, or code after br being executed."""
    code = r"""
const T = { ii_i: 0, i_i: 1, i64_i64: 2, ii_ii: 3, v_i: 4 };
const funcs = {
  // iterative factorial with loop + br_if (i64)
  fac: { type: T.i64_i64, locals: [[1, "i64"]], code: `
    i64.const 1 local.set 1
    block
      loop
        local.get 0 i64.eqz br_if 1
        local.get 1 local.get 0 i64.mul local.set 1
        local.get 0 i64.const 1 i64.sub local.set 0
        br 0
      end
    end
    local.get 1` },
  // recursive fibonacci via call and if-with-result as the final expression
  fib: { type: T.i_i, code: `
    local.get 0 i32.const 2 i32.lt_s
    if i32
      local.get 0
    else
      local.get 0 i32.const 1 i32.sub call 1
      local.get 0 i32.const 2 i32.sub call 1
      i32.add
    end` },
  // br_table switch with a default arm
  classify: { type: T.i_i, code: `
    block
      block
        block
          block
            local.get 0
            br_table 0,1,2 3
          end
          i32.const 100 return
        end
        i32.const 101 return
      end
      i32.const 102 return
    end
    i32.const 999` },
  max: { type: T.ii_i, code: "local.get 0 local.get 1 local.get 0 local.get 1 i32.gt_s select" },
  // a value carried out of a block by br_if
  pick: { type: T.i_i, code: "block i32 i32.const 5 local.get 0 br_if 0 drop i32.const 7 end" },
  // nested loops: sum of i*j for i < a, j < b
  grid: { type: T.ii_i, locals: [[3, "i32"]], code: `
    loop
      i32.const 0 local.set 3
      block
        loop
          local.get 3 local.get 1 i32.ge_s br_if 1
          local.get 4 local.get 2 local.get 3 i32.mul i32.add local.set 4
          local.get 3 i32.const 1 i32.add local.set 3
          br 0
        end
      end
      local.get 2 i32.const 1 i32.add local.tee 2
      local.get 0 i32.lt_s br_if 0
    end
    local.get 4` },
  // early return from inside a loop: first i with i*i >= n
  isqrt: { type: T.i_i, locals: [[1, "i32"]], code: `
    loop
      local.get 1 local.get 1 i32.mul local.get 0 i32.ge_s
      if
        local.get 1 return
      end
      local.get 1 i32.const 1 i32.add local.set 1
      br 0
    end
    i32.const -1` },
  // collatz step count, branch-free body using select
  collatz: { type: T.i_i, locals: [[1, "i32"]], code: `
    block
      loop
        local.get 0 i32.const 1 i32.le_s br_if 1
        local.get 0 i32.const 3 i32.mul i32.const 1 i32.add
        local.get 0 i32.const 1 i32.shr_u
        local.get 0 i32.const 1 i32.and
        select local.set 0
        local.get 1 i32.const 1 i32.add local.set 1
        br 0
      end
    end
    local.get 1` },
  // multi-value: quotient and remainder
  divmod: { type: T.ii_ii, code: "local.get 0 local.get 1 i32.div_u local.get 0 local.get 1 i32.rem_u" },
  // a block with parameters (multi-value block type) that swaps and subtracts
  swapsub: { type: T.ii_i, code: "local.get 0 local.get 1 block type=3 local.set 0 local.set 1 local.get 0 local.get 1 end i32.sub" },
  // if without else, both directions; nop/drop
  flags: { type: T.i_i, locals: [[1, "i32"]], code: `
    nop
    local.get 0 i32.const 1 i32.and if local.get 1 i32.const 10 i32.add local.set 1 end
    local.get 0 i32.const 2 i32.and if local.get 1 i32.const 200 i32.add local.set 1 end
    i32.const 12345 drop
    local.get 1` },
  // br out of two nested blocks skips the unreachable
  skip: { type: T.v_i, code: "block i32 block i32.const 9 br 1 unreachable end i32.const 0 end" },
};
const names = Object.keys(funcs);
const bytes = mod({
  types: [[["i32", "i32"], ["i32"]], [["i32"], ["i32"]], [["i64"], ["i64"]], [["i32", "i32"], ["i32", "i32"]], [[], ["i32"]]],
  funcs: names.map((n) => funcs[n]),
  exports: names.map((n, i) => [n, FN, i]),
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
console.log("fac", [0n, 1n, 5n, 20n, 21n].map((n) => String(e.fac(n))).join(" "));
console.log("fib", [0, 1, 2, 10, 20].map(e.fib).join(" "));
console.log("classify", [0, 1, 2, 3, -1, 77].map(e.classify).join(" "));
console.log("max", e.max(3, 9), e.max(-3, -9), "pick", e.pick(1), e.pick(0));
console.log("grid", e.grid(3, 4), e.grid(10, 10), "isqrt", [0, 1, 15, 16, 17, 1000].map(e.isqrt).join(" "));
console.log("collatz", [1, 6, 7, 27, 97].map(e.collatz).join(" "));
console.log("divmod", JSON.stringify(e.divmod(47, 5)), "swapsub", e.swapsub(10, 3), "flags", [0, 1, 2, 3].map(e.flags).join(" "), "skip", e.skip());
"""
    r = run_wasm(js, code)
    assert out(r) == golden("control_flow_blocks_loops_branches")
    assert (r.returncode, r.stderr) == (0, b"")


def test_compile_errors_and_validate(js, golden):
    """CATCHES: a decoder that accepts malformed binaries (bad magic/version, truncation, unknown or
    duplicate sections, size mismatches, bad type/import/export/segment encodings, invalid UTF-8
    names, LEB128 overflow) or reports them as anything other than CompileError, and validate()
    that throws or returns true for them."""
    code = r"""
const H = [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00];
const sec = (id, body) => [id, ...uleb(body.length), ...body];
const okType = sec(1, vec([[0x60, 0, 0]]));
const cases = {
  "bad magic": [0x00, 0x61, 0x73, 0x6e, 1, 0, 0, 0],
  "version 2": [0x00, 0x61, 0x73, 0x6d, 2, 0, 0, 0],
  "short header": [0x00, 0x61, 0x73],
  "unknown section": [...H, ...sec(13, [])],
  "out of order": [...H, ...sec(7, vec([])), ...okType],
  "duplicate section": [...H, ...okType, ...okType],
  "overrun": [...H, 1, 10, 1, 0x60],
  "size mismatch": [...H, 1, 5, 1, 0x60, 0, 0, 0],
  "bad functype": [...H, ...sec(1, vec([[0x61, 0, 0]]))],
  "bad valtype": [...H, ...sec(1, vec([[0x60, 1, 0x55, 0]]))],
  "type index": [...H, ...okType, ...sec(3, vec([[1]]))],
  "import kind": [...H, ...sec(2, vec([[...name("a"), ...name("b"), 0x04, 0]]))],
  "export kind": [...H, ...sec(7, vec([[...name("x"), 0x05, 0]]))],
  "bad utf8 name": [...H, ...sec(7, vec([[1, 0xff, 0x00, 0]]))],
  "count mismatch": [...H, ...okType, ...sec(3, vec([[0], [0]])), ...sec(10, vec([[2, 0, 0x0b]]))],
  "no end": [...H, ...okType, ...sec(3, vec([[0]])), ...sec(10, vec([[2, 0, 0x01]]))],
  "elem kind": [...H, ...sec(9, vec([[0x08]]))],
  "data kind": [...H, ...sec(11, vec([[0x03]]))],
  "const expr": [...H, ...sec(6, vec([[0x7f, 0x00, 0x6a, 0x0b]]))],
  "leb overflow": [...H, 1, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01],
  "truncated name": [...H, ...sec(7, [1, 5, 0x61])],
  "const leb overflow": [...H, ...sec(6, vec([[0x7e, 0x00, 0x42, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x00, 0x0b]]))],
  "code body overrun": [...H, ...okType, ...sec(3, vec([[0]])), 10, 3, 1, 100, 0],
};
for (const [label, b] of Object.entries(cases)) {
  const bytes = new Uint8Array(b);
  let msg;
  try { new WebAssembly.Module(bytes); msg = "compiled"; } catch (e) { msg = `${e instanceof WebAssembly.CompileError} ${e.name}: ${e.message}`; }
  console.log(label.padEnd(18), WebAssembly.validate(bytes), msg);
}
console.log("empty module", WebAssembly.validate(new Uint8Array(H)), "ArrayBuffer", WebAssembly.validate(new Uint8Array(H).buffer));
const exp = (kind, idx, extra = []) => new Uint8Array([...H, ...extra, ...sec(7, vec([[...name("x"), kind, idx]]))]);
const withMem = sec(5, vec([[0x00, 1]])), withTable = sec(4, vec([[0x70, 0x00, 1]])), withGlobal = sec(6, vec([[0x7f, 0x00, 0x41, 0x00, 0x0b]]));
console.log("export index checks", [exp(0x00, 3), exp(0x01, 0), exp(0x01, 0, withTable), exp(0x02, 0), exp(0x02, 0, withMem), exp(0x03, 1, withGlobal), exp(0x03, 0, withGlobal)].map((b) => WebAssembly.validate(b)).join(" "));
try { new WebAssembly.Module("not bytes"); } catch (e) { console.log(e.name + ": " + e.message); }
try { new WebAssembly.Instance({}); } catch (e) { console.log(e.name + ": " + e.message); }
await WebAssembly.compile(new Uint8Array([1, 2, 3, 4])).catch((e) => console.log("compile rejects", e instanceof WebAssembly.CompileError, e.message));
await WebAssembly.instantiate(new Uint8Array([...H, 99])).catch((e) => console.log("instantiate rejects", e.name, e.message));
console.log("error classes", WebAssembly.CompileError.name, new WebAssembly.LinkError("m") instanceof Error, new WebAssembly.RuntimeError("r").message);
"""
    r = run_wasm(js, code)
    assert out(r) == golden("compile_errors_and_validate")
    assert (r.returncode, r.stderr) == (0, b"")


def test_instantiation_failures(js, golden):
    """CATCHES: instantiation that silently ignores data/element segments falling outside memory or
    table bounds, segments with no memory/table to target, or element entries naming missing
    functions, and a trapping start function whose RuntimeError is swallowed."""
    code = r"""
const cases = {
  "data out of bounds": mod({ mems: [[0x00, 1]], data: [[0x00, ...asm("i32.const 65534"), 0x0b, ...vec([1, 2, 3])]] }),
  "data without memory": mod({ data: [[0x00, ...asm("i32.const 0"), 0x0b, ...vec([1])]] }),
  "elem out of bounds": mod({ types: [[[], []]], funcs: [{ type: 0, code: "" }], tables: [[0x70, 0x00, 1]], elems: [[0x00, ...asm("i32.const 1"), 0x0b, ...vec([uleb(0)])]] }),
  "elem without table": mod({ types: [[[], []]], funcs: [{ type: 0, code: "" }], elems: [[0x00, ...asm("i32.const 0"), 0x0b, ...vec([uleb(0)])]] }),
  "elem bad func": mod({ types: [[[], []]], funcs: [{ type: 0, code: "" }], tables: [[0x70, 0x00, 2]], elems: [[0x00, ...asm("i32.const 0"), 0x0b, ...vec([uleb(5)])]] }),
  "start traps": mod({ types: [[[], []]], funcs: [{ type: 0, code: "i32.const 1 i32.const 0 i32.div_u drop" }], start: 0 }),
};
for (const [label, bytes] of Object.entries(cases)) {
  try { new WebAssembly.Instance(new WebAssembly.Module(bytes)); console.log(label, "instantiated"); }
  catch (e) { console.log(label.padEnd(20), e instanceof Error, label === "start traps" ? e.name : "-", e.message); }
}
"""
    r = run_wasm(js, code)
    assert out(r) == golden("instantiation_failures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_argument_coercion_into_wasm(js, golden):
    """CATCHES: exported-function wrappers that do not apply ToInt32 (wrapping 2**32+5, truncating
    3.9/-3.9, NaN/undefined to 0), round f32 parameters, accept BigInt extremes for i64, or
    mishandle missing and surplus arguments."""
    code = r"""
const bytes = mod({
  types: [[["i32"], ["i32"]], [["f32"], ["f32"]], [["f64"], ["f64"]], [["i64"], ["i64"]], [["i32", "i32"], ["i32"]]],
  funcs: [{ type: 0, code: "local.get 0" }, { type: 1, code: "local.get 0" }, { type: 2, code: "local.get 0" }, { type: 3, code: "local.get 0" }, { type: 4, code: "local.get 0 local.get 1 i32.sub" }],
  exports: [["i32", FN, 0], ["f32", FN, 1], ["f64", FN, 2], ["i64", FN, 3], ["sub", FN, 4]],
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
console.log("i32", [4294967301, -1, 3.9, -3.9, "12", true, null, undefined, NaN, 2147483648].map(e.i32).join(" "));
console.log("f32", [0.1, 16777217, 1e39, "2.5"].map(e.f32).join(" "));
console.log("f64", [0.1, "1e3", undefined].map(e.f64).join(" "));
console.log("i64", [0n, -1n, 9223372036854775807n, -9223372036854775808n].map((x) => String(e.i64(x))).join(" "));
console.log("missing args", e.sub(), e.sub(5), "extra args", e.sub(5, 2, 100));
console.log("export fn", typeof e.i32, e.i32 === e.i32);
"""
    r = run_wasm(js, code)
    assert out(r) == golden("argument_coercion_into_wasm")
    assert (r.returncode, r.stderr) == (0, b"")


def test_module_reflection_all_kinds(js, golden):
    """CATCHES: Module.imports()/exports() that report the wrong kind for table, memory, global or
    function entries, an instance that does not re-export imported entities (the same Memory
    object, the imported global's value), or exports keyed by the wrong names."""
    code = r"""
const bytes = mod({
  types: [[[], []]],
  imports: [["js", "tbl", [0x01, 0x70, 0x00, 1]], ["js", "mem", [0x02, 0x00, 1]], ["js", "g", [0x03, 0x7c, 0x00]], ["js", "fn", [0x00, 0]]],
  funcs: [{ type: 0, code: "call 0" }],
  globals: [[0x7e, 0x00, ...asm("i64.const 99"), 0x0b]],
  exports: [["run", FN, 1], ["table", TABLE, 0], ["memory", MEM, 0], ["imported_g", GLOBAL, 0], ["own_g", GLOBAL, 1], ["raw_import", FN, 0]],
});
const m = new WebAssembly.Module(bytes);
for (const d of WebAssembly.Module.imports(m)) console.log("import", d.module, d.name, d.kind);
for (const d of WebAssembly.Module.exports(m)) console.log("export", d.name, d.kind);
let calls = 0;
const tbl = new WebAssembly.Table({ initial: 1, element: "anyfunc" });
const mem = new WebAssembly.Memory({ initial: 1 });
const inst = new WebAssembly.Instance(m, { js: { tbl, mem, g: 2.5, fn: () => calls++ } });
const x = inst.exports;
x.run(); x.raw_import();
console.log("calls", calls, "table", x.table instanceof WebAssembly.Table, x.table.length, "memory", x.memory === mem, "g", x.imported_g.value, String(x.own_g.value));
console.log("keys", Object.keys(x).sort().join(","));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("module_reflection_all_kinds")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sieve_and_string_reversal_program(js, golden):
    """CATCHES: an engine that breaks on a realistic nested-loop program (byte stores in an inner loop,
    unsigned comparisons, early-exit blocks) or that loses JS writes into exported memory before
    a call that rewrites them in place."""
    code = r"""
// sieve(n): marks composites in memory[0..n), returns the prime count; rev(ptr, len) reverses bytes in place
const bytes = mod({
  types: [[["i32"], ["i32"]], [["i32", "i32"], []]],
  mems: [[0x00, 1]],
  funcs: [
    { type: 0, locals: [[3, "i32"]], code: `
      i32.const 2 local.set 1
      block
        loop
          local.get 1 local.get 0 i32.ge_u br_if 1
          local.get 1 i32.load8_u i32.eqz
          if
            local.get 3 i32.const 1 i32.add local.set 3
            local.get 1 local.get 1 i32.mul local.set 2
            block
              loop
                local.get 2 local.get 0 i32.ge_u br_if 1
                local.get 2 i32.const 1 i32.store8
                local.get 2 local.get 1 i32.add local.set 2
                br 0
              end
            end
          end
          local.get 1 i32.const 1 i32.add local.set 1
          br 0
        end
      end
      local.get 3` },
    { type: 1, locals: [[2, "i32"]], code: `
      local.get 0 local.get 1 i32.add i32.const 1 i32.sub local.set 1
      block
        loop
          local.get 0 local.get 1 i32.ge_u br_if 1
          local.get 0 i32.load8_u local.set 2
          local.get 0 local.get 1 i32.load8_u i32.store8
          local.get 1 local.get 2 i32.store8
          local.get 0 i32.const 1 i32.add local.set 0
          local.get 1 i32.const 1 i32.sub local.set 1
          br 0
        end
      end` },
  ],
  exports: [["sieve", FN, 0], ["rev", FN, 1], ["memory", MEM, 0]],
});
const { instance } = await WebAssembly.instantiate(bytes);
const { sieve, rev, memory } = instance.exports;
console.log("primes below 1000:", sieve(1000));
const flags = new Uint8Array(memory.buffer, 0, 60);
console.log("primes below 60:", [...flags.keys()].filter((i) => i >= 2 && flags[i] === 0).join(","));
new Uint8Array(memory.buffer).fill(0, 0, 1000);
console.log("primes below 20000:", sieve(20000));
const text = new TextEncoder().encode("Hello, WebAssembly!");
new Uint8Array(memory.buffer).set(text, 60000);
rev(60000, text.length);
console.log("reversed:", new TextDecoder().decode(new Uint8Array(memory.buffer, 60000, text.length)));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("sieve_and_string_reversal_program")
    assert (r.returncode, r.stderr) == (0, b"")


def test_misc_constants_locals_loop_params(js, golden):
    """CATCHES: signed-LEB128 immediates decoded wrongly at 7-bit boundaries (63/64/-64/-65, i32/i64
    extremes), declared locals of each type not zero-initialised, a loop with block parameters
    that loses its value on the back-edge, or a data segment whose offset comes from an imported
    global placed at the wrong address."""
    code = r"""
const consts = [0, 1, -1, 63, 64, -64, -65, 127, 128, 8191, -8192, 2147483647, -2147483648];
const consts64 = ["0", "-1", "64", "-65", "4294967296", "-4294967297", "9223372036854775807", "-9223372036854775808"];
const funcs = [
  ...consts.map((c) => ({ type: 0, code: `i32.const ${c}` })),
  ...consts64.map((c) => ({ type: 1, code: `i64.const ${c}` })),
  // zero-initialised locals of every type, observed through reinterpretation and local.tee
  { type: 2, locals: [[1, "i32"], [2, "i64"], [1, "f32"], [1, "f64"]], code: `
    local.get 1 i32.eqz local.get 2 i64.eqz i32.add local.get 3 i64.eqz i32.add
    local.get 4 i32.reinterpret_f32 i32.eqz i32.add local.get 5 i64.reinterpret_f64 i64.eqz i32.add
    i32.const 7 local.tee 1 i32.add local.get 1 i32.add local.get 0 i32.add` },
  // loop with a parameter (multi-value block type 3: [i32] -> [i32]): doubles until >= 1000
  { type: 2, code: "i32.const 3 loop type=3 i32.const 2 i32.mul local.tee 0 local.get 0 i32.const 1000 i32.lt_u br_if 0 end" },
  // f32/f64 constants straight from the instruction stream
  { type: 4, code: "f64.const 0.1 f32.const 0.1 f64.promote_f32 f64.sub" },
  // data segment placed at an offset taken from an imported global
  { type: 0, code: "global.get 0 i32.load8_u global.get 0 i32.load8_u offset=1 i32.add" },
];
const bytes = mod({
  types: [[[], ["i32"]], [[], ["i64"]], [["i32"], ["i32"]], [["i32"], ["i32"]], [[], ["f64"]]],
  imports: [["env", "base", [0x03, 0x7f, 0x00]]],
  funcs,
  mems: [[0x00, 1]],
  data: [[0x00, ...asm("global.get 0"), 0x0b, ...vec([40, 2])]],
  exports: funcs.map((f, i) => ["f" + i, FN, i]),
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes), { env: { base: 1234 } }).exports;
const n = consts.length, m = consts64.length;
console.log("i32.const", consts.map((_, i) => e["f" + i]()).join(" "));
console.log("i64.const", consts64.map((_, i) => String(e["f" + (n + i)]())).join(" "));
console.log("locals", e["f" + (n + m)](100), "loop params", e["f" + (n + m + 1)](0), "fconst", e["f" + (n + m + 2)](), "data@global", e["f" + (n + m + 3)]());
"""
    r = run_wasm(js, code)
    assert out(r) == golden("misc_constants_locals_loop_params")
    assert (r.returncode, r.stderr) == (0, b"")


def test_reference_types_and_const_expr_globals(js, golden):
    """CATCHES: a decoder that rejects funcref/externref value types,
    ref.null/ref.func/f64.const/negative i32.const global initialisers or externref tables, a
    funcref global that does not read back as null, or an imported function with a funcref
    result that cannot be called."""
    code = r"""
const bytes = mod({
  types: [[[], ["i32"]], [[], ["funcref"]]],
  imports: [["env", "nothing", [0x00, 1]]],
  funcs: [{ type: 0, locals: [[1, "funcref"], [1, "i32"]], code: "call 0 drop local.get 1 i32.const 5 i32.add" }],
  tables: [[0x6f, 0x00, 2]],
  globals: [
    [0x70, 0x00, 0xd0, 0x70, 0x0b],
    [0x70, 0x00, 0xd2, 0x01, 0x0b],
    [0x7c, 0x00, ...asm("f64.const -1.5"), 0x0b],
    [0x7f, 0x00, ...asm("i32.const -300"), 0x0b],
  ],
  exports: [["five", FN, 1], ["nullref", GLOBAL, 0], ["ext", TABLE, 0], ["f64g", GLOBAL, 2], ["negg", GLOBAL, 3]],
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes), { env: { nothing: () => null } }).exports;
console.log(e.five(), e.nullref.value, e.ext.length, e.ext.get(1), e.f64g.value, e.negg.value);
"""
    r = run_wasm(js, code)
    assert out(r) == golden("reference_types_and_const_expr_globals")
    assert (r.returncode, r.stderr) == (0, b"")


def test_mixed_signatures_and_mutual_recursion(js, golden):
    """CATCHES: calls that bind mixed i32/i64/f32/f64 parameters to the wrong locals or convert them
    inexactly, mutual recursion through call that loses results or the call-frame state (500
    frames deep), or recursive i64 multiplication that does not wrap at 64 bits."""
    code = r"""
// Mixed-type signatures, mutual recursion and an i64 counter threaded through calls.
const bytes = mod({
  types: [[["i32", "i64", "f32", "f64"], ["f64"]], [["i32"], ["i32"]], [["i64", "i32"], ["i64"]]],
  funcs: [
    // mix(a, b, c, d) = a + f64(b) + f64(c) * d
    { type: 0, locals: [[1, "f64"]], code: "local.get 0 f64.convert_i32_s local.get 1 f64.convert_i64_s f64.add local.get 2 f64.promote_f32 local.get 3 f64.mul f64.add local.tee 4 local.get 4 f64.add f64.const 2 f64.div" },
    // isEven(n) = n == 0 ? 1 : isOdd(n - 1); isOdd(n) = n == 0 ? 0 : isEven(n - 1)
    { type: 1, code: "local.get 0 i32.eqz if i32 i32.const 1 else local.get 0 i32.const 1 i32.sub call 2 end" },
    { type: 1, code: "local.get 0 i32.eqz if i32 i32.const 0 else local.get 0 i32.const 1 i32.sub call 1 end" },
    // pow(base, exp) by repeated multiplication through a recursive call
    { type: 2, code: "local.get 1 i32.eqz if i64 i64.const 1 else local.get 0 local.get 0 local.get 1 i32.const 1 i32.sub call 3 i64.mul end" },
  ],
  exports: [["mix", FN, 0], ["isEven", FN, 1], ["isOdd", FN, 2], ["pow", FN, 3]],
});
const e = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports;
console.log("mix", e.mix(1, 2n, 0.5, 4), e.mix(-7, -9007199254740993n, 1.1, 10), e.mix(2147483647, 1n, -0.25, 0.5));
console.log("parity", [0, 1, 2, 7, 100, 501].map((n) => `${n}:${e.isEven(n)}${e.isOdd(n)}`).join(" "));
console.log("pow", String(e.pow(2n, 10)), String(e.pow(3n, 40)), String(e.pow(-2n, 63)), String(e.pow(2n, 64)), String(e.pow(7n, 0)));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("mixed_signatures_and_mutual_recursion")
    assert (r.returncode, r.stderr) == (0, b"")


def test_async_api_promises(js, golden):
    """CATCHES: WebAssembly.compile/instantiate that return non-Promise values, settle synchronously
    before the current script finishes, resolve to the wrong objects, or reject with something
    other than CompileError for a truncated binary."""
    code = r"""
const bytes = mod({ types: [[[], ["i32"]]], funcs: [{ type: 0, code: "i32.const 42" }], exports: [["answer", FN, 0]] });
const log = [];
const p1 = WebAssembly.compile(bytes);
const p2 = WebAssembly.instantiate(bytes);
const p3 = WebAssembly.instantiate(new Uint8Array([0, 97, 115, 109, 1, 0, 0])).then(() => "fulfilled", (e) => `${e.constructor === WebAssembly.CompileError} ${e.message}`);
log.push("sync code runs before any settlement");
p1.then(() => log.push("compile settled"));
console.log("returns promises", p1 instanceof Promise, p2 instanceof Promise, p3 instanceof Promise);
const m = await p1;
console.log("compiled", m instanceof WebAssembly.Module, Object.getPrototypeOf(m) === WebAssembly.Module.prototype);
const { instance, module } = await p2;
console.log("instantiated", instance.exports.answer(), module instanceof WebAssembly.Module);
console.log("rejected", await p3);
const again = await WebAssembly.instantiate(m);
console.log("from module", again.exports.answer(), again instanceof WebAssembly.Instance);
console.log(log.join(" | "));
"""
    r = run_wasm(js, code)
    assert out(r) == golden("async_api_promises")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_hot_js_driver_tier_equivalence(js, golden, tier):
    """CATCHES: JS tiers (JIT, bytecode, tree-walker) that disagree when a hot loop calls a wasm export
    which itself calls back into a JS import, e.g. a compiled call path that drops the i32
    result or corrupts the closure state updated by the import."""
    code = r"""
// A hot JS driver loop calling wasm exports (JS tiers up around the calls) plus a JS import
// called from wasm on every iteration.
let acc = 0;
const bytes = mod({
  types: [[["i32", "i32"], ["i32"]], [["i32"], []]],
  imports: [["env", "sink", [0x00, 1]]],
  funcs: [{ type: 0, code: "local.get 0 i32.const 31 i32.mul local.get 1 i32.add local.get 0 i32.const 3 i32.shr_u i32.xor local.tee 0 call 0 local.get 0" }],
  exports: [["mix", FN, 1]],
});
const { mix } = new WebAssembly.Instance(new WebAssembly.Module(bytes), { env: { sink: (v) => { acc = (acc + (v & 0xffff)) % 1000003; } } }).exports;
function drive(n) {
  let h = 17;
  for (let i = 0; i < n; i++) h = mix(h, i + 31) | 0;
  return h;
}
const results = [];
for (let round = 0; round < 12; round++) results.push(drive(40 + round));
console.log(results.join(" "));
console.log("acc", acc);
"""
    r = run_wasm(js, code, *tier)
    assert out(r) == golden("hot_js_driver")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_uncaught_trap_exits_with_runtime_error(js, tier):
    """CATCHES: a trap escaping to the top level of a CommonJS script that is not reported as an
    uncaught WebAssembly RuntimeError (wrong name, wrapped as a plain Error, or the process exiting
    0), or code after the trapping call still running, in any JS tier."""
    code = r"""
const e = new WebAssembly.Instance(new WebAssembly.Module(mod({
  types: [[["i32"], ["i32"]]],
  funcs: [{ type: 0, code: "local.get 0 i32.eqz if unreachable end local.get 0 i32.const 2 i32.mul" }],
  exports: [["f", FN, 0]],
}))).exports;
console.log("f(21) =", e.f(21));
console.log("f(-4) =", e.f(-4));
e.f(0);
console.log("after");
"""
    r = run_wasm(js, code, *tier, name="main.js")
    assert out(r) == "f(21) = 42\nf(-4) = -8\n"
    assert (r.returncode, err(r)) == (1, "Uncaught RuntimeError: wasm: unreachable executed\n")


def test_uncaught_exception_from_import_propagates(js):
    """CATCHES: an exception thrown by an imported JS function that is converted into a generic wasm
    trap (or swallowed) instead of propagating unchanged through the wasm frame to the top level
    with its original class and message."""
    code = r"""
const bytes = mod({ types: [[["i32"], []]], imports: [["env", "check", [0x00, 0]]],
  funcs: [{ type: 0, code: "local.get 0 call 0" }], exports: [["go", FN, 1]] });
const { go } = new WebAssembly.Instance(new WebAssembly.Module(bytes), {
  env: { check: (n) => { if (n > 2) throw new RangeError("too big: " + n); console.log("ok", n); } },
}).exports;
for (let i = 1; i < 10; i++) go(i);
console.log("not reached");
"""
    r = run_wasm(js, code, name="main.js")
    assert out(r) == "ok 1\nok 2\n"
    assert (r.returncode, err(r)) == (1, "Uncaught RangeError: too big: 3\n")
