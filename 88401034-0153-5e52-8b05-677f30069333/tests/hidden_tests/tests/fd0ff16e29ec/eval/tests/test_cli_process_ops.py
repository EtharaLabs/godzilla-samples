"""process.* operations backed by OS calls: kill, umask, execve, identity calls, resource counters, warnings."""

import re
import signal


def _res(r):
    return r.returncode, r.stdout, r.stderr


def test_kill_signal_zero_and_missing_pid(run):
    """CATCHES: process.kill that does not return true for signal 0 on itself, or reports a missing pid with a different Error."""
    r = run(["-e", "console.log(process.kill(process.pid, 0));"
                   "try { process.kill(2147483646, 'SIGTERM') } catch (e) { console.log(e.name + ': ' + e.message) }"])
    assert _res(r) == (0, b"true\nError: kill 2147483646 failed (errno set)\n", b"")


def test_kill_self_default_sigterm(run):
    """CATCHES: process.kill(pid) that does not default to SIGTERM, or that lets pending timers run after the signal."""
    r = run(["-e", "console.log('before'); process.kill(process.pid); setTimeout(() => console.log('after'), 100)"])
    assert _res(r) == (-signal.SIGTERM, b"before\n", b"")


def test_kill_self_numeric_signal(run):
    """CATCHES: numeric signals not delivered as-is (9 must be SIGKILL)."""
    r = run(["-e", "console.log('dying'); process.kill(process.pid, 9); console.log('unreachable')"])
    assert _res(r) == (-signal.SIGKILL, b"dying\n", b"")


def test_kill_named_signal_table(run):
    """CATCHES: wrong name-to-number mapping for named signals (SIGHUP is 1) or unknown names not falling back to SIGTERM."""
    hup = run(["-e", "process.kill(process.pid, 'SIGHUP'); console.log('survived')"])
    assert _res(hup) == (-signal.SIGHUP, b"", b"")
    bogus = run(["-e", "process.kill(process.pid, 'SIGBOGUS'); console.log('survived')"])
    assert _res(bogus) == (-signal.SIGTERM, b"", b"")


def test_umask_set_and_read(run):
    """CATCHES: umask that does not return the previous mask, mis-parses octal strings, or whose no-argument form changes the mask."""
    r = run(["-e", "process.umask(0o27); const prev = process.umask(0o77); const now = process.umask(); const again = process.umask();"
                   "console.log(prev.toString(8), now.toString(8), again.toString(8), process.umask(0o1777 | 0o70000).toString(8), process.umask().toString(8))"])
    assert _res(r) == (0, b"27 77 77 77 777\n", b"")


def test_umask_affects_created_files(run, workdir):
    """CATCHES: a umask that is only bookkeeping and not applied by the OS to files the script creates."""
    r = run(["-e", "process.umask(0o077); require('fs').writeFileSync('secret.txt', 'top');"
                   "console.log((require('fs').statSync('secret.txt').mode & 0o777).toString(8))"])
    assert _res(r) == (0, b"600\n", b"")
    assert (workdir / "secret.txt").read_bytes() == b"top"


def test_execve_replaces_process(run):
    """CATCHES: process.execve that spawns a child instead of replacing the image, or does not stringify arguments / pass the environment."""
    r = run(["-e", "process.execve('/bin/sh', ['sh', '-c', 'echo \"$GREETING\" \"$0\" \"$1\"', 'zero', 1], { GREETING: 'replaced', SKIP: undefined });"
                   "console.log('not reached')"])
    assert _res(r) == (0, b"replaced zero 1\n", b"")


def test_execve_argument_validation(run):
    """CATCHES: execve argument validation with different TypeError messages, or OS failures not surfacing as Error."""
    code = ("for (const args of [[1, [], {}], ['/bin/echo', 'x', {}], ['/bin/echo', [], null], ['/bin/echo', [], []],"
            " ['/bin/echo', ['a\\0b'], {}], ['/bin/echo', [], { K: 'v\\0' }], ['/nonexistent/bin', [], {}]]) {"
            " try { process.execve(...args) } catch (e) { console.log(e.name + ': ' + e.message) } }")
    r = run(["-e", code])
    assert _res(r) == (0, b'TypeError: The "file" argument must be of type string\n'
                          b'TypeError: The "args" argument must be an Array\n'
                          b'TypeError: The "env" argument must be an object\n'
                          b'TypeError: The "env" argument must be an object\n'
                          b"TypeError: execve arguments may not contain null bytes\n"
                          b"TypeError: execve arguments may not contain null bytes\n"
                          b"Error: execve failed: No such file or directory (os error 2)\n", b"")


def test_identity_calls_to_own_ids(run):
    """CATCHES: missing POSIX identity functions, or set*id calls to the caller's own ids failing / returning values."""
    r = run(["-e", "const ids = [process.getuid(), process.geteuid(), process.getgid(), process.getegid()];"
                   "console.log(ids.every(Number.isInteger), process.setuid(ids[0]), process.seteuid(ids[1]),"
                   " process.setgid(ids[2]), process.setegid(ids[3]), Array.isArray(process.getgroups()),"
                   " process.getgroups().every(Number.isInteger), process.getuid() === ids[0])"])
    assert _res(r) == (0, b"true undefined undefined undefined undefined true true true\n", b"")


def test_group_argument_validation(run):
    """CATCHES: setgroups/initgroups argument checks that reach the OS (or use other messages) instead of throwing TypeError first."""
    r = run(["-e", "for (const f of [() => process.setgroups('x'), () => process.setgroups(['abc']), () => process.initgroups('a\\0b', 0)]) {"
                   " try { f() } catch (e) { console.log(e.name + ': ' + e.message) } }"])
    assert _res(r) == (0, b'TypeError: The "groups" argument must be an Array\nTypeError: group ids must be numbers\n'
                          b"TypeError: user contains a null byte\n", b"")


def test_resource_counter_shapes(run):
    """CATCHES: memoryUsage/resourceUsage/cpuUsage returning different key sets or non-numeric counters."""
    code = ("const shape = (o) => Object.keys(o).join(',') + ' ' + Object.values(o).every(v => typeof v === 'number' && v >= 0);"
            "console.log(shape(process.memoryUsage())); console.log(shape(process.resourceUsage())); console.log(shape(process.cpuUsage()));"
            "const a = process.cpuUsage(); const d = process.cpuUsage(a); console.log(Object.keys(d).join(','), typeof process.memoryUsage.rss())")
    r = run(["-e", code])
    assert _res(r) == (0, b"rss,heapTotal,heapUsed,external,arrayBuffers true\n"
                          b"userCPUTime,systemCPUTime,maxRSS,sharedMemorySize,unsharedDataSize,unsharedStackSize,minorPageFault,"
                          b"majorPageFault,swappedOut,fsRead,fsWrite,ipcSent,ipcReceived,signalsCount,voluntaryContextSwitches,"
                          b"involuntaryContextSwitches true\nuser,system true\nuser,system number\n", b"")


def test_emit_warning_format(run):
    """CATCHES: process.emitWarning that prints to stdout, omits the '(node:PID) Warning:' prefix, or ignores the warning type."""
    r = run(["-e", "process.emitWarning('careful'); process.emitWarning('old api', 'DeprecationWarning'); console.log('done')"])
    assert (r.returncode, r.stdout) == (0, b"done\n")
    assert re.sub(rb"\(node:\d+\)", b"(node:PID)", r.stderr) == (
        b"(node:PID) Warning: careful\n(node:PID) DeprecationWarning: old api\n")


def test_process_exit_listeners_not_run(run):
    """CATCHES: implementations that emit 'exit'/'beforeExit' or route timer throws to 'uncaughtException' (this runtime does none of these)."""
    r = run(["-e", "process.on('exit', (c) => console.log('exit event', c)); process.on('beforeExit', () => console.log('beforeExit'));"
                   "process.on('uncaughtException', (e) => console.log('handler', e.message));"
                   "setTimeout(() => { throw new Error('boom') }); console.log('main')"])
    assert _res(r) == (0, b"main\n", b"Uncaught Error: boom\n")
