"""node:events (EventEmitter, once/on helpers, captureRejections, EventTarget), node:stream (Readable,
Writable, Duplex, Transform, PassThrough, pipeline/finished and their promise forms, stream/consumers,
state predicates), node:readline over piped stdin and the offline-deterministic parts of node:dns."""

from conftest import check_script, resources_for

G = resources_for(__file__)


def test_emitter_listener_order_and_meta_events(run, workdir):
    """CATCHES: wrong listener ordering for on/prependListener/once/prependOnceListener, once wrappers
    leaking through listeners() (rawListeners must show them), `this` not bound to the emitter, wrong
    newListener/removeListener meta-event sequencing, removal during emit disturbing the current dispatch,
    and wrong eventNames ordering (strings before symbols) or emit() return values."""
    check_script(run, workdir, G, "emitter_listener_order_and_meta_events", r'''
const EventEmitter = require("events");
const e = new EventEmitter();
const log = [];
e.on("newListener", (ev, fn) => log.push(`new:${String(ev)}:${fn.name}`));
e.on("removeListener", (ev, fn) => log.push(`rm:${String(ev)}:${fn.name}`));
function a(x) { log.push(`a(${x}) this=${this === e}`); }
function b(x) { log.push(`b(${x})`); }
function c(x) { log.push(`c(${x})`); }
console.log(e.on("x", a) === e, e.addListener("x", b) === e);
e.prependListener("x", c);
e.once("x", function onceFn(x) { log.push(`once(${x})`); });
e.prependOnceListener("x", function pOnce(x) { log.push(`pOnce(${x})`); });
console.log(e.listenerCount("x"), e.listeners("x").map((f) => f.name).join(","), e.rawListeners("x").map((f) => f.name).join(","));
console.log(e.emit("x", 1), e.emit("x", 2), e.emit("nothing"));
console.log(e.off("x", b) === e, e.removeListener("x", function notThere() {}) === e);
console.log(e.listenerCount("x"), e.eventNames().map(String).join(","));
e.removeAllListeners("x");
console.log(e.listenerCount("x"), e.eventNames().map(String).join(","));
e.removeAllListeners();
console.log("after removeAll", e.eventNames().length, e.listenerCount("removeListener"));
console.log(log.join("\n"));
const sym = Symbol("s"); const e2 = new EventEmitter.EventEmitter();
e2.on(sym, () => {}); e2.on("str", () => {}); e2.on("str", () => {});
console.log(e2.eventNames().map(String).join(","), EventEmitter.listenerCount(e2, "str"), e2.listenerCount(sym), e2.getMaxListeners(), EventEmitter.defaultMaxListeners);
const e3 = new EventEmitter();
let n = 0;
e3.on("ev", function self() { n++; e3.removeListener("ev", self); });
e3.on("ev", () => { n += 10; });
e3.on("ev", () => { e3.on("ev", () => { n += 100; }); });
e3.emit("ev"); e3.emit("ev");
console.log("n", n, e3.listenerCount("ev"));
const raw = new EventEmitter();
const onceRaw = () => console.log("raw once ran");
raw.once("r", onceRaw);
const wrapper = raw.rawListeners("r")[0];
console.log(wrapper === onceRaw, wrapper.listener === onceRaw, raw.listeners("r")[0] === onceRaw);
wrapper(); wrapper(); console.log("after wrapper", raw.listenerCount("r"));
const plain = Object.assign(Object.create(EventEmitter.prototype), { tag: "mixin" });
plain.on("hi", function () { console.log("mixin emitter", this.tag); });
plain.emit("hi");
class Sub extends EventEmitter { constructor() { super(); this.kind = "sub"; } }
const sub = new Sub(); sub.once("go", function (...args) { console.log("subclass", this.kind, JSON.stringify(args)); });
sub.emit("go", 1, "two", [3]);
console.log(sub instanceof EventEmitter, typeof EventEmitter.init, typeof EventEmitter.errorMonitor, EventEmitter.captureRejectionSymbol === Symbol.for("nodejs.rejection"), EventEmitter.usingDomains);
''')


def test_emitter_errors_and_listener_limits(run, workdir):
    """CATCHES: an unhandled 'error' event not throwing (Error instances are thrown as-is, other values are
    wrapped in "Unhandled 'error' event" with a .context), wrong listener/setMaxListeners validation messages,
    and a MaxListenersExceededWarning that is missing, printed to stdout, repeated, or worded differently
    (it must fire once per event name, only past the limit, never when the limit is 0)."""
    check_script(run, workdir, G, "emitter_errors_and_listener_limits", r'''
const EventEmitter = require("events");
const e = new EventEmitter();
for (const v of [new TypeError("unhandled boom"), "a string", undefined, { code: 7 }]) {
  try { e.emit("error", v); } catch (err) { console.log("thrown", err === v, err.name, err.message, JSON.stringify(err.context)); }
}
e.on("error", (er) => console.log("handled", er.message)); console.log(e.emit("error", new Error("caught")));
for (const f of [() => e.on("x", "notfn"), () => e.once("x", null), () => e.prependListener("x", 5), () => e.removeListener("x", {}), () => e.setMaxListeners(-1), () => e.setMaxListeners("3"), () => EventEmitter.setMaxListeners(NaN)]) {
  try { f(); console.log("no error"); } catch (err) { console.log(err.name + ": " + err.message); }
}
const lim = new EventEmitter();
console.log("chain", lim.setMaxListeners(2) === lim, lim.getMaxListeners(), EventEmitter.getMaxListeners(lim));
for (let i = 0; i < 4; i++) lim.on("leak", () => {});
console.log("after 4 leak listeners");
for (let i = 0; i < 11; i++) lim.on("other", () => {});
const unlimited = new EventEmitter(); unlimited.setMaxListeners(0);
for (let i = 0; i < 20; i++) unlimited.on("z", () => {});
const dflt = new EventEmitter();
for (let i = 0; i < 10; i++) dflt.on("ten", () => {});
console.log("10 is fine");
dflt.on("ten", () => {});
for (let i = 0; i < 11; i++) dflt.on(Symbol.for("sy"), () => {});
const et = new EventTarget();
EventEmitter.setMaxListeners(5, et, dflt);
console.log("static", EventEmitter.getMaxListeners(et), dflt.getMaxListeners(), EventEmitter.getMaxListeners(new EventTarget()));
console.log("done", lim.listenerCount("leak"), unlimited.listenerCount("z"));
''', stderr="MaxListenersExceededWarning: Possible EventEmitter memory leak detected. 3 leak listeners added. "
            "Use emitter.setMaxListeners() to increase limit\n"
            "MaxListenersExceededWarning: Possible EventEmitter memory leak detected. 3 other listeners added. "
            "Use emitter.setMaxListeners() to increase limit\n"
            "MaxListenersExceededWarning: Possible EventEmitter memory leak detected. 11 ten listeners added. "
            "Use emitter.setMaxListeners() to increase limit\n"
            "MaxListenersExceededWarning: Possible EventEmitter memory leak detected. 11 Symbol(sy) listeners added. "
            "Use emitter.setMaxListeners() to increase limit\n")


def test_uncaught_emitter_error_exits_1(run, workdir):
    """CATCHES: an 'error' emitted with no listener being swallowed instead of terminating the script with
    `Uncaught <Name>: <message>` and exit code 1, or code after the emit still running."""
    check_script(run, workdir, G, "uncaught_emitter_error", r'''
const EventEmitter = require("events");
const e = new EventEmitter();
e.on("data", (d) => console.log("data", d));
e.emit("data", 1);
e.emit("error", new RangeError("nobody listens"));
console.log("never printed");
''', rc=1, stderr="Uncaught RangeError: nobody listens\n")


def test_events_once_on_and_capture_rejections(run, workdir):
    """CATCHES: events.once() not resolving with the argument array, not rejecting on 'error' or not
    cleaning up its listeners, ignoring an aborted signal; events.on() async iterators not queueing events,
    not ending on a `close` event or not rejecting on 'error'; captureRejections not routing async listener
    rejections to 'error'; and EventTarget dispatch/dedupe/once/preventDefault semantics."""
    check_script(run, workdir, G, "events_once_on_and_capture_rejections", r'''
const EventEmitter = require("events");
(async () => {
  const em = new EventEmitter();
  setTimeout(() => em.emit("ready", 1, "two"), 1);
  console.log("once ->", JSON.stringify(await EventEmitter.once(em, "ready")), em.listenerCount("ready"), em.listenerCount("error"));
  setTimeout(() => em.emit("error", new Error("failed early")), 1);
  try { await EventEmitter.once(em, "never"); } catch (err) { console.log("once rejected", err.message, em.listenerCount("never"), em.listenerCount("error")); }
  setTimeout(() => em.emit("error", new Error("as value")), 1);
  console.log("once(error)", (await EventEmitter.once(em, "error"))[0].message);
  const ac = new AbortController(); ac.abort();
  try { await EventEmitter.once(em, "x", { signal: ac.signal }); } catch (err) { console.log("aborted", err.name); }
  const ac2 = new AbortController();
  setTimeout(() => ac2.abort(), 1);
  try { await EventEmitter.once(em, "y", { signal: ac2.signal }); } catch (err) { console.log("aborted later", err.name, em.listenerCount("y")); }
  const it = EventEmitter.on(em, "tick", { close: ["done"] });
  queueMicrotask(() => { em.emit("tick", 1); em.emit("tick", 2, "b"); em.emit("done"); em.emit("tick", 3); });
  for await (const args of it) console.log("tick", JSON.stringify(args));
  console.log("after on", em.listenerCount("tick"), em.listenerCount("done"));
  const it2 = EventEmitter.on(em, "data");
  queueMicrotask(() => { em.emit("data", "x"); em.emit("data", "y"); em.emit("error", new Error("iter err")); });
  try { for await (const args of it2) console.log("data", args[0]); } catch (err) { console.log("on rejected", err.message); }
  const it3 = EventEmitter.on(em, "item");
  em.emit("item", "queued-before-next");
  console.log("next", JSON.stringify(await it3.next()), JSON.stringify(await it3.return()), JSON.stringify(await it3.next()), em.listenerCount("item"));
  const cap = new EventEmitter({ captureRejections: true });
  cap.on("error", (err) => console.log("captured", err.message));
  cap.on("job", async () => { throw new Error("async listener failed"); });
  console.log("emit job", cap.emit("job"));
  await new Promise((r) => setTimeout(r, 5));
  const et = new EventTarget();
  const h = (ev) => console.log("ET", ev.type, ev instanceof Event, JSON.stringify(ev.detail), ev.target === et, ev.defaultPrevented);
  et.addEventListener("ping", h);
  et.addEventListener("ping", h);
  et.addEventListener("ping", (ev) => { ev.preventDefault(); console.log("second", ev.cancelable, ev.defaultPrevented); }, { once: true });
  et.addEventListener("ping", { handleEvent(ev) { console.log("handleEvent object", ev.type); } });
  console.log("dispatch1", et.dispatchEvent(new CustomEvent("ping", { detail: { n: 1 }, cancelable: true })));
  console.log("dispatch2", et.dispatchEvent(new Event("ping")));
  et.removeEventListener("ping", h);
  console.log("dispatch3", et.dispatchEvent(new Event("ping")));
  const ev = new Event("t", { bubbles: true });
  console.log(ev.type, ev.bubbles, ev.cancelable, ev.composed, ev.isTrusted, new CustomEvent("c").detail);
})();
''')


def test_readable_buffering_and_reads(run, workdir):
    """CATCHES: wrong Readable buffering: push() return values against highWaterMark, read(n) splitting and
    joining chunks, read() returning null until enough data or end, size validation, objectMode counting
    items not bytes, setEncoding/encoding option decoding, readable flags after end, and once('data')
    resuming the stream; also the default highWaterMarks (65536 / 16)."""
    check_script(run, workdir, G, "readable_buffering_and_reads", r'''
const { Readable, Duplex } = require("stream");
const r = new Readable({ highWaterMark: 5 });
console.log("push", r.push(Buffer.from("abc")), r.push(Buffer.from("def")), r.readableLength, r.readableHighWaterMark, r.readableObjectMode, r.readable);
console.log("read", r.read(4).toString(), r.readableLength, r.read(10), r.read(2).toString(), r.readableLength, r.read(), r.read(0));
for (const n of [-1, 1.5]) { try { r.read(n); } catch (e) { console.log(e.name + ": " + e.message); } }
r.push(Buffer.from("tail")); r.push(null);
console.log("after end", r.read(10).toString(), r.read(), r.readable, r.push(Buffer.from("late")));
r.on("end", () => console.log("r end event"));
const o = new Readable({ objectMode: true, highWaterMark: 2 });
console.log("obj", o.push({ id: 1 }), o.push("s"), o.push(3), o.readableLength, JSON.stringify(o.read()), o.read(), o.readableLength, o.readableObjectMode);
const enc = new Readable({ encoding: "hex" }); enc.push(Buffer.from("AB"));
console.log("enc", JSON.stringify(enc.read()), enc.read());
const s2 = new Readable(); s2.setEncoding("utf-8"); s2.push(Buffer.from("héllo"));
console.log("setEncoding", s2.read(3), s2.read(), s2.setEncoding("latin1") === s2);
const defaults = new Readable(), dobj = new Readable({ objectMode: true }), dx = new Duplex({ readableObjectMode: true, read() {}, write(c, e, cb) { cb(); } });
console.log("hwm", defaults.readableHighWaterMark, dobj.readableHighWaterMark, dx.readableObjectMode, dx.writableObjectMode, dx.readableHighWaterMark, dx.writableHighWaterMark);
const oneShot = new Readable();
oneShot.once("data", (chunk) => console.log("once data", chunk.toString(), oneShot.listenerCount("data")));
oneShot.on("end", () => console.log("once end"));
oneShot.push(Buffer.from("fast"));
oneShot.push(null);
const flowing = new Readable({ read() {} });
const got = [];
flowing.on("data", (c) => got.push(c.toString()));
flowing.push("x"); flowing.push("y");
console.log("flowing sync", JSON.stringify(got), flowing.readableLength);
queueMicrotask(() => { flowing.push("z"); console.log("flowing later", JSON.stringify(got)); flowing.push(null); });
flowing.on("end", () => console.log("flowing end", JSON.stringify(got)));
let reads = 0;
const counter = new Readable({ read() { reads++; } });
console.log("custom _read", typeof counter._read, reads);
''')


def test_writable_backpressure_cork_and_end(run, workdir):
    """CATCHES: write() returning the wrong backpressure flag or writableLength, 'drain' firing at the wrong
    time, writes completing out of order, end(chunk, cb) ordering versus 'finish', write-after-end errors
    (callback vs 'error' event), cork/uncork not batching into _writev, objectMode counting, and _final
    running before queued writes finish."""
    check_script(run, workdir, G, "writable_backpressure_cork_and_end", r'''
const { Writable } = require("stream");
const writes = [];
const w = new Writable({ highWaterMark: 3, write(chunk, enc, cb) { writes.push(`${chunk}:${enc}`); setTimeout(cb, 1); } });
w.on("drain", () => console.log("drain", w.writableLength));
w.on("finish", () => console.log("finish", writes.join(" ")));
console.log("write", w.write("ab"), w.write("cd"), w.write(Buffer.from("e")), w.writableLength, w.writableHighWaterMark, w.writable);
w.end("!", () => console.log("end cb"));
w.write("late", (err) => console.log("late cb", err.message));
const w2 = new Writable({ write(c, e, cb) { cb(); } });
w2.on("error", (err) => console.log("w2 error event", err.message));
w2.end(); console.log("w2 late write returns", w2.write("x"));
const wo = new Writable({ objectMode: true, write(c, e, cb) { cb(); } });
console.log("objw", wo.write({}), wo.write(null === null ? 0 : 1), wo.writableObjectMode, wo.writableHighWaterMark, wo.writableLength);
const order = [];
const fin = new Writable({
  write(c, e, cb) { order.push("write " + c); setTimeout(cb, 2); },
  final(cb) { order.push("final"); setTimeout(cb, 1); },
});
fin.on("finish", () => { order.push("finish"); console.log(order.join(" > ")); });
fin.write("1"); fin.write("2"); fin.end("3");
const batches = [];
const bw = new Writable({ write(c, e, cb) { batches.push("w:" + c); cb(); }, writev(chunks, cb) { batches.push("v:" + chunks.map((x) => `${x.chunk}/${x.encoding}`).join("+")); cb(); } });
bw.cork(); bw.write("1"); bw.write("2", "utf8"); bw.uncork(); bw.write("3"); bw.cork(); bw.cork(); bw.write("4"); bw.uncork(); bw.write("5"); bw.end();
bw.on("finish", () => console.log("batches", batches.join(" ")));
const errW = new Writable({ write(c, e, cb) { cb(new Error("disk full")); } });
errW.on("error", (err) => console.log("write error event", err.message));
errW.write("data", (err) => console.log("write cb error", err && err.message));
const big = new Writable({ highWaterMark: 4, write(c, e, cb) { cb(); } });
console.log("exact hwm", big.write("abc"), big.write("d"), big.writableLength);
''')


def test_transform_pipeline_and_consumers(run, workdir):
    """CATCHES: Transform/flush output ordering, PassThrough not forwarding, pipeline() not propagating a
    transform error to its callback (or calling it with a non-null value on success), stream/promises and
    stream.promises pipeline with async generator stages, Readable.from over arrays/generators, and
    stream/consumers text/json/buffer/arrayBuffer results."""
    check_script(run, workdir, G, "transform_pipeline_and_consumers", r'''
const { Readable, Writable, Transform, PassThrough, pipeline } = require("stream");
const sp = require("stream/promises");
const consumers = require("stream/consumers");
const upper = () => new Transform({ transform(chunk, enc, cb) { cb(null, chunk.toString().toUpperCase()); }, flush(cb) { cb(null, "[flushed]"); } });
const sink = (label) => { const parts = []; return new Writable({ write(c, e, cb) { parts.push(c.toString()); cb(); }, final(cb) { console.log(label, "final", JSON.stringify(parts)); cb(); } }); };
(async () => {
  const out = [];
  for await (const chunk of Readable.from(["a", "b", "c"])) out.push(chunk);
  console.log("from array", JSON.stringify(out));
  async function* gen() { yield 1; yield { two: 2 }; yield "three"; }
  const fromGen = [];
  for await (const v of Readable.from(gen(), { objectMode: true })) fromGen.push(v);
  console.log("from gen", JSON.stringify(fromGen));
  const strs = []; for await (const v of Readable.from("whole string")) strs.push(v);
  console.log("from string", JSON.stringify(strs));
  const ret = pipeline(Readable.from(["hello ", "world"]), upper(), sink("p1"), (err) => console.log("pipeline cb", err));
  console.log("pipeline returns last", ret instanceof Writable);
  await new Promise((r) => setTimeout(r, 5));
  await sp.pipeline(Readable.from(["q"]), new PassThrough(), upper(), sink("p2"));
  console.log("promises pipeline resolved", sp.pipeline === require("stream").promises.pipeline);
  const failing = new Transform({ transform(c, e, cb) { cb(new Error("transform failed on " + c)); } });
  await new Promise((res) => pipeline(Readable.from(["bad"]), failing, sink("p3"), (err) => { console.log("pipeline err", err && err.message); res(); }));
  await sp.pipeline(Readable.from(["z", "y"]), async function* (source) { for await (const c of source) yield c + "!"; }, async (source) => { for await (const c of source) console.log("dest got", c); });
  console.log("gen pipeline ok");
  try { await sp.pipeline(Readable.from(["boom"]), async function* (source) { for await (const c of source) throw new Error("gen stage threw " + c); }, sink("p4")); }
  catch (e) { console.log("gen stage rejected", e.message); }
  try { pipeline(Readable.from(["x"])); } catch (e) { console.log(e.name + ": " + e.message); }
  const pt = new PassThrough(); const got = [];
  pt.on("data", (c) => got.push(c.toString())); pt.on("end", () => console.log("pt end", got.join("|")));
  pt.write("one"); pt.write("two"); pt.end("three");
  await new Promise((r) => setTimeout(r, 5));
  const counter = new Transform({ objectMode: true, transform(obj, e, cb) { this.n = (this.n || 0) + obj.v; cb(); }, flush(cb) { this.push({ total: this.n }); cb(); } });
  counter.on("data", (d) => console.log("objectMode transform", JSON.stringify(d)));
  for (const v of [1, 2, 3]) counter.write({ v });
  counter.end();
  await new Promise((r) => setTimeout(r, 5));
  console.log("text", await consumers.text(Readable.from([Buffer.from("con"), "sum"])), JSON.stringify(await consumers.json(Readable.from(['{"a":', '[1]}']))),
    (await consumers.buffer(Readable.from(["ab"]))).toString("hex"), (await consumers.arrayBuffer(Readable.from([Buffer.from("xyz")]))).byteLength,
    await consumers.text((async function* () { yield "async"; yield "-iter"; })()), (await consumers.blob(Readable.from(["blob!"]))).size);
})();
''')


def test_finished_destroy_and_state_predicates(run, workdir):
    """CATCHES: finished() not reporting success (null) for ended/finished streams, not reporting
    ERR_STREAM_PREMATURE_CLOSE for destroy() without error, or the destroy error; destroy() emitting
    error/close synchronously or twice; breaking out of for-await not destroying the stream; wrong
    isReadable/isWritable/isDisturbed/isErrored/isDestroyed predicates; duplexPair/compose/addAbortSignal."""
    check_script(run, workdir, G, "finished_destroy_and_state_predicates", r'''
const stream = require("stream");
const { Readable, Writable, PassThrough, finished } = stream;
const sp = require("stream/promises");
const tick = (ms = 3) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const r = new Readable({ read() {} });
  finished(r, (err) => console.log("finished readable", err));
  r.resume(); r.push("x"); r.push(null);
  await tick();
  const w = new Writable({ write(c, e, cb) { cb(); } });
  finished(w, (err) => console.log("finished writable", err));
  w.end("done");
  await tick();
  const d = new Readable({ read() {} });
  finished(d, (err) => console.log("premature", err.name, err.code, err.message));
  d.destroy();
  console.log("destroy is async", d.destroyed === undefined ? "no flag" : d.destroyed, stream.isDestroyed(d));
  await tick();
  const d2 = new Readable({ read() {} });
  d2.on("error", (e) => console.log("error event", e.message));
  d2.on("close", () => console.log("close event"));
  finished(d2, (err) => console.log("finished with", err.message));
  console.log("destroy returns stream", d2.destroy(new Error("kaput")) === d2);
  d2.destroy(new Error("ignored second"));
  await tick();
  try { await sp.finished(d2); console.log("sp.finished resolved"); } catch (e) { console.log("sp.finished rejected", e.message); }
  const pt = new PassThrough();
  stream.finished(pt, (err) => console.log("duplex finished after both sides", err));
  pt.on("data", () => {}); pt.end("both");
  await tick();
  const src = Readable.from([1, 2, 3, 4]);
  for await (const v of src) { console.log("iter", v); if (v === 2) break; }
  console.log("after break", stream.isDestroyed(src), src.readable);
  const r2 = new Readable({ read() {} });
  console.log("fresh", stream.isReadable(r2), stream.isDisturbed(r2), stream.isErrored(r2), stream.isDestroyed(r2), stream.isWritable(r2));
  r2.resume(); console.log("disturbed after resume", stream.isDisturbed(r2));
  r2.on("error", () => {}); r2.destroy(new Error("x"));
  console.log("after destroy", stream.isDestroyed(r2), stream.isErrored(r2), stream.isReadable(r2));
  const wd = new Writable({ write(c, e, cb) { cb(); } });
  console.log("writable fresh", stream.isWritable(wd), stream.isReadable(wd));
  wd.on("error", (e) => console.log("w error", e.message)); wd.on("close", () => console.log("w close", wd.writable, stream.isWritable(wd)));
  wd.destroy(new Error("w destroyed")); wd.destroy(new Error("second ignored"));
  await tick();
  const [a, b] = stream.duplexPair();
  b.on("data", (c) => console.log("b got", String(c)));
  b.on("end", () => console.log("b end"));
  a.write("ping"); a.end();
  await tick(5);
  const ac = new AbortController();
  const ar = stream.addAbortSignal(ac.signal, new Readable({ read() {} }));
  ar.on("error", (e) => console.log("abort err", e.name, e.message));
  ac.abort();
  await tick();
  const comp = stream.compose(new PassThrough(), new stream.Transform({ transform(c, e, cb) { cb(null, String(c).split("").reverse().join("")); } }));
  comp.on("data", (c) => console.log("composed", String(c)));
  comp.write("abc"); comp.end();
  await tick(5);
  const p = new Readable({ read() {} }); p.pause(); console.log("isPaused", p.isPaused()); p.push("q");
  p.on("data", (c) => console.log("data after resume", String(c)));
  await tick(); console.log("still paused", p.readableLength); p.resume();
  await tick();
  console.log(stream.Stream === stream, stream.Readable.prototype instanceof stream, new stream() instanceof require("events"), require("stream/web").ReadableStream === ReadableStream);
})();
''')


def test_stream_destroy_error_without_listener(run, workdir):
    """CATCHES: a destroy(err) with no 'error' listener crashing synchronously or with exit 1; the
    reference emits the error from a microtask, reports it as an unhandled rejection and still exits 0."""
    check_script(run, workdir, G, "stream_destroy_error_without_listener", r'''
const { Readable } = require("stream");
const r = new Readable({ read() {} });
r.on("close", () => console.log("close emitted"));
r.destroy(new Error("stream blew up"));
console.log("sync code continues");
''', stderr="Uncaught (in promise) Error: stream blew up\n")


def test_readline_lines_from_piped_stdin(run, workdir):
    """CATCHES: readline not splitting piped stdin into 'line' events, not stripping \\r from CRLF, merging
    empty lines, or not emitting 'close' at EOF; the reference DROPS a final line that has no trailing
    newline. Also async iteration over the interface (for await) yielding every line in order."""
    check_script(run, workdir, G, "readline_line_events", r'''
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin });
let n = 0;
rl.on("line", (line) => console.log(`line ${++n}: ${JSON.stringify(line)}`));
rl.on("close", () => console.log("closed after", n, "lines"));
console.log("registered", rl instanceof readline.Interface, rl instanceof require("events"));
''', input=b"first\r\nsecond\n\n  spaced  \n\xc3\xa9t\xc3\xa9\tTAB\nno newline at end")
    check_script(run, workdir, G, "readline_async_iterator", r'''
const readline = require("readline/promises");
(async () => {
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  const lines = [];
  for await (const line of rl) lines.push(line.toUpperCase());
  console.log(lines.length, JSON.stringify(lines));
})();
''', input="alpha\nbeta\n\ngamma\n")


def test_readline_question_prompts(run, workdir):
    """CATCHES: rl.question() not writing the prompt to the output stream, answering with the wrong line,
    consuming more than one line per question, or 'close' not firing after rl.close(); lines arriving
    while no question is pending must still be emitted as 'line' events."""
    check_script(run, workdir, G, "readline_question_prompts", r'''
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
const extra = [];
rl.question("Name? ", (name) => {
  rl.question("Age? ", (age) => {
    console.log(`\nHello ${name}, you are ${Number(age) + 1} next year`);
    rl.on("line", (l) => extra.push(l));
  });
});
rl.on("close", () => console.log("bye; extra lines:", JSON.stringify(extra)));
''', input="Ada\n36\nextra one\nextra two\n")


def test_dns_offline_lookups_and_unimplemented(run, workdir):
    """CATCHES: dns.lookup on IP literals not returning the literal with the right family (callback,
    {all:true} and promise forms), a family mismatch not failing with ENOTFOUND, the unbacked record types
    (SRV/NAPTR/CAA/lookupService) not failing asynchronously with ENOTIMP and Node-shaped code/syscall/
    hostname fields, wrong error-code constants, and Resolver server lists not being independent."""
    check_script(run, workdir, G, "dns_offline_lookups_and_unimplemented", r'''
const dns = require("dns");
const dnsp = require("dns/promises");
const lk = (...a) => new Promise((res) => dns.lookup(...a, (err, ...v) => res([err, ...v])));
console.log(dns.promises === dnsp, dns.NOTFOUND, dns.NOTIMP, dns.BADNAME, dns.ADDRCONFIG, dns.V4MAPPED, dns.ALL, dnsp.ALL, dnsp.CANCELLED, dns.getDefaultResultOrder());
dns.setDefaultResultOrder("ipv4first"); console.log(dnsp.getDefaultResultOrder());
dns.resolveSrv("_sip._tcp.example.com", (err) => console.log("srv", err.code, err.syscall, err.hostname, err.message));
dns.resolve("example.com", "naptr", (err) => console.log("naptr", err.code, err.syscall, err.message));
dns.lookupService("127.0.0.1", 22, (err) => console.log("svc", err.code, err.syscall, err.hostname, err.message));
console.log("sync section done");
(async () => {
  const [e1, addr, fam] = await lk("127.0.0.1"); console.log("lookup", e1, addr, fam);
  const [e2, addr6, fam6] = await lk("::1", { family: 6 }); console.log("lookup6", e2, addr6, fam6);
  const [e3, list] = await lk("10.1.2.3", { all: true }); console.log("all", e3, JSON.stringify(list));
  const [e4, a4] = await lk("192.168.0.1", 4); console.log("numeric family", e4, a4);
  const [mismatch] = await lk("127.0.0.1", 6); console.log("family mismatch", mismatch.name, mismatch.code, mismatch.message);
  console.log("plookup", JSON.stringify(await dnsp.lookup("127.0.0.1")), JSON.stringify(await dnsp.lookup("::1", { all: true })));
  try { await dnsp.resolveCaa("example.com"); } catch (e) { console.log("caa", e.code, e.syscall, e.message); }
  try { await dnsp.lookupService("::1", 80); } catch (e) { console.log("p svc", e.code, e.message); }
  const r = new dns.Resolver(); r.setServers(["1.1.1.1", "8.8.8.8"]); console.log(JSON.stringify(r.getServers()));
  console.log("independent", JSON.stringify(dns.getServers()) === JSON.stringify(new dns.Resolver().getServers()), Array.isArray(dns.getServers()));
  try { r.setServers("1.1.1.1"); } catch (e) { console.log(e.name + ": " + e.message); }
  r.resolveTlsa("example.com", (err) => console.log("tlsa", err.code, err.message));
  const pr = new dnsp.Resolver(); pr.setServers(["9.9.9.9"]); console.log(JSON.stringify(pr.getServers()), typeof pr.resolve4, typeof dns.resolveAny, typeof dns.reverse);
  try { await pr.resolveSoa("example.com"); } catch (e) { console.log("p soa", e.code, e.message); }
})();
''')
