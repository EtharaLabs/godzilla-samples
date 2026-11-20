"""Remaining reachable gaps in the engine core (interpreter, tree-walking evaluator, builtins,
parser/lexer, ES module linker, property storage and string representation).

Each test runs one rich black-box JS program through `lumen-cli` and compares the exact output
with a golden captured from the reference binary. Programs drive rarely-taken engine paths:
proxy traps and receivers on prototype chains, legacy caller/arguments reflection, namespace
objects, TypedArray stores that shrink/detach their buffer, with/@@unscopables binding races,
iterator-close and async-iteration error ordering, class element edge cases, direct/indirect
eval declaration instantiation, promise combinators with custom capabilities, Iterator.zip /
concat, string protocol fallbacks, early errors, template re-scanning, source-phase and deferred
imports, top-level-await cycles, ShadowRealm wrapped functions, hot call/construct sites that must
fall back after shape or realm changes, $262.evalScript global declarations and compact array
element stores. Where all three execution tiers must agree the test is
parametrized over the JIT (default), the bytecode VM and the tree-walking interpreter with a
single shared golden.
"""

import pytest

from conftest import out, err

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]



# ---------------------------------------------------------------- fork A1: interpreter.rs < 4500


# covers: interpreter.rs 3335, 3399, 3409, 3738, 3749, 3796, 3807, 3811
@pytest.mark.parametrize("tier", TIERS)
def test_proxy_get_set_trap_failures_direct_and_inherited(js, golden, tier):
    """CATCHES: a [[Get]]/[[Set]] that ignores a non-callable proxy trap, swallows an exception thrown by the trap, skips the set-trap invariant check, or forgets the original receiver when the proxy sits on the prototype chain instead of being the base object."""
    code = r""""use strict";
var log = [];
function t(name, f) {
  try { log.push(name + " -> " + String(f())); }
  catch (e) { log.push(name + " !! " + e.constructor.name + ": " + e.message); }
}
var direct = new Proxy({a: 1}, {get: 42});
t("direct get, trap not callable", function () { return direct.a; });
var throwingGet = new Proxy({}, {get: function () { throw new RangeError("get-trap-boom"); }});
t("direct get, trap throws", function () { return throwingGet.zz; });
var inherit = Object.create(new Proxy({b: 2}, {get: "nope"}));
t("inherited get, trap not callable", function () { return inherit.b; });
var inheritThrow = Object.create(new Proxy({}, {get: function (tg, k) { throw new EvalError("chain-get-" + String(k)); }}));
t("inherited get, trap throws", function () { return inheritThrow.q; });
var chainOk = Object.create(new Proxy({}, {get: function (tg, k, r) { return "trap(" + String(k) + ", receiver is child: " + (r === chainOk) + ")"; }}));
t("inherited get, trap result", function () { return chainOk.hello; });
var setNC = new Proxy({}, {set: {}});
t("direct set, trap not callable", function () { setNC.x = 1; return "stored"; });
var setThrow = new Proxy({}, {set: function () { throw new URIError("set-trap-boom"); }});
t("direct set, trap throws", function () { setThrow.x = 1; return "stored"; });
var chainSetNC = Object.create(new Proxy({}, {set: 7}));
t("inherited set, trap not callable", function () { chainSetNC.x = 1; return "stored"; });
var chainSetThrow = Object.create(new Proxy({}, {set: function (tg, k) { throw new SyntaxError("chain-set-" + k); }}));
t("inherited set, trap throws", function () { chainSetThrow.y = 1; return "stored"; });
var fixedTarget = {};
Object.defineProperty(fixedTarget, "fixed", {value: 1, writable: false, configurable: false});
var chainSetLie = Object.create(new Proxy(fixedTarget, {set: function () { return true; }}));
t("inherited set, invariant violated", function () { chainSetLie.fixed = 2; return "stored"; });
var chainSetTrue = Object.create(new Proxy({}, {set: function (tg, k, v, r) { log.push("  set trap " + k + "=" + v + " receiver is child: " + (r === chainSetTrue)); return 1; }}));
t("inherited set, truthy trap result", function () { chainSetTrue.w = 9; return "own keys " + Object.keys(chainSetTrue).length; });
var chainSetFalse = Object.create(new Proxy({}, {set: function () { return 0; }}));
t("inherited set, falsy trap result in strict code", function () { chainSetFalse.w = 9; return "stored"; });
console.log(log.join("\n"));
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_proxy_trap_failures")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 629, 3441, 3454, 3476, 3485, 3584
@pytest.mark.parametrize("tier", TIERS)
def test_legacy_caller_arguments_and_mapped_arguments(js, golden, tier):
    """CATCHES: legacy fn.caller/fn.arguments reflection that does not censor strict callers, does not lazily build the arguments object, or lets the poisoned accessor leak for native/bound/arrow/strict functions; also a mapped arguments object whose delete/defineProperty does not sever the parameter alias, or a patterned parameter list that keeps arguments mapped."""
    code = r"""function describe(v) {
  if (v === null) return "null";
  if (typeof v === "function") return "fn " + v.name;
  return "args[" + Array.prototype.join.call(v, "+") + "]";
}
function inner(a, b) { return describe(inner.caller) + " / " + describe(inner.arguments); }
function sloppyOuter() { var r = inner(8, 9); return r; }
function strictOuter() { "use strict"; var r = inner(4, 5); return r; }
console.log("sloppy caller:", sloppyOuter());
console.log("strict caller censored:", strictOuter());
console.log("inactive:", describe(inner.caller), describe(inner.arguments));
function lazyArgs(x) { return lazyArgs.arguments.length + ":" + lazyArgs.arguments[0] + ":" + lazyArgs.arguments[1]; }
console.log("lazily built arguments:", lazyArgs("p", "q"));
function sameArgs() { var a = arguments; return sameArgs.arguments === a; }
console.log("same object as arguments:", sameArgs(1));
var kinds = {
  "primitive receiver": function () { return Reflect.get(new Proxy(function () {}, {}), "caller", 5); },
  "native function": function () { return Math.max.caller; },
  "bound function": function () { return (function () {}).bind(null).caller; },
  "arrow function": function () { return (() => 1).arguments; },
  "strict function": function () { return (function () { "use strict"; }).caller; },
};
Object.keys(kinds).forEach(function (k) {
  try { console.log(k + ":", describe(kinds[k]())); } catch (e) { console.log(k + ":", e.constructor.name); }
});
function mapped(a, b) {
  var r = [];
  r.push(delete arguments.callee, delete arguments.length, delete arguments[7]);
  arguments[0] = "A";
  r.push(a);
  r.push(delete arguments[0]);
  arguments[0] = "Z";
  r.push(a);
  Object.defineProperty(arguments, "1", {value: "B2"});
  r.push(b);
  Object.defineProperty(arguments, "1", {value: "B3", writable: false});
  r.push(b);
  b = "local";
  r.push(arguments[1], "callee" in arguments, arguments.length);
  return r.join(",");
}
console.log("mapped arguments:", mapped(1, 2));
function patterned([a, ...rest], {b} = {b: "dflt"}) {
  arguments[0] = "changed";
  return a + "|" + rest.join("+") + "|" + b + "|" + typeof arguments[0];
}
console.log("destructured params:", patterned([1, 2, 3]), patterned(["x"], {b: "given"}));
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_legacy_caller_arguments")
    assert (r.returncode, r.stderr) == (0, b"")


A1_NS_DEP = """export let live = 1;
export const k = "kv";
export * as sub from "./nssub.mjs";
export function bump() { live++; }
"""


# covers: interpreter.rs 2417, 2461, 3492, 3597, 3726-3727, 3898-3907
@pytest.mark.parametrize("tier", TIERS)
def test_module_namespace_index_and_receiver_writes(js, workdir, golden, tier):
    """CATCHES: module namespace objects that let numeric-index fast paths read or write them like plain objects, accept writes through Reflect.set/super with the namespace as receiver, throw instead of silently ignoring writes from sloppy code, or report a caller for a sloppy function invoked from module top level."""
    (workdir / "nsdep.mjs").write_text(A1_NS_DEP, encoding="utf-8")
    (workdir / "nssub.mjs").write_text("export const deep = 42;\n", encoding="utf-8")
    code = r"""import * as ns from "./nsdep.mjs";
var log = [];
function t(name, f) {
  try { log.push(name + " -> " + String(f())); }
  catch (e) { log.push(name + " !! " + e.constructor.name + ": " + e.message); }
}
t("ns[0]", () => ns[0]);
t("ns['0']", () => ns["0"]);
for (var i = 0; i < 2; i++) t("ns[i] in loop", () => ns[i]);
t("ns[0] = 1", () => { ns[0] = 1; return "stored"; });
t("ns.sub = 1 (star-as export)", () => { ns.sub = 1; return "stored"; });
t("ns.live = 5", () => { ns.live = 5; return "stored"; });
t("Reflect.set(ns)", () => Reflect.set(ns, "live", 9));
t("forwarded Reflect.set, ns receiver", () => Reflect.set(new Proxy({}, {}), "live", 9, ns));
t("forwarded Reflect.set, ns receiver, star-as key", () => Reflect.set(new Proxy({}, {}), "sub", 9, ns));
var home = { m(v) { super.live = v; } };
t("super.live = v with ns as this", () => { home.m.call(ns, 3); return "stored"; });
t("ns.sub.deep", () => ns.sub.deep);
ns.bump();
t("live after bump", () => ns.live);
globalThis.peek = new Function("return peek.caller === null ? 'null' : peek.caller === viaSloppy ? 'viaSloppy' : 'other';");
globalThis.viaSloppy = new Function("var r = peek(); return r;");
var topCaller = peek();
t("sloppy fn caller from module top level", () => topCaller);
t("sloppy fn caller from sloppy fn", () => viaSloppy());
console.log(log.join("\n"));
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("a1_namespace_strict")
    assert (r.returncode, r.stderr) == (0, b"")
    sloppy = r"""import("./nsdep.mjs").then(function (ns) {
  ns.live = 100;
  ns[0] = 1;
  ns.sub = 2;
  var home = { m(v) { super.live = v; } };
  home.m.call(ns, 3);
  console.log("sloppy namespace writes are ignored:", ns.live, ns[0], typeof ns.sub, Reflect.set(new Proxy({}, {}), "k", 1, ns));
});
"""
    r = js(sloppy, *tier, name="sloppy.js")
    assert out(r) == golden("a1_namespace_sloppy")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 3825-3839, 3881-3882, 3898-3920, 3942-3948, 3995-4000
@pytest.mark.parametrize("tier", TIERS)
def test_set_with_foreign_receiver_typed_array_chain_and_super(js, golden, tier):
    """CATCHES: an OrdinarySet that writes to the base instead of the receiver, ignores a read-only/accessor/non-extensible receiver, lets a fixed-length array receiver grow, consults the TypedArray prototype instead of stopping at a TypedArray on the chain, or applies strict-mode throwing to Reflect.set and sloppy super assignments."""
    code = r"""var log = [];
var fwd = new Proxy({}, {});
var recv = {};
Object.defineProperty(recv, "ro", {value: 1, writable: false, configurable: true});
Object.defineProperty(recv, "acc", {get: function () { return 1; }, configurable: true});
log.push("forwarded, read-only receiver prop: " + Reflect.set(fwd, "ro", 2, recv) + " ro=" + recv.ro);
log.push("forwarded, accessor receiver prop: " + Reflect.set(fwd, "acc", 2, recv));
log.push("forwarded, non-extensible receiver: " + Reflect.set(fwd, "n", 2, Object.preventExtensions({})));
var lenFrozen = [1, 2, 3];
Object.defineProperty(lenFrozen, "length", {writable: false});
log.push("forwarded, array receiver with fixed length: " + Reflect.set(fwd, "length", 1, lenFrozen) + " len=" + lenFrozen.length);
log.push("forwarded, index past fixed length: " + Reflect.set(fwd, "5", "x", lenFrozen) + " len=" + lenFrozen.length);
var plainArr = [1, 2, 3];
log.push("forwarded, array length truncation: " + Reflect.set(fwd, "length", 1, plainArr) + " -> " + JSON.stringify(plainArr));
var pr = new Proxy({}, {defineProperty: function (t, k, d) { log.push("  defineProperty trap " + k + " " + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); }});
log.push("forwarded, proxy receiver: " + Reflect.set(fwd, "k", 5, pr));
var ta = new Int8Array(4);
var child = Object.create(ta);
var fwdChild = new Proxy(child, {});
log.push("TA in chain, receiver is the TA: " + Reflect.set(fwdChild, "1", 300, ta) + " ta=" + Array.from(ta));
log.push("TA in chain, foreign receiver: " + Reflect.set(fwdChild, "2", 7, child) + " own=" + JSON.stringify(Object.getOwnPropertyDescriptor(child, "2")) + " ta=" + Array.from(ta));
log.push("TA in chain, non-integer key: " + Reflect.set(fwdChild, "1.5", 7, child) + " own=" + child.hasOwnProperty("1.5"));
log.push("TA in chain, -0 key on TA receiver: " + Reflect.set(fwdChild, "-0", {valueOf: function () { log.push("  coerced"); return 1; }}, ta));
log.push("TA in chain, out-of-range index: " + Reflect.set(fwdChild, "9", 1, ta));
log.push("TA in chain, named key: " + Reflect.set(fwdChild, "label", "L", ta) + " " + ta.label);
var bta = new BigInt64Array(2);
log.push("BigInt TA in chain: " + Reflect.set(new Proxy(Object.create(bta), {}), "1", {valueOf: function () { return 77n; }}, bta) + " " + bta[1]);
child[3] = 11;
log.push("plain write through TA chain: " + JSON.stringify(Object.getOwnPropertyDescriptor(child, "3")) + " ta=" + Array.from(ta));
var home = {
  setRo() { super.ro = 5; },
  setLen(n) { super.length = n; },
  setK(v) { super.k = v; },
};
var t = {};
Object.defineProperty(t, "ro", {value: 0, writable: false});
home.setRo.call(t);
log.push("sloppy super.ro on read-only this: " + t.ro);
home.setLen.call(lenFrozen, 0);
log.push("sloppy super.length on fixed-length array: " + lenFrozen.length);
var b = [1, 2, 3, 4];
home.setLen.call(b, 1);
log.push("super.length truncation: " + JSON.stringify(b));
var refuse = new Proxy({}, {defineProperty: function (tt, k, d) { log.push("  refusing defineProperty " + k + "=" + d.value); return false; }});
home.setK.call(refuse, 3);
log.push("sloppy super.k on refusing proxy: ok");
var thrower = new Proxy({}, {defineProperty: function () { throw new RangeError("define-trap"); }});
try { home.setK.call(thrower, 1); } catch (e) { log.push("receiver trap throws: " + e.constructor.name + " " + e.message); }
(function () {
  "use strict";
  var shome = {
    setK(v) { super.k = v; },
    setLen(n) { super.length = n; },
    setRo() { super.ro = 1; },
  };
  try { shome.setK.call(refuse, 4); } catch (e) { log.push("strict super.k on refusing proxy: " + e.constructor.name + ": " + e.message); }
  try { shome.setLen.call(lenFrozen, 0); } catch (e) { log.push("strict super.length: " + e.constructor.name + ": " + e.message); }
  try { shome.setRo.call(t); } catch (e) { log.push("strict super.ro: " + e.constructor.name + ": " + e.message); }
  try { Object.freeze([1]).length = 0; } catch (e) { log.push("strict frozen length: " + e.constructor.name + ": " + e.message); }
  var kid = Object.create(Object.freeze({x: 1}));
  try { kid.x = 2; } catch (e) { log.push("strict inherited read-only: " + e.constructor.name + ": " + e.message); }
  log.push("strict Reflect.set still returns: " + Reflect.set(fwd, "ro", 1, recv));
})();
var kid2 = Object.create(Object.freeze({x: 1}));
kid2.x = 2;
log.push("sloppy inherited read-only: " + kid2.x + " own=" + kid2.hasOwnProperty("x"));
console.log(log.join("\n"));
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_receiver_set_paths")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 2076, 3515-3521
@pytest.mark.parametrize("tier", TIERS)
def test_cross_realm_derived_constructor_errors_and_generator_proto_fallback(js, golden, tier):
    """CATCHES: derived-constructor return/super errors created with the callee realm's error constructors instead of the caller's, or generator objects whose [[Prototype]] is not the function realm's %GeneratorPrototype% when the generator function's prototype property is not an object."""
    code = r"""var other = $262.createRealm().global;
var ReturnsOne = other.eval("(class extends Object { constructor() { super(); return 1; } })");
var NoSuper = other.eval("(class extends Object { constructor() { } })");
var ReturnsUndef = other.eval("(class extends Object { constructor() { super(); return undefined; } })");
try { new ReturnsOne(); } catch (e) { console.log("foreign derived returns 1:", e.constructor === TypeError, e.constructor === other.TypeError, e.message); }
try { new NoSuper(); } catch (e) { console.log("foreign derived skips super:", e.constructor === ReferenceError, e.constructor === other.ReferenceError, e.message); }
var ok = new ReturnsUndef();
console.log("foreign derived returns undefined:", ok instanceof other.Object, ok instanceof ReturnsUndef);
var LocalRet = class extends Object { constructor() { super(); return "s"; } };
try { new LocalRet(); } catch (e) { console.log("local derived returns string:", e.constructor === TypeError, e.message); }
function* g() { yield 1; yield 2; }
g.prototype = null;
var GP = Object.getPrototypeOf(function* () {}).prototype;
var it = g();
console.log("generator with null prototype:", Object.getPrototypeOf(it) === GP, [...it].join(","));
var og = other.eval("(function* () { yield 'o'; })");
og.prototype = 3;
var oit = og();
console.log("foreign generator with primitive prototype:", Object.getPrototypeOf(oit) === Object.getPrototypeOf(other.eval("(function* () {})")).prototype, Object.getPrototypeOf(oit) === GP, oit.next().value);
async function* ag() { yield "a"; }
ag.prototype = 5;
var ait = ag();
console.log("async generator with primitive prototype:", Object.getPrototypeOf(ait) === Object.getPrototypeOf(async function* () {}).prototype);
ait.next().then(function (r) { console.log("async generator result:", r.value, r.done); });
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_realm_ctor_errors")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 3673, 3694-3695
@pytest.mark.parametrize("tier", TIERS)
def test_property_writes_on_primitive_bases(js, golden, tier):
    """CATCHES: assignments to properties of primitives that create wrapper properties, skip an inherited setter or a proxy set trap on the primitive's prototype chain, pass a boxed receiver to the proxy trap, or fail to throw TypeError in strict mode."""
    code = r"""var log = [];
Object.defineProperty(Number.prototype, "acc", {set: function (v) { log.push("Number.prototype setter: this is " + typeof this + ", v=" + v); }, configurable: true});
(5).acc = 3;
(5).toFixed = 1;
log.push("data property on proto is not shadowed: " + typeof (5).toFixed);
var saved = Object.getPrototypeOf(String.prototype);
Object.setPrototypeOf(String.prototype, new Proxy({}, {set: function (t, k, v, r) { log.push("proxy set trap " + k + "=" + v + " receiver " + typeof r + " " + r); return true; }}));
"abc".foo = 1;
Object.setPrototypeOf(String.prototype, saved);
(10n).bar = 2;
true.baz = 3;
Symbol.iterator.qux = 4;
log.push("sloppy primitive writes are dropped: " + [(10n).bar, true.baz, Symbol.iterator.qux, "abc".foo].join(","));
(function () {
  "use strict";
  try { (5).toFixed = 1; } catch (e) { log.push("strict proto data prop: " + e.constructor.name + ": " + e.message); }
  try { "s".newprop = 1; } catch (e) { log.push("strict new prop on string: " + e.constructor.name + ": " + e.message); }
  try { (1n).p = 1; } catch (e) { log.push("strict new prop on bigint: " + e.constructor.name + ": " + e.message); }
  (5).acc = 8;
})();
console.log(log.join("\n"));
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_primitive_base_writes")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 1496, 2704, 2710, 2761, 2951, 2954, 2957, 2961, 3105, 3131, 3135
@pytest.mark.parametrize("tier", TIERS + [pytest.param("env", id="lumen_tier_env")])
def test_property_fast_paths_fall_back_after_shape_changes(js, golden, tier):
    """CATCHES: an obj.k += str in-place append that fires on arrays, functions, inherited/accessor/read-only slots or a slot replaced by the RHS, or inline caches that return stale results after a prototype is attached/cut or a slot flips to accessor/read-only, or create properties on non-extensible objects (also checks LUMEN_TIER=bytecode selects the same results)."""
    code = r"""var out = [];
function onArray() { var arr = [1]; arr.s = "a"; for (var i = 0; i < 5; i++) arr.s += "" + i; return "append on array: " + arr.s; }
function onFunction() { var F = function () {}; F.s = "f"; for (var i = 0; i < 5; i++) F.s += "<" + i; return "append on function: " + F.s; }
function inherited() { var proto = {s: "p"}; var child = Object.create(proto); for (var i = 0; i < 3; i++) child.s += "c" + i; return "append to inherited: " + child.s + " proto=" + proto.s + " own=" + child.hasOwnProperty("s"); }
function accessor(acc) { for (var i = 0; i < 3; i++) acc.s += "" + i; return "append via accessor: " + acc.s; }
function readonly(ro) { for (var i = 0; i < 3; i++) ro.s += "z"; return "append to read-only: " + ro.s; }
function replaced() { var swap = {s: "x"}; for (var i = 0; i < 3; i++) swap.s += (swap.s = "R" + i, "+"); return "rhs replaces target: " + swap.s; }
function shared() { var o = {s: "base"}; var keep = []; for (var i = 0; i < 4; i++) { keep.push(o.s); o.s += "-" + i; } return "shared accumulator: " + o.s + " kept=" + keep.join("|"); }
function grown() { var big = {s: "y"}; for (var i = 0; i < 40; i++) big.s += "abcdefghij"; return "grown: " + big.s.length + " " + big.s.slice(-12); }
function numeric() { var num = {s: 1}; for (var i = 0; i < 3; i++) num.s += "n"; return "number + string: " + num.s; }
function frozen(o) { for (var i = 0; i < 2; i++) o.s += "!"; return "append to frozen: " + o.s; }
out.push(onArray(), onFunction(), inherited());
out.push(accessor({_v: "g", get s() { return this._v; }, set s(v) { this._v = v + "!"; }}));
var ro = {};
Object.defineProperty(ro, "s", {value: "r", writable: false});
out.push(readonly(ro), replaced(), shared(), grown(), numeric(), frozen(Object.freeze({s: "fz"})));
function readZ(o) { return o.zz; }
function readX(o) { return o.x; }
function writeX(o, v) { o.x = v; return o.x; }
function create(o, v) { o.fresh = v; return o.fresh; }
var bare = Object.create(null);
for (var i = 0; i < 20; i++) readZ(bare);
Object.setPrototypeOf(bare, {zz: "found-after-grow"});
out.push("absent, then chain grows: " + readZ(bare));
var P = {pp: 1};
var o3 = Object.create(P);
for (var i = 0; i < 20; i++) readZ(o3);
Object.setPrototypeOf(P, null);
out.push("absent, then chain cut: " + readZ(o3) + " " + readZ(o3));
var od = {x: 1};
for (var i = 0; i < 20; i++) readX(od);
Object.defineProperty(od, "x", {get: function () { return "getter-own"; }, configurable: true});
out.push("own data becomes accessor: " + readX(od));
var H = {x: "h"};
var kid = Object.create(H);
for (var i = 0; i < 20; i++) readX(kid);
Object.defineProperty(H, "x", {get: function () { return "getter-holder"; }, configurable: true});
out.push("holder data becomes accessor: " + readX(kid));
var H2 = {x: "deep"};
var M = Object.create(H2);
var leaf = Object.create(M);
for (var i = 0; i < 20; i++) readX(leaf);
Object.setPrototypeOf(M, null);
out.push("two-hop holder, middle cut: " + readX(leaf));
var w = {x: 0};
for (var i = 0; i < 20; i++) writeX(w, i);
Object.defineProperty(w, "x", {writable: false});
out.push("write after non-writable flip: " + writeX(w, 99));
var ne = Object.preventExtensions({a: 1});
for (var i = 0; i < 20; i++) create(ne, i);
out.push("create on non-extensible: " + create(ne, 1) + " keys=" + Object.keys(ne));
var deep = {};
for (var d = 0; d < 10; d++) deep = Object.create(deep);
for (var i = 0; i < 20; i++) create(Object.create(deep), i);
out.push("create through a deep prototype chain: " + create(Object.create(deep), "ok"));
for (var i = 0; i < 20; i++) create(Object.create([1, 2]), i);
out.push("create with array in chain: " + create(Object.create([1, 2]), "arr"));
console.log(out.join("\n"));
"""
    if tier == "env":
        r = js(code, env_overrides={"LUMEN_TIER": "bytecode"})
    else:
        r = js(code, *tier)
    assert out(r) == golden("a1_property_fast_paths")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 1699, 1713-1716, 1805, 1830
@pytest.mark.parametrize("tier", TIERS)
def test_typed_array_stores_after_shrink_detach_and_shared_copies(js, golden, tier):
    """CATCHES: TypedArray stores that write past a buffer shrunk or detached by the value's own coercion, or same-type slice copies that fail to read from or write into SharedArrayBuffer-backed views."""
    code = r"""var log = [];
var rab = new ArrayBuffer(8, {maxByteLength: 16});
var ta = new Uint8Array(rab);
ta[6] = {valueOf: function () { rab.resize(2); return 9; }};
log.push("index store, value shrinks buffer: len=" + ta.length + " [6]=" + ta[6]);
var rab2 = new ArrayBuffer(16, {maxByteLength: 32});
var bta = new BigInt64Array(rab2);
bta[1] = {valueOf: function () { rab2.resize(8); return 5n; }};
log.push("bigint store, value shrinks buffer: len=" + bta.length + " [1]=" + bta[1]);
var ab3 = new ArrayBuffer(8);
var ta3 = new Int16Array(ab3);
ta3[2] = {valueOf: function () { $262.detachArrayBuffer(ab3); return 1; }};
log.push("store, value detaches buffer: len=" + ta3.length + " [2]=" + ta3[2] + " byteLength=" + ab3.byteLength);
var rab4 = new ArrayBuffer(4, {maxByteLength: 8});
var ta4 = new Uint8Array(rab4);
ta4.set([1, {valueOf: function () { rab4.resize(1); return 2; }}, 3, 4]);
log.push("set(), element shrinks buffer: len=" + ta4.length + " " + Array.from(ta4));
var rab5 = new ArrayBuffer(32, {maxByteLength: 32});
var bta5 = new BigInt64Array(rab5);
bta5.set([1n, {valueOf: function () { rab5.resize(8); return 2n; }}, 3n]);
log.push("bigint set(), element shrinks buffer: len=" + bta5.length + " " + Array.from(bta5));
var rab6 = new ArrayBuffer(4, {maxByteLength: 8});
var ta6 = new Int8Array(rab6);
ta6.fill({valueOf: function () { rab6.resize(2); return 7; }});
log.push("fill(), value shrinks buffer: " + Array.from(ta6));
var sab = new SharedArrayBuffer(8);
var sta = new Int16Array(sab);
sta.set([1, -2, 3, -4]);
var sl = sta.slice(1, 3);
log.push("slice of shared view: " + Array.from(sl) + " shared=" + (sl.buffer instanceof SharedArrayBuffer));
var src = new Float32Array([1.5, NaN, -0, 2.25]);
src.constructor = {};
src.constructor[Symbol.species] = function (n) { return new Float32Array(new SharedArrayBuffer(n * 4)); };
var dst = src.slice(0, 4);
log.push("slice into shared species target: " + Array.from(dst).map(function (x) { return Object.is(x, -0) ? "-0" : String(x); }) + " shared=" + (dst.buffer instanceof SharedArrayBuffer));
var bsab = new BigUint64Array(new SharedArrayBuffer(16));
bsab[0] = 7n;
bsab[1] = 2n ** 64n - 1n;
log.push("bigint shared: " + bsab[0] + "," + bsab[1] + " slice=" + bsab.slice(1));
log.push("atomics on shared: " + Atomics.add(sta, 0, 10) + " -> " + sta[0] + " cmpxchg=" + Atomics.compareExchange(sta, 1, -2, 50) + " -> " + sta[1]);
console.log(log.join("\n"));
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_typed_array_shrink_shared")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter/call_entry.rs 41-43, 46-49
@pytest.mark.parametrize("tier", TIERS)
def test_iterator_entry_next_with_proper_tail_call(js, golden, tier):
    """CATCHES: the native iterator entry dropping a pending proper tail call made by a strict next() method (so the step result is lost or undefined) when LUMEN_ITERATOR_ENTRY_NATIVE is enabled."""
    code = r""""use strict";
var calls = 0;
function finish(state) {
  calls++;
  state.i++;
  return state.i <= 3 ? {value: state.i * 10, done: false} : {value: undefined, done: true};
}
function make(tag) {
  var state = {i: 0};
  return {
    [Symbol.iterator]() { return this; },
    next() { eval(""); return finish(state); },
    tag: tag,
  };
}
function drain(tag) { var got = []; for (var v of make(tag)) got.push(v); return tag + "=" + got.join(","); }
var lines = [];
for (var n = 0; n < 4; n++) lines.push(drain("run" + n));
var spread = [...make("spread")];
var [first, , third] = make("destructure");
console.log(lines.join(" | "));
console.log("spread", spread.join(","), "destructure", first, third, "finish calls", calls);
"""
    r = js(code, *tier, env_overrides={"LUMEN_ITERATOR_ENTRY_NATIVE": "1"})
    assert out(r) == golden("a1_iterator_entry_tail_call")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 4315-4317
@pytest.mark.parametrize("tier", TIERS)
def test_regexp_subject_cache_overflow_keeps_results(js, golden, tier):
    """CATCHES: a regexp subject-text cache that returns stale or wrong match data after more than 32768 distinct subject strings force it to reset, or loses a global regexp's progress over an earlier subject."""
    code = r"""var re = /(\d+)-(\w)/;
var early = "id-0042-x";
var g = /\d/g;
var firstHit = g.exec(early);
var hits = 0, sum = 0, last = "";
for (var i = 0; i < 33000; i++) {
  var s = "k" + i + "-" + String.fromCharCode(97 + (i % 26));
  var m = re.exec(s);
  if (m) { hits++; sum += Number(m[1]) % 7; last = m[1] + m[2]; }
}
var rest = [];
var m2;
while ((m2 = g.exec(early)) !== null) rest.push(m2[0] + "@" + m2.index);
console.log("distinct subjects:", hits, sum, last);
console.log("global regexp resumed on an early subject:", firstHit[0] + "@" + firstHit.index, rest.join(" "));
console.log("replace/split after churn:", "x9-y".replace(re, "$2$1"), "a1-b|c22-d".split(/\|/).join("/"), re.exec(early)[1]);
"""
    r = js(code, *tier)
    assert out(r) == golden("a1_regexp_subject_cache")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 3408-3443 (run_agent_event_loop waits + host timers)
@pytest.mark.parametrize("tier", TIERS)
def test_ev_atomics_wait_async_resolves_through_module_event_loop(js, golden, tier):
    """CATCHES: an ESM event loop that returns as soon as the microtask queue is empty (never polling pending Atomics.waitAsync waiter threads or $262.agent.setTimeout timers), or that resolves a timed-out wait as 'ok' / a notified wait as 'timed-out', fails this."""
    code = r"""const order = [];
$262.agent.setTimeout(() => { order.push('agent timer'); }, 1);
const a = new Int32Array(new SharedArrayBuffer(16));
const timedOut = Atomics.waitAsync(a, 0, 0, 40);
const woken = Atomics.waitAsync(a, 1, 0);
const notEqual = Atomics.waitAsync(a, 2, 5);
const zero = Atomics.waitAsync(a, 3, 0, 0);
console.log('async flags', timedOut.async, woken.async, notEqual.async, zero.async);
console.log('sync values', notEqual.value, zero.value, Object.prototype.toString.call(timedOut.value));
console.log('notified', Atomics.notify(a, 1, 1), Atomics.notify(a, 2));
Promise.all([timedOut.value, woken.value]).then((v) => {
  console.log('settled', v.join(','), 'after', order.join(','));
});
console.log('module body done');
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("ev_atomics_wait_async")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 2506, 2821, 2884, 2926-2946, 2968, 3155, 5201, 5216, 5235, 5256
@pytest.mark.parametrize("tier", TIERS)
def test_ev_tail_position_tagged_templates_and_optional_chain_continuations(js, golden, tier):
    """CATCHES: a strict-mode proper-tail-call path that mis-binds `this` for tagged templates (ident/member/call/computed tags), loses the cached template object, or that keeps evaluating the rest of an optional chain (index keys, calls, delete operands) after a nullish base short-circuits, fails this; so does treating a replaced global `eval` as a direct eval."""
    code = r""""use strict";
const log = [];
function show(label, f) { try { log.push(label + ' => ' + String(f())); } catch (e) { log.push(label + ' => ' + e.name); } }
function tag(strings, ...subs) {
  return strings.raw.join('|') + '#' + subs.join(',') + '#' + (this === undefined ? 'undef' : typeof this);
}
const obj = { name: 'obj', tag(strings, ...subs) { return this.name + ':' + strings.join('_') + ':' + subs.length; } };
function mk() { return tag; }
function viaIdent(x) { return tag`a${x}b${x + 1}c`; }
function viaMember(x) { return obj.tag`m${x}n`; }
function viaCall(x) { return mk()`q${x}`; }
function viaComputed(x) { return obj['tag']`k${x}`; }
function viaNullBase() { const o = null; return o.tag`z`; }
function notCallable() { const o = { tag: 5 }; return o.tag`z`; }
function deep(n) { if (n === 0) return tag`done${n}`; return deep(n - 1); }
const same = (s) => s;
function ident() { return same`x`; }
function optTail(f) { return f?.(); }
show('ident tag', () => viaIdent(1));
show('member tag', () => viaMember(2));
show('call tag', () => viaCall(3));
show('computed tag', () => viaComputed(4));
show('null base tag', viaNullBase);
show('non-callable tag', notCallable);
show('deep tail tag', () => deep(50));
show('template identity', () => ident() === ident() && Object.isFrozen(ident()));
show('optional tail undefined', () => optTail(undefined));
show('optional tail call', () => optTail(() => 'called'));
function get(v, tag) { log.push('get ' + tag); return v; }
function side(tag) { log.push('side ' + tag); return 'k'; }
const real = { k: { m() { return 'm on ' + typeof this; } }, f() { return (x) => 'inner ' + x; } };
show('index after short', () => get(null, 1)?.a[side(1)]);
show('call member after short', () => get(null, 2)?.a.b());
show('call of short call', () => get(null, 3)?.()());
show('delete member after short', () => delete get(null, 4)?.a.b);
show('delete index after short', () => delete get(null, 5)?.a[side(5)]);
show('delete optional member after short', () => delete get(null, 6)?.a?.b);
show('delete optional index after short', () => delete get(null, 7)?.a?.[side(7)]);
show('delete optional index live', () => { const o = { a: { k: 1 } }; const r = delete o?.a?.[side(8)]; return r + ' ' + JSON.stringify(o); });
show('live chain', () => get(real, 9)?.['k'].m?.());
show('tail short chain', () => get(null, 10)?.f()(1));
show('tail live chain', () => get(real, 11)?.f()(2));
const savedEval = globalThis.eval;
globalThis.eval = function (s) { return 'fake eval ' + s; };
show('strict tail fake eval', () => (function () { return eval('1+1'); })());
show('sloppy fake eval', () => Function("return eval('2+2')")());
globalThis.eval = savedEval;
show('restored eval', () => (function () { return eval('3+3'); })());
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_tail_calls_optional")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 54, 1797-1802, 2128-2133, 2145-2148, 7486-7491, 7566-7567, 7596 (7487-7489: strict compound in with)
@pytest.mark.parametrize("tier", TIERS)
def test_ev_with_unscopables_vanishing_bindings_and_immutable_writes(js, golden, tier):
    """CATCHES: a with-statement binding lookup that does not re-check HasProperty after @@unscopables deleted the property (strict code must throw ReferenceError, sloppy reads undefined / writes recreate it), or that throws for a sloppy write to a named function expression's own name while missing the strict TypeError, fails this."""
    code = r"""var log = [];
function t(label, f) { try { log.push(label + ': ' + f()); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); } }
function mk(name) {
  var env = { x: 1, y: 2 };
  env[Symbol.unscopables] = {
    get x() { log.push(name + ' unscopables x'); delete env.x; return false; },
    get y() { log.push(name + ' unscopables y'); delete env.y; return false; },
  };
  return env;
}
var x = 'outer-x', y = 'outer-y';
var e1 = mk('read');
with (e1) { log.push('read=' + String(x)); }
var e2 = mk('write');
with (e2) { y = 42; }
log.push('e2.y=' + e2.y + ' outer y=' + y);
var e3 = mk('strict-read');
with (e3) { t('strict read', function () { 'use strict'; return x; }); }
var e4 = mk('strict-write');
with (e4) { t('strict write', function () { 'use strict'; y = 7; }); }
log.push('e4 keys=' + Object.keys(e4).join(',') + ' outer y=' + y);
var e5 = mk('compound');
with (e5) { x += 5; }
log.push('e5.x=' + e5.x);
var e5s = mk('strict-compound');
with (e5s) { t('strict compound', function () { 'use strict'; x += 1; }); }
log.push('e5s keys=' + Object.keys(e5s).join(','));
var e6 = mk('typeof');
with (e6) { log.push('typeof=' + typeof x); }
var e7 = mk('var-pattern');
with (e7) { var [y] = [43]; }
log.push('e7.y=' + e7.y + ' outer y=' + y);
var e8 = mk('rest');
with (e8) { ({ ...x } = { p: 1, q: 2 }); }
log.push('e8.x=' + JSON.stringify(e8.x) + ' outer x=' + x);
var e9 = mk('strict-rest');
with (e9) { t('strict rest', function () { 'use strict'; ({ ...y } = { r: 3 }); }); }
log.push('e9 keys=' + Object.keys(e9).join(',') + ' outer y=' + y);
t('sloppy fn-name rest', function () { return (function f() { ({ ...f } = { a: 2 }); return typeof f; })(); });
t('sloppy fn-name compound', function () { return (function nm() { nm += 1; return typeof nm; })(); });
t('strict fn-name rest', function () { return (function g() { 'use strict'; ({ ...g } = {}); })(); });
t('strict fn-name compound', function () { return (function nm() { 'use strict'; nm += 1; })(); });
const k = 1;
t('const rest', function () { ({ ...k } = {}); });
t('const compound', function () { k *= 2; });
globalThis.gz = 1;
t('strict global vanish', function () { 'use strict'; gz = (delete globalThis.gz, 2); return gz; });
log.push('gz after: ' + typeof globalThis.gz);
globalThis.gy = 1;
t('sloppy global vanish', function () { gy = (delete globalThis.gy, 3); return globalThis.gy; });
t('tdz assign', function () { x1 = 5; let x1; return x1; });
var [h1, , ] = [1];
var [h2, , , ] = [];
log.push('holes ' + h1 + ' ' + h2);
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_with_unscopables")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 54, 111, 1239, 1246, 1249, 1255, 1449, 1479, 1488, 1492, 1535, 5779, 5804, 6925
@pytest.mark.parametrize("tier", TIERS)
def test_ev_iterator_close_errors_and_sync_yield_star_delegation(js, golden, tier):
    """CATCHES: an IteratorClose that swallows a non-callable or non-object `return` on normal completion, replaces a throw completion with the `return` getter's error, skips closing when a generator is returned out of a destructuring default, or a yield* that ignores missing/non-callable inner throw/return methods, fails this."""
    code = r"""const log = [];
function t(label, f) { try { log.push(label + ': ' + f()); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); } }
function endless(extra) {
  return { [Symbol.iterator]() { return Object.assign({ n: 0, next() { return { value: this.n++, done: false }; } }, extra); } };
}
t('close: return not callable', () => { var [a] = endless({ return: 7 }); return a; });
t('close: return non-object', () => { var [a] = endless({ return() { return 1; } }); return a; });
t('assign close: return not callable', () => { let a; [a] = endless({ return: 'x' }); return a; });
t('close: return getter throws during throw', () => {
  const iter = { next() { return { value: undefined, done: false }; } };
  Object.defineProperty(iter, 'return', { get() { log.push('return getter'); throw new Error('getter'); } });
  var [a = (() => { throw new RangeError('default threw'); })()] = { [Symbol.iterator]() { return iter; } };
});
t('iterator not object', () => { var [a] = { [Symbol.iterator]() { return 1; } }; return a; });
t('spread non-callable iterator', () => Math.max(...{ [Symbol.iterator]: 5 }));
t('spread next not callable', () => Math.max(...{ [Symbol.iterator]() { return { next: 5 }; } }));
t('spread result not object', () => Math.max(...{ [Symbol.iterator]() { return { next() { return 0; } }; } }));
t('holes exhaust', () => { var [, , x] = [1]; let y; [, , y] = 'ab'; return x + ',' + y; });
function* binder(src) { var [a = yield 'paused-var'] = src; return a; }
function* assigner(src) { let a; [a = yield 'paused-assign'] = src; return a; }
const closer = (tag) => ({ [Symbol.iterator]() { return { next() { return { value: undefined, done: false }; }, return() { log.push(tag + ' closed'); return {}; } }; } });
t('generator return inside var pattern', () => { const g = binder(closer('var')); g.next(); return JSON.stringify(g.return('early')); });
t('generator return inside assignment pattern', () => { const g = assigner(closer('assign')); g.next(); return JSON.stringify(g.return('early2')); });
t('generator return with bad close', () => { const g = binder({ [Symbol.iterator]() { return { next() { return { done: false }; }, return: 3 }; } }); g.next(); return JSON.stringify(g.return('x')); });
function show(label, f) {
  try { log.push(label + ': ' + JSON.stringify(f())); }
  catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); }
}
function inner(extra) {
  return Object.assign({ [Symbol.iterator]() { return this; }, n: 0, next(v) { this.n++; return { value: 'n' + this.n + ':' + v, done: this.n > 3 }; } }, extra);
}
function* outer(it) { const r = yield* it; log.push('outer got ' + r); return 'end'; }
let g = outer(inner({ throw: 5 }));
show('first', () => g.next('a'));
show('throw non-callable', () => g.throw(new Error('t')));
g = outer(inner({}));
g.next();
show('return without inner return', () => g.return('R'));
show('after return', () => g.next());
g = outer(inner({ return: 'nope' }));
g.next();
show('return non-callable', () => g.return('R2'));
g = outer(inner({ next() { return 17; } }));
show('next non-object', () => g.next());
g = outer(inner({ return(v) { return { value: 'closed ' + v, done: true }; } }));
g.next();
show('return delegated', () => g.return('R3'));
g = outer(inner({ throw(e) { return { value: 'caught ' + e, done: false }; } }));
g.next();
show('throw delegated', () => g.throw('E1'));
show('continue', () => g.next('c'));

console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_iterator_protocol")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 579, 864, 1038, 1057, 1074, 1090-1093, 1125, 1209, 1278-1290, 1319, 1399, 1408-1409, 3184-3193, 3315
@pytest.mark.parametrize("tier", TIERS)
def test_ev_for_await_close_async_yield_star_and_await_using(js, golden, tier):
    """CATCHES: a for-await loop that does not adopt a thenable from return(), surfaces close errors over a body throw, skips the async-from-sync close on a rejected value, or an async-generator yield* / return(rejectedPromise) that does not await and rethrow at the yield, or await-using loops that dispose in the wrong order, fails this."""
    code = r"""const log = [];
function counter(ret) {
  return { [Symbol.asyncIterator]() {
    return { i: 0, next() { return Promise.resolve({ value: this.i++, done: false }); }, return: ret };
  } };
}
async function attempt(label, f) {
  try { log.push(label + ': ok ' + JSON.stringify(await f())); }
  catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); }
}
function asyncInner(extra) {
  return Object.assign({ [Symbol.asyncIterator]() { return this; }, n: 0,
    next(v) { this.n++; return Promise.resolve({ value: 'n' + this.n + ':' + v, done: this.n > 3 }); } }, extra);
}
async function* outer(it) { try { const r = yield* it; log.push('outer got ' + r); } catch (e) { log.push('outer caught ' + e.name); throw e; } }
async function* plain() {
  try { yield 1; log.push('not reached'); }
  catch (e) { log.push('plain caught ' + e.message); yield 'recovered'; }
}
function res(name) { return { name, [Symbol.dispose]() { log.push('dispose ' + name); } }; }
function ares(name) { return { name, async [Symbol.asyncDispose]() { log.push('adispose ' + name); } }; }
async function main() {
  await attempt('thenable return', async () => {
    for await (const v of counter(function () { log.push('return called'); return { then(r) { log.push('then called'); r({ done: true }); } }; })) { if (v === 2) break; }
    return 'after';
  });
  await attempt('plain object return', async () => { for await (const v of counter(function () { log.push('plain return'); return { done: true }; })) { break; } return 'plain'; });
  await attempt('null return', async () => { let s = 0; for await (const v of counter(null)) { s += v; if (v === 3) break; } return s; });
  await attempt('non-callable return', async () => { for await (const v of counter(42)) { break; } return 'x'; });
  await attempt('throw in body swallows close error', async () => {
    for await (const v of counter(function () { throw new Error('close failed'); })) { throw new RangeError('body ' + v); }
  });
  await attempt('sync iterable close', async () => {
    const sync = { [Symbol.iterator]() { return { next() { return { value: Promise.resolve('p'), done: false }; }, return() { log.push('sync return'); return { value: Promise.resolve('rv'), done: true }; } }; } };
    for await (const v of sync) { log.push('got ' + v); break; }
    return 'sync done';
  });
  await attempt('asyncIterator non-object', async () => { for await (const v of { [Symbol.asyncIterator]() { return 7; } }) {} });
  await attempt('next non-object', async () => { for await (const v of { [Symbol.asyncIterator]() { return { next() { return 3; } }; } }) {} });
  await attempt('rejected sync value', async () => {
    const sync = { [Symbol.iterator]() { return { next() { return { value: Promise.reject(new TypeError('bad value')), done: false }; }, return() { log.push('sync closed on reject'); return {}; } }; } };
    for await (const v of sync) { log.push('unreachable'); }
  });
  await attempt('poisoned constructor', async () => {
    const p = Promise.resolve(1);
    Object.defineProperty(p, 'constructor', { get() { throw new SyntaxError('ctor getter'); } });
    const sync = { [Symbol.iterator]() { return { next() { return { value: p, done: false }; } }; } };
    for await (const v of sync) { log.push('unreachable ' + v); }
  });
  let g = outer(asyncInner({}));
  await attempt('yield* first', () => g.next('a'));
  await attempt('yield* throw, no throw/return', () => g.throw(new Error('t1')));
  g = outer(asyncInner({ return() { log.push('inner return called'); return Promise.resolve({ done: true }); } }));
  await attempt('yield* first2', () => g.next());
  await attempt('yield* throw, return only', () => g.throw(new Error('t2')));
  g = outer(asyncInner({ throw(e) { return Promise.resolve({ value: 'inner caught ' + e, done: false }); } }));
  await attempt('yield* first3', () => g.next());
  await attempt('yield* throw delegated', () => g.throw('E'));
  await attempt('yield* next after throw', () => g.next('z'));
  g = outer(asyncInner({ throw(e) { return Promise.resolve({ value: 'inner caught rejected ' + e.message, done: false }); } }));
  await attempt('yield* first4', () => g.next());
  await attempt('yield* return(rejected)', () => g.return(Promise.reject(new Error('rej'))));
  const p = plain();
  await attempt('plain first', () => p.next());
  await attempt('plain return(rejected)', () => p.return(Promise.reject(new Error('boom'))));
  await attempt('plain after', () => p.next());
  Function.prototype[Symbol.dispose] = function () { log.push('fn dispose ' + this.name); };
  { using f = function () {}; using a = () => 0; log.push('using block body'); }
  delete Function.prototype[Symbol.dispose];
  let i = 0;
  for (await using x = ares('cfor'); i < 2; i++) log.push('cfor iter ' + i + ' ' + x.name);
  for await (await using y of [ares('of1'), null, ares('of2')]) log.push('for-await iter ' + (y && y.name));
  { await using n = null; log.push('await using null'); }
  await attempt('using non-disposable', async () => { await using bad = {}; });
  class SubPromise extends Promise {}
  let rejectLater;
  const sp = new SubPromise((_, r) => { rejectLater = r; });
  rejectLater(new URIError('deferred'));
  await attempt('subclass deferred reject', async () => { await sp; });
  log.push('subclass identity ' + (sp instanceof SubPromise));
  console.log(log.join('\n'));
}
main();
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_async_iteration")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 2980-2981, 3050, 3055-3057, 3995, 4290, 4388, 4392, 4405-4408, 4492, 4498, 4617, 4653, 4921-4932
@pytest.mark.parametrize("tier", TIERS)
def test_ev_class_private_brands_accessor_merging_and_arrow_super(js, golden, tier):
    """CATCHES: a class implementation that lets private methods be stamped twice or onto non-extensible objects, drops the getter when a private/public setter precedes it, ignores non-callable decorators, mis-names static anonymous fields, or that fails to rebind `this` when super() runs inside an arrow and the base constructor returns an override object, fails this."""
    code = r"""const log = [];
function t(label, f) { try { log.push(label + ': ' + f()); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); } }
class Base { constructor(o) { return o; } }
class Stamper extends Base {
  #m() { return 'm'; }
  constructor(o) { super(o); log.push('stamped ' + Stamper.has(o)); }
  static has(o) { return #m in o; }
}
const shared = {};
t('first stamp', () => { new Stamper(shared); return Stamper.has(shared); });
t('second stamp', () => { new Stamper(shared); return 'no error'; });
t('frozen target', () => { new Stamper(Object.preventExtensions({})); return 'no error'; });
class Fielder extends Base { #f = 1; static has(o) { return #f in o; } }
t('field on sealed', () => { const o = Object.seal({}); new Fielder(o); return Fielder.has(o); });
t('static private on non-extensible', () => {
  class S { static { Object.preventExtensions(this); } static #late = 1; }
  return 'no error';
});
t('accessor order', () => {
  class A {
    set #v(x) { this.log.push('set ' + x); }
    get #v() { return 'got'; }
    set w(x) { this.log.push('set w ' + x); }
    get w() { return 'w!'; }
    static set s(x) { A.slog = x; }
    static get s() { return 'static s'; }
    m() { return 'method'; }
    get m() { return 'getter replaces method'; }
    constructor() { this.log = []; this.#v = 5; this.w = 6; }
    read() { return this.#v + ',' + this.w + ',' + this.log.join('/'); }
  }
  A.s = 'x';
  const a = new A();
  const d = Object.getOwnPropertyDescriptor(A.prototype, 'm');
  return a.read() + ' ' + A.s + ' ' + A.slog + ' ' + typeof d.get + ' ' + a.m;
});
t('static fields', () => {
  class F { static anon = function () {}; static arrow = () => 1; static #p = function () {}; static empty; static pname() { return F.#p.name; } }
  return [F.anon.name, F.arrow.name, F.pname(), 'empty' in F, F.empty].join(',');
});
t('null prototype parent', () => {
  function P() {}
  P.prototype = null;
  class C extends P { constructor() { const o = Object.create(new.target.prototype); return o; } }
  return Object.getPrototypeOf(C.prototype) === null;
});
t('field decorator not callable', () => { class D { @(1) x = 1; } return 'no error'; });
t('accessor decorator not callable', () => { class D { @(2) accessor y = 1; } return 'no error'; });
const sharedObj = { tag: 'shared' };
class B2 { constructor(ret) { if (ret) return ret; this.fromB = true; } }
class D2 extends B2 {
  field = 'f';
  constructor(ret) { const go = () => super(ret); go(); this.later = () => super(); }
}
t('arrow super with override', () => { const d = new D2(sharedObj); return (d === sharedObj) + ' ' + d.field + ' ' + typeof d.later; });
t('arrow super plain', () => { const d = new D2(); return d.fromB + ' ' + d.field; });
t('arrow super after ctor', () => new D2().later());
t('static name method', () => { const C = class { static name() { return 'custom'; } }; return typeof C.name + ' ' + C.name(); });
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_class_elements")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 2006-2009, 2023-2025, 3609, 3632, 3644-3653, 3761-3764, 3894-3896, 6874, 6882, 6916, 6926-6928, 6931, 6971
@pytest.mark.parametrize("tier", TIERS)
def test_ev_direct_and_indirect_eval_declaration_instantiation(js, golden, tier):
    """CATCHES: an eval that lets a var/function hoist over a script-level let, rewrites the attributes of a non-configurable global when declaring a function, fails to re-create an Annex B block function binding deleted earlier in the same eval, or accepts super()/super.x through an ordinary function boundary fails this; so does a $262.evalScript global declaration step that skips CanDeclareGlobalFunction/Var (accessor, non-enumerable, non-extensible global) or partially declares a failing script."""
    code = r"""const log = [];
function t(label, f) { try { log.push(label + ': ' + f()); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); } }
const geval = eval;
$262.evalScript('let lexG = 1;');
t('global eval var over global let', () => geval('var lexG = 2; "declared"'));
t('global eval function over global let', () => geval('function lexG() {}'));
t('global let survives', () => geval('lexG'));
t('local let in eval stays local', () => geval('let evLocal = 5; evLocal') + ',' + typeof globalThis.evLocal);
Object.defineProperty(globalThis, 'pinned', { value: 'v', writable: true, enumerable: true, configurable: false });
t('global eval fn over non-configurable var', () => {
  geval('function pinned() { return "fn"; }');
  const d = Object.getOwnPropertyDescriptor(globalThis, 'pinned');
  return typeof pinned + ' ' + pinned() + ' configurable=' + d.configurable + ' enumerable=' + d.enumerable + ' writable=' + d.writable;
});
t('annexB re-create in function eval', () => (function () {
  return eval('var before = typeof q; var del = delete q; { function q() { return "q!"; } } [before, del, typeof q, q(), delete q, typeof q].join(",")');
})());
t('annexB re-create at global', () => geval('var b1 = typeof gq; var d1 = delete gq; { function gq() { return 1; } } [b1, d1, typeof gq, Object.getOwnPropertyDescriptor(globalThis, "gq").configurable].join(",")'));
class P {
  #secret = 42;
  static #s = 's';
  read() { return eval('this.#secret + P.#s'); }
}
t('eval sees private names', () => new P().read());
class E extends Object { x = eval('super(); 1'); }
t('super() in field init eval', () => new E().x);
class F2 extends Object { m() { return eval('super()'); } }
t('super() in method eval', () => new F2().m());
t('eval super prop in nested function', () => ({ m() { return (function () { return eval('super.toString'); })(); } }).m());
t('eval super prop via arrows', () => ({ m() { return (() => (() => eval('typeof super.hasOwnProperty'))())(); } }).m());
function evalAll(o) {
  return eval("var acc = [], i; for (i = 0; i < 2; i++) acc.push(i); for (var k in o) acc.push(k);" +
    " var af = async () => await 1; var lazy = () => import('./missing-module.mjs');" +
    " acc.push(String.raw`r${1}\\n`); var c = { ...o, z: 0 }; var h = [1, , 2];" +
    " acc.push(h.length, 1 in h, Object.keys(c).join('')); acc.join(';')");
}
t('eval walks every construct', () => evalAll({ p: 1, q: 2 }));
class K { #p = 1; static check(o) { return eval('#p in o'); } }
t('eval private in', () => K.check(new K()) + ' ' + K.check({}));
// Script-level GlobalDeclarationInstantiation through $262.evalScript (CanDeclareGlobalFunction/Var).
const attrs = (n) => { const p = Object.getOwnPropertyDescriptor(globalThis, n); return p ? ['w', 'e', 'c'].map((k, i) => [p.writable, p.enumerable, p.configurable][i] ? k : '-').join('') + (p.get ? ' accessor' : ' ' + typeof p.value) : 'absent'; };
globalThis.cfgProp = 1;
t('script fn over configurable prop', () => { $262.evalScript('function cfgProp() { return "fn"; }'); return attrs('cfgProp') + ' ' + cfgProp(); });
Object.defineProperty(globalThis, 'fixedProp', { value: 0, writable: true, enumerable: true, configurable: false });
t('script fn over non-configurable writable prop', () => { $262.evalScript('function fixedProp() { return "fixed fn"; }'); return attrs('fixedProp') + ' ' + fixedProp(); });
Object.defineProperty(globalThis, 'accProp', { get() { return 'acc'; }, configurable: false });
t('script fn over non-configurable accessor', () => $262.evalScript('function accProp() {}'));
Object.defineProperty(globalThis, 'hiddenProp', { value: 0, writable: true, enumerable: false, configurable: false });
t('script fn over non-enumerable non-configurable', () => $262.evalScript('function hiddenProp() {}'));
t('script var over non-configurable keeps attrs', () => { $262.evalScript('var hiddenProp = 5;'); return attrs('hiddenProp') + ' ' + hiddenProp; });
t('script let over var', () => $262.evalScript('let cfgProp = 1;'));
t('script let over restricted global', () => $262.evalScript('let NaN = 1;'));
$262.evalScript('let scriptLet = "L";');
t('script var over earlier script let', () => $262.evalScript('var scriptLet;'));
t('script function over earlier script let', () => $262.evalScript('function scriptLet() {}'));
t('failed script declares nothing', () => { try { $262.evalScript('var okA = 1; let scriptLet = 2;'); } catch (e) {} return typeof okA + ' ' + attrs('okA'); });
t('labelled function declaration hoists', () => { $262.evalScript('lbl: function labelled() { return "L!"; }'); return labelled() + ' ' + attrs('labelled'); });
Object.preventExtensions(globalThis);
t('script var on non-extensible global', () => $262.evalScript('var brandNew;'));
t('script fn on non-extensible global', () => $262.evalScript('function brandNewFn() {}'));
t('script fn redefining existing on non-extensible', () => { $262.evalScript('function cfgProp() { return "again"; }'); return cfgProp(); });
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_direct_eval")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 3563, 5010, 5059-5060, 5134, 6136-6145, 6166, 6193, 6279-6280, 7221
@pytest.mark.parametrize("tier", TIERS)
def test_ev_bigint_shift_compare_instanceof_and_operator_slow_paths(js, golden, tier):
    """CATCHES: BigInt shifts by counts >= 2**30 that hang, allocate or round wrongly (must be RangeError / 0n / -1n), string-vs-BigInt comparisons that go through floats, ToBigInt that accepts undefined/null/symbols, an instanceof that rejects an undefined @@hasInstance, or a typeof that does not report IsHTMLDDA as undefined, fails this."""
    code = r"""const log = [];
function t(label, f) { try { const v = f(); log.push(label + ': ' + (typeof v === 'bigint' ? v + 'n' : String(v))); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); } }
const huge = 2n ** 31n, big = 2n ** 30n;
t('shl huge', () => 1n << huge);
t('shl zero huge', () => 0n << huge);
t('shr huge neg', () => (-7n) >> big);
t('shr huge pos', () => 7n >> big);
t('shl negative huge', () => 7n << -big);
t('shl negative huge neg', () => (-7n) << -huge);
t('shr negative count', () => 3n >> -4n);
t('asIntN undefined', () => BigInt.asIntN(8, undefined));
t('asUintN symbol', () => BigInt.asUintN(8, Symbol('s')));
t('asIntN null', () => BigInt.asIntN(8, null));
t('str<big', () => '10' < 11n);
t('str>big', () => '100' > 11n);
t('bad str<big', () => 'x1' < 11n);
t('str>=big', () => ' 0x10 ' >= 16n);
t('big<=str', () => 16n <= '0b10000');
function F() {}
Object.defineProperty(F, Symbol.hasInstance, { value: undefined });
t('hasInstance undefined', () => new F() instanceof F);
function G() {}
Object.defineProperty(G, Symbol.hasInstance, { value: null });
t('hasInstance null', () => ({}) instanceof G);
t('hasInstance non-callable', () => { const H = function () {}; Object.defineProperty(H, Symbol.hasInstance, { value: 1 }); return {} instanceof H; });
t('non-callable rhs undefined handler', () => ({}) instanceof { [Symbol.hasInstance]: undefined });
const dda = $262.IsHTMLDDA;
function typeOf(v) { return typeof v; }
let seenType = '';
for (let i = 0; i < 30; i++) seenType = typeOf(dda);
t('IsHTMLDDA', () => [typeof $262.IsHTMLDDA, seenType, dda == null, dda === undefined, dda ? 'truthy' : 'falsy', typeof (dda ?? 'nullish')].join(','));
function dup(v) { return { a: v, b: 1, a: v + 1 }; }
let last;
for (let i = 0; i < 30; i++) last = dup(i);
t('duplicate literal keys', () => JSON.stringify(last));
t('regexp cache churn', () => { let hits = 0; for (let i = 0; i < 300; i++) if (new RegExp('^a' + i + '$').test('a' + i)) hits++; return hits; });
t('mod infinity', () => [5 % Infinity, -5 % -Infinity, Infinity % 2, 0 % Infinity, -0 % Infinity].map(String).join(',') + ' ' + Object.is(-0 % Infinity, -0));
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_operator_slow_paths")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 2033, 2203, 2220, 4848, 4886, 5401-5403, 5480, 5657-5679, 5763-5764, 5874-5875, 5884-5888, 7514-7526, 7628
@pytest.mark.parametrize("tier", TIERS)
def test_ev_assignment_targets_super_references_and_proxy_operator_traps(js, golden, tier):
    """CATCHES: for-in/of heads that cannot assign to member, computed, super or private targets, super compound assignment that reads from the receiver instead of the home object's prototype, a missing TypeError for a null super base, or in/delete/object-rest that bypass proxy has/deleteProperty/ownKeys traps and their invariants, fails this."""
    code = r"""const log = [];
function t(label, f) { try { log.push(label + ': ' + f()); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message); } }
const o = { list: [] };
t('for-of member', () => { for (o.p of ['a', 'b']) o.list.push(o.p); return o.list.join('') + o.p; });
t('for-of index', () => { const box = {}; let i = 0; for (box['k' + i++] of [10, 20]); return JSON.stringify(box); });
t('for-in index', () => { const box = []; for (box[box.length] in { x: 1, y: 2 }); return box.join('|'); });
class Base { set s(v) { (this.seen || (this.seen = [])).push('base set ' + v); } }
class Derived extends Base {
  #p = 0;
  run() {
    for (super.s of [1, 2]);
    for (super['s'] of [3]);
    for (this.#p of [4, 5]);
    return this.seen.join(';') + ' #p=' + this.#p + ' own s=' + Object.getOwnPropertyNames(this).includes('s');
  }
  bump() {
    super.n = 1;
    super.n += 10;
    super['n']++;
    return this.n;
  }
}
t('for-of super/private targets', () => new Derived().run());
t('super compound', () => new Derived().bump());
const nul = { __proto__: null, get() { return super.x; }, set() { super.x = 1; }, inc() { super.x++; } };
t('null super base get', () => nul.get());
t('null super base set', () => nul.set());
t('null super base update', () => nul.inc());
t('call target for-of', () => { let calls = 0; function f() { calls++; return {}; } try { for (f() of [1]); } catch (e) { return calls + ' ' + e.name + ': ' + e.message; } });
t('keyed patterns', () => {
  let a, b, c, d, e, fn1, fn2, q;
  const k = 'dyn';
  ({ 'str key': a, 7: b, [k]: c, 1.5: d, __proto__: e } = { 'str key': 'S', 7: 'seven', dyn: 'D', '1.5': 'onefive', __proto__: { tag: 'P' } });
  ({ m: [q] = ['dflt'], n: { z: fn1 = function () {} } = {} } = {});
  [[fn2 = () => 0] = []] = [];
  return [a, b, c, d, e.tag, q, fn1.name, fn2.name].join(',');
});
t('array nested default', () => { let x, y; [[x] = ['nx'], { y } = { y: 'ny' }] = []; return x + y; });
t('has trap non-callable', () => 'x' in new Proxy({ x: 1 }, { has: 5 }));
t('has false on configurable', () => 'x' in new Proxy({ x: 1 }, { has() { return false; } }));
t('has false on absent', () => 'y' in new Proxy({}, { has() { return false; } }));
t('has false on non-configurable', () => 'z' in new Proxy(Object.defineProperty({}, 'z', { value: 1 }), { has() { return false; } }));
t('has symbol key', () => { let seen; const p = new Proxy({}, { has(t, k) { seen = typeof k; return true; } }); return (Symbol.iterator in p) + ' ' + seen; });
const target = { a: 1 };
const dp = new Proxy(target, { deleteProperty(t, k) { log.push('trap ' + String(k)); return true; } });
t('delete trap true present', () => (delete dp.a) + ' still=' + ('a' in target));
t('delete trap true absent', () => delete dp.missing);
t('delete trap false', () => delete new Proxy({ q: 1 }, { deleteProperty() { return false; } }).q);
t('delete forwards to target', () => { const inner = { r: 1 }; return (delete new Proxy(inner, {}).r) + ' ' + ('r' in inner); });
t('delete in with non-configurable', () => { const o = Object.defineProperty({ c: 1 }, 'nc', { value: 2 }); with (o) { return [delete nc, delete c, delete notThere].join(',') + ' ' + Object.keys(o).join('') + ' ' + o.nc; } });
t('rest over proxy', () => {
  const p = new Proxy({ a: 1, b: 2, hidden: 3 }, {
    ownKeys() { return ['a', 'b', 'ghost', 'hidden']; },
    getOwnPropertyDescriptor(t, k) { if (k === 'ghost') return undefined; const d = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'hidden') d.enumerable = false; return d; },
  });
  const { a, ...rest } = p;
  return a + ' ' + JSON.stringify(rest);
});
t('rest over string', () => { const { 0: first, 2: third, ...rest } = 'wxyz'; return first + third + ' ' + JSON.stringify(rest); });
class Br { #v = 1; static read(o) { return o.#v; } static has(o) { return #v in o; } }
t('private read on primitive', () => Br.read(5));
t('private in on primitive', () => Br.has('s'));
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("ev_assignment_targets")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: eval.rs 694-695, 701, 1716, 1921, 7478
@pytest.mark.parametrize("tier", TIERS)
def test_ev_esm_default_export_names_import_tdz_and_attribute_proxies(js, golden, workdir, tier):
    """CATCHES: module code that names an anonymous `export default (class {})` / `(function () {})` anything but 'default', lets `typeof` read an import still in its TDZ across a cycle, allows compound assignment to an import binding, or reads import attributes without honouring a proxy's ownKeys/getOwnPropertyDescriptor traps, fails this."""
    (workdir / "b.mjs").write_text(r"""import { late } from './main.mjs';
let probe;
try { probe = typeof late; } catch (e) { probe = e.name + ': ' + e.message; }
export { probe };
export default (function () {});
""", encoding="utf-8")
    (workdir / "dep.mjs").write_text(r"""export let counter = 1;
export function bump() { counter += 10; }
""", encoding="utf-8")
    (workdir / "data.json").write_text('{"k": [1, 2]}\n', encoding="utf-8")
    code = r"""import * as self from './main.mjs';
import dc, { probe } from './b.mjs';
import { counter, bump } from './dep.mjs';
const log = [];
log.push('b saw: ' + probe);
export default (class {});
export let late = 'late';
log.push('default class name: ' + self.default.name);
log.push('default function name: ' + dc.name);
log.push('late now: ' + typeof late);
try { counter += 1; } catch (e) { log.push('compound import: ' + e.name + ': ' + e.message); }
try { counter++; } catch (e) { log.push('update import: ' + e.name + ': ' + e.message); }
bump();
log.push('live counter ' + counter);
const attrs = new Proxy({ type: 'json' }, {
  ownKeys() { return [Symbol('skip'), 'type', 'ghost']; },
  getOwnPropertyDescriptor(t, k) { return k === 'ghost' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); },
});
const ns = await import('./data.json', { with: attrs });
log.push('json ' + JSON.stringify(ns.default));
console.log(log.join('\n'));
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("ev_esm_bindings")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/collection_data.rs 90-93, 148-151, 182-195, 202-207, 210-212
BI_COLLECTIONS = r"""
// Three distinct keys whose 64-bit collection hashes are identical: a string, a Number
// with hand-picked bits and a BigInt with a hand-picked limb (FxHash inverted offline).
const str = "collision";
const num = new Float64Array(new BigUint64Array([0xeede71dd2e83e150n]).buffer)[0];
const big = 0xc2b33f5d91fed428n;
const log = [];
const m = new Map();
m.set(str, "s");
log.push("miss num " + m.has(num) + " " + m.get(num));
m.set(num, "n");
m.set(big, "b");
m.set(num, "n2");          // update through the chain
m.set(str, "s2");
log.push("size " + m.size + " get " + [m.get(str), m.get(num), m.get(big)].join(","));
log.push("miss other " + m.has("collision2") + " " + m.has(-num) + " " + m.has(big + 1n));
log.push("del num " + m.delete(num) + " again " + m.delete(num));   // middle of chain
log.push("after " + [m.get(str), m.get(num), m.get(big)].join(",") + " size " + m.size);
log.push("del str " + m.delete(str));     // head with a successor
log.push("big still " + m.get(big) + " has str " + m.has(str));
m.set(num, "n3"); m.set(str, "s3");
log.push("order " + [...m.keys()].map(k => typeof k).join(","));
log.push("del big " + m.delete(big) + " del str " + m.delete(str) + " del num " + m.delete(num) + " size " + m.size);
const s = new Set([str, num, big, str, num]);
log.push("set size " + s.size + " " + s.has(big) + s.has(num) + s.has(str));
s.delete(big); s.delete(str);
log.push("set left " + [...s].map(v => v === num) + " " + s.has(big) + s.has(str));
console.log(log.join("\n"));
// Weak collections compact their vacant slots once most entries are deleted.
const keys = Array.from({length: 12}, (_, i) => ({i}));
const wm = new WeakMap(keys.map(k => [k, "v" + k.i]));
const ws = new WeakSet(keys);
const sym = Symbol("weak");
wm.set(sym, "sym"); ws.add(sym);
const gone = [];
for (const k of keys) if (k.i % 4 !== 1) { gone.push(wm.delete(k) && ws.delete(k)); }
console.log("deleted " + gone.length + " " + gone.every(Boolean));
console.log("live " + keys.map(k => wm.has(k) ? wm.get(k) : "-").join(" "));
console.log("ws " + keys.map(k => ws.has(k) ? 1 : 0).join("") + " sym " + wm.get(sym) + " " + ws.has(sym));
wm.delete(keys[1]); wm.set(keys[0], "back");
console.log("again " + wm.get(keys[0]) + " " + wm.has(keys[1]) + " " + wm.get(keys[5]) + " " + wm.delete(keys[2]));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_collection_hash_collisions_and_weak_compaction(js, golden, tier):
    """CATCHES: a Map/Set that trusts the 64-bit key hash alone (or mishandles its collision chain when updating, deleting the head or a middle entry) confuses a string, a Number and a BigInt that share one hash; WeakMap/WeakSet compaction after mass deletion that loses or resurrects entries also fails."""
    r = js(BI_COLLECTIONS, *tier)
    assert out(r) == golden("bi_collections")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 2946, 2985, 2988, 3051-3052, 3158, 3173, 3218, 3258, 3262
BI_PROMISES = r"""
// Custom "promise" constructors drive the combinators' rarely used capability paths.
const sync = [];
const jobs = [];
const describe = e => (e && e.message !== undefined ? e.constructor.name + ":" + e.message : JSON.stringify(e));
const settle = (label, p) => jobs.push(p.then(v => label + " ok " + JSON.stringify(v), e => label + " err " + describe(e)));
// resolve() hands back thenables whose then() settles more than once: [[AlreadyCalled]] swallows repeats.
function Twice(executor) { return new Promise(executor); }
Twice.resolve = v => ({ then(f, r) { f(v); f("dup-" + v); r("late-" + v); } });
function Rejecting(executor) { return new Promise(executor); }
Rejecting.resolve = v => ({ then(f, r) { r("no-" + v); r("again-" + v); f("yes-" + v); } });
settle("all", Promise.all.call(Twice, [1, 2]));
settle("allSettled", Promise.allSettled.call(Twice, ["a"]));
settle("allSettled rejects", Promise.allSettled.call(Rejecting, ["b"]));
settle("any", Promise.any.call(Rejecting, ["c", "d"]).catch(e => { throw new Error(e.errors.join("|")); }));
settle("allKeyed", Promise.allKeyed.call(Twice, { x: 1, y: 2 }));
settle("allSettledKeyed", Promise.allSettledKeyed.call(Twice, { z: 3 }));
settle("allSettledKeyed rejects", Promise.allSettledKeyed.call(Rejecting, { w: 4 }));
// A capability whose resolve function throws: the combinator calls reject instead.
function Throwing(executor) {
  executor(() => { throw new RangeError("resolve exploded"); }, e => sync.push("Throwing rejected " + describe(e)));
}
Throwing.resolve = v => Promise.resolve(v);
Promise.allKeyed.call(Throwing, {});
Promise.allSettledKeyed.call(Throwing, {});
// A then() that throws synchronously rejects the keyed result.
function BadThen(executor) { return new Promise(executor); }
BadThen.resolve = v => ({ get then() { return () => { throw new TypeError("then " + v); }; } });
settle("keyed bad then", Promise.allKeyed.call(BadThen, { k: "v" }));
// An ownKeys trap that throws rejects the keyed combinator; non-enumerable keys are skipped.
settle("keyed ownKeys", Promise.allKeyed(new Proxy({ a: 1 }, { ownKeys() { throw new EvalError("no keys"); } })));
settle("keyed hidden", Promise.allKeyed(Object.defineProperty({ shown: 1 }, "hidden", { value: 2, enumerable: false })));
// A capability executor invoked twice is a TypeError thrown synchronously.
function Double(executor) { executor(() => {}, () => {}); executor(() => {}, () => {}); }
try { Promise.allKeyed.call(Double, {}); } catch (e) { sync.push("double " + describe(e)); }
// SpeciesConstructor: undefined falls back to %Promise%, a primitive is a TypeError, a missing @@species too.
const p1 = Promise.resolve(5); p1.constructor = undefined;
settle("species undefined", p1.finally(() => {}));
const p2 = Promise.resolve(6); p2.constructor = 42;
try { p2.finally(() => {}); } catch (e) { sync.push("species primitive " + e.constructor.name); }
const p3 = Promise.resolve(7); p3.constructor = { [Symbol.species]: undefined };
settle("species missing", p3.then(v => v * 2));
sync.push("sync done");
Promise.all(jobs).then(lines => console.log(sync.concat(lines).join("\n")));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_promise_combinators_with_custom_capabilities(js, golden, tier):
    """CATCHES: promise combinators (all/allSettled/any/allKeyed/allSettledKeyed) that ignore [[AlreadyCalled]] when a custom resolve() thenable settles twice, swallow a throwing capability resolve instead of rejecting, let a throwing then() or ownKeys trap escape synchronously, or mishandle SpeciesConstructor fallbacks fail this."""
    r = js(BI_PROMISES, *tier)
    assert out(r) == golden("bi_promises")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 1737-1740, 7869-7877, 8173, 8199-8215, 8295-8296, 8466, 8728, 8739, 8810, 8933, 8981-8988, 9034, 9173; jstr.rs 188-189, 233
BI_STRINGS = r"""
const hex = s => { const r = []; for (let k = 0; k < s.length; k++) { const cp = s.codePointAt(k); r.push(cp.toString(16)); if (cp > 0xffff) k++; } return r.join(" "); };
const out = [];
// Object search values whose symbol methods are null fall back to ToString of the object.
const sep = (method, text) => ({ [method]: null, toString() { return text; } });
out.push("replace " + "a-b-c".replace(sep(Symbol.replace, "-"), "+"));
out.push("replaceAll " + "a-b-c".replaceAll(sep(Symbol.replace, "-"), "+"));
out.push("match " + JSON.stringify("x1y22".match(sep(Symbol.match, "\\d+"))));
out.push("split " + JSON.stringify("a-b-c".split(sep(Symbol.split, "-"))));
out.push("search " + "hello".search(sep(Symbol.search, "l+")));
out.push("matchAll " + [..."a1b22".matchAll(sep(Symbol.matchAll, "\\d"))].map(m => m[0] + "@" + m.index).join(","));
out.push("matchAll() " + [..."ab".matchAll()].map(m => JSON.stringify(m[0]) + "@" + m.index).join(","));
out.push("matchAll(undefined) " + [..."xyz".matchAll(undefined)].length);
// Annex B substr with NaN start / NaN length / -Infinity.
out.push("substr " + JSON.stringify(["abcdef".substr(NaN, 2), "abcdef".substr(2, NaN), "abcdef".substr(-Infinity, 3), "abcdef".substr("x")]));
// Non-ASCII slice with an empty (reversed) range.
out.push("slice " + JSON.stringify(["h\u00e9llo".slice(3, 1), "h\u00e9llo".slice(1, 3), "h\u00e9llo".slice(-2)]));
// toWellFormed on well-formed non-ASCII strings returns them unchanged.
out.push("toWellFormed " + ["na\u00efve".toWellFormed(), "\u{1F600}".toWellFormed() === "\u{1F600}", hex("a\uD800b".toWellFormed())].join(" "));
// Characters in the U+10F800..U+10FFFF range iterate, encode and compare as one code point.
const hi = "\u{10FFFF}", mid = "\u{10F800}";
const it = (hi + "a" + mid)[Symbol.iterator]();
const steps = [];
for (let r = it.next(); !r.done; r = it.next()) steps.push(hex(r.value) + "/" + r.value.length);
out.push("iter " + steps.join(" "));
out.push("uri " + encodeURIComponent(hi + mid) + " " + encodeURI("x" + hi));
out.push("wellFormed " + [hi.isWellFormed(), (hi + mid).isWellFormed(), "\uDBFF".isWellFormed(), ("\uDBFF" + "\uDFFF") === hi, ("\uDBFF" + "\uDFFF").length].join(","));
// Relational comparison uses UTF-16 code units (astral < U+FFFF); join/repeat re-pair adjacent halves.
out.push("unit order " + ["\u{1F600}" < "\u{1F601}", "\u{1F601}" > "\u{1F600}a", "\u{1F600}" < "\uFFFF", "\uFFFF" < "\u{10000}", "\u{1D306}" > "\uD834"].join());
out.push("re-paired " + [("\uDF06" + "\uD834").repeat(3).length, [...("\uDF06" + "\uD834").repeat(3)].length, ["a\uD834", "\uDF06b"].join("") === "a\u{1D306}b", ["\uD834", "\uDF06"].join("").codePointAt(0).toString(16)].join());
// Lithuanian casing: uppercasing drops a dot above (U+0307) that follows a soft-dotted letter.
const softDotted = [0x69, 0x2148, 0x2149, 0x1D422, 0x1D457, 0x1D48A, 0x1D4BF, 0x1D4F2, 0x1D527, 0x1D55A, 0x1D58F, 0x1D5C2, 0x1D5F7, 0x1D62A, 0x1D65F, 0x1D692, 0x1E04C, 0x1E04D];
for (const cp of softDotted) {
  const s = String.fromCodePoint(cp) + "\u0307";
  out.push("lt upper " + hex(s) + " -> " + hex(s.toLocaleUpperCase("lt")));
}
// Intervening marks of other classes (U+0323 class 220, U+0328 class 202) are kept.
out.push("lt upper marks " + hex("i\u0323\u0307x".toLocaleUpperCase("lt")) + " | " + hex("j\u0328\u0307".toLocaleUpperCase("lt")));
// Lowercasing: More_Above looks through class-220 marks to a class-230 accent.
out.push("lt lower " + hex("I\u0323\u0300".toLocaleLowerCase("lt")) + " | " + hex("J\u0316\u0301".toLocaleLowerCase("lt")) + " | " + hex("I\u0323a".toLocaleLowerCase("lt")));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_string_protocol_fallbacks_and_unicode_edges(js, golden, tier):
    """CATCHES: string methods that do not fall back to ToString when an object's @@replace/@@match/@@split/@@search/@@matchAll is null, mishandle substr/slice NaN and reversed ranges, split U+10F800..U+10FFFF code points into lone surrogates when iterating or URI-encoding, compare astral characters by code point instead of UTF-16 code units, fail to re-pair surrogate halves joined by join/repeat, or get Lithuanian soft-dotted casing wrong fail this."""
    r = js(BI_STRINGS, *tier)
    assert out(r) == golden("bi_strings")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 752, 6373-6375, 7014, 7063, 7071, 7155-7254, 7286, 7290, 7334-7335, 7368, 7381, 7459-7477, 7540, 7627, 7896, 7905-7906
BI_ITERATORS = r"""
const log = [];
function src(name, values, opts = {}) {
  let k = 0;
  return {
    [Symbol.iterator]() { return this; },
    next() {
      if (opts.badResult && k === values.length) return 7;
      return k < values.length ? { value: values[k++], done: false } : { value: undefined, done: true };
    },
    return() { log.push("close " + name); if (opts.returnThrows) throw new Error(name + " return boom"); return {}; },
  };
}
function attempt(label, f) {
  try { const r = f(); log.push(label + " -> " + JSON.stringify(r)); }
  catch (e) { log.push(label + " !! " + e.constructor.name + ": " + e.message); }
}
// zipKeyed setup failures close the inputs that were already opened (reverse order).
attempt("keyed getter", () => Iterator.zipKeyed({ a: src("A", [1]), b: src("B", [2]), get c() { throw new RangeError("getter c"); } }));
attempt("keyed not iterable", () => Iterator.zipKeyed({ a: src("A", [1]), b: 5 }));
const gopdThrows = new Proxy({ a: src("A", [1]), b: src("B", [2]) }, {
  getOwnPropertyDescriptor(t, k) { if (k === "b") throw new SyntaxError("gopd b"); return Reflect.getOwnPropertyDescriptor(t, k); },
});
attempt("keyed gopd throws", () => Iterator.zipKeyed(gopdThrows));
const gopdMissing = new Proxy({ a: src("A", [1, 2]), ghost: src("G", [9]) }, {
  ownKeys: () => ["a", "ghost", "nothing"],
  getOwnPropertyDescriptor(t, k) { return k === "a" ? Reflect.getOwnPropertyDescriptor(t, k) : undefined; },
});
attempt("keyed gopd undefined", () => [...Iterator.zipKeyed(gopdMissing)]);
attempt("keyed padding getter", () => Iterator.zipKeyed({ a: src("A", [1]) }, { mode: "longest", padding: { get a() { throw new TypeError("pad a"); } } }));
// Index-like keys order: canonical array indices first, then strings ("01", 2**32-1) in insertion order.
attempt("keyed key order", () => Object.keys([...Iterator.zipKeyed({ b: [1], "01": [2], 7: [3], "4294967295": [4], 2: [5] })][0]));
// Positional zip: failures stepping the iterables iterator or the padding.
function* failingOuter() { yield src("P", [1]); throw new Error("outer step"); }
attempt("zip outer throws", () => Iterator.zip(failingOuter()));
attempt("zip padding not iterable", () => Iterator.zip([src("Q", [1])], { mode: "longest", padding: {} }));
attempt("zip padding next throws", () => Iterator.zip([src("R", [1])], { mode: "longest", padding: { [Symbol.iterator]() { return { next() { throw new EvalError("pad next"); } }; } } }));
attempt("zip padding return throws", () => Iterator.zip([src("S", [1]), src("T", [2])], { mode: "longest", padding: src("pad2", ["x", "y", "z"], { returnThrows: true }) }));
attempt("zip padding exhausted", () => [...Iterator.zip([src("U", [1]), src("V", [2, 3])], { mode: "longest", padding: ["p"] })]);
// strict mode: the first input finished, the others are probed with IteratorStep.
attempt("strict bad result", () => [...Iterator.zip([src("W", []), src("X", [], { badResult: true })], { mode: "strict" })]);
attempt("strict next not callable", () => { const it = Iterator.zip([src("Y", []), { [Symbol.iterator]() { return { next: 3, return() { log.push("close Z"); } }; } }], { mode: "strict" }); return it.next(); });
attempt("shortest close error wins", () => [...Iterator.zip([src("A2", [1]), src("B2", [1, 2], { returnThrows: true }), src("C2", [1, 2], { returnThrows: true })], { mode: "shortest" })]);
// Re-entrancy and return() on a finished zip.
let z;
z = Iterator.zip([{ [Symbol.iterator]() { return { next() { return z.next(); } }; } }]);
attempt("zip reenter next", () => z.next());
let z2;
z2 = Iterator.zip([{ [Symbol.iterator]() { return { next() { return z2.return(); }, return() { return {}; } }; } }]);
attempt("zip reenter return", () => z2.next());
const z3 = Iterator.zip([[1]]);
attempt("zip finished", () => [z3.next(), z3.next(), z3.return(), z3.return()]);
// Iterator.concat re-entrancy and return() before/after starting.
let c;
c = Iterator.concat({ [Symbol.iterator]() { return { next() { return c.next(); } }; } });
attempt("concat reenter next", () => c.next());
let c2;
c2 = Iterator.concat({ [Symbol.iterator]() { return { next() { return c2.return(); }, return() { return {}; } }; } });
attempt("concat reenter return", () => c2.next());
const c3 = Iterator.concat(src("D", [1, 2]), src("E", [3]));
attempt("concat return unstarted", () => [c3.return(), c3.next()]);
const c4 = Iterator.concat(src("F", [1, 2]), src("G2", [3]));
attempt("concat return mid", () => [c4.next(), c4.return(), c4.next()]);
// Iterator helper re-entrancy through return().
let h;
h = [1, 2].values().map(x => h.return());
attempt("helper reenter return", () => h.next());
// take() whose source runs dry before the limit.
const took = [1, 2].values().take(5);
log.push("take short " + JSON.stringify([took.next(), took.next(), took.next(), took.next()]));
// flatMap: a mapper result with a non-callable @@iterator is a TypeError that closes the source.
let closed = 0;
const counter = { i: 0, next() { return { value: this.i++, done: false }; }, return() { closed++; return {}; }, __proto__: Iterator.prototype };
attempt("flatMap bad iterator", () => counter.flatMap(() => ({ [Symbol.iterator]: 5 })).next());
log.push("source closed " + closed);
// Subclassing Iterator: OrdinaryCreateFromConstructor uses newTarget.prototype.
class Countdown extends Iterator {
  constructor(n) { super(); this.n = n; }
  next() { return this.n > 0 ? { value: this.n--, done: false } : { value: undefined, done: true }; }
}
const cd = new Countdown(3);
log.push("subclass " + (Object.getPrototypeOf(cd) === Countdown.prototype) + " " + [...cd.map(x => x * 10)].join());
attempt("abstract Iterator", () => new Iterator());
// Iterator.prototype[@@toStringTag] and constructor use SetterThatIgnoresPrototypeProperties.
const tagSetter = Object.getOwnPropertyDescriptor(Iterator.prototype, Symbol.toStringTag).set;
const child = Object.create(Iterator.prototype);
child[Symbol.toStringTag] = "Mine";
log.push("tag on child " + Object.prototype.toString.call(child) + " own=" + Object.getOwnPropertySymbols(child).length);
attempt("tag on home", () => { Iterator.prototype[Symbol.toStringTag] = "x"; return "no error"; });
attempt("tag on primitive", () => tagSetter.call(5, "x"));
const child2 = Object.create(Iterator.prototype);
Object.getOwnPropertyDescriptor(Iterator.prototype, "constructor").set.call(child2, Array);
log.push("constructor on child " + (child2.constructor === Array) + " " + Object.getOwnPropertyDescriptor(child2, "constructor").enumerable);
// Completed generators: return() reports its argument, throw() rethrows; a primitive receiver is rejected.
function* g() { yield 1; }
const gen = g();
gen.next(); gen.next();
attempt("done gen return", () => gen.return(42));
attempt("done gen throw", () => gen.throw(new RangeError("after completion")));
attempt("gen next on primitive", () => Object.getPrototypeOf(g).prototype.next.call(5));
console.log(log.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_iterator_zip_concat_and_helper_error_paths(js, golden, tier):
    """CATCHES: Iterator.zip/zipKeyed/concat and iterator helpers that fail to close already-opened inputs (in reverse order) when setup, padding or strict-mode probing throws, let the first close error lose to a later one, allow re-entrant next()/return(), misorder index-like keys, or mishandle completed generators and SetterThatIgnoresPrototypeProperties fail this."""
    r = js(BI_ITERATORS, *tier)
    assert out(r) == golden("bi_iterators")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 671, 996, 1285, 1310, 1402-1407, 1796
BI_PROXIES = r"""
const log = [];
const show = (label, v) => log.push(label + ": " + (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)));
// Reflect.set with a foreign receiver walks the target chain (OrdinarySet).
const seen = [];
const proxy = new Proxy({}, { set(t, k, v, r) { seen.push("set trap " + String(k) + "=" + v + " recv=" + (r === recv)); return true; } });
const viaProxy = Object.create(proxy);
const recv = {};
show("proxy on chain", Reflect.set(viaProxy, "k", 1, recv));
show("trap log", seen.join("; "));
// A TypedArray on the chain with a foreign receiver.
const ta = new Int8Array(4);
const child = Object.create(ta);
const r2 = {};
show("ta index foreign", Reflect.set(child, "1", 9, r2) + " " + JSON.stringify(r2) + " ta=" + ta.join());
show("ta non-index numeric", Reflect.set(child, "-0", 9, r2) + " " + Object.keys(r2).join());
show("ta 1.5", Reflect.set(child, "1.5", 9, r2) + " " + Object.keys(r2).join());
show("ta ordinary key", Reflect.set(child, "name", "n", r2) + " " + r2.name);
// The receiver itself is a TypedArray: integer keys go through its exotic define.
const recvTa = new Uint8Array(2);
show("recv ta in range", Reflect.set({}, "1", 300, recvTa) + " " + recvTa.join());
show("recv ta out of range", Reflect.set({}, "5", 1, recvTa) + " " + recvTa.length);
// Receiver with an accessor or a non-writable data property refuses the write.
const acc = Object.defineProperty({}, "x", { get() { return 1; }, configurable: true });
show("recv accessor", Reflect.set({ x: 0 }, "x", 2, acc));
const ro = Object.defineProperty({}, "x", { value: 1, writable: false, configurable: true });
show("recv readonly", Reflect.set({ x: 0 }, "x", 2, ro));
show("recv primitive", Reflect.set({ x: 0 }, "x", 2, 5));
show("recv frozen", Reflect.set({}, "y", 2, Object.freeze({})));
// Reflect.get through a proxy on the prototype chain threads the receiver.
const gp = new Proxy({}, { get(t, k, r) { return "got " + String(k) + " recv=" + (r === recv); } });
show("get via proxy chain", Reflect.get(Object.create(gp), "q", recv));
// Revoked proxies in various reflective positions.
const { proxy: rp, revoke } = Proxy.revocable({}, {});
revoke();
for (const [label, f] of [
  ["getPrototypeOf", () => Object.getPrototypeOf(rp)],
  ["lookupGetter", () => Object.prototype.__lookupGetter__.call(Object.create(rp), "x")],
  ["isPrototypeOf", () => Object.prototype.isPrototypeOf.call({}, Object.create(rp))],
  ["instanceof", () => Object.create(rp) instanceof Object],
  ["construct newTarget", () => Reflect.construct(function () {}, [], rp)],
]) {
  try { show(label, f()); } catch (e) { show(label, e.constructor.name); }
}
const tryShow = (label, f) => { try { show(label, f()); } catch (e) { show(label, e.constructor.name); } };
// Descriptor maps and Object.values/entries over proxies that report phantom keys.
const phantom = new Proxy({ real: { value: 1, enumerable: true } }, {
  ownKeys: () => ["real", "ghost"],
  getOwnPropertyDescriptor(t, k) { return k === "ghost" ? undefined : Reflect.getOwnPropertyDescriptor(t, k); },
});
const defined = Object.defineProperties({}, phantom);
show("defineProperties", JSON.stringify(Object.getOwnPropertyDescriptors(defined)));
const valueSrc = new Proxy({ a: 1, b: 2, c: 3 }, {
  ownKeys: () => ["a", "b", "c", "ghost"],
  getOwnPropertyDescriptor(t, k) {
    if (k === "ghost") return undefined;
    const d = Reflect.getOwnPropertyDescriptor(t, k);
    if (k === "b") d.enumerable = false;
    return d;
  },
});
show("values", JSON.stringify(Object.values(valueSrc)) + " entries " + JSON.stringify(Object.entries(valueSrc)));
// Invariant checks that must PASS: reporting exactly the non-configurable target property.
const getter = function () { return "g"; };
const target = {};
Object.defineProperty(target, "acc", { get: getter, configurable: false, enumerable: true });
Object.defineProperty(target, "frozen", { value: 5, writable: false, configurable: false, enumerable: true });
Object.defineProperty(target, "nc", { value: 1, writable: true, configurable: false, enumerable: false });
const honest = new Proxy(target, {
  getOwnPropertyDescriptor(t, k) {
    if (k === "acc") return { get: getter, configurable: false, enumerable: true };
    if (k === "frozen") return { value: 5, writable: false, configurable: false, enumerable: true };
    return Reflect.getOwnPropertyDescriptor(t, k);
  },
  defineProperty(t, k, d) { return true; },
});
show("gOPD acc", JSON.stringify(Object.getOwnPropertyDescriptor(honest, "acc"), (k, v) => typeof v === "function" ? "fn" : v));
show("gOPD frozen", JSON.stringify(Object.getOwnPropertyDescriptor(honest, "frozen")));
show("gOPD nc", JSON.stringify(Object.getOwnPropertyDescriptor(honest, "nc")));
show("define acc same", Reflect.defineProperty(honest, "acc", { get: getter }));
show("define frozen same", Reflect.defineProperty(honest, "frozen", { value: 5, writable: false }));
show("define nc enumerable same", Reflect.defineProperty(honest, "nc", { enumerable: false, configurable: false }));
tryShow("define acc different getter", () => Reflect.defineProperty(honest, "acc", { get() {}, configurable: false }));
tryShow("define frozen other value", () => Reflect.defineProperty(honest, "frozen", { value: 6, configurable: false }));
tryShow("define nc enumerable flip", () => Reflect.defineProperty(honest, "nc", { enumerable: true, configurable: false }));
const liar = new Proxy(target, { getOwnPropertyDescriptor(t, k) { return { value: 9, writable: false, configurable: false, enumerable: true }; } });
tryShow("gOPD frozen lie", () => Object.getOwnPropertyDescriptor(liar, "frozen"));
tryShow("gOPD acc lie", () => Object.getOwnPropertyDescriptor(liar, "acc"));
console.log(log.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_reflect_receivers_and_proxy_invariants(js, golden, tier):
    """CATCHES: a Reflect.set/Reflect.get that ignores a proxy or TypedArray on the prototype chain, writes integer keys on a TypedArray receiver as ordinary properties, accepts writes onto accessor/read-only/frozen receivers, or proxy invariant checks that reject honest descriptors (or accept lies about non-configurable properties) fail this."""
    r = js(BI_PROXIES, *tier)
    assert out(r) == golden("bi_proxies")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 950, 1078-1081, 1244-1249, 1500-1504, 2782, 4828, 4850, 5678, 5722, 5766-5769, 6816-6817, 6874, 6881, 6888; array_iterator.rs 173-174
BI_ARRAYS = r"""
const log = [];
const show = (label, v) => log.push(label + ": " + v);
const tryShow = (label, f) => { try { show(label, f()); } catch (e) { show(label, e.constructor.name + (e instanceof TypeError || e instanceof RangeError && !e.message.startsWith("define") ? "" : ": " + e.message)); } };
function traced(target, name, opts = {}) {
  return new Proxy(target, {
    deleteProperty(t, k) { log.push(name + " delete " + k); return opts.refuseDelete ? false : Reflect.deleteProperty(t, k); },
    defineProperty(t, k, d) {
      log.push(name + " define " + k + "=" + JSON.stringify(d.value));
      if (opts.defineThrows) throw new RangeError("define " + k);
      return opts.refuseDefine ? false : Reflect.defineProperty(t, k, d);
    },
  });
}
// Hot push/pop: array-likes that borrow the methods and arrays at the maximum length take the generic path.
function hotPush(a, v) { return a.push(v); }
function hotPop(a) { return a.pop(); }
let sum = 0;
for (let k = 0; k < 60; k++) { const a = [k]; sum += hotPush(a, 1) + hotPop(a); }
show("warm", sum);
const like = { length: 2, 0: "a", 1: "b", push: Array.prototype.push, pop: Array.prototype.pop };
show("like", hotPop(like) + " len=" + like.length + " push=" + hotPush(like, "z") + " " + JSON.stringify(like));
const big = [];
big.length = 2 ** 32 - 1;
tryShow("max push", () => hotPush(big, "x"));
show("after max push", big.length + " stored=" + big[4294967295] + " pop=" + hotPop(big) + " len=" + big.length);
// Array mutators delete through the proxy's deleteProperty trap (DeletePropertyOrThrow).
const p1 = traced([1, 2, 3], "p1");
tryShow("pop", () => Array.prototype.pop.call(p1) + " len=" + p1.length);
tryShow("shift", () => Array.prototype.shift.call(p1) + " rest=" + JSON.stringify(Array.from(p1)));
const p2 = traced([1, 2, 3], "p2", { refuseDelete: true });
tryShow("pop refused", () => Array.prototype.pop.call(p2));
tryShow("splice refused", () => Array.prototype.splice.call(traced([1, 2, 3], "p3", { refuseDelete: true }), 0, 1));
// Array.from / Array.of / map with a constructor that returns a proxy: CreateDataPropertyOrThrow traps.
function Maker() { return traced({}, "made"); }
tryShow("from", () => JSON.stringify(Array.from.call(Maker, ["a", "b"])));
tryShow("from arraylike", () => JSON.stringify(Array.from.call(Maker, { length: 1, 0: "z" })));
function Thrower() { return traced({}, "thr", { defineThrows: true }); }
tryShow("from throws", () => Array.from.call(Thrower, [1]));
const species = [5, 6];
species.constructor = { [Symbol.species]: Maker };
tryShow("map species", () => JSON.stringify(species.map(x => x * 2)));
// Non-constructor receivers fall back to plain arrays.
const plainFrom = Array.from.call(undefined, { length: 2, 0: "x", 1: "y" });
show("from non-ctor", JSON.stringify(plainFrom) + " " + Array.isArray(plainFrom));
show("from non-ctor iterable", JSON.stringify(Array.from.call(Math.max, new Set([3, 4]))));
show("of non-ctor", JSON.stringify(Array.of.call(parseInt, 1, 2)));
tryShow("from huge non-ctor", () => Array.from.call(undefined, { length: 2 ** 32 }));
// Array iterators over primitives and null.
show("values on string", JSON.stringify([...Array.prototype.values.call("a\u{10FFFF}")].map(s => s.charCodeAt(0).toString(16))));
show("entries on number", JSON.stringify([...Array.prototype.entries.call(5)]));
tryShow("keys on null", () => Array.prototype.keys.call(null));
// ArraySpeciesCreate / ArrayCreate limits on huge array-likes (no element is visited).
tryShow("map huge arraylike", () => Array.prototype.map.call({ length: 2 ** 32 }, x => x));
// Species lookup across realms: another realm's %Array% constructor is replaced by this realm's.
const other = $262.createRealm().global;
const foreign = new other.Array(1, 2, 3);
const mapped = Array.prototype.map.call(foreign, x => x + 1);
show("foreign %Array%", (Object.getPrototypeOf(mapped) === Array.prototype) + " " + mapped.join());
foreign.constructor = other.Object;
const mapped2 = Array.prototype.map.call(foreign, x => x * 2);
show("foreign Object ctor", (Object.getPrototypeOf(mapped2) === Array.prototype) + " " + mapped2.join());
foreign.constructor = { [Symbol.species]: other.Array };
const mapped3 = Array.prototype.map.call(foreign, x => -x);
show("foreign species", (Object.getPrototypeOf(mapped3) === other.Array.prototype) + " " + mapped3.join());
// Compact element stores (small builtin-made arrays, new Array(n)) and indexed/mirrored large arrays.
const keysLen = (a) => JSON.stringify(Object.keys(a)) + " len=" + a.length;
const cp1 = "a,b,c".split(",");
Object.defineProperty(cp1, "1", { value: "B", enumerable: true });
Object.defineProperty(cp1, "6", { value: "G", writable: true, enumerable: true, configurable: true });
show("define inside/after compact", keysLen(cp1) + " " + cp1.join("|"));
cp1[1000] = "far";
show("far index then pop", cp1.pop() + " " + keysLen(cp1));
show("pop again", cp1.pop() + " " + keysLen(cp1));
const cHoles = new Array(8);
cHoles.length = 3;
cHoles.push("pushed");
show("holey shrink then push", keysLen(cHoles) + " " + JSON.stringify(cHoles));
show("holey pop", cHoles.pop() + " " + cHoles.pop() + " " + keysLen(cHoles));
const cHoles2 = new Array(4);
show("pop of hole", String(cHoles2.pop()) + " " + cHoles2.length + " delete beyond " + delete cHoles2[10] + " delete hole " + delete cHoles2[1]);
const cAcc = Array.of("x", "y");
Object.defineProperty(cAcc, "1", { get() { return "got"; }, configurable: true });
show("pop accessor tail", cAcc.pop() + " " + keysLen(cAcc));
const cFixed = Array.of("x", "y");
Object.defineProperty(cFixed, "1", { value: "fixed", configurable: false });
tryShow("pop non-configurable tail", () => cFixed.pop());
show("after failed pop", keysLen(cFixed));
const cBig = Array.from({ length: 40 }, (_, i) => i);
for (let k = 0; k < 10; k++) cBig["name" + k] = k;
cBig.push(40);
cBig[45] = 45;
show("indexed big push/gap", cBig.length + " " + cBig[40] + " " + (44 in cBig) + " " + cBig[45]);
Object.defineProperty(cBig, "45", { get() { return "acc45"; }, configurable: true });
show("pop accessor on big", cBig.pop() + " " + cBig.length);
cBig.length = 5;
show("truncate keeps names", Object.keys(cBig).join() + " " + cBig.join());
const cNums = Array.from({ length: 40 }, (_, i) => i * 1.5);
cNums[1000] = 1;
Object.defineProperty(cNums, "1000", { value: 2, writable: true, enumerable: true, configurable: true });
cNums["007"] = "a";
cNums["007"] = "b";
show("mirror far/non-canonical", cNums.length + " " + cNums[1000] + " " + cNums["007"] + " " + cNums[7] + " " + cNums.reduce((s, v) => s + (typeof v === "number" ? v : 0), 0));
Array.fromAsync.call(undefined, { length: 2 ** 32 }).then(v => show("fromAsync huge", v), e => show("fromAsync huge", e.constructor.name)).then(() => console.log(log.join("\n")));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_array_generics_on_proxies_and_array_likes(js, golden, tier):
    """CATCHES: Array mutators and constructors (pop/shift/splice/from/map, hot-path push/pop) that bypass a proxy's deleteProperty/defineProperty traps, ignore a refused delete, keep a foreign realm's %Array% as species, create arrays past 2**32-1, or iterate primitive receivers incorrectly fail this; so do compact/indexed element stores that lose elements or holes when defining past the end, adding far indices, shrinking length, popping accessor/non-configurable tails or overwriting non-canonical "007" keys."""
    r = js(BI_ARRAYS, *tier)
    assert out(r) == golden("bi_arrays")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 518, 3656, 3971, 4313, 4377, 4580, 5004, 5260, 5938, 6020, 9237, 9412
BI_MISC = r"""
const log = [];
const show = (label, v) => log.push(label + ": " + v);
const tryShow = (label, f) => { try { show(label, f()); } catch (e) { show(label, e.constructor.name + ": " + e.message); } };
// Number formatting corner cases.
show("toExponential", [(0).toExponential(0), (-0).toExponential(0), (0).toExponential(2), (1.5).toExponential(0), (2.5).toExponential(0)].join(" "));
show("f16round tiny", [Math.f16round(1e-20), Math.f16round(-1e-300), Math.f16round(6e-8), Math.f16round(2.9e-8)].map(x => Object.is(x, -0) ? "-0" : String(x)).join(" "));
show("includes fromIndex", [[1, 2, 3].includes(3, 1.5), [1, 2, 3].includes(1, 0.9), [1, 2, 3].includes(1, 1), [NaN].includes(NaN, 0.5)].join());
// Wrapper constructors honour newTarget.prototype, falling back to the intrinsic when it is a primitive.
function NT() {}
NT.prototype = 5;
const boxed = Reflect.construct(String, ["ab"], NT);
show("String newTarget fallback", (Object.getPrototypeOf(boxed) === String.prototype) + " " + boxed.length + " " + boxed[1]);
const nt2 = function () {}; nt2.prototype = Object.create(Number.prototype, { tag: { value: "custom" } });
const n2 = Reflect.construct(Number, [7], nt2);
show("Number newTarget proto", n2.tag + " " + (n2 + 1));
const ntThrows = new Proxy(function () {}, { get(t, k) { if (k === "prototype") throw new EvalError("no prototype"); return Reflect.get(t, k); } });
tryShow("Boolean newTarget throws", () => Reflect.construct(Boolean, [true], ntThrows));
// Array length descriptor validation.
tryShow("length accessor", () => Object.defineProperty([], "length", { get() { return 1; } }));
show("length configurable", [Reflect.defineProperty([1], "length", { configurable: true }), Reflect.defineProperty([1], "length", { enumerable: true }), Reflect.defineProperty([1], "length", { value: 1, writable: true }), Reflect.defineProperty([1], "length", { value: 0, configurable: true }), Reflect.defineProperty([1], "length", { value: 3, enumerable: true })].join());
// Errors thrown deep inside flat/splice/groupBy propagate unchanged.
const inner = [1];
Object.defineProperty(inner, 0, { get() { throw new URIError("deep element"); } });
tryShow("flat depth 3", () => [[0, [inner]]].flat(3));
tryShow("flat depth 2 ok", () => [[0, [inner]]].flat(2).length);
const arrayLike = { 0: "a", 1: "b", get length() { return 2; }, set length(v) { throw new RangeError("length set " + v); } };
tryShow("splice length setter", () => Array.prototype.splice.call(arrayLike, 0, 1));
show("after splice", JSON.stringify(arrayLike));
tryShow("groupBy throws", () => Object.groupBy([1, 2], x => { if (x === 2) throw new SyntaxError("group " + x); return "k"; }));
tryShow("Map.groupBy ok", () => JSON.stringify([...Map.groupBy([1, 2, 3], x => x % 2)]));
// Mapped arguments: a refused redefinition leaves the alias intact.
function mapped(a) {
  Object.defineProperty(arguments, "0", { configurable: false });
  const refused = Reflect.defineProperty(arguments, "0", { enumerable: false });
  a = "changed";
  return refused + " " + arguments[0] + " " + Object.getOwnPropertyDescriptor(arguments, "0").configurable;
}
show("arguments", mapped("orig"));
// TypedArray element redefinition without a value keeps the element.
const ta = new Int8Array([4, 5]);
show("TA define no value", Reflect.defineProperty(ta, "0", { writable: true, enumerable: true, configurable: true }) + " " + ta[0] + " " + Reflect.defineProperty(ta, "1", { configurable: false }) + " " + Reflect.defineProperty(ta, "2", { value: 1 }));
// Object.assign from a proxy that reports a key as non-enumerable.
const src = new Proxy({ a: 1, b: 2 }, { getOwnPropertyDescriptor(t, k) { const d = Reflect.getOwnPropertyDescriptor(t, k); if (k === "a") d.enumerable = false; return d; } });
show("assign from proxy", JSON.stringify(Object.assign({}, src)));
// Array.prototype.toString falls back to the intrinsic Object.prototype.toString when join is unusable.
const noJoin = [1, 2]; noJoin.join = null;
const tagged = []; tagged.join = 7; tagged[Symbol.toStringTag] = "Tagged";
const proxied = new Proxy([3], { get(t, k) { return k === "join" ? undefined : Reflect.get(t, k); } });
show("toString without join", [noJoin.toString(), tagged.toString(), Array.prototype.toString.call(proxied)].join(" "));
// __lookupGetter__ walks past a proxy that has no such own property.
const base = { get g() { return "base getter"; } };
const viaProxy = Object.create(new Proxy(Object.create(base), {}));
show("lookupGetter through proxy", viaProxy.__lookupGetter__("g") === Object.getOwnPropertyDescriptor(base, "g").get);
// %TypedArray%.prototype.byteOffset getter, also after detaching.
const offsetGetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Int8Array.prototype), "byteOffset").get;
const view = new Int16Array(new ArrayBuffer(16), 4, 2);
const before = offsetGetter.call(view);
$262.detachArrayBuffer(view.buffer);
show("byteOffset", before + " " + offsetGetter.call(view) + " " + view.length);
console.log(log.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_object_number_builtin_corner_cases(js, golden, tier):
    """CATCHES: builtins that mis-format (0).toExponential(0), round tiny values in Math.f16round to anything but a signed zero, mishandle includes() fractional fromIndex, newTarget prototype fallbacks for wrapper constructors, array length descriptor validation, errors thrown deep inside flat/splice/groupBy, mapped-arguments or TypedArray redefinition, or Array#toString without a callable join fail this."""
    r = js(BI_MISC, *tier)
    assert out(r) == golden("bi_misc")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 1933, 2146, 2150, 2516
BI_REGEXP = r"""
const log = [];
const show = (label, v) => log.push(label + ": " + v);
const tryShow = (label, f) => { try { show(label, f()); } catch (e) { show(label, e.constructor.name + ": " + e.message); } };
const statics = () => JSON.stringify([RegExp.input, RegExp.lastMatch, RegExp["$1"], RegExp.leftContext, RegExp.rightContext]);
// Discarded-result replace/match in hot code still update the legacy RegExp statics,
// including the empty-match advance at the end of the subject.
function hotReplace(s) { s.replace(/(z*)$/g, "-"); return 1; }
function hotMatch(s) { s.match(/(q*)/g); return 1; }
let n = 0;
for (let k = 0; k < 40; k++) n += hotReplace("ab" + k);
show("after replace", statics());
for (let k = 0; k < 40; k++) n += hotMatch("cd" + k);
show("after match", statics() + " " + n);
// RegExpExec on a non-RegExp whose exec is not callable.
tryShow("test non-regexp", () => RegExp.prototype.test.call({ exec: 5 }, "x"));
tryShow("test exec returns", () => RegExp.prototype.test.call({ exec() { return {}; } }, "x"));
// lastIndex shapes that the built-in fast paths must decline.
const ro = /b/;
Object.defineProperty(ro, "lastIndex", { value: 0, writable: false });
show("readonly lastIndex test", ro.test("abc") + " " + "abc".replace(ro, "B"));
const rog = /b/g;
Object.defineProperty(rog, "lastIndex", { value: 0, writable: false });
try { "abc".replace(rog, "B"); show("readonly global replace", "no error"); } catch (e) { show("readonly global replace", e.constructor.name + " lastIndex=" + rog.lastIndex); }
for (const li of [-1, 1.5, "1", { valueOf() { return 2; } }]) {
  const r = /c/y;
  r.lastIndex = li;
  show("sticky lastIndex " + JSON.stringify(li), r.test("abc") + " -> " + r.lastIndex);
}
const r2 = /a/g; r2.lastIndex = 10;
show("lastIndex past end", r2.exec("aaa") + " " + r2.lastIndex);
// Discarded exec() results in hot code: lastIndex shapes the built-in fast path must decline.
function hotExec(re, s) { re.exec(s); return 1; }
function drive(label, re, s) {
  let n = 0;
  for (let k = 0; k < 30; k++) n += hotExec(re, s);
  log.push(label + ": " + n + " lastIndex=" + String(re.lastIndex) + " lastMatch=" + RegExp.lastMatch);
}
drive("plain", /b+/, "abbc");
drive("global", /c/g, "cxc");
const roHot = /d/; Object.defineProperty(roHot, "lastIndex", { value: 0, writable: false });
drive("readonly", roHot, "xdx");
const neg = /e/; neg.lastIndex = -1;
drive("negative", neg, "xex");
const frac = /f/; frac.lastIndex = 1.5;
drive("fraction", frac, "fff");
const str = /g/; str.lastIndex = "0";
drive("string", str, "agg");
// A patched exec must be observed by replace/match even on literals.
const origExec = RegExp.prototype.exec;
let calls = 0;
RegExp.prototype.exec = function (s) { calls++; return origExec.call(this, s); };
function hotPatched(s) { s.replace(/b/, "x"); s.match(/d/); return 1; }
for (let k = 0; k < 20; k++) hotPatched("abcd");
RegExp.prototype.exec = origExec;
show("patched exec calls", calls);
// Statics are per realm: a match in another realm does not clobber this realm's.
const other = $262.createRealm().global;
/(main)/.exec("in main realm");
other.eval('/(oth)er/.exec("the other realm")');
show("realm statics", RegExp["$1"] + " " + other.RegExp["$1"]);
/(again)/.exec("main again");
show("realm statics 2", RegExp["$1"] + " " + other.RegExp["$1"] + " " + other.RegExp.lastMatch);
console.log(log.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_regexp_lastindex_and_legacy_statics(js, golden, tier):
    """CATCHES: a RegExp implementation whose exec fast paths ignore non-writable or non-integer lastIndex values, skips a patched RegExp.prototype.exec, accepts a non-RegExp receiver with a non-callable exec, or shares the legacy RegExp.$1/lastMatch statics across realms fails this."""
    r = js(BI_REGEXP, *tier)
    assert out(r) == golden("bi_regexp")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/host.rs 173, 191, 203-204, 209, 217-221; builtins/globals.rs 130; eval.rs 3408-3443
BI_HOST = r"""
const out = [];
// $262.agent in the main thread: no workers, so broadcast is a no-op and getReport has nothing.
const sab = new SharedArrayBuffer(16);
out.push("broadcast sab " + $262.agent.broadcast(sab) + " view " + $262.agent.broadcast(new Int32Array(sab), 3));
out.push("getReport " + $262.agent.getReport() + " " + $262.agent.getReport());
out.push("sleep " + $262.agent.sleep(2) + " " + $262.agent.sleep(0) + " " + $262.agent.sleep(-5));
try { $262.agent.setTimeout(42, 0); } catch (e) { out.push("setTimeout non-callable " + e.constructor.name); }
// Indirect eval returns non-string arguments unchanged.
const obj = { tag: "same object" };
out.push("indirect eval " + [(0, eval)(42), (0, eval)(obj) === obj, (0, eval)(undefined), typeof (0, eval)(Symbol.iterator), (0, eval)("6 * 7")].join(","));
// Host timers fire after the script has finished and its microtasks drained; a timer armed by
// another timer fires (after a short wait) once the first callback's microtasks have run.
const events = [];
$262.agent.setTimeout(() => {
  events.push("timer A");
  Promise.resolve().then(() => events.push("microtask after A"));
  $262.agent.setTimeout(() => {
    events.push("timer B");
    console.log(out.join("\n"));
    console.log(events.join("\n"));
  }, 5);
}, 0);
Promise.resolve().then(() => events.push("script microtask"));
events.push("script end");
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_host_agent_timers_and_indirect_eval(js, golden, tier):
    """CATCHES: a test262 host whose $262.agent broadcast/getReport/sleep misbehave without worker agents, whose setTimeout accepts non-callables or fires timers before the script's microtasks (or never fires a timer armed by another timer), or whose indirect eval does not return non-string arguments unchanged fails this."""
    r = js(BI_HOST, *tier, name="main.mjs")
    assert out(r) == golden("bi_host")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: builtins/mod.rs 1463-1465, 3397-3400, 3517-3520, 4355
BI_NS_A = r"""
import * as bns from "./b.mjs";
export let late = "a-late";
export function hoisted() { return "a-hoisted"; }
export const report = bns.report;
"""
BI_NS_B = r"""
import * as ans from "./a.mjs";
export const report = [];
const probe = (label, f) => { try { report.push(label + " = " + f()); } catch (e) { report.push(label + " threw " + e.constructor.name); } };
// b runs first: a's `let` export is still in its TDZ, the hoisted function is already live.
probe("hasOwn late", () => Object.prototype.hasOwnProperty.call(ans, "late"));
probe("hasOwn hoisted", () => Object.prototype.hasOwnProperty.call(ans, "hoisted"));
probe("propertyIsEnumerable late", () => Object.prototype.propertyIsEnumerable.call(ans, "late"));
probe("keys", () => Object.keys(ans).join());
probe("Reflect.get late", () => Reflect.get(ans, "late", {}));
probe("Reflect.get hoisted", () => Reflect.get(ans, "hoisted", {})());
export function later() {
  probe("after hasOwn late", () => Object.prototype.hasOwnProperty.call(ans, "late"));
  probe("after propertyIsEnumerable", () => [Object.prototype.propertyIsEnumerable.call(ans, "late"), Object.prototype.propertyIsEnumerable.call(ans, "missing"), Object.prototype.propertyIsEnumerable.call(ans, Symbol.toStringTag)].join());
  probe("after keys", () => Object.keys(ans).join());
  probe("after Reflect.get", () => [Reflect.get(ans, "late", {}), Reflect.get(ans, "missing", {}), Reflect.get(ans, Symbol.toStringTag, 1)].join());
  probe("Reflect.set", () => Reflect.set(ans, "late", 1));
  probe("defineProperty", () => [Reflect.defineProperty(ans, "late", { enumerable: true }), Reflect.defineProperty(ans, "late", { value: "a-late" }), Reflect.defineProperty(ans, "late", { value: 1 }), Reflect.defineProperty(ans, "late", { writable: false }), Reflect.defineProperty(ans, "fresh", { value: 1 })].join());
  probe("hasOwn missing", () => Object.prototype.hasOwnProperty.call(ans, "missing"));
}
"""
BI_NS_MAIN = r"""
import * as ans from "./a.mjs";
import { later, report } from "./b.mjs";
later();
console.log(report.join("\n"));
console.log(Object.keys(ans).join(), ans[Symbol.toStringTag]);
"""


@pytest.mark.parametrize("tier", TIERS)
def test_bi_module_namespace_reflective_ops_in_cycle(js, golden, workdir, tier):
    """CATCHES: module namespace objects whose hasOwnProperty/propertyIsEnumerable/Object.keys/Reflect.get do not throw ReferenceError for an export still in its TDZ during a cyclic import, or whose Reflect.set/defineProperty accept writes and new keys, fail this."""
    (workdir / "a.mjs").write_text(BI_NS_A, encoding="utf-8")
    (workdir / "b.mjs").write_text(BI_NS_B, encoding="utf-8")
    r = js(BI_NS_MAIN, *tier, name="main.mjs")
    assert out(r) == golden("bi_namespace")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: parser.rs 78, 862-863, 901, 1138, 1261, 3067, 3129, 3487, 3665, 3787, 3794, 3978, 4002, 4004,
#   4015-4019, 4025, 4031, 4034, 4037-4040 (pattern_strict_banned), 4095-4097, 4144-4145, 4153
PM_PARSER_PATTERNS = r"""var out = [];
function show(v) { return typeof v === 'string' ? JSON.stringify(v) : String(v); }
function se(src) { try { return 'ok ' + show((0, eval)(src)); } catch (e) { return e.name + ': ' + e.message; } }
function group(name, list) { out.push('# ' + name); list.forEach(function (src) { out.push(JSON.stringify(src) + ' => ' + se(src)); }); }
group('strict destructuring assignment', [
  '"use strict"; var a, r; [a, , ...r] = [1, 2, 3, 4]; a + "|" + r',
  '"use strict"; var a, b; [a = 1, b] = []; ({ k: a = 2, b = 3 } = {}); a + b',
  '"use strict"; var a, c, d; ({ a, b: c = 9, ...d } = { a: 1, e: 5 }); [a, c, JSON.stringify(d)].join("|")',
  '"use strict"; var p; ({ __proto__: p } = { __proto__: null }); String(p)',
  '"use strict"; var p2; ({ __proto__: p2 = 4 } = Object.create(null)); p2',
  '"use strict"; var o = {}; ({ ...o.rest } = { z: 1 }); JSON.stringify(o)',
  '"use strict"; var q; for ([q] of [[5]]); q',
  '"use strict"; [eval] = []',
  '"use strict"; [...arguments] = []',
  '"use strict"; [arguments = 1] = []',
  '"use strict"; [[eval]] = [[]]',
  '"use strict"; ({ arguments } = {})',
  '"use strict"; ({ eval = 1 } = {})',
  '"use strict"; ({ a: eval } = {})',
  '"use strict"; ({ a: eval = 1 } = {})',
  '"use strict"; ({ __proto__: eval } = {})',
  '"use strict"; ({ __proto__: eval = 1 } = {})',
  '"use strict"; ({ ...eval } = {})',
  '"use strict"; for ([eval] of []);',
  '"use strict"; for ({ x: arguments } of []);',
  '"use strict"; for ([f()] of []);',
  '"use strict"; for ([1] of []);',
]);
group('pattern validity', [
  '({ __proto__: a1 = 1 } = {}); a1',
  '({ ...r4 } = { k: 1 }); JSON.stringify(r4)',
  '({ ...[a2] } = {})',
  '({ ...r3, a3 } = {})',
  '({ m() {} } = {})',
  '({ get g() { return 1; } } = {})',
  '({ a: x = { b = 1 } } = {})',
  '({ __proto__: x = { c = 1 } } = {})',
  '({ ...{ y = 1 }.z } = {})',
  '[...{ w = 1 }.v] = []',
  'var hole; for ([, hole] of [[1, 2]]); hole',
  'var o = {}; for ([o.p] of [[1]]); o.p',
  'for ({ m() {} } of []);',
  'for ({ a: 1 } of []);',
  'for ({ a, ...{ b } } of []);',
  'var { "a" } = {}',
  'let { 1 } = {}',
  '({ "a" } = {})',
  '({ 1 })',
  '({ [k] })',
]);
group('functions, classes and labels', [
  'class C1 { #x = 5; m() { return eval("this.#x * 2"); } } new C1().m()',
  'class C2 { #x = 5; m() { return eval("this.#y"); } } new C2().m()',
  'class A extends Object { constructor() { super(); var o = { m() { super(); } }; } }',
  'class A extends Object { constructor() { super(); var o = { m(a = super()) {} }; } }',
  '(async function () { for await (var x = 0 in {}) ; })',
  '"use strict"; (implements => 1)',
  '"use strict"; (yield => 1)',
  '(async function () { (await => 1); })',
  '(async await => 1)',
  'class S3 { static { (await => 1); } }',
  'class S4 { static { (async () => await 1); } } "static block async arrow"',
  '({ set s(v) { "use strict"; } }) && "strict setter"',
  '({ set s(static) { "use strict"; } })',
  'class A1 { accessor x; } Object.getOwnPropertyNames(A1.prototype).join()',
  'function* g() { L1: yield: 1; }',
  'async function af() { L1: L2: await: 1; }',
  'L: function f(,) {}',
]);
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_pm_strict_destructuring_and_pattern_early_errors(js, golden, tier):
    """CATCHES: a parser that skips the strict-mode eval/arguments check inside destructuring
    assignment patterns (array/object/__proto__/rest/default and for-of heads), accepts invalid
    rest/method/cover-initializer targets, mis-reports shorthand-key, label-chain, arrow-binding
    and nested super() errors, or loses private names visible to a direct eval fails this."""
    r = js(PM_PARSER_PATTERNS, *tier)
    assert out(r) == golden("pm_strict_destructuring_patterns")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: lexer.rs 562, 603-606, 633-638, 656-670, 680-682, 713, 724, 857, 867-868, 876, 883-890, 1051;
#   parser.rs 2821-2826, 2892-2897 (lexer errors inside template substitutions)
PM_LEXER_TEMPLATES = r"""var out = [];
function show(v) { return typeof v === 'string' ? JSON.stringify(v) : String(v); }
function se(src) { try { return 'ok ' + show((0, eval)(src)); } catch (e) { return e.name + ': ' + e.message; } }
function group(name, list) { out.push('# ' + name); list.forEach(function (src) { out.push(JSON.stringify(src).replace(/\u2028/g, '<LS>') + ' => ' + se(src)); }); }
group('template substitutions re-scanned by the lexer', [
  '`[${ "a\\"}b" }]`',
  "`[${ 'c\\'{d' }]`",
  '`[${ `in\\`ner${ 1 + 1 }` }]`',
  '`[${ /a\\/[/}]b/.source }]`',
  '`[${ /x/gimsuy.flags }]`',
  '`[${ 1 /* } */ + 2 }]`',
  '`[${ 1 // }\n + 3 }]`',
  '`${ /* never closed',
  '`${ "never closed',
  '`${ `never closed',
  '`${ /never closed',
  '`${ 0x }`',
  'String.raw`a${ 0b2 }b`',
  '`trailing backslash\\',
]);
out.push('# template escapes');
function tag(s) { return JSON.stringify(s) + ' raw=' + JSON.stringify(s.raw); }
out.push(tag`\u{123456789}`);
out.push(tag`a\u{110000}b${1}\u{00000041}`);
out.push(se('`\\u{123456789}`'));
out.push(se('`\\u{110000}`'));
group('surrogate escapes', [
  '"\\uD83D\\u{DE00}".codePointAt(0).toString(16)',
  '"\\uD83D\\u{DE00".length',
  '"\\uD83D\\uDE0".length',
  '"\\uD83D\\uZZZZ".length',
  '"\\uDBFF\\uDFFF".codePointAt(0).toString(16) + "/" + "\\uDBFF\\uDFFF".length',
  '"\\uDBFF\\uDFFF" === "\\u{10FFFF}"',
  '"\\uD800\\u0041".length + "/" + "\\uD800\\u0041".charCodeAt(0).toString(16) + "/" + "\\uD800\\u0041".charCodeAt(1)',
  '"\\uD800\\u{41}".charCodeAt(1)',
]);
group('regex literal line terminators', [
  '/a\\\nb/',
  '/a\\\u2028b/',
  '/a\\ b/.source',
]);
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_pm_template_substitution_rescan_and_surrogate_escapes(js, golden, tier):
    """CATCHES: a lexer whose template-substitution scanner is confused by braces or backticks
    inside nested strings, templates, regex literals (classes, escapes, flags) and comments,
    mis-reports unterminated pieces inside a substitution, accepts out-of-range braced code points
    in templates, or pairs a high-surrogate escape with a following braced/four-digit escape (or a
    non-surrogate escape) into the wrong code units fails this."""
    r = js(PM_LEXER_TEMPLATES, *tier)
    assert out(r) == golden("pm_template_rescan_surrogates")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: parser.rs 103-106 (module lexer error), 220-224 (import vs var clash), 1659, 1770, 1813
PM_MODULE_SYNTAX_FILES = {
    'escas.mjs': "export * \\u0061s ns from './lib.mjs';\n",
    'escfrom.mjs': "var y = 2;\nexport { y } fr\\u006fm './lib.mjs';\n",
    'importvar.mjs': "import { x } from './lib.mjs';\nvar x;\n",
    'lexerr.mjs': 'var s = "never closed\n',
    'lib.mjs': "export var x = 1;\nexport default 'lib default';\n",
    'srcdefault.mjs': "import source from './lib.mjs';\nexport default 'default import named source: ' + source;\n",
    'srcfrom.mjs': "import source from from './lib.mjs';\n",
    'srcfrom2.mjs': "import source from from '<module source>';\nexport default typeof from;\n",
}


def test_pm_module_parse_errors_and_source_keyword_forms(js, golden, workdir):
    """CATCHES: a module parser that does not surface tokenizer errors as SyntaxErrors from
    import(), lets a top-level var redeclare an imported binding, treats `import source from` as a
    source-phase import (or `import source from from` as a default import), or accepts escaped
    `as`/`from` contextual keywords in export clauses fails this."""
    for name, text in PM_MODULE_SYNTAX_FILES.items():
        (workdir / name).write_text(text, encoding="utf-8")
    r = js(r"""for (const n of ['lexerr', 'importvar', 'srcdefault', 'escas', 'escfrom', 'srcfrom', 'srcfrom2']) {
  try { const m = await import('./' + n + '.mjs'); console.log(n + ': ok ' + m.default); }
  catch (e) { console.log(n + ': ' + e.name + ': ' + e.message); }
}
""", name="main.mjs")
    assert out(r) == golden("pm_module_parse_errors")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: modules.rs 263-264, 505-507, 561-573 (<module source> ModuleSource), 606-607 (re-exported
#   source binding), 823-849 (self-deferred namespace stub hydration), 1564-1565 (same_binding)
PM_SOURCE_PHASE_FILES = {
    'lazy.mjs': "console.log('lazy evaluated');\nexport const lv = 'lazy value';\n",
    'other.mjs': "export const o = 'other';\n",
    's1.mjs': "import defer * as lz from './lazy.mjs';\nexport { lz };\nexport const mixed = 's1 local';\n",
    's2.mjs': "import defer * as lz from './lazy.mjs';\nimport * as mixed from './other.mjs';\nexport { lz, mixed };\n",
    'selfdefer.mjs': "import defer * as me from './selfdefer.mjs';\nconsole.log('selfdefer body');\nexport const v = 'self value';\nexport function read() { return me.v + ' / ' + Object.keys(me).join(','); }\n",
    'srcre.mjs': "import source mod from '<module source>';\nexport { mod };\n",
    'star-mixed.mjs': "import { mixed } from './star.mjs';\nexport { mixed };\n",
    'star.mjs': "export * from './s1.mjs';\nexport * from './s2.mjs';\n",
}


def test_pm_source_phase_star_bindings_and_self_deferred_namespace(js, golden, workdir):
    """CATCHES: a module linker that gives `import source` of the host '<module source>' a fresh or
    wrongly-prototyped object per importer, cannot re-export a source binding, treats star exports
    of the same deferred namespace as ambiguous (or a local vs a namespace as not ambiguous), or
    leaves a module's self-deferred namespace with an empty export table after evaluation fails
    this."""
    for name, text in PM_SOURCE_PHASE_FILES.items():
        (workdir / name).write_text(text, encoding="utf-8")
    r = js(r"""import source s from '<module source>';
import { mod } from './srcre.mjs';
import * as star from './star.mjs';
import { read } from './selfdefer.mjs';
const AMS = $262.AbstractModuleSource;
console.log(typeof s, Object.getPrototypeOf(s) === AMS.prototype, s === mod, String(s[Symbol.toStringTag]));
console.log(Object.prototype.toString.call(s), Object.keys(s).length, Object.isExtensible(s));
try { AMS(); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log('star keys:', Object.keys(star).join(','), 'mixed' in star);
console.log(Object.prototype.toString.call(star.lz));
console.log('before lz access');
console.log(star.lz.lv);
console.log(read());
try { const m = await import('./star-mixed.mjs'); console.log('mixed ok', m.mixed); } catch (e) { console.log(e.name + ': ' + e.message); }
""", name="main.mjs")
    assert out(r) == golden("pm_source_phase_star_bindings")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: modules.rs 1085-1090 (in-cycle dependency parked at await), 1104-1106 (dependency whose
#   evaluation already failed)
PM_TLA_CYCLE_FILES = {
    'bad.mjs': "console.log('bad evaluated');\nthrow new RangeError('bad module');\n",
    'ca.mjs': "import { bv } from './cb.mjs';\nconsole.log('ca body sees', bv);\nexport const av = 'A';\n",
    'cb.mjs': "import './ca.mjs';\nconsole.log('cb before await');\nawait null;\nconsole.log('cb after await');\nexport const bv = 'B';\n",
    'tla-ok.mjs': "await null;\nconsole.log('tla-ok evaluated');\nexport const tla = 'ok';\n",
    'uses.mjs': "import './bad.mjs';\nconsole.log('uses evaluated (never)');\n",
    'uses2.mjs': "import { tla } from './tla-ok.mjs';\nimport './uses.mjs';\nconsole.log('uses2 evaluated (never)', tla);\n",
}


@pytest.mark.parametrize("tier", TIERS)
def test_pm_tla_cycle_order_and_previously_failed_dependency(js, golden, workdir, tier):
    """CATCHES: async module evaluation that runs a cycle member before its in-cycle dependency
    finishes its top-level await, or that re-evaluates (or silently accepts) a module whose
    evaluation already threw when a later dynamic import reaches it directly or through another
    graph that also starts an unrelated async module fails this."""
    for name, text in PM_TLA_CYCLE_FILES.items():
        (workdir / name).write_text(text, encoding="utf-8")
    r = js(r"""import { av } from './ca.mjs';
console.log('main', av);
try { await import('./bad.mjs'); } catch (e) { console.log('first:', e.name, e.message); }
try { await import('./uses.mjs'); } catch (e) { console.log('dependent:', e.name, e.message); }
try { await import('./uses2.mjs'); } catch (e) { console.log('indirect:', e.name, e.message); }
const again = await import('./ca.mjs');
console.log('cycle namespace', again.av, Object.keys(again).join(','));
""", *tier, name="main.mjs")
    assert out(r) == golden("pm_tla_cycle_failed_dep")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: modules.rs 860, 917-918 (deferred module that itself defers), 1166, 1357, 1370-1379,
#   1384-1387 (async subgraph of import.defer() and nested defers)
PM_DEFER_ASYNC_FILES = {
    'd.mjs': "import { tv } from './t.mjs';\nconsole.log('d evaluated');\nexport const dv = 'D+' + tv;\n",
    'nd-a.mjs': "import defer * as b from './nd-b.mjs';\nconsole.log('nd-a evaluated');\nexport const x = 'ax';\nexport function getB() { return b.y; }\n",
    'nd-b.mjs': "import { z } from './nd-c.mjs';\nimport { z as z2 } from './nd-d.mjs';\nconsole.log('nd-b evaluated');\nexport const y = 'by+' + z + z2;\n",
    'nd-c.mjs': "import './nd-d.mjs';\nconsole.log('nd-c evaluated');\nexport const z = 'cz';\n",
    'nd-d.mjs': "console.log('nd-d evaluated');\nexport const z = 'dz';\n",
    'p.mjs': "import defer * as d from './d.mjs';\nconsole.log('p evaluated');\nexport function get() { return d.dv; }\n",
    'self-tla.mjs': "console.log('self-tla start');\nawait null;\nconsole.log('self-tla end');\nexport const sv = 'S';\n",
    't.mjs': "console.log('t start');\nawait null;\nconsole.log('t end');\nexport const tv = 'T';\n",
    't2.mjs': "console.log('t2 start');\nawait Promise.resolve();\nconsole.log('t2 end');\nexport const tv2 = 'T2';\n",
    'x.mjs': "import { tv2 } from './t2.mjs';\nimport defer * as yy from './y.mjs';\nconsole.log('x evaluated');\nexport const xv = 'X+' + tv2;\nexport function readY() { return yy.yv; }\n",
    'y.mjs': "console.log('y evaluated');\nexport const yv = 'Y';\n",
}


@pytest.mark.parametrize("tier", TIERS)
def test_pm_import_defer_async_subgraphs_and_nested_defers(js, golden, workdir, tier):
    """CATCHES: `import defer` / `import.defer()` handling that evaluates the deferred module
    itself too early, fails to run its top-level-await dependencies eagerly (or runs an already
    finished one again), or mis-orders a deferred module's own eager and deferred dependencies
    (including a shared dependency reached twice) once it is finally touched fails this."""
    for name, text in PM_DEFER_ASYNC_FILES.items():
        (workdir / name).write_text(text, encoding="utf-8")
    r = js(r"""import defer * as nd from './nd-a.mjs';
console.log('main start');
const t = await import('./t.mjs');
console.log('t loaded', t.tv);
const p = await import('./p.mjs');
console.log('p get', p.get());
const x = await import.defer('./x.mjs');
console.log('x deferred ns', Object.prototype.toString.call(x));
console.log('x value', x.xv);
console.log('y via x', x.readY());
const st = await import.defer('./self-tla.mjs');
console.log('self-tla', st.sv);
console.log('touch nd');
console.log(nd.x);
console.log(nd.getB());
""", *tier, name="main.mjs")
    assert out(r) == golden("pm_defer_async_subgraphs")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: modules.rs 1304 (ancestor already rejected while the async-ancestor cascade runs)
PM_CASCADE_FILES = {
    'leaf.mjs': "console.log('leaf start');\nawait null;\nconsole.log('leaf end');\nexport const lv = 1;\n",
    'mid.mjs': "import { lv } from './leaf.mjs';\nconsole.log('mid runs with', lv);\nthrow new TypeError('mid failed after async leaf');\n",
    'quiet.mjs': 'globalThis.onunhandledrejection = (ev) => ev.preventDefault();\n',
    'side.mjs': "import './leaf.mjs';\nconsole.log('side runs');\n",
}


def test_pm_sync_module_throw_after_async_leaf_rejects_root(js, workdir):
    """CATCHES: an async-module cascade that still executes the root after a synchronous ancestor
    of a top-level-await leaf throws, skips the independent sibling that the same leaf unblocked,
    or exits 0 / reports a different error once the module graph rejects fails this."""
    for name, text in PM_CASCADE_FILES.items():
        (workdir / name).write_text(text, encoding="utf-8")
    r = js(r"""import './quiet.mjs';
import './mid.mjs';
import './side.mjs';
console.log('main body (never)');
""", name="main.mjs")
    assert out(r) == "leaf start\nleaf end\nmid runs with 1\nside runs\n"
    assert (r.returncode, err(r)) == (1, "Uncaught TypeError: mid failed after async leaf\n")


# ---------------------------------------------------------------- interpreter.rs call/construct boundaries


# covers: interpreter.rs 4649, 4728, 4732, 4848-4849, 4858-4861, 4868, 4870, 4998-4999, 5013-5014, 7569
IC_REALM_BOUNDARIES = r"""const log = [];
const t = (label, f) => { try { log.push(label + ': ' + f()); } catch (e) { log.push(label + ': ' + e.constructor.name + ': ' + e.message); } };
const sr = new ShadowRealm();
const callWith = sr.evaluate(`(function (cb, mode) {
  const c = (f) => { try { return f(); } catch (e) { return 'inner caught ' + e.constructor.name + ': ' + e.message; } };
  if (mode === 'fn') return cb(function (z) { return 'realm fn got ' + z; });
  if (mode === 'obj') return c(() => cb({}));
  if (mode === 'ret-fn') { const r = cb(); return typeof r + ' ' + r(4); }
  if (mode === 'ret-obj') return c(() => cb());
  if (mode === 'throw') return c(() => cb());
  return cb(1, 'two', null, undefined, 3n, Symbol.iterator.description);
})`);
t('host callback receives a wrapped realm function', () => callWith(function (f) { return typeof f + ' -> ' + f('x'); }, 'fn'));
t('host callback given an object', () => callWith(function (o) { return 'host got ' + typeof o; }, 'obj'));
t('host callback returns a function', () => callWith(function () { return function (q) { return q * 2; }; }, 'ret-fn'));
t('host callback returns an object', () => callWith(function () { return {}; }, 'ret-obj'));
t('host callback throws', () => callWith(function () { throw new Error('host boom'); }, 'throw'));
t('primitives cross unchanged', () => callWith(function (...a) { return a.map(String).join('|'); }, 'prims'));
t('object argument to wrapped fn', () => callWith({}, 'fn'));
t('wrapped fn returns object', () => sr.evaluate('(function () { return []; })')());
t('wrapped fn returns callable', () => { const g = sr.evaluate('(function () { return function inner(a, b) { return a + b; }; })')(); return typeof g + ' ' + g.name + '/' + g.length + ' ' + g(2, 3); });
t('wrapped fn throws', () => sr.evaluate('(function () { throw new RangeError("inside"); })')());
const shapes = sr.evaluate(`(function (kind) {
  const f = function named(a, b, c) {};
  if (kind === 'no-length') { delete f.length; return f; }
  if (kind === 'string-length') return Object.defineProperty(f, 'length', { value: '7' });
  if (kind === 'inf-length') return Object.defineProperty(f, 'length', { value: Infinity });
  if (kind === 'neg-length') return Object.defineProperty(f, 'length', { value: -4.5 });
  if (kind === 'frac-length') return Object.defineProperty(f, 'length', { value: 2.9 });
  if (kind === 'throw-length') return Object.defineProperty(f, 'length', { get() { throw new Error('len'); } });
  if (kind === 'num-name') return Object.defineProperty(f, 'name', { value: 42 });
  if (kind === 'throw-name') return Object.defineProperty(f, 'name', { get() { throw new Error('nm'); } });
  if (kind === 'proxy-gopd') return new Proxy(f, { getOwnPropertyDescriptor() { throw new Error('gopd'); } });
  return f;
})`);
for (const kind of ['plain', 'no-length', 'string-length', 'inf-length', 'neg-length', 'frac-length', 'num-name', 'throw-length', 'throw-name', 'proxy-gopd']) {
  t('wrapper of ' + kind, () => { const g = shapes(kind); return JSON.stringify(g.name) + '/' + g.length; });
}
t('evaluate returns length-less fn', () => { const g = sr.evaluate('(() => { const f = function () {}; delete f.length; return f; })()'); return g.length; });
// [[Construct]] through proxies whose targets cannot be constructed.
t('new proxy of Math.max', () => new (new Proxy(Math.max, {}))());
t('new proxy of arrow', () => new (new Proxy(() => 1, {}))());
t('new proxy of method', () => new (new Proxy({ m() {} }.m, {}))());
t('new proxy of async fn', () => new (new Proxy(async function () {}, {}))());
t('new proxy of wrapped fn', () => new (new Proxy(sr.evaluate('(function () {})'), {}))());
// GetFunctionRealm through 70 nested proxies / bound functions when prototype is not an object.
function Base() { this.made = true; }
Base.prototype = 3;
let nt = Base;
for (let k = 0; k < 70; k++) nt = (k % 2) ? new Proxy(nt, {}) : nt.bind(null);
t('deep newTarget chain', () => { const o = Reflect.construct(function () {}, [], nt); return (Object.getPrototypeOf(o) === Object.prototype) + ' ' + Object.keys(o).length; });
const other = $262.createRealm().global;
const OtherBase = other.eval('(function OtherBase() {})');
OtherBase.prototype = null;
t('foreign newTarget with null prototype', () => Object.getPrototypeOf(Reflect.construct(function () {}, [], OtherBase)) === other.Object.prototype);
// A native function with a long non-Function prototype chain is called in the active realm.
let chain = {};
for (let k = 0; k < 12; k++) chain = Object.create(chain);
const mx = Math.max;
Object.setPrototypeOf(mx, chain);
t('native fn with long proto chain', () => mx(3, 9, 4) + ' ' + Reflect.apply(mx, null, [1, 2]));
t('construct proxy after createRealm', () => { const P = new Proxy(function Pc(v) { this.v = v; }, {}); return new P(5).v; });
t('construct foreign proxy', () => { const P = new Proxy(other.eval('(function Fp(v) { this.v = v * 2; })'), {}); const o = new P(5); return o.v + ' ' + (o instanceof other.Object); });
console.log(log.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_ic_shadowrealm_wrappers_and_function_realm_lookup(js, golden, tier):
    """CATCHES: ShadowRealm wrapped functions that pass objects across the boundary, fail to wrap callables in either direction, leak the original error instead of a TypeError, or copy name/length without the CopyNameAndLength rules (missing, non-number, infinite, negative, fractional, throwing); also GetFunctionRealm that gives up on long bound/proxy chains or picks the wrong realm's Object.prototype for a foreign newTarget."""
    r = js(IC_REALM_BOUNDARIES, *tier)
    assert out(r) == golden("ic_realm_boundaries")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 6041, 6046, 6290-6298, 6301, 6303-6305, 6424, 6446
IC_HOT_SITES = r"""function F(a, b) { this.a = a; this.b = b; }
function make(n) { return new F(n, n + 1); }
var s = 0, out = [];
for (var i = 0; i < 300; i++) s += make(i).b;
out.push(s);
F.extra = 'shape change';
for (var i = 0; i < 50; i++) s += make(i).a;
out.push(s, Object.getPrototypeOf(make(1)) === F.prototype);
var oldProto = F.prototype;
F.prototype = 7;
var o = make(2);
out.push(Object.getPrototypeOf(o) === Object.prototype, o.a);
F.prototype = oldProto;
for (var i = 0; i < 50; i++) s += make(i).a;
out.push(s, make(3) instanceof F);
function G(x) { this.x = x; }
function makeG(n) { return new G(n); }
for (var i = 0; i < 200; i++) makeG(i);
G.prototype = null;
out.push(Object.getPrototypeOf(makeG(1)) === Object.prototype);
console.log('construct IC: ' + out.join(' '));

out = [];
var other = $262.createRealm().global;
function P(x) { this.x = x; }
function mk(n) { return new P(n); }
var s = 0;
for (var i = 0; i < 300; i++) s += mk(i).x;
out.push('local ctor after realm: ' + s);
var Q = other.eval('(function Q(x) { this.q = x * 2; })');
function mkQ(n) { return new Q(n); }
s = 0;
for (var i = 0; i < 300; i++) s += mkQ(i).q;
out.push('foreign ctor: ' + s + ' ' + (Object.getPrototypeOf(mkQ(1)) === Q.prototype));
function add(a, b) { return a + b; }
function callAdd(n) { return add(n, 1); }
s = 0;
for (var i = 0; i < 300; i++) s += callAdd(i);
out.push('local call: ' + s);
var fadd = other.eval('(function fadd(a, b) { return [a + b] instanceof Array; })');
function callF(n) { return fadd(n, 1); }
var t = 0;
for (var i = 0; i < 300; i++) t += callF(i) ? 1 : 0;
out.push('foreign call result realm check: ' + t);
var env = { k: 'with-k' };
with (env) { var wf = function () { return k; }; }
function callW() { return wf(); }
var w = '';
for (var i = 0; i < 300; i++) w = callW();
out.push('with closure: ' + w);
class C { constructor() { this.c = 1; } }
function callC() { try { return C(); } catch (e) { return e.constructor.name; } }
var cc = '';
for (var i = 0; i < 300; i++) cc = callC();
out.push('class call: ' + cc);
function deep() { return function a() { return function b() { return function c() { return function d() { return function e() { return function f() { return function g() { return function h() { return function i2() { return function j(x) { this.j = x; return x + 1; }; }; }; }; }; }; }; }; }; }; }
var J = deep()()()()()()()()()();
function callJ(n) { return J(n); }
function newJ(n) { return new J(n).j; }
s = 0;
for (var i = 0; i < 300; i++) s += callJ(i) + newJ(i);
out.push('deeply nested closure: ' + s);
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_ic_hot_call_and_construct_sites_fall_back_correctly(js, golden, tier):
    """CATCHES: cached call/construct sites that keep using a stale constructor prototype after the constructor's shape changes or its prototype becomes a primitive, run a foreign-realm function or constructor with this realm's intrinsics, skip the with-scope lookup of a closure created inside `with`, or let a hot call site invoke a class constructor without `new`."""
    r = js(IC_HOT_SITES, *tier)
    assert out(r) == golden("ic_hot_sites")
    assert (r.returncode, r.stderr) == (0, b"")


# covers: interpreter.rs 5209, 6855-6862, 7021, 7035-7036, 7224-7225, 7328, 7351-7354
IC_COROUTINE_ERRORS = r"""const log = [];
const settled = [];
const settle = (label, p) => { const slot = settled.push(label + ': pending') - 1; return p.then(v => { settled[slot] = label + ': resolved ' + JSON.stringify(v); }, e => { settled[slot] = label + ': rejected ' + e.constructor.name + ': ' + e.message; }); };
// Parameter binding failures of async functions reject the returned promise instead of throwing.
async function destructObj({ a }) { return a; }
async function destructArr([x]) { return x; }
async function badDefault(a = (() => { throw new RangeError('default threw'); })()) { return a; }
async function okDefault(a = 'dflt', ...[r = 'rest-dflt']) { return a + '/' + r; }
const jobs = [];
let threw = 'no';
try {
  jobs.push(settle('destructure null', destructObj(null)));
  jobs.push(settle('destructure non-iterable', destructArr(1)));
  jobs.push(settle('throwing default', badDefault()));
  jobs.push(settle('defaults ok', okDefault()));
} catch (e) { threw = e.constructor.name; }
log.push('sync throw from async call: ' + threw);
// A promise whose `constructor` getter throws makes `await` throw at the await itself.
function poisoned(tag) {
  const p = Promise.resolve(tag);
  Object.defineProperty(p, 'constructor', { get() { throw new EvalError('constructor of ' + tag); } });
  return p;
}
async function awaitPoisoned() { try { await poisoned('fn'); return 'not reached'; } catch (e) { return 'caught ' + e.message; } }
jobs.push(settle('await poisoned in async fn', awaitPoisoned()));
async function* agAwait() { try { await poisoned('gen'); } catch (e) { yield 'gen caught ' + e.message; } yield 'after'; }
const ag1 = agAwait();
jobs.push(settle('async gen await poisoned', ag1.next()));
jobs.push(settle('async gen next', ag1.next()));
async function* agPlain() { yield 1; }
const ag2 = agPlain();
jobs.push(settle('return(poisoned) before start', ag2.return(poisoned('start'))));
const ag3 = agPlain();
jobs.push(settle('drain', ag3.next().then(() => ag3.next())));
jobs.push(settle('return(poisoned) when done', ag3.next().then(() => ag3.return(poisoned('done')))));
// A generator body with a top-level `using` disposes when the generator completes or returns.
const res = (name) => ({ [Symbol.dispose]() { log.push('dispose ' + name); } });
function* withUsing(name) { using r = res(name); yield name + ' 1'; yield name + ' 2'; }
const g1 = withUsing('g1');
log.push(JSON.stringify([...g1]));
const g2 = withUsing('g2');
log.push(JSON.stringify(g2.next()) + ' ' + JSON.stringify(g2.return('early')));
function* usingThrows() { using r = { [Symbol.dispose]() { throw new URIError('dispose failed'); } }; yield 1; }
const g3 = usingThrows();
g3.next();
try { g3.next(); } catch (e) { log.push('dispose error surfaces: ' + e.constructor.name + ': ' + e.message); }
// Sloppy duplicate parameters: only the last occurrence is mapped to arguments.
function dup(a, a) { arguments[0] = 'zero'; arguments[1] = 'one'; return a + ' ' + arguments[0] + ' ' + arguments.length; }
log.push('duplicate params: ' + dup('x', 'y'));
function dup3(a, b, a) { a = 'set'; return [arguments[0], arguments[1], arguments[2]].join(','); }
log.push('duplicate params, 3: ' + dup3(1, 2, 3));
Promise.all(jobs).then(() => console.log(log.concat(settled).join('\n')));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_ic_async_and_generator_error_plumbing(js, golden, tier):
    """CATCHES: async functions whose parameter-binding errors throw synchronously instead of rejecting, an `await` (in async functions and async generators) or an async generator return() that does not surface a throwing promise `constructor` getter as a rejection, generators whose top-level `using` is never disposed on completion, early return() or disposal failure, or sloppy duplicate parameters mapping the wrong arguments index."""
    r = js(IC_COROUTINE_ERRORS, *tier)
    assert out(r) == golden("ic_coroutine_errors")
    assert (r.returncode, r.stderr) == (0, b"")
