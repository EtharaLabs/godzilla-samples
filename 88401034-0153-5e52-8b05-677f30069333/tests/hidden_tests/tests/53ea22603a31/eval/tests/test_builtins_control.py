"""Control-flow built-ins: Promise (job ordering, combinators, constructor/statics errors,
subclassing, thenable assimilation), iterator helpers (laziness, closing, Iterator.from/concat/
zip), explicit resource management (using / await using, DisposableStack, AsyncDisposableStack,
SuppressedError), ShadowRealm, and the Error hierarchy."""

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
const describeError = e => e !== null && typeof e === 'object' ? e.name + ': ' + e.message : 'thrown ' + fmt(e);
const show = (label, f) => {
  try { console.log(label + ' => ' + fmt(f())); }
  catch (e) { console.log(label + ' !! ' + describeError(e)); }
};
const showAsync = async (label, f) => {
  try { console.log(label + ' => ' + fmt(await f())); }
  catch (e) { console.log(label + ' !! ' + describeError(e)); }
};
'''


def check(run, workdir, name, body, *, module=False, **kw):
    """Run PRELUDE + body (as an .mjs module when `module`) and compare with the golden `name`."""
    filename = f"{name}.mjs" if module else None
    return check_script(run, workdir, G, name, PRELUDE + body, filename=filename, **kw)


def test_promise_job_ordering(run, workdir):
    """CATCHES: wrong microtask ordering: then-chains interleaving, the extra ticks for resolving
    with a native promise or thenable (NewPromiseResolveThenableJob), await on non-promises,
    async functions returning promises, finally's extra hops, queueMicrotask FIFO with promise
    jobs, and `then` getters read once during resolution."""
    check(run, workdir, "promise_job_ordering", r'''
const log = [];
const p = s => log.push(s);
Promise.resolve().then(() => p('A1')).then(() => p('A2')).then(() => p('A3')).then(() => p('A4')).then(() => p('A5'));
new Promise(r => r(Promise.resolve())).then(() => p('resolved-with-promise'));
Promise.resolve({then(r) { p('thenable.then'); r(); }}).then(() => p('thenable-done'));
(async () => { p('async-1'); await undefined; p('async-2'); await Promise.resolve(); p('async-3'); })();
(async () => { return Promise.resolve(); })().then(() => p('async-return-promise'));
queueMicrotask(() => p('qm'));
Promise.reject(new Error('r')).then(null, () => p('rejected-handler'));
Promise.resolve().finally(() => p('finally-cb')).then(() => p('after-finally'));
Promise.resolve(1).then(v => { p('value ' + v); return {get then() { p('then getter read'); return undefined; }}; }).then(() => p('non-callable then fulfilled'));
const thrower = Promise.resolve().then(() => { throw new Error('in then'); });
thrower.catch(e => p('caught ' + e.message));
p('sync end');
setTimeout(() => console.log(log.join('\n')), 20);
''', module=True)


def test_promise_combinators(run, workdir):
    """CATCHES: Promise.all/allSettled/any/race producing wrong values/order, not rejecting with the
    first rejection, AggregateError for any() with empty message and ordered errors, invoking
    Promise.resolve (looked up once per element) and thenables synchronously, closing the
    iterator on errors, plus Promise.allKeyed/allSettledKeyed results and their TypeErrors."""
    check(run, workdir, "promise_combinators", r'''
await showAsync('all', () => Promise.all([1, Promise.resolve(2), {then(r) { r(3); }}]));
await showAsync('all empty', () => Promise.all([]));
await showAsync('all first rejection', () => Promise.all([1, Promise.reject(new Error('A')), Promise.reject(new Error('B'))]));
await showAsync('all order by index', () => Promise.all([new Promise(r => setTimeout(() => r('slow'), 30)), 'fast']));
await showAsync('allSettled', () => Promise.allSettled([1, Promise.reject('no'), {then(_, j) { j('thenable no'); }}]));
await showAsync('any', () => Promise.any([Promise.reject(1), Promise.resolve(2), 3]));
await showAsync('any all rejected', async () => { try { await Promise.any([Promise.reject(1), Promise.reject(2)]); } catch (e) { return [e.name, e.message, e.errors, e instanceof AggregateError, Object.keys(e)]; } });
await showAsync('any empty', async () => { try { await Promise.any([]); } catch (e) { return [e.name, e.message, e.errors]; } });
await showAsync('race', () => Promise.race([new Promise(r => setTimeout(() => r('slow'), 30)), Promise.resolve('fast')]));
await showAsync('race rejection wins', () => Promise.race([Promise.reject(new Error('first')), Promise.resolve('second')]));
await showAsync('all non-iterable', () => Promise.all(5));
await showAsync('race undefined (message JSON-escaped)', () => Promise.race().catch(e => e.name + ': ' + e.message));
await showAsync('string iterable', () => Promise.all('ab'));
await showAsync('then called synchronously', async () => { const order = []; const pr = Promise.all([{then(r) { order.push('then called'); r('x'); }}]); order.push('after all()'); return [await pr, order]; });
await showAsync('resolve called per element', async () => { const orig = Promise.resolve; let calls = 0; Promise.resolve = function (v) { calls++; return orig.call(this, v); }; try { await Promise.all([1, 2, 3]); await Promise.allSettled([4]); return calls; } finally { Promise.resolve = orig; } });
await showAsync('resolve not callable', async () => { const orig = Promise.resolve; Promise.resolve = 1; try { return await Promise.all([1]); } finally { Promise.resolve = orig; } });
await showAsync('iterator closed when resolve throws', async () => { let closed = false; const it = {[Symbol.iterator]() { return {next() { return {value: 1, done: false}; }, return() { closed = true; return {}; }}; }}; const orig = Promise.resolve; Promise.resolve = () => { throw new Error('resolve threw'); }; try { await Promise.race(it); } catch (e) { return [e.message, closed]; } finally { Promise.resolve = orig; } });
await showAsync('allKeyed', () => Promise.allKeyed({a: 1, b: Promise.resolve(2), [Symbol('s')]: 3}));
await showAsync('allKeyed result shape', async () => { const o = await Promise.allKeyed({b: 1, a: 2}); return [Object.keys(o), Object.getPrototypeOf(o)]; });
await showAsync('allSettledKeyed', () => Promise.allSettledKeyed({ok: 1, bad: Promise.reject('no')}));
await showAsync('allKeyed rejection', () => Promise.allKeyed({a: Promise.reject(new Error('keyed'))}));
await showAsync('allKeyed primitive', () => Promise.allKeyed(5));
show('statics', () => Object.getOwnPropertyNames(Promise).sort().join(' '));
''', module=True)


def test_promise_constructor_and_statics(run, workdir):
    """CATCHES: Promise constructor validation (new required, callable executor), resolve functions
    (length 1, nameless, idempotent), executor throwing after resolve being ignored, self-resolution
    TypeError, then/catch/finally receiver checks and pass-through of non-callable handlers,
    finally semantics, subclass/species propagation, withResolvers and Promise.try."""
    check(run, workdir, "promise_constructor_and_statics", r'''
show('ctor bad executor', () => new Promise(1));
show('ctor without new', () => Promise(() => {}));
show('resolve functions', () => { let res, rej; new Promise((a, b) => { res = a; rej = b; }); return [res.length, res.name, rej.length, 'prototype' in res]; });
await showAsync('resolve twice', () => new Promise(r => { r(1); r(2); }));
await showAsync('executor throws after resolve', () => new Promise(r => { r('first'); throw new Error('ignored'); }));
await showAsync('executor throws', () => new Promise(() => { throw new RangeError('exec'); }));
await showAsync('self resolution', () => { let res; const sp = new Promise(r => { res = r; }); res(sp); return sp; });
show('Promise.resolve non-object this', () => Promise.resolve.call(1, 2));
show('Promise.reject non-ctor this', () => Promise.reject.call({}, 2));
show('then on non-promise', () => Promise.prototype.then.call({}, () => {}));
show('resolve identity', () => { const pr = Promise.resolve(1); return [Promise.resolve(pr) === pr, new Promise(r => r(pr)) === pr]; });
await showAsync('then non-callable args', () => Promise.resolve(7).then(5, null));
await showAsync('catch passthrough', () => Promise.reject(8).then(v => 'no').catch(v => 'got ' + v));
await showAsync('catch calls then', async () => { const calls = []; const fake = {then(a, b) { calls.push(typeof a, typeof b); return 'then result'; }}; return [Promise.prototype.catch.call(fake, () => {}), calls]; });
await showAsync('finally value passthrough', () => Promise.resolve(1).finally(() => 'ignored'));
await showAsync('finally throw overrides', () => Promise.resolve(1).finally(() => { throw new Error('fin'); }));
await showAsync('finally reject passthrough', () => Promise.reject(2).finally(() => Promise.resolve(3)).catch(v => 'reason ' + v));
await showAsync('finally waits for promise', async () => { const order = []; await Promise.resolve().finally(() => new Promise(r => setTimeout(() => { order.push('inner'); r(); }, 10))).then(() => order.push('outer')); return order; });
await showAsync('finally non-callable', () => Promise.resolve(4).finally(5));
await showAsync('then getter throws', () => Promise.resolve({get then() { throw new Error('then getter threw'); }}));
await showAsync('withResolvers', async () => { const {promise, resolve, reject} = Promise.withResolvers(); resolve('wr'); return [await promise, typeof reject, Object.keys(Promise.withResolvers())]; });
show('withResolvers non-ctor', () => Promise.withResolvers.call({}));
await showAsync('try sync value', () => Promise.try((a, b) => a + b, 1, 2));
await showAsync('try throws', () => Promise.try(() => { throw new Error('t'); }));
await showAsync('try returns promise', () => Promise.try(() => Promise.resolve('inner')));
show('try is async', () => { const r = []; Promise.try(() => r.push('callback ran')); r.push('after try'); return r; });
await showAsync('subclass', async () => { class MyP extends Promise {} const mp = MyP.resolve(1); return [mp instanceof MyP, mp.then(() => {}) instanceof MyP, MyP.all([]) instanceof MyP, mp.finally(() => {}) instanceof MyP, MyP.withResolvers().promise instanceof MyP, Promise.resolve(mp) === mp]; });
await showAsync('species override', async () => { class P2 extends Promise { static get [Symbol.species]() { return Promise; } } const x = P2.resolve(1).then(v => v); return [x instanceof P2, x instanceof Promise]; });
await showAsync('then with non-promise species', async () => { const native = Promise.resolve(5); const seen = []; let created; native.constructor = {[Symbol.species]: function (executor) { const self = this; created = this; executor(v => { self.v = v; seen.push('resolve ' + v); }, () => seen.push('reject')); }}; const res = native.then(x => x * 2); await new Promise(r => setTimeout(r, 10)); return [res === created, res instanceof Promise, seen, res.v]; });
show('capability functions not callable', () => ['all', 'allSettled', 'any', 'race', 'resolve', 'reject', 'withResolvers'].map(m => { try { Promise[m].call(function NotAPromise(executor) { executor(1, 2); }, []); return m + ' ok'; } catch (e) { return m + ': ' + e.message; } }));
show('capability executor called twice', () => Promise.resolve.call(function (ex) { ex(() => {}, () => {}); ex(() => {}, () => {}); }, 1));
show('combinator on undefined this', () => Promise.all.call(undefined, []));
show('proto keys', () => Reflect.ownKeys(Promise.prototype).map(String));
show('tags', () => [Object.prototype.toString.call(Promise.resolve()), Promise.prototype[Symbol.toStringTag], Promise.length, Promise.prototype.then.length, Promise.all.length]);
''', module=True)


def test_iterator_helpers_laziness(run, workdir):
    """CATCHES: iterator helpers that are eager (pulling the source on creation or reading ahead),
    take() not closing the source once satisfied, drop() not skipping lazily, flatMap not
    flattening per item, short-circuiting reducers (some/every/find) not calling return(), and
    callbacks receiving the wrong counter argument."""
    check(run, workdir, "iterator_helpers_laziness", r'''
const log = [];
function src(n) {
  let i = 0;
  return {__proto__: Iterator.prototype,
    next() { log.push('next' + i); return i < n ? {value: i++, done: false} : {value: undefined, done: true}; },
    return() { log.push('return'); return {}; }};
}
const step = (label, f) => { log.length = 0; show(label, f); console.log('   log: ' + log.join(' ')); };
const h = src(10).map(x => { log.push('map' + x); return x * 2; }).filter(x => { log.push('filter' + x); return x % 4 === 0; }).take(2);
step('chain created', () => 'nothing pulled');
step('chain next 1', () => h.next());
step('chain next 2', () => h.next());
step('chain next 3 closes', () => h.next());
step('chain after done', () => h.next());
step('drop', () => src(5).drop(3).toArray());
step('flatMap', () => [...src(2).flatMap(x => { log.push('fm' + x); return [x, x]; })]);
step('some', () => src(5).some(x => x === 2));
step('every', () => src(5).every(x => x < 1));
step('find', () => src(5).find(x => x === 3));
step('find none', () => src(2).find(x => x > 9));
step('take(0)', () => src(5).take(0).next());
step('return after start', () => { const m = src(3).map(x => x); m.next(); return [m.return(), m.next()]; });
step('return before start', () => { const m = src(3).map(x => x); return [m.return(), m.next()]; });
step('reduce', () => [src(5).reduce((a, b) => a + b), src(3).reduce((a, b) => a + b, 10)]);
step('forEach', () => { const r = []; src(3).forEach((v, i) => r.push(v + ':' + i)); return r; });
step('counter argument', () => src(3).filter((v, i) => i !== 1).map((v, i) => v + '@' + i).toArray());
function* nat() { let i = 0; while (true) yield i++; }
show('infinite source', () => nat().map(x => x * x).filter(x => x % 2).drop(1).take(4).toArray());
show('array iterator helpers', () => [[1, 2, 3, 4].values().drop(2).toArray(), ['a', 'b'].values().map((s, i) => s + i).toArray()]);
show('generator helpers', () => (function* () { yield 'x'; yield 'y'; })().flatMap(s => [s, s.toUpperCase()]).toArray());
''', module=True)


def test_iterator_helpers_errors_and_constructors(run, workdir):
    """CATCHES: missing validation in iterator helpers (non-callable callbacks, negative/NaN limits
    after closing the source, non-object `this`, non-object results), flatMap accepting primitive
    strings, not closing the source when a callback throws, re-entrancy ('already running'),
    and Iterator / Iterator.from / Iterator.concat / Iterator.zip / zipKeyed semantics and errors."""
    check(run, workdir, "iterator_helpers_errors_and_constructors", r'''
const log = [];
function src(n) {
  let i = 0;
  return {__proto__: Iterator.prototype,
    next() { log.push('next' + i); return i < n ? {value: i++, done: false} : {value: undefined, done: true}; },
    return() { log.push('return'); return {}; }};
}
const step = (label, f) => { log.length = 0; show(label, f); console.log('   log: ' + log.join(' ')); };
step('map not callable', () => src(1).map(1));
step('take NaN', () => src(1).take('x'));
step('take negative', () => src(1).take(-1));
step('drop negative', () => src(1).drop(-1));
step('reduce no reducer', () => src(1).reduce());
step('reduce empty', () => src(0).reduce((a, b) => a));
step('callback throws closes', () => src(3).map(() => { throw new Error('cb'); }).next());
step('next throws does not close', () => ({__proto__: Iterator.prototype, next() { throw new Error('next threw'); }, return() { log.push('return'); return {}; }}).map(x => x).next());
show('next returns primitive', () => ({__proto__: Iterator.prototype, next() { return 1; }}).toArray());
show('flatMap string', () => ['ab'].values().flatMap(s => s).toArray());
show('flatMap String object', () => [1].values().flatMap(() => new String('xy')).toArray());
show('flatMap number', () => [1].values().flatMap(x => x).toArray());
show('helper on non-object', () => Iterator.prototype.map.call(1, x => x));
show('toArray without next', () => Iterator.prototype.toArray.call({}));
show('already running', () => { let it; it = [1].values().map(() => it.next()); return it.next(); });
show('take Infinity', () => [1, 2].values().take(Infinity).toArray());
show('Iterator abstract', () => new Iterator());
show('Iterator call', () => Iterator());
show('Iterator subclass', () => { class MyIt extends Iterator { next() { return {value: undefined, done: true}; } } return [new MyIt() instanceof Iterator, new MyIt().toArray()]; });
show('from iterator', () => { const g = (function* () { yield 1; })(); return Iterator.from(g) === g; });
show('from wraps plain next', () => { const it = Iterator.from({next() { return {value: 1, done: false}; }}); return [Object.getPrototypeOf(it) === Iterator.prototype, it.take(2).toArray(), Object.prototype.toString.call(it)]; });
step('from wrapped return', () => Iterator.from({next() { return {value: 1, done: false}; }, return() { log.push('return'); return {done: true}; }}).return());
show('from iterables', () => [Iterator.from([1, 2]).toArray(), Iterator.from('ab').toArray(), Iterator.from({[Symbol.iterator]() { return [7, 8].values(); }}).toArray()]);
show('from number', () => Iterator.from(5));
show('from bad @@iterator', () => Iterator.from({[Symbol.iterator]: 1}));
show('from @@iterator returns primitive', () => Iterator.from({[Symbol.iterator]() { return 1; }}));
show('concat', () => Iterator.concat([1, 2], new Set([3]), 'ab'.split('')).toArray());
show('concat no args', () => [Iterator.concat().toArray(), Object.prototype.toString.call(Iterator.concat())]);
show('concat primitive', () => Iterator.concat(1));
show('concat non-iterable object', () => Iterator.concat({}));
step('concat lazy + return', () => { const c = Iterator.concat(src(2), src(2)); return [c.next(), c.return()]; });
show('zip shortest', () => Iterator.zip([[1, 2, 3], ['a', 'b']]).toArray());
show('zip longest padding', () => Iterator.zip([[1, 2], ['a']], {mode: 'longest', padding: [0, 'z']}).toArray());
show('zip strict mismatch', () => Iterator.zip([[1, 2], ['a']], {mode: 'strict'}).toArray());
show('zip bad mode', () => Iterator.zip([[1]], {mode: 'bogus'}));
show('zip non-object', () => Iterator.zip(5));
show('zip non-iterable element', () => Iterator.zip([1]));
show('zip empty', () => Iterator.zip([], {}).toArray());
show('zipKeyed', () => [Iterator.zipKeyed({a: [1, 2], b: [3, 4]}).toArray(), Iterator.zipKeyed({a: [1, 2], b: [3]}, {mode: 'longest', padding: {b: 'pad'}}).toArray()]);
show('prototype shape', () => [Reflect.ownKeys(Iterator.prototype).map(String).join(' '), Object.getOwnPropertyNames(Iterator).sort().join(' '), Iterator.prototype[Symbol.toStringTag]]);
show('toStringTag setter on prototype', () => { Iterator.prototype[Symbol.toStringTag] = 'x'; });
show('toStringTag setter on instance', () => { const o = Object.create(Iterator.prototype); o[Symbol.toStringTag] = 'Mine'; return [Object.prototype.toString.call(o), Iterator.prototype[Symbol.toStringTag]]; });
show('helper tag', () => Object.prototype.toString.call([].values().map(x => x)));
''', module=True)


def test_using_declarations(run, workdir):
    """CATCHES: `using`/`await using` disposing in the wrong (non-LIFO) order, skipping null/
    undefined resources incorrectly, not throwing 'value is not disposable' at declaration time,
    wrong SuppressedError nesting (error = newest failure, suppressed = earlier), await using
    falling back to Symbol.dispose, and disposal on break/return from loops and functions."""
    check(run, workdir, "using_declarations", r'''
const log = [];
const res = (name, fail) => ({[Symbol.dispose]() { log.push('dispose ' + name); if (fail) throw new Error('from ' + name); }});
{
  using a = res('a');
  using b = res('b');
  using n = null, u = undefined;
  log.push('body');
}
console.log('basic: ' + log.join(', ')); log.length = 0;
try {
  using x = res('x', true);
  using y = res('y', true);
  throw new Error('body error');
} catch (e) {
  console.log('nested: ' + [e.constructor.name, e.message, e.error.message, e.suppressed.constructor.name, e.suppressed.error.message, e.suppressed.suppressed.message].join(' | '));
}
console.log('nested order: ' + log.join(', ')); log.length = 0;
try { { using only = res('only', true); } } catch (e) { console.log('single failure: ' + describeError(e) + ' ' + (e instanceof SuppressedError)); }
log.length = 0;
for (const bad of [5, {}, {[Symbol.dispose]: 1}, 'str']) { try { using z = bad; log.push('unreachable'); } catch (e) { console.log('not disposable (' + typeof bad + '): ' + describeError(e)); } }
function early() { using r = res('fn'); log.push('returning'); return 'ret'; }
console.log('function return: ' + early() + ' ' + log.join(', ')); log.length = 0;
for (const i of [1, 2, 3]) { using r = res('loop' + i); if (i === 2) break; }
console.log('loop: ' + log.join(', ')); log.length = 0;
for (using r of [res('of1'), res('of2')]) log.push('iter');
console.log('for-using-of: ' + log.join(', ')); log.length = 0;
const getterLog = [];
try { using g = {get [Symbol.dispose]() { getterLog.push('dispose getter'); return () => getterLog.push('disposed'); }}; getterLog.push('body'); } catch (e) { console.log(describeError(e)); }
console.log('method read once at declaration: ' + getterLog.join(', '));
{
  await using a = {async [Symbol.asyncDispose]() { log.push('async a'); }};
  await using b = {[Symbol.dispose]() { log.push('sync b via await using'); }};
  await using c = null;
  log.push('body');
}
console.log('await using: ' + log.join(', ')); log.length = 0;
try { await using q = 1; } catch (e) { console.log('await using primitive: ' + describeError(e)); }
try { await using q = {async [Symbol.asyncDispose]() { throw new RangeError('async dispose failed'); }}; } catch (e) { console.log('async dispose rejection: ' + describeError(e)); }
const order = [];
{ await using t = {[Symbol.asyncDispose]() { order.push('dispose'); return Promise.resolve(); }}; order.push('body'); }
order.push('after block');
console.log('awaited: ' + order.join(', '));
const gen = (function* () { try { yield 1; } finally { log.push('generator finally'); } })();
gen.next(); gen[Symbol.dispose]();
console.log('generator dispose: ' + log.join(', ') + ' | ' + typeof [].values()[Symbol.dispose]);
async function* ag() { try { yield 1; yield 2; } finally { console.log('async generator finally'); } }
{ await using it = ag(); console.log('async generator first value: ' + (await it.next()).value); }
const adispose = Object.getPrototypeOf(Object.getPrototypeOf(ag.prototype))[Symbol.asyncDispose];
console.log('AsyncIterator.prototype[@@asyncDispose]: ' + [typeof adispose, adispose.name, adispose.length].join(' '));
let argCount;
console.log('no return method: ' + await adispose.call({}) + ' | return result dropped: ' + await adispose.call({return(...a) { argCount = a.length; return {value: 'ignored'}; }}) + ' args=' + argCount);
for (const [label, obj] of [['getter throws', {get return() { throw new Error('getter threw'); }}], ['return throws', {return() { throw new Error('return threw'); }}], ['return rejects', {return() { return Promise.reject(new Error('return rejected')); }}]]) {
  const pr = adispose.call(obj);
  try { await pr; } catch (e) { console.log('asyncDispose ' + label + ': promise=' + (pr instanceof Promise) + ' rejected with ' + describeError(e)); }
}
''', module=True)


def test_disposable_stacks(run, workdir):
    """CATCHES: DisposableStack/AsyncDisposableStack not disposing LIFO, not passing adopt's value to
    its callback, use() accepting non-disposables, move() not transferring resources and marking
    the source disposed, operations on disposed stacks not throwing ReferenceError, double dispose
    not being a no-op, errors not aggregated into SuppressedError, and SuppressedError itself."""
    check(run, workdir, "disposable_stacks", r'''
const log = [];
const s = new DisposableStack();
console.log('fresh: ' + [s.disposed, typeof s.dispose, Object.prototype.toString.call(s), DisposableStack.prototype[Symbol.dispose] === DisposableStack.prototype.dispose].join(' '));
s.defer(() => log.push('defer1'));
const r = {[Symbol.dispose]() { log.push('use1'); }};
console.log('use returns value: ' + (s.use(r) === r));
console.log('adopt returns value: ' + s.adopt('held', v => log.push('adopt ' + v)));
console.log('use null/undefined: ' + [s.use(null), s.use(undefined)].join(','));
const moved = s.move();
console.log('after move: ' + s.disposed + ' ' + moved.disposed + ' ' + (moved instanceof DisposableStack));
for (const [label, f] of [['defer', () => s.defer(() => {})], ['use', () => s.use(null)], ['adopt', () => s.adopt(1, () => {})], ['move', () => s.move()]]) {
  try { f(); console.log(label + ' on disposed: ok'); } catch (e) { console.log(label + ' on disposed: ' + describeError(e)); }
}
console.log('dispose disposed: ' + s.dispose());
moved.dispose(); moved.dispose();
console.log('LIFO: ' + log.join(', ') + ' ' + moved.disposed); log.length = 0;
show('use non-disposable', () => new DisposableStack().use(1));
show('use without method', () => new DisposableStack().use({}));
show('defer non-callable', () => new DisposableStack().defer(1));
show('adopt non-callable', () => new DisposableStack().adopt(1, 2));
show('without new', () => DisposableStack());
show('dispose wrong receiver', () => DisposableStack.prototype.dispose.call({}));
show('errors aggregated', () => { const s2 = new DisposableStack(); s2.defer(() => { throw new Error('d1'); }); s2.defer(() => { throw new Error('d2'); }); s2.defer(() => log.push('ok one')); try { s2.dispose(); } catch (e) { return [e.constructor.name, e.message, e.error.message, e.suppressed.message, log.join()]; } });
show('single error not wrapped', () => { const s3 = new DisposableStack(); s3.defer(() => { throw new TypeError('lonely'); }); try { s3.dispose(); } catch (e) { return [e.constructor.name, e.message]; } });
show('SuppressedError', () => { const e = new SuppressedError(new Error('new'), new Error('old'), 'supp'); return [e.name, e.message, e.error.message, e.suppressed.message, String(e), SuppressedError.length, Object.getOwnPropertyNames(e).filter(k => k !== 'stack').sort(), Object.getPrototypeOf(SuppressedError) === Error]; });
show('SuppressedError no message', () => { const e = new SuppressedError(1, 2); return [e.message, e.hasOwnProperty('message'), e.error, e.suppressed]; });
show('SuppressedError call', () => SuppressedError('a', 'b', 'c').message);
const as = new AsyncDisposableStack();
as.defer(async () => log.push('as defer'));
as.use({[Symbol.asyncDispose]: async () => log.push('as use async')});
as.use({[Symbol.dispose]: () => log.push('as use sync')});
as.adopt('v', async v => log.push('as adopt ' + v));
const done = as.disposeAsync();
console.log('disposeAsync returns promise: ' + (done instanceof Promise) + ' ' + log.length);
await done;
console.log('async LIFO: ' + log.join(', ') + ' ' + as.disposed);
console.log('disposeAsync again: ' + (await as.disposeAsync()));
await showAsync('async errors', async () => { const a2 = new AsyncDisposableStack(); a2.defer(() => Promise.reject(new Error('r1'))); a2.defer(async () => { throw new Error('r2'); }); try { await a2.disposeAsync(); } catch (e) { return [e.constructor.name, e.error.message, e.suppressed.message]; } });
await showAsync('async use non-disposable', async () => new AsyncDisposableStack().use(5));
await showAsync('disposeAsync wrong receiver', () => AsyncDisposableStack.prototype.disposeAsync.call({}));
show('async tags', () => [Object.prototype.toString.call(new AsyncDisposableStack()), AsyncDisposableStack.prototype[Symbol.asyncDispose] === AsyncDisposableStack.prototype.disposeAsync]);
await showAsync('async move', async () => { const src = new AsyncDisposableStack(); src.defer(() => log.push('moved defer')); log.length = 0; const dst = src.move(); const r = [src.disposed, dst.disposed, dst instanceof AsyncDisposableStack]; await src.disposeAsync(); r.push(log.length); await dst.disposeAsync(); r.push(log.join()); return r; });
for (const [label, f] of [['defer', st => st.defer(() => {})], ['use', st => st.use(null)], ['adopt', st => st.adopt(1, () => {})], ['move', st => st.move()]]) {
  const st = new AsyncDisposableStack(); await st.disposeAsync();
  show('async ' + label + ' on disposed', () => f(st));
}
show('async use null/undefined', () => { const st = new AsyncDisposableStack(); return [st.use(null), st.use(undefined)]; });
show('async defer non-callable', () => new AsyncDisposableStack().defer(1));
show('async adopt non-callable', () => new AsyncDisposableStack().adopt(1, 2));
show('async without new', () => AsyncDisposableStack());
show('async disposed getter wrong receiver', () => Object.getOwnPropertyDescriptor(AsyncDisposableStack.prototype, 'disposed').get.call(new DisposableStack()));
''', module=True)


def test_shadow_realm(run, workdir):
    """CATCHES: ShadowRealm leaking objects across the boundary (only primitives and callables may
    cross, as wrapped functions with copied name/length), sharing globals/intrinsics with the
    incubator realm, not converting inner errors into TypeErrors (syntax errors stay SyntaxError),
    and evaluate/importValue argument validation messages."""
    check(run, workdir, "shadow_realm", r'''
const r = new ShadowRealm();
show('primitive', () => [r.evaluate('1 + 2'), r.evaluate('"s" + 1'), r.evaluate('undefined'), r.evaluate('null'), r.evaluate('10n ** 20n'), typeof r.evaluate('Symbol("x")')]);
show('global isolation', () => { globalThis.leak = 1; return [r.evaluate('typeof leak'), r.evaluate('globalThis.Array === Array'), r.evaluate('Array') === Array]; });
show('state persists', () => { r.evaluate('var counter = 0'); r.evaluate('counter++'); return r.evaluate('counter'); });
show('separate intrinsics', () => { r.evaluate('Array.prototype.myExtra = 1'); return [[].myExtra, r.evaluate('[].myExtra')]; });
show('object result', () => r.evaluate('({})'));
show('array result', () => r.evaluate('[1, 2]'));
show('wrapped function', () => { const f = r.evaluate('(x) => x * 2'); return [typeof f, f(21), f.name, f.length, Object.getPrototypeOf(f) === Function.prototype, 'prototype' in f]; });
show('wrapped name/length', () => { const f = r.evaluate('function namedFn(a, b, c) {}; namedFn'); return [f.name, f.length]; });
show('wrapped returns object', () => r.evaluate('() => ({})')());
show('wrapped receives object', () => r.evaluate('(o) => typeof o')({}));
show('wrapped receives callable', () => r.evaluate('(cb) => cb(5) + 1')(x => x * 10));
show('wrapped throws', () => r.evaluate('() => { throw new RangeError("inner"); }')());
show('wrapped not constructible', () => new (r.evaluate('(function F() {})'))());
show('syntax error', () => r.evaluate('1 +'));
show('syntax error class', () => { try { r.evaluate('let let = 1'); } catch (e) { return [e.constructor === SyntaxError, e instanceof Error]; } });
show('evaluation throws', () => r.evaluate('throw new Error("boom")'));
show('evaluation throws primitive', () => r.evaluate('throw 5'));
show('error is outer TypeError', () => { try { r.evaluate('null.x'); } catch (e) { return [e.constructor === TypeError, e.message]; } });
show('non-string source', () => r.evaluate(1));
show('without new', () => ShadowRealm());
show('bad receiver', () => ShadowRealm.prototype.evaluate.call({}, '1'));
show('tag', () => [Object.prototype.toString.call(r), typeof ShadowRealm.prototype.importValue, ShadowRealm.length]);
show('importValue bad export name', () => r.importValue('./x.js', 1));
show('importValue bad receiver', () => ShadowRealm.prototype.importValue.call({}, './x.js', 'y'));
await showAsync('importValue missing module', () => r.importValue('./does-not-exist.mjs', 'x'));
show('strict directive per evaluation', () => [r.evaluate('sloppyGlobal = 1; typeof sloppyGlobal'), (() => { try { return r.evaluate('"use strict"; strictGlobal = 1'); } catch (e) { return describeError(e); } })(), r.evaluate('typeof strictGlobal')]);
show('lexicals are per evaluation', () => [r.evaluate('let lex = 1; const k = 2; lex + k'), r.evaluate('typeof lex'), r.evaluate('var v1 = 3; typeof v1'), r.evaluate('typeof v1')]);
show('realm microtasks drained', () => { r.evaluate('Promise.resolve().then(() => { globalThis.mt = "ran"; }); 0'); return r.evaluate('typeof mt === "undefined" ? "pending" : mt'); });
show('two realms independent', () => { const r2 = new ShadowRealm(); r2.evaluate('var counter = 100'); return [r.evaluate('counter'), r2.evaluate('counter')]; });
''', module=True)


def test_error_objects(run, workdir):
    """CATCHES: Error constructors with wrong own properties (message only when provided, cause only
    when present in options, non-enumerable), wrong prototype chains/names for native errors,
    Error.prototype.toString edge cases, AggregateError argument order and errors array,
    Error.isError/captureStackTrace, and exact messages of engine-thrown errors."""
    check(run, workdir, "error_objects", r'''
show('basic', () => { const e = new Error('msg'); return [e.name, e.message, String(e), Object.keys(e), Object.getOwnPropertyNames(e).filter(k => k !== 'stack').sort(), e instanceof Error, Object.prototype.toString.call(e)]; });
show('no message', () => [String(new Error()), new Error().hasOwnProperty('message'), Error('x').message, new Error(undefined).hasOwnProperty('message'), String(new Error(null)), String(new Error(''))]);
show('message coercion', () => [new Error(42).message, new Error({toString() { return 'obj'; }}).message, new TypeError([1, 2]).message]);
show('message symbol', () => new Error(Symbol('s')));
show('message descriptor', () => { const d = Object.getOwnPropertyDescriptor(new Error('q'), 'message'); return [d.writable, d.enumerable, d.configurable]; });
show('cause', () => { const e = new Error('m', {cause: 0}); return [e.cause, e.hasOwnProperty('cause'), new Error('m', {}).hasOwnProperty('cause'), new Error('m', 1).hasOwnProperty('cause'), new Error('m', {cause: undefined}).hasOwnProperty('cause'), Object.getOwnPropertyDescriptor(e, 'cause')]; });
show('cause getter called once', () => { const log = []; new Error('m', {get cause() { log.push('get'); return 1; }}); return log; });
show('native types', () => [EvalError, RangeError, ReferenceError, SyntaxError, TypeError, URIError].map(C => { const e = new C('x'); return [e.name, String(e), Object.getPrototypeOf(C) === Error, C.prototype.hasOwnProperty('message'), C.prototype.message, C.length]; }));
show('prototype props', () => [Error.prototype.name, TypeError.prototype.name, Error.prototype.message, Object.prototype.toString.call(Error.prototype), Object.getPrototypeOf(TypeError.prototype) === Error.prototype]);
show('toString variants', () => [Error.prototype.toString.call({name: 'N', message: 'M'}), Error.prototype.toString.call({}), Error.prototype.toString.call({name: '', message: 'only'}), Error.prototype.toString.call({name: 'onlyname', message: ''}), Error.prototype.toString.call({name: undefined, message: undefined}), Error.prototype.toString.call({name: 5, message: true})]);
show('toString non-object', () => Error.prototype.toString.call(1));
show('AggregateError', () => { const e = new AggregateError(new Set([new Error('a'), 2]), 'multi', {cause: 'c'}); return [e.name, e.message, e.errors.length, e.errors[1], e.cause, String(e), Object.getOwnPropertyNames(e).filter(k => k !== 'stack').sort(), Array.isArray(e.errors), Object.getOwnPropertyDescriptor(e, 'errors').enumerable, AggregateError.length]; });
show('AggregateError fresh array', () => { const src = [1]; const e = new AggregateError(src); return [e.errors !== src, e.message, e.hasOwnProperty('message')]; });
show('AggregateError not iterable', () => new AggregateError(5));
show('AggregateError no args (message JSON-escaped)', () => { try { new AggregateError(); } catch (e) { return e.name + ': ' + e.message; } });
show('subclass', () => { class MyErr extends RangeError { constructor(m) { super(m); this.name = 'MyErr'; } } const e = new MyErr('boom'); return [String(e), e instanceof RangeError, e instanceof MyErr, e.constructor.name, Object.prototype.toString.call(e)]; });
show('call without new', () => { const e = TypeError('t'); return [e instanceof TypeError, e.message]; });
show('isError', () => [Error.isError(new Error()), Error.isError({__proto__: Error.prototype}), Error.isError(new (class extends TypeError {})()), Error.isError(null), Error.isError(Object.create(RangeError.prototype)), Error.isError(new AggregateError([]))]);
show('captureStackTrace', () => { const o = {}; Error.captureStackTrace(o); return [typeof o.stack, Object.getOwnPropertyDescriptor(o, 'stack') !== undefined, typeof Error.stackTraceLimit]; });
show('stack first line', () => [typeof new Error('s').stack, new Error('s').stack.split('\n')[0], new TypeError('t').stack.split('\n')[0]]);
const stackDesc = Object.getOwnPropertyDescriptor(Error.prototype, 'stack');
show('stack accessor shape', () => [typeof stackDesc.get, typeof stackDesc.set, stackDesc.enumerable, stackDesc.configurable, stackDesc.get.name, stackDesc.set.name]);
show('stack head is computed at read', () => { const e = new Error('first'); const before = e.stack.split('\n')[0]; e.message = 'changed'; e.name = 'Renamed'; const e2 = new Error('m'); e2.name = ''; return [before, e.stack.split('\n')[0], new TypeError('').stack.split('\n')[0], e2.stack.split('\n')[0]]; });
show('stack getter non-error', () => [stackDesc.get.call({}), stackDesc.get.call(Object.create(Error.prototype))]);
show('stack getter primitive', () => stackDesc.get.call(1));
show('stack setter primitive', () => stackDesc.set.call(1, 's'));
show('stack setter non-string', () => stackDesc.set.call({}, 5));
show('stack setter on Error.prototype', () => stackDesc.set.call(Error.prototype, 's'));
show('stack setter defines own', () => { const o = {}; stackDesc.set.call(o, 'custom'); const e = new Error('x'); e.stack = 'replaced'; return [Object.getOwnPropertyDescriptor(o, 'stack'), e.stack, Object.getOwnPropertyDescriptor(e, 'stack').enumerable]; });
show('stack setter non-extensible', () => stackDesc.set.call(Object.preventExtensions({}), 's'));
show('engine errors', () => {
  const r = [];
  const t = f => { try { f(); r.push('no error'); } catch (e) { r.push(e.name + ': ' + e.message); } };
  t(() => undefinedVar); t(() => null.f); t(() => undefined.p.q); t(() => ({}).foo()); t(() => eval('1 +'));
  t(() => { let x = x; }); t(() => { const c = 1; c = 2; }); t(() => new (() => {})()); t(() => [].reduce(() => {}));
  t(() => new Array(-1)); t(() => 'abc'.repeat(-1)); t(() => Symbol() + ''); t(() => 1n + 1);
  t(() => ({}) instanceof 1); t(() => 'x' in 'str'); t(() => class A extends 5 {}); t(() => { class B { #p; static t(o) { return o.#p; } } B.t({}); });
  return r;
});
''')


def test_promise_combinator_abrupt_paths(run, workdir):
    """CATCHES: Promise.all/allSettled/any/race not turning every abrupt step into a rejection:
    a throwing iterator next() must NOT close the iterator, while a throwing/non-callable
    C.resolve, a throwing `then` getter or a throwing `then` call must close it; also non-iterable
    inputs and the exact TypeError for a non-callable resolve."""
    check(run, workdir, "promise_combinator_abrupt_paths", r"""
const log = [];
const iterable = (items, throwAt = -1) => ({[Symbol.iterator]() { let i = 0; return {next() { if (i === throwAt) throw new Error('next threw'); return i < items.length ? {value: items[i++], done: false} : {value: undefined, done: true}; }, return() { log.push('closed'); return {}; }}; }});
const modes = {
  'next throws': () => [Promise, iterable([1, 2], 1)],
  'resolve throws': () => { class P extends Promise { static resolve() { throw new Error('resolve threw'); } } return [P, iterable([1])]; },
  'then getter throws': () => { class P extends Promise { static resolve() { return {get then() { throw new Error('then getter threw'); }}; } } return [P, iterable([1])]; },
  'then call throws': () => { class P extends Promise { static resolve() { return {then() { throw new Error('then threw'); }}; } } return [P, iterable([1])]; },
  'resolve not callable': () => { class P extends Promise {} Object.defineProperty(P, 'resolve', {value: 'nope'}); return [P, iterable([1])]; },
  'not iterable': () => [Promise, 42],
  'custom then fulfills': () => { class P extends Promise { static resolve(v) { return {then(f) { log.push('custom then'); f(v * 10); }}; } } return [P, iterable([1, 2])]; },
};
for (const comb of ['all', 'allSettled', 'any', 'race']) {
  for (const [mode, mk] of Object.entries(modes)) {
    log.length = 0;
    const [C, it] = mk();
    let out;
    try { out = 'fulfilled ' + fmt(await C[comb](it)); } catch (e) { out = 'rejected ' + describeError(e); }
    console.log(comb.padEnd(10) + ' ' + mode.padEnd(20) + ' ' + out + (log.length ? ' [' + log.join(',') + ']' : ''));
  }
}
""", module=True)


def test_iterator_zip_protocol(run, workdir):
    """CATCHES: Iterator.zip/zipKeyed opening inputs lazily or in the wrong order, not closing the
    remaining inputs (in reverse order) when the shortest finishes, strict mode not detecting
    length mismatches in both directions, return() not closing every open input, padding iterables
    read the wrong number of times or not closed, setup errors leaking open iterators, zipKeyed key
    order / null-prototype results, and option validation messages."""
    check(run, workdir, "iterator_zip_protocol", r"""
const log = [];
const src = (name, n) => { let i = 0; return {[Symbol.iterator]() { log.push('open ' + name); return {next() { log.push('next ' + name); return i < n ? {value: name + i++, done: false} : {value: undefined, done: true}; }, return() { log.push('close ' + name); return {}; }}; }}; };
const step = (label, f) => { log.length = 0; show(label, f); console.log('   log: ' + log.join(', ')); };
step('shortest closes others', () => Iterator.zip([src('a', 1), src('b', 3), src('c', 3)]).toArray());
step('longest', () => Iterator.zip([src('a', 1), src('b', 2)], {mode: 'longest'}).toArray());
step('strict ok', () => Iterator.zip([src('a', 2), src('b', 2)], {mode: 'strict'}).toArray());
step('strict first shorter', () => Iterator.zip([src('a', 1), src('b', 2), src('c', 5)], {mode: 'strict'}).toArray());
step('strict first longer', () => Iterator.zip([src('a', 2), src('b', 1)], {mode: 'strict'}).toArray());
step('return closes in reverse', () => { const z = Iterator.zip([src('a', 3), src('b', 3), src('c', 3)]); z.next(); return z.return(); });
step('return before start', () => { const z = Iterator.zip([src('a', 3), src('b', 3)]); return [z.return(), z.next()]; });
step('padding iterable', () => Iterator.zip([src('a', 1), src('b', 2), src('c', 3)], {mode: 'longest', padding: src('p', 10)}).toArray());
step('padding too short', () => Iterator.zip([src('a', 1), src('b', 2)], {mode: 'longest', padding: ['only']}).toArray());
step('padding not object', () => Iterator.zip([src('a', 1)], {mode: 'longest', padding: 5}));
step('options not object', () => Iterator.zip([src('a', 1)], 5));
step('mode not string', () => Iterator.zip([src('a', 1)], {mode: 1}));
step('setup error closes opened', () => Iterator.zip([src('a', 1), src('b', 1), 5]));
step('strings rejected', () => Iterator.zip(['ab', 'cd']).toArray());
step('input next throws', () => { const bad = {[Symbol.iterator]() { return {next() { throw new Error('inner next'); }, return() { log.push('close bad'); return {}; }}; }}; return Iterator.zip([src('a', 3), bad, src('c', 3)]).next(); });
step('close errors', () => { const mk = n => ({[Symbol.iterator]() { return {next() { return {value: 1, done: false}; }, return() { log.push('close ' + n); throw new Error('close ' + n); }}; }}); const z = Iterator.zip([mk('a'), mk('b')]); z.next(); return z.return(); });
step('reentrant next', () => { let z; const evil = {[Symbol.iterator]() { return {next() { return z.next(); }}; }}; z = Iterator.zip([evil]); return z.next(); });
step('zipKeyed', () => Iterator.zipKeyed({x: src('a', 2), y: src('b', 2), skip: undefined}).toArray());
step('zipKeyed key order', () => { const s = Symbol('s'); const r = Iterator.zipKeyed({2: src('two', 1), b: src('b', 1), [s]: src('sym', 1), 1: src('one', 1)}).next().value; return [Reflect.ownKeys(r).map(String), Object.getPrototypeOf(r)]; });
step('zipKeyed non-enumerable skipped', () => Iterator.zipKeyed(Object.defineProperty({a: [1]}, 'hidden', {value: [2], enumerable: false})).toArray());
step('zipKeyed padding object', () => Iterator.zipKeyed({a: src('a', 1), b: src('b', 2)}, {mode: 'longest', padding: {a: 'PA'}}).toArray());
step('zipKeyed primitive', () => Iterator.zipKeyed(1));
step('zipKeyed value not iterable', () => Iterator.zipKeyed({a: 1}));
show('result tags', () => [Object.prototype.toString.call(Iterator.zip([[1]])), Object.prototype.toString.call(Iterator.zipKeyed({})), Iterator.zip.length, Iterator.zipKeyed.length]);
""", module=True)


def test_async_generator_methods(run, workdir):
    """CATCHES: async generators not queueing next() calls made before earlier ones settle, not
    awaiting yielded promises (a rejected yield must throw into the body), return()/throw() on
    suspended-start or completed generators resolving/rejecting wrongly (return awaits its
    argument), receiver validation reported as a rejection, yield* forwarding return(), and
    for-await over async and sync iterables."""
    check(run, workdir, "async_generator_methods", r'''
const log = [];
async function* g() { try { log.push('start'); const x = yield 1; log.push('got ' + x); yield Promise.resolve(2); yield 3; } catch (e) { log.push('caught ' + describeError(e)); yield 'after catch'; } finally { log.push('finally'); } }
const step = async (label, f) => { log.length = 0; await showAsync(label, f); console.log('   log: ' + log.join(', ')); };
await step('queued next calls', () => { const it = g(); return Promise.all([it.next('ignored'), it.next('second'), it.next(), it.next(), it.next()]); });
await step('return before start', async () => { const it = g(); return [await it.return('early'), await it.next()]; });
await step('throw before start', () => g().throw(new Error('before start')));
await step('throw while suspended', async () => { const it = g(); await it.next(); return [await it.throw(new Error('inside')), await it.next()]; });
await step('return awaits its argument', async () => { const it = g(); await it.next(); return it.return(Promise.resolve('awaited return')); });
await step('completed generator', async () => { const it = g(); await it.next(); await it.return(); const r = [await it.return('x'), await it.return(Promise.resolve('resolved on completed'))]; try { await it.return(Promise.reject(new Error('rejected return'))); } catch (e) { r.push(describeError(e)); } try { await it.throw(new Error('after done')); } catch (e) { r.push(describeError(e)); } return r; });
await step('yielded rejection', async () => { async function* y() { try { yield Promise.reject(new Error('yielded rejection')); } catch (e) { yield 'recovered ' + e.message; } } const it = y(); return [await it.next(), await it.next()]; });
const AG = Object.getPrototypeOf(g.prototype);
await step('bad receiver rejects', async () => { const p = AG.next.call(1); const r = [p instanceof Promise]; try { await p; } catch (e) { r.push(describeError(e)); } try { await AG.return.call({}); } catch (e) { r.push(describeError(e)); } return r; });
show('prototype shape', () => [Object.prototype.toString.call(g()), Object.getOwnPropertyNames(AG).sort().join(' '), AG[Symbol.toStringTag], typeof AG[Symbol.asyncIterator]]);
await step('yield* forwards return', async () => { async function* delegating() { return yield* g(); } const it = delegating(); return [await it.next(), await it.return('delegated return')]; });
await step('for await', async () => { const out = []; for await (const v of (async function* () { yield 'a'; yield 'b'; })()) out.push(v); for await (const v of [Promise.resolve('p1'), 'plain']) out.push(v); return out; });
await step('break closes async generator', async () => { for await (const v of g()) { log.push('value ' + v); break; } return 'broke'; });
''', module=True)
