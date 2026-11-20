"""Core built-in library, part 2: Promise, Error types, Date, Proxy/Reflect, collections, iterator helpers,
Function.prototype, WeakRef/FinalizationRegistry and DisposableStack.

Each program prints labelled lines (exact values, error name+message) compared to a golden. Dates use only fixed
timestamps (TZ=UTC is fixed by the harness).
"""

import pytest

from conftest import golden, write_files

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


PROG_PROMISE_COMBINATORS_AND_STATICS = PRELUDE + r"""
const log = [];
const P = (v, label) => Promise.resolve(v).then(x => { log.push(label); return x; });
const rej = (e) => Promise.reject(e);
const delayTick = (v, n) => { let p = Promise.resolve(v); for (let i = 0; i < n; i++) p = p.then(x => x); return p; };
(async () => {
  show('all', await Promise.all([1, Promise.resolve(2), { then(r) { r(3); } }, delayTick(4, 3)]));
  show('all-empty', await Promise.all([]));
  try { await Promise.all([delayTick(1, 2), rej(new Error('first-reject')), rej(new Error('second'))]); } catch (e) { show('all-reject', e.message); }
  show('allSettled', await Promise.allSettled([1, rej('no'), delayTick('late', 2)]));
  show('any', await Promise.any([rej(1), delayTick('slow', 3), delayTick('fast', 1)]));
  try { await Promise.any([rej('a'), rej('b')]); } catch (e) { show('any-all-reject', e.name, e.message, e.errors, e instanceof AggregateError); }
  try { await Promise.any([]); } catch (e) { show('any-empty', e.name, e.message, e.errors); }
  show('race', await Promise.race([delayTick('slow', 3), delayTick('fast', 1)]));
  try { await Promise.race([delayTick('slow', 3), rej('fast-reject')]); } catch (e) { show('race-reject', e); }
  const never = Promise.race([]);
  let settled = false; never.then(() => settled = true, () => settled = true);
  await delayTick(0, 5);
  show('race-empty-pending', settled);
  // non-iterable inputs
  for (const m of ['all', 'allSettled', 'any', 'race']) {
    try { await Promise[m](5); } catch (e) { console.log('noniter', m, e.name + ': ' + e.message); }
  }
  // iterator closing on resolve lookup failure
  const closed = [];
  const iter = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { closed.push('return called'); return {}; } }; } };
  const FakeCtor = function (ex) { return new Promise(ex); };
  FakeCtor.resolve = 'not callable';
  try { await Promise.all.call(FakeCtor, iter); } catch (e) { show('resolve-not-callable', e.name, e.message, closed); }
  // withResolvers / try
  const wr = Promise.withResolvers();
  show('withResolvers', Object.keys(wr), wr.promise instanceof Promise, typeof wr.resolve, typeof wr.reject);
  wr.resolve('wr-value'); wr.resolve('ignored'); wr.reject('ignored too');
  show('withResolvers-value', await wr.promise);
  show('try-sync', await Promise.try(() => 'sync result'));
  show('try-args', await Promise.try((a, b) => a + b, 2, 3));
  try { await Promise.try(() => { throw new TypeError('thrown in try'); }); } catch (e) { show('try-throw', e.name, e.message); }
  show('try-returns-promise', await Promise.try(() => delayTick('inner', 2)));
  // finally
  const fin = [];
  show('finally-pass', await Promise.resolve('kept').finally(() => { fin.push('f1'); return 'ignored'; }));
  try { await Promise.reject('orig').finally(() => fin.push('f2')); } catch (e) { show('finally-reject-pass', e); }
  try { await Promise.resolve(1).finally(() => { throw 'from finally'; }); } catch (e) { show('finally-throw', e); }
  try { await Promise.resolve(1).finally(() => Promise.reject('finally-rejected')); } catch (e) { show('finally-returns-rejected', e); }
  show('finally-log', fin);
  show('finally-noncallable', await Promise.resolve('nc').finally(5));
  // resolve self
  let resolveSelf; const selfP = new Promise(r => { resolveSelf = r; }); resolveSelf(selfP);
  try { await selfP; } catch (e) { show('self-resolve', e.name, e.message); }
  // thenable that throws after resolve
  show('thenable-throw-after', await new Promise(r => r({ then(res) { res('first'); throw new Error('ignored'); } })));
  try { await { then(_, rj) { throw new Error('thenable threw'); } }; } catch (e) { show('thenable-throws', e.message); }
  // getter on then
  try { await Promise.resolve({ get then() { throw new Error('then getter'); } }); } catch (e) { show('then-getter-throws', e.message); }
  // Promise.resolve identity
  const pr = Promise.resolve(1);
  const rejPr = Promise.reject(pr); rejPr.catch(() => {});
  show('resolve-identity', Promise.resolve(pr) === pr, rejPr === pr, new Promise(r => r(pr)) === pr, (await rejPr.catch(x => x)) === pr);
  // subclass
  class MyP extends Promise { }
  const mp = MyP.resolve(5);
  show('subclass', mp instanceof MyP, mp.then(x => x) instanceof MyP, MyP.all([]) instanceof MyP, Promise.prototype.then.call(mp, x => x) instanceof MyP, mp.finally(() => {}) instanceof MyP);
  show('subclass-value', await mp.then(x => x * 2));
  // errors
  try { Promise(); } catch (e) { show('no-new', e.name, e.message); }
  try { new Promise(5); } catch (e) { show('bad-executor', e.name, e.message); }
  try { Promise.prototype.then.call({}, () => {}); } catch (e) { show('then-bad-this', e.name, e.message); }
  try { Promise.resolve.call(1, 2); } catch (e) { show('resolve-bad-this', e.name, e.message); }
  try { Promise.reject.call(undefined); } catch (e) { show('reject-bad-this', e.name, e.message); }
  try { Promise.withResolvers.call(5); } catch (e) { show('withResolvers-bad-this', e.name, e.message); }
  try { Promise.try.call('x', () => {}); } catch (e) { show('try-bad-this', e.name, e.message); }
  try { Promise.prototype.finally.call(1); } catch (e) { show('finally-bad-this', e.name, e.message); }
  try { Promise.all.call(function (ex) { ex(1, 2); }, []); } catch (e) { show('capability-noncallable', e.name, e.message); }
  try { Promise.resolve.call(function (ex) { ex(() => {}, () => {}); ex(() => {}, () => {}); }, 1); } catch (e) { show('capability-twice', e.name, e.message); }
  show('then-noncallable-args', await Promise.resolve('passthrough').then(5, 6), await Promise.reject('r').then(null, null).catch(x => 'caught ' + x));
  show('tags', Object.prototype.toString.call(Promise.resolve()), Promise.name, Promise.length, Promise.prototype.then.length, Promise.all.length);
  show('species', Promise[Symbol.species] === Promise);
  if (typeof Promise.allKeyed === 'function') {
    show('allKeyed', await Promise.allKeyed({ a: delayTick(1, 2), b: 2, [Symbol('s')]: 3 }));
    show('allSettledKeyed', await Promise.allSettledKeyed({ ok: 1, bad: rej('x') }));
    try { await Promise.allKeyed(5); } catch (e) { show('allKeyed-bad', e.name, e.message); }
    try { await Promise.allKeyed({ a: rej('kr') }); } catch (e) { show('allKeyed-reject', e); }
  }
})();
"""


def test_promise_combinators_and_statics(run):
    """CATCHES: Promise.all/allSettled/any/race/allKeyed with wrong settle order, AggregateError shape, non-iterable or bad-capability errors, withResolvers/try/finally semantics, self-resolution, thenable handling, subclassing and misuse TypeErrors."""
    _ok(run(["-e", PROG_PROMISE_COMBINATORS_AND_STATICS]), "promise_combinators_and_statics")


PROG_PROMISE_JOB_ORDERING = PRELUDE + r"""
const log = [];
const L = s => log.push(s);
setTimeout(() => L('timeout-1'), 0);
queueMicrotask(() => L('microtask-1'));
Promise.resolve().then(() => L('then-1')).then(() => L('then-1b')).then(() => L('then-1c'));
Promise.resolve().then(() => { L('then-2'); return Promise.resolve('x'); }).then(() => L('then-2-after-promise-return'));
Promise.resolve().then(() => { L('then-3'); return { then(r) { L('thenable-then-called'); r(); } }; }).then(() => L('then-3-after-thenable'));
(async () => { L('async-start'); await null; L('after-await-1'); await new Promise(r => r()); L('after-await-2'); })();
new Promise(r => { L('executor-sync'); r(); }).then(() => L('then-4'));
const p = Promise.reject(new Error('handled-later'));
p.catch(() => L('catch-handled'));
Promise.all([1, 2]).then(() => L('all-resolved'));
Promise.race([Promise.resolve('r')]).then(() => L('race-resolved'));
L('sync-end');
setTimeout(() => { L('timeout-2'); console.log(log.join('\n')); }, 0);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_promise_job_ordering(run, tier):
    """CATCHES: microtask/macrotask ordering bugs: thenable and promise-returning reactions needing extra ticks, await ticks, queueMicrotask vs then ordering, and timers running before the microtask queue drains."""
    _ok(run([*tier, "-e", PROG_PROMISE_JOB_ORDERING]), "promise_job_ordering")


PROG_PROMISE_COMBINATOR_ERROR_PATHS = PRELUDE + r"""
const out = [];
const L = (...a) => out.push(a.map(x => typeof x === 'string' ? x : fmt(x)).join(' '));
const settle = (label, p) => p.then(v => L(label, 'fulfilled', v), e => L(label, 'rejected', e && e.message !== undefined ? e.name + ': ' + e.message : e));
function iterLog(items, log) {
  let i = 0;
  return { [Symbol.iterator]() { return { next() { log.push('next'); return i < items.length ? { value: items[i++], done: false } : { done: true }; }, return() { log.push('return'); return {}; } }; } };
}
class Tricky extends Promise {
  static resolve(v) {
    if (v === 'bad-resolve') throw new Error('resolve threw');
    if (v === 'bad-then-getter') return { get then() { throw new Error('then getter threw'); } };
    if (v === 'bad-then-call') return { then() { throw new Error('then call threw'); } };
    return super.resolve(v);
  }
}
(async () => {
  for (const m of ['all', 'allSettled', 'any', 'race']) {
    for (const bad of ['bad-resolve', 'bad-then-getter', 'bad-then-call']) {
      const log = [];
      await settle(m + ' ' + bad, Tricky[m](iterLog([1, bad, 3], log)));
      L('  iter-log', log);
    }
    const log = [];
    await settle(m + ' next-throws', Promise[m]({ [Symbol.iterator]() { return { next() { log.push('next'); throw new Error('iterator next threw'); }, return() { log.push('return'); } }; } }));
    L('  iter-log', log);
    await settle(m + ' iterator-getter-throws', Promise[m]({ get [Symbol.iterator]() { throw new Error('@@iterator getter threw'); } }));
    await settle(m + ' non-object-this', (async () => Promise[m].call(1, []))());
    await settle(m + ' resolve-getter-throws', Promise[m].call(class extends Promise { static get resolve() { throw new Error('resolve getter'); } }, []));
  }
  // then via a species constructor that is not a native promise
  let captured;
  function NotNative(executor) { const self = this; executor(v => { captured = 'resolved:' + v; }, e => { captured = 'rejected:' + e; }); }
  const p = Promise.resolve('species-value');
  p.constructor = { [Symbol.species]: NotNative };
  const derived = p.then(x => x + '!');
  L('species-then-result', derived instanceof NotNative, derived instanceof Promise);
  await null; await null; await null; await null;
  L('species-captured', captured);
  const bad = Promise.resolve(1); bad.constructor = { [Symbol.species]: 5 };
  try { bad.then(); } catch (e) { L('species-bad', e.name + ': ' + e.message); }
  const undefSpecies = Promise.resolve(1); undefSpecies.constructor = { [Symbol.species]: undefined };
  L('species-undefined-default', undefSpecies.then() instanceof Promise);
  const ctorNotObj = Promise.resolve(1); ctorNotObj.constructor = 'str';
  try { ctorNotObj.then(); } catch (e) { L('constructor-not-object', e.name + ': ' + e.message); }
  // finally edge cases
  try { Promise.prototype.finally.call({ then: 5 }, () => {}); } catch (e) { L('finally-then-noncallable', e.name + ': ' + e.message); }
  L('finally-generic-thenable', Promise.prototype.finally.call({ then(a, b) { return 'then called with ' + typeof a + '/' + typeof b; } }, () => {}));
  L('finally-generic-noncallable-arg', Promise.prototype.finally.call({ then(a, b) { return [a, b]; } }, 7));
  await settle('finally-thenable-delay', Promise.resolve('orig').finally(() => ({ then(r) { r('ignored'); } })));
  // executor behaviour
  await settle('executor-throws', new Promise(() => { throw new RangeError('executor threw'); }));
  await settle('executor-throws-after-resolve', new Promise(r => { r('kept'); throw new Error('ignored'); }));
  await settle('executor-reject-then-resolve', new Promise((res, rej) => { rej('first'); res('second'); }));
  function NT() {}
  NT.prototype = 7;
  L('newtarget-nonobj-proto', Object.getPrototypeOf(Reflect.construct(Promise, [() => {}], NT)) === Promise.prototype);
  L('resolve-functions', (() => { let fns; new Promise((a, b) => { fns = [a, b]; }); return fns.map(f => [f.length, f.name, typeof f.prototype]); })());
  // resolve with thenables whose then is a getter / non-callable
  await settle('resolve-noncallable-then', Promise.resolve({ then: 'not callable', v: 1 }).then(x => x.v));
  await settle('resolve-thenable-rejects', Promise.resolve({ then(_, rj) { rj(new TypeError('thenable rejected')); } }));
  // keyed combinators
  if (typeof Promise.allKeyed === 'function') {
    await settle('allKeyed-nested', Promise.allKeyed({ a: Promise.resolve(1), b: { then(r) { r(2); } }, c: 3 }));
    await settle('allKeyed-empty', Promise.allKeyed({}));
    await settle('allKeyed-proto', Promise.allKeyed({}).then(o => Object.getPrototypeOf(o)));
    const neverSeen = Promise.reject('never'); neverSeen.catch(() => {});
    await settle('allKeyed-nonenum-skipped', Promise.allKeyed(Object.defineProperty({ v: 1 }, 'hidden', { value: neverSeen, enumerable: false })));
    await settle('allSettledKeyed-mixed', Promise.allSettledKeyed({ ok: Promise.resolve('y'), no: Promise.reject(new Error('n')) }).then(o => [o.ok, o.no.status, o.no.reason.message]));
    await settle('allKeyed-bad-resolve', Tricky.allKeyed({ a: 'bad-resolve' }));
    await settle('allKeyed-bad-then', Tricky.allKeyed({ a: 'bad-then-call' }));
    await settle('allKeyed-proxy', Promise.allKeyed(new Proxy({ x: 1, y: 2 }, { ownKeys: () => ['y', 'x'] })));
    await settle('allKeyed-getter-throws', Promise.allKeyed({ get g() { throw new Error('keyed getter'); } }));
  }
  // async generator return paths
  async function* ag() { try { yield 1; yield 2; } finally { L('ag finally'); } }
  const g1 = ag();
  await settle('ag-return-before-start', g1.return('early'));
  const g2 = ag(); await g2.next();
  await settle('ag-return-thenable', g2.return({ then(r) { r('from thenable'); } }));
  const g3 = ag();
  await settle('ag-return-rejected-promise', g3.return(Promise.reject(new Error('return arg rejected'))));
  const g4 = ag(); await g4.next();
  await settle('ag-return-rejected-mid', g4.return(Promise.reject(new Error('mid rejected'))));
  await settle('ag-next-after', g4.next());
  const g5 = ag();
  await settle('ag-throw-before-start', g5.throw(new Error('thrown in')));
  await settle('ag-queued', Promise.all([ag().next(), (() => { const g = ag(); return Promise.all([g.next(), g.next(), g.next(), g.return('done-q')]); })()]));
  const agProto = Object.getPrototypeOf(ag.prototype);
  await settle('ag-next-bad-this', agProto.next.call({}));
  await settle('ag-return-bad-this', agProto.return.call({}));
  await settle('ag-throw-bad-this', agProto.throw.call(1));
  L('ag-tags', Object.prototype.toString.call(ag()), Object.prototype.toString.call(ag), typeof agProto[Symbol.asyncIterator]);
  // Array.fromAsync remaining paths
  await settle('fromAsync-arraylike-mapfn', Array.fromAsync({ length: 2, 0: 'a', 1: Promise.resolve('b') }, async (v, i) => v + i));
  await settle('fromAsync-async-iter-nonobj', Array.fromAsync({ [Symbol.asyncIterator]() { return { next() { return 5; } }; } }));
  await settle('fromAsync-bad-asyncIterator', Array.fromAsync({ [Symbol.asyncIterator]: 5 }));
  await settle('fromAsync-mapfn-throws-closes', (() => { const lg = []; return Array.fromAsync({ [Symbol.asyncIterator]() { let n = 0; return { next() { return Promise.resolve({ value: n++, done: false }); }, return() { lg.push('closed'); return Promise.resolve({}); } }; } }, v => { if (v === 1) throw new Error('map fail'); return v; }).catch(e => [e.message, lg]); })());
  await settle('fromAsync-ctor-define-fails', Array.fromAsync.call(function () { return Object.freeze([]); }, [1]));
  await settle('fromAsync-arraylike-ctor', Array.fromAsync.call(function (n) { this.n = n; }, { length: 1, 0: 'v' }).then(o => [o.n, o.length, o[0]]));
  await settle('fromAsync-sync-iter-rejects-closes', (() => { const lg = []; const it = { [Symbol.iterator]() { let i = 0; return { next() { return { value: i++ === 0 ? Promise.reject(new Error('elem rejected')) : 1, done: false }; }, return() { lg.push('sync return'); return {}; } }; } }; return Array.fromAsync(it).catch(e => [e.message, lg]); })());
  console.log(out.join('\n'));
})();
"""


def test_promise_combinator_error_paths(run):
    """CATCHES: Promise combinators that fail to close the iterator (or close it wrongly) when resolve/then throws, mishandle iterator errors or bad receivers; then() through non-native species constructors; finally/executor edge cases; keyed combinators; async generator return/throw queueing; and Array.fromAsync error/closing paths."""
    _ok(run(["-e", PROG_PROMISE_COMBINATOR_ERROR_PATHS]), "promise_combinator_error_paths")


PROG_ERROR_OBJECTS = PRELUDE + r"""
const kinds = [Error, TypeError, RangeError, ReferenceError, SyntaxError, EvalError, URIError];
for (const K of kinds) {
  const e = new K('msg');
  const e2 = K('called');
  console.log(K.name, K.length, e.name, e.message, String(e), e2 instanceof K, Object.getPrototypeOf(K) === (K === Error ? Function.prototype : Error), Object.getPrototypeOf(K.prototype) === (K === Error ? Object.prototype : Error.prototype), Object.keys(e).length, Object.prototype.toString.call(e), K.prototype.name, JSON.stringify(K.prototype.message), Error.isError(e));
}
show('msg-desc', Object.getOwnPropertyDescriptor(new Error('m'), 'message'), Object.hasOwn(new Error(), 'message'), Object.hasOwn(new Error(undefined), 'message'));
show('msg-coerce', new Error(42).message, new Error(null).message, new Error({ toString() { return 'obj-msg'; } }).message, new Error('').message);
tryit('msg-symbol', () => new Error(Symbol()));
show('cause', new Error('c', { cause: 'why' }).cause, Object.getOwnPropertyDescriptor(new Error('c', { cause: 0 }), 'cause'), 'cause' in new Error('c', {}), 'cause' in new Error('c', { cause: undefined }), new Error('x', 'not-obj').cause);
const causeLog = [];
new Error('p', new Proxy({ cause: 1 }, { has(t, k) { causeLog.push('has:' + k); return k in t; }, get(t, k) { causeLog.push('get:' + k); return t[k]; } }));
show('cause-proxy', causeLog);
show('cause-inherited', new Error('i', Object.create({ cause: 'inherited cause' })).cause);
show('toString', Error.prototype.toString.call({ name: 'N', message: 'M' }), Error.prototype.toString.call({}), Error.prototype.toString.call({ name: '', message: 'only msg' }), Error.prototype.toString.call({ name: 'only name', message: '' }), Error.prototype.toString.call({ name: undefined, message: undefined }), Error.prototype.toString.call({ name: 5, message: null }));
tryit('toString-prim', () => Error.prototype.toString.call('str'));
show('custom-name', (() => { const e = new RangeError('r'); e.name = 'Custom'; return String(e); })(), (() => { const e = new Error('m'); e.message = 'changed'; return e.toString(); })());
const agg = new AggregateError([1, new Error('inner')], 'agg msg', { cause: 'agg cause' });
show('AggregateError', agg.name, agg.message, agg.errors.length, agg.errors[1].message, agg.cause, Array.isArray(agg.errors), Object.getOwnPropertyDescriptor(agg, 'errors').enumerable, AggregateError.length, Object.getPrototypeOf(AggregateError) === Error, String(agg));
show('AggregateError-iter', new AggregateError(new Set(['s1', 's2'])).errors, new AggregateError('ab').errors, AggregateError([]).message);
tryit('AggregateError-noniter', () => new AggregateError(5));
tryit('AggregateError-noargs', () => new AggregateError());
show('AggregateError-own-keys', Object.getOwnPropertyNames(new AggregateError([], 'm', { cause: 1 })));
const sup = new SuppressedError(new Error('primary'), new Error('suppressed one'), 'sup msg');
show('SuppressedError', sup.name, sup.message, sup.error.message, sup.suppressed.message, SuppressedError.length, Object.getOwnPropertyNames(sup), String(sup), SuppressedError('a', 'b').error, Object.getOwnPropertyDescriptor(sup, 'error').enumerable);
show('isError', Error.isError(new TypeError()), Error.isError({ __proto__: Error.prototype }), Error.isError(Object.create(Error.prototype)), Error.isError('Error'), Error.isError(new AggregateError([])), Error.isError(new (class E extends Error {})()), Error.isError(), Error.isError.length);
class HttpError extends Error {
  constructor(status, msg) { super(msg, { cause: { status } }); this.name = 'HttpError'; this.status = status; }
}
const he = new HttpError(404, 'not found');
show('subclass', he instanceof HttpError, he instanceof Error, String(he), he.cause, Object.keys(he), Error.isError(he), Object.prototype.toString.call(he));
const viaReflect = Reflect.construct(TypeError, ['reflected'], HttpError);
show('reflect-construct', viaReflect instanceof HttpError, viaReflect.name, viaReflect.message);
function NoProto() {}
NoProto.prototype = 5;
show('newtarget-bad-proto', Object.getPrototypeOf(Reflect.construct(RangeError, ['x'], NoProto)) === RangeError.prototype);
show('stack-type', typeof new Error('s').stack, new Error('first line').stack.split('\n')[0], Object.getOwnPropertyNames(new Error('x')).includes('stack'));
const stackDesc = Object.getOwnPropertyDescriptor(Error.prototype, 'stack');
show('stack-accessor', stackDesc ? [typeof stackDesc.get, typeof stackDesc.set, stackDesc.enumerable, stackDesc.configurable] : 'no accessor');
if (stackDesc) {
  show('stack-get-nonerror', stackDesc.get.call({}));
  tryit('stack-get-prim', () => stackDesc.get.call(1));
  tryit('stack-set-nonstring', () => { const e = new Error(); e.stack = 5; return e.stack; });
  show('stack-set-string', (() => { const e = new Error(); e.stack = 'custom stack'; return [e.stack, Object.getOwnPropertyDescriptor(e, 'stack').enumerable]; })());
  tryit('stack-set-on-proto', () => { Error.prototype.stack = 'x'; });
  tryit('stack-set-prim', () => stackDesc.set.call(1, 's'));
}
show('captureStackTrace', typeof Error.captureStackTrace);
if (typeof Error.captureStackTrace === 'function') {
  const target = {};
  Error.captureStackTrace(target);
  show('captured', typeof target.stack, Object.getOwnPropertyDescriptor(target, 'stack') !== undefined);
  tryit('capture-nonobj', () => Error.captureStackTrace(1));
}
show('native-errors-from-engine', (() => { try { null.x; } catch (e) { return [e.constructor === TypeError, e.name, Error.isError(e)]; } })(), (() => { try { undefinedVar; } catch (e) { return [e.name, e.message]; } })(), (() => { try { eval('1 +'); } catch (e) { return [e.name, e instanceof SyntaxError]; } })(), (() => { try { new Array(-1); } catch (e) { return e instanceof RangeError; } })());
if (stackDesc) {
  show('stack-name-variants', (() => { const e = new Error('m'); e.name = undefined; return e.stack.split('\n')[0]; })(), (() => { const e = new Error(); e.name = ''; e.message = 'only message'; return e.stack.split('\n')[0]; })(), (() => { const e = new TypeError(); return e.stack.split('\n')[0]; })(), (() => { const e = new Error('x'); e.message = undefined; return e.stack.split('\n')[0]; })());
  const plog = [];
  const errProxy = new Proxy(new Error('p'), { set(t, k, v, rcv) { plog.push('set ' + k); return Reflect.set(t, k, v); }, getOwnPropertyDescriptor(t, k) { plog.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, defineProperty(t, k, d) { plog.push('define ' + k); return Reflect.defineProperty(t, k, d); } });
  stackDesc.set.call(errProxy, 'via proxy');
  show('stack-set-proxy', plog);
  const plog2 = [];
  const plainProxy = new Proxy({}, { getOwnPropertyDescriptor(t, k) { plog2.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, defineProperty(t, k, d) { plog2.push('define ' + k + ' ' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); } });
  stackDesc.set.call(plainProxy, 'fresh');
  show('stack-define-proxy', plog2);
  tryit('stack-set-proxy-false', () => stackDesc.set.call(new Proxy(Object.defineProperty({}, 'stack', { value: 'x', writable: true, configurable: true }), { set: () => false }), 'nope'));
  tryit('stack-define-frozen', () => stackDesc.set.call(Object.freeze({}), 'frozen'));
  show('stack-set-own-existing', (() => { const o = { stack: 'old' }; stackDesc.set.call(o, 'new'); return o.stack; })());
  show('stack-set-no-proxy-trap', (() => { const t = { stack: 'old' }; stackDesc.set.call(new Proxy(t, {}), 'new2'); return t.stack; })());
}
function BadProto() {}
BadProto.prototype = 'not an object';
show('agg-newtarget-bad-proto', Object.getPrototypeOf(Reflect.construct(AggregateError, [[]], BadProto)) === AggregateError.prototype, Object.getPrototypeOf(Reflect.construct(SuppressedError, [1, 2], BadProto)) === SuppressedError.prototype);
show('suppressed-cause', new SuppressedError(1, 2, 'm', { cause: 'c' }).cause, Object.getOwnPropertyNames(new SuppressedError(1, 2, undefined, { cause: 0 })));
tryit('agg-message-symbol', () => new AggregateError([], Symbol()));
tryit('suppressed-message-throws', () => new SuppressedError(1, 2, { toString() { throw new RangeError('message coercion'); } }));
tryit('cause-getter-throws', () => new Error('x', { get cause() { throw new EvalError('cause getter'); } }));
"""


def test_error_objects(run):
    """CATCHES: native Error constructors with wrong prototype chains, message/cause property descriptors, toString rules, AggregateError/SuppressedError fields, Error.isError, subclass/new.target handling and the stack accessor/captureStackTrace."""
    _ok(run(["-e", PROG_ERROR_OBJECTS]), "error_objects")


PROG_DATE_PARSE_FORMAT_SETTERS = PRELUDE + r"""
const strs = ['2020-01-02', '2020-01-02T03:04:05', '2020-01-02T03:04:05Z', '2020-01-02T03:04:05.678Z', '2020-01-02T03:04:05.6789123Z', '2020-01-02T03:04:05.6Z', '2020-01-02T03:04:05+05:30', '2020-01-02T03:04:05-0800', '2020-01-02T03:04Z', '2020-01-02T03Z', '2020-01', '2020', '+002020-01-01T00:00:00Z', '-000001-01-01T00:00:00Z', '-000000-01-01T00:00:00Z', '+275760-09-13T00:00:00Z', '+275760-09-13T00:00:00.001Z', '-271821-04-20T00:00:00Z', '-271821-04-19T23:59:59.999Z', '2020-13-01', '2020-02-30', '2020-00-10', '2020-01-02T24:00:00Z', '2020-01-02T25:00:00Z', '2020-01-02T12:60:00Z', '20-01-02', '2020-1-2', '2020-01-02 03:04:05', '2020-01-02 3:4:5', '2020-01-02T', '2020-01-02T03:04:05.Z', ' 2020-01-02 ', 'Thu, 01 Jan 1970 00:00:00 GMT', 'Tue, 02 Jan 2024 10:20:30 GMT', 'Jan 2 2024', 'January 2, 2024 10:20:30', '2 Jan 2024 10:20 GMT+0200', 'Tue Jan 02 2024 10:20:30 GMT-0500 (EST)', 'Mon, 31 Dec 1999 23:59:59 +0100', 'Dec 25, 1995', 'garbage', '', '12/25/2020', '2020/12/25', 'Sat Jan 01 2000', '1970-01-01T00:00:00.000+00:00'];
for (const s of strs) {
  const t = Date.parse(s);
  console.log('parse', JSON.stringify(s), t, isNaN(t) ? '-' : new Date(t).toISOString());
}
show('ctor-forms', new Date(0).getTime(), new Date('1970-01-01').getTime(), new Date(2020, 0).getTime(), new Date(2020, 0, 31, 23, 59, 59, 999).getTime(), new Date(99, 0).getFullYear(), new Date(0, 0).getFullYear(), new Date(100, 0).getFullYear(), new Date(-1, 0).getFullYear(), new Date(2020, 12, 1).getMonth(), new Date(2020, -1).toISOString(), new Date(2020, 1, 29.9).getDate());
show('ctor-coerce', new Date('0').getTime(), new Date(true).getTime(), new Date(null).getTime(), new Date(new Date(5)).getTime(), new Date({ valueOf() { return 77; } }).getTime(), new Date({ toString() { return '1970-01-02'; }, valueOf: undefined }).getTime(), new Date(1.9).getTime(), new Date(-1.9).getTime(), new Date([2020]).getTime());
show('ctor-invalid', new Date(NaN).getTime(), new Date(8.64e15).getTime(), new Date(8.64e15 + 1).getTime(), new Date(-8.64e15).getTime(), new Date(undefined).getTime(), new Date(2020, NaN).getTime(), new Date(Infinity).getTime(), String(new Date(NaN)));
tryit('ctor-symbol', () => new Date(Symbol()));
show('typeof-call', typeof Date(), typeof Date(0), Date.length, Date.name);
show('UTC', Date.UTC(2020), Date.UTC(2020, 1), Date.UTC(2020, 1, 29), Date.UTC(99, 11, 31), Date.UTC(1e6), Date.UTC(), Date.UTC(2020, 0, 1, 25, 61, 61, 1001), Date.UTC(-1, 0), Date.UTC(275760, 8, 13), Date.UTC(275760, 8, 13, 0, 0, 0, 1), Date.UTC(2020, 0, 0), Date.UTC(1970, 0, 1, 0, 0, 0, -1), Date.UTC(NaN), Date.UTC(2020.7, 0.9), Date.UTC(0));
const d = new Date(Date.UTC(2024, 1, 29, 13, 45, 30, 123));
show('getters', d.getFullYear(), d.getMonth(), d.getDate(), d.getDay(), d.getHours(), d.getMinutes(), d.getSeconds(), d.getMilliseconds(), d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCDay(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds(), d.getTimezoneOffset(), d.getYear(), d.getTime(), d.valueOf());
show('formats', d.toString(), d.toDateString(), d.toTimeString(), d.toUTCString(), d.toISOString(), d.toJSON(), d.toGMTString === d.toUTCString || d.toGMTString === Date.prototype.toUTCString);
show('formats-old', new Date(Date.UTC(-50, 0, 1)).toISOString(), new Date(Date.UTC(-50, 0, 1)).toString(), new Date(Date.UTC(-50, 0, 1)).toUTCString(), new Date(Date.UTC(12345, 5, 6)).toISOString(), new Date(Date.UTC(12345, 5, 6)).toUTCString(), new Date(Date.UTC(5, 0, 1) - 62135596800000 * 0).getUTCFullYear(), new Date(-62198755200000).toISOString(), new Date(-62198755200000).toString());
const inv = new Date(NaN);
show('invalid-formats', inv.toString(), inv.toDateString(), inv.toTimeString(), inv.toUTCString(), inv.toJSON(), inv.getFullYear(), inv.getDay(), inv.getTimezoneOffset());
tryit('invalid-toISOString', () => inv.toISOString());
show('toJSON-generic', Date.prototype.toJSON.call({ toISOString() { return 'custom-iso'; } }), Date.prototype.toJSON.call({ valueOf() { return Infinity; }, toISOString() { return 'never'; } }));
tryit('toJSON-noniso', () => Date.prototype.toJSON.call({}));
const s = new Date(Date.UTC(2020, 0, 31, 10, 0, 0));
show('setMonth-overflow', new Date(s).setMonth(1), new Date(new Date(s).setMonth(1)).toISOString());
const m = new Date(0);
show('setters', m.setFullYear(2021, 5, 15), m.setMonth(0), m.setDate(0), m.toISOString(), m.setHours(25, 70, 70, 1500), m.toISOString(), m.setMinutes(-1), m.setSeconds(3600), m.setMilliseconds(-1), m.toISOString(), m.setTime(86400000), m.setTime('x'), m.getTime());
const u = new Date(0);
show('utc-setters', u.setUTCFullYear(2000), u.setUTCMonth(11, 31), u.setUTCDate(1), u.setUTCHours(23), u.setUTCMinutes(59, 59, 999), u.setUTCSeconds(0), u.setUTCMilliseconds(5), u.toISOString());
const nan = new Date(NaN);
show('set-on-invalid', nan.setDate(1), nan.setHours(1), nan.setFullYear(2020), new Date(nan.getTime()).toISOString(), new Date(NaN).setUTCFullYear(1999, 1), new Date(NaN).setMilliseconds(5));
show('set-nan-arg', new Date(0).setFullYear(NaN), new Date(0).setMonth(), new Date(0).setUTCHours(undefined));
const y = new Date(0);
show('setYear', y.setYear(95), y.getFullYear(), y.setYear(2005), y.getYear(), y.setYear(NaN), new Date(NaN).setYear(99));
show('setter-arg-coercion-order', (() => { const log = []; const dd = new Date(NaN); dd.setHours({ valueOf() { log.push('h'); return 1; } }, { valueOf() { log.push('m'); return 2; } }); return log; })());
show('setter-returns', (() => { const dd = new Date(0); const r = dd.setUTCHours(1); return r === dd.getTime(); })());
tryit('getTime-nondate', () => Date.prototype.getTime.call({}));
tryit('setTime-nondate', () => Date.prototype.setTime.call(Object.create(Date.prototype), 1));
tryit('toISOString-nondate', () => Date.prototype.toISOString.call(1));
tryit('toString-nondate', () => Date.prototype.toString.call({}));
show('toPrimitive', new Date(0)[Symbol.toPrimitive]('number'), new Date(0)[Symbol.toPrimitive]('default'), new Date(0)[Symbol.toPrimitive]('string'), new Date(0) + 1, new Date(5) - 1, `${new Date(0)}` === new Date(0).toString(), new Date(5) == 5, new Date(0) < new Date(1));
tryit('toPrimitive-bad-hint', () => new Date(0)[Symbol.toPrimitive]('bogus'));
tryit('toPrimitive-bad-this', () => Date.prototype[Symbol.toPrimitive].call(1, 'number'));
show('date-subclass', (() => { class D extends Date { y() { return this.getUTCFullYear(); } } const x = new D(0); return [x.y(), x instanceof Date, Object.prototype.toString.call(x)]; })());
show('locale-basic', typeof new Date(0).toLocaleString(), typeof new Date(0).toLocaleDateString(), typeof new Date(0).toLocaleTimeString(), new Date(NaN).toLocaleString());
show('now-type', typeof Date.now(), Date.now() > 1.6e12, Number.isInteger(Date.now()));
for (const s of ['2020-01-02 03:04:05+0530', '2020-01-02 03:04 +05', '2020-01-02 03:04:05-08', '2020-01-02 03:04:05+5', '2020-01-02T03:04:05+05', '2020-01-02 003:04', '2020-01-02 03:04:05.', '2020-01-02 03:04:05.12x', '2020-01-02T03:04:05+05:3', '2020-01-02T03:04:05+0a:00', '2020-01-02 1:2', '2020-1-2 3:4', 'Jan 2 2024 10:20:30 +0530', '10 Feb 15', 'Feb 15 10 2020', '2024 March 3', '+2020-01-01', '2020-01-0x', '2020-ab-01']) {
  const t = Date.parse(s);
  console.log('parse2', JSON.stringify(s), t, isNaN(t) ? '-' : new Date(t).toISOString());
}
show('locale-invalid', new Date(NaN).toLocaleDateString(), new Date(NaN).toLocaleTimeString());
tryit('toPrimitive-no-primitive', () => Date.prototype[Symbol.toPrimitive].call({ toString() { return {}; }, valueOf() { return {}; } }, 'number'));
tryit('toPrimitive-hint-nonstring', () => new Date(0)[Symbol.toPrimitive](1));
show('toPrimitive-generic', Date.prototype[Symbol.toPrimitive].call({ valueOf() { return 42; }, toString() { return 'str'; } }, 'default'), Date.prototype[Symbol.toPrimitive].call({ valueOf() { return 42; }, toString() { return 'str'; } }, 'number'));
tryit('ctor-proxy-of-date', () => new Date(new Proxy(new Date(7), {})).getTime());
show('ctor-string-object', new Date(new String('1970-01-01T00:00:01Z')).getTime());
"""


def test_date_parse_format_setters(run):
    """CATCHES: Date parsing of ISO/RFC-2822/legacy strings and range limits, constructor coercion and two-digit years, Date.UTC edge cases, getters in UTC, toString/toUTCString/toISOString/toJSON formats, invalid-date handling, setter overflow/NaN rules and Date misuse TypeErrors."""
    _ok(run(["-e", PROG_DATE_PARSE_FORMAT_SETTERS]), "date_parse_format_setters")


PROG_PROXY_TRAPS_AND_INVARIANTS = PRELUDE + r"""
const log = [];
const handler = {};
for (const trap of ['get', 'set', 'has', 'deleteProperty', 'ownKeys', 'getOwnPropertyDescriptor', 'defineProperty', 'getPrototypeOf', 'setPrototypeOf', 'isExtensible', 'preventExtensions', 'apply', 'construct']) {
  handler[trap] = function (...args) {
    log.push(trap + '(' + args.slice(1).map(a => typeof a === 'symbol' ? a.toString() : typeof a === 'function' ? 'fn' : (a && typeof a === 'object') ? (Array.isArray(a) ? '[' + a.join(',') + ']' : '{' + Object.keys(a).join(',') + '}') : String(a)).join(';') + ')');
    return Reflect[trap](...args);
  };
}
const target = function T(a, b) { if (new.target) { this.made = a; } return a + b; };
target.prop = 1;
const p = new Proxy(target, handler);
const step = (label, f) => { log.length = 0; let r; try { r = fmt(f()); } catch (e) { r = 'THROW ' + e.name + ': ' + e.message; } console.log(label, '=>', r, '::', log.join(' ')); };
step('get', () => p.prop);
step('get-sym', () => p[Symbol.toStringTag]);
step('set', () => { p.prop = 2; return target.prop; });
step('has', () => 'prop' in p);
step('delete', () => delete p.prop);
step('defineProperty', () => Object.defineProperty(p, 'x', { value: 1, configurable: true }) === p);
step('gopd', () => Object.getOwnPropertyDescriptor(p, 'x'));
step('ownKeys', () => Object.keys(p));
step('getOwnPropertyNames', () => Object.getOwnPropertyNames(p).length);
step('getPrototypeOf', () => Object.getPrototypeOf(p) === Function.prototype);
step('setPrototypeOf', () => Object.setPrototypeOf(p, Function.prototype) === p);
step('isExtensible', () => Object.isExtensible(p));
step('apply', () => p(1, 2));
step('call', () => p.call(null, 3, 4));
step('construct', () => new p(5, 6).made);
step('instanceof', () => ({}) instanceof p);
step('for-in', () => { const ks = []; for (const k in p) ks.push(k); return ks; });
step('spread', () => ({ ...p }));
step('hasOwn', () => Object.hasOwn(p, 'x'));
step('preventExtensions', () => Object.isExtensible(Object.preventExtensions(p)));
step('typeof', () => typeof p + '/' + typeof new Proxy({}, {}) + '/' + typeof new Proxy(class {}, {}));
step('in-with-proto-chain', () => 'missing' in Object.create(new Proxy({}, handler)));
step('set-via-proto', () => { const child = Object.create(new Proxy({}, handler)); child.q = 1; return Object.keys(child); });
// invariants
const frozenT = Object.freeze({ fixed: 1 });
const lie = (traps) => new Proxy(frozenT, traps);
const inv = (label, f) => { try { console.log('inv', label, fmt(f())); } catch (e) { console.log('inv', label, e.name + ': ' + e.message); } };
inv('get-nonwritable', () => lie({ get: () => 2 }).fixed);
inv('get-same-ok', () => lie({ get: () => 1 }).fixed);
inv('set-nonwritable', () => Reflect.set(lie({ set: () => true }), 'fixed', 5));
inv('has-nonconfig', () => 'fixed' in lie({ has: () => false }));
inv('has-nonext', () => 'zzz' in new Proxy(Object.preventExtensions({ zzz: 1 }), { has: () => false }));
inv('delete-nonconfig', () => Reflect.deleteProperty(lie({ deleteProperty: () => true }), 'fixed'));
inv('delete-false-strict', () => { 'use strict'; return delete new Proxy({ a: 1 }, { deleteProperty: () => false }).a; });
inv('ownKeys-missing', () => Reflect.ownKeys(lie({ ownKeys: () => [] })));
inv('ownKeys-extra-nonext', () => Reflect.ownKeys(lie({ ownKeys: () => ['fixed', 'extra'] })));
inv('ownKeys-dupes', () => Reflect.ownKeys(new Proxy({}, { ownKeys: () => ['a', 'a'] })));
inv('ownKeys-nonstring', () => Reflect.ownKeys(new Proxy({}, { ownKeys: () => [1] })));
inv('ownKeys-nonarray', () => Reflect.ownKeys(new Proxy({}, { ownKeys: () => 5 })));
inv('ownKeys-arraylike', () => Reflect.ownKeys(new Proxy({}, { ownKeys: () => ({ length: 2, 0: 'b', 1: 'a' }) })));
inv('gopd-nonobj', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: () => 5 }), 'a'));
inv('gopd-undef-nonconfig', () => Object.getOwnPropertyDescriptor(lie({ getOwnPropertyDescriptor: () => undefined }), 'fixed'));
inv('gopd-config-mismatch', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: () => ({ value: 1, configurable: false }) }), 'a'));
inv('gopd-ok', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: () => ({ value: 1, configurable: true }) }), 'a'));
inv('defineProperty-false', () => Object.defineProperty(new Proxy({}, { defineProperty: () => false }), 'a', { value: 1 }));
inv('defineProperty-false-reflect', () => Reflect.defineProperty(new Proxy({}, { defineProperty: () => false }), 'a', { value: 1 }));
inv('defineProperty-nonext', () => Object.defineProperty(lie({ defineProperty: () => true }), 'newkey', { value: 1 }));
inv('defineProperty-nonconfig-missing', () => Object.defineProperty(new Proxy({}, { defineProperty: () => true }), 'a', { value: 1, configurable: false }));
inv('getPrototypeOf-nonobj', () => Object.getPrototypeOf(new Proxy({}, { getPrototypeOf: () => 5 })));
inv('getPrototypeOf-nonext-mismatch', () => Object.getPrototypeOf(lie({ getPrototypeOf: () => Array.prototype })));
inv('setPrototypeOf-false', () => Object.setPrototypeOf(new Proxy({}, { setPrototypeOf: () => false }), null));
inv('setPrototypeOf-false-reflect', () => Reflect.setPrototypeOf(new Proxy({}, { setPrototypeOf: () => false }), null));
inv('setPrototypeOf-nonext-mismatch', () => Reflect.setPrototypeOf(lie({ setPrototypeOf: () => true }), null));
inv('isExtensible-mismatch', () => Object.isExtensible(new Proxy({}, { isExtensible: () => false })));
inv('preventExtensions-lie', () => Object.preventExtensions(new Proxy({}, { preventExtensions: () => true })));
inv('apply-nonfn-target', () => new Proxy({}, { apply: () => 1 })());
inv('construct-nonobj-result', () => new (new Proxy(function () {}, { construct: () => 1 }))());
inv('construct-nonctor-target', () => new (new Proxy(() => {}, { construct: () => ({}) }))());
inv('trap-noncallable', () => new Proxy({}, { get: 5 }).x);
inv('trap-null-passthrough', () => new Proxy({ v: 'through' }, { get: null }).v);
inv('trap-getter-handler', () => new Proxy({ v: 1 }, { get get() { return () => 'from getter trap'; } }).v);
inv('ctor-nonobj', () => new Proxy(1, {}));
inv('ctor-nonobj-handler', () => new Proxy({}, null));
inv('ctor-no-new', () => Proxy({}, {}));
inv('proxy-proto', () => [Proxy.prototype, Proxy.length, Proxy.name, typeof Proxy.revocable]);
// revocable
const { proxy: rp, revoke } = Proxy.revocable({ a: 1 }, {});
inv('revocable-before', () => rp.a);
revoke(); revoke();
inv('revoked-get', () => rp.a);
inv('revoked-set', () => { rp.a = 2; });
inv('revoked-has', () => 'a' in rp);
inv('revoked-keys', () => Object.keys(rp));
inv('revoked-typeof', () => typeof rp);
inv('revoked-isArray', () => Array.isArray(Proxy.revocable([], {}).proxy) && (() => { const r = Proxy.revocable([], {}); r.revoke(); return Array.isArray(r.proxy); })());
inv('revoked-as-target', () => new Proxy(rp, {}));
inv('revoked-as-handler', () => new Proxy({}, rp));
inv('revoke-fn', () => [revoke.name, revoke.length]);
// proxy of array
const arrP = new Proxy([1, 2, 3], {});
inv('array-proxy', () => [Array.isArray(arrP), arrP.length, JSON.stringify(arrP), arrP.map(x => x * 2), Object.prototype.toString.call(arrP), [].concat(arrP).length]);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_proxy_traps_and_invariants(run, tier):
    """CATCHES: proxies that skip or misorder trap calls (including the get/set/defineProperty chain of [[Set]]), fail to enforce the trap invariants with TypeErrors, mishandle revocation, or treat array/function targets incorrectly."""
    _ok(run([*tier, "-e", PROG_PROXY_TRAPS_AND_INVARIANTS]), "proxy_traps_and_invariants")


PROG_PROXY_FORWARDING_AND_DESCRIPTOR_INVARIANTS = PRELUDE + r"""
const r = (label, f) => { try { console.log(label, fmt(f())); } catch (e) { console.log(label, 'THROW', e.name + ': ' + e.message); } };
// 1. Forwarding through a chain of trap-less proxies (proxy whose target is a proxy).
const base = { a: 1, [Symbol.for('s')]: 2 };
Object.defineProperty(base, 'hidden', { value: 3, enumerable: false, configurable: true });
const inner = new Proxy(base, {});
const outer = new Proxy(inner, {});
r('chain-get', () => [outer.a, outer.hidden, 'a' in outer, Reflect.has(outer, 'zz')]);
r('chain-ownKeys', () => Reflect.ownKeys(outer));
r('chain-keys/values/entries', () => [Object.keys(outer), Object.values(outer), Object.entries(outer)]);
r('chain-gopd', () => Object.getOwnPropertyDescriptor(outer, 'hidden'));
r('chain-gopds', () => Object.keys(Object.getOwnPropertyDescriptors(outer)));
r('chain-define', () => [Reflect.defineProperty(outer, 'b', { value: 'B', enumerable: true, configurable: true, writable: true }), base.b]);
r('chain-set', () => [Reflect.set(outer, 'c', 'C'), base.c, Object.getOwnPropertyDescriptor(base, 'c').enumerable]);
r('chain-delete', () => [delete outer.c, 'c' in base]);
r('chain-proto', () => [Object.getPrototypeOf(outer) === Object.prototype, Reflect.setPrototypeOf(outer, null), Object.getPrototypeOf(base)]);
r('chain-extensible', () => [Object.isExtensible(outer), Reflect.preventExtensions(outer), Object.isExtensible(base)]);
r('chain-frozen', () => [Object.isFrozen(outer), Object.isSealed(outer), Object.freeze(outer) === outer, Object.isFrozen(base)]);
r('chain-hasOwnProperty', () => [Object.prototype.hasOwnProperty.call(outer, 'a'), Object.prototype.propertyIsEnumerable.call(outer, 'hidden'), Object.prototype.propertyIsEnumerable.call(outer, 'a')]);
r('chain-names/symbols', () => [Object.getOwnPropertyNames(outer), Object.getOwnPropertySymbols(outer).map(String)]);
r('chain-assign', () => Object.assign({}, outer));
r('chain-json', () => JSON.stringify(outer));
const fnChain = new Proxy(new Proxy(function (x) { return 'called ' + x; }, {}), {});
r('chain-call', () => [fnChain(1), new (new Proxy(new Proxy(class K { constructor() { this.k = 1; } }, {}), {}))().k]);
r('isArray-chain', () => Array.isArray(new Proxy(new Proxy([], {}), {})));
// 2. Non-callable traps for every trap name.
for (const trap of ['get', 'set', 'has', 'deleteProperty', 'ownKeys', 'getOwnPropertyDescriptor', 'defineProperty', 'getPrototypeOf', 'setPrototypeOf', 'isExtensible', 'preventExtensions', 'apply', 'construct']) {
  const p = new Proxy(function () {}, { [trap]: 'not callable' });
  const ops = { get: () => p.x, set: () => { p.x = 1; }, has: () => 'x' in p, deleteProperty: () => delete p.x, ownKeys: () => Reflect.ownKeys(p), getOwnPropertyDescriptor: () => Object.getOwnPropertyDescriptor(p, 'x'), defineProperty: () => Object.defineProperty(p, 'x', { value: 1 }), getPrototypeOf: () => Object.getPrototypeOf(p), setPrototypeOf: () => Object.setPrototypeOf(p, null), isExtensible: () => Object.isExtensible(p), preventExtensions: () => Object.preventExtensions(p), apply: () => p(), construct: () => new p() };
  r('noncallable-' + trap, ops[trap]);
}
// 3. Revoked proxies through every Reflect operation.
for (const op of ['get', 'set', 'has', 'deleteProperty', 'ownKeys', 'getOwnPropertyDescriptor', 'defineProperty', 'getPrototypeOf', 'setPrototypeOf', 'isExtensible', 'preventExtensions', 'apply', 'construct']) {
  const { proxy, revoke } = Proxy.revocable(function () {}, {});
  revoke();
  const args = { get: [proxy, 'x'], set: [proxy, 'x', 1], has: [proxy, 'x'], deleteProperty: [proxy, 'x'], ownKeys: [proxy], getOwnPropertyDescriptor: [proxy, 'x'], defineProperty: [proxy, 'x', {}], getPrototypeOf: [proxy], setPrototypeOf: [proxy, null], isExtensible: [proxy], preventExtensions: [proxy], apply: [proxy, null, []], construct: [proxy, []] }[op];
  r('revoked-' + op, () => Reflect[op](...args));
}
// 4. Boolean traps returning false.
const falsy = new Proxy({ x: 1 }, { set: () => false, deleteProperty: () => 0, defineProperty: () => '', setPrototypeOf: () => null, preventExtensions: () => false, has: () => false });
r('false-set-reflect', () => Reflect.set(falsy, 'x', 2));
r('false-set-strict', () => { 'use strict'; falsy.x = 2; });
r('false-set-sloppy', () => { falsy.x = 2; return 'no throw'; });
r('false-delete', () => [Reflect.deleteProperty(falsy, 'x'), delete falsy.x]);
r('false-delete-strict', () => { 'use strict'; delete falsy.x; });
r('false-define', () => Reflect.defineProperty(falsy, 'y', { value: 1 }));
r('false-setProto', () => Reflect.setPrototypeOf(falsy, null));
r('false-pe', () => Reflect.preventExtensions(falsy));
r('false-has-with', () => [Reflect.has(falsy, 'x'), 'x' in falsy]);
// 5. getOwnPropertyDescriptor trap invariants.
const g1 = function g1() {}, s1 = function s1(v) {}, other = function other() {};
const T = {};
Object.defineProperty(T, 'ncData', { value: 1, writable: false, enumerable: true, configurable: false });
Object.defineProperty(T, 'ncWritable', { value: 1, writable: true, enumerable: false, configurable: false });
Object.defineProperty(T, 'ncAcc', { get: g1, set: s1, enumerable: false, configurable: false });
Object.defineProperty(T, 'cfg', { value: 1, writable: true, enumerable: true, configurable: true });
const gopd = (key, desc) => r('gopd ' + key + ' ' + JSON.stringify(desc, (k, v) => typeof v === 'function' ? v.name : v), () => Object.getOwnPropertyDescriptor(new Proxy(T, { getOwnPropertyDescriptor: () => desc }), key));
gopd('ncData', { value: 1, configurable: true });
gopd('ncData', { value: 1, configurable: false, enumerable: false });
gopd('ncData', { get: g1, configurable: false, enumerable: true });
gopd('ncData', { value: 1, writable: true, configurable: false, enumerable: true });
gopd('ncData', { value: 2, configurable: false, enumerable: true });
gopd('ncData', { value: 1, writable: false, configurable: false, enumerable: true });
gopd('ncAcc', { get: other, configurable: false, enumerable: false });
gopd('ncAcc', { get: g1, set: other, configurable: false, enumerable: false });
gopd('ncAcc', { value: 1, configurable: false, enumerable: false });
gopd('ncAcc', { get: g1, set: s1, configurable: false, enumerable: false });
gopd('cfg', { value: 1, configurable: false, enumerable: true });
gopd('ncWritable', { value: 1, writable: false, configurable: false, enumerable: false });
gopd('ncWritable', { value: 5, writable: true, configurable: false, enumerable: false });
r('gopd-undefined-for-nonext', () => Object.getOwnPropertyDescriptor(new Proxy(Object.preventExtensions({ cfg: 1 }), { getOwnPropertyDescriptor: () => undefined }), 'cfg'));
r('gopd-new-on-nonext', () => Object.getOwnPropertyDescriptor(new Proxy(Object.preventExtensions({}), { getOwnPropertyDescriptor: () => ({ value: 1, configurable: true }) }), 'nope'));
r('gopd-undefined-ok', () => Object.getOwnPropertyDescriptor(new Proxy({ cfg: 1 }, { getOwnPropertyDescriptor: () => undefined }), 'cfg'));
r('gopd-desc-getter-fields', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: () => ({ get value() { return 'from getter'; }, configurable: true, enumerable: 1 }) }), 'v'));
r('gopd-bad-desc', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: () => ({ get: 5, configurable: true }) }), 'v'));
r('gopd-mixed-desc', () => Object.getOwnPropertyDescriptor(new Proxy({}, { getOwnPropertyDescriptor: () => ({ get() {}, value: 1, configurable: true }) }), 'v'));
// 6. defineProperty trap invariants (trap reports success).
const def = (key, desc) => r('define ' + key + ' ' + JSON.stringify(desc, (k, v) => typeof v === 'function' ? v.name : v), () => Reflect.defineProperty(new Proxy(T, { defineProperty: () => true }), key, desc));
def('cfg', { value: 1, configurable: false });
def('ncData', { configurable: true });
def('ncData', { enumerable: false });
def('ncData', { get: g1 });
def('ncData', { writable: true });
def('ncData', { value: 2 });
def('ncData', { value: 1, writable: false });
def('ncAcc', { get: other });
def('ncAcc', { set: other });
def('ncAcc', { value: 1 });
def('ncAcc', { get: g1, set: s1 });
def('ncWritable', { writable: false, configurable: false });
def('ncWritable', { value: 9 });
def('missing', { value: 1 });
r('define-trap-desc-arg', () => { let seen; Reflect.defineProperty(new Proxy({}, { defineProperty(t, k, d) { seen = [k, d, Object.getPrototypeOf(d) === Object.prototype]; return true; } }), 'k', { get: g1, enumerable: false, extra: 'dropped' }); return seen; });
// 7. ownKeys invariants for non-extensible target with configurable keys.
const nonext = Object.preventExtensions({ a: 1, b: 2 });
r('ownKeys-omit-config-nonext', () => Reflect.ownKeys(new Proxy(nonext, { ownKeys: () => ['a'] })));
r('ownKeys-exact-nonext', () => Reflect.ownKeys(new Proxy(nonext, { ownKeys: () => ['b', 'a'] })));
r('ownKeys-symbol-ok', () => Reflect.ownKeys(new Proxy({}, { ownKeys: () => [Symbol.iterator, 'z'] })).map(String));
r('ownKeys-for-in', () => { const ks = []; for (const k in new Proxy({ x: 1, y: 2 }, { ownKeys: () => ['y', 'x', 'ghost'] })) ks.push(k); return ks; });
r('values-entries-trap-order', () => { const log = []; const p = new Proxy({ a: 1, b: 2 }, { ownKeys(t) { log.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor(t, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, get(t, k) { log.push('get ' + String(k)); return t[k]; } }); return [Object.entries(p), Object.values(p), log]; });
// 8. getPrototypeOf / isExtensible / preventExtensions success paths.
r('proto-trap-ok', () => Object.getPrototypeOf(new Proxy({}, { getPrototypeOf: () => Array.prototype })) === Array.prototype);
r('proto-instanceof', () => new Proxy({}, { getPrototypeOf: () => Array.prototype }) instanceof Array);
r('proto-isPrototypeOf', () => Array.prototype.isPrototypeOf(new Proxy({}, { getPrototypeOf: () => Array.prototype })));
r('pe-trap-ok', () => { const t = {}; return [Reflect.preventExtensions(new Proxy(t, { preventExtensions(tt) { Object.preventExtensions(tt); return true; } })), Object.isExtensible(t)]; });
r('setProto-trap-ok-nonext-same', () => { const t = Object.preventExtensions({}); return Reflect.setPrototypeOf(new Proxy(t, { setPrototypeOf: () => true }), Object.prototype); });
r('isExtensible-trap-truthy', () => Object.isExtensible(new Proxy({}, { isExtensible: () => 1 })));
"""


def test_proxy_forwarding_and_descriptor_invariants(run):
    """CATCHES: trap-less proxy chains that stop forwarding, missing TypeErrors for non-callable traps or revoked proxies, falsy trap results, and every getOwnPropertyDescriptor/defineProperty/ownKeys invariant check (non-configurable, non-writable, accessor identity, non-extensible targets)."""
    _ok(run(["-e", PROG_PROXY_FORWARDING_AND_DESCRIPTOR_INVARIANTS]), "proxy_forwarding_and_descriptor_invariants")


PROG_REFLECT_API = PRELUDE + r"""
const o = { a: 1, get g() { return this.tag; }, set s(v) { this.written = v; } };
show('get', Reflect.get(o, 'a'), Reflect.get(o, 'g', { tag: 'receiver' }), Reflect.get([5, 6], 1), Reflect.get(o, 'missing'));
const recv = {};
show('set', Reflect.set(o, 'a', 2), o.a, Reflect.set(o, 's', 'v', recv), recv.written, o.written);
show('set-receiver-data', (() => { const r = {}; const ok = Reflect.set({ x: 1 }, 'x', 9, r); return [ok, r]; })());
show('set-receiver-nonwritable', (() => { const r = Object.defineProperty({}, 'x', { value: 0, writable: false, configurable: true }); return Reflect.set({ x: 1 }, 'x', 9, r); })());
show('set-receiver-accessor', (() => { const r = { set x(v) {} }; return Reflect.set({ x: 1 }, 'x', 9, r); })());
show('set-receiver-prim', Reflect.set({ x: 1 }, 'x', 9, 5));
show('set-frozen', Reflect.set(Object.freeze({ x: 1 }), 'x', 2), Reflect.set(Object.freeze({}), 'y', 2), Reflect.set(Object.freeze([]), 'length', 0));
show('set-getter-only', Reflect.set({ get x() { return 1; } }, 'x', 2));
show('set-inherited-nonwritable', Reflect.set(Object.create(Object.freeze({ x: 1 })), 'x', 2));
show('set-array-length', (() => { const a = [1, 2, 3]; return [Reflect.set(a, 'length', 1), a]; })());
show('has', Reflect.has(o, 'a'), Reflect.has(o, 'toString'), Reflect.has([], 'length'), Reflect.has([1], 0));
show('deleteProperty', Reflect.deleteProperty({ a: 1 }, 'a'), Reflect.deleteProperty(Object.freeze({ a: 1 }), 'a'), Reflect.deleteProperty({}, 'nothing'), Reflect.deleteProperty([1], 'length'));
show('defineProperty', Reflect.defineProperty({}, 'x', { value: 1 }), Reflect.defineProperty(Object.freeze({}), 'x', { value: 1 }), Reflect.defineProperty(Object.defineProperty({}, 'x', { value: 1 }), 'x', { value: 2 }));
show('gopd', Reflect.getOwnPropertyDescriptor({ a: 1 }, 'a'), Reflect.getOwnPropertyDescriptor({}, 'a'));
show('ownKeys', Reflect.ownKeys({ b: 1, 1: 1, [Symbol.iterator]: 1, a: 1 }), Reflect.ownKeys([1, 2]), Reflect.ownKeys(function f(x) {}));
show('protos', Reflect.getPrototypeOf([]) === Array.prototype, Reflect.setPrototypeOf({}, null), Reflect.setPrototypeOf(Object.preventExtensions({}), {}), Reflect.isExtensible({}), Reflect.preventExtensions({}), Reflect.isExtensible(Object.seal({})));
show('apply', Reflect.apply(Math.max, null, [1, 3, 2]), Reflect.apply(function () { return this; }, 'str', []) instanceof String, Reflect.apply(String.prototype.slice, 'hello', { length: 1, 0: 1 }), Reflect.apply((...a) => a.length, null, { length: 3 }));
class Base { constructor(x) { this.x = x; this.nt = new.target.name; } }
class Other { }
const made = Reflect.construct(Base, [7], Other);
show('construct', made.x, made.nt, made instanceof Other, made instanceof Base, Reflect.construct(Date, [0]).getTime(), Reflect.construct(Array, [3]).length);
show('construct-builtin-newtarget', Object.getPrototypeOf(Reflect.construct(Array, [], Other)) === Other.prototype, Object.getPrototypeOf(Reflect.construct(Map, [], Other)) === Other.prototype, Reflect.construct(Map, [], Other) instanceof Other);
for (const [name, f] of [
  ['get-nonobj', () => Reflect.get(1, 'a')],
  ['set-nonobj', () => Reflect.set('s', 'a', 1)],
  ['has-nonobj', () => Reflect.has(null, 'a')],
  ['deleteProperty-nonobj', () => Reflect.deleteProperty(1, 'a')],
  ['defineProperty-nonobj', () => Reflect.defineProperty(1, 'a', {})],
  ['defineProperty-baddesc', () => Reflect.defineProperty({}, 'a', 1)],
  ['gopd-nonobj', () => Reflect.getOwnPropertyDescriptor(1, 'a')],
  ['ownKeys-nonobj', () => Reflect.ownKeys('abc')],
  ['getPrototypeOf-nonobj', () => Reflect.getPrototypeOf(1)],
  ['setPrototypeOf-nonobj', () => Reflect.setPrototypeOf(1, null)],
  ['setPrototypeOf-badproto', () => Reflect.setPrototypeOf({}, 1)],
  ['setPrototypeOf-noarg', () => Reflect.setPrototypeOf({})],
  ['isExtensible-nonobj', () => Reflect.isExtensible(1)],
  ['preventExtensions-nonobj', () => Reflect.preventExtensions(1)],
  ['apply-nonfn', () => Reflect.apply(1, null, [])],
  ['apply-noargs', () => Reflect.apply(Math.max, null)],
  ['apply-badargs', () => Reflect.apply(Math.max, null, 5)],
  ['construct-nonctor', () => Reflect.construct(() => {}, [])],
  ['construct-bad-newtarget', () => Reflect.construct(Base, [], Math.max)],
  ['construct-badargs', () => Reflect.construct(Base, 1)],
  ['key-toString-throws', () => Reflect.get({}, { toString() { throw new EvalError('key coercion'); } })],
]) tryit(name, f);
show('Reflect-object', Object.prototype.toString.call(Reflect), typeof Reflect, Object.keys(Reflect).length, Object.getOwnPropertyNames(Reflect).sort(), Reflect.apply.length, Reflect.construct.length, Reflect.defineProperty.length, Reflect.set.length);
// Reflect.set / get through proxies (with and without traps, explicit receivers)
const plog = [];
const tgt = { v: 1, set acc(x) { plog.push('acc setter this===rcv:' + (this === rcv2)); } };
const rcv2 = {};
const withTrap = new Proxy(tgt, { set(t, k, v, r) { plog.push('trap ' + k + ' rcv===proxy:' + (r === withTrap) + ' rcv===rcv2:' + (r === rcv2)); return Reflect.set(t, k, v, r); } });
const noTrap = new Proxy(tgt, {});
show('proxy-set-default-receiver', Reflect.set(withTrap, 'v', 2), tgt.v, Reflect.set(withTrap, 'n', 3, rcv2), rcv2.n, plog.splice(0));
show('proxy-set-no-trap', Reflect.set(noTrap, 'v', 5), tgt.v, Reflect.set(noTrap, 'acc', 1, rcv2), plog.splice(0), Reflect.set(noTrap, 'fresh', 1, rcv2), rcv2.fresh);
show('proxy-set-no-trap-frozen', Reflect.set(new Proxy(Object.freeze({ f: 1 }), {}), 'f', 2), Reflect.set(new Proxy(Object.freeze({}), {}), 'g', 2));
tryit('proxy-set-trap-invariant', () => Reflect.set(new Proxy(Object.defineProperty({}, 'c', { value: 1, writable: false, configurable: false }), { set: () => true }), 'c', 2, {}));
const { proxy: revokedP, revoke } = Proxy.revocable({}, {}); revoke();
tryit('proxy-set-revoked', () => Reflect.set(revokedP, 'x', 1, {}));
show('proxy-get-receiver', Reflect.get(new Proxy({ get g() { return this.tag; } }, {}), 'g', { tag: 'R' }), Reflect.get(new Proxy({}, { get: (t, k, r) => r.tag }), 'any', { tag: 'R2' }));
show('reflect-gopd-proxy', Reflect.getOwnPropertyDescriptor(new Proxy({ a: 1 }, {}), 'a'), Reflect.getPrototypeOf(new Proxy([], {})) === Array.prototype);
show('reflect-ta', Reflect.ownKeys(new Uint8Array(2)), Reflect.getOwnPropertyDescriptor(new Uint8Array([9]), 0), Reflect.getOwnPropertyDescriptor(new Uint8Array(1), 1), Reflect.deleteProperty(new Uint8Array(1), 0), Reflect.deleteProperty(new Uint8Array(1), 5), Reflect.deleteProperty(new Uint8Array(1), 'x'));
show('reflect-arguments-gopd', (function (a) { a = 'updated'; return Reflect.getOwnPropertyDescriptor(arguments, 0).value; })('orig'));
show('reflect-set-arraylike-receiver', (() => { const arr = [1, 2]; const ok = Reflect.set({}, 'length', 0, arr); return [ok, arr.length]; })());
show('reflect-set-setter-receiver-prim', Reflect.set({ set s(v) { this.v = v; } }, 's', 1, 'prim'));
show('reflect-set-getter-only-proto', Reflect.set(Object.create({ get x() { return 1; } }), 'x', 5));
show('reflect-set-receiver-proxy', (() => { const log = []; const recvP = new Proxy({}, { getOwnPropertyDescriptor(t, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(t, k); }, defineProperty(t, k, d) { log.push('define ' + k + ' ' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); } }); Reflect.set({}, 'q', 1, recvP); Reflect.set({}, 'q', 2, recvP); return log; })());
show('reflect-apply-arraylike-holes', Reflect.apply(function () { return [arguments.length, ...arguments]; }, null, { length: 3, 1: 'mid' }));
show('reflect-construct-newtarget-proxy', Reflect.construct(function () { return new.target === nt; }, [], (globalThis.nt = new Proxy(function () {}, {}))) instanceof Object);
"""


def test_reflect_api(run):
    """CATCHES: Reflect methods returning wrong booleans (receiver-aware set, frozen targets, array length), wrong construct/newTarget prototype selection, or wrong TypeError messages for non-object targets and bad argument lists."""
    _ok(run(["-e", PROG_REFLECT_API]), "reflect_api")


PROG_MAP_SET_WEAK_COLLECTIONS = PRELUDE + r"""
const m = new Map([[1, 'one'], ['1', 'str-one'], [NaN, 'nan'], [-0, 'zero']]);
show('map-basic', m.size, m.get(1), m.get('1'), m.get(NaN), m.get(0), m.get(+0), m.has(-0), [...m.keys()], m.get({}));
show('map-set-chain', m.set('k', 'v') === m, m.size, m.delete('k'), m.delete('k'), m.size);
const objKey = {}; const fnKey = () => {};
m.set(objKey, 'obj').set(fnKey, 'fn');
show('map-obj-keys', m.get(objKey), m.get(fnKey), m.has({}));
show('map-order-reinsert', (() => { const x = new Map([['a', 1], ['b', 2], ['c', 3]]); x.set('a', 'updated'); x.delete('b'); x.set('b', 'readded'); return [...x]; })());
show('map-iter-during-mutation', (() => { const x = new Map([[1, 1], [2, 2], [3, 3]]); const seen = []; for (const [k] of x) { seen.push(k); if (k === 1) { x.delete(2); x.set(4, 4); } if (k === 4) x.set(5, 5); } return seen; })());
show('map-clear-during-iter', (() => { const x = new Map([[1, 1], [2, 2]]); const seen = []; for (const [k] of x) { seen.push(k); if (k === 1) { x.clear(); x.set(9, 9); } } return seen; })());
show('map-forEach', (() => { const out = []; new Map([['x', 1], ['y', 2]]).forEach(function (v, k, mm) { out.push(k + '=' + v + ':' + (mm instanceof Map) + ':' + this.t); }, { t: 'T' }); return out; })());
show('map-entries', [...new Map([[1, 2]]).entries()], Map.prototype.entries === Map.prototype[Symbol.iterator], Object.prototype.toString.call(new Map().entries()), new Map()[Symbol.toStringTag]);
const mi = new Map([[1, 'a']]).values();
show('map-iter-next', mi.next(), mi.next(), mi.next(), typeof mi[Symbol.iterator], mi[Symbol.iterator]() === mi);
tryit('map-iter-bad-next', () => mi.next.call({}));
show('map-from-iterable', [...new Map(new Set([['s', 1]]))], new Map(undefined).size, new Map(null).size);
tryit('map-bad-entry', () => new Map([1]));
tryit('map-noniterable', () => new Map(5));
tryit('map-no-new', () => Map());
tryit('map-get-bad-this', () => Map.prototype.get.call({}, 1));
tryit('map-size-bad-this', () => Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.call(new Set()));
tryit('map-set-on-weakmap', () => Map.prototype.set.call(new WeakMap(), {}, 1));
show('map-ctor-uses-set', (() => { const calls = []; class M2 extends Map { set(k, v) { calls.push(k); return super.set(k, v); } } new M2([['a', 1], ['b', 2]]); return calls; })());
tryit('map-ctor-set-noncallable', () => { class M3 extends Map { } M3.prototype.set = 5; return new M3([[1, 2]]); });
show('map-groupBy', [...Map.groupBy(['apple', 'avocado', 'banana', 'cherry', 'blueberry'], (s, i) => s[0])].map(([k, v]) => k + ':' + v.join('/')), Map.groupBy([1, 2, 3], x => x > 1 ? objKey : null).get(objKey));
show('object-groupBy', Object.groupBy([1, 2, 3, 4, 5], (x, i) => i % 2 ? 'odd-index' : 'even-index'), Object.getPrototypeOf(Object.groupBy([], x => x)), Object.groupBy('abca', c => c));
tryit('groupBy-noncallable', () => Object.groupBy([1], 'x'));
tryit('groupBy-noniterable', () => Map.groupBy(5, x => x));
tryit('groupBy-null', () => Object.groupBy(null, x => x));
// Set
const s = new Set([1, 2, 2, NaN, NaN, -0, 0, 'a']);
show('set-basic', s.size, [...s], s.has(NaN), s.has(0), s.add(3) === s, s.delete(1), s.delete(1), [...s.entries()].slice(0, 2), Set.prototype.keys === Set.prototype.values, Set.prototype[Symbol.iterator] === Set.prototype.values);
show('set-forEach', (() => { const out = []; new Set(['p', 'q']).forEach((v, k, ss) => out.push(v + k + ss.size)); return out; })());
show('set-iter-mutation', (() => { const x = new Set([1, 2, 3]); const seen = []; for (const v of x) { seen.push(v); if (v === 1) { x.delete(1); x.add(1); } if (seen.length > 10) break; } return seen; })());
const A = new Set([1, 2, 3, 4]), B = new Set([3, 4, 5]);
show('set-methods', [...A.union(B)], [...A.intersection(B)], [...A.difference(B)], [...A.symmetricDifference(B)], A.isSubsetOf(B), new Set([3]).isSubsetOf(B), A.isSupersetOf(new Set([1, 2])), A.isDisjointFrom(new Set([9])), A.isDisjointFrom(B));
show('set-methods-order', [...new Set([5, 1, 3]).intersection(new Set([3, 5, 7, 1]))], [...new Set([3, 2, 1]).intersection(new Set([1, 2]))], [...new Set([1, 2]).symmetricDifference(new Set([2, 3, 1, 4]))]);
show('set-methods-map-arg', [...A.union(new Map([[9, 'x']]))], A.isSubsetOf(new Map([[1], [2], [3], [4], [5]])));
const setLike = { size: 2, has(v) { return v === 1 || v === 10; }, keys() { const vals = [10, 1]; let i = 0; return { next() { return i < vals.length ? { value: vals[i++], done: false } : { value: undefined, done: true }; } }; } };
show('set-like', [...A.union(setLike)], [...A.intersection(setLike)], [...A.difference(setLike)], [...A.symmetricDifference(setLike)], A.isSupersetOf(setLike), A.isDisjointFrom(setLike));
tryit('set-like-no-size', () => A.union({ has() {}, keys() {} }));
tryit('set-like-nan-size', () => A.union({ size: 'x', has() {}, keys() {} }));
tryit('set-like-neg-size', () => A.union({ size: -1, has() {}, keys() {} }));
tryit('set-like-no-has', () => A.union({ size: 1, keys() {} }));
tryit('set-like-no-keys', () => A.union({ size: 1, has() {} }));
tryit('set-like-array', () => A.union([1, 2]));
tryit('set-like-prim', () => A.union(5));
tryit('set-method-bad-this', () => Set.prototype.union.call([], new Set()));
show('set-like-call-log', (() => { const log = []; const big = { size: 100, has(v) { log.push('has:' + v); return v < 3; }, keys() { log.push('keys'); return [][Symbol.iterator](); } }; const small = new Set([1, 2, 5]); const r = [[...small.intersection(big)], small.isSubsetOf(big), small.isDisjointFrom(big)]; return [r, log]; })());
show('set-like-small-other', (() => { const log = []; const other = { size: 1, has(v) { log.push('has:' + v); return true; }, keys() { log.push('keys'); const it = [2][Symbol.iterator](); return { next() { const r = it.next(); log.push('next:' + r.value); return r; } }; } }; const r = [[...new Set([1, 2, 3]).intersection(other)], [...new Set([1, 2, 3]).difference(other)]]; return [r, log]; })());
tryit('set-no-new', () => Set());
tryit('set-add-bad-this', () => Set.prototype.add.call(new Map(), 1));
show('set-ctor-uses-add', (() => { const calls = []; class S2 extends Set { add(v) { calls.push(v); return super.add(v); } } new S2('abc'); return calls; })());
// Weak collections
const wm = new WeakMap(); const k1 = {}; const sk = Symbol('weak-ok');
show('weakmap', wm.set(k1, 'v1') === wm, wm.get(k1), wm.has(k1), wm.has({}), wm.delete(k1), wm.has(k1), wm.get(k1), wm.set(sk, 's').get(sk));
tryit('weakmap-prim-key', () => wm.set(1, 1));
tryit('weakmap-registered-symbol', () => wm.set(Symbol.for('reg'), 1));
show('weakmap-prim-has', wm.has(1), wm.get('x'), wm.delete(null));
show('weakmap-ctor', new WeakMap([[k1, 1]]).get(k1), Object.prototype.toString.call(wm), typeof WeakMap.prototype.clear, 'size' in wm);
tryit('weakmap-ctor-bad', () => new WeakMap([[1, 2]]));
const ws = new WeakSet([k1]);
show('weakset', ws.has(k1), ws.add(sk) === ws, ws.has(sk), ws.delete(k1), ws.has(k1), ws.has(5), Object.prototype.toString.call(ws));
tryit('weakset-prim', () => ws.add('str'));
tryit('weakset-bad-this', () => WeakSet.prototype.add.call(new Set(), {}));
tryit('weakmap-get-bad-this', () => WeakMap.prototype.get.call(new Map(), {}));
show('lengths', Map.length, Set.length, WeakMap.length, WeakSet.length, Map.prototype.set.length, Set.prototype.union.length, Map.groupBy.length);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_map_set_weak_collections(run, tier):
    """CATCHES: Map/Set SameValueZero keys, insertion order under deletion/re-insertion and live iteration, groupBy, the ES2025 Set methods (union/intersection/... with set-like protocol and call order), and WeakMap/WeakSet key validation and receiver errors."""
    _ok(run([*tier, "-e", PROG_MAP_SET_WEAK_COLLECTIONS]), "map_set_weak_collections")


PROG_COLLECTIONS_UPSERT_HASHING_SETLIKE = PRELUDE + r"""
const r = (label, f) => { try { console.log(label, fmt(f())); } catch (e) { console.log(label, 'THROW', e.name + ': ' + e.message); } };
// upsert proposal methods
const m = new Map([['a', 1]]);
r('getOrInsert', () => [m.getOrInsert('a', 99), m.getOrInsert('b', 2), [...m]]);
r('getOrInsertComputed', () => { const calls = []; const v1 = m.getOrInsertComputed('a', k => { calls.push(k); return 0; }); const v2 = m.getOrInsertComputed(-0, k => { calls.push(Object.is(k, -0) ? '-0' : k); return 'zero'; }); return [v1, v2, calls, m.has(0), [...m.keys()].map(k => Object.is(k, -0) ? '-0' : k)]; });
r('getOrInsertComputed-mutating-cb', () => { const mm = new Map(); const v = mm.getOrInsertComputed('k', key => { mm.set(key, 'from-cb'); mm.set('other', 1); return 'computed'; }); return [v, [...mm]]; });
r('getOrInsertComputed-noncallable', () => m.getOrInsertComputed('zz', 5));
r('getOrInsert-bad-this', () => Map.prototype.getOrInsert.call(new Set(), 1, 1));
r('getOrInsertComputed-cb-throws', () => { const mm = new Map(); try { mm.getOrInsertComputed('k', () => { throw new Error('cb threw'); }); } catch (e) { return [e.message, mm.size]; } });
const wm = new WeakMap();
const k1 = {}, k2 = {};
r('weak-getOrInsert', () => [wm.getOrInsert(k1, 'v1'), wm.getOrInsert(k1, 'ignored'), wm.get(k1)]);
r('weak-getOrInsertComputed', () => [wm.getOrInsertComputed(k2, k => k === k2 ? 'computed-for-k2' : 'wrong'), wm.getOrInsertComputed(k2, () => 'not called')]);
r('weak-getOrInsert-prim', () => wm.getOrInsert(1, 1));
r('weak-getOrInsertComputed-prim', () => wm.getOrInsertComputed('s', () => 1));
r('weak-getOrInsertComputed-noncallable', () => wm.getOrInsertComputed({}, null));
r('weak-getOrInsert-bad-this', () => WeakMap.prototype.getOrInsert.call(new Map(), {}, 1));
// Set.prototype misc
const s = new Set([3, 1, 2]);
r('set-keys-values', () => [[...s.keys()], [...s.values()], [...s.entries()], s.keys().next(), Object.prototype.toString.call(s.keys())]);
r('set-clear', () => { const x = new Set([1, 2]); const it = x.values(); it.next(); x.clear(); return [x.size, it.next(), x.clear(), (x.add(5), [...x])]; });
r('set-clear-bad-this', () => Set.prototype.clear.call(new Map()));
r('map-clear-bad-this', () => Map.prototype.clear.call(new Set()));
r('set-forEach-delete-readd', () => { const x = new Set(['a', 'b', 'c']); const seen = []; x.forEach(v => { seen.push(v); if (v === 'a') { x.delete('b'); x.add('b'); } }); return seen; });
r('map-forEach-noncallable', () => new Map().forEach(1));
r('set-forEach-noncallable', () => new Set().forEach());
r('map-groupBy-noncallable', () => Map.groupBy([], 1));
r('map-groupBy-keys-samevaluezero', () => [...Map.groupBy([1, 2, 3, 4], x => x % 2 === 0 ? -0 : NaN)].map(([k, v]) => [Object.is(k, -0) ? '-0' : k, v]));
r('object-groupBy-key-coercion', () => Object.groupBy([1, 2], x => ({ toString() { return 'k' + x; } })));
r('object-groupBy-symbol-key', () => Object.getOwnPropertySymbols(Object.groupBy([1], () => Symbol.iterator)).map(String));
// many keys of every type: exercises hashing, collision chains and deletion/compaction
const big = new Map();
const keys = [];
for (let i = 0; i < 300; i++) keys.push(i, -i - 0.5, 'k' + i, i % 7 === 0 ? BigInt(i) : i + 0.25, i % 2 === 0);
const objKeys = Array.from({ length: 50 }, (_, i) => ({ i }));
for (const k of [...keys, ...objKeys, null, undefined, NaN, Symbol.iterator]) big.set(k, typeof k);
r('big-size', () => big.size);
r('big-lookups', () => [big.get(299), big.get(-0.5), big.get('k150'), big.get(140n), big.get(true), big.get(false), big.get(objKeys[49]), big.get(null), big.get(undefined), big.get(NaN), big.get(Symbol.iterator), big.get(300), big.has(141n), big.has(0n)]);
let deleted = 0;
for (let i = 0; i < 300; i += 2) { if (big.delete(i)) deleted++; if (big.delete('k' + i)) deleted++; }
r('big-after-delete', () => [deleted, big.size, big.has(2), big.has(3), big.get('k3'), [...big.keys()].slice(0, 6)]);
for (let i = 0; i < 300; i += 2) big.set(i, 'readded');
r('big-readded-order', () => { const ks = [...big.keys()]; return [big.size, ks.indexOf(0) > ks.indexOf('k299'), big.get(0), ks.slice(-3)]; });
const bigSet = new Set();
for (let i = 0; i < 1000; i++) bigSet.add(i * 1.5);
for (let i = 0; i < 1000; i += 3) bigSet.delete(i * 1.5);
r('bigset', () => [bigSet.size, bigSet.has(1.5), bigSet.has(0), bigSet.has(4.5), [...bigSet].slice(0, 4)]);
r('bigint-keys', () => { const mm = new Map([[1n, 'a'], [2n ** 70n, 'big']]); return [mm.get(1n), mm.get(2n ** 70n), mm.has(1), mm.get(BigInt(1))]; });
r('bool-keys', () => { const mm = new Map([[true, 't'], [false, 'f']]); return [mm.get(true), mm.get(false), mm.get(1), mm.delete(true), mm.size]; });
// set methods: remaining branches
const A = new Set([1, 2, 3]);
r('size-infinity', () => [[...A.intersection({ size: Infinity, has: v => v !== 2, keys() { throw new Error('keys should not be called'); } })], A.isSubsetOf({ size: Infinity, has: () => true, keys() {} })]);
r('size-minus-infinity', () => A.union({ size: -Infinity, has() {}, keys() {} }));
r('size-fractional', () => [...A.intersection({ size: 2.9, has: v => v === 1, keys() { return [1][Symbol.iterator](); } })]);
r('keys-no-next', () => A.union({ size: 1, has() {}, keys() { return {}; } }));
r('keys-result-nonobj', () => A.union({ size: 1, has() {}, keys() { return { next() { return 1; } }; } }));
r('keys-result-nonobj-intersection', () => new Set([1, 2, 3, 4, 5]).intersection({ size: 1, has() {}, keys() { return { next() { return 'x'; } }; } }));
r('difference-iterate-this', () => { const log = []; const res = A.difference({ size: 10, has(v) { log.push(v); return v === 2; }, keys() { log.push('keys'); } }); return [[...res], log]; });
r('difference-iterate-other', () => { const log = []; const res = new Set([1, 2, 3, 4]).difference({ size: 1, has() { log.push('has'); }, keys() { log.push('keys'); return [2, 9][Symbol.iterator](); } }); return [[...res], log]; });
r('symmetricDifference-dupes', () => [...new Set([1, 2]).symmetricDifference({ size: 3, has() {}, keys() { return [2, 3, 3, 1, 4][Symbol.iterator](); } })]);
r('isSupersetOf-smaller-this', () => { const log = []; return [new Set([1]).isSupersetOf({ size: 5, has() { log.push('has'); }, keys() { log.push('keys'); } }), log]; });
r('isSupersetOf-iterates-other', () => { const log = []; const res = new Set([1, 2, 3]).isSupersetOf({ size: 2, has() {}, keys() { log.push('keys'); let i = 0; const vals = [1, 9, 2]; return { next() { log.push('next'); return i < vals.length ? { value: vals[i++], done: false } : { done: true }; }, return() { log.push('return'); return {}; } }; } }); return [res, log]; });
r('isDisjointFrom-iterates-other', () => { const log = []; const res = new Set([1, 2, 3]).isDisjointFrom({ size: 1, has() {}, keys() { log.push('keys'); let done = false; return { next() { log.push('next'); if (done) return { done: true }; done = true; return { value: 3, done: false }; }, return() { log.push('return'); return {}; } }; } }); return [res, log]; });
r('isSubsetOf-larger-this', () => new Set([1, 2, 3]).isSubsetOf({ size: 1, has: () => true, keys() {} }));
r('isSubsetOf-has-coerced', () => new Set([1, 2]).isSubsetOf({ size: 5, has: v => v === 1 ? 'truthy' : 0, keys() {} }));
r('union-mutation-during', () => { const base = new Set([1]); const res = base.union({ size: 2, has() {}, keys() { base.add(99); return [2, 3][Symbol.iterator](); } }); return [[...res], [...base]]; });
r('intersection-has-mutates-this', () => { const base = new Set([1, 2, 3]); const res = base.intersection({ size: 5, has(v) { if (v === 1) base.delete(2); return true; }, keys() {} }); return [...res]; });
r('set-method-result-class', () => { class MySet extends Set {} const x = new MySet([1]).union(new Set([2])); return [x instanceof MySet, x instanceof Set, x.constructor === Set]; });
"""


def test_collections_upsert_hashing_setlike(run):
    """CATCHES: Map/WeakMap getOrInsert/getOrInsertComputed, Set clear/keys and forEach errors, hashing of many mixed-type keys with deletion and re-insertion, and the remaining set-like protocol branches (infinite/fractional sizes, bad keys iterators, which side gets iterated, mutation during the operation)."""
    _ok(run(["-e", PROG_COLLECTIONS_UPSERT_HASHING_SETLIKE]), "collections_upsert_hashing_setlike")


PROG_ITERATOR_HELPERS = PRELUDE + r"""
function* nat() { let n = 0; while (true) yield n++; }
function* tracked(items, log) { try { for (const x of items) { log.push('yield ' + x); yield x; } } finally { log.push('finally'); } }
show('map-filter-take', nat().map(x => x * x).filter(x => x % 2).take(4).toArray());
show('drop', nat().drop(3).take(2).toArray(), [1, 2, 3].values().drop(5).toArray());
show('flatMap', [1, 2].values().flatMap(x => [x, x * 10]).toArray(), ['ab', 'c'].values().flatMap(s => new String(s)).toArray(), [1].values().flatMap(x => new Set([x, 'set'])).toArray());
tryit('flatMap-nonobj', () => [1].values().flatMap(x => 5).toArray());
show('flatMap-string-rejected', (() => { try { return [1].values().flatMap(x => 'str').toArray(); } catch (e) { return e.name + ': ' + e.message; } })());
show('reduce', nat().take(5).reduce((a, b) => a + b), nat().take(3).reduce((a, b) => a + b, 100), [].values().reduce((a, b) => a, 'init'));
tryit('reduce-empty', () => [].values().reduce((a, b) => a));
show('some/every/find', nat().some(x => x > 5), [1, 2].values().every(x => x > 0), nat().find(x => x * x > 50), [1].values().find(x => false), [].values().some(x => true), [].values().every(x => false));
show('forEach', (() => { const out = []; const r = [3, 4].values().forEach((v, i) => out.push(v + '@' + i)); return [out, r]; })());
show('counter-arg', ['a', 'b', 'c'].values().map((v, i) => v + i).toArray(), ['a', 'b', 'c'].values().filter((v, i) => i !== 1).toArray(), [5, 6].values().flatMap((v, i) => [i]).toArray(), [1, 2].values().reduce((acc, v, i) => acc + i, ''));
const log = [];
const it = tracked([1, 2, 3, 4], log).map(x => x * 2);
show('helper-next', it.next(), it.next());
show('helper-return', it.return(), it.next(), log);
const log2 = [];
show('take-closes', tracked([1, 2, 3], log2).take(1).toArray(), log2);
const log3 = [];
show('find-closes', tracked([1, 2, 3], log3).find(x => x === 2), log3);
const log4 = [];
tryit('callback-throw-closes', () => tracked([1, 2], log4).map(x => { throw new Error('cb threw'); }).toArray());
show('log4', log4);
const log5 = [];
show('some-closes', tracked([1, 2, 3], log5).some(x => x === 1), log5);
tryit('take-negative', () => nat().take(-1));
tryit('take-nan', () => nat().take(NaN));
tryit('drop-negative', () => nat().drop(-1));
show('take-inf', [1, 2].values().take(Infinity).toArray(), [1, 2].values().drop(Infinity).toArray(), [1, 2, 3].values().take(1.9).toArray());
tryit('map-noncallable', () => nat().map(5));
tryit('filter-noncallable', () => nat().filter());
tryit('forEach-noncallable', () => nat().forEach());
tryit('some-noncallable', () => nat().some());
tryit('find-noncallable', () => nat().find(1));
tryit('reduce-noncallable', () => nat().reduce());
tryit('helper-on-nonobj', () => Iterator.prototype.map.call(1, x => x));
tryit('toArray-on-nonobj', () => Iterator.prototype.toArray.call(null));
const running = nat().map(function (x) { return running.next(); });
tryit('helper-reentrant', () => running.next());
const helperProto = Object.getPrototypeOf(nat().map(x => x));
show('helper-proto', Object.prototype.toString.call(nat().map(x => x)), helperProto[Symbol.toStringTag], Object.getPrototypeOf(helperProto) === Iterator.prototype, typeof helperProto.next, typeof helperProto.return);
tryit('helper-next-bad-this', () => helperProto.next.call({}));
tryit('helper-return-bad-this', () => helperProto.return.call({}));
// Iterator global
show('Iterator', typeof Iterator, Iterator.prototype === Object.getPrototypeOf(Object.getPrototypeOf([].values())), Iterator.length, Iterator.name);
tryit('Iterator-call', () => Iterator());
tryit('Iterator-new-abstract', () => new Iterator());
class MyIt extends Iterator { next() { return { value: 1, done: false }; } }
show('Iterator-subclass', new MyIt().take(2).toArray(), new MyIt() instanceof Iterator);
show('Iterator.from-iterable', Iterator.from([1, 2]).toArray(), Iterator.from('ab').toArray(), Iterator.from(new Set([3])).map(x => x + 1).toArray());
const plain = { i: 0, next() { return this.i < 2 ? { value: this.i++, done: false } : { done: true }; } };
const wrapped = Iterator.from(plain);
show('Iterator.from-wrapped', wrapped.toArray(), Object.getPrototypeOf(wrapped) === Iterator.prototype, typeof wrapped.next, Object.prototype.toString.call(wrapped));
const genObj = nat();
show('Iterator.from-identity', Iterator.from(genObj) === genObj);
tryit('Iterator.from-prim', () => Iterator.from(5));
tryit('Iterator.from-bad-iterator-method', () => Iterator.from({ [Symbol.iterator]: 1 }));
show('Iterator.from-wrap-return', (() => { const l = []; const w = Iterator.from({ next() { return { value: 1, done: false }; }, return() { l.push('inner return'); return { done: true, value: 'r' }; } }); return [w.return(), l]; })());
show('Iterator.from-wrap-noreturn', Iterator.from({ next() { return { value: 1, done: false }; } }).return());
if (typeof Iterator.concat === 'function') {
  show('concat', Iterator.concat([1, 2], new Set([3]), 'xy'.split('')).toArray(), Iterator.concat().toArray());
  tryit('concat-nonobj', () => Iterator.concat(5));
  tryit('concat-string', () => Iterator.concat('ab'));
  tryit('concat-noniterable', () => Iterator.concat({}));
  const c = Iterator.concat([1, 2], [3]);
  show('concat-steps', c.next(), c.return(), c.next());
}
if (typeof Iterator.zip === 'function') {
  show('zip', Iterator.zip([[1, 2, 3], ['a', 'b']]).toArray(), Iterator.zip([[1, 2], ['a']], { mode: 'longest' }).toArray(), Iterator.zip([[1, 2], ['a']], { mode: 'longest', padding: ['P1', 'P2'] }).toArray());
  tryit('zip-strict', () => Iterator.zip([[1, 2], ['a']], { mode: 'strict' }).toArray());
  tryit('zip-bad-mode', () => Iterator.zip([[1]], { mode: 'bogus' }));
  if (typeof Iterator.zipKeyed === 'function') show('zipKeyed', Iterator.zipKeyed({ a: [1, 2], b: ['x', 'y', 'z'] }).toArray(), Iterator.zipKeyed({ a: [1], b: [] }, { mode: 'longest', padding: { b: 'pad' } }).toArray());
}
// array / string iterators
const ai = ['x', 'y'].entries();
show('array-iter', Object.prototype.toString.call(ai), ai.next(), ai.next(), ai.next(), ai.next());
const grow = [1]; const gi = grow.values(); gi.next(); grow.push(2);
show('array-iter-live', gi.next(), gi.next(), (grow.push(3), gi.next()));
show('array-iter-arraylike', [...Array.prototype.values.call({ length: 2, 0: 'a', 1: 'b' })], [...Array.prototype.keys.call('xyz')]);
const arrIterProto = Object.getPrototypeOf([][Symbol.iterator]());
tryit('array-iter-bad-this', () => arrIterProto.next.call({}));
tryit('array-iter-on-null', () => Array.prototype.values.call(null));
show('generator-proto', Object.prototype.toString.call(nat()), typeof nat().return, nat().return('early'), (() => { const g = nat(); g.next(); return g.throw === undefined ? 'no throw' : (() => { try { g.throw(new Error('gen-thrown')); } catch (e) { return e.message; } })(); })());
tryit('generator-next-bad-this', () => Object.getPrototypeOf(nat()).next.call({}));
tryit('generator-running', () => { const g = (function* () { g.next(); })(); g.next(); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_iterator_helpers(run, tier):
    """CATCHES: Iterator.prototype helpers (map/filter/take/drop/flatMap/reduce/toArray/forEach/some/every/find) that are eager, skip closing the source, accept bad limits, or mis-report errors; Iterator.from/concat/zip; array/string/generator iterator protocol and receiver checks."""
    _ok(run([*tier, "-e", PROG_ITERATOR_HELPERS]), "iterator_helpers")


PROG_ITERATOR_PROTOCOL_EDGES = PRELUDE + r"""
const r = (label, f) => { try { console.log(label, fmt(f())); } catch (e) { console.log(label, 'THROW', e.name + ': ' + e.message); } };
function logged(name, items, log, extra = {}) {
  let i = 0;
  return Object.assign({
    [Symbol.iterator]() { return this; },
    next() { log.push(name + '.next'); return i < items.length ? { value: items[i++], done: false } : { value: undefined, done: true }; },
    return() { log.push(name + '.return'); return { done: true }; },
  }, extra);
}
// Iterator.prototype.constructor / @@toStringTag accessors (SetterThatIgnoresPrototypeProperties)
const ctorDesc = Object.getOwnPropertyDescriptor(Iterator.prototype, 'constructor');
const tagDesc = Object.getOwnPropertyDescriptor(Iterator.prototype, Symbol.toStringTag);
r('proto-accessors', () => [typeof ctorDesc.get, typeof ctorDesc.set, ctorDesc.enumerable, ctorDesc.configurable, typeof tagDesc.get, tagDesc.get.call(1), ctorDesc.get.call(null) === Iterator]);
r('set-on-proto', () => { Iterator.prototype.constructor = 1; });
r('set-tag-on-proto', () => { Iterator.prototype[Symbol.toStringTag] = 'x'; });
r('set-on-derived', () => { const o = Object.create(Iterator.prototype); o.constructor = 'own'; o[Symbol.toStringTag] = 'MyTag'; return [Object.getOwnPropertyDescriptor(o, 'constructor'), Object.prototype.toString.call(o)]; });
r('set-on-prim', () => ctorDesc.set.call(5, 1));
r('set-undefined-this', () => tagDesc.set.call(undefined, 'x'));
function NT() {}
NT.prototype = 3;
r('construct-newtarget-bad-proto', () => Object.getPrototypeOf(Reflect.construct(Iterator, [], NT)) === Iterator.prototype);
class Sub extends Iterator {}
r('construct-subclass', () => [Object.getPrototypeOf(new Sub()) === Sub.prototype, typeof new Sub().next]);
// helpers: errors from next/value/callback and closing behaviour
const log1 = [];
r('map-next-throws', () => Iterator.from({ next() { throw new RangeError('next threw'); }, return() { log1.push('should-not-close'); } }).map(x => x).next());
r('map-next-throws-log', () => log1);
r('map-result-nonobj', () => Iterator.prototype.map.call({ next() { return 1; } }, x => x).next());
r('map-next-noncallable', () => Iterator.prototype.map.call({ next: 5 }, x => x).next());
r('map-done-getter-throws', () => Iterator.prototype.map.call({ next() { return { get done() { throw new EvalError('done getter'); } }; } }, x => x).next());
const log2 = [];
r('filter-callback-throws', () => Iterator.prototype.filter.call(logged('src', [1, 2], log2), () => { throw new URIError('pred threw'); }).next());
r('filter-log', () => log2);
const log3 = [];
r('take-limit-valueOf-throws', () => Iterator.prototype.take.call(logged('src', [1], log3), { valueOf() { throw new Error('limit valueOf'); } }));
r('take-limit-log', () => log3);
const log4 = [];
r('drop-skips-then-done', () => [Iterator.prototype.drop.call(logged('d', [1, 2], log4), 5).next(), log4]);
const log5 = [];
r('flatMap-inner-next-throws', () => Iterator.prototype.flatMap.call(logged('outer', [1, 2], log5), () => ({ [Symbol.iterator]() { return { next() { throw new TypeError('inner next'); } }; } })).next());
r('flatMap-inner-log', () => log5);
const log6 = [];
r('flatMap-mapper-throws', () => Iterator.prototype.flatMap.call(logged('outer', [1], log6), () => { throw new Error('mapper'); }).next());
r('flatMap-mapper-log', () => log6);
const log7 = [];
r('flatMap-returns-iterator-not-iterable', () => Iterator.prototype.flatMap.call(logged('o', [1], log7), () => ({ i: 0, next() { return this.i++ < 2 ? { value: 'it' + this.i, done: false } : { done: true }; } })).toArray());
const log8 = [];
const fmIt = Iterator.prototype.flatMap.call(logged('outer', [1, 2], log8), x => logged('inner' + x, [x, x], log8));
r('flatMap-return-mid-inner', () => [fmIt.next(), fmIt.return(), fmIt.next(), log8]);
const log9 = [];
const notStarted = Iterator.prototype.map.call(logged('ns', [1], log9), x => x);
r('return-before-start', () => [notStarted.return(), notStarted.next(), log9]);
const log10 = [];
const doneIt = Iterator.prototype.map.call(logged('dn', [], log10), x => x);
r('return-after-done', () => [doneIt.next(), doneIt.return(), log10]);
r('helper-return-throws', () => { const h = Iterator.prototype.map.call({ next() { return { value: 1, done: false }; }, return() { throw new Error('return threw'); } }, x => x); h.next(); return h.return(); });
r('helper-return-nonobj-result', () => { const h = Iterator.prototype.map.call({ next() { return { value: 1, done: false }; }, return() { return 5; } }, x => x); h.next(); return h.return(); });
// reduce/some/every/find/forEach/toArray: callback throws closes; next result non-object
for (const m of ['reduce', 'some', 'every', 'find', 'forEach']) {
  const lg = [];
  r(m + '-callback-throws', () => { try { Iterator.prototype[m].call(logged('s', [1, 2], lg), () => { throw new Error(m + ' cb'); }); } catch (e) { return [e.message, lg]; } });
}
r('toArray-nonobj-result', () => Iterator.prototype.toArray.call({ next() { return null; } }));
r('every-false-closes', () => { const lg = []; return [Iterator.prototype.every.call(logged('e', [1, 2], lg), x => x > 1), lg]; });
r('find-not-found', () => { const lg = []; return [Iterator.prototype.find.call(logged('f', [1], lg), x => false), lg]; });
// Iterator.from with non-iterable iterator-like objects / strings / string objects
r('from-string-object', () => Iterator.from(new String('ab')).toArray());
r('from-next-only', () => Iterator.from({ next() { return { value: 'n', done: this.d = !this.d ? false : true }; } }).take(3).toArray());
r('from-iterator-returning-nonobj', () => Iterator.from({ [Symbol.iterator]() { return 5; } }));
r('from-null-iterator-method', () => Iterator.from({ [Symbol.iterator]: null, next() { return { done: true }; } }).toArray());
const wrapProto = Object.getPrototypeOf(Iterator.from({ next() {} }));
r('wrap-next-bad-this', () => wrapProto.next.call({}));
r('wrap-return-bad-this', () => wrapProto.return.call({}));
r('wrap-return-noncallable', () => Iterator.from({ next() {}, return: 5 }).return());
// concat
const clog = [];
const cc = Iterator.concat(logged('a', [1], clog), logged('b', [2, 3], clog));
r('concat-lazy', () => [clog.slice(), cc.next(), cc.next(), clog.slice(), cc.return(), clog.slice(), cc.next()]);
r('concat-iterator-method-nonobj', () => Iterator.concat({ [Symbol.iterator]() { return 1; } }).next());
r('concat-next-throws', () => Iterator.concat({ [Symbol.iterator]() { return { next() { throw new Error('concat inner'); } }; } }).next());
r('concat-reentrant', () => { let c; c = Iterator.concat({ [Symbol.iterator]() { return { next() { return c.next(); } }; } }); return c.next(); });
r('concat-bad-this-next', () => Iterator.concat().next.call({}));
r('concat-shape', () => [Object.prototype.toString.call(Iterator.concat()), Object.getPrototypeOf(Iterator.concat()) === Object.getPrototypeOf([].values().map(x => x)), typeof Iterator.concat().return]);
r('concat-return-before-start', () => { const lg = []; const c = Iterator.concat(logged('x', [1], lg)); return [c.return(), lg]; });
// zip edge cases
const zlog = [];
const z = Iterator.zip([logged('p', [1, 2], zlog), logged('q', ['a', 'b', 'c'], zlog)]);
r('zip-shortest-closes-others', () => [z.next(), z.next(), z.next(), zlog]);
const zlog2 = [];
const z2 = Iterator.zip([logged('p', [1, 2], zlog2), logged('q', ['a'], zlog2)]);
r('zip-return-mid', () => [z2.next(), z2.return(), z2.next(), zlog2]);
r('zip-return-before-start', () => { const lg = []; const zz = Iterator.zip([logged('a', [1], lg)]); return [zz.return(), lg]; });
r('zip-strict-ok', () => Iterator.zip([[1, 2], ['a', 'b']], { mode: 'strict' }).toArray());
r('zip-strict-first-longer', () => { const lg = []; return [(() => { try { return Iterator.zip([logged('a', [1, 2], lg), logged('b', [1], lg)], { mode: 'strict' }).toArray(); } catch (e) { return e.message; } })(), lg]; });
r('zip-strict-second-longer', () => { const lg = []; return [(() => { try { return Iterator.zip([logged('a', [1], lg), logged('b', [1, 2], lg)], { mode: 'strict' }).toArray(); } catch (e) { return e.message; } })(), lg]; });
r('zip-longest-padding-iter', () => Iterator.zip([[1], [], [1, 2, 3]], { mode: 'longest', padding: new Set(['p0', 'p1']) }).toArray());
r('zip-empty', () => [Iterator.zip([]).toArray(), Iterator.zip([], { mode: 'longest' }).next()]);
r('zip-input-nonobj', () => Iterator.zip(5));
r('zip-options-nonobj', () => Iterator.zip([], 5));
r('zip-padding-nonobj', () => Iterator.zip([], { mode: 'longest', padding: 5 }));
r('zip-input-string-element', () => Iterator.zip(['ab']));
r('zip-next-throws', () => { const lg = []; try { Iterator.zip([logged('ok', [1], lg), { [Symbol.iterator]() { return { next() { throw new Error('zip next'); }, return() { lg.push('thrower.return'); } }; } }]).next(); } catch (e) { return [e.message, lg]; } });
r('zip-reentrant', () => { let zz; zz = Iterator.zip([{ [Symbol.iterator]() { return { next() { return zz.next(); } }; } }]); return zz.next(); });
r('zip-bad-this', () => Object.getPrototypeOf(Iterator.zip([])).next.call({}));
r('zipKeyed-symbols-order', () => { const s = Symbol('k'); return Iterator.zipKeyed({ b: [1], a: [2], [s]: [3], 1: [4] }).toArray().map(o => Reflect.ownKeys(o).map(String)); });
r('zipKeyed-longest-padding', () => Iterator.zipKeyed({ a: [1, 2], b: [9] }, { mode: 'longest', padding: { b: 'B' } }).toArray());
r('zipKeyed-undefined-skipped', () => Iterator.zipKeyed({ a: [1], b: undefined }).toArray());
r('zipKeyed-nonobj', () => Iterator.zipKeyed(1));
// string iterator over joined halves and array iterator kinds on array-likes
r('string-iter-joined', () => [...('\uD83D' + '\uDE00' + 'x')]);
r('string-iter-next-detached', () => { const it = 'ab'[Symbol.iterator](); return [it.next(), Object.getPrototypeOf(it).next.call(it), it.next()]; });
r('array-iter-entries-arraylike', () => [...Array.prototype.entries.call({ length: 2, 0: 'z' })]);
r('array-iter-shrinking', () => { const a = [1, 2, 3]; const out = []; for (const x of a) { out.push(x); a.length = 1; } return out; });
r('array-iter-typed', () => [...new Uint8Array([4, 5]).entries()]);
r('array-iter-proto-chain', () => [Object.getPrototypeOf(Object.getPrototypeOf([].keys())) === Iterator.prototype, [].keys()[Symbol.toStringTag], typeof [].keys().map]);
"""


def test_iterator_protocol_edges(run):
    """CATCHES: Iterator.prototype constructor/@@toStringTag setter semantics, helper error propagation and source closing in every state, Iterator.from wrappers, lazy Iterator.concat, Iterator.zip/zipKeyed shortest/longest/strict modes with closing order, and string/array iterator corner cases."""
    _ok(run(["-e", PROG_ITERATOR_PROTOCOL_EDGES]), "iterator_protocol_edges")


PROG_ITERATOR_DISPOSE_AND_ZIP_SETUP = PRELUDE + r"""
const r = (label, f) => { try { console.log(label, fmt(f())); } catch (e) { console.log(label, 'THROW', e.name + ': ' + e.message); } };
// Iterator.prototype[@@dispose] and %AsyncIteratorPrototype%[@@asyncDispose]
r('iterator-dispose', () => { const log = []; const it = Iterator.from({ next() { return { done: false, value: 1 }; }, return() { log.push('return called'); return {}; } }); return [typeof Iterator.prototype[Symbol.dispose], it[Symbol.dispose](), log]; });
r('iterator-dispose-generator', () => { const log = []; function* g() { try { yield 1; yield 2; } finally { log.push('gen finally'); } } const it = g(); it.next(); it[Symbol.dispose](); return [log, it.next()]; });
r('iterator-dispose-using', () => { const log = []; { using it = Iterator.from({ next() { return { done: true }; }, return() { log.push('closed by using'); return {}; } }); } return log; });
const AsyncIteratorPrototype = Object.getPrototypeOf(Object.getPrototypeOf((async function* () {})()).__proto__);
const ad = AsyncIteratorPrototype[Symbol.asyncDispose];
const results = [];
const settle = (label, p) => p.then(v => results.push(label + ' fulfilled ' + fmt(v)), e => results.push(label + ' rejected ' + (e && e.message || e)));
(async () => {
  await settle('asyncDispose-no-return', ad.call({}));
  await settle('asyncDispose-return-value-dropped', ad.call({ return(...args) { results.push('return args ' + args.length); return 'dropped'; } }));
  await settle('asyncDispose-return-throws', ad.call({ return() { throw new Error('return threw'); } }));
  await settle('asyncDispose-return-getter-throws', ad.call({ get return() { throw new Error('getter threw'); } }));
  await settle('asyncDispose-return-rejects', ad.call({ return() { return Promise.reject(new Error('rejected result')); } }));
  await settle('asyncDispose-return-noncallable', ad.call({ return: 5 }));
  await settle('asyncDispose-async-generator', (async () => { const log = []; async function* ag() { try { yield 1; } finally { log.push('ag finally'); } } const g = ag(); await g.next(); await g[Symbol.asyncDispose](); return log; })());
  console.log(results.join('\n'));
  rest();
})();
function rest() {
  // Iterator.zip setup failures and option handling
  const open = (name, items, log) => { let i = 0; return { [Symbol.iterator]() { log.push('open ' + name); return { next() { return i < items.length ? { value: items[i++], done: false } : { done: true }; }, return() { log.push('close ' + name); return {}; } }; } }; };
  r('zip-mode-undefined', () => Iterator.zip([[1], [2]], { mode: undefined }).toArray());
  r('zip-bad-element-closes-opened', () => { const log = []; try { Iterator.zip([open('a', [1], log), open('b', [1], log), 5]); } catch (e) { return [e.message, log]; } });
  r('zip-iterables-next-throws', () => { const log = []; const iterables = { [Symbol.iterator]() { let n = 0; return { next() { if (n++ === 1) throw new Error('iterables next'); return { value: open('x', [1], log), done: false }; } }; } }; try { Iterator.zip(iterables); } catch (e) { return [e.message, log]; } });
  r('zip-padding-iter-throws', () => { const log = []; try { Iterator.zip([open('a', [1], log)], { mode: 'longest', padding: { [Symbol.iterator]() { return { next() { throw new Error('padding next'); } }; } } }); } catch (e) { return [e.message, log]; } });
  r('zip-padding-closed', () => { const log = []; Iterator.zip([open('a', [1], log)], { mode: 'longest', padding: { [Symbol.iterator]() { return { next() { return { value: 'p', done: false }; }, return() { log.push('padding closed'); return {}; } }; } } }); return log; });
  r('zipKeyed-proxy-input', () => Iterator.zipKeyed(new Proxy({ b: ['B'], a: ['A'], hidden: ['H'] }, { ownKeys: () => ['a', 'b', 'hidden'], getOwnPropertyDescriptor: (t, k) => ({ value: t[k], enumerable: k !== 'hidden', configurable: true }) })).toArray());
  r('zipKeyed-getter-throws-closes', () => { const log = []; try { Iterator.zipKeyed({ a: open('a', [1], log), get b() { throw new Error('getter b'); } }); } catch (e) { return [e.message, log]; } });
  r('zipKeyed-gopd-throws', () => Iterator.zipKeyed(new Proxy({ a: [1] }, { getOwnPropertyDescriptor() { throw new Error('gopd threw'); } })));
  r('zipKeyed-padding-getter-throws', () => { const log = []; try { Iterator.zipKeyed({ a: open('a', [1], log) }, { mode: 'longest', padding: { get a() { throw new Error('pad getter'); } } }); } catch (e) { return [e.message, log]; } });
}
"""


def test_iterator_dispose_and_zip_setup(run):
    """CATCHES: Iterator.prototype[@@dispose] and %AsyncIteratorPrototype%[@@asyncDispose] not calling return (or mishandling its errors/results), and Iterator.zip/zipKeyed setup failures that do not close already-opened inputs in reverse order."""
    _ok(run(["-e", PROG_ITERATOR_DISPOSE_AND_ZIP_SETUP]), "iterator_dispose_and_zip_setup")


PROG_FUNCTION_PROTO_WEAKREFS = PRELUDE + r"""
function add(a, b, c) { return [this === undefined ? 'undef' : this === null ? 'null' : typeof this === 'object' ? (this.tag || 'obj') : this, a, b, c]; }
function strictAdd(a, b) { 'use strict'; return [this === undefined ? 'undef' : this === null ? 'null' : typeof this, a, b]; }
show('call', add.call({ tag: 'T' }, 1, 2, 3), strictAdd.call(5, 1), strictAdd.call(null), strictAdd.call(undefined));
show('call-sloppy-this', (function () { return typeof this; }).call(5), (function () { return this === globalThis; }).call(null), (function () { return this === globalThis; }).call(undefined), (function () { return this instanceof String; }).call('s'));
show('apply', add.apply({ tag: 'A' }, [1, 2]), add.apply({ tag: 'B' }), add.apply({ tag: 'C' }, null), add.apply({ tag: 'D' }, { length: 2, 0: 'x', 1: 'y' }), strictAdd.apply('s', 'ab'.split('')));
tryit('apply-prim-args', () => add.apply(null, 5));
tryit('apply-string-args', () => add.apply(null, 'ab'));
tryit('call-noncallable', () => Function.prototype.call.call({}));
tryit('apply-noncallable', () => Function.prototype.apply.call(1));
const bound = add.bind({ tag: 'bound' }, 'p1');
show('bind', bound('p2', 'p3'), bound.name, bound.length, add.bind(null, 1, 2, 3, 4).length, typeof bound.prototype, Object.getOwnPropertyDescriptor(bound, 'name'), Object.getOwnPropertyDescriptor(bound, 'length'));
show('bind-twice', add.bind({ tag: 'first' }).bind({ tag: 'second' }, 'a')('b'), add.bind().bind().name);
function Point(x, y) { this.x = x; this.y = y; }
const BoundPoint = Point.bind({ ignored: true }, 10);
const bp = new BoundPoint(20);
show('bind-new', bp.x, bp.y, bp instanceof Point, bp instanceof BoundPoint, Object.getPrototypeOf(bp) === Point.prototype);
show('bind-length-edge', (() => { const f = function (a, b, c) {}; Object.defineProperty(f, 'length', { value: Infinity }); return [f.bind().length, f.bind(null, 1).length]; })(), (() => { const f = function () {}; Object.defineProperty(f, 'length', { value: -5 }); return f.bind().length; })(), (() => { const f = function () {}; Object.defineProperty(f, 'length', { value: 2.7 }); return f.bind().length; })(), (() => { const f = function () {}; Object.defineProperty(f, 'length', { value: '3' }); return f.bind().length; })(), (() => { const f = function () {}; delete f.length; return f.bind().length; })());
show('bind-name-edge', (() => { const f = function () {}; Object.defineProperty(f, 'name', { value: 42 }); return f.bind().name; })(), (() => { const f = () => {}; return f.bind().name; })(), Math.max.bind().name, (class K {}).bind().name, (() => { const f = function () {}; Object.defineProperty(f, 'name', { value: Symbol('s') }); return f.bind().name; })());
tryit('bind-noncallable', () => Function.prototype.bind.call({}));
show('bind-arrow-this', (() => { const arrow = () => this; return arrow.bind({ x: 1 })() === this; })());
show('bound-native', [1, 5, 3].map(Math.max.bind(null, 4)), Array.prototype.join.bind([1, 2], '-')());
show('toString-user', (function foo(a, b) { return a + b; }).toString(), (x => x * 2).toString(), (async function* ag() {}).toString(), (class A { m() {} }).toString(), ({ method() { return 1; } }).method.toString(), ({ get g() { return 1; } }) && Object.getOwnPropertyDescriptor({ get g() { return 1; } }, 'g').get.toString());
show('toString-native', Math.max.toString(), Function.prototype.toString.call(Array), (function () {}).bind().toString(), Function.prototype.toString(), Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.toString(), Symbol.prototype[Symbol.toPrimitive].toString());
tryit('toString-nonfn', () => Function.prototype.toString.call({}));
tryit('toString-proxy-fn', () => Function.prototype.toString.call(new Proxy(function f() {}, {})));
show('Function-ctor', new Function('a', 'b', 'return a * b')(3, 4), Function('return 42')(), new Function('a, b', 'c', 'return a + b + c')(1, 2, 3), new Function().name, new Function('x', 'return x').toString());
tryit('Function-ctor-syntax', () => new Function('return )'));
tryit('Function-ctor-body-injection', () => new Function('/*', '*/){'));
show('fn-props', (function f(a, b = 1, ...c) {}).length, ((a, b) => {}).length, (function () {}).name, (() => {}).name, Object.getOwnPropertyNames(function () {}).sort(), Object.getOwnPropertyNames(() => {}).sort(), Object.getOwnPropertyNames(async function () {}).sort());
show('fn-proto-props', Function.prototype.length, Function.prototype.name, typeof Function.prototype, Function.prototype(), Object.getPrototypeOf(Function.prototype) === Object.prototype);
show('hasInstance', Function.prototype[Symbol.hasInstance].call(Array, []), Object[Symbol.hasInstance]({}), Function.prototype[Symbol.hasInstance].call({}, {}), Object.getOwnPropertyDescriptor(Function.prototype, Symbol.hasInstance).writable);
tryit('instanceof-nonobj-proto', () => { function F() {} F.prototype = 1; return ({}) instanceof F; });
tryit('instanceof-noncallable', () => ({}) instanceof {});
show('instanceof-custom', 1 instanceof { [Symbol.hasInstance]: v => v === 1 }, [] instanceof { [Symbol.hasInstance]: () => 'truthy' });
show('caller-arguments', (() => { try { return (function () { 'use strict'; return arguments.callee; })(); } catch (e) { return e.name; } })(), (function () { return typeof arguments.callee; })());
// WeakRef / FinalizationRegistry
const target = { name: 'target' };
const wr = new WeakRef(target);
show('weakref', wr.deref() === target, wr.deref().name, Object.prototype.toString.call(wr), WeakRef.length, typeof WeakRef.prototype.deref, Reflect.ownKeys(wr), new WeakRef(Symbol('ws')).deref().toString());
tryit('weakref-prim', () => new WeakRef(1));
tryit('weakref-registered-sym', () => new WeakRef(Symbol.for('x')));
tryit('weakref-no-new', () => WeakRef({}));
tryit('weakref-deref-bad', () => WeakRef.prototype.deref.call({}));
const fr = new FinalizationRegistry(held => console.log('cleanup', held));
const token = {};
show('finreg', fr.register({}, 'held', token), fr.unregister(token), fr.unregister({}), fr.register({}, 'no-token'), Object.prototype.toString.call(fr), FinalizationRegistry.length, Reflect.ownKeys(fr));
tryit('finreg-same', () => fr.register(target, target));
tryit('finreg-prim-target', () => fr.register(1, 'h'));
tryit('finreg-bad-token', () => fr.register({}, 'h', 'tok'));
tryit('finreg-unregister-prim', () => fr.unregister(1));
tryit('finreg-no-callback', () => new FinalizationRegistry());
tryit('finreg-no-new', () => FinalizationRegistry(() => {}));
tryit('finreg-register-bad-this', () => FinalizationRegistry.prototype.register.call({}, {}, 1));
tryit('finreg-unregister-bad-this', () => FinalizationRegistry.prototype.unregister.call({}, {}));
show('finreg-symbol-target', fr.register(Symbol('t'), 'sym-held'), fr.unregister(Symbol('tok')));
"""


def test_function_proto_weakrefs(run):
    """CATCHES: Function.prototype.call/apply/bind with wrong this-coercion, bound name/length computation, bound construction, toString of user and native functions, the Function constructor, instanceof/@@hasInstance, and WeakRef/FinalizationRegistry argument validation."""
    _ok(run(["-e", PROG_FUNCTION_PROTO_WEAKREFS]), "function_proto_weakrefs")


PROG_FUNCTION_CONSTRUCTORS_AND_TOSTRING = PRELUDE + r"""
const GeneratorFunction = Object.getPrototypeOf(function* () {}).constructor;
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const AsyncGeneratorFunction = Object.getPrototypeOf(async function* () {}).constructor;
show('ctor-names', GeneratorFunction.name, AsyncFunction.name, AsyncGeneratorFunction.name, GeneratorFunction.length, Object.getPrototypeOf(GeneratorFunction) === Function, typeof GeneratorFunction.prototype.prototype);
const gf = new GeneratorFunction('a', 'b', 'yield a; yield b; return a + b;');
show('generator-function', [...gf(1, 2)], gf.name, gf.toString(), Object.prototype.toString.call(gf), Object.getPrototypeOf(gf) === GeneratorFunction.prototype);
const gfCall = GeneratorFunction('yield* [7, 8]');
show('generator-function-call', [...gfCall()], typeof gfCall.prototype);
const af = AsyncFunction('x', 'return await x * 2');
const agf = AsyncGeneratorFunction('yield 1; yield await Promise.resolve(2);');
show('async-function-shape', af.name, af.length, af.toString(), Object.prototype.toString.call(af), typeof af.prototype, agf.toString().split('\n')[0]);
tryit('generator-ctor-syntax', () => GeneratorFunction('yield )'));
tryit('async-ctor-await-param', () => AsyncFunction('await', 'return 1'));
tryit('generator-ctor-yield-param', () => GeneratorFunction('yield', ''));
tryit('fn-ctor-param-injection', () => Function('a = 1) { return a; } (function (', 'return 2'));
tryit('fn-ctor-body-close-brace', () => Function('}); console.log("injected"); ({'));
tryit('fn-ctor-strict-dupe-params', () => Function('a', 'a', '"use strict"; return a'));
show('fn-ctor-sloppy-dupe-params', Function('a', 'a', 'return a')(1, 2));
show('fn-ctor-param-coercion', Function({ toString() { return 'p'; } }, 'return p')('coerced'), Function(undefined, 'return 1').length, new Function('a,b', 'c', 'return 0').length, Function('...rest', 'return rest.length')(1, 2, 3), Function('a = 5', 'return a')());
show('fn-ctor-global-scope', (() => { const shadow = 'local'; globalThis.shadow = 'global'; return Function('return typeof shadow === "string" ? shadow : "none"')(); })());
show('fn-ctor-newtarget', (() => { class MyFn extends Function {} const f = new MyFn('return 9'); return [f(), f instanceof MyFn, f instanceof Function]; })());
function NT() {}
NT.prototype = 4;
show('fn-ctor-newtarget-bad-proto', Object.getPrototypeOf(Reflect.construct(Function, ['return 1'], NT)) === Function.prototype, Object.getPrototypeOf(Reflect.construct(GeneratorFunction, [''], NT)) === GeneratorFunction.prototype);
// Function.prototype.toString for a variety of sources
const samples = [
  function plain(a, /* comment */ b) { return a; },
  async (x) => { await x; },
  function* gen() { yield 1; },
  class { static s() {} },
  { m(a) {} }.m,
  { async *am() {} }.am,
  { ['computed' + 1]() {} }.computed1,
  Object.getOwnPropertyDescriptor({ set s(v) {} }, 's').set,
  (function () { return function inner() {}; })(),
];
for (const f of samples) console.log('toString', JSON.stringify(f.toString()), JSON.stringify(f.name));
show('toString-natives', [Function.prototype.call, Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get, Symbol, Map.prototype[Symbol.iterator], function () {}.bind(), Function.prototype.toString].map(f => Function.prototype.toString.call(f)));
show('toString-class-method-native-bound', (class { m() {} }).prototype.m.bind().toString());
// call/apply/bind with symbols & edge receivers
show('call-symbol-this', function () { 'use strict'; return typeof this; }.call(Symbol()), function () { return typeof this; }.call(Symbol()), function () { return this instanceof BigInt; }.call(1n));
show('apply-huge-arraylike', Math.max.apply(null, { length: 5, 0: 1, 4: 9 }), String.fromCharCode.apply(null, new Uint8Array([72, 105])));
show('bind-preserves-new-target', (() => { function F() { return new.target === F; } const B = F.bind(null); return [new B(), Reflect.construct(B, []), Reflect.construct(B, [], class {})]; })());
show('bound-instanceof', (() => { function F() {} const B = F.bind(); return [new F() instanceof B, Object.getPrototypeOf(B) === Function.prototype, B.hasOwnProperty('prototype')]; })());
show('bound-proxy-target', (() => { const p = new Proxy(function target() { return 'proxied'; }, {}); const b = p.bind(null); return [b(), b.name, b.length]; })());
show('bound-of-generator', (() => { const b = function* g(x) { yield x; }.bind(null, 'bv'); return [[...b()], b.name, Object.getPrototypeOf(b) === Object.getPrototypeOf(function* () {})]; })());
show('bound-async-proto', Object.getPrototypeOf((async function () {}).bind()) === AsyncFunction.prototype);
show('bind-length-getter-throws', (() => { const f = function () {}; Object.defineProperty(f, 'length', { get() { throw new Error('length getter'); } }); try { f.bind(); } catch (e) { return e.message; } })());
show('hasInstance-bound', (() => { function F() {} const B = F.bind(); return [Function.prototype[Symbol.hasInstance].call(B, new F()), Function.prototype[Symbol.hasInstance].call(5, {})]; })());
show('print-is-silent', print('this text must not appear'), typeof print, print.length);
"""


def test_function_constructors_and_tostring(run):
    """CATCHES: GeneratorFunction/AsyncFunction/AsyncGeneratorFunction constructors and their SyntaxErrors, Function constructor parameter/body handling and global scoping, toString of many function forms, and bind/call/apply corner cases (symbols, new.target, generators, proxies)."""
    _ok(run(["-e", PROG_FUNCTION_CONSTRUCTORS_AND_TOSTRING]), "function_constructors_and_tostring")


PROG_DISPOSABLE_STACKS = PRELUDE + r"""
const log = [];
const L = s => log.push(s);
const ds = new DisposableStack();
show('shape', Object.prototype.toString.call(ds), ds.disposed, Reflect.ownKeys(ds), typeof DisposableStack.prototype[Symbol.dispose], DisposableStack.prototype[Symbol.dispose] === DisposableStack.prototype.dispose, DisposableStack.length);
const res = { name: 'res', [Symbol.dispose]() { L('dispose ' + this.name); } };
show('use-returns', ds.use(res) === res, ds.use(null), ds.use(undefined));
show('adopt-returns', ds.adopt('adopted-value', (v) => L('adopt cb got ' + v)));
show('defer-returns', ds.defer(() => L('deferred')));
ds.dispose();
show('dispose-order', log.splice(0), ds.disposed, ds.dispose());
tryit('use-after-dispose', () => ds.use(res));
tryit('adopt-after-dispose', () => ds.adopt(1, () => {}));
tryit('defer-after-dispose', () => ds.defer(() => {}));
tryit('move-after-dispose', () => ds.move());
tryit('use-nondisposable', () => new DisposableStack().use({}));
tryit('use-prim', () => new DisposableStack().use(5));
tryit('use-dispose-noncallable', () => new DisposableStack().use({ [Symbol.dispose]: 'x' }));
tryit('adopt-noncallable', () => new DisposableStack().adopt(1, 2));
tryit('defer-noncallable', () => new DisposableStack().defer());
tryit('no-new', () => DisposableStack());
tryit('bad-receiver', () => DisposableStack.prototype.dispose.call({}));
tryit('bad-receiver-async', () => DisposableStack.prototype.use.call(new AsyncDisposableStack(), null));
tryit('disposed-getter-bad', () => Object.getOwnPropertyDescriptor(DisposableStack.prototype, 'disposed').get.call({}));
// errors during disposal: SuppressedError chains
const es = new DisposableStack();
es.defer(() => { throw new Error('first registered'); });
es.defer(() => L('middle runs'));
es.defer(() => { throw new Error('last registered'); });
try { es.dispose(); } catch (e) {
  show('suppressed-chain', e.name, e.error && e.error.message, e.suppressed && e.suppressed.message, e instanceof SuppressedError, log.splice(0));
}
const one = new DisposableStack();
one.defer(() => { throw new RangeError('only'); });
tryit('single-error', () => one.dispose());
// move
const src = new DisposableStack();
src.defer(() => L('moved disposer'));
const moved = src.move();
show('move', src.disposed, moved.disposed, moved instanceof DisposableStack, log.splice(0));
moved.dispose();
show('moved-dispose', log.splice(0));
src.dispose();
show('src-dispose-after-move', log.splice(0));
class SubDS extends DisposableStack {}
show('subclass', new SubDS() instanceof SubDS, Object.getPrototypeOf(new SubDS().move()) === DisposableStack.prototype);
// using with a DisposableStack
{
  using st = new DisposableStack();
  st.defer(() => L('using-block disposed'));
  L('in block');
}
show('using-block', log.splice(0));
// AsyncDisposableStack
(async () => {
  const as = new AsyncDisposableStack();
  show('async-shape', Object.prototype.toString.call(as), as.disposed, typeof as[Symbol.asyncDispose], as[Symbol.asyncDispose] === as.disposeAsync);
  as.use({ [Symbol.asyncDispose]() { L('asyncDispose res'); return Promise.resolve(); } });
  as.use({ [Symbol.dispose]() { L('sync fallback res'); } });
  as.adopt('av', async v => { await null; L('async adopt ' + v); });
  as.defer(async () => { L('async defer start'); await null; L('async defer end'); });
  as.use(null);
  const p = as.disposeAsync();
  L('disposeAsync returned ' + (p instanceof Promise));
  await p;
  show('async-order', log.splice(0), as.disposed, await as.disposeAsync());
  try { as.use({}); } catch (e) { show('async-use-after', e.name, e.message); }
  try { new AsyncDisposableStack().use({}); } catch (e) { show('async-use-nondisposable', e.name, e.message); }
  try { new AsyncDisposableStack().adopt(1, null); } catch (e) { show('async-adopt-noncallable', e.name, e.message); }
  try { new AsyncDisposableStack().defer(1); } catch (e) { show('async-defer-noncallable', e.name, e.message); }
  try { AsyncDisposableStack(); } catch (e) { show('async-no-new', e.name, e.message); }
  const bad = await AsyncDisposableStack.prototype.disposeAsync.call({}).then(() => 'resolved', e => e.name + ': ' + e.message);
  show('async-bad-receiver', bad);
  const ae = new AsyncDisposableStack();
  ae.defer(() => { throw new Error('async first'); });
  ae.defer(async () => { throw new Error('async second'); });
  const err = await ae.disposeAsync().then(() => null, e => e);
  show('async-suppressed', err.name, err.error.message, err.suppressed.message);
  const am = new AsyncDisposableStack();
  am.defer(() => L('async moved'));
  const amMoved = am.move();
  await am.disposeAsync();
  show('async-move', log.splice(0), am.disposed);
  await amMoved.disposeAsync();
  show('async-moved-dispose', log.splice(0));
  try { am.move(); } catch (e) { show('async-move-after-dispose', e.name, e.message); }
  {
    await using ast = new AsyncDisposableStack();
    ast.defer(async () => L('await-using disposed'));
  }
  show('await-using', log.splice(0));
})();
"""


def test_disposable_stacks(run):
    """CATCHES: DisposableStack/AsyncDisposableStack with wrong disposal order, missing SuppressedError chaining, use/adopt/defer/move validation and ReferenceErrors after disposal, receiver brand checks, and using/await using integration."""
    _ok(run(["-e", PROG_DISPOSABLE_STACKS]), "disposable_stacks")


PROG_INTERNAL_SLOTS_OBSERVABLE = PRELUDE + r"""
// The engine stores many internal slots as non-enumerable own data properties; they are observable
// through Reflect.ownKeys / getOwnPropertyNames (but not Object.keys / JSON / for-in), and writable.
const items = {
  arrayIter: [].values(), mapIter: new Map().entries(), setIter: new Set().values(), strIter: 'x'[Symbol.iterator](),
  helper: [].values().map(x => x), wrap: Iterator.from({ next() {} }), disposable: new DisposableStack(),
  date: new Date(0), weakref: new WeakRef({}), promise: Promise.resolve(), map: new Map(), error: new Error('e'),
};
for (const [k, v] of Object.entries(items)) {
  console.log(k, JSON.stringify(Reflect.ownKeys(v).map(String)), JSON.stringify(Object.keys(v)), JSON.stringify(v));
}
const d = new Date(0);
console.log('date-slot-desc', JSON.stringify(Object.getOwnPropertyDescriptor(d, '__date_ms')));
d.__date_ms = 86400000;
console.log('date-slot-write', d.toISOString());
const it = ['a', 'b', 'c'].values();
it.__ai_index = 2;
console.log('array-iterator-slot-write', JSON.stringify(it.next()), JSON.stringify(it.next()));
"""


def test_internal_slots_observable(run):
    """CATCHES: a rewrite that hides the reference engine's internal-slot properties: builtin instances expose writable, non-enumerable __xx_ data properties via Reflect.ownKeys and writing them changes behaviour (Date value, array iterator index)."""
    _ok(run(["-e", PROG_INTERNAL_SLOTS_OBSERVABLE]), "internal_slots_observable")


NS_LIB = r"""
export let counter = 1;
export function bump() { counter++; }
export const b = 'bee';
export default 'dflt';
export { b as aliasB };
"""

NS_MAIN = r"""
import * as ns from './lib.mjs';
const r = (label, f) => { try { console.log(label, JSON.stringify(f(), (k, v) => typeof v === 'function' ? '[fn ' + v.name + ']' : v === undefined ? '<undef>' : v)); } catch (e) { console.log(label, 'THROW', e.name + ': ' + e.message); } };
r('keys', () => Object.keys(ns));
r('ownKeys', () => Reflect.ownKeys(ns).map(String));
r('toStringTag', () => [Object.prototype.toString.call(ns), ns[Symbol.toStringTag], Object.getOwnPropertyDescriptor(ns, Symbol.toStringTag)]);
r('proto', () => [Object.getPrototypeOf(ns), Reflect.setPrototypeOf(ns, {}), Reflect.setPrototypeOf(ns, null)]);
r('extensible', () => [Object.isExtensible(ns), Reflect.preventExtensions(ns), Object.isSealed(ns), Object.isFrozen(ns)]);
r('gopd', () => [Object.getOwnPropertyDescriptor(ns, 'counter'), Object.getOwnPropertyDescriptor(ns, 'missing')]);
r('live', () => { const before = ns.counter; ns.bump(); return [before, ns.counter, Object.getOwnPropertyDescriptor(ns, 'counter').value]; });
r('has', () => ['b' in ns, 'nope' in ns, Reflect.has(ns, 'default'), Object.hasOwn(ns, 'aliasB'), ns.hasOwnProperty, Object.prototype.hasOwnProperty.call(ns, 'b'), Object.prototype.propertyIsEnumerable.call(ns, 'b')]);
r('set', () => [Reflect.set(ns, 'b', 'changed'), Reflect.set(ns, 'newProp', 1), ns.b]);
r('set-strict', () => { ns.b = 'x'; });
r('delete', () => [Reflect.deleteProperty(ns, 'b'), Reflect.deleteProperty(ns, 'nope'), Reflect.deleteProperty(ns, Symbol.toStringTag)]);
r('delete-strict', () => { delete ns.b; });
r('define', () => [Reflect.defineProperty(ns, 'b', { value: 'bee' }), Reflect.defineProperty(ns, 'b', { value: 'other' }), Reflect.defineProperty(ns, 'b', { value: 'bee', writable: true, enumerable: true, configurable: false }), Reflect.defineProperty(ns, 'b', { enumerable: false }), Reflect.defineProperty(ns, 'b', { configurable: true }), Reflect.defineProperty(ns, 'b', { writable: false }), Reflect.defineProperty(ns, 'b', { get() {} }), Reflect.defineProperty(ns, 'fresh', { value: 1 }), Reflect.defineProperty(ns, Symbol.toStringTag, { value: 'Module' })]);
r('define-throws', () => Object.defineProperty(ns, 'fresh', { value: 1 }));
r('freeze', () => Object.freeze(ns));
r('seal', () => Object.seal(ns) === ns);
r('entries-values', () => [Object.entries(ns).map(([k]) => k), Object.values(ns).length]);
r('assign-from', () => Object.keys(Object.assign({}, ns)));
r('spread', () => Object.keys({ ...ns }));
r('json', () => JSON.stringify(ns));
r('names', () => Object.getOwnPropertyNames(ns));
r('gopds', () => Object.keys(Object.getOwnPropertyDescriptors(ns)));
r('for-in', () => { const ks = []; for (const k in ns) ks.push(k); return ks; });
r('reflect-get-receiver', () => Reflect.get(ns, 'b', {}));
r('lookupGetter', () => ({}).__lookupGetter__.call(ns, 'b'));
r('typeof', () => [typeof ns, ns instanceof Object, Array.isArray(ns)]);
"""


def test_module_namespace_object(run, workdir):
    """CATCHES: module namespace exotic objects with a prototype, extensibility, writable/configurable exports, wrong [[DefineOwnProperty]]/[[Set]]/[[Delete]] results or errors, stale (non-live) bindings, or wrong key order/@@toStringTag."""
    write_files(workdir, {"lib.mjs": NS_LIB, "main.mjs": NS_MAIN})
    _ok(run(["main.mjs"]), "module_namespace_object")
