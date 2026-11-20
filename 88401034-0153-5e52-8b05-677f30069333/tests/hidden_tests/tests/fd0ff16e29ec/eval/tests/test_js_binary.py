"""Binary data and numbers: TypedArrays (all kinds incl. Float16 and BigInt64), ArrayBuffer (resizable,
transfer, immutable), SharedArrayBuffer, DataView, Atomics, Uint8Array base64/hex, BigInt arithmetic and
Number formatting. Each program prints labelled lines that are compared to a golden recorded from the
reference binary; engine-heavy programs run under all three execution tiers."""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


PROG_KINDS = r"""
const show = (v) => typeof v === 'bigint' ? v + 'n' : (Object.is(v, -0) ? '-0' : String(v));
const kinds = [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, Float16Array, Float32Array, Float64Array];
const inputs = [0, -0, 1.5, 2.5, -1.5, 127, 128, 255, 256, -129, 65535, 65536, 2147483648, -2147483649, 4294967296 + 7, 1e10, NaN, Infinity, -Infinity, 0.1, 65504, 65520, 1e-5, 6e-8, 3.4028235677973366e38, 1e39];
for (const K of kinds) {
  const a = new K(inputs.length);
  inputs.forEach((v, i) => { a[i] = v; });
  console.log(K.name.padEnd(18), K.BYTES_PER_ELEMENT, a.BYTES_PER_ELEMENT, Array.from(a, show).join(' '));
}
for (const K of [BigInt64Array, BigUint64Array]) {
  const a = new K(8);
  const vals = [0n, -1n, 2n ** 63n, 2n ** 64n + 5n, -(2n ** 63n) - 1n, 123456789012345678901234567890n, 2n**63n-1n, -5n];
  vals.forEach((v, i) => { a[i] = v; });
  console.log(K.name.padEnd(18), K.BYTES_PER_ELEMENT, Array.from(a, show).join(' '));
  try { a[0] = 1; } catch (e) { console.log(e.name + ': ' + e.message); }
  a[1] = '77'; a[2] = true;
  console.log(show(a[1]), show(a[2]));
  try { a[3] = 'x1'; } catch (e) { console.log(e.name + ': ' + e.message); }
}
try { new Int8Array(2)[0] = 1n; } catch (e) { console.log(e.name + ': ' + e.message); }
const ab = new ArrayBuffer(8);
const f64 = new Float64Array(ab), u8 = new Uint8Array(ab), u16 = new Uint16Array(ab), f32 = new Float32Array(ab), i32 = new Int32Array(ab), f16 = new Float16Array(ab);
f64[0] = Math.PI;
console.log(Array.from(u8).join(','), Array.from(u16).join(','), Array.from(f32, show).join(','), Array.from(i32).join(','), Array.from(f16, show).join(','));
f64[0] = -0; console.log(Array.from(u8).join(','));
f64[0] = NaN; console.log(Array.from(u8).join(','));
u16.set([0x7c00, 0xfc00, 0x0001, 0x3c00]); console.log(Array.from(f16, show).join(','));
u16.set([0x03ff, 0x7bff, 0x7e00, 0x8000]); console.log(Array.from(f16, show).join(','));
console.log(Math.f16round ? [Math.f16round(1.337), Math.f16round(65519.99), Math.f16round(65520), Math.f16round(5.960464477539063e-8), Math.f16round(2.9802322387695312e-8), Math.f16round(2.98023223876953125e-8 * 1.0000001)].map(show).join(',') : 'no f16round');
console.log(Math.fround(1.337), Math.fround(16777217), Math.fround(1e-46));
// out-of-range and non-index keys
const t = new Uint8Array(3);
t[5] = 9; t[-1] = 9; t['1.5'] = 9; t.foo = 1; t['-0'] = 3;
console.log(t[5], t[-1], t['1.5'], t.foo, t['-0'], Object.keys(t).join(','), 5 in t, 2 in t, '-0' in t);
console.log(Object.getOwnPropertyNames(new Int16Array(2)).join(','), JSON.stringify(Object.getOwnPropertyDescriptor(new Int8Array([4]), '0')));
console.log(Object.prototype.toString.call(new BigUint64Array(1)), new Float32Array(2)[Symbol.toStringTag], Object.getPrototypeOf(Int8Array).name, Object.getPrototypeOf(Int8Array.prototype) === Object.getPrototypeOf(Float64Array.prototype));
console.log(Int8Array.length, Int8Array.name, Object.getPrototypeOf(Int8Array).prototype[Symbol.toStringTag]);
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_kinds(run, workdir, tier):
    """CATCHES: implementations that get element conversion for every TypedArray kind (Int8 wrap, Uint8Clamped round-half-even, Float16/Float32 rounding, BigInt64 wrapping), aliasing views over one buffer, Float16 bit patterns and BigInt/Number mixing errors wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_KINDS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "kinds")


PROG_CONSTRUCTORS = r"""
const E = (f) => { try { const r = f(); return 'ok ' + (r && r.length !== undefined ? r.constructor.name + '[' + Array.from(r).join(',') + ']' : String(r)); } catch (e) { return e.name + ': ' + e.message; } };
console.log(E(() => new Int16Array()));
console.log(E(() => new Int16Array(3)));
console.log(E(() => new Int16Array('4')));
console.log(E(() => new Int16Array(2.9)));
console.log(E(() => new Int16Array(NaN)));
console.log(E(() => new Int16Array(-1)));
console.log(E(() => new Int16Array(2 ** 53)));
console.log(E(() => new Int16Array(Symbol())));
console.log(E(() => new Int16Array(1n)));
console.log(E(() => new Int16Array(null)));
console.log(E(() => new Int16Array(undefined)));
console.log(E(() => new Int16Array([1, '2', 3.7, null, undefined, {}, [5]])));
console.log(E(() => new Int16Array(new Set([7, 8, 9]))));
console.log(E(() => new Int16Array((function* () { yield 1; yield 2; })())));
console.log(E(() => new Int16Array({ length: 3, 0: 4, 2: 6 })));
console.log(E(() => new Int16Array({ length: -5 })));
console.log(E(() => new Int16Array({ [Symbol.iterator]: 5 })));
console.log(E(() => new Int16Array('abc'.split(''))));
console.log(E(() => new Uint8Array(new Float64Array([1.9, -1, 300]))));
console.log(E(() => new Float64Array(new Uint8ClampedArray([1, 2]))));
console.log(E(() => new BigInt64Array(new Int8Array([1]))));
console.log(E(() => new Int8Array(new BigInt64Array([1n]))));
console.log(E(() => new BigUint64Array(new BigInt64Array([-1n]))));
console.log(E(() => new BigInt64Array([1, 2])));
console.log(E(() => new BigInt64Array(['3', true])));
const buf = new ArrayBuffer(16);
new Uint8Array(buf).forEach((_, i, a) => { a[i] = i; });
console.log(E(() => new Uint8Array(buf, 4)));
console.log(E(() => new Uint8Array(buf, 4, 3)));
console.log(E(() => new Uint16Array(buf, 2, 3)));
console.log(E(() => new Uint16Array(buf, 3)));
console.log(E(() => new Uint32Array(buf, 16)));
console.log(E(() => new Uint32Array(buf, 20)));
console.log(E(() => new Uint32Array(buf, 8, 3)));
console.log(E(() => new Uint32Array(buf, -4)));
console.log(E(() => new Uint32Array(new ArrayBuffer(6))));
console.log(E(() => new Uint16Array(new ArrayBuffer(6), 2)));
console.log(E(() => Uint8Array(4)));
console.log(E(() => { const T = Object.getPrototypeOf(Int8Array); return new T(); }));
console.log(E(() => { const T = Object.getPrototypeOf(Int8Array); return T(); }));
const v = new Int32Array(buf, 4, 2);
console.log(v.length, v.byteLength, v.byteOffset, v.buffer === buf, Array.from(v).join(','));
console.log(E(() => Int8Array.of(1, 2, 300)));
console.log(E(() => Float32Array.from([1, 2, 3], (x, i) => x * 10 + i)));
console.log(E(() => Float32Array.from({ length: 2, 0: 'x' })));
console.log(E(() => Float32Array.from(new Map([[1, 2]]).keys())));
console.log(E(() => Float32Array.from([1], 'nope')));
console.log(E(() => Int8Array.from.call(Object, [1])));
console.log(E(() => Int8Array.of.call(function () { return new Int8Array(1); }, 1, 2)));
console.log(E(() => Int8Array.from.call(undefined, [1])));
class MyTA extends Uint8Array { sum() { return this.reduce((a, b) => a + b, 0); } }
const m = new MyTA([1, 2, 3]);
console.log(m.sum(), m instanceof Uint8Array, m.constructor.name, MyTA.from([4, 5]).sum(), MyTA.of(9).constructor.name, m.map(x => x * 2).constructor.name, m.subarray(1).constructor.name, m.slice(0, 1).sum());
console.log(E(() => Reflect.construct(Uint8Array, [2], Object)), Object.getPrototypeOf(Reflect.construct(Uint8Array, [2], Object)) === Object.prototype);
console.log(Uint8Array.prototype.BYTES_PER_ELEMENT, Object.getOwnPropertyDescriptor(Uint8Array, 'BYTES_PER_ELEMENT').writable, ArrayBuffer.isView(v), ArrayBuffer.isView(new DataView(buf)), ArrayBuffer.isView(buf), ArrayBuffer.isView([]));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_constructors(run, workdir, tier):
    """CATCHES: implementations that get TypedArray constructors from lengths, arrays, iterables, array-likes, other typed arrays and buffers with offsets, plus the exact RangeError/TypeError messages for bad lengths, misaligned offsets and abstract %TypedArray% wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_CONSTRUCTORS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "constructors")


PROG_METHODS = r"""
const S = (a) => a.constructor.name + '[' + Array.from(a, v => Object.is(v, -0) ? '-0' : String(v)).join(',') + ']';
const E = (f) => { try { const r = f(); return r && typeof r === 'object' && 'length' in r ? S(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const a = new Int16Array([5, -3, 9, 0, 9, -7, 2]);
console.log('at', a.at(0), a.at(-1), a.at(-8), a.at(7), a.at('1'), a.at(1.9), a.at(NaN));
console.log('idx', a.indexOf(9), a.indexOf(9, 3), a.indexOf(9, -2), a.lastIndexOf(9), a.lastIndexOf(9, 3), a.lastIndexOf(9, -4), a.indexOf('9'), a.indexOf(9, 100), a.lastIndexOf(9, -100), a.lastIndexOf(5, undefined));
console.log('inc', a.includes(9), a.includes(9, 5), a.includes(-7, -2), a.includes('9'), new Float32Array([NaN]).includes(NaN), new Float32Array([NaN]).indexOf(NaN), new Float64Array([-0]).includes(0), new Int8Array(0).includes(undefined));
console.log('join', a.join(), a.join(' | '), a.join(undefined), new Float64Array([1.5, -0, NaN, 1e21]).join(';'), a.toString(), String(new BigInt64Array([-1n, 2n])), new Uint8Array(0).join('x') === '');
console.log('find', a.find(x => x < 0), a.findIndex(x => x < 0), a.findLast(x => x < 0), a.findLastIndex(x => x < 0), a.find(x => x > 100), a.findIndex(x => x > 100), a.findLastIndex(x => x > 100));
console.log('pred', a.every(x => x > -10), a.some(x => x > 8), a.every(x => x > 0), a.some(x => x > 100));
const seen = []; a.forEach(function (v, i, arr) { seen.push(v + '@' + i + (arr === a) + (this && this.tag)); }, { tag: 'T' }); console.log('forEach', seen.join(' '));
console.log('map', S(a.map(x => x * 10000)), S(new Uint8Array([1, 2]).map(x => x - 3)), S(new BigInt64Array([2n]).map(x => x * x)));
console.log('filter', S(a.filter((x, i) => i % 2 === 0)), S(a.filter(() => false)));
console.log('reduce', a.reduce((s, x) => s + x), a.reduce((s, x) => s + ',' + x, '>'), a.reduceRight((s, x) => s + ',' + x, '<'), a.reduceRight((s, x) => s - x));
console.log('reduce-empty', E(() => new Int8Array(0).reduce((x, y) => x)), E(() => new Int8Array(0).reduceRight((x, y) => x)), new Int8Array(0).reduce((x) => x, 'init'));
console.log('cb-errors', E(() => a.map(1)), E(() => a.forEach()), E(() => a.filter(null)), E(() => a.find('x')), E(() => a.every({})));
const b = Int8Array.of(1, 2, 3, 4, 5, 6);
console.log('copyWithin', S(b.slice().copyWithin(0, 3)), S(b.slice().copyWithin(1, 0, 3)), S(b.slice().copyWithin(-2, 0)), S(b.slice().copyWithin(2, -3, -1)), S(b.slice().copyWithin(0, 4, 100)), S(b.slice().copyWithin(10, 0)), S(b.slice().copyWithin(0, 0)));
console.log('fill', S(b.slice().fill(9)), S(b.slice().fill(7, 2)), S(b.slice().fill(7, -2)), S(b.slice().fill(7, 1, 3)), S(b.slice().fill(7, 3, 1)), S(b.slice().fill('3.9', -100, 100)), S(new BigUint64Array(2).fill(-1n)), E(() => new BigInt64Array(2).fill(1)), S(new Float32Array(2).fill(1 / 3)));
console.log('reverse', S(b.slice().reverse()), S(new Int8Array([1]).reverse()), S(b.toReversed()), S(b));
console.log('slice', S(b.slice(2)), S(b.slice(-2)), S(b.slice(1, -1)), S(b.slice(4, 2)), S(b.slice(-100, 100)), S(b.slice(1.5, 3.5)));
console.log('subarray', S(b.subarray(2)), S(b.subarray(-2)), S(b.subarray(1, -1)), S(b.subarray(4, 2)), b.subarray(2, 4).byteOffset, b.subarray(2).buffer === b.buffer);
const sub = b.subarray(1, 3); sub[0] = 100; console.log('alias', S(b), S(sub));
const f = new Float64Array([3, -0, NaN, -Infinity, 0, 1e-300, -5, NaN, Infinity, 2]);
console.log('sort-default', S(f.slice().sort()), S(f.toSorted()), S(f));
console.log('sort-cmp', S(new Int8Array([3, 1, 2, -1]).sort((x, y) => y - x)), S(new Int8Array([3, 1, 2]).sort(() => NaN)), E(() => new Int8Array([2, 1]).sort('x')), S(new Uint32Array([10, 9, 1, 100]).sort()), S(new BigInt64Array([5n, -10n, 3n]).sort()), S(new BigInt64Array([5n, -10n, 3n]).toSorted((x, y) => (x < y ? 1 : -1))));
const stab = new Int8Array([21, 12, 31, 13, 22, 11]); console.log('stable', S(stab.toSorted((x, y) => (x % 10) - (y % 10))));
try { new Int8Array([3, 2, 1]).sort(() => { throw new Error('cmp boom'); }); } catch (e) { console.log('sort-throw', e.message); }
console.log('with', S(b.with(0, 50)), S(b.with(-1, 60)), E(() => b.with(6, 1)), E(() => b.with(-7, 1)), S(b.with('2', '7')), S(new BigInt64Array(2).with(1, 5n)), E(() => new BigInt64Array(2).with(1, 5)), S(new Uint8ClampedArray([1]).with(0, 300)));
console.log('iter', JSON.stringify([...b.entries()].slice(0, 2)), [...b.keys()].join(','), [...b.values()].join(','), [...b].length, b[Symbol.iterator] === b.values, Object.prototype.toString.call(b.entries()), b.entries().toString());
const it = new Uint8Array([1, 2]).values(); console.log('iter-next', JSON.stringify(it.next()), JSON.stringify(it.next()), JSON.stringify(it.next()), JSON.stringify(it.next()));
console.log('toLocale', new Float64Array([1234.5, 6]).toLocaleString(), new Int8Array(0).toLocaleString() === '', new BigInt64Array([12345n]).toLocaleString());
console.log('set', E(() => { const t = new Int8Array(6); t.set([1, 2, 3]); t.set([9, 9], 4); return t; }), E(() => { const t = new Int8Array(3); t.set([1, 2], 2); return t; }), E(() => new Int8Array(3).set([1], -1)), E(() => { const t = new Int8Array(3); t.set(new Float32Array([1.5, 2.5]), 1); return t; }), E(() => new Int8Array(3).set(new BigInt64Array(1))), E(() => { const t = new Int8Array(3); t.set({ length: 2, 0: 7, 1: 8 }, 1); return t; }), E(() => { const t = new Int8Array(2); t.set('12'); return t; }), E(() => new Int8Array(2).set(5)), E(() => new Int8Array(2).set(null)));
const ov = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]); ov.set(ov.subarray(0, 5), 2); console.log('overlap', S(ov));
const ov2 = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]); new Uint16Array(ov2.buffer).set(ov2.subarray(0, 3)); console.log('overlap2', S(ov2));
const proto = Object.getPrototypeOf(Int8Array.prototype);
console.log('brand', E(() => proto.map.call([1, 2], x => x)), E(() => proto.set.call([], [])), E(() => proto.subarray.call({})), E(() => Object.getOwnPropertyDescriptor(proto, 'length').get.call([])), Object.getOwnPropertyDescriptor(proto, Symbol.toStringTag).get.call([]), E(() => proto.toLocaleString.call([])));
console.log('lengths', ['copyWithin', 'slice', 'subarray', 'with', 'keys', 'entries', 'map', 'set', 'fill', 'at', 'toSorted', 'reverse'].map(n => n + '=' + proto[n].length).join(' '));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_methods(run, workdir, tier):
    """CATCHES: implementations that get the %TypedArray%.prototype methods (at/indexOf/includes/join/find*/map/filter/reduce/copyWithin/fill/sort/toSorted/with/set/subarray/slice/iterators) including negative indices, NaN/-0 ordering, overlapping set and brand-check errors wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_METHODS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "methods")


PROG_RESIZABLE = r"""
const S = (a) => a.constructor.name + '[' + Array.from(a).join(',') + ']';
const E = (f) => { try { const r = f(); return r && typeof r === 'object' && 'length' in r ? S(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const st = (b) => [b.byteLength, b.maxByteLength, b.resizable, b.detached].join('/');
const rab = new ArrayBuffer(8, { maxByteLength: 16 });
console.log('rab', st(rab), Object.prototype.toString.call(rab));
const track = new Uint16Array(rab), fixed = new Uint16Array(rab, 2, 2), trackOff = new Uint8Array(rab, 4);
const dv = new DataView(rab), dvFixed = new DataView(rab, 1, 4);
const L = () => [track.length, fixed.length, trackOff.length, dv.byteLength, E(() => dvFixed.byteLength), track.byteLength, fixed.byteOffset, trackOff.byteOffset].join(' ');
console.log('init', L());
new Uint8Array(rab).set([1, 2, 3, 4, 5, 6, 7, 8]);
rab.resize(12); console.log('grow', st(rab), L(), S(new Uint8Array(rab)));
rab.resize(5); console.log('shrink5', st(rab), L(), S(trackOff), S(track));
rab.resize(3); console.log('shrink3', L(), E(() => fixed[0]), E(() => fixed.fill(1)), E(() => fixed.join()), E(() => trackOff.at(0)), E(() => dvFixed.getInt8(0)), E(() => dv.getInt8(2)), E(() => dv.getInt8(3)));
console.log('oob-methods', E(() => fixed.map(x => x)), E(() => fixed.indexOf(0)), E(() => fixed.sort()), E(() => fixed.set([1])), E(() => fixed.slice()), E(() => fixed.subarray(0)), E(() => fixed.toLocaleString()), E(() => [...fixed]));
rab.resize(16); console.log('regrow', L(), S(fixed));
console.log('resize-errors', E(() => rab.resize(17)), E(() => rab.resize(-1)), E(() => new ArrayBuffer(4).resize(2)), E(() => rab.resize(NaN)), st(rab));
console.log('ctor-errors', E(() => new ArrayBuffer(4, { maxByteLength: 2 })), E(() => new ArrayBuffer(-1)), E(() => new ArrayBuffer(4, { maxByteLength: -1 })), E(() => ArrayBuffer(4)), E(() => st(new ArrayBuffer(4, { maxByteLength: undefined }))), E(() => st(new ArrayBuffer(2.7, {}))), E(() => st(new ArrayBuffer('3', { maxByteLength: '9' }))), E(() => new ArrayBuffer(2 ** 53)));
// slice
const ab = new ArrayBuffer(8); new Uint8Array(ab).set([10, 20, 30, 40, 50, 60, 70, 80]);
console.log('slice', S(new Uint8Array(ab.slice(2))), S(new Uint8Array(ab.slice(-3))), S(new Uint8Array(ab.slice(1, -5))), ab.slice(5, 2).byteLength, ab.slice().resizable, rab.slice(0, 4).resizable, S(new Uint8Array(ab.slice(-100, 100))));
// transfer
const src = new ArrayBuffer(6, { maxByteLength: 32 }); new Uint8Array(src).set([1, 2, 3, 4, 5, 6]);
const view = new Uint8Array(src);
const t1 = src.transfer();
console.log('transfer', st(src), st(t1), S(new Uint8Array(t1)), view.length, view.byteLength, view.byteOffset, E(() => view[0]), E(() => view.fill(0)), E(() => src.slice()), E(() => src.transfer()), E(() => src.resize(1)));
const t2 = t1.transfer(3); console.log('transfer3', st(t2), S(new Uint8Array(t2)));
const t3 = t2.transferToFixedLength(5); console.log('fixed5', st(t3), S(new Uint8Array(t3)));
const t4 = t3.transfer(0); console.log('zero', st(t4), E(() => t3.transfer(-1)), E(() => t4.transfer(2 ** 60)));
console.log('detached-ctor', E(() => new Uint8Array(src)), E(() => new DataView(src)), E(() => new Uint8Array(view)), E(() => Uint8Array.from(view)), E(() => view.subarray(0)));
// immutable
const im = new Uint8Array([1, 2, 3, 4]).buffer.transferToImmutable();
console.log('immutable', im.immutable, im.resizable, im.byteLength, new ArrayBuffer(1).immutable);
const iv = new Uint8Array(im);
iv[0] = 99; console.log('imm-write', iv[0], E(() => iv.fill(0)), E(() => iv.set([5])), E(() => iv.reverse()), E(() => iv.sort()), E(() => iv.copyWithin(0, 1)), E(() => new DataView(im).setInt8(0, 1)), E(() => im.resize(1)), E(() => im.transfer()), E(() => iv.setFromHex('ff')), E(() => Atomics.store(iv, 0, 1)));
console.log('imm-read', S(iv.toSorted((a, b) => b - a)), S(iv.toReversed()), S(iv.with(0, 7)), S(iv.slice(1)), new DataView(im).getUint16(0), Atomics.load(iv, 1));
const sl = new Uint8Array([9, 8, 7, 6]).buffer.sliceToImmutable(1, 3); console.log('sliceToImmutable', sl.immutable, S(new Uint8Array(sl)));
console.log('isView', ArrayBuffer.isView(iv), E(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'byteLength').get.call({})), E(() => ArrayBuffer.prototype.slice.call(new SharedArrayBuffer(2))));
console.log('species', ArrayBuffer[Symbol.species] === ArrayBuffer, E(() => { class X extends ArrayBuffer { static get [Symbol.species]() { return function () { return new ArrayBuffer(1); }; } } return new X(4).slice(0, 4); }), E(() => { class Y extends ArrayBuffer {} const y = new Y(4).slice(1); return y.constructor.name + y.byteLength; }));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_resizable(run, workdir, tier):
    """CATCHES: implementations that get resizable ArrayBuffer length tracking, out-of-bounds views after shrinking, transfer/transferToFixedLength detaching, immutable buffers and ArrayBuffer.prototype.slice semantics wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_RESIZABLE})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "resizable")


PROG_ATOMICS = r"""
const S = (a) => a.constructor.name + '[' + Array.from(a).join(',') + ']';
const E = (f) => { try { const r = f(); return r && typeof r === 'object' && 'length' in r ? S(r) : (typeof r === 'bigint' ? r + 'n' : String(r)); } catch (e) { return e.name + ': ' + e.message; } };
const sab = new SharedArrayBuffer(16);
console.log('sab', sab.byteLength, sab.growable, sab.maxByteLength, Object.prototype.toString.call(sab), sab instanceof ArrayBuffer, ArrayBuffer.isView(sab));
const g = new SharedArrayBuffer(4, { maxByteLength: 12 });
const gv = new Int32Array(g);
console.log('growable', g.byteLength, g.growable, g.maxByteLength, gv.length);
g.grow(8); console.log('grown', g.byteLength, gv.length, E(() => g.grow(4)), E(() => g.grow(13)), E(() => sab.grow(20)), g.byteLength);
console.log('sab-errors', E(() => SharedArrayBuffer(1)), E(() => new SharedArrayBuffer(-1)), E(() => new SharedArrayBuffer(4, { maxByteLength: 2 })), E(() => Object.getOwnPropertyDescriptor(SharedArrayBuffer.prototype, 'byteLength').get.call(new ArrayBuffer(1))), E(() => SharedArrayBuffer.prototype.slice.call(new ArrayBuffer(4))), E(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'byteLength').get.call(sab)));
const su = new Uint8Array(sab); su.set([1, 2, 3, 4, 5, 6, 7, 8]);
const sl = sab.slice(2, 6); console.log('sab-slice', sl.constructor.name, sl.byteLength, S(new Uint8Array(sl)), S(new Uint8Array(sab.slice(-2))));
const i32 = new Int32Array(sab);
i32.fill(0);
console.log('rmw', Atomics.store(i32, 0, 5), Atomics.add(i32, 0, 3), Atomics.sub(i32, 0, 1), Atomics.load(i32, 0), Atomics.and(i32, 0, 6), Atomics.or(i32, 0, 9), Atomics.xor(i32, 0, 3), Atomics.exchange(i32, 0, 42), Atomics.compareExchange(i32, 0, 42, 7), Atomics.compareExchange(i32, 0, 1, 8), Atomics.load(i32, 0));
console.log('wrap', Atomics.store(i32, 1, 2 ** 31), i32[1], Atomics.add(i32, 1, -1), i32[1], Atomics.store(i32, 2, 3.9), Atomics.store(i32, 2, -0), Atomics.store(i32, 2, '12'), Atomics.store(i32, 2, NaN), Atomics.store(i32, 2, Infinity), i32[2]);
const u8 = new Uint8Array(8);
console.log('u8', Atomics.add(u8, 0, 300), u8[0], Atomics.sub(u8, 1, 1), u8[1], Atomics.compareExchange(u8, 1, 511, 3), u8[1], Atomics.exchange(u8, 2, -1), u8[2]);
const i16 = new Int16Array(4); i16[0] = 2979;
console.log('i16', Atomics.compareExchange(i16, 0, 68547, 1), i16[0], Atomics.add(i16, 1, 40000), i16[1], Atomics.or(new Uint16Array([1]), 0, 0x10000 | 6));
const b64 = new BigInt64Array(new SharedArrayBuffer(16));
console.log('big', E(() => Atomics.store(b64, 0, 2n ** 63n)), b64[0] + 'n', E(() => Atomics.add(b64, 0, -1n)), b64[0] + 'n', E(() => Atomics.compareExchange(b64, 1, 0n, 5n)), E(() => Atomics.load(b64, 1)), E(() => Atomics.add(b64, 0, 1)), E(() => Atomics.xor(new BigUint64Array(1), 0, 2n ** 64n + 3n)), E(() => Atomics.sub(new BigUint64Array(1), 0, 1n)));
console.log('errors', E(() => Atomics.add(new Float32Array(2), 0, 1)), E(() => Atomics.load(new Uint8ClampedArray(2), 0)), E(() => Atomics.load([1], 0)), E(() => Atomics.load(i32, 4)), E(() => Atomics.load(i32, -1)), E(() => Atomics.load(i32, 1.7)), E(() => Atomics.load(i32, '1')), E(() => Atomics.store(new Float64Array(1), 0, 1)), E(() => Atomics.load(new Int32Array(new ArrayBuffer(4).transfer(0)), 0)));
console.log('lockfree', [1, 2, 3, 4, 8, 16].map(n => Atomics.isLockFree(n)).join(','));
console.log('wait', E(() => Atomics.wait(i32, 0, 0, 0)), E(() => Atomics.wait(i32, 0, 7, 0)), E(() => Atomics.wait(i32, 0, 7, 1)), E(() => Atomics.wait(new Int32Array(4), 0, 0, 0)), E(() => Atomics.wait(new Int16Array(sab), 0, 0, 0)), E(() => Atomics.wait(b64, 1, 5n, 0)), E(() => Atomics.wait(b64, 1, 0n, 0)), E(() => Atomics.wait(i32, 9, 0, 0)), E(() => Atomics.wait(i32, 0, 7, NaN === NaN ? 0 : 0)));
console.log('notify', Atomics.notify(i32, 0), Atomics.notify(i32, 0, 5), Atomics.notify(new Int32Array(4), 0, 1), E(() => Atomics.notify(new Uint32Array(sab), 0)), E(() => Atomics.notify(i32, 100)), Atomics.notify(b64, 0, -3));
const wa = Atomics.waitAsync(i32, 0, 1, 1000); console.log('waitAsync-ne', wa.async, wa.value);
const wb = Atomics.waitAsync(i32, 0, 8, 0); console.log('waitAsync-0', wb.async, wb.value);
const wc = Atomics.waitAsync(i32, 3, 0, 5000); console.log('waitAsync-pending', wc.async, Object.prototype.toString.call(wc.value));
console.log('notify-one', Atomics.notify(i32, 3, 1));
console.log('waitAsync-errors', E(() => Atomics.waitAsync(new Int32Array(2), 0, 0, 0)), E(() => Atomics.waitAsync(new Float64Array(2), 0, 0, 0)));
console.log('pause', Atomics.pause(), Atomics.pause(3), E(() => Atomics.pause(1.5)), E(() => Atomics.pause('1')), Object.prototype.toString.call(Atomics), typeof Atomics.wait);
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_atomics(run, workdir, tier):
    """CATCHES: implementations that get SharedArrayBuffer growth/slicing and every Atomics operation on Int32/Uint8/Int16/BigInt64 arrays, including wrapping, compareExchange on wrapped values, wait/notify/waitAsync results and the error messages wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_ATOMICS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "atomics")


PROG_DATAVIEW = r"""
const E = (f) => { try { const r = f(); return typeof r === 'bigint' ? r + 'n' : (Object.is(r, -0) ? '-0' : String(r)); } catch (e) { return e.name + ': ' + e.message; } };
const buf = new ArrayBuffer(24);
const dv = new DataView(buf);
const hex = () => Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');
dv.setInt8(0, -2); dv.setUint8(1, 511); dv.setInt16(2, -12345); dv.setInt16(4, -12345, true); dv.setUint16(6, 0xBEEF, false);
dv.setInt32(8, -19088744); dv.setUint32(12, 0xDEADBEEF, true); dv.setFloat32(16, Math.PI); dv.setFloat16(20, 1.5); dv.setFloat16(22, -65504, true);
console.log(hex());
console.log([dv.getInt8(0), dv.getUint8(0), dv.getUint8(1), dv.getInt16(2), dv.getInt16(2, true), dv.getUint16(4), dv.getUint16(4, true), dv.getUint16(6), dv.getInt32(8), dv.getUint32(8), dv.getInt32(12, true), dv.getUint32(12, true), dv.getUint32(12), dv.getFloat32(16), dv.getFloat32(16, true), dv.getFloat16(20), dv.getFloat16(22, true), dv.getFloat16(22)].join(' '));
dv.setFloat64(0, -1e-310); console.log(hex().slice(0, 16), dv.getFloat64(0), dv.getFloat64(0, true), dv.getBigInt64(0), dv.getBigUint64(0, true));
dv.setBigInt64(8, -2n); dv.setBigUint64(16, 2n ** 64n + 0x0102030405060708n, true);
console.log(hex().slice(16), dv.getBigInt64(8), dv.getBigUint64(8), dv.getBigInt64(16, true), dv.getBigInt64(16), dv.getFloat64(16));
dv.setFloat32(0, NaN); dv.setFloat16(4, 1e-7); dv.setFloat16(6, 65520); dv.setFloat32(8, 1e40); dv.setFloat64(16, -0);
console.log(hex(), E(() => dv.getFloat16(4)), E(() => dv.getFloat64(16)), E(() => dv.getFloat32(0)));
console.log('coerce', E(() => dv.setUint8(0, '0x41')), dv.getUint8(0), E(() => dv.getUint8('1')), E(() => dv.getUint8(1.9)), E(() => dv.getUint8(NaN)), E(() => dv.setInt16(0, 70000)), dv.getInt16(0), E(() => dv.setUint32(0, -1)), dv.getUint32(0), E(() => dv.setUint8(0)), dv.getUint8(0));
console.log('bounds', E(() => dv.getInt8(24)), E(() => dv.getInt16(23)), E(() => dv.getFloat64(17)), E(() => dv.getInt8(-1)), E(() => dv.setInt32(21, 0)), E(() => dv.getBigInt64(20)), E(() => dv.setBigUint64(17, 0n)), E(() => dv.getUint8(Infinity)), E(() => dv.getFloat16(23)));
console.log('types', E(() => dv.setBigInt64(0, 1)), E(() => dv.setBigInt64(0, '12')), dv.getBigInt64(0), E(() => dv.setInt8(0, 1n)), E(() => dv.setBigUint64(0, true)), dv.getBigUint64(0), E(() => dv.setBigInt64(0, Symbol())));
const sub = new DataView(buf, 4, 8);
console.log('sub', sub.byteOffset, sub.byteLength, sub.buffer === buf, E(() => sub.getInt8(8)), sub.getUint8(0) === dv.getUint8(4), new DataView(buf, 24).byteLength, new DataView(buf, 3).byteLength, Object.prototype.toString.call(sub));
console.log('ctor', E(() => new DataView(buf, 25)), E(() => new DataView(buf, 4, 21)), E(() => new DataView(buf, -1)), E(() => new DataView({})), E(() => new DataView(new Uint8Array(4))), E(() => DataView(buf)), E(() => new DataView(buf, 0, -1)), E(() => new DataView(new SharedArrayBuffer(4)).byteLength), E(() => new DataView(buf, '2', '3').byteLength));
console.log('brand', E(() => DataView.prototype.getInt8.call(new Uint8Array(4), 0)), E(() => Object.getOwnPropertyDescriptor(DataView.prototype, 'byteLength').get.call({})), E(() => Object.getOwnPropertyDescriptor(DataView.prototype, 'buffer').get.call(buf)), E(() => DataView.prototype.setFloat32.call(1, 0, 1)));
const det = new ArrayBuffer(8); const ddv = new DataView(det); det.transfer();
console.log('detached', E(() => ddv.byteLength), E(() => ddv.byteOffset), E(() => ddv.getInt8(0)), E(() => ddv.setInt8(0, 1)), ddv.buffer === det, E(() => ddv.getBigInt64(0)));
const r = new ArrayBuffer(4, { maxByteLength: 8 }); const tdv = new DataView(r, 2); const fdv = new DataView(r, 0, 4);
r.resize(8); console.log('rab', tdv.byteLength, fdv.byteLength, E(() => tdv.setUint16(4, 0x1234)), tdv.getUint16(4));
r.resize(1); console.log('rab-shrunk', E(() => tdv.byteLength), E(() => fdv.getInt8(0)), E(() => tdv.byteOffset), E(() => new DataView(r, 2)));
console.log('lengths', ['getInt8', 'setInt8', 'getFloat16', 'setFloat16', 'getBigInt64', 'setBigUint64'].map(n => DataView.prototype[n].length).join(','), DataView.length);
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_dataview(run, workdir, tier):
    """CATCHES: implementations that get DataView getters/setters of every width in both endiannesses (incl. Float16 and BigInt64), coercions, bounds/constructor/brand errors, detached and resizable-buffer DataViews wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_DATAVIEW})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "dataview")


PROG_BASE64 = r"""
const S = (a) => '[' + Array.from(a).join(',') + ']';
const E = (f) => { try { const r = f(); return r instanceof Uint8Array ? S(r) : (r && typeof r === 'object' ? JSON.stringify(r) : String(r)); } catch (e) { return e.name + ': ' + e.message; } };
const bytes = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255, 62, 63]);
for (let n = 0; n <= 5; n++) {
  const b = bytes.subarray(0, n + 6);
  console.log('enc', n + 6, b.toBase64(), b.toBase64({ alphabet: 'base64url' }), b.toBase64({ omitPadding: true }), b.toBase64({ alphabet: 'base64url', omitPadding: 1 }), b.toHex());
}
console.log('enc-empty', JSON.stringify(new Uint8Array(0).toBase64()), JSON.stringify(new Uint8Array(0).toHex()));
console.log('enc-errors', E(() => bytes.toBase64({ alphabet: 'base32' })), E(() => bytes.toBase64('x')), E(() => bytes.toBase64(null)), E(() => Uint8Array.prototype.toBase64.call(new Int8Array(2))), E(() => Uint8Array.prototype.toHex.call([])), E(() => Uint8Array.prototype.toHex.call(new Uint16Array(1))));
const dec = (s, o) => E(() => Uint8Array.fromBase64(s, o));
console.log('dec', dec('AAEC+vv8/f7/Pj8='), dec('AAEC-vv8_f7_Pj8', { alphabet: 'base64url' }), dec('AAEC+vv8/f7/Pj8', { alphabet: 'base64url' }), dec(' Q U\tJD\nRA==\r '), dec('QUJD'), dec('QUI='), dec('QUI'), dec('QQ'), dec('Q'), dec('QQ=='), dec('QQ='), dec('QQ==='), dec('QQ==QQ=='), dec('Q===') );
for (const h of ['loose', 'strict', 'stop-before-partial']) {
  console.log('handling', h, dec('QUJDRA', { lastChunkHandling: h }), dec('QUJDRA==', { lastChunkHandling: h }), dec('QUJDRB==', { lastChunkHandling: h }), dec('QUJDRA=', { lastChunkHandling: h }), dec('QUJDR', { lastChunkHandling: h }), dec('QUJDRUY', { lastChunkHandling: h }), dec('QUJDRUZ=', { lastChunkHandling: h }), dec('', { lastChunkHandling: h }));
}
console.log('dec-errors', dec(42), dec('QU*J'), dec('QUJD', { lastChunkHandling: 'lax' }), dec('QUJD', { alphabet: 'hex' }), dec('QUJD', 5), dec('QU=J'), dec('=QUJ'), dec('QUJé'));
const hx = (s) => E(() => Uint8Array.fromHex(s));
console.log('hex', hx('00ff7fA0bC'), hx(''), hx('abc'), hx('zz'), hx('0g'), hx(' 00'), hx(12), hx('DEADbeef'));
const t = new Uint8Array(6);
console.log('setFromHex', E(() => t.setFromHex('0102')), S(t), E(() => t.setFromHex('aabbccddeeff0011')), S(t), E(() => t.setFromHex('1122zz')), S(t), E(() => t.setFromHex('123')), E(() => t.setFromHex(5)), E(() => t.subarray(4).setFromHex('9999')), S(t));
const u = new Uint8Array(7);
console.log('setFromBase64', E(() => u.setFromBase64('QUJDREVG')), S(u), E(() => u.fill(0).setFromBase64('QUJDREVGR0hJ')), S(u), E(() => u.fill(0).setFromBase64('QUJDRA==')), E(() => u.fill(0).setFromBase64('QUJD*A==')), S(u), E(() => u.fill(0).setFromBase64('QUJDRA', { lastChunkHandling: 'stop-before-partial' })), S(u), E(() => u.fill(0).setFromBase64('QUJDREVGRw==')), S(u), E(() => new Uint8Array(1).setFromBase64('QUJD')), E(() => new Uint8Array(2).setFromBase64('QUJD')), E(() => new Uint8Array(0).setFromBase64('QUJD')), E(() => u.setFromBase64('-_-_', { alphabet: 'base64url' })), S(u));
console.log('set-errors', E(() => u.setFromBase64(null)), E(() => Uint8Array.prototype.setFromBase64.call(new Int8Array(3), 'AA==')), E(() => Uint8Array.prototype.setFromHex.call({}, '00')));
const big = new Uint8Array(300).map((_, i) => (i * 37) & 255);
const enc = big.toBase64();
console.log('roundtrip', enc.length, enc.slice(0, 40), Uint8Array.fromBase64(enc).every((v, i) => v === big[i]), Uint8Array.fromHex(big.toHex()).length, btoa(String.fromCharCode(...big)) === enc);
console.log('lengths', Uint8Array.fromBase64.length, Uint8Array.fromHex.length, Uint8Array.prototype.toBase64.length, Uint8Array.prototype.setFromBase64.length, typeof Int8Array.fromBase64, typeof Uint8Array.prototype.toHex);
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_base64(run, workdir, tier):
    """CATCHES: implementations that get Uint8Array toBase64/fromBase64/toHex/fromHex/setFromBase64/setFromHex with alphabet, omitPadding and lastChunkHandling options, partial writes and the exact errors wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_BASE64})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "base64")


PROG_BIGINT = r"""
const E = (f) => { try { const r = f(); return typeof r === 'bigint' ? r + 'n' : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const a = 2n ** 200n + 12345678901234567890n, b = -(3n ** 77n), c = 98765432109876543210987654321n;
console.log('mul', a * b, b * b, c * c * c, -1n * 0n, (2n ** 64n - 1n) * (2n ** 64n - 1n));
console.log('div', a / c, a % c, b / c, b % c, -7n / 2n, -7n % 2n, 7n / -2n, 7n % -2n, c / c, (c * c + 5n) / c, (c * c + 5n) % c, 1n / 3n, (2n ** 128n) / (2n ** 64n + 1n), (2n ** 128n) % (2n ** 64n + 1n));
console.log('pow', 2n ** 0n, (-2n) ** 63n, (-3n) ** 4n, 0n ** 0n, 10n ** 40n, E(() => 2n ** -1n), 1n ** 1000000n, (-1n) ** 1000001n);
console.log('divzero', E(() => 1n / 0n), E(() => 1n % 0n), E(() => 0n / 0n));
console.log('shift', 1n << 100n, a >> 150n, b >> 3n, b >> 1000n, (-1n) >> 5n, 5n << -1n, 5n >> -2n, -5n >> 1n, -5n << 0n, 255n >> 4n, (2n ** 64n) >> 64n, -(2n ** 64n) >> 63n, 1n >> 64n, E(() => 1n << (2n ** 40n)));
console.log('bitwise', 12n & 10n, 12n | 10n, 12n ^ 10n, ~12n, ~-1n, -12n & 10n, -12n | 10n, -12n ^ 10n, -12n & -10n, -12n | -10n, (2n ** 70n - 1n) & -(2n ** 64n), b & 0xFFFFn, b | 1n, b ^ -1n);
console.log('asN', BigInt.asIntN(8, 255n), BigInt.asIntN(8, 128n), BigInt.asIntN(8, -129n), BigInt.asUintN(8, -1n), BigInt.asUintN(64, -1n), BigInt.asIntN(64, 2n ** 63n), BigInt.asIntN(0, 5n), BigInt.asUintN(0, 5n), BigInt.asIntN(1, 1n), BigInt.asIntN(200, b), BigInt.asUintN(100, b), BigInt.asIntN(65, 2n ** 64n), E(() => BigInt.asIntN(-1, 1n)), E(() => BigInt.asUintN(8, 1)), BigInt.asUintN('3', 15n), BigInt.asIntN(2 ** 30, 7n), E(() => BigInt.asUintN(2 ** 30, -1n)));
console.log('radix', a.toString(16), b.toString(36), c.toString(2).length, (255n).toString(2), (-255n).toString(16), (0n).toString(7), E(() => (1n).toString(1)), E(() => (1n).toString(37)), (35n).toString(36), (-(2n ** 64n)).toString(32));
console.log('ctor', BigInt(' 0x1F '), BigInt('0b101'), BigInt('0o17'), BigInt('-123'), BigInt('+77'), BigInt(''), BigInt('  '), BigInt(true), BigInt(false), BigInt(2 ** 60), BigInt(-0), BigInt(Number.MAX_SAFE_INTEGER), BigInt(1e21), BigInt(Number.MAX_VALUE).toString().length, BigInt({ valueOf() { return 42; } }), BigInt('9'.repeat(40)));
console.log('ctor-errors', E(() => BigInt(1.5)), E(() => BigInt(NaN)), E(() => BigInt(Infinity)), E(() => BigInt('1.5')), E(() => BigInt('0x')), E(() => BigInt('-0x10')), E(() => BigInt('1n')), E(() => BigInt('1e3')), E(() => BigInt(undefined)), E(() => BigInt(null)), E(() => BigInt(Symbol('s'))), E(() => new BigInt(1)), E(() => BigInt('12a')), E(() => BigInt()));
console.log('mixing', E(() => 1n + 1), E(() => 1n * 2.5), E(() => 1 - 1n), E(() => 2n ** 2), E(() => 1n >>> 1n), E(() => +1n), E(() => Math.max(1n)), E(() => 1n | 0), E(() => 1n < 2), E(() => 2n > '1'), E(() => 1n == 1), E(() => 1n === 1), E(() => 0n == ''), E(() => 1n == '1'), E(() => 2n ** 64n > Number.MAX_SAFE_INTEGER), E(() => 1n < 1.5), E(() => 9007199254740993n > 9007199254740992), E(() => 1n < NaN), E(() => 1n + '2'), E(() => `${-5n}`), E(() => 5n + true));
console.log('unary', -(-5n), -0n, typeof 1n, typeof Object(1n), Object(1n) + 1n, !!0n, !!1n, 0n ? 'T' : 'F', [3n, 1n, 2n].sort().join(), [10n, 9n, -1n].sort((x, y) => (x < y ? -1 : 1)).join());
let x = 5n; x++; x += 10n; x **= 2n; x--; x >>= 1n; x %= 7n; console.log('compound', x, (() => { let y = -3n; y--; return y; })());
console.log('number', Number(2n ** 53n + 1n), Number(2n ** 1024n), Number(-(2n ** 1024n)), Number(2n ** 1023n * 3n / 2n), Number(123456789012345678901234567890n), parseInt('123n'), Number(-(2n ** 63n)), Number(2n ** 54n + 3n), Number(2n ** 54n + 2n), Number(2n ** 54n + 6n));
console.log('misc', (12345678901234567890n).toLocaleString('en-US'), BigInt.prototype.valueOf.call(Object(9n)), E(() => BigInt.prototype.toString.call(1)), E(() => BigInt.prototype.valueOf.call('1')), Object.prototype.toString.call(1n), JSON.stringify({ v: typeof 1n }), E(() => JSON.stringify(1n)), new Map([[1n, 'a']]).get(1n), new Set([1n, 1n, 2n]).size, [0n, -0n].includes(0n), Object.is(0n, -0n));
let big = 1n; for (let i = 1n; i <= 60n; i++) big *= i;
console.log('fact60', big, big.toString().length, big % 1000000007n, big / (2n ** 100n));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_bigint(run, workdir, tier):
    """CATCHES: implementations that get BigInt arithmetic on multi-limb values (division/remainder signs, pow, shifts with negative counts, two's-complement bitwise ops), asIntN/asUintN, radix strings, BigInt() parsing errors and BigInt/Number mixing rules wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_BIGINT})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "bigint")


PROG_NUMBER_FORMAT = r"""
const E = (f) => { try { return String(f()); } catch (e) { return e.name + ': ' + e.message; } };
const vals = [0, -0, 1, -1, 0.1, 0.1 + 0.2, 1 / 3, 2 / 3, 5e-324, 2.2250738585072014e-308, 1.7976931348623157e308, 1e21, 1e20, 123456789012345680000, 1e-6, 1e-7, 1.5e-7, 0.000001234, 9007199254740993, 4.35, 1.005, 123.456, -1e-10, 100, 1e100, 2 ** 70, 0.5, 25e-5, 1.2345678901234567e-30, Math.PI * 1e15, Math.E * 1e16, 1e300 * 10, NaN, -Infinity];
console.log(vals.map(String).join(' '));
console.log('fixed', [[0, 2], [1.005, 2], [1.45, 1], [0.5, 0], [1.5, 0], [2.5, 0], [-2.5, 0], [-0.0000001, 2], [1e21, 2], [1.23e20, 2], [123.456, 10], [0.1, 20], [5e-324, 3], [-1.5, 0], [999.995, 2], [1234.5678, undefined]].map(([v, d]) => v.toFixed(d)).join(' '));
console.log('fixed-err', E(() => (1).toFixed(101)), E(() => (1).toFixed(-1)), (1).toFixed(100).length, E(() => (NaN).toFixed(2)), E(() => Infinity.toFixed(1)), (12.5).toFixed(NaN), (12.34).toFixed('1'));
console.log('exp', [[0, undefined], [0, 2], [123456, 2], [123456, undefined], [1.5e-10, 3], [-1e21, 1], [5e-324, undefined], [1.7976931348623157e308, 5], [1.25, 1], [1.35, 1], [0.000123, 0], [9.995, 2], [1, 20]].map(([v, d]) => v.toExponential(d)).join(' '));
console.log('exp-err', E(() => (1).toExponential(101)), E(() => (1).toExponential(-1)), (NaN).toExponential(200), (-Infinity).toExponential(500), E(() => (1).toExponential(Infinity)));
console.log('prec', [[0, 1], [0, 5], [123.456, 1], [123.456, 2], [123.456, 3], [123.456, 7], [0.000123, 2], [1e-7, 3], [1e21, 3], [1.5e-7, 1], [99.99, 3], [-0.5, 1], [123456789, 21], [5e-324, 2], [1e6, 6], [1e6, 7], [3.5, 1], [2.45, 2], [0.00001, 1]].map(([v, d]) => v.toPrecision(d)).join(' '));
console.log('prec-err', E(() => (1).toPrecision(0)), E(() => (1).toPrecision(101)), (1).toPrecision(undefined), (NaN).toPrecision(0), (Infinity).toPrecision(1000));
console.log('radix', (255).toString(16), (255).toString(2), (-255).toString(36), (0.5).toString(2), (3.75).toString(16), (-0).toString(2), (2 ** 53).toString(7), (0.1).toString(16), Math.PI.toString(16), (255.5).toString(16), (-0.75).toString(4), (1 / 3).toString(3), (NaN).toString(16), (-Infinity).toString(2), (123.456).toString(8), (1e-7).toString(16), E(() => (1).toString(1)), E(() => (1).toString(37)), (10).toString(undefined), E(() => (10).toString(NaN)));
console.log('parse', Number('0x1F'), Number('0b11'), Number('0o17'), Number('  12  '), Number(''), Number('1e1000'), Number('-1e-1000'), Number('1_000'), Number('.5'), Number('5.'), Number('+.5e+2'), Number('Infinity'), Number('-Infinity'), Number('infinity'), Number('0x'), Number('-0x10'), Number(null), Number([]), Number(['7']), Number([1, 2]), Number({}), Number(true), Number(' 12 '));
console.log('parseFloat', parseFloat('3.14abc'), parseFloat('.5.5'), parseFloat('-0'), Object.is(parseFloat('-0'), -0), parseFloat('1e'), parseFloat('1e+'), parseFloat('Infinityx'), parseFloat('0x10'), parseFloat('  -12.5e-3xyz'), parseFloat('9'.repeat(400)), parseFloat('1' + '0'.repeat(400) + 'e-400'));
console.log('parseInt', parseInt('0x1f'), parseInt('1f', 16), parseInt('z', 36), parseInt('12', 3), parseInt('9', 8), parseInt('-0'), parseInt('  +42abc'), parseInt('1e3'), parseInt(0.0000005), parseInt('123', 0), parseInt('123', 1), parseInt('123', 37), parseInt('11', 2.9), parseInt('9007199254740993'), parseInt('ffffffffffffffffff', 16));
console.log('roundtrip', [0.1, 0.2, 0.3, 1 / 7, 123e-20, 5e-324, 1.7976931348623157e308, 4.9406564584124654e-324, 2 ** -1074 * 3, 9.5367431640625e-7, 1.0000000000000002, 0.9999999999999999].every(v => Number(String(v)) === v), String(4.9406564584124654e-324), String(2 ** -1074 * 3), 1.0000000000000002, 0.9999999999999999, 1e23, 8.41e21, 5e-7, 123e-20);
console.log('locale', (1234567.891).toLocaleString(), (-0.5).toLocaleString(), (1e21).toLocaleString('en-US'), (NaN).toLocaleString());
console.log('consts', Number.MAX_SAFE_INTEGER, Number.MIN_SAFE_INTEGER, Number.EPSILON, Number.MIN_VALUE, Number.MAX_VALUE, Number.isInteger(5.0), Number.isSafeInteger(2 ** 53), Number.isNaN('NaN'), isNaN('NaN'), Number.isFinite('1'), isFinite('1'), Number.parseFloat === parseFloat, Number.parseInt === parseInt);
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_number_format(run, workdir, tier):
    """CATCHES: implementations that get Number-to-string conversion: shortest round-trip doubles, exponent thresholds, toFixed/toExponential/toPrecision rounding and range errors, radix strings and Number/parseFloat/parseInt parsing wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_NUMBER_FORMAT})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "number_format")


PROG_DETACH_DURING_COERCION = r"""
const S = (a) => a.constructor.name + '[' + Array.from(a).join(',') + ']';
const E = (f) => { try { const r = f(); return r && typeof r === 'object' && 'length' in r ? S(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const mk = (n = 4) => { const b = new ArrayBuffer(n * 2, { maxByteLength: 64 }); const t = new Int16Array(b, 0, n); t.set([1, 2, 3, 4].slice(0, n)); return [b, t]; };
const detacher = (b, ret = 0) => ({ valueOf() { b.transfer(); return ret; } });
const shrinker = (b, n, ret = 0) => ({ valueOf() { b.resize(n); return ret; } });
let b, t;
[b, t] = mk(); console.log('fill-detach', E(() => t.fill(detacher(b, 7))));
[b, t] = mk(); console.log('fill-shrink', E(() => t.fill(9, shrinker(b, 4))), E(() => S(new Int16Array(b))));
[b, t] = mk(); console.log('includes-detach', t.includes(undefined), E(() => t.includes(undefined, detacher(b))), E(() => t.length));
[b, t] = mk(); console.log('indexOf-detach', E(() => t.indexOf(0, detacher(b))), E(() => t.lastIndexOf(0, detacher(b))));
[b, t] = mk(); console.log('indexOf-shrink', E(() => t.indexOf(0, shrinker(b, 2))));
[b, t] = mk(); console.log('copyWithin-shrink', E(() => t.copyWithin(0, shrinker(b, 6, 1))), S(new Int16Array(b)));
[b, t] = mk(); console.log('copyWithin-detach', E(() => t.copyWithin(detacher(b), 1)));
[b, t] = mk(); console.log('set-detach', E(() => t.set([1], detacher(b))));
[b, t] = mk(); console.log('set-src-oob', E(() => { const [b2, t2] = mk(); b2.resize(0); return t.set(t2); }));
[b, t] = mk(); console.log('with-detach', E(() => t.with(0, detacher(b, 5))));
[b, t] = mk(); console.log('with-shrink', E(() => t.with(3, shrinker(b, 4, 5))));
[b, t] = mk(); console.log('at-shrink', E(() => t.at(shrinker(b, 8, 1))));
[b, t] = mk(); let calls = 0; console.log('map-detach', E(() => t.map((v, i) => { if (i === 1) b.transfer(); calls++; return v; })), calls);
[b, t] = mk(); console.log('forEach-shrink', E(() => { const seen = []; t.forEach((v, i) => { if (i === 0) b.resize(4); seen.push(v); }); return seen.join('|'); }));
[b, t] = mk(); console.log('find-detach', E(() => t.findIndex((v, i) => { if (i === 0) b.transfer(); return v === undefined; })), E(() => t.findLast(v => v === undefined)));
[b, t] = mk(); console.log('reduce-shrink', E(() => t.reduce((acc, v, i) => { if (i === 1) b.resize(2); return acc + ':' + v; }, 's')));
[b, t] = mk(); console.log('join-detach', E(() => t.join({ toString() { b.transfer(); return '-'; } })));
[b, t] = mk(); console.log('slice-species-detach', E(() => { t.constructor = { [Symbol.species]: function (n) { b.transfer(); return new Int16Array(n); } }; return t.slice(1); }));
[b, t] = mk(); console.log('slice-species-shrink', E(() => { t.constructor = { [Symbol.species]: function (n) { b.resize(4); return new Int16Array(n); } }; return t.slice(0); }));
[b, t] = mk(); console.log('subarray-detach', E(() => t.subarray(detacher(b))), E(() => t.subarray(0, 1)));
[b, t] = mk(); console.log('toLocale-shrink', E(() => { Number.prototype.toLocaleString = function () { b.resize(2); return 'n' + this; }; return t.toLocaleString(); }));
delete Number.prototype.toLocaleString;
[b, t] = mk(); console.log('dv-detach', E(() => new DataView(b).getInt16(detacher(b))), E(() => { const [b3] = mk(); return new DataView(b3).setInt16(0, detacher(b3)); }));
[b, t] = mk(); console.log('ta-ctor-detach', E(() => new Int16Array(b, detacher(b))), E(() => { const [b4] = mk(); return new Int16Array(b4, 0, detacher(b4, 1)); }));
const sab = new SharedArrayBuffer(8); const i32 = new Int32Array(sab);
[b, t] = mk(); const ia = new Int32Array(b);
console.log('atomics-detach', E(() => Atomics.add(ia, 0, detacher(b, 1))), E(() => { const [b5] = mk(); return Atomics.store(new Int32Array(b5), 0, shrinker(b5, 0, 3)); }), E(() => { const [b6] = mk(); return Atomics.load(new Int32Array(b6), detacher(b6)); }));
[b, t] = mk(); console.log('ab-slice-species-detach', E(() => { const src = new ArrayBuffer(4); src.constructor = { [Symbol.species]: function (n) { src.transfer(); return new ArrayBuffer(n); } }; return src.slice(0, 2).byteLength; }), E(() => { const src = new ArrayBuffer(4, { maxByteLength: 8 }); new Uint8Array(src).set([1, 2, 3, 4]); src.constructor = { [Symbol.species]: function (n) { src.resize(1); return new ArrayBuffer(n); } }; return S(new Uint8Array(src.slice(0, 3))); }), E(() => { const src = new ArrayBuffer(4); src.constructor = { [Symbol.species]: function (n) { return new ArrayBuffer(n).transferToImmutable(); } }; return src.slice(0, 2); }));
console.log('ab-slice-species-errors', E(() => { const a = new ArrayBuffer(4); a.constructor = { [Symbol.species]: function () { return a; } }; return a.slice(); }), E(() => { const a = new ArrayBuffer(4); a.constructor = { [Symbol.species]: function () { return {}; } }; return a.slice(); }), E(() => { const a = new ArrayBuffer(4); a.constructor = { [Symbol.species]: function () { return new SharedArrayBuffer(4); } }; return a.slice(); }), E(() => { const a = new ArrayBuffer(4); a.constructor = { [Symbol.species]: function () { const x = new ArrayBuffer(4); x.transfer(); return x; } }; return a.slice(); }), E(() => { const a = new ArrayBuffer(4); a.constructor = 5; return a.slice(); }));
console.log('ta-species-errors', E(() => { const x = new Int8Array(4); x.constructor = 5; return x.map(v => v); }), E(() => { const x = new Int8Array(4); x.constructor = { [Symbol.species]: 5 }; return x.slice(); }), E(() => { const x = new Int8Array(4); x.constructor = { [Symbol.species]: function () { return new Int8Array(1); } }; return x.filter(() => true); }), E(() => { const x = new Int8Array(4); x.constructor = { [Symbol.species]: function () { return [1, 2, 3, 4]; } }; return x.map(v => v); }), E(() => { const x = new Int8Array([1, 2]); x.constructor = { [Symbol.species]: function (n) { return new Float64Array(n); } }; return x.slice(); }), E(() => { const x = new Int8Array([1, 2]); x.constructor = { [Symbol.species]: function (n) { return new BigInt64Array(n); } }; return x.slice(); }), E(() => { const x = new Int8Array([5, 6]); x.constructor = undefined; return x.map(v => v * 2); }), E(() => { const x = new Int8Array([5, 6, 7]); x.constructor = { [Symbol.species]: null }; return x.subarray(1); }));
console.log('ta-species-ok', E(() => { class Sub extends Uint8Array { static get [Symbol.species]() { return Uint16Array; } } const s = new Sub([1, 2, 3]); return [S(s.map(v => v * 300)), S(s.filter(v => v > 1)), S(s.slice(1)), E(() => s.subarray(1)), S(s.subarray(0, 2)), S(s.toSorted()), S(s.toReversed()), S(s.with(0, 9))].join(' '); }));
console.log('ta-species-immutable', E(() => { const im = new ArrayBuffer(8).transferToImmutable(); const x = new Uint8Array(4); x.constructor = { [Symbol.species]: function (n) { return new Uint8Array(im, 0, n); } }; return x.slice(); }));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_detach_during_coercion(run, workdir, tier):
    """CATCHES: implementations that get TypedArray/DataView/Atomics/ArrayBuffer methods whose argument coercion or callbacks detach or shrink the buffer mid-operation, and TypedArraySpeciesCreate / ArrayBuffer species validation errors wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_DETACH_DURING_COERCION})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "detach_during_coercion")


PROG_BUFFER_EXTRAS = r"""
const S = (a) => a.constructor.name + '[' + Array.from(a).join(',') + ']';
const E = (f) => { try { const r = f(); return r && typeof r === 'object' && 'length' in r ? S(r) : (typeof r === 'bigint' ? r + 'n' : String(r)); } catch (e) { return e.name + ': ' + e.message; } };
const sab = new SharedArrayBuffer(8); new Uint8Array(sab).set([1, 2, 3, 4, 5, 6, 7, 8]);
console.log('sab-species', E(() => { sab.constructor = { [Symbol.species]: function () { return sab; } }; return sab.slice(0, 2); }), E(() => { sab.constructor = { [Symbol.species]: function () { return new ArrayBuffer(4); } }; return sab.slice(0, 2); }), E(() => { sab.constructor = { [Symbol.species]: function () { return new SharedArrayBuffer(1); } }; return sab.slice(0, 2); }), E(() => { sab.constructor = { [Symbol.species]: function (n) { return new SharedArrayBuffer(n + 2); } }; return S(new Uint8Array(sab.slice(-3))); }));
delete sab.constructor;
const sv8 = new Uint8Array(sab), sv32 = new Int32Array(sab), sdv = new DataView(sab);
sv32[1] = -1; sdv.setInt16(0, 0x1234);
console.log('sab-views', S(sv8), sdv.getUint32(4), sdv.getInt8(1), Atomics.add(sv8, 0, 1), sv8[0], new Int16Array(sab, 2, 1)[0]);
const big = new BigInt64Array(new SharedArrayBuffer(16));
console.log('sab-big', Atomics.store(big, 1, -7n), Atomics.compareExchange(big, 1, -7n, 9n), big[1], Atomics.exchange(big, 0, 3n), Atomics.and(big, 0, 1n), Atomics.or(big, 0, 6n), Atomics.load(big, 0), Atomics.wait(big, 0, 0n, 0), Atomics.notify(big, 0));
const wa = Atomics.waitAsync(sv32, 0, sv32[0]); console.log('waitAsync-inf', wa.async, Object.prototype.toString.call(wa.value), Atomics.notify(sv32, 0, 0));
console.log('ab-alloc', E(() => new ArrayBuffer(1, { maxByteLength: 2 ** 40 })), E(() => new SharedArrayBuffer(1, { maxByteLength: 2 ** 40 })), E(() => new ArrayBuffer(1, { get maxByteLength() { throw new Error('getter'); } })), E(() => new ArrayBuffer({ valueOf() { return 3; } }).byteLength), E(() => new ArrayBuffer(Infinity)));
const rab = new ArrayBuffer(8, { maxByteLength: 16 }); new Uint8Array(rab).set([1, 2, 3, 4, 5, 6, 7, 8]);
console.log('sliceToImmutable', E(() => S(new Uint8Array(rab.sliceToImmutable(-3)))), E(() => rab.sliceToImmutable(0, { valueOf() { rab.resize(2); return 6; } })), rab.byteLength, E(() => { const x = new ArrayBuffer(2); x.transfer(); return x.sliceToImmutable(); }), E(() => S(new Uint8Array(rab.sliceToImmutable(1, 0)))));
console.log('resize-coerce', E(() => { const r = new ArrayBuffer(2, { maxByteLength: 4 }); return r.resize({ valueOf() { r.transfer(); return 1; } }); }), E(() => { const r = new ArrayBuffer(2, { maxByteLength: 4 }); return r.transfer({ valueOf() { r.transfer(); return 1; } }); }), E(() => { const r = new ArrayBuffer(2, { maxByteLength: 4 }); r.resize(4.9); return r.byteLength; }));
console.log('accessors', E(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'detached').get.call(sab)), E(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'resizable').get.call({})), E(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'maxByteLength').get.call(1)), E(() => Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'immutable').get.call({})), E(() => Object.getOwnPropertyDescriptor(SharedArrayBuffer.prototype, 'growable').get.call(new ArrayBuffer(1))), E(() => ArrayBuffer.prototype.transfer.call(sab)), E(() => ArrayBuffer.prototype.resize.call(5, 1)), E(() => SharedArrayBuffer.prototype.grow.call(new SharedArrayBuffer(1), 2)));
function F() {} F.prototype = 1;
const viaF = Reflect.construct(Uint8Array, [2], F);
console.log('realm-proto', Object.getPrototypeOf(viaF) === Uint8Array.prototype, viaF.length, Object.getPrototypeOf(Reflect.construct(DataView, [new ArrayBuffer(1)], F)) === DataView.prototype, Object.getPrototypeOf(Reflect.construct(ArrayBuffer, [1], F)) === ArrayBuffer.prototype);
const origIter = Array.prototype[Symbol.iterator];
Array.prototype[Symbol.iterator] = function* () { yield 42; yield 43; };
console.log('patched-iterator', S(new Int8Array([1, 2, 3])), S(Int8Array.from([1, 2, 3])));
Array.prototype[Symbol.iterator] = origIter;
const track = new Uint8Array(rab); const sub = track.subarray(1), subEnd = track.subarray(1, 3);
rab.resize(5); console.log('tracking-subarray', track.length, sub.length, subEnd.length, S(sub)); rab.resize(10); console.log('tracking-subarray-grow', sub.length, subEnd.length, sub.byteOffset);
console.log('ctor-undef', S(new Int8Array(new ArrayBuffer(3), undefined, undefined)), E(() => new Int8Array(new ArrayBuffer(3), 1, undefined).length));
Number.prototype.toLocaleString = 5; console.log('toLocale-noncallable', E(() => new Int8Array([1]).toLocaleString())); delete Number.prototype.toLocaleString;
console.log('of-from', E(() => Int8Array.of.call({}, 1)), E(() => Int8Array.from({ [Symbol.iterator]: 1 })), E(() => Int8Array.from([1, 2], function (v) { return v * this.k; }, { k: 5 })), E(() => Int8Array.from({ length: 2, 0: 1, 1: 2 }, (v, i) => v + i)), E(() => Int8Array.of.call(function () { const t = new Int8Array(2); t.buffer.transfer(); return t; }, 1)), E(() => Int8Array.from.call(function () { return new Int8Array(new ArrayBuffer(4).transferToImmutable()); }, [1])));
console.log('species-detached', E(() => { const x = new Int8Array(2); x.constructor = { [Symbol.species]: function (n) { const t = new Int8Array(n); t.buffer.transfer(); return t; } }; return x.map(v => v); }));
console.log('tostring-tag', [Int8Array, Uint8ClampedArray, Float16Array, BigUint64Array].map(T => Object.prototype.toString.call(new T(1))).join(' '), Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Int8Array.prototype), Symbol.toStringTag).get.call(new DataView(new ArrayBuffer(1))));
console.log('keys-order', Object.keys(new Float32Array([1, 2])).join(), JSON.stringify(Object.entries(new Uint8Array([7, 8]))), Reflect.ownKeys(new Int8Array(2)).length, Object.isFrozen(new Int8Array(0)), E(() => Object.freeze(new Int8Array(1))), E(() => Object.defineProperty(new Int8Array(2), '0', { value: 9 })[0]), E(() => Object.defineProperty(new Int8Array(2), '5', { value: 9 })), delete new Int8Array(2)[0], E(() => { 'use strict'; const t = new Int8Array(1); t[3] = 1; return t[3]; }));
const nb = new Uint8Array(8); nb.set([1, 0, 0, 0, 0, 0, 0xf8, 0x7f]); const nf = new Float64Array(nb.buffer);
const bytes = (t) => Array.from(new Uint8Array(t.buffer, t.byteOffset, t.byteLength)).join(',');
const g4 = new Uint8Array([1, 0, 0xc0, 0x7f]);
console.log('nan-payload', bytes(nf.slice()), (() => { const t = new Float64Array(2); t.set(nf, 1); return bytes(t); })(), bytes(new Float32Array(g4.buffer).slice()));
console.log('generic-array-methods', Array.prototype.join.call(new Int8Array([1, 2]), '-'), Array.prototype.map.call(new Int8Array([1, 2]), x => x * 2).constructor.name, [].concat(new Int8Array([1, 2])).length, Array.prototype.slice.call(new Uint8Array([5, 6, 7]), 1).join(), Array.from(new Uint16Array([9, 8])).join(), Math.max(...new Float32Array([1.5, 9.25, -3])), String.fromCharCode(...new Uint8Array([72, 105])));
const ta = new Int8Array([1, 2, 3]); const ks = []; for (const k in ta) ks.push(k);
console.log('reflect', ks.join(), Reflect.set(ta, '0', 5), ta[0], Reflect.set(ta, '9', 5), Reflect.has(ta, 1.5), Reflect.has(ta, '2'), Object.getOwnPropertyDescriptor(ta, '5'), (ta['1e0'] = 4), ta['1e0'], Reflect.ownKeys(ta).join());
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_buffer_extras(run, workdir, tier):
    """CATCHES: implementations that get SharedArrayBuffer species/views/BigInt Atomics, allocation limits, sliceToImmutable/resize/transfer coercion order, accessor brand checks, realm prototype fallback, patched Array iterators, length-tracking subarrays and TypedArray.of/from receivers wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_BUFFER_EXTRAS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "buffer_extras")


PROG_EDGE_PATHS = r"""
const S = (a) => a.constructor.name + '[' + Array.from(a).join(',') + ']';
const E = (f) => { try { const r = f(); return r && typeof r === 'object' && 'length' in r ? S(r) : (typeof r === 'bigint' ? r + 'n' : String(r)); } catch (e) { return e.name + ': ' + e.message; } };
const t = new Int16Array([4, 5, 6]);
const boom = (v, i) => { if (i === 1) throw new Error('cb#' + v); return false; };
console.log('cb-throws', ['forEach', 'every', 'some', 'find', 'findIndex', 'findLast', 'findLastIndex', 'map', 'filter'].map(m => m + '=' + E(() => t[m](m === 'every' ? (v, i) => { if (i === 1) throw new Error('cb#' + v); return true; } : boom))).join(' '), E(() => t.reduce((a, v, i) => { if (i === 2) throw new Error('red'); return a + v; })), E(() => t.reduceRight((a, v, i) => { if (i === 0) throw new Error('redR'); return a + v; })));
console.log('empty-search', new Int8Array(0).indexOf(1), new Int8Array(0).lastIndexOf(1), new Int8Array(0).includes(0), t.includes(5, NaN), t.indexOf(6, -Infinity), t.lastIndexOf(4, -Infinity), t.lastIndexOf(6, Infinity));
const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const tr = new Int16Array(rab); tr.set([1, 0, 0, 0]);
console.log('indexOf-tracking-shrink', tr.indexOf(0, { valueOf() { rab.resize(2); return 0; } }), tr.length);
rab.resize(8); tr.set([1, 0, 0, 0]);
console.log('lastIndexOf-tracking-shrink', tr.lastIndexOf(0, { valueOf() { rab.resize(4); return 3; } }), tr.length);
rab.resize(8); tr.set([7, 8, 9, 10]);
console.log('slice-species-other-kind-shrink', E(() => { tr.constructor = { [Symbol.species]: function (n) { rab.resize(4); return new Float64Array(n); } }; return tr.slice(0); }));
rab.resize(8); tr.set([7, 8, 9, 10]);
console.log('slice-species-same-kind-shrink', E(() => { tr.constructor = { [Symbol.species]: function (n) { rab.resize(6); return new Int16Array(n); } }; return tr.slice(1); }));
delete tr.constructor;
console.log('infinity-indices', S(new Int8Array([1, 2, 3, 4]).fill(9, -Infinity, Infinity)), S(new Int8Array([1, 2, 3, 4]).slice(-Infinity, 2)), S(new Int8Array([1, 2, 3, 4]).copyWithin(Infinity, 0)), S(new Int8Array([1, 2, 3, 4]).subarray(1, Infinity)), S(new Int8Array([1, 2, 3, 4]).fill(5, 1, -Infinity)), new Int8Array([1, 2]).at(-Infinity));
function F() {} F.prototype = 1;
console.log('realm-proto-object-arg', Object.getPrototypeOf(Reflect.construct(Uint8Array, [], F)) === Uint8Array.prototype, Object.getPrototypeOf(Reflect.construct(Int16Array, [new ArrayBuffer(4)], F)) === Int16Array.prototype, Reflect.construct(Int16Array, [[1, 2, 3]], F).length);
console.log('huge-lengths', E(() => new Int8Array(2 ** 20).length), E(() => new Int8Array(2 ** 20 + 1)), E(() => new Float64Array(2 ** 20).byteLength), E(() => new Int8Array(new ArrayBuffer(3e6)).length), E(() => Uint8Array.from({ length: 2 ** 20 + 1 })), E(() => new Int8Array(2 ** 40)), E(() => new Int8Array({ length: 2 ** 40 })), E(() => Int8Array.from({ length: -3 }).length));
console.log('set-edge', E(() => { const x = new Int8Array(3); x.set([1], NaN); return x; }), E(() => new Int8Array(2).set(new Int8Array(3))), E(() => new Int8Array(4).set(new Int8Array(2), 3)), E(() => { const x = new Int8Array(3); x.set([7], '2'); return x; }), E(() => { const x = new Int8Array(3); x.set([7], 2.9); return x; }));
console.log('ab-brand', E(() => ArrayBuffer.prototype.slice.call({})), E(() => ArrayBuffer.prototype.sliceToImmutable.call(new SharedArrayBuffer(1))), E(() => ArrayBuffer.prototype.transferToImmutable.call({})));
const sab = new SharedArrayBuffer(4, {}); const sab2 = new SharedArrayBuffer(4, { maxByteLength: undefined });
console.log('sab-options', sab.growable, sab.maxByteLength, sab2.growable, sab.slice(3, 1).byteLength, new SharedArrayBuffer(2.5).byteLength, E(() => new SharedArrayBuffer(2, { maxByteLength: 2 ** 40 })));
const dec = (s, o) => E(() => Uint8Array.fromBase64(s, o));
console.log('b64-padding-ws', dec('QQ= ='), dec('QQ=\n='), dec('QQ = = '), dec('QUI= '), dec('QQ=\t=x'), dec('QQ= ', { lastChunkHandling: 'stop-before-partial' }), E(() => JSON.stringify(new Uint8Array(3).setFromBase64('QUJDREVG'))), E(() => JSON.stringify(new Uint8Array(4).setFromBase64('QUJDREVG'))), E(() => JSON.stringify(new Uint8Array(5).setFromBase64('QUJD REVG', { lastChunkHandling: 'strict' }))));
const TA = Object.getPrototypeOf(Int8Array);
console.log('subclass-super', E(() => { class Y extends Int8Array { constructor() { super(2); this.extra = 1; } } const y = new Y(); return [y.length, y.extra, y instanceof TA].join(); }));
const imm = new ArrayBuffer(8).transferToImmutable(); const det = new ArrayBuffer(8); const ddv = new DataView(det); det.transfer();
console.log('dv-bigint-edge', E(() => new DataView(imm).setBigInt64(0, 1n)), E(() => ddv.setBigInt64(0, 1n)), E(() => ddv.getBigUint64(0)), E(() => new DataView(imm).getBigInt64(0)));
const proxyNT = (buf, act) => new Proxy(function () {}, { get(target, key) { if (key === 'prototype') { act(buf); return DataView.prototype; } return target[key]; } });
console.log('dv-newtarget', E(() => { const b = new ArrayBuffer(8); return Reflect.construct(DataView, [b], proxyNT(b, (x) => x.transfer())); }), E(() => { const b = new ArrayBuffer(8, { maxByteLength: 8 }); return Reflect.construct(DataView, [b, 6], proxyNT(b, (x) => x.resize(4))); }), E(() => { const b = new ArrayBuffer(8, { maxByteLength: 8 }); return Reflect.construct(DataView, [b, 2, 4], proxyNT(b, (x) => x.resize(5))); }), E(() => { const b = new ArrayBuffer(8, { maxByteLength: 8 }); return Reflect.construct(DataView, [b, 2], proxyNT(b, (x) => x.resize(4))).byteLength; }));
const i32 = new Int32Array(new SharedArrayBuffer(8)); const detI = new Int32Array(new ArrayBuffer(8)); detI.buffer.transfer();
console.log('atomics-edge', E(() => Atomics.notify(detI, 0)), E(() => Atomics.wait(detI, 0, 0, 0)), Atomics.wait(i32, 0, 5, NaN), Atomics.wait(i32, 0, 5, Infinity), Atomics.wait(i32, 0, 5), Atomics.notify(i32, 0, Infinity), Atomics.notify(i32, 1, NaN), Atomics.notify(i32, 1, -5), JSON.stringify(Atomics.waitAsync(i32, 1, 0, 0)), JSON.stringify(Atomics.waitAsync(i32, 1, 0, -10)), Atomics.isLockFree('4'), Atomics.isLockFree(3.9));
console.log('bigint-edge', 0n << 5n, 0n >> 3n, -0n << 64n, 1n < Infinity, 1n > -Infinity, -1n > -1.5, -2n < -1.5, 2n > 1.5, 3n == 3.0, 3n == 3.5, 2n ** 64n == 18446744073709551616, 10n > NaN, E(() => BigInt.prototype.valueOf.call({})), E(() => BigInt.prototype.toString.call(Object(5n), 2)), E(() => (5n).toString(undefined)), E(() => (255n).toString('16')));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_edge_paths(run, workdir, tier):
    """CATCHES: implementations that get throwing callbacks, empty/infinite/NaN search indices, length-tracking views shrunk during coercion or by a species constructor, huge lengths, set offsets, SharedArrayBuffer options, base64 padding with whitespace, DataView newTarget/immutable/detached BigInt paths, Atomics on detached arrays and BigInt/Number comparisons wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_EDGE_PATHS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "edge_paths")


PROG_HOT_LOOPS = r"""
function fillAndSum(T, n, f) { const a = new T(n); for (let i = 0; i < n; i++) a[i] = f(i); let s = 0; for (let i = 0; i < a.length; i++) s += a[i]; return [s, a[n - 1], a[n >> 1]]; }
const out = [];
for (let rep = 0; rep < 2; rep++) {
  out.push(fillAndSum(Int8Array, 700, i => i * 7).join(','));
  out.push(fillAndSum(Uint8ClampedArray, 700, i => i - 1000.5).join(','));
  out.push(fillAndSum(Int32Array, 700, i => i * 1000003).join(','));
  out.push(fillAndSum(Uint32Array, 700, i => -i).join(','));
  out.push(fillAndSum(Float32Array, 700, i => i / 3).join(','));
  out.push(fillAndSum(Float64Array, 700, i => Math.sqrt(i)).join(','));
  out.push(fillAndSum(Float16Array, 700, i => i / 7).join(','));
  out.push(fillAndSum(Uint16Array, 700, i => i * i).join(','));
}
console.log(out.join('\n'));
function bigSum(n) { const a = new BigInt64Array(n); for (let i = 0; i < n; i++) a[i] = BigInt(i) * 700000000000n; let s = 0n; for (let i = 0; i < n; i++) s += a[i]; return s; }
console.log(bigSum(600), bigSum(600) === bigSum(600));
function dvLoop(n) { const dv = new DataView(new ArrayBuffer(n * 8)); for (let i = 0; i < n; i++) dv.setFloat64(i * 8, i * 1.5, i & 1); let s = 0; for (let i = 0; i < n; i++) s += dv.getFloat64(i * 8, i & 1); return s; }
console.log(dvLoop(700));
function crcLike(buf) { let h = 0x811c9dc5; for (let i = 0; i < buf.length; i++) { h ^= buf[i]; h = Math.imul(h, 0x01000193) >>> 0; } return h; }
const u8 = new Uint8Array(6000); for (let i = 0; i < u8.length; i++) u8[i] = (i * 31 + (i >> 3)) & 255;
console.log(crcLike(u8), crcLike(u8.subarray(100, 3000)), crcLike(u8.slice(3000).reverse()));
let oob = 0; const small = new Int16Array(10); for (let i = 0; i < 2000; i++) { const v = small[i % 13]; if (v === undefined) oob++; small[i % 13] = i; }
console.log(oob, small.join(','), Object.keys(small).length);
function bigMul(n) { let x = 1n; for (let i = 1; i <= n; i++) x = x * BigInt(i) + BigInt(i & 7); return x % 1000000000039n; }
console.log(bigMul(150));
"""

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_hot_loops(run, workdir, tier):
    """CATCHES: implementations that get JIT/bytecode handling of typed-array element loads and stores in hot loops (clamping, wrapping, Float16/Float32 rounding, BigInt64 sums, DataView loops, out-of-range index reads) wrong (in any execution tier)."""
    write_files(workdir, {"main.js": PROG_HOT_LOOPS})
    r = run([*tier, "main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "hot_loops")


