"""Built-in library coverage for lumen-cli: Proxy key/descriptor invariants, Symbol.species, RegExp,
JSON, array-likes, iterator helpers, promise combinators, string casing, and Temporal (calendars,
time zones with the bundled tz data, durations, ISO parsing). No test reads the wall clock."""

import pytest

from conftest import out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]


@pytest.mark.parametrize("tier", TIERS)
def test_proxy_own_keys_descriptor_and_define_invariants(js, golden, tier):
    """CATCHES: a Proxy whose ownKeys/getOwnPropertyDescriptor/defineProperty/getPrototypeOf results are not validated against the target's non-configurable keys and extensibility, or whose freeze/seal/isFrozen skip trap calls or typed-array rules, fails this."""
    code = r"""function t(label, f) { try { console.log(label, f()); } catch (e) { console.log(label, e.name + ': ' + e.message); } }
var ne = Object.preventExtensions({ a: 1 });
t('ownKeys-added', () => Reflect.ownKeys(new Proxy(ne, { ownKeys() { return ['a', 'b']; } })));
t('ownKeys-omitted', () => Reflect.ownKeys(new Proxy(ne, { ownKeys() { return []; } })));
var nc = {}; Object.defineProperty(nc, 'fixed', { value: 1 });
t('ownKeys-noncfg', () => Reflect.ownKeys(new Proxy(nc, { ownKeys() { return ['x']; } })));
t('ownKeys-dupe', () => Reflect.ownKeys(new Proxy({}, { ownKeys() { return ['x', 'x']; } })));
t('ownKeys-type', () => Reflect.ownKeys(new Proxy({}, { ownKeys() { return [1]; } })));
t('ownKeys-prim', () => Reflect.ownKeys(new Proxy({}, { ownKeys() { return 5; } })));
t('ownKeys-neglen', () => JSON.stringify(Reflect.ownKeys(new Proxy({}, { ownKeys() { return { length: -3, 0: 'a' }; } }))));
t('ownKeys-nanlen', () => JSON.stringify(Reflect.ownKeys(new Proxy({}, { ownKeys() { return { length: 'zz', 0: 'a' }; } }))));
t('ownKeys-arraylike', () => JSON.stringify(Reflect.ownKeys(new Proxy({}, { ownKeys() { return { length: 2, 0: 'a', 1: 'b' }; } }))));
t('ownKeys-notcallable', () => Reflect.ownKeys(new Proxy({}, { ownKeys: 1 })));
t('ownKeys-forward-nested', () => JSON.stringify(Reflect.ownKeys(new Proxy(new Proxy({ b: 1, 2: 0, a: 1, 1: 0 }, {}), {}))));
var sym = Symbol('s');
t('ownKeys-forward', () => Reflect.ownKeys(new Proxy({ [sym]: 1, z: 1, 0: 1 }, {})).map(String).join());
// getPrototypeOf
t('gpo-mismatch', () => Object.getPrototypeOf(new Proxy(Object.preventExtensions({}), { getPrototypeOf() { return Array.prototype; } })));
t('gpo-ok', () => Object.getPrototypeOf(new Proxy(Object.preventExtensions({}), { getPrototypeOf() { return Object.prototype; } })) === Object.prototype);
t('gpo-bad', () => Object.getPrototypeOf(new Proxy({}, { getPrototypeOf() { return 1; } })));
t('gpo-forward-null', () => Object.getPrototypeOf(new Proxy(Object.create(null), {})));
t('gpo-forward-nested', () => Object.getPrototypeOf(new Proxy(new Proxy([], {}), {})) === Array.prototype);
// getOwnPropertyDescriptor
var neb = Object.preventExtensions({ p: 1 });
t('gopd-undef-nonext', () => Object.getOwnPropertyDescriptor(new Proxy(neb, { getOwnPropertyDescriptor() { return undefined; } }), 'p'));
t('gopd-undef-noncfg', () => Object.getOwnPropertyDescriptor(new Proxy(nc, { getOwnPropertyDescriptor() { return undefined; } }), 'fixed'));
t('gopd-missing-nonext', () => Object.getOwnPropertyDescriptor(new Proxy(neb, { getOwnPropertyDescriptor() { return { value: 1, configurable: true }; } }), 'q'));
var frozenv = {}; Object.defineProperty(frozenv, 'k', { value: 1, writable: false, configurable: false });
t('gopd-value', () => Object.getOwnPropertyDescriptor(new Proxy(frozenv, { getOwnPropertyDescriptor() { return { value: 2, writable: false, configurable: false }; } }), 'k'));
var acc = {}; Object.defineProperty(acc, 'g', { get() { return 1; }, configurable: false });
t('gopd-getter', () => Object.getOwnPropertyDescriptor(new Proxy(acc, { getOwnPropertyDescriptor() { return { get() { return 2; }, configurable: false }; } }), 'g'));
t('gopd-setter', () => Object.getOwnPropertyDescriptor(new Proxy(acc, { getOwnPropertyDescriptor(t, k) { var d = Reflect.getOwnPropertyDescriptor(t, k); d.set = function () {}; return d; } }), 'g'));
t('gopd-same', () => JSON.stringify(Object.getOwnPropertyDescriptor(new Proxy(acc, { getOwnPropertyDescriptor(t, k) { return Reflect.getOwnPropertyDescriptor(t, k); } }), 'g')));
var wr = {}; Object.defineProperty(wr, 'w', { value: 1, writable: true, configurable: false });
t('gopd-nonwritable', () => Object.getOwnPropertyDescriptor(new Proxy(wr, { getOwnPropertyDescriptor() { return { value: 1, writable: false, configurable: false }; } }), 'w'));
t('gopd-noncfg-missing', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor() { return { value: 1, configurable: false }; } }), 'm'));
t('gopd-noncfg-but-cfg', () => Object.getOwnPropertyDescriptor(new Proxy({ c: 1 }, { getOwnPropertyDescriptor() { return { value: 1, configurable: false }; } }), 'c'));
t('gopd-shape', () => Object.getOwnPropertyDescriptor(new Proxy(frozenv, { getOwnPropertyDescriptor() { return { get() {}, configurable: false }; } }), 'k'));
t('gopd-forward-nested', () => JSON.stringify(Object.getOwnPropertyDescriptor(new Proxy(new Proxy({ n: 3 }, {}), {}), 'n')));
t('gopd-forward-missing', () => Object.getOwnPropertyDescriptor(new Proxy({}, {}), 'nope'));
// propertyIsEnumerable through proxies
t('pie-nested', () => Object.prototype.propertyIsEnumerable.call(new Proxy(new Proxy({ e: 1 }, {}), {}), 'e'));
// defineProperty invariants
t('dp-nonext', () => Object.defineProperty(new Proxy(Object.preventExtensions({}), { defineProperty() { return true; } }), 'x', { value: 1 }));
t('dp-noncfg', () => Object.defineProperty(new Proxy({}, { defineProperty() { return true; } }), 'x', { value: 1, configurable: false }));
t('dp-noncfg-writable', () => Object.defineProperty(new Proxy(wr, { defineProperty() { return true; } }), 'w', { value: 1, writable: false, configurable: false }));
t('dp-incompatible', () => Object.defineProperty(new Proxy(frozenv, { defineProperty() { return true; } }), 'k', { value: 5 }));
t('dp-forward-nested', () => JSON.stringify(Object.defineProperty(new Proxy(new Proxy({}, {}), {}), 'x', { value: 9, enumerable: true })));
t('dp-false', () => Reflect.defineProperty(new Proxy({}, { defineProperty() { return false; } }), 'x', { value: 1 }));
t('dp-false-throw', () => Object.defineProperty(new Proxy({}, { defineProperty() { return false; } }), 'x', { value: 1 }));
// integrity levels through proxies and typed arrays
var traps = [];
var logged = new Proxy({ a: 1, b: 2 }, {
  ownKeys: function (t) { traps.push('ownKeys'); return Reflect.ownKeys(t); },
  defineProperty: function (t, k, d) { traps.push('define ' + k + ' ' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); },
  preventExtensions: function (t) { traps.push('preventExtensions'); return Reflect.preventExtensions(t); },
  getOwnPropertyDescriptor: function (t, k) { traps.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); },
  isExtensible: function (t) { traps.push('isExtensible'); return Reflect.isExtensible(t); }
});
t('freeze proxy', () => Object.freeze(logged) === logged);
console.log('  traps: ' + traps.join(' | '));
traps.length = 0;
t('isFrozen proxy', () => Object.isFrozen(logged));
console.log('  traps: ' + traps.join(' | '));
traps.length = 0;
t('seal proxy refusing', () => Object.seal(new Proxy({}, { preventExtensions: () => false })));
t('freeze refusing define', () => Object.freeze(new Proxy({ x: 1 }, { defineProperty: () => false })));
t('freeze empty typed array', () => Object.isFrozen(Object.freeze(new Uint8Array(0))));
t('freeze typed array', () => Object.freeze(new Uint8Array(2)));
t('seal typed array', () => Object.seal(new Uint8Array(2)));
t('preventExtensions typed array', () => Object.isExtensible(Object.preventExtensions(new Uint8Array(2))) + ' sealed=' + Object.isSealed(Object.preventExtensions(new Uint8Array(2))));
t('freeze resizable-backed', () => Object.freeze(new Uint8Array(new ArrayBuffer(4, { maxByteLength: 8 }))));
t('preventExtensions length-tracking', () => Object.preventExtensions(new Uint8Array(new ArrayBuffer(4, { maxByteLength: 8 }))));
t('isFrozen primitive', () => Object.isFrozen(1) + ' ' + Object.isSealed('s') + ' ' + Object.isExtensible(1));
t('freeze primitive', () => Object.freeze('str'));
t('keys via ownKeys order', () => Object.keys(new Proxy({}, { ownKeys: () => ['b', 'a', Symbol.iterator], getOwnPropertyDescriptor: () => ({ value: 1, enumerable: true, configurable: true }) })).join());
t('for-in via proxy', () => { var r = []; for (var k in new Proxy({ x: 1, y: 2 }, { ownKeys: () => ['y', 'x'] })) r.push(k); return r.join(); });
t('assign from proxy', () => JSON.stringify(Object.assign({}, new Proxy({ p: 1, q: 2 }, { ownKeys: () => ['q'] }))));
"""
    r = js(code, *tier)
    assert out(r) == golden("proxy_own_keys_descriptor_and_define_invariants")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_symbol_species_constructors(js, golden, tier):
    """CATCHES: ArraySpeciesCreate, SpeciesConstructor and TypedArray/ArrayBuffer species handling that ignore @@species, mishandle null/undefined/non-constructor species, cross-realm Array constructors, or skip result validation fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
class MyArray extends Array {}
var ma = MyArray.from([1, 2, 3, 4]);
show('subclass methods keep species', function () { return ['map', 'filter', 'slice', 'splice', 'concat', 'flat', 'flatMap'].map(function (m) { var r = m === 'splice' ? MyArray.from([1, 2]).splice(0, 1) : m === 'flatMap' ? ma.flatMap(function (x) { return [x]; }) : m === 'map' ? ma.map(function (x) { return x; }) : m === 'filter' ? ma.filter(Boolean) : ma[m](); return m + '=' + (r instanceof MyArray); }).join(' '); });
show('non-species methods', function () { return [ma.toSorted() instanceof MyArray, ma.toReversed() instanceof MyArray, ma.with(0, 9) instanceof MyArray, Array.prototype.toSpliced.call(ma, 0) instanceof MyArray].join(); });
class Plain extends Array { static get [Symbol.species]() { return Array; } }
show('species override to Array', function () { var p = Plain.from([1, 2]); return [p instanceof Plain, p.map(function (x) { return x; }) instanceof Plain, Array.isArray(p.slice())].join(); });
var arr = [1, 2, 3];
arr.constructor = { [Symbol.species]: function Recorder(n) { this.recordedLength = n; } };
show('custom species constructor', function () { var r = arr.map(function (x) { return x * 2; }); return r.constructor.name + ' len=' + r.recordedLength + ' items=' + r[0] + ',' + r[2] + ' length=' + r.length; });
arr.constructor = { [Symbol.species]: null };
show('null species falls back', function () { return Array.isArray(arr.filter(Boolean)) + ' ' + arr.filter(Boolean).constructor.name; });
arr.constructor = { [Symbol.species]: undefined };
show('undefined species falls back', function () { return Array.isArray(arr.slice()); });
arr.constructor = { [Symbol.species]: 'nope' };
show('non-constructor species', function () { return arr.map(function (x) { return x; }); });
arr.constructor = 5;
show('primitive constructor', function () { return arr.slice(); });
arr.constructor = undefined;
show('undefined constructor', function () { return Array.isArray(arr.concat([4])); });
var frozenSpecies = { [Symbol.species]: function () { return Object.freeze([]); } };
var src = [1, 2]; src.constructor = frozenSpecies;
show('species result not writable', function () { return src.map(function (x) { return x; }); });
var otherRealm = $262.createRealm().global;
var foreign = new otherRealm.Array(1, 2, 3);
show('foreign map keeps foreign realm', function () { var r = foreign.map(function (x) { return x; }); return (Object.getPrototypeOf(r) === Array.prototype) + ' ' + (r instanceof otherRealm.Array); });
show('local map on foreign array uses local Array', function () { var r = Array.prototype.map.call(foreign, function (x) { return x; }); return (Object.getPrototypeOf(r) === Array.prototype) + ' ' + (r instanceof otherRealm.Array); });
// Promise species
class MyPromise extends Promise {}
var mp = MyPromise.resolve(1);
show('promise then species', function () { return [mp.then() instanceof MyPromise, mp.finally(function () {}) instanceof MyPromise, mp.catch(function () {}) instanceof MyPromise, MyPromise.all([]) instanceof MyPromise].join(); });
var calls = [];
class Tracking extends Promise { constructor(ex) { calls.push('ctor'); super(ex); } static get [Symbol.species]() { calls.push('species'); return Promise; } }
var tp = new Tracking(function (r) { r(1); });
calls.length = 0;
show('promise species getter', function () { var p = tp.then(function () {}); return (p instanceof Tracking) + ' ' + (p instanceof Promise) + ' ' + calls.join(','); });
var badPromise = Promise.resolve(1); badPromise.constructor = { [Symbol.species]: function NotAPromise(ex) { ex(function () {}, function () {}); } };
show('promise species non-promise capability', function () { var r = badPromise.then(); return r.constructor.name; });
var badExec = Promise.resolve(1); badExec.constructor = { [Symbol.species]: function (ex) { } };
show('species executor never called', function () { return badExec.then(); });
// RegExp species for split
var execCalls = [];
class MyRegExp extends RegExp { exec(s) { execCalls.push(this.lastIndex); return super.exec(s); } static get [Symbol.species]() { execCalls.push('species'); return MyRegExp; } }
show('regexp split species', function () { var parts = 'a1b2c'.split(new MyRegExp('\\d')); return parts.join('|') + ' calls=' + execCalls.length + ' first=' + execCalls[0]; });
show('regexp matchAll species', function () { execCalls.length = 0; var m = [...'x1y2'.matchAll(new MyRegExp('\\d', 'g'))].map(function (r) { return r[0] + '@' + r.index; }); return m.join() + ' ' + execCalls[0]; });
// TypedArray / ArrayBuffer species
class MyU8 extends Uint8Array {}
var u = new MyU8([5, 6, 7]);
show('typed array species', function () { return [u.map(function (x) { return x; }) instanceof MyU8, u.subarray(1) instanceof MyU8, u.slice(0, 1) instanceof MyU8, u.filter(Boolean) instanceof MyU8, u.toReversed() instanceof MyU8].join(); });
var shortTA = new Uint8Array([1, 2, 3]);
shortTA.constructor = { [Symbol.species]: function (n) { return new Uint8Array(1); } };
show('typed array species too short', function () { return shortTA.slice(0, 3); });
var wrongType = new Uint8Array([1, 2]);
wrongType.constructor = { [Symbol.species]: function (n) { return new BigInt64Array(n); } };
show('typed array species content type', function () { return wrongType.map(function (x) { return x; }); });
class MyBuf extends ArrayBuffer {}
show('arraybuffer slice species', function () { return new MyBuf(8).slice(2) instanceof MyBuf; });
var ab = new ArrayBuffer(8);
ab.constructor = { [Symbol.species]: function (n) { return ab; } };
show('arraybuffer species same buffer', function () { return ab.slice(0, 4); });
var ab2 = new ArrayBuffer(8);
ab2.constructor = { [Symbol.species]: function (n) { return new ArrayBuffer(2); } };
show('arraybuffer species too small', function () { return ab2.slice(0, 4); });
show('species getters', function () { return [Array, Map, Set, Promise, RegExp, ArrayBuffer, Uint8Array].map(function (C) { return C[Symbol.species] === C; }).join() + ' ' + Object.getOwnPropertyDescriptor(Array, Symbol.species).get.name; });
Promise.resolve().then(function () { console.log(out.join('\n')); });
"""
    r = js(code, *tier)
    assert out(r) == golden("symbol_species_constructors")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_regexp_semantics_and_legacy_statics(js, golden, tier):
    """CATCHES: a RegExp implementation with wrong lastIndex handling for global/sticky regexps, missing legacy RegExp.$1/lastMatch statics, wrong replacement patterns, flags getter order, or error messages for invalid patterns fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('legacy statics', function () { /(\d+)-(\d+)/.exec('tel 12-345 end'); return [RegExp.$1, RegExp.$2, RegExp.$3 === '', RegExp.lastMatch, RegExp['$&'], RegExp.leftContext, RegExp["$`"], RegExp.rightContext, RegExp["$'"], RegExp.lastParen, RegExp['$+'], RegExp.input, RegExp.$_].join('|'); });
show('statics after replace', function () { 'abcabc'.replace(/(b)(c)/g, 'X'); return RegExp.$1 + RegExp.$2 + ' ' + RegExp.leftContext + ' ' + RegExp.lastMatch; });
show('statics after failed match keep', function () { /(z)/.test('qqq'); return RegExp.$1 + ' ' + RegExp.lastMatch; });
show('statics input setter', function () { RegExp.input = 'set-input'; return RegExp.$_; });
show('statics on subclass', function () { class R extends RegExp {} return RegExp.prototype.hasOwnProperty('$1') + ' ' + typeof Object.getOwnPropertyDescriptor(RegExp, '$1').get; });
show('global lastIndex walk', function () { var re = /o/g, r = []; var m; while ((m = re.exec('foo boo')) !== null) r.push(m.index + ':' + re.lastIndex); return r.join(' ') + ' end=' + re.lastIndex; });
show('lastIndex beyond length', function () { var re = /a/g; re.lastIndex = 10; return re.exec('aaa') + ' ' + re.lastIndex; });
show('sticky', function () { var re = /b/y; re.lastIndex = 1; var a = re.test('abc'); var b = re.test('abc'); return a + ' ' + b + ' ' + re.lastIndex; });
show('non-global ignores lastIndex', function () { var re = /a/; re.lastIndex = 5; return re.exec('a').index + ' ' + re.lastIndex; });
show('lastIndex valueOf read', function () { var re = /x/; var reads = 0; re.lastIndex = { valueOf: function () { reads++; return 0; } }; re.exec('x'); return reads; });
show('frozen lastIndex global', function () { var re = /a/g; Object.defineProperty(re, 'lastIndex', { writable: false }); return re.exec('a'); });
show('frozen lastIndex failing match', function () { var re = /a/g; Object.defineProperty(re, 'lastIndex', { value: 0, writable: false }); return re.exec('b'); });
show('replace patterns', function () { return 'John Smith'.replace(/(?<first>\w+)\s(?<last>\w+)/, '$<last>, $<first> [$2 $1] $$ $& ($`|$\') $0 $9 $<none>.'); });
show('replace function args', function () { var seen; 'xay'.replace(/(a)(?<n>z)?/, function () { seen = Array.prototype.slice.call(arguments).map(function (v) { return typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v); }); return '_'; }); return seen.join('|'); });
show('replaceAll non-global regexp', function () { return 'aa'.replaceAll(/a/, 'b'); });
show('matchAll non-global', function () { return 'aa'.matchAll(/a/); });
show('replaceAll string special', function () { return 'a.b.c'.replaceAll('.', '$&$&') + ' ' + 'xx'.replaceAll('', '-'); });
show('split limit and captures', function () { return JSON.stringify('a1b2c3'.split(/(\d)/, 4)) + ' ' + JSON.stringify(''.split(/x/)) + ' ' + JSON.stringify('abc'.split(/(?:)/u)) + ' ' + JSON.stringify('ab'.split(/(?:)/, 0)); });
show('search restores lastIndex', function () { var re = /b/g; re.lastIndex = 2; var pos = 'abc'.search(re); return pos + ' ' + re.lastIndex; });
show('custom exec result', function () { var re = /./; re.exec = function () { return { 0: 'fake', length: 1, index: 0, groups: undefined }; }; return re.test('zzz') + ' ' + 'zzz'.replace(re, '[$&]'); });
show('custom exec bad return', function () { var re = /./; re.exec = function () { return 5; }; return re.test('a'); });
show('exec on non-regexp', function () { return RegExp.prototype.exec.call({}, 'a'); });
show('flags getter order', function () { var log = []; var fake = {}; ['hasIndices', 'global', 'ignoreCase', 'multiline', 'dotAll', 'unicode', 'unicodeSets', 'sticky'].forEach(function (k) { Object.defineProperty(fake, k, { get: function () { log.push(k); return true; } }); }); var f = Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get.call(fake); return f + ' ' + log.join(','); });
show('source escaping', function () { return [new RegExp('/').source, new RegExp('').source, new RegExp('\n').source, RegExp.prototype.source, String(new RegExp('a/b', 'gi'))].join(' '); });
show('RegExp from regexp', function () { var re = /ab/gi; var copy = new RegExp(re, 'm'); return copy.flags + ' ' + (RegExp(re) === re) + ' ' + (new RegExp(re) === re); });
show('invalid flags', function () { return new RegExp('a', 'gg'); });
show('invalid pattern', function () { return new RegExp('(?<n>a)(?<n>b)'); });
show('indices', function () { var m = /(?<w>b)(c)?/d.exec('abd'); return JSON.stringify(m.indices) + ' ' + JSON.stringify(m.indices.groups); });
show('lookbehind and unicode sets', function () { return 'price $42 and 7'.match(/(?<=\$)\d+/)[0] + ' ' + /[\p{L}--[a-z]]/v.test('a') + ' ' + /[\p{L}--[a-z]]/v.test('Q') + ' ' + /\p{Script=Greek}/u.test('α'); });
show('case-insensitive unicode', function () { return /K/iu.test('k') + ' ' + /K/i.test('k') + ' ' + /ß/iu.test('ẞ'); });
show('RegExp.escape', function () { return RegExp.escape('a.b*c') + ' ' + RegExp.escape('1x') + ' ' + RegExp.escape(' -'); });
show('Symbol.match false', function () { var re = /a/; re[Symbol.match] = false; return 'x/a/y'.includes(re) + ' ' + 'a/'.startsWith(re); });
show('compile', function () { var re = /a/g; re.lastIndex = 3; var r = re.compile('b', 'i'); return (r === re) + ' ' + re.source + ' ' + re.flags + ' ' + re.lastIndex; });
show('toString generic', function () { return RegExp.prototype.toString.call({ source: 'S', flags: 'F' }); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("regexp_semantics_and_legacy_statics")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_json_stringify_and_parse_edge_cases(js, golden, tier):
    """CATCHES: JSON.stringify that mishandles replacer arrays/functions, toJSON, gap clamping, BigInt, cycles or lone surrogates, or a JSON.parse whose reviver, source text access, __proto__ keys, rawJSON or error detection deviate from the spec fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('replacer array dedupe and numbers', function () { return JSON.stringify({ 1: 'one', a: 'A', b: 'B' }, ['b', 1, 'b', new String('a'), {}, new Number(1)]); });
show('replacer function holder', function () { var seen = []; JSON.stringify({ x: [10, { y: 1 }] }, function (k, v) { seen.push(JSON.stringify(k) + (Array.isArray(this) ? '@arr' : '@obj')); return v; }); return seen.join(' '); });
show('replacer removes and transforms', function () { return JSON.stringify({ keep: 1, drop: 2, nested: { drop: 3, n: 4 } }, function (k, v) { return k === 'drop' ? undefined : typeof v === 'number' ? v * 10 : v; }); });
show('toJSON order', function () { var d = { toJSON: function (key) { return 'toJSON(' + key + ')'; } }; return JSON.stringify({ k: d, arr: [d] }); });
show('toJSON then replacer', function () { return JSON.stringify({ a: { toJSON: function () { return 1; } } }, function (k, v) { return k === 'a' ? v + 1 : v; }); });
show('gap clamping', function () { return JSON.stringify([1, [2]], null, 20).split('\n')[1].length + ' ' + JSON.stringify({ a: 1 }, null, 'abcdefghijklmnop').split('\n')[1] + ' ' + JSON.stringify([1], null, new Number(2)).replace(/\n/g, '\\n') + ' ' + JSON.stringify([1], null, -3) + ' ' + JSON.stringify({}, null, 2) + JSON.stringify([], null, 2); });
show('wrapper objects', function () { return JSON.stringify([new String('s'), new Number(3), new Boolean(false), Object(1n) instanceof BigInt]); });
show('bigint', function () { return JSON.stringify({ n: 1n }); });
show('bigint toJSON', function () { BigInt.prototype.toJSON = function () { return this.toString() + 'n'; }; var r = JSON.stringify({ n: 12n }); delete BigInt.prototype.toJSON; return r; });
show('cycle', function () { var a = { name: 'a' }; a.self = { back: a }; return JSON.stringify(a); });
show('cycle in array', function () { var a = []; a.push(a); return JSON.stringify(a); });
show('special numbers and undefined', function () { return JSON.stringify([NaN, Infinity, -0, undefined, function () {}, Symbol('s')]) + ' ' + JSON.stringify({ u: undefined, f: function () {}, s: Symbol('s') }) + ' ' + JSON.stringify(undefined) + ' ' + JSON.stringify(Symbol()); });
show('well-formed stringify', function () { return JSON.stringify('\ud800 \udc00 😀    \u0007"\\'); });
show('symbol keys skipped', function () { var o = { a: 1 }; o[Symbol('k')] = 2; return JSON.stringify(o); });
show('proxy array', function () { return JSON.stringify(new Proxy([1, 2], {})) + ' ' + JSON.stringify(new Proxy({ z: 1 }, { ownKeys: function () { return ['z', 'q']; }, getOwnPropertyDescriptor: function (t, k) { return { value: k, enumerable: true, configurable: true }; }, get: function (t, k) { return 'v-' + k; } })); });
show('parse reviver', function () { return JSON.stringify(JSON.parse('{"a":[1,2,{"b":3}],"c":"x"}', function (k, v) { if (k === 'b') return undefined; if (typeof v === 'number') return v * 100; return v; })); });
show('reviver source context', function () { var ctx = []; JSON.parse('[1.50, "s", {"k": 1e2}]', function (k, v, c) { if (c && 'source' in c) ctx.push(k + '=' + c.source); return v; }); return ctx.join(' '); });
show('reviver mutating holder', function () { return JSON.stringify(JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') { delete this.b; this.c = 'added'; } return v; })); });
show('parse errors', function () { var r = []; ['{"a":1,}', '[1,]', "{'a':1}", '01', '"\u0001"', '', 'nul', '1 2', '{"a" 1}', '"\\x41"'].forEach(function (s) { try { JSON.parse(s); r.push('ok'); } catch (e) { r.push(e.name); } }); return r.join(','); });
show('parse error message', function () { return JSON.parse('{"a": tru}'); });
show('parse __proto__ key', function () { var o = JSON.parse('{"__proto__": {"x": 1}, "y": 2}'); return Object.getPrototypeOf(o) === Object.prototype && Object.prototype.hasOwnProperty.call(o, '__proto__') && o.__proto__.x === 1; });
show('parse duplicate keys', function () { return JSON.stringify(JSON.parse('{"a":1,"a":2}')); });
show('parse numbers', function () { return JSON.stringify(JSON.parse('[-0, 1E400, 1e-400, 0.1e1, 123456789012345678901234567890]')) + ' ' + Object.is(JSON.parse('-0'), -0); });
show('parse whitespace and unicode escapes', function () { return JSON.parse(' \t\n\r"\\u00e9\\ud83d\\ude00\\/"\r\n') + ' ' + JSON.parse('"\\uD800"').length; });
show('rawJSON', function () { var raw = JSON.rawJSON('1e1000'); return JSON.stringify({ big: raw, s: JSON.rawJSON('"str"') }) + ' ' + JSON.isRawJSON(raw) + ' ' + JSON.isRawJSON({}) + ' ' + Object.isFrozen(raw) + ' ' + Object.getPrototypeOf(raw); });
show('rawJSON invalid', function () { return JSON.rawJSON('{"a":1}'); });
show('rawJSON whitespace', function () { return JSON.rawJSON(' 1'); });
show('toStringTag', function () { return Object.prototype.toString.call(JSON) + ' ' + JSON.stringify.length + ' ' + JSON.parse.length; });
show('deep nesting', function () { var s = ''; for (var i = 0; i < 500; i++) s += '['; for (var j = 0; j < 500; j++) s += ']'; var v = JSON.parse(s); var d = 0; while (Array.isArray(v) && v.length) { v = v[0]; d++; } return d + ' ' + JSON.stringify(JSON.parse(s)).length; });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("json_stringify_and_parse_edge_cases")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_array_methods_on_array_likes(js, golden, tier):
    """CATCHES: generic Array.prototype methods that do not honour ToLength on array-likes, skip holes correctly, delete trailing elements (sort/copyWithin/reverse), respect Symbol.isConcatSpreadable, or use the this-constructor in Array.from/of fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var AP = Array.prototype;
function al() { return { length: 4, 0: 'a', 1: 'b', 3: 'd', extra: 'x' }; }
show('join/toString', function () { return AP.join.call(al(), '-') + ' ' + AP.toString.call({ join: function () { return 'custom join'; } }) + ' ' + AP.toString.call({}); });
show('map/filter/forEach skip holes', function () { var seen = []; AP.forEach.call(al(), function (v, i) { seen.push(i + v); }); return seen.join() + ' ' + JSON.stringify(AP.map.call(al(), function (v) { return v.toUpperCase(); })) + ' ' + JSON.stringify(AP.filter.call(al(), function () { return true; })); });
show('reduce/reduceRight', function () { return AP.reduce.call(al(), function (a, b) { return a + b; }) + ' ' + AP.reduceRight.call(al(), function (a, b) { return a + b; }, '>'); });
show('reduce empty', function () { return AP.reduce.call({ length: 0 }, function () {}); });
show('indexOf/lastIndexOf/includes', function () { var o = { length: 5, 0: NaN, 1: 2, 2: 2, 4: undefined }; return [AP.indexOf.call(o, 2), AP.lastIndexOf.call(o, 2), AP.indexOf.call(o, NaN), AP.includes.call(o, NaN), AP.includes.call(o, undefined), AP.indexOf.call(o, undefined), AP.lastIndexOf.call(o, 2, -4), AP.indexOf.call(o, 2, -2)].join(); });
show('length coercion', function () { return [AP.join.call({ length: -5, 0: 'x' }), AP.join.call({ length: '2', 0: 'p', 1: 'q' }), AP.join.call({ length: 2.9, 0: 'r', 1: 's', 2: 't' }), AP.join.call({ length: { valueOf: function () { return 1; } }, 0: 'v' }), AP.indexOf.call({ length: Infinity, 0: 'inf' }, 'inf')].join('|'); });
show('push/pop/shift/unshift on objects', function () { var o = { length: 2, 0: 'a', 1: 'b' }; AP.push.call(o, 'c'); var p = AP.pop.call(o); var s = AP.shift.call(o); AP.unshift.call(o, 'z', 'y'); return p + ' ' + s + ' ' + JSON.stringify(o); });
show('push past 2^53-1', function () { var o = { length: 9007199254740991 }; return AP.push.call(o, 1); });
show('pop on empty object sets length', function () { var o = {}; var r = AP.pop.call(o); return r + ' ' + o.length; });
show('splice on object', function () { var o = { length: 5, 0: 0, 1: 1, 2: 2, 3: 3, 4: 4 }; var removed = AP.splice.call(o, 1, 2, 'x'); return JSON.stringify(removed) + ' ' + JSON.stringify(o); });
show('reverse with holes', function () { var o = { length: 4, 0: 'a', 3: 'd', 1: 'b' }; AP.reverse.call(o); return JSON.stringify(o); });
show('sort array-like with holes and undefined', function () { var o = { length: 6, 0: 'c', 1: undefined, 3: 'a', 4: 'b' }; AP.sort.call(o); return JSON.stringify(o) + ' has3=' + (3 in o) + ' o3=' + o[3] + ' has4=' + (4 in o) + ' has5=' + (5 in o); });
show('sort comparator', function () { var o = { length: 3, 0: 3, 1: 1, 2: 2 }; AP.sort.call(o, function (a, b) { return b - a; }); return JSON.stringify(o); });
show('sort bad comparator', function () { return [1, 2].sort('nope'); });
show('copyWithin/fill', function () { var o = { length: 5, 0: 'a', 1: 'b', 2: 'c' }; AP.copyWithin.call(o, 3, 0, 2); var f = AP.fill.call({ length: 3 }, 7, 1); return JSON.stringify(o) + ' ' + JSON.stringify(f); });
show('copyWithin deletes holes', function () { var o = { length: 4, 0: 'a', 2: 'c' }; AP.copyWithin.call(o, 1, 0); return JSON.stringify(o); });
show('flat/flatMap on object', function () { return JSON.stringify(AP.flat.call({ length: 3, 0: [1, [2, [3]]], 1: 'x', 2: [[4]] }, 2)) + ' ' + JSON.stringify(AP.flatMap.call({ length: 2, 0: 1, 1: 2 }, function (v) { return [v, [v * 10]]; })); });
show('flat depth edge cases', function () { var nested = [1, [2, [3, [4]]]]; return JSON.stringify(nested.flat(Infinity)) + ' ' + JSON.stringify(nested.flat(-1)) + ' ' + JSON.stringify(nested.flat('1')) + ' ' + JSON.stringify([[1], , [2]].flat()); });
show('find/findLast/findIndex on strings', function () { return [AP.find.call('hello', function (c) { return c > 'h'; }), AP.findLast.call('hello', function (c) { return c < 'l'; }), AP.findIndex.call('hello', function (c) { return c === 'l'; }), AP.findLastIndex.call('hello', function (c) { return c === 'z'; })].join(); });
show('every/some visit only present', function () { var visits = 0; var r = AP.every.call({ length: 100, 5: 1, 50: 2 }, function () { visits++; return true; }); return r + ' visits=' + visits + ' ' + AP.some.call({ length: 2 }, function () { return true; }); });
show('concat spreadable', function () { var spreadable = { length: 2, 0: 's0', 1: 's1', [Symbol.isConcatSpreadable]: true }; var arr = [9]; arr[Symbol.isConcatSpreadable] = false; return JSON.stringify([0].concat(spreadable, arr, 'str')); });
show('slice/at/with/toSpliced on objects', function () { var o = { length: 3, 0: 'a', 1: 'b', 2: 'c' }; return [JSON.stringify(AP.slice.call(o, -2)), AP.at.call(o, -1), JSON.stringify(AP.with.call(o, 0, 'z')), JSON.stringify(AP.toSpliced.call(o, 1, 1)), JSON.stringify(AP.toReversed.call(o)), JSON.stringify(AP.toSorted.call({ length: 2, 0: 'b', 1: 'a' }))].join(' '); });
show('with out of range', function () { return AP.with.call({ length: 2 }, 5, 'x'); });
show('entries/keys/values on object', function () { var o = { length: 2, 0: 'p', 1: 'q' }; return JSON.stringify([...AP.entries.call(o)]) + ' ' + [...AP.keys.call(o)].join() + ' ' + [...AP.values.call(o)].join(); });
show('Array.from array-like and iterables', function () { return JSON.stringify(Array.from({ length: 3, 1: 'mid' })) + ' ' + JSON.stringify(Array.from('a😀', function (c, i) { return c + i; })) + ' ' + JSON.stringify(Array.from(new Map([[1, 2]]))); });
show('Array.from on constructor this', function () { function C(n) { this.made = n; } var r = Array.from.call(C, { length: 2, 0: 'x', 1: 'y' }); return (r instanceof C) + ' made=' + r.made + ' length=' + r.length + ' ' + r[1]; });
show('Array.of on constructor', function () { function D() {} var r = Array.of.call(D, 1, 2); return (r instanceof D) + ' ' + r.length; });
show('null this', function () { return AP.map.call(null, function () {}); });
show('non-callable callback', function () { return AP.forEach.call({ length: 0 }, 'nope'); });
show('callback mutation', function () { var a = [1, 2, 3]; var seen = []; a.forEach(function (v, i) { seen.push(v); if (i === 0) { a.push(99); a.length = 2; } }); return seen.join(); });
show('lastIndexOf fromIndex', function () { var a = [1, 2, 1, 2]; return [a.lastIndexOf(1, -2), a.lastIndexOf(2, -5), a.lastIndexOf(2, 10), a.lastIndexOf(1, 0)].join(); });
show('join nullish elements', function () { return String([null, undefined, [null], [[]], 0]) + ' ' + [1, [2, [3]]].join(';'); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("array_methods_on_array_likes")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_iterator_helpers_zip_concat_and_from_async(js, golden, tier):
    """CATCHES: iterator helpers that do not close underlying iterators on early exit, accept string primitives where GetIteratorFlattenable rejects them, mis-pad Iterator.zip/zipKeyed, allow re-entrant next(), or an Array.fromAsync that drops awaits fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function* nums(n) { for (var i = 1; i <= n; i++) yield i; }
show('helpers chain', function () { return nums(10).filter(function (x) { return x % 2; }).map(function (x) { return x * x; }).drop(1).take(3).toArray().join(); });
show('flatMap', function () { return nums(3).flatMap(function (x) { return x === 2 ? new Set(['s1', 's2']) : [x, -x]; }).toArray().join(); });
show('flatMap rejects string primitives', function () { return nums(2).flatMap(function (x) { return 'str'; }).toArray(); });
show('flatMap accepts String objects', function () { return nums(1).flatMap(function () { return new String('hi'); }).toArray().join(); });
show('reduce/some/every/find/forEach', function () { var seen = []; nums(4).forEach(function (v, i) { seen.push(i + ':' + v); }); return [nums(4).reduce(function (a, b) { return a + b; }), nums(4).reduce(function (a, b) { return a + b; }, 100), nums(4).some(function (x) { return x > 3; }), nums(4).every(function (x) { return x > 0; }), nums(4).find(function (x) { return x > 2; }), seen.join(' ')].join(' | '); });
show('reduce empty', function () { return nums(0).reduce(function () {}); });
show('take/drop validation', function () { var r = []; [-1, NaN, 'x', Infinity].forEach(function (n) { try { r.push(nums(3).take(n).toArray().length); } catch (e) { r.push(e.name); } }); try { nums(3).drop(-1); } catch (e) { r.push('drop:' + e.name); } return r.join(','); });
show('closing on early exit', function () { var log = []; var it = { i: 0, next: function () { return { value: this.i++, done: false }; }, return: function () { log.push('return called'); return {}; }, __proto__: Iterator.prototype }; it.take(2).toArray(); it.some(function (x) { return x === 5; }); return log.join(','); });
show('Iterator.from wraps', function () { var plain = { next: function () { return { value: 1, done: true }; } }; var w = Iterator.from(plain); return (w instanceof Iterator) + ' ' + JSON.stringify(w.next()) + ' ' + (Iterator.from([1].values()) instanceof Iterator) + ' ' + Iterator.from('ab').toArray().join(); });
show('Iterator.from bad', function () { return Iterator.from(5); });
show('helper protocol', function () { var h = nums(2).map(function (x) { return x; }); return [Object.prototype.toString.call(h), JSON.stringify(h.next()), JSON.stringify(h.return()), JSON.stringify(h.next())].join(' '); });
show('helper running reentry', function () { var h; h = nums(3).map(function () { return h.next(); }); return h.next(); });
show('Iterator.concat', function () { return Iterator.concat([1, 2], new Set([3]), 'xy'.split('')).toArray().join() + ' ' + Iterator.concat().toArray().length; });
show('Iterator.concat bad', function () { return Iterator.concat([1], 5); });
show('Iterator.zip shortest', function () { return JSON.stringify(Iterator.zip([[1, 2, 3], new Set(['a', 'b'])]).toArray()); });
show('Iterator.zip rejects string input', function () { return Iterator.zip([[1], 'ab']).toArray(); });
show('Iterator.zip longest', function () { return JSON.stringify(Iterator.zip([[1, 2, 3], ['a']], { mode: 'longest', padding: ['P1', 'P2'] }).toArray()); });
show('Iterator.zip strict', function () { return JSON.stringify(Iterator.zip([[1, 2], ['a']], { mode: 'strict' }).toArray()); });
show('Iterator.zip strict ok', function () { return JSON.stringify(Iterator.zip([[1, 2], ['a', 'b']], { mode: 'strict' }).toArray()); });
show('Iterator.zip bad mode', function () { return Iterator.zip([], { mode: 'widest' }); });
show('Iterator.zipKeyed', function () { return JSON.stringify(Iterator.zipKeyed({ a: [1, 2], b: ['x', 'y', 'z'] }).toArray()) + ' ' + JSON.stringify(Iterator.zipKeyed({ a: [1], b: [] }, { mode: 'longest', padding: { b: 'pad' } }).toArray()); });
show('zip closes others', function () { var log = []; function tracked(name, n) { var i = 0; return { [Symbol.iterator]: function () { return this; }, next: function () { return i++ < n ? { value: name + i, done: false } : { value: undefined, done: true }; }, return: function () { log.push('close ' + name); return {}; } }; } Iterator.zip([tracked('a', 5), tracked('b', 1), tracked('c', 5)]).toArray(); return log.join(','); });
show('generator helpers via Symbol.iterator', function () { var m = new Map([[1, 'a'], [2, 'b']]); return m.entries().map(function (e) { return e.join('='); }).toArray().join(' ') + ' ' + [10, 20].values().map(function (v, i) { return v + i; }).toArray(); });
show('Iterator constructor abstract', function () { return new Iterator(); });
show('Iterator subclass', function () { class Count extends Iterator { constructor() { super(); this.n = 0; } next() { return this.n < 3 ? { value: this.n++, done: false } : { done: true, value: undefined }; } } return new Count().map(function (x) { return x * 3; }).toArray().join(); });
show('toStringTag/constructor weird setters', function () { var p = Iterator.prototype; var o = Object.create(p); o[Symbol.toStringTag] = 'Custom'; o.constructor = 'ctor'; return Object.prototype.toString.call(o) + ' ' + o.constructor + ' ' + p[Symbol.toStringTag] + ' ' + (p.constructor === Iterator); });
show('weird setter on prototype itself', function () { try { Iterator.prototype[Symbol.toStringTag] = 'X'; } catch (e) { return e.name + ': ' + e.message; } return 'no error'; });
(async function () {
  var r1 = await Array.fromAsync([Promise.resolve(1), 2, Promise.resolve(3)]);
  async function* ag() { yield 'a'; yield 'b'; }
  var r2 = await Array.fromAsync(ag(), function (v, i) { return v + i; });
  var r3 = await Array.fromAsync({ length: 2, 0: Promise.resolve('x'), 1: 'y' });
  var e1; try { await Array.fromAsync([1], 'notfn'); } catch (e) { e1 = e.name + ': ' + e.message; }
  var e2; try { await Array.fromAsync({ [Symbol.asyncIterator]: function () { return { next: function () { return Promise.reject(new Error('async next failed')); } }; } }); } catch (e) { e2 = e.message; }
  function C() { this.isC = true; }
  var r4 = await Array.fromAsync.call(C, [1, 2]);
  out.push('fromAsync: ' + r1.join() + ' ' + r2.join() + ' ' + r3.join() + ' | ' + e1 + ' | ' + e2 + ' | ' + r4.isC + ' ' + r4.length);
  console.log(out.join('\n'));
})();
"""
    r = js(code, *tier)
    assert out(r) == golden("iterator_helpers_zip_concat_and_from_async")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_promise_combinators_and_thenables(js, golden, tier):
    """CATCHES: promise combinators (all/allSettled/any/race/allKeyed/allSettledKeyed/try/withResolvers/finally) that mishandle thenables, throwing then getters, custom resolve lookups, self-resolution, or AggregateError errors fail this."""
    code = r"""var out = [];
function settle(label, p) { return p.then(function (v) { out.push(label + ': fulfilled ' + JSON.stringify(v)); }, function (e) { out.push(label + ': rejected ' + (e && e.name ? e.name + ': ' + e.message + (e.errors ? ' errors=' + JSON.stringify(e.errors.map(String)) : '') : JSON.stringify(e))); }); }
var order = [];
var thenable = { then: function (res) { order.push('thenable.then called'); res('from-thenable'); } };
var badThenable = { then: function () { throw new TypeError('then threw'); } };
var getterThrows = {}; Object.defineProperty(getterThrows, 'then', { get: function () { throw new RangeError('then getter'); } });
Promise.all([
  settle('all', Promise.all([1, Promise.resolve(2), thenable])),
  settle('all reject first', Promise.all([Promise.reject(new Error('r1')), new Promise(function () {})])),
  settle('allSettled', Promise.allSettled([1, Promise.reject('no'), badThenable])),
  settle('any', Promise.any([Promise.reject(1), Promise.resolve('winner')])),
  settle('any all rejected', Promise.any([Promise.reject(new Error('a')), Promise.reject('b')])),
  settle('any empty', Promise.any([])),
  settle('race', Promise.race([new Promise(function (r) { setTimeout(r, 5, 'slow'); }), Promise.resolve('fast')])),
  settle('race empty-ish', Promise.race([getterThrows])),
  settle('all non-iterable', Promise.all(5)),
  settle('allKeyed', Promise.allKeyed({ a: 1, b: Promise.resolve('B'), c: thenable })),
  settle('allKeyed reject', Promise.allKeyed({ ok: 1, bad: Promise.reject(new SyntaxError('keyed')) })),
  settle('allSettledKeyed', Promise.allSettledKeyed({ x: Promise.reject('nope'), y: 2 })),
  settle('allKeyed non-object', Promise.allKeyed(5)),
  settle('try sync value', Promise.try(function (a, b) { return a + b; }, 2, 3)),
  settle('try sync throw', Promise.try(function () { throw new EvalError('tried'); })),
  settle('withResolvers', (function () { var w = Promise.withResolvers(); w.resolve('resolved-later'); w.reject('ignored'); return w.promise; })()),
  settle('resolve self', (function () { var res; var p = new Promise(function (r) { res = r; }); res(p); return p; })()),
  settle('finally passthrough', Promise.resolve('keep').finally(function () { return 'discard'; })),
  settle('finally throw', Promise.resolve('keep').finally(function () { throw new Error('finally threw'); })),
  settle('finally thenable delay', Promise.reject('orig').finally(function () { return thenable; })),
  settle('then non-callable', Promise.resolve('pass').then(5, null)),
  settle('subclass all', (function () { class P2 extends Promise {} var r = P2.all([1]); out.push('subclass instance: ' + (r instanceof P2)); return r; })()),
  settle('resolve non-promise ctor', (function () { try { return Promise.resolve.call(function (ex) { ex(function () {}, function () {}); }, 1).then ? Promise.resolve('has then') : Promise.resolve('plain object'); } catch (e) { return Promise.reject(e); } })()),
  settle('all with custom resolve', (function () { var calls = 0; function C(ex) { return new Promise(ex); } C.resolve = function (v) { calls++; return Promise.resolve(v); }; return Promise.all.call(C, [1, 2]).then(function (v) { return v.concat('resolveCalls=' + calls); }); })()),
  settle('all resolve not callable', (function () { function C(ex) { return new Promise(ex); } C.resolve = 5; return Promise.all.call(C, [1]); })())
]).then(function () {
  out.push('order: ' + order.join(','));
  console.log(out.sort().join('\n'));
});
"""
    r = js(code, *tier)
    assert out(r) == golden("promise_combinators_and_thenables")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_string_locale_casing_and_legacy_methods(js, golden, tier):
    """CATCHES: string case mapping without Turkish/Azeri/Lithuanian tailoring, Greek final sigma or SpecialCasing expansions, HTML methods without quote escaping, or wrong normalize/isWellFormed/repeat/fromCodePoint errors fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('turkish', function () { return ['I'.toLocaleLowerCase('tr'), 'i'.toLocaleUpperCase('tr'), 'İ'.toLocaleLowerCase('en').length, 'İ'.toLocaleLowerCase('tr'), 'ı'.toUpperCase(), 'iI'.toLocaleUpperCase('az'), 'I'.toLocaleLowerCase(['tr', 'en'])].join(' '); });
show('lithuanian', function () { return [escape('I'.toLocaleLowerCase('lt')), escape('Ì'.toLocaleLowerCase('lt')), escape('i̇'.toLocaleUpperCase('lt')), escape('J́'.toLocaleLowerCase('lt')), escape('Į̀'.toLocaleLowerCase('lt'))].join(' '); });
show('greek final sigma', function () { return ['ΟΔΟΣ'.toLowerCase(), 'ΣΑ'.toLowerCase(), 'Α.Σ'.toLowerCase(), 'ΑΣ́Β'.toLowerCase(), 'ΑΣ.'.toLowerCase()].join(' '); });
show('special casing', function () { return ['ß'.toUpperCase(), 'ﬃ'.toUpperCase(), 'ŉ'.toUpperCase(), 'İ'.toLowerCase().length, 'ǅ'.toLowerCase() + 'ǅ'.toUpperCase()].join(' '); });
show('locale arg validation', function () { return 'a'.toLocaleUpperCase('not a locale!'); });
show('locale arg type', function () { return 'a'.toLocaleUpperCase(5); });
show('html methods', function () { return ['x'.anchor('a"b'), 'x'.link('u&"v'), 'x'.fontcolor('red'), 'x'.big(), 'x'.sub(), String.prototype.bold.call(5), 'x'.fontsize(7)].join(' '); });
show('html on null', function () { return String.prototype.anchor.call(null, 'n'); });
show('normalize', function () { return ['Å'.normalize('NFC').length, 'Å'.normalize('NFD').length, 'ﬁ'.normalize('NFKC'), 'ẛ̣'.normalize('NFKD').length].join(' '); });
show('normalize bad form', function () { return 'a'.normalize('NFX'); });
show('well-formed', function () { return ['ab\ud800'.isWellFormed(), 'ab\ud800c'.toWellFormed().charCodeAt(2).toString(16), '😀'.isWellFormed(), '\udc00\ud800'.toWellFormed().length].join(' '); });
show('at/codePointAt/padding', function () { return ['abc'.at(-1), '😀x'.codePointAt(0).toString(16), '😀x'.codePointAt(1).toString(16), 'abc'.padStart(7, '12'), 'abc'.padEnd(5, ''), 'abc'.padStart(2)].join(' '); });
show('repeat errors', function () { var r = []; [-1, Infinity].forEach(function (n) { try { 'a'.repeat(n); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | ') + ' ' + JSON.stringify(''.repeat(1e9)); });
show('localeCompare', function () { return ['a'.localeCompare('b'), 'b'.localeCompare('a'), 'a'.localeCompare('a'), 'ä'.localeCompare('a', 'de', { sensitivity: 'base' }), ['é', 'e', 'z', 'E'].sort(function (a, b) { return a.localeCompare(b, 'en'); }).join('')].join(' '); });
show('split/substr legacy', function () { return ['abcdef'.substr(-3, 2), 'abc'.substr(1), 'a,b,,c'.split(',', 2).join('|'), 'abc'.split('').join('|'), 'abc'.split(undefined).length, 'abc'.split(undefined, 0).length].join(' '); });
show('trim variants', function () { var ws = '  ﻿ x 　\t'; return JSON.stringify([ws.trim(), ws.trimStart(), ws.trimEnd(), ws.trimLeft === ws.trimStart, String.prototype.trimLeft.name]); });
show('String.raw/fromCodePoint', function () { return [String.fromCodePoint(0x1F600, 65).length, String.fromCharCode(0x10041)].join(' '); });
show('fromCodePoint invalid', function () { return String.fromCodePoint(0x110000); });
show('fromCodePoint fractional', function () { return String.fromCodePoint(1.5); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("string_locale_casing_and_legacy_methods")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_non_iso_calendar_arithmetic(js, golden, tier):
    """CATCHES: Temporal calendar arithmetic that mishandles leap months in chinese/dangi/hebrew (constrain vs reject), 13-month calendars, era/eraYear resolution, calendar id validation, or month/monthCode conflicts fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function fmt(d) { return d.calendarId + ' ' + d.year + '/' + d.monthCode + '/' + d.day + ' (iso ' + d.withCalendar('iso8601').toString() + ')'; }
show('chinese add months', function () { var d = Temporal.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 15 }); return fmt(d) + ' -> +1mo ' + fmt(d.add({ months: 1 })) + ' -> +13mo ' + fmt(d.add({ months: 13 })) + ' -> -14mo ' + fmt(d.subtract({ months: 14 })); });
show('chinese add years constrains leap month', function () { var d = Temporal.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 30 }, { overflow: 'constrain' }); return fmt(d) + ' -> ' + fmt(d.add({ years: 1 })); });
show('chinese add years reject', function () { return Temporal.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 1 }).add({ years: 1 }, { overflow: 'reject' }); });
show('chinese months in year', function () { return [2022, 2023, 2024, 2025].map(function (y) { var d = Temporal.PlainDate.from({ calendar: 'chinese', year: y, month: 1, day: 1 }); return y + ':' + d.monthsInYear + '/' + d.daysInYear + '/' + d.inLeapYear; }).join(' '); });
show('dangi until', function () { var a = Temporal.PlainDate.from({ calendar: 'dangi', year: 2020, monthCode: 'M04L', day: 10 }); var b = Temporal.PlainDate.from({ calendar: 'dangi', year: 2023, monthCode: 'M02L', day: 5 }); return a.until(b, { largestUnit: 'years' }).toString() + ' ' + b.since(a, { largestUnit: 'months' }).toString() + ' ' + a.until(b).toString(); });
show('hebrew add', function () { var d = Temporal.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30 }); return fmt(d) + ' -> +1y ' + fmt(d.add({ years: 1 })) + ' -> +1mo ' + fmt(d.add({ months: 1 })) + ' -> -13mo ' + fmt(d.subtract({ months: 13 })); });
show('hebrew reject', function () { return Temporal.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30 }).add({ years: 1 }, { overflow: 'reject' }); });
show('hebrew since', function () { var a = Temporal.PlainDate.from({ calendar: 'hebrew', year: 5780, monthCode: 'M01', day: 1 }); var b = Temporal.PlainDate.from({ calendar: 'hebrew', year: 5785, monthCode: 'M07', day: 20 }); return b.since(a, { largestUnit: 'years' }).toString() + ' ' + a.since(b, { largestUnit: 'months' }).toString() + ' months/years: ' + [5782, 5783, 5784].map(function (y) { return Temporal.PlainDate.from({ calendar: 'hebrew', year: y, month: 1, day: 1 }).monthsInYear; }).join(','); });
show('coptic/ethiopic 13th month', function () { var c = Temporal.PlainDate.from({ calendar: 'coptic', year: 1740, month: 13, day: 5 }); return fmt(c) + ' +1mo ' + fmt(c.add({ months: 1 })) + ' +1y ' + fmt(c.add({ years: 1 })) + ' months ' + c.monthsInYear + ' ' + fmt(Temporal.PlainDate.from({ calendar: 'ethiopic', year: 2016, monthCode: 'M13', day: 6 })); });
show('coptic leap epagomenal', function () { return [1739, 1740].map(function (y) { try { return y + ':' + Temporal.PlainDate.from({ calendar: 'coptic', year: y, month: 13, day: 6 }, { overflow: 'reject' }).toString(); } catch (e) { return y + ':' + e.name; } }).join(' '); });
show('persian/indian', function () { var p = Temporal.PlainDate.from('2024-03-20[u-ca=persian]'); var n = Temporal.PlainDate.from('2024-03-21[u-ca=indian]'); return fmt(p) + ' ' + p.inLeapYear + ' ' + fmt(p.subtract({ days: 1 })) + ' | ' + fmt(n) + ' ' + fmt(n.add({ months: 6 })); });
show('islamic variants', function () { return ['islamic-civil', 'islamic-tbla', 'islamic-umalqura'].map(function (c) { var d = Temporal.PlainDate.from('2024-04-09').withCalendar(c); return c + ' ' + d.year + '-' + d.monthCode + '-' + d.day + ' ' + d.daysInMonth + ' ' + d.add({ months: 1 }).day; }).join(' | '); });
show('eras', function () { return [
  Temporal.PlainDate.from({ calendar: 'gregory', era: 'bce', eraYear: 5, month: 3, day: 1 }).year,
  Temporal.PlainDate.from({ calendar: 'japanese', era: 'heisei', eraYear: 31, month: 4, day: 30 }).toString(),
  Temporal.PlainDate.from('2019-05-01[u-ca=japanese]').era + Temporal.PlainDate.from('2019-05-01[u-ca=japanese]').eraYear,
  Temporal.PlainDate.from({ calendar: 'roc', era: 'broc', eraYear: 1, month: 1, day: 1 }).year,
  Temporal.PlainDate.from('2024-01-01[u-ca=buddhist]').era + Temporal.PlainDate.from('2024-01-01[u-ca=buddhist]').year,
  Temporal.PlainDate.from({ calendar: 'indian', era: 'shaka', eraYear: 1946, month: 1, day: 1 }).toString(),
  Temporal.PlainDate.from({ calendar: 'persian', era: 'ap', eraYear: 1403, month: 1, day: 1 }).toString(),
  Temporal.PlainDate.from({ calendar: 'hebrew', era: 'am', eraYear: 5784, month: 1, day: 1 }).toString(),
  Temporal.PlainDate.from({ calendar: 'islamic-civil', era: 'bh', eraYear: 1, month: 1, day: 1 }).year,
  Temporal.PlainDate.from({ calendar: 'ethiopic', era: 'aa', eraYear: 5500, month: 1, day: 1 }).year,
  Temporal.PlainDate.from({ calendar: 'coptic', era: 'am', eraYear: 1, month: 1, day: 1 }).toString()
].join(' | '); });
show('invalid era', function () { return Temporal.PlainDate.from({ calendar: 'persian', era: 'ce', eraYear: 1, month: 1, day: 1 }); });
show('era without eraYear', function () { return Temporal.PlainDate.from({ calendar: 'gregory', era: 'ce', month: 1, day: 1 }); });
show('iso era', function () { var d = Temporal.PlainDate.from({ year: 2020, month: 1, day: 1, era: 'ce', eraYear: 1999 }); return d.toString() + ' ' + d.era; });
show('calendar validation', function () { var r = []; [5, null, 'ISO8601', 'islamicc', 'gregorian', 'nonsense', '2020-01-01[u-ca=hebrew]'].forEach(function (c) { try { r.push(new Temporal.PlainDate(2020, 1, 1, c).calendarId); } catch (e) { r.push(e.name); } }); return r.join(','); });
show('month/monthCode conflicts', function () { var r = []; [{ month: 13 }, { month: 0 }, { monthCode: 'M02', month: 3 }, { monthCode: 'M13' }, { monthCode: 'm01' }, { month: -1 }, { monthCode: 'M01', month: 1.5 }].forEach(function (f) { var bag = Object.assign({ year: 2020, day: 1 }, f); try { r.push(Temporal.PlainDate.from(bag, { overflow: 'reject' }).toString()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('chinese month/monthCode disagree', function () { return Temporal.PlainDate.from({ calendar: 'chinese', year: 2023, month: 3, monthCode: 'M03', day: 1 }); });
show('chinese absent leap month', function () { var c = Temporal.PlainDate.from({ calendar: 'chinese', year: 2024, monthCode: 'M06L', day: 1 }); return fmt(c); });
show('chinese absent leap month reject', function () { return Temporal.PlainDate.from({ calendar: 'chinese', year: 2024, monthCode: 'M06L', day: 1 }, { overflow: 'reject' }); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_non_iso_calendar_arithmetic")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_plain_month_day_calendars(js, golden, tier):
    """CATCHES: PlainMonthDay resolution that picks the wrong ISO reference year for non-ISO calendars, accepts impossible leap month codes, ignores overflow, or mis-parses month-day strings fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var cals = ['iso8601', 'gregory', 'islamic-civil', 'islamic-tbla', 'islamic-umalqura', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'hebrew', 'chinese', 'dangi', 'buddhist', 'japanese', 'roc'];
cals.forEach(function (cal) {
  var r = [];
  ['M01', 'M05L', 'M12', 'M13'].forEach(function (mc) {
    ['constrain', 'reject'].forEach(function (ovf) {
      try { r.push(mc + '/' + ovf[0] + '=' + Temporal.PlainMonthDay.from({ calendar: cal, monthCode: mc, day: 31 }, { overflow: ovf }).toString()); }
      catch (e) { r.push(mc + '/' + ovf[0] + '=' + e.name); }
    });
  });
  out.push(cal + ': ' + r.join(' '));
});
show('monthday strings', function () { return ['--12-25', '12-25', '1225', '--1225', '2024-12-25', '-12-25', '--12-25[u-ca=iso8601]', '12-25T10:00', '--02-30', '1976-11-18T15:23[u-ca=gregory]'].map(function (s) { try { return Temporal.PlainMonthDay.from(s).toString(); } catch (e) { return e.name; } }).join(' '); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_plain_month_day_calendars")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_zoned_dst_and_offsets(js, golden, tier):
    """CATCHES: ZonedDateTime handling that ignores disambiguation in DST gaps/overlaps, the offset option for conflicting offsets, sub-minute historical offsets, skipped days, transitions, or day-length-aware rounding with the bundled tz data fails this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var Z = Temporal.ZonedDateTime, PDT = Temporal.PlainDateTime;
var gap = PDT.from('2024-03-10T02:30'), overlap = PDT.from('2024-11-03T01:30');
show('gap disambiguation', function () { return ['compatible', 'earlier', 'later'].map(function (d) { return d + '=' + gap.toZonedDateTime('America/New_York', { disambiguation: d }).toString(); }).join(' '); });
show('gap reject', function () { return gap.toZonedDateTime('America/New_York', { disambiguation: 'reject' }).toString(); });
show('overlap disambiguation', function () { return ['compatible', 'earlier', 'later'].map(function (d) { return d + '=' + overlap.toZonedDateTime('America/New_York', { disambiguation: d }).offset; }).join(' '); });
show('overlap reject', function () { return overlap.toZonedDateTime('America/New_York', { disambiguation: 'reject' }).toString(); });
show('bad disambiguation', function () { return gap.toZonedDateTime('America/New_York', { disambiguation: 'nearest' }); });
var s = '2024-11-03T01:30-04:00[America/New_York]';
show('offset option on overlap', function () { return ['use', 'ignore', 'prefer', 'reject'].map(function (o) { return o + '=' + Z.from(s, { offset: o }).offset; }).join(' '); });
var wrong = '2024-07-01T12:00+01:00[America/New_York]';
show('wrong offset use', function () { return Z.from(wrong, { offset: 'use' }).toString(); });
show('wrong offset ignore', function () { return Z.from(wrong, { offset: 'ignore' }).toString(); });
show('wrong offset prefer', function () { return Z.from(wrong, { offset: 'prefer' }).toString(); });
show('wrong offset reject', function () { return Z.from(wrong).toString(); });
show('bag with offset', function () { return Z.from({ year: 2024, month: 11, day: 3, hour: 1, minute: 30, offset: '-05:00', timeZone: 'America/New_York' }).toString() + ' ' + Z.from({ year: 2024, month: 11, day: 3, hour: 1, minute: 30, offset: '+05:00', timeZone: 'America/New_York' }, { offset: 'ignore' }).toString(); });
show('bad offset string', function () { return Z.from({ year: 2024, month: 1, day: 1, offset: '+5', timeZone: 'UTC' }); });
show('sub-minute offset', function () { var z = Z.from('1970-01-01T00:00[Africa/Monrovia]'); return z.offset + ' ' + z.offsetNanoseconds + ' ' + z.toString() + ' ' + z.toString({ offset: 'never' }); });
show('sub-minute offset match', function () { return Z.from('1970-01-01T00:00-00:45[Africa/Monrovia]', { offset: 'reject' }).toString(); });
show('hoursInDay', function () { return ['2024-03-10', '2024-11-03', '2024-06-01'].map(function (d) { return Temporal.PlainDate.from(d).toZonedDateTime('America/New_York').hoursInDay; }).join(',') + ' lordhowe=' + Temporal.PlainDate.from('2024-04-07').toZonedDateTime('Australia/Lord_Howe').hoursInDay; });
show('startOfDay skipped midnight', function () { return Temporal.PlainDate.from('2024-09-08').toZonedDateTime('America/Santiago').toString() + ' ' + Z.from('2024-09-08T12:00[America/Santiago]').startOfDay().toString(); });
show('skipped day', function () { var z = Z.from('2011-12-29T23:00[Pacific/Apia]'); return z.add({ hours: 1 }).toString() + ' ' + z.add({ days: 1 }).toString() + ' ' + Temporal.PlainDate.from('2011-12-30').toZonedDateTime('Pacific/Apia').toString(); });
show('transitions', function () { var z = Z.from('2024-06-01T00:00[Europe/London]'); return z.getTimeZoneTransition('next').toString() + ' ' + z.getTimeZoneTransition('previous').toString() + ' ' + z.getTimeZoneTransition({ direction: 'next' }).offset + ' ' + Z.from('2024-06-01T00:00[UTC]').getTimeZoneTransition('next'); });
show('transition bad direction', function () { return Z.from('2024-06-01T00:00[UTC]').getTimeZoneTransition('sideways'); });
show('transition missing direction', function () { return Z.from('2024-06-01T00:00[UTC]').getTimeZoneTransition(); });
show('add across DST', function () { var z = Z.from('2024-03-09T12:00[America/New_York]'); return z.add({ days: 1 }).toString() + ' ' + z.add({ hours: 24 }).toString() + ' ' + z.until(z.add({ days: 1 }), { largestUnit: 'hours' }).toString(); });
show('until days vs hours', function () { var a = Z.from('2024-03-09T12:00[America/New_York]'), b = Z.from('2024-11-03T12:00[America/New_York]'); return a.until(b, { largestUnit: 'months' }).toString() + ' ' + a.until(b, { largestUnit: 'days' }).toString() + ' ' + a.until(b, { largestUnit: 'hours' }).toString() + ' ' + b.since(a, { largestUnit: 'years', smallestUnit: 'weeks', roundingMode: 'halfExpand' }).toString(); });
show('until different zones', function () { return Z.from('2024-01-01T00:00[UTC]').until(Z.from('2024-02-01T00:00[Europe/Paris]'), { largestUnit: 'days' }); });
show('round to day across DST', function () { return Z.from('2024-03-10T12:30[America/New_York]').round({ smallestUnit: 'day' }).toString() + ' ' + Z.from('2024-03-10T11:30[America/New_York]').round('day').toString() + ' ' + Z.from('2024-11-03T12:00[America/New_York]').round({ smallestUnit: 'hour', roundingIncrement: 6 }).toString(); });
show('with on overlap', function () { var z = Z.from('2024-11-03T01:30-04:00[America/New_York]'); return z.with({ minute: 45 }).toString() + ' ' + z.with({ minute: 45 }, { offset: 'ignore', disambiguation: 'later' }).toString() + ' ' + z.withPlainTime('01:15').toString(); });
show('withTimeZone/equals', function () { var z = Z.from('2024-05-01T12:00[Asia/Kolkata]'); var w = z.withTimeZone('Asia/Kathmandu'); return w.toString() + ' ' + z.equals(w) + ' ' + z.equals(w.withTimeZone('Asia/Calcutta')) + ' ' + w.withTimeZone('Asia/Calcutta').timeZoneId; });
show('time zone ids', function () { return ['utc', 'Etc/GMT+5', 'america/new_york', '+05:30', '-0800', 'Asia/Calcutta', 'US/Pacific'].map(function (t) { try { return Z.from('2024-01-01T00:00[' + t + ']').timeZoneId; } catch (e) { return e.name; } }).join(' '); });
show('invalid zones', function () { return ['Mars/Olympus', '+05:30:15', ''].map(function (t) { try { return new Z(0n, t).timeZoneId; } catch (e) { return e.name + ':' + e.message; } }).join(' | '); });
show('far zone offsets', function () { return [new Z(0n, 'Pacific/Kiritimati').toString(), new Z(1700000000000000000n, 'Pacific/Chatham').toString()].join(' '); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_zoned_dst_and_offsets")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_duration_round_total_and_parse(js, golden, tier):
    """CATCHES: Duration parsing, range validation, toString rounding, round/total/compare with PlainDate and ZonedDateTime relativeTo across DST, or option validation messages that deviate from the Temporal spec fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var D = Temporal.Duration;
show('parse odd strings', function () { return ['P1Y2M3W4DT5H6M7.008009010S', 'pt1.5h', 'PT0.5M', '-P1D', '+PT1,25S', 'P0D', 'PT1H0.5M', 'PT36H'].map(function (s) { try { return D.from(s).toString(); } catch (e) { return e.name; } }).join(' '); });
show('parse invalid strings', function () { return ['P', 'PT', 'P1.5Y', 'PT1.5H2M', 'P1DT', '1D', 'P-1D', 'PT1.0000000001S', 'P1Y1Y'].map(function (s) { try { return D.from(s).toString(); } catch (e) { return e.name; } }).join(' '); });
show('mixed signs', function () { return new D(1, -1); });
show('non-integer field', function () { return new D(0, 0, 0, 1.5); });
show('out of range', function () { return D.from({ seconds: 2 ** 53 }); });
show('years out of range', function () { return D.from({ years: 2 ** 32 }); });
show('bag errors', function () { var r = []; [{}, { day: 1 }, { hours: Infinity }, { minutes: NaN }, { weeks: '2' }].forEach(function (b) { try { r.push(D.from(b).toString()); } catch (e) { r.push(e.name); } }); return r.join(' '); });
show('toString options', function () { var d = D.from('PT1H2M3.456789S'); return [d.toString({ fractionalSecondDigits: 2 }), d.toString({ fractionalSecondDigits: 0 }), d.toString({ smallestUnit: 'millisecond' }), d.toString({ smallestUnit: 'second', roundingMode: 'ceil' }), D.from('PT59.999999999S').toString({ fractionalSecondDigits: 3, roundingMode: 'halfExpand' }), D.from({ milliseconds: 1500 }).toString(), D.from({ microseconds: -1 }).toString()].join(' '); });
show('toString bad options', function () { var r = []; [{ fractionalSecondDigits: 10 }, { smallestUnit: 'minute' }, { fractionalSecondDigits: 'x' }, { roundingMode: 'up' }].forEach(function (o) { try { r.push(D.from('PT1S').toString(o)); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('round time units', function () { var d = D.from({ hours: 25, minutes: 59, seconds: 30 }); return [d.round('hour').toString(), d.round({ largestUnit: 'day' }).toString(), d.round({ smallestUnit: 'minute', roundingIncrement: 15 }).toString(), d.round({ smallestUnit: 'minute', roundingIncrement: 15, roundingMode: 'trunc' }).toString(), D.from('-PT1H30M').round({ smallestUnit: 'hour', roundingMode: 'floor' }).toString(), D.from('-PT1H30M').round({ smallestUnit: 'hour', roundingMode: 'halfEven' }).toString()].join(' '); });
show('round increments invalid', function () { var r = []; [{ smallestUnit: 'minute', roundingIncrement: 7 }, { smallestUnit: 'hour', roundingIncrement: 24 }, { smallestUnit: 'second', roundingIncrement: 0 }, { smallestUnit: 'nanosecond', roundingIncrement: 1e10 }].forEach(function (o) { try { r.push(D.from('PT1H').round(o).toString()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('round needs relativeTo', function () { return D.from({ months: 1 }).round('day'); });
show('round largest < smallest', function () { return D.from('PT1H').round({ largestUnit: 'minute', smallestUnit: 'hour' }); });
show('round missing units', function () { return D.from('PT1H').round({}); });
var rel = Temporal.PlainDate.from('2024-01-31');
show('round with PlainDate relativeTo', function () { var d = D.from({ days: 45 }); return [d.round({ largestUnit: 'months', relativeTo: rel }).toString(), d.round({ smallestUnit: 'months', relativeTo: rel }).toString(), d.round({ smallestUnit: 'months', relativeTo: rel, roundingMode: 'floor' }).toString(), D.from({ months: 13 }).round({ largestUnit: 'years', relativeTo: '2024-02-29' }).toString(), D.from({ years: 1, days: 400 }).round({ smallestUnit: 'years', roundingIncrement: 2, relativeTo: rel }).toString(), D.from({ weeks: 7 }).round({ largestUnit: 'months', smallestUnit: 'weeks', relativeTo: rel }).toString()].join(' '); });
show('total with relativeTo', function () { return [D.from({ months: 1 }).total({ unit: 'days', relativeTo: '2024-02-01' }), D.from({ months: 1 }).total({ unit: 'days', relativeTo: '2023-02-01' }), D.from({ days: 45 }).total({ unit: 'months', relativeTo: rel }), D.from('PT36H').total('day'), D.from({ years: 1 }).total({ unit: 'weeks', relativeTo: '2024-01-01' }), D.from('P1D').total({ unit: 'hours', relativeTo: '2024-03-10T00:00[America/New_York]' })].join(' '); });
show('total errors', function () { var r = []; [undefined, {}, { unit: 'fortnight' }, 'months'].forEach(function (o) { try { r.push(D.from('P1D').total(o)); } catch (e) { r.push(e.name); } }); return r.join(' '); });
show('zoned relativeTo across DST', function () { var z = '2024-03-09T12:00[America/New_York]'; return [D.from('PT47H').round({ largestUnit: 'days', relativeTo: z }).toString(), D.from({ days: 1, hours: 23 }).round({ smallestUnit: 'days', relativeTo: z }).toString(), D.from({ hours: 23 }).total({ unit: 'days', relativeTo: z }), D.from({ days: 2 }).round({ largestUnit: 'hours', relativeTo: z }).toString()].join(' '); });
show('relativeTo bag and strings', function () { return [D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: { year: 2024, month: 2, day: 1 } }).toString(), D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: '2024-02-01T10:00+05:00[Asia/Karachi]' }).toString()].join(' '); });
show('relativeTo invalid', function () { var r = []; ['2024-02-01T10:00Z', 'nonsense', 5, { year: 2024 }].forEach(function (rt) { try { r.push(D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: rt }).toString()); } catch (e) { r.push(e.name); } }); return r.join(' '); });
show('add/subtract', function () { var a = D.from('PT20H'), b = D.from('PT5H'); return [a.add(b).toString(), a.subtract(D.from('P1D')).toString(), a.negated().toString(), a.negated().abs().toString(), a.negated().sign, D.from('PT0S').blank, a.with({ minutes: 5 }).toString()].join(' '); });
show('add calendar units', function () { return D.from({ months: 1 }).add({ days: 1 }); });
show('compare', function () { return [D.compare('PT1H', 'PT60M'), D.compare('P1D', 'PT25H'), D.compare({ months: 1 }, { days: 30 }, { relativeTo: '2024-02-01' }), D.compare({ months: 1 }, { days: 30 }, { relativeTo: '2024-01-01' })].join(','); });
show('compare needs relativeTo', function () { return D.compare({ months: 1 }, { days: 30 }); });
show('options type', function () { return D.from('PT1H').round({ smallestUnit: 'minute', roundingIncrement: 'abc' }); });
show('options primitive', function () { return D.from('PT1H').toString(5); });
show('range limits', function () { return [function () { return D.from({ seconds: 9007199254740991 }); }, function () { return D.from({ seconds: 9007199254740990, milliseconds: 999 }); }, function () { return D.from({ milliseconds: 9007199254740991999 }); }, function () { return D.from({ nanoseconds: Number.MAX_SAFE_INTEGER, microseconds: Number.MAX_SAFE_INTEGER }).round({ largestUnit: 'hours' }); }, function () { return D.from({ days: 104249991374 }); }, function () { return D.from({ days: 104249991375 }); }].map(function (f) { try { return f().toString(); } catch (e) { return e.name; } }).join(' '); });
show('valueOf throws', function () { return D.from('PT1S') + 1; });
show('toLocaleString en', function () { return D.from({ hours: 1, minutes: 30, seconds: 5 }).toLocaleString('en') + ' | ' + D.from({ days: 2 }).toLocaleString('en', { style: 'long' }) + ' | ' + D.from({ hours: 1, minutes: 2 }).toLocaleString('en', { style: 'digital' }); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_duration_round_total_and_parse")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_iso_string_parsing_and_to_string_options(js, golden, tier):
    """CATCHES: Temporal ISO 8601 parsing that accepts invalid annotations, critical flags, ambiguous time strings or out-of-range limits, or toString options (fractionalSecondDigits, smallestUnit, calendarName, timeZoneName, offset) that format wrongly fail this."""
    code = r"""var out = [];
function each(label, ctor, inputs) { out.push(label + ': ' + inputs.map(function (s) { try { return ctor.from(s).toString(); } catch (e) { return e.name; } }).join(' | ')); }
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
each('PlainDate', Temporal.PlainDate, ['2024-02-29', '20240229', '+002024-02-29', '-000001-01-01', '-000000-01-01', '2024-02-30', '2024-02-29T25:00', '2024-02-29T23:59:60', '2024-02-29t12:00z', '2024-02-29 12:00', '2024-02-29[u-ca=gregory]', '2024-02-29[!u-ca=iso8601]', '2024-02-29[u-ca=iso8601][u-ca=gregory]', '2024-02-29[!u-ca=iso8601][u-ca=gregory]', '2024-02-29[foo=bar]', '2024-02-29[!foo=bar]', '2024-02-29[Europe/Paris]', '2024-02-29[Europe/Paris][u-ca=japanese]', '2024-02-29Z', '2024-W09-4', '2024-060', '275760-09-13', '+275760-09-14']);
each('PlainTime', Temporal.PlainTime, ['12:34', '1234', 'T12:34:56.123456789', 't1234', '12:34:56,5', '23:59:60', '24:00', '12:34+05:00', '12:34Z', '2024-01-01T12:00', '2024-01-01', '12:34[u-ca=hebrew]', '12', 'T12', '12-01', '1201', 'T1201', '12:34:56.1234567891']);
each('PlainDateTime', Temporal.PlainDateTime, ['2024-01-01T00:00', '2024-01-01', '2024-01-01T24:00', '2024-01-01T12:00:00.5+01:00[Asia/Tokyo]', '2024-01-01T12:00Z', '-271821-04-19T00:00:00.000000001', '-271821-04-19T00:00', '+275760-09-13T23:59:59.999999999']);
each('Instant', Temporal.Instant, ['2024-01-01T00:00Z', '2024-01-01T00:00+05:30', '2024-01-01T00:00:00.123456789-23:59', '2024-01-01T00:00', '2024-01-01T00:00z[Asia/Tokyo]', '2024-01-01T00:00+00:00[!Asia/Tokyo]', '-271821-04-20T00:00Z', '-271821-04-19T23:59:59.999999999Z', '2024-01-01T00:00+01:00:30']);
each('PlainYearMonth', Temporal.PlainYearMonth, ['2024-05', '202405', '2024-05-17', '--05', '2024-05[u-ca=iso8601]', '2024-05[u-ca=hebrew]', '2024-05-01[u-ca=hebrew]', '-271821-04', '+275760-09']);
show('toString options PlainDateTime', function () { var dt = Temporal.PlainDateTime.from('2024-07-04T09:08:07.654321987'); return [dt.toString({ fractionalSecondDigits: 4 }), dt.toString({ smallestUnit: 'minute' }), dt.toString({ smallestUnit: 'second', roundingMode: 'ceil' }), dt.toString({ calendarName: 'always' }), dt.withCalendar('hebrew').toString({ calendarName: 'critical' }), dt.withCalendar('hebrew').toString({ calendarName: 'never' }), Temporal.PlainDateTime.from('2024-12-31T23:59:59.9999').toString({ smallestUnit: 'second', roundingMode: 'halfExpand' })].join(' '); });
show('toString options Instant', function () { var i = Temporal.Instant.from('2024-03-10T06:59:59.5Z'); return [i.toString(), i.toString({ timeZone: 'America/New_York' }), i.toString({ timeZone: '+05:45', smallestUnit: 'minute' }), i.toString({ fractionalSecondDigits: 'auto' }), i.toString({ smallestUnit: 'second', roundingMode: 'halfEven' }), i.round({ smallestUnit: 'hour', roundingMode: 'ceil' }).toString(), i.round({ smallestUnit: 'minute', roundingIncrement: 30 }).toString()].join(' '); });
show('toString options ZonedDateTime', function () { var z = Temporal.ZonedDateTime.from('2024-03-10T01:59:59.999999999-05:00[America/New_York][u-ca=japanese]'); return [z.toString(), z.toString({ timeZoneName: 'never', calendarName: 'never' }), z.toString({ offset: 'never', timeZoneName: 'critical' }), z.toString({ smallestUnit: 'second', roundingMode: 'ceil' }), z.toString({ fractionalSecondDigits: 0, roundingMode: 'halfExpand' })].join(' '); });
show('bad toString options', function () { var r = []; [{ calendarName: 'sometimes' }, { timeZoneName: 'short' }, { offset: 'maybe' }, { smallestUnit: 'day' }, { smallestUnit: 'hours' }].forEach(function (o) { try { r.push(Temporal.ZonedDateTime.from('2024-01-01T00:00[UTC]').toString(o)); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('PlainTime round/with/until', function () { var t = Temporal.PlainTime.from('23:59:59.6'); return [t.round('second').toString(), t.round({ smallestUnit: 'hour', roundingIncrement: 3 }).toString(), t.with({ hour: 1, nanosecond: 5 }).toString(), t.until('00:00').toString(), t.since('12:00', { largestUnit: 'minute', smallestUnit: 'second' }).toString(), t.add({ hours: 25 }).toString(), Temporal.PlainTime.compare('01:00', t)].join(' '); });
show('PlainTime bag overflow', function () { return [Temporal.PlainTime.from({ hour: 25, minute: 61 }).toString(), (function () { try { return Temporal.PlainTime.from({ hour: 25 }, { overflow: 'reject' }).toString(); } catch (e) { return e.name; } })(), (function () { try { return Temporal.PlainTime.from({}).toString(); } catch (e) { return e.name; } })()].join(' '); });
show('limits arithmetic', function () { var r = []; [function () { return Temporal.PlainDate.from('+275760-09-13').add({ days: 1 }); }, function () { return Temporal.PlainDateTime.from('-271821-04-19T00:00:00.000000001').subtract({ nanoseconds: 1 }); }, function () { return Temporal.Instant.fromEpochMilliseconds(8.64e15).add({ nanoseconds: 1 }); }, function () { return Temporal.Instant.fromEpochNanoseconds(-8640000000000000000000n); }, function () { return new Temporal.ZonedDateTime(8640000000000000000000n, 'Pacific/Kiritimati').toPlainDateTime(); }, function () { return Temporal.ZonedDateTime.from({ year: 275760, month: 9, day: 13, hour: 12, timeZone: 'UTC' }); }].forEach(function (f) { try { r.push(f().toString()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_iso_string_parsing_and_to_string_options")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_subclassing_compare_and_year_month(js, golden, tier):
    """CATCHES: Temporal constructors that ignore new.target prototypes, accept foreign receivers, read property bags or options in the wrong order, or PlainYearMonth/PlainMonthDay/Instant operations that compute or validate incorrectly fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
class MyDate extends Temporal.PlainDate { describe() { return 'MyDate(' + this.toString() + ')'; } }
show('subclass construct', function () { var d = new MyDate(2024, 5, 6); return d.describe() + ' ' + (d instanceof MyDate) + ' ' + (d.add({ days: 1 }) instanceof MyDate) + ' ' + (MyDate.from('2024-01-01') instanceof MyDate) + ' ' + Object.getPrototypeOf(d.add({ days: 1 })).constructor.name; });
show('subclass new.target prototype getter', function () { var calls = 0; var NT = function () {}.bind(); Object.defineProperty(NT, 'prototype', { get: function () { calls++; return MyDate.prototype; } }); var d = Reflect.construct(Temporal.PlainDate, [2020, 1, 2], NT); return (d instanceof MyDate) + ' calls=' + calls; });
show('subclass non-object prototype', function () { function NT2() {} NT2.prototype = null; var d = Reflect.construct(Temporal.Duration, [1], NT2); return Object.getPrototypeOf(d) === Temporal.Duration.prototype; });
show('prototype getter throws', function () { var nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { get: function () { throw new EvalError('proto getter'); } }); return Reflect.construct(Temporal.PlainTime, [], nt); });
show('call without new', function () { return Temporal.PlainDate(2024, 1, 1); });
show('brand checks', function () { var r = []; [['PlainDate', 'year'], ['PlainTime', 'hour'], ['Duration', 'days'], ['Instant', 'epochMilliseconds'], ['ZonedDateTime', 'offset'], ['PlainYearMonth', 'month'], ['PlainMonthDay', 'monthCode']].forEach(function (p) { var g = Object.getOwnPropertyDescriptor(Temporal[p[0]].prototype, p[1]).get; try { g.call(new Temporal.PlainDateTime(2020, 1, 1)); r.push('accepted'); } catch (e) { r.push(e.name); } }); return r.join(','); });
show('property bag read order', function () { var log = []; var bag = new Proxy({ year: 2024, month: 2, day: 30, hour: 1 }, { get: function (t, k) { if (typeof k === 'string') log.push(k); return t[k]; }, has: function (t, k) { return k in t; } }); var d = Temporal.PlainDateTime.from(bag); return d.toString() + ' ' + log.join(','); });
show('options read order', function () { var log = []; var opts = new Proxy({}, { get: function (t, k) { log.push(String(k)); return undefined; } }); Temporal.PlainDate.from('2024-01-01').until('2024-03-01', opts); return log.join(','); });
show('compare/equals', function () { return [Temporal.PlainDate.compare('2024-01-01', '2024-01-02'), Temporal.PlainDate.compare({ year: 2024, month: 1, day: 1 }, '2024-01-01'), Temporal.PlainDate.from('2024-01-01').equals('2024-01-01[u-ca=gregory]'), Temporal.PlainDateTime.compare('2024-01-01T00:00', '2023-12-31T23:59:59.999999999'), Temporal.Instant.compare('2024-01-01T00:00Z', '2024-01-01T01:00+01:00'), Temporal.ZonedDateTime.compare('2024-01-01T00:00[UTC]', '2024-01-01T01:00[Europe/Paris]'), Temporal.PlainYearMonth.compare('2024-01', '2023-12'), Temporal.PlainTime.compare('12:00', '12:00:00.000000001')].join(','); });
show('sort with compare', function () { return ['2024-03-01', '2023-12-31', '2024-01-15'].map(function (s) { return Temporal.PlainDate.from(s); }).sort(Temporal.PlainDate.compare).map(String).join(' '); });
show('PlainYearMonth arithmetic', function () { var ym = Temporal.PlainYearMonth.from('2024-01'); return [ym.add({ months: 13 }).toString(), ym.subtract({ years: 1, months: 1 }).toString(), ym.until('2025-07').toString(), ym.until('2025-07', { largestUnit: 'months' }).toString(), ym.since('2021-03', { smallestUnit: 'years', roundingMode: 'halfExpand' }).toString(), ym.daysInMonth + '/' + ym.daysInYear + '/' + ym.monthsInYear + '/' + ym.inLeapYear, ym.toPlainDate({ day: 31 }).toString(), ym.with({ month: 2 }).toString()].join(' '); });
show('PlainYearMonth invalid ops', function () { var r = []; [function () { return Temporal.PlainYearMonth.from('2024-01').add({ days: 1 }); }, function () { return Temporal.PlainYearMonth.from('2024-01').until('2024-05', { smallestUnit: 'days' }); }, function () { return Temporal.PlainYearMonth.from('2024-01').toPlainDate(); }, function () { return Temporal.PlainYearMonth.from('2024-01').until('2024-05[u-ca=gregory]'); }].forEach(function (f) { try { r.push(f().toString()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('PlainYearMonth in calendars', function () { var h = Temporal.PlainYearMonth.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L' }); var c = Temporal.PlainYearMonth.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L' }); return [h.toString(), h.add({ months: 1 }).monthCode, h.add({ years: 1 }).monthCode, h.until(Temporal.PlainYearMonth.from({ calendar: 'hebrew', year: 5786, monthCode: 'M01' })).toString(), c.toString(), c.add({ months: 12 }).monthCode, c.daysInMonth].join(' '); });
show('PlainMonthDay', function () { var md = Temporal.PlainMonthDay.from('--02-29'); return [md.toString(), md.toPlainDate({ year: 2023 }).toString(), md.toPlainDate({ year: 2024 }).toString(), md.with({ day: 31 }).toString(), md.equals({ monthCode: 'M02', day: 29 }), Temporal.PlainMonthDay.from({ month: 2, day: 30 }).toString(), Temporal.PlainMonthDay.from({ monthCode: 'M05L', day: 1, calendar: 'hebrew' }).toString()].join(' '); });
show('PlainMonthDay errors', function () { var r = []; [function () { return Temporal.PlainMonthDay.from({ month: 2, day: 30 }, { overflow: 'reject' }); }, function () { return Temporal.PlainMonthDay.from({ calendar: 'hebrew', month: 5, day: 1 }); }, function () { return Temporal.PlainMonthDay.from({ day: 1 }); }, function () { return Temporal.PlainMonthDay.from({ calendar: 'chinese', monthCode: 'M12L', day: 1 }, { overflow: 'reject' }); }, function () { return Temporal.PlainMonthDay.from('-12-25'); }].forEach(function (f) { try { r.push(f().toString()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('non-ISO with()', function () { var d = Temporal.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 15 }); return [function () { return d.with({ year: 5785 }).toString(); }, function () { return d.with({ monthCode: 'M13' }).monthCode; }, function () { return d.with({ day: 99 }).day; }, function () { return d.with({ month: 7 }).monthCode; }, function () { return d.with({ monthCode: 'M06', month: 6 }).monthCode; }].map(function (f) { try { return f(); } catch (e) { return e.name + ':' + e.message; } }).join(' | '); });
show('non-ISO with reject', function () { return Temporal.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 15 }).with({ year: 5785 }, { overflow: 'reject' }); });
show('weeks and dayOfYear', function () { return ['2020-12-31', '2021-01-03', '2024-12-30', '2026-01-01'].map(function (s) { var d = Temporal.PlainDate.from(s); return d.weekOfYear + '/' + d.yearOfWeek + '/' + d.dayOfWeek + '/' + d.dayOfYear; }).join(' ') + ' hebrew week=' + Temporal.PlainDate.from('2024-01-01[u-ca=hebrew]').weekOfYear; });
show('Instant conversions', function () { var i = Temporal.Instant.fromEpochMilliseconds(1700000000123); return [i.epochNanoseconds, i.toZonedDateTimeISO('Asia/Tokyo').toString(), i.since('2023-01-01T00:00Z', { largestUnit: 'hours' }).toString(), i.add({ hours: 1.0 }).epochMilliseconds].join(' '); });
show('Instant invalid add', function () { return Temporal.Instant.fromEpochMilliseconds(0).add({ days: 1 }); });
show('toLocaleString', function () { return [Temporal.PlainDate.from('2024-07-04').toLocaleString('en-US'), Temporal.PlainTime.from('15:04:05').toLocaleString('en-US'), Temporal.PlainDateTime.from('2024-07-04T15:04').toLocaleString('en-US'), Temporal.PlainYearMonth.from('2024-07').toLocaleString('en-US', { calendar: 'iso8601' }), Temporal.PlainDate.from('2024-07-04').toLocaleString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })].join(' | '); });
show('toLocaleString calendar mismatch', function () { return Temporal.PlainDate.from('2024-07-04[u-ca=hebrew]').toLocaleString('en-US', { calendar: 'gregory' }); });
show('zdt toLocaleString timeZone option', function () { return Temporal.ZonedDateTime.from('2024-07-04T15:04[Europe/Berlin]').toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_subclassing_compare_and_year_month")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_temporal_calendar_new_years_and_conversions(js, golden, tier):
    """CATCHES: calendar conversion code with off-by-one new-year boundaries or wrong leap-year/month-count rules for hebrew, persian, islamic, chinese, dangi, indian, coptic, ethiopic, buddhist, roc or japanese calendars, including far past/future dates, fails this."""
    code = r"""var out = [];
function newYears(cal, years, extra) {
  return cal + ': ' + years.map(function (y) {
    try { var d = Temporal.PlainDate.from(Object.assign({ calendar: cal, year: y, month: 1, day: 1 }, extra || {})); return y + '=' + d.withCalendar('iso8601').toString() + '(' + d.daysInYear + 'd,' + d.monthsInYear + 'm' + (d.inLeapYear ? ',leap' : '') + ')'; }
    catch (e) { return y + '=' + e.name; }
  }).join(' ');
}
out.push(newYears('hebrew', [1, 3761, 5000, 5784, 5785, 6000]));
out.push(newYears('persian', [1, 475, 1354, 1403, 1404, 2000]));
out.push(newYears('islamic-civil', [1, 1000, 1445, 1446, 2000]));
out.push(newYears('islamic-tbla', [1, 1446]));
out.push(newYears('islamic-umalqura', [1300, 1445, 1446, 1500, 1600]));
out.push(newYears('chinese', [1900, 2023, 2024, 2033, 2050]));
out.push(newYears('dangi', [1900, 2024, 2050]));
out.push(newYears('indian', [1, 1900, 1946, 1947]));
out.push(newYears('coptic', [1, 1740, 1741]));
out.push(newYears('ethiopic', [2016, 2017]));
out.push(newYears('ethioaa', [7516]));
out.push(newYears('buddhist', [2567]));
out.push(newYears('roc', [113, -10]));
out.push(newYears('japanese', [2019]));
['-002000-03-01', '0000-01-01', '1000-06-15', '1582-10-15', '1900-02-28', '2100-12-31', '+100000-01-01'].forEach(function (s) {
  var iso = Temporal.PlainDate.from(s);
  out.push(s + ' -> ' + ['hebrew', 'persian', 'islamic-civil', 'indian', 'coptic', 'chinese', 'gregory'].map(function (c) {
    try { var d = iso.withCalendar(c); return c + ' ' + d.year + '/' + d.monthCode + '/' + d.day + (d.era ? ' ' + d.era + d.eraYear : ''); } catch (e) { return c + ' ' + e.name; }
  }).join(', '));
});
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("temporal_calendar_new_years_and_conversions")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_shared_resizable_and_detached_buffers(js, golden, tier):
    """CATCHES: typed arrays and Atomics that do not alias SharedArrayBuffer views, wrap/convert BigInt and integer element types, honour resizable/growable length tracking, out-of-bounds and detached views, immutable buffers, DataView endianness or base64/hex codecs fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
var sab = new SharedArrayBuffer(32);
var i32 = new Int32Array(sab), b64 = new BigInt64Array(sab, 16), u8 = new Uint8Array(sab);
show('shared views alias', function () { i32[0] = 0x01020304; b64[0] = -2n; return [u8[0], u8[3], u8[16], u8[23], b64[1], i32[4], i32[5]].join(','); });
show('Atomics int32', function () { return [Atomics.store(i32, 1, 10), Atomics.add(i32, 1, 5), Atomics.sub(i32, 1, 3), Atomics.and(i32, 1, 6), Atomics.or(i32, 1, 9), Atomics.xor(i32, 1, 1), Atomics.exchange(i32, 1, 77), Atomics.compareExchange(i32, 1, 77, 88), Atomics.compareExchange(i32, 1, 1, 99), Atomics.load(i32, 1)].join(','); });
show('Atomics bigint', function () { return [Atomics.store(b64, 1, 5n), Atomics.add(b64, 1, 2n), Atomics.sub(b64, 1, 10n), Atomics.load(b64, 1), Atomics.exchange(b64, 1, 2n ** 63n), Atomics.load(b64, 1), Atomics.compareExchange(b64, 1, -(2n ** 63n), 1n), Atomics.load(b64, 1)].join(','); });
show('Atomics on non-shared', function () { var ta = new Int16Array(4); return [Atomics.add(ta, 0, 40000), ta[0], Atomics.isLockFree(4), Atomics.isLockFree(3)].join(','); });
show('Atomics errors', function () { var r = []; [function () { return Atomics.add(new Float64Array(1), 0, 1); }, function () { return Atomics.load(i32, 8); }, function () { return Atomics.store(b64, 0, 1); }, function () { return Atomics.add([1], 0, 1); }, function () { return Atomics.wait(new Int32Array(4), 0, 0, 0); }, function () { return Atomics.load(i32, -1); }].forEach(function (f) { try { r.push(f()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('Atomics.wait immediate', function () { var w = new Int32Array(new SharedArrayBuffer(8)); return [Atomics.wait(w, 0, 1, 0), Atomics.wait(w, 0, 0, 0), Atomics.notify(w, 0, 1), Atomics.notify(w, 0)].join(','); });
show('Atomics.waitAsync sync results', function () { var w = new Int32Array(new SharedArrayBuffer(8)); var a = Atomics.waitAsync(w, 0, 1); var b = Atomics.waitAsync(w, 0, 0, 0); return JSON.stringify(a) + ' ' + JSON.stringify(b); });
show('growable shared', function () { var g = new SharedArrayBuffer(4, { maxByteLength: 16 }); var track = new Uint8Array(g); track[3] = 7; g.grow(12); var fixed = new Uint8Array(g, 4, 4); return [g.growable, g.byteLength, g.maxByteLength, track.length, track[3], fixed.length].join(','); });
show('growable shrink', function () { return new SharedArrayBuffer(8, { maxByteLength: 16 }).grow(4); });
show('resizable buffer views', function () { var rb = new ArrayBuffer(8, { maxByteLength: 16 }); var track = new Uint16Array(rb); var fixed = new Uint16Array(rb, 4, 2); var r = [track.length, fixed.length]; rb.resize(6); r.push(track.length, fixed.length, fixed.byteOffset, fixed.byteLength, String(fixed[0])); rb.resize(2); r.push(track.length, fixed.length, fixed.byteOffset); rb.resize(16); r.push(track.length, fixed.length, fixed.byteOffset); return r.join(','); });
show('out-of-bounds view methods', function () { var rb = new ArrayBuffer(8, { maxByteLength: 16 }); var fixed = new Uint8Array(rb, 4, 4); rb.resize(2); var r = []; [function () { return fixed.fill(1); }, function () { return fixed.join(); }, function () { return [...fixed].length; }, function () { return fixed.at(0); }].forEach(function (f) { try { r.push(String(f())); } catch (e) { r.push(e.name); } }); return r.join(' | '); });
show('detached via transfer', function () { var ab = new ArrayBuffer(8); var v = new Float64Array(ab); v[0] = 1.5; var moved = ab.transfer(16); var r = [ab.detached, ab.byteLength, v.length, String(v[0]), moved.byteLength, new Float64Array(moved)[0]]; try { v.fill(0); } catch (e) { r.push(e.name); } try { ab.slice(0); } catch (e) { r.push(e.name + ':' + e.message); } v[0] = 9; r.push(String(v[0])); return r.join(','); });
show('detach via $262', function () { var ab = new ArrayBuffer(4); var v = new Int8Array(ab); $262.detachArrayBuffer(ab); return [v.length, v.byteLength, v.byteOffset, String(v[0]), Object.keys(v).length, ab.byteLength].join(','); });
show('transferToFixedLength', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var f = rb.transferToFixedLength(); return [f.resizable, f.byteLength, rb.detached].join(','); });
show('immutable buffer', function () { var ab = new ArrayBuffer(4); new Uint8Array(ab)[0] = 5; var im = ab.transferToImmutable(); var v = new Uint8Array(im); v[0] = 9; var r = [im.immutable, v[0], ab.detached]; try { (function () { 'use strict'; v[0] = 1; })(); } catch (e) { r.push(e.name + ':' + e.message); } try { v.fill(3); } catch (e) { r.push(e.name); } try { im.resize(1); } catch (e) { r.push(e.name); } try { new DataView(im).setInt8(0, 1); } catch (e) { r.push(e.name); } return r.join(' | '); });
show('DataView endianness', function () { var dv = new DataView(new ArrayBuffer(16)); dv.setUint16(0, 0x1234); dv.setUint16(2, 0x1234, true); dv.setFloat32(4, 1.5); dv.setBigInt64(8, -1n, true); return [dv.getUint8(0), dv.getUint8(2), dv.getFloat32(4), dv.getBigUint64(8), dv.getInt16(0, true)].join(','); });
show('DataView errors', function () { var r = []; [function () { return new DataView(new ArrayBuffer(4)).getInt32(1); }, function () { return new DataView(new ArrayBuffer(4), 5); }, function () { return new DataView({}); }].forEach(function (f) { try { r.push(f()); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('Float16 and clamped', function () { var h = new Float16Array([1.0009765625, 65504, 70000, 1e-8]); var c = new Uint8ClampedArray([300, -5, 1.5, 2.5, NaN]); return Array.from(h).join(',') + ' ' + Array.from(c).join(',') + ' ' + Math.f16round(1.337); });
show('base64/hex', function () { var u = Uint8Array.fromBase64('SGVsbG8gV29ybGQ='); var t = new Uint8Array(4); var res = t.setFromHex('cafe'); return [new TextDecoder().decode(u), u.toBase64({ alphabet: 'base64url', omitPadding: true }), Uint8Array.fromHex('00ff10').join(), JSON.stringify(res), t.join(), u.subarray(0, 2).toHex()].join(' '); });
show('base64 errors', function () { var r = []; ['SGVsbG8', 'SGV$', 'SGVsbA=x'].forEach(function (s) { try { r.push(Uint8Array.fromBase64(s, { lastChunkHandling: 'strict' }).length); } catch (e) { r.push(e.name); } }); try { Uint8Array.fromHex('abc'); } catch (e) { r.push(e.name); } return r.join(','); });
show('typed array set/subarray/sort', function () { var a = new Int8Array([5, -3, 0, 127]); a.set([1, 2], 2); var s = a.subarray(1, 3); s[0] = 99; return [a.join(), s.join(), a.toSorted().join(), new Float64Array([NaN, -0, 0, -Infinity]).sort().join(), Object.is(new Float64Array([0, -0]).sort()[0], -0)].join(' '); });
show('typed array set overlapping', function () { var buf = new ArrayBuffer(8); var a = new Uint8Array(buf); a.set([1, 2, 3, 4, 5, 6, 7, 8]); var b = new Uint16Array(buf, 2, 2); a.set(b, 1); return a.join(); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("shared_resizable_and_detached_buffers")
    assert (r.returncode, r.stderr) == (0, b"")

@pytest.mark.parametrize("tier", TIERS)
def test_collections_set_methods_and_grouping(js, golden, tier):
    """CATCHES: Map/Set/WeakMap implementations with wrong set-like protocol use in union/intersection/isSupersetOf, live iteration under mutation, SameValueZero keys, groupBy, getOrInsert(Computed), or symbol weak-key rules fail this."""
    code = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function S(arr) { return new Set(arr); }
function str(s) { return '{' + [...s].join(',') + '}'; }
show('set algebra', function () { var a = S([1, 2, 3]), b = S([3, 4]); return [str(a.union(b)), str(a.intersection(b)), str(a.difference(b)), str(a.symmetricDifference(b)), a.isSubsetOf(S([1, 2, 3, 4])), a.isSupersetOf(S([1])), a.isDisjointFrom(S([9]))].join(' '); });
show('set-like argument', function () { var calls = []; var setLike = { size: 2, has: function (v) { calls.push('has ' + v); return v === 2; }, keys: function () { calls.push('keys'); return [2, 5].values(); } }; var r = [str(S([1, 2, 3]).intersection(setLike)), str(S([1, 2]).union(setLike)), S([1, 2, 3]).isSupersetOf(setLike)]; return r.join(' ') + ' calls=' + calls.join(','); });
show('set-like validation', function () { var r = []; [{ size: NaN, has: function () {}, keys: function () {} }, { size: 1, has: 5, keys: function () {} }, { size: 1, has: function () {} }, [1, 2], { size: -1, has: function () {}, keys: function () {} }].forEach(function (x) { try { S([1]).union(x); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('intersection order when other smaller', function () { return str(S([5, 4, 3, 2, 1]).intersection(S([1, 3]))) + ' ' + str(S([1, 3]).intersection(S([5, 4, 3, 2, 1]))); });
show('mutation during iteration', function () { var m = new Map([[1, 'a'], [2, 'b']]); var seen = []; for (var [k] of m) { seen.push(k); if (k === 1) { m.delete(2); m.set(3, 'c'); m.set(2, 'again'); } } var s = S([1]); var n = 0; s.forEach(function (v) { if (n++ < 3) s.add(v + 1); }); return seen.join() + ' ' + str(s); });
show('clear during iteration', function () { var s = S([1, 2, 3]); var it = s.values(); it.next(); s.clear(); s.add(9); return JSON.stringify(it.next()) + ' ' + JSON.stringify(it.next()); });
show('SameValueZero keys', function () { var m = new Map([[NaN, 'nan'], [0, 'zero']]); return [m.get(NaN), m.get(-0), m.has(-0), [...new Map([[-0, 1]]).keys()].map(function (k) { return Object.is(k, -0); }), S([NaN, NaN, 0, -0]).size].join(' '); });
show('groupBy', function () { var g = Object.groupBy([1, 2, 3, 4, 5], function (n) { return n % 2 ? 'odd' : 'even'; }); var m = Map.groupBy(['apple', 'avocado', 'banana'], function (s) { return s[0]; }); return JSON.stringify(g) + ' ' + (Object.getPrototypeOf(g) === null) + ' ' + JSON.stringify([...m]); });
show('groupBy errors', function () { var r = []; try { Object.groupBy(null, function () {}); } catch (e) { r.push(e.name); } try { Object.groupBy([1], 'x'); } catch (e) { r.push(e.name); } return r.join(','); });
show('getOrInsert', function () { var m = new Map(); var calls = 0; var a = m.getOrInsert('k', 'first'); var b = m.getOrInsert('k', 'second'); var c = m.getOrInsertComputed('c', function (key) { calls++; return key.toUpperCase(); }); var d = m.getOrInsertComputed('c', function () { calls++; return 'nope'; }); var wm = new WeakMap(); var key = {}; var w = wm.getOrInsert(key, 'w'); return [a, b, c, d, calls, w, wm.get(key)].join(','); });
show('getOrInsertComputed errors', function () { var r = []; try { new Map().getOrInsertComputed('k', 5); } catch (e) { r.push(e.name); } try { new WeakMap().getOrInsert(1, 'x'); } catch (e) { r.push(e.name + ':' + e.message); } return r.join(' | '); });
show('weak collections with symbols', function () { var wm = new WeakMap(), ws = new WeakSet(); var sym = Symbol('local'); wm.set(sym, 'sym-value'); ws.add(sym); var r = [wm.get(sym), ws.has(sym)]; try { wm.set(Symbol.for('registered'), 1); } catch (e) { r.push(e.name); } try { new WeakRef(Symbol.for('registered')); } catch (e) { r.push('weakref ' + e.name); } r.push(new WeakRef(Symbol.iterator).deref() === Symbol.iterator); return r.join(','); });
show('constructor iterables', function () { var r = []; try { new Map([1]); } catch (e) { r.push(e.name + ':' + e.message); } var calls = 0; var origSet = Map.prototype.set; Map.prototype.set = function (k, v) { calls++; return origSet.call(this, k, v); }; new Map([[1, 2], [3, 4]]); Map.prototype.set = origSet; r.push('set calls=' + calls); try { Map(); } catch (e) { r.push(e.name); } return r.join(' | '); });
show('size getter receiver', function () { var r = []; try { Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.call(new Set()); } catch (e) { r.push(e.name); } try { Set.prototype.has.call(new Map(), 1); } catch (e) { r.push(e.name); } return r.join(','); });
show('iterator protos', function () { var mi = new Map().entries(); var si = new Set().values(); return [Object.prototype.toString.call(mi), Object.prototype.toString.call(si), Object.getPrototypeOf(Object.getPrototypeOf(mi)) === Object.getPrototypeOf(Object.getPrototypeOf([].values())), Set.prototype.keys === Set.prototype.values, Map.prototype[Symbol.iterator] === Map.prototype.entries].join(','); });
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("collections_set_methods_and_grouping")
    assert (r.returncode, r.stderr) == (0, b"")
