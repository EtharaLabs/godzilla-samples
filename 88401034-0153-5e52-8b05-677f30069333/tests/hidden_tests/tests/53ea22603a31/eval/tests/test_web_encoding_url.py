"""Web platform encoding and URL layer: TextEncoder/TextDecoder, atob/btoa, URL, URLSearchParams,
URLPattern and structuredClone, as exposed to scripts by lumen-cli."""

from conftest import check_script, resources_for

G = resources_for(__file__)

# Prints `label value` or `label THREW Name: message` for a thunk.
SHOW = r'''
const show = (label, f) => {
  try { console.log(label, f()); }
  catch (e) { console.log(label, 'THREW', e.name + ': ' + e.message); }
};
'''

URL_PARTS = r'''
const KEYS = ['href', 'origin', 'protocol', 'username', 'password', 'host', 'hostname', 'port',
              'pathname', 'search', 'hash'];
const parts = (u) => KEYS.map((k) => k + '=' + JSON.stringify(u[k])).join(' ');
'''


def test_text_encoder_utf8_bytes(run, workdir):
    """CATCHES: a TextEncoder that emits UTF-16 code units or Latin-1 instead of UTF-8, encodes
    astral characters as two 3-byte surrogates, mishandles the undefined/null/number argument
    coercions, or reports an encoding other than utf-8. Also pins the reference's odd 4-byte output
    for a lone surrogate (not U+FFFD)."""
    check_script(run, workdir, G, "text_encoder_utf8_bytes", r'''
const te = new TextEncoder();
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join(' ');
console.log(te.encoding, te.encode('x') instanceof Uint8Array);
for (const s of ['', 'abc', 'aé', '€', '😀', 'ß\u0000z', '\u{10000}', '\uffff', String.fromCodePoint(0x100000)]) {
  const b = te.encode(s);
  console.log(JSON.stringify(s), b.length, hex(b));
}
console.log(te.encode().length, te.encode(undefined).length);
console.log(hex(te.encode(null)), '|', hex(te.encode(12.5)), '|', hex(te.encode({ toString() { return 'ok'; } })));
console.log('lone surrogate:', hex(te.encode('\ud800x')));
''', filename="text_encoder_utf8_bytes.mjs")


def test_text_decoder_bom_fatal_and_inputs(run, workdir):
    """CATCHES: a TextDecoder that keeps the UTF-8 BOM by default (or strips it with ignoreBOM),
    throws instead of substituting U+FFFD for invalid bytes, ignores `fatal`, accepts unsupported
    labels silently, or rejects ArrayBuffer / non-Uint8 views (and pins that DataView and strings
    are rejected with the reference's TypeError message)."""
    check_script(run, workdir, G, "text_decoder_bom_fatal_and_inputs", SHOW + r'''
const td = new TextDecoder();
console.log(td.encoding, td.fatal, td.ignoreBOM);
const bom = new Uint8Array([0xef, 0xbb, 0xbf, 0x68, 0x69]);
console.log(JSON.stringify(td.decode(bom)), td.decode(bom).length);
const keep = new TextDecoder('utf-8', { ignoreBOM: true });
console.log(keep.ignoreBOM, JSON.stringify(keep.decode(bom)), keep.decode(bom).length);
console.log(JSON.stringify(td.decode(new Uint8Array([0x68, 0xff, 0xc3, 0x69]))));
console.log(JSON.stringify(td.decode(new Uint8Array([0xe2, 0x82]), { stream: true })));
const fatal = new TextDecoder('utf-8', { fatal: true });
console.log(fatal.fatal, fatal.decode(new Uint8Array([0xc3, 0xa9])));
show('fatal invalid', () => fatal.decode(new Uint8Array([0x68, 0xff])));
show('ArrayBuffer', () => td.decode(new Uint8Array([104, 105]).buffer));
show('Uint16Array', () => td.decode(new Uint16Array([0x6968])));
show('subarray', () => td.decode(new Uint8Array([97, 98, 99, 100]).subarray(1, 3)));
show('DataView', () => td.decode(new DataView(new ArrayBuffer(2))));
show('string', () => td.decode('abc'));
show('no input', () => JSON.stringify(td.decode()));
for (const label of ['UTF-8', 'utf8', 'unicode-1-1-utf-8', 'latin1', ' utf-8', 'utf-16le']) {
  show('label ' + JSON.stringify(label), () => new TextDecoder(label).encoding);
}
''', filename="text_decoder_bom_fatal_and_inputs.mjs")


def test_btoa_atob_roundtrip_and_errors(run, workdir):
    """CATCHES: wrong base64 padding, atob not stripping ASCII whitespace or not accepting unpadded
    input, btoa accepting characters above U+00FF, or errors that are not DOMException
    InvalidCharacterError with the reference's messages."""
    check_script(run, workdir, G, "btoa_atob_roundtrip_and_errors", SHOW + r'''
for (const s of ['', 'a', 'ab', 'abc', 'abcd', 'hello world', '\xff\xfe\x00', '<<???>>']) {
  const enc = btoa(s);
  console.log(JSON.stringify(s), JSON.stringify(enc), atob(enc) === s);
}
show('btoa number', () => btoa(12345));
show('atob whitespace', () => atob(' aGVs\nbG8=\t'));
show('atob unpadded', () => atob('YQ') + atob('YWI'));
show('atob binary', () => Array.from(atob('/+8A'), (c) => c.charCodeAt(0)).join());
show('atob null', () => JSON.stringify(atob(null)));
for (const bad of ['a', 'ab$c', 'YQ===', '=YQ', 'Y Q=x']) {
  try { atob(bad); console.log('accepted', JSON.stringify(bad)); }
  catch (e) { console.log(JSON.stringify(bad), e.name, e.message, e instanceof DOMException); }
}
try { btoa('€'); } catch (e) { console.log(e.name, e.message, e instanceof DOMException, e instanceof Error); }
''', filename="btoa_atob_roundtrip_and_errors.mjs")


def test_url_components(run, workdir):
    """CATCHES: URL getters returning wrong components: scheme/host not lowercased, default ports
    (80/443/21) not elided, dot segments not resolved, userinfo split at the wrong '@', IPv6 brackets
    lost, opaque (mailto:/data:) paths mangled, or non-special schemes given a '/' path. Also pins the
    reference's verbatim (non percent-encoded) spaces and its `scheme://` origin for opaque URLs."""
    check_script(run, workdir, G, "url_components", URL_PARTS + r'''
for (const s of [
  'HTTP://User:Pw@Example.COM:8080/a/b/../c/./d?q=1&r=a+b#frag',
  'https://x.com:443',
  'ws://h:80/p',
  'ftp://files.example:21/pub/',
  'http://[::1]:9000/x',
  'http://u:p@ss@h/',
  'mailto:someone@example.com?subject=hi',
  'data:text/plain,hello#x',
  'file:///etc/hosts',
  'foo://bar/baz',
  'http://a.com?x',
  'http://a.com/a b?c d#e f',
  '  http://trim.me/  ',
]) {
  console.log(parts(new URL(s)));
}
console.log(String(new URL('http://a.com')), JSON.stringify({ u: new URL('http://a/b') }));
console.log(new URL('http://x/a/.').pathname, new URL('http://x/a/..').pathname, new URL('http://x/a/b/').pathname);
console.log(new URL('http://a.com/%7Euser/%zz/é').pathname);
''', filename="url_components.mjs")


def test_url_relative_resolution(run, workdir):
    """CATCHES: relative references resolved like plain string concatenation: '..' not popping
    directories (or escaping above the root), query-only/fragment-only references not keeping the
    base path (and query for '#'), protocol-relative '//host' not keeping the base scheme, or a URL
    object as base not being stringified."""
    check_script(run, workdir, G, "url_relative_resolution", r'''
const base = 'http://x.com/a/b/c?old#f';
for (const ref of ['d', './d', '../d', '../../../../x', '/d?x', '?q=2', '#g', '', '//y.com/z', 'https://other/', 'e/f/']) {
  console.log(JSON.stringify(ref), '->', new URL(ref, base).href);
}
console.log(new URL('p', new URL('http://x.com/dir/')).href);
console.log(new URL('p', 'http://x.com/dir').href);
console.log(new URL('../up', 'foo://h/a/b').href);
''', filename="url_relative_resolution.mjs")


def test_url_parse_errors(run, workdir):
    """CATCHES: URL accepting invalid input (relative without base, missing host, special scheme
    without '//', out-of-range or non-numeric ports, unclosed IPv6, non-ASCII hosts), throwing
    something other than TypeError with the reference's 'URL: ...' messages, or URL.canParse /
    URL.parse disagreeing with the constructor."""
    check_script(run, workdir, G, "url_parse_errors", SHOW + r'''
for (const [input, base] of [['nobase'], ['http://'], ['http:foo'], ['http://h:99999/'], ['http://h:ab/'],
                             ['http://bücher.de/'], ['x', 'relative'], ['http://[::1/'], ['https://h:65535/ok']]) {
  show(JSON.stringify(input), () => new URL(input, base).href);
}
console.log(URL.canParse('http://a'), URL.canParse('a'), URL.canParse('a', 'http://b/'), URL.canParse('http://h:70000'));
console.log(URL.parse('http://a/b').href, URL.parse('zz'), URL.parse('/x', 'http://h').href);
try { new URL('::'); } catch (e) { console.log(e instanceof TypeError, e.constructor === TypeError); }
''', filename="url_parse_errors.mjs")


def test_url_setters_and_search_params_sync(run, workdir):
    """CATCHES: URL setters that do not re-validate/re-normalise (dot segments, default port, host
    case), a `searchParams` object that goes stale after `search`/`href` changes, mutations through
    `searchParams` not being written back to `search`/`href` (or leaving a dangling '?'), and
    read-only `protocol` not throwing in strict code."""
    check_script(run, workdir, G, "url_setters_and_search_params_sync", SHOW + r'''
const u = new URL('http://h.com/p?a=1&b=2#h');
const sp = u.searchParams;
console.log(sp === u.searchParams, sp.get('a'));
u.pathname = '/x/../y z'; console.log(u.href);
u.search = 'c=3'; console.log(u.href, sp.get('c'), sp.get('a'));
u.search = '?d=4'; console.log(u.search, sp.toString());
u.hash = 'top'; console.log(u.href);
u.hash = ''; console.log(u.href);
u.port = '8081'; console.log(u.href, u.host, u.origin);
u.port = '80'; console.log(u.href, JSON.stringify(u.port));
u.hostname = 'EXAMPLE.org'; console.log(u.href);
u.href = 'https://new.example/q?z=9'; console.log(u.href, sp.get('z'), sp.get('d'));
sp.append('k', 'v w&x'); console.log(u.href, u.search);
sp.set('z', '1'); console.log(u.href);
sp.delete('z'); console.log(u.href);
sp.delete('k'); console.log(JSON.stringify(u.href), JSON.stringify(u.search));
show('bad port', () => { u.port = 'abc'; return u.href; });
show('protocol', () => { u.protocol = 'ftp'; return u.href; });
console.log(u.href);
''', filename="url_setters_and_search_params_sync.mjs")


def test_url_search_params_api(run, workdir):
    """CATCHES: URLSearchParams parsing that does not decode '+' as space, drops empty names/values,
    throws on stray '%', or serialises with '%20' instead of '+'; set() not removing later
    duplicates; sort() not stable; record/sequence/URLSearchParams init forms or the
    pair-length TypeError message behaving differently."""
    check_script(run, workdir, G, "url_search_params_api", SHOW + r'''
const p = new URLSearchParams('?a=1&b=x+y&a=%20z&&c&=e&d=%zz');
console.log(JSON.stringify([...p]), p.size);
console.log(p.get('a'), JSON.stringify(p.getAll('a')), p.has('c'), p.get('nope'), JSON.stringify(p.get('c')));
p.set('a', 'only'); console.log(p.toString());
p.sort(); console.log(p.toString());
const s2 = new URLSearchParams('b=2&a=1&b=1&a=0'); s2.sort(); console.log(s2.toString());
console.log(new URLSearchParams({ x: 1, y: 'a&b=c', z: null }).toString());
console.log(new URLSearchParams([['q', 'é ü'], ['r', "~!*()'-._"]]).toString());
console.log(new URLSearchParams(new URLSearchParams('m=1&n=2')).toString());
show('bad pair', () => new URLSearchParams([['a']]));
const out = [];
new URLSearchParams('a=1&b=2').forEach(function (v, k, o) { out.push(k + ':' + v + ':' + (o instanceof URLSearchParams) + ':' + this.tag); }, { tag: 'T' });
console.log(out.join(' '));
const it = new URLSearchParams('a=1&b=2');
console.log([...it.keys()].join(), [...it.values()].join(), JSON.stringify([...it.entries()]));
console.log(JSON.stringify(new URLSearchParams('').toString()), new URLSearchParams('x').toString(), new URLSearchParams('=').size);
const d = new URLSearchParams('a=1&b=2&a=3'); d.delete('a'); console.log(d.toString(), d.size);
''', filename="url_search_params_api.mjs")


def test_urlpattern_matching(run, workdir):
    """CATCHES: URLPattern that does not compile named groups (':id'), regex groups (':id(\\d+)'),
    wildcards, optional '{...}?' groups and hostname wildcards; missing components defaulting to
    anything but '*'; exec() result shape (inputs + per-component input/groups) differing; or
    string patterns resolved against a baseURL incorrectly. Pins the reference's quirky group
    numbering for ':name*' and bare '*' components."""
    check_script(run, workdir, G, "urlpattern_matching", r'''
const p1 = new URLPattern({ pathname: '/books/:id' });
console.log(p1.protocol, p1.hostname, p1.pathname, p1.search, p1.hash);
console.log(p1.test('https://ex.com/books/42'), p1.test('https://ex.com/books/42/x'), p1.test('https://ex.com/books/'));
console.log(JSON.stringify(p1.exec('https://ex.com/books/42?x=1#f')));
console.log(p1.test('/books/7', 'http://base.org'), p1.exec('not a url'));
console.log(JSON.stringify(p1.exec({ pathname: '/books/9' }).pathname));
const p2 = new URLPattern('https://*.example.com/:cat/*');
console.log(JSON.stringify([p2.protocol, p2.hostname, p2.pathname]));
const r2 = p2.exec('https://api.example.com/users/1/2/3');
console.log(JSON.stringify(r2.hostname), JSON.stringify(r2.pathname));
const p3 = new URLPattern({ pathname: '/item/:id(\\d+)' });
console.log(p3.test('http://x/item/123'), p3.test('http://x/item/abc'));
const p4 = new URLPattern({ pathname: '/files{/:name}?' });
console.log(p4.test('http://x/files'), p4.test('http://x/files/a'), JSON.stringify(p4.exec('http://x/files/a').pathname.groups), JSON.stringify(p4.exec('http://x/files').pathname.groups));
const p5 = new URLPattern('/api/*', 'https://ex.com');
console.log(JSON.stringify([p5.protocol, p5.hostname, p5.pathname]), p5.test('https://ex.com/api/v1'), p5.test('http://ex.com/api/v1'));
const p6 = new URLPattern({ pathname: '/(a|b)/:rest*' });
console.log(JSON.stringify(p6.exec('http://h/a/x/y').pathname));
const p7 = new URLPattern({ search: 'q=:term', hash: '*' });
const r7 = p7.exec('http://h/?q=cats#sec');
console.log(JSON.stringify(r7.search), JSON.stringify(r7.hash));
const p9 = new URLPattern({ hostname: '*.example.com', port: '8080' });
console.log(p9.test('http://a.example.com:8080/'), p9.test('http://a.example.com/'), p9.test('http://example.com:8080/'));
const p10 = new URLPattern({ pathname: '/a.b+c' });
console.log(p10.test('http://h/a.b+c'), p10.test('http://h/aXb+c'));
console.log(JSON.stringify(new URLPattern({ pathname: '/x/:a/:b' }).exec('http://h/x/1/2').pathname.groups));
console.log(new URLPattern().pathname, new URLPattern().test('http://anything/at/all'));
''', filename="urlpattern_matching.mjs")


def test_structured_clone_supported_types(run, workdir):
    """CATCHES: structuredClone that copies by reference, loses cycles or shared references, drops
    `undefined` properties or array holes, does not reconstruct Date/RegExp/Map/Set/typed arrays/
    ArrayBuffer/BigInt/Error subclasses, or shares the typed array's buffer with the original."""
    check_script(run, workdir, G, "structured_clone_supported_types", r'''
const src = { n: 1, s: 'x', b: true, u: undefined, nl: null, big: 10n, d: new Date(86400000),
  re: /a+b/gi, m: new Map([[1, { k: 'v' }]]), set: new Set(['a', 'b']), arr: [1, , 3],
  ta: new Uint16Array([1, 2, 65535]), f64: new Float64Array([0.5, -0]), ab: new Uint8Array([9, 8]).buffer,
  err: new RangeError('bad range'), nested: { deep: [{ x: 1 }] } };
src.self = src;
src.re.lastIndex = 2;
const c = structuredClone(src);
console.log(c !== src, c.self === c, c.nested !== src.nested, c.nested.deep[0].x);
console.log(c.d instanceof Date, c.d !== src.d, c.d.toISOString(), String(c.re), c.re.lastIndex);
console.log(c.m instanceof Map, JSON.stringify([...c.m]), c.m.get(1) !== src.m.get(1), c.set instanceof Set, [...c.set].join());
console.log(1 in c.arr, c.arr.length, JSON.stringify(c.arr));
console.log(c.ta.constructor.name, c.ta.join(), c.ta.buffer !== src.ta.buffer, Object.is(c.f64[1], -0));
console.log(c.ab instanceof ArrayBuffer, c.ab.byteLength, new Uint8Array(c.ab).join(), typeof c.big, String(c.big));
console.log(c.err instanceof RangeError, c.err.name, c.err.message, 'u' in c, c.u, c.nl);
console.log(Object.keys(c).join());
const shared = { v: 1 };
const two = structuredClone([shared, shared, { shared }]);
console.log(two[0] === two[1], two[2].shared === two[0], two[0] !== shared);
const k = { id: 1 };
const [[kk, vv]] = [...structuredClone(new Map([[k, k]]))];
console.log(kk === vv, kk !== k);
console.log([5, 's', null, undefined].map((v) => String(structuredClone(v))).join(), Object.is(structuredClone(-0), -0), String(structuredClone(new Date(NaN))));
''', filename="structured_clone_supported_types.mjs")


def test_structured_clone_errors_and_quirks(run, workdir):
    """CATCHES: structuredClone not throwing DOMException DataCloneError for functions, symbols and
    promises (with the reference's messages), copying getters as accessors instead of values,
    keeping class prototypes or non-enumerable / symbol keys. Pins the reference's quirks: transfer
    lists are ignored (source not detached), WeakMap/DataView/boxed primitives become plain objects,
    Error subclasses keep their constructor but get name 'Error', and extra Error props are dropped."""
    check_script(run, workdir, G, "structured_clone_errors_and_quirks", SHOW + r'''
const fail = (label, v) => {
  try { structuredClone(v); console.log(label, 'cloned'); }
  catch (e) { console.log(label, e.name, e.message, e instanceof DOMException, e instanceof Error); }
};
fail('arrow', () => 1);
fail('method in object', { f() {} });
fail('symbol', Symbol('s'));
fail('promise', Promise.resolve(1));
fail('nested fn', [1, [2, { deep: function named() {} }]]);
const keys = (v) => JSON.stringify(Object.keys(v)) + ' ' + Object.prototype.toString.call(v);
class Point { constructor() { this.x = 1; } get y() { return 2; } }
show('class instance', () => { const p = structuredClone(new Point()); return (p.constructor === Object) + ' ' + JSON.stringify(p); });
show('getter', () => { const o = structuredClone({ get g() { return 5; } }); return JSON.stringify(Object.getOwnPropertyDescriptor(o, 'g')); });
show('non-enumerable', () => { const o = {}; Object.defineProperty(o, 'h', { value: 1, enumerable: false }); o.v = 2; return JSON.stringify(structuredClone(o)); });
show('symbol key', () => Object.getOwnPropertySymbols(structuredClone({ [Symbol('k')]: 1, a: 2 })).length);
show('array extra prop', () => JSON.stringify(Object.keys(structuredClone(Object.assign([1, 2], { extra: 'e' })))));
show('weakmap', () => keys(structuredClone(new WeakMap())));
show('dataview', () => keys(structuredClone(new DataView(new ArrayBuffer(2)))));
show('boxed', () => structuredClone([new Number(3), new String('s'), new Boolean(false)]).map(keys).join(' | '));
show('transfer', () => { const ab = new ArrayBuffer(4); const r = structuredClone(ab, { transfer: [ab] }); return r.byteLength + ' ' + ab.byteLength; });
show('custom error', () => { class MyErr extends Error {} const e = structuredClone(new MyErr('m')); return e.constructor.name + ' ' + e.name + ' ' + e.message; });
show('error props', () => { const e = new TypeError('x'); e.code = 'E1'; const c = structuredClone(e); return c.name + ' ' + c.code; });
show('no argument', () => structuredClone());
''', filename="structured_clone_errors_and_quirks.mjs")
