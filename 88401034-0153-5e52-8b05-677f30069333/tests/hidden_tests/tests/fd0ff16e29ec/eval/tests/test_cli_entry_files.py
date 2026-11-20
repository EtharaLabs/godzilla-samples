"""Entry-file edge cases (paths, symlinks, encodings, hashbangs, extensions) and terminal-vs-pipe stdin handling."""

from conftest import write_files

BANNER = b"lumen 0.1.3 (.help for help, .exit or Ctrl-D to quit)\n"
HASHBANG = "#!/usr/bin/env lumen-cli\nconsole.log('hashbang ok', require('path').basename(__filename));\n"


def _res(r):
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------- terminal stdin

def test_terminal_stdin_starts_repl(tty_run):
    """CATCHES: implementations that do not open the REPL (banner, prompts, echoing results) when stdin is a terminal and no script is given."""
    r = tty_run([], input=b"1 + 1\n'x'\n\x04")
    assert _res(r) == (0, BANNER + b"> 2\n> 'x'\n> \n", b"")


def test_terminal_repl_continuation_and_exit(tty_run):
    """CATCHES: a terminal REPL that lacks multi-line continuation or keeps running after .exit."""
    r = tty_run([], input=b"function f() {\nreturn 3 }\nf()\n.exit\n")
    assert _res(r) == (0, BANNER + b"> .. undefined\n> 3\n> ", b"")


def test_terminal_repl_with_tier_option(tty_run):
    """CATCHES: option parsing that disables terminal REPL detection once a --tier option is present."""
    r = tty_run(["--tier=interp"], input=b"[1, 2].length\n\x04")
    assert _res(r) == (0, BANNER + b"> 2\n> \n", b"")


def test_terminal_ctrl_d_immediately(tty_run):
    """CATCHES: a terminal REPL that does not end cleanly (newline, exit 0) on an immediate end of input."""
    r = tty_run([], input=b"\x04")
    assert _res(r) == (0, BANNER + b"> \n", b"")


def test_terminal_stdin_with_eval_does_not_open_repl(tty_run):
    """CATCHES: implementations that open the REPL whenever stdin is a terminal, even with -e code."""
    r = tty_run(["-e", "console.log('eval only', typeof process.stdin)"], input=b"\x04")
    assert _res(r) == (0, b"eval only object\n", b"")


def test_terminal_stdin_with_script_does_not_open_repl(tty_run, workdir):
    """CATCHES: implementations that open the REPL whenever stdin is a terminal, even when a script is given."""
    write_files(workdir, {"s.js": "console.log('script only')\n"})
    r = tty_run(["s.js"], input=b"\x04")
    assert _res(r) == (0, b"script only\n", b"")


# ---------------------------------------------------------------- what -e / stdin programs see

def test_eval_program_scope(run):
    """CATCHES: -e programs run as CommonJS modules or ES modules; they are global scripts with a global require only."""
    r = run(["-e", "console.log(typeof require, typeof module, typeof __filename, typeof exports, this === globalThis);"
                   "var declared = 1; console.log(globalThis.declared, typeof require('node:path').join)"])
    assert _res(r) == (0, b"function undefined undefined undefined true\n1 function\n", b"")


def test_eval_rejects_import_meta(run):
    """CATCHES: -e programs parsed as modules (import.meta must be a SyntaxError in a script)."""
    r = run(["-e", "console.log(import.meta.url)"])
    assert _res(r) == (1, b"", b"SyntaxError: 'import.meta' is only valid in a module (line 1)\n")


def test_eval_and_stdin_dynamic_import_unsupported(run, workdir):
    """CATCHES: -e/stdin programs that can import() files; without an entry file there is no module loader (the rejection is reported, exit 0)."""
    write_files(workdir, {"m.mjs": "export const x = 1;\n"})
    r = run(["-e", "import('./m.mjs').then(() => console.log('loaded'))"])
    assert _res(r) == (0, b"", b"Uncaught (in promise) TypeError: no module loader configured\n")
    r2 = run([], input="import('./m.mjs').catch(e => console.log('caught', e.message))\n")
    assert _res(r2) == (0, b"caught no module loader configured\n", b"")


def test_stdin_program_argv(run):
    """CATCHES: process.argv for stdin programs including a phantom script name; it is just the executable plus raw options."""
    r = run([], input="console.log(process.argv.length, JSON.stringify(process.argv.slice(1)))\n")
    assert _res(r) == (0, b"1 []\n", b"")
    r2 = run(["--tier=interp"], input="console.log(process.argv.length, JSON.stringify(process.argv.slice(1)))\n")
    assert _res(r2) == (0, b'2 ["--tier=interp"]\n', b"")


def test_repl_program_argv(run):
    """CATCHES: the REPL hiding its own 'repl' keyword from process.argv."""
    r = run(["repl"], input="JSON.stringify(process.argv.slice(1))\n")
    assert _res(r) == (0, BANNER + b"> '[\"repl\"]'\n> \n", b"")


# ---------------------------------------------------------------- script paths

def test_absolute_script_path(run, workdir):
    """CATCHES: implementations that only accept relative script paths."""
    write_files(workdir, {"abs.js": HASHBANG})
    assert _res(run([str(workdir / "abs.js")])) == (0, b"hashbang ok abs.js\n", b"")


def test_dot_slash_and_spaces_in_path(run, workdir):
    """CATCHES: script paths with './' prefixes or spaces in directory and file names being mangled."""
    write_files(workdir, {"sp ace/x y.js": HASHBANG})
    assert _res(run(["./sp ace/x y.js"])) == (0, b"hashbang ok x y.js\n", b"")


def test_symlinked_script(run, workdir):
    """CATCHES: implementations that refuse symlinked scripts, do not resolve __filename to the link target, or accept links to directories / dangling links."""
    write_files(workdir, {"real.js": HASHBANG, "dir/keep": ""})
    (workdir / "link.js").symlink_to("real.js")
    (workdir / "dirlink").symlink_to("dir")
    (workdir / "dangling.js").symlink_to("nowhere.js")
    assert _res(run(["link.js"])) == (0, b"hashbang ok real.js\n", b"")
    assert _res(run(["dirlink"])) == (2, b"", b"cannot read dirlink: not a file\n")
    assert _res(run(["dangling.js"])) == (2, b"", b"cannot read dangling.js: not a file\n")


# ---------------------------------------------------------------- file contents

def test_hashbang_line_in_scripts_and_modules(run, workdir):
    """CATCHES: a '#!' first line rejected as a syntax error in CommonJS or ES module entries."""
    write_files(workdir, {"hb.js": HASHBANG, "hb.mjs": "#!/usr/bin/env lumen-cli\nconsole.log('module hashbang ok', typeof module);\n"})
    assert _res(run(["hb.js"])) == (0, b"hashbang ok hb.js\n", b"")
    assert _res(run(["hb.mjs"])) == (0, b"module hashbang ok undefined\n", b"")


def test_utf8_bom_is_ignored(run, workdir):
    """CATCHES: a UTF-8 byte-order mark at the start of an entry file causing a syntax error."""
    write_files(workdir, {"bom.js": b"\xef\xbb\xbfconsole.log('bom ok cjs')\n", "bom.mjs": b"\xef\xbb\xbfconsole.log('bom ok esm')\n"})
    assert _res(run(["bom.js"])) == (0, b"bom ok cjs\n", b"")
    assert _res(run(["bom.mjs"])) == (0, b"bom ok esm\n", b"")


def test_invalid_utf8_entry_files(run, workdir):
    """CATCHES: entry files with invalid UTF-8 being decoded lossily instead of failing with the exact read errors (CJS names the absolute path)."""
    write_files(workdir, {"bad.js": b"\xff\xfeconsole.log(1)\n", "bad.mjs": b"\xff\xfeconsole.log(1)\n"})
    r = run(["bad.js"])
    assert (r.returncode, r.stdout) == (1, b"")
    assert r.stderr.replace(str(workdir.resolve()).encode(), b"<WORKDIR>") == (
        b"Uncaught Error: cannot read '<WORKDIR>/bad.js': stream did not contain valid UTF-8\n")
    assert _res(run(["bad.mjs"])) == (1, b"", b"Uncaught cannot read bad.mjs: stream did not contain valid UTF-8\n")


def test_empty_entry_files(run, workdir):
    """CATCHES: empty entry files rejected, or treated differently between CommonJS and ESM, while a sibling script still runs."""
    write_files(workdir, {"empty.js": "", "empty.mjs": "", "next.js": "require('./empty.js'); console.log('required empty ok')\n"})
    assert _res(run(["empty.js"])) == (0, b"", b"")
    assert _res(run(["empty.mjs"])) == (0, b"", b"")
    assert _res(run(["next.js"])) == (0, b"required empty ok\n", b"")


def test_import_statement_in_cjs_entry(run, workdir):
    """CATCHES: .cjs entries parsed as modules (a static import declaration must be a syntax error there)."""
    write_files(workdir, {"imp.cjs": "import x from './d.json';\nconsole.log(x);\n", "d.json": "{}"})
    assert _res(run(["imp.cjs"])) == (1, b"", b"Uncaught SyntaxError: expected '('\n")


def test_mts_entry_is_esm_without_type_stripping(run, workdir):
    """CATCHES: .mts entries run as CommonJS, or type-stripped (the reference runs them as plain ES modules)."""
    write_files(workdir, {"plain.mts": "console.log('mts', typeof module);\n", "typed.mts": "const n: number = 1;\nconsole.log(n);\n"})
    assert _res(run(["plain.mts"])) == (0, b"mts undefined\n", b"")
    assert _res(run(["typed.mts"])) == (1, b"", b"Uncaught SyntaxError: missing initializer in const declaration\n")


def test_json_entry_file(run, workdir):
    """CATCHES: a .json entry that is printed or rejected; it is loaded through require (parsed, no output)."""
    write_files(workdir, {"d.json": '{"a": 1}', "bad.json": "{oops"})
    assert _res(run(["d.json"])) == (0, b"", b"")
    assert _res(run(["bad.json"])) == (1, b"", b"Uncaught SyntaxError: Expected string key in JSON object\n")
