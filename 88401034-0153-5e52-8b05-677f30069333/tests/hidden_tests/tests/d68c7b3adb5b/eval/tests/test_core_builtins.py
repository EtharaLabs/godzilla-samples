"""Core language built-ins for lumen-cli: Object/Array/String/Number/Math/Symbol/BigInt/Function/Error/
Reflect/Proxy/JSON/collections/iterator helpers, eval in odd contexts and Annex B legacy features.
Every program prints a deterministic report; most run on all three tiers against one shared golden."""

import pytest

from conftest import err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# Every program below starts with this reporter: each case prints `label: value` or `label: Name: message`.
SHOW = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
"""
END = "\nconsole.log(out.join('\\n'));\n"


@pytest.mark.parametrize("tier", TIERS)
def test_object_define_properties_and_descriptors(js, golden, tier):
    """CATCHES: Object.defineProperty/defineProperties/getOwnPropertyDescriptor(s) that skip ToPropertyDescriptor validation (accessor+value, non-callable getters), allow SameValue-violating redefinitions of non-configurable properties (-0 vs +0), or report wrong descriptors for strings, arrays, functions and proxies fail this."""
    code = SHOW + r"""function d(desc) { if (!desc) return String(desc); return Object.keys(desc).map(function (k) { var v = desc[k]; return k + '=' + (typeof v === 'function' ? 'fn:' + v.name : String(v)); }).join(','); }
var s = Symbol('sym');
show('defineProperties', function () { var o = Object.defineProperties({}, { a: { value: 1, enumerable: true }, b: { get: function () { return 2; }, configurable: true }, [s]: { value: 's', writable: true } }); return JSON.stringify(o) + ' ' + o.b + ' ' + d(Object.getOwnPropertyDescriptor(o, s)) + ' ' + d(Object.getOwnPropertyDescriptor(o, 'b')); });
show('defineProperties non-object descriptor', function () { return Object.defineProperties({}, { a: 1 }); });
show('defineProperties getter+value', function () { return Object.defineProperties({}, { a: { value: 1, get: function () {} } }); });
show('defineProperties bad getter', function () { return Object.defineProperties({}, { a: { get: 5 } }); });
show('defineProperties bad setter', function () { return Object.defineProperties({}, { a: { set: 'x' } }); });
show('defineProperties on primitive', function () { return Object.defineProperties(1, {}); });
show('defineProperties null props', function () { return Object.defineProperties({}, null); });
show('defineProperties string props', function () { return JSON.stringify(Object.defineProperties({}, 'ab')); });
show('defineProperties via proxy props', function () { var log = []; var p = new Proxy({ a: { value: 1, enumerable: true }, h: { value: 2 } }, { ownKeys: function (t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor: function (t, k) { log.push('gopd ' + k); var r = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'h') r.enumerable = false; return r; } }); var o = Object.defineProperties({}, p); return JSON.stringify(Object.getOwnPropertyNames(o)) + ' ' + log.join(','); });
show('defineProperties onto proxy', function () { var log = []; var p = new Proxy({}, { defineProperty: function (t, k, desc) { log.push(k + ':' + Object.keys(desc).sort().join('/')); return k !== 'no'; } }); try { Object.defineProperties(p, { yes: { value: 1 }, no: { get: function () {} } }); } catch (e) { log.push(e.name); } return log.join(' '); });
show('defineProperty returns', function () { var o = {}; return (Object.defineProperty(o, 'k', { value: 1 }) === o) + ' ' + d(Object.getOwnPropertyDescriptor(o, 'k')); });
show('defineProperty non-object', function () { return Object.defineProperty('str', 'x', {}); });
show('defineProperty redefine non-configurable', function () { var o = {}; Object.defineProperty(o, 'k', { value: 1 }); Object.defineProperty(o, 'k', { value: 2 }); });
show('defineProperty same value ok', function () { var o = {}; Object.defineProperty(o, 'k', { value: NaN }); Object.defineProperty(o, 'k', { value: NaN }); return 'ok ' + o.k; });
show('defineProperty -0 vs +0', function () { var o = {}; Object.defineProperty(o, 'k', { value: -0 }); Object.defineProperty(o, 'k', { value: 0 }); });
show('defineProperty enumerable change on non-configurable', function () { var o = {}; Object.defineProperty(o, 'k', { value: 1, enumerable: false }); return Reflect.defineProperty(o, 'k', { enumerable: true }) + ' ' + Reflect.defineProperty(o, 'k', { get: function () {} }) + ' ' + Reflect.defineProperty(o, 'k', { writable: true }) + ' ' + Reflect.defineProperty(o, 'k', { writable: false, enumerable: false }); });
show('defineProperty non-configurable accessor', function () { function g() { return 1; } var o = {}; Object.defineProperty(o, 'a', { get: g }); return [Reflect.defineProperty(o, 'a', { get: g }), Reflect.defineProperty(o, 'a', { get: function () {} }), Reflect.defineProperty(o, 'a', { set: function () {} }), Reflect.defineProperty(o, 'a', { set: undefined }), Reflect.defineProperty(o, 'a', { value: 1 })].join(); });
show('defineProperty accessor to data', function () { var o = {}; Object.defineProperty(o, 'k', { get: function () { return 1; }, configurable: true }); Object.defineProperty(o, 'k', { value: 5 }); return d(Object.getOwnPropertyDescriptor(o, 'k')); });
show('defineProperty data to accessor', function () { var o = { k: 1 }; Object.defineProperty(o, 'k', { set: function setK(v) {} }); return d(Object.getOwnPropertyDescriptor(o, 'k')); });
show('defineProperty descriptor via proto/getters', function () { var log = []; var desc = Object.create({ value: 'inherited' }); Object.defineProperty(desc, 'enumerable', { get: function () { log.push('enumerable'); return true; } }); var o = Object.defineProperty({}, 'p', desc); return o.p + ' ' + Object.keys(o) + ' ' + log; });
show('array length descriptors', function () { var a = [1, 2, 3]; var r = [Reflect.defineProperty(a, 'length', { value: 1 }), a.length, Reflect.defineProperty(a, 'length', { writable: false }), Reflect.defineProperty(a, 'length', { value: 1 }), Reflect.defineProperty(a, 'length', { value: 5 }), Reflect.defineProperty(a, 'length', { writable: true }), Reflect.defineProperty(a, 'length', { enumerable: true }), Reflect.defineProperty(a, 'length', { get: function () {} }), Reflect.defineProperty(a, '1', { value: 'x' })]; return r.join(); });
show('array length vs non-configurable element', function () { var a = [1, 2, 3]; Object.defineProperty(a, 1, { value: 'pin', configurable: false }); var ok = Reflect.defineProperty(a, 'length', { value: 0 }); return ok + ' ' + a.length + ' ' + JSON.stringify(a); });
show('array length bad values', function () { var r = []; [-1, 1.5, 2 ** 32, NaN, '3', { valueOf: function () { return 2; } }].forEach(function (v) { var a = [1, 2, 3, 4]; try { r.push(Reflect.defineProperty(a, 'length', { value: v }) + '/' + a.length); } catch (e) { r.push(e.name); } }); return r.join(' '); });
show('array index on non-writable length', function () { var a = [1]; Object.defineProperty(a, 'length', { writable: false }); return Reflect.defineProperty(a, '5', { value: 1 }) + ' ' + Reflect.defineProperty(a, '0', { value: 9 }) + ' ' + a[0] + ' ' + a.length; });
show('getOwnPropertyDescriptors', function () { var o = { a: 1, get b() { return 2; }, set c(v) {}, [s]: 3 }; var ds = Object.getOwnPropertyDescriptors(o); return Reflect.ownKeys(ds).map(function (k) { return String(k) + '{' + d(ds[k]) + '}'; }).join(' '); });
show('getOwnPropertyDescriptors array', function () { var ds = Object.getOwnPropertyDescriptors(['x']); return Object.keys(ds).join() + ' ' + d(ds.length); });
show('getOwnPropertyDescriptors string', function () { var ds = Object.getOwnPropertyDescriptors('hi'); return Object.keys(ds).join() + ' ' + d(ds[1]) + ' ' + d(ds.length); });
show('getOwnPropertyDescriptors proxy undefined', function () { var p = new Proxy({ a: 1 }, { ownKeys: function () { return ['a', 'ghost']; }, getOwnPropertyDescriptor: function (t, k) { return k === 'a' ? { value: 1, configurable: true, writable: true, enumerable: true } : undefined; } }); return Object.keys(Object.getOwnPropertyDescriptors(p)).join(); });
show('getOwnPropertyDescriptor primitive', function () { return d(Object.getOwnPropertyDescriptor('abc', 'length')) + ' | ' + d(Object.getOwnPropertyDescriptor('abc', 0)) + ' | ' + Object.getOwnPropertyDescriptor(5, 'x'); });
show('getOwnPropertyDescriptor null', function () { return Object.getOwnPropertyDescriptor(null, 'x'); });
show('getOwnPropertyDescriptor function', function () { function f(a, b) {} return d(Object.getOwnPropertyDescriptor(f, 'length')) + ' | ' + d(Object.getOwnPropertyDescriptor(f, 'name')) + ' | ' + d(Object.getOwnPropertyDescriptor(f, 'prototype')); });
show('getOwnPropertyDescriptor key coercion', function () { var log = []; var key = { toString: function () { log.push('toString'); return 'a'; } }; return d(Object.getOwnPropertyDescriptor({ a: 7 }, key)) + ' ' + log.join(); });
show('getOwnPropertyDescriptor private-looking key', function () { class C { #x = 1; } return Object.getOwnPropertyDescriptor(new C(), '#x') + ' ' + Reflect.ownKeys(new C()).length; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("object_define_properties_and_descriptors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_object_static_collection_helpers(js, golden, tier):
    """CATCHES: Object.fromEntries/groupBy/assign/keys/values/entries/getOwnPropertyNames/getOwnPropertySymbols/create/is/hasOwn that use the wrong key order (integer keys first), read getters at the wrong time, skip iterator closing, ignore proxy traps or ToObject on primitives fail this."""
    code = SHOW + r"""var s = Symbol('sym');
show('fromEntries', function () { return JSON.stringify(Object.fromEntries([['a', 1], ['b', 2], ['a', 3]])) + ' ' + JSON.stringify(Object.fromEntries(new Map([[1, 'one'], [{}, 'obj']]))) + ' ' + JSON.stringify(Object.fromEntries((function* () { yield ['g', 'gen']; })())); });
show('fromEntries bad entry', function () { return Object.fromEntries([1]); });
show('fromEntries null', function () { return Object.fromEntries(null); });
show('fromEntries closes iterator', function () { var closed = false; var it = { [Symbol.iterator]: function () { return { next: function () { return { value: 'bad', done: false }; }, return: function () { closed = true; return {}; } }; } }; try { Object.fromEntries(it); } catch (e) { return e.name + ' closed=' + closed; } });
show('fromEntries entry getter order', function () { var log = []; var entry = { get 0() { log.push('k'); return 'key'; }, get 1() { log.push('v'); return 'val'; } }; var r = Object.fromEntries([entry]); return log.join() + ' ' + JSON.stringify(r); });
show('fromEntries symbol keys', function () { var o = Object.fromEntries([[s, 'symval'], [1.5, 'num']]); return o[s] + ' ' + Object.keys(o); });
show('groupBy', function () { var g = Object.groupBy([1, 2, 3, 4, 5], function (x, i) { return x % 2 ? 'odd' : 'even'; }); return Object.getPrototypeOf(g) + ' ' + JSON.stringify(g); });
show('groupBy keys coerced', function () { var g = Object.groupBy(['a', 'bb', 'cc'], function (x) { return x.length; }); return Object.keys(g).join() + ' ' + JSON.stringify(g); });
show('groupBy string', function () { return JSON.stringify(Object.groupBy('abcab', function (c) { return c; })); });
show('groupBy index arg', function () { return JSON.stringify(Object.groupBy(['x', 'y', 'z'], function (v, i) { return i < 1 ? 'first' : 'rest'; })); });
show('groupBy non-callable', function () { return Object.groupBy([], 1); });
show('groupBy non-iterable', function () { return Object.groupBy(5, function () {}); });
show('Map.groupBy', function () { var k = {}; var m = Map.groupBy([1, 2, 3], function (x) { return x > 1 ? k : 'small'; }); return m.size + ' ' + m.get(k) + ' ' + m.get('small') + ' ' + Map.groupBy([-0, 0], function (x) { return x; }).size; });
show('assign', function () { var src = { a: 1, get g() { return 'got'; } }; Object.defineProperty(src, 'hidden', { value: 'no', enumerable: false }); src[s] = 'symval'; var t = Object.assign({}, src, null, undefined, 'xy', 5, [9]); return JSON.stringify(t) + ' ' + t[s]; });
show('assign setter on target', function () { var log = []; var t = { set a(v) { log.push('set a=' + v); } }; Object.assign(t, { a: 1 }); return log.join(); });
show('assign to non-writable', function () { var t = Object.freeze({ a: 1 }); return Object.assign(t, { a: 2 }); });
show('assign primitive target', function () { var r = Object.assign(3, { a: 1 }); return typeof r + ' ' + r.a + ' ' + (r instanceof Number); });
show('assign null target', function () { return Object.assign(null, {}); });
show('assign proxy source order', function () { var log = []; var p = new Proxy({ a: 1, b: 2 }, { ownKeys: function (t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor: function (t, k) { log.push('gopd:' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, get: function (t, k) { log.push('get:' + String(k)); return t[k]; } }); Object.assign({}, p); return log.join(' '); });
show('assign getter deletes later key', function () { var src = { get a() { delete this.b; return 1; }, b: 2, c: 3 }; return JSON.stringify(Object.assign({}, src)); });
show('keys/values/entries order', function () { var o = { b: 1, 2: 'two', a: 2, 1: 'one', [s]: 'sym', '-1': 'neg', '01': 'lead', 4294967295: 'big' }; return Object.keys(o).join() + ' | ' + Object.values(o).join() + ' | ' + Object.entries(o).map(function (e) { return e.join('='); }).join(); });
show('keys on primitives', function () { return Object.keys('abc').join() + ' ' + Object.keys(5).length + ' ' + Object.entries('xy').join(';') + ' ' + Object.values(true).length; });
show('keys null', function () { return Object.keys(null); });
show('values undefined', function () { return Object.values(undefined); });
show('values getter deletes', function () { var o = { get a() { delete this.b; return 'A'; }, b: 'B', c: 'C' }; return Object.values(o).join(); });
show('entries proxy', function () { var p = new Proxy({ x: 1, y: 2 }, { getOwnPropertyDescriptor: function (t, k) { var r = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'y') r.enumerable = false; return r; } }); return JSON.stringify(Object.entries(p)) + ' ' + JSON.stringify(Object.values(p)) + ' ' + Object.keys(p); });
show('keys of arguments and functions', function () { var a = (function () { return arguments; })(1, 2); return Object.keys(a).join() + ' ' + Object.keys(function f() {}).length + ' ' + Object.keys([, 'b']).join(); });
show('getOwnPropertyNames', function () { return Object.getOwnPropertyNames([1, 2]).join() + ' | ' + Object.getOwnPropertyNames('ab').join() + ' | ' + Object.getOwnPropertyNames(function f(a) {}).sort().join() + ' | ' + Object.getOwnPropertyNames(5).length; });
show('getOwnPropertyNames null', function () { return Object.getOwnPropertyNames(undefined); });
show('getOwnPropertyNames proxy', function () { var p = new Proxy({}, { ownKeys: function () { return ['z', s, 'a']; } }); return Object.getOwnPropertyNames(p).join() + ' ' + Object.getOwnPropertySymbols(p).map(String).join(); });
show('getOwnPropertySymbols', function () { var o = { a: 1, [s]: 1, [Symbol.iterator]: 2 }; return Object.getOwnPropertySymbols(o).map(String).join() + ' ' + Object.getOwnPropertySymbols('str').length; });
show('getOwnPropertySymbols null', function () { return Object.getOwnPropertySymbols(null); });
show('create', function () { var o = Object.create({ inherited: 1 }, { own: { value: 2, enumerable: true } }); return o.inherited + ' ' + JSON.stringify(o) + ' ' + Object.getPrototypeOf(Object.create(null)); });
show('create bad proto', function () { return Object.create(1); });
show('create undefined', function () { return Object.create(undefined); });
show('create bad props', function () { return Object.create({}, null); });
show('is', function () { return [Object.is(NaN, NaN), Object.is(0, -0), Object.is(-0, -0), Object.is('a', 'a'), Object.is({}, {}), Object.is(1n, 1n), Object.is(), Object.is(Symbol.iterator, Symbol.iterator)].join(); });
show('hasOwn', function () { return [Object.hasOwn({ a: 1 }, 'a'), Object.hasOwn([], 'length'), Object.hasOwn(Object.create({ x: 1 }), 'x'), Object.hasOwn({ [s]: 1 }, s)].join(); });
show('hasOwn null', function () { return Object.hasOwn(null, 'a'); });
show('Object()', function () { var o = {}; return [Object(o) === o, typeof Object(1), typeof Object(null), Object(undefined) instanceof Object, Object('s').length, typeof Object(1n), typeof Object(s), new Object(true) instanceof Boolean, Object.length, Object.name].join(); });
show('Object subclass new.target', function () { class O extends Object { constructor() { super(5); } } var o = new O(); return (o instanceof O) + ' ' + (typeof o.valueOf()); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("object_static_collection_helpers")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_object_prototype_chain_operations(js, golden, tier):
    """CATCHES: getPrototypeOf/setPrototypeOf/__proto__ implementations that allow prototype cycles, change the immutable Object.prototype or non-extensible objects, mishandle primitives and null, or skip proxy getPrototypeOf/setPrototypeOf trap validation fail this."""
    code = SHOW + r"""var OP = Object.prototype;
show('getPrototypeOf primitives', function () { return [Object.getPrototypeOf(1) === Number.prototype, Object.getPrototypeOf('s') === String.prototype, Object.getPrototypeOf(true) === Boolean.prototype, Object.getPrototypeOf(Symbol()) === Symbol.prototype, Object.getPrototypeOf(1n) === BigInt.prototype, Object.getPrototypeOf(Object.prototype)].join(); });
show('getPrototypeOf undefined', function () { return Object.getPrototypeOf(undefined); });
show('setPrototypeOf', function () { var a = {}; var b = Object.create(a); return [Object.setPrototypeOf(1, null), Object.setPrototypeOf(b, null) === b, Object.getPrototypeOf(b)].join(); });
show('setPrototypeOf cycle', function () { var a = {}; var b = Object.create(a); return Object.setPrototypeOf(a, b); });
show('setPrototypeOf self', function () { var a = {}; return Reflect.setPrototypeOf(a, a); });
show('setPrototypeOf bad proto', function () { return Object.setPrototypeOf({}, 5); });
show('setPrototypeOf undefined target', function () { return Object.setPrototypeOf(undefined, {}); });
show('setPrototypeOf non-extensible', function () { return Object.setPrototypeOf(Object.preventExtensions({}), {}); });
show('setPrototypeOf non-extensible same', function () { var o = Object.preventExtensions({}); return Object.setPrototypeOf(o, Object.prototype) === o; });
show('setPrototypeOf Object.prototype', function () { return Object.setPrototypeOf(Object.prototype, {}); });
show('setPrototypeOf Object.prototype null ok', function () { return Object.setPrototypeOf(Object.prototype, null) === Object.prototype; });
show('__proto__ accessor', function () { var d = Object.getOwnPropertyDescriptor(OP, '__proto__'); var o = {}; o.__proto__ = Array.prototype; var r = [typeof d.get, typeof d.set, Array.isArray(o), o instanceof Array, (5).__proto__ === Number.prototype, d.get.call(1) === Number.prototype]; o.__proto__ = 5; r.push(Object.getPrototypeOf(o) === Array.prototype); var n = Object.create(null); n.__proto__ = Array.prototype; r.push(Object.getPrototypeOf(n), Object.keys(n).join()); return r.join(); });
show('__proto__ setter on primitive', function () { var set = Object.getOwnPropertyDescriptor(OP, '__proto__').set; return set.call(1, {}); });
show('__proto__ setter on undefined', function () { var set = Object.getOwnPropertyDescriptor(OP, '__proto__').set; return set.call(undefined, {}); });
show('__proto__ getter on undefined', function () { var get = Object.getOwnPropertyDescriptor(OP, '__proto__').get; return get.call(undefined); });
show('__proto__ setter cycle', function () { var a = {}; var b = Object.create(a); a.__proto__ = b; });
show('__proto__ setter non-extensible', function () { var a = Object.preventExtensions({}); try { a.__proto__ = {}; } catch (e) { return e.name; } });
show('__proto__ in literals', function () { var p = { tag: 'P' }; var o1 = { __proto__: p }; var o2 = { '__proto__': p }; var o3 = { ['__proto__']: p }; var __proto__ = p; var o4 = { __proto__ }; var o5 = { __proto__: 5 }; return [o1.tag, o2.tag, Object.getPrototypeOf(o3) === OP, Object.keys(o3).join(), Object.getPrototypeOf(o4) === OP, Object.keys(o4).join(), Object.getPrototypeOf(o5) === OP].join(); });
show('proxy setPrototypeOf trap false', function () { return Reflect.setPrototypeOf(new Proxy({}, { setPrototypeOf: function () { return false; } }), null); });
show('proxy setPrototypeOf trap false Object', function () { return Object.setPrototypeOf(new Proxy({}, { setPrototypeOf: function () { return false; } }), null); });
show('proxy setPrototypeOf not callable', function () { return Object.setPrototypeOf(new Proxy({}, { setPrototypeOf: 'x' }), null); });
show('proxy setPrototypeOf forward', function () { var t = {}; var p = new Proxy(t, {}); Object.setPrototypeOf(p, Array.prototype); return Array.isArray(p) + ' ' + (Object.getPrototypeOf(t) === Array.prototype); });
show('proxy setPrototypeOf nonext ok', function () { var t = Object.preventExtensions({}); var p = new Proxy(t, { setPrototypeOf: function () { return true; } }); return Reflect.setPrototypeOf(p, Object.prototype); });
show('proxy setPrototypeOf nonext lie', function () { var t = Object.preventExtensions({}); var p = new Proxy(t, { setPrototypeOf: function () { return true; } }); return Reflect.setPrototypeOf(p, null); });
show('proxy in proto chain stops cycle check', function () { var a = {}; var p = new Proxy(Object.create(a), {}); return Reflect.setPrototypeOf(a, p); });
show('proxy getPrototypeOf not callable', function () { return Object.getPrototypeOf(new Proxy({}, { getPrototypeOf: 7 })); });
show('proxy getPrototypeOf forward to proxy', function () { var inner = new Proxy(Object.create(Array.prototype), {}); return Object.getPrototypeOf(new Proxy(inner, { getPrototypeOf: undefined })) === Array.prototype; });
show('revoked setPrototypeOf', function () { var r = Proxy.revocable({}, {}); r.revoke(); return Object.setPrototypeOf(r.proxy, null); });
show('revoked getPrototypeOf', function () { var r = Proxy.revocable({}, {}); r.revoke(); return Object.getPrototypeOf(r.proxy); });
show('isPrototypeOf through proxy', function () { var proto = {}; var p = new Proxy({}, { getPrototypeOf: function () { return proto; } }); return proto.isPrototypeOf(p) + ' ' + OP.isPrototypeOf(p); });
show('instanceof through proxy prototype', function () { function F() {} var p = new Proxy({}, { getPrototypeOf: function () { return F.prototype; } }); return p instanceof F; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("object_prototype_chain_operations")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_integrity_levels_on_exotic_objects(js, golden, tier):
    """CATCHES: freeze/seal/preventExtensions/isFrozen/isSealed that ignore array length, typed array element rules, String wrapper indices, arguments objects or proxy preventExtensions/ownKeys/defineProperty traps, or that let strict-mode writes, deletes and adds on locked objects pass silently fail this."""
    code = SHOW + r"""function st(o) { return [Object.isExtensible(o), Object.isSealed(o), Object.isFrozen(o)].map(Number).join(''); }
show('primitives', function () { return [Object.freeze(1), Object.seal('s'), Object.preventExtensions(true), st(1), st('x'), st(undefined), Object.isExtensible(1)].join(); });
show('empty object', function () { var o = {}; var a = st(o); Object.preventExtensions(o); return a + ' ' + st(o); });
show('object with props', function () { var o = { a: 1 }; Object.preventExtensions(o); var a = st(o); Object.seal(o); var b = st(o); o.a = 2; Object.freeze(o); return a + ' ' + b + ' ' + st(o) + ' a=' + o.a; });
show('accessor frozen', function () { var o = Object.freeze({ get x() { return 1; } }); return st(o) + ' ' + JSON.stringify(Object.getOwnPropertyDescriptor(o, 'x')); });
show('non-writable but configurable', function () { var o = {}; Object.defineProperty(o, 'k', { value: 1, writable: false, configurable: true }); Object.preventExtensions(o); return st(o); });
show('array freeze', function () { var a = Object.freeze([1, 2]); var r = st(a); try { a.push(3); } catch (e) { r += ' push:' + e.name; } return r + ' len=' + a.length; });
show('array seal then set', function () { var a = Object.seal([1, 2]); a[0] = 9; a[5] = 1; return st(a) + ' ' + JSON.stringify(a); });
show('array pop on frozen', function () { var a = Object.freeze([1]); return a.pop(); });
show('array shift on sealed', function () { var a = Object.seal([1, 2]); return a.shift(); });
show('array unshift on frozen', function () { return Object.freeze([1]).unshift(0); });
show('array reverse on frozen', function () { return Object.freeze([1, 2]).reverse(); });
show('typed array freeze', function () { return Object.freeze(new Uint8Array(2)); });
show('typed array empty freeze', function () { return st(Object.freeze(new Uint8Array(0))); });
show('typed array seal', function () { var t = Object.seal(new Uint8Array(2)); return st(t); });
show('typed array preventExtensions', function () { var t = new Int8Array(3); Object.preventExtensions(t); return st(t); });
show('string wrapper', function () { var s = new String('ab'); var r = st(s); Object.freeze(s); return r + ' ' + st(s); });
show('string wrapper seal check', function () { var s = Object.preventExtensions(new String('ab')); return st(s); });
show('function freeze', function () { function f() {} Object.freeze(f); f.x = 1; return st(f) + ' ' + f.x + ' ' + Object.isFrozen(f.prototype); });
show('arguments freeze', function () { return (function (a) { Object.freeze(arguments); arguments[0] = 9; return st(arguments) + ' ' + a + ' ' + arguments[0]; })(1); });
show('proxy freeze traps', function () { var log = []; var p = new Proxy({ a: 1 }, { preventExtensions: function (t) { log.push('pe'); return Reflect.preventExtensions(t); }, ownKeys: function (t) { log.push('ok'); return Reflect.ownKeys(t); }, defineProperty: function (t, k, d) { log.push('dp:' + k + ':' + Object.keys(d).join('/')); return Reflect.defineProperty(t, k, d); }, getOwnPropertyDescriptor: function (t, k) { log.push('gopd:' + k); return Reflect.getOwnPropertyDescriptor(t, k); } }); Object.freeze(p); return log.join(' '); });
show('proxy seal traps', function () { var log = []; var p = new Proxy({ a: 1, get b() { return 2; } }, { defineProperty: function (t, k, d) { log.push('dp:' + k + ':' + Object.keys(d).join('/')); return Reflect.defineProperty(t, k, d); } }); Object.seal(p); return log.join(' ') + ' ' + st(p); });
show('proxy freeze defineProperty false', function () { var p = new Proxy({ a: 1 }, { defineProperty: function () { return false; } }); return Object.freeze(p); });
show('isFrozen proxy with configurable prop', function () { var t = Object.preventExtensions({ a: 1 }); return Object.isFrozen(new Proxy(t, {})) + ' ' + Object.isSealed(new Proxy(t, {})); });
show('isFrozen proxy with writable prop', function () { var t = Object.seal({ a: 1 }); return Object.isFrozen(new Proxy(t, {})) + ' ' + Object.isSealed(new Proxy(t, {})); });
show('isFrozen proxy lying gopd', function () { var t = Object.preventExtensions({}); var p = new Proxy(t, { ownKeys: function () { return []; } }); return Object.isFrozen(p); });
show('proxy preventExtensions false', function () { var p = new Proxy({}, { preventExtensions: function () { return false; } }); return Object.preventExtensions(p); });
show('proxy preventExtensions lies', function () { var p = new Proxy({}, { preventExtensions: function () { return true; } }); return Object.preventExtensions(p); });
show('proxy preventExtensions not callable', function () { return Object.preventExtensions(new Proxy({}, { preventExtensions: 5 })); });
show('Reflect.preventExtensions false', function () { var p = new Proxy({}, { preventExtensions: function () { return false; } }); return Reflect.preventExtensions(p); });
show('proxy isExtensible not callable', function () { return Object.isExtensible(new Proxy({}, { isExtensible: 1 })); });
show('proxy isExtensible mismatch', function () { return Object.isExtensible(new Proxy({}, { isExtensible: function () { return false; } })); });
show('proxy isExtensible forward', function () { return Object.isExtensible(new Proxy(Object.preventExtensions({}), { isExtensible: null })); });
show('revoked', function () { var r = Proxy.revocable({}, {}); r.revoke(); var res = []; [Object.isExtensible, Object.preventExtensions, Object.getPrototypeOf, Object.keys, Object.freeze, Object.isFrozen, Object.isSealed, Object.seal].forEach(function (f) { try { f(r.proxy); res.push('ok'); } catch (e) { res.push(e.name); } }); return res.join(); });
show('isFrozen proxy', function () { var p = new Proxy(Object.freeze({ a: 1 }), {}); return Object.isFrozen(p) + ' ' + Object.isSealed(p); });
show('freeze nested', function () { var o = Object.freeze({ inner: { x: 1 } }); o.inner.x = 2; return o.inner.x + ' ' + Object.isFrozen(o.inner); });
show('strict write frozen', function () { 'use strict'; var o = Object.freeze({ a: 1 }); o.a = 2; });
show('strict add non-extensible', function () { 'use strict'; var o = Object.preventExtensions({}); o.b = 2; });
show('strict add index on frozen array', function () { 'use strict'; var a = Object.freeze([]); a[0] = 1; });
show('strict delete sealed', function () { 'use strict'; var o = Object.seal({ a: 1 }); delete o.a; });
show('sloppy delete sealed', function () { var o = Object.seal({ a: 1 }); return delete o.a; });
show('defineProperty on non-extensible', function () { return Object.defineProperty(Object.preventExtensions({}), 'x', { value: 1 }); });
show('Reflect.defineProperty on non-extensible', function () { return Reflect.defineProperty(Object.preventExtensions({}), 'x', { value: 1 }); });
show('frozen array length', function () { var a = Object.freeze([1, 2, 3]); a.length = 0; return a.length; });
show('freeze map still mutable', function () { var m = Object.freeze(new Map()); m.set(1, 2); return m.size + ' ' + st(m); });
show('global object integrity', function () { return Object.isExtensible(globalThis) + ' ' + Object.isFrozen(Math) + ' ' + Object.isSealed(JSON); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("integrity_levels_on_exotic_objects")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_object_prototype_methods_and_tags(js, golden, tier):
    """CATCHES: Object.prototype methods that do not coerce the key before ToObject(this), report the wrong [[Class]]/@@toStringTag for built-in objects, iterators, proxies and wrappers, or that let the Annex B __defineGetter__/__lookupGetter__ family skip prototype walks or callability checks fail this."""
    code = SHOW + r"""var OP = Object.prototype;
show('hasOwnProperty', function () { var s = Symbol(); var o = { a: 1, [s]: 1 }; return [o.hasOwnProperty('a'), o.hasOwnProperty('toString'), o.hasOwnProperty(s), OP.hasOwnProperty.call('abc', 1), OP.hasOwnProperty.call('abc', 'length'), OP.hasOwnProperty.call([1], 0), OP.hasOwnProperty.call(function () {}, 'prototype'), OP.hasOwnProperty.call(new Uint8Array(2), 1), OP.hasOwnProperty.call(new Uint8Array(2), 2), OP.hasOwnProperty.call(5, 'x')].join(); });
show('hasOwnProperty null this', function () { return OP.hasOwnProperty.call(null, 'a'); });
show('hasOwnProperty key first', function () { var log = []; try { OP.hasOwnProperty.call(undefined, { toString: function () { log.push('tostr'); return 'k'; } }); } catch (e) { return e.name + ' log=' + log.join(); } });
show('hasOwnProperty proxy', function () { var log = []; var p = new Proxy({ a: 1 }, { getOwnPropertyDescriptor: function (t, k) { log.push(k); return Reflect.getOwnPropertyDescriptor(t, k); } }); return p.hasOwnProperty('a') + ' ' + p.hasOwnProperty('b') + ' ' + log.join(); });
show('isPrototypeOf', function () { function F() {} var f = new F(); return [F.prototype.isPrototypeOf(f), OP.isPrototypeOf(f), Array.prototype.isPrototypeOf([]), OP.isPrototypeOf.call(F.prototype, 1), F.prototype.isPrototypeOf(F.prototype), OP.isPrototypeOf(Object.create(null))].join(); });
show('isPrototypeOf null this primitive arg', function () { return OP.isPrototypeOf.call(null, 1); });
show('isPrototypeOf null this object arg', function () { return OP.isPrototypeOf.call(null, {}); });
show('propertyIsEnumerable', function () { var o = { a: 1 }; Object.defineProperty(o, 'h', { value: 1 }); return [o.propertyIsEnumerable('a'), o.propertyIsEnumerable('h'), o.propertyIsEnumerable('toString'), [1].propertyIsEnumerable(0), [1].propertyIsEnumerable('length'), 'ab'.propertyIsEnumerable(0), 'ab'.propertyIsEnumerable('length')].join(); });
show('propertyIsEnumerable null', function () { return OP.propertyIsEnumerable.call(null, 'x'); });
show('propertyIsEnumerable proxy', function () { var p = new Proxy({}, { getOwnPropertyDescriptor: function (t, k) { return k === 'yes' ? { value: 1, enumerable: true, configurable: true } : undefined; } }); return p.propertyIsEnumerable('yes') + ' ' + p.propertyIsEnumerable('no'); });
show('toString tags', function () { var ts = OP.toString; function* g() {} async function af() {} return [ts.call(undefined), ts.call(null), ts.call(1), ts.call('s'), ts.call(true), ts.call(Symbol()), ts.call(1n), ts.call([]), ts.call(function () {}), ts.call(g), ts.call(af), ts.call(new Error()), ts.call(new TypeError()), ts.call(new Date(0)), ts.call(/x/), ts.call((function () { return arguments; })()), ts.call(new Map()), ts.call(new Set()), ts.call(new WeakMap()), ts.call(Promise.resolve()), ts.call(g()), ts.call(new ArrayBuffer(1)), ts.call(new DataView(new ArrayBuffer(1))), ts.call(new Float64Array(1)), ts.call(Math), ts.call(JSON), ts.call(Reflect), ts.call(Atomics), ts.call(new Proxy([], {})), ts.call(new Proxy(function () {}, {})), ts.call([][Symbol.iterator]()), ts.call(new Map().entries()), ts.call(''[Symbol.iterator]()), ts.call('a'.matchAll(/a/g)), ts.call(Object(1n)), ts.call(new WeakRef({})), ts.call(new FinalizationRegistry(function () {})), ts.call(new Boolean(false)), ts.call(new Number(1)), ts.call(new String('')), ts.call(Object(Symbol()))].join(' '); });
show('toString custom tag', function () { var o = { [Symbol.toStringTag]: 'Custom' }; var a = []; a[Symbol.toStringTag] = 'NotArr'; var f = function () {}; f[Symbol.toStringTag] = 5; var n = new Number(1); n[Symbol.toStringTag] = 'Tagged'; return OP.toString.call(o) + ' ' + OP.toString.call(a) + ' ' + OP.toString.call(f) + ' ' + OP.toString.call(n) + ' ' + OP.toString.call(Object.create(null)); });
show('toString tag getter throws', function () { return OP.toString.call({ get [Symbol.toStringTag]() { throw new RangeError('tag'); } }); });
show('toString revoked proxy', function () { var r = Proxy.revocable([], {}); r.revoke(); return OP.toString.call(r.proxy); });
show('toLocaleString', function () { return [OP.toLocaleString.call({ toString: function () { return 'custom'; } }), OP.toLocaleString.call(1), [1, 'a', null, undefined, { toLocaleString: function () { return 'L'; } }].toLocaleString()].join(' | '); });
show('toLocaleString null', function () { return OP.toLocaleString.call(null); });
show('toLocaleString non-callable', function () { return OP.toLocaleString.call({ toString: 1 }); });
show('array toLocaleString non-callable', function () { return [{ toLocaleString: 1 }].toLocaleString(); });
show('valueOf', function () { var o = {}; return [o.valueOf() === o, typeof OP.valueOf.call(1), OP.valueOf.call('s') instanceof String].join(); });
show('valueOf null', function () { return OP.valueOf.call(null); });
show('__defineGetter__', function () { var o = {}; o.__defineGetter__('g', function () { return 'G'; }); o.__defineSetter__('s', function (v) { this._s = v; }); o.s = 4; var gd = Object.getOwnPropertyDescriptor(o, 'g'); return [o.g, o._s, gd.enumerable, gd.configurable, typeof o.__lookupGetter__('g'), o.__lookupGetter__('s'), typeof o.__lookupSetter__('s'), o.__lookupSetter__('nope'), typeof Object.create(o).__lookupGetter__('g'), ({ a: 1 }).__lookupGetter__('a')].join(); });
show('__defineGetter__ non-callable', function () { return ({}).__defineGetter__('x', 1); });
show('__defineSetter__ non-callable', function () { return ({}).__defineSetter__('x', {}); });
show('__defineGetter__ frozen', function () { return Object.freeze({}).__defineGetter__('x', function () {}); });
show('__lookupGetter__ null this', function () { return OP.__lookupGetter__.call(null, 'x'); });
show('__lookupGetter__ proxy', function () { var log = []; var p = new Proxy({}, { getOwnPropertyDescriptor: function (t, k) { log.push('gopd ' + k); }, getPrototypeOf: function () { log.push('gpo'); return null; } }); p.__lookupGetter__('q'); return log.join(); });
show('__lookupGetter__ proxy accessor', function () { function getter() { return 1; } var p = new Proxy({}, { getOwnPropertyDescriptor: function (t, k) { return k === 'acc' ? { get: getter, configurable: true } : k === 'dat' ? { value: 1, configurable: true } : undefined; } }); return (p.__lookupGetter__('acc') === getter) + ' ' + p.__lookupSetter__('acc') + ' ' + p.__lookupGetter__('dat'); });
show('__defineGetter__ on proxy', function () { var log = []; var p = new Proxy({}, { defineProperty: function (t, k, d) { log.push(k + ':' + Object.keys(d).sort().join('/')); return Reflect.defineProperty(t, k, d); } }); p.__defineGetter__('w', function () { return 'W'; }); return log.join() + ' ' + p.w; });
show('__defineGetter__ on primitive', function () { var r = OP.__defineGetter__.call(5, 'x', function () {}); return r; });
show('__defineGetter__ key coercion', function () { var o = {}; o.__defineGetter__(12, function () { return 'twelve'; }); return Object.keys(o) + ' ' + o[12]; });
show('constructor props', function () { return [OP.constructor === Object, Object.length, Object.name, Object.prototype.toString.length, Object.getOwnPropertyNames(OP).sort().join()].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("object_prototype_methods_and_tags")
    assert (r.returncode, r.stderr) == (0, b"")


ARRAY_J = r"""function j(a) { var r = []; for (var i = 0; i < a.length; i++) r.push(i in a ? JSON.stringify(a[i]) : '_'); return '[' + r.join(',') + ']'; }
"""


@pytest.mark.parametrize("tier", TIERS)
def test_array_construction_and_length_limits(js, golden, tier):
    """CATCHES: Array constructors and length-changing methods that accept invalid lengths (negative, fractional, >= 2^32), let push/unshift/splice/concat/toSpliced exceed 2^53-1 without a TypeError, mishandle indices at 2^32-1, or that mis-size Array.from/Array.of results fail this."""
    code = SHOW + ARRAY_J + r"""show('ctor', function () { return [j(Array(3)), j(Array(1, 2)), j(Array('3')), j(new Array(0)), Array.length, j(Array.call(null, 2)), j(new Array(undefined))].join(' '); });
show('ctor bad length', function () { return new Array(-1); });
show('ctor fractional', function () { return Array(1.5); });
show('ctor 2^32', function () { return Array(4294967296); });
show('ctor max', function () { return Array(4294967295).length; });
show('ctor subclass', function () { class A extends Array {} var a = new A(3); return (a instanceof A) + ' ' + a.length + ' ' + Array.isArray(a) + ' ' + (A.from([1]) instanceof A); });
show('ctor new.target proto', function () { function F() {} F.prototype = Array.prototype; var a = Reflect.construct(Array, [2], F); return Array.isArray(a) + ' ' + a.length; });
show('length assignments', function () { var a = [1, 2, 3]; a.length = 1; var b = []; b.length = 3; var r = [j(a), j(b)]; try { a.length = -1; } catch (e) { r.push(e.name + ': ' + e.message); } try { a.length = 1.5; } catch (e) { r.push(e.name); } a.length = '2'; r.push(a.length); a.length = { valueOf: function () { return 0; } }; r.push(a.length); return r.join(' '); });
show('index beyond 2^32-2', function () { var a = []; a[4294967295] = 'x'; a[4294967294] = 'y'; return a.length + ' ' + Object.keys(a).join(); });
show('push past 2^32', function () { var a = []; a.length = 4294967295; try { a.push(1); } catch (e) { return e.name + ' ' + a.length + ' ' + a[4294967295]; } });
show('splice huge array-like', function () { return Array.prototype.splice.call({ length: 2 ** 53 - 1 }, 0, 0, 'x'); });
show('splice 2^32', function () { var o = { length: 2 ** 32, 4294967295: 'last' }; Array.prototype.splice.call(o, 4294967295, 1); return o.length + ' ' + (4294967295 in o); });
show('unshift huge', function () { return Array.prototype.unshift.call({ length: 2 ** 53 - 1 }, 1); });
show('unshift huge zero args', function () { return Array.prototype.unshift.call({ length: 2 ** 53 - 1 }); });
show('concat huge', function () { var o = { length: 2 ** 53 - 1, [Symbol.isConcatSpreadable]: true }; return [1].concat(o); });
show('concat huge non-spreadable', function () { var big = []; big.length = 2; return Array.prototype.concat.call(big, { length: 1 }).length; });
show('toSpliced too long', function () { return Array.prototype.toSpliced.call({ length: 2 ** 53 - 1 }, 0, 0, 1); });
show('toReversed huge', function () { return Array.prototype.toReversed.call({ length: 2 ** 32 }); });
show('toSorted huge', function () { return Array.prototype.toSorted.call({ length: 2 ** 32 }); });
show('with huge', function () { return Array.prototype.with.call({ length: 2 ** 32 }, 0, 1); });
show('fill huge array-like', function () { return Array.prototype.fill.call({ length: 2 ** 40 }, 0, 2 ** 40 - 2).length; });
show('apply huge', function () { return Math.max.apply(null, { length: 2 ** 32 }); });
show('Array.from length', function () { return [Array.from({ length: 3, 1: 'mid' }).length, Array.from({ length: -1 }).length, Array.from({ length: '2' }).length].join(); });
show('Array.from huge', function () { return Array.from({ length: 2 ** 32 }); });
show('Array.of', function () { return j(Array.of()) + j(Array.of(7)) + j(Array.of(1, 'a')) + j(Array.of(undefined)); });
show('Array.of non-writable result', function () { function C() { Object.defineProperty(this, '0', { value: 'fixed', writable: false, configurable: false }); } return Array.of.call(C, 'x'); });
show('isArray', function () { var r = Proxy.revocable([], {}); var res = [Array.isArray([]), Array.isArray(new Proxy([], {})), Array.isArray(new Proxy(new Proxy([], {}), {})), Array.isArray({ length: 0 }), Array.isArray(Array.prototype), Array.isArray(), Array.isArray(new Uint8Array(1)), Array.isArray((function () { return arguments; })())]; r.revoke(); try { Array.isArray(r.proxy); } catch (e) { res.push(e.name); } return res.join(); });
show('species length overflow', function () { var a = [1, 2]; a.constructor = { [Symbol.species]: function (n) { return { length: 0, n: n }; } }; return JSON.stringify(a.map(function (x) { return x; })); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("array_construction_and_length_limits")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_array_mutators_on_dense_and_sparse_arrays(js, golden, tier):
    """CATCHES: push/pop/shift/unshift/splice/reverse/fill/copyWithin implementations that fill holes, drop inherited elements, mis-clamp negative or Infinity indices, or fail to throw TypeErrors when the target elements are frozen fail this."""
    code = SHOW + ARRAY_J + r"""show('push/pop/shift/unshift', function () { var a = [1, 2]; var r = [a.push(3, 4), a.pop(), a.shift(), a.unshift(0, -1), j(a), [].pop(), [].shift(), a.unshift()]; return r.join(' '); });
show('sparse push', function () { var a = [, , 1]; a.push(2); return j(a) + ' ' + a.length; });
show('shift/unshift sparse', function () { var a = [1, , 3]; a.shift(); var b = [, 2]; b.unshift('x'); return j(a) + ' ' + j(b); });
show('pop on sparse', function () { var a = [1, , ,]; var v = a.pop(); return v + ' ' + a.length + ' ' + j(a); });
show('slice', function () { var a = [1, 2, 3, 4, 5]; return [j(a.slice()), j(a.slice(1, -1)), j(a.slice(-2)), j(a.slice(10)), j(a.slice(2, 1)), j(a.slice(-100, 2)), j(a.slice(undefined, undefined)), j([1, , 3].slice(0)), j(a.slice('1', '3')), j(a.slice(-Infinity, Infinity)), j(a.slice(NaN, 2))].join(' '); });
show('splice', function () { var a = [1, 2, 3, 4, 5]; var r1 = a.splice(1, 2); var r2 = a.splice(-1, 1, 'x', 'y'); var r3 = a.splice(1); var b = [1, 2, 3]; var r4 = b.splice(); var r5 = b.splice(0, undefined); var c = [1, 2, 3]; var r6 = c.splice(1, Infinity); var d = [1, 2, 3]; var r7 = d.splice(-Infinity, 1, 'start'); return [j(r1), j(r2), j(r3), j(a), j(r4), j(r5), j(b), j(r6), j(c), j(r7), j(d)].join(' '); });
show('splice sparse', function () { var a = [1, , 3, , 5]; var r = a.splice(1, 2, 'a'); return j(r) + ' ' + j(a); });
show('splice insert into sparse', function () { var a = [1, , 3]; a.splice(1, 0, 'x', 'y'); return j(a) + ' ' + a.length; });
show('splice array-like inserts', function () { var o = { length: 4, 0: 'a', 1: 'b', 3: 'd' }; var r = Array.prototype.splice.call(o, 1, 1, 'X', 'Y', 'Z'); return JSON.stringify(r) + ' ' + JSON.stringify(o); });
show('splice array-like shrink with holes', function () { var o = { length: 5, 0: 0, 2: 2, 4: 4 }; Array.prototype.splice.call(o, 0, 2); return JSON.stringify(o); });
show('splice frozen', function () { return Object.freeze([1, 2]).splice(0, 1); });
show('reverse', function () { var a = [1, 2, 3, 4]; a.reverse(); var b = [1, , 3]; b.reverse(); var c = [, 2, 3, ,]; c.reverse(); return j(a) + ' ' + j(b) + ' ' + j([].reverse()) + ' ' + j(c); });
show('reverse array-like one hole', function () { var o = { length: 3, 0: 'a' }; Array.prototype.reverse.call(o); var p = { length: 3, 2: 'c' }; Array.prototype.reverse.call(p); return JSON.stringify(o) + ' ' + JSON.stringify(p); });
show('fill', function () { return [j([1, 2, 3].fill(0)), j([1, 2, 3].fill(9, 1)), j([1, 2, 3].fill(9, -1)), j([1, 2, 3].fill(9, 0, -2)), j(Array(3).fill()), j([1, 2].fill(7, 5)), j([1, 2, 3].fill(8, -Infinity, Infinity)), j([1, 2, 3].fill(4, NaN, NaN))].join(' '); });
show('fill frozen', function () { return Object.freeze([1]).fill(0); });
show('copyWithin', function () { return [j([1, 2, 3, 4, 5].copyWithin(0, 3)), j([1, 2, 3, 4, 5].copyWithin(1, 0, 3)), j([1, 2, 3, 4, 5].copyWithin(-2, -4, -3)), j([1, , 3].copyWithin(0, 1)), j([1, 2, 3].copyWithin(0, 5)), j([1, 2, 3, 4].copyWithin(2, 0)), j([1, 2, 3].copyWithin(-Infinity, 1, Infinity))].join(' '); });
show('copyWithin frozen', function () { return Object.freeze([1, 2]).copyWithin(0, 1); });
show('proto elements', function () { Array.prototype[1] = 'proto'; var a = [0, , 2]; var r = [a[1], a.indexOf('proto'), a.includes('proto'), j(a.slice()), a.join(), JSON.stringify(a), j(a.concat()), a.lastIndexOf('proto')]; var b = [0, , 2]; b.reverse(); r.push(Object.keys(b).join()); delete Array.prototype[1]; return r.join(' '); });
show('getters on indices', function () { var a = [1, 2, 3]; var log = []; Object.defineProperty(a, 1, { get: function () { log.push('get1'); return 'G'; } }); return a.map(function (x) { return x; }).join() + ' ' + a.indexOf('G') + ' ' + a.join('') + ' ' + log.length; });
show('setter on index during push', function () { var log = []; var a = []; Object.defineProperty(Array.prototype, 3, { set: function (v) { log.push('proto setter ' + v); }, configurable: true }); a.length = 3; a.push('x'); delete Array.prototype[3]; return log.join() + ' len=' + a.length + ' has3=' + (3 in a); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("array_mutators_on_dense_and_sparse_arrays")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_array_search_iteration_and_callbacks(js, golden, tier):
    """CATCHES: indexOf/includes/lastIndexOf with wrong SameValueZero or fromIndex clamping, find*/every/some/forEach/map/filter/reduce/reduceRight/flat/flatMap that visit holes wrongly, keep running after a callback throws, or accept non-callable callbacks fail this."""
    code = SHOW + ARRAY_J + r"""show('indexOf/includes/lastIndexOf', function () { var a = [1, 2, NaN, 2, undefined, , -0]; return [a.indexOf(2), a.indexOf(2, 2), a.indexOf(2, -3), a.indexOf(NaN), a.includes(NaN), a.indexOf(undefined), a.includes(undefined), a.indexOf(0), a.includes(0), a.lastIndexOf(2), a.lastIndexOf(2, 2), a.lastIndexOf(-0), a.indexOf(2, 100), a.includes(1, -100), [].lastIndexOf(1), a.includes(2, Infinity), a.indexOf(1, -Infinity), a.lastIndexOf(1, -Infinity), [].indexOf(1, { valueOf: function () { throw new Error('not coerced'); } }), [].includes(1, { valueOf: function () { throw new Error('not coerced'); } }), a.indexOf(2, Infinity), a.includes(1, NaN)].join(); });
show('includes on large sparse', function () { var a = []; a[100000] = 'needle'; return a.includes('needle') + ' ' + a.indexOf('needle') + ' ' + a.lastIndexOf('needle') + ' ' + a.includes(undefined); });
show('join', function () { var a = [1, [2, 3], null, undefined, {}, 'x']; return [a.join(), a.join(undefined), a.join(''), a.join(0), [].join(), new Array(3).join('ab'), [Symbol.iterator.description].join()].join(' | '); });
show('join symbol element', function () { return [Symbol()].join(); });
show('findLast/findLastIndex', function () { var a = [1, 2, 3, 4]; var seen = []; var r = a.findLast(function (x, i, arr) { seen.push(i); return x % 2 === 1; }); return [r, a.findLastIndex(function (x) { return x > 10; }), a.findLast(function () { return false; }), seen.join(''), [, 1].findLast(function (x) { return x === undefined; }), [5, 6].findIndex(function (x, i) { return i === 1; }), [5, 6].find(function () { return this.v; }, { v: true })].join(); });
show('find on sparse visits holes', function () { var seen = []; [1, , 3].find(function (x, i) { seen.push(i + ':' + x); }); return seen.join(); });
show('reduce/reduceRight', function () { return [[1, 2, 3].reduceRight(function (a, b) { return a + '-' + b; }), [, 1, , 2, ,].reduceRight(function (a, b) { return a + b; }), [5].reduceRight(function () { return 'never'; }), [].reduceRight(function () {}, 'init'), [, , 3].reduce(function (a, b) { return a + b; }), [1, 2].reduce(function (a, b) { return a + b; }, 'p')].join(' '); });
show('reduceRight empty', function () { return [, ,].reduceRight(function () {}); });
show('reduce empty sparse', function () { return [, ,].reduce(function () {}); });
show('reduce index args', function () { var s = []; [10, 20, 30].reduce(function (acc, v, i, arr) { s.push(acc + '/' + v + '/' + i + '/' + arr.length); return acc + v; }); return s.join(' '); });
show('every/some', function () { return [[1, 2].every(function (x) { return x > 0; }), [].every(function () { return false; }), [1, 2].some(function (x) { return x > 1; }), [].some(function () { return true; }), [, ,].every(function () { return false; }), [1, 2, 3].every(function (x) { return x < 2; })].join(); });
show('flat/flatMap', function () { return [j([1, [2, [3, [4]]]].flat()), j([1, [2, [3, [4]]]].flat(2)), j([[]].flat()), j([1, , [2, , 3]].flat()), j([1, 2].flatMap(function (x) { return x === 1 ? [[x]] : x; })), j(['a b', 'c'].flatMap(function (s) { return s.split(' '); })), j([[1], [2]].flatMap(function (x, i) { return [x, this.t + i]; }, { t: 't' })), j([1, [2, [3]]].flat(Infinity)), j([[1]].flat(-Infinity)), j([[[1]]].flat(1.9))].join(' '); });
show('flat with species', function () { var a = [1, [2]]; a.constructor = { [Symbol.species]: function (n) { this.made = n; } }; var r = a.flat(); return r.made + ' ' + r[0] + ' ' + r[1]; });
show('forEach thisArg', function () { var t = { s: 0 }; [1, 2].forEach(function (x) { this.s += x; }, t); return t.s; });
show('filter with mutation', function () { var a = [1, 2, 3]; return j(a.filter(function (x, i) { if (i === 0) a[2] = 'changed'; return true; })); });
show('map on large sparse', function () { var a = []; a[1000000] = 1; var m = a.map(function (x) { return x + 1; }); return m.length + ' ' + Object.keys(m).join(); });
show('map keeps holes', function () { return j([1, , 3].map(function (x) { return x * 2; })); });
show('callbacks shrinking array', function () { var a = [1, 2, 3, 4]; var seen = []; a.map(function (x, i) { seen.push(x); if (i === 0) a.length = 2; }); var b = [1, 2, 3]; var seen2 = []; b.reduceRight(function (acc, x) { seen2.push(x); b.length = 1; return acc; }, 0); return seen.join() + ' ' + seen2.join(); });
show('non-callable callbacks', function () { var r = []; ['forEach', 'map', 'filter', 'some', 'every', 'find', 'findIndex', 'findLast', 'findLastIndex', 'reduce', 'reduceRight', 'flatMap'].forEach(function (m) { try { [1][m]({}); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.name); } }); return r.join(' '); });
show('non-callable callback messages', function () { var r = []; ['map', 'filter', 'reduce', 'reduceRight', 'find', 'some'].forEach(function (m) { try { [][m](null); } catch (e) { r.push(e.message); } }); return r.join(' | '); });
show('throwing callbacks stop', function () { var r = []; ['forEach', 'map', 'filter', 'some', 'every', 'find', 'findIndex', 'findLast', 'findLastIndex', 'flatMap'].forEach(function (m) { var calls = 0; try { [1, 2, 3][m](function () { calls++; throw new Error(m); }); } catch (e) { r.push(e.message + '=' + calls); } }); [['reduce', [1, 2, 3]], ['reduceRight', [1, 2, 3]]].forEach(function (p) { var calls = 0; try { p[1][p[0]](function () { calls++; throw new Error(p[0]); }); } catch (e) { r.push(e.message + '=' + calls); } }); return r.join(' '); });
show('Array.from mapFn throws closes', function () { var closed = false; var it = { [Symbol.iterator]: function () { return { next: function () { return { value: 1, done: false }; }, return: function () { closed = true; return {}; } }; } }; try { Array.from(it, function () { throw new Error('mapfn'); }); } catch (e) { return e.message + ' closed=' + closed; } });
show('Array.from mapFn on array-like throws', function () { return Array.from({ length: 2, 0: 'a' }, function (v, i) { if (i === 1) throw new TypeError('second'); return v; }); });
show('Array.from non-callable', function () { return Array.from([], 'x'); });
show('Array.from thisArg', function () { return Array.from([1, 2], function (x) { return x * this.m; }, { m: 10 }).join(); });
show('Array.from iterator getter', function () { var o = { get [Symbol.iterator]() { return undefined; }, length: 1, 0: 'al' }; return Array.from(o).join(); });
show('Array.from bad iterator', function () { return Array.from({ [Symbol.iterator]: 5 }); });
show('Array.from next returns primitive', function () { return Array.from({ [Symbol.iterator]: function () { return { next: function () { return 1; } }; } }); });
show('Array.from string surrogate', function () { return Array.from('a😀b\ud800').length; });
show('keys/entries/values', function () { var a = ['a', , 'c']; return [[...a.keys()].join(), JSON.stringify([...a.entries()]), [...a.values()].map(String).join(), a.values === a[Symbol.iterator], Array.prototype[Symbol.unscopables].flat, Object.getPrototypeOf(Array.prototype[Symbol.unscopables])].join(' '); });
show('array iterator mutation', function () { var a = [1, 2]; var it = a.values(); var r = [it.next().value]; a.push(3); r.push(it.next().value, it.next().value, it.next().done); a.push(4); r.push(it.next().done); return r.join(); });
show('array iterator on typed array detached', function () { var ta = new Uint8Array(2); var it = ta.values(); it.next(); $262.detachArrayBuffer(ta.buffer); return it.next(); });
show('array iterator next bad this', function () { var next = [][Symbol.iterator]().next; return next.call({}); });
show('at', function () { return [[1, 2, 3].at(0), [1, 2, 3].at(-1), [1, 2, 3].at(3), [1, 2, 3].at(-4), [1, 2, 3].at('1'), [1, 2, 3].at(NaN), [1, 2].at(1.7), [1, 2].at(-Infinity), [1, 2].at(Infinity)].join(); });
show('toString/toLocaleString', function () { var a = [1, 'b', [2, [3]]]; var r = [a.toString(), String([null]), String([undefined, null]), [1.5, 1000].toLocaleString()]; var o = { join: 5 }; r.push(Array.prototype.toString.call(o)); var t = { join: 5 }; t[Symbol.toStringTag] = 'Tagged'; r.push(Array.prototype.toString.call(t)); return r.join(' | '); });
show('array-like length getter throws', function () { return Array.prototype.map.call({ get length() { throw new SyntaxError('len'); } }, String); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("array_search_iteration_and_callbacks")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_array_sort_copy_methods_and_species(js, golden, tier):
    """CATCHES: Array sort/toSorted that is unstable, does not push undefined and holes to the end, ignores comparator results' ToNumber, swallows comparator errors, or change-array-by-copy and species-aware methods that consult Symbol.species wrongly fail this."""
    code = SHOW + ARRAY_J + r"""show('sort', function () { return [j([3, 1, 10, 2].sort()), j(['b', undefined, 'a', , 'c'].sort()), j([3, 1, 2].sort(function (a, b) { return b - a; })), j([1, 2, 3].sort(function () { return 0; })), j([2, 1].sort(undefined)), j([{ k: 1, v: 'a' }, { k: 0, v: 'b' }, { k: 1, v: 'c' }, { k: 0, v: 'd' }].sort(function (a, b) { return a.k - b.k; }).map(function (o) { return o.v; }))].join(' '); });
show('sort stability large', function () { var a = []; for (var i = 0; i < 200; i++) a.push({ k: i % 3, i: i }); a.sort(function (x, y) { return x.k - y.k; }); var ok = true; for (var k = 1; k < a.length; k++) { if (a[k - 1].k === a[k].k && a[k - 1].i > a[k].i) ok = false; } return ok + ' ' + a[0].i + ' ' + a[199].i; });
show('sort comparator returns', function () { return [j([1, 2, 3].sort(function () { return NaN; })), j([1, 2, 3].sort(function (a, b) { return a < b ? '1' : '-1'; })), j([1, 2, 3].sort(function (a, b) { return { valueOf: function () { return b - a; } }; }))].join(' '); });
show('sort comparator throws', function () { var a = [3, 2, 1]; try { a.sort(function () { throw new Error('cmp'); }); } catch (e) { return e.message + ' ' + j(a); } });
show('sort comparator bigint', function () { return [2, 1].sort(function (a, b) { return 1n; }); });
show('sort toString throws', function () { return [{ toString: function () { throw new TypeError('ts'); } }, 1].sort(); });
show('sort mixed', function () { return j([true, false, null, 10, 9, 'a', 'A', NaN, -1].sort()); });
show('sort symbols', function () { return [Symbol(), Symbol()].sort(); });
show('sort length getter', function () { var log = []; var o = { get length() { log.push('len'); return 2; }, 0: 'b', 1: 'a' }; Array.prototype.sort.call(o); return log.join() + ' ' + o[0] + o[1]; });
show('sort frozen', function () { return Object.freeze([2, 1]).sort(); });
show('sort bad comparator', function () { return [1, 2].sort(null); });
show('sort comparator undefined values', function () { var calls = 0; var a = [undefined, 3, undefined, 1]; a.sort(function (x, y) { calls++; return x - y; }); return j(a) + ' ' + (calls > 0); });
show('sort holes with proto', function () { Array.prototype[2] = 'P'; var a = [3, , , 1]; a.sort(); delete Array.prototype[2]; return j(a); });
show('toSorted/toSpliced/with/toReversed', function () { var a = [3, 1, 2]; return [j(a.toSorted()), j(a.toSorted(function (x, y) { return y - x; })), j(a), j(a.toSpliced(1, 1, 'a', 'b')), j(a.toSpliced()), j(a.toSpliced(-1)), j(a.with(-1, 'z')), j([1, , 3].toReversed()), j([, 1].toSorted()), j([1, , 2].with(1, 'h')), j(a.toSpliced(1)), j(a.toSpliced(0, Infinity, 'only'))].join(' '); });
show('with RangeError', function () { return [1, 2].with(2, 0); });
show('with neg RangeError', function () { return [1, 2].with(-3, 0); });
show('toSorted bad comparator', function () { return [].toSorted(1); });
show('change-by-copy ignores species', function () { class A extends Array {} var a = A.from([2, 1]); return [a.toSorted() instanceof A, a.toReversed() instanceof A, a.with(0, 1) instanceof A, a.toSpliced(0, 0) instanceof A, Array.isArray(a.toSorted())].join(); });
show('map species', function () { class MyArr extends Array {} var m = MyArr.from([1, 2]).map(function (x) { return x * 2; }); return (m instanceof MyArr) + ' ' + m.length + ' ' + j(m) + ' ' + (MyArr.of(1) instanceof MyArr) + ' ' + (m.filter(Boolean) instanceof MyArr) + ' ' + (m.slice() instanceof MyArr) + ' ' + (m.splice(0, 1) instanceof MyArr) + ' ' + (m.concat() instanceof MyArr) + ' ' + (m.flatMap(function (x) { return x; }) instanceof MyArr); });
show('species null/undefined', function () { var a = [1]; a.constructor = { [Symbol.species]: null }; var b = [1]; b.constructor = undefined; return Array.isArray(a.map(String)) + ' ' + Array.isArray(b.map(String)); });
show('species bad ctor', function () { var a = [1]; a.constructor = 5; return a.map(String); });
show('species non-constructor', function () { var a = [1]; a.constructor = { [Symbol.species]: function () {}.bind() }; return typeof a.map(String); });
show('species arrow', function () { var a = [1]; a.constructor = { [Symbol.species]: () => {} }; return a.map(String); });
show('species result non-writable', function () { var a = [1, 2]; a.constructor = { [Symbol.species]: function () { Object.defineProperty(this, '0', { value: 'x', writable: false, configurable: false }); } }; return a.map(function (v) { return v; }); });
show('species on non-array receiver ignored', function () { var o = { length: 1, 0: 'a', constructor: { [Symbol.species]: function () { throw new Error('never'); } } }; return Array.isArray(Array.prototype.map.call(o, String)); });
show('species cross-realm Array ctor', function () { var other = $262.createRealm().global; var a = new other.Array(1, 2); var m = Array.prototype.map.call(a, function (x) { return x; }); return (Object.getPrototypeOf(m) === Array.prototype) + ' ' + m.length; });
show('splice species', function () { var a = [1, 2, 3]; a.constructor = { [Symbol.species]: function (n) { this.len = n; } }; var r = a.splice(0, 2); return r.len + ' ' + r[0] + ' ' + r[1] + ' ' + r.length; });
show('slice species', function () { var a = [1, 2, 3]; a.constructor = { [Symbol.species]: function (n) { this.len = n; } }; var r = a.slice(1); return r.len + ' ' + r[0] + ' ' + r.length; });
show('concat spreadable getters', function () { var log = []; var o = { length: 2, 0: 'a', 1: 'b' }; Object.defineProperty(o, Symbol.isConcatSpreadable, { get: function () { log.push('spreadable?'); return true; } }); return JSON.stringify([0].concat(o)) + ' ' + log.join(); });
show('concat', function () { var a = [1, , 3]; return [j(a.concat([4], 5, [[6]])), j([].concat.call(1, 2)), j(Array.prototype.concat.call('s', 't'))].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("array_sort_copy_methods_and_species")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_string_search_slice_and_pad(js, golden, tier):
    """CATCHES: String.prototype indexOf/lastIndexOf/includes/startsWith/endsWith/slice/substring/substr/at/charAt/codePointAt/trim/pad/repeat/concat that mis-clamp positions, treat NaN wrongly, accept RegExp arguments where IsRegExp forbids them, split surrogate pairs, or skip RequireObjectCoercible fail this."""
    code = SHOW + r"""var SP = String.prototype;
show('indexOf/lastIndexOf', function () { var s = 'abcabc'; return [s.indexOf('c'), s.indexOf('c', 3), s.indexOf(''), s.indexOf('', 10), s.indexOf('x'), s.lastIndexOf('a'), s.lastIndexOf('a', 2), s.lastIndexOf('a', -5), s.lastIndexOf(''), s.lastIndexOf('c', NaN), s.lastIndexOf('', 2), 'aaa'.lastIndexOf('aa'), s.indexOf(undefined), 'undefined'.indexOf(), s.indexOf('a', -Infinity), s.lastIndexOf('c', Infinity), s.indexOf('bc', 1.9), s.lastIndexOf('abcabcd')].join(); });
show('includes/startsWith/endsWith', function () { var s = 'hello world'; return [s.includes('o w'), s.includes('o', 8), s.startsWith('world', 6), s.startsWith('h', -5), s.endsWith('hello', 5), s.endsWith('d', 100), s.endsWith(''), s.includes(''), s.startsWith('', 50), s.endsWith('h', -1), s.includes(null), 'null'.includes(null)].join(); });
show('includes regexp', function () { return 'a'.includes(/a/); });
show('startsWith regexp', function () { return 'a'.startsWith(/a/); });
show('endsWith regexp', function () { return 'a'.endsWith(/a/); });
show('regexp with match false', function () { var r = /a/; r[Symbol.match] = false; return 'x/a/y'.includes(r) + ' ' + '/a/'.startsWith(r); });
show('IsRegExp match getter', function () { var o = { [Symbol.match]: true, toString: function () { return 'o'; } }; return 'o'.endsWith(o); });
show('IsRegExp getter throws', function () { var o = { get [Symbol.match]() { throw new EvalError('match getter'); } }; return 'o'.includes(o); });
show('null this', function () { var r = []; ['indexOf', 'includes', 'startsWith', 'endsWith', 'slice', 'trim', 'at', 'padStart', 'repeat', 'normalize', 'concat', 'localeCompare', 'replace', 'match', 'search', 'split', 'replaceAll', 'matchAll', 'substring', 'substr', 'charAt', 'toLowerCase'].forEach(function (m) { try { SP[m].call(null, 'a'); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.name); } }); return r.join(' '); });
show('slice/substring/substr', function () { var s = 'abcdef'; return [s.slice(1, 3), s.slice(-2), s.slice(3, 1), s.substring(3, 1), s.substring(-1, 2), s.substring(NaN, 2), s.substr(2, 2), s.substr(-2), s.substr(1, -1), s.substr(10), s.slice(), s.substring(), s.slice(2, -2), s.slice(-Infinity, Infinity), s.substring(Infinity, -Infinity), s.substr(-Infinity, 2), s.substr(1, Infinity), s.slice(NaN)].join(','); });
show('at/charAt/charCodeAt/codePointAt', function () { var s = 'a😀'; return [s.at(0), s.at(-1).charCodeAt(0), s.at(5), s.charAt(1).length, s.charAt(9), s.charCodeAt(1), s.charCodeAt(9), s.codePointAt(1), s.codePointAt(2), s.codePointAt(9), 'abc'.at(-4), 'abc'.charAt(-1), 'abc'.charCodeAt(-1), 'abc'.at(NaN), 'abc'.charAt(1.9), '\ud800'.codePointAt(0), '\udc00\ud800'.codePointAt(0)].join(','); });
show('codePointAt bad this', function () { return SP.codePointAt.call(null, 0); });
show('trim', function () { var s = '\t\n\v\f\r         \u3000\ufeffx\u200b '; return JSON.stringify([s.trim(), s.trimStart().length, s.trimEnd().length, '\u180e'.trim().length, ' \u2028\u2029'.trim().length]); });
show('pad', function () { return ['5'.padStart(3, '0'), 'abc'.padEnd(10, '123'), 'x'.padStart(4, undefined), 'x'.padStart(-1), 'x'.padEnd(3, 'long filler'), 'x'.padStart(3, {}), 'abc'.padEnd(6, ''), escape('ab'.padStart(5, '😀')), 'x'.padEnd(2.9, '-'), 'x'.padStart(NaN, '-')].join('|'); });
show('repeat', function () { return ['ab'.repeat(3), 'x'.repeat(0), ''.repeat(5), 'a'.repeat('2'), 'a'.repeat(2.9), 'z'.repeat(NaN)].join('|'); });
show('repeat huge', function () { return 'ab'.repeat(2 ** 30); });
show('repeat negative', function () { return 'a'.repeat(-1); });
show('concat', function () { return ['a'.concat(1, null, undefined, [2, 3], {}), SP.concat.call(5, 6), 'x'.concat()].join(' '); });
show('concat symbol', function () { return 'a'.concat(Symbol()); });
show('string compare', function () { return ['a' < 'b', 'B' < 'a', 'aa' > 'a', '\ud800' > '￿', '10' < '9', '10' < 9, '' < 'a', 'a' <= 'a', '😀' > '￿'].join(); });
show('length immutable', function () { 'use strict'; var s = 'abc'; s.length = 5; });
show('string index assign strict', function () { 'use strict'; var s = 'abc'; s[0] = 'z'; });
show('string prop assign strict', function () { 'use strict'; var s = 'abc'; s.foo = 'z'; });
show('string index assign sloppy', function () { var s = 'abc'; s[0] = 'z'; s.foo = 1; return s + ' ' + s.foo; });
show('string indices', function () { var s = 'héllo'; return [s[1], s['1'], s[-1], s[1.5], s.length, s[10], 'length' in Object(s), 2 in Object(s), '2.0' in Object(s)].join(); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("string_search_slice_and_pad")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_string_replace_split_match_patterns(js, golden, tier):
    """CATCHES: replace/replaceAll substitution handling of $$, $&, $`, $', $n, $nn and $<name> (including out-of-range groups), replacer-function arguments, split limit/empty-separator/capture rules, or match/matchAll/search delegation to custom Symbol.* methods and non-global RegExp errors that deviate from the spec fail this."""
    code = SHOW + r"""var SP = String.prototype;
show('split', function () { return [JSON.stringify('a,b,c'.split(',')), JSON.stringify('a,b,c'.split(',', 2)), JSON.stringify('a,b,c'.split(',', 0)), JSON.stringify('a,b,c'.split(',', -1)), JSON.stringify('abc'.split('')), JSON.stringify(''.split('')), JSON.stringify(''.split(',')), JSON.stringify('a1b2c'.split(/\d/)), JSON.stringify('a1b2c'.split(/(\d)/)), JSON.stringify('abc'.split(/(?:)/)), JSON.stringify('test'.split(/(t)?/)), JSON.stringify('a,b'.split(',', 4294967297)), JSON.stringify('ab'.split(undefined, 1)), JSON.stringify('😀a'.split('')), JSON.stringify('aXbXc'.split('X', 2.9)), JSON.stringify('abcabc'.split('bc')), JSON.stringify('a,b,'.split(',')), JSON.stringify('ab'.split('ab')), JSON.stringify('x'.split('long separator'))].join(' '); });
show('split regex flags', function () { return [JSON.stringify('A1a2A'.split(/a/i)), JSON.stringify('a\nb'.split(/^/m)), JSON.stringify('😀😀'.split(/(?:)/u)), JSON.stringify('xay'.split(/a/y)), JSON.stringify('a1b2c3'.split(/\d/, 2)), JSON.stringify('abc'.split(/(b)|(z)/))].join(' '); });
show('split custom splitter', function () { var o = { [Symbol.split]: function (s, lim) { return 'custom:' + s + ':' + lim; } }; return 'xyz'.split(o, 3); });
show('split splitter not callable', function () { return 'xyz'.split({ [Symbol.split]: 5 }); });
show('split null this', function () { return SP.split.call(null, ','); });
show('split limit coercion order', function () { var log = []; 'a-b'.split({ toString: function () { log.push('sep'); return '-'; } }, { valueOf: function () { log.push('limit'); return 5; } }); return log.join(); });
show('replace patterns', function () { var s = 'John Smith'; return [s.replace('John', '[$&]'), s.replace('o', "$`|$'"), s.replace('Smith', '$$'), s.replace(/(\w+)\s(\w+)/, '$2, $1'), s.replace(/(\w+)\s(\w+)/, '$3$0$1'), s.replace(/(?<first>\w+) (?<last>\w+)/, '$<last> $<first> $<none>|'), s.replace(/(\w)/g, '$10'), 'abc'.replace(/(b)/, '$01$001'), 'abc'.replace('b', '$<x>'), 'aaa'.replace('a', function (m, off, str) { return '[' + m + off + str + ']'; }), 'x'.replace(/(y)?x/, function (m, g1) { return typeof g1; }), 'abc'.replace(/(?<n>b)/, function () { return JSON.stringify(arguments[arguments.length - 1]); }), 'abcdefghijkl'.replace(/(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)/, '$11-$10-$1$2-$12-$011'), 'ab'.replace(/(?<n>a)/, '$<n$<n>>')].join(' || '); });
show('replace with $ at end', function () { return ['abc'.replace('b', '$'), 'abc'.replace('b', '$x'), 'abc'.replace(/b/, '$9'), 'abc'.replace('b', '$0'), 'abc'.replace(/b/, '$<'), 'abc'.replace(/(?<g>b)/, '$<g')].join(' '); });
show('replace non-string search', function () { return ['a1b'.replace(1, 'one'), 'nullx'.replace(null, 'N'), 'aundefined'.replace(undefined, 'U'), 'abc'.replace('', '_'), 'abc'.replace('zz', 'q')].join(' '); });
show('replace replacer coercion', function () { return 'abc'.replace('b', function () { return { toString: function () { return 'OBJ'; } }; }) + ' ' + 'abc'.replace('b', 42) + ' ' + 'abc'.replace('b', null); });
show('replace replacer throws', function () { return 'abc'.replace('b', function () { throw new RangeError('replacer'); }); });
show('replaceAll', function () { return ['a.b.c'.replaceAll('.', '-'), 'aaa'.replaceAll('a', '$&$&'), 'aaa'.replaceAll('aa', 'b'), 'abc'.replaceAll('', '_'), 'xax'.replaceAll('x', function (m, o) { return o; }), 'a1b2'.replaceAll(/\d/g, '<$&>'), 'abab'.replaceAll('b', '$`'), 'xyx'.replaceAll('x', "$'"), ''.replaceAll('', 'E'), 'aaaa'.replaceAll('a', function (m, off, str) { return off + str.length; })].join(' '); });
show('replaceAll non-global regex', function () { return 'aa'.replaceAll(/a/, 'b'); });
show('replaceAll flags getter', function () { var r = /a/g; Object.defineProperty(r, 'flags', { value: 'y' }); return 'aa'.replaceAll(r, 'b'); });
show('replaceAll null flags', function () { var r = /a/g; Object.defineProperty(r, 'flags', { value: undefined }); return 'aa'.replaceAll(r, 'b'); });
show('replace custom replacer', function () { var o = { [Symbol.replace]: function (s, r) { return 'R(' + s + ',' + r + ')'; } }; return 'q'.replace(o, 'w') + ' ' + 'q'.replaceAll(o, 'w'); });
show('replace replacer not callable', function () { return 'q'.replace({ [Symbol.replace]: 'nope' }, 'w'); });
show('replace null this', function () { return SP.replace.call(undefined, 'a', 'b'); });
show('match/matchAll/search', function () { var s = 'a1b22c333'; return [JSON.stringify(s.match(/\d+/g)), s.match(/\d+/).index, s.match(/z/), JSON.stringify([...s.matchAll(/\d+/g)].map(function (m) { return m[0] + '@' + m.index; })), s.search(/b/), s.search('2'), s.search(/z/), JSON.stringify('ab'.match()), 'x.y'.search('.'), JSON.stringify([...'aXbX'.matchAll('X')].map(function (m) { return m.index; })), JSON.stringify('a+b'.match('[+]b')), 'abc'.search(), JSON.stringify('aaa'.match(/a*?/g)), JSON.stringify([...'abc'.matchAll(/(?:)/g)].map(function (m) { return m.index; }))].join(' '); });
show('match string becomes regexp', function () { return JSON.stringify('a.c'.match('.')) + ' ' + 'x'.search(null) + ' ' + 'null'.search(null); });
show('match bad pattern', function () { return 'x'.match('('); });
show('matchAll non-global', function () { return 'a'.matchAll(/a/); });
show('matchAll null flags', function () { var r = /a/g; Object.defineProperty(r, 'flags', { value: null }); return 'a'.matchAll(r); });
show('matchAll iterator protocol', function () { var it = 'a1a2'.matchAll(/a(\d)/g); var first = it.next(); var rest = [...it]; return first.value[1] + ' ' + rest.length + ' ' + rest[0][1] + ' ' + JSON.stringify(it.next()) + ' ' + Object.prototype.toString.call(it); });
show('matchAll empty matches advance', function () { return [...'😀x'.matchAll(/(?:)/gu)].map(function (m) { return m.index; }).join() + ' ' + [...'😀x'.matchAll(/(?:)/g)].map(function (m) { return m.index; }).join(); });
show('matchAll iterator next bad this', function () { var next = Object.getPrototypeOf('a'.matchAll(/a/g)).next; return next.call({}); });
show('match custom matcher', function () { return 'z'.match({ [Symbol.match]: function (s) { return 'M:' + s; } }) + ' ' + 'z'.search({ [Symbol.search]: function (s) { return 42; } }) + ' ' + 'z'.matchAll({ [Symbol.matchAll]: function () { return 'MA'; } }); });
show('match matcher not callable', function () { return 'z'.match({ [Symbol.match]: 1 }); });
show('search searcher not callable', function () { return 'z'.search({ [Symbol.search]: 1 }); });
show('match null this', function () { return SP.match.call(null, /a/); });
show('regexp exec via subclass', function () { class R extends RegExp { exec(s) { this.calls = (this.calls || 0) + 1; return super.exec(s); } } var r = new R('b', 'g'); var res = 'abcb'.replace(r, 'X'); return res + ' calls=' + r.calls + ' ' + 'abcb'.split(new R('b')).join('|'); });
show('legacy statics after replace', function () { 'xa1b2y'.replace(/([a-z])(\d)/g, '_'); return [RegExp.$1, RegExp.$2, RegExp.lastMatch, RegExp['$&'], RegExp.leftContext, RegExp.rightContext, RegExp.lastParen, RegExp.input].join(','); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("string_replace_split_match_patterns")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_string_constructor_raw_wrappers_and_iterator(js, golden, tier):
    """CATCHES: String()/new String/String.raw/fromCharCode/fromCodePoint/normalize/isWellFormed/toWellFormed/localeCompare/case mapping or the string iterator that mishandle Symbols, wrapper exotic indices, raw-array substitutions, code-point ranges, lone surrogates or Number-to-String formatting fail this."""
    code = SHOW + r"""var SP = String.prototype;
show('normalize', function () { return ['Å'.normalize() === 'Å', 'Å'.normalize('NFD').length, 'ﬁ'.normalize('NFKD'), 'x'.normalize(undefined), 'ẛ̣'.normalize('NFC').length, '한'.normalize('NFD').length, '각'.normalize('NFC').length, 'ḱ'.normalize('NFKC').length].join(); });
show('normalize bad form', function () { return 'x'.normalize('nfc'); });
show('isWellFormed/toWellFormed', function () { return ['a\ud83d'.isWellFormed(), 'a😀'.isWellFormed(), escape('\udc00x\ud800'.toWellFormed()), SP.isWellFormed.call(123), escape(SP.toWellFormed.call({ toString: function () { return 'z\ud801'; } }))].join(); });
show('localeCompare', function () { return ['a'.localeCompare('B'), 'résumé'.localeCompare('resume'), ''.localeCompare(''), '10'.localeCompare('9'), '10'.localeCompare('9', undefined, { numeric: true }), 'a'.localeCompare('A', 'en', { sensitivity: 'base' }), 'a'.localeCompare(), 'undefined'.localeCompare()].join(); });
show('toUpperCase/toLowerCase', function () { return ['ǆ'.toUpperCase(), 'ǈ'.toLowerCase(), 'Ⅻ'.toLowerCase(), '𐐀'.toLowerCase().codePointAt(0).toString(16), SP.toUpperCase.call(true), 'ﬀ'.toLocaleUpperCase(), 'İstanbul'.toLocaleLowerCase('tr'), 'ıi'.toLocaleUpperCase('tr'), 'IÍ'.toLocaleLowerCase('lt').length, 'i̇'.toLocaleUpperCase('lt').length, 'ΑΣ'.toLowerCase()].join(); });
show('toUpperCase null', function () { return SP.toUpperCase.call(undefined); });
show('String.raw', function () { return [String.raw`a\nb${1}\u{zz}`, String.raw({ raw: ['x', 'y', 'z'] }, 1, 2, 3, 4), String.raw({ raw: { length: 0 } }), String.raw({ raw: { length: 2, 0: 'p', 1: 'q' } }), String.raw({ raw: ['only'] }, 'ignored'), String.raw({ raw: { length: 3, 0: 'a', 2: 'c' } }, 1, 2), String.raw({ raw: { length: -5 } })].join(' | '); });
show('String.raw no raw', function () { return String.raw({}); });
show('String.raw null', function () { return String.raw(); });
show('fromCharCode', function () { return [String.fromCharCode(), String.fromCharCode(65, 66.9, '67'), String.fromCharCode(-1).charCodeAt(0), String.fromCharCode(0x1F600).charCodeAt(0), String.fromCharCode(0xD83D, 0xDE00) === '😀', String.fromCharCode(NaN).charCodeAt(0)].join(','); });
show('fromCodePoint', function () { return [String.fromCodePoint(), String.fromCodePoint(0x61, '98'), String.fromCodePoint(0x10FFFF).length, String.fromCodePoint(0xD800).length, String.fromCodePoint(-0).charCodeAt(0)].join(','); });
show('fromCodePoint -1', function () { return String.fromCodePoint(-1); });
show('fromCodePoint NaN', function () { return String.fromCodePoint(NaN); });
show('fromCodePoint Infinity', function () { return String.fromCodePoint(Infinity); });
show('fromCodePoint symbol', function () { return String.fromCodePoint(Symbol()); });
show('String() conversions', function () { return [String(), String(null), String(undefined), String(Symbol('d')), String(-0), String([1, [2]]), String({}), String(1n), String(1e21), String(1e-7), String(123456789012345680000), String(0.000001), String(-1e-7), String(2 ** 53), String(1.7976931348623157e308), String(5e-324), String(0.1 + 0.2), String(-1.5e-10), String(1 / 3), String(100), String(1e100), String(123e-20)].join(' '); });
show('String symbol implicit', function () { return '' + Symbol('x'); });
show('String wrapper', function () { var s = new String('ab'); s.extra = 1; return [typeof s, s.length, s[0], s[5], Object.keys(s).join(), JSON.stringify(Object.getOwnPropertyDescriptor(s, '0')), 0 in s, 5 in s, s == 'ab', s === 'ab', delete s[0], delete s.extra, Reflect.ownKeys(s).join()].join(' '); });
show('String wrapper index define', function () { var s = new String('ab'); return Reflect.defineProperty(s, '0', { value: 'z' }) + ' ' + Reflect.defineProperty(s, '0', { value: 'a' }) + ' ' + Reflect.defineProperty(s, '5', { value: 'q' }) + ' ' + s[5] + ' ' + Reflect.defineProperty(s, 'length', { value: 2 }) + ' ' + Reflect.defineProperty(s, 'length', { value: 3 }); });
show('String wrapper set index', function () { 'use strict'; var s = new String('ab'); s[0] = 'x'; });
show('String wrapper for-in', function () { var s = new String('xy'); s.p = 1; var ks = []; for (var k in s) ks.push(k); return ks.join(); });
show('String subclass', function () { class S extends String { shout() { return this.toUpperCase() + '!'; } } var s = new S('hey'); return s.shout() + ' ' + s.length + ' ' + (s instanceof String) + ' ' + JSON.stringify(s) + ' ' + Object.prototype.toString.call(s); });
show('String new.target symbol', function () { return new String(Symbol()); });
show('string iterator', function () { var it = 'a😀\ud800b'[Symbol.iterator](); var r = []; var x; while (!(x = it.next()).done) r.push(x.value.length); return r.join() + ' ' + Object.prototype.toString.call(it) + ' ' + it.next().done + ' ' + [...'\udc00😀'].length; });
show('string iterator bad this', function () { var next = ''[Symbol.iterator]().next; return next.call({}); });
show('string iterator on wrapper and null', function () { var r = [[...new String('hi')].join('-')]; try { String.prototype[Symbol.iterator].call(null); } catch (e) { r.push(e.name); } return r.join(' '); });
show('toString/valueOf bad this', function () { return SP.toString.call({}); });
show('valueOf bad this', function () { return SP.valueOf.call(1); });
show('toString on wrapper', function () { return SP.toString.call(new String('w')) + ' ' + SP.valueOf.call(Object('v')); });
show('anchor etc', function () { return ['a'.blink(), 'a'.fixed(), 'a'.italics(), 'a'.small(), 'a'.strike(), 'a'.sup(), 'a'.fontsize(), 'a'.anchor(), 'a'.link('"q"')].join(''); });
show('toLocaleString', function () { return 'abc'.toLocaleString() + ' ' + SP.toLocaleString.call(5); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("string_constructor_raw_wrappers_and_iterator")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_number_formatting_methods(js, golden, tier):
    """CATCHES: Number.prototype toFixed/toPrecision/toExponential/toString(radix)/toLocaleString/valueOf that round ties the wrong way, mis-format values around 1e21 and subnormals, check the digit range before/after NaN handling incorrectly, or accept non-Number receivers fail this."""
    code = SHOW + r"""show('toFixed', function () { return [(1.005).toFixed(2), (1.45).toFixed(1), (0.5).toFixed(0), (1.5).toFixed(0), (2.5).toFixed(0), (-1.5).toFixed(0), (-0).toFixed(2), (1e21).toFixed(2), (1e20).toFixed(2), (123.456).toFixed(), (0.000001).toFixed(7), NaN.toFixed(2), (-0.0000001).toFixed(3), (999.995).toFixed(2), (9.995).toFixed(2), (0.1).toFixed(20), (5e-324).toFixed(100).length, (1.23).toFixed(undefined), (99.99).toFixed(1), Infinity.toFixed(1), (0.05).toFixed(1), (-1e21).toFixed(1), (1.25).toFixed(1), (2 ** 53).toFixed(2), (0.000000000001).toFixed(15)].join(' '); });
show('toFixed range', function () { return (1).toFixed(101); });
show('toFixed neg range', function () { return (1).toFixed(-1); });
show('toFixed Infinity digits', function () { return (1).toFixed(Infinity); });
show('toFixed NaN with bad digits', function () { return NaN.toFixed(101); });
show('toFixed bad this', function () { return Number.prototype.toFixed.call('1', 1); });
show('toFixed wrapper this', function () { return Number.prototype.toFixed.call(new Number(2.5), 1); });
show('toPrecision', function () { return [(123.456).toPrecision(4), (0.00001234).toPrecision(2), (1234567).toPrecision(2), (1.5).toPrecision(1), (0).toPrecision(3), (-0).toPrecision(1), (1e21).toPrecision(3), (123).toPrecision(), NaN.toPrecision(2), (-Infinity).toPrecision(2), (1e-7).toPrecision(1), (123456).toPrecision(6), (999.99).toPrecision(3), (0.000001).toPrecision(1), (-123.456).toPrecision(2), (1e-6).toPrecision(2), (12.6).toPrecision(2), (5e-324).toPrecision(3), (1.7976931348623157e308).toPrecision(4), (123.456).toPrecision(100).length].join(' '); });
show('toPrecision range', function () { return (1).toPrecision(0); });
show('toPrecision 101', function () { return (1).toPrecision(101); });
show('toPrecision NaN with bad p', function () { return NaN.toPrecision(1000); });
show('toPrecision Infinity with bad p', function () { return Infinity.toPrecision(0); });
show('toExponential', function () { return [(123.456).toExponential(2), (0).toExponential(), (0).toExponential(2), (-0).toExponential(1), (1e21).toExponential(), (1.5e-7).toExponential(3), (123).toExponential(0), (12345).toExponential(), NaN.toExponential(200), Infinity.toExponential(1), (-Infinity).toExponential(), (1.25).toExponential(1), (1.35).toExponential(1), (5e-324).toExponential(), (1.7976931348623157e308).toExponential(5), (0.1).toExponential(20), (-6.02e23).toExponential(2), (9.999).toExponential(2), (1).toExponential(undefined), (25).toExponential(0)].join(' '); });
show('toExponential range', function () { return (1).toExponential(101); });
show('toExponential -1', function () { return (1).toExponential(-1); });
show('toExponential coercion before NaN check', function () { var log = []; NaN.toExponential({ valueOf: function () { log.push('coerced'); return 1; } }); return log.join(); });
show('toString radix', function () { return [(255).toString(16), (255).toString(2), (-255).toString(36), (0.5).toString(2), (3.75).toString(8), (0).toString(7), NaN.toString(16), (-Infinity).toString(2), (0.1).toString(3).slice(0, 12), (2 ** 60).toString(32), (-0).toString(2), (35).toString(36), (1.5).toString(10), (1e-7).toString(2).slice(0, 15), (255).toString(undefined), (-0.5).toString(16), (1e21).toString(10), (10).toString(36.9)].join(' '); });
show('toString radix 1', function () { return (1).toString(1); });
show('toString radix 37', function () { return (1).toString(37); });
show('toString radix NaN', function () { return (10).toString(NaN); });
show('toString bad this', function () { return Number.prototype.toString.call({}); });
show('toLocaleString', function () { return [(1234567.891).toLocaleString(), (1234.5).toLocaleString('de-DE'), (0.5).toLocaleString('en', { style: 'percent' }), (12).toLocaleString('en', { minimumFractionDigits: 2 }), NaN.toLocaleString(), (-0).toLocaleString()].join(' '); });
show('toLocaleString bad this', function () { return Number.prototype.toLocaleString.call('5'); });
show('valueOf', function () { return [new Number(5).valueOf(), Number.prototype.valueOf.call(7), Number.prototype.valueOf()].join(); });
show('valueOf bad', function () { return Number.prototype.valueOf.call('7'); });
show('number literal formatting', function () { return [0.1, 1e21, 1e-7, 123e-20, 2 ** -1074, 4.35, 0.000001, 1.0, -0, 0x10, 0o17, 0b101, 1_000_000, .5e1, 5e-7].map(String).join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("number_formatting_methods")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_number_conversion_and_parse_globals(js, golden, tier):
    """CATCHES: ToNumber string parsing (hex/octal/binary prefixes, whitespace, Infinity spelling, separators), Number statics, parseInt radix wrapping and prefix rules, parseFloat longest-prefix scanning, or isNaN/isFinite coercion that deviate from the spec fail this."""
    code = SHOW + r"""function z(x) { return Object.is(x, -0) ? '-0' : String(x); }
show('Number()', function () { return [Number(), Number(undefined), Number(null), Number(''), Number(' 12 '), Number('0x1F'), Number('0b101'), Number('0o17'), Number('0X'), Number('1_000'), Number('Infinity'), Number('-Infinity'), Number('+Infinity'), Number('infinity'), Number('-0'), Number('1e3'), Number('.5'), Number('5.'), Number('.'), Number('1e'), Number('-0x10'), Number(true), Number([]), Number([7]), Number([1, 2]), Number({}), Number(10n), Number(2n ** 64n), Number('12px'), Number(new Date(5)), Number('00012'), Number('1e1000'), Number('-1e-1000'), Number('\u00a0 42 \ufeff'), Number('0B11'), Number('0O7'), Number('0b2'), Number('1__0'), Number(-2n)].map(z).join(' '); });
show('Number symbol', function () { return Number(Symbol()); });
show('new Number', function () { var n = new Number(3); return typeof n + ' ' + (n + 1) + ' ' + (n == 3) + ' ' + (n === 3) + ' ' + typeof new Number() + ' ' + new Number(5n).valueOf(); });
show('Number subclass', function () { class N extends Number { twice() { return this * 2; } } var n = new N(21); return n.twice() + ' ' + (n instanceof Number) + ' ' + Object.prototype.toString.call(n); });
show('Number statics', function () { return [Number.isInteger(5), Number.isInteger(5.5), Number.isInteger('5'), Number.isInteger(Infinity), Number.isSafeInteger(2 ** 53), Number.isSafeInteger(2 ** 53 - 1), Number.isSafeInteger(-(2 ** 53 - 1)), Number.isSafeInteger(1.5), Number.isFinite('1'), Number.isFinite(1), Number.isNaN('NaN'), Number.isNaN(NaN), Number.isInteger(-0), Number.EPSILON === 2 ** -52, Number.MAX_SAFE_INTEGER, Number.MIN_SAFE_INTEGER, Number.MAX_VALUE, Number.MIN_VALUE, Number.parseInt === parseInt, Number.parseFloat === parseFloat, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.isNaN(), Number.isSafeInteger(new Number(1))].join(' '); });
show('parseInt', function () { return [parseInt('42px'), parseInt('  -0x1A'), parseInt('0x'), parseInt('101', 2), parseInt('z', 36), parseInt('Z', 36), parseInt('10', 37), parseInt('10', 1), parseInt('10', 0), parseInt('10', 4294967298), parseInt('10', -4294967294), parseInt('0x10', 16), parseInt('0x10', 10), parseInt(''), parseInt('-'), parseInt('-0'), parseInt('1e3'), parseInt(0.0000005), parseInt(1e21), parseInt('  \ufeff7'), parseInt('+12'), parseInt('٣'), parseInt(null, 36), parseInt('11', Infinity), parseInt('11', NaN), parseInt('11', '2'), parseInt('0b11'), parseInt('0o7'), parseInt('-FF', 16), parseInt('+0x10'), parseInt('9007199254740993'), parseInt('\n\t 77 '), parseInt('12', 2), parseInt('ff', 16.9), parseInt({ toString: function () { return '31'; } }, { valueOf: function () { return 8; } })].map(z).join(' '); });
show('parseInt coercion order', function () { var log = []; parseInt({ toString: function () { log.push('str'); return '1'; } }, { valueOf: function () { log.push('radix'); return 10; } }); return log.join(); });
show('parseFloat', function () { return [parseFloat('3.14abc'), parseFloat('  -.5e-3x'), parseFloat('Infinityx'), parseFloat('-Infinity'), parseFloat('+Infinity'), parseFloat('infinity'), parseFloat('1e'), parseFloat('1e+'), parseFloat('1.e5'), parseFloat('.e5'), parseFloat('0x10'), parseFloat(''), parseFloat('-'), parseFloat('-0'), parseFloat('1_0'), parseFloat(' 1.5'), parseFloat('1.5.5'), parseFloat('5E2'), parseFloat('-.'), parseFloat([' 7 ']), parseFloat('1e1000'), parseFloat('.0001e-2'), parseFloat('+.5'), parseFloat('1e-5x'), parseFloat('\u2028 9'), parseFloat('0.0000001'), parseFloat('123456789012345678'), parseFloat('-0.0e0'), parseFloat('Infin')].map(z).join(' '); });
show('parseFloat symbol', function () { return parseFloat(Symbol()); });
show('isNaN/isFinite', function () { return [isNaN('abc'), isNaN(''), isNaN(undefined), isNaN(null), isFinite('12'), isFinite(Infinity), isFinite(null), isFinite('1e400'), isNaN({ valueOf: function () { return 1; } }), isFinite('0x10'), isNaN(new Date(NaN))].join(); });
show('isNaN symbol', function () { return isNaN(Symbol()); });
show('isFinite bigint', function () { return isFinite(1n); });
show('global function shapes', function () { return ['parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURI', 'decodeURI', 'encodeURIComponent', 'decodeURIComponent', 'escape', 'unescape', 'eval'].map(function (n) { var d = Object.getOwnPropertyDescriptor(globalThis, n); return n + '/' + globalThis[n].length + '/' + [d.writable, d.enumerable, d.configurable].map(Number).join(''); }).join(' '); });
show('global functions not constructors', function () { var r = []; [parseInt, isNaN, escape, encodeURI].forEach(function (f) { try { new f('1'); r.push('constructed'); } catch (e) { r.push(e.name); } }); return r.join(); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("number_conversion_and_parse_globals")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_uri_codecs_and_escape(js, golden, tier):
    """CATCHES: encodeURI/encodeURIComponent/decodeURI/decodeURIComponent that encode the wrong reserved sets, accept lone surrogates, overlong or out-of-range UTF-8 sequences, or decode reserved escapes in decodeURI, and escape/unescape that mishandle %uXXXX and short escapes fail this."""
    code = SHOW + r"""show('URI encode', function () { return [encodeURIComponent('a b&c=d/é😀'), encodeURI('http://x.y/a b?q=1&r=é#h'), encodeURIComponent("-_.!~*'()"), encodeURI(';,/?:@&=+$#'), encodeURIComponent(';,/?:@&=+$#'), encodeURI('[]{}|^`"<>\\'), encodeURIComponent('\u0000\u007f\u0080߿ࠀ￿'), encodeURI(), encodeURIComponent(12.5), encodeURI('%')].join(' | '); });
show('URI encode lone surrogate', function () { return encodeURIComponent('\ud800'); });
show('URI encode lone low', function () { return encodeURI('a\udc00'); });
show('URI encode reversed pair', function () { return encodeURIComponent('\udc00\ud800'); });
show('URI decode', function () { return [decodeURIComponent('a%20b%26%C3%A9%F0%9F%98%80'), decodeURI('%3B%2F%3F%3A%40%26%3D%2B%24%2C%23%20'), decodeURIComponent('%3B%2F%23'), decodeURI('%e2%82%ac'), decodeURIComponent('no escapes'), decodeURI('%41%42'), decodeURIComponent('%F4%8F%BF%BF').length, decodeURIComponent('%00').charCodeAt(0), decodeURI('%2f%2F'), decodeURIComponent('%7f%7F')].join(' | '); });
show('URI decode bad', function () { var r = []; ['%', '%2', '%zz', '%C3', '%C3%28', '%FF', '%ED%A0%80', '%F4%90%80%80', '%C0%AF', '%E0%80%AF', '%80', '%F0%9F%98', '%E2%82', '%C3%A9%'].forEach(function (s) { try { decodeURIComponent(s); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' '); });
show('URI decode bad via decodeURI', function () { return decodeURI('%E0%A4%A'); });
show('URI error class', function () { try { decodeURI('%'); } catch (e) { return [e instanceof URIError, e.constructor === URIError, Object.getPrototypeOf(URIError) === Error, String(e)].join(); } });
show('escape/unescape', function () { return [escape('a b+c/@*_-.éĀ😀~!'), unescape('%41%u0042%zz%u12%4'), unescape('%u00E9%E9'), unescape(escape('héllo wörld 😀')), escape(''), unescape('%'), unescape('%u'), unescape('%u004'), unescape('abc%'), unescape('%U0041'), escape('ÿĀ'), escape(undefined), unescape(null)].join(' | '); });
show('escape symbol', function () { return escape(Symbol()); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("uri_codecs_and_escape")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_math_functions(js, golden, tier):
    """CATCHES: Math functions with wrong signed-zero, NaN and Infinity handling (round ties, sign, atanh, atan2, pow with base 1), wrong fround/f16round/clz32/imul integer conversions, hypot/max/min that stop coercing early, or a sumPrecise that is not correctly rounded or skips iterator closing fail this."""
    code = SHOW + r"""function z(x) { return Object.is(x, -0) ? '-0' : typeof x === 'number' && isFinite(x) && x !== Math.trunc(x) ? x.toPrecision(12) : String(x); }
function each(f, xs) { return xs.map(function (x) { return z(f(x)); }).join(' '); }
var M = Math;
show('round', function () { return each(M.round, [0.5, -0.5, 1.5, -1.5, 2.5, -2.5, 0.49999999999999994, -0.49999999999999994, 4503599627370495.5, -4503599627370497, NaN, Infinity, -0, 0, -0.2, 1e300, '2.5', -Infinity]); });
show('sign/trunc/floor/ceil', function () { return [each(M.sign, [-3, 3, 0, -0, NaN, '-2', Infinity]), each(M.trunc, [-1.9, 1.9, -0.5, NaN, Infinity]), each(M.floor, [-0.5, 0.5, -0, -1.5]), each(M.ceil, [-0.5, 0.5, -0, 1.2])].join(' | '); });
show('sqrt/cbrt', function () { return [each(M.sqrt, [4, -1, -0, Infinity, 2, NaN]), each(M.cbrt, [27, -8, -0, 2, -Infinity])].join(' | '); });
show('exp/log family', function () { return [each(M.exp, [0, 1, -Infinity, Infinity, NaN]), each(M.expm1, [0, -0, 1e-10, -Infinity]), each(M.log, [1, 0, -1, Math.E, -0]), each(M.log1p, [0, -1, -2, 1e-10, -0]), each(M.log2, [8, 0.5, 3, 0]), each(M.log10, [1000, 0.001, 2, -1])].join(' | '); });
show('trig', function () { return [each(M.sin, [0, -0, Infinity]), each(M.cos, [0, NaN]), each(M.tan, [-0]), each(M.asin, [1, 2, -0]), each(M.acos, [1, -1, 2]), each(M.atan, [Infinity, -0, 1]), each(M.sinh, [-0, 1]), each(M.cosh, [0, -Infinity]), each(M.tanh, [Infinity, -0, -Infinity]), each(M.asinh, [-0, 1]), each(M.acosh, [1, 0.5, Infinity]), each(M.atanh, [0, -0, 0.25, -0.25, 0.5, -0.5, 0.9, 1, -1, 2, NaN])].join(' | '); });
show('atan2', function () { return [M.atan2(0, -0), M.atan2(-0, -0), M.atan2(-0, 0), M.atan2(1, 1), M.atan2(Infinity, -Infinity), M.atan2(NaN, 1), M.atan2(1, 0), M.atan2(-1, Infinity)].map(z).join(' '); });
show('pow', function () { return [M.pow(2, 10), M.pow(NaN, 0), M.pow(1, Infinity), M.pow(-1, -Infinity), M.pow(1, NaN), M.pow(0, -1), M.pow(-0, -1), M.pow(-0, -2), M.pow(-8, 1 / 3), M.pow(2, -1074), M.pow(-2, 3), M.pow(-0, 3), M.pow(-Infinity, 3), M.pow(-Infinity, 2), M.pow(0.5, -Infinity), (-2) ** 2, 2 ** 0.5 === M.SQRT2].map(z).join(' '); });
show('fround/clz32/imul', function () { return [each(M.fround, [5.5, 5.05, 2 ** 128, -0, NaN, 1e-46, 16777217, 3.4028235677973366e38]), each(M.clz32, [0, 1, -1, 0.5, 2 ** 32, 2 ** 31, NaN, '8', -0, Infinity]), [M.imul(2, 4), M.imul(-1, 8), M.imul(0xffffffff, 5), M.imul(2 ** 31, 2), M.imul(3.9, 2.1), M.imul(), M.imul(0x7fffffff, 0x7fffffff)].join(' ')].join(' | '); });
show('f16round', function () { return each(M.f16round, [1.337, 65504, 65520, 1e-8, -0, 5e-8, NaN, -Infinity, 65519.99]); });
show('hypot', function () { return [M.hypot(), M.hypot(3, 4), M.hypot(3, 4, 12), M.hypot(NaN, Infinity), M.hypot(NaN, 1), M.hypot(-Infinity), M.hypot(-0), M.hypot('3', [4]), M.hypot(-0, -0), M.hypot(5)].map(z).join(' '); });
show('hypot coercion order', function () { var log = []; try { M.hypot({ valueOf: function () { log.push('a'); return Infinity; } }, { valueOf: function () { log.push('b'); throw new Error('b threw'); } }); } catch (e) { return log.join() + ' ' + e.message; } });
show('max/min', function () { return [M.max(), M.min(), M.max(1, 3, 2), M.min(1, 3, 2), M.max(-0, 0), M.max(0, -0), M.min(0, -0), M.min(-0, 0), M.max(1, NaN, 3), M.min(NaN, 1), M.max('10', 9), M.min([2], [1]), M.max(-Infinity), M.min(Infinity, -0)].map(z).join(' '); });
show('max coerces all', function () { var log = []; var r = M.max({ valueOf: function () { log.push(1); return NaN; } }, { valueOf: function () { log.push(2); return 5; } }); return r + ' ' + log.join(); });
show('min coerces all', function () { var log = []; var r = M.min({ valueOf: function () { log.push(1); return NaN; } }, { valueOf: function () { log.push(2); return 5; } }); return r + ' ' + log.join(); });
show('sumPrecise', function () { return [M.sumPrecise([1, 2, 3]), M.sumPrecise([0.1, 0.2]), M.sumPrecise([1e20, 0.1, -1e20]), M.sumPrecise([]), M.sumPrecise([-0, -0]), M.sumPrecise([-0, 0]), M.sumPrecise([Infinity, 1]), M.sumPrecise([Infinity, -Infinity]), M.sumPrecise([-Infinity, 5]), M.sumPrecise([NaN, 1]), M.sumPrecise([1.7976931348623157e308, 1.7976931348623157e308]), M.sumPrecise([1.7976931348623157e308, 1.7976931348623157e308, -1.7976931348623157e308]), M.sumPrecise(new Set([0.5, 0.25])), M.sumPrecise([1, 1e-16, 1e-16]), M.sumPrecise([2 ** 53, 1, 1]), M.sumPrecise([2 ** 53, 1]), M.sumPrecise([3, -3]), M.sumPrecise([-1.7976931348623157e308, -1.7976931348623157e308]), M.sumPrecise([5e-324, 5e-324]), M.sumPrecise([1, 2 ** -53, 2 ** -106])].map(function (x) { return Object.is(x, -0) ? '-0' : String(x); }).join(' '); });
show('sumPrecise non-number', function () { return M.sumPrecise([1, '2']); });
show('sumPrecise closes', function () { var closed = false; var it = { [Symbol.iterator]: function () { var n = 0; return { next: function () { n++; return { value: n === 1 ? 1 : 2n, done: false }; }, return: function () { closed = true; return {}; } }; } }; try { M.sumPrecise(it); } catch (e) { return e.name + ' closed=' + closed; } });
show('sumPrecise non-iterable', function () { return M.sumPrecise(5); });
show('random range', function () { var ok = true; for (var i = 0; i < 50; i++) { var r = M.random(); if (!(r >= 0 && r < 1)) ok = false; } return ok + ' ' + typeof M.random(); });
show('constants', function () { return [M.E, M.LN10, M.LN2, M.LOG10E, M.LOG2E, M.PI, M.SQRT1_2, M.SQRT2, M[Symbol.toStringTag], JSON.stringify(Object.getOwnPropertyDescriptor(M, 'PI'))].join(' '); });
show('abs', function () { return each(M.abs, [-5, -0, '-3', null, undefined, -Infinity, [-2], {}]); });
show('bigint arg', function () { return M.abs(1n); });
show('symbol arg', function () { return M.max(1, Symbol()); });
show('function lengths', function () { return ['abs', 'max', 'min', 'hypot', 'pow', 'atan2', 'imul', 'random', 'sumPrecise', 'f16round', 'clz32'].map(function (n) { return n + M[n].length; }).join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("math_functions")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_symbol_registry_and_wrappers(js, golden, tier):
    """CATCHES: Symbol implementations whose registry (Symbol.for/keyFor) is not shared or accepts non-symbols, whose description/toString/valueOf/@@toPrimitive accept wrong receivers, that allow `new Symbol`, implicit string/number conversion, or expose writable well-known symbols fail this."""
    code = SHOW + r"""show('Symbol basics', function () { var a = Symbol('desc'), b = Symbol(), c = Symbol(undefined), d = Symbol(null), e = Symbol(''); return [a.toString(), b.toString(), String(c), d.description, JSON.stringify(e.description), b.description, c.description, typeof a, a === Symbol('desc'), Symbol.length, Symbol.name, e.toString()].join(' '); });
show('Symbol desc coercion', function () { return Symbol({ toString: function () { return 'obj'; } }).description + ' ' + Symbol(12).description; });
show('Symbol desc from symbol', function () { return Symbol(Symbol('inner')); });
show('new Symbol', function () { return new Symbol(); });
show('Symbol.for/keyFor', function () { var a = Symbol.for('app'); var b = Symbol.for('app'); return [a === b, Symbol.keyFor(a), Symbol.keyFor(Symbol('app')), Symbol.keyFor(Symbol.iterator), Symbol.for().toString(), Symbol.keyFor(Symbol.for(undefined)), Symbol.for(1) === Symbol.for('1'), Symbol.for('app').description].join(' '); });
show('Symbol.for cross realm', function () { var other = $262.createRealm().global; return (other.Symbol.for('shared') === Symbol.for('shared')) + ' ' + (other.Symbol.iterator === Symbol.iterator) + ' ' + other.Symbol.keyFor(Symbol.for('shared')); });
show('keyFor non-symbol', function () { return Symbol.keyFor('app'); });
show('well-known', function () { return ['asyncIterator', 'hasInstance', 'isConcatSpreadable', 'iterator', 'match', 'matchAll', 'replace', 'search', 'species', 'split', 'toPrimitive', 'toStringTag', 'unscopables', 'dispose', 'asyncDispose'].map(function (k) { var d = Object.getOwnPropertyDescriptor(Symbol, k); return Symbol[k].description + (d.writable || d.configurable || d.enumerable ? '!' : ''); }).join(' '); });
show('wrapper', function () { var s = Symbol('w'); var o = Object(s); return [typeof o, o.valueOf() === s, o.toString(), o.description, o == s, Object.prototype.toString.call(o), o[Symbol.toPrimitive]('default') === s, Symbol.prototype[Symbol.toStringTag], o instanceof Symbol].join(' '); });
show('toString bad this', function () { return Symbol.prototype.toString.call('x'); });
show('toString bad object this', function () { return Symbol.prototype.toString.call({}); });
show('valueOf bad this', function () { return Symbol.prototype.valueOf.call(1); });
show('valueOf bad object', function () { return Symbol.prototype.valueOf.call(new Number(1)); });
show('description getter bad this', function () { return Object.getOwnPropertyDescriptor(Symbol.prototype, 'description').get.call({}); });
show('description getter on wrapper', function () { return Object.getOwnPropertyDescriptor(Symbol.prototype, 'description').get.call(Object(Symbol('wd'))); });
show('toPrimitive bad this', function () { return Symbol.prototype[Symbol.toPrimitive].call(1); });
show('toPrimitive descriptor', function () { var d = Object.getOwnPropertyDescriptor(Symbol.prototype, Symbol.toPrimitive); return [d.writable, d.enumerable, d.configurable, d.value.name, d.value.length].join(); });
show('symbol arithmetic', function () { return Symbol() + 1; });
show('symbol template', function () { return `${Symbol('t')}`; });
show('symbol unary plus', function () { return +Symbol(); });
show('symbol as key', function () { var s = Symbol('k'); var o = {}; o[s] = 1; o[Object(s)] = 2; return o[s] + ' ' + Object.getOwnPropertySymbols(o).length + ' ' + JSON.stringify(o) + ' ' + (s in o); });
show('symbol equality', function () { var s = Symbol(); return [s == Object(s), Object(s) == Object(s), s == 'Symbol()', !!s, Object(s) === Object(s)].join(); });
show('symbol property on primitive', function () { var s = Symbol('p'); s.extra = 1; return [s.extra, s.description, s.constructor === Symbol, 'description' in Object(s)].join(); });
show('symbols in for-in and keys', function () { var o = { a: 1, [Symbol('hidden')]: 2 }; var ks = []; for (var k in o) ks.push(k); return ks.join() + ' ' + Object.keys(o).length + ' ' + Reflect.ownKeys(o).length; });
show('Boolean', function () { var r = [Boolean(), Boolean(''), Boolean('0'), Boolean(NaN), Boolean({}), Boolean([]), Boolean(0n), Boolean(Symbol()), new Boolean(false) ? 'obj-truthy' : 'falsy', typeof new Boolean(1), (true).toString(), new Boolean(true).valueOf(), Boolean.prototype.valueOf(), Boolean.prototype.toString.call(false), Boolean(-0), Boolean(' '), Boolean(document_all_like())]; function document_all_like() { return $262.IsHTMLDDA; } return r.join(' '); });
show('Boolean bad this', function () { return Boolean.prototype.toString.call(1); });
show('Boolean bad object this', function () { return Boolean.prototype.valueOf.call({}); });
show('Boolean subclass', function () { class B extends Boolean {} var b = new B(false); return (b instanceof Boolean) + ' ' + b.valueOf() + ' ' + Object.prototype.toString.call(b); });
show('IsHTMLDDA', function () { var dda = $262.IsHTMLDDA; return [typeof dda, dda == null, dda == undefined, dda === undefined, !dda, dda ? 'truthy' : 'falsy', dda ?? 'nullish', typeof dda()].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("symbol_registry_and_wrappers")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_bigint_builtins_and_operators(js, golden, tier):
    """CATCHES: BigInt()/asIntN/asUintN/toString/toLocaleString that convert non-integral Numbers, misparse string prefixes, wrap bit widths wrongly, or BigInt arithmetic, shifts, comparisons with Numbers/strings and mixed-type errors that deviate from the spec fail this."""
    code = SHOW + r"""show('BigInt()', function () { return [BigInt(10), BigInt('0x1f'), BigInt('0b11'), BigInt('0o7'), BigInt(' 42 '), BigInt(''), BigInt(true), BigInt(false), BigInt(-0), BigInt(2 ** 60), BigInt(Number.MAX_SAFE_INTEGER) + 2n, BigInt({ valueOf: function () { return 7; } }), BigInt('-12'), BigInt(new Number(3)), BigInt(Object(5n)), BigInt('  0  '), BigInt('+9'), BigInt(1e21), BigInt({ [Symbol.toPrimitive]: function () { return '77'; } })].join(' '); });
show('BigInt bad string', function () { return BigInt('1.5'); });
show('BigInt bad string 2', function () { return BigInt('12n'); });
show('BigInt -0x', function () { return BigInt('-0x10'); });
show('BigInt 1e3 string', function () { return BigInt('1e3'); });
show('BigInt fraction', function () { return BigInt(1.5); });
show('BigInt NaN', function () { return BigInt(NaN); });
show('BigInt Infinity', function () { return BigInt(Infinity); });
show('BigInt undefined', function () { return BigInt(undefined); });
show('BigInt null', function () { return BigInt(null); });
show('BigInt symbol', function () { return BigInt(Symbol()); });
show('new BigInt', function () { return new BigInt(1); });
show('asIntN/asUintN', function () { return [BigInt.asIntN(8, 255n), BigInt.asIntN(8, 128n), BigInt.asIntN(8, -129n), BigInt.asUintN(8, -1n), BigInt.asUintN(8, 256n), BigInt.asIntN(0, 5n), BigInt.asUintN(0, 5n), BigInt.asIntN(64, 2n ** 63n), BigInt.asUintN(64, -1n), BigInt.asIntN(1, 1n), BigInt.asUintN(200, -1n).toString(16).length, BigInt.asIntN(65, 2n ** 64n), BigInt.asIntN('3', '7'), BigInt.asUintN(3, true), BigInt.asIntN(128, -(2n ** 127n)), BigInt.asUintN(1, 3n)].join(' '); });
show('asIntN bad bits', function () { return BigInt.asIntN(-1, 1n); });
show('asUintN huge bits', function () { return BigInt.asUintN(2 ** 53, 1n); });
show('asIntN number', function () { return BigInt.asIntN(8, 1); });
show('asIntN bits coercion first', function () { var log = []; try { BigInt.asIntN({ valueOf: function () { log.push('bits'); return 8; } }, { valueOf: function () { log.push('value'); return 1; } }); } catch (e) { return log.join() + ' ' + e.name; } });
show('asIntN huge bits', function () { return [BigInt.asIntN(2 ** 27, 5n), BigInt.asUintN(2 ** 27, 7n), BigInt.asIntN(2 ** 30, -3n)].join(); });
show('asUintN huge bits negative', function () { return BigInt.asUintN(2 ** 30, -1n); });
show('toString radix', function () { return [(255n).toString(16), (-255n).toString(2), (0n).toString(36), (2n ** 100n).toString(36), (10n).toString(), BigInt.prototype.toString.call(Object(5n), 7), (-1n).toString(undefined), (35n).toString(36.5)].join(' '); });
show('toString bad radix', function () { return (1n).toString(37); });
show('toString radix 0', function () { return (1n).toString(0); });
show('toString bad this', function () { return BigInt.prototype.toString.call(1); });
show('toString bad obj this', function () { return BigInt.prototype.toString.call({}); });
show('valueOf', function () { return typeof BigInt.prototype.valueOf.call(Object(3n)) + ' ' + (3n).valueOf(); });
show('valueOf bad', function () { return BigInt.prototype.valueOf.call('3'); });
show('valueOf bad object', function () { return BigInt.prototype.valueOf.call(new Number(3)); });
show('toLocaleString', function () { return (1234567n).toLocaleString() + ' ' + (1234567n).toLocaleString('de') + ' ' + (-5n).toLocaleString('en'); });
show('toLocaleString bad', function () { return BigInt.prototype.toLocaleString.call(5); });
show('arith', function () { return [2n ** 64n, -7n / 2n, -7n % 2n, 7n % -2n, 5n << 3n, -9n >> 1n, 5n & 3n, 5n | 3n, 5n ^ 3n, ~5n, -(-3n), 10n ** 0n, 0n ** 0n, (-2n) ** 3n, 1n << -1n, (-1n) >> 100n, -5n & 0xffn, -1n | 0n, (2n ** 70n) / 3n, -(2n ** 70n) % 7n, 1n << 100n >> 99n].join(' '); });
show('div zero', function () { return 1n / 0n; });
show('mod zero', function () { return 1n % 0n; });
show('neg exp', function () { return 2n ** -1n; });
show('unsigned shift', function () { return 1n >>> 0n; });
show('unary plus', function () { return +1n; });
show('mix', function () { return 1n + 1; });
show('mix compound', function () { var x = 1n; x *= 2; return x; });
show('compare', function () { return [1n < 2, 2n > 1.5, 1n == 1, 1n === 1, 1n == '1', 10n > '9', 1n < 'x', 0n == '', 1n == true, 2n ** 64n > Infinity, -1n < -Infinity, 1n < NaN, 9007199254740993n > 9007199254740992, [1n, -1, 0.5, 0n].sort(function (a, b) { return a < b ? -1 : a > b ? 1 : 0; }).join(), 1n == 1.5, 2n > '1.5', 1n != Symbol.iterator.description, 0n === -0n, Object.is(0n, -0n)].join(' '); });
show('inc/dec', function () { var a = 1n; a++; ++a; a--; var b = 5n; b -= 7n; return a + ' ' + typeof a + ' ' + b; });
show('bigint truthiness', function () { return [!!0n, !!1n, 0n ? 'y' : 'n', typeof Object(1n), 0n || 'fallback', 1n && 'and'].join(); });
show('bigint to number ops', function () { return Math.max(1n); });
show('bigint string concat', function () { return 1n + 'x' + `${2n}` + String(-3n) + [4n]; });
show('bigint keys', function () { var o = {}; o[1n] = 'one'; return Object.keys(o) + ' ' + o['1']; });
show('bigint typeof and wrappers', function () { var w = Object(7n); return [typeof w, w + 1n, w == 7n, w === 7n, Object.prototype.toString.call(w), JSON.stringify(Object.getOwnPropertyNames(BigInt).sort())].join(' '); });
show('bigint literal radixes', function () { return [0x1Fn, 0o17n, 0b101n, 1_000n, 0n, 18446744073709551616n, 0xFFFF_FFFF_FFFF_FFFF_FFn].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("bigint_builtins_and_operators")
    assert (r.returncode, r.stderr) == (0, b"")


FN_DECLS = r"""function decl(a, b /* c */) { return a + b; }
var expr = function named(x) { return x; };
var anon = function () {};
var arrow = (a, b) => a * b;
var arrow1 = x => x;
async function af() { await 1; }
var aarrow = async (x) => x;
function* gen() { yield 1; }
async function* agen() {}
class K { constructor(v) { this.v = v; } method() { return 1; } static st() {} get g() { return 1; } set g(v) {} *gm() {} async am() {} async *agm() {} ['comp' + 'uted']() {} #priv() {} static #sp() {} }
class Empty {}
class Derived extends K {}
var o = { m() {}, get acc() { return 1; }, set acc(v) {}, [Symbol.iterator]() {}, 'quoted key'() {}, 42() {}, prop: function () {}, arrowProp: () => 1 };
"""


@pytest.mark.parametrize("tier", TIERS)
def test_function_to_string_and_names(js, golden, tier):
    """CATCHES: Function.prototype.toString that does not return the exact source slice for declarations, expressions, arrows, async/generator functions, class bodies, methods, accessors and computed keys, the NativeFunction form for built-ins/bound/proxies, or the synthesized source of Function-constructor functions, and wrong `name` inference fail this."""
    code = SHOW + FN_DECLS + r"""show('decl', function () { return decl.toString(); });
show('expr', function () { return expr.toString() + ' | ' + anon.toString(); });
show('arrows', function () { return arrow.toString() + ' | ' + arrow1.toString() + ' | ' + aarrow.toString(); });
show('async/gen', function () { return [af, gen, agen].map(String).join(' | '); });
show('class', function () { return Empty.toString() + ' | ' + Derived.toString(); });
show('class full', function () { return K.toString(); });
show('class expression', function () { var C = class Named { x = 1; }; var D = class {}; return C.toString() + ' | ' + D.toString() + ' | ' + C.name + ' | ' + D.name; });
show('class methods', function () { var p = K.prototype; return [p.method, K.st, Object.getOwnPropertyDescriptor(p, 'g').get, Object.getOwnPropertyDescriptor(p, 'g').set, p.gm, p.am, p.agm, p.computed].map(String).join(' | '); });
show('object methods', function () { var d = Object.getOwnPropertyDescriptor(o, 'acc'); return [o.m, d.get, d.set, o[Symbol.iterator], o['quoted key'], o[42], o.prop, o.arrowProp].map(String).join(' | '); });
show('natives', function () { return [Math.max, Array.prototype.push, Object.getOwnPropertyDescriptor(Map.prototype, 'size').get, Symbol, Function.prototype, Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get, Array.prototype[Symbol.iterator], Object.getOwnPropertyDescriptor(Symbol.prototype, Symbol.toPrimitive).value].map(String).join(' | '); });
show('bound', function () { return [decl.bind(null), Math.max.bind(), K.bind()].map(String).join(' | '); });
show('proxy', function () { return Function.prototype.toString.call(new Proxy(decl, {})) + ' | ' + Function.prototype.toString.call(new Proxy(class {}, {})); });
show('new Function', function () { return [new Function('a', 'b', 'return a + b'), Function(), new Function('a,b', 'c', ''), Function('/* x */ a = 1, ...rest', '// body\nreturn rest')].map(String).join(' | '); });
show('GeneratorFunction ctors', function () { var GF = Object.getPrototypeOf(gen).constructor; var AF = Object.getPrototypeOf(af).constructor; var AGF = Object.getPrototypeOf(agen).constructor; var g = new GF('a', 'yield a; yield a * 2'); var it = g(5); return [GF.name, AF.name, AGF.name, String(g), it.next().value, it.next().value, String(new AF('x', 'return await x')), String(AGF('yield 1')), Object.getPrototypeOf(GF) === Function, typeof g.prototype, GF.length, Object.getPrototypeOf(g) === Object.getPrototypeOf(gen)].join(' | '); });
show('toString non-function', function () { return Function.prototype.toString.call({}); });
show('toString callable proxy object', function () { return Function.prototype.toString.call(new Proxy({}, {})); });
show('toString comments preserved', function () { function /* a */ weird /* b */ ( /* c */ ) /* d */ { /* e */ } return weird.toString(); });
show('getter/setter toString with odd names', function () { var o2 = { get 'a b'() { return 1; }, set [Symbol.for('s')](v) {}, get 0x10() { return 2; }, get() { return 'method named get'; }, set: function () {} }; return [Object.getOwnPropertyDescriptor(o2, 'a b').get, Object.getOwnPropertyDescriptor(o2, Symbol.for('s')).set, Object.getOwnPropertyDescriptor(o2, '16').get, o2.get, o2.set].map(String).join(' | '); });
show('names', function () { var d = Object.getOwnPropertyDescriptor(o, 'acc'); return [decl.name, expr.name, anon.name, arrow.name, K.name, K.prototype.method.name, d.get.name, d.set.name, o[Symbol.iterator].name, o[42].name, o['quoted key'].name, decl.bind().name, decl.bind().bind().name, (function () {}).bind().name, new Function().name, Symbol.prototype[Symbol.toPrimitive].name, Object.getOwnPropertyDescriptor(K.prototype, 'g').get.name, (class { static name() {} }).name === undefined].join(','); });
show('name inference', function () { var a = function () {}; let b = () => {}; const c = class {}; var obj = { d: function () {}, ['e' + 1]: () => {}, [Symbol('sym')]: function () {}, [Symbol()]: function () {} }; var f; f = function () {}; var { g = function () {} } = {}; var [h = () => {}] = []; var i = (0, function () {}); var syms = Object.getOwnPropertySymbols(obj); return JSON.stringify([a.name, b.name, c.name, obj.d.name, obj.e1.name, obj[syms[0]].name, obj[syms[1]].name, f.name, g.name, h.name, i.name]); });
show('name descriptors', function () { function f() {} var d = Object.getOwnPropertyDescriptor(f, 'name'); class C {} return [d.writable, d.enumerable, d.configurable, Object.hasOwn(function () {}, 'name'), Object.hasOwn(() => {}, 'name'), JSON.stringify(Object.getOwnPropertyNames(C).sort())].join(); });
show('length/name descriptors', function () { function f(a, b = 1, c) {} var d = Object.getOwnPropertyDescriptor(f, 'length'); return [f.length, ((a, ...r) => 0).length, (function ({ a }, [b]) {}).length, d.writable, d.configurable, (function (a, b) {}).length, ((...args) => 0).length].join(); });
show('prototype properties', function () { return [typeof decl.prototype, typeof arrow.prototype, typeof af.prototype, typeof gen.prototype, typeof agen.prototype, typeof o.m.prototype, typeof K.prototype.method.prototype, typeof Math.max.prototype, Object.getOwnPropertyDescriptor(K, 'prototype').writable, Object.getOwnPropertyDescriptor(decl, 'prototype').writable].join(); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("function_to_string_and_names")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_bind_call_apply_and_instanceof(js, golden, tier):
    """CATCHES: bind that computes length/name wrongly for odd target lengths, does not forward new.target through bound constructors, call/apply that box or drop odd receivers, mishandle array-likes and null argument lists, or instanceof/@@hasInstance that skip bound-target unwrapping or prototype validation fail this."""
    code = SHOW + FN_DECLS + r"""show('bind', function () { function f(a, b, c) { return [this && this.tag, a, b, c].join('/'); } var b = f.bind({ tag: 'T' }, 1); return [b(2, 3), b.length, f.bind(null, 1, 2, 3, 4).length, b.name, new b(9) instanceof f, typeof b.prototype, b.bind(null, 'x')(), b.bind(null, 'x').length].join(' '); });
show('bind length odd', function () { function f(a, b) {} var res = []; [Infinity, -Infinity, -0, 1.9, -5, 'x', NaN, 2 ** 53].forEach(function (L) { Object.defineProperty(f, 'length', { value: L, configurable: true }); res.push(Object.is(f.bind().length, -0) ? '-0' : f.bind().length); }); Object.defineProperty(f, 'length', { get: function () { throw new Error('len getter'); }, configurable: true }); try { f.bind(); } catch (e) { res.push(e.message); } delete f.length; res.push(f.bind().length); return res.join(','); });
show('bind name odd', function () { function f() {} Object.defineProperty(f, 'name', { value: 42 }); var g = function () {}; Object.defineProperty(g, 'name', { value: Symbol('s') }); return JSON.stringify(f.bind().name) + ' ' + JSON.stringify(g.bind().name); });
show('bind non-callable', function () { return Function.prototype.bind.call({}); });
show('bind proxy target', function () { var log = []; var p = new Proxy(function target(a, b) { return a + b; }, { get: function (t, k) { log.push(String(k)); return t[k]; }, getOwnPropertyDescriptor: function (t, k) { log.push('gopd:' + String(k)); return Reflect.getOwnPropertyDescriptor(t, k); } }); var b = p.bind(null, 1); return b(2) + ' ' + b.length + ' ' + b.name + ' ' + log.join(','); });
show('bound new.target', function () { function F() { this.nt = new.target === F; } var B = F.bind({ ignored: true }); var x = new B(); class C { constructor() { this.nt = new.target; } } var BC = C.bind(); return x.nt + ' ' + (x instanceof B) + ' ' + (new BC().nt === C) + ' ' + Reflect.construct(B, [], Array).nt; });
show('bound arrow new', function () { var a = () => 1; return new (a.bind())(); });
show('bound class call', function () { return K.bind()(); });
show('bound method of builtin', function () { var slice = Function.prototype.call.bind(Array.prototype.slice); return JSON.stringify(slice('abc', 1)) + ' ' + [1, 2, 3].map(Math.pow.bind(null, 2)).join(); });
show('call/apply receivers', function () { function sloppy() { return typeof this + ':' + (this === globalThis); } function strict() { 'use strict'; return this === undefined ? 'undef' : this === null ? 'null' : typeof this; } return [sloppy.call(null), sloppy.call(undefined), sloppy.call(1), sloppy.apply('s'), strict.call(null), strict.call(), strict.call(1), strict.apply(true, []), sloppy.call(Symbol()), sloppy.call(1n), strict.call(1n)].join(' '); });
show('apply arg lists', function () { function f() { return arguments.length + ':' + Array.prototype.join.call(arguments, ','); } return [f.apply(null), f.apply(null, null), f.apply(null, undefined), f.apply(null, { length: 2, 0: 'a' }), f.apply(null, new String('ab')), f.apply(null, [1, , 3]), f.apply(null, { length: '2', 1: 'x' }), f.apply(null, (function () { return arguments; })('p', 'q')), f.apply(null, new Uint8Array([7, 8]))].join(' | '); });
show('apply primitive arg list', function () { return Math.max.apply(null, 5); });
show('apply string arg list', function () { return Math.max.apply(null, '12'); });
show('apply non-callable', function () { return Function.prototype.apply.call({}, null, []); });
show('call non-callable', function () { return Function.prototype.call.call(5); });
show('apply arg list getter throws', function () { return Math.max.apply(null, { get length() { throw new SyntaxError('length getter'); } }); });
show('apply proxy arg list', function () { var log = []; var p = new Proxy([1, 2], { get: function (t, k) { log.push(String(k)); return t[k]; } }); return Math.max.apply(null, p) + ' ' + log.join(','); });
show('Function.prototype itself', function () { return [Function.prototype(), Function.prototype.length, Function.prototype.name === '', typeof Function.prototype, Object.getPrototypeOf(Function.prototype) === Object.prototype, Function.prototype(1, 2, 3)].join(); });
show('new Function.prototype', function () { return new Function.prototype(); });
show('hasInstance', function () { function F() {} var hi = Function.prototype[Symbol.hasInstance]; return [hi.call(F, new F()), hi.call(F, {}), hi.call({}, {}), hi.call(F.bind(), new F()), hi.call(F, 1), Object.getOwnPropertyDescriptor(Function.prototype, Symbol.hasInstance).writable, hi.name, hi.call(F.bind().bind(), new F())].join(); });
show('hasInstance bad prototype', function () { function F() {} F.prototype = 1; return ({}) instanceof F; });
show('hasInstance primitive lhs skips prototype', function () { function F() {} F.prototype = 1; return 5 instanceof F; });
show('instanceof custom', function () { var Even = { [Symbol.hasInstance]: function (n) { return n % 2 === 0; } }; return [2 instanceof Even, 3 instanceof Even].join(); });
show('instanceof custom truthiness', function () { var C = { [Symbol.hasInstance]: function () { return 'yes'; } }; var D = { [Symbol.hasInstance]: function () { return 0; } }; return [({}) instanceof C, ({}) instanceof D].join(); });
show('instanceof non-callable', function () { return ({}) instanceof {}; });
show('instanceof non-callable hasInstance', function () { return ({}) instanceof { [Symbol.hasInstance]: 1 }; });
show('instanceof proxy function', function () { function F() {} var p = new Proxy(F, {}); return (new F() instanceof p) + ' ' + (new p() instanceof F); });
show('instanceof cross realm', function () { var other = $262.createRealm().global; var arr = new other.Array(); return [arr instanceof Array, arr instanceof other.Array, Array.isArray(arr), other.Function('return this')() === other].join(); });
show('arguments object', function () { function f(a) { arguments[0] = 'changed'; return [a, arguments.length, Object.prototype.toString.call(arguments), typeof arguments[Symbol.iterator], arguments.callee === f].join(); } return f(1, 2); });
show('strict arguments callee', function () { 'use strict'; return (function () { return arguments.callee; })(); });
show('arrow has no own arguments', function () { function outer() { var a = () => arguments[0]; return a('inner'); } return outer('outer'); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("bind_call_apply_and_instanceof")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_function_constructors_with_odd_parameters(js, golden, tier):
    """CATCHES: Function/GeneratorFunction/AsyncFunction constructors that parse parameters and body together (so `/*`, `//` or unbalanced parentheses leak), skip strict-mode body checks on the parameter list, capture the caller's scope instead of the global one, or allow super/new.target misuse fail this."""
    code = SHOW + r"""show('odd params', function () { var r = []; r.push(Function('a', 'b = a * 2', '{c} = {c: 3}', '[d] = [4]', 'return a + b + c + d')(1)); r.push(Function('a, /* , */ b', 'return b')(1, 2)); r.push(Function('...args', 'return args.length')(1, 2, 3)); r.push(Function('a\n,b', 'return a+b')(1, 2)); r.push(Function(undefined, 'return 1')(1)); r.push(Function({ toString: function () { return 'p'; } }, 'return p')(7)); r.push(Function('a', 'b', 'return arguments.length')(1, 2, 3)); r.push(Function('a // trailing comment', 'return a')(5)); r.push(Function('return "no params"')()); r.push(Function('a = 1', 'b = a + 1', 'return [a, b].join("/")')()); return r.join(' '); });
show('param errors', function () { var r = []; ['a b', ')', 'a){', '...a, b', 'a = ', '/*', '//', 'a,', ',a', '1', 'a, a = 1', 'yield', 'let'].forEach(function (p) { try { Function(p, ''); r.push(p + '=ok'); } catch (e) { r.push(p + '=' + e.name); } }); return r.join(' '); });
show('body errors', function () { var r = []; ['}', '/*', '})({', 'return return', 'break', 'continue', 'a:a:1', 'new.target', 'super.x', 'super()', 'yield 1', 'await 1', 'return /*', '"use strict"; with (a) {}'].forEach(function (b) { try { Function('', b); r.push(JSON.stringify(b) + '=ok'); } catch (e) { r.push(JSON.stringify(b) + '=' + e.name); } }); return r.join(' '); });
show('strict body', function () { var r = []; try { Function('a', 'a', '"use strict";'); r.push('dup ok'); } catch (e) { r.push(e.name); } try { Function('eval', '"use strict";'); } catch (e) { r.push(e.name); } try { Function('a = 1', '"use strict";'); } catch (e) { r.push(e.name); } try { Function('{a}', '"use strict";'); } catch (e) { r.push(e.name); } try { Function('', '"use strict"; arguments = 1'); } catch (e) { r.push(e.name); } try { Function('', '"use strict"; return 010'); } catch (e) { r.push(e.name); } r.push(Function('a', 'a', 'return a')(1, 2)); return r.join(','); });
show('global scope value', function () { var local = 'local'; globalThis.gv2 = 'g2'; return Function('return typeof local + gv2')(); });
show('sloppy this', function () { return [Function('return this === globalThis')(), Function('"use strict"; return this')()].join(); });
show('new.target', function () { var f = Function('return new.target'); return [typeof f(), new f() === undefined, typeof Reflect.construct(Function('this.made = typeof new.target'), []).made].join(); });
show('generator constructor', function () { var GF = Object.getPrototypeOf(function* () {}).constructor; var g = GF('a', 'b', 'yield a; yield* b; return "done"'); var it = g(1, [2, 3]); var r = []; var x; while (!(x = it.next()).done) r.push(x.value); r.push(x.value); var errs = []; ['yield', 'yield = 1'].forEach(function (p) { try { GF(p, ''); errs.push('ok'); } catch (e) { errs.push(e.name); } }); return r.join() + ' ' + errs.join() + ' ' + typeof GF('yield').prototype; });
show('async constructor parse errors', function () { var AF = Object.getPrototypeOf(async function () {}).constructor; var r = []; ['await', 'a = await 1'].forEach(function (p) { try { AF(p, ''); r.push('ok'); } catch (e) { r.push(e.name); } }); try { AF('', 'await'); r.push('body ok'); } catch (e) { r.push('body ' + e.name); } return r.join(); });
show('async constructor runs', function () { var AF = Object.getPrototypeOf(async function () {}).constructor; var log = []; var f = AF('x', 'var v = await x; return v * 2'); f(Promise.resolve(21)).then(function (v) { console.log('async constructor result: ' + v); }); return typeof f(1).then; });
show('Function.prototype.constructor', function () { return [Function.prototype.constructor === Function, (function () {}).constructor === Function, Function.length, Function.name, typeof Function.prototype.bind.prototype].join(); });
show('Function called with symbol param', function () { return Function(Symbol(), ''); });
show('toString of constructed with newlines', function () { return JSON.stringify(String(Function('a\n', 'b', '\nreturn 1\n'))); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("function_constructors_with_odd_parameters")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_error_constructors_cause_aggregate_suppressed(js, golden, tier):
    """CATCHES: Error constructors that create message/cause when they should not (or make them enumerable), read options.cause without HasProperty, mis-order AggregateError message/errors processing, lack SuppressedError/Error.isError/captureStackTrace, or an Error.prototype.toString with wrong name/message defaults fail this."""
    code = SHOW + r"""function own(e) { return Object.getOwnPropertyNames(e).filter(function (k) { return k !== 'stack'; }).sort().map(function (k) { var d = Object.getOwnPropertyDescriptor(e, k); return k + (d.enumerable ? '+' : '') + '=' + (k === 'errors' ? JSON.stringify(e[k]) : String(e[k])); }).join(' '); }
show('Error basics', function () { var e = new Error('msg'); return [e.name, e.message, String(e), own(e), e instanceof Error, Object.prototype.toString.call(e), Error('called').message, Error().message === '', 'message' in Error(), Object.hasOwn(Error(), 'message'), Error(undefined).hasOwnProperty('message')].join(' | '); });
show('message coercion', function () { return [new Error(42).message, new Error(null).message, new Error({ toString: function () { return 'obj'; } }).message, new Error('').hasOwnProperty('message')].join(','); });
show('message symbol', function () { return new Error(Symbol()); });
show('cause', function () { var c = new TypeError('inner'); var e = new Error('outer', { cause: c }); var r = [e.cause === c, own(e)]; r.push(Object.hasOwn(new Error('x', {}), 'cause'), Object.hasOwn(new Error('x', { cause: undefined }), 'cause'), Object.hasOwn(new Error('x', 'str'), 'cause'), new RangeError('r', { cause: 0 }).cause, Object.hasOwn(new Error('x', Object.create({ cause: 'inherited' })), 'cause')); var log = []; new Error('m', { get cause() { log.push('cause read'); return 1; } }); r.push(log.join()); return r.join(' | '); });
show('cause proxy has trap', function () { var log = []; var p = new Proxy({}, { has: function (t, k) { log.push('has ' + k); return true; }, get: function (t, k) { log.push('get ' + k); return 'C'; } }); var e = new Error('m', p); return log.join() + ' ' + e.cause; });
show('native error types', function () { return [EvalError, RangeError, ReferenceError, SyntaxError, TypeError, URIError].map(function (C) { var e = new C('m', { cause: 'c' }); return C.name + ':' + e.name + ':' + (e instanceof Error) + ':' + (Object.getPrototypeOf(C) === Error) + ':' + (Object.getPrototypeOf(C.prototype) === Error.prototype) + ':' + C.length + ':' + Object.hasOwn(C.prototype, 'message') + ':' + e.cause + ':' + (C('called') instanceof C); }).join(' '); });
show('Error.prototype', function () { var P = Error.prototype; return [P.name, JSON.stringify(P.message), Object.prototype.toString.call(P), typeof P.toString, Error.length, Error.name, Object.keys(P).length, JSON.stringify(Object.getOwnPropertyDescriptor(TypeError.prototype, 'name'))].join(' | '); });
show('toString variants', function () { var ts = Error.prototype.toString; return [ts.call({}), ts.call({ name: 'N' }), ts.call({ message: 'M' }), ts.call({ name: '', message: 'M' }), ts.call({ name: 'N', message: '' }), ts.call({ name: undefined, message: undefined }), ts.call({ name: 5, message: { toString: function () { return 'obj'; } } }), ts.call(Object.assign(Object.create(null), { name: 'Z', message: 'z' })), ts.call(function namedFn() {}), ts.call([])].join(' | '); });
show('toString non-object', function () { return Error.prototype.toString.call('str'); });
show('toString getter throws', function () { return Error.prototype.toString.call({ get name() { throw new EvalError('name getter'); } }); });
show('AggregateError', function () { var e = new AggregateError([1, new Error('x')], 'agg', { cause: 'c' }); var e2 = AggregateError(new Set(['s'])); return [e.name, e.message, e.cause, e.errors.length, String(e.errors[1]), own(e), Array.isArray(e.errors), e2.message === '', e2.errors.join(), AggregateError.length, Object.getPrototypeOf(AggregateError) === Error, Object.hasOwn(e2, 'message'), String(e)].join(' | '); });
show('AggregateError non-iterable', function () { return new AggregateError(5); });
show('AggregateError order', function () { var log = []; try { new AggregateError({ [Symbol.iterator]: function () { log.push('iter'); throw new Error('iter threw'); } }, { toString: function () { log.push('msg'); return 'm'; } }); } catch (e) { return log.join() + ' ' + e.message; } });
show('AggregateError errors fresh array', function () { var src = [1, 2]; var e = new AggregateError(src); return (e.errors !== src) + ' ' + JSON.stringify(Object.getOwnPropertyDescriptor(e, 'errors').writable); });
show('SuppressedError', function () { var e = new SuppressedError(new Error('err'), new Error('sup'), 'msg'); var e2 = SuppressedError(1, 2); return [e.name, e.message, e.error.message, e.suppressed.message, own(e2), SuppressedError.length, e instanceof Error, Object.hasOwn(e2, 'message'), Object.prototype.toString.call(e), Object.getPrototypeOf(SuppressedError) === Error, String(e)].join(' | '); });
show('SuppressedError message coercion', function () { return new SuppressedError(1, 2, { toString: function () { return 'coerced'; } }).message + ' ' + new SuppressedError(1, 2, undefined).hasOwnProperty('message'); });
show('captureStackTrace', function () { var o = {}; Error.captureStackTrace(o); var r = [typeof o.stack, Object.getOwnPropertyDescriptor(o, 'stack') !== undefined, Error.captureStackTrace.length]; try { Error.captureStackTrace(5); } catch (e) { r.push(e.name); } return r.join(' '); });
show('isError', function () { return [Error.isError(new Error()), Error.isError(new TypeError()), Error.isError({}), Error.isError(Object.create(Error.prototype)), Error.isError(new Proxy(new Error(), {})), Error.isError(), Error.isError(new (class extends Error {})()), Error.isError(new AggregateError([])), Error.isError(new DOMException('d')), Error.isError(new ($262.createRealm().global.Error)())].join(); });
show('stack property', function () { var e = new Error('s'); return typeof e.stack + ' ' + String(e.stack).split('\n')[0]; });
show('subclass', function () { class MyErr extends Error { constructor(m) { super(m, { cause: 'sub' }); this.name = 'MyErr'; } } var e = new MyErr('boom'); return [String(e), e instanceof MyErr, e instanceof Error, e.cause, Object.prototype.toString.call(e), Error.prototype.isPrototypeOf(e)].join(' | '); });
show('new.target proto', function () { function F() {} F.prototype = Object.create(RangeError.prototype); var e = Reflect.construct(RangeError, ['nt'], F); return (e instanceof F) + ' ' + e.name + ' ' + e.message; });
show('new.target bad proto realm fallback', function () { function F() {} F.prototype = null; var e = Reflect.construct(TypeError, ['x'], F); return Object.getPrototypeOf(e) === TypeError.prototype; });
show('thrown errors', function () { var r = []; try { null.x; } catch (e) { r.push(e.constructor.name); } try { undefinedVar; } catch (e) { r.push(e.constructor.name + ':' + e.message); } try { (void 0)(); } catch (e) { r.push(e.name); } try { new Array(-1); } catch (e) { r.push(e.name); } try { decodeURI('%'); } catch (e) { r.push(e.name); } try { eval('('); } catch (e) { r.push(e.name); } try { (function f() { 'use strict'; undeclared = 1; })(); } catch (e) { r.push(e.name + ':' + e.message); } return r.join(' '); });
show('error message for calls', function () { var r = []; var obj = { a: {} }; try { obj.a.b.c(); } catch (e) { r.push(e.message); } try { obj.a.f(); } catch (e) { r.push(e.message); } try { obj.nope(); } catch (e) { r.push(e.message); } try { var u; u.x = 1; } catch (e) { r.push(e.message); } try { null[Symbol.iterator]; } catch (e) { r.push(e.message); } try { new (function () {}.bind().call)(); } catch (e) { r.push(e.message); } try { [...5]; } catch (e) { r.push(e.message); } try { let { a } = null; } catch (e) { r.push(e.message); } try { 1(); } catch (e) { r.push(e.message); } try { 'x' in 'y'; } catch (e) { r.push(e.message); } return r.join(' | '); });
show('Error props writable', function () { var e = new Error('m'); e.message = 'changed'; e.name = 'Renamed'; return String(e) + ' ' + JSON.stringify(Object.getOwnPropertyDescriptor(Error.prototype, 'name')); });
show('Error ctor message toString order', function () { var log = []; new Error({ toString: function () { log.push('msg'); return 'm'; } }, { get cause() { log.push('cause'); } }); return log.join(); });
var sd = Object.getOwnPropertyDescriptor(Error.prototype, 'stack');
show('stack accessor shape', function () { return [typeof sd.get, typeof sd.set, sd.enumerable, sd.configurable, Object.hasOwn(new Error('x'), 'stack'), sd.get.name, sd.set.name].join(); });
show('stack getter non-error object', function () { return sd.get.call({}); });
show('stack getter primitive', function () { return sd.get.call(1); });
show('stack getter name/message variants', function () { var e1 = new Error('m'); e1.name = undefined; var e2 = new Error(''); e2.name = 'OnlyName'; var e3 = new Error('only message'); e3.name = ''; return [e1.stack.split('\n')[0], e2.stack.split('\n')[0], e3.stack.split('\n')[0]].join(' | '); });
show('stack setter primitive this', function () { return sd.set.call(1, 's'); });
show('stack setter non-string', function () { return sd.set.call({}, 5); });
show('stack setter on Error.prototype', function () { return sd.set.call(Error.prototype, 's'); });
show('stack setter creates own', function () { var o = {}; sd.set.call(o, 'custom stack'); var d = Object.getOwnPropertyDescriptor(o, 'stack'); return [o.stack, d.writable, d.enumerable, d.configurable].join(); });
show('stack setter updates own', function () { var o = { stack: 'old' }; sd.set.call(o, 'new'); return o.stack; });
show('stack setter on frozen', function () { var o = Object.freeze({}); return sd.set.call(o, 'x'); });
show('stack setter own read-only', function () { var o = {}; Object.defineProperty(o, 'stack', { value: 'ro', writable: false, configurable: true }); return sd.set.call(o, 'x'); });
show('stack setter proxy with own', function () { var log = []; var p = new Proxy({ stack: 'p' }, { set: function (t, k, v) { log.push('set ' + k + '=' + v); return k !== 'stack' || v !== 'reject'; } }); sd.set.call(p, 'accepted'); try { sd.set.call(p, 'reject'); } catch (e) { log.push(e.name); } return log.join(' '); });
show('stack setter proxy without trap', function () { var t = { stack: 'orig' }; sd.set.call(new Proxy(t, {}), 'via target'); return t.stack; });
show('stack setter proxy defines', function () { var log = []; var p = new Proxy({}, { defineProperty: function (t, k, d) { log.push('define ' + k + ' ' + d.value); return Reflect.defineProperty(t, k, d); } }); sd.set.call(p, 'defined'); return log.join(); });
show('stack assignment on error', function () { var e = new Error('x'); e.stack = 'replaced'; return e.stack + ' ' + Object.hasOwn(e, 'stack'); });
show('AggregateError newTarget non-object prototype', function () { function F() {} F.prototype = 1; var e = Reflect.construct(AggregateError, [[]], F); return Object.getPrototypeOf(e) === AggregateError.prototype; });
show('SuppressedError newTarget non-object prototype', function () { function F() {} F.prototype = null; var e = Reflect.construct(SuppressedError, [1, 2], F); return Object.getPrototypeOf(e) === SuppressedError.prototype; });
show('AggregateError cross-realm newTarget', function () { var other = $262.createRealm().global; var F = other.Function(); F.prototype = null; var e = Reflect.construct(AggregateError, [[]], F); return Object.getPrototypeOf(e) === other.AggregateError.prototype; });
show('errors cross realm', function () { var other = $262.createRealm().global; var e = new other.TypeError('x'); return [e instanceof TypeError, e instanceof other.TypeError, Object.prototype.toString.call(e), Error.prototype.toString.call(e)].join(); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("error_constructors_cause_aggregate_suppressed")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_reflect_api(js, golden, tier):
    """CATCHES: Reflect methods that accept non-object targets, coerce argument lists loosely, ignore newTarget or receiver arguments, throw instead of returning false (or vice versa) for failed defineProperty/set/deleteProperty/setPrototypeOf, or mishandle array length and accessor receivers fail this."""
    code = SHOW + r"""var R = Reflect;
show('apply', function () { return [R.apply(Math.max, null, [1, 3, 2]), R.apply(function () { return this; }, 'x', []) + '', R.apply(String.prototype.slice, 'hello', [1, 3]), R.apply(function () { return arguments.length; }, null, { length: 3 })].join(' '); });
show('apply non-callable', function () { return R.apply(1, null, []); });
show('apply no args', function () { return R.apply(function () {}, null); });
show('apply primitive args', function () { return R.apply(function () {}, null, 1); });
show('construct', function () { function F(a) { this.a = a; this.nt = new.target; } function G() {} var o = R.construct(F, [1], G); return [o.a, o.nt === G, Object.getPrototypeOf(o) === G.prototype, R.construct(Date, [0]).getTime(), R.construct(Array, [3]).length, R.construct(F, { length: 1, 0: 'al' }).a, R.construct(Map, []) instanceof Map].join(' '); });
show('construct non-ctor', function () { return R.construct(Math.max, []); });
show('construct bad newTarget', function () { return R.construct(function () {}, [], Math.max); });
show('construct arrow newTarget', function () { return R.construct(function () {}, [], () => {}); });
show('construct no args', function () { return R.construct(function () {}); });
show('construct class newTarget', function () { class A { constructor() { this.t = new.target.name; } } class B {} return R.construct(A, [], B).t + ' ' + (Object.getPrototypeOf(R.construct(A, [], B)) === B.prototype); });
show('construct builtin newTarget proto', function () { function F() {} F.prototype = Object.create(Map.prototype); F.prototype.extra = 'e'; var m = R.construct(Map, [[[1, 2]]], F); return m.extra + ' ' + m.get(1) + ' ' + (m instanceof F); });
show('defineProperty', function () { var o = {}; return [R.defineProperty(o, 'x', { value: 1 }), R.defineProperty(o, 'x', { value: 2 }), R.defineProperty(o, 'x', { value: 1 }), o.x, R.defineProperty(Object.freeze([]), 0, { value: 1 }), R.defineProperty(o, Symbol.iterator, { value: 1 })].join(); });
show('defineProperty bad length', function () { return R.defineProperty([], 'length', { value: -1 }); });
show('defineProperty non-object', function () { return R.defineProperty(1, 'x', {}); });
show('defineProperty bad desc', function () { return R.defineProperty({}, 'x', 1); });
show('deleteProperty', function () { var o = { a: 1 }; Object.defineProperty(o, 'nc', { value: 1 }); return [R.deleteProperty(o, 'a'), R.deleteProperty(o, 'nc'), R.deleteProperty(o, 'missing'), 'a' in o, R.deleteProperty([1], 'length'), R.deleteProperty(Object.freeze({ z: 1 }), 'z'), R.deleteProperty(new String('ab'), '0'), R.deleteProperty(new String('ab'), '5')].join(); });
show('deleteProperty non-object', function () { return R.deleteProperty('s', 0); });
show('get', function () { var o = { a: 1, get g() { return this.tag; } }; return [R.get(o, 'a'), R.get(o, 'g', { tag: 'recv' }), R.get(o, 'g'), R.get([5], 0), R.get(Object.create(o), 'a'), R.get(new Proxy({}, { get: function (t, k, r) { return r.mark; } }), 'x', { mark: 'proxyrecv' }), R.get(Object.create(new Proxy({}, { get: function (t, k, r) { return 'via proto ' + (r.mark || '?'); } })), 'q', { mark: 'M' }), R.get(new Uint8Array([9]), 0, {}), R.get(new Uint8Array([9]), 5), R.get('str'.constructor.prototype, 'length')].join(' '); });
show('get non-object', function () { return R.get(1, 'x'); });
show('get typed array on proto chain', function () { var o = Object.create(new Uint8Array([4, 5])); var r = [R.get(o, 1), R.get(o, 7), R.get(o, '-0'), R.get(o, 'byteLength', Object.getPrototypeOf(o))]; try { o.length; } catch (e) { r.push(e.name); } return r.join(); });
show('set', function () { var o = { set s(v) { this.got = v; } }; var recv = {}; var r = [R.set(o, 's', 5, recv), recv.got, o.got]; var t = {}; r.push(R.set(t, 'a', 1), t.a); var fr = Object.freeze({ a: 1 }); r.push(R.set(fr, 'a', 2), R.set(fr, 'b', 2)); var proto = Object.freeze({ inh: 1 }); r.push(R.set(Object.create(proto), 'inh', 2)); r.push(R.set({}, 'x', 1, 5)); var nonext = Object.preventExtensions({}); r.push(R.set({}, 'x', 1, nonext)); var withAcc = {}; Object.defineProperty(withAcc, 'x', { get: function () {}, configurable: true }); r.push(R.set({}, 'x', 1, withAcc)); var ro = {}; Object.defineProperty(ro, 'x', { value: 1, writable: false, configurable: true }); r.push(R.set({}, 'x', 2, ro)); var ok = { x: 1 }; r.push(R.set({}, 'x', 'recv-updated', ok), ok.x); return r.join(); });
show('set array length via receiver', function () { var a = [1, 2, 3]; return R.set(a, 'length', 1) + ' ' + a.length + ' ' + R.set({}, 'length', 0, a) + ' ' + a.length; });
show('set non-object', function () { return R.set(1, 'x', 1); });
show('set setter-less accessor', function () { var o = {}; Object.defineProperty(o, 'g', { get: function () { return 1; } }); return R.set(o, 'g', 2); });
show('set typed array receivers', function () { var ta = new Uint8Array(2); var r = [R.set(ta, 0, 300), ta[0], R.set(ta, 5, 1), R.set(ta, '-0', 1), R.set(ta, 'foo', 'bar'), ta.foo]; var other = {}; r.push(R.set(ta, 1, 7, other), other[1], ta[1]); var child = Object.create(ta); r.push(R.set(child, 0, 9), ta[0], Object.hasOwn(child, '0')); var big = new BigInt64Array(1); r.push(R.set(big, 0, 5n), big[0]); return r.join(); });
show('set typed array bigint type error', function () { return R.set(new BigInt64Array(1), 0, 1); });
show('set through proxy on proto', function () { var log = []; var p = new Proxy({}, { set: function (t, k, v, r) { log.push(k + '=' + v + ' recvIsChild=' + (r === child)); return true; } }); var child = Object.create(p); child.x = 1; return log.join() + ' own=' + Object.hasOwn(child, 'x'); });
show('getOwnPropertyDescriptor', function () { return [JSON.stringify(R.getOwnPropertyDescriptor({ a: 1 }, 'a')), R.getOwnPropertyDescriptor({}, 'a'), JSON.stringify(R.getOwnPropertyDescriptor([], 'length')), JSON.stringify(R.getOwnPropertyDescriptor(new Uint8Array([3]), 0)), R.getOwnPropertyDescriptor(new Uint8Array([3]), 1), R.getOwnPropertyDescriptor(new Uint8Array([3]), '1.5')].join(' '); });
show('getOwnPropertyDescriptor non-object', function () { return R.getOwnPropertyDescriptor('s', 'length'); });
show('getPrototypeOf', function () { return [R.getPrototypeOf([]) === Array.prototype, R.getPrototypeOf(Object.create(null))].join(); });
show('getPrototypeOf non-object', function () { return R.getPrototypeOf(1); });
show('has', function () { return [R.has({ a: 1 }, 'a'), R.has([], 'length'), R.has(Object.create({ p: 1 }), 'p'), R.has({}, 'toString'), R.has(new Proxy({}, { has: function () { return true; } }), 'any'), R.has(new Uint8Array(1), 0), R.has(new Uint8Array(1), 1), R.has(new String('ab'), 1)].join(); });
show('has non-object', function () { return R.has('str', 'length'); });
show('isExtensible', function () { return [R.isExtensible({}), R.isExtensible(Object.seal({}))].join(); });
show('isExtensible non-object', function () { return R.isExtensible(1); });
show('ownKeys', function () { var s = Symbol('s'); var o = { b: 1, 10: 1, a: 1, [s]: 1, 2: 1 }; return R.ownKeys(o).map(String).join() + ' | ' + R.ownKeys([1, 2]).join() + ' | ' + R.ownKeys(function f(x) {}).join() + ' | ' + R.ownKeys(new String('hi')).join() + ' | ' + R.ownKeys(new Uint8Array(2)).join(); });
show('ownKeys non-object', function () { return R.ownKeys('x'); });
show('preventExtensions non-object', function () { return R.preventExtensions(1); });
show('setPrototypeOf', function () { var o = {}; return [R.setPrototypeOf(o, Array.prototype), R.setPrototypeOf(o, null), R.setPrototypeOf(Object.preventExtensions({}), {}), R.setPrototypeOf(Object.prototype, {})].join(); });
show('setPrototypeOf bad proto', function () { return R.setPrototypeOf({}, 1); });
show('setPrototypeOf undefined proto', function () { return R.setPrototypeOf({}); });
show('setPrototypeOf non-object', function () { return R.setPrototypeOf(1, null); });
show('Reflect.set proxy with trap and receiver', function () { var log = []; var p = new Proxy({}, { set: function (t, k, v, r) { log.push(k + ':' + v + ':' + (r === recv)); return v !== 'no'; } }); var recv = {}; return [Reflect.set(p, 'a', 1, recv), Reflect.set(p, 'b', 'no'), Reflect.set(p, 'c', 2)].join() + ' ' + log.join(' '); });
show('Reflect.set proxy trap invariant', function () { var t = {}; Object.defineProperty(t, 'ro', { value: 1 }); var p = new Proxy(t, { set: function () { return true; } }); return Reflect.set(p, 'ro', 2); });
show('Reflect.set proxy without trap', function () { var t = Object.freeze({ k: 1 }); var p = new Proxy(t, {}); var recv = {}; return [Reflect.set(p, 'k', 2), Reflect.set(new Proxy({}, {}), 'x', 1, recv), recv.x].join(); });
show('Reflect.set revoked', function () { var r = Proxy.revocable({}, {}); r.revoke(); return Reflect.set(r.proxy, 'x', 1); });
show('Reflect.gopd mapped arguments', function () { return (function (a) { a = 'changed'; return JSON.stringify(Reflect.getOwnPropertyDescriptor(arguments, '0')); })('orig'); });
show('Reflect.gopd proxy', function () { return JSON.stringify(Reflect.getOwnPropertyDescriptor(new Proxy({ z: 1 }, {}), 'z')); });
show('Reflect.gopd private-looking key', function () { return Reflect.getOwnPropertyDescriptor({}, '#x'); });
show('Reflect.deleteProperty typed array', function () { var t = new Uint8Array(2); return [Reflect.deleteProperty(t, 0), Reflect.deleteProperty(t, 5), Reflect.deleteProperty(t, '-0'), Reflect.deleteProperty(t, 'foo')].join(); });
show('Reflect.getPrototypeOf proxy', function () { return Reflect.getPrototypeOf(new Proxy([], {})) === Array.prototype; });
show('Reflect.defineProperty proxy', function () { var p = new Proxy({}, { defineProperty: function () { return false; } }); return Reflect.defineProperty(p, 'x', { value: 1 }); });
show('Reflect props', function () { return Object.getOwnPropertyNames(R).sort().join() + ' ' + R[Symbol.toStringTag] + ' ' + typeof R + ' ' + R.apply.length + R.construct.length + R.defineProperty.length + R.get.length + R.set.length; });
show('Reflect not callable', function () { return R(); });
show('Reflect not constructor', function () { return new R.get({}, 'x'); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("reflect_api")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_proxy_traps_and_revocation(js, golden, tier):
    """CATCHES: Proxy objects whose apply/construct/has/deleteProperty/ownKeys traps are not consulted (or are called with the wrong receiver/newTarget), that allow construct traps to return primitives, call/construct revoked proxies, accept non-object targets, or skip deleteProperty invariants fail this."""
    code = SHOW + r"""var R = Reflect;
show('apply/construct traps', function () { var log = []; var p = new Proxy(function target(a) { return 'target:' + a; }, { apply: function (t, thisArg, args) { log.push('apply this=' + thisArg + ' args=' + args); return t.apply(thisArg, args) + '!'; }, construct: function (t, args, nt) { log.push('construct nt=' + (nt === p)); return { made: args[0] }; } }); var r1 = p(1); var r2 = p.call('ctx', 2); var r3 = new p(3).made; var r4 = R.apply(p, 'R', [4]); var r5 = R.construct(p, [5], Object).made; return [r1, r2, r3, r4, r5, log.join(' ; ')].join(' | '); });
show('construct returns primitive', function () { var p = new Proxy(function () {}, { construct: function () { return 1; } }); return new p(); });
show('construct on non-ctor target', function () { var p = new Proxy(() => {}, { construct: function () { return {}; } }); return new p(); });
show('apply on non-callable target', function () { var p = new Proxy({}, { apply: function () { return 1; } }); return p(); });
show('apply trap not callable', function () { return new Proxy(function () {}, { apply: 1 })(); });
show('construct trap not callable', function () { return new (new Proxy(function () {}, { construct: 'x' }))(); });
show('forwarding without traps', function () { function F(a) { this.a = a; } var p = new Proxy(F, {}); return [new p(7).a, p.call({}, 1), p.length, p.name, new p(1) instanceof F].join(); });
show('typeof', function () { return [typeof new Proxy(function () {}, {}), typeof new Proxy({}, {}), typeof new Proxy(class {}, {}), typeof Proxy.revocable(function () {}, {}).proxy, typeof new Proxy(new Proxy(function () {}, {}), {})].join(); });
show('Proxy without new', function () { return Proxy({}, {}); });
show('Proxy bad args', function () { return new Proxy(1, {}); });
show('Proxy bad handler', function () { return new Proxy({}, null); });
show('Proxy.revocable', function () { var r = Proxy.revocable({ a: 1 }, {}); var v = r.proxy.a; r.revoke(); r.revoke(); var res = [v, Object.keys(r).join(), typeof r.revoke, r.revoke.length, r.revoke.name === '']; try { r.proxy.a; } catch (e) { res.push(e.name + ':' + e.message); } return res.join(' '); });
show('Proxy.revocable bad args', function () { return Proxy.revocable({}, 5); });
show('revoked proxy call', function () { var r = Proxy.revocable(function () {}, {}); r.revoke(); return r.proxy(); });
show('revoked proxy new', function () { var r = Proxy.revocable(function () {}, {}); r.revoke(); return new r.proxy(); });
show('revoked proxy ops', function () { var r = Proxy.revocable({}, {}); r.revoke(); var res = []; [function () { return 'x' in r.proxy; }, function () { return delete r.proxy.x; }, function () { r.proxy.x = 1; }, function () { return Object.getOwnPropertyDescriptor(r.proxy, 'x'); }, function () { return Object.defineProperty(r.proxy, 'x', {}); }, function () { return Reflect.ownKeys(r.proxy); }, function () { for (var k in r.proxy) {} }, function () { return typeof r.proxy; }].forEach(function (f) { try { res.push(String(f())); } catch (e) { res.push(e.name); } }); return res.join(','); });
show('revoked as target', function () { var r = Proxy.revocable({}, {}); r.revoke(); return typeof new Proxy(r.proxy, {}); });
show('Proxy props', function () { return [Proxy.length, Proxy.name, 'prototype' in Proxy, Object.getOwnPropertyNames(Proxy).sort().join()].join(' '); });
show('trap not callable', function () { return new Proxy({}, { get: 5 }).x; });
show('trap undefined/null forwards', function () { return new Proxy({ x: 'fwd' }, { get: undefined }).x + ' ' + new Proxy({ y: 'null' }, { get: null }).y; });
show('handler getter called per operation', function () { var log = []; var handler = new Proxy({}, { get: function (t, k) { log.push(String(k)); return undefined; } }); var p = new Proxy({ a: 1 }, handler); p.a; p.b = 2; 'a' in p; delete p.b; Object.keys(p); return log.join(','); });
show('has trap via in and with', function () { var log = []; var p = new Proxy({ v: 1 }, { has: function (t, k) { log.push('has:' + String(k)); return k in t; } }); var r = 'v' in p; with (p) { v; } return r + ' ' + log.join(); });
show('has trap invariants', function () { var nc = {}; Object.defineProperty(nc, 'x', { value: 1 }); var r = []; try { 'x' in new Proxy(nc, { has: function () { return false; } }); } catch (e) { r.push(e.name); } try { 'y' in new Proxy(Object.preventExtensions({ y: 1 }), { has: function () { return false; } }); } catch (e) { r.push(e.name); } r.push('z' in new Proxy({}, { has: function () { return 1; } })); return r.join(); });
show('deleteProperty trap', function () { var nc = {}; Object.defineProperty(nc, 'x', { value: 1 }); var p = new Proxy(nc, { deleteProperty: function () { return true; } }); return delete p.x; });
show('deleteProperty false strict', function () { 'use strict'; var p = new Proxy({ a: 1 }, { deleteProperty: function () { return false; } }); delete p.a; });
show('deleteProperty false sloppy', function () { var p = new Proxy({ a: 1 }, { deleteProperty: function () { return false; } }); return delete p.a; });
show('deleteProperty non-extensible', function () { var t = Object.preventExtensions({ a: 1 }); var p = new Proxy(t, { deleteProperty: function () { return true; } }); return R.deleteProperty(p, 'a'); });
show('deleteProperty not callable', function () { return delete new Proxy({}, { deleteProperty: 'x' }).a; });
show('deleteProperty forward', function () { var t = { a: 1 }; var p = new Proxy(t, {}); return delete p.a && !('a' in t); });
show('enumerate for-in', function () { var p = new Proxy({ a: 1, b: 2 }, { ownKeys: function () { return ['b', 'a', 'zz']; }, getOwnPropertyDescriptor: function (t, k) { return k === 'zz' ? undefined : { value: 1, enumerable: k !== 'a', configurable: true }; } }); var ks = []; for (var k in p) ks.push(k); return ks.join(); });
show('for-in through proxy prototype', function () { var proto = new Proxy({ inherited: 1 }, { ownKeys: function (t) { return Reflect.ownKeys(t).concat(['ghost']); }, getOwnPropertyDescriptor: function (t, k) { return k === 'ghost' ? { value: 1, enumerable: true, configurable: true } : Reflect.getOwnPropertyDescriptor(t, k); } }); var o = Object.create(proto); o.own = 1; var ks = []; for (var k in o) ks.push(k); return ks.join(); });
show('get trap receiver for inherited', function () { var p = new Proxy({}, { get: function (t, k, r) { return r === child ? 'child receiver' : 'other'; } }); var child = Object.create(p); return child.anything; });
show('set trap invariants', function () { var t = {}; Object.defineProperty(t, 'ro', { value: 1, writable: false, configurable: false }); Object.defineProperty(t, 'acc', { get: function () {}, configurable: false }); var p = new Proxy(t, { set: function () { return true; } }); var r = []; try { p.ro = 2; } catch (e) { r.push(e.name); } try { p.ro = 1; r.push('same ok'); } catch (e) { r.push(e.name); } try { p.acc = 1; } catch (e) { r.push(e.name); } return r.join(); });
show('set trap false strict', function () { 'use strict'; var p = new Proxy({}, { set: function () { return false; } }); p.x = 1; });
show('get trap invariants', function () { var t = {}; Object.defineProperty(t, 'ro', { value: 1, writable: false, configurable: false }); Object.defineProperty(t, 'acc', { set: function () {}, configurable: false }); var r = []; try { new Proxy(t, { get: function () { return 2; } }).ro; } catch (e) { r.push(e.name); } r.push(new Proxy(t, { get: function () { return 1; } }).ro); try { new Proxy(t, { get: function () { return 'x'; } }).acc; } catch (e) { r.push(e.name); } return r.join(); });
show('proxy as prototype of class instance', function () { var log = []; class Base {} Object.setPrototypeOf(Base.prototype, new Proxy({}, { get: function (t, k, r) { if (typeof k === 'string') log.push(k); return undefined; } })); var b = new Base(); b.missing; return log.join(); });
show('proxy wrapping array length', function () { var p = new Proxy([1, 2, 3], {}); p.length = 1; p.push(9); return JSON.stringify(p) + ' ' + Array.isArray(p) + ' ' + Array.prototype.concat.call([], p).length; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("proxy_traps_and_revocation")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_proxy_define_and_descriptor_invariants(js, golden, tier):
    """CATCHES: a Proxy defineProperty/getOwnPropertyDescriptor implementation that does not normalize the descriptor passed to the trap, or that lets traps report non-configurable, non-writable, different-enumerability or different-shape descriptors that contradict the target, fails this."""
    code = SHOW + r"""function t(label, f) { show(label, f); }
var nc = {}; Object.defineProperty(nc, 'fixed', { value: 1, enumerable: false, writable: false, configurable: false });
Object.defineProperty(nc, 'acc', { get: function g() { return 1; }, set: undefined, enumerable: true, configurable: false });
Object.defineProperty(nc, 'wr', { value: 1, writable: true, configurable: false });
nc.cfg = 1;
function definer(ret) { var log = []; var p = new Proxy(nc, { defineProperty: function (target, key, desc) { log.push(key + '{' + Object.keys(desc).join(',') + '}'); return ret; } }); return { p: p, log: log }; }
t('trap receives normalized descriptor', function () { var d = definer(true); Object.defineProperty(d.p, 'cfg', { value: 2, extra: 'dropped', enumerable: 1 }); return d.log.join(); });
t('trap receives accessor halves', function () { var d = definer(true); try { Object.defineProperty(d.p, 'cfg', { get: function () {}, set: function () {} }); } catch (e) {} return d.log.join(); });
t('trap false -> Reflect false', function () { return Reflect.defineProperty(definer(false).p, 'x', { value: 1 }); });
t('trap false -> Object throws', function () { return Object.defineProperty(definer(false).p, 'x', { value: 1 }); });
t('new non-configurable prop target lacks', function () { var p = new Proxy({}, { defineProperty: function () { return true; } }); return Object.defineProperty(p, 'x', { value: 1, configurable: false }); });
t('add to non-extensible target', function () { var p = new Proxy(Object.preventExtensions({}), { defineProperty: function () { return true; } }); return Object.defineProperty(p, 'x', { value: 1 }); });
t('configurable target made non-configurable', function () { var p = new Proxy({ c: 1 }, { defineProperty: function () { return true; } }); return Object.defineProperty(p, 'c', { value: 1, configurable: false }); });
t('non-configurable made configurable', function () { return Object.defineProperty(definer(true).p, 'fixed', { configurable: true }); });
t('enumerable change on non-configurable', function () { return Object.defineProperty(definer(true).p, 'fixed', { enumerable: true }); });
t('shape change on non-configurable', function () { return Object.defineProperty(definer(true).p, 'fixed', { get: function () {} }); });
t('getter change on non-configurable accessor', function () { return Object.defineProperty(definer(true).p, 'acc', { get: function other() {} }); });
t('setter change on non-configurable accessor', function () { return Object.defineProperty(definer(true).p, 'acc', { set: function other() {} }); });
t('same accessor ok', function () { var g = Object.getOwnPropertyDescriptor(nc, 'acc').get; return Reflect.defineProperty(definer(true).p, 'acc', { get: g, set: undefined }); });
t('non-writable made writable', function () { return Object.defineProperty(definer(true).p, 'fixed', { writable: true }); });
t('non-writable value change', function () { return Object.defineProperty(definer(true).p, 'fixed', { value: 2 }); });
t('non-writable same value ok', function () { return Reflect.defineProperty(definer(true).p, 'fixed', { value: 1 }); });
t('writable non-configurable made non-writable', function () { return Object.defineProperty(definer(true).p, 'wr', { value: 1, writable: false, configurable: false }); });
t('defineProperty trap not callable', function () { return Object.defineProperty(new Proxy({}, { defineProperty: 7 }), 'x', { value: 1 }); });
t('defineProperty forward', function () { var tgt = {}; Object.defineProperty(new Proxy(tgt, {}), 'x', { value: 'forwarded', enumerable: true }); return JSON.stringify(tgt); });
t('defineProperty revoked', function () { var r = Proxy.revocable({}, {}); r.revoke(); return Object.defineProperty(r.proxy, 'x', { value: 1 }); });
function gopd(desc, target) { return Object.getOwnPropertyDescriptor(new Proxy(target || nc, { getOwnPropertyDescriptor: function () { return desc; } }), 'fixed'); }
t('gopd reports configurable for non-configurable', function () { return gopd({ value: 1, configurable: true }); });
t('gopd reports different enumerable', function () { return gopd({ value: 1, configurable: false, enumerable: true }); });
t('gopd reports accessor for data', function () { return gopd({ get: function () {}, configurable: false }); });
t('gopd reports writable for non-writable', function () { return gopd({ value: 1, writable: true, configurable: false }); });
t('gopd reports different value', function () { return gopd({ value: 2, writable: false, configurable: false }); });
t('gopd reports matching', function () { return JSON.stringify(gopd({ value: 1, writable: false, configurable: false, enumerable: false })); });
t('gopd returns primitive', function () { return gopd(5); });
t('gopd non-configurable for configurable target', function () { return Object.getOwnPropertyDescriptor(new Proxy({ c: 1 }, { getOwnPropertyDescriptor: function () { return { value: 1, configurable: false }; } }), 'c'); });
t('gopd non-configurable non-writable for writable target', function () { return Object.getOwnPropertyDescriptor(new Proxy(nc, { getOwnPropertyDescriptor: function () { return { value: 1, writable: false, configurable: false }; } }), 'wr'); });
t('gopd undefined for non-configurable', function () { return Object.getOwnPropertyDescriptor(new Proxy(nc, { getOwnPropertyDescriptor: function () { return undefined; } }), 'fixed'); });
t('gopd undefined for missing ok', function () { return Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: function () { return undefined; } }), 'nope'); });
t('gopd trap not callable', function () { return Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: 'x' }), 'k'); });
t('gopd revoked', function () { var r = Proxy.revocable({}, {}); r.revoke(); return Object.getOwnPropertyDescriptor(r.proxy, 'x'); });
t('gopd completes partial descriptor', function () { var d = Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: function () { return { value: 'v', configurable: true }; } }), 'x'); return JSON.stringify(d); });
t('gopd accessor result', function () { var d = Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: function () { return { get: undefined, configurable: true }; } }), 'x'); return Object.keys(d).join() + ' ' + d.get + ' ' + d.set; });
t('hasOwnProperty via gopd trap', function () { var p = new Proxy({}, { getOwnPropertyDescriptor: function (t, k) { return k === 'yes' ? { value: 1, configurable: true } : undefined; } }); return [Object.prototype.hasOwnProperty.call(p, 'yes'), Object.prototype.hasOwnProperty.call(p, 'no')].join(); });
t('getOwnPropertyDescriptors via proxy', function () { var p = new Proxy({ a: 1 }, { ownKeys: function () { return ['a', 'b']; }, getOwnPropertyDescriptor: function (t, k) { return k === 'b' ? { value: 'B', configurable: true, enumerable: false } : Reflect.getOwnPropertyDescriptor(t, k); } }); var ds = Object.getOwnPropertyDescriptors(p); return Object.keys(ds).join() + ' ' + ds.b.value; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("proxy_define_and_descriptor_invariants")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_json_stringify_formatting_and_errors(js, golden, tier):
    """CATCHES: JSON.stringify that indents nested empty containers, ignores String/Number wrapper gaps or proxy replacer arrays, mis-escapes control characters and surrogates, serializes BigInt wrappers, functions, symbols or non-enumerable properties, or does not propagate toJSON/getter/replacer errors and cycles fails this."""
    code = SHOW + r"""show('pretty nested', function () { return JSON.stringify({ a: [1, { b: [] }, {}], c: { d: null, e: 'x' } }, null, '--'); });
show('pretty tab', function () { return JSON.stringify([{ k: [1] }], null, '\t'); });
show('space String wrapper', function () { return JSON.stringify([1, 2], null, new String('ab')); });
show('space Number wrapper', function () { return JSON.stringify({ a: 1 }, null, new Number(1)); });
show('space bool ignored', function () { return JSON.stringify({ a: 1 }, null, true); });
show('space fractional', function () { return JSON.stringify([1], null, 2.9); });
show('replacer proxy array', function () { var p = new Proxy(['b', 'a'], {}); return JSON.stringify({ a: 1, b: 2, c: 3 }, p); });
show('replacer array with holes and objects', function () { return JSON.stringify({ 1: 'x', a: 'y', u: 'z' }, [1, , 'a', true, null]); });
show('replacer array applies to nested', function () { return JSON.stringify({ keep: { keep: 1, drop: 2 }, drop: 3 }, ['keep']); });
show('replacer array with String/Number objects', function () { return JSON.stringify({ x: 1, 2: 'two' }, [new String('x'), new Number(2)]); });
show('control chars', function () { return JSON.stringify('\b\f\n\r\t\u0000\u001f\u007f"\\/  '); });
show('surrogate pairs', function () { return JSON.stringify('😀😀') + ' ' + JSON.stringify('\udead\ud83d') + ' ' + JSON.stringify({ '\ud800': '\udc00' }); });
show('BigInt wrapper', function () { return JSON.stringify([Object(1n)]); });
show('BigInt nested', function () { return JSON.stringify({ deep: [{ n: 2n }] }); });
show('BigInt replaced', function () { return JSON.stringify({ n: 5n }, function (k, v) { return typeof v === 'bigint' ? v.toString() + 'n' : v; }); });
show('Date toJSON', function () { return JSON.stringify({ d: new Date(0), inv: new Date(NaN) }); });
show('Date toJSON generic', function () { return Date.prototype.toJSON.call({ toISOString: function () { return 'custom iso'; } }) + ' ' + Date.prototype.toJSON.call({ valueOf: function () { return Infinity; }, toISOString: function () { return 'never'; } }); });
show('Date toJSON non-callable', function () { return Date.prototype.toJSON.call({ toISOString: 1 }); });
show('toJSON non-function', function () { return JSON.stringify({ toJSON: 5, v: 1 }); });
show('toJSON throws', function () { return JSON.stringify({ toJSON: function () { throw new EvalError('tj'); } }); });
show('toJSON on prototype', function () { function P() {} P.prototype.toJSON = function (key) { return 'P@' + key; }; return JSON.stringify({ a: new P(), b: [new P()] }); });
show('Map/Set/RegExp/Error', function () { return JSON.stringify([new Map([[1, 2]]), new Set([1]), /re/g, new Error('e'), new ArrayBuffer(2), Symbol.iterator, function () {}, Math, JSON, new Boolean(true), new Number(-0), Object(Symbol())]); });
show('getter throws', function () { return JSON.stringify({ get g() { throw new URIError('getter'); } }); });
show('nested cycle message', function () { var a = { b: { c: [] } }; a.b.c.push(a); return JSON.stringify(a); });
show('cycle through toJSON', function () { var a = {}; a.self = { toJSON: function () { return a; } }; return JSON.stringify(a); });
show('repeated non-cyclic references', function () { var shared = { s: 1 }; return JSON.stringify({ x: shared, y: shared, z: [shared, shared] }); });
show('non-enumerable/inherited skipped', function () { var o = Object.create({ inh: 1 }); Object.defineProperty(o, 'hid', { value: 2 }); o.vis = 3; return JSON.stringify(o); });
show('array-like object', function () { return JSON.stringify({ length: 2, 0: 'a' }) + ' ' + JSON.stringify(Object.assign([1, 2], { extra: 'x' })) + ' ' + JSON.stringify((function () { return arguments; })(1, 2)); });
show('sparse array', function () { return JSON.stringify([, 1, , undefined]); });
show('numbers', function () { return JSON.stringify([1e21, 1e-7, -0, 0.1 + 0.2, 2 ** 53 + 2, 5e-324, -1.5e300, NaN, -Infinity]); });
show('replacer function on root', function () { return JSON.stringify(5, function (k, v) { return k === '' ? { wrapped: v } : v; }); });
show('replacer returns undefined root', function () { return String(JSON.stringify(1, function () { return undefined; })); });
show('replacer this binding', function () { var holders = []; JSON.stringify({ a: [1] }, function (k, v) { holders.push(k + ':' + (Array.isArray(this) ? 'array' : typeof this) + (k === '' ? ':' + Object.keys(this).join('/') : '')); return v; }); return holders.join(' '); });
show('replacer throws', function () { return JSON.stringify({ a: 1 }, function (k, v) { if (k === 'a') throw new RangeError('replacer threw'); return v; }); });
show('stringify proxy revoked', function () { var r = Proxy.revocable({}, {}); r.revoke(); return JSON.stringify(r.proxy); });
show('stringify proxy ownKeys order', function () { var p = new Proxy({ a: 1, b: 2 }, { ownKeys: function () { return ['b', 'a']; } }); return JSON.stringify(p); });
show('stringify proxy array', function () { var log = []; var p = new Proxy([1, 2], { get: function (t, k) { log.push(String(k)); return t[k]; } }); return JSON.stringify(p) + ' ' + log.join(','); });
show('stringify key order', function () { return JSON.stringify({ b: 1, 2: 2, a: 3, 1: 4, [Symbol()]: 5 }); });
show('stringify string escapes key', function () { return JSON.stringify({ 'a"b': 1, 'c\nd': 2, '\u2028': 3 }); });
show('JSON space plain object ignored', function () { return JSON.stringify([1], null, {}) + JSON.stringify([1], null, new Boolean(true)); });
show('JSON proxy with symbol keys', function () { var s = Symbol('s'); var p = new Proxy({ a: 1 }, { ownKeys: function () { return ['a', s]; }, getOwnPropertyDescriptor: function (t, k) { return { value: 1, enumerable: true, configurable: true }; } }); var rev = JSON.parse('{"w":0}', function (k, v) { if (k === 'w') return p; return v; }); return JSON.stringify(p) + ' ' + JSON.stringify(rev); });
show('large structure', function () { var a = []; for (var i = 0; i < 2000; i++) a.push({ i: i, s: 'v' + i }); var s = JSON.stringify(a); var b = JSON.parse(s); return s.length + ' ' + b[1999].s + ' ' + b.length; });
show('stringify deep nest', function () { var o = {}; var cur = o; for (var i = 0; i < 200; i++) { cur.n = {}; cur = cur.n; } return JSON.stringify(o).length; });
show('JSON object', function () { return [Object.keys(JSON).length, Object.getOwnPropertyNames(JSON).sort().join(), JSON[Symbol.toStringTag], JSON.stringify.length, typeof JSON, Object.getPrototypeOf(JSON) === Object.prototype].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("json_stringify_formatting_and_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_json_parse_errors_reviver_and_raw_json(js, golden, tier):
    """CATCHES: a JSON.parse that accepts trailing commas, leading zeros, bad escapes, unescaped control characters or trailing garbage, reports the wrong error, or whose reviver does not delete undefined results, walk grafted proxies/typed arrays, honour non-configurable holders, or expose source text only for unmodified primitives, and a lax JSON.rawJSON fail this."""
    code = SHOW + r"""show('parse basics', function () { return JSON.stringify([JSON.parse('{}'), JSON.parse('[]'), JSON.parse(' [ ] '), JSON.parse('{ }'), JSON.parse('false'), JSON.parse('true'), JSON.parse('null'), JSON.parse('"\\"\\\\\\/\\b\\f\\n\\r\\t\\u0041"'), JSON.parse('-1.5e+2'), JSON.parse('0'), JSON.parse('[[[]]]'), JSON.parse('{"a":{"b":{}}}'), JSON.parse('1E2'), JSON.parse('-0.0'), JSON.parse('"\\u00e9\\uD83D\\uDE00"')]); });
show('parse reviver empty containers', function () { return JSON.stringify(JSON.parse('{"a":{},"b":[]}', function (k, v) { return v; })); });
show('parse errors messages', function () { var r = []; ['{"a" 1}', '{"a":1 "b":2}', '[1 2]', '{1:2}', '[1,2', '{"a":1', '"abc', '-', '1.', '1e', '1e+', '01', '{"a":1}x', 'falsy', 'nul', '"\\q"', '"\\u12"', ' 1 x', '[,]', '{,}', '+1', '.5', 'NaN', '"\t"', '{"a":1,}', '[1,]', "'single'", '\u00a01', '[', '{"a":}', 'tRue', '-01', '0x10', '"\\uZZZZ"'].forEach(function (s) { try { JSON.parse(s); r.push(JSON.stringify(s) + '=>ok'); } catch (e) { r.push(JSON.stringify(s) + '=>' + e.name + ':' + e.message); } }); return r.join('\n  '); });
show('parse whitespace kinds', function () { return [JSON.parse('\t\n\r 1 \t\n\r'), JSON.parse('[1\n,\n2]').length].join(); });
show('parse reviver deletes', function () { return JSON.stringify(JSON.parse('{"a":{"x":1,"y":2}}', function (k, v) { if (k === 'a') return v; if (k === 'x') { this.self = 1; } return k === 'y' ? undefined : v; })); });
show('reviver grafts proxy', function () { var log = []; var r = JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') { this.b = new Proxy({ p: 1, q: 2 }, { deleteProperty: function (t, key) { log.push('delete ' + key); return Reflect.deleteProperty(t, key); }, defineProperty: function (t, key, d) { log.push('define ' + key); return Reflect.defineProperty(t, key, d); } }); } if (k === 'p') return undefined; if (k === 'q') return 'Q'; return v; }); return log.join(',') + ' ' + JSON.stringify(r); });
show('reviver grafts proxy array', function () { var log = []; var done = false; var r = JSON.parse('[1, 2]', function (k, v) { if (k === '0' && !done) { done = true; this[1] = new Proxy([7, 8], { deleteProperty: function (t, key) { log.push('del ' + key); return Reflect.deleteProperty(t, key); } }); } if (v === 7) return undefined; return v; }); return log.join(',') + ' ' + JSON.stringify(r); });
show('reviver grafts typed array', function () { var r = JSON.parse('{"a":1,"t":0}', function (k, v) { if (k === 'a') { this.t = new Uint8Array([5, 6]); } if (this instanceof Uint8Array) return v * 2; return v; }); return Array.from(r.t).join(); });
show('reviver non-configurable target', function () { var r = JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') Object.defineProperty(this, 'b', { value: 'fixed', configurable: false }); return k === 'b' ? 'revived' : v; }); return JSON.stringify(r); });
show('reviver delete non-configurable', function () { var r = JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') Object.defineProperty(this, 'b', { value: 'stays', configurable: false, enumerable: true }); return k === 'b' ? undefined : v; }); return JSON.stringify(r); });
show('reviver array length getter', function () { var done = false; var r = JSON.parse('[1,[2,3]]', function (k, v) { if (k === '0' && !done) { done = true; this[1] = { length: 1, 0: 'al' }; } return v; }); return JSON.stringify(r); });
show('reviver source for nested', function () { var log = []; JSON.parse('{"n": -0.0, "s": "\\u0041", "arr": [true, null]}', function (k, v, ctx) { log.push(k + ':' + (ctx && ctx.source !== undefined ? ctx.source : '-')); return v; }); return log.join(' '); });
show('reviver source after modification', function () { var log = []; JSON.parse('[1, 2]', function (k, v, ctx) { if (k === '0') this[1] = 3; log.push(k + ':' + (ctx && 'source' in ctx ? ctx.source : 'nosrc')); return v; }); return log.join(' '); });
show('reviver order', function () { var log = []; JSON.parse('{"a":{"b":1,"c":[2]},"d":3}', function (k, v) { log.push(k === '' ? '<root>' : k); return v; }); return log.join(','); });
show('reviver throws', function () { return JSON.parse('[1]', function () { throw new RangeError('rev'); }); });
show('reviver non-callable ignored', function () { return JSON.stringify(JSON.parse('[1]', 5)); });
show('parse coercion', function () { return JSON.parse({ toString: function () { return '[9]'; } })[0] + ' ' + JSON.parse(1) + ' ' + JSON.parse(null) + ' ' + JSON.parse(true) + ' ' + JSON.parse(new String('"wrapped"')); });
show('parse undefined', function () { return JSON.parse(); });
show('parse symbol', function () { return JSON.parse(Symbol()); });
show('parse duplicate and __proto__', function () { var o = JSON.parse('{"__proto__":1,"a":1,"a":2}'); return Object.keys(o).join() + ' ' + o.a + ' ' + (Object.getPrototypeOf(o) === Object.prototype); });
show('parse big numbers and precision', function () { return JSON.stringify(JSON.parse('[1e309, -1e309, 123456789012345678901234567890, 0.1, 1.7976931348623157e308, 4.9e-324, 2.5e-324]')); });
show('JSON parse errors with reviver', function () { var r = []; var rev = function (k, v) { return v; }; ['{"a" 1}', '{1:2}', '{"a":1 "b":2}', '[1 2]', '{"a":1}x', '{"a":}', '[1,]'].forEach(function (s) { try { JSON.parse(s, rev); r.push('ok'); } catch (e) { r.push(e.message); } }); return r.join(' | '); });
show('reviver walks grafted proxy with symbol keys', function () { var s = Symbol('s'); var log = []; JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') { this.b = new Proxy({ x: 1 }, { ownKeys: function () { return ['x', s]; } }); } log.push(String(k)); return v; }); return log.join(); });
show('rawJSON errors', function () { var r = []; ['', ' 1', '1 ', '[]', '{}', 'tru', '"a', 'null', '1e5', '-0', '"\\n"', '\t1', '1\n', '"unterminated', '01'].forEach(function (s) { try { var x = JSON.rawJSON(s); r.push(JSON.stringify(x)); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('rawJSON in array/pretty', function () { return JSON.stringify([JSON.rawJSON('1.000'), { r: JSON.rawJSON('true') }], null, 1); });
show('rawJSON symbol', function () { return JSON.rawJSON(Symbol()); });
show('rawJSON object shape', function () { var r = JSON.rawJSON('"x"'); return [Object.keys(r).join(), r.rawJSON, Object.isFrozen(r), Object.getPrototypeOf(r), JSON.isRawJSON(r), JSON.isRawJSON(Object.freeze({ rawJSON: '1' })), JSON.isRawJSON(1)].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("json_parse_errors_reviver_and_raw_json")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_map_set_and_set_methods(js, golden, tier):
    """CATCHES: Map/Set with wrong SameValueZero keys (NaN, -0), iteration that ignores deletions/additions/clear during forEach or iterators, constructors that skip the adder lookup, or Set.prototype union/intersection/difference/symmetricDifference/isSubsetOf/isSupersetOf/isDisjointFrom that misuse the set-like size/has/keys protocol fail this."""
    code = SHOW + r"""function S(s) { return '{' + [...s].join(',') + '}'; }
show('Map basics', function () { var k = {}; var m = new Map([[1, 'a'], ['1', 'b'], [k, 'obj'], [NaN, 'nan'], [-0, 'zero']]); return [m.size, m.get(1), m.get('1'), m.get(k), m.get(NaN), m.get(0), m.has(+0), m.delete(1), m.delete(1), m.size, [...m.keys()].map(String).join(), m.set('x', 1) === m, Object.is([...m.keys()][3], 0), m.get('missing')].join(' '); });
show('Map iteration mutation', function () { var m = new Map([[1, 1], [2, 2], [3, 3]]); var seen = []; m.forEach(function (v, k, map) { seen.push(k); if (k === 1) { map.delete(2); map.set(4, 4); } if (k === 3) map.set(1, 'again'); }); return seen.join() + ' ' + [...m.entries()].join(';'); });
show('Map delete and re-add during iteration', function () { var m = new Map([['a', 1], ['b', 2]]); var seen = []; for (var [k] of m) { seen.push(k); if (k === 'a') { m.delete('a'); m.set('a', 'readded'); } if (seen.length > 5) break; } return seen.join(); });
show('Map clear during iteration', function () { var m = new Map([[1, 1], [2, 2]]); var it = m.keys(); var a = it.next().value; m.clear(); m.set(9, 9); return a + ' ' + JSON.stringify(it.next()) + ' ' + JSON.stringify(it.next()); });
show('Map ctor errors', function () { var r = []; [5, [1], [[1, 2], 3]].forEach(function (x) { try { new Map(x); r.push('ok'); } catch (e) { r.push(e.name); } }); try { Map(); } catch (e) { r.push(e.message); } r.push(new Map(null).size, new Map(undefined).size); return r.join(); });
show('Map custom set', function () { var log = []; class M2 extends Map { set(k, v) { log.push(k); return super.set(k, v); } } new M2([['a', 1], ['b', 2]]); return log.join(); });
show('Map set non-callable', function () { var orig = Map.prototype.set; Map.prototype.set = 5; try { new Map([[1, 2]]); } catch (e) { Map.prototype.set = orig; return e.name; } Map.prototype.set = orig; return 'no error'; });
show('Map ctor closes iterator on bad entry', function () { var closed = false; var it = { [Symbol.iterator]: function () { return { next: function () { return { value: 1, done: false }; }, return: function () { closed = true; return {}; } }; } }; try { new Map(it); } catch (e) { return e.name + ' closed=' + closed; } });
show('Map methods bad this', function () { var r = []; ['get', 'set', 'has', 'delete', 'clear', 'forEach', 'keys', 'values', 'entries'].forEach(function (n) { try { Map.prototype[n].call({}, function () {}); r.push('ok'); } catch (e) { r.push(n + ':' + e.name); } }); try { Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.call(new Set()); } catch (e) { r.push('size:' + e.name); } return r.join(' '); });
show('Map forEach non-callable', function () { return new Map().forEach(5); });
show('Map getOrInsert', function () { var m = new Map(); var r = [m.getOrInsert('a', 1), m.getOrInsert('a', 2), m.getOrInsertComputed('b', function (k) { return k + '!'; }), m.getOrInsertComputed('b', function () { throw new Error('no'); }), m.size, m.getOrInsertComputed(-0, function (k) { return Object.is(k, 0); })]; return r.join(); });
show('Map getOrInsertComputed non-callable', function () { return new Map().getOrInsertComputed('k', 1); });
show('Map iterator protocol', function () { var it = new Map([[1, 2]])[Symbol.iterator](); return [Object.prototype.toString.call(it), typeof it.next, it[Symbol.iterator]() === it, JSON.stringify(it.next()), JSON.stringify(it.next()), Map.prototype.entries === Map.prototype[Symbol.iterator], Map.prototype[Symbol.toStringTag]].join(' '); });
show('Map species and statics', function () { return [Map[Symbol.species] === Map, typeof Map.groupBy, Map.length, Map.name, Object.getOwnPropertyNames(Map.prototype).sort().join()].join(' '); });
show('Set basics', function () { var s = new Set([1, 1, '1', NaN, NaN, -0, 0]); return [s.size, s.has(NaN), s.has(-0), s.add(2) === s, s.delete('1'), S(s), Set.prototype.keys === Set.prototype.values, Set.prototype[Symbol.iterator] === Set.prototype.values, JSON.stringify([...new Set('hello')]), JSON.stringify([...new Set([1, 2]).entries()]), Object.is([...new Set([-0])][0], 0)].join(' '); });
show('Set forEach thisArg', function () { var r = []; new Set(['a', 'b']).forEach(function (v, k, set) { r.push(this.p + v + k + set.size); }, { p: '>' }); return r.join(); });
show('Set forEach additions visited', function () { var s = new Set([1]); var seen = []; s.forEach(function (v) { seen.push(v); if (v < 4) s.add(v + 1); }); return seen.join(); });
show('Set custom add', function () { var log = []; class S2 extends Set { add(v) { log.push(v); return super.add(v); } } new S2('ab'); return log.join(); });
show('Set methods', function () { var a = new Set([1, 2, 3, 4]), b = new Set([3, 4, 5]); return [S(a.union(b)), S(a.intersection(b)), S(a.difference(b)), S(a.symmetricDifference(b)), a.isSubsetOf(b), new Set([3]).isSubsetOf(b), a.isSupersetOf(new Set([1, 2])), a.isDisjointFrom(new Set([9])), a.isDisjointFrom(b), S(b.intersection(a)), S(b.difference(a)), S(new Set().union(a)), new Set().isSubsetOf(a), a.isSupersetOf(new Set())].join(' '); });
show('Set methods with Map', function () { var a = new Set(['k1', 'z']); var m = new Map([['k1', 1], ['k2', 2]]); return [S(a.union(m)), S(a.intersection(m)), S(a.difference(m)), a.isSubsetOf(m), S(a.symmetricDifference(m))].join(' '); });
show('Set methods with set-like', function () { var log = []; var like = { size: 2, has: function (v) { log.push('has ' + v); return v === 1; }, keys: function () { log.push('keys'); var vals = [1, 7], i = 0; return { next: function () { return i < vals.length ? { value: vals[i++], done: false } : { done: true }; } }; } }; var a = new Set([1, 2, 3]); var r = [S(a.intersection(like)), S(a.difference(like)), S(a.union(like)), a.isSupersetOf(like), a.isDisjointFrom(like)]; return r.join(' ') + ' | ' + log.join(','); });
show('Set methods small this uses has', function () { var log = []; var like = { size: 10, has: function (v) { log.push('has ' + v); return v !== 2; }, keys: function () { log.push('keys'); return [][Symbol.iterator](); } }; var a = new Set([1, 2]); var r = [S(a.intersection(like)), S(a.difference(like)), a.isSubsetOf(like), a.isDisjointFrom(like)]; return r.join(' ') + ' | ' + log.join(','); });
show('Set methods bad size', function () { var r = []; [{ size: undefined, has: function () {}, keys: function () {} }, { size: 'x', has: function () {}, keys: function () {} }, { size: -1, has: function () {}, keys: function () {} }, { size: 1, has: 5, keys: function () {} }, { size: 1, has: function () {}, keys: 5 }, 5].forEach(function (o) { try { new Set([1]).union(o); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('Set methods size Infinity', function () { var like = { size: Infinity, has: function () { return true; }, keys: function () { throw new Error('keys not called'); } }; return new Set([1, 2]).isSubsetOf(like) + ' ' + S(new Set([1, 2]).intersection(like)); });
show('Set method keys next not object', function () { var like = { size: 1, has: function () {}, keys: function () { return { next: function () { return 5; } }; } }; return new Set([1]).union(like); });
show('Set method keys returns primitive', function () { var like = { size: 1, has: function () {}, keys: function () { return 1; } }; return new Set([1]).union(like); });
show('Set isSupersetOf closes', function () { var closed = false; var like = { size: 1, has: function () {}, keys: function () { return { next: function () { return { value: 99, done: false }; }, return: function () { closed = true; return {}; } }; } }; return new Set([1]).isSupersetOf(like) + ' closed=' + closed; });
show('Set isDisjointFrom closes', function () { var closed = false; var like = { size: 1, has: function () {}, keys: function () { return { next: function () { return { value: 1, done: false }; }, return: function () { closed = true; return {}; } }; } }; return new Set([1, 2, 3]).isDisjointFrom(like) + ' closed=' + closed; });
show('Set mutation during methods', function () { var a = new Set([1, 2, 3]); var like = { size: 10, has: function (v) { if (v === 1) a.delete(2); return true; }, keys: function () {} }; return S(a.intersection(like)) + ' ' + S(a); });
show('Set methods result order and -0', function () { var like = { size: 1, has: function () { return false; }, keys: function () { return [-0][Symbol.iterator](); } }; var u = new Set([5]).union(like); return S(u) + ' ' + Object.is([...u][1], 0); });
show('Set methods bad this', function () { return Set.prototype.union.call(new Map(), new Set()); });
show('Set species and statics', function () { return [Set[Symbol.species] === Set, Set.length, Object.getOwnPropertyNames(Set.prototype).sort().join()].join(' '); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("map_set_and_set_methods")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_weak_collections_and_finalization_registry(js, golden, tier):
    """CATCHES: WeakMap/WeakSet/WeakRef/FinalizationRegistry that accept primitives or registered symbols as weak keys, allow target/holdings identity, mis-validate unregister tokens, return the wrong unregister results, or can be called without new fail this (only deterministic, non-GC behaviour is checked)."""
    code = SHOW + r"""show('WeakMap', function () { var k = {}; var s = Symbol('local'); var wm = new WeakMap([[k, 1]]); wm.set(s, 2); return [wm.get(k), wm.has(k), wm.get(s), wm.delete(k), wm.has(k), wm.get({}), wm.delete(1), wm.has('x'), wm.getOrInsert(k, 'ins'), wm.getOrInsertComputed({}, function () { return 'cmp'; }), wm.set(k, 'v') === wm, wm.get(1)].join(); });
show('WeakMap bad key', function () { return new WeakMap().set(1, 1); });
show('WeakMap registered symbol', function () { return new WeakMap().set(Symbol.for('reg'), 1); });
show('WeakMap well-known symbol ok', function () { var wm = new WeakMap(); wm.set(Symbol.iterator, 'wk'); return wm.get(Symbol.iterator); });
show('WeakMap ctor', function () { var r = []; try { WeakMap(); } catch (e) { r.push(e.name); } try { new WeakMap([[1, 2]]); } catch (e) { r.push(e.name); } r.push(new WeakMap(null) instanceof WeakMap); return r.join(); });
show('WeakMap getOrInsert bad key', function () { return new WeakMap().getOrInsert('str', 1); });
show('WeakMap bad this', function () { return WeakMap.prototype.get.call(new Map(), {}); });
show('WeakSet', function () { var o = {}; var ws = new WeakSet([o]); return [ws.has(o), ws.add(Symbol()) === ws, ws.delete(o), ws.has(o), ws.has(1), ws.delete(null), Object.prototype.toString.call(ws)].join(); });
show('WeakSet bad value', function () { return new WeakSet().add('s'); });
show('WeakSet bad this', function () { return WeakSet.prototype.add.call({}, {}); });
show('WeakRef', function () { var o = { v: 1 }; var w = new WeakRef(o); var ws = new WeakRef(Symbol('ws')); return [w.deref() === o, typeof ws.deref(), Object.prototype.toString.call(w), WeakRef.prototype.deref.length, WeakRef.length].join(); });
show('WeakRef bad', function () { return new WeakRef(1); });
show('WeakRef registered symbol', function () { return new WeakRef(Symbol.for('r')); });
show('WeakRef call', function () { return WeakRef({}); });
show('WeakRef deref bad this', function () { return WeakRef.prototype.deref.call({}); });
show('WeakRef subclass', function () { class W extends WeakRef { constructor(t) { super(t); this.tag = 'sub'; } } var t = {}; var w = new W(t); return (w.deref() === t) + ' ' + w.tag + ' ' + (w instanceof WeakRef); });
show('FinalizationRegistry', function () { var fr = new FinalizationRegistry(function () {}); var t = {}; var tok = {}; fr.register(t, 'held', tok); fr.register({}, 'h2'); return [fr.unregister(tok), fr.unregister(tok), fr.unregister({}), typeof fr.register(Symbol(), 1), Object.prototype.toString.call(fr), FinalizationRegistry.length, fr.register.length].join(); });
show('FR token is target', function () { var fr = new FinalizationRegistry(function () {}); var t = {}; fr.register(t, 'h', t); return fr.unregister(t); });
show('FR errors', function () { var fr = new FinalizationRegistry(function () {}); var r = []; var t = {}; [function () { fr.register(1, 'x'); }, function () { fr.register(t, t); }, function () { fr.register(t, 1, 5); }, function () { fr.unregister(1); }, function () { new FinalizationRegistry(5); }, function () { FinalizationRegistry(function () {}); }, function () { FinalizationRegistry.prototype.register.call({}, {}); }, function () { fr.register(Symbol.for('x'), 1); }, function () { FinalizationRegistry.prototype.unregister.call({}, {}); }].forEach(function (f) { try { f(); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('FR undefined token ok', function () { var fr = new FinalizationRegistry(function () {}); return fr.register({}, 1, undefined); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("weak_collections_and_finalization_registry")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_iterator_helper_error_paths(js, golden, tier):
    """CATCHES: Iterator.prototype helpers (map/filter/take/drop/flatMap/reduce/toArray/forEach/some/every/find) and Iterator.from/concat/zip wrappers that fail to close the underlying iterator when a callback throws or is not callable, mis-validate receivers and next() results, or keep yielding after return() fail this."""
    code = SHOW + r"""function src(log, n) { var i = 0; return { __proto__: Iterator.prototype, next: function () { log.push('next'); return i < n ? { value: i++, done: false } : { value: undefined, done: true }; }, return: function () { log.push('return'); return {}; } }; }
['forEach', 'reduce', 'some', 'every', 'find', 'map', 'filter', 'flatMap'].forEach(function (m) {
  show(m + ' non-callable closes', function () { var log = []; try { var r = src(log, 3)[m](42); if (r && typeof r.next === 'function') r.next(); } catch (e) { return e.name + ' ' + log.join(); } return 'no error ' + log.join(); });
  show(m + ' throwing callback closes', function () { var log = []; try { var r = src(log, 3)[m](function () { throw new Error(m + ' cb'); }); if (r && typeof r.next === 'function') r.next(); } catch (e) { return e.message + ' ' + log.join(); } return 'no error ' + log.join(); });
});
show('take/drop bad limit closes', function () { var r = []; ['take', 'drop'].forEach(function (m) { [-1, NaN, { valueOf: function () { throw new EvalError('limit'); } }].forEach(function (lim) { var log = []; try { src(log, 2)[m](lim); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.name + ':' + log.join('/')); } }); }); return r.join(' '); });
show('drop past end', function () { var log = []; var it = src(log, 2).drop(5); return JSON.stringify(it.next()) + ' ' + JSON.stringify(it.next()) + ' ' + log.join(); });
show('take zero closes immediately', function () { var log = []; var it = src(log, 5).take(0); return JSON.stringify(it.next()) + ' ' + log.join(); });
show('flatMap inner throws closes outer', function () { var log = []; var inner = { [Symbol.iterator]: function () { return { next: function () { throw new RangeError('inner next'); } }; } }; try { src(log, 2).flatMap(function () { return inner; }).next(); } catch (e) { return e.message + ' ' + log.join(); } });
show('flatMap non-iterable result closes', function () { var log = []; try { src(log, 2).flatMap(function () { return 5; }).next(); } catch (e) { return e.name + ' ' + log.join(); } });
show('flatMap return closes inner and outer', function () { var log = []; var inner = { [Symbol.iterator]: function () { return { next: function () { return { value: 'in', done: false }; }, return: function () { log.push('inner return'); return {}; } }; } }; var it = src(log, 3).flatMap(function () { return inner; }); it.next(); it.return(); return log.join(); });
show('helper return before start', function () { var log = []; var it = src(log, 3).map(function (x) { return x; }); var r1 = JSON.stringify(it.return()); var r2 = JSON.stringify(it.next()); return r1 + ' ' + r2 + ' ' + log.join(); });
show('helper return after done', function () { var log = []; var it = src(log, 0).filter(Boolean); it.next(); return JSON.stringify(it.return()) + ' ' + log.join(); });
show('helper next bad receiver', function () { var proto = Object.getPrototypeOf(Iterator.prototype.map.call([1].values(), function () {})); var r = []; try { proto.next.call({}); } catch (e) { r.push(e.name); } try { proto.return.call({}); } catch (e) { r.push(e.name); } return r.join() + ' ' + Object.prototype.toString.call(proto); });
show('helpers on non-object this', function () { var r = []; ['map', 'filter', 'take', 'drop', 'flatMap', 'reduce', 'toArray', 'forEach', 'some', 'every', 'find'].forEach(function (m) { try { Iterator.prototype[m].call(5, function () {}); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.name); } }); return r.join(' '); });
show('next not callable', function () { var it = { __proto__: Iterator.prototype, next: 5 }; return it.toArray(); });
show('next returns primitive', function () { var it = { __proto__: Iterator.prototype, next: function () { return 1; } }; return it.map(function (x) { return x; }).next(); });
show('reduce with initial and index', function () { var log = []; var r = src(log, 3).reduce(function (acc, v, i) { return acc + v + ':' + i + ' '; }, '>'); return r + '| ' + log.length; });
show('find returns undefined when exhausted', function () { var log = []; return src(log, 2).find(function () { return false; }) + ' ' + log.join(); });
show('Iterator.from wrapper return', function () { var log = []; var plain = { next: function () { return { value: 1, done: false }; }, return: function () { log.push('plain return'); return { done: true, value: 'r' }; } }; var w = Iterator.from(plain); var r = w.return(); var plain2 = { next: function () { return { done: true }; } }; var w2 = Iterator.from(plain2); return JSON.stringify(r) + ' ' + log.join() + ' ' + JSON.stringify(w2.return()) + ' ' + (Object.getPrototypeOf(w) === Object.getPrototypeOf(w2)); });
show('Iterator.from wrapper return not callable', function () { var w = Iterator.from({ next: function () { return { done: true }; }, return: 5 }); return w.return(); });
show('Iterator.from wrapper bad receiver', function () { var w = Iterator.from({ next: function () { return { done: true }; } }); var proto = Object.getPrototypeOf(w); var r = []; try { proto.next.call({}); } catch (e) { r.push(e.name); } try { proto.return.call({}); } catch (e) { r.push(e.name); } return r.join(); });
show('Iterator.from returns iterator objects as is', function () { var gen = (function* () { yield 1; })(); return (Iterator.from(gen) === gen) + ' ' + (Iterator.from([1].values()) instanceof Iterator); });
show('Iterator.from bad @@iterator result', function () { return Iterator.from({ [Symbol.iterator]: function () { return 5; } }); });
show('Iterator.from string object', function () { return Iterator.from(new String('ab')).toArray().join(); });
show('Iterator.concat return', function () { var log = []; var a = { [Symbol.iterator]: function () { return { next: function () { return { value: 'a', done: false }; }, return: function () { log.push('a closed'); return {}; } }; } }; var c = Iterator.concat(a, [1]); var before = JSON.stringify(c.return()); var c2 = Iterator.concat(a, [1]); c2.next(); var after = JSON.stringify(c2.return()); return before + ' ' + after + ' ' + log.join() + ' ' + JSON.stringify(c2.next()); });
show('Iterator.concat bad @@iterator result', function () { return Iterator.concat({ [Symbol.iterator]: function () { return 1; } }).next(); });
show('Iterator.concat non-callable @@iterator', function () { return Iterator.concat({ [Symbol.iterator]: 'nope' }); });
show('Iterator.concat next after done', function () { var c = Iterator.concat([1]); c.next(); return JSON.stringify(c.next()) + JSON.stringify(c.next()); });
show('Iterator.zip return', function () { var log = []; function tracked(name) { return { [Symbol.iterator]: function () { return this; }, next: function () { return { value: name, done: false }; }, return: function () { log.push('close ' + name); return {}; } }; } var z = Iterator.zip([tracked('a'), tracked('b')]); z.next(); var r = JSON.stringify(z.return()); var r2 = JSON.stringify(z.next()); var z2 = Iterator.zip([tracked('c')]); var r3 = JSON.stringify(z2.return()); return r + ' ' + r2 + ' ' + r3 + ' ' + log.join(); });
show('Iterator.zip errors', function () { var r = []; [function () { Iterator.zip(5); }, function () { Iterator.zip([], 5); }, function () { Iterator.zip([], { mode: 'longest', padding: 5 }); }, function () { Iterator.zip([[1]], { mode: undefined }).next(); }, function () { Iterator.zipKeyed(5); }, function () { Iterator.zip([5]); }].forEach(function (f) { try { f(); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('Iterator.zip empty input', function () { return JSON.stringify(Iterator.zip([]).next()) + ' ' + JSON.stringify(Iterator.zipKeyed({}).next()); });
show('Iterator.zip strict mismatch closes', function () { var log = []; var b = { [Symbol.iterator]: function () { return this; }, next: function () { return { value: 'b', done: false }; }, return: function () { log.push('b closed'); return {}; } }; try { Iterator.zip([[1], b], { mode: 'strict' }).toArray(); } catch (e) { return e.name + ': ' + e.message + ' ' + log.join(); } });
show('Iterator.zip longest padding iterator', function () { var log = []; var pad = { [Symbol.iterator]: function () { var i = 0; return { next: function () { log.push('pad next'); return { value: 'P' + i++, done: false }; }, return: function () { log.push('pad closed'); return {}; } }; } }; var res = Iterator.zip([[1, 2], ['a']], { mode: 'longest', padding: pad }).toArray(); return JSON.stringify(res) + ' ' + log.join(); });
show('Iterator.zip longest short padding', function () { return JSON.stringify(Iterator.zip([[1, 2], [], []], { mode: 'longest', padding: ['only-one'] }).toArray()); });
show('Iterator.zipKeyed proxy input', function () { var p = new Proxy({ a: [1, 2], b: ['x', 'y'], c: undefined }, {}); return JSON.stringify(Iterator.zipKeyed(p).toArray()); });
show('Iterator.zipKeyed symbol keys and non-enumerable', function () { var s = Symbol('s'); var o = { a: [1] }; o[s] = [2]; Object.defineProperty(o, 'hidden', { value: [3], enumerable: false }); var r = Iterator.zipKeyed(o).toArray(); return r.length + ' ' + r[0].a + ' ' + r[0][s] + ' ' + ('hidden' in r[0]); });
show('Iterator.zipKeyed padding object', function () { return JSON.stringify(Iterator.zipKeyed({ a: [1, 2], b: [] }, { mode: 'longest', padding: { b: 'B' } }).toArray()); });
show('Iterator constructor', function () { var r = []; try { new Iterator(); } catch (e) { r.push(e.name); } try { Iterator(); } catch (e) { r.push(e.name); } class Sub extends Iterator {} r.push(new Sub() instanceof Iterator); function F() {} F.prototype = null; r.push(Object.getPrototypeOf(Reflect.construct(Iterator, [], F)) === Iterator.prototype); return r.join(); });
show('Iterator.prototype dispose', function () { var log = []; var it = src(log, 1); Iterator.prototype[Symbol.dispose].call(it); return log.join() + ' ' + typeof Iterator.prototype[Symbol.dispose]; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("iterator_helper_error_paths")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_eval_in_odd_contexts(js, golden, tier):
    """CATCHES: an eval that returns wrong completion values, leaks or isolates var/let bindings incorrectly in strict, parameter, arrow, class-field, static-block, with and generator contexts, treats optional/aliased calls as direct eval, or misses var/lexical conflict and new.target/super early errors fails this."""
    code = SHOW + r"""var geval = eval;
show('completion values', function () { return [eval('1; 2;'), eval('if (true) 3;'), eval('if (false) 3;'), eval('do { 4; } while (false)'), eval('for (var i = 0; i < 2; i++) i * 10;'), eval('L: { 5; break L; }'), eval('try { 6; } finally { 7; }'), eval('switch (1) { case 1: 8; }'), eval('var x = 9;'), eval('function f() {}'), eval(''), eval('{}'), eval('while (false);'), eval('1; try { } catch (e) {}'), eval('2; if (true) {}'), eval('3; var z;'), eval('with ({}) 11'), eval('class C {}'), eval('let q = 1; q + 1')].map(String).join(','); });
show('non-string eval', function () { var o = {}; return [eval(5), eval(o) === o, eval(null), eval(), typeof eval(Symbol.iterator), eval(new String('1+1')) instanceof String].join(); });
show('direct eval sees locals', function () { var local = 'L'; return eval('local') + ' ' + (0, eval)('typeof local'); });
show('direct eval var leaks into function', function () { eval('var leaked = 1'); return typeof leaked; });
show('direct eval let does not leak', function () { eval('let notLeaked = 1'); return typeof notLeaked; });
show('strict direct eval var isolation', function () { 'use strict'; eval('var isolated = 1'); return typeof isolated; });
show('eval in strict string', function () { eval('"use strict"; var inner = 1'); return typeof inner; });
show('eval in parameter default', function () { function f(a = eval('var fromParam = 7; fromParam')) { return a + ' ' + typeof fromParam; } return f(); });
show('eval arguments in parameter default', function () { function f(a, b = eval('arguments.length')) { return b; } return f(1); });
show('eval in arrow sees outer this', function () { var o = { m: function () { return (() => eval('this'))(); } }; return o.m() === o; });
show('eval new.target', function () { function F() { return eval('new.target'); } return [F() === undefined, Reflect.construct(F, []) instanceof F].join(); });
show('eval new.target in global', function () { return geval('new.target'); });
show('eval super property in method', function () { var base = { greet: function () { return 'base'; } }; var o = { __proto__: base, greet() { return eval('super.greet()') + '+derived'; } }; return o.greet(); });
show('eval super in function-valued property', function () { var o = { greet: function () { return eval('super.x'); } }; return o.greet(); });
show('eval super call in derived constructor', function () { class A { constructor() { this.made = 'A'; } } class B extends A { constructor() { eval('super()'); this.after = this.made + '!'; } } return new B().after; });
show('eval super outside method', function () { return eval('super.x'); });
show('eval in class field initializer', function () { var log = []; class C { a = eval('this.constructor.name'); b = eval('typeof arguments'); } try { new C(); } catch (e) { return e.name; } });
show('eval in class field initializer ok', function () { class C { a = eval('this.constructor.name'); } return new C().a; });
show('eval in static block', function () { var r; class C { static x = 5; static { r = eval('this.x + 1'); } } return r; });
show('eval var conflicts with let', function () { let blocked = 1; try { eval('var blocked = 2'); } catch (e) { return e.name; } return 'no error'; });
show('eval var in block conflicts', function () { { let inner = 1; try { eval('var inner'); } catch (e) { return e.name; } } return 'no'; });
show('eval function declaration hoists', function () { eval('function hoisted() { return "h"; }'); return hoisted(); });
show('eval in with', function () { var o = { wv: 'from with' }; with (o) { return eval('wv'); } });
show('eval var in with binds to function', function () { var o = {}; with (o) { eval('var created = 1'); } return typeof created + ' ' + ('created' in o); });
show('eval arguments assignment sloppy', function () { function f(a) { eval('arguments = 5'); return arguments; } return f(1); });
show('eval delete var', function () { eval('var del = 1'); return (delete del) + ' ' + typeof del; });
show('indirect eval global var', function () { geval('var indirectGlobal = 1'); return Object.getOwnPropertyDescriptor(globalThis, 'indirectGlobal').configurable; });
show('indirect eval this', function () { return geval('this') === globalThis; });
show('indirect forms', function () { var local = 'local'; var r = []; r.push((0, eval)('typeof local')); r.push(eval?.('typeof local')); r.push(globalThis.eval('typeof local')); var e = eval; r.push(e('typeof local')); r.push([eval][0]('typeof local')); return r.join(); });
show('eval syntax errors', function () { var r = []; ['(', 'return 1', 'break', 'continue', 'let let = 1', 'var a; let a;', 'new.target', 'yield 1', '}', '/a/gg', '"\\u{110000}"', 'a => {', '1 = 2', 'super()'].forEach(function (s) { try { eval(s); r.push(s + '=ok'); } catch (e) { r.push(s + '=' + e.name); } }); return r.join(' | '); });
show('eval returns function', function () { var f = eval('(function named() { return "fn"; })'); return f() + ' ' + f.name; });
show('nested eval', function () { var depth = 'outer'; return eval('var depth2 = "mid"; eval("depth + depth2")'); });
show('eval string with BOM and line terminators', function () { return eval('﻿ 1 +  2'); });
show('eval in generator', function () { function* g() { var x = yield 1; yield eval('x * 2'); } var it = g(); it.next(); return it.next(21).value; });
show('eval yield as identifier sloppy', function () { var yield_ = eval('var yield = 3; yield'); return yield_; });
show('eval await as identifier', function () { return eval('var await = 4; await'); });
show('eval in async function', function () { var result = 'pending'; (async function () { var v = await 1; result = eval('v + 1'); })(); return result; });
show('eval let shadow and TDZ', function () { let t = 'outer'; return eval('{ let t = "inner"; t }') + ' ' + t; });
show('eval TDZ', function () { try { eval('tdz; let tdz = 1;'); } catch (e) { return e.name; } });
show('eval global let collision', function () { geval('let collide = 1'); try { geval('var collide = 2'); } catch (e) { return e.name; } return 'no error'; });
show('eval global function non-configurable conflict', function () { try { geval('function NaN() {}'); } catch (e) { return e.name; } return 'no error'; });
show('eval var undefined global', function () { try { geval('var undefined = 1'); } catch (e) { return e.name; } return 'ok ' + typeof undefined; });
show('eval html comments', function () { return eval('1 <!-- comment\n+ 2'); });
show('eval html close comment', function () { return eval('3\n--> comment\n+ 4'); });
show('Function in eval', function () { var local = 1; return eval('Function("return typeof local")()'); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("eval_in_odd_contexts")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_annex_b_legacy_features(js, golden, tier):
    """CATCHES: an engine missing Annex B legacy behaviour (octal literals and escapes, labelled and if-statement function declarations, for-in var initializers, HTML-like comments, getYear/setYear/toGMTString, RegExp.prototype.compile and legacy statics, permissive regexp syntax, duplicate __proto__ rules) or applying it in the wrong places fails this."""
    code = SHOW + r"""show('legacy octal literals', function () { return [010, 0777, 08, 09.5, 019, 00, 0.5, eval('07 + 1')].join(); });
show('legacy octal escapes', function () { return ['\101', escape('\0'), escape('\08'), '\8', '\9', escape('\377'), '\400'.length, '\1a'.charCodeAt(0), '\7'.charCodeAt(0), '\12'.charCodeAt(0), escape('\0' + '1')].join('|'); });
show('octal in template is error', function () { try { eval('`\\101`'); } catch (e) { return e.name; } return 'no error'; });
show('tagged template octal raw', function () { return (function (s) { return s[0] + '|' + s.raw[0]; })`\101`; });
show('labelled function declaration', function () { return eval('L: function lf() { return "labelled"; } lf()'); });
show('if function declaration', function () { if (true) function iff() { return 'if-fn'; } return iff(); });
show('if-else function declaration', function () { if (false) function a1() {} else function a2() { return 'else-fn'; } return a2() + ' ' + typeof a1; });
show('for-in var initializer', function () { var log = []; for (var i = 'init' in {}) {} for (var j = 'start' in { k: 1 }) log.push(j); return i + ' ' + log.join(); });
show('block function hoisting', function () { var r = [typeof bf]; { function bf() { return 'block'; } } r.push(bf()); return r.join(); });
show('html comments in eval', function () { return eval('var h = 1; <!-- ignored\nh += 1;\n  --> also ignored\nh'); });
show('html close comment after block comment', function () { return eval('var c = 5;\n/* x */ --> ignored\nc'); });
show('html comment not in module-like context', function () { return eval('x = 3; x <!--y\n'); });
show('getYear/setYear', function () { var d = new Date(Date.UTC(1999, 5, 15)); var r = [d.getYear()]; d.setYear(99); r.push(d.getUTCFullYear()); d.setYear(2005); r.push(d.getUTCFullYear(), d.getYear()); d.setYear(NaN); r.push(d.getTime(), new Date(NaN).getYear()); return r.join(); });
show('setYear on invalid date', function () { var d = new Date(NaN); d.setYear(2000); return d.getUTCFullYear() + ' ' + d.getUTCMonth() + ' ' + d.getUTCDate(); });
show('toGMTString', function () { return [Date.prototype.toGMTString === Date.prototype.toUTCString, new Date(0).toGMTString()].join(' '); });
show('RegExp compile', function () { var r = /a/g; r.lastIndex = 3; var same = r.compile('b+', 'i'); return [same === r, r.source, r.flags, r.lastIndex, r.test('BBB'), r.compile(/x/m).source, r.flags, r.compile().source].join(' '); });
show('RegExp compile bad flags', function () { return /a/.compile('a', 'gg'); });
show('RegExp compile regexp with flags', function () { return /a/.compile(/b/, 'g'); });
show('RegExp compile subclass', function () { class R extends RegExp {} return new R('a').compile('b'); });
show('RegExp compile cross realm', function () { var other = $262.createRealm().global; var r = new other.RegExp('a'); return RegExp.prototype.compile.call(r, 'b'); });
show('legacy regexp syntax', function () { return [/\1(a)/.test('a'), /{/.test('{'), /a{/.test('a{'), /}/.test('}'), /]/.test(']'), /\c/.test('\\c'), /[\c]/.test('c'), /\p/.test('p'), /\8/.test('8'), /(?=a)*/.test(''), /\u{2}/.test('uu'), /[a-\d]/.test('-'), /x{2,1/.test('x{2,1'), /\_/.test('_')].join(); });
show('legacy static properties', function () { /(\d)(\d)?(?<n>x)?/.exec('a12b'); var r = [RegExp.$1, RegExp.$2, RegExp.$3, RegExp.$9, RegExp.lastMatch, RegExp['$+'], RegExp['$`'], RegExp["$'"], RegExp.input, RegExp.$_]; RegExp.input = 'set'; r.push(RegExp.$_); return r.join(','); });
show('legacy statics descriptors', function () { return ['$1', 'input', '$_', 'lastMatch', 'leftContext'].map(function (k) { var d = Object.getOwnPropertyDescriptor(RegExp, k); return k + ':' + typeof d.get + '/' + typeof d.set + '/' + d.enumerable; }).join(' '); });
show('legacy statics on subclass', function () { class R extends RegExp {} new R('(z)').exec('z'); try { return R.$1; } catch (e) { return e.name; } });
show('legacy statics bad receiver', function () { return Object.getOwnPropertyDescriptor(RegExp, '$1').get.call({}); });
show('substr/trimLeft/trimRight', function () { return ['abcdef'.substr(-3, 2), '  x '.trimLeft() + '|', '  x '.trimRight() + '|', String.prototype.trimRight.name, String.prototype.trimLeft === String.prototype.trimStart].join(' '); });
show('arguments.callee and caller', function () { function f() { return arguments.callee === f; } return f(); });
show('__proto__ duplicate in literal', function () { try { eval('({ __proto__: null, __proto__: null })'); } catch (e) { return e.name; } return 'no error'; });
show('__proto__ duplicate allowed with shorthand', function () { var __proto__ = 1; var o = eval('({ __proto__, __proto__: null })'); return Object.getPrototypeOf(o) + ' ' + o.__proto__; });
show('__proto__ in destructuring pattern ok', function () { var a, b; eval('({ __proto__: a, __proto__: b } = { x: 1 })'); return (a === Object.prototype) + ' ' + (b === Object.prototype); });
show('escape/unescape round trip', function () { var s = 'Ünïcødé ✓ 😀 \u0000'; return escape(s) + ' ' + (unescape(escape(s)) === s); });
show('String HTML methods', function () { return ['x'.anchor('a"b'), 'x'.fontcolor('"red"'), 'x'.bold(), 'x'.link('l')].join(''); });
show('Date parse legacy formats', function () { return [Date.parse('Thu, 01 Jan 1970 00:00:00 GMT'), Date.parse('1970-01-01T00:00:00Z'), Date.parse('Jan 2, 1970 UTC')].join(); });
show('sloppy-only with and delete', function () { var o = { w: 1 }; with (o) { w = 2; } var g = 1; return o.w + ' ' + eval('delete g'); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("annex_b_legacy_features")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_global_object_bindings_and_accessors(js, golden, tier):
    """CATCHES: a global object whose NaN/Infinity/undefined are writable or configurable, whose accessor properties are not invoked by identifier reads/writes, that lets strict code create implicit globals or write read-only globals, or gives wrong descriptors to global functions fails this."""
    code = SHOW + r"""show('global constants', function () { var r = []; ['NaN', 'Infinity', 'undefined', 'globalThis', 'parseInt', 'Math', 'JSON', 'Reflect', 'Object', 'eval'].forEach(function (k) { var d = Object.getOwnPropertyDescriptor(globalThis, k); r.push(k + ':' + [d.writable, d.enumerable, d.configurable].map(Number).join('')); }); return r.join(' '); });
show('assign constants sloppy', function () { NaN = 1; undefined = 2; Infinity = 3; return [NaN, undefined, Infinity].join(); });
show('assign undefined strict', function () { 'use strict'; undefined = 1; });
show('assign NaN strict', function () { 'use strict'; NaN = 1; });
show('globalThis', function () { return [globalThis === this, typeof globalThis, globalThis.globalThis === globalThis, Object.getPrototypeOf(globalThis) !== null, typeof global, global === globalThis].join(); });
show('global getter accessed by name', function () { var n = 0; Object.defineProperty(globalThis, 'counter', { get: function () { return ++n; }, configurable: true }); var a = counter; var b = counter; var t = typeof counter; delete globalThis.counter; return [a, b, t, typeof counter].join(); });
show('global setter by assignment', function () { var log = []; Object.defineProperty(globalThis, 'sink', { set: function (v) { log.push(v); }, get: function () { return 'sink-get'; }, configurable: true }); sink = 1; sink += 1; var r = log.join() + ' ' + sink; delete globalThis.sink; return r; });
show('global getter throws', function () { Object.defineProperty(globalThis, 'boom', { get: function () { throw new EvalError('global getter'); }, configurable: true }); try { return boom; } finally { delete globalThis.boom; } });
show('global non-writable strict assignment', function () { Object.defineProperty(globalThis, 'frozenGlobal', { value: 1, writable: false, configurable: true }); try { (function () { 'use strict'; frozenGlobal = 2; })(); } catch (e) { delete globalThis.frozenGlobal; return e.name; } });
show('implicit global creation', function () { (function () { implicitGlobal = 'made'; })(); var d = Object.getOwnPropertyDescriptor(globalThis, 'implicitGlobal'); var r = [implicitGlobal, d.configurable, d.enumerable, delete globalThis.implicitGlobal, typeof implicitGlobal]; return r.join(); });
show('strict implicit global', function () { 'use strict'; undeclaredStrict = 1; });
show('typeof undeclared', function () { return typeof notDeclaredAnywhere; });
show('delete global var', function () { return eval('var gvd = 1; delete gvd') + ' ' + delete globalThis.Math_nonexistent; });
show('global property via this in sloppy function', function () { return (function () { return this.parseFloat === parseFloat; })(); });
show('globalThis property descriptor', function () { var d = Object.getOwnPropertyDescriptor(globalThis, 'globalThis'); return [d.writable, d.enumerable, d.configurable].join(); });
show('global proto chain', function () { var p = Object.getPrototypeOf(globalThis); var depth = 0; while (p) { depth++; p = Object.getPrototypeOf(p); } return depth > 0; });
show('global symbol properties', function () { return Object.prototype.toString.call(globalThis).length > 8; });
show('global var redefinition', function () { globalThis.eval('var redefined = 1'); globalThis.eval('var redefined = 2'); return redefined; });
show('print builtin', function () { return typeof print + ' ' + print.length; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("global_object_bindings_and_accessors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_typed_array_object_reflection(js, golden, tier):
    """CATCHES: Object.keys/values/entries/getOwnPropertyNames/getOwnPropertyDescriptor/defineProperty/delete/in/for-in on typed arrays that list metadata properties, accept non-canonical or out-of-bounds indices, allow non-configurable element definitions, or mis-report detached and length-tracking views fail this."""
    code = SHOW + r"""show('keys/values/entries', function () { var t = new Int16Array([5, -6, 7]); t.extra = 'x'; t[String(Symbol.iterator)] = 'symstr'; return [Object.keys(t).join(), Object.values(t).join(), JSON.stringify(Object.entries(t)), Object.getOwnPropertyNames(t).join(), Reflect.ownKeys(t).length].join(' | '); });
show('non-enumerable expando', function () { var t = new Uint8Array(2); Object.defineProperty(t, 'hidden', { value: 1, enumerable: false }); t.shown = 2; return Object.keys(t).join() + ' | ' + Object.values(t).join() + ' | ' + Object.getOwnPropertyNames(t).join(); });
show('gopd', function () { var t = new Float32Array([1.5]); return [JSON.stringify(Object.getOwnPropertyDescriptor(t, 0)), Object.getOwnPropertyDescriptor(t, 1), Object.getOwnPropertyDescriptor(t, '-0'), Object.getOwnPropertyDescriptor(t, '0.0'), Object.getOwnPropertyDescriptor(t, 'length')].join(' | '); });
show('defineProperty on elements', function () { var t = new Uint8Array(2); var r = [Reflect.defineProperty(t, 0, { value: 9 }), t[0], Reflect.defineProperty(t, 0, { value: 1, writable: false }), Reflect.defineProperty(t, 0, { value: 1, enumerable: false }), Reflect.defineProperty(t, 0, { value: 1, configurable: false }), Reflect.defineProperty(t, 0, { get: function () {} }), Reflect.defineProperty(t, 5, { value: 1 }), Reflect.defineProperty(t, '-0', { value: 1 }), Reflect.defineProperty(t, '1.5', { value: 1 }), Reflect.defineProperty(t, 'x', { value: 1 }), t.x]; return r.join(); });
show('defineProperty element type coercion', function () { var t = new Uint8Array(1); Object.defineProperty(t, 0, { value: '300' }); return t[0]; });
show('in and delete', function () { var t = new Uint8Array(2); return [0 in t, 2 in t, '-0' in t, '1.5' in t, delete t[0], delete t[5], delete t.foo, t[0]].join(); });
show('strict delete element', function () { 'use strict'; var t = new Uint8Array(2); delete t[0]; });
show('assign through Object.assign', function () { var t = new Uint8Array(3); Object.assign(t, [1, 2, 3, 4]); return Array.from(t).join() + ' ' + t[3]; });
show('freeze/seal empty and isFrozen', function () { return [Object.isFrozen(new Uint8Array(0)), Object.isFrozen(Object.preventExtensions(new Uint8Array(0))), Object.isSealed(Object.preventExtensions(new Uint8Array(1)))].join(); });
show('for-in', function () { var t = new Uint8Array(3); t.p = 1; var ks = []; for (var k in t) ks.push(k); return ks.join(); });
show('spread and Array.from', function () { var t = new Uint16Array([1, 2]); return [...t].join() + ' ' + Array.from(t, function (x) { return x * 2; }).join() + ' ' + Array.prototype.slice.call(t).join(); });
show('out-of-bounds after detach', function () { var t = new Uint8Array(4); $262.detachArrayBuffer(t.buffer); return [t.length, t.byteLength, t.byteOffset, t[0], Object.keys(t).length, 0 in t, Reflect.set(t, 0, 1)].join(); });
show('length-tracking resize', function () { var buf = new ArrayBuffer(4, { maxByteLength: 8 }); var t = new Uint8Array(buf); buf.resize(2); var r = [t.length, Object.keys(t).join()]; buf.resize(6); r.push(t.length, Object.keys(t).length); return r.join(' '); });
show('meta getters bad receiver', function () { var proto = Object.getPrototypeOf(Int8Array.prototype); var r = []; ['length', 'byteLength', 'byteOffset', 'buffer'].forEach(function (k) { try { Object.getOwnPropertyDescriptor(proto, k).get.call({}); r.push('ok'); } catch (e) { r.push(k + ':' + e.name); } }); return r.join(' '); });
show('meta getters on detached', function () { var t = new Uint8Array(new ArrayBuffer(8), 2, 3); $262.detachArrayBuffer(t.buffer); var proto = Object.getPrototypeOf(Int8Array.prototype); return ['length', 'byteLength', 'byteOffset'].map(function (k) { return Object.getOwnPropertyDescriptor(proto, k).get.call(t); }).join() + ' ' + (Object.getOwnPropertyDescriptor(proto, 'buffer').get.call(t) instanceof ArrayBuffer); });
show('meta getters offset', function () { var t = new Uint8Array(new ArrayBuffer(8), 2, 3); return [t.length, t.byteLength, t.byteOffset, t.buffer.byteLength].join(); });
show('toStringTag getter', function () { var g = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Int8Array.prototype), Symbol.toStringTag).get; return [g.call(new Int8Array(1)), g.call({}), g.call(5), g.call(new BigUint64Array(1))].join(); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("typed_array_object_reflection")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_dead_result_regexp_and_array_calls_in_hot_loops(js, golden, tier):
    """CATCHES: a JIT that elides discarded RegExp literal exec/replace/match/split calls, discarded global/sticky regexp exec and replace, or discarded Array.prototype.pop in hot loops without still updating lastIndex, the legacy RegExp statics and array lengths (or that ignores non-writable lengths) fails this."""
    code = r"""var words = ['z1', 'yz2', 'none', 'z3z4', 'q'];
var subjects = ['foo1', 'boo2', 'xyz', 'moon'];
function loopExec() { for (var i = 0; i < words.length; i++) { /z(\d)/.exec(words[i]); } return RegExp.$1; }
function constExec() { for (var i = 0; i < 3; i++) { /(c)(o)nst/.exec('const'); } return RegExp.$2; }
function loopReplace() { for (var i = 0; i < subjects.length; i++) { subjects[i].replace(/o(o|\d)/, 'X'); } return RegExp.$1 + RegExp.lastMatch; }
function loopReplaceG() { for (var i = 0; i < subjects.length; i++) { subjects[i].replace(/o/g, '0'); } return RegExp.lastMatch + RegExp.leftContext; }
function loopMatch() { for (var i = 0; i < words.length; i++) { words[i].match(/(z)(\d)/); } return RegExp.$2 + RegExp.rightContext; }
function loopMatchG() { for (var i = 0; i < words.length; i++) { words[i].match(/z\d/g); } return RegExp.lastMatch + '/' + RegExp.input; }
function loopSplit() { for (var i = 0; i < subjects.length; i++) { subjects[i].split(/o/); } return RegExp.input; }
var g = /o/g;
function loopGlobalExec() { for (var i = 0; i < subjects.length; i++) { g.exec(subjects[i]); } return g.lastIndex; }
var reVar = /(o)(o)?/g, stickyVar = /b/y, plainVar = /(\d)/;
function replaceWithVar(s) { s.replace(reVar, '-'); s.replace(plainVar, '#'); return reVar.lastIndex + ':' + RegExp.$1; }
function replaceSticky(s) { stickyVar.lastIndex = 0; s.replace(stickyVar, 'B'); return stickyVar.lastIndex + RegExp.lastMatch; }
function splitWithVar(s) { s.split(plainVar); return RegExp.input; }
function execVar(s) { plainVar.exec(s); reVar.exec(s); return reVar.lastIndex; }
function popAll(a) { var n = 0; while (a.length) { a.pop(); n++; } return n; }
function popSome(a) { a.pop(); a.pop(); return a.length; }
var log = [];
for (var n = 0; n < 300; n++) {
  var arr = [1, 2, 3, n]; var holey = [1, , 3]; var frozenLen = [1, 2]; Object.defineProperty(frozenLen, 'length', { writable: false });
  var popped = []; try { popped.push(popSome(holey), popAll(arr)); popSome(frozenLen); } catch (e) { popped.push(e.name + ':' + frozenLen.length); }
  var r = [loopExec(), constExec(), loopReplace(), loopReplaceG(), loopMatch(), loopMatchG(), loopSplit(), loopGlobalExec(), replaceWithVar('foo' + n + 'boo'), replaceSticky('bab'), splitWithVar('a1b' + n), execVar('o' + n + 'oo'), popped.join('/')];
  if (n % 100 === 0 || n === 299) log.push(n + ': ' + r.join(' | '));
}
RegExp.prototype.exec = function (s) { return null; };
var afterPatch = [loopExec(), constExec()];
console.log(log.join('\n'));
console.log('after exec patch: ' + afterPatch.join(' | ') + ' ' + /x/.test('x'));
"""
    r = js(code, *tier)
    assert out(r) == golden("dead_result_regexp_and_array_calls_in_hot_loops")
    assert (r.returncode, r.stderr) == (0, b"")


def test_uncaught_throw_report_formats(run, workdir):
    """CATCHES: a CLI that formats uncaught throws wrongly (primitives, plain objects with message, nameless constructors, Error subclasses, errors whose name/message getters throw or whose constructor lacks a name) or does not flush earlier console output before exiting with status 1 fails this."""
    cases = [
        ("throw 5", "Uncaught Number: 5\n"),
        ("throw 'str'", "Uncaught String: str\n"),
        ("throw null", "Uncaught null\n"),
        ("throw undefined", "Uncaught undefined\n"),
        ("throw 10n", "Uncaught BigInt: 10\n"),
        ("throw true", "Uncaught Boolean: true\n"),
        ("throw {message: 'm'}", "Uncaught Object: m\n"),
        ("throw Object.create(null)", "Uncaught \n"),
        ("throw new RangeError('r')", "Uncaught RangeError: r\n"),
        ("class MyErr extends Error {}; throw new MyErr('sub')", "Uncaught Error: sub\n"),
        ("class Named extends Error { get name() { return 'Named'; } }; throw new Named('n')", "Uncaught Named: n\n"),
        ("function Custom() { this.message = 'custom'; } throw new Custom()", "Uncaught Custom: custom\n"),
        ("var e = new Error('x'); e.name = ''; throw e", "Uncaught x\n"),
        ("throw [1, 2]", "Uncaught Array: \n"),
        ("throw new AggregateError([1], 'agg')", "Uncaught AggregateError: agg\n"),
        ("var o = {}; Object.defineProperty(o, 'message', { get: function () { throw 1; } }); throw o", "Uncaught Object: \n"),
        ("throw function namedFn() {}", "Uncaught namedFn: \n"),
        ("throw {name: 'N', message: 'M'}", "Uncaught N: M\n"),
        ("throw {name: 5}", "Uncaught 5: \n"),
        ("var e = new Error('m'); e.name = undefined; throw e", "Uncaught Error: m\n"),
        ("throw new Error('multi\\nline')", "Uncaught Error: multi\nline\n"),
        ("(function deep(n) { if (n === 0) throw new TypeError('deep ' + n); deep(n - 1); })(50)", "Uncaught TypeError: deep 0\n"),
    ]
    got = []
    for code, _ in cases:
        r = run(["-e", "console.log('before'); " + code])
        got.append((code, out(r), err(r), r.returncode))
    assert got == [(code, "before\n", expected, 1) for code, expected in cases]
    (workdir / "thrower.js").write_text("console.log('file before');\nfunction f() { throw new SyntaxError('from file'); }\nf();\n", encoding="utf-8")
    r = run(["thrower.js"])
    assert (out(r), err(r), r.returncode) == ("file before\n", "Uncaught SyntaxError: from file\n", 1)
    r = run([], input="console.log('stdin before'); throw new TypeError('from stdin');")
    assert (out(r), err(r), r.returncode) == ("stdin before\n", "Uncaught TypeError: from stdin\n", 1)


@pytest.mark.parametrize("tier", TIERS)
def test_decorator_runtime_semantics(js, golden, tier):
    """CATCHES: a decorator implementation that passes wrong context objects (kind/name/static/private/access/addInitializer), ignores replacement values from class/method/getter/setter decorators, applies field initializer transforms or accessor get/set/init results wrongly, runs addInitializer callbacks at the wrong time, or accepts invalid decorator return values fails this."""
    code = SHOW + r"""function ctxInfo(c) { return [c.kind, typeof c.name === 'symbol' ? c.name.toString() : c.name, c.static, c.private, Object.keys(c.access).sort().join('/'), typeof c.addInitializer, c.metadata].join(','); }
show('method/getter/setter/field/accessor contexts', function () { var log = []; function rec(v, c) { log.push(ctxInfo(c) + ':' + typeof v); } var s = Symbol('sym'); class C { @rec m() {} @rec get g() { return 1; } @rec set g(v) {} @rec f = 1; @rec accessor a = 2; @rec static sm() {} @rec static #pf = 3; @rec #pm() {} @rec [s]() {} @rec static get #sg() { return 1; } } return log.join(' | '); });
show('class decorator replaces class', function () { function replace(C, ctx) { return class extends C { extra() { return 'extra ' + ctx.name; } }; } @replace class Orig { base() { return 'base'; } } var o = new Orig(); return o.base() + ' ' + o.extra() + ' ' + Orig.name; });
show('class decorator bad return', function () { function bad() { return 5; } @bad class X {} });
show('getter/setter decorators wrap', function () { function upper(fn, ctx) { return function () { return String(fn.call(this)).toUpperCase(); }; } function logSet(fn, ctx) { return function (v) { fn.call(this, v + '!'); }; } class C { #v = 'x'; @upper get v() { return this.#v; } @logSet set v(x) { this.#v = x; } } var c = new C(); c.v = 'set'; return c.v; });
show('getter decorator bad return', function () { function bad() { return 1; } class C { @bad get g() { return 1; } } });
show('field decorator initializer transforms', function () { function times(n) { return function (v, ctx) { return function (init) { return init * n; }; }; } class C { @times(2) @times(10) f = 3; @times(5) static sf = 1; @times(7) #p = 1; getP() { return this.#p; } } var c = new C(); return c.f + ' ' + C.sf + ' ' + c.getP(); });
show('field decorator bad return', function () { function bad() { return {}; } class C { @bad f = 1; } });
show('field decorator access', function () { var acc; function grab(v, ctx) { acc = ctx.access; } class C { @grab #secret = 's'; @grab pub = 'p'; } var c = new C(); var c2 = new C(); return acc.get(c) + ' ' + (acc.set(c, 'changed'), acc.get(c)) + ' ' + acc.get(c2); });
show('private field access get/set', function () { var acc; function grab(v, ctx) { acc = ctx.access; } class C { @grab #secret = 's'; read() { return this.#secret; } } var c = new C(); acc.set(c, 'via access'); return c.read() + ' ' + acc.get(c); });
show('accessor decorator get/set/init', function () { function track(pair, ctx) { return { get() { return 'got:' + pair.get.call(this); }, set(v) { pair.set.call(this, v * 2); }, init(v) { return v + 100; } }; } class C { @track accessor a = 1; @track static accessor s = 2; } var c = new C(); var before = c.a; c.a = 5; return before + ' ' + c.a + ' ' + C.s; });
show('accessor decorator partial and undefined', function () { function onlyInit() { return { init(v) { return 'init:' + v; } }; } function nothing() {} class C { @onlyInit @nothing accessor a = 'x'; } return new C().a; });
show('accessor decorator bad return', function () { function bad() { return 1; } class C { @bad accessor a = 1; } });
show('private accessor decorator', function () { function track(pair, ctx) { return { get() { return ctx.name + '=' + pair.get.call(this); } }; } class C { @track accessor #pa = 7; read() { return this.#pa; } } return new C().read(); });
show('addInitializer order', function () { var log = []; function init(tag) { return function (v, ctx) { ctx.addInitializer(function () { log.push(tag + ' this=' + (typeof this === 'function' ? 'class' : 'instance')); }); }; } @init('class') class C { @init('method') m() {} @init('static') static s() {} @init('field') f = 1; constructor() { log.push('ctor body'); } } log.push('defined'); new C(); return log.join(', '); });
show('addInitializer non-callable', function () { function bad(v, ctx) { ctx.addInitializer(5); } class C { @bad m() {} } });
show('decorator not callable', function () { var notFn = 5; class C { @notFn m() {} } });
show('decorated static field this', function () { function d(v, ctx) { return function (init) { return init + typeof this; }; } class C { @d static f = 'x'; } return C.f; });
show('decorator with member chain and call', function () { var lib = { deco: { make: function (tag) { return function (v, ctx) { return function () { return tag + ':' + v.call(this); }; }; } } }; class C { @lib.deco.make('T') m() { return 'm'; } @(lib.deco.make('P')) n() { return 'n'; } } var c = new C(); return c.m() + ' ' + c.n(); });
show('accessor keyword without decorators', function () { class C { accessor a = 1; static accessor b = 2; accessor #c = 3; getC() { return this.#c; } } var c = new C(); c.a = 10; var d = Object.getOwnPropertyDescriptor(C.prototype, 'a'); return [c.a, C.b, c.getC(), typeof d.get, typeof d.set, Object.keys(c).length].join(); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("decorator_runtime_semantics")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_class_runtime_edge_cases(js, golden, tier):
    """CATCHES: class evaluation with wrong super property/call semantics (computed super, returned objects, double super, this TDZ, extends null), missing private brand checks (non-extensible targets, re-initialization, method/accessor writes, wrong receivers), static 'prototype' via computed keys, wrong computed-key and field evaluation order, or broken static blocks fails this."""
    code = SHOW + r"""show('super computed member', function () { class A { greet() { return 'A.greet'; } get val() { return 'A.val:' + this.tag; } } class B extends A { constructor() { super(); this.tag = 'b'; } test() { var k = 'greet', v = 'val'; return super[k]() + ' ' + super[v] + ' ' + super['gr' + 'eet'].call({}); } } return new B().test(); });
show('super computed on null proto', function () { var o = { m() { return super['x']; } }; Object.setPrototypeOf(o, null); return o.m(); });
show('super property set', function () { class A {} class B extends A { m() { super.x = 1; super['y'] = 2; return this.x + this.y + ' ' + Object.hasOwn(A.prototype, 'x'); } } return new B().m(); });
show('super in object literal methods', function () { var base = { hi() { return 'base hi'; } }; var o = { __proto__: base, hi() { return super.hi() + ' + derived'; }, get g() { return super.hi(); } }; return o.hi() + ' | ' + o.g; });
show('super in static and arrow', function () { class A { static s() { return 'A.s'; } } class B extends A { static s() { var f = () => super.s(); return f() + '!'; } } return B.s(); });
show('super call returning other object', function () { class A { constructor() { return { replaced: true }; } } class B extends A { constructor() { super(); this.after = 1; } } var b = new B(); return JSON.stringify(b) + ' ' + (b instanceof B); });
show('super call with arrow capturing this', function () { class A {} class B extends A { constructor() { var getThis = () => this; super(); this.ok = getThis() === this; } } return new B().ok; });
show('super call twice', function () { class A {} class B extends A { constructor() { super(); super(); } } return new B(); });
show('this before super', function () { class A {} class B extends A { constructor() { this.x = 1; super(); } } return new B(); });
show('derived constructor no super', function () { class A {} class B extends A { constructor() {} } return new B(); });
show('derived constructor returns primitive', function () { class A {} class B extends A { constructor() { super(); return 1; } } return new B(); });
show('derived constructor returns object without super', function () { class A {} class B extends A { constructor() { return { manual: 1 }; } } return JSON.stringify(new B()); });
show('base constructor returns primitive', function () { class A { constructor() { return 5; } } return typeof new A(); });
show('super constructor not constructor', function () { class A {} class B extends A { constructor() { super(); } } Object.setPrototypeOf(B, Math.max); return new B(); });
show('extends null', function () { class N extends null { constructor() { return Object.create(N.prototype); } } var n = new N(); return [Object.getPrototypeOf(N.prototype), n instanceof N].join(); });
show('extends null implicit ctor', function () { class N extends null {} return new N(); });
show('extends non-constructor', function () { return class extends Math.max {}; });
show('extends with bad prototype', function () { function F() {} F.prototype = 3; return class extends F {}; });
show('private field on non-extensible', function () { class Base { constructor(o) { return o; } } class Stamp extends Base { #x = 1; static has(o) { return #x in o; } } var o = Object.preventExtensions({}); try { new Stamp(o); } catch (e) { return e.name + ': ' + e.message + ' ' + Stamp.has(o); } return 'stamped ' + Stamp.has(o); });
show('private field twice', function () { class Base { constructor(o) { return o; } } class Stamp extends Base { #x = 1; } var o = {}; new Stamp(o); return new Stamp(o); });
show('private method write', function () { class A { #m() {} write() { this.#m = 1; } } return new A().write(); });
show('private getter only write', function () { class A { get #g() { return 1; } write() { this.#g = 2; } } return new A().write(); });
show('private setter only read', function () { class A { set #s(v) {} read() { return this.#s; } } return new A().read(); });
show('private read wrong object', function () { class A { #p = 1; static read(o) { return o.#p; } } return A.read({}); });
show('private write wrong object', function () { class A { #p = 1; static write(o) { o.#p = 2; } } return A.write({}); });
show('private write primitive', function () { class A { #p = 1; static write(o) { o.#p = 2; } } return A.write(5); });
show('private static brand', function () { class A { static #s = 1; static read(o) { return o.#s; } } class B extends A {} return A.read(A) + ' ' + (function () { try { return A.read(B); } catch (e) { return e.name; } })(); });
show('private names with same spelling in different classes', function () { function make() { return class { #v = Math.random() > 2 ? 0 : 'v'; static get(o) { return o.#v; } }; } var X = make(), Y = make(); try { return Y.get(new X()); } catch (e) { return e.name; } });
show('static computed prototype key', function () { var k = 'prototype'; return class { static [k] = 1; }; });
show('static computed prototype method', function () { var k = 'prototype'; return class { static [k]() {} }; });
show('computed keys evaluation order', function () { var log = []; function k(n) { log.push(n); return n; } class C { [k('a')]() {} static [k('b')] = log.push('init b'); [k('c')] = log.push('init c'); } log.push('after class'); new C(); return log.join(','); });
show('field initializers this and new.target', function () { class C { a = this.constructor.name; b = typeof new.target; c = (() => this.a + '!')(); } var c = new C(); return [c.a, c.b, c.c].join(' '); });
show('static block this and scoping', function () { var r; class C { static #p = 'private'; static { var local = 1; r = this.name + ' ' + C.#p + ' ' + typeof local; } } return r + ' ' + typeof local; });
show('static block using', function () { var log = []; class C { static { using a = { [Symbol.dispose]() { log.push('disposed a'); } }; log.push('in block'); } } return log.join(', '); });
show('static block throws', function () { try { class C { static { throw new RangeError('in static block'); } } } catch (e) { return e.message + ' ' + typeof C; } });
show('class binding inside body is const', function () { class C { static rename() { C = 1; } } return C.rename(); });
show('class expression name scope', function () { var E = class Inner { static who() { return Inner.name; } }; return E.who() + ' ' + typeof Inner; });
show('class in TDZ during heritage', function () { try { class C extends C {} } catch (e) { return e.name; } });
show('class fields with ASI', function () { class C { a = 1
  b
  ['c'] = 3
  static d = 4;
  *gen() { yield 5; } } var c = new C(); return [c.a, c.b, c.c, C.d, c.gen().next().value].join(); });
show('accessors with odd names', function () { class C { get 'quoted key'() { return 'q'; } set 123(v) { this._n = v; } get [Symbol.toStringTag]() { return 'Tagged'; } static get static() { return 'static getter'; } } var c = new C(); c[123] = 'num'; return [c['quoted key'], c._n, String(c), C.static].join(' '); });
show('method enumerability and descriptors', function () { class C { m() {} static s() {} get g() { return 1; } } var d = Object.getOwnPropertyDescriptor(C.prototype, 'm'); var gd = Object.getOwnPropertyDescriptor(C.prototype, 'g'); return [d.enumerable, d.writable, d.configurable, gd.enumerable, Object.keys(C.prototype).length, Object.getOwnPropertyNames(C).sort().join()].join(); });
show('class constructor call without new', function () { class C {} return C(); });
show('generator and async methods', function () { class C { *g() { yield* [1, 2]; } async a() { return 3; } static async *ag() { yield 4; } } return [...new C().g()].join() + ' ' + typeof new C().a().then + ' ' + typeof C.ag().next; });
show('instance fields defined with define semantics', function () { var log = []; class Base { set x(v) { log.push('setter called'); } } class D extends Base { x = 1; } var d = new D(); return log.length + ' ' + Object.hasOwn(d, 'x'); });
show('derived default constructor passes args', function () { class A { constructor(...args) { this.args = args.join(); } } class B extends A {} return new B(1, 2, 3).args; });
show('derived default constructor with spread override', function () { var orig = Array.prototype[Symbol.iterator]; Array.prototype[Symbol.iterator] = function () { throw new Error('iterator used'); }; try { class A { constructor(a) { this.a = a; } } class B extends A {} return new B('no iterator').a; } finally { Array.prototype[Symbol.iterator] = orig; } });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("class_runtime_edge_cases")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_operators_references_and_delete_forms(js, golden, tier):
    """CATCHES: operator semantics with wrong ToPrimitive hints and valueOf/toString order, loose-equality or relational coercions, logical-assignment short-circuiting, compound-assignment evaluation order, increment coercions, delete on strings/super/proxies/optional chains, super property assignment, destructuring order and iterator closing, or optional-call this binding fails this."""
    code = SHOW + r"""function z(x) { return Object.is(x, -0) ? '-0' : String(x); }
show('arithmetic on non-numbers', function () { var o = { valueOf: function () { return 6; } }; return ['6' - '2', '3' * '4', '8' / '2', '7' % '4', '2' ** '3', '6' & '3', '6' | '1', '6' ^ '3', '1' << '3', '-16' >> '2', '-1' >>> '28', o - 1, o * o, [] - 1, [5] * 2, null - 1, undefined * 1, true + true, '5' - - '2', {} * 1, 'a' % 2, -'0', +[], +{}].map(z).join(' '); });
show('exponent edge cases', function () { var a = -1, b = Infinity, one = 1, nan = NaN, m = -8; return [a ** b, one ** nan, (-0) ** -1, m ** (1 / 3), 2 ** 1024, (-2) ** 0.5, 0 ** 0, nan ** 0, '-1' ** 'Infinity'].map(z).join(' '); });
show('toPrimitive protocol', function () { var log = []; var o = { [Symbol.toPrimitive]: function (hint) { log.push(hint); return hint === 'number' ? 42 : 'str'; } }; var r = [o + 1, o * 1, `${o}`, o == 'str', o < 50, String(o), Number(o), [o] + '']; return r.join(' ') + ' | ' + log.join(','); });
show('toPrimitive returns object', function () { var o = { [Symbol.toPrimitive]: function () { return {}; } }; return o + 1; });
show('toPrimitive not callable', function () { var o = { [Symbol.toPrimitive]: 5 }; return o + 1; });
show('valueOf/toString fallback order', function () { var log = []; var o = { valueOf: function () { log.push('valueOf'); return {}; }, toString: function () { log.push('toString'); return 'S'; } }; var r = o + '!'; var p = { valueOf: function () { log.push('v2'); return 1; }, toString: function () { log.push('t2'); return 'T'; } }; r += ' ' + String(p) + ' ' + (p * 3); return r + ' | ' + log.join(','); });
show('no primitive value', function () { return ({ valueOf: function () { return {}; }, toString: function () { return {}; } }) + 1; });
show('Date default hint', function () { var d = new Date(0); return typeof (d + 1) + ' ' + typeof (d - 1) + ' ' + (d - 1); });
show('loose equality matrix', function () { var vals = [0, -0, '', '0', null, undefined, NaN, false, [], [0], {}, 1n, '1', true]; var rows = []; for (var i = 0; i < vals.length; i++) { var row = ''; for (var j = 0; j < vals.length; j++) row += vals[i] == vals[j] ? '1' : '0'; rows.push(row); } return rows.join(' '); });
show('strict equality and SameValueZero', function () { return [NaN === NaN, 0 === -0, [NaN].includes(NaN), [NaN].indexOf(NaN), new Set([0, -0]).size, Object.is(0, -0)].join(); });
show('relational comparisons', function () { return ['a' < 'b', 'a' < 1, null >= 0, undefined >= 0, null > -1, [2] > 1, [1, 2] > 1, '10' > '9', 10 > '9', NaN <= NaN, 1n < 1.5, 'abc' < 'abd', {} < {}, ({ valueOf: function () { return 1; } }) <= 1].join(); });
show('comparison coercion order', function () { var log = []; var a = { valueOf: function () { log.push('a'); return 1; } }; var b = { valueOf: function () { log.push('b'); return 2; } }; var r = [a < b, a > b, a <= b, a >= b]; return r.join() + ' ' + log.join(''); });
show('in operator', function () { var p = new Proxy({}, { has: function (t, k) { return k === 'virtual'; } }); return ['length' in [], 0 in [1], 1 in [1], 'virtual' in p, 'other' in p, Symbol.iterator in [], 'x' in Object.create({ x: 1 })].join(); });
show('in with primitive', function () { return 'a' in 'abc'; });
show('typeof all kinds', function () { return [typeof 1, typeof 'a', typeof true, typeof undefined, typeof null, typeof {}, typeof [], typeof function () {}, typeof Symbol(), typeof 1n, typeof class {}, typeof new Proxy(function () {}, {}), typeof undeclaredThing].join(); });
show('void and comma', function () { var x = 0; var r = (x++, x++, x); return [void 0, void x++, r, x].join(); });
show('logical assignment short-circuit', function () { var log = []; var o = { get a() { log.push('get a'); return 1; }, set a(v) { log.push('set a ' + v); }, get n() { log.push('get n'); return null; }, set n(v) { log.push('set n ' + v); } }; o.a ||= 5; o.a &&= 6; o.a ??= 7; o.n ||= 8; o.n &&= 9; o.n ??= 10; var u; u ??= 'init'; var t = 0; t ||= 'or'; var f = 1; f &&= 'and'; return log.join(', ') + ' | ' + [u, t, f].join(); });
show('logical assignment on const', function () { const c = 1; c ||= 2; return c; });
show('logical assignment on const that assigns', function () { const c = 0; c ||= 2; return c; });
show('logical assignment names functions', function () { var f; f ??= function () {}; var g = null; g ||= () => {}; return f.name + ' ' + g.name; });
show('compound assignment evaluation order', function () { var log = []; var o = { get p() { log.push('get'); return 1; }, set p(v) { log.push('set ' + v); } }; function key() { log.push('key'); return 'p'; } function obj() { log.push('obj'); return o; } obj()[key()] += (log.push('rhs'), 2); return log.join(','); });
show('assignment to undeclared in strict via compound', function () { 'use strict'; undeclaredCompound += 1; });
show('increment coercions', function () { var s = '5', n = null, u, b = true, o = { valueOf: function () { return 9; } }, big = 9n; s++; n++; u++; b--; o++; big++; var d = '1.5'; --d; return [s, n, u, b, o, big, d, typeof s].map(String).join(' '); });
show('increment on symbol', function () { var s = Symbol(); s++; });
show('delete forms', function () { var o = { a: 1, b: { c: 2 } }; var arr = [1, 2]; var r = [delete o.a, 'a' in o, delete o.b.c, delete o['b'], delete arr[0], 0 in arr, arr.length, delete o.nope, delete 5, delete 'str', delete o?.missing?.x]; var n = null; r.push(delete n?.x, delete n?.[0]); var k = 'b'; var o2 = { b: 1 }; r.push(delete o2?.[k], 'b' in o2); return r.join(); });
show('delete string own props sloppy', function () { var s = 'abc'; return [delete s[0], delete s.length, delete s[5], delete s.foo, delete 'xy'[1]].join(); });
show('delete string own props strict', function () { 'use strict'; var s = 'abc'; return delete s[1]; });
show('delete string length strict', function () { 'use strict'; var s = 'abc'; return delete s.length; });
show('delete super property', function () { class A { m() { return delete super.x; } } return new A().m(); });
show('delete super computed property', function () { var log = []; class A { m() { return delete super[(log.push('key evaluated'), 'x')]; } } try { new A().m(); } catch (e) { return e.name + ': ' + e.message + ' ' + log.join(); } });
show('delete through nested proxies', function () { var t = { a: 1, b: 2 }; var inner = new Proxy(t, {}); var outer = new Proxy(inner, {}); var r = [delete outer.a, 'a' in t]; Object.defineProperty(t, 'b', { configurable: false }); r.push(delete outer.b); return r.join(); });
show('delete global and var bindings', function () { globalThis.deletableGlobal = 1; var r = [eval('delete deletableGlobal'), typeof deletableGlobal]; return r.join(); });
show('delete in with scope', function () { var o = { w: 1 }; var r; with (o) { r = delete w; } return r + ' ' + ('w' in o); });
show('super property assignment computed', function () { class A {} class B extends A { m() { var k = 'dyn'; super[k] = 'value'; super.fixed = 'f'; return this.dyn + this.fixed + ' ' + Object.hasOwn(this, 'dyn'); } } return new B().m(); });
show('super property assignment to setter', function () { var log = []; class A { set s(v) { log.push('A setter ' + v + ' this ok=' + (this instanceof B)); } } class B extends A { m() { super.s = 1; super['s'] = 2; } } new B().m(); return log.join(', '); });
show('destructuring assignment nested defaults', function () { var a, b, c, d, e, f, g; ({ a: [b] = [1], c: { d } = { d: 2 }, e = 3, ...f } = { x: 9, y: 8 }); [g = function () {}] = []; var h; ({ h = class {} } = {}); return [b, d, e, JSON.stringify(f), g.name, h.name].join(' '); });
show('destructuring assignment order', function () { var log = []; var src = { get a() { log.push('get a'); return 1; }, get b() { log.push('get b'); return 2; } }; var tgt = { set x(v) { log.push('set x ' + v); }, set y(v) { log.push('set y ' + v); } }; ({ a: tgt.x, b: tgt.y } = src); return log.join(', '); });
show('destructuring null', function () { var a; ({ a } = null); });
show('array destructuring closes iterator', function () { var log = []; var it = { [Symbol.iterator]: function () { return { next: function () { return { value: 1, done: false }; }, return: function () { log.push('closed'); return {}; } }; } }; var x; [x] = it; var y, z; [y, ...z] = [1, 2, 3]; return log.join() + ' ' + x + ' ' + z.join(); });
show('array destructuring default throws closes', function () { var log = []; var it = { [Symbol.iterator]: function () { return { next: function () { return { value: undefined, done: false }; }, return: function () { log.push('closed'); return {}; } }; } }; try { var [a = (function () { throw new Error('default threw'); })()] = it; } catch (e) { return e.message + ' ' + log.join(); } });
show('assignment to call expression', function () { var log = []; function f() { log.push('called'); return {}; } try { f() = 1; } catch (e) { return e.name + ' ' + log.join(); } });
show('chained assignment and this', function () { var a, b, c; a = b = c = { v: 1 }; return (a === c) + ' ' + ((function () { return this; }).call(5) instanceof Number); });
show('optional call this binding', function () { var o = { m: function () { return this === o; } }; var n = null; return [o.m?.(), o?.m(), (o?.m)(), n?.m(), o.missing?.(), n?.a.b.c()].join(); });
show('optional call on non-function', function () { var o = { m: 1 }; return o.m?.(); });
show('parenthesized optional chain call', function () { var n = null; return (n?.m)(); });
show('optional chain with private', function () { class A { #p = 'private'; static get(o) { return o?.#p; } } return A.get(new A()) + ' ' + A.get(null); });
show('spread holes and iterables', function () { function f() { return Array.prototype.map.call(arguments, String).join('|'); } return [f(...[1, , 3]), f(...'ab', ...new Set([7])), [...[, 'x']].length, Math.max(...[1, 5, 3])].join(' '); });
show('spread non-iterable', function () { function f() {} return f(...5); });
show('template literal coercions', function () { var o = { toString: function () { return 'T'; }, valueOf: function () { return 'V'; } }; return `${o}|${[1, 2]}|${null}|${undefined}|${1n}|${-0}`; });
show('template symbol', function () { return `${Symbol('s')}`; });
show('string concatenation with surrogates', function () { var hi = '\ud83d', lo = '\ude00'; return (hi + lo).length + ' ' + (hi + lo === '😀') + ' ' + [...(hi + lo)].length; });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("operators_references_and_delete_forms")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_async_builtins_from_async_dispose_and_keyed_promises(js, golden, tier):
    """CATCHES: Array.fromAsync that mishandles sync iterables of promises, primitive iterator results, rejected elements, async mappers, this-constructors and define failures without closing iterators, an %AsyncIteratorPrototype%[@@asyncDispose] that leaks return() values or errors, keyed/settled promise combinators with wrong key handling or double-settlement, Iterator.zip strict errors, Date toLocale*String option defaults, or special-cased string casing/indexOf fails this."""
    code = "var out = [];\n" + r"""async function t(label, f) { try { var r = await f(); out.push(label + ': ' + r); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
(async function () {
  await t('fromAsync sync iterable with promises', async () => (await Array.fromAsync(new Set([Promise.resolve('a'), 'b']))).join());
  await t('fromAsync sync iterable next throws', async () => { var it = { [Symbol.iterator]() { return { next() { throw new RangeError('next threw'); } }; } }; return Array.fromAsync(it); });
  await t('fromAsync sync iterator result primitive', async () => Array.fromAsync({ [Symbol.iterator]() { return { next() { return 5; } }; } }));
  await t('fromAsync async iterator result primitive', async () => Array.fromAsync({ [Symbol.asyncIterator]() { return { next() { return Promise.resolve(5); } }; } }));
  await t('fromAsync rejected element closes', async () => { var log = []; var it = { [Symbol.iterator]() { var i = 0; return { next() { i++; return i === 1 ? { value: Promise.reject(new EvalError('element rejected')), done: false } : { value: 2, done: false }; }, return() { log.push('sync return'); return {}; } }; } }; try { await Array.fromAsync(it); } catch (e) { return e.message + ' ' + log.join(); } });
  await t('fromAsync async mapfn', async () => (await Array.fromAsync([1, 2], async (v, i) => v * 10 + i)).join());
  await t('fromAsync mapfn throws closes async', async () => { var log = []; var it = { [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 1, done: false }); }, return() { log.push('async return'); return Promise.resolve({}); } }; } }; try { await Array.fromAsync(it, () => { throw new URIError('mapper'); }); } catch (e) { return e.message + ' ' + log.join(); } });
  await t('fromAsync mapfn with thisArg on array-like', async () => (await Array.fromAsync({ length: 2, 0: 'x', 1: Promise.resolve('y') }, function (v) { return v + this.s; }, { s: '!' })).join());
  await t('fromAsync this constructor array-like', async () => { function C(n) { this.n = n; } var r = await Array.fromAsync.call(C, { length: 2, 0: 1, 1: 2 }); return (r instanceof C) + ' ' + r.n + ' ' + r.length; });
  await t('fromAsync this constructor iterable', async () => { function C() { this.made = true; } var r = await Array.fromAsync.call(C, [1]); return (r instanceof C) + ' ' + r.made + ' ' + r[0]; });
  await t('fromAsync non-constructor this', async () => { var r = await Array.fromAsync.call(Math.max, [1]); return Array.isArray(r); });
  await t('fromAsync iterator method not callable', async () => Array.fromAsync({ [Symbol.asyncIterator]: 5 }));
  await t('fromAsync null', async () => Array.fromAsync(null));
  await t('fromAsync huge array-like', async () => Array.fromAsync({ length: 2 ** 32 }));
  await t('fromAsync define fails', async () => { function C() { Object.defineProperty(this, 0, { value: 'fixed', writable: false, configurable: false }); } return Array.fromAsync.call(C, [1]); });
  await t('fromAsync define fails array-like', async () => { function C() { Object.defineProperty(this, 0, { value: 'fixed', writable: false, configurable: false }); } return Array.fromAsync.call(C, { length: 1, 0: 'v' }); });
  var asyncDispose = Object.getPrototypeOf(Object.getPrototypeOf(async function* () {}.prototype))[Symbol.asyncDispose];
  await t('asyncDispose shape', async () => typeof asyncDispose + ' ' + asyncDispose.name + ' ' + asyncDispose.length);
  await t('asyncDispose calls return', async () => { var log = []; var r = await asyncDispose.call({ return(...a) { log.push('return args=' + a.length); return { value: 'ignored', done: true }; } }); return r + ' ' + log.join(); });
  await t('asyncDispose without return', async () => await asyncDispose.call({}));
  await t('asyncDispose return throws', async () => asyncDispose.call({ return() { throw new SyntaxError('return threw'); } }));
  await t('asyncDispose return getter throws', async () => asyncDispose.call({ get return() { throw new TypeError('getter threw'); } }));
  await t('asyncDispose return rejects', async () => asyncDispose.call({ return() { return Promise.reject(new RangeError('rejected')); } }));
  await t('asyncDispose on async generator', async () => { var log = []; async function* g() { try { yield 1; } finally { log.push('finally ran'); } } var it = g(); await it.next(); await it[Symbol.asyncDispose](); return log.join() + ' ' + JSON.stringify(await it.next()); });
  await t('await using with async generator', async () => { var log = []; async function* g() { try { yield 1; } finally { log.push('cleanup'); } } { await using it = g(); await it.next(); log.push('in block'); } return log.join(', '); });
  await t('allKeyed proxy input', async () => { var p = new Proxy({ a: 1, b: Promise.resolve(2), hidden: 3 }, { getOwnPropertyDescriptor(t, k) { var d = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'hidden') d.enumerable = false; return d; } }); return JSON.stringify(await Promise.allKeyed(p)); });
  await t('allKeyed symbol keys', async () => { var s = Symbol('s'); var r = await Promise.allKeyed({ [s]: Promise.resolve('sym'), str: 'plain' }); return r[s] + ' ' + r.str + ' ' + Object.getPrototypeOf(r); });
  await t('allKeyed getter throws', async () => Promise.allKeyed({ get a() { throw new EvalError('getter'); } }));
  await t('allKeyed empty', async () => JSON.stringify(await Promise.allKeyed({})));
  await t('allSettledKeyed mixed', async () => JSON.stringify(await Promise.allSettledKeyed({ ok: 1, bad: Promise.reject('no') })));
  await t('allKeyed resolve not callable', async () => { function C(ex) { return new Promise(ex); } C.resolve = 1; return Promise.allKeyed.call(C, { a: 1 }); });
  await t('allKeyed resolve throws', async () => { function C(ex) { return new Promise(ex); } C.resolve = function () { throw new RangeError('resolve threw'); }; return Promise.allKeyed.call(C, { a: 1 }); });
  await t('allKeyed then getter throws', async () => { function C(ex) { return new Promise(ex); } C.resolve = function (v) { return { get then() { throw new URIError('then getter'); } }; }; return Promise.allKeyed.call(C, { a: 1 }); });
  await t('allKeyed non-constructor this', async () => Promise.allKeyed.call(5, {}));
  await t('Promise.all element called twice', async () => { var res; function C(ex) { return new Promise(ex); } C.resolve = function (v) { return { then(f) { f('first'); f('second'); } }; }; return JSON.stringify(await Promise.all.call(C, [1])); });
  await t('Promise.allSettled element called twice', async () => { function C(ex) { return new Promise(ex); } C.resolve = function (v) { return { then(f, r) { r('rej'); f('ful'); } }; }; return JSON.stringify(await Promise.allSettled.call(C, [1])); });
  await t('Promise.any reject twice', async () => { function C(ex) { return new Promise(ex); } C.resolve = function (v) { return { then(f, r) { r('r1'); r('r2'); } }; }; try { await Promise.any.call(C, [1]); } catch (e) { return e.name + ' ' + JSON.stringify(e.errors); } });
  await t('zip strict next not callable', async () => Iterator.zip([[1], { [Symbol.iterator]() { return { next: 5 }; } }], { mode: 'strict' }).toArray());
  await t('zip strict next primitive', async () => Iterator.zip([[1], { [Symbol.iterator]() { return { next() { return 1; } }; } }], { mode: 'strict' }).toArray());
  await t('zip strict second longer', async () => Iterator.zip([[1], [1, 2]], { mode: 'strict' }).toArray());
  await t('zip strict next throws', async () => { var log = []; var a = { [Symbol.iterator]() { return this; }, next() { return { value: 1, done: false }; }, return() { log.push('a closed'); return {}; } }; var b = { [Symbol.iterator]() { return this; }, next() { throw new EvalError('b next'); } }; try { Iterator.zip([a, b]).next(); } catch (e) { return e.message + ' ' + log.join(); } });
  await t('zipKeyed numeric keys order', async () => JSON.stringify(Iterator.zipKeyed({ b: [1], 2: [2], a: [3], 1: [4] }).next().value));
  await t('date toLocaleDateString defaults', async () => { var d = new Date(Date.UTC(2020, 0, 2, 3, 4, 5)); return [d.toLocaleDateString('en-US', { timeZone: 'UTC' }), d.toLocaleTimeString('en-US', { timeZone: 'UTC' }), d.toLocaleString('en-US', { timeZone: 'UTC' }), d.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'long' }), d.toLocaleTimeString('en-US', { timeZone: 'UTC', hour: 'numeric' }), d.toLocaleDateString('en-US', { timeZone: 'UTC', dateStyle: 'medium' }), d.toLocaleTimeString('en-US', { timeZone: 'UTC', timeStyle: 'short' }), d.toLocaleDateString(), d.toLocaleTimeString('de-DE')].join(' | '); });
  await t('date toLocaleDateString bad options', async () => new Date(0).toLocaleDateString('en', 5));
  await t('date toLocaleString bad options', async () => new Date(0).toLocaleString('en', 'x'));
  await t('date toLocaleTimeString bad options', async () => new Date(0).toLocaleTimeString('en', true));
  await t('date toLocaleDateString invalid date', async () => new Date(NaN).toLocaleDateString());
  await t('lithuanian soft dotted', async () => ['ɨ̃'.toLocaleUpperCase('lt'), escape('i̇̃'.toLocaleUpperCase('lt')), escape('j̇́'.toLocaleUpperCase('lt')), escape('Ĩ'.toLocaleLowerCase('lt')), escape('Í'.toLocaleLowerCase('lt')), escape('Ì'.toLocaleLowerCase('lt')), escape('İ'.toLocaleLowerCase('tr')), escape('İ'.toLocaleLowerCase('tr')), escape('Ị̇'.toLocaleLowerCase('az')), escape('Ii'.toLocaleLowerCase('lt')), escape('ı'.toLocaleUpperCase('tr'))].join(' '));
  await t('indexOf non-ascii', async () => ['héllo wörld'.indexOf('ö'), 'héllo wörld'.indexOf('l', 3), '😀a😀'.indexOf('a'), '😀😀'.indexOf('\ude00'), 'ab😀'.lastIndexOf('😀'), 'é'.indexOf('', 5), '日本語'.indexOf('語', -5), '日本語'.includes('本'), 'ü'.startsWith('ü', 0)].join());
  console.log(out.join('\n'));
})();
"""
    r = js(code, *tier)
    assert out(r) == golden("async_builtins_from_async_dispose_and_keyed_promises")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_object_rest_subclassing_with_scopes_and_async_delegation(js, golden, tier):
    """CATCHES: object rest that skips proxy ownKeys/getOwnPropertyDescriptor traps, non-enumerable or excluded keys, subclassing of bound functions, proxies and built-ins (Function, DataView, ArrayBuffer, Map, Promise, RegExp, Date, Array, Error) that loses internal slots, with-statement references that ignore deleted bindings or unscopables, or async yield* that mishandles missing throw/return methods fails this."""
    code = SHOW + r"""show('object rest from proxy', function () { var log = []; var p = new Proxy({ a: 1, b: 2, c: 3, [Symbol('s')]: 4 }, { ownKeys: function (t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor: function (t, k) { log.push('gopd ' + String(k)); var d = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'c') d.enumerable = false; return d; } }); var { a, ...rest } = p; return a + ' ' + JSON.stringify(rest) + ' ' + Object.getOwnPropertySymbols(rest).length + ' ' + log.join(','); });
show('object rest from array and string', function () { var { 0: first, ...restArr } = [10, 20, 30]; var { length, ...restStr } = 'xyz'; return first + ' ' + JSON.stringify(restArr) + ' ' + length + ' ' + JSON.stringify(restStr); });
show('object rest excluded computed keys', function () { var k = 'b'; var { [k]: bv, ...r } = { a: 1, b: 2, c: 3 }; return bv + ' ' + JSON.stringify(r); });
show('object rest getter order', function () { var log = []; var src = { get x() { log.push('x'); return 1; }, get y() { log.push('y'); return 2; } }; var { ...all } = src; return JSON.stringify(all) + ' ' + log.join(); });
show('object rest null', function () { var { ...r } = null; });
show('assignment rest from proxy', function () { var p = new Proxy({ m: 1, n: 2 }, {}); var m, others; ({ m, ...others } = p); return m + ' ' + JSON.stringify(others); });
show('extends bound function without prototype', function () { return class extends (function () {}).bind() {}; });
show('extends bound function', function () { function A(tag, x) { this.tag = tag; this.x = x; } var B0 = A.bind(null, 'bound-tag'); B0.prototype = A.prototype; class B extends B0 { constructor(x) { super(x); } } var b = new B(5); return b.tag + ' ' + b.x + ' ' + (b instanceof B); });
show('extends proxy of class', function () { class A { constructor() { this.made = 'A'; } } var P = new Proxy(A, {}); class B extends P {} var b = new B(); return b.made + ' ' + (b instanceof A); });
show('extends proxy with construct trap', function () { var log = []; class A { constructor(v) { this.v = v; } } var P = new Proxy(A, { construct: function (t, args, nt) { log.push('construct trap nt=' + nt.name); return Reflect.construct(t, args, nt); } }); class B extends P { constructor() { super('val'); } } var b = new B(); return b.v + ' ' + log.join() + ' ' + (b instanceof B); });
show('extends Function', function () { class F extends Function {} var f = new F('a', 'return a * 2'); return f(21) + ' ' + (f instanceof F) + ' ' + typeof f; });
show('extends DataView and ArrayBuffer', function () { class DV extends DataView {} class AB extends ArrayBuffer {} var ab = new AB(4); var dv = new DV(ab); dv.setUint8(1, 200); return dv.getUint8(1) + ' ' + (dv instanceof DV) + ' ' + (ab instanceof AB) + ' ' + ab.byteLength; });
show('extends Map Set Promise RegExp Date', function () { class M extends Map {} class S extends Set {} class P extends Promise {} class R extends RegExp {} class D extends Date {} var m = new M([[1, 2]]); var s = new S([1]); var r = new R('a+', 'g'); var d = new D(0); return [m.get(1), s.has(1), new P(function (res) { res(1); }) instanceof P, r.test('aa'), r.lastIndex, d.getTime(), d instanceof D].join(); });
show('extends Array length behaviour', function () { class A extends Array {} var a = new A(); a[5] = 1; a.length = 2; return a.length + ' ' + Array.isArray(a) + ' ' + JSON.stringify(a); });
show('extends Error captures message', function () { class E extends Error { constructor(m) { super(m); this.name = 'E'; } } var e = new E('msg'); return String(e) + ' ' + Object.prototype.toString.call(e); });
show('strict assignment to deleted with-binding', function () { var o = { x: 1 }; with (o) { (function () { 'use strict'; x = (delete o.x, 2); })(); } return JSON.stringify(o); });
show('sloppy assignment to deleted with-binding', function () { var o = { x: 1 }; with (o) { x = (delete o.x, 2); } return JSON.stringify(o) + ' ' + typeof x; });
show('strict read deleted with-binding', function () { var o = { y: 1 }; var r; with (o) { r = (function () { 'use strict'; return y + (delete o.y, 0); })(); } return r; });
show('with binding unscopables', function () { var o = { u: 'from o', [Symbol.unscopables]: { u: true } }; var u = 'outer'; with (o) { return u; } });
show('with typeof and call this', function () { var o = { f: function () { return this === o; }, v: 1 }; with (o) { return typeof v + ' ' + f(); } });
show('with proxy has traps', function () { var log = []; var p = new Proxy({ z: 1 }, { has: function (t, k) { if (typeof k === 'string') log.push('has ' + k); return k in t; }, get: function (t, k) { if (typeof k === 'string') log.push('get ' + k); return t[k]; } }); with (p) { z; z = 2; } return log.join(','); });
console.log(out.join('\n'));
(async function () {
  var log = [];
  async function* inner() { try { yield 1; yield 2; } finally { log.push('inner finally'); } }
  async function* outer() { yield* inner(); }
  var it = outer(); await it.next(); var r = await it.return('early'); log.push('return result ' + JSON.stringify(r));
  var noThrow = { [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 'nt', done: false }); }, return() { log.push('noThrow return called'); return Promise.resolve({ done: true }); } }; } };
  async function* o2() { yield* noThrow; }
  var it2 = o2(); await it2.next(); try { await it2.throw(new Error('boom')); } catch (e) { log.push('throw result ' + e.name + ': ' + e.message); }
  var withThrow = { [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 'wt', done: false }); }, throw(e) { log.push('inner throw got ' + e); return Promise.resolve({ value: 'recovered', done: true }); } }; } };
  async function* o3() { var v = yield* withThrow; log.push('delegate returned ' + v); }
  var it3 = o3(); await it3.next(); var r3 = await it3.throw('err3'); log.push('outer after throw ' + JSON.stringify(r3));
  var noReturn = { [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 'nr', done: false }); } }; } };
  async function* o4() { yield* noReturn; }
  var it4 = o4(); await it4.next(); log.push('return without inner return ' + JSON.stringify(await it4.return(Promise.resolve('awaited value'))));
  var badIter = { [Symbol.asyncIterator]() { return 5; } };
  async function* o5() { yield* badIter; }
  try { await o5().next(); } catch (e) { log.push('bad async iterator ' + e.name + ': ' + e.message); }
  var syncFallback = { [Symbol.iterator]() { return [Promise.resolve('p1'), 'p2'][Symbol.iterator](); } };
  async function* o6() { yield* syncFallback; }
  var vals = []; for await (var v of o6()) vals.push(v); log.push('sync fallback ' + vals.join());
  var returnNotDone = { [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 'rn', done: false }); }, return(v) { return Promise.resolve({ value: 'still going ' + v, done: false }); } }; } };
  async function* o7() { yield* returnNotDone; }
  var it7 = o7(); await it7.next(); log.push('return not done ' + JSON.stringify(await it7.return('x')));
  console.log(log.join('\n'));
})();
"""
    r = js(code, *tier)
    assert out(r) == golden("object_rest_subclassing_with_scopes_and_async_delegation")
    assert (r.returncode, r.stderr) == (0, b"")
