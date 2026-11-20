"""The interactive shell, driven through the documented `repl` keyword with piped stdin."""

from conftest import golden

BANNER = b"lumen 0.1.3 (.help for help, .exit or Ctrl-D to quit)\n"


def _repl(run, text, args=()):
    return run([*args, "repl"], input=text)


def test_repl_eof_immediately(run):
    """CATCHES: a REPL that omits the banner, the '> ' prompt, or the newline printed on end of input."""
    r = run(["repl"])
    assert (r.returncode, r.stdout, r.stderr) == (0, BANNER + b"> \n", b"")


def test_repl_expression_results(run):
    """CATCHES: wrong rendering of REPL results (numbers bare, strings single-quoted, undefined for statements)."""
    r = _repl(run, "1 + 1\n'hi'\nlet z = 3\nz * 2\n")
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == BANNER + b"> 2\n> 'hi'\n> undefined\n> 6\n> \n"


def test_repl_value_rendering(run):
    """CATCHES: REPL result rendering that diverges from console-style ToString rendering for objects, arrays, symbols, bigints, null."""
    r = _repl(run, "({a: 1})\n[1, 2, 3]\nnull\nundefined\nSymbol('q')\n10n\ntrue\n-0\n1/0\n")
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "value_rendering")


def test_repl_last_result_underscore(run):
    """CATCHES: a REPL that does not bind `_` to the last result, or binds it for errors."""
    r = _repl(run, "const x = 10\nx * 2\n_ + 1\n_ * 2\n")
    assert r.stdout == BANNER + b"> undefined\n> 20\n> 21\n> 42\n> \n"


def test_repl_persistent_realm(run):
    """CATCHES: a REPL that evaluates each line in a fresh realm (functions/classes must persist between inputs)."""
    r = _repl(run, "function sq(n) { return n * n }\nclass P { constructor(v) { this.v = v } }\nsq(new P(7).v)\n")
    assert r.stdout == BANNER + b"> undefined\n> undefined\n> 49\n> \n"


def test_repl_multiline_continuation(run):
    """CATCHES: a REPL that does not detect incomplete input or uses a different '.. ' continuation prompt."""
    r = _repl(run, "function fact(n) {\n  return n < 2 ? 1 : n * fact(n - 1)\n}\nfact(5)\n")
    assert r.stdout == BANNER + b"> .. .. undefined\n> 120\n> \n"


def test_repl_continuation_template_and_paren(run):
    """CATCHES: continuation detection that only handles braces (templates, parens and arrays must continue too)."""
    r = _repl(run, "const s = `a\nb`\ns.length\n(1 +\n2)\n[1,\n2,\n3].length\n")
    assert r.stdout == golden(__file__, "continuation_kinds")


def test_repl_dot_exit_in_continuation_is_code(run):
    """CATCHES: a REPL that treats '.exit' as a command while inside unfinished multi-line input."""
    r = _repl(run, "const s = `\n.exit\n`\ns.includes('.exit')\n")
    assert r.stdout == BANNER + b"> .. .. undefined\n> true\n> \n"


def test_repl_help_command(run):
    """CATCHES: a REPL whose .help command is missing, evaluated as code, or prints different help text."""
    r = _repl(run, ".help\n")
    assert r.stdout == golden(__file__, "help")


def test_repl_unknown_dot_command(run):
    """CATCHES: unknown dot commands evaluated as code or reported with a different message."""
    r = _repl(run, ".nope\n  .save file  \n")
    assert r.stdout == BANNER + b"> unknown command .nope (try .help)\n> unknown command .save file (try .help)\n> \n"


def test_repl_double_dot_is_code(run):
    """CATCHES: input starting with '..' treated as a dot command instead of (invalid) code."""
    r = _repl(run, "..foo\n")
    assert r.stdout == BANNER + b"> SyntaxError: unexpected token Punct(\".\")\n> \n"


def test_repl_exit_command_stops_reading(run):
    """CATCHES: a REPL that keeps evaluating input after .exit, or prints a trailing newline/prompt after it."""
    r = _repl(run, "1\n.exit\nconsole.log('not reached')\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, BANNER + b"> 1\n> ", b"")


def test_repl_blank_lines_reprompt(run):
    """CATCHES: blank or whitespace-only lines that print 'undefined' instead of just re-prompting."""
    r = _repl(run, "\n   \n\t\n7\n")
    assert r.stdout == BANNER + b"> > > > 7\n> \n"


def test_repl_uncaught_throw_recovers(run):
    """CATCHES: a REPL that dies on an uncaught throw or reports it differently from 'Uncaught Name: message'."""
    r = _repl(run, "throw new TypeError('boom')\n1\n")
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == BANNER + b"> Uncaught TypeError: boom\n> 1\n> \n"


def test_repl_thrown_primitive(run):
    """CATCHES: REPL throws of primitives rendered with a type prefix (the REPL prints the bare value)."""
    r = _repl(run, "throw 'text'\nthrow 3\nthrow { name: 'N', message: 'm' }\n")
    assert r.stdout == BANNER + b"> Uncaught text\n> Uncaught 3\n> Uncaught N: m\n> \n"


def test_repl_syntax_error_recovers(run):
    """CATCHES: a REPL whose syntax errors carry a line suffix, or which keeps the bad input buffered afterwards."""
    r = _repl(run, "let let = 1\n2 + 2\n")
    assert r.stdout == BANNER + b"> SyntaxError: 'let' is disallowed as a lexically bound name\n> 4\n> \n"


def test_repl_console_output_interleaves(run):
    """CATCHES: console output from REPL input printed after the result instead of before it, or stderr output lost."""
    r = _repl(run, "console.log('hi')\nconsole.error('to err')\n")
    assert r.stdout == BANNER + b"> hi\nundefined\n> undefined\n> \n"
    assert r.stderr == b"to err\n"


def test_repl_top_level_await(run):
    """CATCHES: a REPL without top-level await sugar (expression form) or that prints the promise instead of its value."""
    r = _repl(run, "await Promise.resolve(42)\nawait new Promise(r => setTimeout(() => r('slept'), 5))\n")
    assert r.stdout == BANNER + b"> 42\n> 'slept'\n> \n"


def test_repl_await_rejection(run):
    """CATCHES: rejected top-level awaits not reported as 'Uncaught <error>'."""
    r = _repl(run, "await Promise.reject(new RangeError('nope'))\n")
    assert r.stdout == BANNER + b"> Uncaught RangeError: nope\n> \n"


def test_repl_await_never_settles(run):
    """CATCHES: a REPL that hangs or prints undefined when an awaited promise never settles."""
    r = _repl(run, "await new Promise(() => {})\n'still alive'\n")
    assert r.stdout == BANNER + b"> [promise never settled]\n> 'still alive'\n> \n"


def test_repl_await_statement_form(run):
    """CATCHES: top-level await in statement form (declarations) not supported via the async-wrapper fallback."""
    r = _repl(run, "const v = await Promise.resolve(5); console.log('v is', v)\ntypeof v\n")
    assert r.stdout == BANNER + b"> v is 5\nundefined\n> 'undefined'\n> \n"


def test_repl_await_syntax_error_reports_original(run):
    """CATCHES: a REPL that reports the async-wrapper's parse error instead of the original one when await input is invalid."""
    r = _repl(run, "await 1 +\n2\n")
    assert r.stdout == BANNER + b"> SyntaxError: expected ';'\n> 2\n> \n"


def test_repl_timers_settle_before_prompt(run):
    """CATCHES: a REPL that prints the next prompt before pending timers have fired (loop-to-quiescence per input)."""
    r = _repl(run, "setTimeout(() => console.log('later'), 5); 'queued'\n'next'\n")
    assert r.stdout == BANNER + b"> later\n'queued'\n> 'next'\n> \n"


def test_repl_respects_tier_option(run):
    """CATCHES: implementations that reject --tier before the repl keyword or change results under it."""
    r = _repl(run, "let t = 0; for (let i = 0; i < 10; i++) t += i; t\n", args=("--tier=interp",))
    assert r.stdout == BANNER + b"> 45\n> \n"


def test_repl_process_exit(run):
    """CATCHES: process.exit inside the REPL not terminating the process with that status."""
    r = _repl(run, "1\nprocess.exit(9)\n2\n")
    assert (r.returncode, r.stdout, r.stderr) == (9, BANNER + b"> 1\n> ", b"")


def test_repl_unfinished_input_at_eof(run):
    """CATCHES: a REPL that evaluates or reports an unfinished buffer when input ends mid-continuation."""
    r = _repl(run, "function f() {\n  return 1\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, BANNER + b"> .. .. \n", b"")


def test_repl_session_golden(run):
    """CATCHES: any divergence in a longer mixed REPL session (results, errors, continuation, dot commands, timers)."""
    session = (
        "const m = new Map([[1, 'a'], [2, 'b']])\n"
        "m.size\n"
        "[...m.values()].join('')\n"
        "class A {\n  get v() { return 41 }\n}\n"
        "new A().v + 1\n"
        "JSON.stringify({x: [1, {y: 2}]})\n"
        "typeof _\n"
        "Promise.resolve(1).then(v => console.log('then', v)); 'sync'\n"
        "undefinedThing\n"
        ".help\n"
        "`multi\nline`\n"
        "await Promise.all([1, 2].map(async x => x * 10))\n"
    )
    r = _repl(run, session)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "session")


def test_repl_await_wrapper_sync_throw(run):
    """CATCHES: a REPL whose top-level-await wrapper swallows a synchronous throw from its own bookkeeping instead of reporting it."""
    r = _repl(run, "Object.defineProperty(globalThis, '__repl_settled', { set() { throw new Error('setter blew up') }, configurable: true })\n"
                   "await 1\n")
    assert r.stdout == BANNER + b"> [object Object]\n> Uncaught Error: setter blew up\n> \n"
