"""JavaScript runtime semantics of the evaluation core: scoping/hoisting/TDZ, closures, parameters
and the arguments object, destructuring/spread, evaluation order, classes, accessors, generators,
async functions and async generators, iterator closing, control flow (labels, switch, finally),
optional chaining and logical assignment, operators, sloppy vs strict mode, `with`, direct/indirect
eval and completion values (eval and the piped REPL). Several programs are run on more than one
execution tier against ONE shared golden, because the tiers must agree observably."""

import pytest

from conftest import assert_result, check_script, resources_for

G = resources_for(__file__)

TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
         pytest.param(["--tier=bytecode"], id="bytecode")]
TWO_TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp")]


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_hoisting_and_temporal_dead_zone(run, workdir, cli):
    """CATCHES: var/function hoisting done wrongly (function value vs undefined), let/const/class read
    before initialisation not throwing ReferenceError (including typeof, closures, default params,
    self-referencing initialisers, switch cases, for heads), or var/function/param precedence errors."""
    check_script(run, workdir, G, "hoisting_tdz", r'''
const out = [];
out.push(typeof hoistedFn, typeof hoistedVar, String(hoistedVar), hoistedFn());
var hoistedVar = 'assigned';
function hoistedFn() { return 'fn hoisted'; }
out.push(hoistedVar);
try { tdzLet; } catch (e) { out.push(e.name + ': ' + e.message); }
try { typeof tdzLet; } catch (e) { out.push('typeof in TDZ -> ' + e.name); }
let tdzLet = 1;
try { new TdzClass(); } catch (e) { out.push(e.name + ': ' + e.message); }
class TdzClass {}
const readLater = () => laterConst; try { readLater(); } catch (e) { out.push('closure before init: ' + e.message); }
const laterConst = 'now ok'; out.push(readLater());
try { (function (a = b, b = 1) { return a; })(); } catch (e) { out.push('param TDZ: ' + e.message); }
try { let self = self + 1; } catch (e) { out.push('self ref: ' + e.message); }
try { const [z = z] = []; } catch (e) { out.push('pattern self ref: ' + e.message); }
{ out.push(typeof blockFn); function blockFn() {} }
switch (1) { case 0: let sw = 'zero'; case 1: try { sw; } catch (e) { out.push('switch TDZ: ' + e.message); } }
try { for (let i = (() => i)(); ;) break; } catch (e) { out.push('for-init TDZ: ' + e.message); }
try { for (const x of [x]) {} } catch (e) { out.push('for-of head TDZ: ' + e.message); }
var dupVar = 1; { var dupVar = 2; } out.push(dupVar);
let shadowed = 'outer'; { let shadowed = 'inner'; out.push(shadowed); } out.push(shadowed);
function fnScope() { if (false) { var neverAssigned = 1; } return neverAssigned; } out.push(String(fnScope()));
function paramsAndVar(a) { var a; return a; } out.push(paramsAndVar('kept'));
function paramsAndFn(a) { function a() {} return typeof a; } out.push(paramsAndFn(1));
function varAndFn() { var f = 1; function f() {} return typeof f; } out.push(varAndFn());
function fnThenVar() { function g() {} var g; return typeof g; } out.push(fnThenVar());
try { const c = 1; c++; } catch (e) { out.push(e.name + ': ' + e.message); }
(function () { 'use strict'; try { undeclared = 1; } catch (e) { out.push(e.name + ': ' + e.message); } })();
const fnExprName = function inner() { inner = 1; return typeof inner; }; out.push(fnExprName());
const fnExprStrict = function inner2() { 'use strict'; try { inner2 = 1; } catch (e) { return e.name + ': ' + e.message; } }; out.push(fnExprStrict());
class ClsInner { static rename() { try { ClsInner = 1; } catch (e) { return e.name + ': ' + e.message; } } } out.push(ClsInner.rename());
console.log(out.join('\n'));
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_closures_and_per_iteration_bindings(run, workdir, cli):
    """CATCHES: let/const loop variables not copied per iteration (closures all seeing the last value),
    var loop variables wrongly copied, for-init closures capturing the wrong environment, block scopes
    in switch/labelled loops, and closure state (counters/memoisation) shared between instances."""
    check_script(run, workdir, G, "closures_loops", r'''
const fns = [];
for (var i = 0; i < 3; i++) fns.push(() => i);
for (let j = 0; j < 3; j++) fns.push(() => j);
for (let k = 0; k < 3; k++) { fns.push(() => k); k++; }
for (const x of ['a', 'b']) fns.push(() => x);
for (const key in { p: 1, q: 2 }) fns.push(() => key);
let w = 0; while (w < 2) { let captured = w; fns.push(() => captured); w++; }
console.log(fns.map(f => f()).join(','));
const mutators = []; for (let m = 0; m < 3; m++) { mutators.push(() => m++); mutators.push(() => m); }
console.log(mutators.map(f => f()).join(','));
const closuresInInit = []; for (let n = 0, get = () => n; n < 2; n++) closuresInInit.push(get);
console.log(closuresInInit.map(f => f()).join(','));
function counter() { let c = 0; return { inc: () => ++c, dec: () => --c, get value() { return c; } }; }
const c1 = counter(), c2 = counter(); c1.inc(); c1.inc(); c2.dec(); console.log(c1.value, c2.value);
function makeAdders() { const out = {}; for (const n of [1, 5, 10]) out['add' + n] = (x) => x + n; return out; }
const adders = makeAdders(); console.log(adders.add1(1), adders.add5(1), adders.add10(1));
const memo = (fn) => { const cache = new Map(); return (n) => cache.has(n) ? 'cached:' + cache.get(n) : (cache.set(n, fn(n)), cache.get(n)); };
const sq = memo(x => x * x); console.log(sq(4), sq(4), sq(5));
let shared = 'v1'; const readShared = () => shared; shared = 'v2'; console.log(readShared());
function outer() { var x = 'outer x'; function inner() { return x; } x = 'changed'; return inner; } console.log(outer()());
const curried = (a) => (b) => (c) => a * 100 + b * 10 + c; console.log(curried(1)(2)(3));
function recursiveClosure(n) { const go = (k) => k <= 0 ? [] : [k, ...go(k - 1)]; return go(n); } console.log(recursiveClosure(4).join());
const once = (f) => { let done = false, r; return (...a) => done ? r : (done = true, r = f(...a)); };
const o1 = once((x) => 'first ' + x); console.log(o1(1), o1(2));
for (var v = 0; v < 2; v++) {} console.log(v);
const fnsInSwitch = []; for (let s = 0; s < 2; s++) { switch (s) { case 0: { const t = 'zero'; fnsInSwitch.push(() => t); break; } default: { const t = 'other'; fnsInSwitch.push(() => t); } } }
console.log(fnsInSwitch.map(f => f()).join());
const labelled = []; outer: for (let a = 0; a < 3; a++) { for (let b = 0; b < 3; b++) { if (b > a) continue outer; labelled.push(() => `${a}${b}`); } } console.log(labelled.map(f => f()).join(' '));
const doFns = []; let d = 0; do { const dd = d; doFns.push(() => dd * 10); d++; } while (d < 3); console.log(doFns.map(f => f()).join());
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_parameters_defaults_rest_and_arguments(run, workdir, cli):
    """CATCHES: a mapped arguments object that does not alias sloppy simple parameters (or aliases
    strict/default/rest/destructured ones), wrong arguments.length/callee/iterator, defaults evaluated
    eagerly or for null, parameter scope seeing body vars, wrong Function.length, and bind/apply/call
    argument passing."""
    check_script(run, workdir, G, "parameters_arguments", r'''
function mapped(a, b) { arguments[0] = 'changed via arguments'; b = 'changed param'; return [a, arguments[1], arguments.length, arguments[2]].join('|'); }
console.log(mapped(1, 2, 3), mapped(1));
function unmappedStrict(a) { 'use strict'; arguments[0] = 'x'; a = 'y'; return [a, arguments[0]].join('|'); }
console.log(unmappedStrict(1));
function unmappedDefaults(a = 0) { arguments[0] = 'x'; return [a, arguments[0]].join('|'); } console.log(unmappedDefaults(1));
function unmappedRest(a, ...r) { a = 'na'; return [arguments[0], r.length].join('|'); } console.log(unmappedRest(1, 2, 3));
function unmappedDestr({ a }) { return arguments[0].a; } console.log(unmappedDestr({ a: 'destr' }));
function deleteMapping(a) { delete arguments[0]; arguments[0] = 'new'; return a; } console.log(deleteMapping('orig'));
function lengthBeyond(a) { arguments.length = 5; return [arguments.length, Array.from(arguments).length].join(); } console.log(lengthBeyond(1));
function argsProps() { return [Object.prototype.toString.call(arguments), Array.isArray(arguments), typeof arguments[Symbol.iterator], arguments.callee === argsProps, Object.keys(arguments).join()].join(' '); } console.log(argsProps('a', 'b'));
function strictCallee() { 'use strict'; try { return arguments.callee; } catch (e) { return e.name; } } console.log(strictCallee());
function spreadArgs() { return [...arguments].reverse().join(); } console.log(spreadArgs(1, 2, 3));
function defaults(a, b = a * 2, c = () => a + b, d = this) { a = 10; return [a, b, c(), typeof d].join(); } console.log(defaults(1), defaults.call('t', 1, 1));
function defaultScope(x = () => y) { var y = 'body y'; return typeof x(); }
try { console.log(defaultScope()); } catch (e) { console.log(e.name + ': ' + e.message); }
function bodyVarShadowsParam(a, f = () => a) { var a = 'body'; return [a, f()].join(); } console.log(bodyVarShadowsParam('param'));
function defaultUndefinedOnly(a = 'dflt', b = 'dflt') { return [a, b].join(); } console.log(defaultUndefinedOnly(undefined, null), defaultUndefinedOnly(0, ''));
const evaluatedEachCall = []; function each(a = evaluatedEachCall.push('eval')) { return a; } each(); each(); each(5); console.log(evaluatedEachCall.length);
function lengths(a, b, ...c) {} console.log(lengths.length, ((a, b = 1, ...c) => {}).length, (function (...args) {}).length);
function restWithDestr(...[first, ...others]) { return first + ':' + others.length; } console.log(restWithDestr(1, 2, 3));
function argumentsShadow(arguments) { return arguments; } console.log(argumentsShadow('param named arguments'));
function argInArrow() { const f = () => arguments.length; return f(1, 2, 3, 4); } console.log(argInArrow(9));
function sum() { let s = 0; for (const v of arguments) s += v; return s; } console.log(sum(1, 2, 3, 4), sum.apply(null, [5, 5]), sum.call(null, ...[1, 1]));
const bound = sum.bind(null, 100); console.log(bound(1), bound.length, bound.name, new ((function F(a, b) { this.v = a + b; }).bind(null, 1))(2).v);
function tooMany(a) { return arguments.length; } console.log(tooMany(), tooMany(1, 2, 3, ...[4, 5]), tooMany(...'abc'), tooMany(...new Set([1, 1, 2])));
function fnLength(a, b) {} Object.defineProperty(fnLength, 'length', { value: 'custom' }); console.log(fnLength.length);
function paramEval(a, b = eval('a + 1')) { return b; } console.log(paramEval(1));
function paramArgs(a, b = arguments.length) { return b; } console.log(paramArgs(1));
function arityThis() { return typeof this; } console.log(arityThis.call(null), arityThis.apply(undefined), arityThis.call(1), (function () { 'use strict'; return this; }).call(null));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_evaluation_order(run, workdir, cli):
    """CATCHES: operands, keys, call arguments, template substitutions, destructuring defaults and class
    element keys evaluated out of left-to-right order, the RHS not evaluated before a null-base
    assignment throws, compound assignment re-reading its target, or accessor get/set pairs wrong."""
    check_script(run, workdir, G, "evaluation_order", r'''
const order = [];
const t = (v) => { order.push(String(v)); return v; };
const flush = (label) => { console.log(label + ': ' + order.join(' ')); order.length = 0; };
t(1) + t(2) * t(3) - t(4) ** t(5); flush('binary');
const obj = { [t('k1')]: t('v1'), [t('k2')]: t('v2') }; flush('object literal');
const target = {}; t(target)[t('prop')] = t('rhs'); flush('member assign');
try { t(null)[t('p')] = t('value'); } catch (e) { order.push(e.name); } flush('assign to null base');
try { t(undefined)[t('key')]; } catch (e) { order.push(e.name); } flush('read null base');
try { t('notfn')(t('arg1'), t('arg2')); } catch (e) { order.push(e.name); } flush('call non-function');
try { new (t(5))(t('ctorArg')); } catch (e) { order.push(e.name); } flush('new non-constructor');
const arr = [t('e0'), ...[t('e1')], t('e2')]; flush('array');
t(true) ? t('then') : t('else'); t(0) || t('or'); t(1) && t('and'); t(null) ?? t('nullish'); flush('short circuit');
let x = 1; x += t(x = 10); flush('x += (x = 10) gives ' + x);
let y = { v: 1 }; const keyObj = { toString() { order.push('key->string'); return 'v'; } }; y[keyObj] += t('add'); flush('compound with object key gives ' + y.v);
const getterObj = { get g() { order.push('get g'); return 1; }, set g(v) { order.push('set g ' + v); } }; getterObj.g++; getterObj.g += 5; flush('update via accessor');
function f(a, b, c) { order.push('body'); } f(t('a1'), t('a2'), t('a3')); flush('args');
`${t('tpl1')}${t('tpl2')}`; flush('template');
const fnObj = { m(...args) { order.push('m called'); } }; fnObj[t('m')](t('marg')); flush('computed method call');
t(1) < t(2); t({ valueOf: () => (order.push('left valueOf'), 1) }) > t({ valueOf: () => (order.push('right valueOf'), 2) }); flush('relational');
const [d1 = t('default1'), d2 = t('default2')] = [t('given')]; flush('destructuring defaults');
({ [t('dk')]: target.dst = t('dflt') } = {}); flush('assignment pattern');
(t('c1'), t('c2'), t('c3')); flush('comma');
delete t({ z: 1 })[t('z')]; typeof t('typeof operand'); void t('void operand'); flush('unary');
class K { static [t('static key')] = t('static val'); [t('inst key')] = t('inst val'); [t('method key')]() {} } flush('class definition');
new K(); flush('class instantiation');
const traced = (name, prim) => ({ valueOf() { order.push(name + '.valueOf'); return prim; }, toString() { order.push(name + '.toString'); return 'str:' + name; } });
const a = traced('a', 1), b = traced('b', 2);
console.log(a + b, a < b, a == 1, `${a}`, String(b), a + '', [a] + '', a * b, -a, +b); flush('ToPrimitive hints');
''', cli=cli)


def test_spread_in_calls_arrays_and_objects(run, workdir):
    """CATCHES: spread that skips holes/iterator protocol (strings by code point, Sets, Maps, custom
    iterators interleaved with other arguments), object spread that copies non-enumerables, invokes
    getters at the wrong time or uses the wrong Proxy traps, or fails on large argument lists."""
    check_script(run, workdir, G, "spread", r'''
const log = [];
function collect(...args) { return JSON.stringify(args); }
console.log(collect(...[1, 2], 3, ...'ab', ...new Set([4, 4, 5]), ...new Map([[6, 7]]), ...[], ...[[8]]));
console.log([...[1, , 3]].length, JSON.stringify([...[1, , 3]]), 1 in [...[1, , 3]], JSON.stringify([0, ...[1, 2], ...[3], 4]));
const iterable = { *[Symbol.iterator]() { log.push('iter start'); yield 'x'; log.push('iter mid'); yield 'y'; } };
console.log(collect(log.push('arg0') && 'a0', ...iterable, log.push('arg-last') && 'aN'), log.join(','));
console.log(Math.max(...[1, 5, 3]), Math.min(...[]), String.fromCharCode(...[72, 105]));
const big = Array.from({ length: 10000 }, (_, i) => i); console.log(Math.max(...big), collect(...big).length);
function Point(x, y) { this.x = x; this.y = y; } const pt = new Point(...[1, 2]); console.log(pt.x + pt.y, pt instanceof Point);
class Vec { constructor(...c) { this.c = c; } } console.log(new Vec(...'xyz').c.join('-'));
const objSpread = { ...{ a: 1, b: 2 }, ...{ b: 3, c: 4 }, d: 5 }; console.log(JSON.stringify(objSpread));
const withGetter = { get g() { log.push('spread getter'); return 'G'; } }; const copy = { ...withGetter }; console.log(copy.g, Object.getOwnPropertyDescriptor(copy, 'g').writable);
const symKey = Symbol('k'); const s2 = { ...{ [symKey]: 'sym', regular: 'r' } }; console.log(s2[symKey], Object.getOwnPropertySymbols(s2).length);
const proxy = new Proxy({ a: 1, b: 2 }, { ownKeys(t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor(t, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, get(t, k) { log.push('get ' + String(k)); return t[k]; } });
log.length = 0; const fromProxy = { ...proxy }; console.log(JSON.stringify(fromProxy), log.join(','));
const arrLike = { 0: 'a', 1: 'b', length: 2 }; console.log(JSON.stringify({ ...arrLike }), Array.from(arrLike).join());
try { collect(...{}); } catch (e) { console.log(e.name + ': ' + e.message); }
try { [...123]; } catch (e) { console.log(e.name + ': ' + e.message); }
const s = 'a😀b'; console.log([...s].length, s.length, [...''].length);
function optionalCall(...a) { return a.length; } const maybe = null; console.log(maybe?.(...[1, 2]), optionalCall?.(...[1, 2]));
const o = { method(...a) { return this === o && a.join(); } }; console.log(o.method(...[1, 2]), o['method'](...'ab'));
console.log(Array.of(...[1, 2]).length, [].concat(...[[1], [2, [3]]]).length, Object.assign({}, ...[{ a: 1 }, { b: 2 }]).b);
''')


@pytest.mark.parametrize("cli", TIERS)
def test_class_features(run, workdir, cli):
    """CATCHES: wrong class semantics: field initialisation order relative to super(), static blocks,
    private fields/methods/static privates and `#x in obj`, super method/getter calls, computed and
    generator members, non-enumerable methods, and the constructor errors (call without new, missing
    or repeated super(), `this` before super, bad return values); all tiers must agree."""
    check_script(run, workdir, G, "class_features", r'''
const log = [];
class Base {
  static count = 0;
  baseField = (log.push('baseField'), 'b');
  constructor(x) { log.push('Base ctor ' + new.target.name); this.x = x; Base.count++; }
  greet() { return 'base greet ' + this.x; }
  get kind() { return 'base'; }
  static create(...a) { return new this(...a); }
  toString() { return `Base(${this.x})`; }
}
class Derived extends Base {
  #secret = 42;
  static #instances = 0;
  field = (log.push('derivedField'), this.x * 2);
  ['comp' + 'uted'] = 'cf';
  static { log.push('static block, count=' + Base.count); Derived.tag = 'T'; }
  constructor(x) { log.push('Derived before super'); super(x + 1); Derived.#instances++; log.push('Derived after super'); }
  greet() { return 'derived>' + super.greet(); }
  get kind() { return 'derived/' + super.kind; }
  #priv() { return this.#secret; }
  static get instances() { return Derived.#instances; }
  static isDerived(o) { return #secret in o; }
  reveal() { return this.#priv(); }
  set secret(v) { this.#secret = v; }
  static async asyncStatic() { return 'as'; }
  *[Symbol.iterator]() { yield this.x; yield this.field; }
}
const d = new Derived(1);
console.log(log.join(' | '));
console.log(d.greet(), d.kind, d.field, d.computed, d.reveal(), String(d), [...d].join());
d.secret = 7; console.log(d.reveal(), Derived.instances, Derived.isDerived(d), Derived.isDerived({}), Derived.tag, Base.count);
const d2 = Derived.create(10); console.log(d2 instanceof Derived, d2.x, Derived.instances, Object.keys(d2).join());
console.log(typeof Derived, Object.getPrototypeOf(Derived) === Base, Derived.prototype.constructor === Derived);
console.log(Object.getOwnPropertyNames(Derived.prototype).join(), Object.getOwnPropertyNames(Derived).sort().join());
console.log(JSON.stringify(Object.getOwnPropertyDescriptor(Base.prototype, 'greet')), Object.getOwnPropertyDescriptor(Derived, 'prototype').writable);
try { Derived(); } catch (e) { console.log(e.name + ': ' + e.message); }
try { Derived.prototype.reveal.call({}); } catch (e) { console.log(e.name + ': ' + e.message); }
try { Object.getOwnPropertyDescriptor(Derived.prototype, 'secret').set.call({}, 1); } catch (e) { console.log(e.name + ': ' + e.message); }
class NoSuper extends Base { constructor() { } }
try { new NoSuper(); } catch (e) { console.log(e.name + ': ' + e.message); }
class ThisFirst extends Base { constructor() { this.a = 1; super(); } }
try { new ThisFirst(); } catch (e) { console.log(e.name + ': ' + e.message); }
class TwiceSuper extends Base { constructor() { super(1); super(2); } }
try { new TwiceSuper(); } catch (e) { console.log(e.name + ': ' + e.message); }
class RetObj extends Base { constructor() { return { custom: true }; } }
console.log(JSON.stringify(new RetObj()));
class RetPrim extends Base { constructor() { super(0); return 1; } }
try { new RetPrim(); } catch (e) { console.log(e.name + ': ' + e.message); }
class BaseRetPrim { constructor() { this.q = 1; return 5; } }
console.log(new BaseRetPrim().q);
class PrivStatic { static #s() { return 'static private method'; } static call() { return PrivStatic.#s(); } static bad() { try { return SubPriv.#s(); } catch (e) { return e.name; } } }
class SubPriv extends PrivStatic {} console.log(PrivStatic.call(), PrivStatic.bad());
class DoubleInit { constructor(o) { return o; } } class Stamp extends DoubleInit { #mark = 'm'; static has(o) { return #mark in o; } }
const plain = {}; new Stamp(plain); console.log(Stamp.has(plain)); try { new Stamp(plain); } catch (e) { console.log(e.name + ': ' + e.message); }
''', cli=cli)


def test_class_heritage_new_target_and_accessors(run, workdir):
    """CATCHES: broken `extends null`, subclassing of Array/Error/Map/Promise/Function (species,
    instanceof, internal slots), wrong new.target in plain functions/arrows/Reflect.construct,
    `accessor` fields, class name bindings, static `this`, private accessors and super property
    assignment."""
    check_script(run, workdir, G, "class_heritage", r'''
class N extends null { constructor() { return Object.create(N.prototype); } m() { return 'm'; } }
const n = new N(); console.log(n.m(), Object.getPrototypeOf(N.prototype), typeof N.prototype.toString);
class N2 extends null {}
try { new N2(); } catch (e) { console.log(e.name + ': ' + e.message); }
class MyArr extends Array { sum() { return this.reduce((a, b) => a + b, 0); } }
const ma = MyArr.from([1, 2, 3]); ma.push(4);
console.log(ma.sum(), ma.length, ma instanceof MyArr, Array.isArray(ma), ma.map(x => x * 2) instanceof MyArr, ma.filter(x => x > 2).sum());
ma.length = 1; ma[5] = 9; console.log(ma.length, JSON.stringify(ma));
class MyErr extends Error { constructor(m) { super(m, { cause: 'c' }); this.name = 'MyErr'; } }
const me = new MyErr('oops'); console.log(String(me), me.cause, me instanceof Error, Object.prototype.toString.call(me), me.hasOwnProperty('message'));
class MyMap extends Map { get(k) { return super.get(k) ?? 'dflt'; } }
const mm = new MyMap([[1, 'one']]); console.log(mm.get(1), mm.get(2), mm.size);
try { Map.prototype.get.call({}, 1); } catch (e) { console.log(e.name + ': ' + e.message); }
class MyPromise extends Promise {}
console.log(MyPromise.resolve(1) instanceof MyPromise, MyPromise.resolve(1).then(() => {}) instanceof MyPromise);
class MyFn extends Function {} const mf = new MyFn('return 7'); console.log(mf(), mf instanceof MyFn);
function F() { return new.target === undefined ? 'call' : 'new:' + new.target.name; }
console.log(F(), new F() instanceof F, Reflect.construct(F, [], class Other {}) instanceof Object);
function G() { this.t = new.target; } class H extends G {} console.log(new H().t === H);
function viaArrow() { return (() => new.target)(); } console.log(new viaArrow() === viaArrow, viaArrow());
class Acc { accessor value = 3; static accessor sv = 's'; }
const acc = new Acc(); console.log(acc.value, (acc.value = 9, acc.value), Acc.sv, Object.getOwnPropertyNames(Acc.prototype).join(), Object.keys(acc).length);
const exprCls = class Inner { who() { return Inner.name; } }; console.log(exprCls.name, new exprCls().who(), typeof Inner);
const anon = class {}; console.log(anon.name, (class {}).name === '', class { static name = 'custom' }.name);
class Getters { static #count = 0; static inc() { return ++Getters.#count; } get #g() { return 'pg'; } set #g(v) { this.log = v; } run() { this.#g = this.#g + '!'; return this.log; } }
console.log(Getters.inc(), Getters.inc(), new Getters().run());
class StaticThis { static a = 1; static b = this.a + 1; static c = () => this.b; } console.log(StaticThis.b, StaticThis.c());
class FieldOrder { a = this.constructor.name; ['b'] = 2; static [Symbol.for('s')] = 3; } console.log(JSON.stringify(new FieldOrder()), FieldOrder[Symbol.for('s')]);
const objWithSuper = { __proto__: { hi() { return 'proto hi'; } }, hi() { return 'own+' + super.hi(); } }; console.log(objWithSuper.hi());
class SetSuper { set p(v) { this._p = v; } } class SS2 extends SetSuper { setIt() { super.p = 5; super.q = 6; return this._p + ':' + this.q + ':' + this.hasOwnProperty('q'); } } console.log(new SS2().setIt());
class StaticInherit { static who() { return this.name; } } class SI2 extends StaticInherit {} console.log(SI2.who(), Object.getPrototypeOf(SI2.prototype) === StaticInherit.prototype);
class ReadonlyMethods { m() {} } console.log(delete ReadonlyMethods.prototype.m, typeof ReadonlyMethods.prototype.m, Object.keys(ReadonlyMethods.prototype).length);
''')


def test_getters_setters_on_prototype_chain(run, workdir):
    """CATCHES: assignments that create own properties instead of calling an inherited setter, writes
    through an inherited getter-only or read-only property that succeed, wrong `this` in inherited
    accessors (including primitives), self-replacing lazy getters, and defineProperty conversions."""
    check_script(run, workdir, G, "accessors_prototype_chain", r'''
const log = [];
const proto = { _v: 'proto', get v() { log.push('get on ' + this.name); return this._v; }, set v(x) { log.push('set on ' + this.name); this._v = x; }, get onlyGet() { return 'og'; }, set onlySet(x) { this._os = x; } };
const child = Object.create(proto); child.name = 'child';
console.log(child.v); child.v = 'child value'; console.log(child.v, proto._v, Object.keys(child).join(), child.hasOwnProperty('v'));
child.onlyGet = 'ignored in sloppy'; console.log(child.onlyGet, child.hasOwnProperty('onlyGet'), child.onlySet, child._os);
child.onlySet = 'via setter'; console.log(child._os);
const roProto = Object.defineProperty({}, 'ro', { value: 'proto ro', writable: false }); const roChild = Object.create(roProto); roChild.ro = 'shadow attempt'; console.log(roChild.ro, roChild.hasOwnProperty('ro'));
Object.defineProperty(roChild, 'ro', { value: 'defined own', writable: true }); console.log(roChild.ro);
class A { get x() { return 'A.x'; } set x(v) { log.push('A setter ' + v); } } class B extends A { get x() { return 'B.x+' + super.x; } } const b = new B(); b.x = 1; console.log(b.x, Object.getOwnPropertyNames(b).length);
const counterObj = { count: 0, get next() { return ++this.count; } }; console.log(counterObj.next, counterObj.next, counterObj.count);
const dp = {}; Object.defineProperty(dp, 'computed', { get() { return 'dp getter'; }, enumerable: false, configurable: true }); console.log(dp.computed, JSON.stringify(dp), Object.keys(dp).length);
Object.defineProperty(dp, 'computed', { value: 'now data' }); console.log(dp.computed, typeof Object.getOwnPropertyDescriptor(dp, 'computed').get);
const lazy = { get expensive() { log.push('compute once'); Object.defineProperty(this, 'expensive', { value: 42 }); return this.expensive; } }; console.log(lazy.expensive, lazy.expensive);
const getterThrows = { get bad() { throw new Error('getter threw'); } }; try { getterThrows.bad; } catch (e) { console.log(e.message); }
Object.defineProperty(Number.prototype, 'double', { get() { return this * 2; }, configurable: true }); console.log((21).double, typeof (function () { return this; }).call(1));
Object.defineProperty(String.prototype, 'selfType', { get() { 'use strict'; return typeof this; }, configurable: true }); console.log('s'.selfType);
delete Number.prototype.double; delete String.prototype.selfType; console.log((1).double, 's'.selfType);
const symAcc = { get [Symbol.toStringTag]() { return 'Custom'; } }; console.log(String(symAcc), Object.prototype.toString.call(symAcc));
const setterOnly = { set s(v) { log.push('setter only got ' + v); } }; console.log(setterOnly.s, (setterOnly.s = 'assigned'));
console.log(log.join('\n'));
''')


@pytest.mark.parametrize("cli", TIERS)
def test_generators(run, workdir, cli):
    """CATCHES: generator next/return/throw semantics (values sent into yield, finally blocks that
    yield during return(), throw before start), yield* delegation to generators/arrays/strings/Maps
    with return values, forwarding throw/return to delegates (and closing ones without throw), and
    re-entrancy/receiver errors; all tiers must agree."""
    check_script(run, workdir, G, "generators", r'''
const show = (r) => JSON.stringify(r);
function* g1() { try { const x = yield 1; console.log('got', x); yield x * 2; } finally { console.log('cleanup'); yield 'from finally'; } return 'end'; }
let it = g1();
console.log(show(it.next('ignored')), show(it.next(5)), show(it.return(99)), show(it.next()), show(it.next()));
it = g1(); it.next();
try { console.log(show(it.throw(new Error('boom')))); console.log(show(it.next())); } catch (e) { console.log('caught', e.message); }
it = g1(); console.log(show(it.return(1)), show(it.next()));
try { g1().throw(new Error('early')); } catch (e) { console.log('early throw:', e.message); }
function* inner() { const r = yield 'i1'; console.log('inner got', r); try { yield 'i2'; } finally { console.log('inner finally'); } return 'inner-ret'; }
function* outer() { const v = yield* inner(); console.log('delegate result', v); yield* [10, 20]; yield* 'ab'; return yield* new Map([[1, 2]]); }
it = outer(); const out = []; let r;
while (!(r = it.next('sent')).done) out.push(JSON.stringify(r.value));
console.log(out.join(' '), show(r));
it = outer(); it.next(); it.next(); console.log(show(it.return('early')));
const throwable = { [Symbol.iterator]() { return { next: () => ({ value: 1, done: false }), throw: (e) => ({ value: 'handled ' + e, done: true }), return: () => { console.log('return called'); return {}; } }; } };
function* delegThrow() { const res = yield* throwable; yield 'after ' + res; }
it = delegThrow(); it.next(); console.log(show(it.throw('E')), show(it.next()));
const noThrow = { [Symbol.iterator]() { return { next: () => ({ value: 1, done: false }), return: () => { console.log('closing on missing throw'); return {}; } }; } };
it = (function* () { yield* noThrow; })(); it.next(); try { it.throw('X'); } catch (e) { console.log(e.name + ': ' + e.message); }
const genObj = { *[Symbol.iterator]() { yield 1; yield 2; } }; console.log([...genObj].join(), Array.from(genObj, x => x * 3).join());
function* fib() { let [a, b] = [0, 1]; for (;;) { yield a; [a, b] = [b, a + b]; } }
const first = []; for (const f of fib()) { if (f > 50) break; first.push(f); } console.log(first.join());
const gf = function* () {}; console.log(Object.prototype.toString.call(gf()), typeof gf().next, gf()[Symbol.iterator]() instanceof gf);
it = g1(); it.next(); try { it.next.call({}); } catch (e) { console.log(e.name + ': ' + e.message); }
function* running() { try { it2.next(); } catch (e) { yield e.name; } } const it2 = running(); console.log(it2.next().value);
function* argsGen(a, b = a + 1) { yield arguments.length; yield b; } console.log([...argsGen(1)].join());
function* yieldPrecedence() { const a = yield 1 + 1; const b = yield; const c = [yield 'in array', yield 'second']; return [a, b, c]; }
it = yieldPrecedence(); const vals = [it.next().value]; for (const v of ['A', 'B', 'C', 'D']) { const res = it.next(v); vals.push(JSON.stringify(res.value)); } console.log(vals.join(' '));
class GenMethods { *[Symbol.iterator]() { yield* this.items; } constructor() { this.items = ['m1', 'm2']; } static *range(n) { for (let i = 0; i < n; i++) yield i; } }
console.log([...new GenMethods()].join(), [...GenMethods.range(4)].join(), typeof GenMethods.range(1).return);
function* nestedFinally() { try { try { yield 'a'; } finally { console.log('inner f'); } } finally { console.log('outer f'); } }
it = nestedFinally(); it.next(); console.log(show(it.return('R')));
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_async_await_ordering(run, workdir, cli):
    """CATCHES: wrong microtask ordering of await (1 tick for native promises, extra ticks for thenables
    and for returning a promise from an async function), async functions running asynchronously before
    their first await, rejected awaits not catchable with try/catch/finally, and queueMicrotask
    interleaving; all tiers must agree."""
    check_script(run, workdir, G, "async_ordering", r'''
const log = [];
async function a1() { log.push('a1 start'); await null; log.push('a1 after await'); return 'a1'; }
async function a2() { log.push('a2 start'); try { await Promise.reject(new Error('rej')); } catch (e) { log.push('a2 caught ' + e.message); } finally { log.push('a2 finally'); } throw new TypeError('a2 fails'); }
const thenable = { then(res) { log.push('thenable.then called'); res('thenable value'); } };
async function a3() { const v = await thenable; log.push('a3 got ' + v); return thenable; }
log.push('sync start');
Promise.resolve().then(() => log.push('micro 1')).then(() => log.push('micro 2')).then(() => log.push('micro 3'));
a1().then(v => log.push('a1 resolved ' + v));
a2().catch(e => log.push('a2 rejected ' + e.name));
a3().then(v => log.push('a3 resolved ' + v));
queueMicrotask(() => log.push('queueMicrotask'));
(async () => { log.push('arrow await order'); for (let i = 0; i < 3; i++) { await i; log.push('loop ' + i); } })();
log.push('sync end');
setTimeout(() => {
  console.log(log.join('\n'));
  const p = (async () => 1)();
  console.log(p instanceof Promise, Object.prototype.toString.call(p), typeof (async function(){}).constructor);
  async function retPromise() { return Promise.resolve('inner'); }
  async function awaitPromise() { return await Promise.resolve('awaited'); }
  const order = [];
  retPromise().then(v => order.push('retPromise ' + v));
  awaitPromise().then(v => order.push('awaitPromise ' + v));
  Promise.resolve().then(() => order.push('t1')).then(() => order.push('t2')).then(() => order.push('t3')).then(() => order.push('t4'));
  setTimeout(() => {
    console.log(order.join(' '));
    const rejections = [];
    (async () => { try { await (async () => { throw new RangeError('deep'); })(); } catch (e) { rejections.push('caught ' + e.name); } })();
    (async () => { await undefined; return Promise.reject('plain'); })().catch(v => rejections.push('rejected with ' + v));
    Promise.all([1, Promise.resolve(2), (async () => 3)()]).then(v => rejections.push('all ' + v.join()));
    setTimeout(() => console.log(rejections.join(' | ')), 0);
  }, 0);
}, 0);
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_async_generators_and_for_await(run, workdir, cli):
    """CATCHES: async generators that do not await yielded promises, mishandle yield* to sync/async
    iterables, do not queue concurrent next() calls, run finally on return()/break incorrectly, or
    for-await that does not use Symbol.asyncIterator / async-from-sync wrapping / return() on break;
    all tiers must agree."""
    check_script(run, workdir, G, "async_generators", r'''
const log = [];
async function* agen() { try { yield 1; const x = yield Promise.resolve(2); log.push('agen got ' + x); yield* [3, Promise.resolve(4)]; yield* inner(); } finally { log.push('agen finally'); } }
async function* inner() { yield 'i1'; await null; yield 'i2'; return 'iret'; }
(async () => {
  for await (const v of agen()) log.push('for-await ' + v);
  for await (const v of [Promise.resolve('p1'), 'plain', Promise.resolve('p2')]) log.push('sync-iter ' + v);
  const it = agen();
  log.push(JSON.stringify(await it.next()));
  log.push(JSON.stringify(await it.next()));
  log.push(JSON.stringify(await it.next('sent')));
  log.push(JSON.stringify(await it.return('R')));
  log.push(JSON.stringify(await it.next()));
  const it2 = agen();
  const [r1, r2, r3] = await Promise.all([it2.next(), it2.next(), it2.next()]);
  log.push('queued ' + [r1, r2, r3].map(r => r.value).join());
  try { const it3 = agen(); await it3.next(); await it3.throw(new Error('thrown in')); } catch (e) { log.push('throw result ' + e.message); }
  for await (const v of agen()) { log.push('break at ' + v); break; }
  const custom = { [Symbol.asyncIterator]() { let i = 0; return { next() { return Promise.resolve({ value: i++, done: i > 2 }); }, return() { log.push('custom return'); return Promise.resolve({ done: true }); } }; } };
  for await (const v of custom) log.push('custom ' + v);
  for await (const v of custom) { if (v === 0) break; }
  log.push(Object.prototype.toString.call(agen()), typeof agen.prototype, Object.getPrototypeOf(agen).constructor.name);
  try { for await (const x of 5) {} } catch (e) { log.push(e.name + ': ' + e.message); }
  const rejecting = async function* () { yield Promise.reject(new Error('yield-rejected')); };
  try { for await (const x of rejecting()) {} } catch (e) { log.push('caught ' + e.message); }
  const early = agen(); log.push(JSON.stringify(await early.return('before start')), JSON.stringify(await early.next()));
  const syncWithReturn = { [Symbol.iterator]() { return { i: 0, next() { return { value: this.i++, done: false }; }, return() { log.push('sync iterator closed'); return { done: true }; } }; } };
  for await (const v of syncWithReturn) { if (v === 1) break; }
  let label = 0; outer: for await (const a of agen()) { for await (const b of inner()) { label++; continue outer; } }
  log.push('labelled continue across for-await ' + label);
  console.log(log.join('\n'));
})();
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_iterator_closing_protocol(run, workdir, cli):
    """CATCHES: iterators not closed (return() not called) on break/continue-outer/throw/return out of
    for-of or after destructuring stops early, closed when they completed normally, a non-object
    return() result not rejected, or an error from return() masking the body's throw."""
    check_script(run, workdir, G, "iterator_closing", r'''
const log = [];
function tracked(name, values) {
  return { [Symbol.iterator]() { let i = 0; return {
    next() { log.push(name + '.next'); return i < values.length ? { value: values[i++], done: false } : { value: undefined, done: true }; },
    return(v) { log.push(name + '.return'); return { done: true }; } }; } };
}
for (const x of tracked('A', [1, 2, 3])) { if (x === 2) break; }
log.push('--');
outer: for (const x of tracked('B', [1, 2])) { for (const y of tracked('C', [1, 2])) { continue outer; } }
log.push('--');
try { for (const x of tracked('D', [1])) throw new Error('t'); } catch (e) { log.push('caught'); }
log.push('--');
(function () { for (const x of tracked('E', [1, 2])) return x; })();
log.push('--');
const [p, q] = tracked('F', [1, 2, 3]); log.push(`p=${p} q=${q}`);
const [r, ...rest] = tracked('G', [1, 2, 3]); log.push(`rest=${rest}`);
const [] = tracked('H', [1]);
const [s, , t] = tracked('I', [1, 2]); log.push(`s=${s} t=${t}`);
log.push('--');
try { const [u = (() => { throw new Error('default threw'); })()] = tracked('J', [undefined, 5]); } catch (e) { log.push(e.message); }
log.push('--');
for (const x of tracked('K', [1, 2])) { }
log.push('--');
const m = new Map(tracked('L', [['k', 'v']])); log.push('map size ' + m.size);
try { new Map(tracked('M', [1])); } catch (e) { log.push(e.name + ': ' + e.message); }
Array.from(tracked('N', [1])); Promise.all(tracked('O', [])); log.push('--');
function* genWithFinally() { try { yield 1; yield 2; } finally { log.push('gen finally'); } }
for (const v of genWithFinally()) break;
const [g1] = genWithFinally(); log.push('g1=' + g1);
const badReturn = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { return 5; } }; } };
try { for (const x of badReturn) break; } catch (e) { log.push(e.name + ': ' + e.message); }
const throwingReturn = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { throw new Error('from return'); } }; } };
try { for (const x of throwingReturn) throw new Error('body error'); } catch (e) { log.push('wins: ' + e.message); }
try { for (const x of throwingReturn) break; } catch (e) { log.push('break: ' + e.message); }
const nonObjNext = { [Symbol.iterator]() { return { next() { return 3; } }; } };
try { for (const x of nonObjNext) {} } catch (e) { log.push(e.name + ': ' + e.message); }
const nextThrows = { [Symbol.iterator]() { return { next() { throw new Error('next threw'); }, return() { log.push('must not close'); } }; } };
try { for (const x of nextThrows) {} } catch (e) { log.push(e.message); }
const getterDone = { [Symbol.iterator]() { let n = 0; return { next() { return { get done() { log.push('done read'); return n++ > 0; }, get value() { log.push('value read'); return 'v'; } }; } }; } };
for (const v of getterDone) log.push('body ' + v);
console.log(log.join('\n'));
''', cli=cli)


def test_labels_switch_and_loops(run, workdir):
    """CATCHES: switch using loose equality or not falling through, default clause in the middle handled
    wrongly, case expressions evaluated past the match, labelled break/continue targeting the wrong
    statement (multiple labels, labelled blocks/ifs), and for-in enumeration order/mutation/prototype
    rules and member-expression loop targets."""
    check_script(run, workdir, G, "labels_switch", r'''
const out = [];
function sw(x) { const r = []; switch (x) { case 1: r.push('one'); case 2: r.push('two'); break; default: r.push('default'); case 3: r.push('three'); break; case '1': r.push('string one'); } return r.join('+'); }
console.log([1, 2, 3, 4, '1', '2'].map(sw).join(' | '));
function swEval(x) { const log = []; const t = (v) => (log.push('test ' + v), v); switch (x) { case t(1): log.push('hit 1'); break; case t(2): log.push('hit 2'); break; default: log.push('dflt'); } return log.join(','); }
console.log(swEval(2), '/', swEval(9));
function swStrict(x) { switch (x) { case NaN: return 'nan'; case 0: return 'zero'; case null: return 'null'; case undefined: return 'undef'; } return 'none'; }
console.log(swStrict(NaN), swStrict(-0), swStrict(null), swStrict(), swStrict(false));
function swScope(x) { switch (x) { case 'a': { let v = 'block a'; return v; } case 'b': let v = 'shared b'; return v; } } console.log(swScope('a'), swScope('b'));
function swEmpty(x) { switch (x) {} switch (x) { default: } return 'empty ok'; } console.log(swEmpty(1));
outer: for (let i = 0; i < 3; i++) { inner: for (let j = 0; j < 3; j++) { if (j === 1) continue outer; if (i === 2) break outer; out.push(`${i}${j}`); } }
console.log(out.join(' '));
block: { out.push('in block'); if (out.length) break block; out.push('never'); } console.log(out[out.length - 1]);
let n = 0; loop1: while (true) { n++; do { if (n > 3) break loop1; continue loop1; } while (false); } console.log('n', n);
const labelsSeen = []; a: b: c: for (let i = 0; i < 2; i++) { labelsSeen.push(i); continue b; } console.log(labelsSeen.join());
lbl: if (true) { labelsSeen.push('if-label'); break lbl; } console.log(labelsSeen.join());
sw: switch (1) { case 1: for (;;) { break sw; } } console.log('broke out of switch from loop');
function forInMutation() { const o = { a: 1, b: 2, c: 3 }; const seen = []; for (const k in o) { seen.push(k); if (k === 'a') { delete o.b; o.d = 4; } } return seen.join(); } console.log(forInMutation());
function forInProto() { const p = { inherited: 1, shadow: 'p' }; const o = Object.create(p); o.own = 2; o.shadow = 'o'; Object.defineProperty(o, 'hidden', { value: 1, enumerable: false }); const r = []; for (const k in o) r.push(k); return r.join(); } console.log(forInProto());
for (const k in 'ab') out.push('str key ' + k); for (const k in null) out.push('never'); for (const k in undefined) out.push('never'); for (const k in [7, , 9]) out.push('arr key ' + k); console.log(out.slice(-4).join(', '));
const ordered = { b: 1, 10: 1, a: 1, 2: 1, [Symbol('s')]: 1 }; const ok = []; for (const k in ordered) ok.push(k); console.log(ok.join());
let doCount = 0; do { doCount++; if (doCount === 2) continue; } while (doCount < 4); console.log('do count', doCount);
let forCount = 0; for (;;) { if (++forCount >= 5) break; } console.log('for count', forCount);
var fi; for (fi in { x: 1 }); console.log('for-in var leftover', fi);
const obj = {}; for (obj.prop of [1, 2]); for (obj['k' + 1] in { z: 1 }); console.log(obj.prop, obj.k1);
for (var vi = 0, vj = 10; vi < vj; vi += 3, vj -= 3); console.log(vi, vj);
''')


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_try_catch_finally_control_flow(run, workdir, cli):
    """CATCHES: finally blocks that do not run on return/break/continue, return/throw in finally not
    overriding the pending completion, the returned value being re-read after finally mutates it,
    optional catch binding, catch-parameter scoping, and generator finally on return()."""
    check_script(run, workdir, G, "try_finally", r'''
const log = [];
function f1() { try { return 'try'; } finally { log.push('finally runs after return expr evaluated'); } }
function f2() { try { return 'try'; } finally { return 'finally overrides'; } }
function f3() { try { throw new Error('lost'); } finally { return 'finally swallows throw'; } }
function f4() { for (const i of [1, 2, 3]) { try { if (i === 2) break; } finally { log.push('finally on ' + i); } } return 'loop done'; }
function f5() { let i = 0; while (i < 3) { try { i++; continue; } finally { log.push('continue finally ' + i); } } return i; }
function f6() { try { try { throw new Error('inner'); } finally { log.push('inner finally'); } } catch (e) { return 'outer caught ' + e.message; } }
function f7() { try { throw 1; } catch (e) { try { throw 2; } catch (e2) { return [e, e2].join(); } } }
function f8() { let x = 'initial'; try { return x; } finally { x = 'mutated'; } }
function f9() { try { throw new Error('a'); } catch { return 'optional catch binding'; } }
function f10() { outer: try { break outer; } finally { log.push('break-out-of-try finally'); } return 'after labelled try'; }
function f11() { try { return (log.push('return expr'), 'r'); } finally { log.push('finally after expr'); } }
function f12() { const e = 'outer e'; try { throw 'x'; } catch (e) { var e2 = e; } return e + '/' + e2; }
function f13() { try { throw new Error('rethrow me'); } catch (e) { throw e; } finally { log.push('finally before rethrow propagates'); } }
function f14() { let r = []; for (let i = 0; i < 2; i++) { try { if (i === 0) continue; r.push('body ' + i); } finally { r.push('fin ' + i); } } return r.join(); }
function* f15() { try { yield 1; yield 2; } finally { log.push('generator finally on return()'); } }
function f16() { try { return 'try'; } finally { try { throw 'inner'; } catch (e) { log.push('caught in finally ' + e); } } }
function f17() { for (;;) { try { return 'returned from loop'; } finally { break; } } return 'finally break wins'; }
function f18() { let n = 0; do { try { n++; if (n < 3) continue; } finally { log.push('do-while finally ' + n); } } while (n < 3); return n; }
for (const f of [f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f14, f16, f17, f18]) log.push(f.name + ' => ' + f());
try { f13(); } catch (e) { log.push('f13 threw ' + e.message); }
const g = f15(); g.next(); log.push(JSON.stringify(g.return('done')));
try { null.x; } catch (e) { log.push((e instanceof TypeError) + ' ' + e.constructor.name); }
try { try { throw new Error('first'); } finally { throw new Error('second'); } } catch (e) { log.push('finally throw wins: ' + e.message); }
const catchScope = (() => { try { throw 'v'; } catch (err) { return typeof err; } })(); log.push(catchScope, typeof err);
try { throw undefined; } catch (e) { log.push('caught undefined: ' + e); }
try { throw { toString() { return 'custom thrown object'; } }; } catch (e) { log.push(String(e)); }
console.log(log.join('\n'));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_optional_chaining_and_logical_assignment(run, workdir, cli):
    """CATCHES: optional chains that do not short-circuit the whole chain (including calls, computed
    keys and arguments), lose `this` for optional calls, treat parenthesised chains as continuing,
    ?? treating 0/'' as nullish, and logical assignment (&&=, ||=, ??=) that evaluates the RHS or calls
    the setter when it must not, or evaluates the key twice. Note: the reference does NOT short-circuit
    an optional call on a missing super property (`super.missing?.()` throws a TypeError)."""
    check_script(run, workdir, G, "optional_chaining", r'''
const log = [];
const o = { a: { b: { c: 'deep' }, fn() { return this === o.a ? 'this ok' : 'this lost'; } }, arr: [1, 2], nul: null, zero: 0, empty: '' };
const side = (v) => { log.push('side ' + v); return v; };
console.log(o?.a?.b?.c, o.x?.y.z.w, o.nul?.[side('never')], o.a?.['b']?.c, o.arr?.[1], o.a.fn?.(), o.a?.fn(), o.missing?.(side('never arg')), o.a.nope?.());
console.log((o?.a).b.c, o.nul?.b ?? 'fallback', o.zero ?? 'nn', o.zero || 'or', o.empty ?? 'nn', o.nul ?? side('rhs evaluated'));
console.log(null?.x, undefined?.[0], (void 0)?.(), typeof null?.x, delete o?.zero, 'zero' in o, delete null?.x);
try { o.nul.x; } catch (e) { console.log(e.name + ': ' + e.message); }
try { o.a.nope(); } catch (e) { console.log(e.name + ': ' + e.message); }
try { (o?.nul).x; } catch (e) { console.log(e.name + ': ' + e.message); }
const counter = { n: 0, get v() { log.push('get v'); return this.n; }, set v(x) { log.push('set v=' + x); this.n = x; } };
counter.v ||= side(5); counter.v &&= side(6); counter.v ??= side(7); counter.v ||= side(8);
console.log(counter.n, log.join(', ')); log.length = 0;
let la = null, lb = 0, lc = 'set'; la ??= 'was null'; lb ||= 'was falsy'; lc &&= 'was truthy'; console.log(la, lb, lc);
const frozen = Object.freeze({ x: 1 }); frozen.x ||= 2; console.log('no write needed', frozen.x);
let anon; anon ??= function () {}; let arrowName; arrowName ||= () => {}; console.log(anon.name, arrowName.name);
try { undeclaredLogical ||= 1; } catch (e) { console.log(e.name + ': ' + e.message); }
const cnt = { k: 0 }; const keyFn = () => { log.push('key evaluated'); return 'k'; }; cnt[keyFn()] ??= 1; cnt[keyFn()] ||= 2; console.log(cnt.k, log.join(','));
class Priv { #p = null; static t(o) { o.#p ??= 'priv set'; o.#p ||= 'never'; return o.#p; } } console.log(Priv.t(new Priv()));
const chainCall = { m() { return { n() { return 'chained'; } }; } }; console.log(chainCall.m?.().n?.(), chainCall.x?.().n(), chainCall?.m().n());
const fnThis = { v: 'fnThis', get() { return this?.v; } }; console.log(fnThis.get?.(), (fnThis.get)?.(), (0, fnThis.get)?.());
console.log(o?.a.b?.c?.length, o.arr?.length, o.arr?.map?.(x => x * 2).join(), 'str'?.length, 5?.toFixed(1));
const constTarget = (() => { const c = 1; try { c ||= 2; return 'no throw, c=' + c; } catch (e) { return e.name; } })();
const constTarget2 = (() => { const c = 0; try { c ||= 2; return 'no throw'; } catch (e) { return e.name + ': ' + e.message; } })();
console.log(constTarget, constTarget2);
class SuperOpt extends Object { m() { return super.missing?.x ?? 'super optional member'; } n() { try { return super.missing?.(); } catch (e) { return e.name + ': ' + e.message; } } }
console.log(new SuperOpt().m(), new SuperOpt().n());
''', cli=cli)


def test_typeof_delete_in_instanceof(run, workdir):
    """CATCHES: instanceof ignoring Symbol.hasInstance, bound functions, prototype reassignment or the
    non-object/non-callable errors; `in` with proxies/private names/primitives; delete return values
    for vars, non-configurable props, array elements and arguments; typeof of every value kind; and
    ==/Object.is/SameValueZero corner cases."""
    check_script(run, workdir, G, "typeof_delete_in", r'''
class Even { static [Symbol.hasInstance](n) { return n % 2 === 0; } }
console.log(2 instanceof Even, 3 instanceof Even, [] instanceof Array, [] instanceof Object, Object.create(null) instanceof Object);
function F() {} const f = new F(); F.prototype = {}; console.log(f instanceof F, new F() instanceof F);
const bound = F.bind(null); console.log(new F() instanceof bound, Object.getPrototypeOf(new bound()) === F.prototype);
try { ({}) instanceof {}; } catch (e) { console.log(e.name + ': ' + e.message); }
try { ({}) instanceof (() => {}); } catch (e) { console.log(e.name + ': ' + e.message); }
const badProto = function () {}; badProto.prototype = 5; try { ({}) instanceof badProto; } catch (e) { console.log(e.name + ': ' + e.message); }
console.log(1 instanceof Number, new Number(1) instanceof Number, Object(1n) instanceof BigInt, Symbol() instanceof Symbol);
const p = new Proxy({}, { has(t, k) { return k === 'virtual'; } }); console.log('virtual' in p, 'other' in p, Symbol.iterator in [], 'length' in 'abc'.split(''));
try { 'x' in 5; } catch (e) { console.log(e.name + ': ' + e.message); }
class WithPriv { #x; static has(o) { try { return #x in o; } catch (e) { return e.name; } } } console.log(WithPriv.has(new WithPriv()), WithPriv.has({}), WithPriv.has(1));
const obj = { a: 1, b: 2 }; Object.defineProperty(obj, 'fixed', { value: 1, configurable: false });
console.log(delete obj.a, 'a' in obj, delete obj.nonexistent, delete obj.fixed, 'fixed' in obj, delete obj['b'], Object.keys(obj).join());
const arr = [1, 2, 3]; console.log(delete arr[1], arr.length, 1 in arr, JSON.stringify(arr), delete arr.length);
var fvar = 1; console.log(delete fvar, typeof fvar); let lv = 1; console.log(delete lv); console.log(delete 5, delete 'str'.length, delete [].x, delete Math.PI, delete (0, obj).zz);
function delArgs(a) { return [delete arguments[0], arguments[0], a].join(); } console.log(delArgs('arg'));
console.log(typeof typeof x, typeof NaN, typeof new String(''), typeof String(''), typeof Object(Symbol()), typeof new Proxy(function () {}, {}), typeof new Proxy({}, {}), typeof document, typeof globalThis);
console.log(void 0 === undefined, void function () { return 1; }(), [void 0].length);
console.log((1, 2), [1, 2, 3].map((x) => (x, x * 2)).join(), eval('1, 2, 3'));
console.log(1 == 1n, '1' == 1n, 1n == true, NaN == NaN, null == false, undefined == null, {} == '[object Object]', Symbol.for('a') == Symbol.for('a'), new String('a') == 'a', new String('a') == new String('a'));
console.log(Object.is(NaN, NaN), Object.is(0, -0), [NaN].includes(NaN), [NaN].indexOf(NaN), [-0].includes(0), new Set([0, -0, NaN, NaN]).size);
console.log(0.1 + 0.2 === 0.3, 9007199254740992 === 9007199254740993, 1 / 3, 2 ** 53, -(2 ** 31) | 0, 4294967296 >>> 0, 5 % 0, -5 % Infinity, Infinity - Infinity, 0 / 0);
''')


def test_with_statement_and_sloppy_globals(run):
    """CATCHES: `with` scoping (object properties shadowing outer bindings, Symbol.unscopables,
    var declarations escaping to the function scope, closures created inside `with`, the exact Proxy
    has/get trap sequence), sloppy `this` boxing, implicit globals, global var non-deletability and
    Annex B block-function hoisting in a classic (non-module) script read from stdin."""
    src = r'''
var x = 'global x';
const o = { x: 'obj x', y: 'obj y', [Symbol.unscopables]: { y: true } };
var y = 'global y';
with (o) { console.log(x, y); x = 'assigned'; var z = 'z via var'; }
console.log(o.x, x, z, 'z' in o);
with ([1, 2, 3]) { console.log(length, join('-'), typeof values, typeof includes); }
function makeGetter(obj) { with (obj) { return function () { return typeof q === 'undefined' ? 'none' : q; }; } }
const scope = {}; const get = makeGetter(scope); console.log(get()); scope.q = 'late'; console.log(get());
const proxyLog = [];
const p = new Proxy({ a: 1 }, { has(t, k) { proxyLog.push('has ' + String(k)); return k in t; }, get(t, k) { proxyLog.push('get ' + String(k)); return t[k]; } });
with (p) { a; }
console.log(proxyLog.join(', '));
with ({ f() { return this === undefined ? 'undef' : (this.tag || 'other'); }, tag: 'withobj' }) console.log(f());
with ({ shadowed: 'from with' }) { let shadowed = 'block let'; console.log(shadowed); }
function sloppy() { return this === globalThis; } function strict() { 'use strict'; return this; }
console.log(sloppy(), strict(), sloppy.call(5), typeof (function () { return this; }).call(5), (function () { 'use strict'; return typeof this; }).call(5));
implicitGlobal = 42; console.log(globalThis.implicitGlobal, delete globalThis.implicitGlobal, typeof implicitGlobal);
var declaredGlobal = 1; console.log(delete globalThis.declaredGlobal, Object.getOwnPropertyDescriptor(globalThis, 'declaredGlobal').configurable, this === globalThis);
function globalFn() {} console.log(typeof globalThis.globalFn, Object.getOwnPropertyDescriptor(globalThis, 'globalFn').enumerable);
let notOnGlobal = 1; const alsoNot = 2; class NorThis {} console.log('notOnGlobal' in globalThis, 'alsoNot' in globalThis, 'NorThis' in globalThis);
console.log(0.1 * 3, 010 + 1, '\08'.length, typeof arguments);
if (true) function annexB() { return 'annexB'; }
console.log(typeof annexB, annexB());
{ function blockFn() { return 'block'; } } console.log(blockFn());
console.log(typeof laterFn); { function laterFn() {} } console.log(typeof laterFn);
console.log('strict block fn not visible:', (function () { 'use strict'; { function inner() {} } return typeof inner; })());
label: function labelled() { return 'lab'; } console.log(labelled());
var dup = 1; var dup = 2; function dupf() { return 1; } function dupf() { return 2; } console.log(dup, dupf());
console.log((function (a, a) { return a; })(1, 2));
try { eval('let declaredGlobal = 1'); console.log('eval let ok'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { (0, eval)('let notOnGlobal = 2'); } catch (e) { console.log(e.name + ': ' + e.message); }
'''
    assert_result(run([], input=src), G / "with_sloppy.golden")


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_strict_mode_semantics(run, workdir, cli):
    """CATCHES: strict code silently ignoring failed writes (read-only, getter-only, non-extensible,
    frozen arrays, primitives), deletes of non-configurable properties, undeclared assignment, boxing
    `this`, exposing arguments.callee/caller, leaking eval vars, or not honouring strictness of
    functions created by `Function` from strict code."""
    check_script(run, workdir, G, "strict_mode", r'''
'use strict';
const out = [];
const attempt = (label, fn) => { try { const r = fn(); out.push(label + ': ok ' + r); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } };
attempt('undeclared assign', () => { undeclaredStrictVar = 1; });
attempt('write non-writable', () => { const o = {}; Object.defineProperty(o, 'ro', { value: 1 }); o.ro = 2; });
attempt('write getter-only', () => { const o = { get g() { return 1; } }; o.g = 2; });
attempt('add to non-extensible', () => { const o = Object.preventExtensions({}); o.nw = 1; });
attempt('add to sealed', () => { Object.seal({ a: 1 }).b = 1; });
attempt('delete non-configurable', () => { delete Object.freeze({ a: 1 }).a; });
attempt('write frozen array elem', () => { Object.freeze([1])[0] = 2; });
attempt('write string index', () => { const s = 'abc'; s[0] = 'z'; });
attempt('write string length', () => { 'abc'.length = 1; });
attempt('set prop on primitive', () => { (5).x = 1; });
attempt('this in function', () => (function () { return this; })());
attempt('this via call primitive', () => typeof (function () { return this; }).call(5));
attempt('arguments.callee', () => (function () { return arguments.callee; })());
attempt('fn.caller', () => (function f() { return f.caller; })());
attempt('eval var scope', () => { eval('var inEval = 1'); return typeof inEval; });
attempt('arguments unmapped', () => (function (a) { a = 2; return arguments[0]; })(1));
attempt('NaN assign', () => { NaN = 1; });
attempt('undefined assign', () => { undefined = 1; });
attempt('Infinity assign', () => { globalThis.Infinity = 0; });
attempt('octal in eval', () => eval('010'));
attempt('with in eval', () => eval('with ({}) {}'));
attempt('duplicate params via Function', () => Function('a', 'a', '"use strict"; return a')(1, 2));
attempt('sloppy Function inside strict', () => Function('a', 'a', 'return a')(1, 2));
attempt('sloppy fn this', () => Function('return this === globalThis')());
attempt('array length shrink frozen', () => { const a = Object.freeze([1, 2]); a.length = 0; });
attempt('defineProperty on frozen', () => Object.defineProperty(Object.freeze({}), 'x', { value: 1 }));
attempt('Reflect.set result', () => Reflect.set(Object.freeze({ a: 1 }), 'a', 2));
attempt('class body strict', () => { class S { m() { return this; } } return (0, new S().m)(); });
attempt('setter on proto chain', () => { const proto = Object.freeze({ inherited: 1 }); const o = Object.create(proto); o.inherited = 2; });
attempt('non-writable via super', () => { const base = {}; Object.defineProperty(base, 'k', { value: 1 }); const obj = { __proto__: base, m() { super.k = 2; } }; obj.m(); });
console.log(out.join('\n'));
''', cli=cli)


def test_direct_and_indirect_eval(run):
    """CATCHES: indirect eval ((0,eval), aliased eval, globalThis.eval) seeing local scope, direct eval
    not seeing locals/this/arguments/closures, var declarations from sloppy direct eval not leaking (or
    leaking from strict eval / let), eval of non-strings, `new Function` closing over locals instead
    of the global scope, and eval-specific SyntaxErrors such as var/let conflicts."""
    src = r'''
var gv = 'global';
function direct() { var gv = 'local'; return eval('gv'); }
function indirect() { var gv = 'local'; return (0, eval)('typeof gv === "string" ? gv : "none"'); }
function indirect2() { var gv = 'local'; const e = eval; return e('gv'); }
console.log(direct(), indirect(), indirect2(), globalThis.eval('1+1'));
function varLeak() { eval('var leaked = 1'); return leaked; } console.log(varLeak(), typeof leaked);
function strictEval() { 'use strict'; eval('var notLeaked = 1'); return typeof notLeaked; } console.log(strictEval());
function letNoLeak() { eval('let l = 1; const c = 2'); return typeof l + typeof c; } console.log(letNoLeak());
function evalThis() { return eval('this'); } console.log(evalThis.call('str') == 'str', typeof evalThis.call(7));
function evalArgs(a) { return eval('arguments.length + a'); } console.log(evalArgs(10, 20));
function evalClosure() { const k = 5; return eval('() => k * 2')(); } console.log(evalClosure());
function evalFnDecl() { eval('function declared() { return "decl" }'); return declared(); } console.log(evalFnDecl());
function evalAssign() { let local = 1; eval('local = 2'); return local; } console.log(evalAssign());
(0, eval)('var indirectGlobal = "made global"'); console.log(globalThis.indirectGlobal, Object.getOwnPropertyDescriptor(globalThis, 'indirectGlobal').configurable);
eval('var directTopLevel = 1'); console.log(delete globalThis.directTopLevel, typeof directTopLevel);
console.log(eval(42), eval({ a: 1 }).a, eval(), eval('"use strict"; 5'), eval(new String('1+1')) instanceof String);
const nf = new Function('a', 'b = 2', '...c', 'return [a, b, c.length, typeof gv]');
console.log(JSON.stringify(nf(1, undefined, 3, 4)));
function makeNF() { const local = 1; return new Function('return typeof local'); } console.log(makeNF()());
console.log(new Function('a,b', 'c', 'return a+b+c')(1, 2, 3), Function('return this')() === globalThis, Function()() === undefined);
try { new Function('a', 'return a +'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { new Function('a)', '{', 'return 1'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { new Function('/*', '*/){'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { eval('let x = 1; let x = 2;'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { eval('}'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { eval('a b'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { eval('throw new RangeError("from eval")'); } catch (e) { console.log(e.name + ': ' + e.message, e instanceof RangeError); }
let shadow = 'outer'; function evalLet() { eval('var shadow = "inner"'); return shadow; } console.log(evalLet(), shadow);
function evalConflict() { let c = 1; { try { eval('var c = 2'); } catch (e) { return e.name + ': ' + e.message; } } } console.log(evalConflict());
function evalNested() { const v = 'outer'; return eval('(function () { const v = "inner"; return eval("v"); })()') + '/' + eval('v'); } console.log(evalNested());
function evalInArrow() { return (() => eval('this.tag'))(); } console.log(evalInArrow.call({ tag: 'arrow this' }));
class EvalClass { #p = 'private'; read() { return eval('this.#p'); } } console.log(new EvalClass().read());
function evalNewTarget() { return eval('new.target') === evalNewTarget; } console.log(new evalNewTarget() instanceof evalNewTarget, evalNewTarget());
try { eval('new.target'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { (0, eval)('super.x'); } catch (e) { console.log(e.name + ': ' + e.message); }
'''
    assert_result(run([], input=src), G / "direct_indirect_eval.golden")


def test_completion_values_via_eval(run, workdir):
    """CATCHES: wrong statement completion values: empty statements/declarations not keeping the
    previous value, loops/if/switch/try/finally/labelled/with/block completions (UpdateEmpty rules),
    break/continue carrying values, and eval returning the last value-producing statement."""
    check_script(run, workdir, G, "completion_values", r'''
const cases = ['1; 2; 3', '', 'var q = 5', 'if (true) { "then" } else { "else" }', 'for (var i = 0; i < 3; i++) i * 10',
  'do { 7; break; } while (false)', 'try { "t" } finally { "f" }', 'try { throw 1 } catch (e) { "c" }',
  'switch (1) { case 1: "one"; case 2: "two"; break; }', 'switch (3) { case 1: "one"; }', '{}', '({})', 'L: { "in label"; break L; }',
  'while (false);', '1; if (false) 2;', '3; var z = 4;', '"before"; function f(){}', '"before"; class K {}', '"before"; let l = 1;',
  '1; try { 2 } finally { 3 }', '4; do { 5; continue; } while (false)', '6; with ({}) 7', '8; x: 9', '9; for (const k in {}) 10',
  '10; for (const k of [1, 2]) { k; }', '11; for (const k of [1, 2]) { if (k == 2) break; "body" + k; }',
  '12; while (true) { 13; break; }', '14; if (true) {}', '15; try {} catch {}', '16; switch (0) {}', '17; ;', '18; { }',
  'var n = 0; while (n < 3) { n++; if (n == 2) continue; "w" + n; }', '"x"; try { "y"; throw 0; } catch { } finally { "z" }',
  'outer: for (const a of [1]) { for (const b of [2]) { "ab" + a + b; continue outer; } }', '1; do { } while (false)',
  'typeof undefinedThing', 'void 1', '"s" + 1', '[1, 2]', 'null', 'x => x', '20; try { 21 } catch (e) { 22 } finally { }',
  '23; label: { 24; { 25; break label; } }', '26; if (false) ; else 27', '28; for (;false;) 29', '(function () { return 30; })()'];
for (const c of cases) {
  const v = eval(c);
  console.log(JSON.stringify(c).padEnd(60), typeof v === 'function' ? 'function' : JSON.stringify(v) ?? 'undefined');
}
''')


def test_repl_completion_values(run):
    """CATCHES: a piped REPL that does not print each input's completion value (loops, try/finally,
    switch fallthrough, labelled blocks, compound assignment, declarations as undefined), loses
    bindings/classes/private names between lines, or stops after a thrown error."""
    src = ('for (let i = 0; i < 3; i++) i * 2\n'
           'try { "t" } finally { "f" }\n'
           'switch (2) { case 1: "a"; case 2: "b"; case 3: "c" }\n'
           'let o = { a: 1 }\n'
           'o.a += 5\n'
           'const f = (x) => x ** 2\n'
           'f(9)\n'
           'typeof nothing\n'
           '[..."ab"]\n'
           '`t${1+1}`\n'
           'class A { #p = 1; static get(o) { return o.#p } }\n'
           'A.get(new A)\n'
           'x = 1; y = 2\n'
           'void 0\n'
           '1, 2, 3\n'
           'label: { 5; break label }\n'
           'function* g() { yield 1; yield 2 }\n'
           '[...g()]\n'
           'throw new TypeError("mid-session")\n'
           'o.a\n'
           'if (o.a > 3) { "big" } else { "small" }\n'
           'var v = 10\n'
           'v\n'
           'do { v-- } while (v > 7)\n'
           'null ?? "nullish"\n'
           '0 || 0n\n'
           'eval("var fromEval = 3"); fromEval\n')
    assert_result(run(["repl"], input=src), G / "repl_completion.golden")


@pytest.mark.parametrize("cli,name", [
    pytest.param(["--tier=interp"], "do_while_interp", id="interp"),
    pytest.param(["--tier=bytecode"], "do_while_bytecode", id="bytecode"),
])
def test_do_while_condition_evaluation(run, workdir, cli, name):
    """CATCHES: loop tests/updates evaluated the wrong number of times. Pins a reference quirk: the
    tree-walking tier (--tier=interp) evaluates a do-while condition TWICE between iterations whose
    body completed normally (once after `continue`), while the bytecode tier evaluates it once;
    while/for loops evaluate test and update exactly once per iteration on both tiers."""
    check_script(run, workdir, G, name, r'''
const log = [];
const t = (tag, v) => { log.push(tag); return v; };
let i = 0; while (t('w' + i, i < 2)) i++;
for (let j = 0; t('f' + j, j < 2); t('u' + j, j++));
let k = 0; do { log.push('body' + k); } while (t('d' + k, ++k < 3));
let m = 0; do { log.push('cb' + m); if (m < 5) { m++; continue; } } while (t('dc' + m, m < 2));
let n = 0; do { log.push('once'); } while (t('false', false));
console.log(log.join(' '), '| k =', k);
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_super_references_direct_eval_and_tail_calls(run, workdir, cli):
    """CATCHES: computed super access (`super[k]`, calls, assignment, compound/update which must read
    from the home object's prototype but write to `this`), super in arrows/static methods, `delete
    super.x`, super/new.target inside direct eval (allowed only where the enclosing code allows it),
    eval-declared deletable vars, and tail-position calls/tagged templates losing values or `this`."""
    check_script(run, workdir, G, "super_eval_tail", r'''
const log = [];
class B { get g() { return 'B.g'; } m(x) { return 'B.m' + x; } static s() { return 'B.s'; } }
B.prototype.n = 100; B.prototype.c = 10;
class D extends B {
  test() { const k = 'g'; const keys = []; return [super[k], super['m'](1), super[(keys.push('key'), 'm')](2), keys.join()].join('|'); }
  setComputed() { super['dyn' + 1] = 'set via super[]'; return [this.dyn1, Object.keys(this).join(), B.prototype.dyn1].join('|'); }
  static st() { return super['s']() + '/' + super.s.name; }
  compound() { super.n += 5; const first = this.n; super['n'] *= 2; return [first, this.n, B.prototype.n].join(); }
  arrow() { return (() => super.m('A'))(); }
  inc() { super.c++; ++super['c']; return [this.c, B.prototype.c].join(); }
}
const d = new D(); console.log(d.test(), d.setComputed(), D.st(), d.compound(), d.arrow(), d.inc());
const objSuper = { __proto__: { v: 'proto v' }, get() { return super['v']; }, del() { try { delete super.v; } catch (e) { return e.name + ': ' + e.message; } } };
console.log(objSuper.get(), objSuper.del(), Object.getPrototypeOf(objSuper).v);
const tag = (s, ...v) => s.raw.join('_') + v.join('');
function tailTagged(n) { return tag`a${n}b`; } function tailCall(n) { return n <= 0 ? 'done' : tailCall(n - 1); }
function tailCond(n) { return n ? tag`yes${n}` : tag`no`; } function tailComma(n) { return (log.push(n), tailCall(n)); }
function tailLogical(n) { return n && tailCall(n); } function tailMember(o) { return o.m(); }
function tailApply(f, ...a) { return f.apply(null, a); } function tailNew(C) { return new C(); }
console.log(tailTagged(1), tailCall(50), tailCond(1), tailCond(0), tailComma(3), tailLogical(0), tailMember({ m() { return this === undefined ? 'undef' : 'obj this'; } }), tailApply(Math.max, 1, 9, 3), tailNew(Map) instanceof Map);
class E extends B { constructor() { super(); this.viaEval = eval('super.m("E")'); } m2() { return eval('super.g'); } arrowEval() { return (() => eval('super.g'))(); } nested() { return function () { try { return eval('super.g'); } catch (e) { return e.name + ': ' + e.message; } }(); } }
const e = new E(); console.log(e.viaEval, e.m2(), e.arrowEval(), e.nested());
class F extends B { constructor() { eval('super()'); this.ok = 'super() via eval'; } } console.log(new F().ok);
class G2 extends B { constructor() { super(); try { eval('super()'); } catch (e) { this.err = e.name + ': ' + e.message; } } } console.log(new G2().err);
class H2 extends B { constructor() { super(); this.fnEval = (function () { try { eval('super()'); } catch (e) { return e.name + ': ' + e.message; } })(); } } console.log(new H2().fnEval);
function NT() { return eval('new.target') === NT; } console.log(new NT() instanceof NT, NT());
function delEval() { eval('var evalVar = 1'); const before = typeof evalVar; const res = delete evalVar; return [before, res, typeof evalVar].join(); } console.log(delEval());
function delEvalFn() { eval('function evalFn() {}'); return [delete evalFn, typeof evalFn].join(); } console.log(delEvalFn());
const wobj = { inWith: 1 }; with (wobj) { console.log(delete inWith, 'inWith' in wobj); }
const wo = { n: 1 }; with (wo) { n += 10; n++; n **= 2; var declaredInWith = n; } console.log(wo.n, declaredInWith);
console.log(log.join());
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_operator_coercion_slow_paths(run, workdir, cli):
    """CATCHES: arithmetic, bitwise, shift, exponent and relational operators that skip valueOf on
    objects, coerce operands out of order, mishandle string-number conversions (whitespace, hex,
    exponent, empty), NaN/Infinity/negative-zero corner cases, or BigInt values produced by
    ToPrimitive (allowed with BigInts, TypeError with Numbers)."""
    check_script(run, workdir, G, "operator_slow_paths", r'''
const log = [];
const val = (n) => ({ valueOf() { log.push('valueOf ' + n); return n; } });
console.log(val(7) - val(2), val(3) * val(4), val(9) / val(3), val(7) % val(4), val(2) ** val(3), val(5) & val(3), val(5) | val(2), val(6) ^ val(3), val(1) << val(4), val(-16) >> val(2), val(-1) >>> val(28), ~val(5), -val(3), +val(4));
console.log(log.join(',')); log.length = 0;
console.log(val(1) < val(2), val(2) <= val(2), val(3) > val(4), val(3) >= val(3), '10' < '9', '10' < 9, 'a' < 1, null < 1, undefined < 1, [1] < [2], ({}) < ({}), NaN <= NaN, null <= null);
console.log(log.join(','));
const bigVal = { valueOf() { return 10n; } }; console.log(String(bigVal + 1n), String(bigVal * 2n), String(-bigVal), String(bigVal ** 2n), bigVal > 5n, bigVal == 10n, typeof (bigVal + 1n), String(bigVal % 3n), String(bigVal >> 1n));
try { bigVal + 1; } catch (err) { console.log(err.name + ': ' + err.message); }
try { 1n - val(1); } catch (err) { console.log(err.name + ': ' + err.message); }
try { 2n ** -1n; } catch (err) { console.log(err.name + ': ' + err.message); }
try { +bigVal; } catch (err) { console.log(err.name + ': ' + err.message); }
console.log(1 ** NaN, NaN ** 0, (-1) ** Infinity, 2 ** 1024, (-8) % 3, 8 % -3, -0 % 5, 0.5 % 0.25, 2 ** 0.5 === Math.SQRT2, Object.is(-0 * 1, -0), Object.is(0 * -1, -0), 1 / (-0 + 0));
console.log('3' * '4', '10' / '4', '7' % '4', '2' ** '3', '5' - '2', true + true, null + 1, undefined + 1, [] * 2, [3] * [4], '0x10' * 1, ' \n12\t' * 1, '1e2' - 0, '' - 1, '0b101' * 1, '0o17' - 0, '-0x10' * 1, '1_000' * 1, 'Infinity' * 1, '-Infinity' / 2);
console.log(1 + '2' + 3, 1 + 2 + '3', '3' + 4 * 5, [1, 2] + [3], {} + [], 1 + null, 1 + undefined, 'x' + null, true + '1', 1 + true, Symbol.iterator.description + 1);
console.log(5 >> 33, 5 << 32, -5 >>> 0, 2 ** 31 | 0, 2 ** 32 + 5 | 0, 1e21 | 0, NaN | 0, Infinity >> 0, -0 | 0, 0.9999 | 0, -2147483649 | 0);
console.log(0 == -0, 0 === -0, null == 0, null >= 0, undefined == 0, NaN == false, '' == false, ' ' == 0, '\n' == 0, '1' == true, '2' == true);
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_async_generator_delegation(run, workdir, cli):
    """CATCHES: async-generator `yield*` that does not forward next/throw/return to the inner async
    iterator (with the received values), closes an iterator lacking `throw`, treats a non-done return()
    result as completion, wraps sync iterators/generators wrongly, rejects on non-object results, or
    mishandles awaits/rejections inside async generator bodies; all tiers must agree."""
    check_script(run, workdir, G, "async_generator_delegation", r'''
const log = [];
const mkIter = (name, opts = {}) => ({
  [Symbol.asyncIterator]() { let i = 0; return {
    next(v) { log.push(`${name}.next(${v})`); return Promise.resolve({ value: name + i++, done: i > 3 }); },
    ...(opts.noThrow ? {} : { throw(e) { log.push(`${name}.throw(${e})`); return Promise.resolve({ value: 'caught ' + e, done: opts.throwDone ?? false }); } }),
    ...(opts.noReturn ? {} : { return(v) { log.push(`${name}.return(${v})`); return Promise.resolve({ value: 'ret ' + v, done: opts.returnDone ?? true }); } }),
  }; } });
async function* deleg(src) { const r = yield* src; log.push('delegate result ' + r); return 'outer done'; }
(async () => {
  let it = deleg(mkIter('A'));
  log.push(JSON.stringify(await it.next('first')), JSON.stringify(await it.next('second')), JSON.stringify(await it.throw('E1')), JSON.stringify(await it.return('R1')), JSON.stringify(await it.next()));
  log.push('--');
  it = deleg(mkIter('B', { throwDone: true })); await it.next(); log.push(JSON.stringify(await it.throw('E2')));
  log.push('--');
  it = deleg(mkIter('C', { noThrow: true })); await it.next(); try { await it.throw('E3'); } catch (e) { log.push(e.name + ': ' + e.message); }
  log.push('--');
  it = deleg(mkIter('D', { noReturn: true })); await it.next(); log.push(JSON.stringify(await it.return('R2')));
  log.push('--');
  it = deleg(mkIter('E', { returnDone: false })); await it.next(); log.push(JSON.stringify(await it.return('R3')));
  log.push('--');
  it = deleg(mkIter('F')); const all = []; for await (const v of it) all.push(v); log.push('drained ' + all.join());
  it = deleg([Promise.resolve('sync1'), 'sync2']); log.push(JSON.stringify(await it.next()), JSON.stringify(await it.next()), JSON.stringify(await it.next()));
  it = deleg((function* () { try { yield 's1'; } finally { log.push('sync gen finally'); } })()); await it.next(); log.push(JSON.stringify(await it.return('R4')));
  it = deleg((function* () { try { yield 's1'; } catch (e) { log.push('sync gen caught ' + e); yield 'after catch'; } })()); await it.next(); log.push(JSON.stringify(await it.throw('E4')));
  const badNext = { [Symbol.asyncIterator]() { return { next() { return 5; } }; } };
  try { for await (const x of badNext) ; } catch (e) { log.push(e.name + ': ' + e.message); }
  it = deleg(badNext); try { await it.next(); } catch (e) { log.push('deleg ' + e.name + ': ' + e.message); }
  async function* awaitInside() { const v = await new Promise(r => setTimeout(() => r('timer value'), 1)); yield v; yield await Promise.resolve('x'); }
  for await (const v of awaitInside()) log.push(v);
  async function* returnAwait() { try { return await Promise.reject(new Error('rejected return')); } catch (e) { yield 'caught ' + e.message; } }
  for await (const v of returnAwait()) log.push(v);
  async function* yieldRejectCaught() { try { yield Promise.reject(new Error('yielded rejection')); } catch (e) { yield 'inside caught ' + e.message; } }
  for await (const v of yieldRejectCaught()) log.push(v);
  async function* thrower() { yield 1; throw new TypeError('async gen threw'); }
  const th = thrower(); log.push(JSON.stringify(await th.next())); try { await th.next(); } catch (e) { log.push(e.name + ': ' + e.message); } log.push(JSON.stringify(await th.next()));
  console.log(log.join('\n'));
})();
''', cli=cli)


def test_cyclic_garbage_collection_keeps_live_objects(run, workdir):
    """CATCHES: a cycle collector that frees objects still reachable from arrays, WeakMap/Map entries,
    closures or a suspended generator frame while lots of cyclic garbage (well past the collection
    threshold) is being reclaimed, or that corrupts their properties, so later reads return wrong
    values or crash."""
    check_script(run, workdir, G, "gc_cycles", r'''
const keep = [], closures = [];
const wm = new WeakMap(), map = new Map();
function* gen() { const local = { n: 0, tag: 'gen local' }; local.self = local; while (true) { local.n++; yield local; } }
const g = gen(); g.next();
for (let i = 0; i < 70000; i++) {
  const a = { i }, b = { a }; a.b = b;
  if (i % 10000 === 0) { keep.push(a); wm.set(a, 'meta' + i); map.set('k' + i, b); closures.push(() => a.i + a.b.a.i); g.next(); }
}
console.log(keep.length, keep.every(o => o.b.a === o), wm.get(keep[3]), keep.map(o => o.i).join(), map.get('k60000').a.i);
console.log(closures.map(f => f()).join(), JSON.stringify(g.next().value, (k, v) => k === 'self' ? '[cycle]' : v));
''')


def test_proper_tail_calls_on_tree_walker(run, workdir):
    """CATCHES: the tree-walking tier not performing proper tail calls in strict functions (deep
    tail recursion through ?:, ||, ??, comma, tagged templates, methods and mutual recursion must not
    exhaust the stack), losing `this` across a tail call, or crashing instead of throwing RangeError
    when a non-tail (native `.call`) recursion is too deep. Note: the reference's bytecode/JIT tiers do
    NOT do PTC (they throw RangeError for the same programs), so this is pinned on --tier=interp."""
    check_script(run, workdir, G, "proper_tail_calls", r'''
'use strict';
function loop(n, acc) { return n === 0 ? acc : loop(n - 1, acc + 1); }
function even(n) { return n === 0 ? true : odd(n - 1); } function odd(n) { return n === 0 ? false : even(n - 1); }
const tag = (s, n) => n === 0 ? 'tag done' : viaTag(n - 1);
function viaTag(n) { return tag`x${n}`; }
function viaLogical(n) { return n <= 0 || viaLogical(n - 1); }
function viaComma(n) { return (n, n <= 0 ? 'comma done' : viaComma(n - 1)); }
function viaNullish(n) { return (n <= 0 ? 'nullish done' : null) ?? viaNullish(n - 1); }
const obj = { count(n) { return n === 0 ? this.tag : this.count(n - 1); }, tag: 'method this kept' };
function viaCall(n) { return n === 0 ? 'call done' : viaCall.call(null, n - 1); }
for (const [name, f] of [['loop', () => loop(20000, 0)], ['mutual', () => even(20001)], ['tag', () => viaTag(20000)], ['logical', () => viaLogical(20000)],
                         ['comma', () => viaComma(20000)], ['nullish', () => viaNullish(20000)], ['method', () => obj.count(20000)], ['call', () => viaCall(20000)]]) {
  try { console.log(name, f()); } catch (e) { console.log(name, e.name + ': ' + e.message); }
}
''', cli=["--tier=interp"])


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_in_delete_instanceof_on_exotic_objects(run, workdir, cli):
    """CATCHES: `in`/`delete`/`instanceof` ignoring exotic semantics: revoked proxies and invariant
    checks of has/deleteProperty traps, typed-array and String-wrapper own indices, optional `delete`,
    strict-mode delete failures, proxy getPrototypeOf in instanceof, TDZ on compound/update/logical/
    destructuring assignment, and await of thenables whose `then` throws, resolves twice or is not
    callable."""
    check_script(run, workdir, G, "exotic_operands", r'''
const out = [];
const tryIt = (label, f) => { try { out.push(label + ': ' + String(f())); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } };
const { proxy: revoked, revoke } = Proxy.revocable({}, {}); revoke();
tryIt('in revoked proxy', () => 'x' in revoked);
const sealedTarget = Object.defineProperty({}, 'fixed', { value: 1, configurable: false });
tryIt('has trap hides non-configurable', () => 'fixed' in new Proxy(sealedTarget, { has() { return false; } }));
tryIt('has trap hides on non-extensible', () => 'a' in new Proxy(Object.preventExtensions({ a: 1 }), { has() { return false; } }));
tryIt('has without trap forwards', () => 'a' in new Proxy({ a: 1 }, {}));
tryIt('in typed array', () => [0 in new Uint8Array(2), 2 in new Uint8Array(2), '-0' in new Uint8Array(2), '1.5' in new Uint8Array(2), 'length' in new Uint8Array(2)].join());
tryIt('in String wrapper', () => [0 in new String('ab'), 2 in new String('ab'), 'length' in new String('ab')].join());
tryIt('in arguments', () => (function () { return [0 in arguments, 1 in arguments]; })('x').join());
tryIt('delete optional index', () => { const o = { k: 1 }, n = null; return [delete o?.['k'], 'k' in o, delete n?.['k']].join(); });
tryIt('delete typed array index sloppy', () => { const ta = new Uint8Array(2); return [delete ta[0], delete ta[5], delete ta['1.5']].join(); });
tryIt('delete typed array index strict', () => { 'use strict'; const ta = new Uint8Array(2); return delete ta[0]; });
tryIt('delete string index sloppy', () => [delete 'abc'[0], delete 'abc'[5], delete 'abc'.length].join());
tryIt('delete string index strict', () => { 'use strict'; return delete 'abc'[1]; });
tryIt('delete string length strict', () => { 'use strict'; return delete 'abc'.length; });
tryIt('delete proxy trap', () => { const log = []; const p = new Proxy({ a: 1 }, { deleteProperty(t, k) { log.push('trap ' + k); return delete t[k]; } }); return [delete p.a, log.join()].join(' '); });
tryIt('delete proxy trap false strict', () => { 'use strict'; const p = new Proxy({ a: 1 }, { deleteProperty() { return false; } }); return delete p.a; });
tryIt('delete proxy trap false sloppy', () => { const p = new Proxy({ a: 1 }, { deleteProperty() { return false; } }); return delete p.a; });
tryIt('delete proxy lies about non-configurable', () => { const p = new Proxy(sealedTarget, { deleteProperty() { return true; } }); return delete p.fixed; });
tryIt('instanceof via proxy getPrototypeOf', () => { const p = new Proxy({}, { getPrototypeOf() { return Array.prototype; } }); return p instanceof Array; });
tryIt('instanceof bound chain', () => { class K {} const b1 = K.bind(null), b2 = b1.bind(null); return new K() instanceof b2; });
tryIt('TDZ compound', () => { x += 1; let x = 0; });
tryIt('TDZ update', () => { y++; let y = 0; });
tryIt('TDZ logical assign', () => { z ??= 1; let z; });
tryIt('TDZ destructuring assign', () => { [w] = [1]; let w; });
(async () => {
  const throwingThen = { then() { throw new Error('then threw'); } };
  try { await throwingThen; } catch (e) { out.push('await throwing then: ' + e.message); }
  const getterThen = { get then() { throw new Error('then getter threw'); } };
  try { await getterThen; } catch (e) { out.push('await throwing then getter: ' + e.message); }
  const lateResolve = { then(res, rej) { res('first'); res('second'); rej(new Error('ignored')); } };
  out.push('await thenable resolves once: ' + await lateResolve);
  const nonCallableThen = { then: 5 }; out.push('await non-callable then: ' + ((await nonCallableThen) === nonCallableThen));
  const rejectsLater = { then(res, rej) { setTimeout(() => rej(new RangeError('later')), 1); } };
  try { await rejectsLater; } catch (e) { out.push('await async-rejecting thenable: ' + e.name); }
  console.log(out.join('\n'));
})();
''', cli=cli)


def test_global_declaration_instantiation(run):
    """CATCHES: global/eval declaration instantiation errors: functions declared over non-configurable
    globals (NaN, undefined, accessors) not throwing, var/function colliding with global lexical
    bindings not raising SyntaxError, eval-created globals not being deletable while script vars are,
    global let/const appearing on globalThis, and declarations on a non-extensible global object."""
    src = r'''
let topLet = 1; var alsoVar = 1; const topConst = 'c';
const show = (label, f) => { try { console.log(label + ': ' + String(f())); } catch (e) { console.log(label + ': ' + e.name + ': ' + e.message); } };
try { eval('function NaN() {}'); console.log('direct global eval function NaN: no error'); } catch (e) { console.log('direct global eval function NaN: ' + e.name + ': ' + e.message); }
try { eval('var undefined = 1'); console.log('direct global eval var undefined:', typeof undefined); } catch (e) { console.log('direct global eval var undefined: ' + e.name + ': ' + e.message); }
show('indirect eval function undefined', () => (0, eval)('function undefined() {}'));
show('eval function over configurable', () => { globalThis.cfg = 1; (0, eval)('function cfg() { return "replaced"; }'); return typeof cfg + ' enumerable=' + Object.getOwnPropertyDescriptor(globalThis, 'cfg').enumerable; });
show('eval function over writable enumerable non-configurable', () => { Object.defineProperty(globalThis, 'wen', { value: 1, writable: true, enumerable: true, configurable: false }); (0, eval)('function wen() {}'); return typeof wen + ' configurable=' + Object.getOwnPropertyDescriptor(globalThis, 'wen').configurable; });
show('eval function over non-configurable accessor', () => { Object.defineProperty(globalThis, 'acc', { get() { return 1; }, configurable: false }); (0, eval)('function acc() {}'); });
show('eval let is local to the eval', () => { (0, eval)('let lexA = 1'); return (0, eval)('typeof lexA'); });
show('global let then eval var', () => (0, eval)('var topLet = 2'));
show('global const then eval function', () => (0, eval)('function topConst() {}'));
show('eval var then eval let', () => { (0, eval)('var fromEval = 1'); return (0, eval)('let fromEval = 2; fromEval'); });
show('eval var is deletable global', () => { (0, eval)('var evalGlobal = 1'); return [Object.getOwnPropertyDescriptor(globalThis, 'evalGlobal').configurable, delete globalThis.evalGlobal, typeof evalGlobal].join(); });
show('script var is not deletable', () => [Object.getOwnPropertyDescriptor(globalThis, 'alsoVar').configurable, delete globalThis.alsoVar].join());
show('global lexical not on globalThis', () => ['topLet' in globalThis, globalThis.topConst, typeof topConst].join());
show('assign to global const', () => { topConst = 'x'; });
show('function declaration in eval sees caller let', () => (0, eval)('function readsTop() { return topLet; } readsTop()'));
Object.preventExtensions(globalThis);
show('eval var on non-extensible global', () => (0, eval)('var brandNew = 1'));
show('eval function on non-extensible global', () => (0, eval)('function brandNewFn() {}'));
show('existing var still assignable', () => { (0, eval)('var alsoVar = 3'); return alsoVar; });
show('sloppy implicit global on non-extensible', () => { implicitNew = 1; return typeof implicitNew; });
'''
    assert_result(run([], input=src), G / "global_declarations.golden")


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_property_access_through_proxies_and_primitives(run, workdir, cli):
    """CATCHES: [[Get]]/[[Set]]/[[HasProperty]] that skip a Proxy on the prototype chain (or pass the
    wrong receiver), proxy trap validation (non-callable traps, revoked proxies, get/set invariants,
    construct returning a primitive, set returning false in strict code), setters/getter-only
    properties reached from primitive receivers, Reflect.set receiver semantics, and the legacy
    fn.caller / fn.arguments of sloppy functions."""
    check_script(run, workdir, G, "proxies_primitives_legacy", r'''
const out = [];
const tryIt = (label, f) => { try { out.push(label + ': ' + String(f())); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } };
function inner() { return inner.caller === outer ? 'caller is outer' : typeof inner.caller; }
function outer() { return inner(); }
tryIt('fn.caller', () => outer());
function withArgs(a, b) { return withArgs.arguments.length + ':' + withArgs.arguments[0]; }
tryIt('fn.arguments', () => withArgs('x', 'y', 'z'));
tryIt('fn.arguments when not running', () => withArgs.arguments);
tryIt('arrow caller', () => { const a = () => 1; return a.caller; });
tryIt('class method caller', () => { class K { m() {} } return new K().m.caller; });
tryIt('hasOwn caller', () => [Object.hasOwn(function () {}, 'caller'), Object.hasOwn(function () {}, 'arguments'), 'caller' in Function.prototype].join());
const protoProxy = new Proxy({}, { get(t, k, r) { return typeof k === 'string' ? 'trap:' + k : undefined; }, set(t, k, v, r) { out.push('set trap ' + String(k) + '=' + v + ' recvIsChild=' + (r === child)); return true; }, has(t, k) { return k === 'virtual'; } });
const child = Object.create(protoProxy); child.own = 'own';
tryIt('get via proxy proto', () => [child.own, child.anything].join());
tryIt('set via proxy proto', () => { child.fresh = 1; return Object.hasOwn(child, 'fresh'); });
tryIt('in via proxy proto', () => ['virtual' in child, 'other' in child, 'own' in child].join());
const revokedP = Proxy.revocable({}, {}); revokedP.revoke();
tryIt('get revoked', () => revokedP.proxy.x);
tryIt('set revoked', () => { revokedP.proxy.x = 1; });
tryIt('call revoked', () => { const r = Proxy.revocable(function () {}, {}); r.revoke(); return r.proxy(); });
tryIt('get trap not callable', () => new Proxy({}, { get: 5 }).x);
tryIt('set trap not callable', () => { new Proxy({}, { set: 5 }).x = 1; });
tryIt('apply trap', () => new Proxy(function (a) { return a; }, { apply(t, thisArg, args) { return 'applied ' + args.join(); } })(1, 2));
tryIt('apply trap not callable', () => new Proxy(function () {}, { apply: 1 })());
tryIt('construct trap', () => new (new Proxy(function () {}, { construct(t, args, nt) { return { made: args[0] }; } }))('m').made);
tryIt('construct trap returns primitive', () => new (new Proxy(function () {}, { construct() { return 1; } }))());
tryIt('get invariant', () => { const t = Object.defineProperty({}, 'c', { value: 1, writable: false, configurable: false }); return new Proxy(t, { get() { return 2; } }).c; });
tryIt('set invariant', () => { 'use strict'; const t = Object.defineProperty({}, 'c', { value: 1, writable: false, configurable: false }); new Proxy(t, { set() { return true; } }).c = 2; });
tryIt('set trap false strict', () => { 'use strict'; new Proxy({}, { set() { return false; } }).x = 1; });
tryIt('set trap false sloppy', () => { new Proxy({}, { set() { return false; } }).x = 1; return 'silently ignored'; });
Object.defineProperty(Number.prototype, 'boxedSet', { set(v) { out.push('setter this type ' + typeof this + ' v=' + v); }, configurable: true });
tryIt('setter on primitive proto', () => { (5).boxedSet = 7; return 'done'; });
Object.defineProperty(Boolean.prototype, 'strictSet', { set(v) { 'use strict'; out.push('strict setter this ' + typeof this); }, configurable: true });
tryIt('strict setter primitive this', () => { true.strictSet = 1; return 'done'; });
Object.defineProperty(String.prototype, 'getterOnly', { get() { return 1; }, configurable: true });
tryIt('assign getter-only on primitive sloppy', () => { 'x'.getterOnly = 2; return 'ignored'; });
tryIt('assign getter-only on primitive strict', () => { 'use strict'; 'x'.getterOnly = 2; });
tryIt('assign symbol prop on primitive strict', () => { 'use strict'; Symbol().x = 1; });
tryIt('Reflect.set receiver', () => { const target = { set p(v) { this.got = v; } }; const recv = {}; return [Reflect.set(target, 'p', 9, recv), recv.got, target.got].join(); });
tryIt('Reflect.set data to receiver', () => { const recv = {}; return [Reflect.set({ q: 1 }, 'q', 2, recv), recv.q].join(); });
tryIt('Reflect.set non-writable receiver prop', () => { const recv = Object.defineProperty({}, 'q', { value: 1, writable: false, configurable: true }); return Reflect.set({}, 'q', 2, recv); });
tryIt('Reflect.set accessor receiver prop', () => { const recv = { get q() { return 1; } }; return Reflect.set({}, 'q', 2, recv); });
tryIt('Reflect.set primitive receiver', () => Reflect.set({}, 'q', 2, 5));
delete Number.prototype.boxedSet; delete Boolean.prototype.strictSet; delete String.prototype.getterOnly;
console.log(out.join('\n'));
''', cli=cli)


def test_repl_redeclaration_across_inputs(run):
    """CATCHES: a REPL whose inputs are not separate scripts sharing one global scope: let/const/class
    redeclared on a later line must throw SyntaxError (and var/function colliding with an earlier
    lexical binding), restricted globals (NaN, undefined, non-configurable properties) must reject
    function declarations with TypeError, while var/function re-declaration is allowed."""
    src = ('let x = 1\nvar x = 2\nconst y = 1\nfunction y() {}\nvar z = 1\nlet z = 2\nfunction NaN() {}\n'
           'var undefined = 5\nundefined\nlet undefined = 1\nclass C {}\nclass C {}\nx = 10\nx\ny = 2\n'
           'function f() { return "f1" }\nfunction f() { return "f2" }\nf()\nvar f = 3\nf\n'
           'Object.defineProperty(globalThis, "frozenG", { value: 1, writable: false, enumerable: false, configurable: false }) === globalThis\n'
           'function frozenG() {}\nvar frozenG\nfrozenG\nlet globalThis = 1\ntypeof globalThis\n')
    assert_result(run(["repl"], input=src), G / "repl_redeclaration.golden")
