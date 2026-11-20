"""node:net (and the UDP half of net.rs that backs node:dgram) driven through real loopback sockets.

Every program opens its own server on 127.0.0.1 with port 0 and never prints the ephemeral port.
Two-sided programs record the client's and the server's events in separate lists and print both
once each side has closed, so only causally forced per-side orders reach stdout.
"""

import socket

import pytest

from conftest import out


def _ipv6_loopback_works() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"),
         pytest.param(("--tier=interp",), id="interp")]

needs_ipv6 = pytest.mark.skipif(not _ipv6_loopback_works(), reason="no IPv6 loopback (::1) in this environment")

# Shared two-sided logging harness: C = client events, S = server events; done() is called once
# per side and prints both logs when the second side finishes.
TWO_SIDED = r"""
const net = require('net');
const S = [], C = [];
let pending = 2;
const done = () => { if (--pending === 0) console.log(['client:', ...C, 'server:', ...S].join('\n')); };
"""


@pytest.mark.parametrize("tier", TIERS)
def test_request_response_lifecycle_event_order(js, golden, tier):
    """CATCHES: a socket that emits connect/ready/finish/end/close out of order, fires 'close' before
    the peer's reply was read, forgets the listen()/connect() callbacks, or reports wrong
    address/family fields for an IPv4 loopback connection."""
    code = TWO_SIDED + r"""
const server = net.createServer((sock) => {
  S.push('connection remote=' + sock.remoteAddress + '/' + sock.remoteFamily + ' local=' + sock.localAddress
    + ' localPortIsServerPort=' + (sock.localPort === server.address().port) + ' remotePort=' + typeof sock.remotePort);
  let req = '';
  sock.on('data', (d) => { req += d; });
  sock.on('end', () => { S.push('end request=' + JSON.stringify(req)); sock.end('echo:' + req.toUpperCase()); });
  sock.on('finish', () => S.push('finish'));
  sock.on('close', (hadError) => {
    S.push('close hadError=' + hadError);
    server.close(() => { S.push('server close callback listening=' + server.listening); done(); });
  });
});
server.on('listening', () => S.push('listening event'));
server.listen(0, '127.0.0.1', () => {
  const a = server.address();
  S.push('listen callback ' + a.address + ' ' + a.family + ' ' + typeof a.port + ' ' + (a.port > 0) + ' listening=' + server.listening);
  const client = net.connect({ port: a.port, host: '127.0.0.1' }, () => C.push('connect callback'));
  C.push('connecting=' + client.connecting + ' readyState=' + client.readyState);
  client.on('connect', () => {
    C.push('connect event readyState=' + client.readyState + ' connecting=' + client.connecting + ' remote=' + client.remoteAddress + ' family=' + client.remoteFamily);
    client.write('hello ', () => C.push('write callback'));
    client.end('world');
  });
  client.on('ready', () => C.push('ready'));
  let resp = '';
  client.on('data', (d) => { resp += d; });
  client.on('finish', () => C.push('finish'));
  client.on('end', () => C.push('end response=' + JSON.stringify(resp)));
  client.on('close', (hadError) => { C.push('close hadError=' + hadError); done(); });
});
"""
    r = js(code, *tier)
    assert out(r) == golden("lifecycle_event_order")
    assert (r.returncode, r.stderr) == (0, b"")


def test_write_encodings_callbacks_and_byte_counters(js, golden):
    """CATCHES: write() ignoring its encoding argument (hex/base64/latin1), mis-counting multi-byte
    UTF-8 in bytesWritten/bytesRead, running write callbacks out of order, or a setEncoding('utf8')
    reader that drops an incomplete trailing sequence instead of emitting U+FFFD at end."""
    code = TWO_SIDED + r"""
const server = net.createServer((c) => {
  const parts = [];
  c.on('data', (d) => parts.push(d));
  c.on('end', () => {
    const all = Buffer.concat(parts);
    S.push('received ' + all.length + ' bytes, bytesRead=' + c.bytesRead);
    S.push('hex ' + all.toString('hex'));
    c.end(Buffer.from([0x68, 0x69, 0xe2, 0x82]));
  });
  c.on('close', () => { server.close(); done(); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => {
    const order = [];
    c.write('héllo', () => order.push('utf8'));
    c.write('414243', 'hex', () => order.push('hex'));
    c.write('3q2+7w==', 'base64', () => order.push('base64'));
    c.write(Buffer.from([0, 255]), () => order.push('buffer'));
    c.write(new Uint8Array([7, 8, 9]), () => order.push('uint8array'));
    c.write('ÿ', 'latin1', () => order.push('latin1'));
    c.end(() => { C.push('callbacks in order: ' + order.join(',')); C.push('bytesWritten=' + c.bytesWritten); });
  });
  c.setEncoding('utf8');
  let text = '';
  c.on('data', (d) => { if (typeof d !== 'string') C.push('NON-STRING CHUNK'); text += d; });
  c.on('end', () => C.push('text ' + JSON.stringify(text) + ' bytesRead=' + c.bytesRead));
  c.on('close', () => done());
});
"""
    r = js(code)
    assert out(r) == golden("write_encodings")
    assert (r.returncode, r.stderr) == (0, b"")


def test_set_encoding_hex_and_latin1_readers(js, golden):
    """CATCHES: setEncoding() that is ignored (Buffers delivered instead of strings) or that decodes
    with the wrong codec, e.g. treating latin1 bytes as UTF-8 or emitting base64 instead of hex."""
    code = TWO_SIDED + r"""
const server = net.createServer((c) => {
  c.setEncoding('latin1');
  let text = '';
  c.on('data', (d) => { text += d; });
  c.on('end', () => {
    S.push('latin1 text ' + JSON.stringify(text) + ' length=' + text.length + ' codes=' + [...text].map((ch) => ch.charCodeAt(0)).join(','));
    c.end(Buffer.from([0xde, 0xad, 0xbe, 0xef, 0x00, 0x01]));
  });
  c.on('close', () => { server.close(); done(); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => c.end(Buffer.from([0x41, 0xe9, 0xff, 0x20, 0xc3, 0xa9])));
  c.setEncoding('hex');
  const types = new Set();
  let hex = '';
  c.on('data', (d) => { types.add(typeof d); hex += d; });
  c.on('end', () => C.push('hex ' + hex + ' chunk types=' + [...types].join(',')));
  c.on('close', () => done());
});
"""
    r = js(code)
    assert out(r) == golden("set_encoding_hex_latin1")
    assert (r.returncode, r.stderr) == (0, b"")


def test_pause_holds_data_and_end_until_resume(js, golden):
    """CATCHES: pause() that does not stop 'data'/'end' delivery (data emitted while paused), an
    isPaused() that lies, or resume() that loses the bytes buffered while the socket was paused."""
    code = TWO_SIDED + r"""
const server = net.createServer((c) => {
  c.pause();
  S.push('paused at connection: ' + c.isPaused());
  let resumed = false, text = '';
  c.on('data', (d) => { if (!resumed) S.push('DATA WHILE PAUSED'); text += d; });
  c.on('end', () => { if (!resumed) S.push('END WHILE PAUSED'); S.push('end text=' + text); c.end('ok:' + text.length); });
  c.on('close', () => { server.close(); done(); });
  c.write('ready');
  setTimeout(() => {
    resumed = true;
    S.push('resuming; isPaused=' + c.isPaused());
    c.resume();
    S.push('after resume isPaused=' + c.isPaused());
  }, 60);
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1');
  let text = '';
  c.on('data', (d) => { text += d; if (text === 'ready') c.end('abc-def'); });
  c.on('end', () => C.push('client text=' + JSON.stringify(text)));
  c.on('close', () => done());
});
"""
    r = js(code)
    assert out(r) == golden("pause_resume")
    assert (r.returncode, r.stderr) == (0, b"")


def test_allow_half_open_server_keeps_writing_after_peer_end(js, golden):
    """CATCHES: a server with allowHalfOpen:true that still auto-ends its side when the client
    half-closes, so the late writes after 'end' are lost or the socket closes too early."""
    code = TWO_SIDED + r"""
const server = net.createServer({ allowHalfOpen: true }, (c) => {
  S.push('connection allowHalfOpen=' + c.allowHalfOpen);
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('end', () => {
    S.push('end got=' + got + ' writable=' + c.writable);
    setTimeout(() => { c.write('late-1;'); c.end('late-2', () => S.push('end callback')); }, 30);
  });
  c.on('finish', () => S.push('finish'));
  c.on('close', (h) => { S.push('close ' + h); server.close(() => { S.push('server closed'); done(); }); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => {
    C.push('connect allowHalfOpen=' + c.allowHalfOpen);
    c.end('ping', () => C.push('end callback readable=' + c.readable));
  });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('finish', () => C.push('finish'));
  c.on('end', () => C.push('end got=' + got));
  c.on('close', (h) => { C.push('close ' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("allow_half_open")
    assert (r.returncode, r.stderr) == (0, b"")


def test_peer_fin_auto_ends_default_socket(js, golden):
    """CATCHES: a default (allowHalfOpen:false) socket that does not end its own side after the
    peer's FIN, so the server never sees 'end' and both sockets stay open forever."""
    code = TWO_SIDED + r"""
const server = net.createServer((sock) => {
  sock.write('bye');
  sock.end();
  sock.on('end', () => S.push('end (client auto-ended)'));
  sock.on('finish', () => S.push('finish'));
  sock.on('close', (h) => { S.push('close ' + h); server.close(done); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1');
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('end', () => C.push('end got=' + got));
  c.on('finish', () => C.push('finish'));
  c.on('close', (h) => { C.push('close ' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("peer_fin_auto_end")
    assert (r.returncode, r.stderr) == (0, b"")


def test_destroy_with_error_emits_error_then_close_true(js, golden):
    """CATCHES: destroy(err) that skips the 'error' event, reports close(hadError=false), is not
    idempotent, or leaves the peer without an EOF so the server never closes."""
    code = TWO_SIDED + r"""
const server = net.createServer((sock) => {
  sock.on('data', (d) => { S.push('data ' + d); sock.write('ack'); });
  sock.on('end', () => S.push('end'));
  sock.on('error', (e) => S.push('UNEXPECTED server error ' + e.message));
  sock.on('close', (h) => { S.push('close ' + h); server.close(done); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => c.write('hi'));
  c.on('data', (d) => {
    C.push('data ' + d);
    const ret = c.destroy(new Error('client gave up'));
    C.push('destroy returned socket: ' + (ret === c) + ' destroyed=' + c.destroyed + ' readyState=' + c.readyState);
    c.destroy(new Error('second destroy is a no-op'));
  });
  c.on('error', (e) => C.push('error ' + e.name + ': ' + e.message));
  c.on('close', (h) => { C.push('close hadError=' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("destroy_with_error")
    assert (r.returncode, r.stderr) == (0, b"")


def test_destroy_before_connect_completes(js, golden):
    """CATCHES: a socket destroyed while still connecting that later fires 'connect' anyway, never
    emits 'close', or accepts writes afterwards without reporting an error to the callback."""
    code = r"""
const net = require('net');
const log = [];
const server = net.createServer((c) => c.on('error', () => {}));
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => log.push('CONNECT CALLBACK (unexpected)'));
  c.on('connect', () => log.push('CONNECT EVENT (unexpected)'));
  c.on('error', () => {});
  log.push('before destroy connecting=' + c.connecting);
  c.destroy();
  log.push('after destroy connecting=' + c.connecting + ' destroyed=' + c.destroyed + ' readyState=' + c.readyState);
  c.on('close', (h) => {
    log.push('close hadError=' + h);
    c.write('late', (e) => {
      log.push('write after destroy fails: ' + (e instanceof Error));
      setTimeout(() => server.close(() => { log.push('server closed'); console.log(log.join('\n')); }), 20);
    });
  });
});
"""
    r = js(code)
    assert out(r) == golden("destroy_before_connect")
    assert (r.returncode, r.stderr) == (0, b"")


def test_connection_refused_error_shape(js, golden):
    """CATCHES: a refused TCP connect that is not reported as an Error with code ECONNREFUSED,
    syscall 'connect', address/port fields and the 'connect ECONNREFUSED host:port' message, or
    that skips the close(hadError=true) event."""
    # The port is held by a UDP socket, so no TCP listener can exist on it: the refusal is certain.
    code = r"""
const net = require('net');
const dgram = require('dgram');
const holder = dgram.createSocket('udp4');
holder.bind(0, '127.0.0.1', () => {
  const port = holder.address().port;
  const c = net.connect({ port, host: '127.0.0.1' });
  c.on('connect', () => console.log('unexpected connect'));
  c.on('error', (e) => {
    console.log('error', e instanceof Error, e.name, e.code, e.syscall, e.address);
    console.log('port field matches:', e.port === port, typeof e.port);
    console.log('message:', e.message.replace(String(port), 'PORT'));
    console.log('destroyed', c.destroyed, 'connecting', c.connecting);
  });
  c.on('close', (h) => { console.log('close hadError=' + h); holder.close(); });
});
"""
    r = js(code)
    assert out(r) == golden("econnrefused")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unix_domain_socket_round_trip(js, golden):
    """CATCHES: Unix-domain listen/connect that is missing or broken: wrong server.address() (must
    be the path string), TCP-only fields filled in for a path socket, lost echo data, or a socket
    file left behind after server.close()."""
    code = TWO_SIDED + r"""
const fs = require('fs');
const server = net.createServer((c) => {
  S.push('connection remoteAddress=' + c.remoteAddress + ' remotePort=' + c.remotePort + ' address()=' + JSON.stringify(c.address()));
  let got = '';
  c.setEncoding('utf8');
  c.on('data', (d) => { got += d; });
  c.on('end', () => { S.push('end ' + got); c.end(got.toUpperCase()); });
  c.on('close', (h) => {
    S.push('close ' + h);
    server.close(() => { S.push('server closed listening=' + server.listening + ' socket file exists=' + fs.existsSync('srv.sock')); done(); });
  });
});
server.listen('srv.sock', () => {
  S.push('listening address=' + JSON.stringify(server.address()) + ' socket file exists=' + fs.existsSync('srv.sock'));
  const c = net.connect('srv.sock', () => {
    C.push('connect remoteAddress=' + c.remoteAddress + ' address()=' + JSON.stringify(c.address()));
    C.push('setNoDelay chains=' + (c.setNoDelay(true) === c) + ' setKeepAlive chains=' + (c.setKeepAlive(true, 500) === c));
    c.end('over unix');
  });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('end', () => C.push('end ' + got + ' bytesRead=' + c.bytesRead + ' bytesWritten=' + c.bytesWritten));
  c.on('close', (h) => { C.push('close ' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("unix_round_trip")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unix_path_errors_enoent_and_eaddrinuse(js, golden):
    """CATCHES: connecting to a missing socket path not failing with ENOENT ('connect ENOENT
    <path>'), or listening on an already-existing path not failing with EADDRINUSE carrying the
    path as `address`."""
    code = r"""
const net = require('net');
const fs = require('fs');
const c = net.connect({ path: 'missing.sock' });
c.on('connect', () => console.log('unexpected connect'));
c.on('error', (e) => console.log('connect error:', e.code, e.syscall, e.address, e.port, JSON.stringify(e.message)));
c.on('close', (h) => {
  console.log('connect close hadError=' + h);
  fs.writeFileSync('taken.sock', 'not a socket');
  const s = net.createServer();
  s.on('listening', () => console.log('unexpected listening'));
  s.on('error', (e) => {
    console.log('listen error:', e.code, e.syscall, e.address, JSON.stringify(e.message), 'listening=' + s.listening);
    console.log('file untouched:', fs.readFileSync('taken.sock', 'utf8'));
  });
  s.listen({ path: 'taken.sock' });
});
"""
    r = js(code)
    assert out(r) == golden("unix_path_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_listen_eaddrinuse_relisten_and_close_not_running(js, golden):
    """CATCHES: a second listen() on a bound TCP port that succeeds or throws synchronously instead
    of emitting an EADDRINUSE 'error', a double listen() on one server that is accepted, or
    close() on a stopped server that does not report ERR_SERVER_NOT_RUNNING."""
    code = r"""
const net = require('net');
const a = net.createServer();
a.listen(0, '127.0.0.1', () => {
  const port = a.address().port;
  const b = net.createServer();
  b.on('listening', () => console.log('unexpected listening'));
  b.on('error', (e) => {
    console.log('listen error:', e.code, e.syscall, e.address, e.port === port, e.message.replace(String(port), 'PORT'));
    console.log('second server listening=' + b.listening + ' address=' + b.address());
    try { a.listen(0, '127.0.0.1'); console.log('relisten accepted'); } catch (e2) { console.log('relisten threw:', e2.message); }
    a.close(() => {
      console.log('closed; listening=' + a.listening + ' address=' + a.address());
      const ret = a.close((e4) => console.log('second close:', e4.code, e4.message));
      console.log('close returns server:', ret === a);
    });
  });
  b.listen(port, '127.0.0.1');
});
"""
    r = js(code)
    assert out(r) == golden("eaddrinuse_and_close")
    assert (r.returncode, r.stderr) == (0, b"")


def test_invalid_connect_arguments_throw(js, golden):
    """CATCHES: connect() accepting out-of-range or non-integer ports instead of throwing a
    RangeError synchronously, or silently accepting the unsupported fd-wrapping/raw-handle APIs."""
    code = r"""
const net = require('net');
const tryIt = (label, f) => {
  try { const r = f(); console.log(label, '-> returned', typeof r); }
  catch (e) { console.log(label, '->', e.name + ':', e.message); }
};
for (const port of [65536, -1, 1.5, 'abc', NaN, 99999]) tryIt('connect port ' + String(port), () => net.connect({ port, host: '127.0.0.1' }));
tryIt('new Socket({fd})', () => new net.Socket({ fd: 3 }));
tryIt('_createServerHandle', () => net._createServerHandle());
tryIt('_setSimultaneousAccepts', () => net._setSimultaneousAccepts(true));
console.log('Stream is Socket:', net.Stream === net.Socket, 'createConnection is connect:', net.createConnection === net.connect);
const n1 = net._normalizeArgs([8080, 'example.test', () => {}]);
console.log('normalize port+host+cb:', JSON.stringify(n1[0]), typeof n1[1], n1[Symbol.for('normalizedArgs')]);
const n2 = net._normalizeArgs(['some.sock']);
console.log('normalize path:', JSON.stringify(n2[0]), n2[1]);
const n3 = net._normalizeArgs(['4000']);
console.log('normalize numeric string:', JSON.stringify(n3[0]));
const n4 = net._normalizeArgs([]);
console.log('normalize empty:', JSON.stringify(n4[0]), n4[1], n4[Symbol.for('normalizedArgs')]);
"""
    r = js(code)
    assert out(r) == golden("invalid_arguments")
    assert (r.returncode, r.stderr) == (0, b"")


def test_socket_timeout_keepalive_nodelay(js, golden):
    """CATCHES: setTimeout() idle timers that never fire, fire while traffic flows, destroy the
    socket on their own, or are not cancelled by setTimeout(0); and setNoDelay/setKeepAlive that are
    not chainable or break a socket when called before it connects."""
    code = TWO_SIDED + r"""
const server = net.createServer((c) => {
  S.push('connection');
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('end', () => S.push('end got=' + got));
  c.on('close', (h) => { S.push('close ' + h); server.close(() => { S.push('server closed'); done(); }); });
});
server.listen(0, '127.0.0.1', () => {
  const c = new net.Socket();
  C.push('before connect readyState=' + c.readyState + ' pending=' + c.pending + ' address()=' + JSON.stringify(c.address()) + ' remoteAddress=' + c.remoteAddress);
  C.push('chainable before connect: ' + (c.setNoDelay() === c) + ' ' + (c.setKeepAlive(true, 2000) === c) + ' ' + (c.setTimeout(100) === c));
  c.connect(server.address().port, '127.0.0.1', () => {
    C.push('connect readyState=' + c.readyState + ' pending=' + c.pending);
    C.push('chainable after connect: ' + (c.setNoDelay(false) === c) + ' ' + (c.setKeepAlive(false) === c) + ' ' + (c.setKeepAlive(true, 1500) === c));
    c.write('one;');
  });
  let timeouts = 0;
  c.on('timeout', () => {
    timeouts++;
    C.push('timeout #' + timeouts + ' destroyed=' + c.destroyed);
    if (timeouts === 1) c.write('two;');
    else {
      c.setTimeout(0);
      setTimeout(() => { C.push('no further timeouts after setTimeout(0): ' + (timeouts === 2)); c.end('three'); }, 80);
    }
  });
  c.on('close', (h) => { C.push('close ' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("timeout_keepalive_nodelay")
    assert (r.returncode, r.stderr) == (0, b"")


def test_get_connections_and_close_waits_for_open_sockets(js, golden):
    """CATCHES: getConnections() returning stale counts, server.close() emitting 'close' (or
    running its callback) while accepted connections are still open, or a closed server that
    still reports itself as listening with an address."""
    code = r"""
const net = require('net');
const log = [];
const server = net.createServer();
let remaining = 4;
const finish = () => { if (--remaining === 0) console.log(log.join('\n')); };
server.on('connection', (c) => {
  c.on('data', (d) => {
    server.getConnections((err, n) => { log.push('server got ' + d + ' connections=' + n + ' err=' + err); c.write('ack ' + d); });
  });
});
server.on('close', () => log.push('server close event'));
server.listen(0, '127.0.0.1', () => {
  const port = server.address().port;
  const clients = [];
  const open = (i) => new Promise((res) => {
    const c = net.connect(port, '127.0.0.1', () => c.write('c' + i));
    c.once('data', (d) => { log.push('client' + i + ' ' + d); res(c); });
    clients.push(c);
  });
  (async () => {
    for (let i = 1; i <= 3; i++) await open(i);
    server.close((err) => { log.push('close callback err=' + err + ' listening=' + server.listening); finish(); });
    log.push('close() called: listening=' + server.listening + ' address=' + server.address());
    server.getConnections((e, n) => {
      log.push('still open after close(): ' + n);
      for (const c of clients) c.on('close', finish);
      for (const c of clients) c.end();
    });
  })();
});
"""
    r = js(code)
    assert out(r) == golden("get_connections_close")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unref_server_and_sockets_let_process_exit(js, golden):
    """CATCHES: unref() on servers/sockets that still keeps the event loop alive (the program would
    hang), or ref()/unref() toggles that throw or forget the latest state when the pending accept
    or read is re-armed."""
    code = r"""
const net = require('net');
const server = net.createServer((c) => {
  c.unref(); c.ref(); c.unref();
  c.write('hello from an unref\'d server socket');
});
server.listen(0, '127.0.0.1', () => {
  console.log('listening');
  server.unref(); server.ref(); server.unref();
  const c = net.connect(server.address().port, '127.0.0.1');
  c.ref();
  c.once('data', (d) => {
    console.log('client got:', String(d));
    c.unref(); c.ref(); c.unref();
    setTimeout(() => console.log('last timer fired; only unref\'d handles remain'), 20);
  });
});
"""
    r = js(code)
    assert out(r) == golden("unref_exit")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_large_payload_round_trip(js, golden, tier):
    """CATCHES: chunked reads/writes that drop, duplicate or reorder bytes of a 140 KB transfer, or
    bytesRead/bytesWritten counters that diverge from the bytes actually moved."""
    code = TWO_SIDED + r"""
const N = 140000;
const payload = Buffer.alloc(N, 'The quick brown fox jumps over the lazy dog. 0123456789\n');
let sum = 0;
for (let i = 0; i < N; i += 997) sum = (sum * 31 + payload[i]) % 1000003;
const server = net.createServer((c) => {
  let n = 0;
  c.on('data', (d) => { n += d.length; c.write(d); });
  c.on('end', () => { S.push('server saw ' + n + ' bytes, bytesRead=' + c.bytesRead); c.end(); });
  c.on('close', () => { S.push('server bytesWritten=' + c.bytesWritten); server.close(); done(); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1');
  const chunks = [];
  c.on('connect', () => c.end(payload));
  c.on('data', (d) => chunks.push(d));
  c.on('end', () => {
    const all = Buffer.concat(chunks);
    let s2 = 0;
    for (let i = 0; i < all.length; i += 997) s2 = (s2 * 31 + all[i]) % 1000003;
    C.push('echoed ' + all.length + ' bytes, identical=' + all.equals(payload) + ' sample checksum match=' + (s2 === sum));
    C.push('tail ' + JSON.stringify(all.subarray(all.length - 12).toString()));
    C.push('bytesRead=' + c.bytesRead + ' bytesWritten=' + c.bytesWritten);
  });
  c.on('close', () => done());
});
"""
    r = js(code, *tier)
    assert out(r) == golden("large_payload")
    assert (r.returncode, r.stderr) == (0, b"")


def test_epipe_when_writing_to_destroyed_peer(js, golden):
    """CATCHES: writes to a peer that has fully closed (RST received) that report success forever
    instead of failing with EPIPE (syscall 'write', message 'write EPIPE') on the callback and the
    'error' event."""
    code = r"""
const net = require('net');
const log = [];
let cbErr = null, evErr = null;
const server = net.createServer((c) => {
  c.on('data', (d) => { log.push('server got ' + d); setTimeout(() => c.destroy(), 5); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect({ port: server.address().port, host: '127.0.0.1', allowHalfOpen: true }, () => c.write('hello'));
  const settle = () => {
    if (!cbErr || !evErr) return;
    log.push('second write callback: ' + cbErr.code + ' syscall=' + cbErr.syscall + ' message=' + cbErr.message);
    log.push('error event carries the same error: ' + (cbErr === evErr));
    c.destroy();
  };
  c.on('end', () => {
    log.push('end (peer destroyed its socket)');
    c.write('first write after peer close', (e) => {
      log.push('first write callback: ' + (e ? e.code : 'ok'));
      setTimeout(() => c.write('second', (e2) => { cbErr = e2; settle(); }), 25);
    });
  });
  c.on('error', (e) => { evErr = e; settle(); });
  c.on('close', () => { log.push('close destroyed=' + c.destroyed); server.close(() => console.log(log.join('\n'))); });
});
"""
    r = js(code)
    assert out(r) == golden("epipe")
    assert (r.returncode, r.stderr) == (0, b"")


def test_is_ip_family_detection(js, golden):
    """CATCHES: IP validators that accept out-of-range IPv4 octets, too few/many groups, double
    '::' compressions or non-hex IPv6 groups, or that return booleans instead of 0/4/6 from isIP."""
    code = r"""
const net = require('net');
const cases = ['127.0.0.1', '0.0.0.0', '255.255.255.255', '256.1.1.1', '1.2.3', '1.2.3.4.5', '1.1.1.1.',
  '::', '::1', 'fe80::1', '2001:db8::8a2e:370:7334', '1:2:3:4:5:6:7:8', '1:2:3:4:5:6:7:8:9', '1::2::3',
  'gggg::1', '2001:0db8:85a3:0000:0000:8a2e:0370:7334', '', 'abc', '1.2.3.4 ', 123, null, undefined, {}];
for (const c of cases) {
  const label = c === undefined ? 'undefined' : JSON.stringify(c);
  console.log(label.padEnd(42), net.isIP(c), net.isIPv4(c), net.isIPv6(c));
}
"""
    r = js(code)
    assert out(r) == golden("is_ip")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_block_list_rules_and_matching(js, golden, tier):
    """CATCHES: BlockList matching that ignores range bounds, CIDR masks or the address family,
    lists rules in insertion order instead of newest-first, or accepts invalid ranges/prefixes."""
    code = r"""
const net = require('net');
const bl = new net.BlockList();
bl.addAddress('10.0.0.5');
bl.addRange('192.168.1.10', '192.168.1.20');
bl.addSubnet('172.16.0.0', 12);
bl.addSubnet('2001:db8::', 32, 'ipv6');
bl.addAddress('::1', 'ipv6');
bl.addSubnet(new net.SocketAddress({ address: '100.64.0.0' }), 10);
console.log(JSON.stringify(bl.rules, null, 1));
const probes = [['10.0.0.5'], ['10.0.0.6'], ['192.168.1.9'], ['192.168.1.10'], ['192.168.1.20'], ['192.168.1.21'],
  ['172.16.0.0'], ['172.31.255.255'], ['172.32.0.0'], ['100.127.1.1'], ['100.128.0.0'],
  ['2001:db8:ffff::1', 'ipv6'], ['2001:db9::', 'ipv6'], ['::1', 'ipv6'], ['::2', 'ipv6'], ['10.0.0.5', 'ipv6'],
  ['not-an-ip', 'ipv4']];
for (const [a, f] of probes) console.log('check', a, f || '(auto)', bl.check(a, f));
console.log('check SocketAddress', bl.check(new net.SocketAddress({ address: '192.168.1.15', port: 1 })));
const all = new net.BlockList();
all.addSubnet('0.0.0.0', 0);
console.log('/0 matches anything v4:', all.check('203.0.113.7'), 'but not v6:', all.check('::1', 'ipv6'));
for (const f of [() => bl.addRange('10.0.0.9', '10.0.0.1'), () => bl.addSubnet('10.0.0.0', 33), () => bl.addAddress('1.2.3.4', 'ipx'), () => bl.addAddress('1.2.3', 'ipv4')]) {
  try { f(); console.log('no throw'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
console.log('rules after failed adds:', bl.rules.length);
"""
    r = js(code, *tier)
    assert out(r) == golden("block_list")
    assert (r.returncode, r.stderr) == (0, b"")


def test_socket_address_and_auto_select_family_settings(js, golden):
    """CATCHES: a SocketAddress with wrong defaults (127.0.0.1 / '::', port 0, flowlabel 0), that
    accepts an address of the wrong family, or parse() that mis-splits host:port; and
    auto-select-family setters that do not round-trip or clamp the attempt timeout."""
    code = r"""
const net = require('net');
const show = (sa) => sa === undefined ? 'undefined' : `${sa.address}|${sa.port}|${sa.family}|${sa.flowlabel}`;
console.log('default', show(new net.SocketAddress()));
console.log('ipv6 default', show(new net.SocketAddress({ family: 'ipv6' })));
console.log('explicit', show(new net.SocketAddress({ address: '10.0.0.5', port: 8080 })));
console.log('IPV6 family case-insensitive', show(new net.SocketAddress({ family: 'IPv6', address: 'fe80::1', port: 443, flowlabel: 7 })));
for (const t of ['1.2.3.4:80', '[::1]:443', '[fe80::1]', '9.9.9.9', 'fe80::2', 'nope', '1.2.3.4:x', '999.1.1.1:5']) console.log('parse', JSON.stringify(t), show(net.SocketAddress.parse(t)));
for (const f of [() => new net.SocketAddress({ family: 'ipx' }), () => new net.SocketAddress({ address: '1.2.3' }), () => new net.SocketAddress({ family: 'ipv6', address: '10.0.0.1' })]) {
  try { f(); console.log('no throw'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
console.log('autoSelectFamily', net.getDefaultAutoSelectFamily(), net.getDefaultAutoSelectFamilyAttemptTimeout());
net.setDefaultAutoSelectFamily(0);
net.setDefaultAutoSelectFamilyAttemptTimeout(5);
console.log('after set', net.getDefaultAutoSelectFamily(), net.getDefaultAutoSelectFamilyAttemptTimeout());
net.setDefaultAutoSelectFamily('yes');
net.setDefaultAutoSelectFamilyAttemptTimeout(300);
console.log('after set again', net.getDefaultAutoSelectFamily(), net.getDefaultAutoSelectFamilyAttemptTimeout());
for (const v of [0, -5, 2.5, 'x']) {
  try { net.setDefaultAutoSelectFamilyAttemptTimeout(v); console.log('accepted', v); } catch (e) { console.log(e.name + ': ' + e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("socket_address")
    assert (r.returncode, r.stderr) == (0, b"")


@needs_ipv6
def test_ipv6_loopback_connection_and_unspecified_listener(js, golden):
    """CATCHES: IPv6 sockets reported with family 'IPv4' (or wrong address strings) on ::1, or a
    server listening on '::' whose close() cannot wake its pending accept and so hangs the process."""
    code = TWO_SIDED + r"""
const server = net.createServer((c) => {
  S.push('connection ' + c.remoteAddress + ' ' + c.remoteFamily + ' local ' + c.localAddress + ' ' + JSON.stringify(Object.keys(c.address())));
  S.push('server-side address() ' + c.address().address + ' ' + c.address().family);
  c.on('data', (d) => c.end('v6:' + d));
  c.on('close', () => {
    server.close(() => {
      const any = net.createServer();
      any.listen(0, '::', () => {
        S.push('wildcard listener ' + any.address().address + ' ' + any.address().family);
        any.close(() => { S.push('wildcard listener closed'); done(); });
      });
    });
  });
});
server.listen(0, '::1', () => {
  const a = server.address();
  S.push('listening ' + a.address + ' ' + a.family + ' ' + (a.port > 0));
  const c = net.connect({ port: a.port, host: '::1' }, () => {
    C.push('connected ' + c.remoteAddress + ' ' + c.remoteFamily + ' local ' + c.localAddress);
    C.push('address() ' + c.address().address + ' ' + c.address().family);
    c.write('ping');
  });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('close', () => { C.push('got ' + got); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("ipv6_loopback")
    assert (r.returncode, r.stderr) == (0, b"")


def test_wildcard_ipv4_and_default_host_listeners(js, golden):
    """CATCHES: a server bound to 0.0.0.0 (explicitly or via the default host) that is unreachable
    on 127.0.0.1, reports a different bound address, or whose close() hangs because the wake-up
    connection targets the unspecified address."""
    code = r"""
const net = require('net');
const log = [];
const echoOnce = (server, label) => new Promise((res) => {
  const c = net.connect(server.address().port, '127.0.0.1', () => c.end(label));
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('close', () => { log.push(label + ' -> ' + got); res(); });
});
const handler = (c) => { let s = ''; c.on('data', (d) => { s += d; }); c.on('end', () => c.end('[' + s + ']')); };
const a = net.createServer(handler);
a.listen({ port: 0, host: '0.0.0.0' }, async () => {
  log.push('explicit wildcard address=' + a.address().address + ' family=' + a.address().family);
  await echoOnce(a, 'explicit');
  const b = net.createServer(handler);
  b.listen(0, async () => {
    log.push('default host family=' + typeof b.address().family + ' port>0=' + (b.address().port > 0));
    await echoOnce(b, 'default-host');
    a.close(() => b.close(() => { log.push('both closed'); console.log(log.join('\n')); }));
  });
});
"""
    r = js(code)
    assert out(r) == golden("wildcard_listeners")
    assert (r.returncode, r.stderr) == (0, b"")


def test_address_objects_agree_between_peers(js, golden):
    """CATCHES: address()/localPort/remotePort fields that disagree between the two ends of one
    connection (client local == server remote and vice versa), or address() objects with a
    different key set/order than {address, family, port}."""
    code = r"""
const net = require('net');
const server = net.createServer((sc) => {
  sc.on('data', () => {
    const cc = client;
    const ca = cc.address(), sa = sc.address();
    console.log('client address() keys', JSON.stringify(Object.keys(ca)));
    console.log('server-side address() keys', JSON.stringify(Object.keys(sa)));
    console.log('client local == server remote:', ca.port === sc.remotePort, cc.localPort === sc.remotePort, cc.localAddress === sc.remoteAddress);
    console.log('server local == client remote:', sa.port === cc.remotePort, sc.localPort === cc.remotePort);
    console.log('server-side local port is the listening port:', sa.port === server.address().port);
    console.log('client localFamily', cc.localFamily, 'remoteFamily', cc.remoteFamily, 'server address() family', sa.family);
    console.log('ports differ:', ca.port !== sa.port);
    sc.end();
  });
  sc.on('close', () => server.close(() => console.log('done; server address() now', server.address())));
});
let client;
server.listen(0, '127.0.0.1', () => {
  console.log('server.address() keys', JSON.stringify(Object.keys(server.address())));
  client = net.connect(server.address().port, '127.0.0.1', () => client.write('x'));
  client.on('close', () => console.log('client closed; address() now', JSON.stringify(client.address())));
});
"""
    r = js(code)
    assert out(r) == golden("address_objects")
    assert (r.returncode, r.stderr) == (0, b"")


def test_tls_upgrade_takes_over_accepted_socket(js, golden):
    """CATCHES: tls.connect({socket}) over an accepted net.Socket that does not hand the native TCP
    stream to TLS (no ClientHello reaches the peer), or never reports the failed handshake as an
    'error' followed by close(hadError=true)."""
    code = TWO_SIDED + r"""
const tls = require('tls');
const server = net.createServer((c) => {
  S.push('connection');
  const t = tls.connect({ socket: c, servername: 'example.test' });
  S.push('tls socket encrypted=' + t.encrypted);
  t.on('secureConnect', () => S.push('UNEXPECTED secureConnect'));
  t.on('error', (e) => S.push('tls error is an Error: ' + (e instanceof Error)));
  t.on('close', (h) => { S.push('tls close hadError=' + h); server.close(); done(); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1');
  c.once('data', (d) => { C.push('first byte is a TLS handshake record: ' + (d[0] === 0x16)); c.destroy(); });
  c.on('close', (h) => { C.push('client close ' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("tls_upgrade")
    assert (r.returncode, r.stderr) == (0, b"")


def test_peer_reset_surfaces_as_econnreset(js, golden):
    """CATCHES: a connection reset by the peer (it closed with our bytes still unread) being
    reported as a clean EOF instead of an 'error' with code ECONNRESET, syscall 'read' and message
    'read ECONNRESET', followed by close(hadError=true)."""
    # The server hands its socket to TLS, which rejects the client's plaintext after reading only
    # the record header and closes with the rest unread, so the kernel answers with a RST.
    code = TWO_SIDED + r"""
const tls = require('tls');
const server = net.createServer((c) => {
  const t = tls.connect({ socket: c, servername: 'example.test' });
  t.on('error', () => S.push('tls handshake failed'));
  t.on('close', (h) => { S.push('tls close ' + h); server.close(); done(); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => c.write(Buffer.alloc(8192, 'plaintext, not a TLS ServerHello record\n')));
  c.on('end', () => C.push('UNEXPECTED clean end'));
  c.on('error', (e) => C.push('error ' + e.code + ' syscall=' + e.syscall + ' message=' + e.message));
  c.on('close', (h) => { C.push('close hadError=' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("econnreset")
    assert (r.returncode, r.stderr) == (0, b"")


def test_tls_upgrade_of_unix_socket_is_rejected(js, golden):
    """CATCHES: tls.connect({socket}) over a Unix-domain connection that pretends to start a TLS
    session (or crashes) instead of failing with 'Unix sockets cannot be upgraded to TLS' and
    closing the stream so the peer sees EOF."""
    code = TWO_SIDED + r"""
const tls = require('tls');
const server = net.createServer((c) => {
  const t = tls.connect({ socket: c });
  t.on('secureConnect', () => S.push('UNEXPECTED secureConnect'));
  t.on('error', (e) => S.push('tls error: ' + e.message));
  t.on('close', (h) => { S.push('tls close hadError=' + h); server.close(); done(); });
});
server.listen('upgrade.sock', () => {
  const c = net.connect('upgrade.sock');
  let n = 0;
  c.on('data', (d) => { n += d.length; });
  c.on('end', () => C.push('end after ' + n + ' bytes'));
  c.on('close', (h) => { C.push('close hadError=' + h); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("tls_upgrade_unix")
    assert (r.returncode, r.stderr) == (0, b"")


def test_connect_to_unresolvable_host_reports_enotfound(js, golden):
    """CATCHES: a connect whose hostname cannot be resolved that hangs, throws synchronously, or
    reports a connect error instead of an ENOTFOUND 'getaddrinfo' error carrying the host/port."""
    # A NUL byte makes the name unresolvable before any resolver (or network) is consulted.
    code = r"""
const net = require('net');
const c = net.connect({ host: 'bad\u0000host', port: 4321 });
console.log('connecting', c.connecting);
c.on('connect', () => console.log('UNEXPECTED connect'));
c.on('error', (e) => console.log('error', e.code, e.syscall, JSON.stringify(e.address), e.port, JSON.stringify(e.message)));
c.on('close', (h) => console.log('close hadError=' + h, 'connecting=' + c.connecting));
"""
    r = js(code)
    assert out(r) == golden("enotfound")
    assert (r.returncode, r.stderr) == (0, b"")


def test_socket_constructor_connect_overloads(js, golden):
    """CATCHES: connect() overloads (port, host, cb) / (options, cb) / numeric-string port that
    mis-parse their arguments, a readyState that does not move opening -> open, a returned object
    that is not the net.Socket, or a Socket that is not a Duplex stream."""
    code = r"""
const net = require('net');
const { Duplex } = require('stream');
const log = [];
const server = net.createServer({ allowHalfOpen: true }, (c) => {
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('end', () => { setTimeout(() => c.end('reply to ' + got), 20); });
});
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const s = new net.Socket();
  log.push('instanceof Duplex=' + (s instanceof Duplex) + ' Stream=' + (s instanceof net.Stream) + ' readyState=' + s.readyState);
  const variants = [
    (cb) => s.connect(port, '127.0.0.1', cb),
    (cb) => net.createConnection({ port, host: '127.0.0.1' }, cb),
    (cb) => net.connect(String(port), '127.0.0.1', cb),
  ];
  for (let i = 0; i < variants.length; i++) {
    await new Promise((res) => {
      let sock;
      sock = variants[i](() => {
        log.push('variant ' + i + ' connected readyState=' + sock.readyState + ' remotePortOk=' + (sock.remotePort === port));
        sock.end('v' + i, () => log.push('variant ' + i + ' end callback'));
      });
      log.push('variant ' + i + ' returned socket=' + (sock instanceof net.Socket) + ' same as s=' + (sock === s) + ' readyState=' + sock.readyState);
      let reply = '';
      sock.on('data', (d) => { reply += d; });
      sock.on('close', () => { log.push('variant ' + i + ' reply=' + JSON.stringify(reply)); res(); });
    });
  }
  server.close(() => console.log(log.join('\n')));
});
"""
    r = js(code)
    assert out(r) == golden("connect_overloads")
    assert (r.returncode, r.stderr) == (0, b"")


def test_write_after_end_reports_error_to_callback(js, golden):
    """CATCHES: a socket that still sends data written after end() (the server would see it) or
    that silently drops it without passing a 'write after end' error to the write callback."""
    code = TWO_SIDED + r"""
const server = net.createServer((sock) => {
  let got = '';
  sock.on('data', (d) => { got += d; });
  sock.on('end', () => { S.push('server received ' + JSON.stringify(got)); sock.end(); });
  sock.on('close', () => { server.close(); done(); });
});
server.listen(0, '127.0.0.1', () => {
  const c = net.connect(server.address().port, '127.0.0.1', () => {
    c.end('only-this');
    c.write('too late', (e) => C.push('write callback: ' + (e instanceof Error) + ' ' + (e && e.message)));
  });
  c.on('error', () => {});
  c.on('close', () => { C.push('client closed'); done(); });
});
"""
    r = js(code)
    assert out(r) == golden("write_after_end")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sequential_clients_get_isolated_streams(js, golden):
    """CATCHES: a server that mixes up data between concurrent connections, reuses socket state
    across connections, or stops accepting after the first client."""
    code = r"""
const net = require('net');
let seq = 0;
const server = net.createServer((c) => {
  const id = ++seq;
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('end', () => c.end(`conn#${id} saw ${got.length} chars: ${got.split('').reverse().join('')}`));
});
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const ask = (msg) => new Promise((res) => {
    const c = net.connect(port, '127.0.0.1', () => { for (const part of msg.split(' ')) c.write(part + '_'); c.end(); });
    let r = '';
    c.on('data', (d) => { r += d; });
    c.on('close', () => res(r));
  });
  const results = [];
  for (const m of ['alpha beta', 'gamma', 'delta epsilon zeta', 'eta']) results.push(await ask(m));
  const parallel = await Promise.all(['one two', 'three', 'four five six'].map(ask));
  console.log(results.join('\n'));
  console.log(parallel.map((s) => s.replace(/^conn#\d+/, 'conn#N')).join('\n'));
  server.getConnections((e, n) => { console.log('connections left', n); server.close(() => console.log('closed')); });
});
"""
    r = js(code)
    assert out(r) == golden("sequential_clients")
    assert (r.returncode, r.stderr) == (0, b"")


def test_end_overloads_with_encoding_and_callback(js, golden):
    """CATCHES: end(data, encoding, cb) / end(data, cb) / end(cb) overloads that ignore the encoding,
    drop the final chunk, or never invoke the callback once the socket has finished."""
    code = r"""
const net = require('net');
const log = [];
const server = net.createServer((c) => {
  const parts = [];
  c.on('data', (d) => parts.push(d));
  c.on('end', () => c.end(Buffer.concat(parts).toString('hex')));
});
server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const run = (label, fn) => new Promise((res) => {
    const c = net.connect(port, '127.0.0.1', () => fn(c, () => log.push(label + ' end callback')));
    let r = '';
    c.on('data', (d) => { r += d; });
    c.on('close', () => { log.push(label + ' server saw hex ' + r); res(); });
  });
  await run('hex', (c, cb) => c.end('cafe', 'hex', cb));
  await run('base64', (c, cb) => c.end('AQID', 'base64', cb));
  await run('utf8', (c, cb) => c.end('ok', cb));
  await run('write-then-end', (c, cb) => { c.write('ab'); c.end(cb); });
  server.close(() => console.log(log.join('\n')));
});
"""
    r = js(code)
    assert out(r) == golden("end_overloads")
    assert (r.returncode, r.stderr) == (0, b"")


# ---- UDP (node:dgram) — the __udp half of net.rs ------------------------------------------------


def test_dgram_round_trip_after_idle_polls(js, golden):
    """CATCHES: a UDP receive loop that gives up or errors when its periodic poll times out while
    idle (so a datagram sent after ~0.45 s is never delivered), wrong rinfo fields, send callbacks
    without byte counts, or datagrams still delivered to a socket that was just closed."""
    # Message deliveries (A) and send callbacks (SENDS) race each other, so they are kept apart.
    code = r"""
const dgram = require('dgram');
const a = dgram.createSocket('udp4');
const b = dgram.createSocket({ type: 'udp4' });
const A = [], SENDS = [];
let steps = 3;
const step = () => { if (--steps === 0) console.log([...A, 'send callbacks:', ...SENDS.sort()].join('\n')); };
a.on('message', (msg, rinfo) => {
  A.push('a got ' + JSON.stringify(msg.toString()) + ' size=' + rinfo.size + ' family=' + rinfo.family + ' address=' + rinfo.address + ' fromB=' + (rinfo.port === b.address().port));
  a.send('pong:' + msg, rinfo.port, rinfo.address, (err, n) => { SENDS.push('a->b err=' + err + ' bytes=' + n); step(); });
});
b.on('message', (msg, rinfo) => {
  A.push('b got ' + msg + ' size=' + rinfo.size);
  const port = a.address().port;
  a.close(() => {
    A.push('a closed');
    b.send('into the void', port, '127.0.0.1', () => {
      setTimeout(() => b.close(() => { A.push('b closed'); step(); }), 30);
    });
  });
});
a.on('close', () => a.on('message', () => A.push('UNEXPECTED message after close')));
a.bind(0, '127.0.0.1', () => {
  b.bind({ port: 0, address: '127.0.0.1' }, () => {
    A.push('bound: ' + a.address().family + ' ' + b.address().address);
    setTimeout(() => {
      b.send(Buffer.from('xxpingxx'), 2, 4, a.address().port, '127.0.0.1', (err, n) => { SENDS.push('b->a err=' + err + ' bytes=' + n); step(); });
    }, 450);
  });
});
"""
    r = js(code)
    assert out(r) == golden("dgram_idle_round_trip")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dgram_unref_socket_lets_process_exit(js, golden):
    """CATCHES: dgram unref() that does not carry over to the re-armed receive, so a socket that
    keeps delivering messages after unref() still holds the process open forever."""
    code = r"""
const dgram = require('dgram');
const rx = dgram.createSocket('udp4');
const tx = dgram.createSocket('udp4');
const got = [];
rx.on('message', (m) => {
  got.push(String(m));
  if (got.length === 1) {
    rx.unref();
    tx.send('second', rx.address().port, '127.0.0.1');
  } else {
    console.log('received', got.join(' + '), 'while unref\'d');
    tx.close(() => console.log('sender closed; the unref\'d receiver must not keep the process alive'));
  }
});
rx.bind(0, '127.0.0.1', () => {
  rx.unref(); rx.ref();
  tx.send('first', rx.address().port, '127.0.0.1');
});
"""
    r = js(code)
    assert out(r) == golden("dgram_unref")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dgram_bind_conflict_and_unresolvable_destination(js, golden):
    """CATCHES: binding a UDP port that is already taken without an EADDRINUSE 'error' event
    (message 'bind EADDRINUSE host:port'), or a send to an unresolvable host that is reported
    as success instead of an ENOTFOUND getaddrinfo error on the callback."""
    code = r"""
const dgram = require('dgram');
const s = dgram.createSocket('udp4');
s.bind(0, '127.0.0.1', () => {
  const port = s.address().port;
  const t = dgram.createSocket('udp4');
  t.on('listening', () => console.log('UNEXPECTED listening'));
  t.on('error', (e) => {
    console.log('bind error:', e.code, e.syscall, e.address, e.port === port, e.message.replace(String(port), 'PORT'));
    s.send('x', 9, 'bad\u0000host', (e2, n) => {
      console.log('send error:', e2.code, e2.syscall, JSON.stringify(e2.address), e2.port, JSON.stringify(e2.message), n);
      s.close(() => console.log('closed'));
    });
  });
  t.bind(port, '127.0.0.1');
});
"""
    r = js(code)
    assert out(r) == golden("dgram_bind_conflict")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dgram_udp4_multicast_membership_on_loopback(js, golden):
    """CATCHES: IPv4 multicast join/leave (including source-specific membership) that is a no-op or
    maps kernel errors to the wrong code (double join EADDRINUSE, leaving a group never joined
    EADDRNOTAVAIL), or interface/TTL setters that accept invalid input."""
    code = r"""
const dgram = require('dgram');
const s = dgram.createSocket('udp4');
const t = (label, f) => {
  try { const r = f(); console.log(label, 'ok', r === s ? 'this' : r); }
  catch (e) { console.log(label, 'threw', e.name, e.code, e.syscall, JSON.stringify(e.message)); }
};
s.bind(0, '127.0.0.1', () => {
  t('ssm join', () => s.addSourceSpecificMembership('127.0.0.1', '232.1.2.3', '127.0.0.1'));
  t('ssm drop', () => s.dropSourceSpecificMembership('127.0.0.1', '232.1.2.3', '127.0.0.1'));
  t('ssm bad source', () => s.addSourceSpecificMembership('nope', '232.1.2.3'));
  t('ssm non-multicast group', () => s.addSourceSpecificMembership('127.0.0.1', '10.1.2.3'));
  t('ssm bad interface', () => s.addSourceSpecificMembership('127.0.0.1', '232.1.2.3', 'eth0'));
  t('ssm unparsable group', () => s.addSourceSpecificMembership('127.0.0.1', 'bogus'));
  t('ssm drop never joined', () => s.dropSourceSpecificMembership('127.0.0.1', '232.9.9.9', '127.0.0.1'));
  t('join', () => s.addMembership('224.1.2.3', '127.0.0.1'));
  t('join again', () => s.addMembership('224.1.2.3', '127.0.0.1'));
  t('drop', () => s.dropMembership('224.1.2.3', '127.0.0.1'));
  t('drop again', () => s.dropMembership('224.1.2.3', '127.0.0.1'));
  t('join bad group', () => s.addMembership('224.1.2', '127.0.0.1'));
  t('join bad interface', () => s.addMembership('224.1.2.3', 'lo'));
  t('setMulticastInterface', () => s.setMulticastInterface('127.0.0.1'));
  t('setMulticastInterface bad', () => s.setMulticastInterface('nope'));
  t('setMulticastInterface non-local', () => s.setMulticastInterface('10.255.255.1'));
  t('setMulticastTTL', () => s.setMulticastTTL(3));
  t('setMulticastTTL 256', () => s.setMulticastTTL(256));
  t('setMulticastLoopback', () => s.setMulticastLoopback(false));
  t('setTTL', () => s.setTTL(64));
  t('setTTL 0', () => s.setTTL(0));
  t('setBroadcast', () => s.setBroadcast(true));
  t('buffer sizes', () => { s.setRecvBufferSize(65536); s.setSendBufferSize(65536); return [s.getRecvBufferSize() > 0, s.getSendBufferSize() > 0].join(); });
  t('buffer size 0', () => s.setRecvBufferSize(0));
  s.close(() => {
    console.log('closed');
    t('setTTL after close', () => s.setTTL(5));
    t('address after close', () => s.address());
    t('send after close', () => s.send('x', 9, '127.0.0.1'));
    t('close again', () => s.close());
  });
});
"""
    r = js(code)
    assert out(r) == golden("dgram_udp4_multicast")
    assert (r.returncode, r.stderr) == (0, b"")


@needs_ipv6
def test_dgram_udp6_socket_options_and_round_trip(js, golden):
    """CATCHES: udp6 sockets that bind to the IPv4 wildcard, use the IPv4 TTL/loopback setters
    (which fail on IPv6 sockets), accept non-numeric IPv6 multicast interfaces, permit
    source-specific multicast, or cannot exchange datagrams over ::1."""
    code = r"""
const dgram = require('dgram');
const s = dgram.createSocket('udp6');
const t = (label, f) => {
  try { const r = f(); console.log(label, 'ok', r === s ? 'this' : r); }
  catch (e) { console.log(label, 'threw', e.name, e.code, e.syscall, JSON.stringify(e.message)); }
};
s.bind(0, () => {
  const a = s.address();
  console.log('bound', a.address, a.family, a.port > 0);
  t('setTTL', () => s.setTTL(64));
  t('setMulticastTTL', () => s.setMulticastTTL(2));
  t('setMulticastLoopback true', () => s.setMulticastLoopback(true));
  t('setMulticastLoopback false', () => s.setMulticastLoopback(false));
  t('setMulticastInterface %1', () => s.setMulticastInterface('%1'));
  t('setMulticastInterface ::%lo', () => s.setMulticastInterface('::%lo'));
  t('addMembership ff02::1:3 on 1', () => s.addMembership('ff02::1:3', '1'));
  t('dropMembership ff02::1:3 on 1', () => s.dropMembership('ff02::1:3', '1'));
  t('addMembership bad', () => s.addMembership('not-an-ip'));
  t('addMembership v4 group', () => s.addMembership('224.0.0.1'));
  t('ssm', () => s.addSourceSpecificMembership('10.0.0.1', '232.1.1.1'));
  t('ssm drop', () => s.dropSourceSpecificMembership('10.0.0.1', '232.1.1.1', '127.0.0.1'));
  const peer = dgram.createSocket('udp6');
  let got = null, sent = null;
  const both = () => {
    if (got === null || sent === null) return;
    console.log('peer got', got);
    console.log('send callback', sent);
    peer.close(); s.close(() => console.log('closed'));
  };
  peer.on('message', (m, r) => { got = [String(m), r.family, r.address, r.size].join(' '); both(); });
  peer.bind(0, '::1', () => s.send('over v6', peer.address().port, '::1', (e, n) => { sent = e + ' ' + n; both(); }));
});
"""
    r = js(code)
    assert out(r) == golden("dgram_udp6")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dgram_connected_send_and_argument_errors(js, golden):
    """CATCHES: connected-UDP emulation that ignores the remembered peer, allows a port on a
    connected send, or argument validation that does not raise the Node error codes
    (ERR_SOCKET_BAD_PORT, ERR_SOCKET_DGRAM_IS_CONNECTED, ERR_SOCKET_ALREADY_BOUND, ...)."""
    code = r"""
const dgram = require('dgram');
const log = [];
const tryIt = (label, f) => { try { f(); log.push(label + ' ok'); } catch (e) { log.push(label + ' threw ' + e.name + ' ' + e.code + ' ' + e.message); } };
tryIt('bad type', () => dgram.createSocket('udp5'));
tryIt('raw handle', () => dgram._createSocketHandle());
const rx = dgram.createSocket('udp4');
rx.bind(0, '127.0.0.1', () => {
  tryIt('bind twice', () => rx.bind(0));
  const tx = dgram.createSocket('udp4');
  tryIt('remoteAddress before connect', () => tx.remoteAddress());
  tryIt('disconnect before connect', () => tx.disconnect());
  tx.send('x', 0, '127.0.0.1', (e) => log.push('port 0 callback ' + e.name + ' ' + e.code + ' ' + e.message));
  tryIt('bad msg', () => tx.send(42, rx.address().port, '127.0.0.1'));
  tx.connect(rx.address().port, '127.0.0.1', () => {
    const ra = tx.remoteAddress();
    log.push('connected remote ' + ra.address + ' ' + ra.family + ' portOk=' + (ra.port === rx.address().port));
    tryIt('connect twice', () => tx.connect(1, '127.0.0.1'));
    tx.send('x', 9, (e) => log.push('send with port while connected ' + e.code + ' ' + e.message));
    tx.send(['multi', '-', Buffer.from('part')], (e, n) => { sentBytes = n; finish(); });
  });
  let sentBytes = null, received = null;
  const finish = () => {
    if (sentBytes === null || received === null) return;
    log.push('connected send bytes=' + sentBytes + ' received ' + JSON.stringify(received));
    tx.disconnect();
    tryIt('remoteAddress after disconnect', () => tx.remoteAddress());
    tx.close(); rx.close(() => console.log(log.join('\n')));
  };
  rx.on('message', (m) => { if (received === null) { received = String(m); finish(); } });
});
"""
    r = js(code)
    assert out(r) == golden("dgram_connected_and_errors")
    assert (r.returncode, r.stderr) == (0, b"")
