"""The process/timers/event-loop layer of lumen-cli: argv/env, nextTick vs microtasks vs immediates vs
timers, setInterval/clearInterval, timers/promises, stdin/stdout streams, exit semantics, warnings,
cwd/chdir, worker_threads (and the web Worker) and child_process (sync, async, fork)."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)


def test_argv_and_env(run, workdir):
    """CATCHES: wrong process.argv layout for script arguments (empty strings and dash-prefixed args
    must pass through), env variables from the environment missing, and env assignment semantics
    (the reference keeps the assigned value's type: a number stays a number) or delete not working."""
    check_script(run, workdir, G, "process_argv_env", r'''
const path = require('path');
console.log(process.argv.length, path.basename(process.argv[1]), JSON.stringify(process.argv.slice(2)));
console.log(JSON.stringify([process.env.MYTEST_A, process.env.MYTEST_EMPTY, process.env.MYTEST_UNICODE, process.env.NOPE_NOT_SET]));
console.log('MYTEST_A' in process.env, 'NOPE_NOT_SET' in process.env, Object.keys(process.env).filter((k) => k.startsWith('MYTEST_')).sort().join(','));
process.env.N = 5;
console.log(typeof process.env.N, process.env.N);
process.env.S = 'str';
delete process.env.S;
delete process.env.MYTEST_A;
console.log(process.env.S, process.env.MYTEST_A, 'MYTEST_A' in process.env);
console.log(process.env.TZ, process.env.LANG, typeof process.env.HOME);
''', args=["first", "", "--tier=interp", "-e", "a b", "ünï"],
                 env_overrides={"MYTEST_A": "alpha", "MYTEST_EMPTY": "", "MYTEST_UNICODE": "ü→✓"})


def test_event_loop_ordering(run, workdir):
    """CATCHES: a different interleaving of promise jobs, queueMicrotask, process.nextTick, setImmediate
    and 0 ms timers. In the reference nextTick and setImmediate share one FIFO queue that runs after
    the microtask checkpoint and before due timers, and microtasks drain after every callback."""
    check_script(run, workdir, G, "event_loop_order", r'''
const log = [];
setTimeout(() => log.push('timeout0'), 0);
setImmediate(() => log.push('immediate'));
Promise.resolve().then(() => log.push('promise1')).then(() => log.push('promise2'));
process.nextTick(() => {
  log.push('tick1');
  process.nextTick(() => log.push('tick-nested'));
  Promise.resolve().then(() => log.push('promise-from-tick'));
});
queueMicrotask(() => { log.push('microtask'); process.nextTick(() => log.push('tick-from-micro')); });
process.nextTick((a, b) => log.push('tick2 ' + a + b), 'x', 'y');
setTimeout(() => {
  log.push('timeout1');
  process.nextTick(() => log.push('tick-in-timeout'));
  Promise.resolve().then(() => log.push('promise-in-timeout'));
}, 0);
setTimeout(() => log.push('timeout2'), 0);
setImmediate((arg) => {
  log.push('immediate2 ' + arg);
  setTimeout(() => log.push('timeout-from-immediate'), 0);
  setImmediate(() => {
    log.push('immediate-from-immediate');
    setTimeout(() => console.log(log.join('\n')), 0);
  });
}, 'arg');
(async () => { log.push('async fn sync part'); await null; log.push('after await'); })();
log.push('sync end');
''')


def test_intervals_and_timeouts(run, workdir):
    """CATCHES: setInterval not repeating or not stopping after clearInterval, extra timer arguments not
    passed, clearTimeout not cancelling, delay coercion (negative/NaN -> 0, numeric strings), timer
    ids not being numbers, and the exact TypeErrors for non-function callbacks."""
    check_script(run, workdir, G, "timers_interval", r'''
const t = setTimeout(() => {}, 0);
console.log(typeof t, typeof t.unref);
clearTimeout(t);
// 0 ms timers are scheduled before the interval so their deadlines are always earlier.
setTimeout((...args) => console.log('timeout args', JSON.stringify(args)), 0, 1, 'two', null);
setTimeout(() => console.log('negative delay'), -10);
setTimeout(() => console.log('NaN delay'), NaN);
let n = 0, cleared = false;
const iv = setInterval((a, b) => {
  if (cleared) return;
  n++;
  console.log('tick', n, a, b);
  if (n === 3) { clearInterval(iv); cleared = true; console.log('cleared'); }
}, 15, 'A', 'B');
const cancelled = setTimeout(() => console.log('SHOULD NOT RUN'), 0);
clearTimeout(cancelled);
clearTimeout(undefined); clearTimeout('junk'); clearInterval(null); clearTimeout(99999);
for (const f of [() => setTimeout('code string', 0), () => setInterval(), () => setImmediate(5),
                 () => process.nextTick(5), () => queueMicrotask(5)]) {
  try { f(); console.log('accepted'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
setTimeout(() => console.log('string delay "150"', 'ticks so far', n), '150');
setTimeout(() => console.log('delay 100', 'ticks so far', n), 100);
''')


def test_timers_module_and_immediates(run, workdir):
    """CATCHES: node:timers not exposing the same setTimeout as the global, its setImmediate not
    returning a cancellable Immediate handle (clearImmediate must cancel), or the global
    setImmediate/clearImmediate surface differing (the reference's global setImmediate returns
    undefined and there is no global clearImmediate)."""
    check_script(run, workdir, G, "timers_module", r'''
const timers = require('timers');
console.log(timers.setTimeout === setTimeout, timers.clearInterval === clearInterval, require('node:timers') === timers);
const h = timers.setImmediate((x) => console.log('immediate handle ran', x), 'arg');
const cancelled = timers.setImmediate(() => console.log('SHOULD NOT RUN'));
timers.clearImmediate(cancelled);
console.log(typeof h, h.constructor.name, h.hasRef(), h.ref() === h, h.unref() === h);
console.log(typeof setImmediate(() => console.log('global immediate ran')), typeof globalThis.clearImmediate);
const item = { _onTimeout() { console.log('enrolled timer fired'); } };
timers.enroll(item, 10);
timers.active(item);
const gone = { _onTimeout() { console.log('SHOULD NOT RUN (unenrolled)'); } };
timers.enroll(gone, 5);
timers.active(gone);
timers.unenroll(gone);
console.log('sync end', gone._idleTimeout);
''')


def test_timers_promises(run, workdir):
    """CATCHES: timers/promises resolving with the wrong value, setInterval's async iterator not yielding
    repeatedly / not stopping on break, AbortSignal support (pre-aborted and aborted-while-pending,
    default AbortError vs custom reason), and scheduler.wait/yield."""
    check_script(run, workdir, G, "timers_promises", r'''
import { setTimeout as sleep, setImmediate as immediate, setInterval as every, scheduler } from 'node:timers/promises';
import timers from 'timers';
console.log(await sleep(10, 'slept'), await immediate('imm'), await sleep(1));
let i = 0;
for await (const v of every(5, 'iv')) { console.log(v, ++i); if (i === 3) break; }
const ac = new AbortController();
const pending = sleep(10000, 'never', { signal: ac.signal });
ac.abort();
try { await pending; } catch (e) { console.log(e.name, e.message); }
const ac2 = new AbortController();
ac2.abort(new Error('custom reason'));
for (const f of [() => sleep(5, 'x', { signal: ac2.signal }), () => immediate('x', { signal: ac2.signal }),
                 async () => { for await (const _ of every(5, 1, { signal: ac2.signal })) break; }]) {
  try { await f(); console.log('resolved'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
console.log(await scheduler.wait(5), await scheduler.yield(), timers.promises.setTimeout === sleep);
''', filename="timers_promises.mjs")


def test_stdin_reading(run, workdir):
    """CATCHES: piped stdin not delivered through 'data'/'end' (string chunks after setEncoding, Buffer
    chunks otherwise, bytes preserved exactly), 'end' not firing for empty stdin, readline over stdin
    splitting lines wrongly (CRLF, empty lines) or not firing 'close', and `for await` over stdin not
    collecting all input. Pins that the reference's readline drops a final line that has no trailing
    newline."""
    src = r'''
const chunks = [];
if (process.argv[2] === 'text') process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => chunks.push(c));
process.stdin.on('end', () => {
  const types = [...new Set(chunks.map((c) => Buffer.isBuffer(c) ? 'Buffer' : typeof c))].join('/');
  const all = types === 'string' ? chunks.join('') : Buffer.concat(chunks).toString('hex');
  console.log('end', types || 'none', JSON.stringify(all));
});
console.log('listening', process.stdin.isTTY);
'''
    (workdir / "stdin.js").write_text(src)
    text = run(["stdin.js", "text"], input="line a\nline b ü\n")
    binary = run(["stdin.js", "binary"], input=b"\x00\xff\xfeabc\n")
    empty = run(["stdin.js", "text"], input=b"")
    assert (text.stdout, text.stderr, text.returncode) == (
        'listening false\nend string "line a\\nline b ü\\n"\n'.encode(), b"", 0)
    assert (binary.stdout, binary.stderr, binary.returncode) == (
        b'listening false\nend Buffer "00fffe6162630a"\n', b"", 0)
    assert (empty.stdout, empty.stderr, empty.returncode) == (b'listening false\nend none ""\n', b"", 0)
    write_files(workdir, {
        "rl.js": "const rl = require('readline').createInterface({ input: process.stdin });\nconst lines = [];\n"
                 "rl.on('line', (l) => lines.push(l));\nrl.on('close', () => console.log('lines', JSON.stringify(lines)));\n",
        "iter.js": "(async () => { let s = ''; for await (const c of process.stdin) s += c;\n"
                   "console.log('iterated', JSON.stringify(s)); })();\n",
    })
    rl = run(["rl.js"], input="one\ntwo\r\n\nthree\nlast without newline")
    it = run(["iter.js"], input="async\niteration")
    assert (rl.stdout, rl.stderr, rl.returncode) == (b'lines ["one","two","","three"]\n', b"", 0)
    assert (it.stdout, it.stderr, it.returncode) == (b'iterated "async\\niteration"\n', b"", 0)


def test_stdout_stderr_write(run, workdir):
    """CATCHES: process.stdout.write not accepting Buffers/Uint8Arrays, returning something other than
    true, interleaving wrongly with console.log, or stderr writes landing on stdout. Pins that the
    reference never invokes write callbacks and ignores the encoding argument (hex text is written
    verbatim)."""
    check_script(run, workdir, G, "stdout_write", r'''
const r1 = process.stdout.write('a\n', () => console.log('SHOULD NOT RUN cb1'));
const r2 = process.stdout.write(Buffer.from('buf\n'));
const r3 = process.stdout.write(new Uint8Array([0x75, 0x38, 0x0a]));
const r4 = process.stdout.write('');
process.stderr.write('to stderr\n');
process.stderr.write(Buffer.from('stderr buffer\n'));
console.log('log between');
process.stdout.write('héllo\n', 'utf8', () => console.log('SHOULD NOT RUN cb2'));
process.stdout.write('6869210a', 'hex');
process.stdout.write('\n');
console.log(r1, r2, r3, r4, typeof process.stdout.on, process.stdout.isTTY, process.stdout.fd, process.stderr.fd);
''', stderr="to stderr\nstderr buffer\n")


def test_exit_semantics(run, workdir):
    """CATCHES: process.exit() without an argument ignoring process.exitCode, code coercion of string
    arguments, code after exit() still running, or 'exit'/'beforeExit' listeners being invoked (the
    reference registers them on its EventEmitter but never emits them); custom events do work."""
    write_files(workdir, {
        "a.js": "process.on('exit', (c) => console.log('exit event', c));\nprocess.on('beforeExit', () => console.log('beforeExit'));\n"
                "process.on('custom', (a, b) => console.log('custom event', a, b));\n"
                "console.log(process.emit('custom', 1, 2), process.emit('none'), process.listenerCount('custom'));\n"
                "process.exitCode = 3;\nconsole.log('exitCode now', process.exitCode);\n"
                "setTimeout(() => { console.log('in timer'); process.exit(); console.log('never'); }, 5);\n",
        "b.js": "process.exitCode = 4;\nprocess.exit(undefined);\n",
        "c.js": "process.exit('7');\n",
        "d.js": "process.on('exit', () => console.log('exit event'));\nconsole.log('natural end');\n",
    })
    a, b, c, d = (run([f]) for f in ["a.js", "b.js", "c.js", "d.js"])
    assert (a.stdout, a.stderr, a.returncode) == (b"custom event 1 2\ntrue false 1\nexitCode now 3\nin timer\n", b"", 3)
    assert (b.stdout, b.stderr, b.returncode) == (b"", b"", 4)
    assert (c.stdout, c.stderr, c.returncode) == (b"", b"", 7)
    assert (d.stdout, d.stderr, d.returncode) == (b"natural end\n", b"", 0)


def test_emit_warning(run, workdir):
    """CATCHES: emitWarning lines with a different shape ('(node:PID) [CODE] Type: message', optional
    detail line), the type/code options, Error arguments, or the 'warning' event not being emitted
    synchronously with the Error object."""
    check_script(run, workdir, G, "emit_warning", r'''
const lines = [];
process.stderr.write = (s) => { lines.push(String(s).split(String(process.pid)).join('PID')); return true; };
process.on('warning', (w) => console.log('event:', w.name, w.message, w.code, w instanceof Error));
process.emitWarning('careful now');
process.emitWarning('typed', 'CustomWarning');
process.emitWarning('with code', { type: 'DeprecationWarning', code: 'DEP0001', detail: 'more detail here' });
const e = new RangeError('as error');
process.emitWarning(e);
console.log(JSON.stringify(lines));
''')


def test_cwd_chdir_and_env_file(run, workdir):
    """CATCHES: process.chdir not affecting relative fs paths or process.cwd(), wrong chdir error
    messages, process.loadEnvFile not parsing KEY=VALUE lines (quotes, comments, '=' in values), and
    getBuiltinModule not returning the require()d builtin."""
    write_files(workdir, {".env": "A=1\n# comment\nB = \"quoted value\"\nC='single'\nEMPTY=\n bad line\nD=x=y\n",
                          "sub/.keep": ""})
    check_script(run, workdir, G, "cwd_chdir", r'''
const fs = require('fs');
const start = process.cwd();
const rel = () => process.cwd() === start ? '.' : process.cwd().slice(start.length + 1);
fs.mkdirSync('sub/deeper', { recursive: true });
process.chdir('sub');
console.log(rel(), fs.existsSync('deeper'), fs.existsSync('.keep'));
fs.writeFileSync('here.txt', 'written after chdir');
process.chdir('..');
console.log(rel(), fs.readFileSync('sub/here.txt', 'utf8'));
for (const d of ['nope', 'sub/here.txt']) {
  try { process.chdir(d); } catch (e) { console.log(e.name, e.code, e.message); }
}
process.chdir(start + '/sub/deeper');
console.log(rel());
process.chdir(start);
process.loadEnvFile();
console.log(JSON.stringify([process.env.A, process.env.B, process.env.C, process.env.EMPTY, process.env.D, process.env.bad]));
try { process.loadEnvFile('missing.env'); } catch (e) { console.log(e.name, e.code, e.message); }
console.log(process.getBuiltinModule('fs') === fs, process.getBuiltinModule('node:path') === require('path'), process.getBuiltinModule('nope'));
''')
    assert (workdir / "sub" / "here.txt").read_bytes() == b"written after chdir"


def test_worker_file_round_trip(run, workdir):
    """CATCHES: Worker with a file entry not receiving workerData (structured-cloned), isMainThread/
    threadId wrong on either side, postMessage round trips out of order or losing Map/Date types,
    'online' not preceding the first message, or the worker not exiting with 0 when its port closes."""
    check_script(run, workdir, G, "worker_round_trip", r'''
const { Worker, isMainThread, parentPort, workerData, threadId } = require('worker_threads');
if (isMainThread) {
  console.log('main thread', threadId);
  const w = new Worker(__filename, { workerData: { n: 5, list: [1, 'two'], nested: { ok: true } } });
  console.log('worker threadId', w.threadId);
  w.on('online', () => console.log('online'));
  w.on('message', (m) => {
    console.log('main got', JSON.stringify(m));
    if (m.step === 1) w.postMessage(new Map([['d', new Date(0)], ['arr', [1, 2]]]));
    else if (m.step === 2) w.postMessage('bye');
  });
  w.on('error', (e) => console.log('error', e.message));
  w.on('exit', (c) => console.log('exit', c));
} else {
  parentPort.postMessage({ step: 1, wd: workerData, main: isMainThread, tid: threadId });
  parentPort.on('message', (m) => {
    if (m === 'bye') { parentPort.close(); return; }
    parentPort.postMessage({ step: 2, isMap: m instanceof Map, size: m.size, date: m.get('d') instanceof Date, iso: m.get('d').toISOString(), arr: m.get('arr') });
  });
}
''')


def test_worker_eval_errors_and_exit_codes(run, workdir):
    """CATCHES: eval workers not supported, an uncaught worker exception not surfacing as 'error' then
    'exit' with code 1 (after messages posted before the throw), process.exit(n) in a worker not
    becoming the exit code, terminate() not stopping a worker kept alive by a timer (its promise
    resolves after 'exit'), or a bare filename being accepted as the worker entry."""
    check_script(run, workdir, G, "worker_eval_errors", r'''
const { Worker } = require('worker_threads');
const steps = [
  () => new Promise((done) => {
    const w = new Worker(`const { parentPort, workerData } = require('worker_threads');
      parentPort.postMessage(workerData * 2); throw new TypeError('boom in worker');`, { eval: true, workerData: 21 });
    w.on('message', (m) => console.log('A message', m));
    w.on('error', (e) => console.log('A error', e.name, e.message));
    w.on('exit', (c) => { console.log('A exit', c); done(); });
  }),
  () => new Promise((done) => {
    const w = new Worker(`const { parentPort } = require('worker_threads');
      parentPort.on('message', (m) => { if (m === 'stop') { process.exit(7); return; } parentPort.postMessage(m + '!'); });`, { eval: true });
    w.on('message', (m) => { console.log('B message', m); w.postMessage('stop'); });
    w.on('exit', (c) => { console.log('B exit', c); done(); });
    w.postMessage('hi');
  }),
  () => new Promise((done) => {
    const w = new Worker(`setInterval(() => {}, 1000); require('worker_threads').parentPort.postMessage('started');`, { eval: true });
    w.on('message', async (m) => { console.log('C message', m); console.log('C terminate resolved', await w.terminate()); done(); });
    w.on('exit', (c) => console.log('C exit', c));
  }),
  () => {
    try { new Worker('not-relative.js'); } catch (e) { console.log('D', e.name + ': ' + e.message); }
  },
];
(async () => { for (const s of steps) await s(); console.log('all done'); })();
''')


def test_web_worker_module(run, workdir):
    """CATCHES: the global web Worker (module type) not delivering MessageEvents both ways via
    onmessage/postMessage, `self` not being the worker global, or terminate() not ending it."""
    write_files(workdir, {"wk.mjs": "self.onmessage = (e) => { postMessage({ n: e.data.n, from: 'worker', isSelf: self === globalThis }); };\n"})
    check_script(run, workdir, G, "web_worker", r'''
const w = new Worker(new URL('./wk.mjs', import.meta.url).href, { type: 'module' });
w.onmessage = (e) => {
  console.log('main got', JSON.stringify(e.data), e.constructor.name, e.type);
  if (e.data.n === 2) { w.terminate(); console.log('terminated'); } else w.postMessage({ n: e.data.n + 1 });
};
w.postMessage({ n: 0 });
''', filename="main.mjs")


def test_child_process_sync_and_errors(run, workdir):
    """CATCHES: spawnSync/execSync/execFileSync not capturing stdout/stderr separately, wrong status,
    Buffer vs string results by encoding, the `input` option not feeding stdin, cwd/shell options
    ignored, spawning the lumen binary itself (process.execPath) failing, or different error shapes for
    failing children ('Command failed: ...' with status/stderr; a missing program throws from spawnSync
    too instead of returning result.error). Pins that the sync variants ignore the `env` option."""
    check_script(run, workdir, G, "child_sync", r'''
const cp = require('child_process');
const r = cp.spawnSync('sh', ['-c', 'echo out; echo err >&2; exit 3']);
console.log(r.status, r.signal, JSON.stringify(r.stdout.toString()), JSON.stringify(r.stderr.toString()), Buffer.isBuffer(r.stdout), r.output.length, r.output[0]);
const r2 = cp.spawnSync('cat', [], { input: 'fed via input', encoding: 'utf8' });
console.log(r2.status, JSON.stringify(r2.stdout), typeof r2.stdout, JSON.stringify(r2.output));
console.log(JSON.stringify(cp.spawnSync('echo', ['$HOME', 'a  b'], { encoding: 'utf8' }).stdout));
console.log(JSON.stringify(cp.spawnSync('echo $((6 * 7))', { shell: true, encoding: 'utf8' }).stdout));
console.log(JSON.stringify(cp.execSync('echo hello; echo world').toString()), Buffer.isBuffer(cp.execSync('true')));
console.log(JSON.stringify(cp.execSync('cat', { input: Buffer.from('abc'), encoding: 'utf8' })));
console.log(JSON.stringify(cp.execFileSync('echo', ['a  b', 'c'], { encoding: 'utf8' })));
console.log(JSON.stringify(cp.execSync('pwd', { cwd: '/', encoding: 'utf8' })));
const node = cp.spawnSync(process.execPath, ['-e', 'console.log(1 + 1); console.error("e"); process.exit(5)'], { encoding: 'utf8' });
console.log(node.status, JSON.stringify(node.stdout), JSON.stringify(node.stderr));
const fed = cp.execFileSync(process.execPath, [], { input: 'console.log("stdin program", 6 * 7)', encoding: 'utf8' });
console.log(JSON.stringify(fed));
''')
    check_script(run, workdir, G, "child_errors", r'''
const cp = require('child_process');
try { cp.execSync('echo partial; echo bad >&2; exit 2'); }
catch (e) { console.log(e.name, e.status, JSON.stringify(e.message), JSON.stringify(String(e.stderr)), e.stdout); }
try { cp.execFileSync('sh', ['-c', 'echo out; exit 9']); }
catch (e) { console.log(e.name, e.status, JSON.stringify(e.message), JSON.stringify(String(e.stdout))); }
for (const f of [() => cp.spawnSync('definitely-not-a-program-xyz'), () => cp.execFileSync('definitely-not-a-program-xyz')]) {
  try { f(); console.log('no throw'); } catch (e) { console.log(e.name, e.code, e.message); }
}
console.log(JSON.stringify(cp.execSync('echo "[$CHILD_VAR]"', { env: { CHILD_VAR: 'set', PATH: process.env.PATH }, encoding: 'utf8' })));
''')


def test_child_process_async(run, workdir):
    """CATCHES: async spawn not streaming stdout/stderr, stdin writes not reaching the child, 'exit'
    and 'close' not both firing with the code (exit strictly before close), exec/execFile callbacks
    with the wrong (err, stdout, stderr) values, the async env option ignored, or a lumen child
    failing. (The reference emits 'close' right after 'exit', not after stdio drains, so every child
    here only exits once the parent has seen its output.)"""
    check_script(run, workdir, G, "child_async", r'''
const cp = require('child_process');
function step1(next) {
  const child = cp.spawn('sh', ['-c', 'read x; echo "got $x"; echo "err $x" >&2; read y; exit 4']);
  let out = '', err = '';
  child.stdout.on('data', (d) => { out += d; if (out.endsWith('\n') && err.endsWith('\n')) child.stdin.end(); });
  child.stderr.on('data', (d) => { err += d; if (out.endsWith('\n') && err.endsWith('\n')) child.stdin.end(); });
  child.on('exit', (code, sig) => console.log('exit', code, sig, child.exitCode));
  child.on('close', (code, sig) => { console.log('close', code, sig, JSON.stringify(out), JSON.stringify(err)); next(); });
  child.stdin.write('value\n');
  console.log('spawned', typeof child.pid, typeof child.kill, child.exitCode);
}
function step2(next) {
  const c = cp.exec('echo via exec; read x; exit 1', (err, stdout, stderr) => {
    console.log('exec cb', err && err.code, err && err.message, JSON.stringify(stdout), JSON.stringify(stderr));
    next();
  });
  c.stdout.once('data', () => c.stdin.end());
}
function step3(next) {
  const c = cp.execFile('sh', ['-c', 'echo "[$CHILD_VAR]"; read x'], { env: { CHILD_VAR: 'async env', PATH: process.env.PATH } }, (err, stdout, stderr) => {
    console.log('execFile cb', err, JSON.stringify(stdout), JSON.stringify(stderr));
    next();
  });
  c.stdout.once('data', () => c.stdin.end());
}
function step4(next) {
  const p = cp.spawn(process.execPath, ['-e', 'process.stdin.on("data", (d) => process.stdout.write(String(d).toUpperCase())); process.stdin.on("end", () => process.exit(2))']);
  p.stdout.setEncoding('utf8');
  let upper = '';
  p.stdout.on('data', (d) => { upper += d; if (upper === 'SHOUT') p.stdin.end(); });
  p.on('close', (c) => { console.log('lumen child close', c, JSON.stringify(upper)); next(); });
  p.stdin.write('shout');
}
step1(() => step2(() => step3(() => step4(() => console.log('done')))));
''')


def test_fork_ipc(run, workdir):
    """CATCHES: child_process.fork without an IPC channel (process.send/'message' in the child),
    messages not JSON round-tripping in order in both directions, script arguments not reaching the
    child, or the child's exit code not reaching the parent's 'exit' event."""
    check_script(run, workdir, G, "fork_ipc", r'''
const { fork } = require('child_process');
if (process.argv[2] === 'child') {
  process.on('message', (m) => {
    if (m === 'quit') process.exit(3);
    process.send({ echo: m, doubled: m.n * 2, argv: process.argv.slice(2), connected: process.connected });
  });
  process.send('ready');
} else {
  const c = fork(__filename, ['child', 'extra']);
  c.on('message', (m) => {
    console.log('parent got', JSON.stringify(m));
    if (m === 'ready') { c.send({ n: 1 }); c.send({ n: 2, nested: [true, null] }); }
    else if (m.echo.n === 2) c.send('quit');
  });
  c.on('exit', (code) => console.log('child exit', code));
  console.log('forked', c.connected, typeof c.send);
}
''')


def test_umask_and_signals(run, workdir):
    """CATCHES: process.umask not setting/returning the creation mask (files and directories created
    afterwards must carry it), a numeric-string mask parsed as octal (the reference parses '027' as
    decimal 27), process.kill(pid, 0) not returning true, or children killed by a signal (including
    an unknown signal name, which the reference maps to SIGTERM) not reporting status null."""
    check_script(run, workdir, G, "umask_signals", r'''
const fs = require('fs');
const cp = require('child_process');
const prev = process.umask(0o077);
console.log(typeof prev, process.umask() === 0o077, process.umask('027'), process.umask(0o077));
fs.writeFileSync('private.txt', 'x');
fs.mkdirSync('privdir');
process.umask(0o022);
fs.writeFileSync('public.txt', 'y');
fs.mkdirSync('pubdir/nested', { recursive: true });
console.log(process.umask(prev) === 0o022);
for (const f of ['private.txt', 'privdir', 'public.txt', 'pubdir', 'pubdir/nested']) console.log(f, (fs.statSync(f).mode & 0o777).toString(8));
console.log(process.kill(process.pid, 0), typeof process.kill);
for (const code of ['process.kill(process.pid)', 'process.kill(process.pid, "SIGNOPE")', 'process.kill(process.pid, "SIGKILL")',
                    'console.log(process.kill(process.pid, 0))', 'process.kill(process.pid, 15)']) {
  const r = cp.spawnSync(process.execPath, ['-e', code], { encoding: 'utf8' });
  console.log(JSON.stringify(code), r.status, r.signal, JSON.stringify(r.stdout), JSON.stringify(r.stderr));
}
const c = cp.spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000); console.log("child up")']);
c.stdout.on('data', (d) => { console.log('child said', String(d).trim(), 'kill returned', c.kill(), c.killed); });
c.on('exit', (code, sig) => console.log('exit', code, sig));
''')
    modes = {f: oct((workdir / f).stat().st_mode & 0o777) for f in ["private.txt", "privdir", "public.txt", "pubdir", "pubdir/nested"]}
    assert modes == {"private.txt": "0o600", "privdir": "0o700", "public.txt": "0o644", "pubdir": "0o755",
                     "pubdir/nested": "0o755"}


def test_unref_lets_process_exit(run, workdir):
    """CATCHES: child.unref()/worker.unref() not releasing the event loop (the program would hang on a
    child blocked on stdin or a worker with a live interval), or unref also cancelling the pending
    work it should only stop waiting for (later timers must still run)."""
    check_script(run, workdir, G, "unref_exit", r'''
const { Worker } = require('worker_threads');
const cp = require('child_process');
const c = cp.spawn('sh', ['-c', 'echo child up; read x']);
c.stdout.once('data', (d) => {
  console.log(String(d).trim());
  c.unref();
  console.log('child unref');
  const w = new Worker('setInterval(() => {}, 1000); require("worker_threads").parentPort.postMessage("worker up");', { eval: true });
  w.once('message', (m) => {
    console.log(m);
    w.unref();
    console.log('worker unref');
    setTimeout(() => console.log('timer after unref still runs'), 20);
  });
});
''')
