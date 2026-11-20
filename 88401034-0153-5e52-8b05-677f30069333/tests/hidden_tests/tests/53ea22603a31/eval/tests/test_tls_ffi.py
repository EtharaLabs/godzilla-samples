"""node:tls over loopback (the reference drives the system OpenSSL through dlopen) plus the https
clients that verify certificates (fetch / node:https / wss WebSocket / https EventSource), and
bun:ffi against libc.so.6 / libm.so.6 (glibc; identical on x86-64 and arm64).

TLS tests only exchange handshakes (no application data: a TLS write that races the socket's read
pump can be delayed for seconds by the reference) and assert API-level fields, never cipher names,
certificate dates or OpenSSL error-queue text (messages are cut before the '(SSL error' detail).
FFI tests never print native addresses (only differences between pointers into one buffer)."""

from conftest import check_script, resources_for

G = resources_for(__file__)

PEMS = r'''// Self-signed EC P-256 certificate for CN=localhost (SAN DNS:localhost, IP:127.0.0.1), valid 2026-2126,
// its private key, and an unrelated second key (for the key-mismatch case).
const CERT = `-----BEGIN CERTIFICATE-----
MIIBnDCCAUGgAwIBAgIUKfwDLNWWO9qHqGlsJelwCjTZ8PwwCgYIKoZIzj0EAwIw
FDESMBAGA1UEAwwJbG9jYWxob3N0MCAXDTI2MTExMDAxMzcyMloYDzIxMjYxMDE3
MDEzNzIyWjAUMRIwEAYDVQQDDAlsb2NhbGhvc3QwWTATBgcqhkjOPQIBBggqhkjO
PQMBBwNCAARQ8i8oBhVIRXaJHgn4HV0PPGxsu31t172RAkySeVKO9nt/Bvzc13JO
C+SMv3EHBve9kYPhAB1hZjjMso0DhITJo28wbTAdBgNVHQ4EFgQUV+/MQ8KXIu/+
qPMieavSlSzKm9wwHwYDVR0jBBgwFoAUV+/MQ8KXIu/+qPMieavSlSzKm9wwDwYD
VR0TAQH/BAUwAwEB/zAaBgNVHREEEzARgglsb2NhbGhvc3SHBH8AAAEwCgYIKoZI
zj0EAwIDSQAwRgIhAO5hU9QfRXK8LYP3QbNUfhmdR9gMQS3HU/WveV9veZ4RAiEA
jzh3IVZYzPO70FAsZBN75tknfIPwq/Pcv5xzRLpqYhY=
-----END CERTIFICATE-----
`;
const KEY = `-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgCVIesGwdY2S/RxNW
i2l2b79oAAguz41CMwXtGHfYQy+hRANCAARQ8i8oBhVIRXaJHgn4HV0PPGxsu31t
172RAkySeVKO9nt/Bvzc13JOC+SMv3EHBve9kYPhAB1hZjjMso0DhITJ
-----END PRIVATE KEY-----
`;
const KEY2 = `-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgLYBhjJVRuo9S+oT6
IOf2Zhlu808BK6gTCm+BVS9TwN6hRANCAAQCyio9kThAXgq3ut+ephOmiekQqxjI
NBWXUvx3ttWVLxDN+KWOyLo0/SNxO9Qtefw6q0KcMjG+aqR91rtXQP8K
-----END PRIVATE KEY-----
`;
'''

TLS_HELPERS = PEMS + r'''const tls = require('node:tls');
const net = require('node:net');
const once = (em, ev) => new Promise((resolve) => em.once(ev, (...a) => resolve(a)));
// Keep only the deterministic head of a TLS error message (drop the OpenSSL error-queue detail).
const tlsMsg = (m) => String(m).replace(/ \(SSL error [\s\S]*$/, '').replace(/^(invalid PEM|TLS certificate\/private key configuration failed): [\s\S]*$/, '$1');
// A TLS server whose handshake failures can be awaited one by one.
const failingServer = async (options, listenArgs = [0, '127.0.0.1']) => {
  const server = tls.createServer(options);
  const queue = [], waiters = [];
  server.on('tlsClientError', (e) => { const m = e.name + ': ' + tlsMsg(e.message); if (waiters.length) waiters.shift()(m); else queue.push(m); });
  server.nextError = () => queue.length ? Promise.resolve(queue.shift()) : new Promise((r) => waiters.push(r));
  server.listen(...listenArgs);
  await once(server, 'listening');
  return server;
};
// One client attempt: the event sequence until 'close' (a successful handshake is destroyed at once).
const attempt = (...args) => new Promise((resolve) => {
  const c = tls.connect(...args);
  const ev = [];
  c.on('secureConnect', () => { ev.push('secureConnect authorized=' + c.authorized + ' alpn=' + c.alpnProtocol); c.destroy(); });
  c.on('error', (e) => ev.push(e.name + ': ' + tlsMsg(e.message)));
  c.on('close', (hadError) => { ev.push('close hadError=' + hadError); resolve(ev.join(' -> ')); });
});
'''


def test_tls_handshake_alpn_and_socket_fields(run, workdir):
    """CATCHES: a tls.createServer/tls.connect pair that cannot complete a TLSv1.2/1.3 handshake over
    loopback with an in-memory PEM certificate, wrong ALPN negotiation (server preference order wins,
    no overlap -> false on both ends, Buffer protocol names accepted), wrong pre-connect state
    (connecting/pending/servername defaulting to the host), client sockets reporting authorized=true or
    a different authorizationError when rejectUnauthorized is false, server-side sockets not reporting
    authorized=true, wrong remote/local address and port pairing, getCipher() shape, getConnections()
    counts, or a client destroy() not delivering 'end' then 'close' to the server socket. Also pins
    reference quirks: server sockets stay destroyed=false after closing and server.address() keeps
    returning the old address after close()."""
    check_script(run, workdir, G, "tls_handshake_alpn_and_socket_fields", TLS_HELPERS + r'''
let onServerSocket;
const server = tls.createServer({ cert: CERT, key: KEY, ALPNProtocols: ['h2', 'http/1.1'] }, (sock) => onServerSocket(sock));
server.on('tlsClientError', (e) => console.log('unexpected tlsClientError', e.message));
console.log('before listen', server.listening, JSON.stringify(server.address()), server instanceof tls.Server);
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const P = (v) => String(v).replaceAll(String(port), 'PORT');
  console.log('listening', P(JSON.stringify(server.address())), server.listening);
  const round = async (label, opts) => {
    const serverSock = new Promise((r) => { onServerSocket = r; });
    const c = tls.connect({ port, host: '127.0.0.1', rejectUnauthorized: false, ...opts });
    console.log(label, 'pre-connect', c.connecting, c.pending, c.encrypted, JSON.stringify(c.servername), c.authorized, JSON.stringify(c.address()), c.alpnProtocol, c instanceof tls.TLSSocket);
    await once(c, 'secureConnect');
    const s = await serverSock;
    const cipher = c.getCipher();
    console.log(label, 'client', c.connecting, c.pending, c.authorized, c.authorizationError, JSON.stringify(c.alpnProtocol), JSON.stringify(c.servername),
      c.remoteAddress, c.remotePort === port, typeof c.localPort, /^TLSv1\.[23]$/.test(c.getProtocol()), Object.keys(cipher).join('/'),
      cipher.name === cipher.standardName, cipher.version === c.getProtocol(), P(JSON.stringify({ ...c.address(), port: typeof c.address().port })));
    console.log(label, 'server', s.encrypted, s.authorized, s.authorizationError, JSON.stringify(s.alpnProtocol), s.remoteAddress,
      s.remotePort === c.localPort, s.localPort === port, s.getProtocol() === c.getProtocol(), s.getCipher().name === cipher.name, s.bytesRead, s.bytesWritten);
    console.log(label, 'connections', JSON.stringify(await new Promise((r) => server.getConnections((err, n) => r([err, n])))));
    const ev = [];
    s.on('end', () => ev.push('server end'));
    s.resume();
    const serverClosed = new Promise((r) => s.on('close', (h) => { ev.push('server close hadError=' + h); r(); }));
    const clientClosed = once(c, 'close');
    c.destroy();
    console.log(label, 'destroyed', c.destroyed, JSON.stringify(c.address()), 'client close hadError=' + (await clientClosed)[0]);
    await serverClosed;
    console.log(label, ev.join(', '), 'server socket destroyed=' + s.destroyed);
  };
  await round('A', { ALPNProtocols: ['http/1.1', 'h2'] });
  await round('B', { ALPNProtocols: ['spdy/3', Buffer.from('http/1.1')], servername: 'localhost' });
  await round('C', { ALPNProtocols: ['spdy/3'] });
  await round('D', {});
  console.log('connections after all closed', JSON.stringify(await new Promise((r) => server.getConnections((err, n) => r([err, n])))));
  server.close(() => console.log('server closed', server.listening, P(JSON.stringify(server.address()))));
});
''', filename="tls_handshake_alpn_and_socket_fields.cjs")


def test_tls_handshake_failures_and_config_errors(run, workdir):
    """CATCHES: tls servers that listen without cert/key (TypeError expected) or report a busy port
    differently ('TLS listen: Address already in use (os error 98)'), servers that do not surface bad
    PEM certificates/keys, key/certificate mismatches or over-long ALPN names as 'tlsClientError' (with
    the client's handshake failing), clients that accept over-long ALPN names or a NUL in servername,
    verify the self-signed certificate successfully by default, connect to non-TLS peers, or report
    refused connections / invalid ports with other messages; also checks that the secureContext / Buffer
    / array option forms and listen() on 0.0.0.0 work, that closing a never-listened server still calls
    back, and pins the quirk that tls.connect(port, host, options) ignores the third argument."""
    check_script(run, workdir, G, "tls_handshake_failures_and_config_errors", TLS_HELPERS + r'''
(async () => {
  for (const [label, opts] of [['no options', {}], ['cert only', { cert: CERT }], ['key only', { key: KEY }]]) {
    try { tls.createServer(opts).listen(0, '127.0.0.1'); console.log(label, 'listened?!'); } catch (e) { console.log(label, '->', e.name + ': ' + e.message); }
  }
  const holder = net.createServer();
  holder.listen(0, '127.0.0.1');
  await once(holder, 'listening');
  try { tls.createServer({ cert: CERT, key: KEY }).listen(holder.address().port, '127.0.0.1'); } catch (e) { console.log('busy port ->', e.name + ': ' + e.message); }
  holder.close();
  for (const port of [70000, -1, 'abc', 1.5]) {
    try { tls.connect({ port, host: '127.0.0.1' }); } catch (e) { console.log('port', JSON.stringify(port), '->', e.name + ': ' + e.message); }
  }
  console.log('refused ->', await attempt({ port: 1, host: '127.0.0.1', rejectUnauthorized: false }));

  const good = await failingServer({ cert: CERT, key: KEY });
  const gp = good.address().port;
  const both = async (label, ...args) => {
    const [client, server] = await Promise.all([attempt(...args), good.nextError()]);
    console.log(label, '-> client:', client, '| server:', server);
  };
  await both('client ALPN name of 300 bytes', { port: gp, host: '127.0.0.1', rejectUnauthorized: false, ALPNProtocols: ['x'.repeat(300)] });
  await both('NUL in servername', { port: gp, host: '127.0.0.1', rejectUnauthorized: false, servername: 'a\u0000b' });
  await both('default verification', { port: gp, host: '127.0.0.1' });
  await both('verification for localhost', { port: gp, host: '127.0.0.1', servername: 'localhost', rejectUnauthorized: true });
  await both('options as third argument', gp, '127.0.0.1', { rejectUnauthorized: false });
  const raw = net.connect(gp, '127.0.0.1', () => raw.end('GET / HTTP/1.0\r\n\r\n'));
  raw.on('error', () => {});
  const [rawClosed, rawServer] = await Promise.all([once(raw, 'close'), good.nextError()]);
  console.log('plain-text client -> server:', rawServer, '| raw socket closed', rawClosed.length);
  good.close();

  for (const [label, opts] of [['key does not match cert', { cert: CERT, key: KEY2 }], ['cert is not PEM', { cert: 'not a pem', key: KEY }],
                               ['key is not PEM', { cert: CERT, key: Buffer.from('junk') }], ['server ALPN name of 300 bytes', { cert: CERT, key: KEY, ALPNProtocols: ['y'.repeat(300)] }]]) {
    const bad = await failingServer(opts);
    const [client, server] = await Promise.all([attempt({ port: bad.address().port, host: '127.0.0.1', rejectUnauthorized: false }), bad.nextError()]);
    console.log(label, '-> client:', client, '| server:', server);
    bad.close();
  }

  const plain = net.createServer((s) => { s.on('error', () => {}); s.end('HTTP/1.1 400 Bad Request\r\n\r\n'); });
  plain.listen(0, '127.0.0.1');
  await once(plain, 'listening');
  console.log('non-TLS server ->', await attempt({ port: plain.address().port, host: '127.0.0.1', rejectUnauthorized: false }));
  plain.close();

  const ctxServer = await failingServer({ secureContext: tls.createSecureContext({ cert: [Buffer.from(CERT)], key: [Buffer.from(KEY)] }) }, [{ port: 0, host: '127.0.0.1' }]);
  console.log('secureContext + array/Buffer forms ->', await attempt({ port: ctxServer.address().port, host: '127.0.0.1', rejectUnauthorized: false }));
  ctxServer.close();
  const anyServer = await failingServer({ cert: CERT, key: KEY }, []);
  console.log('listen() with no arguments binds', anyServer.address().address, anyServer.address().family);
  console.log('connect via 127.0.0.1 ->', await attempt(anyServer.address().port, { host: '127.0.0.1', rejectUnauthorized: false }));
  anyServer.close(() => console.log('0.0.0.0 server closed'));
  await once(anyServer, 'close');
  const never = tls.createServer({ cert: CERT, key: KEY });
  never.close(() => console.log('close() of a server that never listened calls back'));
})();
''', filename="tls_handshake_failures_and_config_errors.cjs")


def test_tls_verifying_https_clients_reject_self_signed(run, workdir):
    """CATCHES: fetch, node:https, a wss:// WebSocket or an https:// EventSource that do not verify the
    server certificate (a self-signed one must be rejected), report the failure with a different shape
    (fetch/https: TypeError "fetch '<url>': TLS handshake failed ..."; WebSocket: error then close 1006
    with wasClean=false; EventSource: a retriable error in CONNECTING state that close() ends), or that
    do not abort the handshake with an alert the TLS server reports as a tlsClientError."""
    check_script(run, workdir, G, "tls_verifying_https_clients_reject_self_signed", TLS_HELPERS + r'''
const https = require('node:https');
(async () => {
  const server = await failingServer({ cert: CERT, key: KEY });
  server.on('secureConnection', () => console.log('unexpected secure connection'));
  const port = server.address().port;
  const P = (v) => tlsMsg(String(v).replaceAll(String(port), 'PORT'));
  const step = async (label, run) => {
    const [client, srv] = await Promise.all([run(), server.nextError()]);
    console.log(label, '-> client:', client, '| server:', srv);
  };
  await step('fetch', async () => {
    try { await fetch(`https://127.0.0.1:${port}/x?y=1`); return 'resolved?!'; } catch (e) { return `${e.name}: ${P(e.message)}`; }
  });
  await step('https.get', () => new Promise((resolve) => {
    const req = https.get(`https://127.0.0.1:${port}/h`, () => resolve('response?!'));
    req.on('error', (e) => resolve(`error ${e.name}: ${P(e.message)}`));
  }));
  await step('WebSocket wss', () => new Promise((resolve) => {
    const ws = new WebSocket(`wss://127.0.0.1:${port}/sock`);
    const ev = [];
    ws.onopen = () => ev.push('open?!');
    ws.onerror = (e) => ev.push(`${e.type} readyState=${ws.readyState}`);
    ws.onclose = (e) => { ev.push(`close ${e.code} ${JSON.stringify(e.reason)} wasClean=${e.wasClean} readyState=${ws.readyState}`); resolve(ev.join(' -> ')); };
  }));
  await step('EventSource https', () => new Promise((resolve) => {
    const es = new EventSource(`https://127.0.0.1:${port}/events`);
    es.onopen = () => resolve('open?!');
    es.onerror = (e) => { const before = es.readyState; es.close(); resolve(`${e.type} readyState=${before}, after close() ${es.readyState}`); };
  }));
  server.close(() => console.log('server closed'));
})();
''', filename="tls_verifying_https_clients_reject_self_signed.cjs")


def test_tls_module_helpers_and_unconnected_sockets(run, workdir):
    """CATCHES: tls.checkServerIdentity with wrong RFC 6125 matching (case-insensitive DNS names, a
    wildcard covering exactly one leftmost label, IP literals only against 'IP Address' entries, CN
    fallback only without SAN names) or a wrong ERR_TLS_CERT_ALTNAME_INVALID error shape (message,
    reason, host, cert); convertALPNProtocols producing a wrong length-prefixed encoding; wrong
    getCiphers()/DEFAULT_* constants/rootCertificates/createSecureContext shapes or module keys; an
    unconnected TLSSocket with wrong defaults or getters; wrapping an already-connected net.Socket not
    throwing the reference's error; and a write before the handshake not failing with 'TLS socket is
    not connected' (the later handshake error is still emitted, then close(hadError=true))."""
    check_script(run, workdir, G, "tls_module_helpers_and_unconnected_sockets", TLS_HELPERS + r'''
let cert;
const showErr = (v) => v === undefined ? 'ok' : `${v.name} [${v.code}] ${v.message} | reason=${v.reason} | host=${v.host} | cert kept=${v.cert === cert}`;
for (const [host, c] of [
  ['example.com', { subjectaltname: 'DNS:example.com, DNS:www.example.com' }],
  ['WWW.Example.COM', { subjectaltname: 'DNS:www.example.com' }],
  ['a.example.com', { subjectaltname: 'DNS:*.example.com' }],
  ['a.b.example.com', { subjectaltname: 'DNS:*.example.com' }],
  ['example.com', { subjectaltname: 'DNS:*.example.com' }],
  ['10.0.0.1', { subjectaltname: 'DNS:example.com, IP Address:10.0.0.1' }],
  ['10.0.0.2', { subjectaltname: 'DNS:10.0.0.2, IP Address:10.0.0.1' }],
  ['localhost', { subject: { CN: 'localhost' } }],
  ['other', { subject: { CN: ['a', 'other'] } }],
  ['nope', { subject: { CN: 'localhost' } }],
  ['x.test', { subjectaltname: 'DNS:y.test', subject: { CN: 'x.test' } }],
  ['x.test', { subjectaltname: 'URI:http://x.test', subject: { CN: 'x.test' } }],
  ['x', {}],
  ['x', undefined],
]) { cert = c; console.log('checkServerIdentity', host, '->', showErr(tls.checkServerIdentity(host, c))); }
const ctx = {};
tls.convertALPNProtocols(['h2', 'http/1.1', 'é'], ctx); console.log('alpn array', JSON.stringify([...ctx.ALPNProtocols]), Buffer.isBuffer(ctx.ALPNProtocols));
tls.convertALPNProtocols(new Uint8Array([2, 104, 50]), ctx); console.log('alpn bytes', JSON.stringify([...ctx.ALPNProtocols]));
tls.convertALPNProtocols('h2', ctx); console.log('alpn string', JSON.stringify([...ctx.ALPNProtocols]));
console.log('alpn without context', tls.convertALPNProtocols(['x']));
const ciphers = tls.getCiphers();
console.log('ciphers', ciphers.length, ciphers.includes('tls_aes_256_gcm_sha384'), ciphers.every((c) => c === c.toLowerCase()), ciphers === tls.getCiphers(), JSON.stringify(ciphers.slice(0, 3)));
console.log('constants', tls.DEFAULT_MIN_VERSION, tls.DEFAULT_MAX_VERSION, tls.DEFAULT_ECDH_CURVE, tls.CLIENT_RENEG_LIMIT, tls.CLIENT_RENEG_WINDOW, tls.DEFAULT_CIPHERS.split(':').slice(0, 3).join(':'));
console.log('roots', JSON.stringify(tls.rootCertificates), Object.isFrozen(tls.rootCertificates), JSON.stringify(tls.getCACertificates()));
const sc = tls.createSecureContext({ cert: 'C', key: 'K', ALPNProtocols: ['h2'] });
console.log('secure context', sc instanceof tls.SecureContext, JSON.stringify(sc), JSON.stringify(new tls.SecureContext()));
try { tls.createSecurePair(); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log('keys', Object.keys(tls).sort().join());
const srv = tls.createServer({ cert: 'x', key: 'y' }, () => {});
console.log('server', srv.listenerCount('secureConnection'), srv.listening, srv.address(), JSON.stringify(srv.options), srv.ref() === srv, srv.unref() === srv);

const fresh = new tls.TLSSocket();
console.log('fresh socket', fresh.encrypted, fresh.authorized, fresh.authorizationError, fresh.pending, fresh.connecting, fresh.alpnProtocol, fresh.servername,
  JSON.stringify(fresh.address()), fresh.getProtocol(), fresh.getCipher(), JSON.stringify(fresh.getPeerCertificate()), JSON.stringify(fresh.getCertificate()),
  fresh.getSession(), fresh.isSessionReused(), fresh.getFinished(), fresh.getPeerFinished(), fresh.setMaxSendFragment(16384), fresh.ref() === fresh, fresh.unref() === fresh,
  fresh instanceof require('node:stream').Duplex);
fresh.setServername('example.test');
console.log('setServername', fresh.servername, 'renegotiate', fresh.renegotiate({}, (e) => console.log('renegotiate callback', e.message)));

const plain = net.createServer((s) => { s.on('error', () => {}); s.end(); });
plain.listen(0, '127.0.0.1', () => {
  const c = net.connect(plain.address().port, '127.0.0.1', async () => {
    try { new tls.TLSSocket(c); console.log('wrapped?!'); } catch (e) { console.log('wrap connected net.Socket ->', e.name + ': ' + e.message); }
    try { tls.connect({ socket: c }); console.log('upgraded?!'); } catch (e) { console.log('tls.connect({ socket }) ->', e.name + ': ' + e.message); }
    c.destroy();
    plain.close();
    const server = await failingServer({ cert: CERT, key: KEY });
    const early = tls.connect({ port: server.address().port, host: '127.0.0.1' });
    const ev = [];
    early.write('too early', (err) => ev.push('write callback: ' + (err && err.message)));
    early.on('error', (e) => ev.push('error: ' + tlsMsg(e.message)));
    const [hadError] = await once(early, 'close');
    console.log('write before handshake ->', ev.join(' -> '), '-> close hadError=' + hadError, 'destroyed=' + early.destroyed);
    console.log('server saw', await server.nextError());
    server.close();
  });
});
''', filename="tls_module_helpers_and_unconnected_sockets.cjs")


def test_tls_upgrade_of_unix_socket_is_rejected(run, workdir):
    """CATCHES: new tls.TLSSocket(socket) inside a net.Server 'connection' handler not reporting its
    initial state (connecting, raw socket marked destroyed at once), or a unix-domain socket being
    upgradable: the reference fails with 'Unix sockets cannot be upgraded to TLS', emitting the error
    and then close(hadError=true), and the unix client sees its connection closed."""
    check_script(run, workdir, G, "tls_upgrade_of_unix_socket", TLS_HELPERS + r'''
(async () => {
  const unixEvents = [];
  let unixDone;
  const unixFinished = new Promise((r) => { unixDone = r; });
  const us = net.createServer((sock) => {
    const secure = new tls.TLSSocket(sock, { rejectUnauthorized: false });
    unixEvents.push(`upgrade started connecting=${secure.connecting} raw destroyed=${sock.destroyed}`);
    secure.on('error', (e) => unixEvents.push(`${e.name}: ${e.message}`));
    secure.on('close', (hadError) => { unixEvents.push('close hadError=' + hadError); unixDone(); });
  });
  us.listen('upgrade.sock');
  await once(us, 'listening');
  const uc = net.connect('upgrade.sock');
  uc.on('error', () => {});
  await Promise.all([unixFinished, once(uc, 'close')]);
  console.log('unix socket:', unixEvents.join(' -> '));
  us.close();
  console.log('done');
})();
''', filename="tls_upgrade_of_unix_socket.cjs")


FFI_HELPERS = r'''const ffi = require('bun:ffi');
const { dlopen, FFIType, ptr, CString, read, toArrayBuffer, toBuffer, JSCallback, CFunction, linkSymbols, viewSource } = ffi;
const show = (v) => typeof v === 'bigint' ? v + 'n' : v === undefined ? 'undefined' : typeof v === 'number' && !Number.isFinite(v) ? String(v)
  : Array.isArray(v) ? '[' + v.map(show).join(', ') + ']' : JSON.stringify(v);
const t = (label, f) => { try { console.log(label, '->', show(f())); } catch (e) { console.log(label, 'THREW', e instanceof Error ? e.name + ': ' + e.message : 'non-error ' + String(e)); } };
const cs = (s) => Buffer.from(s + '\0'); // NUL-terminated C string in a Buffer
'''


def test_ffi_libc_integer_marshalling(run, workdir):
    """CATCHES: bun:ffi dlopen/call marshalling wrong for libc integer functions: usize/u64/i64 returns
    must be BigInt (i64_fast/u64_fast plain numbers), narrow returns (i8/u8/i16/u16/u32/char) must be
    truncated and sign-extended per declared width, arguments truncated to the declared width (200 as
    i8), missing arguments passed as 0, fractional numbers truncated for 32-bit ints but rejected for
    64-bit ints ('Not an integer'), BigInt arguments for i64, string arguments coerced for ints, bool
    returns taken from the low bit only (2 -> false), cstring/buffer parameters, aliases via `name`,
    numeric FFIType codes, void returns, and the exact TypeErrors for strings/BigInts/objects used as
    pointers."""
    check_script(run, workdir, G, "ffi_libc_integer_marshalling", FFI_HELPERS + r'''
const libc = dlopen('libc.so.6', {
  strlen: { args: ['ptr'], returns: 'usize' },
  strlen32: { name: 'strlen', args: [FFIType.buffer], returns: FFIType.u32 },
  abs: { args: ['i32'], returns: 'i32' },
  abs8: { name: 'abs', args: ['i8'], returns: 'i8' },
  absU8: { name: 'abs', args: [FFIType.int], returns: FFIType.u8 },
  absBool: { name: 'abs', args: ['int'], returns: 'bool' },
  labs: { args: ['i64'], returns: 'i64' },
  labsFast: { name: 'labs', args: ['i64_fast'], returns: 'i64_fast' },
  toupper: { args: ['int'], returns: 'char' },
  atoi: { args: ['cstring'], returns: 'int' },
  strcmp: { args: ['ptr', 'ptr'], returns: 'i32' },
  strtoull: { args: ['ptr', 'ptr', 'i32'], returns: 'u64' },
  strtoullI64: { name: 'strtoull', args: ['ptr', 'ptr', 'i32'], returns: 'i64' },
  strtoullFast: { name: 'strtoull', args: ['ptr', 'ptr', 'i32'], returns: 'u64_fast' },
  strtoullU32: { name: 'strtoull', args: ['ptr', 'ptr', 'i32'], returns: 'u32' },
  strtoullU16: { name: 'strtoull', args: ['ptr', 'ptr', 'i32'], returns: 'u16' },
  strtoullI16: { name: 'strtoull', args: ['ptr', 'ptr', 'i32'], returns: 'i16' },
  free: { args: ['ptr'], returns: 'void' },
  noReturnsKey: { name: 'free', args: ['ptr'] },
  strlenUnknownCode: { name: 'strlen', args: ['ptr'], returns: 99 },
});
const s = libc.symbols;
console.log('symbols', Object.keys(s).join(','), typeof s.abs);
t('strlen("hello")', () => s.strlen(cs('hello')));
t('strlen("") as u32 via buffer type', () => s.strlen32(cs('')));
t('strlen(utf-8 bytes)', () => s.strlen32(cs('héllo')));
t('abs(-42)', () => s.abs(-42));
t('abs() missing arg', () => s.abs());
t('abs(-3.9)', () => s.abs(-3.9));
t('abs("-17")', () => s.abs('-17'));
t('abs(2**32 + 5)', () => s.abs(2 ** 32 + 5));
t('abs as i8 (200)', () => s.abs8(200));
t('abs as u8 (-3)', () => s.absU8(-3));
t('abs as bool (2, 3, 0)', () => [s.absBool(2), s.absBool(3), s.absBool(0)]);
t('labs(-(2n**40n))', () => s.labs(-(2n ** 40n)));
t('labs(-12)', () => s.labs(-12));
t('labs(1.5)', () => s.labs(1.5));
t('labs(Infinity)', () => s.labs(Infinity));
t('labs i64_fast', () => s.labsFast(-7));
t('toupper(97) as char', () => s.toupper(97));
t('toupper(353) wraps to char', () => s.toupper(353));
t('toupper(255)', () => s.toupper(255));
t('atoi("  -1234xyz")', () => s.atoi(cs('  -1234xyz')));
t('strcmp signs', () => [Math.sign(s.strcmp(cs('abc'), cs('abd'))), s.strcmp(cs('same'), cs('same')), Math.sign(s.strcmp(cs('b'), cs('a')))]);
t('strtoull u64 max', () => s.strtoull(cs('18446744073709551615'), null, 10));
t('strtoull as i64', () => s.strtoullI64(cs('18446744073709551615'), null, 10));
t('strtoull as u64_fast', () => s.strtoullFast(cs('9007199254740993'), null, 10));
t('strtoull 2^32+1 as u32', () => s.strtoullU32(cs('4294967297'), null, 10));
t('strtoull 65535 as u16 / i16', () => [s.strtoullU16(cs('65535'), null, 10), s.strtoullI16(cs('65535'), null, 10)]);
t('strtoull hex', () => s.strtoull(cs('ff'), undefined, 16));
t('free(null) void', () => s.free(null));
t('default return type is void', () => s.noReturnsKey(null));
t('string as pointer', () => s.strlen('abc'));
t('bigint as pointer', () => s.strlen(5n));
t('object as pointer', () => s.strlen({}));
t('array as pointer', () => s.strlen([1, 2]));
t('string as cstring', () => s.atoi('12'));
t('boolean as pointer is NULL', () => s.strtoull(cs('77'), true, 10));
t('unknown numeric return code', () => s.strlenUnknownCode(cs('hello')));
libc.close();
''', filename="ffi_libc_integer_marshalling.cjs")


def test_ffi_pointers_memory_and_cstrings(run, workdir):
    """CATCHES: ptr() not returning the typed array's data address (byteOffset honoured for offsets,
    subarrays and other views; ArrayBuffer/DataView/number rejected with the reference message), native
    writes (memset/memcpy) not landing in the JS buffer, ptr/cstring returns wrong (pointer arithmetic
    relative to the buffer, NULL -> null for ptr and an empty CString for cstring), read.* reading the
    wrong width/sign/endianness or ignoring the offset, CString not decoding UTF-8 up to the NUL or an
    explicit length (and its arrayBuffer getter), and toArrayBuffer/toBuffer not returning copies."""
    check_script(run, workdir, G, "ffi_pointers_memory_and_cstrings", FFI_HELPERS + r'''
const libc = dlopen('libc.so.6', {
  strchr: { args: ['ptr', 'i32'], returns: 'cstring' },
  strchrPtr: { name: 'strchr', args: ['ptr', 'i32'], returns: 'ptr' },
  memset: { args: ['ptr', 'i32', 'usize'], returns: 'ptr' },
  memcpy: { args: ['ptr', 'ptr', 'usize'], returns: 'void' },
});
const s = libc.symbols;
const hw = cs('hello world');
const base = ptr(hw);
const r = s.strchr(hw, 'w'.charCodeAt(0));
t('strchr -> CString', () => [String(r), r instanceof CString, r instanceof String, r.length, typeof r.ptr, r.ptr - base, r.byteOffset, r.byteLength]);
t('strchr miss -> CString', () => { const n = s.strchr(hw, 'z'.charCodeAt(0)); return [String(n), n.ptr, n.length]; });
t('strchr as ptr', () => s.strchrPtr(hw, 'o'.charCodeAt(0)) - base);
t('strchr miss as ptr', () => s.strchrPtr(hw, 'z'.charCodeAt(0)));
const b = Buffer.alloc(8, 46);
t('memset returns its first argument', () => s.memset(b, 65, 3) === ptr(b));
t('memset wrote into the Buffer', () => b.toString());
const dst = new Uint8Array(6);
s.memcpy(dst, cs('xyzzy'), 5);
t('memcpy', () => [...dst]);
const big = new Uint8Array(10);
s.memcpy(big.subarray(4), cs('QQ'), 2);
t('memcpy into subarray', () => [...big]);
const words = new Uint16Array(4);
s.memset(ptr(words, 2), 255, 4);
t('memset through ptr(view, 2)', () => [...words]);
const bytes = new Uint8Array([0x01, 0x80, 0xff, 0x7f, 0x00, 0x00, 0xc0, 0x3f, 0, 0, 0, 0, 0, 0, 0xf0, 0xbf, 0x68, 0x69, 0xc3, 0xa9, 0, 0x7a]);
const p = ptr(bytes);
t('ptr offsets', () => [ptr(bytes, 3) - p, ptr(bytes.subarray(5)) - p, ptr(new Uint16Array(bytes.buffer, 2, 2)) - p, ptr(new Float64Array(bytes.buffer, 8, 1), 1) - p]);
t('ptr(ArrayBuffer)', () => ptr(new ArrayBuffer(4)));
t('ptr(DataView)', () => ptr(new DataView(new ArrayBuffer(4))));
t('ptr(number)', () => ptr(5));
t('read u8/i8/u16/i16', () => [read.u8(p), read.i8(p, 1), read.u16(p, 1), read.i16(p, 1), read.u8(p, 2), read.i8(p, 2)]);
t('read u32/i32', () => [read.u32(p), read.i32(p), read.u32(p, 1), read.i32(p, 1)]);
t('read f32/f64', () => [read.f32(p, 4), read.f64(p, 8)]);
t('read u64/i64', () => [read.u64(p), read.i64(p, 8), read.u64(p, 8)]);
t('read ptr/intptr agree', () => [read.ptr(p, 14) === read.intptr(p, 14), typeof read.ptr(p)]);
t('read with string pointer', () => read.u8('x'));
t('CString NUL-terminated', () => { const c = new CString(p, 16); return [String(c), c.length, c.byteOffset, c.byteLength, c.ptr === p]; });
t('CString explicit length', () => { const c = new CString(p, 16, 2); return [String(c), [...new Uint8Array(c.arrayBuffer)], c.byteLength]; });
t('CString.arrayBuffer without length', () => new CString(p, 16).arrayBuffer);
t('CString(null)', () => { const c = new CString(null); return [String(c), c.ptr, c.byteOffset, c.byteLength]; });
t('CString string methods', () => new CString(p, 16) + '!' + new CString(p, 21).toUpperCase() + new CString(p, 16).slice(1));
t('toArrayBuffer', () => { const ab = toArrayBuffer(p, 16, 4); return [ab instanceof ArrayBuffer, ab.byteLength, [...new Uint8Array(ab)]]; });
t('toArrayBuffer is a copy', () => { const ab = toArrayBuffer(p, 0, 2); bytes[0] = 9; return [new Uint8Array(ab)[0], bytes[0]]; });
t('toArrayBuffer empty cases', () => [toArrayBuffer(p).byteLength, toArrayBuffer(null, 0, 5).byteLength]);
t('toBuffer', () => { const buf = toBuffer(p, 16, 4); return [Buffer.isBuffer(buf), buf.toString('utf8'), buf.length]; });
t('toBuffer empty', () => toBuffer(p).length);
''', filename="ffi_pointers_memory_and_cstrings.cjs")


def test_ffi_libm_float_marshalling(run, workdir):
    """CATCHES: float/double arguments and returns not passed in the floating-point registers (or with
    the wrong width: f32 values must round-trip through single precision), mixed float/int argument
    lists (ldexp, frexp with an out-pointer) mis-ordered, number coercion of string arguments, f64
    results that are NaN/infinite/subnormal mangled, and i64_fast/int returns of math functions. Only
    exactly-rounded libm functions are used (sqrt, fma, ldexp, floor, fabs, fmax, lround, ilogb)."""
    check_script(run, workdir, G, "ffi_libm_float_marshalling", FFI_HELPERS + r'''
const m = dlopen('libm.so.6', {
  sqrt: { args: ['f64'], returns: 'f64' },
  sqrtf: { args: ['f32'], returns: 'f32' },
  ldexp: { args: ['double', 'int'], returns: 'double' },
  ldexpf: { args: ['float', 'int'], returns: 'float' },
  fma: { args: ['f64', 'f64', 'f64'], returns: 'f64' },
  fabsf: { args: ['f32'], returns: 'f32' },
  frexp: { args: ['f64', 'ptr'], returns: 'f64' },
  floor: { args: [FFIType.double], returns: FFIType.double },
  fmaxf: { args: ['float', 'float'], returns: 'float' },
  lround: { args: ['f64'], returns: 'i64_fast' },
  lroundBig: { name: 'lround', args: ['f64'], returns: 'i64' },
  ilogb: { args: ['f64'], returns: 'int' },
  copysign: { args: ['f64', 'f64'], returns: 'f64' },
});
const s = m.symbols;
t('sqrt', () => [s.sqrt(2.25), s.sqrt(-1), s.sqrt('16'), s.sqrt(Infinity), s.sqrt(0)]);
t('sqrtf(2) single precision', () => s.sqrtf(2));
t('ldexp', () => [s.ldexp(3, 4), s.ldexp(1, -1074), s.ldexp(1, 1024), s.ldexp(-0.75, '2')]);
t('ldexpf', () => s.ldexpf(1.5, 3));
t('fma(2, 3, 4)', () => s.fma(2, 3, 4));
t('fabsf(-0.1)', () => s.fabsf(-0.1));
const exp = new Int32Array(1);
t('frexp(48) with out-pointer', () => [s.frexp(48, exp), exp[0]]);
t('frexp(-0.375)', () => [s.frexp(-0.375, exp), exp[0]]);
t('floor', () => [s.floor(-2.5), s.floor(7.999)]);
t('fmaxf', () => [s.fmaxf(NaN, 1.25), s.fmaxf(-1, -2)]);
t('lround', () => [s.lround(2.5), s.lround(-2.5), s.lroundBig(-1e15)]);
t('ilogb', () => [s.ilogb(1024), s.ilogb(0.75)]);
t('copysign', () => [s.copysign(3, -0), Object.is(s.copysign(0, -1), -0)]);
m.close();
''', filename="ffi_libm_float_marshalling.cjs")


def test_ffi_jscallback_qsort_and_thunks(run, workdir):
    """CATCHES: JSCallback thunks that cannot be called back from native code (qsort/bsearch
    comparators receiving pointers as numbers), a JSCallback object not being rejected where its .ptr
    is required, wrong argument conversion inside callbacks (narrow ints wrapped and sign-extended,
    64-bit ints as BigInt, bool from the low bit, NULL pointers as null), wrong return conversion
    (BigInt/bool/string coercion, void -> 0, null pointer), a throwing callback not reporting
    'uncaught exception in bun:ffi JSCallback: ...' on stderr and returning 0, CFunction/linkSymbols
    over raw pointers, close() not nulling ptr / freeing the slot, the 16-slot-per-arity pool limit,
    the unsupported float/arity messages, and viewSource output."""
    check_script(run, workdir, G, "ffi_jscallback_qsort_and_thunks", FFI_HELPERS + r'''
const libc = dlopen('libc.so.6', {
  qsort: { args: ['ptr', 'usize', 'usize', 'function'], returns: 'void' },
  bsearch: { args: ['ptr', 'ptr', 'usize', 'usize', 'callback'], returns: 'ptr' },
});
const arr = new Int32Array([5, -3, 99, 0, -3, 42, -100, 7]);
const argTypes = new Set();
const cmp = new JSCallback((a, b) => { argTypes.add(typeof a + '/' + typeof b); return read.i32(a) - read.i32(b); }, { args: ['ptr', 'ptr'], returns: 'i32' });
t('JSCallback ptr', () => [typeof cmp.ptr, cmp.ptr > 0, Object.keys(cmp).join()]);
t('qsort with the JSCallback object itself', () => libc.symbols.qsort(arr, arr.length, 4, cmp));
libc.symbols.qsort(arr, arr.length, 4, cmp.ptr);
t('qsort with cmp.ptr', () => [...arr]);
t('comparator argument types', () => [...argTypes]);
const key = new Int32Array([42]);
t('bsearch hit index', () => (libc.symbols.bsearch(key, arr, arr.length, 4, cmp.ptr) - ptr(arr)) / 4);
key[0] = 8;
t('bsearch miss', () => libc.symbols.bsearch(key, arr, arr.length, 4, cmp.ptr));
cmp.close();
t('after close()', () => cmp.ptr);
cmp.close();
const temp = new JSCallback(() => 7, { returns: 'i32' });
const stalePtr = temp.ptr;
const callTemp = CFunction({ ptr: stalePtr, returns: 'i32' });
t('thunk before close', () => callTemp());
temp.close();
t('thunk after close returns 0', () => callTemp());

const seen = [];
const ints = new JSCallback((...a) => { seen.push(a.map(show).join(' ')); return -1; }, { args: ['i8', 'u8', 'i16', 'u16', 'i32', 'u32', 'i64', 'u64'], returns: 'i32' });
const callInts = CFunction({ ptr: ints.ptr, args: ['i8', 'u8', 'i16', 'u16', 'i32', 'u32', 'i64', 'u64'], returns: 'i32' });
t('8 integer args', () => callInts(-1, 255, -300, 65535, -5, 4294967295, -(2n ** 63n), 2n ** 64n - 1n));
t('8 integer args (wrapping)', () => callInts(255, 256, 40000, -1, 2 ** 31, -1, 5, 7));
t('callback saw', () => seen.splice(0));
const kinds = new JSCallback((...a) => { seen.push(a.map((v) => typeof v === 'number' && v > 1e6 ? 'ADDR' : show(v)).join(' ')); return true; },
  { args: ['ptr', 'bool', 'char', 'cstring', 'u64_fast', 'i64_fast'], returns: 'bool' });
const callKinds = CFunction({ ptr: kinds.ptr, args: ['ptr', 'bool', 'char', 'ptr', 'u64', 'i64'], returns: 'u8' });
t('pointer/bool/char/fast args', () => [callKinds(null, true, 200, null, 1n, -1n), callKinds(new Uint8Array(1), 2, -1, null, 0, 0)]);
t('callback saw', () => seen.splice(0));
const ret = (fn, def, as) => CFunction({ ptr: new JSCallback(fn, def).ptr, returns: as })();
t('i64 return -2n', () => [ret(() => -2n, { returns: 'i64' }, 'i64'), ret(() => -2n, { returns: 'i64' }, 'u64')]);
t('bool/string/null returns', () => [ret(() => true, { returns: 'i32' }, 'i32'), ret(() => '17', { returns: 'i32' }, 'i32'), ret(() => null, { returns: 'ptr' }, 'ptr'), ret(() => 3.9, { returns: 'u8' }, 'u8')]);
t('void callback returns 0', () => ret(() => 123, {}, 'i32'));
t('throwing callback', () => ret(() => { throw new Error('boom'); }, { returns: 'i32' }, 'i32'));
const answer = new JSCallback(() => 42n, { returns: 'i64' });
const linked = linkSymbols({ answer: { ptr: answer.ptr, returns: 'i64_fast' }, nothing: { ptr: answer.ptr } });
t('linkSymbols', () => [linked.symbols.answer(), linked.symbols.nothing(), linked.close(), Object.keys(linked).join()]);
t('native.callback', () => typeof ffi.native.callback(() => 1, { returns: 'i32' }).ptr);
t('float argument', () => new JSCallback(() => 0, { args: ['f64'] }));
t('float return', () => new JSCallback(() => 0, { returns: 'float' }));
t('not a function', () => new JSCallback(42, {}));
t('9 arguments', () => new JSCallback(() => 0, { args: Array(9).fill('i32') }));
t('unknown type', () => new JSCallback(() => 0, { args: ['quux'] }));
t('call with 9 arguments', () => CFunction({ ptr: answer.ptr, args: Array(9).fill('i32') })(1, 2, 3, 4, 5, 6, 7, 8, 9));
const pool = [];
t('pool of arity 3', () => { for (let i = 0; i < 20; i++) pool.push(new JSCallback(() => 0, { args: ['i32', 'i32', 'i32'] })); });
t('created before exhaustion', () => pool.length);
pool.forEach((c) => c.close());
t('slot reusable after close', () => typeof new JSCallback(() => 0, { args: ['i32', 'i32', 'i32'] }).ptr);
t('viewSource(native)', () => viewSource(callInts).replace(/0x[0-9a-f]+/, '0xADDR'));
t('viewSource(js)', () => viewSource(function f(a) { return a; }));
t('viewSource(5)', () => viewSource(5));
''', filename="ffi_jscallback_qsort_and_thunks.cjs", stderr="uncaught exception in bun:ffi JSCallback: Error: boom\n")


def test_ffi_module_surface_and_errors(run, workdir):
    """CATCHES: a bun:ffi module with missing exports, wrong FFIType codes or aliases (including the
    numeric self-keys), a wrong `suffix`, dlopen of a missing library or dlsym of a missing symbol not
    failing with the reference messages, unknown type names accepted, {tag} type objects or numeric
    codes rejected, close() returning something, cc() not validating its options before compiling
    (no compiler is needed for these errors), and bun:ffi being importable from ES modules (the
    reference only provides it to require(); dynamic import fails with 'module not found')."""
    check_script(run, workdir, G, "ffi_module_surface_and_errors", FFI_HELPERS + r'''
console.log('exports', Object.keys(ffi).sort().join());
console.log('suffix', ffi.suffix, 'native keys', Object.keys(ffi.native).join());
const named = Object.keys(FFIType).filter((k) => !/^\d+$/.test(k));
console.log('named types', named.map((k) => k + '=' + FFIType[k]).join(' '));
console.log('numeric keys', Object.keys(FFIType).filter((k) => /^\d+$/.test(k)).map((k) => FFIType[k]).join(','));
t('dlopen missing library', () => dlopen('libdefinitely-missing.so', {}));
t('dlsym missing symbol', () => dlopen('libc.so.6', { no_such_function_xyz: { args: [], returns: 'void' } }));
t('unknown arg type', () => dlopen('libc.so.6', { abs: { args: ['int128'], returns: 'int' } }));
t('unknown return type', () => dlopen('libc.so.6', { abs: { args: ['int'], returns: 'long double' } }));
t('null type', () => dlopen('libc.so.6', { abs: { args: [null], returns: 'int' } }));
t('{tag} type objects', () => dlopen('libc.so.6', { abs: { args: [{ tag: 'i32' }], returns: { tag: 'i32' } } }).symbols.abs(-9));
t('numeric type codes', () => dlopen('libc.so.6', { abs: { args: [5], returns: 5 } }).symbols.abs(-10));
t('empty symbol table', () => Object.keys(dlopen('libc.so.6', {}).symbols));
t('close()', () => { const l = dlopen('libc.so.6', { abs: { args: ['int'], returns: 'int' } }); return [l.symbols.abs(-1), l.close(), Object.keys(l).join()]; });
t('CFunction without ptr', () => typeof CFunction({ args: [], returns: 'void' }));
t('cc()', () => ffi.cc());
t('cc({ source: 42 })', () => ffi.cc({ source: 42 }));
t('cc missing file', () => ffi.cc({ source: 'missing.c', symbols: {} }));
t('cc missing file URL', () => ffi.cc({ source: new URL('file:///nonexistent/dir/x.c') }));
t('cc file-like object', () => ffi.cc({ source: { name: 'nope.c' } }));
import('bun:ffi').then((m) => console.log('dynamic import?!', Object.keys(m)), (e) => console.log('dynamic import ->', e.name + ': ' + e.message.replace(process.cwd(), '<cwd>')));
''', filename="ffi_module_surface_and_errors.cjs")
