"""node:tls over lumen's dlopen'd system OpenSSL (lumen-tls + the lumen-node TLS registry), and the
https/wss/EventSource clients of lumen-web that ride the same backend.

Every program starts its own TLS server on 127.0.0.1 port 0 from fixed PEM material embedded
below (a private test CA plus leaf certificates, all valid 2000-2199, so neither today's date nor
a shifted clock is near a validity bound). Clients trust the CA through OpenSSL's documented
SSL_CERT_FILE variable (a relative path into the work directory); tests that leave it unset see
the CA as unknown. Ports never reach the output (programs mask them), negotiated cipher names and
exact protocol versions are reduced to booleans, and only causally ordered events are printed per
side.

A lumen TLS socket's own pending read keeps its native stream busy, so a write only goes out once
that read ends. Programs therefore only send from the side that closes right after writing (the
destroy ends the read, the queued bytes are flushed, then close_notify), or let a lumen-web client
(fetch, WebSocket, EventSource) send the request. Two tests use a TLS peer run by the test process
itself (Python's ssl module): one that dials an accepted socket the program upgrades, and one that
forges a record after the handshake.
"""

import ctypes
import os
import socket
import ssl
import threading
import time

import pytest

from conftest import out


def _openssl_loads() -> bool:
    """lumen-tls dlopens libssl.so.3/libcrypto.so.3 at run time; without them TLS cannot work."""
    try:
        ctypes.CDLL("libcrypto.so.3")
        ctypes.CDLL("libssl.so.3")
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _openssl_loads(), reason="system OpenSSL 3 (libssl.so.3) is not loadable")


def _ipv6_loopback_works() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


needs_ipv6 = pytest.mark.skipif(not _ipv6_loopback_works(), reason="no IPv6 loopback (::1) in this environment")

TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"),
         pytest.param(("--tier=interp",), id="interp")]

TRUST = {"SSL_CERT_FILE": "ca.pem"}

# ------------------------------------------------------------------------------ PEM material
# "Lumen Test Root CA" (P-256, self-signed, CA:TRUE), valid 2000-01-01 .. 2199-11-13.
CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBpDCCAUmgAwIBAgIBATAKBggqhkjOPQQDAjA4MRswGQYDVQQDDBJMdW1lbiBU
ZXN0IFJvb3QgQ0ExGTAXBgNVBAoMEEx1bWVuIFRlc3QgU3VpdGUwIBcNMDAwMTAx
MDAwMDAwWhgPMjE5OTExMTMwMDAwMDBaMDgxGzAZBgNVBAMMEkx1bWVuIFRlc3Qg
Um9vdCBDQTEZMBcGA1UECgwQTHVtZW4gVGVzdCBTdWl0ZTBZMBMGByqGSM49AgEG
CCqGSM49AwEHA0IABNE2LA71gp+0lszdf6X3deOsrMoVdDT0luk6KrTnntIslclh
oRgCLmYueNgWXEXkC/3A/h1fM39Rws6oJMzJXtCjQjBAMA8GA1UdEwEB/wQFMAMB
Af8wDgYDVR0PAQH/BAQDAgEGMB0GA1UdDgQWBBRGfpSFVFYhsCQ098zyIoc7QULb
/jAKBggqhkjOPQQDAgNJADBGAiEAirGUSvpFgJLxE8CcINQ/eYoYPksBZEObnsVj
aLzGMM0CIQCfQwE+4Ko1L4MAe5wb4IB93WSfG9wBOysfFh/BjRa1oQ==
-----END CERTIFICATE-----
"""
# CN=localhost, SAN DNS:localhost + IP:127.0.0.1, issued by the test CA.
SERVER_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQggcRUu1kR7IOTO1Ac
yT8GOdO0sS0FB3SR+3bB4HAyAV+hRANCAATXJxopeIb0b7SqR0qQknC17YYoi4NO
G69DgiUvWEkwcXPU0o9Zo12BXvkfogdXcF3OfNIviBMqoj5u1aa0uhn0
-----END PRIVATE KEY-----
"""
SERVER_CERT = """-----BEGIN CERTIFICATE-----
MIIB6jCCAZGgAwIBAgIBAjAKBggqhkjOPQQDAjA4MRswGQYDVQQDDBJMdW1lbiBU
ZXN0IFJvb3QgQ0ExGTAXBgNVBAoMEEx1bWVuIFRlc3QgU3VpdGUwIBcNMDAwMTAx
MDAwMDAwWhgPMjE5OTExMTMwMDAwMDBaMC8xEjAQBgNVBAMMCWxvY2FsaG9zdDEZ
MBcGA1UECgwQTHVtZW4gVGVzdCBTdWl0ZTBZMBMGByqGSM49AgEGCCqGSM49AwEH
A0IABNcnGil4hvRvtKpHSpCScLXthiiLg04br0OCJS9YSTBxc9TSj1mjXYFe+R+i
B1dwXc580i+IEyqiPm7VprS6GfSjgZIwgY8wDAYDVR0TAQH/BAIwADAOBgNVHQ8B
Af8EBAMCB4AwEwYDVR0lBAwwCgYIKwYBBQUHAwEwGgYDVR0RBBMwEYIJbG9jYWxo
b3N0hwR/AAABMB8GA1UdIwQYMBaAFEZ+lIVUViGwJDT3zPIihztBQtv+MB0GA1Ud
DgQWBBR3BLpxP6jF3ZOrVHTbEGR91jZHNzAKBggqhkjOPQQDAgNHADBEAiB3vjgF
TpqUlg7AXNVzpmZxB15rNueJbdZELnMK5yJLDwIgYgN5Y6z3S8Y9xgCUTYU4d8Q7
wqYsGA3KoDIxjC8rtGo=
-----END CERTIFICATE-----
"""
# CN=other.test, SAN DNS:other.test + DNS:*.wild.test (no IP), issued by the test CA.
OTHER_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg1Go2P4ZrVLc3qcfr
yL/Hp0+XitSqLDPlN/AYebEq+YGhRANCAARO3SqjHgN2MJM2RL755TsbPgGMrF6Q
5jo3sWmlr2BtnMk8F41g5C67B19r0gnB2F4KiZtU7cK47j0m9boFAzxP
-----END PRIVATE KEY-----
"""
OTHER_CERT = """-----BEGIN CERTIFICATE-----
MIIB9TCCAZqgAwIBAgIBBDAKBggqhkjOPQQDAjA4MRswGQYDVQQDDBJMdW1lbiBU
ZXN0IFJvb3QgQ0ExGTAXBgNVBAoMEEx1bWVuIFRlc3QgU3VpdGUwIBcNMDAwMTAx
MDAwMDAwWhgPMjE5OTExMTMwMDAwMDBaMDAxEzARBgNVBAMMCm90aGVyLnRlc3Qx
GTAXBgNVBAoMEEx1bWVuIFRlc3QgU3VpdGUwWTATBgcqhkjOPQIBBggqhkjOPQMB
BwNCAARO3SqjHgN2MJM2RL755TsbPgGMrF6Q5jo3sWmlr2BtnMk8F41g5C67B19r
0gnB2F4KiZtU7cK47j0m9boFAzxPo4GaMIGXMAwGA1UdEwEB/wQCMAAwDgYDVR0P
AQH/BAQDAgeAMBMGA1UdJQQMMAoGCCsGAQUFBwMBMCIGA1UdEQQbMBmCCm90aGVy
LnRlc3SCCyoud2lsZC50ZXN0MB8GA1UdIwQYMBaAFEZ+lIVUViGwJDT3zPIihztB
Qtv+MB0GA1UdDgQWBBQcaRSdWQzeD0m1+pHT29HjQQqwJjAKBggqhkjOPQQDAgNJ
ADBGAiEAwaN6umMyi2wWxhwGoxI2g6sVm4XcE0rq0MvUSx0Weo4CIQDiRZO88juv
PMOxM4OHCgT2hVClx5LYq6U3aR6RfN1HPQ==
-----END CERTIFICATE-----
"""
# Self-signed CN=localhost (SAN DNS:localhost + IP:127.0.0.1), trusted by nobody.
SELF_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgQxp2ZOYdpiydjj3C
OWtQVihz4du27UEyjv3KIETC3yKhRANCAAQMOw4RgNiCORy1tgu6y0y8WzopRTfZ
78GAWoekzpDueHnOnnKFXZK3JI2ZsYGtDexL+m0LyPUeQgUtxiIjTqEc
-----END PRIVATE KEY-----
"""
SELF_CERT = """-----BEGIN CERTIFICATE-----
MIIBsTCCAVagAwIBAgIBAzAKBggqhkjOPQQDAjAoMRIwEAYDVQQDDAlsb2NhbGhv
c3QxEjAQBgNVBAoMCVVudHJ1c3RlZDAgFw0wMDAxMDEwMDAwMDBaGA8yMTk5MTEx
MzAwMDAwMFowKDESMBAGA1UEAwwJbG9jYWxob3N0MRIwEAYDVQQKDAlVbnRydXN0
ZWQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQMOw4RgNiCORy1tgu6y0y8Wzop
RTfZ78GAWoekzpDueHnOnnKFXZK3JI2ZsYGtDexL+m0LyPUeQgUtxiIjTqEco28w
bTAdBgNVHQ4EFgQU8OTr9pxT2skW45XDLENU0v7UeJYwHwYDVR0jBBgwFoAU8OTr
9pxT2skW45XDLENU0v7UeJYwDwYDVR0TAQH/BAUwAwEB/zAaBgNVHREEEzARggls
b2NhbGhvc3SHBH8AAAEwCgYIKoZIzj0EAwIDSQAwRgIhANqm6vl32DL/4UMN4f7+
+5DxNyaGOIIwt9Wj/uZDH/iQAiEA5oIYfVq4/5QHIV9zNBodeUMMAn+ykyUR2erM
TL/DMCs=
-----END CERTIFICATE-----
"""
PEM_FILES = {
    "ca.pem": CA_PEM, "server.key": SERVER_KEY, "server.pem": SERVER_CERT,
    "other.key": OTHER_KEY, "other.pem": OTHER_CERT, "self.key": SELF_KEY, "self.pem": SELF_CERT,
}


@pytest.fixture(autouse=True)
def pki(workdir):
    """Write the CA, the leaf certificates and their keys into the program's working directory."""
    for name, text in PEM_FILES.items():
        (workdir / name).write_text(text, encoding="ascii")


@pytest.fixture
def dead_port():
    """A loopback port held bound but never listened on, so connecting to it is refused."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    yield s.getsockname()[1]
    s.close()


PRELUDE = r"""
const tls = require('tls');
const net = require('net');
const fs = require('fs');
const pem = (name) => fs.readFileSync(name);
const key = pem('server.key'), cert = pem('server.pem');
const short = (v) => (typeof v === 'string' && v.length > 24 ? `${v[0]}*${v.length}` : v);
"""

# attempt(label, serverOptions, clientOptions, vague) runs one connection against a fresh server and
# prints both sides' logs once both have finished. The server greets and closes. With `vague`, a
# client handshake error is reduced to its prefix: the server tore the TCP connection down while the
# ClientHello was in flight, so the client sees either an EOF or a reset.
ATTEMPT = PRELUDE + r"""
function attempt(label, serverOptions, clientOptions, vague) {
  return new Promise((resolve) => {
    const S = [], C = [];
    let pending = 2;
    const done = () => {
      if (--pending === 0) server.close(() => { console.log(`${label}\n  client: ${C.join(' | ')}\n  server: ${S.join(' | ')}`); resolve(); });
    };
    const server = tls.createServer(serverOptions, (s) => {
      S.push('secureConnection alpn=' + short(s.alpnProtocol));
      s.write('hi ' + label);
      setImmediate(() => s.destroy());
      s.on('close', () => { S.push('closed'); done(); });
    });
    server.on('tlsClientError', (e) => { S.push('tlsClientError: ' + e.message); done(); });
    server.listen(0, '127.0.0.1', () => {
      const c = tls.connect({ port: server.address().port, host: '127.0.0.1', ...clientOptions });
      c.on('secureConnect', () => C.push(`secure authorized=${c.authorized} authorizationError=${c.authorizationError === null ? null : typeof c.authorizationError} servername=${short(c.servername)} alpn=${short(c.alpnProtocol)}`));
      c.on('data', (d) => C.push('data ' + JSON.stringify(String(d))));
      c.on('error', (e) => C.push('error: ' + (vague && e.message.startsWith('TLS handshake failed (') ? 'TLS handshake failed (...)' : e.message)));
      c.on('close', (h) => { C.push('close hadError=' + h); done(); });
    });
  });
}
"""


# ------------------------------------------------------------------------- client <-> server basics
@pytest.mark.parametrize("tier", TIERS)
def test_verified_session_delivers_server_greeting(js, golden, tier):
    """CATCHES: a TLS client/server pair that never completes a verified handshake against a trusted
    CA, emits connect/secureConnect/ready out of order or before the session exists, reports wrong
    authorized/servername/address/protocol fields, loses the server's bytes, or misses end/close."""
    code = PRELUDE + r"""
const S = [], C = [];
let pending = 2;
const done = () => { if (--pending === 0) console.log(['client:', ...C, 'server:', ...S].join('\n')); };
const server = tls.createServer({ key, cert }, (s) => {
  S.push(`secureConnection encrypted=${s.encrypted} alpn=${s.alpnProtocol} remote=${s.remoteAddress} local=${s.localAddress} portIsServerPort=${s.localPort === server.address().port} protocolOk=${/^TLSv1\.[23]$/.test(s.getProtocol())}`);
  server.getConnections((e, n) => S.push(`getConnections err=${e} count=${n}`));
  s.write('hello from the TLS server');
  setImmediate(() => s.destroy());
  s.on('close', (h) => {
    S.push('socket close hadError=' + h + ' destroyed=' + s.destroyed);
    server.close(() => { S.push('server close callback listening=' + server.listening); done(); });
  });
});
server.on('tlsClientError', (e) => { S.push('tlsClientError: ' + e.message); server.close(done); });
server.on('listening', () => S.push('listening ' + JSON.stringify({ ...server.address(), port: typeof server.address().port }) + ' listening=' + server.listening));
server.listen(0, '127.0.0.1', () => {
  const c = tls.connect({ port: server.address().port, host: '127.0.0.1', servername: 'localhost' }, () => C.push('secureConnect callback'));
  C.push(`before: pending=${c.pending} connecting=${c.connecting} encrypted=${c.encrypted} authorized=${c.authorized} alpn=${c.alpnProtocol} servername=${c.servername} address=${JSON.stringify(c.address())}`);
  c.on('connect', () => C.push('connect'));
  c.on('secureConnect', () => {
    const ci = c.getCipher();
    C.push(`secureConnect authorized=${c.authorized} authorizationError=${c.authorizationError} pending=${c.pending} connecting=${c.connecting}`);
    C.push(`  remote=${c.remoteAddress} remotePortIsServerPort=${c.remotePort === server.address().port} local=${c.localAddress} family=${c.address().family}`);
    C.push(`  protocolOk=${/^TLSv1\.[23]$/.test(c.getProtocol())} cipherKeys=${Object.keys(ci).join(',')} cipherNamed=${typeof ci.name === 'string' && ci.name.length > 0 && ci.standardName === ci.name && ci.version === c.getProtocol()} reused=${c.isSessionReused()}`);
  });
  c.on('ready', () => C.push('ready'));
  c.setEncoding('utf8');
  c.on('data', (d) => C.push('data ' + JSON.stringify(d)));
  c.on('end', () => C.push('end bytesRead=' + c.bytesRead));
  c.on('error', (e) => C.push('error: ' + e.message));
  c.on('close', (h) => { C.push('close hadError=' + h + ' address=' + JSON.stringify(c.address())); done(); });
});
"""
    r = js(code, *tier, env_overrides=TRUST)
    assert out(r) == golden("verified_session")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bulk_server_write_is_flushed_by_destroy(js, golden):
    """CATCHES: a TLS server whose queued write is dropped when the socket is destroyed right after
    it, that corrupts or truncates a 40 kB payload split over several TLS records, or reports the
    wrong write() backpressure result, bytesWritten or client-side byte count."""
    code = PRELUDE + r"""
const payload = Buffer.from('lumen-tls bulk!\n'.repeat(2500));
const S = [], C = [], W = [];
let pending = 3;
const done = () => { if (--pending === 0) { server.close(); console.log(['client:', ...C, 'server:', ...S, 'server write callback:', ...W].join('\n')); } };
const server = tls.createServer({ key, cert }, (s) => {
  const ok = s.write(payload, (e) => { W.push(`error=${e} bytesWritten=${s.bytesWritten}`); done(); });
  S.push(`write returned ${ok} writableLength=${s.writableLength}`);
  setImmediate(() => s.destroy());
  s.on('close', (h) => { S.push('close hadError=' + h + ' destroyed=' + s.destroyed); done(); });
});
server.on('tlsClientError', (e) => { S.push('tlsClientError: ' + e.message); pending = 1; done(); });
server.listen(0, '127.0.0.1', () => {
  const c = tls.connect(server.address().port, '127.0.0.1', { servername: 'localhost' });
  const parts = [];
  c.on('data', (d) => parts.push(d));
  c.on('end', () => {
    const all = Buffer.concat(parts);
    C.push(`end received=${all.length} bytesRead=${c.bytesRead} intact=${all.equals(payload)} several chunks=${parts.length > 1}`);
  });
  c.on('error', (e) => C.push('error: ' + e.message));
  c.on('close', (h) => { C.push('close hadError=' + h); done(); });
});
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("bulk_server_write")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------- certificate verification
def test_hostname_and_ip_verification(js, golden):
    """CATCHES: hostname verification that ignores the servername, fails to match an IP literal
    against the certificate's IP SAN, mishandles wildcard SANs (one label only) or case, or accepts a
    CA-signed certificate for the wrong name instead of failing the handshake on both sides."""
    code = ATTEMPT + r"""
const other = { key: pem('other.key'), cert: pem('other.pem') };
(async () => {
  await attempt('ip literal host, no servername', { key, cert }, {});
  await attempt('wrong ip', { key, cert }, { servername: '127.0.0.2' });
  await attempt('upper-case OTHER.TEST', other, { servername: 'OTHER.TEST' });
  await attempt('wildcard one label', other, { servername: 'api.wild.test' });
  await attempt('wildcard two labels', other, { servername: 'a.b.wild.test' });
  await attempt('no ip san', other, {});
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("hostname_ip_verification")
    assert (r.returncode, r.stderr) == (0, b"")


def test_trust_anchors_come_from_ssl_cert_file(js, golden):
    """CATCHES: a client that trusts any certificate, or ignores OpenSSL's SSL_CERT_FILE trust store:
    with only the self-signed certificate configured as anchor, the CA-issued server must fail with
    'certificate verify failed' (server: 'unknown ca') while the self-signed server is authorized."""
    code = ATTEMPT + r"""
const selfSigned = { key: pem('self.key'), cert: pem('self.pem') };
(async () => {
  await attempt('issuer not in the store', { key, cert }, { servername: 'localhost' });
  await attempt('issuer not in the store, rejectUnauthorized false', { key, cert }, { servername: 'localhost', rejectUnauthorized: false });
  await attempt('configured anchor itself', selfSigned, { servername: 'localhost' });
})();
"""
    r = js(code, env_overrides={"SSL_CERT_FILE": "self.pem"})
    assert out(r) == golden("trust_anchor_file")
    assert (r.returncode, r.stderr) == (0, b"")


def test_self_signed_server_rejected_unless_verification_disabled(js, golden):
    """CATCHES: trusting a self-signed leaf just because some CA file is configured, or a
    rejectUnauthorized:false connection that still checks the issuer or the hostname (it must
    connect to a self-signed server even under a wrong servername and report authorized=false)."""
    code = ATTEMPT + r"""
const selfSigned = { key: pem('self.key'), cert: pem('self.pem') };
(async () => {
  await attempt('self-signed', selfSigned, { servername: 'localhost' });
  await attempt('self-signed, wrong name, no verification', selfSigned, { servername: 'nothing.example', rejectUnauthorized: false });
  await attempt('trusted leaf, no verification', { key, cert }, { servername: 'localhost', rejectUnauthorized: false });
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("self_signed")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------------- ALPN
def test_alpn_negotiation(js, golden):
    """CATCHES: ALPN that is not offered by the client, not selected by the server's callback in the
    server's preference order, mishandles Buffer entries, reports a protocol when there is no
    overlap or the client offered none, or truncates a maximal 255-byte protocol name."""
    code = ATTEMPT + r"""
const long = 'p'.repeat(255);
(async () => {
  await attempt('server order wins', { key, cert, ALPNProtocols: ['http/1.1', 'h2'] }, { servername: 'localhost', ALPNProtocols: ['h2', Buffer.from('http/1.1')] });
  await attempt('no overlap', { key, cert, ALPNProtocols: ['h2'] }, { servername: 'localhost', ALPNProtocols: ['spdy/3', 'http/1.0'] });
  await attempt('client offers none', { key, cert, ALPNProtocols: ['h2'] }, { servername: 'localhost', ALPNProtocols: [''] });
  await attempt('255-byte name', { key, cert, ALPNProtocols: [long] }, { servername: 'localhost', ALPNProtocols: ['q', long] });
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("alpn_negotiation")
    assert (r.returncode, r.stderr) == (0, b"")


def test_client_session_configuration_errors(js, golden):
    """CATCHES: client-side session setup that accepts an ALPN name over 255 bytes, an over-long or
    NUL-containing servername, instead of failing after the TCP connect with the exact message (the
    peer must then see the connection end before a single byte of ClientHello)."""
    code = PRELUDE + r"""
// A plain TCP peer: it only reports how many bytes arrived before the client hung up.
function refusedLocally(label, clientOptions) {
  return new Promise((resolve) => {
    const P = [], C = [];
    let pending = 2;
    const done = () => { if (--pending === 0) { peer.close(); console.log(`${label}\n  client: ${C.join(' | ')}\n  peer: ${P.join(' | ')}`); resolve(); } };
    const peer = net.createServer((s) => {
      let n = 0;
      s.on('data', (d) => { n += d.length; });
      s.on('end', () => P.push(`end after ${n} bytes`));
      s.on('close', () => { P.push('close'); done(); });
    });
    peer.listen(0, '127.0.0.1', () => {
      const c = tls.connect({ port: peer.address().port, host: '127.0.0.1', ...clientOptions }, () => C.push('UNEXPECTED secureConnect'));
      c.on('error', (e) => C.push('error: ' + e.message));
      c.on('close', (h) => { C.push('close hadError=' + h); done(); });
    });
  });
}
(async () => {
  await refusedLocally('alpn name of 256 bytes', { servername: 'localhost', ALPNProtocols: ['h2', 'a'.repeat(256)] });
  await refusedLocally('servername of 300 bytes', { servername: 's'.repeat(300) });
  await refusedLocally('servername with NUL', { servername: 'local\0host' });
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("client_configuration_errors")
    assert (r.returncode, r.stderr) == (0, b"")


# --------------------------------------------------------------------------------- server options
def test_server_certificate_and_key_errors(js, golden):
    """CATCHES: a TLS server that accepts unparsable certificate/key PEM, a certificate whose key does
    not match, or an over-long ALPN name, instead of failing each accepted connection with the exact
    OpenSSL reason as a 'tlsClientError' (while the client's handshake fails)."""
    code = ATTEMPT + r"""
(async () => {
  await attempt('garbage certificate', { key, cert: 'not a certificate' }, { servername: 'localhost' }, true);
  await attempt('garbage key', { key: Buffer.from('not a key'), cert }, { servername: 'localhost' }, true);
  await attempt('key of another certificate', { key: pem('self.key'), cert }, { servername: 'localhost' }, true);
  await attempt('server alpn name of 300 bytes', { key, cert, ALPNProtocols: ['x'.repeat(300)] }, { servername: 'localhost' }, true);
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("server_pem_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_server_option_forms_and_listen_errors(js, golden):
    """CATCHES: tls.createServer ignoring secureContext/array cert+key options or the listen({port,
    host}) object form, or failing to throw the exact TypeError for missing cert/key and the exact
    error for a port already in use."""
    code = PRELUDE + r"""
const errOf = (f) => { try { f(); return 'no error'; } catch (e) { return `${e.name}: ${e.message}`; } };
console.log('no options:', errOf(() => tls.createServer().listen(0)));
console.log('listener only:', errOf(() => tls.createServer(() => {}).listen(0)));
console.log('cert only:', errOf(() => tls.createServer({ cert }).listen(0)));
console.log('key only:', errOf(() => new tls.Server({ key }).listen(0)));
const ctx = tls.createSecureContext({ key: [key], cert: [cert] });
console.log('secure context:', ctx instanceof tls.SecureContext, JSON.stringify(Object.keys(ctx.context)));
function greetOnce(server, label) {
  return new Promise((resolve) => {
    const c = tls.connect({ port: server.address().port, host: '127.0.0.1', servername: 'localhost' });
    let got = '';
    c.setEncoding('utf8');
    c.on('data', (d) => { got += d; });
    c.on('error', (e) => console.log(label, 'error:', e.message));
    c.on('close', (h) => { console.log(label, JSON.stringify(got), 'hadError=' + h); resolve(); });
  });
}
const greeter = (s) => { s.write('greeting from ' + s.localAddress); setImmediate(() => s.destroy()); };
(async () => {
  const a = tls.createServer({ secureContext: ctx }, greeter);
  await new Promise((resolve) => a.listen({ port: 0, host: '127.0.0.1' }, resolve));
  console.log('object listen:', a.address().address, a.address().family, a.listening);
  await greetOnce(a, 'secureContext server says');
  const b = new tls.Server({ key: [key, pem('self.key')], cert: [cert, pem('self.pem')] }, greeter);
  const port = a.address().port;
  console.log('port in use:', errOf(() => b.listen(port, '127.0.0.1')).split(String(port)).join('PORT'), b.listening);
  await new Promise((resolve) => a.close(resolve));
  console.log('after close: listening', a.listening);
  b.listen(0, '127.0.0.1');
  await new Promise((resolve) => b.once('listening', resolve));
  await greetOnce(b, 'array options server says');
  b.close(() => console.log('second server closed'));
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("server_option_forms")
    assert (r.returncode, r.stderr) == (0, b"")


def test_wildcard_listen_address_and_close_lifecycle(js, golden):
    """CATCHES: a TLS server listening on the default 0.0.0.0 address that reports the wrong
    address/family, cannot be reached over loopback, or whose close() leaves the pending accept
    blocked (the process would hang) or skips the callback, 'close' event or getConnections count."""
    code = PRELUDE + r"""
const log = [];
const server = tls.createServer({ key, cert }, (s) => {
  log.push('secureConnection from ' + s.remoteAddress);
  s.write('wildcard ok');
  setImmediate(() => s.destroy());
});
server.on('close', () => log.push('close event'));
server.listen(0, () => {
  const a = server.address();
  log.push(`listen callback address=${a.address} family=${a.family} listening=${server.listening}`);
  const c = tls.connect({ port: a.port, host: '127.0.0.1', servername: 'localhost' });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('error', (e) => log.push('client error: ' + e.message));
  c.on('close', () => {
    log.push('client got ' + JSON.stringify(got));
    server.getConnections((e, n) => {
      log.push(`connections after client close: ${n}`);
      server.close(() => { log.push('close callback listening=' + server.listening); setImmediate(() => console.log(log.join('\n'))); });
    });
  });
});
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("wildcard_listen")
    assert (r.returncode, r.stderr) == (0, b"")


@needs_ipv6
def test_ipv6_wildcard_listen_and_close(js, golden):
    """CATCHES: a TLS server on the IPv6 wildcard address '::' that reports an IPv4 family, is not
    reachable over ::1, or whose close() cannot wake its pending accept over the IPv6 loopback (the
    process would hang instead of exiting after the close callback)."""
    code = PRELUDE + r"""
const log = [];
const server = tls.createServer({ key, cert }, (s) => {
  log.push(`secureConnection remote=${s.remoteAddress} family=${s.address().family}`);
  s.write('hello over IPv6');
  setImmediate(() => s.destroy());
});
server.listen(0, '::', () => {
  const a = server.address();
  log.push(`listening address=${a.address} family=${a.family}`);
  const c = tls.connect({ port: a.port, host: '::1', servername: 'localhost' });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('error', (e) => log.push('client error: ' + e.message));
  c.on('close', () => {
    log.push(`client got ${JSON.stringify(got)} authorized=${c.authorized} remote=${c.remoteAddress}`);
    server.close(() => { log.push('closed listening=' + server.listening); console.log(log.join('\n')); });
  });
});
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("ipv6_wildcard_listen")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- connect failures
def test_connect_argument_and_network_errors(js, golden, dead_port):
    """CATCHES: tls.connect accepting out-of-range or non-integer ports instead of throwing the
    RangeError, hanging or throwing synchronously on a refused connection or an unresolvable host
    instead of an 'error' event with the exact message followed by close(hadError=true)."""
    code = PRELUDE + r"""
const dead = Number(process.argv[2]);
const mask = (s) => s.split(String(dead)).join('DEAD');
for (const port of [70000, -1, 1.5, 'abc']) {
  try { tls.connect({ port, host: '127.0.0.1' }); console.log('port', port, 'accepted'); }
  catch (e) { console.log(`port ${JSON.stringify(port)}: ${e.name}: ${e.message}`); }
}
function failing(label, ...args) {
  return new Promise((resolve) => {
    const c = tls.connect(...args, () => console.log(label, 'UNEXPECTED secureConnect'));
    const events = [];
    c.on('error', (e) => events.push(`error ${e.name}: ${JSON.stringify(mask(e.message))}`));
    c.on('close', (h) => { events.push('close hadError=' + h + ' authorized=' + c.authorized); console.log(label + ': ' + events.join(' | ')); resolve(); });
  });
}
(async () => {
  await failing('refused (port, host)', dead, '127.0.0.1');
  await failing('refused (options)', { port: dead, host: '127.0.0.1', servername: 'localhost' });
  await failing('unresolvable host', { port: dead, host: 'no\0such.host' });
})();
"""
    r = js(code, args=(str(dead_port),), env_overrides=TRUST)
    assert out(r) == golden("connect_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_client_hello_contents_and_silent_peer_timeout(js, golden):
    """CATCHES: a client that sends no SNI for its servername or omits the offered ALPN names from a
    well-formed ClientHello record, or that waits forever on a peer which never answers instead of
    failing the handshake (SSL error 2) and closing its TCP connection."""
    code = PRELUDE + r"""
const P = [], C = [];
let pending = 2;
const done = () => { if (--pending === 0) { peer.close(); console.log(['peer:', ...P, 'client:', ...C].join('\n')); } };
const peer = net.createServer((s) => {
  let buf = Buffer.alloc(0), reported = false;
  s.on('data', (d) => {
    buf = Buffer.concat([buf, d]);
    if (reported || buf.length < 5 || buf.length < 5 + buf.readUInt16BE(3)) return;
    reported = true;
    const text = buf.toString('latin1');
    P.push(`record type=0x${buf[0].toString(16)} version major=${buf[1]} complete=${buf.length === 5 + buf.readUInt16BE(3)} handshake type=${buf[5]}`);
    P.push(`sni sent=${text.includes('sni.example.test')} alpn sent=${text.includes('lumen-proto/1')},${text.includes('lumen-proto/2')}`);
  });
  s.on('end', () => P.push('end'));
  s.on('close', (h) => { P.push('close hadError=' + h); done(); });
});
peer.listen(0, '127.0.0.1', () => {
  const c = tls.connect({ port: peer.address().port, host: '127.0.0.1', servername: 'sni.example.test', ALPNProtocols: ['lumen-proto/1', 'lumen-proto/2'] });
  c.on('secureConnect', () => C.push('UNEXPECTED secureConnect'));
  c.on('error', (e) => C.push('error: ' + e.message));
  c.on('close', (h) => { C.push('close hadError=' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("client_hello_silent_peer")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- server handshakes
def test_server_handshake_timeout_then_keeps_serving(js, golden):
    """CATCHES: a TLS server whose accept loop dies (or blocks forever) when a client connects and
    never sends a ClientHello, instead of reporting the failed handshake as 'tlsClientError', closing
    that TCP connection, and still serving the next client."""
    code = PRELUDE + r"""
const S = [], R = [], C = [];
let phase1 = 2, phase2 = 2;
const server = tls.createServer({ key, cert }, (s) => {
  S.push('secureConnection');
  s.write('still serving');
  setImmediate(() => s.destroy());
  s.on('close', () => { S.push('closed'); second(); });
});
server.on('tlsClientError', (e) => { S.push('tlsClientError: ' + e.message); first(); });
const first = () => {
  if (--phase1 !== 0) return;
  const c = tls.connect({ port: server.address().port, host: '127.0.0.1', servername: 'localhost' });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('error', (e) => C.push('error: ' + e.message));
  c.on('close', (h) => { C.push(`got ${JSON.stringify(got)} hadError=${h}`); second(); });
};
const second = () => { if (--phase2 === 0) server.close(() => console.log(['silent raw client:', ...R, 'tls client:', ...C, 'server:', ...S].join('\n'))); };
server.listen(0, '127.0.0.1', () => {
  const raw = net.connect(server.address().port, '127.0.0.1'); // connects, then never sends a byte
  raw.on('data', (d) => R.push('data ' + d.length));
  raw.on('end', () => R.push('end'));
  raw.on('close', (h) => { R.push('close hadError=' + h); first(); });
});
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("server_handshake_timeout")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------- peers run by the test process itself
class PeerThread:
    """A peer run by the test process in a background thread. `log` records what it observed, one
    line per event; finish() (called once the program has exited) stops any wait and returns it."""

    def __init__(self):
        self.log = []
        self.stop = threading.Event()
        self.thread = None

    def start(self, target):
        self.thread = threading.Thread(target=self._guard, args=(target,), daemon=True)
        self.thread.start()

    def _guard(self, target):
        try:
            target()
        except (OSError, ValueError) as e:  # recorded, so the log assertion shows what went wrong
            self.log.append(f"peer failed: {type(e).__name__}: {e}")

    def finish(self):
        self.stop.set()
        self.thread.join(15)
        return self.log

    def wait_for_port(self, port_file):
        """The port the program wrote to `port_file` once it was listening."""
        deadline = time.monotonic() + 15
        while not port_file.exists() or not port_file.read_text().strip().isdigit():
            if self.stop.is_set() or time.monotonic() > deadline:
                raise OSError("the program never wrote its port file")
            time.sleep(0.01)
        return int(port_file.read_text())

    def accept(self, listener):
        """accept() that gives up once the program has exited."""
        listener.settimeout(0.05)
        deadline = time.monotonic() + 15
        while True:
            try:
                return listener.accept()[0]
            except TimeoutError:
                if self.stop.is_set() or time.monotonic() > deadline:
                    raise


class PyTlsServer(PeerThread):
    """A TLS server endpoint driven by Python's ssl module, with the test certificate, no session
    tickets (nothing unsolicited follows the handshake) and an optional ALPN list."""

    def __init__(self, workdir, alpn=None):
        super().__init__()
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(workdir / "server.pem"), str(workdir / "server.key"))
        self.ctx.num_tickets = 0
        if alpn:
            self.ctx.set_alpn_protocols(alpn)
        self.sni = []
        self.ctx.sni_callback = lambda _obj, name, _ctx: self.sni.append(name)

    def dial_and_greet(self, port_file, greetings):
        """Wait for the program to write its listening port, then for each greeting: connect, act as
        the TLS *server* on that connection, send the greeting and exchange close_notify."""
        def run():
            port = self.wait_for_port(port_file)
            for greeting in greetings:
                raw = socket.create_connection(("127.0.0.1", port), timeout=10)
                tls = self.ctx.wrap_socket(raw, server_side=True)
                self.log.append(f"handshake sni={self.sni[-1]!r} alpn={tls.selected_alpn_protocol()!r}")
                tls.sendall(greeting)
                tls.unwrap().close()
                self.log.append("close_notify exchanged")
        self.start(run)

    def forge_after_handshake(self):
        """Listen; after one handshake write a forged application-data record straight onto the
        TCP stream, then record what the client sends back before it closes. Returns the port."""
        listener = socket.create_server(("127.0.0.1", 0))

        def run():
            with listener:
                conn = self.accept(listener)
            conn.settimeout(10)
            tls = self.ctx.wrap_socket(conn, server_side=True)
            self.log.append(f"handshake sni={self.sni[-1]!r}")
            raw = socket.socket(fileno=os.dup(tls.fileno()))
            raw.settimeout(10)
            raw.sendall(bytes([0x17, 0x03, 0x03, 0x00, 0x20]) + b"\x5a" * 32)
            reply = b""
            while chunk := raw.recv(4096):
                reply += chunk
            self.log.append(f"client answered {len(reply)} bytes, record type 0x{reply[0]:02x}, then closed")
            raw.close()
            tls.close()
        self.start(run)
        return listener.getsockname()[1]


def test_upgrade_of_accepted_socket(js, golden, workdir):
    """CATCHES: tls.connect({socket}) and new tls.TLSSocket(socket) on an accepted net.Socket that do
    not run a verified client handshake (with SNI and ALPN) over that socket's native stream, lose the
    peer's data or close_notify, or accept a socket that is not a paused accepted net.Socket."""
    peer = PyTlsServer(workdir, alpn=["lumen-proto/1"])
    peer.dial_and_greet(workdir / "entry.port", [b"greetings over an upgraded socket", b"and again"])
    code = PRELUDE + r"""
const errOf = (f) => { try { f(); return 'no error'; } catch (e) { return `${e.name}: ${e.message}`; } };
const forms = [
  ['tls.connect({socket})', (sock) => tls.connect({ socket: sock, servername: 'localhost', ALPNProtocols: ['h2', 'lumen-proto/1'] })],
  ['new tls.TLSSocket(socket)', (sock) => new tls.TLSSocket(sock, { servername: 'localhost' })],
];
const log = [];
let n = 0;
const entry = net.createServer((accepted) => {
  const [label, wrap] = forms[n++];
  const C = [];
  const t = wrap(accepted);
  C.push(`encrypted=${t.encrypted} connecting=${t.connecting} accepted socket destroyed=${accepted.destroyed}`);
  t.on('secureConnect', () => C.push(`secureConnect authorized=${t.authorized} servername=${t.servername} alpn=${t.alpnProtocol} protocolOk=${/^TLSv1\.[23]$/.test(t.getProtocol())}`));
  t.on('data', (d) => C.push('data ' + JSON.stringify(String(d))));
  t.on('end', () => C.push('end'));
  t.on('error', (e) => C.push('error: ' + e.message));
  t.on('close', (h) => {
    C.push('close hadError=' + h);
    log.push(`${label}: ${C.join(' | ')}`);
    if (n === forms.length) finish();
  });
});
entry.listen(0, '127.0.0.1', () => fs.writeFileSync('entry.port', String(entry.address().port)));
function finish() {
  log.push('unconnected socket: ' + errOf(() => tls.connect({ socket: new net.Socket() })));
  const plain = net.createServer((s) => s.destroy());
  plain.listen(0, '127.0.0.1', () => {
    const outgoing = net.connect(plain.address().port, '127.0.0.1', () => {
      log.push('connected outgoing socket: ' + errOf(() => tls.connect({ socket: outgoing })));
      outgoing.destroy();
      entry.close();
      plain.close(() => console.log(log.join('\n')));
    });
    outgoing.on('error', () => {});
  });
}
"""
    r = js(code, env_overrides=TRUST)
    assert peer.finish() == [
        "handshake sni='localhost' alpn='lumen-proto/1'", "close_notify exchanged",
        "handshake sni='localhost' alpn=None", "close_notify exchanged",
    ]
    assert out(r) == golden("upgrade_accepted_socket")
    assert (r.returncode, r.stderr) == (0, b"")


def test_forged_record_after_handshake_is_a_read_error(js, golden, workdir):
    """CATCHES: a TLS client that ignores, or delivers as data, an application-data record that fails
    authentication after the handshake, instead of failing the read with OpenSSL's 'decryption failed
    or bad record mac' error and answering with an alert before closing."""
    peer = PyTlsServer(workdir)
    port = peer.forge_after_handshake()
    code = PRELUDE + r"""
const C = [];
const c = tls.connect({ port: Number(process.argv[2]), host: '127.0.0.1', servername: 'localhost' }, () => C.push('secureConnect authorized=' + c.authorized));
c.on('data', (d) => C.push('UNEXPECTED data ' + JSON.stringify(String(d))));
c.on('end', () => C.push('UNEXPECTED end'));
c.on('error', (e) => C.push('error: ' + e.message));
c.on('close', (h) => { C.push('close hadError=' + h + ' bytesRead=' + c.bytesRead); console.log(C.join('\n')); });
"""
    r = js(code, args=(str(port),), env_overrides=TRUST)
    assert peer.finish() == ["handshake sni='localhost'", "client answered 24 bytes, record type 0x17, then closed"]
    assert out(r) == golden("forged_record")
    assert (r.returncode, r.stderr) == (0, b"")


def raw_exchanges(peer, port_file, payloads):
    """Background client: for each payload, connect to the program's port, send the payload at once
    and record what comes back and how the connection ends."""
    def run():
        port = peer.wait_for_port(port_file)
        for payload in payloads:
            sock = socket.create_connection(("127.0.0.1", port), timeout=10)
            sock.sendall(payload)
            received = b""
            ending = "eof"
            try:
                while chunk := sock.recv(4096):
                    received += chunk
            except ConnectionResetError:
                ending = "reset"
            sock.close()
            peer.log.append(f"received {received.hex() or 'nothing'}, then {ending}")
    peer.start(run)


def test_server_rejects_plaintext_and_malformed_hello(js, golden, workdir):
    """CATCHES: a TLS server that hangs on or accepts a plaintext HTTP request or a truncated
    ClientHello, instead of failing each with OpenSSL's exact reason, resetting the connection whose
    bytes it left unread and answering the malformed hello with a fatal decode_error alert."""
    client = PeerThread()
    raw_exchanges(client, workdir / "server.port", [
        b"GET / HTTP/1.1\r\nHost: example\r\n\r\n",
        bytes.fromhex("16030100050100000100"),
    ])
    code = PRELUDE + r"""
const S = [];
const server = tls.createServer({ key, cert }, () => S.push('UNEXPECTED secureConnection'));
server.on('tlsClientError', (e) => {
  S.push('tlsClientError: ' + e.message);
  if (S.length === 2) server.close(() => console.log(S.join('\n')));
});
server.listen(0, '127.0.0.1', () => fs.writeFileSync('server.port', String(server.address().port)));
"""
    r = js(code)
    assert client.finish() == ["received nothing, then reset", "received 15030300020232, then eof"]
    assert out(r) == golden("plaintext_and_malformed")
    assert (r.returncode, r.stderr) == (0, b"")


# --------------------------------------------------------------------- lumen-web clients over TLS
HTTPS_SERVER = PRELUDE + r"""
const UA = /lumen\/[0-9][^ ;]*/g;
// httpsServer(options, respond, log): a TLS server that reads one HTTP request (head plus
// Content-Length body), logs it, writes respond(request) and closes.
function httpsServer(options, respond, log) {
  return tls.createServer(options, (s) => {
    let buf = Buffer.alloc(0);
    s.on('data', (d) => {
      buf = Buffer.concat([buf, d]);
      const end = buf.toString('latin1').indexOf('\r\n\r\n');
      if (end < 0) return;
      const head = buf.toString('latin1', 0, end).split('\r\n');
      const lengthLine = head.find((l) => /^content-length:/i.test(l));
      const want = lengthLine ? Number(lengthLine.split(':')[1]) : 0;
      if (buf.length < end + 4 + want) return;
      const request = { line: head[0], headers: head.slice(1), body: buf.toString('utf8', end + 4, end + 4 + want) };
      if (log) log.push(`server saw ${request.line} [${request.headers.map((h) => h.replace(/:\d+$/, ':PORT').replace(UA, 'lumen/VERSION')).sort().join('; ')}] body=${JSON.stringify(request.body)}`);
      s.write(respond(request));
      setImmediate(() => s.destroy());
    });
  });
}
const response = (status, headers, body) => `HTTP/1.1 ${status}\r\n${Object.entries(headers).map(([k, v]) => `${k}: ${v}\r\n`).join('')}Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`;
"""


def test_fetch_and_https_module_over_tls(js, golden):
    """CATCHES: fetch() or node:https requests to an https:// URL that are sent in plaintext, skip
    certificate verification, drop the request body or headers, or mis-parse the TLS-delivered
    status line, headers and body (GET, POST with a body, https.get and https.request)."""
    code = HTTPS_SERVER + r"""
const log = [];
const server = httpsServer({ key, cert }, (req) => response('201 Created', { 'Content-Type': 'text/plain', 'X-Served-By': 'lumen-tls' }, `secure reply to ${req.line.split(' ')[0]} ${req.line.split(' ')[1]} (${req.body.length} body bytes)`), log);
server.on('tlsClientError', (e) => log.push('tlsClientError: ' + e.message));
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const base = `https://127.0.0.1:${port}`;
  const mask = (s) => s.split(String(port)).join('PORT');
  try {
    let res = await fetch(`${base}/items?id=5`, { headers: { 'X-Request': 'one' } });
    log.push(`fetch GET -> ${res.status} ${res.statusText} ok=${res.ok} type=${res.headers.get('content-type')} by=${res.headers.get('x-served-by')} url=${mask(res.url)} body=${JSON.stringify(await res.text())}`);
    res = await fetch(`${base}/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secure: true, n: 42 }) });
    log.push(`fetch POST -> ${res.status} body=${JSON.stringify(await res.text())}`);
  } catch (e) { log.push('fetch failed: ' + mask(e.message)); }
  const https = require('https');
  await new Promise((resolve) => {
    https.get(`${base}/via-https-get`, (r) => {
      let b = '';
      r.setEncoding('utf8');
      r.on('data', (d) => { b += d; });
      r.on('end', () => { log.push(`https.get -> ${r.statusCode} ${r.statusMessage} by=${r.headers['x-served-by']} body=${JSON.stringify(b)}`); resolve(); });
    }).on('error', (e) => { log.push('https.get failed: ' + mask(e.message)); resolve(); });
  });
  await new Promise((resolve) => {
    const req = https.request({ hostname: '127.0.0.1', port, path: '/via-https-request', method: 'PUT', headers: { 'Content-Type': 'text/plain' } }, (r) => {
      let b = '';
      r.on('data', (d) => { b += d; });
      r.on('end', () => { log.push(`https.request -> ${r.statusCode} body=${JSON.stringify(b)}`); resolve(); });
    });
    req.on('error', (e) => { log.push('https.request failed: ' + mask(e.message)); resolve(); });
    req.write('first part, ');
    req.end('second part');
  });
  server.close(() => console.log(log.join('\n')));
});
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("fetch_https")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fetch_tls_failures_and_chunked_bodies(js, golden):
    """CATCHES: fetch() over https that accepts an untrusted or wrong-host certificate instead of
    rejecting with a TypeError naming the URL and OpenSSL's reason, mis-decodes a chunked body read
    through TLS, or buffers a chunk larger than the 32 MiB response limit instead of failing."""
    code = HTTPS_SERVER + r"""
const servers = [];
const start = (options, respond) => new Promise((resolve) => {
  const s = httpsServer(options, respond);
  servers.push(s);
  s.listen(0, '127.0.0.1', () => resolve(s));
});
// Each attempt waits for the client's outcome and, when the handshake is refused, for the server's
// matching tlsClientError, then prints both.
const attempt = async (label, server, path, viaHttps) => {
  const port = server.address().port;
  const mask = (s) => s.split(String(port)).join('PORT');
  const url = `https://127.0.0.1:${port}${path}`;
  const refused = new Promise((resolve) => server.once('tlsClientError', (e) => resolve(e.message)));
  let line;
  if (viaHttps) {
    line = await new Promise((resolve) => require('https').get(url, () => resolve('UNEXPECTED response')).on('error', (e) => resolve(`${e.name}: ${mask(e.message)}`)));
  } else {
    try {
      const res = await fetch(url);
      line = `${res.status} ${JSON.stringify(await res.text())}`;
    } catch (e) { line = `${e.name}: ${mask(e.message)}`; }
  }
  console.log(`${label}: ${line}`);
  if (line.includes('TLS handshake failed')) console.log(`  server tlsClientError: ${await refused}`);
  else console.log('  server completed the handshake');
};
(async () => {
  const selfSigned = await start({ key: pem('self.key'), cert: pem('self.pem') }, () => 'unused');
  await attempt('fetch self-signed', selfSigned, '/');
  await attempt('https.get self-signed', selfSigned, '/https-get', true);
  const other = await start({ key: pem('other.key'), cert: pem('other.pem') }, () => 'unused');
  await attempt('fetch certificate for other.test', other, '/');
  const ok = await start({ key, cert }, (req) => req.line.includes('/huge')
    ? 'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2000001\r\n'
    : 'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: text/plain\r\n\r\n6\r\nchunk-\r\n5;ext=1\r\nover-\r\n3\r\nTLS\r\n0\r\nX-Trailer: t\r\n\r\n');
  await attempt('fetch chunked', ok, '/chunked');
  await attempt('fetch oversized chunk', ok, '/huge');
  for (const s of servers) s.close();
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("fetch_tls_failures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_wss_websocket_over_tls(js, golden):
    """CATCHES: a wss:// WebSocket that handshakes in plaintext, skips certificate verification, or
    mis-reads the 101 response and frames carried over TLS (text message then the server's close
    1000 'bye' as a clean close), or reports an untrusted server as anything but error + close 1006."""
    code = PRELUDE + r"""
const crypto = require('crypto');
const log = [];
const wsServer = (options) => tls.createServer(options, (s) => {
  let head = '';
  s.on('data', (d) => {
    head += d.toString('latin1');
    if (!head.includes('\r\n\r\n')) return;
    const lines = head.split('\r\n');
    const keyLine = lines.find((l) => /^sec-websocket-key:/i.test(l));
    const wsKey = keyLine.split(':')[1].trim();
    log.push(`  server saw ${lines[0]} [${lines.slice(1).filter((l) => /^(host|upgrade|connection|sec-websocket-version):/i.test(l)).map((l) => l.replace(/:\d+$/, ':PORT')).join('; ')}] key bytes=${Buffer.from(wsKey, 'base64').length}`);
    const accept = crypto.createHash('sha1').update(wsKey + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    const text = Buffer.from('hello over wss');
    s.write(Buffer.concat([
      Buffer.from(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`),
      Buffer.from([0x81, text.length]), text,
      Buffer.from([0x88, 5, 0x03, 0xe8]), Buffer.from('bye'),
    ]));
    setImmediate(() => s.destroy());
  });
});
const session = (label, port) => new Promise((resolve) => {
  const ws = new WebSocket(`wss://127.0.0.1:${port}/chat?room=1`);
  const events = [];
  ws.onopen = () => events.push(`open protocol=${JSON.stringify(ws.protocol)} readyState=${ws.readyState}`);
  ws.onmessage = (e) => events.push('message ' + JSON.stringify(e.data));
  ws.onerror = (e) => events.push('error event ' + e.type);
  ws.onclose = (e) => { events.push(`close code=${e.code} reason=${JSON.stringify(e.reason)} clean=${e.wasClean} readyState=${ws.readyState}`); log.push(`${label}: ${events.join(' | ')}`); resolve(); };
});
(async () => {
  const good = wsServer({ key, cert });
  good.on('tlsClientError', (e) => log.push('  trusted server: ' + e.message));
  await new Promise((resolve) => good.listen(0, '127.0.0.1', resolve));
  await session('trusted', good.address().port);
  const bad = wsServer({ key: pem('self.key'), cert: pem('self.pem') });
  const refused = new Promise((resolve) => bad.once('tlsClientError', (e) => resolve(e.message)));
  await new Promise((resolve) => bad.listen(0, '127.0.0.1', resolve));
  await session('self-signed', bad.address().port);
  log.push('  untrusted server: ' + await refused);
  good.close();
  bad.close(() => console.log(log.join('\n')));
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("wss")
    assert (r.returncode, r.stderr) == (0, b"")


def test_eventsource_over_https(js, golden):
    """CATCHES: an EventSource on an https:// URL that cannot open a verified TLS stream, mis-parses
    the event stream delivered over TLS (default message, named event, id), or treats an untrusted
    certificate as anything but an error that leaves the source reconnecting until close()."""
    code = PRELUDE + r"""
const log = [];
const sseServer = (options) => tls.createServer(options, (s) => {
  let head = '';
  s.on('data', (d) => {
    head += d;
    if (!head.includes('\r\n\r\n')) return;
    const lines = head.split('\r\n');
    log.push(`server saw ${lines[0]} [${lines.slice(1).filter((l) => /^(accept|cache-control):/i.test(l)).join('; ')}]`);
    s.write('HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\ndata: first\n\nid: 7\nevent: greet\ndata: secure\ndata: event\n\n');
    setImmediate(() => s.destroy());
  });
});
(async () => {
  const good = sseServer({ key, cert });
  good.on('tlsClientError', (e) => log.push('trusted server: ' + e.message));
  await new Promise((resolve) => good.listen(0, '127.0.0.1', resolve));
  await new Promise((resolve) => {
    const es = new EventSource(`https://127.0.0.1:${good.address().port}/events`);
    es.onopen = () => log.push('open readyState=' + es.readyState);
    es.onmessage = (e) => log.push(`message ${JSON.stringify(e.data)} lastEventId=${JSON.stringify(e.lastEventId)}`);
    es.onerror = () => { log.push('error readyState=' + es.readyState); es.close(); resolve(); };
    es.addEventListener('greet', (e) => { log.push(`greet ${JSON.stringify(e.data)} lastEventId=${JSON.stringify(e.lastEventId)}`); es.close(); log.push('closed readyState=' + es.readyState); resolve(); });
  });
  const bad = sseServer({ key: pem('self.key'), cert: pem('self.pem') });
  const failed = new Promise((resolve) => bad.once('tlsClientError', (e) => resolve(e.message)));
  await new Promise((resolve) => bad.listen(0, '127.0.0.1', resolve));
  await new Promise((resolve) => {
    const es = new EventSource(`https://127.0.0.1:${bad.address().port}/events`);
    es.onopen = () => log.push('UNEXPECTED open');
    es.onerror = (e) => { log.push(`untrusted: ${e.type} readyState=${es.readyState}`); es.close(); log.push('closed readyState=' + es.readyState); resolve(); };
  });
  log.push('untrusted server: ' + await failed);
  good.close();
  bad.close(() => console.log(log.join('\n')));
})();
"""
    r = js(code, env_overrides=TRUST)
    assert out(r) == golden("eventsource_https")
    assert (r.returncode, r.stderr) == (0, b"")
