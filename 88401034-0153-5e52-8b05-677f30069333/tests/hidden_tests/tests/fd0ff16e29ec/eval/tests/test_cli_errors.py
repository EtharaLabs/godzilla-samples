"""Uncaught errors, syntax errors and exit statuses, across -e, stdin, CommonJS files and ES modules."""

import pytest

from conftest import write_files


def _res(r):
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------- -e / stdin (script evaluation)

def test_eval_uncaught_error(run):
    """CATCHES: an uncaught Error in -e code reported with the wrong prefix/format, on stdout, or with exit status other than 1."""
    r = run(["-e", "throw new Error('boom')"])
    assert _res(r) == (1, b"", b"Uncaught Error: boom\n")


def test_eval_output_before_throw_is_kept(run):
    """CATCHES: implementations that buffer console output and lose it when the script throws, or keep running after the throw."""
    r = run(["-e", "console.log('before'); throw new RangeError('stop'); console.log('never')"])
    assert _res(r) == (1, b"before\n", b"Uncaught RangeError: stop\n")


def test_eval_uncaught_type_error_from_engine(run):
    """CATCHES: wrong wording of the engine's own TypeError for property access on null."""
    r = run(["-e", "const o = null; o.x"])
    assert _res(r) == (1, b"", b"Uncaught TypeError: cannot read property 'x' of null\n")


def test_eval_uncaught_reference_error(run):
    """CATCHES: wrong wording of ReferenceError for an undeclared identifier."""
    r = run(["-e", "missingName + 1"])
    assert _res(r) == (1, b"", b"Uncaught ReferenceError: missingName is not defined\n")


def test_eval_custom_error_subclass(run):
    """CATCHES: uncaught reports that ignore a subclass's own name property."""
    r = run(["-e", "class MyErr extends Error { constructor(m) { super(m); this.name = 'MyErr'; } } throw new MyErr('custom')"])
    assert _res(r) == (1, b"", b"Uncaught MyErr: custom\n")


def test_eval_error_with_empty_message(run):
    """CATCHES: reports of an Error without a message that drop the trailing ': ' the script evaluator prints."""
    r = run(["-e", "throw new Error()"])
    assert _res(r) == (1, b"", b"Uncaught Error: \n")


@pytest.mark.parametrize("code, expected", [
    ("throw 'text'", b"Uncaught String: text\n"),
    ("throw 42", b"Uncaught Number: 42\n"),
    ("throw true", b"Uncaught Boolean: true\n"),
    ("throw 7n", b"Uncaught BigInt: 7\n"),
    ("throw null", b"Uncaught null\n"),
    ("throw undefined", b"Uncaught undefined\n"),
    ("throw {}", b"Uncaught Object: \n"),
    ("throw [1, 2]", b"Uncaught Array: \n"),
    ("throw Symbol('s')", b"Uncaught Symbol: \n"),
    ("throw { name: 'Custom', message: 'plain object' }", b"Uncaught Custom: plain object\n"),
    ("throw { name: 'OnlyName' }", b"Uncaught OnlyName: \n"),
])
def test_eval_thrown_non_error_values(run, code, expected):
    """CATCHES: wrong rendering of thrown primitives/objects by the -e evaluator (it prefixes the value's constructor name; null/undefined are bare)."""
    r = run(["-e", code])
    assert _res(r) == (1, b"", expected)


def test_eval_syntax_error_line_one(run):
    """CATCHES: syntax errors reported with a different message, without the '(line N)' suffix, or with 'Uncaught' prefixed."""
    r = run(["-e", "let a = 1; let a = 2;"])
    assert _res(r) == (1, b"", b"SyntaxError: Identifier 'a' has already been declared (line 1)\n")


def test_eval_syntax_error_reports_line(run):
    """CATCHES: a syntax error whose reported line number is not the line where the parser failed."""
    r = run(["-e", "const ok = 1;\nconst alsoOk = 2;\nc = )\nok;\nok;\n"])
    assert _res(r) == (1, b"", b"SyntaxError: unexpected token Punct(\")\") (line 3)\n")
    r = run(["-e", "const ok = 1;\nconst alsoOk = 2;\n\nlet 5 = 1;\nok;\n"])
    assert _res(r) == (1, b"", b"SyntaxError: expected ';' (line 4)\n")


def test_eval_syntax_error_at_eof(run):
    """CATCHES: an unexpected end of input reported with a different token description or line."""
    r = run(["-e", "1 +\n\n\n+"])
    assert _res(r) == (1, b"", b"SyntaxError: unexpected token Eof (line 4)\n")


def test_eval_syntax_error_unterminated_string(run):
    """CATCHES: a lexer error for an unterminated string literal reported with a different message."""
    r = run(["-e", "'unterminated"])
    assert _res(r) == (1, b"", b"SyntaxError: unterminated string literal (line 1)\n")


def test_eval_syntax_error_unterminated_template(run):
    """CATCHES: a lexer error for an unterminated template literal reported with a different message."""
    r = run(["-e", "x = `abc"])
    assert _res(r) == (1, b"", b"SyntaxError: unterminated template literal (line 1)\n")


def test_eval_syntax_error_runs_nothing(run):
    """CATCHES: implementations that execute statements before a later syntax error (the whole program must parse first)."""
    r = run(["-e", "console.log('should not print')\nlet = ;\n"])
    assert _res(r) == (1, b"", b"SyntaxError: unexpected token Punct(\";\") (line 2)\n")


def test_stdin_syntax_error(run):
    """CATCHES: stdin programs whose syntax errors are reported differently than -e programs."""
    r = run([], input="console.log('a')\nlet = ;\n")
    assert _res(r) == (1, b"", b"SyntaxError: unexpected token Punct(\";\") (line 2)\n")


def test_stdin_uncaught_error(run):
    """CATCHES: stdin programs whose uncaught throws do not exit 1 with the 'Uncaught' report."""
    r = run([], input="console.log('start');\nthrow new TypeError('from stdin');\n")
    assert _res(r) == (1, b"start\n", b"Uncaught TypeError: from stdin\n")


def test_stdin_invalid_utf8(run):
    """CATCHES: implementations that lossily decode a non-UTF-8 stdin program instead of failing with 'cannot read stdin' (exit 2)."""
    r = run([], input=b"\xff\xfe console.log(1)\n")
    assert _res(r) == (2, b"", b"cannot read stdin\n")


# ---------------------------------------------------------------- loop-time errors

def test_unhandled_rejection_does_not_fail(run):
    """CATCHES: implementations that exit non-zero on an unhandled rejection, or report it without the '(in promise)' marker."""
    r = run(["-e", "Promise.reject(new Error('rej')); console.log('sync done')"])
    assert _res(r) == (0, b"sync done\n", b"Uncaught (in promise) Error: rej\n")


def test_unhandled_rejection_primitive(run):
    """CATCHES: rejected primitives rendered with a type prefix in the '(in promise)' report (they print bare)."""
    r = run(["-e", "Promise.reject(42); Promise.reject('why')"])
    assert _res(r) == (0, b"", b"Uncaught (in promise) 42\nUncaught (in promise) why\n")


def test_handled_rejection_is_silent(run):
    """CATCHES: implementations that report a rejection even though a handler is attached in the same tick."""
    r = run(["-e", "Promise.reject(new Error('x')).catch(e => console.log('caught', e.message))"])
    assert _res(r) == (0, b"caught x\n", b"")


def test_async_function_rejection(run):
    """CATCHES: unhandled rejections from async functions not being reported after the loop drains."""
    r = run(["-e", "async function f() { await null; throw new SyntaxError('late'); } f(); console.log('scheduled')"])
    assert _res(r) == (0, b"scheduled\n", b"Uncaught (in promise) SyntaxError: late\n")


def test_timer_callback_throw_keeps_loop_alive(run):
    """CATCHES: implementations that abort the event loop (or exit 1) when a timer callback throws; Node-style they report and continue."""
    r = run(["-e", "setTimeout(() => { throw new Error('in timer') }); setTimeout(() => console.log('after'), 5)"])
    assert _res(r) == (0, b"after\n", b"Uncaught Error: in timer\n")


def test_timer_callback_throw_primitive(run):
    """CATCHES: loop-reported primitive throws rendered with a type prefix (loop reports print the bare value)."""
    r = run(["-e", "setTimeout(() => { throw 'plain' })"])
    assert _res(r) == (0, b"", b"Uncaught plain\n")


def test_onerror_suppresses_timer_error(run):
    """CATCHES: a global onerror handler that is not consulted, gets the wrong message, or cannot suppress the default report by returning true."""
    code = ("globalThis.onerror = (msg, src, line, col, err) => { console.log('handled:', msg, err instanceof Error); return true; };"
            "setTimeout(() => { throw new TypeError('t1') });")
    r = run(["-e", code])
    assert _res(r) == (0, b"handled: Uncaught TypeError: t1 true\n", b"")


def test_onerror_not_returning_true_still_reports(run):
    """CATCHES: onerror handlers that suppress the default report even though they did not return true."""
    code = "onerror = (msg) => { console.log('saw', msg); }; setTimeout(() => { throw 5 });"
    r = run(["-e", code])
    assert _res(r) == (0, b"saw Uncaught 5\n", b"Uncaught 5\n")


def test_onunhandledrejection_prevent_default(run):
    """CATCHES: an onunhandledrejection handler that is not called with an event, or whose preventDefault does not suppress the report."""
    code = ("onunhandledrejection = (ev) => { console.log(ev.type, ev.reason.message, ev.cancelable); ev.preventDefault(); };"
            "Promise.reject(new Error('quiet'));")
    r = run(["-e", code])
    assert _res(r) == (0, b"unhandledrejection quiet true\n", b"")


def test_onunhandledrejection_without_prevent_default(run):
    """CATCHES: rejection handlers that suppress the default report without calling preventDefault."""
    code = "onunhandledrejection = (ev) => { console.log('seen', ev.defaultPrevented); }; Promise.reject(new Error('loud'));"
    r = run(["-e", code])
    assert _res(r) == (0, b"seen false\n", b"Uncaught (in promise) Error: loud\n")


def test_report_error_default(run):
    """CATCHES: reportError that throws, prints to stdout, or formats differently from an uncaught loop error."""
    r = run(["-e", "reportError(new TypeError('reported')); console.log('continues')"])
    assert _res(r) == (0, b"continues\n", b"Uncaught TypeError: reported\n")


def test_report_error_requires_argument(run):
    """CATCHES: reportError() with no argument not throwing the documented TypeError."""
    r = run(["-e", "try { reportError() } catch (e) { console.log(e.name, e.message) }"])
    assert _res(r) == (0, b"TypeError reportError requires at least 1 argument\n", b"")


def test_report_error_routed_through_onerror(run):
    """CATCHES: reportError that bypasses the global onerror handler."""
    r = run(["-e", "onerror = (m) => { console.log('via onerror:', m); return true }; reportError('str')"])
    assert _res(r) == (0, b"via onerror: Uncaught str\n", b"")


# ---------------------------------------------------------------- process.exit

@pytest.mark.parametrize("arg, code", [("", 0), ("3", 3), ("'5'", 5), ("259", 3), ("-1", 255), ("0", 0)])
def test_process_exit_codes(run, arg, code):
    """CATCHES: process.exit that ignores its argument, does not coerce strings, or does not wrap the status modulo 256."""
    r = run(["-e", f"console.log('pre'); process.exit({arg}); console.log('post')"])
    assert _res(r) == (code, b"pre\n", b"")


def test_process_exit_from_timer(run):
    """CATCHES: process.exit inside a timer callback that does not terminate the process immediately with that status."""
    r = run(["-e", "setTimeout(() => process.exit(7), 1); setTimeout(() => console.log('too late'), 50); console.log('queued')"])
    assert _res(r) == (7, b"queued\n", b"")


def test_process_exit_skips_pending_rejection_report(run):
    """CATCHES: implementations that run the loop (and report rejections) after process.exit was called synchronously."""
    r = run(["-e", "Promise.reject(new Error('unseen')); process.exit(4)"])
    assert _res(r) == (4, b"", b"")


# ---------------------------------------------------------------- CommonJS entry files

def test_cjs_file_uncaught_error(run, workdir):
    """CATCHES: CommonJS entry errors reported differently from the documented 'Uncaught Name: message' with exit 1."""
    write_files(workdir, {"e.js": "console.log('a');\nthrow new Error('cjs boom');\n"})
    r = run(["e.js"])
    assert _res(r) == (1, b"a\n", b"Uncaught Error: cjs boom\n")


@pytest.mark.parametrize("value, expected", [("'s'", b"Uncaught s\n"), ("5", b"Uncaught 5\n"), ("{}", b"Uncaught [object Object]\n"),
                                             ("null", b"Uncaught null\n")])
def test_cjs_file_thrown_primitives(run, workdir, value, expected):
    """CATCHES: a CommonJS entry's thrown non-Error values rendered with a type prefix (file entries print them via ToString)."""
    write_files(workdir, {"t.js": f"throw {value}\n"})
    r = run(["t.js"])
    assert _res(r) == (1, b"", expected)


def test_cjs_file_syntax_error(run, workdir):
    """CATCHES: CommonJS entry syntax errors reported with a '(line N)' suffix or without the 'Uncaught' prefix."""
    write_files(workdir, {"s.js": "// fine\nlet x = ;\n"})
    r = run(["s.js"])
    assert _res(r) == (1, b"", b"Uncaught SyntaxError: unexpected token Punct(\";\")\n")


def test_cjs_missing_require(run, workdir):
    """CATCHES: wrong wording of the CommonJS 'Cannot find module' error (it names the request and the requiring directory)."""
    write_files(workdir, {"r.js": "require('./nope')\n"})
    r = run(["r.js"])
    assert (r.returncode, r.stdout) == (1, b"")
    assert r.stderr.replace(str(workdir).encode(), b"<WORKDIR>") == b"Uncaught Error: Cannot find module './nope' from '<WORKDIR>'\n"


def test_cjs_error_in_required_module(run, workdir):
    """CATCHES: errors thrown while loading a dependency not propagating to the entry as an uncaught error."""
    write_files(workdir, {"main.js": "console.log('main start'); require('./dep');\n",
                          "dep.js": "console.log('dep start'); throw new TypeError('dep failed');\n"})
    r = run(["main.js"])
    assert _res(r) == (1, b"main start\ndep start\n", b"Uncaught TypeError: dep failed\n")


def test_cjs_timer_error_after_main(run, workdir):
    """CATCHES: a throw from a timer scheduled by a CommonJS entry changing the exit status (it is reported, exit stays 0)."""
    write_files(workdir, {"t.js": "setTimeout(() => { throw new Error('later') }, 1); console.log('main done');\n"})
    r = run(["t.js"])
    assert _res(r) == (0, b"main done\n", b"Uncaught Error: later\n")


# ---------------------------------------------------------------- ES module entry files

def test_esm_uncaught_error_reports_twice(run, workdir):
    """CATCHES: ESM entry throws not reported both as a rejected module promise and as the final uncaught error (exit 1)."""
    write_files(workdir, {"e.mjs": "console.log('m');\nthrow new Error('esm boom');\n"})
    r = run(["e.mjs"])
    assert _res(r) == (1, b"m\n", b"Uncaught (in promise) Error: esm boom\nUncaught Error: esm boom\n")


def test_esm_thrown_primitive(run, workdir):
    """CATCHES: ESM entry primitive throws rendered like CommonJS ones (the final report carries the type prefix)."""
    write_files(workdir, {"p.mjs": "throw 'esm text'\n"})
    r = run(["p.mjs"])
    assert _res(r) == (1, b"", b"Uncaught (in promise) esm text\nUncaught String: esm text\n")


def test_esm_top_level_await_rejection(run, workdir):
    """CATCHES: a rejected top-level await in an ES module entry that does not fail the process with exit 1."""
    write_files(workdir, {"t.mjs": "console.log('waiting');\nawait Promise.reject(new RangeError('tla'));\nconsole.log('never');\n"})
    r = run(["t.mjs"])
    assert _res(r) == (1, b"waiting\n", b"Uncaught (in promise) RangeError: tla\nUncaught RangeError: tla\n")


def test_esm_syntax_error(run, workdir):
    """CATCHES: ES module syntax errors reported with a line suffix or without the 'Uncaught' prefix."""
    write_files(workdir, {"s.mjs": "\n\nlet x = ;\n"})
    r = run(["s.mjs"])
    assert _res(r) == (1, b"", b"Uncaught SyntaxError: unexpected token Punct(\";\")\n")


def test_esm_missing_import(run, workdir):
    """CATCHES: wrong wording of the ESM 'module not found' error (it names the specifier and the importing file)."""
    write_files(workdir, {"i.mjs": "import './missing.mjs';\nconsole.log('unreached');\n"})
    r = run(["i.mjs"])
    assert (r.returncode, r.stdout) == (1, b"")
    assert r.stderr.replace(str(workdir).encode(), b"<WORKDIR>") == (
        b"Uncaught TypeError: module not found: ./missing.mjs (imported from <WORKDIR>/i.mjs)\n")


def test_esm_missing_named_export(run, workdir):
    """CATCHES: importing a name a module does not export being silently undefined instead of a link-time SyntaxError."""
    write_files(workdir, {"main.mjs": "import { nope } from './lib.mjs';\nconsole.log(nope);\n",
                          "lib.mjs": "export const yes = 1;\n"})
    r = run(["main.mjs"])
    assert (r.returncode, r.stdout) == (1, b"")
    assert r.stderr.replace(str(workdir).encode(), b"<WORKDIR>") == (
        b"Uncaught SyntaxError: the requested module '<WORKDIR>/lib.mjs' does not provide an export named 'nope'\n")


def test_loop_reports_name_only_errors_without_colon(run):
    """CATCHES: loop-time reports that print 'Name: ' for errors with an empty message (they print just the name, unlike -e top-level throws)."""
    r = run(["-e", "setTimeout(() => { throw new Error() }); setTimeout(() => { throw { name: 'OnlyName', message: '' } });"
                   "Promise.reject(new TypeError())"])
    assert _res(r) == (0, b"", b"Uncaught (in promise) TypeError\nUncaught Error\nUncaught OnlyName\n")
