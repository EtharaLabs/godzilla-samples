"""Environment variables (LUMEN_TIER, HOME, arbitrary variables) and the process/os surface the CLI sets up."""

import pytest

from conftest import write_files

WORKLOAD = ("function fib(n) { return n < 2 ? n : fib(n - 1) + fib(n - 2) }\n"
            "const a = []; for (let i = 0; i < 20; i++) a.push(fib(i) % 7);\n"
            "let o = { s: 0 }; for (const v of a) o.s += v * 3;\n"
            "console.log(a.join(','), o.s, [3, 1, 2].sort((x, y) => y - x).join(''));\n")
WORKLOAD_OUT = b"0,1,1,2,3,5,1,6,0,6,6,5,4,2,6,1,0,1,1,2 159 321\n"


def _res(r):
    return r.returncode, r.stdout, r.stderr


@pytest.mark.parametrize("tier", ["interp", "bytecode", "jit", "anything-else", ""])
def test_lumen_tier_env(run, tier):
    """CATCHES: LUMEN_TIER values that change program results or that are rejected (unknown values fall back silently)."""
    r = run(["-e", WORKLOAD], env_overrides={"LUMEN_TIER": tier})
    assert _res(r) == (0, WORKLOAD_OUT, b"")


def test_lumen_tier_env_with_flag(run):
    """CATCHES: implementations where LUMEN_TIER and --tier conflict (the flag overrides; results stay identical)."""
    r = run(["--tier=bytecode", "-e", WORKLOAD], env_overrides={"LUMEN_TIER": "interp"})
    assert _res(r) == (0, WORKLOAD_OUT, b"")


def test_lumen_tier_env_does_not_validate_flag(run):
    """CATCHES: implementations that let a valid LUMEN_TIER excuse an invalid --tier flag."""
    r = run(["--tier=jit", "-e", WORKLOAD], env_overrides={"LUMEN_TIER": "interp"})
    assert _res(r) == (2, b"", b"unknown tier 'jit' (interp|bytecode)\n")


@pytest.mark.parametrize("tier", ["interp", "bytecode"])
def test_lumen_tier_env_file_entry(run, workdir, tier):
    """CATCHES: LUMEN_TIER only being honoured for -e and not for script files."""
    write_files(workdir, {"w.js": WORKLOAD})
    assert _res(run(["w.js"], env_overrides={"LUMEN_TIER": tier})) == (0, WORKLOAD_OUT, b"")


def test_env_variable_passthrough(run):
    """CATCHES: process.env not reflecting the caller's environment."""
    r = run(["-e", "console.log(process.env.MY_SETTING, process.env.EMPTY_ONE === '', process.env.UNSET_ONE)"],
            env_overrides={"MY_SETTING": "value with spaces=and=equals", "EMPTY_ONE": ""})
    assert _res(r) == (0, b"value with spaces=and=equals true undefined\n", b"")


def test_env_is_writable_snapshot(run):
    """CATCHES: a read-only or shared process.env (writes must be visible to the script and enumerable)."""
    r = run(["-e", "process.env.NEWVAR = 'x'; delete process.env.DROP_ME;"
                   "console.log(process.env.NEWVAR, 'DROP_ME' in process.env, Object.keys(process.env).includes('NEWVAR'))"],
            env_overrides={"DROP_ME": "1"})
    assert _res(r) == (0, b"x false true\n", b"")


def test_env_lists_exact_environment(run):
    """CATCHES: process.env that adds, drops, renames or reorders-by-value the caller's variables (checked on a controlled prefix)."""
    r = run(["-e", "console.log(JSON.stringify(Object.keys(process.env).filter(k => k.startsWith('LUMEN_T_')).sort()"
                   ".map(k => [k, process.env[k]])))"],
            env_overrides={"LUMEN_T_B": "2", "LUMEN_T_A": "1", "LUMEN_T_C": "x y"})
    assert _res(r) == (0, b'[["LUMEN_T_A","1"],["LUMEN_T_B","2"],["LUMEN_T_C","x y"]]\n', b"")


def test_home_env_drives_homedir(run):
    """CATCHES: os.homedir() that ignores $HOME (e.g. reads the password database instead)."""
    r = run(["-e", "console.log(require('os').homedir(), process.env.HOME)"], env_overrides={"HOME": "/custom/home"})
    assert _res(r) == (0, b"/custom/home /custom/home\n", b"")


def test_process_identity_fields(run):
    """CATCHES: wrong platform name, a non-Node version string, or wrong versions object (ecosystem feature detection relies on them)."""
    r = run(["-e", "console.log(process.platform, process.version, JSON.stringify(process.versions), typeof process.pid,"
                   " typeof process.ppid, process.argv0 === process.execPath, process.execPath === process.argv[0])"])
    assert _res(r) == (0, b'linux v20.11.0 {"node":"20.11.0","lumen":"0.1.1","v8":"0.0.0"} number number true true\n', b"")


def test_process_stdio_stream_shape(run):
    """CATCHES: process.stdout/stderr that claim to be TTYs, use other fds, or report a size other than the fixed 80x24."""
    r = run(["-e", "const o = process.stdout, e = process.stderr;"
                   "console.log(o.isTTY, o.fd, e.fd, o.columns, o.rows, o.write('') === true, o.on('x', () => {}) === o)"],
            env_overrides={"COLUMNS": "132", "LINES": "50"})
    assert _res(r) == (0, b"false 1 2 80 24 true true\n", b"")


def test_process_stdout_write_raw(run):
    """CATCHES: process.stdout.write adding newlines, or stderr writes going to stdout; typed arrays must be written as bytes."""
    r = run(["-e", "process.stdout.write('no newline'); process.stdout.write(new Uint8Array([33, 10]));"
                   "process.stderr.write('E1'); process.stdout.end('tail'); process.stderr.write(42)"])
    assert _res(r) == (0, b"no newline!\ntail", b"E142")


def test_console_methods_streams(run):
    """CATCHES: console.info/debug not going to stdout or console.warn/error not going to stderr."""
    r = run(["-e", "console.log('log'); console.info('info'); console.debug('debug'); console.warn('warn'); console.error('error')"])
    assert _res(r) == (0, b"log\ninfo\ndebug\n", b"warn\nerror\n")


def test_console_log_rendering(run):
    """CATCHES: console.log rendering that uses inspect-style output instead of space-joined ToString (strings bare, symbols by description)."""
    r = run(["-e", "console.log({a: 1}, [1, [2, 3]], null, undefined, Symbol('x'), Symbol(), 1n, 'str', -0, 1e21, () => 1, true);"
                   "console.log(); console.log('');"
                   "console.log({ toString() { throw new Error('no') } }, Object.create(null))"])
    assert _res(r) == (0, b"[object Object] 1,2,3 null undefined Symbol(x) Symbol() 1 str 0 1e+21 () => 1 true\n\n\n[object] [object]\n", b"")


def test_event_loop_phase_order(run):
    """CATCHES: a different ordering of microtasks, queueMicrotask, process.nextTick, setImmediate and setTimeout(0)."""
    r = run(["-e", "process.nextTick(() => console.log('tick')); Promise.resolve().then(() => console.log('micro'));"
                   "setTimeout(() => console.log('timeout')); setImmediate(() => console.log('immediate'));"
                   "queueMicrotask(() => console.log('qm')); console.log('sync')"])
    assert _res(r) == (0, b"sync\nmicro\nqm\ntick\nimmediate\ntimeout\n", b"")


def test_timer_ordering_by_delay(run):
    """CATCHES: timers fired in registration order instead of deadline order, clearTimeout not cancelling, or extra arguments not forwarded."""
    code = ("setTimeout(() => console.log('t30'), 30); setTimeout(() => console.log('t10'), 10);"
            "const c = setTimeout(() => console.log('cancelled'), 5); clearTimeout(c);"
            "setTimeout((a, b) => console.log('args', a, b), 40, 'x', 'y'); setTimeout(() => console.log('t0'));"
            "console.log(typeof c, c > 0);")
    r = run(["-e", code])
    assert _res(r) == (0, b"number true\nt0\nt10\nt30\nargs x y\n", b"")


def test_interval_cleared_in_callback(run):
    """CATCHES: setInterval that never fires, fires before its period, or keeps the loop alive after clearInterval."""
    code = ("let n = 0; const iv = setInterval((tag) => { console.log('iv', ++n, tag); clearInterval(iv) }, 150, 'T');"
            "setTimeout(() => console.log('before interval'), 20);")
    r = run(["-e", code])
    assert _res(r) == (0, b"before interval\niv 1 T\n", b"")


def test_timer_argument_validation(run):
    """CATCHES: timer functions accepting non-callables instead of throwing TypeError with the documented messages."""
    r = run(["-e", "for (const f of [setTimeout, setInterval, setImmediate]) {"
                   " try { f('code string', 1) } catch (e) { console.log(e.name + ': ' + e.message) } }"
                   "clearTimeout('nonsense'); clearInterval(undefined); clearTimeout(-1); console.log('clears ignore junk')"])
    assert _res(r) == (0, b"TypeError: setTimeout expects a function\nTypeError: setInterval expects a function\n"
                          b"TypeError: setImmediate expects a function\nclears ignore junk\n", b"")


def test_next_tick_and_microtask_argument_errors(run):
    """CATCHES: process.nextTick/queueMicrotask accepting non-functions instead of throwing the documented TypeErrors."""
    r = run(["-e", "for (const f of [() => process.nextTick(5), () => queueMicrotask('x')]) {"
                   " try { f() } catch (e) { console.log(e.name + ': ' + e.message) } }"])
    assert _res(r) == (0, b"TypeError: process.nextTick expects a function\nTypeError: queueMicrotask expects a function\n", b"")


def test_process_exit_code_property_is_ignored(run):
    """CATCHES: implementations that honour process.exitCode (this runtime always exits 0 unless process.exit is called or the entry throws)."""
    r = run(["-e", "process.exitCode = 4; console.log('set')"])
    assert _res(r) == (0, b"set\n", b"")


def test_process_cwd_and_chdir(run, workdir):
    """CATCHES: process.cwd() not reporting the launch directory, or chdir not affecting later relative file access."""
    write_files(workdir, {"sub/data.txt": "inside sub"})
    r = run(["-e", "const fs = require('fs'); const before = process.cwd(); process.chdir('sub');"
                   "console.log(require('path').relative(before, process.cwd()), fs.readFileSync('data.txt', 'utf8'))"])
    assert _res(r) == (0, b"sub inside sub\n", b"")
    r2 = run(["-e", "console.log(process.cwd())"])
    assert (r2.returncode, r2.stdout, r2.stderr) == (0, str(workdir.resolve()).encode() + b"\n", b"")


def test_process_chdir_missing_directory(run):
    """CATCHES: chdir into a missing directory not throwing the ENOENT-style Error message."""
    r = run(["-e", "try { process.chdir('no/such/dir') } catch (e) { console.log(e.name, e.message) }"])
    assert _res(r) == (0, b"Error ENOENT: chdir 'no/such/dir': No such file or directory (os error 2)\n", b"")


def test_process_argv_for_script(run, workdir):
    """CATCHES: script arguments not forwarded verbatim (spaces, empty strings, unicode) to process.argv."""
    write_files(workdir, {"a.js": "console.log(JSON.stringify(process.argv.slice(1).map((s, i) => i === 0 ? require('path').basename(s) : s)))\n"})
    r = run(["a.js", "one two", "", "ü", "key=value"])
    assert _res(r) == (0, '["a.js","one two","","ü","key=value"]\n'.encode(), b"")


def test_os_module_basics(run):
    """CATCHES: node:os returning wrong EOL, platform, type or endianness strings on Linux."""
    r = run(["-e", "const os = require('node:os'); console.log(JSON.stringify(os.EOL), os.platform(), os.type(), os.endianness(),"
                   " Array.isArray(os.cpus()), typeof os.totalmem(), os.homedir())"], env_overrides={"HOME": "/h"})
    assert _res(r) == (0, b'"\\n" linux Linux LE true number /h\n', b"")


def test_process_hrtime_shapes(run):
    """CATCHES: hrtime/uptime/performance.now that return the wrong types or non-monotonic values."""
    r = run(["-e", "const a = process.hrtime(); const d = process.hrtime(a); const b = process.hrtime.bigint();"
                   "console.log(Array.isArray(a), a.length, d[0] >= 0, d[1] >= 0, typeof b, process.uptime() >= 0, performance.now() >= 0)"])
    assert _res(r) == (0, b"true 2 true true bigint true true\n", b"")
