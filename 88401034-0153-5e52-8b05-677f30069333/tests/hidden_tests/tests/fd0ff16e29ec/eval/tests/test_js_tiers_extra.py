"""Additional execution-tier agreement tests (tree-walking interpreter vs bytecode VM vs JIT).

Every program runs under all three tiers against ONE shared golden: the documented contract is
that `--tier=interp`, `--tier=bytecode` and the default JIT tier produce identical output. The
programs target the native JIT's specialised regions (numeric register chains, branchy numeric
loops, record-scan loops, guarded field writes, oversized frames/functions/code and perturbed
Richards scheduler shapes) so that every fast path and every decline/fallback is exercised.
"""

import pytest

from conftest import golden

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


def check_prog(run, tier, prog, name):
    # Each program takes well under a second on the reference build; the generous timeout only
    # matters for slow instrumented builds of the same binary.
    r = run([*tier, "-e", prog], timeout=90)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


PROG_CHAINS = r"""// Straight-line numeric register chains over several array receivers.
function mk(n, k) { var x = []; for (var i = 0; i < n; i++) x.push((i * k) % 17 + 0.5); return x; }
function mix4(a, b, c, d, n) {
  for (var r = 0; r < 3; r++) {
    for (var i = 0; i < n; i++) d[i] = a[i] + b[i] * c[i] - d[i] / 2;
  }
  return d[0] + d[n - 1];
}
var s = 0;
for (var t = 0; t < 30; t++) s += mix4(mk(50, 3), mk(50, 5), mk(50, 7), mk(50, 11), 50);
console.log("mix4", s);
function five(a, b, c, d, e, i) { return a[i] + b[i] + c[i] + d[i] + e[i]; }
var A = mk(20, 1), B = mk(20, 2), C = mk(20, 3), D = mk(20, 4), E = mk(20, 5);
var s2 = 0;
for (var t = 0; t < 3000; t++) s2 += five(A, B, C, D, E, t % 20);
console.log("five", s2, five(A, B, C, D, E, 25), five(A, B, C, D, [1, 2], 1));
function holey4(a, b, c, d, i) { a[i] = b[i] + c[i] + d[i]; return a[i]; }
var H = [1, , 3, 4], s3 = 0;
for (var t = 0; t < 3000; t++) s3 += holey4(H, A, B, C, t % 4) || 0;
console.log("holey", s3, H.length, 1 in H, H.join("|"));
function swapRecv(a, b, i) { var t = a[i] + b[i]; a = b; return t + a[i]; }
var s4 = 0;
for (var t = 0; t < 3000; t++) s4 += swapRecv(A, B, t % 20);
console.log("swap", s4);
function keep(a, b, n) { var s = 0; for (var i = 0; i < n; i++) s += (a[i] = b[i] * 2); return s; }
var K = [], L = [];
for (var i = 0; i < 32; i++) { K.push(0); L.push(i + 0.5); }
var ks = 0;
for (var t = 0; t < 100; t++) ks += keep(K, L, 32);
console.log("keep", ks, K[31], K.length);
function keep4(a, b, c, d, i) { return (d[i] = a[i] + b[i] + c[i] + c[i + 1]) + (d[i + 1] = c[i] * 2); }
var M = L.slice(), N = K.slice(), k4 = 0;
for (var t = 0; t < 2000; t++) k4 += keep4(K, L, M, N, t % 30);
console.log("keep4", k4, N[5], N[30]);
function updRecv(a, i) { var s = a[i] * 2 + a[i + 1]; a++; return s + (a !== a ? 1 : 0); }
var ur = 0;
for (var t = 0; t < 2000; t++) ur += updRecv(L, t % 30);
console.log("updRecv", ur);
function preIdx(a, i) { return a[++i]; }
function preDec(a, i) { return a[--i]; }
var arr = [10, 20, 30, 40, 50], u = 0;
for (var t = 0; t < 3000; t++) u += preIdx(arr, t % 4) + preDec(arr, (t % 4) + 1);
console.log("preIdx", u, preIdx(arr, 4), preIdx("abc", 0), preDec([1.5, 2.5], 1), preIdx({ 1: "one" }, 0));
// late type changes reach the guarded slow paths of the compiled chains
A[3] = "7"; B[4] = null; C[5] = undefined; L[6] = 2.25;
console.log("late", five(A, B, C, D, E, 3), five(A, B, C, D, E, 4), five(A, B, C, D, E, 5), keep(K, L, 8), K[6]);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_numeric_chains_many_receivers(run, tier):
    """CATCHES: register-chain fusion that mishandles three to five distinct array receivers in one straight-line expression (classic vs mirror receiver caches), holes, kept assignment values `s += (a[i] = v)`, receiver reassignment or `a++` mid-chain, `a[++i]`/`a[--i]` keys, or late string/null/undefined elements."""
    check_prog(run, tier, PROG_CHAINS, "chains")


_MANY_VARS = "  var " + ", ".join("v%d" % i for i in range(270)) + ";"
PROG_FRAMES = r"""
function big(a) {
%(vars)s
  v0 = a; v269 = a * 2; v135 = v0 + v269;
  return v135 + v0 + (v200 === undefined ? 1000 : 0);
}
function BigCtor(a) {
%(vars)s
  v1 = a; v268 = a + 1;
  this.s = v1 + v268 + (v7 === undefined ? 0.5 : 0);
}
function drive1(n) { var t = 0; for (var k = 0; k < n; k++) { t += big(k, k, k); t += new BigCtor(k).s; } return t; }
console.log("bigFrame", drive1(300), drive1(10), big(3), new BigCtor(4).s);
function Pt(x) { this.x = x; }
function drive2(n) { var u = 0; for (var k = 0; k < n; k++) u += new Pt(k, "extra", {}, [k]).x; return u; }
console.log("surplusNew", drive2(500));
function Reset(a) { for (var a = 0; a < 3; a++) this.v = (this.v || 0) + a; this.a = a; }
function reset(a) { var s = 0; for (var a = 0; a < 3; a++) s += a; return s + a; }
function drive3(n) { var w = 0; for (var k = 0; k < n; k++) { var r = new Reset(k); w += r.v + r.a + reset(k); } return w; }
console.log("forceReset", drive3(500), reset(), reset(100), new Reset("x").a);
""" % {"vars": _MANY_VARS}


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_large_frames_and_for_var_resets(run, tier):
    """CATCHES: JIT call/construct frames that overflow the fixed frame buffer when a function has 270+ locals (the pooled oversized-frame path), drop surplus constructor arguments wrongly, or forget that `for (var a = 0; ...)` re-initializes a same-named parameter in both calls and constructors."""
    check_prog(run, tier, PROG_FRAMES, "frames")


PROG_CFG = r"""// Numeric loops with general control flow: shapes the register-resident CFG region must reject
// or handle (too many locals, five arrays, receivers used as values, deep operand stacks,
// more than six guarded inputs, comparisons inside expressions, overlapping register homes).
function nine(n) {
  var a = 1, b = 2, c = 3, d = 4, e = 5, f = 6, g = 7, h = 8, k = 0;
  for (var i = 0; i < n; i++) {
    if (i < 700) { a += b * 0.001; b -= c * 0.0005; } else { c += d * 0.001; d = d * 0.9999 - e * 0.001; }
    e += f / 7000; f -= g * 0.0001; g += h * 0.0001; h = h * 0.999 + k * 0.001; k += 0.25;
  }
  return [a, b, c, d, e, f, g, h, k].map(function (x) { return x.toFixed(4); }).join(",");
}
console.log("nine", nine(2000));
function fiveArrays(p, q, r, s, t, n) {
  var acc = 0;
  for (var i = 0; i < n; i++) { if (p[i] < q[i]) acc += r[i]; else acc -= s[i] * t[i]; }
  return acc;
}
var P = [], Q = [], R = [], S = [], T = [];
for (var i = 0; i < 64; i++) { P.push(i % 7); Q.push(i % 5); R.push(i * 0.5); S.push(i % 3); T.push(1.5); }
var fa = 0;
for (var k = 0; k < 40; k++) fa += fiveArrays(P, Q, R, S, T, 64);
console.log("fiveArrays", fa);
function recvLocal(arr, n) {
  var s = 0, t = 0;
  for (var i = 0; i < n; i++) { if (arr[i] > 2) s += arr[i]; else t = arr; }
  return s + (t === arr ? 1 : 0);
}
var rl = 0;
for (var k = 0; k < 60; k++) rl += recvLocal(P, 64);
console.log("recvLocal", rl);
function inputLocal(o, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (i < o.lim) s += o.w; else s -= 1; if (s > 1e9) o = 0; }
  return s;
}
var il = 0;
for (var k = 0; k < 60; k++) il += inputLocal({ lim: 10, w: 2.5 }, 50);
console.log("inputLocal", il);
function deep(n) {
  var a = 1, b = 2, c = 3, s = 0;
  for (var i = 0; i < n; i++) {
    if (i < 1500) s += a; else s += (a + (b + (c + (a + (b + (c + (a + (b + (c + (a + i))))))))));
  }
  return s;
}
console.log("deep", deep(3000));
function sevenInputs(o, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (s < 1e6) s += o.a + o.b + o.c + o.d + o.e + o.f + o.g; else s = 0; }
  return s;
}
var si = 0;
for (var k = 0; k < 40; k++) si += sevenInputs({ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 }, 100);
console.log("sevenInputs", si);
function ternaryCmp(n) {
  var s = 0, x = 0.5;
  for (var i = 0; i < n; i++) { s += (x < 0.7 ? 1 : 2); x = x * 1.5; if (x > 10) x = x - 9.75; }
  return s;
}
console.log("ternaryCmp", ternaryCmp(3000));
function preserve(n) {
  var x = 1, y = 0;
  for (var i = 0; i < n; i++) {
    y = x + (x = x * 1.5);
    if (x > 1000) x = x / 999;
    y = y - (x = x + 1) * 0;
  }
  return x.toFixed(6) + ":" + y.toFixed(6);
}
console.log("preserve", preserve(2000));
function Box(w) { this.w = w; this.scale = 1.5; }
Box.prototype.total = function (n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (i < this.w) s = s + this.w * this.scale; else s = s - 1; }
  return s;
};
var bx = new Box(40), bt = 0;
for (var k = 0; k < 50; k++) bt += bx.total(100);
bx.scale = "2";
console.log("thisInputs", bt, bx.total(100));
function cfgOps(n) {
  var a = 0, b = 1, c = 0, j = 0;
  for (var i = 0; i < n; i++) {
    if (a < 100) { a = -b + a + 3; c = b = a * 0.5; } else { a = a - 150; }
    j++;
    c = j++ + ++j - c-- + --c;
    a + 1;
  }
  return [a, b, c, j].join(",");
}
console.log("cfgOps", cfgOps(500));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_numeric_cfg_region_limits(run, tier):
    """CATCHES: numeric branchy-loop regions that accept (and miscompile) loops with nine locals, five array receivers, an array also used as a value, a property input whose receiver is reassigned, operand stacks deeper than eight, seven property inputs, comparisons inside expressions, overlapping register homes (`y = x + (x = x * 1.5)`), `this.` inputs, or negation/dup/pop/++ value steps."""
    check_prog(run, tier, PROG_CFG, "cfg")


PROG_DIAMOND = r"""function fin(x) { return x; }
var LIMIT = 4, SLIMIT = "4";
function W(v2) { this.v2 = v2; this.other = 0; }
W.prototype.ok = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
W.prototype.shape = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.other = 1; packet.a2[i] = this.v2; }
  return fin(this.v2 + this.other);
};
W.prototype.limitStr = function (packet) {
  for (var i = 0; i < SLIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
W.prototype.thrFrac = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26.5) this.v2 = 1; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
W.prototype.resetFrac = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 0.5; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
W.prototype.protoArr = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
W.prototype.poly = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
W.prototype.exitEarly = function (packet) {
  for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; packet.a2[i] = this.v2; }
  return fin(this.v2);
};
function Pk() { this.a2 = new Array(4); }
function ProtoPk() {}
ProtoPk.prototype.a2 = [0, 0, 0, 0];
function V(v2) { this.extra = 1; this.v2 = v2; }
V.prototype = W.prototype;
var out = [];
function drive(name, mkPacket, mkTask) {
  var t = mkTask(3), s = 0, p = mkPacket();
  for (var k = 0; k < 400; k++) { s += t[name](p); if (k % 2 && mkTask === mixTask) t = mkTask(k); }
  out.push(name + "=" + s + ":" + p.a2.join("|"));
}
var flip = 0;
function mixTask(v) { flip++; return flip % 2 ? new W(v) : new V(v); }
function wTask(v) { return new W(v); }
drive("ok", function () { return new Pk(); }, wTask);
drive("shape", function () { return new Pk(); }, wTask);
drive("limitStr", function () { return new Pk(); }, wTask);
drive("thrFrac", function () { return new Pk(); }, wTask);
drive("resetFrac", function () { return new Pk(); }, wTask);
drive("protoArr", function () { return new ProtoPk(); }, wTask);
drive("poly", function () { return new Pk(); }, mixTask);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_counter_fill_loop_variants(run, tier):
    """CATCHES: the specialised `this.v2++; if (this.v2 > K) this.v2 = R; p.a2[i] = this.v2` fill-loop region applied when the reset writes a different field, the bound is a string global, the threshold or reset is fractional, the array lives on the prototype, or the receiver shape is polymorphic."""
    check_prog(run, tier, PROG_DIAMOND, "diamond")


PROG_MIXED = r"""// Object-heavy loops (array-of-records scans) run by the borrowed shadow-stack region:
// truthiness of booleans/numbers/null/undefined, equality and relational branches, value
// comparisons, this-property reads/writes, ++/-- values, plus late type changes that force
// the guarded exits back to the baseline templates.
function mk(n) {
  var a = [];
  for (var i = 0; i < n; i++)
    a.push({ v: i * 1.5, w: i % 7, k: i, flag: i % 3 === 0, cnt: i % 4, opt: i % 5 === 0 ? null : (i % 5 === 1 ? undefined : i) });
  return a;
}
function truthy(a) {
  var s = 0;
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    if (o.flag) s += o.v;
    if (o.cnt) s += 1;
    if (o.opt) s += 0.5;
  }
  return s;
}
function eqs(a) {
  var s = 0;
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    if (o.cnt == 2) s += 3;
    if (o.opt === null) s += 7;
    if (o.opt != undefined) s -= 1;
    if (o.cnt !== 1) s += o.cnt;
  }
  return s;
}
function writes(a) {
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    o.v = o.v * 0.5 + i;
    if (o.flag) o.cnt = o.cnt + 1;
  }
  return a[a.length - 1].v + a[3].cnt;
}
function Acc(items) { this.items = items; this.total = 0; this.scale = 2; this.hits = 0; }
Acc.prototype.run = function () {
  var a = this.items;
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    this.total = this.total + o.v * this.scale;
    if (o.w >= 3) this.hits = this.hits + 1;
    if (o.w <= 1) this.hits = this.hits + 2;
    if (o.w > 5) this.total = this.total - 1;
    if (o.w != 4) this.total = this.total + 0.25;
  }
  return this.total + this.hits;
};
function cmpvals(a) {
  var s = 0, lt, ge, eq, ne, le, gt;
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    lt = o.w < 3; ge = o.v >= 9; eq = o.w == 2; ne = o.w !== 4; le = o.w <= 1; gt = o.v > 30;
    if (lt) s += 1;
    if (ge) s += 2;
    if (eq) s += 4;
    if (ne) s += 8;
    if (le) s += 16;
    if (gt) s += 32;
  }
  return s;
}
function counters(a) {
  var s = 0, j = 0, q = 100;
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    var x = j++;
    var y = ++j;
    var z = q--;
    var u = --q;
    s += o.v + x + y - z + u;
  }
  return s;
}
function dups(a) {
  var s = 0, x, y;
  for (var i = 0; i < a.length; i++) {
    var o = a[i];
    x = y = o.v;
    s = s + x + y;
    a[i].k += 1;
  }
  return s;
}
function destr(arr) { var s = 0; for (var i = 0; i < arr.length; i++) { const { x, y } = arr[i]; s += x * y; } return s; }
var DA = [];
for (var i = 0; i < 40; i++) DA.push({ x: i, y: i % 3 });
var dsum = 0;
for (var k = 0; k < 100; k++) dsum += destr(DA);
DA[7] = { x: "2", y: 4 };
console.log("destructure", dsum, destr(DA));
function mk2(n) { var a = []; for (var i = 0; i < n; i++) a.push({ v: i * 1.5, w: i % 7, k: i }); return a; }
var acc2 = new Acc(mk2(48)), r0 = 0;
for (var k = 0; k < 60; k++) r0 = acc2.run();
console.log("acc", r0, acc2.hits);
var A = mk(64), out = [];
var t = 0, e = 0, w = 0;
for (var k = 0; k < 80; k++) { t += truthy(A); e += eqs(A); }
for (var k = 0; k < 20; k++) w += writes(A);
out.push("scan " + t + " " + e + " " + w.toFixed(4));
var acc = new Acc(A), r1 = 0, r2 = 0, r3 = 0, r4 = 0;
for (var k = 0; k < 60; k++) { r1 = acc.run(); r2 += cmpvals(A); r3 += counters(A); r4 += dups(A); }
out.push("records " + r1 + " " + r2 + " " + r3 + " " + r4 + " " + A[10].k);
A[5].flag = "yes"; A[6].cnt = "2"; A[7].opt = 10n; A[8] = { v: 1, flag: {}, cnt: 0, opt: [], w: "3", k: 0 };
A[9].w = null; A[11].v = "4.5";
t = 0; e = 0;
for (var k = 0; k < 5; k++) { t += truthy(A); e += eqs(A); }
out.push("changed " + t + " " + e + " " + cmpvals(A) + " " + acc.run() + " " + counters(A));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_record_scan_shadow_loops(run, tier):
    """CATCHES: object-scan loop regions that get truthiness of booleans/numbers/null/undefined/objects/strings/BigInts wrong, mis-evaluate ==/===/!=/<=/>= on record fields or as stored booleans, lose this-property writes, ++/-- results or chained assignments, or fail to exit cleanly after fields change type."""
    check_prog(run, tier, PROG_MIXED, "mixed")


PROG_LINEAR = r"""function bits(a, n) {
  var h = 0, g = 0, x = 7;
  for (var i = 0; i < n; i++) { h = h ^ a[i]; g = g | (i & 12); x = (x << 1) >>> 3; h = h >> 1; }
  return h + ":" + g + ":" + x;
}
function popLoop(n) {
  var s = 0;
  for (var i = 0; i < n; i++) { s + 1; s = s + i; }
  return s;
}
function neLoop(n) {
  var s = 0, i = 0;
  while (i !== n) { s = s + i * 2; i++; }
  return s;
}
function eqLoop(n) {
  var s = 0, i = 0;
  while (i == 0) { s = s + 1; i = (s > n) * 1; }
  return s;
}
function cmpVal(n) {
  var s = 0, b = 0;
  for (var i = 0; i < n; i++) { b = i < 5; s = s + i; }
  return s + ":" + b;
}
function manyArrays(a, b, c, d, e, f, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { s = s + a[i] + b[i] + c[i] + d[i] + e[i] + f[i]; }
  return s;
}
function storedRecv(a, b, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { s = s + a[i]; a = b; }
  return s;
}
function pressureD(n) {
  var a = 0.5, b = 1.5, c = 2.5, d = 3.5, e = 4.5, f = 5.5, g = 6.5, h = 7.5, p = 8.5, q = 9.5, r = 10.5, t = 11.5;
  for (var i = 0; i < n; i++) {
    a = a + b * 0.5; b = b + c * 0.25; c = c + d * 0.125; d = d + e * 0.5; e = e + f * 0.25; f = f + g * 0.125;
    g = g + h * 0.5; h = h + p * 0.25; p = p + q * 0.125; q = q + r * 0.5; r = r + t * 0.25; t = t + a * 0.0001;
  }
  return [a, b, c, d, e, f, g, h, p, q, r, t].map(function (v) { return v.toExponential(6); }).join(",");
}
function pressureI(arr, n) {
  var a = 1, b = 2, c = 3, d = 4, e = 5, f = 6, g = 7, h = 8, p = 9, q = 10, r = 11, t = 12;
  for (var i = 0; i < n; i++) {
    a = (a + arr[b & 15]) | 0; b = (b + arr[c & 15]) | 0; c = (c + arr[d & 15]) | 0; d = (d ^ arr[e & 15]) | 0;
    e = (e + arr[f & 15]) | 0; f = (f + arr[g & 15]) | 0; g = (g ^ arr[h & 15]) | 0; h = (h + arr[p & 15]) | 0;
    p = (p + arr[q & 15]) | 0; q = (q + arr[r & 15]) | 0; r = (r ^ arr[t & 15]) | 0; t = (t + arr[a & 15]) | 0;
  }
  return [a, b, c, d, e, f, g, h, p, q, r, t].join(",");
}
function shifts(a, n) {
  var s = 0, u = 0, k = 0;
  for (var i = 0; i < n; i++) { k = a[i & 15] >>> 1; s = (s + (k << 2)) | 0; u = (u + (a[i & 15] >> 3)) | 0; }
  return s + ":" + u;
}
function nameLoop(n) {
  var s = 0;
  for (var i = 0; i < n; i++) { s = s + K1 * i - K2; }
  return s;
}
function varBits(a, n) { var s = 0, m = 5, sh = 2; for (var i = 0; i < n; i++) { s = (s + (a[i] & m)) | 0; s = s + (a[i] >> sh); m = 7; } return s; }
function arr3(a, b, c, n) { var s = 0; for (var i = 0; i < n; i++) { s = s + a[i] * b[i] - c[i]; } return s; }
function arr4(a, b, c, d, n) { var s = 0; for (var i = 0; i < n; i++) { s = s + a[i] * b[i] - c[i] + d[i]; } return s; }
function arr5(a, b, c, d, e, n) { var s = 0; for (var i = 0; i < n; i++) { s = s + a[i] * b[i] - c[i] + d[i] * e[i]; } return s; }
function intMany(a, n) {
  var x0 = 0, x1 = 1, x2 = 2, x3 = 3, x4 = 4, x5 = 5, x6 = 6, x7 = 7, x8 = 8;
  for (var i = 0; i < n; i++) {
    x0 = (x0 + a[i]) | 0; x1 = (x1 ^ a[i]) | 0; x2 = (x2 + x1) | 0; x3 = (x3 ^ x2) | 0; x4 = (x4 + x3) | 0;
    x5 = (x5 ^ x4) | 0; x6 = (x6 + x5) | 0; x7 = (x7 ^ x6) | 0; x8 = (x8 + x7) | 0;
  }
  return [x0, x1, x2, x3, x4, x5, x6, x7, x8].join(",");
}
var K1 = 3, K2 = 0.5;
var A = [], B = [];
for (var i = 0; i < 64; i++) { A.push((i * 37) % 101); B.push(i); }
var names = ["bits", "popLoop", "neLoop", "eqLoop", "cmpVal", "manyArrays", "storedRecv", "pressureD", "pressureI", "shifts", "nameLoop"];
var out = [];
for (var k = 0; k < 30; k++) {
  var r = [bits(A, 64), popLoop(100), neLoop(100), eqLoop(50), cmpVal(20), manyArrays(A, B, A, B, A, B, 64),
           storedRecv(A, B, 64), pressureD(50), pressureI(A, 64), shifts(A, 64), nameLoop(100)];
  if (k === 29) out = r;
}
for (var j = 0; j < names.length; j++) console.log(names[j], out[j]);
K1 = "3"; A[2] = 1.5; B[3] = -0;
var C = [], D = [], E = [];
for (var i = 0; i < 64; i++) { C.push(i % 5); D.push(i * 0.5); E.push(2); }
var r2 = [];
for (var k = 0; k < 30; k++) r2 = [varBits(A, 64), arr3(A, B, C, 64), arr4(A, B, C, D, 64), arr5(A, B, C, D, E, 64), intMany(A, 64)];
console.log("intLoops", r2.join(" "));
console.log("changed", nameLoop(10), bits(A, 8), shifts(A, 8), manyArrays(A, B, A, B, A, B, 8), pressureI(A, 4));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_linear_loop_chain_planner(run, tier):
    """CATCHES: register-resident linear loops that mistranslate ^ | << >>> >> int32 ops, discarded expression values, !== / == loop conditions, comparisons stored as booleans, six array receivers, a receiver reassigned inside the loop, global-name inputs, or that spill wrongly under twelve live doubles or twelve live int32 values."""
    check_prog(run, tier, PROG_LINEAR, "linear")


_HUGE_BODY = "\n".join("    s = g%d(s, i, %d);" % (j % 3, j % 11) for j in range(600))
PROG_HUGE_LOOP = r"""
function g0(a, b, c) { return (a + b + c) | 0; }
function g1(a, b, c) { return (a ^ b) + c; }
function g2(a, b, c) { return (a - c) | 0; }
function huge(m) {
  var s = 0;
  for (var i = 0; i < m; i++) {
%s
  }
  return s;
}
var t = [];
for (var k = 0; k < 5; k++) t.push(huge(k));
console.log("hugeCalls", t.join(","));
g1 = function (a, b, c) { return a - b; };
console.log("replaced", huge(2));
""" % _HUGE_BODY


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_loop_body_over_one_megabyte_of_code(run, tier):
    """CATCHES: a native code generator that cannot relax conditional branches (B.cond/CBZ) whose loop-exit target lies beyond the +-1 MiB range when a hot loop body holds 600 inlinable calls, producing wrong results or crashes instead of the interpreter's sums."""
    check_prog(run, tier, PROG_HUGE_LOOP, "huge_loop")


PROG_GUARDED = r"""// `if (cmp) obj.f = e1; else obj.f = e2;` diamonds (one field write on every path) for every
// relational/equality operator, nested branches, negated operands and odd operand types.
function G() { this.x = 0; this.y = 0.5; }
G.prototype.lt = function (a, b) { if (a < b) this.x = a - b; else this.x = -b; return this.x; };
G.prototype.le = function (a, b) { if (a <= b) this.x = a * 2; else this.x = b * -1; return this.x; };
G.prototype.gt = function (a, b) { if (a > b) this.x = -a; else this.x = b + 1; return this.x; };
G.prototype.ge = function (a, b) { if (a >= b) this.x = a + this.y; else this.x = b - this.y; return this.x; };
G.prototype.ne = function (a, b) { if (a != b) this.x = a / 2; else this.x = 0; return this.x; };
G.prototype.sne = function (a, b) { if (a !== b) this.x = -(a + b); else this.x = 1; return this.x; };
G.prototype.nest = function (a, b) { if (a < b) { if (a > 0) this.x = 1; else this.x = 2; } else this.x = 3; return this.x; };
G.prototype.neg = function (a, b) { this.y = -a * b + -this.y; return this.y; };
function local(o, a, b) { if (a < b) o.x = a; else o.x = b; return o.x; }
var g = new G(), o = { x: 0 }, s = 0;
for (var k = 0; k < 2000; k++) {
  var a = k % 7, b = (k * 3) % 5;
  s += g.lt(a, b) + g.le(a, b) + g.gt(a, b) + g.ge(a, b) + g.ne(a, b) + g.sne(a, b) + g.nest(a - 2, b) + local(o, a, b);
  if (k % 100 === 0) g.y = 0.5;
  s += g.neg(a, 0.001);
}
console.log("guarded", s.toFixed(6), g.x, g.y.toFixed(6), o.x);
g.lt("3", 2); g.ge(NaN, 1);
console.log("odd", g.lt("3", 2), g.ge(NaN, 1), g.ne(null, undefined), g.sne(-0, 0), g.neg("2", "3").toFixed(3));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_guarded_field_write_diamonds(run, tier):
    """CATCHES: branch-to-field-write regions that use the wrong condition code for < <= > >= != !== (including NaN, null/undefined and -0 operands), mishandle nested diamonds, negated operands, or writes through a local object instead of `this`."""
    check_prog(run, tier, PROG_GUARDED, "guarded")


PROG_LISTS = r"""// Linked-list tail scans `while ((peek = next.link) != null) next = peek;` and near-miss shapes.
function N(v) { this.link = null; this.v = v; }
function M(v) { this.v = v; this.link = null; }
function build(n, poly) { var h = null; for (var i = 0; i < n; i++) { var x = poly && i % 2 ? new M(i + 1) : new N(i + 1); x.link = h; h = x; } return h; }
function tailOf(q) { var peek, next = q; while ((peek = next.link) != null) next = peek; return next.v; }
function tailStrict(q) { var peek, next = q; while ((peek = next.link) !== null) next = peek; return next.v; }
function tailPoly(q) { var peek, next = q; while ((peek = next.link) != null) next = peek; return next.v; }
function noAdvance(q) { var peek, next = q, o = 0; while ((peek = next.link) != null) o = peek; return o; }
function undefScan(q) { var peek, next = q; while ((peek = next.link) != undefined) next = peek; return next.v; }
function P() { this.v = 5; }
P.prototype.link = null;
function tailProto(q) { var peek, next = q; while ((peek = next.link) != null) next = peek; return next.v; }
var pp = new P(), f = 0;
for (var k = 0; k < 300; k++) f += tailProto(pp);
console.log("protoLink", f);
var mono = build(30, false), poly = build(30, true), single = new N(7), out = [];
var a = 0, b = 0, c = 0, d = 0, e = 0;
for (var k = 0; k < 300; k++) { a += tailOf(mono); b += tailStrict(mono); c += tailPoly(poly); d += noAdvance(single); e += undefScan(mono); }
out.push("scan " + a + " " + b + " " + c + " " + d + " " + e);
var und = build(5, false); und.link.link.link = undefined;
out.push("undef " + tailOf(und) + " " + tailStrict(build(3, false)) + " " + undefScan(und));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_linked_list_tail_scans(run, tier):
    """CATCHES: the specialised linked-list tail-scan loop applied to near-miss shapes (a loop that never advances, `!= undefined` sentinels, prototype-inherited `link`, polymorphic node shapes, `!==` vs `!=` with an undefined link) and returning the wrong tail."""
    check_prog(run, tier, PROG_LISTS, "lists")


PROG_OVERSIZED = "function big(i){var s=0;" + "s+=i;" * 17000 + "return s;}\n" + r"""
var t = 0;
for (var k = 0; k < 20; k++) t += big(k);
console.log("bigops", t, big(0.5), big("1").length);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_function_with_more_than_65535_ops(run, tier):
    """CATCHES: a JIT that tries to compile a function whose bytecode exceeds 65535 ops (helper pcs no longer fit one immediate) instead of leaving it to the VM, corrupting the 17000-step accumulation of numbers and strings."""
    check_prog(run, tier, PROG_OVERSIZED, "oversized")


# The classic V8 "Richards" benchmark (identical to the canonical source used elsewhere). The JIT
# pattern-matches this exact program shape; each variant below perturbs one method or global so
# that a different part of the scheduler specialisation declines, falls back or emits its
# non-epoch variant. All tiers must still compute the same counts.
RICHARDS_BASE = r"""
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
"""

RICHARDS_DRIVER = r"""
COUNT = 400;
var res = [runRichards()];
COUNT = 8;
for (var w = 0; w < 120; w++) { var r = runRichards(); if (w % 40 === 0) res.push(r); }
res.push(runRichards());
console.log("%NAME%", res.join(" "));
var fs = freshScheduler(23);
fs.schedule();
console.log("graph", describe(fs));
"""

RICHARDS_VARIANTS = {
    # compound |= in markAsRunnable
    'markAlt': [('TaskControlBlock.prototype.markAsRunnable = function () {\n  this.state = this.state | STATE_RUNNABLE;', 'TaskControlBlock.prototype.markAsRunnable = function () {\n  this.state |= STATE_RUNNABLE;')],
    # IdleTask.run inherited from a grandparent prototype
    'idleDeep': [('IdleTask.prototype.run = function (packet) {', 'var IdleBase = Object.create(Object.prototype);\nIdleTask.prototype = Object.create(IdleBase);\nIdleBase.run = function (packet) {')],
    # strict null check in Packet.addTo
    'addToNull': [('  this.link = null;\n  if (queue == null) return this;', '  this.link = null;\n  if (queue === null) return this;')],
    # HandlerTask suspends through a local scheduler alias
    'handSuspAlt': [('  }\n  return this.scheduler.suspendCurrent();\n};\n\nHandlerTask.prototype.toString', '  }\n  var sc = this.scheduler;\n  return sc.suspendCurrent();\n};\n\nHandlerTask.prototype.toString')],
    # non-integral STATE_RUNNABLE global
    'stateConst': [('var STATE_RUNNING = 0;\nvar STATE_RUNNABLE = 1;', 'var STATE_RUNNING = 0;\nvar STATE_RUNNABLE = 1.5;')],
    # compound |= in markAsHeld
    'heldAlt': [('  this.state = this.state | STATE_HELD;', '  this.state |= STATE_HELD;')],
    # WorkerTask queues through a local scheduler alias
    'workQueueAlt': [('      packet.a2[i] = this.v2;\n    }\n    return this.scheduler.queue(packet);', '      packet.a2[i] = this.v2;\n    }\n    var sc = this.scheduler;\n    return sc.queue(packet);')],
    # whole program in strict mode
    'strict': [('\nfunction runRichards() {', "\n'use strict';\nfunction runRichards() {")],
    # Packet.addTo walks next.link without a temp
    'addToAlt': [('  while ((peek = next.link) != null)\n    next = peek;', '  while (next.link != null)\n    next = next.link;')],
    # strict equality on packet.kind
    'handKindAlt': [('    if (packet.kind == KIND_WORK) {', '    if (packet.kind === KIND_WORK) {')],
    # no second device task
    'noDeviceB': [('  scheduler.addDeviceTask(ID_DEVICE_B, 5000, null);\n\n  scheduler.schedule();', '  scheduler.schedule();')],
    # Scheduler.queue inherited from a grandparent prototype
    'schedDeep': [('var COUNT = 100;', 'var COUNT = 100;\nvar SchedBase = {};\nScheduler.prototype = Object.create(SchedBase);'), ('Scheduler.prototype.queue = function (packet) {', 'SchedBase.queue = function (packet) {')],
    # Scheduler.suspendCurrent inherited from a grandparent prototype
    'schedDeep2': [('var COUNT = 100;', 'var COUNT = 100;\nvar SchedBase = {};\nScheduler.prototype = Object.create(SchedBase);'), ('Scheduler.prototype.suspendCurrent = function () {', 'SchedBase.suspendCurrent = function () {')],
    # no worker task
    'noWorker': [('  scheduler.addWorkerTask(ID_WORKER, 1000, queue);\n', '')],
    # no idle task (nothing releases the devices)
    'noIdle': [('  scheduler.addIdleTask(ID_IDLE, 0, null, COUNT);\n\n  var queue', '  var queue')],
}


def richards_variant(name):
    src = RICHARDS_BASE
    for old, new in RICHARDS_VARIANTS[name]:
        assert old in src, (name, old)
        src = src.replace(old, new, 1)
    return src + RICHARDS_DRIVER.replace("%NAME%", name)


@pytest.mark.parametrize("variant", list(RICHARDS_VARIANTS))
@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_richards_variants(run, tier, variant):
    """CATCHES: Richards scheduler specialisations that still fire (or fire half-way) when one method body, prototype depth, global constant, strictness or task role differs from the canonical benchmark, producing queue/hold counts or final task graphs that differ from the tree-walking interpreter."""
    check_prog(run, tier, richards_variant(variant), "richards_" + variant)
