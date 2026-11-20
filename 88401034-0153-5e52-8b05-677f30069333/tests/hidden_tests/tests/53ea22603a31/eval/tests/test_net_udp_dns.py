"""Loopback networking gaps: node:dgram (socket creation/validation, bind forms and errors, datagram
payload forms, connected-UDP emulation, socket options incl. buffer sizes and multicast membership on
the loopback interface, ref/unref, close semantics, udp6 on ::1), net.Server/net.Socket unref and
unix-socket options, the server side of Lumen.upgradeWebSocket driven by a raw TCP client (control
frames, close handshake, protocol violations, handshake headers), and WebSocket/EventSource client
limits against raw TCP servers. Every server binds port 0 and port numbers are never printed.

Not exercised on purpose: node:dns record queries (the reference sends them to the /etc/resolv.conf
nameservers on port 53 and ignores Resolver#setServers, so a server started by the test cannot answer
them) and server-to-client sends on Lumen.upgradeWebSocket handles (the reference's server-side read
loop holds the socket lock in a blocking read, so handle.send()/close() can block the event loop
until the peer sends something)."""

from conftest import check_script, resources_for

G = resources_for(__file__)

HELPERS = r'''const dgram = require('node:dgram');
const fmt = (e) => e instanceof Error ? `${e.name} [${e.code}] ${e.message}` : 'non-error ' + JSON.stringify(e);
const t = (label, f) => { try { console.log(label, '->', JSON.stringify(f())); } catch (e) { console.log(label, 'THREW', fmt(e)); } };
const once = (em, ev) => new Promise((resolve) => em.once(ev, (...a) => resolve(a)));
'''


def test_dgram_socket_validation_and_lifecycle_errors(run, workdir):
    """CATCHES: createSocket accepting unknown types or missing options (ERR_SOCKET_BAD_TYPE expected),
    unbound sockets not failing address()/setTTL/setBroadcast with EBADF, remoteAddress()/disconnect()
    on an unconnected socket not throwing ERR_SOCKET_DGRAM_NOT_CONNECTED, a second bind not throwing
    ERR_SOCKET_ALREADY_BOUND, wrong TTL / multicast TTL / buffer-size range checks and messages
    (string coercion, fractional values), membership address validation (TypeError messages for bad
    group/source/interface addresses), and close() twice / send/address/setTTL after close not
    failing with the Node-style codes (close(cb) twice reports through the callback)."""
    check_script(run, workdir, G, "dgram_socket_validation_and_lifecycle_errors", HELPERS + r'''
t('udp5', () => dgram.createSocket('udp5'));
t('no type', () => dgram.createSocket());
t('options object', () => dgram.createSocket({ type: 'udp4' }).type);
t('bad options type', () => dgram.createSocket({ type: 'tcp' }));
const a = dgram.createSocket('udp4');
console.log('is EventEmitter', a instanceof require('node:events'), a instanceof dgram.Socket, typeof dgram._createSocketHandle);
t('raw handle', () => dgram._createSocketHandle());
t('address before bind', () => a.address());
t('setTTL before bind', () => a.setTTL(5));
t('setBroadcast before bind', () => a.setBroadcast(true));
t('remoteAddress unconnected', () => a.remoteAddress());
t('disconnect unconnected', () => a.disconnect());
a.bind(0, '127.0.0.1', () => {
  const ad = a.address();
  console.log('bound', ad.address, ad.family, typeof ad.port, Object.keys(ad).join(','));
  t('bind twice', () => a.bind(0));
  t('setTTL 64', () => a.setTTL(64));
  t('setTTL "7"', () => a.setTTL('7'));
  t('setTTL 0', () => a.setTTL(0));
  t('setTTL 256', () => a.setTTL(256));
  t('setTTL 1.5', () => a.setTTL(1.5));
  t('setMulticastTTL 0', () => a.setMulticastTTL(0));
  t('setMulticastTTL 255', () => a.setMulticastTTL(255));
  t('setMulticastTTL -1', () => a.setMulticastTTL(-1));
  t('setMulticastTTL "x"', () => a.setMulticastTTL('x'));
  t('setMulticastLoopback 0', () => a.setMulticastLoopback(0));
  t('setMulticastLoopback "yes"', () => a.setMulticastLoopback('yes'));
  t('setBroadcast 1', () => a.setBroadcast(1));
  t('setRecvBufferSize 0', () => a.setRecvBufferSize(0));
  t('setRecvBufferSize -5', () => a.setRecvBufferSize(-5));
  t('setSendBufferSize "x"', () => a.setSendBufferSize('x'));
  t('setSendBufferSize 2^31', () => a.setSendBufferSize(2 ** 31));
  t('setMulticastInterface "nope"', () => a.setMulticastInterface('nope'));
  t('addMembership "nope"', () => a.addMembership('nope'));
  t('addMembership bad iface', () => a.addMembership('224.0.0.251', 'eth0'));
  t('dropMembership bad group', () => a.dropMembership('300.1.1.1'));
  t('ssm bad source', () => a.addSourceSpecificMembership('x', '232.1.1.1'));
  t('ssm unicast group', () => a.addSourceSpecificMembership('10.0.0.1', '10.0.0.2'));
  t('ssm bad group', () => a.dropSourceSpecificMembership('10.0.0.1', 'zz'));
  t('ssm bad iface', () => a.addSourceSpecificMembership('10.0.0.1', '232.1.1.1', 'q'));
  t('ref', () => a.ref() === a);
  t('unref', () => a.unref() === a);
  t('ref again', () => a.ref() === a);
  console.log('close returns this', a.close(() => {
    console.log('close callback');
    t('close again', () => a.close());
    a.close((e) => console.log('close(cb) again ->', fmt(e)));
    t('send after close', () => a.send('x', 1234, '127.0.0.1', () => console.log('never')));
    t('address after close', () => a.address());
    t('setTTL after close', () => a.setTTL(3));
    t('ref after close', () => a.ref() === a);
    console.log('sync part of close callback done');
  }) === a);
});
''', filename="dgram_socket_validation_and_lifecycle_errors.cjs")


def test_dgram_echo_payload_forms_and_send_errors(run, workdir):
    """CATCHES: dgram send() mishandling payload forms (string, Buffer with offset/length, Uint8Array
    with NUL/0xff bytes, an array of chunks concatenated, empty datagrams, 60000-byte datagrams), a
    wrong send-callback byte count, 'message' rinfo lacking address/family/port/size or reporting the
    wrong sender port, an unbound sender not being auto-bound to 0.0.0.0 (with address() throwing EBADF
    before), the default destination for '' / omitted address not being 127.0.0.1, oversized datagrams
    not failing with the reference's UNKNOWN/send error, and bad ports / bad message types not raising
    ERR_SOCKET_BAD_PORT RangeError / TypeError (via the callback when given, synchronously otherwise)."""
    check_script(run, workdir, G, "dgram_echo_payload_forms_and_send_errors", HELPERS + r'''
const serverLog = [];
let clientPort;
const server = dgram.createSocket('udp4', (msg, rinfo) => {
  serverLog.push(`server got ${JSON.stringify(msg.toString('latin1').slice(0, 12))} len=${msg.length} buffer=${Buffer.isBuffer(msg)} ` +
    `from=${rinfo.address}/${rinfo.family} size=${rinfo.size} senderPortMatches=${rinfo.port === clientPort} keys=${Object.keys(rinfo).join(',')}`);
  server.send(Buffer.concat([Buffer.from('echo:'), msg]), rinfo.port, rinfo.address);
});
server.bind({ port: 0, address: '127.0.0.1' }, async () => {
  const port = server.address().port;
  const P = (s) => String(s).replaceAll(String(port), 'PORT');
  const client = dgram.createSocket({ type: 'udp4' });
  const send = (...args) => new Promise((res) => client.send(...args, (err, n) => res(err ? 'ERR ' + P(fmt(err)) + ' syscall=' + err.syscall : 'sent ' + n)));
  const exchange = async (label, ...args) => {
    const [sent, [reply]] = await Promise.all([send(...args), once(client, 'message')]);
    console.log(label, '|', sent, '|', serverLog.splice(0).join('; '), '| reply', JSON.stringify([...reply.subarray(0, 12)]), 'len', reply.length);
  };
  t('client address before first send', () => client.address());
  const first = client.send('hello', port, '127.0.0.1');
  console.log('send() returns', first);
  clientPort = client.address().port;
  console.log('auto-bound to', client.address().address, client.address().family, clientPort > 0);
  const [r1] = await once(client, 'message');
  console.log('first reply', r1.toString(), serverLog.splice(0).join('; '));
  await exchange('buffer offset/length', Buffer.from('0123456789'), 2, 5, port, '127.0.0.1');
  await exchange('uint8array, no address', new Uint8Array([104, 105, 0, 255]), port);
  await exchange('array of chunks, empty address', ['ab', Buffer.from('cd'), new Uint8Array([101])], port, '');
  await exchange('empty string', '', port, '127.0.0.1');
  await exchange('60000 bytes', Buffer.alloc(60000, 97), port, '127.0.0.1');
  await exchange('string port', 'p', String(port), '127.0.0.1');
  console.log('70000 bytes', await send(Buffer.alloc(70000), port, '127.0.0.1'));
  console.log('port 0', await send('x', 0, '127.0.0.1'));
  console.log('port "abc"', await send('x', 'abc', '127.0.0.1'));
  console.log('port 70000', await send('x', 70000));
  console.log('port 1.5', await send('x', 1.5));
  console.log('object message', await send({}, port));
  console.log('number message', await send(42, port));
  try { client.send('x', -1); } catch (e) { console.log('sync bad port', fmt(e)); }
  try { client.send(null, port); } catch (e) { console.log('sync bad msg', fmt(e)); }
  try { client.send('x'); } catch (e) { console.log('sync no port', fmt(e)); }
  console.log('server saw nothing else:', JSON.stringify(serverLog));
  client.close();
  server.close(() => console.log('done'));
});
''', filename="dgram_echo_payload_forms_and_send_errors.cjs")


def test_dgram_bind_errors_and_connected_mode(run, workdir):
    """CATCHES: a second bind to a used UDP port not emitting 'error' with code EADDRINUSE, syscall
    bind, address/port fields and the 'bind EADDRINUSE host:port' message; binding a non-local address
    not failing with EADDRNOTAVAIL; a socket whose bind failed not being closable; connect() not
    emitting 'connect' (listener order: on('connect') before the connect callback) or remoteAddress()
    returning the wrong shape; a second connect, or send() with a port on a connected socket, not
    failing with ERR_SOCKET_DGRAM_IS_CONNECTED; connected sends (with offset/length) not going to the
    remote; and disconnect() not restoring the unconnected behaviour (no-port send -> bad port)."""
    check_script(run, workdir, G, "dgram_bind_errors_and_connected_mode", HELPERS + r'''
const serverLog = [];
const server = dgram.createSocket('udp4');
server.on('message', (m, r) => { serverLog.push('server got ' + m); server.send('ack:' + m, r.port, r.address); });
server.bind(0, '127.0.0.1', async () => {
  const port = server.address().port;
  const P = (s) => String(s).replaceAll(String(port), 'PORT');
  const dup = dgram.createSocket('udp4');
  dup.bind(port, '127.0.0.1');
  const [e1] = await once(dup, 'error');
  console.log('dup bind error', P(fmt(e1)), 'syscall=' + e1.syscall, 'address=' + e1.address, 'portMatches=' + (e1.port === port));
  t('dup address after failed bind', () => dup.address());
  dup.on('close', () => console.log('dup close event'));
  t('dup close', () => dup.close() === dup);
  await once(dup, 'close');
  const na = dgram.createSocket('udp4');
  na.bind({ port: 0, address: '192.0.2.1' }, () => console.log('never listening'));
  const [e2] = await once(na, 'error');
  console.log('non-local bind error', fmt(e2), 'syscall=' + e2.syscall, 'address=' + e2.address, 'port=' + e2.port);
  na.close();

  const c = dgram.createSocket('udp4');
  const order = [];
  c.on('connect', () => order.push('connect event'));
  c.connect(port, '127.0.0.1', () => order.push('connect callback'));
  t('remoteAddress before connect event', () => P(JSON.stringify(c.remoteAddress())));
  await once(c, 'connect');
  console.log(order.join(' then '));
  t('remoteAddress', () => P(JSON.stringify(c.remoteAddress())));
  t('connect twice', () => c.connect(port));
  const withPort = await new Promise((res) => c.send('a', port, (err) => res(err)));
  console.log('send with port on connected socket', fmt(withPort));
  let [reply] = await Promise.all([new Promise((res) => c.send('hi', (err, n) => res([err, n]))), once(c, 'message')]);
  console.log('connected send', JSON.stringify(reply[0]), reply[1]);
  [reply] = await Promise.all([new Promise((res) => c.send(Buffer.from('xxbyexx'), 2, 3, (err, n) => res([err, n]))), once(c, 'message')]);
  console.log('connected offset send', JSON.stringify(reply[0]), reply[1]);
  console.log(serverLog.join(' | '));
  t('disconnect', () => c.disconnect());
  t('remoteAddress after disconnect', () => c.remoteAddress());
  t('disconnect twice', () => c.disconnect());
  t('send without port after disconnect', () => c.send('nope'));
  c.close(() => server.close(() => console.log('closed all')));
});
''', filename="dgram_bind_errors_and_connected_mode.cjs")


def test_dgram_unhandled_bind_error(run, workdir):
    """CATCHES: a failed bind() throwing synchronously instead of emitting 'error' asynchronously, or an
    unhandled dgram 'error' event being reported differently from the reference, which prints it as an
    unhandled promise rejection ('Uncaught (in promise) Error: bind EADDRNOTAVAIL 192.0.2.1:0') on
    stderr and still exits with status 0 after the synchronous code has run."""
    check_script(run, workdir, G, "dgram_unhandled_bind_error", r'''const dgram = require('node:dgram');
const s = dgram.createSocket('udp4');
console.log('bind returns this:', s.bind(0, '192.0.2.1') === s);
console.log('after bind call');
setTimeout(() => console.log('timer after the error still runs'), 20);
''', filename="dgram_unhandled_bind_error.cjs", stderr="Uncaught (in promise) Error: bind EADDRNOTAVAIL 192.0.2.1:0\n")


def test_dgram_bind_forms_event_order_and_unref(run, workdir):
    """CATCHES: bind() overloads resolved wrongly (no args / {} / string port -> 0.0.0.0 ephemeral,
    callback-only, options object with address), 'listening' emitted synchronously or out of
    registration order relative to the bind callback, an implicit bind from send() not emitting
    'listening', datagrams sent before 'listening' being lost, a burst of datagrams delivered out of
    order, the createSocket listener not being a 'message' listener, close() listeners firing in the
    wrong order, or unref() not letting the process exit while a bound socket is still open (the
    process must end by itself after its timer)."""
    check_script(run, workdir, G, "dgram_bind_forms_event_order_and_unref", HELPERS + r'''
(async () => {
  const forms = [['no args', () => []], ['empty object', () => [{}]], ['string port', () => ['0']],
                 ['callback only', (order) => [() => order.push('bind callback')]],
                 ['port + callback', (order) => [0, () => order.push('bind callback')]],
                 ['options + address', (order) => [{ port: 0, address: '127.0.0.1', exclusive: true }, () => order.push('bind callback')]]];
  for (const [label, makeArgs] of forms) {
    const s = dgram.createSocket('udp4');
    const order = [];
    s.on('listening', () => order.push('listening#1'));
    s.bind(...makeArgs(order));
    s.on('listening', () => order.push('listening#2'));
    order.push('sync');
    await once(s, 'listening');
    const a = s.address();
    console.log(label.padEnd(18), a.address, a.family, a.port > 0, order.join(','));
    await new Promise((r) => s.close(r));
  }
  const got = [];
  const rx = dgram.createSocket('udp4', (m) => got.push('ctor listener ' + m));
  rx.on('message', (m, r) => got.push('on listener ' + m + ' ' + r.size));
  rx.bind(0, '127.0.0.1');
  const port = rx.address().port; // bound synchronously, 'listening' is still pending
  const tx = dgram.createSocket('udp4');
  const txOrder = [];
  tx.on('listening', () => txOrder.push('implicit listening'));
  const counts = [];
  const firstSend = new Promise((r) => tx.send('one', port, '127.0.0.1', (e, n) => r(n)));
  txOrder.push('after first send() call');
  counts.push(await firstSend);
  for (const word of ['two', 'three', 'four', 'five']) counts.push(await new Promise((r) => tx.send(word, port, '127.0.0.1', (e, n) => r(n))));
  console.log('send byte counts', JSON.stringify(counts));
  while (got.length < 10) await once(rx, 'message');
  console.log(got.join(' | '));
  console.log(txOrder.join(','));
  const closeOrder = [];
  tx.on('close', () => closeOrder.push('close listener'));
  tx.close(() => closeOrder.push('close callback'));
  closeOrder.push('after close()');
  await once(tx, 'close');
  console.log(closeOrder.join(','));
  console.log('unref/ref return the socket', rx.unref() === rx, rx.ref() === rx, rx.unref() === rx);
  // an unref'd socket still receives (a ref'd timer keeps the loop alive meanwhile)
  const keepAlive = setTimeout(() => console.log('late datagram never arrived'), 10000);
  const tx2 = dgram.createSocket('udp4');
  tx2.send('late', port, '127.0.0.1', () => tx2.close());
  const [late] = await once(rx, 'message');
  clearTimeout(keepAlive);
  console.log('unref socket received', String(late), got.slice(10).join(' | '));
  setTimeout(() => console.log('unref: bound socket no longer keeps the process alive'), 30);
})();
''', filename="dgram_bind_forms_event_order_and_unref.cjs")


def test_net_unref_and_unix_socket_options(run, workdir):
    """CATCHES: net.Server#unref/ref and net.Socket#unref/ref not returning `this` or not letting the
    process exit while an unref'd TCP server and an unref'd client connection are still open; unix
    domain sockets reporting a non-empty address() or remote address/port, setNoDelay/setKeepAlive on
    a unix socket throwing instead of being silently ignored (they return the socket), or the socket
    file not being removed when the unix server closes."""
    r = check_script(run, workdir, G, "net_unref_and_unix_socket_options", r'''const net = require('node:net');
const fs = require('node:fs');
const serverSide = [];
const us = net.createServer((s) => {
  serverSide.push(`server side address=${JSON.stringify(s.address())} remote=${s.remoteAddress}/${s.remotePort} ` +
    `setNoDelay->this=${s.setNoDelay(true) === s} setKeepAlive->this=${s.setKeepAlive(true, 1000) === s}`);
  s.on('data', (d) => s.end('re:' + d));
});
us.listen('u.sock', () => {
  console.log('unix server.address()', JSON.stringify(us.address()), 'socket file exists', fs.existsSync('u.sock'));
  const c = net.connect('u.sock', () => {
    console.log('unix client address()', JSON.stringify(c.address()), 'remote', c.remoteAddress, 'setNoDelay->this', c.setNoDelay() === c,
      'setKeepAlive->this', c.setKeepAlive(false) === c, 'ref->this', c.ref() === c);
    c.write('x');
  });
  let got = '';
  c.on('data', (d) => { got += d; });
  c.on('close', () => us.close(() => {
    console.log('reply', got, '|', serverSide.join(' | '));
    console.log('socket file after close', fs.existsSync('u.sock'));
    const srv = net.createServer((s) => { s.unref(); s.on('data', () => {}); });
    srv.listen(0, '127.0.0.1', () => {
      console.log('server unref/ref/unref return this', srv.unref() === srv, srv.ref() === srv, srv.unref() === srv);
      const k = net.connect(srv.address().port, '127.0.0.1', () => {
        console.log('client unref/ref/unref return this', k.unref() === k, k.ref() === k, k.unref() === k);
        k.write('keep the server-side read busy');
        setTimeout(() => console.log('exiting with an open server and connection'), 50);
      });
    });
  }));
});
''', filename="net_unref_and_unix_socket_options.cjs")
    assert sorted(p.name for p in workdir.iterdir()) == ["net_unref_and_unix_socket_options.cjs"]
    assert r.returncode == 0


def test_lumen_upgrade_websocket_raw_client_control_frames(run, workdir):
    """CATCHES: a Lumen.upgradeWebSocket server side that computes a wrong Sec-WebSocket-Accept for the
    RFC 6455 sample key, omits the chosen subprotocol or the extra headers (plain object, [name, value]
    pairs and Headers forms; numbers stringified; Upgrade/Connection/Sec-WebSocket-Accept overrides must
    be dropped), masks its frames, does not answer pings (including empty ones) with unmasked pongs,
    reacts to unsolicited pongs, loses text/binary/16-bit-length messages, does not echo a client close
    (code only; an empty close is reported to onclose as 1005 and echoed as 1000), or does not fail a
    frame with reserved bits with an unmasked 1002 close carrying the reason and onclose wasClean=false."""
    check_script(run, workdir, G, "lumen_upgrade_websocket_raw_client_control_frames", r'''import net from 'node:net';
const log = [];
const closed = {};
const closedP = (path) => closed[path] ??= (() => { let r; const p = new Promise((res) => { r = res; }); p.resolve = r; return p; })();
const OPTIONS = {
  '/proto': { protocol: 'chat', headers: { 'X-Extra': 'yes', Upgrade: 'evil', connection: 'nope', 'Sec-WebSocket-Accept': 'bad', 'X-Num': 7 } },
  '/pairs': { headers: [['X-A', 1], ['X-B', 'two']] },
  '/headers': { headers: new Headers({ 'X-From-Headers': 'h' }) },
};
const server = Lumen.serve({ port: 0, hostname: '127.0.0.1' }, (req) => {
  const path = new URL(req.url).pathname;
  const h = Lumen.upgradeWebSocket(req, OPTIONS[path]);
  log.push(`${path}: upgraded, remoteAddress=${h.remoteAddress}, handle keys=${Object.keys(h).sort().join(',')}`);
  h.onmessage = (data, isBinary) => log.push(`${path}: got ${isBinary ? 'binary [' + [...data].slice(0, 4).join() + '] len=' + data.length : 'text ' + JSON.stringify(data)}`);
  h.onclose = (code, reason, wasClean) => { log.push(`${path}: onclose ${code} ${JSON.stringify(reason)} wasClean=${wasClean}`); closedP(path).resolve(); };
  return new Response('ignored after upgrade');
});
const masked = (op, payload, b0 = 0x80 | op) => {
  payload = Buffer.from(payload);
  const m = [9, 8, 7, 6];
  const len = payload.length < 126 ? [0x80 | payload.length] : [0x80 | 126, payload.length >> 8, payload.length & 255];
  return Buffer.concat([Buffer.from([b0, ...len]), Buffer.from(m), Buffer.from(payload.map((b, i) => b ^ m[i % 4]))]);
};
const closeFrame = (code, reason) => masked(8, Buffer.concat([Buffer.from([code >> 8, code & 255]), Buffer.from(reason)]));
// A raw RFC 6455 client: sends the handshake, prints the 101 response and every frame it receives.
const client = (path, onOpen, onFrame) => new Promise((resolve) => {
  const s = net.connect(server.port, '127.0.0.1', () => {
    s.write(`GET ${path} HTTP/1.1\r\nHost: example.test\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n` +
      'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: chat, superchat\r\n\r\n');
  });
  let buf = Buffer.alloc(0), head = null;
  const out = [];
  s.on('data', (d) => {
    buf = Buffer.concat([buf, d]);
    if (head === null) {
      const i = buf.toString('latin1').indexOf('\r\n\r\n');
      if (i < 0) return;
      head = buf.subarray(0, i).toString();
      buf = buf.subarray(i + 4);
      out.push('  response: ' + head.split('\r\n').join(' | '));
      onOpen(s);
    }
    while (buf.length >= 2 && buf.length >= 2 + (buf[1] & 127)) {
      const len = buf[1] & 127, op = buf[0] & 15, payload = buf.subarray(2, 2 + len);
      out.push(`  frame fin=${buf[0] >> 7} op=${op} masked=${buf[1] >> 7} len=${len} ` +
        (op === 8 ? `code=${payload.readUInt16BE(0)} reason=${JSON.stringify(payload.subarray(2).toString())}` : JSON.stringify(payload.toString())));
      buf = buf.subarray(2 + len);
      onFrame(s, op, payload);
    }
  });
  s.on('error', () => {});
  s.on('close', () => resolve(out.join('\n')));
});
let pongs = 0;
console.log('/proto\n' + await client('/proto', (s) => s.write(masked(9, 'p1')), (s, op) => {
  if (op === 10 && ++pongs === 1) {
    s.write(masked(1, 'hello')); s.write(masked(2, [1, 2, 3])); s.write(masked(2, Buffer.alloc(300, 5)));
    s.write(masked(10, 'unsolicited')); s.write(masked(9, ''));
  } else if (op === 10) s.write(closeFrame(4000, 'bye'));
  if (op === 8) s.end();
}));
await closedP('/proto');
console.log('/rsv\n' + await client('/rsv', (s) => s.write(masked(1, 'x', 0x80 | 0x40 | 1)), (s, op) => { if (op === 8) s.end(); }));
await closedP('/rsv');
console.log('/pairs\n' + await client('/pairs', (s) => s.write(closeFrame(1000, '')), (s, op) => { if (op === 8) s.end(); }));
await closedP('/pairs');
console.log('/headers\n' + await client('/headers', (s) => s.write(masked(8, '')), (s, op) => { if (op === 8) s.end(); }));
await closedP('/headers');
console.log(log.join('\n'));
await server.shutdown();
console.log('server shut down');
''', filename="lumen_upgrade_websocket_raw_client_control_frames.mjs")


def test_websocket_and_eventsource_client_limits(run, workdir):
    """CATCHES: an EventSource that accepts a response head over 64 KiB, does not treat a 302 without
    Location or a redirect loop (6 requests, then stop) as fatal (readyState CLOSED in onerror), treats a
    head cut off by EOF as fatal instead of retriable (readyState CONNECTING), or cannot follow an
    absolute redirect to a mixed-case 'Text/Event-Stream; charset' response; and a WebSocket client
    that accepts a frame announcing a 2^40-byte payload (must fail with close 1009 'message too big',
    sending that close frame to the server) or a handshake response head over 64 KiB (error + 1006)."""
    check_script(run, workdir, G, "websocket_and_eventsource_client_limits", r'''import net from 'node:net';
import { createHash } from 'node:crypto';
const seen = {};
let clientCloseFrame;
const clientClosed = new Promise((r) => { clientCloseFrame = r; });
const server = net.createServer((sock) => {
  let buf = '';
  sock.on('error', () => {});
  sock.on('data', (c) => {
    buf += c.toString('latin1');
    const end = buf.indexOf('\r\n\r\n');
    if (end < 0) return;
    const lines = buf.slice(0, end).split('\r\n');
    buf = '';
    const path = lines[0].split(' ')[1];
    seen[path] = (seen[path] || 0) + 1;
    if (path === '/bighead') sock.end('HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nX-Big: ' + 'a'.repeat(70000) + '\r\n\r\ndata: x\n\n');
    else if (path === '/cut') sock.end('HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n');
    else if (path === '/noloc') sock.end('HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n');
    else if (path === '/loop') sock.end('HTTP/1.1 307 Temporary Redirect\r\nLocation: /loop\r\nContent-Length: 0\r\n\r\n');
    else if (path === '/hop') sock.end('HTTP/1.1 301 Moved\r\nLocation: http://127.0.0.1:' + server.address().port + '/ok?from=hop\r\n\r\n');
    else if (path === '/ok?from=hop') sock.end('HTTP/1.1 200 OK\r\nContent-Type: Text/Event-Stream; charset=utf-8\r\n\r\ndata: reached\n\n');
    else if (path === '/ws-bighead') sock.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nX-Big: ' + 'b'.repeat(70000) + '\r\n\r\n');
    else if (path === '/ws-huge') {
      const key = /sec-websocket-key: (\S+)/i.exec(lines.join('\n'))[1];
      const accept = createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      sock.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n', () => {
        sock.write(Buffer.from([0x82, 127, 0, 0, 1, 0, 0, 0, 0, 0])); // binary frame claiming 2^40 bytes
      });
      sock.on('data', (d) => {
        if ((d[0] & 15) !== 8) return;
        const p = Buffer.from(d.subarray(6, 6 + (d[1] & 127))).map((b, i) => b ^ d[2 + (i % 4)]);
        clientCloseFrame(`masked=${d[1] >> 7} code=${p.readUInt16BE(0)} reason=${JSON.stringify(p.subarray(2).toString())}`);
        sock.end();
      });
    }
  });
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const es = (path) => new Promise((resolve) => {
  const e = new EventSource(base + path);
  const ev = [];
  e.onopen = () => ev.push('open');
  e.onmessage = (m) => { ev.push('message ' + m.data); e.close(); resolve(ev.join(', ') + ' -> readyState ' + e.readyState); };
  e.onerror = () => { ev.push('error readyState=' + e.readyState); e.close(); resolve(ev.join(', ') + ' -> after close() ' + e.readyState); };
});
for (const p of ['/bighead', '/cut', '/noloc', '/loop', '/hop']) console.log('EventSource', p, '->', await es(p));
const ws = (path) => new Promise((resolve) => {
  const w = new WebSocket(base.replace('http', 'ws') + path);
  const ev = [];
  w.onopen = () => ev.push('open');
  w.onmessage = () => ev.push('message?!');
  w.onerror = () => ev.push('error');
  w.onclose = (e) => { ev.push(`close ${e.code} ${JSON.stringify(e.reason)} wasClean=${e.wasClean}`); resolve(ev.join(' -> ')); };
});
console.log('WebSocket /ws-huge ->', await ws('/ws-huge'));
console.log('server received close frame:', await clientClosed);
console.log('WebSocket /ws-bighead ->', await ws('/ws-bighead'));
console.log('requests seen', JSON.stringify(seen));
server.close();
''', filename="websocket_and_eventsource_client_limits.mjs")
