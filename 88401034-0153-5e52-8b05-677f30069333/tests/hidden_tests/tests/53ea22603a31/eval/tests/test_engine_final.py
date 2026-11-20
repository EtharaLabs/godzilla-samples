"""Final gap-closing pass over the JS engine's library and compiler corners: Array iterator factories
on nullish receivers, RegExpExec's fallback to the built-in exec, Iterator.zip's strict-mode
end-of-input protocol checks, iterator-helper `next` receiver checks, Array.from / Array.fromAsync
over huge array-likes with a non-constructor receiver, Lithuanian soft-dotted uppercasing,
immutable-ArrayBuffer write rejection in Uint8Array base64/hex setters, DeletePropertyOrThrow
through proxies in the Array mutators, iterator-result validation in AggregateError / TypedArray
construction, private writes to primitives, strict-mode PutValue re-checks, ToBigInt of nullish
values, the bytecode compiler's binding/destructuring/for-of head shapes (on every tier) and
module evaluation of cyclic graphs with top-level await."""

import pytest

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

TIERS = [pytest.param([], id="jit"), pytest.param(["--tier=bytecode"], id="bytecode"),
         pytest.param(["--tier=interp"], id="interp")]

PRELUDE = r'''
const T = (label, f) => {
  let out;
  try { out = String(f()); } catch (e) { out = 'threw ' + e.name + ': ' + e.message; }
  console.log(label + ' => ' + out);
};
'''


def check_js(run, workdir, name, body, **kw):
    """Run PRELUDE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRELUDE + body, **kw)


def test_array_iterator_factories_and_regexp_exec_fallback(run, workdir):
    """CATCHES: Array.prototype.values/keys/entries that accept null/undefined receivers (they must
    throw a TypeError from ToObject) or fail to box primitive receivers ('ab' iterates its indices),
    and RegExpExec (used by RegExp.prototype.test) that does not fall back to the built-in exec when
    the receiver's `exec` property is not callable -- for a real RegExp the built-in runs, for a
    plain object the brand check must throw."""
    check_js(run, workdir, "array_iterators_regexp_exec_fallback", r'''
T('values(null)', () => Array.prototype.values.call(null));
T('keys(undefined)', () => Array.prototype.keys.call(undefined));
T('entries(null)', () => Array.prototype.entries.call(null));
T('entries(string)', () => [...Array.prototype.entries.call('ab')].join('|'));
T('keys(number)', () => [...Array.prototype.keys.call(3)].length);
T('values(array-like)', () => [...Array.prototype.values.call({ length: 2, 0: 'x', 1: 'y' })].join());
T('test on plain object with non-callable exec', () => RegExp.prototype.test.call({ exec: 1 }, 'x'));
T('test on plain object without exec', () => RegExp.prototype.test.call({}, 'x'));
T('regexp with non-callable own exec', () => { const r = /a/g; r.exec = 5; return [r.test('cat'), r.lastIndex].join(); });
T('regexp with null own exec', () => { const r = /z/; r.exec = null; return r.test('cat'); });
T('match with non-callable own exec', () => { const r = /(a)(t)/; r.exec = 'nope'; return JSON.stringify('cat'.match(r)); });
''')


def test_iterator_zip_strict_and_helper_receivers(run, workdir):
    """CATCHES: Iterator.zip in mode 'strict' that, once the first input is exhausted, does not
    validate the remaining inputs with IteratorStep (a non-callable cached `next` or a primitive
    iterator result must throw TypeErrors, while genuinely finished inputs end cleanly and a still-
    running input is a length mismatch), and zip/concat/helper `next` methods that accept primitive
    receivers instead of throwing."""
    check_js(run, workdir, "zip_strict_and_receivers", r'''
const iterOf = (it) => ({ [Symbol.iterator]() { return it; } });
T('strict, other next not callable', () => Iterator.zip([[], iterOf({ next: 42 })], { mode: 'strict' }).next());
T('strict, other result primitive', () => Iterator.zip([[], iterOf({ next() { return 7; } })], { mode: 'strict' }).next());
T('strict, other also done', () => JSON.stringify(Iterator.zip([[], iterOf({ next() { return { done: true }; } })], { mode: 'strict' }).next()));
T('strict, other still running', () => Iterator.zip([[], [1]], { mode: 'strict' }).next());
T('strict, equal lengths', () => JSON.stringify([...Iterator.zip([[1, 2], ['a', 'b']], { mode: 'strict' })]));
T('shortest stops early', () => JSON.stringify([...Iterator.zip([[1, 2, 3], ['a']])]));
T('longest pads', () => JSON.stringify([...Iterator.zip([[1, 2], ['a']], { mode: 'longest', padding: ['p', 'q'] })]));
T('zip next on number', () => Iterator.zip([[1]]).next.call(1));
T('concat next on number', () => Iterator.concat([1]).next.call(1));
T('concat next on string', () => Iterator.concat([1]).next.call('s'));
''')


def test_array_from_huge_array_like_without_constructor(run, workdir):
    """CATCHES: Array.from / Array.fromAsync with a non-constructor `this` (an arrow function) that
    do not fall back to a plain Array, or that accept an array-like whose length exceeds 2^32 - 1
    instead of throwing RangeError (synchronously for Array.from, as a rejection for fromAsync),
    plus ordinary non-constructor results for small array-likes."""
    check_js(run, workdir, "array_from_non_constructor", r'''
const arrow = () => 0;
T('from arrow small', () => { const r = Array.from.call(arrow, { length: 3, 0: 'a', 2: 'c' }); return [Array.isArray(r), r.length, r.join('-')].join(); });
T('from arrow huge', () => Array.from.call(arrow, { length: 2 ** 32 }));
T('from arrow max ok length shape', () => typeof Array.from.call(arrow, { length: 0 }));
T('of arrow', () => { const r = Array.of.call(arrow, 1, 2); return [Array.isArray(r), r.join()].join(); });
Array.fromAsync.call(arrow, { length: 2 ** 32 }).then(v => console.log('fromAsync huge => resolved ' + v), e => console.log('fromAsync huge => rejected ' + e.name + ': ' + e.message));
Array.fromAsync.call(arrow, { length: 2, 0: Promise.resolve('p'), 1: 'q' }).then(v => console.log('fromAsync small => ' + Array.isArray(v) + ' ' + v.join()));
''')


def test_lithuanian_uppercase_soft_dotted_letters(run, workdir):
    """CATCHES: toLocaleUpperCase('lt') that only removes a combining dot above (U+0307) after the
    ASCII i/j, instead of after every Soft_Dotted letter -- including the mathematical italic/bold/
    script/fraktur/double-struck/sans-serif/monospace i and j (U+1D422..U+1D693) and the Cyrillic
    modifier letters U+1E04C/U+1E04D -- or that drops dots after non-soft-dotted letters."""
    check_js(run, workdir, "lithuanian_soft_dotted", r'''
const soft = [0x69, 0x6A, 0x12F, 0x1D456, 0x1D457, 0x1D48A, 0x1D48B, 0x1D4BE, 0x1D4BF, 0x1D4F2, 0x1D4F3, 0x1D526, 0x1D527,
  0x1D55A, 0x1D55B, 0x1D58E, 0x1D58F, 0x1D5C2, 0x1D5C3, 0x1D5F6, 0x1D5F7, 0x1D62A, 0x1D62B, 0x1D65E, 0x1D65F, 0x1D692,
  0x1D693, 0x1E04C, 0x1E04D];
const hex = (s) => [...s].map(c => c.codePointAt(0).toString(16)).join(' ');
for (let k = 0; k < soft.length; k += 6) {
  const chunk = soft.slice(k, k + 6);
  console.log(hex(chunk.map(c => String.fromCodePoint(c) + '̇x').join('').toLocaleUpperCase('lt')));
}
console.log('not soft dotted keeps dot: ' + hex('ȧ \u{1D400}̇'.toLocaleUpperCase('lt')));
console.log('other locale keeps dot: ' + hex('\u{1D456}̇'.toLocaleUpperCase('en')));
''')


def test_immutable_buffers_and_array_buffer_slice_receivers(run, workdir):
    """CATCHES: Uint8Array.prototype.setFromBase64/setFromHex that write into a view over an
    immutable ArrayBuffer (transferToImmutable) instead of throwing, immutable buffers that can be
    resized or written through a view, and ArrayBuffer.prototype.slice that accepts a
    SharedArrayBuffer or a plain object receiver; SharedArrayBuffer.prototype.slice must still copy
    the requested window (and an inverted range gives an empty buffer)."""
    check_js(run, workdir, "immutable_buffers_slice", r'''
T('setFromBase64 on immutable', () => JSON.stringify(new Uint8Array(new ArrayBuffer(4).transferToImmutable()).setFromBase64('AAAA')));
T('setFromHex on immutable', () => JSON.stringify(new Uint8Array(new ArrayBuffer(4).transferToImmutable()).setFromHex('0102')));
T('setFromHex empty on immutable', () => JSON.stringify(new Uint8Array(new ArrayBuffer(4).transferToImmutable()).setFromHex('')));
T('setFromHex on mutable', () => { const u = new Uint8Array(4); return JSON.stringify(u.setFromHex('0aff')) + ' ' + u.join(); });
T('immutable element write', () => { const u = new Uint8Array(new Uint8Array([1, 2]).buffer.transferToImmutable()); u[0] = 9; return u.join(); });
T('immutable resize', () => new ArrayBuffer(4, { maxByteLength: 8 }).transferToImmutable().resize(2));
T('immutable flags', () => { const b = new ArrayBuffer(3).transferToImmutable(); return [b.immutable, b.resizable, b.byteLength].join(); });
T('AB slice on SAB', () => ArrayBuffer.prototype.slice.call(new SharedArrayBuffer(2)));
T('AB slice on object', () => ArrayBuffer.prototype.slice.call({}));
T('SAB slice window', () => { const s = new SharedArrayBuffer(4); new Uint8Array(s).set([1, 2, 3, 4]); return [...new Uint8Array(s.slice(1, 3))].join(); });
T('SAB slice inverted', () => new SharedArrayBuffer(4).slice(3, 1).byteLength);
T('SAB slice negative', () => { const s = new SharedArrayBuffer(4); new Uint8Array(s).set([5, 6, 7, 8]); return [...new Uint8Array(s.slice(-2))].join(); });
''')


def test_array_mutators_through_refusing_proxies(run, workdir):
    """CATCHES: Array.prototype.pop/shift/splice/copyWithin/reverse that ignore a `false` result from
    a proxy's deleteProperty trap (DeletePropertyOrThrow must throw a TypeError naming the key), and
    a revoked proxy reaching JSON.stringify's IsArray check (it must throw a TypeError; note the
    reference's message, "cannot read property 'get' of null", leaks its handler lookup rather
    than naming the revoked proxy -- looks like a reference quirk, pinned as observed)."""
    check_js(run, workdir, "mutators_refusing_proxies", r'''
const refusing = (arr) => new Proxy(arr, { deleteProperty(t, k) { console.log('  delete ' + String(k)); return false; } });
T('pop', () => Array.prototype.pop.call(refusing([1, 2])));
T('shift', () => Array.prototype.shift.call(refusing([1, 2])));
T('splice', () => Array.prototype.splice.call(refusing([1, 2, 3]), 0, 1));
T('copyWithin over hole', () => Array.prototype.copyWithin.call(refusing([1, , 3]), 0, 1, 2));
T('reverse with hole', () => Array.prototype.reverse.call(refusing([1, , 3, 4])));
T('pop allowed', () => { const p = new Proxy([1, 2], {}); return [Array.prototype.pop.call(p), p.length].join(); });
const { proxy: revoked, revoke } = Proxy.revocable([], {}); revoke();
T('stringify revoked nested', () => JSON.stringify({ a: revoked }));
T('stringify revoked top', () => JSON.stringify(revoked));
''')


def test_iterator_results_must_be_objects_in_builtins(run, workdir):
    """CATCHES: built-ins that drain an iterable without checking that each `next()` result is an
    Object -- AggregateError's errors list, TypedArray.from and the TypedArray constructor must throw
    'iterator result is not an object' for a primitive result -- while TypedArray.prototype.set
    treats an iterable as an array-like (no iteration) and a well-behaved iterator still works."""
    check_js(run, workdir, "iterator_results_objects", r'''
const bad = { [Symbol.iterator]() { return { next() { return 1; } }; } };
let n = 0;
const good = { [Symbol.iterator]() { return { next() { n++; return n <= 3 ? { value: n * 2, done: false } : { done: true }; } }; } };
T('AggregateError bad', () => new AggregateError(bad));
T('Uint8Array.from bad', () => Uint8Array.from(bad));
T('new Uint8Array bad', () => new Uint8Array(bad));
T('set ignores iteration', () => { const u = new Uint8Array(2); u.set(bad); return u.join(); });
T('AggregateError good', () => { n = 0; return new AggregateError(good, 'm').errors.join(); });
T('Float64Array.from good', () => { n = 0; return Float64Array.from(good, x => x / 4).join(); });
''')


@pytest.mark.parametrize("cli", TIERS)
def test_private_writes_and_strict_put_value_rechecks(run, workdir, cli):
    """CATCHES: private field writes/reads on primitive bases that do not throw the brand-check
    TypeError, a strict function inside `with` whose binding vanished while @@unscopables ran (the
    strict SetMutableBinding must throw ReferenceError), and a strict assignment to a global that
    the right-hand side deleted (PutValue must re-check HasProperty and throw, while sloppy code
    re-creates the global)."""
    check_js(run, workdir, "private_writes_strict_put", r'''
class P { #x = 1; static w(o) { o.#x = 2; return 'wrote'; } static r(o) { return o.#x; } static ok() { const p = new P(); P.w(p); return P.r(p); } }
T('private write to number', () => P.w(5));
T('private write to undefined', () => P.w(undefined));
T('private read from string', () => P.r('s'));
T('private write to object without brand', () => P.w({}));
T('private round trip', () => P.ok());
var scoped = { x: 1 };
scoped[Symbol.unscopables] = { get x() { delete scoped.x; return false; } };
with (scoped) {
  (function () { 'use strict'; T('strict with vanished binding', () => { x = 2; return JSON.stringify(scoped); }); })();
}
T('strict global deleted by rhs', () => { 'use strict'; globalThis.gx = 1; gx = (delete globalThis.gx, 2); return 'assigned ' + globalThis.gx; });
T('sloppy global deleted by rhs', () => { globalThis.gy = 1; gy = (delete globalThis.gy, 2); return 'assigned ' + globalThis.gy; });
''', cli=cli)


def test_to_bigint_rejects_nullish_and_symbols(run, workdir):
    """CATCHES: ToBigInt that converts undefined/null/symbols instead of throwing 'Cannot convert
    value to a BigInt' (BigInt.asIntN/asUintN, BigInt64Array stores/of/fill, DataView setBigInt64,
    Atomics on BigInt arrays), while booleans and numeric strings convert and Numbers throw their
    own message."""
    check_js(run, workdir, "to_bigint_nullish", r'''
T('asIntN undefined', () => BigInt.asIntN(8, undefined));
T('asUintN null', () => BigInt.asUintN(8, null));
T('asIntN symbol', () => BigInt.asIntN(8, Symbol('s')));
T('asIntN true / string', () => [BigInt.asIntN(8, true), BigInt.asIntN(8, '0x1ff')].join());
T('asIntN number', () => BigInt.asIntN(8, 1));
T('BigInt64Array store undefined', () => { const a = new BigInt64Array(1); a[0] = undefined; return a[0]; });
T('BigInt64Array.of null', () => BigInt64Array.of(null));
T('BigUint64Array fill undefined', () => new BigUint64Array(2).fill(undefined));
T('DataView setBigInt64 undefined', () => new DataView(new ArrayBuffer(8)).setBigInt64(0, undefined));
T('Atomics.add BigInt64Array undefined', () => Atomics.add(new BigInt64Array(1), 0, undefined));
T('Atomics.add BigInt64Array string', () => { const a = new BigInt64Array(1); return Atomics.add(a, 0, '5') + ',' + a[0]; });
''')


def test_date_locale_methods_reject_primitive_options(run, workdir):
    """CATCHES: Date.prototype.toLocaleDateString/toLocaleTimeString/toLocaleString that silently
    accept a primitive options argument (the reference throws 'options must be an object' from
    its ToDateTimeOptions step), while undefined and object options format normally."""
    check_js(run, workdir, "date_locale_primitive_options", r'''
const d = new Date(Date.UTC(2020, 0, 2, 3, 4, 5));
T('date number options', () => d.toLocaleDateString('en-US', 1));
T('string string options', () => d.toLocaleString('en-US', 'x'));
T('time boolean options', () => d.toLocaleTimeString('en-US', true));
T('date undefined options', () => d.toLocaleDateString('en-US', undefined));
T('time object options', () => d.toLocaleTimeString('en-US', { timeZone: 'UTC', hour12: false }));
T('string null options', () => d.toLocaleString('en-US', null));
''')


@pytest.mark.parametrize("cli", TIERS)
def test_compiled_binding_and_for_head_shapes(run, workdir, cli):
    """CATCHES: a bytecode compiler that mis-homes captured block `let`s (closures must see the
    block's own binding), var/let/const object destructuring whose leaves are captured, for-of heads
    that assign to an existing local/captured binding (and must throw on a const), for-in over an
    existing local, destructuring-assignment for-of heads with defaults, `var` destructuring heads
    that leak the last value, and dynamic import() inside a loop -- every tier must agree."""
    check_js(run, workdir, "compiled_binding_shapes", r'''
const out = [];
function blockLet(n) { let s = 0; { let b = n * 2; const g = () => b; b++; s += g(); } for (let i = 0; i < 3; i++) s += i; return s; }
let a = 0; for (let i = 0; i < 300; i++) a += blockLet(i); out.push('blockLet ' + a);
function blockLet2(n) { let s = 0; if (n > 0) { let c = n; const h = () => c * 10; s = h(); } while (n-- > 0) s++; return s; }
a = 0; for (let i = 0; i < 300; i++) a += blockLet2(i % 5); out.push('blockLet2 ' + a);
function varDestr(o) { var { p, q } = o; const g = () => p + q; let s = 0; for (let i = 0; i < 2; i++) s += g(); return s; }
a = 0; for (let i = 0; i < 300; i++) a += varDestr({ p: i, q: 1 }); out.push('varDestr ' + a);
function letDestr(o) { let { p, q } = o; const g = () => p * q; p++; let s = 0; for (let i = 0; i < 2; i++) s += g(); return s; }
a = 0; for (let i = 0; i < 300; i++) a += letDestr({ p: i, q: 2 }); out.push('letDestr ' + a);
function constDestr(o) { const { p, q: { r } } = o; const g = () => p - r; let s = 0; for (let i = 0; i < 2; i++) s += g(); return s; }
a = 0; for (let i = 0; i < 300; i++) a += constDestr({ p: i, q: { r: 1 } }); out.push('constDestr ' + a);
function strKeys(o) { const { 'a': x, "b c": y, 3: z } = o; let s = 0; for (let i = 0; i < 2; i++) s += x + y; return s + String(z); }
let t = ''; for (let i = 0; i < 200; i++) t = strKeys({ a: i, 'b c': 1, 3: 'z' }); out.push('strKeys ' + t);
function forOfLocal(xs) { let x; let s = 0; for (x of xs) s += x; return s + x; }
a = 0; for (let i = 0; i < 300; i++) a += forOfLocal([i, 1, 2]); out.push('forOfLocal ' + a);
function forOfConst(xs) { const x = 0; let s = 0; try { for (x of xs) s += 1; } catch (e) { return e.name + ': ' + e.message; } return s; }
out.push('forOfConst ' + forOfConst([1, 2]) + ' / ' + forOfConst([]));
function forOfCapConst(xs) { const x = 0; const g = () => x; try { for (x of xs) {} } catch (e) { return e.name + ': ' + e.message + ' g=' + g(); } return 'none'; }
out.push('forOfCapConst ' + forOfCapConst([1]));
function forOfCap(xs) { let x = 0; const g = () => x; let s = 0; for (x of xs) s += g(); return s; }
a = 0; for (let i = 0; i < 300; i++) a += forOfCap([i, 2]); out.push('forOfCap ' + a);
function forInLocal(o) { let k; let s = ''; for (k in o) s += k; return s + k; }
out.push('forInLocal ' + forInLocal({ a: 1, b: 2 }));
function forOfDestrAssign(xs) { let p, q, s = 0; for ([p, q] of xs) s += p * q; for ({ p, q = 3 } of [{ p: 1 }]) s += p * q; return s; }
a = 0; for (let i = 0; i < 300; i++) a += forOfDestrAssign([[i, 2], [1, 1]]); out.push('forOfDestrAssign ' + a);
function forOfVarDestr(xs) { let s = 0; for (var [p, q] of xs) s += p + q; return s + p; }
a = 0; for (let i = 0; i < 300; i++) a += forOfVarDestr([[i, 2]]); out.push('forOfVarDestr ' + a);
function shadowHead(xs) { let x = 'outer'; const g = () => x; let s = ''; for (let x of xs) s += x; for (const x in { k: 1 }) s += x; return s + g(); }
t = ''; for (let i = 0; i < 200; i++) t = shadowHead(['a', i]); out.push('shadowHead ' + t);
function breakInTry(xs) { let s = 0; for (const x of xs) { try { if (x > 2) break; s += x; } catch (e) { s = -1; } } return s; }
a = 0; for (let i = 0; i < 200; i++) a += breakInTry([1, 2, 3, 4]); out.push('breakInTry ' + a);
async function imp() { let n = 0; for (let i = 0; i < 2; i++) { try { await import('./missing-' + i + '.mjs'); } catch (e) { n++; } } return n; }
imp().then(v => console.log('import failures ' + v));
console.log(out.join('\n'));
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_compiled_update_operands_and_discarded_assignments(run, workdir, cli):
    """CATCHES: fused `a[k] = <expr>` element stores whose right-hand side contains `o.n++` /
    `b[j]++` / `-o.n--` (the update must happen before the store, in order), discarded destructuring
    assignments (`[p, q] = [q, p + q];` / `({ p: o.p } = ...)`), logical assignment statements on
    members and locals, and compound member updates (`**=`, `<<=`, `>>>=`, `%=`) used as statements."""
    check_js(run, workdir, "compiled_update_operands", r'''
const out = [];
function fusedUpd(n) { const a = [0, 0, 0, 0], b = [1, 2, 3, 4], o = { n: 0 }; for (let i = 0; i < n; i++) { a[i & 3] = o.n++; a[(i + 1) & 3] = b[i & 3]++; a[(i + 2) & 3] = -o.n--; } return a.join() + '|' + b.join() + '|' + o.n; }
out.push('fusedUpd ' + fusedUpd(50));
function swapDiscard(n) { let p = 1, q = 2; const o = { p: 0, q: 0 }; for (let i = 0; i < n; i++) { [p, q] = [q, p + q]; ({ p: o.p, q: o.q } = { p, q }); } return p + ',' + q + ',' + o.p; }
out.push('swapDiscard ' + swapDiscard(20));
function logicalDiscard(n) { const o = { a: null, b: 1, c: 0 }; let x = null, y = 0; for (let i = 0; i < n; i++) { o.a ??= i; o.b &&= i; o.c ||= i; x ??= i; y ||= i; } return JSON.stringify(o) + x + y; }
out.push('logicalDiscard ' + logicalDiscard(5));
function memberUpdDiscard(n) { const o = { v: 1 }; const k = 'v'; const arr = [1, 2]; for (let i = 0; i < n; i++) { o[k] **= 1; o.v <<= 1; arr[i & 1] >>>= 0; o.v %= 1000003; } return o.v + ',' + arr; }
out.push('memberUpdDiscard ' + memberUpdDiscard(40));
function strKeysVar(o) { var { 'p': x, "q": y } = o; let s = 0; for (let i = 0; i < 2; i++) s += x * y; return s; }
let t = 0; for (let i = 0; i < 200; i++) t += strKeysVar({ p: i, q: 2 }); out.push('strKeysVar ' + t);
function contInTry(xs) { let s = 0; for (const x of xs) { try { if (x === 2) continue; s += x; } catch (e) { s = -1; } } return s; }
t = 0; for (let i = 0; i < 200; i++) t += contInTry([1, 2, 3]); out.push('contInTry ' + t);
function nestedBreak(xs) { let s = 0; outer: for (const x of xs) { for (const y of xs) { try { if (y > x) continue outer; if (x > 2) break outer; s += y; } catch (e) {} } } return s; }
t = 0; for (let i = 0; i < 200; i++) t += nestedBreak([1, 2, 3]); out.push('nestedBreak ' + t);
console.log(out.join('\n'));
''', cli=cli)


def test_reflect_on_forwarding_proxies_and_bigint_comparisons(run, workdir):
    """CATCHES: Reflect.set/getOwnPropertyDescriptor/getPrototypeOf that read a trap-less proxy's
    own storage instead of forwarding to the target (Reflect.set with three arguments must use the
    proxy itself as receiver), Function.prototype.toString on proxies/bound/accessor/symbol-named
    natives, identifiers spelled with \\u escapes, BigInt vs BigInt/Number comparisons with negative
    operands and fractional or subnormal numbers, BigInt64Array sorting of negatives, shifts of
    zero and carries across 64-bit limbs."""
    check_js(run, workdir, "reflect_proxies_bigint_compare", r'''
const P = new Proxy({ a: 1 }, {});
T('Reflect.set 3 args', () => [Reflect.set(P, 'b', 2), P.b, Object.keys(P).join('')].join());
T('Reflect.set frozen target', () => Reflect.set(new Proxy(Object.freeze({ a: 1 }), {}), 'a', 2));
T('Reflect.gOPD', () => JSON.stringify(Reflect.getOwnPropertyDescriptor(P, 'a')));
T('Reflect.gOPD missing', () => Reflect.getOwnPropertyDescriptor(P, 'zz'));
T('Reflect.getPrototypeOf', () => Reflect.getPrototypeOf(P) === Object.prototype);
T('Reflect.getPrototypeOf trap', () => Reflect.getPrototypeOf(new Proxy({}, { getPrototypeOf() { return Array.prototype; } })) === Array.prototype);
T('toString proxy fn', () => Function.prototype.toString.call(new Proxy(function foo() {}, {})));
T('toString bound', () => Function.prototype.toString.call(function foo() {}.bind(null)));
T('toString getter', () => Function.prototype.toString.call(Object.getOwnPropertyDescriptor(Map.prototype, 'size').get));
T('toString symbol-named', () => Function.prototype.toString.call(RegExp.prototype[Symbol.split]));
T('escaped identifiers', () => eval('var \\u0061bc = 1; var x\\u{62}yz9 = 2; abc + xbyz9'));
T('astral escaped identifier', () => eval('var \\u{1d4d0}q = 3; \u{1d4d0}q * 2'));
T('bigint compare', () => [-5n < -3n, -3n < -5n, -5n > -5.5, -5n < -4.5, 0n < 5e-324, 0n == 5e-324, -1n < -5e-324, 2n ** 64n > 1.8446744073709552e19].join());
T('BigInt64Array sort', () => new BigInt64Array([-5n, -3n, -9n, 4n, 0n]).sort().join());
T('BigInt64Array toSorted', () => new BigInt64Array([-5n, -3n, -9n]).toSorted().join());
T('shift zero', () => [0n << 5n, 0n >> 5n, 0n << 100n, -0n << 1n].join());
T('limb carries', () => [(2n ** 128n - 1n) + 1n, (2n ** 192n - 1n) + 1n].join());
T('asIntN wide', () => [BigInt.asIntN(64, 2n ** 130n + 5n), BigInt.asUintN(64, -(2n ** 130n) - 1n), BigInt.asIntN(128, 2n ** 127n)].join());
T('asIntN huge width', () => [BigInt.asIntN(2 ** 30, 5n), BigInt.asUintN(2 ** 30, 7n)].join());
T('asUintN huge width negative', () => BigInt.asUintN(2 ** 30, -1n));
''')


def test_module_cycle_with_top_level_await(run, workdir):
    """CATCHES: async module evaluation that mishandles a dependency cycle where both members use
    top-level await (a.mjs -> b.mjs <-> c.mjs): the parked async dependency must count towards its
    parent's pending-async total so evaluation order is c, b, a, main, and the cycle's exported
    bindings must be initialised before dependants run."""
    write_files(workdir, {
        "a.mjs": "import { b } from './b.mjs';\nexport const a = 'a+' + b;\nconsole.log('eval a');\n",
        "b.mjs": "import { c } from './c.mjs';\nimport './a.mjs';\nawait 0;\nexport const b = 'b+' + c;\nconsole.log('eval b');\n",
        "c.mjs": "import './b.mjs';\nawait Promise.resolve();\nexport const c = 'c';\nconsole.log('eval c');\n",
        "d.mjs": "import './e.mjs';\nexport const d = 'd';\nconsole.log('eval d');\n",
        "e.mjs": "await null;\nconsole.log('eval e');\n",
    })
    check_script(run, workdir, G, "module_tla_cycle", r'''
import { a } from './a.mjs';
console.log('main', a);
const ns = await import('./d.mjs');
console.log('dynamic', ns.d, Object.keys(ns).join());
const again = await import('./b.mjs');
console.log('again', again.b);
''', filename="main.mjs")


def test_uint8_only_methods_base64_last_chunks_and_conversions(run, workdir):
    """CATCHES: Uint8Array.prototype.toHex/toBase64/setFromHex/setFromBase64 accepting other
    TypedArray kinds or plain objects, setFromBase64 mishandling lastChunkHandling for 1-3
    character final chunks, padding and non-zero padding bits ('loose' decodes, 'strict' rejects,
    'stop-before-partial' stops before the partial chunk), TypedArray.prototype.toLocaleString that
    keeps calling element toLocaleString after a resizable buffer shrank (out-of-bounds elements
    become empty), Uint8Clamped round-half-to-even conversions on every write path, and float16
    underflow to (signed) zero / the smallest subnormal."""
    check_js(run, workdir, "uint8_methods_base64_conversions", r'''
T('toHex on Int8Array', () => Uint8Array.prototype.toHex.call(new Int8Array(2)));
T('toBase64 on Uint8ClampedArray', () => Uint8Array.prototype.toBase64.call(new Uint8ClampedArray(2)));
T('setFromHex on Uint16Array', () => Uint8Array.prototype.setFromHex.call(new Uint16Array(2), '00'));
T('setFromBase64 on object', () => Uint8Array.prototype.setFromBase64.call({}, 'AA'));
for (const s of ['Z', 'ZZ', 'ZZZ', 'ZZ=', 'ZZZ=', 'ZZ==', 'AAAAZ', 'AAAAZZ', 'AAAA ZZ Z', 'ZZ=Z']) {
  const row = [];
  for (const h of ['loose', 'strict', 'stop-before-partial']) {
    try { const u = new Uint8Array(8); const r = u.setFromBase64(s, { lastChunkHandling: h }); row.push(r.read + '/' + r.written + '[' + u.subarray(0, r.written).join() + ']'); }
    catch (e) { row.push(e.name); }
  }
  console.log(JSON.stringify(s).padEnd(12) + row.join('  '));
}
T('toLocaleString after shrink', () => { const rab = new ArrayBuffer(4, { maxByteLength: 8 }); const ta = new Uint8Array(rab); ta.set([1, 2, 3, 4]); const orig = Number.prototype.toLocaleString; let n = 0; Number.prototype.toLocaleString = function () { n++; rab.resize(1); return 'x' + this; }; try { return ta.toLocaleString() + ' calls=' + n; } finally { Number.prototype.toLocaleString = orig; } });
const v = [1.7, 2.5, 3.5, 0.5, 254.6, -0.3, 1.5000001];
const show = (ta) => Array.from(ta).join(',');
T('clamped ctor/from/of', () => [show(new Uint8ClampedArray(v)), show(Uint8ClampedArray.from(v)), show(Uint8ClampedArray.of(...v))].join(' | '));
T('clamped set/store', () => { const a = new Uint8ClampedArray(7); a.set(v); const b = new Uint8ClampedArray(7); for (let i = 0; i < 7; i++) b[i] = v[i]; return show(a) + ' | ' + show(b); });
T('clamped fill/with/map', () => [show(new Uint8ClampedArray(2).fill(1.7)), show(new Uint8ClampedArray(2).with(1, 1.7)), show(new Uint8ClampedArray(2).map(() => 2.6))].join(' | '));
T('float16 DataView underflow', () => { const dv = new DataView(new ArrayBuffer(8)); dv.setFloat16(0, 1e-30); dv.setFloat16(2, -1e-30); dv.setFloat16(4, 3e-8); return [dv.getFloat16(0), Object.is(dv.getFloat16(2), -0), dv.getFloat16(4)].join(); });
T('Float16Array underflow', () => show(new Float16Array([1e-30, -1e-30, 6e-8, 2.9e-8, 65520, 1e-300])) + ' ' + Object.is(new Float16Array([-1e-30])[0], -0));
T('Math.f16round', () => [Math.f16round(1e-30), Object.is(Math.f16round(-1e-300), -0), Math.f16round(5.960464477539063e-8)].join());
''')


def test_iterator_helper_limits_zip_padding_and_keyed_order(run, workdir):
    """CATCHES: Iterator.prototype.take/drop that do not close the underlying iterator when the
    limit's ToNumber throws (or is NaN/negative/a Symbol), Array.from/Array.of that swallow a
    throwing or refusing [[DefineOwnProperty]] on a custom constructor's result, Iterator.zip
    'longest' padding iterators that are exhausted early (remaining slots are undefined), and
    Iterator.zipKeyed that loses symbol keys, orders keys wrongly (array indices ascending first,
    then strings -- including "4294967295" and "01" -- in insertion order) or keeps keys whose
    proxy descriptor is undefined."""
    check_js(run, workdir, "iterator_limits_zip_keyed", r'''
const closing = () => { const it = [1, 2, 3].values(); it.return = () => { console.log('  closed'); return {}; }; return it; };
T('take throwing limit', () => Iterator.prototype.take.call(closing(), { valueOf() { throw new Error('limit boom'); } }));
T('drop symbol limit', () => Iterator.prototype.drop.call(closing(), Symbol()));
T('take NaN', () => Iterator.prototype.take.call(closing(), NaN));
T('take -1', () => Iterator.prototype.take.call(closing(), -1));
T('drop Infinity', () => JSON.stringify([...Iterator.prototype.drop.call([1, 2].values(), Infinity)]));
T('take 0 then next', () => JSON.stringify(Iterator.prototype.take.call(closing(), 0).next()));
T('from throwing define', () => Array.from.call(function () { return new Proxy({}, { defineProperty() { throw new Error('dp boom'); } }); }, [1]));
T('from refusing define', () => Array.from.call(function () { return new Proxy({}, { defineProperty() { return false; } }); }, [1]));
T('of on non-extensible result', () => Array.of.call(function () { return Object.preventExtensions({}); }, 1));
T('zip longest short padding', () => JSON.stringify([...Iterator.zip([[1], [2, 'b'], [3]], { mode: 'longest', padding: (function* () { yield 'p0'; })() })]));
const s1 = Symbol('k');
T('zipKeyed symbol key', () => { const r = [...Iterator.zipKeyed({ a: [1], [s1]: [2] })]; return JSON.stringify(r) + ' ' + String(r[0][s1]); });
T('zipKeyed key order', () => JSON.stringify([...Iterator.zipKeyed({ b: [1], 2: [2], 4294967295: [3], '01': [4], 1: [5] })]));
T('zipKeyed proxy gopd undefined', () => JSON.stringify([...Iterator.zipKeyed(new Proxy({ a: [1], b: [2] }, { getOwnPropertyDescriptor(t, k) { return k === 'a' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); } }))]));
T('zipKeyed longest padding', () => JSON.stringify([...Iterator.zipKeyed({ x: [1, 2], y: [3] }, { mode: 'longest', padding: { y: 'Y' } })]));
''')
