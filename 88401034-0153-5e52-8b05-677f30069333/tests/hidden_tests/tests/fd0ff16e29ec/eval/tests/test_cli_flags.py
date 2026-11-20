"""Command-line options: -e, --tier=, the repl keyword, script arguments and argument parsing order."""

from conftest import write_files

ARGS_SCRIPT = "console.log('script ran:', JSON.stringify(process.argv.slice(2)));\n"


def test_eval_short_prints(run):
    """CATCHES: a -e that does not evaluate its argument or that buffers console output incorrectly."""
    r = run(["-e", "console.log('hello', 1 + 2)"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"hello 3\n", b"")


def test_eval_missing_code(run):
    """CATCHES: a -e with no following argument that silently succeeds, opens the REPL or uses a different message/exit code."""
    r = run(["-e"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"-e expects code\n")


def test_last_eval_wins(run):
    """CATCHES: implementations that concatenate or run every -e instead of keeping only the last one."""
    r = run(["-e", "console.log('first')", "-e", "console.log('second')"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"second\n", b"")


def test_eval_takes_dash_prefixed_code(run):
    """CATCHES: parsers that treat a code argument beginning with '-' as another option instead of the -e value."""
    r = run(["-e", "-1 < 0 && console.log('negated literal ok')"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"negated literal ok\n", b"")


def test_eval_beats_file_argument(run, workdir):
    """CATCHES: implementations that run the script file when -e code was also given (eval takes priority)."""
    write_files(workdir, {"f.js": "console.log('file ran')\n"})
    r = run(["-e", "console.log('eval ran')", "f.js"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"eval ran\n", b"")


def test_eval_beats_file_even_if_file_missing(run):
    """CATCHES: implementations that validate the free script argument even though -e code takes priority."""
    r = run(["-e", "console.log('eval ran')", "missing.js"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"eval ran\n", b"")


def test_eval_beats_repl_keyword(run):
    """CATCHES: implementations that open the REPL when both -e and 'repl' are given (eval takes priority)."""
    r = run(["-e", "console.log('eval ran')", "repl"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"eval ran\n", b"")


def test_tier_interp(run):
    """CATCHES: implementations that reject --tier=interp or change program output under the tree-walking tier."""
    r = run(["--tier=interp", "-e", "let s = 0; for (let i = 0; i < 100; i++) s += i; console.log(s)"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"4950\n", b"")


def test_tier_bytecode(run):
    """CATCHES: implementations that reject --tier=bytecode or change program output under the bytecode VM."""
    r = run(["--tier=bytecode", "-e", "function f(n) { return n < 2 ? n : f(n - 1) + f(n - 2) } console.log(f(15))"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"610\n", b"")


def test_tier_after_eval(run):
    """CATCHES: parsers that stop option parsing after -e; a later --tier is still an option."""
    r = run(["-e", "console.log('ok')", "--tier=interp"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"ok\n", b"")


def test_tier_jit_is_rejected(run):
    """CATCHES: implementations that accept --tier=jit; the CLI only knows interp and bytecode and exits 2."""
    r = run(["--tier=jit", "-e", "console.log('ran')"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"unknown tier 'jit' (interp|bytecode)\n")


def test_tier_unknown_value(run):
    """CATCHES: an unknown tier value that is silently ignored or reported with a different message/exit code."""
    r = run(["--tier=fast", "-e", "console.log('ran')"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"unknown tier 'fast' (interp|bytecode)\n")


def test_tier_empty_value(run):
    """CATCHES: '--tier=' with an empty value being accepted instead of reported as unknown tier ''."""
    r = run(["--tier=", "-e", "1"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"unknown tier '' (interp|bytecode)\n")


def test_tier_is_case_sensitive(run):
    """CATCHES: tier names matched case-insensitively; 'INTERP' is an unknown tier."""
    r = run(["--tier=INTERP", "-e", "1"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"unknown tier 'INTERP' (interp|bytecode)\n")


def test_tier_separate_value_is_not_supported(run):
    """CATCHES: implementations that accept '--tier interp' as two words; only --tier=VALUE is an option, so '--tier' is a script path."""
    r = run(["--tier", "interp", "-e", "1"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read --tier: not a file\n")


def test_last_tier_wins(run):
    """CATCHES: implementations that keep the first --tier instead of the last valid one, or that reject repeats."""
    r = run(["--tier=bytecode", "--tier=interp", "-e", "console.log('ok')"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"ok\n", b"")


def test_invalid_tier_after_valid_one(run):
    """CATCHES: implementations that only validate the first --tier occurrence."""
    r = run(["--tier=interp", "--tier=vm", "-e", "1"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"unknown tier 'vm' (interp|bytecode)\n")


def test_unknown_dash_option_is_a_path(run):
    """CATCHES: implementations that print an 'unknown option' error; an unrecognised -x is taken as the script path."""
    r = run(["-x"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read -x: not a file\n")


def test_unknown_long_option_is_a_path(run):
    """CATCHES: implementations that reject --inspect style flags differently than as a missing script file."""
    r = run(["--inspect", "-e", "1"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read --inspect: not a file\n")


def test_double_dash_is_a_path(run):
    """CATCHES: implementations that treat '--' as an end-of-options marker; here it is a (missing) script path."""
    r = run(["--", "f.js"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read --: not a file\n")


def test_empty_argument_is_a_path(run):
    """CATCHES: implementations that skip empty arguments instead of reporting them as an unreadable script."""
    r = run([""])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read : not a file\n")


def test_missing_script(run):
    """CATCHES: a missing script file reported with the wrong message, on stdout, or with an exit code other than 2."""
    r = run(["does-not-exist.js"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read does-not-exist.js: not a file\n")


def test_directory_as_script(run, workdir):
    """CATCHES: implementations that try to run a directory (index.js lookup) instead of rejecting it as not a file."""
    write_files(workdir, {"pkg/index.js": "console.log('index ran')\n"})
    r = run(["pkg"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read pkg: not a file\n")


def test_dot_directory_as_script(run):
    """CATCHES: '.' accepted as a runnable path instead of 'cannot read .: not a file'."""
    r = run(["."])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"cannot read .: not a file\n")


def test_script_args_are_passed_through(run, workdir):
    """CATCHES: implementations that interpret arguments after the script (-e, --tier=bad, repl) instead of passing them to it."""
    write_files(workdir, {"f.js": ARGS_SCRIPT})
    r = run(["f.js", "-e", "x", "--tier=bad", "repl", "-e"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == b'script ran: ["-e","x","--tier=bad","repl","-e"]\n'


def test_tier_before_script_appears_in_argv(run, workdir):
    """CATCHES: implementations that strip runtime options from process.argv (they stay, as raw arguments)."""
    write_files(workdir, {"f.js": ARGS_SCRIPT})
    r = run(["--tier=interp", "f.js", "a", "b"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b'script ran: ["f.js","a","b"]\n', b"")


def test_repl_keyword_before_script_runs_script(run, workdir):
    """CATCHES: implementations that open the REPL when 'repl' precedes a script; the script still runs."""
    write_files(workdir, {"f.js": ARGS_SCRIPT})
    r = run(["repl", "f.js", "z"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b'script ran: ["f.js","z"]\n', b"")


def test_script_named_like_option_value(run, workdir):
    """CATCHES: implementations that treat a file literally named 'repl' as the repl keyword after another script."""
    write_files(workdir, {"main.js": ARGS_SCRIPT})
    r = run(["main.js", "repl"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b'script ran: ["repl"]\n', b"")


def test_script_path_with_subdirectory(run, workdir):
    """CATCHES: implementations that only resolve scripts in the current directory."""
    write_files(workdir, {"a/b/c.js": "console.log('nested', require('path').basename(__filename))\n"})
    r = run(["a/b/c.js"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"nested c.js\n", b"")


def test_script_without_extension(run, workdir):
    """CATCHES: implementations that require a .js extension; an extensionless file runs as CommonJS."""
    write_files(workdir, {"tool": "console.log(typeof module, typeof require)\n"})
    r = run(["tool"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b"object function\n", b"")


def test_no_args_reads_program_from_stdin(run):
    """CATCHES: implementations that open an interactive REPL (prompts, result echo) for piped stdin instead of evaluating it."""
    r = run([], input="const a = [3, 1, 2].sort();\nconsole.log(a.join(','));\na.length\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"1,2,3\n", b"")


def test_tier_only_reads_stdin(run):
    """CATCHES: implementations that need a script/-e once a --tier option is present; stdin is still the program."""
    r = run(["--tier=bytecode"], input="console.log('from stdin')\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"from stdin\n", b"")


def test_bad_tier_reported_before_missing_script(run):
    """CATCHES: implementations that check the script path before validating an earlier --tier option."""
    r = run(["--tier=bogus", "nonexistent.js"])
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", b"unknown tier 'bogus' (interp|bytecode)\n")


def test_eval_empty_string_is_a_no_op(run):
    """CATCHES: an empty -e program that is rejected or that falls back to reading stdin / the REPL, while a non-empty one still runs."""
    empty = run(["-e", ""], input="console.log('stdin must not be read')\n")
    assert (empty.returncode, empty.stdout, empty.stderr) == (0, b"", b"")
    full = run(["-e", "console.log('non-empty')"], input="console.log('stdin must not be read')\n")
    assert (full.returncode, full.stdout, full.stderr) == (0, b"non-empty\n", b"")


def test_eval_sees_raw_argv(run):
    """CATCHES: a process.argv that drops the option words; it must contain every raw argument after argv[0]."""
    r = run(["-e", "console.log(JSON.stringify(process.argv.slice(1)))", "x", "y"])
    assert (r.returncode, r.stdout, r.stderr) == (0, b'["-e","console.log(JSON.stringify(process.argv.slice(1)))","x","y"]\n', b"")


def test_no_args_stdin_comment_only_program(run):
    """CATCHES: implementations that echo piped stdin or print a REPL banner/prompt instead of evaluating it (a comment-only program prints nothing)."""
    r = run([], input="// just a comment\n/* and a block */\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    r2 = run([], input="// comment\nconsole.log('evaluated')\n")
    assert (r2.returncode, r2.stdout, r2.stderr) == (0, b"evaluated\n", b"")


def test_eval_consumes_keyword_and_option_words(run):
    """CATCHES: parsers that let the word after -e be re-interpreted as the repl keyword, a --tier option or another -e."""
    r = run(["-e", "repl"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"Uncaught ReferenceError: repl is not defined\n")
    r = run(["-e", "--tier=bogus"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"SyntaxError: invalid assignment target (line 1)\n")
    r = run(["-e", "-e"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"Uncaught ReferenceError: e is not defined\n")


def test_repl_keyword_then_options(run):
    """CATCHES: parsers that stop at the repl keyword; later --tier options still apply and a repeated keyword is harmless."""
    r = run(["repl", "--tier=interp", "repl"], input="[1, 2].length\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"lumen 0.1.3 (.help for help, .exit or Ctrl-D to quit)\n> 2\n> \n", b"")


def test_repl_keyword_then_eval(run):
    """CATCHES: implementations where a 'repl' keyword before -e opens the REPL instead of evaluating the code."""
    r = run(["repl", "-e", "console.log('eval wins')"], input="console.log('stdin ignored')\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"eval wins\n", b"")
