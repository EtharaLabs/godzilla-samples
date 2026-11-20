"""Node library modules built on plain JS: Buffer and node:buffer helpers, node:util (inspect, format,
types, promisify/callbackify, inherits, deprecate, parseArgs, text helpers, MIMEType), TextEncoder /
TextDecoder and node:string_decoder, node:querystring and the legacy node:url API, node:assert error
reporting, node:vm contexts and the deterministic bits of node:os / node:constants."""

from conftest import check_script, resources_for

G = resources_for(__file__)

# Prints strings with every non-printable / non-ASCII code unit escaped so goldens stay readable.
ESC = r'''
const esc = (s) => String(s).replace(/[\u0000-\u001f\u007f-\uffff]/g,
  (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
'''


def test_buffer_string_encodings(run, workdir):
    """CATCHES: wrong utf8/hex/base64/base64url/latin1/ascii/utf16le codecs, base64url keeping '+/='
    padding, a strict hex/base64 decoder (the reference skips invalid characters instead of stopping),
    ascii decoding not masking the high bit, odd-length utf16le not dropping the last byte, wrong
    byteLength per encoding, and wrong isEncoding / unknown-encoding TypeError messages."""
    check_script(run, workdir, G, "buffer_string_encodings", ESC + r'''
const b = Buffer.from("héllo wörld €😀");
console.log("utf8", b.length, b.toString("hex"));
console.log("base64", b.toString("base64"), b.toString("base64url"));
console.log("b64 tail", Buffer.from([0xfb, 0xff, 0xfe]).toString("base64"), Buffer.from([0xfb, 0xff, 0xfe]).toString("base64url"),
  Buffer.from([1]).toString("base64"), Buffer.from([1]).toString("base64url"), Buffer.from([1, 2]).toString("base64"));
console.log("b64 decode", Buffer.from("aGk", "base64").toString(), Buffer.from("aGVsbG8gd29ybGQ", "base64url").toString(),
  Buffer.from("aG V\nsbG8=!!", "base64").toString(), Buffer.from("-__-", "base64").toString("hex"), Buffer.from("+//+", "base64url").toString("hex"));
console.log("hex decode", Buffer.from("zz12g3456", "hex").toString("hex"), Buffer.from("abc", "hex").toString("hex"), Buffer.from("DEADbeef", "hex").toString("hex"), Buffer.from("", "hex").length);
console.log("latin1", Buffer.from("é€ÿ", "latin1").toString("hex"), Buffer.from("x", "binary").toString("hex"), esc(Buffer.from([0x48, 0xe9, 0xff]).toString("latin1")));
console.log("ascii", Buffer.from("é", "ascii").toString("hex"), esc(Buffer.from([0x48, 0xe9, 0xff, 0x7f]).toString("ascii")));
console.log("utf16le", Buffer.from("hi€", "utf16le").toString("hex"), Buffer.from("hi€", "ucs2").toString("hex"), Buffer.from("A", "UCS-2").toString("hex"),
  esc(Buffer.from([0x68, 0, 0x69, 0, 0x41]).toString("utf16le")), esc(Buffer.from("😀", "utf16le").toString("utf16le")));
console.log("utf8 invalid", esc(Buffer.from([0x61, 0xc3, 0x28, 0xff, 0x62]).toString()), esc(Buffer.from([0xe2, 0x82]).toString("utf-8")));
console.log("case", Buffer.from("AB", "HEX").toString("BASE64"), Buffer.from("hi", "UTF-8").toString("Latin1"));
console.log("range", b.toString("utf8", 1, 3), b.toString(undefined, 0, 1), b.toString("hex", 18), JSON.stringify(b.toString("hex", 5, 5)));
console.log("byteLength", Buffer.byteLength("€"), Buffer.byteLength("€", "utf16le"), Buffer.byteLength("abcd", "base64"),
  Buffer.byteLength("abcdef", "hex"), Buffer.byteLength("é", "latin1"), Buffer.byteLength(new Uint16Array(3)), Buffer.byteLength(new ArrayBuffer(7)));
console.log("isEncoding", ["utf8", "UTF-8", "hex", "base64url", "binary", "ucs-2", "utf-16le", "latin2", "", null, 1].map(Buffer.isEncoding).join());
for (const f of [() => Buffer.from("x", "latin2"), () => b.toString("utf32"), () => Buffer.from(42), () => Buffer.from(null), () => Buffer.alloc(2, "a", "nope")]) {
  try { f(); console.log("no error"); } catch (e) { console.log(e.name + ": " + e.message); }
}
console.log("atob/btoa", btoa("hiÿ"), esc(atob("aGn/")));
''')


def test_buffer_bytes_views_and_comparison(run, workdir):
    """CATCHES: wrong LE/BE integer accessors, writes not truncated to 8/32 bits, reads past the end
    (the reference does no bounds checking: undefined / 0 instead of a RangeError), slice() sharing memory
    (the reference copies; subarray shares), Buffer.from(ArrayBuffer, offset, length) aliasing, wrong
    compare/equals/concat/alloc-fill/write() return values and toJSON shape."""
    check_script(run, workdir, G, "buffer_bytes_views_and_comparison", r'''
const b = Buffer.from([0x01, 0x02, 0x03, 0x04, 0xff, 0xfe, 0x80, 0x00]);
console.log("u8/u16", b.readUInt8(0), b.readUInt8(4), b.readUInt8(), b.readUInt16LE(0), b.readUInt16BE(0), b.readUInt16LE(4), b.readUInt16BE(4));
console.log("u32", b.readUInt32LE(0), b.readUInt32BE(0), b.readUInt32LE(4), b.readUInt32BE(4));
console.log("past end", b.readUInt8(8), b.readUInt16LE(7), b.readUInt32BE(6), b.readUInt16BE(7));
const w = Buffer.alloc(6);
console.log("writes", w.writeUInt8(0x1ff, 0), w.writeUInt8(-1, 1), w.writeUInt32LE(0xdeadbeef, 2), w.toString("hex"));
console.log("writes2", w.writeUInt32LE(-2, 1), w.toString("hex"), w.writeUInt32LE(0x0a0b0c0d, 4), w.toString("hex"), w.length);
console.log("accessors", ["readInt8", "readInt16LE", "readInt32BE", "readFloatLE", "readDoubleBE", "readBigUInt64LE", "writeUInt16BE", "swap16", "fill", "indexOf", "includes", "copy"].map((m) => m + "=" + typeof b[m]).join(" "));
const s = Buffer.from("abcdef");
const sl = s.slice(1, 3), sub = s.subarray(1, 3);
sl[0] = 0x58; sub[1] = 0x59;
console.log("views", s.toString(), sl.toString(), sub.toString(), Buffer.isBuffer(sl), Buffer.isBuffer(sub), sub.constructor.name, sl instanceof Uint8Array);
console.log("negative", s.slice(-2).toString(), s.slice(4, 2).length, s.subarray(-3, -1).toString(), s.slice().length);
const ab = new ArrayBuffer(8); const v = new Uint8Array(ab); v.set([1, 2, 3, 4, 5, 6, 7, 8]);
const fa = Buffer.from(ab, 2, 3); v[2] = 0xaa;
console.log("from ab", fa.toString("hex"), Buffer.from(ab, 6).toString("hex"), Buffer.from(new Uint16Array([0x102, 0x304])).toString("hex"), Buffer.from(v).toString("hex"));
console.log("from array", Buffer.from([256, -1, 3.7, "4", "x"]).toString("hex"), Buffer.from({ length: 3, 0: 1, 1: 2 }).toString("hex"), Buffer.from("").length);
console.log("compare", Buffer.compare(Buffer.from("a"), Buffer.from("b")), Buffer.compare(Buffer.from("b"), Buffer.from("a")), Buffer.compare(Buffer.from("ab"), Buffer.from("a")), Buffer.compare(Buffer.from(""), Buffer.from("")));
console.log("equals", Buffer.from("abc").equals(new Uint8Array([97, 98, 99])), Buffer.from("abc").equals("abc"), Buffer.from("abc").equals(Buffer.from("ab")), Buffer.from("abc").compare(Buffer.from("abcd")), Buffer.from("b").compare(new Uint8Array([97])));
try { Buffer.compare("a", Buffer.from("a")); } catch (e) { console.log(e.name + ": " + e.message); }
console.log("sorted", [Buffer.from("b"), Buffer.from("a"), Buffer.from("ab"), Buffer.from("")].sort(Buffer.compare).map((x) => JSON.stringify(x.toString())).join(" "));
console.log("search", s.indexOf(0x64), s.indexOf(0x63), s.indexOf("de"), s.includes(0x59), s.lastIndexOf(0x61));
console.log("concat", Buffer.concat([Buffer.from("ab"), new Uint8Array([0x63]), Buffer.from("de")]).toString(), Buffer.concat([Buffer.from("abc"), Buffer.from("def")], 4).toString(),
  Buffer.concat([Buffer.from("ab")], 5).toString("hex"), Buffer.concat([]).length, Buffer.isBuffer(Buffer.concat([])));
console.log("alloc", Buffer.alloc(5, "ab").toString(), Buffer.alloc(4, 0x101).toString("hex"), Buffer.alloc(4, "ff", "hex").toString("hex"), Buffer.alloc(3, "").toString("hex"), Buffer.alloc(0).length, Buffer.allocUnsafe(3).length, Buffer.allocUnsafeSlow(2).length);
console.log("json", JSON.stringify(Buffer.from("hi!")), JSON.stringify({ buf: Buffer.from([1, 2]) }), JSON.stringify(Buffer.alloc(0)));
const w2 = Buffer.alloc(8);
console.log("write", w2.write("héllo"), w2.toString("hex"), w2.write("zz", 6), w2.write("abcd", 5, 1), w2.write("ff00", "hex"), w2.write("6162", 2, "hex"), w2.write("€", 7), w2.toString("hex"));
console.log("isBuffer", Buffer.isBuffer(Buffer.from("x")), Buffer.isBuffer(new Uint8Array(1)), Buffer.isBuffer("x"), Buffer.isBuffer(null), Buffer.name, Object.getPrototypeOf(Buffer.prototype) === Uint8Array.prototype);
''')


def test_buffer_module_helpers(run, workdir):
    """CATCHES: missing node:buffer exports, an isUtf8 validator that accepts overlong forms, surrogates or
    truncated sequences, isAscii accepting high bytes, wrong ERR_INVALID_ARG_TYPE / ERR_UNKNOWN_ENCODING
    errors, transcode not round-tripping, wrong kMaxLength/kStringMaxLength/INSPECT_MAX_BYTES values."""
    check_script(run, workdir, G, "buffer_module_helpers", r'''
const buffer = require("buffer");
const { isUtf8, isAscii, transcode, constants, kMaxLength, kStringMaxLength, INSPECT_MAX_BYTES, SlowBuffer } = buffer;
console.log(buffer.Buffer === Buffer, buffer.atob === atob, buffer.btoa === btoa, buffer.Blob === Blob, typeof buffer.File);
console.log(kMaxLength, kStringMaxLength, INSPECT_MAX_BYTES, JSON.stringify(constants), SlowBuffer(3).length, Buffer.isBuffer(SlowBuffer(1)));
const cases = {
  ascii: [0x41, 0x7f], high: [0x41, 0x80], euro: [0xe2, 0x82, 0xac], emoji: [0xf0, 0x9f, 0x98, 0x80], truncated: [0xe2, 0x82],
  overlong: [0xc0, 0xaf], surrogate: [0xed, 0xa0, 0x80], tooBig: [0xf4, 0x90, 0x80, 0x80], badCont: [0xe2, 0x28, 0xa1], loneCont: [0x80], empty: [],
};
for (const [k, bytes] of Object.entries(cases)) console.log(k.padEnd(9), isUtf8(new Uint8Array(bytes)), isAscii(Buffer.from(bytes)));
console.log("views", isUtf8(new Uint8Array([0x61, 0x62]).buffer), isAscii(new DataView(new Uint8Array([0x61]).buffer)), isUtf8(new Uint16Array([0x4141])));
for (const f of [() => isUtf8("abc"), () => isAscii(null), () => transcode("str", "utf8", "latin1"), () => transcode(Buffer.from("x"), "utf8", "ebcdic")]) {
  try { f(); console.log("no error"); } catch (e) { console.log(e.name, e.code, e.message); }
}
const latin = transcode(Buffer.from("café €"), "utf8", "latin1");
console.log("transcode", latin.toString("hex"), transcode(latin, "latin1", "utf8").toString(), transcode(Buffer.from("hi"), "utf8", "ucs2").toString("hex"), Buffer.isBuffer(latin));
console.log("resolveObjectURL", buffer.resolveObjectURL("blob:nodedata:abc"));
''')


def test_util_inspect_shapes(run, workdir):
    """CATCHES: an inspect that differs from the reference formatter: string quoting/escaping at top level vs
    nested, function/class labels, the default depth of 2 ([Array]/[Object] markers), Map/Set (including the
    two-space empty form), key quoting rules, class-name prefixes, [Circular *1], Buffer/typed-array forms,
    inspect.custom hooks, showHidden, getters being invoked, and array holes."""
    check_script(run, workdir, G, "util_inspect_shapes", r'''
const util = require("util");
const i = util.inspect;
console.log(i("str"), i(["it's", "x"]), i(42), i(-0), i(10n), i(true), i(null), i(undefined), i(Symbol("s")), i(Symbol()));
console.log(i(function named() {}), i(() => {}), i(class Foo {}), i(async function af() {}), i(Math.max), i(function* g() {}));
console.log(i([]), i({}), i([1, [2, [3, [4, [5]]]]]), i({ a: { b: { c: { d: { e: 1 } } } } }));
console.log(i({ a: { b: { c: { d: 1 } } } }, { depth: 0 }), i({ a: { b: { c: { d: 1 } } } }, { depth: Infinity }), i([[[[1]]]], { depth: 1 }), i({ m: new Map([[1, [2]]]) }, { depth: 1 }));
console.log(i(new Map([["k", { v: [1] }], [{}, null]])), i(new Set([1, "two", [3]])), i(new Map()), i(new Set()), i(new Map([[new Map(), new Set([new Set()])]])));
console.log(i({ "a-b": 1, valid_id: 2, $d: 3, "1x": 4, [Symbol("sym")]: 5, "": 6, "it's": 7 }));
class Point { constructor() { this.x = 1; this.y = 2; } }
class Empty {}
class Sub extends Point {}
console.log(i(new Point()), i(new Empty()), i(new Sub()), i(Object.create(null)), i(Object.create({ inherited: 1 })), i({ constructor: { name: "Fake" }, z: 1 }));
const circ = { name: "c" }; circ.self = circ; circ.arr = [circ, { back: circ }];
console.log(i(circ));
const shared = { s: 1 }; console.log(i({ a: shared, b: shared, c: [shared, shared] }));
console.log(i(new Error("boom")).split("\n")[0], "|", i(new TypeError("bad")).split("\n")[0]);
console.log(i(/re+/gi), i(new Date(0)), i(new Date(NaN)), i(new Date("2020-02-29T12:34:56.789Z")), i([new Date(86400000)]));
console.log(i(Buffer.from("hello")), i(Buffer.alloc(0)), i({ buf: Buffer.from([255, 0]) }));
console.log(i(Buffer.alloc(52, 1)));
console.log(i(new Uint8Array([1, 2, 3])), i(new Float64Array(2)), i(new ArrayBuffer(4)), i(new DataView(new ArrayBuffer(2))), i([new Uint8Array(0)]));
console.log(i({ [util.inspect.custom]: (depth, opts) => `<custom depth=${depth} ${typeof opts} ${opts.depth}>` }), i([{ [util.inspect.custom]() { return 7; } }]), i({ k: { [Symbol.for("nodejs.util.inspect.custom")]: (d) => "inner@" + d } }));
console.log(i([1, 2], { showHidden: true }), i([1, 2], true), i({ get g() { return "got"; }, set s(v) {} }));
const o = {}; Object.defineProperty(o, "hid", { value: 1, enumerable: false }); o.vis = 2; o[Symbol("sk")] = 3;
console.log(i(o), i(o, { showHidden: true }));
console.log(i(new Promise(() => {})), i(Promise.resolve(4)), i(new WeakMap()), i(new Proxy({ a: 1 }, {})), i(new Number(3)), i(new String("ab")));
console.log(i({ arr: new Array(3) }), i([1, , 3]), i([undefined, null]), i({ u: undefined }), i([[]]), i([{}]));
console.log(i("top 'quoted'"), i(["nested 'q'"]), JSON.stringify(i({ s: "multi\nline", t: "tab\there" })));
console.log(i({ a: 1, b: "x".repeat(30) }, { breakLength: 20, compact: false, sorted: true, colors: true }));
console.log(util.inspect.defaultOptions.depth, typeof util.inspect.custom, util.inspect.custom === Symbol.for("nodejs.util.inspect.custom"));
''')


def test_util_format_specifiers(run, workdir):
    """CATCHES: wrong handling of %s (objects inspected at depth 0, bigint suffix, symbols), %d/%i/%f number
    coercion, %j (including the [Circular] fallback), %o/%O, %c being swallowed, %% escapes, unknown
    specifiers left verbatim, missing arguments left as-is and extra arguments appended (strings raw,
    objects inspected)."""
    check_script(run, workdir, G, "util_format_specifiers", r'''
const util = require("util");
const f = util.format;
console.log(f("%s|%s|%s|%s", "str", 42, 5n, { a: { b: 1 } }));
console.log(f("%d|%d|%d|%d|%d|%d", "42", "x", 3.9, 7n, null, {}));
console.log(f("%i|%i|%i|%f|%f|%f", "42.9px", -3.9, "z", "3.5e2", "abc", 1));
console.log(f("%j|%j|%j|%j", { a: [1, "x"] }, "s", undefined, [new Date(0)]));
const c = {}; c.c = c; console.log(f("%j", c), f("%s", c));
console.log(f("%o / %O", [1, { a: 2 }], { b: "x" }));
console.log(JSON.stringify(f("%c styled %c", "color: red", "x")), f("100%% sure %s", "yes"), f("%x %q %", 1), f("%%s %s", "a"));
console.log(f("missing %s and %d"), "|", f("%s", "a", "extra", 1, { k: 1 }, [2]));
console.log(f(1, 2, "three", { four: 4 }), JSON.stringify(f()), f("only"), f(null, undefined), JSON.stringify(f("%s")), f({ a: 1 }, "%s", 2));
console.log(util.formatWithOptions({ depth: 0 }, "%O", { a: { b: 1 } }), util.formatWithOptions({}, { x: [1] }), util.formatWithOptions({ depth: 5 }, "%s", { a: { b: { c: 1 } } }));
console.log(f("%s", Symbol("q")), f("%s", null), f("%s", undefined), f("%s", [1, [2, 3]]), f("%s", function fn() { return 1; }), f("%s", new Map([[1, 2]])));
console.log(f("%s %s", "-0", -0), f("%d", -0), f("%d", ""), f("%i", ""), f("%f", ""), f("%d", "0x1A"), f("%i", "0x1A"), f("%f", "1e3x"));
''')


def test_util_types_predicates(run, workdir):
    """CATCHES: util.types predicates that confuse related shapes (typed arrays vs DataView, ArrayBuffer vs
    SharedArrayBuffer, boxed primitives vs primitives, Map/Set iterators, generator objects vs generator
    functions, proxies), plus wrong legacy util.is* helpers and util/types / sys module identities."""
    check_script(run, workdir, G, "util_types_predicates", r'''
const util = require("util");
const t = util.types;
const samples = {
  date: new Date(0), re: /x/, map: new Map(), set: new Set(), wm: new WeakMap(), ws: new WeakSet(),
  prom: Promise.resolve(), gen: (function* () {})(), genfn: function* () {}, asyncfn: async () => {}, plainfn: () => {},
  args: (function () { return arguments; })(), u8: new Uint8Array(1), f32: new Float32Array(1), dv: new DataView(new ArrayBuffer(1)),
  ab: new ArrayBuffer(1), sab: new SharedArrayBuffer(1), boxedNum: new Number(1), boxedStr: Object("s"), boxedBool: new Boolean(false),
  boxedSym: Object(Symbol("q")), boxedBig: Object(1n), num: 1, str: "s", nul: null, err: new TypeError("x"), errLike: { name: "Error", message: "m" },
  mapIter: new Map().keys(), setIter: new Set().values(), arrIter: [].values(), proxy: new Proxy({}, {}), buf: Buffer.alloc(1),
  bigArr: new BigInt64Array(1), u8c: new Uint8ClampedArray(1), i16: new Int16Array(1), obj: {},
};
const preds = Object.keys(t).filter((k) => typeof t[k] === "function").sort();
console.log(preds.length, preds.join(" "));
for (const [name, v] of Object.entries(samples)) console.log(name.padEnd(9), preds.filter((p) => t[p](v) === true).map((p) => p.slice(2)).join(",") || "-");
console.log(util.isArray([]), util.isDate(new Date(0)), util.isError(new Error()), util.isRegExp(/a/), util.isPrimitive(null), util.isPrimitive({}), util.isPrimitive(Symbol()),
  util.isNullOrUndefined(undefined), util.isObject(null), util.isObject([]), util.isBuffer(Buffer.alloc(0)), util.isBuffer(new Uint8Array(0)), util.isFunction(class {}),
  util.isString(""), util.isNumber(NaN), util.isBoolean(0), util.isSymbol(Symbol()), util.isUndefined(null), util.isNull(null));
console.log(require("util/types") === util.types, require("node:util/types") === t, require("sys") === util, require("node:util") === util);
console.log(JSON.stringify(util._extend({ a: 1 }, { b: 2 })), util.TextEncoder === TextEncoder, util.TextDecoder === TextDecoder);
''')


def test_util_promisify_callbackify_inherits(run, workdir):
    """CATCHES: promisify not resolving with the first callback value / not rejecting with the error / losing
    `this`, ignoring util.promisify.custom, callbackify invoking callbacks synchronously or not wrapping a
    falsy rejection, inherits not wiring super_ and the prototype chain or wrong argument errors, and
    deprecate warning more than once per function or printing to stdout instead of stderr."""
    check_script(run, workdir, G, "util_promisify_callbackify_inherits", r'''
const util = require("util");
function legacy(a, b, cb) { setTimeout(() => (a < 0 ? cb(new Error("neg " + a)) : cb(null, a + b, "second")), 1); }
const p = util.promisify(legacy);
function custom() {}
custom[util.promisify.custom] = () => Promise.resolve("custom!");
console.log(util.promisify(custom) === custom[util.promisify.custom], util.promisify.custom === Symbol.for("nodejs.util.promisify.custom"), typeof p, p.name);
for (const f of [() => util.promisify(5), () => util.callbackify("x")]) {
  try { f(); } catch (e) { console.log(e.name + ": " + e.message); }
}
const obj = { k: 10, m(x, cb) { cb(null, this.k + x); } };
obj.pm = util.promisify(obj.m);
(async () => {
  console.log("resolved", await p(1, 2));
  try { await p(-1, 0); } catch (e) { console.log("rejected", e.message); }
  console.log("this", await obj.pm(5));
  console.log("custom", await util.promisify(custom)());
  const cbf = util.callbackify(async (x) => { if (x === "bad") throw new RangeError("nope"); return x.toUpperCase(); });
  cbf("ok", (err, v) => console.log("cb ok", err, v));
  cbf("bad", (err, v) => console.log("cb bad", err.name, err.message, v));
  util.callbackify(() => Promise.reject(null))((err) => console.log("cb falsy", err.name, err.message));
  console.log("sync after callbackify calls");
  await new Promise((r) => setTimeout(r, 5));
  function Animal(name) { this.name = name; }
  Animal.prototype.speak = function () { return this.name + " speaks"; };
  function Dog(name) { Animal.call(this, name); }
  util.inherits(Dog, Animal);
  const d = new Dog("rex");
  console.log(d.speak(), d instanceof Animal, Dog.super_ === Animal, Object.keys(Dog).length, Object.getPrototypeOf(Dog.prototype) === Animal.prototype);
  for (const args of [[null, Animal], [Dog, null], [Dog, Object.create(null, { prototype: { value: undefined } })]]) {
    try { util.inherits(...args); } catch (e) { console.log(e.name + ": " + e.message); }
  }
  const old = util.deprecate(function (x) { return x * 2 + (this && this.k || 0); }, "old() is deprecated, use new()", "DEP0999");
  const noCode = util.deprecate(() => "nc", "noCode is going away");
  console.log("deprecated results", old(2), old.call({ k: 100 }, 3), noCode(), noCode());
})();
''', stderr="DeprecationWarning: [DEP0999] old() is deprecated, use new()\n"
            "DeprecationWarning: noCode is going away\n")


def test_util_parse_args_and_text_helpers(run, workdir):
    """CATCHES: a parseArgs tokenizer that mishandles short groups, inline values, `multiple`, defaults,
    the `--` terminator, tokens output and the exact ERR_PARSE_ARGS_* messages; wrong styleText ANSI codes
    or validation; stripVTControlCharacters / toUSVString / parseEnv / MIMEType / getSystemErrorName /
    util.diff results; and isDeepStrictEqual treating -0/0, prototypes or boxed values loosely."""
    check_script(run, workdir, G, "util_parse_args_and_text_helpers", r'''
const util = require("util");
const { parseArgs } = util;
const opts = { verbose: { type: "boolean", short: "v" }, name: { type: "string", short: "n", default: "anon" }, tag: { type: "string", multiple: true, short: "t" } };
const r = parseArgs({ args: ["-vn", "bob", "--tag=a", "-t", "b", "pos1", "--", "--not-opt"], options: opts, allowPositionals: true });
console.log(JSON.stringify(r.values), JSON.stringify(r.positionals));
const r2 = parseArgs({ args: ["-nX", "--verbose"], options: opts, tokens: true });
console.log(JSON.stringify(r2.values), JSON.stringify(r2.tokens));
console.log(JSON.stringify(parseArgs({ args: [], options: opts }).values), JSON.stringify(parseArgs({ args: ["--unknown", "x", "-abc"], strict: false })));
for (const args of [["--nope"], ["pos"], ["--name"], ["--verbose=yes"], ["--name", "--verbose"], ["-z"], ["-n", "-"]]) {
  try { console.log("ok", JSON.stringify(parseArgs({ args, options: opts }).values)); } catch (e) { console.log(e.name, e.code, e.message); }
}
try { parseArgs({ args: [], options: { bad: { type: "number" } } }); } catch (e) { console.log(e.code, e.message); }
console.log(JSON.stringify(util.styleText("red", "hi")), JSON.stringify(util.styleText(["bold", "underline"], "x")), JSON.stringify(util.styleText("green", "s", { stream: { isTTY: false } })));
try { util.styleText("rainbow", "x"); } catch (e) { console.log(e.name, e.code, e.message); }
try { util.styleText("red", 5); } catch (e) { console.log(e.name, e.message); }
console.log(JSON.stringify(util.stripVTControlCharacters("\u001b[31mred\u001b[39m \u001b[1;4mboth\u001b[0m plain")));
console.log(JSON.stringify(util.toUSVString("a\ud800b\udc00c😀")));
const m = new util.MIMEType('Text/HTML; Charset="utf-8"; q=0.5; bad; x="a\\"b"');
console.log(m.type, m.subtype, m.essence, m.params.get("charset"), m.params.get("x"), m.params.has("bad"), m.params.get("none"), String(m), JSON.stringify(m));
m.params.set("charset", "latin1 x"); m.subtype = "plain"; m.params.delete("q"); console.log(String(m), JSON.stringify([...m.params.keys()]));
for (const f of [() => new util.MIMEType("nonsense"), () => new util.MIMEType("a b/c"), () => m.params.set("bad name", "v")]) {
  try { f(); } catch (e) { console.log(e.code, e.message); }
}
console.log(JSON.stringify(util.parseEnv('A=1\n# comment\nexport B="two\\nlines"\nC = spaced value # trailing\nD=\'single\'\nnoeq\nE=\n')));
console.log(util.getSystemErrorName(-2), util.getSystemErrorName(-13), util.getSystemErrorMessage(-2), util.getSystemErrorName(-99999), util.getSystemErrorMap().get(-17)[0]);
for (const v of [2, -1.5, "x"]) { try { util.getSystemErrorName(v); } catch (e) { console.log(e.name, e.message); } }
console.log(JSON.stringify(util.diff("kitten", "sitting")), JSON.stringify(util.diff(["a", "b"], ["b", "c"])), JSON.stringify(util.diff("same", "same")));
const deq = util.isDeepStrictEqual;
console.log(deq({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] }), deq([1], ["1"]), deq(new Set([{ a: 1 }]), new Set([{ a: 1 }])), deq(new Map([[1, "a"]]), new Map([[1, "b"]])),
  deq(NaN, NaN), deq(0, -0), deq(new Date(1), new Date(1)), deq(Object.create(null), {}), deq(new Uint8Array([1]), new Uint8Array([1])), deq(/a/g, /a/i),
  deq(new Number(1), new Number(2)), deq([1, , 3], [1, undefined, 3]), deq({ a: undefined }, {}));
''')


def test_text_codecs_and_string_decoder(run, workdir):
    """CATCHES: wrong TextEncoder bytes, TextDecoder BOM handling / fatal errors / encoding labels, and the
    reference's StringDecoder behaviour: its utf8 mode does NOT carry partial multi-byte sequences across
    writes (each split half decodes to U+FFFD), base64/hex encode each chunk independently and utf16le drops
    a dangling odd byte; also wrong encoding normalisation and unknown-encoding errors."""
    check_script(run, workdir, G, "text_codecs_and_string_decoder", ESC + r'''
const enc = new TextEncoder(), dec = new TextDecoder();
console.log(enc.encoding, dec.encoding, dec.fatal, dec.ignoreBOM, Array.from(enc.encode("é€😀")).join(","), enc.encode().length, enc.encode("\ud800").join(","));
console.log(dec.decode(new Uint8Array([0xe2, 0x82, 0xac])), esc(dec.decode(new Uint8Array([0xe2, 0x82]))), dec.decode(new Uint8Array([0x61, 0x62]).buffer), JSON.stringify(dec.decode()));
console.log(esc(dec.decode(new Uint8Array([0xef, 0xbb, 0xbf, 0x41]))), esc(new TextDecoder("utf-8", { ignoreBOM: true }).decode(new Uint8Array([0xef, 0xbb, 0xbf, 0x41]))));
console.log(new TextDecoder("UTF8").encoding, new TextDecoder("unicode-1-1-utf-8").encoding, typeof enc.encodeInto);
for (const f of [() => new TextDecoder(" utf-8 ").encoding, () => new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array([0xff])), () => new TextDecoder("latin1"), () => dec.decode("str")]) {
  try { console.log(f()); } catch (e) { console.log(e.name + ": " + e.message); }
}
const { StringDecoder } = require("string_decoder");
const d = new StringDecoder("utf8");
const euro = Buffer.from("€"), emoji = Buffer.from("😀");
console.log("utf8 split", [d.write(euro.subarray(0, 1)), d.write(euro.subarray(1)), d.write(emoji.subarray(0, 3)), d.write(emoji.subarray(3)), d.write(Buffer.from("ok")), d.end()].map(esc).join("|"));
const d2 = new StringDecoder("utf-8");
console.log("utf8 end", [d2.write(Buffer.from([0x61, 0xe2, 0x82])), d2.end(Buffer.from("z")), d2.end()].map(esc).join("|"), d2.encoding);
const d3 = new StringDecoder("hex"); console.log("hex", d3.write(Buffer.from([1, 255])), d3.end(Buffer.from([16])), d3.encoding);
const d4 = new StringDecoder("base64"); console.log("base64", d4.write(Buffer.from("ab")), d4.write(Buffer.from("c")), JSON.stringify(d4.end()));
const d5 = new StringDecoder("utf16le"); console.log("utf16le", JSON.stringify([d5.write(Buffer.from([0x68, 0x00, 0x69])), d5.write(Buffer.from([0x00])), d5.end()]), d5.encoding);
const d6 = new StringDecoder("latin1"); console.log("latin1", esc(d6.write(Buffer.from([0xe9, 0x41]))), new StringDecoder().encoding, new StringDecoder("UCS-2").encoding, new StringDecoder("Base64").encoding);
const d7 = new StringDecoder("ucs2"); console.log("ucs2", d7.write(Buffer.from([0x41, 0x00])), d7.write(new Uint8Array([0x42, 0x00])));
try { new StringDecoder("bogus").write(Buffer.from("x")); } catch (e) { console.log(e.name + ": " + e.message); }
const inherited = function Child(e) { StringDecoder.call(this, e); };
inherited.prototype = StringDecoder.prototype;
console.log("callable", new inherited("utf8").write(Buffer.from("yes")));
''')


def test_querystring_and_legacy_url(run, workdir):
    """CATCHES: querystring.parse not producing null-prototype objects / arrays for repeated keys / custom
    sep+eq, malformed escapes not left verbatim, wrong stringify of arrays/null/objects, escape/unescape and
    unescapeBuffer differences; legacy url.parse field values (lower-cased protocol, auth, port, query
    parsing, slashesDenoteHost), url.format/resolve/urlToHttpOptions, fileURLToPath and domain helpers."""
    check_script(run, workdir, G, "querystring_and_legacy_url", r'''
const qs = require("querystring");
const show = (o) => JSON.stringify(o) + (Object.getPrototypeOf(o) === null ? " (null proto)" : " (object proto)");
console.log(show(qs.parse("a=1&b=two+words&c=%E2%82%AC&a=2&empty=&flag&=noval&a=3")));
console.log(show(qs.parse("x:1;y:2;x:3", ";", ":")), show(qs.parse("")), show(qs.parse("bad=%E2%82&ok=%41")), show(qs.parse("k==v&&")));
console.log(show(qs.parse("a=>b|c=>d", "|", "=>")), show(qs.parse(null)), show(qs.parse("a=1&a=2&b=3", undefined, undefined, { maxKeys: 1 })));
console.log(qs.stringify({ a: 1, b: "two words", c: ["x", "y"], d: null, e: undefined, f: true, g: "€&=", h: {} }));
console.log(qs.stringify({ a: 1, b: 2 }, ";", ":"), JSON.stringify(qs.stringify("str")), JSON.stringify(qs.stringify(null)), qs.stringify({ "k y": "v!'()*~" }), JSON.stringify(qs.stringify({})));
console.log(qs.escape("a b&c/d?é"), qs.unescape("a+b%20c%zz"), qs.unescape("a+b%20c"), qs.unescape("%E2%82%AC"), qs.decode === qs.parse, qs.encode === qs.stringify);
console.log(qs.unescapeBuffer("a%41+%zz%4").toString("hex"), qs.unescapeBuffer("a+b", true).toString(), Buffer.isBuffer(qs.unescapeBuffer("")));
const url = require("url");
const p = (s, ...a) => JSON.stringify(Object.fromEntries(Object.entries(url.parse(s, ...a)).map(([k, v]) => [k, v && typeof v === "object" ? { ...v } : v])));
console.log(p("HTTP://user:pw@Example.com:8080/p/a/t/h?query=string&a=1#hash"));
console.log(p("/path/only?x=1&x=2", true));
console.log(p("//cdn.example.com/lib.js", false, true));
console.log(p("//cdn.example.com/lib.js"));
console.log(p("mailto:someone@example.com"));
console.log(p("http://host.com"));
console.log(p("relative/file.txt#frag", true));
console.log(url.format({ protocol: "https:", hostname: "ex.com", port: 8443, pathname: "/a b", query: { q: "1 2", r: ["x", "y"] }, hash: "#h" }));
console.log(url.format({ protocol: "http", host: "h.com", search: "?s=1", query: { ignored: 1 } }), url.format("as-is"), url.format(new URL("http://x.com/a?b#c")));
console.log(url.format({ protocol: "file:", slashes: true, pathname: "/etc/hosts" }), url.format({ auth: "u:p", host: "h", pathname: "/" }), JSON.stringify(url.format({})));
console.log(url.resolve("http://a.com/b/c/d", "../e"), url.resolve("/one/two/three", "four"), url.resolve("http://a.com/", "//other.com/x"), url.resolve("http://a.com/b", "?q=1"));
console.log(JSON.stringify(url.resolveObject("http://a.com/x/y", "z?k=v")));
console.log(JSON.stringify(url.urlToHttpOptions(new URL("https://u%20x:p@[::1]:8443/p?q=1#h"))), JSON.stringify(url.urlToHttpOptions(new URL("http://plain.com/"))));
console.log(url.fileURLToPath("file:///tmp/a%20b.txt"), url.fileURLToPath(new URL("file:///x/y")), url.pathToFileURL("/x/y.txt").href, url.pathToFileURL("/q").protocol);
console.log(url.domainToASCII("Bücher.example"), url.domainToUnicode("xn--bcher-kva.example"), url.domainToASCII("ascii.COM"), url.URL === URL, url.URLSearchParams === URLSearchParams);
''')


def test_assert_error_messages(run, workdir):
    """CATCHES: wrong AssertionError name/code/message/operator/actual/expected for each assert function
    (the reference uses generic messages such as 'Assertion failed' and 'The error did not match the
    expected criteria.', not Node's diff output), throws/rejects matcher semantics (class, RegExp,
    validation function, property object), assert.fail rethrowing Error instances, ifError, CallTracker,
    and the strict variants mapping equal->strictEqual."""
    check_script(run, workdir, G, "assert_error_messages", r'''
const assert = require("assert");
const util = require("util");
const fmt = (v) => typeof v === "string" ? JSON.stringify(v) : v instanceof Error ? `${v.name}(${v.message})` : typeof v === "function" ? `fn ${v.name}` : util.inspect(v);
function t(label, fn) {
  try { fn(); console.log(label, "passed"); }
  catch (e) { console.log(label, "|", e.name, e.code, JSON.stringify(e.message), e.operator, fmt(e.actual), fmt(e.expected), e instanceof assert.AssertionError, e instanceof Error); }
}
t("ok", () => assert.ok(1));
t("ok0", () => assert.ok(0));
t("okmsg", () => assert(false, "nope"));
t("okerr", () => assert.ok(null, new TypeError("custom error")));
t("eq", () => assert.equal(1, "1"));
t("eqf", () => assert.equal(null, 0));
t("eqnull", () => assert.equal(null, undefined));
t("neq", () => assert.notEqual(1, "1", "loose same"));
t("seq", () => assert.strictEqual("a", "b"));
t("seqNaN", () => assert.strictEqual(NaN, NaN));
t("seq0", () => assert.strictEqual(0, -0));
t("nseq", () => assert.notStrictEqual(2, 2, "should differ"));
t("deq", () => assert.deepEqual({ a: [1, "2"] }, { a: ["1", 2] }));
t("deqf", () => assert.deepEqual([1, 2], [1, 3]));
t("ndeq", () => assert.notDeepEqual([1], ["1"]));
t("dseq", () => assert.deepStrictEqual({ a: [1, 2] }, { a: [1, 2] }));
t("dseqf", () => assert.deepStrictEqual([1], ["1"]));
t("dseqproto", () => assert.deepStrictEqual(Object.create(null), {}));
t("dseqmap", () => assert.deepStrictEqual(new Map([[1, { x: 1 }]]), new Map([[1, { x: 1 }]])));
t("dseqset", () => assert.deepStrictEqual(new Set([1, 2]), new Set([2, 3])));
t("dseqdate", () => assert.deepStrictEqual(new Date(5), new Date(6)));
t("ndseq", () => assert.notDeepStrictEqual({ a: 1 }, { a: 1 }));
t("partial", () => assert.partialDeepStrictEqual({ a: 1, b: { c: 2, d: 3 } }, { b: { c: 2 } }));
t("partialf", () => assert.partialDeepStrictEqual({ a: 1 }, { a: 2 }));
t("match", () => assert.match("hello", /^h/));
t("matchf", () => assert.match("hello", /^x/, "no x"));
t("dnm", () => assert.doesNotMatch("abc", /b/));
t("throws", () => assert.throws(() => { throw new TypeError("bad thing"); }, TypeError));
t("throwsre", () => assert.throws(() => { throw new Error("abc123"); }, /\d+/));
t("throwsobj", () => assert.throws(() => { throw Object.assign(new Error("m"), { code: "E1" }); }, { code: "E1", message: "m" }));
t("throwsobjf", () => assert.throws(() => { throw Object.assign(new Error("m"), { code: "E1" }); }, { code: "E2" }));
t("throwsfn", () => assert.throws(() => { throw new Error("x"); }, (e) => e.message === "x"));
t("throwsclassf", () => assert.throws(() => { throw new Error("plain"); }, RangeError));
t("throwsnone", () => assert.throws(() => {}));
t("throwsnonemsg", () => assert.throws(() => {}, "expected boom"));
t("dnt", () => assert.doesNotThrow(() => { throw new Error("oops"); }));
t("dntmsg", () => assert.doesNotThrow(() => { throw new Error("oops"); }, "extra"));
t("dntother", () => assert.doesNotThrow(() => { throw new TypeError("other kind"); }, RangeError));
t("iferr", () => assert.ifError(null));
t("iferr2", () => assert.ifError(new Error("cb failed")));
t("iferr3", () => assert.ifError("str"));
t("fail", () => assert.fail());
t("failmsg", () => assert.fail("explicit"));
t("failerr", () => assert.fail(new RangeError("as is")));
const s = require("assert/strict");
t("strict.equal", () => s.equal(1, "1"));
t("strict.deepEqual", () => s.deepEqual([1], ["1"]));
t("strict.ok", () => s(""));
console.log(s === assert.strict, s.strict === s, require("node:assert") === assert, new assert.AssertionError({ message: "m", actual: 1, expected: 2, operator: "x" }).message);
const e0 = new assert.AssertionError({}); console.log(e0.message, e0.name, e0.code, String(e0).split("\n")[0]);
const tracker = new assert.CallTracker();
const fn = tracker.calls(function named(x) { return x * 2; }, 2);
const anon = tracker.calls(1);
console.log("tracked result", fn(21));
console.log(JSON.stringify(tracker.report().map((r) => [r.message, r.actual, r.expected, r.operator])));
t("verify", () => tracker.verify());
fn(1); anon(); t("verify2", () => tracker.verify());
(async () => {
  await assert.rejects(Promise.reject(new Error("r1")), /r1/).then(() => console.log("rejects ok"));
  await assert.rejects(Promise.resolve(1)).catch((e) => console.log("rejects none", e.message, e.operator));
  await assert.rejects(async () => { throw new TypeError("t"); }, RangeError).catch((e) => console.log("rejects mismatch", e.message, e.operator, fmt(e.actual)));
  await assert.doesNotReject(Promise.reject(new Error("dr"))).catch((e) => console.log("dnr", e.message, e.operator));
  await assert.doesNotReject(Promise.resolve(2)).then((v) => console.log("dnr ok", v));
})();
''')


def test_vm_contexts(run, workdir):
    """CATCHES: vm contexts that leak assignments to the host scope or fail to write `var`/implicit globals
    back to the sandbox, sandbox lookups not falling back to host globals, Script reuse/filename defaults,
    runInThisContext seeing module locals, wrong TypeError messages for non-contexts, errors from sandboxed
    code not propagating as the same class, and compileFunction parameters."""
    check_script(run, workdir, G, "vm_contexts", r'''
const vm = require("vm");
const ctx = vm.createContext({ x: 2, log: [] });
console.log(vm.isContext(ctx), vm.isContext({}), vm.createContext(ctx) === ctx, vm.runInContext("x * 21", ctx));
vm.runInContext("var y = x + 1; z = 'set'; log.push(typeof Math.max, typeof JSON)", ctx);
console.log(ctx.y, ctx.z, JSON.stringify(ctx.log), typeof y, typeof z);
console.log(vm.runInNewContext("a + b", { a: "con", b: "cat" }), vm.runInNewContext("typeof undefinedThing"), vm.runInNewContext("1 + 1"), vm.runInNewContext(""));
const s = new vm.Script("count += 1; count", { filename: "counter.vm" });
const c2 = vm.createContext({ count: 0 });
console.log(s.runInContext(c2), s.runInContext(c2), c2.count, s.runInNewContext({ count: 41 }), s.filename, new vm.Script("1").filename, vm.createScript("6 * 7").runInThisContext());
globalThis.hostGlobal = "visible";
console.log(vm.runInThisContext("typeof hostGlobal + ':' + hostGlobal"), new vm.Script("hostGlobal.length").runInThisContext());
const localVar = 5;
console.log(vm.runInThisContext("typeof localVar"), localVar);
vm.runInThisContext("var leakedFromVm = 'global now'");
console.log(globalThis.leakedFromVm);
try { new vm.Script("let = ;"); console.log("compiled"); } catch (e) { console.log(e.name); }
for (const f of [() => vm.runInContext("1", {}), () => s.runInContext({}), () => vm.createContext(5), () => vm.createContext(null)]) {
  try { f(); } catch (e) { console.log(e.name + ": " + e.message); }
}
try { vm.runInNewContext("throw new RangeError('inner')"); } catch (e) { console.log(e.name + ": " + e.message, e instanceof RangeError); }
const add = vm.compileFunction("return a + b + (typeof c)", ["a", "b"]);
console.log(add(1, 2), add.length, vm.compileFunction("return 9")(), typeof vm.measureMemory, typeof vm.constants.DONT_CONTEXTIFY, typeof vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER);
console.log(vm.runInNewContext("[1,2].map(v => v * k)", { k: 10 }).join(), vm.runInNewContext("JSON.stringify({q: q})", { q: [1] }), vm.runInNewContext("str.length", { str: "four" }));
const sb = { arr: [] }; vm.runInNewContext("arr.push(1); newProp = 7; function declared() { return 1 }", sb); console.log(JSON.stringify(Object.keys(sb)), sb.arr.length, sb.newProp, typeof sb.declared);
try { new vm.Script("1").createCachedData(); } catch (e) { console.log(e.message); }
vm.measureMemory().then((m) => console.log(JSON.stringify(m)));
''')


def test_os_and_constants_deterministic_bits(run, workdir):
    """CATCHES: wrong os.EOL/devNull, an os.constants that is not the reference's (empty) signals/errno
    tables, wrong node:constants values (the reference ships the darwin numbers, e.g. SIGUSR1=30, EAGAIN=35,
    on every platform), wrong priority validation messages, getPriority/setPriority on a pid that cannot
    exist not raising ERR_SYSTEM_ERROR (ESRCH, errno -3, info object), and a wrong util system-error table."""
    check_script(run, workdir, G, "os_and_constants_deterministic_bits", r'''
const os = require("os");
const constants = require("constants");
console.log(JSON.stringify(os.EOL), os.devNull, JSON.stringify(os.constants), typeof os.platform(), typeof os.cpus().length);
// only the IPv4 loopback entry is host-independent (other interfaces and ::1 vary by machine)
console.log(JSON.stringify((os.networkInterfaces().lo || []).filter((a) => a.family === 'IPv4')));
const pick = ["SIGHUP", "SIGINT", "SIGKILL", "SIGUSR1", "SIGUSR2", "SIGTERM", "SIGCHLD", "SIGSTOP", "ENOENT", "EAGAIN", "EADDRINUSE", "ECONNREFUSED", "ENOTEMPTY", "O_RDONLY", "O_WRONLY", "O_CREAT", "S_IFMT", "PRIORITY_HIGHEST", "RTLD_GLOBAL"];
console.log(pick.map((k) => `${k}=${constants[k]}`).join(" "));
console.log(Object.keys(constants).length, require("node:constants") === constants);
for (const f of [() => os.setPriority(0, 50), () => os.setPriority("x"), () => os.getPriority("1"), () => os.setPriority(0, 1.5)]) {
  try { f(); } catch (e) { console.log(e.name, e.code, e.message); }
}
for (const f of [() => os.getPriority(2147483647), () => os.setPriority(2147483647, 5)]) {
  try { f(); } catch (e) { console.log(e.name, e.code, e.errno, e.syscall, e.message, JSON.stringify(e.info)); }
}
const util = require("util");
console.log(util.getSystemErrorMap().size, util.getSystemErrorName(-4095), util.getSystemErrorMessage(-98765));
''')
