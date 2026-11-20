"""WebAssembly JS API of lumen-cli: validate/compile/instantiate of hand-assembled modules (built
by a tiny assembler embedded in each script), numeric semantics, memory/tables/globals/imports,
traps and CompileError/LinkError/RuntimeError messages."""

from conftest import check_script, resources_for

G = resources_for(__file__)

# A tiny wasm binary assembler shared by the scripts below (LEB128, sections, a text-ish
# instruction encoder). It only produces bytes; everything observable comes from the runtime.
ASM = r'''
// Tiny wasm binary assembler: wasm({type, import, func, table, memory, global, export, start, elem, code, data}).
const U = (n) => { const o = []; n = Number(n); do { let b = n % 128; n = Math.floor(n / 128); if (n) b |= 0x80; o.push(b); } while (n); return o; };
const S = (v) => { let n = BigInt(v); const o = []; for (;;) { const b = Number(n & 0x7fn); n >>= 7n; if ((n === 0n && !(b & 0x40)) || (n === -1n && (b & 0x40))) { o.push(b); return o; } o.push(b | 0x80); } };
const STR = (x) => { const b = [...new TextEncoder().encode(x)]; return [...U(b.length), ...b]; };
const VEC = (items) => [...U(items.length), ...items.flat()];
const T = { i32: 0x7f, i64: 0x7e, f32: 0x7d, f64: 0x7c, funcref: 0x70, void: 0x40 };
const NUMERIC = ('i32.eqz i32.eq i32.ne i32.lt_s i32.lt_u i32.gt_s i32.gt_u i32.le_s i32.le_u i32.ge_s i32.ge_u ' +
  'i64.eqz i64.eq i64.ne i64.lt_s i64.lt_u i64.gt_s i64.gt_u i64.le_s i64.le_u i64.ge_s i64.ge_u ' +
  'f32.eq f32.ne f32.lt f32.gt f32.le f32.ge f64.eq f64.ne f64.lt f64.gt f64.le f64.ge ' +
  'i32.clz i32.ctz i32.popcnt i32.add i32.sub i32.mul i32.div_s i32.div_u i32.rem_s i32.rem_u i32.and i32.or i32.xor i32.shl i32.shr_s i32.shr_u i32.rotl i32.rotr ' +
  'i64.clz i64.ctz i64.popcnt i64.add i64.sub i64.mul i64.div_s i64.div_u i64.rem_s i64.rem_u i64.and i64.or i64.xor i64.shl i64.shr_s i64.shr_u i64.rotl i64.rotr ' +
  'f32.abs f32.neg f32.ceil f32.floor f32.trunc f32.nearest f32.sqrt f32.add f32.sub f32.mul f32.div f32.min f32.max f32.copysign ' +
  'f64.abs f64.neg f64.ceil f64.floor f64.trunc f64.nearest f64.sqrt f64.add f64.sub f64.mul f64.div f64.min f64.max f64.copysign ' +
  'i32.wrap_i64 i32.trunc_f32_s i32.trunc_f32_u i32.trunc_f64_s i32.trunc_f64_u i64.extend_i32_s i64.extend_i32_u ' +
  'i64.trunc_f32_s i64.trunc_f32_u i64.trunc_f64_s i64.trunc_f64_u f32.convert_i32_s f32.convert_i32_u f32.convert_i64_s ' +
  'f32.convert_i64_u f32.demote_f64 f64.convert_i32_s f64.convert_i32_u f64.convert_i64_s f64.convert_i64_u f64.promote_f32 ' +
  'i32.reinterpret_f32 i64.reinterpret_f64 f32.reinterpret_i32 f64.reinterpret_i64 ' +
  'i32.extend8_s i32.extend16_s i64.extend8_s i64.extend16_s i64.extend32_s').split(' ');
const MEMOPS = ('i32.load i64.load f32.load f64.load i32.load8_s i32.load8_u i32.load16_s i32.load16_u i64.load8_s i64.load8_u ' +
  'i64.load16_s i64.load16_u i64.load32_s i64.load32_u i32.store i64.store f32.store f64.store i32.store8 i32.store16 ' +
  'i64.store8 i64.store16 i64.store32').split(' ');
const SIMPLE = { unreachable: 0x00, nop: 0x01, else: 0x05, end: 0x0b, return: 0x0f, drop: 0x1a, select: 0x1b };
const IDX = { br: 0x0c, br_if: 0x0d, call: 0x10, 'local.get': 0x20, 'local.set': 0x21, 'local.tee': 0x22, 'global.get': 0x23, 'global.set': 0x24 };
const FC = { 'i32.trunc_sat_f32_s': 0, 'i32.trunc_sat_f32_u': 1, 'i32.trunc_sat_f64_s': 2, 'i32.trunc_sat_f64_u': 3,
  'i64.trunc_sat_f32_s': 4, 'i64.trunc_sat_f32_u': 5, 'i64.trunc_sat_f64_s': 6, 'i64.trunc_sat_f64_u': 7 };
const isNum = (t) => t !== undefined && /^-?(\d|nan|inf)/i.test(t);
const num = (t) => (/^-?nan$/i.test(t) ? NaN : /^-?inf$/i.test(t) ? (t[0] === '-' ? -Infinity : Infinity) : Number(t));
function asm(text) {
  const tk = text.trim().split(/\s+/).filter(Boolean);
  const out = [];
  for (let i = 0; i < tk.length; i++) {
    const t = tk[i];
    if (t in SIMPLE) out.push(SIMPLE[t]);
    else if (t in IDX) out.push(IDX[t], ...U(tk[++i]));
    else if (t === 'block' || t === 'loop' || t === 'if') {
      const bt = tk[i + 1] in T ? T[tk[++i]] : isNum(tk[i + 1]) ? S(tk[++i]) : 0x40;
      out.push({ block: 0x02, loop: 0x03, if: 0x04 }[t], ...[bt].flat());
    } else if (t === 'br_table') { const ls = []; while (isNum(tk[i + 1])) ls.push(Number(tk[++i])); const d = ls.pop(); out.push(0x0e, ...VEC(ls.map(U)), ...U(d)); }
    else if (t === 'call_indirect') out.push(0x11, ...U(tk[++i]), ...U(tk[++i]));
    else if (t === 'i32.const' || t === 'i64.const') out.push(t === 'i32.const' ? 0x41 : 0x42, ...S(tk[++i]));
    else if (t === 'f32.const') out.push(0x43, ...new Uint8Array(new Float32Array([num(tk[++i])]).buffer));
    else if (t === 'f64.const') out.push(0x44, ...new Uint8Array(new Float64Array([num(tk[++i])]).buffer));
    else if (MEMOPS.includes(t)) out.push(0x28 + MEMOPS.indexOf(t), ...U(tk[++i]), ...U(tk[++i]));
    else if (t === 'memory.size' || t === 'memory.grow') out.push(t === 'memory.size' ? 0x3f : 0x40, 0);
    else if (t === 'memory.copy') out.push(0xfc, 10, 0, 0);
    else if (t === 'memory.fill') out.push(0xfc, 11, 0);
    else if (t in FC) out.push(0xfc, FC[t]);
    else if (NUMERIC.includes(t)) out.push(0x45 + NUMERIC.indexOf(t));
    else if (/^0x[0-9a-f]+$/i.test(t)) out.push(Number(t));
    else throw new Error('asm: unknown token ' + t);
  }
  return out;
}
const functype = (params, results) => [0x60, ...VEC(params.map((p) => T[p])), ...VEC(results.map((r) => T[r]))];
const body = (locals, text) => { const b = [...VEC(locals.map(([n, t]) => [...U(n), T[t]])), ...asm(text), 0x0b]; return [...U(b.length), ...b]; };
const limits = (min, max) => (max === undefined ? [0, ...U(min)] : [1, ...U(min), ...U(max)]);
const KIND = { func: 0, table: 1, memory: 2, global: 3 };
const imp = (m, n, kind, desc) => [...STR(m), ...STR(n), KIND[kind], ...desc];
const exp = (n, kind, idx) => [...STR(n), KIND[kind], ...U(idx)];
const constExpr = (text) => [...asm(text), 0x0b];
const SECTION_IDS = { type: 1, import: 2, func: 3, table: 4, memory: 5, global: 6, export: 7, start: 8, elem: 9, code: 10, data: 11 };
function wasm(secs) {
  const out = [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00];
  for (const [name, id] of Object.entries(SECTION_IDS)) {
    if (secs[name] === undefined) continue;
    const content = name === 'start' ? U(secs.start) : VEC(secs[name]);
    out.push(id, ...U(content.length), ...content);
  }
  return new Uint8Array(out);
}
const errStr = (e) => (e && e.name ? e.name + ': ' + e.message : 'non-error ' + String(e));
const tryIt = (label, f) => { try { console.log(label, f()); } catch (e) { console.log(label, 'THREW', errStr(e), e instanceof WebAssembly.RuntimeError, e instanceof Error); } };
'''


def test_wasm_showcase_module_bytes(run, workdir):
    """CATCHES: a WebAssembly implementation that cannot decode a minimal literal module (type,
    function, export and code sections), returns the wrong {module, instance} shape from
    instantiate(bytes) versus an Instance from instantiate(Module), or describes exports/imports
    with the wrong descriptor objects."""
    check_script(run, workdir, G, "wasm_showcase_module_bytes", r'''
// (module (func (export "mul") (param i32 i32) (result i32) local.get 0 local.get 1 i32.mul))
const bytes = new Uint8Array([
  0, 97, 115, 109, 1, 0, 0, 0,
  1, 7, 1, 96, 2, 127, 127, 1, 127,
  3, 2, 1, 0,
  7, 7, 1, 3, 109, 117, 108, 0, 0,
  10, 9, 1, 7, 0, 32, 0, 32, 1, 108, 11,
]);
console.log(WebAssembly.validate(bytes), WebAssembly.validate(bytes.buffer), WebAssembly.validate(new DataView(bytes.buffer)));
const result = await WebAssembly.instantiate(bytes);
console.log(Object.keys(result).join(), result.module instanceof WebAssembly.Module, result.instance instanceof WebAssembly.Instance);
const { mul } = result.instance.exports;
console.log(typeof mul, mul(6, 7), mul(-3, 5), mul(65536, 65536), mul(0x7fffffff, 2));
console.log(JSON.stringify(WebAssembly.Module.exports(result.module)), JSON.stringify(WebAssembly.Module.imports(result.module)));
const again = await WebAssembly.instantiate(result.module);
console.log(again instanceof WebAssembly.Instance, again.exports.mul(2, 21), again.exports.mul !== mul);
const viaCtor = new WebAssembly.Instance(new WebAssembly.Module(bytes.buffer));
console.log(viaCtor.exports.mul(9, 9), Object.keys(viaCtor.exports).join());
const p = WebAssembly.compile(bytes);
console.log(p instanceof Promise, (await p) instanceof WebAssembly.Module, WebAssembly.Module.customSections(await p).length);
console.log(Object.keys(WebAssembly).join());
''', filename="wasm_showcase_module_bytes.mjs")


def test_wasm_integer_arithmetic_and_traps(run, workdir):
    """CATCHES: i32 arithmetic that does not wrap at 32 bits, signed/unsigned division and
    remainder mix-ups, missing 'integer divide by zero' / 'integer overflow' RuntimeError traps,
    wrong clz/ctz/popcnt/rotate/shift semantics (shift counts mod 32), or loops/locals computing
    wrong results (iterative factorial wraps mod 2^32)."""
    check_script(run, workdir, G, "wasm_integer_arithmetic_and_traps", ASM + r'''
const bin = ['i32.add', 'i32.sub', 'i32.mul', 'i32.div_s', 'i32.div_u', 'i32.rem_s', 'i32.rem_u', 'i32.and', 'i32.or', 'i32.xor', 'i32.shl', 'i32.shr_s', 'i32.shr_u', 'i32.rotl', 'i32.rotr', 'i32.lt_s', 'i32.lt_u', 'i32.ge_u'];
const un = ['i32.clz', 'i32.ctz', 'i32.popcnt', 'i32.eqz'];
const fac = 'i32.const 1 local.set 1 block loop local.get 0 i32.eqz br_if 1 local.get 1 local.get 0 i32.mul local.set 1 local.get 0 i32.const 1 i32.sub local.set 0 br 0 end end local.get 1';
const m = wasm({
  type: [functype(['i32', 'i32'], ['i32']), functype(['i32'], ['i32'])],
  func: [...bin.map(() => [0]), ...un.map(() => [1]), [1]],
  export: [...bin, ...un, 'fac'].map((n, i) => exp(n, 'func', i)),
  code: [...bin.map((o) => body([], 'local.get 0 local.get 1 ' + o)), ...un.map((o) => body([], 'local.get 0 ' + o)), body([[1, 'i32']], fac)],
});
const e = (await WebAssembly.instantiate(m)).instance.exports;
const pairs = [[7, 2], [-7, 2], [0x7fffffff, 1], [-1, 31], [1, 33], [-2147483648, -1], [5, 0]];
for (const o of bin) {
  console.log(o.padEnd(10), pairs.map(([a, b]) => { try { return e[o](a, b); } catch (err) { return err.name + '(' + err.message + ')'; } }).join(' | '));
}
for (const o of un) console.log(o.padEnd(10), [0, 1, -1, 0x80000000, 0x00f0f000].map((v) => e[o](v)).join(' '));
console.log('fac', [0, 1, 5, 10, 12, 13].map((n) => e.fac(n)).join(' '));
try { e['i32.div_s'](1, 0); } catch (err) { console.log(err instanceof WebAssembly.RuntimeError, err instanceof Error, err.constructor === WebAssembly.RuntimeError); }
''', filename="wasm_integer_arithmetic_and_traps.mjs")


def test_wasm_i64_bigint_bridge(run, workdir):
    """CATCHES: i64 values crossing the JS boundary as Numbers instead of BigInts (losing
    precision above 2^53), BigInt arguments not wrapped to 64 bits, imported JS functions not
    receiving BigInt for i64 params, i64 traps missing, or 64-bit shifts/compares being done in
    32 bits."""
    check_script(run, workdir, G, "wasm_i64_bigint_bridge", ASM + r'''
const bin = ['i64.add', 'i64.mul', 'i64.div_s', 'i64.div_u', 'i64.rem_s', 'i64.shl', 'i64.shr_s', 'i64.shr_u', 'i64.rotl'];
const m = wasm({
  type: [functype(['i64', 'i64'], ['i64']), functype(['i64'], ['i64']), functype(['i64', 'i64'], ['i32']), functype(['i32'], ['i64']), functype(['i64'], ['i32'])],
  import: [imp('env', 'cb', 'func', U(1))],
  func: [...bin.map(() => [0]), [1], [2], [3], [3], [4], [1], [1]],
  export: [...bin, 'viaJs', 'lt_u', 'ext_s', 'ext_u', 'wrap', 'clz', 'popcnt'].map((n, i) => exp(n, 'func', i + 1)),
  code: [...bin.map((o) => body([], 'local.get 0 local.get 1 ' + o)),
    body([], 'local.get 0 call 0 i64.const 1 i64.add'),
    body([], 'local.get 0 local.get 1 i64.lt_u'),
    body([], 'local.get 0 i64.extend_i32_s'),
    body([], 'local.get 0 i64.extend_i32_u'),
    body([], 'local.get 0 i32.wrap_i64'),
    body([], 'local.get 0 i64.clz'),
    body([], 'local.get 0 i64.popcnt')],
});
const seen = [];
const e = (await WebAssembly.instantiate(m, { env: { cb: (x) => { seen.push(typeof x + ':' + x); return x * 3n; } } })).instance.exports;
const show = (v) => typeof v + ':' + v;
const pairs = [[9007199254740993n, 2n], [-9n, 2n], [0x7fffffffffffffffn, 1n], [1n, 65n], [-1n, 63n]];
for (const o of bin) console.log(o.padEnd(9), pairs.map(([a, b]) => { try { return show(e[o](a, b)); } catch (err) { return err.message; } }).join(' | '));
try { e['i64.div_s'](-9223372036854775808n, -1n); } catch (err) { console.log(err.name, err.message); }
try { e['i64.rem_s'](1n, 0n); } catch (err) { console.log(err.name, err.message); }
console.log('wrap args', show(e['i64.add'](2n ** 64n + 5n, 0n)), show(e['i64.add'](-(2n ** 63n) - 1n, 0n)), show(e['i64.add'](12, 0)));
console.log('viaJs', show(e.viaJs(14n)), seen.join());
console.log('lt_u', e.lt_u(-1n, 1n), e.lt_u(1n, -1n));
console.log('extend', show(e.ext_s(-1)), show(e.ext_u(-1)), 'wrap', e.wrap(0x1ffffffffn), e.wrap(-1n));
console.log('clz/popcnt', show(e.clz(1n)), show(e.clz(0n)), show(e.popcnt(-1n)));
''', filename="wasm_i64_bigint_bridge.mjs")


def test_wasm_float_ops(run, workdir):
    """CATCHES: f32 operations computed in double precision (results must be rounded to f32),
    `nearest` not rounding half to even, wrong signed-zero handling in ceil/trunc/neg/copysign,
    division by zero not giving infinities/NaN, NaN comparisons, or wrong bit patterns from
    reinterpret/promote/demote and unsigned integer-to-float conversions."""
    check_script(run, workdir, G, "wasm_float_ops", ASM + r'''
const un64 = ['f64.abs', 'f64.neg', 'f64.ceil', 'f64.floor', 'f64.trunc', 'f64.nearest', 'f64.sqrt'];
const un32 = ['f32.abs', 'f32.neg', 'f32.ceil', 'f32.floor', 'f32.trunc', 'f32.nearest', 'f32.sqrt'];
const bin = ['f64.add', 'f64.sub', 'f64.mul', 'f64.div', 'f64.copysign', 'f32.add', 'f32.mul', 'f32.div', 'f32.copysign', 'f64.lt', 'f64.eq', 'f64.ne', 'f32.ge'];
const types = [functype(['f64'], ['f64']), functype(['f32'], ['f32']), functype(['f64', 'f64'], ['f64']), functype(['f32', 'f32'], ['f32']), functype(['f64', 'f64'], ['i32']), functype(['f32', 'f32'], ['i32'])];
const binType = (o) => (/\.(lt|eq|ne)$/.test(o) ? 4 : o === 'f32.ge' ? 5 : o.startsWith('f64') ? 2 : 3);
const ops = [...un64.map((o) => [o, 0, 'local.get 0 ' + o]), ...un32.map((o) => [o, 1, 'local.get 0 ' + o]),
  ...bin.map((o) => [o, binType(o), 'local.get 0 local.get 1 ' + o]),
  ['promote', 0, 'local.get 0 f32.demote_f64 f64.promote_f32'],
  ['bits32', 0, 'local.get 0 f32.demote_f64 i32.reinterpret_f32 f64.convert_i32_u'],
  ['bits64hi', 0, 'local.get 0 i64.reinterpret_f64 i64.const 32 i64.shr_u f64.convert_i64_u'],
  ['frombits', 0, 'i64.const 4614253070214989087 f64.reinterpret_i64'],
  ['u64conv', 0, 'i64.const -1 f64.convert_i64_u'],
  ['s64conv', 0, 'i64.const -1 f64.convert_i64_s'],
  ['u32conv', 0, 'i32.const -1 f64.convert_i32_u'],
  ['f32const', 0, 'f32.const 0.1 f64.promote_f32'],
  ['nanconst', 0, 'f64.const nan'],
];
const m = wasm({ type: types, func: ops.map(([, t]) => [t]), export: ops.map(([n], i) => exp(n, 'func', i)), code: ops.map(([, , src]) => body([], src)) });
const e = (await WebAssembly.instantiate(m)).instance.exports;
const fmt = (x) => (Object.is(x, -0) ? '-0' : String(x));
for (const o of un64) console.log(o.padEnd(12), [-2.5, -0.5, 0.5, 1.5, 2.5, -0, 2, -Infinity, NaN].map((v) => fmt(e[o](v))).join(' '));
for (const o of un32) console.log(o.padEnd(12), [-2.5, 0.5, 1.5, 2.5, 0.1, 16777217].map((v) => fmt(e[o](v))).join(' '));
for (const o of bin) console.log(o.padEnd(12), [[1, 2], [0.1, 0.2], [1, 0], [-1, 0], [0, 0], [3, -0], [NaN, 1], [2 ** 24, 1]].map(([a, b]) => fmt(e[o](a, b))).join(' '));
for (const o of ['promote', 'bits32', 'bits64hi']) console.log(o.padEnd(12), [0.1, 1, -2, 1e40].map((v) => fmt(e[o](v))).join(' '));
for (const o of ['frombits', 'u64conv', 's64conv', 'u32conv', 'f32const', 'nanconst']) console.log(o.padEnd(12), fmt(e[o](0)));
''', filename="wasm_float_ops.mjs")


def test_wasm_conversions_and_coercions(run, workdir):
    """CATCHES: wrong saturating truncation (trunc_sat) or sign-extension results, and JS-to-wasm
    argument coercion differences. Pins reference quirks: the non-saturating i32/i64.trunc_* ops
    do NOT trap on NaN/overflow (they saturate like trunc_sat), Infinity passed as an i32 becomes
    -1, and BigInt/Symbol i32 arguments become 0 instead of throwing TypeError."""
    check_script(run, workdir, G, "wasm_conversions_and_coercions", ASM + r'''
const ops = [
  ['trunc_s', 0, 'local.get 0 i32.trunc_f64_s'], ['trunc_u', 0, 'local.get 0 i32.trunc_f64_u'],
  ['trunc64', 1, 'local.get 0 i64.trunc_f64_s'], ['sat_s', 0, 'local.get 0 i32.trunc_sat_f64_s'],
  ['sat_u', 0, 'local.get 0 i32.trunc_sat_f64_u'], ['sat64_u', 1, 'local.get 0 i64.trunc_sat_f64_u'],
  ['satf32_s', 2, 'local.get 0 f32.demote_f64 i32.trunc_sat_f32_s'],
  ['ext8', 3, 'local.get 0 i32.extend8_s'], ['ext16', 3, 'local.get 0 i32.extend16_s'],
  ['ext64_8', 4, 'local.get 0 i64.extend8_s'], ['ext64_32', 4, 'local.get 0 i64.extend32_s'], ['id', 3, 'local.get 0'],
];
const m = wasm({
  type: [functype(['f64'], ['i32']), functype(['f64'], ['i64']), functype(['f64'], ['i32']), functype(['i32'], ['i32']), functype(['i64'], ['i64'])],
  func: ops.map(([, t]) => [t]), export: ops.map(([n], i) => exp(n, 'func', i)), code: ops.map(([, , src]) => body([], src)),
});
const e = (await WebAssembly.instantiate(m)).instance.exports;
const fs = ['trunc_s', 'trunc_u', 'trunc64', 'sat_s', 'sat_u', 'sat64_u', 'satf32_s'];
console.log('input'.padEnd(12), fs.join(' '));
for (const v of [1.9, -1.9, -0.5, NaN, Infinity, -Infinity, 3e9, -3e9, 2 ** 63]) console.log(String(v).padEnd(12), fs.map((f) => String(e[f](v))).join(' '));
console.log('ext8', [0x80, 0x7f, 0x1ff, 0x100].map(e.ext8).join(), 'ext16', [0x8000, 0x12345, 0xffff].map(e.ext16).join());
console.log('ext64', String(e.ext64_8(0xffn)), String(e.ext64_8(0x17fn)), String(e.ext64_32(0x80000000n)), String(e.ext64_32(0x1_7fffffffn)));
const inputs = [2 ** 32 + 5, 2 ** 31, -(2 ** 31) - 1, 2 ** 53, NaN, Infinity, -Infinity, '12', '0x10', true, null, undefined, 3.99, -3.99, [7], { valueOf: () => 9 }];
console.log('i32 coercion', inputs.map((v) => e.id(v)).join(' '));
for (const [label, v] of [['bigint', 5n], ['symbol', Symbol('s')]]) {
  try { console.log(label, e.id(v)); } catch (err) { console.log(label, 'THREW', err.name); }
}
''', filename="wasm_conversions_and_coercions.mjs")


def test_wasm_control_flow(run, workdir):
    """CATCHES: broken structured control flow: if/else with results, br_table default and
    out-of-range indices, select operand order, early return, block results via br with values,
    multi-value blocks (type-index block types), deep recursion not trapping with 'call stack
    exhausted', or unreachable not trapping with 'unreachable executed'."""
    check_script(run, workdir, G, "wasm_control_flow", ASM + r'''
const m = wasm({
  type: [functype(['i32'], ['i32']), functype([], []), functype(['i32', 'i32'], ['i32', 'i32']), functype(['i32', 'i32', 'i32'], ['i32']), functype(['i32', 'i32'], ['i32'])],
  func: [[0], [0], [0], [3], [1], [0], [4], [0], [0]],
  export: ['sign', 'brt', 'early', 'sel', 'trap', 'deep', 'swapsub', 'blockval', 'collatz'].map((n, i) => exp(n, 'func', i)),
  code: [
    body([], 'local.get 0 i32.const 0 i32.lt_s if i32 i32.const -1 else local.get 0 i32.eqz if i32 i32.const 0 else i32.const 1 end end'),
    body([], 'block block block block local.get 0 br_table 0 1 2 3 end i32.const 100 return end i32.const 200 return end i32.const 300 return end i32.const 400'),
    body([], 'local.get 0 i32.const 10 i32.gt_s if i32.const 999 return end local.get 0 i32.const 2 i32.mul'),
    body([], 'local.get 0 local.get 1 local.get 2 select'),
    body([], 'unreachable'),
    body([], 'local.get 0 i32.const 1 i32.add call 5'),
    body([], 'local.get 0 local.get 1 block 2 local.set 0 local.set 1 local.get 0 local.get 1 end i32.sub'),
    body([], 'block i32 i32.const 5 local.get 0 br_if 0 drop i32.const 6 end'),
    body([[1, 'i32']], 'block loop local.get 0 i32.const 1 i32.eq br_if 1 local.get 1 i32.const 1 i32.add local.set 1 local.get 0 i32.const 1 i32.and if local.get 0 i32.const 3 i32.mul i32.const 1 i32.add local.set 0 else local.get 0 i32.const 1 i32.shr_u local.set 0 end br 0 end end local.get 1'),
  ],
});
const e = (await WebAssembly.instantiate(m)).instance.exports;
console.log('sign', [-5, 0, 7].map(e.sign).join());
console.log('br_table', [0, 1, 2, 3, 4, 100, -1].map(e.brt).join());
console.log('early', e.early(3), e.early(11));
console.log('select', e.sel(1, 2, 1), e.sel(1, 2, 0), e.sel(1, 2, -5));
console.log('multi-value block', e.swapsub(10, 3), e.swapsub(3, 10));
console.log('br_if with value', e.blockval(1), e.blockval(0));
console.log('collatz steps', [1, 6, 7, 27].map(e.collatz).join());
for (const [label, f] of [['unreachable', () => e.trap()], ['deep recursion', () => e.deep(0)]]) {
  try { f(); } catch (err) { console.log(label, err.name, err.message, err instanceof WebAssembly.RuntimeError); }
}
console.log('still usable after trap', e.sign(-1));
''', filename="wasm_control_flow.mjs")


def test_wasm_memory_data_and_grow(run, workdir):
    """CATCHES: exported memory not exposed as WebAssembly.Memory with a live buffer, data segments
    not applied, wrong little-endian / sign-extending load widths, writes from JS not visible to
    wasm, missing 'out of bounds memory access' traps at the exact boundary, memory.grow from
    wasm/JS not returning the old page count (or -1 / RangeError past maximum), or a new buffer
    not being exposed after growth. Pins that the pre-grow ArrayBuffer is not detached."""
    check_script(run, workdir, G, "wasm_memory_data_and_grow", ASM + r'''
const ops = [
  ['load', 0, 'local.get 0 i32.load 2 0'], ['store', 1, 'local.get 0 local.get 1 i32.store 2 0'],
  ['size', 2, 'memory.size'], ['grow', 0, 'local.get 0 memory.grow'],
  ['load8s', 0, 'local.get 0 i32.load8_s 0 0'], ['load8u', 0, 'local.get 0 i32.load8_u 0 0'],
  ['load16s', 0, 'local.get 0 i32.load16_s 1 0'], ['loadOff', 0, 'local.get 0 i32.load 0 4'],
  ['load64', 3, 'local.get 0 i64.load 3 0'], ['store16', 1, 'local.get 0 local.get 1 i32.store16 1 0'],
  ['loadf64', 4, 'local.get 0 f64.load 3 0'],
];
const m = wasm({
  type: [functype(['i32'], ['i32']), functype(['i32', 'i32'], []), functype([], ['i32']), functype(['i32'], ['i64']), functype(['i32'], ['f64'])],
  func: ops.map(([, t]) => [t]), memory: [limits(1, 3)],
  export: [exp('mem', 'memory', 0), ...ops.map(([n], i) => exp(n, 'func', i))],
  code: ops.map(([, , src]) => body([], src)),
  data: [[0, ...constExpr('i32.const 16'), ...STR('Hello, wasm!')], [0, ...constExpr('i32.const 100'), ...VEC([[0xff], [0x80], [0x7f], [0x01]])]],
});
const e = (await WebAssembly.instantiate(m)).instance.exports;
const mem = e.mem;
console.log(mem instanceof WebAssembly.Memory, mem.buffer instanceof ArrayBuffer, mem.buffer.byteLength);
console.log(JSON.stringify(new TextDecoder().decode(new Uint8Array(mem.buffer, 16, 12))));
console.log(e.load(16).toString(16), e.load8s(100), e.load8u(100), e.load8s(101), e.load16s(100), e.load16s(102), e.loadOff(12).toString(16));
e.store(200, 0x01020304); e.store16(210, 0x12345);
console.log(Array.from(new Uint8Array(mem.buffer, 200, 4)).join(), Array.from(new Uint8Array(mem.buffer, 210, 3)).join());
new Uint8Array(mem.buffer)[300] = 42;
new DataView(mem.buffer).setFloat64(400, 2.75, true);
console.log('js writes visible', e.load(300), e.loadf64(400), typeof e.load64(200), String(e.load64(200)));
for (const addr of [65532, 65533, 65536, -1]) {
  try { console.log('load', addr, e.load(addr)); } catch (err) { console.log('load', addr, err.name, err.message); }
}
const before = mem.buffer;
console.log('size', e.size(), 'grow', e.grow(1), 'size', e.size(), mem.buffer.byteLength, before === mem.buffer, before.byteLength);
console.log('grow past max', e.grow(5), e.size(), 'negative', e.grow(-1));
console.log('JS grow', mem.grow(1), mem.buffer.byteLength, e.size());
try { mem.grow(1); } catch (err) { console.log('JS grow past max', err.name, err.message); }
console.log('grow 0', mem.grow(0), 'top of grown memory', e.load(3 * 65536 - 4));
const m2 = new WebAssembly.Memory({ initial: 1, maximum: 2 });
console.log('standalone', m2.buffer.byteLength, m2.grow(1), m2.buffer.byteLength, new WebAssembly.Memory({ initial: 0 }).buffer.byteLength);
try { m2.grow(1); } catch (err) { console.log('standalone past max', err.name); }
''', filename="wasm_memory_data_and_grow.mjs")


def test_wasm_imported_memory_and_bulk_ops(run, workdir):
    """CATCHES: imported memories not shared with JS or between instances, memory.fill /
    memory.copy (including overlapping copies) computing wrong bytes or missing out-of-bounds
    traps, or growth through JS not being visible to wasm. Pins a reference quirk: a data segment
    written into an IMPORTED memory is clobbered by the stale JS view on the first call."""
    check_script(run, workdir, G, "wasm_imported_memory_and_bulk_ops", ASM + r'''
const mem = new WebAssembly.Memory({ initial: 1, maximum: 4 });
new Uint8Array(mem.buffer).set([1, 2, 3, 4, 5], 0);
const m = wasm({
  type: [functype(['i32', 'i32', 'i32'], []), functype(['i32'], ['i32'])],
  import: [imp('js', 'mem', 'memory', limits(1))],
  func: [[0], [0], [1]],
  export: [exp('fill', 'func', 0), exp('copy', 'func', 1), exp('sum', 'func', 2)],
  data: [[0, ...constExpr('i32.const 10'), ...STR('xyz')]],
  code: [
    body([], 'local.get 0 local.get 1 local.get 2 memory.fill'),
    body([], 'local.get 0 local.get 1 local.get 2 memory.copy'),
    body([[1, 'i32']], 'block loop local.get 0 i32.eqz br_if 1 local.get 0 i32.const 1 i32.sub local.tee 0 i32.load8_u 0 0 local.get 1 i32.add local.set 1 br 0 end end local.get 1'),
  ],
});
console.log(JSON.stringify(WebAssembly.Module.imports(new WebAssembly.Module(m))));
const e = (await WebAssembly.instantiate(m, { js: { mem } })).instance.exports;
const view = () => Array.from(new Uint8Array(mem.buffer, 0, 16)).join();
console.log('after instantiate', view());
e.fill(5, 0xab, 3); console.log('fill', view());
e.copy(0, 10, 3); console.log('copy', view());
e.copy(1, 0, 6); console.log('overlap copy', view());
new Uint8Array(mem.buffer)[15] = 200;
console.log('sum', e.sum(16), Object.keys(e).join(), 'mem' in e);
for (const [label, f] of [['fill oob', () => e.fill(65530, 1, 10)], ['copy oob', () => e.copy(0, 65535, 2)]]) {
  try { f(); } catch (err) { console.log(label, err.name, err.message); }
}
const reader = wasm({ type: [functype(['i32'], ['i32'])], import: [imp('js', 'mem', 'memory', limits(1))], func: [[0]], export: [exp('get', 'func', 0)], code: [body([], 'local.get 0 i32.load8_u 0 0')] });
const r2 = (await WebAssembly.instantiate(reader, { js: { mem } })).instance;
e.fill(100, 77, 1);
console.log('second instance sees', r2.exports.get(100));
mem.grow(1);
new Uint8Array(mem.buffer)[65536 + 5] = 9;
console.log('after JS grow', mem.buffer.byteLength, r2.exports.get(65536 + 5));
''', filename="wasm_imported_memory_and_bulk_ops.mjs")


def test_wasm_tables_and_call_indirect(run, workdir):
    """CATCHES: element segments not populating tables, call_indirect dispatching to the wrong
    function or not trapping with the distinct reference messages for null slots, out-of-range
    indices and signature mismatches, Table.get/set/length misbehaving (RangeError out of bounds,
    TypeError for plain JS functions), or a JS-created table not being shared across instances."""
    check_script(run, workdir, G, "wasm_tables_and_call_indirect", ASM + r'''
const m = wasm({
  type: [functype(['i32', 'i32'], ['i32']), functype(['i32', 'i32', 'i32'], ['i32']), functype([], ['i32'])],
  func: [[0], [0], [0], [1], [2]],
  table: [[T.funcref, ...limits(4, 8)]],
  export: [exp('add', 'func', 0), exp('sub', 'func', 1), exp('mul', 'func', 2), exp('dispatch', 'func', 3), exp('tbl', 'table', 0), exp('k', 'func', 4)],
  elem: [[0, ...constExpr('i32.const 0'), ...VEC([U(0), U(1), U(2)])]],
  code: [
    body([], 'local.get 0 local.get 1 i32.add'), body([], 'local.get 0 local.get 1 i32.sub'), body([], 'local.get 0 local.get 1 i32.mul'),
    body([], 'local.get 1 local.get 2 local.get 0 call_indirect 0 0'), body([], 'i32.const 7'),
  ],
});
const e = (await WebAssembly.instantiate(m)).instance.exports;
const tryIt2 = (label, f) => { try { console.log(label, f()); } catch (err) { console.log(label, 'THREW', err.name + ': ' + err.message); } };
console.log('dispatch', e.dispatch(0, 6, 7), e.dispatch(1, 6, 7), e.dispatch(2, 6, 7));
tryIt2('null slot', () => e.dispatch(3, 1, 1));
tryIt2('index 4', () => e.dispatch(4, 1, 1));
tryIt2('index -1', () => e.dispatch(-1, 1, 1));
const tbl = e.tbl;
console.log(tbl instanceof WebAssembly.Table, tbl.length, typeof tbl.get(0), tbl.get(0)(10, 5), tbl.get(3));
tryIt2('get out of bounds', () => tbl.get(10));
tbl.set(3, e.mul);
console.log('after set', e.dispatch(3, 4, 5));
tryIt2('signature mismatch', () => { tbl.set(3, e.k); return e.dispatch(3, 1, 1); });
tryIt2('set plain function', () => tbl.set(0, () => 1));
tbl.set(0, null);
tryIt2('cleared slot', () => e.dispatch(0, 1, 1));
tryIt2('set out of bounds', () => tbl.set(9, e.add));
const t2 = new WebAssembly.Table({ initial: 2, element: 'anyfunc' });
console.log('standalone table', t2.length, t2.get(0), t2.get(1));
const table = new WebAssembly.Table({ initial: 2 });
const provider = wasm({ type: [functype([], ['i32'])], import: [imp('js', 'tbl', 'table', [T.funcref, ...limits(2)])], func: [[0], [0]],
  elem: [[0, ...constExpr('i32.const 0'), ...VEC([U(0), U(1)])]], code: [body([], 'i32.const 111'), body([], 'i32.const 222')] });
new WebAssembly.Instance(new WebAssembly.Module(provider), { js: { tbl: table } });
const consumer = wasm({ type: [functype([], ['i32']), functype(['i32'], ['i32'])], import: [imp('js', 'tbl', 'table', [T.funcref, ...limits(2)])], func: [[1]],
  export: [exp('call', 'func', 0)], code: [body([], 'local.get 0 call_indirect 0 0')] });
const c = new WebAssembly.Instance(new WebAssembly.Module(consumer), { js: { tbl: table } });
console.log('cross-instance table', c.exports.call(0), c.exports.call(1), table.get(1)());
''', filename="wasm_tables_and_call_indirect.mjs")


def test_wasm_imports_globals_multivalue_start(run, workdir):
    """CATCHES: start functions not running during instantiation, imported functions receiving
    the wrong argument types, imported globals (numbers or WebAssembly.Global) not readable or
    usable in global initialisers, exported globals exposing the wrong value/type or being
    writable, mutable Global objects not settable, or multi-value results not returned as arrays."""
    check_script(run, workdir, G, "wasm_imports_globals_multivalue_start", ASM + r'''
const log = [];
const m = wasm({
  type: [functype(['i32'], []), functype(['i64'], ['i64']), functype([], []), functype(['i32', 'i32'], ['i32', 'i32']), functype([], ['i32']), functype(['f64'], ['f64', 'i32', 'i64'])],
  import: [imp('env', 'log', 'func', U(0)), imp('env', 'twice', 'func', U(1)), imp('env', 'g', 'global', [T.i32, 0]), imp('env', 'mg', 'global', [T.f64, 1])],
  func: [[2], [3], [4], [1], [5], [4]],
  global: [[T.i32, 1, ...constExpr('i32.const 100')], [T.i64, 0, ...constExpr('i64.const -5')], [T.i32, 0, ...constExpr('global.get 0')]],
  export: [exp('start', 'func', 2), exp('swap', 'func', 3), exp('bump', 'func', 4), exp('callTwice', 'func', 5), exp('multi', 'func', 6),
    exp('counter', 'global', 2), exp('neg', 'global', 3), exp('copy', 'global', 4), exp('readImported', 'func', 7)],
  start: 2,
  code: [
    body([], 'i32.const 1 call 0'),
    body([], 'local.get 1 local.get 0'),
    body([], 'global.get 2 i32.const 1 i32.add global.set 2 global.get 2'),
    body([], 'local.get 0 call 1 i64.const 1 i64.add'),
    body([], 'local.get 0 local.get 0 f64.add i32.const 7 i64.const 9007199254740993'),
    body([], 'global.get 0'),
  ],
});
const mg = new WebAssembly.Global({ value: 'f64', mutable: true }, 1.5);
const env = { log: (x) => log.push('log:' + x + ':' + typeof x), twice: (b) => { log.push('twice got ' + typeof b + ' ' + b); return b * 2n; }, g: 41, mg };
console.log(JSON.stringify(WebAssembly.Module.imports(new WebAssembly.Module(m))));
const e = (await WebAssembly.instantiate(m, { env })).instance.exports;
console.log('start ran:', log.join(' '));
console.log(JSON.stringify(e.swap(1, 2)), Array.isArray(e.swap(1, 2)));
console.log(e.bump(), e.bump(), e.counter instanceof WebAssembly.Global, e.counter.value, e.counter.valueOf(), typeof e.neg.value, String(e.neg.value), e.copy.value, e.readImported());
try { e.counter.value = 5; } catch (err) { console.log(err.name + ': ' + err.message); }
console.log(String(e.callTwice(21n)), log[log.length - 1], String(e.callTwice(4)));
const r = e.multi(1.25); console.log(r.length, r[0], r[1], typeof r[2], String(r[2]));
console.log(mg.value, (mg.value = 3, mg.value), mg.valueOf());
const ig = new WebAssembly.Global({ value: 'i32' }, 9);
try { ig.value = 1; } catch (err) { console.log(err.name + ': ' + err.message); }
const g64 = new WebAssembly.Global({ value: 'i64' }, 5n);
console.log(ig.value, String(g64.value), typeof g64.value, new WebAssembly.Global({ value: 'f32' }, 0.1).value, new WebAssembly.Global({ value: 'i32', mutable: true }).value);
const gi64 = new WebAssembly.Global({ value: 'i64', mutable: true }, 1n);
const gf32 = new WebAssembly.Global({ value: 'f32', mutable: true }, 0);
const m3 = wasm({
  type: [functype([], ['i32', 'i64']), functype([], ['i64']), functype([], [])],
  import: [imp('env', 'pair', 'func', U(0)), imp('env', 'gi64', 'global', [T.i64, 1]), imp('env', 'gf32', 'global', [T.f32, 1])],
  func: [[1], [2]],
  export: [exp('sumPair', 'func', 1), exp('bumpGlobals', 'func', 2)],
  code: [
    body([[1, 'i64']], 'call 0 local.set 0 i64.extend_i32_s local.get 0 i64.add global.get 0 i64.add'),
    body([], 'global.get 0 i64.const 10 i64.mul global.set 0 global.get 1 f32.const 0.5 f32.add global.set 1'),
  ],
});
const e3 = new WebAssembly.Instance(new WebAssembly.Module(m3), { env: { pair: () => [-5, 100n], gi64, gf32 } }).exports;
console.log('host multi-value', String(e3.sumPair()));
gi64.value = 7n; gf32.value = 0.1;
e3.bumpGlobals();
console.log('globals written by wasm', String(gi64.value), gf32.value, String(e3.sumPair()));
''', filename="wasm_imports_globals_multivalue_start.mjs")


def test_wasm_compile_errors_and_validate(run, workdir):
    """CATCHES: decoders that accept malformed binaries or report them with different
    CompileError messages (bad magic/version, truncated or out-of-order sections, unknown section
    ids, size mismatches, bad value types, out-of-range type indices, function/code count mismatch,
    unterminated bodies, invalid UTF-8 names), validate() disagreeing, or compile()/instantiate()
    not rejecting asynchronously. Pins two quirks: a non-empty custom section is rejected with a
    size mismatch, and an out-of-range export index fails validate() but still compiles."""
    check_script(run, workdir, G, "wasm_compile_errors_and_validate", ASM + r'''
const good = wasm({ type: [functype([], [])], func: [[0]], export: [exp('f', 'func', 0)], code: [body([], 'nop')] });
const H = [0, 0x61, 0x73, 0x6d, 1, 0, 0, 0];
const cases = {
  'empty': new Uint8Array(0),
  'header only': new Uint8Array(H),
  'bad magic': new Uint8Array([0, 0x61, 0x73, 0x6e, 1, 0, 0, 0]),
  'version 2': new Uint8Array([0, 0x61, 0x73, 0x6d, 2, 0, 0, 0]),
  'truncated': good.slice(0, good.length - 3),
  'out of order': new Uint8Array([...H, 3, 1, 0, 1, 1, 0]),
  'unknown section': new Uint8Array([...H, 13, 0]),
  'size mismatch': new Uint8Array([...H, 1, 2, 0, 0]),
  'bad functype': new Uint8Array([...H, 1, 2, 1, 0x61]),
  'bad valtype': wasm({ type: [[0x60, 1, 0x55, 0]] }),
  'type idx oob': wasm({ type: [functype([], [])], func: [[5]] }),
  'export oob': wasm({ type: [functype([], [])], func: [[0]], export: [exp('f', 'func', 3)], code: [body([], 'nop')] }),
  'count mismatch': wasm({ type: [functype([], [])], func: [[0], [0]], code: [body([], 'nop')] }),
  'no end': new Uint8Array([...wasm({ type: [functype([], [])], func: [[0]] }), 10, 4, 1, 2, 0, 0x01]),
  'empty custom': new Uint8Array([...good, 0, 0]),
  'named custom': new Uint8Array([...good, 0, 5, 4, 0x6e, 0x61, 0x6d, 0x65]),
  'bad import kind': wasm({ import: [[...STR('a'), ...STR('b'), 7]] }),
  'bad export kind': wasm({ export: [[...STR('a'), 9, 0]] }),
  'unsupported elem': wasm({ type: [functype([], [])], func: [[0]], table: [[T.funcref, 0, 1]], elem: [[5]], code: [body([], 'nop')] }),
  'bad utf8 name': wasm({ type: [functype([], [])], func: [[0]], export: [[1, 0xff, 0, 0]], code: [body([], 'nop')] }),
  'bad const expr': wasm({ global: [[T.i32, 0, 0x6a, 0x0b]] }),
};
for (const [name, bytes] of Object.entries(cases)) {
  let msg;
  try { new WebAssembly.Module(bytes); msg = 'compiled'; } catch (e) { msg = errStr(e) + ' ' + (e instanceof WebAssembly.CompileError); }
  console.log(name.padEnd(16), WebAssembly.validate(bytes), msg);
}
tryIt('validate non-buffer', () => WebAssembly.validate('abc'));
tryIt('Module non-buffer', () => new WebAssembly.Module('abc'));
try { await WebAssembly.compile(new Uint8Array(3)); } catch (e) { console.log('compile rejects', errStr(e)); }
try { await WebAssembly.instantiate(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8])); } catch (e) { console.log('instantiate rejects', errStr(e)); }
const ce = new WebAssembly.CompileError('x');
console.log(ce instanceof Error, ce.name, new WebAssembly.LinkError('y').name, new WebAssembly.RuntimeError('z').message, String(new WebAssembly.RuntimeError('r')));
''', filename="wasm_compile_errors_and_validate.mjs")


def test_wasm_link_and_instantiation_errors(run, workdir):
    """CATCHES: instantiation that does not raise LinkError (with the reference messages) for
    missing or non-callable function imports and out-of-bounds data/element segments, start
    function traps not surfacing as RuntimeError from the constructor, exceptions thrown by
    imported JS functions not propagating unchanged, or unsupported opcodes (ref.null,
    memory.init) and memory access without a memory not trapping with the reference messages."""
    check_script(run, workdir, G, "wasm_link_and_instantiation_errors", ASM + r'''
const needsImport = wasm({ type: [functype([], [])], import: [imp('env', 'boom', 'func', U(0))], func: [[0]], export: [exp('run', 'func', 1)], code: [body([], 'call 0')] });
const mod = new WebAssembly.Module(needsImport);
console.log(JSON.stringify(WebAssembly.Module.imports(mod)), JSON.stringify(WebAssembly.Module.exports(mod)));
tryIt('missing import', () => new WebAssembly.Instance(mod, {}));
tryIt('no import object', () => new WebAssembly.Instance(mod));
tryIt('non-callable import', () => new WebAssembly.Instance(mod, { env: { boom: 42 } }));
tryIt('not a Module', () => new WebAssembly.Instance({}));
try { await WebAssembly.instantiate(needsImport, {}); } catch (e) { console.log('async link error', errStr(e), e instanceof WebAssembly.LinkError); }
const inst = new WebAssembly.Instance(mod, { env: { boom: () => { throw new TypeError('from js'); } } });
try { inst.exports.run(); } catch (e) { console.log('import throws', errStr(e), e instanceof TypeError, e instanceof WebAssembly.RuntimeError); }
const custom = { tag: 'thrown object' };
const inst2 = new WebAssembly.Instance(mod, { env: { boom: () => { throw custom; } } });
try { inst2.exports.run(); } catch (e) { console.log('non-error propagates', e === custom); }
const dataOob = wasm({ memory: [limits(1)], data: [[0, ...constExpr('i32.const 65535'), ...STR('ab')]] });
tryIt('data segment oob', () => new WebAssembly.Instance(new WebAssembly.Module(dataOob)));
const elemOob = wasm({ type: [functype([], [])], func: [[0]], table: [[T.funcref, ...limits(1)]], elem: [[0, ...constExpr('i32.const 1'), ...VEC([U(0)])]], code: [body([], 'nop')] });
tryIt('elem segment oob', () => new WebAssembly.Instance(new WebAssembly.Module(elemOob)));
const trapStart = wasm({ type: [functype([], [])], func: [[0]], start: 0, code: [body([], 'unreachable')] });
tryIt('start traps', () => new WebAssembly.Instance(new WebAssembly.Module(trapStart)));
const run1 = (label, code, extra = {}) => {
  const bytes = wasm({ type: [functype([], ['i32'])], func: [[0]], export: [exp('f', 'func', 0)], code: [body([], code)], ...extra });
  tryIt(label, () => new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports.f());
};
run1('no memory', 'i32.const 0 i32.load 2 0');
run1('ref.null', '0xd0 0x70 0xd1');
run1('memory.init', 'i32.const 0 i32.const 0 i32.const 0 0xfc 0x08 0x00 0x00 i32.const 1', { memory: [limits(1)] });
run1('table.get', 'i32.const 0 0x25 0x00 drop i32.const 1', { table: [[T.funcref, ...limits(1)]] });
''', filename="wasm_link_and_instantiation_errors.mjs")


def test_wasm_memory_widths_comparisons_and_const_exprs(run, workdir):
    """CATCHES: wrong sign/zero extension in the narrow i64 loads, wrong byte layout or truncation
    in i64.store8/16/32 and f32/f64 stores, bit errors across the full i32/i64/f32/f64 comparison
    sets (including NaN), i64<->f32 conversions, global initialisers using f32/f64/i64 consts and
    ref.null, data segments with an explicit memory index (and passive segments wrongly applied),
    or element segments with an explicit table index."""
    check_script(run, workdir, G, "wasm_memory_widths_comparisons_and_const_exprs", ASM + r'''const loads = ['i64.load8_s', 'i64.load8_u', 'i64.load16_s', 'i64.load16_u', 'i64.load32_s', 'i64.load32_u'];
const ops = [
  ...loads.map((o) => [o, 0, 'local.get 0 ' + o + ' 0 0']),
  ['f32load', 1, 'local.get 0 f32.load 2 0'],
  ['store_all', 2, 'i32.const 0 i64.const -1 i64.store8 0 0 i32.const 2 i64.const 0x12345 i64.store16 1 0 i32.const 4 i64.const -2 i64.store32 2 0 i32.const 8 f32.const 1.5 f32.store 2 0 i32.const 16 f64.const -0.25 f64.store 3 0 i32.const 24 i32.const 0x1ff i32.store8 0 0'],
  ['cmp64', 3, 'local.get 0 local.get 1 i64.lt_s local.get 0 local.get 1 i64.gt_u i32.const 1 i32.shl i32.or local.get 0 local.get 1 i64.le_u i32.const 2 i32.shl i32.or local.get 0 local.get 1 i64.ge_s i32.const 3 i32.shl i32.or local.get 0 local.get 1 i64.eq i32.const 4 i32.shl i32.or local.get 0 local.get 1 i64.ne i32.const 5 i32.shl i32.or local.get 0 i64.eqz i32.const 6 i32.shl i32.or'],
  ['cmp32', 4, 'local.get 0 local.get 1 i32.gt_s local.get 0 local.get 1 i32.le_s i32.const 1 i32.shl i32.or local.get 0 local.get 1 i32.gt_u i32.const 2 i32.shl i32.or local.get 0 local.get 1 i32.le_u i32.const 3 i32.shl i32.or local.get 0 local.get 1 i32.ge_s i32.const 4 i32.shl i32.or local.get 0 local.get 1 i32.lt_u i32.const 5 i32.shl i32.or local.get 0 local.get 1 i32.eq i32.const 6 i32.shl i32.or local.get 0 local.get 1 i32.ne i32.const 7 i32.shl i32.or'],
  ['cmpf32', 5, 'local.get 0 local.get 1 f32.eq local.get 0 local.get 1 f32.ne i32.const 1 i32.shl i32.or local.get 0 local.get 1 f32.lt i32.const 2 i32.shl i32.or local.get 0 local.get 1 f32.gt i32.const 3 i32.shl i32.or local.get 0 local.get 1 f32.le i32.const 4 i32.shl i32.or'],
  ['cmpf64', 6, 'local.get 0 local.get 1 f64.gt local.get 0 local.get 1 f64.le i32.const 1 i32.shl i32.or local.get 0 local.get 1 f64.ge i32.const 2 i32.shl i32.or'],
  ['conv', 7, 'local.get 0 i64.trunc_sat_f32_s local.get 0 i64.trunc_sat_f32_u i64.add'],
  ['conv2', 8, 'local.get 0 f32.convert_i64_s f64.promote_f32 local.get 0 f32.convert_i64_u f64.promote_f32 f64.add'],
  ['conv3', 9, 'local.get 0 f32.convert_i32_u f64.promote_f32 local.get 0 f64.convert_i32_s f64.add'],
  ['g', 10, 'global.get 0 global.get 1 f64.promote_f32 f64.add global.get 2 f64.convert_i64_s f64.add'],
  ['i64trunc', 7, 'local.get 0 i64.trunc_f32_u local.get 0 i64.trunc_f32_s i64.sub'],
  ['f32minmax', 11, 'local.get 0 local.get 1 f32.min local.get 0 local.get 1 f32.max f32.sub'],
  ['f64minmax', 12, 'local.get 0 local.get 1 f64.min local.get 0 local.get 1 f64.max f64.sub'],
  ['i64bits', 13, 'local.get 0 i64.ctz local.get 0 i64.const 4 i64.rotr i64.add'],
  ['i64extend16', 13, 'local.get 0 i64.extend16_s'],
];
const m = wasm({
  type: [functype(['i32'], ['i64']), functype(['i32'], ['f32']), functype([], []), functype(['i64', 'i64'], ['i32']), functype(['i32', 'i32'], ['i32']), functype(['f32', 'f32'], ['i32']), functype(['f64', 'f64'], ['i32']), functype(['f32'], ['i64']), functype(['i64'], ['f64']), functype(['i32'], ['f64']), functype([], ['f64']), functype(['f32', 'f32'], ['f32']), functype(['f64', 'f64'], ['f64']), functype(['i64'], ['i64'])],
  func: ops.map(([, t]) => [t]),
  table: [[T.funcref, ...limits(2)]],
  memory: [limits(1)],
  global: [[T.f64, 0, ...constExpr('f64.const 2.5')], [T.f32, 0, ...constExpr('f32.const 0.5')], [T.i64, 1, ...constExpr('i64.const -7')], [T.funcref, 0, 0xd0, 0x70, 0x0b], [T.funcref, 0, 0xd2, 0x00, 0x0b]],
  export: [exp('mem', 'memory', 0), exp('tbl', 'table', 0), exp('gf32', 'global', 1), exp('gref', 'global', 3), ...ops.map(([n], i) => exp(n, 'func', i))],
  elem: [[2, 0, ...constExpr('i32.const 1'), 0x00, ...VEC([U(1)])]],
  code: ops.map(([, , src]) => body([], src)),
  data: [[1, ...STR('passive')], [2, 0, ...constExpr('i32.const 40'), ...STR('kind2')]],
});
console.log(WebAssembly.validate(m));
const e = (await WebAssembly.instantiate(m)).instance.exports;
const u8 = new Uint8Array(e.mem.buffer);
u8.set([0xff, 0x80, 0x01, 0x80, 0xfe, 0xff, 0xff, 0xff], 100);
console.log(loads.map((o) => o + '=' + e[o](100)).join(' '), loads.map((o) => String(e[o](102))).join(','));
new DataView(e.mem.buffer).setFloat32(200, 3.25, true);
console.log('f32load', e.f32load(200));
e.store_all();
console.log('stores', Array.from(new Uint8Array(e.mem.buffer, 0, 32)).join());
console.log('data kind2', new TextDecoder().decode(new Uint8Array(e.mem.buffer, 40, 5)), 'passive not applied', new Uint8Array(e.mem.buffer, 45, 7).every((b) => b === 0));
const bits = (n, w) => n.toString(2).padStart(w, '0');
for (const [a, b] of [[1n, 2n], [-1n, 1n], [5n, 5n], [0n, 0n]]) console.log('cmp64', a, b, bits(e.cmp64(a, b), 7));
for (const [a, b] of [[1, 2], [-1, 1], [5, 5]]) console.log('cmp32', a, b, bits(e.cmp32(a, b), 8));
for (const [a, b] of [[1, 2], [NaN, 1], [2, 2]]) console.log('cmpf32', a, b, bits(e.cmpf32(a, b), 5), 'cmpf64', bits(e.cmpf64(a, b), 3));
console.log('conv', String(e.conv(3.7)), String(e.conv(-3.7)), String(e.conv(NaN)), String(e.conv(1e30)));
console.log('conv2', e.conv2(-1n), e.conv2(16777217n), 'conv3', e.conv3(-1), e.conv3(7));
console.log('globals', e.g(), e.gf32.value, e.gref.value);
console.log('i64trunc', String(e.i64trunc(-2.5)), String(e.i64trunc(2.5)));
console.log('minmax', e.f32minmax(1.5, -2), e.f64minmax(3, 10));
console.log('i64bits', String(e.i64bits(8n)), String(e.i64extend16(0x18000n)));
console.log('table slot 1 from kind-2 elem', typeof e.tbl.get(1), e.tbl.get(0));
''', filename="wasm_memory_widths_comparisons_and_const_exprs.mjs")
