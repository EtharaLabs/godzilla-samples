"""WinterTC Minimum Common Web Platform API surface: DOMException, events/EventTarget, AbortController /
AbortSignal, TextEncoder/TextDecoder, atob/btoa, structuredClone, URL/URLSearchParams/URLPattern,
crypto, Blob/File/FormData, Headers/Request/Response bodies, Readable/Writable/Transform streams,
MessageChannel/BroadcastChannel and the platform globals (navigator, performance, self).

Network-backed APIs (fetch over loopback, Lumen.serve, EventSource, WebSocket) live in
test_runtime_http.py; WebAssembly lives in test_runtime_wasm.py.
"""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

PRELUDE = "const L = (...a) => console.log(...a);\n"


def _run_mjs(run, workdir, src, tier=()):
    write_files(workdir, {"t.mjs": PRELUDE + src})
    return run([*tier, "t.mjs"])


def _check(r, name, stderr=b""):
    assert (r.returncode, r.stderr) == (0, stderr)
    assert r.stdout == golden(__file__, name)


# ---------------------------------------------------------------------------------------------
# DOMException + base64
# ---------------------------------------------------------------------------------------------

PROG_DOMEXCEPTION_BASE64 = r"""
const e = new DOMException("boom", "NotFoundError");
L("domexception", e.name, e.message, e instanceof Error, e instanceof DOMException, String(e), Object.prototype.toString.call(e));
const d = new DOMException();
L("defaults", JSON.stringify(d.name), JSON.stringify(d.message), String(new DOMException("m", 42)), typeof e.stack);
for (const s of ["", "f", "fo", "foo", "foob", "fooba", "foobar", "\x00\xff\x80", "héllo"]) L("btoa", JSON.stringify(s), btoa(s));
L("btoa coerce", btoa(123), btoa(null), btoa(undefined), btoa([1, 2]));
for (const s of ["", "Zg==", "Zg=", "Zg", "Zm9v", "Zm9vYg", " Zm 9v\nYmFy\t", "AAEC/w==", "+/+/", "Zm9vYmFy=="]) {
  try { L("atob", JSON.stringify(s), JSON.stringify(atob(s))); } catch (x) { L("atob", JSON.stringify(s), x.name, x.message, x instanceof DOMException); }
}
for (const s of ["Z", "Zm9v!", "Zg===", "Z===", "-_", "Zm9vY"]) {
  try { L("atob", JSON.stringify(s), JSON.stringify(atob(s))); } catch (x) { L("atob", JSON.stringify(s), x.name, x.message); }
}
for (const s of ["Ā", "€uro", "ok\u0100"]) {
  try { btoa(s); L("no error"); } catch (x) { L("btoa error", x.name, x.message, x instanceof DOMException); }
}
L("roundtrip", atob(btoa("\x00\x01\x02 binary \xfe\xff")) === "\x00\x01\x02 binary \xfe\xff");
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_domexception_and_base64(run, workdir, tier):
    """CATCHES: DOMException with wrong name/message defaults or not an Error subclass; btoa/atob padding,
    whitespace stripping, forgiving-base64 rules, or InvalidCharacterError cases that differ from the reference."""
    _check(_run_mjs(run, workdir, PROG_DOMEXCEPTION_BASE64, tier), "domexception_base64")


# ---------------------------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------------------------

PROG_EVENTS = r"""
const t = new EventTarget();
const log = [];
function h1(e) { log.push(`h1:${e.type}:${e.target === t}:${e.currentTarget === t}:${this === t}`); }
t.addEventListener("x", h1);
t.addEventListener("x", h1); // duplicate (same capture) ignored
t.addEventListener("x", { handleEvent(e) { log.push("obj:" + e.eventPhase + ":" + (this !== t)); } });
t.addEventListener("x", () => log.push("once"), { once: true });
t.addEventListener("x", h1, true); // capture=true is a distinct registration
t.addEventListener("x", null);
t.addEventListener("x", undefined);
L("first", t.dispatchEvent(new Event("x")), log.join(" "));
log.length = 0; t.dispatchEvent(new Event("x")); L("second", log.join(" "));
t.removeEventListener("x", h1);
t.removeEventListener("x", h1, { capture: true });
t.removeEventListener("nope", h1);
log.length = 0; t.dispatchEvent(new Event("x")); L("after remove", log.join(" "));
// a listener removed during dispatch does not run; one added during dispatch does not run either
const t5 = new EventTarget();
const order = [];
const late = () => order.push("late");
const b = () => order.push("b");
t5.addEventListener("go", () => { order.push("a"); t5.removeEventListener("go", b); t5.addEventListener("go", late); });
t5.addEventListener("go", b);
t5.dispatchEvent(new Event("go")); t5.dispatchEvent(new Event("go"));
L("mutation during dispatch", order.join(","));
const ev = new Event("c", { cancelable: true, bubbles: 1, composed: "yes" });
L("init", ev.type, ev.bubbles, ev.cancelable, ev.composed, ev.defaultPrevented, ev.eventPhase, ev.isTrusted, typeof ev.timeStamp, ev.target, ev.currentTarget);
const t2 = new EventTarget();
t2.addEventListener("c", (e) => { e.preventDefault(); e.stopImmediatePropagation(); L("first listener", e.currentTarget === t2); });
t2.addEventListener("c", () => L("never runs"));
L("dispatch result", t2.dispatchEvent(ev), ev.defaultPrevented, ev.currentTarget, ev.target === t2);
const nc = new Event("c"); nc.preventDefault(); L("non-cancelable preventDefault", nc.defaultPrevented);
const sp = new Event("s"); const t6 = new EventTarget(); const sl = [];
t6.addEventListener("s", (e) => { e.stopPropagation(); sl.push(1); }); t6.addEventListener("s", () => sl.push(2));
t6.dispatchEvent(sp); L("stopPropagation keeps same-target listeners", sl.join(","));
L("type coerced", new Event(42).type, new Event(undefined).type, new Event("z", null).bubbles);
try { new Event(); } catch (e) { L(e.name, e.message); }
try { t.dispatchEvent({ type: "x" }); } catch (e) { L(e.name, e.message); }
const ce = new CustomEvent("cc", { detail: { a: 1 }, cancelable: true });
L("custom", ce.type, JSON.stringify(ce.detail), new CustomEvent("z").detail, ce instanceof Event, ce.cancelable);
L("phases", Event.NONE, Event.CAPTURING_PHASE, Event.AT_TARGET, Event.BUBBLING_PHASE);
const t3 = new EventTarget();
t3.addEventListener("err", () => { throw new RangeError("bad listener"); });
t3.addEventListener("err", () => { throw "plain string"; });
t3.addEventListener("err", () => L("later listener still runs"));
L("dispatch with throwing listeners", t3.dispatchEvent(new Event("err")));
const ac = new AbortController();
const t4 = new EventTarget();
t4.addEventListener("y", () => L("y fired"), { signal: ac.signal });
t4.dispatchEvent(new Event("y"));
ac.abort();
t4.dispatchEvent(new Event("y"));
t4.addEventListener("y", () => L("never: signal already aborted"), { signal: ac.signal });
t4.dispatchEvent(new Event("y"));
class Emitter extends EventTarget { fire() { return this.dispatchEvent(new CustomEvent("ping", { detail: 7 })); } }
const em = new Emitter(); em.addEventListener("ping", (e) => L("subclass", e.detail, e.target instanceof Emitter)); em.fire();
"""

EVENTS_STDERR = b"Uncaught (in event listener) RangeError: bad listener\nUncaught (in event listener) plain string\n"


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_event_target_dispatch_semantics(run, workdir, tier):
    """CATCHES: EventTarget bugs: duplicate listeners not deduplicated, capture flag ignored, once/signal
    options broken, handleEvent objects unsupported, stopImmediatePropagation/preventDefault wrong, or a
    throwing listener aborting dispatch instead of being reported to stderr."""
    _check(_run_mjs(run, workdir, PROG_EVENTS, tier), "events", EVENTS_STDERR)


PROG_ABORT = r"""
const ac = new AbortController();
const s = ac.signal;
L("initial", s.aborted, s.reason, s instanceof EventTarget, s instanceof AbortSignal, ac.signal === s);
let n = 0;
s.onabort = function (e) { L("onabort", e.type, this === s); };
s.addEventListener("abort", (e) => { n++; L("listener", e.type, e.target === s); });
ac.abort();
ac.abort("again"); // second abort is a no-op
L("aborted", s.aborted, s.reason.name, s.reason.message, s.reason instanceof DOMException, n);
try { s.throwIfAborted(); } catch (e) { L("throwIfAborted", e === s.reason); }
const s2 = AbortSignal.abort("why");
L("static abort", s2.aborted, s2.reason);
try { s2.throwIfAborted(); } catch (e) { L("thrown reason", e); }
L("abort() default reason", AbortSignal.abort().reason.name);
try { new AbortSignal(); } catch (e) { L(e.name, e.message); }
new AbortController().signal.throwIfAborted(); L("not aborted: no throw");
const a1 = new AbortController(), a2 = new AbortController();
const any = AbortSignal.any([a1.signal, a2.signal]);
any.addEventListener("abort", () => L("any aborted with", any.reason));
L("any pending", any.aborted);
a2.abort("second");
a1.abort("first");
L("any reason", any.reason);
const pre = AbortSignal.any([new AbortController().signal, AbortSignal.abort(42)]);
L("any pre-aborted", pre.aborted, pre.reason);
const err = new Error("custom");
const ac3 = new AbortController(); ac3.abort(err); L("custom reason identity", ac3.signal.reason === err);
const ac4 = new AbortController(); ac4.signal.onabort = () => { throw new Error("in onabort"); }; ac4.abort();
L("after throwing onabort", ac4.signal.aborted);
const ts = AbortSignal.timeout(5);
L("timeout pending", ts.aborted);
await new Promise((resolve) => ts.addEventListener("abort", resolve));
L("timeout", ts.aborted, ts.reason.name, ts.reason.message, ts.reason instanceof DOMException);
"""


def test_abort_controller_signal_any_and_timeout(run, workdir):
    """CATCHES: AbortSignal not firing onabort/listeners exactly once, wrong default AbortError reason,
    AbortSignal.abort/any/timeout statics missing or using wrong reasons, or a constructible AbortSignal."""
    _check(_run_mjs(run, workdir, PROG_ABORT), "abort", b"Uncaught (in onabort) Error: in onabort\n")


# ---------------------------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------------------------

PROG_ENCODING = r"""
const te = new TextEncoder();
L("encoder", te.encoding, Array.from(te.encode("aé€😀")).join(","), te.encode().length, Array.from(te.encode(123)).join(), te.encode("x") instanceof Uint8Array);
const td = new TextDecoder();
L("decoder", td.encoding, td.fatal, td.ignoreBOM);
const bom = new Uint8Array([0xef, 0xbb, 0xbf, 0x68, 0x69]);
L("bom stripped", JSON.stringify(td.decode(bom)), "kept with ignoreBOM", JSON.stringify(new TextDecoder("utf-8", { ignoreBOM: true }).decode(bom)).length);
L("replacement", JSON.stringify(td.decode(new Uint8Array([0x61, 0xff, 0x62, 0xc3]))), JSON.stringify(td.decode(new Uint8Array([0xf0, 0x9f, 0x98, 0x80, 0xed, 0xa0, 0x80]))));
L("inputs", JSON.stringify(td.decode()), JSON.stringify(td.decode(new Uint8Array([104, 105]).buffer)), JSON.stringify(td.decode(new Uint16Array([0x6968]))), JSON.stringify(td.decode(new Int8Array([-61, -87]))));
L("subarray view", td.decode(new TextEncoder().encode("hello world").subarray(6)));
for (const bad of [new DataView(new ArrayBuffer(2)), "str", 5, null]) {
  try { td.decode(bad); L("decoded?"); } catch (e) { L("decode error", e.name, e.message); }
}
const fatal = new TextDecoder("utf-8", { fatal: true });
L("fatal flags", fatal.fatal, fatal.decode(new Uint8Array([0xe2, 0x82, 0xac])));
for (const bytes of [[0xc3], [0xff], [0xed, 0xa0, 0x80], [0xc0, 0x80]]) {
  try { fatal.decode(new Uint8Array(bytes)); L("no error"); } catch (e) { L("fatal", bytes.join(","), e.name, e.message); }
}
for (const lab of ["UTF-8", "utf8", "UTF8", "unicode-1-1-utf-8", " utf-8 ", "latin1", "utf-16le", "windows-1252", "nonsense"]) {
  try { L("label", JSON.stringify(lab), new TextDecoder(lab).encoding); } catch (e) { L("label", JSON.stringify(lab), e.name, e.message); }
}
const sd = new TextDecoder();
L("stream option", JSON.stringify(sd.decode(new Uint8Array([0xe2, 0x82]), { stream: true }) + sd.decode(new Uint8Array([0xac]))));
L("roundtrip", td.decode(te.encode("mixed ascii, ünïcödé, 中文, 🎉")) === "mixed ascii, ünïcödé, 中文, 🎉");
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_text_encoder_decoder(run, workdir, tier):
    """CATCHES: wrong UTF-8 encoding, BOM handling ignoring ignoreBOM, replacement-character decoding
    differences, fatal mode not throwing TypeError, accepting non-utf-8 labels, or BufferSource input handling."""
    _check(_run_mjs(run, workdir, PROG_ENCODING, tier), "encoding")


# ---------------------------------------------------------------------------------------------
# structuredClone
# ---------------------------------------------------------------------------------------------

PROG_CLONE = r"""
const o = { n: 1, s: "x", b: true, u: undefined, nl: null, big: 10n, d: new Date(86400000), re: /ab+c/gi,
  m: new Map([[1, { k: "v" }], [{ key: true }, "objkey"]]), st: new Set([1, "two", 1]), arr: [1, , 3], ab: new Uint8Array([1, 2, 3]).buffer,
  ta: new Int16Array([-1, 2]), f64: new Float64Array([1.5]), err: new RangeError("bad range"), te: new TypeError("t"), nested: { deep: [{ x: 1 }] } };
o.self = o;
o.arr2 = o.arr;
o.m.set("cycle", o);
o.re.lastIndex = 3;
const c = structuredClone(o);
L("identity", c !== o, c.self === c, c.arr2 === c.arr, c.m.get("cycle") === c);
L("primitives", c.n, c.s, c.b, "u" in c, c.u, c.nl, typeof c.big, c.big);
L("date", c.d instanceof Date, c.d.toISOString(), c.d !== o.d);
L("regexp", c.re instanceof RegExp, c.re.source, c.re.flags, c.re !== o.re, c.re.lastIndex);
L("map", c.m instanceof Map, c.m.size, c.m.get(1).k, c.m.get(1) !== o.m.get(1), [...c.m.keys()].map((k) => typeof k).join());
L("set", c.st instanceof Set, [...c.st].join("|"));
L("sparse array", c.arr.length, 1 in c.arr, String(c.arr));
L("arraybuffer", c.ab instanceof ArrayBuffer, c.ab.byteLength, new Uint8Array(c.ab).join(), c.ab !== o.ab);
L("typed", c.ta.constructor.name, c.ta.join(), c.f64[0], c.ta.buffer !== o.ta.buffer);
L("errors", c.err instanceof RangeError, c.err.name, c.err.message, c.err !== o.err, c.te instanceof TypeError);
L("nested", JSON.stringify(c.nested), c.nested.deep[0] !== o.nested.deep[0]);
for (const [label, bad] of [["function", () => 1], ["symbol", Symbol("s")], ["promise", Promise.resolve(1)], ["method", { f() {} }], ["in map", new Map([[1, () => 2]])]]) {
  try { structuredClone(bad); L(label, "cloned?"); } catch (e) { L(label, e.name, e.message, e instanceof DOMException); }
}
class Pt { constructor() { this.x = 1; } get y() { return 2; } }
const pc = structuredClone(new Pt());
L("class instance", pc instanceof Pt, Object.getPrototypeOf(pc) === Object.prototype, JSON.stringify(pc));
L("top-level primitives", structuredClone(5), structuredClone("s"), structuredClone(null), structuredClone(undefined), structuredClone(-0) === 0, typeof structuredClone(1n));
const sym = { [Symbol("k")]: 1, v: 2 }; L("symbol keys dropped", JSON.stringify(Object.keys(structuredClone(sym))));
const nonEnum = Object.defineProperty({ a: 1 }, "hidden", { value: 2, enumerable: false }); L("non-enumerable dropped", JSON.stringify(Object.getOwnPropertyNames(structuredClone(nonEnum))));
const getter = { get g() { return "computed"; } }; L("getter value captured", Object.getOwnPropertyDescriptor(structuredClone(getter), "g").value);
const sub = new Uint8Array([1, 2, 3, 4]).subarray(1, 3); const subc = structuredClone(sub);
L("subarray", subc.length, subc.join(), subc.byteOffset, subc.buffer.byteLength);
const shared = { v: 1 }; const pair = structuredClone([shared, shared]); L("shared refs", pair[0] === pair[1]);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_structured_clone(run, workdir, tier):
    """CATCHES: structuredClone losing cycles/shared references, Date/RegExp/Map/Set/Error/ArrayBuffer/typed
    array copies that alias the original or lose type, keeping prototypes or non-enumerable props, or
    missing DataCloneError for functions/symbols/promises."""
    _check(_run_mjs(run, workdir, PROG_CLONE, tier), "structured_clone")


# ---------------------------------------------------------------------------------------------
# URL / URLSearchParams / URLPattern
# ---------------------------------------------------------------------------------------------

PROG_URL_PARSE = r"""
const show = (s, b) => { try { const u = b === undefined ? new URL(s) : new URL(s, b); L(JSON.stringify([u.href, u.protocol, u.username, u.password, u.host, u.hostname, u.port, u.pathname, u.search, u.hash, u.origin])); } catch (e) { L(JSON.stringify(s), e.name, e.message); } };
for (const s of [
  "HTTP://User:Pw@Example.COM:8080/a/./b/../c?q=1&r=a+b#Frag",
  "https://x.com:443", "http://x.com:80/", "http://x.com:8080", "ws://h:80/p", "wss://h:443/", "ftp://h:21/", "ftp://h:2121/f",
  "http://[::1]:9000/x", "http://[2001:DB8::1]/", "custom://host:99/p", "custom://host", "file:///etc/passwd", "file://server/share",
  "mailto:Joe@Example.com?subject=hi", "data:text/plain,hello#x", "javascript:void(0)", "urn:isbn:123",
  "http://user@h/", "http://:pass@h/", "http://a@b@c/", "http://h/a/b/../../..", "http://h/a/%2e%2e/b", "http://h/?#", "http://h/p?a=1#f?g",
  "  http://trim.me/path  ", "http://h/a b", "HTTPS://UPPER.CASE/Path", "a+b-c.d://x/y",
]) show(s);
for (const bad of ["", "nobase", "http://", "http:x.com", "https:/x.com", "http://bücher.de/", "http://h:99999/", "http://h:abc/", "http://[::1/", "//no-scheme", "1http://x"]) show(bad);
L("canParse", URL.canParse("http://a"), URL.canParse("nope"), URL.canParse("x", "http://a/"), URL.canParse("x", "bad base"));
L("parse", URL.parse("zz"), URL.parse("/p", "http://a").href, URL.parse(new URL("http://obj/")).href);
L("toString/toJSON", String(new URL("http://s/x")), JSON.stringify({ u: new URL("http://j/y") }), new URL("http://o/") + "");
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_url_parsing_components_and_errors(run, workdir, tier):
    """CATCHES: URL parsers with different component splitting, default-port elision, host lowercasing,
    path dot-segment normalization, opaque-path handling, origin strings, or TypeError messages for invalid
    input (missing host, bad port, non-ASCII host, missing base)."""
    _check(_run_mjs(run, workdir, PROG_URL_PARSE, tier), "url_parse")


PROG_URL_RELATIVE = r"""
const base = "http://user:pw@x.com:8080/a/b/c?old#f";
for (const r of ["d", "../d", "../../../../d", "/d", "?q=2", "#g", "", "//y.com/z", "//y.com", "./", ".", "..", "d/./e/../f/", "  d  ", "d?x#y", "/", "https://abs.com/", "mailto:x@y"]) {
  L(JSON.stringify(r).padEnd(18), new URL(r, base).href);
}
L("base object", new URL("z", new URL("http://b.com/dir/file")).href);
try { new URL("rel", "also-rel"); } catch (e) { L(e.name, e.message); }
try { new URL("rel", "mailto:x"); L("opaque base ok"); } catch (e) { L(e.name, e.message); }
const u = new URL("http://a.com/p?x=1");
u.pathname = "/new/../path"; u.search = "y=2"; u.hash = "h"; u.port = "8080"; u.hostname = "B.com";
L("setters", u.href, u.host, u.origin);
u.port = "80"; L("default port", u.href, JSON.stringify(u.port));
u.search = ""; u.hash = ""; L("cleared", u.href);
u.search = "?already"; u.hash = "#hashed"; L("prefixed", u.href);
u.href = "https://z.org/"; L("href setter", u.href, u.origin, u.protocol);
for (const f of [() => { u.href = "bad"; }, () => { u.port = "x"; }, () => { u.hostname = ""; }]) {
  try { f(); L("no error", u.href); } catch (e) { L(e.name, e.message); }
}
L("unchanged after failed set", u.href);
const cred = new URL("http://user:pw@h.com:81/a?q#f"); cred.pathname = "/b"; L("recompose keeps credentials", cred.href);
const onlyUser = new URL("http://user@h.com/"); onlyUser.hash = "x"; L("username only", onlyUser.href);
const file = new URL("file:///tmp/a.txt"); file.pathname = "/etc/b.txt"; file.search = "v=1"; L("file recompose", file.href);
const opaque = new URL("mailto:a@b.c"); opaque.search = "subject=x"; L("opaque recompose", opaque.href);
"""


def test_url_relative_resolution_and_setters(run, workdir):
    """CATCHES: wrong RFC 3986 relative resolution (dot segments, query/fragment-only refs, protocol-relative
    refs), base handling, or URL setters that don't revalidate/recompose the href."""
    _check(_run_mjs(run, workdir, PROG_URL_RELATIVE), "url_relative")


PROG_SEARCH_PARAMS = r"""
const p = new URLSearchParams("?a=1&b=x+y&a=2&c=%20%zz&&d&=e&f=%E2%82%AC");
L("parsed", p.size, JSON.stringify([...p]));
L("get", p.get("a"), JSON.stringify(p.getAll("a")), p.get("zz"), p.has("d"), JSON.stringify(p.get("d")), p.has("zz"));
L("toString", p.toString());
p.append("g", "a b&c=d/é~*'()!"); p.set("a", "9"); p.delete("b"); L("mutated", p.toString());
p.sort(); L("sorted", p.toString());
const keys = []; p.forEach(function (v, k, self) { keys.push(k + "=" + v + (self === p) + (this === undefined ? "" : this.tag)); }, { tag: "!" }); L("forEach", keys.join(";"));
L("iterators", [...p.keys()].join(), [...p.values()].join("|"), JSON.stringify([...p.entries()][0]));
L("object init", new URLSearchParams({ x: 1, y: [1, 2], z: null }).toString());
L("pairs init", new URLSearchParams([["k", "v"], ["k", 2], ["sp ace", "+"]]).toString());
L("copy init", new URLSearchParams(new URLSearchParams("q=1")).toString(), new URLSearchParams().toString() === "", new URLSearchParams(undefined).size);
try { new URLSearchParams([["only"]]); } catch (e) { L(e.name, e.message); }
try { new URLSearchParams([["a", "b", "c"]]); } catch (e) { L(e.name, e.message); }
const s = new URLSearchParams("k=1&x=a&k=2&k=3"); s.set("k", "new"); L("set dedupes", s.toString()); s.set("fresh", "f"); L("set appends", s.toString());
const u = new URL("http://h/p?x=1&y=2#frag");
const sp = u.searchParams; sp.append("z", "a b"); L("linked", u.href, u.searchParams === sp);
sp.delete("x"); sp.delete("y"); sp.delete("z"); L("emptied", u.href);
u.search = "?m=5"; L("url->params", sp.get("m"), sp.size);
u.href = "http://h/?n=6"; L("href->params", sp.get("n"), sp.has("m"));
sp.sort(); L("sort on url", u.search);
"""


def test_url_search_params(run, workdir):
    """CATCHES: application/x-www-form-urlencoded parsing/serialization differences (+ vs %20, stray %,
    empty names), set() not removing later duplicates, unstable sort, or URL.searchParams not staying in
    sync with the owning URL in both directions."""
    _check(_run_mjs(run, workdir, PROG_SEARCH_PARAMS), "search_params")


PROG_URLPATTERN = r"""
const p = new URLPattern({ pathname: "/books/:id" });
L("components", p.protocol, p.hostname, p.pathname, p.search, p.hash);
L("test", p.test("https://ex.com/books/42"), p.test("https://ex.com/books/42/x"), p.test("https://ex.com/books/"));
const r = p.exec("https://ex.com/books/42?x#h");
L("exec", JSON.stringify(r.pathname), JSON.stringify(r.search), JSON.stringify(r.hostname), JSON.stringify(r.inputs), JSON.stringify(r.protocol));
const p2 = new URLPattern("https://*.example.com/api/:ver(v\\d+)/*");
L("string pattern", JSON.stringify([p2.protocol, p2.hostname, p2.pathname, p2.port, p2.search, p2.hash]));
const r2 = p2.exec("https://api.example.com/api/v2/users/7");
L("groups", JSON.stringify(r2.hostname.groups), JSON.stringify(r2.pathname.groups));
L("regex group", p2.test("https://api.example.com/api/vx/users"), p2.test("http://api.example.com/api/v1/a"));
const p3 = new URLPattern({ pathname: "/files{/:name}?" });
L("optional group", p3.test({ pathname: "/files" }), p3.test({ pathname: "/files/a" }), JSON.stringify(p3.exec({ pathname: "/files/b" }).pathname));
const p3b = new URLPattern({ pathname: "/x{-:n}+" });
L("repeat group", p3b.test({ pathname: "/x-1-2" }), p3b.test({ pathname: "/x" }));
const p4 = new URLPattern("/users/:uid/posts/:pid", "https://site.org");
L("baseURL", JSON.stringify([p4.protocol, p4.hostname, p4.pathname]), JSON.stringify(p4.exec("https://site.org/users/u1/posts/p9").pathname.groups));
L("host mismatch", p4.test("https://other.org/users/1/posts/2"), p4.test("/users/1/posts/2", "https://site.org"));
const p5 = new URLPattern({ pathname: "/(\\d+)/:rest*" });
L("anonymous groups", JSON.stringify(p5.exec({ pathname: "/12/a" })?.pathname.groups));
const p6 = new URLPattern({ hostname: ":sub.example.com", search: "q=:term" });
const r6 = p6.exec("http://www.example.com/?q=cats");
L("hostname/search groups", JSON.stringify(r6.hostname.groups), JSON.stringify(r6.search.groups));
L("wildcard all", new URLPattern().test("http://anything/"), new URLPattern({}).pathname, p.exec("not a url"), p.test("not a url"));
const p7 = new URLPattern("http://u:pw@h.com:8080/x?q=1#frag");
L("full string", JSON.stringify([p7.username, p7.password, p7.hostname, p7.port, p7.pathname, p7.search, p7.hash]));
L("full match", p7.test("http://u:pw@h.com:8080/x?q=1#frag"), p7.test("http://u:pw@h.com:8081/x?q=1#frag"));
const p8 = new URLPattern({ pathname: "/a.b+c" }); L("literal escaping", p8.test({ pathname: "/a.b+c" }), p8.test({ pathname: "/axbbc" }));
const p9 = new URLPattern({ protocol: "http{s}?", pathname: "/*" }); L("protocol group", p9.test("http://h/x"), p9.test("https://h/x"), p9.test("ftp://h/x"));
const p10 = new URLPattern({ pathname: "/:a/:b" }); L("object exec inputs", JSON.stringify(p10.exec({ pathname: "/1/2", hostname: "ignored" }).pathname.groups));
"""


def test_url_pattern(run, workdir):
    """CATCHES: URLPattern compilers that mis-handle named/regex/wildcard groups, {...} groups with ? + *
    modifiers, baseURL resolution, component defaults ("*"), literal escaping, or exec() result shape."""
    _check(_run_mjs(run, workdir, PROG_URLPATTERN), "urlpattern")


# ---------------------------------------------------------------------------------------------
# crypto
# ---------------------------------------------------------------------------------------------

PROG_CRYPTO = r"""
const hex = (b) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
const enc = (s) => new TextEncoder().encode(s);
L("abc", hex(await crypto.subtle.digest("SHA-256", enc("abc"))));
L("empty", hex(await crypto.subtle.digest({ name: "sha-256" }, new ArrayBuffer(0))));
for (const n of [55, 56, 63, 64, 65, 119, 120, 1000]) L("len" + n, hex(await crypto.subtle.digest("SHA-256", enc("a".repeat(n)))));
L("subarray", hex(await crypto.subtle.digest("SHA-256", new Uint8Array([0, 0, 97, 98, 99, 0]).subarray(2, 5))));
L("dataview", hex(await crypto.subtle.digest("SHA-256", new DataView(enc("xabcx").buffer, 1, 3))));
L("uint32 view", hex(await crypto.subtle.digest("SHA-256", new Uint32Array([0x64636261]))));
const out = await crypto.subtle.digest("SHA-256", enc("x"));
L("result type", Object.prototype.toString.call(out), out.byteLength);
for (const alg of ["SHA-1", "SHA-384", "SHA-512", "MD5", "", { name: "SHA-512" }, {}]) {
  try { L(JSON.stringify(alg), hex(await crypto.subtle.digest(alg, new Uint8Array(0)))); } catch (e) { L(JSON.stringify(alg), e.name, e.message, e instanceof DOMException); }
}
for (const data of ["str", [1, 2], null]) {
  try { await crypto.subtle.digest("SHA-256", data); } catch (e) { L("bad data", e.name, e.message); }
}
const p = crypto.subtle.digest("SHA-1", new Uint8Array(0)); L("rejects asynchronously", p instanceof Promise); await p.catch(() => {});
const u8 = crypto.getRandomValues(new Uint8Array(16)); L("u8", u8.length, u8 instanceof Uint8Array);
const u32 = new Uint32Array(4); L("same object", crypto.getRandomValues(u32) === u32);
for (const T of [Int8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, BigInt64Array, BigUint64Array]) L(T.name, crypto.getRandomValues(new T(2)).length);
L("quota boundary", crypto.getRandomValues(new Uint8Array(65536)).length, crypto.getRandomValues(new Uint32Array(16384)).length, crypto.getRandomValues(new Uint8Array(0)).length);
for (const bad of [new Float32Array(2), new Float64Array(1), [1, 2], new DataView(new ArrayBuffer(4)), null, new ArrayBuffer(4)]) {
  try { crypto.getRandomValues(bad); L("ok?"); } catch (e) { L("getRandomValues", e.name, e.message); }
}
for (const big of [new Uint8Array(65537), new Uint32Array(16385)]) {
  try { crypto.getRandomValues(big); } catch (e) { L("quota", e.name, e.message, e instanceof DOMException); }
}
const big = new Uint8Array(4096); crypto.getRandomValues(big); L("filled", big.some((b) => b !== 0));
const sub = new Uint8Array(8); crypto.getRandomValues(sub.subarray(2, 4)); L("subarray only", sub[0], sub[1], sub[4], sub[7]);
const uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ids = Array.from({ length: 20 }, () => crypto.randomUUID());
L("uuid", typeof ids[0], ids[0].length, ids.every((id) => uuidRe.test(id)), new Set(ids).size);
L("classes", crypto instanceof Crypto, crypto.subtle instanceof SubtleCrypto, crypto.subtle === crypto.subtle, typeof CryptoKey, typeof crypto.subtle.digest);
"""


def test_crypto_digest_random_and_uuid(run, workdir):
    """CATCHES: SHA-256 padding/multi-block bugs, digest ignoring view offsets, unsupported algorithms not
    rejecting with NotSupportedError, getRandomValues accepting float arrays or ignoring the 65536-byte
    quota, or randomUUID not producing RFC 4122 v4 strings."""
    _check(_run_mjs(run, workdir, PROG_CRYPTO), "crypto")


# ---------------------------------------------------------------------------------------------
# Blob / File / FormData
# ---------------------------------------------------------------------------------------------

PROG_BLOB = r"""
const b = new Blob(["héllo ", new Uint8Array([65, 66]), new Blob(["<b>"]), new Uint16Array([0x4443]).buffer, 42, new Uint8Array([1, 2, 69, 70]).subarray(2)], { type: "Text/Plain" });
L("blob", b.size, b.type, await b.text(), Object.prototype.toString.call(b), String(b), b instanceof Blob);
L("slice", await b.slice(1, 3).text(), JSON.stringify(await b.slice(-4).text()), b.slice(2, 1).size, b.slice(0, 100, "x/y").type, b.slice().size, b.slice(-100, 2).size, b.slice("2", "4").size);
L("arrayBuffer", new Uint8Array(await b.slice(0, 2).arrayBuffer()).join(), (await b.bytes()).constructor.name, (await b.arrayBuffer()).byteLength);
L("empty", new Blob().size, JSON.stringify(new Blob([], { type: "badé" }).type), new Blob(undefined).size, new Blob(null).size, JSON.stringify(new Blob([]).type));
for (const bad of ["str", {}, 5]) { try { new Blob(bad); L("ok?"); } catch (e) { L(e.name, e.message); } }
const chunks = []; for await (const c of b.stream()) chunks.push(c.constructor.name + ":" + c.length); L("stream", chunks.join());
let emptyChunks = 0; for await (const c of new Blob([]).stream()) emptyChunks++; L("empty stream chunks", emptyChunks);
const src = new Uint8Array([1, 2, 3]); const copied = new Blob([src]); src[0] = 99; L("parts copied", (await copied.bytes()).join());
const f = new File(["abc"], "a.txt", { type: "text/plain", lastModified: 1234 });
L("file", f.name, f.size, f.type, f.lastModified, f instanceof Blob, f instanceof File, Object.prototype.toString.call(f), await f.text());
L("file defaults", typeof new File([], "x").lastModified, new File([], 123).name, new File([], "n", { lastModified: "77" }).lastModified);
try { new File(["x"]); } catch (e) { L(e.name, e.message); }
const sliced = f.slice(1); L("file slice is Blob", sliced instanceof File, sliced instanceof Blob, await sliced.text());
"""


def test_blob_and_file(run, workdir):
    """CATCHES: Blob part concatenation errors (strings, views with offsets, nested Blobs, numbers), type
    lowercasing/validation, slice() clamping with negative indices, stream()/bytes()/arrayBuffer() results,
    or File name/lastModified handling."""
    _check(_run_mjs(run, workdir, PROG_BLOB), "blob")


PROG_FORMDATA = r"""
const f = new File(["abc"], "a.txt", { type: "text/plain", lastModified: 1 });
const fd = new FormData();
fd.append("a", "1"); fd.append("a", 2); fd.append("blob", new Blob(["zz"], { type: "app/x" })); fd.append("file", f, "renamed.txt"); fd.append("orig", f);
L("get", fd.get("a"), JSON.stringify(fd.getAll("a")), fd.has("blob"), fd.get("blob").name, fd.get("blob").type, fd.get("blob") instanceof File, fd.get("file").name, fd.get("orig") === f, fd.get("nope"), JSON.stringify(fd.getAll("nope")));
fd.set("a", "only"); L("set", JSON.stringify([...fd.keys()]), fd.get("a"));
fd.set("new", "n"); fd.delete("blob"); fd.delete("missing"); L("set/delete", JSON.stringify([...fd.keys()]));
const vals = []; fd.forEach((v, k, self) => vals.push(k + ":" + (typeof v === "string" ? v : "File(" + v.name + ")") + (self === fd))); L("forEach", vals.join(" "), Object.prototype.toString.call(fd));
L("iterators", JSON.stringify([...fd.values()].map((v) => typeof v)), JSON.stringify([...fd].map(([k]) => k)), JSON.stringify([...fd.entries()][0]));
try { fd.append("x", "y", "fname"); } catch (e) { L(e.name, e.message); }
fd.set("blob2", new Blob(["q"]), "named.bin"); L("set with filename", fd.get("blob2").name, fd.get("blob2").type === "");
const req = new Request("http://x/", { method: "POST", body: fd });
const ct = req.headers.get("content-type");
L("content-type", /^multipart\/form-data; boundary=----lumenFormBoundary[0-9a-f]{32}$/.test(ct));
const raw = new TextDecoder().decode(await req.clone().arrayBuffer());
const boundary = ct.split("boundary=")[1];
L("wire", JSON.stringify(raw.split(boundary).join("BOUNDARY")));
const back = await req.formData();
L("roundtrip", JSON.stringify([...back].map(([k, v]) => [k, typeof v === "string" ? v : [v.name, v.type, v.size]])));
const fd2 = new FormData(); fd2.append('q"x', "line1\nline2"); fd2.append("bin", new File([new Uint8Array([0, 13, 10, 45, 45, 255])], 'we"ird.bin'));
const back2 = await new Response(fd2).formData();
L("escaping", JSON.stringify([...back2].map(([k, v]) => [k, typeof v === "string" ? v : v.name])), (await back2.get("bin").bytes()).join());
// A multipart body from another client (quoted boundary, extra headers, preamble).
const body = 'preamble\r\n--XyZ\r\nContent-Disposition: form-data; name="t"\r\nX-Extra: 1\r\n\r\nhello\r\n--XyZ\r\ncontent-disposition: form-data; name="up"; filename="u.txt"\r\nContent-Type: text/markdown\r\n\r\n# md\r\n--XyZ\r\nContent-Disposition: form-data\r\n\r\nno name\r\n--XyZ--\r\n';
const parsed = await new Response(body, { headers: { "content-type": 'multipart/form-data; boundary="XyZ"' } }).formData();
L("external", JSON.stringify([...parsed].map(([k, v]) => [k, typeof v === "string" ? v : [v.name, v.type, v.size]])));
const urlenc = await new Request("http://x/", { method: "POST", body: "a=1&b=two+words&a=3", headers: { "content-type": "application/x-www-form-urlencoded" } }).formData();
L("urlencoded", JSON.stringify([...urlenc]));
for (const ctype of ["text/plain", "multipart/form-data", ""]) {
  try { await new Response("x", { headers: ctype ? { "content-type": ctype } : {} }).formData(); } catch (e) { L("formData error", e.name, e.message); }
}
"""


def test_formdata_and_multipart_bodies(run, workdir):
    """CATCHES: FormData append/set/delete ordering bugs, Blob values not wrapped as File("blob"), wrong
    multipart/form-data serialization (CRLFs, escaping, Content-Type defaults) or parsing (quoted boundaries,
    filenames, binary parts), and formData() accepting unsupported content types."""
    _check(_run_mjs(run, workdir, PROG_FORMDATA), "formdata")


# ---------------------------------------------------------------------------------------------
# Headers / Request / Response
# ---------------------------------------------------------------------------------------------

PROG_HEADERS = r"""
const h = new Headers({ "Content-Type": " text/html ", "X-A": "1" });
h.append("x-a", "2"); h.set("Accept", "*/*"); h.append("Set-Cookie", "a=1"); h.append("set-cookie", "b=2");
L("entries", JSON.stringify([...h]));
L("get", h.get("X-A"), h.has("content-type"), h.has("CONTENT-TYPE"), h.get("missing"), h.get("set-cookie"));
h.delete("X-A"); h.delete("not-there"); L("keys", JSON.stringify([...h.keys()]), JSON.stringify([...h.values()]));
const fe = []; h.forEach(function (v, k, self) { fe.push(`${k}=${v}:${self === h}:${this && this.t}`); }, { t: "ctx" }); L("forEach", fe.join(" "));
L("pairs init", JSON.stringify([...new Headers([["b", "2"], ["a", "1"], ["b", "3"]])]), "copy", JSON.stringify([...new Headers(h)]), "empty", [...new Headers()].length, [...new Headers(null)].length);
h.set("x-num", 42); h.set("x-ws", "\t padded \t"); L("coerce/trim", h.get("x-num"), JSON.stringify(h.get("x-ws")));
for (const bad of ["", "a b", "a:b", "é", 'a"b', "a(b)", "a\nb"]) { try { h.set(bad, "v"); L("ok?"); } catch (e) { L(e.name, e.message); } }
for (const bad of [() => h.get("bad name"), () => h.has("x y"), () => h.delete("(")]) { try { bad(); L("ok?"); } catch (e) { L("lookup", e.name, e.message); } }
try { new Headers([["a"]]); } catch (e) { L(e.name, e.message); }
try { new Headers([["a", "b", "c"]]); } catch (e) { L(e.name, e.message); }
L("iterator protocol", typeof h[Symbol.iterator], typeof h.entries().next);
"""


def test_headers_semantics(run, workdir):
    """CATCHES: Headers that don't lowercase/sort names, don't combine appended values with ", ", don't trim
    values, accept invalid header names, or iterate in insertion order instead of sorted order."""
    _check(_run_mjs(run, workdir, PROG_HEADERS), "headers")


PROG_RESPONSE = r"""
const r = new Response("hello", { status: 201, statusText: "Created", headers: { "X-Y": "z" } });
L("fields", r.status, r.statusText, r.ok, r.headers.get("content-type"), r.headers.get("x-y"), r.bodyUsed, JSON.stringify(r.url), r.redirected, r.body instanceof ReadableStream, r.headers instanceof Headers);
L("text", await r.text(), r.bodyUsed);
try { await r.text(); } catch (e) { L("reuse", e.name, e.message); }
try { r.clone(); } catch (e) { L("clone used", e.name, e.message); }
const j = Response.json({ a: [1, 2] }, { status: 202, headers: { "content-type": "application/vnd+json" } });
L("json", j.status, j.headers.get("content-type"), JSON.stringify(await j.json()));
L("json defaults", Response.json(null).headers.get("content-type"), await Response.json("s").text(), await Response.json(undefined).text());
const er = Response.error(); L("error()", er.status, er.type, er.ok, er.body);
L("redirect static", typeof Response.redirect);
for (const st of [199, 600, 0, "abc"]) { try { new Response(null, { status: st }); L("ok?", st); } catch (e) { L(e.name, e.message); } }
L("status bounds", new Response(null, { status: 200 }).ok, new Response(null, { status: 299 }).ok, new Response(null, { status: 300 }).ok, new Response(null, { status: 599 }).ok, new Response(null, { status: undefined }).status, new Response(null, { status: "204" }).status);
const nr = new Response(); L("empty", nr.status, nr.body, JSON.stringify(await nr.text()), JSON.stringify(nr.statusText), nr.headers.get("content-type"));
const ab = await new Response(new Uint8Array([1, 2, 3])).arrayBuffer(); L("bytes body", Object.prototype.toString.call(ab), ab.byteLength, new Uint8Array(ab).join());
L("buffer body", (await new Response(new Uint16Array([0x0201, 0x0403]).buffer).bytes()).join(), (await new Response(new DataView(new Uint8Array([9, 8, 7]).buffer, 1)).bytes()).join());
const bl = await new Response(new Blob(["xy"], { type: "a/b" })).blob(); L("blob", bl.size, bl.type, await bl.text());
L("blob no type", (await new Response(new Uint8Array([1])).blob()).type === "");
const usp = new Response(new URLSearchParams("a=1&b=2")); L("urlsearchparams", usp.headers.get("content-type"), await usp.clone().text());
L("keeps explicit ct", new Response("x", { headers: { "Content-Type": "text/custom" } }).headers.get("content-type"));
try { await new Response("{bad").json(); } catch (e) { L("bad json", e.name); }
const c1 = new Response("clone me", { status: 203, statusText: "NA", headers: { a: "1" } }); const c2 = c1.clone();
L("clone", await c1.text(), await c2.text(), c2.status, c2.statusText, c2.headers.get("a"), c2.headers !== c1.headers);
const bytes = await new Response("é").bytes(); L("bytes()", bytes.constructor.name, bytes.join());
L("number body", await new Response(123).text(), await new Response(true).text());
"""


def test_response_construction_and_body_mixin(run, workdir):
    """CATCHES: Response defaults (status 200, empty statusText), status range validation, default
    Content-Type for string/URLSearchParams/Blob bodies, single-use body enforcement, clone(), and
    Response.json/error statics behaving differently from the reference."""
    _check(_run_mjs(run, workdir, PROG_RESPONSE), "response")


PROG_REQUEST = r"""
const q = new Request("http://example.com/a/../b?x", { method: "post", body: "data", headers: { "X-Q": "1" } });
L("fields", q.url, q.method, q.headers.get("content-type"), q.headers.get("x-q"), q.signal, q.bodyUsed);
L("clone/text", await q.clone().text(), await q.text(), q.bodyUsed);
for (const [m, init] of [["GET", { body: "x" }], ["HEAD", { method: "HEAD", body: "x" }], ["get", { method: "get", body: new Uint8Array(1) }]]) {
  try { new Request("http://e/", init); L("ok?"); } catch (e) { L(m, e.name, e.message); }
}
try { new Request("relative"); } catch (e) { L(e.name, e.message); }
const d = new Request("http://e"); L("defaults", d.url, d.method, d.body, d.signal, [...d.headers].length);
L("null body allowed on GET", new Request("http://e/", { body: null }).method);
const q2 = new Request(q, { method: "PUT" }); L("from request", q2.method, q2.url, q2.headers.get("x-q"));
const q3 = new Request(new Request("http://e/", { method: "POST", body: "inherit" })); L("inherits body", q3.method, await q3.text());
const q4 = new Request(new Request("http://e/", { method: "POST", body: "old", headers: { a: "1" } }), { body: "replaced", headers: { b: "2" } });
L("override", await q4.text(), q4.headers.get("a"), q4.headers.get("b"));
const ac = new AbortController(); const q5 = new Request("http://e/", { signal: ac.signal }); L("signal", q5.signal === ac.signal, new Request(q5).signal === ac.signal);
const methods = ["delete", "Options", "PATCH", "custom"].map((m) => new Request("http://e/", { method: m }).method); L("methods", methods.join(","));
const j = new Request("http://e/", { method: "POST", body: JSON.stringify({ k: [1] }) }); L("json", JSON.stringify(await j.json()));
const blobReq = new Request("http://e/", { method: "POST", body: new Blob(["b"], { type: "x/y" }) }); L("blob ct", blobReq.headers.get("content-type"), (await blobReq.blob()).type);
L("url object", new Request(new URL("http://u.rl/p?q")).url);
"""


def test_request_construction(run, workdir):
    """CATCHES: Request URL normalization, method uppercasing, GET/HEAD-with-body TypeError, inheriting
    url/method/headers/body/signal from another Request, or init overrides applied incorrectly."""
    _check(_run_mjs(run, workdir, PROG_REQUEST), "request")


PROG_BODY_STREAMS = r"""
const mk = (chunks) => new ReadableStream({ start(c) { for (const x of chunks) c.enqueue(x); c.close(); } });
const r1 = new Response(mk(["ab", new Uint8Array([99, 100]), new Uint16Array([0x6665]).buffer]));
L("stream body", r1.body instanceof ReadableStream, r1.bodyUsed, await r1.text(), r1.bodyUsed);
const r2 = new Response("streamed");
const reader = r2.body.getReader();
const c1 = await reader.read();
L("read body", c1.value.constructor.name, new TextDecoder().decode(c1.value), JSON.stringify(await reader.read()), r2.bodyUsed);
try { await r2.text(); } catch (e) { L("after stream read:", e.name, e.message); }
const r3 = new Response("x"); L("same stream", r3.body === r3.body);
await r3.text(); try { await r3.body.getReader().read(); } catch (e) { L("stream after text:", e.name, e.message); }
const asyncSrc = new ReadableStream({ start(c) { setTimeout(() => { c.enqueue("late"); c.close(); }, 1); } });
try { await new Response(asyncSrc).text(); } catch (e) { L("async body:", e.name, e.message); }
const locked = mk(["a"]); locked.getReader();
try { await new Response(locked).text(); } catch (e) { L("locked body:", e.name, e.message); }
try { await new Response(mk([{ not: "bytes" }])).text(); } catch (e) { L("bad chunk:", e.name, e.message); }
const r7 = new Response(mk(["clone-", "me"])); const r7c = r7.clone(); L("clone stream", await r7.text(), await r7c.text());
const q = new Request("http://h/", { method: "POST", body: mk(["req ", "stream"]) });
L("request stream", q.body instanceof ReadableStream, await q.clone().text(), await q.text());
const probe = new Request("http://h/", { method: "POST", body: new ReadableStream(), duplex: "half" });
L("unsent probe ok", probe.headers.has("content-type"));
L("null vs empty", new Response(null).body, new Response("").body instanceof ReadableStream, JSON.stringify(await new Response("").text()));
const er = new Response(new ReadableStream({ start(c) { c.error(new Error("src err")); } }));
try { await er.arrayBuffer(); } catch (e) { L("errored body:", e.message); }
const pulled = new Response(new ReadableStream({ n: 0, pull(c) { this.n++ < 3 ? c.enqueue("p" + this.n) : c.close(); } }));
L("pull source", await pulled.text());
const forIter = []; for await (const chunk of new Response("iterate me").body) forIter.push(chunk.length); L("async iterate body", forIter.join());
"""


def test_body_readable_stream_interop(run, workdir):
    """CATCHES: Request/Response bodies built from ReadableStreams not drained correctly (mixed chunk
    types, pull sources), body streams not sharing the consumed flag with text()/json(), or missing errors
    for locked, asynchronous, errored or non-binary stream bodies."""
    _check(_run_mjs(run, workdir, PROG_BODY_STREAMS), "body_streams")


# ---------------------------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------------------------

PROG_READABLE = r"""
let i = 0;
const rs = new ReadableStream({ pull(c) { i++; if (i <= 3) c.enqueue("c" + i); else c.close(); }, cancel(r) { L("cancel", r); } });
L("locked", rs.locked);
const rd = rs.getReader(); L("locked after getReader", rs.locked, rd instanceof ReadableStreamDefaultReader);
try { rs.getReader(); } catch (e) { L(e.name, e.message); }
L("reads", JSON.stringify(await rd.read()), JSON.stringify(await rd.read()), JSON.stringify(await rd.read()), JSON.stringify(await rd.read()), JSON.stringify(await rd.read()));
await rd.closed; L("closed resolved");
rd.releaseLock(); L("released", rs.locked); rd.releaseLock();
try { await rd.read(); } catch (e) { L(e.name, e.message); }
try { await rd.cancel(); } catch (e) { L(e.name, e.message); }
try { new ReadableStreamDefaultReader({}); } catch (e) { L(e.name, e.message); }
const er = new ReadableStream({ start(c) { c.enqueue(1); c.error(new Error("boom")); } });
try { for await (const v of er) L("v", v); } catch (e) { L("iter err", e.message); }
const er2 = new ReadableStream({ start(c) { c.enqueue(1); c.enqueue(2); c.error(new Error("boom2")); c.error(new Error("ignored")); } });
const r2 = er2.getReader(); try { await r2.read(); } catch (e) { L("read err", e.message); }
await r2.closed.catch((e) => L("closed rejected", e.message));
new ReadableStream({ start(c) { L("desiredSize", c.desiredSize); c.close(); L("after close", c.desiredSize); c.close(); try { c.enqueue(1); } catch (e) { L(e.name, e.message); } } });
new ReadableStream({ start(c) { c.error("e"); L("after error", c.desiredSize); } });
const cs = new ReadableStream({ start(c) { c.enqueue("x"); }, cancel(reason) { L("source cancel", reason); } });
L("cancel result", await cs.cancel("why"));
L("read after cancel", JSON.stringify(await cs.getReader().read()));
const ls = new ReadableStream(); ls.getReader(); try { await ls.cancel(); } catch (e) { L(e.name, e.message); }
const tc = new ReadableStream({ cancel() { throw new Error("cancel threw"); } }); try { await tc.cancel(); } catch (e) { L("cancel rejects", e.message); }
const later = new ReadableStream({ start(c) { setTimeout(() => { c.enqueue("late"); c.close(); }, 5); } });
const lr = later.getReader(); L("pending then resolved", JSON.stringify(await lr.read()), JSON.stringify(await lr.read()));
const pend = new ReadableStream(); const pr = pend.getReader(); const p = pr.read(); try { pr.releaseLock(); } catch (e) { L(e.name, e.message); }
const bs = new ReadableStream({ start(c) { c.enqueue("a"); c.enqueue("b"); }, cancel() { L("cancelled by break"); } });
for await (const v of bs) { L("got", v); break; }
L("unlocked after break", bs.locked);
const ps = new ReadableStream({ start(c) { c.enqueue("a"); c.enqueue("b"); c.close(); } });
for await (const v of ps.values({ preventCancel: true })) { L("preventCancel", v); break; }
L("preventCancel keeps data", ps.locked, JSON.stringify(await ps.getReader().read()));
const t = new ReadableStream({ start(c) { c.enqueue("t1"); c.enqueue({ o: 1 }); c.close(); } });
const [a, b] = t.tee();
const ra = []; for await (const v of a) ra.push(v);
const rb = []; for await (const v of b) rb.push(v);
L("tee", ra.length, rb.length, ra[0], rb[0], ra[1] === rb[1], t.locked);
const plain = new ReadableStream(null); L("null source", plain.locked, typeof plain.getReader);
const ctrlName = []; new ReadableStream({ start(c) { ctrlName.push(c instanceof ReadableStreamDefaultController); } }); L("controller class", ctrlName[0]);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_readable_stream_default_reader(run, workdir, tier):
    """CATCHES: ReadableStream bugs in pull scheduling, reader locking/release, closed promise, error
    propagation (queued chunks discarded), cancel() semantics, async iteration with break/preventCancel,
    or tee() not delivering every chunk to both branches."""
    _check(_run_mjs(run, workdir, PROG_READABLE, tier), "readable")


PROG_BYTE_STREAMS = r"""
const bs = new ReadableStream({ type: "bytes", start(c) { c.enqueue(new Uint8Array([1, 2, 3, 4, 5])); c.enqueue(new Uint16Array([0x0706])); c.close(); } });
const br = bs.getReader({ mode: "byob" });
L("reader class", br instanceof ReadableStreamBYOBReader, bs.locked);
let r = await br.read(new Uint8Array(3)); L("read1", r.done, r.value.join(), r.value.byteLength, r.value.constructor.name);
r = await br.read(new Uint8Array(10)); L("read2", r.done, r.value.join());
r = await br.read(new Uint16Array(2)); L("read3", r.done, r.value.length, r.value.constructor.name);
await br.closed; L("byob closed resolved");
try { new ReadableStream().getReader({ mode: "byob" }); } catch (e) { L(e.name, e.message); }
try { new ReadableStreamBYOBReader(new ReadableStream()); } catch (e) { L(e.name, e.message); }
try { await br.read([1]); } catch (e) { L(e.name, e.message); }
new ReadableStream({ type: "bytes", start(c) { try { c.enqueue("str"); } catch (e) { L(e.name, e.message); } L("byte desiredSize", c.desiredSize, c.byobRequest); c.close(); L("closed desiredSize", c.desiredSize); try { c.enqueue(new Uint8Array(1)); } catch (e) { L(e.name, e.message); } } });
let n = 0;
const pullS = new ReadableStream({ type: "bytes", pull(c) { const req = c.byobRequest; if (n++ < 2 && req) { req.view[0] = 9 + n; req.view[1] = 20 + n; req.respond(2); } else c.close(); } });
const pr = pullS.getReader({ mode: "byob" });
L("byobRequest pulls", (await pr.read(new Uint8Array(8))).value.join(), (await pr.read(new Uint8Array(8))).value.join(), (await pr.read(new Uint8Array(8))).done);
const nv = new ReadableStream({ type: "bytes", pull(c) { if (c.byobRequest) c.byobRequest.respondWithNewView(new Uint8Array([7, 7, 7])); } });
const nvr = nv.getReader({ mode: "byob" });
L("respondWithNewView splits", (await nvr.read(new Uint8Array(2))).value.join(), (await nvr.read(new Uint8Array(2))).value.join());
const dbs = new ReadableStream({ type: "bytes", start(c) { const src = new Uint8Array([5, 6]); c.enqueue(src); src[0] = 0; c.close(); } });
const dr = await dbs.getReader().read(); L("default reader on bytes", dr.value.constructor.name, dr.value.join());
const ebs = new ReadableStream({ type: "bytes", start(c) { c.error(new TypeError("byte err")); } });
const ebr = ebs.getReader({ mode: "byob" });
try { await ebr.read(new Uint8Array(1)); } catch (e) { L("errored byob", e.name, e.message); }
await ebr.closed.catch((e) => L("byob closed rejects", e.message));
const later = new ReadableStream({ type: "bytes", start(c) { setTimeout(() => { c.enqueue(new Uint8Array([1, 2, 3])); c.close(); }, 2); } });
const lr = later.getReader({ mode: "byob" });
const lv = await lr.read(new Uint8Array(2)); L("pending byob read", lv.value.join(), (await lr.read(new Uint8Array(2))).value.join(), (await lr.read(new Uint8Array(2))).done);
const rel = new ReadableStream({ type: "bytes" }); const relr = rel.getReader({ mode: "byob" }); relr.releaseLock(); L("byob release", rel.locked);
try { await relr.read(new Uint8Array(1)); } catch (e) { L(e.name, e.message); }
const cbs = new ReadableStream({ type: "bytes", cancel(r) { L("byte source cancel", r); } }); await cbs.getReader({ mode: "byob" }).cancel("stop"); L("after byob cancel", cbs.locked);
"""


def test_byte_streams_and_byob_reader(run, workdir):
    """CATCHES: byte streams that don't copy enqueued views, BYOB reads that don't fill the caller's view
    (or don't split partial chunks), missing byobRequest respond/respondWithNewView support, or wrong
    errors for BYOB readers on non-byte streams."""
    _check(_run_mjs(run, workdir, PROG_BYTE_STREAMS), "byte_streams")


PROG_WRITABLE = r"""
const written = [];
const ws = new WritableStream({ start(c) { written.push("start:" + Object.prototype.toString.call(c)); }, write(ch) { written.push("w:" + ch); }, close() { written.push("close"); }, abort(r) { written.push("abort:" + r); } }, { highWaterMark: 3 });
const w = ws.getWriter();
L("writer", ws.locked, w.desiredSize, w instanceof WritableStreamDefaultWriter, Object.prototype.toString.call(ws));
w.write("a"); w.write("b");
L("queued desiredSize", w.desiredSize);
await w.ready; await w.close(); await w.closed;
L("sink calls", written.join(" "), "desiredSize after close", w.desiredSize);
try { ws.getWriter(); } catch (e) { L(e.name, e.message); }
w.releaseLock(); L("released", ws.locked); w.releaseLock();
try { w.desiredSize; } catch (e) { L(e.name, e.message); }
L("write after release", await w.write("x").catch((e) => e.message), await w.close().catch((e) => e.message), await w.abort().catch((e) => e.message));
const ws2 = new WritableStream({ write(c) { if (c === "bad") throw new Error("sink fail"); } });
const w2 = ws2.getWriter();
await w2.write("ok");
L("failing write", await w2.write("bad").catch((e) => "rej:" + e.message), w2.desiredSize);
L("subsequent write", await w2.write("after").catch((e) => "rej2:" + e.message));
L("closed rejects", await w2.closed.catch((e) => "closed:" + e.message));
L("close errored", await w2.close().catch((e) => "close:" + e.message));
const ws3 = new WritableStream({ abort(r) { L("sink abort", r); } });
await ws3.abort("stop"); L("aborted, abort again resolves", await ws3.abort("again"));
L("getWriter on errored", await ws3.getWriter().ready.catch((e) => "ready rejects:" + e));
const ws4 = new WritableStream({ start(c) { L("controller signal", typeof c.signal, c.signal.aborted); } });
await ws4.close(); L("stream.close()", ws4.locked);
const ws5 = new WritableStream(); ws5.getWriter(); try { await ws5.close(); } catch (e) { L(e.name, e.message); }
const order = [];
const slow = new WritableStream({ write(c) { return new Promise((res) => setTimeout(() => { order.push(c); res(); }, 3 - c)); } });
const sw = slow.getWriter(); sw.write(1); sw.write(2); await sw.write(3); L("sequential writes", order.join());
let ctrl; const ews = new WritableStream({ start(c) { ctrl = c; } }); const ew = ews.getWriter(); ctrl.error(new RangeError("ctrl error"));
L("controller.error", await ew.write("x").catch((e) => e.name + ":" + e.message), await ew.closed.catch((e) => e.message));
const st = new WritableStream({ start() { throw new Error("start threw"); } }); L("start throws", await st.getWriter().write(1).catch((e) => e.message));
const ast = new WritableStream({ start() { return Promise.reject(new Error("async start")); } }); await new Promise((r) => setTimeout(r, 1)); L("async start rejects", await ast.getWriter().write(1).catch((e) => e.message));
const sig = new WritableStream({ start(c) { c.signal.addEventListener("abort", () => L("controller signal aborted", c.signal.reason)); } }); await sig.abort("reason!");
"""


def test_writable_stream_writer_lifecycle(run, workdir):
    """CATCHES: WritableStream sinks called out of order or concurrently, desiredSize/highWaterMark
    accounting, errors from write()/controller.error()/start() not erroring the stream, abort() not
    reaching the sink or controller signal, or writer release semantics."""
    _check(_run_mjs(run, workdir, PROG_WRITABLE), "writable")


PROG_TRANSFORM = r"""
const src = () => new ReadableStream({ start(c) { for (const s of ["al", "pha", " be", "ta"]) c.enqueue(s); c.close(); } });
const up = new TransformStream({
  start(c) { L("ts start", Object.prototype.toString.call(c), c.desiredSize); },
  transform(chunk, c) { c.enqueue(chunk.toUpperCase()); if (chunk === "pha") c.enqueue("|"); },
  flush(c) { c.enqueue("!"); L("flushed"); },
});
L("class", Object.prototype.toString.call(up), up.readable instanceof ReadableStream, up.writable instanceof WritableStream);
let out = ""; for await (const ch of src().pipeThrough(up)) out += ch; L("pipeThrough", out);
const id = new TransformStream(); const iw = id.writable.getWriter(); iw.write(1); iw.write(2); iw.close();
const got = []; for await (const v of id.readable) got.push(v); L("identity", got.join());
const asyncT = new TransformStream({ async transform(ch, c) { await new Promise((r) => setTimeout(r, 1)); c.enqueue(ch * 10); } });
const aw = asyncT.writable.getWriter(); aw.write(1); aw.write(2); aw.close();
const ag = []; for await (const v of asyncT.readable) ag.push(v); L("async transform", ag.join());
const sink = []; await src().pipeTo(new WritableStream({ write(c) { sink.push(c); }, close() { sink.push("CLOSED"); } })); L("pipeTo", sink.join("/"));
const sink2 = []; const ws2 = new WritableStream({ write(c) { sink2.push(c); }, close() { sink2.push("CLOSED"); } });
await src().pipeTo(ws2, { preventClose: true }); L("preventClose", sink2.join("/"), ws2.locked);
const errSrc = new ReadableStream({ pull(c) { c.error(new Error("src broke")); } });
const ws3 = new WritableStream({ abort(r) { L("dest aborted:", r.message); } });
try { await errSrc.pipeTo(ws3); } catch (e) { L("pipeTo rejected", e.message); }
const ws4 = new WritableStream({ abort() { L("never aborted"); } });
try { await new ReadableStream({ pull(c) { c.error(new Error("e2")); } }).pipeTo(ws4, { preventAbort: true }); } catch (e) { L("preventAbort", e.message); }
const badSink = new WritableStream({ write() { throw new Error("sink broke"); } });
try { await src().pipeTo(badSink); } catch (e) { L("sink error", e.message); }
try { src().pipeThrough({}); } catch (e) { L(e.name, e.message); }
const term = new TransformStream({ transform(ch, c) { c.enqueue(ch); c.terminate(); } });
const tw = term.writable.getWriter(); await tw.write("only");
const tr = term.readable.getReader();
L("terminate", JSON.stringify(await tr.read()), JSON.stringify(await tr.read()));
L("write after terminate", await tw.write("more").catch((e) => e.name + ": " + e.message));
const te = new TransformStream({ transform(ch, c) { c.error(new RangeError("tx err")); } });
te.writable.getWriter().write("x").catch(() => {});
try { await te.readable.getReader().read(); } catch (e) { L("readable errored", e.name, e.message); }
const fl = new TransformStream({ flush() { return new Promise((r) => setTimeout(r, 1)); } });
const flw = fl.writable.getWriter(); flw.write("z"); await flw.close(); L("async flush done", JSON.stringify(await fl.readable.getReader().read()));
const ab = new TransformStream(); const abw = ab.writable.getWriter(); await abw.abort(new Error("aborted!"));
try { await ab.readable.getReader().read(); } catch (e) { L("abort errors readable", e.message); }
const chain = src().pipeThrough(new TransformStream({ transform(c, k) { k.enqueue(c.length); } })).pipeThrough(new TransformStream({ transform(c, k) { k.enqueue(c * 2); } }));
const cg = []; for await (const v of chain) cg.push(v); L("chained", cg.join());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_transform_stream_pipe_to_and_pipe_through(run, workdir, tier):
    """CATCHES: TransformStream transform/flush/terminate/error handling, identity transforms, async
    transforms reordering chunks, pipeTo not closing/aborting the destination (or ignoring preventClose/
    preventAbort), or pipeThrough chains losing data."""
    _check(_run_mjs(run, workdir, PROG_TRANSFORM, tier), "transform")


PROG_TEXT_STREAMS = r"""
const src = (chunks) => new ReadableStream({ start(c) { for (const s of chunks) c.enqueue(s); c.close(); } });
const enc = new TextEncoderStream(); L("encoder", enc.encoding, enc.readable instanceof ReadableStream, enc.writable instanceof WritableStream);
const bytes = []; for await (const b of src(["al", "", "pha€", 42]).pipeThrough(enc)) bytes.push(b.constructor.name + ":" + Array.from(b).join(".")); L("encoded", bytes.join(" "));
const dec = new TextDecoderStream(); L("decoder", dec.encoding);
let txt = ""; for await (const t of src([new Uint8Array([0x68, 0x69, 0x20]), new Uint8Array([0xc3, 0xa9]), new Uint8Array([])]).pipeThrough(dec)) txt += "[" + t + "]"; L("decoded", txt);
let txt2 = ""; for await (const t of src([new Uint8Array([0xe2, 0x82]), new Uint8Array([0xac])]).pipeThrough(new TextDecoderStream())) txt2 += "[" + t + "]"; L("split multibyte", JSON.stringify(txt2));
let txt3 = ""; for await (const t of src([new Uint8Array([0xef, 0xbb, 0xbf, 0x41]), new Uint8Array([0xef, 0xbb, 0xbf, 0x42])]).pipeThrough(new TextDecoderStream("utf8", { ignoreBOM: false }))) txt3 += "[" + t.length + "]"; L("bom per chunk", txt3);
try { new TextDecoderStream("latin1"); } catch (e) { L(e.name, e.message); }
const round = src(["héllo ", "wörld"]).pipeThrough(new TextEncoderStream()).pipeThrough(new TextDecoderStream());
let rt = ""; for await (const t of round) rt += t; L("roundtrip", rt);
const bl = new ByteLengthQueuingStrategy({ highWaterMark: 16 }); L("ByteLength", bl.highWaterMark, bl.size(new Uint8Array(5)), Object.prototype.toString.call(bl));
const cq = new CountQueuingStrategy({ highWaterMark: 2 }); L("Count", cq.highWaterMark, cq.size("anything"), Object.prototype.toString.call(cq));
const hw = new WritableStream({}, new CountQueuingStrategy({ highWaterMark: 4 })); L("strategy hwm", hw.getWriter().desiredSize);
// A fatal decode error inside the transform errors only the writable side: the readable never settles,
// so the pending for-await is abandoned and the program simply ends once the event loop is empty.
const fatal = new TextDecoderStream("utf-8", { fatal: true });
L("fatal stream start");
try { for await (const t of src([new Uint8Array([0x41]), new Uint8Array([0xff])]).pipeThrough(fatal)) L("chunk", t); L("loop ended"); } catch (e) { L("fatal stream", e.name, e.message); }
L("not reached");
"""


def test_text_encoder_decoder_streams_and_strategies(run, workdir):
    """CATCHES: TextEncoderStream/TextDecoderStream missing or emitting wrong chunks (empty chunks, numbers,
    multi-byte sequences split across chunks), queuing strategy classes with wrong highWaterMark/size, or a
    fatal decode error that settles the readable side (the reference leaves it pending and exits 0)."""
    _check(_run_mjs(run, workdir, PROG_TEXT_STREAMS), "text_streams")


# ---------------------------------------------------------------------------------------------
# Messaging + event subclasses
# ---------------------------------------------------------------------------------------------

PROG_EVENT_CLASSES = r"""
const me = new MessageEvent("message", { data: { x: 1 }, origin: "o", lastEventId: 7, ports: [], cancelable: true });
L("MessageEvent", me.type, JSON.stringify(me.data), me.origin, me.lastEventId, me.source, Array.isArray(me.ports), Object.isFrozen(me.ports), me instanceof Event, me.cancelable);
const dme = new MessageEvent("m"); L("defaults", dme.data, JSON.stringify(dme.origin), JSON.stringify(dme.lastEventId), dme.ports.length, dme.source);
const ce = new CloseEvent("close", { code: 70000, reason: "bye", wasClean: 1 });
L("CloseEvent", ce.code, ce.reason, ce.wasClean, new CloseEvent("c").code, new CloseEvent("c", { code: "x" }).code, JSON.stringify(new CloseEvent("c").reason), new CloseEvent("c", { code: 1000.9 }).code);
const ee = new ErrorEvent("error", { message: "m", filename: "f.js", lineno: -1, colno: "5", error: 42 });
L("ErrorEvent", ee.message, ee.filename, ee.lineno, ee.colno, ee.error, new ErrorEvent("e").error, JSON.stringify(new ErrorEvent("e").message), new ErrorEvent("e", { lineno: "x" }).lineno);
for (const init of [undefined, {}, null, "str"]) { try { new PromiseRejectionEvent("unhandledrejection", init); L("ok?"); } catch (e) { L(e.name, e.message); } }
const p = Promise.resolve(); const pre = new PromiseRejectionEvent("x", { promise: p, reason: "r" }); L("PromiseRejectionEvent", pre.promise === p, pre.reason, new PromiseRejectionEvent("x", { promise: p }).reason);
L("inheritance", [MessageEvent, CloseEvent, ErrorEvent, PromiseRejectionEvent].map((C) => C.prototype instanceof Event).join());
"""


def test_event_subclasses(run, workdir):
    """CATCHES: MessageEvent/CloseEvent/ErrorEvent/PromiseRejectionEvent with wrong defaults, missing
    coercions (code & 0xffff, lineno >>> 0), unfrozen ports, or PromiseRejectionEvent not requiring a promise."""
    _check(_run_mjs(run, workdir, PROG_EVENT_CLASSES), "event_classes")


PROG_MESSAGE_CHANNEL = r"""
try { new MessagePort(); } catch (e) { L(e.name, e.message); }
const { port1, port2 } = new MessageChannel();
L("ports", port1 instanceof MessagePort, port2 instanceof EventTarget, port1.onmessage);
const obj = { n: 1, list: [1, 2], when: new Date(0), m: new Map([["k", 1]]) };
const done = new Promise((resolve) => {
  const seen = [];
  port2.onmessage = (e) => {
    seen.push(e.data);
    L("port2 got", JSON.stringify(e.data), e.data !== obj, e instanceof MessageEvent, e.target === port2, e.type);
    if (seen.length === 1) L("clone types", e.data.when instanceof Date, e.data.m instanceof Map);
    if (e.data === "last") resolve();
  };
});
port1.postMessage(obj);
obj.n = 99; // mutating after postMessage is invisible to the receiver
port1.postMessage({ n: 2 });
port1.postMessage("last");
try { port1.postMessage(() => 1); } catch (e) { L("post function", e.name, e.message); }
await done;
L("onmessage getter", typeof port2.onmessage);
// port1 only delivers after start(); addEventListener alone does not start the port.
const got1 = [];
port1.addEventListener("message", (e) => got1.push(e.data));
port2.postMessage("queued-1"); port2.postMessage("queued-2");
await new Promise((r) => setTimeout(r, 5));
L("before start", got1.length);
port1.start(); port1.start();
await new Promise((r) => setTimeout(r, 5));
L("after start", got1.join(","));
// close(): further messages are dropped in both directions.
port1.close();
port2.postMessage("dropped"); port1.postMessage("dropped too");
await new Promise((r) => setTimeout(r, 5));
L("after close", got1.length);
// onmessage = null removes the handler.
const ch = new MessageChannel(); const hits = [];
ch.port2.onmessage = (e) => hits.push(e.data);
ch.port1.postMessage(1);
await new Promise((r) => setTimeout(r, 5));
ch.port2.onmessage = null; ch.port1.postMessage(2);
await new Promise((r) => setTimeout(r, 5));
L("handler removed", hits.join(","), ch.port2.onmessage);
// A transfer list (array or { transfer }) is accepted; the reference copies rather than detaches.
const tc = new MessageChannel(); const ab = new Uint8Array([1, 2, 3]).buffer; const got = [];
tc.port2.onmessage = (e) => got.push(e.data instanceof ArrayBuffer ? "ab:" + new Uint8Array(e.data).join() : JSON.stringify(e.data));
tc.port2.onmessageerror = () => got.push("messageerror");
tc.port1.postMessage(ab, [ab]); tc.port1.postMessage({ n: 1 }, { transfer: [] });
await new Promise((r) => setTimeout(r, 5));
L("transfer", got.join(" "), "sender buffer length", ab.byteLength, typeof tc.port2.onmessageerror);
tc.port1.close(); tc.port2.close();
"""


def test_message_channel_ports(run, workdir):
    """CATCHES: MessagePort delivery bugs: messages not structured-cloned at post time, onmessage not
    implicitly starting the port, addEventListener without start() delivering early, close() not
    disentangling, or DataCloneError not thrown synchronously from postMessage."""
    _check(_run_mjs(run, workdir, PROG_MESSAGE_CHANNEL), "message_channel")


PROG_BROADCAST = r"""
try { new BroadcastChannel(); } catch (e) { L(e.name, e.message); }
const a = new BroadcastChannel("chan"), b = new BroadcastChannel("chan"), c = new BroadcastChannel(42), d = new BroadcastChannel("chan"), other = new BroadcastChannel("other");
L("names", a.name, c.name, typeof c.name, a instanceof EventTarget);
const log = [];
b.onmessage = (e) => { e.data.touched = "b"; log.push("b:" + JSON.stringify(e.data)); };
d.addEventListener("message", (e) => log.push("d:" + JSON.stringify(e.data) + ":" + (e.target === d)));
other.onmessage = () => log.push("other (wrong channel)");
a.onmessage = (e) => log.push("a:" + JSON.stringify(e.data));
const payload = { v: 1 };
a.postMessage(payload);
payload.v = 2;
await new Promise((r) => setTimeout(r, 5));
L("first", log.join(" | "));
log.length = 0;
d.close();
b.postMessage("from b");
await new Promise((r) => setTimeout(r, 5));
L("after d.close", log.join(" | "), typeof a.onmessage);
try { d.postMessage("x"); } catch (e) { L(e.name, e.message, e instanceof DOMException); }
try { a.postMessage(Symbol("s")); } catch (e) { L(e.name, e.message); }
a.close(); b.close(); c.close(); other.close(); a.close();
L("closed all");
"""


def test_broadcast_channel(run, workdir):
    """CATCHES: BroadcastChannel delivering to the sender, to other channel names, to closed channels, sharing
    one clone between receivers (mutation leaks), or not throwing InvalidStateError when posting on a closed channel."""
    _check(_run_mjs(run, workdir, PROG_BROADCAST), "broadcast")


# ---------------------------------------------------------------------------------------------
# Platform globals
# ---------------------------------------------------------------------------------------------

PROG_PLATFORM = r"""
L("self", self === globalThis, typeof globalThis.window);
L("navigator", typeof navigator, navigator.userAgent, Object.keys(navigator).includes("userAgent"));
L("performance", performance instanceof Performance, typeof performance.now(), typeof performance.timeOrigin, performance.timeOrigin > 1e12, Object.keys(performance.toJSON()).join());
const t0 = performance.now(); let spin = 0; for (let i = 0; i < 1e5; i++) spin += i; const t1 = performance.now();
L("monotonic", t1 >= t0, t0 >= 0, spin > 0);
const m = performance.mark("a", { detail: { x: 1 } });
L("mark", m.name, m.entryType, typeof m.startTime, JSON.stringify(m.detail), m.duration);
performance.mark("b");
const ms = performance.measure("a-b", "a", "b");
L("measure", ms.name, ms.entryType, typeof ms.duration, ms.duration >= 0);
L("entries", performance.getEntriesByType("mark").map((e) => e.name).join(), performance.getEntriesByName("a").length, performance.getEntriesByType("measure").length);
try { performance.measure("x", "nonexistent"); } catch (e) { L(e.name, e.message); }
performance.clearMarks(); L("cleared", performance.getEntriesByType("mark").length);
L("Lumen", typeof Lumen, typeof Lumen.serve, typeof Lumen.upgradeWebSocket, /^\d+\.\d+\.\d+/.test(Lumen.version), Object.getOwnPropertyDescriptor(Lumen, "version").writable);
const names = ["DOMException", "Event", "EventTarget", "CustomEvent", "AbortController", "AbortSignal", "TextEncoder", "TextDecoder", "URL", "URLSearchParams", "URLPattern", "Blob", "File", "FormData", "Headers", "Request", "Response", "ReadableStream", "WritableStream", "TransformStream", "MessageChannel", "BroadcastChannel", "WebSocket", "EventSource", "Crypto", "SubtleCrypto", "Performance"];
L("constructors", names.filter((n) => typeof globalThis[n] !== "function").join() || "all present");
L("functions", ["fetch", "atob", "btoa", "structuredClone", "queueMicrotask", "setTimeout", "reportError"].map((n) => typeof globalThis[n]).join());
L("raw ops hidden", ["__encoding", "__url", "__http", "__crypto", "__perf", "__wasm", "__ws", "__sse"].filter((n) => n in globalThis).join() || "none");
"""


def test_platform_globals(run, workdir):
    """CATCHES: missing WinterTC globals, navigator.userAgent other than "lumen", performance.now() not
    monotonic, performance.mark/measure entry shapes, Lumen namespace members, or leaking the internal
    __* op namespaces onto globalThis."""
    _check(_run_mjs(run, workdir, PROG_PLATFORM), "platform")
