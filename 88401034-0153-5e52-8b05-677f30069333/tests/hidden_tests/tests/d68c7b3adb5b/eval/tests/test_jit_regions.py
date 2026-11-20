"""Specialised JIT regions and the bytecode VM's inline recompile, checked against the oracle.

docs/optimizer.md and the closure/numeric-region notes describe the shapes the ARM64 JIT
specialises: linear numeric loops over dense arrays, branchy numeric CFG regions with
invariant property/global inputs, object-element "mixed" loops with borrowed shadow frames,
numeric property chains and field expressions, and guarded inlining of hot monomorphic callees
(recompiled after 100 machine-code runs). Each program warms those shapes until they are
compiled, then feeds them values that must leave the fast path (strings, holes, getters,
proxies, out-of-range indices, int32 overflow, NaN, -0, redefined callees, prototype changes).
Every run must print the same golden on the JIT, the bytecode VM and the tree-walking oracle.
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
def test_linear_numeric_loop_kernels(js, golden, tier):
    """CATCHES: a linear numeric loop emitter that mis-assigns FP registers, drops element stores, reuses a stale key for repeated a[i] reads, evaluates pre/post increments in the wrong order, or exits on the wrong comparison (<=, >=, >, !==, !=)."""
    code = r"""
var SCALE = 3, OFFSET = 0.5;
function axpy(a, b, n) { for (let i = 0; i < n; i++) b[i] = a[i] * SCALE + b[i]; return b; }
function dot(a, b, n) { let s = 0; for (let i = 0; i < n; i++) s += a[i] * b[i]; return s; }
function negate(a, n) { for (let i = 0; i < n; i++) a[i] = -a[i]; return a; }
function chainAssign(a, b, n) { let last = 0; for (let i = 0; i < n; i++) last = b[i] = a[i] + OFFSET; return last; }
function prefix(a, n) { for (let i = 1; i < n; i++) a[i] = a[i] + a[i - 1]; return a; }
function countDown(a, n) { let s = 0; for (let i = n - 1; i >= 0; i--) s = s * 2 - a[i]; return s; }
function untilZero(a) { let i = 0; while (a[i] !== 0) i++; return i; }
function untilEq(a, v) { let i = 0; while (a[i] != v) i += 1; return i; }
function le(n) { let s = 0; for (let i = 0; i <= n; i++) s += i * i; return s; }
function gt(n) { let s = 0, i = n; while (i > 0) { s ^= i << 2; i--; } return s; }
function bitsLoop(a, n) { let h = 0; for (let i = 0; i < n; i++) h = ((h << 5) - h + a[i]) | 0; return h; }
function shifts(a, n) { let x = 0; for (let i = 0; i < n; i++) x = (x >>> 1) ^ (a[i] & 255) ^ (x >> 3); return x; }
function divLoop(a, n) { let s = 0; for (let i = 0; i < n; i++) s += a[i] / (i + 1); return s; }
function copy(a, b, n) { for (let i = 0; i < n; i++) b[i] = a[i]; return b; }
function dupKey(a, n) { let s = 0; for (let i = 0; i < n; i++) s += a[i] + a[i] * a[i]; return s; }
function twoArr(a, b, c, n) { for (let i = 0; i < n; i++) c[i] = a[i] - b[i] * 0.5; return c; }
function stride(a, n) { let s = 0; for (let i = 0; i < n; i += 2) s += a[i] - a[i + 1]; return s; }
function preInc(a, n) { let s = 0, i = -1; while (i < n - 1) s += a[++i]; return s; }
function fmt(x) { return Array.isArray(x) ? x.map(v => Object.is(v, -0) ? "-0" : String(v)).join(",") : String(x); }
function run(label, f) { console.log(label + ": " + fmt(f())); }
const base = () => Array.from({ length: 16 }, (_, i) => i - 4);
for (let k = 0; k < 40; k++) { axpy(base(), base(), 16); dot(base(), base(), 16); negate(base(), 16); chainAssign(base(), base(), 16); prefix(base(), 16); countDown(base(), 16); untilZero(base()); untilEq(base(), 7); le(20); gt(20); bitsLoop(base(), 16); shifts(base(), 16); divLoop(base(), 16); copy(base(), base(), 16); dupKey(base(), 16); twoArr(base(), base(), base(), 16); stride(base(), 16); preInc(base(), 16); }
run("axpy", () => axpy(base(), base(), 16));
run("dot", () => dot(base(), base(), 16));
run("negate", () => negate(base(), 16));
run("chain", () => chainAssign(base(), base(), 16));
run("prefix", () => prefix(base(), 16));
run("countDown", () => countDown(base(), 16));
run("untilZero", () => untilZero(base()));
run("untilEq", () => untilEq(base(), 7));
run("le", () => le(20));
run("gt", () => gt(20));
run("bits", () => bitsLoop(base(), 16));
run("shifts", () => shifts(base(), 16));
run("div", () => divLoop(base(), 16));
run("copy", () => copy(base(), base(), 16));
run("dupKey", () => dupKey(base(), 16));
run("twoArr", () => twoArr(base(), base(), base(), 16));
run("stride", () => stride(base(), 16));
run("preInc", () => preInc(base(), 16));
"""
    check(js, golden, "linear_kernels", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_linear_numeric_loops_leave_the_fast_path_correctly(js, golden, tier):
    """CATCHES: numeric loop side exits that resume at the wrong iteration or with stale register values when an element is a string, hole, getter, proxy, BigInt or typed-array value, the index runs past the length, int32 arithmetic overflows, or a global constant used in the loop changes type."""
    code = r"""
var SCALE = 3, OFFSET = 0.5;
function axpy(a, b, n) { for (let i = 0; i < n; i++) b[i] = a[i] * SCALE + b[i]; return b; }
function dot(a, b, n) { let s = 0; for (let i = 0; i < n; i++) s += a[i] * b[i]; return s; }
function negate(a, n) { for (let i = 0; i < n; i++) a[i] = -a[i]; return a; }
function chainAssign(a, b, n) { let last = 0; for (let i = 0; i < n; i++) last = b[i] = a[i] + OFFSET; return last; }
function prefix(a, n) { for (let i = 1; i < n; i++) a[i] = a[i] + a[i - 1]; return a; }
function countDown(a, n) { let s = 0; for (let i = n - 1; i >= 0; i--) s = s * 2 - a[i]; return s; }
function untilZero(a) { let i = 0; while (a[i] !== 0) i++; return i; }
function untilEq(a, v) { let i = 0; while (a[i] != v) i += 1; return i; }
function le(n) { let s = 0; for (let i = 0; i <= n; i++) s += i * i; return s; }
function gt(n) { let s = 0, i = n; while (i > 0) { s ^= i << 2; i--; } return s; }
function bitsLoop(a, n) { let h = 0; for (let i = 0; i < n; i++) h = ((h << 5) - h + a[i]) | 0; return h; }
function shifts(a, n) { let x = 0; for (let i = 0; i < n; i++) x = (x >>> 1) ^ (a[i] & 255) ^ (x >> 3); return x; }
function divLoop(a, n) { let s = 0; for (let i = 0; i < n; i++) s += a[i] / (i + 1); return s; }
function copy(a, b, n) { for (let i = 0; i < n; i++) b[i] = a[i]; return b; }
function dupKey(a, n) { let s = 0; for (let i = 0; i < n; i++) s += a[i] + a[i] * a[i]; return s; }
function twoArr(a, b, c, n) { for (let i = 0; i < n; i++) c[i] = a[i] - b[i] * 0.5; return c; }
function stride(a, n) { let s = 0; for (let i = 0; i < n; i += 2) s += a[i] - a[i + 1]; return s; }
function preInc(a, n) { let s = 0, i = -1; while (i < n - 1) s += a[++i]; return s; }
function fmt(x) { return Array.isArray(x) ? x.map(v => Object.is(v, -0) ? "-0" : String(v)).join(",") : String(x); }
function run(label, f) { console.log(label + ": " + fmt(f())); }
const base = () => Array.from({ length: 16 }, (_, i) => i - 4);
for (let k = 0; k < 40; k++) { axpy(base(), base(), 16); dot(base(), base(), 16); negate(base(), 16); chainAssign(base(), base(), 16); prefix(base(), 16); countDown(base(), 16); untilZero(base()); untilEq(base(), 7); le(20); gt(20); bitsLoop(base(), 16); shifts(base(), 16); divLoop(base(), 16); copy(base(), base(), 16); dupKey(base(), 16); twoArr(base(), base(), base(), 16); stride(base(), 16); preInc(base(), 16); }
// deopts: holes, strings, undefined past end, doubles, int overflow, NaN, -0, getters
run("axpy-str", () => axpy([1, "2", 3], [1, 1, 1], 3));
run("axpy-oob", () => axpy([1, 2], [1, 1, 1, 1], 4));
run("dot-hole", () => dot([1, , 3], [1, 1, 1], 3));
run("dot-obj", () => dot([1, { valueOf() { return 10; } }, 3], [1, 1, 1], 3));
run("negate-zero", () => negate([0, -0, NaN, Infinity], 4));
run("bits-big", () => bitsLoop([2147483647, 2147483647, 4294967296.7, -1e20], 4));
run("prefix-overflow", () => prefix([2147483647, 2147483647, 2147483647, 1], 4));
run("copy-getter", () => { const src = [1, 2, 3]; Object.defineProperty(src, 1, { get() { return 99; } }); return copy(src, [0, 0, 0], 3); });
run("copy-typed", () => copy(new Float64Array([1.5, 2.5, 3.5]), new Int8Array(3), 3));
run("SCALE-change", () => { SCALE = "x"; const r = axpy([1, 2], [3, 4], 2); SCALE = 3; return r; });
run("untilZero-miss", () => untilZero([1, 2, "0", 0]));
run("stride-odd", () => stride([1, 2, 3], 3));
run("dot-proto", () => { const a = [1, 2]; a.length = 3; Array.prototype[2] = 5; const r = dot(a, [1, 1, 1], 3); delete Array.prototype[2]; return r; });
run("copy-grow", () => copy([1, 2, 3, 4], [9], 4));
run("copy-frozen-dst", () => copy([1, 2, 3], Object.freeze([0, 0, 0]), 3));
run("copy-sealed-dst", () => { const d = Object.seal([0, 0]); copy([5, 6, 7], d, 3); return d; });
run("axpy-typed", () => Array.from(axpy(new Int32Array([1, 2, 3]), new Float64Array([0.5, 0.5, 0.5]), 3)));
run("negate-uint8", () => Array.from(negate(new Uint8Array([1, 2, 255]), 3)));
run("dot-deleted", () => { const a = [1, 2, 3]; delete a[1]; return dot(a, [1, 1, 1], 3); });
run("prefix-bigint", () => { try { return prefix([1n, 2n, 3n], 3); } catch (e) { return e.constructor.name; } });
run("dupKey-nan", () => dupKey([NaN, Infinity, -Infinity], 3));
run("stride-proxy", () => stride(new Proxy([1, 2, 3, 4], {}), 4));
run("bits-strings", () => bitsLoop(["1", "x", "0x10", true], 4));
run("shifts-neg", () => shifts([-1, -256, 2 ** 31, -(2 ** 31)], 4));
run("le-fraction", () => le(2.5));
run("gt-negative", () => gt(-3));
run("countDown-empty", () => countDown([], 0));
run("untilEq-string", () => untilEq(["a", "b", "c"], "c"));
run("preInc-holey", () => preInc([1, , 3], 3));
run("twoArr-alias", () => { const x = [1, 2, 3]; return twoArr(x, x, x, 3); });
run("chain-getter-dst", () => { const b = [0, 0]; Object.defineProperty(b, 0, { set(v) { this.seen = v; }, get() { return -1; } }); chainAssign([1, 2], b, 2); return [b[0], b[1], b.seen]; });
"""
    check(js, golden, "linear_kernel_exits", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_branchy_numeric_loops_with_invariant_inputs(js, golden, tier):
    """CATCHES: numeric CFG regions with forward branches, break/continue and do-while latches that keep a cached property or global input after it changes, or keep running natively after an element stops being a number."""
    code = r"""
var LIMIT = 50;
function absSum(a, n) { let s = 0; for (let i = 0; i < n; i++) { const v = a[i]; if (v < 0) { s -= v; } else { s += v; } } return s; }
function clampSum(o, a, n) { let s = 0; for (let i = 0; i < n; i++) { let v = a[i] * o.scale; if (v > o.max) { v = o.max; } if (v < -o.max) { v = -o.max; } s += v; } return s; }
function thisLoop(a, n) { let s = 0; for (let i = 0; i < n; i++) { if (a[i] >= this.lo) { s += a[i] * this.w; } } return s; }
function globalLimit(n) { let s = 0, c = 0; for (let i = 0; i < n; i++) { if (s > LIMIT) { s = s - LIMIT; c++; } else { s = s + i; } } return s + ":" + c; }
function multiExit(a, n) { let i = 0, s = 0; while (i < n) { if (a[i] === 99) { break; } if (a[i] < 0) { i++; continue; } s += a[i]; i++; } return s + "@" + i; }
function nestedIf(a, n) { let x = 0, y = 0; for (let i = 0; i < n; i++) { const v = a[i]; if (v > 2) { if (v > 5) { x += v; } else { y += v; } } else { x -= 1; } } return x + "," + y; }
function divBranch(n) { let s = 0; for (let i = 1; i <= n; i++) { const q = 100 / i; if (q !== q) { s = -1; } else if (q > 10) { s += 1; } else { s += q; } } return s.toFixed(6); }
function countdown(n) { let k = n, t = 0; do { if (k <= 3) { t += 100; } else { t += k; } k--; } while (k > 0); return t; }
const o = { scale: 2, max: 7 }; const ctx = { lo: 0, w: 3 };
const base = () => [3, -1, 4, -1, 5, -9, 2, 6, -5, 3, 5, 8, 9, 7, 9, 3];
for (let k = 0; k < 60; k++) { absSum(base(), 16); clampSum(o, base(), 16); thisLoop.call(ctx, base(), 16); globalLimit(40); multiExit(base(), 16); nestedIf(base(), 16); divBranch(20); countdown(10); }
console.log(absSum(base(), 16), clampSum(o, base(), 16), thisLoop.call(ctx, base(), 16), globalLimit(40), multiExit(base(), 16), multiExit([1, -2, 99, 5], 4), nestedIf(base(), 16), divBranch(20), countdown(10));
// deopts: non-number elements, property type change, getter input, out-of-range, global change
console.log(absSum([1, "2", -3], 3), absSum([1, , -3], 3), absSum([1, 2], 4), absSum([1, { valueOf() { return -10; } }], 2));
o.scale = 0.5; console.log(clampSum(o, base(), 16)); o.max = "3"; console.log(clampSum(o, base(), 16));
Object.defineProperty(ctx, "w", { get() { return 10; } }); console.log(thisLoop.call(ctx, base(), 16));
console.log(thisLoop.call({ lo: 4, w: 1 }, base(), 16), thisLoop.call({ w: 1 }, base(), 16));
LIMIT = 10.5; console.log(globalLimit(40)); LIMIT = "x"; console.log(globalLimit(5));
console.log(nestedIf([10, 1e308, -Infinity, NaN, 4], 5), countdown(1), countdown(2.5));
"""
    check(js, golden, "branchy_numeric_loops", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_object_element_loops_with_shape_and_type_changes(js, golden, tier):
    """CATCHES: mixed object/number loops (arr[i].v, arr[i].get(), o.v = o.v + 1) that publish shadow state incorrectly when an element changes shape, becomes a primitive, null, a proxy, a frozen object or gains an own method, or when the prototype method is replaced mid-run."""
    code = r"""
"use strict";
class P { constructor(v) { this.v = v; this.w = 1; } get() { return this.v * 2; } }
function sumField(arr, n) { let s = 0; for (let i = 0; i < n; i++) { s += arr[i].v; } return s; }
function sumMethod(arr, n) { let s = 0; for (let i = 0; i < n; i++) { s += arr[i].get(); } return s; }
function bump(arr, n) { for (let i = 0; i < n; i++) { const o = arr[i]; o.v = o.v + 1; } return arr[0].v; }
function weighted(arr, n) { let s = 0; for (let i = 0; i < n; i++) { const o = arr[i]; if (o.v > 5) { s += o.v * o.w; } else { s -= o.w; } } return s; }
function findFirst(arr, n, limit) { let i = 0; while (i < n) { if (arr[i].v >= limit) { return i; } i++; } return -1; }
function fieldToThis(arr, n) { for (let i = 0; i < n; i++) { this.total = this.total + arr[i].v; } return this.total; }
function countOn(arr, n) { let c = 0; for (let i = 0; i < n; i++) { if (arr[i].on) { c = c + 1; } } return c; }
function negDiv(arr, n) { let s = 0; for (let i = 0; i < n; i++) { const o = arr[i]; s = s + -o.v / 2 - o.w * -1; } return s; }
function compound(arr, n) { for (let i = 0; i < n; i++) { arr[i].w += arr[i].v; } return arr[n - 1].w; }
function clearField(arr, n) { for (let i = 0; i < n; i++) { const o = arr[i]; if (o.v === 3) { o.tag = undefined; } } return n; }
function make(n) { const a = []; for (let i = 0; i < n; i++) { const p = new P(i); p.on = i % 3 === 0; p.tag = 1; a.push(p); } return a; }
const arr = make(20);
function drive() { let t = 0; for (let k = 0; k < 150; k++) { t += sumField(arr, 20) + sumMethod(arr, 20) + weighted(arr, 20) + findFirst(arr, 20, 10 + k) + countOn(arr, 20) + negDiv(arr, 20) + clearField(arr, 20); bump(arr, 20); } return t; }
function drive2() { const b = make(10); let t = 0; for (let k = 0; k < 120; k++) t += compound(b, 10); return t; }
console.log("compound", drive2());
const t = drive();
const acc = { total: 0 }; for (let k = 0; k < 30; k++) fieldToThis.call(acc, arr, 20);
console.log("warm", t, arr[0].v, arr[19].v, acc.total);
function fresh() { return make(6); }
const lines = [];
// element is not an object / missing / null-proto / getter / proxy / different shape / prototype method swap
let a1 = fresh(); a1[2] = { v: "str", w: 2 }; lines.push(sumField(a1, 6), weighted(a1, 6));
let a2 = fresh(); a2[3] = { w: 5 }; lines.push(sumField(a2, 6), weighted(a2, 6));
let a3 = fresh(); Object.defineProperty(a3[1], "v", { get() { return 100; } }); lines.push(sumField(a3, 6), sumMethod(a3, 6));
let a4 = fresh(); a4[4] = new Proxy({ v: 7, w: 1, get() { return 0; } }, {}); lines.push(sumField(a4, 6), sumMethod(a4, 6), weighted(a4, 6));
let a5 = fresh(); try { sumField(a5, 8); } catch (e) { lines.push(e.constructor.name); }
let a6 = fresh(); a6.length = 3; lines.push(findFirst(a6, 3, 1));
let a7 = fresh(); a7[5] = 12; try { sumMethod(a7, 6); } catch (e) { lines.push(e.constructor.name); }
let a8 = fresh(); a8[0] = null; try { sumField(a8, 6); } catch (e) { lines.push(e.constructor.name); }
const origGet = P.prototype.get; P.prototype.get = function () { return -this.v; }; lines.push(sumMethod(fresh(), 6)); P.prototype.get = origGet;
let a9 = fresh(); a9[2].get = () => 1000; lines.push(sumMethod(a9, 6));
let a10 = fresh(); Object.freeze(a10[1]); try { bump(a10, 6); } catch (e) { lines.push(e.constructor.name); } lines.push(a10.map(o => o.v).join("/"));
let a11 = fresh(); a11[3] = Object.create(a11[0]); lines.push(sumField(a11, 6), sumMethod(a11, 6));
let a12 = fresh(); for (const o of a12) o.extra = 1; lines.push(sumField(a12, 6), weighted(a12, 6));
let a13 = fresh(); a13[1].v = 2.5; a13[2].v = -0; a13[3].v = NaN; lines.push(sumField(a13, 3), weighted(a13, 6));
let a14 = fresh(); a14[2].v = 2147483647; a14[3].v = 2147483647; bump(a14, 6); lines.push(sumField(a14, 6));
const truthy = fresh(); const tv = [1, 0, NaN, "", "x", null, undefined, {}, -0, true, 2n]; for (let i = 0; i < 6; i++) truthy[i].on = tv[i]; lines.push(countOn(truthy, 6)); for (let i = 0; i < 5; i++) truthy[i].on = tv[i + 6]; lines.push(countOn(truthy, 5));
const nd = fresh(); nd[1].v = "4"; nd[2].w = null; lines.push(negDiv(nd, 6), compound(nd, 6));
console.log(lines.join(" "));
"""
    check(js, golden, "object_element_loops", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_inlined_callees_follow_redefinition_and_prototype_changes(js, golden, tier):
    """CATCHES: guarded inlining that keeps executing a spliced callee after the global function, prototype method or polymorphic receiver set changes, or that loses exceptions and global reads performed inside the inlined body."""
    code = r"""
"use strict";
function sq(x) { return x * x; }
function addOne(x) { return x + 1; }
function cube(x) { return sq(x) * x; }
function viaGlobal(n) { let s = 0; for (let i = 0; i < n; i++) s += sq(i) + addOne(i) + cube(i % 5); return s; }
class Vec { constructor(x, y) { this.x = x; this.y = y; } dot(o) { return this.x * o.x + this.y * o.y; } scale(k) { this.x = this.x * k; this.y = this.y * k; return this; } len2() { return this.dot(this); } }
function viaMethod(vs, n) { let s = 0; for (let i = 0; i < n; i++) { const v = vs[i % vs.length]; s += v.dot(vs[0]) + v.len2(); } return s; }
function mutating(vs, n) { for (let i = 0; i < n; i++) vs[i % vs.length].scale(1); return vs[0].x; }
function Counter() { this.c = 0; }
Counter.prototype.inc = function () { this.c = this.c + 1; return this.c; };
function viaProto(n) { const c = new Counter(); let s = 0; for (let i = 0; i < n; i++) s += c.inc(); return s; }
const shapes = [{ area() { return 1; } }, { area() { return 2; } }, { area() { return 3; } }];
function poly(n) { let s = 0; for (let i = 0; i < n; i++) s += shapes[i % 3].area(); return s; }
function thrower(x) { if (x === 77) throw new RangeError("x" + x); return x; }
function viaThrow(n) { let s = 0; try { for (let i = 0; i < n; i++) s += thrower(i); } catch (e) { return "caught " + e.message + " at " + s; } return s; }
let G = 10;
function readsGlobal(x) { return x + G; }
function viaGlobalRead(n) { let s = 0; for (let i = 0; i < n; i++) s += readsGlobal(i); return s; }
function argc(a, b) { return b === undefined ? a : a + b; }
function viaArgs(n) { let s = 0; for (let i = 0; i < n; i++) s += argc(i) + argc(i, 1) + argc(i, 1, 2); return s; }
function drive(rounds) {
  const vs = [new Vec(1, 2), new Vec(3, 4), new Vec(-1, 0.5)];
  const out = [];
  for (let r = 0; r < rounds; r++) out.push(viaGlobal(20), viaMethod(vs, 9), mutating(vs, 6), viaProto(5), poly(9), viaThrow(5), viaGlobalRead(4), viaArgs(3));
  return out.slice(-8).join(" ");
}
console.log("warm", drive(130));
// now invalidate every inlined guard
sq = function (x) { return -x; };
console.log("sq", drive(3));
Vec.prototype.dot = function (o) { return 1000; };
console.log("dot", drive(3));
Counter.prototype.inc = function () { this.c = this.c + 10; return this.c; };
console.log("inc", drive(3));
shapes.push({ area: () => 100 });
console.log("poly", drive(3));
console.log("throw", viaThrow(100));
G = "g";
console.log("global", drive(2));
addOne = Math.abs;
console.log("native", drive(2));
"""
    check(js, golden, "inlined_callees", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_inline_admission_edge_cases_and_caller_reflection(js, golden, tier):
    """CATCHES: inline splicing applied to callees it cannot model (9 arguments, defaults, rest/destructured parameters, var hoisting, nested function declarations, arguments, shadowed free names, recursion) or that loses the inlined frame so function.caller reflection reports the wrong caller."""
    code = r"""
function many(a, b, c, d, e, f, g, h, i) { return a + b + c + d + e + f + g + h + i; }
function nine(n) { let s = 0; for (let k = 0; k < n; k++) s += many(k, 1, 2, 3, 4, 5, 6, 7, 8) + many(k, 1, 2, 3, 4, 5, 6, 7); return s; }
var G = 5;
function readG(x) { return x * G; }
function shadowG(n) { let G = 1000; let s = 0; for (let k = 0; k < n; k++) s += readG(k) + G; return s; }
function withDefault(x, y = 2) { return x * y; }
function withRest(x, ...r) { return x + r.length; }
function withPattern({ v }) { return v; }
function withVars(x) { var t = x * 2; var u; if (x > 3) { u = t; } return t + (u === undefined ? -1 : u); }
function withInner(x) { function h() { return 3; } return x + h(); }
function withArgs() { return arguments.length; }
function usesThis() { return this === undefined ? "u" : typeof this; }
function shapes(n) { let s = 0; for (let k = 0; k < n; k++) s += withDefault(k) + withDefault(k, 3) + withRest(k, 1, 2) + withPattern({ v: k }) + withVars(k % 6) + withInner(k) + withArgs(1, 2); return s; }
function plainThis(n) { let r = ""; for (let k = 0; k < n; k++) r = usesThis() + usesThis.call(k); return r; }
function target() { return target.caller === invoke ? "invoke" : String(target.caller && target.caller.name); }
function invoke() { return target(); }
function reflect(n) { let c = 0, last; for (let k = 0; k < n; k++) { last = invoke(); if (last === "invoke") c++; } return c + "/" + n + ":" + last; }
function level3(x) { return x + 1; } function level2(x) { return level3(x) * 2; } function level1(x) { return level2(x) - 1; } function level0(x) { return level1(x) + level1(-x); }
function deep(n) { let s = 0; for (let k = 0; k < n; k++) s += level0(k); return s; }
function rec(x) { return x <= 0 ? 0 : x + rec(x - 2); }
function recursive(n) { let s = 0; for (let k = 0; k < n; k++) s += rec(k % 9); return s; }
function getterUse(o) { return o.val; }
function viaGetter(n) { const objs = [{ val: 1 }, { get val() { return 2; } }]; let s = 0; for (let k = 0; k < n; k++) s += getterUse(objs[k & 1]); return s; }
function drive(r) { const out = []; for (let k = 0; k < r; k++) out.push(nine(4), shadowG(3), shapes(4), plainThis(3), reflect(3), deep(5), recursive(9), viaGetter(4)); return out.slice(-8).join(" "); }
console.log(drive(130));
G = 7; withVars = function (x) { return 0; }; level3 = function (x) { return 100; }; usesThis = function () { return "replaced"; };
console.log(drive(2));
console.log(reflect(200));
const callee = { one(a) { return a + 1; } };
function nineArgs(n) { let s = 0; for (let k = 0; k < n; k++) s += callee.one(k, 1, 2, 3, 4, 5, 6, 7, 8) + first(k, 1, 2, 3, 4, 5, 6, 7, 8); return s; }
function first(a) { return a * 2; }
function driveNine(r) { let t = 0; for (let k = 0; k < r; k++) t += nineArgs(3); return t; }
console.log(driveNine(130));
callee.one = (a) => -a; first = (a) => 0;
console.log(driveNine(2));
"""
    check(js, golden, "inline_admission", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_numeric_field_expressions_on_nested_objects(js, golden, tier):
    """CATCHES: numeric field expressions such as this.pos.x + this.vel.x * dt that keep using borrowed nested objects after a field becomes a string, getter or is deleted, ignore prototype-held constants changing, or write into frozen objects."""
    code = r"""
"use strict";
class Body {
  constructor(i) { this.pos = { x: i, y: -i }; this.vel = { x: 1, y: 0.5 }; this.mass = 2; }
  step(dt) { this.pos.x = this.pos.x + this.vel.x * dt; this.pos.y = this.pos.y - this.vel.y * dt; return this.pos.x * this.mass + this.pos.y / this.mass; }
  energy() { return 0.5 * this.mass * (this.vel.x * this.vel.x + this.vel.y * this.vel.y); }
  kick(o) { o.vel.x = o.vel.x * this.drag; return -o.vel.x; }
}
Body.prototype.drag = 0.5;
Body.prototype.g = 9.81;
class Heavy extends Body {}
Heavy.prototype.mass2 = 10;
function fall(b, t) { return b.g * t * t / 2 + b.pos.y; }
function grand(h) { return h.g * h.mass2 - h.drag; }
function simulate(bodies, steps) { let acc = 0; for (let s = 0; s < steps; s++) { for (let k = 0; k < bodies.length; k++) { const b = bodies[k]; acc += b.step(0.25) + b.energy() + fall(b, 1) + b.kick(bodies[0]); } } return acc; }
function drive() { const bodies = [new Body(1), new Body(2), new Heavy(3)]; let t = 0; for (let r = 0; r < 60; r++) t += simulate(bodies, 3); const h = new Heavy(1); let g = 0; for (let r = 0; r < 120; r++) g += grand(h); return t.toFixed(6) + " " + g.toFixed(4); }
console.log(drive());
// guard failures: field becomes a string, getter, deleted, prototype constant changes, receiver of other shape
const b1 = new Body(5);
b1.pos.x = "5"; console.log(b1.step(1), b1.energy().toFixed(3));
const b2 = new Body(5); Object.defineProperty(b2.vel, "x", { get() { return 100; } }); console.log(b2.step(1), b2.energy().toFixed(3));
const b3 = new Body(5); delete b3.vel.y; console.log(b3.step(1), b3.energy());
Body.prototype.g = 1; console.log(fall(new Body(1), 2)); Body.prototype.drag = "x"; console.log(new Body(1).kick(new Body(2)), grand(new Heavy(0)));
Heavy.prototype.mass2 = undefined; console.log(grand(new Heavy(0)));
const odd = { pos: { x: 1, y: 2, z: 3 }, vel: { x: 1, y: 1 }, mass: 4, g: 2 }; console.log(Body.prototype.step.call(odd, 2), fall(odd, 3));
const frozen = new Body(1); Object.freeze(frozen.pos); try { frozen.step(1); } catch (e) { console.log(e.constructor.name); }
console.log(new Body(1e308).step(1e308), new Body(-0).energy(), new Body(NaN).step(0));
"""
    check(js, golden, "field_expressions", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_numeric_property_chains_with_prototype_fields(js, golden, tier):
    """CATCHES: numeric property chains (bitwise masks, flag updates, ordered compares) that guard only the receiver shape and miss changes to prototype-held fields at depth one or two, non-number field values, accessors, or frozen receivers."""
    code = r"""
"use strict";
var KIND = 2;
function one() { return 1; }
function P(x, y) { this.x = x; this.y = y; this.flags = 0; }
P.prototype.k = 3;
P.prototype.mix = function (o) { one(); return (this.x ^ o.y) & 0xFF; };
P.prototype.protoBits = function () { one(); return (this.x << 2) | this.k; };
P.prototype.mark = function () { one(); this.flags = this.flags | 4; return this.flags; };
P.prototype.unmark = function () { one(); this.flags = this.flags & ~4; return this.flags; };
P.prototype.isKind = function () { one(); if (this.y === KIND) return 1; return 0; };
P.prototype.less = function (o) { one(); if (this.x * 2 < o.y + this.k) return "lt"; return "ge"; };
function Q(x, y) { P.call(this, x, y); }
Q.prototype = Object.create(P.prototype);
Q.prototype.constructor = Q;
function depth2(q) { one(); return (q.k << 4) ^ q.x; }
function depth1(p) { one(); return (p.k * 8) >> 1; }
function storeLocal(o, v) { one(); o.flags = (o.flags + v) | 0; return o.flags; }
function cmpLocal(a, b) { let n = one() - 1; if (a.x >= b.x) n += 1; if (a.y <= b.k) n += 10; if (a.flags > b.flags) n += 100; return n; }
function drive() { const a = new P(5, 2), b = new P(3, 9), q = new Q(7, 2); let s = 0, t = "";
  for (let i = 0; i < 200; i++) { s += a.mix(b) + a.protoBits() + a.mark() + a.unmark() + a.isKind() + b.isKind() + depth2(q) + depth1(b) + storeLocal(b, i) + cmpLocal(a, b); t = a.less(b) + b.less(a); }
  return s + " " + t; }
console.log(drive());
const a = new P(5, 2), b = new P(3, 9);
a.x = 2.5; console.log(a.mix(b), a.protoBits(), a.less(b), storeLocal(a, 0.5));
a.x = "7"; console.log(a.mix(b), a.protoBits(), a.less(b), cmpLocal(a, b));
P.prototype.k = 1.5; console.log(a.protoBits(), depth2(new Q(1, 1)), depth1(new P(0, 0)), new Q(0, 0).less(b));
Q.prototype.k = 100; console.log(depth2(new Q(1, 1)), new Q(1, 1).protoBits());
KIND = "2"; console.log(a.isKind(), new P(0, "2").isKind());
const g = new P(1, 2); Object.defineProperty(g, "flags", { get() { return 8; }, set(v) {} }); console.log(g.mark(), g.unmark(), storeLocal(g, 1));
const z = new P(NaN, -0); console.log(z.mix(b), z.less(b), z.protoBits(), cmpLocal(z, b), storeLocal(z, NaN));
const fr = Object.freeze(new P(1, 1)); try { fr.mark(); } catch (e) { console.log(e.constructor.name); }
"""
    check(js, golden, "property_chains", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_counter_fill_region_with_global_limit(js, golden, tier):
    """CATCHES: the specialised counter/array fill region (this.counter++ with a reset threshold, stored into owner.arr[i] up to a global limit) that keeps running natively when the global limit no longer matches the array length, is zero, or exceeds the packed-array bound."""
    code = r"""
var LIMIT = 12;
function noop() { return 0; }
function Gen() { this.counter = 0; }
Gen.prototype.fill = function (owner) {
  noop();
  for (var i = 0; i < LIMIT; i++) {
    this.counter++;
    if (this.counter > 3) this.counter = 0;
    owner.arr[i] = this.counter;
  }
  return owner.arr.join("");
};
function drive(n) { const g = new Gen(); const owner = { arr: new Array(LIMIT).fill(0) }; let r; for (let k = 0; k < n; k++) r = g.fill(owner); return r + ":" + g.counter; }
console.log(drive(150));
LIMIT = 4; console.log(drive(20));
LIMIT = 0; console.log(drive(5));
LIMIT = 20; console.log(drive(5));
"""
    check(js, golden, "counter_fill_region", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_class_create_initializers_forwarded_through_apply(js, golden, tier):
    """CATCHES: the forwarded `this.initialize.apply(this, arguments)` constructor fast path (Prototype-style Class.create) that applies stale defaults, ignores a replaced initializer or prototype, skips accessors on the new instance, or hides errors from a non-callable initializer."""
    code = r"""
var Class = { create: function () { return function () { this.initialize.apply(this, arguments); }; } };
var Color = Class.create();
Color.prototype = {
  initialize: function (r, g, b) { if (!r) r = 0.0; if (!g) g = 0.0; if (!b) b = 0.0; this.red = r; this.green = g; this.blue = b; },
  add: function (c) { return new Color(this.red + c.red, this.green + c.green, this.blue + c.blue); },
  toString: function () { return "rgb(" + [this.red, this.green, this.blue].map(v => Math.round(v * 255)).join(",") + ")"; }
};
var Vector = Class.create();
Vector.prototype = {
  initialize: function (x, y, z) { this.x = x ? x : 0; this.y = y ? y : 0; this.z = z ? z : 1; },
  dot: function (w) { return this.x * w.x + this.y * w.y + this.z * w.z; }
};
var Plain = Class.create();
Plain.prototype = { initialize: function (a, b) { this.a = a; this.b = b; } };
var Odd = Class.create();
Odd.prototype = { initialize: function (a) { this.list = [a]; this.count = arguments.length; } };
function drive(n) { let acc = new Color(), d = 0, s = 0, c = 0;
  for (let i = 0; i < n; i++) { acc = acc.add(new Color(0.001, i % 2 ? 0.002 : 0, undefined)); d += new Vector(i, null, undefined).dot(new Vector(1, 2, 3)); const p = new Plain(i, "b"); s += p.a + p.b.length; c += new Odd(i, i).count; }
  return acc + " " + d + " " + s + " " + c; }
console.log(drive(150));
// guard misses: initialize replaced, prototype swapped, extra args, getter/setter on target, frozen this
Color.prototype.initialize = function (r) { this.red = this.green = this.blue = r || 0.5; };
console.log(String(new Color(0.1, 0.2, 0.3)), drive(3));
Vector.prototype = { initialize: function (x) { this.x = -x; this.y = 0; this.z = 0; }, dot: function (w) { return this.x * w.x; } };
console.log(drive(3));
Object.defineProperty(Plain.prototype, "a", { set(v) { this._a = v * 100; }, get() { return this._a; }, configurable: true });
console.log(new Plain(2, "x").a, drive(2));
try { new Plain(1, null).b.length; } catch (e) { console.log(e.constructor.name); }
Plain.prototype.initialize = 5; try { new Plain(1, 2); } catch (e) { console.log(e.constructor.name); }
"""
    check(js, golden, "class_create_initializers", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_recompiled_functions_with_deep_prototype_reads(js, golden, tier):
    """CATCHES: recompiled hot functions whose seeded caches read inherited fields two or three prototypes up, Array/String prototype fields, globals and captured variables, and then keep serving stale values after prototypes are reshaped, replaced by getters, or re-parented."""
    code = r"""
"use strict";
function tick() { return 0; }
class A {} A.prototype.tag = "a"; A.prototype.n = 1;
class B extends A {} class C extends B {} class D extends C {}
const objs = { a: new A(), b: new B(), c: new C(), d: new D() };
function depthReads(o) { tick(); return o.tag + o.n; }
function arrProps(a) { tick(); return a.length + a.tag2; }
Array.prototype.tag2 = 7;
function strProps(s) { tick(); return s.length + s.big; }
String.prototype.big = 100;
var gCounter = 0, gName = "g";
function globals(k) { tick(); gCounter = gCounter + k; gName = gName + k; return gCounter; }
function captured(n) { let c = 0; const bump = () => { tick(); c = c + n; return c; }; bump(); bump(); return bump(); }
function makeFields(i) { tick(); const o = {}; o.x = i; o.y = i * 2; o.z = "z"; return o.x + o.y; }
function Ctor(i) { tick(); this.a = i; this.b = true; this.c = null; this.d = undefined; this.e = "s"; this.f = [i]; }
function ctorUse(i) { tick(); const c = new Ctor(i); return c.a + (c.b ? 1 : 0) + (c.c === null ? 1 : 0) + c.f.length; }
function elems(a, i) { tick(); a[i & 3] = a[(i + 1) & 3] + 1; return a[i & 3]; }
function updates(o) { tick(); o.count++; o.count += 2; --o.count; return o.count; }
function inst(x) { tick(); return (x instanceof A ? 1 : 0) + (x instanceof D ? 10 : 0) + (x instanceof Array ? 100 : 0); }
function eqs(a, b) { tick(); if (a === b) return 1; if (a == b) return 2; return 3; }
function nots(x) { tick(); return !x ? "f" : "t"; }
function methods(o) { tick(); return o.toString().length + o.hasOwnProperty("tag"); }
function drive(rounds) {
  const arr = [1, 2, 3, 4]; const counter = { count: 0 }; let acc = 0, s = "";
  for (let r = 0; r < rounds; r++) {
    s = depthReads(objs.a) + depthReads(objs.b) + depthReads(objs.c) + depthReads(objs.d);
    acc += arrProps(arr) + strProps("hey") + globals(1) + captured(r) + makeFields(r) + ctorUse(r) + elems(arr, r) + updates(counter) + inst(objs.d) + inst(arr) + eqs(r, r) + eqs(r, String(r)) + eqs(r, {}) + methods(objs.c);
    s += nots(r & 1) + nots(r & 1 ? "" : "x");
  }
  return acc + " " + s + " " + arr.join() + " " + counter.count;
}
console.log(drive(130));
// perturb every specialised path
A.prototype.tag = "A2"; C.prototype.tag = "c-own"; Object.defineProperty(B.prototype, "n", { get() { return 50; } });
Array.prototype.tag2 = "t"; String.prototype.big = "B";
Object.defineProperty(globalThis, "gCounterAcc", { value: 1 });
console.log(drive(3));
delete C.prototype.tag; Object.setPrototypeOf(D.prototype, A.prototype);
console.log(drive(2), depthReads({ tag: "own", n: 0 }), arrProps({ length: 9 }), strProps(new String("abcd")), inst(Object.create(D.prototype)));
console.log(eqs(null, undefined), eqs(NaN, NaN), eqs(0, -0), eqs("1", 1), eqs(1n, 1), nots(0n), nots(""), nots(NaN), nots([]), methods({ tag: 1 }));
"""
    check(js, golden, "recompiled_deep_reads", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_guarded_numeric_field_writes_on_branches(js, golden, tier):
    """CATCHES: guarded branch regions that end in one numeric field write per path (clamp/sign/threshold stores, nested diamonds, global limits) and commit the wrong value or keep the fast path for NaN, -0, strings, accessors, frozen targets or a global that stops being a number."""
    code = r"""
"use strict";
var LIMIT = 50;
function clamp(o, v) { if (v > o.max) o.cur = o.max; else o.cur = v; return o.cur; }
function sign(o, v) { if (v < 0) { o.s = -1; } else if (v > 0) { o.s = 1; } else { o.s = 0; } return o.s; }
function Box(lo) { this.lo = lo; this.val = 0; }
Box.prototype.put = function (v) { if (v >= this.lo) this.val = v * 2; else this.val = this.lo - v; return this.val; };
function eqBranch(o, a, b) { if (a === b) o.flag = a + 1; else o.flag = b - 1; return o.flag; }
function neBranch(o, a, b) { if (a != b) o.flag = 7; else o.flag = 8; return o.flag; }
function leBranch(o, a) { if (a <= 3) o.v = a * a; else o.v = -a; return o.v; }
function viaGlobal(o, v) { if (v < LIMIT) o.w = v + 0.5; else o.w = LIMIT; return o.w; }
function deep(o, a, b) { if (a < b) { if (a < 0) o.r = 1; else o.r = 2; } else { if (b < 0) o.r = 3; else o.r = 4; } return o.r; }
function drive(n) { const o = { max: 10, cur: 0, s: 0, flag: 0, v: 0, w: 0, r: 0 }; const b = new Box(5); let t = 0;
  for (let i = 0; i < n; i++) { const x = (i % 23) - 11; t += clamp(o, x) + sign(o, x) + b.put(x) + eqBranch(o, x, 3) + neBranch(o, x, 4) + leBranch(o, x) + viaGlobal(o, x * 10) + deep(o, x, 2); }
  return t; }
console.log(drive(300));
// guard misses: NaN, strings, objects with different shapes, getters/setters, frozen targets, global change
const o2 = { max: "7", cur: 0, s: 0, flag: 0, v: 0, w: 0, r: 0 };
console.log(clamp(o2, 9), clamp(o2, "8"), sign(o2, NaN), sign(o2, -0), eqBranch(o2, NaN, NaN), neBranch(o2, NaN, NaN), leBranch(o2, "2"), deep(o2, NaN, 1));
const frozen = Object.freeze({ max: 1, cur: 0 }); try { clamp(frozen, 5); } catch (e) { console.log(e.constructor.name); }
const acc = { max: 3, get cur() { return 99; }, set cur(v) { this.seen = v; } }; console.log(clamp(acc, 1), acc.seen);
LIMIT = "z"; console.log(viaGlobal({ w: 0 }, 5), viaGlobal({ w: 0 }, 500));
const b2 = new Box(1); b2.lo = undefined; console.log(b2.put(3), new Box(2).put(1n === 1n ? 2 : 0));
"""
    check(js, golden, "guarded_field_writes", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_object_loops_over_this_fields_and_globals(js, golden, tier):
    """CATCHES: object loops reached through `this.items[i]` that read a stale global multiplier, store comparison results incorrectly, miscount post-increment indices, or keep running after an element turns into a string, a different shape or null."""
    code = r"""
"use strict";
var SCALE = 3;
function Bag(n) { this.items = []; for (let i = 0; i < n; i++) this.items.push({ v: i, w: 2, ok: false }); this.total = 0; }
Bag.prototype.sum = function (n) { let s = 0; for (let i = 0; i < n; i++) { s = s + this.items[i].v * SCALE; } return s; };
Bag.prototype.flags = function (n) { let c = 0; for (let i = 0; i < n; i++) { const it = this.items[i]; const big = it.v > 4; it.ok = big; if (big) { c = c + 1; } } return c; };
Bag.prototype.neg = function (n) { let s = 0; for (let i = 0; i < n; i++) { const x = this.items[i].v; s = s - -x; } return s; };
Bag.prototype.acc = function (n) { const items = this.items; for (let i = 0; i < n; i++) { items[i].w += 1; } return items[0].w; };
Bag.prototype.post = function (n) { let j = 0, s = 0; for (let i = 0; i < n; i++) { s = s + this.items[j++].v; } return s + j; };
function drive() { const b = new Bag(10); let t = 0; for (let k = 0; k < 150; k++) t += b.sum(10) + b.flags(10) + b.neg(10) + b.acc(10) + b.post(10); return t; }
console.log(drive());
const b = new Bag(6); b.items[2].v = "s"; b.items[3] = { v: 1.5 }; SCALE = 0.5;
console.log(b.sum(6), b.flags(6), b.neg(6), b.post(6));
try { b.acc(6); } catch (e) { console.log(e.constructor.name); }
b.items[4] = null; try { b.sum(6); } catch (e) { console.log(e.constructor.name); }
SCALE = { valueOf() { return 2; } }; console.log(new Bag(3).sum(3));
"""
    check(js, golden, "this_field_loops", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_constructor_frames_extra_args_throws_and_deep_recursion(js, golden, tier):
    """CATCHES: machine-code constructor frames that leak or double-drop surplus arguments, lose the exception when a constructor throws (also mid-expression), release captured activations too early, mishandle BigInt fields, or corrupt the frame pool when constructors recurse deeper than its 64 cached buffers."""
    code = r"""
"use strict";
function Pt(x, y) { this.x = x; this.y = y; }
function Temp(v) { const scratch = { big: [v, v + 1], s: "t" + v }; this.v = scratch.big[1]; }
function Thrower(v) { this.v = v; if (v % 5 === 4) throw new RangeError("ctor " + v); }
function MidThrow(v) { this.v = [v, (() => { if (v === 3) throw new TypeError("mid"); return v; })()].length; }
function Resets(n, o) { const before = typeof o; for (var k in o) { this.last = k; } this.before = before; }
function Captures(v) { const self = this; this.v = v; this.get = () => self.v * 2; }
function ExtraArgs(a) { const t = [a][0] * 2; this.t = t; }
function ParamReset(k, o) { const b = String(k); for (var k in o) { this.last = k; } this.b = b; }
function Tree(d) { this.d = d; this.kid = d > 0 ? new Tree(d - 1) : null; }
function Big(v) { this.v = v; this.b = 10n ** BigInt(v % 5); }
function drive(n) { let t = 0, errs = 0, tree = 0;
  for (let i = 0; i < n; i++) {
    const p = new Pt(i, i * 2, "extra", { more: true }); t += p.x + p.y;
    t += new Temp(i).v;
    try { t += new Thrower(i).v; } catch (e) { errs++; }
    try { t += new MidThrow(i).v; } catch (e) { errs += 100; }
    const r = new Resets(i, { a: 1, b: 2 }); t += r.last.length + r.before.length;
    t += new Captures(i).get();
    t += Number(new Big(i).b % 7n);
    t += new ExtraArgs(i, { x: 1 }, [2], "s").t;
    const pr = new ParamReset("p" + i, { z: 1 }); t += pr.last.length + pr.b.length;
  }
  let node = new Tree(70); while (node) { tree++; node = node.kid; }
  return t + ":" + errs + ":" + tree; }
console.log(drive(40));
console.log(drive(3));
"""
    check(js, golden, "constructor_frames", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_linked_list_tail_scans(js, golden, tier):
    """CATCHES: the specialised `while ((peek = next.link) != null) next = peek` scan that treats undefined like null under !==, keeps following a link after it becomes a getter, a primitive or an inherited property, or returns the wrong tail node."""
    code = r"""
"use strict";
function one() { return 1; }
function Node(v, next) { this.v = v; this.link = next; }
function tailLoose(head) { one(); let peek, next = head; while ((peek = next.link) != null) next = peek; return next.v; }
function tailStrict(head) { one(); let peek, next = head; while ((peek = next.link) !== null) next = peek; return next.v; }
function append(head, node) { one(); node.link = null; if (head == null) return node; let peek, next = head; while ((peek = next.link) != null) next = peek; next.link = node; return head; }
function list(n) { let h = null; for (let i = n; i > 0; i--) h = new Node(i, h); return h; }
function drive(n) { let t = 0; const a = list(6), b = list(3); for (let i = 0; i < n; i++) { t += tailLoose(a) + tailStrict(b); let q = new Node(0, null); for (let j = 1; j < 4; j++) q = append(q, new Node(j, null)); t += tailLoose(q); } return t; }
console.log(drive(150));
// shape and type changes on the link field
const odd = list(3); odd.link.link.link = undefined; console.log(tailLoose(odd)); try { console.log(tailStrict(odd)); } catch (e) { console.log(e.constructor.name); }
const mixed = list(4); mixed.link = { v: "plain", link: { v: "end", link: null } }; console.log(tailLoose(mixed), tailStrict(mixed));
const getterNode = list(2); Object.defineProperty(getterNode.link, "link", { get() { return null; } }); console.log(tailLoose(getterNode), tailStrict(getterNode));
const zero = list(2); zero.link.link = 0; for (const f of [tailStrict, tailLoose]) { try { console.log(f(zero)); } catch (e) { console.log(e.constructor.name); } }
const protoLink = Object.create({ link: null }); protoLink.v = "proto"; console.log(tailLoose(protoLink), tailStrict(protoLink));
"""
    check(js, golden, "linked_list_scans", code, tier)
