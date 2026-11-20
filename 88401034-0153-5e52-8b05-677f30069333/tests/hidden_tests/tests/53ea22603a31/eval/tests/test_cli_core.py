"""Entry points of lumen-cli: script files, stdin, -e, the piped REPL, tiers, exit codes and
how uncaught errors are reported."""

import pytest

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)
TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
         pytest.param(["--tier=bytecode"], id="bytecode")]


def test_args_after_script_belong_to_script(run, workdir):
    """CATCHES: flags after the script path being interpreted by the CLI (--help/-e) instead of being
    passed through to process.argv."""
    check_script(run, workdir, G, "argv_passthrough",
                 "console.log(JSON.stringify(process.argv.slice(2)));\n"
                 "console.log(process.argv.length);\n",
                 args=["-e", "x", "--tier=bytecode", "repl", "plain arg", ""])


def test_stdin_program(run):
    """CATCHES: a CLI that ignores piped stdin when no script is given, or buffers output wrongly."""
    src = "let total = 0;\nfor (let i = 1; i <= 10; i++) total += i * i;\nconsole.log('sum of squares', total);\n" \
          "console.log([3, 1, 2].sort().join('-'));\n"
    r = run([], input=src)
    assert_result(r, G / "stdin_program.golden")


def test_empty_stdin_is_a_silent_success(run):
    """CATCHES: treating empty or comment-only stdin as an error, echoing it, or printing a REPL banner
    when stdin is not a terminal (a program on the same stream must still run)."""
    empty = run([], input=b"")
    comments = run([], input=b"// nothing to do\n/* still nothing */\n\n")
    code = run([], input=b"// a comment, then code\nconsole.log(typeof globalThis)\n")
    assert (empty.stdout, empty.stderr, empty.returncode) == (b"", b"", 0)
    assert (comments.stdout, comments.stderr, comments.returncode) == (b"", b"", 0)
    assert (code.stdout, code.stderr, code.returncode) == (b"object\n", b"", 0)


def test_stdin_invalid_utf8(run):
    """CATCHES: accepting or lossily decoding invalid UTF-8 on stdin instead of failing with exit 2."""
    r = run([], input=b"console.log('\xff\xfe')\n")
    assert r.stdout == b""
    assert r.stderr == b"cannot read stdin\n"
    assert r.returncode == 2


def test_eval_flag(run):
    """CATCHES: -e not evaluating its argument, or output lines out of order between log calls."""
    r = run(["-e", "console.log('a', 1, true, null, undefined); console.log(2 ** 10)"])
    assert r.stdout == b"a 1 true null undefined\n1024\n"
    assert r.stderr == b""
    assert r.returncode == 0


def test_eval_without_code(run):
    """CATCHES: -e with no following argument crashing, hanging on stdin, or using the wrong exit code."""
    r = run(["-e"])
    assert r.stdout == b""
    assert r.stderr == b"-e expects code\n"
    assert r.returncode == 2


def test_eval_argv_includes_cli_arguments(run):
    """CATCHES: wrong process.argv layout in -e mode; extra arguments after the code stay in argv and are
    not run as a script."""
    r = run(["-e", "console.log(JSON.stringify(process.argv.slice(1)))", "extra.js", "more"])
    assert r.stdout == b'["-e","console.log(JSON.stringify(process.argv.slice(1)))","extra.js","more"]\n'
    assert r.stderr == b""
    assert r.returncode == 0


def test_eval_wins_over_stdin(run):
    """CATCHES: reading stdin even though -e supplied the program."""
    r = run(["-e", "console.log('from -e')"], input="console.log('from stdin')\n")
    assert r.stdout == b"from -e\n"
    assert r.stderr == b""
    assert r.returncode == 0


def test_missing_script(run):
    """CATCHES: a missing script reported with a different message, on stdout, or with exit code 1."""
    r = run(["does-not-exist.js"])
    assert r.stdout == b""
    assert r.stderr == b"cannot read does-not-exist.js: not a file\n"
    assert r.returncode == 2


def test_directory_as_script(run, workdir):
    """CATCHES: trying to execute a directory (or its index.js) instead of rejecting it as not a file."""
    (workdir / "pkg").mkdir()
    (workdir / "pkg" / "index.js").write_text("console.log('index ran')\n")
    r = run(["pkg"])
    assert r.stdout == b""
    assert r.stderr == b"cannot read pkg: not a file\n"
    assert r.returncode == 2


def test_unknown_tier(run):
    """CATCHES: silently accepting an unknown --tier value (including 'jit', which the CLI rejects)."""
    r = run(["--tier=jit", "-e", "console.log('ran')"])
    assert r.stdout == b""
    assert r.stderr == b"unknown tier 'jit' (interp|bytecode)\n"
    assert r.returncode == 2


@pytest.mark.parametrize("cli", TIERS)
def test_tiers_agree_on_program(run, workdir, cli):
    """CATCHES: an execution tier (tree-walker, bytecode VM, JIT) that diverges on closures, loops,
    exceptions or number formatting."""
    src = r"""
function fib(n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
const counters = [];
for (let i = 0; i < 3; i++) counters.push(() => i * 10);
function sumTo(n) { let s = 0; for (let i = 0; i < n; i++) { s += i % 7 === 0 ? i / 2 : i; } return s; }
let caught;
try { (function thrower() { throw new SyntaxError('inner'); })(); } catch (e) { caught = e.name + ':' + e.message; }
console.log(fib(20), counters.map(f => f()).join(','), sumTo(1000), caught);
console.log(0.1 + 0.2, 1 / 3, 1e21, 2 ** 53 + 1, -1e-7, (255).toString(16), (0.000001234).toFixed(8));
"""
    check_script(run, workdir, G, "tiers_program", src, cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_tiers_agree_on_stdin_eval(run, cli):
    """CATCHES: tier flags only applied to script files and not to stdin evaluation."""
    src = "const o = {}; for (let i = 0; i < 50; i++) o['k' + (i % 5)] = (o['k' + (i % 5)] || 0) + i;\n" \
          "console.log(JSON.stringify(o));\n"
    r = run([*cli], input=src)
    assert_result(r, G / "tiers_stdin.golden")


def test_lumen_tier_env(run, workdir):
    """CATCHES: ignoring the documented LUMEN_TIER=interp environment override or breaking output under it."""
    check_script(run, workdir, G, "tiers_program_env",
                 "function f(a) { let r = 0; for (const x of a) r += x; return r; }\n"
                 "console.log(f([1, 2, 3, 4]), [...'abc'].reverse().join(''));\n",
                 env_overrides={"LUMEN_TIER": "interp"})


def test_syntax_error_in_eval(run):
    """CATCHES: syntax errors reported with a different message/line format or exit code."""
    r = run(["-e", "let a = 1;\nlet b = ;\n"])
    assert r.stdout == b""
    assert r.stderr == b'SyntaxError: unexpected token Punct(";") (line 2)\n'
    assert r.returncode == 1


def test_syntax_error_from_stdin(run):
    """CATCHES: stdin programs with a parse error partially executing or reporting the wrong line."""
    r = run([], input="console.log('first');\n\n\nfunction (\n")
    assert r.stdout == b""
    assert r.stderr == b"SyntaxError: expected binding identifier (line 5)\n"
    assert r.returncode == 1


def test_syntax_error_in_script_file(run, workdir):
    """CATCHES: a CommonJS script file with a parse error being reported without the Uncaught prefix or
    with exit code 0."""
    check_script(run, workdir, G, "syntax_error_file", "console.log('never');\nconst x = {;\n",
                 rc=1, stderr=G / "syntax_error_file.stderr.golden")


def test_syntax_error_in_module_file(run, workdir):
    """CATCHES: ES module parse errors not reported as 'Uncaught SyntaxError: ... (line N)'."""
    check_script(run, workdir, G, "syntax_error_module", "export const a = 1;\n\nimport {\n", filename="bad.mjs",
                 rc=1, stderr=G / "syntax_error_module.stderr.golden")


@pytest.mark.parametrize("snippet,expected", [
    ("throw new TypeError('bad thing')", b"Uncaught TypeError: bad thing\n"),
    ("throw new Error('')", b"Uncaught Error: \n"),
    ("throw 42", b"Uncaught Number: 42\n"),
    ("throw 'plain string'", b"Uncaught String: plain string\n"),
    ("throw {name: 'Custom', message: 'shaped like an error'}", b"Uncaught Custom: shaped like an error\n"),
    ("null.x", b"Uncaught TypeError: cannot read property 'x' of null\n"),
    ("undefinedVariable + 1", b"Uncaught ReferenceError: undefinedVariable is not defined\n"),
    ("class E extends Error { constructor(m) { super(m); this.name = 'MyError'; } } throw new E('sub')",
     b"Uncaught MyError: sub\n"),
], ids=["typeerror", "empty-message", "number", "string", "error-like-object", "null-property",
        "reference", "subclass"])
def test_uncaught_in_eval(run, snippet, expected):
    """CATCHES: wrong rendering of uncaught exceptions in -e mode (name/message joining, primitives
    rendered with their constructor name) or a non-1 exit code."""
    r = run(["-e", "console.log('before');\n" + snippet])
    assert r.stdout == b"before\n"
    assert r.stderr == expected
    assert r.returncode == 1


@pytest.mark.parametrize("snippet,expected", [
    ("throw new RangeError('out of range')", b"Uncaught RangeError: out of range\n"),
    ("throw 42", b"Uncaught 42\n"),
    ("throw 'plain string'", b"Uncaught plain string\n"),
    ("throw {message: 'no name'}", b"Uncaught [object Object]\n"),
    ("throw null", b"Uncaught null\n"),
    ("throw Object.assign(new Error('boom'), {name: 'Renamed'})", b"Uncaught Renamed: boom\n"),
], ids=["rangeerror", "number", "string", "nameless-object", "null", "renamed"])
def test_uncaught_in_script_file(run, workdir, snippet, expected):
    """CATCHES: uncaught exceptions of a CommonJS entry rendered differently from the reference (which
    prints primitives bare and objects as name: message)."""
    (workdir / "main.js").write_text("console.log('before');\n" + snippet + "\n")
    r = run(["main.js"])
    assert r.stdout == b"before\n"
    assert r.stderr == expected
    assert r.returncode == 1


def test_uncaught_in_module(run, workdir):
    """CATCHES: a throwing ES module not reporting both the rejected evaluation promise and the uncaught
    error, or exiting 0."""
    check_script(run, workdir, G, "uncaught_module",
                 "console.log('top');\nawait null;\nthrow new RangeError('esm boom');\n", filename="m.mjs",
                 rc=1, stderr="Uncaught (in promise) RangeError: esm boom\nUncaught RangeError: esm boom\n")


def test_unhandled_rejection_does_not_change_exit(run):
    """CATCHES: an unhandled rejection that aborts the event loop or changes the exit status; the
    reference reports it and keeps running timers."""
    r = run(["-e", "Promise.reject(new Error('rej')); setTimeout(() => console.log('later'), 5)"])
    assert r.stdout == b"later\n"
    assert r.stderr == b"Uncaught (in promise) Error: rej\n"
    assert r.returncode == 0


def test_uncaught_error_in_timer_keeps_loop_running(run):
    """CATCHES: a throwing timer callback that stops other timers or sets a failing exit code."""
    r = run(["-e", "setTimeout(() => { throw new Error('in timer'); }, 1);\n"
                   "setTimeout(() => console.log('after'), 30);"])
    assert r.stdout == b"after\n"
    assert r.stderr == b"Uncaught Error: in timer\n"
    assert r.returncode == 0


@pytest.mark.parametrize("code,rc", [(0, 0), (3, 3), (255, 255), (256, 0), (-1, 255)])
def test_process_exit_code(run, code, rc):
    """CATCHES: process.exit(n) not terminating immediately (later output appears) or truncating n differently."""
    r = run(["-e", f"console.log('start'); process.exit({code}); console.log('unreachable')"])
    assert r.stdout == b"start\n"
    assert r.stderr == b""
    assert r.returncode == rc


def test_process_exit_inside_timer(run):
    """CATCHES: process.exit from a callback not cancelling pending timers."""
    r = run(["-e", "setTimeout(() => { console.log('t1'); process.exit(4); }, 1);\n"
                   "setTimeout(() => console.log('t2 must not run'), 200);"])
    assert r.stdout == b"t1\n"
    assert r.stderr == b""
    assert r.returncode == 4


def test_exit_code_property_is_ignored(run):
    """CATCHES: honouring process.exitCode at loop exit; the reference always exits 0 after a clean run."""
    r = run(["-e", "process.exitCode = 3; process.stdout.write('no newline')"])
    assert r.stdout == b"no newline"
    assert r.stderr == b""
    assert r.returncode == 0


def test_stdout_and_stderr_streams(run):
    """CATCHES: console.warn/error going to stdout, info/debug going to stderr, or missing newlines."""
    r = run(["-e", "console.log('log'); console.info('info'); console.debug('debug'); console.warn('warn');"
                   " console.error('error'); process.stdout.write('raw-out\\n'); process.stderr.write('raw-err\\n')"])
    assert r.stdout == b"log\ninfo\ndebug\nraw-out\n"
    assert r.stderr == b"warn\nerror\nraw-err\n"
    assert r.returncode == 0


def test_console_renders_with_tostring(run):
    """CATCHES: a console.log that pretty-prints objects like util.inspect; the reference joins the
    ToString of every argument with spaces."""
    src = r"""
console.log({a: 1}, [1, [2, 3], , null, undefined], -0, NaN, 1e21, 12345678901234567890n);
console.log(Symbol('desc'), Symbol(), function named() { return 1; });
console.log(new Map([[1, 2]]), new Set([1]), new Date(0).toISOString(), /re/gi, new Error('msg'));
console.log({ toString() { return 'custom toString'; } }, { toString() { throw new Error('x'); } });
console.log();
console.log('', '');
console.log('%s and %d', 'fmt', 5);
"""
    r = run(["-e", src])
    assert_result(r, G / "console_tostring.golden")


def test_shebang_bom_and_crlf(run, workdir):
    """CATCHES: failing on a leading #! line, a UTF-8 byte order mark or CRLF line endings in a script."""
    (workdir / "a.js").write_bytes(b"#!/usr/bin/env lumen-cli\nconsole.log('shebang ok')\n")
    (workdir / "b.js").write_bytes(b"\xef\xbb\xbfconsole.log('bom ok')\r\nconsole.log('crlf'\r\n)\r\n")
    a = run(["a.js"])
    b = run(["b.js"])
    assert (a.stdout, a.stderr, a.returncode) == (b"shebang ok\n", b"", 0)
    assert (b.stdout, b.stderr, b.returncode) == (b"bom ok\ncrlf\n", b"", 0)


def test_invalid_utf8_script_file(run, workdir):
    """CATCHES: running a script file that is not valid UTF-8 instead of reporting the read failure."""
    (workdir / "bad.js").write_bytes(b"console.log('\xff\xfe')\n")
    r = run(["bad.js"])
    assert r.stdout == b""
    assert r.stderr.replace(str(workdir.resolve()).encode(), b"<DIR>") == \
        b"Uncaught Error: cannot read '<DIR>/bad.js': stream did not contain valid UTF-8\n"
    assert r.returncode == 1


def test_unicode_source_and_output(run, workdir):
    """CATCHES: mishandling non-ASCII identifiers, astral characters, escapes or UTF-16 length semantics."""
    src = r"""
const café = 'naïve résumé';
const ꝏ = '😀👍🏽 中文 עברית';
console.log(café, café.length, ꝏ);
console.log(ꝏ.length, [...ꝏ].length, '😀'.codePointAt(0).toString(16), '\u{1F600}' === '😀');
console.log('é'.normalize('NFD').length, 'é'.normalize('NFC') === 'é');
console.log(encodeURIComponent('é/😀 ?'), decodeURIComponent('%E4%B8%AD'));
console.log('ǅ'.toLowerCase(), 'ß'.toUpperCase(), 'İ'.toLowerCase().length, 'ΑΣ'.toLowerCase());
console.log(JSON.stringify(' \ud800'), escape('ä'), unescape('%u4E2D'));
"""
    check_script(run, workdir, G, "unicode_source", src)


def test_large_program_from_stdin(run):
    """CATCHES: truncating or mis-buffering a large stdin program (thousands of statements)."""
    lines = [f"const v{i} = {i} * 3 + {i % 7};" for i in range(4000)]
    lines.append("let acc = 0;")
    lines += [f"acc += v{i};" for i in range(0, 4000, 3)]
    lines.append("console.log(acc, v3999, typeof v0);")
    r = run([], input="\n".join(lines) + "\n")
    assert r.stdout == b"8006000 11999 number\n"
    assert r.stderr == b""
    assert r.returncode == 0


def test_large_output(run):
    """CATCHES: losing or reordering output when a program writes many lines (buffer/flush bugs)."""
    r = run(["-e", "for (let i = 0; i < 20000; i++) console.log('line ' + i + ' ' + 'x'.repeat(i % 50));"])
    expected = "".join(f"line {i} {'x' * (i % 50)}\n" for i in range(20000)).encode()
    assert r.stdout == expected
    assert r.stderr == b""
    assert r.returncode == 0


def test_large_input_file_processing(run, workdir):
    """CATCHES: a runtime whose fs read truncates large files or mis-splits lines."""
    rows = [f"{i},{'name' + str(i)},{(i * 37) % 101}" for i in range(8000)]
    (workdir / "data.csv").write_text("\n".join(rows) + "\n")
    check_script(run, workdir, G, "large_csv", r"""
const fs = require('fs');
const text = fs.readFileSync('data.csv', 'utf8');
const rows = text.trim().split('\n').map(l => l.split(','));
let total = 0, max = -1, maxName = '';
for (const [id, name, score] of rows) { total += +score; if (+score > max || (+score === max && name < maxName)) { max = +score; maxName = name; } }
console.log(rows.length, total, max, maxName, text.length);
""")


def test_repl_piped(run):
    """CATCHES: a REPL that does not echo results, mishandles let bindings across lines, `_`, .help or .exit."""
    r = run(["repl"], input="1+1\nlet x = 5\nx*2\n_ + 1\n.help\nconsole.log('hi')\n.exit\nconsole.log('after exit')\n")
    assert_result(r, G / "repl_piped.golden")


def test_repl_multiline_and_errors(run):
    """CATCHES: a REPL without multi-line continuation, that dies on errors, or doesn't support top-level await."""
    src = ("function add(a, b) {\n  return a + b;\n}\nadd(2, 3)\nthrow new Error('oops')\n"
           "[1, 2,\n 3].length\nawait Promise.resolve(41 + 1)\n'str'\nundefinedName\n")
    r = run(["repl"], input=src)
    assert_result(r, G / "repl_multiline.golden")


def test_repl_word_only_as_first_argument(run, workdir):
    """CATCHES: treating 'repl' as a subcommand when it follows a script (it must reach process.argv)."""
    check_script(run, workdir, G, "repl_as_arg", "console.log(process.argv.slice(2).join('|'));\n",
                 args=["repl", "x"])


def test_script_named_repl_file(run, workdir):
    """CATCHES: matching 'repl' as a prefix; a script file called repl.js must run normally."""
    (workdir / "repl.js").write_text("console.log('a file named repl.js')\n")
    r = run(["repl.js"])
    assert r.stdout == b"a file named repl.js\n"
    assert r.stderr == b""
    assert r.returncode == 0


def test_module_kind_selection(run, workdir):
    """CATCHES: choosing ESM vs CommonJS by something other than the extension and the nearest
    package.json "type" field."""
    write_files(workdir, {
        "plain.js": "console.log('plain', typeof require, typeof module);\n",
        "esm.mjs": "console.log('mjs', typeof require, typeof module);\n",
        "cjs.cjs": "console.log('cjs', typeof require, typeof module);\n",
        "modpkg/package.json": '{ "name": "x", "type" : "module" }',
        "modpkg/sub/deep.js": "console.log('deep in type=module', typeof require, typeof module);\n",
        "modpkg/sub/legacy.cjs": "console.log('cjs inside type=module', typeof require);\n",
        "cjspkg/package.json": '{"type": "commonjs"}',
        "cjspkg/x.js": "console.log('type=commonjs', typeof require);\n",
        "cjspkg/y.mjs": "console.log('mjs inside commonjs', typeof require);\n",
    })
    outs = [run([p]) for p in ["plain.js", "esm.mjs", "cjs.cjs", "modpkg/sub/deep.js", "modpkg/sub/legacy.cjs",
                               "cjspkg/x.js", "cjspkg/y.mjs"]]
    joined = b"".join(o.stdout for o in outs)
    assert [o.returncode for o in outs] == [0] * 7
    assert b"".join(o.stderr for o in outs) == b""
    assert joined == (b"plain function object\nmjs function undefined\ncjs function object\n"
                      b"deep in type=module function undefined\ncjs inside type=module function\n"
                      b"type=commonjs function\nmjs inside commonjs function\n")
