"""Keyed collections: Map/Set ordering and SameValueZero keys, live iteration while mutating,
constructors and their adder lookups, Map.groupBy, the ES2025 Set methods with real sets, maps and
set-like objects (including which protocol members they call), WeakMap/WeakSet/WeakRef/
FinalizationRegistry validation, and Map upsert methods."""

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
  if (v instanceof Map) return 'Map{' + [...v].map(([k, x]) => fmt(k, d + 1) + ' => ' + fmt(x, d + 1)).join(', ') + '}';
  if (v instanceof Set) return 'Set{' + [...v].map(x => fmt(x, d + 1)).join(', ') + '}';
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


def test_map_set_order_and_keys(run, workdir):
    """CATCHES: Map/Set not preserving insertion order (re-setting an existing key must keep its
    slot, delete+add moves it to the end), keys compared with === instead of SameValueZero
    (NaN equal, -0 normalised to +0), object keys by identity, wrong size/has/get/delete/clear
    results and chaining return values."""
    check(run, workdir, "map_set_order_and_keys", r'''
show('map order', () => { const m = new Map([['b', 1], ['a', 2]]); m.set('c', 3); m.delete('b'); m.set('b', 4); m.set('a', 5); return [...m]; });
show('set order', () => { const s = new Set(['x', 'y', 'z']); s.delete('x'); s.add('x'); s.add('y'); return [...s]; });
show('map -0 and NaN', () => { const m = new Map(); m.set(-0, 'zero'); m.set(NaN, 'nan'); m.set(0 / 0, 'nan2'); return [m.get(0), m.get(NaN), Object.is([...m.keys()][0], -0), m.has(-0), m.size]; });
show('set -0 and NaN', () => { const s = new Set([-0, 0, NaN, NaN, '0', 0n]); return [s.size, Object.is([...s][0], -0), [...s]]; });
show('object keys identity', () => { const k = {}; const m = new Map([[k, 1], [{}, 2]]); return [m.get(k), m.get({}), m.size]; });
show('mixed key types', () => { const m = new Map([[1, 'num'], ['1', 'str'], [1n, 'big'], [true, 'bool'], [null, 'null'], [undefined, 'undef']]); return [m.get(1), m.get('1'), m.get(1n), m.get(true), m.get(null), m.get(undefined), m.get(), m.size]; });
show('symbol keys', () => { const s = Symbol('k'); return [new Map([[s, 1]]).get(s), new Set([s, s]).size]; });
show('chaining', () => { const m = new Map(); const s = new Set(); return [m.set(1, 1) === m, s.add(1) === s, m.delete(1), m.delete(1), m.clear(), s.clear(), m.size, s.size]; });
show('set entries', () => [[...new Set(['a', 'b']).entries()], [...new Set(['a']).keys()]]);
show('map keys/values', () => { const m = new Map([[1, 'a'], [2, 'b']]); return [[...m.keys()], [...m.values()], [...m.entries()]]; });
show('forEach args and thisArg', () => { const r = []; new Map([[1, 2]]).forEach(function (v, k, m) { r.push(v, k, m instanceof Map, this.t); }, {t: 'T'}); new Set(['x']).forEach((v, k, s) => r.push(v, k, s.size)); return r; });
show('forEach not callable', () => new Map().forEach(1));
show('large', () => { const m = new Map(); for (let i = 0; i < 1000; i++) m.set('k' + i, i); for (let i = 0; i < 1000; i += 2) m.delete('k' + i); let sum = 0; for (const v of m.values()) sum += v; return [m.size, sum, [...m.keys()].slice(0, 3)]; });
show('protos and tags', () => [Object.prototype.toString.call(new Map()), Object.prototype.toString.call(new Set()), Map.prototype[Symbol.iterator] === Map.prototype.entries, Set.prototype.keys === Set.prototype.values, Set.prototype[Symbol.iterator] === Set.prototype.values, Map.prototype.set.length, Set.prototype.add.length]);
show('size getter', () => [Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.name, typeof Object.getOwnPropertyDescriptor(Set.prototype, 'size').set]);
show('Map.prototype.size', () => Map.prototype.size);
show('get on Set', () => Map.prototype.get.call(new Set(), 1));
show('size of Map via Set getter', () => Object.getOwnPropertyDescriptor(Set.prototype, 'size').get.call(new Map()));
show('add on WeakSet', () => Set.prototype.add.call(new WeakSet(), {}));
''')


def test_collection_iteration_while_mutating(run, workdir):
    """CATCHES: Map/Set iterators that snapshot entries instead of being live: entries added during
    iteration must be visited, deleted ones skipped, clear() + add continues with the new entry,
    re-added entries revisited, and an exhausted iterator stays done even after new additions.
    Pinned quirk: the reference's Map iterator next() accepts a Set iterator receiver and reports
    done instead of throwing a TypeError."""
    check(run, workdir, "collection_iteration_while_mutating", r'''
show('map delete/add during for-of', () => { const m = new Map([[1, 'a'], [2, 'b'], [3, 'c']]); const seen = []; for (const [k] of m) { seen.push(k); if (k === 1) { m.delete(2); m.set(4, 'd'); } if (k === 3) m.set(1, 'again'); } return [seen, [...m.keys()]]; });
show('set clear during iteration', () => { const s = new Set([1, 2, 3]); const seen = []; for (const v of s) { seen.push(v); if (v === 1) { s.clear(); s.add(9); } } return seen; });
show('set re-add during iteration', () => { const s = new Set([1, 2]); const seen = []; for (const v of s) { seen.push(v); if (seen.length < 5) { s.delete(v); s.add(v); } } return seen; });
show('delete current entry', () => { const m = new Map([['a', 1], ['b', 2], ['c', 3]]); const seen = []; for (const [k] of m) { seen.push(k); m.delete(k); } return [seen, m.size]; });
show('forEach sees additions', () => { const s = new Set([1]); const seen = []; s.forEach(v => { seen.push(v); if (v < 4) s.add(v + 1); }); return seen; });
show('manual iterator', () => { const m = new Map([[1, 'x']]); const it = m.entries(); const r = [it.next(), it.next()]; m.set(2, 'y'); r.push(it.next()); return r; });
show('iterator created before additions', () => { const s = new Set(); const it = s.values(); s.add('late'); return [it.next(), it.next()]; });
show('iterator after delete of all then add', () => { const s = new Set([1, 2]); const it = s.values(); it.next(); s.delete(1); s.delete(2); s.add(3); return [it.next(), it.next()]; });
show('iterator objects', () => { const it = new Map([[1, 2]]).entries(); return [Object.prototype.toString.call(it), Object.prototype.toString.call(new Set().values()), it[Symbol.iterator]() === it, typeof it.next, Object.getPrototypeOf(Object.getPrototypeOf(it)) === Iterator.prototype]; });
show('iterator next wrong receiver', () => new Map().keys().next.call(new Set().values()));
show('spread after mutation', () => { const m = new Map([[1, 1]]); const it = m.keys(); m.set(2, 2); return [...it]; });
''')


def test_collection_constructors(run, workdir):
    """CATCHES: Map/Set/WeakMap/WeakSet constructors not requiring `new`, not using the
    (overridable) prototype adder set/add per entry, not validating entry objects, iterating
    strings by code point, failing to close the iterator on errors, and their exact TypeErrors."""
    check(run, workdir, "collection_constructors", r'''
show('Map from iterables', () => [new Map([[1, 'a'], [2]]), new Map(new Map([['k', 'v']])), new Map(), new Map(null), new Map(undefined)]);
show('Set from string', () => new Set('a\u{1F600}a'));
show('Map entry not object', () => new Map([1]));
show('Map entry string', () => new Map(['ab']));
show('Map entry array-like', () => new Map([{0: 'k', 1: 'v'}]));
show('Map without new', () => Map());
show('Set without new', () => Set([]));
show('not iterable', () => new Set(5));
show('object not iterable', () => new Map({}));
show('adder override used', () => { const orig = Set.prototype.add; let calls = 0; Set.prototype.add = function (v) { calls++; return orig.call(this, v * 10); }; try { return [calls, [...new Set([1, 2])], calls]; } finally { Set.prototype.add = orig; } });
show('adder not callable', () => { const orig = Map.prototype.set; Map.prototype.set = 1; try { return new Map([[1, 2]]); } finally { Map.prototype.set = orig; } });
show('adder not looked up for empty', () => { const orig = Set.prototype.add; Set.prototype.add = 1; try { return [new Set().size, new Set(null).size]; } finally { Set.prototype.add = orig; } });
show('closes iterator on bad entry', () => { let closed = false; const it = {[Symbol.iterator]() { return {next() { return {value: 'bad', done: false}; }, return() { closed = true; return {}; }}; }}; try { new Map(it); } catch (e) { return [e.message, closed]; } });
show('subclass', () => { class M2 extends Map { set(k, v) { return super.set(k, v * 2); } } return [new M2([[1, 1]]), new M2() instanceof Map]; });
show('species', () => [Map[Symbol.species] === Map, Set[Symbol.species] === Set, Object.getOwnPropertyDescriptor(Map, Symbol.species).get.name]);
show('WeakMap ctor', () => { const k = {}; const wm = new WeakMap([[k, 'v']]); return [wm.get(k), wm.has({})]; });
show('WeakMap bad entry key', () => new WeakMap([['s', 1]]));
show('WeakSet ctor', () => { const k = {}; return new WeakSet([k, k]).has(k); });
show('WeakSet bad value', () => new WeakSet([1]));
show('lengths', () => [Map.length, Set.length, WeakMap.length, WeakSet.length, Map.name]);
''')


def test_group_by(run, workdir):
    """CATCHES: Map.groupBy/Object.groupBy coercing keys wrongly (Map keeps object identity and
    normalises -0, Object.groupBy uses property keys), losing first-seen order, passing a wrong
    index to the callback, or accepting non-callables. The reference drains the iterator before
    invoking any callback (so a throwing callback does not trigger IteratorClose) and leaks an
    internal key name in the TypeError for a null input; both are pinned."""
    check(run, workdir, "group_by", r'''
show('Map.groupBy', () => Map.groupBy([1, 2, 3, 4, 5, 6], x => x % 3));
show('object keys by identity', () => { const k1 = {}; const g = Map.groupBy([k1, {}, k1], x => x); return [g.size, g.get(k1).length]; });
show('-0 normalised', () => [...Map.groupBy([1], () => -0).keys()].map(k => Object.is(k, -0)));
show('NaN key', () => Map.groupBy([1, 2], () => NaN).get(NaN));
show('callback index', () => Map.groupBy('abc', (c, i) => i % 2));
show('Object.groupBy keys coerced', () => Object.groupBy([1, 2, 3], x => x > 1 ? {toString() { return 'big'; }} : 1));
show('Object.groupBy symbol key', () => { const s = Symbol('g'); return Object.groupBy([1], () => s)[s]; });
show('Object.groupBy null proto', () => { const g = Object.groupBy(['a'], () => 'toString'); return [Object.getPrototypeOf(g), Array.isArray(g.toString)]; });
show('empty', () => [Map.groupBy([], x => x).size, Object.keys(Object.groupBy([], x => x)).length]);
show('Map.groupBy not callable', () => Map.groupBy([1], null));
show('Map.groupBy not iterable', () => Map.groupBy(1, x => x));
show('Map.groupBy null (message JSON-escaped)', () => { try { Map.groupBy(null, x => x); } catch (e) { return e.name + ': ' + e.message; } });
const log = [];
const finite = {[Symbol.iterator]() { let i = 0; return {next() { log.push('next'); return i < 3 ? {value: i++, done: false} : {value: undefined, done: true}; }, return() { log.push('return'); return {}; }}; }};
show('iteration vs callback order', () => { log.length = 0; Map.groupBy(finite, v => { log.push('cb' + v); return 1; }); return log.join(' '); });
show('callback throws', () => { log.length = 0; try { Object.groupBy(finite, v => { log.push('cb' + v); if (v === 1) throw new Error('cb threw'); return 'k'; }); } catch (e) { return [e.message, log.join(' ')]; } });
show('groups are arrays', () => { const g = Map.groupBy(new Set([3, 1, 2]), x => 'all').get('all'); return [Array.isArray(g), g]; });
''')


def test_set_methods_with_sets_and_maps(run, workdir):
    """CATCHES: wrong results or result ordering for union/intersection/difference/
    symmetricDifference (order depends on which side is iterated), wrong boolean results for
    isSubsetOf/isSupersetOf/isDisjointFrom, results that alias `this` or use subclass species,
    and Maps not being accepted as set-like (keys are used)."""
    check(run, workdir, "set_methods_with_sets_and_maps", r'''
const A = new Set([1, 2, 3, 4]);
const B = new Set([3, 4, 5]);
show('union', () => [A.union(B), B.union(A)]);
show('intersection', () => [A.intersection(B), B.intersection(A), new Set([5, 4, 3, 2, 1]).intersection(new Set([1, 3])), new Set([1, 3]).intersection(new Set([5, 4, 3, 2, 1]))]);
show('difference', () => [A.difference(B), B.difference(A), A.difference(new Set())]);
show('symmetricDifference', () => [A.symmetricDifference(B), B.symmetricDifference(A), A.symmetricDifference(A)]);
show('isSubsetOf', () => [new Set([3]).isSubsetOf(B), A.isSubsetOf(B), new Set().isSubsetOf(new Set()), A.isSubsetOf(A)]);
show('isSupersetOf', () => [A.isSupersetOf(new Set([1, 2])), A.isSupersetOf(B), A.isSupersetOf(new Set())]);
show('isDisjointFrom', () => [A.isDisjointFrom(new Set([9])), A.isDisjointFrom(B), new Set().isDisjointFrom(A)]);
show('with Map argument', () => [A.union(new Map([[9, 'x']])), A.isSubsetOf(new Map([[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]])), A.intersection(new Map([[2, 'two']]))]);
show('-0 in argument', () => { const r = new Set([0]).union(new Set([-0])); return [r.size, Object.is([...r][0], -0)]; });
show('result is fresh', () => { const r = A.union(new Set()); return [r !== A, r instanceof Set, Object.getPrototypeOf(r) === Set.prototype]; });
show('subclass result is Set', () => { class S2 extends Set {} return [new S2([1]).union(new Set([2])).constructor.name, new S2([1]).difference(new Set()).constructor.name]; });
show('receivers unchanged', () => { A.union(B); A.intersection(B); A.difference(B); A.symmetricDifference(B); return [A, B]; });
show('this not a Set', () => Set.prototype.union.call(new Map(), new Set()));
show('this is array', () => Set.prototype.isSubsetOf.call([1], new Set([1])));
show('lengths', () => ['union', 'intersection', 'difference', 'symmetricDifference', 'isSubsetOf', 'isSupersetOf', 'isDisjointFrom'].map(m => Set.prototype[m].length));
''')


def test_set_methods_with_set_likes(run, workdir):
    """CATCHES: Set methods not following the GetSetRecord protocol: size read first and validated
    (NaN -> TypeError, negative -> RangeError), has/keys must be callable, and the algorithm picks
    has() vs keys() iteration based on relative sizes; also infinite sizes, mutation of `this`
    during has() calls, and non-object arguments (arrays are not set-like)."""
    check(run, workdir, "set_methods_with_set_likes", r'''
const A = new Set([1, 2, 3, 4]);
const log = [];
const setLike = (items, size = items.length) => ({
  get size() { log.push('size'); return size; },
  has(v) { log.push('has(' + v + ')'); return items.includes(v); },
  keys() { log.push('keys'); let i = 0; return {next() { log.push('next'); return i < items.length ? {value: items[i++], done: false} : {value: undefined, done: true}; }}; },
});
const traced = (label, f) => { log.length = 0; show(label, f); console.log('   calls: ' + log.join(' ')); };
traced('union', () => A.union(setLike([4, 7])));
traced('intersection, this smaller', () => new Set([1, 7]).intersection(setLike([7, 8, 9])));
traced('intersection, this larger', () => A.intersection(setLike([2, 9])));
traced('difference, this smaller', () => new Set([1, 2]).difference(setLike([2, 5, 6])));
traced('difference, this larger', () => A.difference(setLike([2])));
traced('symmetricDifference', () => A.symmetricDifference(setLike([1, 9, 9])));
traced('isSubsetOf', () => new Set([1, 2]).isSubsetOf(setLike([1, 2, 3])));
traced('isSubsetOf, this larger', () => A.isSubsetOf(setLike([1, 2, 3])));
traced('isSupersetOf', () => A.isSupersetOf(setLike([1, 5])));
traced('isSupersetOf, other larger', () => new Set([1]).isSupersetOf(setLike([1, 2])));
traced('isDisjointFrom, this smaller', () => new Set([1]).isDisjointFrom(setLike([5, 6, 7])));
traced('isDisjointFrom, this larger', () => A.isDisjointFrom(setLike([5, 4])));
traced('size is read before has/keys', () => A.union({get size() { log.push('size'); return 1; }, get has() { log.push('get has'); return () => false; }, get keys() { log.push('get keys'); return () => [][Symbol.iterator](); }}));
const closing = (items, size = items.length) => ({size, has: v => items.includes(v), keys() { let i = 0; return {next() { log.push('next'); return i < items.length ? {value: items[i++], done: false} : {value: undefined, done: true}; }, return() { log.push('return'); return {}; }}; }});
traced('isSupersetOf early exit closes keys', () => A.isSupersetOf(closing([1, 9, 2])));
traced('isDisjointFrom early exit closes keys', () => A.isDisjointFrom(closing([9, 3, 8])));
traced('isDisjointFrom no early exit', () => A.isDisjointFrom(closing([9, 8])));
show('keys next returns primitive', () => A.union({size: 1, has() {}, keys() { return {next() { return 1; }}; }}));
show('keys next returns primitive (superset)', () => A.isSupersetOf({size: 1, has() {}, keys() { return {next() { return 7; }}; }}));
show('size NaN', () => A.union({size: 'x', has() {}, keys() {}}));
show('size missing', () => A.union({has() {}, keys() {}}));
show('size negative', () => A.union({size: -1, has() {}, keys() {}}));
show('has not callable', () => A.union({size: 1, has: 1, keys() {}}));
show('keys not callable', () => A.union({size: 1, has() {}, keys: 1}));
show('keys returns primitive', () => A.union({size: 1, has() {}, keys() { return 1; }}));
show('array argument', () => A.union([1]));
show('primitive argument', () => A.union(1));
show('infinite size', () => [A.isSubsetOf({size: Infinity, has: () => true, keys() { throw new Error('nope'); }}), A.intersection({size: Infinity, has: v => v > 2, keys() { throw new Error('nope'); }})]);
show('this mutated during has', () => { const s = new Set([1, 2, 3]); return s.intersection({size: 10, has(v) { if (v === 1) s.delete(2); return true; }, keys() {}}); });
show('keys values are not deduplicated by caller', () => A.symmetricDifference({size: 2, has: () => false, keys() { return [7, 7][Symbol.iterator](); }}));
''')


def test_weak_collections_and_refs(run, workdir):
    """CATCHES: WeakMap/WeakSet/WeakRef/FinalizationRegistry accepting primitives or registered
    symbols as keys/targets (non-registered symbols are allowed), returning wrong values for
    has/get/delete on invalid keys (false/undefined instead of throwing), and the exact
    TypeErrors for register/unregister validation (target === held, bad tokens)."""
    check(run, workdir, "weak_collections_and_refs", r'''
show('WeakMap ops', () => { const wm = new WeakMap(); const k = {}; return [wm.set(k, 1) === wm, wm.get(k), wm.has(k), wm.has({}), wm.delete(k), wm.has(k), wm.get(1), wm.delete(1), wm.has('x')]; });
show('WeakMap symbol keys', () => { const wm = new WeakMap(); const s = Symbol('local'); wm.set(s, 1); return [wm.get(s), wm.has(Symbol.for('reg'))]; });
show('WeakMap registered symbol', () => new WeakMap().set(Symbol.for('reg'), 1));
show('WeakMap primitive key', () => new WeakMap().set(1, 1));
show('WeakMap null key', () => new WeakMap().set(null, 1));
show('WeakSet ops', () => { const ws = new WeakSet(); const k = {}; return [ws.add(k) === ws, ws.has(k), ws.delete(k), ws.has(k), ws.has(1), ws.add(Symbol('ok')) instanceof WeakSet, ws.delete('x')]; });
show('WeakSet null', () => new WeakSet().add(null));
show('WeakSet registered symbol', () => new WeakSet().add(Symbol.for('r')));
show('WeakSet well-known symbol ok', () => new WeakSet().add(Symbol.iterator).has(Symbol.iterator));
show('Weak tags', () => [Object.prototype.toString.call(new WeakMap()), Object.prototype.toString.call(new WeakSet()), typeof WeakMap.prototype.clear, 'size' in WeakMap.prototype]);
show('WeakMap wrong receiver', () => WeakMap.prototype.get.call(new Map(), {}));
show('WeakRef', () => { const t = {v: 1}; const w = new WeakRef(t); return [w.deref() === t, Object.prototype.toString.call(w), WeakRef.prototype.constructor === WeakRef, typeof new WeakRef(Symbol('s')).deref()]; });
show('WeakRef primitive', () => new WeakRef(1));
show('WeakRef registered symbol', () => new WeakRef(Symbol.for('x')));
show('WeakRef without new', () => WeakRef({}));
show('WeakRef deref wrong receiver', () => WeakRef.prototype.deref.call({}));
show('FinalizationRegistry', () => { const fr = new FinalizationRegistry(() => {}); const tok = {}; return [fr.register({}, 'held', tok), fr.unregister(tok), fr.unregister(tok), fr.unregister({}), Object.prototype.toString.call(fr), fr.register({}, 'no token')]; });
show('register primitive target', () => new FinalizationRegistry(() => {}).register(1, 'x'));
show('register target is held', () => { const o = {}; new FinalizationRegistry(() => {}).register(o, o); });
show('register bad token', () => new FinalizationRegistry(() => {}).register({}, 1, 2));
show('register undefined token ok', () => new FinalizationRegistry(() => {}).register({}, 1, undefined));
show('unregister bad token', () => new FinalizationRegistry(() => {}).unregister(1));
show('bad cleanup callback', () => new FinalizationRegistry(1));
show('register wrong receiver', () => FinalizationRegistry.prototype.register.call({}, {}, 1));
show('unregister wrong receiver', () => FinalizationRegistry.prototype.unregister.call(new WeakMap(), {}));
show('register symbol target and token', () => { const fr = new FinalizationRegistry(() => {}); const s = Symbol('t'); return [fr.register(s, 'held', s), fr.unregister(s), fr.unregister(s)]; });
show('FinalizationRegistry without new', () => FinalizationRegistry(() => {}));
show('lengths', () => [WeakRef.length, FinalizationRegistry.length, FinalizationRegistry.prototype.register.length, FinalizationRegistry.prototype.unregister.length]);
''')


def test_map_upsert_methods(run, workdir):
    """CATCHES: Map/WeakMap getOrInsert/getOrInsertComputed inserting when the key already exists,
    calling the callback for existing keys, not normalising -0, or ignoring callback errors and
    key validation for WeakMap."""
    check(run, workdir, "map_upsert_methods", r'''
show('getOrInsert', () => { const m = new Map(); return [m.getOrInsert('a', 1), m.getOrInsert('a', 2), m]; });
show('getOrInsertComputed', () => { const m = new Map([['x', 0]]); const calls = []; const r = [m.getOrInsertComputed('b', k => { calls.push(k); return k + '!'; }), m.getOrInsertComputed('b', () => { calls.push('again'); return 'no'; }), m.getOrInsertComputed('x', () => 'unused')]; return [r, calls, m]; });
show('-0 key', () => { const m = new Map(); m.getOrInsertComputed(-0, k => Object.is(k, -0) ? 'neg' : 'pos'); return [[...m.keys()].map(k => Object.is(k, -0)), m.get(0)]; });
show('callback not callable', () => new Map().getOrInsertComputed('k', 1));
show('callback throws', () => { const m = new Map(); try { m.getOrInsertComputed('k', () => { throw new Error('cb'); }); } catch (e) { return [e.message, m.has('k')]; } });
show('callback mutates map', () => { const m = new Map(); const v = m.getOrInsertComputed('k', () => { m.set('k', 'inner'); return 'outer'; }); return [v, m]; });
show('WeakMap getOrInsert', () => { const wm = new WeakMap(); const k = {}; return [wm.getOrInsert(k, 1), wm.getOrInsert(k, 2), wm.getOrInsertComputed({}, () => 'c')]; });
show('WeakMap bad key', () => new WeakMap().getOrInsert(1, 1));
show('WeakMap computed bad key', () => new WeakMap().getOrInsertComputed('s', () => 1));
show('lengths', () => [Map.prototype.getOrInsert.length, Map.prototype.getOrInsertComputed.length]);
''')
