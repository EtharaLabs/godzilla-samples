"""Node-compatible core modules: path, util, events, buffer, string_decoder, querystring, url, assert,
os/module/vm/timers, stream, zlib, readline and a few small builtins."""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


def _ok(r):
    assert (r.returncode, r.stderr) == (0, b""), r.stderr


PROG_PATH = r"""
const path = require("path");
const out = (...a) => console.log(...a);
out("join", path.join("/a/b", "../c", "./d"), path.join("a", "", "b/"), path.join(), path.join("..", "x", "../.."), path.join("a", null, "b"));
out("normalize", path.normalize("/a//b/../c/."), path.normalize("./x/../../y"), path.normalize(""), path.normalize("a/b/"), path.normalize("//a"), path.normalize("/.."), path.normalize("a/../.."));
out("resolve", path.resolve("/root", "x", "../y"), path.resolve("/a", "/b", "c"), path.resolve("/a/b/", ""), path.resolve("/", ".."));
out("resolve relative drops the leading slash", path.resolve("q") === process.cwd().slice(1) + "/q", path.resolve() === process.cwd().slice(1), path.isAbsolute(path.resolve("q")));
out("dirname", path.dirname("/a/b/c.txt"), path.dirname("a"), path.dirname("/"), path.dirname("a/b/"), path.dirname(""), path.dirname("/x"));
out("basename", path.basename("/a/b/c.txt"), path.basename("/a/b/c.txt", ".txt"), path.basename("/a/b/"), path.basename("c.txt", "c.txt"), JSON.stringify(path.basename("")), path.basename("x.js", "js"));
out("extname", path.extname("x.tar.gz"), JSON.stringify(path.extname(".bashrc")), path.extname("a."), JSON.stringify(path.extname("a")), path.extname("a/.b.c"), JSON.stringify(path.extname("a.b/")));
out("parse", JSON.stringify(path.parse("/home/u/file.txt")), JSON.stringify(path.parse("rel/x")), JSON.stringify(path.parse("/")), JSON.stringify(path.parse(".env")));
out("format", path.format({ dir: "/x", base: "y.js" }), path.format({ root: "/", name: "n", ext: ".e" }), path.format({ name: "n", ext: "e" }), path.format({ dir: "d", name: "n", ext: ".e", base: "b.f" }));
out("relative", path.relative("/a/b/c", "/a/d"), path.relative("/a", "/a/b/c"), JSON.stringify(path.relative("/x", "/x")), path.relative("/a/b", "/"), path.relative("/a/bc", "/a/b"));
out("isAbs", path.isAbsolute("/x"), path.isAbsolute("x"), path.isAbsolute(""), path.isAbsolute("./x"));
out("sep", path.sep, path.delimiter, path.posix === path, path.posix.sep, typeof path.win32.join);
out("win32", path.win32.join("C:\\a", "..", "b"), path.win32.sep, path.win32.delimiter, path.win32.basename("C:\\x\\y.txt"), path.win32.isAbsolute("C:\\x"), path.win32.normalize("C:/a/./b"), path.win32.dirname("C:\\x\\y"));
out("glob", path.matchesGlob("a/b/c.js", "a/**/*.js"), path.matchesGlob("a/c.ts", "a/*.js"), path.matchesGlob("abc", "a?c"));
out("ns", path.toNamespacedPath("/x"), path._makeLong("/y"));
const pp = require("path/posix"), pw = require("node:path/win32");
out("submodules", pp === path.posix, pw === path.win32);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_path_module(run, tier):
    """CATCHES: node:path join/normalize/resolve/dirname/basename/extname/parse/format/relative bugs,
    including the reference's quirks (resolve() of a relative path drops the leading '/', format() does
    not add a dot to a bare ext, win32 helpers), in any execution tier."""
    r = run([*tier, "-e", PROG_PATH])
    _ok(r)
    assert r.stdout == golden(__file__, "path")


PROG_INSPECT = r"""
const util = require("util");
const out = (...a) => console.log(...a);
const I = util.inspect;
out(I({ a: 1, s: "str", n: null, u: undefined, arr: [1, "two", [3, [4, [5, [6]]]]], nested: { x: { y: { z: { w: 1 } } } } }));
out(I([1, 2, 3]), I("q'uote"), I('dq"'), I(`b'"`), I(-0), I(10n), I(Symbol("s")), I(NaN), I(null), I(undefined), I(true));
out(I(function named() {}), I(() => {}), I(class Foo {}), I(class extends Array {}), I(async function af() {}), I(function* g() {}), I(Math.max), I(Object.assign(() => {}, { prop: 1 })));
out(I(new Map([[1, "a"], ["k", { v: 2 }]])), I(new Set([1, "x"])), I(new WeakMap()), I(new WeakSet()), I(new WeakRef({})), I(new Map()), I(new Set()));
out(I(new Date(0)), I(/re+/gi), I(new Error("boom")), I(new TypeError("bad thing")), I(new (class MyErr extends Error {})("m")), I({ err: new RangeError("r") }));
out(I(Buffer.from("abc")), I(new Uint8Array([1, 2])), I(new Float64Array(2)), I(new Int16Array([1, -2])), I(new ArrayBuffer(3)), I(new DataView(new ArrayBuffer(2))));
out(I(Promise.resolve(4)), I(new Promise(() => {})), I(Object.create(null)), I(Object.create({ inherited: 1 })));
const circ = { name: "c" }; circ.self = circ; circ.list = [circ];
out(I(circ));
class Pt { constructor() { this.x = 1; this.y = 2; } get g() { return 1; } }
out(I(new Pt()), I(Object.assign(Object.create(null), { a: 1 })), I(Object.defineProperty({}, "hidden", { value: 1, enumerable: false })));
out(I({ [Symbol("k")]: 1, "a-b": 2, 3: 4, get g() { return 1; }, set s(v) {}, valid_id: 5, $d: 6 }));
out(I("x".repeat(5)), I(new Array(5)), I([1, , 3]), I(Object.assign([1, 2], { extra: true })), I([undefined, null]), I([[]]), I({}), I([]));
out(I({ a: { b: { c: { d: {} } } } }, { depth: 0 }), I({ a: { b: { c: { d: {} } } } }, { depth: Infinity }), I({ x: [{ y: { z: 1 } }] }, { depth: 1 }), I([[1, [2, [3, [4]]]]]));
out(I(Array.from({ length: 120 }, (_, i) => i)));
out(I({ long1: "aaaaaaaaaaaaaaaaaaaa", long2: "bbbbbbbbbbbbbbbbbbbbbbbbb", long3: "cccccccccccccccccccccc", long4: 1234567 }));
out(I({ a: 1 }, { compact: false }), I([1, 2, 3], { maxArrayLength: 2 }), I("abcdefghij", { maxStringLength: 3 }), I({ b: 2, a: 1 }, { sorted: true }), I({ a: 1, b: "x" }, { colors: true }));
out(I(new Map([[{ a: 1 }, [1, 2]]])), I([new Set([[1]])]), I(new Map([[1, 2]]).entries()), I([1][Symbol.iterator]()));
out(I(new Proxy({ a: 1 }, {})), I(Object(1)), I(Object("s")), I(Object(true)), I(Object(Symbol("b"))), I(Number.prototype));
out(I({ toString() { return "x"; } }), I({ [util.inspect.custom]() { return "CUSTOM"; } }), I({ inner: { [util.inspect.custom]: (d) => ({ replaced: d }) } }), I({ f: function () {} }));
out(I("a\nb\tc\u0001"), I(["a\nb"]), I([1.5, -0, 0]), I(new (class X extends Map {})([[1, 2]])));
out(typeof util.inspect.custom, util.inspect.custom === Symbol.for("nodejs.util.inspect.custom"), JSON.stringify(util.inspect.defaultOptions));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_util_inspect(run, tier):
    """CATCHES: util.inspect formatting differences (depth/[Object]/[Array] elision, Map/Set/typed array/
    Buffer rendering, [Circular *1], class-name prefixes, quoting of keys, custom inspect symbol, line
    breaking at width 80, options like depth/sorted/maxArrayLength) in any execution tier."""
    r = run([*tier, "-e", PROG_INSPECT])
    _ok(r)
    assert r.stdout == golden(__file__, "inspect")


PROG_UTIL_MISC = r"""
const util = require("util");
const out = (...a) => console.log(...a);
out(util.format("%s|%d|%i|%f|%j|%o|%O|%%|%c", "str", "42.5", "42.9", "1.5", { a: [1] }, [1], { b: 2 }, "css"), util.format("extra", 1, { a: 1 }, "s"));
out(util.format("%s %s", "only"), util.format(1, 2), util.format("%d", "abc"), util.format("%s", Symbol("q")), util.format("%s", 12n), util.format("%d", 12n), util.format("%j", (() => { const c = {}; c.c = c; return c; })()), util.format("%s", { o: 1 }), util.format("%i", 3.9e2), util.format());
out(util.formatWithOptions({ depth: 0 }, "%O", { a: { b: 1 } }));
function Animal(n) { this.n = n; } Animal.prototype.speak = function () { return this.n + " speaks"; };
function Dog(n) { Animal.call(this, n); } util.inherits(Dog, Animal);
out(new Dog("rex").speak(), Dog.super_ === Animal, Object.getPrototypeOf(Dog.prototype) === Animal.prototype, new Dog("x") instanceof Animal);
const T = util.types;
out("types", [T.isDate(new Date()), T.isRegExp(/x/), T.isMap(new Map()), T.isSet(new Set()), T.isPromise(Promise.resolve()), T.isAsyncFunction(async () => {}), T.isGeneratorFunction(function* () {}), T.isTypedArray(new Int8Array()), T.isTypedArray(new DataView(new ArrayBuffer(1))), T.isUint8Array(Buffer.alloc(1)), T.isArrayBuffer(new ArrayBuffer(1)), T.isBoxedPrimitive(Object(1)), T.isBoxedPrimitive(1), T.isNativeError(new RangeError()), T.isProxy(new Proxy({}, {})), T.isProxy({}), T.isWeakMap(new WeakMap()), T.isMapIterator(new Map().keys()), T.isSetIterator(new Set().values()), T.isGeneratorObject((function* () {})()), T.isArgumentsObject((function () { return arguments; })()), T.isFloat64Array(new Float64Array()), T.isBigInt64Array(new BigInt64Array()), T.isExternal({}), T.isDataView(new DataView(new ArrayBuffer(1))), T.isAnyArrayBuffer(new ArrayBuffer(1)), T.isNumberObject(1), T.isStringObject(Object("s"))].map(Number).join(""));
out("legacy", util.isArray([]), util.isDate(new Date()), util.isRegExp(/a/), util.isError(new Error()));
const cbFn = (a, b, cb) => setTimeout(() => (a < 0 ? cb(new Error("neg")) : cb(null, a + b)), 0);
const p = util.promisify(cbFn);
const custom = function () {}; custom[util.promisify.custom] = () => Promise.resolve("custom!");
(async () => {
  out("promisify", await p(1, 2));
  try { await p(-1, 2); } catch (e) { out("promisify err", e.message); }
  out("custom", await util.promisify(custom)(), util.promisify(custom) === custom[util.promisify.custom], util.promisify.custom === Symbol.for("nodejs.util.promisify.custom"));
  try { util.promisify(42); } catch (e) { out("promisify bad", e.name, e.code, e.message); }
  const cbified = util.callbackify(async (x) => { if (x) throw new Error("cbErr"); return "val"; });
  await new Promise((r) => cbified(0, (e, v) => { out("callbackify", e, v); r(); }));
  await new Promise((r) => cbified(1, (e, v) => { out("callbackify err", e.message, v); r(); }));
  const cbNull = util.callbackify(() => Promise.reject(null));
  await new Promise((r) => cbNull((e) => { out("callbackify null", e.message, e.code, e.reason); r(); }));
  out("deepEq", util.isDeepStrictEqual({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] }), util.isDeepStrictEqual([1], ["1"]), util.isDeepStrictEqual(new Set([1, 2]), new Set([2, 1])), util.isDeepStrictEqual(new Map([[1, { x: 1 }]]), new Map([[1, { x: 2 }]])), util.isDeepStrictEqual(NaN, NaN), util.isDeepStrictEqual(0, -0), util.isDeepStrictEqual(new Date(1), new Date(1)), util.isDeepStrictEqual(Buffer.from("a"), Buffer.from("a")), util.isDeepStrictEqual(new Uint8Array([1]), new Uint8Array([1])), util.isDeepStrictEqual(/a/g, /a/g), util.isDeepStrictEqual({ a: undefined }, {}), util.isDeepStrictEqual(Object.create(null), {}));
  const dep = util.deprecate(() => "dep result", "this is deprecated", "DEP0999");
  out("deprecate", dep(), dep());
  out("strip", JSON.stringify(util.stripVTControlCharacters("\u001b[31mred\u001b[39m plain")));
  out("style", JSON.stringify(util.styleText("red", "R")), JSON.stringify(util.styleText(["bold", "underline"], "BU")));
  try { util.styleText("nocolor", "x"); } catch (e) { out("style err", e.name, e.code); }
  out("toUSV", JSON.stringify(util.toUSVString("a\ud800b")));
  out("sysErr", util.getSystemErrorName(-2), util.getSystemErrorName(-13), util.getSystemErrorMessage(-2), JSON.stringify(util.getSystemErrorMap().get(-17)));
  try { util.getSystemErrorName(5); } catch (e) { out("sysErr bad", e.name, e.code); }
  const { values, positionals } = util.parseArgs({ args: ["-f", "--bar", "b", "pos1", "--num=3", "--", "--after"], options: { foo: { type: "boolean", short: "f" }, bar: { type: "string" }, num: { type: "string" } }, allowPositionals: true });
  out("parseArgs", JSON.stringify(values), JSON.stringify(positionals));
  try { util.parseArgs({ args: ["--unknown"], options: {} }); } catch (e) { out("parseArgs err", e.code, e.message); }
  try { util.parseArgs({ args: ["pos"], options: {} }); } catch (e) { out("parseArgs err2", e.code, e.message); }
  try { util.parseArgs({ args: ["--s"], options: { s: { type: "string" } } }); } catch (e) { out("parseArgs err3", e.code, e.message); }
  const tk = util.parseArgs({ args: ["-ab", "x"], options: { a: { type: "boolean", short: "a" }, b: { type: "string", short: "b", multiple: true, default: ["d"] } }, tokens: true });
  out("tokens", JSON.stringify(tk.values), JSON.stringify(tk.tokens));
  out("parseEnv", JSON.stringify(util.parseEnv("A=1\n# comment\nB = 'two words'\nC=\"line\\nbreak\"\nexport D=4\nE=val # trailing\nF=`bt`")));
  const mt = new util.MIMEType("text/html; charset=UTF-8; q=\"a b\"");
  out("mime", mt.type, mt.subtype, mt.essence, mt.params.get("charset"), String(mt), JSON.stringify([...mt.params.keys()]), mt.params.has("q"), JSON.stringify(mt));
  mt.params.set("x", "y"); mt.params.delete("q");
  out("mime2", String(mt));
  out("misc", typeof util.TextEncoder, typeof util.TextDecoder, typeof util.debuglog("x"), util.debuglog("x").enabled, typeof util.aborted, typeof util.log);
  out("diff", JSON.stringify(util.diff(["a", "b", "c"], ["a", "c", "d"])));
})();
"""


def test_util_helpers(run):
    """CATCHES: util.format specifiers (%s/%d/%i/%f/%j/%o/%O/%%/%c and extra args), inherits, util.types
    predicates, promisify/callbackify (custom symbol, falsy rejection), isDeepStrictEqual, deprecate's
    one-time stderr warning, styleText, system error maps, parseArgs (errors, tokens), parseEnv, MIMEType."""
    r = run(["-e", PROG_UTIL_MISC])
    assert r.returncode == 0
    assert r.stderr == b"DeprecationWarning: [DEP0999] this is deprecated\n"
    assert r.stdout == golden(__file__, "util_misc")


PROG_EVENTS = r"""
const EventEmitter = require("events");
const { once, on, EventEmitter: EE2, errorMonitor, getEventListeners, setMaxListeners, listenerCount, captureRejectionSymbol } = require("events");
const out = (...a) => console.log(...a);
const e = new EventEmitter();
e.on("newListener", (ev) => out("newListener", String(ev)));
e.on("removeListener", (ev) => out("removeListener", String(ev)));
const f1 = (a, b) => out("f1", a, b);
e.on("x", f1);
e.prependListener("x", () => out("prepended"));
e.once("x", () => out("once"));
e.prependOnceListener("x", () => out("prependOnce"));
out("count", e.listenerCount("x"), EventEmitter.listenerCount(e, "x"), e.eventNames().map(String).join(","));
out("emit", e.emit("x", 1, 2));
out("emit2", e.emit("x", 3, 4), e.emit("nothing"));
e.off("x", f1);
out("after off", e.listenerCount("x"), e.listeners("x").length, e.rawListeners("x").length);
e.removeListener("x", () => {});
const s = Symbol("sym");
e.on(s, () => out("symbol event"));
e.emit(s);
try { e.emit("error", new Error("unhandled boom")); } catch (err) { out("error thrown", err.message); }
try { e.emit("error", "str"); } catch (err) { out("error thrown2", err.message, err.code); }
e.on(errorMonitor, (err) => out("monitor", err.message));
e.on("error", (err) => out("handled", err.message));
e.emit("error", new Error("E2"));
out("max", e.getMaxListeners(), EventEmitter.defaultMaxListeners);
e.setMaxListeners(1);
e.on("y", () => {}); e.on("y", () => {});
out("this", (() => { let t; const em = new EventEmitter(); em.on("q", function () { t = this === em; }); em.emit("q"); return t; })());
e.removeAllListeners("y");
out("y count", e.listenerCount("y"));
const chain = new EventEmitter();
out("chain", chain.on("a", () => {}) === chain, chain.once("b", () => {}) === chain, chain.addListener("c", () => {}) === chain, chain.removeAllListeners() === chain, chain.eventNames().length);
const raw = new EventEmitter(); const onceFn = () => {}; raw.once("r", onceFn);
out("rawListeners once", raw.rawListeners("r")[0] === onceFn, raw.listeners("r")[0] === onceFn, typeof raw.rawListeners("r")[0].listener);
class My extends EventEmitter { constructor() { super({ captureRejections: false }); } }
const m = new My();
m.once("go", (v) => out("my go", v));
out("my", m instanceof EventEmitter, EE2 === EventEmitter, typeof captureRejectionSymbol);
setTimeout(() => m.emit("go", 7), 1);
(async () => {
  const [v] = await once(m, "go");
  out("once resolved", v);
  const em = new EventEmitter();
  setTimeout(() => { em.emit("d", 1); em.emit("d", 2); em.emit("end"); }, 1);
  const got = [];
  const ac = new AbortController();
  em.once("end", () => ac.abort());
  try { for await (const [x] of on(em, "d", { signal: ac.signal })) got.push(x); } catch (err) { out("on aborted", err.name); }
  out("on", got.join(","));
  const em2 = new EventEmitter();
  setTimeout(() => em2.emit("error", new Error("once err")), 1);
  try { await once(em2, "x"); } catch (err) { out("once rejected", err.message); }
  out("getEventListeners", getEventListeners(m, "go").length, typeof setMaxListeners, typeof listenerCount);
  out("done");
})();
"""


def test_events_module(run):
    """CATCHES: EventEmitter listener ordering (prepend/once/prependOnce), newListener/removeListener
    events, return values of emit, unhandled 'error' throwing, errorMonitor (the reference never calls
    it), MaxListenersExceededWarning text on stderr, events.once/on with AbortSignal."""
    r = run(["-e", PROG_EVENTS])
    assert r.returncode == 0
    assert r.stderr == (b"MaxListenersExceededWarning: Possible EventEmitter memory leak detected. "
                        b"2 y listeners added. Use emitter.setMaxListeners() to increase limit\n")
    assert r.stdout == golden(__file__, "events")


PROG_BUFFER = r"""
const { Buffer, constants, kMaxLength, isUtf8, isAscii, transcode, btoa: b2, atob: a2, SlowBuffer, Blob: B2 } = require("buffer");
const out = (...a) => console.log(...a);
const b = Buffer.from("héllo wörld €", "utf8");
out("len", b.length, Buffer.byteLength("héllo wörld €"), Buffer.byteLength("aGk=", "base64"), Buffer.byteLength("abcd", "hex"), Buffer.byteLength(new Uint16Array(3)), Buffer.byteLength(new ArrayBuffer(7)));
for (const enc of ["hex", "base64", "base64url", "latin1", "binary", "ascii", "utf16le", "ucs2", "utf-8", "UTF8"]) out(enc, b.toString(enc));
try { b.toString("bogus"); } catch (e) { out("bad enc", e.name, e.message); }
out("from hex", Buffer.from("48656c6c6fzz", "hex").toString(), Buffer.from("SGVsbG8", "base64").toString(), Buffer.from("SGVsbG8_-w", "base64url").toString("hex"), Buffer.from("ÿ", "latin1")[0], Buffer.from("hi", "utf16le").toString("hex"), Buffer.from("aé", "ascii").toString("hex"));
out("alloc", Buffer.alloc(4).toString("hex"), Buffer.alloc(5, "ab").toString(), Buffer.alloc(3, 0x41).toString(), Buffer.allocUnsafe(3).length, Buffer.allocUnsafeSlow(2).length, Buffer.alloc(4, "aGk=", "base64").toString(), Buffer.alloc(2, 0x1ff).toString("hex"));
out("from arr", Buffer.from([1, 2, 256, -1, 3.7]).toString("hex"), Buffer.from(new Uint16Array([1, 0x102]).buffer).toString("hex"), Buffer.from(Buffer.from("copy")).toString(), Buffer.from({ length: 2, 0: 65, 1: 66 }).toString());
const ab = new ArrayBuffer(8); const view = Buffer.from(ab, 2, 3); view[0] = 9; out("abview", new Uint8Array(ab)[2], view.length, Buffer.from(ab, 6).length);
out("concat", Buffer.concat([Buffer.from("ab"), Buffer.from("cd"), new Uint8Array([101])]).toString(), Buffer.concat([Buffer.from("abc")], 2).toString(), Buffer.concat([]).length, Buffer.concat([Buffer.from("x")], 3).toString("hex"));
out("compare", Buffer.compare(Buffer.from("a"), Buffer.from("b")), Buffer.from("b").compare(Buffer.from("a")), Buffer.compare(Buffer.from("ab"), Buffer.from("a")), Buffer.from("abc").equals(Buffer.from("abc")), Buffer.from("abc").equals(new Uint8Array([97, 98, 99])), Buffer.from("abc").compare(Buffer.from("xbcx"), 1, 3, 1, 3));
try { Buffer.compare("a", Buffer.from("a")); } catch (e) { out("compare err", e.name, e.message); }
const s = Buffer.from("0123456789");
out("slice", s.slice(2, 5).toString(), s.subarray(-3).toString(), s.slice(-2, -1).toString(), s.toString("utf8", 1, 4), s.toString("hex", 8));
const sl = s.subarray(0, 2); sl[0] = 0x41; out("subarray shares", s.toString());
const cp = s.slice(0, 2); cp[0] = 0x42; out("slice copies", s.toString(), cp.toString(), Buffer.isBuffer(cp), Buffer.isBuffer(s.subarray(1)));
out("typedarray index semantics", s.indexOf("45"), s.indexOf(0x39), s.lastIndexOf(0x31), s.includes(0x35), s.includes("5"));
const w = Buffer.alloc(10);
out("write", w.write("hey"), w.write("XY", 5), w.write("abcdef", 8), w.toString("hex"), w.write("ff00", 0, "hex"), w.write("zz", "latin1"), w.toString("hex"));
out("fill", Buffer.alloc(3).fill(0x101).toString("hex"), Buffer.alloc(3).fill(7, 1).toString("hex"));
const n = Buffer.alloc(12);
out("w8", n.writeUInt8(0x1ff, 0), n.writeUInt32LE(0xdeadbeef, 1), n.writeUInt32LE(-1, 5));
n[9] = 0x12; n[10] = 0x34;
out("nums", n.toString("hex"), n.readUInt8(0), n.readUInt8(), n.readUInt16LE(9), n.readUInt16BE(9), n.readUInt32LE(1).toString(16), n.readUInt32BE(1).toString(16), n.readUInt32LE(5), n.readUInt8(20), n.readUInt16BE(11));
out("missing methods", typeof n.writeInt8, typeof n.readInt16LE, typeof n.readBigInt64LE, typeof n.swap16, typeof n.writeDoubleLE, typeof n.copy);
out("json", JSON.stringify(Buffer.from("hi")), JSON.stringify({ b: Buffer.from([1]) }));
out("isBuf", Buffer.isBuffer(Buffer.alloc(1)), Buffer.isBuffer(new Uint8Array(1)), Buffer.isEncoding("utf8"), Buffer.isEncoding("UTF-8"), Buffer.isEncoding("nope"), Buffer.isEncoding(1), Buffer.alloc(1) instanceof Uint8Array);
out("iter", [...Buffer.from("ab")].join(), [...Buffer.from("ab").entries()].join("|"), [...Buffer.from("ab").keys()].join(), Buffer.from("abc").map(x => x + 1).constructor.name);
out("misc", isUtf8(Buffer.from([0xc3, 0x28])), isUtf8(Buffer.from("ok")), isAscii(Buffer.from("é")), isAscii(new Uint8Array([65])), b2("hi"), a2("aGk="), typeof constants.MAX_LENGTH, kMaxLength === constants.MAX_LENGTH, Buffer.poolSize, SlowBuffer(3).length, B2 === Blob);
out("transcode", transcode(Buffer.from("hé"), "utf8", "latin1").toString("hex"), transcode(Buffer.from("hi"), "utf8", "utf16le").toString("hex"));
out("tostr", Buffer.from("abc").toLocaleString(), JSON.stringify(Buffer.from([0xff, 0xfe, 0x41]).toString()), Buffer.from("€").toString("ascii"), String(Buffer.from("str")));
out("inspect", require("util").inspect(Buffer.from("a".repeat(60))));
out("readme", Buffer.from("test").readUInt16LE(), Buffer.from([1, 2, 3]).reverse().toString("hex"));
try { Buffer.from({}); } catch (e) { out("fromObj", e.name, e.message); }
try { Buffer.alloc(-1); } catch (e) { out("allocNeg", e.name, e.message); }
try { Buffer.from("x", "klingon"); } catch (e) { out("badenc", e.name, e.message); }
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_buffer_module(run, tier):
    """CATCHES: Buffer encodings (utf8/hex/base64/base64url/latin1/ascii/utf16le), alloc fill rules,
    concat/compare/equals, slice-copies vs subarray-shares, write() overloads, the small integer
    read/write method set, toJSON, isUtf8/isAscii/transcode, and the absent Node methods, in every tier."""
    r = run([*tier, "-e", PROG_BUFFER])
    _ok(r)
    assert r.stdout == golden(__file__, "buffer")


PROG_TEXT_MODULES = r"""
const out = (...a) => console.log(...a);
const { StringDecoder } = require("string_decoder");
const d = new StringDecoder("utf8");
const euro = Buffer.from("€");
out("sd", JSON.stringify(d.write(euro.subarray(0, 1))), JSON.stringify(d.write(euro.subarray(1, 2))), JSON.stringify(d.write(euro.subarray(2))), JSON.stringify(d.end(Buffer.from([0xe2]))), d.encoding);
out("sd whole", JSON.stringify(new StringDecoder().write(Buffer.from("héllo"))), JSON.stringify(new StringDecoder("utf-8").end()));
const dh = new StringDecoder("hex"); out("sdhex", dh.write(Buffer.from([1, 255])), JSON.stringify(dh.end()));
const db = new StringDecoder("base64"); out("sdb64", db.write(Buffer.from("ab")), db.end(Buffer.from("c")));
const d16 = new StringDecoder("utf16le"); out("sd16", JSON.stringify(d16.write(Buffer.from([0x61, 0x00, 0x62]))), JSON.stringify(d16.end()));
const dl = new StringDecoder("latin1"); out("sdlatin1", dl.write(Buffer.from([0xe9, 0x41])), dl.encoding);
const qs = require("querystring");
out("qs", JSON.stringify(qs.parse("a=1&b=2&a=3&c=%20x+y&d&e=")), qs.stringify({ x: [1, 2], y: "a b&c", z: true, n: null, u: undefined, o: { k: 1 } }), qs.escape("a b/ü"), qs.unescape("%41%zz+"));
out("qs2", JSON.stringify(qs.parse("a:1;b:2", ";", ":")), qs.stringify({ a: 1, b: 2 }, ";", ":"), JSON.stringify(qs.parse("a=1&a=2&a=3", null, null, { maxKeys: 2 })), qs.unescapeBuffer("%41+B", true).toString(), qs.unescapeBuffer("%41+B").toString());
out("qs3", JSON.stringify(qs.parse("")), JSON.stringify(qs.parse("=v&k=")), qs.stringify("notobj"), qs.encode === qs.stringify, qs.decode === qs.parse, JSON.stringify(qs.parse("x=%E2%82%AC&y=%ZZ")));
const url = require("url");
const u = url.parse("https://user:pw@Example.com:8080/p/a/t/h?query=string&q2=x#hash", true);
out("url.parse", u.protocol, u.auth, u.host, u.hostname, u.port, u.pathname, u.search, JSON.stringify(u.query), u.hash, u.href, u.path, u.slashes);
const u2 = url.parse("/rel/path?x=1");
out("url.parse rel", u2.protocol, u2.host, u2.pathname, u2.query, u2.href, u2.search);
const u3 = url.parse("mailto:someone@example.com");
out("url.parse mailto", u3.protocol, u3.host, u3.pathname, u3.href);
out("url.format", url.format({ protocol: "http", hostname: "h.com", port: 81, pathname: "/x", query: { a: 1, b: "c d" } }), url.format({ protocol: "https:", host: "x.org", pathname: "p", search: "?s=1", hash: "#h" }), url.format(new URL("http://a.com/b?c#d")), url.format(u), url.format("http://str.com/x"));
out("url.resolve", url.resolve("http://a.com/b/c", "../d"), url.resolve("http://a.com/b/c", "/e"), url.resolve("/one/two", "three"), url.resolve("http://a.com", "http://b.com/x"), url.resolve("http://a.com/b/", "c?q=1#f"));
out("fileURL", url.fileURLToPath("file:///tmp/a%20b.txt"), url.fileURLToPath(new URL("file:///x/y")), url.pathToFileURL("/x y/#z").href, url.domainToASCII("münchen.de"), url.domainToUnicode("xn--mnchen-3ya.de"));
try { url.fileURLToPath("http://x.com/a"); } catch (e) { out("fileURL err", e.name, e.code, e.message); }
out("urlToHttp", JSON.stringify(url.urlToHttpOptions(new URL("https://u:p@h.com:9/p?q=1"))));
out("URL global", url.URL === URL, url.URLSearchParams === URLSearchParams, typeof url.Url);
const punycode = require("punycode");
out("punycode", punycode.encode("mañana"), punycode.decode("maana-pta"), punycode.toASCII("mañana.com"), punycode.toUnicode("xn--maana-pta.com"), punycode.toASCII("ascii.org"), JSON.stringify(punycode.ucs2.decode("a😀")), punycode.ucs2.encode([0x1f600, 98]));
"""


def test_string_decoder_querystring_url_punycode(run):
    """CATCHES: StringDecoder behaviour per encoding (the reference emits U+FFFD for split UTF-8
    sequences), querystring parse/stringify/escape/unescapeBuffer with custom separators and maxKeys,
    legacy url.parse/format/resolve/fileURLToPath (no %-decoding), urlToHttpOptions and punycode."""
    r = run(["-e", PROG_TEXT_MODULES])
    _ok(r)
    assert r.stdout == golden(__file__, "text_modules")


PROG_ASSERT = r"""
const assert = require("assert");
const out = (...a) => console.log(...a);
const tryA = (label, f) => { try { f(); out(label, "pass"); } catch (e) { out(label, e.name, e.code, JSON.stringify(e.message), e.operator, JSON.stringify(e.actual), JSON.stringify(e.expected), e instanceof assert.AssertionError); } };
tryA("ok", () => assert.ok(1));
tryA("okFail", () => assert(0));
tryA("okMsg", () => assert.ok(false, "custom msg"));
tryA("okErrObj", () => assert.ok(false, new TypeError("thrown as is")));
tryA("equal", () => assert.equal(1, "1"));
tryA("equalFail", () => assert.equal(1, 2));
tryA("strictEqual", () => assert.strictEqual(1, 2));
tryA("strictEqualMsg", () => assert.strictEqual("a", "b", "values differ"));
tryA("notStrictEqual", () => assert.notStrictEqual(1, 1));
tryA("deepEqual", () => assert.deepEqual({ a: [1] }, { a: ["1"] }));
tryA("notDeepEqual", () => assert.notDeepEqual({ a: 1 }, { a: 1 }));
tryA("deepStrictEqual", () => assert.deepStrictEqual({ a: [1] }, { a: ["1"] }));
tryA("deepStrictEqualOk", () => assert.deepStrictEqual(new Map([[1, { a: 1 }]]), new Map([[1, { a: 1 }]])));
tryA("notDeepStrictEqual", () => assert.notDeepStrictEqual([1], [1]));
tryA("throws", () => assert.throws(() => { throw new TypeError("tt"); }, TypeError));
tryA("throwsWrongClass", () => assert.throws(() => { throw new TypeError("tt"); }, RangeError));
tryA("throwsRe", () => assert.throws(() => { throw new Error("abc"); }, /b/));
tryA("throwsReMiss", () => assert.throws(() => { throw new Error("abc"); }, /zzz/));
tryA("throwsObj", () => assert.throws(() => { throw new Error("abc"); }, { message: "abc" }));
tryA("throwsFn", () => assert.throws(() => { throw new Error("v"); }, (e) => e.message === "v"));
tryA("throwsNone", () => assert.throws(() => {}));
tryA("doesNotThrow", () => assert.doesNotThrow(() => { throw new Error("dnt"); }));
tryA("doesNotThrowOk", () => assert.doesNotThrow(() => 1));
tryA("match", () => assert.match("abc", /x/));
tryA("matchOk", () => assert.match("abc", /b/));
tryA("doesNotMatch", () => assert.doesNotMatch("abc", /b/));
tryA("fail", () => assert.fail("boom"));
tryA("failNoArg", () => assert.fail());
tryA("ifError", () => assert.ifError(new Error("iferr")));
tryA("ifErrorNull", () => assert.ifError(null));
tryA("ifErrorUndef", () => assert.ifError(undefined));
tryA("strict", () => assert.strict.equal(1, "1"));
tryA("strictMod", () => require("assert/strict").deepEqual([1], ["1"]));
tryA("notEqual", () => assert.notEqual(1, 2));
tryA("notEqualFail", () => assert.notEqual(1, "1"));
tryA("AssertionError", () => { const e = new assert.AssertionError({ actual: 1, expected: 2, operator: "strictEqual" }); out("AE", e.name, e.actual, e.expected, e.code, e.operator, JSON.stringify(e.message)); });
tryA("AssertionErrorMsg", () => { const e = new assert.AssertionError({ message: "mine" }); out("AE2", e.message, e.generatedMessage); });
(async () => {
  try { await assert.rejects(Promise.resolve(1)); } catch (e) { out("rejects", e.code, JSON.stringify(e.message)); }
  await assert.rejects(Promise.reject(new Error("r")), /r/); out("rejects ok");
  await assert.rejects(async () => { throw new TypeError("fn"); }, TypeError); out("rejects fn ok");
  try { await assert.doesNotReject(Promise.reject(new Error("dnr"))); } catch (e) { out("doesNotReject", e.code, JSON.stringify(e.message)); }
  await assert.doesNotReject(Promise.resolve(2)); out("doesNotReject ok");
})();
"""


def test_assert_module(run):
    """CATCHES: node:assert pass/fail decisions (loose vs strict vs deep equality, throws matchers by
    class/RegExp/object/predicate, match, ifError, rejects/doesNotReject) and the AssertionError shape
    (code ERR_ASSERTION, operator, actual/expected, generic 'Assertion failed' message)."""
    r = run(["-e", PROG_ASSERT])
    _ok(r)
    assert r.stdout == golden(__file__, "assert")


PROG_OS_MODULE_VM_TIMERS = r"""
const out = (...a) => console.log(...a);
const os = require("os");
out("os", os.platform(), os.type(), JSON.stringify(os.EOL), os.endianness(), os.devNull, typeof os.hostname(), typeof os.release(), typeof os.version(), typeof os.uptime(), typeof os.totalmem(), typeof os.freemem(), Array.isArray(os.cpus()), os.cpus().length === os.availableParallelism(), typeof os.arch(), typeof os.machine(), os.homedir() === process.env.HOME, typeof os.tmpdir(), os.loadavg().length, typeof os.userInfo().username);
out("cpu shape", JSON.stringify(os.cpus()[0]));
out("ifaces", JSON.stringify(os.networkInterfaces()));
out("os consts", os.constants.signals === undefined ? "nosignals" : typeof os.constants.signals, JSON.stringify(os.constants.priority), os.constants.errno === undefined ? "noerrno" : typeof os.constants.errno);
out("prio", typeof os.getPriority(), os.getPriority(0) === os.getPriority());
try { os.getPriority("x"); } catch (e) { out("prio err", e.name, e.code, e.message); }
try { os.setPriority("y", 0); } catch (e) { out("setprio err", e.name, e.code, e.message); }
const { createRequire, builtinModules, isBuiltin, Module } = require("module");
require("fs").writeFileSync("dep.js", "module.exports = { v: 42, file: require('path').basename(__filename), main: require.main === module };");
require("fs").writeFileSync("data.json", '{"k": [1, 2]}');
const req = createRequire(__filename);
out("createRequire", req("./dep.js").v, req("./dep").file, req("./dep").main, JSON.stringify(req("./data.json")), typeof req.resolve, require("path").basename(req.resolve("./dep")), req.resolve("fs"), req.resolve("node:path"));
out("builtins", builtinModules.includes("fs"), builtinModules.includes("node:fs"), isBuiltin("node:path"), isBuiltin("fs/promises"), isBuiltin("nope"), builtinModules.length > 30, typeof Module, require("module") === Module);
out("cache", Object.keys(require.cache).some(k => k.endsWith("/dep.js")), require("./dep") === req("./dep"));
try { req("./missing-dep"); } catch (e) { out("missing", e.code, e.message.split("\n")[0].replace(process.cwd(), "<cwd>")); }
const vm = require("vm");
out("vm", vm.runInNewContext("a + b", { a: 1, b: 2 }), vm.runInThisContext("typeof require"), new vm.Script("x * 2").runInNewContext({ x: 21 }));
const ctx = vm.createContext({ n: 1 });
vm.runInContext("n += 10; var created = 'yes'", ctx);
out("vmctx", ctx.n, ctx.created, vm.isContext(ctx), vm.isContext({}));
try { vm.runInNewContext("throw new RangeError('vm err')"); } catch (e) { out("vmerr", e.name, e.message); }
try { new vm.Script("let let = 1"); } catch (e) { out("vmsyntax", e.name); }
const fn = vm.compileFunction("return a + b", ["a", "b"]); out("compileFunction", fn(2, 3));
const tp = require("timers/promises");
const order = [];
setTimeout(() => order.push("timeout"), 0);
setImmediate(() => order.push("immediate"));
process.nextTick(() => order.push("tick"));
Promise.resolve().then(() => order.push("micro"));
queueMicrotask(() => order.push("qm"));
(async () => {
  out("tp", await tp.setTimeout(5, "val"), await tp.setImmediate("imm"));
  out("top-level order", order.join(","));
  let i = 0;
  for await (const v of tp.setInterval(2, "iv")) { if (++i >= 3) { out("interval value", v); break; } }
  out("interval", i);
  const ac = new AbortController();
  const pr = tp.setTimeout(1000, null, { signal: ac.signal });
  ac.abort();
  try { await pr; } catch (e) { out("abort", e.name, e.code); }
  const timers = require("timers");
  out("timers", timers.setTimeout === setTimeout, typeof timers.setImmediate, timers.promises === tp, typeof tp.scheduler);
  const t = setTimeout(() => {}, 10); out("timer handle", typeof t); clearTimeout(t);
  const order2 = [];
  setTimeout(() => order2.push("timeout"), 0);
  setImmediate(() => order2.push("immediate"));
  process.nextTick(() => order2.push("tick"));
  Promise.resolve().then(() => order2.push("micro"));
  await tp.setTimeout(10);
  out("order inside microtask", order2.join(","));
})();
"""


def test_os_module_vm_timers(run, workdir):
    """CATCHES: node:os facts that must be fixed (platform/type/EOL/endianness/devNull, synthetic cpus
    and loopback-only networkInterfaces, getPriority validation), module.createRequire/builtinModules/
    isBuiltin, node:vm contexts, timers/promises and nextTick/microtask/immediate/timeout ordering."""
    write_files(workdir, {"main.js": PROG_OS_MODULE_VM_TIMERS})
    r = run(["main.js"])
    _ok(r)
    assert r.stdout == golden(__file__, "os_module_vm_timers")


PROG_STREAM = r"""
const out = (...a) => console.log(...a);
const { Readable, Writable, Transform, PassThrough, Duplex, pipeline, finished, Stream } = require("stream");
const sp = require("stream/promises");
(async () => {
  const r = Readable.from(["a", "b", "c"]);
  const got = [];
  for await (const c of r) got.push(c);
  out("from", got.join(""));
  const upper = new Transform({ transform(chunk, enc, cb) { cb(null, chunk.toString().toUpperCase()); } });
  const sink = []; const w = new Writable({ write(chunk, enc, cb) { sink.push(chunk.toString()); cb(); } });
  await sp.pipeline(Readable.from(["x", "y", "z"]), upper, w);
  out("pipeline", sink.join("|"));
  const rr = new Readable({ read() {} });
  rr.push("one"); rr.push("two"); rr.push(null);
  let data = ""; rr.setEncoding("utf8");
  rr.on("data", (c) => (data += c + ";"));
  await new Promise((res) => rr.on("end", res));
  out("readable", data);
  const om = new Readable({ objectMode: true, read() {} });
  om.push({ a: 1 }); om.push([2]); om.push(null);
  const objs = []; for await (const o of om) objs.push(JSON.stringify(o));
  out("objectMode", objs.join(" "));
  const pt = new PassThrough(); const ptOut = [];
  pt.on("data", (c) => ptOut.push(c.toString()));
  pt.write("p1"); pt.end("p2");
  await new Promise((res) => pt.on("finish", res));
  out("passthrough", ptOut.join(","));
  const events = [];
  const ww = new Writable({ highWaterMark: 2, write(c, e, cb) { events.push("w:" + c); setTimeout(cb, 1); }, final(cb) { events.push("final"); cb(); } });
  out("write ret", ww.write("aaa"), ww.writableLength, ww.writableHighWaterMark);
  ww.on("drain", () => events.push("drain"));
  ww.end("bb");
  await new Promise((res) => ww.on("finish", res));
  out("writable", events.join(","));
  await new Promise((res) => pipeline(Readable.from(["q"]), new Transform({ transform(c, e, cb) { cb(new Error("tfail")); } }), new Writable({ write(c, e, cb) { cb(); } }), (err) => { out("pipeline err", err && err.message); res(); }));
  const dup = new Duplex({ read() {}, write(c, e, cb) { out("duplex wrote", c.toString()); cb(); } });
  dup.write("dw"); dup.end();
  await new Promise((res) => finished(new Writable({ write(c, e, cb) { cb(); } }).end("fin"), (err) => { out("finished", err); res(); }));
  const rs = new Readable({ read() {} });
  rs.push("paused"); rs.push(null);
  out("read()", String(rs.read()));
  const flush = new Transform({ transform(c, e, cb) { cb(null, c); }, flush(cb) { this.push("<flushed>"); cb(); } });
  const fo = []; flush.on("data", (c) => fo.push(String(c)));
  flush.end("body");
  await new Promise((res) => flush.on("end", res));
  out("flush", fo.join(""));
  out("same", require("node:stream").Readable === Readable, typeof Stream, typeof require("stream/web").ReadableStream, typeof Readable.toWeb, typeof Readable.prototype.map);
  const sd = new Readable({ read() {} }); sd.on("close", () => out("closed", sd.destroyed)); sd.destroy();
})();
"""


def test_stream_module(run):
    """CATCHES: node:stream Readable.from/async iteration, Transform/PassThrough/Writable backpressure
    (write() return value, drain/final ordering), pipeline success and error propagation, finished(),
    paused read(), transform flush, destroy/close, and the reference's missing toWeb/iterator helpers."""
    r = run(["-e", PROG_STREAM])
    _ok(r)
    assert r.stdout == golden(__file__, "stream")


PROG_ZLIB = r"""
const out = (...a) => console.log(...a);
const zlib = require("zlib");
const text = "The quick brown fox jumps over the lazy dog. ".repeat(8);
for (const [c, d] of [["deflateSync", "inflateSync"], ["deflateRawSync", "inflateRawSync"], ["gzipSync", "gunzipSync"], ["brotliCompressSync", "brotliDecompressSync"], ["zstdCompressSync", "zstdDecompressSync"]]) {
  const comp = zlib[c](text);
  const round = zlib[d](comp);
  out(c, Buffer.isBuffer(comp), Buffer.isBuffer(round), round.toString() === text, zlib[d](zlib[c](Buffer.alloc(0))).length, zlib[d](zlib[c](new Uint8Array([0, 1, 2]))).toString("hex"));
}
out("deflate bytes", zlib.deflateSync("hello").toString("hex"), zlib.deflateRawSync("hello").toString("hex"));
out("gzip hdr", zlib.gzipSync("hello").subarray(0, 4).toString("hex"), zlib.gunzipSync(Buffer.from("1f8b08000000000000ffcb48cdc9c90700863ba63605000000", "hex")).toString());
out("inflate known", zlib.inflateSync(Buffer.from("789ccb48cdc9c90700062c0215", "hex")).toString(), zlib.inflateRawSync(Buffer.from("cb48cdc9c90700", "hex")).toString(), zlib.unzipSync(zlib.gzipSync("unz")).toString());
out("crc32", zlib.crc32("hello"), zlib.crc32("world", zlib.crc32("hello ")), zlib.crc32("hello world"), zlib.crc32(Buffer.from([1, 2, 3])), zlib.crc32(""));
const big = Buffer.alloc(40000); for (let i = 0; i < big.length; i++) big[i] = (i * 7919) % 251;
const mid = big.subarray(0, 1000);
out("big", zlib.inflateSync(zlib.deflateSync(big)).equals(big), zlib.gunzipSync(zlib.gzipSync(big)).equals(big), zlib.inflateRawSync(zlib.deflateRawSync(big)).equals(big), zlib.brotliDecompressSync(zlib.brotliCompressSync(mid)).equals(mid), zlib.zstdDecompressSync(zlib.zstdCompressSync(mid)).equals(mid));
for (const [label, f] of [["inflate", () => zlib.inflateSync(Buffer.from("not compressed"))], ["gunzip", () => zlib.gunzipSync(Buffer.from("xx"))], ["inflateRaw", () => zlib.inflateRawSync(Buffer.from([0xff, 0xff, 0xff]))], ["brotli", () => zlib.brotliDecompressSync(Buffer.from([0xff, 0xff, 0xff, 0xff]))], ["zstd", () => zlib.zstdDecompressSync(Buffer.from("nope"))], ["truncated", () => zlib.inflateSync(zlib.deflateSync(text).subarray(0, 10))]]) {
  try { f(); out("bad", label, "no error"); } catch (e) { out("bad", label, e.name, e.code, e.message); }
}
out("constants", zlib.constants.Z_BEST_COMPRESSION, zlib.constants.Z_SYNC_FLUSH, zlib.constants.Z_NO_FLUSH, typeof zlib.constants.BROTLI_PARAM_QUALITY, zlib.Z_DEFAULT_COMPRESSION);
zlib.deflate("async data", (err, buf) => {
  out("async deflate", err, Buffer.isBuffer(buf));
  zlib.inflate(buf, (err2, res) => {
    out("async inflate", err2, res.toString());
    zlib.gzip("g", (e, b) => zlib.gunzip(b, (e2, r) => {
      out("async gzip", e, e2, r.toString());
      zlib.inflate(Buffer.from("garbage"), (e3, r3) => {
        out("async error", e3 && e3.message, r3);
        require("util").promisify(zlib.brotliCompress)("brot").then((b2) => {
          out("promisified", zlib.brotliDecompressSync(b2).toString());
          const gz = zlib.createGzip();
          const chunks = [];
          gz.on("data", (c) => chunks.push(c));
          gz.on("end", () => {
            out("stream gzip", zlib.gunzipSync(Buffer.concat(chunks)).toString());
            const { pipeline, Readable, Writable } = require("stream");
            const outChunks = [];
            pipeline(Readable.from([Buffer.from("piped "), Buffer.from("through deflate")]), zlib.createDeflate(), zlib.createInflate(), new Writable({ write(c, e, cb) { outChunks.push(c); cb(); } }), (perr) => out("stream pipeline", perr, Buffer.concat(outChunks).toString()));
          });
          gz.write("stream ");
          gz.end("data");
        });
      });
    }));
  });
});
"""


def test_zlib_module(run):
    """CATCHES: zlib codecs that fail to round-trip (deflate/raw/gzip/brotli/zstd, empty and large
    /large inputs), produce non-canonical bytes for tiny inputs, mis-decode known zlib/gzip vectors, compute
    the wrong crc32 (with seed), report different error messages for corrupt input, or break the
    callback/promisified/stream (createGzip/createDeflate pipeline) APIs."""
    r = run(["-e", PROG_ZLIB], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "zlib")


PROG_READLINE = r"""
const out = (...a) => console.log(...a);
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin, terminal: false });
const lines = [];
rl.on("line", (l) => lines.push(l));
rl.on("close", async () => {
  out("lines", JSON.stringify(lines));
  const { Readable } = require("stream");
  const rl2 = readline.createInterface({ input: Readable.from(["x1\ny", "2\r\nz3"]), crlfDelay: Infinity });
  const got = [];
  for await (const l of rl2) got.push(l);
  out("async iter", JSON.stringify(got));
  const rlp = require("readline/promises");
  out("promises", typeof rlp.createInterface, rlp.Interface === readline.Interface, readline.promises === rlp, typeof rlp.Readline);
  out("helpers", readline.clearLine(process.stdout, 0), readline.cursorTo(process.stdout, 0), readline.moveCursor(process.stdout, 1, 1), readline.clearScreenDown(process.stdout));
  const { EventEmitter } = require("events");
  const fake = new EventEmitter();
  readline.emitKeypressEvents(fake);
  readline.emitKeypressEvents(fake);
  const keys = [];
  fake.on("keypress", (ch, key) => keys.push(`${JSON.stringify(ch)}:${key.name}`));
  fake.emit("data", "aB\t\n\x7f");
  out("keypress", keys.join(" "));
  const pending = new readline.Interface({ input: new EventEmitter() });
  pending.close(); pending.close();
  out("iface", pending.pause() === pending, pending.resume() === pending);
});
"""


def test_readline_from_stdin(run):
    """CATCHES: readline line splitting of piped stdin (\n and \r\n, empty lines; the reference drops a
    final unterminated line), async iteration over a stream source, the readline/promises exports and
    emitKeypressEvents key naming."""
    r = run(["-e", PROG_READLINE], input=b"first\nsecond line\r\n\nlast-no-newline")
    _ok(r)
    assert r.stdout == golden(__file__, "readline")


PROG_QUESTION = r"""
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
rl.question("Name? ", (name) => {
  rl.question("Age? ", (age) => {
    console.log(`Hello ${name}, ${age}`);
    rl.close();
  });
});
rl.on("close", () => console.log("closed"));
"""


def test_readline_question(run):
    """CATCHES: readline.question() that does not write the prompt to the output stream (without a
    newline) or does not answer successive questions with successive stdin lines."""
    r = run(["-e", PROG_QUESTION], input=b"Ann\n33\nextra\n")
    _ok(r)
    assert r.stdout == b"Name? Age? Hello Ann, 33\nclosed\n"


PROG_SMALL_BUILTINS = r"""
const out = (...a) => console.log(...a);
const v8 = require("v8");
const ser = v8.serialize({ a: [1, 2n, "s", true, null, undefined], m: new Map([[1, 2]]), s: new Set(["x"]), d: new Date(0), r: /re/g, u8: new Uint8Array([1, 2]), f32: new Float32Array([1.5]), ab: new ArrayBuffer(2), buf: Buffer.from("b") });
const de = v8.deserialize(ser);
out("v8", Buffer.isBuffer(ser), JSON.stringify(de.a.map(String)), de.m.get(1), de.s.has("x"), de.d.toISOString(), String(de.r), Array.from(de.u8).join(), de.f32[0], de.ab.byteLength, Buffer.isBuffer(de.buf), String(de.buf), typeof v8.getHeapStatistics().total_heap_size);
const cyc = { n: 1 }; cyc.me = cyc;
const dc2 = v8.deserialize(v8.serialize(cyc)); out("v8 cycle", dc2.me === dc2);
const sz = new v8.Serializer(); sz.writeHeader(); sz.writeValue({ k: "v" }); const dz = new v8.Deserializer(sz.releaseBuffer()); dz.readHeader(); out("v8 classes", JSON.stringify(dz.readValue()));
const dc = require("diagnostics_channel"); const ch = dc.channel("my-ch");
const sub = (m, n) => out("dc", JSON.stringify(m), n);
out("dc before", ch.hasSubscribers, dc.hasSubscribers("my-ch"));
ch.subscribe(sub); ch.publish({ v: 1 }); out("dc has", ch.hasSubscribers, dc.channel("my-ch") === ch);
ch.unsubscribe(sub); ch.publish({ v: 2 }); out("dc after", ch.hasSubscribers);
dc.subscribe("named", (m) => out("dc named", m)); dc.channel("named").publish("hi");
const constants = require("constants"); out("constants", constants.O_RDONLY, constants.ENOENT, constants.SIGINT, constants.S_IFREG);
const { performance: perf, PerformanceObserver } = require("perf_hooks"); out("perf", typeof perf.now(), perf === performance, typeof PerformanceObserver);
const tty = require("tty"); out("tty", tty.isatty(1), tty.isatty(0), tty.isatty(99), typeof tty.WriteStream, typeof tty.ReadStream);
const domain = require("domain"); const d = domain.create(); out("domain", typeof d.run);
d.on("error", (e) => out("domain caught", e.message)); d.run(() => out("domain run"));
const sc = structuredClone(new Map([[1, { x: [1] }]])); out("structuredClone", sc.get(1).x[0]);
const sys = require("sys"); out("sys", sys === require("util"));
"""


def test_small_builtins(run):
    """CATCHES: node:v8 serialize/deserialize round trips (Map/Set/Date/RegExp/typed arrays/Buffer/
    cycles, Serializer classes), diagnostics_channel subscribe/publish/unsubscribe, constants, perf_hooks,
    tty.isatty on pipes, domain and the sys alias."""
    r = run(["-e", PROG_SMALL_BUILTINS])
    _ok(r)
    assert r.stdout == golden(__file__, "small_builtins")


PROG_CONSOLE_CLASS = r"""
const { Console } = require("console");
const c = new Console({ stdout: process.stdout, stderr: process.stderr });
c.log("%s is %d years and %o; %j %%", "Bob", 42, { x: 1 }, [2]);
c.log({ a: 1, nested: { deep: { deeper: { x: 1 } } } }, [1, 2], null, undefined, Symbol("s"), 5n, "str");
c.group("G1"); c.log("inside"); c.group(); c.info("deeper\nmultiline"); c.groupEnd(); c.groupEnd(); c.log("out"); c.groupEnd();
c.count(); c.count("k"); c.count(); c.countReset(); c.count(); c.countReset("nope");
c.dir({ a: { b: { c: { d: 1 } } } }, { depth: 0 });
c.dirxml({ x: [1] });
c.assert(1 === 1, "no"); c.assert(false, "assert %s", "msg"); c.assert(false);
c.table([{ a: 1, b: "x" }, { a: 2, c: true }]);
c.table([[1, 2], [3]]);
c.table({ r1: { c: 1 }, r2: { c: 2 } }, ["c"]);
c.table("not tabular");
c.table(new Map([["k", 1]]));
c.table([1, "two"]);
c.groupCollapsed("collapsed"); c.warn("warn in group"); c.groupEnd();
c.error("err line"); c.debug("debug line");
const c2 = new Console(process.stdout);
c2.log("positional ctor"); c2.error("positional ctor stderr goes to stdout");
try { new Console({}); } catch (e) { console.log("bad ctor", e.name, e.message); }
const g = require("console"); console.log("same global", g === console, typeof g.Console);
console.table([{ global: "table" }]);
"""


def test_console_class(run):
    """CATCHES: node:console Console instances that skip util.format specifiers or inspect formatting,
    mis-indent groups, miscount count/countReset, render console.table boxes differently (objects,
    arrays, Maps, column filters, primitives), or route assert/warn/error to the wrong stream."""
    r = run(["-e", PROG_CONSOLE_CLASS])
    assert r.returncode == 0
    assert r.stdout == golden(__file__, "console_class_stdout")
    assert r.stderr == golden(__file__, "console_class_stderr")


PROG_TEST_TLS_HOOKS = r"""const out = (...a) => console.log(...a);
const test = require("node:test");
const assert = require("assert");
out("test exports", typeof test, Object.keys(test).join(","), test.it === test, test.suite === test.describe);
test("passes", () => { out("in passes"); assert.equal(1, 1); });
test("with options", { skip: false }, (t) => { out("in with options", t.name, typeof t.diagnostic); });
test.describe("suite", () => { test.it("inner ok", () => out("inner")); });
test.describe(() => out("anonymous describe"));
const m = test.mock.fn((x) => x * 2); out("mock fn", m(4), typeof test.mock.fn());
test("fails sync", () => { assert.equal(1, 2); }).catch((e) => out("rejected with", e.code));
test("async", async () => { await new Promise((r) => setTimeout(r, 1)); out("in async"); }).then(() => out("async settled"));
const tls = require("tls");
const cert = { subject: { CN: "example.com" }, subjectaltname: "DNS:example.com, DNS:*.example.org, IP Address:10.0.0.1" };
out("checkServerIdentity ok", tls.checkServerIdentity("example.com", cert), tls.checkServerIdentity("a.example.org", cert), tls.checkServerIdentity("10.0.0.1", cert));
const bad = tls.checkServerIdentity("evil.com", cert);
out("checkServerIdentity bad", bad.code, bad.message, bad.host);
out("deep wildcard", tls.checkServerIdentity("a.b.example.org", cert) instanceof Error);
const ctx = {}; tls.convertALPNProtocols(["h2", "http/1.1"], ctx); out("alpn", ctx.ALPNProtocols.toString("hex"));
out("tls consts", tls.DEFAULT_ECDH_CURVE, tls.CLIENT_RENEG_LIMIT, tls.getCiphers().length, tls.getCiphers()[0], typeof tls.createSecureContext());
const { AsyncLocalStorage, AsyncResource, executionAsyncId, createHook } = require("async_hooks");
const als = new AsyncLocalStorage();
out("als run", als.run({ id: 1 }, () => als.getStore().id), als.getStore());
als.run({ id: 2 }, () => { Promise.resolve().then(() => out("als in promise", JSON.stringify(als.getStore()))); setTimeout(() => out("als in timeout", JSON.stringify(als.getStore())), 2); });
als.enterWith({ id: 3 }); out("enterWith", als.getStore().id); als.disable(); out("disabled", als.getStore());
out("async_hooks misc", typeof executionAsyncId(), typeof createHook({}).enable, typeof AsyncResource);
const consumers = require("stream/consumers");
const { Readable } = require("stream");
(async () => {
  out("consumers text", await consumers.text(Readable.from(["a", "b"])));
  out("consumers json", JSON.stringify(await consumers.json(Readable.from(['{"k":', "1}"]))));
  out("consumers buffer", (await consumers.buffer(Readable.from([Buffer.from("xy")]))).toString("hex"));
  out("consumers arrayBuffer", (await consumers.arrayBuffer(Readable.from([Buffer.from("xyz")]))).byteLength);
  const insp = require("inspector");
  out("inspector", typeof insp.open, insp.url(), typeof insp.Session);
})();
"""


def test_node_test_runner_tls_helpers_async_hooks(run):
    """CATCHES: the minimal node:test runner (eager execution, options overload, describe/it, mock.fn,
    failing tests reported on stderr and rejecting), tls.checkServerIdentity/convertALPNProtocols,
    AsyncLocalStorage semantics (the reference does not propagate stores into async callbacks),
    stream/consumers helpers and the inspector stubs."""
    r = run(["-e", PROG_TEST_TLS_HOOKS])
    assert (r.returncode, r.stderr) == (0, b'test "fails sync" failed: Assertion failed\n')
    assert r.stdout == golden(__file__, "test_tls_hooks")
