"""Core built-in library, part 1: Array, Object, String, Number/Boolean/BigInt, Math, JSON, global functions and Symbol.

Each program prints labelled lines (exact values, holes, -0, error name+message) compared to a golden.
"""

import pytest

from conftest import golden

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

# Shared JS helpers prepended to every program: fmt() renders values exactly (-0, holes, symbols,
# key order), show() prints a labelled line, tryit() prints the result or the exact error name+message.
PRELUDE = r"""function fmt(v, d = 0) {
  if (d > 5) return '...';
  switch (typeof v) {
    case 'number': return Object.is(v, -0) ? '-0' : String(v);
    case 'string': return JSON.stringify(v);
    case 'bigint': return v + 'n';
    case 'symbol': return v.toString();
    case 'undefined': return 'undefined';
    case 'boolean': return String(v);
    case 'function': return '[Function ' + v.name + ']';
  }
  if (v === null) return 'null';
  if (Array.isArray(v)) {
    const out = [];
    for (let i = 0; i < v.length; i++) out.push(i in v ? fmt(v[i], d + 1) : '<hole>');
    return '[' + out.join(', ') + ']';
  }
  return '{' + Reflect.ownKeys(v).map(k => (typeof k === 'symbol' ? '[' + k.toString() + ']' : k) + ': ' + fmt(v[k], d + 1)).join(', ') + '}';
}
const show = (l, ...vs) => console.log(l + ':', vs.map(v => fmt(v)).join(' | '));
const tryit = (l, f) => { try { show(l, f()); } catch (e) { console.log(l + ': THROW ' + (e && e.name) + ': ' + (e && e.message)); } };
"""


def _ok(r, name):
    assert r.stderr == b""
    assert r.returncode == 0
    assert r.stdout == golden(__file__, name)


PROG_ARRAY_MUTATORS_ACCESSORS = PRELUDE + r"""
// basic mutators
const a = [1, 2, 3];
show('push', a.push(4, 5), a);
show('pop', a.pop(), a);
show('shift', a.shift(), a);
show('unshift', a.unshift(-1, 0), a);
show('splice-del', a.splice(1, 2), a);
show('splice-ins', a.splice(1, 0, 'x', 'y'), a);
show('splice-neg', a.splice(-2), a);
show('splice-none', a.splice(), a);
show('splice-one-arg', [1,2,3,4].splice(1));
show('splice-big-del', [1,2,3].splice(1, 100));
show('reverse', [1, , 3, 4].reverse());
show('concat', [1].concat(2, [3, [4]], 'five'));
const spreadable = { length: 2, 0: 'a', 1: 'b', [Symbol.isConcatSpreadable]: true };
show('concat-spreadable', [0].concat(spreadable));
const nonspread = [9, 8]; nonspread[Symbol.isConcatSpreadable] = false;
show('concat-nonspread', [0].concat(nonspread).length);
show('join', [1, null, undefined, [2, 3], 'z'].join('-'));
show('join-default', [1, 2].join(), [].join(), [undefined].join());
show('toString', String([1, [2, [3]]]));
show('slice', [1,2,3,4,5].slice(1, -1), [1,2,3].slice(-2), [1,2,3].slice(5), [1,2,3].slice());
show('indexOf', [1,2,3,2].indexOf(2), [1,2,3,2].indexOf(2, 2), [1,2,3].indexOf(4), [1,2,3].indexOf(1, -1));
show('lastIndexOf', [1,2,3,2].lastIndexOf(2), [1,2,3,2].lastIndexOf(2, 2), [1,2,3,2].lastIndexOf(2, -3), [2].lastIndexOf(2, -5));
show('includes', [1,2,NaN].includes(NaN), [1,2,3].includes(1, 1), [,].includes(undefined), [-0].includes(0));
show('indexOf-hole', [,].indexOf(undefined), [NaN].indexOf(NaN));
show('at', [1,2,3].at(0), [1,2,3].at(-1), [1,2,3].at(3), [1,2,3].at(-4), [1,2,3].at(1.7), [1,2,3].at('-2'));
show('keys', [...['a','b'].keys()], [...['a','b'].entries()], [...['a',,'c'].values()]);
show('fill', [1,2,3,4].fill(0), [1,2,3,4].fill(9, 1, 3), [1,2,3,4].fill(9, -2), Array(3).fill());
show('copyWithin', [1,2,3,4,5].copyWithin(0, 3), [1,2,3,4,5].copyWithin(1, 0, 3), [1,2,3,4,5].copyWithin(-2, 0), [1,,3].copyWithin(0, 1));
show('flat', [1, [2, [3, [4, [5]]]]].flat(), [1, [2, [3, [4]]]].flat(2), [[1, , 3], , [4]].flat(), [1, [2]].flat(0), [1,[2,[3]]].flat(-1));
show('flatMap', [1, 2, 3].flatMap(x => [x, x * 10]), ['a b', 'c'].flatMap(s => s.split(' ')), [1,2].flatMap(x => [[x]]));
show('isArray', Array.isArray([]), Array.isArray({length:0}), Array.isArray(new Proxy([], {})), Array.isArray(Array.prototype));
show('toReversed', [1,2,3].toReversed(), [1,,3].toReversed());
show('toSorted', [3,1,10,2].toSorted(), [3,1,10,2].toSorted((x,y)=>x-y), [,1,undefined,0].toSorted());
show('toSpliced', [1,2,3,4].toSpliced(1,2,'x','y','z'), [1,2,3].toSpliced(), [1,2,3].toSpliced(1), [1,,3].toSpliced(0,0));
show('with', [1,2,3].with(1, 'b'), [1,2,3].with(-3, 'a'), [1,,3].with(0, 0));
tryit('with-oob', () => [1,2,3].with(3, 0));
tryit('with-oob-neg', () => [1,2,3].with(-4, 0));
const orig = [3, 2, 1]; orig.toSorted(); orig.toReversed(); orig.with(0, 9); orig.toSpliced(0, 1);
show('immutable', orig);
show('findLast', [1,2,3,4].findLast(x => x % 2), [1,2,3,4].findLastIndex(x => x % 2), [].findLast(x => 1), [1].findLastIndex(x => 0));
show('find', [5, 12, 8].find(x => x > 6), [5, 12, 8].findIndex(x => x > 100), [,1].find(x => true));
show('Array.length', Array.prototype.length, Array.length, [].push.length, [].splice.length, [].concat.length, Array.from.length);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_array_mutators_accessors(run, tier):
    """CATCHES: wrong results/holes from push/pop/shift/unshift/splice/slice/concat (isConcatSpreadable)/join/indexOf/lastIndexOf/includes/at/fill/copyWithin/flat/flatMap and the ES2023 copying methods toSorted/toReversed/toSpliced/with/findLast."""
    _ok(run([*tier, "-e", PROG_ARRAY_MUTATORS_ACCESSORS]), "array_mutators_accessors")


PROG_ARRAY_CALLBACKS_SORT_GENERIC = PRELUDE + r"""
const log = [];
const ctx = { k: 10 };
show('map-this', [1, 2].map(function (x, i, arr) { return [x * this.k, i, arr.length]; }, ctx));
show('map-holes', [1, , 3].map(x => x * 2));
show('filter', [1, 2, 3, 4, , 6].filter((x, i) => i % 2 === 0));
[1, , 3].forEach((x, i) => log.push(i + '=' + x));
show('forEach', log);
show('some/every', [1, 2].some(x => x > 1), [].some(x => true), [1, 2].every(x => x > 0), [].every(x => false));
show('reduce', [1, 2, 3].reduce((a, b) => a + b), [1, 2, 3].reduce((a, b) => a + b, 10), [[1], [2]].reduceRight((a, b) => a.concat(b)));
show('reduce-trace', [1, , 3].reduce((acc, x, i) => acc + `(${i}:${x})`, ''), ['a', 'b', 'c'].reduceRight((acc, x, i) => acc + i + x, '>'));
tryit('reduce-empty', () => [].reduce((a, b) => a));
tryit('reduceRight-empty', () => [, ,].reduceRight((a, b) => a));
show('reduce-single', [, 5, ,].reduce((a, b) => a + b));
// mutation during iteration
const m = [1, 2, 3];
show('map-mutate', m.map((x, i) => { if (i === 0) { m.push(99); m[2] = 30; } return x; }), m);
const f = [1, 2, 3, 4];
show('forEach-delete', (() => { const seen = []; f.forEach((x, i) => { seen.push(x); if (i === 0) delete f[2]; }); return seen; })());
// sort
show('sort-default', [10, 9, 1, 100, undefined, 'b', 'a', null].sort());
show('sort-holes', [3, , 1, undefined, 2].sort());
show('sort-cmp', [5, 1, 4].sort((a, b) => b - a));
const people = [['a', 2], ['b', 1], ['c', 2], ['d', 1], ['e', 2], ['f', 1], ['g', 0], ['h', 2], ['i', 1], ['j', 0], ['k', 2], ['l', 1]];
show('sort-stable', people.sort((x, y) => x[1] - y[1]).map(p => p[0]).join(''));
show('sort-bad-cmp-return', [3, 1, 2].sort(() => NaN));
show('sort-strings', ['b', 'B', 'a', 'A', '\u00e9', 'e', '10', '9', '\u{1F600}', '\uffff'].sort());
tryit('sort-noncallable', () => [1, 2].sort(null));
tryit('sort-noncallable-obj', () => [1, 2].sort({}));
tryit('toSorted-noncallable', () => [1, 2].toSorted('x'));
tryit('sort-throwing', () => [1, 2, 3].sort(() => { throw new RangeError('cmp failed'); }));
const s = { length: 3, 0: 'c', 1: 'a', 2: 'b' };
Array.prototype.sort.call(s);
show('sort-arraylike', s);
// generic methods on array-likes and strings
const al = { length: 3, 0: 'x', 2: 'z' };
show('generic-join', Array.prototype.join.call(al, '+'));
show('generic-map', Array.prototype.map.call('abc', c => c.toUpperCase()));
show('generic-push', Array.prototype.push.call(al, 'w'), al);
show('generic-indexOf', Array.prototype.indexOf.call({ length: 2, 0: NaN, 1: 'q' }, 'q'));
show('generic-includes', Array.prototype.includes.call({ length: 1 }, undefined));
show('generic-pop-empty', (() => { const o = {}; const r = Array.prototype.pop.call(o); return [r, o.length]; })());
show('generic-length-str', Array.prototype.slice.call({ length: '2', 0: 1, 1: 2, 2: 3 }));
show('generic-length-neg', Array.prototype.slice.call({ length: -5, 0: 1 }));
show('generic-reverse', Array.prototype.reverse.call({ length: 3, 0: 'a', 2: 'c' }));
show('generic-splice', (() => { const o = { length: 4, 0: 0, 1: 1, 2: 2, 3: 3 }; const r = Array.prototype.splice.call(o, 1, 2); return [r, o]; })());
show('generic-unshift', (() => { const o = { length: 1, 0: 'a' }; Array.prototype.unshift.call(o, 'z'); return o; })());
show('generic-shift', (() => { const o = { length: 2, 0: 'a', 1: 'b' }; return [Array.prototype.shift.call(o), o]; })());
show('generic-fill', Array.prototype.fill.call({ length: 2 }, 'f'));
show('generic-flat', Array.prototype.flat.call({ length: 2, 0: [1], 1: 2 }));
show('generic-at', Array.prototype.at.call('hey', -1));
show('generic-toReversed', Array.prototype.toReversed.call({ length: 2, 0: 'a', 1: 'b' }));
show('generic-with', Array.prototype.with.call({ length: 2, 0: 'a', 1: 'b' }, 0, 'q'));
show('generic-copyWithin', Array.prototype.copyWithin.call({ length: 3, 0: 'a', 2: 'c' }, 0, 1));
show('generic-lastIndexOf', Array.prototype.lastIndexOf.call({ length: 3, 0: 1, 1: 1 }, 1));
show('generic-concat', [].concat.call(1, 2).map(x => typeof x));
// errors
tryit('map-null', () => Array.prototype.map.call(null, x => x));
tryit('forEach-undef', () => Array.prototype.forEach.call(undefined, x => x));
tryit('map-nonfn', () => [1].map());
tryit('filter-nonfn', () => [1].filter('x'));
tryit('forEach-nonfn', () => [1].forEach(1));
tryit('find-nonfn', () => [1].find());
tryit('findLast-nonfn', () => [1].findLast());
tryit('some-nonfn', () => [1].some());
tryit('every-nonfn', () => [1].every({}));
tryit('reduce-nonfn', () => [1].reduce());
tryit('flatMap-nonfn', () => [1].flatMap());
tryit('from-nonfn', () => Array.from([1], 'x'));
tryit('new-Array-neg', () => new Array(-1));
tryit('new-Array-frac', () => new Array(1.5));
tryit('set-length', () => { const x = [1]; x.length = 2 ** 32; });
tryit('set-length-frac', () => { const x = [1]; x.length = 1.5; });
show('Array-ctor', new Array(3).length, new Array('3'), Array(1, 2), new Array(0), Array());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_array_callbacks_sort_generic(run, tier):
    """CATCHES: callback methods that visit holes, ignore thisArg or mutation during iteration, unstable or non-spec default sort (undefined/holes last), wrong comparator errors, and Array.prototype methods that fail on array-likes/strings or report wrong TypeError messages."""
    _ok(run([*tier, "-e", PROG_ARRAY_CALLBACKS_SORT_GENERIC]), "array_callbacks_sort_generic")


PROG_ARRAY_FROM_SPECIES_LENGTH = PRELUDE + r"""
show('from-string', Array.from('a\u{1F600}b'));
show('from-set', Array.from(new Set([1, 2, 2, 3])));
show('from-map', Array.from(new Map([[1, 'a']])));
show('from-arraylike', Array.from({ length: 3, 1: 'one' }));
show('from-mapfn', Array.from([1, 2], function (x, i) { return x * this.m + i; }, { m: 100 }));
show('from-iter', Array.from({ *[Symbol.iterator]() { yield 'g1'; yield 'g2'; } }));
show('from-length-clamp', Array.from({ length: -1 }), Array.from({ length: 2.9 }).length);
show('from-num', Array.from(5), Array.from(true));
tryit('from-null', () => Array.from(null));
tryit('from-undefined', () => Array.from());
tryit('from-bad-iter', () => Array.from({ [Symbol.iterator]: 5 }));
tryit('from-iter-noobj', () => Array.from({ [Symbol.iterator]() { return 1; } }));
const closed = [];
tryit('from-mapfn-throw-closes', () => Array.from({ [Symbol.iterator]() { let n = 0; return { next() { return { value: n++, done: false }; }, return() { closed.push('closed'); return {}; } }; } }, x => { if (x === 2) throw new Error('stop at 2'); return x; }));
show('from-closed', closed);
function Ctor(n) { this.made = n; }
const fromCtor = Array.from.call(Ctor, { length: 2, 0: 'a', 1: 'b' });
show('from-this-ctor', fromCtor instanceof Ctor, fromCtor.made, fromCtor.length, fromCtor[0]);
const fromCtorIter = Array.from.call(Ctor, ['p']);
show('from-this-ctor-iter', fromCtorIter.made, fromCtorIter.length, fromCtorIter[0]);
show('from-nonctor-this', Array.isArray(Array.from.call({}, [1])), Array.isArray(Array.from.call(() => {}, [1])));
show('of', Array.of(), Array.of(3), Array.of(1, 'b', null));
const ofCtor = Array.of.call(Ctor, 'x', 'y');
show('of-this', ofCtor instanceof Ctor, ofCtor.made, ofCtor.length, ofCtor[1]);
// species
class MyArr extends Array { tag() { return 'my' + this.length; } }
const ma = MyArr.from([1, 2, 3]);
show('species-from', ma instanceof MyArr, ma.tag());
show('species-map', ma.map(x => x) instanceof MyArr, ma.filter(Boolean).tag(), ma.slice(1).tag(), ma.splice(0, 1).tag(), ma.concat([9]).tag(), ma.flat().tag(), ma.flatMap(x => [x]).tag());
show('species-toX-are-plain', ma.toSorted() instanceof MyArr, ma.toReversed() instanceof MyArr, ma.with(0, 1) instanceof MyArr, ma.toSpliced(0) instanceof MyArr);
show('MyArr.of', MyArr.of(7).tag(), new MyArr(3).length, new MyArr(1, 2).length);
class NoSpecies extends Array { static get [Symbol.species]() { return Array; } }
show('species-override', new NoSpecies(1, 2, 3).map(x => x) instanceof NoSpecies, new NoSpecies(1, 2, 3).map(x => x) instanceof Array);
const weird = [1, 2]; weird.constructor = { [Symbol.species]: function (n) { this.len = n; } };
show('species-custom', weird.map(x => x * 2));
const weird2 = [1]; weird2.constructor = { [Symbol.species]: null };
show('species-null', Array.isArray(weird2.map(x => x)));
const weird3 = [1]; weird3.constructor = { [Symbol.species]: 5 };
tryit('species-bad', () => weird3.map(x => x));
const weird4 = [1]; weird4.constructor = 7;
tryit('species-ctor-not-obj', () => weird4.slice());
show('species-getter', Object.getOwnPropertyDescriptor(Array, Symbol.species).get.call('val'));
// length behaviors
const L = [1, 2, 3, 4, 5];
L.length = 2;
show('truncate', L, L.length);
L.length = 4;
show('extend', L);
L[9] = 'nine';
show('index-extends', L.length);
const big = []; big[4294967294] = 'max';
show('max-index', big.length);
const notIdx = []; notIdx[4294967295] = 'not-index';
show('not-index', notIdx.length, Object.keys(notIdx));
const frozenLen = [1, 2, 3];
Object.defineProperty(frozenLen, 'length', { writable: false });
tryit('push-nonwritable-len', () => frozenLen.push(4));
tryit('pop-nonwritable-len', () => frozenLen.pop());
show('after', frozenLen, Object.getOwnPropertyDescriptor(frozenLen, 'length'));
tryit('assign-len-nonwritable-strict', () => { 'use strict'; frozenLen.length = 0; });
const unconf = [1, 2, 3];
Object.defineProperty(unconf, 1, { value: 'pinned', configurable: false });
tryit('shrink-past-nonconfig', () => { 'use strict'; unconf.length = 0; });
show('shrink-result', unconf, unconf.length);
tryit('define-len', () => Reflect.defineProperty([1, 2], 'length', { value: -1 }));
show('define-len-shrink', Reflect.defineProperty([1, 2], 'length', { value: 1 }), Reflect.defineProperty(Object.freeze([1, 2]), 'length', { value: 1 }), Reflect.defineProperty(Object.freeze([1, 2]), 'length', { value: 2 }));
tryit('define-len-bad', () => Object.defineProperty([], 'length', { value: -1 }));
tryit('define-len-accessor', () => Object.defineProperty([], 'length', { get() { return 1; } }));
show('length-string-coerce', (() => { const a = [1, 2, 3]; a.length = '1'; return a; })());
tryit('length-obj-coerce', () => { const a = [1, 2, 3]; a.length = { valueOf() { return 2; } }; return a; });
tryit('length-bad-string', () => { const a = []; a.length = 'abc'; });
show('arraylike-huge', Array.prototype.indexOf.call({ length: 2 ** 53 + 10, [2 ** 53 - 2]: 'end' }, 'end', 2 ** 53 - 3));
tryit('push-overflow', () => Array.prototype.push.call({ length: 2 ** 53 - 1 }, 1));
tryit('unshift-overflow', () => Array.prototype.unshift.call({ length: 2 ** 53 - 1 }, 1));
tryit('concat-overflow', () => { const o = { length: 2 ** 53 - 1, [Symbol.isConcatSpreadable]: true }; return [1].concat(o); });
tryit('splice-overflow', () => Array.prototype.splice.call({ length: 2 ** 53 - 1 }, 0, 0, 1));
tryit('toSpliced-overflow', () => Array.prototype.toSpliced.call({ length: 2 ** 53 - 1 }, 0, 0, 1));
tryit('toReversed-big', () => Array.prototype.toReversed.call({ length: 2 ** 32 }));
tryit('with-big', () => Array.prototype.with.call({ length: 2 ** 32 }, 0, 1));
"""


def test_array_from_species_length(run):
    """CATCHES: Array.from/of ignoring iterables, mapFn, this-constructors or iterator closing; broken @@species for subclasses; and wrong array length semantics (truncation, max index, non-writable length, non-configurable elements, 2^53-1 overflow TypeErrors)."""
    _ok(run(["-e", PROG_ARRAY_FROM_SPECIES_LENGTH]), "array_from_species_length")


PROG_ARRAY_FROM_ASYNC = PRELUDE + r"""
(async () => {
  show('fromAsync-array', await Array.fromAsync([1, Promise.resolve(2), 3]));
  async function* gen() { yield 'a'; yield 'b'; }
  show('fromAsync-asyncgen', await Array.fromAsync(gen()));
  show('fromAsync-mapfn', await Array.fromAsync([1, 2], async (x, i) => x * 10 + i));
  show('fromAsync-arraylike', await Array.fromAsync({ length: 2, 0: Promise.resolve('p'), 1: 'q' }));
  show('fromAsync-sync-iter', await Array.fromAsync(new Set(['s1', 's2'])));
  try { await Array.fromAsync([1], 'nope'); } catch (e) { show('fromAsync-bad-mapfn', e.name, e.message); }
  try { await Array.fromAsync(null); } catch (e) { show('fromAsync-null', e.name, e.message); }
  try { await Array.fromAsync([Promise.reject(new Error('rej'))]); } catch (e) { show('fromAsync-reject', e.message); }
  function C() { this.c = 1; }
  const r = await Array.fromAsync.call(C, [7]);
  show('fromAsync-this', r instanceof C, r.length, r[0]);
  const p = Array.fromAsync([]);
  show('fromAsync-returns-promise', p instanceof Promise);
})();
"""


def test_array_from_async(run):
    """CATCHES: Array.fromAsync that fails to await elements, mishandles async/sync iterables, array-likes, mapFn, this-constructors, or reports rejections/TypeErrors synchronously instead of as rejections."""
    _ok(run(["-e", PROG_ARRAY_FROM_ASYNC]), "array_from_async")


PROG_OBJECT_KEYS_ASSIGN_PROTOTYPES = PRELUDE + r"""
const sym = Symbol('s');
const o = { b: 1, 10: 'ten', a: 2, 2: 'two', [sym]: 'sym', '-1': 'neg', '01': 'lead0', 4294967295: 'big', 4294967294: 'maxidx' };
show('keys', Object.keys(o));
show('ownKeys', Reflect.ownKeys(o));
show('getOwnPropertyNames', Object.getOwnPropertyNames(o));
show('getOwnPropertySymbols', Object.getOwnPropertySymbols(o));
show('values', Object.values({ x: 1, y: [2] }));
show('entries', Object.entries({ x: 1, 0: 'z' }));
show('entries-string', Object.entries('hi'), Object.keys('abc'), Object.values('ab'));
show('keys-array', Object.keys(['a', , 'c']));
const ordered = {}; ordered.z = 1; ordered[1] = 1; ordered.y = 1; delete ordered.z; ordered.z = 2;
show('keys-after-delete', Object.keys(ordered));
show('for-in', (() => { const out = []; const p = { inherited: 1, 5: 0 }; const c = Object.create(p); c.own = 1; c[3] = 0; for (const k in c) out.push(k); return out; })());
show('for-in-shadow', (() => { const out = []; const p = { x: 1, y: 2 }; const c = Object.create(p); Object.defineProperty(c, 'x', { value: 0, enumerable: false }); for (const k in c) out.push(k); return out; })());
show('fromEntries', Object.fromEntries([['a', 1], ['b', 2], ['a', 3]]), Object.fromEntries(new Map([[sym, 'v'], [1, 'one']])));
tryit('fromEntries-bad', () => Object.fromEntries([1]));
tryit('fromEntries-null', () => Object.fromEntries(null));
show('fromEntries-gen', Object.fromEntries((function* () { yield ['k', 'v']; yield new String('xy'); })()));
// assign
const order = [];
const src = new Proxy({ b: 1, a: 2, 1: 3 }, { get(t, k) { order.push('get:' + String(k)); return t[k]; }, ownKeys(t) { order.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor(t, k) { order.push('gopd:' + String(k)); return Reflect.getOwnPropertyDescriptor(t, k); } });
show('assign', Object.assign({ z: 0 }, src, null, undefined, 'xy', 5, { [sym]: 's' }));
show('assign-order', order);
const target = {}; Object.defineProperty(target, 'ro', { value: 1, writable: false });
tryit('assign-readonly', () => Object.assign(target, { ro: 2 }));
tryit('assign-to-null', () => Object.assign(null, {}));
show('assign-primitive-target', typeof Object.assign(1, { a: 1 }), Object.assign('s', { a: 1 }).a);
show('assign-setter', (() => { const log = []; const t = { set v(x) { log.push('set ' + x); } }; Object.assign(t, { v: 42 }); return log; })());
show('assign-getter-src', Object.assign({}, { get g() { return 'computed'; } }));
show('assign-nonenum', Object.assign({}, Object.defineProperty({}, 'hidden', { value: 1 })));
// hasOwn & co
show('hasOwn', Object.hasOwn({ a: 1 }, 'a'), Object.hasOwn({ a: 1 }, 'toString'), Object.hasOwn([1], 'length'), Object.hasOwn({ [sym]: 0 }, sym));
tryit('hasOwn-prim', () => Object.hasOwn('abc', 1));
tryit('hasOwn-null', () => Object.hasOwn(null, 'a'));
show('hasOwnProperty', ({ a: 1 }).hasOwnProperty('a'), Object.prototype.hasOwnProperty.call('str', 'length'), [].hasOwnProperty(0));
tryit('hasOwnProperty-null', () => Object.prototype.hasOwnProperty.call(null, 'a'));
show('propertyIsEnumerable', [1].propertyIsEnumerable(0), [1].propertyIsEnumerable('length'), Object.prototype.propertyIsEnumerable.call('ab', 0));
show('isPrototypeOf', Object.prototype.isPrototypeOf([]), Array.prototype.isPrototypeOf(Object.create(null)), Object.prototype.isPrototypeOf.call(null, 1));
tryit('isPrototypeOf-null-this', () => Object.prototype.isPrototypeOf.call(null, {}));
show('is', Object.is(NaN, NaN), Object.is(0, -0), Object.is('a', 'a'), Object.is({}, {}));
// create / prototypes
const proto = { greet() { return 'hi ' + this.n; } };
const c = Object.create(proto, { n: { value: 'bob', enumerable: true }, hidden: { value: 1 } });
show('create', c.greet(), Object.keys(c), Object.getPrototypeOf(c) === proto);
show('create-null', Object.getPrototypeOf(Object.create(null)), typeof Object.create(null).toString);
tryit('create-bad', () => Object.create(5));
tryit('create-bad-props', () => Object.create({}, { x: 5 }));
show('getPrototypeOf-prim', Object.getPrototypeOf('s') === String.prototype, Object.getPrototypeOf(1) === Number.prototype);
tryit('getPrototypeOf-null', () => Object.getPrototypeOf(null));
show('setPrototypeOf', Object.getPrototypeOf(Object.setPrototypeOf({}, null)), Object.setPrototypeOf(1, null));
tryit('setPrototypeOf-bad', () => Object.setPrototypeOf({}, 1));
tryit('setPrototypeOf-undefined', () => Object.setPrototypeOf(undefined, {}));
tryit('setPrototypeOf-cycle', () => { const a = {}; const b = Object.create(a); Object.setPrototypeOf(a, b); });
tryit('setPrototypeOf-nonext', () => Object.setPrototypeOf(Object.preventExtensions({}), {}));
show('setPrototypeOf-nonext-same', Object.setPrototypeOf(Object.preventExtensions({ q: 1 }), Object.prototype).q);
tryit('setPrototypeOf-ObjectProto', () => Object.setPrototypeOf(Object.prototype, {}));
show('reflect-setProto', Reflect.setPrototypeOf(Object.prototype, {}), Reflect.setPrototypeOf(Object.prototype, null));
// __proto__
const pp = {}; pp.__proto__ = Array.prototype;
show('__proto__-set', Array.isArray(pp), pp instanceof Array, typeof pp.push);
show('__proto__-literal', Object.getPrototypeOf({ __proto__: null }), Object.keys({ ['__proto__']: 1 }), Object.keys({ __proto__: [] }));
show('__proto__-desc', Object.keys(Object.getOwnPropertyDescriptor(Object.prototype, '__proto__')));
tryit('__proto__-cyclic', () => { const a = {}; const b = { __proto__: a }; a.__proto__ = b; });
tryit('__proto__-getter-null', () => Object.getOwnPropertyDescriptor(Object.prototype, '__proto__').get.call(null));
tryit('__proto__-setter-undef', () => Object.getOwnPropertyDescriptor(Object.prototype, '__proto__').set.call(undefined, {}));
show('__proto__-setter-prim', Object.getOwnPropertyDescriptor(Object.prototype, '__proto__').set.call(1, {}));
// legacy accessors
const la = {};
la.__defineGetter__('g', () => 'got');
la.__defineSetter__('s', function (v) { this._s = v; });
la.s = 5;
show('defineGetter', la.g, la._s, typeof la.__lookupGetter__('g'), la.__lookupSetter__('g'), typeof Object.create(la).__lookupSetter__('s'));
tryit('defineGetter-nonfn', () => ({}).__defineGetter__('x', 1));
tryit('defineGetter-frozen', () => Object.freeze({}).__defineGetter__('x', () => 1));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_object_keys_assign_prototypes(run, tier):
    """CATCHES: wrong own-key ordering (integer keys first, then insertion order, symbols last), for-in shadowing, Object.assign/fromEntries/hasOwn/create/setPrototypeOf semantics and error messages, __proto__ handling and the Annex B __defineGetter__ family."""
    _ok(run([*tier, "-e", PROG_OBJECT_KEYS_ASSIGN_PROTOTYPES]), "object_keys_assign_prototypes")


PROG_OBJECT_DESCRIPTORS_INTEGRITY = PRELUDE + r"""
const o = {};
Object.defineProperty(o, 'a', { value: 1 });
show('default-desc', Object.getOwnPropertyDescriptor(o, 'a'));
Object.defineProperty(o, 'b', { get() { return 'B'; }, enumerable: true });
show('accessor-desc', Object.getOwnPropertyDescriptor(o, 'b'));
show('missing-desc', Object.getOwnPropertyDescriptor(o, 'zz'));
tryit('redefine-nonconfig', () => Object.defineProperty(o, 'a', { value: 2 }));
show('redefine-same', Object.defineProperty(o, 'a', { value: 1, writable: false }) === o);
tryit('redefine-enum', () => Object.defineProperty(o, 'a', { enumerable: true }));
tryit('redefine-to-accessor', () => Object.defineProperty(o, 'a', { get() {} }));
tryit('mixed-desc', () => Object.defineProperty({}, 'x', { value: 1, get() {} }));
tryit('getter-nonfn', () => Object.defineProperty({}, 'x', { get: 5 }));
tryit('setter-nonfn', () => Object.defineProperty({}, 'x', { set: 'no' }));
tryit('desc-nonobj', () => Object.defineProperty({}, 'x', 5));
tryit('target-nonobj', () => Object.defineProperty(5, 'x', {}));
const w = {};
Object.defineProperty(w, 'v', { value: 1, writable: true, configurable: false });
Object.defineProperty(w, 'v', { value: 2 });
Object.defineProperty(w, 'v', { writable: false });
tryit('writable-to-true', () => Object.defineProperty(w, 'v', { writable: true }));
show('after-w', Object.getOwnPropertyDescriptor(w, 'v'));
const cfg = {};
Object.defineProperty(cfg, 'p', { value: 1, configurable: true });
Object.defineProperty(cfg, 'p', { get() { return 'now accessor'; } });
show('data-to-accessor', Object.getOwnPropertyDescriptor(cfg, 'p').writable, cfg.p, typeof Object.getOwnPropertyDescriptor(cfg, 'p').get);
Object.defineProperty(cfg, 'p', { value: 'data again' });
show('accessor-to-data', Object.getOwnPropertyDescriptor(cfg, 'p'));
const inh = Object.create({ value: 'from proto', enumerable: true });
show('desc-inherited-fields', Object.getOwnPropertyDescriptor(Object.defineProperty({}, 'k', inh), 'k'));
const descOrder = [];
const descProxy = new Proxy({}, { has(t, k) { descOrder.push('has:' + k); return ['enumerable', 'value'].includes(k); }, get(t, k) { descOrder.push('get:' + String(k)); return k === 'value' ? 9 : true; } });
Object.defineProperty({}, 'x', descProxy);
show('desc-read-order', descOrder);
const dps = Object.defineProperties({}, { x: { value: 1, enumerable: true }, y: { get() { return 2; }, enumerable: true }, [Symbol.for('z')]: { value: 3 } });
show('defineProperties', dps, Object.getOwnPropertySymbols(dps).length);
tryit('defineProperties-bad', () => Object.defineProperties({}, { x: { value: 1, get() {} } }));
tryit('defineProperties-nonobj', () => Object.defineProperties(1, {}));
show('getOwnPropertyDescriptors', Object.getOwnPropertyDescriptors({ a: 1, get b() { return 2; } }));
show('gopd-string', Object.getOwnPropertyDescriptor('abc', 1), Object.getOwnPropertyDescriptor('abc', 'length'));
show('gopd-array-len', Object.getOwnPropertyDescriptor([1, 2], 'length'));
show('gopd-fn', Object.getOwnPropertyDescriptor(function f(a, b) {}, 'length'), Object.getOwnPropertyDescriptor(function f() {}, 'name'), Object.getOwnPropertyDescriptor(function f() {}, 'prototype'));
show('gopd-class-proto', Object.getOwnPropertyDescriptor(class {}, 'prototype'));
// freeze / seal / preventExtensions
const fz = Object.freeze({ a: 1, nested: { b: 2 }, get acc() { return 1; } });
show('isFrozen', Object.isFrozen(fz), Object.isSealed(fz), Object.isExtensible(fz));
fz.a = 99; fz.nested.b = 3; fz.added = 1; delete fz.a;
show('frozen-sloppy', fz.a, fz.nested.b, fz.added);
tryit('frozen-strict-set', () => { 'use strict'; fz.a = 5; });
tryit('frozen-strict-add', () => { 'use strict'; fz.zz = 5; });
tryit('frozen-strict-delete', () => { 'use strict'; delete fz.a; });
show('frozen-desc', Object.getOwnPropertyDescriptor(fz, 'a'), Object.getOwnPropertyDescriptor(fz, 'acc').configurable);
const sl = Object.seal({ a: 1 });
sl.a = 2; sl.b = 3; delete sl.a;
show('sealed', sl, Object.isSealed(sl), Object.isFrozen(sl), Object.getOwnPropertyDescriptor(sl, 'a'));
const pe = Object.preventExtensions({ a: 1 });
pe.b = 2; delete pe.a;
show('preventExtensions', pe, Object.isExtensible(pe), Object.isSealed(pe), Object.isFrozen(pe));
show('empty-nonext', Object.isFrozen(Object.preventExtensions({})), Object.isSealed(Object.preventExtensions({})));
show('prims', Object.freeze(1), Object.isFrozen('x'), Object.isSealed(2), Object.isExtensible(3), Object.preventExtensions('s'), Object.seal(true));
const fa = Object.freeze([1, 2]);
tryit('frozen-array-push', () => fa.push(3));
tryit('frozen-array-sort', () => fa.sort());
tryit('frozen-array-shift', () => fa.shift());
show('frozen-array-concat-ok', fa.concat(3), fa.toSorted(), Object.isFrozen(fa));
tryit('sealed-array-push', () => Object.seal([1]).push(2));
tryit('nonext-array-push', () => Object.preventExtensions([1]).push(2));
show('sealed-array-set', (() => { const a = Object.seal([1, 2]); a[0] = 'z'; return a; })());
// freeze on proxy logs traps
const plog = [];
const fp = new Proxy({ x: 1 }, { preventExtensions(t) { plog.push('pe'); return Reflect.preventExtensions(t); }, ownKeys(t) { plog.push('ownKeys'); return Reflect.ownKeys(t); }, defineProperty(t, k, d) { plog.push('dp:' + k + ':' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); }, getOwnPropertyDescriptor(t, k) { plog.push('gopd:' + k); return Reflect.getOwnPropertyDescriptor(t, k); } });
Object.freeze(fp);
show('freeze-proxy-traps', plog);
plog.length = 0;
show('isFrozen-proxy', Object.isFrozen(fp), plog);
const badFreeze = new Proxy({}, { preventExtensions() { return false; } });
tryit('freeze-proxy-false', () => Object.freeze(badFreeze));
tryit('seal-proxy-false', () => Object.seal(badFreeze));
tryit('pe-proxy-false', () => Object.preventExtensions(badFreeze));
show('reflect-pe-false', Reflect.preventExtensions(badFreeze));
// toString tags & valueOf
show('toString-tags', [undefined, null, [], {}, () => {}, new Date(0), /x/, 1, 's', true, Symbol(), 1n, new Error('e'), Math, JSON, (function () { return arguments; })(), new Map(), Promise.resolve(), { [Symbol.toStringTag]: 'Custom' }, Object.create(null)].map(v => Object.prototype.toString.call(v)));
show('toLocaleString', ({ toString() { return 'TS'; } }).toLocaleString(), [1, 'a', null].toLocaleString());
tryit('toLocaleString-null', () => Object.prototype.toLocaleString.call(null));
show('valueOf', typeof Object.prototype.valueOf.call(5), Object.prototype.valueOf.call(o) === o);
tryit('valueOf-null', () => Object.prototype.valueOf.call(null));
show('Object-ctor', typeof Object(1), Object('s') instanceof String, Object(null) instanceof Object, Object(o) === o, new Object(true).valueOf());
"""


def test_object_descriptors_integrity(run):
    """CATCHES: defineProperty validation and redefinition rules, descriptor field read order, defineProperties/getOwnPropertyDescriptors, freeze/seal/preventExtensions (incl. proxies and arrays) and Object.prototype.toString tags."""
    _ok(run(["-e", PROG_OBJECT_DESCRIPTORS_INTEGRITY]), "object_descriptors_integrity")


PROG_OBJECT_EXOTIC_RECEIVERS = PRELUDE + r"""
// arguments objects (mapped vs unmapped)
function mapped(a, b) {
  const out = [];
  arguments[0] = 'changed-via-arguments';
  out.push(a);
  b = 'changed-via-param';
  out.push(arguments[1]);
  Object.defineProperty(arguments, 0, { value: 'defined' });
  out.push(a);
  Object.defineProperty(arguments, 1, { writable: false });
  b = 'after-unmap';
  out.push(arguments[1]);
  Object.defineProperty(arguments, 0, { get() { return 'getter'; } });
  a = 'param-after-accessor';
  out.push(arguments[0]);
  out.push(Object.getOwnPropertyDescriptor(arguments, 1));
  out.push(Object.prototype.toString.call(arguments), arguments.length, typeof arguments[Symbol.iterator], Object.keys(arguments));
  return out;
}
show('mapped-arguments', mapped('A', 'B'));
function unmapped(a) { 'use strict'; arguments[0] = 'x'; return [a, arguments[0], Object.getOwnPropertyNames(arguments).sort()]; }
show('unmapped-arguments', unmapped('orig'));
function gopdArgs(a) { a = 'live'; return Object.getOwnPropertyDescriptor(arguments, 0); }
show('arguments-gopd-live', gopdArgs('stale'));
tryit('strict-callee', () => (function () { 'use strict'; return arguments.callee; })());
// typed arrays through Object/Reflect APIs
const ta = new Uint8Array([10, 20, 30]);
ta.extra = 'expando';
show('ta-keys', Object.keys(ta), Object.values(ta), Object.entries(ta), Object.getOwnPropertyNames(ta));
show('ta-gopd', Object.getOwnPropertyDescriptor(ta, 1), Object.getOwnPropertyDescriptor(ta, 5), Object.getOwnPropertyDescriptor(ta, '-0'), Object.getOwnPropertyDescriptor(ta, '1.5'));
show('ta-hasOwn', ta.hasOwnProperty(2), ta.hasOwnProperty(3), ta.hasOwnProperty('-0'), ta.hasOwnProperty('extra'), 1 in ta, 7 in ta);
show('ta-define', Reflect.defineProperty(ta, 0, { value: 99 }), ta[0], Reflect.defineProperty(ta, 0, { value: 1, writable: false }), Reflect.defineProperty(ta, 0, { get() {} }), Reflect.defineProperty(ta, 9, { value: 1 }), Reflect.defineProperty(ta, '1.5', { value: 1 }), Reflect.defineProperty(ta, 'name', { value: 'ok', enumerable: true }));
show('ta-set', Reflect.set(ta, 1, 300), ta[1], Reflect.set(ta, 10, 1), Reflect.set(ta, '-0', 1), Reflect.set(ta, 'prop', 1), ta.prop);
const recv = {};
show('ta-set-receiver', Reflect.set(ta, 0, 5, recv), recv, Reflect.set(ta, 99, 5, recv), Object.keys(recv));
show('ta-get-receiver', Reflect.get(ta, 2, {}), Reflect.get(ta, 99, {}), Reflect.get(ta, '1.5', {}));
const big = new BigInt64Array(2);
show('bigint-ta-set', Reflect.set(big, 0, 5n), big[0], (() => { try { return Reflect.set(big, 1, 1); } catch (e) { return e.name; } })());
show('ta-freeze', (() => { try { Object.freeze(new Uint8Array(1)); return 'frozen'; } catch (e) { return e.name + ': ' + e.message; } })(), Object.isFrozen(new Uint8Array(0)), Object.isFrozen(Object.freeze(new Uint8Array(0))));
// proxy receivers of Object.* helpers
const sym = Symbol('ps');
const prox = new Proxy({ a: 1, [sym]: 2 }, { getOwnPropertyDescriptor(t, k) { return k === 'a' ? { value: 'A', enumerable: false, configurable: true, writable: true } : Reflect.getOwnPropertyDescriptor(t, k); } });
show('proxy-gopds', Object.getOwnPropertyDescriptors(prox));
show('proxy-symbols', Object.getOwnPropertySymbols(prox).map(String));
show('proxy-propertyIsEnumerable', prox.propertyIsEnumerable('a'), Object.prototype.propertyIsEnumerable.call(prox, sym), Object.prototype.propertyIsEnumerable.call(prox, 'zz'));
show('proxy-hasOwnProperty', Object.prototype.hasOwnProperty.call(prox, 'a'), Object.prototype.hasOwnProperty.call(prox, 'nope'));
const getterHolder = new Proxy({}, { getOwnPropertyDescriptor(t, k) { return k === 'acc' ? { get: function proxGetter() { return 1; }, configurable: true } : k === 'dat' ? { value: 1, configurable: true } : undefined; } });
show('lookupGetter-proxy', ({}).__lookupGetter__.call(getterHolder, 'acc').name, ({}).__lookupGetter__.call(getterHolder, 'dat'), ({}).__lookupSetter__.call(getterHolder, 'acc'), ({}).__lookupGetter__.call(Object.create(getterHolder), 'acc').name);
show('lookupGetter-chain', ({}).__lookupGetter__('__proto__').name, Object.create(null).__lookupGetter__, ({ x: 1 }).__lookupGetter__('x'), ({}).__lookupGetter__('nope'));
show('defineGetter-proxy', (() => { const log = []; const p = new Proxy({}, { defineProperty(t, k, d) { log.push(k + ':' + Object.keys(d).join('/')); return Reflect.defineProperty(t, k, d); } }); p.__defineSetter__('w', v => {}); return log; })());
// getPrototypeOf on primitives and constructing Object subclasses
show('proto-prims', Object.getPrototypeOf(true) === Boolean.prototype, Object.getPrototypeOf(Symbol()) === Symbol.prototype, Object.getPrototypeOf(1n) === BigInt.prototype, Reflect.getPrototypeOf(Object(1n)) === BigInt.prototype);
class SubObj extends Object { constructor() { super(); this.tag = 'sub'; } }
const so = new SubObj();
show('Object-subclass', so instanceof SubObj, so.tag, Object.getPrototypeOf(so) === SubObj.prototype);
function NT() {}
NT.prototype = null;
show('Object-newtarget-nonobj-proto', Object.getPrototypeOf(Reflect.construct(Object, [], NT)) === Object.prototype);
show('Object-newtarget-with-arg', typeof Reflect.construct(Object, [5], NT), Reflect.construct(Object, [{ q: 1 }], NT).q);
// non-configurable accessor redefinition
const acc = {};
const getA = () => 'a', setA = v => {};
Object.defineProperty(acc, 'p', { get: getA, set: setA, configurable: false });
show('nc-accessor', Reflect.defineProperty(acc, 'p', { get: getA }), Reflect.defineProperty(acc, 'p', { set: setA }), Reflect.defineProperty(acc, 'p', { get: () => 'b' }), Reflect.defineProperty(acc, 'p', { set: undefined }), Reflect.defineProperty(acc, 'p', { configurable: true }), Reflect.defineProperty(acc, 'p', { enumerable: true }), Reflect.defineProperty(acc, 'p', {}), Reflect.defineProperty(acc, 'p', { value: 1 }));
const ncData = Object.defineProperty({}, 'd', { value: NaN, writable: false, configurable: false });
show('nc-data-samevalue', Reflect.defineProperty(ncData, 'd', { value: NaN }), Reflect.defineProperty(Object.defineProperty({}, 'z', { value: 0 }), 'z', { value: -0 }), Reflect.defineProperty(ncData, 'd', { writable: false }));
const cfgAcc = {};
Object.defineProperty(cfgAcc, 'q', { get() { return 1; }, configurable: true });
Object.defineProperty(cfgAcc, 'q', { set(v) { this._q = v; } });
show('accessor-merge', typeof Object.getOwnPropertyDescriptor(cfgAcc, 'q').get, typeof Object.getOwnPropertyDescriptor(cfgAcc, 'q').set);
Object.defineProperty(cfgAcc, 'q', { get: undefined });
show('accessor-clear-getter', Object.getOwnPropertyDescriptor(cfgAcc, 'q').get, cfgAcc.q);
show('generic-desc', (() => { const o = {}; Object.defineProperty(o, 'g', {}); return Object.getOwnPropertyDescriptor(o, 'g'); })(), (() => { const o = { x: 1 }; Object.defineProperty(o, 'x', { enumerable: false }); return Object.getOwnPropertyDescriptor(o, 'x'); })());
const nwl = [1, 2];
Object.defineProperty(nwl, 'length', { writable: false });
show('array-index-past-nonwritable-length', Reflect.defineProperty(nwl, 2, { value: 3 }), Reflect.defineProperty(nwl, 1, { value: 'ok' }), nwl, Reflect.set(nwl, 5, 1), nwl.length);
show('array-length-define-variants', (() => { const a = [1, 2, 3]; Object.defineProperty(a, 'length', { value: 1, writable: false }); return [a, Object.getOwnPropertyDescriptor(a, 'length'), Reflect.defineProperty(a, 'length', { value: 1 }), Reflect.defineProperty(a, 'length', { writable: true }), Reflect.defineProperty(a, 'length', { value: 2 })]; })());
show('array-length-shrink-partial', (() => { const a = [0, 1, 2, 3]; Object.defineProperty(a, 2, { value: 'nc', configurable: false }); const ok = Reflect.defineProperty(a, 'length', { value: 0 }); return [ok, a.length, a]; })());
show('array-length-shrink-to-nonwritable', (() => { const a = [0, 1, 2]; Object.defineProperty(a, 1, { value: 'nc', configurable: false }); const ok = Reflect.defineProperty(a, 'length', { value: 0, writable: false }); return [ok, a.length, Object.getOwnPropertyDescriptor(a, 'length').writable]; })());
// Object.defineProperties: ordering & atomicity
show('defineProperties-order', (() => { const log = []; const props = new Proxy({ b: { value: 1 }, a: { value: 2 } }, { ownKeys(t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor(t, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, get(t, k) { log.push('get ' + k); return t[k]; } }); Object.defineProperties({}, props); return log; })());
show('defineProperties-partial-failure', (() => { const o = Object.defineProperty({}, 'locked', { value: 1 }); try { Object.defineProperties(o, { fresh: { value: 'f', enumerable: true }, locked: { value: 2 } }); } catch (e) { return [e.name, Object.keys(o)]; } })());
show('defineProperties-nonenum-skipped', Object.keys(Object.defineProperties({}, Object.create({ inherited: { value: 1 } }, { own: { value: { value: 2, enumerable: true }, enumerable: true }, hidden: { value: { value: 3 }, enumerable: false } }))));
tryit('defineProperties-props-null', () => Object.defineProperties({}, null));
show('create-with-props-null-proto', Object.keys(Object.create(null, { k: { value: 1, enumerable: true } })));
show('freeze-accessor-and-symbol', (() => { const o = { get g() { return 1; }, [Symbol('fz')]: 2 }; Object.freeze(o); const d = Object.getOwnPropertyDescriptor(o, 'g'); return [d.configurable, 'set' in d, Object.isFrozen(o), Object.getOwnPropertyDescriptor(o, Object.getOwnPropertySymbols(o)[0]).writable]; })());
show('isFrozen-variants', Object.isFrozen(Object.preventExtensions({ a: 1 })), Object.isFrozen(Object.preventExtensions(Object.defineProperty({}, 'a', { get() {}, configurable: false }))), Object.isSealed(Object.preventExtensions(Object.defineProperty({}, 'a', { value: 1, writable: true, configurable: false }))), Object.isFrozen(Object.preventExtensions(Object.defineProperty({}, 'a', { value: 1, writable: true, configurable: false }))));
"""


def test_object_exotic_receivers(run):
    """CATCHES: Object/Reflect operations on exotic receivers: mapped arguments aliasing, typed-array integer-indexed properties, proxies seen through getOwnPropertyDescriptors/propertyIsEnumerable/__lookupGetter__, plus non-configurable accessor redefinition, ArraySetLength partial failure and defineProperties atomicity."""
    _ok(run(["-e", PROG_OBJECT_EXOTIC_RECEIVERS]), "object_exotic_receivers")


PROG_STRING_METHODS = PRELUDE + r"""
show('pad', 'abc'.padStart(6), 'abc'.padStart(8, '12'), 'abc'.padEnd(7, 'xy'), 'abc'.padStart(2, 'z'), 'abc'.padEnd(6, ''), 'a'.padStart(3, undefined));
show('at', 'abc'.at(-1), 'abc'.at(5), 'abc'.at(), '\u{1F600}'.at(0).length);
show('charAt', 'abc'.charAt(1), 'abc'.charAt(9), 'abc'.charAt(-1), 'abc'.charAt(NaN));
show('charCodeAt', 'abc'.charCodeAt(1), 'abc'.charCodeAt(9), '\u{1F600}'.charCodeAt(1));
show('codePointAt', '\u{1F600}x'.codePointAt(0), '\u{1F600}x'.codePointAt(1), '\u{1F600}x'.codePointAt(2), 'a'.codePointAt(5));
show('trim', '  \t\n x y \u00a0\ufeff'.trim(), ' \u2028x '.trimStart(), ' x \u3000'.trimEnd(), '\u180e x'.trim().length);
show('trim-alias', String.prototype.trimLeft === String.prototype.trimStart, String.prototype.trimRight.name);
show('repeat', 'ab'.repeat(3), 'x'.repeat(0), ''.repeat(5));
tryit('repeat-neg', () => 'x'.repeat(-1));
tryit('repeat-inf', () => 'x'.repeat(Infinity));
tryit('repeat-huge', () => 'x'.repeat(2 ** 31));
show('startsWith', 'hello'.startsWith('ell', 1), 'hello'.startsWith(''), 'hello'.endsWith('ell', 4), 'hello'.endsWith('o', 99), 'hello'.includes('ll', 3));
tryit('startsWith-regexp', () => 'x'.startsWith(/x/));
tryit('includes-regexp', () => 'x'.includes(/x/));
tryit('endsWith-regexp', () => 'x'.endsWith(/x/));
const notRe = /x/; notRe[Symbol.match] = false;
show('startsWith-unmarked-re', '/x/'.startsWith(notRe));
show('indexOf', 'abcabc'.indexOf('c'), 'abcabc'.indexOf('c', 3), 'abc'.indexOf(''), 'abc'.indexOf('', 10), 'abcabc'.lastIndexOf('a'), 'abcabc'.lastIndexOf('a', 2), 'abc'.lastIndexOf('', 1), 'aaa'.lastIndexOf('a', -5));
show('slice', 'hello'.slice(1, -1), 'hello'.slice(-3), 'hello'.slice(3, 1), 'hello'.slice(NaN));
show('substring', 'hello'.substring(3, 1), 'hello'.substring(-5, 2), 'hello'.substring(1, NaN), 'hello'.substring(Infinity));
show('substr', 'hello'.substr(1, 3), 'hello'.substr(-3, 2), 'hello'.substr(2), 'hello'.substr(1, -1), 'hello'.substr(-99, 2));
show('split', 'a,b,,c'.split(','), 'abc'.split(''), 'a,b,c'.split(',', 2), 'abc'.split(), 'abc'.split(undefined, 0), ''.split(','), ''.split(''), 'a<>b<>'.split('<>'), '\u{1F600}a'.split(''));
show('split-limit', 'a,b'.split(',', -1), 'a,b'.split(',', 2 ** 32 + 1), 'a,b'.split(',', 0));
show('concat', 'a'.concat(1, null, [2, 3]), String.prototype.concat.call(1, 2));
show('case', 'Stra\u00dfe'.toUpperCase(), '\u0130stanbul'.toLowerCase().length, '\u03a3\u0391\u03a3'.toLowerCase(), '\u01c5'.toLowerCase(), '\ufb01'.toUpperCase(), '\u0149'.toUpperCase());
show('localeCase', 'I'.toLocaleLowerCase('tr'), 'i'.toLocaleUpperCase('tr'), 'I'.toLocaleLowerCase('en-US'), 'Ii'.toLocaleLowerCase());
show('localeCompare', 'a'.localeCompare('b'), 'b'.localeCompare('a'), 'a'.localeCompare('a'), ['b', 'a', 'C', 'c'].sort((x, y) => x.localeCompare(y)));
show('html', 'x'.anchor('a"b'), 'x'.big(), 'x'.blink(), 'x'.bold(), 'x'.fixed(), 'x'.fontcolor('red'), 'x'.fontsize(7), 'x'.italics(), 'x'.link('u'), 'x'.small(), 'x'.strike(), 'x'.sub(), 'x'.sup());
tryit('html-null', () => String.prototype.bold.call(null));
show('fromCharCode', String.fromCharCode(72, 105, 0x10041, -1 >>> 16), String.fromCharCode(), String.fromCharCode(0xD83D, 0xDE00));
show('fromCodePoint', String.fromCodePoint(0x1F600, 97), String.fromCodePoint());
tryit('fromCodePoint-big', () => String.fromCodePoint(0x110000));
tryit('fromCodePoint-frac', () => String.fromCodePoint(1.5));
tryit('fromCodePoint-neg', () => String.fromCodePoint(-1));
tryit('fromCodePoint-nan', () => String.fromCodePoint('x'));
show('raw', String.raw`a\n${1 + 1}\u{41}`, String.raw({ raw: ['x', 'y', 'z'] }, 1), String.raw({ raw: [] }), String.raw({ raw: { length: 1, 0: 'only' } }, 'ignored'));
tryit('raw-string-raw', () => String.raw({ raw: 'abc' }, '-', '+', '*'));
tryit('raw-bad', () => String.raw({}));
tryit('raw-undefined', () => String.raw());
show('wellFormed', 'ab'.isWellFormed(), '\uD800'.isWellFormed(), 'a\uDC00b'.isWellFormed(), '\u{1F600}'.isWellFormed());
show('toWellFormed', [...'a\uD800b\uDC00'.toWellFormed()].map(c => c.charCodeAt(0).toString(16)), '\u{1F600}'.toWellFormed() === '\u{1F600}');
show('iter', [...'a\u{1F600}\uD800b'].map(c => c.length));
const si = 'xy'[Symbol.iterator]();
show('iter-proto', Object.prototype.toString.call(si), si.next(), si.next(), si.next(), si.next());
tryit('iter-next-bad', () => si.next.call({}));
show('length', 'a\u{1F600}'.length, String.prototype.length, String.length);
show('String()', String(), String(null), String(Symbol('d')), String([1, [2]]), String({}), String(-0), new String('ab').length, typeof new String('x'));
tryit('String+symbol', () => '' + Symbol());
tryit('template+symbol', () => `${Symbol()}`);
show('String-obj', Object.keys(new String('ab')), 1 in new String('ab'), new String('ab')[1], Object.getOwnPropertyNames(new String('ab')));
show('valueOf', new String('v').valueOf(), 'p'.toString(), String.prototype.valueOf.call(new String('q')));
tryit('valueOf-bad', () => String.prototype.valueOf.call({}));
tryit('toString-bad', () => String.prototype.toString.call(1));
show('search-str', 'abc'.search('c'), 'a.c'.search('.'), 'abc'.match('b').index, 'aXbX'.matchAll('X').next().value.index);
tryit('matchAll-nonglobal', () => 'a'.matchAll(/a/));
show('normalize-basic', 'abc'.normalize() === 'abc');
show('coercions', 'abc'.indexOf({ toString() { return 'b'; } }), 'aaa'.padStart({ valueOf() { return 5; } }, '-'), String.prototype.at.call(12345, -2));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_string_methods(run, tier):
    """CATCHES: incorrect String.prototype pad/at/charAt/codePointAt/trim/repeat/startsWith/indexOf/slice/substring/substr/split/case-mapping/HTML methods, fromCharCode/fromCodePoint/raw RangeErrors, isWellFormed/toWellFormed and the string iterator."""
    _ok(run([*tier, "-e", PROG_STRING_METHODS]), "string_methods")


PROG_STRING_REPLACE_SPLIT_PATTERNS = PRELUDE + r"""
show('replace-first', 'a-b-c'.replace('-', '+'), 'aaa'.replace('a', 'b'), 'abc'.replace('', '_'), 'abc'.replace('z', 'y'));
show('replace-patterns', 'John Smith'.replace('Smith', "[$&]"), 'abc'.replace('b', "[$`]"), 'abc'.replace('b', "[$']"), 'abc'.replace('b', '$$'), 'abc'.replace('b', '$1'), 'abc'.replace('b', '$<name>'), 'abc'.replace('b', '$'), 'abc'.replace('b', '$0'), 'abc'.replace('b', '$&$&'), 'abc'.replace('b', '$`$\''));
show('replace-fn', 'a1b2'.replace('1', (m, off, str) => `<${m}|${off}|${str}>`), 'xyz'.replace('y', () => '$&'), 'xyz'.replace('y', () => 42), 'xyz'.replace('y', () => undefined));
show('replaceAll', 'a.b.c'.replaceAll('.', '/'), 'aaaa'.replaceAll('aa', 'b'), 'abc'.replaceAll('', '-'), 'x-y-z'.replaceAll('-', (m, off) => off), 'aXbX'.replaceAll('X', '[$&$`]'), ''.replaceAll('', 'E'));
tryit('replaceAll-nonglobal-re', () => 'a'.replaceAll(/a/, 'b'));
show('replaceAll-global-re', 'aXa'.replaceAll(/a/g, 'b'));
show('replace-coerce', 'a1b'.replace(1, 'one'), 'null'.replace(null, 'N'), 'und'.replace(undefined, 'U'), 'undefined'.replace(undefined, 'U'), String.prototype.replace.call(12321, 2, 'x'));
const custom = { [Symbol.replace](s, r) { return `custom(${s},${r})`; } };
show('symbol-replace', 'str'.replace(custom, 'rep'), 'str'.replaceAll(custom, 'rep2'));
const splitter = { [Symbol.split](s, lim) { return ['custom', s, lim]; } };
show('symbol-split', 'a,b'.split(splitter, 3));
const searcher = { [Symbol.search](s) { return 'searched:' + s; } };
const matcher = { [Symbol.match](s) { return ['matched:' + s]; } };
show('symbol-search-match', 'q'.search(searcher), 'q'.match(matcher));
tryit('symbol-replace-noncallable', () => 'x'.replace({ [Symbol.replace]: 5 }, ''));
tryit('symbol-split-noncallable', () => 'x'.split({ [Symbol.split]: 'no' }));
tryit('symbol-match-noncallable', () => 'x'.match({ [Symbol.match]: {} }));
tryit('symbol-search-noncallable', () => 'x'.search({ [Symbol.search]: 1 }));
tryit('symbol-matchAll-noncallable', () => 'x'.matchAll({ [Symbol.matchAll]: 1 }));
show('symbol-null-ignored', 'a.b'.split({ [Symbol.split]: null, toString() { return '.'; } }), 'a.b'.replace({ [Symbol.replace]: undefined, toString() { return '.'; } }, '!'));
tryit('replace-on-null', () => String.prototype.replace.call(null, 'a', 'b'));
tryit('split-on-undefined', () => String.prototype.split.call(undefined, ','));
show('split-sep-coerce', 'a1b1c'.split(1), 'a,b'.split({ toString() { return ','; } }), 'abc'.split(null), 'anullb'.split(null), 'aundefinedb'.split(undefined));
show('split-limit-coerce', 'a,b,c'.split(',', '2'), 'a,b,c'.split(',', -1).length, 'a,b,c'.split(',', 1.9), 'a,b,c'.split(',', null), 'a,b,c'.split(',', undefined).length);
show('split-order', (() => { const log = []; 'a,b'.split({ toString() { log.push('sep'); return ','; } }, { valueOf() { log.push('limit'); return 5; } }); return log; })());
show('split-unicode', '\u{1F600}\u{1F601}'.split('\uDE00'), 'a\u00e9b'.split('\u00e9'));
show('match-string', 'a.c abc'.match('.c').index, 'abc'.match('b')[0], 'abc'.match('z'), 'a+b'.search('\\+'), 'a.b'.search('.'));
show('concat-many', ''.concat(...Array.from({ length: 5 }, (_, i) => i)), 'x'.concat(), 'x'.concat(undefined));
tryit('concat-symbol', () => 'x'.concat(Symbol('no')));
show('at-coerce', 'abc'.at('1'), 'abc'.at(null), 'abc'.at(-0), 'abc'.at(Infinity), 'abc'.at(-Infinity), 'abc'.at(NaN));
show('indexOf-coerce', 'a1a'.indexOf(1), 'abc'.indexOf('c', -100), 'abc'.indexOf('a', Infinity), 'aaa'.lastIndexOf('a', NaN), 'aaa'.lastIndexOf('a', 1.5), 'abc'.includes(''), 'abc'.startsWith('b', 1.9));
show('padStart-big-fill', 'x'.padStart(5, 'abcdef'), 'x'.padEnd(4, '\u{1F600}').length, ''.padStart(3, 'z'), 'abc'.padStart(NaN, 'z'), 'ab'.padEnd(-1, 'z'));
show('substring-coerce', 'hello'.substring('1', '3'), 'hello'.substring(null, 2), 'hello'.slice(undefined, undefined), 'hello'.substr(undefined, 2), 'hello'.slice(-Infinity, 2), 'hello'.substring(2, -Infinity));
show('codepoint-edge', String.fromCodePoint(0x10FFFF).length, String.fromCodePoint(0xD800).length, '\u{10FFFF}'.codePointAt(0), String.fromCharCode(65.9, '66', null, 65536 + 67));
show('case-misc', '\u01c8'.toUpperCase(), '\u01c8'.toLowerCase(), '\u038c\u03a3\u039f'.toLowerCase(), '\u03a3'.toLowerCase(), 'A\u03a3 b'.toLowerCase(), '\u1fb3'.toUpperCase(), '\u0130'.toLowerCase().length, '\u00df'.toLocaleUpperCase(), String.prototype.toUpperCase.call(true));
show('localeCompare-misc', 'a'.localeCompare('B'), 'r\u00e9sum\u00e9'.localeCompare('resume'), ''.localeCompare(''), 'a'.localeCompare(), 'undefined'.localeCompare(), 'A\u030a'.localeCompare('\u00c5'));
tryit('localeCompare-null', () => String.prototype.localeCompare.call(null, 'a'));
show('trim-all-ws', JSON.stringify('\u0009\u000A\u000B\u000C\u000D \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeffx\u200b'.trim()));
show('string-index-props', (() => { const s = new String('ab'); s[5] = 'x'; s[0] = 'ignored'; return [s[0], s[5], s.length, Object.keys(s)]; })(), (() => { 'use strict'; try { const s = new String('ab'); s[0] = 'z'; return 'no error'; } catch (e) { return e.name + ': ' + e.message; } })());
show('string-iterator-surrogates', Array.from('\u{1f600}\uD83D|\uDE00'), [...'\uD800\u{10000}'].map(c => c.length));
"""


def test_string_replace_split_patterns(run):
    """CATCHES: string-pattern replace/replaceAll with $-replacement patterns and function replacers, Symbol.replace/split/search/match dispatch and their TypeErrors, argument coercion order, and Unicode-edge behaviour of split/case mapping/trim."""
    _ok(run(["-e", PROG_STRING_REPLACE_SPLIT_PATTERNS]), "string_replace_split_patterns")


PROG_STRING_ASTRAL_AND_LONE_SURROGATES = PRELUDE + r"""
const hex = s => Array.from({ length: s.length }, (_, i) => s.charCodeAt(i).toString(16)).join(' ');
const MAXC = '\u{10FFFF}', PUA = '\u{10F800}', EMO = '\u{1F600}';
const joinedMax = '\uDBFF' + '\uDFFF';
const joinedPua = '\uDBFE' + '\uDC00';
const joinedEmo = '\uD83D' + '\uDE00';
console.log('joined-equal', joinedMax === MAXC, joinedPua === PUA, joinedEmo === EMO, joinedMax.length, hex(joinedMax), hex(PUA));
console.log('fromCharCode', String.fromCharCode(0xDBFF, 0xDFFF) === MAXC, String.fromCharCode(0xDBFE, 0xDC00) === PUA, String.fromCodePoint(0x10F800) === PUA);
console.log('iterate', [...joinedMax].length, [...MAXC].length, [...(MAXC + PUA + 'x')].map(c => c.codePointAt(0).toString(16)).join(','), [...joinedPua].map(c => c.length).join(','), [...joinedEmo].length);
console.log('codePointAt', MAXC.codePointAt(0).toString(16), MAXC.codePointAt(1).toString(16), PUA.codePointAt(0).toString(16), joinedMax.codePointAt(0).toString(16));
console.log('charCodeAt', MAXC.charCodeAt(0).toString(16), MAXC.charCodeAt(1).toString(16), PUA.charCodeAt(1).toString(16));
console.log('slice', hex(MAXC.slice(0, 1)), hex(MAXC.slice(1)), hex(('a' + PUA + 'b').slice(1, 3)), (PUA + PUA).slice(2) === PUA, hex(MAXC.substring(1, 2)), hex(MAXC.substr(-1)), hex(MAXC.at(-1)), hex(MAXC[0]));
console.log('rejoin-halves', MAXC.slice(0, 1) + MAXC.slice(1) === MAXC, (PUA.slice(0, 1) + PUA.slice(1)).codePointAt(0).toString(16), [...(MAXC.slice(0, 1) + MAXC.slice(1))].length);
console.log('indexOf', ('ab' + MAXC + 'c').indexOf('c'), ('ab' + MAXC).indexOf('\uDFFF'), ('ab' + MAXC).lastIndexOf('\uDBFF'), ('x' + PUA).indexOf(PUA), (PUA + 'z').includes('\uDC00'), MAXC.startsWith('\uDBFF'), MAXC.endsWith('\uDFFF'), ('q' + EMO + 'q').indexOf(EMO, 2));
console.log('split', JSON.stringify((MAXC + ',' + PUA).split(',').map(hex)), JSON.stringify(MAXC.split('').map(hex)), JSON.stringify(('a' + EMO + 'b').split(EMO)));
console.log('replace', hex(('a' + MAXC + 'b').replace(MAXC, '-')), hex(('a' + PUA + 'b').replaceAll(PUA, '+')), hex(('x' + EMO).replace(EMO, '$&$&')));
console.log('json', JSON.stringify(MAXC), JSON.stringify(PUA), JSON.stringify('\uDBFF'), JSON.stringify(joinedMax), JSON.stringify(MAXC.slice(0, 1) + 'x'), JSON.parse('"\\udbff\\udfff"') === MAXC, JSON.parse('"\\udbfe\\udc00"') === PUA, JSON.parse(JSON.stringify(PUA)) === PUA);
console.log('uri', encodeURIComponent(MAXC), encodeURIComponent(PUA), decodeURIComponent('%F4%8F%BF%BF') === MAXC, decodeURIComponent('%F4%8F%A0%80') === PUA);
try { encodeURIComponent(MAXC.slice(0, 1)); } catch (e) { console.log('uri-lone', e.name, e.message); }
console.log('wellformed', MAXC.isWellFormed(), PUA.isWellFormed(), MAXC.slice(1).isWellFormed(), hex((MAXC.slice(1) + MAXC.slice(0, 1)).toWellFormed()), joinedMax.isWellFormed());
console.log('pad-repeat', hex('a'.padStart(3, MAXC)), hex(PUA.repeat(2)), PUA.repeat(2).length, hex('x'.padEnd(2, PUA)));
console.log('case', MAXC.toUpperCase() === MAXC, PUA.toLowerCase() === PUA, hex(('\uDBFF' + 'a').toUpperCase()), ('\u{10428}').toUpperCase().codePointAt(0).toString(16), hex('\u{10400}'.toLowerCase()));
console.log('trim', hex((' ' + MAXC + ' ').trim()), hex(('\uDFFF ').trimEnd()));
console.log('compare', MAXC > PUA, PUA > EMO, '\uDBFF' < MAXC, MAXC.localeCompare(PUA) > 0, [MAXC, 'z', PUA, EMO, '\uffff'].sort().map(s => s.codePointAt(0).toString(16)).join(','));
console.log('array-ops', [MAXC, PUA].join('|') === MAXC + '|' + PUA, Array.from(PUA + MAXC).length, Array.prototype.map.call(MAXC, c => hex(c)).join('/'), Object.keys(MAXC).join(), Object.getOwnPropertyDescriptor(PUA, 1).value.charCodeAt(0).toString(16));
console.log('string-object', new String(MAXC).length, hex(new String(PUA)[1]), Object.entries(new String(PUA)).map(([k, v]) => k + '=' + hex(v)).join(';'));
console.log('raw-template', String.raw`${MAXC}`.length, `${PUA}${PUA}`.length, hex(String.raw({ raw: [MAXC.slice(0, 1), MAXC.slice(1)] }, '')));
console.log('normalize', MAXC.normalize() === MAXC, PUA.normalize('NFD') === PUA, hex(('\uDBFF' + 'e\u0301').normalize()));
try { 'x'.normalize('NFX'); } catch (e) { console.log('normalize-bad', e.name, e.message); }
console.log('slow-paths', 'h\u00e9llo w\u00f6rld'.indexOf('w\u00f6'), 'h\u00e9llo'.slice(-3), 'h\u00e9llo'.slice(1, -1), 'h\u00e9llo'.lastIndexOf('l'), '\u00e9\u00e9\u00e9'.indexOf('\u00e9', 1), 'caf\u00e9'.at(-1), '\u00fcber'.substring(1), '\u00fcber'.charAt(0), 'na\u00efve'.split('\u00ef').join('+'), '\u00e9t\u00e9'.replaceAll('\u00e9', 'e'), '\u00e9t\u00e9'.padStart(5, '\u00b7'));
"""


def test_string_astral_and_lone_surrogates(run):
    """CATCHES: UTF-16 semantics broken for astral characters (incl. the top private-use plane U+10F800-U+10FFFF), joined or split surrogate halves and lone surrogates across iteration, slicing, searching, split/replace, JSON, URI coding, case mapping, comparison and well-formedness."""
    _ok(run(["-e", PROG_STRING_ASTRAL_AND_LONE_SURROGATES]), "string_astral_and_lone_surrogates")


PROG_NUMBER_BOOLEAN_BIGINT_FORMATTING = PRELUDE + r"""
const nums = [0, -0, 1, -1, 0.1, 0.5, 1.5, 2.5, 123.456, 1e21, 1e-7, 123456789.123, -1.005, 0.000001, 1.45, 8.345, 255, 1e100, 5e-324, 1.7976931348623157e308, NaN, Infinity, -Infinity];
for (const n of nums) {
  console.log(String(n), '|', n.toFixed(), n.toFixed(2), n.toFixed(5), '|', n.toPrecision(), n.toPrecision(1), n.toPrecision(3), n.toPrecision(21), '|', n.toExponential(), n.toExponential(0), n.toExponential(3));
}
show('toFixed-big', (1.23e20).toFixed(2), (0.5).toFixed(0), (1.5).toFixed(0), (-0.5).toFixed(0), (1000000000000000128).toFixed(0), (0.1).toFixed(20), (1.255).toFixed(2), (10.235).toFixed(2), (100).toFixed(100).length);
tryit('toFixed-101', () => (1).toFixed(101));
tryit('toFixed--1', () => (1).toFixed(-1));
tryit('toPrecision-0', () => (1).toPrecision(0));
tryit('toPrecision-101', () => (1).toPrecision(101));
show('toPrecision-100', (1 / 3).toPrecision(100));
tryit('toExponential-101', () => (1).toExponential(101));
tryit('toExponential-neg', () => (1).toExponential(-1));
tryit('nonfinite-toFixed-range', () => NaN.toFixed(1000));
show('nonfinite-ignores-range', Infinity.toExponential(-5), NaN.toPrecision(0), NaN.toExponential(Infinity));
show('ties', (2.5).toPrecision(1), (25).toPrecision(1), (12.5).toPrecision(2), (0.125).toPrecision(2), (3.5).toPrecision(1), (2.5).toExponential(0), (12.5).toExponential(1), (1.25).toFixed(1), (1.125).toFixed(2));
show('toString-radix', (255).toString(2), (255).toString(36), (-255).toString(16), (0.5).toString(2), (0.1).toString(3), (3.75).toString(8), (1e21).toString(36), (2 ** 53).toString(7), (-0).toString(2), (NaN).toString(16), (-Infinity).toString(36), (123.456).toString(36), (Number.MAX_VALUE).toString(36).length, (5e-324).toString(2).length);
tryit('toString-radix-1', () => (1).toString(1));
tryit('toString-radix-37', () => (1).toString(37));
show('toString-radix-undef', (10).toString(undefined), (10).toString(10.9));
show('shortest', [0.1 + 0.2, 1 / 3, 2 ** 53 + 2, 1e21, 1e-6, 1e-7, 123e-20, 2 ** -1074, -1e-323, 4.35, 0.000123, 1.0000000000000002, 100, 1e20, 12345678901234567890].map(String));
show('Number()', Number(''), Number(' 12 '), Number('0x1F'), Number('0b101'), Number('0o17'), Number('-0x10'), Number('1e3'), Number('.5'), Number('5.'), Number('Infinity'), Number('-Infinity'), Number('infinity'), Number('1_000'), Number(null), Number(undefined), Number([5]), Number([1, 2]), Number(true), Number(12n), Number('\u00a0 7 \n'), Number('0x'), Number('+0x1'), Number('1e1000'));
tryit('Number(symbol)', () => Number(Symbol()));
show('statics', Number.MAX_SAFE_INTEGER, Number.MIN_SAFE_INTEGER, Number.EPSILON, Number.MAX_VALUE, Number.MIN_VALUE, Number.parseFloat === parseFloat, Number.parseInt === parseInt);
show('isInteger', [1, 1.5, -0, Infinity, NaN, '1', 2 ** 53, 1e300].map(Number.isInteger));
show('isSafeInteger', [1, 2 ** 53 - 1, 2 ** 53, -(2 ** 53 - 1), 1.5, '1'].map(Number.isSafeInteger));
show('isFinite/isNaN', Number.isFinite('1'), isFinite('1'), Number.isNaN('x'), isNaN('x'), isNaN(undefined), Number.isNaN(NaN), isFinite(null));
show('parseInt', parseInt('  42px'), parseInt('-0x1A'), parseInt('0x'), parseInt('z', 36), parseInt('10', 2), parseInt('10', 1), parseInt('10', 37), parseInt('10', 0), parseInt(''), parseInt('-0'), parseInt('0.0000005'), parseInt(0.0000005), parseInt('123', 4.9), parseInt('9007199254740993'), parseInt('1e3'), parseInt('\u00a0-12'), parseInt('0b11'), parseInt('ff', 16), parseInt('FF', '16'), parseInt(null, 36), parseInt('12', -1), parseInt('12', 2 ** 32 + 10));
show('parseFloat', parseFloat('3.14abc'), parseFloat('.5'), parseFloat('-.5e-3x'), parseFloat('Infinityx'), parseFloat('-Infinity'), parseFloat('0x10'), parseFloat('1e'), parseFloat('1e+'), parseFloat('e5'), parseFloat(''), parseFloat('  \n 7'), parseFloat('-0'), parseFloat('1.7976931348623159e308'), parseFloat('5e-325'), parseFloat('00012.5000'));
show('Number-proto', Number.prototype.valueOf(), typeof Number.prototype, Object.prototype.toString.call(Number.prototype));
tryit('toFixed-bad-this', () => Number.prototype.toFixed.call('1', 2));
tryit('toString-bad-this', () => Number.prototype.toString.call({}));
tryit('valueOf-bad-this', () => Number.prototype.valueOf.call(true));
show('boxed', new Number(5).toFixed(1), Number.prototype.toString.call(new Number(255), 16), typeof new Number(1), new Number(3) + 1);
show('toLocaleString', (1234.5).toLocaleString === undefined, typeof (1).toLocaleString());
// Boolean
show('Boolean', Boolean(''), Boolean('0'), Boolean([]), Boolean(0n), Boolean(NaN), Boolean(Symbol()), new Boolean(false) ? 'truthy' : 'falsy', true.toString(), Boolean.prototype.valueOf.call(new Boolean(true)), Boolean.prototype.toString());
tryit('Boolean-bad-this', () => Boolean.prototype.toString.call(1));
tryit('Boolean-valueOf-bad', () => Boolean.prototype.valueOf.call('true'));
// BigInt basics
show('BigInt', BigInt(10), BigInt('0x1f'), BigInt(' 12 '), BigInt(true), (255n).toString(16), (-255n).toString(2), BigInt.asIntN(8, 255n), BigInt.asUintN(8, -1n), BigInt.asIntN(64, 2n ** 63n), BigInt.asUintN(0, 5n), (2n ** 64n).toString(36), typeof Object(1n), BigInt.prototype.valueOf.call(Object(3n)));
tryit('BigInt-frac', () => BigInt(1.5));
tryit('BigInt-str', () => BigInt('1.5'));
tryit('BigInt-new', () => new BigInt(1));
tryit('BigInt-sym', () => BigInt(Symbol()));
tryit('BigInt-radix', () => (1n).toString(99));
tryit('BigInt-asIntN-neg', () => BigInt.asIntN(-1, 1n));
tryit('BigInt-toString-bad', () => BigInt.prototype.toString.call(1));
"""


def test_number_boolean_bigint_formatting(run):
    """CATCHES: inexact toFixed/toPrecision/toExponential/toString(radix) output, wrong RangeError messages or check order, wrong Number()/parseInt/parseFloat string parsing, Number statics, and Boolean/BigInt prototype methods and errors."""
    _ok(run(["-e", PROG_NUMBER_BOOLEAN_BIGINT_FORMATTING]), "number_boolean_bigint_formatting")


PROG_NUMBER_BIGINT_SYMBOL_EVAL_EXTRAS = PRELUDE + r"""
show('toFixed-carry', (9.99).toFixed(1), (99.96).toFixed(1), (0.999).toFixed(2), (9.5).toFixed(0), (-9.99).toFixed(1), (999.9999).toFixed(3), (0.0005).toFixed(3), (1e-10).toFixed(5), (123.456).toFixed(10));
tryit('toString-radix-NaN', () => (10).toString(NaN));
show('toString-radix-coerce', (255).toString('16'), (255).toString(16.9), (255).toString({ valueOf() { return 2; } }));
show('Number-noargs', Number(), new Number().valueOf(), Number(undefined), Number.call(null, '5'), typeof Number('1'));
show('Number-ctor-bigint', Number(2n ** 64n), Number(-1n), Number(2n ** 1024n));
show('Number-toLocaleString-basic', typeof (1234.5).toLocaleString(), (0).toLocaleString().length > 0);
show('BigInt-ctor-obj', BigInt({ valueOf() { return 7n; } }), BigInt({ valueOf() { return 8; } }), BigInt(Object(9n)), BigInt('-0x10'.slice(1)), BigInt(''), BigInt('  '), BigInt('0b101'), BigInt('0o17'), BigInt(Number.MAX_SAFE_INTEGER) + 2n);
tryit('BigInt-neg-hex', () => BigInt('-0x10'));
tryit('BigInt-nan', () => BigInt(NaN));
tryit('BigInt-inf', () => BigInt(Infinity));
tryit('BigInt-undefined', () => BigInt(undefined));
tryit('BigInt-null', () => BigInt(null));
show('asIntN', BigInt.asIntN(3, 3n), BigInt.asIntN(3, 4n), BigInt.asIntN(3, -5n), BigInt.asIntN(1, 1n), BigInt.asIntN(0, 99n), BigInt.asIntN(128, 2n ** 127n), BigInt.asIntN(2 ** 27, 5n), BigInt.asIntN('8', '200'));
show('asUintN', BigInt.asUintN(3, 9n), BigInt.asUintN(64, -1n), BigInt.asUintN(1, -1n), BigInt.asUintN(2 ** 27, 5n), BigInt.asUintN(8, true));
tryit('asUintN-huge-neg', () => BigInt.asUintN(2 ** 27, -1n));
tryit('asIntN-bits-too-big', () => BigInt.asIntN(2 ** 53, 1n));
tryit('asUintN-nonbigint', () => BigInt.asUintN(8, 1));
show('BigInt-proto', BigInt.prototype.toString.call(Object(255n), 16), (10n).toLocaleString === undefined, typeof (10n).toLocaleString(), Object.prototype.toString.call(1n), BigInt.prototype[Symbol.toStringTag]);
tryit('BigInt-valueOf-bad', () => BigInt.prototype.valueOf.call(1));
tryit('BigInt-toLocaleString-bad', () => BigInt.prototype.toLocaleString.call('1'));
show('Boolean-boxed', Boolean.prototype.toString.call(new Boolean(true)), Boolean.prototype.valueOf.call(false), new Boolean(new Boolean(false)).valueOf(), Object(true) instanceof Boolean);
tryit('Boolean-toString-obj', () => Boolean.prototype.toString.call({}));
show('Symbol-boxed', Symbol.prototype.toString.call(Object(Symbol('boxed'))), Object(Symbol('d')).description, Symbol.prototype.valueOf.call(Object(Symbol.iterator)) === Symbol.iterator, Object.getOwnPropertyDescriptor(Symbol.prototype, 'description').get.call(Object(Symbol('via getter'))));
tryit('Symbol-valueOf-bad', () => Symbol.prototype.valueOf.call({}));
tryit('Symbol-description-bad', () => Object.getOwnPropertyDescriptor(Symbol.prototype, 'description').get.call({}));
show('Symbol-ctor-coerce', Symbol(1).description, Symbol(null).description, Symbol({ toString() { return 'obj'; } }).description, Symbol.for(1) === Symbol.for('1'));
tryit('Symbol-desc-symbol', () => Symbol(Symbol()));
show('indirect-eval', (0, eval)('var __ie = 40; __ie + 2'), typeof globalThis.__ie, (0, eval)(5), (0, eval)({ a: 1 }).a, (0, eval)(), eval.name, eval.length);
tryit('indirect-eval-syntax', () => (0, eval)('1 +'));
tryit('indirect-eval-throw', () => (0, eval)('throw new RangeError("from eval")'));
show('indirect-eval-scope', (() => { const local = 'local'; try { return (0, eval)('typeof local'); } catch (e) { return e.name; } })(), (() => { const local = 'local'; return eval('local'); })());
show('global-print', typeof globalThis.print);
show('parseInt-more', parseInt('0X1f'), parseInt('+42'), parseInt('-0x'), parseInt('  +0x10  '), parseInt('\u0663'), parseInt('1'.repeat(400)) === Infinity, parseInt('123', 36), parseInt('Infinity'), parseInt('0.5e1'), parseInt('-'), parseInt('+'));
show('parseFloat-more', parseFloat('+.5'), parseFloat('+-1'), parseFloat('1e+5x'), parseFloat('.e1'), parseFloat('-.'), parseFloat('+Infinity'), parseFloat('infinity'), parseFloat('1.e3'), parseFloat('\u00a01'), parseFloat('\u20281'));
show('Number-parse-more', Number('+.5'), Number('-.5e-1'), Number('1e'), Number('0b'), Number('0o8'), Number('0xG'), Number('00012'), Number('1__0'), Number('\u00a012\u00a0'), Number('\u180e12'), Number('+Infinity'), Number('-0'), Number('.'), Number('e5'));
show('math-sumPrecise-more', Math.sumPrecise([-Infinity, 1]), Math.sumPrecise([-Infinity, -Infinity]), Math.sumPrecise([1e308, -1e308, 1e-308]), Math.sumPrecise([0.1, -0.1]), Math.sumPrecise([-0]), Math.sumPrecise([5e-324, 5e-324]), Math.sumPrecise([1, 1e100, 1, -1e100]), Math.sumPrecise([2 ** 1023, 2 ** 1023, -(2 ** 1023)]), Math.sumPrecise([3, NaN, Infinity]));
show('math-more', Math.max(NaN, Infinity), Math.min(-0, 0), Math.max(0, -0), Math.round(-2.5), Math.round(2.4999999999999996), Math.sign(-0), Math.trunc(-0.9), Math.ceil(-0.5), Math.floor(-0), Math.abs(-Infinity), Math.fround(NaN), Math.f16round(NaN), Math.f16round(-65520), Math.f16round(1.0009765625), Math.f16round(1.00048828125), Math.f16round(1.000732421875), Math.clz32(NaN), Math.imul(NaN, 1));
"""


def test_number_bigint_symbol_eval_extras(run):
    """CATCHES: toFixed carry propagation, radix/Number()/parseInt/parseFloat corner cases, BigInt constructor coercion and asIntN/asUintN limits, boxed Boolean/Symbol receivers, Symbol description coercion, indirect eval scoping, the silent global print(), and extra sumPrecise/f16round/round edge values."""
    _ok(run(["-e", PROG_NUMBER_BIGINT_SYMBOL_EVAL_EXTRAS]), "number_bigint_symbol_eval_extras")


PROG_MATH_FUNCTIONS = PRELUDE + r"""
// transcendental results come from the platform libm: print 14 significant digits so the output is portable
const r = v => (typeof v === 'number' && isFinite(v) && v !== 0) ? Number(v.toPrecision(14)) : v;
const exact = new Set(['abs', 'ceil', 'floor', 'fround', 'round', 'sign', 'sqrt', 'trunc', 'clz32', 'f16round']);
const fns = ['abs', 'acos', 'acosh', 'asin', 'asinh', 'atan', 'atanh', 'cbrt', 'ceil', 'cos', 'cosh', 'exp', 'expm1', 'floor', 'fround', 'log', 'log1p', 'log10', 'log2', 'round', 'sign', 'sin', 'sinh', 'sqrt', 'tan', 'tanh', 'trunc', 'clz32', 'f16round'];
const inputs = [0, -0, 0.5, -0.5, 1, -1, 2, 2.5, -2.5, 10, 1e-10, Infinity, -Infinity, NaN];
for (const f of fns) {
  if (typeof Math[f] !== 'function') { console.log(f, 'MISSING'); continue; }
  console.log(f, Math[f].length, inputs.map(x => fmt(exact.has(f) ? Math[f](x) : r(Math[f](x)))).join(' '));
}
show('round-edge', Math.round(0.49999999999999994), Math.round(-0.4), Math.round(-0.5), Math.round(-0.6), Math.round(2 ** 52 + 0.5), Math.round(-(2 ** 53)), Math.round(4503599627370495.5));
show('atan2', ...[Math.sin(Math.PI), Math.cos(Math.PI), Math.atan2(1, 1), Math.atan2(-0, -1), Math.atan2(0, -0), Math.atan2(-0, 0), Math.atan2(Infinity, -Infinity), Math.atan2(1, 0), Math.atan2(NaN, 1)].map(r));
show('pow', Math.pow(2, 10), Math.pow(2, -1), Math.pow(NaN, 0), Math.pow(1, Infinity), Math.pow(-1, -Infinity), Math.pow(-8, 1 / 3), Math.pow(-0, -1), Math.pow(-0, -2), Math.pow(-0, 3), Math.pow(0, 0), r(2 ** 0.5), (-2) ** 3, Math.pow(2, 1024), Math.pow(10, -400), Math.pow('3', [2]), Math.pow.length);
show('max/min', Math.max(), Math.min(), Math.max(1, 3, 2), Math.min(1, -0, 0), Math.max(-0, 0), Math.max(1, NaN, 3), Math.min('2', [1]), Math.max.length);
show('hypot', Math.hypot(), Math.hypot(3, 4), Math.hypot(3, 4, 12), Math.hypot(NaN, Infinity), Math.hypot(-0), Math.hypot(1e200, 1e200), Math.hypot(1, 'x'), Math.hypot.length);
show('imul', Math.imul(3, 4), Math.imul(-5, 12), Math.imul(0xffffffff, 5), Math.imul(2 ** 31, 2), Math.imul(1.9, 2.9));
show('clz32', Math.clz32(1), Math.clz32(0), Math.clz32(-1), Math.clz32(2 ** 32), Math.clz32(0.5), Math.clz32('8'));
show('fround', Math.fround(5.5), Math.fround(5.05), Math.fround(2 ** 128), Math.fround(1e-46), Math.fround(-1e-46), Math.fround(16777217));
show('f16round', Math.f16round(1.337), Math.f16round(65504), Math.f16round(65520), Math.f16round(5.960464477539063e-8), Math.f16round(2.9802322387695312e-8), Math.f16round(-1e-10), Math.f16round(0.1));
show('sumPrecise', Math.sumPrecise([1e20, 0.1, -1e20]), Math.sumPrecise([0.1, 0.2, 0.3]), Math.sumPrecise([]), Math.sumPrecise([-0, -0]), Math.sumPrecise([-0, 0]), Math.sumPrecise([1, Infinity]), Math.sumPrecise([Infinity, -Infinity]), Math.sumPrecise([NaN, 1]), Math.sumPrecise(new Set([1, 2])), Math.sumPrecise([1e308, 1e308, -1e308]), Math.sumPrecise([2 ** 53, 1, 1]));
tryit('sumPrecise-nonnum', () => Math.sumPrecise([1, '2']));
tryit('sumPrecise-noniter', () => Math.sumPrecise(5));
tryit('sumPrecise-overflow', () => Math.sumPrecise([1e308, 1e308]));
show('constants', Math.E, Math.LN10, Math.LN2, Math.LOG10E, Math.LOG2E, Math.PI, Math.SQRT1_2, Math.SQRT2);
show('const-desc', Object.getOwnPropertyDescriptor(Math, 'PI'));
show('tag', String(Math), Math[Symbol.toStringTag], typeof Math.random(), Math.random() >= 0 && Math.random() < 1);
show('coerce', Math.abs('-3'), Math.abs(null), Math.abs([]), Math.abs({}), Math.floor({ valueOf() { return 2.7; } }), Math.sqrt(-1));
tryit('coerce-sym', () => Math.abs(Symbol()));
tryit('coerce-bigint', () => Math.abs(1n));
show('libm-values', ...[Math.exp(1), Math.log(10), Math.cbrt(27), Math.cbrt(-8), Math.sqrt(2), Math.tan(Math.PI / 4), Math.sinh(1), Math.cosh(1), Math.tanh(0.5), Math.asinh(1), Math.acosh(2), Math.atanh(0.5), Math.expm1(1e-10), Math.log1p(1e-10), Math.log10(1000), Math.log2(8), Math.log2(3)].map(r));
"""


def test_math_functions(run):
    """CATCHES: Math functions with wrong special-value handling (-0, NaN, Infinity), wrong round/clz32/imul/fround/f16round/hypot/max/min results, an imprecise Math.sumPrecise, or wrong constants/coercion errors."""
    _ok(run(["-e", PROG_MATH_FUNCTIONS]), "math_functions")


PROG_ARRAY_OBJECT_STRING_CORNER_CASES = PRELUDE + r"""
const r = (label, f) => { try { console.log(label, fmt(f())); } catch (e) { console.log(label, 'THROW', e.name + ': ' + e.message); } };
// Array.prototype corner cases
r('reverse-holes', () => [[, , 3].reverse(), [1, , ,].reverse(), [, 2, , 4, ,].reverse(), Array.prototype.reverse.call({ length: 4, 0: 'a', 3: undefined })]);
r('reverse-frozen-holes', () => Object.freeze([1, , 3]).reverse());
r('reduceRight-noncallable', () => [1].reduceRight('x'));
r('reduceRight-holes', () => [, 1, , 2, ,].reduceRight((acc, v, i) => acc + `${i}:${v};`, ''));
r('includes-fromIndex', () => [[1, 2, 3].includes(1, Infinity), [1, 2, 3].includes(1, -Infinity), [1, 2, 3].includes(3, NaN), [1, 2, 3].includes(1, -2), [1, 2, 3].includes(2, -2), [].includes(undefined), [,].includes(undefined, -1)]);
r('includes-empty-skips-coercion', () => { const log = []; [].includes(1, { valueOf() { log.push('coerced'); return 0; } }); return log; });
r('indexOf-empty-skips-coercion', () => { const log = []; [].indexOf(1, { valueOf() { log.push('coerced'); return 0; } }); [].lastIndexOf(1, { valueOf() { log.push('coerced-last'); return 0; } }); return log; });
r('from-iter-result-nonobj', () => Array.from({ [Symbol.iterator]() { return { next() { return 1; } }; } }));
r('from-arraylike-mapfn-nonctor-huge', () => Array.from.call(null, { length: 2 ** 32 }));
r('from-arraylike-mapfn', () => Array.from({ length: 3, 0: 'a', 2: 'c' }, (v, i) => `${i}${v}`));
r('splice-holes', () => { const a = [1, , 3, , 5]; const removed = a.splice(1, 2, 'x'); return [a, removed]; });
r('splice-grow-holes', () => { const a = [1, , 3]; a.splice(1, 0, 'p', 'q'); return a; });
r('splice-frozen', () => Object.freeze([1, 2, 3]).splice(0, 1));
r('splice-sealed-delete', () => Object.seal([1, 2, 3]).splice(1, 1));
r('splice-nonconfig-tail', () => { const a = [1, 2, 3]; Object.defineProperty(a, 2, { value: 3, configurable: false, writable: true }); return a.splice(0, 1); });
r('shift-holes', () => { const a = [, 2, , 4]; const v = a.shift(); return [v, a]; });
r('unshift-holes', () => { const a = [1, , 3]; a.unshift(0); return a; });
r('copyWithin-frozen', () => Object.freeze([1, 2]).copyWithin(0, 1));
r('fill-frozen', () => Object.freeze([1]).fill(0));
r('concat-spreadable-holes', () => [0].concat({ length: 3, 1: 'one', [Symbol.isConcatSpreadable]: true }));
r('concat-spreadable-proxy-array', () => [0].concat(new Proxy([1, 2], {})));
r('concat-spreadable-false-array', () => { const a = [1]; a[Symbol.isConcatSpreadable] = undefined; return [0].concat(a); });
r('flat-depth-coercion', () => [[[1]], [[2]]].flat('1'));
r('flatMap-thisArg', () => [1].flatMap(function (x) { return [this.v + x]; }, { v: 10 }));
r('sort-accessors-frozen-ok', () => Object.freeze([1, 2]).sort());
r('toSorted-holes-undefined', () => [3, , undefined, 1].toSorted());
r('lastIndexOf-holes', () => [1, , 1].lastIndexOf(undefined));
r('toString-non-callable-join', () => Array.prototype.toString.call({ join: 5 }));
r('toLocaleString-elements', () => [1.5, 'x', null, undefined, { toLocaleString() { return 'custom'; } }].toLocaleString());
r('toLocaleString-noncallable', () => [{ toLocaleString: 1 }].toLocaleString());
r('entries-on-string-object', () => [...Array.prototype.entries.call(new String('hi'))]);
// Object.prototype.toString / toLocaleString odd tags
r('toStringTag-nonstring', () => [Object.prototype.toString.call({ [Symbol.toStringTag]: 42 }), Object.prototype.toString.call(Object.assign([], { [Symbol.toStringTag]: null })), Object.prototype.toString.call(Object.assign(() => {}, { [Symbol.toStringTag]: 'Tagged' }))]);
r('toStringTag-builtins-overridden', () => [Object.prototype.toString.call(new Proxy([], {})), Object.prototype.toString.call(new Proxy(() => {}, {})), Object.prototype.toString.call(Object.create(Date.prototype)), Object.prototype.toString.call(new (class extends Map {})())]);
r('toLocaleString-toString-noncallable', () => Object.prototype.toLocaleString.call({ toString: 1 }));
// String match/search/matchAll/replaceAll receivers & missing patterns
r('match-null-this', () => String.prototype.match.call(null, 'a'));
r('search-null-this', () => String.prototype.search.call(undefined, 'a'));
r('matchAll-null-this', () => String.prototype.matchAll.call(null, 'a'));
r('replaceAll-null-this', () => String.prototype.replaceAll.call(null, 'a', 'b'));
r('match-search-undefined', () => ['abc'.match()[0], 'abc'.match().index, 'abc'.search(), [...'ab'.matchAll()].length]);
r('replaceAll-flags-null', () => 'a'.replaceAll({ [Symbol.match]: true, flags: undefined }, 'b'));
r('matchAll-flags-null', () => 'a'.matchAll({ [Symbol.match]: true, flags: null }));
r('replaceAll-flags-nonglobal-isregexp', () => 'a'.replaceAll({ [Symbol.match]: true, flags: 'i', [Symbol.replace]: () => 'custom' }, 'b'));
r('replaceAll-flags-global-isregexp', () => 'a'.replaceAll({ [Symbol.match]: true, flags: 'g', [Symbol.replace]: (s, rep) => 'custom ' + s + ' ' + rep }, 'b'));
// locale-sensitive case mapping
r('tr-lower', () => ['I', '\u0130', 'I\u0307', 'I\u0323\u0307'].map(s => [...s.toLocaleLowerCase('tr')].map(c => c.codePointAt(0).toString(16)).join(' ')));
r('az-upper', () => ['i', '\u0131', 'iI'].map(s => s.toLocaleUpperCase('az')));
r('lt-lower', () => ['I\u0300', 'J\u0301', '\u012e\u0301', '\u00cc', '\u00cd', '\u0128', 'I', 'Ia'].map(s => [...s.toLocaleLowerCase('lt')].map(c => c.codePointAt(0).toString(16)).join(' ')));
r('lt-upper', () => ['i\u0307', 'j\u0307x', 'i\u0323\u0307', 'a\u0307', '\u012f\u0307'].map(s => [...s.toLocaleUpperCase('lt')].map(c => c.codePointAt(0).toString(16)).join(' ')));
r('locale-list', () => ['I'.toLocaleLowerCase(['tr', 'en']), 'I'.toLocaleLowerCase('TR'), 'I'.toLocaleLowerCase('tr-TR'), 'i'.toLocaleUpperCase([])]);
r('locale-bad', () => 'a'.toLocaleLowerCase('not a tag!'));
// boxed primitive construction with odd new.target
function NT() {}
NT.prototype = null;
r('boxed-newtarget', () => [Object.getPrototypeOf(Reflect.construct(String, ['s'], NT)) === String.prototype, Object.getPrototypeOf(Reflect.construct(Number, [1], NT)) === Number.prototype, Object.getPrototypeOf(Reflect.construct(Boolean, [1], NT)) === Boolean.prototype]);
r('boxed-subclass', () => { class S extends String { shout() { return this.toUpperCase() + '!'; } } const s = new S('hey'); return [s.shout(), s.length, s instanceof String, Object.prototype.toString.call(s), JSON.stringify(s)]; });
r('boxed-newtarget-proto-getter-throws', () => { const nt = function () {}.bind(); Object.defineProperty(nt, 'prototype', { get() { throw new Error('proto getter'); } }); return Reflect.construct(Number, [1], nt); });
"""


def test_array_object_string_corner_cases(run):
    """CATCHES: holes in reverse/splice/shift/unshift/concat/reduceRight, frozen/sealed receivers that must throw, includes/indexOf coercion order, join cycles, toLocaleString/toString fallbacks, odd @@toStringTag values, match/search/matchAll/replaceAll receiver and flags checks, tr/az/lt locale case mapping, and boxed-primitive new.target handling."""
    _ok(run(["-e", PROG_ARRAY_OBJECT_STRING_CORNER_CASES]), "array_object_string_corner_cases")


PROG_NATIVE_FAST_PATHS_HOT_LOOPS = PRELUDE + r"""
// Small functions called many times (so they tier up past the call threshold) over the natively
// specialised built-ins, mixing fast-path receivers with ones that must take the generic algorithm.
const pushOne = (a, v) => a.push(v);
const popOne = a => a.pop();
const codeAt = (s, k) => s.charCodeAt(k);
const charOf = (s, k) => s.charAt(k);
const sliceOf = (s, a, b) => s.slice(a, b);
const root = x => Math.sqrt(x);
const own = (o, k) => Object.hasOwn(o, k);
const applyIt = (f, t, args) => f.apply(t, args);
const rep = (s, a, b) => s.replace(a, b);
const spl = (s, sep) => s.split(sep);
const mat = (s, re) => s.match(re);
const out = [];
const N = 400;
// push/pop on plain arrays
const arr = [];
let acc = 0;
for (let i = 0; i < N; i++) { pushOne(arr, i); pushOne(arr, i * 2); acc += popOne(arr); if (i % 3 === 0) acc += popOne(arr) || 0; }
out.push(['push/pop', acc, arr.length, arr[arr.length - 1]]);
// unusual receivers through the same (now hot) call sites
const empty = [];
let undef = 0;
for (let i = 0; i < 20; i++) if (popOne(empty) === undefined) undef++;
out.push(['pop-empty', undef, empty.length]);
const holey = [1, , 3];
out.push(['pop-holey', [popOne(holey), popOne(holey), popOne(holey), popOne(holey)].map(String), holey.length]);
const frozen = Object.freeze([1, 2]);
let frozenErrors = 0;
for (let i = 0; i < 10; i++) { try { pushOne(frozen, i); } catch (e) { frozenErrors++; } try { popOne(frozen); } catch (e) { frozenErrors++; } }
out.push(['frozen-errors', frozenErrors, frozen.length]);
const fixedLen = [1, 2, 3];
Object.defineProperty(fixedLen, 'length', { writable: false });
let fixedErrors = 0;
for (let i = 0; i < 5; i++) { try { popOne(fixedLen); } catch (e) { fixedErrors++; } try { pushOne(fixedLen, 0); } catch (e) { fixedErrors++; } }
out.push(['nonwritable-length', fixedErrors, fixedLen.length, 2 in fixedLen]);
const like = { length: 0, push: Array.prototype.push, pop: Array.prototype.pop };
for (let i = 0; i < 30; i++) pushOne(like, i);
let likeSum = 0;
for (let i = 0; i < 10; i++) likeSum += popOne(like);
out.push(['arraylike', like.length, likeSum]);
let setterHits = 0, ownZero = 0;
Object.defineProperty(Array.prototype, '0', { set(v) { setterHits += v; }, configurable: true });
for (let i = 0; i < 10; i++) { const w = []; pushOne(w, i); if (Object.hasOwn(w, 0)) ownZero++; }
delete Array.prototype[0];
out.push(['push-through-proto-setter', setterHits, ownZero]);
let ps = 0;
const proxyArr = new Proxy([], { set(t, k, v) { if (k !== 'length') ps++; t[k] = v; return true; } });
for (let i = 0; i < 10; i++) pushOne(proxyArr, i);
out.push(['push-proxy', ps, proxyArr.length, popOne(proxyArr), proxyArr.length]);
const sub = new (class extends Array {})();
pushOne(sub, 'sub'); 
out.push(['push-subclass', sub.length, popOne(sub), sub.length]);
const nonExt = Object.preventExtensions([1]);
out.push(['push-nonextensible', (() => { try { return pushOne(nonExt, 2); } catch (e) { return e.name; } })(), nonExt.length]);
out.push(['pop-nonconfigurable', (() => { const a = [1, 2]; Object.defineProperty(a, 1, { configurable: false }); try { return popOne(a); } catch (e) { return e.name + ': ' + e.message; } })()]);
// strings
const s = 'h\u00e9llo w\u00f6rld \u{1F600}!';
let codes = 0, chars = '', slices = '';
for (let i = 0; i < N; i++) {
  const k = i % (s.length + 2);
  const c = codeAt(s, k);
  codes += Number.isNaN(c) ? -1 : c;
  if (i < s.length + 2) { chars += '[' + charOf(s, k) + ']'; slices += '|' + sliceOf(s, k, k + 2); }
}
out.push(['charCodeAt', codes], ['charAt', chars], ['slice', slices]);
out.push(['string-receivers', codeAt('abc', -1), codeAt('abc', 1.9), charOf('abc', '1'), sliceOf('abcdef', -2), sliceOf('abc', undefined, 2), String(codeAt.call(null, new String('xyz'), 0)), (() => { try { return String.prototype.charCodeAt.call(null, 0); } catch (e) { return e.name; } })()]);
let sq = 0;
for (let i = 0; i < N; i++) sq += root(i);
out.push(['sqrt', sq.toFixed(6), root(-1), root('16'), Object.is(root(-0), -0), root({ valueOf() { return 9; } })]);
const o = { a: 1 };
let ownCount = 0;
for (let i = 0; i < N; i++) { if (own(o, 'a')) ownCount++; if (own(o, 'toString')) ownCount += 100; if (own([1], 0)) ownCount += 0.5; }
out.push(['hasOwn', ownCount, (() => { try { return own('str', 'length'); } catch (e) { return e.name; } })(), own(new Proxy({ z: 1 }, {}), 'z'), own({ [Symbol.iterator]: 1 }, Symbol.iterator)]);
let applied = 0;
function sum3(a, b, c) { return a + b + c; }
for (let i = 0; i < N; i++) applied += applyIt(sum3, null, [i, 1, 2]) + applyIt(Math.max, Math, [i, 3]);
out.push(['apply', applied, applyIt(sum3, null, { length: 3, 0: 'a', 1: 'b', 2: 'c' }), applyIt(function () { return arguments.length; }, null, undefined), (() => { try { return applyIt(sum3, null, 5); } catch (e) { return e.name; } })()]);
let reps = '', splits = 0, matches = 0;
for (let i = 0; i < N; i++) {
  const t = 'a-b-c-' + (i % 10);
  if (i < 3) reps += rep(t, '-', '+') + rep(t, /-/g, '_') + ';';
  splits += spl(t, '-').length;
  matches += (mat(t, /\d/) || [''])[0].length;
}
out.push(['replace', reps], ['split', splits], ['match', matches]);
out.push(['replace-receivers', rep('aaa', 'a', () => 'F'), rep('x$y', '$', '$$'), spl('a,b', { [Symbol.split]: () => 'custom' }), mat('q', { [Symbol.match]: () => 'm' })]);
for (const line of out) console.log(JSON.stringify(line));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_native_fast_paths_hot_loops(run, tier):
    """CATCHES: specialised (JIT/bytecode call-cache) versions of push/pop/charCodeAt/charAt/slice/sqrt/hasOwn/apply/replace/split/match that diverge from the generic algorithm on empty, holey, frozen, non-writable-length, array-like, proxy or prototype-setter receivers."""
    _ok(run([*tier, "-e", PROG_NATIVE_FAST_PATHS_HOT_LOOPS]), "native_fast_paths_hot_loops")


PROG_JSON_STRINGIFY = PRELUDE + r"""
const out = (l, ...v) => console.log(l + ':', v.join(' | '));
out('basic', JSON.stringify({ a: [1, 'two', null, true, undefined, () => 1, Symbol('s')], b: undefined, c: () => 1, [Symbol('k')]: 1, d: NaN, e: -0, f: Infinity, g: new Date(0), h: { toJSON(k) { return 'toJSON:' + k; } } }));
out('top-level', JSON.stringify(undefined), JSON.stringify(() => {}), JSON.stringify(Symbol()), JSON.stringify(null), JSON.stringify('s'), JSON.stringify(-0), JSON.stringify(1e21));
out('boxed', JSON.stringify([new Number(3), new String('str'), new Boolean(false), Object(Symbol('x'))]));
out('escapes', JSON.stringify('q"b\\n\n\r\t\b\f\u0001\u001f\u007f\u2028\u2029'), JSON.stringify('\uD800 \uDC00 \u{1F600}'));
out('keys', JSON.stringify({ 2: 'b', 1: 'a', z: 1, y: 2 }));
out('indent-num', JSON.stringify({ a: [1, { b: 2 }], c: [], d: {} }, null, 2));
out('indent-str', JSON.stringify([1, [2]], null, '--'));
out('indent-long', JSON.stringify({ a: 1 }, null, '0123456789ABC'));
out('indent-clamp', JSON.stringify([1], null, 20) === JSON.stringify([1], null, 10), JSON.stringify([1], null, 0), JSON.stringify([1], null, -5), JSON.stringify([1], null, 3.9));
out('indent-boxed', JSON.stringify([1], null, new Number(1)), JSON.stringify([1], null, new String('>')));
out('replacer-fn', JSON.stringify({ a: 1, b: 'x', c: { d: 2 } }, function (k, v) { return typeof v === 'number' ? v * 10 : v; }));
const trace = [];
JSON.stringify({ a: 1, b: [2, { c: 3 }] }, function (k, v) { trace.push(JSON.stringify(k) + '@' + (Array.isArray(this) ? 'arr' : typeof this) + (k === '' ? ':root=' + (this[''] === v) : '')); return v; });
out('replacer-trace', trace.join(' '));
out('replacer-undefined-drop', JSON.stringify({ a: 1, b: 2 }, (k, v) => k === 'a' ? undefined : v), JSON.stringify([1, 2], (k, v) => k === '0' ? undefined : v));
out('replacer-root', JSON.stringify(5, (k, v) => k === '' ? { wrapped: v } : v), JSON.stringify({ a: 1 }, (k, v) => k === '' ? [v.a, 'r'] : v), JSON.stringify(1, () => undefined));
out('replacer-array', JSON.stringify({ a: 1, b: 2, c: { a: 3, d: 4 }, 1: 'one' }, ['a', 'c', 1, 'a', new String('b')]));
out('replacer-array-on-array', JSON.stringify([{ a: 1, b: 2 }], ['b']));
out('replacer-nonfunc', JSON.stringify({ a: 1 }, 'ignored'), JSON.stringify({ a: 1 }, {}));
out('toJSON-precedence', JSON.stringify({ x: { toJSON() { return { y: 1 }; } } }, (k, v) => k === 'y' ? 'replaced' : v));
out('toJSON-noncallable', JSON.stringify({ toJSON: 5, k: 1 }));
out('date-toJSON', JSON.stringify(new Date(Date.UTC(2020, 0, 2, 3, 4, 5, 6))), JSON.stringify(new Date(NaN)));
try { JSON.stringify(1n); } catch (e) { out('bigint', e.name + ': ' + e.message); }
BigInt.prototype.toJSON = function () { return this.toString() + 'n'; };
out('bigint-toJSON', JSON.stringify({ v: 10n }));
delete BigInt.prototype.toJSON;
const cyc = { name: 'root' }; cyc.self = cyc;
try { JSON.stringify(cyc); } catch (e) { out('cycle-obj', e.name + ': ' + e.message); }
const arrCyc = [1]; arrCyc.push([arrCyc]);
try { JSON.stringify(arrCyc); } catch (e) { out('cycle-arr', e.name + ': ' + e.message); }
const shared = { s: 1 };
out('shared-not-cycle', JSON.stringify({ a: shared, b: shared, c: [shared, shared] }));
out('proxy', JSON.stringify(new Proxy({ a: 1, b: [1] }, {})), JSON.stringify(new Proxy([1, 2], {})));
out('getter', JSON.stringify({ get g() { return 'gotten'; } }));
out('nonenum', JSON.stringify(Object.defineProperty({ v: 1 }, 'hidden', { value: 2 })));
out('array-holes', JSON.stringify([, 1, , undefined]));
out('nested-deep', JSON.stringify([[[[[['deep']]]]]], null, 1).split('\n').length);
out('map/set', JSON.stringify(new Map([[1, 2]])), JSON.stringify(new Set([1])), JSON.stringify(/re/g), JSON.stringify(new Error('e')));
out('typed', JSON.stringify(new Uint8Array([1, 2])));
out('toJSON-throws', (() => { try { JSON.stringify({ toJSON() { throw new RangeError('from toJSON'); } }); } catch (e) { return e.name + ': ' + e.message; } })());
out('len', JSON.stringify.length, JSON.parse.length, String(JSON), Object.keys(JSON).length);
"""


def test_json_stringify(run):
    """CATCHES: JSON.stringify mishandling undefined/functions/symbols, boxed primitives, escapes, indentation clamping, replacer functions/arrays, toJSON, BigInt and cycle TypeErrors, proxies and holes."""
    _ok(run(["-e", PROG_JSON_STRINGIFY]), "json_stringify")


PROG_JSON_PARSE_REVIVER_RAW = PRELUDE + r"""
show('parse-basic', JSON.parse('{"a":[1,2.5e3,-0,true,false,null,"s\\u0041\\n"],"b":{}}'));
show('parse-prims', JSON.parse('1'), JSON.parse(' "x" '), JSON.parse('null'), JSON.parse('-0'), JSON.parse('1E2'), JSON.parse('\t\r\n[]'), JSON.parse(123), JSON.parse(true), JSON.parse(null));
show('parse-dup', JSON.parse('{"a":1,"a":2}'), JSON.parse('{"__proto__":1}'), Object.getPrototypeOf(JSON.parse('{"__proto__":null}')) === Object.prototype);
show('parse-order', Object.keys(JSON.parse('{"b":1,"2":1,"a":1,"1":1}')));
show('parse-bignum', JSON.parse('12345678901234567890'), JSON.parse('1e400'), JSON.parse('-1e-400'), JSON.parse('0.1e1'));
show('parse-escapes', JSON.parse('"\\"\\\\\\/\\b\\f\\n\\r\\t\\u00e9\\ud83d\\ude00"'));
const bad = ['', ' ', '{', '[1,]', '{"a":1,}', '01', '1.', '.5', '+1', '-', 'NaN', 'undefined', "'s'", '"\\x41"', '"\t"', '{a:1}', '[1 2]', 'tru', 'nul', '"abc', '1e', '[', '{"a"}', '{"a":}', '"\\u12"', '1 2', '\u00a0 1', '"\\ud800"x', '{"a":1}}', '[1]]', '0x10', 'Infinity', '-Infinity', '"\u2028"x'];
for (const s of bad) {
  try { const v = JSON.parse(s); console.log('parse-ok', JSON.stringify(s), fmt(v)); }
  catch (e) { console.log('parse-err', JSON.stringify(s), e.name + ': ' + e.message); }
}
show('lone-surrogate-ok', JSON.parse('"\\ud800"').length, JSON.parse('"\u2028"').charCodeAt(0));
// reviver
const rlog = [];
const revived = JSON.parse('{"a":1,"b":[10,20],"c":{"d":"x"}}', function (k, v) { rlog.push(k + ':' + (typeof v === 'object' ? (Array.isArray(v) ? 'arr' : 'obj') : v)); return typeof v === 'number' ? v + 1 : v; });
show('reviver', revived, rlog);
show('reviver-delete', JSON.parse('{"a":1,"b":2,"c":[1,2,3]}', (k, v) => (k === 'b' || k === '1') ? undefined : v));
show('reviver-root', JSON.parse('[1]', (k, v) => k === '' ? 'root replaced' : v));
show('reviver-this', JSON.parse('{"p":{"q":1}}', function (k, v) { if (k === 'q') return Object.keys(this).join(); return v; }));
show('reviver-mutate', JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') { this.b = 'changed-by-a'; } return v; }));
show('reviver-add', JSON.parse('[1,2]', function (k, v) { if (k === '0') { this[5] = 'later'; } return v; }));
show('reviver-noncallable', JSON.parse('{"a":1}', 'nope'));
// source text access
const srcs = [];
JSON.parse('{"n":1.50,"s":"a\\u0062","big":12345678901234567890,"neg":-0,"t":true,"z":null,"o":{"x":1e2},"arr":[1.0]}', function (k, v, ctx) {
  srcs.push(k + '=' + (ctx && 'source' in ctx ? JSON.stringify(ctx.source) : 'nosrc'));
  return v;
});
show('source-text', srcs);
const big = JSON.parse('{"id":12345678901234567890123}', (k, v, { source }) => k === 'id' ? BigInt(source) : v);
show('source-bigint', big.id);
const srcMod = [];
JSON.parse('[1,2]', function (k, v, ctx) { if (k === '0') this[1] = 3; srcMod.push(k + ':' + ('source' in ctx ? ctx.source : 'none')); return v; });
show('source-after-modify', srcMod);
// rawJSON
const raw = JSON.rawJSON('12345678901234567890');
show('rawJSON', JSON.isRawJSON(raw), JSON.isRawJSON({}), JSON.isRawJSON(1), Object.getPrototypeOf(raw), Object.isFrozen(raw), raw.rawJSON, Object.keys(raw));
console.log('rawJSON-stringify:', JSON.stringify({ a: raw, b: [JSON.rawJSON('"str"'), JSON.rawJSON('null'), JSON.rawJSON('true'), JSON.rawJSON('-1e3')] }));
for (const s of ['{}', '[]', '', ' 1', '1 ', 'undefined', '"a', '\t1', '1n']) {
  try { JSON.rawJSON(s); console.log('rawJSON-ok', JSON.stringify(s)); } catch (e) { console.log('rawJSON-err', JSON.stringify(s), e.name + ': ' + e.message); }
}
show('rawJSON-coerce', JSON.rawJSON(42).rawJSON, JSON.rawJSON(true).rawJSON);
tryit('rawJSON-symbol', () => JSON.rawJSON(Symbol()));
show('parse-coerce', JSON.parse({ toString() { return '[7]'; } }), JSON.parse([1]));
tryit('parse-symbol', () => JSON.parse(Symbol()));
show('parse-deepish', JSON.stringify(JSON.parse('['.repeat(200) + ']'.repeat(200))).length);
show('roundtrip', JSON.parse(JSON.stringify({ s: '\u0000\u{1F600}\uD800', n: [1e-7, 5e-324, 2 ** 53] })));
"""


def test_json_parse_reviver_raw(run):
    """CATCHES: JSON.parse accepting invalid JSON or reporting wrong SyntaxError messages, reviver walk order/deletion/this binding, the source-text access context argument, and JSON.rawJSON/isRawJSON validation and serialization."""
    _ok(run(["-e", PROG_JSON_PARSE_REVIVER_RAW]), "json_parse_reviver_raw")


PROG_JSON_REVIVER_PARSER_AND_REPLACER_EDGES = PRELUDE + r"""
const out = (l, ...v) => console.log(l + ':', v.map(x => typeof x === 'string' && x.isWellFormed() ? x : fmt(x)).join(' | '));
const id = (k, v) => v;
// The reviver path uses a separate (source-recording) parser: its errors and edge cases.
for (const s of ['{}', '[]', '{"a":[]}', '[{}]', '{"a":1 "b":2}', '{"a":1,}', '{,}', '{"a" 1}', '{1:2}', '[1 2]', '[1,]', '[,1]', '["a"', '{"a":1', '  [1] x', '"\\ud83d\\ude00"', '"\\uD800\\u0041"', '-0', '1e-2', '[true,false,null]', '{"__proto__":{"x":1}}', '{"a":{"b":{"c":[1,{"d":2}]}}}']) {
  try { out('revived', JSON.stringify(s), JSON.parse(s, id)); } catch (e) { out('revive-err', JSON.stringify(s), e.name + ': ' + e.message); }
}
out('revive-proto-key', Object.getPrototypeOf(JSON.parse('{"__proto__":{"x":1}}', id)) === Object.prototype, Object.keys(JSON.parse('{"__proto__":1}', id)));
// A reviver that grafts objects into not-yet-visited positions: proxies, arrays, typed arrays.
const trapLog = [];
const graftProxy = new Proxy({ p1: 1, p2: 2 }, {
  ownKeys(t) { trapLog.push('ownKeys'); return Reflect.ownKeys(t); },
  getOwnPropertyDescriptor(t, k) { trapLog.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); },
  deleteProperty(t, k) { trapLog.push('delete ' + k); return Reflect.deleteProperty(t, k); },
  defineProperty(t, k, d) { trapLog.push('define ' + k); return Reflect.defineProperty(t, k, d); },
});
const grafted = JSON.parse('{"first":0,"second":0,"third":0}', function (k, v) {
  if (k === 'first') { this.second = graftProxy; this.third = new Uint8Array([7, 8]); }
  if (k === 'p1') return undefined;
  if (k === 'p2') return 'P2';
  if (k === '0' && this instanceof Uint8Array) return v + 1;
  return v;
});
out('graft-result', Object.keys(grafted), grafted.second === graftProxy, JSON.stringify(Object.assign({}, graftProxy)), Array.from(grafted.third));
out('graft-proxy-traps', trapLog);
let didGraft = false;
const arrGraft = JSON.parse('[0,0]', function (k, v) { if (k === '0' && !didGraft) { didGraft = true; this[1] = new Proxy([5, 6], {}); } if (k === '1' && typeof v === 'number') return v * 10; return v; });
out('graft-array-proxy', Array.isArray(arrGraft[1]), JSON.stringify(arrGraft));
const frozenGraft = JSON.parse('{"a":0,"b":0}', function (k, v) { if (k === 'a') this.b = Object.freeze({ keep: 1, drop: 2 }); if (k === 'keep') return 'changed'; if (k === 'drop') return undefined; return v; });
out('graft-frozen', frozenGraft.b);
// Replacer variants.
out('replacer-proxy-array', JSON.stringify({ a: 1, b: 2, c: 3 }, new Proxy(['c', 'a'], {})));
out('replacer-array-mixed', JSON.stringify({ 1: 'one', a: 'A', true: 'T', null: 'N', b: 'B' }, [1, new Number(1), 'a', new String('b'), true, null, {}, ['a'], Symbol.iterator]));
out('replacer-array-dupes-order', JSON.stringify({ x: 1, y: 2, z: 3 }, ['z', 'x', 'z', 'y']));
out('replacer-fn-holder-root', JSON.stringify('v', function (k, v) { return k === '' ? Object.keys(this).join('|') + '=' + JSON.stringify(this['']) : v; }));
out('replacer-fn-proxy-value', JSON.stringify({ p: new Proxy({ z: 1, y: 2 }, {}) }, (k, v) => v));
out('stringify-boxed-bigint', (() => { try { return JSON.stringify(Object(1n)); } catch (e) { return e.name + ': ' + e.message; } })());
out('stringify-boxed-symbol', JSON.stringify(Object(Symbol('s'))), JSON.stringify([Object(Symbol('s'))]));
out('stringify-custom-boxed-toString', JSON.stringify(Object.assign(new String('real'), { toString() { return 'overridden'; } })), JSON.stringify(Object.assign(new Number(1), { valueOf() { return 2; } })));
out('stringify-space-object', JSON.stringify([1], null, { length: 2 }), JSON.stringify([1], null, true), JSON.stringify([1], null, new String('abcdefghijklmn')).split('\n')[1]);
out('stringify-toJSON-key', JSON.stringify([{ toJSON(k) { return 'idx' + k; } }]), JSON.stringify({ deep: { toJSON(k) { return k; } } }));
out('stringify-toJSON-inherited', JSON.stringify(Object.create({ toJSON() { return 'from proto'; } })));
out('stringify-getter-throws', (() => { try { return JSON.stringify({ get bad() { throw new SyntaxError('getter threw'); } }); } catch (e) { return e.name + ': ' + e.message; } })());
out('stringify-array-like-not-array', JSON.stringify({ length: 2, 0: 'a' }), JSON.stringify(Object.create(Array.prototype)), JSON.stringify(new Proxy([], {})), JSON.stringify(Array.prototype));
out('stringify-revoked', (() => { const r = Proxy.revocable({}, {}); r.revoke(); try { return JSON.stringify(r.proxy); } catch (e) { return e.name + ': ' + e.message; } })());
out('stringify-revoked-replacer', (() => { const r = Proxy.revocable([], {}); r.revoke(); try { return JSON.stringify({}, r.proxy); } catch (e) { return e.name + ': ' + e.message; } })());
out('stringify-sparse-indent', JSON.stringify([, , 1], null, 1));
out('stringify-empty-nested-indent', JSON.stringify({ a: {}, b: [], c: [[]], d: [{}] }, null, '\t'));
out('rawJSON-in-array-indent', JSON.stringify([JSON.rawJSON('1e1000')], null, 2));
out('rawJSON-props', Object.getOwnPropertyDescriptor(JSON.rawJSON('1'), 'rawJSON'), Object.isExtensible(JSON.rawJSON('1')));
out('rawJSON-as-replacer-result', JSON.stringify({ n: 1 }, (k, v) => typeof v === 'number' ? JSON.rawJSON('0.10') : v));
out('isRawJSON-lookalike', JSON.isRawJSON(Object.freeze(Object.setPrototypeOf({ rawJSON: '1' }, null))));
out('parse-reviver-context-arrays', (() => { const ctx = []; JSON.parse('[[1,"x"],{"k":[true]}]', (k, v, c) => { ctx.push(k + ':' + ('source' in c ? c.source : '-')); return v; }); return ctx; })());
out('parse-reviver-replaced-primitive', (() => { const ctx = []; JSON.parse('{"a":1,"b":2}', function (k, v, c) { if (k === 'a') this.b = 3; ctx.push(k + ':' + ('source' in c ? c.source : '-')); return v; }); return ctx; })());
out('parse-reviver-same-value-keeps-source', (() => { const ctx = []; JSON.parse('{"a":1,"b":2}', function (k, v, c) { if (k === 'a') this.b = 2; ctx.push(k + ':' + ('source' in c ? c.source : '-')); return v; }); return ctx; })());
"""


def test_json_reviver_parser_and_replacer_edges(run):
    """CATCHES: the reviver-mode JSON parser accepting bad input or using different SyntaxError messages, revivers grafting proxies/typed arrays/frozen objects into unvisited positions, source-text context after modification, proxy/boxed replacer arrays, and stringify of boxed/revoked/array-like values."""
    _ok(run(["-e", PROG_JSON_REVIVER_PARSER_AND_REPLACER_EDGES]), "json_reviver_parser_and_replacer_edges")


PROG_GLOBALS_URI_SYMBOLS = PRELUDE + r"""
show('encodeURIComponent', encodeURIComponent("a b&c=d/e?f#g;h,i+j:k@l$m!n'o(p)q*r~s_t-u.v"), encodeURIComponent('\u00e9\u{1F600}\u0000'), encodeURIComponent(123), encodeURIComponent());
show('encodeURI', encodeURI("http://x.com/a b?c=d&e#f;g,h+i:j@k$l!m'n(o)p*q~r[s]"), encodeURI('\u20ac%'));
tryit('encodeURI-lone-high', () => encodeURI('\uD800'));
tryit('encodeURIComponent-lone-low', () => encodeURIComponent('a\uDC00'));
tryit('encode-high-then-ascii', () => encodeURIComponent('\uD800a'));
show('decodeURIComponent', decodeURIComponent('a%20b%26c%2F%3F%23'), decodeURIComponent('%C3%A9%F0%9F%98%80'), decodeURIComponent('%e2%82%ac'), decodeURIComponent('plain'));
show('decodeURI', decodeURI('a%20b%26c%2F%3F%23%3B%2C%2B%3A%40%24%3D'), decodeURI('%C3%A9'), decodeURI('%25'));
for (const s of ['%', '%2', '%zz', '%C3', '%C3%28', '%FF', '%80', '%ED%A0%80', '%F4%90%80%80', '%C0%AF', '%E0%80%AF', '%F0%80%80%80', '%c3%a', 'ok%41']) {
  try { console.log('decode', JSON.stringify(s), JSON.stringify(decodeURIComponent(s))); } catch (e) { console.log('decode', JSON.stringify(s), e.name + ': ' + e.message); }
}
tryit('decodeURI-bad', () => decodeURI('%E0%A4%A'));
show('escape', escape('a b+c/@*_-.\u00e9\u0100\u{1F600}'), unescape('%u0041%41%zz%u12%'), unescape('%E9'), unescape(escape('\u00ff\uffff')));
show('isNaN/isFinite', isNaN('abc'), isNaN(''), isFinite('1e3'), isFinite(Infinity), isNaN({}), isFinite([]));
tryit('isNaN-symbol', () => isNaN(Symbol()));
tryit('isNaN-bigint', () => isNaN(1n));
// global property descriptors
for (const k of ['undefined', 'NaN', 'Infinity', 'globalThis', 'Object', 'Array', 'JSON', 'Math', 'parseInt', 'Reflect', 'Symbol', 'eval']) {
  const d = Object.getOwnPropertyDescriptor(globalThis, k);
  console.log('gdesc', k, d ? [d.writable, d.enumerable, d.configurable, typeof d.value].join(',') : 'missing');
}
show('globalThis', typeof globalThis, globalThis.globalThis === globalThis, Object.prototype.toString.call(globalThis).startsWith('[object '), 'Array' in globalThis);
undefined = 5; NaN = 1; Infinity = 0;
show('global-readonly-sloppy', undefined, NaN, Infinity);
tryit('global-readonly-strict', () => { 'use strict'; undefined = 5; });
tryit('global-readonly-strict-NaN', () => { 'use strict'; NaN = 5; });
show('fn-names', [parseInt, parseFloat, isNaN, isFinite, encodeURI, decodeURI, encodeURIComponent, decodeURIComponent, escape, unescape].map(f => f.name + '/' + f.length));
// Symbols
const s = Symbol('desc');
show('symbol', s.toString(), s.description, Symbol().description, Symbol('').description, typeof s, Object(s) instanceof Symbol, Object(s).valueOf() === s, Symbol.prototype[Symbol.toStringTag]);
show('symbol-for', Symbol.for('app') === Symbol.for('app'), Symbol.keyFor(Symbol.for('app')), Symbol.keyFor(s), Symbol.for().toString(), Symbol.keyFor(Symbol.iterator));
tryit('symbol-new', () => new Symbol());
tryit('keyFor-nonsym', () => Symbol.keyFor('x'));
tryit('symbol-tonum', () => +s);
tryit('symbol-toString-bad', () => Symbol.prototype.toString.call('x'));
tryit('symbol-desc-bad', () => Object.getOwnPropertyDescriptor(Symbol.prototype, 'description').get.call(1));
show('well-known', ['asyncIterator', 'hasInstance', 'isConcatSpreadable', 'iterator', 'match', 'matchAll', 'replace', 'search', 'species', 'split', 'toPrimitive', 'toStringTag', 'unscopables', 'dispose', 'asyncDispose'].map(k => typeof Symbol[k] === 'symbol' ? Symbol[k].description : 'missing:' + k));
show('wk-desc', Object.getOwnPropertyDescriptor(Symbol, 'iterator'));
show('toPrimitive', Symbol.prototype[Symbol.toPrimitive].call(s) === s, Object.getOwnPropertyDescriptor(Symbol.prototype, Symbol.toPrimitive).writable);
const tp = { [Symbol.toPrimitive](hint) { return hint === 'number' ? 42 : hint === 'string' ? 'str' : 'default'; } };
show('toPrimitive-hints', +tp, `${tp}`, tp + '', tp * 2, [tp] + '', String(tp), tp == 'default');
tryit('toPrimitive-returns-obj', () => +{ [Symbol.toPrimitive]() { return {}; } });
tryit('toPrimitive-noncallable', () => +{ [Symbol.toPrimitive]: 1 });
tryit('ordinary-toPrimitive-fail', () => '' + { toString() { return {}; }, valueOf() { return {}; } });
show('symbol-keys', Object.keys({ [s]: 1 }), JSON.stringify({ [s]: 1 }), Object.getOwnPropertySymbols({ [s]: 1, [Symbol.iterator]: 2 }).map(String));
show('unscopables', Object.keys(Array.prototype[Symbol.unscopables]).sort(), Object.getPrototypeOf(Array.prototype[Symbol.unscopables]));
"""


def test_globals_uri_symbols(run):
    """CATCHES: URI encode/decode functions accepting malformed input or encoding the wrong reserved sets, escape/unescape, global value property descriptors, and Symbol registry/description/toPrimitive/well-known symbol behaviour."""
    _ok(run(["-e", PROG_GLOBALS_URI_SYMBOLS]), "globals_uri_symbols")


@pytest.mark.parametrize("code, expected", [
    ("JSON.parse('{')", b"Uncaught SyntaxError: Expected string key in JSON object\n"),
    ("[].reduce((a, b) => a)", b"Uncaught TypeError: Reduce of empty array with no initial value\n"),
    ("new Array(-1)", b"Uncaught RangeError: Invalid array length\n"),
    ("(1).toFixed(101)", b"Uncaught RangeError: toFixed() digits argument must be between 0 and 100\n"),
    ("decodeURIComponent('%')", b"Uncaught URIError: URI malformed\n"),
    ("Symbol() + ''", b"Uncaught TypeError: Cannot convert a Symbol value to a string\n"),
    ("Object.defineProperty(Object.freeze({}), 'x', { value: 1 })", b"Uncaught TypeError: Cannot redefine property\n"),
    ("BigInt(1.5)", b"Uncaught RangeError: The number cannot be converted to a BigInt\n"),
    ("new Date(NaN).toISOString()", b"Uncaught RangeError: Invalid time value\n"),
    ("JSON.stringify({ toJSON() { return 1n } })", b"Uncaught TypeError: Do not know how to serialize a BigInt\n"),
    ("String.fromCodePoint(-1)", b"Uncaught RangeError: Invalid code point\n"),
    ("'x'.repeat(-1)", b"Uncaught RangeError: invalid count value\n"),
], ids=["json-parse", "reduce-empty", "array-length", "toFixed", "uri", "symbol-concat", "redefine",
        "bigint-frac", "iso-invalid", "json-bigint", "codepoint", "repeat"])
def test_uncaught_builtin_errors(run, code, expected):
    """CATCHES: built-ins that throw the wrong error type or wording (as reported by the uncaught-error printer), or that do not throw at all and exit 0."""
    r = run(["-e", "console.log('start'); " + code + "; console.log('unreachable')"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"start\n", expected)
