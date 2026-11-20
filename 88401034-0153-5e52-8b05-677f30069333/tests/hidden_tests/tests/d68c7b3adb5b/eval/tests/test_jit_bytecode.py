"""Tier equivalence of the bytecode VM and the ARM64 JIT for hot JavaScript.

Every program here is run three times: on the tree-walking interpreter (the semantic oracle),
on the bytecode VM (`--tier=bytecode`) and on the default JIT tier, and all three runs must
print the same golden. Functions tier up after 8 calls (immediately when the body contains a
loop), so each program warms its functions in loops before printing results; the warm phase
drives the compiled code through its specialised templates and then through the fallback
paths (strings, undefined, holes, getters, proxies, prototype changes, overflow, NaN, -0).
"""

import pytest

from conftest import out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]


def check(js, golden, name, code, tier):
    r = js(code, *tier)
    assert out(r) == golden(name)
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_int32_overflow_negative_zero_and_nan(js, golden, tier):
    """CATCHES: compiled integer arithmetic that wraps instead of overflowing into doubles, loses
    the sign of -0, mishandles NaN in comparisons or forgets string concatenation inside `+`."""
    code = r"""
"use strict";
function acc(n, step) { let s = 0; for (let i = 0; i < n; i++) s = (s + step) | 0; return s; }
function grow(n) { let x = 1; for (let i = 0; i < n; i++) x = x * 3 + 1; return x; }
function addOver(n) { let x = 2147483600; for (let i = 0; i < n; i++) x += 7; return x; }
function subUnder(n) { let x = -2147483600; for (let i = 0; i < n; i++) x -= 9; return x; }
function negz(n) { const r = []; for (let i = 0; i < n; i++) { const z = -0 * i; r.push(Object.is(z, -0) ? "-0" : String(z)); } return r.join(); }
function show(v) { return Object.is(v, -0) ? "-0" : String(v); }
function divs(n) { const out = []; for (let i = -2; i < n; i++) out.push(10 / i, -7 % (i || 1), i % 3, 0 / i); return out.map(show).join(" "); }
function nanLoop(a) { let c = 0, s = 0; for (let i = 0; i < a.length; i++) { const v = a[i] * 2; if (v !== v) c++; else s += v; } return c + ":" + s; }
function extremes(n) { let lo = Infinity, hi = -Infinity; for (let i = 0; i < n; i++) { const v = ((i * 7919) % 401 - 200) / 2.5 + i / 1024; if (v < lo) lo = v; if (v > hi) hi = v; } return lo.toFixed(4) + "/" + hi.toFixed(4); }
function cmpTable(n) { let t = 0; const xs = [NaN, 1, -1, 0, -0, Infinity]; for (let i = 0; i < n; i++) { const a = xs[i % 6], b = xs[(i * 5) % 6]; if (a < b) t += 1; if (a <= b) t += 10; if (a == b) t += 100; if (a != b) t += 1000; if (a > b) t += 10000; if (a >= b) t += 100000; } return t; }
function mixedAdd(vals) { let s = 0; for (let i = 0; i < vals.length; i++) s = s + vals[i]; return s; }
function negLoop(n) { let r = []; for (let i = 0; i < n; i++) { const v = -(i - 1); r.push(show(v * 0), show(-v)); } return r.join(); }
function modLoop(n) { let s = 0; for (let i = 1; i < n; i++) s += (-i % 4) + (i % -3) + (2.5 % i); return s; }
function incTypes(vals) { const r = []; for (let v of vals) { let w = v; w++; let u = v; --u; r.push(typeof w + ":" + String(w) + "/" + String(u)); } return r.join(" "); }
for (let k = 0; k < 3; k++) {
  console.log(acc(1000, 2147483647), grow(25), addOver(20), subUnder(20), negz(4));
  console.log(divs(4));
  console.log(nanLoop([1, 2, NaN, 4, undefined, "3"]), extremes(300), cmpTable(360), negLoop(3), modLoop(12));
}
console.log(mixedAdd([1, 2, 3]), mixedAdd([1, 2, "x", 4]), mixedAdd([1.5, true, null, undefined]), mixedAdd([0.1, 0.2]));
console.log(incTypes([1, "5", null, undefined, true, 2147483647, -0, "x", 1.5]));
"""
    check(js, golden, "int32_overflow", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_bitwise_masks_shifts_and_bigint(js, golden, tier):
    """CATCHES: wrong ARM64 logical-immediate encodings for masks such as 0xFF00, 0x00FF00FF or
    0x55555555, shift counts not taken modulo 32, `>>>` treated as signed, or doubles not
    truncated through ToInt32 before bit operations."""
    code = r"""
"use strict";
function masks(n) { let a = 0, b = 0, c = 0, d = 0, e = 0;
  for (let i = 0; i < n; i++) { const x = (i * 2654435761) | 0;
    a = (a + (x & 0xFF00)) | 0; b ^= x & 0x00FF00FF; c = (c | (x & 0x33333333)) ^ (x & 0x55555555);
    d = (d + (x >>> 28) + (x >> 30) + (x << 3)) | 0;
    e = (e + ((x & 0x0F0F0F0F) | 0x10101010) - (~x & 0xF0) + (x & 0x7FFFFFFF) + (x | 0x80000000) + (x ^ 0xAAAAAAAA)) | 0; }
  return [a, b, c, d, e].join(","); }
function shifts(n) { const r = []; for (let i = -n; i < n; i++) r.push((i << 31) >> 31, i >>> 1, i >> 33, 1 << i, -1 >>> i, i << 32); return r.join(" "); }
function popcnt(n) { let total = 0; for (let i = 0; i < n; i++) { let v = i; v = v - ((v >> 1) & 0x55555555); v = (v & 0x33333333) + ((v >> 2) & 0x33333333); total += (((v + (v >> 4)) & 0x0F0F0F0F) * 0x01010101) >>> 24; } return total; }
function truncs(n) { let x = 0; for (let i = 0; i < n; i++) x = (x + 4294967296.5 * i) | 0; return x; }
function toInt(vals) { return vals.map(v => [v | 0, v >>> 0, ~v, v & -1, v ^ 0].join("/")).join(" "); }
function bigbits(n) { let x = 0n; for (let i = 0n; i < n; i++) x = (x << 3n) ^ (i & 0xFFn) | (i << 60n); return x.toString(16) + ":" + BigInt.asIntN(64, x) + ":" + (x >> 100n); }
function rotl(x, k) { return (x << k) | (x >>> (32 - k)); }
function hash(s) { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); h = rotl(h, 5) ^ (h >>> 7); } return h >>> 0; }
for (let k = 0; k < 3; k++) {
  console.log(masks(500));
  console.log(shifts(3));
  console.log(popcnt(256), truncs(50), hash("lumen-jit"), hash("bytecode"));
  console.log(bigbits(20n));
}
console.log(toInt([1.9, -1.9, 2147483648, 4294967295, -2147483649, NaN, Infinity, "12", "0x1F", null, true, [7], {}]));
"""
    check(js, golden, "bitwise", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_array_elements_holes_bounds_and_prototype_indices(js, golden, tier):
    """CATCHES: compiled element loads that read past the length, treat holes as values instead
    of consulting the prototype chain, ignore an indexed getter installed on Array.prototype
    mid-loop, or let writes to frozen arrays succeed (strict) or throw (sloppy)."""
    code = r"""
function sumArr(a) { let s = 0; for (let i = 0; i < a.length; i++) s += a[i]; return s; }
function readPast(a, n) { let s = 0, u = 0; for (let i = 0; i < n; i++) { const v = a[i]; if (v === undefined) u++; else s += v; } return s + "/" + u; }
function holey(n) { const a = [1, , 3, , 5]; let r = ""; for (let i = 0; i < n; i++) r += a[i % 6] === undefined ? "h" : a[i % 6]; return r; }
function writeGrow(n) { const a = []; for (let i = 0; i < n; i++) a[i] = i * 2; a[n + 3] = -1; return a.length + ":" + a.filter(x => x === undefined).length + ":" + (n + 1 in a) + ":" + (n in a); }
function negIdx(a) { const r = []; for (let i = -2; i < 4; i++) r.push(String(a[i])); a[-1] = "neg"; a["1.5"] = "frac"; return r.join() + "|" + a.length + "|" + a[-1] + a[1.5]; }
function strKeys(o, keys) { let s = 0; for (let i = 0; i < keys.length; i++) s += o[keys[i]]; return s; }
function protoIdx(n) { const a = [10, 20, 30]; let s = 0;
  for (let i = 0; i < n; i++) { if (i === 50) Object.defineProperty(Array.prototype, 4, { get() { return 1000; }, configurable: true }); s += a[i % 6] || 0; }
  delete Array.prototype[4]; return s; }
function frozen(n) { "use strict"; const a = Object.freeze([1, 2, 3]); let errs = 0; for (let i = 0; i < n; i++) { try { a[i % 4] = 9; } catch (e) { errs++; } } return errs + ":" + a.join(); }
function sloppyFrozen(n) { const a = Object.freeze([1, 2, 3]); for (let i = 0; i < n; i++) a[i % 4] = 9; return a.join() + ":" + a.length; }
function elemTypes(n) { const a = [1, "two", 3.5, null, {}, [6], true, undefined, 10n]; let r = ""; for (let i = 0; i < n; i++) r += typeof a[i % 9] + ","; return r; }
function swapLoop(a) { for (let i = 0, j = a.length - 1; i < j; i++, j--) { const t = a[i]; a[i] = a[j]; a[j] = t; } return a.join(""); }
function preIncIdx(a) { let i = -1, s = ""; while (i < a.length - 1) s += a[++i]; let j = a.length; while (j > 0) s += a[--j]; return s; }
function nested(m) { let s = 0; for (let i = 0; i < m.length; i++) for (let j = 0; j < m[i].length; j++) s += m[i][j] * (i + 1); return s; }
function lenChange(a) { let n = 0; for (let i = 0; i < a.length; i++) { if (a[i] > 2) a.length = i; n++; } return n + ":" + a.length; }
function chainedStore(n) { const a = [], b = []; let last; for (let i = 0; i < n; i++) last = a[i] = b[i] = i * i; return last + ":" + a.join() + ":" + b.length; }
function objElems(n) { const o = { 0: "a", 1: "b", length: 2 }; const r = []; for (let i = 0; i < n; i++) { o[i + 2] = i; r.push(o[i]); } return r.join() + ":" + Object.keys(o).length; }
function stringElems(s) { let r = ""; for (let i = 0; i < s.length + 2; i++) r += s[i] === undefined ? "_" : s[i].toUpperCase(); return r; }
for (let k = 0; k < 3; k++) {
  console.log(sumArr([1, 2, 3, 4.5]), readPast([1, 2, 3], 6), holey(12), writeGrow(10), negIdx([7, 8, 9]), strKeys({ a: 1, b: 2, 0: 5 }, ["a", "b", "0", 0]));
  console.log(frozen(8), sloppyFrozen(5), elemTypes(10), swapLoop([1, 2, 3, 4, 5]), preIncIdx(["a", "b", "c"]), nested([[1, 2], [3, 4], [5]]));
  console.log(lenChange([1, 2, 3, 4, 5]), chainedStore(5), objElems(4), stringElems("abc"));
}
console.log(protoIdx(100));
console.log(sumArr([1, 2, , 4]), sumArr(["a", "b"]), sumArr({ length: 3, 0: 1, 1: 2, 2: 3 }), sumArr("123"));
"""
    check(js, golden, "array_elements", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_typed_array_conversions_in_hot_loops(js, golden, tier):
    """CATCHES: compiled typed-array stores that skip the element-type conversion (Int8 wrap,
    Uint8Clamped rounding, Float32 rounding, Uint32 sign) or allow out-of-bounds writes to grow
    the view instead of being ignored."""
    code = r"""
function fill(n) {
  const i8 = new Int8Array(4), u8c = new Uint8ClampedArray(4), i32 = new Int32Array(4), u32 = new Uint32Array(4);
  const f32 = new Float32Array(4), f64 = new Float64Array(4), u16 = new Uint16Array(4), i16 = new Int16Array(4);
  for (let i = 0; i < n; i++) {
    const v = i * 37.7 - 200;
    i8[i & 3] = v; u8c[i & 3] = v; i32[i & 3] += i * 1000003; u32[i & 3] = -i; f32[i & 3] = v / 3; f64[i & 3] += v / 7; u16[i & 3] = v * 300; i16[i & 3] = v * 300;
    i8[4] = 1; f64[-1] = 5;
  }
  return [i8, u8c, i32, u32, Array.from(f32, x => x.toFixed(4)), Array.from(f64, x => x.toFixed(4)), u16, i16].map(a => Array.from(a).join(",")).join(" | ") + " | " + i8.length + ":" + i8[4] + ":" + f64[-1];
}
function sumTyped(t) { let s = 0; for (let i = 0; i < t.length; i++) s += t[i]; return s; }
function clampRound(n) { const c = new Uint8ClampedArray(n); const r = []; for (let i = 0; i < n; i++) { c[i] = i - 0.5; } for (let i = 0; i < n; i++) r.push(c[i]); return r.join(); }
function special(n) { const f = new Float32Array(3), i = new Int32Array(3); for (let k = 0; k < n; k++) { f[0] = NaN; f[1] = -0; f[2] = 1e40; i[0] = NaN; i[1] = -0.9; i[2] = "77"; } return [f[0], Object.is(f[1], -0), f[2], i[0], i[1], i[2]].join(); }
for (let k = 0; k < 3; k++) {
  console.log(fill(30));
  console.log(sumTyped(new Int16Array([1, -2, 30000, 4])), sumTyped(new Float64Array([0.5, 0.25])), sumTyped(new Uint8Array([255, 1])), clampRound(6), special(20));
}
"""
    check(js, golden, "typed_arrays", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_property_shapes_accessors_and_prototype_changes(js, golden, tier):
    """CATCHES: inline caches that keep returning a stale prototype value after the prototype is
    mutated, shadowed or swapped mid-loop, skip getters/setters or proxies, or let assignments to
    non-writable properties succeed."""
    code = r"""
function readX(o) { return o.x; }
function poly(objs, n) { let s = 0; for (let i = 0; i < n; i++) s += readX(objs[i % objs.length]); return s; }
function mkShapes() { const out = []; for (let i = 0; i < 12; i++) { const o = {}; o["k" + i] = i; o.x = i + 1; out.push(o); } return out; }
class Acc { constructor() { this._v = 0; this.hits = 0; } get v() { this.hits++; return this._v; } set v(n) { this._v = n * 2; } }
function useAcc(n) { const a = new Acc(); for (let i = 0; i < n; i++) a.v = a.v + 1; return a._v + ":" + a.hits; }
function protoChange(n) { function T() {} T.prototype.val = 1; const t = new T(); let s = 0;
  for (let i = 0; i < n; i++) { if (i === 30) T.prototype.val = 5; if (i === 60) t.val = 100; if (i === 80) delete t.val; if (i === 90) Object.setPrototypeOf(t, { val: -1 }); s += t.val; }
  return s; }
function addDelete(n) { const o = { a: 1 }; let s = 0; for (let i = 0; i < n; i++) { o["p" + (i % 3)] = i; if (i % 4 === 0) delete o.p1; s += (o.p1 || 0) + o.a; } return s + ":" + Object.keys(o).join(); }
function strictRO(n) { "use strict"; const o = {}; Object.defineProperty(o, "r", { value: 1, writable: false }); let e = 0; for (let i = 0; i < n; i++) { try { o.r = i; } catch (err) { e++; } } return e + ":" + o.r; }
function sloppyRO(n) { const o = Object.defineProperty({}, "r", { value: 7, writable: false }); for (let i = 0; i < n; i++) o.r = i; return o.r; }
function inherited(n) { const base = { m() { return this.k * 2; } }; const objs = [Object.create(base), Object.create(base)]; objs[0].k = 1; objs[1].k = 2; let s = 0; for (let i = 0; i < n; i++) { if (i === 20) base.m = function () { return -this.k; }; s += objs[i & 1].m(); } return s; }
function updates(n) { const o = { c: 0, d: 10 }; for (let i = 0; i < n; i++) { o.c++; ++o.c; o.d--; o.c += 2; o.d *= 1; o.e = (o.e || 0) - 1; } return o.c + "," + o.d + "," + o.e; }
function proxyRead(n) { const p = new Proxy({ x: 1 }, { get(t, k) { return k === "x" ? 42 : undefined; } }); const objs = [{ x: 1 }, { x: 2 }, p]; let s = 0; for (let i = 0; i < n; i++) s += objs[i % 3].x; return s; }
function lengths(n) { const xs = ["", "a", "abc", [1, 2], { length: 9 }, function (a, b) {}]; let s = 0; for (let i = 0; i < n; i++) s += xs[i % 6].length; return s; }
function thisFields(n) { function P() { this.a = 1; this.b = 2; this.c = 3; } let s = 0; for (let i = 0; i < n; i++) { const p = new P(); s += p.a + p.b + p.c; } return s; }
function manyFields(n) { function Big() { this.f0 = 0; this.f1 = 1; this.f2 = 2; this.f3 = 3; this.f4 = 4; this.f5 = 5; this.f6 = 6; this.f7 = 7; this.f8 = 8; this.f9 = 9; this.f10 = 10; this.f11 = 11; this.f12 = 12; this.f13 = 13; this.f14 = 14; this.f15 = 15; this.f16 = 16; this.f17 = 17; } let s = 0; for (let i = 0; i < n; i++) { const b = new Big(); s += b.f17 + b.f0 + b.f9; } return s; }
function dupFields(a) { this.a = a; this.b = 1; this.a = a + 1; this.b += this.a; }
function setterOnProto(n) { const log = []; const proto = { set w(v) { log.push(v); } }; const o = Object.create(proto); for (let i = 0; i < n; i++) o.w = i; return log.join() + ":" + Object.keys(o).length; }
function symbolKeys(n) { const s = Symbol("k"); const o = { [s]: 1 }; let t = 0; for (let i = 0; i < n; i++) { o[s] += i; t += o[s]; } return t + ":" + String(s.description); }
const shapes = mkShapes();
for (let k = 0; k < 3; k++) {
  console.log(poly(shapes.slice(0, 1), 50), poly(shapes.slice(0, 3), 60), poly(shapes, 120), useAcc(20), protoChange(100), addDelete(20), strictRO(5), sloppyRO(5));
  console.log(inherited(40), updates(10), proxyRead(30), lengths(24), thisFields(20), manyFields(20), setterOnProto(4), symbolKeys(5));
  const ds = []; for (let i = 0; i < 12; i++) ds.push(JSON.stringify(new dupFields(i))); console.log(ds.join(""));
}
try { (function nullRead(xs) { let s = 0; for (let i = 0; i < 3; i++) s += xs[i].x; return s; })([{ x: 1 }, { x: 2 }]); } catch (e) { console.log(e.constructor.name + ": " + e.message); }
"""
    check(js, golden, "property_shapes", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_calls_closures_bound_and_forwarded(js, golden, tier):
    """CATCHES: call caches that keep calling the previous target when the callee changes, drop
    or invent arguments, bind the wrong `this` through bind/call/apply, or share one binding
    between closures created in different loop iterations."""
    code = r"""
function add(a, b) { return a + b; }
function direct(n) { let s = 0; for (let i = 0; i < n; i++) s = add(s, i); return s; }
function missingArgs(n) { const r = []; for (let i = 0; i < n; i++) r.push(add(i)); return r.slice(0, 3).join(); }
function extraArgs(n) { let s = 0; for (let i = 0; i < n; i++) s += add(i, 1, 2, 3); return s; }
function changingCallee(n) { const fs = [x => x + 1, x => x * 2, function (x) { return x - 3; }, Math.abs, String, Number.isInteger]; const r = []; for (let i = 0; i < n; i++) r.push(fs[i % fs.length](i - 4)); return r.join(); }
function closuresInLoop(n) { const fs = []; for (let i = 0; i < n; i++) fs.push(() => i * i); let s = 0; for (const f of fs) s += f(); return s; }
function varClosures(n) { const fs = []; for (var i = 0; i < n; i++) fs.push(function () { return i; }); return fs.map(f => f()).join(); }
function counter() { let c = 0; return { inc() { return ++c; }, get() { return c; }, reset() { c = 0; } }; }
function useCounter(n) { const c = counter(), d = counter(); for (let i = 0; i < n; i++) { c.inc(); if (i % 3 === 0) d.inc(); } const before = c.get(); c.reset(); return before + ":" + d.get() + ":" + c.get(); }
function freshClosures(n) { let t = 0; for (let i = 0; i < n; i++) { const k = i; const f = (x) => x + k; t += f(1); } return t; }
function bound(n) { const o = { v: 3 }; function m(a, b) { return this.v * a + b; } const b1 = m.bind(o, 2); const b2 = Math.max.bind(null, 5); const b3 = b1.bind({ v: 100 }); let s = 0; for (let i = 0; i < n; i++) s += b1(i) + b2(i) + b3(1); return s + ":" + b1.name + ":" + b1.length; }
function callApply(n) { function m(a, b) { return (this && this.k ? this.k : 0) + a * b; } const o = { k: 10 }; let s = 0; for (let i = 0; i < n; i++) s += m.call(o, i, 2) + m.apply(o, [i, 3]) + Math.max.apply(Math, [i, 7, 2]) + m.call(null, 1, 1) + m.apply(undefined, { length: 2, 0: 2, 1: 2 }); return s; }
function fib(n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
function depth(n) { return n === 0 ? 0 : 1 + depth(n - 1); }
function methodCalls(n) { const objs = [{ f() { return 1; } }, { f() { return 2; } }, { f: () => 3 }, { f: Math.sqrt }, { f: add.bind(null, 10) }]; let s = 0; for (let i = 0; i < n; i++) s += objs[i % 5].f(16); return s; }
function restP(first, ...rest) { let s = first; for (const r of rest) s += r; return s + "/" + rest.length; }
function defaults(a, b = a * 2, c = b + 1) { return a + b + c; }
function tail(n, acc) { if (n === 0) return acc; return tail(n - 1, acc + n); }
function hoisted(n) { let s = 0; for (let i = 0; i < n; i++) s += helper(i); return s; function helper(x) { return x * 3; } }
function iife(n) { let s = 0; for (let i = 0; i < n; i++) s += (function (x) { return x + 1; })(i) + ((y) => y * 2)(i); return s; }
function nonCallable(n) { let names = []; const vals = [1, "s", null, undefined, {}]; for (let i = 0; i < n; i++) { try { vals[i % 5](); } catch (e) { names.push(e.constructor.name); } } return names.join(); }
for (let k = 0; k < 3; k++) {
  console.log(direct(100), missingArgs(5), extraArgs(10), changingCallee(12), closuresInLoop(10), varClosures(4), useCounter(50), freshClosures(30));
  console.log(bound(10), callApply(10), fib(12), depth(40), methodCalls(25), hoisted(10), iife(10), nonCallable(5));
  const xs = []; for (let j = 0; j < 10; j++) xs.push(restP(1, 2, 3) + " " + restP(j) + " " + defaults(j) + " " + defaults(j, 1) + " " + tail(20, 0)); console.log(xs.slice(7).join(" | "));
}
"""
    check(js, golden, "calls_closures", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_spread_calls_dense_holes_getters_and_iterables(js, golden, tier):
    """CATCHES: a spread-call fast path that copies array storage verbatim for arrays longer than
    16, turns holes into missing arguments instead of undefined/inherited values, skips element
    getters, or fails to iterate Sets, Maps, strings and generators."""
    code = r"""
function add3(a, b, c) { return String(a) + "," + String(b) + "," + String(c); }
function count() { return arguments.length; }
function sum() { let s = 0; for (let i = 0; i < arguments.length; i++) s += arguments[i]; return s; }
function spreads(n) { const small = [1, 2, 3], big = Array.from({ length: 20 }, (_, i) => i), holes = [1, , 3]; const out = [];
  for (let i = 0; i < n; i++) out.push(add3(...small), sum(...big), add3(...holes), add3(i, ...[i, i]), count(...[]), count(...small, ...small), Math.max(...small), sum(1, ...small));
  return out.slice(-8).join(" "); }
const o = { k: 5, m(...xs) { return this.k + xs.length; } };
function methodSpread(n) { let s = 0; for (let i = 0; i < n; i++) s += o.m(...[1, 2, 3]) + o.m(1, ...[i]); return s; }
function iterables(n) { const set = new Set([3, 4]); const str = "xy"; const map = new Map([[1, 2]]); function* g() { yield "g1"; yield "g2"; } const out = [];
  for (let i = 0; i < n; i++) out.push(add3(...set), add3(...str), add3(...map), add3(...g()), add3(..."a\u{1F600}b")); return out.slice(-5).join(" "); }
function getterElem(n) { const a = [1, 2, 3]; let calls = 0; Object.defineProperty(a, 1, { get() { calls++; return "G"; } }); let r; for (let i = 0; i < n; i++) r = add3(...a); return r + ":" + calls; }
function inheritedHole(n) { const a = [1, , 3]; Array.prototype[1] = "P"; let r; for (let i = 0; i < n; i++) r = add3(...a); delete Array.prototype[1]; return r + ":" + add3(...a); }
function badSpread() { const names = []; for (const v of [null, 5, {}, undefined]) { try { add3(...v); } catch (e) { names.push(e.constructor.name); } } return names.join(); }
function newSpread(n) { function P(a, b) { this.s = a + b; } let t = 0; for (let i = 0; i < n; i++) t += new P(...[i, 1]).s + new Date(...[0]).getTime(); return t; }
function exactly16(n) { const a = Array.from({ length: 16 }, (_, i) => i * 2), b = a.concat([99]); let r = 0; for (let i = 0; i < n; i++) r += sum(...a) + count(...b); return r; }
function objectArgs(n) { const objs = [{ v: 1 }, { v: 2 }]; let t = 0; for (let i = 0; i < n; i++) { const pick = (x, y) => x.v * 10 + y.v; t += pick(...objs); } return t; }
for (let k = 0; k < 3; k++) {
  console.log(spreads(20));
  console.log(methodSpread(10), iterables(3), getterElem(5), inheritedHole(4), badSpread(), newSpread(10), exactly16(5), objectArgs(10));
}
"""
    check(js, golden, "spread_calls", code, tier)


@pytest.mark.parametrize("tier", TIERS[:2])
def test_spread_calls_observe_patched_iterators_in_compiled_tiers(js, golden, tier):
    """CATCHES: a compiled spread call that keeps scalar-replacing the array walk after
    Array.prototype[Symbol.iterator], an own Symbol.iterator or ArrayIterator.prototype.next has
    been replaced, instead of running the user's iterator as the spec requires."""
    code = r"""
function add3(a, b, c) { return String(a) + "," + String(b) + "," + String(c); }
function sum() { let s = 0; for (let i = 0; i < arguments.length; i++) s += arguments[i]; return s; }
function patchedIterator(n) { const a = [7, 8, 9]; const orig = Array.prototype[Symbol.iterator]; const r = [];
  for (let i = 0; i < n; i++) { if (i === 5) Array.prototype[Symbol.iterator] = function* () { yield "patched"; }; r.push(add3(...a)); }
  Array.prototype[Symbol.iterator] = orig; r.push(add3(...a)); return r.slice(3).join(" "); }
function patchedNext(n) { const proto = Object.getPrototypeOf([][Symbol.iterator]()); const orig = proto.next; let steps = 0; const r = [];
  for (let i = 0; i < n; i++) { if (i === 4) proto.next = function () { steps++; return orig.call(this); }; r.push(sum(...[1, 2])); }
  proto.next = orig; return r.join() + ":" + steps; }
function ownIterator(n) { const a = [1, 2, 3]; a[Symbol.iterator] = function* () { yield* [30, 20, 10]; }; let r; for (let i = 0; i < n; i++) r = add3(...a); return r; }
for (let k = 0; k < 3; k++) console.log(patchedIterator(8), patchedNext(8), ownIterator(3));
"""
    check(js, golden, "spread_patched_iterators", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_arguments_objects_mapped_and_unmapped(js, golden, tier):
    """CATCHES: compiled functions that materialise `arguments` as a plain copy (losing the
    sloppy-mode parameter mapping), keep the mapping in strict mode, or report the wrong length
    and callee when called with fewer or more arguments than declared."""
    code = r"""
function variadic() { let s = 0; for (let i = 0; i < arguments.length; i++) s += arguments[i] * (i + 1); return s + ":" + arguments.length; }
function sliceArgs() { return Array.prototype.slice.call(arguments, 1).join("-") + ":" + Array.from(arguments).length + ":" + [...arguments].join(""); }
function sloppy(a, b) { arguments[0] = 100; b = 7; return a + ":" + arguments[1] + ":" + arguments.length; }
function strict(a, b) { "use strict"; arguments[0] = 100; b = 7; return a + ":" + arguments[1] + ":" + arguments.length; }
function lengthWrite() { arguments.length = 1; return Array.prototype.join.call(arguments, "+"); }
function argsType() { return Object.prototype.toString.call(arguments) + typeof arguments[Symbol.iterator] + (arguments.callee === argsType); }
function strictCallee() { "use strict"; try { return arguments.callee; } catch (e) { return e.constructor.name; } }
function passThrough() { return variadic.apply(null, arguments); }
function deleteArg(a) { delete arguments[0]; return a + ":" + arguments[0] + ":" + arguments.length; }
function extraIndex(a) { arguments[3] = "x"; return arguments.length + ":" + arguments[3]; }
for (let k = 0; k < 3; k++) {
  const lines = [];
  for (let i = 0; i < 12; i++) lines.push([variadic(1, 2, 3, i), variadic(), sliceArgs("a", "b", "c"), sloppy(1, 2), sloppy(1), strict(1, 2), lengthWrite(5, 6, 7), argsType(), strictCallee(), passThrough(4, 5), deleteArg(9), extraIndex(1)].join(" "));
  console.log(lines[0]);
  console.log(lines[11]);
}
"""
    check(js, golden, "arguments_objects", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_constructors_classes_and_new_target(js, golden, tier):
    """CATCHES: the cached constructor fast path applied to derived classes, classes with fields
    or private members, or proxies, a stale prototype after `F.prototype` is replaced, ignored
    object return overrides, or a wrong `new.target`."""
    code = r"""
class Pair { constructor(a, b) { this.a = a; this.b = b; } sum() { return this.a + this.b; } }
class Base { constructor(x) { this.x = x; } }
class Derived extends Base { constructor(x) { super(x * 2); this.y = x; } }
class Fielded { z = 5; #p = 1; static count = 0; constructor(q) { this.q = q + this.#p; Fielded.count++; } get p() { return this.#p; } }
function Plain(v) { this.v = v; }
function Override(v) { this.v = v; if (v % 2) return { v: -v }; return 3; }
function NT() { return new.target === NT ? "new" : "call"; }
class NTBase { constructor() { this.t = new.target.name; } } class NTChild extends NTBase {}
function build(n) { let s = 0, t = "";
  for (let i = 0; i < n; i++) s += new Pair(i, 1).sum() + new Derived(i).x + new Fielded(i).q + new Fielded(i).z + new Plain(i).v + new Override(i).v;
  for (let i = 0; i < 3; i++) t += NT() + "," + typeof new NT() + "," + new NTChild().t + ";";
  return s + "|" + t + "|" + Fielded.count; }
function protoMut(n) { function K() { this.k = 1; } const out = []; for (let i = 0; i < n; i++) { if (i === 5) K.prototype = { tag: "B" }; if (i === 7) K.prototype = null; const o = new K(); out.push(o.tag || (Object.getPrototypeOf(o) === Object.prototype ? "O" : "A")); } return out.join(""); }
function ctorThrow(n) { function C(v) { if (v === 3) throw new RangeError("bad " + v); this.v = v; } let ok = 0, msg = ""; for (let i = 0; i < n; i++) { try { new C(i); ok++; } catch (e) { msg = e.message; } } return ok + ":" + msg; }
function classCall() { try { Pair(1, 2); return "no"; } catch (e) { return e.constructor.name; } }
function proxyNew(n) { const P = new Proxy(Plain, { construct(t, args) { return { v: args[0] * 10 }; } }); let s = 0; for (let i = 0; i < n; i++) s += new P(i).v + new Plain(i).v; return s; }
function reflectNew(n) { class Other { constructor() { this.o = 1; } } let s = 0; for (let i = 0; i < n; i++) { const r = Reflect.construct(Plain, [i], Other); s += r.v + (r instanceof Other ? 100 : 0); } return s; }
function arrowNew() { try { new (() => 1)(); } catch (e) { return e.constructor.name; } }
function derivedNoSuper() { class D extends Base { constructor() { } } try { new D(); } catch (e) { return e.constructor.name; } }
function derivedReturn(n) { class D extends Base { constructor(x) { super(x); return x > 2 ? { alt: x } : undefined; } } const r = []; for (let i = 0; i < n; i++) { const d = new D(i); r.push(d.alt || d.x); } return r.join(); }
for (let k = 0; k < 3; k++) {
  console.log(build(30));
  console.log(protoMut(9), ctorThrow(6), classCall(), proxyNew(10), reflectNew(10), arrowNew(), derivedNoSuper(), derivedReturn(5), new Fielded(1).p);
}
"""
    check(js, golden, "constructors", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_try_catch_finally_inside_hot_loops(js, golden, tier):
    """CATCHES: compiled exception handlers that are not popped on break/continue/return, run
    finally blocks the wrong number of times, lose the thrown value, or fail to close an
    iterator when a for-of body throws or breaks."""
    code = r"""
function hot(n) { let r = 0; for (let i = 0; i < n; i++) { try { if (i % 5 === 0) throw i; r += i; } catch (e) { r -= e; } finally { r += 1; } } return r; }
function nestedTry(n) { const log = []; for (let i = 0; i < n; i++) { try { try { if (i & 1) throw new Error("in" + i); log.push("ok" + i); } finally { log.push("f" + i); } } catch (e) { log.push(e.message); } } return log.join(","); }
function finallyOverride() { for (let i = 0; i < 3; i++) { try { return "try" + i; } finally { if (i === 0) return "fin"; } } }
function breakInFinally(n) { let c = 0; for (let i = 0; i < n; i++) { try { c++; if (i === 3) break; } finally { c += 10; } } return c; }
function continueInTry(n) { let c = 0; for (let i = 0; i < n; i++) { try { if (i % 2) continue; c += i; } catch (e) { c = -1; } } return c; }
function thrower(i) { if (i === 7) throw new TypeError("seven"); return i; }
function callThrow(n) { let s = 0, m = ""; for (let i = 0; i < n; i++) { try { s += thrower(i); } catch (e) { m = e.name + ":" + e.message; } } return s + "|" + m; }
function rethrow(n) { try { for (let i = 0; i < n; i++) { try { thrower(i); } catch (e) { throw new Error("wrapped " + e.message); } } } catch (e) { return e.message; } return "none"; }
function catchNoBinding(n) { let c = 0; for (let i = 0; i < n; i++) { try { null.x; } catch { c++; } } return c; }
function destructCatch(n) { let s = ""; for (let i = 0; i < n; i++) { try { throw { code: i, msg: "m" + i }; } catch ({ code, msg }) { s += code + msg; } } return s; }
function forOfTry(arr) { let s = 0; for (const v of arr) { try { if (v < 0) throw v; s += v; } catch (e) { s += 100; } } return s; }
function iterClose(n) { let closed = 0; const it = { [Symbol.iterator]() { let i = 0; return { next() { return { value: i++, done: i > 10 }; }, return() { closed++; return {}; } }; } };
  let s = 0; for (let k = 0; k < n; k++) { for (const v of it) { if (v === 3) break; s += v; } try { for (const v of it) { if (v === 2) throw "x"; } } catch (e) { s += 1000; } } return s + ":" + closed; }
function returnFromForOf(xs) { for (const x of xs) { if (x > 2) return "found" + x; } return "none"; }
function builtinErrors(n) { const names = []; for (let i = 0; i < n; i++) { try { [].reduce((a, b) => a); } catch (e) { names.push(e.constructor.name); } try { undefinedVar; } catch (e) { names.push(e.constructor.name); } try { new Array(-1); } catch (e) { names.push(e.constructor.name); } } return names.join(); }
function finallyCounts(n) { let f = 0, c = 0; for (let i = 0; i < n; i++) { try { try { if (i % 3 === 0) throw 1; } finally { f++; } } catch (e) { c++; } } return f + ":" + c; }
function throwNonError(n) { const r = []; for (const v of [1, "s", null, undefined, { a: 1 }]) { try { throw v; } catch (e) { r.push(typeof e + ":" + String(e && e.a !== undefined ? e.a : e)); } } return r.join(); }
for (let k = 0; k < 3; k++) {
  console.log(hot(50), nestedTry(4), finallyOverride(), breakInFinally(10), continueInTry(10), callThrow(10), rethrow(10), catchNoBinding(5));
  console.log(destructCatch(3), forOfTry([1, -1, 2, -2]), iterClose(3), returnFromForOf([1, 2, 3, 4]), returnFromForOf([]), builtinErrors(1), finallyCounts(10), throwNonError());
}
"""
    check(js, golden, "try_catch_finally", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_generators_and_async_functions_in_loops(js, golden, tier):
    """CATCHES: compiled async bodies that resume with the wrong value after `await`, run
    microtasks out of order, swallow rejections, or generator objects whose return/throw
    injection and yield* delegation diverge when driven from hot loops."""
    code = r"""
function* range(n) { for (let i = 0; i < n; i++) yield i; }
function* withReturn() { try { yield 1; yield 2; } finally { yield "cleanup"; } }
function* delegating(n) { const r = yield* range(n); yield* [10, 20]; return "end" + r; }
function sumGen(n) { let s = 0; for (const v of range(n)) s += v; return s; }
function manual() { const g = withReturn(); const a = [g.next().value, g.return(9).value, g.next().done]; const g2 = delegating(2); const b = []; let r; while (!(r = g2.next()).done) b.push(r.value); b.push(r.value); return a.join() + "|" + b.join(); }
function genThrow() { function* g() { try { yield 1; } catch (e) { yield "caught " + e; } } const it = g(); it.next(); return it.throw("boom").value; }
function genArgs() { function* g(a) { const x = yield a; const y = yield x * 2; return x + y; } const it = g(5); return [it.next().value, it.next(3).value, it.next(4).value, it.next().done].join(); }
async function sq(x) { await null; return x * x; }
async function loopAwait(n) { let s = 0; for (let i = 0; i < n; i++) s += await sq(i); return s; }
async function awaitThrow(n) { let c = 0; for (let i = 0; i < n; i++) { try { await Promise.reject(new Error("r" + i)); } catch (e) { c += e.message.length; } } return c; }
async function* agen(n) { for (let i = 0; i < n; i++) { await null; yield i * 3; } }
async function consume(n) { const out = []; for await (const v of agen(n)) out.push(v); return out.join(); }
async function hotAsync(x) { const a = await x; return a + 1; }
async function thenable() { const t = { then(res) { res(41); } }; return (await t) + 1; }
async function rejectsLater(i) { await null; if (i === 3) throw new RangeError("three"); return i; }
async function main() {
  for (let k = 0; k < 3; k++) console.log(sumGen(50), manual(), genThrow(), genArgs());
  console.log(await loopAwait(30), await awaitThrow(12), await consume(5), await thenable());
  let t = 0; for (let i = 0; i < 40; i++) t += await hotAsync(i);
  console.log(t);
  const settled = await Promise.allSettled([0, 1, 2, 3, 4].map(rejectsLater));
  console.log(settled.map(s => s.status === "fulfilled" ? s.value : s.reason.message).join());
  const order = []; const p = Promise.resolve().then(() => order.push("micro1")).then(() => order.push("micro2")); order.push("sync"); queueMicrotask(() => order.push("qm")); await p; console.log(order.join());
}
main().then(() => console.log("done"));
"""
    check(js, golden, "generators_async", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_map_set_lookups_with_unusual_keys(js, golden, tier):
    """CATCHES: collection lookup/insert intrinsics that hash NaN, -0, BigInt or object keys
    incorrectly, keep using the native Map.prototype.get after it is patched, or bypass a
    subclass override."""
    code = r"""
function mapHot(n) { const m = new Map(); for (let i = 0; i < n; i++) { const k = i % 10; m.set(k, (m.get(k) || 0) + i); } let s = 0; for (const [k, v] of m) s += k * v; return s + ":" + m.size; }
function mapKeys(n) { const m = new Map(); const keys = [NaN, 0, -0, "0", null, undefined, true, 1n, {}, Symbol.for("s"), 0.5, "NaN"]; for (let i = 0; i < n; i++) m.set(keys[i % keys.length], i);
  return [m.size, m.get(NaN), m.get(0), m.has(-0), m.get("0"), m.has({}), m.get(1n), m.get(0.5), m.get(undefined), m.get(null), [...m.keys()].map(String).join("/")].join(":"); }
function setHot(n) { const s = new Set(); let dup = 0; for (let i = 0; i < n; i++) { const v = (i * 7) % 23; if (s.has(v)) dup++; else s.add(v); } return s.size + ":" + dup + ":" + s.has(22) + s.has(23); }
function objKeys(n) { const s = new Set(); const objs = []; for (let i = 0; i < 5; i++) objs.push({ i }); for (let i = 0; i < n; i++) s.add(objs[i % 5]); return s.size + ":" + s.has(objs[2]) + s.has({ i: 2 }); }
function strMap(words) { const m = new Map(); for (const w of words) m.set(w, (m.get(w) ?? 0) + 1); return [...m].map(([k, v]) => k + "=" + v).join(","); }
function delMap(n) { const m = new Map(); for (let i = 0; i < n; i++) { m.set(i, i); if (i % 3 === 0) m.delete(i - 1); } return m.size + ":" + [...m.keys()].slice(0, 6).join(); }
function weak(n) { const wm = new WeakMap(); const ks = [{}, {}, {}]; for (let i = 0; i < n; i++) wm.set(ks[i % 3], (wm.get(ks[i % 3]) || 0) + 1); return ks.map(k => wm.get(k)).join() + wm.has({}); }
function mapSubclass(n) { class M extends Map { get(k) { return super.get(k) ?? "dflt"; } set(k, v) { return super.set(k, v * 2); } } const m = new M(); for (let i = 0; i < n; i++) m.set(i % 3, i); return m.get(1) + "," + m.get(7); }
function iterMutation() { const m = new Map([[1, "a"], [2, "b"]]); const seen = []; for (const [k] of m) { seen.push(k); if (k < 5) m.set(k + 2, "n"); if (k === 2) m.delete(3); } return seen.join(); }
function chained(n) { const m = new Map(); for (let i = 0; i < n; i++) m.set("a" + (i % 4), i).set(i % 2, -i); return [...m.entries()].join(";"); }
function patched(n) { const m = new Map([[1, "a"]]); const s = new Set([1]); const og = Map.prototype.get, oh = Set.prototype.has; const r = [];
  for (let i = 0; i < n; i++) { if (i === 10) { Map.prototype.get = function (k) { return "patched" + k; }; Set.prototype.has = function () { return "nope"; }; } r.push(m.get(1) + s.has(1)); }
  Map.prototype.get = og; Set.prototype.has = oh; return r.slice(8, 12).join() + "|" + m.get(1) + s.has(1); }
for (let k = 0; k < 3; k++) {
  console.log(mapHot(200), mapKeys(36), setHot(100), objKeys(20), strMap("a b a c b a d".split(" ")));
  console.log(delMap(20), weak(9), mapSubclass(10), iterMutation(), chained(6));
}
console.log(patched(20));
"""
    check(js, golden, "collections", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_global_bindings_accessors_and_late_definitions(js, golden, tier):
    """CATCHES: cached global name lookups that miss a global defined, deleted or turned into an
    accessor after the cache was filled, write through const bindings, or confuse script-level
    `let` with properties of globalThis."""
    code = r"""
var gCount = 0; var gStr = ""; let lexG = 1; const constG = 3;
function bump(n) { for (let i = 0; i < n; i++) { gCount = gCount + 1; gCount++; gStr += "x"; lexG = lexG * 2 % 1000; } return gCount + ":" + gStr.length + ":" + lexG + ":" + ("lexG" in globalThis) + ("gCount" in globalThis); }
function implicit(n) { for (let i = 0; i < n; i++) { implicitGlobal = i; } return typeof implicitGlobal + implicitGlobal; }
function viaThis(n) { for (let i = 0; i < n; i++) globalThis.gt = (globalThis.gt || 0) + i; return gt; }
Object.defineProperty(globalThis, "acc", { get() { return gCount * 10; }, set(v) { gCount = v; }, configurable: true });
function accessorGlobal(n) { let s = 0; for (let i = 0; i < n; i++) { s += acc; acc = i; } return s; }
function lateDefined(n) { let s = 0; for (let i = 0; i < n; i++) { s += typeof lateVar === "undefined" ? 0 : lateVar; if (i === 5) globalThis.lateVar = 100; } return s; }
function deleted(n) { globalThis.tmpG = 1; let s = 0; for (let i = 0; i < n; i++) { if (i === 3) delete globalThis.tmpG; s += typeof tmpG === "number" ? tmpG : -1; } return s; }
function becomesAccessor(n) { globalThis.morph = 1; let s = 0; for (let i = 0; i < n; i++) { if (i === 4) Object.defineProperty(globalThis, "morph", { get() { return 50; }, configurable: true }); s += morph; } delete globalThis.morph; return s; }
function constWrite() { try { constG2 = 1; } catch (e) { return e.constructor.name; } return "ok"; }
const constG2 = 9;
function strictUndeclared() { "use strict"; try { notDeclaredAnywhere = 1; } catch (e) { return e.constructor.name; } return "ok"; }
function counterUpdates(n) { for (let i = 0; i < n; i++) { gCount += 2; gCount -= 1; gCount *= 1; ++gCount; gCount--; } return gCount; }
function shadowedByLocal(n) { let gCount = 1000; for (let i = 0; i < n; i++) gCount++; return gCount; }
function readMissing() { try { return missingGlobalName; } catch (e) { return e.constructor.name + ": " + e.message; } }
for (let k = 0; k < 3; k++) {
  console.log(bump(10), implicit(5), viaThis(10), accessorGlobal(5), lateDefined(10), deleted(6), becomesAccessor(8));
  console.log(constWrite(), strictUndeclared(), constG + constG2, counterUpdates(10), shadowedByLocal(5), readMissing());
}
"""
    check(js, golden, "global_bindings", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_equality_and_relational_operator_matrix(js, golden, tier):
    """CATCHES: fused compare-and-branch templates that treat -0/NaN/BigInt/strings/objects with
    the number fast path, apply strict semantics to `==` (or vice versa), or mis-order string
    comparisons."""
    code = r"""
function eqMatrix() { const vs = [0, -0, 1, "1", "", null, undefined, NaN, true, false, [], [1], {}, "abc", 1n, Symbol.iterator, 1.5, "1.5"]; const out = [];
  for (let i = 0; i < vs.length; i++) { let row = ""; for (let j = 0; j < vs.length; j++) { const a = vs[i], b = vs[j]; let c = 0; if (a == b) c |= 1; if (a === b) c |= 2; if (a != b) c |= 4; if (a !== b) c |= 8; row += c.toString(16); } out.push(row); }
  return out.join(" "); }
function localEq(xs, ys) { let n = 0; for (let i = 0; i < xs.length; i++) { const a = xs[i], b = ys[i]; if (a === b) n += 1; if (a !== b) n += 10; if (a == b) n += 100; if (a != b) n += 1000; } return n; }
function strEq(n) { const a = ["abc", "abd", "ab" + "c", "", "abcd"]; let c = 0; for (let i = 0; i < n; i++) { const x = a[i % 5], y = a[(i + 2) % 5]; if (x === y) c++; if (x === "abc") c += 10; if (x < y) c += 100; } return c; }
function nullish(xs) { let r = ""; for (const x of xs) { r += (x == null ? "N" : "v") + (x ?? "d") + (x?.length ?? "-") + (x === null) + ","; } return r; }
function shortCircuit(n) { let c = 0; for (let i = 0; i < n; i++) { const a = i % 3, b = i % 5; if ((a === 0 || b === 0) && !(a === 1 && b === 1)) c++; if (a == 2 ? b != 4 : b == 3) c += 100; if (!(a < b) || a >= 2) c += 10000; } return c; }
function relational(n) { const vs = ["10", 9, "9", "a", null, undefined, true, [2], NaN, 2n, "B", "b"]; let s = ""; for (let i = 0; i < n; i++) { const a = vs[i % 12], b = vs[(i * 5) % 12]; s += (a < b ? 1 : 0) + (a >= b ? 2 : 0) + (a > b ? 4 : 0) + (a <= b ? 8 : 0) + ","; } return s; }
function objIdentity(n) { const o = {}, p = {}; let c = 0; for (let i = 0; i < n; i++) { const x = i & 1 ? o : p; if (x === o) c++; if (x == p) c += 100; if (x !== p && x != o) c += 10000; } return c; }
function boolBranch(xs) { let r = ""; for (const x of xs) r += (x ? "T" : "F") + (!x ? "t" : "f"); return r; }
function loopCompare(n, m) { let c = 0; for (let i = 0; i < n; i++) { for (let j = n; j >= 0; j--) { if (i === j) c += 1; else if (i > j) c += 2; else if (j <= i + m) c += 3; } } return c; }
for (let k = 0; k < 3; k++) {
  console.log(eqMatrix());
  console.log(localEq([1, "1", null, undefined, NaN, 0, {}, "x", 2n], [1, 1, undefined, null, NaN, -0, {}, "x", 2]), strEq(25), nullish([null, undefined, 0, "", "ab", [1]]), shortCircuit(30), objIdentity(10));
  console.log(relational(24), boolBranch([0, -0, NaN, "", "0", [], {}, null, 1n, 0n, undefined]), loopCompare(12, 3));
}
"""
    check(js, golden, "equality_matrix", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_instanceof_hasinstance_and_prototype_swaps(js, golden, tier):
    """CATCHES: an inline instanceof that caches the prototype chain answer across a replaced
    `F.prototype` or setPrototypeOf, ignores Symbol.hasInstance or bound targets, or fails to throw
    for a non-callable right-hand side."""
    code = r"""
class A {} class B extends A {} function F() {}
function check(objs) { let r = ""; for (const o of objs) r += (o instanceof A ? "A" : "-") + (o instanceof B ? "B" : "-") + (o instanceof F ? "F" : "-") + (o instanceof Object ? "O" : "-") + (o instanceof Function ? "f" : "-") + " "; return r; }
function hasInst(n) { const Even = { [Symbol.hasInstance](v) { return v % 2 === 0; } }; let c = 0; for (let i = 0; i < n; i++) if (i instanceof Even) c++; return c; }
function boundInst(n) { const BA = A.bind(null); let c = 0; const a = new B(); for (let i = 0; i < n; i++) if (a instanceof BA) c++; return c; }
function protoSwap(n) { const o = new F(); let r = ""; for (let i = 0; i < n; i++) { if (i === 3) F.prototype = {}; if (i === 6) Object.setPrototypeOf(o, F.prototype); r += o instanceof F ? 1 : 0; } return r; }
function badRhs() { const names = []; for (const rhs of [5, {}, null, "s"]) { try { ({}) instanceof rhs; } catch (e) { names.push(e.constructor.name); } } return names.join(); }
function badProto() { function G() {} G.prototype = 3; try { return ({}) instanceof G; } catch (e) { return e.constructor.name; } }
function primitives(n) { let c = 0; const vs = [1, "s", null, undefined, true, Object(1), new String("s")]; for (let i = 0; i < n; i++) { const v = vs[i % 7]; if (v instanceof Number) c += 1; if (v instanceof String) c += 10; if (v instanceof Object) c += 100; } return c; }
function proxyInst(n) { const p = new Proxy(new B(), {}); const PA = new Proxy(A, {}); let c = 0; for (let i = 0; i < n; i++) { if (p instanceof A) c++; if (new B() instanceof PA) c += 100; } return c; }
function nullProto(n) { const o = Object.create(null); let c = 0; for (let i = 0; i < n; i++) if (!(o instanceof Object)) c++; return c; }
function hasInstanceCount(n) { let calls = 0; class C { static [Symbol.hasInstance](v) { calls++; return v === 1; } } let t = 0; for (let i = 0; i < n; i++) if (i instanceof C) t++; return t + ":" + calls; }
for (let k = 0; k < 3; k++) console.log(check([new A(), new B(), new F(), {}, Object.create(null), [], () => 1]), hasInst(20), boundInst(10), protoSwap(9), badRhs(), badProto(), primitives(14), proxyInst(10), nullProto(5), hasInstanceCount(6));
"""
    check(js, golden, "instanceof", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_string_building_and_append_paths(js, golden, tier):
    """CATCHES: the fused string-append template (`o.s += x`) that drops the ToString of
    non-string operands, double-appends, or reads the property after the right-hand side; and
    charCodeAt/indexing that mishandle surrogate pairs or out-of-range positions."""
    code = r"""
function build(n) { let s = ""; for (let i = 0; i < n; i++) s += i % 10; return s; }
function appendProp(n) { const o = { s: "" }; for (let i = 0; i < n; i++) { o.s += "ab"; o.s += i; o.s += null; } return o.s.length + o.s.slice(-12); }
function appendThis(n) { function B() { this.out = ""; } B.prototype.w = function (x) { this.out += x; return this; }; const b = new B(); for (let i = 0; i < n; i++) b.w("<").w(i).w(">"); return b.out.slice(0, 24); }
function appendNumeric(n) { const o = { s: 1 }; for (let i = 0; i < n; i++) o.s += i; const p = { s: "x" }; for (let i = 0; i < n; i++) p.s += { toString() { return "T"; } }; return o.s + ":" + p.s; }
function appendOrder(n) { const log = []; const o = { get s() { log.push("get"); return "v"; }, set s(v) { log.push("set:" + v); } }; for (let i = 0; i < n; i++) o.s += (log.push("rhs"), i); return log.join(","); }
function codes(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h + ":" + s.charCodeAt(s.length) + ":" + s.codePointAt(0); }
function chars(s) { let r = ""; for (let i = s.length - 1; i >= 0; i--) r += s[i] + s.charAt(i).toUpperCase(); return r + s.charAt(99) + "|" + s.at(-1); }
function unicode(s) { let n = 0; const cps = []; for (const ch of s) { n++; cps.push(ch.codePointAt(0).toString(16)); } return n + ":" + s.length + ":" + cps.join(".") + ":" + s.split("").length; }
function cmpStr(words) { let c = 0; for (let i = 1; i < words.length; i++) { if (words[i - 1] < words[i]) c++; if (words[i] > "m") c += 10; if (words[i] === words[i - 1]) c += 100; } return c; }
function tmpl(n) { const r = []; for (let i = 0; i < n; i++) r.push(`${i}-${i * 2}:${typeof i}${[i]}${null}`); return r.join(); }
function numToStr(n) { const r = []; for (let i = 0; i < n; i++) r.push(String(i / 4), (i * 1e21).toString(), (-i).toString(2), (i + 0.1).toFixed(3), (255 * i).toString(16)); return r.join(" "); }
function strNum(xs) { let s = 0; for (const x of xs) s += +x; return s; }
function mixedConcat(n) { const vs = [1, "a", null, undefined, true, 2.5, [1, 2], { toString() { return "T"; } }, -0, 1e21, 2n]; let s = ""; for (let i = 0; i < n; i++) s += vs[i % vs.length]; return s; }
function addTypes(n) { const vs = [1, "1", null, true, [], {}, undefined]; const out = []; for (let i = 0; i < n; i++) { const a = vs[i % 7], b = vs[(i + 3) % 7]; out.push(String(a + b)); } return out.join("|"); }
function repeatJoin(n) { const parts = []; for (let i = 0; i < n; i++) parts.push("x".repeat(i % 4) || "-"); return parts.join("").length + parts.join(".").slice(0, 15); }
for (let k = 0; k < 3; k++) {
  console.log(build(30), appendProp(20), appendThis(10), appendNumeric(5), appendOrder(2));
  console.log(codes("hello world"), chars("abc"), unicode("aé\u{1F600}z"), cmpStr(["apple", "banana", "banana", "cherry", "zeta", "alpha"]), tmpl(3));
  console.log(numToStr(4), strNum(["1", " 2 ", "0x10", "", "1e3", "-0", "0b11", "abc"]), mixedConcat(22), repeatJoin(9));
  console.log(addTypes(14));
}
"""
    check(js, golden, "string_building", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_regexp_exec_replace_match_loops(js, golden, tier):
    """CATCHES: specialised regexp loops (global `re.exec(strs[i])`, literal exec/replace/match
    statements) that skip updating lastIndex or RegExp statics, or drop the side effects of
    discarded calls."""
    code = r"""
var re = /(\d+)-(\w+)/; var reG = /o/g; var inputs = ["12-ab", "x", "999-zz", "7-q", "no"];
function execLoop() { for (var i = 0; i < inputs.length; i++) re.exec(inputs[i]); }
function execGlobal() { for (var i = 0; i < inputs.length; i++) reG.exec(inputs[i]); }
function execLit() { for (var i = 0; i < inputs.length; i++) { /a(b)?/.exec(inputs[i]); /z+/.exec("zzz"); } }
function replLoop() { var out = []; for (var i = 0; i < inputs.length; i++) { inputs[i].replace(/\d/g, "#"); out.push(inputs[i].replace(/\d/g, "#")); } return out.join(); }
function matchLoop() { var c = 0; for (var i = 0; i < inputs.length; i++) { inputs[i].match(/\w/); if (inputs[i].match(/\d+/)) c++; } return c; }
function globalExec(s) { const r = /o/g; const idx = []; let m; while ((m = r.exec(s)) !== null) idx.push(m.index + ":" + r.lastIndex); return idx.join(); }
function testLoop(n) { let c = 0; const r = /^[a-c]+$/; for (let i = 0; i < n; i++) if (r.test(["abc", "abd", "cab", ""][i % 4])) c++; return c; }
function sticky(s) { const r = /\d/y; let out = ""; for (let i = 0; i < s.length; i++) { r.lastIndex = i; out += r.test(s) ? "d" : "."; } return out; }
function replaceFn(n) { const r = []; for (let i = 0; i < n; i++) r.push("a1b2".replace(/\d/g, (d, off) => "[" + (d * i) + "@" + off + "]")); return r.join(" "); }
function namedGroups(s) { const out = []; for (const m of s.matchAll(/(?<k>\w)=(?<v>\d)/g)) out.push(m.groups.k + m.groups.v + m.index); return out.join(); }
for (let k = 0; k < 30; k++) { execLoop(); execLit(); }
for (let k = 0; k < 7; k++) execGlobal();
console.log("lastIndex", reG.lastIndex, RegExp.$1, RegExp.lastMatch);
for (let k = 0; k < 3; k++) console.log(re.exec(inputs[0]).join("/"), replLoop(), matchLoop(), globalExec("foo boo"), testLoop(10), sticky("a1b2"), "a1b22c333".split(/\d+/).join("|"), replaceFn(2), namedGroups("a=1,b=2"));
var reAll = /(\d+)-(\w+)/g; var subjects = ["12-ab", "x", "999-zz", "7-q", "no"];
function execFixed() { for (var i = 0; i < 5; i++) reAll.exec(subjects[i]); return reAll.lastIndex; }
let fixedTotal = 0; for (let k = 0; k < 30; k++) fixedTotal += execFixed();
console.log("fixed", fixedTotal, RegExp.$1, RegExp.$2, reAll.lastIndex);
subjects[2] = 42; console.log(execFixed(), RegExp.lastMatch);
subjects.length = 2; console.log(execFixed(), RegExp.lastMatch);
reAll.exec = function () { return null; }; subjects.length = 5; console.log(execFixed());
"""
    check(js, golden, "regexp_loops", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_for_in_switch_and_labeled_control_flow(js, golden, tier):
    """CATCHES: compiled for-in that visits deleted keys or skips integer-key ordering, switch
    lowering that breaks fallthrough or case-block TDZ, and labeled break/continue across nested
    for-of loops that fail to close the abandoned iterators."""
    code = r"""
function forIn(o) { const ks = []; for (const k in o) { ks.push(k); } return ks.join(); }
function forInDelete() { const o = { a: 1, b: 2, c: 3, d: 4 }; const seen = []; for (const k in o) { seen.push(k); if (k === "a") delete o.c; if (k === "b") o.e = 5; } return seen.join(); }
function forInProto() { const p = { inherited: 1, shadow: 2 }; const o = Object.create(p); o.own = 2; o[2] = "x"; o[1] = "y"; o.shadow = 3; Object.defineProperty(o, "hidden", { value: 3, enumerable: false }); const r = []; for (const k in o) r.push(k); return r.join(); }
function forInVar(o) { var k; let r = ""; for (k in o) r += k; for (var j in [7, 8]) r += j; for (const q in "ab") r += q; for (const z in null) r += z; return r + k + j; }
function forInArrays(n) { let c = 0; for (let i = 0; i < n; i++) for (const k in [5, , 7]) c += Number(k); return c; }
function sw(n) { let r = ""; for (let i = 0; i < n; i++) { switch (i % 5) { case 0: { let t = "z"; r += t; break; } case 1: r += "o"; case 2: r += "t"; break; case "3": r += "S"; break; default: r += "d"; } } return r; }
function swStr(xs) { let r = 0; for (const x of xs) { switch (x) { case "a": r += 1; break; case "b": case "c": r += 10; break; case 1: r += 100; break; default: r += 1000; } } return r; }
function swLex(n) { const r = []; for (let i = 0; i < n; i++) { switch (i) { case 0: let v = "first"; r.push(v); break; case 1: r.push("second"); break; default: try { r.push(v); } catch (e) { r.push(e.constructor.name); } } } return r.join(); }
function swClosure(n) { const fs = []; for (let i = 0; i < n; i++) { switch (i % 2) { case 0: const c = i * 10; fs.push(() => c); break; default: fs.push(() => -i); } } return fs.map(f => f()).join(); }
function labeled(n) { let c = 0; outer: for (let i = 0; i < n; i++) { inner: for (let j = 0; j < n; j++) { if (j > i) continue outer; if (i + j > 6) break outer; c += i * j; } } return c; }
function labeledForOf(A, B) { let n = 0; outer: for (let i = 0; i < 2; i++) { for (const a of A) { for (const b of B) { if (b > a) continue outer; if (a > 3) break outer; n += a * b + i; } } } return n; }
function closingIter() { const log = []; const mk = (tag) => ({ [Symbol.iterator]() { let i = 0; return { next() { return { value: i++, done: i > 3 }; }, return() { log.push("close" + tag); return {}; } }; } });
  outer: for (let r = 0; r < 2; r++) { for (const a of mk("A")) { for (const b of mk("B")) { if (b === 1) continue outer; } } } return log.join(","); }
function labelBlock(x) { let r = "s"; blk: { if (x) break blk; r += "-not"; } return r + x; }
function doWhile(n) { let i = 0, s = 0; do { s += i; i++; if (i === 3) continue; } while (i < n); return s; }
function whileBreak(n) { let i = 0; while (true) { if (++i > n) break; } return i; }
for (let k = 0; k < 3; k++) {
  console.log(forIn({ x: 1, y: 2, 10: 3, 2: 4, "-1": 5 }), forInDelete(), forInProto(), forInVar({ p: 1, q: 2 }), forInArrays(5));
  console.log(sw(12), swStr(["a", "b", "c", 1, "1", null]), swLex(3), swClosure(4), labeled(6), labeledForOf([1, 2, 3, 4, 5], [1, 2, 3]), closingIter(), labelBlock(0) + labelBlock(1), doWhile(5), whileBreak(7));
}
"""
    check(js, golden, "control_flow", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_destructuring_and_binding_forms(js, golden, tier):
    """CATCHES: destructuring lowering that reads properties in the wrong order, ignores
    defaults or rest elements, mis-handles holes, or closures over block-scoped destructured
    bindings and duplicate sloppy parameters that see the wrong value."""
    code = r"""
function destr(n) { let r = 0; for (let i = 0; i < n; i++) { const { a, b: { c } } = { a: i, b: { c: 2 } }; const [x, , y] = [1, 2, 3]; let [p, q] = [i, -i]; [p, q] = [q, p]; r += a + c + x + y + p - q; } return r; }
function destrDefaults(objs) { let r = ""; for (const { a = "A", b: [c = "C"] = [], ...rest } of objs) r += a + c + Object.keys(rest).join("") + ";"; return r; }
function forOfDestr(m) { let r = ""; for (const [k, v] of m) r += k + v; for (const [i, ch] of [..."ab"].entries()) r += i + ch; return r; }
function order() { const log = []; const src = { get a() { log.push("a"); return 1; }, get b() { log.push("b"); return 2; } }; const { b, a } = src; return log.join("") + a + b; }
function nullDestr() { const names = []; for (const v of [null, undefined]) { try { const { x } = v; } catch (e) { names.push(e.constructor.name); } } return names.join(); }
function assignTargets(n) { const o = {}; const arr = []; let a, b; for (let i = 0; i < n; i++) { [o.x, arr[i]] = [i, i * 2]; ({ a, b = 9 } = { a: i }); } return JSON.stringify(o) + arr.join() + a + b; }
function forOfTargets(arr) { let a, b; const o = {}; const r = []; for ([a, b] of arr) r.push(a + b); for ({ a, b } of [{ a: 1, b: 2 }]) r.push(a * b); for (o.p of arr) r.push(o.p.length); return r.join(); }
function iterDestr() { function* g() { yield 1; yield 2; yield 3; } const [first, ...rest] = g(); const [m, n] = new Set(["s1", "s2", "s3"]); const [c1, c2] = "hi"; return first + ":" + rest + ":" + m + n + c1 + c2; }
function swapVars(n) { let a = 1, b = 2; for (let i = 0; i < n; i++) [a, b] = [b, a + b]; return a + "," + b; }
function blockCapture(o) { if (o) { let { a, b } = o; return () => a + b; } return null; }
function paramDup(a, a) { let s = 0; for (let i = 0; i < 3; i++) s += a; return s; }
function nestedDefaults({ x = 1, y: { z = 2 } = {} } = {}, [w = 3] = []) { return x + y_or(z) + w; }
function y_or(v) { return v * 10; }
function computedKeys(n) { const keys = ["p", "q"]; let r = ""; for (let i = 0; i < n; i++) { const { [keys[i % 2]]: v = "d" } = { p: "P" }; r += v; } return r; }
for (let k = 0; k < 3; k++) {
  console.log(destr(5), destrDefaults([{}, { a: 1, b: [2], z: 0 }]), forOfDestr(new Map([["k", 1]])), order(), nullDestr(), assignTargets(3), forOfTargets([[1, 2], [3, 4]]), iterDestr(), swapVars(10));
  const xs = []; for (let i = 0; i < 12; i++) xs.push(blockCapture({ a: i, b: 1 })(), paramDup(1, i)); console.log(xs.join(","), nestedDefaults(), nestedDefaults({ x: 5, y: {} }, [7]), computedKeys(4));
}
"""
    check(js, golden, "destructuring", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_object_literals_and_computed_members(js, golden, tier):
    """CATCHES: object-literal shape templates that reorder or deduplicate keys incorrectly, treat
    a computed `__proto__` key as a prototype setter, lose accessor or method definitions, or
    evaluate spread and computed keys out of order."""
    code = r"""
function lit(i) { return { a: i, b: "s" + i, c: [i], ["d"]: i * 2, ["e" + ""]: 1, a: -i, get g() { return this.a * 10; }, m() { return this.b; }, 7: "seven", "x y": 0 }; }
function protoLit(i) { const p = { inherited: i }; const o1 = { __proto__: p, own: 1 }; const o2 = { ["__proto__"]: p }; const __proto__ = 5; const o3 = { __proto__ }; return [o1.inherited, Object.keys(o1).join(), Object.getPrototypeOf(o2) === Object.prototype, Object.keys(o2).join(), o3.__proto__ === 5 ? "own5" : "x"].join(":"); }
function spreadLit(n) { const base = { a: 1, b: 2 }; const log = []; let r; for (let i = 0; i < n; i++) r = { ...base, b: i, ...null, ...undefined, ...[9], ...{ get c() { log.push("c"); return 3; } }, ...(log.push("k"), {}) }; return JSON.stringify(r) + log.length; }
function order(n) { const log = []; const k = (s) => (log.push(s), s); for (let i = 0; i < n; i++) ({ [k("x")]: k("vx"), [k("y")]: k("vy") }); return log.join(""); }
function shorthand(n) { const out = []; for (let i = 0; i < n; i++) { const x = i, y = i * i; const o = { x, y, f() { return x + y; }, async g() { return 1; }, *h() { yield 1; } }; out.push(o.f() + typeof o.g + typeof o.h().next); } return out.join(); }
function numericKeys(n) { const o = { 2: "b", 1: "a", z: "z", "10": "j", "-1": "m", 1.5: "f" }; let s = ""; for (let i = 0; i < n; i++) s += o[1] + o["2"] + o[1.5] + o[-1]; return Object.keys(o).join() + "|" + s; }
function nestedLit(n) { let t = 0; for (let i = 0; i < n; i++) { const o = { p: { q: { r: i } }, arr: [{ v: i }, { v: -i }] }; t += o.p.q.r + o.arr[1].v + o.arr.length; } return t; }
function symbolsLit() { const s = Symbol("tag"); const o = { [s]: 1, [Symbol.toStringTag]: "Custom" }; return String(o) + Object.getOwnPropertySymbols(o).length; }
function fnNames() { const o = { f: function () {}, g: () => {}, ["h" + 1]: function () {}, get acc() { return 1; } }; return [o.f.name, o.g.name, o.h1.name, Object.getOwnPropertyDescriptor(o, "acc").get.name].join(); }
for (let k = 0; k < 3; k++) {
  const parts = []; for (let i = 0; i < 12; i++) { const o = lit(i); parts.push(JSON.stringify(o) + o.g + o.m()); }
  console.log(parts[0]); console.log(parts[11]);
  console.log(protoLit(3), spreadLit(5), order(2), shorthand(3), numericKeys(2), nestedLit(10), symbolsLit(), fnNames());
}
"""
    check(js, golden, "object_literals", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_captured_bindings_in_loops_and_activations(js, golden, tier):
    """CATCHES: compiled activations that share one captured slot across loop iterations, read a
    stale captured value after a closure writes it, or lose captured parameters/defaults when a
    closure escapes and the activation is promoted."""
    code = r"""
function perIteration(n) { const fs = []; for (let i = 0; i < n; i++) { let j = i * 2; fs.push(() => i + ":" + j++); } return fs.map(f => f() + "/" + f()).join(); }
function sharedVar(n) { const fs = []; for (var i = 0; i < n; i++) fs.push(() => i); return fs.map(f => f()).join(); }
function writer(n) { let total = 0; const add = (v) => { total += v; }; for (let i = 0; i < n; i++) { add(i); total *= 1; } return total; }
function readerWriter(n) { let x = 0; const inc = () => ++x; let s = 0; for (let i = 0; i < n; i++) { s += x; inc(); s += x; } return s + ":" + x; }
function capturedParam(a, b = a + 1) { const get = () => a + b; a = a * 10; return get(); }
function capturedDefault(x = {}) { const f = () => x; x.tag = "t"; return f().tag; }
function escaping(n) { const out = []; for (let i = 0; i < n; i++) { const mk = (k) => { let v = k; return { get: () => v, set: (w) => { v = w; } }; }; const c = mk(i); c.set(c.get() * 3); out.push(c.get()); } return out.join(); }
function nestedCapture(n) { let depth1 = 1; const f1 = () => { let depth2 = 10; const f2 = () => { let depth3 = 100; const f3 = () => depth1 + depth2 + depth3; depth3++; return f3(); }; depth2++; return f2(); }; let s = 0; for (let i = 0; i < n; i++) { depth1 = i; s += f1(); } return s; }
function closureCounter(n) { const counters = []; for (let i = 0; i < 3; i++) { let c = 0; counters.push(() => ++c); } let s = ""; for (let i = 0; i < n; i++) s += counters[i % 3](); return s; }
function lexicalThis(n) { const o = { v: 7, run() { const fs = []; for (let i = 0; i < n; i++) fs.push(() => this.v + i); return fs.map(f => f()).join(); } }; return o.run(); }
function evalScope(n) { let x = 1; let s = 0; for (let i = 0; i < n; i++) s += eval("x + i"); return s; }
function withScope(n) { const o = { w: 5 }; let s = 0; with (o) { for (let i = 0; i < n; i++) s += w; } return s; }
function functionInBlock(n) { if (n > 0) { function inner() { return n * 2; } } return typeof inner === "function" ? inner() : -1; }
for (let k = 0; k < 3; k++) {
  console.log(perIteration(4), sharedVar(4), writer(20), readerWriter(10), capturedParam(2), capturedParam(2, 5), capturedDefault(), escaping(4));
  const fib = []; for (let i = 0; i < 12; i++) fib.push(functionInBlock(i - 1)); console.log(nestedCapture(10), closureCounter(7), lexicalThis(3), evalScope(5), withScope(4), fib.join());
}
"""
    check(js, golden, "captured_bindings", code, tier)
