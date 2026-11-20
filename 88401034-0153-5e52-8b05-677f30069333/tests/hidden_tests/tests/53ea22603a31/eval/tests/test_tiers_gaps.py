"""Second-wave tier coverage: bytecode-VM opcodes and compiled-code helpers that the first wave never
reached -- updates of variables captured by inner closures, free-name writes through the global
object and parent activations, `delete` and TDZ errors inside compiled bodies, element
assignment/update expressions with coercing keys, computed-key method calls, iterator-driven
destructuring against a patched iteration protocol, `for`-head re-declarations of parameters,
very large frames, dead-result RegExp statements and builtin call intrinsics.
Every program warms its functions past tier-up (a body with a loop compiles on its first call,
others after a few calls) and runs on the default JIT tier, --tier=bytecode and --tier=interp
against ONE shared golden, so a tier that diverges from the tree-walker is caught."""
import pytest

from conftest import assert_result, check_script, resources_for

G = resources_for(__file__)
TIERS = [pytest.param([], id="jit"), pytest.param(["--tier=bytecode"], id="bytecode"),
         pytest.param(["--tier=interp"], id="interp")]
tiers = pytest.mark.parametrize("cli", TIERS)


@tiers
def test_captured_variable_updates(run, workdir, cli):
    """CATCHES: compiled functions whose own variables are captured by an inner closure (so they
    live in an activation, not a slot) and are then updated with ++/--, compound assignment used
    as an expression, plain assignment in expression position or destructuring -- a tier that
    updates a stale copy (closure sees the old value), coerces BigInt to Number, returns the
    un-coerced old value of `s++` on a string or `o--` on an object with valueOf, or forgets the
    TDZ ReferenceError for `x++` / `x = 1` / a closure read of a captured `let` before its
    declaration."""
    check_script(run, workdir, G, "captured_variable_updates", r'''
function counterBox(n) {
  var c = 0, big = 10n, s = '5', o = { valueOf: function () { return 7; } }, u;
  var peek = function () { return [c, big, s, o, u].map(String).join('|'); };
  var trace = [];
  for (var i = 0; i < n; i++) {
    c++; ++c; c--; big++; --big; big++;
    trace.push(c++, ++c, s++, o--, typeof big);
  }
  u++;
  var r1 = (c += 3), r2 = (c *= 2), r3 = (c = c - 1), r4 = (c >>= 1), r5 = (big **= 2n);
  return peek() + ' ' + trace.slice(-5).join(',') + ' ' + [r1, r2, r3, r4, r5].join(',');
}
var out;
for (var k = 0; k < 12; k++) out = counterBox(5);
console.log(out);
function tdzCaptured(mode) {
  var f = function () { return x; };
  var m = 'no error';
  try { if (mode === 0) x++; else if (mode === 1) x = 1; else if (mode === 2) x += 1; else f(); } catch (e) { m = e.name + ': ' + e.message; }
  let x = 2;
  x++;
  return m + ' / after=' + f();
}
var tz = [];
for (var k = 0; k < 12; k++) tz = [0, 1, 2, 3].map(tdzCaptured);
console.log(tz.join('\n'));
function destructCaptured(pairs) {
  var a, b, get = function () { return a + ':' + b; }, log = [];
  for (var i = 0; i < pairs.length; i++) {
    [a, b] = pairs[i];
    log.push(get());
    ({ a, b = 'dflt' } = { a: i });
    log.push(get());
  }
  var [p, q = 10] = pairs[pairs.length - 1];
  var inner = function () { return p * q; };
  let { length: L } = pairs;
  var gl = function () { return L; };
  return log.join(' ') + ' | ' + inner() + ' ' + gl();
}
var d1;
for (var k = 0; k < 12; k++) d1 = destructCaptured([[1, 2], [3, 4], [5]]);
console.log(d1);
function loopCaptured(list) {
  var item, keyName, fns = [];
  for (item of list) fns.push(function () { return item; });
  for (keyName in { p: 1, q: 2 }) fns.push(function () { return keyName; });
  var total = 0, add = function (v) { total += v; return total; };
  for (var i = 0; i < 4; i++) { add(i); total = total * 2; }
  return fns.map(function (f) { return f(); }).join(',') + ' total=' + total;
}
var f1;
for (var k = 0; k < 12; k++) f1 = loopCaptured(['x', 'y']);
console.log(f1);
''', cli=cli)


@tiers
def test_free_name_writes(run, workdir, cli):
    """CATCHES: cached free-name stores from compiled code that keep writing a global after it was
    made read-only (sloppy writes must be silently ignored, strict writes must throw TypeError),
    bypass a global accessor's getter/setter, write the wrong scope when an inner function with
    its own activation assigns a variable of its enclosing function, or lose compound
    assignment-expression results (`r = (total += 1)`, `y = (g = v)`) on free names."""
    check_script(run, workdir, G, "free_name_writes", r'''
globalThis.gCount = 0;
globalThis.gStr = 'a';
function bumpGlobals(n) { for (var i = 0; i < n; i++) { gCount = gCount + i; gStr = gStr + (i % 3); } return gCount + ' ' + gStr.length; }
console.log(bumpGlobals(50), bumpGlobals(10));
Object.defineProperty(globalThis, 'gCount', { writable: false });
console.log('read-only', bumpGlobals(5), gCount);
function strictBump() { 'use strict'; try { gCount = 1; return 'no error'; } catch (e) { return e.name + ': ' + e.message; } }
var sb;
for (var k = 0; k < 10; k++) sb = strictBump();
console.log(sb);
var hits = 0;
Object.defineProperty(globalThis, 'gAcc', { get: function () { hits++; return hits * 10; }, set: function (v) { hits += v; }, configurable: true });
function useAcc(n) { var s = 0; for (var i = 0; i < n; i++) { s += gAcc; gAcc = 1; } return s + ' ' + hits; }
console.log('accessor', useAcc(5), useAcc(3));
var gChain = 0, gLast;
function exprAssign(n) { var r = []; for (var i = 0; i < n; i++) { r.push(gChain += i, gLast = gChain * 2, gChain -= 1); } return r.slice(-3).join(',') + ' ' + gChain + ' ' + gLast; }
for (var k = 0; k < 10; k++) var ea = exprAssign(4);
console.log('expr', ea);
function outer(seed) {
  var total = seed, label = 'L';
  function inner(n) {
    var cap = 0, peek = function () { return cap; };
    for (var i = 0; i < n; i++) { total = total + i; cap = cap + 1; label = label + i; }
    var r = (total += 1);
    return r + ':' + peek() + ':' + total;
  }
  var res = [];
  for (var k = 0; k < 12; k++) res.push(inner(k % 4));
  return res.join(' ') + ' ' + label;
}
console.log(outer(100));
function shadowLater() {
  var x = 1;
  function reader() { var a = 0, f = function () { return a; }; for (var i = 0; i < 3; i++) a += x; return a + f(); }
  var r = [];
  for (var k = 0; k < 10; k++) { r.push(reader()); x++; }
  return r.join(',');
}
console.log(shadowLater());
''', cli=cli)


@tiers
def test_delete_in_compiled_code(run, workdir, cli):
    """CATCHES: compiled `delete` that coerces the key wrongly (numeric, symbol and object keys whose
    toString names a property), returns the wrong boolean for arrays (index vs length), frozen
    objects and string primitives, does not throw the exact TypeError for a nullish base or for
    a non-configurable property in strict code, deletes holes incorrectly, or evaluates
    `delete <non-reference>` without returning true."""
    check_script(run, workdir, G, "delete_in_compiled_code", r'''
function delTest(objs, keys) {
  var out = [];
  for (var i = 0; i < objs.length; i++) {
    var o = objs[i], k = keys[i], r;
    try { r = delete o[k]; } catch (e) { r = e.name + ': ' + e.message; }
    out.push(String(r));
  }
  return out.join(',');
}
var sym = Symbol('s'), objs, d;
function mk() { var a = [1, 2, 3]; var fr = Object.freeze({ z: 1 }); var o = { a: 1, 2: 'two' }; o[sym] = 1; return [o, o, o, a, a, fr, 'str', null, undefined, o, a]; }
for (var k = 0; k < 10; k++) { objs = mk(); d = delTest(objs, ['a', 2, sym, 1, 'length', 'z', 0, 'x', 'y', { toString: function () { return 'a'; } }, -0]); }
console.log(d);
console.log(JSON.stringify(objs[3]), objs[3].length, 0 in objs[3], 1 in objs[3], Object.keys(objs[0]).length, Object.getOwnPropertySymbols(objs[0]).length);
function delStrict(o, k) { 'use strict'; try { return delete o[k]; } catch (e) { return e.name + ': ' + e.message; } }
function delStrictProp(o) { 'use strict'; try { return delete o.z; } catch (e) { return e.name + ': ' + e.message; } }
var ds;
for (var k = 0; k < 10; k++) ds = [delStrict(Object.freeze({ q: 1 }), 'q'), delStrict([1], 'length'), delStrict({ q: 1 }, 'q'), delStrict('abc', 1), delStrictProp(Object.seal({ z: 1 })), delStrictProp(null), delStrictProp({})];
console.log(ds.join('\n'));
function delMisc(o) {
  var a = delete (o.p.q);
  var b = delete (o.p);
  var c = delete [1, 2][0];
  var d = delete o['p' + 1];
  var e = delete o.missing;
  var f = delete Math.PI;
  return [a, b, c, d, e, f, 'p' in o, 'p1' in o].join();
}
var dm;
for (var k = 0; k < 10; k++) dm = delMisc({ p: { q: 1 }, p1: 2 });
console.log(dm);
function holes(n) { var a = []; for (var i = 0; i < n; i++) a.push(i); for (var j = 0; j < n; j += 3) delete a[j]; var s = 0, h = 0; for (var j = 0; j < n; j++) { if (j in a) s += a[j]; else h++; } return s + ':' + h + ':' + a.length + ':' + a.indexOf(undefined) + ':' + JSON.stringify(a.slice(0, 4)); }
console.log(holes(20), holes(1));
''', cli=cli)


@tiers
def test_tdz_in_compiled_code(run, workdir, cli):
    """CATCHES: compiled code that lets a `let`/`const` slot be read, property-accessed, assigned
    through (`x.p = 1`, `x[0] = 2`), updated or typeof-ed before its declaration instead of
    throwing `ReferenceError: cannot access 'x' before initialization`, or that leaves a
    per-iteration `let` in its TDZ state (or initialized) across loop iterations and switch
    cases."""
    check_script(run, workdir, G, "tdz_in_compiled_code", r'''
function tdzLocal(which) {
  try {
    if (which === 0) { x.p = 1; }
    else if (which === 1) { var v = x.p; }
    else if (which === 2) { x++; }
    else if (which === 3) { x[0] = 2; }
    else if (which === 4) { typeof x; }
    else if (which === 5) { x.m(); }
    else { x += 'a'; }
  } catch (e) { return which + ' ' + e.name + ': ' + e.message; }
  let x = { p: 1, m: function () { } };
  return which + ' ok ' + x.p;
}
function tdzPattern() { try { [x] = [1]; } catch (e) { return e.name + ': ' + e.message; } let x; return 'no error'; }
var tz = [];
for (var k = 0; k < 10; k++) { tz = []; for (var w = 0; w < 7; w++) tz.push(tdzLocal(w)); tz.push(tdzPattern()); }
console.log(tz.join('\n'));
function constLater(flag) { try { if (flag) return y * 2; } catch (e) { return e.message; } const y = 21; return y * 2; }
var cl = [];
for (var k = 0; k < 10; k++) cl = [constLater(true), constLater(false)];
console.log(cl.join(' | '));
function perIteration(n) {
  var seen = [];
  for (var i = 0; i < n; i++) {
    try { seen.push(typeof later === 'undefined' ? 'u' : 'd'); } catch (e) { seen.push('T'); }
    let later = i;
    seen.push(later);
  }
  return seen.join('');
}
console.log(perIteration(4));
function switchTdz(v) {
  switch (v) {
    case 0: let s = 'zero'; return s;
    case 1: try { return s; } catch (e) { return e.name; }
    default: return 'other';
  }
}
var st = [];
for (var k = 0; k < 10; k++) st = [switchTdz(0), switchTdz(1), switchTdz(2)];
console.log(st.join(','));
''', cli=cli)


@tiers
def test_element_assignment_expressions(run, workdir, cli):
    """CATCHES: compiled element writes/updates used as expressions that return the wrong value,
    canonicalize keys inconsistently (1, '1', 1.5, -0), call a key object's toString more or
    fewer than once per compound assignment, mis-coerce the old value of `o[k]++` (numeric
    strings, BigInt, holes, null, getters, valueOf objects), or skip the TypeError for compound
    assignment and ++ on a null/undefined base."""
    check_script(run, workdir, G, "element_assignment_expressions", r'''
function setExpr(o, keys) { var out = []; for (var i = 0; i < keys.length; i++) { var r = (o[keys[i]] = i * 2); out.push(r); } return out.join(',') + ' ' + JSON.stringify(o); }
var se;
for (var k = 0; k < 10; k++) se = setExpr({}, ['a', 'b', 1, '2', 1.5, -0, 'a', 'x' + k]);
console.log(se);
function setExprArr(a, keys) { var out = []; for (var i = 0; i < keys.length; i++) out.push(a[keys[i]] = i); out.push(a['length'] = 6); return out.join(',') + ' len=' + a.length + ' ' + JSON.stringify(a) + ' ' + a.foo; }
for (var k = 0; k < 10; k++) se = setExprArr([], [0, '1', 3, 'foo', 9]);
console.log(se);
var ks = 0;
var keyObj = { toString: function () { ks++; return 'kk'; } };
function compoundElem(o, key, n) { var r = []; for (var i = 0; i < n; i++) { r.push(o[key] += i); o[key] -= 1; o[key] *= 2; r.push(o[key] **= 1, o[key] |= 0); } return r.join(',') + ' ' + o[key]; }
var ce;
for (var k = 0; k < 10; k++) { ks = 0; ce = compoundElem({ kk: 1 }, keyObj, 4); }
console.log('compound', ce, 'toString calls per run', ks);
function strConcat(o, n) { for (var i = 0; i < n; i++) { o['s'] += i; o.t += '-'; } return o.s + ' ' + o.t; }
for (var k = 0; k < 10; k++) var sc = strConcat({ s: 'x', t: '' }, 5);
console.log(sc);
function updElem(o, key) { var a = o[key]++; var b = ++o[key]; var c = o[key]--; return [typeof a, a, b, c, String(o[key])].join(','); }
var ue = [];
for (var k = 0; k < 10; k++) ue = [updElem({ x: '5' }, 'x'), updElem({ x: 10n }, 'x'), updElem([, 1], 0), updElem({ x: null }, 'x'), updElem({ get x() { return 3; }, set x(v) { } }, 'x'), updElem([1.5], 0), updElem({ x: { valueOf: function () { return -1; } } }, 'x'), updElem({ x: '0x10' }, 'x'), updElem({ x: true }, 'x')];
console.log(ue.join('\n'));
function nullCompound(o, k) { try { o[k] += 1; return 'no error'; } catch (e) { return e.constructor.name; } }
function nullUpdate(o, k) { try { o[k]++; return 'no error'; } catch (e) { return e.constructor.name; } }
var ne;
for (var k = 0; k < 10; k++) ne = [nullCompound(null, 'a'), nullCompound(undefined, keyObj), nullUpdate(null, 0), nullUpdate(undefined, 'z'), nullCompound({}, 'a'), nullUpdate([], 0)];
console.log(ne.join(','));
''', cli=cli)


@tiers
def test_computed_method_calls_and_instanceof(run, workdir, cli):
    """CATCHES: compiled `o[key](...)` calls that resolve string/number/symbol/object keys to the
    wrong method, lose the receiver (`this` must be `o`), or do not throw a TypeError for a
    nullish base or a non-callable value; and compiled `instanceof` that ignores
    Symbol.hasInstance, mis-walks subclass prototype chains, accepts primitives, or does not throw
    for a non-callable right-hand side."""
    check_script(run, workdir, G, "computed_method_calls_and_instanceof", r'''
function methodElem(o, keys) { var r = []; for (var i = 0; i < keys.length; i++) r.push(o[keys[i]](i)); return r.join(','); }
var msym = Symbol('m');
var mo = { tag: 'T', a: function (x) { return this.tag + 'a' + x; }, 1: function (x) { return 'one' + x; }, '-0': function () { return 'negzero'; } };
mo[msym] = function (x) { return 'sym' + x + (this === mo); };
var me;
for (var k = 0; k < 10; k++) me = methodElem(mo, ['a', 1, msym, '1', { toString: function () { return 'a'; } }, 1.0, '-0']);
console.log(me);
function protoMethods(list) { var r = []; for (var i = 0; i < list.length; i++) r.push(list[i][typeof list[i] === 'number' ? 'toFixed' : 'padStart'](4)); return r.join(' '); }
for (var k = 0; k < 10; k++) var pm = protoMethods([1.25, 'abc', 7, 'x']);
console.log(pm);
function badCall(o, k) { try { return o[k](); } catch (e) { return e.constructor.name; } }
var bc;
for (var k = 0; k < 10; k++) bc = [badCall(null, 'f'), badCall(undefined, 0), badCall({}, 'f'), badCall({ f: 1 }, 'f'), badCall({ f: function () { return 'ok'; } }, 'f'), badCall([function () { return this.length; }], 0)];
console.log(bc.join(','));
function inst(xs, C) { var c = 0; for (var i = 0; i < xs.length; i++) if (xs[i] instanceof C) c++; return c; }
class A {}
class B extends A {}
function F() {}
var BH = { [Symbol.hasInstance]: function (v) { return typeof v === 'number'; } };
var bound = F.bind(null);
var ins;
for (var k = 0; k < 10; k++) ins = [inst([new A, new B, {}, 1, null, undefined], A), inst([new A, new B], B), inst([1, 2, 'x', NaN], BH), inst([new F, Object.create(F.prototype), F], F), inst([new F], bound), inst([[], {}, function () {}], Object), inst([Object.create(null)], Object)];
console.log(ins.join(','));
F.prototype = {};
console.log('after prototype swap', inst([new F], F), inst([Object.create(F.prototype)], F));
function badInst(v, C) { try { return v instanceof C; } catch (e) { return e.name + ': ' + e.message; } }
for (var k = 0; k < 10; k++) var bi = [badInst(1, {}), badInst({}, null), badInst({}, 1)];
console.log(bi.join('\n'));
''', cli=cli)


@tiers
def test_destructuring_iteration_protocol(run, workdir, cli):
    """CATCHES: compiled array destructuring that takes a dense-array shortcut even when the
    iteration protocol is observable -- a patched %ArrayIteratorPrototype%.next or .return, a
    patched Array.prototype[Symbol.iterator], an own iterator on the array, holes reading
    Array.prototype elements, accessor elements, more than 16 targets -- or that forgets to call
    return() when the pattern stops early, or mishandles short Sets/strings/generators/Map
    iterators (missing targets must be undefined)."""
    check_script(run, workdir, G, "destructuring_iteration_protocol", r'''
function destr3(xs) { var [a, b, c] = xs; return a + '|' + b + '|' + c; }
function destr4(src) { var [a, b, c, d] = src; return [a, b, c, d].join('/'); }
function destrBig(xs) { var [a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q] = xs; return [a, h, q].join('/'); }
function destrSkip(xs) { var [, second, , fourth = 'D', ...rest] = xs; return second + fourth + rest.length; }
function* gen3() { yield 1; yield 2; }
function run(label) {
  var r;
  for (var k = 0; k < 12; k++) r = [destr3([7, 8, 9]), destr3([1]), destr3('xy'), destrBig(Array.from({ length: 17 }, function (_, i) { return i; })), destrSkip([1, 2, 3]), destrSkip([1, 2, 3, 4, 5, 6])];
  console.log(label, r.join(' '));
}
run('plain');
var ds;
for (var k = 0; k < 10; k++) ds = [destr4(new Set([1, 2, 3, 4, 5])), destr4('ab'), destr4(gen3()), destr4(new Map([[1, 2]]).keys()), destr4([1, , 3]), destr4(new Uint8Array([9, 8]))];
console.log(ds.join(' '));
var holey = [1, , 3], r1 = [], r2 = [];
for (var k = 0; k < 12; k++) r1 = destr3(holey);
Array.prototype[1] = 'P';
for (var k = 0; k < 12; k++) r2 = destr3(holey);
delete Array.prototype[1];
console.log('holes', r1, r2);
var acc = [1, 2, 3], gets = 0, r3;
Object.defineProperty(acc, 1, { get: function () { gets++; return 'G'; } });
for (var k = 0; k < 12; k++) r3 = destr3(acc);
console.log('accessor elem', r3, gets);
var own = [1, 2, 3], r4;
own[Symbol.iterator] = function* () { yield 'own'; yield 'iter'; };
for (var k = 0; k < 12; k++) r4 = destr3(own);
console.log('own iterator', r4);
var AIP = Object.getPrototypeOf([][Symbol.iterator]());
var origNext = AIP.next, nexts = 0;
AIP.next = function () { nexts++; return origNext.call(this); };
run('patched next');
console.log('next calls', nexts);
AIP.next = origNext;
var returns = 0;
AIP.return = function () { returns++; return { done: true }; };
run('with return');
console.log('return calls', returns);
delete AIP.return;
var origIter = Array.prototype[Symbol.iterator], iters = 0;
Array.prototype[Symbol.iterator] = function () { iters++; return origIter.call(this); };
run('patched @@iterator');
console.log('iterator calls', iters);
Array.prototype[Symbol.iterator] = origIter;
run('restored');
var closed = 0;
var iterable = { [Symbol.iterator]: function () { var n = 0; return { next: function () { return { value: n++, done: n > 10 }; }, return: function () { closed++; return {}; } }; } };
function destrClose() { var [x, y] = iterable; return x + y; }
for (var k = 0; k < 10; k++) var dc = destrClose();
console.log('closed', dc, closed);
function destrNull(v) { try { var [a] = v; return 'ok ' + a; } catch (e) { return e.constructor.name; } }
for (var k = 0; k < 10; k++) var dn = [destrNull(null), destrNull(undefined), destrNull(5), destrNull({}), destrNull('s')];
console.log(dn.join(','));
''', cli=cli)


@tiers
def test_for_head_redeclares_parameter(run, workdir, cli):
    """CATCHES: a tier that handles a `for (var p ...)` / `for (var p in/of ...)` head re-declaring
    a parameter differently from the others. The reference binds such for-heads
    unconditionally at function entry, so the parameter reads `undefined` before the loop
    (this deviates from ECMAScript, where the argument value survives -- pinned as observed);
    a parameter that is NOT re-declared, or is re-declared by a plain `var`, keeps its value."""
    check_script(run, workdir, G, "for_head_redeclares_parameter", r'''
function f(i) { var before = i; for (var i = 0; i < 3; i++); return before + ':' + i; }
function g(k, extra) { var b = k; for (var k in { a: 1, b: 2 }); return b + k + extra; }
function h(x, y) { var s = x + '/' + y; for (var y of [1, 2]) s += y; return s; }
function plainVar(z) { var before = z; var z; var w = z; var z = 9; return before + ':' + w + ':' + z; }
function other(a, b) { var s = a + b; for (var t = 0; t < 2; t++) s += t; return s; }
function caller(n) { var r = []; for (var k = 0; k < n; k++) r.push(f(k), g(k, '!'), h(k, k * 2), plainVar(k), other(k, 1)); return r.slice(-5).join(' '); }
console.log(caller(12));
console.log(f(5), g('x', 1), h('p', 'q'), plainVar('v'), other(3, 4));
''', cli=cli)


@tiers
def test_many_locals_frame(run, workdir, cli):
    """CATCHES: compiled functions with 300 locals, whose frame (locals plus operand stack) no
    longer fits the fixed-size frame buffer: a tier that mis-sizes the oversized frame, does not
    initialize untouched locals to undefined on every call, aliases distant locals, or leaks a
    previous call's values computes different results."""
    names = ["v%d" % i for i in range(300)]
    source = ("function wide(n, seed) {\n  var " + ", ".join(names) + ";\n  var s = 0;\n"
              "  var before = [typeof v0, typeof v150, typeof v299].join(',');\n"
              "  for (var i = 0; i < n; i++) { v0 = i; v299 = (v299 | 0) + seed; v150 = v0 * 2 + v299; s += v150; }\n"
              "  v200 = 'set'; v1 = [v0, v299];\n"
              "  return [before, s, v299, v150, v200, v1, typeof v2, typeof v298].join(':');\n}\n"
              "var r = [];\nfor (var k = 0; k < 12; k++) r.push(wide(k, k + 1));\n"
              "console.log(r.join('\\n'));\nconsole.log(wide(0, 5));\nconsole.log(wide(100, -3));\n")
    check_script(run, workdir, G, "many_locals_frame", source, cli=cli)


@tiers
def test_huge_loop_body(run, workdir, cli):
    """CATCHES: a JIT that mis-encodes conditional branches whose targets end up more than 1 MiB away
    (an 800-statement loop body of property reads compiles to that much machine code): wrong
    branch relaxation jumps into the middle of the body or past the exit, so sums differ, the
    loop never ends, or a later guard failure (a property turning into a string, a getter
    replacing a data property) resumes at the wrong place."""
    stmts = "\n".join("    s = (s + o.p%d * %d) | 0;" % (i % 7, i % 13 + 1) for i in range(800))
    source = ("function huge(o, n) {\n  var s = 0;\n  for (var i = 0; i < n; i++) {\n" + stmts +
              "\n    if (s > 1e6) s = s % 1000;\n  }\n  return s;\n}\n"
              "var o = { p0: 1, p1: 2, p2: 3, p3: 4, p4: 5, p5: 6, p6: 7 };\n"
              "var r = [];\nfor (var k = 0; k < 4; k++) r.push(huge(o, k));\nconsole.log(r.join(' '));\n"
              "var o2 = { p0: 1, p1: 2, p2: 3, p3: 'x', p4: 5, p5: 6, p6: 7 };\n"
              "var gets = 0;\nvar o3 = { p0: 1, p1: 2, p2: 3, p3: 4, p4: 5, get p5() { gets++; return -1; }, p6: 7 };\n"
              "console.log(huge(o2, 2), huge(o3, 2), gets, huge(o, 3), huge({ p0: 0.5 }, 1));\n")
    check_script(run, workdir, G, "huge_loop_body", source, cli=cli)


@tiers
def test_regexp_dead_result_statements(run, workdir, cli):
    """CATCHES: a JIT that fuses dead-result statements such as `/(\\w+)@(\\w+)/.exec(list[i]);`,
    `list[i].replace(/re/, 'X');`, `list[i].match(/re/);` or a global-regexp exec loop and then
    skips their observable effects -- the legacy RegExp statics ($1, $2, lastMatch, leftContext,
    rightContext, input, lastParen) and a global regexp's lastIndex -- or keeps using the fused
    path after the subject list gains numbers, holes, accessor elements, String objects or a
    non-array value, or after RegExp.prototype.exec / String.prototype.replace are patched."""
    check_script(run, workdir, G, "regexp_dead_result_statements", r'''
var inputs = ['alice@example', 'bob@test', 'no-at-here', 'carol@site'];
var subjects = ['dave@host', 'erin@node', 'plain', 'frank@box'];
function scanExec(n) { for (var i = 0; i < n; i++) { /(\w+)@(\w+)/.exec(inputs[i]); } return RegExp.$1 + '|' + RegExp.$2 + '|' + RegExp.lastMatch; }
function scanConst() { /(\d+)-(\d+)/.exec('call 555-1234 now'); return RegExp.$1 + '|' + RegExp.$2 + '|' + RegExp.leftContext + '|' + RegExp.rightContext; }
function scanReplace(n) { for (var i = 0; i < n; i++) { subjects[i].replace(/(\w)(\w*)@/, 'X'); } return RegExp.$1 + '|' + RegExp.$2 + '|' + RegExp.input; }
function scanMatch(n) { for (var i = 0; i < n; i++) { subjects[i].match(/@(\w+)/); } return RegExp.$1 + '|' + RegExp.lastParen; }
var rx = /([a-z])(\d)/g;
var strs = ['a1 b2', 'c3', 'zz', 'q9 r8 s7'];
function loopExec() { for (var i = 0; i < 4; i++) rx.exec(strs[i]); return rx.lastIndex + '|' + RegExp.$1 + RegExp.$2; }
function all(label) {
  var r;
  for (var k = 0; k < 12; k++) { r = [scanExec(4), scanExec(3), scanConst(), scanReplace(4), scanMatch(3), loopExec()]; }
  console.log(label + '\n  ' + r.join('\n  '));
}
all('plain');
inputs[3] = 12345; strs[1] = 77; subjects[3] = new String('gina@obj');
all('non-string element');
inputs.length = 3; inputs[3] = undefined; delete inputs[2]; strs[2] = undefined;
all('holes');
Object.defineProperty(inputs, 1, { get: function () { return 'getter@prop'; } });
all('accessor element');
var origExec = RegExp.prototype.exec, calls = 0;
RegExp.prototype.exec = function (s) { calls++; return origExec.call(this, s); };
all('patched exec');
console.log('exec calls', calls);
RegExp.prototype.exec = origExec;
var origReplace = String.prototype.replace, rcalls = 0;
String.prototype.replace = function (a, b) { rcalls++; return origReplace.call(this, a, b); };
all('patched replace');
console.log('replace calls', rcalls);
String.prototype.replace = origReplace;
inputs = 'not an array'; subjects = ['x@y', 'ab@cd', 'ef@gh', 'ij@kl'];
all('string global');
subjects = { 0: 'p@q', 1: 'r@s', 2: 't@u', 3: 'v@w', length: 4 };
all('array-like global');
''', cli=cli)


@tiers
def test_builtin_call_intrinsics(run, workdir, cli):
    """CATCHES: JIT call intrinsics for Object.hasOwn, Function.prototype.apply, dead-result
    RegExp#exec / String#split / String#replace that answer from a shortcut when the arguments
    are unusual: hasOwn must not see inherited keys or array indices wrongly, apply must honour
    holes, array-likes, accessor elements, extra arguments, mapped (sloppy) vs unmapped (strict)
    arguments objects and native targets, exec must advance lastIndex for g/y regexps and call
    an overridden subclass exec, split must call a custom Symbol.split, and replace must call a
    replacer function for every match."""
    check_script(run, workdir, G, "builtin_call_intrinsics", r'''
function countOwn(objs, key) { var c = 0; for (var i = 0; i < objs.length; i++) { if (Object.hasOwn(objs[i], key)) c++; } return c; }
var proto = { inherited: 1 };
var objs = [{ a: 1 }, Object.create(proto), { a: undefined }, [1, 2], Object.assign(Object.create(proto), { a: 2 }), function a() {}];
var r = [];
for (var k = 0; k < 10; k++) r = [countOwn(objs, 'a'), countOwn(objs, 'inherited'), countOwn(objs, '0'), countOwn(objs, 'length'), countOwn(objs, 'name')];
console.log('hasOwn', r.join(','));
function target(a, b, c) { return [this && this.tag, a, b, c, arguments.length].join('/'); }
function viaApply(thisArg, list) { var out = []; for (var i = 0; i < 3; i++) out.push(target.apply(thisArg, list)); return out[2]; }
function sloppyArgs(a, b) { a = 'changed'; return target.apply({ tag: 'S' }, arguments); }
function strictArgs(a, b) { 'use strict'; a = 'changed'; return target.apply({ tag: 'T' }, arguments); }
var ap = [];
for (var k = 0; k < 12; k++) ap = [viaApply({ tag: 'o' }, [1, 2, 3]), viaApply({ tag: 'h' }, [1, , 3]), viaApply({ tag: 'l' }, { length: 2, 0: 'x', 1: 'y' }), viaApply({ tag: 'g' }, Object.defineProperty([1, 2], 1, { get: function () { return 'G'; } })), viaApply({ tag: 'n' }, [1, 2, 3, 4]), sloppyArgs(1, 2), strictArgs(1, 2), viaApply({ tag: 'e' }, [])];
console.log('apply', ap.join(' '));
function nat(list) { var s = 0; for (var i = 0; i < 3; i++) s += Math.max.apply(null, list); return s; }
var na;
for (var k = 0; k < 12; k++) na = [nat([1, 5, 2]), nat({ length: 2, 0: 4, 1: 9 }), nat([])];
console.log('native apply', na.join(','));
function badApply(list) { try { return target.apply(null, list); } catch (e) { return e.constructor.name; } }
for (var k = 0; k < 10; k++) var ba = [badApply(1), badApply('ab'), badApply(null)];
console.log('bad apply', ba.join(' '));
function execDiscard(re, strs) { for (var i = 0; i < strs.length; i++) { re.exec(strs[i]); } return re.lastIndex + ':' + RegExp.lastMatch; }
var ed = [];
for (var k = 0; k < 12; k++) ed = [execDiscard(/b+/g, ['abbbc', 'bb', 'xb']), execDiscard(/c(\d)/y, ['c1c2', 'c3', 'zc4']), execDiscard(/q/, ['aq', 'qq']), execDiscard(/z/g, ['none'])];
console.log('exec discard', ed.join(' '));
var sub = new (class extends RegExp { exec(s) { this.seen = (this.seen || 0) + 1; return super.exec(s); } })('o');
console.log('subclass exec', execDiscard(sub, ['foo', 'bar']), sub.seen);
function splitDiscard(s, seps) { var n = 0; for (var i = 0; i < seps.length; i++) { s.split(seps[i]); n++; } return n; }
var splits = 0;
var custom = { [Symbol.split]: function (str) { splits++; return [str]; } };
var sd;
for (var k = 0; k < 12; k++) sd = splitDiscard('a,b;c', [',', ';', /[,;]/, custom, '']);
console.log('split discard', sd, splits);
function replaceDiscard(strs, re, rep) { for (var i = 0; i < strs.length; i++) { strs[i].replace(re, rep); } return RegExp.lastMatch; }
var fnCalls = 0, rd;
for (var k = 0; k < 12; k++) rd = [replaceDiscard(['a1b2', 'c3'], /\d/g, function (m) { fnCalls++; return m + m; }), replaceDiscard(['xyz'], 'y', '$&$&'), replaceDiscard(['k9'], /(\d)/, '[$1]')];
console.log('replace discard', rd.join(','), fnCalls);
''', cli=cli)


@tiers
def test_for_of_head_forms(run, workdir, cli):
    """CATCHES: compiled for-of loops whose head is not a fresh declaration -- a global name, a
    variable captured by a closure, a member or element target (whose key expression must run
    once per iteration), let/const destructuring, assignment patterns, or an outer const (must
    throw TypeError) -- writing the wrong binding, plus iterator-close bookkeeping: labeled
    continue/break across nested for-of, return and throw inside the body must call return()
    exactly once per abandoned iterator, while normal exhaustion must not."""
    check_script(run, workdir, G, "for_of_head_forms", r'''
var gItem;
const FIXED = 'fixed';
function globalHead(list) { var n = 0; for (gItem of list) n++; return n + ':' + gItem; }
function capturedHead(list) { var cap, seen = [], peek = function () { return cap; }; for (cap of list) seen.push(peek()); return seen.join('') + ':' + peek(); }
function memberHeads(list) { var o = { p: 0 }, arr = [], j = 0, log = []; for (o.p of list) log.push(o.p); for (arr[j++] of list); return log.join('') + ':' + arr.join('') + ':' + j; }
function patternHeads() {
  var log = [], a, b;
  for (const [k, v] of new Map([['m', 1], ['n', 2]])) log.push(k + v);
  for (let { length, 0: first } of ['abc', 'de']) log.push(first + length);
  for ([a, b = 'B'] of [['x', 'y'], ['z']]) log.push(a + b);
  for ({ a, b } of [{ a: 'p', b: 'q' }]) log.push(a + b);
  return log.join(' ');
}
function constHead(list) { try { for (FIXED of list) return 'assigned'; return 'empty'; } catch (e) { return e.constructor.name; } }
var r;
for (var k = 0; k < 10; k++) r = [globalHead(['x', 'y']), capturedHead(['a', 'b']), memberHeads(['m', 'n']), patternHeads(), constHead([1]), constHead([])];
console.log(r.join('\n'));
console.log(gItem, FIXED);
function earlyExit(list) {
  var closed = 0, it = { [Symbol.iterator]: function () { var i = 0; return { next: function () { return { value: list[i++], done: i > list.length }; }, return: function () { closed++; return {}; } }; } };
  var out = [];
  outer: for (var x of it) {
    for (var y of it) { if (y === 'b') continue outer; if (x === 'c') break outer; out.push(x + y); }
  }
  function ret() { for (var z of it) { if (z === 'b') return z; } return 'none'; }
  out.push(ret());
  try { for (var w of it) { if (w === 'a') throw new Error('boom'); } } catch (e) { out.push(e.message); }
  for (var v of it) out.push(v);
  return out.join(',') + ' closed=' + closed;
}
var ee;
for (var k = 0; k < 10; k++) ee = earlyExit(['a', 'b', 'c']);
console.log(ee);
''', cli=cli)


@tiers
def test_hot_functions_with_uncompiled_constructs(run, workdir, cli):
    """CATCHES: hot functions containing constructs the bytecode compiler declines (try/finally with
    return/break inside loops, destructuring catch parameters, logical assignment expressions,
    direct eval, super calls, optional calls with spread, `with`, nested for-of with return,
    assignment to a captured const) must still run with exact tree-walker semantics: finally
    overriding return values, short-circuit assignment not evaluating its RHS, eval seeing
    locals, and the TypeError for writing a const."""
    check_script(run, workdir, G, "hot_functions_with_uncompiled_constructs", r'''
function finallyLoop(n) {
  var log = [];
  for (var i = 0; i < n; i++) {
    try { if (i === 1) continue; if (i === 3) break; log.push('t' + i); } finally { log.push('f' + i); }
  }
  return log.join('');
}
function finallyReturn(x) { try { if (x) return 'try'; throw new Error('e'); } catch (e) { return 'catch'; } finally { if (x === 2) return 'finally'; } }
function catchPattern(v) { try { throw v; } catch ({ message, code = 'none' }) { return message + ':' + code; } }
function logicalAssign(o) { var calls = 0, f = function () { calls++; return 'rhs'; }; var r = [(o.a ||= f()), (o.b &&= f()), (o.c ??= f()), (o.d ??= f())]; return r.join(',') + ' calls=' + calls; }
function evalSees(n) { var hidden = n * 2; return eval('hidden + 1'); }
class Base { greet(x) { return 'base' + x; } }
class Kid extends Base { greet(x) { return super.greet(x) + '!'; } }
function optionalSpread(o, args) { return o.m?.(...args) + '|' + o.missing?.(...args); }
function withScope(o) { with (o) { return a + b; } }
function nestedForOf(lists) { for (var a of lists) { for (var b of a) { if (b === 'stop') return 'returned ' + a.length; } } return 'none'; }
function constWrite() { const c = 1; var f = function () { return c; }; try { c = 2; } catch (e) { return e.constructor.name + ' ' + f(); } return 'no error'; }
function letNoInit(n) { var r = []; for (let a, b = 0; b < n; b++) { r.push(a === undefined ? 'u' : a); a = b; } return r.join(''); }
var r = [];
for (var k = 0; k < 12; k++) {
  r = [finallyLoop(5), finallyReturn(1), finallyReturn(0), finallyReturn(2), catchPattern(new Error('boom')), catchPattern({ message: 'm', code: 7 }),
       logicalAssign({ a: 0, b: 1, c: null, d: false }), evalSees(k), new Kid().greet(k), optionalSpread({ m: function (a, b) { return a + b; } }, [1, 2]),
       withScope({ a: 'x', b: 'y' }), nestedForOf([['a'], ['b', 'stop']]), nestedForOf([[]]), constWrite(), letNoInit(4)];
}
console.log(r.join('\n'));
''', cli=cli)


@tiers
def test_vm_operator_edge_cases(run, workdir, cli):
    """CATCHES: VM/JIT operator paths for unusual operands: unary +/- on numbers, -0, strings,
    booleans, null, arrays; ++/-- on local BigInt, string, null, valueOf objects and Dates whose
    result is used (post forms yield the coerced old value); call/new/method spread of strings,
    Sets, Maps, generators, arguments, typed arrays, holes and >16 elements, with a TypeError for
    non-iterables; `o.s += 'x'` on non-string, frozen and accessor properties; element writes and
    compound writes through a non-local object with boolean/symbol/object/null keys; and errors
    from `this.x` in strict calls and throwing getters."""
    check_script(run, workdir, G, "vm_operator_edge_cases", r'''
function unary(xs) { var r = []; for (var i = 0; i < xs.length; i++) { var x = xs[i]; r.push(+x, -x); } return r.map(function (v) { return Object.is(v, -0) ? '-0' : String(v); }).join(','); }
var u;
for (var k = 0; k < 10; k++) u = unary([1.5, -0, 0, NaN, '7', '', ' 12 ', true, null, undefined, [5], '0x1f', -Infinity]);
console.log(u);
function badUnary(v) { try { return +v; } catch (e) { return e.constructor.name; } }
for (var k = 0; k < 10; k++) var bu = [badUnary(1n), badUnary(Symbol('s')), badUnary({ valueOf: function () { return '4'; } })];
console.log(bu.join(','));
function updLocals() { var b = 1n, s = '5', n = null, o = { valueOf: function () { return 10; } }, d = new Date(0), t = true, p = '0x10', q = 'x'; var r = [b++, ++b, b--, --b, s--, --s, n++, ++n, o--, --o, typeof d++, d, t++, t, ++p, p, --q, q]; return r.map(String).join(','); }
var ul;
for (var k = 0; k < 10; k++) ul = updLocals();
console.log(ul);
function sum3(a, b, c) { return [a, b, c].join('+'); }
function* gen() { yield 'g1'; yield 'g2'; yield 'g3'; }
function spreadArgs() { return sum3(...arguments); }
function spreadCall(xs) { return sum3(...xs); }
function spreadMax(xs) { return Math.max(...xs); }
function spreadMixed(a, xs) { return sum3(a, ...xs); }
function spreadMethod(o, xs) { return o.m(...xs); }
function C(a, b) { this.v = a + b; }
function spreadNew(xs) { return new C(...xs).v; }
var o = { tag: 'T', m: function (a, b) { return this.tag + a + b; } };
var twenty = Array.from({ length: 20 }, function (_, i) { return (i * 7) % 19; });
var sp;
for (var k = 0; k < 12; k++) {
  sp = [spreadCall([1, 2, 3]), spreadCall('xyz'), spreadCall(new Set([1, 2])), spreadCall(new Map([[1, 2]])), spreadCall(gen()), spreadArgs(4, 5, 6, 7), spreadCall(new Uint8Array([9, 8, 7])), spreadCall([1, , 3]), spreadCall(''), spreadMax(twenty), spreadMax([]), spreadMixed(1, [2]), spreadMixed(0, 'ab'), spreadMethod(o, ['p', 'q']), spreadMethod(o, 'rs'), spreadNew([3, 4]), spreadNew('ab')].join(' ');
}
console.log(sp);
function badSpread(v) { try { return sum3(...v); } catch (e) { return e.constructor.name; } }
for (var k = 0; k < 10; k++) var bs = [badSpread(5), badSpread(null), badSpread({}), badSpread(undefined), badSpread({ [Symbol.iterator]: function () { return {}; } })];
console.log(bs.join(','));
function appendFallbacks(objs) { var r = []; for (var i = 0; i < objs.length; i++) { var o = objs[i]; o.s += 'x'; o.s += 'y'; r.push(String(o.s)); } return r.join(','); }
var setterLog = [], af;
for (var k = 0; k < 10; k++) { setterLog = []; af = appendFallbacks([{ s: 'a' }, { s: 1 }, { s: null }, Object.freeze({ s: 'f' }), { get s() { return 'G'; }, set s(v) { setterLog.push(v); } }, { s: ['arr'] }, {}]); }
console.log(af, setterLog.join('|'));
var holder = { inner: { a: 1 }, nil: null };
function nonLocalElems(keys) { var r = []; for (var i = 0; i < keys.length; i++) { r.push(holder.inner[keys[i]] = i); holder.inner[keys[i]] += 10; r.push(holder.inner[keys[i]]); } return r.join(','); }
var ksym = Symbol('ks'), nl;
for (var k = 0; k < 10; k++) nl = nonLocalElems(['a', 1, true, ksym, { toString: function () { return 'obj'; } }, null, 2.5]);
console.log(nl, Object.keys(holder.inner).join(','), holder.inner[ksym]);
function nullRead(k) { try { return holder.nil[k]; } catch (e) { return e.constructor.name; } }
function nullCompound(k) { try { holder.nil[k] += 1; return 'no'; } catch (e) { return e.constructor.name; } }
var nr;
for (var k = 0; k < 10; k++) nr = [nullRead('a'), nullRead(0), nullCompound({}), nullCompound(ksym), nullRead.call(null, 'length')];
console.log(nr.join(','));
function strictThis() { 'use strict'; return this.x; }
function thisGetter() { return this.boom; }
var thrower = { get boom() { throw new RangeError('getter threw'); } };
function thisErrors() { var r = []; try { strictThis(); } catch (e) { r.push(e.constructor.name); } try { thisGetter.call(thrower); } catch (e) { r.push(e.message); } r.push(thisGetter.call({ boom: 'ok' }), thisGetter.call('str')); return r.join(','); }
var te;
for (var k = 0; k < 10; k++) te = thisErrors();
console.log(te);
''', cli=cli)


@tiers
def test_assignment_expression_forms(run, workdir, cli):
    """CATCHES: compiled assignment expressions whose VALUE is used: compound assignment to a local,
    a property and a computed element of a call result (base and key evaluated once, Get
    before the RHS), assignments nested inside an element store's key or value (`arr[i] =
    (o.x = v)`, `arr[(o.y = i) + 9]`, destructuring assignments as values), parenthesized
    update targets, `delete` of non-references and parenthesized references, and destructuring
    into let/const bindings captured by closures, including computed keys with rest."""
    check_script(run, workdir, G, "assignment_expression_forms", r'''
function assignExprs(n) {
  var x = 1, o = { p: 1, q: 'a' }, out = [], calls = 0;
  function holder() { calls++; return o; }
  for (var i = 0; i < n; i++) {
    var y = (x += 2), z = (x *= 3), w = (x -= 1), v = (x %= 7), u = (x <<= 2);
    var p = (o.p += i), q = (o.q += 'b'), r2 = (o.p **= 1);
    var e1 = (holder()['p'] += 10), e2 = (holder()[i % 2 ? 'p' : 'q'] += 1);
    out.push([y, z, w, v, u, p, q, r2, e1, e2].join('/'));
  }
  return out.join(' ') + ' | ' + x + ' ' + JSON.stringify(o) + ' calls=' + calls;
}
var ae;
for (var k = 0; k < 10; k++) ae = assignExprs(3);
console.log(ae);
function fusedDeps(arr, o) {
  var j = 0, a, b;
  for (var i = 0; i < 3; i++) {
    arr[i] = (o.x = i * 2);
    arr[i + 3] = (o[j++] = i);
    arr[i + 6] = ([a, b] = [i, i + 1])[1];
    arr[(o.y = i) + 9] = a + b;
  }
  return arr.join(',') + ' ' + JSON.stringify(o);
}
var fd;
for (var k = 0; k < 10; k++) fd = fusedDeps([], {});
console.log(fd);
function deleteForms(o) {
  var n = 0;
  function f() { n++; return o; }
  var r = [delete (o.a), delete ((o)['b']), delete f(), delete 1, delete (o, o.c), delete o.d.e, delete f().z];
  return r.join(',') + ' ' + JSON.stringify(o) + ' n=' + n;
}
var df;
for (var k = 0; k < 10; k++) df = deleteForms({ a: 1, b: 2, c: 3, d: { e: 4, f: 5 } });
console.log(df);
function destructCapturedLet(src) {
  let [a, b] = src;
  const { c, d: [e] } = { c: src[0], d: [src[1]] };
  var get = function () { return a + b + c + e; };
  [a, b] = [b, a];
  return get();
}
var dl;
for (var k = 0; k < 10; k++) dl = destructCapturedLet(['x', 'y']);
console.log(dl);
function computedPattern(o, key) { var { [key]: v, ...rest } = o; return v + ':' + JSON.stringify(rest); }
var cp = [];
for (var k = 0; k < 10; k++) cp.push(computedPattern({ a: 1, b: 2, c: 3 }, k % 2 ? 'a' : 'c'));
console.log(cp.slice(-2).join(' '));
function patternHeadsClosure(list) { var a, b, fns = []; for ([a, b = 'D'] of list) fns.push(function () { return a + b; }); return fns.map(function (f) { return f(); }).join(',') + ' ' + a + b; }
var ph;
for (var k = 0; k < 10; k++) ph = patternHeadsClosure([['x', 'y'], ['z']]);
console.log(ph);
function parenUpdate(n) { var x = 0, o = { v: 0 }, r = []; for (var i = 0; i < n; i++) { (x)++; r.push(++(o.v), (o['v'])--); } return x + ':' + o.v + ':' + r.join(''); }
var pu;
for (var k = 0; k < 10; k++) pu = parenUpdate(5);
console.log(pu);
''', cli=cli)


@tiers
def test_global_script_name_caches(run, workdir, cli):
    """CATCHES: name caches of functions declared at the top level of a classic script (-e), where
    free names resolve to global object properties and global lexical bindings: writes through
    the cache must stop once the global property becomes read-only, accessor globals must call
    their getter on every read, and a global `let` read from a function before its declaration
    must throw ReferenceError every time and then see the value once initialized."""
    code = r'''
var gCount = 0; let gLet = 1; globalThis.gProp = 2;
function bump(n) { for (var i = 0; i < n; i++) { gCount = gCount + i; gProp = gProp + 1; gLet = gLet * 2 % 1000; } return gCount + ':' + gProp + ':' + gLet; }
console.log(bump(10), bump(10));
Object.defineProperty(globalThis, 'gProp', { writable: false });
console.log(bump(3), gProp, Object.getOwnPropertyDescriptor(globalThis, 'gCount').writable);
var hits = 0;
Object.defineProperty(globalThis, 'gAcc', { get: function () { return ++hits; }, configurable: true });
function readAcc(n) { var s = 0; for (var i = 0; i < n; i++) s += gAcc; return s; }
console.log(readAcc(5), readAcc(5));
Object.defineProperty(globalThis, 'gAcc', { value: 100, writable: true });
console.log(readAcc(2), hits);
function readLate() { try { return lateLet; } catch (e) { return e.name; } }
var rl = [];
for (var k = 0; k < 10; k++) rl.push(readLate());
let lateLet = 'now';
rl.push(readLate());
console.log(rl.join(','));
function sloppyCreate(n) { for (var i = 0; i < n; i++) { createdLater = i; } return typeof createdLater; }
console.log(sloppyCreate(3), createdLater, delete globalThis.createdLater, typeof createdLater);
'''
    result = run([*cli, "-e", code])
    assert_result(result, G / "global_script_name_caches.golden")


@tiers
def test_class_private_members_in_hot_code(run, workdir, cli):
    """CATCHES: hot methods using private fields/methods, static private state, accessors, super
    property/method access, `#x in o` brand checks, `in` with string/number/symbol keys and
    `typeof` of undeclared names: a tier that mis-resolves `this.#count++` or super.value,
    skips the TypeError for a private read on a foreign object or for `in` on a primitive, or
    answers `typeof undeclared` with a ReferenceError."""
    check_script(run, workdir, G, "class_private_members_in_hot_code", r'''
class Counter {
  #count = 0; static #instances = 0; label = 'c';
  static made() { return Counter.#instances; }
  constructor(start) { this.#count = start; Counter.#instances++; }
  #bump(n) { this.#count += n; return this.#count; }
  get value() { return this.#count; }
  set value(v) { this.#count = v * 2; }
  tick(n) { var s = 0; for (var i = 0; i < n; i++) s += this.#bump(i % 3); return s; }
  static isCounter(o) { return #count in o; }
  incr() { return ++this.#count; }
  post() { return this.#count++; }
}
class Sub extends Counter { constructor() { super(10); this.extra = 1; } get value() { return super.value + 1000; } tick(n) { return super.tick(n) + this.extra; } }
function hot(objs) { var r = []; for (var i = 0; i < objs.length; i++) { var o = objs[i]; r.push(o.tick(5), o.value, o.incr(), o.post(), Counter.isCounter(o), 'label' in o, typeof o.tick, o instanceof Sub); o.value = i; r.push(o.value); } return r.join(','); }
var res;
for (var k = 0; k < 10; k++) res = hot([new Counter(1), new Sub()]);
console.log(res, Counter.made());
function privateBrand(o) { try { return Counter.isCounter(o) + ':' + Counter.prototype.tick.call(o, 1); } catch (e) { return e.constructor.name; } }
var pb;
for (var k = 0; k < 10; k++) pb = [privateBrand({}), privateBrand(new Sub()), privateBrand(Object.create(Counter.prototype))];
console.log(pb.join(' '));
function typeofs(vals) { var r = []; for (var i = 0; i < vals.length; i++) r.push(typeof vals[i], typeof undeclaredThing, typeof vals[i]?.x); return r.join(','); }
var ty;
for (var k = 0; k < 10; k++) ty = typeofs([1, 'a', null, undefined, {}, [], function () {}, 1n, Symbol('s'), true]);
console.log(ty);
function inOps(o, keys) { var r = []; for (var i = 0; i < keys.length; i++) r.push(keys[i] in o); return r.join(','); }
var io;
for (var k = 0; k < 10; k++) io = [inOps({ a: 1, 0: 2 }, ['a', 'b', 0, '0', 'toString', Symbol.iterator]), inOps([1, 2], [0, 1, 2, 'length', -0]), inOps(Object.create({ p: 1 }), ['p'])];
console.log(io.join(' | '));
function badIn(v) { try { return 'x' in v; } catch (e) { return e.constructor.name; } }
var bi;
for (var k = 0; k < 10; k++) bi = [badIn(1), badIn('str'), badIn(null)];
console.log(bi.join(','));
''', cli=cli)
