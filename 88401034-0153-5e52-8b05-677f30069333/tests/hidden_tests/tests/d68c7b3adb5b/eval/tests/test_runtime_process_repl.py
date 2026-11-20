"""The runtime layer seen from the command line: entry points (script / -e / piped stdin / repl),
CLI argument errors, the REPL, `process`, the event-loop order of timers/ticks/microtasks,
`console`, `child_process` and `worker_threads`.

Every program runs in the empty per-test workdir and prints only relative or derived facts.
Machine-specific text (the version in the REPL banner, the PID in warning lines) is normalised
in Python before comparing. Cross-thread / cross-process programs only print in causally forced
orders (e.g. after a message round trip or a child's 'close').
"""

import re
import shutil

import pytest

from conftest import err, out

TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"),
         pytest.param(("--tier=interp",), id="interp")]

BANNER = re.compile(r"lumen \S.* \(\.help for help, \.exit or Ctrl-D to quit\)")


def repl(run, lines, *flags):
    """Feed `lines` to `lumen-cli [flags] repl`; check the banner line and return (proc, rest)."""
    r = run([*flags, "repl"], input="".join(line + "\n" for line in lines))
    head, _, rest = out(r).partition("\n")
    assert BANNER.fullmatch(head), head
    return r, rest


# ----------------------------------------------------------------------------------- CLI entry
def test_missing_script_or_directory_is_a_usage_error(run, workdir):
    """CATCHES: a CLI that crashes, reports a raw OS error, exits 1, or tries to run a directory
    instead of printing `cannot read <path>: not a file` and exiting 2 for a missing path or a
    directory given as the script."""
    (workdir / "pkgdir").mkdir()
    r = run(["nope.js", "extra"])
    assert (r.returncode, out(r), err(r)) == (2, "", "cannot read nope.js: not a file\n")
    r = run(["pkgdir"])
    assert (r.returncode, out(r), err(r)) == (2, "", "cannot read pkgdir: not a file\n")
    r = run(["--tier=interp", "sub/missing.mjs"])
    assert (r.returncode, out(r), err(r)) == (2, "", "cannot read sub/missing.mjs: not a file\n")


def test_unknown_tier_and_missing_eval_code_exit_2(run):
    """CATCHES: argument parsing that silently ignores an unknown --tier value or a trailing -e
    with no code (running nothing and exiting 0) instead of reporting the exact error and exiting
    2 before any JS runs."""
    r = run(["--tier=foo", "-e", "console.log('ran')"])
    assert (r.returncode, out(r), err(r)) == (2, "", "unknown tier 'foo' (interp|bytecode)\n")
    for flag in ("-e", "--eval"):
        r = run(["--tier=interp", flag])
        assert (r.returncode, out(r), err(r)) == (2, "", "-e expects code\n")


@pytest.mark.parametrize("tier", TIERS)
def test_eval_syntax_error_reports_line_and_runs_nothing(run, tier):
    """CATCHES: an -e evaluator that runs the statements before a syntax error, reports the wrong
    line number, prefixes the message with `Uncaught`, or exits 0/2 instead of exiting 1 with
    `SyntaxError: <msg> (line N)`."""
    code = "console.log('first');\nlet fine = 1;\nlet x = ;\n"
    r = run([*tier, "-e", code])
    assert (r.returncode, out(r)) == (1, "")
    assert err(r) == 'SyntaxError: unexpected token Punct(";") (line 3)\n'


def test_eval_uncaught_error_after_streamed_output(run):
    """CATCHES: an -e runner that buffers console output and loses it when the script throws, that
    renders a custom error class without its own name, or exits 0 after an uncaught throw."""
    code = ("console.log('before'); console.error('err line');"
            "class AppError extends Error { constructor(m) { super(m); this.name = 'AppError'; } }"
            "throw new AppError('it broke');")
    for argv in (["-e", code], ["--eval", code], ["-e", code, "--tier=interp"], ["--tier=bytecode", "--eval", code]):
        r = run(argv)
        assert (r.returncode, out(r)) == (1, "before\n")
        assert err(r) == "err line\nUncaught AppError: it broke\n"


def test_piped_stdin_runs_as_a_script_with_the_event_loop(run):
    """CATCHES: a CLI that opens the REPL (printing a banner and prompts) when stdin is a pipe, or
    evaluates stdin without running the event loop so timers and promises never settle."""
    src = r"""
const parts = ['sync'];
setTimeout(() => { parts.push('timer'); console.log(parts.join('>'), process.argv.length); }, 5);
Promise.resolve().then(() => parts.push('promise'));
"""
    r = run([], input=src)
    assert out(r) == "sync>promise>timer 1\n"
    assert (r.returncode, r.stderr) == (0, b"")


def test_piped_stdin_uncaught_error_exits_1(run):
    """CATCHES: stdin evaluation that swallows an uncaught throw (exit 0) or prints it before the
    output that preceded it, instead of `Uncaught TypeError: ...` on stderr with exit 1."""
    r = run([], input="console.log('one'); null.prop;\nconsole.log('two');\n")
    assert (r.returncode, out(r)) == (1, "one\n")
    assert err(r) == "Uncaught TypeError: cannot read property 'prop' of null\n"


def test_script_argv_keeps_user_args_verbatim(js):
    """CATCHES: argv handling that drops the script path, splits arguments containing spaces,
    or interprets flag-looking arguments after the script (`-e`, `--tier=…`, `repl`) as CLI
    options instead of passing them to the script."""
    code = r"""
console.log(JSON.stringify(process.argv.slice(1)));
console.log(process.argv.length, process.argv0 === process.argv[0], process.execPath === process.argv[0]);
console.log(require.main === module, typeof process.argv[0]);
"""
    expected = '["main.js","a b","--tier=interp","-e","repl",""]\n7 true true\ntrue string\n'
    r = js(code, args=("a b", "--tier=interp", "-e", "repl", ""))
    assert (r.returncode, out(r), r.stderr) == (0, expected, b"")
    r = js(code, args=("a b", "--tier=interp", "-e", "repl", ""), env_overrides={"LUMEN_TIER": "interp"})
    assert (r.returncode, out(r), r.stderr) == (0, expected, b"")


# ------------------------------------------------------------------------------------- the REPL
@pytest.mark.parametrize("tier", TIERS)
def test_repl_session_values_continuation_and_dot_commands(run, golden, tier):
    """CATCHES: a REPL that forgets bindings between inputs, prints strings unquoted, does not
    update `_`, evaluates an unfinished function body instead of showing `..` continuation
    prompts, mishandles .help/unknown dot-commands, or keeps reading after .exit."""
    lines = [
        "1 + 1",
        "'str' + \"ing\"",
        "let x = 5",
        "x * 2",
        "_ + 1",
        "",
        "function add(a, b) {",
        "  return a + b;",
        "}",
        "add(40, 2)",
        "[1, 2, 3].map(n => n * n)",
        "null",
        "Symbol('tag')",
        "10n ** 3n",
        ".help",
        ".bogus",
        "x",
        ".exit",
        "console.log('not reached')",
    ]
    r, rest = repl(run, lines, *tier)
    assert rest == golden("repl_session")
    assert (r.returncode, r.stderr) == (0, b"")


def test_repl_top_level_await_and_loop_quiescence(run, golden):
    """CATCHES: a REPL without top-level-await sugar, one that prints the next prompt before
    awaited timers/promises settle, that reports a rejected await as a value, or that hangs on a
    promise that can never settle instead of printing `[promise never settled]`."""
    lines = [
        "await Promise.resolve(7)",
        "await new Promise(r => setTimeout(() => r('late'), 5))",
        "setTimeout(() => console.log('timer ran before prompt'), 5); 'sync value'",
        "await Promise.reject(new TypeError('nope'))",
        "await new Promise(() => {})",
        "const y = await Promise.resolve(3); y * 2",
        "Promise.resolve(1).then(v => console.log('then', v)), 'expr'",
        "typeof y",
    ]
    r, rest = repl(run, lines)
    assert rest == golden("repl_await")
    assert (r.returncode, r.stderr) == (0, b"")


def test_repl_errors_do_not_end_the_session(run, golden):
    """CATCHES: a REPL that exits on the first thrown error or syntax error, prints errors without
    the `Uncaught` prefix, leaves a broken input in the continuation buffer, or does not print a
    final newline at end of input."""
    lines = [
        "throw new RangeError('bad range')",
        "undefinedName + 1",
        "let = = 3",
        "({}).x.y",
        "throw 'plain string'",
        "'still alive'",
        "await )",
        "if (true) {",
    ]
    r, rest = repl(run, lines, "--tier=bytecode")
    assert rest == golden("repl_errors")
    assert (r.returncode, r.stderr) == (0, b"")


# -------------------------------------------------------------------------------------- process
@pytest.mark.parametrize("snippet,code,expected", [
    ("process.exit(3)", 3, "start\nmicrotask\n"),
    ("process.exitCode = 5; process.exit()", 5, "start\nmicrotask\n"),
    ("process.exitCode = 5; process.exit(0)", 0, "start\nmicrotask\n"),
    ("process.exit('7')", 7, "start\nmicrotask\n"),
])
def test_process_exit_codes_and_pending_work_is_dropped(js, snippet, code, expected):
    """CATCHES: process.exit that ignores its argument or process.exitCode, coerces string codes
    wrongly, or lets already-scheduled timers run after exit was requested."""
    program = ("console.log('start');\nsetTimeout(() => console.log('timer must not run'), 300);\n"
               "Promise.resolve().then(() => { console.log('microtask'); " + snippet + "; });\n")
    r = js(program)
    assert (r.returncode, out(r), r.stderr) == (code, expected, b"")


def test_stdout_and_stderr_streams_route_raw_bytes(js):
    """CATCHES: process.stdout.write that appends newlines or mangles Uint8Array chunks, or a
    console whose info/debug go to stderr or warn/error go to stdout."""
    code = r"""
process.stdout.write('no newline|');
process.stdout.write(new Uint8Array([0x68, 0x69, 0x0a]));
process.stdout.end('ended\n');
process.stderr.write('raw err|');
process.stderr.write(new TextEncoder().encode('bytes\n'));
console.info('info', 1);
console.debug('debug', [1, 2]);
console.warn('warn', null);
console.error('error', undefined, Symbol('s'));
console.log(process.stdout.isTTY, process.stdout.fd, process.stderr.fd, process.stdout.write('') === true);
console.log(Symbol(), { toString() { throw new Error('no'); } }, Object.create(null), [1, [2, [3]]], -0, 1e21);
"""
    r = js(code)
    assert out(r) == ("no newline|hi\nended\ninfo 1\ndebug 1,2\nfalse 1 2 true\n"
                      "Symbol() [object] [object] 1,2,3 0 1e+21\n")
    assert err(r) == "raw err|bytes\nwarn null\nerror undefined Symbol(s)\n"
    assert r.returncode == 0


def test_env_snapshot_and_load_env_file(js, workdir):
    """CATCHES: process.env that does not reflect the launching environment (including empty
    values), treats missing keys as present, or a loadEnvFile that mis-parses quotes, comments
    and `=` inside values."""
    (workdir / "app.env").write_text("# comment\nA=1\nQUOTED=\"two words\"\nSINGLE='x=y'\n\nBAD LINE\n EQ = spaced \n")
    code = r"""
console.log(process.env.LUMEN_SUITE_VAR, JSON.stringify(process.env.LUMEN_EMPTY_VAR), 'LUMEN_EMPTY_VAR' in process.env);
console.log(process.env.LUMEN_NOT_SET, 'LUMEN_NOT_SET' in process.env, process.env.TZ);
process.env.LUMEN_NEW = 'assigned';
console.log(process.env.LUMEN_NEW);
process.loadEnvFile('app.env');
console.log(process.env.A, process.env.QUOTED, process.env.SINGLE, JSON.stringify(process.env.EQ));
try { process.loadEnvFile('missing.env'); } catch (e) { console.log('missing:', e.code); }
"""
    r = js(code, env_overrides={"LUMEN_SUITE_VAR": "val=1 two", "LUMEN_EMPTY_VAR": ""})
    assert out(r) == ('val=1 two "" true\nundefined false UTC\nassigned\n'
                      '1 two words x=y "spaced"\nmissing: ENOENT\n')
    assert (r.returncode, r.stderr) == (0, b"")


def test_cwd_and_chdir(js, workdir):
    """CATCHES: process.cwd that is not the launch directory, a chdir that does not affect later
    relative file access, a chdir failure that does not throw an ENOENT error, or a cwd() that
    does not throw once the working directory itself has been deleted."""
    (workdir / "sub").mkdir()
    (workdir / "sub" / "marker.txt").write_text("in sub")
    code = r"""
const fs = require('fs'), path = require('path');
const start = process.cwd();
console.log(path.isAbsolute(start), fs.realpathSync(start) === fs.realpathSync('.'), fs.existsSync('main.js'));
process.chdir('sub');
console.log(path.basename(process.cwd()), path.dirname(process.cwd()) === start, fs.readFileSync('marker.txt', 'utf8'));
process.chdir('..');
console.log(process.cwd() === start);
try { process.chdir('/definitely/not/here'); } catch (e) { console.log(e.message); }
const doomed = path.join(process.cwd(), 'doomed');
fs.mkdirSync(doomed);
process.chdir('doomed');
fs.rmdirSync(doomed);
try { process.cwd(); } catch (e) { console.log(e.message); }
process.reallyExit();
console.log('not reached');
"""
    r = js(code)
    assert out(r) == ("true true true\nsub true in sub\ntrue\n"
                      "ENOENT: chdir '/definitely/not/here': No such file or directory (os error 2)\n"
                      "cwd unavailable: No such file or directory (os error 2)\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_emit_warning_line_detail_and_event(js):
    """CATCHES: emitWarning that skips the `(node:PID) [code] Name: message` stderr line, drops the
    detail line, ignores a string type argument, or never emits the 'warning' event."""
    code = r"""
process.on('warning', (w) => console.log('event', w.name, w.message, w.code, w instanceof Error));
process.emitWarning('careful', { code: 'W1', detail: 'some detail' });
process.emitWarning('old api', 'DeprecationWarning');
const e = new Error('from error'); e.name = 'CustomWarning';
process.emitWarning(e);
"""
    r = js(code)
    assert out(r) == ("event Warning careful W1 true\nevent DeprecationWarning old api undefined true\n"
                      "event CustomWarning from error undefined true\n")
    stderr = re.sub(r"^\(node:\d+\) ", "(node:PID) ", err(r), flags=re.M)
    assert stderr == ("(node:PID) [W1] Warning: careful\nsome detail\n(node:PID) DeprecationWarning: old api\n"
                      "(node:PID) CustomWarning: from error\n")
    assert r.returncode == 0


def test_process_metrics_have_node_shapes(js):
    """CATCHES: hrtime/hrtime.bigint/uptime/memoryUsage/cpuUsage/resourceUsage that return the
    wrong types or shapes, or an hrtime(prev) diff that is not a [seconds, nanoseconds] pair."""
    code = r"""
const t = process.hrtime();
const d = process.hrtime(t);
console.log(Array.isArray(t), t.length, Number.isInteger(t[0]), t[1] >= 0 && t[1] < 1e9, d.length, d[0] >= 0);
console.log(typeof process.hrtime.bigint(), process.hrtime.bigint() >= 0n, typeof process.uptime());
const mu = process.memoryUsage();
console.log(Object.keys(mu).join(','), mu.rss > 0, typeof process.memoryUsage.rss());
const cpu = process.cpuUsage();
console.log(Object.keys(cpu).join(','), Object.keys(process.cpuUsage(cpu)).join(','));
console.log(Object.keys(process.resourceUsage()).length, typeof process.availableMemory());
console.log(process.version, process.versions.node, typeof process.versions.lumen, process.release.name);
console.log(typeof process.pid, typeof process.ppid, process.execArgv.length, typeof process.title);
console.log(process.features.inspector, process.getActiveResourcesInfo().length, process.permission.has('fs'));
"""
    r = js(code)
    assert out(r) == ("true 2 true true 2 true\nbigint true number\n"
                      "rss,heapTotal,heapUsed,external,arrayBuffers true number\nuser,system user,system\n"
                      "16 number\nv20.11.0 20.11.0 string node\nnumber number 0 string\nfalse 0 true\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_execve_replaces_the_process_image(js):
    """CATCHES: process.execve that validates its arguments wrongly, does not pass argv/env to the
    new image, returns and lets the script continue, or loses output written before the exec."""
    code = r"""
for (const bad of [[1, [], {}], ['/bin/sh', 'x', {}], ['/bin/sh', [], null], ['/bin/sh', ['a\0b'], {}]]) {
  try { process.execve(...bad); } catch (e) { console.log(e.constructor.name, e.message); }
}
console.log('before exec');
process.execve('/bin/sh', ['sh', '-c', 'echo "replaced $GREETING $0"; exit 6', 'zero'], { GREETING: 'hi', SKIP: undefined });
console.log('not reached');
"""
    r = js(code)
    assert out(r) == ('TypeError The "file" argument must be of type string\n'
                      'TypeError The "args" argument must be an Array\n'
                      'TypeError The "env" argument must be an object\n'
                      "TypeError execve arguments may not contain null bytes\n"
                      "before exec\nreplaced hi zero\n")
    assert (r.returncode, r.stderr) == (6, b"")


def test_kill_self_with_sigterm(js):
    """CATCHES: process.kill that ignores signal names, cannot probe with signal 0, or never
    delivers the signal (the script would print `survived` and exit 0 instead of dying by
    SIGTERM)."""
    code = r"""
console.log('alive', process.kill(process.pid, 0));
setTimeout(() => console.log('survived'), 5000);
process.kill(process.pid, 'SIGTERM');
"""
    r = js(code)
    assert (r.returncode, out(r), r.stderr) == (-15, "alive true\n", b"")


def test_umask_and_identity_calls(js, workdir):
    """CATCHES: a umask that does not return the previous mask or is not applied to newly
    created files, identity setters that fail for the current ids, or a setgroups that accepts
    non-arrays."""
    code = r"""
const fs = require('fs');
const old = process.umask(0o077);
fs.writeFileSync('private.txt', 'x');
console.log((fs.statSync('private.txt').mode & 0o777).toString(8));
console.log(process.umask(old).toString(8), process.umask() === old);
console.log(process.setuid(process.getuid()), process.setgid(process.getgid()));
console.log(process.seteuid(process.geteuid()), process.setegid(process.getegid()));
console.log(Array.isArray(process.getgroups()), typeof process.getuid(), typeof process.getegid());
try { process.setgroups('nope'); } catch (e) { console.log(e.message); }
try { process.setgroups(['abc']); } catch (e) { console.log(e.constructor.name, e.message); }
try { process.initgroups('a\0b', 0); } catch (e) { console.log(e.constructor.name, e.message); }
"""
    r = js(code)
    assert out(r) == ('600\n77 true\nundefined undefined\nundefined undefined\ntrue number number\n'
                      'The "groups" argument must be an Array\n'
                      "TypeError group ids must be numbers\nTypeError user contains a null byte\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_stdin_stream_reads_piped_input(js):
    """CATCHES: a process.stdin that never emits data for piped input, splits it wrongly, or never
    emits 'end' (so the program would hang or print nothing)."""
    code = r"""
const chunks = [];
process.stdin.on('data', (c) => chunks.push(c));
process.stdin.on('end', () => {
  const text = Buffer.concat(chunks).toString();
  const lines = text.split('\n').filter(Boolean);
  console.log(lines.length, lines.map((l) => l.toUpperCase()).reverse().join('|'), Buffer.byteLength(text));
});
"""
    r = js(code, input="alpha\nbeta\ngamma é\n")
    assert out(r) == "3 GAMMA É|BETA|ALPHA 20\n"
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------- event loop and uncaught errors
@pytest.mark.parametrize("tier", TIERS)
def test_loop_turn_order_of_microtasks_ticks_immediates_timers(js, golden, tier):
    """CATCHES: an event loop that fires timers before draining microtasks or queued nextTick/
    setImmediate callbacks, skips the microtask checkpoint after each timer callback, loses
    extra callback arguments, or fires same-deadline timers out of scheduling order."""
    code = r"""
const order = [];
setTimeout(() => order.push('timeout 0'), 0);
process.nextTick((a, b) => order.push(`tick ${a}${b}`), 'x', 'y');
process.nextTick(() => order.push('tick 2'));
Promise.resolve().then(() => order.push('promise 1')).then(() => order.push('promise 2'));
queueMicrotask(() => order.push('queueMicrotask'));
setImmediate((v) => order.push('immediate ' + v), 'arg');
setTimeout(() => {
  order.push('timeout 40');
  Promise.resolve().then(() => order.push('microtask inside timeout 40'));
}, 40);
setTimeout(() => order.push('timeout 40 again'), 40);
setTimeout(() => console.log(order.join('\n')), 120);
try { queueMicrotask(5); } catch (e) { order.push(e.constructor.name + ': ' + e.message); }
try { process.nextTick('x'); } catch (e) { order.push(e.constructor.name + ': ' + e.message); }
"""
    r = js(code, *tier)
    assert out(r) == golden("loop_order")
    assert (r.returncode, r.stderr) == (0, b"")


def test_timer_apis_args_clearing_intervals_and_promises(js, golden):
    """CATCHES: timers that drop extra arguments, cannot be cleared (including by clearInterval
    on a timeout id), mis-coerce string/NaN/negative delays, keep intervals running after
    clearInterval, or a timers/promises module whose abort path does not reject with AbortError."""
    code = r"""
const out = [];
const tp = require('timers/promises');
const timers = require('timers');
setTimeout((a, b) => out.push(`args ${a} ${b}`), 15, 'one', 2);
const cancelled = setTimeout(() => out.push('cancelled timeout ran'), 5);
clearTimeout(cancelled);
const viaInterval = setTimeout(() => out.push('cleared via clearInterval ran'), 5);
clearInterval(viaInterval);
clearTimeout(undefined); clearTimeout('nonsense'); clearTimeout(99999);
setTimeout(() => out.push('string delay'), '30');
setTimeout(() => out.push('NaN delay'), NaN);
setTimeout(() => out.push('negative delay'), -50);
let n = 0;
const iv = setInterval((tag) => { out.push(`${tag} ${++n}`); if (n === 3) clearInterval(iv); }, 60, 'interval');
const imm = timers.setImmediate(() => out.push('cancelled immediate ran'));
timers.clearImmediate(imm);
timers.setImmediate((x) => out.push('immediate ' + x), 'ok');
console.log(typeof cancelled, cancelled !== viaInterval, typeof imm, imm.hasRef());
for (const bad of [() => setTimeout('code'), () => setInterval(null), () => setImmediate(1)]) {
  try { bad(); } catch (e) { out.push(e.constructor.name + ': ' + e.message); }
}
(async () => {
  out.push('tp ' + await tp.setTimeout(400, 'value'));
  out.push('tp immediate ' + await tp.setImmediate('iv'));
  const ac = new AbortController();
  const p = tp.setTimeout(10000, 'never', { signal: ac.signal });
  ac.abort();
  try { await p; } catch (e) { out.push(`aborted ${e.name}`); }
  let k = 0;
  for await (const v of tp.setInterval(5, 'tick')) { out.push(`${v} ${++k}`); if (k === 2) break; }
  await tp.scheduler.wait(5);
  console.log(out.join('\n'));
})();
"""
    r = js(code)
    assert out(r) == golden("timer_apis")
    assert (r.returncode, r.stderr) == (0, b"")


def test_uncaught_callback_errors_are_reported_and_loop_continues(js):
    """CATCHES: a loop that dies on the first throwing timer callback, does not report unhandled
    rejections as `Uncaught (in promise) …`, reports a rejection that was handled later in the
    same checkpoint, or turns callback errors into a non-zero exit."""
    code = r"""
setTimeout(() => { throw new TypeError('in timer'); }, 0);
setTimeout(() => { console.log('second timer still runs'); Promise.reject(new RangeError('late reject')); }, 20);
Promise.reject(5);
const handled = Promise.reject(new Error('handled'));
handled.catch((e) => console.log('caught', e.message));
setImmediate(() => { throw { name: 'Custom', message: 'plain object' }; });
setTimeout(() => { reportError(new SyntaxError('reported')); console.log('after reportError'); }, 40);
"""
    r = js(code)
    assert out(r) == "caught handled\nsecond timer still runs\nafter reportError\n"
    assert err(r) == ("Uncaught (in promise) 5\nUncaught Custom: plain object\nUncaught TypeError: in timer\n"
                      "Uncaught (in promise) RangeError: late reject\nUncaught SyntaxError: reported\n")
    assert r.returncode == 0


def test_global_error_handlers_can_suppress_reports(js):
    """CATCHES: missing HTML error-reporting globals: onerror not consulted (or its `true` return
    ignored), onunhandledrejection without preventDefault support, or a throwing handler that
    swallows the original report."""
    code = r"""
let calls = 0;
globalThis.onerror = (msg, src, line, col, error) => {
  calls++;
  console.log('onerror', msg, JSON.stringify([src, line, col]), error instanceof Error);
  return calls === 1;
};
globalThis.onunhandledrejection = (ev) => {
  console.log('onunhandledrejection', ev.type, ev.reason, ev.cancelable, ev.defaultPrevented);
  if (ev.reason === 'suppress') ev.preventDefault();
  console.log('prevented', ev.defaultPrevented);
};
setTimeout(() => { throw new Error('first'); }, 0);
setTimeout(() => { throw new Error('second'); }, 20);
setTimeout(() => { Promise.reject('suppress'); }, 40);
setTimeout(() => { Promise.reject('report me'); }, 60);
setTimeout(() => {
  globalThis.onerror = () => { throw new Error('handler blew up'); };
  reportError(new TypeError('handler threw'));
  try { reportError(); } catch (e) { console.log(e.message); }
}, 80);
"""
    r = js(code)
    assert out(r) == ('onerror Uncaught Error: first ["",0,0] true\n'
                      'onerror Uncaught Error: second ["",0,0] true\n'
                      "onunhandledrejection unhandledrejection suppress true false\nprevented true\n"
                      "onunhandledrejection unhandledrejection report me true false\nprevented false\n"
                      "reportError requires at least 1 argument\n")
    assert err(r) == "Uncaught Error: second\nUncaught (in promise) report me\nUncaught TypeError: handler threw\n"
    assert r.returncode == 0


@pytest.mark.parametrize("body,expected", [
    ("throw 42", "Uncaught 42\n"),
    ("throw { name: 'Shaped', message: 'like an error' }", "Uncaught Shaped: like an error\n"),
    ("throw new Error('')", "Uncaught Error\n"),
    ("throw Object.assign(new Error('m'), { name: 'Renamed' })", "Uncaught Renamed: m\n"),
    ("require('./thrower.js')", "Uncaught RangeError: from a dependency\n"),
])
def test_commonjs_entry_uncaught_throw_rendering(js, workdir, body, expected):
    """CATCHES: a CommonJS entry runner that exits 0 on an uncaught throw, loses output printed
    before it, or renders thrown primitives/error-shaped objects/empty messages differently from
    `Uncaught <name>: <message>`."""
    (workdir / "thrower.js").write_text("throw new RangeError('from a dependency');\n")
    r = js("console.log('ran first');\n" + body + ";\nconsole.log('not reached');\n")
    assert (r.returncode, out(r), err(r)) == (1, "ran first\n", expected)


# -------------------------------------------------------------------------------------- console
def test_console_table_group_count_assert_dir(js, golden):
    """CATCHES: console.table with wrong column union/centering/Values column/property filter,
    group indentation not applied to count/dir output, counters that do not reset, assert that
    prints for truthy values or loses format arguments, and missing timer-label warnings."""
    code = r"""
console.table([{ a: 1, b: 'x' }, { a: 2, c: true }]);
console.table([[1, 2], [3]]);
console.table(['p', 'q']);
console.table({ r1: { v: 1, w: 0 }, r2: { v: 2, w: 3 } }, ['v']);
console.table(5);
console.group('Outer');
console.count();
console.count('lbl');
console.group();
console.count();
console.dir({ deep: { er: { est: 1 } } }, { depth: 0 });
console.groupEnd();
console.countReset();
console.count();
console.groupEnd();
console.groupEnd();
console.count('lbl');
console.assert(true, 'not shown');
console.assert(false, 'shown %s and %d', 'str', 42);
console.assert(0);
console.dir([1, 'two', { three: 3 }]);
console.dir(new Map([['k', 1]]));
console.timeEnd('nolabel');
console.timeLog('nolabel2');
console.time('dup'); console.time('dup');
console.dirxml('x', 1);
console.clear();
"""
    r = js(code)
    assert out(r) == golden("console_methods_out")
    assert err(r) == ("Assertion failed: shown str and 42\nAssertion failed\n"
                      "Warning: No such label 'nolabel' for console.timeEnd()\n"
                      "Warning: No such label 'nolabel2' for console.timeLog()\n"
                      "Warning: Label 'dup' already exists for console.time()\n")
    assert r.returncode == 0


def test_console_class_over_custom_streams(js):
    """CATCHES: a Console constructor that ignores the supplied stdout/stderr streams, does not
    format objects with util.inspect, keeps no per-instance group indentation, or a console module
    that is not the global console object."""
    code = r"""
const { Console } = require('console');
const outChunks = [], errChunks = [];
const c = new Console({ stdout: { write(s) { outChunks.push(s); } }, stderr: { write(s) { errChunks.push(s); } } });
c.log({ nested: { list: [1, 2, 3] }, s: 'str' });
c.log('%s=%d %j', 'n', 7.9, { j: 1 });
c.group('grp'); c.info('inside'); c.count('k'); c.groupEnd(); c.debug('after');
c.error(new Map([[1, 'one']]));
c.warn('w %i', 3.7);
console.log(JSON.stringify(outChunks));
console.log(JSON.stringify(errChunks));
console.log(require('console') === console, typeof console.context().log, console.createTask('t').run((a, b) => a * b, 6, 7));
try { new Console({}); } catch (e) { console.log(e.constructor.name, e.message); }
"""
    r = js(code)
    assert out(r) == (
        '["{ nested: { list: [ 1, 2, 3 ] }, s: \'str\' }\\n","n=7.9 {\\"j\\":1}\\n","grp\\n",'
        '"  inside\\n","  k: 1\\n","after\\n"]\n'
        '["Map(1) { 1 => \'one\' }\\n","w 3\\n"]\n'
        "true function 42\n"
        'TypeError The "stdout" argument must be an instance of a writable stream\n')
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- child_process
def test_child_process_sync_variants(js, workdir):
    """CATCHES: spawnSync/execSync/execFileSync that lose stdout/stderr, ignore input/encoding/
    cwd/shell options, report the wrong status, or do not throw (with status and stderr) for a
    failing command."""
    (workdir / "sub").mkdir()
    (workdir / "sub" / "inner.txt").write_text("x")
    code = r"""
const cp = require('child_process');
const r = cp.spawnSync('sh', ['-c', 'echo out; echo err >&2; exit 3']);
console.log(r.status, r.signal, JSON.stringify(r.stdout.toString()), JSON.stringify(r.stderr.toString()), Buffer.isBuffer(r.stdout));
const r2 = cp.spawnSync('cat', { input: 'piped in', encoding: 'utf8' });
console.log(r2.status, r2.stdout, r2.output.length, r2.output[0]);
const r3 = cp.spawnSync('echo', ['a', '"b c"'], { shell: true, encoding: 'utf8' });
console.log(JSON.stringify(r3.stdout));
console.log(JSON.stringify(cp.execSync('echo hello; printf x', { encoding: 'utf8' })));
console.log(cp.execSync('cat', { input: Buffer.from('buffer input') }).toString());
console.log(cp.execSync('ls', { cwd: 'sub', encoding: 'utf8' }).trim());
try { cp.execSync('echo partial; echo bad >&2; exit 4'); } catch (e) { console.log(e.message, e.status, JSON.stringify(e.stderr.toString())); }
console.log(cp.execFileSync('sh', ['-c', 'echo $0 $1', 'a', 'b']).toString().trim());
console.log(cp.execFileSync('sh', ['-c', 'cat'], { input: 'via execFile', encoding: 'utf8' }));
try { cp.execFileSync('sh', ['-c', 'echo o; exit 2']); } catch (e) { console.log(e.message, e.status, e.stdout.toString().trim()); }
try { cp.execSync('true', { cwd: 'no_such_dir' }); } catch (e) { console.log(e.message.split(':')[0]); }
"""
    r = js(code)
    assert out(r) == ('3 null "out\\n" "err\\n" true\n0 piped in 3 null\n"a b c\\n"\n"hello\\nx"\n'
                      "buffer input\ninner.txt\nCommand failed: echo partial; echo bad >&2; exit 4 4 \"bad\\n\"\n"
                      "a b\nvia execFile\nCommand failed: sh 2 o\nspawn /bin/sh\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_child_process_async_spawn_exec_execfile(js, golden):
    """CATCHES: an async spawn whose stdin writes never reach the child, whose stdout/stderr
    streams lose data or never end, whose spawn/exit/close events are missing or out of order, or
    exec/execFile callbacks that report the wrong error, exit code or output."""
    # Children that print block on a final `read` until the parent has seen their output, so
    # 'close' (emitted on exit) can never overtake the last stdout/stderr chunk.
    code = r"""
const cp = require('child_process');
const log = [];
const gateOn = (child, streams) => {
  let pending = streams.length;
  for (const s of streams) s.once('data', () => { if (--pending === 0) child.stdin.end(); });
};
const ch = cp.spawn('sh', ['-c', 'read x; read y; echo "got:$x,$y"; echo e1 >&2; read z; exit 5']);
let o = '', e = '', ended = 0;
ch.stdout.setEncoding('utf8');
ch.stdout.on('data', (c) => (o += c));
ch.stderr.on('data', (c) => (e += c));
gateOn(ch, [ch.stdout, ch.stderr]);
const finish = () => {
  if (++ended < 3) return;
  log.push(`close+end ${JSON.stringify(o)} ${JSON.stringify(e)} write callback ran: ${wrote}`);
  const c1 = cp.exec('read x; echo "via exec $x"; echo E >&2; read y || :', (err, so, se) => {
    log.push(`exec ${err} ${JSON.stringify(so)} ${JSON.stringify(se)}`);
    cp.exec('exit 9', { encoding: 'buffer' }, (err2, so2) => {
      log.push(`exec fail ${err2.message} ${err2.code} ${Buffer.isBuffer(so2)} ${so2.length}`);
      const c3 = cp.execFile('sh', ['-c', 'read x; echo "file $1 $x"; read y || exit 0', '_', 'arg'], (err3, so3, se3) => {
        log.push(`execFile ${err3} ${JSON.stringify(so3)} ${JSON.stringify(se3)}`);
        console.log(log.join('\n'));
      });
      gateOn(c3, [c3.stdout]);
      c3.stdin.write('stdin3\n');
    });
  });
  gateOn(c1, [c1.stdout, c1.stderr]);
  c1.stdin.write('in1\n');
};
ch.stdout.on('end', finish);
ch.stderr.on('end', finish);
ch.on('spawn', () => log.push('spawn ' + (typeof ch.pid) + ' ' + ch.stdio.length));
ch.on('exit', (code, sig) => log.push(`exit ${code} ${sig} exitCode=${ch.exitCode}`));
ch.on('close', (code) => { log.push('close ' + code); finish(); });
ch.stdin.write('line1\n');
let wrote = false;
ch.stdin.write(Buffer.from('line2\n'), () => { wrote = true; });
"""
    r = js(code)
    assert out(r) == golden("child_async")
    assert (r.returncode, r.stderr) == (0, b"")


def test_child_process_kill_stdio_and_env_options(js):
    """CATCHES: kill() that does not terminate the child (exit code should be null), stdio
    'ignore'/'inherit' not honoured, an env option that is merged instead of replacing the
    environment, or a spawn of a missing program that does not throw."""
    if shutil.which("sleep") is None:
        pytest.skip("sleep(1) not available")
    code = r"""
const cp = require('child_process');
const steps = [];
const sleeper = cp.spawn('sleep', ['5']);
sleeper.on('exit', (code, sig) => {
  steps.push(`killed exit ${code} ${sig} killed=${sleeper.killed}`);
  const quiet = cp.spawn('sh', ['-c', 'echo hidden; echo hidden >&2'], { stdio: 'ignore' });
  steps.push(`ignore streams ${quiet.stdout} ${quiet.stderr} ${quiet.stdin}`);
  quiet.on('close', (c) => {
    steps.push('ignore close ' + c);
    const env = cp.spawn('/bin/sh', ['-c', 'echo "[$ONLY_VAR][$N][$HOME]"'], { env: { ONLY_VAR: 'yes', N: 5 } });
    let eo = '', done = 0;
    const both = () => {
      if (++done < 2) return;
      steps.push('env ' + eo.trim());
      console.log(steps.join('\n'));
      const inh = cp.spawn('sh', ['-c', 'echo inherited stdout; exit 0'], { stdio: 'inherit' });
      inh.on('close', (c2) => console.log('inherit close', c2, inh.stdout));
    };
    env.stdout.on('data', (d) => (eo += d));
    env.stdout.on('end', both);
    env.on('close', both);
  });
});
console.log('kill returned', sleeper.kill());
try { cp.spawn('definitely-not-a-program-xyz'); } catch (e) { console.log(e.message.split(':')[0]); }
"""
    r = js(code)
    assert out(r) == ("kill returned true\nspawn definitely-not-a-program-xyz\n"
                      "killed exit null null killed=true\nignore streams null null null\nignore close 0\n"
                      "env [yes][5][]\ninherited stdout\ninherit close 0 null\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_fork_exchanges_ipc_messages(js, workdir):
    """CATCHES: fork() without a working IPC channel (messages lost or not JSON round-tripped),
    IPC frames leaking into the child's ordinary stdout, a child that cannot see process.send,
    or a disconnect that is not observed by both sides."""
    (workdir / "child.js").write_text(r"""
console.log('ordinary child output', typeof process.send, process.connected, process.argv.slice(2).join());
process.on('message', (m) => {
  process.send({ value: m.value + 1, echo: m.list.concat('child') });
});
process.on('disconnect', () => console.log('child saw disconnect', process.connected));
""")
    code = r"""
const { fork } = require('child_process');
const path = require('path');
const child = fork(path.join(__dirname, 'child.js'), ['arg1', 2], { silent: true });
let stdout = '', pending = 2;
const got = [];
child.stdout.on('data', (c) => { stdout += c; });
child.on('spawn', () => child.send({ value: 41, list: ['parent'] }));
child.on('message', (m) => {
  got.push(JSON.stringify(m));
  if (got.length === 1) child.send({ value: 99, list: [] });
  else child.disconnect();
});
child.on('disconnect', () => got.push('parent disconnect ' + child.connected));
const report = () => { if (--pending === 0) console.log(got.join('\n') + '\n' + JSON.stringify(stdout) + '\nconnected ' + child.connected); };
child.stdout.on('end', report);
child.on('close', (code) => { got.push('close ' + code); report(); });
"""
    r = js(code)
    assert out(r) == ('{"value":42,"echo":["parent","child"]}\n{"value":100,"echo":["child"]}\n'
                      "parent disconnect false\nclose 0\n"
                      '"ordinary child output function true arg1,2\\nchild saw disconnect false\\n"\n'
                      "connected false\n")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------ worker_threads
def test_worker_file_round_trip_workerdata_and_exit_code(js, workdir):
    """CATCHES: workers that do not receive workerData, run their CommonJS entry without
    require.main/__filename, lose or reorder messages, report the parent's thread state inside
    the worker, or ignore process.exit(code) in the worker (exit code should be 7)."""
    (workdir / "w.js").write_text(r"""
const { parentPort, workerData, isMainThread, threadId } = require('worker_threads');
const path = require('path');
parentPort.postMessage({ type: 'ready', isMainThread, data: workerData, tid: threadId > 0,
  main: require.main === module, file: path.basename(__filename), argv: process.argv.slice(2) });
parentPort.on('message', (m) => {
  if (m.cmd === 'mul') parentPort.postMessage({ type: 'result', v: m.v * workerData.n, map: new Map([[m.v, 'k']]) });
  else process.exit(7);
});
""")
    code = r"""
const { Worker, isMainThread, threadId, workerData, parentPort } = require('worker_threads');
const path = require('path');
const log = [`main ${isMainThread} ${threadId} ${workerData} ${parentPort}`];
const w = new Worker(path.join(__dirname, 'w.js'), { workerData: { n: 21, list: [1, 2] }, argv: ['x', 3] });
log.push('threadId positive ' + (w.threadId > 0));
w.on('online', () => log.push('online'));
w.on('message', (m) => {
  log.push('got ' + JSON.stringify(m, (k, v) => (v instanceof Map ? [...v] : v)));
  if (m.type === 'ready') w.postMessage({ cmd: 'mul', v: 2 });
  else w.postMessage({ cmd: 'quit' });
});
w.on('error', (e) => log.push('error ' + e.message));
w.on('exit', (code) => { log.push('exit ' + code); console.log(log.join('\n')); });
"""
    r = js(code)
    assert out(r) == ("main true 0 undefined null\nthreadId positive true\nonline\n"
                      'got {"type":"ready","isMainThread":false,"data":{"n":21,"list":[1,2]},"tid":true,'
                      '"main":true,"file":"w.js","argv":["x","3"]}\n'
                      'got {"type":"result","v":42,"map":[[2,"k"]]}\nexit 7\n')
    assert (r.returncode, r.stderr) == (0, b"")


def test_worker_eval_errors_terminate_and_natural_exit(js, golden):
    """CATCHES: eval workers that cannot require builtins or see env/environmentData, uncaught
    worker errors and rejections that are not revived as the right Error class on the parent, a
    wrong exit code (1 after an error or terminate, 0 for a worker that simply finishes), or
    terminate() promises that never resolve. Workers run concurrently; each one's events are
    logged separately and printed in a fixed order."""
    code = r"""
const { Worker, setEnvironmentData } = require('worker_threads');
setEnvironmentData('shared', 'env-data');
const run = (label, src, opts, first, onMsg) => new Promise((resolve) => {
  const log = [label];
  const w = new Worker(src, { eval: true, ...opts });
  w.on('message', (m) => { log.push('message ' + JSON.stringify(m)); if (onMsg) onMsg(w, m, log); });
  w.on('error', (e) => log.push(`error ${e.constructor.name} ${e.message}`));
  w.on('exit', (c) => { log.push('exit ' + c); setTimeout(() => resolve(log), 0); });
  if (first !== undefined) w.postMessage(first);
});
const terminated = (async () => {
  const log = ['terminate idle worker'];
  const w = new Worker(`require('worker_threads').parentPort.on('message', () => {})`, { eval: true });
  log.push('terminate result ' + await w.terminate());
  log.push('terminate again ' + await w.terminate());
  return log;
})();
Promise.all([
  run('throws after posting', `const { parentPort, workerData, getEnvironmentData } = require('worker_threads');
    parentPort.postMessage([workerData * 2, getEnvironmentData('shared'), process.env.ONLY]);
    throw new TypeError('boom in worker');`, { workerData: 4, env: { ONLY: 'set' } }),
  run('rejects', `Promise.reject(new RangeError('rejected in worker'))`, {}),
  run('finishes', `require('worker_threads').parentPort.postMessage('finishing naturally')`, {}),
  run('syntax error', `let y = ;`, {}),
  run('terminated after echo', `const { parentPort } = require('worker_threads');
    parentPort.on('message', (m) => parentPort.postMessage('echo ' + m));`, {}, 'hello',
    (w, m, log) => { w.terminate().then((code) => log.push('terminate resolved ' + code)); }),
  terminated,
]).then((logs) => {
  for (const log of logs) console.log(log.join('\n  '));
  try { new Worker('relative.js'); } catch (e) { console.log(e.constructor.name + ': ' + e.message); }
  try { new Worker('x', { eval: true, stdout: true }); } catch (e) { console.log(e.message); }
});
"""
    r = js(code)
    assert out(r) == golden("worker_eval")
    assert (r.returncode, r.stderr) == (0, b"")


def test_worker_message_ping_pong_from_eval(js):
    """CATCHES: a worker that does not see messages posted right after construction or that drops
    messages under a burst: 50 sequential round trips must all arrive in order."""
    code = r"""
const { Worker } = require('worker_threads');
const w = new Worker(`const { parentPort } = require('worker_threads');
  parentPort.on('message', (n) => { if (n === 'stop') parentPort.close(); else parentPort.postMessage(n * n); });`, { eval: true });
const got = [];
w.on('message', (sq) => {
  got.push(sq);
  if (got.length < 50) w.postMessage(got.length);
  else w.postMessage('stop');
});
w.on('exit', (c) => console.log(got.length, got.slice(0, 6).join(','), got[49], 'exit', c));
w.postMessage(0);
"""
    r = js(code)
    assert out(r) == "50 0,1,4,9,16,25 2401 exit 0\n"
    assert (r.returncode, r.stderr) == (0, b"")


def test_module_worker_with_imports_and_top_level_await(js, workdir):
    """CATCHES: a .mjs worker entry that is not evaluated as a module (imports or top-level await
    fail), or a web-style Worker global whose postMessage/onmessage/onerror bridge is broken."""
    (workdir / "dep.mjs").write_text("export const base = 21;\n")
    (workdir / "nw.mjs").write_text(r"""
import { parentPort, workerData } from 'node:worker_threads';
import { base } from './dep.mjs';
const v = await Promise.resolve(base * workerData);
parentPort.postMessage({ v, meta: typeof import.meta.url });
""")
    (workdir / "web.js").write_text(r"""
postMessage({ step: 1, selfType: typeof self, parentPortIsNull: require('worker_threads').parentPort === null });
onmessage = (ev) => {
  if (ev.data === 'boom') throw new RangeError('web worker exploded');
  postMessage({ step: 2, sum: ev.data.list.reduce((a, b) => a + b), mapv: ev.data.map.get('k') });
};
""")
    code = r"""
const { Worker: NodeWorker } = require('worker_threads');
const path = require('path');
const log = [];
const nw = new NodeWorker(path.join(__dirname, 'nw.mjs'), { workerData: 2 });
nw.on('message', (m) => log.push('node module worker ' + JSON.stringify(m)));
nw.on('exit', (c) => {
  log.push('node module worker exit ' + c);
  const w = new Worker('./web.js');
  w.onmessage = (ev) => {
    log.push(`web ${ev.constructor.name} ${JSON.stringify(ev.data)}`);
    if (ev.data.step === 1) w.postMessage({ list: [1, 2, 3], map: new Map([['k', 'v']]) });
    else w.postMessage('boom');
  };
  w.onerror = (ev) => { log.push('web onerror ' + ev.message); w.terminate(); console.log(log.join('\n')); };
});
"""
    r = js(code)
    assert out(r) == ('node module worker {"v":42,"meta":"string"}\nnode module worker exit 0\n'
                      'web MessageEvent {"step":1,"selfType":"object","parentPortIsNull":true}\n'
                      'web MessageEvent {"step":2,"sum":6,"mapv":"v"}\n'
                      "web onerror Uncaught RangeError: web worker exploded\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_message_channel_ports_queue_until_received(js):
    """CATCHES: MessageChannel ports that do not structured-clone payloads at post time, lose or
    reorder queued messages, or a receiveMessageOnPort that does not pop the queue in order or
    accepts non-ports."""
    code = r"""
const { MessageChannel, receiveMessageOnPort } = require('worker_threads');
const { port1, port2 } = new MessageChannel();
const payload = { nested: { n: 1 }, when: [1, 2] };
port1.postMessage(payload);
port1.postMessage('second');
payload.nested.n = 99;
setTimeout(() => {
  const first = receiveMessageOnPort(port2);
  console.log(JSON.stringify(first), first.message === payload);
  console.log(JSON.stringify(receiveMessageOnPort(port2)), receiveMessageOnPort(port2));
  const ch = new MessageChannel();
  ch.port2.onmessage = (ev) => { console.log('async delivery', JSON.stringify(ev.data)); ch.port1.close(); ch.port2.close(); };
  ch.port1.postMessage({ late: true });
  console.log('posted');
  try { receiveMessageOnPort({}); } catch (e) { console.log(e.message); }
}, 10);
"""
    r = js(code)
    assert out(r) == ('{"message":{"nested":{"n":1},"when":[1,2]}} false\n{"message":"second"} undefined\n'
                      "posted\nreceiveMessageOnPort expects a MessagePort\n"
                      'async delivery {"late":true}\n')
    assert (r.returncode, r.stderr) == (0, b"")


def test_web_worker_load_errors_close_and_timers(js, workdir):
    """CATCHES: a web Worker whose missing script or top-level throw is not reported through
    onerror/'error' listeners, that dies after a top-level throw (web workers keep running), whose
    timers do not fire inside the worker, or whose self close() never ends it."""
    (workdir / "badsyntax.js").write_text("postMessage('never posted');\nlet x = ;\n")
    (workdir / "thrower.js").write_text(r"""
onmessage = (ev) => {
  if (ev.data === 'ping') setTimeout(() => postMessage('pong after timer'), 5);
  else { postMessage('closing'); close(); }
};
throw new Error('thrown at top level');
""")
    code = r"""
const log = [];
try { new Worker(); } catch (e) { log.push(e.constructor.name + ': ' + e.message); }
const w = new Worker('./missing-worker.js');
w.onerror = (ev) => {
  log.push('missing: ' + ev.message);
  w.terminate();
  const ws = new Worker('./badsyntax.js');
  ws.onmessage = (m) => log.push('unexpected message ' + m.data);
  ws.onerror = (sev) => { log.push('syntax: ' + sev.message); ws.terminate(); startThrower(); };
};
const startThrower = () => {
  const w2 = new Worker('./thrower.js');
  w2.addEventListener('error', (ev2) => log.push('top-level throw: ' + ev2.message));
  w2.onmessage = (ev3) => {
    log.push('still alive: ' + ev3.data);
    if (ev3.data === 'closing') console.log(log.join('\n'));
    else w2.postMessage('close please');
  };
  w2.postMessage('ping');
};
"""
    r = js(code)
    assert out(r) == ("TypeError: Worker requires a scriptURL\n"
                      "missing: cannot load worker script ./missing-worker.js: No such file or directory (os error 2)\n"
                      'syntax: SyntaxError: unexpected token Punct(";") (line 2)\n'
                      "top-level throw: Error: thrown at top level\nstill alive: pong after timer\nstill alive: closing\n")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unref_workers_and_children_do_not_keep_the_loop_alive(js, workdir):
    """CATCHES: worker.unref()/parentPort.unref()/child.unref() that still hold the event loop
    open (the program would hang until the 20 s timeout), ref() that does not re-arm keep-alive,
    or a spawn cwd option that is ignored."""
    (workdir / "sub").mkdir()
    (workdir / "sub" / "file-in-sub").write_text("")
    code = r"""
const { Worker } = require('worker_threads');
const cp = require('child_process');
const idle = new Worker(`require('worker_threads').parentPort.on('message', () => {});`, { eval: true });
idle.unref(); idle.ref(); idle.unref();
const w2 = new Worker(`const { parentPort } = require('worker_threads');
  parentPort.on('message', () => {}); parentPort.unref();
  setTimeout(() => parentPort.postMessage('timer in worker'), 5);`, { eval: true });
w2.on('message', (m) => console.log(m));
w2.on('exit', (c) => console.log('w2 exit', c));
const lingering = cp.spawn('sh', ['-c', 'read x; echo never'], { cwd: 'sub' });
lingering.unref(); lingering.ref(); lingering.unref();
const kept = cp.spawn('sh', ['-c', 'ls; read y || :'], { cwd: 'sub' });
kept.unref(); kept.ref();
let o = '';
kept.stdout.on('data', (d) => { o += d; kept.stdin.end(); });
kept.on('close', (code) => console.log('ref child closed', code, JSON.stringify(o)));
console.log('main sync done');
"""
    r = js(code)
    lines = out(r).splitlines()
    assert lines[0] == "main sync done"
    assert sorted(lines[1:]) == ['ref child closed 0 "file-in-sub\\n"', "timer in worker", "w2 exit 0"]
    assert lines.index("timer in worker") < lines.index("w2 exit 0")
    assert (r.returncode, r.stderr) == (0, b"")
