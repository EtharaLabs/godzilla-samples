"""Less common bytecode forms, call shapes and program entry points on every execution tier.

The bytecode compiler lowers a subset of the language and bails to the tree-walker for the rest;
the JIT then specialises the compiled ops and falls back to Rust helpers for rare ones. These
programs exercise both sides of that boundary (deletes, optional chains, compound and update
operators on elements, unusual property keys, for-in/of targets, labelled exits, void, BigInt and
string updates, call/apply/bind/spread dispatch, Class.create-style forwarding) and the CLI's
script entry points (`-e`, piped stdin), comparing every tier with the same golden output.
"""

import pytest

from conftest import out, err

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
def test_compiled_syntax_forms(js, golden, tier):
    """CATCHES: bytecode lowering of rarely compiled forms (delete of elements and non-references, optional element/method chains, every compound operator on elements and properties, string/BigInt updates, for-in/of with existing or captured targets, odd for-loop heads, void, tagged templates) that diverges from the tree-walker."""
    code = r"""
"use strict";
function id(x) { return x; }
function deletes(o, k) { const r = []; r.push(delete o[k], delete o["b"], delete o[0], k in o, delete o.nothere, Object.keys(o).join("")); return r.join(); }
function deleteValues() { let t; const r = [delete (t = 1), delete [1], delete id(2), typeof t]; return r.join(); }
function optional(o, k) { const r = [o?.a, o?.[k], o?.a?.b, o?.f?.(), o?.m?.(1), o?.[k]?.x, o?.n?.p, o?.["a"]]; return r.map(String).join("|"); }
function updates(a, o, k) { a[k]++; ++a[k]; a[k]--; --a[k]; a[k] += 5; a[k] -= 1; a[k] *= 2; a[k] **= 2; a[k] %= 7; a[k] <<= 3; a[k] >>= 1; a[k] >>>= 1; a[k] &= 0xFF; a[k] |= 1; a[k] ^= 3; o.p **= 2; o.p >>>= 0; let x = 2; x **= 10; x >>>= 1; x %= 100; const pre = a[k]++ + --a[k] + (o.p--) + (++o.p); return a.join() + ":" + o.p + ":" + x + ":" + pre; }
function strUpdates(s, b) { let t = s; t++; let u = s; u--; let big = b; big++; ++big; big--; const arr = ["5", null, true, undefined]; for (let i = 0; i < arr.length; i++) arr[i]++; return [t, u, typeof big, big, arr.join()].join(); }
function forTargets(arr, o) { let k; const seen = []; for (k in o) seen.push(k); for (k of arr) seen.push(k); var v; for (v of arr) seen.push(v * 2); const holder = {}; for (holder.p of arr) seen.push(holder.p); return seen.join() + ":" + k + ":" + v; }
function capturedTarget(arr) { let k = "init"; const get = () => k; const out = []; for (k of arr) out.push(get()); for (k in { a: 1 }) out.push(get()); return out.join(); }
function forHeads(n) { let out = ""; let i; for (i = 0; i < n; i++) out += i; for (; i > 0;) { i -= 2; out += "d"; } for (let a, b = 1; b < 4; b++) out += typeof a + b; for (let j = 0; ; j++) { if (j > 2) break; out += "j"; } return out; }
function emptyStatements(n) { let s = 0; ; for (let i = 0; i < n; i++) { ; s += i; ; } ; return s; }
function voids(n) { const r = []; for (let i = 0; i < n; i++) r.push(void i, void id(i), typeof void 0); return r.join(); }
function computedCalls(o, ks) { let s = ""; for (const k of ks) s += o[k](1) + o[k](...[2]) + o["m"](3); return s; }
function returnsInLoops(arr) { for (const x of arr) { try { if (x > 1) return "r" + x; } finally { } } return; }
function nestedTernary(n) { let s = ""; for (let i = 0; i < n; i++) s += i % 3 === 0 ? "a" : i % 3 === 1 ? "b" : "c"; return s; }
function commaAndSeq(n) { let a = 0, b = 0; for (let i = 0, j = 10; i < n; i++, j--) { a += i, b += j; } return (a, b, a + b); }
function logicalOps(xs) { return xs.map(x => [x && "and", x || "or", x ?? "nul", !x, !!x].join("/")).join(" "); }
function typeofs(xs) { return xs.map(x => typeof x).join(); }
function inChecks(o, a) { const r = []; for (const k of ["x", "y", 0, 1, "length", Symbol.iterator]) r.push(k in o, k in a); return r.map(Number).join(""); }
function unary(xs) { return xs.map(x => [-x, +x, ~x].map(String).join("/")).join(" "); }
function exponent(n) { let r = []; for (let i = -2; i < n; i++) r.push(2 ** i, (-2) ** i, i ** 0.5); return r.map(v => Number.isNaN(v) ? "NaN" : v.toFixed(3)).join(","); }
function regexLiteral(s) { const r = []; for (let i = 0; i < 3; i++) { const re = /(\w)(\d)?/g; r.push(s.replace(re, "$2$1"), re.lastIndex); } return r.join(); }
function templateTags(n) { const tag = (strs, ...vals) => strs.raw.join("|") + vals.join("+"); let r = ""; for (let i = 0; i < n; i++) r = tag`a${i}b${i * 2}\n`; return r; }
function newTargets(n) { function F() { this.v = 1; } const r = []; for (let i = 0; i < n; i++) { const C = i % 2 ? F : Object; r.push(typeof new C()); } return r.join(); }
function fusedElems(a, b) { for (let i = 0; i < 3; i++) { a[i] = b[i]++; a[i + 3] = b[i] = a[i] * 2; a[i] += b[i]--; } return a.join() + "|" + b.join(); }
var freeCounter = 0;
function assignExprs(a, o, k) { let x = 1, r = []; let cap = 10; const peek = () => cap; r.push(x += 2, x -= 1, x *= 5, x **= 2, x = 7); r.push(cap = 5, cap += 1, cap -= 2, peek()); r.push(freeCounter = 3, freeCounter += 4, freeCounter *= 2); r.push(o.p += 2, o.p *= 3, o.p = -1, o[k] += 10, o[k] >>= 1); r.push(a[0] *= 2, a[1] -= 1, a[k] = 9, o.arr[1] -= 1, o.arr[0] += 0.5, (o.arr[2] = 4)); const z = (x = 2) + (x += 1); r.push(z, x); return r.join(); }
function computedMethods(o, n) { let s = 0; for (let i = 0; i < n; i++) s += o["inc"](i) + o["dbl"](i); return s; }
function drive(rounds) {
  const out = [];
  for (let r = 0; r < rounds; r++) {
    out.length = 0;
    out.push(deletes({ a: 1, b: 2, 0: "z", c: 3 }, "a"), deleteValues(), optional({ a: { b: 7 }, f() { return "f"; }, m(x) { return x * 2; }, n: null, k: { x: 9 } }, "k"), optional(null, "k"), optional({}, "z"));
    out.push(updates([1, 2, 3], { p: 3 }, 1), strUpdates("7", 10n), strUpdates("x", -1n), forTargets([1, 2], { p: 1, q: 2 }), capturedTarget(["a", "b"]), forHeads(4), emptyStatements(5), voids(2));
    out.push(computedCalls({ m: (x) => x + 1, n: (x) => x * 10 }, ["m", "n"]), returnsInLoops([1, 2, 3]), String(returnsInLoops([0])), nestedTernary(7), commaAndSeq(4), logicalOps([0, 1, "", null, "s"]), typeofs([1, "s", null, undefined, {}, [], () => 1, 1n, Symbol.iterator, true]));
    out.push(assignExprs([1, 2, 3], { p: 1, q: 4, arr: [1, 2, 3] }, "q"), computedMethods({ inc(x) { return x + 1; }, dbl(x) { return x * 2; } }, 5), fusedElems([0, 0, 0, 0, 0, 0], [5, 6, 7]), inChecks({ x: 1, 0: 0 }, [5, 6]), unary([1, "2", null, undefined, true, "x", [], [3], 1.5, -0]), exponent(3), regexLiteral("a1b2c"), templateTags(3), newTargets(4));
  }
  return out.join("\n");
}
console.log(drive(12));
const cmObj = { inc(x) { return x + 1; }, dbl(x) { return x * 2; } };
function cmDriver(n) { let t = 0; for (let i = 0; i < n; i++) t += computedMethods(cmObj, 3); return t; }
console.log(cmDriver(130));
cmObj.dbl = function (x) { return -x; };
console.log(cmDriver(2), computedMethods({ inc: Math.abs, dbl: String }, 2));
"""
    check(js, golden, "syntax_forms", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_rare_operations_inside_compiled_functions(js, golden, tier):
    """CATCHES: VM/JIT helpers for uncommon ops (post/pre increment values of BigInt, string, undefined and null locals, element deletes and updates, symbol/object/null property keys, iterator abort on throw, computed method calls, unary and arithmetic coercions, regexp literals, computed object literals, BigInt mixing errors) that return the wrong value or error."""
    code = r"""
function postPre(n) { let i = 0, b = 10n, s = "5", u; const out = []; for (let k = 0; k < n; k++) { out.push(i++, ++i, i--, --i); } out.push(b++, ++b, b--, --b, typeof b); out.push(s++, ++s, s--, --s, typeof s); out.push(u++, String(u)); let t = "x"; out.push(t++, t); let nn = null; out.push(nn--, nn); return out.join(","); }
function deletesElem(o, keys) { const r = []; for (const k of keys) r.push(delete o[k]); return r.join() + ":" + Object.keys(o).join(""); }
function strictDelete(o, k) { "use strict"; try { return delete o[k]; } catch (e) { return e.constructor.name; } }
function updElem(a, keys) { const r = []; for (const k of keys) { r.push(a[k]++, ++a[k], a[k]--, --a[k]); a[k]++; --a[k]; } return r.join() + "|" + JSON.stringify(a); }
function propKeys(o) { const sym = Symbol.for("k"), obj = { toString() { return "objkey"; } }; o[sym] = 1; o[obj] = 2; o[null] = 3; o[undefined] = 4; o[1.5] = 5; o[-0] = 6; o[true] = 7; const r = [o[sym], o[obj], o["objkey"], o.null, o.undefined, o["1.5"], o[0], o.true]; return r.join(); }
function propKeysLocal(n) { const o = {}; const keys = [Symbol.iterator, { toString() { return "t"; } }, null, 2, "s"]; let r = ""; for (let i = 0; i < n; i++) { const k = keys[i % 5]; o[k] = i; r += typeof o[k]; } return r + Object.keys(o).length; }
function voids(n) { let c = 0; for (let i = 0; i < n; i++) if (void i === undefined) c++; return c; }
function abortLoop(arr) { let closed = 0; const it = { [Symbol.iterator]() { let i = 0; return { next() { return { value: arr[i++], done: i > arr.length }; }, return() { closed++; return {}; } }; } };
  let s = 0; try { for (const v of it) { if (v < 0) throw new Error("neg" + v); s += v; } } catch (e) { return s + ":" + e.message + ":" + closed; } return s + ":" + closed; }
function abortArray(arr) { let s = 0; try { for (const v of arr) { s += v.length; } } catch (e) { return s + ":" + e.constructor.name; } return String(s); }
function methodElem(o, keys) { let r = ""; for (const k of keys) r += o[k](k); return r; }
function unaryOps(xs) { return xs.map(x => { try { return [~x, -x, +x].map(String).join("/"); } catch (e) { return e.constructor.name; } }).join(" "); }
function divs(xs) { const r = []; for (let i = 1; i < xs.length; i++) r.push(xs[i - 1] / xs[i], xs[i - 1] % xs[i], xs[i - 1] - xs[i], xs[i - 1] * xs[i]); return r.map(String).join(","); }
function regexes(n) { const r = []; for (let i = 0; i < n; i++) { const re = /ab+c/gi; r.push(re.test("xABBC" + i), re.lastIndex, re.source, re.flags); } return r.slice(-4).join(","); }
function objects(n, k) { const r = []; for (let i = 0; i < n; i++) { const o = { [k + i]: i, ...{ s: 1 }, [Symbol.toStringTag]: "T" + i, get g() { return i; } }; r.push(Object.keys(o).join("") + o.g + String(o)); } return r.join(); }
function instanceofs(xs) { return xs.map(x => [x instanceof Object, x instanceof Array, x instanceof Error].map(Number).join("")).join(","); }
function inOps(o, ks) { return ks.map(k => { try { return String(k in o); } catch (e) { return e.constructor.name; } }).join(); }
function bigOps(n) { let x = 1n; for (let i = 0; i < n; i++) { x = x * 3n + BigInt(i); x = -x; x = x % 1000003n; } return String(x) + typeof x + (x > 5) + (x == -x * -1n); }
function mixedBig() { const r = []; for (const [a, b] of [[1n, 1], [2n, "2"], [3n, 3.5]]) { try { r.push(a + b); } catch (e) { r.push(e.constructor.name); } r.push(a == b, a < b); } return r.join(); }
for (let k = 0; k < 3; k++) {
  console.log(postPre(3));
  console.log(deletesElem({ a: 1, b: 2, 0: 3, 1: 4 }, ["a", 0, "zz", 1]), deletesElem([1, 2, 3], [0, "length", 2]), strictDelete(Object.freeze({ x: 1 }), "x"), strictDelete([1, 2], "length"), strictDelete({ y: 1 }, "y"));
  console.log(updElem([1, 2, 3], [0, 2, "x"]), updElem({ a: "5", b: null }, ["a", "b"]), propKeys({}), propKeysLocal(10), voids(5));
  console.log(abortLoop([1, 2, -3, 4]), abortLoop([5, 6]), abortArray(["ab", "c", null, "d"]), abortArray(["ab"]), methodElem({ a: (x) => x + "!", b(x) { return x + "?"; } }, ["a", "b", "a"]));
  console.log(unaryOps([1, "2", null, undefined, true, "x", [], [3], 1.5, -0, 5n, {}]), divs([7, 2, "3", null, true, 0, -0, "x", 4]));
  console.log(regexes(3), objects(2, "k"), instanceofs([{}, [], new TypeError("x"), null, 5, Object.create(null)]), inOps({ a: 1 }, ["a", "b", 0]), inOps([1], [0, 1, "length"]), bigOps(20), mixedBig());
}
try { inOps(5, ["a"]); console.log(inOps(5, ["a"])); } catch (e) { console.log(e.constructor.name); }
"""
    check(js, golden, "rare_operations", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_call_dispatch_shapes_and_target_changes(js, golden, tier):
    """CATCHES: call-site caches for direct, polymorphic, bound, call/apply, spread, constructor, fresh/shared closure and Math/Array/String intrinsic calls that keep calling a stale target after the target array entries or builtins are replaced."""
    code = r"""
"use strict";
function add3(a, b, c) { return a + b + c; }
function add1(x) { return x + 1; } function add2(x) { return x + 2; } function add4(x) { return x + 4; } function add8(x) { return x + 8; }
const userTargets = [add1, add2, add4, add8];
const nativeTargets = [Math.abs, Math.floor, Math.ceil, Math.trunc];
const boundUser = add3.bind(null, 3, 4), boundNative = Math.max.bind(null, 3, 4);
const applyArgs = [3, 4, 5], spreadArgs = [3, 4, 5];
class Pair { constructor(l, r) { this.l = l; this.r = r; } }
class Leaf {}
function factory(seed) { return function (x) { return seed + x; }; }
function invoke(f, x) { return f(x); }
function sharedFactory(seed) { function leaf(x) { return seed + x; } function batch() { let t = 0; for (let j = 0; j < 8; j++) t += leaf(j); return t; } return batch; }
const shapes = {
  "native-direct": n => { let t = 0; for (let i = 0; i < n; i++) t += Math.abs(-(i & 7)); return t; },
  "native-poly": n => { let t = 0; for (let i = 0; i < n; i++) t += nativeTargets[i & 3](-(i & 7) - 0.25); return t; },
  "user-poly": n => { let t = 0; for (let i = 0; i < n; i++) t += userTargets[i & 3](i & 7); return t; },
  "bound-user": n => { let t = 0; for (let i = 0; i < n; i++) t += boundUser(i & 7); return t; },
  "bound-native": n => { let t = 0; for (let i = 0; i < n; i++) t += boundNative(i & 7); return t; },
  "call-user": n => { let t = 0; for (let i = 0; i < n; i++) t += add3.call(null, 3, 4, i & 7); return t; },
  "call-native": n => { let t = 0; for (let i = 0; i < n; i++) t += Math.abs.call(null, -(i & 7)); return t; },
  "apply-user": n => { let t = 0; for (let i = 0; i < n; i++) { applyArgs[2] = i & 7; t += add3.apply(null, applyArgs); } return t; },
  "apply-native": n => { let t = 0; for (let i = 0; i < n; i++) { applyArgs[2] = i & 7; t += Math.max.apply(null, applyArgs); } return t; },
  "spread-user": n => { let t = 0; for (let i = 0; i < n; i++) { spreadArgs[2] = i & 7; t += add3(...spreadArgs); } return t; },
  "spread-native": n => { let t = 0; for (let i = 0; i < n; i++) { spreadArgs[2] = i & 7; t += Math.max(...spreadArgs); } return t; },
  "construct": n => { let t = 0; for (let i = 0; i < n; i++) { const p = new Pair(i, 1); t += p.l + p.r + (new Leaf() instanceof Leaf); } return t; },
  "fresh-closures": n => { let t = 0; for (let i = 0; i < n / 16; i++) { const f = factory(i); for (let j = 0; j < 16; j++) t += invoke(f, j); } return t; },
  "shared-closures": n => { let t = 0; for (let i = 0; i < n / 8; i++) t += sharedFactory(i)(); return t; },
  "math-intrinsics": n => { let t = 0; for (let i = 0; i < n; i++) t += Math.sqrt(i) + Math.floor(i / 3) + Math.max(i, 7) + Math.min(i, 3) + Math.round(i / 7) + Math.ceil(i / 9) + Math.trunc(-i / 4) + Math.sign(i - 5) + Math.imul(i, 3) + Math.hypot(3, 4); return t.toFixed(4); },
  "array-push-pop": n => { const a = []; let t = 0; for (let i = 0; i < n; i++) { a.push(i); if (i % 3 === 0) t += a.pop(); } return t + ":" + a.length; },
  "string-methods": n => { let t = 0; const s = "lumen-jit"; for (let i = 0; i < n; i++) t += s.charCodeAt(i % 9) + s.indexOf("j") + s.length + (s.startsWith("lu") ? 1 : 0); return t; },
};
function runAll(n) { const out = []; for (const name in shapes) out.push(name + "=" + shapes[name](n)); return out.join(" "); }
runAll(400); runAll(400);
console.log(runAll(3200));
// change targets after warmup
userTargets[1] = Math.sqrt; nativeTargets[0] = (x) => 100; Math.abs = (x) => -1; Pair.prototype.constructor = null;
console.log(runAll(64));
"""
    check(js, golden, "call_dispatch", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_builtin_call_intrinsics_and_their_guard_misses(js, golden, tier):
    """CATCHES: JIT intrinsics for charCodeAt/codePointAt/charAt/slice, Object.hasOwn, Function#call/apply, Math.sqrt, Array#push/pop, discarded RegExp#exec/replace/split calls and Map/Set operations that skip coercions or keep the fast path for String wrappers, negative/fractional indices, array-likes, frozen arrays, prototype setters, empty pops or subclassed collections."""
    code = r"""
"use strict";
function codes(s, n) { let h = 0; for (let i = 0; i < n; i++) h = (h * 33 + s.charCodeAt(i) + (s.codePointAt(i) | 0)) | 0; return h; }
function chars(s, n) { let r = ""; for (let i = -1; i < n; i++) r += s.charAt(i) + "."; return r; }
function slices(s, pairs) { const r = []; for (let i = 0; i < pairs.length; i++) r.push(s.slice(pairs[i][0], pairs[i][1])); return r.join("|"); }
function hasOwns(o, keys) { let c = ""; for (let i = 0; i < keys.length; i++) c += Object.hasOwn(o, keys[i]) ? "1" : "0"; return c; }
function applies(f, lists) { let s = 0; for (let i = 0; i < lists.length; i++) s += f.apply(null, lists[i]); return s; }
function sum3(a, b, c) { return (a | 0) + (b | 0) + (c | 0); }
function calls(f, n) { let s = 0; for (let i = 0; i < n; i++) s += f.call({ k: i }, i); return s; }
function roots(xs) { let s = 0; for (let i = 0; i < xs.length; i++) s += Math.sqrt(xs[i]); return s; }
function pushes(a, n) { for (let i = 0; i < n; i++) a.push(i); return a.length; }
function pops(a, n) { let s = ""; for (let i = 0; i < n; i++) s += String(a.pop()); return s + ":" + a.length; }
function execs(re, strs) { for (let i = 0; i < strs.length; i++) re.exec(strs[i]); return re.lastIndex; }
function replaces(strs) { let c = 0; for (let i = 0; i < strs.length; i++) { strs[i].replace("a", "b"); c++; } return c; }
function splits(strs) { let c = 0; for (let i = 0; i < strs.length; i++) { strs[i].split(","); c++; } return c; }
function collections(m, s, n) { let t = 0; for (let i = 0; i < n; i++) { m.set(i % 5, i); s.add(i % 3); if (m.has(i % 7)) t += m.get(i % 5); if (s.has(i % 4)) t++; s.delete(9); m.delete(8); } return t + ":" + m.size + ":" + s.size; }
function withThis(n) { return this.k + n; }
function drive(rounds) { const out = []; for (let r = 0; r < rounds; r++) {
  out.length = 0;
  out.push(codes("hello", 5), chars("abc", 3), slices("abcdef", [[0, 2], [1, 4], [2, 6]]), hasOwns({ a: 1, b: 2 }, ["a", "b", "c"]), applies(sum3, [[1, 2, 3], [4, 5, 6]]), calls(withThis, 5), roots([4, 9, 16]), pushes([], 4), pops([1, 2, 3, 4], 2), execs(/o/g, ["foo", "bar"]), replaces(["abc", "aaa"]), splits(["a,b", "c"]), collections(new Map(), new Set(), 20));
} return out.join(" "); }
console.log(drive(130));
// now the guard misses: non-string receivers, out-of-range/negative/fractional indices, non-ASCII, proxies, array-likes, frozen arrays, empty pops, subclassed collections
console.log(codes("hé\u{1F600}x", 5), codes(new String("abc"), 3), chars("\u00e9a", 3), chars(new String("xy"), 2), chars("abc", 1.5));
console.log(slices("abcdef", [[-2, undefined], [4, 1], [1.7, 3.2], ["1", "3"], [NaN, 2], [-10, 100]]), slices(new String("str"), [[0, 1]]));
console.log(hasOwns({ a: 1 }, [Symbol.iterator, 0, "toString", "a"]), hasOwns([5], [0, "length", 1]), hasOwns(new Proxy({ p: 1 }, {}), ["p", "q"]), hasOwns(Object.create({ inh: 1 }), ["inh"]));
console.log(applies(sum3, [{ length: 2, 0: 5, 1: 6 }, [1, , 3], undefined, null, (function () { return arguments; })(7, 8, 9)]), applies(Math.max, [[1, 9, 3], []]));
console.log(calls(Math.abs, 3), calls((x) => x * 2, 3), calls(withThis.bind({ k: 100 }), 2));
console.log(roots([2, -1, "16", null, 1e308 * 10]), pushes([9], 2));
try { pushes(Object.freeze([1]), 1); } catch (e) { console.log(e.constructor.name); }
const setterArr = [1]; Object.defineProperty(Array.prototype, "3", { set(v) { this.trap = v; }, configurable: true }); console.log(pushes(setterArr, 4), setterArr.trap, setterArr.length); delete Array.prototype[3];
console.log(pops([], 2), pops([1, , 3], 3), pops(Object.assign([1, 2], { extra: 1 }), 1));
console.log(execs(/a/y, ["a", "ba"]), execs(/z/g, ["zz", "a"]), execs(/(?:)/g, ["", "q"]), replaces([new String("x")]), splits(["", "a,,b"]));
class MyMap extends Map { get(k) { return 1000; } } console.log(collections(new MyMap(), new Set(), 10), collections(new Map([[1, NaN]]), new Set([NaN]), 7));
"""
    check(js, golden, "builtin_intrinsics", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_parameter_defaults_rest_and_captured_parameters(js, golden, tier):
    """CATCHES: compiled parameter initialisation that applies literal or expression defaults to null/0 arguments, shares one empty-array default between calls, ignores earlier parameters, evaluates effectful defaults when an argument is present, or mishandles rest, destructured and captured parameters."""
    code = r"""
"use strict";
function lit(a = 1, b = "s", c = null, d = true, e = 10n, f = [], g = {}) { return [a, b, c, d, typeof e, f.length, Object.keys(g).length].join(); }
function capLit(a = 5, b = [], c = {}) { const get = () => a + ":" + b.length + ":" + typeof c; a++; b.push(1); return get(); }
function capFresh(list = []) { list.push(list.length); return () => list.join(); }
function capHoistConflict(x = 3) { function x2() { return x; } return x2(); }
function exprDefaults(a, b = a * 2, c = b + a, d = Math.max(a, 1), e = [a, b], f = { a, k: b }, g = typeof a, h = a ? "t" : "f", i = `${a}!`, j = -a, k = !a) { return [a, b, c, d, e.join("/"), f.k, g, h, i, j, k].join(); }
function capExpr(a, b = a + 1) { return () => b * 10; }
function earlierParam(a, b = a) { return b; }
function laterParamTdz(a = b, b = 1) { return a; }
function effectDefault(a = counter.next()) { return a; }
const counter = { n: 0, next() { return ++this.n; } };
function arrowDefault(f = (x) => x * 2) { return f(4); }
function destructParams({ a, b = 2 } = {}, [c, d = 4] = []) { return a + ":" + b + ":" + c + ":" + d; }
function restParams(a, ...rest) { return a + ":" + rest.length + ":" + rest.join("-"); }
function capturedRest(a, ...r) { return () => r.concat(a).join(); }
function argsWithDefault(a = 1) { return arguments.length + ":" + a; }
function drive(n) { const out = []; for (let i = 0; i < n; i++) { out.length = 0;
  out.push(lit(), lit(0, "", undefined, false, 0n, [1], { z: 1 }), capLit(), capLit(1, [2, 3], null), capFresh()(), capFresh([9])(), capHoistConflict(), capHoistConflict(undefined));
  out.push(exprDefaults(2), exprDefaults(0, undefined, 7), capExpr(1)(), capExpr(1, 5)(), earlierParam(4), earlierParam(4, null), arrowDefault(), arrowDefault((y) => y + 1), effectDefault(), effectDefault(100));
  out.push(destructParams(), destructParams({ a: 1 }, [3]), restParams(1), restParams(1, 2, 3), capturedRest(0, 7, 8)(), argsWithDefault(), argsWithDefault(undefined, 2));
  try { laterParamTdz(); } catch (e) { out.push(e.constructor.name); }
  out.push(laterParamTdz(9)); }
  return out.join(" | "); }
console.log(drive(15));
console.log(counter.n);
"""
    check(js, golden, "parameter_defaults", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_error_paths_raised_from_compiled_code(js, golden, tier):
    """CATCHES: compiled ops that skip TDZ checks on reads/updates/property access of uninitialised let bindings, or raise the wrong error class/message for null/undefined bases in deletes, reads, compound updates with symbol/object keys, destructuring, `in`, instanceof, construction of non-constructors, symbol arithmetic and BigInt mixing."""
    code = r"""
"use strict";
function tdzRead(flag) { if (flag) { return x; } let x = 1; return x; }
function tdzCaptured(flag) { const get = () => y; if (flag) return get(); let y = 2; return get(); }
function tdzTypeof(flag) { if (flag) return typeof z; let z = 3; return typeof z; }
function delNull(o, k) { return delete o[k]; }
function delNullProp(o) { return delete o.p; }
function readNull(o, k) { return o[k]; }
function compoundNull(o, k) { o[k] += 1; return o; }
function compoundNullLocal(k) { let o = null; for (let i = 0; i < 1; i++) o[k] -= 1; return o; }
function updateNull(o, k) { o[k]++; return o; }
function propNull(o) { return o.p; }
function setNull(o) { o.p = 1; return o; }
function callNull(o) { return o.m(); }
function destructNull(v) { const { a } = v; return a; }
function destructIter(v) { const [a, b, c] = v; return [a, b, c].join(); }
function inNull(o) { return "k" in o; }
function instNull(o, C) { return o instanceof C; }
function newNonCtor(F) { return new F(); }
function spreadNull(v) { return Math.max(...v); }
function symToNum(s) { return s + 1; }
function bigMix(a, b) { return a * b; }
function freezeWrite(o) { o.x = 2; return o.x; }
function getterThrows(o) { return o.boom; }
function tdzUpdate(flag) { if (flag) { x++; } let x = 1; return x; }
function tdzUpdateCap(flag) { const g = () => y; if (flag) { y++; } let y = 2; return g(); }
function tdzProp(flag) { if (flag) { return o.p; } let o = { p: 1 }; return o.p; }
function tdzSetProp(flag) { if (flag) { o.p = 5; } let o = { p: 1 }; return o.p; }
function keyedNullLocal(k) { let o = null; for (let i = 0; i < 1; i++) { o[k] += 1; } return o; }
function keyedNullStack(k) { const get = () => null; get()[k] += 1; }
function tdzCapWrite(flag) { const g = () => y; if (flag) { y = 5; } let y = 2; return g(); }
function tdzCapCompound(flag) { const g = () => w; if (flag) { w += 5; } let w = 2; return g(); }
function cases(fn, args, nameOnly) { const out = []; for (const a of args) { try { out.push(String(fn(...a))); } catch (e) { out.push(nameOnly ? e.constructor.name : e.constructor.name + ":" + e.message); } } return out.join(" ; "); }
for (let k = 0; k < 12; k++) { tdzCapWrite(false); tdzCapCompound(false); tdzUpdate(false); tdzUpdateCap(false); tdzProp(false); tdzSetProp(false); tdzRead(false); tdzCaptured(false); tdzTypeof(false); delNull({ a: 1 }, "a"); delNullProp({}); readNull([1], 0); compoundNull({ a: 1 }, "a"); updateNull({ a: 1 }, "a"); propNull({}); setNull({}); callNull({ m() { return 1; } }); destructNull({}); destructIter([1, 2, 3]); inNull({}); instNull({}, Object); newNonCtor(Object); spreadNull([1]); bigMix(2n, 3n); }
const lines = [
  cases(tdzCapWrite, [[true], [false]]), cases(tdzCapCompound, [[true]]), cases(tdzUpdate, [[true], [false]]), cases(tdzUpdateCap, [[true]]), cases(tdzProp, [[true]]), cases(tdzSetProp, [[true]]), cases(keyedNullLocal, [[Symbol.iterator], [{}], [null]]), cases(keyedNullStack, [[Symbol.iterator]]),
  cases(tdzRead, [[true], [false]]), cases(tdzCaptured, [[true], [false]]), cases(tdzTypeof, [[true]]),
  cases(delNull, [[null, "a"], [undefined, 0], [{ a: 1 }, "a"]]), cases(delNullProp, [[null], [undefined]]),
  cases(readNull, [[null, 0], [undefined, "x"], ["str", 1]]), cases(compoundNull, [[null, "a"], [undefined, 1]], true), cases(compoundNullLocal, [["q"]], true),
  cases(updateNull, [[null, "a"], [undefined, 1]], true), cases(propNull, [[null], [undefined]]), cases(setNull, [[null], [undefined], [5]]),
  cases(callNull, [[null], [{}], [{ m: 3 }]], true), cases(destructNull, [[null], [undefined]]), cases(destructIter, [[new Set([7, 8])], ["ab"], [{ [Symbol.iterator]: function* () { yield 1; yield 2; yield 3; yield 4; } }]]),
  cases(destructIter, [[5], [{}]]), cases(inNull, [[null], [5], ["s"]]), cases(instNull, [[{}, null], [{}, {}], [1, Object]]),
  cases(newNonCtor, [[() => 1], [Math.max], [5], [Symbol]]), cases(spreadNull, [[null], [5]], true), cases(symToNum, [[Symbol("s")]]), cases(bigMix, [[1n, 1], [2n, 2n]]),
  cases(freezeWrite, [[Object.freeze({ x: 1 })], [Object.defineProperty({}, "x", { get() { return 1; } })]]), cases(getterThrows, [[{ get boom() { throw new EvalError("from getter"); } }]]),
];
console.log(lines.join("\n"));
"""
    check(js, golden, "compiled_error_paths", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_inlined_callees_inside_async_functions(js, golden, tier):
    """CATCHES: async functions whose synchronous helpers are cached or inlined and that resume with the wrong value after an await, keep a replaced helper, or lose a TypeError thrown when a helper becomes non-callable."""
    code = r"""
"use strict";
function sq(x) { return x * x; }
function plus(a, b) { var t = a + b; return t; }
const helper = { scale(v) { return v * 3; } };
async function work(i) { const a = sq(i) + plus(i, 1) + helper.scale(i); await null; const b = sq(a % 7) + plus(a, -a); return a + b; }
async function loopWork(n) { let s = 0; for (let i = 0; i < n; i++) s += await work(i); return s; }
function syncDriver(n) { const ps = []; for (let i = 0; i < n; i++) ps.push(work(i)); return Promise.all(ps); }
async function main() {
  const all = await syncDriver(150);
  console.log(all.length, all.slice(0, 5).join(), all[149]);
  console.log(await loopWork(20));
  sq = function (x) { return -x; };
  helper.scale = (v) => v;
  const again = await syncDriver(5);
  console.log(again.join(), await loopWork(3));
  try { plus = null; await work(1); } catch (e) { console.log(e.constructor.name); }
}
main();
"""
    check(js, golden, "async_inlining", code, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_script_scope_globals_with_eval_flag(run, golden, tier):
    """CATCHES: cached global-object name loads/stores (var/let/const at script scope, implicit
    globals, globalThis writes, deleted or accessor-replaced globals, non-writable globals) that
    misbehave when the program is a classic script passed with `-e` instead of a module file."""
    code = r"""
var total = 0, label = "L", flags = 0;
let scriptLet = 1;
const scriptConst = 10;
function bump(n) { for (let i = 0; i < n; i++) { total = total + i; total++; label += i % 10; flags = flags | (1 << (i % 8)); scriptLet = scriptLet * 3 % 101; } return total + ":" + label.length + ":" + flags + ":" + scriptLet; }
function readGlobals(n) { let s = 0; for (let i = 0; i < n; i++) s += total % 7 + scriptConst + (typeof undeclaredYet === "undefined" ? 0 : undeclaredYet); return s; }
function implicitWrite(n) { for (let i = 0; i < n; i++) implicitGlobal = (typeof implicitGlobal === "number" ? implicitGlobal : 0) + i; return implicitGlobal; }
function viaGlobalThis(n) { for (let i = 0; i < n; i++) globalThis.total += 1; return total; }
function shadow(n) { let total = -5; for (let i = 0; i < n; i++) total += 1; return total; }
function deleteAndRedefine(n) { let r = ""; for (let i = 0; i < n; i++) { if (i === 3) delete globalThis.implicitGlobal; if (i === 5) globalThis.implicitGlobal = "back"; r += typeof implicitGlobal === "undefined" ? "u" : typeof implicitGlobal[0]; } return r; }
globalThis.swapMe = 1;
function accessorSwap(n) { let s = 0; for (let i = 0; i < n; i++) { if (i === 4) Object.defineProperty(globalThis, "swapMe", { get() { return 1000; }, set(v) {}, configurable: true }); s += swapMe; swapMe = i; } return s; }
function frozenGlobalWrite() { "use strict"; Object.defineProperty(globalThis, "fixedValue", { value: 1, writable: false, configurable: true }); try { fixedValue = 2; } catch (e) { return e.constructor.name + ":" + fixedValue; } return "no error"; }
function constWrite() { try { scriptConst = 1; } catch (e) { return e.constructor.name; } return "no error"; }
for (let k = 0; k < 3; k++) console.log(bump(10), readGlobals(5), implicitWrite(4), viaGlobalThis(3), shadow(4));
globalThis.undeclaredYet = 2;
console.log(readGlobals(5), deleteAndRedefine(8), accessorSwap(8), frozenGlobalWrite(), constWrite(), "total" in globalThis, "scriptLet" in globalThis, typeof globalThis.scriptConst);
var SCALE = 2;
function scaled(x) { return x * SCALE; }
var helper = { m(x) { return x + SCALE; } };
function shadowing(n) { let SCALE = 100; let s = 0; for (let i = 0; i < n; i++) s += scaled(i) + helper.m(i) + SCALE; return s; }
function shadowDriver(r) { let t = 0; for (let k = 0; k < r; k++) t += shadowing(3); return t; }
console.log(shadowDriver(130));
SCALE = 5; console.log(shadowDriver(1));
"""
    r = run([*tier, "-e", code])
    assert out(r) == golden("script_globals")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_program_piped_on_stdin_tiers_up(run, golden, tier):
    """CATCHES: a stdin-evaluated script that does not compile hot functions consistently with
    file programs, prints a different result, or fails to expose top-level functions on the
    global object."""
    code = r"""
function hot(n) { let s = 0; for (let i = 0; i < n; i++) s += i * i; return s; }
let t = 0; for (let k = 0; k < 30; k++) t += hot(k);
console.log("stdin", t, typeof globalThis.hot);
"""
    r = run([*tier], input=code)
    assert out(r) == golden("stdin_program")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_uncaught_error_thrown_from_hot_method(js, golden, tier):
    """CATCHES: an exception thrown from a warmed (compiled or inlined) method that is reported
    with the wrong message, swallowed, or exits with the wrong status after partial output."""
    code = r"""
"use strict";
class Account { constructor(b) { this.balance = b; } withdraw(x) { if (x > this.balance) throw new RangeError("insufficient funds: " + x + " > " + this.balance); this.balance -= x; return this.balance; } }
function settle(acct, amounts) { let last = 0; for (let i = 0; i < amounts.length; i++) last = acct.withdraw(amounts[i]); return last; }
const a = new Account(100000);
let total = 0;
for (let k = 0; k < 200; k++) total += settle(a, [1, 2, 3]);
console.log("warm", total, a.balance);
settle(a, [5, 10, 1e9]);
console.log("not reached");
"""
    r = js(code, *tier)
    assert out(r) == golden("uncaught_hot_method")
    assert (r.returncode, err(r)) == (1, "Uncaught RangeError: insufficient funds: 1000000000 > 98785\n")
