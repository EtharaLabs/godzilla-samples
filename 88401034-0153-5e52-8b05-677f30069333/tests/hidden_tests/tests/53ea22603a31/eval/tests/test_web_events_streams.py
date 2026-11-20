"""Web platform event model, messaging, timers/microtasks, performance user timing, platform
globals, WHATWG streams (readable/writable/transform/byte/text/compression) and Blob/File/FormData."""

from conftest import check_script, resources_for

G = resources_for(__file__)

# Async-aware: prints `label value`, or `label THREW Name: message` (non-Errors as JSON).
SHOW = r'''
const show = async (label, f) => {
  try { console.log(label, await f()); }
  catch (e) { console.log(label, 'THREW', e instanceof Error ? e.name + ': ' + e.message : 'non-error ' + JSON.stringify(e)); }
};
'''


def test_event_target_dispatch_semantics(run, workdir):
    """CATCHES: EventTarget registering duplicate (callback, capture) pairs, treating capture=true
    as the same listener, ignoring handleEvent objects or `once`, wrong `this`/target/currentTarget,
    stopImmediatePropagation not halting later listeners, preventDefault working on non-cancelable
    events, listeners removed during dispatch still firing, or listeners added during dispatch
    firing in the same dispatch."""
    check_script(run, workdir, G, "event_target_dispatch_semantics", r'''
const t = new EventTarget();
const log = [];
const a = (e) => log.push('a:' + e.type + ':' + (e.target === t) + ':' + (e.currentTarget === t) + ':' + e.eventPhase);
t.addEventListener('x', a);
t.addEventListener('x', a);
t.addEventListener('x', a, true);
t.addEventListener('x', { handleEvent(e) { log.push('obj:' + (this !== t) + ':' + e.type); } });
t.addEventListener('x', function () { log.push('once:' + (this === t)); }, { once: true });
t.addEventListener('x', null);
const ev = new Event('x', { cancelable: true, bubbles: true });
console.log(t.dispatchEvent(ev), log.join(' '));
console.log(ev.currentTarget, ev.target === t, ev.bubbles, ev.cancelable);
const round = (label, type = 'x') => { log.length = 0; t.dispatchEvent(new Event(type)); console.log(label, JSON.stringify(log)); };
round('second dispatch');
t.removeEventListener('x', a);
round('after remove (bubble)');
t.removeEventListener('x', a, { capture: true });
round('after remove (capture)');
round('unknown type', 'nothing');
const t2 = new EventTarget();
t2.addEventListener('y', (e) => { log.push('1'); e.stopImmediatePropagation(); });
t2.addEventListener('y', () => log.push('2'));
log.length = 0; t2.dispatchEvent(new Event('y')); console.log('stopImmediate', log.join(' '));
const t3 = new EventTarget();
t3.addEventListener('z', (e) => e.preventDefault());
const nc = new Event('z'); console.log('non-cancelable', t3.dispatchEvent(nc), nc.defaultPrevented);
const c = new Event('z', { cancelable: true }); console.log('cancelable', t3.dispatchEvent(c), c.defaultPrevented);
const t6 = new EventTarget();
function g() { log.push('r2'); }
t6.addEventListener('r', () => { log.push('r1'); t6.removeEventListener('r', g); });
t6.addEventListener('r', g);
log.length = 0; t6.dispatchEvent(new Event('r')); console.log('removed during dispatch', log.join(' '));
const t7 = new EventTarget();
t7.addEventListener('add', () => { log.push('first'); t7.addEventListener('add', () => log.push('added-later')); });
log.length = 0; t7.dispatchEvent(new Event('add')); t7.dispatchEvent(new Event('add')); console.log('added during dispatch', log.join(' '));
class Counter extends EventTarget { constructor() { super(); this.n = 0; } }
const m = new Counter(); m.addEventListener('q', function () { this.n++; }); m.dispatchEvent(new Event('q')); m.dispatchEvent(new Event('q'));
console.log('subclass', m.n, m instanceof EventTarget);
const ac = new AbortController();
const t5 = new EventTarget();
t5.addEventListener('s', () => log.push('sig'), { signal: ac.signal });
log.length = 0; t5.dispatchEvent(new Event('s')); ac.abort(); t5.dispatchEvent(new Event('s'));
t5.addEventListener('s', () => log.push('late'), { signal: ac.signal }); t5.dispatchEvent(new Event('s'));
console.log('signal option', JSON.stringify(log));
''', filename="event_target_dispatch_semantics.mjs")


def test_event_listener_exceptions_are_reported(run, workdir):
    """CATCHES: a throwing listener aborting the dispatch loop or the program, the error going to
    stdout or being swallowed silently, or a different report format than
    'Uncaught (in event listener) Name: message' / 'Uncaught (in onabort) ...' on stderr."""
    check_script(run, workdir, G, "event_listener_exceptions_are_reported", r'''
const t = new EventTarget();
t.addEventListener('e', () => { throw new Error('boom'); });
t.addEventListener('e', () => console.log('second listener still runs'));
t.addEventListener('e', () => { throw 'plain string'; });
t.addEventListener('e', () => { throw new RangeError('third'); });
console.log('dispatch returned', t.dispatchEvent(new Event('e')));
const ac = new AbortController();
ac.signal.onabort = () => { throw new TypeError('in onabort'); };
ac.signal.addEventListener('abort', () => console.log('abort listener still runs'));
ac.abort();
console.log('after abort', ac.signal.aborted);
''', filename="event_listener_exceptions_are_reported.mjs",
        stderr="Uncaught (in event listener) Error: boom\nUncaught (in event listener) plain string\n"
               "Uncaught (in event listener) RangeError: third\nUncaught (in onabort) TypeError: in onabort\n")


def test_event_classes_fields(run, workdir):
    """CATCHES: Event/CustomEvent/MessageEvent/CloseEvent/ErrorEvent/PromiseRejectionEvent with
    wrong default field values, missing phase constants, init dictionaries not coerced (CloseEvent
    code masked to 16 bits, ErrorEvent colno as uint32), or missing required-argument TypeErrors."""
    check_script(run, workdir, G, "event_classes_fields", SHOW + r'''
const e = new Event('k');
console.log(e.type, e.bubbles, e.cancelable, e.composed, e.defaultPrevented, e.isTrusted, e.eventPhase, e.target, e.currentTarget, typeof e.timeStamp);
console.log(Event.NONE, Event.CAPTURING_PHASE, Event.AT_TARGET, Event.BUBBLING_PHASE);
console.log(new Event(42).type, new Event('i', null).bubbles, new Event('c', { composed: 1 }).composed);
await show('Event()', () => new Event());
await show('dispatch plain object', () => new EventTarget().dispatchEvent({ type: 'x' }));
const ce = new CustomEvent('c', { detail: { n: 1 } });
console.log(ce instanceof Event, ce.type, JSON.stringify(ce.detail), new CustomEvent('c').detail, new CustomEvent('c', { detail: undefined }).detail);
const me = new MessageEvent('message', { data: [1], origin: 'o', lastEventId: 7, ports: [] });
console.log(JSON.stringify(me.data), me.origin, me.lastEventId, Object.isFrozen(me.ports), me.source, new MessageEvent('m').data, JSON.stringify(new MessageEvent('m').origin));
const close = new CloseEvent('close', { code: 70000, reason: 'r', wasClean: true });
console.log(close.code, close.reason, close.wasClean, new CloseEvent('close').code, JSON.stringify(new CloseEvent('close').reason));
const ee = new ErrorEvent('error', { message: 'm', filename: 'f.js', lineno: 3, colno: -1, error: 5 });
console.log(ee.message, ee.filename, ee.lineno, ee.colno, ee.error, new ErrorEvent('error').error, new ErrorEvent('error').lineno);
await show('PromiseRejectionEvent()', () => new PromiseRejectionEvent('unhandledrejection'));
const p = Promise.resolve();
const pre = new PromiseRejectionEvent('unhandledrejection', { promise: p, reason: 'r' });
console.log(pre.promise === p, pre.reason, pre instanceof Event);
''', filename="event_classes_fields.mjs")


def test_abort_controller_and_signal(run, workdir):
    """CATCHES: AbortSignal that can be constructed directly, fires abort twice, uses the wrong
    default reason (must be DOMException AbortError 'signal is aborted without reason'), runs
    onabort after addEventListener listeners, ignores null/object reasons, or AbortSignal.any not
    following the first aborted input (including already-aborted inputs). Also checks that
    AbortSignal.timeout eventually aborts with a TimeoutError."""
    check_script(run, workdir, G, "abort_controller_and_signal", SHOW + r'''
const ac = new AbortController();
const s = ac.signal;
console.log(s instanceof AbortSignal, s instanceof EventTarget, s.aborted, s.reason, s.onabort);
const log = [];
s.addEventListener('abort', () => log.push('listener:' + s.aborted));
s.onabort = (e) => log.push('onabort:' + e.type);
s.throwIfAborted();
ac.abort();
console.log(log.join(' '), s.aborted, s.reason.name, s.reason.message, s.reason instanceof DOMException);
ac.abort('again');
console.log(log.length, s.reason.name);
await show('throwIfAborted', () => s.throwIfAborted());
for (const reason of [{ custom: 1 }, null, 0, undefined, new Error('why')]) {
  const c = new AbortController(); c.abort(reason);
  const r = c.signal.reason;
  console.log('reason', r instanceof Error ? r.name + ':' + r.message : JSON.stringify(r));
}
const sa = AbortSignal.abort();
console.log(sa.aborted, sa.reason.name, sa.reason.message, AbortSignal.abort('x').reason);
await show('new AbortSignal', () => new AbortSignal());
const x = new AbortController(), y = new AbortController();
const any = AbortSignal.any([x.signal, y.signal]);
any.addEventListener('abort', () => log.push('any:' + any.reason));
console.log(any.aborted);
y.abort('from-y'); x.abort('from-x');
console.log(any.aborted, any.reason, log[log.length - 1]);
const pre = AbortSignal.any([new AbortController().signal, AbortSignal.abort('pre')]);
console.log(pre.aborted, pre.reason, AbortSignal.any([]).aborted);
const ts = AbortSignal.timeout(5);
console.log('timeout signal initially', ts.aborted);
ts.addEventListener('abort', () => console.log('timeout fired', ts.reason.name, ts.reason.message, ts.reason instanceof DOMException));
''', filename="abort_controller_and_signal.mjs")


def test_dom_exception_shape(run, workdir):
    """CATCHES: DOMException not being an Error subclass, wrong default name ('Error') / message
    (''), name not stringified, or wrong String() rendering. Pins that the reference has no legacy
    numeric `code` property or ABORT_ERR-style constants."""
    check_script(run, workdir, G, "dom_exception_shape", r'''
const de = new DOMException('msg', 'NotFoundError');
console.log(de.name, de.message, de instanceof Error, de instanceof DOMException, String(de), Object.prototype.toString.call(de));
console.log(de.code, typeof DOMException.ABORT_ERR, 'code' in DOMException.prototype);
const d0 = new DOMException();
console.log(JSON.stringify(d0.name), JSON.stringify(d0.message), String(d0));
console.log(new DOMException('only msg').name, new DOMException('m', 42).name, new DOMException(undefined, 'X').message === '');
try { throw new DOMException('thrown', 'SyntaxError'); } catch (e) { console.log(e.name, e.message, e instanceof SyntaxError); }
const names = ['AbortError', 'DataCloneError', 'InvalidCharacterError', 'NotSupportedError', 'QuotaExceededError', 'InvalidStateError', 'TimeoutError'];
console.log(names.map((n) => new DOMException('', n).name).join());
''', filename="dom_exception_shape.mjs")


def test_message_channel_and_broadcast_channel(run, workdir):
    """CATCHES: postMessage delivering synchronously or by reference (later mutations visible),
    MessagePort not queuing messages until start() when using addEventListener, onmessage not
    implicitly starting the port, missing DataCloneError, BroadcastChannel echoing to the sender or
    to other channel names, receivers sharing one clone, or wrong InvalidStateError after close."""
    check_script(run, workdir, G, "message_channel_and_broadcast_channel", SHOW + r'''
const step = (ms) => new Promise((r) => setTimeout(r, ms));
const { port1, port2 } = new MessageChannel();
const obj = { n: 1, list: [1, 2] };
port2.onmessage = (e) => console.log('port2 got', JSON.stringify(e.data), e instanceof MessageEvent, e.type, JSON.stringify(e.origin), e.ports.length, e.data !== obj);
port1.postMessage(obj);
obj.n = 99;
port1.postMessage({ n: 2 });
console.log('posted (sync)', typeof port2.onmessage);
await show('clone error', () => port1.postMessage(() => 1));
await show('new MessagePort', () => new MessagePort());
await step(0);
port2.onmessage = null;
port1.postMessage('reverse?');
port2.addEventListener('message', (e) => console.log('must not be delivered after close', e.data));
port1.close(); port2.close();
const ch = new MessageChannel();
ch.port2.addEventListener('message', (e) => console.log('listener got', e.data));
ch.port1.postMessage('queued until start');
ch.port2.onmessageerror = () => {};
await step(0);
console.log('before start');
ch.port2.start();
await step(0);
ch.port1.close();
ch.port2.close();
const b1 = new BroadcastChannel('chan'), b2 = new BroadcastChannel('chan'), b3 = new BroadcastChannel('chan'), other = new BroadcastChannel('other');
b2.onmessage = (e) => console.log('b2', JSON.stringify(e.data), e instanceof MessageEvent);
b3.addEventListener('message', (e) => { e.data.x = 'mutated by b3'; console.log('b3', JSON.stringify(e.data)); });
b2.addEventListener('message', (e) => console.log('b2 listener sees', JSON.stringify(e.data)));
other.onmessage = () => console.log('other channel must not get it');
b1.onmessage = () => console.log('sender must not get its own message');
b1.postMessage({ x: 1 });
console.log(b1.name, typeof b1.onmessage, other.name);
await step(0);
for (const c of [b1, b2, b3, other]) c.close();
await show('post after close', () => b1.postMessage(1));
await show('new BroadcastChannel()', () => new BroadcastChannel());
''', filename="message_channel_and_broadcast_channel.mjs")


def test_microtask_and_timer_ordering(run, workdir):
    """CATCHES: wrong event-loop phase order: microtasks (promise reactions and queueMicrotask) must
    drain before callbacks; process.nextTick and setImmediate share one FIFO callback queue with a
    microtask checkpoint after each; same-delay timers fire FIFO; callbacks queued from a callback
    run after the next timer phase; clearTimeout cancels; queueMicrotask rejects non-functions; a
    throwing microtask becomes an unhandled rejection but does not stop the loop."""
    check_script(run, workdir, G, "microtask_and_timer_ordering", r'''
const log = [];
setTimeout(() => log.push('t0-a'), 0);
setImmediate(() => log.push('immediate1'));
process.nextTick(() => log.push('tick1'));
setImmediate(() => { log.push('immediate2'); process.nextTick(() => { log.push('tick-in-immediate'); startInterval(); }); Promise.resolve().then(() => log.push('micro-in-immediate')); });
process.nextTick(() => { log.push('tick2'); queueMicrotask(() => log.push('micro-in-tick')); });
setTimeout(() => log.push('t0-b'), 0);
queueMicrotask(() => log.push('micro1'));
Promise.resolve().then(() => log.push('promise1')).then(() => log.push('promise2'));
queueMicrotask(() => { log.push('micro2'); queueMicrotask(() => log.push('micro-nested')); });
const id = setTimeout(() => log.push('cancelled'), 0);
clearTimeout(id);
queueMicrotask(() => { throw new Error('micro boom'); });
setTimeout(() => log.push('t0-after-throw'), 0);
let n = 0;
let iv;
function startInterval() {
  iv = setInterval(() => {
    if (n === 3) return; // guard: a firing batched before clearInterval took effect must not log
    log.push('iv' + (++n));
    if (n === 3) { clearInterval(iv); setTimeout(() => console.log(log.join('\n')), 0); }
  }, 20);
}
log.push('sync');
try { queueMicrotask(5); } catch (e) { console.log(e.name + ': ' + e.message); }
const tmp = setInterval(() => {}, 1000);
clearInterval(tmp);
console.log(typeof id, typeof tmp);
''', filename="microtask_and_timer_ordering.mjs", stderr="Uncaught (in promise) Error: micro boom\n")


def test_report_error_and_global_handlers(run, workdir):
    """CATCHES: reportError not printing 'Uncaught ...' to stderr or stopping the program, onerror
    not receiving (message, source, lineno, colno, error) or its `true` return not suppressing the
    default report, onunhandledrejection's preventDefault() not suppressing 'Uncaught (in
    promise)', or an onerror-handled uncaught timer exception terminating the process."""
    check_script(run, workdir, G, "report_error_and_global_handlers", r'''
console.log(globalThis.onerror, globalThis.onunhandledrejection);
reportError(new TypeError('reported one'));
console.log('continues');
globalThis.onerror = (msg, src, line, col, err) => { console.log('onerror:', msg, JSON.stringify(src), line, col, err instanceof RangeError); return true; };
reportError(new RangeError('handled'));
globalThis.onerror = (msg) => { console.log('onerror not suppressing:', msg); };
reportError('plain string');
globalThis.onerror = null;
try { reportError(); } catch (e) { console.log(e.name + ': ' + e.message); }
globalThis.onunhandledrejection = (e) => { console.log('unhandled:', e.type, e.reason.message, e.cancelable); e.preventDefault(); };
Promise.reject(new Error('rej1'));
setTimeout(() => {
  globalThis.onunhandledrejection = (e) => console.log('seen but not prevented', e.reason);
  Promise.reject('rej2');
}, 0);
setTimeout(() => {
  globalThis.onerror = (m) => { console.log('onerror for uncaught:', m); return true; };
  setTimeout(() => { throw new Error('uncaught in timer'); }, 0);
  setTimeout(() => console.log('still alive after handled uncaught'), 40);
}, 30);
''', filename="report_error_and_global_handlers.mjs",
        stderr="Uncaught TypeError: reported one\nUncaught plain string\nUncaught (in promise) rej2\n")


def test_performance_marks_and_measures(run, workdir):
    """CATCHES: performance.mark/measure ignoring explicit startTime/duration/detail options,
    computing measure durations from the wrong marks, wrong entry shapes or toJSON, getEntries*
    filters or clearMarks/clearMeasures not working, missing-mark errors, or PerformanceObserver not
    batching entries into one asynchronous callback. Uses explicit start times only (no clock
    readings are printed)."""
    check_script(run, workdir, G, "performance_marks_and_measures", SHOW + r'''
const m1 = performance.mark('start', { startTime: 10, detail: { phase: 1 } });
const m2 = performance.mark('end', { startTime: 25.5 });
console.log(m1.name, m1.entryType, m1.startTime, m1.duration, JSON.stringify(m1.detail), m2.detail, JSON.stringify(m1));
const ms = performance.measure('span', 'start', 'end');
console.log(ms.name, ms.entryType, ms.startTime, ms.duration, ms.detail);
const ms2 = performance.measure('obj', { start: 'start', duration: 4, detail: 'd' });
console.log(ms2.startTime, ms2.duration, ms2.detail);
const ms3 = performance.measure('nums', { start: 1, end: 3 });
console.log(ms3.startTime, ms3.duration);
await show('missing mark', () => performance.measure('x', 'nope', 'end'));
console.log(performance.getEntries().map((e) => e.entryType + ':' + e.name).join(' '));
console.log(performance.getEntriesByType('mark').map((e) => e.name).join(), performance.getEntriesByName('span').length, performance.getEntriesByName('span', 'mark').length);
performance.clearMarks('start'); console.log(performance.getEntriesByType('mark').map((e) => e.name).join());
performance.clearMeasures(); console.log(performance.getEntriesByType('measure').length);
performance.clearMarks(); console.log(performance.getEntries().length);
const live = performance.mark('now');
console.log(typeof live.startTime, live.startTime >= 0, typeof performance.now(), typeof performance.timeOrigin, performance instanceof Performance, Object.keys(performance.toJSON()).join());
const { PerformanceObserver } = await import('node:perf_hooks');
const obs = new PerformanceObserver((list, o) => {
  console.log('observed', list.getEntries().map((e) => e.name + '@' + e.startTime).join(), o === obs, list.getEntriesByName('o2').length);
  obs.disconnect();
});
obs.observe({ entryTypes: ['mark'] });
performance.mark('o1', { startTime: 1 });
performance.mark('o2', { startTime: 2 });
performance.measure('not observed', { start: 1, end: 2 });
console.log('sync after marks');
''', filename="performance_marks_and_measures.mjs")


def test_platform_globals_present(run, workdir):
    """CATCHES: a runtime missing any WinterTC Minimum Common API global (or exposing it with the
    wrong typeof), `self` not aliasing globalThis, navigator.userAgent not 'lumen', or
    Symbol.toStringTag values on the stream/Blob classes differing."""
    check_script(run, workdir, G, "platform_globals_present", r'''
const names = ['fetch', 'Request', 'Response', 'Headers', 'URL', 'URLSearchParams', 'URLPattern', 'Blob', 'File',
  'FormData', 'TextEncoder', 'TextDecoder', 'TextEncoderStream', 'TextDecoderStream', 'ReadableStream',
  'ReadableStreamDefaultReader', 'ReadableStreamBYOBReader', 'ReadableStreamDefaultController',
  'ReadableByteStreamController', 'ReadableStreamBYOBRequest', 'WritableStream', 'WritableStreamDefaultWriter',
  'WritableStreamDefaultController', 'TransformStream', 'TransformStreamDefaultController',
  'ByteLengthQueuingStrategy', 'CountQueuingStrategy', 'CompressionStream', 'DecompressionStream', 'crypto',
  'Crypto', 'SubtleCrypto', 'CryptoKey', 'AbortController', 'AbortSignal', 'Event', 'EventTarget', 'CustomEvent',
  'ErrorEvent', 'CloseEvent', 'PromiseRejectionEvent', 'MessageChannel', 'MessagePort', 'MessageEvent',
  'BroadcastChannel', 'DOMException', 'WebAssembly', 'WebSocket', 'EventSource', 'structuredClone', 'atob', 'btoa',
  'queueMicrotask', 'reportError', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance',
  'Performance', 'navigator', 'console', 'onerror', 'onunhandledrejection', 'Lumen'];
for (let i = 0; i < names.length; i += 6) console.log(names.slice(i, i + 6).map((k) => k + ':' + typeof globalThis[k]).join(' '));
console.log(self === globalThis, typeof globalThis.self, navigator.userAgent, Object.keys(navigator).join());
console.log(Object.keys(Lumen).join(), typeof Lumen.version);
const tags = [new Blob([]), new File([], 'f'), new FormData(), new WritableStream(), new TransformStream(), new CountQueuingStrategy({ highWaterMark: 1 }), new ByteLengthQueuingStrategy({ highWaterMark: 1 })];
console.log(tags.map((o) => Object.prototype.toString.call(o)).join(' '));
''', filename="platform_globals_present.mjs")


def test_readable_stream_default_reader(run, workdir):
    """CATCHES: ReadableStream readers that do not lock the stream, allow a second reader, return
    the wrong {value, done} shapes after close, keep chunks queued before error(), resolve pending
    reads late or out of order, allow releasing with pending reads, or controllers reporting the
    wrong desiredSize / accepting enqueue after close."""
    check_script(run, workdir, G, "readable_stream_default_reader", SHOW + r'''
const rs = new ReadableStream({ start(c) { console.log('start desiredSize', c.desiredSize); c.enqueue('a'); c.enqueue('b'); c.close(); console.log('after close', c.desiredSize); } });
console.log(rs.locked);
const r = rs.getReader();
console.log(rs.locked, r instanceof ReadableStreamDefaultReader);
await show('second getReader', () => rs.getReader());
for (let i = 0; i < 4; i++) { const x = await r.read(); console.log('read', JSON.stringify(x.value), x.done, 'value' in x); }
console.log('closed ->', await r.closed);
r.releaseLock(); console.log('released', rs.locked);
await show('read after release', () => r.read());
let i = 0;
const pulled = new ReadableStream({ pull(c) { i++; if (i > 3) c.close(); else c.enqueue(i * 10); } });
const got = []; for await (const v of pulled) got.push(v); console.log('pulled', got.join(), 'pull calls', i);
const errs = new ReadableStream({ start(c) { c.enqueue(1); c.error(new TypeError('src fail')); console.log('errored desiredSize', c.desiredSize); } });
const er = errs.getReader();
await show('errored read', () => er.read());
await show('errored closed', () => er.closed);
await show('enqueue after close', () => { let ctl; new ReadableStream({ start(c) { ctl = c; } }); ctl.close(); ctl.enqueue(1); });
let ctl2;
const lazy = new ReadableStream({ start(c) { ctl2 = c; } });
const lr = lazy.getReader();
const p1 = lr.read(), p2 = lr.read();
setTimeout(() => { ctl2.enqueue('late1'); ctl2.enqueue('late2'); }, 0);
console.log('pending reads', JSON.stringify(await p1), JSON.stringify(await p2));
const p3 = lr.read();
await show('release with pending read', () => lr.releaseLock());
ctl2.close();
console.log('closed while pending', JSON.stringify(await p3));
await show('not a stream', () => new ReadableStreamDefaultReader({}));
''', filename="readable_stream_default_reader.mjs")


def test_readable_stream_tee_cancel_iteration(run, workdir):
    """CATCHES: tee() branches that do not both see every chunk, cancel() not calling the source's
    cancel with the reason, cancel() on a locked stream not rejecting, async iteration not
    cancelling the source on break (or cancelling despite preventCancel), or iteration leaving the
    stream locked."""
    check_script(run, workdir, G, "readable_stream_tee_cancel_iteration", SHOW + r'''
const src = (items, log) => new ReadableStream({
  start(c) { for (const x of items) c.enqueue(x); c.close(); },
  cancel(reason) { log.push('cancel:' + reason); },
});
const [t1, t2] = src(['p', 'q', 'r'], []).tee();
const a1 = []; for await (const v of t1) a1.push(v);
const a2 = []; for await (const v of t2) a2.push(v);
console.log('tee', a1.join(), '|', a2.join(), t1 instanceof ReadableStream);
const obj = { k: 1 };
const [s1, s2] = new ReadableStream({ start(c) { c.enqueue(obj); c.close(); } }).tee();
const o1 = (await s1.getReader().read()).value, o2 = (await s2.getReader().read()).value;
console.log('tee shares chunk objects', o1 === obj, o2 === obj);
const log = [];
const cs = new ReadableStream({ start(c) { c.enqueue(1); }, cancel(reason) { log.push('cancel:' + reason); return 'ignored'; } });
console.log('cancel resolves', await cs.cancel('why'), log.join());
const cr = cs.getReader(); console.log('read after cancel', JSON.stringify(await cr.read()));
const lockedS = new ReadableStream(); lockedS.getReader();
await show('cancel locked', () => lockedS.cancel());
const viaReader = new ReadableStream({ cancel(r) { log.push('reader-cancel:' + r); } });
const vr = viaReader.getReader(); await vr.cancel('rr'); console.log(log[log.length - 1], viaReader.locked);
await show('cancel throws', () => new ReadableStream({ cancel() { throw new Error('cancel failed'); } }).cancel());
const early = src([1, 2, 3], log);
for await (const v of early) { console.log('first', v); break; }
console.log(log[log.length - 1], early.locked);
const pc = src(['x', 'y'], log);
for await (const v of pc.values({ preventCancel: true })) { console.log('pc', v); break; }
console.log('preventCancel locked?', pc.locked, JSON.stringify(await pc.getReader().read()), log.length);
const done = src(['only'], log);
for await (const v of done) console.log('iterated', v);
console.log('after full iteration locked?', done.locked);
const it = src(['m', 'n'], log)[Symbol.asyncIterator]();
console.log(JSON.stringify(await it.next()), JSON.stringify(await it.return('rv')), it[Symbol.asyncIterator]() === it);
''', filename="readable_stream_tee_cancel_iteration.mjs")


def test_writable_stream_writer(run, workdir):
    """CATCHES: WritableStream writers that call sink.write concurrently or out of order, wrong
    desiredSize accounting against highWaterMark, close() not waiting for queued writes, sink
    errors not erroring the stream (later writes and `closed` must reject with the same error),
    abort() not reaching the sink, double getWriter() being allowed, or the controller lacking an
    AbortSignal. Pins that a write after close() resolves silently in the reference."""
    check_script(run, workdir, G, "writable_stream_writer", SHOW + r'''
const log = [];
const ws = new WritableStream({
  start(c) { log.push('start:' + (c.signal instanceof AbortSignal)); },
  write(chunk) { log.push('write-begin:' + chunk); return new Promise((r) => setTimeout(() => { log.push('write-end:' + chunk); r(); }, 1)); },
  close() { log.push('close'); },
  abort(r) { log.push('abort:' + r); },
}, { highWaterMark: 2 });
const w = ws.getWriter();
console.log(ws.locked, w.desiredSize, w instanceof WritableStreamDefaultWriter);
const p1 = w.write('a'); console.log('after write a', w.desiredSize);
const p2 = w.write('b'); console.log('after write b', w.desiredSize);
await p1; await p2; console.log('after awaits', w.desiredSize);
await w.ready;
await w.close();
console.log(log.join(' '));
console.log('desiredSize after close', w.desiredSize);
await show('write after close', () => w.write('c'));
await w.closed; console.log('closed resolved');
await show('second getWriter', () => { const s = new WritableStream(); s.getWriter(); return s.getWriter(); });
await show('close locked stream', () => { const s = new WritableStream(); s.getWriter(); return s.close(); });
const failing = new WritableStream({ write(ch) { if (ch === 2) throw new RangeError('no 2'); log.push('ok' + ch); } });
const fw = failing.getWriter();
await fw.write(1);
await show('failing write', () => fw.write(2));
await show('write after error', () => fw.write(3));
await show('closed rejects', () => fw.closed);
console.log('desiredSize errored', fw.desiredSize);
const ab = new WritableStream({ abort(r) { log.push('sink abort ' + r); } });
const aw = ab.getWriter();
console.log('abort resolves', await aw.abort('stop'), log[log.length - 1]);
await show('write after abort', () => aw.write(1));
const plain = new WritableStream();
console.log('close unlocked', await plain.close(), plain.locked);
aw.releaseLock();
await show('released writer', () => aw.write('x'));
await show('released desiredSize', () => aw.desiredSize);
''', filename="writable_stream_writer.mjs")


def test_transform_stream_and_piping(run, workdir):
    """CATCHES: TransformStream not supporting multiple enqueues per chunk, flush, identity default,
    terminate() or controller.error(); pipeTo not closing the destination (or closing it despite
    preventClose); errors mid-pipe not aborting the destination; chained pipeThrough losing order;
    or pipeThrough accepting a non-pair."""
    check_script(run, workdir, G, "transform_stream_and_piping", SHOW + r'''
const log = [];
const ts = new TransformStream({
  start(c) { log.push('start:' + (c instanceof TransformStreamDefaultController)); },
  transform(chunk, c) { c.enqueue(chunk * 2); c.enqueue(chunk * 2 + 1); },
  flush(c) { c.enqueue('end'); },
});
const tw = ts.writable.getWriter(); tw.write(1); tw.write(5); tw.close();
const out = []; for await (const v of ts.readable) out.push(v);
console.log(out.join(), log.join());
const id = new TransformStream();
const iw = id.writable.getWriter(); iw.write('same'); iw.write({ o: 1 }); iw.close();
for await (const v of id.readable) console.log('identity', JSON.stringify(v));
const term = new TransformStream({ transform(ch, c) { c.enqueue(ch); c.terminate(); } });
const tw2 = term.writable.getWriter();
await tw2.write('only');
await show('write after terminate', () => tw2.write('more'));
const tr = []; for await (const v of term.readable) tr.push(v); console.log('terminated readable', tr.join());
const errT = new TransformStream({ transform(ch, c) { c.error(new Error('tx fail')); } });
errT.writable.getWriter().write('x').catch(() => {});
await show('errored transform read', () => errT.readable.getReader().read());
const asyncT = new TransformStream({ async transform(ch, c) { await new Promise((r) => setTimeout(r, 1)); c.enqueue('[' + ch + ']'); } });
const aw = asyncT.writable.getWriter(); aw.write('a'); aw.write('b'); aw.close();
const ao = []; for await (const v of asyncT.readable) ao.push(v); console.log('async transform', ao.join());
const src = () => new ReadableStream({ start(c) { ['x', 'y', 'z'].forEach((s) => c.enqueue(s)); c.close(); } });
const sink = [];
await src().pipeTo(new WritableStream({ write(c) { sink.push(c); }, close() { sink.push('<closed>'); } }));
console.log('pipeTo', sink.join(' '));
const sink2 = [];
const dest = new WritableStream({ write(c) { sink2.push(c); }, close() { sink2.push('<closed>'); } });
const s1 = src();
await s1.pipeTo(dest, { preventClose: true });
console.log('preventClose', sink2.join(' '), dest.locked, s1.locked);
const chained = src()
  .pipeThrough(new TransformStream({ transform(c, ctl) { ctl.enqueue(c.toUpperCase()); } }))
  .pipeThrough(new TransformStream({ transform(c, ctl) { ctl.enqueue(c + c); } }));
const ou = []; for await (const v of chained) ou.push(v); console.log('chained', ou.join());
const bad = new ReadableStream({ start(c) { c.enqueue(1); }, pull(c) { c.error(new Error('mid-pipe')); } });
const seen = [];
await show('pipe error', () => bad.pipeTo(new WritableStream({ write(c) { seen.push('w' + c); }, abort(r) { seen.push('abort:' + r.message); } })));
console.log(seen.join());
await show('pipeThrough non-pair', () => src().pipeThrough({}));
''', filename="transform_stream_and_piping.mjs")


def test_byte_stream_byob_reader(run, workdir):
    """CATCHES: byte streams (type 'bytes') whose BYOB reader does not fill the caller's view
    across chunk boundaries, returns a view of the wrong type/length, mishandles the byobRequest
    respond() pull path, does not copy enqueued chunks, or BYOB readers being allowed on default
    streams (with the reference's TypeError messages)."""
    check_script(run, workdir, G, "byte_stream_byob_reader", SHOW + r'''
const bs = new ReadableStream({ type: 'bytes', start(c) { c.enqueue(new Uint8Array([1, 2, 3, 4, 5])); c.enqueue(new Uint16Array([0x0706])); c.close(); } });
const br = bs.getReader({ mode: 'byob' });
console.log(br instanceof ReadableStreamBYOBReader, bs.locked);
for (const size of [3, 10, 10, 4]) {
  const res = await br.read(new Uint8Array(size));
  console.log('read', size, res.done, res.value.constructor.name, '[' + res.value.join() + ']', res.value.byteLength, res.value.buffer.byteLength);
}
await show('byob on default stream', () => new ReadableStream().getReader({ mode: 'byob' }));
await show('byob reader ctor', () => new ReadableStreamBYOBReader(new ReadableStream()));
await show('byob read non-view', () => new ReadableStream({ type: 'bytes' }).getReader({ mode: 'byob' }).read([1]));
await show('bytes enqueue string', () => new ReadableStream({ type: 'bytes', start(c) { c.enqueue('str'); } }));
let n = 0;
const auto = new ReadableStream({ type: 'bytes', pull(c) {
  const req = c.byobRequest;
  if (n++ >= 2) { c.close(); return; }
  console.log('pull', n, req instanceof ReadableStreamBYOBRequest, req.view.length);
  req.view[0] = 100 + n; req.view[1] = 200 + n; req.respond(2);
} });
const ar = auto.getReader({ mode: 'byob' });
for (let k = 0; k < 3; k++) { const r = await ar.read(new Uint8Array(8)); console.log('auto', r.done, r.value.join()); }
const bd = new ReadableStream({ type: 'bytes', start(c) { const s = new Uint8Array([9, 9, 9]); c.enqueue(s); s[0] = 0; c.close(); console.log('byobRequest outside pull', c.byobRequest); } });
const dr = bd.getReader();
const d1 = await dr.read();
console.log('default reader on bytes', d1.value.constructor.name, d1.value.join(), JSON.stringify(await dr.read()));
const ib = new ReadableStream({ type: 'bytes', start(c) { c.enqueue(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8])); c.close(); } }).getReader({ mode: 'byob' });
const i16 = await ib.read(new Uint16Array(2));
console.log('u16 view', i16.value.constructor.name, i16.value.length, Array.from(new Uint8Array(i16.value.buffer)).join());
''', filename="byte_stream_byob_reader.mjs")


def test_text_encoder_decoder_streams(run, workdir):
    """CATCHES: TextEncoderStream emitting chunks for empty strings or non-Uint8Array chunks,
    TextDecoderStream with the wrong encoding/label validation, or broken chaining through
    pipeThrough. Pins the reference's non-streaming decode: a UTF-8 sequence split across two
    chunks decodes to two U+FFFD replacement characters."""
    check_script(run, workdir, G, "text_encoder_decoder_streams", SHOW + r'''
const tes = new TextEncoderStream();
console.log(tes.encoding, tes.readable instanceof ReadableStream, tes.writable instanceof WritableStream);
const tw = tes.writable.getWriter(); tw.write('hé'); tw.write(''); tw.write('€'); tw.write(7); tw.close();
const chunks = []; for await (const c of tes.readable) chunks.push(c.constructor.name + '[' + c.join() + ']');
console.log(chunks.join(' '));
const tds = new TextDecoderStream();
console.log(tds.encoding);
const dw = tds.writable.getWriter(); dw.write(new Uint8Array([0x68, 0xc3])); dw.write(new Uint8Array([0xa9, 0x21])); dw.close();
const texts = []; for await (const c of tds.readable) texts.push(JSON.stringify(c));
console.log('split sequence', texts.join(' '));
const whole = new TextDecoderStream('utf8');
const w2 = whole.writable.getWriter(); w2.write(new Uint8Array([0xe2, 0x82, 0xac])); w2.write(new Uint8Array([0xef, 0xbb, 0xbf, 0x41]).buffer); w2.close();
for await (const c of whole.readable) console.log('whole', JSON.stringify(c));
await show('unsupported label', () => new TextDecoderStream('latin1'));
const piped = new ReadableStream({ start(c) { c.enqueue('pipe '); c.enqueue('me 🌍'); c.close(); } })
  .pipeThrough(new TextEncoderStream()).pipeThrough(new TextDecoderStream());
let s = ''; for await (const c of piped) s += c; console.log(s);
''', filename="text_encoder_decoder_streams.mjs")


def test_compression_stream_roundtrip(run, workdir):
    """CATCHES: CompressionStream/DecompressionStream that do not round-trip for gzip, deflate (zlib)
    and deflate-raw, emit the wrong container headers (1f 8b / 78 9c), produce a different number
    of output chunks, or accept unknown formats. Also pins the reference's compressed sizes, as the
    WinterTC showcase does."""
    check_script(run, workdir, G, "compression_stream_roundtrip", SHOW + r'''
async function through(chunks, stream) {
  const rs = new ReadableStream({ start(c) { for (const ch of chunks) c.enqueue(ch); c.close(); } });
  const out = []; let n = 0;
  for await (const chunk of rs.pipeThrough(stream)) { out.push(...chunk); n++; }
  return [new Uint8Array(out), n];
}
const original = new TextEncoder().encode('compress me '.repeat(20));
for (const fmt of ['gzip', 'deflate', 'deflate-raw']) {
  const [z, n1] = await through([original.subarray(0, 100), original.subarray(100).buffer.slice(100)], new CompressionStream(fmt));
  const [u, n2] = await through([z.subarray(0, 5), z.subarray(5)], new DecompressionStream(fmt));
  console.log(fmt, original.length, '->', z.length, 'chunks', n1, '->', u.length, 'chunks', n2,
    new TextDecoder().decode(u) === new TextDecoder().decode(original), 'head', Array.from(z.subarray(0, 3)).join());
}
const [e, ne] = await through([], new CompressionStream('gzip'));
const [ee, nee] = await through([e], new DecompressionStream('gzip'));
console.log('empty gzip', e.length, ne, '->', ee.length, nee);
const bin = new Uint8Array(256).map((_, i) => (i * 7) & 255);
const [bz] = await through([bin], new CompressionStream('deflate'));
const [bu] = await through([bz], new DecompressionStream('deflate'));
console.log('binary roundtrip', bu.length, bu.every((b, i) => b === bin[i]));
const cs = new CompressionStream('gzip');
console.log(cs.readable instanceof ReadableStream, cs.writable instanceof WritableStream);
await show('bad format', () => new CompressionStream('brotli'));
await show('bad decompress format', () => new DecompressionStream('zip'));
await show('string chunk', async () => { const s = new CompressionStream('gzip'); return await s.writable.getWriter().write('text'); });
''', filename="compression_stream_roundtrip.mjs")


def test_decompression_foreign_data_and_errors(run, workdir):
    """CATCHES: a DecompressionStream that cannot inflate standard gzip/zlib/raw-deflate data made by
    another implementation (here Python's zlib), or that reports malformed input with different
    TypeError messages. Pins that the reference does NOT verify the gzip CRC32/ISIZE or zlib
    Adler-32 trailers."""
    check_script(run, workdir, G, "decompression_foreign_data_and_errors", SHOW + r'''
const GZ = [31, 139, 8, 0, 0, 0, 0, 0, 2, 3, 11, 201, 72, 85, 40, 44, 205, 76, 206, 86, 72, 42, 202, 47, 207, 83, 72, 203, 175, 80, 200, 42, 205, 45, 40, 86, 200, 47, 75, 45, 82, 40, 1, 74, 231, 36, 86, 85, 42, 164, 228, 167, 235, 41, 132, 208, 76, 49, 0, 88, 0, 30, 0, 135, 0, 0, 0];
const ZL = [120, 156, 11, 201, 72, 85, 40, 44, 205, 76, 206, 86, 72, 42, 202, 47, 207, 83, 72, 203, 175, 80, 200, 42, 205, 45, 40, 86, 200, 47, 75, 45, 82, 40, 1, 74, 231, 36, 86, 85, 42, 164, 228, 167, 235, 41, 132, 208, 76, 49, 0, 249, 60, 48, 118];
const RAW = ZL.slice(2, -4);
async function inflate(fmt, bytes, split = 3) {
  const rs = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(bytes.slice(0, split))); c.enqueue(new Uint8Array(bytes.slice(split))); c.close(); } });
  let out = '';
  for await (const chunk of rs.pipeThrough(new DecompressionStream(fmt))) out += new TextDecoder().decode(chunk);
  return JSON.stringify(out);
}
await show('gzip', () => inflate('gzip', GZ, 10));
await show('deflate', () => inflate('deflate', ZL));
await show('deflate-raw', () => inflate('deflate-raw', RAW, 7));
await show('zlib data as gzip', () => inflate('gzip', ZL));
await show('gzip data as deflate', () => inflate('deflate', GZ));
await show('gzip data as raw', () => inflate('deflate-raw', GZ));
await show('truncated gzip', () => inflate('gzip', GZ.slice(0, 30)));
await show('short zlib', () => inflate('deflate', [0x78, 0x00, 1, 2], 1));
const badCrc = GZ.slice(); badCrc[badCrc.length - 8] ^= 0xff;
await show('bad gzip crc', async () => (await inflate('gzip', badCrc)).length);
const badLen = GZ.slice(); badLen[badLen.length - 4] ^= 0x01;
await show('bad gzip isize', async () => (await inflate('gzip', badLen)).length);
const badAdler = ZL.slice(); badAdler[badAdler.length - 1] ^= 1;
await show('bad zlib adler', async () => (await inflate('deflate', badAdler)).length);
''', filename="decompression_foreign_data_and_errors.mjs")


def test_blob_and_file(run, workdir):
    """CATCHES: Blob concatenating parts incorrectly (strings as UTF-8, views honouring offsets,
    nested Blobs, other values stringified), type not lowercased / not cleared for non-ASCII,
    slice() not clamping negative or reversed ranges, stream() chunking differently, or File
    missing name/lastModified handling and the two-argument TypeError."""
    check_script(run, workdir, G, "blob_and_file", SHOW + r'''
const b = new Blob(['héllo ', new Uint8Array([0x00, 0x77, 0x6f]).subarray(1), new Uint16Array([0x6c72]).buffer, new Blob(['d']), 42], { type: 'Text/Plain;Charset=UTF-8' });
console.log(b.size, b.type, await b.text(), String(b), Object.prototype.toString.call(b));
console.log(new Uint8Array(await b.arrayBuffer()).join());
const by = await b.bytes(); console.log(by.constructor.name, by.length);
const s = b.slice(1, -2, 'x/y'); console.log(s.size, s.type, JSON.stringify(await s.text()));
console.log(JSON.stringify(await b.slice(-3).text()), JSON.stringify(await b.slice(5, 2).text()), b.slice().size, JSON.stringify(b.slice(0, 0).type), b.slice(100).size, b.slice(-100, 2).size);
console.log(new Blob().size, JSON.stringify(new Blob().type), new Blob([], { type: 'é' }).type === '', new Blob([], { type: 'A/B' }).type);
await show('string parts', () => new Blob('abc'));
await show('non-iterable parts', () => new Blob({}));
console.log(new Blob(new Set(['s', 'e', 't'])).size, new Blob(null).size);
const parts = []; for await (const c of b.stream()) parts.push(c.constructor.name + ':' + c.length);
console.log('stream chunks', parts.join());
const empty = []; for await (const c of new Blob([]).stream()) empty.push(c);
console.log('empty stream chunks', empty.length);
const f = new File(['abc'], 'name.txt', { type: 'text/plain', lastModified: 1234 });
console.log(f instanceof Blob, f instanceof File, f.name, f.size, f.type, f.lastModified, String(f), await f.text());
await show('File with one arg', () => new File(['x']));
console.log(typeof new File([], 'n').lastModified, new File([], 1).name, new File(['a'], 'n', { lastModified: '77' }).lastModified);
const fs = f.slice(1); console.log(fs instanceof File, fs instanceof Blob, await fs.text());
''', filename="blob_and_file.mjs")


def test_form_data_and_multipart_roundtrip(run, workdir):
    """CATCHES: FormData that does not wrap Blob values into Files named 'blob' (or with the given
    filename), set() not replacing the first and removing later entries, delete()/getAll()/has()
    errors, iteration order, a filename accepted with a string value, or multipart/form-data
    serialisation (boundary format, Content-Disposition/Content-Type part headers) and parsing
    back through Request.formData() differing. The random boundary is normalised."""
    check_script(run, workdir, G, "form_data_and_multipart_roundtrip", SHOW + r'''
const f = new File(['abc'], 'name.txt', { type: 'text/plain', lastModified: 0 });
const fd = new FormData();
fd.append('a', '1'); fd.append('a', 2); fd.append('file', new Blob(['xyz'], { type: 'text/x' }));
fd.append('named', new Blob(['q']), 'q.bin'); fd.append('f2', f); fd.append('quote"d', 'line1\nline2');
console.log(String(fd), fd.has('a'), fd.has('zz'), fd.get('zz'), JSON.stringify(fd.getAll('a')));
const fv = fd.get('file');
console.log(fv instanceof File, fv.name, fv.type, fd.get('named').name, fd.get('f2') === f);
fd.set('a', 'replaced'); console.log([...fd.keys()].join(), JSON.stringify(fd.getAll('a')));
fd.set('new', 'n'); fd.delete('named'); console.log([...fd.keys()].join());
console.log(JSON.stringify([...fd.entries()].map(([k, v]) => [k, typeof v === 'string' ? v : 'File:' + v.name])));
const fe = []; fd.forEach(function (v, k, o) { fe.push(k + ':' + (o === fd) + this.t); }, { t: '!' }); console.log(fe.join());
console.log([...fd.values()].length, [...fd].length);
await show('filename with string value', () => fd.append('x', 'str', 'file.txt'));
const req = new Request('http://x/', { method: 'POST', body: fd });
const norm = (s) => s.replace(/[0-9a-f]{32}/g, '<hex>').replace(/\r\n/g, '\\r\\n\n');
console.log(norm(req.headers.get('content-type')));
console.log(norm(await req.clone().text()));
const back = await req.formData();
console.log(JSON.stringify([...back].map(([k, v]) => [k, typeof v === 'string' ? v : [v.name, v.type, v.size]])));
const urlenc = new Response(new URLSearchParams('k=v+1&k=2&e=%C3%A9'));
console.log(urlenc.headers.get('content-type'));
const ufd = await urlenc.formData(); console.log(JSON.stringify([...ufd]));
await show('formData wrong type', () => new Response('plain').formData());
''', filename="form_data_and_multipart_roundtrip.mjs")
