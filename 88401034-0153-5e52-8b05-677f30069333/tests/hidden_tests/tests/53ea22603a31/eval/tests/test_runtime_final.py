"""Final runtime gap pass (networking, processes, module loading): UDP socket buffer sizes, the IPv4
multicast interface and (source-specific) group membership on the loopback interface, unresolvable
host names for UDP sends and TCP connects, wildcard TCP / Lumen.serve listeners, EPIPE on a Unix
socket whose peer closed, a WebSocket closed while still CONNECTING, process.execve failure modes,
child_process.spawn cwd/env/ref, source-phase imports of the host-defined '<module source>',
directory imports through package.json "main", dynamic import() without a module loader (-e /
stdin / REPL) and the JSX entry transformer's syntax errors."""

import pytest

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)


# ---- dgram -------------------------------------------------------------------------------------

def test_dgram_send_to_unresolvable_host(run, workdir):
    """CATCHES: UDP sends to a host name that cannot be resolved (here one containing a NUL byte, which
    fails before any DNS traffic) not failing asynchronously with code ENOTFOUND, syscall
    getaddrinfo, the address/port properties and the 'getaddrinfo ENOTFOUND <host>:<port>' message;
    the error must reach the send callback (also for the offset/length form), become an 'error'
    event when no callback is given, and also surface for a socket connect()ed to such a host
    (connect itself succeeds and remoteAddress() echoes the name)."""
    check_script(run, workdir, G, "dgram_send_to_unresolvable_host", r'''
const dgram = require('dgram');
const fmt = (e) => `${e.name}: ${JSON.stringify(e.message)} code=${e.code} syscall=${e.syscall} address=${JSON.stringify(e.address)} port=${e.port}`;
const s = dgram.createSocket('udp4');
s.on('error', (e) => { console.log('error event', fmt(e)); next(); });
let step = 0;
const next = () => {
  step++;
  if (step === 1) s.send('payload', 4321, 'bad\0host', (err, n) => { console.log('send cb', fmt(err), n); next(); });
  else if (step === 2) s.send(Buffer.from('abc'), 0, 2, 4322, 'x\0', (err) => { console.log('send offset cb', fmt(err)); next(); });
  else if (step === 3) s.send('no callback', 4323, 'nul\0name');
  else if (step === 4) {
    s.connect(4324, 'conn\0host', () => {
      console.log('connected', JSON.stringify(s.remoteAddress()));
      s.send('via connect', (err) => { console.log('connected send cb', fmt(err)); next(); });
    });
  } else s.close(() => console.log('closed'));
};
s.bind(0, '127.0.0.1', () => { console.log('bound'); next(); });
''', filename="dgram_unresolvable.cjs")


# ---- net / Lumen.serve -------------------------------------------------------------------------

def test_net_wildcard_listeners_and_unresolvable_connect(run, workdir):
    """CATCHES: net.Server#listen(port) without a host not binding the IPv4 wildcard (address()
    must report 0.0.0.0 / IPv4) or not accepting loopback connections, closing such a server not
    waking its accept loop (the process would hang), a TCP connect to an unresolvable host (a NUL
    byte in the name) not being destroyed with code ENOTFOUND, syscall getaddrinfo, host/port
    properties and the 'getaddrinfo ENOTFOUND <host>:<port>' message (close(hadError=true) after
    'error'), and Lumen.serve without a hostname not reporting/binding 0.0.0.0 or not shutting down."""
    check_script(run, workdir, G, "net_wildcard_listeners_and_unresolvable_connect", r'''
import net from 'node:net';
const fmt = (e) => `${e.name}: ${JSON.stringify(e.message)} code=${e.code} syscall=${e.syscall} address=${JSON.stringify(e.address)} port=${e.port}`;
const srv = net.createServer((s) => s.end('hi from the wildcard listener'));
await new Promise((r) => srv.listen(0, r));
const a = srv.address();
console.log('net listen', a.address, a.family, Number.isInteger(a.port) && a.port > 0, srv.listening);
const got = await new Promise((resolve) => {
  const c = net.connect(a.port, '127.0.0.1');
  let data = '';
  c.on('data', (d) => { data += d; });
  c.on('end', () => resolve(data));
});
console.log('client got', JSON.stringify(got));
await new Promise((r) => srv.close(r));
console.log('net server closed', srv.listening, srv.address());
await new Promise((resolve) => {
  const bad = net.connect({ host: 'bad\0host', port: 81 });
  const ev = [];
  bad.on('error', (e) => ev.push('error ' + fmt(e)));
  bad.on('close', (hadError) => { ev.push('close hadError=' + hadError + ' destroyed=' + bad.destroyed); console.log(ev.join('\n')); resolve(); });
});
const server = Lumen.serve({ port: 0 }, (req) => new Response('served ' + new URL(req.url).pathname));
console.log('Lumen.serve hostname', server.hostname, typeof server.port);
const r = await fetch(`http://127.0.0.1:${server.port}/wild`);
console.log('fetch', r.status, await r.text());
await server.shutdown();
console.log('Lumen.serve shut down');
''', filename="net_wildcard.mjs")


def test_net_unix_socket_write_after_peer_close_is_epipe(run, workdir):
    """CATCHES: writing to a Unix-domain stream socket after the server destroyed its end not failing
    with code EPIPE / syscall write / message 'write EPIPE', the failure not being reported to both the
    write callback and an 'error' event, or (reference quirk, pinned) the socket being destroyed by
    that write error: it stays undestroyed and writable until destroy(), after which 'close' fires with
    hadError=false and the server can close."""
    check_script(run, workdir, G, "net_unix_write_after_peer_close", r'''
const net = require('net');
const fmt = (e) => `${e.name}: ${JSON.stringify(e.message)} code=${e.code} syscall=${e.syscall}`;
const srv = net.createServer((s) => { console.log('server: destroying accepted socket'); s.destroy(); });
srv.listen('peer.sock', () => {
  const c = net.connect({ path: 'peer.sock', allowHalfOpen: true });
  c.on('end', () => {
    console.log('client end; writable', c.writable, 'destroyed', c.destroyed);
    c.write('after the peer closed', (e) => {
      console.log('write callback', e ? fmt(e) : 'ok');
      console.log('after error: destroyed', c.destroyed, 'writable', c.writable);
      setTimeout(() => {
        console.log('still destroyed', c.destroyed);
        c.destroy();
        srv.close(() => console.log('server closed'));
      }, 10);
    });
  });
  c.on('error', (e) => console.log('error event', fmt(e)));
  c.on('close', (hadError) => console.log('client close hadError', hadError));
});
''', filename="net_unix_epipe.cjs")


# ---- WebSocket ---------------------------------------------------------------------------------

def test_websocket_close_while_connecting(run, workdir):
    """CATCHES: WebSocket#close() during CONNECTING not moving readyState to CLOSING. Pins reference
    quirks: the handshake still completes and fires 'open' (readyState OPEN), the early close frame is
    never sent, later send()/close() calls are silently dropped (the server receives no bytes at all
    after the handshake), and the connection only ends when the server acts: a server close frame
    (4001 'bye') yields close wasClean=true without an echoed close, a frame with reserved bits yields
    error + close 1002 with the protocol-error reason, and the client then drops the TCP connection."""
    check_script(run, workdir, G, "websocket_close_while_connecting", r'''
import net from 'node:net';
import { createHash } from 'node:crypto';
const serverLog = [];
const socketClosed = {};
const server = net.createServer((sock) => {
  let buf = Buffer.alloc(0), name = null, after = 0, done;
  const closed = new Promise((r) => { done = r; });
  sock.on('error', () => {});
  sock.on('close', () => { serverLog.push(`${name}: ${after} bytes received after the handshake, socket closed`); done(); });
  sock.on('data', (chunk) => {
    if (name !== null) { after += chunk.length; return; }
    buf = Buffer.concat([buf, chunk]);
    const end = buf.toString('latin1').indexOf('\r\n\r\n');
    if (end < 0) return;
    const head = buf.subarray(0, end).toString();
    after += buf.length - end - 4;
    name = head.split(' ')[1].slice(1);
    socketClosed[name] = closed;
    const key = /sec-websocket-key: (\S+)/i.exec(head)[1];
    const accept = createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    sock.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n');
    if (name === 'close') sock.write(Buffer.from([0x88, 5, 0x0f, 0xa1, 0x62, 0x79, 0x65]));
    else sock.write(Buffer.from([0x80 | 0x40 | 1, 1, 0x78]));
  });
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
for (const name of ['close', 'fail']) {
  const ev = [];
  await new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/${name}`);
    ws.close(4000, 'early');
    ev.push('after close() readyState=' + ws.readyState);
    ws.onopen = () => {
      ev.push('open readyState=' + ws.readyState);
      ws.send('after open');
      ws.close(4001, 'again');
      ev.push('after second close() readyState=' + ws.readyState);
      ws.send('dropped');
    };
    ws.onmessage = (e) => ev.push('message ' + e.data);
    ws.onerror = () => ev.push('error readyState=' + ws.readyState);
    ws.onclose = (e) => { ev.push(`close ${e.code} ${JSON.stringify(e.reason)} wasClean=${e.wasClean} readyState=${ws.readyState}`); resolve(); };
  });
  console.log(name + ':\n  ' + ev.join('\n  '));
  await socketClosed[name];
}
console.log(serverLog.join('\n'));
server.close();
''', filename="websocket_close_connecting.mjs")


# ---- processes ---------------------------------------------------------------------------------

def test_process_execve_failures_and_dropped_empty_args(run, workdir):
    """CATCHES: process.execve not surfacing the OS errno text as 'execve failed: <error> (os error N)'
    for a non-executable file (EACCES), a file without a valid header or an empty file with the
    execute bit (ENOEXEC), a script whose #! interpreter is missing (ENOENT), a path through a regular
    file (ENOTDIR), an over-long name (ENAMETOOLONG), an empty path or a bare name that must not be
    looked up in PATH (ENOENT); a failing execve must leave the process running. Also pins that
    fs.writeFileSync ignores its mode option for new files, and (reference quirk) that a successful
    execve (run in a child) drops empty-string arguments while keeping empty env values."""
    write_files(workdir, {"child.cjs": "process.execve('/bin/sh', ['sh', '-c', 'echo \"argc=$# [$1] [$2] [$3]\"; echo \"E=[$E] F=[${F-unset}] G=[${G-unset}]\"', "
                                       "'zero', '', 'three', ''], { E: '', F: 'f', G: undefined });\n"})
    check_script(run, workdir, G, "process_execve_failures", r'''
const fs = require('fs');
const cp = require('child_process');
const tryIt = (label, f) => { try { console.log(label, String(f())); } catch (e) { console.log(label, e.name + ': ' + e.message); } };
fs.writeFileSync('plain.txt', 'not a program\n');
fs.writeFileSync('garbage.bin', 'just some text, no shebang\n', { mode: 0o755 });
fs.writeFileSync('empty.bin', '', { mode: 0o755 });
fs.writeFileSync('badinterp.sh', '#!/no/such/interpreter\necho hi\n');
console.log('mode option honoured', (fs.statSync('garbage.bin').mode & 0o111) !== 0);
for (const f of ['garbage.bin', 'empty.bin', 'badinterp.sh']) fs.chmodSync(f, 0o755);
tryIt('non-executable file', () => process.execve('./plain.txt', ['x'], {}));
tryIt('no valid header', () => process.execve('./garbage.bin', ['x'], {}));
tryIt('empty file', () => process.execve('./empty.bin', [], {}));
tryIt('missing interpreter', () => process.execve('./badinterp.sh', ['x'], {}));
tryIt('through a file', () => process.execve('./plain.txt/sub', ['x'], {}));
tryIt('name too long', () => process.execve('./' + 'n'.repeat(300), [], {}));
tryIt('empty path', () => process.execve('', [], {}));
tryIt('bare name not searched in PATH', () => process.execve('sh', ['sh', '-c', 'echo never'], { PATH: '/bin:/usr/bin' }));
tryIt('coerced args', () => process.execve('./missing', [1, true, null, { toString() { return 'obj'; } }], { A: 1 }));
console.log('still running after failed execve calls');
const r = cp.spawnSync(process.execPath, ['child.cjs'], { encoding: 'utf8' });
console.log('child status', r.status, JSON.stringify(r.stderr));
process.stdout.write(r.stdout);
''', filename="execve_failures.cjs")


def test_child_spawn_cwd_env_and_ref(run, workdir):
    """CATCHES: child_process.spawn ignoring options.cwd (relative and '..'-containing paths must be
    used as the child's working directory), coercing a non-string cwd (a file: URL object is
    stringified, so the directory does not exist) or a missing cwd without throwing synchronously
    with the reference's 'spawn <cmd>: No such file or directory (os error 2)' text, options.env not
    replacing the whole environment (numbers and undefined stringified, HOME absent), and
    ChildProcess#unref()/ref() not returning undefined or ref() not keeping the process alive until
    the child's output and exit arrive."""
    check_script(run, workdir, G, "child_spawn_cwd_env_ref", r'''
const cp = require('child_process');
const fs = require('fs');
fs.mkdirSync('sub/inner', { recursive: true });
fs.writeFileSync('sub/inner/f.txt', '');
const norm = (s) => s.split(process.cwd()).join('<cwd>');
// 'close' may fire before the last stdout chunk arrives: wait for both stdout 'end' and 'exit'.
const run = (label, cmd, args, opts) => new Promise((resolve) => {
  const c = cp.spawn(cmd, args, opts);
  let out = '', code, pending = 2;
  const done = () => { if (--pending === 0) { console.log(label, 'exit', code, JSON.stringify(norm(out))); resolve(); } };
  c.stdout.on('data', (d) => { out += d; });
  c.stdout.on('end', done);
  c.on('exit', (c0) => { code = c0; done(); });
});
const attempt = async (label, cmd, args, opts) => {
  try { await run(label, cmd, args, opts); } catch (e) { console.log(label, 'threw', e.name + ': ' + norm(e.message)); }
};
(async () => {
  await attempt('cwd relative', '/bin/sh', ['-c', 'pwd'], { cwd: 'sub' });
  await attempt('cwd with ..', '/bin/sh', ['-c', 'pwd; ls'], { cwd: 'sub/inner/..' });
  await attempt('cwd nested', '/bin/sh', ['-c', 'ls'], { cwd: 'sub/inner' });
  await attempt('cwd URL object', '/bin/sh', ['-c', 'pwd'], { cwd: new URL('file://' + process.cwd() + '/sub') });
  await attempt('cwd missing', '/bin/sh', ['-c', 'pwd'], { cwd: 'nope' });
  await attempt('env replaced', '/bin/sh', ['-c', 'echo "A=$A N=$N B=$B HOME=${HOME-unset}"'], { env: { A: 'x y', N: 7, B: undefined } });
  const c = cp.spawn('/bin/sh', ['-c', 'sleep 0.05; echo done'], {});
  console.log('unref/ref return', c.unref(), c.ref());
  let said = '';
  c.stdout.on('data', (d) => { said += d; });
  c.stdout.on('end', () => console.log('ref child said', JSON.stringify(said)));
})();
''', filename="child_spawn_cwd.cjs")


# ---- module loading ----------------------------------------------------------------------------

def test_esm_source_phase_and_directory_entries(run, workdir):
    """CATCHES: `import source` of the host-defined '<module source>' specifier not binding one shared
    ModuleSource object (same identity across imports and through a re-exporting module) whose
    prototype is %AbstractModuleSource%.prototype (constructor 'AbstractModuleSource' that throws
    'Abstract class AbstractModuleSource not directly constructable' when called or constructed, and a
    @@toStringTag getter returning undefined for every receiver); a source import of a source-text
    module not failing with SyntaxError 'source-text modules have no module source'; dynamic
    import.source()/import() of '<module source>' not rejecting; directory imports not following
    package.json "main" (with ./ and . segments) or not falling back to index when main is missing;
    and attribute-less JSON imports mis-escaping a raw U+2029 (a `type: 'json'` import of the same
    file must be equal but a distinct module instance)."""
    write_files(workdir, {
        "re.mjs": "import source s from '<module source>';\nimport source s3 from '<module source>';\nexport { s, s3 };\n",
        "bad.mjs": "import source x from './re.mjs';\nconsole.log('never evaluated');\n",
        "d1/package.json": '{"main": "./lib/./entry.mjs"}',
        "d1/lib/entry.mjs": "export const who = 'd1 main entry';\n",
        "d2/package.json": '{"main": "missing.mjs"}',
        "d2/index.mjs": "export const who = 'd2 index fallback';\n",
        "sep.json": '{"p": "a\u2029b", "l": "c\u2028d"}'.encode(),
    })
    check_script(run, workdir, G, "esm_source_phase_and_directory_entries", r'''
import source s from '<module source>';
import source s2 from '<module source>';
import { s as rs, s3 } from './re.mjs';
import * as reNs from './re.mjs';
import { who as w1 } from './d1';
import { who as w2 } from './d2';
import sep from './sep.json';
import sepTyped from './sep.json' with { type: 'json' };
const norm = (m) => m.split(process.cwd()).join('<cwd>');
const AMS = Object.getPrototypeOf(s);
console.log('identity', typeof s, s === s2, s === rs, s === s3, reNs.s === s, Object.keys(reNs).join());
console.log('proto chain', Object.getPrototypeOf(AMS) === Object.prototype, Object.getOwnPropertyNames(AMS).join(), AMS.constructor.name, AMS.constructor.length);
const tag = Object.getOwnPropertyDescriptor(AMS, Symbol.toStringTag);
console.log('toStringTag', typeof tag.get, tag.set, tag.enumerable, tag.configurable, tag.get.call(s), tag.get.call({}), tag.get.call(1));
console.log('object', Object.prototype.toString.call(s), Object.keys(s).length, Object.isExtensible(s), Object.isFrozen(s));
for (const f of [() => new AMS.constructor(), () => AMS.constructor()]) {
  try { f(); console.log('constructed?!'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
for (const [label, f] of [['source of source-text', () => import('./bad.mjs')], ['import.source', () => import.source('<module source>')],
                          ['import()', () => import('<module source>')]]) {
  try { await f(); console.log(label, 'ok?!'); } catch (e) { console.log(label, e.name + ': ' + norm(e.message)); }
}
console.log('directories', w1, '|', w2);
console.log('json', JSON.stringify(sep), sep.p.length, sep.p.charCodeAt(1).toString(16), sep.l.charCodeAt(1).toString(16), JSON.stringify(sepTyped) === JSON.stringify(sep), sepTyped === sep);
''', filename="main.mjs")


def test_dynamic_import_without_module_loader(run, workdir):
    """CATCHES: -e code, piped-stdin scripts and the REPL (which run as scripts with no module loader)
    resolving dynamic import() instead of rejecting with 'TypeError: no module loader configured' —
    for relative files and node: builtins alike — while require() keeps working there, and
    import.meta in -e code not being a SyntaxError with the line number."""
    write_files(workdir, {"dep.mjs": "export const v = 'dep loaded';\n"})
    probe = ("import('./dep.mjs').then((m) => console.log('dep', m.v), (e) => console.log('dep', e.name + ': ' + e.message));"
             "import('node:path').then((m) => console.log('builtin', typeof m.join), (e) => console.log('builtin', e.name + ': ' + e.message));"
             "console.log('require works', typeof require('path').join);")
    expected = "require works function\ndep TypeError: no module loader configured\nbuiltin TypeError: no module loader configured\n"
    r = run(["-e", probe])
    assert (r.stdout.decode(), r.stderr, r.returncode) == (expected, b"", 0)
    r = run([], input=probe)
    assert (r.stdout.decode(), r.stderr, r.returncode) == (expected, b"", 0)
    r = run(["-e", "console.log(1);\nimport.meta.url"])
    assert (r.stdout, r.stderr.decode(), r.returncode) == (b"", "SyntaxError: 'import.meta' is only valid in a module (line 2)\n", 1)
    r = run(["repl"], input='await import("./dep.mjs").then((m) => m.v, (e) => e.name + ": " + e.message)\n')
    assert_result(r, G / "dynamic_import_repl.golden")


@pytest.mark.parametrize("source,message", [
    ("const x = </div>;\n", "expected a JSX element name after `<`"),
    ("const y = <div =\"x\"/>;\n", "expected a JSX attribute name"),
    ("const z = <div>{a</div>;\n", "unterminated `{ … }` in JSX"),
    ("const w = <div a={1};\n", "expected a JSX attribute name"),
])
def test_jsx_entry_transform_errors(run, workdir, source, message):
    """CATCHES: a .jsx entry whose JSX transform error is swallowed or reported in another form: the
    reference prints 'Uncaught JSX transform failed for <file as given>: <reason>' on stderr with exit
    status 1 and runs nothing (no stdout) for a missing element name, a missing attribute name, an
    unterminated `{` expression container and an unterminated opening tag."""
    (workdir / "bad.jsx").write_text("console.log('must not run');\n" + source)
    r = run(["bad.jsx"])
    assert (r.stdout, r.stderr.decode(), r.returncode) == (b"", f"Uncaught JSX transform failed for bad.jsx: {message}\n", 1)


def test_jsx_entry_crlf_text_and_attributes(run, workdir):
    """CATCHES: the .jsx entry transform mishandling CRLF source: CR/LF inside quoted attribute
    values must reach props verbatim (also a lone CR), while multi-line text children separated by
    CRLF collapse to single spaces with leading/trailing line whitespace removed."""
    (workdir / "crlf.jsx").write_bytes(
        b"const React = { createElement: (t, p, ...c) => ({ t, p, c }) };\r\n"
        b"const el = <p title=\"a\r\nb\" t2='x\ry'>line1\r\n  line2\r\n   <b>bold\r\n</b>\r\n  tail</p>;\r\n"
        b"console.log(JSON.stringify(el));\r\n")
    r = run(["crlf.jsx"])
    assert_result(r, G / "jsx_entry_crlf.golden")


def test_esm_mutable_import_meta_url_and_cjs_scanner_negatives(run, workdir):
    """CATCHES: dynamic import() not resolving against the importing module's *current*
    import.meta.url (it is writable: a file: URL in a subdirectory redirects './y.mjs' there, a
    directory URL resolves against its parent, and a non-string falls back to an empty base, failing
    with 'module not found: ./y.mjs (imported from )'); the CommonJS named-export scanner treating
    Object.defineProperty on another object or an `__export(x)` call without an object as exports
    (while module.exports.x / exports.x / defineProperty(exports, ...) are found); a re-exported CJS
    file that is not valid UTF-8 not rejecting with "cannot read '<path>': stream did not contain
    valid UTF-8"; and a bare `@scope` specifier not resolving node_modules/@scope's package main."""
    write_files(workdir, {
        "y.mjs": "export const where = 'top-level y.mjs';\n",
        "sub/y.mjs": "export const where = 'sub/y.mjs';\n",
        "c.cjs": "const helper = {};\nObject.defineProperty(helper, 'hidden', { value: 1 });\n"
                 "Object.defineProperty(exports, 'viaDefine', { enumerable: true, value: 2 });\n"
                 "function __export() {}\n__export(helper);\nmodule.exports.direct = 3;\nexports.plain = 4;\n",
        "re.cjs": "module.exports = require('./latin.cjs');\n",
        "latin.cjs": b"exports.fromLatin = 'caf\xe9'; // 0xe9 alone is not UTF-8\n",
        "node_modules/@scope/package.json": '{"main": "main.js"}',
        "node_modules/@scope/main.js": "module.exports = { fromScopeMain: true };\n",
    })
    check_script(run, workdir, G, "esm_import_meta_and_cjs_scanner", r'''
import * as c from './c.cjs';
const norm = (s) => s.split(process.cwd()).join('<cwd>');
const where = async (label) => {
  try { console.log(label, (await import('./y.mjs')).where); } catch (e) { console.log(label, e.name + ': ' + norm(e.message)); }
};
console.log('cjs names', Object.keys(c).join(), JSON.stringify(c.default));
try { await import('./re.cjs'); console.log('re-export imported?!'); } catch (e) { console.log('re-export', e.name + ': ' + norm(e.message)); }
const s = await import('@scope');
console.log('@scope', Object.keys(s).join(), JSON.stringify(s.default));
const original = import.meta.url;
console.log('url', norm(original));
await where('original url');
import.meta.url = new URL('./sub/x.mjs', original).href;
console.log('url', norm(import.meta.url));
await where('sub file url');
import.meta.url = new URL('./sub/', original).href;
await where('sub directory url');
import.meta.url = 42;
console.log('url', typeof import.meta.url);
await where('numeric url');
import.meta.url = original;
await where('restored url');
''', filename="main.mjs")


def test_worker_entry_errors_reach_onerror(run, workdir):
    """CATCHES: a Worker whose entry script fails to parse or throws at top level not reporting an
    ErrorEvent to the parent's onerror with the reference's message forms: classic scripts give
    'SyntaxError: <msg> (line N)', module workers 'SyntaxError: <msg>' without the line, thrown
    primitives and plain objects are named by their type ('Number: 42', 'Object: ' -- toString is
    not used), an Error with an empty name gives just its message; worker_threads eval workers emit
    'error' with the same texts (a thrown string wrapped as Error 'String: prim') and exit with 1."""
    write_files(workdir, {
        "bad.js": "let x = ;\n",
        "bad.mjs": "export let y = ;\n",
        "throwprim.js": "throw 42;\n",
        "throwobj.js": "throw { toString() { return 'custom object'; } };\n",
        "noname.js": "throw Object.assign(new Error('plain message'), { name: '' });\n",
    })
    check_script(run, workdir, G, "worker_entry_errors", r'''
import { Worker as NodeWorker } from 'node:worker_threads';
const run = (label, file, opts) => new Promise((resolve) => {
  const w = new Worker(new URL(file, import.meta.url), opts);
  w.onerror = (e) => { console.log(label, '->', e.constructor.name, JSON.stringify(e.message)); w.terminate(); resolve(); };
  w.onmessage = (e) => console.log(label, 'message?!', e.data);
});
await run('classic syntax error', './bad.js');
await run('module syntax error', './bad.mjs', { type: 'module' });
await run('classic throws number', './throwprim.js');
await run('classic throws object', './throwobj.js');
await run('error without a name', './noname.js');
for (const [label, src] of [['eval syntax error', 'let x = ;'], ['eval throws string', 'throw "prim"']]) {
  await new Promise((resolve) => {
    const w = new NodeWorker(src, { eval: true });
    w.on('error', (e) => console.log(label, '-> error', e.constructor.name, JSON.stringify(e.message)));
    w.on('exit', (code) => { console.log(label, '-> exit', code); resolve(); });
  });
}
''', filename="main.mjs")


def test_esm_top_level_await_inside_import_cycles(run, workdir):
    """CATCHES: wrong async evaluation of strongly connected module graphs: a cycle member with
    top-level await must finish before the cycle's other members run (A sees B's exports, B's
    function sees A's binding afterwards), a synchronous module in the same cycle that does not
    depend on the awaiting one still runs first, and a rejection after the await must reject every
    module that waited on it (the never-run entry, repeatedly with the same error, and the failing
    module itself) instead of leaving them pending or running their bodies. Pins a reference quirk:
    the synchronous cycle member that already ran (fc) later imports successfully although the
    spec would hand back the cycle root's rejected promise."""
    write_files(workdir, {
        "ca.mjs": "import { fromB, readA } from './cb.mjs';\nconsole.log('A body runs after B settled: fromB =', fromB);\n"
                  "export const fromA = 'a';\nconsole.log('B reads A after A initialised:', readA());\n",
        "cb.mjs": "import * as a from './ca.mjs';\nconsole.log('B before await');\nawait null;\nconsole.log('B after await');\n"
                  "export const fromB = 'b';\nexport function readA() { return a.fromA; }\n",
        "fa.mjs": "import './fb.mjs';\nconsole.log('FA body (never runs)');\n",
        "fb.mjs": "import './fa.mjs';\nimport './fc.mjs';\nconsole.log('FB before await');\nawait null;\n"
                  "throw new RangeError('FB failed after await');\n",
        "fc.mjs": "import './fb.mjs';\nconsole.log('FC body');\n",
    })
    check_script(run, workdir, G, "esm_tla_import_cycles", r'''
const ns = await import('./ca.mjs');
console.log('ca namespace', Object.keys(ns).join(), ns.fromA);
for (const f of ['./fa.mjs', './fa.mjs', './fb.mjs', './fc.mjs']) {
  try { const m = await import(f); console.log(f, 'resolved', Object.keys(m).length); } catch (e) { console.log(f, 'rejected', e.name + ': ' + e.message); }
}
''', filename="main.mjs")
