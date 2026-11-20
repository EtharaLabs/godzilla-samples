"""fetch / Request / Response / Headers, the Lumen.serve HTTP server, and WebSocket / EventSource
clients, all over loopback servers that each test starts on an ephemeral port and shuts down.
Port numbers are never printed (they are replaced with PORT in the scripts)."""

import re

from conftest import assert_golden, check_script, resources_for

G = resources_for(__file__)

SHOW = r'''
const show = async (label, f) => {
  try { console.log(label, await f()); }
  catch (e) { console.log(label, 'THREW', e instanceof Error ? e.name + ': ' + e.message : 'non-error ' + JSON.stringify(e)); }
};
'''

# examples/wintertc-showcase/showcase.mjs, verbatim.
SHOWCASE = r'''// A tour of lumen's WinterTC Minimum Common API — every major interface, exercised end to end.
// Run: ../../target/release/lumen-cli showcase.mjs

const line = (label, value) => console.log(`  ${label.padEnd(26)} ${value}`);
const section = (name) => console.log(`\n${name}`);

// ---- encoding, base64, structuredClone ----
section("Encoding & cloning");
const enc = new TextEncoder().encode("héllo 🌍");
line("TextEncoder/Decoder", new TextDecoder().decode(enc));
line("btoa/atob", atob(btoa("round-trip")));
const cloned = structuredClone({ a: [1, 2], when: new Date(0), re: /x/g });
line("structuredClone", `${JSON.stringify(cloned.a)} ${cloned.re}`);

// ---- URL & URLPattern ----
section("URL & URLPattern");
const u = new URL("https://ex.com/books/42?sort=asc#top");
line("URL parts", `${u.hostname} ${u.pathname} ${u.searchParams.get("sort")}`);
const pat = new URLPattern({ pathname: "/books/:id" });
line("URLPattern match", JSON.stringify(pat.exec(u.href).pathname.groups));

// ---- crypto ----
section("crypto");
line("randomUUID", crypto.randomUUID());
const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("abc"));
line("subtle.digest SHA-256", [...new Uint8Array(digest)].slice(0, 4).map((b) => b.toString(16).padStart(2, "0")).join(""));
line("instanceof Crypto", crypto instanceof Crypto);

// ---- Blob / File / FormData ----
section("Blob / File / FormData");
const blob = new Blob(["hello ", "blob"], { type: "text/plain" });
line("Blob", `${blob.size} bytes, "${await blob.text()}"`);
const form = new FormData();
form.append("field", "value");
form.append("upload", new File(["file contents"], "note.txt", { type: "text/plain" }));
const req = new Request("http://x/", { method: "POST", body: form });
const back = await req.formData();
line("FormData round-trip", `${back.get("field")} + file "${(back.get("upload")).name}"`);

// ---- Streams: Transform + Compression ----
section("Streams");
const upper = new TransformStream({ transform: (c, ctl) => ctl.enqueue(c.toUpperCase()) });
const w = upper.writable.getWriter();
w.write("stream"); w.close();
let piped = "";
for await (const c of upper.readable) piped += c;
line("TransformStream", piped);

async function through(bytes, stream) {
  const rs = new ReadableStream({ start(c) { c.enqueue(bytes); c.close(); } });
  const out = [];
  for await (const chunk of rs.pipeThrough(stream)) out.push(...chunk);
  return new Uint8Array(out);
}
const original = new TextEncoder().encode("compress me ".repeat(20));
const gz = await through(original, new CompressionStream("gzip"));
const un = await through(gz, new DecompressionStream("gzip"));
line("Compression gzip", `${original.length} -> ${gz.length} -> ${un.length} bytes, ok=${new TextDecoder().decode(un) === new TextDecoder().decode(original)}`);

// ---- fetch (drive a local server) ----
section("fetch + HTTP server");
const server = Lumen.serve((request) => Response.json({ path: new URL(request.url).pathname, ok: true }), {
  hostname: "127.0.0.1",
  port: 0,
});
const res = await fetch(`http://127.0.0.1:${server.port}/hello`);
line("fetch JSON", JSON.stringify(await res.json()));
await server.shutdown();

// ---- WebAssembly ----
section("WebAssembly");
// (module (func (export "mul") (param i32 i32) (result i32) local.get 0 local.get 1 i32.mul))
const wasmBytes = new Uint8Array([
  0, 97, 115, 109, 1, 0, 0, 0,
  1, 7, 1, 96, 2, 127, 127, 1, 127,
  3, 2, 1, 0,
  7, 7, 1, 3, 109, 117, 108, 0, 0,
  10, 9, 1, 7, 0, 32, 0, 32, 1, 108, 11,
]);
line("validate", WebAssembly.validate(wasmBytes));
const { instance } = await WebAssembly.instantiate(wasmBytes);
line("instance.exports.mul(6,7)", instance.exports.mul(6, 7));

// ---- performance / timers ----
section("Platform");
line("performance.now", typeof performance.now() === "number" ? "monotonic clock ✓" : "?");
await new Promise((r) => setTimeout(r, 1));
line("setTimeout + Promise", "microtask + macrotask ✓");
line("self === globalThis", self === globalThis);

console.log("\nAll WinterTC Minimum Common API interfaces exercised.");
'''

UUID_LINE = re.compile(rb"^(  randomUUID {16} )[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                       re.MULTILINE)


def test_wintertc_showcase_example(run, workdir):
    """CATCHES: any regression across the documented WinterTC showcase (examples/wintertc-showcase):
    encoding, structuredClone, URL/URLPattern, SHA-256 digest, Blob/FormData multipart round-trip,
    TransformStream, gzip CompressionStream sizes, fetch against Lumen.serve, WebAssembly and the
    platform globals. The random UUID is checked for v4 shape and normalised; all else is exact."""
    (workdir / "showcase.mjs").write_text(SHOWCASE)
    r = run(["showcase.mjs"])
    normalised, count = UUID_LINE.subn(rb"\1<uuid-v4>", r.stdout)
    assert count == 1
    assert_golden(normalised, G / "wintertc_showcase_example.golden")
    assert r.stderr == b""
    assert r.returncode == 0


def test_headers_normalisation_and_iteration(run, workdir):
    """CATCHES: Headers that keep the original name case, do not trim values, iterate in insertion
    order instead of sorted lowercase order, overwrite on append instead of joining with ', '
    (including Set-Cookie), accept invalid header names (with the reference's TypeError message),
    or mishandle record / sequence / Headers init forms."""
    check_script(run, workdir, G, "headers_normalisation_and_iteration", SHOW + r'''
const h = new Headers({ 'Content-Type': 'text/html', 'X-B': '  padded  ' });
h.append('x-a', '1'); h.append('X-A', '2'); h.append('Set-Cookie', 'a=1'); h.append('set-cookie', 'b=2');
console.log(JSON.stringify([...h]));
console.log(h.get('x-a'), JSON.stringify(h.get('X-B')), h.get('missing'), h.has('CONTENT-TYPE'), h.has('nope'));
h.set('x-a', 'only'); h.delete('X-B'); h.delete('never-there');
console.log(JSON.stringify([...h.keys()]), JSON.stringify([...h.values()]), JSON.stringify([...h.entries()]));
const fe = []; h.forEach(function (v, k, o) { fe.push(k + '=' + v + ':' + (o === h) + this.t); }, { t: '!' }); console.log(fe.join(' '));
for (const bad of ['', 'a b', 'x:y', 'é', 'a\n', '(paren)']) await show('bad name ' + JSON.stringify(bad), () => new Headers().append(bad, 'v'));
await show('bad name on get', () => new Headers().get('bad name'));
await show('bad name on has', () => new Headers().has('a@b'));
console.log(JSON.stringify([...new Headers([['b', '2'], ['a', '1'], ['B', '3']])]), JSON.stringify([...new Headers(new Headers({ z: '9' }))]));
await show('bad pair', () => new Headers([['a']]));
console.log(typeof h.getSetCookie, JSON.stringify(new Headers({ v: 5 }).get('v')), JSON.stringify(new Headers({ v: '\tvalue\r\n' }).get('v')), [...new Headers()].length, [...new Headers(null)].length);
''', filename="headers_normalisation_and_iteration.mjs")


def test_request_construction_and_bodies(run, workdir):
    """CATCHES: Request not resolving/normalising its URL, not upper-casing methods, allowing bodies
    on GET/HEAD, missing default Content-Type for string/URLSearchParams/Blob bodies, bodies that
    can be read twice, clone() not duplicating the body, Request(request, init) not inheriting
    url/headers, or relative URLs being accepted without a base."""
    check_script(run, workdir, G, "request_construction_and_bodies", SHOW + r'''
const r = new Request('http://example.com/a/../b?x=1', { method: 'post', headers: { 'X-Y': 'z' }, body: 'hello' });
console.log(r.url, r.method, r.headers.get('x-y'), r.headers.get('content-type'), r.bodyUsed, r.signal, r.body instanceof ReadableStream);
console.log(await r.text(), r.bodyUsed);
await show('read twice', () => r.text());
await show('GET with body', () => new Request('http://x/', { body: 'b' }));
await show('HEAD with body', () => new Request('http://x/', { method: 'HEAD', body: '' }));
await show('relative url', () => new Request('/relative'));
await show('missing host', () => new Request('http://'));
const r2 = new Request('http://x/p', { method: 'PUT', body: JSON.stringify({ a: 1 }), headers: [['content-type', 'application/json']] });
const r3 = r2.clone();
console.log(JSON.stringify(await r2.json()), await r3.text(), r3.method, r3.url, r3.headers.get('content-type'));
const r4 = new Request(r3, { method: 'patch' });
console.log(r4.method, r4.url, r4.headers.get('content-type'));
const r5 = new Request('http://x/', { method: 'DELETE' });
console.log(r5.body, JSON.stringify(await r5.text()));
await show('empty body consumed twice', () => r5.text());
console.log(new Request('http://x/').method, new Request('http://x/', null).method, new Request('http://x/', { method: 'custom' }).method);
const ub = new Request('http://x/', { method: 'POST', body: new URLSearchParams({ q: 'a b', r: 'é' }) });
console.log(ub.headers.get('content-type'), await ub.text());
const bb = new Request('http://x/', { method: 'POST', body: new Blob(['blob!'], { type: 'image/png' }) });
console.log(bb.headers.get('content-type'), await bb.text());
const keep = new Request('http://x/', { method: 'POST', body: 'x', headers: { 'Content-Type': 'text/custom' } });
console.log(keep.headers.get('content-type'));
const ab = new Request('http://x/', { method: 'POST', body: new Uint8Array([104, 105]) });
console.log(ab.headers.get('content-type'), await ab.text());
const ac = new AbortController();
console.log(new Request('http://x/', { signal: ac.signal }).signal === ac.signal);
''', filename="request_construction_and_bodies.mjs")


def test_response_construction_and_bodies(run, workdir):
    """CATCHES: Response with wrong defaults (status 200, statusText '', ok), status range checks
    (RangeError outside 200-599), clone() of used bodies, broken text/json/arrayBuffer/bytes/blob
    readers, `.body` not being one shared ReadableStream, stream bodies that are async/locked/
    non-binary not rejected with the reference messages. Pins quirks: Response.json() keeps the
    text/plain content-type, Response.redirect is absent, and NaN status is accepted."""
    check_script(run, workdir, G, "response_construction_and_bodies", SHOW + r'''
const r = new Response('body text', { status: 201, statusText: 'Created', headers: { 'X-Test': 'yes' } });
console.log(r.status, r.statusText, r.ok, r.headers.get('content-type'), r.headers.get('x-test'), JSON.stringify(r.url), r.redirected, r.bodyUsed, r.type);
const c = r.clone();
console.log(await r.text(), await c.text(), r.bodyUsed, c.bodyUsed);
await show('clone used', () => r.clone());
const d = new Response();
console.log(d.status, JSON.stringify(d.statusText), d.ok, d.body, JSON.stringify(await d.text()), [...d.headers].length);
for (const s of [199, 600, 0, 204, 299, 300, 404, 599, '250', NaN]) await show('status ' + s, () => { const x = new Response(null, { status: s }); return x.status + ' ' + x.ok; });
await show('status undefined', () => new Response(null, { status: undefined }).status);
const j = Response.json({ a: [1, 2], s: 'é' }, { status: 202, headers: { 'X-J': '1' } });
console.log(j.status, j.headers.get('content-type'), j.headers.get('x-j'), await j.text());
const j2 = Response.json('str', { headers: { 'content-type': 'application/vnd+json' } });
console.log(j2.headers.get('content-type'), await j2.json());
await show('json(undefined) text', async () => JSON.stringify(await Response.json(undefined).text()));
await show('json(bigint)', () => Response.json({ b: 1n }));
const e = Response.error();
console.log(e.status, e.type, e.ok, JSON.stringify(e.statusText), typeof Response.redirect);
const bytes = new Response(new Uint8Array([1, 2, 255]));
const ab = await bytes.clone().arrayBuffer(); const by = await bytes.clone().bytes(); const bl = await bytes.blob();
console.log(ab instanceof ArrayBuffer, ab.byteLength, by.constructor.name, by.join(), bl instanceof Blob, bl.size, JSON.stringify(bl.type));
const tb = await new Response('x', { headers: { 'content-type': 'text/x' } }).blob(); console.log(tb.type, await tb.text());
await show('bad json', () => new Response('{bad').json());
const st = new Response(new ReadableStream({ start(ctl) { ctl.enqueue('str '); ctl.enqueue(new Uint8Array([98, 121, 116, 101, 115])); ctl.enqueue(new Uint16Array([0x2120]).buffer); ctl.close(); } }));
console.log(JSON.stringify(await st.text()));
const rd = new Response('streamed').body.getReader(); const ch = await rd.read();
console.log(ch.value.constructor.name, new TextDecoder().decode(ch.value), JSON.stringify(await rd.read()));
const consumed = new Response('abc'); const b1 = consumed.body;
console.log(b1 === consumed.body, consumed.bodyUsed); await consumed.text(); console.log(consumed.bodyUsed);
await show('read body stream after text()', () => b1.getReader().read());
await show('async stream body', () => new Response(new ReadableStream({ async pull(ctl) { await null; ctl.enqueue(new Uint8Array([1])); ctl.close(); } })).text());
await show('locked stream body', () => { const s = new ReadableStream(); s.getReader(); return new Response(s).text(); });
await show('object chunk', () => new Response(new ReadableStream({ start(ctl) { ctl.enqueue({}); ctl.close(); } })).text());
console.log(new Response(new URLSearchParams('a=1')).headers.get('content-type'), await new Response(42).text(), await new Response({ toString() { return 'obj'; } }).text(), new Response('').body === null);
const hcopy = new Headers({ a: '1' }); const rr = new Response('', { headers: hcopy }); hcopy.set('a', '2'); console.log(rr.headers.get('a'), rr.headers !== hcopy);
''', filename="response_construction_and_bodies.mjs")


def test_serve_and_fetch_roundtrip(run, workdir):
    """CATCHES: a Lumen.serve / fetch pair that loses the method, body, custom request headers or
    Content-Length, does not add Host / User-Agent (lumen/<version>) / Connection: close, sends
    response headers unsorted or without Content-Length / Server, uses the wrong default reason
    phrase, corrupts binary bodies, mishandles HEAD, or never resolves `finished` after shutdown."""
    check_script(run, workdir, G, "serve_and_fetch_roundtrip", r'''
const seen = [];
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1', onListen: (info) => seen.push('onListen ' + info.hostname + ' ' + typeof info.port + ' ' + (info.port > 0)) }, async (req, info) => {
  const u = new URL(req.url);
  seen.push(`${req.method} ${u.pathname}${u.search} host-ok=${req.headers.get('host') === '127.0.0.1:' + u.port} ua-ok=${req.headers.get('user-agent') === 'lumen/' + Lumen.version} remote=${info.remoteAddr.hostname}/${info.remoteAddr.transport}/${typeof info.remoteAddr.port}`);
  if (u.pathname === '/echo') {
    const body = await req.text();
    return new Response(JSON.stringify({ method: req.method, body, ct: req.headers.get('content-type'), len: req.headers.get('content-length'), custom: req.headers.get('x-custom'), headerNames: [...req.headers.keys()] }), { headers: { 'content-type': 'application/json', 'X-Reply': 'r' } });
  }
  if (u.pathname === '/status') return new Response('teapot', { status: 418, statusText: "I'm a teapot" });
  if (u.pathname === '/nostatus') return new Response(null, { status: 404 });
  if (u.pathname === '/created') return new Response(null, { status: 201 });
  if (u.pathname === '/bin') return new Response(new Uint8Array([0, 1, 2, 255, 10, 13]), { headers: { 'content-type': 'application/octet-stream' } });
  if (u.pathname === '/headers') { const h = new Headers(); h.append('x-multi', 'a'); h.append('x-multi', 'b'); h.set('Server', 'custom'); return new Response('h', { headers: h }); }
  return new Response('not found: ' + u.pathname, { status: 404 });
});
console.log(typeof server.port, server.hostname, typeof server.finished.then, typeof server.shutdown, typeof server.ref, typeof server.unref);
const base = `http://127.0.0.1:${server.port}`;
const norm = (s) => String(s).replaceAll(String(server.port), 'PORT');
const r1 = await fetch(base + '/echo', { method: 'POST', body: 'hello body', headers: { 'X-Custom': 'abc' } });
console.log(r1.status, r1.statusText, r1.ok, norm(r1.url), r1.redirected, r1.headers.get('content-type'), r1.headers.get('x-reply'), r1.headers.get('connection'), r1.headers.get('content-length'), r1.headers.get('server') === 'lumen/' + Lumen.version);
console.log(JSON.stringify([...r1.headers.keys()]));
console.log(await r1.text());
const r2 = await fetch(base + '/status'); console.log(r2.status, r2.statusText, r2.ok, await r2.text());
const r3 = await fetch(base + '/nostatus'); console.log(r3.status, JSON.stringify(r3.statusText), JSON.stringify(await r3.text()));
const r4 = await fetch(base + '/created'); console.log(r4.status, r4.statusText, r4.headers.get('content-length'));
const r5 = await fetch(base + '/bin'); console.log(new Uint8Array(await r5.arrayBuffer()).join(), (await fetch(base + '/bin').then((x) => x.blob())).type);
const r6 = await fetch(base + '/headers'); console.log(JSON.stringify([...r6.headers]));
const r7 = await fetch(new Request(base + '/echo', { method: 'PUT', body: new URLSearchParams({ k: 'v w' }) })); console.log(await r7.text());
const r8 = await fetch(base + '/echo', { method: 'HEAD' }); console.log(r8.status, JSON.stringify(await r8.text()), r8.headers.get('content-length'));
const r9 = await fetch(base + '/missing?q=1'); console.log(r9.status, r9.ok, await r9.text());
const fin = server.finished;
const sd = server.shutdown();
console.log('shutdown returns finished', sd === fin);
await sd;
console.log(seen.join('\n'));
''', filename="serve_and_fetch_roundtrip.mjs")


def test_fetch_follows_redirects(run, workdir):
    """CATCHES: fetch not following 301/302/303/307 redirects (relative Location resolved against
    the current URL), not setting `redirected`/final `url`, keeping the body on 303 or dropping it
    on 307, looping forever instead of failing with the reference's 'too many redirects' TypeError
    after 5 hops, or following a 3xx that has no Location. Pins that the original Content-Type
    request header survives the 303 method change."""
    check_script(run, workdir, G, "fetch_follows_redirects", r'''
const hops = [];
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, async (req) => {
  const u = new URL(req.url);
  hops.push(req.method + ' ' + u.pathname + u.search);
  const body = req.body ? await req.text() : null;
  switch (u.pathname) {
    case '/a/start': return new Response(null, { status: 302, headers: { location: 'next?step=2' } });
    case '/a/next': return new Response(null, { status: 301, headers: { location: '/final?from=' + u.searchParams.get('step') } });
    case '/final': return new Response('final ' + u.search + ' body=' + body);
    case '/r303': return new Response(null, { status: 303, headers: { location: '/echo' } });
    case '/r307': return new Response(null, { status: 307, headers: { location: '/echo' } });
    case '/r302post': return new Response(null, { status: 302, headers: { location: '/echo' } });
    case '/echo': return Response.json({ method: req.method, body, ct: req.headers.get('content-type') });
    case '/loop': return new Response(null, { status: 302, headers: { location: '/loop' } });
    case '/noloc': return new Response('no location header', { status: 301 });
  }
  return new Response('?', { status: 404 });
});
const base = `http://127.0.0.1:${server.port}`;
const norm = (s) => String(s).replaceAll(String(server.port), 'PORT');
const a = await fetch(base + '/a/start');
console.log(a.status, a.redirected, norm(a.url), await a.text());
const b = await fetch(base + '/r303', { method: 'POST', body: 'dropped' }); console.log('303', b.redirected, await b.text());
const c = await fetch(base + '/r307', { method: 'POST', body: 'kept' }); console.log('307', c.redirected, await c.text());
const d = await fetch(base + '/r302post', { method: 'POST', body: 'post-302' }); console.log('302 POST', await d.text());
try { await fetch(base + '/loop'); } catch (e) { console.log(e.name, norm(e.message)); }
const f = await fetch(base + '/noloc'); console.log(f.status, f.redirected, norm(f.url), await f.text());
await server.shutdown();
console.log(hops.join('\n'));
''', filename="fetch_follows_redirects.mjs")


def test_serve_handler_errors_and_options(run, workdir):
    """CATCHES: Lumen.serve not turning a throwing handler or a non-Response return into a 500
    'Internal Server Error' (and printing the error to stderr), onError not being used (or used
    when it comes from an app object with fetch()), the (options, handler) / (handler, options) /
    {fetch} call forms, AbortSignal shutdown, or argument validation messages."""
    check_script(run, workdir, G, "serve_handler_errors_and_options", r'''
const get = async (s, path = '/') => { const r = await fetch(`http://127.0.0.1:${s.port}${path}`); return r.status + ' ' + r.statusText + ' | ' + (await r.text()); };
const s0 = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, (req) => {
  if (req.url.endsWith('/throw')) throw new Error('handler blew up');
  if (req.url.endsWith('/string')) return 'a string';
  return new Response('fine');
});
console.log('throw', await get(s0, '/throw'));
console.log('non-Response', await get(s0, '/string'));
console.log('still serving', await get(s0));
await s0.shutdown();
const app = { name: 'app', fetch(req) { return new Response('app.fetch this=' + this.name); }, port: 0, hostname: '127.0.0.1' };
const s1 = Lumen.serve(app);
console.log('app object form', await get(s1));
await s1.shutdown();
const s2 = Lumen.serve({ port: 0, hostname: '127.0.0.1', onError: (err) => new Response('onError caught ' + err.name + ' ' + err.message, { status: 503 }) }, () => { throw new RangeError('bad'); });
console.log('onError', await get(s2));
await s2.shutdown();
const s3 = Lumen.serve(() => { throw new Error('x'); }, { port: 0, hostname: '127.0.0.1', onError: () => { throw new Error('onError also throws'); } });
console.log('onError throws', await get(s3));
await s3.shutdown();
const s4 = Lumen.serve({ fetch: () => { throw new Error('from fetch-object'); }, port: 0, hostname: '127.0.0.1', onError: () => new Response('not used') });
console.log('fetch-object onError ignored', await get(s4));
await s4.shutdown();
const ac = new AbortController();
const s5 = Lumen.serve((req) => new Response('signal'), { port: 0, hostname: '127.0.0.1', signal: ac.signal });
console.log('with signal', await get(s5));
ac.abort();
await s5.finished;
console.log('finished after abort');
const s6 = Lumen.serve(async (req) => { await new Promise((r) => setTimeout(r, 5)); return new Response(req.body ? 'has body ' + (await req.text()) : 'no body'); }, { port: 0, hostname: '127.0.0.1' });
console.log('async handler', await get(s6));
for (const [label, init] of [['empty POST', { method: 'POST' }], ['empty string POST', { method: 'POST', body: '' }], ['DELETE with body', { method: 'DELETE', body: 'x' }]]) {
  const r = await fetch(`http://127.0.0.1:${s6.port}/`, init); console.log(label, await r.text());
}
await s6.shutdown();
for (const args of [[42], [{}], [() => {}, { port: 70000, hostname: '127.0.0.1' }], [() => {}, { port: -1, hostname: '127.0.0.1' }]]) {
  try { Lumen.serve(...args); console.log('accepted'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
''', filename="serve_handler_errors_and_options.mjs",
        stderr="Error: handler blew up\nTypeError: serve handler did not return a Response\nError: from fetch-object\n")


def test_fetch_against_node_http_server(run, workdir):
    """CATCHES: a fetch client that cannot read responses from a node:http server (status message,
    multiple res.write() calls, custom headers), drops a caller-supplied User-Agent or other
    request headers, or mishandles redirects issued by a non-Lumen server."""
    check_script(run, workdir, G, "fetch_against_node_http_server", r'''
const http = require('node:http');
const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', () => {
    if (req.url === '/parts') {
      res.writeHead(200, { 'Content-Type': 'text/plain', 'X-Order-Z': 'z', 'X-Order-A': 'a' });
      res.write('part1-');
      res.write('part2-');
      res.end('end');
      return;
    }
    if (req.url === '/json') {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ method: req.method, url: req.url, body, ua: req.headers['user-agent'].replace('lumen/' + Lumen.version, 'lumen/<version>'), accept: req.headers['accept'] ?? null }));
      return;
    }
    if (req.url === '/redir') { res.statusCode = 301; res.setHeader('Location', '/json'); res.end(); return; }
    res.statusCode = 404; res.statusMessage = 'Nope'; res.end('missing ' + req.url);
  });
});
server.listen(0, '127.0.0.1', async () => {
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;
  const a = await fetch(base + '/parts');
  console.log(a.status, a.statusText, a.headers.get('content-length'), JSON.stringify(await a.text()));
  console.log(JSON.stringify([...a.headers.keys()]));
  const b = await fetch(base + '/json', { method: 'POST', body: JSON.stringify({ x: 1 }), headers: { accept: 'application/json', 'User-Agent': 'custom-agent/1.0' } });
  console.log(b.headers.get('content-type'), await b.text());
  const c = await fetch(base + '/redir');
  console.log(c.status, c.redirected, c.url.replace(String(port), 'PORT'), JSON.stringify(await c.json()));
  const d = await fetch(base + '/nothing?x=1');
  console.log(d.status, d.statusText, d.ok, await d.text());
  server.close(() => console.log('server closed'));
});
''', filename="fetch_against_node_http_server.cjs")


def test_fetch_network_errors_and_abort(run, workdir):
    """CATCHES: fetch failures not rejecting with TypeError and the reference's messages (refused
    connections for http and https, unsupported schemes ftp/data/file, relative or missing URLs),
    an already-aborted signal not rejecting with its reason (DOMException AbortError by default),
    or aborting an in-flight request not rejecting immediately with the abort reason (the late
    response must be ignored)."""
    check_script(run, workdir, G, "fetch_network_errors_and_abort", SHOW + r'''
const closed = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, () => new Response('x'));
const port = closed.port;
await closed.shutdown();
const scrub = (f) => async () => { try { return await f(); } catch (e) { e.message = e.message.replaceAll(String(port), 'PORT'); throw e; } };
await show('refused http', scrub(() => fetch(`http://127.0.0.1:${port}/path?q=1`)));
await show('refused https', scrub(() => fetch(`https://127.0.0.1:${port}/`)));
await show('ftp', () => fetch('ftp://example.com/x'));
await show('data', () => fetch('data:text/plain,hi'));
await show('file', () => fetch('file:///etc/hosts'));
await show('relative', () => fetch('/relative'));
await show('no arguments', () => fetch());
await show('GET with body', () => fetch('http://127.0.0.1:1/', { body: 'x' }));
await show('pre-aborted', () => fetch('http://127.0.0.1:1/', { signal: AbortSignal.abort() }));
await show('pre-aborted reason', () => fetch('http://127.0.0.1:1/', { signal: AbortSignal.abort('custom reason') }));
console.log('returns promise', fetch('ftp://x/').catch(() => {}) instanceof Promise);
let release;
const gate = new Promise((r) => { release = r; });
const ac = new AbortController();
const events = [];
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, async () => {
  events.push('handler started');
  ac.abort(new RangeError('stop waiting'));
  await gate;
  events.push('handler responding');
  return new Response('late');
});
await show('in-flight abort', () => fetch(`http://127.0.0.1:${server.port}/slow`, { signal: ac.signal }));
release();
await new Promise((r) => setTimeout(r, 30));
await server.shutdown();
console.log(events.join(', '));
''', filename="fetch_network_errors_and_abort.mjs")


WS_NET_SERVER = r'''
const net = require('node:net');
const { createHash } = require('node:crypto');
// A minimal RFC 6455 server over node:net: answers the upgrade, echoes text ("echo:" prefix) and
// binary frames, and answers a close frame with a close frame. It records what it saw.
const frame = (opcode, payload) => {
  const len = payload.length;
  const head = len < 126 ? [0x80 | opcode, len] : len < 65536 ? [0x80 | opcode, 126, len >> 8, len & 255]
    : [0x80 | opcode, 127, 0, 0, 0, 0, (len >>> 24) & 255, (len >> 16) & 255, (len >> 8) & 255, len & 255];
  return Buffer.concat([Buffer.from(head), Buffer.from(payload)]);
};
const log = [];
const server = net.createServer((sock) => {
  let buf = Buffer.alloc(0);
  let upgraded = false;
  sock.on('data', (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    if (!upgraded) {
      const end = buf.toString('latin1').indexOf('\r\n\r\n');
      if (end < 0) return;
      const lines = buf.subarray(0, end).toString().split('\r\n');
      buf = buf.subarray(end + 4);
      const hdr = Object.fromEntries(lines.slice(1).map((l) => [l.slice(0, l.indexOf(':')).toLowerCase(), l.slice(l.indexOf(':') + 1).trim()]));
      log.push('request line: ' + lines[0]);
      log.push('upgrade=' + hdr.upgrade + ' connection=' + hdr.connection + ' version=' + hdr['sec-websocket-version'] +
        ' protocol=' + hdr['sec-websocket-protocol'] + ' key bytes=' + Buffer.from(hdr['sec-websocket-key'], 'base64').length);
      const accept = createHash('sha1').update(hdr['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      sock.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept +
        (hdr['sec-websocket-protocol'] ? '\r\nSec-WebSocket-Protocol: chat' : '') + '\r\n\r\n');
      upgraded = true;
    }
    while (buf.length >= 2) {
      const opcode = buf[0] & 15, masked = (buf[1] & 128) !== 0;
      let len = buf[1] & 127, off = 2;
      if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); off = 4; }
      else if (len === 127) { if (buf.length < 10) return; len = buf.readUInt32BE(6); off = 10; }
      if (buf.length < off + 4 + len) return;
      const mask = buf.subarray(off, off + 4);
      const data = Buffer.from(buf.subarray(off + 4, off + 4 + len)).map((b, i) => b ^ mask[i % 4]);
      buf = buf.subarray(off + 4 + len);
      log.push('frame opcode=' + opcode + ' masked=' + masked + ' len=' + len + (opcode === 1 ? ' text=' + data.toString().slice(0, 12) :
        opcode === 2 ? ' bytes=' + [...data].join() : opcode === 8 ? ' code=' + data.readUInt16BE(0) + ' reason=' + data.subarray(2).toString() : ''));
      if (opcode === 1) sock.write(frame(1, Buffer.from('echo:' + data.toString())));
      else if (opcode === 2) sock.write(frame(2, data));
      else if (opcode === 8) { sock.write(frame(8, data)); sock.end(); }
    }
  });
});
'''


def test_websocket_client_against_net_server(run, workdir):
    """CATCHES: a WebSocket client with a wrong RFC 6455 handshake (Upgrade/Connection/Version
    headers, 16-byte key, subprotocol list) or unmasked frames, wrong frame encoding for 16-bit and
    64-bit payload lengths (both directions), binaryType 'blob' vs 'arraybuffer' not applied per
    message, wrong open/message/close event sequence, or a close handshake that does not report
    the echoed code/reason with wasClean=true. Pins that a Blob send is queued behind later
    synchronous sends (its bytes are read asynchronously)."""
    check_script(run, workdir, G, "websocket_client_against_net_server", WS_NET_SERVER + r'''
server.listen(0, '127.0.0.1', () => {
  const url = `ws://127.0.0.1:${server.address().port}/chat?room=1`;
  const ws = new WebSocket(url, ['chat', 'superchat']);
  console.log('initial', ws.readyState, ws.binaryType, ws.url === url, JSON.stringify(ws.protocol), ws.bufferedAmount);
  let n = 0;
  ws.onopen = (e) => {
    console.log('open', e.type, ws.readyState, ws.protocol, JSON.stringify(ws.extensions));
    ws.send('hello'); ws.send(new Uint8Array([1, 2, 3])); ws.send('x'.repeat(200)); ws.send(new Blob(['blob'])); ws.send('y'.repeat(70000));
  };
  ws.addEventListener('message', async (e) => {
    n++;
    const d = e.data;
    const desc = typeof d === 'string' ? JSON.stringify(d.length > 20 ? d.slice(0, 10) + '...(' + d.length + ')' : d)
      : d instanceof Blob ? 'Blob(' + d.size + ')' : d.constructor.name + '[' + new Uint8Array(d).join() + ']';
    console.log('message', n, desc, e instanceof MessageEvent);
    if (n === 2) ws.binaryType = 'arraybuffer';
    if (n === 5) ws.close(4000, 'done');
  });
  ws.onclose = (e) => {
    console.log('close', e instanceof CloseEvent, e.code, JSON.stringify(e.reason), e.wasClean, ws.readyState);
    console.log(log.join('\n'));
    server.close();
  };
});
''', filename="websocket_client_against_net_server.cjs")


def test_websocket_constructor_and_close_validation(run, workdir):
    """CATCHES: WebSocket accepting invalid URLs, non-ws schemes, fragments, empty/duplicate/
    separator-containing subprotocols, send() before open not throwing InvalidStateError,
    close() accepting reserved codes or >123-byte reasons, bad binaryType values, or a refused
    connection not producing error + close(1006, wasClean=false) events in that order."""
    check_script(run, workdir, G, "websocket_constructor_and_close_validation", SHOW + r'''
for (const [label, args] of [['no args', []], ['bad url', ['not a url']], ['http scheme', ['http://127.0.0.1/']], ['fragment', ['ws://127.0.0.1/#frag']],
                             ['empty protocol', ['ws://127.0.0.1:1/', '']], ['duplicate protocol', ['ws://127.0.0.1:1/', ['a', 'a']]], ['protocol with space', ['ws://127.0.0.1:1/', 'a b']]]) {
  await show(label, () => { new WebSocket(...args); return 'constructed'; });
}
console.log(WebSocket.CONNECTING, WebSocket.OPEN, WebSocket.CLOSING, WebSocket.CLOSED, WebSocket.prototype.onmessage);
const closed = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, () => new Response('x'));
const port = closed.port;
await closed.shutdown();
const ws = new WebSocket(`ws://127.0.0.1:${port}/x`, 'proto');
console.log(ws.readyState, ws.CONNECTING, ws.url.replace(String(port), 'PORT'), ws.binaryType);
await show('send while connecting', () => ws.send('x'));
await show('binaryType nope', () => { ws.binaryType = 'nope'; });
ws.binaryType = 'arraybuffer';
console.log('binaryType now', ws.binaryType);
await show('close code 1001', () => ws.close(1001));
await show('close code 2999', () => ws.close(2999));
await show('close long reason', () => ws.close(1000, 'é'.repeat(62)));
const events = [];
ws.onerror = (e) => events.push('onerror ' + e.type + ' state=' + ws.readyState);
ws.addEventListener('error', () => events.push('error listener'));
await new Promise((resolve) => {
  ws.onclose = (e) => { events.push('close ' + e.code + ' ' + JSON.stringify(e.reason) + ' ' + e.wasClean + ' state=' + ws.readyState); resolve(); };
});
console.log(events.join('\n'));
await show('send after close is silent', () => ws.send('ignored'));
await show('close after close', () => ws.close());
''', filename="websocket_constructor_and_close_validation.mjs")


def test_lumen_upgrade_websocket_receive_and_close(run, workdir):
    """CATCHES: Lumen.upgradeWebSocket not returning null for plain requests, accepting requests
    not delivered by Lumen.serve or a second upgrade of the same connection, server-side handles
    lacking send/close/onmessage/onclose, received text/binary frames losing type or bytes
    (numbers sent as text), or the close handshake not reporting code 1000 + reason to the
    server and wasClean to the client. (Only client->server traffic is exercised.)"""
    check_script(run, workdir, G, "lumen_upgrade_websocket_receive_and_close", r'''
const log = [];
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, async (req) => {
  if (new URL(req.url).pathname === '/plain') return new Response('plain request, upgrade returned ' + Lumen.upgradeWebSocket(req));
  const sock = Lumen.upgradeWebSocket(req, { headers: { 'X-Extra': 'yes' } });
  log.push('server: upgraded, handle keys ' + Object.keys(sock).sort().join(','));
  try { Lumen.upgradeWebSocket(req); } catch (e) { log.push('second upgrade: ' + e.name + ': ' + e.message); }
  sock.onmessage = (data, isBinary) => log.push('server got ' + (isBinary ? 'binary ' + data.constructor.name + '[' + Array.from(data).join() + ']' : 'text ' + JSON.stringify(data)));
  sock.onclose = (code, reason, wasClean) => log.push(`server close ${code} ${JSON.stringify(reason)} ${wasClean}`);
  return new Response('ignored after upgrade');
});
try { Lumen.upgradeWebSocket(new Request('http://x/')); } catch (e) { console.log(e.name + ': ' + e.message); }
const base = `127.0.0.1:${server.port}`;
console.log(await (await fetch(`http://${base}/plain`)).text());
const ws = new WebSocket(`ws://${base}/sock`);
ws.onopen = () => {
  console.log('client open', JSON.stringify(ws.protocol));
  ws.send('one'); ws.send(new Uint8Array([7, 8])); ws.send(new Float32Array([1]).buffer); ws.send(12345); ws.send('');
  ws.close(1000, 'client done');
  console.log('after close() readyState', ws.readyState);
  ws.send('dropped silently');
};
ws.onclose = (e) => {
  console.log('client close', e.code, JSON.stringify(e.reason), e.wasClean, ws.readyState);
  setTimeout(async () => { console.log(log.join('\n')); await server.shutdown(); console.log('server finished'); }, 50);
};
''', filename="lumen_upgrade_websocket_receive_and_close.mjs")


def test_event_source_parsing_and_reconnect(run, workdir):
    """CATCHES: an EventSource whose text/event-stream parser mishandles comments, multi-line
    data, CR / CRLF / LF line endings, the single optional space after ':', field-only lines,
    named events, id/lastEventId persistence (and reset by an empty id), blocks without data, or
    retry; that does not send Accept/Cache-Control/Last-Event-ID headers; or that does not
    reconnect after the stream ends and stop for good after close()."""
    check_script(run, workdir, G, "event_source_parsing_and_reconnect", r'''
const log = [];
let conn = 0;
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, (req) => {
  conn++;
  log.push(`server: conn ${conn} ${new URL(req.url).pathname} accept=${req.headers.get('accept')} cache=${req.headers.get('cache-control')} last-event-id=${req.headers.get('last-event-id')}`);
  if (conn === 1) {
    const body = ': a comment line\n' +
      'data: first\n\n' +
      'id: 7\nevent: custom\ndata: line1\ndata: line2\n\n' +
      'data:no-space\r\n\r\n' +
      'data:  two spaces\rid\r\r' +
      'event: ignored-without-data\n\n' +
      'unknown: field\ndata\n\n' +
      'id: 9\nretry: 40\n\n' +
      'data: last before drop\n\n';
    return new Response(body, { headers: { 'content-type': 'text/event-stream; charset=utf-8' } });
  }
  return new Response('event: done\ndata: reconnected\n\n', { headers: { 'content-type': 'text/event-stream' } });
});
const url = `http://127.0.0.1:${server.port}/events`;
const es = new EventSource(url);
console.log(es.readyState, es.url === url, es.withCredentials, EventSource.CONNECTING, EventSource.OPEN, EventSource.CLOSED, es instanceof EventTarget);
es.onopen = (e) => console.log('open', e.type, es.readyState);
es.onmessage = (e) => console.log('message', JSON.stringify(e.data), JSON.stringify(e.lastEventId), e.origin === new URL(url).origin, e instanceof MessageEvent);
es.addEventListener('custom', (e) => console.log('custom', JSON.stringify(e.data), e.lastEventId));
es.onerror = (e) => console.log('error', e.type, es.readyState);
es.addEventListener('done', (e) => {
  console.log('done', e.data, e.lastEventId);
  es.close();
  console.log('closed', es.readyState);
  setTimeout(async () => { console.log(log.join('\n')); await server.shutdown(); }, 30);
});
''', filename="event_source_parsing_and_reconnect.mjs")


def test_event_source_failures(run, workdir):
    """CATCHES: EventSource accepting invalid or non-http URLs (SyntaxError expected), reconnecting
    after fatal responses (wrong Content-Type, 204, HTTP 500 must fail permanently with readyState
    CLOSED), not following redirects (or following one to a non-http scheme), ignoring
    withCredentials, or a refused connection not firing error in CONNECTING state (with close()
    from onerror stopping retries). Pins a reference quirk: an EventSource closed before its
    connection opens still fires one 'error' event."""
    check_script(run, workdir, G, "event_source_failures", r'''
let earlyRequest;
const earlySeen = new Promise((r) => { earlyRequest = r; });
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, (req) => {
  const p = new URL(req.url).pathname;
  if (p === '/wrongtype') return new Response('data: x\n\n', { headers: { 'content-type': 'text/plain' } });
  if (p === '/nocontent') return new Response(null, { status: 204 });
  if (p === '/err') return new Response('boom', { status: 500 });
  if (p === '/redir') return new Response(null, { status: 302, headers: { location: '/ok' } });
  if (p === '/badredir') return new Response(null, { status: 302, headers: { location: 'ftp://elsewhere/x' } });
  if (p === '/early') { earlyRequest(); return new Response('data: never delivered\n\n', { headers: { 'content-type': 'text/event-stream' } }); }
  return new Response('data: via redirect\n\n', { headers: { 'content-type': 'text/event-stream' } });
});
const base = `http://127.0.0.1:${server.port}`;
for (const bad of ['not a url', 'ftp://x/y']) {
  try { new EventSource(bad); console.log('constructed?'); } catch (e) { console.log(JSON.stringify(bad), e.name, e.message, e instanceof DOMException); }
}
try { new EventSource(); } catch (e) { console.log(e.name + ': ' + e.message); }
const run = (path) => new Promise((resolve) => {
  const es = new EventSource(base + path, { withCredentials: true });
  const events = [];
  es.onopen = () => events.push('open');
  es.onmessage = (e) => { events.push('message:' + e.data); es.close(); resolve(path + ' ' + events.join(',') + ' state=' + es.readyState + ' withCredentials=' + es.withCredentials); };
  es.onerror = () => { events.push('error(state=' + es.readyState + ')'); resolve(path + ' ' + events.join(',') + ' state=' + es.readyState); };
});
for (const p of ['/wrongtype', '/nocontent', '/err', '/redir', '/badredir']) console.log(await run(p));
const early = new EventSource(base + '/early');
const earlyEvents = [];
for (const t of ['open', 'message', 'error']) early.addEventListener(t, () => earlyEvents.push(t));
// The reference fires one late 'error'; allow up to 2 s for it (a no-event implementation just waits).
const lateError = new Promise((r) => early.addEventListener('error', r));
early.close();
await earlySeen;
let fallback;
await Promise.race([lateError, new Promise((r) => { fallback = setTimeout(r, 2000); })]);
clearTimeout(fallback);
await new Promise((r) => setTimeout(r, 20));
console.log('closed before open: server saw request, client events', JSON.stringify(earlyEvents), early.readyState);
await server.shutdown();
const es = new EventSource(`http://127.0.0.1:${server.port}/gone`);
es.onerror = () => { console.log('refused -> error, state', es.readyState); es.close(); console.log('closed in onerror', es.readyState); };
''', filename="event_source_failures.mjs")


def test_fetch_parses_raw_http_responses(run, workdir):
    """CATCHES: an HTTP client that cannot decode chunked bodies (chunk extensions, trailers),
    bodies delimited only by connection close, HTTP/1.0 status lines, empty reason phrases,
    header lines without a colon, padded or duplicated headers, or that reads a body for 204/304/
    HEAD; or whose errors for malformed status lines, bad chunk sizes and truncated bodies differ
    from the reference. Also checks that user Host/Connection headers are replaced, not sent."""
    check_script(run, workdir, G, "fetch_parses_raw_http_responses", r'''const net = require('node:net');
const RESPONSES = {
  '/chunked': 'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: text/plain\r\n\r\n5;ext=1\r\nHello\r\n7\r\n, world\r\nA\r\n!123456789\r\n0\r\nX-Trailer: t\r\n\r\n',
  '/eof': 'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nread until the server closes',
  '/noreason': 'HTTP/1.1 299\r\nContent-Length: 2\r\n\r\nok',
  '/badstatus': 'HTTP/1.1 abc Weird\r\n\r\n',
  '/garbage': 'not http at all\r\n\r\n',
  '/headers': 'HTTP/1.1 200 Fine Thanks\r\nX-Spaces:    padded value   \r\nno-colon-line\r\nX-Dup: 1\r\nX-Dup: 2\r\nContent-Length: 3\r\n\r\nabcEXTRA',
  '/204': 'HTTP/1.1 204 No Content\r\nContent-Length: 5\r\n\r\n',
  '/304': 'HTTP/1.1 304 Not Modified\r\n\r\n',
  '/badchunk': 'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nabc\r\n0\r\n\r\n',
  '/short': 'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nabc',
  '/http10': 'HTTP/1.0 200 OK\r\nContent-Length: 4\r\n\r\nold!',
};
const seen = [];
const server = net.createServer((sock) => {
  let buf = '';
  sock.on('data', (c) => {
    buf += c.toString('latin1');
    const end = buf.indexOf('\r\n\r\n');
    if (end < 0) return;
    const head = buf.slice(0, end).split('\r\n');
    const path = head[0].split(' ')[1];
    seen.push(head.map((l) => l.replace('lumen/' + Lumen.version, 'lumen/V').replace(/:\d+$/, ':PORT')).join(' | '));
    sock.end(RESPONSES[path] ?? 'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n');
  });
  sock.on('error', () => {});
});
server.listen(0, '127.0.0.1', async () => {
  const base = `http://127.0.0.1:${server.address().port}`;
  for (const p of Object.keys(RESPONSES)) {
    try {
      const r = await fetch(base + p, p === '/204' ? { method: 'GET', headers: { Host: 'ignored.example', Connection: 'keep-alive', 'X-Mine': 'm' } } : undefined);
      console.log(p, r.status, JSON.stringify(r.statusText), JSON.stringify([...r.headers]), JSON.stringify(await r.text()));
    } catch (e) { console.log(p, 'THREW', e.name, e.message.replace(/:\d+\//, ':PORT/')); }
  }
  const h = await fetch(base + '/eof', { method: 'HEAD' }); console.log('HEAD', h.status, JSON.stringify(await h.text()));
  console.log(seen.join('\n'));
  server.close();
});
''', filename="fetch_parses_raw_http_responses.cjs")


def test_serve_handles_raw_http_requests(run, workdir):
    """CATCHES: a Lumen.serve request parser that mishandles chunked request bodies, absolute-form
    and slash-less request targets, a missing Host header (must fall back to the listen address),
    lowercase methods, duplicate headers, bodies longer than Content-Length, or headers cut off by
    EOF; that does not answer malformed/empty/oversized (>64 KiB) requests with 400 and the
    reference's plain-text reasons; that lets handlers override Connection/Transfer-Encoding;
    or whose default reason phrases (or empty phrase for unknown codes) differ."""
    check_script(run, workdir, G, "serve_handles_raw_http_requests", r'''const net = require('node:net');
const seen = [];
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, async (req) => {
  const body = req.body ? await req.text() : null;
  seen.push(`${req.method} ${req.url.replace(String(server.port), 'PORT')} body=${JSON.stringify(body)} headers=${JSON.stringify([...req.headers])}`);
  const u = new URL(req.url);
  if (u.pathname.startsWith('/status/')) return new Response(null, { status: Number(u.pathname.slice(8)) });
  return new Response('ok:' + u.pathname, { headers: { 'Connection': 'keep-alive', 'Transfer-Encoding': 'chunked', 'X-Kept': 'k' } });
});
const raw = (data, { end = true } = {}) => new Promise((resolve) => {
  const sock = net.connect(server.port, '127.0.0.1', () => { if (data !== null) sock.write(data); if (end) sock.end(); });
  let out = '';
  sock.on('data', (c) => { out += c.toString('latin1'); });
  sock.on('close', () => resolve(out.replaceAll('lumen/' + Lumen.version, 'lumen/V').replace(/\r\n/g, '\\r\\n')));
  sock.on('error', () => resolve('socket error'));
});
(async () => {
  console.log('1', await raw('GET /plain HTTP/1.1\r\nHost: example.test\r\n\r\n'));
  console.log('2', await raw('POST /chunked HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nWiki\r\n5;x=y\r\npedia\r\n0\r\n\r\n'));
  console.log('3', await raw('GET http://absolute.example/abs?q=1 HTTP/1.1\r\nHost: h\r\n\r\n'));
  console.log('4', await raw('GET relative-target HTTP/1.1\r\nHost: h\r\n\r\n'));
  console.log('5', await raw('GET /nohost HTTP/1.0\r\n\r\n'));
  console.log('6', await raw('get /lower HTTP/1.1\r\nHost: h\r\nX-Dup: a\r\nX-Dup: b\r\n\r\n'));
  console.log('7', await raw('\r\n\r\n'));
  console.log('8', await raw('GET /big HTTP/1.1\r\nX-Big: ' + 'a'.repeat(70000) + '\r\n\r\n'));
  console.log('9', await raw('POST /cl HTTP/1.1\r\nHost: h\r\nContent-Length: 5\r\n\r\nhelloEXTRA'));
  console.log('10', await raw('POST /badchunk HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\nqq\r\n'));
  console.log('11', await raw('GET /eof-headers HTTP/1.1\r\nHost: h\r\n'));
  console.log('12', await raw(null));
  console.log('13', await raw('GET /after-junk HTTP/1.1\r\nHost: h\r\n\r\n'));
  for (const s of [200, 201, 202, 204, 301, 302, 303, 304, 307, 308, 400, 401, 403, 404, 405, 409, 410, 422, 429, 500, 501, 502, 503, 299, 418]) {
    const r = await raw(`GET /status/${s} HTTP/1.1\r\nHost: h\r\n\r\n`);
    console.log('status', r.split('\\r\\n')[0]);
  }
  console.log(seen.join('\n'));
  await server.shutdown();
})();
''', filename="serve_handles_raw_http_requests.cjs")


def test_websocket_frame_protocol_edge_cases(run, workdir):
    """CATCHES: a WebSocket client that does not answer pings with pongs (even mid-fragment),
    fails to reassemble fragmented text/binary messages, mishandles 16-bit and 64-bit payload
    lengths or (tolerated) masked server frames, reports the wrong code/reason for empty and
    coded close frames, or does not fail the connection with the right close code and reason
    (1002/1007) for reserved bits, malformed control frames, stray continuations, interleaved data
    frames, unknown opcodes and invalid UTF-8; or that accepts bad handshakes (non-101 status,
    wrong Sec-WebSocket-Accept, missing Upgrade, unrequested subprotocol)."""
    check_script(run, workdir, G, "websocket_frame_protocol_edge_cases", r'''const net = require('node:net');
const { createHash } = require('node:crypto');
const frame = (b0, payload, { mask } = {}) => {
  payload = Buffer.from(payload);
  const len = payload.length;
  const head = len < 126 ? [b0, len] : len < 65536 ? [b0, 126, len >> 8, len & 255] : [b0, 127, 0, 0, 0, 0, (len >>> 24) & 255, (len >> 16) & 255, (len >> 8) & 255, len & 255];
  if (mask) { head[1] |= 0x80; const m = [1, 2, 3, 4]; return Buffer.concat([Buffer.from(head), Buffer.from(m), Buffer.from(payload.map((b, i) => b ^ m[i % 4]))]); }
  return Buffer.concat([Buffer.from(head), payload]);
};
const FIN = 0x80;
const SCENARIOS = {
  ping: () => [frame(FIN | 9, 'hb'), frame(FIN | 1, 'after-ping'), frame(FIN | 8, [0x03, 0xe8])],
  frag: () => [frame(1, 'Hel'), frame(FIN | 9, 'mid'), frame(0, 'lo '), frame(FIN | 0, 'world'), frame(FIN | 10, 'unsolicited'),
    frame(2, [1, 2]), frame(FIN, [3]), frame(FIN | 2, Buffer.alloc(300, 7)), frame(FIN | 2, Buffer.alloc(70000, 9)), frame(FIN | 1, 'masked-ok', { mask: true }), frame(FIN | 8, '')],
  closecode: () => [frame(FIN | 8, Buffer.concat([Buffer.from([0x0f, 0xa1]), Buffer.from('bye now')]))],
  badutf8: () => [frame(FIN | 1, [0x68, 0xff])],
  rsv: () => [frame(FIN | 0x40 | 1, 'x')],
  badcontrol: () => [frame(9, 'p')],
  cont: () => [frame(FIN | 0, 'x')],
  newdata: () => [frame(1, 'a'), frame(FIN | 1, 'b')],
  opcode: () => [frame(FIN | 3, 'x')],
  closeutf8: () => [frame(FIN | 8, [0x03, 0xe8, 0xff])],
  eof: 'destroy',
};
const FRAMES = Object.fromEntries(Object.entries(SCENARIOS).map(([k, v]) => [k, typeof v === 'function' ? v() : v])); // built up front
const HANDSHAKE = { refuse: 'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n', badaccept: 'accept', noupgrade: 'noupgrade', badproto: 'proto' };
const serverLog = {};
const closedSockets = {};
const server = net.createServer((sock) => {
  let buf = Buffer.alloc(0);
  let name = null;
  let done;
  const closedP = new Promise((r) => { done = r; });
  sock.on('close', () => { serverLog[name]?.push('socket closed'); done(); });
  sock.on('error', () => {});
  sock.on('data', (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    if (name === null) {
      const end = buf.toString('latin1').indexOf('\r\n\r\n');
      if (end < 0) return;
      const lines = buf.subarray(0, end).toString().split('\r\n');
      buf = buf.subarray(end + 4);
      name = lines[0].split(' ')[1].slice(1);
      closedSockets[name] = closedP;
      serverLog[name] = [];
      const key = /sec-websocket-key: (\S+)/i.exec(lines.join('\n'))[1];
      let accept = createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      const h = HANDSHAKE[name];
      if (h && h.startsWith('HTTP')) { sock.write(h); return; }
      if (h === 'accept') accept = 'AAAA' + accept.slice(4);
      const upgrade = h === 'noupgrade' ? '' : 'Upgrade: websocket\r\n';
      const proto = h === 'proto' ? 'Sec-WebSocket-Protocol: other\r\n' : '';
      // The client allows ~100 ms for the handshake reply: send it first, frames once it is flushed.
      sock.write('HTTP/1.1 101 Switching Protocols\r\n' + upgrade + 'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n' + proto + '\r\n', () => {
        if (h) return;
        const frames = FRAMES[name];
        if (frames === 'destroy') { setTimeout(() => sock.destroy(), 5); return; }
        for (const f of frames) sock.write(f);
      });
    }
    while (buf.length >= 6) {
      const opcode = buf[0] & 15;
      const len = buf[1] & 127;
      if (len >= 126 || buf.length < 6 + len) return;
      const m = buf.subarray(2, 6);
      const data = Buffer.from(buf.subarray(6, 6 + len)).map((b, i) => b ^ m[i % 4]);
      buf = buf.subarray(6 + len);
      serverLog[name].push(opcode === 10 ? 'client pong ' + JSON.stringify(data.toString()) : opcode === 8 ? 'client close ' + (data.length >= 2 ? data.readUInt16BE(0) + ' ' + JSON.stringify(data.subarray(2).toString()) : '(empty)') : 'client opcode ' + opcode);
      if (opcode === 8) sock.end();
    }
  });
});
const runOne = (port, name) => new Promise((resolve) => {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/${name}`, name === 'badproto' ? 'chat' : undefined);
  ws.binaryType = 'arraybuffer';
  const ev = [];
  ws.onopen = () => ev.push('open');
  ws.onmessage = (e) => ev.push('message ' + (typeof e.data === 'string' ? JSON.stringify(e.data) : 'binary(' + e.data.byteLength + ':' + new Uint8Array(e.data).slice(0, 3).join() + ')'));
  ws.onerror = () => ev.push('error');
  ws.onclose = (e) => { ev.push(`close ${e.code} ${JSON.stringify(e.reason)} ${e.wasClean}`); resolve(ev); };
});
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  for (const name of [...Object.keys(SCENARIOS), ...Object.keys(HANDSHAKE)]) {
    const ev = await runOne(port, name);
    await closedSockets[name];
    console.log(name.padEnd(11), ev.join(' | '), ' || server saw:', serverLog[name].join(', '));
  }
  server.close();
});
''', filename="websocket_frame_protocol_edge_cases.cjs")


def test_node_net_loopback_errors_and_unix_socket(run, workdir):
    """CATCHES: node:net servers/sockets over loopback reporting wrong address()/remote* info,
    byte counters or close(hadError) flags, EADDRINUSE / ECONNREFUSED errors without the Node-style
    code/syscall/address/port/message fields, or unix-domain socket servers on a relative path
    not working (and ENOENT for a missing socket path)."""
    r = check_script(run, workdir, G, "node_net_loopback_errors_and_unix_socket", r'''const net = require('node:net');
const serverEvents = [];
const fmtErr = (e, port) => [e.name, e.code, e.syscall, JSON.stringify(e.errno), e.address, e.port === port ? 'PORT' : e.port, e.message.replaceAll(String(port), 'PORT')].join(' | ');
const server = net.createServer((sock) => {
  serverEvents.push('conn ' + sock.remoteAddress + ' ' + sock.remoteFamily + ' ' + typeof sock.remotePort + ' ' + JSON.stringify({ ...sock.address(), port: 'P' }));
  sock.setNoDelay(true); sock.setKeepAlive(true, 1000);
  sock.on('data', (d) => { serverEvents.push('data ' + d); sock.write('echo:' + d); sock.end(); });
});
server.listen(0, '127.0.0.1', () => {
  const addr = server.address();
  console.log('listening', addr.address, addr.family, typeof addr.port, server.listening);
  const dup = net.createServer();
  dup.on('error', (e) => {
    console.log('second listen on same port:', fmtErr(e, addr.port));
    const c = net.connect({ port: addr.port, host: '127.0.0.1' });
    c.setEncoding('utf8');
    c.on('connect', () => { console.log('client connect', c.remoteAddress, c.remotePort === addr.port, typeof c.localPort); c.write('ping'); });
    let got = '';
    c.on('data', (d) => { got += d; });
    c.on('end', () => console.log('client end', got));
    c.on('close', (hadErr) => {
      console.log('client close', hadErr, c.destroyed, c.bytesWritten, c.bytesRead);
      server.close(() => {
        console.log('server closed', server.listening, serverEvents.join(' ; '));
        // the accept thread drops its listener clone shortly after close(): give it time first
        setTimeout(() => {
        const r = net.connect(addr.port, '127.0.0.1');
        r.on('error', (e) => console.log('refused:', fmtErr(e, addr.port)));
        r.on('close', (hadErr) => {
          console.log('refused close', hadErr);
          const us = net.createServer((s) => { s.on('data', (d) => s.end('unix:' + d)); });
          us.listen('sock.ipc', () => {
            console.log('unix listening', JSON.stringify(us.address()));
            const uc = net.connect('sock.ipc', () => uc.write('hi'));
            uc.on('data', (d) => console.log('unix reply', String(d)));
            uc.on('close', () => us.close(() => {
              console.log('unix closed');
              const bad = net.connect('missing.ipc');
              bad.on('error', (e) => console.log('unix missing:', e.code, e.syscall, e.message));
            }));
          });
        });
        }, 300);
      });
    });
  });
  dup.listen(addr.port, '127.0.0.1');
});
''', filename="node_net_loopback_errors_and_unix_socket.cjs")
    assert sorted(p.name for p in workdir.iterdir()) == ["node_net_loopback_errors_and_unix_socket.cjs"]
    assert r.returncode == 0
