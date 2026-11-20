"""Second-wave gap tests for the engine's built-in library: TypedArray/ArrayBuffer/DataView exotic
behaviour (Reflect on integer-indexed objects, species validation, resizable/immutable buffers),
JSON reviver walks over proxy and TypedArray holders, the Error.prototype.stack accessor pair,
iterator-helper closing and receiver checks, Array.fromAsync, and other rarely exercised built-in
error paths. Programs that depend on the evaluator are run on more than one tier against ONE golden."""

import pytest

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

TWO_TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp")]
TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
         pytest.param(["--tier=bytecode"], id="bytecode")]


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_typed_array_reflect_and_own_properties(run, workdir, cli):
    """CATCHES: TypedArray [[Set]]/[[GetOwnProperty]]/[[Delete]]/[[Get]] via Reflect with foreign or
    plain receivers handled like ordinary objects (writing into the view instead of the receiver,
    accepting out-of-range or '-0'/'1.5' canonical keys), BigInt views accepting Numbers, and
    Object.values/entries skipping integer indices or the enumerable expandos of a view. Also pins
    the reference's Object.hasOwn on a view (it reports false for in-range indices, unlike
    hasOwnProperty)."""
    check_script(run, workdir, G, "typed_array_reflect", r'''
const ta = new Int16Array([5, -3, 7]);
ta.extra = 'x';
Object.defineProperty(ta, 'hidden', { value: 1, enumerable: false });
console.log(JSON.stringify(Object.values(ta)), JSON.stringify(Object.entries(ta)));
console.log(JSON.stringify(Object.keys(ta)), Object.getOwnPropertyNames(ta).join());
const big = new BigInt64Array(2);
console.log(Reflect.set(big, '0', 5n), big[0], Reflect.set(big, '5', 1n), Reflect.set(big, '1.5', 1n));
try { Reflect.set(big, '0', 1); } catch (e) { console.log(e.name + ': ' + e.message); }
const recv = {};
const u8 = new Uint8Array(2);
console.log(Reflect.set(u8, '0', 300, recv), JSON.stringify(recv), u8[0]);
console.log(Reflect.set(u8, '-0', 1, recv), Reflect.set(u8, 'foo', 1, recv), JSON.stringify(recv));
console.log(Reflect.set(u8, '1', 77, u8), u8[1]);
const other = new Uint8Array(4);
console.log(Reflect.set(u8, '1', 99, other), other[1], u8[1]);
console.log(Reflect.set(u8, '9', 99, other), other[9]);
console.log(JSON.stringify(Reflect.getOwnPropertyDescriptor(u8, '1')), Reflect.getOwnPropertyDescriptor(u8, '7'), Reflect.getOwnPropertyDescriptor(u8, '-0'));
console.log(Reflect.deleteProperty(u8, '0'), Reflect.deleteProperty(u8, '5'), Reflect.deleteProperty(u8, 'extra'), Reflect.deleteProperty(u8, '1.5'));
console.log(Reflect.get(u8, '1', {}), Reflect.get(u8, '9', {}), Reflect.get(u8, '1.5', {}));
console.log(u8.hasOwnProperty('1'), u8.hasOwnProperty(5), u8.hasOwnProperty('-0'), u8.hasOwnProperty('length'));
console.log(Object.hasOwn(u8, '1'), '1' in u8, '-0' in u8, 2 in u8);
try { Reflect.deleteProperty(1, 'x'); } catch (e) { console.log(e.name + ': ' + e.message); }
''', cli=cli)


def test_typed_array_callbacks_species_and_search(run, workdir):
    """CATCHES: TypedArray iteration methods swallowing an exception thrown by the callback, a
    @@species constructor that returns a plain array being accepted by map/filter/slice, slice
    into a different element type not converting values (300 -> 44 in Int8), indexOf/lastIndexOf
    fromIndex coercion (NaN, -Infinity, explicit undefined) wrong, searches not re-checking the
    length after a resizable buffer shrinks during coercion, and the TypedArray constructor's
    newTarget-prototype fallback, length limits and @@iterator validation."""
    check_script(run, workdir, G, "typed_array_callbacks", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(Array.from(r)) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const ta = new Float64Array([1.5, NaN, -0, 3]);
const boom = () => { throw new RangeError('cb boom'); };
for (const m of ['forEach', 'map', 'filter', 'some', 'every', 'find', 'findIndex', 'findLast', 'findLastIndex', 'reduce', 'reduceRight'])
  console.log(m, show(() => ta[m](boom)));
console.log('every-false', show(() => ta.every(x => x > 1)), 'some-false', show(() => ta.some(x => x > 10)));
class NotTA extends Float64Array { static get [Symbol.species]() { return function () { return [9, 9]; }; } }
const nt = new NotTA([1, 2, 3]);
console.log('map species', show(() => nt.map(x => x)));
console.log('filter species', show(() => nt.filter(x => true)));
console.log('slice species', show(() => nt.slice(0)));
class ToI8 extends Float64Array { static get [Symbol.species]() { return Int8Array; } }
console.log('slice kind change', show(() => new ToI8([1.7, -2.2, 300]).slice(0, 3)));
console.log('indexOf from', new Int8Array([4, 5, 4]).indexOf(4, NaN), new Int8Array([4, 5, 4]).lastIndexOf(4, -10), new Int8Array(0).lastIndexOf(0), new Int8Array([4, 5, 4]).lastIndexOf(4, undefined));
console.log('includes', new Int8Array([1, 2]).includes(2, -Infinity), new Int8Array([1, 2]).includes(1, Infinity));
console.log('fill inf', show(() => new Int8Array(4).fill(7, -Infinity, Infinity)), show(() => new Int8Array(4).fill(7, 1, -Infinity)));
const rab = new ArrayBuffer(8, { maxByteLength: 16 });
const view = new Uint8Array(rab);
view.set([1, 2, 3, 4, 5, 6, 7, 8]);
console.log('lastIndexOf shrink', view.lastIndexOf(8, { valueOf() { rab.resize(4); return 7; } }));
rab.resize(8);
view.set([1, 2, 3, 4, 5, 6, 7, 8]);
console.log('indexOf shrink', view.indexOf(0, { valueOf() { rab.resize(2); return 0; } }));
console.log('tracking view', view.length, view.byteLength, view.byteOffset);
const nt2 = function () {}; nt2.prototype = 1;
const r = Reflect.construct(Uint8Array, [2], nt2);
console.log('ctor proto fallback', Object.getPrototypeOf(r) === Uint8Array.prototype, r.length);
const r2 = Reflect.construct(Uint8Array, [[1, 2, 3]], nt2);
console.log(Object.getPrototypeOf(r2) === Uint8Array.prototype, r2.join());
console.log(show(() => new Uint8Array({ length: 2 ** 40 })));
console.log(show(() => new Uint8Array({ [Symbol.iterator]: 5 })));
console.log(show(() => new Uint8Array(2 ** 40)));
console.log(show(() => Uint8Array(2)));
''')


def test_array_buffer_slice_species_validation(run, workdir):
    """CATCHES: ArrayBuffer/SharedArrayBuffer.prototype.slice trusting whatever the @@species
    constructor returns (a plain object, a SharedArrayBuffer for an ArrayBuffer, a detached,
    immutable, too-small or identical buffer), not noticing the source was detached by the species
    constructor, SharedArrayBuffer maxByteLength/size validation, transfer/slice accepting a
    SharedArrayBuffer receiver, and resize/sliceToImmutable not re-validating after coercion."""
    check_script(run, workdir, G, "array_buffer_species", r'''
const show = (f) => { try { const r = f(); return r instanceof ArrayBuffer || r instanceof SharedArrayBuffer ? r.constructor.name + '(' + r.byteLength + ') [' + new Uint8Array(r).join() + ']' : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const withSpecies = (b, make) => { b.constructor = { [Symbol.species]: make }; return b; };
const src = () => { const b = new ArrayBuffer(6); new Uint8Array(b).set([1, 2, 3, 4, 5, 6]); return b; };
console.log('AB normal', show(() => src().slice(1, -1)));
console.log('AB species plain obj', show(() => withSpecies(src(), function () { return {}; }).slice(0)));
console.log('AB species sab', show(() => withSpecies(src(), function (n) { return new SharedArrayBuffer(n); }).slice(0)));
console.log('AB species detached', show(() => withSpecies(src(), function (n) { const b = new ArrayBuffer(n); b.transfer(); return b; }).slice(0)));
let same; console.log('AB species same', show(() => (same = withSpecies(src(), function () { return same; })).slice(0)));
console.log('AB species immutable', show(() => withSpecies(src(), function (n) { return new ArrayBuffer(n).transferToImmutable(); }).slice(0)));
console.log('AB species small', show(() => withSpecies(src(), function () { return new ArrayBuffer(1); }).slice(0, 4)));
let victim; console.log('AB species detaches source', show(() => (victim = withSpecies(src(), function (n) { victim.transfer(); return new ArrayBuffer(n); })).slice(0, 4)));
console.log('AB species larger', show(() => withSpecies(src(), function (n) { return new ArrayBuffer(n + 2); }).slice(2, 4)));
const ssrc = () => { const b = new SharedArrayBuffer(6); new Uint8Array(b).set([6, 5, 4, 3, 2, 1]); return b; };
console.log('SAB normal', show(() => ssrc().slice(-4, 5)));
console.log('SAB species AB', show(() => withSpecies(ssrc(), function (n) { return new ArrayBuffer(n); }).slice(0)));
let ssame; console.log('SAB species same', show(() => (ssame = withSpecies(ssrc(), function () { return ssame; })).slice(0)));
console.log('SAB species small', show(() => withSpecies(ssrc(), function () { return new SharedArrayBuffer(1); }).slice(0, 3)));
console.log('SAB bad max', show(() => new SharedArrayBuffer(8, { maxByteLength: 4 })), show(() => new SharedArrayBuffer(2, { maxByteLength: -1 })));
console.log('SAB too large', show(() => new SharedArrayBuffer(2 ** 52)));
console.log('SAB growable', show(() => { const s = new SharedArrayBuffer(2, { maxByteLength: 8 }); s.grow(5); return s.growable + ' ' + s.byteLength + ' ' + s.maxByteLength; }));
console.log('transfer shared', show(() => ArrayBuffer.prototype.transfer.call(new SharedArrayBuffer(2))));
console.log('slice shared', show(() => ArrayBuffer.prototype.slice.call(new SharedArrayBuffer(2))));
console.log('resize immutable', show(() => { const b = new ArrayBuffer(2, { maxByteLength: 4 }).transferToImmutable(); return b.resize(1); }));
console.log('resize detach in coercion', show(() => { const b = new ArrayBuffer(2, { maxByteLength: 4 }); return b.resize({ valueOf() { b.transfer(); return 1; } }); }));
console.log('resize NaN', show(() => { const b = new ArrayBuffer(2, { maxByteLength: 4 }); b.resize(NaN); return b.byteLength; }));
console.log('sliceToImmutable shrink', show(() => { const b = new ArrayBuffer(6, { maxByteLength: 8 }); return b.sliceToImmutable(0, { valueOf() { b.resize(2); return 4; } }); }));
console.log('sliceToImmutable empty', show(() => src().sliceToImmutable(4, 2)));
console.log('sliceToImmutable detached', show(() => { const b = src(); return b.sliceToImmutable(0, { valueOf() { b.transfer(); return 3; } }); }));
console.log('transfer newlen', show(() => src().transfer(3)), show(() => src().transfer(-1)));
''')


def test_dataview_bounds_bigint_and_revalidation(run, workdir):
    """CATCHES: DataView get/set (including the BigInt64 accessors) not re-deriving the view length
    after a resizable buffer shrinks or a coercion detaches it (must be a TypeError, while an index
    past the view is a RangeError), immutable buffers accepting writes, the constructor not
    re-validating offset/length after a newTarget.prototype getter detaches or resizes the buffer,
    and big-endian default byte order on SharedArrayBuffer-backed views."""
    check_script(run, workdir, G, "dataview_bounds", r'''
const show = (f) => { try { return String(f()); } catch (e) { return e.name + ': ' + e.message; } };
const rab = new ArrayBuffer(16, { maxByteLength: 32 });
const fixed = new DataView(rab, 4, 8);
const tracking = new DataView(rab, 4);
fixed.setBigInt64(0, -2n); tracking.setUint16(10, 0xBEEF, true);
console.log(show(() => fixed.getBigInt64(0)), show(() => fixed.getBigUint64(0, true)), show(() => tracking.getUint16(10, true).toString(16)));
console.log(show(() => fixed.getBigInt64(1)), show(() => fixed.setBigInt64(4, 1n)), show(() => fixed.setBigUint64(2 ** 53, 1n)));
rab.resize(10);
console.log('after shrink', show(() => fixed.byteLength), show(() => tracking.byteLength));
console.log(show(() => fixed.getInt8(0)), show(() => fixed.getBigInt64(0)), show(() => fixed.setBigInt64(0, 1n)), show(() => fixed.setFloat32(0, 1)));
console.log(show(() => tracking.getBigUint64(0)), show(() => tracking.getInt16(4)));
rab.resize(2);
console.log('beyond offset', show(() => tracking.byteLength), show(() => tracking.getInt8(0)), show(() => tracking.byteOffset));
const b2 = new ArrayBuffer(8);
const dv2 = new DataView(b2);
console.log(show(() => dv2.getBigInt64(0, { valueOf() { return 1; } })), show(() => dv2.setBigInt64({ valueOf() { b2.transfer(); return 0; } }, 5n)));
const b3 = new ArrayBuffer(8);
const dv3 = new DataView(b3);
console.log(show(() => dv3.getBigInt64({ valueOf() { b3.transfer(); return 0; } })));
const imm = new ArrayBuffer(8).transferToImmutable();
const dvi = new DataView(imm);
console.log(show(() => dvi.setBigInt64(0, 1n)), show(() => dvi.setInt8(0, 1)), show(() => dvi.getInt8(0)));
const mk = (hook) => { const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { get() { hook(); return DataView.prototype; } }); return nt; };
const b4 = new ArrayBuffer(8);
console.log(show(() => Reflect.construct(DataView, [b4, 0, 4], mk(() => b4.transfer()))));
const b5 = new ArrayBuffer(8, { maxByteLength: 16 });
console.log(show(() => Reflect.construct(DataView, [b5, 6], mk(() => b5.resize(4)))));
const b6 = new ArrayBuffer(8, { maxByteLength: 16 });
console.log(show(() => Reflect.construct(DataView, [b6, 2, 4], mk(() => b6.resize(4)))));
const b7 = new ArrayBuffer(8, { maxByteLength: 16 });
console.log(show(() => Reflect.construct(DataView, [b7, 2], mk(() => b7.resize(12))).byteLength));
console.log(show(() => new DataView(new ArrayBuffer(4), 5)), show(() => new DataView(new ArrayBuffer(4), 2, 3)), show(() => DataView(new ArrayBuffer(1))));
const sab = new SharedArrayBuffer(8); const sdv = new DataView(sab); sdv.setBigUint64(0, 0x0102030405060708n);
console.log(show(() => sdv.getBigUint64(0).toString(16)), show(() => new Uint8Array(sab).join()), show(() => sdv.getUint32(4, true).toString(16)));
''')


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_json_reviver_proxy_and_typed_array_holders(run, workdir, cli):
    """CATCHES: JSON.parse's InternalizeJSONProperty bypassing proxy traps when a reviver grafts a
    Proxy into the tree (it must use ownKeys/getOwnPropertyDescriptor/get, then defineProperty or
    deleteProperty in that order), not walking a grafted TypedArray's indices, wrong reviver
    context.source text, trailing-garbage / bad-literal SyntaxErrors, String/Number wrapper `space`
    arguments, proxy and wrapper-object replacer arrays, and stringifying proxies. Pins the
    reference's internal-looking TypeError text when stringifying a revoked proxy."""
    check_script(run, workdir, G, "json_reviver_holders", r'''
const show = (f) => { try { return JSON.stringify(f()); } catch (e) { return e.name + ': ' + e.message; } };
const trapLog = [];
const handler = {
  ownKeys(t) { trapLog.push('ownKeys'); return Reflect.ownKeys(t); },
  getOwnPropertyDescriptor(t, k) { trapLog.push('gopd:' + k); return Reflect.getOwnPropertyDescriptor(t, k); },
  get(t, k, r) { if (typeof k === 'string') trapLog.push('get:' + k); return Reflect.get(t, k, r); },
  defineProperty(t, k, d) { trapLog.push('define:' + k + '=' + JSON.stringify(d.value)); return Reflect.defineProperty(t, k, d); },
  deleteProperty(t, k) { trapLog.push('delete:' + k); return Reflect.deleteProperty(t, k); },
};
const res = JSON.parse('{"first":0,"second":{"p":1,"q":2},"arr":[5,6]}', function (k, v) {
  if (k === 'first') { this.second = new Proxy({ p: 10, q: 20, drop: 1 }, handler); this.arr = new Proxy([7, 8], handler); }
  if (k === 'drop') return undefined;
  if (typeof v === 'number') return v * 2;
  return v;
});
console.log(trapLog.join(' '));
console.log(JSON.stringify(res));
const res2 = JSON.parse('{"a":1,"t":null}', function (k, v) {
  if (k === 'a') this.t = new Uint8Array([3, 4]);
  if (k === '0' || k === '1') return v + 100;
  return v;
});
console.log(Object.prototype.toString.call(res2.t), Array.from(res2.t).join());
console.log(show(() => JSON.parse('[1.0, "s", false, null, 1e2, -0]', (k, v, c) => k === '' ? v : [v, c.source])));
console.log(show(() => JSON.parse('[1] x', () => 1)), show(() => JSON.parse('[1] x')), show(() => JSON.parse(' fals')), show(() => JSON.parse('tru')));
console.log(show(() => JSON.parse('{"a":false,"b":[true]}', (k, v) => v)));
console.log(JSON.stringify({ a: [1] }, null, new String('--')));
console.log(JSON.stringify({ a: 1 }, null, new Number(3)), JSON.stringify({ a: 1 }, null, Object(true)));
console.log(JSON.stringify({ a: 1, b: 2, 1: 3 }, new Proxy(['b', 1], {})), JSON.stringify({ a: 1, b: 2 }, [new String('a'), new Number(1), {}, 'a']));
console.log(JSON.stringify(new Proxy({ k: 1, z: [1, 2] }, {})), JSON.stringify(new Proxy([1, { a: 2 }], {})));
console.log(show(() => { const r = Proxy.revocable([], {}); r.revoke(); return JSON.stringify({ x: r.proxy }); }));
''', cli=cli)


def test_error_stack_accessor_pair(run, workdir):
    """CATCHES: Error.prototype.stack not being a configurable accessor pair, the getter's header
    ignoring undefined/empty name or message, the setter not validating its receiver/value or
    allowing writes to Error.prototype, not going through a Proxy receiver's getOwnPropertyDescriptor
    / defineProperty / set traps (a false `set` must throw), non-extensible or frozen receivers being
    silently accepted, and Error constructors ignoring newTarget's non-object prototype fallback."""
    check_script(run, workdir, G, "error_stack_accessor", r'''
const show = (f) => { try { return String(f()); } catch (e) { return e.name + ': ' + e.message; } };
const desc = Object.getOwnPropertyDescriptor(Error.prototype, 'stack');
console.log(typeof desc.get, typeof desc.set, desc.enumerable, desc.configurable);
const getStack = desc.get, setStack = desc.set;
const head = (e) => getStack.call(e).split('\n')[0];
const e1 = new Error('m'); Object.defineProperty(e1, 'name', { value: undefined }); Object.defineProperty(e1, 'message', { value: undefined });
const e2 = new RangeError('x'); e2.name = '';
const e4 = new Error('kept'); e4.name = undefined;
console.log(JSON.stringify([head(e1), head(e2), head(new TypeError('')), head(e4)]), getStack.call({}));
console.log(show(() => getStack.call(5)), show(() => setStack.call(5, 'x')));
console.log(show(() => setStack.call({}, 5)), show(() => setStack.call(Error.prototype, 'x')));
const log = [];
const h = {
  getOwnPropertyDescriptor(t, k) { log.push('gopd:' + String(k)); return Reflect.getOwnPropertyDescriptor(t, k); },
  defineProperty(t, k, d) { log.push('define:' + String(k) + ':' + d.value); return Reflect.defineProperty(t, k, d); },
  set(t, k, v, r) { log.push('set:' + String(k) + ':' + v); return Reflect.set(t, k, v); },
};
const p1 = new Proxy({}, h);
setStack.call(p1, 'first'); setStack.call(p1, 'second');
console.log(log.join(' '), '|', JSON.stringify(Object.getOwnPropertyDescriptor(p1, 'stack')));
const p2 = new Proxy({ stack: 'own' }, { set() { return false; } });
console.log(show(() => setStack.call(p2, 'nope')));
const p3 = new Proxy({ stack: 'own' }, {});
setStack.call(p3, 'forwarded'); console.log(p3.stack);
console.log(show(() => setStack.call(new Proxy(Object.preventExtensions({}), {}), 'x')));
console.log(show(() => setStack.call(Object.preventExtensions({}), 'x')));
const frozen = Object.freeze({ stack: 'f' });
console.log(show(() => setStack.call(frozen, 'x')), frozen.stack);
const o = {}; setStack.call(o, 'plain'); console.log(JSON.stringify(Object.getOwnPropertyDescriptor(o, 'stack')));
console.log(Error.prototype.toString.call({ name: undefined, message: undefined }), '|', Error.prototype.toString.call({ name: '', message: 'm' }), '|', Error.prototype.toString.call({ name: 'X', message: '' }));
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: 3 });
const ae = Reflect.construct(AggregateError, [[1, 2], 'agg'], nt);
console.log(Object.getPrototypeOf(ae) === AggregateError.prototype, ae.message, ae.errors.join());
const se = Reflect.construct(SuppressedError, [new Error('e'), new Error('s'), 'sup'], nt);
console.log(Object.getPrototypeOf(se) === SuppressedError.prototype, se.message, se.error.message, se.suppressed.message);
const te = Reflect.construct(TypeError, ['te'], nt);
console.log(Object.getPrototypeOf(te) === TypeError.prototype, te.message);
console.log(show(() => new AggregateError(5)), show(() => new AggregateError([], undefined, { cause: 0 }).cause));
''')


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_iterator_helpers_closing_and_receivers(run, workdir, cli):
    """CATCHES: Iterator.prototype.forEach/some/every/find/reduce not closing the underlying iterator
    when the callback is not callable or throws, Iterator.prototype's constructor/@@toStringTag
    accessor pair not defining own properties on other receivers (and not throwing for the
    prototype itself), the abstract Iterator constructor, Iterator.from wrapper and helper
    next/return receiver checks, re-entrant helper/concat calls not raising "already running",
    and Iterator.concat return()/next() after completion."""
    check_script(run, workdir, G, "iterator_helpers_closing", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const mk = (tag, n = 3) => { let k = 0; return { __proto__: Iterator.prototype, next() { k++; return k > n ? { done: true } : { value: tag + k, done: false }; }, return() { console.log('  return() called on ' + tag); return {}; } }; };
for (const m of ['forEach', 'some', 'every', 'find', 'reduce']) console.log(m, 'non-callable:', show(() => mk(m)[m](42)));
const boom = () => { throw new EvalError('cb'); };
for (const m of ['forEach', 'some', 'every', 'find', 'reduce']) console.log(m, 'throws:', show(() => mk(m)[m](boom, 0)));
console.log('every exhaust', show(() => mk('e').every(x => true)), 'some exhaust', show(() => mk('s').some(x => false)));
console.log('find none', show(() => mk('f').find(x => false)));
console.log(Iterator.prototype.constructor === Iterator, Iterator.prototype[Symbol.toStringTag]);
const obj = { __proto__: Iterator.prototype };
obj.constructor = 'mine'; obj[Symbol.toStringTag] = 'Tagged';
console.log(Object.getOwnPropertyNames(obj).join(), Object.prototype.toString.call(obj), Iterator.prototype.constructor === Iterator);
console.log(show(() => { Iterator.prototype.constructor = 1; }), show(() => { Iterator.prototype[Symbol.toStringTag] = 1; }));
const setC = Object.getOwnPropertyDescriptor(Iterator.prototype, 'constructor').set;
console.log(show(() => setC.call(5, 1)));
class MyIt extends Iterator {}
console.log(Object.getPrototypeOf(new MyIt()) === MyIt.prototype, show(() => new Iterator()), show(() => Iterator()));
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: null });
console.log(Object.getPrototypeOf(Reflect.construct(Iterator, [], nt)) === Iterator.prototype);
const wrapped = Iterator.from({ next() { return { value: 1, done: false }; } });
const WrapProto = Object.getPrototypeOf(wrapped);
console.log(show(() => WrapProto.next.call({})), show(() => WrapProto.return.call({})));
console.log(show(() => wrapped.return()), show(() => Iterator.from({ next() {}, return: 5 }).return()));
console.log(show(() => Iterator.from({ next() {}, return() { return 'raw'; } }).return()));
const HelperProto = Object.getPrototypeOf(mk('h').map(x => x));
console.log(show(() => HelperProto.return.call({})), show(() => HelperProto.next.call({})));
let selfRef; selfRef = mk('r').map(x => selfRef.return());
console.log(show(() => selfRef.next()));
let selfRef2; selfRef2 = mk('n').map(x => selfRef2.next());
console.log(show(() => selfRef2.next()));
const cc = Iterator.concat([1, 2], mk('c', 2));
console.log(show(() => cc.next()), show(() => cc.return()), show(() => cc.next()), show(() => cc.return()));
const cc2 = Iterator.concat(mk('c2', 2));
console.log(show(() => cc2.next()), show(() => cc2.return()));
const cc3 = Iterator.concat([1]); console.log(show(() => cc3.return()), show(() => cc3.next()));
let reent; reent = Iterator.concat({ [Symbol.iterator]() { return { next() { return reent.next(); } }; } });
console.log(show(() => reent.next()));
let reent2; reent2 = Iterator.concat({ [Symbol.iterator]() { return { next() { return { value: reent2.return(), done: false }; } }; } });
console.log(show(() => reent2.next()));
console.log(show(() => Iterator.concat({ [Symbol.iterator]() { return 5; } }).next()));
''', cli=cli)


def test_array_from_async_edge_cases(run, workdir):
    """CATCHES: Array.fromAsync accepting non-callable @@asyncIterator/@@iterator values or non-object
    iterator results, array-like inputs not awaiting elements / passing the index to mapFn, missing
    length and null checks, not closing the (sync or async) iterator when defining an element on a
    frozen constructor result fails or when an async mapFn rejects, and the constructor-receiver
    path for array-likes."""
    check_script(run, workdir, G, "array_from_async", r'''
const show = async (label, f) => { try { const r = await f(); console.log(label, JSON.stringify(r)); } catch (e) { console.log(label, e.name + ': ' + e.message); } };
(async () => {
  await show('async non-callable', () => Array.fromAsync({ [Symbol.asyncIterator]: 1 }));
  await show('sync non-callable', () => Array.fromAsync({ [Symbol.iterator]: 'x' }));
  await show('result not object', () => Array.fromAsync({ [Symbol.iterator]() { return { next() { return 1; } }; } }));
  await show('async result not object', () => Array.fromAsync({ [Symbol.asyncIterator]() { return { next() { return Promise.resolve(2); } }; } }));
  await show('arraylike map', () => Array.fromAsync({ length: 3, 0: 'a', 1: Promise.resolve('b'), 2: 'c' }, (v, k) => v + k));
  await show('arraylike too long', () => Array.fromAsync({ length: 2 ** 32 }));
  await show('primitive', () => Array.fromAsync(5));
  await show('null', () => Array.fromAsync(null));
  const frozenCtor = function () { return Object.freeze([]); };
  await show('cdp fails sync iter', () => Array.fromAsync.call(frozenCtor, { [Symbol.iterator]() { let n = 0; return { next() { return { value: n++, done: n > 2 }; }, return() { console.log('  closed sync'); return {}; } }; } }));
  await show('cdp fails async iter', () => Array.fromAsync.call(frozenCtor, { [Symbol.asyncIterator]() { let n = 0; return { next() { return Promise.resolve({ value: n++, done: n > 2 }); }, return() { console.log('  closed async'); return Promise.resolve({}); } }; } }));
  await show('mapfn rejects async iter', () => Array.fromAsync({ [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 1, done: false }); }, return() { console.log('  closed on map'); return {}; } }; } }, async () => { throw new URIError('m'); }));
  await show('ctor arraylike', () => Array.fromAsync.call(function (n) { this.made = n; }, { length: 2, 0: 1, 1: 2 }));
  await show('map non-callable', () => Array.fromAsync([], 5));
  await show('sync map', () => Array.fromAsync([Promise.resolve(1), 2], x => x * 10));
})();
''')


def test_proxy_aware_object_reflection_helpers(run, workdir):
    """CATCHES: Object.defineProperties/Object.create reading a Proxy descriptor map without its
    ownKeys/getOwnPropertyDescriptor/get traps (or defining onto a Proxy target without the
    defineProperty trap, or not throwing when it returns false), __defineGetter__/__lookupGetter__
    bypassing proxy traps or the prototype walk, Promise.allKeyed ignoring a proxy input's traps,
    and the success paths of the getOwnPropertyDescriptor / setPrototypeOf invariants (a trap may
    report a configurable property absent, a non-extensible target may keep its prototype). Pins the
    reference's TypeError texts for getPrototypeOf/ownKeys on a revoked proxy."""
    check_script(run, workdir, G, "proxy_reflection_helpers", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const log = [];
const tracer = (name) => ({
  ownKeys(t) { log.push(name + '.ownKeys'); return Reflect.ownKeys(t); },
  getOwnPropertyDescriptor(t, k) { log.push(name + '.gopd(' + String(k) + ')'); return Reflect.getOwnPropertyDescriptor(t, k); },
  defineProperty(t, k, d) { log.push(name + '.define(' + String(k) + ':' + Object.keys(d).join('/') + ')'); return Reflect.defineProperty(t, k, d); },
  get(t, k, r) { if (typeof k === 'string') log.push(name + '.get(' + k + ')'); return Reflect.get(t, k, r); },
});
const flush = (label) => { console.log(label + ': ' + log.join(' ')); log.length = 0; };
const descs = new Proxy({ a: { value: 1, enumerable: true }, b: { get() { return 2; } }, hidden: { value: 3 } }, tracer('descs'));
Object.defineProperty(descs, 'skip', { value: { value: 9 }, enumerable: false });
log.length = 0;
const target = new Proxy({}, tracer('target'));
Object.defineProperties(target, descs);
flush('defineProperties');
console.log(JSON.stringify(Object.getOwnPropertyNames(target)), target.b);
log.length = 0;
console.log(show(() => Object.defineProperties({}, new Proxy({ x: 5 }, {}))));
console.log(show(() => Object.defineProperties(new Proxy({}, { defineProperty() { return false; } }), { q: { value: 1 } })));
console.log(show(() => Object.create(null, new Proxy({ z: { value: 'zz', enumerable: true } }, tracer('createProps'))).z));
flush('create');
const ap = new Proxy({}, tracer('ap'));
ap.__defineGetter__('g', () => 'got'); ap.__defineSetter__('g', function (v) {});
flush('__defineGetter__');
console.log(typeof ap.__lookupGetter__('g'), typeof ap.__lookupSetter__('g'), ap.__lookupGetter__('nope'));
flush('__lookupGetter__');
const dataProxy = new Proxy({ d: 1 }, {});
console.log(dataProxy.__lookupGetter__('d'), Object.create(dataProxy).__lookupGetter__('d'), Object.create(dataProxy).__lookupGetter__('missing'));
console.log(show(() => new Proxy({}, { defineProperty() { return false; } }).__defineGetter__('x', () => 1)));
console.log(show(() => ({}).__defineGetter__('x', 5)));
const objWithAcc = Object.create({ get inh() { return 1; } });
console.log(typeof objWithAcc.__lookupGetter__('inh'), objWithAcc.__lookupSetter__('inh'));
const hideConfigurable = new Proxy({ c: 1 }, { getOwnPropertyDescriptor() { return undefined; } });
console.log(show(() => Object.getOwnPropertyDescriptor(hideConfigurable, 'c')), Object.keys(hideConfigurable).length);
const invent = new Proxy({}, { getOwnPropertyDescriptor() { return { value: 'invented', configurable: true }; } });
console.log(show(() => Object.getOwnPropertyDescriptor(invent, 'anything')));
const fixedAcc = {}; const getter = () => 1; Object.defineProperty(fixedAcc, 'acc', { get: getter });
console.log(show(() => Object.getOwnPropertyDescriptor(new Proxy(fixedAcc, { getOwnPropertyDescriptor() { return { get: getter, configurable: false }; } }), 'acc').get === getter));
const sameProto = new Proxy(Object.preventExtensions({}), { setPrototypeOf() { return true; } });
console.log(show(() => Object.setPrototypeOf(sameProto, Object.prototype) === sameProto), show(() => Object.setPrototypeOf(sameProto, null)));
console.log(show(() => Reflect.setPrototypeOf(new Proxy({}, { setPrototypeOf() { return false; } }), null)));
const chainEnd = {}; const viaProxy = Object.create(new Proxy(chainEnd, {}));
console.log(show(() => Reflect.setPrototypeOf(chainEnd, viaProxy)), Object.getPrototypeOf(chainEnd) === viaProxy);
const r = Proxy.revocable({}, {}); r.revoke();
console.log(show(() => Object.getPrototypeOf(r.proxy)), show(() => Object.isExtensible(r.proxy)), show(() => Object.keys(r.proxy)));
Promise.allKeyed(new Proxy({ one: Promise.resolve(1), two: 2 }, tracer('keyed'))).then(v => { flush('allKeyed'); console.log(JSON.stringify(v), Object.getPrototypeOf(v)); });
''')


def test_array_length_definition_and_mutators_on_locked_arrays(run, workdir):
    """CATCHES: ArraySetLength mistakes (shrinking past a non-configurable element must stop just
    above it and report failure, a non-writable length can't become writable again, accessor /
    enumerable / configurable length descriptors are rejected, fractional / negative / 2^32 values
    are RangeErrors after coercing twice), strict-mode writes to frozen/sealed/non-writable-length
    arrays not throwing the right TypeError, and pop/shift partially mutating before failing. Also
    pins the reference quirks that unshift/splice fail before moving elements and that push on a
    sealed (non-extensible) array still appends."""
    check_script(run, workdir, G, "array_length_locked", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const a = [1, 2, 3, 4, 5];
Object.defineProperty(a, 2, { value: 'pinned', configurable: false, enumerable: true, writable: true });
console.log(show(() => Reflect.defineProperty(a, 'length', { value: 1 })), a.length, JSON.stringify(a));
console.log(show(() => Object.defineProperty(a, 'length', { value: 0 })), a.length);
const b = [1, 2];
console.log(Reflect.defineProperty(b, 'length', { writable: false }), Reflect.defineProperty(b, 'length', { writable: true }), Reflect.defineProperty(b, 'length', { writable: false }));
console.log(Reflect.defineProperty(b, 'length', { value: 2 }), Reflect.defineProperty(b, 'length', { value: 3 }), Reflect.defineProperty(b, 'length', { value: 2, writable: true }));
console.log(Reflect.defineProperty([], 'length', { get() {} }), Reflect.defineProperty([], 'length', { enumerable: true }), Reflect.defineProperty([], 'length', { configurable: true }));
console.log(Reflect.defineProperty([], 'length', { value: 0, enumerable: true }), Reflect.defineProperty([1], 'length', {}), Reflect.defineProperty(b, '5', { value: 1 }));
console.log(show(() => Object.defineProperty([], 'length', { value: -1 })), show(() => Object.defineProperty([], 'length', { value: 1.5 })), show(() => Object.defineProperty([], 'length', { value: 2 ** 32 })));
let count = 0;
console.log(show(() => Object.defineProperty([], 'length', { value: { valueOf() { count++; return 2; } } }).length), count);
console.log(show(() => Object.defineProperty([9, 9], 'length', { value: NaN })), show(() => Object.defineProperty([9, 9], 'length', { value: '' }).length));
console.log(show(() => Object.defineProperty([9, 9], 'length', { value: -0 }).length), show(() => Object.defineProperty([9], 'length', { value: Infinity })));
const c = [1, 2, 3];
Object.defineProperty(c, 1, { value: 'x', configurable: false });
console.log(show(() => { 'use strict'; c.length = 0; }), c.length, JSON.stringify(Object.getOwnPropertyDescriptor(c, 'length')));
const d = Object.freeze([1, 2]);
console.log(show(() => { 'use strict'; d.length = 0; }), show(() => { 'use strict'; d.push(1); }), show(() => { 'use strict'; d[5] = 1; }));
const e = [1, 2, 3]; Object.defineProperty(e, 'length', { writable: false });
console.log(show(() => e.push(4)), show(() => e.pop()), JSON.stringify(e), show(() => e.shift()), JSON.stringify(e));
console.log(show(() => e.unshift(0)), show(() => e.splice(0, 1)), JSON.stringify(e));
console.log(show(() => { 'use strict'; e[3] = 9; }), show(() => { e[7] = 9; return e.length; }), show(() => Reflect.set(e, '9', 1)));
const s = [1, 2, 3]; Object.seal(s);
console.log(Object.isExtensible(s), show(() => s.pop()), show(() => s.push(4)), JSON.stringify(s), Object.isSealed(s), Object.isFrozen(s));
function mapped(x) { Object.defineProperty(arguments, '0', { value: 'locked', writable: false, configurable: false }); return [Reflect.defineProperty(arguments, '0', { value: 'other' }), Reflect.defineProperty(arguments, '0', { value: 'locked' }), x, arguments[0]].join(); }
console.log(mapped('orig'));
''')


def test_map_set_hash_collisions_and_weak_compaction(run, workdir):
    """CATCHES: Map/Set implementations that lose or confuse entries whose keys share a hash bucket
    (the Number literals here collide with the strings in the reference's hash), mishandle
    deleting the head vs. a later link of a collision chain, re-adding after delete, or corrupt a
    WeakMap after many deletions trigger compaction; plus getOrInsertComputed validation and the
    symmetricDifference / isSubsetOf / isSupersetOf / difference set-like protocol checks."""
    check_script(run, workdir, G, "map_hash_collisions", r'''
const show = (f) => { try { const r = f(); return r instanceof Set ? '{' + [...r].join() + '}' : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const n1 = -1.1269110119884594e+226; // same bucket as 'collision'
const n2 = -2.0036421021815448e-269; // same bucket as 'beta'
const m = new Map();
m.set('collision', 1); m.set(n1, 2); m.set('collision', 3);
console.log(m.size, m.get('collision'), m.get(n1), m.has(n1 * 1), [...m.keys()].map(String).join('|'));
console.log(m.delete('collision'), m.has('collision'), m.has(n1), m.get(n1));
m.set('collision', 4);
console.log(m.delete(n1), m.get('collision'), m.has(n1), m.delete(n1), m.size);
console.log(m.get(n1), m.delete('nope'), [...m.entries()].join('|'));
const s = new Set(['beta', n2, 'beta']);
console.log(s.size, s.has('beta'), s.has(n2), s.delete(n2), s.has('beta'), s.delete(n2), s.has(n2), s.size);
s.add(n2); s.delete('beta'); console.log([...s].map(String).join('|'), s.has('beta'));
const ws = new WeakMap(); const keys = Array.from({ length: 10 }, (_, k) => ({ k }));
keys.forEach((k, idx) => ws.set(k, idx * 10));
for (let k = 0; k < 7; k++) ws.delete(keys[k]);
console.log(keys.map(k => ws.has(k) ? ws.get(k) : '-').join(','));
ws.set(keys[0], 'again'); console.log(ws.get(keys[0]), ws.get(keys[9]), ws.delete(keys[3]));
console.log(show(() => ws.getOrInsertComputed(keys[9], 5)), show(() => ws.getOrInsertComputed(keys[9], () => 'new')), show(() => ws.getOrInsertComputed(keys[1], (k) => 'computed ' + k.k)), ws.get(keys[1]));
console.log(show(() => ws.getOrInsertComputed(1, () => 1)), show(() => new Map().getOrInsertComputed('k', 3)));
const setLike = (items, extra = {}) => ({ size: items.length, has: (v) => items.includes(v), keys() { let k = 0; return { next() { return k < items.length ? { value: items[k++], done: false } : { done: true }; }, return() { console.log('  keys closed'); return {}; } }; }, ...extra });
console.log(show(() => new Set([1, 2]).symmetricDifference(setLike([2, 3, 1]))), show(() => new Set([1, 2, 3]).symmetricDifference(setLike([3, 3, 4]))));
console.log(show(() => new Set([1, 2, 3]).isSubsetOf(setLike([1, 2, 9]))), show(() => new Set([1, 2]).isSubsetOf(setLike([2, 1, 0]))));
console.log(show(() => new Set([1, 2]).isSupersetOf(setLike([1, 5]))), show(() => new Set([1, 2]).isSupersetOf(setLike([2]))));
console.log(show(() => new Set([1, 2, 3, 4]).difference(setLike([2, 4]))), show(() => new Set([1, 2, 3]).isDisjointFrom(setLike([7, 3]))));
console.log(show(() => new Set([1, 2, 3]).difference({ size: 1, has: () => false, keys() { return { next: 5 }; } })));
console.log(show(() => new Set([1, 2, 3]).difference({ size: 1, has: () => false, keys() { return { next() { return 7; } }; } })));
console.log(show(() => new Set([1]).symmetricDifference({ size: 1, has: () => false, keys() { return { next() { return 7; } }; } })));
''')


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_array_and_string_iterator_state_and_receivers(run, workdir, cli):
    """CATCHES: %ArrayIteratorPrototype%.next / %StringIteratorPrototype%.next accepting foreign
    receivers, iterators that stop working after unrelated own properties are added/deleted,
    TypedArray iterators not throwing once their view goes out of bounds (resizable buffer shrink)
    while length-tracking views keep iterating, and string iteration not pairing surrogates (also
    surrogates joined from separate halves). Pins the reference quirk that a frozen array
    iterator cannot advance."""
    check_script(run, workdir, G, "iterator_state_receivers", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const AIP = Object.getPrototypeOf([][Symbol.iterator]());
console.log(show(() => AIP.next.call({})), show(() => AIP.next.call(5)), show(() => AIP.next.call(new Map().keys())));
const it = [1, 2, 3][Symbol.iterator]();
it.extra = 1; delete it.extra;
Object.defineProperty(it, 'x', { get() { return 1; }, configurable: true });
console.log(show(() => it.next()), show(() => [...it].join()), show(() => it.next()));
const it2 = ['a', 'b'].entries(); Object.freeze(it2);
console.log(show(() => it2.next()), show(() => it2.next()));
const rab = new ArrayBuffer(8, { maxByteLength: 8 });
const ta = new Uint8Array(rab, 4, 2);
const ti = ta.values(); console.log(show(() => ti.next()));
rab.resize(2);
console.log(show(() => ti.next()));
const lta = new Uint8Array(rab); const lti = lta.keys(); rab.resize(3); console.log(show(() => [...lti].join()));
const ent = new Uint16Array([7, 8]).entries(); console.log(show(() => [...ent]));
console.log(show(() => [...'a😀b'].map(c => c.length).join()));
const SIP = Object.getPrototypeOf(''[Symbol.iterator]());
console.log(show(() => SIP.next.call({})), show(() => SIP.next.call('abc')));
const lone = '😀\ud83d'; console.log([...lone].map(c => c.length).join(), [...lone].length);
const joined = String.fromCharCode(0xd83d) + String.fromCharCode(0xde00);
console.log([...joined].length, [...(joined + 'x')].join('').length, joined === '😀');
const si = 'xy'[Symbol.iterator](); si.next(); si.next(); console.log(show(() => si.next()), show(() => si.next()));
''', cli=cli)


def test_generic_array_methods_callbacks_and_species(run, workdir):
    """CATCHES: Array.prototype iteration methods swallowing exceptions thrown by the callback (on
    real arrays and on array-likes), ArraySpeciesCreate not rejecting a length >= 2^32 or not using
    CreateDataPropertyOrThrow through a species Proxy, SpeciesConstructor not validating
    constructor/@@species (undefined/null fall back, primitives and non-constructors throw),
    Object.prototype.toLocaleString / __proto__ setter receiver checks, Object() with a newTarget,
    and generic copyWithin/fill/splice/reverse/toSpliced/with/join/lastIndexOf on array-likes."""
    check_script(run, workdir, G, "generic_array_species", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const boom = (tag) => () => { throw new SyntaxError(tag); };
for (const m of ['forEach', 'map', 'filter', 'reduce', 'reduceRight', 'some', 'every', 'find', 'findLastIndex', 'flatMap'])
  console.log(m, show(() => [3, 1, 2][m](boom(m), 0)), '|', show(() => Array.prototype[m].call({ length: 2, 0: 'a', 1: 'b' }, boom('generic ' + m), 0)));
console.log(show(() => Array.prototype.map.call({ length: 2 ** 32 }, x => x)), show(() => Array.prototype.filter.call({ length: 2 }, 5)));
const dp = []; dp.constructor = { [Symbol.species]: function () { return new Proxy([], { defineProperty(t, k, d) { console.log('  species define', k, d.value); return Reflect.defineProperty(t, k, d); } }); } };
console.log(show(() => dp.concat.call(Object.assign([1, 2], { constructor: dp.constructor }), [3]).length));
console.log(show(() => Object.assign([5, 6], { constructor: dp.constructor }).map(x => x * 2).length));
const ctorUndef = new ArrayBuffer(2); ctorUndef.constructor = undefined;
const ctorNum = new ArrayBuffer(2); ctorNum.constructor = 5;
const ctorPlain = new ArrayBuffer(2); ctorPlain.constructor = {};
const ctorNullSpecies = new ArrayBuffer(2); ctorNullSpecies.constructor = { [Symbol.species]: null };
const ctorBadSpecies = new ArrayBuffer(2); ctorBadSpecies.constructor = { [Symbol.species]: () => {} };
for (const [label, b] of [['undefined', ctorUndef], ['number', ctorNum], ['plain', ctorPlain], ['null species', ctorNullSpecies], ['arrow species', ctorBadSpecies]])
  console.log('species', label, show(() => b.slice(0).byteLength));
const p = Promise.resolve(1); p.constructor = 5;
console.log(show(() => p.then()));
console.log(show(() => Object.prototype.toLocaleString.call({ toString: 5 })), show(() => Object.prototype.toLocaleString.call(7)));
const protoSet = Object.getOwnPropertyDescriptor(Object.prototype, '__proto__').set;
console.log(show(() => protoSet.call(undefined, {})), show(() => protoSet.call(5, {})), show(() => protoSet.call({}, 5)));
const cyc = {}; console.log(show(() => { Object.create(cyc).__proto__; cyc.__proto__ = Object.create(cyc); }));
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: 7 });
console.log(Object.getPrototypeOf(Reflect.construct(Object, [], nt)) === Object.prototype);
class Sub extends Object { constructor() { super(); } }
console.log(Object.getPrototypeOf(new Sub()) === Sub.prototype, show(() => Reflect.construct(Object, [5], Sub) instanceof Sub));
console.log(show(() => [1, , 3].lastIndexOf(undefined)), show(() => [].lastIndexOf(1)), show(() => Array.prototype.lastIndexOf.call({ length: 0 }, 1)));
console.log(show(() => Array.prototype.copyWithin.call({ length: 5, 0: 'a', 1: 'b', 3: 'd' }, -2, -5, -3)), show(() => Array.prototype.fill.call({ length: 4 }, 'f', -3, -1)));
const sparse = { length: 4, 1: 'one', 3: 'three' };
console.log(show(() => Array.prototype.copyWithin.call(sparse, 0, 1)), show(() => Array.prototype.splice.call({ length: 3, 0: 'a', 2: 'c' }, 0, 1)));
console.log(show(() => Array.prototype.reverse.call({ length: 3, 0: 'a' })), show(() => Array.prototype.toSpliced.call({ length: 2, 0: 'x', 1: 'y' }, 1, 0, 'z')));
console.log(show(() => [].concat.call(1, 2)), show(() => [[1, [2, [3]]]].flat(Infinity)), show(() => [1, 2].flatMap((x) => [[x]])));
console.log(show(() => Array.prototype.join.call({ length: 3, 0: null, 1: undefined, 2: 0 })), show(() => [1, [2, [3]]].toLocaleString()), show(() => [{ toLocaleString: 5 }].toLocaleString()));
console.log(show(() => Array.prototype.at.call({ length: 3, 2: 'last' }, -1)), show(() => Array.prototype.with.call({ length: 2, 0: 1 }, -1, 9)), show(() => [1, 2].with(5, 0)));
''')


def test_reflect_set_get_with_foreign_receivers(run, workdir):
    """CATCHES: Reflect.set/Reflect.get with an explicit receiver not threading the receiver through
    a Proxy on the prototype chain, treating accessor-without-setter / getter-less accessors as
    writable/readable, ignoring a Proxy receiver's existing non-writable or accessor property
    (and its defineProperty trap: {value} for an existing property, a full descriptor for a new
    one), TypedArray receivers accepting out-of-range or '-0' keys, and non-extensible, primitive,
    frozen or Array receivers."""
    check_script(run, workdir, G, "reflect_foreign_receivers", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const recv = { tag: 'recv' };
const trapLog = [];
const proto = new Proxy({}, { set(t, k, v, r) { trapLog.push('set ' + k + ' recv=' + (r === recv)); return Reflect.set(t, k, v, r); }, get(t, k, r) { trapLog.push('get ' + String(k) + ' recv=' + (r === recv)); return 'from-trap'; } });
const child = Object.create(proto);
console.log(show(() => Reflect.set(child, 'k', 1, recv)), JSON.stringify(recv), show(() => Reflect.get(child, 'k', recv)), trapLog.join('; '));
const noSetter = { get x() { return 1; } };
const setterOnly = {}; Object.defineProperty(setterOnly, 'w', { set(v) {} });
console.log(show(() => Reflect.set(noSetter, 'x', 2, {})), show(() => Reflect.get(setterOnly, 'w', {})), show(() => Reflect.set(Object.create(noSetter), 'x', 2)));
const roTarget = {}; Object.defineProperty(roTarget, 'ro', { value: 1, writable: false, configurable: true });
const recvProxy = new Proxy(roTarget, {});
const accProxy = new Proxy({ get acc() { return 1; } }, {});
const okProxy = new Proxy({ data: 1 }, { defineProperty(t, k, d) { trapLog.push('define ' + k + ' ' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); } });
trapLog.length = 0;
console.log(show(() => Reflect.set({}, 'ro', 2, recvProxy)), show(() => Reflect.set({}, 'acc', 2, accProxy)), show(() => Reflect.set({}, 'data', 2, okProxy)), show(() => Reflect.set({}, 'fresh', 3, okProxy)), trapLog.join('; '));
const u8 = new Uint8Array(2);
console.log(show(() => Reflect.set({}, '1', 300, u8)), u8[1], show(() => Reflect.set({}, '5', 1, u8)), show(() => Reflect.set({}, '-0', 1, u8)), show(() => Reflect.set({}, 'named', 1, u8)), u8.named);
console.log(show(() => Reflect.set({}, 'k', 1, Object.preventExtensions({}))), show(() => Reflect.set({}, 'k', 1, 5)), show(() => Reflect.set({}, 'length', 1, [1, 2, 3])));
const frozenRecv = Object.freeze({ k: 0 });
console.log(show(() => Reflect.set({}, 'k', 1, frozenRecv)), show(() => Reflect.set({ k: 0 }, 'k', 7, { k: 1 })));
''')


def test_string_locale_case_mapping_and_protocol_fallbacks(run, workdir):
    """CATCHES: Turkish/Azeri and Lithuanian special casing (dotted/dotless I, combining dot above
    absorbed across non-230 marks, More_Above, accented capitals), String methods not falling back
    to the string path when Symbol.search/matchAll/replace/split is undefined or not rejecting a
    non-callable one, string length limits in repeat/concat, at()/substr() index coercions,
    String()/String.raw/fromCharCode edge cases and String/Number/Boolean wrappers honouring
    newTarget. Pins the reference quirk that a RegExp whose @@split is removed still splits as a
    regular expression."""
    check_script(run, workdir, G, "string_case_and_protocols", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const cps = (s) => [...s].map(c => c.codePointAt(0).toString(16)).join(' ');
const lower = (s, l) => cps(s.toLocaleLowerCase(l)), upper = (s, l) => cps(s.toLocaleUpperCase(l));
console.log('tr lower', lower('İ̖', 'tr'), '|', lower('Í̇', 'tr'), '|', lower('IBİ', 'tr'), '|', lower('I', 'az'), '|', lower('İ̖', 'tr'));
console.log('tr upper', upper('ıiq', 'tr'), '|', upper('ßi', 'az'));
console.log('lt lower', lower('Í', 'lt'), '|', lower('Ì', 'lt'), '|', lower('Ì̖', 'lt'), '|', lower('Ia', 'lt'), '|', lower('I', 'lt'), '|', lower('J́', 'lt'), '|', lower('Į́', 'lt'), '|', lower('Ĩ', 'lt'), '|', lower('I̖', 'lt'));
console.log('lt upper', upper('i̇', 'lt'), '|', upper('i̖̇x', 'lt'), '|', upper('j́̇', 'lt'), '|', upper('\u{1D422}̇', 'lt'), '|', upper('ì', 'lt'), '|', upper('ȧ', 'lt'));
console.log('default', lower('İ', 'en'), '|', upper('ﬀ'));
const big = 'y'.repeat(2 ** 25);
console.log(show(() => 'ab'.repeat(2 ** 29)), show(() => big.concat(big, 'z')), show(() => 'ab'.repeat(-1)), show(() => 'ab'.repeat(Infinity)));
console.log(show(() => 'abc'.at(-1)), show(() => 'abc'.at(-4)), show(() => 'abc'.at(3)), show(() => 'abc'.at(NaN)), show(() => 'abc'.at(1.9)));
console.log(show(() => 'abcdef'.substr(-2, NaN)), show(() => 'abcdef'.substr(NaN, 2)), show(() => 'abcdef'.substr(-10, 3)), show(() => 'abcdef'.substr(2, -1)), show(() => 'abcdef'.substr(1, Infinity)));
console.log(show(() => 'aXbX'.search({ [Symbol.search]: undefined, toString() { return 'X'; } })), show(() => 'aXbX'.search({ [Symbol.search]: 5 })));
console.log(show(() => [...'a1b2'.matchAll({ [Symbol.matchAll]: undefined, toString() { return '\\d'; } })].map(m => m[0]).join()));
console.log(show(() => 'a1b2'.matchAll({ [Symbol.matchAll]: 7 })));
console.log(show(() => [...'a1b2'.matchAll(undefined)].length));
console.log(show(() => 'a.b.c'.replaceAll({ [Symbol.replace]: undefined, toString() { return '.'; } }, '-')), show(() => 'a.b'.replaceAll({ [Symbol.replace]: 1 }, '-')));
console.log(show(() => 'a,b'.split({ [Symbol.split]: 1 })), show(() => 'a1b22c'.split(Object.assign(/(\d)+/, { [Symbol.split]: undefined }))));
const re = /(?:)/; re[Symbol.split] = null;
console.log(show(() => 'abc'.split(re)), show(() => 'abc'.split(re, 2)));
const re2 = /(-)|(\+)/; re2[Symbol.split] = undefined;
console.log(show(() => 'a-b+c'.split(re2)), show(() => 'a-b+c'.split(re2, 3)), show(() => 'a-b+c'.split(re2, 2)));
console.log(show(() => String()), show(() => new String().length), show(() => String.fromCharCode(NaN, Infinity, 65, -1).length), show(() => String.raw({ raw: ['a', 'b', 'c'] }, 1)), show(() => String.raw({ raw: { length: 2, 0: 'x', 1: 'y' } }, 'S', 'T')));
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: 'nope' });
const ws = Reflect.construct(String, ['wrapped'], nt);
console.log(Object.getPrototypeOf(ws) === String.prototype, ws.length, Object.getPrototypeOf(Reflect.construct(Number, [4], nt)) === Number.prototype, Object.getPrototypeOf(Reflect.construct(Boolean, [0], nt)) === Boolean.prototype);
const badNt = function () {}.bind(); Object.defineProperty(badNt, 'prototype', { get() { throw new Error('proto getter'); } });
console.log(show(() => Reflect.construct(String, ['x'], badNt)));
''')


def test_number_bigint_symbol_formatting_and_sum_precise(run, workdir):
    """CATCHES: toExponential/toPrecision rounding with carries (9.96 -> 1.0e+1) and zero/negative
    zero formatting, BigInt() conversion rules for BigInt/wrapper/boolean/string/Symbol/fractional
    inputs, BigInt.asIntN/asUintN with 0 and huge widths, Symbol/BigInt/Number prototype methods
    accepting foreign receivers, and Math.sumPrecise infinities/NaN/empty/overflow handling and
    correctly rounded (half-even) exact summation."""
    check_script(run, workdir, G, "number_bigint_sum_precise", r'''
const show = (f) => { try { const r = f(); return typeof r === 'bigint' ? r + 'n' : String(r); } catch (e) { return e.name + ': ' + e.message; } };
console.log((0).toExponential(0), (0).toExponential(2), (-0).toExponential(1), (9.96).toExponential(1), (9.5).toExponential(0), (0.000999).toExponential(1), (99.99).toExponential(2), (1.45).toExponential(1));
console.log((0).toPrecision(1), (0).toPrecision(3), (-0).toPrecision(2), (9.99).toPrecision(2), (0.000123).toPrecision(1), (123456).toPrecision(2));
console.log(show(() => BigInt(10n)), show(() => BigInt(Object(7n))), show(() => BigInt({ valueOf() { return 3n; } })), show(() => BigInt(true)), show(() => BigInt(' 0x1f ')), show(() => BigInt(Symbol())), show(() => BigInt(undefined)), show(() => BigInt(1.5)));
console.log(show(() => BigInt.asIntN(0, 5n)), show(() => BigInt.asUintN(0, -5n)), show(() => BigInt.asIntN(2 ** 27, -5n)), show(() => BigInt.asUintN(2 ** 27, 5n)), show(() => BigInt.asUintN(2 ** 27, -5n)), show(() => BigInt.asIntN(3, 7n)), show(() => BigInt.asUintN(3, -1n)));
console.log(show(() => Symbol.prototype.toString.call({})), show(() => Symbol.prototype.valueOf.call(1)), show(() => Object(Symbol('w')).description), show(() => BigInt.prototype.toString.call({})), show(() => BigInt.prototype.valueOf.call('1')), show(() => Object(5n).toString(16)));
console.log(show(() => Math.sumPrecise([Infinity, 1])), show(() => Math.sumPrecise([-Infinity, 1, -1])), show(() => Math.sumPrecise([Infinity, -Infinity])), show(() => Math.sumPrecise([])), show(() => Math.sumPrecise([1, -1])), show(() => Object.is(Math.sumPrecise([-0, -0]), -0)), show(() => Math.sumPrecise([1e308, 1e308, -1e308])));
console.log(show(() => Math.sumPrecise([2 ** 53, 1, 2 ** -100])), show(() => Math.sumPrecise([2 ** 53, -0.5, -(2 ** -54)])), show(() => Math.sumPrecise([2 ** 53 + 10, 1, 2 ** -100])), show(() => Math.sumPrecise([1, 1e100, 1, -1e100])), show(() => Math.sumPrecise([0.1, 0.2, 0.3])), show(() => Math.sumPrecise([1, '2'])));
console.log(show(() => Number.prototype.toFixed.call('1')), show(() => (1.005).toFixed(2)), show(() => (1e21).toFixed(2)), show(() => (123.456).toFixed(10)));
''')


def test_promise_receivers_and_keyed_combinator_abrupt_paths(run, workdir):
    """CATCHES: Promise statics/prototype methods accepting primitive receivers, Promise.prototype.finally
    on generic thenables, the Promise constructor's newTarget prototype fallback, combinators not
    rejecting when the capability's resolve throws, element functions honouring only the first of
    repeated settlements, and Promise.allKeyed/allSettledKeyed not turning every abrupt step
    (non-callable resolve, throwing ownKeys/getter/resolve/then) into a rejection, not filtering
    keys through a proxy's descriptors, or including symbol keys."""
    check_script(run, workdir, G, "promise_keyed_abrupt", r'''
const log = (...a) => console.log(...a);
const err = (e) => e instanceof Error ? e.name + ': ' + e.message : 'value ' + String(e);
const sync = (label, f) => { try { const r = f(); log(label, 'ok', typeof r); } catch (e) { log(label, err(e)); } };
sync('finally on number', () => Promise.prototype.finally.call(5));
sync('finally then non-callable', () => Promise.prototype.finally.call({ then: 5 }));
sync('finally generic', () => Promise.prototype.finally.call({ then(a, b) { log('  then got', typeof a, typeof b); return 'r'; } }, 7));
sync('withResolvers on number', () => Promise.withResolvers.call(5));
sync('reject on number', () => Promise.reject.call(5, 1));
sync('try on number', () => Promise.try.call(5, () => 1));
sync('ctor without new', () => Promise(() => {}));
sync('ctor non-callable', () => new Promise(5));
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: 0 });
const rp = Reflect.construct(Promise, [() => {}], nt);
log('newTarget fallback', Object.getPrototypeOf(rp) === Promise.prototype);
// capability whose resolve throws at the end of Promise.all with an empty iterable
function ThrowingResolve(executor) { executor(() => { throw new Error('resolve boom'); }, (e) => log('  capability reject got', err(e))); }
ThrowingResolve.resolve = (v) => Promise.resolve(v);
Promise.all.call(ThrowingResolve, []);
Promise.allSettled.call(ThrowingResolve, []);
Promise.allKeyed.call(ThrowingResolve, {});
// a then that settles the same element twice
const twice = { then(res) { res('first'); res('second'); } };
Promise.all([twice, 2]).then(v => log('all twice', JSON.stringify(v)));
Promise.allSettled([twice]).then(v => log('allSettled twice', JSON.stringify(v)));
Promise.any([{ then(_, rej) { rej('r1'); rej('r2'); } }]).catch(e => log('any twice', e.constructor.name, JSON.stringify(e.errors)));
Promise.allKeyed({ a: twice }).then(v => log('allKeyed twice', JSON.stringify(v)));
Promise.allSettledKeyed({ a: twice, b: Promise.reject(new Error('no')) }).then(v => log('allSettledKeyed', JSON.stringify(v, (k, x) => x instanceof Error ? x.message : x)));
// allKeyed abrupt paths reject the result promise
const C = function (ex) { return new Promise(ex); };
C.resolve = 5;
Promise.allKeyed.call(C, { a: 1 }).catch(e => log('allKeyed bad resolve', err(e)));
Promise.allKeyed(new Proxy({ a: 1 }, { ownKeys() { throw new RangeError('ownKeys boom'); } })).catch(e => log('allKeyed ownKeys', err(e)));
Promise.allKeyed({ get a() { throw new TypeError('getter boom'); } }).catch(e => log('allKeyed getter', err(e)));
Promise.allKeyed(5).catch(e => log('allKeyed primitive', err(e)));
const D = function (ex) { return new Promise(ex); };
D.resolve = () => { throw new EvalError('resolve call boom'); };
Promise.allKeyed.call(D, { a: 1 }).catch(e => log('allKeyed resolve throws', err(e)));
const E = function (ex) { return new Promise(ex); };
E.resolve = () => ({ get then() { throw new SyntaxError('then getter'); } });
Promise.allKeyed.call(E, { a: 1 }).catch(e => log('allKeyed then getter', err(e)));
const F = function (ex) { return new Promise(ex); };
F.resolve = () => ({ then() { throw new URIError('then call'); } });
Promise.allSettledKeyed.call(F, { a: 1 }).catch(e => log('allSettledKeyed then throws', err(e)));
Promise.allKeyed(new Proxy({ x: 1, y: 2 }, { getOwnPropertyDescriptor(t, k) { return k === 'y' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); } })).then(v => log('allKeyed proxy filter', JSON.stringify(v)));
const sym = Symbol('s');
Promise.allKeyed({ [sym]: 1, b: 2, hidden: 3 }).then(v => log('allKeyed keys', JSON.stringify(Object.keys(v)), v[sym]));
''')



@pytest.mark.parametrize("cli", TIERS)
def test_dead_result_regexp_calls_keep_side_effects(run, workdir, cli):
    """CATCHES: optimisations that drop RegExp exec/replace/match/split calls whose result is unused
    (hot loops in statement position) and thereby lose observable effects: lastIndex updates for
    sticky/global regexps (including fractional and non-writable lastIndex), the legacy
    RegExp.lastMatch/$1/leftContext/rightContext statics, empty-match advancement, calls to an own
    `exec` override, and TypeErrors from a non-writable lastIndex. All tiers must agree."""
    check_script(run, workdir, G, "dead_result_regexp", r'''
// Dead-result regexp calls (statement position) must keep every observable side effect.
function run(label, body) {
  for (let k = 0; k < 300; k++) body(k);
  console.log(label, RegExp.lastMatch, RegExp['$1'], RegExp.leftContext.length, RegExp.rightContext);
}
const sticky = /b/y;
run('exec sticky', (k) => { sticky.lastIndex = 1; sticky.exec('abc'); });
console.log('  sticky lastIndex', sticky.lastIndex);
const glob = /(\w)/g;
run('exec global', (k) => { glob.exec('xyz'); });
console.log('  global lastIndex', glob.lastIndex);
const plain = /(c)(d)?/;
run('exec plain', (k) => { plain.exec('abcd' + (k % 2 ? '' : 'e')); });
const frozenLi = /q(.)/g; Object.defineProperty(frozenLi, 'lastIndex', { writable: false, value: 0 });
let threw = 0;
run('exec non-writable lastIndex', (k) => { try { frozenLi.exec('aqz'); } catch (e) { threw++; } });
console.log('  threw', threw);
const fracLi = /(m)/y;
run('exec fractional lastIndex', (k) => { fracLi.lastIndex = 0.5; fracLi.exec('mm'); });
console.log('  frac lastIndex', fracLi.lastIndex);
run('replace literal global empty', (k) => { 'ab'.replace(/(?:)/g, '-'); });
run('replace literal', (k) => { 'hello world'.replace(/(o) w/, '_'); });
run('match literal global', (k) => { 'a1b22'.match(/(\d)+/g); });
run('match literal empty', (k) => { 'xy'.match(/z*/g); });
const own = /(e)/g; own.exec = function (s) { own.calls = (own.calls || 0) + 1; return null; };
run('replace with own exec', (k) => { 'eee'.replace(own, 'E'); });
console.log('  own exec calls', own.calls);
const st2 = /(s)/y; st2.lastIndex = 'x';
run('replace sticky odd lastIndex', (k) => { st2.lastIndex = 'x'; 'ss'.replace(st2, 'S'); });
const fli = /(f)/g; Object.defineProperty(fli, 'lastIndex', { writable: false, value: 0 });
let rthrew = 0;
run('replace non-writable lastIndex', (k) => { try { 'ff'.replace(fli, 'F'); } catch (e) { rthrew++; } });
console.log('  replace threw', rthrew);
const flagsOwn = /(g)/g; Object.defineProperty(flagsOwn, 'flags', { value: 'g' });
run('replace with own flags', (k) => { 'gg'.replace(flagsOwn, 'G'); });
run('split literal', (k) => { 'a,b;c'.split(/([,;])/); });
run('split limit', (k) => { 'a,b;c'.split(/([,;])/, 1); });
var subjects = ['aXbXc', 'XX', 'none', 'X'];
function hotReplace() { for (let i = 0; i < subjects.length; i++) { subjects[i].replace(/(X)|$/g, '-'); } }
for (let r = 0; r < 300; r++) hotReplace();
console.log('fused replace', JSON.stringify([RegExp.lastMatch, RegExp['$1'], RegExp.leftContext, RegExp.input]));
function hotEmpty() { for (let i = 0; i < subjects.length; i++) { subjects[i].replace(/(?:)/g, '-'); } }
for (let r = 0; r < 300; r++) hotEmpty();
console.log('fused empty replace', JSON.stringify([RegExp.lastMatch, RegExp.leftContext, RegExp.rightContext]));
function hotMatch() { for (let i = 0; i < subjects.length; i++) { subjects[i].match(/b?(X)/g); } }
for (let r = 0; r < 300; r++) hotMatch();
console.log('fused match', JSON.stringify([RegExp.lastMatch, RegExp['$1'], RegExp.leftContext, RegExp.rightContext]));
function hotMatchEmpty() { for (let i = 0; i < subjects.length; i++) { subjects[i].match(/(?:)/g); } }
for (let r = 0; r < 300; r++) hotMatchEmpty();
console.log('fused empty match', JSON.stringify([RegExp.lastMatch, RegExp.leftContext, RegExp.input]));
function hotSingle() { for (let i = 0; i < subjects.length; i++) { subjects[i].replace(/n(o)/, '_'); } }
for (let r = 0; r < 300; r++) hotSingle();
console.log('fused non-global', JSON.stringify([RegExp.lastMatch, RegExp['$1'], RegExp.input]));
const origReplace = String.prototype.replace;
let patchedCalls = 0;
String.prototype.replace = function (...a) { patchedCalls++; return origReplace.apply(this, a); };
for (let r = 0; r < 50; r++) hotReplace();
String.prototype.replace = origReplace;
const origMatch = String.prototype.match;
let matchCalls = 0;
String.prototype.match = function (...a) { matchCalls++; return origMatch.apply(this, a); };
for (let r = 0; r < 50; r++) hotMatch();
String.prototype.match = origMatch;
console.log('patched calls', patchedCalls, matchCalls);
const origSym = RegExp.prototype[Symbol.replace];
let symCalls = 0;
RegExp.prototype[Symbol.replace] = function (...a) { symCalls++; return origSym.apply(this, a); };
for (let r = 0; r < 50; r++) hotReplace();
RegExp.prototype[Symbol.replace] = origSym;
const origExec = RegExp.prototype.exec;
let execCalls = 0;
RegExp.prototype.exec = function (s) { execCalls++; return origExec.call(this, s); };
for (let r = 0; r < 10; r++) { hotReplace(); hotMatch(); }
RegExp.prototype.exec = origExec;
console.log('symbol/exec calls', symCalls, execCalls);
subjects = [1, 'X'];
let subjectThrew = 0;
for (let r = 0; r < 20; r++) { try { hotReplace(); } catch (e) { subjectThrew++; } }
console.log('non-string subject', subjectThrew, RegExp.lastMatch);
''', cli=cli)


def test_date_parse_iso_variants_and_to_primitive(run, workdir):
    """CATCHES: Date.parse accepting malformed ISO strings (wrong field widths, bad or compact zone
    offsets after 'T', comma fractions, signed -000000 years, an empty time part) or rejecting the
    lenient space-separated form with +hhmm/+hh offsets, legacy 'Mon D YYYY GMT+hhmm' parsing, and
    Date.prototype[Symbol.toPrimitive] hint validation / method order / receiver check."""
    check_script(run, workdir, G, "date_parse_variants", r'''
const cases = ['2020-01-02 03:04', '2020-1-2 3:04', '2020-123-01 10:00', '2020-01-xx 10:00', '2020-01-02T10:00+0530', '2020-01-02 10:00+0530',
  '2020-01-02T10:00+053', '2020-01-02T10:00+ab:cd', '2020-01-02 10:00+05', '2020-01-02T10:00+05', '99999999999999999999-01-01 00:00', '+002020-01-02T00:00Z', '-000000-01-01T00:00Z',
  '2020-01-02T', '2020-01-02 ', 'Jan 2 2020 10:00 GMT+0130', '2 Jan 2020', '2020-01-02T10:00:00.5Z', '2020-01-02T10:00:00,5Z', '1/2/2020', '2020/01/02'];
for (const c of cases) { const t = Date.parse(c); console.log(JSON.stringify(c), isNaN(t) ? 'NaN' : new Date(t).toISOString()); }
const d = new Date(0);
d.valueOf = () => ({}); d.toString = () => 'str-form';
console.log(d[Symbol.toPrimitive]('number'), d[Symbol.toPrimitive]('default'));
const d2 = new Date(0); d2.toString = () => ({}); d2.valueOf = () => 42;
console.log(d2[Symbol.toPrimitive]('string'), `${d2}`, d2 + 1);
const d3 = new Date(0); d3.toString = () => ({}); d3.valueOf = () => ({});
try { d3[Symbol.toPrimitive]('number'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { d3[Symbol.toPrimitive]('bogus'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { Date.prototype[Symbol.toPrimitive].call(1, 'number'); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log(new Date(Object(5)).getTime(), new Date({ valueOf() { return '1970-01-01T00:00:01Z'; } }).getTime(), new Date(new Date(77)).getTime(), new Date(true).getTime());
''')


def test_disposable_stacks_error_aggregation(run, workdir):
    """CATCHES: AsyncDisposableStack.disposeAsync not running disposers in reverse order, not folding
    a synchronous throw / a rejected promise / a failing PromiseResolve (throwing `constructor`
    getter) into nested SuppressedErrors, mishandling null/undefined await-only entries, disposing
    twice, DisposableStack error aggregation, use() validation, and move() leaving the source usable."""
    check_script(run, workdir, G, "disposable_errors", r'''
const err = (e) => e instanceof Error ? e.name + ': ' + e.message + (e.error ? ' [error=' + err(e.error) + ', suppressed=' + err(e.suppressed) + ']' : '') : 'value ' + String(e);
(async () => {
  const order = [];
  const s = new AsyncDisposableStack();
  s.use(null);
  s.defer(() => { order.push('sync thrower'); throw new RangeError('sync throw'); });
  s.adopt('res', (v) => { order.push('adopt ' + v); });
  s.use({ [Symbol.asyncDispose]() { order.push('async dispose'); return Promise.reject(new TypeError('async reject')); } });
  const badPromise = Promise.resolve(1); Object.defineProperty(badPromise, 'constructor', { get() { order.push('ctor getter'); throw new EvalError('ctor getter boom'); } });
  s.defer(() => { order.push('returns bad promise'); return badPromise; });
  s.use(undefined);
  try { await s.disposeAsync(); } catch (e) { console.log('disposeAsync rejected:', err(e)); }
  console.log(order.join(' > '));
  console.log('disposed', s.disposed, await s.disposeAsync());
  const s2 = new AsyncDisposableStack(); s2.use(null); s2.use(undefined);
  console.log('only sentinels', await s2.disposeAsync());
  const ds = new DisposableStack();
  ds.defer(() => { throw new Error('first'); }); ds.defer(() => { throw new Error('second'); });
  try { ds.dispose(); } catch (e) { console.log('dispose:', err(e)); }
  try { new DisposableStack().use(5); } catch (e) { console.log('use primitive:', err(e)); }
  try { new DisposableStack().use({}); } catch (e) { console.log('use no method:', err(e)); }
  try { new AsyncDisposableStack().use({ [Symbol.asyncDispose]: 1 }); } catch (e) { console.log('async use bad method:', err(e)); }
  const moved = new DisposableStack(); moved.defer(() => console.log('moved ran')); const m2 = moved.move();
  try { moved.defer(() => {}); } catch (e) { console.log('after move:', err(e)); }
  m2.dispose();
})();
''')


def test_function_bind_tostring_apply_and_dynamic_constructors(run, workdir):
    """CATCHES: Function.prototype.bind computing length/name wrongly for missing, infinite,
    non-number or fractional target lengths, ignoring a null or trapped prototype, or not
    consulting a Proxy target's getOwnPropertyDescriptor; Function.prototype.toString output for
    natives, accessors, bound functions, proxies and methods; apply() with holes, accessors and
    inherited elements; Function/GeneratorFunction honouring newTarget; and dynamic-function
    parameter parsing errors."""
    check_script(run, workdir, G, "function_bind_tostring", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
function f(a, b, c) { return [this === undefined ? 'u' : typeof this, a, b, c].join('/'); }
const noLen = function (a, b) {}; delete noLen.length;
console.log(noLen.bind().length, Object.getOwnPropertyNames(noLen).includes('length'));
const infLen = function () {}; Object.defineProperty(infLen, 'length', { value: Infinity }); console.log(infLen.bind(null, 1).length);
const negInf = function () {}; Object.defineProperty(negInf, 'length', { value: -Infinity }); console.log(negInf.bind().length);
const strLen = function () {}; Object.defineProperty(strLen, 'length', { value: '3' }); console.log(strLen.bind().length);
const fracLen = function () {}; Object.defineProperty(fracLen, 'length', { value: 2.7 }); console.log(fracLen.bind(null, 1).length);
const noName = function () {}; Object.defineProperty(noName, 'name', { value: 42 }); console.log(JSON.stringify(noName.bind().name));
const nullProto = function () {}; Object.setPrototypeOf(nullProto, null); console.log(Object.getPrototypeOf(Function.prototype.bind.call(nullProto)));
const pf = new Proxy(function target(x) { return x * 2; }, { getPrototypeOf() { return Array.prototype; }, has(t, k) { console.log('  has', k); return k in t; }, getOwnPropertyDescriptor(t, k) { console.log('  gopd', k); return Reflect.getOwnPropertyDescriptor(t, k); } });
const bp = Function.prototype.bind.call(pf, null, 5);
console.log(bp(), bp.name, bp.length, Object.getPrototypeOf(bp) === Array.prototype);
console.log(show(() => Function.prototype.toString.call(bp)), show(() => Function.prototype.toString.call(pf)), show(() => Function.prototype.toString.call({})));
console.log(Function.prototype.toString.call(Math.max), Function.prototype.toString.call(Object.getOwnPropertyDescriptor(Map.prototype, 'size').get), Function.prototype.toString.call(Array.prototype[Symbol.iterator]));
console.log(Function.prototype.toString.call(Function.prototype), Function.prototype.toString.call(class A { m() {} }.prototype.m));
console.log(f.apply(null, [1, , 3]), f.apply(null, { length: 2, 0: 'x' }), show(() => f.apply(null, 5)));
const withGetter = [1, 2]; Object.defineProperty(withGetter, 1, { get() { return 'G'; } });
console.log(f.apply(null, withGetter), f.call(undefined, ...'ab'));
const protoHole = [1, , 3]; Array.prototype[1] = 'fromProto';
console.log(f.apply(null, protoHole)); delete Array.prototype[1];
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: null });
const made = Reflect.construct(Function, ['return 1'], nt);
console.log(Object.getPrototypeOf(made) === Function.prototype, made());
const GF = Object.getPrototypeOf(function* () {}).constructor;
const g = Reflect.construct(GF, ['yield 1'], nt);
console.log(Object.getPrototypeOf(g) === GF.prototype, [...g()].join());
console.log(show(() => Function('a', 'return a +')), show(() => new Function('}', '')), show(() => Function('/*', '*/){')));
console.log(show(() => Function('a,b', 'return a+b')(1, 2)), show(() => Function('...r', 'return r.length')(1, 2, 3)));
''')


def test_uint8array_base64_and_hex_edge_cases(run, workdir):
    """CATCHES: Uint8Array.fromBase64/setFromBase64 mishandling lastChunkHandling (strict extra
    bits, stop-before-partial, loose partial chunks), whitespace around padding, base64url
    alphabet checks, maxLength-limited decoding (read/written counts), non-Uint8Array receivers,
    immutable target buffers, option validation, and hex decoding/encoding errors."""
    check_script(run, workdir, G, "uint8array_base64_hex", r'''
const show = (f) => { try { const r = f(); return r instanceof Uint8Array ? '[' + r.join() + ']' : JSON.stringify(r); } catch (e) { return e.name + ': ' + e.message; } };
const dec = (s, o) => show(() => Uint8Array.fromBase64(s, o));
console.log('strict extra bits 2', dec('QR==', { lastChunkHandling: 'strict' }), dec('QR==', { lastChunkHandling: 'loose' }));
console.log('strict extra bits 3', dec('QUI=', { lastChunkHandling: 'strict' }), dec('QUJ=', { lastChunkHandling: 'strict' }), dec('QUJ=', {}));
console.log('stop-before-partial pad', dec('QUJD QQ=', { lastChunkHandling: 'stop-before-partial' }), dec('QUJDQQ', { lastChunkHandling: 'stop-before-partial' }));
console.log('ws after pad', dec('QQ= \n =', {}), dec('QQ==  ', {}), dec('QQ=x', {}), dec('QQ= =x', {}), dec('Q=', {}));
console.log('loose partial', dec('QUJDQ', {}), dec('QUJDQUI', {}), dec('QUJDQR', {}));
console.log('url', dec('-_8', { alphabet: 'base64url' }), dec('+/8', { alphabet: 'base64url' }), dec('-_8', {}));
const target = new Uint8Array(4);
console.log('setFromBase64', show(() => target.setFromBase64('QUJDREVG')), '[' + target.join() + ']');
console.log('setFromBase64 partial fit', show(() => new Uint8Array(2).setFromBase64('QUJD')), show(() => new Uint8Array(1).setFromBase64('QUJD')));
console.log('setFromBase64 zero', show(() => new Uint8Array(0).setFromBase64('QUJD')), show(() => new Uint8Array(0).setFromBase64('!!')));
console.log('setFromBase64 error', show(() => new Uint8Array(8).setFromBase64('QUJD!!')));
console.log('non-u8', show(() => Uint8Array.prototype.setFromBase64.call(new Int8Array(2), 'QQ==')), show(() => Uint8Array.prototype.toBase64.call(new Uint16Array(1))), show(() => Uint8Array.prototype.setFromHex.call(new Int8Array(2), '00')));
console.log('hex', show(() => Uint8Array.fromHex('0aFf')), show(() => Uint8Array.fromHex('abc')), show(() => Uint8Array.fromHex('zz')), show(() => new Uint8Array(1).setFromHex('aabb')), show(() => new Uint8Array(4).setFromHex('aagg')));
const imm = new Uint8Array(new ArrayBuffer(4).transferToImmutable());
console.log('immutable', show(() => imm.setFromBase64('QUJD')), show(() => imm.setFromHex('00')), show(() => imm.setFromBase64('')));
console.log('toBase64', new Uint8Array([251, 255]).toBase64(), new Uint8Array([251, 255]).toBase64({ alphabet: 'base64url', omitPadding: true }), new Uint8Array([1, 2, 3, 4]).toHex());
console.log(show(() => Uint8Array.fromBase64(5)), show(() => Uint8Array.fromBase64('', { alphabet: 'x' })), show(() => Uint8Array.fromBase64('', { lastChunkHandling: 'x' })), show(() => Uint8Array.fromBase64('', 5)));
''')


def test_promise_combinator_element_functions_settle_once(run, workdir):
    """CATCHES: Promise.all/allSettled/any/allKeyed/allSettledKeyed element functions that can be
    invoked more than once (a subclass whose resolve() returns a thenable calling the callback
    twice must keep only the first value/reason per element), wrong result shapes or ordering, and
    AggregateError errors lists for any()."""
    check_script(run, workdir, G, "promise_element_once", r'''
const report = (label, p) => p.then(v => console.log(label, 'fulfilled', JSON.stringify(v)), e => console.log(label, 'rejected', JSON.stringify(e instanceof AggregateError ? e.errors : e)));
class TwiceOk extends Promise {}
TwiceOk.resolve = (v) => ({ then(f, r) { f('ok:' + v); f('again:' + v); } });
class TwiceErr extends Promise {}
TwiceErr.resolve = (v) => ({ then(f, r) { r('no:' + v); r('no2:' + v); } });
report('all ok', TwiceOk.all([1, 2]));
report('allSettled ok', TwiceOk.allSettled([1, 2]));
report('any ok', TwiceOk.any([1, 2]));
report('allKeyed ok', TwiceOk.allKeyed({ a: 1, b: 2 }));
report('allSettledKeyed ok', TwiceOk.allSettledKeyed({ a: 1 }));
report('all err', TwiceErr.all([1, 2]));
report('allSettled err', TwiceErr.allSettled([1, 2]));
report('any err', TwiceErr.any([1, 2]));
report('allKeyed err', TwiceErr.allKeyed({ a: 1 }));
report('allSettledKeyed err', TwiceErr.allSettledKeyed({ a: 1, b: 2 }));
''')


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_iterator_zip_and_zip_keyed_protocol(run, workdir, cli):
    """CATCHES: Iterator.zip/zipKeyed not reading a proxy input through ownKeys/getOwnPropertyDescriptor/
    get (skipping undefined and non-enumerable entries), not closing already-opened inputs (in
    reverse order) when opening or padding fails, wrong longest-mode padding alignment or padding
    iterator closing, strict-mode length mismatch detection, option validation, return()/next()
    after completion, re-entrancy errors, and inner next/result errors closing the other inputs.
    Pins the reference quirk that the zip helper's next() on a foreign receiver reports done."""
    check_script(run, workdir, G, "iterator_zip_protocol", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const src = (tag, items, extra = {}) => ({ [Symbol.iterator]() { let k = 0; return { next() { return k < items.length ? { value: items[k++], done: false } : { done: true }; }, return() { console.log('  close ' + tag); return {}; }, ...extra }; } });
const log = [];
const tracer = { ownKeys(t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor(t, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, get(t, k) { log.push('get ' + String(k)); return t[k]; } };
const keyedInput = new Proxy({ a: [1, 2], skip: undefined, b: src('b', ['x', 'y', 'z']) }, tracer);
Object.defineProperty(keyedInput, 'hidden', { value: [9], enumerable: false });
log.length = 0;
const zk = Iterator.zipKeyed(keyedInput);
console.log(log.join(', '));
console.log(show(() => [...zk]));
console.log(show(() => Iterator.zipKeyed(new Proxy({ a: [1] }, { getOwnPropertyDescriptor() { throw new RangeError('gopd boom'); } }))));
console.log(show(() => Iterator.zipKeyed({ a: [1], b: 5 })));
console.log(show(() => Iterator.zipKeyed({ a: src('a', [1]), get b() { throw new EvalError('getter boom'); } })));
console.log(show(() => [...Iterator.zipKeyed({ a: [1, 2, 3], b: ['p'] }, { mode: 'longest', padding: { b: 'PAD' } })]));
console.log(show(() => Iterator.zipKeyed({ a: src('a', [1]) }, { mode: 'longest', padding: { get a() { throw new TypeError('pad getter'); } } })));
console.log(show(() => [...Iterator.zip([[1, 2, 3], ['p']], { mode: 'longest', padding: ['P0', 'P1', 'P2'] })]));
console.log(show(() => [...Iterator.zip([[1], [2, 3]], { mode: 'longest', padding: src('pad', ['only']) })]));
console.log(show(() => Iterator.zip([src('a', [1])], { mode: 'longest', padding: 5 })), show(() => Iterator.zip([src('a', [1])], { mode: 'longest', padding: { [Symbol.iterator]() { throw new SyntaxError('pad iter'); } } })));
console.log(show(() => Iterator.zip([src('a', [1])], { mode: 'longest', padding: { [Symbol.iterator]() { return { next() { throw new URIError('pad next'); } }; } } })));
console.log(show(() => Iterator.zip([src('a', [1]), src('b', [1])], { mode: 'longest', padding: { [Symbol.iterator]() { return { next() { return { value: 0, done: false }; }, return() { throw new Error('pad close'); } }; } } })));
console.log(show(() => Iterator.zip({ [Symbol.iterator]() { let n = 0; return { next() { if (n++ === 0) return { value: src('first', [1]), done: false }; throw new RangeError('outer next'); }, return() { console.log('  close outer'); } }; } })));
console.log(show(() => Iterator.zip({ [Symbol.iterator]() { let n = 0; return { next() { return n++ === 0 ? { value: src('first', [1]), done: false } : { value: 42, done: false }; }, return() { console.log('  close outer'); return {}; } }; } })));
console.log(show(() => Iterator.zip([], { mode: 'bogus' })), show(() => Iterator.zip([], 5)), show(() => Iterator.zip(5)));
const strict = Iterator.zip([[1, 2], src('s', [1])], { mode: 'strict' });
console.log(show(() => strict.next()), show(() => strict.next()));
const strict2 = Iterator.zip([src('s1', [1]), [1, 2]], { mode: 'strict' });
console.log(show(() => strict2.next()), show(() => strict2.next()));
const z = Iterator.zip([src('r1', [1, 2]), src('r2', [3, 4])]);
console.log(show(() => z.next()), show(() => z.return()), show(() => z.next()), show(() => z.return()));
const zfresh = Iterator.zip([src('f1', [1])]); console.log(show(() => zfresh.return()), show(() => zfresh.next()));
let reent; reent = Iterator.zip([{ [Symbol.iterator]() { return { next() { return reent.next(); } }; } }]);
console.log(show(() => reent.next()));
let reent2; reent2 = Iterator.zip([{ [Symbol.iterator]() { return { next() { reent2.return(); return { value: 1, done: false }; } }; } }]);
console.log(show(() => reent2.next()));
const badNext = Iterator.zip([{ [Symbol.iterator]() { return { next: 5 }; } }, src('ok', [1])]);
console.log(show(() => badNext.next()));
const badResult = Iterator.zip([src('ok2', [1]), { [Symbol.iterator]() { return { next() { return 3; } }; } }]);
console.log(show(() => badResult.next()));
const throwingNext = Iterator.zip([src('ok3', [1]), { [Symbol.iterator]() { return { next() { throw new Error('inner next'); } }; } }]);
console.log(show(() => throwingNext.next()));
const longestThrow = Iterator.zip([[1, 2], { [Symbol.iterator]() { let n = 0; return { next() { if (n++) throw new Error('late'); return { value: 'v', done: false }; } }; } }], { mode: 'longest' });
console.log(show(() => longestThrow.next()), show(() => longestThrow.next()));
const ZP = Object.getPrototypeOf(Iterator.zip([]));
console.log(show(() => Iterator.zip([]).next.call({})), Object.prototype.toString.call(Iterator.zip([])));
''', cli=cli)


def test_module_namespace_reflection_during_tdz(run, workdir):
    """CATCHES: module namespace exotic objects whose [[GetOwnProperty]]/[[Get]]/[[DefineOwnProperty]]
    (via hasOwnProperty, propertyIsEnumerable, Reflect.getOwnPropertyDescriptor, Object.keys,
    Reflect.get through a prototype chain, Reflect.defineProperty) do not throw ReferenceError for
    an uninitialised export in an import cycle, or that report the wrong descriptor / define
    results / strict-assignment TypeError after initialisation. Pins the reference quirk that
    Reflect.set through an object inheriting from a namespace reports true."""
    write_files(workdir, {
        "a.mjs": r'''
import { probe } from './b.mjs';
probe('during a (TDZ)');
export let x = 'X';
export const fn = () => 1;
probe('after a init');
''',
        "b.mjs": r'''
import * as nsA from './a.mjs';
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
export function probe(label) {
  console.log(label);
  console.log('  hasOwnProperty', show(() => Object.prototype.hasOwnProperty.call(nsA, 'x')), show(() => Object.prototype.hasOwnProperty.call(nsA, 'zz')));
  console.log('  propertyIsEnumerable', show(() => Object.prototype.propertyIsEnumerable.call(nsA, 'x')), show(() => Object.prototype.propertyIsEnumerable.call(nsA, Symbol.toStringTag)));
  console.log('  gOPD', show(() => Reflect.getOwnPropertyDescriptor(nsA, 'x')), show(() => Reflect.getOwnPropertyDescriptor(nsA, 'zz')));
  console.log('  keys', show(() => Object.keys(nsA)), show(() => Reflect.ownKeys(nsA).length));
  console.log('  get via chain', show(() => Reflect.get(Object.create(nsA), 'x', {})), show(() => Reflect.get(nsA, 'x')));
  console.log('  set', show(() => Reflect.set(nsA, 'x', 1)), show(() => Reflect.set(Object.create(nsA), 'x', 1, {})), show(() => { nsA.x = 2; }));
  console.log('  define', show(() => Reflect.defineProperty(nsA, 'x', {})), show(() => Reflect.defineProperty(nsA, 'x', { value: 'X' })), show(() => Reflect.defineProperty(nsA, 'x', { writable: false })));
  console.log('  has/delete', show(() => 'x' in nsA), show(() => Reflect.deleteProperty(nsA, 'x')), show(() => Reflect.deleteProperty(nsA, 'zz')));
}
''',
    })
    check_script(run, workdir, G, "namespace_reflection_tdz", "import './a.mjs';\n", filename="main.mjs")


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_typed_array_accessors_set_subarray_and_from(run, workdir, cli):
    """CATCHES: %TypedArray.prototype% length/byteLength/byteOffset/buffer getters not brand-checking
    or not reporting 0 for an out-of-bounds view, the abstract %TypedArray% constructor, set()
    offset coercion (NaN -> 0, negative/Infinity) and bounds/content-type checks for TypedArray
    and array-like sources (including overlapping copies), length-tracking subarray() results and
    @@species alignment errors, TypedArray.from/of receiver, @@iterator and mapFn handling,
    toLocaleString through Number.prototype.toLocaleString, and search/slice/copyWithin
    re-validating after a detach or shrink performed by user code."""
    check_script(run, workdir, G, "typed_array_set_subarray_from", r'''
const show = (f) => { try { const r = f(); return ArrayBuffer.isView(r) ? r.constructor.name + '[' + Array.from(r).join() + ']' : typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const TAProto = Object.getPrototypeOf(Int8Array.prototype);
const getter = (name) => Object.getOwnPropertyDescriptor(TAProto, name).get;
const rab = new ArrayBuffer(8, { maxByteLength: 16 });
const view = new Int16Array(rab, 2);
const fixed = new Int16Array(rab, 2, 2);
for (const name of ['length', 'byteLength', 'byteOffset', 'buffer'])
  console.log(name, show(() => getter(name).call(view) === rab ? 'rab' : getter(name).call(view)), show(() => getter(name).call(fixed) === rab ? 'rab' : getter(name).call(fixed)), show(() => getter(name).call({})));
rab.resize(4);
console.log('after shrink', show(() => getter('length').call(fixed)), show(() => getter('byteLength').call(fixed)), show(() => getter('byteOffset').call(fixed)), show(() => getter('length').call(view)));
const tag = Object.getOwnPropertyDescriptor(TAProto, Symbol.toStringTag).get;
console.log(tag.call(new Float32Array(1)), tag.call([]), show(() => new (Object.getPrototypeOf(Int8Array))()));
const t = new Uint8Array(4);
console.log(show(() => { t.set([1, 2], NaN); return t; }), show(() => t.set(new Uint8Array(3), 2)), show(() => t.set([1, 2, 3], 2)), show(() => t.set(new BigInt64Array(1))), show(() => t.set([1], -1)), show(() => t.set([1], Infinity)));
console.log(show(() => { const u = new Uint8Array([1, 2, 3, 4]); u.set(u.subarray(0, 3), 1); return u; }), show(() => { const s = new Float64Array([1.5, -1]); const d = new Int8Array(2); d.set(s); return d; }));
const grow = new ArrayBuffer(4, { maxByteLength: 12 });
const tracking = new Uint8Array(grow);
const sub = tracking.subarray(1);
const subEnd = tracking.subarray(1, 3);
grow.resize(8);
console.log('subarray tracking', sub.length, subEnd.length, sub.byteOffset);
class Sp extends Uint8Array { static get [Symbol.species]() { return Uint16Array; } }
console.log(show(() => new Sp(new ArrayBuffer(8, { maxByteLength: 8 })).subarray(2)), show(() => new Sp(4).subarray(1, 3)));
console.log(show(() => Uint8Array.from.call(undefined, [1])), show(() => Uint8Array.from.call(() => {}, [1])), show(() => Uint8Array.from({ [Symbol.iterator]: 3 })), show(() => Uint8Array.from([1], 2)));
console.log(show(() => Uint8Array.from({ length: 3, 0: 5, 2: 7 }, (v, k) => (v ?? 0) + k * 100)), show(() => Int8Array.from(new Set([1, 2]), function (v) { return v * this.m; }, { m: 3 })));
console.log(show(() => Uint8Array.of.call(Int16Array, 1, -2)), show(() => Uint8Array.of.call(function () { return new Uint8Array(1); }, 1, 2)), show(() => Uint8Array.of.call(Object, 1)));
const savedTLS = Number.prototype.toLocaleString;
Number.prototype.toLocaleString = function () { return '<' + this + '>'; };
console.log(new Uint8Array([1, 2]).toLocaleString(), new BigInt64Array(0).toLocaleString());
Number.prototype.toLocaleString = 5;
console.log(show(() => new Uint8Array([1]).toLocaleString()), show(() => new Uint8Array(0).toLocaleString()));
Number.prototype.toLocaleString = savedTLS;
console.log(show(() => TAProto.toLocaleString.call([])));
const detachMe = new Uint8Array([1, 2, 3]);
console.log(show(() => detachMe.lastIndexOf(3, { valueOf() { detachMe.buffer.transfer(); return 2; } })), show(() => new Uint8Array([1, 2]).includes(1, NaN)), show(() => new Uint8Array([1, 2]).includes(2, -1)));
const shrinkBuf = new ArrayBuffer(6, { maxByteLength: 6 });
const shrinkView = new Uint8Array(shrinkBuf); shrinkView.set([1, 2, 3, 4, 5, 6]);
class Shrinker extends Uint8Array { static get [Symbol.species]() { return function (n) { shrinkBuf.resize(0); return new Uint8Array(n); }; } }
const sh = new Shrinker(shrinkBuf);
console.log(show(() => sh.slice(1, 4)));
const cwBuf = new ArrayBuffer(6, { maxByteLength: 6 });
const cw = new Uint8Array(cwBuf); cw.set([1, 2, 3, 4, 5, 6]);
console.log(show(() => cw.copyWithin(0, { valueOf() { cwBuf.resize(4); return 2; } })), show(() => { const d = new Uint8Array([1, 2]); return d.copyWithin(0, { valueOf() { d.buffer.transfer(); return 1; } }); }));
console.log(show(() => new Uint8Array(new ArrayBuffer(4).transferToImmutable()).setFromHex('00ff')), show(() => Uint8Array.prototype.setFromHex.call(new Uint16Array(1), '00')));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_array_constructors_of_from_and_engine_limits(run, workdir, cli):
    """CATCHES: new Array(n) creating real elements instead of holes (for small and large n),
    Array()/new Array() length validation, newTarget/subclass prototypes, Array.of/Array.from with
    non-constructor or frozen-result receivers (an iterator must be closed when defining fails),
    ToLength/2^32 checks and iterator-result validation in Array.from, the engine's array length
    cap in fill/toSpliced, includes() fromIndex coercion, generic reverse() with holes, and
    Array.prototype.toString falling back to the builtin tag when `join` is not callable."""
    check_script(run, workdir, G, "array_constructors_limits", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const holes = (a) => a.length + ':' + Array.from(a.keys()).filter(k => k in a).join('');
for (const n of [0, 1, 4, 32, 33]) { const a = new Array(n); a[1] = 'x'; console.log('new Array(' + n + ')', holes(a), Object.keys(a).join(), a.indexOf('x')); }
const filled = new Array(3); filled.fill(7, 1); console.log(JSON.stringify(filled), 0 in filled, show(() => Array(2.5)), show(() => new Array(-1)), show(() => Array('3').length), Array(1, 2).join());
const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { value: 'x' });
console.log(Object.getPrototypeOf(Reflect.construct(Array, [2], nt)) === Array.prototype, Reflect.construct(Array, [2], nt).length);
class MyArr extends Array {}
console.log(Object.getPrototypeOf(new MyArr(3)) === MyArr.prototype, new MyArr(3).length, MyArr.of(1, 2) instanceof MyArr, MyArr.from([1]).constructor.name);
console.log(show(() => Array.of.call(undefined, 1, 2)), show(() => Array.of.call(function () { return Object.freeze({}); }, 1)), show(() => Array.of.call(function (n) { this.n = n; }, 'a')));
console.log(show(() => Array.from.call(undefined, { length: 2 ** 32 })), show(() => Array.from({ [Symbol.iterator]() { return { next() { return 5; } }; } })), show(() => Array.from({ length: 2, 0: 1 }, () => { throw new TypeError('map arraylike'); })));
console.log(show(() => Array.from({ [Symbol.iterator]: 1 })), show(() => Array.from([], 5)), show(() => Array.from.call(function () { return Object.freeze([]); }, { length: 1, 0: 1 })));
console.log(show(() => Array.from.call(function () { return Object.freeze([]); }, { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { console.log('  from closed'); return {}; } }; } })));
console.log(show(() => new Array(2 ** 21).fill(0)), show(() => Array.prototype.toSpliced.call({ length: 2 ** 21 }, 0, 0)), show(() => Array.prototype.fill.call({ length: 3 }, 1, 0, 2 ** 21).length));
console.log(show(() => [1, 2, 3].includes(1, -Infinity)), show(() => [1, 2, 3].includes(1, NaN)), show(() => [1, 2, 3].includes(3, -1)), show(() => [1, 2, 3].includes(1, 1.5)), show(() => [1, 2].includes(1, Infinity)), show(() => [NaN].includes(NaN)), show(() => Array.prototype.includes.call({ length: 2, 1: undefined }, undefined, -1)));
console.log(show(() => Array.prototype.reverse.call({ length: 4, 1: 'b' })), show(() => Array.prototype.reverse.call({ length: 5, 0: 'a', 4: 'e', 2: 'c' })));
console.log(show(() => Array.prototype.toString.call({ join: 5 })), show(() => { const a = [1]; a.join = null; return a.toString(); }), show(() => Array.prototype.toString.call({ join: 1, [Symbol.toStringTag]: 'Tagged' })), show(() => Array.prototype.toString.call(new Proxy([], { get(t, k) { return k === 'join' ? undefined : t[k]; } }))));
console.log(show(() => Array.prototype.toString.call(5)), show(() => Array.prototype.toString.call(Object.assign(new Date(0), { join: 0 }))), show(() => Array.prototype.toString.call(Object.assign(/x/, { join: 0 }))), show(() => Array.prototype.toString.call(Object.assign(function () {}, { join: 0 }))));
console.log(show(() => Array.prototype.toString.call(Object.assign(new Boolean(true), { join: 0 }))), show(() => Array.prototype.toString.call(Object.assign(new String('s'), { join: 0 }))), show(() => Array.prototype.toString.call(Object.assign(new Error('e'), { join: 0 }))), show(() => (function () { arguments.join = 0; return Array.prototype.toString.call(arguments); })()));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_object_integrity_levels_and_exotic_descriptors(run, workdir, cli):
    """CATCHES: Object.freeze/seal/preventExtensions/isFrozen/isSealed mishandling TypedArrays (views
    with elements can't be frozen or sealed; length-tracking or resizable-backed views can't be made
    non-extensible) and proxies (trap order, false trap results, descriptors reported through
    getOwnPropertyDescriptor), defineProperties/create argument checks, getOwnPropertyDescriptor and
    defineProperty on TypedArray integer keys, mapped arguments that stay mapped after a failed
    define, and accessor-to-data conversion. Pins the reference's propertyIsEnumerable returning
    false for TypedArray indices."""
    check_script(run, workdir, G, "object_integrity_exotic", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const full = new Uint8Array(2), empty = new Uint8Array(0);
const rabView = new Uint8Array(new ArrayBuffer(2, { maxByteLength: 4 }));
const fixedOnRab = new Uint8Array(new ArrayBuffer(4, { maxByteLength: 8 }), 0, 2);
const sabView = new Uint8Array(new SharedArrayBuffer(2, { maxByteLength: 4 }), 0, 2);
console.log('freeze', show(() => Object.freeze(full)), show(() => Object.freeze(empty) === empty), show(() => Object.seal(full)), show(() => Object.isFrozen(empty)));
console.log('preventExtensions', show(() => Object.preventExtensions(rabView)), show(() => Object.preventExtensions(fixedOnRab)), show(() => Object.isExtensible(sabView) + '/' + Object.isExtensible(Object.preventExtensions(sabView))), show(() => Reflect.preventExtensions(rabView)));
const pe = Object.preventExtensions(new Uint8Array(1));
console.log('frozen checks', Object.isFrozen(pe), Object.isSealed(pe), Object.isSealed(Object.preventExtensions(new Uint8Array(0))));
const frozenProxy = new Proxy(Object.freeze({ a: 1, get g() { return 1; } }), {});
const sealedProxy = new Proxy(Object.seal({ a: 1 }), {});
const hiding = new Proxy(Object.preventExtensions({}), { ownKeys() { return []; } });
console.log('proxy integrity', Object.isFrozen(frozenProxy), Object.isSealed(frozenProxy), Object.isFrozen(sealedProxy), Object.isSealed(sealedProxy), Object.isFrozen(hiding), Object.isFrozen(new Proxy({}, {})));
const ghost = new Proxy(Object.preventExtensions({ x: 1 }), { getOwnPropertyDescriptor(t, k) { return undefined; }, ownKeys() { return ['x']; } });
console.log('ghost', show(() => Object.isFrozen(ghost)));
const plog = [];
const freezeMe = new Proxy({ a: 1, get b() { return 2; } }, { defineProperty(t, k, d) { plog.push(k + ':' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); }, preventExtensions(t) { plog.push('preventExtensions'); return Reflect.preventExtensions(t); } });
Object.freeze(freezeMe); console.log('freeze proxy', plog.join(' '));
console.log(show(() => Object.freeze(new Proxy({ a: 1 }, { defineProperty() { return false; } }))), show(() => Object.freeze(new Proxy({}, { preventExtensions() { return false; } }))));
console.log(show(() => Object.defineProperties(1, {})), show(() => Object.defineProperties({}, null)), show(() => Object.create(null, undefined) !== null));
console.log(show(() => Object.prototype.propertyIsEnumerable.call(new Proxy({ a: 1 }, { getOwnPropertyDescriptor() { return undefined; } }), 'a')), show(() => Object.prototype.propertyIsEnumerable.call(new Uint8Array(2), '1')), show(() => Object.prototype.propertyIsEnumerable.call(new Uint8Array(2), '5')));
console.log(show(() => ({ a: 1 }).__lookupGetter__('a')), show(() => Object.create({ a: 1 }).__lookupSetter__('a')), show(() => Object.prototype.__lookupGetter__.call(5, 'x')));
console.log(show(() => Object.getOwnPropertyDescriptor(new Uint8Array(1), 'foo')), show(() => Object.getOwnPropertyDescriptor(Object.assign(new Uint8Array(1), { foo: 1 }), 'foo')), show(() => Object.getOwnPropertyDescriptor({}, 'missing')), show(() => Object.getOwnPropertyDescriptor(new Uint8Array(1), '0')));
console.log(show(() => Reflect.defineProperty(new Uint8Array(1), '0', {})), show(() => Reflect.defineProperty(new Uint8Array(1), '-0', { value: 1 })), show(() => Reflect.defineProperty(new Uint8Array(1), '0', { value: 1, writable: false })), show(() => Reflect.defineProperty(new Uint8Array(1), '0', { get() {} })));
function mapped(a) {
  Object.defineProperty(arguments, '0', { configurable: false });
  const r1 = Reflect.defineProperty(arguments, '0', { enumerable: false });
  a = 'changed';
  return [r1, arguments[0], Reflect.defineProperty(arguments, '0', { value: 'via define' }), a].join();
}
console.log(mapped('orig'));
const acc = {}; Object.defineProperty(acc, 'p', { get() { return 1; }, configurable: true });
Object.defineProperty(acc, 'p', { writable: true }); console.log(JSON.stringify(Object.getOwnPropertyDescriptor(acc, 'p')));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_iterator_helper_steps_generators_and_string_iterators(run, workdir, cli):
    """CATCHES: iterator helpers (filter/map/flatMap/drop/take) not closing the source when the
    callback throws or flatMap's mapper returns a non-iterable (strings are rejected too) or an inner
    iterator throws, flatMap return() not closing the active inner iterator, drop/take limit
    validation and early completion, helper methods on non-object receivers, the RegExp String
    Iterator (non-global matchAll yields once, empty-match advancement, receiver check), the
    Iterator constructor with a newTarget, generator brand checks and return()/throw() through
    finally blocks, and string iteration of separately created surrogate halves."""
    check_script(run, workdir, G, "iterator_helper_steps", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const mk = (tag, n = 3) => { let k = 0; return { __proto__: Iterator.prototype, next() { k++; return k > n ? { done: true } : { value: k, done: false }; }, return() { console.log('  close ' + tag); return {}; } }; };
const boom = (m) => () => { throw new RangeError(m); };
console.log('filter throws', show(() => mk('filter').filter(boom('f')).next()));
console.log('flatMap mapper throws', show(() => mk('fm1').flatMap(boom('fm')).next()));
console.log('flatMap primitive', show(() => mk('fm2').flatMap(() => 5).next()));
console.log('flatMap string', show(() => mk('fm3').flatMap(() => 'ab').next()));
const badInner = { [Symbol.iterator]() { return { next() { throw new SyntaxError('inner'); } }; } };
console.log('flatMap inner throws', show(() => mk('fm4').flatMap(() => badInner).next()));
const fm = mk('fm5').flatMap((v) => [v, v * 10]);
console.log('flatMap', show(() => fm.next()), show(() => fm.next()), show(() => fm.return()), show(() => fm.next()));
const innerClose = { [Symbol.iterator]() { return { next() { return { value: 'in', done: false }; }, return() { console.log('  close inner'); return {}; } }; } };
const fm6 = mk('fm6').flatMap(() => innerClose); fm6.next(); console.log('flatMap return with inner', show(() => fm6.return()));
const dropAll = mk('drop', 2).drop(5);
console.log('drop exhausted', show(() => dropAll.next()), show(() => dropAll.next()));
console.log('drop', show(() => [...mk('d2', 4).drop(2)]), show(() => mk('d3').drop(-1)), show(() => mk('d4').drop(NaN).next()));
const tk = mk('take').take(1);
console.log('take', show(() => tk.next()), show(() => tk.next()), show(() => tk.next()), show(() => mk('t0').take(0).next()), show(() => mk('tbad').take('x')));
console.log('map', show(() => [...mk('m').map((v, k) => v + ':' + k)]), show(() => mk('mt').map(boom('m')).next()));
console.log('non-object receivers', show(() => Iterator.prototype.some.call(5, () => 1)), show(() => Iterator.prototype.map.call(null, () => 1)), show(() => Iterator.prototype.toArray.call('ab')));
const RSIP = Object.getPrototypeOf('a'.matchAll(/a/g));
console.log('regexp string iterator', show(() => RSIP.next.call({})), show(() => [...RegExp.prototype[Symbol.matchAll].call(/a(.)/, 'axay')].map(m => m[0]).join()));
const rsi = 'xx'.matchAll(/x/g); rsi.next(); rsi.next(); console.log(show(() => rsi.next()), show(() => rsi.next()));
const rsiEmpty = [...'ab'.matchAll(/(?:)/gu)].map(m => m.index).join(); console.log('empty matches', rsiEmpty);
function F() {} F.prototype = { marker: 1 };
console.log(Reflect.construct(Iterator, [], F).marker);
const gen = (function* () { yield 1; })();
const GP = Object.getPrototypeOf(gen);
console.log('generator receivers', show(() => GP.next.call({})), show(() => GP.return.call(5)), show(() => GP.throw.call(undefined, 1)));
const g2 = (function* () { try { yield 1; } finally { return 'from finally'; } })(); g2.next();
console.log('generator return override', show(() => g2.return('ignored')), show(() => g2.next()));
const g3 = (function* () { try { yield 1; } finally { yield 'cleanup'; } })(); g3.next();
console.log('generator yield in finally', show(() => g3.return('r')), show(() => g3.next()), show(() => g3.next()));
const sIt = (String.fromCharCode(0xd83d) + String.fromCharCode(0xde00) + 'z')[Symbol.iterator]();
console.log('string iterator pair', show(() => sIt.next()), show(() => sIt.next()), show(() => sIt.next()));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_async_generator_return_and_receivers(run, workdir, cli):
    """CATCHES: AsyncGenerator.prototype.return awaiting its argument incorrectly in each state
    (suspended-start, suspended at a yield with finally blocks, completed; fulfilled vs rejected
    promise vs thenable), queued next/return requests settling out of order, brand checks that
    throw synchronously instead of rejecting, and sync generator throw()/return() after completion."""
    check_script(run, workdir, G, "async_generator_return", r'''
const fmt = (p) => p.then(v => 'ok ' + JSON.stringify(v), e => 'err ' + (e instanceof Error ? e.message : String(e)));
(async () => {
  async function* ag() { try { console.log('  body start'); yield 1; yield 2; } finally { console.log('  ag finally'); } }
  console.log('return before start (fulfil):', await fmt(ag().return(Promise.resolve('R'))));
  console.log('return before start (reject):', await fmt(ag().return(Promise.reject(new Error('RJ')))));
  const it = ag(); await it.next();
  console.log('return at yield (reject):', await fmt(it.return(Promise.reject(new Error('at-yield')))));
  console.log('after:', await fmt(it.next()), await fmt(it.return('late')), await fmt(it.throw(new Error('late throw'))));
  const it2 = ag(); await it2.next();
  console.log('return at yield (fulfil):', await fmt(it2.return(Promise.resolve('v'))));
  const thenable = { then(r) { console.log('  thenable then'); r('T'); } };
  console.log('return thenable:', await fmt(ag().return(thenable)));
  const done = ag(); await done.next(); await done.next(); await done.next();
  console.log('return on completed:', await fmt(done.return(Promise.resolve('C'))), await fmt(done.return(Promise.reject(new Error('C2')))));
  const queued = ag();
  const results = await Promise.all([fmt(queued.next()), fmt(queued.return(Promise.resolve('Q'))), fmt(queued.next())]);
  console.log('queued:', results.join(' | '));
  const AGP = Object.getPrototypeOf(ag());
  console.log('receivers:', await fmt(AGP.next.call({})), await fmt(AGP.return.call(5)), await fmt(AGP.throw.call(undefined)));
  function* g() { try { yield 1; } finally { console.log('  sync finally'); } }
  const s = g(); s.next(); s.next();
  try { s.throw(new Error('on completed')); } catch (e) { console.log('sync throw on completed:', e.message); }
  console.log('sync return on completed:', JSON.stringify(s.return('rv')));
})();
''', cli=cli)


def test_json_surrogates_reviver_deletes_and_abrupt_callbacks(run, workdir):
    """CATCHES: JSON.stringify not escaping lone surrogates (while keeping real astral characters,
    including U+10FFFD, intact), JSON.parse \\u escapes not pairing only a high+low surrogate
    sequence, the reviver deleting a property it made non-configurable (must be kept), symbol keys
    of a grafted Proxy holder leaking into the walk, and exceptions from the reviver, a holder's
    defineProperty/deleteProperty traps, a replacer, toJSON or BigInt serialisation not propagating."""
    check_script(run, workdir, G, "json_surrogates_reviver", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
const units = (s) => Array.from({ length: s.length }, (_, k) => s.charCodeAt(k).toString(16)).join(' ');
const cps = (s) => Array.from(s, (c) => c.codePointAt(0).toString(16)).join(' ');
console.log(cps(JSON.stringify(String.fromCharCode(0xDBFF) + String.fromCharCode(0xDFFD))), cps(JSON.stringify('\u{10FFFD}')), JSON.stringify('\uDBFF'), JSON.stringify('x\uDFFDy'), JSON.stringify('😀\uD83D'));
console.log(units(JSON.parse('"\\uD83D\\u0041"')), '|', units(JSON.parse('"\\uD83D\\uDE00"')), '|', units(JSON.parse('"\\uDE00\\uD83D"')), '|', units(JSON.parse('"\\uD83Dx"')), '|', units(JSON.parse('"\\uD83D\\uD83D\\uDE00"')), '|', units(JSON.parse(JSON.stringify('\u{10FFFD}'))));
const kept = JSON.parse('{"a":1,"b":2,"c":3}', function (k, v) { if (k === 'a') Object.defineProperty(this, 'b', { configurable: false }); if (k === 'b' || k === 'c') return undefined; return v; });
console.log(JSON.stringify(kept), Object.keys(kept).join());
const sym = Symbol('s');
const res = JSON.parse('{"first":0,"later":{"x":1}}', function (k, v) { if (k === 'first') this.later = new Proxy({ x: 2, [sym]: 'sym' }, {}); return v; });
console.log(JSON.stringify(res), Object.getOwnPropertySymbols(res.later).length);
console.log(show(() => JSON.parse('[1,2]', (k, v) => { if (k === '1') throw new RangeError('reviver threw'); return v; })));
console.log(show(() => JSON.parse('{"a":0,"b":{"c":1}}', function (k, v) { if (k === 'a') this.b = new Proxy({ c: 1 }, { defineProperty() { throw new EvalError('define trap'); } }); return v; })));
console.log(show(() => JSON.parse('{"a":0,"b":{"c":1}}', function (k, v) { if (k === 'a') this.b = new Proxy({ c: 1 }, { deleteProperty() { throw new URIError('delete trap'); } }); return k === 'c' ? undefined : v; })));
console.log(show(() => JSON.stringify(new Proxy({ a: 1, [sym]: 2 }, {}))), show(() => JSON.stringify({ a: 1 }, (k, v) => { if (k === 'a') throw new TypeError('replacer threw'); return v; })));
console.log(show(() => JSON.stringify({ toJSON() { throw new SyntaxError('toJSON threw'); } })), show(() => JSON.stringify(10n)), show(() => JSON.stringify({ b: 1n })), show(() => { BigInt.prototype.toJSON = function () { return this.toString() + 'n'; }; return JSON.stringify({ b: 1n }); }));
''')


def test_reflect_collections_atomics_and_escape_leftovers(run, workdir):
    """CATCHES: Reflect.set on revoked proxies / throwing set traps and setters / falsy trap results,
    Reflect.construct defaulting newTarget to the target and validating its arguments,
    Reflect.getOwnPropertyDescriptor on TypedArray expandos, a throwing proxy set trap in the
    Error stack setter, Map.groupBy/Object.groupBy callback errors and grouping, Map/Set iterator
    brand checks (the reference shares one next() between Map and Set iterators),
    FinalizationRegistry.unregister bookkeeping, Atomics.notify count coercion and BigInt64 atomics,
    and unescape/escape handling of malformed or wide escapes."""
    check_script(run, workdir, G, "reflect_collections_leftovers", r'''
const show = (f) => { try { const r = f(); return typeof r === 'object' && r !== null ? JSON.stringify(r) : String(r); } catch (e) { return e.name + ': ' + e.message; } };
// Reflect
const revoked = Proxy.revocable({}, {}); revoked.revoke();
console.log('Reflect.set revoked', show(() => Reflect.set(revoked.proxy, 'a', 1)), show(() => Reflect.set(new Proxy({}, { set() { throw new RangeError('set trap'); } }), 'a', 1)));
console.log('Reflect.set setter throws', show(() => Reflect.set({ set a(v) { throw new EvalError('setter ' + v); } }, 'a', 1, {})), show(() => Reflect.set(new Proxy({}, { set: () => 0 }), 'a', 1)), show(() => Reflect.set(new Proxy({}, { set: () => 1 }), 'a', 1, {})));
function Point(x) { this.x = x; this.nt = new.target === Point; }
console.log('Reflect.construct defaults', show(() => Reflect.construct(Point, [3])), show(() => Reflect.construct(Point, [3], Object)), show(() => Reflect.construct(() => {}, [])), show(() => Reflect.construct(Point, 5)));
console.log('Reflect.getOwnPropertyDescriptor', show(() => Reflect.getOwnPropertyDescriptor(new Uint8Array(1), 'foo')), show(() => Reflect.getOwnPropertyDescriptor(Object.assign(new Uint8Array(1), { foo: 'bar' }), 'foo')), show(() => Reflect.getOwnPropertyDescriptor(1, 'x')));
// Error.prototype.stack setter through a proxy whose set trap throws
const setStack = Object.getOwnPropertyDescriptor(Error.prototype, 'stack').set;
console.log('stack set trap throws', show(() => setStack.call(new Proxy({ stack: 's' }, { set() { throw new URIError('stack trap'); } }), 'v')));
// collections
console.log('Map.groupBy', show(() => Map.groupBy([1, 2], () => { throw new TypeError('group cb'); })), show(() => [...Map.groupBy([1, 2, 3, 4], (v) => v % 2)].map(([k, v]) => k + ':' + v.join('/')).join(' ')), show(() => Map.groupBy([1], 5)));
console.log('Object.groupBy', show(() => Object.groupBy([1, 2, 3], (v, k) => (v + k) % 2 ? 'odd' : 'even')), show(() => Object.groupBy('aba', (c) => c)), show(() => Object.groupBy([1], () => { throw new SyntaxError('ogb'); })));
console.log('Map iterator brand', show(() => new Map().keys().next.call({})), show(() => new Set([1]).values().next.call(new Map([[1, 2]]).entries())));
const fr = new FinalizationRegistry(() => {});
const tok = {}, target = {};
fr.register(target, 'held', tok);
console.log('FinalizationRegistry.unregister', fr.unregister(tok), fr.unregister(tok), fr.unregister({}), show(() => fr.unregister(1)), show(() => FinalizationRegistry.prototype.unregister.call({}, tok)));
fr.register(target, 'a', tok); fr.register({}, 'b', tok);
console.log('  multi token', fr.unregister(tok), fr.unregister(tok));
// Atomics.notify counts
const i32 = new Int32Array(new SharedArrayBuffer(8));
console.log('Atomics.notify', Atomics.notify(i32, 0, Infinity), Atomics.notify(i32, 0, -5), Atomics.notify(i32, 1, NaN), Atomics.notify(i32, 0), show(() => Atomics.notify(new Int32Array(2), 0, 1)), show(() => Atomics.notify(new Uint8Array(new SharedArrayBuffer(2)), 0)));
const b64 = new BigInt64Array(new SharedArrayBuffer(16));
console.log('Atomics bigint', Atomics.add(b64, 0, 5n), Atomics.exchange(b64, 0, -1n), Atomics.load(b64, 0), Atomics.compareExchange(b64, 0, -1n, 7n), Atomics.notify(b64, 1, 1), show(() => Atomics.add(b64, 0, 1)));
// unescape / escape
console.log('unescape', JSON.stringify(unescape('%uZZZZ%u12%41%4g%%u0041%')), escape('a béĀ+@/'));
''')
