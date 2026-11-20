"""Additional execution-tier agreement tests (tree-walking interpreter vs bytecode VM vs JIT).

Every program runs under all three tiers against ONE shared golden: the documented contract is
that `--tier=interp`, `--tier=bytecode` and the default JIT tier produce identical output. The
programs here target bytecode-compiler lowering decisions, VM runtime error paths, inline caches
and JIT helper guards (functions are called repeatedly so the compiled tiers really engage).
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


PROG_COMPILE_SHAPES = r"""
class P { #x = 1; static has(o) { return #x in o; } }
function outer1(o) {
  const inner = () => [P.has(o), typeof import("nope-module-x").catch(() => 0)];
  return inner()[0] + ":" + inner()[1];
}
class Q { #x = 2; static t(o) { function g() { return #x in o; } return g(); } }
for (let i = 0; i < 30; i++) { outer1({}); Q.t({}); }
console.log(outer1(new P()), Q.t(new Q()), Q.t({}));
function holes(a) { const g = () => [a, , a]; return g().length; }
for (let i = 0; i < 30; i++) holes(i);
console.log(holes(1));
function del(o) { delete (o.x); delete o["y"]; const r = delete 1; return [r, Object.keys(o).join()]; }
for (let i = 0; i < 30; i++) del({x:1,y:2,z:3});
console.log(JSON.stringify(del({x:1,y:2,z:3})));
function dbg(n) { ; debugger; let s = 0; for (let i = 0; i < n; i++) { ; s += i; } return s; }
for (let i = 0; i < 30; i++) dbg(10);
console.log(dbg(10));
var out = [];
function rep(f, ...a) { let r; for (let i = 0; i < 40; i++) r = f(...a); out.push((f.name || "anon") + " " + JSON.stringify(r)); }
function capDef(a = Math.max(1, 2)) { return () => a; }
rep(function (x) { return capDef(x)(); }, 7);
function forCap() { var fs = []; for (var i = 0; i < 3; i++) fs.push(() => i); return fs.map(f => f()); }
rep(forCap);
function forDef(a = 5, o) { var s = ""; for (var a in o) s += a; return s + a; }
rep(forDef, undefined, {p: 1, q: 2});
function forParam(a, o) { var s = 0; for (var a = 0; a < 3; a++) s += a; return s + a; }
rep(forParam, 9);
function annexB() { { function g() { return 4; } } return typeof g === "function" ? g() : -1; }
rep(annexB);
function capDestr(o) { const {a, b: {c}} = o; let [x, , y] = [1, 2, 3]; return [() => a + c, x + y]; }
rep(function (o) { const r = capDestr(o); return [r[0](), r[1]]; }, {a: 1, b: {c: 2}});
function destrRest(o) { const {a, ...r} = o; return Object.keys(r).length + a; }
rep(destrRest, {a: 1, b: 2, c: 3});
function destrDef(o) { const {a = 5, b} = o; return a + b; }
rep(destrDef, {b: 2});
function destrStrKey(o) { const {"a": x, b: y} = o; return x + y; }
rep(destrStrKey, {a: 3, b: 4});
function destrNumKey(o) { const {0: x, 1: y} = o; return x + y; }
rep(destrNumKey, [5, 6]);
function destrNested(a) { const [[x], y] = a; return x + y; }
rep(destrNested, [[1], 2]);
function destrHole(a) { let [x, , z] = a; return x * z; }
rep(destrHole, [3, 9, 4]);
function destrVarCap(o) { var {a} = o; return () => a; }
rep(function (o) { return destrVarCap(o)(); }, {a: 11});
function retFor(a) { for (const x of a) { for (const y of a) { if (x + y > 3) return x * 10 + y; } } return 0; }
rep(retFor, [1, 2, 3]);
function doBreak(n) { let i = 0; do { if (i > n) break; i++; } while (true); return i; }
rep(doBreak, 5);
function usingDecl() { return 1; }
rep(usingDecl);
function spreadMid(a) { return Math.max(...a, 0); }
rep(spreadMid, [1, 5, 3]);
function delId() { var q = 1; return typeof q; }
rep(delId);
function optCall(o) { return [o?.a?.b, o?.f?.(1), o.g?.(2), o?.["k"]]; }
rep(optCall, {a: {b: 3}, f: x => x + 1, g: undefined, k: 9});
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_compiler_bailout_and_capture_shapes(run, tier):
    """CATCHES: a bytecode/JIT compiler that mis-lowers (or wrongly compiles instead of deferring to the tree-walker) private-name checks in nested closures, dynamic import, captured/defaulted parameters reset by for(var) heads, Annex B block functions, destructuring with rest/defaults/holes/number keys, or returns crossing nested for-of loops."""
    check_prog(run, tier, PROG_COMPILE_SHAPES, "compile_shapes")


PROG_LOOP_ASSIGN = r"""
var out = [];
function rep(f, ...a) { let r; for (let i = 0; i < 40; i++) r = f(...a); out.push((f.name || "anon") + " " + JSON.stringify(r)); }
function forOfExisting(a) { let x = 0, s = 0; for (x of a) s += x; return [s, x]; }
rep(forOfExisting, [1, 2, 3]);
function forOfConst(a) { const x = 0; try { for (x of a) {} } catch (e) { return e.name; } return "none"; }
rep(forOfConst, [1]);
function forOfCap(a) { let x = 0; const f = () => x; for (x of a) {} return f(); }
rep(forOfCap, [4, 5]);
function forOfCapConst(a) { const x = 0; const f = () => x; try { for (x of a) {} } catch (e) { return e.name + f(); } return "none"; }
rep(forOfCapConst, [4, 5]);
var gx = 0;
function forOfGlobal(a) { for (gx of a) {} return gx; }
rep(forOfGlobal, [7, 8]);
function forOfVar(a) { var s = 0; for (var x of a) s += x; return s; }
rep(forOfVar, [1, 2]);
function forOfDestrAssign(a) { let p, q, s = 0; for ([p, q] of a) s += p * q; return s; }
rep(forOfDestrAssign, [[1, 2], [3, 4]]);
function forOfLetPattern(a) { let s = 0; for (const [p, q] of a) s += p - q; for (let {k} of [{k: 1}, {k: 2}]) s += k; return s; }
rep(forOfLetPattern, [[5, 2], [9, 1]]);
function breakTwo(a) { let n = 0; outer: for (const x of a) { for (const y of a) { n++; if (y === 2) break outer; } } return n; }
rep(breakTwo, [1, 2, 3]);
function breakTry(a) { let n = 0; for (const x of a) { try { n++; if (x === 2) break; } catch (e) {} } return n; }
rep(breakTry, [1, 2, 3]);
function contTry(a) { let n = 0; for (const x of a) { try { if (x === 2) continue; n += x; } catch (e) {} } return n; }
rep(contTry, [1, 2, 3]);
function forLetNoInit(n) { let s = 0; for (let i, j = 0; j < n; j++) { s += (i === undefined) ? 1 : 0; } return s; }
rep(forLetNoInit, 4);
function forLetDestr(n) { let s = 0; for (let [i, j] = [0, n]; i < j; i++) s += i; return s; }
rep(forLetDestr, 5);
function forVarDestr(n) { let s = 0; for (var {i, j} = {i: 0, j: n}; i < j; i++) s += i; return s; }
rep(forVarDestr, 5);
function seqStmt(n) { let a = 0, b = 0; for (let i = 0; i < n; i++, a++) { b += 2, a += 1; } (a++); return [a, b]; }
rep(seqStmt, 3);
function logicalAssign(o) { let a = null, b = 0, c = 1; a ??= 5; b ||= 6; c &&= 7; o.x ??= 1; return [a, b, c, o.x]; }
rep(function logicalAssignFresh() { return logicalAssign({}); });
function constAssign() { const c = 1; try { c = 2; } catch (e) { return e.name; } return "no"; }
rep(constAssign);
function capConstAssign() { const c = 1; const f = () => c; try { c = 2; } catch (e) { return e.name + f(); } return "no"; }
rep(capConstAssign);
function capCompound() { let c = 1; const f = () => c; const r = (c += 4) * (c -= 1); c **= 2; c >>>= 1; return [r, c, f()]; }
rep(capCompound);
var gv = 3;
function globalCompound() { const r = (gv += 2); gv |= 8; return [r, gv]; }
rep(globalCompound);
function memberCompound(o) { const a = (o.x += 2); const b = (o.y *= 3); o.z = (o.w = 1) + 1; return [a, b, o.z, o.w]; }
rep(function memberCompoundFresh() { return memberCompound({x: 1, y: 2}); });
function indexCompound(arr, k) { const a = (arr[k] += 5); const b = (arr[k + 1] -= 1); const c = ([0, 1][1] += 1); return [a, b, c, arr]; }
rep(function indexCompoundFresh() { return indexCompound([1, 2, 3], 0); });
function localIndexCompound(k) { const arr = [10, 20]; const r = (arr[k] *= 2); arr[k] %= 7; return [r, arr]; }
rep(localIndexCompound, 1);
function expCompound(o) { let a = 2; a **= 3; o.p **= 2; return [a, o.p]; }
rep(function expCompoundFresh() { return expCompound({p: 3}); });
function updParen(o) { let a = 0; (a)++; ++(o.x); (o["y"])--; return [a, o]; }
rep(function updParenFresh() { return updParen({x: 1, y: 2}); });
function constUpd() { const c = 1; try { c++; } catch (e) { return e.name; } return "no"; }
rep(constUpd);
function compKeyCall(o, k) { return o[k](2) + o["m"](3); }
rep(compKeyCall, {m(x) { return x * 10; }}, "m");
function finallyOnly() { let r = 0; try { r = 1; } finally { r += 1; } return r; }
rep(finallyOnly);
function catchDestr() { try { throw {a: 1}; } catch ({a}) { return a; } }
rep(catchDestr);
function catchNoParam() { try { throw 1; } catch { return "caught"; } }
rep(catchNoParam);
function withTypeof() { return [typeof undeclaredThing, typeof Math]; }
rep(withTypeof);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_loop_heads_and_compound_assignments(run, tier):
    """CATCHES: compiled tiers that bind for-of/for-in heads to the wrong home (existing slot, captured env, const, global, destructuring), forget handler cleanup on break/continue inside try within for-of, or evaluate compound/logical/exponent assignments to captured, global, member and computed-index targets in the wrong order."""
    check_prog(run, tier, PROG_LOOP_ASSIGN, "loop_assign")


PROG_VM_RUNTIME = r"""
var out = [];
function rep(f, a, b) { let r; for (let i = 0; i < 40; i++) { try { r = f(a, b); } catch (e) { r = "E:" + e.name + ":" + e.message; } } out.push(f.name + " " + (typeof r === "string" ? r : JSON.stringify(r))); }
function tdzUpd() { { x++; let x = 1; } }
rep(tdzUpd);
function tdzLoad() { { let y = x + 1; let x = 1; return y; } }
rep(tdzLoad);
function tdzGetPropLocal() { { const v = x.y; let x = {y: 1}; return v; } }
rep(tdzGetPropLocal);
function tdzSetPropLocal() { { x.y = 1; let x = {}; } }
rep(tdzSetPropLocal);
function bigUpd() { let b = 10n; const r1 = b++; const r2 = ++b; const r3 = b--; const r4 = --b; b++; return [r1, r2, r3, r4, b].join(); }
rep(bigUpd);
function coerceUpd(u, v) { let s = "5"; const r1 = s--; let t = "7"; const r2 = ++t; const r3 = u++; let w = "z"; w--; const r4 = --v; let x = "2"; const r5 = --x; return [r1, s, r2, t, r3, u, w, r4, v, r5, x].join(); }
rep(function coerceUpdFresh() { return coerceUpd({valueOf() { return 3; }}, {valueOf() { return 10; }}); });
function bigProp(o) { o.n = 5n; const a = o.n++; const b = --o.n; o.m = "4"; const c = o.m++; return [a, b, o.n, c, o.m].join(); }
rep(bigProp, {});
function getterThrow(o) { return o.bad; }
rep(getterThrow, {get bad() { throw new RangeError("g"); }});
function thisGetterThrow() { return this.bad; }
rep(function thisG() { return thisGetterThrow.call({get bad() { throw new RangeError("tg"); }}); });
function setterThrow(o) { return (o.bad = 3); }
rep(setterThrow, {set bad(v) { throw new RangeError("s" + v); }});
function C1() { this.bad = 4; }
rep(function thisSet() { const p = {set bad(v) { throw new RangeError("ts" + v); }}; C1.prototype = p; return new C1(); });
function destrNull(o) { const {a} = o; return a; }
rep(destrNull, null);
function destrUndef(o) { let {a, b} = o; return a; }
rep(destrUndef, undefined);
function destrShortIter() { let [a, b, c] = new Set([1, 2]); return [a, b, c === undefined]; }
rep(destrShortIter);
function destrLongIter() { let [a, b] = new Set([1, 2, 3]); return [a, b]; }
rep(destrLongIter);
function delNullProp(o) { return delete o.x; }
rep(delNullProp, null);
function delNullElem(o, k) { return delete o[k]; }
rep(delNullElem, undefined, "q");
function delFrozenStrict(o) { "use strict"; return delete o.x; }
rep(delFrozenStrict, Object.freeze({x: 1}));
function delFrozenSloppy(o, k) { return [delete o.x, delete o[k]]; }
rep(delFrozenSloppy, Object.freeze({x: 1, y: 2}), "y");
function spreadPlain(a) { return Math.max(...a); }
rep(spreadPlain, new Set([3, 9, 2]));
function appendStr(o) { o.s = ""; for (let i = 0; i < 5; i++) o.s += "ab"; o.n = 1; o.n += "x"; return o.s + o.n; }
rep(appendStr, {});
function elemNull(n) { return n[0]; }
rep(elemNull, null);
function setElemFrozen(a) { "use strict"; a[0] = 9; return a[0]; }
rep(setElemFrozen, Object.freeze([1, 2]));
function setElemFrozenSloppy(a) { const r = (a[0] = 9); return [r, a[0]]; }
rep(setElemFrozenSloppy, Object.freeze([1, 2]));
function setElemExpr(a, k) { const r = (a[k] = 5); return [r, a.length]; }
rep(setElemExpr, [], 3);
function updElemVal(o) { const a = o.arr[0]++; const b = ++o.arr[1]; const c = o.arr[2]--; const d = --o.arr[0]; return [a, b, c, d, o.arr].join("|"); }
rep(function updElem() { return updElemVal({arr: [1, 2, 3]}); });
function updElemObj(o) { const a = o["k"]++; o["k"]--; const b = ++o[1]; return [a, b, o.k, o[1]]; }
rep(function updObj() { return updElemObj({k: 1, 1: 5}); });
function updElemNull(o) { try { return o[0]++; } catch (e) { return e.name; } }
rep(updElemNull, null);
function updElemBig(o) { const a = o[0]++; return [String(a), String(o[0])]; }
rep(function updBig() { return updElemBig([5n]); });
function keyLocalNull() { let a = null; a[{}] += 1; }
rep(keyLocalNull);
function keyNull(o) { o.p[{toString() { return "k"; }}] += 1; }
rep(keyNull, {p: null});
function keyObj(o) { const k = {toString() { return "kk"; }}; o[k] = 1; o[k] += 2; const z = o; z[k] *= 3; return o.kk; }
rep(keyObj, {});
function methodElem(o) { return o[1](2) + o[0](3); }
rep(methodElem, Object.assign(Object.create({1: x => x * 7}), {0: x => x + 1}));
function methodElemHoley(a) { return a[1](4); }
rep(methodElemHoley, Object.setPrototypeOf([, ], {1: x => x * 3}));
function plusNum(n) { const k = +n; return k + (+"3") + (-n) + (-"4"); }
rep(plusNum, 5);
function inst(a, b) { return a instanceof b; }
rep(inst, [], Array);
rep(function instBad() { return inst({}, {}); });
rep(function instPrim() { return inst(1, Number); });
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_vm_runtime_errors_and_updates(run, tier):
    """CATCHES: VM/JIT op handlers that skip TDZ ReferenceErrors for locals read/updated/dereferenced before initialization, mishandle BigInt and string/valueOf ++/-- results, nullish destructuring/delete/element access errors, frozen element stores, accessor throws on this/local receivers, or computed method calls through prototypes."""
    check_prog(run, tier, PROG_VM_RUNTIME, "vm_runtime")


PROG_MORE_SHAPES = r"""
var out = [];
function rep(label, f, a, b) { var r; for (var i = 0; i < 40; i++) { try { r = f(a, b); } catch (e) { r = "E:" + e.name; } } out.push(label + " " + JSON.stringify(r)); }
function nestedGen() { function* g() { yield; yield 1; yield* [2, 3]; } return [...g()].map(String).join(); }
rep("nestedGen", nestedGen);
function nestedImportOpts() { const f = () => import("nope-xyz", { with: { type: "json" } }); return typeof f; }
rep("nestedImportOpts", nestedImportOpts);
function noAssign(o, a, i) { o.x = a[i]; o.y = [a, , i]; o.z = (i, a.length); o.w = {k: a[0]}; o.v = `${i}`; o.u = i ? a[1] : a[2]; o.t = typeof a; return o; }
rep("noAssign", function () { return noAssign({}, [4, 5, 6], 1); });
function noAssignHit(o, i) { o.x = (o = {fresh: 1}); return [o.fresh, i]; }
rep("noAssignHit", function () { return noAssignHit({}, 2); });
function noAssignDestr(o, a) { var b; o.x = ([b] = a); return b; }
rep("noAssignDestr", function () { return noAssignDestr({}, [9]); });
function letDestrCap(o) { let {a} = o; let [x, y] = [1, 2]; return () => a + x + y; }
rep("letDestrCap", function () { return letDestrCap({a: 3})(); });
function varRest(o) { var {a, ...r} = o; return a + Object.keys(r).join(); }
rep("varRest", varRest, {a: 1, b: 2, c: 3});
function varDefault(o) { var {a = 4, b} = o; return a + b; }
rep("varDefault", varDefault, {b: 1});
function varNumKey(o) { var {0: z} = o; return z; }
rep("varNumKey", varNumKey, ["q"]);
function varArrNested(a) { var [[p], q] = a; return p + q; }
rep("varArrNested", varArrNested, [[1], 2]);
function varArrRest(a) { var [p, ...q] = a; return p + q.length; }
rep("varArrRest", varArrRest, [1, 2, 3]);
function letArrDefault(a) { let [p = 5, q] = a; return p + q; }
rep("letArrDefault", letArrDefault, [undefined, 2]);
function letArrCap(a) { let [p, q] = a; return () => p + q; }
rep("letArrCap", function () { return letArrCap([1, 2])(); });
function doContinue(n) { let i = 0, s = 0; do { i++; if (i % 2) continue; s += i; } while (i < n); return s; }
rep("doContinue", doContinue, 10);
function forOfVar(a) { var s = 0; for (var x of a) s += x; return s; }
rep("forOfVar", forOfVar, [1, 2, 3]);
function forOfLetCaptured(a) { const fs = []; for (let x of a) fs.push(() => x); let x = 0; return fs.map(f => f()).join() + x; }
rep("forOfLetCaptured", forOfLetCaptured, [1, 2]);
function labeledForOf(a) { let n = 0; outer: for (const x of a) { for (const y of a) { n++; if (y === 2) continue outer; if (x === 3) break outer; } } return n; }
rep("labeledForOf", labeledForOf, [1, 2, 3]);
function labeledFor(n) { let c = 0; outer: for (let i = 0; i < n; i++) { for (let j = 0; j < n; j++) { if (j > i) continue outer; if (i * j > 6) break outer; c++; } } return c; }
rep("labeledFor", labeledFor, 6);
function breakFromForOfInFor(a) { let n = 0; for (let i = 0; i < 3; i++) { for (const x of a) { n += x; if (x === 2) break; } } return n; }
rep("breakFromForOfInFor", breakFromForOfInFor, [1, 2, 3]);
function capAssignExpr() { let c = 1; const f = () => c; const r = (c = 5) + (c = 6); return [r, f()]; }
rep("capAssignExpr", capAssignExpr);
function capFnAssign() { let c; const f = () => c; c = function () { return 3; }; return [c.name, f()()]; }
rep("capFnAssign", capFnAssign);
function coerceUpd2() { let s = "5"; const a = --s; let t = {valueOf() { return 7; }}; const b = ++t; let u = "x"; const c = --u; return [a, b, c, s, t]; }
rep("coerceUpd2", coerceUpd2);
var sum3 = function (a, b, c) { return a + b + c; };
function localSpread(a) { const f = sum3; return f(...a); }
rep("localSpreadArr", localSpread, [1, 2, 3]);
rep("localSpreadSet", localSpread, new Set([4, 5, 6]));
function localSpreadMore(a) { const f = sum3; return f(1, ...a); }
rep("localSpreadMore", localSpreadMore, [2, 3]);
function nullElemDeep(o) { try { return o.p[0]; } catch (e) { return e.name; } }
rep("nullElemDeep", nullElemDeep, {p: null});
function setElemFail(o, v) { const r = (o.a[1] = v); return [r, o.a[1]]; }
var roArr = [1, 2, 3]; Object.defineProperty(roArr, 1, {value: 2, writable: false});
rep("setElemFail", function () { return setElemFail({a: roArr}, 9); });
var setterProtoArr = [1]; var seen = []; Object.setPrototypeOf(setterProtoArr, Object.create(Array.prototype, {1: {set(v) { seen.push(v); }, configurable: true}}));
rep("setElemSetter", function () { return setElemFail({a: setterProtoArr}, 7); });
out.push("seen " + seen.length);
function privUpd() { class P { #c = 0; bump() { this.#c++; ++this.#c; this.#c += 2; return this.#c; } } return new P().bump(); }
rep("privUpd", privUpd);
function optPriv() { class Q { #m() { return 4; } t(o) { return o?.#m(); } } return new Q().t(new Q()); }
rep("optPriv", optPriv);
function optSpread(o, a) { return o?.m(...a); }
rep("optSpread", optSpread, {m(x, y) { return x * y; }}, [3, 4]);
function optNoShort(o) { return (o?.a).b; }
rep("optNoShort", optNoShort, {a: {b: 1}});
function superCall() { class A { constructor(v) { this.v = v; } } class B extends A { constructor() { super(3); } } return new B().v; }
rep("superCall", superCall);
function superProp() { class A { m() { return 2; } } class B extends A { m() { return super.m() + 1; } n() { super.x = 5; return this.x; } } const b = new B(); return [b.m(), b.n()]; }
rep("superProp", superProp);
function usingDecl() { { using u = null; } return 1; }
rep("usingDecl", usingDecl);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_destructuring_labels_and_optional_chains(run, tier):
    """CATCHES: compiled tiers that mishandle var/let destructuring with rest, defaults, number keys and nested patterns, continue in do-while, labelled break/continue across nested for-of/for loops, captured assignment expressions, spread calls through locals, element stores rejected by read-only elements or prototype setters, private-field updates, optional private calls, spread in optional calls and super property access."""
    check_prog(run, tier, PROG_MORE_SHAPES, "more_shapes")


PROG_NAME_CACHES = r"""
var out = [];
Object.defineProperty(globalThis, "accG", { get() { return 41; }, configurable: true });
function readAcc() { let s = 0; for (let i = 0; i < 5; i++) s += accG; return s; }
for (let i = 0; i < 40; i++) readAcc();
out.push("acc " + readAcc());
globalThis.plainG = 1;
function readPlain() { return plainG; }
for (let i = 0; i < 40; i++) readPlain();
Object.defineProperty(globalThis, "plainG", { get() { return 2; }, configurable: true });
out.push("toAcc " + readPlain());
globalThis.other1 = 1; globalThis.other2 = 2;
out.push("shape " + readPlain());
delete globalThis.plainG;
globalThis.plainG = 3;
out.push("readd " + readPlain());
function readTdz() { return laterLet; }
let tdzCount = 0;
for (let i = 0; i < 40; i++) { try { readTdz(); } catch (e) { tdzCount++; } }
let laterLet = 9;
out.push("tdz " + tdzCount + " " + readTdz());
function outerEval(code) {
  var base = 1;
  function inner() { let c = 0; const g = () => c++; g(); return typeof zz === "undefined" ? "none:" + base : zz + c; }
  let r = [];
  for (let i = 0; i < 40; i++) inner();
  r.push(inner());
  eval(code);
  r.push(inner());
  for (let i = 0; i < 40; i++) inner();
  r.push(inner());
  return r.join(",");
}
out.push("eval " + outerEval("var zz = 'Z'"));
var wobj = { wx: 5 };
with (wobj) { var wf = function () { let t = 0; for (let i = 0; i < 3; i++) t += wx; return t; }; }
for (let i = 0; i < 40; i++) wf();
wobj.wx = 6;
out.push("with " + wf());
function shadowLater() { return sv; }
var sv = "global";
for (let i = 0; i < 40; i++) shadowLater();
globalThis.sv = "changed";
out.push("shadow " + shadowLater());
function outer2() {
  let cnt = 0;
  function inc() { cnt += 1; const h = () => cnt; return h(); }
  for (let i = 0; i < 40; i++) inc();
  return inc();
}
out.push("depth1 " + outer2() + " " + outer2());
console.log(out.join("\n"));
var out = [];
function capTdz() { var r = []; try { r.push(x); } catch (e) { r.push(e.name); } try { x = 2; } catch (e) { r.push(e.name); } let x = 1; const g = () => x; return r.join() + g(); }
var ct; for (var i = 0; i < 50; i++) ct = capTdz(); out.push("capTdz " + ct);
function outer(n) {
  var total = 0, hits = 0;
  function add(x) { const f = () => x; total = total + f(); hits = hits + 1; return total; }
  for (var k = 0; k < n; k++) add(k);
  return total + "/" + hits;
}
var ot; for (var i = 0; i < 30; i++) ot = outer(20); out.push("depth1 " + ot);
var gw = 0;
function storeG(v) { gw = v; return gw; }
for (var i = 0; i < 50; i++) storeG(i);
globalThis.newGlobalProp1 = 1;
out.push("afterShape " + storeG(7) + " " + gw);
for (var i = 0; i < 50; i++) storeG(i);
Object.defineProperty(globalThis, "gw", { writable: false });
out.push("readonly " + storeG(99) + " " + gw);
globalThis.gacc = 0;
function storeAcc(v) { gacc = v; return gacc; }
for (var i = 0; i < 50; i++) storeAcc(i);
var accSeen = [];
Object.defineProperty(globalThis, "gacc", { set(v) { accSeen.push(v); }, get() { return -1; }, configurable: true });
out.push("accessor " + storeAcc(5) + " " + accSeen.join());
let lexG = 0;
function storeLex(v) { lexG = v; return lexG; }
for (var i = 0; i < 50; i++) storeLex(i);
out.push("lex " + storeLex(3));
const constG = 1;
function storeConst() { try { constG = 2; } catch (e) { return e.name; } return "no"; }
var sc; for (var i = 0; i < 50; i++) sc = storeConst(); out.push("const " + sc);
function storeUndeclared(v) { undeclaredSloppy = v; return undeclaredSloppy; }
for (var i = 0; i < 50; i++) storeUndeclared(i);
out.push("undeclared " + storeUndeclared(11) + " " + globalThis.undeclaredSloppy);
function storeStrictUndeclared(v) { "use strict"; try { undeclaredStrict = v; } catch (e) { return e.name; } return "no"; }
var ss; for (var i = 0; i < 50; i++) ss = storeStrictUndeclared(i); out.push("strictUndeclared " + ss);
function makeCounter() {
  let count = 0;
  function bump() { let local = 0; const c = () => local; count = count + 1; return count + c(); }
  return bump;
}
var b1 = makeCounter(), b2 = makeCounter();
for (var i = 0; i < 50; i++) { b1(); if (i % 2) b2(); }
out.push("counters " + b1() + " " + b2());
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_free_name_caches(run, tier):
    """CATCHES: stale free-name inline caches that keep returning or writing an old global binding after it becomes an accessor, read-only, re-added or shadowed, that skip TDZ for captured lets, or that write the wrong outer-function activation from an inner compiled closure."""
    check_prog(run, tier, PROG_NAME_CACHES, "name_caches")


PROG_REGEXP_GUARDS = r"""
var out = [];
function st(tag) { out.push(tag + " $1=" + RegExp.$1 + " last=" + RegExp.lastMatch + " li=" + reG.lastIndex); }
var reA = /a(\d)/;
var reG = /b(\d)/g;
var strs = [];
for (var k = 0; k < 12; k++) strs.push("xa" + k + "b" + (k % 7));
var arrLike = {0: "a1", 1: "a2", 2: "a3", 3: "a4", length: 4};
var holey = ["a5", , "a6", "a7"];
var mixed = ["a8", 9, "a0", "a1"];
var acc = ["a2", "a3", "a4", "a5"];
Object.defineProperty(acc, 1, { get() { return "a9"; } });
function loopLimitFrac() { for (var i = 0; i < 2.5; i++) reA.exec(strs[i]); return i; }
function loopLimitHuge() { for (var i = 0; i < 1e12; i++) { reA.exec(strs[i]); if (i > 3) break; } return i; }
function loopStartFrac() { for (var i = 0.5; i < 4; i++) reA.exec(strs[i]); return i; }
function loopStartPast() { for (var i = 9; i < 4; i++) reA.exec(strs[i]); return i; }
function loopStartStr() { for (var i = "1"; i < 4; i++) reA.exec(strs[i]); return i; }
function loopArrLike() { for (var i = 0; i < 4; i++) reA.exec(arrLike[i]); return i; }
function loopG() { for (var i = 0; i < 4; i++) reG.exec(strs[i]); return i; }
var strsHole = holey, strsMixed = mixed, strsAcc = acc;
function loopHole() { for (var i = 0; i < 4; i++) reA.exec(strsHole[i]); return i; }
function loopMixed() { for (var i = 0; i < 4; i++) reA.exec(strsMixed[i]); return i; }
function loopAcc() { for (var i = 0; i < 4; i++) reA.exec(strsAcc[i]); return i; }
var strsStr = "a1a2";
function loopStrPrim() { for (var i = 0; i < 4; i++) reA.exec(strsStr[i]); return i; }
var reObj = { exec(s) { return null; } };
function loopNotRe() { for (var i = 0; i < 4; i++) reObj.exec(strs[i]); return i; }
var reOwn = /a(\d)/; var ownCalls = 0; reOwn.exec = function (s) { ownCalls++; return null; };
function loopOwn() { for (var i = 0; i < 2; i++) reOwn.exec(strs[i]); return i; }
var reSub = Object.setPrototypeOf(/a(\d)/, Object.create(RegExp.prototype));
function loopSub() { for (var i = 0; i < 4; i++) reSub.exec(strs[i]); return i; }
var reLiFrac = /b(\d)/g;
function loopLiFrac() { for (var i = 0; i < 4; i++) reLiFrac.exec(strs[i]); return i; }
var reLiRO = /b(\d)/g;
function loopLiRO() { for (var i = 0; i < 4; i++) reLiRO.exec(strs[i]); return i; }
function litLoopArrLike() { for (var i = 0; i < 4; i++) { /a(\d)/.exec(arrLike[i]); } return i; }
function litLoopMixed() { for (var i = 0; i < 4; i++) { /a(\d)/.exec(strsMixed[i]); } return i; }
function litLoopAcc() { for (var i = 0; i < 4; i++) { /a(\d)/.exec(strsAcc[i]); } return i; }
function litLoopFrac() { for (var i = 0.5; i < 4; i++) { /a(\d)/.exec(strs[i]); } return i; }
function litLoopStrPrim() { for (var i = 0; i < 4; i++) { /a(\d)/.exec(strsStr[i]); } return i; }
function litConstNum() { /a(\d)/.exec(42); return RegExp.lastMatch; }
function repLoopArrLike() { for (var i = 0; i < 4; i++) arrLike[i].replace(/a(\d)/, "-"); return i; }
function repLoopMixed() { for (var i = 0; i < 4; i++) String(strsMixed[i]).replace(/a(\d)/, "-"); return i; }
function repLoopAcc() { for (var i = 0; i < 4; i++) strsAcc[i].replace(/a(\d)/, "-"); return i; }
function repLoopFrac() { for (var i = 0.5; i < 4; i++) { var s = strs[i]; if (s) s.replace(/a(\d)/, "-"); } return i; }
function repFn() { for (var i = 0; i < 4; i++) strs[i].replace(/a(\d)/, function (m, d) { return d; }); return i; }
function repDollar() { for (var i = 0; i < 4; i++) strs[i].replace(/a(\d)/, "$1$&"); return i; }
function matchLoopArrLike() { for (var i = 0; i < 4; i++) arrLike[i].match(/a(\d)/); return i; }
function matchLoopAcc() { for (var i = 0; i < 4; i++) strsAcc[i].match(/a(\d)/); return i; }
function matchLoopG() { for (var i = 0; i < 4; i++) strs[i].match(/a(\d)/g); return i; }
function matchLoopY() { for (var i = 0; i < 4; i++) strs[i].match(/a(\d)/y); return i; }
var fns = [loopLimitFrac, loopLimitHuge, loopStartFrac, loopStartPast, loopStartStr, loopArrLike, loopG, loopHole, loopMixed, loopAcc, loopStrPrim, loopNotRe, loopOwn, loopSub,
  litLoopArrLike, litLoopMixed, litLoopAcc, litLoopFrac, litLoopStrPrim, litConstNum, repLoopArrLike, repLoopMixed, repLoopAcc, repLoopFrac, repFn, repDollar, matchLoopArrLike, matchLoopAcc, matchLoopG, matchLoopY];
for (var r = 0; r < 30; r++) {
  if (r === 10) { reLiFrac.lastIndex = 1.5; Object.defineProperty(reLiRO, "lastIndex", { writable: false }); }
  for (var f = 0; f < fns.length; f++) {
    var res;
    try { res = fns[f](); } catch (e) { res = "E:" + e.name; }
    if (r === 29) st(fns[f].name + "=" + res);
  }
  if (r >= 10) { try { loopLiFrac(); } catch (e) { out.push("lifrac " + e.name); } try { loopLiRO(); } catch (e) { if (r === 29) out.push("liro " + e.name); } }
}
var origExec = RegExp.prototype.exec;
Object.defineProperty(RegExp.prototype, "exec", { get() { return origExec; }, configurable: true });
for (var r = 0; r < 5; r++) { loopG(); litLoopMixed(); }
st("accessorExec");
Object.defineProperty(RegExp.prototype, "exec", { value: origExec, writable: true, configurable: true });
RegExp.prototype.exec = 7;
try { loopG(); } catch (e) { out.push("execNum " + e.name); }
RegExp.prototype.exec = origExec;
for (var r = 0; r < 5; r++) loopG();
st("restored"); out.push("ownCalls " + ownCalls);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_regexp_loop_guard_declines(run, tier):
    """CATCHES: a JIT batched regexp exec/replace/match loop fast path that runs when its guards should decline (fractional or string loop bounds, array-likes, holes, accessor elements, own/overridden/accessor exec, sticky/global lastIndex states) and so loses RegExp.$1/lastMatch updates or exceptions."""
    check_prog(run, tier, PROG_REGEXP_GUARDS, "regexp_guards")


PROG_INTRINSICS = r"""
var out = [];
function sliceAll(s) {
  var r = [];
  var bounds = [[-3, -1], [-Infinity, Infinity], [NaN, 2], [2, NaN], [Infinity, -Infinity], [-100, 3], [1, 100], [4, 2], [0.7, 3.9], [-2.5, -0.5]];
  for (var k = 0; k < bounds.length; k++) r.push(s.slice(bounds[k][0], bounds[k][1]));
  return r.join("|");
}
var sres;
for (var i = 0; i < 60; i++) sres = sliceAll("abcdefgh");
out.push("slice " + sres);
function charAll(s) { var r = ""; var idx = [0, -1, 2.7, NaN, 100, Infinity, -0, 7]; for (var k = 0; k < idx.length; k++) r += "[" + s.charAt(idx[k]) + "]"; return r; }
var cres; for (var i = 0; i < 60; i++) cres = charAll("wxyz1234"); out.push("charAt " + cres);
function hasAll(o) { var r = 0; var keys = ["a", "b", "toString", "c"]; for (var k = 0; k < keys.length; k++) if (Object.hasOwn(o, keys[k])) r += 1 << k; return r; }
var hres; for (var i = 0; i < 60; i++) hres = hasAll({a: 1, c: 3}); out.push("hasOwn " + hres + " " + hasAll(Object.create({a: 1})) + " " + hasAll([1]));
function sum3(a, b, c) { return (this && this.base || 0) + a + b + c; }
function applyMany() {
  var r = [];
  var base = {base: 100};
  r.push(sum3.apply(base, [1, 2, 3]));
  r.push(Math.max.apply(Math, [4, 9, 2]));
  r.push(String.prototype.concat.apply(base, ["x", "y"]));
  r.push(sum3.apply(base, {length: 3, 0: 1, 1: 1, 2: 1}));
  var holey = [1, , 3]; r.push(sum3.apply(base, holey));
  var withAcc = [1, 2, 3]; Object.defineProperty(withAcc, 1, {get() { return 50; }}); r.push(sum3.apply(base, withAcc));
  var lenAcc = {0: 5, 1: 5, 2: 5}; Object.defineProperty(lenAcc, "length", {get() { return 3; }}); r.push(sum3.apply(base, lenAcc));
  r.push(sum3.apply(base, {length: 2.5, 0: 1, 1: 2}));
  r.push(sum3.apply(base, {length: -1}));
  (function () { r.push(sum3.apply(base, arguments)); })(7, 8, 9);
  r.push(sum3.apply(base, new Proxy([1, 2, 3], {})));
  return r.join(",");
}
var ares; for (var i = 0; i < 60; i++) ares = applyMany(); out.push("apply " + ares);
function pushPop(a) { for (var k = 0; k < 5; k++) a.push(k * 2); var s = 0; for (var k = 0; k < 3; k++) s += a.pop(); return s + ":" + a.length; }
var pres; for (var i = 0; i < 60; i++) pres = pushPop([]);
out.push("pushPop " + pres + " " + pushPop(Object.freeze([1, 2]).slice()) + " " + pushPop({length: 0, push: Array.prototype.push, pop: Array.prototype.pop}));
var frozen = Object.freeze([1, 2]);
function pushFrozen() { try { frozen.push(3); return "no"; } catch (e) { return e.name; } }
var pf; for (var i = 0; i < 60; i++) pf = pushFrozen(); out.push("pushFrozen " + pf);
var sealedPop = Object.seal([1, 2, 3]);
function popSealed() { try { return sealedPop.pop(); } catch (e) { return e.name; } }
var ps; for (var i = 0; i < 60; i++) ps = popSealed(); out.push("popSealed " + ps + " " + sealedPop.length);
var nonWritLen = [1, 2, 3]; Object.defineProperty(nonWritLen, "length", {writable: false});
function pushNW() { try { nonWritLen.push(9); return "ok"; } catch (e) { return e.name; } }
function popNW() { try { nonWritLen.pop(); return "ok"; } catch (e) { return e.name; } }
var pn; for (var i = 0; i < 60; i++) pn = pushNW() + popNW(); out.push("nonWritable " + pn + " " + nonWritLen.join());
var reX = /q(\d)/g, reY = /q(\d)/y, reN = /q(?<d>\d)/;
function execDiscard(s) { reX.exec(s); reY.exec(s); reN.exec(s); return reX.lastIndex + "/" + reY.lastIndex + "/" + RegExp.$1; }
var ed; for (var i = 0; i < 60; i++) ed = execDiscard("aq1q2q3"); out.push("execDiscard " + ed);
function splitDiscard(s) { s.split(","); s.split(/;/); s.split(""); return RegExp.lastMatch; }
var sd; for (var i = 0; i < 60; i++) sd = splitDiscard("a,b;c"); out.push("splitDiscard " + sd);
function replaceDiscard(s) { s.replace("a", "b"); s.replace(/b(.)/, "$1"); s.replace(/c/g, () => "d"); return RegExp.lastMatch; }
var rd; for (var i = 0; i < 60; i++) rd = replaceDiscard("abcabc"); out.push("replaceDiscard " + rd);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_builtin_intrinsic_edge_cases(run, tier):
    """CATCHES: JIT intrinsics for String#slice/charAt, Object.hasOwn, Function#apply, Array push/pop and discarded exec/split/replace that mis-normalize negative/NaN/infinite bounds, ignore array-like or accessor argument lists, or bypass frozen/sealed/non-writable-length TypeErrors."""
    check_prog(run, tier, PROG_INTRINSICS, "intrinsics")


PROG_INITIALIZERS = r"""
var Class = { create: function () { return function () { this.initialize.apply(this, arguments); }; } };
var out = [];
function mk(init) { var C = Class.create(); C.prototype = { initialize: init, sum: function () { var s = ""; for (var k in this) if (typeof this[k] !== "function") s += k + "=" + this[k] + ";"; return s; } }; return C; }
var inits = {
  ternary: function (a, b) { this.x = a ? a : 0; this.y = b ? b : 1; },
  ifDefault: function (a, b) { if (!a) a = 5; if (!b) b = 6; this.x = a; this.y = b; },
  duplicate: function (a) { this.x = a; this.y = a; },
  computed: function (a) { this.x = a + 1; },
  varReset: function (a) { for (var a in {p: 1}) {} this.x = a; },
  mixedTernary: function (a, b) { this.x = a ? b : 0; },
  defaultOther: function (a, b) { if (!a) b = 1; this.x = a; this.y = b; },
  empty: function () {},
  ternaryThenConst: function (a) { this.x = a ? a : 0; this.z = 3; },
  nonParam: function (a) { var t = a; this.x = t; },
  dupDefault: function (a) { if (!a) a = 1; if (!a) a = 2; this.x = a; },
  manyFields: function (a, b, c, d, e, f, g, h, i) { this.a = a; this.b = b; this.c = c; this.d = d; this.e = e; this.f = f; this.g = g; this.h = h; this.i = i; },
  usesArgs: function () { this.n = arguments.length; },
  captures: function (a) { this.x = a; this.f2 = () => a; },
  varReset2: function (a) { for (var a = 0; a < 1; a++) {} this.x = a; },
  dupTernary: function (a) { this.x = a ? a : 0; this.y = a ? a : 1; },
};
var classes = {};
for (var name in inits) classes[name] = mk(inits[name]);
function build(C, r) { var o1 = new C(r % 3, r % 2 ? "s" : 0, 3, 4, 5, 6, 7, 8, 9); var o2 = new C(); return [o1, o2]; }
function buildMany(C) { var last; for (var r = 0; r < 60; r++) last = build(C, r); return last; }
for (var name in classes) { var p = buildMany(classes[name]); out.push(name + " " + p[0].sum() + " | " + p[1].sum()); }
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_initializer_forwarding_constructors(run, tier):
    """CATCHES: the this.initialize.apply(this, arguments) constructor shortcut applying a field plan for initializers that use computed values, duplicate parameters, defaults on other parameters, var resets, arguments or closures, producing wrong fields or defaults."""
    check_prog(run, tier, PROG_INITIALIZERS, "initializers")


PROG_INLINE_RECOMPILE = r"""
var out = [];
var K = 3;
function two(a, b) { return a * 10 + b; }
function usesK(a) { return a + K; }
function bare(a) { if (a > 2) return; return a; }
function useThis(a) { return this === undefined ? a : -a; }
function nine(a, b) { return a + b; }
var arrow = (a) => a + 1;
function notCompiled(a) { try { return a; } finally { a++; } }
function hoistVar(a) { var a; var t = a * 2; return t; }
function callerA(n) {
  var s = 0, K = 100;
  for (var i = 0; i < n; i++) {
    s += two(i) || 0.5;
    s += two(i, 1, 2, 3);
    s += usesK(i);
    var b = bare(i); s += b === undefined ? 1000 : b;
    s += useThis(i);
    s += nine(1, 2, 3, 4, 5, 6, 7, 8, 9);
    s += arrow(i);
    s += notCompiled(i);
    s += hoistVar(i);
  }
  return s;
}
function makeCaller() {
  return function callerB(n) { var s = 0; for (var i = 0; i < n; i++) { s += two(i, i); s += usesK(i); } return s; };
}
var callerB = makeCaller();
var objM = { m(a) { return a * 2; }, n(a, b) { return this.m(a) + b; } };
function callerC(n) { var s = 0; for (var i = 0; i < n; i++) { s += objM.n(i, 1); s += objM["m"](i); } return s; }
function drive(f, reps) { var last; for (var r = 0; r < reps; r++) last = f(6); return last; }
for (var k = 0; k < 3; k++) { out.push("A " + drive(callerA, 150)); out.push("B " + drive(callerB, 150)); out.push("C " + drive(callerC, 150)); }
two = function (a, b) { return -1; };
out.push("swapped " + drive(callerA, 5) + " " + drive(callerB, 5));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_inline_recompile_call_shapes(run, tier):
    """CATCHES: hot-callee inlining that binds surplus/missing arguments wrongly, splices callees whose globals are shadowed by caller locals, mishandles bare returns, this-using or computed-key method callees, or keeps calling the inlined body after the global callee is reassigned."""
    check_prog(run, tier, PROG_INLINE_RECOMPILE, "inline_recompile")


PROG_ARRAY_ITERATION = r"""
var out = [];
var AIP = Object.getPrototypeOf([][Symbol.iterator]());
function d2(a) { let [x, y] = a; return String(x) + "," + String(y); }
function d3(a) { let [x, , z] = a; return String(x) + "," + String(z); }
function d17(a) { let [a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16, a17] = a; return a1 + a17; }
function spread(a) { return [].concat(...a).length + ":" + Math.max(...a); }
function sum4(a, b, c, d) { return a + b + c + d; }
function spreadCall(a) { return sum4(...a); }
function forOf(a) { let s = ""; for (const v of a) s += v; return s; }
function run(label, f, v) { let r; for (let k = 0; k < 30; k++) { try { r = f(v); } catch (e) { r = "E:" + e.name; } } out.push(label + " " + r); }
function suite(tag, v, noSpread) { run(tag + ".d2", d2, v); run(tag + ".d3", d3, v); if (!noSpread) run(tag + ".spreadCall", spreadCall, v); run(tag + ".forOf", forOf, v); }
var long = []; for (var k = 0; k < 20; k++) long.push(k);
run("d17", d17, long);
run("spreadLong", spread, long);
suite("plain", [1, 2, 3, 4]);
suite("short", [1]);
suite("str", "wxyz");
suite("holey", [1, , 3, 4]);
var acc = [1, 2, 3, 4]; Object.defineProperty(acc, 1, { get() { return 20; } });
suite("accessor", acc);
var ownIter = [1, 2, 3, 4]; ownIter[Symbol.iterator] = function* () { yield 9; yield 8; yield 7; yield 6; };
suite("ownIter", ownIter, true);
var deep = [5, 6, 7, 8]; var p = Array.prototype; for (var k = 0; k < 9; k++) p = Object.create(p); Object.setPrototypeOf(deep, p);
suite("deepProto", deep);
var proxied = [1, 2, 3, 4]; Object.setPrototypeOf(proxied, new Proxy(Array.prototype, {}));
suite("proxyProto", proxied);
suite("typed", new Int16Array([3, 4, 5, 6]));
suite("keys", [7, 8, 9].keys());
suite("entries", ["a", "b"].entries());
suite("set", new Set([1, 2, 3, 4]));
suite("args", (function () { return arguments; })(1, 2, 3, 4));
var origReturn = AIP.return;
AIP.return = function () { out.push("return called"); return {}; };
suite("withReturn", [1, 2, 3, 4]);
delete AIP.return;
var origNext = AIP.next;
var nexts = 0;
AIP.next = function () { nexts++; return origNext.call(this); };
suite("patchedNext", [1, 2, 3, 4], true);
AIP.next = origNext;
out.push("nexts " + nexts);
var origValues = Array.prototype[Symbol.iterator];
Array.prototype[Symbol.iterator] = function () { return origValues.call([0, 0, 0, 0]); };
suite("patchedValues", [1, 2, 3, 4], true);
Array.prototype[Symbol.iterator] = origValues;
Object.defineProperty(Array.prototype, Symbol.iterator, { get() { return origValues; }, configurable: true });
suite("accessorValues", [1, 2, 3, 4]);
Object.defineProperty(Array.prototype, Symbol.iterator, { value: origValues, writable: true, configurable: true });
suite("restored", [1, 2, 3, 4]);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_array_destructuring_and_spread_guards(run, tier):
    """CATCHES: scalar-replaced array destructuring, spread-call and for-of iteration shortcuts that ignore holes, accessors, own or patched Symbol.iterator/next/return, long prototype chains, proxies, typed arrays, key/entry iterators and Sets."""
    check_prog(run, tier, PROG_ARRAY_ITERATION, "array_iteration")


PROG_MISC_SHAPES = r"""
var out = [];
function rep(label, f, a, b) { var r; for (var i = 0; i < 40; i++) { try { r = f(a, b); } catch (e) { r = "E:" + e.name; } } out.push(label + " " + JSON.stringify(r)); }
function hoistFnDefault(a = 1) { function a() { return "fn"; } const g = () => typeof a; return g(); }
rep("hoistFnDefault", hoistFnDefault);
function holeDefault(a = [1, , 3]) { return a.length + ":" + (1 in a); }
rep("holeDefault", holeDefault);
function seqDefault(a = (0, 7)) { return a; }
rep("seqDefault", seqDefault);
function templDefault(a = `t${1 + 1}`) { return a; }
rep("templDefault", templDefault);
function capParenDefault(a = (5)) { return () => a; }
rep("capParenDefault", function () { return capParenDefault()(); });
function capArrDefault(a = [1]) { return () => a.length; }
rep("capArrDefault", function () { return capArrDefault()(); });
function capObjDefault(a = {}) { return () => typeof a; }
rep("capObjDefault", function () { return capObjDefault()(); });
function capNullDefault(a = null, b = 2n, c = "s", d = true, e = undefined) { return () => [a, String(b), c, d, e === undefined]; }
rep("capNullDefault", function () { return capNullDefault()(); });
function forInCap(o) { var fs = []; for (let k in o) fs.push(() => k); return fs.map(f => f()).join(); }
rep("forInCap", forInCap, {a: 1, b: 2, c: 3});
function forInCtl(o) { var s = ""; for (const k in o) { if (k === "b") continue; if (k === "d") break; s += k; } return s; }
rep("forInCtl", forInCtl, {a: 1, b: 2, c: 3, d: 4, e: 5});
function forInLabel(o) { var s = ""; outer: for (const k in o) { for (const j in o) { if (j === k) continue outer; if (j > "c") break outer; s += k + j; } } return s; }
rep("forInLabel", forInLabel, {a: 1, b: 2, c: 3, d: 4});
function forInDelete(o) { var s = ""; for (const k in o) { delete o.c; s += k; } return s; }
rep("forInDelete", function () { return forInDelete({a: 1, b: 2, c: 3}); });
function protoLit(p) { return Object.getPrototypeOf({__proto__: p, x: 1}) === p; }
rep("protoLit", protoLit, Array.prototype);
function computedLit(v) { return {["k"]: v, [("q")]: v + 1, "s": v + 2}; }
rep("computedLit", computedLit, 1);
function computedNonConst(v) { var k = "dyn"; return {[k]: v}; }
rep("computedNonConst", computedNonConst, 4);
function dupLit(v) { return {a: v, b: 2, a: v + 1}; }
rep("dupLit", dupLit, 5);
function methodLit(v) { return {m() { return v; }, get g() { return v * 2; }}.g; }
rep("methodLit", methodLit, 6);
function spreadLit(o) { return {...o, z: 1}; }
rep("spreadLit", spreadLit, {y: 2});
function arrowThis() { const f = () => this && this.tag; return f(); }
rep("arrowThis", function () { return arrowThis.call({tag: "T"}); });
function nestedArrowThis() { return (() => (() => this.tag)())(); }
rep("nestedArrowThis", function () { return nestedArrowThis.call({tag: "N"}); });
function argsUse() { var s = 0; for (var i = 0; i < arguments.length; i++) s += arguments[i]; return s; }
rep("argsUse", function () { return argsUse(1, 2, 3); });
function argsArrow(a) { return arguments.length; }
rep("argsArrow", function () { return argsArrow(1, 2); });
function newTarget() { return new.target === undefined; }
rep("newTarget", newTarget);
var namedExpr = function nm(n) { return n <= 0 ? "done" : nm(n - 1); };
rep("namedExpr", namedExpr, 3);
function restParam(...r) { return r.length; }
rep("restParam", restParam, 1, 2);
function destrParam({a}, [b]) { return a + b; }
rep("destrParam", destrParam, {a: 1}, [2]);
function* gen() { yield 1; }
rep("gen", function () { return [...gen()]; });
function labeledBlock(n) { var s = 0; blk: { if (n > 1) break blk; s = 1; } return s; }
rep("labeledBlock", labeledBlock, 2);
function switchFall(n) { var s = ""; switch (n) { case 1: s += "a"; case 2: s += "b"; break; default: s += "d"; } return s; }
rep("switchFall", switchFall, 1);
function tryCatchFinally(n) { var s = ""; try { if (n) throw new Error("x"); s += "t"; } catch (e) { s += "c"; } finally { s += "f"; } return s; }
rep("tryCatchFinally", tryCatchFinally, 1);
function withStmt(o) { with (o) { return p; } }
rep("withStmt", withStmt, {p: 8});
function evalDirect(s) { return eval(s); }
rep("evalDirect", evalDirect, "1+2");
function nestedEval() { var q = 5; return (function () { return eval("q"); })(); }
rep("nestedEval", nestedEval);
function classInFn(v) { class K { constructor(x) { this.x = x; } get d() { return this.x * 2; } } return new K(v).d; }
rep("classInFn", classInFn, 4);
function classFieldDefault(v) { class K2 { f = v + 1; static s = 3; } return new K2().f + K2.s; }
rep("classFieldDefault", classFieldDefault, 4);
function taggedTpl(v) { const tag = (s, ...x) => s.raw.join("|") + x.join(","); return tag`a${v}b${v + 1}c`; }
rep("taggedTpl", taggedTpl, 1);
function optChainCall(o) { return [o?.f?.(), o?.["g"]?.(1), o.h?.k, o?.a.b.c]; }
rep("optChainCall", optChainCall, {f() { return 1; }, g: undefined, h: null, a: {b: {c: 4}}});
function optChainDelete(o) { return delete o?.x; }
rep("optChainDelete", optChainDelete, {x: 1});
function deleteIdent() { var v = 1; return typeof v; }
rep("deleteIdent", deleteIdent);
function superLess() { const o = { m() { return super.toString === Object.prototype.toString; } }; return o.m(); }
rep("superLess", superLess);
function voidTypeof(x) { return [void x, typeof x, typeof undeclaredX, -x, +x, ~x, !x]; }
rep("voidTypeof", voidTypeof, "3");
function inOps(o) { return ["a" in o, o instanceof Object, 1 in [5, 6]]; }
rep("inOps", inOps, {a: 1});
function bigintOps(a) { return String(a * 3n + 1n) + (a > 1n) + (-a) + (a ** 2n) + (a % 3n) + (~a); }
rep("bigintOps", bigintOps, 5n);
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_misc_function_shapes(run, tier):
    """CATCHES: compiled tiers that mishandle defaulted parameters shadowed by hoisted functions, captured for-in bindings, for-in continue/break/labels, object literals with __proto__/computed/duplicate keys, lexical this in arrows, arguments, named function expressions, with/eval, classes, tagged templates and optional chains."""
    check_prog(run, tier, PROG_MISC_SHAPES, "misc_shapes")


PROG_CALL_HELPERS = r"""
var out = [];
function thrower(i) { return [i, i * 2, i > 45 ? i.foo.bar : 0].length; }
function callThrower(n) { var s = 0, caught = 0; for (var i = 0; i < n; i++) { try { s += thrower(i); } catch (e) { caught++; } } return s + ":" + caught; }
out.push("thrower " + callThrower(50) + " " + callThrower(50));
function depth(n) { return n === 0 ? 0 : 1 + depth(n - 1); }
function deepMany() { var s = 0; for (var k = 0; k < 5; k++) s += depth(120); return s; }
out.push("depth " + deepMany() + " " + deepMany());
function freshCalls(n) { var s = 0; for (var i = 0; i < n; i++) { s += (function (x) { return x + 1; })(i); s += ((y) => y * 2)(i); } return s; }
out.push("fresh " + freshCalls(60));
function boundCalls(n) { var s = 0; for (var i = 0; i < n; i++) { s += Math.max.bind(null, i)(1); s += String.prototype.charCodeAt.bind("abc")(i % 3); } return s; }
out.push("bound " + boundCalls(60));
function nullish(n) { var s = 0; var vals = [null, undefined, 0, "", false, NaN, {}, 5]; for (var i = 0; i < n; i++) { var v = vals[i % 8]; s += (v ?? 1) === 1 ? 1 : 0; s += (v || 2) === 2 ? 10 : 0; s += (v && 3) === 3 ? 100 : 0; } return s; }
out.push("nullish " + nullish(80));
function capInit(n) { var fs = []; for (var i = 0; i < n; i++) { let k = i * 2; fs.push(() => k); } return fs.reduce((a, f) => a + f(), 0); }
out.push("capInit " + capInit(30) + " " + capInit(30));
function blockLets(n) { var s = 0; for (var i = 0; i < n; i++) { { let a = i; const b = a + 1; s += b; } } return s; }
out.push("blockLets " + blockLets(50));
function keyLocal(n) { var o = {}; var keys = [{toString() { return "p"; }}, "q", 1, true]; for (var i = 0; i < n; i++) { var k = keys[i % 4]; o[k] = (o[k] | 0) + 1; o[k] += 1; } return JSON.stringify(o); }
out.push("keyLocal " + keyLocal(40));
function keyLocalNull(n) { var a = null, caught = 0; for (var i = 0; i < n; i++) { try { a[{}] += 1; } catch (e) { caught++; } } return caught; }
out.push("keyLocalNull " + keyLocalNull(20));
function setElemGeneric(n) { var o = {length: 0}; var r = []; for (var i = 0; i < n; i++) { r.push(o[i % 3] = i); o["k" + (i % 2)] = i; } return r.length + JSON.stringify(o); }
out.push("setElemGeneric " + setElemGeneric(30));
function getMethodElem(n) { var o = {m0(x) { return x; }, 1: (x) => x * 2}; var s = 0; var ks = ["m0", 1, "m0", "1"]; for (var i = 0; i < n; i++) s += o[ks[i % 4]](i); return s; }
out.push("getMethodElem " + getMethodElem(40));
function instanceLoop(n) { var C = function () {}; var objs = [new C(), {}, [], new Date(0), null, 3]; var s = 0; for (var i = 0; i < n; i++) { var v = objs[i % 6]; if (v instanceof C) s += 1; if (v instanceof Object) s += 10; } return s; }
out.push("instanceof " + instanceLoop(60));
function instanceBad(n) { var c = 0; for (var i = 0; i < n; i++) { try { if ({} instanceof (i % 2 ? Object : 5)) c++; } catch (e) { c += 100; } } return c; }
out.push("instanceBad " + instanceBad(10));
function hasInstance(n) { var Even = { [Symbol.hasInstance](v) { return v % 2 === 0; } }; var c = 0; for (var i = 0; i < n; i++) if (i instanceof Even) c++; return c; }
out.push("hasInstance " + hasInstance(20));
function undefOps(n) { var s = []; for (var i = 0; i < n; i++) { var u; s.push(u === undefined, void i); } return s.length; }
out.push("undef " + undefOps(10));
function newInLoop(n) { function P(x) { this.x = x; } var s = 0; for (var i = 0; i < n; i++) { s += new P(i).x; var Q = function (y) { this.y = y; }; s += new Q(1).y; } return s; }
out.push("new " + newInLoop(50));
function makeObjArr(n) { var r = 0; for (var i = 0; i < n; i++) { var o = {a: i, b: [i, i + 1], c: {d: i}}; r += o.a + o.b[1] + o.c.d; var dup = {a: 1, a: 2}; r += dup.a; } return r; }
out.push("makeObj " + makeObjArr(40));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_jit_call_and_element_helpers(run, tier):
    """CATCHES: JIT call/element helpers that leak or mis-drop operands when a direct callee throws mid-expression, recurse deeper than the frame pool, call fresh closures or bound natives, evaluate ??/||/&& on every falsy kind, rebind per-iteration block lets, coerce object keys, or route instanceof through Symbol.hasInstance incorrectly."""
    check_prog(run, tier, PROG_CALL_HELPERS, "call_helpers")


PROG_PROPERTY_CHAINS = r"""
var out = [];
function P(x, vx) { this.x = x; this.vx = vx; this.n = 0; }
P.prototype.step = function (k) { this.x = this.x + this.vx * k; this.n = this.n + 1; return this.x; };
function local(o, k) { o.x = o.x - o.vx * k; o.n = o.n + 1; return o.x; }
function drive(objs, rounds) { var s = 0; for (var r = 0; r < rounds; r++) for (var i = 0; i < objs.length; i++) { s += objs[i].step(0.5); s += local(objs[i], 0.25); } return s; }
var objs = []; for (var i = 0; i < 8; i++) objs.push(new P(i, i + 1));
out.push("warm " + drive(objs, 50));
objs[3].vx = "7";
out.push("strVx " + drive(objs, 3));
objs[5].extra = 1;
out.push("shape " + drive(objs, 3));
Object.defineProperty(objs[6], "x", { get() { return 100; }, set(v) { out.push("set6 " + v); }, configurable: true });
out.push("accessor " + drive(objs, 1));
objs[1].vx = 2n;
try { drive(objs, 1); } catch (e) { out.push("bigint " + e.name); }
objs[1].vx = null;
out.push("null " + drive(objs, 2));
Object.freeze(objs[2]);
out.push("frozen " + drive(objs, 2) + " " + objs[2].x);
function Q() { this.a = 1; this.b = 2; }
Q.prototype.m = function () { var t = this.a * 2 + this.b; this.a = t | 0; this.b = this.b ^ 3; return t; };
function driveQ(o, n) { var s = 0; for (var i = 0; i < n; i++) s += o.m(); return s; }
var q = new Q();
out.push("q " + driveQ(q, 30));
q.b = {valueOf() { return 4; }};
out.push("qobj " + driveQ(q, 3));
delete q.a;
out.push("qdel " + driveQ(q, 3));
var g1 = 3;
function nameChain(n) { var s = 0; for (var i = 0; i < n; i++) { s = s + g1 * i; } return s; }
out.push("name " + nameChain(40));
g1 = "2";
out.push("nameStr " + nameChain(5));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_numeric_property_chain_deopts(run, tier):
    """CATCHES: numeric property read/write chains in hot methods that keep their fast path after a field becomes a string, BigInt, null, accessor, frozen or deleted, or after a receiver changes shape or a numeric global turns into a string."""
    check_prog(run, tier, PROG_PROPERTY_CHAINS, "property_chains")


PROG_NAME_AND_HELPER_ERRORS = r"""
var out = [];
function rep(label, f, a, b) { var r; for (var i = 0; i < 40; i++) { try { r = f(a, b); } catch (e) { r = "E:" + e.name; } } out.push(label + " " + JSON.stringify(r)); }
function noAssign(o, a, i) { o.x = a[i]; o.y = [a.length, i]; o.z = (i, a.length); o.w = {k: a[0]}; o.v = `${i}`; o.u = i ? a[1] : a[2]; o.t = typeof a; o.s = a[o.x]; o.r = [o.x = 9][0]; return o; }
rep("noAssign", function () { return noAssign({}, [4, 5, 6], 1); });
function blockDestrCap(o) { let f; { let {a} = o; const [b] = [2]; f = () => a + b; } return f(); }
rep("blockDestrCap", blockDestrCap, {a: 5});
function loopTdz() { var n = 0; for (var i = 0; i < 3; i++) { reT.exec(strsT[i]); n++; } return n; }
function loopTdz2() { var n = 0; for (var i = 0; i < 3; i++) { reU.exec(strsU[i]); n++; } return n; }
function litTdz() { var n = 0; for (var i = 0; i < 3; i++) { /a(\d)/.exec(strsT[i]); n++; } return n; }
function repTdz() { var n = 0; for (var i = 0; i < 3; i++) { strsT[i].replace(/a(\d)/, "-"); n++; } return n; }
function matchTdz() { var n = 0; for (var i = 0; i < 3; i++) { strsT[i].match(/a(\d)/); n++; } return n; }
var tdzRes = [];
for (var k = 0; k < 3; k++) for (const f of [loopTdz, loopTdz2, litTdz, repTdz, matchTdz]) { try { tdzRes.push(f()); } catch (e) { tdzRes.push(f.name + ":" + e.name); } }
out.push("tdz " + tdzRes.join(","));
var reU = /a(\d)/;
let reT = /a(\d)/, strsT = ["a1", "a2", "a3"];
let strsU = ["a7", "a8", "a9"];
out.push("after " + loopTdz() + loopTdz2() + litTdz() + repTdz() + matchTdz() + " " + RegExp.$1);
function frozenStore(arr, n) { "use strict"; var c = 0; for (var i = 0; i < n; i++) { try { arr[i % 2] = i; } catch (e) { c++; } } return c; }
out.push("frozenStore " + frozenStore([1, 2], 10) + " " + frozenStore(Object.freeze([1, 2]), 10));
function protoSetterStore(arr, n) { "use strict"; var c = 0; for (var i = 0; i < n; i++) { try { arr[1] = i; } catch (e) { c++; } } return c; }
var noSetter = [1]; Object.setPrototypeOf(noSetter, Object.create(Array.prototype, {1: {get() { return 0; }, configurable: true}}));
out.push("getterOnly " + protoSetterStore(noSetter, 10));
function updElemDeep(o) { try { return o.p[0]++; } catch (e) { return e.name; } }
rep("updElemDeep", updElemDeep, {p: null});
function updElemStr(o, k) { const a = o.p[k]++; const b = --o.p[k]; return [a, b, o.p[k]]; }
rep("updElemStr", function () { return updElemStr({p: {q: "4"}}, "q"); });
Object.defineProperty(globalThis, "accFn", { get() { return function (x) { return x * 3; }; }, configurable: true });
function callAcc(n) { var s = 0; for (var i = 0; i < n; i++) s += accFn(i); return s; }
out.push("callAcc " + callAcc(20) + " " + callAcc(5));
async function asyncReset(a) { var s = 0; for (var a = 0; a < 3; a++) { s += await a; } return s + a; }
async function asyncDrive() { var r = []; for (var k = 0; k < 12; k++) r.push(await asyncReset(10)); return r.join(); }
var two = function (a, b) { return a * 10 + (b | 0); };
function plainCaller(n) { var s = 0; var tw = two; for (var i = 0; i < n; i++) { s += tw(1, 2, 3, 4, 5, 6, 7, 8, 9); s += tw(i); } return s; }
function drivePlain() { var last; for (var r = 0; r < 150; r++) last = plainCaller(4); return last; }
out.push("plain " + drivePlain() + " " + drivePlain());
asyncDrive().then(function (v) { out.push("async " + v); console.log(out.join("\n")); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_jit_helper_error_propagation(run, tier):
    """CATCHES: JIT regexp-literal exec/replace/match helpers and element-store helpers that swallow or mis-order TDZ ReferenceErrors and strict-mode TypeErrors, free-name calls through accessor globals, async functions resetting parameters through for(var) heads, and plain-call inline rollbacks with too many arguments."""
    check_prog(run, tier, PROG_NAME_AND_HELPER_ERRORS, "helper_errors")


PROG_COLLECTION_RECEIVERS = r"""
var out = [];
function coll(recvs, n) {
  var errs = [];
  for (var i = 0; i < n; i++) {
    var r = recvs[i % recvs.length];
    try { r.set(i % 5, i); } catch (e) { errs.push("set:" + e.name + ":" + e.message); }
    try { r.add(i % 4); } catch (e) { errs.push("add:" + e.name + ":" + e.message); }
    try { r.get(i % 5); } catch (e) { errs.push("get:" + e.name + ":" + e.message); }
    try { r.has(i % 5); } catch (e) { errs.push("has:" + e.name + ":" + e.message); }
  }
  return errs;
}
var m = new Map(), s = new Set();
var fakeM = { set: Map.prototype.set, add: Set.prototype.add, get: Map.prototype.get, has: Set.prototype.has };
var both = { set: m.set.bind(m), add: s.add.bind(s), get: m.get.bind(m), has: s.has.bind(s) };
var mapLike = new Map(); mapLike.add = Set.prototype.add; mapLike.has = Map.prototype.has;
var setLike = new Set(); setLike.set = Map.prototype.set; setLike.get = Map.prototype.get;
var e1 = coll([mapLike, setLike], 40);
var e2 = coll([mapLike, setLike, fakeM], 30);
out.push("errs " + e1.length + " " + e2.length);
var uniq = {}; e1.concat(e2).forEach(function (x) { uniq[x] = (uniq[x] || 0) + 1; });
Object.keys(uniq).sort().forEach(function (k) { out.push(k + " x" + uniq[k]); });
out.push("sizes " + mapLike.size + " " + setLike.size + " " + [...mapLike.keys()].join() + " " + [...setLike].join());
var wm = new WeakMap(), ws = new WeakSet();
function weak(n) { var c = 0; for (var i = 0; i < n; i++) { try { wm.set(i % 2 ? {} : i, 1); } catch (e) { c++; } try { ws.add(i % 2 ? {} : i); } catch (e) { c += 100; } } return c; }
out.push("weak " + weak(20));
console.log(out.join("\n"));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_collection_intrinsic_receivers(run, tier):
    """CATCHES: Map#set/get/has and Set#add/has JIT intrinsics that skip the receiver brand check when the builtin is borrowed onto plain objects or the other collection kind, losing the incompatible-receiver TypeError or corrupting the real collections, plus WeakMap/WeakSet key validation in hot loops."""
    check_prog(run, tier, PROG_COLLECTION_RECEIVERS, "collection_receivers")
