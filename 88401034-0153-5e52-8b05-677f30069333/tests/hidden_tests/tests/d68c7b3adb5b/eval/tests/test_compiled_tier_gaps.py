"""Rarely taken branches of the bytecode compiler, the bytecode VM and the template JIT.

Each program drives functions hot enough to be compiled (a loop compiles a function on its first
call, otherwise it tiers up after a handful of calls) and then feeds them the operand shapes,
receivers and syntax forms that the specialised paths must decline or bail on: odd property keys
in compound element updates, fused RegExp statements whose guards fail, dense destructuring and
spread fast paths whose preconditions are broken, constructs the compiler leaves to the
tree-walker, and so on. Every program runs on the default JIT, on `--tier=bytecode` and (except
the Richards rewrites, whose warm-ups are slow on the tree-walker) on `--tier=interp`, and all runs
must print the same golden output: an optimisation that changes a result, swallows an exception or
runs a side effect twice fails. The custom-iterator test also enables the documented opt-in
`LUMEN_ITERATOR_ENTRY_NATIVE` switch.
"""

import json

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
def test_compound_element_updates_with_exotic_keys(js, golden, tier):
    """CATCHES: compiled `o[k] += v`, `o[k]++` and `o[k]()` that skip ToPropertyKey for symbol, object, boolean and null keys, call a key's toString the wrong number of times, or read the base instead of throwing a TypeError when it is null or undefined."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 30; k++) r = f(k); return r; }
var sym = Symbol("s");
function addLocal(o, k) { o[k] += 1; return o[k]; }
var o1 = { [sym]: 1, "[object Object]": 5, "true": 1, "null": 2 };
hot(function () { return addLocal({ a: 1 }, "a"); });
out.push(addLocal(o1, sym), addLocal(o1, {}), addLocal(o1, true), addLocal(o1, null));
var keyObj = { toString: function () { out.push("toString"); return "a"; } };
out.push(addLocal({ a: 10 }, keyObj));
try { addLocal(null, {}); } catch (e) { out.push(e.constructor.name); }
try { addLocal(undefined, sym); } catch (e) { out.push(e.constructor.name); }
var holder = { inner: { [sym]: 3, x: 1 } };
function addNested(h, k) { h.inner[k] *= 2; return h.inner[k]; }
hot(function () { return addNested({ inner: { x: 1 } }, "x"); });
out.push(addNested(holder, sym), addNested(holder, keyObj));
try { addNested({ inner: null }, {}); } catch (e) { out.push(e.constructor.name); }
function incElem(o, k) { return o[k]++; }
hot(function () { return incElem([1], 0); });
out.push(incElem(o1, sym), incElem({ x: "5" }, "x"), incElem([1, 2], "1"), o1[sym]);
try { incElem(null, 0); } catch (e) { out.push(e.constructor.name); }
function callElem(o, k) { return o[k](); }
var arrF = [function () { return "a0"; }];
hot(function () { return callElem(arrF, 0); });
var protoArr = [];
Object.setPrototypeOf(protoArr, { 0: function () { return "proto0"; }, __proto__: Array.prototype });
out.push(callElem(protoArr, 0), callElem({ m: function () { return "m"; } }, "m"));
out.push(callElem({ [sym]: function () { return "sym"; } }, sym), callElem({ 1.5: function () { return "frac"; } }, 1.5));
try { callElem(null, 0); } catch (e) { out.push(e.constructor.name); }
try { callElem(undefined, "x"); } catch (e) { out.push(e.constructor.name); }
console.log(out.join("|"));
"""
    check(js, golden, "compound_element_updates_with_exotic_keys", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_regexp_statement_fusions_with_failing_guards(js, golden, tier):
    """CATCHES: a fused `strs[i].replace(/re/, "s")`, `strs[i].match(/re/)` or `/re/.exec(strs[i])` statement that keeps its fast path for strings, proxies, fractional or negative indices, holes, getters, non-string elements or patched String/RegExp methods, so RegExp.$1, getter side effects, patched-method calls or TypeErrors differ from the reference."""
    code = r"""
var out = [];
var strs;
function doReplace(start, n) { for (var i = start; i < n; i++) { strs[i].replace(/a(b)/, "X"); } return RegExp.$1; }
function doMatch(start, n) { for (var i = start; i < n; i++) { strs[i].match(/c(d)/); } return RegExp.$1; }
function doExec(start, n) { for (var i = start; i < n; i++) { /e(f)/.exec(strs[i]); } return RegExp.$1; }
function doExecConst(n) { for (var i = 0; i < n; i++) { /g(h)/.exec("gh"); } return RegExp.$1; }
function attempt(label, f) {
  try { out.push(label + "=" + f()); } catch (e) { out.push(label + "!" + e.constructor.name); }
}
function all(label, s, start, n) {
  strs = s;
  attempt(label + ".r", function () { return doReplace(start, n); });
  attempt(label + ".m", function () { return doMatch(start, n); });
  attempt(label + ".e", function () { return doExec(start, n); });
}
all("ok", ["ab", "cd", "ef"], 0, 3);
all("str", "abc", 0, 1);
all("proxy", new Proxy(["ab", "cd", "ef"], {}), 0, 3);
all("frac", ["ab", "cd", "ef"], 0.5, 1);
all("neg", ["ab", "cd", "ef"], -1, 0);
all("strIndex", ["ab", "cd", "ef"], "0", 1);
all("plain", { 0: "ab", 1: "cd", 2: "ef", length: 3 }, 0, 3);
all("hole", [, "ab"], 0, 2);
var acc = ["ab", "cd"];
Object.defineProperty(acc, 0, { get: function () { out.push("get0"); return "ab"; } });
all("acc", acc, 0, 1);
all("obj", [{ replace: function () { out.push("objR"); }, match: function () { out.push("objM"); } }], 0, 1);
all("num", [5], 0, 1);
strs = ["ab", "cd", "ef"];
var savedReplace = String.prototype.replace;
String.prototype.replace = function () { out.push("patchedR"); return ""; };
attempt("patch.r", function () { return doReplace(0, 1); });
String.prototype.replace = savedReplace;
var savedMatch = String.prototype.match;
String.prototype.match = function () { out.push("patchedM"); return null; };
attempt("patch.m", function () { return doMatch(0, 1); });
String.prototype.match = savedMatch;
var savedExec = RegExp.prototype.exec;
RegExp.prototype.exec = function (s) { out.push("patchedE"); return savedExec.call(this, s); };
attempt("patch.e", function () { return doExec(0, 1); });
attempt("patch.c", function () { return doExecConst(1); });
RegExp.prototype.exec = savedExec;
attempt("const", function () { return doExecConst(3); });
function numConst(n) { for (var i = 0; i < n; i++) { /5/.exec(5); } return RegExp.lastMatch; }
attempt("numConst", function () { return numConst(2); });
function testLit(n) { for (var i = 0; i < n; i++) { /c(d)/.test(strs[i]); } return RegExp.$1; }
attempt("testLit", function () { return testLit(2); });
function replNum(n) { for (var i = 0; i < n; i++) { strs[i].replace(/(a)/, 5); } return RegExp.$1; }
attempt("replNum", function () { return replNum(1); });
function replAll(n) { for (var i = 0; i < n; i++) { strs[i].replaceAll(/(c)/g, "x"); } return RegExp.$1; }
attempt("replAll", function () { return replAll(2); });
function search(n) { for (var i = 0; i < n; i++) { strs[i].search(/(e)/); } return RegExp.$1; }
attempt("search", function () { return search(3); });
function undeclR(n) { for (var i = 0; i < n; i++) { missingArr[i].replace(/a/, "b"); } }
function undeclM(n) { for (var i = 0; i < n; i++) { missingArr[i].match(/a/); } }
function undeclE(n) { for (var i = 0; i < n; i++) { /a/.exec(missingArr[i]); } }
attempt("undeclR", function () { return undeclR(1); });
attempt("undeclM", function () { return undeclM(1); });
attempt("undeclE", function () { return undeclE(1); });
console.log(out.join("\n"));
"""
    check(js, golden, "regexp_statement_fusions_with_failing_guards", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_regexp_exec_loop_batching_guards(js, golden, tier):
    """CATCHES: a batched `for (i = s; i < N; i++) re.exec(strs[i]);` loop that runs its fast path when the start index or limit is not a valid integer, the receiver is not a RegExp or has its own exec, lastIndex is odd, elements are holes, getters or non-strings, exec is an accessor or not callable, or a global name is undeclared, so the final index, RegExp.$1, side effects or thrown errors differ."""
    code = r"""
var out = [];
function attempt(label, f) {
  try { out.push(label + "=" + f()); } catch (e) { out.push(label + "!" + e.constructor.name); }
}
var strs = ["xz", "yz", "zz"], re = /(z)/;
function doLoop(start) { var i; for (i = start; i < 3; i++) re.exec(strs[i]); return i + ":" + RegExp.$1; }
attempt("loop", function () { return doLoop(0); });
attempt("start5", function () { return doLoop(5); });
attempt("frac", function () { return doLoop(0.5); });
attempt("neg", function () { return doLoop(-1); });
attempt("str", function () { return doLoop("1"); });
attempt("notre", function () { re = { exec: function (s) { out.push("fake:" + s); } }; return doLoop(1); });
attempt("ownexec", function () { re = /(z)/; re.exec = function (s) { out.push("own:" + s); }; return doLoop(2); });
attempt("li", function () { re = /(z)/g; re.lastIndex = "x"; return doLoop(1); });
attempt("li2", function () { re = /(z)/; Object.defineProperty(re, "lastIndex", { writable: false, value: 0 }); return doLoop(1); });
attempt("hole", function () { re = /(z)/; strs = [, "z", "z"]; return doLoop(0); });
attempt("nonstr", function () { strs = [1, 2, 3]; return doLoop(0); });
attempt("acc", function () { strs = ["z", "z", "z"]; Object.defineProperty(strs, 1, { get: function () { out.push("lg"); return "z"; } }); return doLoop(0); });
attempt("plain", function () { strs = { 0: "z", 1: "z", 2: "z" }; return doLoop(0); });
attempt("proxy", function () { strs = new Proxy(["z", "z", "z"], {}); return doLoop(0); });
attempt("notobj", function () { strs = "zzz"; return doLoop(0); });
attempt("undef", function () { strs = undefined; return doLoop(0); });
strs = ["az", "bz", "cz"];
function undeclLoopRe() { var i; for (i = 0; i < 2; i++) missingRe.exec(strs[i]); }
function undeclLoopArr() { var i; for (i = 0; i < 2; i++) re.exec(missingArr[i]); }
attempt("undeclRe", undeclLoopRe);
attempt("undeclArr", undeclLoopArr);
function loopTest() { var i; for (i = 0; i < 3; i++) re.test(strs[i]); return i; }
attempt("test", loopTest);
function loopStrLimit() { var i; for (i = 0; i < "3"; i++) re.exec(strs[i]); return i; }
attempt("strLimit", loopStrLimit);
function loopFracLimit() { var i; for (i = 0; i < 2.5; i++) re.exec(strs[i]); return i; }
attempt("fracLimit", loopFracLimit);
function loopNegLimit() { var i; for (i = -3; i < -1; i++) re.exec(strs[i]); return i; }
attempt("negLimit", loopNegLimit);
var savedExec = RegExp.prototype.exec;
Object.defineProperty(RegExp.prototype, "exec", { get: function () { out.push("execGetter"); return savedExec; }, configurable: true });
attempt("getter", function () { re = /(z)/; return doLoop(1); });
Object.defineProperty(RegExp.prototype, "exec", { value: 42, writable: true, configurable: true });
attempt("nonFn", function () { return doLoop(1); });
Object.defineProperty(RegExp.prototype, "exec", { value: savedExec, writable: true, configurable: true });
attempt("restored", function () { strs = ["z1", "z2", "z3"]; re = /z(\d)/; return doLoop(0); });
console.log(out.join("\n"));
"""
    check(js, golden, "regexp_exec_loop_batching_guards", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_array_destructuring_fast_path_preconditions(js, golden, tier):
    """CATCHES: scalar-replaced `var [x, y] = a` that keeps reading elements directly when the pattern is longer than the fast path allows, the array has its own iterator, the iterator prototype has a return method, an element is a getter, the prototype chain contains a Proxy, a getter, or is very deep, so values, getter calls or iterator closing differ."""
    code = r"""
var out = [];
function many(a) { var [a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, b0, b1, b2, b3, b4, b5, b6] = a; return [a0, a9, b6].join("-"); }
var big = []; for (var k = 0; k < 20; k++) big.push(k * 3);
var r1; for (var k = 0; k < 30; k++) r1 = many(big);
out.push(r1, many([1, 2]));
function pair(a) { var [x, y] = a; return x + "," + y; }
function one(a) { var [x] = a; return String(x); }
for (var k = 0; k < 30; k++) { pair([1, 2]); one([k]); }
var own = [1, 2]; own[Symbol.iterator] = function* () { yield "o1"; yield "o2"; yield "o3"; };
out.push(pair(own), one(own));
var proto = Object.getPrototypeOf([].values());
var closed = 0;
proto.return = function () { closed++; return {}; };
out.push(pair([5, 6, 7]), one([8, 9]), pair([1]), closed);
delete proto.return;
var acc = [1, 2]; Object.defineProperty(acc, 1, { get: function () { out.push("getter"); return "g"; } });
out.push(pair(acc));
var px = [3, 4]; Object.setPrototypeOf(px, new Proxy(Array.prototype, {}));
out.push(pair(px));
var orig = Array.prototype[Symbol.iterator];
Object.defineProperty(Array.prototype, Symbol.iterator, { get: function () { out.push("iterGet"); return orig; }, configurable: true });
out.push(pair([8, 9]));
Object.defineProperty(Array.prototype, Symbol.iterator, { value: orig, writable: true, configurable: true });
var deep = [10, 11]; var p = Array.prototype;
for (var d = 0; d < 9; d++) p = Object.create(p);
Object.setPrototypeOf(deep, p);
out.push(pair(deep), pair([12, 13]), pair([, 14]), one([]));
console.log(out.join("|"));
"""
    check(js, golden, "array_destructuring_fast_path_preconditions", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_spread_calls_and_array_iteration_fast_path_preconditions(js, golden, tier):
    """CATCHES: a compiled `f(...a)` or `for (x of a)` fast path that copies elements directly from long arrays, arrays with getters, holes, Proxy or deep prototypes, strings, Sets, keys()/entries() iterators, iterators with extra accessors or array-likes, instead of following the iterator protocol, so spread arguments or loop results differ."""
    code = r"""
var out = [];
function sum3(a, b, c) { return a + "/" + b + "/" + c; }
function sp(a) { return sum3(...a); }
for (var k = 0; k < 30; k++) sp([1, 2, 3]);
var long = []; for (var k = 0; k < 20; k++) long.push(k);
var acc = [1, 2]; Object.defineProperty(acc, 1, { get: function () { out.push("getter"); return "g"; } });
var px = [3, 4]; Object.setPrototypeOf(px, new Proxy(Array.prototype, {}));
var deep = [10, 11]; var p = Array.prototype;
for (var d = 0; d < 9; d++) p = Object.create(p);
Object.setPrototypeOf(deep, p);
out.push(sp(long), sp(acc), sp([1, , 3]), sp(px), sp(deep), sp("abc"), sp(new Set([4, 5, 6])));
function scanCap(a) { var s = "", n = 0; for (var x of a) { s += x; if (++n === 4) break; } return s; }
for (var k = 0; k < 30; k++) scanCap([1, 2, 3]);
function keysOf(a) { var s = ""; for (var k of a.keys()) s += k; for (var e of a.entries()) s += "[" + e + "]"; return s; }
for (var k = 0; k < 30; k++) keysOf([7, 8]);
out.push(keysOf([7, 8, 9]));
var gi = [4, 5].values(); Object.defineProperty(gi, "extra", { get: function () { return 1; } });
out.push(scanCap({ [Symbol.iterator]: function () { return gi; } }));
var arrLike = { length: 2, 0: "a", 1: "b" };
out.push(scanCap({ [Symbol.iterator]: function () { return Array.prototype.values.call(arrLike); } }));
out.push(scanCap([1, , 3]), scanCap(long), scanCap(acc));
console.log(out.join("|"));
"""
    check(js, golden, "spread_calls_and_array_iteration_fast_path_preconditions", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_element_stores_whose_operands_assign_and_destructuring_stores(js, golden, tier):
    """CATCHES: a fused element store that reads the base local before an assignment inside the key or value expression runs, or compiled `var` destructuring that stores captured names, rest, defaults, computed or quoted keys and member targets incorrectly."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function fusedStores(a, i) {
  var t, o = { p: 0 }, q;
  a[i] = (t = i * 2); a[i + 1] = (o.p = t + 1); a[i + 2] = [t, , o.p];
  a[i + 3] = ([q] = [t + 3], q); a[i + 4] = (o.p++, o.p);
  return a.length + ":" + String(a[i + 2]) + ":" + a[i + 3] + ":" + a[i + 4];
}
out.push(hot(function (k) { return fusedStores([], k); }));
function rebase(a) { var b = a; b[(b = [7, 8], 0)] = 5; return a.join() + "/" + b.join(); }
out.push(hot(function () { return rebase([1, 2]); }));
function capVar(o) { var { a, b } = o; var [c, d] = [a, b]; var get = function () { return a + b + c + d; }; return get(); }
out.push(hot(function (k) { return capVar({ a: k, b: 1 }); }));
function patRest(o) { var { a, ...r } = o; return a + Object.keys(r).join(""); }
out.push(hot(function (k) { return patRest({ a: k, x: 1, y: 2 }); }));
function patDefault(o) { var { a = 5, b } = o; return a + b; }
out.push(hot(function (k) { return patDefault({ b: k }); }));
function patComputed(o, k) { var { [k]: v, "q-r": w } = o; return v + w; }
out.push(hot(function (k) { return patComputed({ z: k, "q-r": 1 }, "z"); }));
function patMember(arr) { var o = {}; [o.x, o.y] = arr; ({ a: o.z } = { a: 3 }); return o.x + o.y + o.z; }
out.push(hot(function (k) { return patMember([k, 2]); }));
function delForms(o) { var r1 = delete o?.p; var r2 = delete o.q; return r1 + ":" + r2 + ":" + ("p" in o); }
out.push(hot(function () { return delForms({ p: 1, q: 2 }); }));
function optCalls(o, f) { return [f?.(1), o.m?.(2), o?.m(3), o.n?.(4), o?.["m"]?.(5), o.m?.(...[6])].join(","); }
out.push(hot(function () { return optCalls({ m: function (x) { return x * 10; } }, function (x) { return x; }); }));
console.log(out.join("\n"));
"""
    check(js, golden, "element_stores_whose_operands_assign_and_destructuring_stores", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_loop_exits_across_for_of_try_and_labels(js, golden, tier):
    """CATCHES: compiled control flow that leaks or skips iterator closing and try handlers when return, break or continue leave nested for-of loops, try blocks inside for-of, do-while loops or labelled blocks, or that binds for-of/for-in targets that are pre-declared, captured, const or destructuring patterns incorrectly."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function tracked(xs, log) {
  return { [Symbol.iterator]: function () { var i = 0; return { next: function () { return i < xs.length ? { value: xs[i++], done: false } : { done: true }; }, return: function () { log.push("close" + xs[0]); return {}; } }; } };
}
function nestedReturn(xs, ys) { for (var x of xs) for (var y of ys) if (x * y > 2) return x + "*" + y; return "none"; }
var log = [];
out.push(hot(function () { log.length = 0; return nestedReturn(tracked([1, 2, 3], log), tracked([1, 2], log)); }), log.join());
function tryInForOf(xs) { for (var x of xs) { try { if (x > 1) return "ret" + x; } catch (e) { return "caught"; } } return "end"; }
out.push(hot(function () { log.length = 0; return tryInForOf(tracked([1, 2, 3], log)); }), log.join());
function breakOuter(xs) { var s = ""; outer: for (var x of xs) { for (var y of xs) { if (y > x) continue outer; if (x > 2) break outer; s += x + "" + y; } } return s; }
out.push(hot(function () { return breakOuter([1, 2, 3]); }));
function doBreak(n) { var i = 0; do { if (i === n) break; i++; } while (i < 10); return i; }
out.push(hot(function () { return doBreak(4); }));
function labBlock(x) { var r = "a"; blk: { if (x) break blk; r = "b"; } return r; }
out.push(hot(function (k) { return labBlock(k & 1) + labBlock(0); }));
function forOfLocal(xs) { var x, s = 0; for (x of xs) s += x; let y; for (y of xs) s += y; return s + ":" + x + ":" + y; }
out.push(hot(function () { return forOfLocal([1, 2, 3]); }));
function forOfCaptured(xs) { var x, fs = []; for (x of xs) fs.push(function () { return x; }); return fs.map(function (f) { return f(); }).join(""); }
out.push(hot(function () { return forOfCaptured([1, 2, 3]); }));
function forOfConst(xs) { const c = 0; try { for (c of xs); } catch (e) { return e.constructor.name + c; } return "no"; }
out.push(hot(function () { return forOfConst([1]); }));
function forOfCapturedConst(xs) { const c = 0; var get = function () { return c; }; try { for (c of xs); } catch (e) { return e.constructor.name + get(); } return "no"; }
out.push(hot(function () { return forOfCapturedConst([1]); }));
function forInDestr(o) { var s = ""; for (var [a, b] in o) s += a + b; for (let [c] of ["xy"]) s += c; return s; }
out.push(hot(function () { return forInDestr({ ab: 1, cd: 2 }); }));
function forDestrInit(n) { var s = 0; for (var [a, b] = [1, 2]; a < n; a++) s += a + b; for (let [c, d] = [0, 1]; c < 2; c++) s += d; return s; }
out.push(hot(function () { return forDestrInit(4); }));
function forInControl(o) { var s = ""; for (var k in o) { if (k === "b") continue; if (k === "d") break; s += k; } for (let j in o) { if (j > "b") break; s += j.toUpperCase(); } return s; }
out.push(hot(function () { return forInControl({ a: 1, b: 2, c: 3, d: 4, e: 5 }); }));
function forInCaptured(o) { var fs = []; for (let k in o) fs.push(function () { return k; }); return fs.map(function (f) { return f(); }).join(""); }
out.push(hot(function () { return forInCaptured({ p: 1, q: 2 }); }));
console.log(out.join("\n"));
"""
    check(js, golden, "loop_exits_across_for_of_try_and_labels", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_const_logical_and_parenthesised_assignments(js, golden, tier):
    """CATCHES: compiled assignments, compound assignments and updates to local or captured const bindings that do not throw TypeError (or corrupt the binding), and logical assignment operators on locals and properties that evaluate or store when they must short-circuit."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function constAssign() { const c = 1; try { c = 2; } catch (e) { return e.constructor.name + c; } return "no"; }
function constAssignExpr() { const c = 1; try { return (c = 2); } catch (e) { return e.constructor.name + c; } }
function constCaptured() { const c = 1; var f = function () { return c; }; try { c += 2; } catch (e) { return e.constructor.name + f(); } return "no"; }
function constCapturedExpr() { const c = 1; var f = function () { return c; }; try { return (c = 2); } catch (e) { return e.constructor.name + f(); } }
function constUpdate() { const c = 1; try { c++; } catch (e) { return e.constructor.name + c; } return "no"; }
function constCapturedUpdate() { const c = 5; var f = function () { return c; }; try { return --c; } catch (e) { return e.constructor.name + f(); } }
out.push(hot(constAssign), hot(constAssignExpr), hot(constCaptured), hot(constCapturedExpr), hot(constUpdate), hot(constCapturedUpdate));
function parenUpdate(x) { ++(x); (x)--; (x)++; var o = { v: 1 }; (o.v)++; ++(o["v"]); return x + ":" + o.v; }
out.push(hot(function (k) { return parenUpdate(k); }));
var calls = 0;
function rhs(v) { calls++; return v; }
function logicalAssign(o) { var a = 0, b = null, c = 1, d = 2; a ||= rhs(5); b ??= rhs(6); c &&= rhs(7); d ||= rhs(99); o.x ||= rhs(8); o.y ??= rhs(9); o.z &&= rhs(10); o.w ??= rhs(11); return [a, b, c, d, o.x, o.y, o.z, o.w].join(","); }
out.push(hot(function () { return logicalAssign({ z: 1, w: 0 }); }), calls);
function logicalAssignExpr(o) { var a; return (a ||= 3) + (o.q ??= 4) + (o.r &&= 5); }
out.push(hot(function () { return logicalAssignExpr({ r: 1 }); }));
console.log(out.join("\n"));
"""
    check(js, golden, "const_logical_and_parenthesised_assignments", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_classes_super_private_and_eval_in_hot_code(js, golden, tier):
    """CATCHES: compiled code that mishandles derived-class constructors calling super(), super property reads and calls, private field updates and `#x in obj` checks, classes with static blocks and private fields defined inside hot functions, or a direct eval that must see (and define) the caller's locals."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
class Base { constructor(v) { this.v = v; } get dbl() { return this.v * 2; } m() { return "base"; } }
class Derived extends Base { constructor(v) { super(v + 1); this.w = super.m(); } m() { return "d" + super.m(); } get dbl() { return super.dbl + 1; } }
out.push(hot(function (k) { var d = new Derived(k); return d.v + d.w + d.m() + d.dbl; }));
class Priv { #x = 1; static #count = 0; bump() { this.#x++; ++this.#x; this.#x += 2; Priv.#count++; return this.#x; } has(o) { return #x in o; } static count() { return Priv.#count; } }
out.push(hot(function () { var p = new Priv(); return p.bump() + ":" + p.has(p) + p.has({}) + ":" + Priv.count(); }));
function makeClass(n) { class Local { static s = n; #p = n * 2; get p() { return this.#p; } static { Local.t = Local.s + 1; } } return new Local().p + Local.t; }
out.push(hot(function (k) { return makeClass(k); }));
function nestedPrivIn(o) { class C { #f; static check(x) { return #f in x; } } return C.check(o) + ":" + C.check(new C()); }
out.push(hot(function () { return nestedPrivIn({}); }));
function directEval(x) { var y = 2; return eval("x + y"); }
out.push(hot(function (k) { return directEval(k); }));
function evalDefines(x) { eval("var z = x * 3"); return z; }
out.push(hot(function (k) { return evalDefines(k); }));
function dynImport() { var p = function () { return import("./nope.mjs"); }; return typeof p; }
out.push(hot(dynImport));
console.log(out.join("\n"));
"""
    check(js, golden, "classes_super_private_and_eval_in_hot_code", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_native_call_intrinsics_on_their_slow_paths(js, golden, tier):
    """CATCHES: JIT intrinsics for string concatenation, slice, charAt, Function#apply/call, Object.hasOwn and Array push/pop that skip the RangeError for over-long strings, mis-normalise infinite or NaN indices, take the dense path for array-likes with odd lengths, getters, holes or mapped arguments, or ignore frozen arrays and non-array receivers."""
    code = r"""
var out = [];
function cat(a, b) { var r; for (var i = 0; i < 1; i++) r = a + b; return r.length; }
var big = "x".repeat(33554432);
out.push(cat("ab", "cd"));
try { out.push(cat(big + "y", big)); } catch (e) { out.push(e.constructor.name + ":" + e.message); }
function catHot(a, b) { return (a + b).length; }
for (var k = 0; k < 20; k++) catHot("p", "q");
try { out.push(catHot(big, big + "z")); } catch (e) { out.push(e.constructor.name + ":" + e.message); }
function sl(s, a, b) { var r = ""; for (var i = 0; i < 2; i++) r = s.slice(a, b); return r; }
for (var k = 0; k < 20; k++) sl("hello", 1, 3);
out.push(sl("hello", -Infinity, Infinity), sl("hello", Infinity, 2), sl("hello", NaN, -2), sl("hello", -3, -Infinity), sl("hello", 1.7, 4.2));
function ch(s, i) { var r; for (var k = 0; k < 2; k++) r = s.charAt(i); return r; }
for (var k = 0; k < 20; k++) ch("abc", 1);
out.push(ch("abc", NaN), ch("abc", -1), ch("abc", 7), ch("abc", Infinity), ch("abc", 1.9));
function target(a, b, c) { return [a, b, c].join("+"); }
function ap(t, list) { var r; for (var k = 0; k < 2; k++) r = target.apply(t, list); return r; }
for (var k = 0; k < 20; k++) ap(null, [1, 2, 3]);
function sloppyArgs(a, b) { return ap(null, arguments); }
out.push(ap(null, { length: 2, 0: "x", 1: "y" }), ap(null, { length: "2", 0: "s", 1: "t" }), ap(null, { get length() { return 1; }, 0: "g" }), sloppyArgs("m", "n"));
var accList = [1, 2]; Object.defineProperty(accList, 0, { get: function () { return "acc"; } });
out.push(ap(null, accList), ap(null, [1, , 3]), ap(null, { length: -1 }), ap(null, { length: 1.5, 0: "f" }));
function ownHas(o, k) { var r; for (var i = 0; i < 2; i++) r = Object.hasOwn(o, k); return r; }
for (var k = 0; k < 20; k++) ownHas({ a: 1 }, "a");
out.push(ownHas({ a: 1 }, "b"), ownHas([1], "0"), ownHas({ 1: 2 }, 1));
function pushPop(a, v) { var r; for (var i = 0; i < 1; i++) { a.push(v); r = a.pop(); } return r + ":" + a.length; }
for (var k = 0; k < 20; k++) pushPop([1], 2);
try { out.push(pushPop(Object.freeze([1, 2]), 3)); } catch (e) { out.push(e.constructor.name); }
var al = { length: 1, 0: "z", push: Array.prototype.push, pop: Array.prototype.pop };
out.push(pushPop(al, "w"), pushPop([], undefined));
var fixedLen = []; Object.defineProperty(fixedLen, "length", { writable: false, value: 0 });
try { out.push(pushPop(fixedLen, 1)); } catch (e) { out.push(e.constructor.name); }
function callFwd(f, t, x) { var r; for (var i = 0; i < 2; i++) r = f.call(t, x); return r; }
function self(x) { return this === undefined ? "u" + x : typeof this + x; }
for (var k = 0; k < 20; k++) callFwd(self, {}, 1);
out.push(callFwd(self, 5, 2), callFwd(Math.max, null, 9), callFwd(new Proxy(self, {}), null, 3), callFwd(self.bind("b"), null, 4));
console.log(out.join("|"));
"""
    check(js, golden, "native_call_intrinsics_on_their_slow_paths", code, tier)


def _many_locals_program():
    # ~200 locals make the compiled body large enough that its loop branches need far jumps.
    decls = ", ".join(f"v{i} = {i}" for i in range(195))
    return (
        "var out = [];\n"
        "function manyLocals(n) {\n"
        f"  var {decls};\n"
        "  var s = 0;\n"
        "  for (var i = 0; i < n; i++) { if (v194 > i) s = s + v193; else s = s - v1; }\n"
        "  return s + v0 + v130;\n"
        "}\n"
        "out.push(manyLocals(5), manyLocals(250));\n"
    )


@pytest.mark.parametrize("tier", TIERS)
def test_branchy_numeric_loops_beyond_region_limits(js, golden, tier):
    """CATCHES: numeric loop-region compilation that mis-handles functions with ~200 locals (far branches in very large compiled code), more locals, receivers, global or property inputs than a region supports, a reassigned receiver, deep operand stacks, mid-block comparisons, or value-producing property stores and compound element updates inside loops."""
    code = _many_locals_program() + r"""
function nineLocals(n) {
  var a = 0, b = 0, c = 0, d = 0, e = 0, f = 0, g = 0, h = 0, m = 0;
  for (var i = 0; i < n; i++) { if (i < 3) { a = a + 1; b = b + 2; } else { c = c + 3; d = d + 4; } e = e + i; f = f + 1; g = g - 1; h = h + 2; m = m + a; }
  return [a, b, c, d, e, f, g, h, m].join(",");
}
out.push(nineLocals(6));
function fiveRecv(p, q, r, s, t) {
  var acc = 0;
  for (var i = 0; i < 3; i++) { if (p[i] < q[i]) acc = acc + r[i]; else acc = acc + s[i] - t[i]; }
  return acc;
}
out.push(fiveRecv([1, 5, 1], [2, 2, 2], [10, 20, 30], [4, 5, 6], [1, 1, 1]));
function recvLocal(a) {
  var s = 0;
  for (var i = 0; i < 3; i++) { if (i < 1) s = s + a[i]; else { s = s - a[i]; a = [7, 8, 9]; } }
  return s;
}
out.push(recvLocal([1, 2, 3]));
function deepStack(n) {
  var x = 1, s = 0;
  for (var i = 0; i < n; i++) { if (i < 2) s = x + (x + (x + (x + (x + (x + (x + (x + (x + (x + s))))))))); else s = s - 1; }
  return s;
}
out.push(deepStack(4));
var G1 = 1, G2 = 2, G3 = 3, G4 = 4, G5 = 5, G6 = 6, G7 = 7;
function manyInputs(n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (i < 2) s = s + G1 + G2 + G3; else s = s + G4 + G5 + G6 + G7; }
  return s;
}
out.push(manyInputs(4));
function manyProps(o, n) {
  var s = 0;
  for (var i = 0; i < n; i++) { if (i < 2) s = s + o.a + o.b + o.c; else s = s + o.d + o.e + o.f + o.g; }
  return s;
}
out.push(manyProps({ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 }, 4));
function cmpMid(n) {
  var s = 0, t = 0;
  for (var i = 0; i < n; i++) { t = (i < 2) + 1; if (t > 1) s = s + 1; else s = s + 3; }
  return s;
}
out.push(cmpMid(5));
function mixedSet(objs) {
  var s = 0, v;
  for (var i = 0; i < objs.length; i++) { v = (objs[i].p = i * 2); s = s + v + objs[i].q; }
  return s + ":" + objs[2].p;
}
out.push(mixedSet([{ p: 0, q: 1 }, { p: 0, q: 2 }, { p: 0, q: 3 }]));
function mixedDup2(a, o) {
  for (var i = 0; i < a.length; i++) { a[i] += o.k; o.k += 1; }
  return a.join() + ":" + o.k;
}
out.push(mixedDup2([1, 2, 3], { k: 10 }), mixedDup2([0.5, "s"], { k: 1 }));
function cmpValue(n) { var t = 0, c = 0; for (var i = 0; i < n; i++) { t = i < 5; c = c + t; } return c; }
out.push(cmpValue(10), cmpValue(3));
function bitConst(n) { var x = 5, y = 0; for (var i = 0; i < n; i++) { y = (x & 4294967295) + (x | 2147483648) + (x ^ 1.5) + (x >>> 0) + (y & -1); } return y; }
out.push(bitConst(3));
console.log(out.join("|"));
"""
    check(js, golden, "branchy_numeric_loops_beyond_region_limits", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_compiled_writes_that_miss_their_fast_paths(js, golden, tier):
    """CATCHES: compiled code that mishandles a `for (var p ...)` head re-declaring a passed parameter, `++`/`--` on string or boolean locals, `this.x` reads and writes with an undefined receiver, value-producing property and element stores on frozen, read-only, setter-backed or odd-index targets, `a[i]++` through accessors or frozen arrays, and calls through accessor-valued globals."""
    code = r"""
"use strict";
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function resetParam(n, m) { var s = ""; for (var n = 0; n < 3; n++) s += n; for (var m of ["a", "b"]) s += m; return s + n; }
out.push(hot(function (k) { return resetParam(k, k); }), resetParam(), resetParam(1, 2, 3));
async function resetAsync(n) { var s = ""; for (var n = 0; n < 2; n++) s += n; await null; return s + n; }
function strUpd(s) { var a = s, b = s; var r = ++a; var q = b--; return r + ":" + q + ":" + a + ":" + b; }
out.push(hot(function () { return strUpd("5"); }), strUpd("x"), strUpd(true));
function readThis() { return this.x; }
function writeThis(v) { return (this.y = v); }
var objT = { x: 1, y: 0 };
out.push(hot(function () { return readThis.call(objT) + writeThis.call(objT, 2); }));
try { readThis(); } catch (e) { out.push("rt:" + e.constructor.name); }
try { writeThis(1); } catch (e) { out.push("wt:" + e.constructor.name); }
function setVal(o, v) { return (o.p = v); }
hot(function (k) { return setVal({}, k); });
try { setVal(Object.freeze({ p: 1 }), 2); } catch (e) { out.push("sv:" + e.constructor.name); }
try { setVal({ set p(v) { throw new Error("setter"); } }, 2); } catch (e) { out.push("sv:" + e.message); }
try { setVal(null, 2); } catch (e) { out.push("sv:" + e.constructor.name); }
function setElemVal(h, i, v) { return (h.a[i] = v); }
hot(function (k) { return setElemVal({ a: [0, 0] }, 1, k); });
var ro = [1, 2]; Object.defineProperty(ro, 0, { writable: false });
try { out.push(setElemVal({ a: ro }, 0, 9)); } catch (e) { out.push("se:" + e.constructor.name + ro[0]); }
var sa = []; Object.defineProperty(sa, 0, { set: function (v) { out.push("setter" + v); }, configurable: true });
out.push(setElemVal({ a: sa }, 0, 7), setElemVal({ a: {} }, 1.5, "f"), setElemVal({ a: [] }, -1, "neg"), setElemVal({ a: [] }, 4294967295, "max"));
function updElem(h, i) { h.a[i]++; return h.a[i]; }
hot(function () { return updElem({ a: [1, 2] }, 0); });
try { updElem({ a: Object.freeze([1]) }, 0); } catch (e) { out.push("ue:" + e.constructor.name); }
var ga = [5]; Object.defineProperty(ga, 0, { get: function () { return 41; }, set: function (v) { out.push("gs" + v); } });
out.push(updElem({ a: ga }, 0));
function updLocalElem(a, i) { a[i]++; return a[i]; }
hot(function () { return updLocalElem([1, 2], 0); });
try { updLocalElem(Object.freeze([1]), 0); } catch (e) { out.push("ule:" + e.constructor.name); }
Object.defineProperty(globalThis, "viaGetter", { get: function () { return function () { return "got"; }; }, configurable: true });
function callGetterGlobal() { return viaGetter(); }
out.push(hot(callGetterGlobal));
resetAsync(7).then(function (v) { out.push("async:" + v); console.log(out.join("\n")); });
"""
    check(js, golden, "compiled_writes_that_miss_their_fast_paths", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_collection_call_intrinsics_with_foreign_receivers(js, golden, tier):
    """CATCHES: JIT Map#set/Set#add/Map#get/Map#has/Set#has fast paths that skip the brand check when the builtin is borrowed by a plain object or a WeakMap, mishandle subclass instances, or normalise NaN, -0, BigInt, string and object keys differently from SameValueZero."""
    code = r"""
var out = [];
function fill(m, s, n) { for (var i = 0; i < n; i++) { m.set(i, i * 2); s.add("k" + i); } return m.size + s.size; }
function look(m, s, k) { var r = ""; for (var i = 0; i < 2; i++) r = m.get(k) + ":" + m.has(k) + ":" + s.has("k" + k); return r; }
out.push(fill(new Map(), new Set(), 5), look(new Map([[1, "one"]]), new Set(["k1"]), 1));
var fakeMap = { set: Map.prototype.set, get: Map.prototype.get, has: Map.prototype.has };
var fakeSet = { add: Set.prototype.add, has: Set.prototype.has };
try { fill(fakeMap, new Set(), 1); } catch (e) { out.push("fm:" + e.constructor.name); }
try { fill(new Map(), fakeSet, 1); } catch (e) { out.push("fs:" + e.constructor.name); }
try { look(fakeMap, new Set(), 1); } catch (e) { out.push("lm:" + e.constructor.name); }
try { look(new Map(), fakeSet, 1); } catch (e) { out.push("ls:" + e.constructor.name); }
var wm = new WeakMap(); wm.set = Map.prototype.set;
try { fill(wm, new Set(), 1); } catch (e) { out.push("wm:" + e.constructor.name); }
class MyMap extends Map { }
class MySet extends Set { }
out.push(fill(new MyMap(), new MySet(), 3), look(new MyMap([[2, "two"]]), new MySet(["k2"]), 2));
var objKey = {};
function setGetKinds(m) { var r = []; for (var i = 0; i < 1; i++) { m.set(objKey, "o"); m.set(NaN, "n"); m.set(-0, "z"); m.set("1", "s"); m.set(1, "i"); m.set(1n, "b"); r.push(m.get(objKey), m.get(NaN), m.get(0), m.get("1"), m.get(1), m.get(1n), m.has(undefined), m.size); } return r.join(","); }
var keyed = new Map();
out.push(setGetKinds(keyed), setGetKinds(keyed), setGetKinds(new Map()), [...keyed.keys()].map(String).join(" "));
console.log(out.join("|"));
"""
    check(js, golden, "collection_call_intrinsics_with_foreign_receivers", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_forwarded_initializers_with_unrecognised_bodies(js, golden, tier):
    """CATCHES: the constructor-forwarding fast path for `this.initialize.apply(this, arguments)` that accepts initialize bodies it cannot model (too many fields, non-parameter or duplicated sources, cross-wired defaults, arguments use, for-var resets, captured parameters, explicit return, computed tails) and so stores the wrong field values or omits side effects."""
    code = r"""
var out = [];
var Class = { create: function () { return function () { this.initialize.apply(this, arguments); }; } };
function build(init) { var K = Class.create(); K.prototype.initialize = init; return K; }
var kinds = {
  nine: build(function (a, b, c, d, e, f, g, h, i) { this.a = a ? a : 0; this.b = b ? b : 0; this.c = c ? c : 0; this.d = d ? d : 0; this.e = e ? e : 0; this.f = f ? f : 0; this.g = g ? g : 0; this.h = h ? h : 0; this.i = i ? i : 0; }),
  nonParam: build(function (a) { var t = 2; this.a = t ? t : 0; this.b = a; }),
  dup: build(function (a, b) { this.a = a ? a : 1; this.b = a ? a : 2; }),
  cross: build(function (a, b) { this.a = a ? b : 3; }),
  prefixCross: build(function (a, b) { if (!a) b = 4; this.a = a; this.b = b; }),
  prefixDup: build(function (a, b) { if (!a) a = 5; if (!a) a = 6; this.a = a; this.b = b; }),
  usesArgs: build(function (a) { this.a = a ? a : arguments.length; }),
  forceReset: build(function (a) { for (var a = 0; a < 1; a++); this.a = a ? a : 7; }),
  captured: build(function (a) { this.a = a ? a : 8; this.get = function () { return a; }; }),
  explicitReturn: build(function (a) { this.a = a ? a : 9; return; }),
  mixedTail: build(function (a, b) { if (!a) a = 10; this.a = a; this.b = b + 1; }),
  simple: build(function (a, b) { this.a = a; this.b = b; }),
  defaults: build(function (a, b) { this.a = a ? a : 11; this.b = b ? b : 12; }),
  prefix: build(function (a, b) { if (!a) a = 13; this.a = a; this.b = b; })
};
var names = Object.keys(kinds);
var res = {};
for (var r = 0; r < 150; r++) {
  for (var n = 0; n < names.length; n++) {
    var K = kinds[names[n]];
    var o = (r & 1) ? new K(r, r + 1, 3, 4, 5, 6, 7, 8, 9) : new K(0, "", 0, 0, 0, 0, 0, 0, 0);
    res[names[n] + (r & 1)] = JSON.stringify(o) + (typeof o.get === "function" ? "/get=" + o.get() : "");
  }
}
for (var n = 0; n < names.length; n++) out.push(names[n] + " " + res[names[n] + 0] + " " + res[names[n] + 1]);
console.log(out.join("\n"));
"""
    check(js, golden, "forwarded_initializers_with_unrecognised_bodies", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_literal_parameter_and_declaration_forms_left_to_the_tree_walker(js, golden, tier):
    """CATCHES: compiled functions that mishandle object literals with __proto__, parenthesised computed or duplicate keys, parameter defaults using updates, holes, methods, members, indices, parentheses or destructuring after defaults (also when captured or shadowed by a function declaration), decorated classes and members, `using` declarations in blocks, bodies, for-of and for heads, or nested generators and async arrows."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function protoLit(k) { var p = { base: k }; var o = { __proto__: p, own: 1 }; return o.base + o.own + (Object.getPrototypeOf(o) === p); }
function parenKey(k) { var o = { [("pk")]: k, ["q"]: 2 }; return o.pk + o.q; }
function hashKey(k) { var o = { "#x": k }; return o["#x"]; }
function dupKeys(k) { var o = { a: 1, a: k, b: 2 }; return o.a + o.b + Object.keys(o).join(""); }
out.push(hot(protoLit), hot(parenKey), hot(hashKey), hot(dupKeys));
function defaults(a, b = (1), c = a++, d = [1, , 2], e = { m() { return 1; } }, f = a.x, g = a[0], h = [a, , a]) { return [typeof a, a, b, c, d.length, e.m(), f, g, h.length].join(","); }
out.push(hot(defaults), defaults({ x: "X", 0: "Z", valueOf: function () { return 40; } }));
function tag(v, ctx) { return v; }
function makeDecorated(k) {
  @tag class A { @tag m() { return "m" + k; } @tag static s() { return "s"; } }
  return new A().m() + A.s();
}
out.push(hot(makeDecorated));
var log = [];
function res(name) { return { [Symbol.dispose]: function () { log.push("dispose " + name); } }; }
function useBlock(k) { { using a = res("a" + k), b = null; log.push("body" + k); } return log.length; }
out.push(hot(useBlock), log.slice(-3).join(","));
function useBody(k) { using r = res("r" + k); return "ret" + k; }
out.push(hot(useBody), log.slice(-1)[0]);
function useForOf(k) { var n = 0; for (using x of [res("x" + k), res("y" + k)]) n++; return n; }
out.push(hot(useForOf), log.slice(-2).join(","));
function useForHead(k) { var n = 0; for (using z = res("z" + k); n < 2; n++); return n; }
out.push(hot(useForHead), log.slice(-1)[0]);
function nestedGen(k) { function* g() { yield k; yield* [k + 1]; } return [...g()].join(""); }
out.push(hot(nestedGen));
function nestedAsyncArrow(k) { var f = async (x) => { await x; return x; }; return typeof f(k); }
out.push(hot(nestedAsyncArrow));
function destrLater(a = 1, { b } = { b: 2 }, [c] = [3]) { return a + b + c; }
out.push(hot(function (k) { return destrLater(k); }), destrLater(undefined, { b: 10 }, [20]));
function parenCaptured(a = (5), b = ([]), c = ({})) { return function () { return a + b.length + Object.keys(c).length; }; }
out.push(hot(function () { return parenCaptured()(); }), parenCaptured(7, [1], { k: 1 })());
function capturedFnDefault(a = 1) { function a() { return "fn"; } return function () { return typeof a; }; }
out.push(hot(function () { return capturedFnDefault()(); }), capturedFnDefault(2)());
function updDefault(a, b = a.n++) { return a.n + ":" + b; }
out.push(hot(function () { return updDefault({ n: 1 }); }), updDefault({ n: 5 }, "given"));
console.log(out.join("|"));
"""
    check(js, golden, "literal_parameter_and_declaration_forms_left_to_the_tree_walker", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_property_reads_through_three_prototype_hops(js, golden, tier):
    """CATCHES: compiled property-read caches that bake a three-level prototype lookup and then miss a shadowing write, a deletion, an accessor installed mid-chain or a deeper receiver, or mishandle digit-leading names, named properties on arrays and string-primitive method receivers."""
    code = r"""
var out = [];
var A = { deep: 1, "9x": 9, m: function () { return "m"; } };
var B = Object.create(A); B.b = 2;
var C = Object.create(B); C.c = 3;
var D = Object.create(C); D.d = 4;
function rd(o) { return o.deep + o["9x"] + o.m() + o.c; }
function rdLoop(o, n) { var s = ""; for (var i = 0; i < n; i++) s = rd(o); return s; }
out.push(rdLoop(D, 300));
var E = Object.create(D); E.e = 5;
out.push(rdLoop(E, 3));
B.deep = 20;
out.push(rdLoop(D, 3));
delete B.deep; C["9x"] = 90;
out.push(rdLoop(D, 3));
Object.defineProperty(B, "deep", { get: function () { return 200; }, configurable: true });
out.push(rdLoop(D, 3));
A.m = function () { return "M"; };
out.push(rdLoop(D, 3), rdLoop(E, 2));
function digitKeys(o) { var s = 0; for (var i = 0; i < 20; i++) s += o["1a"] + o["2b"]; return s; }
out.push(digitKeys({ "1a": 1, "2b": 2 }), digitKeys(Object.create({ "1a": 3, "2b": 4 })), digitKeys([5]));
function arrNamed(a) { var s = 0; for (var i = 0; i < 20; i++) s += a.extra + a.length; return s; }
var arr = [1, 2]; arr.extra = 7;
out.push(arrNamed(arr), arrNamed(Object.assign([1], { extra: 1 })));
function strMethods(s) { var r = ""; for (var i = 0; i < 20; i++) r = s.toUpperCase() + s.at(0) + s.length; return r; }
out.push(strMethods("ab"), strMethods(new String("cd")));
console.log(out.join("|"));
"""
    check(js, golden, "property_reads_through_three_prototype_hops", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_hoisting_and_binding_forms_that_force_a_fallback(js, golden, tier):
    """CATCHES: compiled functions whose `for (var p ...)` head re-declares a defaulted parameter, whose function declaration shadows a parameter, whose captured defaults reference other parameters (including the TDZ error), or that use lexical destructuring with defaults/nesting/rest, labelled exits crossing two or three for-of loops, destructuring for-heads, block functions and lexical declarations in switch cases."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function forceDefault(a = 1) { var s = ""; for (var a = 0; a < 2; a++) s += a; return s + a; }
out.push(hot(function (k) { return forceDefault(k); }), forceDefault());
function fnShadowParam(a) { function a() { return "fn"; } return typeof a + a(); }
out.push(hot(function (k) { return fnShadowParam(k); }));
function capturedDefault(a, b = a + 1) { return function () { return a + b; }; }
out.push(hot(function (k) { return capturedDefault(k)(); }));
function capturedDefaultLater(a = b, b = 2) { return function () { return a; }; }
try { out.push(capturedDefaultLater()()); } catch (e) { out.push(e.constructor.name); }
out.push(hot(function (k) { return capturedDefaultLater(k)(); }));
function lexDefault(arr) { let [x = 1, y] = arr; const { p: { q } } = { p: { q: arr.length } }; let [...rest] = arr; return x + ":" + y + ":" + q + ":" + rest.length; }
out.push(hot(function (k) { return lexDefault([undefined, k]); }));
function breakTwo(xs) { var s = ""; outer: for (var x of xs) { for (var y of xs) { s += x + "" + y; if (y === 2) break outer; } } return s; }
out.push(hot(function () { return breakTwo([1, 2, 3]); }));
function continueTwo(xs) { var s = ""; outer: for (var x of xs) { for (var y of xs) { for (var z of xs) { if (z === 2) continue outer; s += z; } } } return s; }
out.push(hot(function () { return continueTwo([1, 2, 3]); }));
function letDestrFor(n) { var s = 0; for (let [c, d] = [0, 1]; c < n; c++) s += d + c; return s; }
out.push(hot(function () { return letDestrFor(3); }));
function constDestrFor(n) { var s = 0; for (const { v } = { v: n }; s < v; s++); return s; }
out.push(hot(function () { return constDestrFor(4); }));
function fnInBlock(k) { { function inner() { return "in" + k; } } return inner(); }
out.push(hot(fnInBlock));
function letInSwitch(k) { switch (k % 3) { case 0: let a = "zero"; return a; case 1: { let b = "one"; return b; } default: return "d"; } }
out.push(hot(letInSwitch), letInSwitch(1), letInSwitch(3));
console.log(out.join("|"));
"""
    check(js, golden, "hoisting_and_binding_forms_that_force_a_fallback", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_lexical_for_in_and_mixed_type_switches(js, golden, tier):
    """CATCHES: compiled lexical for-in loops whose continue/break targets are patched wrongly, that share one binding between closures, skip keys deleted or visit keys added during iteration, mishandle inherited, array, string, null or Proxy subjects, or switch statements that compare cases with loose equality, mis-order fall-through, or confuse break and continue inside loops."""
    code = r"""
var out = [];
function hot(f) { var r; for (var k = 0; k < 12; k++) r = f(k); return r; }
function letForIn(o) { var s = ""; for (let j in o) { if (j === "b") continue; if (j > "c") break; s += j; } for (const q in o) { if (q === "a") continue; s += q.toUpperCase(); if (q === "c") break; } return s; }
out.push(hot(function () { return letForIn({ a: 1, b: 2, c: 3, d: 4 }); }));
function capLetForIn(o) { var fs = []; for (let k in o) fs.push(function () { return k; }); return fs.map(function (f) { return f(); }).join(""); }
out.push(hot(function () { return capLetForIn({ p: 1, q: 2 }); }));
function labeledForIn(o) { var s = ""; outer: for (let a in o) { for (let b in o) { if (b === a) continue outer; if (b > "b") break outer; s += a + b; } } return s; }
out.push(hot(function () { return labeledForIn({ a: 1, b: 2, c: 3 }); }));
function forInMutate(o) { var s = ""; for (let k in o) { s += k; delete o.c; o.z = 1; } return s; }
out.push(hot(function () { return forInMutate({ a: 1, b: 2, c: 3 }); }));
function forInProto(o) { var s = ""; for (let k in o) s += k; return s; }
var base = { inherited: 1 }; var derived = Object.create(base); derived.own = 2;
out.push(hot(function () { return forInProto(derived); }), forInProto([5, 6]), forInProto("xy"), forInProto(null), forInProto(new Proxy({ pa: 1 }, {})));
function sw(x) {
  switch (x) { case 1: return "one"; case "1": return "str1"; case true: return "true"; case null: return "null"; case undefined: return "undef"; case 1n: return "big"; default: return "def"; }
}
out.push(hot(function () { return [1, "1", true, null, undefined, 1n, 2, NaN].map(sw).join(); }));
function swFall(x) { var s = ""; switch (x) { case 0: s += "a"; case 1: s += "b"; break; case 2: { s += "c"; } default: s += "d"; case 3: s += "e"; } return s; }
out.push(hot(function () { return [0, 1, 2, 3, 4].map(swFall).join(); }));
function swLoop(xs) { var s = ""; for (var x of xs) { switch (x) { case 1: continue; case 2: s += "two"; break; default: s += x; } s += ";"; } return s; }
out.push(hot(function () { return swLoop([1, 2, 3]); }));
function swObj(x, o) { switch (x) { case o: return "same"; case o.v: return "v"; default: return "none"; } }
var so = { v: 5 };
out.push(hot(function () { return swObj(so, so) + swObj(5, so) + swObj({}, so); }));
console.log(out.join("|"));
"""
    check(js, golden, "lexical_for_in_and_mixed_type_switches", code, tier)


NATIVE_ENTRY = {"LUMEN_ITERATOR_ENTRY_NATIVE": "1"}
ENTRY_MODES = [
    pytest.param((), NATIVE_ENTRY, id="jit-native-entry"),
    pytest.param(("--tier=bytecode",), NATIVE_ENTRY, id="bytecode-native-entry"),
    pytest.param((), {}, id="jit"),
    pytest.param(("--tier=interp",), {}, id="interp"),
]


@pytest.mark.parametrize("tier,switches", ENTRY_MODES)
def test_custom_iterator_next_bodies_outside_the_native_entry_subset(js, golden, tier, switches):
    """CATCHES: the opt-in native iterator entry (docs/optimizer.md, LUMEN_ITERATOR_ENTRY_NATIVE) admitting or mis-evaluating next() bodies with multiplication/division, >=/<= guards, undefined values, extra or misspelt result keys, deep operand stacks, loops, `&&` guards, chained assignments, two stores, non-object results, named/parameterised/arguments-using/arrow/decorated-object/capturing callees, class methods, or a next method swapped at the same loop."""
    code = r"""
var out = [];
function drain(it) { var values = []; for (var value of it) values.push(value); return values.join(","); }
function mk(kind, n) {
  const st = { c: 0, n: n, k: 3 };
  var local = 0;
  var it = { [Symbol.iterator]() { return this; } };
  if (kind === "muldiv") it.next = function () { if (st.c <= st.n) { st.c = st.c + 1; return { value: st.c * st.k / 2, done: false }; } return { done: true }; };
  if (kind === "ge") it.next = function () { if (st.n >= st.c) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true, value: undefined }; };
  if (kind === "undef") it.next = function () { if (st.c < st.n) { st.c = st.c + 1; return { value: undefined, done: false }; } return { done: true }; };
  if (kind === "keys") it.next = function () { if (st.c < st.n) { st.c = st.c + 1; return { done: false, value: st.c, extra: 1 }; } return { done: true }; };
  if (kind === "wrongkeys") it.next = function () { if (st.c < st.n) { st.c = st.c + 1; return { val: st.c, done: st.c > 2 }; } return { done: true }; };
  if (kind === "deep") it.next = function () { if (st.c < st.n) { st.c = st.c + 1; return { value: st.c + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + (st.k + st.k))))))))))))))), done: false }; } return { done: true }; };
  if (kind === "loop") it.next = function () { while (st.c < st.n) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; };
  if (kind === "and") it.next = function () { if (st.c < st.n && st.k > 0) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; };
  if (kind === "dup") it.next = function () { if (st.c < st.n) { var v = st.c = st.c + 1; return { value: v, done: false }; } return { done: true }; };
  if (kind === "twostores") it.next = function () { if (st.c < st.n) { st.c = st.c + 1; st.k = st.k + 1; return { value: st.k, done: false }; } return { done: true }; };
  if (kind === "named") it.next = function nx() { if (st.c < st.n) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; };
  if (kind === "param") it.next = function (p) { if (st.c < st.n) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; };
  if (kind === "args") it.next = function () { if (st.c < st.n + arguments.length) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; };
  if (kind === "arrow") it.next = () => { if (st.c < st.n) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; };
  if (kind === "fnprops") { it.next = function () { if (st.c < st.n) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; }; Object.defineProperty(it.next, "x", { get: function () { return 1; } }); }
  if (kind === "capture") it.next = function () { var inner = function () { return local; }; if (st.c < st.n) { st.c = st.c + 1; return { value: st.c + inner(), done: false }; } return { done: true }; };
  return it;
}
class CIt { constructor(n) { this.st = { c: 0, n: n }; } [Symbol.iterator]() { return this; } next() { var st = this.st; if (st.c < st.n) { st.c = st.c + 1; return { value: st.c, done: false }; } return { done: true }; } }
var kinds = ["muldiv", "ge", "undef", "keys", "wrongkeys", "deep", "loop", "and", "dup", "twostores", "named", "param", "args", "arrow", "fnprops", "capture"];
var res = {};
for (var r = 0; r < 100; r++) { for (var q = 0; q < kinds.length; q++) res[kinds[q]] = drain(mk(kinds[q], 3)); res.cls = drain(new CIt(2)); }
for (var q = 0; q < kinds.length; q++) out.push(kinds[q] + "=" + res[kinds[q]]);
out.push("cls=" + res.cls);
function nonObj() { const st = { c: 0 }; return { [Symbol.iterator]() { return this; }, next: function () { if (st.c < 2) { st.c = st.c + 1; return st.c; } return { done: true }; } }; }
for (var r = 0; r < 30; r++) { try { drain(nonObj()); } catch (e) { res.nonobj = e.constructor.name + ":" + e.message; } }
out.push("nonobj=" + res.nonobj);
const shared = { c: 0, n: 0 };
function nextA() { if (shared.c < shared.n) { shared.c = shared.c + 1; return { value: "A" + shared.c, done: false }; } return { done: true }; }
function nextB() { if (shared.c < shared.n) { shared.c = shared.c + 1; return { value: "B" + shared.c, done: false }; } return { done: true }; }
function swapDrain(f) { shared.c = 0; shared.n = 2; var it = { [Symbol.iterator]() { return this; }, next: f }; return drain(it); }
var sw = [];
for (var r = 0; r < 100; r++) sw[r & 1] = swapDrain(r < 60 ? nextA : (r & 1 ? nextA : nextB));
out.push("swap=" + sw.join("/"));
console.log(out.join("\n"));
"""
    r = js(code, *tier, env_overrides=switches)
    assert out(r) == golden("custom_iterator_next_bodies_outside_the_native_entry_subset")
    assert (r.returncode, r.stderr) == (0, b"")



@pytest.mark.parametrize("tier", TIERS)
def test_counter_fill_loops_and_tail_walks_with_unusual_receivers(js, golden, tier):
    """CATCHES: the counter-wrap fill and linked-list tail-walk loop regions, or mixed property loops, that assume monomorphic receivers, an own `a2`/`link` field, a loop entered with an empty operand stack (inside a switch case), or a non-aliasing scan variable, and so store wrong elements, return the wrong tail or mis-count pre-increments."""
    code = r"""
var LIMIT = 6;
function W(seed) { this.v2 = seed; }
function W2(seed) { this.pad = 0; this.v2 = seed; }
function Pk() { this.a2 = new Array(8).fill(0); }
function Pk2() { this.pad = 1; this.a2 = new Array(8).fill(0); }
function ProtoPk() {}
ProtoPk.prototype.a2 = new Array(8).fill(0);
W.prototype.fmt = W2.prototype.fmt = function (pk) { return pk.a2.join(","); };
W.prototype.fillA = W2.prototype.fillA = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.v2; } return this.fmt(pk); };
W.prototype.fillB = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.v2; } return this.fmt(pk); };
W.prototype.fillC = function (pk) { for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.v2; } return this.fmt(pk); };
W.prototype.fillD = function (pk, mode) { switch (mode) { case 1: for (var i = 0; i < LIMIT; i++) { this.v2++; if (this.v2 > 26) this.v2 = 1; pk.a2[i] = this.v2; } } return this.fmt(pk); };
function Node(id, link) { this.id = id; this.link = link; }
function PNode(id) { this.id = id; }
PNode.prototype.link = null;
function idOf(n) { return n.id; }
function tailSwitch(head, mode) { var peek, next = head; switch (mode) { case 1: while ((peek = next.link) != null) next = peek; } return next.id; }
function tailProto(head) { var peek, next = head; while ((peek = next.link) != null) next = peek; return next.id + ":" + idOf(next); }
function tailSame(head) { var next = head, peek = head; while ((next = next.link) != null) peek = next; return peek.id + idOf(peek); }
var list = null; for (var k = 0; k < 12; k++) list = new Node(k, list);
var res = [], seen = [];
for (var r = 0; r < 160; r++) {
  var w = (r & 1) ? new W(r % 30) : new W2(r % 30);
  var pk = (r & 1) ? new Pk() : new Pk2();
  res = [w.fillA(new Pk()), new W(r % 7).fillB(pk), new W(r % 5).fillC(new ProtoPk()), new W(r % 3).fillD(new Pk(), 1), new W(4).fillD(new Pk(), 2), tailSwitch(list, 1), tailSwitch(list, 0), tailProto(new PNode(r)), tailSame(list)];
  if (r % 53 === 0) seen.push(res.join(" "));
}
console.log(seen.join("\n"));
console.log(res.join("\n"));
function mixedPre(objs) { var s = 0, c = 0, t; for (var i = 0; i < objs.length; i++) { s = s + objs[i].v; t = ++c; s = s + t; t = --c + 2; } return s + ":" + c + ":" + t; }
var objs = []; for (var i = 0; i < 10; i++) objs.push({ v: i });
console.log(mixedPre(objs), mixedPre([{ v: 0.5 }, { v: "x" }]));
"""
    check(js, golden, "counter_fill_loops_and_tail_walks_with_unusual_receivers", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_global_and_closure_stores_after_scope_changes(js, golden, tier):
    """CATCHES: cached name stores in compiled code that keep writing a global slot after the global object grew, after the binding became non-writable (silently in sloppy code, TypeError in strict code) or an accessor, that miss bindings added to an enclosing function scope by eval, or that keep writing a `with` object's property after it was deleted."""
    code = r"""
var out = [];
var g = 0;
globalThis.h = 0;
function storeG(v) { g = v; h = v + 1; return g + h; }
for (var i = 0; i < 20; i++) storeG(i);
globalThis.extra1 = 1;
out.push(storeG(100), g, h);
Object.defineProperty(globalThis, "h", { writable: false });
out.push(storeG(200), g, h);
function strictStore(v) { "use strict"; h = v; return h; }
try { strictStore(5); } catch (e) { out.push(e.constructor.name); }
Object.defineProperty(globalThis, "h", { get: function () { return "getter"; }, set: function (v) { out.push("set:" + v); }, configurable: true });
out.push(storeG(300), h);
function outer(code) {
  var base = 1;
  eval(code);
  function bump(v) { base = base + v; return base; }
  for (var k = 0; k < 20; k++) bump(1);
  eval("var late = 9;");
  return bump(5) + ":" + base + ":" + late;
}
out.push(outer(""), outer("var early = 1;"));
var wobj = { wx: 1 };
var wset;
with (wobj) { wset = function (v) { wx = v; return wx; }; }
for (var k = 0; k < 20; k++) wset(k);
out.push(wset(42), wobj.wx);
delete wobj.wx;
out.push(wset(7), String(wobj.wx), typeof wx === "undefined" ? "nowx" : wx);
function counterIn() { var n = 0; return { inc: function () { n = n + 1; return n; }, get: function () { return n; } }; }
var c = counterIn(); for (var k = 0; k < 20; k++) c.inc();
out.push(c.inc(), c.get());
console.log(out.join("|"));
"""
    check(js, golden, "global_and_closure_stores_after_scope_changes", code, tier)

# ----------------------------------------------------------------------------- Richards planners
# The JIT recognises the V8 Richards benchmark's methods by exact bytecode shape, inline-cache
# state and global values, and plans dedicated scheduler regions for them. Every rewrite below
# perturbs one method body, constructor or global so that a planner gets part-way and must decline
# (or plan a different region); the program must behave exactly as on the tree-walker. All rewrites
# of a group run in one process: each is evaluated as fresh global code, warmed until schedule()
# and the task methods are recompiled with their callees inlined, and then run once more. (Every
# rewrite was checked against --tier=interp when this module was written; the tree-walker needs
# several seconds for these warm-ups, so the tests compare the two compiled tiers.)
RICHARDS_TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode")]
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
  return scheduler;
}

var COUNT = 1000;
var EXPECTED_QUEUE_COUNT = 2322;
var EXPECTED_HOLD_COUNT = 928;

var ID_IDLE       = 0;
var ID_WORKER     = 1;
var ID_HANDLER_A  = 2;
var ID_HANDLER_B  = 3;
var ID_DEVICE_A   = 4;
var ID_DEVICE_B   = 5;
var NUMBER_OF_IDS = 6;

var KIND_DEVICE   = 0;
var KIND_WORK     = 1;

function Scheduler() {
  this.queueCount = 0;
  this.holdCount = 0;
  this.blocks = new Array(NUMBER_OF_IDS);
  this.list = null;
  this.currentTcb = null;
  this.currentId = null;
}

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
"""

RICHARDS_WARMUP = r"""
// Get schedule() and the task methods compiled, then recompiled with their callees inlined: real
// runs warm every role, direct holdCurrent calls warm the hold helper, and cheap re-schedules of a
// finished (all held or suspended) scheduler reach schedule()'s recompilation threshold.
function warmup(first, small) {
  var s, acc = 0;
  COUNT = first;
  s = runRichards();
  acc = s.queueCount * 3 + s.holdCount;
  for (var i = 0; i < 9; i++) {
    COUNT = small;
    s = runRichards();
    acc = (acc * 31 + s.queueCount * 3 + s.holdCount) % 1000003;
  }
  for (var k = 0; k < 110; k++) {
    s.currentTcb = s.blocks[k % 2 ? ID_DEVICE_A : ID_DEVICE_B];
    s.holdCurrent();
  }
  s.currentTcb = null;
  for (var j = 0; j < 80; j++) s.schedule();
  for (var i = 0; i < 25; i++) {
    COUNT = small + (i % 3);
    s = runRichards();
    acc = (acc * 31 + s.queueCount * 3 + s.holdCount) % 1000003;
  }
  return acc + "/" + s.queueCount + "/" + s.holdCount;
}
"""

RICHARDS_RUN = r"""
var line;
try {
  line = "warmup " + warmup(120, 4);
  COUNT = 200;
  var s = runRichards(), states = [];
  for (var id = 0; id < NUMBER_OF_IDS; id++) states.push(String(s.blocks[id]));
  line += " | " + s.queueCount + "/" + s.holdCount + " " + states.join(" ");
} catch (e) {
  line = "error " + e.constructor.name;
}
line;
"""

OPERAND_ORDER_REWRITES = [
    ('release-priority-operands-swapped', [('if (tcb.priority > this.currentTcb.priority) {', 'if (this.currentTcb.priority < tcb.priority) {')], ''),
    ('release-compares-with-false', [('if (tcb == null) return tcb;\n  tcb.markAsNotHeld();', 'if (tcb == false) return tcb;\n  tcb.markAsNotHeld();')], ''),
    ('queue-compares-with-false', [('var t = this.blocks[packet.id];\n  if (t == null) return t;', 'var t = this.blocks[packet.id];\n  if (t == false) return t;')], ''),
    ('tcb-run-state-operands-swapped', [('if (this.state == STATE_SUSPENDED_RUNNABLE) {', 'if (STATE_SUSPENDED_RUNNABLE == this.state) {')], ''),
    ('handler-count-operands-swapped', [('if (count < DATA_SIZE) {', 'if (DATA_SIZE > count) {')], ''),
    ('handler-kind-operands-swapped', [('if (packet.kind == KIND_WORK) {', 'if (KIND_WORK == packet.kind) {')], ''),
    ('worker-id-operands-swapped', [('if (this.v1 == ID_HANDLER_A) {', 'if (ID_HANDLER_A == this.v1) {')], ''),
]
STATEMENT_REWRITES = [
    ('held-mask-compares-with-false', [('return (this.state & STATE_HELD) != 0 || (this.state == STATE_SUSPENDED);', 'return (this.state & STATE_HELD) != false || (this.state == STATE_SUSPENDED);')], ''),
    ('idle-xor-mask-changed', [('^ 0xD008;', '^ 0xD009;')], ''),
    ('idle-parity-compares-with-half', [('if ((this.v1 & 1) == 0) {', 'if ((this.v1 & 1) == 0.5) {')], ''),
    ('check-priority-operands-swapped', [('if (this.priority > task.priority) return this;', 'if (task.priority < this.priority) return this;')], ''),
    ('queue-stores-reordered', [('  packet.link = null;\n  packet.id = this.currentId;', '  packet.id = this.currentId;\n  packet.link = null;')], ''),
    ('schedule-reads-tcb-into-a-local', [('      this.currentId = this.currentTcb.id;\n      this.currentTcb = this.currentTcb.run();', '      var tcb = this.currentTcb;\n      this.currentId = tcb.id;\n      this.currentTcb = tcb.run();')], ''),
    ('schedule-loop-has-a-trailing-store', [('      this.currentTcb = this.currentTcb.run();\n    }\n  }', '      this.currentTcb = this.currentTcb.run();\n    }\n    this.lastId = this.currentId;\n  }')], ''),
]
GLOBAL_VALUE_REWRITES = [
    ('held-bit-is-fractional', [], 'STATE_HELD = 4.5;\n'),
    ('running-state-is-negative-zero', [], 'STATE_RUNNING = -0;\n'),
    ('runnable-state-is-boolean', [], 'STATE_RUNNABLE = true;\n'),
    ('suspended-runnable-state-is-string', [], "STATE_SUSPENDED_RUNNABLE = '3';\n"),
    ('work-kind-is-fractional', [], 'KIND_WORK = 1.5;\n'),
    ('data-size-is-five', [], 'DATA_SIZE = 5;\n'),
    ('not-held-mask-is-fractional', [], 'STATE_SUSPENDED = 2.0; STATE_NOT_HELD = -5.5;\n'),
    ('worker-reset-above-threshold', [('if (this.v2 > 26) this.v2 = 1;', 'if (this.v2 > 26) this.v2 = 30;')], ''),
    ('worker-a1-is-fractional', [('    packet.a1 = 0;\n    for', '    packet.a1 = 0.5;\n    for')], ''),
    ('worker-id-store-adds-zero', [('    packet.id = this.v1;\n    packet.a1 = 0;', '    packet.id = this.v1 + 0;\n    packet.a1 = 0;')], ''),
    ('worker-loop-bound-swapped', [('for (var i = 0; i < DATA_SIZE; i++) {', 'for (var i = 0; DATA_SIZE > i; i++) {')], ''),
]
SHAPE_REWRITES = [
    ('handler-element-read-adds-zero', [('      v.a1 = this.v1.a2[count];', '      v.a1 = this.v1.a2[count] + 0;')], ''),
    ('mark-suspended-uses-compound-or', [('  this.state = this.state | STATE_SUSPENDED;', '  this.state |= STATE_SUSPENDED;')], ''),
    ('mark-runnable-uses-compound-or', [('  this.state = this.state | STATE_RUNNABLE;', '  this.state |= STATE_RUNNABLE;')], ''),
    ('add-to-clears-link-with-void', [('Packet.prototype.addTo = function (queue) {\n  this.link = null;', 'Packet.prototype.addTo = function (queue) {\n  this.link = void 0;')], ''),
    ('add-to-declares-locals-reordered', [('  var peek, next = queue;\n  while', '  var next = queue, peek;\n  while')], ''),
    ('add-to-loop-operands-swapped', [('  while ((peek = next.link) != null)\n    next = peek;', '  while (null != (peek = next.link))\n    next = peek;')], ''),
    ('add-to-takes-an-extra-parameter', [('Packet.prototype.addTo = function (queue) {', 'Packet.prototype.addTo = function (queue, unused) {')], ''),
    ('handler-locals-reordered', [('    var count = this.v1.a1;\n    var v;', '    var v;\n    var count = this.v1.a1;')], ''),
    ('mark-runnable-takes-a-parameter', [('TaskControlBlock.prototype.markAsRunnable = function () {', 'TaskControlBlock.prototype.markAsRunnable = function (unused) {')], ''),
    ('device-b-packets-have-an-extra-field', [('  this.a2 = new Array(DATA_SIZE);\n}', '  this.a2 = new Array(DATA_SIZE);\n  if (id == ID_DEVICE_B) this.extra = 1;\n}')], ''),
    ('check-priority-compares-queue-with-zero', [('if (this.queue == null) {\n    this.queue = packet;', 'if (this.queue == 0) {\n    this.queue = packet;')], ''),
    ('device-clears-v1-with-zero', [('    var v = this.v1;\n    this.v1 = null;', '    var v = this.v1;\n    this.v1 = 0;')], ''),
    ('handler-v2-inherited-from-prototype', [('function HandlerTask(scheduler) {\n  this.scheduler = scheduler;\n  this.v1 = null;\n  this.v2 = null;\n}', 'HandlerTask.prototype.v2 = null;\nfunction HandlerTask(scheduler) {\n  this.scheduler = scheduler;\n  this.v1 = null;\n}')], ''),
    ('packet-link-inherited-when-null', [('function Packet(link, id, kind) {\n  this.link = link;', 'Packet.prototype.link = null;\nfunction Packet(link, id, kind) {\n  if (link != null) this.link = link;')], ''),
    ('idle-task-has-own-run-method', [('function IdleTask(scheduler, v1, count) {\n  this.scheduler = scheduler;', 'function IdleTask(scheduler, v1, count) {\n  this.run = IdleTask.prototype.run;\n  this.scheduler = scheduler;')], ''),
]


def richards_variants_program(variants):
    sources = []
    for name, rewrites, prelude in variants:
        src = RICHARDS
        for old, new in rewrites:
            assert old in src, name
            src = src.replace(old, new)
        sources.append([name, src + prelude + RICHARDS_WARMUP + RICHARDS_RUN])
    return (
        "var VARIANTS = " + json.dumps(sources) + ";\n"
        "for (var vi = 0; vi < VARIANTS.length; vi++) console.log(VARIANTS[vi][0] + ': ' + (0, eval)(VARIANTS[vi][1]));\n"
    )


@pytest.mark.parametrize("tier", RICHARDS_TIERS)
def test_richards_with_reversed_comparison_operands(js, golden, tier):
    """CATCHES: Idle-release, scheduler-active, Handler and Worker region planners that accept Richards methods whose comparisons have their operands swapped or compare against false instead of null, and then commit the canonical benchmark's guards and state transitions instead of the program's."""
    code = richards_variants_program(OPERAND_ORDER_REWRITES)
    check(js, golden, "richards_with_reversed_comparison_operands", code, tier)


@pytest.mark.parametrize("tier", RICHARDS_TIERS)
def test_richards_with_rewritten_constants_and_statements(js, golden, tier):
    """CATCHES: scheduler-shell, Idle-release and queue planners that bake the canonical Richards constants (the 0xD008 mask, parity test, null/0 compares) or statement order, so a changed xor mask, a half-valued parity compare, reordered stores, a schedule loop with a local or a trailing store produce different queue/hold counts than the tree-walker."""
    code = richards_variants_program(STATEMENT_REWRITES)
    check(js, golden, "richards_with_rewritten_constants_and_statements", code, tier)


@pytest.mark.parametrize("tier", RICHARDS_TIERS)
def test_richards_with_unusual_global_and_field_values(js, golden, tier):
    """CATCHES: Richards region planners that bake STATE_*/KIND_*/DATA_SIZE globals or worker constants as int32 immediates even when they are fractional, negative zero, boolean or string, or when the worker reset value, packet a1 or loop bound differ, so queue/hold counts or task states diverge from the tree-walker."""
    code = richards_variants_program(GLOBAL_VALUE_REWRITES)
    check(js, golden, "richards_with_unusual_global_and_field_values", code, tier)


@pytest.mark.parametrize("tier", RICHARDS_TIERS)
def test_richards_with_reshaped_methods_and_objects(js, golden, tier):
    """CATCHES: Handler/Device delivery planners that assume the canonical Packet.addTo, mark*, checkPriorityAdd and handler bodies (local order, parameters, compound operators, void/zero stores), own (not inherited) task fields and methods, or monomorphic packet shapes, and so mis-deliver packets or skip state changes when those methods are rewritten."""
    code = richards_variants_program(SHAPE_REWRITES)
    check(js, golden, "richards_with_reshaped_methods_and_objects", code, tier)
