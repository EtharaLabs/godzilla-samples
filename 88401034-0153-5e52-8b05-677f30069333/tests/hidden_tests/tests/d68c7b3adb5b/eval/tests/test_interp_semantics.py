"""Language-semantics coverage for lumen-cli: realms, `with`, eval, Annex B, arguments, classes,
proxies, receivers, disposal, ShadowRealm and GC behaviour, checked on every execution tier."""

import pytest

from conftest import err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]


@pytest.mark.parametrize("tier", TIERS)
def test_cross_realm_intrinsics(js, golden, tier):
    """CATCHES: a realm created by $262.createRealm that shares the main realm's intrinsics (Array, Function, error constructors) or does not share the well-known symbols, or evaluates evalScript/indirect eval in the wrong global, fails this."""
    code = r"""var r = $262.createRealm();
var g = r.global;
var out = [];
out.push('distinct globals: ' + (g !== globalThis) + ' ' + (g.Array !== Array) + ' ' + (g.Object.prototype !== Object.prototype));
var a = new g.Array(1, 2, 3);
out.push('foreign array: isArray=' + Array.isArray(a) + ' instanceof Array=' + (a instanceof Array) + ' instanceof g.Array=' + (a instanceof g.Array));
out.push('shared symbols: ' + (g.Symbol.iterator === Symbol.iterator) + ' ' + (g.Symbol.toStringTag === Symbol.toStringTag) + ' ' + (g.Symbol.for('k') === Symbol.for('k')));
out.push('spread foreign: ' + [...a].join('+') + ' concat: ' + JSON.stringify([0].concat(a)));
out.push('evalScript: ' + r.evalScript('var realmVar = 40; realmVar + 2') + ' ' + g.realmVar + ' ' + typeof globalThis.realmVar);
out.push('indirect eval: ' + g.eval('typeof realmVar') + ' ' + g.eval(7) + ' ' + g.eval());
out.push('this in realm: ' + r.evalScript('this === globalThis') + ' ' + (r.evalScript('globalThis') === g));
var f = g.Function('return this');
out.push('Function ctor this: ' + (f() === g) + ' proto=' + (Object.getPrototypeOf(f) === g.Function.prototype));
try { r.evalScript('throw new TypeError("inner")'); } catch (e) {
  out.push('thrown: ' + (e instanceof TypeError) + ' ' + (e instanceof g.TypeError) + ' ' + e.name + ': ' + e.message);
}
try { r.evalScript('var 1x'); } catch (e) {
  out.push('syntax: ' + (e.constructor === SyntaxError) + ' ' + e.name);
}
try { g.eval('null.p'); } catch (e) { out.push('eval error realm: ' + (e instanceof g.TypeError) + ' ' + (e instanceof TypeError)); }
var r2 = r.createRealm();
out.push('nested realm: ' + (r2.global !== g) + ' ' + (r2.global.Object !== g.Object));
out.push('protos: ' + Object.getPrototypeOf(g.Object.prototype) + ' ' + (Object.getPrototypeOf(g.Function.prototype) === g.Object.prototype));
var mapped = g.eval('[1,2,3].map(function (x) { return x * 2; })');
out.push('mapped: ' + JSON.stringify(mapped) + ' ' + (Object.getPrototypeOf(mapped) === g.Array.prototype));
out.push('toString tag: ' + Object.prototype.toString.call(new g.Map()) + ' ' + Object.prototype.toString.call(a));
out.push('json: ' + JSON.stringify(g.JSON.parse('{"k":[1,{"z":null}]}')) + ' ' + g.JSON.stringify({ q: [1, 'x'] }));
out.push('main evalScript: ' + $262.evalScript('1 + 2') + ' nonstring=' + r.evalScript(5));
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("cross_realm_intrinsics")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_cross_realm_new_target_prototype_fallback(js, golden, tier):
    """CATCHES: GetPrototypeFromConstructor that falls back to the current realm's intrinsic (instead of new.target's realm) when new.target.prototype is not an object, or that fails to unwrap bound/proxy new.targets, fails this."""
    code = r"""var other = $262.createRealm().global;
var C = new other.Function();
C.prototype = null;
var out = [];
function check(label, ctor, args, protoName) {
  try {
    var o = Reflect.construct(ctor, args, C);
    var expected = protoName.split('.').reduce(function (acc, k) { return acc[k]; }, other);
    out.push(label + ': ' + (Object.getPrototypeOf(o) === expected) + ' local=' + (Object.getPrototypeOf(o) === ctor.prototype));
  } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); }
}
check('Object', Object, [], 'Object.prototype');
check('Array', Array, [3], 'Array.prototype');
check('Function', Function, ['return 1'], 'Function.prototype');
check('String', String, ['s'], 'String.prototype');
check('Number', Number, [1], 'Number.prototype');
check('Boolean', Boolean, [true], 'Boolean.prototype');
check('Error', Error, ['m'], 'Error.prototype');
check('RangeError', RangeError, ['m'], 'RangeError.prototype');
check('Map', Map, [], 'Map.prototype');
check('Promise', Promise, [function () {}], 'Promise.prototype');
check('Date', Date, [0], 'Date.prototype');
check('RegExp', RegExp, ['a'], 'RegExp.prototype');
check('ArrayBuffer', ArrayBuffer, [8], 'ArrayBuffer.prototype');
// bound and proxy newTargets unwrap to their target's realm
var bound = C.bind(null);
var o1 = Reflect.construct(Array, [], bound);
out.push('bound newTarget: ' + (Object.getPrototypeOf(o1) === other.Array.prototype));
var px = new Proxy(C, {});
var o2 = Reflect.construct(Object, [], px);
out.push('proxy newTarget: ' + (Object.getPrototypeOf(o2) === other.Object.prototype));
var rev = Proxy.revocable(C, {});
rev.revoke();
try { Reflect.construct(Object, [], rev.proxy); } catch (e) { out.push('revoked: ' + e.name + ': ' + e.message); }
// same-realm newTarget with primitive prototype falls back to the local intrinsic
function L() {}
L.prototype = 42;
out.push('local fallback: ' + (Object.getPrototypeOf(Reflect.construct(Array, [], L)) === Array.prototype));
// class extending a foreign base
class Sub extends other.Array {}
var s = new Sub(); s.push(1, 2);
out.push('subclass foreign: ' + (s instanceof Sub) + ' ' + Array.isArray(s) + ' ' + s.length + ' ' + (Object.getPrototypeOf(Sub.prototype) === other.Array.prototype));
function UserCtor() { this.made = true; }
class UserClass { constructor() { this.k = 1; } }
var C2 = new other.Function(); C2.prototype = 1;
function chk(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
chk('user function newTarget', function () { var o = Reflect.construct(UserCtor, [], C2); return (Object.getPrototypeOf(o) === other.Object.prototype) + ' ' + o.made; });
chk('class newTarget', function () { var o = Reflect.construct(UserClass, [], C2); return (Object.getPrototypeOf(o) === other.Object.prototype) + ' ' + o.k; });
chk('user function bound newTarget', function () { return Object.getPrototypeOf(Reflect.construct(UserCtor, [], C2.bind())) === other.Object.prototype; });
chk('user function proxy newTarget', function () { return Object.getPrototypeOf(Reflect.construct(UserCtor, [], new Proxy(C2, {}))) === other.Object.prototype; });
chk('newTarget revoked during prototype read', function () { var r = Proxy.revocable(C2, { get: function (t, k) { if (k === 'prototype') { r.revoke(); return undefined; } return t[k]; } }); return Reflect.construct(UserCtor, [], r.proxy); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("cross_realm_new_target_prototype_fallback")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_evalscript_global_declaration_instantiation(js, golden, tier):
    """CATCHES: a script evaluator that skips GlobalDeclarationInstantiation checks (let/var clashes, restricted globals, CanDeclareGlobalFunction/Var on a non-extensible global) or misreports script completion values fails this."""
    code = r"""function t(label, f) { try { console.log(label, f()); } catch (e) { console.log(label, e.name + ': ' + e.message); } }
t('script-let', () => $262.evalScript('let scriptLet = 1; scriptLet + 1'));
t('script-let-again', () => $262.evalScript('var scriptLet;'));
t('script-let-dup', () => $262.evalScript('let scriptLet = 2;'));
t('script-restricted', () => $262.evalScript('let NaN = 1;'));
t('script-class-dup', () => $262.evalScript('class scriptLet {}'));
t('script-var-then-let', () => { $262.evalScript('var sv = 1;'); return $262.evalScript('let sv = 2;'); });
t('script-destructure', () => $262.evalScript('const {da, db: [dc]} = {da: 1, db: [2]}; da + dc'));
Object.defineProperty(globalThis, 'lockedFn', { value: 1, writable: false, enumerable: false, configurable: false });
t('script-fn-locked', () => $262.evalScript('function lockedFn() {}'));
Object.defineProperty(globalThis, 'okFn', { value: 1, writable: true, enumerable: true, configurable: false });
t('script-fn-ok', () => $262.evalScript('function okFn() { return "ok"; } okFn()'));
t('script-fn-redefine', () => { $262.evalScript('function cfgFn() { return 1; }'); $262.evalScript('function cfgFn() { return 2; }'); return [cfgFn(), JSON.stringify(Object.getOwnPropertyDescriptor(globalThis, 'cfgFn').enumerable)].join(); });
t('script-var-prop', () => [$262.evalScript('var gvp = 5; this.gvp'), Object.getOwnPropertyDescriptor(globalThis, 'gvp').configurable].join());
t('script-completion', () => $262.evalScript('1; if (true) { 2; } else { 3; }'));
t('script-break', () => $262.evalScript('lbl: { 4; break lbl; }'));
t('script-syntax', () => $262.evalScript('var 1x'));
t('script-nonstring', () => $262.evalScript(42));
t('script-throw', () => $262.evalScript('throw new RangeError("from script")'));
Object.preventExtensions(globalThis);
t('script-var-nonext', () => $262.evalScript('var brandNew;'));
t('script-fn-nonext', () => $262.evalScript('function brandNewFn() {}'));
t('script-existing-var-nonext', () => $262.evalScript('var gvp; gvp'));
"""
    r = js(code, *tier)
    assert out(r) == golden("evalscript_global_declaration_instantiation")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_with_statement_scoping(js, golden, tier):
    """CATCHES: a with-statement implementation that ignores @@unscopables, does not re-check HasProperty for strict assignments, resolves names through a proxy without calling its has trap in spec order, or loses this-binding for calls fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var obj = { x: 1, y: 2, f: function () { return this === obj; } };
with (obj) {
  out.push('read ' + (x + y) + ' this-binding ' + f());
  x = 10;
  var hoisted = 5;
  [y] = [20];
  ({ x: x } = { x: 11 });
}
out.push('after: x=' + obj.x + ' y=' + obj.y + ' hoisted=' + hoisted + ' own=' + ('hoisted' in obj));
var uns = { a: 1, b: 2 };
uns[Symbol.unscopables] = { b: true };
var b = 'outer-b';
with (uns) { out.push('unscopables: a=' + a + ' b=' + b); b = 'set-outer'; }
out.push('outer b now ' + b + ', uns.b ' + uns.b);
var bad = { q: 1 };
Object.defineProperty(bad, Symbol.unscopables, { get: function () { throw new Error('unscopables getter boom'); } });
show('throwing unscopables', function () { with (bad) { return q; } });
function vanishing(name) {
  var o = {}; o[name] = 1;
  Object.defineProperty(o, Symbol.unscopables, { get: function () { delete o[name]; return undefined; } });
  return o;
}
var vanishV = vanishing('v'), vanishW = vanishing('w');
with (vanishV) { show('strict assign vanished', function () { 'use strict'; v = 2; return 'no error'; }); }
with (vanishW) { show('strict destructure vanished', function () { 'use strict'; [w] = [3]; return 'no error'; }); }
with (vanishing('s')) { show('sloppy assign vanished', function () { s = 4; return typeof globalThis.s; }); }
out.push('vanish now ' + JSON.stringify(vanishV) + JSON.stringify(vanishW));
show('strict destructure undeclared', function () { 'use strict'; [notDeclaredAnywhere] = [1]; return 'no error'; });
show('strict for-of undeclared', function () { 'use strict'; for (alsoUndeclared of [1]) {} return 'no error'; });
[sloppyCreated] = ['made']; out.push('sloppy destructure global: ' + globalThis.sloppyCreated);
var seen = [];
var px = new Proxy({ k: 7 }, { has: function (t, key) { seen.push(typeof key === 'symbol' ? key.toString() : key); return key in t; }, get: function (t, key) { if (key !== Symbol.unscopables) seen.push('get ' + String(key)); return t[key]; } });
with (px) { out.push('proxy with: ' + k + ' ' + typeof missing); }
out.push('proxy traps: ' + seen.join('|'));
with (new String('str')) { out.push('String wrapper with: ' + length + ' ' + charAt(1)); }
show('with null', function () { with (null) {} return 'no error'; });
var counter = { n: 0 };
with (counter) { for (var i = 0; i < 3; i++) n += i; }
out.push('loop in with: ' + counter.n + ' ' + i);
with (obj) { out.push('delete in with: ' + delete y + ' ' + ('y' in obj) + ' typeof ' + typeof y); }
function inner() { with ({ val: 'closure' }) { return function () { return val; }; } }
out.push('closure: ' + inner()());
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("with_statement_scoping")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_proxy_get_set_and_trap_invariants(js, golden, tier):
    """CATCHES: a Proxy implementation that skips the get/set invariants for non-configurable target properties, the has/deleteProperty/isExtensible/preventExtensions/setPrototypeOf checks, or the apply/construct trap contracts fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var target = {};
Object.defineProperty(target, 'frozen', { value: 1, writable: false, configurable: false });
Object.defineProperty(target, 'noGetter', { set: function (v) {}, configurable: false });
Object.defineProperty(target, 'noSetter', { get: function () { return 'g'; }, configurable: false });
Object.defineProperty(target, 'loose', { value: 1, writable: true, configurable: false });
var lying = new Proxy(target, {
  get: function (t, k) { return k === 'frozen' ? 2 : k === 'noGetter' ? 'invented' : k === 'loose' ? 'anything' : 'other'; },
  set: function () { return true; }
});
show('get frozen mismatch', function () { return lying.frozen; });
show('get frozen via Reflect', function () { return Reflect.get(lying, 'frozen'); });
show('get accessor without getter', function () { return lying.noGetter; });
show('get writable non-configurable', function () { return lying.loose; });
show('get unrelated', function () { return lying.whatever; });
show('set frozen different', function () { lying.frozen = 5; return 'no error'; });
show('set frozen same value', function () { lying.frozen = 1; return 'ok'; });
show('set accessor without setter', function () { lying.noSetter = 1; return 'no error'; });
show('Reflect.set accessor without setter', function () { return Reflect.set(lying, 'noSetter', 1); });
show('set writable ok', function () { lying.loose = 9; return 'ok'; });
var honest = new Proxy(target, { get: function (t, k, r) { return Reflect.get(t, k, r); } });
show('honest get', function () { return [honest.frozen, honest.noSetter, honest.noGetter].join(); });
var falsy = new Proxy({}, { set: function () { return false; }, deleteProperty: function () { return false; }, defineProperty: function () { return false; } });
show('sloppy set false', function () { falsy.a = 1; return 'silently ignored'; });
show('strict set false', function () { 'use strict'; falsy.a = 1; return 'no error'; });
show('strict delete false', function () { 'use strict'; delete falsy.a; return 'no error'; });
show('Reflect.deleteProperty', function () { return Reflect.deleteProperty(falsy, 'a'); });
var log = [];
var traced = new Proxy(function (a, b) { return a + b; }, {
  apply: function (t, thisArg, args) { log.push('apply:' + args.join(',')); return Reflect.apply(t, thisArg, args) * 10; },
  construct: function (t, args, nt) { log.push('construct:' + args.length + ':' + (nt === traced)); return { made: args[0] }; },
  has: function (t, k) { log.push('has:' + String(k)); return k in t; },
  deleteProperty: function (t, k) { log.push('delete:' + String(k)); return delete t[k]; }
});
show('apply trap', function () { return traced(1, 2); });
show('call via call()', function () { return traced.call(null, 3, 4); });
show('construct trap', function () { return JSON.stringify(new traced(7)); });
show('has trap', function () { return 'length' in traced; });
show('delete trap', function () { return delete traced.extra; });
out.push('log: ' + log.join(' '));
show('construct returns primitive', function () { return new (new Proxy(function () {}, { construct: function () { return 1; } }))(); });
show('apply not callable trap', function () { return new Proxy(function () {}, { apply: 5 })(); });
show('non-callable target apply', function () { return new Proxy({}, {})(); });
var nonExt = Object.preventExtensions({ p: 1 });
show('has hides non-extensible', function () { return 'p' in new Proxy(nonExt, { has: function () { return false; } }); });
show('has hides non-configurable', function () { return 'frozen' in new Proxy(target, { has: function () { return false; } }); });
show('deleteProperty non-configurable', function () { return delete new Proxy(target, { deleteProperty: function () { return true; } }).frozen; });
show('isExtensible mismatch', function () { return Object.isExtensible(new Proxy({}, { isExtensible: function () { return false; } })); });
show('preventExtensions lie', function () { return Object.preventExtensions(new Proxy({}, { preventExtensions: function () { return true; } })); });
show('setPrototypeOf non-extensible', function () { return Reflect.setPrototypeOf(new Proxy(Object.preventExtensions({}), { setPrototypeOf: function () { return true; } }), Array.prototype); });
var r = Proxy.revocable({}, {}); r.revoke();
show('revoked get', function () { return r.proxy.x; });
show('revoked typeof', function () { return typeof r.proxy; });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("proxy_get_set_and_trap_invariants")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_annex_b_block_function_hoisting(js, golden, tier):
    """CATCHES: an Annex B.3.3 implementation that promotes block functions despite a conflicting lexical binding (let, for-let, destructured catch param, parameter names) or promotes generators, async functions or strict-mode block functions fails this."""
    code = r"""var out = [];
function probe() {
  var r = [];
  r.push('before block: ' + typeof inBlock);
  { function inBlock() { return 'b'; } }
  r.push('after block: ' + typeof inBlock + ' ' + inBlock());
  r.push('if-decl before: ' + typeof ifFn);
  if (true) function ifFn() { return 'if'; }
  r.push('if-decl after: ' + ifFn());
  if (false) function neverFn() {}
  r.push('untaken if: ' + typeof neverFn);
  { let shadow = 1; { function shadow2() {} } }
  r.push('nested ok: ' + typeof shadow2);
  let lexical = 'lex';
  { function lexical() {} }
  r.push('blocked by let: ' + lexical);
  { function* genFn() {} async function asyncFn() {} }
  r.push('generator/async stay lexical: ' + typeof genFn + ' ' + typeof asyncFn);
  switch (1) { case 1: function inSwitch() { return 'sw'; } }
  r.push('switch: ' + inSwitch());
  try { function inTry() { return 't'; } } catch (e) { function inCatch() {} } finally { function inFinally() { return 'f'; } }
  r.push('try/catch/finally: ' + typeof inTry + ' ' + typeof inCatch + ' ' + inFinally());
  try { throw 1; } catch (caught) { { function caught() { return 'promoted'; } } }
  r.push('simple catch param exemption: ' + typeof caught);
  try { throw [1]; } catch ([dest]) { { function dest() {} } }
  r.push('destructured catch param blocks: ' + typeof dest);
  for (let loopVar = 0; loopVar < 1; loopVar++) { function loopVar() {} }
  r.push('for-let blocks: ' + typeof loopVar);
  for (var k in { a: 1 }) { function inForIn() { return k; } }
  r.push('for-in body: ' + inForIn());
  for (const v of [1]) { function v() {} }
  r.push('for-of const blocks: ' + typeof v);
  lbl: function labelled() { return 'lbl'; }
  r.push('labelled: ' + labelled());
  var i = 0; while (i++ < 1) { function inWhile() { return 'w'; } }
  do { function inDo() { return 'd'; } } while (false);
  r.push('loops: ' + inWhile() + inDo());
  { function twice() { return 1; } } { function twice() { return 2; } }
  r.push('last wins: ' + twice());
  with ({}) { function inWith() { return 'with'; } }
  r.push('with body: ' + inWith());
  { function inner() { return 'outer'; } { function inner() { return 'inner'; } } }
  r.push('nested same name: ' + inner());
  return r;
}
out = out.concat(probe());
function params(argFn) { { function argFn() { return 'block'; } } return typeof argFn; }
out.push('parameter blocks promotion: ' + params(5));
function strictProbe() { 'use strict'; { function strictFn() {} } return typeof strictFn; }
out.push('strict stays block-scoped: ' + strictProbe());
eval('{ function fromEval() { return "eval"; } }');
out.push('eval block function: ' + fromEval());
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("annex_b_block_function_hoisting")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_mapped_arguments_object(js, golden, tier):
    """CATCHES: an arguments object that does not alias parameters in sloppy simple-parameter functions, or keeps the alias after delete, writable:false or accessor redefinition, or maps strict/non-simple functions, fails this."""
    code = r"""var out = [];
function mapped(a, b, c) {
  var r = [];
  arguments[0] = 'A0';
  r.push('write-through: ' + a);
  b = 'B1';
  r.push('read-through: ' + arguments[1]);
  r.push('gOPD live: ' + JSON.stringify(Object.getOwnPropertyDescriptor(arguments, '1')));
  Object.defineProperty(arguments, '0', { value: 'defined' });
  r.push('define value syncs param: ' + a);
  Object.defineProperty(arguments, '0', { writable: false });
  a = 'after-freeze';
  r.push('writable:false severs: ' + arguments[0] + ' ' + a);
  delete arguments[1];
  b = 'B2';
  r.push('delete severs: ' + arguments[1] + ' ' + (1 in arguments));
  arguments[1] = 'new1';
  r.push('re-added is unmapped: ' + b + ' ' + arguments[1]);
  Object.defineProperty(arguments, '2', { get: function () { return 'getter'; }, configurable: true });
  c = 'C2';
  r.push('accessor severs: ' + arguments[2] + ' ' + c);
  r.push('Reflect.gOPD: ' + JSON.stringify(Reflect.getOwnPropertyDescriptor(arguments, '0')));
  r.push('length/callee: ' + arguments.length + ' ' + (arguments.callee === mapped));
  arguments[5] = 'beyond';
  r.push('beyond length: ' + arguments.length + ' ' + arguments[5]);
  return r;
}
out = out.concat(mapped(1, 2, 3));
function fewer(a, b) { arguments[1] = 'set'; return [b, arguments.length, arguments[1]].join(); }
out.push('unpassed param not mapped: ' + fewer(1));
function strict(a) { 'use strict'; arguments[0] = 'changed'; a = 'mine'; return [a, arguments[0]].join(); }
out.push('strict unmapped: ' + strict(1));
function defaults(a = 0) { arguments[0] = 'changed'; return a; }
out.push('non-simple params unmapped: ' + defaults(1));
function calleeStrict() { 'use strict'; try { return arguments.callee; } catch (e) { return e.name; } }
out.push('strict callee: ' + calleeStrict());
function iter() { return [...arguments].join('|') + ' ' + Object.prototype.toString.call(arguments); }
out.push('iterable: ' + iter('x', 'y'));
function keys(a, b) { return Object.keys(arguments).join() + ' ' + JSON.stringify(arguments); }
out.push('keys: ' + keys(1, 2));
function sliced() { return Array.prototype.slice.call(arguments, 1).join(); }
out.push('slice: ' + sliced(1, 2, 3));
function frozen(a) { Object.freeze(arguments); a = 'changed'; return arguments[0] + ' ' + Object.isFrozen(arguments); }
out.push('freeze: ' + frozen('orig'));
var arrow = function (a) { return (() => arguments[0])(); };
out.push('arrow inherits: ' + arrow('outer-arg'));
function shadow(a) { var arguments = 'shadowed'; return arguments; }
out.push('var arguments: ' + shadow(1));
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("mapped_arguments_object")
    assert (r.returncode, r.stderr) == (0, b"")

def test_interp_proper_tail_calls(js, golden):
    """CATCHES: a tree-walking interpreter that does not run strict-mode calls in tail position (conditional, logical, comma-free, method, call-expression callee, mutual recursion) in constant stack, or mis-handles direct eval and optional calls there, fails this."""
    code = r"""'use strict';
var out = [];
function run(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function selfRec(n) { if (n === 0) return 'self-done'; return selfRec(n - 1); }
function condRec(n) { return n === 0 ? 'cond-done' : condRec(n - 1); }
function orRec(n) { return n === 0 || orRec(n - 1); }
function andRec(n) { return n !== 0 && andRec(n - 1); }
function nullishRec(n) { return n === 0 ? 'nullish-done' : (null ?? nullishRec(n - 1)); }
function isEven(n) { return n === 0 ? true : isOdd(n - 1); }
function isOdd(n) { return n === 0 ? false : isEven(n - 1); }
var obj = { count(n) { return n === 0 ? 'method-done' : this.count(n - 1); } };
function getSelf() { return viaCallee; }
function viaCallee(n) { return n === 0 ? 'callee-expr-done' : getSelf()(n - 1); }
function acc(n, total) { if (n === 0) return total; return acc(n - 1, total + n); }
function withArgs() { return arguments.length === 0 ? 'args-done' : withArgs.apply(null, Array.prototype.slice.call(arguments, 1)); }
run('self', function () { return selfRec(100000); });
run('conditional', function () { return condRec(100000); });
run('logical or', function () { return orRec(100000); });
run('logical and', function () { return andRec(100000); });
run('nullish', function () { return nullishRec(100000); });
run('mutual', function () { return isEven(100001); });
run('method', function () { return obj.count(100000); });
run('call-expression callee', function () { return viaCallee(100000); });
run('accumulator', function () { return acc(100000, 0); });
run('apply chain', function () { return withArgs(1, 2, 3); });
var holder = { f: function () { return 'opt-called'; } };
function optTail() { return holder.f?.(); }
function optMissing() { return holder.g?.(); }
run('optional call tail', optTail);
run('optional missing', optMissing);
function nullBase() { var o; return o.method(); }
run('undefined base in tail', nullBase);
function evalTail(x) { return eval('x * 2'); }
run('direct eval in tail', function () { return evalTail(21); });
function notTail(n) { if (n === 0) return 0; return 1 + notTail(n - 1); }
run('non-tail shallow', function () { return notTail(100); });
function inTry(n) { try { return n === 0 ? 'try-done' : inTry(n - 1); } finally { } }
run('try-return shallow', function () { return inTry(100); });
function finRet(n) { try { return 'from-try'; } finally { if (n) return selfRec(1000); } }
run('finally override', function () { return finRet(1); });
console.log(out.join('\n'));
"""
    r = js(code, "--tier=interp")
    assert out(r) == golden("interp_proper_tail_calls")
    assert (r.returncode, r.stderr) == (0, b"")

def test_stack_overflow_is_catchable_range_error(js, golden):
    """CATCHES: an engine that crashes or aborts on runaway recursion instead of throwing a catchable RangeError, or that fails to reset its depth counter so later calls (and a second overflow) misbehave, fails this."""
    code = r"""var out = [];
var depth = 0;
function rec() { depth++; return rec() + 1; }
try { rec(); } catch (e) { out.push('caught: ' + e.name + ': ' + e.message + ' ' + (e instanceof RangeError) + ' unwound=' + (depth > 100)); }
function after() { return 'recovered, depth reset: ' + (function shallow(n) { return n === 0 ? 0 : 1 + shallow(n - 1); })(200); }
out.push(after());
try { rec(); } catch (e) { out.push('second overflow also catchable: ' + e.name); }
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("stack_overflow_is_catchable_range_error")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_direct_and_indirect_eval_and_function_constructor(js, golden, tier):
    """CATCHES: an eval that confuses direct and indirect eval scoping, leaks strict-mode or lexical declarations, returns wrong completion values, or a Function constructor that mis-parses parameter lists or bodies fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function hoistInto() { eval('var leaked = "from-eval"; function evalFn() { return "fn"; }'); return leaked + ' ' + evalFn(); }
show('sloppy eval var leaks', hoistInto);
function strictEval() { 'use strict'; eval('var contained = 1'); return typeof contained; }
show('strict eval own var env', strictEval);
function letStays() { eval('let blockScoped = 1; const c = 2;'); return typeof blockScoped + ' ' + typeof c; }
show('eval let/const stay inside', letStays);
show('completion values', function () { return [eval('1; 2;'), eval('if (true) { "then"; } else { "else"; }'), eval('for (var i = 0; i < 3; i++) i * 10;'), eval('try { "try"; } finally { "fin"; }'), eval('do { "do"; } while (false)'), String(eval('var z = 5;')), String(eval(''))].join('|'); });
show('eval non-string', function () { var o = {}; return eval(o) === o && eval(42) === 42; });
globalThis.g1 = 'global';
show('indirect eval global scope', function () { var g1 = 'local'; return (0, eval)('g1') + ' ' + eval('g1') + ' ' + globalThis.eval('typeof g1'); });
show('indirect eval var creates global', function () { (0, eval)('var madeByIndirect = 3'); return globalThis.madeByIndirect + ' ' + JSON.stringify(Object.getOwnPropertyDescriptor(globalThis, 'madeByIndirect')); });
show('eval sees arguments', function (a, b) { return eval('arguments.length + ":" + a'); }.bind(null, 'x', 'y'));
show('eval this in method', function () { var o = { m: function () { return eval('this') === o; } }; return o.m(); });
show('eval syntax error', function () { return eval('var 1a'); });
show('eval let redeclare', function () { let dup = 1; return eval('var dup = 2;'); });
show('eval new.target in function', function () { function F() { return eval('new.target') === F; } return new F() instanceof F; });
show('eval super outside method', function () { return eval('super.x'); });
show('Function params', function () { return [new Function('a, b', 'c', 'return a + b + c')(1, 2, 3), Function('a = 10', '...rest', 'return a + rest.length')(undefined, 1, 2), Function('{x, y}', 'return x * y')({ x: 3, y: 4 })].join(); });
show('Function length/name', function () { var f = new Function('a', 'b', ''); return f.length + ' ' + f.name + ' ' + (Object.getPrototypeOf(f) === Function.prototype); });
show('Function toString', function () { return Function('a', 'b', 'return a').toString().replace(/\n/g, '\\n'); });
show('Function global scope', function () { var hidden = 1; return Function('return typeof hidden')(); });
show('Function body syntax error', function () { return Function('return }'); });
show('Function param syntax error', function () { return Function('a b', 'return a'); });
show('Function sloppy this', function () { return Function('return this')() === globalThis; });
show('Function strict body', function () { return Function('"use strict"; return this')(); });
show('generator via constructor', function () { var GF = Object.getPrototypeOf(function* () {}).constructor; var g = new GF('a', 'yield a; yield a * 2'); return [...g(4)].join() + ' ' + GF.name; });
show('async fn constructor', function () { var AF = Object.getPrototypeOf(async function () {}).constructor; return AF.name + ' ' + typeof AF('return 1')().then; });
show('eval returns function decl', function () { return typeof eval('(function named() { return 1; })'); });
show('nested eval', function () { var depth = 'outer'; return eval('eval("depth + \'-nested\'")'); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("direct_and_indirect_eval_and_function_constructor")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_labelled_break_continue_and_iterator_close(js, golden, tier):
    """CATCHES: labelled break/continue handling that fails to close for-of iterators and generators, lets break/continue/return in finally resolve in the wrong order, or mis-targets stacked labels fails this."""
    code = r"""var out = [];
function iterable(tag, n) {
  return { [Symbol.iterator]: function () { var i = 0; return { next: function () { return { value: tag + i, done: i++ >= n }; }, return: function () { out.push('close ' + tag); return {}; } }; } };
}
var r = [];
outer: for (var a of iterable('A', 3)) {
  inner: for (var b of iterable('B', 3)) {
    if (b === 'B1') continue outer;
    if (a === 'A2') break outer;
    r.push(a + b);
  }
}
out.push('for-of labels: ' + r.join(','));
r = [];
var i = 0;
loop: do {
  i++;
  switch (i) {
    case 1: continue loop;
    case 2: r.push('two'); break;
    case 3: break loop;
  }
  r.push('after-switch ' + i);
} while (i < 10);
out.push('do/switch: ' + r.join(',') + ' i=' + i);
r = [];
block: {
  r.push('in block');
  if (r.length) break block;
  r.push('unreachable');
}
out.push('labelled block: ' + r.join(','));
function finallyOverride() {
  var log = [];
  outer: for (var k = 0; k < 3; k++) {
    try {
      if (k === 1) continue outer;
      log.push('try' + k);
    } finally {
      log.push('fin' + k);
      if (k === 2) break outer;
    }
  }
  return log.join(',');
}
out.push('finally+labels: ' + finallyOverride());
function returnInFinallyOverBreak() { lbl: try { break lbl; } finally { return 'finally-return'; } }
out.push('return beats break: ' + returnInFinallyOverBreak());
function breakOverReturn() { lbl: try { return 'try-return'; } finally { break lbl; } return 'after-label'; }
out.push('break beats return: ' + breakOverReturn());
r = [];
lab1: lab2: for (var x = 0; x < 3; x++) { if (x === 1) continue lab1; if (x === 2) break lab2; r.push(x); }
out.push('stacked labels: ' + r.join(','));
r = [];
forin: for (var key in { p: 1, q: 2, s: 3 }) { for (var j = 0; j < 2; j++) { if (key === 'q') continue forin; if (j === 1) continue; r.push(key + j); } }
out.push('for-in labels: ' + r.join(','));
r = [];
w: while (true) { for (const v of iterable('C', 5)) { if (v === 'C2') break w; r.push(v); } }
out.push('while/for-of break: ' + r.join(','));
function* gen() { try { yield 1; yield 2; } finally { out.push('gen finally'); } }
g: for (var gv of gen()) { for (;;) { break g; } }
out.push('generator closed via label: ' + gv);
var completion = eval('L: for (var e = 0; e < 3; e++) { if (e === 1) { "kept"; continue L; } "body" + e; }');
out.push('completion value: ' + completion);
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("labelled_break_continue_and_iterator_close")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_tagged_templates(js, golden, tier):
    """CATCHES: a tagged-template implementation that does not cache frozen template objects per site, cooks invalid escapes instead of yielding undefined, loses the member-call this value, or evaluates substitutions after the tag fails this."""
    code = r"""var out = [];
function tag(strings) { var subs = Array.prototype.slice.call(arguments, 1); return JSON.stringify({ cooked: strings, raw: strings.raw, subs: subs }); }
out.push('basic: ' + tag`a${1}b${'two'}c`);
out.push('escapes: ' + tag`\n\t\u0041\x42`);
out.push('invalid escapes cooked undefined: ' + tag`\unicode and \xZZ and \01`);
out.push('String.raw: ' + String.raw`C:\new\table${1 + 1}\x`);
out.push('String.raw object: ' + String.raw({ raw: ['x', 'y', 'z'] }, 1, 2, 3, 4));
var sites = [];
function capture(s) { sites.push(s); return s; }
for (var i = 0; i < 2; i++) capture`same site`;
capture`same site`;
out.push('site caching: ' + (sites[0] === sites[1]) + ' ' + (sites[1] === sites[2]));
out.push('frozen: ' + Object.isFrozen(sites[0]) + ' ' + Object.isFrozen(sites[0].raw) + ' ' + Array.isArray(sites[0]));
out.push('raw descriptor: ' + JSON.stringify(Object.getOwnPropertyDescriptor(sites[0], 'raw')));
var obj = { prefix: '>', tagm: function (s, v) { return this.prefix + s[0] + v; } };
out.push('member tag this: ' + obj.tagm`val=${7}` + ' ' + obj['tagm']`idx=${8}`);
function chain(s) { return function (s2) { return s[0] + '+' + s2[0]; }; }
out.push('chained: ' + chain`first``second`);
function Factory(s) { return function () { this.text = s[0]; }; }
out.push('new binds to tagged result: ' + (new Factory`made`).text);
var order = [];
function sub(n) { order.push(n); return n; }
function t2(s) { order.push('tag'); return arguments.length; }
out.push('evaluation order: ' + t2`${sub(1)}${sub(2)}` + ' ' + order.join(','));
out.push('empty: ' + tag`` + ' ' + tag`${0}`);
out.push('line continuation: ' + tag`a\
b`);
out.push('untagged: ' + `x${1}y${[1, 2]}z${{ toString: function () { return 'obj'; } }}`);
try { `${Symbol('s')}`; } catch (e) { out.push('symbol in template: ' + e.name + ': ' + e.message); }
function strictTag() { 'use strict'; return (function (s) { return this; })`x`; }
out.push('strict tag this: ' + strictTag());
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("tagged_templates")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_class_private_static_and_derived_semantics(js, golden, tier):
    """CATCHES: a class implementation with wrong private-name brand checks, static block ordering, private accessor/method writes, derived-constructor this/super rules, or heritage validation errors fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var order = [];
function key(k) { order.push('key:' + k); return k; }
class Counter {
  static #instances = 0;
  static log = [];
  #count = Counter.#bump();
  [key('computed')] = 'c';
  #secret = 's';
  static #bump() { return ++Counter.#instances; }
  static { this.log.push('static block 1, instances=' + Counter.#instances); }
  get #hidden() { return 'hidden:' + this.#secret; }
  set #hidden(v) { this.#secret = v; }
  static { this.log.push('static block 2 this===Counter ' + (this === Counter)); }
  reveal() { return this.#hidden; }
  update(v) { this.#hidden = v; return this.#secret; }
  get count() { return this.#count; }
  static isCounter(o) { return #count in o; }
  static total() { return Counter.#instances; }
  readPrivate(o) { return o.#secret; }
  callStaticOn(o) { return o.#bumpless(); }
  #bumpless() { return 'instance method'; }
  writeMethod() { this.#bumpless = 1; }
  static readStaticOn(o) { return o.#instances; }
}
out.push('static blocks: ' + Counter.log.join(' | '));
var c1 = new Counter(), c2 = new Counter();
out.push('private fields: ' + c1.count + ' ' + c2.count + ' total=' + Counter.total() + ' computed=' + c1.computed + ' order=' + order.join(','));
out.push('private accessors: ' + c1.reveal() + ' ' + c1.update('new') + ' ' + c1.reveal());
out.push('brand check: ' + Counter.isCounter(c1) + ' ' + Counter.isCounter({}) + ' ' + Counter.isCounter(Object.create(c1)));
show('read foreign', function () { return c1.readPrivate({}); });
show('call method foreign', function () { return c1.callStaticOn({}); });
show('write method', function () { c1.writeMethod(); });
show('static private on subclass', function () { class Sub extends Counter {} return Counter.readStaticOn(Sub); });
show('in on primitive', function () { return Counter.isCounter(1); });
class Base { constructor() { this.fromBase = new.target.name; } static who() { return 'Base.' + this.name; } greet() { return 'base-greet'; } }
class Derived extends Base {
  field = this.fromBase + '-field';
  constructor() { super(); this.after = 'ok'; }
  greet() { return super.greet() + '+derived'; }
  static who() { return super.who() + '!'; }
  setViaSuper() { super.prop = 'assigned'; return Object.prototype.hasOwnProperty.call(this, 'prop'); }
}
var d = new Derived();
out.push('derived: ' + d.fromBase + ' ' + d.field + ' ' + d.greet() + ' ' + Derived.who() + ' ' + d.setViaSuper());
show('this before super', function () { class X extends Base { constructor() { this.x = 1; super(); } } return new X(); });
show('super twice', function () { class Y extends Base { constructor() { super(); super(); } } return new Y(); });
show('derived returns primitive', function () { class Z extends Base { constructor() { super(); return 1; } } return new Z(); });
show('derived no super', function () { class W extends Base { constructor() { } } return new W(); });
show('derived returns object', function () { class V extends Base { constructor() { return { custom: true }; } } return JSON.stringify(new V()); });
show('extends null', function () { class N extends null { constructor() { return Object.create(N.prototype); } } return Object.getPrototypeOf(N.prototype) === null && new N() instanceof N; });
show('extends non-constructor', function () { var notCtor = function () {}.bind(); notCtor.prototype = 3; class Q extends notCtor {} return 'created'; });
show('extends arrow', function () { class R extends (() => {}) {} return 'created'; });
show('call class', function () { return Base(); });
show('class name binding immutable', function () { class Imm { static rename() { Imm = 1; } } Imm.rename(); });
show('accessor pairs', function () { class P { static get s() { return 'sget'; } static set s(v) { P._s = v; } } P.s = 5; return P.s + ' ' + P._s; });
show('field arrow this', function () { class F { name = 'inst'; getName = () => this.name; } var g = new F().getName; return g(); });
show('new.target in field', function () { class T { nt = new.target; } return String(new T().nt); });
show('anonymous class name', function () { var anon = class {}; var named = class Inner {}; return anon.name + ' ' + named.name + ' ' + typeof Inner; });
show('symbol method name', function () { var s = Symbol('desc'); var o = class { [s]() {} static [Symbol()]() {} }; return o.prototype[s].name + '|' + Object.getOwnPropertySymbols(o).map(function (k) { return o[k].name; }).join(); });
show('getter/setter names', function () { class A { get g() { return 1; } set g(v) {} } var dsc = Object.getOwnPropertyDescriptor(A.prototype, 'g'); return dsc.get.name + ' ' + dsc.set.name; });
show('instance private on proxy', function () { return Counter.isCounter(new Proxy(c1, {})); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("class_private_static_and_derived_semantics")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_using_declarations_and_disposable_stacks(js, golden, tier):
    """CATCHES: explicit resource management that disposes in the wrong order, drops SuppressedError chaining, accepts non-disposable values, or mishandles await using fallbacks and DisposableStack/AsyncDisposableStack fails this."""
    code = r"""var out = [];
function res(name, opts) {
  opts = opts || {};
  var r = { name: name };
  r[Symbol.dispose] = function () { out.push('dispose ' + name); if (opts.throwOnDispose) throw new Error('dispose failed: ' + name); };
  return r;
}
function basic() {
  using a = res('a'), b = res('b');
  { using inner = res('inner'); out.push('in block'); }
  using nothing = null, alsoNothing = undefined;
  out.push('body end');
  return 'returned';
}
out.push('basic: ' + basic());
function throwing() {
  using x = res('x', { throwOnDispose: true });
  using y = res('y', { throwOnDispose: true });
  throw new Error('body error');
}
try { throwing(); } catch (e) {
  out.push('suppressed chain: ' + e.name + ' | ' + e.message + ' | ' + e.error.message + ' | ' + e.suppressed.name + ' | ' + e.suppressed.error.message + ' | ' + e.suppressed.suppressed.message);
}
function disposeOnly() { using z = res('z', { throwOnDispose: true }); return 'never seen'; }
try { disposeOnly(); } catch (e) { out.push('dispose over return: ' + e.message); }
try { (function () { using bad = { [Symbol.dispose]: 42 }; })(); } catch (e) { out.push('non-callable dispose: ' + e.name + ': ' + e.message); }
try { (function () { using bad = {}; })(); } catch (e) { out.push('missing dispose: ' + e.name + ': ' + e.message); }
try { (function () { using bad = 5; })(); } catch (e) { out.push('primitive resource: ' + e.name + ': ' + e.message); }
for (using it of [res('loop1'), res('loop2')]) { out.push('loop body ' + it.name); }
function breakOut() { for (var i = 0; i < 3; i++) { using r = res('iter' + i); if (i === 1) break; } return 'after loop'; }
out.push(breakOut());
var stack = new DisposableStack();
stack.use(res('stack-use'));
stack.defer(function () { out.push('deferred'); });
var adopted = stack.adopt('val', function (v) { out.push('adopt release ' + v); });
out.push('adopted returns ' + adopted + ', disposed=' + stack.disposed);
stack.dispose();
out.push('stack disposed=' + stack.disposed);
try { stack.use(res('late')); } catch (e) { out.push('use after dispose: ' + e.name + ': ' + e.message); }
var se = new SuppressedError(new Error('e1'), new Error('e2'), 'msg');
out.push('SuppressedError: ' + se.name + ' ' + se.message + ' ' + se.error.message + ' ' + se.suppressed.message + ' ' + (se instanceof Error));
async function asyncUsing() {
  var log = [];
  {
    await using a = { [Symbol.asyncDispose]: async function () { log.push('async dispose a'); } };
    await using b = { [Symbol.dispose]: function () { log.push('sync fallback b'); } };
    await using c = null;
    log.push('async body');
  }
  try {
    await using t = { [Symbol.asyncDispose]: function () { return Promise.reject(new Error('async reject')); } };
  } catch (e) { log.push('caught ' + e.message); }
  var ads = new AsyncDisposableStack();
  ads.defer(async function () { log.push('async deferred'); });
  await ads.disposeAsync();
  return log.join(', ');
}
asyncUsing().then(function (v) { out.push('async: ' + v); console.log(out.join('\n')); }, function (e) { console.log('FAIL ' + e); });
"""
    r = js(code, *tier)
    assert out(r) == golden("using_declarations_and_disposable_stacks")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_array_exotic_set_and_length(js, golden, tier):
    """CATCHES: an Array [[Set]]/ArraySetLength that accepts invalid lengths, coerces length once, ignores non-writable length, sealed/frozen arrays or non-configurable elements blocking truncation fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('negative length', function () { var a = [1]; a.length = -1; return a.length; });
show('fractional length', function () { var a = [1]; a.length = 1.5; return a.length; });
show('huge length', function () { var a = []; a.length = 4294967296; return a.length; });
show('length coercion twice', function () { var calls = 0; var a = [1, 2, 3]; a.length = { valueOf: function () { calls++; return 1; } }; return a.length + ' calls=' + calls; });
show('length string', function () { var a = [1, 2, 3]; a.length = '2'; return JSON.stringify(a); });
show('frozen length sloppy', function () { var a = Object.freeze([1, 2]); a.length = 0; return a.length; });
show('frozen length strict', function () { 'use strict'; var a = Object.freeze([1, 2]); a.length = 0; return a.length; });
show('non-configurable blocker sloppy', function () { var a = [0, 1, 2, 3, 4]; Object.defineProperty(a, '2', { value: 'pinned', configurable: false }); a.length = 1; return a.length + ' ' + JSON.stringify(a); });
show('non-configurable blocker strict', function () { 'use strict'; var a = [0, 1, 2, 3]; Object.defineProperty(a, '1', { value: 'pinned', configurable: false }); try { a.length = 0; } catch (e) { return e.name + ': ' + e.message + ' -> length ' + a.length; } });
show('sealed append sloppy', function () { var a = Object.seal([1]); a[1] = 2; a[0] = 'changed'; return JSON.stringify(a) + ' ' + a.length; });
show('sealed append strict', function () { 'use strict'; var a = Object.seal([1]); a[5] = 2; });
show('read-only length append sloppy', function () { var a = [1, 2]; Object.defineProperty(a, 'length', { writable: false }); a[2] = 3; a[0] = 'ok'; return JSON.stringify(a) + ' ' + a.length; });
show('read-only length append strict', function () { 'use strict'; var a = [1, 2]; Object.defineProperty(a, 'length', { writable: false }); a[2] = 3; });
show('read-only length push', function () { var a = [1]; Object.defineProperty(a, 'length', { writable: false }); a.push(2); });
show('existing element attributes kept', function () { var a = [1, 2]; Object.defineProperty(a, '0', { enumerable: false }); a[0] = 'new'; return JSON.stringify(Object.getOwnPropertyDescriptor(a, '0')) + ' keys=' + Object.keys(a); });
show('read-only element sloppy', function () { var a = [1, 2]; Object.defineProperty(a, '1', { writable: false }); a[1] = 'x'; return a[1]; });
show('read-only element strict', function () { 'use strict'; var a = [1, 2]; Object.defineProperty(a, '1', { writable: false }); a[1] = 'x'; });
show('index 2^32-1 is not an index', function () { var a = []; a[4294967295] = 'big'; a[4294967294] = 'last'; return a.length + ' ' + Object.keys(a).join(); });
show('setter on element', function () { var log = []; var a = [1]; Object.defineProperty(a, '3', { set: function (v) { log.push(v); }, configurable: true }); a[3] = 'via-setter'; return a.length + ' ' + log.join(); });
show('getter-only element strict', function () { 'use strict'; var a = []; Object.defineProperty(a, '0', { get: function () { return 1; } }); a[0] = 2; });
show('inherited setter', function () { var log = []; var proto = []; Object.defineProperty(proto, '0', { set: function (v) { log.push('proto-set ' + v); } }); var a = []; Object.setPrototypeOf(a, proto); a[0] = 'x'; return log.join() + ' own=' + a.hasOwnProperty('0') + ' len=' + a.length; });
show('inherited read-only', function () { 'use strict'; var proto = Object.freeze(['locked']); var a = []; Object.setPrototypeOf(a, proto); a[0] = 'x'; });
show('defineProperty length shrink', function () { var a = [1, 2, 3, 4]; Object.defineProperty(a, 'length', { value: 2 }); return JSON.stringify(a); });
show('defineProperty length invalid', function () { return Object.defineProperty([], 'length', { value: -5 }); });
show('length grows holes', function () { var a = [1]; a.length = 3; return JSON.stringify(a) + ' ' + (1 in a); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("array_exotic_set_and_length")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_set_and_get_with_exotic_receivers(js, golden, tier):
    """CATCHES: property [[Set]]/[[Get]] that ignores primitive receivers, proxies or typed arrays on the prototype chain, revoked proxies, or Reflect.set receivers whose defineProperty trap or attributes must be consulted fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
// primitive bases
show('sloppy primitive set ignored', function () { var s = 'abc'; s.extra = 1; return typeof s.extra; });
show('strict primitive set', function () { 'use strict'; var s = 'abc'; s.extra = 1; });
show('strict number set', function () { 'use strict'; (5).x = 1; });
show('strict boolean set', function () { 'use strict'; true.x = 1; });
show('strict symbol set', function () { 'use strict'; Symbol('q').x = 1; });
show('strict bigint set', function () { 'use strict'; (10n).x = 1; });
show('undefined base set', function () { var u; u.x = 1; });
show('null base set', function () { var n = null; n.x = 1; });
Object.defineProperty(String.prototype, 'primSetter', { set: function (v) { out.push('  setter this type=' + typeof this + ' value=' + v); }, configurable: true });
Object.defineProperty(Number.prototype, 'primGetterOnly', { get: function () { return 'g'; }, configurable: true });
show('setter on String.prototype strict', function () { 'use strict'; 'abc'.primSetter = 'v1'; return 'done'; });
show('setter on String.prototype sloppy', function () { 'abc'.primSetter = 'v2'; return 'done'; });
show('getter-only on Number.prototype strict', function () { 'use strict'; (1).primGetterOnly = 2; });
show('getter-only on Number.prototype sloppy', function () { (1).primGetterOnly = 2; return (1).primGetterOnly; });
show('Reflect.set primitive receiver', function () { return Reflect.set(String.prototype, 'primSetter', 'v3', 'xyz'); });
show('Reflect.set data on primitive receiver', function () { return Reflect.set({ a: 1 }, 'a', 2, 'str'); });
delete String.prototype.primSetter; delete Number.prototype.primGetterOnly;
// proxies on the prototype chain
var log = [];
var protoProxy = new Proxy({}, {
  get: function (t, k, r) { log.push('get ' + String(k) + ' recv=' + (r === child)); return 'trapped-' + String(k); },
  set: function (t, k, v, r) { log.push('set ' + String(k) + '=' + v + ' recv=' + (r === child)); return true; }
});
var child = Object.create(protoProxy);
child.own = 'mine';
show('inherited proxy get', function () { return child.missing + ' ' + child.own; });
show('inherited proxy set', function () { child.fresh = 1; return Object.prototype.hasOwnProperty.call(child, 'fresh'); });
out.push('  log: ' + log.join(' | '));
var rev = Proxy.revocable({}, {});
var orphan = Object.create(rev.proxy);
rev.revoke();
show('revoked proxy on chain get', function () { return orphan.anything; });
show('revoked proxy on chain set', function () { orphan.anything = 1; });
var passthrough = Object.create(new Proxy({ inherited: 'from-target' }, {}));
show('trapless proxy on chain', function () { passthrough.newProp = 'set'; return passthrough.inherited + ' ' + passthrough.newProp + ' ' + Object.keys(passthrough); });
// proxy as receiver
var defineLog = [];
var recvProxy = new Proxy({}, { defineProperty: function (t, k, d) { defineLog.push(k + ':' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); }, getOwnPropertyDescriptor: function (t, k) { defineLog.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); } });
show('Reflect.set proxy receiver', function () { return Reflect.set({}, 'k', 1, recvProxy) + ' ' + Reflect.set({}, 'k', 2, recvProxy) + ' ' + defineLog.join(' ; '); });
var refusing = new Proxy({}, { defineProperty: function () { return false; } });
show('Reflect.set refusing receiver', function () { return Reflect.set({}, 'k', 1, refusing); });
// typed arrays on the prototype chain
var ta = new Uint8Array(4);
var taChild = Object.create(ta);
show('TA proto valid index creates own', function () { taChild[1] = 7; return Object.prototype.hasOwnProperty.call(taChild, '1') + ' ta[1]=' + ta[1] + ' child[1]=' + taChild[1]; });
show('TA proto invalid index ignored', function () { taChild[10] = 7; taChild['-0'] = 1; return Object.prototype.hasOwnProperty.call(taChild, '10') + ' ' + Object.prototype.hasOwnProperty.call(taChild, '-0'); });
show('Reflect.set TA receiver itself', function () { return Reflect.set(taChild, '2', 9, ta) + ' ta[2]=' + ta[2]; });
show('TA own numeric non-index', function () { ta['1.5'] = 3; ta[-1] = 3; return String(ta['1.5']) + ' ' + Object.keys(ta).join(); });
show('TA coerces even out of range', function () { var called = 0; ta[100] = { valueOf: function () { called++; return 1; } }; return 'valueOf calls=' + called; });
var big = new BigInt64Array(2);
show('BigInt TA set number', function () { big[0] = 1; });
show('BigInt TA set bigint', function () { big[1] = 5n; return big[1]; });
// receiver differs from target for ordinary objects
show('Reflect.set getter-only inherited', function () { var p = { get g() { return 1; } }; return Reflect.set(p, 'g', 2, {}); });
show('Reflect.set non-writable receiver prop', function () { var r = {}; Object.defineProperty(r, 'k', { value: 1, writable: false, configurable: true }); return Reflect.set({}, 'k', 2, r) + ' ' + r.k; });
show('Reflect.set accessor on receiver', function () { var r = { set k(v) {} }; return Reflect.set({}, 'k', 2, r); });
show('Reflect.set non-object receiver', function () { return Reflect.set({}, 'k', 2, 1); });
show('Reflect.get receiver', function () { var src = { get who() { return this.name; } }; return Reflect.get(src, 'who', { name: 'receiver' }); });
show('Reflect.get primitive receiver', function () { var src = { get who() { return typeof this; } }; return Reflect.get(src, 'who', 42); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("set_and_get_with_exotic_receivers")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_legacy_function_caller_and_arguments(js, golden, tier):
    """CATCHES: legacy fn.caller/fn.arguments reflection that does not return the live activation (or null when inactive / for strict callers), or exposes them on strict, arrow, method, generator or class functions, fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function callee() { return callee.caller; }
function outerCaller() { return callee(); }
show('caller is calling function', function () { return outerCaller() === outerCaller; });
show('caller when inactive', function () { return callee.caller; });
function readArgs() { return readArgs.arguments; }
show('fn.arguments while active', function () { var a = readArgs(1, 'two'); return Object.prototype.toString.call(a) + ' ' + a.length + ' ' + a[1]; });
show('fn.arguments inactive', function () { return readArgs.arguments; });
function notNaming(x) { return inspector(); }
function inspector() { var a = notNaming.arguments; return a === null ? 'null' : a.length + ':' + a[0]; }
show('arguments conjured lazily', function () { return notNaming('lazy'); });
function strictCaller() { 'use strict'; var r = callee(); return r; }
show('strict caller censored', function () { return strictCaller(); });
show('strict function caller access', function () { 'use strict'; function s() {} return s.caller; });
show('strict function arguments access', function () { 'use strict'; function s() {} return s.arguments; });
show('arrow caller access', function () { var arrow = () => 1; return arrow.caller; });
show('method caller access', function () { var o = { m() {} }; return o.m.caller; });
show('generator arguments access', function () { function* g() {} return g.arguments; });
show('class caller access', function () { class C {} return C.caller; });
show('own properties', function () { function plain() {} return [Object.prototype.hasOwnProperty.call(plain, 'caller'), Object.prototype.hasOwnProperty.call(plain, 'arguments'), Object.prototype.hasOwnProperty.call(Function.prototype, 'caller')].join(); });
show('poison accessor identity', function () { var d1 = Object.getOwnPropertyDescriptor(Function.prototype, 'caller'); var d2 = Object.getOwnPropertyDescriptor(Function.prototype, 'arguments'); return (d1.get === d1.set) + ' ' + (d1.get === d2.get) + ' ' + d1.get.name.length + ' ' + Object.isFrozen(d1.get); });
show('recursive arguments youngest', function () { function rec(n) { if (n > 0) return rec(n - 1); return rec.arguments[0]; } return rec(3); });
show('strict arguments.callee', function () { 'use strict'; return arguments.callee; });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("legacy_function_caller_and_arguments")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_shadowrealm_boundary(js, golden, tier):
    """CATCHES: a ShadowRealm that lets objects cross its boundary, does not wrap callables in both directions with CopyNameAndLength, or reports inner errors as anything but TypeError fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var sr = new ShadowRealm();
show('primitives cross', function () { return [sr.evaluate('1 + 1'), sr.evaluate('"s" + "t"'), sr.evaluate('null'), typeof sr.evaluate('undefined'), typeof sr.evaluate('Symbol("x")'), typeof sr.evaluate('10n')].join(); });
show('isolated globals', function () { sr.evaluate('globalThis.shared = 1; var realmVar = 2;'); return typeof globalThis.shared + ' ' + sr.evaluate('shared + realmVar') + ' ' + sr.evaluate('typeof console'); });
show('object result rejected', function () { return sr.evaluate('({})'); });
show('array result rejected', function () { return sr.evaluate('[1, 2]'); });
var fn = sr.evaluate('(function namedInside(a, b, c) { return a * b; })');
show('wrapped function', function () { return typeof fn + ' name=' + fn.name + ' length=' + fn.length + ' result=' + fn(6, 7) + ' proto=' + (Object.getPrototypeOf(fn) === Function.prototype); });
show('wrapped is not constructor', function () { return new fn(1, 2); });
show('wrapped arg object rejected', function () { return fn({}, 1); });
show('wrapped returns object', function () { return sr.evaluate('() => ({ leaked: true })')(); });
show('wrapped throws', function () { return sr.evaluate('() => { throw new RangeError("inner boom"); }')(); });
show('evaluate throws', function () { return sr.evaluate('throw new Error("eval boom")'); });
show('evaluate syntax error', function () { return sr.evaluate('let let = 1'); });
show('evaluate non-string', function () { return sr.evaluate(42); });
show('callback crosses', function () { var apply = sr.evaluate('(cb, x) => cb(x) + "|" + typeof cb + "|" + cb.length'); return apply(function (v) { return 'host saw ' + v; }, 'arg'); });
show('callback throws in host', function () { var apply = sr.evaluate('(cb) => { try { cb(); return "no"; } catch (e) { return e.constructor === TypeError ? "TypeError in realm" : "other"; } }'); return apply(function () { throw new Error('host error'); }); });
show('returned function wraps again', function () { var mk = sr.evaluate('(n) => (m) => n + m'); return mk(10)(5); });
show('length edge cases', function () { var f2 = sr.evaluate('var g = function () {}; Object.defineProperty(g, "length", { value: Infinity }); g'); var f3 = sr.evaluate('var h = function () {}; Object.defineProperty(h, "length", { value: -3.5 }); Object.defineProperty(h, "name", { value: 7 }); h'); return f2.length + ' ' + f3.length + ' [' + f3.name + ']'; });
show('name getter throws', function () { return sr.evaluate('var k = function () {}; Object.defineProperty(k, "name", { get() { throw new Error("no"); } }); k'); });
show('requires new', function () { return ShadowRealm(); });
show('evaluate wrong receiver', function () { return ShadowRealm.prototype.evaluate.call({}, '1'); });
show('two realms independent', function () { var a = new ShadowRealm(), b = new ShadowRealm(); a.evaluate('globalThis.v = "A"'); b.evaluate('globalThis.v = "B"'); return a.evaluate('v') + b.evaluate('v'); });
show('toStringTag', function () { return Object.prototype.toString.call(sr); });
show('microtasks inside realm', function () { return sr.evaluate('var log = []; Promise.resolve().then(() => log.push("job")); "sync"') + ' then ' + sr.evaluate('log.join()'); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("shadowrealm_boundary")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_generator_and_async_delegation(js, golden, tier):
    """CATCHES: generator and async-generator delegation that does not forward next/throw/return to the inner iterator, close iterators lacking throw, or await yielded promises in async generators fails this."""
    code = r"""var out = [];
function* g1() { var x = yield 1; out.push('got ' + x); try { yield 2; } finally { out.push('fin'); } }
var it = g1(); out.push(JSON.stringify(it.next()), JSON.stringify(it.next('a')), JSON.stringify(it.return(9)));
function* inner() { yield 'i1'; return 'iret'; }
function* outer() { var r = yield* inner(); out.push('r=' + r); yield* [10, 20]; yield* 'ab'; }
out.push([...outer()].join());
// yield* throw/return forwarding
var log2 = [];
var iterable = { [Symbol.iterator]() { return { next(v) { log2.push('next:' + v); return { value: 'n', done: false }; }, throw(e) { log2.push('throw:' + e); return { value: 't', done: true }; }, return(v) { log2.push('ret:' + v); return { value: 'rr', done: true }; } }; } };
function* deleg() { var r = yield* iterable; log2.push('res:' + r); }
var d = deleg(); d.next('x'); d.next('y'); out.push(JSON.stringify(d.throw('E'))); out.push(log2.join(';'));
var d2 = deleg(); d2.next(); out.push(JSON.stringify(d2.return('Q'))); out.push(log2.join(';'));
// yield* to iterator without throw method
var noThrow = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { out.push('closed'); return {}; } }; } };
function* deleg2() { yield* noThrow; }
var d3 = deleg2(); d3.next();
try { d3.throw(new Error('x')); } catch (e) { out.push(e.name + ': ' + e.message); }
console.log(out.join('\n'));
// async
async function af(x) { var a = await x; var b = await Promise.resolve(a + 1); return b * 2; }
async function* ag() { yield 1; yield await Promise.resolve(2); var x = yield Promise.resolve(3); yield* [4, 5]; }
(async () => {
  console.log(await af(1));
  var vals = []; for await (var v of ag()) vals.push(v); console.log(vals.join());
  var vals2 = []; for await (var v2 of [Promise.resolve('p'), 'q']) vals2.push(v2); console.log(vals2.join());
  async function* inner2() { yield 'a'; yield 'b'; return 'done'; }
  async function* outer2() { var r = yield* inner2(); yield r; yield* ['s1', 's2']; }
  var v3 = []; for await (var w of outer2()) v3.push(w); console.log(v3.join());
  try { await (async () => { throw new RangeError('rej'); })(); } catch (e) { console.log(e.name + ': ' + e.message); }
  var agi = ag(); console.log(JSON.stringify(await agi.next()), JSON.stringify(await agi.return(7)), JSON.stringify(await agi.next()));
  try { for await (var bad of { [Symbol.asyncIterator]: 5 }) {} } catch (e) { console.log(e.name + ': ' + e.message); }
  async function* thrower() { try { yield 1; } catch (e) { yield 'caught ' + e; } }
  var th = thrower(); await th.next(); console.log(JSON.stringify(await th.throw('T')));
  async function* yr() { yield Promise.reject(new Error('yield-rej')); }
  try { await yr().next(); } catch (e) { console.log(e.message); }
  async function* adeleg() { yield* { [Symbol.asyncIterator]: 3 }; }
  try { await adeleg().next(); } catch (e) { console.log(e.name + ': ' + e.message); }
})();
"""
    r = js(code, *tier)
    assert out(r) == golden("generator_and_async_delegation")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_global_object_bindings_in_scripts(run, golden, tier):
    """CATCHES: a script-level global environment where var/function declarations do not become non-configurable global properties, let leaks onto globalThis, global accessors are not invoked on identifier reads/writes, or strict writes to read-only globals pass silently fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var declared = 1;
function declaredFn() { return 'fn'; }
let lexical = 'lex';
show('var/function become global properties', function () { return [JSON.stringify(Object.getOwnPropertyDescriptor(globalThis, 'declared')), typeof globalThis.declaredFn, Object.getOwnPropertyDescriptor(globalThis, 'declaredFn').enumerable].join(' '); });
show('let is not a global property', function () { return typeof globalThis.lexical + ' ' + lexical; });
show('delete declared var', function () { return delete globalThis.declared; });
implicitGlobal = 'implicit';
show('implicit global configurable', function () { var d = Object.getOwnPropertyDescriptor(globalThis, 'implicitGlobal'); return d.configurable + ' ' + delete globalThis.implicitGlobal + ' ' + typeof implicitGlobal; });
var hits = 0;
Object.defineProperty(globalThis, 'counter', { get: function () { return ++hits; }, set: function (v) { hits = v * 100; }, configurable: true });
show('global accessor via identifier', function () { var a = counter, b = counter; counter = 2; return a + ',' + b + ',' + counter + ',' + typeof counter; });
show('global accessor in nested function', function () { return (function () { return (function () { return counter; })(); })(); });
Object.defineProperty(globalThis, 'readOnlyGlobal', { value: 'ro', writable: false, configurable: true });
show('sloppy write to read-only global', function () { readOnlyGlobal = 'changed'; return readOnlyGlobal; });
show('strict write to read-only global', function () { 'use strict'; readOnlyGlobal = 'changed'; });
Object.defineProperty(globalThis, 'getterOnlyGlobal', { get: function () { return 'g'; }, configurable: true });
show('strict write to getter-only global', function () { 'use strict'; getterOnlyGlobal = 1; });
show('typeof undeclared', function () { return typeof neverDeclaredAnywhere + ' ' + typeof globalThis.neverDeclaredAnywhere; });
show('read undeclared', function () { return neverDeclaredAnywhere; });
show('global this in sloppy function', function () { return (function () { return this === globalThis; })() + ' ' + (function () { 'use strict'; return this; })(); });
show('builtin attributes', function () { var d = Object.getOwnPropertyDescriptor(globalThis, 'Array'); var n = Object.getOwnPropertyDescriptor(globalThis, 'NaN'); return [d.writable, d.enumerable, d.configurable, n.writable, n.configurable, Object.getOwnPropertyDescriptor(globalThis, 'globalThis').enumerable].join(','); });
show('assign NaN/undefined', function () { NaN = 1; undefined = 2; return String(NaN) + ' ' + String(undefined); });
show('strict assign undefined', function () { 'use strict'; undefined = 2; });
var proto = Object.getPrototypeOf(globalThis);
show('global prototype chain', function () { return (proto !== null) + ' ' + ('hasOwnProperty' in globalThis) + ' ' + (globalThis.toString === Object.prototype.toString); });
Object.prototype.fromObjectProto = 'inherited';
show('identifier resolves via Object.prototype', function () { return fromObjectProto; });
delete Object.prototype.fromObjectProto;
show('after delete', function () { return typeof fromObjectProto; });
show('eval var at top creates deletable global', function () { (0, eval)('var evalGlobal = 7'); return [evalGlobal, delete globalThis.evalGlobal, typeof evalGlobal].join(','); });
show('function decl over existing global accessor', function () { return typeof declaredFn + ' ' + declaredFn(); });
show('globalThis writable', function () { var saved = globalThis; globalThis = 'replaced'; var r = typeof saved.globalThis; saved.globalThis = saved; return r; });
console.log(out.join('\n'));
"""
    r = run([*tier, "-e", code])
    assert out(r) == golden("global_object_bindings_in_scripts")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_async_generator_request_queue_and_return(js, golden, tier):
    """CATCHES: async generators that do not queue next/return/throw requests in order, await return values (promises and thenables), run yields in finally after return, close sync iterators whose values reject, or validate receivers fail this."""
    code = r"""var log = [];
function rec(label) { return function (r) { log.push(label + ' ' + JSON.stringify(r)); }; }
function recErr(label) { return function (e) { log.push(label + ' threw ' + (e && e.message !== undefined ? e.message : String(e))); }; }
async function* counter() { try { yield 1; yield 2; yield 3; } finally { log.push('counter finally'); } }
async function* awaitsInFinally() { try { yield 'a'; } finally { await null; log.push('async finally ran'); yield 'from-finally'; } }
async function main() {
  var g = counter();
  // queued requests resolve in order
  await Promise.all([g.next().then(rec('q1')), g.next().then(rec('q2')), g.return('early').then(rec('q3')), g.next().then(rec('q4'))]);
  // return while suspendedStart with a promise value
  var g2 = counter();
  await g2.return(Promise.resolve('awaited-return')).then(rec('start-return'));
  await g2.return(Promise.reject(new Error('rejected-return'))).then(rec('completed-return'), recErr('completed-return'));
  await g2.throw(new Error('on-completed')).then(rec('completed-throw'), recErr('completed-throw'));
  // return with thenable
  var g3 = counter(); await g3.next();
  await g3.return({ then: function (r) { r('thenable-value'); } }).then(rec('thenable-return'));
  // yield inside finally after return
  var g4 = awaitsInFinally(); await g4.next();
  await g4.return('R').then(rec('finally-yield'));
  await g4.next().then(rec('after-finally'));
  // await of a rejected promise inside yield operand
  async function* rejYield() { try { yield Promise.reject(new Error('yield operand rejected')); } catch (e) { yield 'caught:' + e.message; } }
  var g5 = rejYield();
  await g5.next().then(rec('rej-yield'));
  // yield* over sync iterator with rejected promise closes it
  var closed = [];
  var syncIt = { [Symbol.iterator]: function () { var i = 0; return { next: function () { i++; return i === 1 ? { value: 'v1', done: false } : { value: Promise.reject(new Error('sync rejected')), done: false }; }, return: function () { closed.push('sync closed'); return {}; } }; } };
  async function* delegator() { yield* syncIt; }
  var g6 = delegator();
  await g6.next().then(rec('delegate-1'));
  await g6.next().then(rec('delegate-2'), recErr('delegate-2'));
  log.push('closed: ' + closed.join(','));
  // for await over sync iterable with rejected element
  var closed2 = [];
  var syncIt2 = { [Symbol.iterator]: function () { var i = 0; return { next: function () { i++; return { value: i === 2 ? Promise.reject('bad element') : i, done: i > 3 }; }, return: function () { closed2.push('closed'); return {}; } }; } };
  try { for await (var v of syncIt2) log.push('for-await got ' + v); } catch (e) { log.push('for-await caught ' + e + ' closed=' + closed2.length); }
  // async iterator return() result must be an object
  var badReturn = { [Symbol.asyncIterator]: function () { return { next: function () { return Promise.resolve({ value: 1, done: false }); }, return: function () { return 5; } }; } };
  try { for await (var w of badReturn) break; log.push('no error'); } catch (e) { log.push('bad return: ' + e.name + ': ' + e.message); }
  // generator methods on wrong receivers
  try { await counter.prototype.__proto__.next.call({}); } catch (e) { log.push('wrong receiver: ' + e.name); }
  await Object.getPrototypeOf(counter.prototype).next.call({}).then(rec('wrong receiver resolved'), recErr('wrong receiver rejects'));
  // sync generator re-entrancy
  function* reenter() { try { it.next(); } catch (e) { yield 'reentry ' + e.name + ' ' + (e instanceof TypeError); } }
  var it = reenter();
  log.push(it.next().value);
  // throw into suspendedStart sync generator
  function* never() { log.push('body ran'); }
  var n = never();
  try { n.throw(new Error('start-throw')); } catch (e) { log.push('suspendedStart throw: ' + e.message + ' ' + JSON.stringify(n.next())); }
}
main().then(function () { console.log(log.join('\n')); }, function (e) { console.log('FAILED ' + e); });
"""
    r = js(code, *tier)
    assert out(r) == golden("async_generator_request_queue_and_return")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_object_literal_semantics(js, golden, tier):
    """CATCHES: object literals with the wrong key/value evaluation order, accessor/data merging, __proto__ handling, spread semantics, NamedEvaluation function names, or super property access in methods fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var order = [];
function k(name) { order.push('key ' + name); return name; }
function v(val) { order.push('val ' + val); return val; }
var o = { [k('b')]: v(1), a: v(2), [k(1)]: v(3), get [k('g')]() { return 'getter'; }, [k('b')]: v(4) };
show('evaluation and key order', function () { return order.join(', ') + ' => ' + Object.keys(o).join(',') + ' b=' + o.b; });
show('accessor merging', function () { var m = { get x() { return 'get1'; }, set x(val) { this._x = val; }, get x() { return 'get2'; } }; m.x = 5; var d = Object.getOwnPropertyDescriptor(m, 'x'); return m.x + ' ' + m._x + ' ' + typeof d.set + ' ' + d.enumerable; });
show('data then accessor', function () { var m = { x: 1, get x() { return 'acc'; } }; var d = Object.getOwnPropertyDescriptor(m, 'x'); return m.x + ' ' + ('value' in d) + ' ' + typeof d.set; });
show('accessor then data', function () { var m = { get x() { return 'acc'; }, x: 'data' }; return m.x + ' ' + JSON.stringify(Object.getOwnPropertyDescriptor(m, 'x')); });
show('__proto__ literal', function () { var p = { inherited: true }; var a = { __proto__: p }; var b = { ['__proto__']: p }; var c = { __proto__: 5 }; var __proto__ = p; var d = { __proto__ }; return [Object.getPrototypeOf(a) === p, Object.getPrototypeOf(b) === Object.prototype, Object.prototype.hasOwnProperty.call(b, '__proto__'), Object.getPrototypeOf(c) === Object.prototype, Object.prototype.hasOwnProperty.call(d, '__proto__')].join(','); });
show('__proto__ null', function () { var n = { __proto__: null, x: 1 }; return Object.getPrototypeOf(n) + ' ' + ('toString' in n); });
show('duplicate __proto__', function () { return eval('({ __proto__: null, __proto__: null })'); });
show('spread invokes getters, skips non-enumerable', function () { var calls = 0; var src = { get g() { calls++; return 'G'; } }; Object.defineProperty(src, 'hidden', { value: 1, enumerable: false }); src[Symbol('s')] = 'sym'; var copy = { ...src, ...null, ...undefined, ...'hi', ...[9] }; return JSON.stringify(copy) + ' calls=' + calls + ' syms=' + Object.getOwnPropertySymbols(copy).length + ' getterCopiedAsData=' + ('value' in Object.getOwnPropertyDescriptor(copy, 'g')); });
show('spread does not trigger setters', function () { var hit = false; var target = { set x(v) { hit = true; } }; var r = { ...target, ...{ x: 1 } }; return hit + ' ' + r.x; });
show('function names', function () { var s = Symbol('described'); var anon = Symbol(); var m = { plain: function () {}, arrow: () => {}, [s]: function () {}, [anon]: function () {}, get acc() { return 1; }, method() {}, ['comp' + 'uted']: class {}, named: function inner() {}, async am() {}, *gm() {} }; var d = Object.getOwnPropertyDescriptor(m, 'acc'); return [m.plain.name, m.arrow.name, m[s].name, '[' + m[anon].name + ']', d.get.name, m.method.name, m.computed.name, m.named.name, m.am.name, m.gm.name].join('|'); });
show('assignment names', function () { var x; x = function () {}; var y = (function () {}); var z = (0, function () {}); var obj = {}; obj.prop = function () {}; var [d1 = function () {}] = []; var { d2 = () => {} } = {}; return [x.name, y.name, '[' + z.name + ']', '[' + obj.prop.name + ']', d1.name, d2.name].join('|'); });
show('logical assignment names', function () { var a; a ??= function () {}; var b = 0; b ||= () => {}; var c = 1; c &&= class {}; return [a.name, b.name, c.name].join('|'); });
show('super in object methods', function () { var base = { hi: function () { return 'base hi from ' + this.who; } }; var child = { __proto__: base, who: 'child', hi() { return super.hi() + '!'; }, plain: function () { try { return eval('super.hi()'); } catch (e) { return e.name; } } }; var borrowed = { who: 'borrowed', hi: child.hi }; return child.hi() + ' | ' + borrowed.hi() + ' | ' + child.plain(); });
show('super property set', function () { var proto = { set v(x) { this._v = 'via-proto-setter:' + x; } }; var obj = { __proto__: proto, assign() { super.v = 1; super.w = 2; return this._v + ' w-own=' + Object.prototype.hasOwnProperty.call(this, 'w'); } }; return obj.assign(); });
show('super with null proto', function () { var obj = { m() { return super.x; } }; Object.setPrototypeOf(obj, null); return obj.m(); });
show('numeric keys canonicalized', function () { var n = { 1.50: 'a', 0x10: 'b', 1e3: 'c', '01': 'd', [-0]: 'e', .5: 'f' }; return Object.keys(n).join(','); });
show('shorthand and computed symbols', function () { var x = 1, y = 2; var sym = Symbol.iterator; var it = { x, y, [sym]: function* () { yield x; yield y; } }; return [...it].join() + ' ' + JSON.stringify(it); });
show('getter on primitive receiver', function () { Object.defineProperty(Number.prototype, 'selfType', { get: function () { 'use strict'; return typeof this; }, configurable: true }); var r = (5).selfType; delete Number.prototype.selfType; return r; });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("object_literal_semantics")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_destructuring_semantics(js, golden, tier):
    """CATCHES: destructuring that does not close iterators (or closes exhausted/throwing ones), evaluates defaults eagerly or out of order, includes excluded keys in object rest, or mis-orders assignment-pattern reference and value evaluation fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function tracked(values) { var log = []; var it = { log: log, [Symbol.iterator]: function () { var i = 0; return { next: function () { log.push('next'); return i < values.length ? { value: values[i++], done: false } : { value: undefined, done: true }; }, return: function () { log.push('return'); return {}; } }; } }; return it; }
show('array pattern closes iterator', function () { var t = tracked([1, 2, 3]); var [a, b] = t; return a + b + ' ' + t.log.join(','); });
show('exhausted iterator not closed', function () { var t = tracked([1]); var [a, b, c] = t; return a + ' ' + b + ' ' + t.log.join(','); });
show('rest drains', function () { var t = tracked([1, 2, 3]); var [first, ...rest] = t; return first + ' [' + rest + '] ' + t.log.join(','); });
show('elision', function () { var t = tracked([1, 2, 3]); var [, , third] = t; return third + ' ' + t.log.join(','); });
show('empty pattern', function () { var t = tracked([1]); var [] = t; return t.log.join(','); });
show('default evaluated lazily', function () { var calls = []; function d(n) { calls.push(n); return n; } var [a = d('a'), b = d('b')] = [undefined, null]; var { c = d('c'), e = d('e') } = { c: 0 }; return [a, b, c, e].join(',') + ' calls=' + calls.join(','); });
show('defaults see earlier bindings', function () { var [x = 1, y = x * 10, z = y + x] = []; return [x, y, z].join(); });
show('default TDZ', function () { var [p = q, q = 1] = []; return p; });
show('let default TDZ', function () { let [p = q, q = 1] = []; return p; });
show('object rest', function () { var sym = Symbol('s'); var src = { a: 1, b: 2, [sym]: 3 }; Object.defineProperty(src, 'hidden', { value: 4, enumerable: false }); var { a, ...rest } = src; return a + ' ' + JSON.stringify(rest) + ' sym=' + (rest[sym] === 3) + ' hidden=' + ('hidden' in rest); });
show('object rest computed key excluded', function () { var key = 'dyn'; var { [key]: val, ...others } = { dyn: 'D', keep: 'K' }; return val + ' ' + JSON.stringify(others); });
show('rest from primitive', function () { var { length, ...chars } = 'ab'; return length + ' ' + JSON.stringify(chars); });
show('null destructure', function () { var { x } = null; });
show('undefined destructure', function () { try { var [y] = undefined; } catch (e) { return e.constructor.name; } });
show('non-iterable', function () { var [z] = {}; });
show('nested defaults', function () { var { a: { b: [c = 'deflt'] = [] } = {} } = {}; return c; });
show('assignment targets', function () { var o = {}; var arr = []; ({ x: o.p, y: arr[0], z: o['q' + 1] = 'dz' } = { x: 'X', y: 'Y' }); [o.r, ...arr[1]] = [1, 2, 3]; return JSON.stringify(o) + ' ' + JSON.stringify(arr); });
show('assignment evaluation order', function () { var log = []; var target = { set a(v) { log.push('set a=' + v); } }; function src() { log.push('get source'); return { get a() { log.push('get a'); return 1; } }; } ({ a: (log.push('target ref'), target).a } = src()); return log.join(', '); });
show('swap', function () { var a = 1, b = 2; [a, b] = [b, a]; return a + ',' + b; });
show('destructure in params', function () { function f({ a, b: [c, d = 'dd'] = [] } = {}, ...[e, f2]) { return [a, c, d, e, f2].join('|'); } return f({ a: 'A', b: ['C'] }, 'E', 'F') + ' ' + f() + ' ' + f.length; });
show('params null', function () { function g({ a }) { return a; } return g(null); });
show('catch destructuring', function () { try { throw { code: 42, detail: ['x'] }; } catch ({ code, detail: [first] }) { return code + first; } });
show('for-of destructuring', function () { var r = []; for (var [k, { v = 'none' }] of [['a', { v: 1 }], ['b', {}]]) r.push(k + v); for (const { length } of ['xyz', [1]]) r.push(length); return r.join(','); });
show('generator closed by pattern', function () { var log = []; function* g() { try { yield 1; yield 2; } finally { log.push('gen closed'); } } var [one] = g(); return one + ' ' + log.join(); });
show('return throws during close', function () { var it = { [Symbol.iterator]: function () { return { next: function () { return { value: 1, done: false }; }, return: function () { throw new Error('close failed'); } }; } }; var [a] = it; return a; });
show('next throws not closed', function () { var closed = false; var it = { [Symbol.iterator]: function () { return { next: function () { throw new Error('next failed'); }, return: function () { closed = true; return {}; } }; } }; try { var [a] = it; } catch (e) { return e.message + ' closed=' + closed; } });
show('default throws closes', function () { var closed = false; var it = { [Symbol.iterator]: function () { return { next: function () { return { value: undefined, done: false }; }, return: function () { closed = true; return {}; } }; } }; try { var [a = (function () { throw new Error('default threw'); })()] = it; } catch (e) { return e.message + ' closed=' + closed; } });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("destructuring_semantics")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_parameter_scope_and_auto_accessors(js, golden, tier):
    """CATCHES: function instantiation that shares one scope between parameter expressions and the body (so body vars are not seeded from parameters, defaults see body declarations, or param closures write the wrong binding), miscomputes length/duplicate-parameter rules, or breaks class auto-accessors fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function seeded(a, b = function () { return a; }) { var a; var r1 = a; a = 'changed'; return [r1, a, b()].join(','); }
show('body var seeded from parameter', function () { return seeded('orig'); });
function seededFn(a, b = () => a) { function a() { return 'fn'; } return typeof a + ' ' + typeof b(); }
show('body function shadows parameter', function () { return seededFn(1); });
function argsSeed(x = 1) { var arguments; return typeof arguments + ' ' + arguments.length; }
show('var arguments seeded with param exprs', function () { return argsSeed(); });
function closures(x, getX = () => x, setX = (v) => { x = v; }) { var x; setX('set-by-param-closure'); return [x, getX()].join(' / '); }
show('param closures see param scope', function () { return closures('init'); });
show('param TDZ', function () { function f(a = b, b = 1) { return a; } return f(); });
show('param refers to earlier', function () { function f(a, b = a * 2, c = b + a) { return [a, b, c].join(); } return f(3); });
show('default not applied for null', function () { function f(a = 'dflt') { return a; } return [f(undefined), f(null), f()].join('|'); });
show('length stops at first default or rest', function () { return [function (a, b = 1, c) {}.length, function (a, ...r) {}.length, function ({ a }, [b]) {}.length, (function (a, b) {}).length].join(); });
show('sloppy duplicate params', function () { function f(a, a) { return a; } return f(1, 2) + ' ' + f.length; });
show('strict duplicate params', function () { return Function('a', 'a', '"use strict"; return a'); });
show('duplicate with default', function () { return Function('a', 'a = 1', 'return a'); });
show('use strict with non-simple params', function () { return Function('a = 1', '"use strict"; return a'); });
show('defaults evaluated per call', function () { var n = 0; function f(a = ++n) { return a; } return [f(), f(), f(10), f()].join(); });
show('default sees outer not body', function () { var v = 'outer'; function f(a = v) { var v = 'body'; return a; } return f(); });
show('body function invisible to defaults', function () { function f(a = typeof g) { function g() {} return a; } return f(); });
show('rest param', function () { function f(a, ...rest) { return rest.length + ' ' + Array.isArray(rest) + ' ' + arguments.length; } return f(1, 2, 3); });
show('arrow params and arguments', function () { var outer = function () { var arrow = (a = arguments[0]) => a + ':' + arguments.length; return arrow(); }; return outer('from-outer', 2); });
show('new.target in default', function () { function F(x = new.target) { this.x = x === F; } return new F().x + ' ' + typeof F(); });
show('this in default', function () { var o = { m: function (t = this) { return t === o; } }; return o.m(); });
show('super in default param', function () { var base = { greet: function () { return 'base'; } }; var obj = { __proto__: base, m(x = super.greet()) { return x; } }; return obj.m(); });
show('yield in generator default', function () { return Function('function* g(a = yield) {}'); });
show('await as param name in async', function () { return Function('async function f(await) {}'); });
class A { accessor x = 1; static accessor s = 'static'; accessor #p = 'priv'; getP() { return this.#p; } setP(v) { this.#p = v; } }
show('auto-accessor', function () { var a = new A(); var d = Object.getOwnPropertyDescriptor(A.prototype, 'x'); a.x = 5; return [a.x, typeof d.get, typeof d.set, d.enumerable, Object.keys(a).length, A.s, a.getP(), (a.setP('np'), a.getP())].join(','); });
show('auto-accessor foreign receiver get', function () { return Object.getOwnPropertyDescriptor(A.prototype, 'x').get.call({}); });
show('auto-accessor foreign receiver set', function () { return Object.getOwnPropertyDescriptor(A.prototype, 'x').set.call({}, 1); });
show('auto-accessor subclass override', function () { class B extends A { get x() { return 'overridden ' + super.x; } } return new B().x; });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("parameter_scope_and_auto_accessors")
    assert (r.returncode, r.stderr) == (0, b"")


GC_LIB = r"""export let counter = 0;
export function bump() { counter++; return counter; }
export const table = { rows: [1, 2, 3] };
"""

GC_LEGACY = r"""var scopeObj = { a: 1, b: [1, 2, 3] };
var result;
with (scopeObj) {
  for (var i = 0; i < 50; i++) { var tmp = { i: i, arr: new Array(20).fill(i) }; }
  $262.gc();
  result = a + b.length + tmp.arr.length;
}
function withArgs(a, b) { var ar = arguments; $262.gc(); a = 'A'; return ar[0] + ar[1] + ar.length; }
function makeCycle(n) { var box = { n: n }; box.get = function () { return box.n; }; return n; }
var total = 0;
for (var j = 0; j < 30000; j++) { var c = {}; c.self = c; total += makeCycle(1); }
$262.gc();
module.exports = { result: result, args: withArgs('x', 'y'), total: total };
"""


@pytest.mark.parametrize("tier", TIERS)
def test_gc_keeps_live_bindings_scopes_and_weak_entries(js, golden, workdir, tier):
    """CATCHES: a cycle collector that frees objects still reachable through module import bindings, with-statement objects, mapped arguments, closures, suspended generators or strongly-held WeakMap/WeakRef targets, or that mishandles cyclic garbage, fails this."""
    (workdir / "lib.mjs").write_text(GC_LIB, encoding="utf-8")
    (workdir / "legacy.cjs").write_text(GC_LEGACY, encoding="utf-8")
    code = r"""import { counter, bump, table } from './lib.mjs';
import * as ns from './lib.mjs';
import legacy from './legacy.cjs';
const out = [];
bump();
$262.gc();
out.push('live binding after gc: ' + counter + ' ' + ns.counter);
bump();
$262.gc();
out.push('again: ' + counter + ' rows=' + table.rows.join(','));
out.push('cjs: with=' + legacy.result + ' args=' + legacy.args + ' cycles=' + legacy.total);
const holder = new WeakMap();
const keys = [];
for (let i = 0; i < 200; i++) { const k = { i }; keys.push(k); holder.set(k, 'v' + i); }
for (let r = 0; r < 20; r++) { let junk = []; for (let j = 0; j < 500; j++) junk.push({ j, nested: { j } }); }
$262.gc();
out.push('weakmap survivors: ' + keys.filter(k => holder.get(k) === 'v' + k.i).length);
const ref = new WeakRef(keys[5]);
$262.gc();
out.push('weakref deref: ' + (ref.deref() === keys[5]));
const fns = [];
for (let i = 0; i < 100; i++) { fns.push(() => i * 2); }
$262.gc();
out.push('closures: ' + fns.reduce((a, f) => a + f(), 0));
function* gen() { const local = { tag: 'gen-local' }; yield local.tag; $262.gc(); yield local.tag + '!'; }
out.push('generator: ' + [...gen()].join(' '));
await null;
$262.gc();
out.push('after await: ' + bump());
console.log(out.join('\n'));
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("gc_keeps_live_bindings_scopes_and_weak_entries")
    assert (r.returncode, r.stderr) == (0, b"")


NS_A = r"""import * as self from './a.mjs';
import * as b from './b.mjs';
const out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('tdz read via namespace', () => b.later);
show('tdz set via namespace', () => { b.later = 1; });
show('set export', () => { b.value = 2; });
show('set missing', () => { b.missing = 2; });
show('Reflect.set', () => Reflect.set(b, 'value', 3));
show('Reflect.set receiver ns strict', () => { 'use strict'; var o = Object.create(null); return Reflect.set(o, 'zz', 1, b); });
show('delete export', () => { delete b.value; });
show('delete missing', () => delete b.missing);
show('defineProperty same', () => Object.defineProperty(b, 'value', { value: 'v' }) === b);
show('defineProperty different', () => Object.defineProperty(b, 'value', { value: 'other' }));
show('Reflect.defineProperty', () => Reflect.defineProperty(b, 'value', { value: 'v', writable: true, enumerable: true, configurable: false }));
show('gOPD', () => JSON.stringify(Object.getOwnPropertyDescriptor(b, 'value')));
show('gOPD tdz', () => Object.getOwnPropertyDescriptor(b, 'later'));
show('keys', () => Reflect.ownKeys(b).map(String).join());
show('toStringTag', () => Object.prototype.toString.call(b) + ' ' + b[Symbol.toStringTag]);
show('proto', () => Object.getPrototypeOf(b) + ' ' + Object.isExtensible(b) + ' ' + Object.isFrozen(b) + ' ' + Object.isSealed(b));
show('setPrototypeOf', () => Reflect.setPrototypeOf(b, {}) + ' ' + Reflect.setPrototypeOf(b, null));
show('in', () => ('value' in b) + ' ' + ('missing' in b) + ' ' + ('later' in b));
show('self cycle', () => typeof self.default);
show('with object assign', () => { var child = Object.create(b); return Reflect.set(child, 'other', 1, b); });
export default 'self-default';
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS)
def test_module_namespace_exotic_object(js, golden, workdir, tier):
    """CATCHES: a module namespace object that allows writes, deletes or redefinitions of exports, skips the TDZ check for uninitialised let exports, reports wrong descriptors/keys/prototype, or is not sealed fails this."""
    (workdir / "a.mjs").write_text(NS_A, encoding="utf-8")
    code = r"""import './a.mjs';
export var value = 'v';
export let later = 'initialized';
"""
    r = js(code, *tier, name="b.mjs")
    assert out(r) == golden("module_namespace_exotic_object")
    assert (r.returncode, r.stderr) == (0, b"")


def test_uncaught_stack_overflow_reports_range_error(run):
    """CATCHES: an engine that dies with a native stack overflow (signal, abort, or Rust panic text) on unbounded recursion instead of surfacing an uncaught RangeError after flushing earlier output fails this."""
    r = run(["-e", "console.log('before'); function down(n) { return down(n + 1) + 1; } down(0); console.log('never');"])
    assert out(r) == "before\n"
    assert (r.returncode, err(r)) == (1, "Uncaught RangeError: Maximum call stack size exceeded\n")
