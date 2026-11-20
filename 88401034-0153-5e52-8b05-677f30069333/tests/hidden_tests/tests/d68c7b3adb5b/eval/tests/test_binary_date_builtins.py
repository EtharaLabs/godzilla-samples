"""Behavioural tests for lumen's binary-data and object builtins.

Typed arrays (every element type incl. Float16Array and the BigInt arrays), ArrayBuffer (resizable,
transfer, detach, immutable), SharedArrayBuffer, DataView, Atomics (incl. a real `$262.agent`
thread), the Uint8Array base64/hex codecs, Date (fixed time values only: construction, getters,
setters, string formats, Date.parse, toJSON/@@toPrimitive), Promise combinators and job ordering,
unhandled-rejection reporting, DisposableStack/AsyncDisposableStack/`using`, WeakRef and
FinalizationRegistry, ShadowRealm, the `$262` host helpers and BigInt arithmetic. No test reads the
wall clock: every Date is built from explicit components or millisecond values.
"""

import pytest

from conftest import err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

SHOW = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function tries(fns) { return fns.map(function (f) { try { return String(f()); } catch (e) { return e.name + ':' + e.message; } }).join(' | '); }
"""


def test_typed_array_element_conversions(js, golden):
    """CATCHES: wrong ToInt8/ToUint8/ToUint8Clamp (round-half-even)/ToInt16/.../ToUint32 wrapping,
    Float16/Float32 rounding (overflow to Infinity, subnormal flush), BigInt64/BigUint64 modular
    wrapping, or missing TypeErrors when mixing BigInt and Number element types."""
    code = SHOW + r"""
var kinds = [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, Float16Array, Float32Array, Float64Array, BigInt64Array, BigUint64Array];
show('names/bpe', function () { return kinds.map(function (K) { return K.name + ':' + K.BYTES_PER_ELEMENT + ':' + K.prototype.BYTES_PER_ELEMENT + ':' + K.length; }).join(' '); });
var nums = [0, -1, 1.5, -1.5, 2.5, 127, 128, 255, 256, 300, -129, 32768, 65536, 2147483648, 4294967296, -0, NaN, Infinity, -Infinity, 1e-8, 65520, 0.1, 65504, 6e-8];
kinds.slice(0, 10).forEach(function (K) { show(K.name, function () { return Array.from(new K(nums), function (v) { return Object.is(v, -0) ? '-0' : String(v); }).join(','); }); });
var bigs = [0n, -1n, 2n ** 63n, 2n ** 64n + 5n, -(2n ** 63n) - 1n, 123456789012345678901234567890n];
[BigInt64Array, BigUint64Array].forEach(function (K) { show(K.name, function () { return Array.from(new K(bigs)).join(','); }); });
show('bigint into number array', function () { return new Int8Array([1n]); });
show('number into bigint array', function () { return new BigInt64Array([1]); });
show('assign bigint to Int8 elem', function () { var a = new Int8Array(1); a[0] = 1n; return a[0]; });
show('assign coercions', function () { var a = new BigInt64Array(1); a[0] = '12'; var b = new Float32Array(1); b[0] = '0.5'; var c = new Uint8Array(1); c[0] = { valueOf: function () { return 513; } }; var d = new Int16Array(1); d[0] = true; return [a[0], b[0], c[0], d[0]].join(' '); });
show('out of range index writes ignored', function () { var a = new Int8Array(2); a[5] = 1; a[-1] = 2; a['1.5'] = 3; a.foo = 4; return [a.length, a[5], a[-1], a['1.5'], a.foo, Object.keys(a).join('/')].join(); });
show('Math.f16round', function () { return [Math.f16round(1.337), Math.f16round(65520), Math.f16round(-1e-8), Math.f16round(5.960464477539063e-8)].map(function (v) { return Object.is(v, -0) ? '-0' : v; }).join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("typed_array_element_conversions")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typed_array_construction_sources_and_errors(js, golden):
    """CATCHES: TypedArray constructors that mishandle iterables, array-likes, other typed arrays
    (including content-type mismatches) or buffer/offset/length arguments, or report misaligned,
    out-of-range and non-multiple buffer lengths with the wrong error type or message."""
    code = SHOW + r"""
show('from iterable', function () { return new Int16Array(new Set([1, 2, 3])).join() + ' ' + new Uint8Array('123').length + ' ' + new Float64Array({ length: 3, 0: 1, 2: '7' }).join() + ' ' + new Int8Array(function* () { yield 1; yield 2; }()).join(); });
show('from typed array', function () { return new Uint8Array(new Int16Array([-1, 256, 257])).join() + ' ' + new Float32Array(new Uint8Array([1, 2])).join() + ' ' + new BigInt64Array(new BigUint64Array([2n ** 64n - 1n])).join() + ' ' + new Int8Array(new Int8Array([5, 6])).join(); });
show('from mixed content typed array', function () { return new BigInt64Array(new Int8Array(2)); });
show('from bigint typed array into number', function () { return new Float64Array(new BigInt64Array(1)); });
show('buffer offsets', function () { var buf = new ArrayBuffer(16); var a = new Uint8Array(buf, 4, 8); var b = new Uint16Array(buf, 2); var c = new Int32Array(buf, 8); var d = new Float64Array(buf, 8, 1); return [a.length, a.byteOffset, a.byteLength, b.length, b.byteOffset, c.length, c.byteLength, d.length, a.buffer === buf].join(); });
show('offset/length coercion', function () { var buf = new ArrayBuffer(8); var a = new Uint8Array(buf, '2', '3'); var b = new Uint8Array(buf, undefined, undefined); var c = new Uint8Array(buf, 8); return [a.byteOffset, a.length, b.length, c.length].join(); });
show('errors', function () { return tries([
  function () { return new Int32Array(new ArrayBuffer(8), 1); }, function () { return new Int16Array(new ArrayBuffer(8), 2, 4); }, function () { return new Int32Array(new ArrayBuffer(7)); },
  function () { return new Int8Array(new ArrayBuffer(4), 5); }, function () { return new Uint8Array(-1); }, function () { return new Float64Array(2 ** 53); }, function () { return Uint8Array(2); },
  function () { return new Int8Array(new ArrayBuffer(4), -1); }, function () { var b = new ArrayBuffer(4); return new Int8Array(b, { valueOf: function () { b.transfer(); return 0; } }); },
  function () { return new Int8Array({ [Symbol.iterator]: 5 }); }, function () { return new Uint8Array({ length: 2 ** 53 }); }, function () { return new Int8Array(2 ** 40); },
]); });
show('no args', function () { var a = new Float32Array(); return a.length + ' ' + a.buffer.byteLength + ' ' + new Int8Array(undefined).length + ' ' + new Int8Array(null).length + ' ' + new Int8Array(2.7).length; });
show('abstract TypedArray', function () { var TA = Object.getPrototypeOf(Int8Array); return tries([function () { return new TA(); }, function () { return TA(); }]) + ' ' + TA.name + ' ' + (Object.getPrototypeOf(Uint8Array.prototype) === TA.prototype); });
show('ctor array-like', function () { return new Int8Array({ length: 3, 1: 9 }).join() + ' ' + new Uint8Array({ length: '2', 0: '7' }).join() + ' ' + new Int8Array({ length: -5 }).length; });
show('newTarget prototype', function () { function F() {} F.prototype = Object.create(Int8Array.prototype); var t = Reflect.construct(Int8Array, [2], F); function G() {} G.prototype = 7; var u = Reflect.construct(Int8Array, [1], G); return [Object.getPrototypeOf(t) === F.prototype, t.length, Object.getPrototypeOf(u) === Int8Array.prototype].join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("typed_array_construction_sources_and_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typed_array_of_from_and_subclassing(js, golden):
    """CATCHES: TypedArray.of/from that ignore the receiver constructor, mapfn/thisArg, array-like
    sources or iterator validation, subclasses losing their prototype through map/of/from, or the
    @@toStringTag and length/byteLength/byteOffset/buffer getters failing their brand checks."""
    code = SHOW + r"""
show('of', function () { return Int8Array.of(1, 2, 300).join() + ' ' + Float64Array.of().length + ' ' + BigInt64Array.of(1n, -1n).join(); });
show('of non-ctor', function () { return Int8Array.of.call({}, 1); });
show('of short result', function () { return Int8Array.of.call(function () { return new Int8Array(1); }, 1, 2); });
show('from mapfn', function () { return Uint8Array.from([1, 2, 3], function (v, k) { return v * 10 + k + this.o; }, { o: 100 }).join() + ' ' + Int8Array.from({ length: 2, 0: 5 }, function (v) { return v === undefined ? -1 : v; }).join() + ' ' + Int16Array.from(new Map([[1, 2]]).keys()).join(); });
show('from array-like no mapfn', function () { return Int8Array.from({ length: 3, 0: 1, 2: '9' }).join() + ' ' + Float32Array.from('12').join(); });
show('from array-like order', function () { var log = []; var src = { get length() { log.push('length'); return 2; }, get 0() { log.push('0'); return 1; }, get 1() { log.push('1'); return 2; } }; var r = Int8Array.from(src, function (v) { log.push('map' + v); return v * 3; }); return r.join() + ' ' + log.join(','); });
show('from errors', function () { return tries([function () { return Int8Array.from([1], 5); }, function () { return Int8Array.from.call(function () {}.bind(), [1]); }, function () { return Int8Array.from({ [Symbol.iterator]: 5 }); }, function () { return Int8Array.from.call({}, []); }, function () { try { Int8Array.from(null); } catch (e) { return 'null source ' + e.name; } }]); });
show('subclass', function () { class M extends Uint8Array { sum() { return this.reduce(function (a, b) { return a + b; }, 0); } } var m = M.from([1, 2, 3]); return m.sum() + ' ' + (m.map(function (x) { return x * 2; }) instanceof M) + ' ' + M.of(4).sum() + ' ' + Object.prototype.toString.call(m) + ' ' + (m.subarray(1) instanceof M) + ' ' + m.constructor.name; });
show('toStringTag getter', function () { var g = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Int8Array.prototype), Symbol.toStringTag).get; return [g.call(new Int8Array(1)), g.call({}), g.call(3), g.call(new Float16Array(0)), Object.prototype.toString.call(new BigUint64Array(0)), g.name].join(); });
show('getters on non-TA', function () { var P = Object.getPrototypeOf(Int8Array.prototype); return ['length', 'byteLength', 'byteOffset', 'buffer'].map(function (k) { try { return Object.getOwnPropertyDescriptor(P, k).get.call({}); } catch (e) { return k + ':' + e.name; } }).join(); });
show('methods on non-TA', function () { var P = Object.getPrototypeOf(Int8Array.prototype); return ['join', 'at', 'with', 'set', 'subarray', 'toLocaleString', 'fill', 'map'].map(function (k) { try { P[k].call([1, 2], 0); return k + ':ok'; } catch (e) { return k + ':' + e.name; } }).join(' '); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("typed_array_of_from_and_subclassing")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_typed_array_search_and_callback_methods(js, golden, tier):
    """CATCHES: typed-array indexOf/lastIndexOf/includes with wrong NaN/-0 equality or fromIndex
    handling (an explicit undefined fromIndex is 0), at() index coercion, or forEach/every/some/
    find*/reduce*/map/filter that pass wrong arguments, ignore thisArg or skip empty-array errors."""
    code = SHOW + r"""
var f = new Float64Array([3, -0, NaN, 1, 0, -Infinity, 1]);
show('indexOf', function () { return [f.indexOf(1), f.indexOf(1, 4), f.indexOf(1, -1), f.indexOf(NaN), f.indexOf(0), f.indexOf(-0), f.indexOf(1, 100), f.indexOf(3, -100), f.indexOf(1, undefined), new Int8Array(0).indexOf(0), f.indexOf('1'), f.indexOf(1, -Infinity)].join(); });
show('lastIndexOf', function () { return [f.lastIndexOf(1), f.lastIndexOf(1, 5), f.lastIndexOf(1, -2), f.lastIndexOf(NaN), f.lastIndexOf(-0), f.lastIndexOf(3, -100), f.lastIndexOf(1, undefined), f.lastIndexOf(1, 100), new Int8Array(0).lastIndexOf(0)].join(); });
show('includes', function () { return [f.includes(NaN), f.includes(-0), f.includes(0, 5), f.includes(1, -1), f.includes(3, -7), f.includes(undefined), new Uint8Array(0).includes(0, { valueOf: function () { throw 1; } }), new Int8Array([1]).includes(1, NaN), new BigInt64Array([2n]).includes(2n), new BigInt64Array([2n]).includes(2)].join(); });
show('at', function () { var o = new Int8Array([1, 2, 3]); return [o.at(0), o.at(-1), o.at(3), o.at(-4), o.at(1.7), o.at('2'), o.at(NaN), o.at()].join(); });
var a = new Int16Array([5, 1, 4, 2, 3]);
show('forEach/every/some', function () { var r = []; a.forEach(function (v, i, arr) { r.push(v * i + (arr === a ? '' : '!')); }); return r.join() + ' every=' + a.every(function (v) { return v > 0; }) + ' some=' + a.some(function (v) { return v > 4; }) + ' every2=' + a.every(function (v) { return v > 1; }) + ' some2=' + a.some(function (v) { return v > 9; }); });
show('find family', function () { var gt2 = function (v) { return v > 2; }; return [a.find(gt2), a.findIndex(gt2), a.findLast(gt2), a.findLastIndex(gt2), a.find(function (v) { return v > 9; }), a.findIndex(function () { return false; }), a.findLast(function () { return false; }), a.findLastIndex(function () { return false; })].join(); });
show('thisArg', function () { var t = { m: 10 }; var r = []; a.forEach(function (v) { r.push(v * this.m); }, t); return r.join() + ' ' + a.find(function (v) { return v === this.m / 2; }, t); });
show('reduce', function () { return [a.reduce(function (x, y) { return x + y; }), a.reduce(function (x, y) { return x + '' + y; }, ''), a.reduceRight(function (x, y) { return x + '' + y; }), a.reduceRight(function (x, y, i) { return x + i; }, 'r'), new BigInt64Array([1n, 2n]).reduce(function (x, y) { return x * 10n + y; })].join(' '); });
show('reduce empty', function () { return new Int8Array(0).reduce(function () {}); });
show('reduceRight empty', function () { return new Int8Array(0).reduceRight(function () {}); });
show('reduceRight empty init', function () { return new Int8Array(0).reduceRight(function () {}, 'init'); });
show('callback not callable', function () { return tries([function () { return a.forEach(5); }, function () { return a.every(); }, function () { return a.some(null); }, function () { return a.find({}); }, function () { return a.reduce('x'); }, function () { return a.map(1); }, function () { return a.filter(); }, function () { return a.findLastIndex(2); }]); });
show('callback throws', function () { var boom = function () { throw new EvalError('cb'); }; return tries(['forEach', 'every', 'some', 'find', 'findIndex', 'findLast', 'findLastIndex', 'map', 'filter', 'reduce', 'reduceRight'].map(function (m) { return function () { return a[m](boom, 0); }; })); });
show('detach during fromIndex', function () { var b = new ArrayBuffer(4); var t = new Uint8Array(b); var b2 = new ArrayBuffer(4); var t2 = new Uint8Array(b2); var b3 = new ArrayBuffer(4); var t3 = new Uint8Array(b3); return [t.indexOf(0, { valueOf: function () { b.transfer(); return 0; } }), t2.lastIndexOf(0, { valueOf: function () { b2.transfer(); return 3; } }), t3.includes(undefined, { valueOf: function () { b3.transfer(); return 0; } })].join(); });
show('map/filter', function () { return a.map(function (v) { return v * 100; }).join() + ' ' + a.filter(function (v) { return v % 2; }).join() + ' ' + (a.map(String) instanceof Int16Array) + ' ' + a.filter(function () { return false; }).length; });
var hot = new Int32Array(64); for (var i = 0; i < 64; i++) hot[i] = i * 3 % 17;
var acc = 0; for (var k = 0; k < 40; k++) acc += hot.indexOf(k % 17) + (hot.includes(k) ? 1 : 0) + hot.reduce(function (x, y) { return x + y; }, 0);
out.push('hot loop ' + acc);
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("typed_array_search_and_callback_methods")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typed_array_mutation_methods(js, golden):
    """CATCHES: fill/copyWithin with wrong relative-index clamping, reverse on odd lengths, a default
    sort that does not order -0 before +0 and NaN last (or a comparator sort that is unstable or
    ignores NaN results), toSorted/toReversed mutating the source, or `with` index validation."""
    code = SHOW + r"""
show('fill', function () { var b = new Uint8Array(6); return [b.fill(7, 1, -2).join(), b.fill(9, -1).join(), b.fill(1, 10).join(), b.fill(2, -100, 1).join(), b.fill('3', NaN, Infinity).join(), new BigInt64Array(2).fill(5n).join(), new Float32Array(2).fill(0.1).join(), new Int8Array(3).fill(1, 1, undefined).join()].join(' | '); });
show('fill bigint wrong type', function () { return new BigInt64Array(2).fill(1); });
show('fill coercion order', function () { var log = []; new Int8Array(2).fill({ valueOf: function () { log.push('value'); return 1; } }, { valueOf: function () { log.push('start'); return 0; } }, { valueOf: function () { log.push('end'); return 1; } }); return log.join(); });
show('copyWithin', function () { return [new Int8Array([1, 2, 3, 4, 5]).copyWithin(0, 3).join(), new Int8Array([1, 2, 3, 4, 5]).copyWithin(1, 0, 3).join(), new Int8Array([1, 2, 3, 4, 5]).copyWithin(-2, -4, -3).join(), new Int8Array([1, 2, 3, 4, 5]).copyWithin(0, 1, -10).join(), new Int8Array([1, 2, 3]).copyWithin(5, 0).join(), new Float64Array([1, 2, 3, 4]).copyWithin(2, 0, undefined).join(), new Int8Array([1, 2, 3, 4]).copyWithin(NaN, 2).join()].join(' | '); });
show('reverse', function () { return new Int8Array([1, 2, 3, 4]).reverse().join() + ' ' + new Int8Array([1, 2, 3]).reverse().join() + ' ' + new Int8Array(0).reverse().length + ' ' + new BigUint64Array([1n, 2n]).reverse().join(); });
show('sort default', function () { var s = new Float64Array([3, NaN, -0, 0, -Infinity, 1, NaN, -1]).sort(); return Array.from(s, function (v) { return Object.is(v, -0) ? '-0' : v; }).join() + ' ' + new Int32Array([10, 9, 1, -5]).sort().join() + ' ' + new BigInt64Array([3n, -1n, 2n]).sort().join() + ' ' + new Uint32Array([4294967295, 0, 1]).sort().join() + ' ' + new Float16Array([2, -0.5, 1]).sort().join(); });
show('sort comparator', function () { var calls = 0; var r = new Int8Array([5, 1, 4, 2, 3]).sort(function (x, y) { calls++; return y - x; }); return r.join() + ' calls>0=' + (calls > 0); });
show('sort stable', function () { var r = new Float32Array([1.5, 1.25, 2.5, 2.25, 1.75, 2.75, 1.125]).sort(function (x, y) { return Math.floor(x) - Math.floor(y); }); return r.join(); });
show('sort comparator results', function () { return new Int8Array([3, 1, 2]).sort(function () { return NaN; }).join() + ' ' + new Int8Array([3, 1, 2]).sort(function (x, y) { return String(x - y); }).join() + ' ' + new BigInt64Array([3n, 1n, 2n]).sort(function (x, y) { return Number(y - x); }).join(); });
show('sort errors', function () { return tries([function () { return new Int8Array([1]).sort({}); }, function () { return new Int8Array([1, 2, 3]).sort(function () { throw new RangeError('cmp'); }); }, function () { return new Int8Array([1]).toSorted(5); }]); });
show('toSorted', function () { var o = new Uint8Array([3, 1, 2]); var s = o.toSorted(); var s2 = o.toSorted(function (x, y) { return y - x; }); return o.join() + ' ' + s.join() + ' ' + s2.join() + ' ' + (s instanceof Uint8Array) + ' ' + Array.from(new Float64Array([NaN, 1, -0, 0]).toSorted(), String).join() + ' ' + new BigUint64Array([5n, 1n]).toSorted().join(); });
show('toReversed', function () { var o = new Int8Array([1, 2, 3]); return o.toReversed().join() + ' ' + o.join() + ' ' + new Float16Array([0.5, 2]).toReversed().join(); });
show('with', function () { var o = new Int8Array([1, 2, 3]); return [o.with(0, 9).join(), o.with(-1, 300).join(), o.join(), new BigInt64Array([1n]).with(0, 7n).join(), o.with('1', '5').join(), o.with(1.9, 8).join()].join(' | '); });
show('with errors', function () { return tries([function () { return new Int8Array([1, 2, 3]).with(3, 0); }, function () { return new Int8Array([1, 2, 3]).with(-4, 0); }, function () { return new BigInt64Array([1n]).with(0, 1); }, function () { return new Int8Array(1).with(0, { valueOf: function () { throw new EvalError('coerce'); } }); }]); });
show('with resize during coercion', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var t = new Uint8Array(rb); return t.with(3, { valueOf: function () { rb.resize(2); return 1; } }); });
show('with species ignored', function () { var o = new Int8Array([1, 2]); o.constructor = { [Symbol.species]: function () { throw new Error('species used'); } }; return o.with(0, 5).join() + ' ' + o.toSorted().join() + ' ' + o.toReversed().join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("typed_array_mutation_methods")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typed_array_set_slice_subarray_and_species(js, golden):
    """CATCHES: TypedArray set() that does not clone an overlapping same-buffer source, coerces the
    offset wrongly or misses its RangeErrors, slice/subarray with wrong clamping or byteOffset, or a
    species protocol that ignores custom constructors, null species, or invalid results."""
    code = SHOW + r"""
show('set', function () { var t = new Uint8Array(6); t.set([1, 2]); t.set(new Int16Array([-1, 256]), 2); t.set({ length: 2, 0: 7, 1: 8 }, 4); return t.join() + ' ' + t.set([]); });
show('set errors', function () { return tries([function () { return new Uint8Array(2).set([1, 2, 3]); }, function () { return new Uint8Array(2).set(new Uint8Array(2), 1); }, function () { return new Uint8Array(2).set([1], -1); }, function () { return new Uint8Array(2).set(new BigInt64Array(1)); }, function () { return new Uint8Array(2).set([1n]); }, function () { return new Uint8Array(2).set([1], Infinity); }, function () { return new BigInt64Array(1).set(new Uint8Array(1)); }, function () { return Int8Array.prototype.set.call([], [1]); }]); });
show('set same buffer different type', function () { var buf = new ArrayBuffer(8); var u8 = new Uint8Array(buf); u8.set([1, 2, 3, 4, 5, 6, 7, 8]); new Uint16Array(buf).set(u8.subarray(0, 4)); return u8.join(); });
show('set same buffer same type overlap', function () { var u = new Uint8Array([1, 2, 3, 4, 5, 6]); u.set(u.subarray(0, 4), 2); var v = new Uint8Array([1, 2, 3, 4, 5, 6]); v.set(v.subarray(2), 0); return u.join() + ' ' + v.join(); });
show('set offset coercion', function () { var t = new Int8Array(4); t.set([5], '2'); t.set([6], 1.9); t.set([7], NaN); t.set([8], { valueOf: function () { return 3; } }); return t.join(); });
show('set string source', function () { var t = new Int8Array(3); t.set('12'); return t.join(); });
show('set from float/bigint arrays', function () { var t = new Int8Array(3); t.set(new Float32Array([1.9, -1.9, 300])); var b = new BigUint64Array(2); b.set(new BigInt64Array([-1n, 5n])); return t.join() + ' ' + b.join(); });
show('slice', function () { var o = new Int16Array([1, 2, 3, 4, 5]); return [o.slice(1, 3).join(), o.slice(-2).join(), o.slice(3, 1).length, o.slice().join(), o.slice(1, undefined).join(), o.slice(NaN, 2).join(), o.slice(-Infinity, Infinity).length].join(' | '); });
show('slice keeps NaN payload type', function () { var f = new Float64Array([NaN, -0]); var s = f.slice(); return [isNaN(s[0]), Object.is(s[1], -0)].join(); });
show('subarray', function () { var o = new Int16Array([1, 2, 3, 4, 5]); var s = o.subarray(1, -1); s[0] = 99; return [s.join(), s.byteOffset, o.join(), o.subarray(-2).join(), o.subarray(4, 1).length, o.subarray(1).subarray(1).byteOffset, o.subarray(NaN).length, o.subarray(0, Infinity).length].join(' | '); });
show('species slice different type', function () { var o = new Int16Array([1, -2, 300]); o.constructor = { [Symbol.species]: function (n) { return new Uint8Array(n); } }; return o.slice(0, 3).join() + ' ' + o.map(function (x) { return x; }).join() + ' ' + o.filter(Boolean).join(); });
show('species too short', function () { var o = new Int8Array([1, 2, 3]); o.constructor = { [Symbol.species]: function () { return new Int8Array(1); } }; return tries([function () { return o.slice(); }, function () { return o.map(function (x) { return x; }); }, function () { return o.filter(Boolean); }]); });
show('species errors', function () { var r = []; [5, { [Symbol.species]: 5 }, { [Symbol.species]: function () { return {}; } }, { [Symbol.species]: function () { return new BigInt64Array(4); } }, { [Symbol.species]: function () { var b = new ArrayBuffer(4); var t = new Int8Array(b); b.transfer(); return t; } }].forEach(function (c) { var o = new Int8Array([4]); o.constructor = c; try { o.slice(); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('species fallbacks', function () { var o = new Int8Array([4]); o.constructor = undefined; var a = o.slice().join() + ' ' + o.filter(Boolean).join(); o.constructor = { [Symbol.species]: null }; return a + ' ' + (o.slice() instanceof Int8Array) + ' ' + (o.subarray(0) instanceof Int8Array); });
show('species subarray args', function () { var o = new Int8Array([1, 2, 3]); var seen; o.constructor = { [Symbol.species]: function (b, off, len) { seen = [b === o.buffer, off, len]; return new Int8Array(b, off, len); } }; var s = o.subarray(1); return s.join() + ' ' + seen.join(); });
show('species detaches source', function () { var buf = new ArrayBuffer(4); var o = new Int8Array(buf); o.constructor = { [Symbol.species]: function (n) { buf.transfer(); return new Int8Array(n); } }; return tries([function () { return o.slice(0, 2); }]); });
show('species shrinks source', function () { var rb = new ArrayBuffer(4, { maxByteLength: 4 }); var o = new Int8Array(rb); o.set([1, 2, 3, 4]); o.constructor = { [Symbol.species]: function (n) { rb.resize(2); return new Int16Array(n); } }; return o.slice(0, 4).join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("typed_array_set_slice_subarray_and_species")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typed_array_join_locale_and_iterators(js, golden):
    """CATCHES: typed-array join/toString/toLocaleString that mishandle separators, -0, BigInt
    elements, forwarded locale arguments or a non-callable element toLocaleString, and
    entries/keys/values iterators that are not Array Iterators sharing @@iterator."""
    code = SHOW + r"""
show('join/toString', function () { var o = new Float64Array([1.5, -0, 1e21, NaN]); return [o.join(), o.join(' '), o.join(undefined), o.join(null), o.toString(), String(new Int8Array([1, 2])), new Int8Array(0).join('x'), new BigInt64Array([-1n, 2n]).join(';'), new Uint8Array([1, 2]).join({ toString: function () { return '<>'; } })].join(' | '); });
show('toString is Array.prototype.toString', function () { return Object.getPrototypeOf(Int8Array.prototype).toString === Array.prototype.toString; });
show('toLocaleString', function () { return [new Uint16Array([1000, 2]).toLocaleString(), new Float64Array([1234.5]).toLocaleString('de-DE'), new BigInt64Array([12345n]).toLocaleString('en-US')].join(' | '); });
show('toLocaleString forwards args', function () { var save = Number.prototype.toLocaleString; Number.prototype.toLocaleString = function (a, b) { return '<' + this + ':' + a + ':' + (b && b.k) + '>'; }; try { return new Int8Array([1, 2]).toLocaleString('xx', { k: 'v' }); } finally { Number.prototype.toLocaleString = save; } });
show('toLocaleString non-callable', function () { var save = Number.prototype.toLocaleString; Number.prototype.toLocaleString = 5; try { return new Int8Array([1]).toLocaleString(); } finally { Number.prototype.toLocaleString = save; } });
show('toLocaleString detached', function () { var b = new ArrayBuffer(2); var t = new Int8Array(b); b.transfer(); return t.toLocaleString(); });
show('iterators', function () { var o = new Int8Array([7, 8]); return JSON.stringify([...o.entries()]) + ' ' + [...o.keys()].join() + ' ' + [...o.values()].join() + ' ' + (o[Symbol.iterator] === o.values) + ' ' + Object.prototype.toString.call(o.values()) + ' ' + Array.from(new BigInt64Array([3n]).entries()).join(); });
show('iterator sees later writes', function () { var o = new Uint8Array([1, 2, 3]); var it = o.values(); it.next(); o[1] = 20; return [it.next().value, it.next().value, it.next().done].join(); });
show('spread/destructure', function () { var [a, , c] = new Int16Array([4, 5, 6]); return a + c + ' ' + Math.max(...new Uint8Array([3, 9, 2])); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("typed_array_join_locale_and_iterators")
    assert (r.returncode, r.stderr) == (0, b"")


def test_array_buffer_construction_slice_and_species(js, golden):
    """CATCHES: ArrayBuffer constructor validation (new requirement, ToIndex, maxByteLength option,
    allocation limits) or a slice() that ignores species, accepts shared/detached/immutable/too small
    results, or misses a source detached by the species constructor."""
    code = SHOW + r"""
show('ctor errors', function () { return tries([function () { return ArrayBuffer(1); }, function () { return new ArrayBuffer(-1); }, function () { return new ArrayBuffer(Infinity); }, function () { return new ArrayBuffer(4, { maxByteLength: -1 }); }, function () { return new ArrayBuffer(8, { maxByteLength: 4 }); }, function () { return new ArrayBuffer(2 ** 40); }, function () { return new ArrayBuffer(1, { maxByteLength: 2 ** 40 }); }, function () { return new ArrayBuffer(1, { maxByteLength: NaN }); }]); });
show('ctor coercion', function () { var a = new ArrayBuffer('3'); var b = new ArrayBuffer(NaN); var c = new ArrayBuffer(2.9, { maxByteLength: undefined }); var d = new ArrayBuffer(0, { maxByteLength: NaN }); var e = new ArrayBuffer(1, 'opts'); return [a.byteLength, b.byteLength, c.byteLength, c.resizable, c.maxByteLength, d.resizable, d.maxByteLength, e.resizable, new ArrayBuffer().byteLength].join(); });
show('isView', function () { return [ArrayBuffer.isView(new Int8Array(1)), ArrayBuffer.isView(new DataView(new ArrayBuffer(1))), ArrayBuffer.isView(new ArrayBuffer(1)), ArrayBuffer.isView({}), ArrayBuffer.isView(), ArrayBuffer.isView(Object.create(Int8Array.prototype))].join(); });
show('slice', function () { var ab = new ArrayBuffer(8); new Uint8Array(ab).set([1, 2, 3, 4, 5, 6, 7, 8]); return [new Uint8Array(ab.slice(2, -2)).join(), new Uint8Array(ab.slice(-3)).join(), ab.slice(5, 2).byteLength, ab.slice(NaN).byteLength, ab.slice(1, undefined).byteLength, ab.slice(-Infinity, Infinity).byteLength].join(' | '); });
show('slice species errors', function () { var r = []; var specs = [function () { return {}; }, function () { return new SharedArrayBuffer(8); }, function () { var b = new ArrayBuffer(8); b.transfer(); return b; }, function () { return new ArrayBuffer(8).transferToImmutable(); }, function (n) { return new ArrayBuffer(n - 1); }, function () { return new ArrayBuffer(8); }]; specs.forEach(function (sp) { var ab = new ArrayBuffer(8); ab.constructor = { [Symbol.species]: sp }; try { r.push(ab.slice(0, 4).byteLength); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('slice species same buffer', function () { var ab = new ArrayBuffer(8); ab.constructor = { [Symbol.species]: function () { return ab; } }; return ab.slice(0, 4); });
show('slice detaches source', function () { var ab = new ArrayBuffer(8); ab.constructor = { [Symbol.species]: function (n) { ab.transfer(); return new ArrayBuffer(n); } }; return ab.slice(0, 4); });
show('slice receivers', function () { return tries([function () { return ArrayBuffer.prototype.slice.call({}, 0); }, function () { return ArrayBuffer.prototype.slice.call(new SharedArrayBuffer(2), 0); }, function () { var d = new ArrayBuffer(2); d.transfer(); return d.slice(0); }]); });
show('subclass', function () { class B extends ArrayBuffer { get tag() { return 'B' + this.byteLength; } } var b = new B(3); return [b.tag, b.slice(1).tag, b instanceof ArrayBuffer, Object.prototype.toString.call(b)].join(); });
show('getters on non-buffer', function () { var P = ArrayBuffer.prototype; return ['byteLength', 'maxByteLength', 'resizable', 'detached'].map(function (k) { try { return Object.getOwnPropertyDescriptor(P, k).get.call({}); } catch (e) { return k + ':' + e.name; } }).join(' '); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("array_buffer_construction_slice_and_species")
    assert (r.returncode, r.stderr) == (0, b"")


def test_resizable_buffers_and_length_tracking_views(js, golden):
    """CATCHES: resizable ArrayBuffers whose resize() does not zero-fill or validate, length-tracking
    typed arrays/DataViews that do not follow the buffer, fixed views that do not report 0 when out
    of bounds, or typed-array methods that operate on an out-of-bounds view instead of throwing."""
    code = SHOW + r"""
show('resize', function () { var rb = new ArrayBuffer(4, { maxByteLength: 12 }); var u = new Uint8Array(rb); u.set([1, 2, 3, 4]); rb.resize(8); var a = Array.from(u).join(); rb.resize(2); var b = Array.from(u).join(); rb.resize(6); return a + ' | ' + b + ' | ' + Array.from(u).join() + ' | ' + rb.byteLength + '/' + rb.maxByteLength + ' ' + rb.resizable; });
show('resize errors', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); return tries([function () { rb.resize(9); }, function () { rb.resize(-1); }, function () { new ArrayBuffer(4).resize(2); }, function () { rb.resize(NaN); return rb.byteLength; }, function () { var d = new ArrayBuffer(2, { maxByteLength: 4 }); d.transfer(); d.resize(1); }, function () { var d = new ArrayBuffer(2, { maxByteLength: 4 }); d.resize({ valueOf: function () { d.transfer(); return 1; } }); }, function () { rb.resize(Infinity); }, function () { ArrayBuffer.prototype.resize.call({}, 1); }]); });
show('length tracking views', function () { var rb = new ArrayBuffer(8, { maxByteLength: 16 }); var t16 = new Int16Array(rb); var t16o = new Int16Array(rb, 2); var f = new Int16Array(rb, 4, 2); var dv = new DataView(rb, 2); var r = [t16.length, t16o.length, f.length, dv.byteLength]; rb.resize(5); r.push(t16.length, t16o.length, t16o.byteLength, dv.byteLength, f.length, f.byteOffset, f.byteLength); rb.resize(1); r.push(t16.length, t16o.length, t16o.byteOffset); try { dv.byteLength; } catch (e) { r.push('dv:' + e.message); } try { dv.byteOffset; } catch (e) { r.push('dvoff:' + e.name); } try { dv.getInt8(0); } catch (e) { r.push('dvget:' + e.name); } rb.resize(16); r.push(t16.length, t16o.length, f.length, dv.byteLength, f[1]); return r.join(','); });
show('oob typed array ops', function () { var rb = new ArrayBuffer(8, { maxByteLength: 16 }); var f = new Uint8Array(rb, 4, 4); rb.resize(2); var r = []; ['fill', 'copyWithin', 'sort', 'reverse', 'indexOf', 'lastIndexOf', 'includes', 'join', 'slice', 'map', 'filter', 'forEach', 'at', 'with', 'set', 'subarray', 'toLocaleString', 'entries', 'toSorted', 'toReversed', 'every', 'find'].forEach(function (m) { try { var v = m === 'set' ? f.set([1]) : m === 'with' ? f.with(0, 1) : /map|filter|forEach|every|find/.test(m) ? f[m](function (x) { return x; }) : m === 'sort' || m === 'toSorted' ? f[m]() : f[m](0); r.push(m + '=' + (v && typeof v === 'object' ? 'obj' : v)); } catch (e) { r.push(m + ':' + e.name); } }); return r.join(' ') + ' len=' + f.length + ' [0]=' + f[0]; });
show('tracking view element access', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var t = new Uint8Array(rb); t[3] = 9; rb.resize(2); var a = [t[3], t.length, 3 in t, Object.keys(t).join('/')]; t[3] = 5; rb.resize(4); a.push(t[3]); return a.join(); });
show('subarray of tracking', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var t = new Uint8Array(rb); var s = t.subarray(1); var s2 = t.subarray(1, 3); rb.resize(8); return s.length + ' ' + s2.length; });
show('method resizes mid-call', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var t = new Uint8Array(rb); t.set([1, 2, 3, 4]); var r = []; r.push(t.indexOf(4, { valueOf: function () { rb.resize(2); return 0; } })); rb.resize(4); t.set([1, 2, 3, 4]); r.push(t.includes(undefined, { valueOf: function () { rb.resize(2); return 0; } })); rb.resize(4); t.set([1, 2, 3, 4]); r.push(t.fill(7, { valueOf: function () { rb.resize(3); return 0; } }).join()); rb.resize(4); t.set([1, 2, 3, 4]); r.push(t.copyWithin(0, { valueOf: function () { rb.resize(3); return 1; } }).join()); rb.resize(4); t.set([1, 2, 3, 4]); r.push(t.lastIndexOf(1, { valueOf: function () { rb.transfer && rb.resize(1); return 3; } })); return r.join(' | '); });
show('fill/copyWithin detach mid-call', function () { var b = new ArrayBuffer(4); var t = new Uint8Array(b); return tries([function () { return t.fill(1, { valueOf: function () { b.transfer(); return 0; } }); }, function () { var b2 = new ArrayBuffer(4); var t2 = new Uint8Array(b2); return t2.copyWithin(0, { valueOf: function () { b2.transfer(); return 1; } }); }]); });
show('integrity', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); return tries([function () { return Object.isFrozen(Object.freeze(new Uint8Array(rb, 0, 0))); }, function () { return Object.isSealed(Object.seal(new Uint8Array(rb, 0, 2))); }]); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("resizable_buffers_and_length_tracking_views")
    assert (r.returncode, r.stderr) == (0, b"")


def test_transfer_detach_and_immutable_buffers(js, golden):
    """CATCHES: ArrayBuffer.prototype.transfer/transferToFixedLength/transferToImmutable/
    sliceToImmutable that lose contents or resizability, do not detach the source, accept shared or
    immutable buffers, or views over detached/immutable buffers that read or write anyway."""
    code = SHOW + r"""
show('transfer', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); new Uint8Array(rb)[0] = 9; var t = rb.transfer(); var t2 = t.transfer(6); var r = [rb.detached, t.detached, t2.resizable, t2.byteLength, t2.maxByteLength, new Uint8Array(t2)[0]]; var t3 = t2.transferToFixedLength(2); r.push(t2.detached, t3.resizable, t3.byteLength, new Uint8Array(t3)[0], new ArrayBuffer(2).transfer().resizable, new ArrayBuffer(3).transfer(1).byteLength); return r.join(); });
show('transfer grows with zeros', function () { var a = new ArrayBuffer(2); new Uint8Array(a).set([5, 6]); return new Uint8Array(a.transfer(4)).join() + ' ' + new Uint8Array(new ArrayBuffer(4, { maxByteLength: 8 }).transferToFixedLength(6)).join(); });
show('transfer errors', function () { return tries([function () { var d = new ArrayBuffer(2); d.transfer(); d.transfer(); }, function () { new ArrayBuffer(2).transfer(-1); }, function () { ArrayBuffer.prototype.transfer.call(new SharedArrayBuffer(2)); }, function () { new ArrayBuffer(2).transferToImmutable().transfer(); }, function () { ArrayBuffer.prototype.transfer.call({}); }, function () { var d = new ArrayBuffer(2); d.transfer(); d.transferToFixedLength(); }, function () { new ArrayBuffer(2).transfer(2 ** 53); }]); });
show('transfer length read before detach check', function () { var d = new ArrayBuffer(2); d.transfer(); var log = []; try { d.transfer({ valueOf: function () { log.push('len'); return 1; } }); } catch (e) { log.push(e.name); } return log.join(); });
show('detached getters', function () { var ab = new ArrayBuffer(4, { maxByteLength: 8 }); ab.transfer(); return [ab.byteLength, ab.maxByteLength, ab.detached, ab.resizable].join(); });
show('detached views', function () { var ab = new ArrayBuffer(8); var t = new Int32Array(ab); var dv = new DataView(ab); ab.transfer(); var r = [t.length, t.byteOffset, t.byteLength, t[0], 0 in t]; t[0] = 5; r.push(t[0]); r.push(tries([function () { return t.at(0); }, function () { return dv.getInt8(0); }, function () { return dv.byteLength; }, function () { return new Int8Array(ab); }, function () { return new DataView(ab); }, function () { return [...t]; }])); return r.join(','); });
show('detach via $262', function () { var ab = new ArrayBuffer(4); var v = new Int8Array(ab); $262.detachArrayBuffer(ab); return [v.length, ab.byteLength, ab.detached].join(); });
show('sliceToImmutable', function () { var ab = new ArrayBuffer(6); new Uint8Array(ab).set([1, 2, 3, 4, 5, 6]); var im = ab.sliceToImmutable(1, -1); var r = [im.immutable, im.byteLength, new Uint8Array(im).join(), ab.detached, ab.sliceToImmutable().byteLength, ab.sliceToImmutable(4, 2).byteLength, ab.immutable]; var d = new ArrayBuffer(2); d.transfer(); r.push(tries([function () { return d.sliceToImmutable(); }, function () { return ArrayBuffer.prototype.sliceToImmutable.call(new SharedArrayBuffer(1)); }, function () { return ArrayBuffer.prototype.sliceToImmutable.call({}); }, function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); return rb.sliceToImmutable(0, { valueOf: function () { rb.resize(1); return 4; } }); }])); return r.join(' | '); });
show('immutable writes', function () { var src = new ArrayBuffer(4); new Uint8Array(src).set([4, 3, 2, 1]); var im = src.transferToImmutable(); var t = new Uint8Array(im); var r = [src.detached, im.immutable, im.resizable, t.join()]; ['fill', 'copyWithin', 'reverse', 'sort', 'set'].forEach(function (m) { try { m === 'set' ? t.set([1]) : m === 'sort' ? t.sort() : t[m](0); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.message); } }); r.push(tries([function () { return Atomics.store(new Int32Array(im), 0, 1); }, function () { return t.setFromHex('ff'); }, function () { return t.setFromBase64('AA=='); }, function () { return new DataView(im).setBigInt64(0, 1n); }, function () { return im.resize(2); }, function () { return im.transfer(); }, function () { return t.with(0, 9).join(); }, function () { return t.toSorted().join(); }, function () { t[0] = 77; return t[0]; }, function () { 'use strict'; t[1] = 1; }])); return r.join(' | '); });
show('immutable species targets', function () { var im = new ArrayBuffer(4).transferToImmutable(); var o = new Uint8Array([1, 2]); o.constructor = { [Symbol.species]: function (n) { return new Uint8Array(im, 0, n); } }; return tries([function () { return o.slice(); }, function () { return o.map(function (x) { return x; }); }, function () { return o.subarray(0).length; }]); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("transfer_detach_and_immutable_buffers")
    assert (r.returncode, r.stderr) == (0, b"")


def test_shared_array_buffer_grow_and_slice(js, golden):
    """CATCHES: SharedArrayBuffer constructor/getter brand checks, grow() that shrinks or exceeds
    maxByteLength, or a slice() that aliases instead of copying or accepts an ArrayBuffer, the same
    buffer or an undersized species result."""
    code = SHOW + r"""
show('ctor', function () { var s = new SharedArrayBuffer(4); var g = new SharedArrayBuffer(2, { maxByteLength: 6 }); return [s.byteLength, s.growable, s.maxByteLength, g.growable, g.maxByteLength, Object.prototype.toString.call(s), new SharedArrayBuffer().byteLength, new SharedArrayBuffer(1, {}).growable].join(); });
show('ctor errors', function () { return tries([function () { return SharedArrayBuffer(1); }, function () { return new SharedArrayBuffer(-1); }, function () { return new SharedArrayBuffer(4, { maxByteLength: 2 }); }, function () { return new SharedArrayBuffer(2 ** 40); }, function () { return new SharedArrayBuffer(1, { maxByteLength: 2 ** 40 }); }]); });
show('getters on non-shared', function () { var P = SharedArrayBuffer.prototype; return ['byteLength', 'growable', 'maxByteLength'].map(function (k) { try { return Object.getOwnPropertyDescriptor(P, k).get.call(new ArrayBuffer(1)); } catch (e) { return k + ':' + e.message; } }).join(' | '); });
show('grow', function () { var g = new SharedArrayBuffer(2, { maxByteLength: 6 }); var t = new Uint8Array(g); g.grow(5); var r = [g.byteLength, t.length]; r.push(tries([function () { g.grow(1); }, function () { g.grow(7); }, function () { new SharedArrayBuffer(2).grow(3); }, function () { SharedArrayBuffer.prototype.grow.call(1, 2); }, function () { g.grow(NaN); }])); g.grow(5); r.push(g.byteLength); return r.join(','); });
show('slice', function () { var s = new SharedArrayBuffer(6); new Uint8Array(s).set([1, 2, 3, 4, 5, 6]); var c = s.slice(1, -1); var r = [c instanceof SharedArrayBuffer, c.byteLength, new Uint8Array(c).join(), s.slice(-2).byteLength, s.slice(4, 1).byteLength, s.slice().byteLength]; new Uint8Array(c)[0] = 99; r.push(new Uint8Array(s)[1]); return r.join(); });
show('slice errors', function () { return tries([function () { return SharedArrayBuffer.prototype.slice.call(new ArrayBuffer(2)); }, function () { var s = new SharedArrayBuffer(4); s.constructor = { [Symbol.species]: function () { return new ArrayBuffer(4); } }; return s.slice(0); }, function () { var s = new SharedArrayBuffer(4); s.constructor = { [Symbol.species]: function () { return s; } }; return s.slice(0); }, function () { var s = new SharedArrayBuffer(4); s.constructor = { [Symbol.species]: function () { return new SharedArrayBuffer(1); } }; return s.slice(0); }, function () { var s = new SharedArrayBuffer(4); new Uint8Array(s).set([9, 8, 7, 6]); s.constructor = { [Symbol.species]: function (n) { return new SharedArrayBuffer(n + 2); } }; var c = s.slice(1); return c.byteLength + ':' + new Uint8Array(c).join(); }]); });
show('views alias', function () { var s = new SharedArrayBuffer(8); var a = new Int32Array(s); var b = new Uint8Array(s, 4); a[1] = -1; return b.join() + ' ' + new DataView(s).getInt32(4) + ' ' + structuredClone(a).length; });
show('transfer shared', function () { return ArrayBuffer.prototype.transfer.call(new SharedArrayBuffer(2)); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("shared_array_buffer_grow_and_slice")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dataview_get_set_all_types_and_endianness(js, golden):
    """CATCHES: DataView getters/setters with the wrong default (big-endian) or little-endian byte
    order for any of the 11 element types, wrong value conversion (wrapping, Float16/Float32
    rounding, BigInt modular wrapping), or reading/writing at the wrong view offset."""
    code = SHOW + r"""
var dv = new DataView(new ArrayBuffer(24), 4);
var types = [['Int8', -100], ['Uint8', 200], ['Int16', -12345], ['Uint16', 54321], ['Int32', -123456789], ['Uint32', 3123456789], ['Float16', 1.5], ['Float32', -2.75], ['Float64', Math.PI], ['BigInt64', -1234567890123n], ['BigUint64', 18446744073709551000n]];
types.forEach(function (t) {
  show(t[0], function () {
    var r = [];
    [false, true].forEach(function (le) { dv['set' + t[0]](2, t[1], le); var bytes = Array.from(new Uint8Array(dv.buffer, 6, 8), function (b) { return b.toString(16).padStart(2, '0'); }).join(''); r.push((le ? 'LE ' : 'BE ') + bytes + ' -> ' + dv['get' + t[0]](2, le) + ' / swapped ' + dv['get' + t[0]](2, !le)); new Uint8Array(dv.buffer).fill(0); });
    return r.join(' ; ');
  });
});
show('lengths', function () { return types.map(function (t) { return DataView.prototype['get' + t[0]].length + '/' + DataView.prototype['set' + t[0]].length; }).join(' '); });
show('conversions', function () { dv.setUint8(0, 257); dv.setInt8(1, 255); dv.setUint16(2, -1); dv.setFloat32(4, 1e40); dv.setFloat16(8, 70000); dv.setBigInt64(10, 2n ** 64n + 3n); return [dv.getUint8(0), dv.getInt8(1), dv.getUint16(2), dv.getFloat32(4), dv.getFloat16(8), dv.getBigInt64(10), dv.getBigUint64(10, true)].join(); });
show('truthy littleEndian', function () { dv.setUint16(0, 0x0102, 'yes'); var a = dv.getUint8(0); dv.setUint16(0, 0x0102, 0); return a + ' ' + dv.getUint8(0) + ' ' + dv.getUint16(0, {}); });
show('NaN preserved', function () { dv.setFloat64(0, NaN); return dv.getFloat64(0) + ' ' + dv.getUint8(0).toString(16); });
show('setter returns undefined', function () { return [dv.setInt8(0, 1), dv.setBigUint64(0, 1n), dv.setFloat16(0, 1)].join() + '|'; });
show('shared dataview', function () { var s = new SharedArrayBuffer(8); var d = new DataView(s); d.setUint32(0, 0xdeadbeef); d.setBigUint64(0, 0x0102030405060708n, true); var u = new Uint8Array(s); return [d.getUint16(6), u.join(), d.byteLength, d.getBigInt64(0), d.getFloat64(0, true)].join(' '); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("dataview_get_set_all_types_and_endianness")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dataview_bounds_receivers_and_resizable_buffers(js, golden):
    """CATCHES: DataView offset/length validation (ToIndex RangeErrors, reads past the view end),
    missing receiver brand checks on methods and buffer/byteLength/byteOffset getters, detach or
    resize during argument coercion not being re-checked, or length-tracking views over resizable
    buffers reporting stale lengths."""
    code = SHOW + r"""
var dv = new DataView(new ArrayBuffer(24), 4);
show('offset errors', function () { return tries([function () { return dv.getInt32(17); }, function () { return dv.setInt16(19, 1); }, function () { return dv.getInt8(-1); }, function () { return dv.getFloat64(2 ** 53); }, function () { return dv.getBigInt64(13); }, function () { return dv.setBigUint64(16, 1n); }, function () { return dv.setBigInt64(0, 1); }, function () { return dv.getUint8(); }, function () { return dv.getUint8('3'); }, function () { return dv.getUint8(1.9); }, function () { return dv.getInt8(20); }]); });
show('receiver checks', function () { var r = []; ['getInt8', 'setInt8', 'getBigInt64', 'setBigUint64', 'getFloat16'].forEach(function (m) { try { DataView.prototype[m].call(new Int8Array(4), 0, 0n); } catch (e) { r.push(m + ':' + e.message); } }); ['buffer', 'byteLength', 'byteOffset'].forEach(function (k) { try { Object.getOwnPropertyDescriptor(DataView.prototype, k).get.call({}); } catch (e) { r.push(k + ':' + e.message); } }); return r.join(' | '); });
show('getters', function () { var b = new ArrayBuffer(10); var d = new DataView(b, 3, 4); return [d.buffer === b, d.byteOffset, d.byteLength, new DataView(b, 10).byteLength, new DataView(b).byteLength, Object.prototype.toString.call(d), new DataView(b, '2', '3').byteLength, new DataView(b, undefined, undefined).byteLength].join(); });
show('ctor errors', function () { var b = new ArrayBuffer(4); return tries([function () { return DataView(b); }, function () { return new DataView({}); }, function () { return new DataView(b, 5); }, function () { return new DataView(b, 2, 3); }, function () { return new DataView(b, -1); }, function () { return new DataView(b, 1, -1); }, function () { var d = new ArrayBuffer(2); d.transfer(); return new DataView(d); }, function () { var d = new ArrayBuffer(4); return new DataView(d, { valueOf: function () { d.transfer(); return 0; } }); }, function () { var d = new ArrayBuffer(4); return new DataView(d, 0, { valueOf: function () { d.transfer(); return 1; } }); }, function () { return new DataView(new Int8Array(4).buffer, 0, 5); }]); });
show('newTarget prototype access detaches', function () { var d = new ArrayBuffer(4); var nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { get: function () { d.transfer(); return DataView.prototype; } }); return tries([function () { return Reflect.construct(DataView, [d, 0], nt); }]); });
show('newTarget prototype shrinks', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { get: function () { rb.resize(1); return DataView.prototype; } }); return tries([function () { return Reflect.construct(DataView, [rb, 2], nt); }, function () { rb.resize(4); return Reflect.construct(DataView, [rb, 0, 3], nt).byteLength; }]); });
show('detached mid-call', function () { var mk = function () { var b = new ArrayBuffer(8); return [b, new DataView(b)]; }; return tries([function () { var p = mk(); return p[1].setInt8({ valueOf: function () { p[0].transfer(); return 0; } }, 1); }, function () { var p = mk(); return p[1].getBigInt64({ valueOf: function () { p[0].transfer(); return 0; } }); }, function () { var p = mk(); return p[1].setBigInt64(0, { valueOf: function () { p[0].transfer(); return 0n; } }); }, function () { var p = mk(); return p[1].getFloat32({ valueOf: function () { p[0].transfer(); return 0; } }); }, function () { var p = mk(); return p[1].setFloat64(0, { valueOf: function () { p[0].transfer(); return 1; } }); }]); });
show('resizable dataview', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); var d = new DataView(rb); var fixed = new DataView(rb, 1, 2); rb.resize(8); var r = [d.byteLength, fixed.byteLength]; d.setInt32(4, -2); r.push(d.getInt32(4), d.getBigInt64(0, true)); rb.resize(2); r.push(d.byteLength); r.push(tries([function () { return fixed.byteLength; }, function () { return fixed.getInt8(0); }, function () { return d.getInt32(0); }, function () { return fixed.setInt8(0, 1); }, function () { return d.getBigInt64(0); }, function () { return d.setBigInt64(0, 1n); }, function () { return d.setInt16(1, 1); }])); var late = new DataView(rb, 2); rb.resize(1); r.push(tries([function () { return late.byteLength; }, function () { return late.byteOffset; }, function () { return late.getUint8(0); }, function () { return late.getBigUint64(0); }, function () { return late.setBigInt64(0, 0n); }])); return r.join(','); });
show('resizable dataview with length', function () { var rb = new ArrayBuffer(4, { maxByteLength: 8 }); return tries([function () { return new DataView(rb, 1, 3).byteLength; }, function () { return new DataView(rb, 1, 4).byteLength; }, function () { return new DataView(rb, 5).byteLength; }]); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("dataview_bounds_receivers_and_resizable_buffers")
    assert (r.returncode, r.stderr) == (0, b"")


def test_atomics_operations_and_validation(js, golden):
    """CATCHES: Atomics read-modify-write operations that return the new instead of the old value,
    do not wrap per element type, return an unconverted value from store, accept float/clamped/
    non-typed-array targets, or miss index range checks and detach/shrink-during-coercion errors."""
    code = SHOW + r"""
show('ops on every int kind', function () { return [Int8Array, Uint8Array, Int16Array, Uint16Array, Int32Array, Uint32Array].map(function (K) { var t = new K(new SharedArrayBuffer(8)); return K.name + ':' + [Atomics.store(t, 0, -5), Atomics.add(t, 0, 300), Atomics.sub(t, 0, 1), Atomics.and(t, 0, 0xff), Atomics.or(t, 0, 0x100), Atomics.xor(t, 0, 3), Atomics.exchange(t, 0, 7), Atomics.compareExchange(t, 0, 7, -1), Atomics.compareExchange(t, 0, 5, 6), Atomics.load(t, 0)].join(','); }).join(' '); });
show('bigint kinds non-shared', function () { var t = new BigUint64Array(2); var s = new BigInt64Array(2); return [Atomics.store(t, 0, -1n), Atomics.add(t, 0, 2n), Atomics.load(t, 0), Atomics.sub(s, 1, 1n), Atomics.and(s, 1, 6n), Atomics.or(s, 1, 1n), Atomics.xor(s, 1, 3n), Atomics.load(s, 1), Atomics.compareExchange(s, 1, 4n, 9n), Atomics.exchange(s, 1, -9n), Atomics.load(s, 1), Atomics.compareExchange(t, 0, 1n, 2n)].join(','); });
show('store returns coerced', function () { var t = new Int8Array(1); return [Atomics.store(t, 0, 3.7), Atomics.store(t, 0, -0), Object.is(Atomics.store(t, 0, -0), 0), Atomics.store(t, 0, '300'), t[0], Atomics.store(new BigInt64Array(1), 0, 2n ** 70n)].join(); });
show('index coercion', function () { var t = new Int32Array(4); Atomics.store(t, '2', 5); return [Atomics.load(t, 2.9), Atomics.load(t, { valueOf: function () { return 2; } }), Atomics.load(t)].join(); });
show('errors', function () { return tries([function () { return Atomics.add(new Float32Array(1), 0, 1); }, function () { return Atomics.add(new Uint8ClampedArray(1), 0, 1); }, function () { return Atomics.load(new Int32Array(2), 2); }, function () { return Atomics.load(new Int32Array(2), -1); }, function () { return Atomics.add(new BigInt64Array(1), 0, 1); }, function () { return Atomics.add(new Int32Array(1), 0, 1n); }, function () { return Atomics.load({}, 0); }, function () { return Atomics.load([1], 0); }, function () { var b = new ArrayBuffer(8); var t = new Int32Array(b); b.transfer(); return Atomics.load(t, 0); }, function () { var b = new ArrayBuffer(8, { maxByteLength: 8 }); var t = new Int32Array(b); return Atomics.store(t, 1, { valueOf: function () { b.resize(4); return 1; } }); }, function () { var b = new ArrayBuffer(8); var t = new Int32Array(b); return Atomics.exchange(t, 0, { valueOf: function () { b.transfer(); return 1; } }); }, function () { return Atomics.compareExchange(new Float64Array(1), 0, 0, 1); }]); });
show('isLockFree/pause', function () { return [1, 2, 3, 4, 8, 16].map(function (n) { return Atomics.isLockFree(n); }).join() + ' ' + Atomics.pause() + ' ' + Atomics.pause(3) + ' ' + Atomics.pause(-0) + ' ' + Object.prototype.toString.call(Atomics); });
show('pause bad', function () { return tries([function () { return Atomics.pause(1.5); }, function () { return Atomics.pause('1'); }, function () { return Atomics.pause(Infinity); }, function () { return Atomics.pause(null); }]); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("atomics_operations_and_validation")
    assert (r.returncode, r.stderr) == (0, b"")


def test_atomics_wait_notify_and_agent_threads(js, golden):
    """CATCHES: Atomics.wait/notify/waitAsync that accept non-Int32/BigInt64 arrays, ignore the
    expected value (not-equal) or the timeout (timed-out), miscount woken waiters, or a $262.agent
    thread that does not share SharedArrayBuffer memory with the main thread."""
    code = SHOW + r"""
show('wait/notify validation', function () { return tries([function () { return Atomics.wait(new Int16Array(new SharedArrayBuffer(8)), 0, 0); }, function () { return Atomics.notify(new Float64Array(1), 0); }, function () { return Atomics.notify(new Int32Array(4), 0); }, function () { return Atomics.wait(new BigInt64Array(new SharedArrayBuffer(8)), 0, 1n, 0); }, function () { return Atomics.wait(new BigInt64Array(new SharedArrayBuffer(8)), 0, 0n, 0); }, function () { return Atomics.notify(new Int32Array(new SharedArrayBuffer(8)), 0, -3); }, function () { return Atomics.notify(new Int32Array(new SharedArrayBuffer(8)), 0, Infinity); }, function () { return Atomics.notify(new Int32Array(new SharedArrayBuffer(8)), 0, NaN); }, function () { return Atomics.wait(new Int32Array(new SharedArrayBuffer(8)), 0, 0, -5); }, function () { var b = new ArrayBuffer(8); var t = new Int32Array(b); b.transfer(); return Atomics.notify(t, 0); }, function () { return Atomics.waitAsync(new Int32Array(4), 0, 0); }, function () { return Atomics.notify(new Int32Array(new SharedArrayBuffer(8)), 9); }]); });
show('waitAsync sync results', function () { var w = new Int32Array(new SharedArrayBuffer(8)); return JSON.stringify(Atomics.waitAsync(w, 0, 1)) + ' ' + JSON.stringify(Atomics.waitAsync(w, 0, 0, 0)) + ' ' + JSON.stringify(Atomics.waitAsync(new BigInt64Array(new SharedArrayBuffer(8)), 0, 0n, -1)); });
var w = new Int32Array(new SharedArrayBuffer(16));
var res = Atomics.waitAsync(w, 1, 0);
out.push('waitAsync pending: ' + res.async + ' ' + Object.prototype.toString.call(res.value));
out.push('notify count: ' + Atomics.notify(w, 1) + ' then ' + Atomics.notify(w, 1) + ' other index ' + Atomics.notify(w, 2));
var sab = new SharedArrayBuffer(16);
var ia = new Int32Array(sab);
$262.agent.start(`
  $262.agent.receiveBroadcast(function (buf) {
    var t = new Int32Array(buf);
    Atomics.add(t, 0, 5);
    var w = Atomics.wait(t, 1, 99, 0);
    var w2 = Atomics.wait(t, 1, 0, 0);
    $262.agent.report('agent saw ' + t[0] + ' wait=' + w + '/' + w2);
    $262.agent.leaving();
  });
`);
ia[0] = 10;
$262.agent.broadcast(ia);
var rep;
while ((rep = $262.agent.getReport()) === null) $262.agent.sleep(1);
out.push(rep + ' | main sees ' + Atomics.load(ia, 0));
out.push(tries([function () { return $262.agent.broadcast({}); }, function () { return $262.agent.broadcast(1); }, function () { return typeof $262.agent.monotonicNow(); }, function () { return $262.agent.leaving(); }]));
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("atomics_wait_notify_and_agent_threads")
    assert (r.returncode, r.stderr) == (0, b"")


def test_base64_and_hex_encoding(js, golden):
    """CATCHES: Uint8Array toBase64/toHex/fromBase64/fromHex with wrong padding, base64url alphabet
    mapping, whitespace skipping, lastChunkHandling (loose/strict/stop-before-partial) semantics, or
    missing TypeErrors/SyntaxErrors for bad options, receivers and inputs."""
    code = SHOW + r"""
var u = function (a) { return new Uint8Array(a); };
show('toBase64', function () { return [u([]).toBase64(), u([0xfb]).toBase64(), u([0xfb, 0xff]).toBase64(), u([0xfb, 0xff, 0xbf]).toBase64(), u([0xfb]).toBase64({ omitPadding: true }), u([0xfb, 0xff]).toBase64({ alphabet: 'base64url' }), u([0xfb, 0xff]).toBase64({ alphabet: 'base64url', omitPadding: 1 }), u([1, 2, 3, 4]).toBase64({ omitPadding: 0 }), u([0xfb, 0xef]).toBase64({})].join(' '); });
show('toBase64 bad options', function () { return tries([function () { return u([1]).toBase64({ alphabet: 'hex' }); }, function () { return u([1]).toBase64(5); }, function () { return u([1]).toBase64(null); }]); });
show('toHex', function () { return u([0, 15, 16, 255]).toHex() + ' ' + u([]).toHex().length + ' ' + u([1, 2, 3]).subarray(1).toHex(); });
show('receivers', function () { return tries([function () { return Uint8Array.prototype.toBase64.call(new Int8Array(1)); }, function () { return Uint8Array.prototype.toHex.call([]); }, function () { var b = new ArrayBuffer(2); var t = new Uint8Array(b); b.transfer(); return t.toHex(); }]); });
show('fromBase64 variants', function () { return ['Zg==', 'Zg', 'Zm8=', 'Zm9v', ' Z m 9 v ', 'Zm9v\nYmFy', 'Zg=\t=', '', '-_8', '+/8=', '\tZm9v\r\n'].map(function (s) { try { var o = /[-_]/.test(s) ? { alphabet: 'base64url' } : undefined; return JSON.stringify(s) + '=' + Uint8Array.fromBase64(s, o).join('.'); } catch (e) { return JSON.stringify(s) + ':' + e.name; } }).join(' '); });
show('lastChunkHandling', function () { var r = []; ['Zg', 'Zm8', 'Zh==', 'Zm9=', 'Z', 'Zg=', 'Zm9vYg', 'Zm9vYmE=', 'Zm9vY', 'Zm9v =', 'Zg== '].forEach(function (s) { ['loose', 'strict', 'stop-before-partial'].forEach(function (h) { try { r.push(JSON.stringify(s) + '/' + h.slice(0, 4) + '=' + Uint8Array.fromBase64(s, { lastChunkHandling: h }).join('.')); } catch (e) { r.push(JSON.stringify(s) + '/' + h.slice(0, 4) + ':' + e.name); } }); }); return r.join(' '); });
show('fromBase64 errors', function () { var r = []; [['Zg==Zg==', undefined], ['Zm9v=', undefined], ['Z===', undefined], ['+/', { alphabet: 'base64url' }], ['-_', undefined], ['Zg', { lastChunkHandling: 'nope' }], ['Zg', { alphabet: 1 }], [5, undefined], ['Zg', 'opts'], ['Zg', { lastChunkHandling: undefined }], ['Zm9v!', undefined], ['Z=', undefined]].forEach(function (c) { try { r.push(Uint8Array.fromBase64(c[0], c[1]).join('.')); } catch (e) { r.push(e.name + ':' + e.message); } }); return r.join(' | '); });
show('fromHex', function () { var r = []; ['', '00ff', 'AbCd', 'abc', 'zz', 'a g0', '0x10'].forEach(function (s) { try { r.push(JSON.stringify(s) + '=' + Uint8Array.fromHex(s).join('.')); } catch (e) { r.push(JSON.stringify(s) + ':' + e.name + ':' + e.message); } }); try { Uint8Array.fromHex(1); } catch (e) { r.push(e.message); } return r.join(' | '); });
show('roundtrip', function () { var bytes = new Uint8Array(256); for (var i = 0; i < 256; i++) bytes[i] = (i * 37) & 255; var b = bytes.toBase64(), h = bytes.toHex(), url = bytes.toBase64({ alphabet: 'base64url', omitPadding: true }); return [b.length, h.length, url.length, Uint8Array.fromBase64(b).toHex() === h, Uint8Array.fromHex(h).toBase64() === b, Uint8Array.fromBase64(url, { alphabet: 'base64url' }).toHex() === h, b.slice(0, 12), url.slice(-6)].join(' '); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("base64_and_hex_encoding")
    assert (r.returncode, r.stderr) == (0, b"")


def test_base64_and_hex_decoding_into_existing_arrays(js, golden):
    """CATCHES: Uint8Array setFromBase64/setFromHex that report wrong {read, written} counts, overrun
    the target, decode a chunk that no longer fits, fail to write the valid prefix before throwing,
    ignore subarray offsets, or accept non-string input / non-Uint8Array receivers."""
    code = SHOW + r"""
show('setFromBase64', function () { var t = new Uint8Array(5); var r1 = t.setFromBase64('Zm9vYmFy'); var a = t.join(); var t2 = new Uint8Array(8); var r2 = t2.setFromBase64('  Zm 9v  '); var t3 = new Uint8Array(4); var r3 = t3.setFromBase64('Zm9vYg==', { lastChunkHandling: 'strict' }); var t4 = new Uint8Array(1); var r4 = t4.setFromBase64('Zm9v'); var t5 = new Uint8Array(2); var r5 = t5.setFromBase64('Zm9v'); var t6 = new Uint8Array(6); var r6 = t6.setFromBase64('Zm9vYmFy'); return [JSON.stringify(r1), a, JSON.stringify(r2), t2.join(), JSON.stringify(r3), t3.join(), JSON.stringify(r4), JSON.stringify(r5), t5.join(), JSON.stringify(r6), t6.join()].join(' '); });
show('setFromBase64 url and partial', function () { var t = new Uint8Array(6); var r = t.setFromBase64('-_8', { alphabet: 'base64url' }); var t2 = new Uint8Array(6); var r2 = t2.setFromBase64('Zm9vYmE', { lastChunkHandling: 'stop-before-partial' }); var t3 = new Uint8Array(6); var r3 = t3.setFromBase64('Zm9vYmE'); var t4 = new Uint8Array(4); var r4 = t4.setFromBase64('Zm9vYg==', { lastChunkHandling: 'stop-before-partial' }); var t5 = new Uint8Array(4); var r5 = t5.setFromBase64('Zm9vYg=', { lastChunkHandling: 'stop-before-partial' }); return [JSON.stringify(r) + t.join(), JSON.stringify(r2) + t2.join(), JSON.stringify(r3) + t3.join(), JSON.stringify(r4) + t4.join(), JSON.stringify(r5) + t5.join()].join(' '); });
show('setFromBase64 exact fit', function () { var t = new Uint8Array(3); var r = t.setFromBase64('Zm9vYmFy'); var t2 = new Uint8Array(4); var r2 = t2.setFromBase64('Zm9vYmE='); return JSON.stringify(r) + t.join() + ' ' + JSON.stringify(r2) + t2.join(); });
show('setFromBase64 error writes prefix', function () { var t = new Uint8Array(6); try { t.setFromBase64('Zm9v$mFy'); } catch (e) { return e.name + ':' + e.message + ' ' + t.join(); } });
show('setFromBase64 strict bad tail', function () { var t = new Uint8Array(6); try { t.setFromBase64('Zm9vYh==', { lastChunkHandling: 'strict' }); } catch (e) { return e.name + ' ' + t.join(); } });
show('setFromBase64 misc', function () { return tries([function () { return JSON.stringify(new Uint8Array(0).setFromBase64('Zm9v')); }, function () { return new Uint8Array(2).setFromBase64(1); }, function () { return new Uint8Array(2).setFromBase64('AA', { alphabet: 'x' }); }, function () { return Uint8Array.prototype.setFromBase64.call(new Uint16Array(2), 'AA'); }, function () { var b = new ArrayBuffer(2); var t = new Uint8Array(b); b.transfer(); return t.setFromBase64('AA'); }]); });
show('setFromHex', function () { var t = new Uint8Array(3); var r = t.setFromHex('aabbccdd'); var t2 = new Uint8Array(4); var r2 = t2.setFromHex('0102'); var t3 = new Uint8Array(4); var e; try { t3.setFromHex('01x2'); } catch (x) { e = x.name + ':' + x.message; } var t4 = new Uint8Array(4); try { t4.setFromHex('0102f'); } catch (x) { e += ' ' + x.name + ' ' + t4.join(); } return JSON.stringify(r) + t.join() + ' ' + JSON.stringify(r2) + t2.join() + ' ' + e + ' ' + t3.join(); });
show('setFromHex misc', function () { return tries([function () { return new Uint8Array(2).setFromHex(null); }, function () { return JSON.stringify(new Uint8Array(0).setFromHex('ff')); }, function () { return Uint8Array.prototype.setFromHex.call(new Int8Array(2), '00'); }]); });
show('setFrom on subarray', function () { var base = new Uint8Array(6); base.subarray(2, 5).setFromHex('ffeeddcc'); var b2 = new Uint8Array(6); var r = b2.subarray(3).setFromBase64('AQID'); return base.join() + ' ' + b2.join() + ' ' + JSON.stringify(r); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("base64_and_hex_decoding_into_existing_arrays")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_date_construction_and_getters(js, golden, tier):
    """CATCHES: Date construction from components that does not map two-digit years to 19xx,
    mis-carries month/day/time overflow, ignores NaN components or TimeClip, or local/UTC getters
    (fixture TZ is UTC) that disagree with the Gregorian calendar for leap, negative and far years."""
    code = SHOW + r"""
function all(d) { return [d.getFullYear(), d.getMonth(), d.getDate(), d.getDay(), d.getHours(), d.getMinutes(), d.getSeconds(), d.getMilliseconds(), d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCDay(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds(), d.getTimezoneOffset(), d.getTime(), d.valueOf()].join(); }
show('components', function () { return all(new Date(2020, 0, 31, 13, 45, 12, 345)); });
show('leap day', function () { return all(new Date(2000, 1, 29)); });
show('epoch and negative', function () { return all(new Date(0)) + ' / ' + all(new Date(-1)) + ' / ' + all(new Date(-62198755200000)); });
show('far dates', function () { return all(new Date(8.64e15)) + ' / ' + all(new Date(-8.64e15)); });
show('invalid getters', function () { return all(new Date(NaN)); });
show('two-digit year', function () { return [new Date(99, 0).getFullYear(), new Date(0, 0).getFullYear(), new Date(100, 0).getFullYear(), new Date(-1, 0).getFullYear(), new Date(99.9, 0).getFullYear(), new Date('50', 0).getFullYear()].join(); });
show('overflow components', function () { return [new Date(2020, 12, 1), new Date(2020, -1, 1), new Date(2020, 1, 30), new Date(2020, 0, 1, 25, 61, 61, 1001), new Date(2021, 1, 29), new Date(2020, 0, 0), new Date(2020, 0, 1, -1), new Date(2020, 0, 1, 0, 0, 0, -1), new Date(1970, 0, 1, 0, 0, 0, 0.9)].map(function (d) { return d.toISOString(); }).join(' '); });
show('NaN components', function () { return [new Date(NaN).getTime(), new Date(2020, NaN).getTime(), new Date(2020, 0, 1, 0, 0, 0, Infinity).getTime(), new Date('x', 1).getTime(), String(new Date(2020, undefined)), new Date(2e5 * 365, 0).getTime(), new Date(275760, 8, 13, 0, 0, 0, 1).getTime()].join(); });
show('ms ctor and clip', function () { return [new Date(8.64e15 + 1).getTime(), new Date(1.9).getTime(), new Date(-1.9).getTime(), Object.is(new Date(-0).getTime(), 0), new Date(true).getTime(), new Date(null).getTime(), new Date(undefined).getTime(), new Date('').getTime(), new Date(Infinity).getTime()].join(' '); });
show('date from objects', function () { var d = new Date(5); d.valueOf = function () { return 99; }; return new Date(d).getTime() + ' ' + new Date({ valueOf: function () { return 7; } }).getTime() + ' ' + new Date({ toString: function () { return '1970-01-01T00:00:00.010Z'; }, valueOf: undefined }).getTime() + ' ' + new Date({ [Symbol.toPrimitive]: function (h) { return h === 'default' ? 3 : 4; } }).getTime() + ' ' + new Date(new String('1970-01-01T00:00:00.020Z')).getTime(); });
show('coercion order', function () { var log = []; var arg = function (n, v) { return { valueOf: function () { log.push(n); return v; } }; }; new Date(arg('y', 2000), arg('m', 1), arg('d', 2), arg('h', 3), arg('mi', 4), arg('s', 5), arg('ms', 6), arg('extra', 7)); return log.join(); });
show('getYear', function () { return [new Date(Date.UTC(1999, 0)).getYear(), new Date(Date.UTC(2024, 0)).getYear(), new Date(Date.UTC(1850, 0)).getYear(), new Date(NaN).getYear()].join(); });
var acc = 0; for (var i = 0; i < 200; i++) { var dd = new Date(2000 + (i % 30), i % 12, 1 + (i % 28), i % 24); acc += dd.getDay() + dd.getDate() + dd.getMonth() + dd.getHours(); }
out.push('hot loop ' + acc);
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("date_construction_and_getters")
    assert (r.returncode, r.stderr) == (0, b"")


def test_date_string_formats(js, golden):
    """CATCHES: Date toString/toDateString/toTimeString/toUTCString/toISOString/toJSON with wrong
    weekday/month names, zero padding, signed six-digit extended years in ISO strings, negative or
    five-digit years, the RangeError for invalid ISO output, or 'Invalid Date' handling."""
    code = SHOW + r"""
show('strings', function () { var d = new Date(Date.UTC(2024, 1, 29, 7, 5, 9, 4)); return [d.toString(), d.toDateString(), d.toTimeString(), d.toUTCString(), d.toGMTString(), d.toISOString(), d.toJSON(), String(d), d + '', JSON.stringify({ d: d }), `${d}`].join(' | '); });
show('every weekday/month', function () { var r = []; for (var m = 0; m < 12; m++) r.push(new Date(Date.UTC(2023, m, 1 + m)).toUTCString().slice(0, 16)); return r.join(' ; '); });
show('extended years', function () { return [Date.UTC(-1, 0, 1), Date.UTC(10000, 0, 1), Date.UTC(0, 0, 1), -62198755200000, Date.UTC(275760, 8, 13), Date.UTC(-271821, 3, 20), Date.UTC(9999, 11, 31, 23, 59, 59, 999), -62167219200001].map(function (t) { return new Date(t).toISOString(); }).join(' '); });
show('toISOString invalid', function () { return new Date(NaN).toISOString(); });
show('invalid strings', function () { var d = new Date(NaN); return [d.toString(), d.toDateString(), d.toTimeString(), d.toUTCString(), JSON.stringify(d.toJSON()), d.toLocaleString(), d.toLocaleDateString(), d.toLocaleTimeString(), JSON.stringify([d]), String(d)].join(' | '); });
show('negative and big years', function () { var d = new Date(Date.UTC(-44, 2, 15, 12)); var z = new Date(Date.UTC(0, 0, 1)); z.setUTCFullYear(0); return d.toString() + ' | ' + d.toUTCString() + ' | ' + d.toDateString() + ' | ' + z.toDateString() + ' | ' + new Date(Date.UTC(12345, 0, 1)).toUTCString() + ' | ' + new Date(Date.UTC(-12345, 0, 1)).toISOString(); });
show('toGMTString identity', function () { return Date.prototype.toGMTString === Date.prototype.toUTCString; });
show('locale strings', function () { var d = new Date(Date.UTC(2024, 6, 4, 15, 30, 45)); return [d.toLocaleString(), d.toLocaleDateString(), d.toLocaleTimeString(), d.toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }), d.toLocaleDateString('en-US', { month: 'long' }), d.toLocaleTimeString('en-US', { hour: 'numeric' }), d.toLocaleTimeString('en-US', { timeStyle: 'short' }), d.toLocaleDateString('en-US', { dateStyle: 'medium' }), d.toLocaleString('en-US', { year: 'numeric' })].join(' | '); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("date_string_formats")
    assert (r.returncode, r.stderr) == (0, b"")


def test_date_setters_overflow_and_nan(js, golden):
    """CATCHES: Date setters that do not coerce every argument before applying, carry overflow
    incorrectly between fields, fail to return/stored NaN for non-finite or out-of-range results,
    treat a NaN date as epoch for the wrong setters (only set[UTC]FullYear/setYear do), or ignore the
    Annex B setYear two-digit rule."""
    code = SHOW + r"""
function fresh() { return new Date(Date.UTC(2021, 4, 15, 10, 20, 30, 400)); }
var setters = [['setMilliseconds', [999]], ['setMilliseconds', [1000]], ['setSeconds', [59, 999]], ['setSeconds', [-1]], ['setMinutes', [5, 6, 7]], ['setMinutes', [60]], ['setHours', [23, 59, 59, 999]], ['setHours', [-25]], ['setDate', [31]], ['setDate', [0]], ['setMonth', [1, 29]], ['setMonth', [13]], ['setMonth', [-1, 31]], ['setFullYear', [2024, 1, 29]], ['setFullYear', [2023, 1, 29]], ['setFullYear', [-5]], ['setFullYear', [275760, 8, 14]],
  ['setUTCMilliseconds', [-1]], ['setUTCSeconds', [1.9, 2.9]], ['setUTCMinutes', [0, 0, 0]], ['setUTCHours', [48]], ['setUTCDate', [366]], ['setUTCMonth', [11, 31]], ['setUTCFullYear', [1999, 11, 31]], ['setUTCMonth', [0, 1, 99]],
  ['setHours', []], ['setHours', [NaN]], ['setMinutes', [1, Infinity]], ['setDate', ['7']], ['setMonth', [1e20]], ['setSeconds', [8.64e15]], ['setTime', [86400000]], ['setTime', [8.64e15 + 1]], ['setTime', ['12']], ['setTime', []], ['setTime', [-0]],
  ['setYear', [99]], ['setYear', [2000]], ['setYear', [-1]], ['setYear', [NaN]], ['setYear', [50.7]], ['setYear', ['3']]];
setters.forEach(function (s) { show(s[0] + '(' + s[1].map(String).join(',') + ')', function () { var d = fresh(); var r = d[s[0]].apply(d, s[1]); return (Object.is(r, -0) ? '-0' : r) + ' ' + (isNaN(d) ? 'Invalid' : d.toISOString()); }); });
show('setters on NaN date', function () { var r = []; ['setMilliseconds', 'setSeconds', 'setMinutes', 'setHours', 'setDate', 'setMonth', 'setUTCHours', 'setUTCDate', 'setUTCMonth', 'setUTCSeconds'].forEach(function (m) { var d = new Date(NaN); r.push(m + '=' + d[m](1)); }); r.push('setFullYear=' + new Date(new Date(NaN).setFullYear(2000)).toISOString()); r.push('setUTCFullYear=' + new Date(new Date(NaN).setUTCFullYear(1990, 5)).toISOString()); r.push('setYear=' + new Date(new Date(NaN).setYear(5)).toISOString()); return r.join(' '); });
show('coercion order and side effects', function () { var log = []; var d = fresh(); var a = { valueOf: function () { log.push('a'); return 1; } }; var b = { valueOf: function () { log.push('b'); d.setTime(NaN); return 2; } }; var r = d.setHours(a, b); return log.join() + ' ' + r + ' ' + d.getTime(); });
show('extra args ignored', function () { var log = []; var d = fresh(); d.setMilliseconds(1, { valueOf: function () { log.push('extra'); return 2; } }); d.setDate(2, { valueOf: function () { log.push('extra2'); return 2; } }); return log.length + ' ' + d.toISOString(); });
show('NaN receiver valueOf side effect', function () { var d = new Date(NaN); var r = d.setMinutes({ valueOf: function () { d.setTime(0); return 5; } }); return r + ' ' + d.getTime(); });
show('setter brand before coercion', function () { var called = false; try { Date.prototype.setHours.call({}, { valueOf: function () { called = true; return 1; } }); } catch (e) { return e.name + ' called=' + called; } });
show('setTime brand', function () { return Date.prototype.setTime.call(Object.create(Date.prototype), 1); });
show('lengths', function () { return ['setMilliseconds', 'setSeconds', 'setMinutes', 'setHours', 'setDate', 'setMonth', 'setFullYear', 'setUTCHours', 'setUTCFullYear', 'setYear', 'setTime'].map(function (m) { return Date.prototype[m].length; }).join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("date_setters_overflow_and_nan")
    assert (r.returncode, r.stderr) == (0, b"")


def test_date_parse_and_utc(js, golden):
    """CATCHES: Date.parse that rejects valid ISO forms (reduced precision, fractions beyond ms,
    offsets, signed extended years) or accepts invalid ones (-000000, out-of-range clip, bad
    separators), cannot read its own toString/toUTCString output or RFC 2822-style dates, and a
    Date.UTC with wrong defaults, coercion order or TimeClip."""
    code = r"""
var inputs = ['2020', '2020-06', '2020-06-15', '2020-06-15T10:20', '2020-06-15T10:20:30', '2020-06-15T10:20:30.5', '2020-06-15T10:20:30.123456', '2020-06-15T10:20:30Z', '2020-06-15T10:20:30+05:30', '2020-06-15T10:20:30.000-08:00', '2020-06-15T00:00:00.000+14:00',
  '+002020-06-15T00:00:00Z', '-000001-01-01T00:00:00Z', '-000000-01-01T00:00:00Z', '+275760-09-13T00:00:00.000Z', '+275760-09-13T00:00:00.001Z', '-271821-04-20T00:00:00.000Z', '-271821-04-19T23:59:59.999Z', '2020-06-15T10', '2020-6-5', '2020-06-15 10:20:30', '2020-06-15T', '20200615', '2020-06-15T10:20:30.Z', ' 2020-06-15 ', '2020-06-15T10:20:30.x', '02020-01-01', '2020-06-15T10:20:30+5:30', '2020-06-15T10:20:30Z+01:00', '2020-06-15T1:20', '2020-06-15 10:20+05', '2020-06-15 10:20:30+0530', '2020-06-15T10:20:30-0800', '2020-06-15T10:20+5', '99999999999999999999-01-01 00:00', '2020-123-01 10:00', '2020-06-1x', '2020-06-15T10:20:3x', '2020-06-15T10:2x',
  'Thu, 01 Jan 1970 00:00:00 GMT', 'Mon, 15 Jun 2020 10:20:30 GMT+0200', 'Wed Jul 28 1993 14:39:07 GMT-0600 (CST)', 'Tue Feb 29 2000', 'June 15, 2020', '15 June 2020 10:20', 'Dec 25, 1995 13:30', '1 January 2000', 'not a date', '', 'Thu Jan 01 1970 00:00:00 GMT+0000 (Coordinated Universal Time)', 'Thu, 01 Jan 12345 00:00:00 GMT', 'Fri Jul 04 2025 05:06:07 GMT-0130', 'Sun, 31 Dec 1899 23:59:59 GMT'];
inputs.forEach(function (s) { var v = Date.parse(s); console.log(JSON.stringify(s).padEnd(50) + ' ' + v + (isNaN(v) ? '' : ' ' + new Date(v).toISOString())); });
console.log(new Date('2020-06-15T10:20:30Z').getTime(), Date.parse({ toString: function () { return '1970-01-01T00:00:01Z'; } }), Date.parse(), Date.parse(0), Date.parse(null));
var d = new Date(Date.UTC(2001, 2, 3, 4, 5, 6));
console.log(Date.parse(d.toString()), Date.parse(d.toUTCString()), Date.parse(d.toISOString()), Date.parse(new Date(Date.UTC(-5, 2, 3)).toISOString()), Date.parse(d.toDateString()));
console.log([Date.UTC(), Date.UTC(2020), Date.UTC(2020, 1), Date.UTC(2020, 1, 29, 12, 30, 15, 250), Date.UTC(2020, 0, 1, 0, 0, 0, 0.9), Date.UTC(NaN), Date.UTC(2020, Infinity), Date.UTC(275760, 8, 13, 0, 0, 0, 1), Date.UTC(1e10), Date.UTC(-271821, 3, 20), Date.UTC(2020, 0, 1, 0, 0, 0, -1), Date.UTC(5), Date.UTC(99, 11, 31), Date.UTC(-0.5)].join(' '));
var log = []; Date.UTC({ valueOf: function () { log.push('y'); return 2000; } }, { valueOf: function () { log.push('m'); return NaN; } }, { valueOf: function () { log.push('d'); return 1; } });
console.log(log.join(), Date.UTC.length, Date.parse.length, Date.length);
"""
    r = js(code)
    assert out(r) == golden("date_parse_and_utc")
    assert (r.returncode, r.stderr) == (0, b"")


def test_date_to_json_to_primitive_and_brand_checks(js, golden):
    """CATCHES: a Date.prototype.toJSON that is not generic (must use ToPrimitive number then call
    toISOString), a @@toPrimitive with wrong hint handling/attributes, `+`/`-`/template coercion of
    Dates, or Date methods that accept non-Date receivers."""
    code = SHOW + r"""
show('toJSON generic', function () { return [Date.prototype.toJSON.call({ toISOString: function () { return 'iso!'; } }), JSON.stringify(Date.prototype.toJSON.call({ valueOf: function () { return Infinity; }, toISOString: function () { return 'never'; } })), JSON.stringify(Date.prototype.toJSON.call({ valueOf: function () { return NaN; } })), Date.prototype.toJSON.call({ valueOf: function () { return 'str'; }, toISOString: function (a) { return 'called ' + arguments.length; } })].join(' '); });
show('toJSON errors', function () { return tries([function () { return Date.prototype.toJSON.call({ toISOString: 1 }); }, function () { return Date.prototype.toJSON.call(null); }, function () { return Date.prototype.toJSON.call(new Date(NaN)); }, function () { return new Date(0).toJSON('ignored'); }]); });
show('toPrimitive', function () { var d = new Date(Date.UTC(2000, 0, 1)); var p = d[Symbol.toPrimitive]; return [p.call(d, 'number'), p.call(d, 'string'), p.call(d, 'default'), d - 0, d + 1, `${d}` === d.toString(), d < new Date(Date.UTC(2001, 0)), typeof (d * 1), d == d.toString(), [d] + ''].join(' | '); });
show('toPrimitive errors', function () { var d = new Date(0); var p = d[Symbol.toPrimitive]; var r = tries([function () { return p.call(d, 'nope'); }, function () { return p.call(d); }, function () { return p.call(d, 1); }, function () { return p.call(1, 'number'); }, function () { return p.call({ valueOf: function () { return {}; }, toString: function () { return {}; } }, 'number'); }, function () { return p.call({ toString: function () { return 's'; } }, 'default'); }, function () { return p.call({ valueOf: function () { return 9; }, toString: 5 }, 'string'); }]); var desc = Object.getOwnPropertyDescriptor(Date.prototype, Symbol.toPrimitive); return r + ' | ' + desc.writable + '/' + desc.enumerable + '/' + desc.configurable + '/' + p.name + '/' + p.length; });
show('overridden valueOf/toString', function () { var d = new Date(1000); d.valueOf = function () { return 5; }; d.toString = function () { return 'S'; }; return [d + 1, d * 2, `${d}`, String(d), d.getTime(), JSON.stringify(d)].join(' '); });
show('brand checks', function () { var r = []; ['getTime', 'getFullYear', 'getUTCDay', 'setDate', 'setUTCMinutes', 'toISOString', 'toString', 'valueOf', 'getTimezoneOffset', 'setTime', 'toLocaleString', 'toLocaleDateString', 'toLocaleTimeString', 'toUTCString', 'toDateString', 'toTimeString', 'setYear'].forEach(function (m) { try { Date.prototype[m].call({}); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.name); } }); try { Date.prototype.getTime.call(Date.prototype); } catch (e) { r.push('proto:' + e.message); } return r.join(' '); });
show('statics', function () { return [Date.length, Date.prototype.toJSON.length, Object.prototype.toString.call(new Date(0)), Date.prototype.constructor === Date, typeof Date.prototype.toTemporalInstant, new Date(1500).toTemporalInstant().toString()].join(); });
show('subclass', function () { class D extends Date { get y() { return this.getUTCFullYear(); } } var d = new D(Date.UTC(2010, 0)); return d.y + ' ' + (d instanceof Date) + ' ' + d.toISOString() + ' ' + (Object.getPrototypeOf(new D(0)) === D.prototype); });
show('date in JSON.stringify replacer', function () { return JSON.stringify({ when: new Date(Date.UTC(2020, 0, 2)) }, function (k, v) { return k === 'when' ? typeof v + ':' + v : v; }); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("date_to_json_to_primitive_and_brand_checks")
    assert (r.returncode, r.stderr) == (0, b"")


def test_promise_combinator_error_paths(js, golden):
    """CATCHES: Promise.all/allSettled/any/race that throw synchronously instead of rejecting when
    the iterator, next(), a custom resolve, or a result's then getter/call throws, that skip
    IteratorClose after a then failure, or that mishandle non-iterables, empty inputs and thenables."""
    code = r"""
var out = [];
function settle(label, p) { return Promise.resolve(p).then(function (v) { out.push(label + ': fulfilled ' + JSON.stringify(v)); }, function (e) { out.push(label + ': rejected ' + (e && e.name ? e.name + ': ' + e.message + (e.errors ? ' errors=' + JSON.stringify(e.errors.map(String)) : '') : JSON.stringify(e))); }); }
function throwingIter(where) {
  return { [Symbol.iterator]: function () { if (where === 'iter') throw new TypeError('no iterator'); return this; }, next: function () { if (where === 'next') throw new RangeError('next threw'); if (this.n++ > 0) return { done: true }; return { value: where === 'then' ? { get then() { throw new SyntaxError('then getter'); } } : where === 'thencall' ? { then: function () { throw new EvalError('then call'); } } : 1, done: false }; }, return: function () { closed.push(where); return {}; }, n: 0 };
}
var closed = [];
var jobs = [];
['all', 'allSettled', 'any', 'race'].forEach(function (c) {
  ['iter', 'next', 'then', 'thencall'].forEach(function (w) { jobs.push(settle(c + '/' + w, Promise[c](throwingIter(w)))); });
  function Bad(ex) { return new Promise(ex); }
  Bad.resolve = function () { throw new URIError('resolve threw'); };
  jobs.push(settle(c + '/resolve-throws', Promise[c].call(Bad, [1])));
  function NotCallable(ex) { return new Promise(ex); }
  NotCallable.resolve = 1;
  jobs.push(settle(c + '/resolve-not-callable', Promise[c].call(NotCallable, [1])));
  jobs.push(settle(c + '/non-iterable', Promise[c](7)));
  if (c !== 'race') jobs.push(settle(c + '/empty', Promise[c]([])));
  var closes = [];
  function C(ex) { return new Promise(ex); }
  C.resolve = function (v) { return v === 'getter' ? { get then() { throw new SyntaxError(c + ' then getter'); } } : { then: function () { throw new EvalError(c + ' then call'); } }; };
  function it(v) { return { [Symbol.iterator]: function () { var done = false; return { next: function () { if (done) return { done: true }; done = true; return { value: v, done: false }; }, return: function () { closes.push(v); return {}; } }; } }; }
  jobs.push(settle(c + '/custom then getter', Promise[c].call(C, it('getter'))));
  jobs.push(settle(c + '/custom then call', Promise[c].call(C, it('call'))));
  out.push(c + ' closes ' + closes.join());
  try { Promise[c].call(1, []); } catch (e) { out.push(c + '/non-ctor this: ' + e.name + ': ' + e.message); }
  try { Promise[c].call(function () {}, []); } catch (e) { out.push(c + '/bad executor: ' + e.name + ': ' + e.message); }
});
jobs.push(settle('allSettled mix', Promise.allSettled([1, Promise.reject(2), { then: function (r) { r(3); } }])));
jobs.push(settle('any mixed', Promise.any([Promise.reject(1), { then: function (a, b) { b(2); } }, Promise.resolve(3)])));
jobs.push(settle('race thenable vs resolved', Promise.race([{ then: function (a, b) { b('rej-thenable'); } }, Promise.resolve('later')])));
jobs.push(settle('all order', Promise.all([new Promise(function (r) { setTimeout(r, 2, 'slow'); }), 'fast', Promise.resolve('mid')])));
jobs.push(settle('any errors order', Promise.any([new Promise(function (a, r) { setTimeout(r, 2, 'slow'); }), Promise.reject('fast')])));
Promise.all(jobs).then(function () { out.push('generic closed: ' + closed.join()); console.log(out.sort().join('\n')); });
"""
    r = js(code)
    assert out(r) == golden("promise_combinator_error_paths")
    assert (r.returncode, r.stderr) == (0, b"")


def test_promise_constructor_and_statics_validation(js, golden):
    """CATCHES: Promise constructor/then/finally/catch/resolve/reject/withResolvers/try that skip
    receiver validation, let an executor throw after resolve override the result, use the wrong
    prototype for a custom newTarget, or pass the wrong callbacks through generic finally/catch."""
    code = SHOW + r"""
show('no new', function () { return Promise(function () {}); });
show('bad executor', function () { return new Promise(5); });
show('then on non-promise', function () { return Promise.prototype.then.call({}, function () {}); });
show('finally on primitive', function () { return Promise.prototype.finally.call(1); });
show('finally then not callable', function () { return Promise.prototype.finally.call({ then: 5 }); });
show('finally non-callable passes', function () { var seen; var r = Promise.prototype.finally.call({ then: function (a, b) { seen = [a, b]; return 'then-result'; } }, 7); return r + ' ' + seen.join(); });
show('finally callable wraps', function () { var seen; Promise.prototype.finally.call({ then: function (a, b) { seen = [typeof a, typeof b, a.length, b.length]; } }, function () {}); return seen.join(); });
show('statics on non-object', function () { var r = []; ['resolve', 'reject', 'withResolvers', 'try', 'all', 'race', 'any', 'allSettled'].forEach(function (m) { try { Promise[m].call(5, 1); } catch (e) { r.push(m + ':' + e.message); } }); return r.join(' | '); });
show('catch generic', function () { var seen; var r = Promise.prototype.catch.call({ then: function (a, b) { seen = typeof a + '/' + typeof b; return 'ok'; } }, function () {}); return r + ' ' + seen; });
show('new.target proto', function () { function F() {} F.prototype = Object.create(Promise.prototype, { tag: { value: 'F' } }); var p = Reflect.construct(Promise, [function (r) { r(1); }], F); return p.tag + ' ' + (p instanceof F); });
show('new.target bad proto', function () { function F() {} F.prototype = 3; var p = Reflect.construct(Promise, [function () {}], F); return Object.getPrototypeOf(p) === Promise.prototype; });
show('withResolvers subclass', function () { class P extends Promise {} var w = P.withResolvers(); return (w.promise instanceof P) + ' ' + typeof w.resolve + ' ' + Object.keys(w).join(); });
show('species misuse', function () { var p = Promise.resolve(1); p.constructor = { [Symbol.species]: 5 }; return p.then(); });
var jobs = [];
function settle(label, p) { jobs.push(p.then(function (v) { out.push(label + ': fulfilled ' + JSON.stringify(v)); }, function (e) { out.push(label + ': rejected ' + (e && e.name ? e.name + ': ' + e.message : JSON.stringify(e))); })); }
settle('executor throws after resolve', new Promise(function (res) { res('first'); throw new Error('ignored'); }));
settle('executor throws', new Promise(function () { throw new TypeError('exec threw'); }));
settle('executor rejects twice', new Promise(function (res, rej) { rej('one'); rej('two'); res('three'); }));
settle('reject via capability', Promise.reject.call(function (ex) { return new Promise(ex); }, 'custom-reject'));
settle('resolve thenable getter throws', Promise.resolve({ get then() { throw new RangeError('getter'); } }));
settle('resolve with self-thenable chain', Promise.resolve({ then: function (r) { r({ then: function (r2) { r2('nested'); } }); } }));
settle('try with args', Promise.try(function () { return Array.prototype.join.call(arguments, '+'); }, 1, 2, 3));
settle('try non-callable', Promise.try(5));
settle('try returns rejected', Promise.try(function () { return Promise.reject('inner'); }));
settle('resolve returns same promise', (function () { var p = Promise.resolve(9); return Promise.resolve(p) === p ? p.then(function (v) { return 'same ' + v; }) : Promise.resolve('different'); })());
settle('then returns itself', (function () { var p = Promise.resolve(1).then(function () { return p; }); return p; })());
settle('finally return value ignored', Promise.resolve('kept').finally(function () { return Promise.resolve('dropped'); }));
settle('finally rejection wins', Promise.resolve('kept').finally(function () { return Promise.reject('finally-rejected'); }));
Promise.all(jobs).then(function () { console.log(out.sort().join('\n')); });
"""
    r = js(code)
    assert out(r) == golden("promise_constructor_and_statics_validation")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unhandled_rejection_reporting(js):
    """CATCHES: an event loop that silently drops unhandled promise rejections, reports handled
    ones, prints them on stdout instead of stderr, formats the reason differently, or changes the
    exit status (the reference reports `Uncaught (in promise) <reason>` and exits 0)."""
    r = js("console.log('start');\nPromise.reject(new RangeError('lost'));\nconsole.log('end');\n")
    assert (r.returncode, out(r), err(r)) == (0, "start\nend\n", "Uncaught (in promise) RangeError: lost\n")
    r = js("Promise.reject(42);\nsetTimeout(function () { console.log('timer ran'); }, 0);\n")
    assert (r.returncode, out(r), err(r)) == (0, "timer ran\n", "Uncaught (in promise) 42\n")
    r = js("var p = Promise.reject(1); p.then(function () {});\nPromise.reject('handled').catch(function (e) { console.log('caught', e); });\n")
    assert (r.returncode, out(r), err(r)) == (0, "caught handled\n", "Uncaught (in promise) 1\n")
    r = js("async function f() { throw new TypeError('in async'); }\nf();\nPromise.reject(undefined);\nPromise.reject({ a: 1 });\nconsole.log('sync done');\n")
    assert (r.returncode, out(r), err(r)) == (
        0,
        "sync done\n",
        "Uncaught (in promise) TypeError: in async\nUncaught (in promise) undefined\nUncaught (in promise) [object Object]\n",
    )


@pytest.mark.parametrize("tier", TIERS)
def test_promise_job_ordering(js, golden, tier):
    """CATCHES: a microtask queue with the wrong interleaving of reaction jobs, thenable resolution
    jobs (an extra tick per thenable/native-promise resolution), await continuations,
    queueMicrotask callbacks and finally handlers, in any execution tier."""
    code = r"""
var log = [];
var p = Promise.resolve();
p.then(function () { log.push('a1'); }).then(function () { log.push('a2'); }).then(function () { log.push('a3'); }).then(function () { log.push('a4'); });
new Promise(function (r) { r({ then: function (f) { log.push('thenable.then'); f('t'); } }); }).then(function (v) { log.push('thenable resolved ' + v); });
new Promise(function (r) { r(Promise.resolve('inner')); }).then(function (v) { log.push('promise-resolved ' + v); });
(async function () { log.push('async start'); await null; log.push('after await 1'); await Promise.resolve(); log.push('after await 2'); return 'ret'; })().then(function (v) { log.push('async ' + v); });
queueMicrotask(function () { log.push('microtask'); });
Promise.reject('r').catch(function (e) { log.push('catch ' + e); }).finally(function () { log.push('finally'); });
Promise.all([1, Promise.resolve(2)]).then(function (v) { log.push('all ' + v); });
Promise.race([Promise.resolve('race-a'), 'race-b']).then(function (v) { log.push('race ' + v); });
log.push('sync end');
setTimeout(function () { log.push('timeout'); console.log(log.join('\n')); }, 0);
"""
    r = js(code, *tier)
    assert out(r) == golden("promise_job_ordering")
    assert (r.returncode, r.stderr) == (0, b"")


def test_disposable_stack_and_using(js, golden):
    """CATCHES: DisposableStack use/adopt/defer/dispose/move that run disposers in the wrong (non-
    LIFO) order or with wrong this/arguments, do not chain multiple errors as nested
    SuppressedErrors, allow use after disposal, or `using` declarations that skip disposal."""
    code = SHOW + r"""
function desc(e) { if (e && e.name === 'SuppressedError') return 'Suppressed(' + desc(e.error) + ' over ' + desc(e.suppressed) + ')'; return e && e.message !== undefined ? e.name + ':' + e.message : String(e); }
show('order', function () { var log = []; var s = new DisposableStack(); var res = { [Symbol.dispose]: function () { log.push('use ' + (this === res) + ' ' + arguments.length); } }; var r1 = s.use(res); var r2 = s.adopt('val', function (v) { log.push('adopt ' + v + ' ' + (this === undefined)); }); var r3 = s.defer(function () { log.push('defer ' + arguments.length); }); s.use(null); s.use(undefined); var d1 = s.disposed; var r4 = s.dispose(); var r5 = s.dispose(); return [r1 === res, r2, r3, d1, s.disposed, r4, r5].join() + ' ' + log.join(' > '); });
show('errors suppressed', function () { var s = new DisposableStack(); s.defer(function () { throw new Error('first'); }); s.defer(function () { throw new TypeError('second'); }); s.defer(function () { throw new RangeError('third'); }); try { s.dispose(); } catch (e) { return desc(e) + ' msg=' + JSON.stringify(e.message) + ' ' + (e instanceof Error) + ' disposed=' + s.disposed; } });
show('single error', function () { var s = new DisposableStack(); s.defer(function () { throw 'plain'; }); s.defer(function () {}); try { s.dispose(); } catch (e) { return typeof e + ' ' + e; } });
show('after dispose', function () { var s = new DisposableStack(); s.dispose(); var r = []; ['use', 'adopt', 'defer', 'move'].forEach(function (m) { try { s[m]({ [Symbol.dispose]: function () {} }, function () {}); } catch (e) { r.push(m + ':' + e.name + ':' + e.message); } }); return r.join(' | '); });
show('validation', function () { var s = new DisposableStack(); return tries([function () { s.use({}); }, function () { s.use(5); }, function () { s.adopt(1, 2); }, function () { s.defer('x'); }, function () { DisposableStack(); }, function () { DisposableStack.prototype.dispose.call({}); }, function () { DisposableStack.prototype.use.call(new AsyncDisposableStack(), null); }, function () { Object.getOwnPropertyDescriptor(DisposableStack.prototype, 'disposed').get.call({}); }, function () { s.use({ [Symbol.dispose]: 1 }); }]); });
show('move', function () { var log = []; var s = new DisposableStack(); s.defer(function () { log.push('moved ran'); }); var m = s.move(); var a = [s.disposed, m.disposed, m instanceof DisposableStack]; s.dispose(); a.push(log.length); m.dispose(); a.push(log.join()); return a.join(); });
show('symbol alias', function () { return [DisposableStack.prototype[Symbol.dispose] === DisposableStack.prototype.dispose, AsyncDisposableStack.prototype[Symbol.asyncDispose] === AsyncDisposableStack.prototype.disposeAsync, Object.prototype.toString.call(new DisposableStack()), Object.prototype.toString.call(new AsyncDisposableStack())].join(); });
show('SuppressedError ctor', function () { var e = new SuppressedError(1, 2, 'msg'); var f = SuppressedError('a', 'b'); return [e.error, e.suppressed, e.message, e.name, f instanceof SuppressedError, 'message' in f, Object.prototype.hasOwnProperty.call(f, 'message'), SuppressedError.length, Object.getPrototypeOf(SuppressedError) === Error].join(); });
show('using declaration', function () { var log = []; { using a = { [Symbol.dispose]: function () { log.push('a'); } }; using b = { [Symbol.dispose]: function () { log.push('b'); } }; log.push('body'); } return log.join(); });
show('using with throw', function () { try { using a = { [Symbol.dispose]: function () { throw new Error('dispose'); } }; throw new Error('body'); } catch (e) { return desc(e); } });
show('using null', function () { var log = []; { using a = null; log.push('ok'); } return log.join(); });
show('using non-disposable', function () { { using a = {}; } });
show('using in loop', function () { var log = []; for (using x of [{ [Symbol.dispose]: function () { log.push('x1'); } }, { [Symbol.dispose]: function () { log.push('x2'); } }]) { log.push('iter'); } return log.join(); });
show('using stack', function () { var log = []; { using s = new DisposableStack(); s.defer(function () { log.push('stack disposed'); }); log.push('in block'); } return log.join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("disposable_stack_and_using")
    assert (r.returncode, r.stderr) == (0, b"")


def test_async_disposable_stack(js, golden):
    """CATCHES: AsyncDisposableStack.disposeAsync that does not await each disposer in LIFO order,
    calls disposers before earlier awaits settle, loses the sync @@dispose fallback, throws instead
    of rejecting for a bad receiver, or folds rejections into the wrong SuppressedError chain."""
    code = r"""
function desc(e) { if (e && e.name === 'SuppressedError') return 'Suppressed(' + desc(e.error) + ' over ' + desc(e.suppressed) + ')'; return e && e.message !== undefined ? e.name + ':' + e.message : String(e); }
var aout = [];
var as = new AsyncDisposableStack();
as.use({ [Symbol.asyncDispose]: function () { aout.push('async use'); return new Promise(function (r) { setTimeout(function () { aout.push('async use settled'); r(); }, 1); }); } });
as.use({ [Symbol.dispose]: function () { aout.push('sync fallback ' + arguments.length); return 'ignored'; } });
as.use(null);
as.adopt(7, function (v) { aout.push('adopt ' + v); return Promise.reject(new Error('adopt fail')); });
as.defer(function () { aout.push('defer'); throw new TypeError('defer threw'); });
var p = as.disposeAsync();
aout.push('disposeAsync returned ' + Object.prototype.toString.call(p) + ' disposed=' + as.disposed);
p.then(function () { aout.push('resolved?'); }, function (e) { aout.push('rejected ' + desc(e)); }).then(function () {
  return AsyncDisposableStack.prototype.disposeAsync.call({}).catch(function (e) { aout.push('brand ' + e.name + ':' + e.message); });
}).then(function () { return as.disposeAsync().then(function (v) { aout.push('second dispose ' + v); }); }).then(function () {
  var s2 = new AsyncDisposableStack(); var r = []; [function () { s2.use(1); }, function () { s2.use({}); }, function () { s2.adopt(1, 1); }, function () { s2.defer(1); }, function () { AsyncDisposableStack(); }, function () { AsyncDisposableStack.prototype.use.call(new DisposableStack(), null); }, function () { Object.getOwnPropertyDescriptor(AsyncDisposableStack.prototype, 'disposed').get.call({}); }].forEach(function (f) { try { f(); r.push('ok'); } catch (e) { r.push(e.name + ':' + e.message); } });
  var m = s2.move(); r.push(s2.disposed, m.disposed, Object.getPrototypeOf(m) === AsyncDisposableStack.prototype); s2.disposeAsync(); ['use', 'adopt', 'defer', 'move'].forEach(function (k) { try { s2[k](null, function () {}); } catch (e) { r.push(k + ':' + e.name); } });
  aout.push('async validation ' + r.join(' | '));
  var s3 = new AsyncDisposableStack(); s3.use({ [Symbol.asyncDispose]: function () { return 5; } }); s3.defer(function () { return { then: function (f) { aout.push('thenable awaited'); f(); } }; });
  var poison = { then: 1 }; Object.defineProperty(poison, 'then', { get: function () { throw new RangeError('then getter'); } });
  var badCtor = Promise.resolve(); Object.defineProperty(badCtor, 'constructor', { get: function () { throw new URIError('ctor getter'); } });
  var s4 = new AsyncDisposableStack(); s4.defer(function () { return badCtor; }); s4.defer(function () { return poison; }); s4.defer(function () { throw new EvalError('sync throw'); });
  return Promise.all([s3.disposeAsync().then(function (v) { aout.push('s3 done ' + v); }), s4.disposeAsync().then(null, function (e) { aout.push('s4 rejected ' + desc(e)); })]);
}).then(function () {
  var order = []; var s5 = new AsyncDisposableStack();
  s5.defer(function () { order.push('d1'); }); s5.defer(function () { order.push('d2'); return Promise.resolve(); });
  var done = s5.disposeAsync(); order.push('sync after call');
  Promise.resolve().then(function () { order.push('tick1'); }).then(function () { order.push('tick2'); });
  return done.then(function () { order.push('done'); aout.push('interleave ' + order.join(',')); });
}).then(function () { console.log(aout.join('\n')); });
"""
    r = js(code)
    assert out(r) == golden("async_disposable_stack")
    assert (r.returncode, r.stderr) == (0, b"")


def test_weakref_and_finalization_registry(js, golden):
    """CATCHES: WeakRef/FinalizationRegistry that accept primitives or registered symbols as targets
    or tokens, allow target === held value, miss brand checks or the `new` requirement, or return
    the wrong boolean from unregister (true only when a live registration used that token)."""
    code = SHOW + r"""
show('WeakRef', function () { var o = { v: 1 }; var w = new WeakRef(o); var s = Symbol('local'); var ws = new WeakRef(s); return [w.deref() === o, ws.deref() === s, Object.prototype.toString.call(w), WeakRef.prototype.constructor === WeakRef, typeof WeakRef.prototype.deref, new WeakRef(Symbol.iterator).deref() === Symbol.iterator, new WeakRef(function () {}).deref().length].join(); });
show('WeakRef errors', function () { return tries([function () { return WeakRef({}); }, function () { return new WeakRef(1); }, function () { return new WeakRef(Symbol.for('reg')); }, function () { return WeakRef.prototype.deref.call({}); }, function () { return new WeakRef(); }, function () { return WeakRef.prototype.deref.call(new FinalizationRegistry(function () {})); }]); });
show('WeakRef subclass', function () { class W extends WeakRef { get x() { return this.deref().x; } } return new W({ x: 5 }).x; });
show('FinalizationRegistry', function () { var calls = 0; var fr = new FinalizationRegistry(function () { calls++; }); var target = {}, token = {}, tok2 = Symbol('t'); var r = [fr.register(target, 'held'), fr.register(target, 'held2', token), fr.register({}, 1, token), fr.register(Symbol('x'), 2, tok2), fr.unregister(token), fr.unregister(token), fr.unregister(tok2), fr.unregister({}), fr.unregister(target), calls, Object.prototype.toString.call(fr)]; return r.join(); });
show('FinalizationRegistry errors', function () { var fr = new FinalizationRegistry(function () {}); var t = {}; return tries([function () { FinalizationRegistry(function () {}); }, function () { new FinalizationRegistry(); }, function () { new FinalizationRegistry({}); }, function () { fr.register(1, 2); }, function () { fr.register(t, t); }, function () { fr.register(t, 1, 5); }, function () { fr.register(Symbol.for('r'), 1); }, function () { fr.unregister(1); }, function () { fr.unregister(Symbol.for('r')); }, function () { FinalizationRegistry.prototype.register.call({}, {}); }, function () { FinalizationRegistry.prototype.unregister.call({}, {}); }, function () { return fr.register(t, 1, undefined); }, function () { return fr.register(t, undefined); }]); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("weakref_and_finalization_registry")
    assert (r.returncode, r.stderr) == (0, b"")


def test_shadow_realm_evaluate_and_import_value(js, golden, workdir):
    """CATCHES: a ShadowRealm that shares globals with the caller, lets objects cross the boundary,
    keeps `let` bindings between evaluations, does not wrap callables in both directions, reports
    inner errors as anything but a TypeError, or an importValue that resolves missing exports."""
    (workdir / "mod.mjs").write_text("export const value = 42;\nexport function fn(n) { return n * 7; }\nexport const obj = {};\nexport let maybe = undefined;\n")
    (workdir / "bad.mjs").write_text("throw new Error('boom');\nexport const x = 1;\n")
    code = SHOW + r"""
var sr = new ShadowRealm();
show('primitives', function () { return [sr.evaluate('1 + 1'), sr.evaluate('"s" + "t"'), sr.evaluate('undefined'), sr.evaluate('null'), typeof sr.evaluate('Symbol("q")'), sr.evaluate('10n ** 20n'), sr.evaluate('var x = 5; x'), sr.evaluate('x * 2'), sr.evaluate('let y = 1; y'), sr.evaluate('typeof y'), sr.evaluate('globalThis.z = 3; z'), sr.evaluate(''), sr.evaluate('if (true) { 8 }')].map(String).join(','); });
show('isolation', function () { globalThis.outer = 1; return sr.evaluate('typeof outer') + ' ' + sr.evaluate('Array === undefined') + ' ' + (sr.evaluate('Object') === undefined) + ' ' + new ShadowRealm().evaluate('typeof x'); });
show('wrapped function', function () { var f = sr.evaluate('(function add(a, b) { return a + b + (this === undefined ? "" : "!"); })'); var g = sr.evaluate('(function () { return {}; })'); var h = sr.evaluate('(function (cb) { return cb(2) * 10; })'); var r = [typeof f, f(1, 2), f.call({}, 'a', 'b'), h(function (n) { return n + 1; })]; try { g(); } catch (e) { r.push(e.name); } try { f({}); } catch (e) { r.push('arg:' + e.name); } return r.join(); });
show('wrapped function throws', function () { var f = sr.evaluate('(function () { throw new Error("inside"); })'); try { f(); } catch (e) { return e.name + ' ' + (e instanceof TypeError); } });
show('errors', function () { return tries([function () { return sr.evaluate('({})'); }, function () { return sr.evaluate('throw new RangeError("x")'); }, function () { return sr.evaluate('var = ;'); }, function () { return sr.evaluate(5); }, function () { return ShadowRealm.prototype.evaluate.call({}, '1'); }, function () { return ShadowRealm(); }, function () { return sr.evaluate('[]'); }]); });
show('strict', function () { return sr.evaluate('"use strict"; (function () { return this; })()') + ' ' + sr.evaluate('(function () { return typeof this; })()'); });
show('promise inside', function () { return sr.evaluate('var done; Promise.resolve(4).then(function (v) { done = v; }); 0') + ' ' + sr.evaluate('done'); });
show('tag', function () { return Object.prototype.toString.call(sr) + ' ' + typeof ShadowRealm.prototype.importValue; });
show('importValue sync errors', function () { return tries([function () { return ShadowRealm.prototype.importValue.call({}, './m.mjs', 'x'); }, function () { return sr.importValue('./m.mjs', 1); }]); });
var jobs = [
  sr.importValue('./mod.mjs', 'value').then(function (v) { out.push('import value ' + v); }),
  sr.importValue('./mod.mjs', 'fn').then(function (f) { out.push('import fn ' + typeof f + ' ' + f(3)); }),
  sr.importValue('./mod.mjs', 'obj').then(function (v) { out.push('obj ' + v); }, function (e) { out.push('import obj ' + e.name); }),
  sr.importValue('./mod.mjs', 'missing').then(null, function (e) { out.push('import missing ' + e.name + ': ' + e.message); }),
  sr.importValue('./nope.mjs', 'x').then(null, function (e) { out.push('import nope ' + e.name + ': ' + e.message); }),
  sr.importValue('./bad.mjs', 'x').then(null, function (e) { out.push('import bad ' + e.name + ': ' + e.message); }),
];
Promise.all(jobs).then(function () { console.log(out.join('\n')); });
"""
    r = js(code)
    assert out(r) == golden("shadow_realm_evaluate_and_import_value")
    assert (r.returncode, r.stderr) == (0, b"")


def test_host_262_helpers(js, golden):
    """CATCHES: broken $262 host hooks used by conformance-style scripts: evalScript running with
    the wrong global semantics, IsHTMLDDA not being falsy/typeof undefined, createRealm sharing
    intrinsics, detachArrayBuffer not detaching, or AbstractModuleSource being constructible."""
    code = r"""
console.log($262.evalScript('var fromScript = 6 * 7; fromScript'), typeof fromScript, $262.evalScript(5), Object.getOwnPropertyDescriptor(globalThis, 'fromScript').configurable);
try { $262.evalScript('let q = 1; let q = 2;'); } catch (e) { console.log('evalScript', e.name); }
try { $262.evalScript('var fromScript2 = 1; throw new URIError("from script")'); } catch (e) { console.log('evalScript threw', e.name, e.message, typeof fromScript2); }
var dda = $262.IsHTMLDDA;
console.log($262.gc(), typeof dda, dda(), dda(''), dda('x'), dda(1, 2), dda === undefined, dda == undefined, dda == null, !dda, dda ? 'truthy' : 'falsy', typeof $262.global, $262.global === globalThis);
var other = $262.createRealm();
console.log(other.evalScript('var r = 1 + 2; r'), other.global.r, other.global.Array === Array, other.evalScript('this') === other.global, typeof other.global.$262);
console.log($262.agent.receiveBroadcast(function () { console.log('never'); }), $262.agent.sleep(0), $262.agent.sleep(-1), $262.agent.report('nobody listens'));
try { $262.agent.setTimeout(5, 1); } catch (e) { console.log(e.name + ': ' + e.message); }
var AMS = $262.AbstractModuleSource;
try { new AMS(); } catch (e) { console.log(e.name + ': ' + e.message); }
try { AMS(); } catch (e) { console.log(e.name); }
console.log(typeof AMS, Object.getOwnPropertyDescriptor(AMS.prototype, Symbol.toStringTag).get.call({}), AMS.prototype.constructor === AMS);
var dd = new ArrayBuffer(4); $262.detachArrayBuffer(dd); console.log(dd.detached, dd.byteLength, $262.detachArrayBuffer(5));
"""
    r = js(code)
    assert out(r) == golden("host_262_helpers")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_bigint_bitwise_shift_and_division(js, golden, tier):
    """CATCHES: BigInt two's-complement bitwise operators on negative or multi-limb values, shifts
    that do not floor (arithmetic right shift of negatives), wrong truncating division/remainder
    signs, or missing RangeErrors/TypeErrors for division by zero, negative exponents and mixing."""
    code = SHOW + r"""
var big = 2n ** 130n + 12345n, neg = -(2n ** 70n) - 3n;
show('bitwise', function () { return [5n & 3n, 5n | 3n, 5n ^ 3n, ~5n, ~-1n, -5n & 3n, -5n | 3n, -5n ^ 3n, -5n & -3n, -5n | -3n, -5n ^ -3n, big & neg, big | neg, big ^ neg, neg & 0xffffn, ~big, ~neg, neg ^ neg, -(2n ** 64n) | 1n, (2n ** 64n - 1n) & -(2n ** 64n)].join(' '); });
show('shifts', function () { return [1n << 100n, big >> 64n, big >> 200n, neg >> 200n, neg >> 3n, -1n >> 1000n, neg << 5n, 5n << -1n, -9n >> 1n, 0n << 1000n, (2n ** 64n - 1n) << 1n, -(2n ** 64n) >> 64n, -(2n ** 64n) - 1n >> 64n, 1n << 64n >> 63n, -3n >> -2n].join(' '); });
show('arith', function () { return [big * neg, big / neg, big % neg, neg % 7n, -7n / 2n, -7n % 2n, 7n % -2n, 3n ** 0n, (-2n) ** 63n, 2n ** 200n / 2n ** 199n, big - big, -neg, (2n ** 64n) * (2n ** 64n) + 1n, (2n ** 128n - 1n) / (2n ** 64n + 1n), 0n ** 0n, (2n ** 64n + 7n) % (2n ** 32n)].join(' '); });
show('errors', function () { return tries([function () { return 1n / 0n; }, function () { return 1n % 0n; }, function () { return 2n ** -1n; }, function () { return 1n + 1; }, function () { return 1n >>> 0n; }, function () { return +1n; }, function () { return BigInt(1.5); }, function () { return BigInt('1.5'); }, function () { return BigInt(Symbol()); }, function () { return new BigInt(1); }, function () { return BigInt(NaN); }, function () { return Math.max(1n); }, function () { return 1n < Symbol(); }]); });
show('increment', function () { var x = 2n ** 64n - 1n; x++; var y = -(2n ** 64n); y--; return x + ' ' + y + ' ' + (-x) + ' ' + (x - x - 1n); });
var acc = 0n; for (var i = 0n; i < 200n; i++) acc = (acc * 31n + (i ^ (i >> 2n)) - (i & 7n)) % (2n ** 61n - 1n);
out.push('hot loop ' + acc);
console.log(out.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("bigint_bitwise_shift_and_division")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bigint_number_interop(js, golden):
    """CATCHES: BigInt/Number comparisons that lose precision above 2^53 or mishandle fractions,
    NaN and infinities, Number(bigint) conversions that do not round to nearest-even, BigInt
    parsing of radix prefixes and whitespace, asIntN/asUintN wrapping, or BigInts as Map/Set keys."""
    code = SHOW + r"""
var big = 2n ** 130n + 12345n, neg = -(2n ** 70n) - 3n;
show('compare with numbers', function () { return [1n < 1.5, 2n > 1.5, 1n == 1, 1n == 1.5, -1n < -0.5, big > 1e39, big < 1e40, big == 2 ** 130, 2n ** 130n == 2 ** 130, 1n < Infinity, -1n > -Infinity, 1n < NaN, 1n >= NaN, 0n == -0, 9007199254740993n > 9007199254740992, 9007199254740993n == 9007199254740992, -(2n ** 1100n) < -1e300, 5n > '4.5', 5n == '5', '0x10' == 16n, 1n < '1n', 2n ** 64n > 2 ** 64, -5n < -4.999, 3n <= 3, [1n, 2] < [1n, 3]].join(' '); });
show('to number', function () { return [Number(big), Number(neg), Number(2n ** 53n + 1n), Number(2n ** 53n + 3n), Number(-(2n ** 64n)), Number(2n ** 1024n), Number(-(2n ** 1030n)), Number(2n ** 1023n * 3n / 2n), Number((2n ** 54n) + 2n), Number(0n), Number(-0n), parseFloat(big), +String(big), Number(2n ** 63n - 1n), Number(-(2n ** 60n) - 1n)].join(' '); });
show('from number', function () { return [BigInt(2 ** 60), BigInt(-(2 ** 80)), BigInt(1e21), BigInt(Number.MAX_SAFE_INTEGER), BigInt(5e-324 * 0), BigInt(2 ** 1023), BigInt(-0), BigInt(true), BigInt(Object(7n))].join(' '); });
show('asIntN/asUintN', function () { return [BigInt.asIntN(8, 255n), BigInt.asIntN(8, 128n), BigInt.asUintN(8, -1n), BigInt.asIntN(64, 2n ** 63n), BigInt.asUintN(64, -1n), BigInt.asIntN(0, 5n), BigInt.asUintN(130, -1n) === 2n ** 130n - 1n, BigInt.asIntN(200, -(2n ** 150n)), BigInt.asUintN(1, 3n), BigInt.asIntN(3, 4n), BigInt.asIntN(65, 2n ** 64n), BigInt.asUintN(64, 2n ** 64n + 1n)].join(' '); });
show('asIntN errors', function () { return tries([function () { return BigInt.asIntN(-1, 1n); }, function () { return BigInt.asUintN(2 ** 53, 1n); }, function () { return BigInt.asIntN(8, 1); }]); });
show('parse strings', function () { return [BigInt('  123  '), BigInt('0x1F'), BigInt('0o17'), BigInt('0b101'), BigInt(''), BigInt('-42'), BigInt('+7'), BigInt('000123'), BigInt('0XfF'), BigInt('\n9\t')].join(' '); });
show('parse errors', function () { var r = []; ['-0x1', '1e3', '12n', '0x', ' - 1', '1_000', '0b2', 'Infinity'].forEach(function (s) { try { r.push(BigInt(s)); } catch (e) { r.push(e.name); } }); return r.join(' '); });
show('toString radix', function () { return [big.toString(16), neg.toString(2).length, (255n).toString(36), (-35n).toString(36), (1234567n).toLocaleString('en-US'), (0n).toString(2), (2n ** 64n).toString(32)].join(' '); });
show('toString radix error', function () { return (1n).toString(37); });
show('as keys', function () { var m = new Map([[1n, 'a'], [big, 'b']]); var s = new Set([1n, 1n, 2n ** 64n, 2n ** 64n, 1, -0n, 0n]); var o = {}; o[big] = 1; return [m.get(1n), m.get(2n ** 130n + 12345n), m.has(1), s.size, Object.keys(o)[0], [1n, 2n ** 64n].includes(2n ** 64n), [0n].indexOf(-0n), Object.is(0n, -0n)].join(' '); });
show('wrappers and JSON', function () { var w = Object(5n); return [typeof 5n, typeof w, w + 1n, w.valueOf() === 5n, BigInt.prototype.valueOf.call(w), Object.prototype.toString.call(w), tries([function () { return JSON.stringify({ a: 1n }); }, function () { return BigInt.prototype.valueOf.call(5); }])].join(' '); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("bigint_number_interop")
    assert (r.returncode, r.stderr) == (0, b"")
