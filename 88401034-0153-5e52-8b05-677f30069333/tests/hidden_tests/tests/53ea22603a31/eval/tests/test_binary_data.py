"""Binary data: ArrayBuffer (resizable, transfer, detach, immutable), SharedArrayBuffer (growable),
every TypedArray kind (element conversion, construction, the %TypedArray% prototype methods,
integer-indexed exotic property behaviour, species), Uint8Array base64/hex helpers, DataView
accessors for every type and endianness, and Atomics."""

import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)

PRE = r'''
const fmt = (v) => typeof v === 'bigint' ? v + 'n' : v === undefined ? 'undefined'
  : Object.is(v, -0) ? '-0' : ArrayBuffer.isView(v) && !(v instanceof DataView) ? v.constructor.name + '[' + Array.from(v, fmt).join(',') + ']'
  : Array.isArray(v) ? '[' + v.map(fmt).join(',') + ']'
  : v instanceof ArrayBuffer ? 'ArrayBuffer(' + v.byteLength + ')'
  : v !== null && typeof v === 'object' ? '{' + Object.keys(v).map(k => k + ':' + fmt(v[k])).join(',') + '}'
  : typeof v === 'string' ? JSON.stringify(v) : String(v);
const err = (f) => { try { return 'ok ' + fmt(f()); } catch (e) { return e.name + ': ' + e.message; } };
'''


def test_element_conversion_all_kinds(run, workdir):
    r"""CATCHES: wrong ToIntN/ToUintN wrapping (modulo 2^n, truncation toward zero), Uint8Clamped
    rounding (round-half-to-even, NaN -> 0, clamping), Float16/Float32 rounding and overflow to
    Infinity, -0 preservation in float arrays, BigInt64/BigUint64 wrapping, and wrong
    BYTES_PER_ELEMENT/length/byteLength."""
    check_script(run, workdir, G, "element_conversion", PRE + r'''
const kinds = [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, Float16Array, Float32Array, Float64Array, BigInt64Array, BigUint64Array];
const nums = [-1, 255.5, 256, -129, 1.5, 2.5, -0.5, 65537, 3e38, NaN, Infinity, -Infinity, 0.1, 1e-8, 65520, 2 ** 31, -0, 0.5, 254.5, '7', true, null];
const bigs = [-1n, 2n ** 63n, 2n ** 64n + 5n, -(2n ** 63n) - 1n, 0n, 12345678901234567890n];
for (const K of kinds) {
  const ta = new K(K.name.startsWith('Big') ? bigs : nums);
  console.log(K.name, K.BYTES_PER_ELEMENT, ta.length, ta.byteLength, Array.from(ta, fmt).join(' '));
}
''')


def test_float16_and_rounding_details(run, workdir):
    r"""CATCHES: Float16Array / DataView float16 / Math.f16round implemented via float32 double
    rounding or without subnormal support (ties-to-even at the half-ulp, largest finite 65504,
    overflow threshold 65520, smallest subnormal 2^-24), and Uint8ClampedArray ties."""
    check_script(run, workdir, G, "float16_rounding", PRE + r'''
const vals = [65504, 65519.99, 65520, 2 ** -24, 2 ** -25, 2 ** -25 + 2 ** -40, 2 ** -14, 1 + 2 ** -11, 1 + 3 * 2 ** -11, 1 / 3, 0.1, -0, 2049, 2051, 1e-10, -65536];
console.log(Array.from(new Float16Array(vals), fmt).join(' '));
console.log(typeof Math.f16round === 'function' ? vals.map(v => fmt(Math.f16round(v))).join(' ') : 'no f16round');
const dv = new DataView(new ArrayBuffer(2));
console.log(vals.map(v => { dv.setFloat16(0, v); return dv.getUint16(0).toString(16).padStart(4, '0'); }).join(' '));
for (const bits of [0x0001, 0x03ff, 0x0400, 0x3c00, 0x7bff, 0x7c00, 0xfc00, 0x7e00, 0x8000, 0x3555]) { dv.setUint16(0, bits); console.log(bits.toString(16), fmt(dv.getFloat16(0))); }
console.log(Array.from(new Uint8ClampedArray([0.5, 1.5, 2.5, 3.5, 254.5, 253.5, -0.4, 255.49, 1e10, -Infinity]), fmt).join(' '));
console.log(Array.from(new Float32Array([16777217, 0.1, 3.4028235e38, 3.4028236e38, 1e-46, 1.4e-45]), fmt).join(' '));
''')


def test_constructors_and_errors(run, workdir):
    r"""CATCHES: TypedArray constructors mishandling lengths, array-likes, iterables, other typed
    arrays (value conversion, not byte copy), buffer/offset/length views, and wrong error types
    or messages for negative lengths, misaligned offsets, out-of-range views, BigInt/Number
    mixing, calling without new, and the abstract %TypedArray% constructor."""
    check_script(run, workdir, G, "constructors", PRE + r'''
console.log(fmt(new Uint8Array(3)), fmt(new Uint8Array()), fmt(new Uint8Array('2')), fmt(new Int8Array([1, '2', 3.7])), fmt(new Int8Array({ length: 2, 0: 5 })));
console.log(fmt(new Uint8Array(new Set([7, 8]))), fmt(new Uint8Array(new Int16Array([-1, 256, 513]))), fmt(new Float64Array(new Uint8Array([1, 2]))), fmt(new Uint16Array([1, 2][Symbol.iterator]())));
const buf = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]).buffer;
const v = new Uint16Array(buf, 2, 2); console.log(fmt(v), v.byteOffset, v.byteLength, v.length, v.buffer === buf, fmt(new Uint32Array(buf, 4)), fmt(new Int8Array(buf, 8)));
console.log(err(() => new Uint8Array(-1)), '|', err(() => Uint8Array(2)), '|', err(() => new Uint16Array(new ArrayBuffer(3))));
console.log(err(() => new Uint16Array(new ArrayBuffer(4), 1)), '|', err(() => new Uint16Array(new ArrayBuffer(4), 6)), '|', err(() => new Uint16Array(new ArrayBuffer(4), 2, 2)));
console.log(err(() => new (Object.getPrototypeOf(Uint8Array))()), '|', err(() => new BigInt64Array([1])), '|', err(() => new Uint8Array([1n])));
console.log(err(() => new BigInt64Array(new Uint8Array(1))), '|', err(() => new Uint8Array(new BigInt64Array(1))), '|', err(() => new Uint8Array({ [Symbol.iterator]: 1 })));
console.log(err(() => new Uint8Array(2 ** 53)), '|', err(() => new Uint8Array(new ArrayBuffer(4), -1)), '|', err(() => new Float64Array(1.5)));
console.log(fmt(new BigInt64Array([5n, -5n])), fmt(new BigUint64Array(new BigInt64Array([-1n]))), fmt(new BigInt64Array({ length: 1, 0: '42' })));
console.log(Int8Array.name, Int8Array.length, Object.getPrototypeOf(Int8Array).name, Int8Array.prototype.BYTES_PER_ELEMENT, Uint8Array.prototype[Symbol.iterator] === Uint8Array.prototype.values);
''')


def test_search_and_access_methods(run, workdir):
    r"""CATCHES: indexOf/lastIndexOf finding NaN (they must not) or includes missing it (it must),
    -0/+0 equality, fromIndex handling, at() with negative/out-of-range indices, and
    find/findLast/findIndex/findLastIndex/some/every callbacks receiving wrong arguments."""
    check_script(run, workdir, G, "search_access", PRE + r'''
const f = new Float64Array([3, NaN, -0, 0, 1, NaN, -Infinity]);
console.log([f.indexOf(NaN), f.lastIndexOf(NaN), f.includes(NaN), f.indexOf(0), f.indexOf(-0), f.lastIndexOf(0), f.includes(-0)].join());
console.log([f.at(-1), f.at(7), f.at(-8), f.at(0.9), f.at('1'), f.at(NaN)].map(fmt).join());
console.log([f.indexOf(3, 1), f.indexOf(1, -3), f.lastIndexOf(3, -8), f.lastIndexOf(0, -5), f.includes(3, 1), f.includes(1, -10), f.indexOf('1'), new Int8Array(0).includes(undefined), new Int8Array(2).includes(undefined)].join());
const seen = []; const r = new Int16Array([5, -7, 9]).findLast((v, i, a) => { seen.push(v + '@' + i + ':' + a.length); return v < 0; });
console.log(r, seen.join(' '), new Int16Array([5, -7, 9]).findIndex(v => v > 6), new Int16Array([5, -7]).findLastIndex(v => v > 99), new Int16Array([5]).find(v => v > 99));
console.log(new Uint8Array([1, 2]).some(function (v) { return v === this.k; }, { k: 2 }), new Uint8Array([]).every(() => false), new Uint8Array([3, 4]).every(v => v > 2));
console.log(fmt([...new Float32Array([1.5, -2]).entries()]), fmt([...new Float32Array([1.5, -2]).keys()]), fmt([...new BigInt64Array([1n, -2n])]));
''')


def test_sort_reverse_with(run, workdir):
    r"""CATCHES: default TypedArray sort comparing as strings (it is numeric, -0 before +0, NaN
    last), comparators returning NaN or non-numbers, toSorted/toReversed/with mutating the
    receiver or ignoring the element type, with() index validation (RangeError) and value
    coercion order, and sort's comparefn type check."""
    check_script(run, workdir, G, "sort_reverse_with", PRE + r'''
console.log(fmt(new Float64Array([3, NaN, -0, 0, 1, -Infinity, NaN, 10]).sort()));
console.log(fmt(new Float64Array([3, NaN, -0, 0, 1]).sort((a, b) => b - a)), fmt(new Int8Array([3, 1, 2]).sort(() => NaN)), fmt(new Int8Array([3, 1, 2]).sort((a, b) => ({ valueOf() { return a - b; } }))));
console.log(fmt(new Int8Array([5, -3, 10, -128, 127]).sort()), fmt(new Uint32Array([10, 9, 4294967295, 1]).sort()), fmt(new BigInt64Array([3n, -5n, 0n]).sort()), fmt(new BigUint64Array([2n ** 64n - 1n, 0n]).sort()));
const stable = new Uint8Array([21, 12, 22, 11, 23]).sort((a, b) => (a % 10) - (b % 10)); console.log(fmt(stable));
const orig = new Int16Array([3, 1, 2]);
console.log(fmt(orig.toSorted()), fmt(orig.toReversed()), fmt(orig.with(-1, 70000)), fmt(orig.with(0, '9')), fmt(orig), fmt(orig.reverse()), fmt(orig));
console.log(err(() => orig.with(3, 1)), '|', err(() => orig.with(-4, 1)), '|', err(() => new BigInt64Array(1).with(0, 1)), '|', err(() => orig.sort('x')), '|', err(() => orig.toSorted(null)));
const log = []; console.log(err(() => orig.with(10, { valueOf() { log.push('coerced'); return 1; } })), log.join());
console.log(fmt(new Float32Array([2, 1]).toSorted((a, b) => b - a)), new Uint8Array(3).toSorted().constructor.name, fmt(new Uint8Array(0).toReversed()));
''')


def test_set_subarray_slice_copywithin_fill(run, workdir):
    r"""CATCHES: subarray copying instead of sharing the buffer, negative/out-of-order indices in
    subarray/slice/copyWithin/fill, set() offsets and RangeErrors, set() from an overlapping view
    of the same buffer (must behave as if copied first) and across element types, fill value
    conversion, and slice producing a view on the same buffer."""
    check_script(run, workdir, G, "set_subarray_slice", PRE + r'''
const u = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
console.log(fmt(u.subarray(2, 5)), fmt(u.subarray(-3)), u.subarray(5, 2).length, fmt(u.slice(-2)), u.subarray(1).byteOffset, u.subarray(2, 6).buffer === u.buffer, u.slice(1, 3).buffer === u.buffer);
const sub = u.subarray(2, 6); sub[0] = 99; console.log(fmt(u), fmt(sub), sub.byteOffset, fmt(sub.subarray(1, 2)), sub.subarray(1, 2).byteOffset);
u.copyWithin(0, 5); console.log(fmt(u)); u.copyWithin(2, 0, 2); console.log(fmt(u)); u.copyWithin(-2, -4, -3); console.log(fmt(u));
console.log(fmt(new Uint8Array(5).fill(7, 1, -1)), fmt(new Float32Array(3).fill(1.1)), fmt(new Uint8Array(3).fill(300)), fmt(new Int8Array(3).fill('-2', -2)), fmt(new BigInt64Array(2).fill(-3n)));
const tgt = new Uint8Array(6); tgt.set([1, 2, 3], 2); tgt.set(new Int8Array([-1, -2]), 0); tgt.set({ length: 1, 0: 77 }, 5); console.log(fmt(tgt));
console.log(err(() => tgt.set([1, 2, 3], 4)), '|', err(() => tgt.set([1], -1)), '|', err(() => tgt.set(new BigInt64Array(1))), '|', err(() => tgt.set([1], Infinity)));
const ov = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]); ov.set(ov.subarray(0, 4), 2); console.log(fmt(ov));
const ov16 = new Uint16Array(ov.buffer, 0, 2); ov.set(ov16, 3); console.log(fmt(ov));
const f = new Float32Array(new Uint8Array([0, 0, 128, 63, 0, 0, 0, 64]).buffer); const back = new Uint8Array(f.buffer, 0, 2); back.set(f); console.log(fmt(f), fmt(back));
const s = new Int16Array([1, 2, 3, 4]).slice(1, 3); console.log(fmt(s), s.buffer.byteLength, fmt(new Int16Array([1, 2]).slice(5)), fmt(new BigUint64Array([1n, 2n]).subarray(-1)));
''')


def test_from_of_and_generic_methods(run, workdir):
    r"""CATCHES: TypedArray.from/of not converting values, ignoring mapfn/thisArg or iterables,
    accepting a non-callable mapfn, wrong `this` requirement; map/filter/reduce/join/toString/
    toLocaleString/entries behaving like Array (e.g. map not converting to the element type) and
    the brand checks on the shared prototype methods and accessors."""
    check_script(run, workdir, G, "from_of_generic", PRE + r'''
console.log(fmt(Int16Array.from('123')), fmt(Int16Array.from([1, 2, 3], function (v, i) { return v * 10 + i + this.k; }, { k: 100 })), fmt(Float32Array.of(1, 2.5, '3')), fmt(Uint8Array.from({ length: 3, 0: 9 })), fmt(Uint8Array.from(new Set([4, 5]))), fmt(BigInt64Array.of(1n, -1n)));
console.log(err(() => Uint8Array.from([1], 'nope')), '|', err(() => Uint8Array.of.call({}, 1)), '|', err(() => Uint8Array.from.call(Array, [1])), '|', err(() => BigInt64Array.from([1])));
const f = new Float32Array([1.5, -2, 3]);
console.log(fmt(f.map(x => x * 2)), fmt(new Uint8Array([200, 100]).map(x => x * 2)), fmt(f.filter(x => x > 0)), f.reduce((a, b) => a + b), f.reduceRight((a, b) => a + '|' + b, 's'), err(() => new Uint8Array(0).reduce((a, b) => a)));
console.log(f.join('-'), f.join(), f.toString(), String(new Uint8Array([1, 2])), new Float64Array([1.5, 1e21, -0]).join(';'), new BigUint64Array([1n, 2n]).join(), new Uint8Array(0).join() === '');
console.log(new Float64Array([1234.5, -0, 1e6]).toLocaleString(), '|', new BigInt64Array([1234n]).toLocaleString(), '|', new Uint8Array([1, 2]).toLocaleString());
console.log(Object.prototype.toString.call(new Float16Array(1)), new Uint8Array(1)[Symbol.toStringTag], Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Uint8Array.prototype), Symbol.toStringTag).get.call([]));
console.log(err(() => Uint8Array.prototype.join.call([1, 2])), '|', err(() => Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Uint8Array.prototype), 'length').get.call([])), '|', err(() => new Uint8Array(4).map(1)), '|', err(() => Uint8Array.prototype.subarray.call([])), '|', err(() => Uint8Array.prototype.set.call([], [])));
const it = new Uint8Array([7])[Symbol.iterator](); console.log(Object.prototype.toString.call(it), fmt(it.next()), fmt(it.next()));
const out = []; console.log(new Int8Array([3, -4]).forEach(function (v, i, a) { out.push(v + ':' + i + ':' + (a instanceof Int8Array) + ':' + this.tag); }, { tag: 'T' }), out.join(' '), err(() => new Int8Array(1).forEach()), new Int8Array(0).forEach(() => { throw 1; }));
''')


def test_integer_indexed_exotic_properties(run, workdir):
    r"""CATCHES: typed arrays treating canonical numeric keys ("-0", "1.5", "-1", "NaN",
    out-of-range indices) as ordinary properties or consulting the prototype chain for them,
    non-canonical keys ("01") not being ordinary, defineProperty accepting non-writable/accessor/
    non-enumerable element descriptors, delete of elements succeeding, freeze/seal behaviour, and
    [[Set]] through a typed array on the prototype chain. Also pins the reference's
    JSON.stringify of a typed array, which serializes only the non-index own properties
    ("{}" for a plain view -- an observed reference quirk)."""
    check_script(run, workdir, G, "integer_indexed", PRE + r'''
const ta = new Int16Array([10, 20, 30]);
console.log(fmt(Object.keys(ta)), fmt(Object.getOwnPropertyNames(ta)), [1 in ta, 3 in ta, '-0' in ta, '1.5' in ta, '01' in ta, 'foo' in ta, -1 in ta, 'Infinity' in ta, 'NaN' in ta].join());
ta[5] = 1; ta['-0'] = 9; ta['1.5'] = 9; ta['01'] = 7; ta.foo = 'bar'; ta[-1] = 3; ta.NaN = 4;
console.log(fmt(Object.keys(ta)), fmt(ta[5]), fmt(ta['-0']), ta['01'], ta.length, fmt(ta.NaN));
console.log(JSON.stringify(Object.getOwnPropertyDescriptor(ta, '0')), Object.getOwnPropertyDescriptor(ta, '3'), JSON.stringify(ta), JSON.stringify({ t: new Uint8Array([1, 2]) }));
console.log(err(() => Object.defineProperty(ta, '0', { value: 99 })), ta[0], err(() => Object.defineProperty(ta, '0', { value: 1, writable: false })), err(() => Object.defineProperty(ta, '0', { get() { return 1; } })), err(() => Object.defineProperty(ta, '7', { value: 1 })), err(() => Object.defineProperty(ta, '0', { value: 5, enumerable: false })));
console.log(Reflect.defineProperty(ta, '0', { value: 1, configurable: false }), Reflect.defineProperty(ta, '1', { value: 42, writable: true, enumerable: true, configurable: true }), ta[1]);
console.log(delete ta[0], delete ta[7], delete ta.foo, err(() => { 'use strict'; delete ta[0]; }), Object.isExtensible(ta));
console.log(err(() => Object.freeze(ta)), err(() => Object.freeze(new Int8Array(0))), err(() => Object.seal(ta)), Object.isFrozen(Object.freeze(new Int8Array(0))));
console.log(ta[0] = 'x', ta[0], (ta[1] = '12abc', ta[1]), (ta[2] = { valueOf() { return 7.9; } }, ta[2]), Reflect.set(ta, 10, 1), Reflect.set(ta, 0, 1), Reflect.get(ta, 10), Reflect.has(ta, 2));
Object.prototype[3] = 'proto'; Object.prototype['-0'] = 'p'; console.log(fmt(ta[3]), 3 in ta, fmt(new Int8Array(2)['-0'])); delete Object.prototype[3]; delete Object.prototype['-0'];
const child = Object.create(ta); child[0] = 55; child[9] = 1; console.log(ta[0], Object.keys(child).join(), fmt(child[9]));
''')


def test_species_and_subclassing(run, workdir):
    r"""CATCHES: map/filter/slice/subarray ignoring Symbol.species (or toSorted/toReversed/with
    honouring it, which they must not), not validating that the species result is a typed
    array of sufficient length, and subarray constructing species views with wrong offsets."""
    check_script(run, workdir, G, "species", PRE + r'''
class MyU8 extends Uint8Array { static get [Symbol.species]() { return Uint16Array; } sum() { return this.reduce((a, b) => a + b, 0); } }
const mu = new MyU8([1, 2, 300]);
console.log(mu.constructor.name, mu.sum(), fmt(mu.map(x => x * 100)), mu.filter(x => x > 1).constructor.name, mu.slice(1).constructor.name, err(() => mu.subarray(1)), err(() => mu.subarray(0)));
console.log(mu.toSorted().constructor.name, mu.with(0, 9).constructor.name, mu.toReversed().constructor.name, MyU8.from([1]).constructor.name, MyU8.of(2).constructor.name, mu instanceof Uint8Array);
class Bad extends Uint8Array { static get [Symbol.species]() { return function () { return {}; }; } }
console.log(err(() => new Bad(2).map(x => x)), '|', err(() => new Bad(2).slice()), '|', err(() => new Bad(2).subarray()), '|', err(() => new Bad(2).filter(() => 1)));
class Short extends Uint8Array { static get [Symbol.species]() { return function (n) { return new Uint8Array(1); }; } }
console.log(err(() => new Short(4).map(x => x)), '|', err(() => new Short(4).slice(0, 3)), '|', err(() => new Short(4).filter(() => 1)));
class Mixed extends Uint8Array { static get [Symbol.species]() { return BigInt64Array; } }
console.log(err(() => new Mixed(2).slice()), '|', err(() => new Mixed(2).map(x => x)));
let calls = []; class Logged extends Int8Array { static get [Symbol.species]() { calls.push('species'); return Int8Array; } }
const lg = new Logged([1, 2, 3]); lg.slice(1); lg.subarray(1); lg.toSorted(); console.log(calls.join(','));
const x = new Uint8Array([1, 2]);
x.constructor = 5; console.log(err(() => x.map(v => v)));
x.constructor = { [Symbol.species]: 5 }; console.log(err(() => x.slice()));
x.constructor = { [Symbol.species]: null }; console.log(err(() => x.filter(() => true)));
x.constructor = undefined; console.log(err(() => x.subarray(1)));
x.constructor = { [Symbol.species]: function () { return new Uint8Array(new Uint8Array(4).buffer.transferToImmutable()); } };
console.log(err(() => x.map(v => v)), '|', err(() => x.slice()), '|', err(() => x.subarray()));
x.constructor = { [Symbol.species]: function () { const b = new ArrayBuffer(4); const t = new Uint8Array(b); b.transfer(); return t; } };
console.log(err(() => x.map(v => v)), '|', err(() => x.filter(() => 1)));
const src = new Uint8Array([1, 2, 3]); src.constructor = { [Symbol.species]: function (len) { src.buffer.transfer(); return new Uint8Array(len); } };
console.log(err(() => src.map(v => v)), src.length);
''')


def test_resizable_array_buffer_and_tracking_views(run, workdir):
    r"""CATCHES: resizable ArrayBuffers without length-tracking views (length follows the buffer),
    fixed-length views not going out of bounds (length/byteOffset 0 and operations throwing) when
    the buffer shrinks and coming back when it regrows, data not zero-filled on regrowth, and
    wrong resize/maxByteLength errors and option handling."""
    check_script(run, workdir, G, "resizable_buffer", PRE + r'''
const ab = new ArrayBuffer(4, { maxByteLength: 12 });
console.log(ab.byteLength, ab.maxByteLength, ab.resizable, ab.detached, new ArrayBuffer(4).maxByteLength, new ArrayBuffer(4).resizable);
const track = new Uint8Array(ab); const fixed = new Uint8Array(ab, 0, 4); const off = new Uint16Array(ab, 2);
track.set([1, 2, 3, 4]);
console.log(ab.resize(10), track.length, fixed.length, off.length, fmt(track), off.byteLength);
ab.resize(1); console.log(track.length, fixed.length, fixed.byteLength, fixed.byteOffset, off.length, off.byteOffset, fmt(track));
console.log(err(() => fixed[0]), err(() => fixed.join()), err(() => off.fill(1)), err(() => [...off]), err(() => fixed.at(0)), fixed[0] = 5, err(() => fixed.slice()));
ab.resize(4); console.log(fmt(fixed), off.length, fmt(off), fixed.byteLength);
console.log(err(() => ab.resize(13)), '|', err(() => ab.resize(-1)), '|', err(() => new ArrayBuffer(4).resize(2)));
console.log(err(() => new ArrayBuffer(8, { maxByteLength: 4 })), '|', err(() => new ArrayBuffer(1, { maxByteLength: -1 })), '|', err(() => new ArrayBuffer(1, { maxByteLength: 2 ** 53 })));
console.log(new ArrayBuffer(3, {}).resizable, new ArrayBuffer(3, { maxByteLength: undefined }).resizable, new ArrayBuffer(2.9).byteLength, new ArrayBuffer('3').byteLength, new ArrayBuffer().byteLength, new ArrayBuffer(0, { maxByteLength: 0 }).resizable);
console.log(err(() => new ArrayBuffer(-1)), '|', err(() => ArrayBuffer(1)), '|', err(() => new ArrayBuffer(2 ** 53)));
const r2 = new ArrayBuffer(2, { maxByteLength: 8 }); const t32 = new Int32Array(r2); console.log(t32.length); r2.resize(7); console.log(t32.length, t32.byteLength); r2.resize(8); console.log(t32.length);
const s = new ArrayBuffer(4, { maxByteLength: 8 }); const sl = s.slice(1); console.log(sl.resizable, sl.byteLength, sl.maxByteLength);
''')


def test_transfer_and_detached_buffers(run, workdir):
    r"""CATCHES: transfer()/transferToFixedLength() not detaching the source, not preserving data
    and resizability, mishandling the new length (truncate/zero-extend), and views over a
    detached buffer not reporting length 0 / throwing the exact TypeErrors from methods, slice,
    resize and construction. Also pins the reference quirk that transfer(n) of a resizable
    buffer to n > maxByteLength succeeds (byteLength n, maxByteLength unchanged) instead of
    throwing a RangeError."""
    check_script(run, workdir, G, "transfer_detach", PRE + r'''
const src = new ArrayBuffer(4, { maxByteLength: 8 }); new Uint8Array(src).set([9, 8, 7, 6]);
const v = new Uint8Array(src);
const t1 = src.transfer();
console.log(src.detached, src.byteLength, src.maxByteLength, t1.byteLength, t1.resizable, t1.maxByteLength, fmt(new Uint8Array(t1)), v.length, v.byteOffset, v.byteLength);
console.log(err(() => v[0]), err(() => v.join()), err(() => v.at(0)));
console.log(err(() => src.slice(0)), '|', err(() => src.transfer()), '|', err(() => src.resize(1)), '|', err(() => new Uint8Array(src)), '|', err(() => new DataView(src)));
const t2 = t1.transfer(6); console.log(t2.byteLength, t2.resizable, fmt(new Uint8Array(t2)), t1.detached);
const t3 = t2.transferToFixedLength(2); console.log(t3.byteLength, t3.resizable, fmt(new Uint8Array(t3)));
console.log(err(() => t3.transfer(-1)), '|', err(() => t3.slice(0).transfer(9, 1)), '|', err(() => t2.transferToFixedLength()), '|', err(() => t3.transfer(2 ** 53)));
const t4 = t3.transfer(0); console.log(t4.byteLength, t3.detached, t4.detached);
const t5 = new Uint8Array([1, 2]).buffer.transfer(5); console.log(fmt(new Uint8Array(t5)), t5.resizable);
const fixedToBig = new ArrayBuffer(4, { maxByteLength: 4 }).transfer(); console.log(fixedToBig.resizable, fixedToBig.maxByteLength);
const over = new ArrayBuffer(4, { maxByteLength: 6 }).transfer(10); console.log(over.byteLength, over.resizable, over.maxByteLength);
const s = new Uint8Array([1, 2, 3, 4, 5]).buffer; console.log(fmt(new Uint8Array(s.slice(1, -1))), s.slice(4, 1).byteLength, fmt(new Uint8Array(s.slice(-2))));
console.log(ArrayBuffer.isView(new DataView(s)), ArrayBuffer.isView(s), ArrayBuffer.isView(new Uint8Array(1)), ArrayBuffer.isView(), Object.prototype.toString.call(s), ArrayBuffer[Symbol.species] === ArrayBuffer);
console.log(err(() => ArrayBuffer.prototype.slice.call(new SharedArrayBuffer(1))), '|', err(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'detached').get.call({})));
''')


def test_immutable_array_buffer(run, workdir):
    r"""CATCHES: transferToImmutable/sliceToImmutable missing, immutable buffers being writable via
    typed-array methods, DataView setters or strict-mode assignment (exact TypeError messages),
    or being resizable/detachable; sloppy assignment must silently do nothing. Also pins the
    reference's Reflect.set path, which DOES write through an immutable-buffer view (an observed
    reference quirk)."""
    check_script(run, workdir, G, "immutable_buffer", PRE + r'''
const src = new Uint8Array([1, 2, 3]).buffer;
const im = src.transferToImmutable(); console.log(im.immutable, im.byteLength, im.resizable, src.detached, new ArrayBuffer(1).immutable);
const iv = new Uint8Array(im); iv[0] = 50; console.log(fmt(iv));
console.log(err(() => iv.fill(0)), '|', err(() => iv.set([1])), '|', err(() => iv.sort()), '|', err(() => iv.copyWithin(0, 1)), '|', err(() => iv.reverse()));
console.log(err(() => new DataView(im).setInt8(0, 1)), '|', err(() => im.resize(1)), '|', err(() => im.transfer()), '|', err(() => im.transferToImmutable()));
console.log(err(() => { 'use strict'; iv[0] = 5; }), '|', err(() => iv.setFromHex('ff')));
console.log(fmt(iv.map(x => x * 2)), fmt(iv.slice(1)), fmt(iv.toReversed()), new DataView(im).getUint8(2), fmt(new Uint8Array(im.slice(1))), im.slice(1).immutable);
const si = new Uint8Array([5, 6, 7, 8]).buffer.sliceToImmutable(1, 3); console.log(si.immutable, fmt(new Uint8Array(si)), new Uint8Array([5, 6]).buffer.sliceToImmutable().byteLength);
console.log(Reflect.set(iv, 0, 9), fmt(iv));
''')


def test_shared_array_buffer(run, workdir):
    r"""CATCHES: SharedArrayBuffer missing growable/grow/maxByteLength, grow allowing shrink or
    exceeding the max, length-tracking views not following growth, slice returning the wrong
    class, and the ArrayBuffer/SharedArrayBuffer brand checks with their messages."""
    check_script(run, workdir, G, "shared_buffer", PRE + r'''
const sab = new SharedArrayBuffer(4, { maxByteLength: 16 });
console.log(sab.byteLength, sab.maxByteLength, sab.growable, Object.prototype.toString.call(sab), sab.slice(1).byteLength, sab.slice(1) instanceof SharedArrayBuffer, sab.slice(1).growable);
const tv = new Int32Array(sab); console.log(tv.length, sab.grow(8), tv.length, sab.byteLength, sab.grow(8), sab.byteLength);
console.log(err(() => sab.grow(4)), '|', err(() => sab.grow(17)), '|', err(() => new SharedArrayBuffer(2).grow(2)), '|', err(() => SharedArrayBuffer(1)), '|', err(() => new SharedArrayBuffer(-1)));
console.log(err(() => SharedArrayBuffer.prototype.slice.call(new ArrayBuffer(1))), '|', err(() => Object.getOwnPropertyDescriptor(SharedArrayBuffer.prototype, 'byteLength').get.call(new ArrayBuffer(1))), '|', err(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'byteLength').get.call(sab)));
console.log(new SharedArrayBuffer(3).growable, new SharedArrayBuffer(3).maxByteLength, 'transfer' in sab, ArrayBuffer.isView(sab), new SharedArrayBuffer(5).slice(-2, 10).byteLength);
const shared = new Uint8Array(new SharedArrayBuffer(4)); shared.set([1, 2, 3, 4]); const other = new Uint16Array(shared.buffer); console.log(fmt(other), other.buffer === shared.buffer);
''')


def test_dataview_all_types_and_endianness(run, workdir):
    r"""CATCHES: DataView getters/setters with wrong default endianness (big-endian), wrong
    little-endian byte order, missing Float16/BigInt accessors, wrong wrapping of out-of-range
    integer values, NaN/-0 float encodings, ToBoolean of the littleEndian argument, and byte
    offsets relative to the view (not the buffer)."""
    check_script(run, workdir, G, "dataview_types", PRE + r'''
const buf = new ArrayBuffer(16); const dv = new DataView(buf, 2, 12); const bytes = new Uint8Array(buf);
const hex = () => Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
console.log(dv.byteOffset, dv.byteLength, dv.buffer === buf, Object.prototype.toString.call(dv));
dv.setInt16(0, -2); dv.setInt16(2, -2, true); console.log(hex(), dv.getInt16(0), dv.getUint16(0), dv.getInt16(0, true), dv.getUint16(2, true));
dv.setUint32(4, 0xdeadbeef); console.log(hex(), dv.getUint32(4).toString(16), dv.getUint32(4, true).toString(16), dv.getInt32(4), dv.getInt32(4, true), dv.getInt8(4), dv.getUint8(4));
dv.setFloat32(0, Math.PI, true); console.log(hex(), dv.getFloat32(0, true), dv.getFloat32(0));
dv.setFloat64(4, -1.5); console.log(hex(), dv.getFloat64(4), dv.getFloat64(4, true));
dv.setFloat16(0, 1.5); dv.setFloat16(2, 65504, true); console.log(hex(), dv.getFloat16(0), dv.getFloat16(2, true), dv.getFloat16(0, true));
dv.setFloat64(4, NaN); console.log(hex()); dv.setFloat32(4, -0); console.log(hex(), fmt(dv.getFloat32(4)));
dv.setBigInt64(4, -2n); console.log(hex(), fmt(dv.getBigInt64(4)), fmt(dv.getBigUint64(4)), fmt(dv.getBigInt64(4, true)));
dv.setBigUint64(4, 2n ** 64n + 1n, true); console.log(hex(), fmt(dv.getBigUint64(4, true)), fmt(dv.getBigUint64(4)));
dv.setInt8(11, 200); dv.setUint8(10, -1); dv.setUint16(8, 70000); dv.setInt32(0, 2 ** 32 + 5, 1); console.log(hex(), dv.getInt8(11), dv.getUint8(10), dv.getUint16(8), dv.getInt32(0, 'yes'));
console.log(dv.getUint16(1.9), dv.getUint16('3'), dv.getUint8(), dv.setUint8(0, 1), new DataView(new ArrayBuffer(8), 8).byteLength, new DataView(new ArrayBuffer(8), 3).byteLength);
const sdv = new DataView(new SharedArrayBuffer(4)); sdv.setUint16(1, 0x1234); console.log(sdv.getUint8(1), sdv.getUint8(2), Object.prototype.toString.call(sdv.buffer));
''')


def test_dataview_errors_resizable_detached(run, workdir):
    r"""CATCHES: DataView accessors not range-checking offset+size against the view, wrong
    errors for negative offsets/BigInt mismatches/bad buffers/constructor misuse, length-tracking
    DataViews over resizable buffers not following resizes, fixed views not throwing once out of
    bounds, and detached-buffer views not throwing from byteLength/byteOffset/getters."""
    check_script(run, workdir, G, "dataview_errors", PRE + r'''
const buf = new ArrayBuffer(16); const dv = new DataView(buf, 2, 12);
console.log(err(() => dv.getInt32(9)), '|', err(() => dv.getInt8(12)), '|', err(() => dv.getInt8(-1)), '|', err(() => dv.setUint16(11, 1)), '|', err(() => dv.getFloat64(Infinity)));
console.log(err(() => dv.setBigInt64(0, 1)), '|', err(() => dv.setInt8(0, 1n)), '|', err(() => dv.setInt8(0, Symbol())));
console.log(err(() => new DataView(buf, 17)), '|', err(() => new DataView(buf, 4, 13)), '|', err(() => new DataView({})), '|', err(() => DataView(buf)), '|', err(() => new DataView(buf, -1)), '|', err(() => new DataView()));
console.log(err(() => DataView.prototype.getInt8.call(new Uint8Array(2), 0)), '|', err(() => Object.getOwnPropertyDescriptor(DataView.prototype, 'byteLength').get.call(new Uint8Array(1))));
const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const tdv = new DataView(rab, 2); const fdv = new DataView(rab, 2, 4);
console.log(tdv.byteLength, fdv.byteLength); rab.resize(12); console.log(tdv.byteLength, fdv.byteLength, err(() => tdv.getInt8(9)), err(() => tdv.getInt8(10)));
rab.resize(4); console.log(tdv.byteLength, err(() => fdv.byteLength), err(() => fdv.getInt8(0)), err(() => fdv.byteOffset));
rab.resize(1); console.log(err(() => tdv.byteLength), err(() => tdv.byteOffset), err(() => tdv.getInt8(0)));
rab.resize(6); console.log(fdv.byteLength, tdv.byteLength, fdv.byteOffset);
const det = new ArrayBuffer(4); const ddv = new DataView(det); det.transfer(); console.log(err(() => ddv.byteLength), '|', err(() => ddv.getInt8(0)), '|', err(() => ddv.byteOffset), '|', ddv.buffer.detached);
console.log(err(() => new DataView(new ArrayBuffer(2), 0, -1)), '|', err(() => new DataView(new ArrayBuffer(2), 3)), '|', new DataView(new ArrayBuffer(2), undefined, undefined).byteLength);
''')


def test_atomics_operations(run, workdir):
    r"""CATCHES: Atomics read-modify-write operations returning the new value instead of the old
    one, not wrapping to the element type, compareExchange comparing unconverted values, store
    returning the converted value instead of ToIntegerOrInfinity of the input, BigInt64 support,
    and operating on non-shared integer arrays."""
    check_script(run, workdir, G, "atomics_ops", PRE + r'''
const ia = new Int32Array(new SharedArrayBuffer(16));
console.log(Atomics.store(ia, 0, 5), Atomics.add(ia, 0, 3), Atomics.load(ia, 0), Atomics.sub(ia, 0, 10), ia[0], Atomics.and(ia, 0, 6), ia[0], Atomics.or(ia, 0, 1), ia[0], Atomics.xor(ia, 0, 3), ia[0]);
console.log(Atomics.exchange(ia, 0, 100), Atomics.compareExchange(ia, 0, 100, 7), Atomics.compareExchange(ia, 0, 100, 8), ia[0], Atomics.add(ia, 1, 2 ** 31), ia[1], Atomics.sub(ia, 2, 1), ia[2]);
console.log(Atomics.store(ia, 1, 3.7), fmt(Atomics.store(ia, 1, -0)), Atomics.store(ia, 1, 2 ** 32 + 1), ia[1], Atomics.store(ia, 1, '12'), Atomics.load(ia, '1'), Atomics.store(ia, 3, Infinity), ia[3]);
const u8 = new Uint8Array(4); console.log(Atomics.add(u8, 0, 300), u8[0], Atomics.sub(u8, 1, 1), u8[1], Atomics.compareExchange(u8, 1, 255, 1), u8[1], Atomics.compareExchange(u8, 1, 257, 9), u8[1]);
const i16 = new Int16Array(2); console.log(Atomics.exchange(i16, 0, 40000), i16[0], Atomics.or(i16, 1, -1), i16[1]);
const b64 = new BigInt64Array(new SharedArrayBuffer(16)); console.log(fmt(Atomics.add(b64, 0, 5n)), fmt(Atomics.exchange(b64, 0, -1n)), fmt(Atomics.compareExchange(b64, 0, -1n, 2n ** 63n)), fmt(b64[0]), fmt(Atomics.sub(b64, 1, 1n)), fmt(Atomics.load(b64, 1)));
const bu = new BigUint64Array(1); console.log(fmt(Atomics.sub(bu, 0, 1n)), fmt(bu[0]), fmt(Atomics.and(bu, 0, 0xffn)), fmt(Atomics.store(bu, 0, 2n ** 64n + 3n)), fmt(bu[0]));
console.log([1, 2, 3, 4, 5, 6, 7, 8].map(n => Atomics.isLockFree(n)).join(), String(Atomics), Object.prototype.toString.call(Atomics), typeof Atomics.pause, Atomics.pause === undefined ? '' : fmt(Atomics.pause()));
''')


def test_atomics_wait_notify_and_errors(run, workdir):
    r"""CATCHES: Atomics.wait returning wrong strings ("not-equal"/"timed-out"), waitAsync result
    shapes (sync {async:false} vs promise resolving to "ok"/"timed-out"), notify return counts,
    and the TypeError/RangeError messages for non-shared arrays, wrong element types, float
    arrays, out-of-range indices, non-typed-array receivers, immutable and detached buffers
    (also when a value coercion detaches/shrinks the buffer), Atomics.pause argument checks, and
    a NaN-timeout waitAsync (async:true) that must not keep the process alive."""
    check_script(run, workdir, G, "atomics_wait_errors", PRE + r'''
const ia = new Int32Array(new SharedArrayBuffer(16)); ia[0] = 7;
console.log(Atomics.wait(ia, 0, 7, 0), Atomics.wait(ia, 0, 7, 5), Atomics.wait(ia, 0, 6), Atomics.wait(ia, 0, 7, NaN === NaN ? 1 : -1));
console.log(Atomics.notify(ia, 0, 1), Atomics.notify(ia, 0), Atomics.notify(new Int32Array(4), 0), Atomics.notify(ia, 0, -5));
console.log(fmt(Atomics.waitAsync(ia, 0, 6)), fmt(Atomics.waitAsync(ia, 0, 7, 0)));
const w = Atomics.waitAsync(ia, 1, 0); console.log(w.async, Object.prototype.toString.call(w.value), Atomics.notify(ia, 1, 1), Atomics.notify(ia, 1, 1));
console.log(err(() => Atomics.wait(new Int32Array(4), 0, 0, 0)), '|', err(() => Atomics.wait(new Int16Array(new SharedArrayBuffer(4)), 0, 0, 0)));
console.log(err(() => Atomics.add(new Float64Array(1), 0, 1)), '|', err(() => Atomics.add(ia, 4, 1)), '|', err(() => Atomics.add(ia, -1, 1)), '|', err(() => Atomics.load([1], 0)));
console.log(err(() => Atomics.add(new Uint8ClampedArray(1), 0, 1)), '|', err(() => Atomics.store(new Float32Array(1), 0, 1)), '|', err(() => Atomics.notify(new Float64Array(1), 0)), '|', err(() => Atomics.add(new BigInt64Array(1), 0, 1)));
const ab = new ArrayBuffer(4); const ta = new Uint8Array(ab); ab.transfer(); console.log(err(() => Atomics.load(ta, 0)), '|', err(() => Atomics.store(ta, 0, 1)));
const imm = new Int32Array(new Int32Array([1, 2]).buffer.transferToImmutable());
console.log(err(() => Atomics.store(imm, 0, 1)), '|', err(() => Atomics.add(imm, 0, 1)), '|', err(() => Atomics.load(imm, 1)), '|', err(() => Atomics.compareExchange(imm, 0, 1, 2)));
const ab1 = new ArrayBuffer(8); const t1 = new Int32Array(ab1); console.log(err(() => Atomics.store(t1, 1, { valueOf() { ab1.transfer(); return 1; } })));
const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const rt = new Int32Array(rab); console.log(err(() => Atomics.add(rt, 1, { valueOf() { rab.resize(4); return 1; } })), rt.length);
const ab2 = new ArrayBuffer(8); const t2 = new Int32Array(ab2); ab2.transfer(); console.log(err(() => Atomics.notify(t2, 0)), '|', err(() => Atomics.wait(t2, 0, 0, 0)), '|', err(() => Atomics.waitAsync(new Int32Array(4), 0, 0, 0)));
console.log(err(() => Atomics.pause(1.5)), '|', err(() => Atomics.pause(1)), '|', err(() => Atomics.pause('1')), '|', err(() => Atomics.pause(-3)));
console.log(err(() => Atomics.notify(ia, 4)), '|', err(() => Atomics.wait(ia, 4, 0)), '|', err(() => Atomics.notify(ia, 0, NaN)), '|', err(() => Atomics.notify(new BigInt64Array(new SharedArrayBuffer(8)), 0)));
const bi = new BigInt64Array(new SharedArrayBuffer(8)); console.log(err(() => Atomics.wait(bi, 0, 1n, 0)), err(() => Atomics.wait(bi, 0, 0n, 0)), '|', err(() => Atomics.wait(bi, 0, 0, 0)));
const forever = Atomics.waitAsync(ia, 0, 7, NaN); console.log('NaN timeout', forever.async, fmt(Atomics.waitAsync(ia, 0, 7, -Infinity)));
''')


def test_uint8array_base64_and_hex(run, workdir):
    r"""CATCHES: missing or wrong Uint8Array.prototype.toBase64/toHex and Uint8Array.fromBase64/
    fromHex/setFromBase64/setFromHex: alphabet and omitPadding options, whitespace skipping, the
    three lastChunkHandling modes, {read, written} results with partial writes into a short
    target, and the exact SyntaxError/TypeError messages for malformed input and bad options."""
    check_script(run, workdir, G, "base64_hex", PRE + r'''
const u = new Uint8Array([72, 101, 108, 108, 111, 251, 255, 0]);
console.log(u.toBase64(), u.toBase64({ alphabet: 'base64url' }), u.toBase64({ omitPadding: true }), u.subarray(0, 5).toBase64(), u.subarray(0, 4).toBase64({ omitPadding: true }), u.toHex(), JSON.stringify(new Uint8Array(0).toBase64()), JSON.stringify(new Uint8Array(0).toHex()));
console.log(err(() => Uint8Array.fromBase64('SGVsbG8=')), err(() => Uint8Array.fromBase64('SGVsbG8')), err(() => Uint8Array.fromBase64(' S G V s\nbG8= ')), err(() => Uint8Array.fromBase64('-_8=', { alphabet: 'base64url' })));
console.log(err(() => Uint8Array.fromBase64('+/8=', { alphabet: 'base64url' })), '|', err(() => Uint8Array.fromBase64('-_8=')));
console.log(err(() => Uint8Array.fromBase64('SGVsbG8', { lastChunkHandling: 'strict' })), err(() => Uint8Array.fromBase64('SGVsbG9=', { lastChunkHandling: 'strict' })), err(() => Uint8Array.fromBase64('SGVsbG8', { lastChunkHandling: 'stop-before-partial' })), err(() => Uint8Array.fromBase64('SGVsbG9=', { lastChunkHandling: 'loose' })));
console.log(err(() => Uint8Array.fromBase64('SGVsbG8=', { lastChunkHandling: 'bogus' })), '|', err(() => Uint8Array.fromBase64('SGVsbG8=', { alphabet: 'hex' })));
console.log(['S', 'SG=V', 'SGVs=', 'SGVsbG8==', 'SGV*', 'AA==AA==', 'AA=', 'A==='].map(s => s + ' ' + err(() => Uint8Array.fromBase64(s))).join(' | '));
console.log(err(() => Uint8Array.fromBase64(42)), '|', err(() => Uint8Array.fromBase64('', 5)), '|', err(() => Uint8Array.fromBase64('')));
console.log(err(() => Uint8Array.fromHex('48656c6C6f')), err(() => Uint8Array.fromHex('abc')), err(() => Uint8Array.fromHex('zz')), err(() => Uint8Array.fromHex('')), err(() => Uint8Array.fromHex(1)), err(() => Uint8Array.fromHex('ab cd')));
const tgt = new Uint8Array(4);
console.log(fmt(tgt.setFromBase64('SGVsbG8=')), fmt(tgt), fmt(new Uint8Array(8).setFromBase64('SGVsbG8=')), fmt(tgt.setFromHex('aabbccddee')), fmt(tgt), fmt(tgt.setFromHex('01')), fmt(tgt));
const t2 = new Uint8Array(5); console.log(fmt(t2.setFromBase64('SGVs bG8', { lastChunkHandling: 'stop-before-partial' })), fmt(t2));
const t3 = new Uint8Array(5); console.log(err(() => t3.setFromHex('aaxx')), fmt(t3), err(() => t3.setFromBase64('qqqq$')), fmt(t3));
const t4 = new Uint8Array(new ArrayBuffer(8), 2, 3); console.log(fmt(t4.setFromBase64('/////w==')), fmt(new Uint8Array(t4.buffer)));
console.log(err(() => Uint8Array.prototype.toBase64.call(new Int8Array(1))), '|', err(() => Uint8Array.prototype.toHex.call([1])), '|', err(() => new Uint8Array(1).setFromBase64(1)), '|', err(() => new Uint8Array(1).setFromHex(1)));
console.log(err(() => new Uint8Array(1).toBase64({ alphabet: 'x' })), '|', err(() => new Uint8Array(1).toBase64(null)), '|', err(() => new Uint8Array(1).toBase64('x')), '|', new Uint8Array([255]).toBase64(undefined));
const ab = new ArrayBuffer(4); const dv = new Uint8Array(ab); ab.transfer(); console.log(err(() => dv.toBase64()), '|', err(() => dv.toHex()), '|', err(() => dv.setFromHex('00')));
console.log(Uint8Array.fromBase64.length, Uint8Array.prototype.setFromBase64.length, typeof Int8Array.fromBase64, typeof Int8Array.prototype.toHex);
''')


WAIT_ASYNC = r'''
const ia = new Int32Array(new SharedArrayBuffer(16));
const w = Atomics.waitAsync(ia, 1, 0); console.log(w.async, Atomics.notify(ia, 1, 1), Atomics.notify(ia, 1, 1));
const two = [Atomics.waitAsync(ia, 3, 0), Atomics.waitAsync(ia, 3, 0, 1000)];
console.log('notified', Atomics.notify(ia, 3));
// each step starts only after the previous one settled, so the order never depends on timing
w.value.then(v => { console.log('woken', v); return Promise.all(two.map(x => x.value)); })
  .then(v => { console.log('both', v.join()); const t = Atomics.waitAsync(ia, 2, 0, 30); console.log('waiting', t.async); return t.value; })
  .then(v => console.log('timer', v));
Promise.resolve().then(() => console.log('microtask'));
console.log('sync end');
'''


def test_atomics_wait_async_settlement_esm_vs_cjs(run, workdir):
    r"""CATCHES: Atomics.waitAsync promises not resolving to "ok" when notified (in FIFO waiter
    order, notify counting every waiter) or "timed-out" after the timeout, relative to microtasks,
    in an ES module; and pins the reference quirk that in a CommonJS script the same waitAsync
    promises never settle (only the microtask and an ordinary timer run)."""
    check_script(run, workdir, G, "wait_async_esm", WAIT_ASYNC, filename="wait_async.mjs")
    check_script(run, workdir, G, "wait_async_cjs", WAIT_ASYNC + "setTimeout(() => console.log('plain timer'), 50);\n",
                 filename="wait_async.cjs")


@pytest.mark.parametrize("cli", [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
                                 pytest.param(["--tier=bytecode"], id="bytecode")])
def test_hot_typed_array_loops_across_tiers(run, workdir, cli):
    r"""CATCHES: JIT/bytecode fast paths for typed-array element loads/stores that skip element
    conversion (wrapping, clamping, float rounding), ignore out-of-bounds writes, keep reading a
    detached or shrunk buffer, or diverge from the interpreter on DataView accesses in hot loops."""
    check_script(run, workdir, G, "typed_array_tiers", r'''
function fill(ta, n) { for (let i = 0; i < n; i++) ta[i] = i * 37 - 500.5; return ta; }
function sum(ta) { let s = 0; for (let i = 0; i < ta.length + 2; i++) { const v = ta[i]; s += v === undefined ? 1000 : Number(v); } return s; }
const kinds = [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint32Array, Float32Array, Float64Array];
for (let round = 0; round < 3; round++) {
  const line = kinds.map(K => sum(fill(new K(64), 70)));
  console.log(round, line.join(' '));
}
const rab = new ArrayBuffer(64, { maxByteLength: 128 }); const view = new Int32Array(rab);
let total = 0;
for (let i = 0; i < 300; i++) {
  if (i === 100) rab.resize(16);
  if (i === 200) rab.resize(128);
  view[i % 40] = i;
  total += view.length + (view[i % 40] === undefined ? -1 : view[i % 40]);
}
console.log('resizable', total, view.length);
const ab = new ArrayBuffer(16); const u = new Uint16Array(ab); let acc = 0;
for (let i = 0; i < 200; i++) { if (i === 150) ab.transfer(); u[i % 8] = i; acc += u[i % 8] === undefined ? 1 : u[i % 8]; }
console.log('detached', acc, u.length);
const dv = new DataView(new ArrayBuffer(32)); let h = 0;
for (let i = 0; i < 400; i++) { dv.setInt16(i % 30, i * 331, i & 1); h = (h * 31 + dv.getUint16(i % 30, !(i & 1)) + dv.getInt8(i % 31)) >>> 0; }
console.log('dataview', h);
const b = new BigInt64Array(8); for (let i = 0; i < 100; i++) b[i % 8] += BigInt(i) * 3000000000000000000n; console.log('bigint', b.join());
''', cli=cli)
