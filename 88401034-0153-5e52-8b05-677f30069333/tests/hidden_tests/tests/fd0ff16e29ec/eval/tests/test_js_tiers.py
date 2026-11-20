"""Execution-tier agreement tests: the tree-walking interpreter, the bytecode VM and the native JIT.

Every program here is engine-heavy (hot loops, inline-cache churn, deopt-style guard failures)
and runs under all three tiers against ONE shared golden: the documented contract is that every
tier produces identical output.
"""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


def check_prog(run, tier, prog, name):
    # Each program takes well under a second on the reference build; the generous timeout only
    # matters for slow instrumented builds of the same binary.
    r = run([*tier, "-e", prog], timeout=90)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


PROG_NUMERIC = r"""
function intSum(n) { let s = 0; for (let i = 0; i < n; i++) { s += i; } return s; }
function mixedSum(n) {
  let s = 0;
  for (let i = 0; i < n; i++) { s += i * 0.5; if (i % 7 === 3) s -= 1.25; }
  return s;
}
function overflow(n) { let s = 2147483000; for (let i = 0; i < n; i++) s += 1000; return s; }
function negOverflow(n) { let s = -2147483000; for (let i = 0; i < n; i++) s -= 999; return s; }
function mulOverflow(n) { let p = 1; for (let i = 1; i <= n; i++) p = p * i; return p; }
function bits(n) {
  let h = 0x811c9dc5 | 0, x = 1, y = 0, z = 0, w = 0;
  for (let i = 0; i < n; i++) {
    h = Math.imul(h ^ (i & 0xff), 16777619);
    x = (x << 3) ^ (x >>> 5) ^ i;
    y = (y + (h >> 7)) | 0;
    z = (z ^ ~i) & 0x7fffffff;
    w = (w + (i << 28)) >>> 0;
  }
  return [h >>> 0, x | 0, y, z, x >>> 0, w].join(",");
}
function toInt32(n) {
  const vals = [1.9, -1.9, 2147483648, 4294967296 + 5, -2147483649, NaN, Infinity, -0, 1e20, "12", true, null, undefined, "x"];
  const out = [];
  for (let r = 0; r < n; r++) {
    for (let i = 0; i < vals.length; i++) {
      const v = vals[i];
      if (r === n - 1) out.push((v | 0) + ":" + (v >>> 0) + ":" + (v >> 1) + ":" + (~v));
    }
  }
  return out.join(" ");
}
function divmod(n) {
  let a = 0, b = 0, c = 0, d = 0;
  for (let i = -n; i < n; i++) { a += i % 7; b += (i / 3) | 0; c += Math.floor(i / 4); d += Math.round(i / 6); }
  return [a, b, c, d].join(",");
}
function cmpTable(n) {
  const vals = [0, -0, 1, -1, 0.5, NaN, Infinity, -Infinity, "1", "a", null, undefined, true];
  const t = [0, 0, 0, 0, 0, 0, 0, 0];
  for (let r = 0; r < n; r++) {
    for (let i = 0; i < vals.length; i++) {
      for (let j = 0; j < vals.length; j++) {
        const a = vals[i], b = vals[j];
        if (a < b) t[0]++;
        if (a <= b) t[1]++;
        if (a > b) t[2]++;
        if (a >= b) t[3]++;
        if (a == b) t[4]++;
        if (a != b) t[5]++;
        if (a === b) t[6]++;
        if (a !== b) t[7]++;
      }
    }
  }
  return t.join(",");
}
function loops(n) {
  let i = 0, s = 0, guard = 0;
  do { s += i; i += 3; } while (i < n);
  outer: for (let a = 0; a < 50; a++) {
    for (let b = 0; b < 50; b++) {
      if (b > a) continue outer;
      if (a * b > 900) break outer;
      if ((a + b) % 5 === 0) continue;
      guard += a ^ b;
    }
  }
  let k = n; while (true) { k = k >> 1; if (k === 0) break; s++; }
  return [s, guard, i].join(",");
}
function fib(n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
function collatz(limit) {
  let best = 0, at = 0;
  for (let i = 1; i < limit; i++) {
    let x = i, steps = 0;
    while (x !== 1) { x = (x & 1) ? 3 * x + 1 : x / 2; steps++; }
    if (steps > best) { best = steps; at = i; }
  }
  return at + ":" + best;
}
function floats(n) {
  let s = 0, m = -Infinity, lo = Infinity, sq = 0;
  for (let i = 1; i <= n; i++) {
    const v = ((i * 7919) % 20011 - 10005) / 100.03;
    s += Math.abs(v);
    m = Math.max(m, v);
    lo = Math.min(lo, v);
    sq += Math.sqrt(i);
  }
  return [s.toFixed(6), m.toFixed(9), lo.toFixed(9), sq.toFixed(4), (0.1 + 0.2), 1 / 3, -0 === 0, Object.is(-0 * 1, -0)].join(" ");
}
function negZero(n) {
  let r = 1, z = -0, q = 0, m = 0, u = 0;
  for (let i = 1; i < n; i++) { r = 1 / (z * i); q = 0 / -i; m = -i % i; u = -(i - i); }
  return [r, Object.is(q, -0), Object.is(m, -0), Object.is(u, -0), Object.is(Math.round(-0.4), -0), Math.sign(-0) === 0, (-0).toString()].join(",");
}
function incDec(n) {
  let a = 0, b = 10, c = 0.5, d = "5";
  for (let i = 0; i < n; i++) { a++; b--; ++c; --c; c++; }
  d++;
  let e = "x"; e++;
  return [a, b, c, d, typeof d, e].join(",");
}
function exponent(n) {
  let s = 0;
  for (let i = 0; i < n; i++) s += (i % 5) ** 2 + 2 ** (i % 11) - 2 ** -(i % 7) + (i % 3) ** 3;
  return s.toFixed(5);
}
function unary(n) {
  let s = 0;
  const xs = ["3", "-2", " 4 ", "", "0x1f", "1e2", "abc", null, false, [5], [], [1, 2], {}];
  for (let r = 0; r < n; r++) for (let i = 0; i < xs.length; i++) { const v = +xs[i]; if (v === v) s += v; }
  return s + " " + (-"3") + " " + (+true) + " " + (-[]) + " " + typeof (+"z");
}
console.log("intSum", intSum(30000));
console.log("mixedSum", mixedSum(20000));
console.log("overflow", overflow(5000), negOverflow(5000));
console.log("mulOverflow", mulOverflow(25), mulOverflow(171), mulOverflow(12));
console.log("bits", bits(12000));
console.log("toInt32", toInt32(20));
console.log("divmod", divmod(8000));
console.log("cmpTable", cmpTable(30));
console.log("loops", loops(12000));
console.log("fib", fib(22));
console.log("collatz", collatz(3000));
console.log("floats", floats(8000));
console.log("negZero", negZero(1000));
console.log("incDec", incDec(10001));
console.log("exponent", exponent(8000));
console.log("unary", unary(200));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_numeric_kernels(run, tier):
    """CATCHES: tiers that disagree on int32 overflow to double, ToInt32/ToUint32 bit operations, NaN/-0 comparisons, modulo/division rounding, fused compare-and-branch or labelled loop control flow in hot numeric loops."""
    check_prog(run, tier, PROG_NUMERIC, "numeric")


PROG_ARRAYS = r"""
function fillPacked(n) {
  const a = [];
  for (let i = 0; i < n; i++) a.push(i * 3);
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i];
  let popped = 0;
  for (let i = 0; i < 10; i++) popped += a.pop();
  return [a.length, s, a[a.length - 1], popped].join(",");
}
function holey(n) {
  const a = new Array(n);
  for (let i = 0; i < n; i += 3) a[i] = i;
  let cnt = 0, s = 0;
  for (let i = 0; i < n; i++) { if (a[i] === undefined) cnt++; else s += a[i]; }
  return [cnt, s, 1 in a, 3 in a, a.length, Object.keys(a).length].join(",");
}
function protoIndex() {
  const a = [1, , 3];
  const s = [];
  for (let k = 0; k < 40; k++) {
    let row = "";
    for (let i = 0; i < 3; i++) row += a[i] + ";";
    if (k === 20) Array.prototype[1] = "P";
    if (k === 0 || k === 39) s.push(row);
  }
  delete Array.prototype[1];
  s.push(String(a[1]));
  return s.join(" ");
}
function protoGetter() {
  const a = [10, , 30, , 50];
  let calls = 0, s = 0;
  for (let k = 0; k < 200; k++) {
    if (k === 100) Object.defineProperty(Array.prototype, "3", { get() { calls++; return 7; }, configurable: true });
    for (let i = 0; i < a.length; i++) { const v = a[i]; if (v !== undefined) s += v; }
  }
  delete Array.prototype[3];
  return s + "/" + calls;
}
function lengthChange() {
  const a = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  let s = 0, steps = 0;
  for (let i = 0; i < a.length; i++) {
    s += a[i];
    steps++;
    if (i === 5) a.length = 8;
    if (i === 2) a.push(100);
  }
  const b = [1, 2, 3];
  b[10] = 4;
  let holes = 0;
  for (let i = 0; i < b.length; i++) if (!(i in b)) holes++;
  return [s, a.length, steps, b.length, holes].join(",");
}
function oob(n) {
  const a = [1, 2, 3];
  let u = 0, neg = 0, frac = 0;
  for (let i = 0; i < n; i++) {
    if (a[i % 5] === undefined) u++;
    if (a[-1] === undefined) neg++;
    if (a[1.5] === undefined) frac++;
  }
  a[-1] = "neg";
  a["1.5"] = "frac";
  return [u, neg, frac, a.length, a[-1], a[1.5], Object.keys(a).join("|")].join(",");
}
function doubles(n) {
  const a = [];
  for (let i = 0; i < n; i++) a.push(0);
  for (let i = 0; i < n; i++) a[i] = i / 3;
  let s = 0;
  for (let i = 0; i < n; i++) s += a[i] * 1.5;
  a[5] = "str";
  let strs = 0;
  for (let i = 0; i < n; i++) if (typeof a[i] === "string") strs++;
  return s.toFixed(4) + "," + strs;
}
function objects(n) {
  const a = [];
  for (let i = 0; i < n; i++) a.push({ v: i, w: i & 1 });
  let s = 0, w = 0;
  for (let i = 0; i < a.length; i++) { s += a[i].v; w += a[i].w; a[i].v = -a[i].v; }
  return [s, w, a[7].v].join(",");
}
function matmul(n) {
  const A = [], B = [], C = [];
  for (let i = 0; i < n; i++) {
    A.push([]); B.push([]); C.push([]);
    for (let j = 0; j < n; j++) { A[i].push((i * j) % 7 - 3); B[i].push((i + 2 * j) % 5 - 2); C[i].push(0); }
  }
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      let s = 0;
      for (let k = 0; k < n; k++) s += A[i][k] * B[k][j];
      C[i][j] = s;
    }
  let tr = 0, all = 0;
  for (let i = 0; i < n; i++) { tr += C[i][i]; for (let j = 0; j < n; j++) all += C[i][j] * (j + 1); }
  return tr + "," + all;
}
function methods(n) {
  const a = [];
  for (let i = 0; i < 50; i++) a.push((i * 37) % 50);
  let acc = 0;
  for (let r = 0; r < n; r++) {
    acc += a.indexOf(r % 50) + (a.includes(r) ? 1 : 0) + a.lastIndexOf(7);
    const s = a.slice(r % 10, r % 10 + 5);
    acc += s.length + s[0];
  }
  const sorted = a.slice().sort((x, y) => y - x);
  const sp = a.slice(); const removed = sp.splice(3, 4, "a", "b");
  return [acc, sorted.slice(0, 5).join("|"), removed.join("|"), sp.length, a.slice().reverse()[0],
          a.map(x => x * 2).filter(x => x % 3 === 0).reduce((p, c) => p + c, 0),
          a.findIndex(x => x > 45), a.every(x => x >= 0), a.some(x => x > 49), a.join("").length].join(",");
}
function sparseAndConcat() {
  const a = [1, 2, 3];
  const b = a.concat([4, [5, 6]], 7);
  const c = Array.from({ length: 5 }, (_, i) => i * i);
  const d = [...a, ...c];
  const e = Array(3);
  e[1] = "m";
  return [b.length, b.join("-"), c.join("-"), d.join("-"), e.join("-"), [, 1].length, Array.of(9, 8).join("")].join(" ");
}
function copyWithinFill(n) {
  const a = [];
  for (let i = 0; i < n; i++) a[i] = i;
  a.copyWithin(0, n - 5);
  a.fill(-1, 10, 15);
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i];
  return s + "," + a.slice(0, 16).join(" ");
}
console.log("fillPacked", fillPacked(8000));
console.log("holey", holey(3000));
console.log("protoIndex", protoIndex());
console.log("protoGetter", protoGetter());
console.log("lengthChange", lengthChange());
console.log("oob", oob(5000));
console.log("doubles", doubles(5000));
console.log("objects", objects(5000));
console.log("matmul", matmul(24));
console.log("methods", methods(200));
console.log("sparseAndConcat", sparseAndConcat());
console.log("copyWithinFill", copyWithinFill(1000));
function makeArrays() {
  var list = [];
  list.push([1, 2, 3, 4]);
  var b = new Array(4); for (var i = 0; i < 4; i++) b[i] = i + 1; list.push(b);
  var c = [1, 2, 3, 4]; c.tag = "named"; list.push(c);
  var d = [1, 2, 3, 4]; delete d[3]; d[3] = 4; list.push(d);
  var e = [1, 2, 3, 4]; Object.defineProperty(e, 0, { value: 1, writable: true, enumerable: true, configurable: false }); list.push(e);
  var f = [1, 2, 3, 4]; f[50] = 9; f.length = 4; list.push(f);
  var g = []; for (var i = 4; i >= 1; i--) g.unshift(i); list.push(g);
  var h = Array.from({ length: 4 }, function (_, i) { return i + 1; }); list.push(h);
  var k = [1, 2, 3, 4, 5].slice(0, 4); list.push(k);
  var m = [1, 2].concat([3, 4]); list.push(m);
  var n = [4, 3, 2, 1].reverse(); list.push(n);
  var o = [1, 2, 3, 4], hidden = 4; Object.defineProperty(o, 3, { get: function () { return hidden; }, set: function (v) { hidden = v * 2; }, configurable: true }); list.push(o);
  return list;
}
function exercise(a, rounds) {
  var log = 0;
  for (var r = 0; r < rounds; r++) {
    a.push(r, r + 1, r + 2);
    log += a.pop() + a.pop();
    a[a.length] = r;
    log += a.length;
    var s = 0;
    for (var i = 0; i < a.length; i++) s += a[i] | 0;
    log += s;
    if (a.length > 40) { a.length = 4; }
  }
  var popped = [];
  for (var i = 0; i < 3; i++) popped.push(a.pop());
  a.unshift(0); a.shift(); a.splice(1, 1, 22, 23); a.reverse();
  return log + ":" + popped.join(".") + ":" + a.slice(0, 8).join(".") + ":" + a.length;
}
var arrays = makeArrays(), out = [];
for (var i = 0; i < arrays.length; i++) out.push(i + "=" + exercise(arrays[i], 60));
console.log(out.join("\n"));
var fz = Object.freeze([1, 2, 3]), errs = [];
try { fz.pop(); } catch (e) { errs.push(e.name); }
try { fz.push(1); } catch (e) { errs.push(e.name); }
try { "use strict"; fz.length = 0; } catch (e) { errs.push(e.name); }
var sealed = Object.seal([1, 2, 3]);
try { sealed.pop(); } catch (e) { errs.push("sealed " + e.name); }
sealed[0] = 10;
var nc = [1, 2, 3]; Object.defineProperty(nc, 2, { value: 3, configurable: false, writable: true });
try { nc.pop(); } catch (e) { errs.push("nc " + e.name); }
nc.length = 1;
console.log(errs.join(","), fz.length, sealed.join(""), nc.length, nc.join(""));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_array_element_paths(run, tier):
    """CATCHES: tiers that mishandle packed vs holey element fast paths: holes read through Array.prototype (data and late-installed getters), length truncation mid-loop, out-of-bounds/negative/fractional indices, and elements changing kind from int to double to string."""
    check_prog(run, tier, PROG_ARRAYS, "arrays")


PROG_TYPED = r"""
function roundTrip(Ctor, n) {
  const ta = new Ctor(n);
  for (let i = 0; i < n; i++) ta[i] = i * 37 - 500 + (i % 3) * 0.75;
  let s = 0;
  for (let i = 0; i < n; i++) s += ta[i];
  const head = [];
  for (let i = 0; i < 6; i++) head.push(ta[i]);
  return Ctor.name + " " + s + " [" + head.join(",") + "] last=" + ta[n - 1];
}
const ctors = [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, Float32Array, Float64Array];
for (const C of ctors) console.log(roundTrip(C, 2000));
function specials() {
  const out = [];
  const vals = [NaN, Infinity, -Infinity, -0, 255.5, 256, -1, 1e10, "7", "x", true, null, undefined, 2.5, 3.5];
  for (const C of ctors) {
    const ta = new C(vals.length);
    for (let r = 0; r < 30; r++) for (let i = 0; i < vals.length; i++) ta[i] = vals[i];
    const row = [];
    for (let i = 0; i < ta.length; i++) row.push(Object.is(ta[i], -0) ? "-0" : String(ta[i]));
    out.push(C.name + ":" + row.join(","));
  }
  return out.join("\n");
}
console.log(specials());
function oob() {
  const ta = new Int32Array(8);
  let w = 0;
  for (let i = 0; i < 100; i++) { ta[i] = i; if (ta[i] === i) w++; }
  ta[-1] = 5; ta[1.5] = 6; ta["2"] = 77;
  return [w, ta.length, ta[-1], ta[1.5], ta[2], Object.keys(ta).length, 9 in ta, "1.5" in ta].join(",");
}
console.log("oob", oob());
function bigints(n) {
  const a = new BigInt64Array(n), b = new BigUint64Array(n);
  for (let i = 0; i < n; i++) { a[i] = BigInt(i) * -3n; b[i] = BigInt(i) - 2n; }
  let s = 0n, t = 0n;
  for (let i = 0; i < n; i++) { s += a[i]; t += b[i] & 0xffffn; }
  return s + " " + t + " " + b[0] + " " + a[n - 1];
}
console.log("bigints", bigints(3000));
function views(n) {
  const buf = new ArrayBuffer(n * 4);
  const u8 = new Uint8Array(buf), u32 = new Uint32Array(buf), dv = new DataView(buf);
  for (let i = 0; i < n; i++) u32[i] = (i * 2654435761) >>> 0;
  let s = 0;
  for (let i = 0; i < u8.length; i++) s = (s + u8[i] * (i & 15)) | 0;
  let d = 0;
  for (let i = 0; i < n; i++) d = (d ^ dv.getUint32(i * 4, true) ^ dv.getUint16(i * 4, false)) >>> 0;
  const sub = u32.subarray(3, 7);
  sub[0] = 1;
  return [s, d, u32[3], sub.length, sub.byteOffset, u8.slice(0, 4).join("|")].join(",");
}
console.log("views", views(4000));
function hist(n) {
  const h = new Uint16Array(16);
  let x = 12345;
  for (let i = 0; i < n; i++) { x = (x * 1103515245 + 12345) & 0x7fffffff; h[x & 15]++; }
  return Array.from(h).join(",");
}
console.log("hist", hist(50000));
function methodsTA() {
  const f = new Float64Array([5, -1, 3.5, NaN, 0, -0, 2]);
  const sorted = Float64Array.from(f).sort();
  const i8 = Int8Array.from([1, 2, 3, 200, -200]);
  return [Array.from(sorted).map(v => Object.is(v, -0) ? "-0" : v).join(" "), i8.join(" "), i8.map(v => v * 2).join(" "),
          f.indexOf(NaN), f.includes(NaN), Array.from(new Uint8Array([1, 2, 3]).reverse()).join(""), i8.at(-1)].join(" | ");
}
console.log("methods", methodsTA());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_typed_array_loops(run, tier):
    """CATCHES: tiers whose typed-array store/load fast paths get element conversion wrong (Int8 wrap, Uint8Clamped round-half-even, Float32 rounding, NaN/-0/Infinity/strings), ignore out-of-bounds writes incorrectly, or mishandle BigInt64 arrays and shared ArrayBuffer views."""
    check_prog(run, tier, PROG_TYPED, "typed")


PROG_PROPS = r"""
function Point(x, y) { this.x = x; this.y = y; }
Point.prototype.norm1 = function () { return Math.abs(this.x) + Math.abs(this.y); };
function mono(n) {
  const p = new Point(1, 2);
  let s = 0;
  for (let i = 0; i < n; i++) { p.x = i; s += p.x + p.y + p.norm1(); }
  return s;
}
function shapes() {
  return [{ x: 1 }, { y: 2, x: 3 }, { z: 0, y: 1, x: 5 }, { w: 9, z: 0, y: 1, x: 7 }];
}
function poly(n) {
  const objs = shapes();
  let s = 0;
  for (let i = 0; i < n; i++) { const o = objs[i & 3]; s += o.x; o.x = o.x + 1; }
  return s + ":" + objs.map(o => o.x).join("|");
}
function mega(n) {
  const objs = [];
  for (let k = 0; k < 24; k++) {
    const o = {};
    for (let j = 0; j < k % 6; j++) o["p" + j] = j;
    o["q" + k] = k;
    o.val = k;
    objs.push(o);
  }
  let s = 0;
  for (let i = 0; i < n; i++) { const o = objs[i % 24]; s += o.val; o.val = (o.val * 3 + 1) % 101; }
  return s;
}
function protoChain(n) {
  const base = { deep: 5, f() { return this.deep * 2; } };
  const mid = Object.create(base);
  mid.mid = 1;
  const top = Object.create(mid);
  top.own = 2;
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += top.deep + top.mid + top.own + top.f();
    if (i === n >> 1) base.deep = 6;
    if (i === (n >> 1) + 10) mid.deep = 100;
  }
  return s;
}
function accessors(n) {
  let gets = 0, sets = 0;
  const proto = {
    get v() { gets++; return this._v * 2; },
    set v(x) { sets++; this._v = x; },
  };
  const o = Object.create(proto);
  o._v = 1;
  let s = 0;
  for (let i = 0; i < n; i++) { o.v = i; s += o.v; }
  class C { #p = 3; get p() { return this.#p; } set p(v) { this.#p = v + 1; } static get k() { return "K"; } }
  const c = new C();
  let t = 0;
  for (let i = 0; i < n; i++) { c.p = i; t += c.p; }
  return [s, gets, sets, t, C.k].join(",");
}
function transitions(n) {
  const out = [];
  let total = 0;
  for (let i = 0; i < n; i++) {
    const o = {};
    if (i & 1) o.a = i;
    if (i & 2) o.b = i;
    if (i & 4) o.c = i;
    o.d = i;
    if (i % 3 === 0) delete o.d;
    total += (o.a || 0) + (o.b || 0) + (o.c || 0) + (o.d === undefined ? 1 : o.d);
    if (i < 8) out.push(Object.keys(o).join(""));
  }
  return total + ":" + out.join(",");
}
function getterLater(n) {
  function K() { this.a = 1; }
  K.prototype.v = 10;
  const k = new K();
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += k.v;
    if (i === 600) Object.defineProperty(K.prototype, "v", { get() { return 1000; }, configurable: true });
    if (i === 700) k.v = 3;
    if (i === 800) delete k.v;
    if (i === 900) Object.defineProperty(K.prototype, "v", { value: -1, writable: true, configurable: true });
  }
  return s;
}
function protoSwap(n) {
  const A = { who() { return "A"; }, n: 1 };
  const B = { who() { return "B"; }, n: 2 };
  const o = Object.create(A);
  const seen = [];
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += o.n;
    if (i % 250 === 0) seen.push(o.who());
    if (i === 500) Object.setPrototypeOf(o, B);
    if (i === 750) B.who = function () { return "B2"; };
  }
  return s + ":" + seen.join("");
}
function sloppyFrozen(n) {
  const f = Object.freeze({ a: 1, b: { c: 2 } });
  const nw = {};
  Object.defineProperty(nw, "x", { value: 5, writable: false, enumerable: true });
  let s = 0;
  for (let i = 0; i < n; i++) { f.a = i; f.z = i; nw.x = i; f.b.c = i; s += f.a + nw.x; }
  return [s, f.a, f.z, nw.x, f.b.c, Object.isFrozen(f)].join(",");
}
function strictFrozen(n) {
  "use strict";
  const f = Object.freeze({ a: 1 });
  const ne = Object.preventExtensions({ q: 1 });
  const g = { get only() { return 4; } };
  const msgs = new Set();
  let errs = 0;
  for (let i = 0; i < n; i++) {
    try { f.a = i; } catch (e) { errs++; msgs.add(e.constructor.name + ": " + e.message); }
    try { ne.r = i; } catch (e) { errs++; msgs.add(e.constructor.name + ": " + e.message); }
    try { g.only = i; } catch (e) { errs++; msgs.add(e.constructor.name + ": " + e.message); }
    try { delete f.a; } catch (e) { errs++; msgs.add(e.constructor.name + ": " + e.message); }
    ne.q = i;
  }
  return errs + " q=" + ne.q + "\n  " + [...msgs].join("\n  ");
}
function ops(n) {
  const o = { a: 1, b: undefined };
  const arr = [1, 2];
  let c = 0;
  for (let i = 0; i < n; i++) {
    if ("a" in o) c++;
    if ("b" in o) c++;
    if ("c" in o) c += 100;
    if (o.hasOwnProperty("a")) c++;
    if (Object.hasOwn(o, "toString")) c += 1000;
    if (1 in arr) c++;
    if (o instanceof Object) c++;
    if (arr instanceof Array) c++;
  }
  return c;
}
function computed(n) {
  const o = {};
  for (let i = 0; i < n; i++) { const k = "k" + (i % 5); o[k] = (o[k] || 0) + i; }
  const sym = Symbol("s");
  o[sym] = 1;
  for (let i = 0; i < n; i++) o[sym] += 2;
  o[1] = "one"; o["01"] = "zero-one"; o[1e21] = "big";
  return JSON.stringify(o) + " " + o[sym] + " " + Object.keys(o).join("|");
}
function proxies(n) {
  let traps = 0;
  const p = new Proxy({ x: 1 }, {
    get(t, k, r) { traps++; return k === "x" ? t.x * 2 : Reflect.get(t, k, r); },
    set(t, k, v) { traps++; t[k] = v + 1; return true; },
    has(t, k) { traps++; return k !== "hidden"; },
  });
  let s = 0;
  for (let i = 0; i < n; i++) { p.x = i; s += p.x; if ("hidden" in p) s = -1; }
  return s + "," + traps;
}
function optional(n) {
  const list = [{ a: { b: 1 } }, { a: null }, null, { a: { b: { c: 3 } } }, undefined];
  let s = 0, u = 0;
  for (let i = 0; i < n; i++) {
    const o = list[i % 5];
    const v = o?.a?.b;
    if (v === undefined) u++; else s += typeof v === "number" ? v : v.c;
    s += o?.a?.b?.c ?? 0;
    const f = o?.fn?.();
    if (f !== undefined) s = -1;
  }
  return s + "," + u;
}
console.log("mono", mono(20000));
console.log("poly", poly(20000));
console.log("mega", mega(20000));
console.log("protoChain", protoChain(4000));
console.log("accessors", accessors(5000));
console.log("transitions", transitions(3000));
console.log("getterLater", getterLater(1000));
console.log("protoSwap", protoSwap(1000));
console.log("sloppyFrozen", sloppyFrozen(2000));
console.log("strictFrozen", strictFrozen(300));
console.log("ops", ops(5000));
console.log("computed", computed(2000));
console.log("proxies", proxies(2000));
console.log("optional", optional(5000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_property_inline_caches(run, tier):
    """CATCHES: stale property inline caches: monomorphic/polymorphic/megamorphic sites, prototype-chain hits after the holder or an intermediate object changes, accessors installed or removed after warm-up, setPrototypeOf, deletes, and silent (sloppy) versus throwing (strict) writes to frozen/non-writable/getter-only properties."""
    check_prog(run, tier, PROG_PROPS, "props")


PROG_CALLS = r"""
function add3(a, b, c) { return a + b + c; }
function add1(x) { return x + 1; }
function add2(x) { return x + 2; }
function add4(x) { return x + 4; }
function add8(x) { return x + 8; }
const userTargets = [add1, add2, add4, add8];
const nativeTargets = [Math.abs, Math.floor, Math.ceil, Math.trunc];
function direct(n) { let t = 0; for (let i = 0; i < n; i++) t += add3(i, 1, 2); return t; }
function polyUser(n) { let t = 0; for (let i = 0; i < n; i++) t += userTargets[i & 3](i & 7); return t; }
function polyNative(n) { let t = 0; for (let i = 0; i < n; i++) t += nativeTargets[i & 3](-(i & 7) - 0.25); return t; }
function bound(n) {
  const bu = add3.bind(null, 3, 4), bn = Math.max.bind(null, 3, 4);
  let t = 0;
  for (let i = 0; i < n; i++) t += bu(i & 7) + bn(i & 7);
  return t + " " + bu.name + " " + bu.length + " " + bn.name;
}
function callApply(n) {
  const args = [3, 4, 5];
  let t = 0;
  for (let i = 0; i < n; i++) {
    t += add3.call(null, 3, 4, i & 7);
    t += Math.abs.call(null, -(i & 7));
    args[2] = i & 7;
    t += add3.apply(null, args);
    t += Math.max.apply(Math, args);
  }
  return t;
}
function spread(n) {
  const args = [3, 4, 5];
  const holey = [1, , 3];
  let t = 0;
  for (let i = 0; i < n; i++) {
    args[0] = i & 3;
    t += add3(...args) + Math.min(...args) + add3(1, ...Array.from(holey.slice(0, 2), x => x || 0));
  }
  const it = { *[Symbol.iterator]() { yield 10; yield 20; yield 30; } };
  t += add3(...it);
  const str = Math.max(..."31415");
  Array.prototype[1] = 100;
  const viaProto = add3(...holey);
  delete Array.prototype[1];
  return [t, str, viaProto].join(",");
}
function rest(n) {
  function r(a, ...more) { return a + more.length + (more[0] || 0); }
  function argsLen() { return arguments.length + (arguments[1] || 0); }
  function sloppyAlias(a) { arguments[0] = 99; return a; }
  function strictNoAlias(a) { "use strict"; arguments[0] = 99; return a; }
  function defaults(a, b = a * 2, c = b + 1) { return a + b + c; }
  let t = 0;
  for (let i = 0; i < n; i++) {
    t += r(i) + r(i, 1) + r(i, 2, 3, 4) + argsLen() + argsLen(1, 2, 3) + defaults(i) + defaults(i, 1) + defaults(1, 2, 3);
  }
  return [t, sloppyAlias(1), strictNoAlias(1), (function () { return typeof arguments; })(), add3(1), add3(1, 2, 3, 4)].join(",");
}
function recursion() {
  function ack(m, n) { return m === 0 ? n + 1 : n === 0 ? ack(m - 1, 1) : ack(m - 1, ack(m, n - 1)); }
  function sumTo(n) { return n === 0 ? 0 : n + sumTo(n - 1); }
  function isEven(n) { return n === 0 ? true : isOdd(n - 1); }
  function isOdd(n) { return n === 0 ? false : isEven(n - 1); }
  function hanoi(n, a, b, c) { return n === 0 ? 0 : hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a); }
  return [ack(2, 3), sumTo(120), isEven(101), hanoi(12, 1, 2, 3)].join(",");
}
function nonCallable(n) {
  const things = [1, "s", null, undefined, {}, [], Symbol.iterator];
  const msgs = [];
  let errs = 0;
  for (let i = 0; i < n; i++) {
    const v = things[i % things.length];
    try { v(); } catch (e) { errs++; if (i < things.length) msgs.push(e.constructor.name); }
  }
  let m = "";
  try { const o = { f: 1 }; o.f(); } catch (e) { m = e instanceof TypeError; }
  let m2 = "";
  try { const o = {}; o.missing(); } catch (e) { m2 = e.name; }
  return errs + " " + msgs.join(",") + " | " + m + " | " + m2;
}
function methodsOnPrimitives(n) {
  let t = 0;
  for (let i = 0; i < n; i++) {
    t += "abcdef".indexOf("d") + (i).toString(2).length + (1.5).toFixed(1).length + true.toString().length;
  }
  return t;
}
function intrinsics(n) {
  const arr = [];
  let t = 0;
  for (let i = 0; i < n; i++) {
    arr.push(i);
    if (arr.length > 8) t += arr.pop() + arr.shift();
    t += Math.sqrt(i) | 0;
    t += Object.hasOwn(arr, 0) ? 1 : 0;
    t += arr.slice(1, 3).length;
    t += String.fromCharCode(65 + (i % 26)).charCodeAt(0);
  }
  return t + "," + arr.join("|");
}
console.log("direct", direct(10000));
console.log("polyUser", polyUser(10000));
console.log("polyNative", polyNative(10000));
console.log("bound", bound(8000));
console.log("callApply", callApply(8000));
console.log("spread", spread(4000));
console.log("rest", rest(5000));
console.log("recursion", recursion());
console.log("nonCallable", nonCallable(700));
console.log("primitives", methodsOnPrimitives(5000));
console.log("intrinsics", intrinsics(5000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_call_dispatch(run, tier):
    """CATCHES: call-IC bugs across tiers: polymorphic user/native call sites, bound functions, call/apply, trailing spread of arrays/holes/iterables/strings, rest and arguments objects (sloppy aliasing vs strict), defaults, deep recursion with RangeError recovery, and calling non-callables."""
    check_prog(run, tier, PROG_CALLS, "calls")


PROG_CLOSURES = r"""
function counterFactory(n) {
  const counters = [];
  for (let i = 0; i < 10; i++) {
    let c = i;
    counters.push({ inc: () => ++c, get: () => c });
  }
  for (let i = 0; i < n; i++) counters[i % 10].inc();
  return counters.map(o => o.get()).join(",");
}
function sharedCapture(n) {
  let total = 0;
  const add = x => { total += x; };
  const sub = x => { total -= x >> 1; };
  for (let i = 0; i < n; i++) { add(i); if (i & 1) sub(i); }
  return total;
}
function freshClosures(n) {
  let t = 0;
  for (let i = 0; i < n; i++) {
    const k = i & 15;
    const f = function (x) { return x * k + i; };
    t += f(2) + f(3);
  }
  return t;
}
function loopCapture() {
  const fs = [];
  for (let i = 0; i < 5; i++) fs.push(() => i);
  const gs = [];
  for (var j = 0; j < 5; j++) gs.push(() => j);
  const hs = [];
  for (const k of [7, 8, 9]) hs.push(() => k);
  let w = 0;
  const ws = [];
  while (w < 3) { let x = w * 10; ws.push(() => x); w++; }
  return [fs.map(f => f()).join(""), gs.map(f => f()).join(""), hs.map(f => f()).join(""), ws.map(f => f()).join("")].join(" ");
}
function nested(n) {
  function outer(a) {
    let b = a * 2;
    function mid(c) {
      let d = c + b;
      return function inner(e) { b++; return a + b + d + e; };
    }
    return mid(a + 1);
  }
  let t = 0;
  const f = outer(3);
  for (let i = 0; i < n; i++) t += f(i);
  return t;
}
function memo(n) {
  const cache = new Map();
  function fibm(k) {
    if (k < 2) return k;
    if (cache.has(k)) return cache.get(k);
    const v = fibm(k - 1) + fibm(k - 2);
    cache.set(k, v);
    return v;
  }
  let t = 0;
  for (let i = 0; i < n; i++) t += fibm(i % 70);
  return t;
}
function compose(n) {
  const pipe = (...fns) => x => fns.reduce((v, f) => f(v), x);
  const f = pipe(x => x + 1, x => x * 3, x => x - 2, x => x % 1000);
  let t = 0;
  for (let i = 0; i < n; i++) t += f(i);
  return t;
}
function iife(n) {
  let t = 0;
  for (let i = 0; i < n; i++) t += (function (q) { return q * q; })(i & 31) + ((q) => q + 1)(i & 7);
  return t;
}
function curry(n) {
  const c = a => b => c2 => a * 100 + b * 10 + c2;
  let t = 0;
  for (let i = 0; i < n; i++) t += c(i % 10)((i >> 1) % 10)((i >> 2) % 10);
  return t;
}
function setterCapture(n) {
  let hidden = 0;
  const o = { get h() { return hidden; }, set h(v) { hidden = v * 2; } };
  for (let i = 0; i < n; i++) o.h = o.h % 1000 + i;
  return hidden;
}
function selfRef(n) {
  const fact = function f(k) { return k <= 1 ? 1 : k * f(k - 1); };
  let t = 0;
  for (let i = 0; i < n; i++) t += fact(i % 12);
  return t;
}
function blockScopes(n) {
  let t = 0;
  for (let i = 0; i < n; i++) {
    let x = i;
    {
      let x = i * 2;
      t += x;
      {
        const x = 1;
        t += x;
      }
    }
    t += x;
    switch (i % 3) {
      case 0: { let y = 5; t += y; break; }
      case 1: { let y = 7; t -= y; break; }
      default: { const y = (() => i)(); t += y & 1; }
    }
  }
  return t;
}
console.log("counterFactory", counterFactory(10007));
console.log("sharedCapture", sharedCapture(20000));
console.log("freshClosures", freshClosures(20000));
console.log("loopCapture", loopCapture());
console.log("nested", nested(10000));
console.log("memo", memo(3000));
console.log("compose", compose(10000));
console.log("iife", iife(10000));
console.log("curry", curry(10000));
console.log("setterCapture", setterCapture(5000));
console.log("selfRef", selfRef(5000));
console.log("blockScopes", blockScopes(10000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_closures_and_captures(run, tier):
    """CATCHES: tiers that share or lose captured bindings: per-iteration let/const capture vs var, closures mutating captured state from hot loops, freshly created closures called in loops, nested environments, named function expressions, and block-scoped shadowing inside compiled code."""
    check_prog(run, tier, PROG_CLOSURES, "closures")


PROG_CTORS = r"""
class Pair { constructor(a, b) { this.a = a; this.b = b; } sum() { return this.a + this.b; } }
class Fielded { x = 1; #y = 2; static count = 0; constructor(v) { this.v = v; Fielded.count++; } get y() { return this.#y; } }
class Base { constructor(k) { this.k = k; this.kind = new.target.name; } who() { return "base" + this.k; } }
class Derived extends Base { constructor(k) { super(k * 2); this.d = true; } who() { return "derived:" + super.who(); } }
class Deeper extends Derived { extra = 9; }
function Legacy(v) { this.v = v; }
Legacy.prototype.get = function () { return this.v; };
function Override(v) { this.v = v; if (v & 1) return { v: -v }; return 5; }
function Arrayish(n) { const a = new Array(n); a.fill(n); return a; }
function NT() { return new.target === NT ? "new" : "call"; }
function pairs(n) {
  let s = 0;
  for (let i = 0; i < n; i++) { const p = new Pair(i, 1); s += p.sum(); }
  return s;
}
function fielded(n) {
  let s = 0;
  for (let i = 0; i < n; i++) { const f = new Fielded(i); s += f.x + f.y + f.v; }
  return s + "," + Fielded.count;
}
function derived(n) {
  let s = 0, last = "";
  for (let i = 0; i < n; i++) { const d = i % 3 === 0 ? new Deeper(i) : new Derived(i); s += d.k + d.extra || d.k; last = d.who() + ":" + d.kind; }
  return s + "," + last;
}
function legacy(n) {
  let s = 0, o = 0;
  for (let i = 0; i < n; i++) {
    s += new Legacy(i).get();
    const r = new Override(i);
    o += r.v;
    if (i === n >> 1) Legacy.prototype.get = function () { return -this.v; };
  }
  return s + "," + o;
}
function misc(n) {
  let s = 0;
  for (let i = 0; i < n; i++) s += Arrayish(i % 5).length + (NT() === "call" ? 1 : 0) + (new NT() instanceof NT ? 1 : 0);
  const errs = [];
  try { Pair(1, 2); } catch (e) { errs.push(e.constructor.name); }
  try { new (() => 1)(); } catch (e) { errs.push(e.constructor.name); }
  try { new Math.max(); } catch (e) { errs.push(e.constructor.name); }
  class Bad extends Base { constructor() { } }
  try { new Bad(); } catch (e) { errs.push(e.constructor.name); }
  class Twice extends Base { constructor() { super(1); try { super(2); } catch (e) { errs.push("twice:" + e.constructor.name); } } }
  new Twice();
  return s + "," + errs.join("|");
}
function protoMutation(n) {
  function P(v) { this.v = v; }
  P.prototype.m = function () { return 1; };
  let s = 0;
  for (let i = 0; i < n; i++) {
    const p = new P(i);
    s += p.m() + (Object.getPrototypeOf(p) === P.prototype ? 0 : 100);
    if (i === 300) P.prototype = { m() { return 10; } };
    if (i === 600) P.prototype.m = function () { return 1000; };
  }
  return s;
}
function builtins(n) {
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += new Date(Date.UTC(2020, i % 12, 1)).getUTCMonth();
    s += new Map([[i, i]]).size + new Set([1, 2, i & 1]).size + new Array(3).length + new Array(1, 2).length;
    s += new Error("m" + i).message.length + new RegExp("a+", "g").flags.length + new Number(i).valueOf() % 3;
    s += new String("ab").length + (new Boolean(false) ? 1 : 0) + new Uint8Array(4).length + new Object(i).valueOf() % 2;
  }
  return s;
}
function subclassBuiltins(n) {
  class MyArr extends Array { sum() { let s = 0; for (let i = 0; i < this.length; i++) s += this[i]; return s; } }
  class MyErr extends Error { constructor(m) { super(m); this.name = "MyErr"; } }
  class MyMap extends Map { get(k) { return super.get(k) ?? "dflt"; } }
  let s = 0;
  const a = new MyArr();
  for (let i = 0; i < n; i++) a.push(i);
  s += a.sum();
  const m = a.map(x => x * 2);
  const e = new MyErr("boom");
  const mm = new MyMap([[1, "one"]]);
  return [s, m instanceof MyArr, m.sum(), e instanceof Error, String(e), e.stack.split("\n")[0], mm.get(1), mm.get(2), MyArr.from([1, 2]).sum()].join(",");
}
console.log("pairs", pairs(20000));
console.log("fielded", fielded(5000));
console.log("derived", derived(5000));
console.log("legacy", legacy(5000));
console.log("misc", misc(2000));
console.log("protoMutation", protoMutation(1000));
console.log("builtins", builtins(1000));
console.log("subclassBuiltins", subclassBuiltins(2000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_constructors_in_loops(run, tier):
    """CATCHES: constructor fast paths that skip class fields/private members/static counters, mis-set new.target or derived this, ignore object return overrides, cache a stale .prototype after reassignment, or construct non-constructors (arrows, class calls without new, missing super) without the right TypeError/ReferenceError."""
    check_prog(run, tier, PROG_CTORS, "ctors")


PROG_COLLECTIONS = r"""
function intKeys(n) {
  const m = new Map();
  for (let i = 0; i < n; i++) m.set(i % 1000, (m.get(i % 1000) || 0) + i);
  let s = 0;
  for (let i = 0; i < 1000; i++) if (m.has(i)) s += m.get(i);
  for (let i = 0; i < 1000; i += 3) m.delete(i);
  return [m.size, s, m.get(1), m.get(3), [...m.keys()].slice(0, 5).join("|")].join(",");
}
function strKeys(n) {
  const m = new Map(), st = new Set();
  for (let i = 0; i < n; i++) {
    const k = "key" + (i % 257);
    m.set(k, (m.get(k) ?? 0) + 1);
    st.add(k.length + ":" + (i % 7));
  }
  let s = 0;
  for (const [k, v] of m) s += v * k.length;
  return [m.size, st.size, s, m.get("key0"), m.get("nope"), [...st].slice(0, 4).join("|")].join(",");
}
function specialKeys() {
  const m = new Map();
  const o1 = {}, o2 = {};
  for (let r = 0; r < 50; r++) {
    m.set(NaN, r); m.set(0, "zero"); m.set(-0, "negzero"); m.set(o1, "o1"); m.set(o2, "o2");
    m.set("0", "str0"); m.set(null, "null"); m.set(undefined, "undef"); m.set(true, "t"); m.set(1n, "big");
  }
  const s = new Set([NaN, NaN, 0, -0, "0", 0n]);
  return [m.size, m.get(NaN), m.get(0), m.get(-0), m.get(o1), m.get({}), m.get("0"), m.get(null), m.get(undefined), m.get(1n),
          s.size, s.has(-0), s.has(NaN), Object.is([...m.keys()][1], -0)].join(",");
}
function orderAfterDeletes(n) {
  const s = new Set();
  for (let i = 0; i < n; i++) s.add(i);
  for (let i = 0; i < n; i += 2) s.delete(i);
  for (let i = 0; i < 10; i++) s.add(i);
  const seen = [];
  let k = 0;
  for (const v of s) { seen.push(v); if (k++ === 2) { s.delete(5); s.add(-1); } if (seen.length > 12) break; }
  return seen.join(" ") + " size=" + s.size;
}
function mutateDuringIteration() {
  const m = new Map([[1, "a"], [2, "b"], [3, "c"]]);
  const out = [];
  for (const [k, v] of m) {
    out.push(k + v);
    if (k === 1) { m.delete(2); m.set(4, "d"); }
    if (k === 4) m.set(1, "again");
  }
  m.clear();
  return out.join(",") + " " + m.size;
}
function weak(n) {
  const wm = new WeakMap(), ws = new WeakSet();
  const keys = [];
  for (let i = 0; i < 50; i++) keys.push({ i });
  let s = 0;
  for (let i = 0; i < n; i++) {
    const k = keys[i % 50];
    wm.set(k, (wm.get(k) || 0) + 1);
    if (i % 3 === 0) ws.add(k);
    if (ws.has(k)) s++;
  }
  let err = "";
  try { wm.set(1, 1); } catch (e) { err = e.constructor.name; }
  return [s, wm.get(keys[7]), wm.has({}), ws.has(keys[3]), err].join(",");
}
function patchedMethods(n) {
  const m = new Map([[1, 10]]);
  let s = 0;
  const origGet = Map.prototype.get, origSet = Map.prototype.set;
  for (let i = 0; i < n; i++) {
    s += m.get(1);
    m.set(2, i);
    if (i === n >> 1) Map.prototype.get = function (k) { return origGet.call(this, k) * 2; };
    if (i === (n >> 1) + 100) m.get = function () { return 1; };
  }
  Map.prototype.get = origGet;
  Map.prototype.set = origSet;
  return s + "," + m.get(2) + "," + (Map.prototype.get === origGet);
}
function groupBy(n) {
  const items = [];
  for (let i = 0; i < n; i++) items.push({ id: i, cat: ["a", "b", "c", "d"][i % 4], v: (i * 7) % 13 });
  const g = Map.groupBy(items, x => x.cat);
  const o = Object.groupBy(items, x => x.v % 2 ? "odd" : "even");
  const sums = [];
  for (const [k, list] of g) sums.push(k + "=" + list.reduce((a, b) => a + b.v, 0));
  return sums.join(" ") + " " + o.odd.length + "/" + o.even.length;
}
function setOps() {
  const a = new Set([1, 2, 3, 4, 5]), b = new Set([4, 5, 6]);
  const fmt = s => [...s].join("");
  return [fmt(a.union(b)), fmt(a.intersection(b)), fmt(a.difference(b)), fmt(a.symmetricDifference(b)),
          a.isSubsetOf(b), new Set([4]).isSubsetOf(b), a.isSupersetOf(new Set([1, 2])), a.isDisjointFrom(new Set([9]))].join(",");
}
function forEachOrder() {
  const out = [];
  new Map([["x", 1], ["y", 2]]).forEach((v, k, mm) => out.push(k + v + mm.size));
  new Set(["p", "q"]).forEach((v, k) => out.push(v + k));
  const it = new Map([[1, 2]]).entries();
  out.push(Object.prototype.toString.call(it), JSON.stringify(it.next()), JSON.stringify(it.next()));
  return out.join(" ");
}
console.log("intKeys", intKeys(20000));
console.log("strKeys", strKeys(20000));
console.log("specialKeys", specialKeys());
console.log("orderAfterDeletes", orderAfterDeletes(2000));
console.log("mutateDuringIteration", mutateDuringIteration());
console.log("weak", weak(5000));
console.log("patched", patchedMethods(2000));
console.log("groupBy", groupBy(1000));
console.log("setOps", setOps());
console.log("forEachOrder", forEachOrder());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_collections_in_loops(run, tier):
    """CATCHES: collection lookup/insert fast paths that break SameValueZero keys (NaN, -0 normalisation, object identity), insertion order after deletes and during live iteration, WeakMap key validation, or keep using the builtin after Map.prototype.get / an own get method is replaced."""
    check_prog(run, tier, PROG_COLLECTIONS, "collections")


PROG_ITERATION = r"""
function forIn(n) {
  const proto = { inherited: 1, shadowed: 2 };
  const o = Object.create(proto);
  o.b = 1; o.a = 2; o[2] = "two"; o[1] = "one"; o.shadowed = 3;
  Object.defineProperty(o, "hidden", { value: 1, enumerable: false });
  let keys = "", count = 0;
  for (let r = 0; r < n; r++) {
    for (const k in o) { count++; if (r === 0) keys += k + ","; }
  }
  const arr = [5, 6, , 8];
  arr.extra = 1;
  let ak = "";
  for (const k in arr) ak += k + typeof k[0];
  let sk = "";
  for (const k in "hey") sk += k;
  let nk = 0;
  for (const k in null) nk++;
  for (const k in undefined) nk++;
  for (const k in 42) nk++;
  return [keys, count, ak, sk, nk].join(" ");
}
function forInMutation() {
  const o = { a: 1, b: 2, c: 3, d: 4 };
  const seen = [];
  for (const k in o) {
    seen.push(k);
    if (k === "a") { delete o.c; o.e = 5; }
  }
  const p = { x: 1, y: 2 };
  const s2 = [];
  for (var k in p) { s2.push(k); p["z" + s2.length] = 0; if (s2.length > 10) break; }
  return seen.join("") + " " + s2.join("") + " " + k;
}
function forOfArrays(n) {
  const a = [];
  for (let i = 0; i < n; i++) a.push(i);
  let s = 0;
  for (const v of a) s += v;
  let t = 0;
  for (const [i, v] of a.entries()) t += i * v;
  let u = 0;
  for (const k of a.keys()) u += k & 1;
  const grow = [1, 2, 3];
  let g = 0;
  for (const v of grow) { if (grow.length < 6) grow.push(v * 10); g += v; }
  const holes = [1, , 3];
  const hv = [];
  for (const v of holes) hv.push(v);
  return [s, t, u, g, hv.join("|")].join(",");
}
function forOfStrings() {
  let s = "", n = 0;
  for (const ch of "a\u{1F600}bé") { s += "[" + ch.length + "]"; n++; }
  const cps = [...("x\u{10437}y")].map(c => c.codePointAt(0).toString(16)).join(" ");
  return s + " " + n + " " + cps;
}
function generators(n) {
  function* range(a, b, step = 1) { for (let i = a; i < b; i += step) yield i; }
  function* take(it, k) { for (const v of it) { if (k-- <= 0) return "done"; yield v; } }
  function* inner() { const x = yield 1; yield x * 2; return "inner-ret"; }
  function* outer() { const r = yield* inner(); yield r; }
  let s = 0;
  for (let r = 0; r < n; r++) for (const v of take(range(0, 1000, 3), 10)) s += v;
  const g = outer();
  const steps = [g.next().value, g.next(21).value, g.next().value, g.next().done];
  const g2 = range(0, 10);
  g2.next();
  const ret = g2.return(99);
  const after = g2.next();
  const g3 = (function* () { try { yield 1; yield 2; } finally { s += 1000000; } })();
  g3.next();
  g3.return();
  let thrown = "";
  const g4 = (function* () { try { yield 1; } catch (e) { thrown = "caught " + e; yield 2; } })();
  g4.next();
  const t4 = g4.throw("E");
  return [s, steps.join("|"), JSON.stringify(ret), JSON.stringify(after), thrown, JSON.stringify(t4)].join(" ");
}
function closeOnBreak() {
  const log = [];
  const iterable = {
    [Symbol.iterator]() {
      let i = 0;
      return {
        next() { i++; log.push("n" + i); return { value: i, done: i > 5 }; },
        return() { log.push("ret"); return {}; },
      };
    },
  };
  for (const v of iterable) { if (v === 2) break; }
  try { for (const v of iterable) { if (v === 1) throw new Error("x"); } } catch (e) { log.push("caught"); }
  outer: for (const a of [1, 2]) { for (const v of iterable) { if (v === 1) continue outer; } }
  const [first] = iterable;
  log.push("first=" + first);
  return log.join(",");
}
function destructuring(n) {
  let s = 0;
  const pairs = [];
  for (let i = 0; i < 20; i++) pairs.push([i, i * 2, i * 3]);
  for (let r = 0; r < n; r++) {
    for (let i = 0; i < pairs.length; i++) {
      const [a, b, c] = pairs[i];
      s += a + b - c;
      const [x, , z = 7, ...rest] = pairs[i];
      s += x + z + rest.length;
    }
  }
  let a = 1, b = 2;
  for (let i = 0; i < 1001; i++) [a, b] = [b, a];
  const { p, q: { r = 5 } = {}, ...others } = { p: 1, t: 2, u: 3 };
  const [[d1, d2], [d3]] = [[1, 2], [3]];
  const [h1 = "def", h2] = [, "two"];
  const { length } = "hello";
  const fromSet = (([s1, s2]) => s1 + s2)(new Set(["S", "T"]));
  const [m1, m2] = new Map([["k", "v"]]);
  return [s, a, b, p, r, JSON.stringify(others), d1 + d2 + d3, h1, h2, length, fromSet, m1.join(":"), m2].join(",");
}
function iterHelpers() {
  function* nat() { let i = 0; while (true) yield i++; }
  const r1 = nat().filter(x => x % 3 === 0).map(x => x * x).take(5).toArray();
  const r2 = Iterator.from([1, 2, 3, 4]).drop(1).reduce((a, b) => a + b, 0);
  const r3 = [..."abc"].entries().toArray().map(([i, c]) => c + i).join("");
  const r4 = nat().flatMap(x => [x, -x]).take(6).toArray();
  return [r1.join(" "), r2, r3, r4.join(" "), nat().some(x => x > 5), nat().take(4).every(x => x < 4), nat().find(x => x * x > 50)].join(" | ");
}
function spreadsAndFrom(n) {
  let s = 0;
  for (let i = 0; i < n; i++) {
    const a = [i, i + 1];
    const b = [...a, ...a, i];
    s += b.length + b[4];
    const o = { ...{ x: i }, y: 1, ...null, ...[7] };
    s += o.x + o.y + o[0];
  }
  return [s, Array.from(new Map([[1, 2]])).join(";"), Array.from("ab", c => c + c).join(""), Object.entries({ a: 1, b: [2] }).join(";"),
          Object.fromEntries([["k", 1], ["j", 2]]).j].join(" ");
}
console.log("forIn", forIn(2000));
console.log("forInMutation", forInMutation());
console.log("forOfArrays", forOfArrays(4000));
console.log("forOfStrings", forOfStrings());
console.log("generators", generators(150));
console.log("closeOnBreak", closeOnBreak());
console.log("destructuring", destructuring(150));
console.log("iterHelpers", iterHelpers());
console.log("spreads", spreadsAndFrom(3000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_iteration_protocols(run, tier):
    """CATCHES: tiers with wrong for-in key order (integer keys first, inherited/shadowed/non-enumerable handling, deletion during enumeration), for-of over growing/holey arrays and strings with surrogates, generator return/throw/yield* plumbing, iterator close on break/throw/continue-outer, and array/object destructuring defaults/holes/rest."""
    check_prog(run, tier, PROG_ITERATION, "iteration")


PROG_SWITCH_STRINGS = r"""
function intSwitch(n) {
  const t = [0, 0, 0, 0, 0, 0];
  for (let i = 0; i < n; i++) {
    switch (i % 9) {
      case 0: t[0]++;
      case 1: t[1]++; break;
      case 2: case 3: t[2]++; break;
      default: t[5]++;
      case 4: t[3]++; break;
      case 5: { t[4] += 2; continue; }
      case 6: t[4]--;
    }
  }
  return t.join(",");
}
function strSwitch(n) {
  const words = ["alpha", "beta", "gamma", "delta", "", "1", 1, null, undefined, NaN];
  let out = 0;
  const seen = [];
  for (let i = 0; i < n; i++) {
    const w = words[i % words.length];
    let v;
    switch (w) {
      case "alpha": v = 1; break;
      case "beta": v = 2; break;
      case "gam" + "ma": v = 3; break;
      case "": v = 4; break;
      case 1: v = 5; break;
      case "1": v = 6; break;
      case null: v = 7; break;
      case undefined: v = 8; break;
      case NaN: v = 100; break;
      default: v = 9;
    }
    out += v;
    if (i < words.length) seen.push(v);
  }
  return out + ":" + seen.join("");
}
function sideEffectCases() {
  const log = [];
  const c = v => { log.push("c" + v); return v; };
  function pick(x) {
    switch (x) { case c(1): return "one"; case c(2): return "two"; default: return "dflt"; case c(3): return "three"; }
  }
  const r = [pick(2), pick(3), pick(9)];
  return r.join(",") + " " + log.join("");
}
function lexicalCases(n) {
  let s = 0;
  for (let i = 0; i < n; i++) {
    switch (i & 3) {
      case 0: let a = i; s += a; break;
      case 1: const b = 2; s += b; break;
      case 2: { let a = 5; s -= a; } break;
      default: function f() { return 3; } s += f();
    }
  }
  let tdz = "";
  try { switch (1) { case 0: let z = 1; case 1: z = 2; } } catch (e) { tdz = e.constructor.name; }
  return s + " " + tdz;
}
function building(n) {
  let s = "";
  for (let i = 0; i < n; i++) s += String.fromCharCode(97 + (i % 26));
  let parts = [];
  for (let i = 0; i < n; i++) parts.push(i.toString(36));
  const joined = parts.join("");
  let t = "";
  for (let i = 0; i < 300; i++) t = `${t.length}:${i % 10}` + t.slice(0, 20);
  let codes = 0;
  for (let i = 0; i < s.length; i++) codes = (codes * 31 + s.charCodeAt(i)) | 0;
  let mixed = "";
  for (let i = 0; i < 50; i++) mixed += i + (i % 2 ? "o" : 1) + null + [i] + true;
  return [s.length, s.slice(-5), joined.length, joined.slice(100, 120), t, codes, mixed.length, mixed.slice(0, 40)].join(" ");
}
function searching(n) {
  const hay = "the quick brown fox jumps over the lazy dog ".repeat(20);
  let c = 0;
  for (let i = 0; i < n; i++) {
    c += hay.indexOf("o", i % 100) + hay.lastIndexOf("the") + (hay.includes("lazy") ? 1 : 0) + (hay.startsWith("the") ? 1 : 0);
    c += hay.charAt(i % hay.length).length + (hay[i % hay.length] === " " ? 1 : 0) + hay.at(-2).charCodeAt(0);
  }
  return c;
}
function transforms() {
  const s = "  Hello, Wörld! ß ǅ İ  ";
  return [s.trim(), s.trimStart().length, s.toUpperCase(), s.toLowerCase(), s.split(",").length, s.split("").length,
          "a-b-c".split("-", 2).join("+"), "abc".padStart(6, "12").padEnd(8, "."), "x".repeat(3), "aXbXc".replaceAll("X", "_"),
          "abc".replace(/b/, m => m.toUpperCase() + "$&"), "AbC".localeCompare("abc") !== 0, "Å".normalize("NFC").length,
          "abcdef".substring(4, 1), "abcdef".substr(-3, 2), String.raw`a\nb${1}`, "z".codePointAt(0), "€".charCodeAt(0)].join("|");
}
function regexLoops(n) {
  const re = /(\d+)-(\w+)/g;
  const text = "10-ab 20-cd x 30-ef 4-g";
  let s = 0, names = "";
  for (let i = 0; i < n; i++) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) { s += +m[1]; if (i === 0) names += m[2]; }
    s += "a1b2c3".replace(/\d/g, "").length + (/^q/.test("quiz") ? 1 : 0) + "x,y;z".split(/[,;]/).length;
    const mm = text.match(/\d+/g);
    s += mm.length;
  }
  const named = "2024-05-06".match(/(?<y>\d{4})-(?<m>\d\d)-(?<d>\d\d)/).groups;
  return [s, names, named.y + named.m + named.d, [..."a1b22c333".matchAll(/\d+/g)].map(x => x[0] + "@" + x.index).join(" "),
          "AbcAbc".search(/c/), /a.c/s.test("a\nc"), /\u{1F600}/u.test("\u{1F600}"), "aaa".lastIndexOf("a")].join(" ");
}
function templates(n) {
  const tag = (strs, ...vals) => strs.raw.join("|") + "#" + vals.join(",");
  let s = 0;
  for (let i = 0; i < n; i++) s += `${i}-${i * 2}-${{ toString() { return "o"; } }}`.length;
  return s + " " + tag`a${1}b${2}\n` + " " + `${[1, 2]}${null}${undefined}${Symbol.iterator.description}`;
}
console.log("intSwitch", intSwitch(9000));
console.log("strSwitch", strSwitch(5000));
console.log("sideEffectCases", sideEffectCases());
console.log("lexicalCases", lexicalCases(4000));
console.log("building", building(3000));
console.log("searching", searching(3000));
console.log("transforms", transforms());
console.log("regexLoops", regexLoops(500));
console.log("templates", templates(3000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_switch_and_strings(run, tier):
    """CATCHES: switch lowering bugs (fallthrough, default in the middle, strict equality incl. NaN/null/undefined/"1" vs 1, case-expression evaluation order, lexical TDZ across cases) and string-building/search/regex loops that diverge between interpreter, bytecode VM and JIT."""
    check_prog(run, tier, PROG_SWITCH_STRINGS, "switch_strings")


PROG_EXCEPTIONS = r"""
function hotCatch(n) {
  let caught = 0, s = 0;
  for (let i = 0; i < n; i++) {
    try {
      if (i % 7 === 0) throw new RangeError("r" + i);
      if (i % 11 === 0) throw i;
      if (i % 13 === 0) null.x;
      s += i;
    } catch (e) {
      caught++;
      if (typeof e === "number") s -= e;
      else if (e instanceof RangeError) s += 1;
      else s += 2;
    }
  }
  return s + "," + caught;
}
function thrower(i) { if (i % 5 === 0) throw new Error("t" + i); return i; }
function viaCalls(n) {
  let s = 0, msg = "";
  for (let i = 0; i < n; i++) {
    try { s += thrower(i); } catch (e) { msg = e.message; s -= 1; }
  }
  return s + "," + msg;
}
function finallyFlow(n) {
  const log = [];
  function f(x) {
    try {
      if (x === 0) return "ret";
      if (x === 1) throw new Error("boom");
      return "body";
    } catch (e) {
      return "catch:" + e.message;
    } finally {
      log.push("fin" + x);
      if (x === 2) return "override";
    }
  }
  function g() {
    let k = 0;
    for (let i = 0; i < 10; i++) {
      try { if (i === 3) continue; if (i === 6) break; k += i; } finally { k += 100; }
    }
    return k;
  }
  function h() {
    try { try { throw new Error("inner"); } finally { log.push("innerFin"); } } catch (e) { return "outer caught " + e.message; }
  }
  function swallow() { for (;;) { try { throw 1; } finally { break; } } return "swallowed"; }
  let s = 0;
  for (let i = 0; i < n; i++) s += g();
  return [f(0), f(1), f(2), f(3), s, h(), swallow(), log.join(",")].join(" ");
}
function rethrow(n) {
  let depth = 0, msgs = [];
  function level(k) {
    try {
      if (k === 0) throw new TypeError("bottom");
      return level(k - 1);
    } catch (e) {
      depth++;
      if (k < 3) throw e;
      return e.message + "@" + k;
    }
  }
  for (let i = 0; i < n; i++) msgs.push(level(5));
  return depth + " " + msgs[0] + " " + msgs.length;
}
function fromGetters(n) {
  const o = { get bad() { throw new SyntaxError("getter"); }, good: 1 };
  let s = 0, names = new Set();
  for (let i = 0; i < n; i++) {
    try { s += i % 2 ? o.good : o.bad; } catch (e) { names.add(e.name + ":" + e.message); }
    try { s += [1, 2][i % 3].toFixed(0).length; } catch (e) { names.add(e.name); }
    try { JSON.parse(i % 4 ? "[" + i + "]" : "{bad"); } catch (e) { names.add(e.name); }
  }
  return s + " " + [...names].join(",");
}
function errorObjects() {
  const e1 = new Error("msg", { cause: "why" });
  const e2 = new AggregateError([new Error("a"), new TypeError("b")], "agg");
  class E3 extends RangeError {}
  const e3 = new E3("sub");
  const plain = Error("no new");
  return [e1.cause, e2.errors.length, e2.errors[1].name, e2.message, e3.name, e3 instanceof RangeError, e3 instanceof E3,
          String(e3), plain.message, Object.prototype.toString.call(e1), e1.hasOwnProperty("message"), "stack" in e1,
          new Error().message === "", String(new TypeError())].join(",");
}
function catchBindings(n) {
  let s = 0;
  for (let i = 0; i < n; i++) {
    try { throw { code: i, list: [i, i + 1] }; } catch ({ code, list: [a, b] }) { s += code + a + b; }
    try { throw i; } catch { s++; }
    let e = "outer";
    try { throw "inner"; } catch (e) { e = e + "!"; } finally { s += e === "outer" ? 1 : 1000; }
  }
  return s;
}
function nested(n) {
  let order = [];
  function a(i) {
    try { return b(i); } finally { if (i === 0) order.push("a-fin"); }
  }
  function b(i) {
    try { if (i % 2) throw new Error("odd"); return i; } catch (e) { if (i % 3 === 0) throw e; return -i; }
  }
  let s = 0, outer = 0;
  for (let i = 0; i < n; i++) { try { s += a(i); } catch (e) { outer++; } }
  return s + "," + outer + "," + order.join("");
}
console.log("hotCatch", hotCatch(20000));
console.log("viaCalls", viaCalls(20000));
console.log("finallyFlow", finallyFlow(2000));
console.log("rethrow", rethrow(500));
console.log("fromGetters", fromGetters(3000));
console.log("errorObjects", errorObjects());
console.log("catchBindings", catchBindings(5000));
console.log("nested", nested(6000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_exceptions_in_hot_code(run, tier):
    """CATCHES: tiers that mis-unwind exceptions thrown from compiled loops, callees and getters: wrong catch dispatch, finally blocks skipped or run twice, return/break/continue overridden by finally, rethrow across frames, destructured catch parameters and catch-binding shadowing."""
    check_prog(run, tier, PROG_EXCEPTIONS, "exceptions")


PROG_ASYNC = r"""
const log = [];
async function sumAsync(n) {
  let s = 0;
  for (let i = 0; i < n; i++) { s += await i; if (i % 100 === 0) s += await Promise.resolve(1); }
  return s;
}
async function thrower(i) { if (i % 3 === 0) throw new Error("e" + i); return i; }
async function catching(n) {
  let s = 0, c = 0;
  for (let i = 0; i < n; i++) {
    try { s += await thrower(i); } catch (e) { c++; }
  }
  return s + "/" + c;
}
async function* agen(n) { for (let i = 0; i < n; i++) { await null; yield i * 2; } }
async function consume(n) {
  let s = 0;
  for await (const v of agen(n)) s += v;
  for await (const v of [Promise.resolve(5), 6, Promise.resolve(7)]) s += v;
  return s;
}
function ordering() {
  const out = [];
  Promise.resolve().then(() => out.push("p1")).then(() => out.push("p3"));
  queueMicrotask(() => out.push("q1"));
  (async () => { out.push("a-sync"); await undefined; out.push("a1"); await null; out.push("a2"); })();
  Promise.resolve().then(() => out.push("p2"));
  out.push("sync");
  const thenable = { then(r) { out.push("thenable"); r("T"); } };
  Promise.resolve(thenable).then(v => out.push("tv" + v));
  return new Promise(r => setTimeout(() => r(out.join(",")), 0));
}
async function combinators() {
  const d = (v, fail) => fail ? Promise.reject(new Error(v)) : Promise.resolve(v);
  const all = await Promise.all([d(1), d(2), 3]);
  const settled = await Promise.allSettled([d("a"), d("b", true)]);
  const any = await Promise.any([d("x", true), d("y")]);
  const race = await Promise.race([new Promise(r => setTimeout(() => r("slow"), 5)), d("fast")]);
  let agg = "";
  try { await Promise.any([d("p", true), d("q", true)]); } catch (e) { agg = e.constructor.name + ":" + e.errors.length; }
  const wr = Promise.withResolvers();
  setTimeout(() => wr.resolve("wr"), 1);
  return [all.join(""), settled.map(s => s.status + ":" + (s.value || s.reason.message)).join("|"), any, race, agg, await wr.promise].join(" ");
}
function syncGenerators(n) {
  function* fibGen() { let [a, b] = [0, 1]; while (true) { yield a; [a, b] = [b, a + b]; } }
  function* tree(d) { if (d === 0) { yield 1; return; } yield* tree(d - 1); yield d; yield* tree(d - 1); }
  let s = 0;
  for (let r = 0; r < n; r++) {
    let k = 0;
    for (const v of fibGen()) { if (k++ > 30) break; s += v % 1000; }
  }
  let t = 0;
  for (const v of tree(10)) t += v;
  const g = fibGen();
  const spreadTen = [];
  for (let i = 0; i < 10; i++) spreadTen.push(g.next().value);
  const genObj = { *m() { yield this.v; }, v: "this-ok" };
  return [s, t, spreadTen.join(" "), [...genObj.m()][0], Object.prototype.toString.call(g), typeof g[Symbol.iterator]].join(" ");
}
async function main() {
  log.push("sumAsync " + await sumAsync(1500));
  log.push("catching " + await catching(1500));
  log.push("consume " + await consume(500));
  log.push("ordering " + await ordering());
  log.push("combinators " + await combinators());
  log.push("syncGenerators " + syncGenerators(300));
  const results = await Promise.all([sumAsync(10), sumAsync(20), catching(10)]);
  log.push("parallel " + results.join(","));
  let unhandled = "";
  try { await (async () => { await null; throw new TypeError("late"); })(); } catch (e) { unhandled = e.message; }
  log.push("lateThrow " + unhandled);
}
main().then(() => console.log(log.join("\n")));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_async_and_generators(run, tier):
    """CATCHES: tiers that resume async functions/generators with wrong values or ordering: await in hot loops, try/catch around awaited rejections, async generators with for-await, microtask vs thenable vs timer ordering, Promise combinators, recursive yield* and infinite generators closed by break."""
    check_prog(run, tier, PROG_ASYNC, "async")


PROG_THIS = r"""
var globalName = "G";
function sloppyThis() { return this === globalThis ? "global" : typeof this; }
function strictThis() { "use strict"; return this === undefined ? "undef" : typeof this; }
function primThis() { return typeof this + ":" + (this instanceof Number || this instanceof String || this instanceof Boolean); }
function strictPrim() { "use strict"; return typeof this; }
const obj = {
  name: "obj",
  regular() { return this.name; },
  arrow: () => typeof this,
  nested() { const inner = () => this.name; return inner(); },
  delayed() { return function () { return this === globalThis; }.call(undefined); },
};
class K {
  constructor() { this.name = "K"; this.bound = this.method.bind(this); }
  method() { return this === undefined ? "undef" : this.name; }
  static sm() { return this === K; }
}
function run(n) {
  const counts = {};
  const bump = k => { counts[k] = (counts[k] || 0) + 1; };
  const k = new K();
  const detached = k.method;
  const holder = { name: "holder", m: obj.regular };
  for (let i = 0; i < n; i++) {
    bump("sloppy:" + sloppyThis());
    bump("strict:" + strictThis());
    bump("callPrim:" + primThis.call(5));
    bump("strictPrim:" + strictPrim.call("s"));
    bump("callNull:" + sloppyThis.call(null));
    bump("strictNull:" + String(strictThis.call(null)));
    bump("method:" + obj.regular());
    bump("borrowed:" + holder.m());
    bump("arrow:" + obj.arrow());
    bump("nested:" + obj.nested());
    bump("delayed:" + obj.delayed());
    bump("detached:" + detached());
    bump("bound:" + k.bound());
    bump("static:" + K.sm());
    bump("apply:" + obj.regular.apply({ name: "applied" }));
    bump("comma:" + (0, obj.regular)());
    bump("paren:" + (obj.regular)());
    bump("bind2:" + obj.regular.bind({ name: "b1" }).bind({ name: "b2" })());
    bump("reflect:" + Reflect.apply(obj.regular, { name: "refl" }, []));
    bump("arrayCb:" + [1].map(function () { return this.tag; }, { tag: "cb" })[0]);
    bump("arrayCbStrict:" + [1].map(function () { "use strict"; return typeof this; })[0]);
  }
  return Object.entries(counts).map(([key, v]) => key + "=" + v).join("\n");
}
console.log(run(500));
console.log(this === globalThis, typeof globalThis.globalName, globalName);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_this_binding(run, tier):
    """CATCHES: this-binding mistakes in compiled call paths: sloppy functions must box primitives and map null/undefined to globalThis while strict functions must not, detached class methods get undefined, arrows capture lexical this, comma/paren member calls, double bind, Reflect.apply and callback thisArg."""
    check_prog(run, tier, PROG_THIS, "this")


PROG_DEOPTS = r"""
function accumulate(xs) { let s = 0; for (let i = 0; i < xs.length; i++) s += xs[i]; return s; }
function kinds() {
  const ints = [], dbls = [], mixed = [];
  for (let i = 0; i < 2000; i++) { ints.push(i); dbls.push(i + 0.5); mixed.push(i % 500 === 499 ? String(i) : i); }
  const out = [];
  for (let r = 0; r < 20; r++) { out.length = 0; out.push(accumulate(ints), accumulate(dbls)); }
  out.push(accumulate(mixed).length);
  out.push(accumulate([1, 2, { valueOf() { return 10; } }]));
  try { out.push(accumulate([1n, 2n, 3n])); } catch (e) { out.push(e.name); }
  out.push(accumulate(["a", 1, 2]));
  out.push(accumulate([1, 2, , 4]));
  out.push(accumulate({ length: 3, 0: 1, 1: 2, 2: 3 }));
  out.push(accumulate("123"));
  out.push(accumulate([2147483647, 1, -2147483648, -1, 0.5]));
  return out.join(",");
}
function typeFlip(n) {
  let x = 0;
  const trace = [];
  for (let i = 0; i < n; i++) {
    if (i === n * 0.25) x = 1.5;
    else if (i === n * 0.5) x = "s";
    else if (i === n * 0.75) x = 1n;
    if (typeof x === "bigint") x += 1n;
    else x += 1;
    if (i % (n / 8) === 0) trace.push(typeof x + ":" + String(x).slice(0, 12));
  }
  return trace.join(" ");
}
function globalsChange(n) {
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += LIMIT * 2;
    if (i === n >> 1) LIMIT = "7";
  }
  return typeof s + ":" + String(s).length + ":" + String(s).slice(0, 15);
}
var LIMIT = 3;
function cmpFlip() {
  const vals = [1, 2, 3, 2.5, "10", "9", null, undefined, NaN, true, [2], { valueOf() { return 2; } }];
  let r = "";
  for (let round = 0; round < 3; round++) {
    let c = 0;
    for (let i = 0; i < 3000; i++) { const a = vals[i % vals.length], b = vals[(i * 7) % vals.length]; if (a < b) c++; if (a == b) c += 10; if (a === b) c += 100; }
    r += c + ";";
  }
  return r;
}
function funcRedefine(n) {
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += helper(i);
    if (i === 300) helper = function (x) { return -x; };
    if (i === 600) globalThis.helper = x => x * 100;
  }
  return s;
}
var helper = function (x) { return x; };
function shapeChurn(n) {
  function make(i) { const o = { a: i }; if (i % 4 === 1) o.b = 1; if (i % 4 === 2) { o.c = 2; o.b = 3; } if (i % 4 === 3) Object.defineProperty(o, "a", { get() { return 1000; } }); return o; }
  let s = 0;
  for (let i = 0; i < n; i++) { const o = make(i); s += o.a + (o.b || 0) + (o.c || 0); }
  return s;
}
function arrayToDict(n) {
  const a = [];
  for (let i = 0; i < 100; i++) a.push(i);
  let s = 0;
  for (let r = 0; r < n; r++) {
    for (let i = 0; i < a.length && i < 120; i++) s += a[i] === undefined ? 0.25 : a[i];
    if (r === 5) a[100000] = 1;
    if (r === 10) Object.defineProperty(a, 50, { get() { return -1000; } });
    if (r === 15) Object.freeze(a);
    if (r === 16) { try { "use strict"; a.push(1); } catch (e) { s += 0.5; } }
  }
  return s + "," + a.length;
}
function argumentsDeopt(n) {
  function f(a, b) { if (a === 3) arguments[1] = "changed"; return b; }
  function g() { return Array.prototype.slice.call(arguments, 1).length; }
  let s = 0, last = "";
  for (let i = 0; i < n; i++) { const r = f(i % 5, i); if (typeof r === "string") last = r; else s += r; s += g(1, 2, 3, i); }
  return s + "," + last;
}
function protoMethodLater(n) {
  const arr = [3, 1, 2];
  let s = 0;
  for (let i = 0; i < n; i++) {
    s += arr.indexOf(2);
    if (i === n >> 1) Array.prototype.indexOf = function () { return 100; };
  }
  delete Array.prototype.indexOf;
  return s + "," + typeof [].indexOf;
}
console.log("kinds", kinds());
console.log("typeFlip", typeFlip(8000));
console.log("globalsChange", globalsChange(1000));
console.log("cmpFlip", cmpFlip());
console.log("funcRedefine", funcRedefine(1000));
console.log("shapeChurn", shapeChurn(4000));
console.log("arrayToDict", arrayToDict(20));
console.log("argumentsDeopt", argumentsDeopt(3000));
console.log("protoMethodLater", protoMethodLater(1000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_type_changes_mid_loop(run, tier):
    """CATCHES: speculative fast paths that keep running after their assumption breaks: a loop accumulator flipping int->double->string->BigInt, arrays switching element kinds/becoming sparse/getter-backed/frozen, a global changing type, a called global function being reassigned, and Array.prototype methods patched mid-loop."""
    check_prog(run, tier, PROG_DEOPTS, "deopts")


# The classic V8 "Richards" OS-scheduler benchmark (task control blocks, packets, four task
# roles). The JIT pattern-matches this program shape, so the canonical source is kept verbatim;
# one full-size run (COUNT=1000) warms every method, then COUNT is lowered so the 100+ further
# runs that trigger whole-scheduler recompilation stay fast under the tree-walking interpreter.
RICHARDS = r"""
function runRichards() {
  var scheduler = new Scheduler();
  scheduler.addIdleTask(ID_IDLE, 0, null, COUNT);

  var queue = new Packet(null, ID_WORKER, KIND_WORK);
  queue = new Packet(queue,  ID_WORKER, KIND_WORK);
  scheduler.addWorkerTask(ID_WORKER, 1000, queue);

  queue = new Packet(null, ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_A, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_A, 2000, queue);

  queue = new Packet(null, ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue,  ID_DEVICE_B, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_B, 3000, queue);

  scheduler.addDeviceTask(ID_DEVICE_A, 4000, null);

  scheduler.addDeviceTask(ID_DEVICE_B, 5000, null);

  scheduler.schedule();

  return scheduler.queueCount + "/" + scheduler.holdCount;
}

var COUNT = 100;

function Scheduler() {
  this.queueCount = 0;
  this.holdCount = 0;
  this.blocks = new Array(NUMBER_OF_IDS);
  this.list = null;
  this.currentTcb = null;
  this.currentId = null;
}

var ID_IDLE       = 0;
var ID_WORKER     = 1;
var ID_HANDLER_A  = 2;
var ID_HANDLER_B  = 3;
var ID_DEVICE_A   = 4;
var ID_DEVICE_B   = 5;
var NUMBER_OF_IDS = 6;

var KIND_DEVICE   = 0;
var KIND_WORK     = 1;

Scheduler.prototype.addIdleTask = function (id, priority, queue, count) {
  this.addRunningTask(id, priority, queue, new IdleTask(this, 1, count));
};

Scheduler.prototype.addWorkerTask = function (id, priority, queue) {
  this.addTask(id, priority, queue, new WorkerTask(this, ID_HANDLER_A, 0));
};

Scheduler.prototype.addHandlerTask = function (id, priority, queue) {
  this.addTask(id, priority, queue, new HandlerTask(this));
};

Scheduler.prototype.addDeviceTask = function (id, priority, queue) {
  this.addTask(id, priority, queue, new DeviceTask(this))
};

Scheduler.prototype.addRunningTask = function (id, priority, queue, task) {
  this.addTask(id, priority, queue, task);
  this.currentTcb.setRunning();
};

Scheduler.prototype.addTask = function (id, priority, queue, task) {
  this.currentTcb = new TaskControlBlock(this.list, id, priority, queue, task);
  this.list = this.currentTcb;
  this.blocks[id] = this.currentTcb;
};

Scheduler.prototype.schedule = function () {
  this.currentTcb = this.list;
  while (this.currentTcb != null) {
    if (this.currentTcb.isHeldOrSuspended()) {
      this.currentTcb = this.currentTcb.link;
    } else {
      this.currentId = this.currentTcb.id;
      this.currentTcb = this.currentTcb.run();
    }
  }
};

Scheduler.prototype.release = function (id) {
  var tcb = this.blocks[id];
  if (tcb == null) return tcb;
  tcb.markAsNotHeld();
  if (tcb.priority > this.currentTcb.priority) {
    return tcb;
  } else {
    return this.currentTcb;
  }
};

Scheduler.prototype.holdCurrent = function () {
  this.holdCount++;
  this.currentTcb.markAsHeld();
  return this.currentTcb.link;
};

Scheduler.prototype.suspendCurrent = function () {
  this.currentTcb.markAsSuspended();
  return this.currentTcb;
};

Scheduler.prototype.queue = function (packet) {
  var t = this.blocks[packet.id];
  if (t == null) return t;
  this.queueCount++;
  packet.link = null;
  packet.id = this.currentId;
  return t.checkPriorityAdd(this.currentTcb, packet);
};

function TaskControlBlock(link, id, priority, queue, task) {
  this.link = link;
  this.id = id;
  this.priority = priority;
  this.queue = queue;
  this.task = task;
  if (queue == null) {
    this.state = STATE_SUSPENDED;
  } else {
    this.state = STATE_SUSPENDED_RUNNABLE;
  }
}

var STATE_RUNNING = 0;
var STATE_RUNNABLE = 1;
var STATE_SUSPENDED = 2;
var STATE_HELD = 4;
var STATE_SUSPENDED_RUNNABLE = STATE_SUSPENDED | STATE_RUNNABLE;
var STATE_NOT_HELD = ~STATE_HELD;

TaskControlBlock.prototype.setRunning = function () {
  this.state = STATE_RUNNING;
};

TaskControlBlock.prototype.markAsNotHeld = function () {
  this.state = this.state & STATE_NOT_HELD;
};

TaskControlBlock.prototype.markAsHeld = function () {
  this.state = this.state | STATE_HELD;
};

TaskControlBlock.prototype.isHeldOrSuspended = function () {
  return (this.state & STATE_HELD) != 0 || (this.state == STATE_SUSPENDED);
};

TaskControlBlock.prototype.markAsSuspended = function () {
  this.state = this.state | STATE_SUSPENDED;
};

TaskControlBlock.prototype.markAsRunnable = function () {
  this.state = this.state | STATE_RUNNABLE;
};

TaskControlBlock.prototype.run = function () {
  var packet;
  if (this.state == STATE_SUSPENDED_RUNNABLE) {
    packet = this.queue;
    this.queue = packet.link;
    if (this.queue == null) {
      this.state = STATE_RUNNING;
    } else {
      this.state = STATE_RUNNABLE;
    }
  } else {
    packet = null;
  }
  return this.task.run(packet);
};

TaskControlBlock.prototype.checkPriorityAdd = function (task, packet) {
  if (this.queue == null) {
    this.queue = packet;
    this.markAsRunnable();
    if (this.priority > task.priority) return this;
  } else {
    this.queue = packet.addTo(this.queue);
  }
  return task;
};

TaskControlBlock.prototype.toString = function () {
  return "tcb { " + this.task + "@" + this.state + " }";
};

function IdleTask(scheduler, v1, count) {
  this.scheduler = scheduler;
  this.v1 = v1;
  this.count = count;
}

IdleTask.prototype.run = function (packet) {
  this.count--;
  if (this.count == 0) return this.scheduler.holdCurrent();
  if ((this.v1 & 1) == 0) {
    this.v1 = this.v1 >> 1;
    return this.scheduler.release(ID_DEVICE_A);
  } else {
    this.v1 = (this.v1 >> 1) ^ 0xD008;
    return this.scheduler.release(ID_DEVICE_B);
  }
};

IdleTask.prototype.toString = function () {
  return "IdleTask"
};

function DeviceTask(scheduler) {
  this.scheduler = scheduler;
  this.v1 = null;
}

DeviceTask.prototype.run = function (packet) {
  if (packet == null) {
    if (this.v1 == null) return this.scheduler.suspendCurrent();
    var v = this.v1;
    this.v1 = null;
    return this.scheduler.queue(v);
  } else {
    this.v1 = packet;
    return this.scheduler.holdCurrent();
  }
};

DeviceTask.prototype.toString = function () {
  return "DeviceTask";
};

function WorkerTask(scheduler, v1, v2) {
  this.scheduler = scheduler;
  this.v1 = v1;
  this.v2 = v2;
}

WorkerTask.prototype.run = function (packet) {
  if (packet == null) {
    return this.scheduler.suspendCurrent();
  } else {
    if (this.v1 == ID_HANDLER_A) {
      this.v1 = ID_HANDLER_B;
    } else {
      this.v1 = ID_HANDLER_A;
    }
    packet.id = this.v1;
    packet.a1 = 0;
    for (var i = 0; i < DATA_SIZE; i++) {
      this.v2++;
      if (this.v2 > 26) this.v2 = 1;
      packet.a2[i] = this.v2;
    }
    return this.scheduler.queue(packet);
  }
};

WorkerTask.prototype.toString = function () {
  return "WorkerTask";
};

function HandlerTask(scheduler) {
  this.scheduler = scheduler;
  this.v1 = null;
  this.v2 = null;
}

HandlerTask.prototype.run = function (packet) {
  if (packet != null) {
    if (packet.kind == KIND_WORK) {
      this.v1 = packet.addTo(this.v1);
    } else {
      this.v2 = packet.addTo(this.v2);
    }
  }
  if (this.v1 != null) {
    var count = this.v1.a1;
    var v;
    if (count < DATA_SIZE) {
      if (this.v2 != null) {
        v = this.v2;
        this.v2 = this.v2.link;
        v.a1 = this.v1.a2[count];
        this.v1.a1 = count + 1;
        return this.scheduler.queue(v);
      }
    } else {
      v = this.v1;
      this.v1 = this.v1.link;
      return this.scheduler.queue(v);
    }
  }
  return this.scheduler.suspendCurrent();
};

HandlerTask.prototype.toString = function () {
  return "HandlerTask";
};

var DATA_SIZE = 4;

function Packet(link, id, kind) {
  this.link = link;
  this.id = id;
  this.kind = kind;
  this.a1 = 0;
  this.a2 = new Array(DATA_SIZE);
}

Packet.prototype.addTo = function (queue) {
  this.link = null;
  if (queue == null) return this;
  var peek, next = queue;
  while ((peek = next.link) != null)
    next = peek;
  next.link = this;
  return queue;
};

Packet.prototype.toString = function () {
  return "Packet";
};

function queueLength(p) { var n = 0; while (p != null && n < 50) { n++; p = p.link; } return n; }
function describe(s) {
  var parts = [];
  for (var id = 0; id < NUMBER_OF_IDS; id++) {
    var t = s.blocks[id];
    if (t == null) { parts.push(id + ":-"); continue; }
    parts.push(id + ":" + t.state + "/q" + queueLength(t.queue) + "/" + t.task + "/" +
               (t.task.v1 == null ? "_" : typeof t.task.v1 === "object" ? "P" + t.task.v1.a1 : t.task.v1));
  }
  return s.queueCount + "," + s.holdCount + "," + s.currentId + " [" + parts.join(" ") + "]";
}
function freshScheduler(count) {
  var scheduler = new Scheduler();
  scheduler.addIdleTask(ID_IDLE, 0, null, count);
  var queue = new Packet(null, ID_WORKER, KIND_WORK);
  queue = new Packet(queue, ID_WORKER, KIND_WORK);
  scheduler.addWorkerTask(ID_WORKER, 1000, queue);
  queue = new Packet(null, ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_A, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_A, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_A, 2000, queue);
  queue = new Packet(null, ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_B, KIND_DEVICE);
  queue = new Packet(queue, ID_DEVICE_B, KIND_DEVICE);
  scheduler.addHandlerTask(ID_HANDLER_B, 3000, queue);
  scheduler.addDeviceTask(ID_DEVICE_A, 4000, null);
  scheduler.addDeviceTask(ID_DEVICE_B, 5000, null);
  return scheduler;
}
COUNT = 1000;
var warm = {};
warm[runRichards()] = 1;
COUNT = 10;
for (var w = 0; w < 115; w++) { var r = runRichards(); warm[r] = (warm[r] || 0) + 1; }
console.log("warm", JSON.stringify(warm));
"""

PROG_RICHARDS_CANONICAL = RICHARDS + r"""
var counts = [];
var sizes = [1, 2, 3, 7, 50, 100];
for (var k = 0; k < sizes.length; k++) {
  var s = freshScheduler(sizes[k]);
  s.schedule();
  counts.push(sizes[k] + "=>" + s.queueCount + "/" + s.holdCount);
}
console.log("counts", counts.join(" "));
var s2 = freshScheduler(37);
console.log("before", describe(s2));
console.log("list", String(s2.list), String(s2.list.link.link));
s2.schedule();
console.log("after", describe(s2));
var p = s2.blocks[ID_HANDLER_A].queue;
console.log("packet", String(new Packet(null, 0, 0)), p == null ? "none" : p.a2.join("|"));
for (var w2 = 0; w2 < 30; w2++) runRichards();
console.log("again", runRichards());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_richards_canonical(run, tier):
    """CATCHES: a JIT/bytecode scheduler specialisation that computes different queue/hold counts, task states, packet payloads or final scheduler graph than the reference interpreter for the classic Richards benchmark at several idle counts."""
    check_prog(run, tier, PROG_RICHARDS_CANONICAL, "richards_canonical")


PROG_RICHARDS_METHODS = RICHARDS + r"""
var hits = {};
function wrap(proto, name, label) {
  var orig = proto[name];
  proto[name] = function () { hits[label] = (hits[label] || 0) + 1; return orig.apply(this, arguments); };
  return function () { proto[name] = orig; };
}
var targets = [
  [Scheduler.prototype, "holdCurrent", "hold"], [Scheduler.prototype, "release", "release"],
  [Scheduler.prototype, "queue", "queue"], [Scheduler.prototype, "suspendCurrent", "suspend"],
  [TaskControlBlock.prototype, "markAsHeld", "markHeld"], [TaskControlBlock.prototype, "isHeldOrSuspended", "isHeld"],
  [TaskControlBlock.prototype, "run", "tcbRun"], [TaskControlBlock.prototype, "checkPriorityAdd", "cpa"],
  [DeviceTask.prototype, "run", "device"], [WorkerTask.prototype, "run", "worker"],
  [HandlerTask.prototype, "run", "handler"], [IdleTask.prototype, "run", "idle"],
  [Packet.prototype, "addTo", "addTo"], [TaskControlBlock.prototype, "markAsNotHeld", "notHeld"],
  [TaskControlBlock.prototype, "markAsRunnable", "runnable"], [TaskControlBlock.prototype, "markAsSuspended", "markSusp"],
];
for (var t = 0; t < targets.length; t++) {
  hits = {};
  var restore = wrap(targets[t][0], targets[t][1], targets[t][2]);
  var res = runRichards();
  restore();
  var again = runRichards();
  console.log(targets[t][2], res, again, JSON.stringify(hits));
}
var origRun = DeviceTask.prototype.run;
var calls = 0;
DeviceTask.prototype.run = function (packet) {
  calls++;
  if (packet != null && calls % 3 === 0) { this.v1 = packet; return this.scheduler.suspendCurrent(); }
  return origRun.call(this, packet);
};
console.log("deviceVariant", runRichards(), calls);
DeviceTask.prototype.run = origRun;
var origHold = Scheduler.prototype.holdCurrent;
Scheduler.prototype.holdCurrent = function () { this.holdCount += 0.5; this.currentTcb.markAsHeld(); return this.currentTcb.link; };
console.log("halfHold", runRichards());
Scheduler.prototype.holdCurrent = origHold;
var origWorker = WorkerTask.prototype.run;
WorkerTask.prototype.run = function (packet) {
  if (packet == null) return this.scheduler.suspendCurrent();
  this.v1 = this.v1 == ID_HANDLER_A ? ID_HANDLER_B : ID_HANDLER_A;
  packet.id = this.v1;
  packet.a1 = 0;
  return this.scheduler.queue(packet);
};
var nf = freshScheduler(60);
nf.schedule();
console.log("workerNoFill", describe(nf));
WorkerTask.prototype.run = origWorker;
console.log("final", runRichards(), runRichards());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_richards_method_replacement(run, tier):
    """CATCHES: scheduler fast paths that keep calling the warmed-up prototype methods after Scheduler/TaskControlBlock/task/Packet methods are replaced (wrappers must observe every call exactly once), or that fail to resume the generic path and then re-specialise after restoration."""
    check_prog(run, tier, PROG_RICHARDS_METHODS, "richards_methods")


PROG_RICHARDS_STATE = RICHARDS + r"""
DATA_SIZE = 2;
console.log("data2", runRichards(), runRichards());
DATA_SIZE = 6;
console.log("data6", runRichards());
DATA_SIZE = 4;
var s = freshScheduler(30);
s.holdCount = 1.25;
s.queueCount = 2147483646;
s.schedule();
console.log("ieee", s.holdCount, s.queueCount);
s = freshScheduler(20);
s.blocks[ID_HANDLER_A].queue.a2 = new Int8Array(DATA_SIZE);
s.blocks[ID_WORKER].queue.a2 = { length: 4 };
s.schedule();
console.log("a2kinds", describe(s));
s = freshScheduler(25);
var seen = 0;
Object.defineProperty(Array.prototype, "1", { set: function (v) { seen += v; }, configurable: true });
s.schedule();
delete Array.prototype[1];
console.log("protoSetter", seen, describe(s));
s = freshScheduler(25);
var tcb = s.blocks[ID_DEVICE_A];
var st = tcb.state, stateReads = 0;
Object.defineProperty(tcb, "state", { get: function () { stateReads++; return st; }, set: function (v) { st = v; }, configurable: true });
s.schedule();
console.log("stateAccessor", stateReads > 0, st, describe(s));
s = freshScheduler(25);
var other = Object.create(s);
s.blocks[ID_DEVICE_B].task.scheduler = other;
s.blocks[ID_WORKER].task.scheduler = other;
s.schedule();
console.log("foreign", describe(s), "|", other.queueCount, other.holdCount, Object.keys(other).join("+"));
s = freshScheduler(15);
s.blocks[ID_HANDLER_B].queue.link = undefined;
s.blocks[ID_WORKER].task.v2 = 25.5;
s.blocks[ID_IDLE].task.v1 = 0x7fffffff;
s.schedule();
console.log("oddValues", describe(s), s.blocks[ID_WORKER].task.v2);
var savedHeld = STATE_HELD;
STATE_NOT_HELD = ~0;
s = freshScheduler(10);
s.schedule();
console.log("notHeld", describe(s));
STATE_NOT_HELD = ~STATE_HELD;
ID_DEVICE_A = 5;
console.log("idSwap", runRichards());
ID_DEVICE_A = 4;
KIND_WORK = 7;
console.log("kind", runRichards());
KIND_WORK = 1;
var calls = 0;
var origQueue = Scheduler.prototype.queue;
Scheduler.prototype.queue = function (p) {
  if (++calls === 150) throw new Error("queue failure at " + this.queueCount);
  return origQueue.call(this, p);
};
s = freshScheduler(1000);
try { s.schedule(); } catch (e) { console.log("thrown", e.message, describe(s)); }
Scheduler.prototype.queue = origQueue;
var badTask = freshScheduler(40);
badTask.blocks[ID_HANDLER_B].task.run = function () { throw new TypeError("handler B exploded"); };
try { badTask.schedule(); } catch (e) { console.log("taskThrow", e.name, e.message, badTask.currentId, badTask.queueCount); }
var nullBlocks = freshScheduler(30);
nullBlocks.blocks[ID_HANDLER_A] = null;
nullBlocks.schedule();
console.log("nullBlock", nullBlocks.queueCount, nullBlocks.holdCount);
console.log("restored", runRichards(), runRichards());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_richards_state_mutation(run, tier):
    """CATCHES: scheduler regions that bake in global constants (DATA_SIZE, IDs, state masks), assume int32 counters, plain packet arrays, data-property TCB state or same-scheduler task graphs, or mishandle exceptions thrown mid-schedule; results must match the generic tree-walker exactly."""
    check_prog(run, tier, PROG_RICHARDS_STATE, "richards_state")


PROG_NUMERIC_REGIONS = r"""
function calc(n) {
  var total = 0;
  for (var i = 0; i < n; i++) {
    if (i < 8) { total += 2; continue; }
    if (i > 3000) break;
    if (i < 1000) total -= 1; else total += 3;
  }
  return total * 10000 + i;
}
function nested(n) {
  var sum = 0;
  for (var i = 0; i < n; i++) {
    for (var j = 0; j < n; j++) {
      if (j < 20) { sum += i; continue; }
      if (i < 20) { sum -= j; continue; }
      sum += 2;
    }
  }
  return sum;
}
function bottom(n) {
  var i = 0, sum = 0;
  do { if (i < 1200) sum += 2; else sum--; i++; } while (i < n);
  return sum;
}
function specials(n) {
  var a = 0, b = 1, c = -0, d = 0;
  for (var i = 0; i < n; i++) {
    a = a + 0.5;
    if (i === 100) b = Infinity;
    if (i === 200) c = NaN;
    if (b > 1e308) d = d - 1; else d = d + 1;
    if (c !== c) d = d + 0.25;
  }
  return [a, b, c, d, Object.is(-0 + 0, 0)].join(",");
}
function arrays(xs, ys, n) {
  var s = 0, t = 0;
  for (var k = 0; k < n; k++) {
    for (var i = 0; i < xs.length; i++) {
      var v = xs[i];
      if (v > 2) s = s + v * ys[i % ys.length]; else t = t - v;
    }
  }
  return s + "/" + t;
}
function badIndex(xs, n) {
  var s = 0, idx = 0;
  for (var i = 0; i < n; i++) {
    idx = i * 0.5;
    s = s + (xs[idx] === undefined ? 1000 : xs[idx]);
  }
  return s;
}
function oobIndex(xs, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { var v = xs[i]; if (v === undefined) s = s + 7; else s = s + v; }
  return s;
}
function Box(w) { this.w = w; this.scale = 1.5; this.items = [1.5, 2.5, 3.5, 4.5]; }
Box.prototype.total = function (n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (i % 3 === 0) s = s + this.w * this.scale; else s = s - 1; }
  return s;
};
Box.prototype.lenLoop = function () {
  var s = 0, a = this.items;
  for (var i = 0; i < a.length; i++) s = s + a[i];
  return s;
};
function outerInputs(limit, factor) {
  var bound = limit, f = factor;
  function inner() {
    var s = 0;
    for (var i = 0; i < bound; i++) { if (i & 1) s = s + f; else s = s - 0.5; }
    return s;
  }
  var r1 = inner();
  bound = limit * 2; f = factor + 1;
  var r2 = inner();
  f = "3";
  var r3 = inner();
  return [r1, r2, r3].join(",");
}
function coercing(n) {
  var calls = 0;
  var o = { valueOf: function () { calls++; return 2; } };
  var s = 0, x = 1;
  for (var i = 0; i < n; i++) { x = x * 1.0001; if (i === n - 3) x = o; s = s + x; }
  return s.toFixed(6) + ":" + calls;
}
function bigUpd(n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (typeof s === "bigint") s = s + 2n; else s = s + 1; if (i === n >> 1) s = BigInt(s); }
  return typeof s + ":" + s;
}
function getterArray() {
  var xs = [1, 2, 3, 4, 5, 6, 7, 8];
  var hits = 0;
  var out = [];
  for (var r = 0; r < 4; r++) {
    if (r === 2) Object.defineProperty(xs, 3, { get: function () { hits++; return 100; } });
    var s = 0;
    for (var i = 0; i < xs.length; i++) s = s + xs[i];
    out.push(s);
  }
  return out.join(",") + ":" + hits;
}
function receiverSwap() {
  var a = [1, 2, 3], b = [10, 20, 30, 40], s = 0;
  var xs = a;
  for (var i = 0; i < 6; i++) { if (i === 2) xs = b; var v = xs[i % 3]; s = s + v; }
  var ta = new Float64Array([0.5, 1.5]), pr = new Proxy([5, 6], {});
  var t = 0;
  for (var k = 0; k < 3; k++) { var arr = k === 0 ? ta : k === 1 ? pr : [1, , 3]; for (var j = 0; j < 3; j++) { var e = arr[j]; t = t + (e === undefined ? 100 : e); } }
  return s + "," + t;
}
function longRun(n) {
  var a = 0, b = 0;
  for (var i = 0; i < n; i++) { a = (a + i * 3) % 1000003; if (a > 500000) b = b + 1; else b = b - 1; }
  return a + "," + b;
}
function mixedInts(n) {
  var x = 0, y = 2147483647, z = 0;
  for (var i = 0; i < n; i++) { x = x + 1073741824; y = y + 1; z = (z + i) | 0; if (x > 1e10) x = -x; }
  return [x, y, z].join(",");
}
function maxOf(a, n) { var m = -1; for (var i = 0; i < n; i++) { var v = a[i]; if (v > m) m = v; } return m; }
function cmpArr(a, b, n) { for (var i = n - 1; i >= 0; i--) { if (a[i] != b[i]) return a[i] - b[i]; } return 0; }
function sumLen(a) { var s = 0; for (var i = 0; i < a.length; i++) { if (a[i] > 0) s += a[i]; else s -= 1; } return s; }
function arrayReads() {
  var a = [], b = [];
  for (var i = 0; i < 300; i++) { a.push(i * 1.5); b.push(i * 1.5); }
  var out = [maxOf(a, 300), cmpArr(a, b, 300), sumLen(a)];
  b[3] = 0;
  out.push(cmpArr(a, b, 300), maxOf(a, 300.5), maxOf(a, 305), maxOf(b, -1));
  var holes = a.slice(); delete holes[299];
  out.push(maxOf(holes, 300), sumLen(holes));
  var g = a.slice(); Object.defineProperty(g, 7, { get: function () { return 1e6; } });
  out.push(maxOf(g, 300), sumLen(g));
  out.push(maxOf(new Float64Array([3, 9, 1]), 3), maxOf("98765", 5), maxOf({ 0: 4, 1: 44, length: 2 }, 2));
  var mixed = a.slice(); mixed[297] = "999"; mixed[298] = { valueOf: function () { return 5000; } };
  out.push(maxOf(mixed, 300), sumLen(mixed), cmpArr(mixed, a, 300));
  var neg = [-0, 0.5]; out.push(maxOf(neg, 2), cmpArr([NaN], [NaN], 1), cmpArr([1, 2], [1, 2], 2));
  return out.join(",");
}
var xs = [1.5, 2.5, 3.5, 4.5, -1, 0, 7, 8.25];
var ys = [2, 0.5, -1];
console.log("arrayReads", arrayReads());
console.log("calc", calc(5000), calc(4));
console.log("nested", nested(40), nested(3));
console.log("bottom", bottom(2000), bottom(1));
console.log("specials", specials(5000));
console.log("arrays", arrays(xs, ys, 3000));
console.log("badIndex", badIndex(xs, 16));
console.log("oobIndex", oobIndex(xs, 12));
var box = new Box(3);
console.log("box", box.total(3000), box.lenLoop());
box.w = 0.25; box.items.push(10);
console.log("box2", box.total(3000), box.lenLoop());
Object.defineProperty(box, "scale", { get: function () { return -2; } });
console.log("box3", box.total(3000));
console.log("outerInputs", outerInputs(3000, 2));
console.log("coercing", coercing(3000));
console.log("bigUpd", bigUpd(3000));
console.log("getterArray", getterArray());
console.log("receiverSwap", receiverSwap());
console.log("longRun", longRun(100000));
console.log("mixedInts", mixedInts(5000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_numeric_region_loops(run, tier):
    """CATCHES: register-resident numeric loop regions that lose locals on continue/break/bounded-backedge exits, ignore Infinity/NaN/-0, read array elements past a fractional/out-of-bounds index or after a getter is installed, keep stale enclosing-binding or this-field inputs, or skip valueOf coercion and BigInt transitions."""
    check_prog(run, tier, PROG_NUMERIC_REGIONS, "numeric_regions")


# A port of the classic V8 "NavierStokes" fluid solver kernel (lin_solve/advect/project over flat
# arrays indexed through closure-captured width/height/rowSize), at a reduced 40x40 resolution.
PROG_NAVIER = r"""function FluidField(canvas) {
    function addFields(x, s, dt)
    {
        for (var i=0; i<size ; i++ ) x[i] += dt*s[i];
    }

    function set_bnd(b, x)
    {
        if (b===1) {
            for (var i = 1; i <= width; i++) {
                x[i] =  x[i + rowSize];
                x[i + (height+1) *rowSize] = x[i + height * rowSize];
            }

            for (var j = 1; i <= height; i++) {
                x[j * rowSize] = -x[1 + j * rowSize];
                x[(width + 1) + j * rowSize] = -x[width + j * rowSize];
            }
        } else if (b === 2) {
            for (var i = 1; i <= width; i++) {
                x[i] = -x[i + rowSize];
                x[i + (height + 1) * rowSize] = -x[i + height * rowSize];
            }

            for (var j = 1; j <= height; j++) {
                x[j * rowSize] =  x[1 + j * rowSize];
                x[(width + 1) + j * rowSize] =  x[width + j * rowSize];
            }
        } else {
            for (var i = 1; i <= width; i++) {
                x[i] =  x[i + rowSize];
                x[i + (height + 1) * rowSize] = x[i + height * rowSize];
            }

            for (var j = 1; j <= height; j++) {
                x[j * rowSize] =  x[1 + j * rowSize];
                x[(width + 1) + j * rowSize] =  x[width + j * rowSize];
            }
        }
        var maxEdge = (height + 1) * rowSize;
        x[0]                 = 0.5 * (x[1] + x[rowSize]);
        x[maxEdge]           = 0.5 * (x[1 + maxEdge] + x[height * rowSize]);
        x[(width+1)]         = 0.5 * (x[width] + x[(width + 1) + rowSize]);
        x[(width+1)+maxEdge] = 0.5 * (x[width + maxEdge] + x[(width + 1) + height * rowSize]);
    }

    function lin_solve(b, x, x0, a, c)
    {
        if (a === 0 && c === 1) {
            for (var j=1 ; j<=height; j++) {
                var currentRow = j * rowSize;
                ++currentRow;
                for (var i = 0; i < width; i++) {
                    x[currentRow] = x0[currentRow];
                    ++currentRow;
                }
            }
            set_bnd(b, x);
        } else {
            var invC = 1 / c;
            for (var k=0 ; k<iterations; k++) {
                for (var j=1 ; j<=height; j++) {
                    var lastRow = (j - 1) * rowSize;
                    var currentRow = j * rowSize;
                    var nextRow = (j + 1) * rowSize;
                    var lastX = x[currentRow];
                    ++currentRow;
                    for (var i=1; i<=width; i++)
                        lastX = x[currentRow] = (x0[currentRow] + a*(lastX+x[++currentRow]+x[++lastRow]+x[++nextRow])) * invC;
                }
                set_bnd(b, x);
            }
        }
    }

    function diffuse(b, x, x0, dt)
    {
        var a = 0;
        lin_solve(b, x, x0, a, 1 + 4*a);
    }

    function lin_solve2(x, x0, y, y0, a, c)
    {
        if (a === 0 && c === 1) {
            for (var j=1 ; j <= height; j++) {
                var currentRow = j * rowSize;
                ++currentRow;
                for (var i = 0; i < width; i++) {
                    x[currentRow] = x0[currentRow];
                    y[currentRow] = y0[currentRow];
                    ++currentRow;
                }
            }
            set_bnd(1, x);
            set_bnd(2, y);
        } else {
            var invC = 1/c;
            for (var k=0 ; k<iterations; k++) {
                for (var j=1 ; j <= height; j++) {
                    var lastRow = (j - 1) * rowSize;
                    var currentRow = j * rowSize;
                    var nextRow = (j + 1) * rowSize;
                    var lastX = x[currentRow];
                    var lastY = y[currentRow];
                    ++currentRow;
                    for (var i = 1; i <= width; i++) {
                        lastX = x[currentRow] = (x0[currentRow] + a * (lastX + x[currentRow] + x[lastRow] + x[nextRow])) * invC;
                        lastY = y[currentRow] = (y0[currentRow] + a * (lastY + y[++currentRow] + y[++lastRow] + y[++nextRow])) * invC;
                    }
                }
                set_bnd(1, x);
                set_bnd(2, y);
            }
        }
    }

    function diffuse2(x, x0, y, y0, dt)
    {
        var a = 0;
        lin_solve2(x, x0, y, y0, a, 1 + 4 * a);
    }

    function advect(b, d, d0, u, v, dt)
    {
        var Wdt0 = dt * width;
        var Hdt0 = dt * height;
        var Wp5 = width + 0.5;
        var Hp5 = height + 0.5;
        for (var j = 1; j<= height; j++) {
            var pos = j * rowSize;
            for (var i = 1; i <= width; i++) {
                var x = i - Wdt0 * u[++pos];
                var y = j - Hdt0 * v[pos];
                if (x < 0.5)
                    x = 0.5;
                else if (x > Wp5)
                    x = Wp5;
                var i0 = x | 0;
                var i1 = i0 + 1;
                if (y < 0.5)
                    y = 0.5;
                else if (y > Hp5)
                    y = Hp5;
                var j0 = y | 0;
                var j1 = j0 + 1;
                var s1 = x - i0;
                var s0 = 1 - s1;
                var t1 = y - j0;
                var t0 = 1 - t1;
                var row1 = j0 * rowSize;
                var row2 = j1 * rowSize;
                d[pos] = s0 * (t0 * d0[i0 + row1] + t1 * d0[i0 + row2]) + s1 * (t0 * d0[i1 + row1] + t1 * d0[i1 + row2]);
            }
        }
        set_bnd(b, d);
    }

    function project(u, v, p, div)
    {
        var h = -0.5 / Math.sqrt(width * height);
        for (var j = 1 ; j <= height; j++ ) {
            var row = j * rowSize;
            var previousRow = (j - 1) * rowSize;
            var prevValue = row - 1;
            var currentRow = row;
            var nextValue = row + 1;
            var nextRow = (j + 1) * rowSize;
            for (var i = 1; i <= width; i++ ) {
                div[++currentRow] = h * (u[++nextValue] - u[++prevValue] + v[++nextRow] - v[++previousRow]);
                p[currentRow] = 0;
            }
        }
        set_bnd(0, div);
        set_bnd(0, p);

        lin_solve(0, p, div, 1, 4 );
        var wScale = 0.5 * width;
        var hScale = 0.5 * height;
        for (var j = 1; j<= height; j++ ) {
            var prevPos = j * rowSize - 1;
            var currentPos = j * rowSize;
            var nextPos = j * rowSize + 1;
            var prevRow = (j - 1) * rowSize;
            var currentRow = j * rowSize;
            var nextRow = (j + 1) * rowSize;

            for (var i = 1; i<= width; i++) {
                u[++currentPos] -= wScale * (p[++nextPos] - p[++prevPos]);
                v[currentPos]   -= hScale * (p[++nextRow] - p[++prevRow]);
            }
        }
        set_bnd(1, u);
        set_bnd(2, v);
    }

    function dens_step(x, x0, u, v, dt)
    {
        addFields(x, x0, dt);
        diffuse(0, x0, x, dt );
        advect(0, x, x0, u, v, dt );
    }

    function vel_step(u, v, u0, v0, dt)
    {
        addFields(u, u0, dt );
        addFields(v, v0, dt );
        var temp = u0; u0 = u; u = temp;
        var temp = v0; v0 = v; v = temp;
        diffuse2(u,u0,v,v0, dt);
        project(u, v, u0, v0);
        var temp = u0; u0 = u; u = temp;
        var temp = v0; v0 = v; v = temp;
        advect(1, u, u0, u0, v0, dt);
        advect(2, v, v0, u0, v0, dt);
        project(u, v, u0, v0 );
    }
    var uiCallback = function(d,u,v) {};

    function Field(dens, u, v) {
        this.setDensity = function(x, y, d) {
             dens[(x + 1) + (y + 1) * rowSize] = d;
        }
        this.getDensity = function(x, y) {
             return dens[(x + 1) + (y + 1) * rowSize];
        }
        this.setVelocity = function(x, y, xv, yv) {
             u[(x + 1) + (y + 1) * rowSize] = xv;
             v[(x + 1) + (y + 1) * rowSize] = yv;
        }
        this.getXVelocity = function(x, y) {
             return u[(x + 1) + (y + 1) * rowSize];
        }
        this.getYVelocity = function(x, y) {
             return v[(x + 1) + (y + 1) * rowSize];
        }
        this.width = function() { return width; }
        this.height = function() { return height; }
    }
    function queryUI(d, u, v)
    {
        for (var i = 0; i < size; i++)
            u[i] = v[i] = d[i] = 0.0;
        uiCallback(new Field(d, u, v));
    }

    this.update = function () {
        queryUI(dens_prev, u_prev, v_prev);
        vel_step(u, v, u_prev, v_prev, dt);
        dens_step(dens, dens_prev, u, v, dt);
        displayFunc(new Field(dens, u, v));
    }
    this.setDisplayFunction = function(func) {
        displayFunc = func;
    }

    this.iterations = function() { return iterations; }
    this.setIterations = function(iters)
    {
        if (iters > 0 && iters <= 100)
           iterations = iters;
    }
    this.setUICallback = function(callback) {
        uiCallback = callback;
    }
    var iterations = 10;
    var visc = 0.5;
    var dt = 0.1;
    var dens;
    var dens_prev;
    var u;
    var u_prev;
    var v;
    var v_prev;
    var width;
    var height;
    var rowSize;
    var size;
    var displayFunc;
    function reset()
    {
        rowSize = width + 2;
        size = (width+2)*(height+2);
        dens = [];
        dens_prev = [];
        u = [];
        u_prev = [];
        v = [];
        v_prev = [];
        for (var i = 0; i < size; i++) {
            dens_prev.push(0.5); u_prev.push(0.5); v_prev.push(0.5); dens.push(0.5); u.push(0.5); v.push(0.5);
        }
        for (var i = 0; i < size; i++)
            dens_prev[i] = u_prev[i] = v_prev[i] = dens[i] = u[i] = v[i] = 0;
    }
    this.getDens = function()
    {
        return dens;
    }
    this.reset = reset;
    this.setResolution = function (hRes, wRes)
    {
        var res = wRes * hRes;
        if (res > 0 && res < 1000000 && (wRes != width || hRes != height)) {
            width = wRes;
            height = hRes;
            reset();
            return true;
        }
        return false;
    }
    this.setResolution(64, 64);
}

var solver = null;
var nsFrameCounter = 0;
var framesTillAddingPoints = 0;
var framesBetweenAddingPoints = 5;
var RES = 24;
function prepareFrame(field)
{
    if (framesTillAddingPoints == 0) {
        addPoints(field);
        framesTillAddingPoints = framesBetweenAddingPoints;
        framesBetweenAddingPoints++;
    } else {
        framesTillAddingPoints--;
    }
}
function addPoints(field) {
    var n = RES >> 1;
    for (var i = 1; i <= n; i++) {
        field.setVelocity(i, i, n, n);
        field.setDensity(i, i, 5);
        field.setVelocity(i, n - i, -n, -n);
        field.setDensity(i, n - i, 20);
        field.setVelocity(RES - i, n + i - 1, -n, -n);
        field.setDensity(RES - i, n + i - 1, 30);
    }
}
var last = null;
solver = new FluidField(null);
solver.setResolution(RES, RES);
solver.setIterations(6);
solver.setDisplayFunction(function (f) { last = f; });
solver.setUICallback(prepareFrame);
solver.reset();
var sums = [];
for (var frame = 0; frame < 9; frame++) {
  solver.update();
  var d = solver.getDens(), s = 0, cs = 0;
  for (var i = 0; i < d.length; i++) { s += d[i]; cs += ~~(d[i] * 10); }
  sums.push(frame + ":" + s.toFixed(10) + ":" + cs);
}
console.log(sums.join("\n"));
var probe = [];
for (var y = 0; y < RES; y += 7) for (var x = 0; x < RES; x += 9) probe.push(last.getDensity(x, y).toFixed(8) + "/" + last.getXVelocity(x, y).toFixed(8) + "/" + last.getYVelocity(x, y).toFixed(8));
console.log(probe.join(" "));
console.log(last.width(), last.height(), solver.iterations(), solver.setResolution(RES, RES), solver.setResolution(8, 8));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_navier_stokes_kernel(run, tier):
    """CATCHES: numeric array-loop specialisations (pre-increment index chains, compound element updates, closure-captured loop bounds, |0 truncation and clamping branches) that change floating-point results of the NavierStokes solver relative to the interpreter."""
    check_prog(run, tier, PROG_NAVIER, "navier")


# A port of the classic V8 "DeltaBlue" one-way constraint solver: prototype inheritance through
# superConstructor.call, polymorphic constraint methods, OrderedCollection churn.
PROG_DELTABLUE = r"""function alert(s) { throw new Error(s); }
Object.prototype.inheritsFrom = function (shuper) {
  function Inheriter() { }
  Inheriter.prototype = shuper.prototype;
  this.prototype = new Inheriter();
  this.superConstructor = shuper;
}

function OrderedCollection() {
  this.elms = new Array();
}

OrderedCollection.prototype.add = function (elm) {
  this.elms.push(elm);
}

OrderedCollection.prototype.at = function (index) {
  return this.elms[index];
}

OrderedCollection.prototype.size = function () {
  return this.elms.length;
}

OrderedCollection.prototype.removeFirst = function () {
  return this.elms.pop();
}

OrderedCollection.prototype.remove = function (elm) {
  var index = 0, skipped = 0;
  for (var i = 0; i < this.elms.length; i++) {
    var value = this.elms[i];
    if (value != elm) {
      this.elms[index] = value;
      index++;
    } else {
      skipped++;
    }
  }
  for (var i = 0; i < skipped; i++)
    this.elms.pop();
}

function Strength(strengthValue, name) {
  this.strengthValue = strengthValue;
  this.name = name;
}

Strength.stronger = function (s1, s2) {
  return s1.strengthValue < s2.strengthValue;
}

Strength.weaker = function (s1, s2) {
  return s1.strengthValue > s2.strengthValue;
}

Strength.weakestOf = function (s1, s2) {
  return this.weaker(s1, s2) ? s1 : s2;
}

Strength.strongest = function (s1, s2) {
  return this.stronger(s1, s2) ? s1 : s2;
}

Strength.prototype.nextWeaker = function () {
  switch (this.strengthValue) {
    case 0: return Strength.WEAKEST;
    case 1: return Strength.WEAK_DEFAULT;
    case 2: return Strength.NORMAL;
    case 3: return Strength.STRONG_DEFAULT;
    case 4: return Strength.PREFERRED;
    case 5: return Strength.REQUIRED;
  }
}

Strength.REQUIRED        = new Strength(0, "required");
Strength.STONG_PREFERRED = new Strength(1, "strongPreferred");
Strength.PREFERRED       = new Strength(2, "preferred");
Strength.STRONG_DEFAULT  = new Strength(3, "strongDefault");
Strength.NORMAL          = new Strength(4, "normal");
Strength.WEAK_DEFAULT    = new Strength(5, "weakDefault");
Strength.WEAKEST         = new Strength(6, "weakest");

function Constraint(strength) {
  this.strength = strength;
}

Constraint.prototype.addConstraint = function () {
  this.addToGraph();
  planner.incrementalAdd(this);
}

Constraint.prototype.satisfy = function (mark) {
  this.chooseMethod(mark);
  if (!this.isSatisfied()) {
    if (this.strength == Strength.REQUIRED)
      alert("Could not satisfy a required constraint!");
    return null;
  }
  this.markInputs(mark);
  var out = this.output();
  var overridden = out.determinedBy;
  if (overridden != null) overridden.markUnsatisfied();
  out.determinedBy = this;
  if (!planner.addPropagate(this, mark))
    alert("Cycle encountered");
  out.mark = mark;
  return overridden;
}

Constraint.prototype.destroyConstraint = function () {
  if (this.isSatisfied()) planner.incrementalRemove(this);
  else this.removeFromGraph();
}

Constraint.prototype.isInput = function () {
  return false;
}

function UnaryConstraint(v, strength) {
  UnaryConstraint.superConstructor.call(this, strength);
  this.myOutput = v;
  this.satisfied = false;
  this.addConstraint();
}

UnaryConstraint.inheritsFrom(Constraint);

UnaryConstraint.prototype.addToGraph = function () {
  this.myOutput.addConstraint(this);
  this.satisfied = false;
}

UnaryConstraint.prototype.chooseMethod = function (mark) {
  this.satisfied = (this.myOutput.mark != mark)
    && Strength.stronger(this.strength, this.myOutput.walkStrength);
}

UnaryConstraint.prototype.isSatisfied = function () {
  return this.satisfied;
}

UnaryConstraint.prototype.markInputs = function (mark) {
  // has no inputs
}

UnaryConstraint.prototype.output = function () {
  return this.myOutput;
}

UnaryConstraint.prototype.recalculate = function () {
  this.myOutput.walkStrength = this.strength;
  this.myOutput.stay = !this.isInput();
  if (this.myOutput.stay) this.execute(); // Stay optimization
}

UnaryConstraint.prototype.markUnsatisfied = function () {
  this.satisfied = false;
}

UnaryConstraint.prototype.inputsKnown = function () {
  return true;
}

UnaryConstraint.prototype.removeFromGraph = function () {
  if (this.myOutput != null) this.myOutput.removeConstraint(this);
  this.satisfied = false;
}

function StayConstraint(v, str) {
  StayConstraint.superConstructor.call(this, v, str);
}

StayConstraint.inheritsFrom(UnaryConstraint);

StayConstraint.prototype.execute = function () {
  // Stay constraints do nothing
}

function EditConstraint(v, str) {
  EditConstraint.superConstructor.call(this, v, str);
}

EditConstraint.inheritsFrom(UnaryConstraint);

EditConstraint.prototype.isInput = function () {
  return true;
}

EditConstraint.prototype.execute = function () {
  // Edit constraints do nothing
}

var Direction = new Object();
Direction.NONE     = 0;
Direction.FORWARD  = 1;
Direction.BACKWARD = -1;

function BinaryConstraint(var1, var2, strength) {
  BinaryConstraint.superConstructor.call(this, strength);
  this.v1 = var1;
  this.v2 = var2;
  this.direction = Direction.NONE;
  this.addConstraint();
}

BinaryConstraint.inheritsFrom(Constraint);

BinaryConstraint.prototype.chooseMethod = function (mark) {
  if (this.v1.mark == mark) {
    this.direction = (this.v2.mark != mark && Strength.stronger(this.strength, this.v2.walkStrength))
      ? Direction.FORWARD
      : Direction.NONE;
  }
  if (this.v2.mark == mark) {
    this.direction = (this.v1.mark != mark && Strength.stronger(this.strength, this.v1.walkStrength))
      ? Direction.BACKWARD
      : Direction.NONE;
  }
  if (Strength.weaker(this.v1.walkStrength, this.v2.walkStrength)) {
    this.direction = Strength.stronger(this.strength, this.v1.walkStrength)
      ? Direction.BACKWARD
      : Direction.NONE;
  } else {
    this.direction = Strength.stronger(this.strength, this.v2.walkStrength)
      ? Direction.FORWARD
      : Direction.BACKWARD
  }
}

BinaryConstraint.prototype.addToGraph = function () {
  this.v1.addConstraint(this);
  this.v2.addConstraint(this);
  this.direction = Direction.NONE;
}

BinaryConstraint.prototype.isSatisfied = function () {
  return this.direction != Direction.NONE;
}

BinaryConstraint.prototype.markInputs = function (mark) {
  this.input().mark = mark;
}

BinaryConstraint.prototype.input = function () {
  return (this.direction == Direction.FORWARD) ? this.v1 : this.v2;
}

BinaryConstraint.prototype.output = function () {
  return (this.direction == Direction.FORWARD) ? this.v2 : this.v1;
}

BinaryConstraint.prototype.recalculate = function () {
  var ihn = this.input(), out = this.output();
  out.walkStrength = Strength.weakestOf(this.strength, ihn.walkStrength);
  out.stay = ihn.stay;
  if (out.stay) this.execute();
}

BinaryConstraint.prototype.markUnsatisfied = function () {
  this.direction = Direction.NONE;
}

BinaryConstraint.prototype.inputsKnown = function (mark) {
  var i = this.input();
  return i.mark == mark || i.stay || i.determinedBy == null;
}

BinaryConstraint.prototype.removeFromGraph = function () {
  if (this.v1 != null) this.v1.removeConstraint(this);
  if (this.v2 != null) this.v2.removeConstraint(this);
  this.direction = Direction.NONE;
}

function ScaleConstraint(src, scale, offset, dest, strength) {
  this.direction = Direction.NONE;
  this.scale = scale;
  this.offset = offset;
  ScaleConstraint.superConstructor.call(this, src, dest, strength);
}

ScaleConstraint.inheritsFrom(BinaryConstraint);

ScaleConstraint.prototype.addToGraph = function () {
  ScaleConstraint.superConstructor.prototype.addToGraph.call(this);
  this.scale.addConstraint(this);
  this.offset.addConstraint(this);
}

ScaleConstraint.prototype.removeFromGraph = function () {
  ScaleConstraint.superConstructor.prototype.removeFromGraph.call(this);
  if (this.scale != null) this.scale.removeConstraint(this);
  if (this.offset != null) this.offset.removeConstraint(this);
}

ScaleConstraint.prototype.markInputs = function (mark) {
  ScaleConstraint.superConstructor.prototype.markInputs.call(this, mark);
  this.scale.mark = this.offset.mark = mark;
}

ScaleConstraint.prototype.execute = function () {
  if (this.direction == Direction.FORWARD) {
    this.v2.value = this.v1.value * this.scale.value + this.offset.value;
  } else {
    this.v1.value = (this.v2.value - this.offset.value) / this.scale.value;
  }
}

ScaleConstraint.prototype.recalculate = function () {
  var ihn = this.input(), out = this.output();
  out.walkStrength = Strength.weakestOf(this.strength, ihn.walkStrength);
  out.stay = ihn.stay && this.scale.stay && this.offset.stay;
  if (out.stay) this.execute();
}

function EqualityConstraint(var1, var2, strength) {
  EqualityConstraint.superConstructor.call(this, var1, var2, strength);
}

EqualityConstraint.inheritsFrom(BinaryConstraint);

EqualityConstraint.prototype.execute = function () {
  this.output().value = this.input().value;
}

function Variable(name, initialValue) {
  this.value = initialValue || 0;
  this.constraints = new OrderedCollection();
  this.determinedBy = null;
  this.mark = 0;
  this.walkStrength = Strength.WEAKEST;
  this.stay = true;
  this.name = name;
}

Variable.prototype.addConstraint = function (c) {
  this.constraints.add(c);
}

Variable.prototype.removeConstraint = function (c) {
  this.constraints.remove(c);
  if (this.determinedBy == c) this.determinedBy = null;
}

function Planner() {
  this.currentMark = 0;
}

Planner.prototype.incrementalAdd = function (c) {
  var mark = this.newMark();
  var overridden = c.satisfy(mark);
  while (overridden != null)
    overridden = overridden.satisfy(mark);
}

Planner.prototype.incrementalRemove = function (c) {
  var out = c.output();
  c.markUnsatisfied();
  c.removeFromGraph();
  var unsatisfied = this.removePropagateFrom(out);
  var strength = Strength.REQUIRED;
  do {
    for (var i = 0; i < unsatisfied.size(); i++) {
      var u = unsatisfied.at(i);
      if (u.strength == strength)
        this.incrementalAdd(u);
    }
    strength = strength.nextWeaker();
  } while (strength != Strength.WEAKEST);
}

Planner.prototype.newMark = function () {
  return ++this.currentMark;
}

Planner.prototype.makePlan = function (sources) {
  var mark = this.newMark();
  var plan = new Plan();
  var todo = sources;
  while (todo.size() > 0) {
    var c = todo.removeFirst();
    if (c.output().mark != mark && c.inputsKnown(mark)) {
      plan.addConstraint(c);
      c.output().mark = mark;
      this.addConstraintsConsumingTo(c.output(), todo);
    }
  }
  return plan;
}

Planner.prototype.extractPlanFromConstraints = function (constraints) {
  var sources = new OrderedCollection();
  for (var i = 0; i < constraints.size(); i++) {
    var c = constraints.at(i);
    if (c.isInput() && c.isSatisfied())
      sources.add(c);
  }
  return this.makePlan(sources);
}

Planner.prototype.addPropagate = function (c, mark) {
  var todo = new OrderedCollection();
  todo.add(c);
  while (todo.size() > 0) {
    var d = todo.removeFirst();
    if (d.output().mark == mark) {
      this.incrementalRemove(c);
      return false;
    }
    d.recalculate();
    this.addConstraintsConsumingTo(d.output(), todo);
  }
  return true;
}

Planner.prototype.removePropagateFrom = function (out) {
  out.determinedBy = null;
  out.walkStrength = Strength.WEAKEST;
  out.stay = true;
  var unsatisfied = new OrderedCollection();
  var todo = new OrderedCollection();
  todo.add(out);
  while (todo.size() > 0) {
    var v = todo.removeFirst();
    for (var i = 0; i < v.constraints.size(); i++) {
      var c = v.constraints.at(i);
      if (!c.isSatisfied())
        unsatisfied.add(c);
    }
    var determining = v.determinedBy;
    for (var i = 0; i < v.constraints.size(); i++) {
      var next = v.constraints.at(i);
      if (next != determining && next.isSatisfied()) {
        next.recalculate();
        todo.add(next.output());
      }
    }
  }
  return unsatisfied;
}

Planner.prototype.addConstraintsConsumingTo = function (v, coll) {
  var determining = v.determinedBy;
  var cc = v.constraints;
  for (var i = 0; i < cc.size(); i++) {
    var c = cc.at(i);
    if (c != determining && c.isSatisfied())
      coll.add(c);
  }
}

function Plan() {
  this.v = new OrderedCollection();
}

Plan.prototype.addConstraint = function (c) {
  this.v.add(c);
}

Plan.prototype.size = function () {
  return this.v.size();
}

Plan.prototype.constraintAt = function (index) {
  return this.v.at(index);
}

Plan.prototype.execute = function () {
  for (var i = 0; i < this.size(); i++) {
    var c = this.constraintAt(i);
    c.execute();
  }
}

function chainTest(n) {
  planner = new Planner();
  var prev = null, first = null, last = null;
  for (var i = 0; i <= n; i++) {
    var name = "v" + i;
    var v = new Variable(name);
    if (prev != null)
      new EqualityConstraint(prev, v, Strength.REQUIRED);
    if (i == 0) first = v;
    if (i == n) last = v;
    prev = v;
  }
  new StayConstraint(last, Strength.STRONG_DEFAULT);
  var edit = new EditConstraint(first, Strength.PREFERRED);
  var edits = new OrderedCollection();
  edits.add(edit);
  var plan = planner.extractPlanFromConstraints(edits);
  for (var i = 0; i < 100; i++) {
    first.value = i;
    plan.execute();
    if (last.value != i)
      alert("Chain test failed.");
  }
  return plan.size() + ":" + last.value + ":" + planner.currentMark;
}

function projectionTest(n) {
  planner = new Planner();
  var scale = new Variable("scale", 10);
  var offset = new Variable("offset", 1000);
  var src = null, dst = null;
  var dests = new OrderedCollection();
  for (var i = 0; i < n; i++) {
    src = new Variable("src" + i, i);
    dst = new Variable("dst" + i, i);
    dests.add(dst);
    new StayConstraint(src, Strength.NORMAL);
    new ScaleConstraint(src, scale, offset, dst, Strength.REQUIRED);
  }
  change(src, 17);
  if (dst.value != 1170) alert("Projection 1 failed");
  change(dst, 1050);
  if (src.value != 5) alert("Projection 2 failed");
  change(scale, 5);
  for (var i = 0; i < n - 1; i++) {
    if (dests.at(i).value != i * 5 + 1000)
      alert("Projection 3 failed");
  }
  change(offset, 2000);
  for (var i = 0; i < n - 1; i++) {
    if (dests.at(i).value != i * 5 + 2000)
      alert("Projection 4 failed");
  }
  var sum = 0;
  for (var i = 0; i < n; i++) sum += dests.at(i).value;
  return sum + ":" + src.value + ":" + planner.currentMark + ":" + scale.constraints.size();
}

function change(v, newValue) {
  var edit = new EditConstraint(v, Strength.PREFERRED);
  var edits = new OrderedCollection();
  edits.add(edit);
  var plan = planner.extractPlanFromConstraints(edits);
  for (var i = 0; i < 10; i++) {
    v.value = newValue;
    plan.execute();
  }
  edit.destroyConstraint();
}

var planner = null;

var results = {};
for (var round = 0; round < 6; round++) {
  var r = chainTest(30) + " " + projectionTest(30);
  results[r] = (results[r] || 0) + 1;
}
console.log(JSON.stringify(results));
console.log(chainTest(5), projectionTest(3), projectionTest(45));
var names = [];
for (var k in new Variable("x", 1)) names.push(k);
console.log(names.join(","), Strength.REQUIRED.nextWeaker().name, Strength.WEAKEST.nextWeaker());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_deltablue_constraint_solver(run, tier):
    """CATCHES: polymorphic method-call caches and superConstructor.call/prototype-inheritance paths that dispatch to the wrong constraint subclass method, mis-handle the switch in nextWeaker, or corrupt OrderedCollection arrays, changing DeltaBlue's chain/projection results."""
    check_prog(run, tier, PROG_DELTABLUE, "deltablue")


# Shapes of the classic V8 "RegExp" benchmark: discarded exec/replace/match/split calls on global
# regexes and string arrays inside counted loops. Their only observable effects are RegExp
# legacy statics, lastIndex, coercion callbacks and user-patched methods.
PROG_REGEXP_BENCH = r"""
var re0 = /^ba(r|z)/;
var re1 = /(\w+)=(\d+)/g;
var re2 = /x(\d)/y;
var s0 = [], s1 = [], s2 = [];
for (var k = 0; k < 40; k++) {
  s0.push(k % 3 ? "bar" + k : "foo" + k);
  s1.push("key" + k + "=" + (k * 7) + " other=" + k);
  s2.push("x" + (k % 10) + "x" + ((k + 1) % 10));
}
var log = [];
function statics(tag) { log.push(tag + " $1=" + RegExp.$1 + " $2=" + RegExp.$2 + " last=" + RegExp.lastMatch + " lc=" + RegExp.lastParen + " L=" + RegExp.leftContext.length + " R=" + RegExp.rightContext.length); }
function block0() {
  for (var i = 0; i < 40; i++) {
    re0.exec(s0[i]);
  }
  statics("b0");
  for (var i = 0; i < 40; i++) {
    re1.exec(s1[i]);
  }
  statics("b1 li=" + re1.lastIndex);
  for (var i = 0; i < 40; i++) {
    re2.exec(s2[i]);
  }
  statics("b2 li=" + re2.lastIndex);
}
function block1() {
  for (var i = 0; i < 40; i++) {
    /(\d+)(\d)$/.exec(s0[i]);
  }
  statics("lit-exec");
  /q(u)(i)z/.exec("a quiz b");
  statics("lit-const");
  for (var i = 0; i < 40; i++) {
    s1[i].replace(/other=(\d+)/, "");
  }
  statics("lit-replace");
  for (var i = 0; i < 40; i++) {
    s2[i].match(/(x)(\d)/);
  }
  statics("lit-match");
  for (var i = 0; i < 40; i++) {
    s1[i].split(/=/);
  }
  statics("split");
  for (var i = 0; i < 40; i++) {
    s0[i].replace(/z/g, "Z");
  }
  statics("replace-g");
}
function hostile() {
  var calls = 0;
  var saved = s0[5];
  s0[5] = { toString: function () { calls++; return "baz-object"; } };
  block0();
  s0[5] = saved;
  var origExec = RegExp.prototype.exec, seen = 0;
  RegExp.prototype.exec = function (s) { seen++; return origExec.call(this, s); };
  block0();
  block1();
  RegExp.prototype.exec = origExec;
  var getterHits = 0;
  Object.defineProperty(s2, 3, { get: function () { getterHits++; return "x9x9"; }, configurable: true });
  block0();
  block1();
  Object.defineProperty(s2, 3, { value: "x3x4", writable: true, configurable: true });
  var origReplace = String.prototype.replace, rep = 0;
  String.prototype.replace = function (a, b) { rep++; return origReplace.call(this, a, b); };
  block1();
  String.prototype.replace = origReplace;
  var origSplit = String.prototype.split, spl = 0;
  String.prototype.split = function (a) { spl++; return origSplit.call(this, a); };
  block1();
  String.prototype.split = origSplit;
  return "calls=" + calls + " seen=" + seen + " getter=" + getterHits + " rep=" + rep + " spl=" + spl;
}
for (var round = 0; round < 25; round++) { log.length = 0; block0(); block1(); }
console.log(log.join("\n"));
log.length = 0;
console.log(hostile());
console.log(log.slice(0, 6).join("\n"));
s1[7] = "num=42";
s0.length = 30;
log.length = 0;
block0();
try { block1(); } catch (e) { log.push("threw " + e.name + " at s0 hole"); }
console.log(log.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_regexp_benchmark_shapes(run, tier):
    """CATCHES: JIT/VM shortcuts for result-discarding regexp exec/replace/match/split loops that skip updating RegExp.$1/lastMatch/leftContext, sticky/global lastIndex, element getters, toString coercions or user-replaced RegExp.prototype.exec / String.prototype.replace/split."""
    check_prog(run, tier, PROG_REGEXP_BENCH, "regexp_bench")


PROG_SPREAD_ARGS = r"""
function sum3(a, b, c) { return a + b + c; }
function count() { return arguments.length; }
function joinAll() { var s = ""; for (var i = 0; i < arguments.length; i++) s += arguments[i] + "|"; return s; }
var obj = { base: 100, add: function (a, b) { return this.base + a + b; } };
function dense(n) {
  var args = [1, 2, 3], t = 0;
  for (var i = 0; i < n; i++) {
    args[0] = i & 7;
    t += sum3(...args) + count(...args) + obj.add(...args) + Math.max(...args) + sum3(1, ...args);
  }
  return t;
}
function sizes() {
  var out = [];
  for (var len = 0; len <= 20; len += 4) {
    var a = [];
    for (var i = 0; i < len; i++) a.push(i);
    out.push(count(...a) + ":" + joinAll(...a).length);
  }
  return out.join(" ");
}
function holes() {
  var a = [1, 2, 3, 4];
  delete a[1];
  var r1 = joinAll(...a);
  Array.prototype[1] = "proto";
  var r2 = joinAll(...a);
  delete Array.prototype[1];
  var g = [1, 2, 3];
  var gets = 0;
  Object.defineProperty(g, 2, { get: function () { gets++; return "G"; } });
  var r3 = joinAll(...g) + joinAll(...g);
  return r1 + " " + r2 + " " + r3 + " gets=" + gets;
}
function iterables() {
  var r = [];
  r.push(joinAll(..."héllo"));
  r.push(joinAll(...new Set([3, 1, 3, 2])));
  r.push(joinAll(...new Map([["k", 1]])));
  r.push(joinAll(...new Uint8Array([5, 6])));
  var it = { from: 0 };
  it[Symbol.iterator] = function () { var n = this.from; return { next: function () { n++; return { value: n * 10, done: n > 3 }; } }; };
  r.push(joinAll(...it));
  function* gen() { yield "a"; yield "b"; }
  r.push(joinAll(...gen()));
  var args = (function () { return arguments; })(7, 8);
  r.push(joinAll(...args));
  return r.join(" / ");
}
function errors() {
  var out = [];
  var bad = [null, undefined, 5, {}, { [Symbol.iterator]: 1 }, { [Symbol.iterator]: function () { return 1; } }];
  for (var i = 0; i < bad.length; i++) {
    try { count(...bad[i]); out.push("ok"); } catch (e) { out.push(e.name); }
  }
  var thrower = { [Symbol.iterator]: function () { return { next: function () { throw new RangeError("mid"); } }; } };
  try { count(...thrower); } catch (e) { out.push(e.name + ":" + e.message); }
  try { (void 0)(...[1]); } catch (e) { out.push("callee:" + e.name); }
  var order = [];
  function tag(x) { order.push(x); return x; }
  try { tag("f")(...[tag("arg")]); } catch (e) { out.push("notfn:" + e.name); }
  return out.join(",") + " order=" + order.join("");
}
function methodSpread(n) {
  var calc = { k: 3, f: function (a, b) { return (a * this.k + b) | 0; } };
  var t = 0, args = [0, 0];
  for (var i = 0; i < n; i++) { args[0] = i; args[1] = i >> 1; t += calc.f(...args); if (i === n >> 1) calc.f = function (a) { return -a; }; }
  var proxyFn = new Proxy(sum3, { apply: function (target, self, list) { return "P" + target(...list); } });
  return t + " " + proxyFn(...[1, 2, 3]) + " " + Reflect.apply(sum3, null, [4, 5, 6]) + " " + new Array(...[3]).length + " " + new Date(...[0]).getTime();
}
console.log("dense", dense(20000));
console.log("sizes", sizes());
console.log("holes", holes());
console.log("iterables", iterables());
console.log("errors", errors());
console.log("methodSpread", methodSpread(4000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_spread_call_arguments(run, tier):
    """CATCHES: spread-call shortcuts that skip the iterator protocol when they must not: holes resolved through Array.prototype, element getters, strings/Sets/Maps/typed arrays/generators/custom iterables, long arrays, non-iterables (TypeError), throwing iterators and evaluation order."""
    check_prog(run, tier, PROG_SPREAD_ARGS, "spread_args")


PROG_CAPTURED = r"""
function makeCounter() {
  var count = 0, total = 0.5, label = "c";
  return {
    inc: function () { count++; total += count; return count; },
    dec: function () { --count; total -= 1; return count; },
    mul: function (k) { total *= k; count <<= 1; return total; },
    mix: function () { label += count; count = count % 7; return label.length; },
    get: function () { return count + ":" + total + ":" + label.length; },
  };
}
function counters(n) {
  var c = makeCounter(), s = 0;
  for (var i = 0; i < n; i++) {
    s += c.inc();
    if (i % 3 === 0) s += c.dec();
    if (i % 100 === 0) { c.mul(0.5); s += c.mix(); }
  }
  return s + " " + c.get();
}
function sharedEnv(n) {
  var acc = 0, hits = 0;
  var fns = [];
  for (var k = 0; k < 4; k++) {
    fns.push(function (x) { acc += x * k; hits++; });
  }
  for (var i = 0; i < n; i++) fns[i & 3](i);
  var arrows = [];
  for (let j = 0; j < 4; j++) arrows.push(x => { acc -= x * j; return j; });
  var js = 0;
  for (var i = 0; i < n; i++) js += arrows[i & 3](1);
  return acc + "," + hits + "," + js;
}
function captureParams(a, b) {
  var get = function () { return a + b; };
  var set = function (x) { a = x; b = x * 2; };
  var s = 0;
  for (var i = 0; i < 1000; i++) { set(i); s += get(); }
  return s + "," + a + "," + b;
}
function defaults(n) {
  function lit(a, b = 10, c = "s", d = null, e = [], f = {}) { e.push(a); return a + b + c + d + e.length + Object.keys(f).length; }
  function captured(a, b = 5) { var g = function () { return b++; }; return a + g() + g() + b; }
  function expr(a, b = a + 1, c = b * 2) { return a + b + c; }
  function thisDefault(a = this) { return typeof a; }
  function undef(a = 1) { return a; }
  var s = "";
  for (var i = 0; i < n; i++) {
    var r = lit(i) + "/" + lit(i, 1, "t", 0) + "/" + captured(i) + "/" + captured(i, 100) + "/" + expr(i) + "/" + expr(i, 0) + "/" + undef(undefined) + "/" + undef(null) + "/" + thisDefault();
    if (i === n - 1) s = r;
  }
  return s;
}
function argumentsObj(n) {
  function variadic() { var s = 0; for (var i = 0; i < arguments.length; i++) s += arguments[i]; return s + arguments.length * 1000; }
  function shape() { return Object.prototype.toString.call(arguments) + ":" + Array.isArray(arguments) + ":" + Array.prototype.slice.call(arguments).join(""); }
  function applyFwd() { return variadic.apply(null, arguments); }
  function Ctor() { Base.apply(this, arguments); this.extra = arguments.length; }
  function Base(x, y) { this.x = x; this.y = y; }
  var t = 0;
  for (var i = 0; i < n; i++) { t += variadic(i, 1, 2) + variadic() + applyFwd(i, i); var o = new Ctor(i, 2, 3); t += o.x + o.y + o.extra; }
  return t + " " + shape(1, "a", null);
}
function arrowThis() {
  var o = {
    v: 7,
    run: function () {
      var self = this;
      var f = () => this.v + self.v;
      var g = () => () => this.v * 2;
      var s = 0;
      for (var i = 0; i < 100; i++) s += f() + g()();
      return s;
    },
  };
  return o.run() + "," + o.run.call({ v: 1 });
}
function capturedLoopVars(n) {
  var fs = [];
  for (let i = 0; i < 5; i++) { let j = i * 10; fs.push(() => i + j); }
  var t = 0;
  for (var r = 0; r < n; r++) for (var k = 0; k < fs.length; k++) t += fs[k]();
  var outer = 1;
  function bump() { outer = outer * 3 % 1000003; }
  for (var r = 0; r < n; r++) bump();
  return t + "," + outer;
}
function closureChain(depth) {
  var make = function (level, next) { var own = level * 2; return function (x) { return next ? next(x + own) : x + own; }; };
  var f = null;
  for (var i = 0; i < depth; i++) f = make(i, f);
  var s = 0;
  for (var i = 0; i < 200; i++) s += f(i);
  return s;
}
function tdzCapture() {
  var out = [];
  try { (function () { var read = () => later; read(); let later = 1; })(); } catch (e) { out.push(e.name); }
  var f;
  { let blockVal = "b"; f = () => blockVal; }
  out.push(f());
  const K = 5;
  var tryWrite = () => { try { K = 6; } catch (e) { return e.name; } return "wrote"; };
  out.push(tryWrite(), K);
  return out.join(",");
}
console.log("counters", counters(5000));
console.log("sharedEnv", sharedEnv(4000));
console.log("captureParams", captureParams(1, 2));
console.log("defaults", defaults(300));
console.log("arguments", argumentsObj(3000));
console.log("arrowThis", arrowThis());
console.log("capturedLoopVars", capturedLoopVars(500));
console.log("closureChain", closureChain(12));
console.log("tdzCapture", tdzCapture());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_captured_bindings_and_parameters(run, tier):
    """CATCHES: compiled code that mishandles captured-variable reads/writes/compound updates shared between closures, parameters captured and reassigned by inner functions, literal/expression/captured default parameters, the arguments object (apply forwarding, constructor delegation) and lexical this/TDZ in arrows."""
    check_prog(run, tier, PROG_CAPTURED, "captured")


PROG_SCANNER = r"""
function tokenize(src) {
  var out = [], i = 0, n = src.length;
  while (i < n) {
    var c = src.charCodeAt(i);
    if (c === 32 || c === 10 || c === 9) { i++; continue; }
    if (c >= 48 && c <= 57) {
      var start = i;
      while (i < n && src.charCodeAt(i) >= 48 && src.charCodeAt(i) <= 57) i++;
      if (src.charAt(i) === ".") { i++; while (i < n && src.charCodeAt(i) >= 48 && src.charCodeAt(i) <= 57) i++; }
      out.push("num:" + src.slice(start, i));
      continue;
    }
    if ((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 95 || c > 127) {
      var s = i;
      while (i < n) { var d = src.charCodeAt(i); if (!((d >= 65 && d <= 90) || (d >= 97 && d <= 122) || d === 95 || (d >= 48 && d <= 57) || d > 127)) break; i++; }
      var word = src.slice(s, i);
      out.push((Object.hasOwn(KEYWORDS, word) ? "kw:" : "id:") + word);
      continue;
    }
    if (c === 34) {
      var e = src.indexOf('"', i + 1);
      out.push("str:" + src.slice(i + 1, e).length);
      i = e + 1;
      continue;
    }
    out.push("op:" + src.charAt(i));
    i++;
  }
  return out;
}
var KEYWORDS = { "if": 1, "else": 1, "while": 1, "return": 1, "var": 1, "function": 1 };
var SRC = 'function fib(n) { if (n < 2) return n; return fib(n - 1) + fib(n - 2); }\nvar x_1 = 3.25 * 4 + "str ing";\nwhile (x_1 > 0) x_1 = x_1 - 1.5;';
function rounds(n) {
  var counts = {}, last;
  for (var r = 0; r < n; r++) {
    last = tokenize(SRC);
    for (var k = 0; k < last.length; k++) { var kind = last[k].slice(0, last[k].indexOf(":")); counts[kind] = (counts[kind] || 0) + 1; }
  }
  return JSON.stringify(counts) + " " + last.length + " " + last.slice(0, 8).join(" ");
}
console.log("ascii", rounds(60));
console.log("unicode", tokenize("naïve ünïcödé 12 €5 \u{1F600}x").join(" "));
function edges() {
  var s = "abc", out = [];
  var idx = [0, 2, 3, -1, 1.5, NaN, "1", null, undefined, true, 2 ** 32];
  for (var r = 0; r < 30; r++) {
    for (var k = 0; k < idx.length; k++) {
      var v = s.charCodeAt(idx[k]), w = s.charAt(idx[k]);
      if (r === 29) out.push(v + "/" + JSON.stringify(w));
    }
  }
  var obj = new String("xyz");
  out.push(obj.charCodeAt(1), obj.charAt(2), "".charCodeAt(0), "😀".charCodeAt(1), "é".charCodeAt(0));
  out.push(s.slice(-2), s.slice(1, -1), s.slice(5), s.slice(2, 1), s.slice(), s.slice(NaN, 2), s.slice(0, Infinity));
  return out.join(" ");
}
console.log("edges", edges());
function patchedIntrinsics() {
  var s = "hello world", t = 0, out = [];
  var orig = String.prototype.charCodeAt;
  for (var i = 0; i < 400; i++) {
    t += s.charCodeAt(i % 11);
    if (i === 200) String.prototype.charCodeAt = function (k) { return 1; };
  }
  String.prototype.charCodeAt = orig;
  out.push(t);
  var origSlice = String.prototype.slice, sl = 0;
  for (var i = 0; i < 300; i++) { out.length = 1; out.push(s.slice(0, 3)); if (i === 150) String.prototype.slice = function () { sl++; return "S"; }; }
  String.prototype.slice = origSlice;
  var origHas = Object.hasOwn, h = 0;
  for (var i = 0; i < 300; i++) { if (Object.hasOwn(KEYWORDS, "if")) h++; if (i === 100) Object.hasOwn = function () { return false; }; }
  Object.hasOwn = origHas;
  var sq = 0, origSqrt = Math.sqrt;
  for (var i = 0; i < 300; i++) { sq += Math.sqrt(i); if (i === 200) Math.sqrt = function (x) { return -1; }; }
  Math.sqrt = origSqrt;
  out.push(sl, h, sq.toFixed(6), Math.sqrt(-1), Math.sqrt("16"), Math.sqrt(-0) === 0 && 1 / Math.sqrt(-0));
  return out.join(" ");
}
console.log("patched", patchedIntrinsics());
function hasOwnCases() {
  var proto = { inh: 1 }, o = Object.create(proto);
  o.own = 1; o[5] = 2;
  var sym = Symbol("s"); o[sym] = 3;
  var keys = ["own", "inh", "5", 5, sym, "toString", "missing"], out = [];
  for (var r = 0; r < 50; r++) { out.length = 0; for (var k = 0; k < keys.length; k++) out.push(Object.hasOwn(o, keys[k])); }
  var errs = [];
  try { Object.hasOwn(null, "x"); } catch (e) { errs.push(e.name); }
  try { Object.hasOwn(undefined, "x"); } catch (e) { errs.push(e.name); }
  return out.join(",") + " " + Object.hasOwn([1], 0) + " " + Object.hasOwn(function f() {}, "name") + " " + errs.join(",");
}
console.log("hasOwn", hasOwnCases());
function pushPop(n) {
  var st = [], maxDepth = 0, popped = 0;
  for (var i = 0; i < n; i++) {
    if (i % 3 === 2) { var v = st.pop(); popped += v === undefined ? 1000 : v; } else st.push(i);
    if (st.length > maxDepth) maxDepth = st.length;
  }
  var e = [];
  var r = [e.pop(), e.push(), e.push(1, 2, 3), e.length, e.pop(), e];
  var frozen = Object.freeze([1]);
  var errs = [];
  try { frozen.push(2); } catch (x) { errs.push(x.name); }
  try { frozen.pop(); } catch (x) { errs.push(x.name); }
  var arrLike = { length: 2, 0: "a", 1: "b" };
  Array.prototype.push.call(arrLike, "c");
  var p = Array.prototype.pop.call(arrLike);
  return [st.length, maxDepth, popped, r.join("|"), errs.join(","), p, arrLike.length].join(" ");
}
console.log("pushPop", pushPop(3000));
function calls(n) {
  function f(a, b) { return (this && this.k || 0) + (a | 0) + (b | 0); }
  var o = { k: 100 }, t = 0;
  for (var i = 0; i < n; i++) t += f.call(o, i, 1) + f.call(null, 1, 2) + f.call(o) + Math.max.call(null, i, 5);
  var notFn = { call: Function.prototype.call };
  var err = "";
  try { notFn.call(); } catch (e) { err = e.name; }
  var bound = f.bind(o, 1);
  return t + " " + bound.call({ k: 5 }, 2) + " " + f.call.call(f, o, 3, 4) + " " + err;
}
console.log("calls", calls(5000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_scanner_intrinsics(run, tier):
    """CATCHES: inline intrinsics (charCodeAt/charAt/slice on ASCII and non-ASCII strings, Object.hasOwn, Math.sqrt, Array push/pop, Function.prototype.call) that return wrong values for edge indices or keep using the builtin after it is replaced mid-loop."""
    check_prog(run, tier, PROG_SCANNER, "scanner")


PROG_VM_OPS = r"""
var gcount = 0;
function typeofs(n) {
  var r = "";
  for (var i = 0; i < n; i++) {
    r = typeof notDeclaredAnywhere + typeof gcount + typeof Math + typeof Symbol() + typeof 1n + typeof null + typeof function () {} + typeof undefined + (void i) + typeof void 0;
  }
  return r;
}
function updates(n) {
  var big = 10n, cap = 5n, num = 1.5, str = "7", obj = { p: 1n, q: "2", r: 0.5 }, arr = [1n, 2, "3"];
  var bump = function () { cap++; --cap; cap++; return cap; };
  for (var i = 0; i < n; i++) {
    big++; ++big; big--;
    bump();
    num++; num--;
    obj.p++; obj.r--; ++obj.p;
    arr[0]++; arr[1]--; ++arr[0];
  }
  var a = str++, b = obj.q--, c = arr[2]++;
  var und = { }; und.x++; var nn = null; nn++;
  return [big, cap, num, str, a, b, obj.p, obj.q, obj.r, arr.join("|"), c, und.x, nn, typeof a].join(",");
}
function compound(n) {
  var x = 7, o = { v: 3 }, a = [2, 3];
  for (var i = 0; i < n; i++) {
    x += i; x -= 1; x *= 1; x /= 1; x %= 1000003; x **= 1; x <<= 1; x >>= 1; x >>>= 0; x &= 0xffffff; x |= 1; x ^= 2;
    o.v += 2; o.v *= 1; o.v -= 1; o.v %= 97; o.v <<= 1; o.v >>= 1; o.v ^= 1;
    a[i & 1] += i; a[i & 1] %= 1001; a[1 - (i & 1)] **= 1; a[0] |= 0;
  }
  var s = "a"; s += 1; s += null; s += [2, 3];
  var big = 2n; big **= 10n; big %= 1000n; big <<= 3n; big >>= 1n; big &= 0xffn; big |= 1n; big ^= 3n; big -= 1n; big *= -2n; big /= 3n;
  return [x, o.v, a.join("|"), s, big].join(",");
}
function accessorsCompound() {
  var log = [];
  var o = { _v: 1, get v() { log.push("get"); return this._v; }, set v(x) { log.push("set" + x); this._v = x; } };
  for (var i = 0; i < 3; i++) { o.v += 10; o.v++; }
  var key = { toString: function () { log.push("key"); return "v"; } };
  o[key] *= 2;
  return o._v + " " + log.join(",");
}
function deletes() {
  var out = [];
  var o = { a: 1, b: 2, c: 3 };
  for (var i = 0; i < 20; i++) { o["k" + i] = i; if (i % 2) delete o["k" + (i - 1)]; }
  out.push(Object.keys(o).join(""));
  var arr = [1, 2, 3, 4];
  out.push(delete arr[1], delete arr[10], arr.length, 1 in arr, delete arr.length);
  var frozen = Object.freeze({ z: 1 });
  out.push(delete frozen.z, delete frozen.nope);
  out.push((function () { "use strict"; try { delete frozen.z; return "deleted"; } catch (e) { return e.name; } })());
  out.push((function () { "use strict"; var a2 = [1]; try { delete a2.length; return "ok"; } catch (e) { return e.name; } })());
  out.push(delete Math.PI, delete globalThis.gcount, typeof gcount);
  var key = "b";
  out.push(delete o[key], "b" in o, delete o.missing);
  return out.join(",");
}
function optionalOps(n) {
  var objs = [{ f: function () { return this.k; }, k: 1, inner: { arr: [5, 6] } }, null, { k: 2 }, undefined, { f: null, inner: null }];
  var t = 0, u = 0;
  for (var i = 0; i < n; i++) {
    var o = objs[i % objs.length];
    var r1 = o?.f?.(), r2 = o?.inner?.arr?.[1], r3 = o?.["k"], r4 = (o ?? { k: 9 }).k, r5 = o?.k ?? -1;
    if (r1 === undefined) u++; else t += r1;
    t += (r2 || 0) + (r3 || 0) + (r4 || 0) + (r5 || 0);
  }
  var calls = 0;
  var maybe = null;
  maybe?.method(calls++);
  var deep = { a: { b: null } };
  return [t, u, calls, deep.a.b?.c.d.e, deep.a?.b?.(), (null)?.x === undefined, 0 ?? 1, "" || "d", 0 && 1, null ?? (false || "x")].join(",");
}
function logical(n) {
  var vals = [0, 1, "", "s", null, undefined, NaN, [], {}, -0, 0n, 1n];
  var r = [];
  for (var k = 0; k < n; k++) {
    r.length = 0;
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      r.push((v && "T") || "F", v ?? "N", !v, !!v, -v === -v ? "eq" : "ne");
    }
  }
  return r.slice(0, 30).join(" ");
}
function seqAndCond(n) {
  var a = 0, b = 0, c = 0;
  for (var i = 0; i < n; i++) {
    a = (b++, c += 2, b + c);
    b = i % 3 === 0 ? (i % 5 === 0 ? 1 : 2) : i % 3 === 1 ? 3 : 4;
    c = c > 100 ? c - 100 : c;
  }
  return [a, b, c].join(",");
}
function relational(n) {
  var t = 0;
  var strs = ["a", "b", "aa", "B", "10", "9", "", "ä"];
  for (var r = 0; r < n; r++) for (var i = 0; i < strs.length; i++) for (var j = 0; j < strs.length; j++) { if (strs[i] < strs[j]) t++; if (strs[i] >= strs[j]) t += 2; }
  var big = [1n, 2, 2n, "3", 3.5, -1n];
  var u = 0;
  for (var i = 0; i < big.length; i++) for (var j = 0; j < big.length; j++) { if (big[i] < big[j]) u++; if (big[i] == big[j]) u += 10; }
  return t + "," + u + "," + ("10" < "9") + "," + (10 < "9") + "," + (null >= 0) + "," + (undefined == null) + "," + (NaN <= NaN);
}
function instanceofCases() {
  function A() {}
  var Even = { [Symbol.hasInstance]: function (v) { return v % 2 === 0; } };
  var bound = A.bind(null);
  var out = [];
  for (var i = 0; i < 3; i++) out.push(new A() instanceof A, 4 instanceof Even, 3 instanceof Even, new A() instanceof bound, [] instanceof Object, Object.create(null) instanceof Object);
  try { ({}) instanceof {}; } catch (e) { out.push(e.name); }
  return out.slice(0, 6).join(",") + "," + out[out.length - 1];
}
function bitwiseBig(n) {
  var x = 0n, y = 1n;
  for (var i = 0; i < n; i++) { x = (x + y * 3n) & 0xffffffffffffn; y = (y << 1n) % 1000000007n; x ^= ~y; }
  return x + "," + y + "," + (-7n / 2n) + "," + (-7n % 2n) + "," + (2n ** 70n) + "," + BigInt.asIntN(8, 255n) + "," + BigInt.asUintN(8, -1n) + "," + (5n > 4) + "," + (5n == "5");
}
function exoticKeys() {
  var o = {};
  var keys = [1, "1", 1.5, -0, NaN, true, null, undefined, Symbol.for("s"), { toString: function () { return "obj"; } }, [1, 2]];
  for (var r = 0; r < 10; r++) for (var i = 0; i < keys.length; i++) o[keys[i]] = (o[keys[i]] || 0) + 1;
  return Object.keys(o).join("|") + " " + o[Symbol.for("s")] + " " + o["0"] + " " + o["1,2"];
}
console.log("typeofs", typeofs(100));
console.log("updates", updates(1000));
console.log("compound", compound(3000));
console.log("accessorsCompound", accessorsCompound());
console.log("deletes", deletes());
console.log("optional", optionalOps(3000));
console.log("logical", logical(50));
console.log("seqAndCond", seqAndCond(3000));
console.log("relational", relational(30));
console.log("instanceof", instanceofCases());
console.log("bitwiseBig", bitwiseBig(500));
console.log("exoticKeys", exoticKeys());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_vm_operator_coverage(run, tier):
    """CATCHES: VM/JIT operator lowering bugs: typeof on undeclared globals, ++/-- on BigInt/string/captured/member/element targets, every compound assignment operator (incl. BigInt and getter/setter targets), delete in sloppy vs strict mode, optional chaining/calls with short-circuit, nullish/logical values, mixed BigInt/string relational comparisons, Symbol.hasInstance and property-key coercion."""
    check_prog(run, tier, PROG_VM_OPS, "vm_ops")


# A jsbn-style multi-precision integer (28-bit digits, am3 inner loop as in the V8 "Crypto"
# benchmark), cross-checked against native BigInt.
PROG_BIGNUM = r"""
var DB = 28, DM = (1 << DB) - 1, DV = 1 << DB;
function BN() { this.array = []; this.t = 0; this.s = 0; }
function nbv(v) { var r = new BN(); r.fromInt(v); return r; }
BN.prototype.fromInt = function (x) {
  this.t = 1; this.s = x < 0 ? -1 : 0;
  if (x > 0) this.array[0] = x; else if (x < -1) this.array[0] = x + DV; else this.t = 0;
};
BN.prototype.am3 = function (i, x, w, j, c, n) {
  var this_array = this.array, w_array = w.array;
  var xl = x & 0x3fff, xh = x >> 14;
  while (--n >= 0) {
    var l = this_array[i] & 0x3fff;
    var h = this_array[i++] >> 14;
    var m = xh * l + h * xl;
    l = xl * l + ((m & 0x3fff) << 14) + w_array[j] + c;
    c = (l >> 28) + (m >> 14) + xh * h;
    w_array[j++] = l & 0xfffffff;
  }
  return c;
};
BN.prototype.clamp = function () {
  var c = this.s & DM, a = this.array;
  while (this.t > 0 && a[this.t - 1] == c) --this.t;
};
BN.prototype.multiplyTo = function (a, r) {
  var x = this, y = a, i = x.t, ra = r.array;
  r.t = i + y.t;
  while (--i >= 0) ra[i] = 0;
  for (i = 0; i < y.t; ++i) ra[i + x.t] = x.am3(0, y.array[i], r, i, 0, x.t);
  r.s = 0;
  r.clamp();
};
BN.prototype.multiply = function (a) { var r = new BN(); this.multiplyTo(a, r); return r; };
BN.prototype.addSmall = function (v) {
  var a = this.array, i = 0, c = v;
  while (c && i < this.t) { var s = a[i] + c; a[i] = s & DM; c = s >> DB; i++; }
  if (c) { a[this.t++] = c; }
  return this;
};
BN.prototype.divSmall = function (d) {
  var a = this.array, rem = 0;
  for (var i = this.t - 1; i >= 0; i--) { var cur = rem * DV + a[i]; a[i] = Math.floor(cur / d); rem = cur % d; }
  this.clamp();
  return rem;
};
BN.prototype.compareTo = function (b) {
  var r = this.t - b.t;
  if (r != 0) return r;
  var i = this.t, ta = this.array, ba = b.array;
  while (--i >= 0) if ((r = ta[i] - ba[i]) != 0) return r;
  return 0;
};
BN.prototype.copy = function () { var r = new BN(); r.t = this.t; r.s = this.s; for (var i = 0; i < this.t; i++) r.array[i] = this.array[i]; return r; };
BN.prototype.toString = function () {
  if (this.t == 0) return "0";
  var c = this.copy(), parts = [];
  while (c.t > 0) { var d = c.divSmall(10000000); var s = String(d); if (c.t > 0) while (s.length < 7) s = "0" + s; parts.push(s); }
  return parts.reverse().join("");
};
function bnFromString(str) {
  var r = nbv(0);
  for (var i = 0; i < str.length; i++) { r = r.multiply(nbv(10)); r.addSmall(str.charCodeAt(i) - 48); }
  return r;
}
function factorial(n) { var r = nbv(1); for (var i = 2; i <= n; i++) r = r.multiply(nbv(i)); return r; }
function power(b, e) { var r = nbv(1), base = nbv(b); for (var i = 0; i < e; i++) r = r.multiply(base); return r; }
var checks = [];
for (var round = 0; round < 3; round++) {
  checks.length = 0;
  var f = factorial(80);
  var fb = 1n; for (var i = 2n; i <= 80n; i++) fb *= i;
  checks.push(f.toString() === fb.toString());
  var p = power(3, 150);
  checks.push(p.toString() === (3n ** 150n).toString());
  var sq = p.multiply(p);
  checks.push(sq.toString() === ((3n ** 150n) ** 2n).toString());
  var parsed = bnFromString("123456789012345678901234567890");
  checks.push(parsed.toString(), parsed.compareTo(p), p.compareTo(parsed), parsed.compareTo(parsed.copy()));
}
console.log(checks.join(" "));
console.log(factorial(30).toString(), power(7, 40).toString(), power(2, 100).t, factorial(25).array.slice(0, 4).join(","));
var zero = nbv(0), neg = nbv(-5);
console.log(zero.toString(), neg.t, neg.s, neg.array[0], nbv(1).multiply(nbv(0)).toString());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_bignum_am3_kernel(run, tier):
    """CATCHES: int32 bit-twiddling loop bugs (>>, &, << on products near 2^31, pre-decrement while loops, post-increment array indices) in a jsbn/Crypto-style multiplication kernel; results are cross-checked against native BigInt and printed in full."""
    check_prog(run, tier, PROG_BIGNUM, "bignum")


# The V8 "Splay" benchmark's splay tree (prototype defaults for left/right, a dummy-node top-down
# splay loop, recursive traversal) driven by a deterministic LCG instead of Math.random.
PROG_SPLAY = r"""
function SplayTree() {};
SplayTree.prototype.root_ = null;
SplayTree.prototype.isEmpty = function() { return !this.root_; };
SplayTree.prototype.insert = function(key, value) {
  if (this.isEmpty()) { this.root_ = new SplayTree.Node(key, value); return; }
  this.splay_(key);
  if (this.root_.key == key) return;
  var node = new SplayTree.Node(key, value);
  if (key > this.root_.key) {
    node.left = this.root_; node.right = this.root_.right; this.root_.right = null;
  } else {
    node.right = this.root_; node.left = this.root_.left; this.root_.left = null;
  }
  this.root_ = node;
};
SplayTree.prototype.remove = function(key) {
  if (this.isEmpty()) throw Error('Key not found: ' + key);
  this.splay_(key);
  if (this.root_.key != key) throw Error('Key not found: ' + key);
  var removed = this.root_;
  if (!this.root_.left) {
    this.root_ = this.root_.right;
  } else {
    var right = this.root_.right;
    this.root_ = this.root_.left;
    this.splay_(key);
    this.root_.right = right;
  }
  return removed;
};
SplayTree.prototype.find = function(key) {
  if (this.isEmpty()) return null;
  this.splay_(key);
  return this.root_.key == key ? this.root_ : null;
};
SplayTree.prototype.findMax = function(opt_startNode) {
  if (this.isEmpty()) return null;
  var current = opt_startNode || this.root_;
  while (current.right) current = current.right;
  return current;
};
SplayTree.prototype.findGreatestLessThan = function(key) {
  if (this.isEmpty()) return null;
  this.splay_(key);
  if (this.root_.key < key) return this.root_;
  else if (this.root_.left) return this.findMax(this.root_.left);
  else return null;
};
SplayTree.prototype.exportKeys = function() {
  var result = [];
  if (!this.isEmpty()) this.root_.traverse_(function(node) { result.push(node.key); });
  return result;
};
SplayTree.prototype.splay_ = function(key) {
  if (this.isEmpty()) return;
  var dummy, left, right;
  dummy = left = right = new SplayTree.Node(null, null);
  var current = this.root_;
  while (true) {
    if (key < current.key) {
      if (!current.left) break;
      if (key < current.left.key) {
        var tmp = current.left;
        current.left = tmp.right;
        tmp.right = current;
        current = tmp;
        if (!current.left) break;
      }
      right.left = current;
      right = current;
      current = current.left;
    } else if (key > current.key) {
      if (!current.right) break;
      if (key > current.right.key) {
        var tmp = current.right;
        current.right = tmp.left;
        tmp.left = current;
        current = tmp;
        if (!current.right) break;
      }
      left.right = current;
      left = current;
      current = current.right;
    } else {
      break;
    }
  }
  left.right = current.left;
  right.left = current.right;
  current.left = dummy.right;
  current.right = dummy.left;
  this.root_ = current;
};
SplayTree.Node = function(key, value) { this.key = key; this.value = value; };
SplayTree.Node.prototype.left = null;
SplayTree.Node.prototype.right = null;
SplayTree.Node.prototype.traverse_ = function(f) {
  var current = this;
  while (current) {
    var left = current.left;
    if (left) left.traverse_(f);
    f(current);
    current = current.right;
  }
};
function GeneratePayloadTree(depth, tag) {
  if (depth == 0) {
    return { array: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], string: 'String for key ' + tag + ' in leaf node' };
  } else {
    return { left: GeneratePayloadTree(depth - 1, tag), right: GeneratePayloadTree(depth - 1, tag) };
  }
}
var seed = 49734321;
function rnd() { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }
function InsertNewNode(tree) {
  var key;
  do { key = rnd(); } while (tree.find(key) != null);
  tree.insert(key, GeneratePayloadTree(2, String(key)));
  return key;
}
var tree = new SplayTree();
for (var i = 0; i < 700; i++) InsertNewNode(tree);
var removedOk = 0, missing = 0;
for (var step = 0; step < 1000; step++) {
  var key = InsertNewNode(tree);
  var greatest = tree.findGreatestLessThan(key);
  if (greatest == null) missing++; else { tree.remove(greatest.key); removedOk++; }
}
var keys = tree.exportKeys();
var sorted = true;
for (var i = 1; i < keys.length; i++) if (!(keys[i - 1] < keys[i])) sorted = false;
var leaf = tree.find(keys[17]).value.left.right;
console.log(keys.length, removedOk, missing, sorted, keys[0].toFixed(9), keys[keys.length - 1].toFixed(9));
console.log(leaf.string.length, leaf.array.join(""), tree.findMax().key === keys[keys.length - 1]);
try { tree.remove(-1); } catch (e) { console.log(e.message); }
var t2 = new SplayTree();
console.log(t2.find(1), t2.findMax(), t2.exportKeys().length, t2.findGreatestLessThan(3));
var numKeys = new SplayTree();
for (var i = 0; i < 500; i++) numKeys.insert((i * 37) % 500, i);
numKeys.insert("250", "dup?");
console.log(numKeys.exportKeys().length, numKeys.find(250).value, numKeys.findGreatestLessThan(100).key, numKeys.exportKeys().slice(0, 5).join(","));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_splay_tree(run, tier):
    """CATCHES: property caches that confuse prototype-default fields (left/right = null on Node.prototype) with own fields once nodes are linked, top-down splay pointer rotations, loose == between string and number keys, and recursive traversal through compiled closures."""
    check_prog(run, tier, PROG_SPLAY, "splay")


# RayTrace-style object code: Prototype.js Class.create (constructors forwarding `arguments`
# through initialize.apply), Object.extend via for-in, small vector/color objects in hot loops.
PROG_RAYTRACE = r"""
var Class = { create: function () { return function () { this.initialize.apply(this, arguments); }; } };
Object.extend = function (destination, source) { for (var property in source) { destination[property] = source[property]; } return destination; };
var Flog = {};
Flog.Vector = Class.create();
Flog.Vector.prototype = {
  x: 0.0, y: 0.0, z: 0.0,
  initialize: function (x, y, z) { this.x = (x ? x : 0); this.y = (y ? y : 0); this.z = (z ? z : 0); },
  normalize: function () { var m = this.magnitude(); return new Flog.Vector(this.x / m, this.y / m, this.z / m); },
  magnitude: function () { return Math.sqrt((this.x * this.x) + (this.y * this.y) + (this.z * this.z)); },
  cross: function (w) { return new Flog.Vector(-this.z * w.y + this.y * w.z, this.z * w.x - this.x * w.z, -this.y * w.x + this.x * w.y); },
  dot: function (w) { return this.x * w.x + this.y * w.y + this.z * w.z; },
  add: function (v) { return new Flog.Vector(v.x + this.x, v.y + this.y, v.z + this.z); },
  subtract: function (v) { return new Flog.Vector(this.x - v.x, this.y - v.y, this.z - v.z); },
  multiplyScalar: function (w) { return new Flog.Vector(this.x * w, this.y * w, this.z * w); },
};
Flog.Color = Class.create();
Flog.Color.prototype = {
  red: 0.0, green: 0.0, blue: 0.0,
  initialize: function (r, g, b) { if (!r) r = 0.0; if (!g) g = 0.0; if (!b) b = 0.0; this.red = r; this.green = g; this.blue = b; },
  add: function (c) { return new Flog.Color(this.red + c.red, this.green + c.green, this.blue + c.blue); },
  multiplyScalar: function (f) { return new Flog.Color(this.red * f, this.green * f, this.blue * f); },
  multiply: function (c) { return new Flog.Color(this.red * c.red, this.green * c.green, this.blue * c.blue); },
  limit: function () {
    this.red = (this.red > 0.0) ? ((this.red > 1.0) ? 1.0 : this.red) : 0.0;
    this.green = (this.green > 0.0) ? ((this.green > 1.0) ? 1.0 : this.green) : 0.0;
    this.blue = (this.blue > 0.0) ? ((this.blue > 1.0) ? 1.0 : this.blue) : 0.0;
  },
  brightness: function () { var r = Math.floor(this.red * 255); var g = Math.floor(this.green * 255); var b = Math.floor(this.blue * 255); return (r * 77 + g * 150 + b * 29) >> 8; },
  toString: function () { return "rgb(" + Math.floor(this.red * 255) + "," + Math.floor(this.green * 255) + "," + Math.floor(this.blue * 255) + ")"; },
};
Flog.Ray = Class.create();
Flog.Ray.prototype = { position: null, direction: null, initialize: function (pos, dir) { this.position = pos; this.direction = dir; } };
Flog.Shape = Class.create();
Flog.Shape.prototype = { kind: "shape", initialize: function () {} };
Flog.Sphere = Class.create();
Flog.Sphere.prototype = Object.extend(Object.extend({}, Flog.Shape.prototype), {
  kind: "sphere",
  initialize: function (pos, radius, color) { this.radius = radius; this.position = pos; this.color = color; },
  intersect: function (ray) {
    var dst = ray.position.subtract(this.position);
    var B = dst.dot(ray.direction);
    var C = dst.dot(dst) - (this.radius * this.radius);
    var D = (B * B) - C;
    if (D > 0) {
      var t = (-B) - Math.sqrt(D);
      if (t > 0) return { hit: true, distance: t, shape: this, position: ray.position.add(ray.direction.multiplyScalar(t)) };
    }
    return { hit: false };
  },
});
Flog.Plane = Class.create();
Flog.Plane.prototype = Object.extend(Object.extend({}, Flog.Shape.prototype), {
  kind: "plane",
  initialize: function (pos, d, color) { this.position = pos; this.d = d; this.color = color; },
  intersect: function (ray) {
    var Vd = this.position.dot(ray.direction);
    if (Vd == 0) return { hit: false };
    var t = -(this.position.dot(ray.position) + this.d) / Vd;
    if (t <= 0) return { hit: false };
    var p = ray.position.add(ray.direction.multiplyScalar(t));
    var checker = (Math.floor(p.x) + Math.floor(p.z)) & 1;
    return { hit: true, distance: t, shape: this, position: p, checker: checker };
  },
});
function render(w, h) {
  var shapes = [
    new Flog.Plane(new Flog.Vector(0.1, 0.9, -0.5).normalize(), 1.2, new Flog.Color(0.2, 0.3, 0.4)),
    new Flog.Sphere(new Flog.Vector(-1.5, 1.5, 2), 1.5, new Flog.Color(0.9, 0.2, 0.1)),
    new Flog.Sphere(new Flog.Vector(1, 0.25, 1), 0.5, new Flog.Color(0.1, 0.8, 0.3)),
  ];
  var light = new Flog.Vector(5, 10, -1).normalize();
  var eye = new Flog.Vector(0, 0, -15);
  var rows = [], hist = {}, total = 0;
  for (var y = 0; y < h; y++) {
    var row = "";
    for (var x = 0; x < w; x++) {
      var dir = new Flog.Vector((x - w / 2) / w, (h / 2 - y) / h, 1).normalize();
      var ray = new Flog.Ray(eye, dir);
      var best = null;
      for (var i = 0; i < shapes.length; i++) {
        var info = shapes[i].intersect(ray);
        if (info.hit && (best == null || info.distance < best.distance)) best = info;
      }
      var color = new Flog.Color(0, 0, 0);
      if (best != null) {
        var n = best.shape.kind === "sphere" ? best.position.subtract(best.shape.position).normalize() : best.shape.position;
        var lambert = Math.max(0, n.dot(light));
        color = best.shape.color.multiplyScalar(0.2 + 0.8 * lambert);
        if (best.checker) color = color.multiply(new Flog.Color(0.5, 0.5, 0.5)).add(new Flog.Color(0.05, 0.05, 0.05));
        hist[best.shape.kind] = (hist[best.shape.kind] || 0) + 1;
      }
      color.limit();
      var b = color.brightness();
      total += b;
      row += " .:-=+*#%@".charAt(Math.min(9, b / 26 | 0));
    }
    rows.push(row);
  }
  return { rows: rows, hist: hist, total: total, sample: color.toString() };
}
var res;
for (var k = 0; k < 2; k++) res = render(40, 16);
console.log(res.rows.join("\n"));
console.log(JSON.stringify(res.hist), res.total, res.sample);
var v = new Flog.Vector(1, 2, 3), keys = [];
for (var key in v) keys.push(key);
console.log(keys.join(","), v.cross(new Flog.Vector(0, 1, 0)).magnitude().toFixed(6), new Flog.Vector().magnitude(), Object.keys(Flog.Sphere.prototype).join(","));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_raytrace_objects(run, tier):
    """CATCHES: constructor paths that forward `arguments` via initialize.apply, prototype objects replaced wholesale (Class.create/Object.extend via for-in), prototype-default vs own numeric fields, and floating-point vector math; the rendered ASCII image, histogram and checksum must match the interpreter."""
    check_prog(run, tier, PROG_RAYTRACE, "raytrace")


UNCAUGHT_SCRIPT = r"""
function hot(objs) { var s = 0; for (var i = 0; i < objs.length; i++) s += objs[i].v.w; return s; }
var objs = [];
for (var i = 0; i < 2000; i++) objs.push({ v: { w: i } });
console.log("warm", hot(objs), hot(objs));
objs[1500] = { v: undefined };
console.log("before");
hot(objs);
console.log("never");
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_uncaught_error_from_hot_loop(run, workdir, tier):
    """CATCHES: a compiled loop that swallows, mis-names or delays a TypeError raised mid-iteration (reading a property of undefined) instead of flushing prior output, printing 'Uncaught TypeError: ...' to stderr and exiting with status 1."""
    write_files(workdir, {"hot.js": UNCAUGHT_SCRIPT})
    r = run([*tier, "hot.js"], timeout=90)
    assert r.returncode == 1
    assert r.stdout == b"warm 1999000 1999000\nbefore\n"
    assert r.stderr == b"Uncaught TypeError: cannot read property 'w' of undefined\n"


UNCAUGHT_MODULE = r"""
class Acc { constructor() { this.n = 0; } add(x) { if (x > 900) throw new RangeError("too big: " + x); this.n += x; return this; } }
const a = new Acc();
let i = 0;
try { for (; i < 1000; i++) a.add(i); } catch (e) { console.log("caught", e.message, a.n, i); }
function strictWrite(o) { "use strict"; for (let k = 0; k < 100; k++) o.frozen = k; }
const o = Object.freeze({ frozen: 1 });
strictWrite(o);
console.log("unreachable");
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_uncaught_error_in_module(run, workdir, tier):
    """CATCHES: ES-module top-level code whose hot method throw is not caught at the right iteration, or whose strict-mode write to a frozen property inside a compiled loop does not abort the module with the reference's uncaught-error report and exit status 1."""
    write_files(workdir, {"mod.mjs": UNCAUGHT_MODULE})
    r = run([*tier, "mod.mjs"], timeout=90)
    assert r.returncode == 1
    assert r.stdout == b"caught too big: 901 405450 901\n"
    assert r.stderr == golden(__file__, "uncaught_module_stderr")


PROG_OWNER_CAPTURES = r"""function ownerUpdates(n) {
  var count = 0, total = 0, big = 0n, label = "";
  let blockLet = 1;
  const read = () => count + total + blockLet;
  for (var i = 0; i < n; i++) {
    count++;
    ++count;
    count--;
    total += i;
    total -= 1;
    total *= 1;
    blockLet <<= 0;
    blockLet += 1;
    big++;
    label += i % 10;
  }
  var tdz = "";
  try { lateLet++; } catch (e) { tdz = e.name; }
  let lateLet = 0;
  const peek = () => lateLet;
  return [count, total, blockLet, big, label.length, read(), tdz, peek()].join(",");
}
function capturedDestructure() {
  var [da, db] = [1, 2];
  var { dx, dy } = { dx: 3, dy: 4 };
  const grab = () => da + db + dx + dy;
  da = 10;
  return grab();
}
function forInCompiled(n) {
  var o = { a: 1, b: 2, c: 3 }, keys = "", t = 0;
  for (var r = 0; r < n; r++) {
    for (const k in o) { t += o[k]; if (r === 0) keys += k; }
    for (const k in [5, 6]) t += +k;
    for (let k in "ab") t += k.length;
  }
  var p = Object.create(o); p.own = 9;
  for (const k in p) keys += k;
  var del = { x: 1, y: 2, z: 3 };
  for (const k in del) { keys += k; delete del.y; del.w = 1; }
  var arr = [1, 2, 3]; arr.extra = true;
  for (const k in arr) keys += k;
  for (const k in null) keys += "never";
  for (const k in 7) keys += "never";
  return t + ":" + keys;
}
function nullElems() {
  var out = [];
  var targets = [null, undefined];
  for (var i = 0; i < 2; i++) {
    var b = targets[i];
    try { b[0]; } catch (e) { out.push(e.message); }
    try { b[0] = 1; } catch (e) { out.push(e.name); }
    try { b.x; } catch (e) { out.push(e.message); }
    try { b.x = 1; } catch (e) { out.push(e.message); }
    try { b[0]++; } catch (e) { out.push(e.name); }
    try { b.m(); } catch (e) { out.push(e.name); }
    try { b[1](); } catch (e) { out.push(e.name); }
  }
  return out.join(" | ");
}
function keyKinds(n) {
  var o = {}, arr = ["a", "b"];
  o[1] = "one"; o["1.5"] = "frac"; o[true] = "t"; o[null] = "n"; o[undefined] = "u";
  var t = "";
  var kobj = { toString: function () { return "0"; } };
  for (var i = 0; i < n; i++) {
    t = o[1] + o["1"] + o[1.5] + o[true] + o[null] + o[undefined] + arr["1"] + arr[1.0] + arr[-0] + arr["01"] + arr[kobj];
  }
  arr["2"] = "c"; arr[3.0] = "d"; arr["x"] = "e";
  return t + " " + arr.length + " " + Object.keys(arr).join("");
}
function viaInlined(n) {
  var small = function (a) { return a * 2 + 1; };
  var call = function (f, v) { return f(v); };
  var t = 0;
  for (var i = 0; i < n; i++) { t += small(i) + call(small, i); }
  var orig = small;
  small = function (a) { return -a; };
  for (var i = 0; i < 50; i++) t += small(i) + call(orig, i);
  return t;
}
console.log(ownerUpdates(3000));
console.log(capturedDestructure());
console.log(forInCompiled(200));
console.log(nullElems());
console.log(keyKinds(200));
console.log(viaInlined(3000));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_owner_captured_updates_and_for_in(run, tier):
    """CATCHES: compiled functions that update their own closure-captured var/let bindings (++/--/compound/BigInt/TDZ) inconsistently with the closures reading them, mis-enumerate for-in (inherited keys, deletion/addition during the loop, arrays with extra keys, null/primitive bases) or coerce property keys differently."""
    check_prog(run, tier, PROG_OWNER_CAPTURES, "owner_captures")


PROG_COMPILED_ITERATION = r"""function forOfArray(n) {
  var a = [];
  for (var i = 0; i < n; i++) a.push(i % 17);
  var s = 0, cnt = 0;
  for (const v of a) { s += v; if (v === 16) cnt++; }
  for (let v of a) { if (v > 15) break; s -= 1; }
  for (const v of a) { if (v & 1) continue; s += 2; }
  return s + "," + cnt;
}
function forOfDestructure(n) {
  var pairs = [];
  for (var i = 0; i < n; i++) pairs.push([i, i * 2, "x" + i]);
  var s = 0, last = "";
  for (const [a, b, c] of pairs) { s += a + b; last = c; }
  for (const { id, val } of [{ id: 1, val: 2 }, { id: 3, val: 4 }]) s += id * val;
  return s + "," + last;
}
function forOfDefaults() {
  var last = "";
  for (const [a, , c = "dflt"] of [[1], [2, 3], [4, 5, 6]]) last += a + c;
  return last;
}
function forOfCollections(n) {
  var m = new Map(), st = new Set();
  for (var i = 0; i < n; i++) { m.set(i % 97, i); st.add(i % 89); }
  var s = 0;
  for (const [k, v] of m) s += k * 2 + v;
  for (const v of st) s += v;
  for (const k of m.keys()) s -= k;
  for (const v of m.values()) s += v & 3;
  for (const [k, v] of m.entries()) if (k === 5) s += v;
  for (const v of st.values()) s ^= v;
  var str = "";
  for (const ch of "héllo👍") str += ch.length;
  return s + "," + str + "," + m.size + "," + st.size;
}
function forOfGenerators(n) {
  var gen = function* (k) { for (var i = 0; i < k; i++) yield i * 3; };
  var s = 0;
  for (var r = 0; r < n; r++) for (const v of gen(10)) { if (v > 20) break; s += v; }
  var closed = 0;
  var iterable = {};
  iterable[Symbol.iterator] = function () {
    var i = 0;
    return { next: function () { i++; return { value: i, done: i > 4 }; }, return: function () { closed++; return {}; } };
  };
  for (var r = 0; r < 10; r++) for (const v of iterable) { if (v === 2) break; s += v; }
  for (var r = 0; r < 10; r++) { try { for (const v of iterable) { if (v === 3) throw new Error("x"); } } catch (e) { s += 100; } }
  return s + "," + closed;
}
function rotate(n) {
  var a = 1, b = 2, c = 3, s = 0;
  for (var i = 0; i < n; i++) {
    [a, b, c] = [b, c, a];
    var [x, y = 10, z] = [i, undefined, i * 2];
    s += x + y + z;
  }
  return [a, b, c, s].join(",");
}
function destructAssign(n) {
  var s = 0;
  for (var i = 0; i < n; i++) {
    var [x, y, z] = [i, 10, i * 2];
    s += x + y + z;
    var [p, q] = "ab";
    var [first, second] = new Set([i, i + 1]);
    s += first + second + p.length + q.length;
  }
  var [m0, m1] = new Map([[1, 2], [3, 4]]);
  var [u1, u2, u3] = [1];
  return [s, m0.join(":"), m1.join(":"), u2, u3].join(",");
}
function collectionsCompiled(n) {
  var m = new Map(), s = new Set(), w = new WeakMap(), keyObjs = [];
  for (var i = 0; i < 16; i++) keyObjs.push({ i: i });
  var hits = 0, total = 0;
  for (var i = 0; i < n; i++) {
    var k = i % 64;
    if (m.has(k)) { total += m.get(k); hits++; } else m.set(k, i);
    s.add("s" + (i % 33));
    var ko = keyObjs[i & 15];
    w.set(ko, (w.get(ko) || 0) + 1);
    if (i % 7 === 0) m.delete(k);
    if (s.has("s3")) total++;
  }
  var nan = new Map();
  for (var i = 0; i < 100; i++) { nan.set(NaN, i); nan.set(-0, i); nan.set(0, -i); }
  return [hits, total, m.size, s.size, w.get(keyObjs[3]), nan.size, nan.get(NaN), nan.get(0), Object.is(nan.keys().next().value, NaN)].join(",");
}
function patchedCollections(n) {
  var m = new Map([[1, 10]]), s = new Set([1]);
  var t = 0;
  var origGet = Map.prototype.get, origHas = Set.prototype.has, origSet = Map.prototype.set, origAdd = Set.prototype.add;
  for (var i = 0; i < n; i++) {
    t += m.get(1) + (s.has(1) ? 1 : 0);
    m.set(2, i); s.add(i & 7);
    if (i === 100) { Map.prototype.get = function (k) { return 1000; }; Set.prototype.has = function () { return false; }; }
    if (i === 200) { Map.prototype.set = function () { t += 0.5; return this; }; Set.prototype.add = function () { t += 0.25; return this; }; }
  }
  Map.prototype.get = origGet; Set.prototype.has = origHas; Map.prototype.set = origSet; Set.prototype.add = origAdd;
  var notMap = { get: Map.prototype.get };
  var err = "";
  try { notMap.get(1); } catch (e) { err = e.name; }
  return t + "," + m.get(2) + "," + s.size + "," + err;
}
function subclassed() {
  var origGet = Map.prototype.get;
  var sub = new (class extends Map { get(k) { return "sub" + origGet.call(this, k); } })([[1, 1]]);
  var r = "";
  for (var i = 0; i < 20; i++) r = sub.get(1);
  return r;
}
console.log("forOfArray", forOfArray(5000));
console.log("forOfDestructure", forOfDestructure(3000));
console.log("forOfCollections", forOfCollections(3000));
console.log("forOfGenerators", forOfGenerators(200));
console.log("forOfDefaults", forOfDefaults());
console.log("rotate", rotate(1000));
console.log("destructAssign", destructAssign(2000));
console.log("subclassed", subclassed());
console.log("collectionsCompiled", collectionsCompiled(10000));
console.log("patchedCollections", patchedCollections(400));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_compiled_iteration_and_collections(run, tier):
    """CATCHES: compiled for-of/array-destructuring entry paths over arrays, Maps, Sets, strings, generators and user iterables (break/continue/throw closing via return()), and Map/Set/WeakMap get/set/has/add/delete fast paths that mishandle NaN/-0 keys or keep the builtin after Map.prototype/Set.prototype methods are replaced."""
    check_prog(run, tier, PROG_COMPILED_ITERATION, "compiled_iteration")


PROG_PARAM_DEFAULTS = r"""var G = 5;
var cfg = { scale: 3, list: [4, 5, 6] };
function d1(a, b = a + 1, c = b * 2 - a) { return [a, b, c].join("/"); }
function d2(a, b = a > 2 ? "big" : "small", c = !a, d = -a, e = typeof a) { return [b, c, d, e].join("/"); }
function d3(a, b = cfg.scale * a, c = cfg.list[a % 3], d = Math.max(a, G)) { return [b, c, d].join("/"); }
function d4(a, b = [a, a + 1], c = { k: a, j: b.length }) { return b.join("+") + "/" + c.k + c.j; }
function d5(a, b = a || "fallback", c = a && "both", d = a ?? "nullish") { return [b, c, d].join("/"); }
function d6(a, b = /x+/g, c = this, d = `t${a}`) { return [b.source, b.lastIndex, typeof c, d].join("/"); }
function d7(a, b = a++, c = a) { return [a, b, c].join("/"); }
function d8(a, b = new Array(a).length, c = String(a).length) { return [b, c].join("/"); }
function d9(a = 1, b = 2) { var f = function () { return a + b; }; a = 10; return f(); }
function d10(a = [], b = {}, c = "", d = null, e = 0n) { a.push(1); var g = function () { return a.length + Object.keys(b).length + c + d + e; }; return g(); }
function d11(a, b = function () { return a * 2; }) { return b(); }
function d12(a = b, b = 1) { return a + b; }
function d13(a, b = (() => a + 100)()) { return b; }
function d14(x = 1) { function x() {} return typeof x; }
function d15(a, b = G++) { return b; }
function run(n) {
  var out = [];
  for (var i = 0; i < n; i++) {
    var row = [d1(i), d1(i, 0), d1(i, undefined, 7), d2(i), d2(0, null), d3(i), d3(i, 9, 9, 9), d4(i), d5(i), d5(0), d5(null),
      d6(i), d7(i), d7(i, "B"), d8(i % 5), d9(), d9(3, 4), d10(), d11(i), d13(i), d14(), d14(undefined)];
    if (i === n - 1 || i === 0) out.push(row.join(" "));
  }
  var e = "";
  try { d12(); } catch (err) { e = err.name; }
  var before = G, r15 = d15(1), r15b = d15(1, 7);
  out.push(e + " " + d12(3) + " " + r15 + " " + r15b + " " + (G - before));
  return out.join("\n");
}
console.log(run(300));
console.log(d1.length, d2.length, d6.length, d12.length, (function (a, b = 1, c) {}).length);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_parameter_defaults(run, tier):
    """CATCHES: compiled default-parameter lowering that evaluates defaults for null (not only undefined), in the wrong order, against later params (TDZ ReferenceError), loses side effects (a++, G++), shares literal default objects between calls, or mishandles captured defaulted params, this/regex/template defaults and Function.length."""
    check_prog(run, tier, PROG_PARAM_DEFAULTS, "param_defaults")


PROG_ASYNC_VM = r"""var trace = [];
async function step(i) { if (i % 5 === 4) throw new RangeError("step" + i); return i * 2; }
async function loopAwait(n) {
  var s = 0, errs = 0;
  for (var i = 0; i < n; i++) {
    try {
      s += await step(i);
      if (i % 3 === 0) s += await i;
      else if (i % 3 === 1) s += await Promise.resolve(1);
      else s += await { then: function (r) { r(2); } };
    } catch (e) {
      errs++;
      if (!(e instanceof RangeError)) throw e;
    }
  }
  return s + "/" + errs;
}
async function exprAwait(n) {
  var acc = [];
  for (var i = 0; i < n; i++) {
    var v = (await i) + (await (i + 1)) * 2;
    var c = (await (i & 1)) ? "odd" : "even";
    var arr = [await i, await "x"];
    var obj = { a: await i, b: arr.length };
    if (i === n - 1) acc.push(v, c, arr.join(""), obj.a + obj.b);
  }
  return acc.join(",");
}
var asyncArrow = async (x) => { var y = await x; return y + 1; };
async function returnAwait() {
  try { return await Promise.reject(new TypeError("inner")); } catch (e) { return "caught " + e.message; }
}
async function returnNoAwait() {
  try { return Promise.reject(new TypeError("escapes")); } catch (e) { return "never"; }
}
async function nested(depth) { if (depth === 0) return 0; return 1 + await nested(depth - 1); }
async function closureAwait() {
  var count = 0;
  var bump = async function () { count++; await null; count += 10; return count; };
  var a = bump(), b = bump();
  trace.push("sync count " + count);
  var r = await a + await b;
  return r + "/" + count;
}
async function ordering() {
  var log = [];
  var p1 = (async function () { log.push("a1"); await null; log.push("a2"); await null; log.push("a3"); })();
  var p2 = (async function () { log.push("b1"); await undefined; log.push("b2"); })();
  Promise.resolve().then(function () { log.push("then1"); }).then(function () { log.push("then2"); });
  log.push("sync");
  await p1; await p2;
  log.push("done");
  return log.join(" ");
}
async function thrower() { await null; null.prop; }
async function main() {
  trace.push("loopAwait " + await loopAwait(200));
  trace.push("exprAwait " + await exprAwait(100));
  var arrows = 0;
  for (var i = 0; i < 100; i++) arrows += await asyncArrow(i);
  trace.push("arrows " + arrows);
  trace.push("returnAwait " + await returnAwait());
  try { await returnNoAwait(); } catch (e) { trace.push("returnNoAwait " + e.message); }
  trace.push("nested " + await nested(50));
  trace.push("closureAwait " + await closureAwait());
  trace.push("ordering " + await ordering());
  try { await thrower(); } catch (e) { trace.push("thrower " + e.name); }
  var all = await Promise.all([loopAwait(10), exprAwait(5), nested(3)]);
  trace.push("all " + all.join("|"));
  var p = step(4);
  p.catch(function (e) { trace.push("late catch " + e.message); });
  await null; await null;
}
main().then(function () { console.log(trace.join("\n")); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_async_functions_on_vm(run, tier):
    """CATCHES: bytecode-VM coroutine bugs in compiled async functions: await inside loops/try/conditions/array and object literals, thenables, async arrows and closures sharing state, return await vs returned rejections, deep async recursion, and interleaving order of several coroutines with plain promise reactions."""
    check_prog(run, tier, PROG_ASYNC_VM, "async_vm")
