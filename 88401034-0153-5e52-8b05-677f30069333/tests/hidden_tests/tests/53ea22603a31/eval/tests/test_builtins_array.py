"""Array built-ins: mutators and ES2023 copying methods, sort semantics, holes/sparse arrays and
length, generic (array-like) receivers, species, concat spreading, Array.from/of/fromAsync and
array iterators."""

import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)

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


@pytest.mark.parametrize("cli", [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp")])
def test_array_mutators(run, workdir, cli):
    """CATCHES: wrong return values or argument clamping in push/pop/shift/unshift/splice/
    reverse/fill/copyWithin (negative and out-of-range indices, missing/undefined deleteCount,
    holes moved by copyWithin), callbacks of forEach/map/filter/reduce visiting holes or using the
    wrong arguments/thisArg, exact 'is not callable' and empty-reduce messages, and JIT fast paths
    for push/pop/indexOf in hot loops (frozen arrays, holes, non-writable length) diverging from
    the interpreter tier."""
    check(run, workdir, "array_mutators", r'''
show('push/pop', () => { const a = [1]; return [a.push(2, 3), a.pop(), a, [].pop(), [].push()]; });
show('shift/unshift', () => { const b = [1, 2]; return [b.unshift(0, 0.5), b.shift(), b, [].shift(), [5].unshift()]; });
show('splice', () => { const b = [1, 2, 3, 4, 5]; const r1 = b.splice(1, 2); const r2 = b.splice(-1, 1, 'a', 'b'); const r3 = b.splice(1); return [r1, r2, r3, b]; });
show('splice no args', () => { const b = [1, 2]; return [b.splice(), b]; });
show('splice undefined start', () => { const b = [1, 2]; return [b.splice(undefined), b]; });
show('splice undefined count', () => { const b = [1, 2, 3]; return [b.splice(1, undefined, 'x'), b]; });
show('splice neg count', () => { const b = [1, 2, 3]; return [b.splice(1, -5, 'y'), b]; });
show('splice huge start', () => { const b = [1, 2]; return [b.splice(99, 1, 'z'), b]; });
show('reverse', () => [[1, 2, 3].reverse(), [1, , 3, , ].reverse(), [].reverse()]);
show('fill', () => [new Array(4).fill(0), [1, 2, 3, 4].fill(9, 1, -1), [1, 2, 3].fill(7, -10), [1, 2].fill(0, 5), [1, 2, 3].fill(8, NaN, 2)]);
show('copyWithin', () => [[1, 2, 3, 4, 5].copyWithin(0, 3), [1, 2, 3, 4, 5].copyWithin(-2, 0, 2), [1, 2, 3, 4, 5].copyWithin(1, 0), [1, , 3].copyWithin(0, 1), [1, 2, 3].copyWithin(0, 1, -5)]);
show('forEach holes', () => { const r = []; [1, , 3].forEach(function (v, i, arr) { r.push(i + ':' + v + ':' + (arr.length) + ':' + this.t); }, {t: 'T'}); return r; });
show('map holes', () => [1, , 3].map(x => x * 2));
show('filter holes', () => [1, , 3, undefined, 0].filter(() => true));
show('reduce', () => [[1, 2, 3].reduce((a, b) => a + b), [1, 2, 3].reduceRight((a, b) => a + b, ''), [, 5].reduce((a, b) => a + b), [1, 2, 3].reduce((acc, v, i, arr) => acc + i + arr.length, 0), [[1], [2]].reduceRight((a, b) => a.concat(b))]);
show('reduce empty', () => [].reduce((a, b) => a));
show('reduce holes only', () => [, , ].reduceRight((a, b) => a));
show('every/some', () => [[].every(x => false), [].some(x => true), [1, 2].every(x => x > 0), [1, 2].some(x => x > 1), [, 1].every(x => x === 1)]);
show('forEach no callback', () => [1].forEach());
show('map bad callback', () => [1].map('x'));
show('filter bad callback', () => [1].filter({}));
show('reduce bad callback', () => [1].reduce(null, 0));
show('find bad callback', () => [1].find());
show('reduceRight bad callback', () => [1].reduceRight(1));
show('some bad callback', () => [1].some());
show('every bad callback', () => [1].every(null));
show('mutation during forEach', () => { const a = [1, 2, 3]; const seen = []; a.forEach((v, i) => { seen.push(v); if (i === 0) { a.push(99); a[2] = 'changed'; } }); return [seen, a.length]; });
show('delete during map', () => { const a = [1, 2, 3]; return a.map((v, i) => { if (i === 0) delete a[1]; return v; }); });
function hot(arr, n) {
  const out = [];
  for (let i = 0; i < n; i++) { arr.push(i, i * 2); out.push(arr.pop()); if (i % 3 === 0) out.push(arr.pop()); }
  let found = 0;
  for (let i = 0; i < n; i++) found += arr.indexOf(i) + arr.lastIndexOf(i) + (arr.includes(i * 2) ? 1 : 0);
  return [arr.length, out.length, out.slice(0, 6), found];
}
show('hot dense', () => hot([], 300));
show('hot holes', () => { const a = [, , 5]; return hot(a, 50); });
show('hot non-writable length', () => { const a = [1]; Object.defineProperty(a, 'length', {writable: false}); return hot(a, 5); });
show('hot frozen pop', () => { const a = Object.freeze([1, 2]); let r; for (let i = 0; i < 3; i++) { try { a.pop(); } catch (e) { r = e.name + ': ' + e.message; } } return [r, a.length]; });
show('hot pop empty', () => { const a = []; let u = 0; for (let i = 0; i < 100; i++) if (a.pop() === undefined) u++; return [u, a.length]; });
show('hot array-like push', () => { const o = {length: 0}; for (let i = 0; i < 100; i++) Array.prototype.push.call(o, i); return [o.length, o[99]]; });
''', cli=cli)


def test_array_es2023_copying_methods(run, workdir):
    """CATCHES: toSorted/toSpliced/toReversed/with mutating the receiver, keeping holes instead of
    filling with undefined, using species (must always produce plain Arrays), wrong index
    coercion/RangeErrors in with(), comparator validation messages, and findLast/findLastIndex
    iterating in the wrong direction."""
    check(run, workdir, "array_es2023_copying_methods", r'''
const a = [5, 1, 4, 2, 3];
show('toSorted', () => [a.toSorted(), a]);
show('toSorted cmp', () => a.toSorted((x, y) => y - x));
show('toSorted bad cmp', () => a.toSorted(1));
show('toSorted holes', () => [3, , 1].toSorted());
show('toSorted array-like', () => Array.prototype.toSorted.call({length: 2, 0: 'b', 1: 'a'}));
show('toSpliced', () => [a.toSpliced(1, 2, 'x', 'y', 'z'), a.toSpliced(), a.toSpliced(-1), a.toSpliced(2), a.toSpliced(0, 0, 'front'), a]);
show('toSpliced array-like', () => Array.prototype.toSpliced.call({length: 3, 0: 'a', 1: 'b', 2: 'c'}, 1, 1));
show('toSpliced holes', () => [1, , 3].toSpliced(0, 0));
show('toSpliced too long', () => Array.prototype.toSpliced.call({length: 2 ** 53 - 1}, 0, 0, 1));
show('toReversed', () => [a.toReversed(), [1, , 3].toReversed(), a]);
show('toReversed huge', () => Array.prototype.toReversed.call({length: 2 ** 32}));
show('with', () => [a.with(0, 9), a.with(-1, 9), a.with('1', 'x'), a.with(1.9, 'f'), [1, , 3].with(0, 0), a]);
show('with out of range', () => a.with(5, 1));
show('with negative out of range', () => a.with(-6, 1));
show('with array-like', () => Array.prototype.with.call({length: 2, 0: 'a', 1: 'b'}, 1, 'z'));
show('species ignored', () => { class MyA extends Array {} const m = MyA.from([3, 1, 2]); return [m.toSorted().constructor.name, m.toReversed().constructor.name, m.with(0, 1).constructor.name, m.toSpliced(0, 1).constructor.name]; });
show('findLast', () => [a.findLast(x => x > 3), a.findLastIndex(x => x > 3), a.findLast(x => x > 10), a.findLastIndex(x => x > 10)]);
show('findLast order', () => { const seen = []; [1, 2, 3].findLast((v, i) => { seen.push(i); return false; }); return seen; });
show('find holes', () => [[, 1].find(x => x === undefined), [, 1].findIndex(x => x === undefined), [1, , ].findLastIndex(x => x === undefined)]);
show('findLast bad', () => [].findLast(1));
show('at', () => [a.at(0), a.at(-1), a.at(5), a.at(-6), a.at(1.7), a.at('2'), a.at(NaN), a.at(-0.5)]);
show('at array-like', () => Array.prototype.at.call({length: 1.9, 0: 'z'}, 0));
show('copying methods are unscopable', () => ['toSorted', 'toSpliced', 'toReversed', 'with'].map(k => Array.prototype[Symbol.unscopables][k]));
''')


def test_array_sort_semantics(run, workdir):
    """CATCHES: an unstable sort, numeric instead of string default ordering, undefined/holes not
    moved to the end (holes after undefineds, length kept), comparator results coerced wrongly,
    the array being modified when the comparator throws, and the exact comparator TypeErrors.
    Pinned quirk: the reference's default comparator orders strings by code point rather than by
    UTF-16 code units, so U+FF61 sorts before U+1F600."""
    check(run, workdir, "array_sort_semantics", r'''
show('default strings', () => [10, 9, 1, 100, -1, 'b', 'B', 'a', 1e21, 1e-7].sort());
show('mixed types', () => [3, 'b', undefined, null, 1, 'a', true, NaN, [], {}].sort());
show('undefined and holes', () => { const b = [3, undefined, , 1, , 2]; b.sort(); return [b, b.length, 4 in b, 3 in b]; });
show('stable', () => [{k: 1, v: 'a'}, {k: 0, v: 'b'}, {k: 1, v: 'c'}, {k: 0, v: 'd'}, {k: 1, v: 'e'}].sort((x, y) => x.k - y.k).map(o => o.v).join(''));
show('stable large', () => { const b = []; for (let i = 0; i < 300; i++) b.push({k: (i * 7) % 5, i}); b.sort((x, y) => x.k - y.k); return b.every((v, j) => j === 0 || b[j - 1].k < v.k || (b[j - 1].k === v.k && b[j - 1].i < v.i)); });
show('cmp returns string', () => [3, 1, 2].sort((x, y) => String(x - y)));
show('cmp returns boolean', () => [3, 1, 2].sort((x, y) => x > y));
show('cmp NaN', () => [3, 1, 2].sort(() => NaN));
show('cmp throws', () => { const b = [3, 2, 1]; try { b.sort(() => { throw new Error('boom'); }); } catch (e) { return [e.message, b]; } });
show('cmp sees undefined?', () => { const seen = []; [2, undefined, 1].sort((x, y) => { seen.push(typeof x, typeof y); return x - y; }); return seen.includes('undefined'); });
show('cmp mutates array', () => { const b = [3, 2, 1]; b.sort((x, y) => { b.length = 0; return x - y; }); return b; });
show('-0 and 0', () => [0, -0, 0, -0].sort().map(x => Object.is(x, -0)));
show('array-like', () => Array.prototype.sort.call({length: 3, 0: 'c', 1: 'a', 2: 'b'}));
show('array-like with holes', () => Array.prototype.sort.call({length: 4, 0: 'b', 3: 'a', 5: 'ignored'}));
show('null comparator', () => [].sort(null));
show('object comparator', () => [2, 1].sort({}));
show('valueOf called', () => { let calls = 0; const mk = n => ({toString() { calls++; return String(n); }}); [mk(2), mk(1), mk(3)].sort(); return calls > 0; });
show('returns same array', () => { const b = [2, 1]; return b.sort() === b; });
show('numeric compare', () => [100, 25, -1, 0, 3.5].sort((x, y) => x - y));
show('localeCompare', () => ['b', 'a', 'C', 'á'].sort((x, y) => x.localeCompare(y)));
show('default order of astral vs BMP strings', () => ['😀', '｡', 'z', 'Z', 'é'].sort().map(s => s.codePointAt(0).toString(16)));
''')


def test_array_holes_length_and_limits(run, workdir):
    """CATCHES: wrong sparse-array behaviour (holes vs undefined in spread/keys/includes/indexOf/
    join/flat), length truncation deleting elements, invalid lengths not raising
    RangeError('Invalid array length'), array-index boundaries (2**32-2), and the reference's
    length-limit errors for push/concat/splice/unshift on huge array-likes."""
    check(run, workdir, "array_holes_length_and_limits", r'''
show('holes spread', () => [...[1, , 3]]);
show('holes keys/entries', () => [[...[1, , 3].keys()], [...[, 'b'].entries()]]);
show('holes includes vs indexOf', () => [[, 1].includes(undefined), [, 1].indexOf(undefined), [NaN].includes(NaN), [NaN].indexOf(NaN), [-0].includes(0), 1 / [-0].indexOf(0)]);
show('holes join', () => [[1, , 3].join('-'), [null, undefined, 1].join(), new Array(3).join('ab'), [[1, [2]], [3]].join(';')]);
show('holes flat', () => [[1, , [2, , 3]].flat(), [[1, [2, [3, [4]]]].flat(Infinity)], [1, [2]].flat(0), [[1]].flat(-1), [[1, [2]]].flat('1')]);
show('flatMap', () => [1, 2, 3].flatMap(x => x === 2 ? [] : [x, [x * 10]]));
show('flatMap bad', () => [1].flatMap(1));
show('length truncate', () => { const b = [1, 2, 3, 4]; b.length = 2; const after = [...b]; b.length = 4; return [after, b, b.length]; });
show('length string', () => { const b = [1, 2, 3]; b.length = '1'; return b; });
show('length -1', () => { const b = []; b.length = -1; });
show('length 1.5', () => { const b = []; b.length = 1.5; });
show('length 2**32', () => { const b = []; b.length = 2 ** 32; });
show('length max', () => { const b = []; b.length = 4294967295; return [b.length, b.at(-1)]; });
show('index boundaries', () => { const b = []; b[4294967295] = 'notidx'; b[4294967294] = 'lastidx'; return [b.length, Object.keys(b)]; });
show('negative index property', () => { const b = [1]; b[-1] = 'neg'; return [b.length, Object.keys(b), b.at(-1)]; });
show('Array ctor', () => [Array(3).length, Array(3, 4), Array('3'), new Array(0).length, Array.of(7), Array.of(), Array.of.call(Object, 1, 2), Array(2 ** 32 - 1).length]);
show('Array ctor bad', () => Array(1.5));
show('Array ctor bad neg', () => new Array(-1));
show('push past 2**53-1', () => Array.prototype.push.call({length: 2 ** 53 - 1}, 1));
show('concat too long', () => [1].concat({length: 2 ** 53 - 1, [Symbol.isConcatSpreadable]: true}).length);
show('splice too long', () => Array.prototype.splice.call({length: 2 ** 53 - 1}, 0, 0, 1));
show('unshift too long', () => Array.prototype.unshift.call({length: 2 ** 53 - 1}, 1));
show('unshift nothing', () => Array.prototype.unshift.call({length: 2 ** 53 - 1}));
show('at huge array-like', () => Array.prototype.at.call({length: Infinity}, -1));
show('holes in prototype', () => { Array.prototype[1] = 'from proto'; try { return [[0, , 2].join(), [0, , 2].indexOf('from proto'), [0, , 2].map(x => x)[1]]; } finally { delete Array.prototype[1]; } });
''')


def test_array_generic_receivers(run, workdir):
    """CATCHES: array methods that only work on real arrays: they must accept array-likes (length
    coerced via ToLength, strings, missing indices), write back with Set semantics, and
    toString must fall back to Object.prototype.toString when join is not callable."""
    check(run, workdir, "array_generic_receivers", r'''
const AP = Array.prototype;
show('push array-like', () => { const o = {length: '2', 0: 'x'}; AP.push.call(o, 'y', 'z'); return o; });
show('pop empty object', () => { const o = {}; return [AP.pop.call(o), o]; });
show('shift array-like', () => { const o = {length: 3, 0: 'a', 2: 'c'}; return [AP.shift.call(o), o]; });
show('reverse array-like', () => AP.reverse.call({length: 3, 0: 'a', 2: 'c'}));
show('splice array-like', () => { const o = {length: 4, 0: 'a', 1: 'b', 2: 'c', 3: 'd'}; return [AP.splice.call(o, 1, 2, 'X'), o]; });
show('slice string', () => [AP.slice.call('abc', 1), AP.map.call('abc', c => c.toUpperCase()), AP.filter.call('a1b2', c => c > '9')]);
show('slice arguments', () => (function () { return AP.slice.call(arguments, 1); })(1, 2, 3));
show('length coercion', () => [AP.indexOf.call({length: '2', 0: 'a', 1: 'b'}, 'b'), AP.includes.call({length: -5, 0: 1}, 1), AP.join.call({length: 3}), AP.join.call({length: 2.9, 0: 'p', 1: 'q', 2: 'r'})]);
show('copyWithin array-like', () => AP.copyWithin.call({length: 5, 3: 1}, 0, 3));
show('fill array-like', () => AP.fill.call({length: 3}, 4));
show('entries array-like', () => [...AP.entries.call({length: 2, 0: 'a', 1: 'b'})]);
show('flat array-like', () => AP.flat.call({length: 2, 0: [1, [2]], 1: 3}, 2));
show('concat array-like spreadable', () => [].concat({length: 2, 0: 'a', 1: 'b', [Symbol.isConcatSpreadable]: true}, {length: 1, 0: 'not spread'}));
show('concat isConcatSpreadable false', () => { const arr = [9]; arr[Symbol.isConcatSpreadable] = false; return [[].concat(arr).length, [1].concat(2, [3, [4]], 'x')]; });
show('toString non-array', () => [AP.toString.call({join: () => 'J'}), AP.toString.call({}), AP.toString.call({join: 1})]);
show('toLocaleString', () => [1, 'a', null, undefined, 1234.5, [2, 3]].toLocaleString());
show('toLocaleString calls each', () => [{toLocaleString() { return 'L1'; }}, {toLocaleString: () => 'L2'}].toLocaleString());
show('null receiver', () => AP.map.call(null, x => x));
show('undefined receiver', () => AP.at.call(undefined, 0));
show('primitive receiver', () => [AP.push.call(true), AP.indexOf.call(5, 1)]);
show('iterator next on wrong receiver', () => [][Symbol.iterator]().next.call({}));
const like = {length: 5, 0: 'a', 1: 'b', 3: 'a', 4: NaN};
show('search array-like', () => [AP.indexOf.call(like, 'a', 1), AP.indexOf.call(like, 'a', -2), AP.indexOf.call(like, 'a', Infinity), AP.indexOf.call(like, undefined), AP.lastIndexOf.call(like, 'a'), AP.lastIndexOf.call(like, 'a', 2), AP.lastIndexOf.call(like, 'a', -Infinity), AP.lastIndexOf.call(like, 'a', -10), AP.includes.call(like, NaN), AP.includes.call(like, undefined), AP.includes.call(like, 'a', Infinity), AP.includes.call(like, 'b', -Infinity)]);
show('search fromIndex coercion on empty', () => { let called = false; const from = {valueOf() { called = true; return 0; }}; AP.indexOf.call({length: 0}, 1, from); AP.includes.call({length: 0}, 1, from); return called; });
show('sort writes back via Set', () => { const o = {length: 2, 0: 'b', 1: 'a'}; Object.defineProperty(o, '0', {value: 'b', writable: false}); return AP.sort.call(o); });
show('sort frozen array', () => Object.freeze([2, 1]).sort());
show('string iterators', () => [[...AP.keys.call('ab')], [...AP.values.call('h\u{1F600}')].length, [...AP.entries.call('xy')]]);
''')


def test_array_species_and_subclassing(run, workdir):
    """CATCHES: map/filter/slice/splice/concat/flat/flatMap not honouring Symbol.species (or
    using it for the ES2023 copy methods), null/undefined species falling back to Array, invalid
    species constructors not throwing, and Array subclass instances losing their class."""
    check(run, workdir, "array_species_and_subclassing", r'''
class MyA extends Array { sum() { return this.reduce((a, b) => a + b, 0); } }
const m = MyA.from([1, 2, 3]);
show('subclass basics', () => [m instanceof MyA, Array.isArray(m), m.length, m.sum(), MyA.of(4, 5).sum(), new MyA(3).length]);
show('species-created', () => [m.map(x => x).constructor.name, m.filter(Boolean).constructor.name, m.slice(1).constructor.name, m.splice(0, 0).constructor.name, m.concat([]).constructor.name, m.flat().constructor.name, m.flatMap(x => [x]).constructor.name]);
show('not species-created', () => [m.toSorted().constructor.name, m.toReversed().constructor.name, [...m].constructor.name, Array.from(m).constructor.name]);
show('species null', () => { const a = [1, 2]; a.constructor = {[Symbol.species]: null}; return a.map(x => x * 2); });
show('constructor undefined', () => { const a = [1, 2]; a.constructor = undefined; return a.map(x => x * 2); });
show('constructor primitive', () => { const a = [1, 2]; a.constructor = 1; return a.map(x => x); });
show('species not ctor', () => { const a = [1, 2]; a.constructor = {[Symbol.species]: 1}; return a.map(x => x); });
show('species custom', () => { const a = [1, 2]; a.constructor = {[Symbol.species]: function (n) { this.created = n; }}; return a.map(x => x * 3); });
show('species non-writable result', () => { const a = [1]; a.constructor = {[Symbol.species]: function () { return Object.freeze({}); }}; return a.map(x => x); });
show('species length arg', () => { const lens = []; class Spy extends Array { static get [Symbol.species]() { return function (n) { lens.push(n); return []; }; } } const s = Spy.from([1, 2, 3, 4]); s.map(x => x); s.filter(x => x); s.slice(1, 3); s.splice(0, 1); return lens; });
show('cross-type species', () => { class S2 extends Array { static get [Symbol.species]() { return Array; } } const s = S2.from([1]); return [s.map(x => x) instanceof S2, s instanceof S2]; });
show('Array[Symbol.species]', () => [Array[Symbol.species] === Array, MyA[Symbol.species] === MyA]);
show('length property of subclass', () => { const s = new MyA(); s[5] = 1; return [s.length, Object.getOwnPropertyDescriptor(s, 'length').writable]; });
show('extends null proto array', () => { const o = Object.setPrototypeOf([1, 2], null); return [Array.isArray(o), Array.prototype.map.call(o, x => x + 1)]; });
''')


def test_array_from_of_and_iterators(run, workdir):
    """CATCHES: Array.from not preferring the iterator over array-like length, splitting strings by
    code units instead of code points, ignoring mapFn/thisArg, not closing the iterator when mapFn
    throws, using `this` as constructor; array iterator objects with the wrong tag/next/receiver
    checks, and live iteration over arrays mutated during for-of."""
    check(run, workdir, "array_from_of_and_iterators", r'''
show('from string', () => Array.from('a\u{1F600}b'));
show('from length', () => Array.from({length: 3}, (v, i) => i * i));
show('from set/map', () => [Array.from(new Set([1, 1, 2])), Array.from(new Map([[1, 'a']]))]);
show('from thisArg', () => Array.from([1, 2], function (x) { return x + this.d; }, {d: 10}));
show('from prefers iterator', () => Array.from({length: 5, 0: 'ignored', *[Symbol.iterator]() { yield 'it'; }}));
show('from bad mapFn', () => Array.from([1], 1));
show('from array-like no iterator', () => Array.from({length: 2, 1: 'b'}));
show('from null', () => Array.from(null));
show('from number', () => Array.from(3));
show('from too long', () => Array.from({length: 2 ** 32}));
show('from closes iterator', () => { let closed = false; const it = {[Symbol.iterator]() { return {next() { return {value: 1, done: false}; }, return() { closed = true; return {}; }}; }}; try { Array.from(it, () => { throw new Error('m'); }); } catch (e) { return [e.message, closed]; } });
show('from this ctor', () => { function C(n) { this.made = n; } const r = Array.from.call(C, {length: 2, 0: 'a', 1: 'b'}); return [r instanceof C, r.made, r.length, r[1]]; });
show('from this ctor iterable', () => { function C(n) { this.args = arguments.length; } const r = Array.from.call(C, ['x']); return [r instanceof C, r.args, r.length]; });
show('from non-ctor this', () => Array.from.call(() => {}, [1, 2]) instanceof Array);
show('of', () => [Array.of(1, 2), Array.of(undefined), Array.of.call(function () {}, 'z').constructor === Array]);
show('isArray', () => [Array.isArray([]), Array.isArray(new Proxy([], {})), Array.isArray(Array.prototype), Array.isArray({length: 0}), Array.isArray(new Proxy(new Proxy([], {}), {})), Array.isArray(Object.create(Array.prototype))]);
show('iterator objects', () => { const it = [7][Symbol.iterator](); return [Object.prototype.toString.call(it), it[Symbol.toStringTag], it.next(), it.next(), it.next(), Object.getPrototypeOf(Object.getPrototypeOf(it)) === Iterator.prototype]; });
show('iterator identity', () => [Array.prototype[Symbol.iterator] === Array.prototype.values, Array.prototype.values.name, Array.prototype.entries.name]);
show('for-of growth', () => { const b = [1, 2, 3]; const r = []; for (const x of b) { r.push(x); if (x === 1) b.push(4); if (x === 2) b.shift(); } return r; });
show('exhausted stays done', () => { const b = [1]; const it = b.values(); it.next(); it.next(); b.push(2); return it.next(); });
show('iterating array-like', () => [...Array.prototype.values.call({length: 2, 0: 'p', 1: 'q'})]);
show('destructuring holes', () => { const [x = 'dflt', , z] = [, 'skip', 'z']; return [x, z]; });
show('spread string', () => [...'😀\uD83D'].map(s => s.length));
''')


def test_array_from_async(run, workdir):
    """CATCHES: Array.fromAsync not awaiting values of sync iterables/array-likes, not awaiting
    async mapFn results, missing TypeErrors (non-callable mapFn, null input) delivered as
    rejections, rejected elements not rejecting, or ignoring a constructor `this`."""
    check(run, workdir, "array_from_async", r'''
const out = (l, v) => console.log(l + ' => ' + fmt(v));
const err = e => e && e.name ? e.name + ': ' + e.message : 'thrown ' + fmt(e);
(async () => {
  out('array of promises', await Array.fromAsync([1, Promise.resolve(2), 3]));
  out('async mapFn', await Array.fromAsync([1, 2], async x => x * 10));
  out('mapFn with index', await Array.fromAsync(['a', 'b'], (x, i) => x + i));
  async function* g() { yield 'a'; yield Promise.resolve('b'); }
  out('async generator', await Array.fromAsync(g()));
  out('array-like', await Array.fromAsync({length: 2, 0: Promise.resolve('x'), 1: 'y'}));
  out('sync iterable', await Array.fromAsync(new Set([3, 4])));
  out('string', await Array.fromAsync('hi'));
  const p = Array.fromAsync([]);
  out('returns promise', [p instanceof Promise, (await p).length]);
  try { await Array.fromAsync([1], 5); } catch (e) { out('bad mapFn', err(e)); }
  try { await Array.fromAsync(null); } catch (e) { out('null input', err(e)); }
  try { await Array.fromAsync({length: 2 ** 32}); } catch (e) { out('array-like too long', err(e)); }
  try { await Array.fromAsync([Promise.reject(new Error('rej'))]); } catch (e) { out('rejected element', err(e)); }
  try { await Array.fromAsync([1], () => { throw new RangeError('in map'); }); } catch (e) { out('mapFn throws', err(e)); }
  class C { constructor() { this.made = true; } }
  const r = await Array.fromAsync.call(C, [1, 2]);
  out('this ctor', [r instanceof C, r.length, r[0], r.made]);
  const order = [];
  const pr = Array.fromAsync([1, 2]).then(() => order.push('fromAsync done'));
  Promise.resolve().then(() => order.push('microtask'));
  await pr;
  out('settles asynchronously', order);
})();
''')
