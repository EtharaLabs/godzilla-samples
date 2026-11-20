"""Core object model built-ins: Object statics and Object.prototype, property ordering, integrity
levels, Function.prototype (call/apply/bind/toString), Reflect, Proxy (traps observed by built-ins,
invariant checks, revocation), Symbol (well-knowns, registry, ToPrimitive) and JSON."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

# Deterministic formatter shared by the scripts below: shows -0, holes, symbols, bigints and
# own keys in [[OwnPropertyKeys]] order without depending on util.inspect.
PRELUDE = r'''
const fmt = (v, d = 0) => {
  if (typeof v === 'string') return JSON.stringify(v);
  if (typeof v === 'number') return Object.is(v, -0) ? '-0' : String(v);
  if (typeof v === 'bigint') return v + 'n';
  if (typeof v === 'symbol') return v.toString();
  if (typeof v === 'function') return '[Function ' + (v.name || '<anon>') + ']';
  if (v === null || typeof v !== 'object') return String(v);
  if (v instanceof Error) return '[' + v.name + ': ' + v.message + ']';
  if (d > 4) return '...';
  if (Array.isArray(v)) {
    const out = [];
    for (let i = 0; i < v.length; i++) out.push(i in v ? fmt(v[i], d + 1) : '<hole>');
    return '[' + out.join(', ') + ']';
  }
  return '{' + Reflect.ownKeys(v).map(k => {
    const desc = Object.getOwnPropertyDescriptor(v, k);
    return String(k) + ': ' + ('value' in desc ? fmt(desc.value, d + 1) : '<accessor>');
  }).join(', ') + '}';
};
const show = (label, f) => {
  try { console.log(label + ' => ' + fmt(f())); }
  catch (e) { console.log(label + ' !! ' + (e !== null && typeof e === 'object' ? e.name + ': ' + e.message : 'thrown ' + fmt(e))); }
};
'''


def check(run, workdir, name, body, **kw):
    """Run PRELUDE + body as a script and compare with the golden `name`."""
    return check_script(run, workdir, G, name, PRELUDE + body, **kw)


def test_property_key_order(run, workdir):
    """CATCHES: [[OwnPropertyKeys]] not listing array indices (up to 2**32-2) ascending first, then
    strings in insertion order, then symbols; '4294967295'/'-1'/'1.5'/'007' wrongly treated as
    indices; for-in not walking the prototype chain after own keys or repeating shadowed keys;
    delete+re-add not moving a key to the end; class static key order."""
    check(run, workdir, "property_key_order", r'''
const proto = {inherited: 1, shadowed: 'proto', 5: 'p5'};
const o = Object.create(proto);
o.zeta = 1; o[10] = 'ten'; o.alpha = 2; o[2] = 'two'; o['-1'] = 'neg'; o['1.5'] = 'frac'; o['007'] = 'bond';
o[Symbol('first')] = 's1'; o[4294967294] = 'maxidx'; o[4294967295] = 'notidx'; o.shadowed = 'own';
Object.defineProperty(o, 'hidden', {value: 'h', enumerable: false});
o[Symbol.for('second')] = 's2';
console.log('ownKeys:', Reflect.ownKeys(o).map(String).join(' '));
const fi = []; for (const k in o) fi.push(k);
console.log('for-in :', fi.join(' '));
delete o.zeta; o.zeta = 'again';
console.log('keys   :', Object.keys(o).join(' '));
console.log('values :', Object.values({b: 1, a: 2, 1: 3, 0: 4}).join(' '));
console.log('entries:', JSON.stringify(Object.entries({y: [1], x: 'v'})));
console.log('json   :', JSON.stringify({b: 1, 10: 2, a: 3, 2: 4}));
const arr = ['a', 'b']; arr.x = 1; arr[5] = 'f';
console.log('array  :', Object.getOwnPropertyNames(arr).join(' '));
console.log('string :', Object.getOwnPropertyNames('hi').join(' '), '|', Object.keys('abc').join(' '));
class K { static s = 1; static m() {} }
console.log('class  :', Object.getOwnPropertyNames(K).join(' '));
console.log('symbols:', Object.getOwnPropertySymbols({[Symbol.iterator]: 1, a: 2, [Symbol('x')]: 3}).map(String).join(' '));
const big = {}; for (const k of ['c', '3', 'b', '1', 'a', '2']) big[k] = k;
console.log('mixed  :', Object.keys(big).join(''));
''')


def test_object_static_methods(run, workdir):
    """CATCHES: Object.assign skipping string sources / not invoking getters in key order / not
    throwing on read-only targets; fromEntries/groupBy/create/hasOwn/setPrototypeOf semantics and
    their exact TypeError messages (e.g. prototype cycles, non-object protos, bad entries).
    Note: the reference's Object.hasOwn rejects primitive strings instead of applying ToObject."""
    check(run, workdir, "object_static_methods", r'''
show('assign', () => Object.assign({a: 1}, null, 'xy', undefined, {b: 2}, [9], 5));
show('assign getter order', () => { const log = []; Object.assign({}, {get b() { log.push('b'); return 1; }, get a() { log.push('a'); return 2; }}); return log; });
show('assign symbols', () => Object.assign({}, {[Symbol('s')]: 1, n: 2}));
show('assign to frozen', () => Object.assign(Object.freeze({a: 1}), {a: 2}));
show('assign null target', () => Object.assign(null));
show('assign prim target', () => typeof Object.assign(1, {x: 1}));
show('fromEntries', () => Object.fromEntries([['a', 1], ['b', 2], ['a', 3]]));
show('fromEntries map', () => Object.fromEntries(new Map([[1, 'x'], [Symbol.iterator, 'y']])));
show('fromEntries bad entry', () => Object.fromEntries([1]));
show('fromEntries null', () => Object.fromEntries(null));
show('groupBy', () => Object.groupBy([1, 2, 3, 4, 5], x => x % 2 ? 'odd' : 'even'));
show('groupBy proto', () => Object.getPrototypeOf(Object.groupBy([], x => x)));
show('groupBy index arg', () => Object.groupBy('abc', (c, i) => i > 0 ? 'rest' : 'first'));
show('groupBy not fn', () => Object.groupBy([1], 1));
show('create null', () => Object.getPrototypeOf(Object.create(null)));
show('create props', () => Object.create({}, {x: {value: 1, enumerable: true}, y: {value: 2}}));
show('create bad', () => Object.create(1));
show('create bad props', () => Object.create(null, {x: 1}));
show('setPrototypeOf cycle', () => { const a = {}; const b = Object.create(a); Object.setPrototypeOf(a, b); });
show('setPrototypeOf bad', () => Object.setPrototypeOf({}, 1));
show('setPrototypeOf prim', () => Object.setPrototypeOf(1, null));
show('setPrototypeOf nonext', () => Object.setPrototypeOf(Object.preventExtensions({}), {}));
show('setPrototypeOf null this', () => Object.setPrototypeOf(null, {}));
show('getPrototypeOf prim', () => [Object.getPrototypeOf('s') === String.prototype, Object.getPrototypeOf(1) === Number.prototype, Object.getPrototypeOf(true) === Boolean.prototype, Object.getPrototypeOf(Symbol()) === Symbol.prototype, Object.getPrototypeOf(1n) === BigInt.prototype]);
show('getPrototypeOf null', () => Object.getPrototypeOf(null));
show('is', () => [Object.is(NaN, NaN), Object.is(0, -0), Object.is('a', 'a'), Object.is({}, {})]);
show('hasOwn', () => [Object.hasOwn({a: 1}, 'a'), Object.hasOwn([], 'length'), Object.hasOwn(Object.create({a: 1}), 'a'), Object.hasOwn([5], 0)]);
show('hasOwn string (no ToObject)', () => Object.hasOwn('ab', 1));
show('hasOwn null', () => Object.hasOwn(null, 'a'));
show('keys null', () => Object.keys(null));
show('entries number', () => Object.entries(42));
show('defineProperties', () => Object.defineProperties({}, {a: {value: 1, enumerable: true}, b: {get() { return 2; }, enumerable: true}}));
show('defineProperties bad', () => Object.defineProperties({}, {a: 1}));
show('getOwnPropertyDescriptors', () => { const d = Object.getOwnPropertyDescriptors({a: 1, get b() { return 2; }}); return [d.a, Object.keys(d.b), typeof d.b.get, d.b.set]; });
show('Object()', () => [typeof Object(1), Object(null) instanceof Object, typeof Object('s'), Object(Symbol.iterator) instanceof Symbol]);
show('new Object(obj) identity', () => { const x = {}; return new Object(x) === x; });
''')


def test_define_property_and_integrity(run, workdir):
    """CATCHES: wrong descriptor validation/redefinition rules (non-configurable data may go
    writable->non-writable but never back; identical redefinition allowed), wrong
    freeze/seal/preventExtensions results, strict-mode assignment errors vs silent sloppy failure,
    and the exact TypeError messages for each violation."""
    check(run, workdir, "define_property_and_integrity", r'''
show('non-object target', () => Object.defineProperty(1, 'x', {}));
show('desc not object', () => Object.defineProperty({}, 'x', 1));
show('accessor+value', () => Object.defineProperty({}, 'x', {get() {}, value: 1}));
show('getter not fn', () => Object.defineProperty({}, 'x', {get: 1}));
show('setter not fn', () => Object.defineProperty({}, 'x', {set: 'no'}));
show('defaults', () => { const o = Object.defineProperty({}, 'x', {value: 1}); return Object.getOwnPropertyDescriptor(o, 'x'); });
show('accessor defaults', () => { const o = Object.defineProperty({}, 'x', {get() { return 1; }}); const d = Object.getOwnPropertyDescriptor(o, 'x'); return [typeof d.get, d.set, d.enumerable, d.configurable]; });
show('redefine nonconfig', () => { const o = {}; Object.defineProperty(o, 'x', {value: 1}); Object.defineProperty(o, 'x', {value: 2}); });
show('redefine same value', () => { const o = {}; Object.defineProperty(o, 'x', {value: 1}); Object.defineProperty(o, 'x', {value: 1}); return o.x; });
show('writable to false ok', () => { const o = {}; Object.defineProperty(o, 'x', {value: 1, writable: true}); Object.defineProperty(o, 'x', {writable: false, value: 3}); return Object.getOwnPropertyDescriptor(o, 'x'); });
show('writable back to true', () => { const o = {}; Object.defineProperty(o, 'x', {value: 1}); Object.defineProperty(o, 'x', {writable: true}); });
show('nonconfig enumerable change', () => { const o = {}; Object.defineProperty(o, 'x', {value: 1}); Object.defineProperty(o, 'x', {enumerable: true}); });
show('nonconfig data to accessor', () => { const o = {}; Object.defineProperty(o, 'x', {value: 1}); Object.defineProperty(o, 'x', {get() {}}); });
show('config data to accessor', () => { const o = {x: 1}; Object.defineProperty(o, 'x', {get() { return 'g'; }}); return [o.x, Object.getOwnPropertyDescriptor(o, 'x').enumerable]; });
show('nonext add', () => Object.defineProperty(Object.preventExtensions({}), 'x', {value: 1}));
const g1 = () => 1;
const acc = Object.defineProperty({}, 'a', {get: g1, configurable: false});
show('nonconfig accessor same getter', () => { Object.defineProperty(acc, 'a', {get: g1}); return Object.getOwnPropertyDescriptor(acc, 'a').get === g1; });
show('nonconfig accessor new getter', () => Object.defineProperty(acc, 'a', {get: () => 2}));
show('nonconfig accessor add setter', () => Object.defineProperty(acc, 'a', {set: v => {}}));
show('nonconfig accessor set undefined', () => { Object.defineProperty(acc, 'a', {set: undefined}); return 'ok'; });
show('nonconfig to configurable', () => Object.defineProperty(acc, 'a', {configurable: true}));
show('generic descriptor ok', () => { const o = Object.defineProperty({}, 'x', {value: 1, enumerable: true}); Object.defineProperty(o, 'x', {}); Object.defineProperty(o, 'x', {enumerable: true}); return Object.getOwnPropertyDescriptor(o, 'x'); });
show('-0 vs 0 nonwritable', () => { const o = {}; Object.defineProperty(o, 'z', {value: -0}); Object.defineProperty(o, 'z', {value: 0}); });
show('freeze', () => { const o = Object.freeze({a: {b: 1}}); o.a.b = 2; o.c = 1; return [Object.isFrozen(o), Object.isSealed(o), Object.isExtensible(o), o.a.b, 'c' in o]; });
show('seal', () => { const o = Object.seal({a: 1}); o.a = 2; delete o.a; o.c = 3; return [o, Object.isFrozen(o), Object.isSealed(o)]; });
show('preventExtensions', () => { const o = Object.preventExtensions({a: 1}); delete o.a; return [o, Object.isExtensible(o), Object.isSealed(o), Object.isFrozen(o)]; });
show('primitives', () => [Object.isFrozen(1), Object.isSealed('x'), Object.isExtensible(1), Object.freeze(5), Object.seal('s'), Object.preventExtensions(true)]);
show('empty nonext is frozen', () => Object.isFrozen(Object.preventExtensions({})));
show('accessor counts frozen', () => Object.isFrozen(Object.preventExtensions(Object.defineProperty({}, 'g', {get() {}}))));
show('frozen array push', () => Object.freeze([1]).push(2));
show('frozen array index', () => { 'use strict'; Object.freeze([1])[0] = 9; });
show('strict write readonly', () => { 'use strict'; const o = Object.freeze({a: 1}); o.a = 2; });
show('strict add nonext', () => { 'use strict'; const o = Object.preventExtensions({}); o.n = 1; });
show('strict delete nonconfig', () => { 'use strict'; delete Object.seal({k: 1}).k; });
show('strict setter-less accessor', () => { 'use strict'; const o = {get g() { return 1; }}; o.g = 2; });
show('sloppy writes ignored', () => { const o = Object.freeze({a: 1}); o.a = 2; o.b = 3; return [o.a, o.b, delete o.a]; });
show('array length nonwritable', () => { const a = [1, 2]; Object.defineProperty(a, 'length', {writable: false}); return [Reflect.set(a, 2, 'x'), a.length, Reflect.defineProperty(a, 'length', {value: 5})]; });
show('array length nonconfig element', () => { const a = [1, 2, 3]; Object.defineProperty(a, 1, {configurable: false}); a.length = 0; return [a.length, a]; });
show('strict length truncate blocked', () => { 'use strict'; const a = [1, 2, 3]; Object.defineProperty(a, 1, {configurable: false}); a.length = 0; });
''')


def test_object_prototype_methods(run, workdir):
    """CATCHES: Object.prototype.toString ignoring builtin tags (Arguments, Error, Boolean, Date...)
    or Symbol.toStringTag (incl. getters and non-string values); wrong hasOwnProperty /
    propertyIsEnumerable / isPrototypeOf on primitives; __proto__ accessor and
    __defineGetter__/__lookupGetter__ legacy methods misbehaving."""
    check(run, workdir, "object_prototype_methods", r'''
const tag = v => Object.prototype.toString.call(v);
console.log([null, undefined, [], function () {}, new Date(0), /x/, 1n, Symbol(), new Map(), new Set(),
  Promise.resolve(), JSON, Math, Reflect, true, 1, 's', new Error('e'), new TypeError('t'), new WeakMap(),
  new ArrayBuffer(1), function* () {}, async () => {}, new Proxy([], {}), new Proxy(function () {}, {}),
  Object.create(null), (function () { return arguments; })()].map(tag).join('\n'));
show('custom tag', () => [String({[Symbol.toStringTag]: 'Custom'}), tag({[Symbol.toStringTag]: 1}), tag(Object.assign([], {[Symbol.toStringTag]: 'NotArray'}))]);
show('tag getter', () => { class Q { get [Symbol.toStringTag]() { return 'QQ'; } } return [String(new Q()), tag(Q)]; });
show('hasOwnProperty', () => [({a: 1}).hasOwnProperty('a'), [].hasOwnProperty('length'), 'ab'.hasOwnProperty(0), 'ab'.hasOwnProperty('length'), ({}).hasOwnProperty('toString')]);
show('hasOwnProperty null this', () => Object.prototype.hasOwnProperty.call(null, 'x'));
show('propertyIsEnumerable', () => [[1].propertyIsEnumerable(0), [1].propertyIsEnumerable('length'), 'x'.propertyIsEnumerable(0), ({}).propertyIsEnumerable('missing')]);
show('isPrototypeOf', () => [Object.prototype.isPrototypeOf([]), Array.prototype.isPrototypeOf(Object.create(Array.prototype)), Object.prototype.isPrototypeOf.call(null, 1), Function.prototype.isPrototypeOf(Object)]);
show('isPrototypeOf null this', () => Object.prototype.isPrototypeOf.call(null, {}));
show('__proto__ literal', () => { const o = {__proto__: Array.prototype}; return [Array.isArray(o), o instanceof Array, '__proto__' in {}, Object.keys({__proto__: null}).length, Object.keys({['__proto__']: 1})]; });
show('__proto__ accessor', () => { const o = {}; o.__proto__ = null; return [Object.getPrototypeOf(o), o.__proto__, Object.create(null).__proto__]; });
show('__proto__ set prim ignored', () => { const o = {}; o.__proto__ = 5; return Object.getPrototypeOf(o) === Object.prototype; });
show('legacy accessors', () => { const o = {}; o.__defineGetter__('x', () => 5); o.__defineSetter__('y', function (v) { this.z = v; }); o.y = 3; return [o.x, o.z, typeof o.__lookupGetter__('x'), o.__lookupSetter__('x'), typeof Object.create(o).__lookupSetter__('y')]; });
show('defineGetter bad', () => ({}).__defineGetter__('x', 1));
show('toLocaleString', () => [({}).toLocaleString(), [1, 'a'].toLocaleString(), ({toString() { return 'custom'; }}).toLocaleString()]);
show('valueOf identity', () => { const o = {}; return [o.valueOf() === o, typeof Object.prototype.valueOf.call('s')]; });
show('valueOf null', () => Object.prototype.valueOf.call(null));
show('constructor links', () => [({}).constructor === Object, [].constructor === Array, (1).constructor === Number, Object.prototype.constructor === Object]);
show('Object.prototype proto immutable', () => [Reflect.setPrototypeOf(Object.prototype, {}), Reflect.setPrototypeOf(Object.prototype, null)]);
show('Object.prototype set proto', () => Object.setPrototypeOf(Object.prototype, {}));
''')


def test_function_call_apply_bind(run, workdir):
    """CATCHES: bound functions with wrong name ('bound bound f'), length (clamped at 0, Infinity
    preserved, fractional truncated, non-number ignored), no prototype, `new` ignoring the bound
    this; call/apply with array-likes; and the exact TypeErrors for non-callables."""
    check(run, workdir, "function_call_apply_bind", r'''
function foo(a, b, c) { return [this === undefined ? 'undef' : typeof this, a, b, c]; }
function strictFoo() { 'use strict'; return this; }
show('call', () => foo.call(1, 2, 3));
show('call this boxing', () => [typeof strictFoo.call(1), strictFoo.call(null), typeof foo.call(null)[0]]);
show('apply', () => foo.apply(null, [4, 5]));
show('apply arraylike', () => foo.apply(null, {length: 2, 0: 'x', 1: 'y'}));
show('apply null args', () => foo.apply(null, null));
show('apply bad', () => foo.apply(null, 1));
show('apply on non-fn', () => Function.prototype.apply.call({}, null, []));
show('call on non-fn', () => Function.prototype.call.call(1));
show('bound', () => { const b = foo.bind(null, 1); return [b.name, b.length, b(2, 3)]; });
show('bound bound', () => { const b = foo.bind(null, 1).bind(null, 2); return [b.name, b.length, 'prototype' in b, b(3)]; });
show('bound len over', () => foo.bind(null, 1, 2, 3, 4).length);
show('bound fractional len', () => { const f = function () {}; Object.defineProperty(f, 'length', {value: 2.7}); return f.bind().length; });
show('bound inf len', () => { const f = function () {}; Object.defineProperty(f, 'length', {value: Infinity}); return [f.bind().length, f.bind(null, 1).length]; });
show('bound neg inf len', () => { const f = function () {}; Object.defineProperty(f, 'length', {value: -Infinity}); return f.bind().length; });
show('bound string len', () => { const f = function () {}; Object.defineProperty(f, 'length', {value: '3'}); return f.bind().length; });
show('bound name nonstring', () => { const f = function () {}; Object.defineProperty(f, 'name', {value: 42}); return f.bind().name; });
show('bound anon', () => (() => {}).bind().name);
show('bound new', () => { function P(x, y) { this.x = x; this.y = y; } const B = P.bind({ignored: 1}, 7); const o = new B(8); return [o.x, o.y, o instanceof P, o instanceof B, Object.getPrototypeOf(o) === P.prototype]; });
show('bound new.target', () => { function T() { return new.target === T; } const B = T.bind(null); return [new B(), B()]; });
show('bound arrow not ctor', () => new ((() => {}).bind())());
show('bound class call', () => (class {}).bind()());
show('bind non-callable', () => Function.prototype.bind.call({}));
show('bound desc', () => { const d = Object.getOwnPropertyDescriptor(foo.bind(), 'name'); return [d.writable, d.enumerable, d.configurable]; });
show('fn props', () => [foo.length, foo.name, Object.getOwnPropertyNames(foo).sort(), Object.getOwnPropertyNames(() => 1).sort()]);
show('Function.prototype', () => [typeof Function.prototype, Function.prototype(), Function.prototype.length, Function.prototype.name, Object.getPrototypeOf(Function.prototype) === Object.prototype]);
show('strict caller', () => { 'use strict'; function s() {} return s.caller; });
show('sloppy caller/arguments', () => { function s() {} return [s.arguments, s.caller]; });
show('hasInstance', () => { class E { static [Symbol.hasInstance](x) { return x === 1; } } return [1 instanceof E, 2 instanceof E, Function.prototype[Symbol.hasInstance].call(Array, [])]; });
show('instanceof non-callable', () => ({}) instanceof {});
show('instanceof bad proto', () => { function F() {} F.prototype = 1; return ({}) instanceof F; });
show('instanceof bound', () => { function F() {} const B = F.bind(); return new F() instanceof B; });
''')


def test_function_tostring_and_names(run, workdir):
    """CATCHES: Function.prototype.toString not returning the exact source slice (whitespace,
    methods, getters, classes, async generators), wrong native/bound/Function-constructor
    forms, and wrong name inference for variables, computed keys, symbols and accessors."""
    check(run, workdir, "function_tostring_and_names", r'''
console.log((function   foo ( a ,b ) { return a+b }).toString());
console.log(((a) => a * 2).toString());
console.log((async (x)=>{ await x }).toString());
console.log((class A extends Object { m() {} static #p = 1; }).toString());
console.log(({ m(x) { return x; } }).m.toString());
console.log(({ async *ag() {} }).ag.toString());
console.log(({ ['comp' + 'uted']() {} }).computed.toString());
console.log(Object.getOwnPropertyDescriptor({get g() { return 1 }}, 'g').get.toString());
console.log(Object.getOwnPropertyDescriptor({set s(v) { }}, 's').set.toString());
console.log(Math.max.toString());
console.log(function () {}.bind().toString());
console.log(Object.getOwnPropertyDescriptor(Array, Symbol.species).get.toString());
console.log(new Function('a', 'b', 'return a + b').toString());
console.log(new Function().toString());
console.log(JSON.stringify(Function('x, y', '/* c */ return x').toString()));
console.log((function* gen() { yield 1 }).toString());
show('toString non fn', () => Function.prototype.toString.call({}));
show('toString proxy fn', () => Function.prototype.toString.call(new Proxy(function f() {}, {})));
show('Function ctor', () => [new Function('a', 'b', 'return a + b')(2, 3), Function('return this')() === globalThis, new Function('').name]);
show('Function ctor syntax', () => new Function('return {'));
show('Function ctor bad params', () => new Function('a b', 'return 1'));
show('Function ctor body injection', () => new Function('}, function() {'));
show('Function ctor comment injection', () => new Function('/*', '*/){'));
show('Function ctor params', () => [Function('a, /* c */ b', 'return a + b')(1, 2), Function('a = 5', '...rest', 'return [a, rest]')(undefined, 1, 2), Function('return new.target')()]);
show('Function ctor super', () => Function('super.x'));
show('Function subclass', () => { class F extends Function {} const f = new F('return 7'); return [f(), f instanceof F, Object.getPrototypeOf(f) === F.prototype]; });
const GF = Object.getPrototypeOf(function* () {}).constructor;
const AF = Object.getPrototypeOf(async function () {}).constructor;
const AGF = Object.getPrototypeOf(async function* () {}).constructor;
show('GeneratorFunction', () => { const g = GF('a', 'yield a; yield a * 2'); return [g.name, [...g(3)], g.toString(), Object.prototype.toString.call(g), GF.name, GF.length, GF === Function]; });
show('AsyncFunction', () => { const f = AF('x', 'return await x'); return [f.name, f.toString(), f(1) instanceof Promise, AF.name]; });
show('AsyncGeneratorFunction', () => { const f = AGF('yield 1'); return [f.name, f.toString(), Object.prototype.toString.call(f()), AGF.name]; });
show('eval direct vs indirect', () => { var local = 'L'; globalThis.gv = 'G'; return [eval('typeof local'), (0, eval)('typeof local'), (0, eval)('gv'), (0, eval)(42), (0, eval)(), eval({a: 1}).a]; });
show('indirect eval var', () => { (0, eval)('var fromIndirect = 1'); return typeof globalThis.fromIndirect; });
show('eval let scope', () => { eval('let scoped = 1'); return typeof scoped; });
show('eval syntax error', () => (0, eval)('1 +'));
show('names', () => {
  const a = function () {}; const b = () => {}; let c; c = function () {};
  const o = {d: function () {}, ['e' + 1]: () => {}, [Symbol('sy')]: function () {}, [Symbol()]: () => {}, f: class {}, g: function named() {}};
  const syms = Object.getOwnPropertySymbols(o);
  return [a.name, b.name, c.name, o.d.name, o.e1.name, o[syms[0]].name, o[syms[1]].name, o.f.name, o.g.name];
});
show('accessor names', () => { const d = Object.getOwnPropertyDescriptor({get x() { return 1; }, set x(v) {}}, 'x'); return [d.get.name, d.set.name]; });
show('symbol method name', () => ({[Symbol.iterator]() {}})[Symbol.iterator].name);
show('class static name method', () => { class A { static name() { return 'm'; } } return [typeof A.name, A.name()]; });
show('default export-ish names', () => { const {x = function () {}} = {}; const [y = () => {}] = []; return [x.name, y.name]; });
show('builtin names', () => [Array.prototype.at.name, Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.name, Symbol.prototype[Symbol.toPrimitive].name, Function.prototype[Symbol.hasInstance].name, Promise.all.name]);
show('builtin lengths', () => [Array.prototype.splice.length, Array.prototype.reduce.length, String.prototype.replace.length, Object.assign.length, Math.max.length, JSON.stringify.length, Function.prototype.bind.length]);
''')


def test_reflect_methods(run, workdir):
    """CATCHES: any of the 13 Reflect methods mis-implemented: boolean results instead of throwing
    (defineProperty/set/setPrototypeOf/preventExtensions), receivers ignored by get/set, newTarget
    ignored by construct, TypeErrors for non-object targets, and the property order of Reflect."""
    check(run, workdir, "reflect_methods", r'''
show('apply', () => Reflect.apply(Math.max, null, [1, 3, 2]));
show('apply noncallable', () => Reflect.apply(1, null, []));
show('apply no args', () => Reflect.apply(Math.max, null));
show('construct newTarget', () => { class A { constructor(x) { this.x = x; this.nt = new.target.name; } } class B {} const o = Reflect.construct(A, [1], B); return [o.x, o.nt, Object.getPrototypeOf(o) === B.prototype]; });
show('construct builtin', () => { const d = Reflect.construct(Date, [0], Object); return [Object.getPrototypeOf(d) === Object.prototype, Date.prototype.getTime.call(d)]; });
show('construct non-ctor', () => Reflect.construct(() => {}, []));
show('construct bad newTarget', () => Reflect.construct(function () {}, [], Math.max));
show('defineProperty', () => { const o = Object.freeze({}); return [Reflect.defineProperty(o, 'x', {value: 1}), Reflect.defineProperty({}, 'x', {value: 1})]; });
show('defineProperty non-object', () => Reflect.defineProperty(1, 'x', {}));
show('deleteProperty', () => { const o = {a: 1}; Object.defineProperty(o, 'b', {value: 1}); return [Reflect.deleteProperty(o, 'a'), Reflect.deleteProperty(o, 'b'), Reflect.deleteProperty(o, 'zz')]; });
show('get receiver', () => { const o = {get x() { return this.y; }}; return [Reflect.get(o, 'x', {y: 42}), Reflect.get([5], 0), Reflect.get({}, 'missing')]; });
show('get non-object', () => Reflect.get('str', 'length'));
show('set accessor receiver', () => { const r = {}; const o = {set x(v) { this.y = v; }}; return [Reflect.set(o, 'x', 5, r), r]; });
show('set data receiver', () => { const r = {}; return [Reflect.set({x: 1}, 'x', 5, r), r]; });
show('set nonwritable', () => Reflect.set(Object.freeze({x: 1}), 'x', 2));
show('set primitive receiver', () => Reflect.set({}, 'x', 2, 1));
show('set receiver accessor prop', () => { const r = {get x() { return 1; }}; return Reflect.set({x: 0}, 'x', 2, r); });
show('set receiver nonwritable own', () => { const r = Object.defineProperty({}, 'x', {value: 1, writable: false, configurable: true}); return Reflect.set({x: 0}, 'x', 2, r); });
show('getOwnPropertyDescriptor', () => [Reflect.getOwnPropertyDescriptor({a: 1}, 'a'), Reflect.getOwnPropertyDescriptor({}, 'a')]);
show('gopd primitive', () => Reflect.getOwnPropertyDescriptor('abc', 0));
show('getPrototypeOf', () => Reflect.getPrototypeOf([]) === Array.prototype);
show('getPrototypeOf primitive', () => Reflect.getPrototypeOf(1));
show('has', () => [Reflect.has({a: 1}, 'a'), Reflect.has([], 'length'), Reflect.has(Object.create({z: 1}), 'z'), Reflect.has({}, Symbol.iterator)]);
show('has primitive', () => Reflect.has('s', 'length'));
show('isExtensible', () => [Reflect.isExtensible({}), Reflect.isExtensible(Object.seal({}))]);
show('isExtensible primitive', () => Reflect.isExtensible(1));
show('ownKeys', () => Reflect.ownKeys({b: 1, [Symbol.for('s')]: 2, 10: 3, a: 4}));
show('ownKeys primitive', () => Reflect.ownKeys(1));
show('preventExtensions', () => { const o = {}; return [Reflect.preventExtensions(o), Object.isExtensible(o)]; });
show('preventExtensions primitive', () => Reflect.preventExtensions(1));
show('setPrototypeOf', () => [Reflect.setPrototypeOf({}, null), Reflect.setPrototypeOf(Object.preventExtensions({}), {}), Reflect.setPrototypeOf(Object.preventExtensions({}), Object.prototype)]);
show('setPrototypeOf cycle', () => { const a = {}; return Reflect.setPrototypeOf(a, Object.create(a)); });
show('setPrototypeOf bad proto', () => Reflect.setPrototypeOf({}, 1));
show('setPrototypeOf missing proto', () => Reflect.setPrototypeOf({}));
show('array length via Reflect', () => { const a = [1, 2, 3]; return [Reflect.defineProperty(a, 'length', {value: 1}), a, Reflect.set(a, 'length', 5), a.length]; });
show('Reflect shape', () => [Reflect[Symbol.toStringTag], typeof Reflect, Object.getOwnPropertyNames(Reflect).join(' ')]);
show('Reflect not ctor', () => new Reflect());
''')


def test_proxy_traps_observed_by_builtins(run, workdir):
    """CATCHES: built-ins performing the wrong sequence of internal methods on proxies (e.g.
    Object.keys skipping getOwnPropertyDescriptor, push/reverse/fill not using Set+length,
    JSON.stringify not reading toJSON first, concat ignoring isConcatSpreadable, rest destructuring
    re-reading excluded keys, spread/assign order, freeze not defining each key)."""
    check(run, workdir, "proxy_traps_observed_by_builtins", r'''
const log = [];
const describe = a => typeof a[1] === 'string' || typeof a[1] === 'symbol' ? ':' + String(a[1]) : '';
const logger = (target) => new Proxy(target, new Proxy({}, {
  get(_, trap) { return (...a) => { log.push(String(trap) + describe(a)); return Reflect[trap](...a); }; },
}));
const traced = (label, f) => { log.length = 0; show(label, f); console.log('   traps: ' + log.join(' ')); };
traced('Object.keys', () => Object.keys(logger({a: 1, b: 2})));
traced('Object.assign source', () => Object.assign({}, logger({a: 1, [Symbol('s')]: 2})));
traced('Object.assign target', () => { Object.assign(logger({}), {x: 1}); return 1; });
traced('spread', () => ({...logger({a: 1})}));
traced('JSON.stringify', () => JSON.stringify(logger({a: 1, b: [2]})));
traced('push', () => { const p = logger([1]); p.push(2); return p.length; });
traced('pop', () => logger([1, 2]).pop());
traced('concat', () => [0].concat(logger([1, 2])));
traced('in', () => 'a' in logger({}));
traced('delete', () => delete logger({a: 1}).a);
traced('for-in', () => { const r = []; for (const k in logger({x: 1, y: 2})) r.push(k); return r; });
traced('freeze', () => { Object.freeze(logger({a: 1})); return 1; });
traced('isFrozen', () => Object.isFrozen(logger({a: 1})));
traced('Array.from array-like', () => Array.from(logger({length: 2, 0: 'a', 1: 'b'})));
traced('instanceof', () => logger({}) instanceof Object);
traced('toString tag', () => Object.prototype.toString.call(logger([])));
traced('call', () => logger(function (a) { return a * 2; })(21));
traced('new', () => new (logger(class { constructor() { this.v = 1; } }))().v);
traced('reverse', () => { const p = logger([1, 2, 3]); p.reverse(); return 1; });
traced('includes', () => logger([1, 2]).includes(2));
traced('Array.isArray', () => Array.isArray(logger([])));
traced('rest destructuring', () => { const {a, ...r} = logger({a: 1, b: 2}); return r; });
traced('hasOwnProperty', () => Object.prototype.hasOwnProperty.call(logger({k: 1}), 'k'));
traced('getPrototypeOf', () => Object.getPrototypeOf(logger([])) === Array.prototype);
traced('defineProperty', () => { Object.defineProperty(logger({}), 'x', {value: 1}); return 1; });
traced('fill', () => { logger([0, 0]).fill(7); return 1; });
traced('with stmt', () => { const p = logger({v: 5}); with (p) { return v; } });
''')


def test_proxy_invariants_and_revocation(run, workdir):
    """CATCHES: missing proxy invariant checks (non-configurable / non-extensible targets for every
    trap, bad trap result types, duplicate ownKeys), wrong TypeError messages, strict-mode falsish
    set/delete results not throwing, Proxy constructor validation, revocation semantics and
    typeof/IsArray for proxies."""
    check(run, workdir, "proxy_invariants_and_revocation", r'''
const nonext = Object.preventExtensions({b: 2});
const nc = Object.defineProperty({}, 'c', {value: 3, configurable: false, writable: false});
show('get invariant', () => new Proxy(nc, {get() { return 4; }}).c);
show('get same value ok', () => new Proxy(nc, {get() { return 3; }}).c);
show('get accessor without getter', () => new Proxy(Object.defineProperty({}, 'g', {set(v) {}, configurable: false}), {get() { return 1; }}).g);
show('set invariant', () => { 'use strict'; new Proxy(nc, {set() { return true; }}).c = 9; });
show('set falsish strict', () => { 'use strict'; new Proxy({}, {set() { return false; }}).x = 1; });
show('set falsish sloppy', () => { const p = new Proxy({}, {set() { return false; }}); p.x = 1; return Reflect.set(p, 'x', 1); });
show('has hides nonconfig', () => 'c' in new Proxy(nc, {has() { return false; }}));
show('has hides on nonext', () => 'b' in new Proxy(nonext, {has() { return false; }}));
show('delete nonconfig', () => delete new Proxy(nc, {deleteProperty() { return true; }}).c);
show('delete falsish strict', () => { 'use strict'; delete new Proxy({x: 1}, {deleteProperty() { return false; }}).x; });
show('defineProperty falsish', () => Object.defineProperty(new Proxy({}, {defineProperty() { return false; }}), 'x', {value: 1}));
show('defineProperty falsish Reflect', () => Reflect.defineProperty(new Proxy({}, {defineProperty() { return false; }}), 'x', {value: 1}));
show('defineProperty on nonext', () => Object.defineProperty(new Proxy(nonext, {defineProperty() { return true; }}), 'z', {value: 1}));
show('defineProperty nonconfig missing', () => Object.defineProperty(new Proxy({}, {defineProperty() { return true; }}), 'z', {value: 1, configurable: false}));
show('gopd hides nonconfig', () => Object.getOwnPropertyDescriptor(new Proxy(nc, {getOwnPropertyDescriptor() { return undefined; }}), 'c'));
show('gopd bad type', () => Object.getOwnPropertyDescriptor(new Proxy({}, {getOwnPropertyDescriptor() { return 1; }}), 'c'));
show('gopd invents nonconfig', () => Object.getOwnPropertyDescriptor(new Proxy({}, {getOwnPropertyDescriptor() { return {value: 1, configurable: false}; }}), 'c'));
show('gopd incompatible', () => Object.getOwnPropertyDescriptor(new Proxy(nc, {getOwnPropertyDescriptor() { return {value: 7, configurable: false}; }}), 'c'));
show('gopd completes descriptor', () => Object.getOwnPropertyDescriptor(new Proxy({x: 1}, {getOwnPropertyDescriptor() { return {value: 5, configurable: true}; }}), 'x'));
show('ownKeys duplicate', () => Object.keys(new Proxy({}, {ownKeys() { return ['a', 'a']; }})));
show('ownKeys non-object', () => Object.keys(new Proxy({}, {ownKeys() { return 1; }})));
show('ownKeys bad element', () => Reflect.ownKeys(new Proxy({}, {ownKeys() { return [1]; }})));
show('ownKeys omits nonconfig', () => Reflect.ownKeys(new Proxy(nc, {ownKeys() { return []; }})));
show('ownKeys adds on nonext', () => Reflect.ownKeys(new Proxy(nonext, {ownKeys() { return ['b', 'x']; }})));
show('ownKeys array-like ok', () => Reflect.ownKeys(new Proxy({}, {ownKeys() { return {length: 2, 0: 'p', 1: Symbol.iterator}; }})));
show('getPrototypeOf bad', () => Object.getPrototypeOf(new Proxy({}, {getPrototypeOf() { return 1; }})));
show('getPrototypeOf nonext mismatch', () => Object.getPrototypeOf(new Proxy(nonext, {getPrototypeOf() { return null; }})));
show('setPrototypeOf falsish', () => Object.setPrototypeOf(new Proxy({}, {setPrototypeOf() { return false; }}), null));
show('setPrototypeOf nonext', () => Object.setPrototypeOf(new Proxy(nonext, {setPrototypeOf() { return true; }}), null));
show('isExtensible mismatch', () => Object.isExtensible(new Proxy({}, {isExtensible() { return false; }})));
show('preventExtensions lies', () => Object.preventExtensions(new Proxy({}, {preventExtensions() { return true; }})));
show('preventExtensions falsish', () => Object.preventExtensions(new Proxy({}, {preventExtensions() { return false; }})));
show('apply on non-callable target', () => new Proxy({}, {apply() { return 1; }})());
show('construct returns primitive', () => new (new Proxy(function () {}, {construct() { return 1; }}))());
show('construct non-ctor target', () => new (new Proxy(() => {}, {}))());
show('construct trap args', () => new (new Proxy(function () {}, {construct(t, args, nt) { return {args, same: nt === undefined}; }}))(1, 2));
show('trap not callable', () => new Proxy({}, {get: 1}).x);
show('trap null falls through', () => new Proxy({x: 'target'}, {get: null}).x);
show('revocable', () => {
  const {proxy, revoke} = Proxy.revocable({a: 1}, {});
  const r = [proxy.a, typeof revoke, revoke.length, revoke.name];
  revoke(); revoke();
  for (const op of [() => proxy.a, () => 'a' in proxy, () => Object.keys(proxy), () => Array.isArray(proxy)]) {
    try { op(); r.push('no throw'); } catch (e) { r.push(e.message); }
  }
  r.push(typeof proxy);
  return r;
});
show('revoked function typeof', () => { const {proxy, revoke} = Proxy.revocable(function () {}, {}); revoke(); return typeof proxy; });
show('Proxy without new', () => Proxy({}, {}));
show('Proxy non-object target', () => new Proxy(1, {}));
show('Proxy null handler', () => new Proxy({}, null));
show('typeof proxies', () => [typeof new Proxy(function () {}, {}), typeof new Proxy(class {}, {}), typeof new Proxy({}, {}), Array.isArray(new Proxy(new Proxy([], {}), {}))]);
show('Proxy shape', () => [Proxy.prototype, Proxy.length, Proxy.name, Object.getOwnPropertyNames(Proxy).sort().join(' ')]);
''')


def test_symbols_well_known_and_registry(run, workdir):
    """CATCHES: missing well-known symbols, wrong descriptions/toString, a broken Symbol.for/keyFor
    registry, Symbols constructible or implicitly convertible to string/number, wrong boxing, and
    protocols driven by Symbol.match/replace/search/split/matchAll/isConcatSpreadable/unscopables."""
    check(run, workdir, "symbols_well_known_and_registry", r'''
show('well-knowns', () => Object.getOwnPropertyNames(Symbol).filter(k => typeof Symbol[k] === 'symbol').sort().join(' '));
show('well-known descriptors', () => { const d = Object.getOwnPropertyDescriptor(Symbol, 'iterator'); return [d.writable, d.enumerable, d.configurable]; });
show('description', () => [Symbol('x').description, Symbol().description, Symbol('').description, Symbol(undefined).toString(), Symbol(null).toString(), Symbol(1).description, Symbol.iterator.description, Symbol.asyncIterator.toString()]);
show('registry', () => { const s = Symbol.for('app'); return [s === Symbol.for('app'), Symbol.keyFor(s), Symbol.keyFor(Symbol('app')), Symbol.keyFor(Symbol.iterator), Symbol.for().toString(), Symbol.keyFor(Symbol.for(undefined)), Symbol.for('app') === Symbol('app')]; });
show('keyFor non-symbol', () => Symbol.keyFor('x'));
show('new Symbol', () => new Symbol());
show('to number', () => Symbol() * 1);
show('template', () => `${Symbol('t')}`);
show('concat', () => Symbol('c') + '');
show('explicit String', () => [String(Symbol('ok')), Symbol('d').toString(), Object(Symbol('e')).toString()]);
show('boxed', () => { const o = Object(Symbol('w')); return [typeof o, o.description, o == o.valueOf(), Object.prototype.toString.call(o), typeof o.valueOf(), o instanceof Symbol]; });
show('truthiness', () => [!!Symbol(), Symbol() == Symbol(), typeof Symbol.prototype.valueOf.call(Symbol.iterator)]);
show('description getter bad this', () => Object.getOwnPropertyDescriptor(Symbol.prototype, 'description').get.call(1));
show('toString bad this', () => Symbol.prototype.toString.call('x'));
show('as property key', () => { const s = Symbol('k'); const o = {[s]: 1, plain: 2}; return [o[s], Object.keys(o), JSON.stringify(o), s in o, Object.getOwnPropertySymbols(o)[0] === s, {...o}[s]]; });
show('string protocol', () => {
  const m = {[Symbol.match](s) { return 'M:' + s; }, [Symbol.replace](s, r) { return 'R:' + s + r; }, [Symbol.search](s) { return 'S:' + s; }, [Symbol.split](s, l) { return 'P:' + s + l; }};
  return ['x'.match(m), 'x'.replace(m, 'y'), 'x'.search(m), 'x'.split(m, 3)];
});
show('matchAll without flags', () => 'x'.matchAll({[Symbol.match]: true, [Symbol.matchAll]() { return 1; }}));
show('replaceAll without flags', () => 'x'.replaceAll({[Symbol.match]: true}, 'z'));
show('matchAll/replaceAll global', () => { const m = {flags: 'g', [Symbol.match]: true, [Symbol.replace](s, r) { return 'R2:' + s + r; }, [Symbol.matchAll](s) { return 'A2:' + s; }}; return ['x'.replaceAll(m, 'z'), 'x'.matchAll(m)]; });
show('matchAll non-global', () => 'x'.matchAll({flags: 'i', [Symbol.match]: true}));
show('Symbol.match false', () => { const r = /a/; r[Symbol.match] = false; return ['/a/'.includes(r), '/a/'.startsWith(r)]; });
show('isConcatSpreadable', () => { const arr = [9]; arr[Symbol.isConcatSpreadable] = false; return [[].concat({length: 2, 0: 'a', 1: 'b', [Symbol.isConcatSpreadable]: true}), [].concat(arr).length]; });
show('unscopables', () => { const o = {a: 1, b: 2, [Symbol.unscopables]: {a: true}}; const a = 'outer'; with (o) { return [a, b]; } });
show('array unscopables', () => [Object.keys(Array.prototype[Symbol.unscopables]).sort().join(' '), Object.getPrototypeOf(Array.prototype[Symbol.unscopables])]);
show('species getters', () => [Array[Symbol.species] === Array, Map[Symbol.species] === Map, Promise[Symbol.species] === Promise, RegExp[Symbol.species] === RegExp, Object.getOwnPropertyDescriptor(Array, Symbol.species).get.name]);
show('Symbol statics', () => [Symbol.length, Symbol.name, Symbol.for.length, Symbol.keyFor.length]);
''')


def test_to_primitive_and_coercion_order(run, workdir):
    """CATCHES: ToPrimitive using the wrong hint (number/string/default) for +, `${}`, ==, arithmetic,
    Date; calling valueOf/toString in the wrong order or ignoring non-object results; missing
    TypeErrors when @@toPrimitive is not callable or returns an object."""
    check(run, workdir, "to_primitive_and_coercion_order", r'''
const log = [];
const tracer = (name) => ({
  valueOf() { log.push(name + '.valueOf'); return 10; },
  toString() { log.push(name + '.toString'); return 'str-' + name; },
});
const ops = {
  'unary +': o => +o, 'binary +': o => o + '', 'template': o => `${o}`, 'String()': o => String(o),
  'loose ==': o => o == 10, 'relational': o => o < 11, 'multiply': o => o * 2, 'property key': o => ({[o]: 1}),
  'Number()': o => Number(o), 'array join': o => [o].join(), 'Date ctor': o => new Date(o).getTime(),
};
for (const [label, f] of Object.entries(ops)) { log.length = 0; show(label, () => f(tracer('t'))); console.log('   calls: ' + log.join(' ')); }
const hinted = {[Symbol.toPrimitive](hint) { log.push(hint); return hint === 'number' ? 42 : hint === 'string' ? 'str' : 'dflt'; }};
log.length = 0;
show('toPrimitive hints', () => [+hinted, `${hinted}`, hinted + '', hinted * 2, [hinted] + '', String(hinted), hinted == 'dflt', hinted > 41]);
console.log('   hints: ' + log.join(' '));
show('Date hint', () => { const d = new Date(0); return [typeof (d + 0), typeof (d - 0), d[Symbol.toPrimitive]('number'), d[Symbol.toPrimitive]('default').slice(0, 3)]; });
show('Date bad hint', () => new Date(0)[Symbol.toPrimitive]('other'));
show('toPrimitive returns object', () => +{[Symbol.toPrimitive]() { return {}; }});
show('toPrimitive not callable', () => +{[Symbol.toPrimitive]: 1});
show('toPrimitive null is ignored', () => +{[Symbol.toPrimitive]: null, valueOf() { return 7; }});
show('both return objects', () => +{valueOf() { return {}; }, toString() { return {}; }});
show('valueOf object falls back', () => { const o = {valueOf() { return {}; }, toString() { return '5'; }}; return [+o, o * 1]; });
show('null proto object', () => `${Object.create(null)}`);
show('Symbol toPrimitive', () => [Symbol.prototype[Symbol.toPrimitive].call(Symbol.iterator) === Symbol.iterator, typeof Object(Symbol('b'))[Symbol.toPrimitive]('number')]);
show('array to number', () => [+[], +[5], +[1, 2], +[[3]], +['  7  '], [] + [], [] + {}, [1] == 1, [0] == false]);
show('boolean/null/undefined', () => [+true, +null, +undefined, null + 1, undefined + 1, true + true, '3' * '4', '3' + 4, 4 + '3', '10' / '4', '7' - - '2']);
''')


def test_json_parse(run, workdir):
    """CATCHES: JSON.parse accepting non-JSON (trailing commas, single quotes, leading zeros, raw
    control chars, bad escapes) or using wrong SyntaxError messages; reviver visiting keys in the
    wrong order, wrong `this`, not deleting on undefined, or missing the source-text context."""
    check(run, workdir, "json_parse", r'''
show('values', () => [JSON.parse(' [1e2, -0, 0.5, true, null, "\\ud83d\\ude00\\n", 1E-2, -12.5e+1] '), JSON.parse('"\\u0041\\/"'), JSON.parse('{}'), JSON.parse('\t\r\n 7 ')]);
show('__proto__ key', () => { const o = JSON.parse('{"__proto__": 1}'); return [Object.keys(o), Object.getPrototypeOf(o) === Object.prototype]; });
show('duplicate key', () => JSON.parse('{"a":1,"b":0,"a":2}'));
show('lone surrogate escape', () => JSON.parse('"\\ud800x"').charCodeAt(0));
show('big numbers', () => [JSON.parse('1e400'), JSON.parse('-1e-400'), JSON.parse('12345678901234567890')]);
const bad = ['', ' ', '[1,]', '{"a":1,}', "'x'", '01', '"\t"', '1 2', '{"a" 1}', '[1', '"\\x"', 'nul', '-', '1.', '.5', '+1', '{a:1}', '"abc', '[1 2]', '{"a":1 "b":2}', 'NaN', 'undefined', '\u00a01', '"\\u12"', '1e', '{,}', '[,1]', 'tru'];
for (const src of bad) show('parse ' + JSON.stringify(src), () => JSON.parse(src));
show('parse undefined', () => JSON.parse(undefined));
show('parse coerces', () => [JSON.parse(1), JSON.parse(null), JSON.parse({toString() { return '[2]'; }})]);
show('reviver transform', () => JSON.parse('{"a":[1,2,{"b":3}],"c":"x"}', (k, v) => typeof v === 'number' ? v * 10 : v));
show('reviver order', () => { const order = []; JSON.parse('{"a":{"b":1},"c":[2,3]}', function (k, v) { order.push(k === '' ? '<root>' : k); return v; }); return order; });
show('reviver delete', () => JSON.parse('{"a":1,"b":2,"c":[1,2]}', (k, v) => k === 'a' || k === '0' ? undefined : v));
show('reviver this', () => { const r = []; JSON.parse('{"x":1,"y":[0]}', function (k, v) { r.push(k + '<' + Object.keys(this).join('|') + '>'); return v; }); return r; });
show('reviver root replace', () => JSON.parse('[1]', (k, v) => k === '' ? 'replaced' : v));
show('reviver adds keys', () => JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') this.b = 'mutated'; return v; }));
show('reviver source', () => { const r = []; JSON.parse('{"n":1.0,"big":12345678901234567890,"s":"a\\u0041","arr":[1e2, -0],"t":true,"z":null}', (k, v, ctx) => { r.push(k + '=' + (ctx && ctx.source)); return v; }); return r; });
show('reviver throws', () => JSON.parse('[1]', () => { throw new RangeError('from reviver'); }));
const keep = (k, v) => v;
for (const src of ['{"a" 1}', '{"a":1 "b":2}', '[1 2]', '{"a":1,}', '"\\q"', '[01]', '"\\u00g0"', '{"a":tru}']) show('reviver path ' + JSON.stringify(src), () => JSON.parse(src, keep));
show('reviver path escapes', () => JSON.parse('["\\b\\f\\n\\r\\t\\/\\\\\\"", "\\ud83d\\ude00", "\\udc00\\ud800", "\\u00e9"]', keep).map(s => [...s].map(c => c.codePointAt(0).toString(16)).join(' ')));
show('reviver path empty containers', () => JSON.parse('{"o":{},"a":[],"n":[[]]}', keep));
show('reviver non-configurable delete', () => JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') Object.defineProperty(this, 'b', {value: 'locked', configurable: false}); return k === 'b' ? undefined : v; }));
show('reviver replaces with proxy', () => JSON.parse('{"p":{"x":1}}', function (k, v) { return k === 'p' ? new Proxy({y: 2}, {}) : v; }).p.y);
show('reviver holder is proxy-wrapped array', () => { const seen = []; JSON.parse('{"a":[1,2]}', function (k, v) { seen.push(k); if (k === 'a') return new Proxy(v, {}); return v; }); return seen; });
show('reviver grafted array-like', () => JSON.parse('{"a":0,"b":0}', function (k, v) { if (k === 'a') this.b = [10, 20]; return typeof v === 'number' ? v + 1 : v; }));
show('reviver not fn ignored', () => JSON.parse('[1]', 5));
show('deep nesting', () => { const s = '['.repeat(500) + ']'.repeat(500); return JSON.stringify(JSON.parse(s)).length; });
show('toStringTag', () => [JSON[Symbol.toStringTag], Object.getOwnPropertyNames(JSON).sort().join(' ')]);
''')


def test_json_stringify(run, workdir):
    """CATCHES: JSON.stringify mishandling undefined/functions/symbols (omit vs null), -0, NaN,
    boxed primitives, well-formed escaping of lone surrogates, gap clamping (10 chars max),
    replacer arrays (dedup, numbers, boxed strings) and functions (holder `this`), toJSON with key
    argument, cycles and BigInt errors, getters that throw, and JSON.rawJSON/isRawJSON."""
    check(run, workdir, "json_stringify", r'''
const p = (label, v) => console.log(label + ': ' + v);
p('omitted', JSON.stringify({a: undefined, b: () => 1, c: Symbol(), d: NaN, e: -0, f: Infinity, g: null, i: [undefined, () => 1, Symbol()]}));
p('top-level', [JSON.stringify(undefined), JSON.stringify(() => 1), JSON.stringify(Symbol()), JSON.stringify(null), JSON.stringify('s')].join(' '));
p('escapes', JSON.stringify('  "\\\b\f\n\r\t\u0001\u001f\u007f\u2028/'));
p('surrogates', [JSON.stringify('\uD800'), JSON.stringify('\uDC00\uD800'), JSON.stringify('😀'), JSON.stringify('a\uDBFFb')].join(' '));
p('boxed', JSON.stringify([Object('s'), Object(1), Object(false), Object(Symbol())]));
p('date', JSON.stringify({d: new Date(Date.UTC(2020, 0, 2, 3, 4, 5, 6)), bad: new Date(NaN)}));
p('indent 2', JSON.stringify({a: [1, {b: 2}], c: {}, e: []}, null, 2));
p('indent string', JSON.stringify([1, [2]], null, '--'));
p('indent clamp num', JSON.stringify({a: 1}, null, 20));
p('indent clamp str', JSON.stringify({a: 1}, null, 'abcdefghijklmn'));
p('indent zero/empty/neg', [JSON.stringify({a: 1}, null, 0), JSON.stringify([1], null, ''), JSON.stringify([1], null, -5)].join(' '));
p('indent boxed', JSON.stringify({a: 1}, null, new Number(3)) + ' ' + JSON.stringify({a: [1]}, null, new String('\t')));
p('replacer array', JSON.stringify({a: 1, b: 2, c: {a: 3, d: 4}}, ['a', 'c']));
p('replacer array numbers', JSON.stringify({1: 'one', 2: 'two', 3: 'three'}, [1, new String('2'), 1, {}]));
p('replacer array on arrays', JSON.stringify([{a: 1, b: 2}], ['b']));
p('replacer fn', JSON.stringify({a: 1, b: [2, 3], c: 'x'}, (k, v) => k === '' ? v : typeof v === 'number' ? v + 100 : k === 'c' ? undefined : v));
const holders = []; JSON.stringify({a: {b: 1}}, function (k, v) { holders.push(k + ':' + Object.keys(this)); return v; });
p('replacer this', JSON.stringify(holders));
p('replacer replaces root', JSON.stringify({x: 1}, (k, v) => k === '' ? [9] : v));
p('toJSON', JSON.stringify({a: {toJSON(k) { return 'A' + k; }}, b: [{toJSON(k) { return 'B' + typeof k + k; }}], c: {toJSON() { return undefined; }}}));
p('toJSON then replacer', JSON.stringify({a: {toJSON() { return 1; }}}, (k, v) => typeof v === 'number' ? v * 2 : v));
p('non-enumerable/symbol keys', JSON.stringify(Object.defineProperty({a: 1, [Symbol('x')]: 2}, 'b', {value: 2})));
p('map/set/error/regexp', JSON.stringify([new Map([[1, 2]]), new Set([1]), new Error('e'), /x/g]));
p('proxy array', JSON.stringify(new Proxy([1, {a: 2}], {})));
p('sparse array', JSON.stringify([1, , 3]));
p('proxy replacer array', JSON.stringify({a: 1, b: 2, c: 3}, new Proxy(['c', 'a'], {})));
p('proxy value object', JSON.stringify({p: new Proxy({k: [1]}, {}), q: new Proxy({}, {ownKeys() { return ['v']; }, getOwnPropertyDescriptor() { return {value: 'virtual', enumerable: true, configurable: true}; }, get() { return 'virtual'; }})}));
p('non-array replacer ignored', JSON.stringify({a: 1}, {a: true}));
p('replacer array with numbers and dups', JSON.stringify({10: 'x', 1.5: 'y'}, [10, 10, '10', 1.5]));
show('cycle object', () => { const o = {x: {}}; o.x.y = o; return JSON.stringify(o); });
show('cycle array', () => { const a = [1]; a.push(a); return JSON.stringify(a); });
show('repeated non-cyclic ok', () => { const s = {v: 1}; return JSON.stringify([s, s, {s}]); });
show('bigint', () => JSON.stringify({a: 1n}));
show('bigint nested', () => JSON.stringify([[2n]]));
show('boxed bigint', () => JSON.stringify(Object(3n)));
show('bigint toJSON', () => { BigInt.prototype.toJSON = function () { return this.toString() + 'n'; }; try { return JSON.stringify({a: 1n}); } finally { delete BigInt.prototype.toJSON; } });
show('getter throws', () => JSON.stringify({get a() { throw new RangeError('inside getter'); }}));
show('rawJSON', () => [JSON.stringify({a: JSON.rawJSON('12345678901234567890'), b: [JSON.rawJSON('"s"'), JSON.rawJSON('null')]}), JSON.isRawJSON(JSON.rawJSON('1')), JSON.isRawJSON({}), JSON.isRawJSON(1), Object.isFrozen(JSON.rawJSON('"x"')), JSON.rawJSON('true').rawJSON, Object.getPrototypeOf(JSON.rawJSON('1'))]);
show('rawJSON object', () => JSON.rawJSON('{}'));
show('rawJSON whitespace', () => JSON.rawJSON(' 1'));
show('rawJSON empty', () => JSON.rawJSON(''));
show('rawJSON invalid', () => JSON.rawJSON('1x'));
''')


def test_proxy_trap_validation_and_forwarding(run, workdir):
    """CATCHES: proxies not validating that each of the 13 traps is callable, wrong behaviour of a
    revoked proxy per operation (the reference reports different messages per internal method),
    trapless proxies (incl. proxies used as prototypes and as Reflect.set receivers) not forwarding
    every internal method to the target, and missing non-extensible-target invariant errors."""
    check(run, workdir, "proxy_trap_validation_and_forwarding", r'''const traps = ['get', 'set', 'has', 'deleteProperty', 'ownKeys', 'getOwnPropertyDescriptor', 'defineProperty', 'getPrototypeOf', 'setPrototypeOf', 'isExtensible', 'preventExtensions', 'apply', 'construct'];
const ops = {
  get: p => p.x, set: p => { p.x = 1; }, has: p => 'x' in p, deleteProperty: p => delete p.x,
  ownKeys: p => Reflect.ownKeys(p), getOwnPropertyDescriptor: p => Object.getOwnPropertyDescriptor(p, 'x'),
  defineProperty: p => Object.defineProperty(p, 'x', {value: 1}), getPrototypeOf: p => Object.getPrototypeOf(p),
  setPrototypeOf: p => Object.setPrototypeOf(p, null), isExtensible: p => Object.isExtensible(p),
  preventExtensions: p => Object.preventExtensions(p), apply: p => p(), construct: p => new p(),
};
for (const t of traps) show('non-callable ' + t, () => ops[t](new Proxy(function T() {}, {[t]: 1})));
for (const t of traps) show('revoked ' + t, () => { const r = Proxy.revocable(function T() {}, {}); r.revoke(); return ops[t](r.proxy); });
show('forward get/set', () => { const t = {x: 'inner x'}; const p = new Proxy(t, {}); p.y = 2; return [p.x, t.y]; });
show('forward has/delete', () => { const t = {x: 1}; const p = new Proxy(t, {}); return ['x' in p, 'nope' in p, delete p.x, 'x' in t]; });
show('forward keys', () => { const p = new Proxy({prototype: 1, x: 2, [Symbol.iterator]() {}}, {}); return [Object.keys(p), Reflect.ownKeys(p).length === 3, Object.getOwnPropertySymbols(p)]; });
show('forward gopd/define', () => { const t = {x: 'inner x'}; const p = new Proxy(t, {}); Object.defineProperty(p, 'z', {value: 'zz'}); return [Object.getOwnPropertyDescriptor(p, 'x'), t.z]; });
show('forward proto/extensible', () => { const t = []; const p = new Proxy(t, {}); return [Object.getPrototypeOf(p) === Array.prototype, Object.isExtensible(p)]; });
show('forward call/construct', () => { const p = new Proxy(function () { return 'called'; }, {}); return [p(), typeof new p()]; });
show('forward preventExtensions', () => { const t = {}; const p = new Proxy(t, {}); Object.preventExtensions(p); return [Object.isExtensible(p), Object.isExtensible(t), Reflect.preventExtensions(p)]; });
show('forward setPrototypeOf on nonext', () => { const p = new Proxy(Object.preventExtensions({}), {}); return Object.setPrototypeOf(p, {}); });
show('forward keys/values/entries', () => { const p = new Proxy({a: 1, b: 2}, {}); return [Object.keys(p), Object.values(p), Object.entries(p)]; });
show('isFrozen through traps', () => { const log = []; const p = new Proxy(Object.freeze({a: 1, b: 2}), {getOwnPropertyDescriptor(t, k) { log.push(k); return Reflect.getOwnPropertyDescriptor(t, k); }}); return [Object.isFrozen(p), log]; });
show('ownKeys omits key of nonext', () => Reflect.ownKeys(new Proxy(Object.preventExtensions({a: 1}), {ownKeys() { return []; }})));
show('Reflect.set with trap and receiver', () => { const recv = {}; let log; const p = new Proxy({}, {set(t, k, v, r) { log = [k, v, r === recv]; return true; }}); return [Reflect.set(p, 'k', 1, recv), log]; });
show('Reflect.set trapless forwards receiver', () => { const t = {}; const recv = {}; const ok = Reflect.set(new Proxy(t, {}), 'q', 9, recv); return [ok, recv.q, 'q' in t]; });
show('Reflect.set non-object', () => Reflect.set(1, 'a', 1));
show('Reflect.setPrototypeOf non-object', () => Reflect.setPrototypeOf(1, null));
show('Reflect on proxies', () => { const p = new Proxy({a: 1}, {}); return [Reflect.get(p, 'a'), Reflect.has(p, 'a'), Reflect.has(p, 'zz'), Reflect.deleteProperty(p, 'a')]; });
show('proxy as prototype get', () => { let o; const proto = new Proxy({a: 1}, {get(t, k, r) { return k in t ? t[k] : 'proto:' + String(k) + ':' + (r === o); }}); o = Object.create(proto); return [o.a, o.missing]; });
show('proxy as prototype set', () => { const proto = new Proxy({}, {}); const o = Object.create(proto); o.own = 1; return [Object.keys(o), Reflect.ownKeys(o)]; });
show('proxy as prototype has', () => { const proto = new Proxy({}, {has(t, k) { return k === 'virtual'; }}); const o = Object.create(proto); return ['virtual' in o, 'other' in o]; });
show('receiver is proxy', () => { const log = []; const recv = new Proxy({}, {defineProperty(t, k, d) { log.push('define ' + k + ' ' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); }, getOwnPropertyDescriptor(t, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }}); Reflect.set({}, 'p', 5, recv); Reflect.set({}, 'p', 6, recv); return log; });
show('legacy lookup through proxy', () => { const p = new Proxy({get g() { return 1; }}, {}); return [typeof Object.prototype.__lookupGetter__.call(p, 'g'), Object.prototype.propertyIsEnumerable.call(p, 'g')]; });
''')


def test_proxy_descriptor_invariants(run, workdir):
    """CATCHES: incomplete IsCompatiblePropertyDescriptor checks for proxy getOwnPropertyDescriptor
    and defineProperty traps (configurability, enumerability, data/accessor shape, writability,
    value and getter/setter identity against non-configurable or non-extensible targets), wrong
    descriptor completion, and the descriptor object/key types passed to the traps."""
    check(run, workdir, "proxy_descriptor_invariants", r'''
const nc = Object.defineProperty({}, 'c', {value: 3, configurable: false, writable: false, enumerable: false});
const ncw = Object.defineProperty({}, 'w', {value: 1, configurable: false, writable: true, enumerable: true});
const getter = function getter() { return 1; };
const nca = Object.defineProperty({}, 'a', {get: getter, configurable: false, enumerable: true});
const cfg = {k: 1};
const nonext = Object.preventExtensions({b: 2});
const gopd = (target, desc, key) => Object.getOwnPropertyDescriptor(new Proxy(target, {getOwnPropertyDescriptor() { return desc; }}), key);
show('gopd undefined on nonext', () => gopd(nonext, undefined, 'b'));
show('gopd missing on nonext', () => gopd(nonext, {value: 1, configurable: true}, 'zz'));
show('gopd report configurable', () => gopd(nc, {value: 3, configurable: true}, 'c'));
show('gopd different enumerable', () => gopd(nc, {value: 3, configurable: false, enumerable: true}, 'c'));
show('gopd shape change', () => gopd(nc, {get() {}, configurable: false}, 'c'));
show('gopd report writable', () => gopd(nc, {value: 3, writable: true, configurable: false}, 'c'));
show('gopd same getter ok', () => gopd(nca, {get: getter, configurable: false, enumerable: true}, 'a'));
show('gopd different getter', () => gopd(nca, {get() {}, configurable: false, enumerable: true}, 'a'));
show('gopd different setter', () => gopd(nca, {set(v) {}, configurable: false, enumerable: true}, 'a'));
show('gopd nonconfig for configurable', () => gopd(cfg, {value: 1, configurable: false}, 'k'));
show('gopd nonwritable for writable', () => gopd(ncw, {value: 1, writable: false, configurable: false, enumerable: true}, 'w'));
show('gopd ok', () => gopd(ncw, {value: 1, writable: true, configurable: false, enumerable: true}, 'w'));
show('gopd accessor completed', () => { const d = gopd({}, {get: getter, configurable: true}, 'x'); return [Object.keys(d), d.get === getter, d.set, d.enumerable]; });
show('gopd invalid descriptor', () => gopd({}, {get: 1, configurable: true}, 'x'));
show('gopd via hasOwnProperty', () => Object.prototype.hasOwnProperty.call(new Proxy(nc, {getOwnPropertyDescriptor() { return undefined; }}), 'c'));
const dp = (target, key, desc) => Reflect.defineProperty(new Proxy(target, {defineProperty() { return true; }}), key, desc);
show('dp configurable made nonconfig', () => dp(cfg, 'k', {configurable: false}));
show('dp nonconfig made configurable', () => dp(nc, 'c', {configurable: true}));
show('dp enumerable change', () => dp(nc, 'c', {enumerable: true}));
show('dp shape change', () => dp(nc, 'c', {get() {}}));
show('dp different getter', () => dp(nca, 'a', {get() {}}));
show('dp different setter', () => dp(nca, 'a', {set(v) {}}));
show('dp same getter', () => dp(nca, 'a', {get: getter}));
show('dp made writable', () => dp(nc, 'c', {writable: true}));
show('dp changed value', () => dp(nc, 'c', {value: 4}));
show('dp same value', () => dp(nc, 'c', {value: 3}));
show('dp writable reported nonwritable', () => dp(ncw, 'w', {writable: false, configurable: false}));
show('dp trap receives normalized descriptor', () => { let seen; Object.defineProperty(new Proxy({}, {defineProperty(t, k, d) { seen = [typeof k, k, d, Object.getPrototypeOf(d) === Object.prototype]; return Reflect.defineProperty(t, k, d); }}), 'x', {value: 1, enumerable: true, extra: 'ignored'}); return seen; });
show('dp symbol key', () => { let seen; Object.defineProperty(new Proxy({}, {defineProperty(t, k) { seen = typeof k; return true; }}), Symbol.iterator, {value: 1}); return seen; });
show('gopd trap key types', () => { const ks = []; const p = new Proxy({a: 1, [Symbol.for('z')]: 2}, {getOwnPropertyDescriptor(t, k) { ks.push(typeof k + ':' + String(k)); return Reflect.getOwnPropertyDescriptor(t, k); }}); Object.getOwnPropertyDescriptors(p); return ks; });
''')


def test_arguments_objects(run, workdir):
    """CATCHES: mapped arguments objects not aliasing formal parameters in both directions, not
    unmapping on defineProperty with writable:false/accessors or on delete, mapping extra or missing
    arguments, strict/default/rest functions not getting unmapped arguments, and wrong own keys,
    descriptors, callee/Symbol.iterator properties or strict-mode callee poison pill."""
    check(run, workdir, "arguments_objects", r'''
function mapped(a, b) {
  const r = [];
  arguments[0] = 'changed via arguments'; r.push(a);
  b = 'changed via param'; r.push(arguments[1]);
  r.push(Object.getOwnPropertyDescriptor(arguments, 0).value);
  Object.defineProperty(arguments, 0, {value: 'defined'}); r.push(a);
  Object.defineProperty(arguments, 1, {writable: false}); b = 'after unmap'; r.push(arguments[1]);
  delete arguments[0]; arguments[0] = 'recreated'; r.push(a);
  return r;
}
show('mapped', () => mapped(1, 2));
show('extra args unmapped', () => (function (a) { arguments[1] = 'x'; return [arguments.length, arguments[1]]; })(1));
show('missing param unmapped', () => (function (a, b) { arguments[1] = 'set'; return [b, arguments.length]; })(1));
show('strict unmapped', () => (function (a) { 'use strict'; arguments[0] = 'z'; return a; })(1));
show('default params unmapped', () => (function (a = 0) { arguments[0] = 'z'; return a; })(1));
show('rest params unmapped', () => (function (a, ...r) { a = 'p'; return arguments[0]; })(1, 2));
show('duplicate params', () => (function (a, a) { arguments[1] = 'second'; return a; })(1, 2));
show('props', () => (function () { return [Object.prototype.toString.call(arguments), arguments.length, typeof arguments.callee, Object.keys(arguments), Object.getOwnPropertyNames(arguments), arguments[Symbol.iterator] === Array.prototype.values]; })('a', 'b'));
show('length descriptor', () => (function () { return Object.getOwnPropertyDescriptor(arguments, 'length'); })(1));
show('strict callee', () => (function () { 'use strict'; return arguments.callee; })());
show('strict callee descriptor', () => (function () { 'use strict'; const d = Object.getOwnPropertyDescriptor(arguments, 'callee'); return [typeof d.get, d.get === d.set, d.enumerable, d.configurable]; })());
show('iteration', () => (function () { return [[...arguments], Array.from(arguments, x => x * 2), Array.prototype.slice.call(arguments, 1), JSON.stringify(arguments)]; })(1, 2, 3));
show('not an array', () => (function () { return [Array.isArray(arguments), typeof arguments.push]; })());
show('modify length', () => (function () { arguments.length = 1; return [...arguments]; })(1, 2, 3));
show('arrow inherits', () => (function () { return (() => arguments[0])(); })('outer'));
show('Reflect.gOPD sees live value', () => (function (a) { a = 'live'; return Reflect.getOwnPropertyDescriptor(arguments, '0').value; })('orig'));
show('freeze unmaps', () => (function (a) { Object.freeze(arguments); a = 'after freeze'; return [arguments[0], Object.isFrozen(arguments)]; })('orig'));
show('accessor unmaps', () => (function (a) { Object.defineProperty(arguments, 0, {get() { return 'getter'; }}); a = 'param'; return [arguments[0], a]; })('orig'));
show('value define keeps mapping', () => (function (a) { Object.defineProperty(arguments, 0, {value: 'v1'}); a = 'v2'; return arguments[0]; })('orig'));
''')


def test_module_namespace_object(run, workdir):
    """CATCHES: module namespace exotic objects with the wrong key order (sorted export names, then
    @@toStringTag), wrong descriptors, mutable/deletable bindings, a non-null prototype,
    defineProperty/setPrototypeOf/preventExtensions results that differ from the spec, stale (non-
    live) bindings, and the exact TypeErrors for writes and deletes in strict module code."""
    write_files(workdir, {"dep.mjs": "export let counter = 1;\nexport function bump() { counter++; }\n"
                                     "export const b = 'bee', a = 'ay';\nexport default 'dflt';\n"
                                     "export { counter as aliased };\n"})
    check(run, workdir, "module_namespace_object", r'''
import * as ns from './dep.mjs';
show('keys', () => Object.keys(ns));
show('ownKeys', () => Reflect.ownKeys(ns).map(String));
show('tag', () => [Object.prototype.toString.call(ns), ns[Symbol.toStringTag], Object.getOwnPropertyDescriptor(ns, Symbol.toStringTag)]);
show('proto/extensible', () => [Object.getPrototypeOf(ns), Object.isExtensible(ns), Object.isFrozen(ns), Object.isSealed(ns)]);
show('binding descriptor', () => Object.getOwnPropertyDescriptor(ns, 'counter'));
show('live binding', () => { const before = ns.counter; ns.bump(); return [before, ns.counter, ns.aliased]; });
show('assign existing', () => { ns.counter = 5; });
show('assign new', () => { ns.newProp = 1; });
show('delete export', () => delete ns.counter);
show('delete missing', () => delete ns.missing);
show('Reflect.set', () => Reflect.set(ns, 'counter', 1));
show('Reflect.deleteProperty', () => [Reflect.deleteProperty(ns, 'a'), Reflect.deleteProperty(ns, 'nope')]);
show('defineProperty same', () => Reflect.defineProperty(ns, 'a', {value: 'ay', writable: true, enumerable: true, configurable: false}));
show('defineProperty different', () => [Reflect.defineProperty(ns, 'a', {value: 'other'}), Reflect.defineProperty(ns, 'zz', {value: 1}), Reflect.defineProperty(ns, 'a', {enumerable: false})]);
show('Object.defineProperty', () => Object.defineProperty(ns, 'a', {value: 'other'}));
show('setPrototypeOf', () => [Reflect.setPrototypeOf(ns, null), Reflect.setPrototypeOf(ns, {})]);
show('preventExtensions', () => Reflect.preventExtensions(ns));
show('freeze', () => Object.freeze(ns));
show('in', () => ['a' in ns, 'default' in ns, 'nope' in ns, Symbol.toStringTag in ns]);
show('entries', () => Object.entries(ns).filter(([k]) => k !== 'bump'));
show('hasOwn', () => [Object.hasOwn(ns, 'default'), ns.hasOwnProperty]);
''', filename="module_namespace_object.mjs")
