"""Failure paths across commands: lowering errors and unfilled holes at compile time,
unwritable outputs, missing interpreters, `uv` as the installer, and REPL/kernel
sessions whose Python worker misbehaves."""

from conftest import case_transcript, golden_name, listing, read_golden, run_case

# A guard that needs statements passes the checker but cannot be lowered.
GUARD = (
    "let f n =\n"
    "  match n:\n"
    "    case x if (match x:\n"
    "        case 0: true\n"
    "        case _: false): \"zero\"\n"
    "    case _: \"other\"\n"
)
LOWER_FAIL_PROJECT = {"rules.pyfun": GUARD, "main.pyfun": "import Rules\nprint (Rules.f 0)\n"}
SIMPLE_PROJECT = {"calc.pyfun": "let double x = x * 2\n", "main.pyfun": "import Calc\nprint (Calc.double 21)\n"}

FAKE_MYPYC = (
    "#!/bin/sh\n"
    "for a in \"$@\"; do case \"$a\" in *.py) : > \"${a%.py}.fake-ext\" ;; esac; done\n"
    "echo \"[mypyc] $#\" >&2\n"
    "exit 0\n"
)


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert case_transcript(proc, case, workdir) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


# ---------------------------------------------------------------- lowering failures in a project

LOWER_COMPILE_CASE = {"id": "project_lowering_failure_compile", "files": LOWER_FAIL_PROJECT,
                      "args": ["compile", "main.pyfun", "-o", "out"]}
LOWER_RUN_CASE = {"id": "project_lowering_failure_run", "files": LOWER_FAIL_PROJECT, "args": ["run", "main.pyfun"]}
LOWER_BUNDLE_CASE = {"id": "project_lowering_failure_bundle", "files": LOWER_FAIL_PROJECT,
                     "args": ["bundle", "main.pyfun", "-o", "site"]}
LOWER_BUILD_CASE = {"id": "project_lowering_failure_build", "files": LOWER_FAIL_PROJECT,
                    "args": ["build", "--native", "main.pyfun", "-o", "native"]}
SINGLE_LOWER_BUILD_CASE = {"id": "single_lowering_failure_build", "files": {"rules.pyfun": GUARD},
                           "args": ["build", "--native", "rules.pyfun", "-o", "native"]}
SINGLE_LOWER_BUNDLE_CASE = {"id": "single_lowering_failure_bundle", "files": {"rules.pyfun": GUARD},
                            "args": ["bundle", "rules.pyfun", "-o", "site"]}


def test_project_compile_reports_a_lowering_failure(run, workdir):
    """CATCHES: a project compile that type-checks, then crashes or writes a partial tree when
    a module cannot be lowered, instead of "error: lowering failed: ..."."""
    _check(run, workdir, LOWER_COMPILE_CASE)
    assert listing(workdir) == "main.pyfun\nrules.pyfun\n"


def test_project_run_reports_a_lowering_failure(run, workdir):
    """CATCHES: a project run that executes anything after a lowering failure."""
    _check(run, workdir, LOWER_RUN_CASE)


def test_project_bundle_reports_a_lowering_failure(run, workdir):
    """CATCHES: a project bundle written despite a lowering failure."""
    _check(run, workdir, LOWER_BUNDLE_CASE)
    assert listing(workdir) == "main.pyfun\nrules.pyfun\n"


def test_project_build_reports_a_lowering_failure(run, workdir):
    """CATCHES: a native project build that invokes mypyc after a lowering failure."""
    _check(run, workdir, LOWER_BUILD_CASE)


def test_single_file_build_reports_a_lowering_failure(run, workdir):
    """CATCHES: a single-file native build that does not render the lowering error."""
    _check(run, workdir, SINGLE_LOWER_BUILD_CASE)


def test_single_file_bundle_reports_a_lowering_failure(run, workdir):
    """CATCHES: a single-file bundle that does not render the lowering error."""
    _check(run, workdir, SINGLE_LOWER_BUNDLE_CASE)


# ---------------------------------------------------------------- unfilled holes

HOLE = "let total xs = List.fold (+) 0 xs\nlet n = total ?\nprint n\n"
HOLE_COMPILE_CASE = {"id": "hole_blocks_compile", "files": {"h.pyfun": HOLE}, "args": ["compile", "h.pyfun"]}
HOLE_RUN_CASE = {"id": "hole_blocks_run", "files": {"h.pyfun": HOLE}, "args": ["run", "h.pyfun"]}
HOLE_CHECK_CASE = {"id": "hole_is_a_note_in_check", "files": {"h.pyfun": HOLE}, "args": ["check", "h.pyfun"]}


def test_compile_refuses_an_unfilled_hole(run, workdir):
    """CATCHES: emitting Python for a program that still contains a typed hole `?`, or not
    showing the hole's type and suggested fills."""
    _check(run, workdir, HOLE_COMPILE_CASE)


def test_run_refuses_an_unfilled_hole(run, workdir):
    """CATCHES: running a program that still contains a typed hole."""
    _check(run, workdir, HOLE_RUN_CASE)


def test_check_reports_a_hole_as_a_note(run, workdir):
    """CATCHES: reporting a hole as an error (or exiting 0) instead of a note plus the
    "1 unfilled hole" summary."""
    _check(run, workdir, HOLE_CHECK_CASE)


# ---------------------------------------------------------------- outputs that cannot be written

UNWRITABLE_CASES = [
    {"id": "project_output_file_is_a_directory", "files": {**SIMPLE_PROJECT, "out/main.py/keep": ""},
     "args": ["compile", "main.pyfun", "-o", "out"]},
    {"id": "bundle_module_is_a_directory", "files": {"hello.pyfun": "print 1\n", "site/main.py/keep": ""},
     "args": ["bundle", "hello.pyfun", "-o", "site"]},
    {"id": "bundle_index_is_a_directory", "files": {"hello.pyfun": "print 1\n", "site/index.html/keep": ""},
     "args": ["bundle", "hello.pyfun", "-o", "site"]},
    {"id": "build_source_is_a_directory", "files": {"hello.pyfun": "print 1\n", "native/hello.py/keep": ""},
     "args": ["build", "--native", "hello.pyfun", "-o", "native"]},
    {"id": "build_project_module_is_a_directory", "files": {**SIMPLE_PROJECT, "native/calc.py/keep": ""},
     "args": ["build", "--native", "main.pyfun", "-o", "native"]},
    {"id": "build_project_out_is_a_file", "files": {**SIMPLE_PROJECT, "native": "occupied\n"},
     "args": ["build", "--native", "main.pyfun", "-o", "native"]},
    {"id": "build_main_is_a_directory",
     "files": {"hello.pyfun": "print 1\n", "native/__main__.py/keep": "", "tools/python": FAKE_MYPYC},
     "executables": ["tools/python"], "env": {"PYFUN_PYTHON": "{workdir}/tools/python"},
     "args": ["build", "--native", "hello.pyfun", "-o", "native"]},
]


def test_project_compile_into_an_occupied_file_name(run, workdir):
    """CATCHES: a project `-o` that reports success although `main.py` could not be written."""
    _check(run, workdir, UNWRITABLE_CASES[0])


def test_bundle_module_that_cannot_be_written(run, workdir):
    """CATCHES: a bundle that ignores a failed write of the compiled module."""
    _check(run, workdir, UNWRITABLE_CASES[1])


def test_bundle_page_that_cannot_be_written(run, workdir):
    """CATCHES: a bundle that ignores a failed write of `index.html`."""
    _check(run, workdir, UNWRITABLE_CASES[2])


def test_build_source_that_cannot_be_written(run, workdir):
    """CATCHES: a native build that goes on to mypyc although its `.py` could not be written."""
    _check(run, workdir, UNWRITABLE_CASES[3])


def test_build_project_module_that_cannot_be_written(run, workdir):
    """CATCHES: a native project build that ignores a failed module write."""
    _check(run, workdir, UNWRITABLE_CASES[4])


def test_build_project_into_a_file(run, workdir):
    """CATCHES: a native project build whose output path is an existing file."""
    _check(run, workdir, UNWRITABLE_CASES[5])


def test_build_entry_point_that_cannot_be_written(run, workdir):
    """CATCHES: reporting a successful build although `__main__.py` could not be written."""
    _check(run, workdir, UNWRITABLE_CASES[6])


# ---------------------------------------------------------------- interpreters

INTERPRETER_CASES = [
    {"id": "project_run_without_python", "files": SIMPLE_PROJECT, "env": {"PATH": "{workdir}/no-bin"},
     "args": ["run", "main.pyfun"]},
    {"id": "project_run_unrunnable_interpreter", "files": SIMPLE_PROJECT,
     "env": {"PYFUN_PYTHON": "./missing-python"}, "args": ["run", "main.pyfun"]},
    {"id": "build_without_python", "files": {"hello.pyfun": "print 1\n"}, "env": {"PATH": "{workdir}/no-bin"},
     "args": ["build", "--native", "hello.pyfun", "-o", "native"], "outputs": ["native/hello.py"]},
    {"id": "build_unrunnable_interpreter", "files": {"hello.pyfun": "print 1\n"},
     "env": {"PYFUN_PYTHON": "./missing-python"}, "args": ["build", "--native", "hello.pyfun", "-o", "native"]},
]


def test_project_run_without_any_python(run, workdir):
    """CATCHES: a project run that crashes when no interpreter exists on PATH."""
    _check(run, workdir, INTERPRETER_CASES[0])


def test_project_run_with_an_unrunnable_interpreter(run, workdir):
    """CATCHES: a project run that hides why the interpreter could not be started."""
    _check(run, workdir, INTERPRETER_CASES[1])


def test_build_without_any_python(run, workdir):
    """CATCHES: a native build that does not tell the user to set PYFUN_PYTHON."""
    _check(run, workdir, INTERPRETER_CASES[2])


def test_build_with_an_unrunnable_interpreter(run, workdir):
    """CATCHES: a native build that reports a missing interpreter as a mypyc failure."""
    _check(run, workdir, INTERPRETER_CASES[3])


# ---------------------------------------------------------------- packages: uv and no python

FAKE_UV = (
    "#!/bin/sh\n"
    "# Logs its arguments, with absolute paths shortened to <dir>/name (they live in a temp dir).\n"
    "out=\"\"\n"
    "for a in \"$@\"; do case \"$a\" in /*) a=\"<dir>/${a##*/}\" ;; esac; out=\"$out $a\"; done\n"
    "echo \"[uv]$out\" >&2\n"
    "exit 0\n"
)
FAKE_META = (
    "#!/bin/sh\n"
    "if [ \"$1\" = \"-c\" ]; then echo 1.2.0; echo \"${0%/*}/../site/tool.pyfun\"; exit 0; fi\n"
    "echo \"[python] $*\" >&2\n"
)
PKG_FILES = {"bin/uv": FAKE_UV, "tools/python": FAKE_META, "site/tool.pyfun": "let ping = \"pong\"\n",
             "pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\nold-dep = \"0.1\"\n"}
PKG_ENV = {"PATH": "{workdir}/bin", "PYFUN_PYTHON": "{workdir}/tools/python"}
UV_ADD_CASE = {"id": "add_uses_uv_when_present", "files": PKG_FILES, "executables": ["bin/uv", "tools/python"],
               "env": PKG_ENV, "args": ["add", "pyfun-tool"], "outputs": ["pyfun.toml"]}
UV_REMOVE_CASE = {"id": "remove_uses_uv_when_present", "files": PKG_FILES, "executables": ["bin/uv", "tools/python"],
                  "env": PKG_ENV, "args": ["remove", "old-dep"], "outputs": ["pyfun.toml"]}
REMOVE_NO_PYTHON_CASE = {"id": "remove_without_python_skips_uninstall", "files": PKG_FILES,
                         "env": {"PATH": "{workdir}/no-bin"}, "args": ["remove", "old-dep"], "outputs": ["pyfun.toml"]}
ADD_NO_INSTALLER_CASE = {"id": "add_installer_cannot_run", "files": PKG_FILES,
                         "env": {"PATH": "{workdir}/no-bin", "PYFUN_PYTHON": "./missing-python"},
                         "args": ["add", "pyfun-tool"], "outputs": ["pyfun.toml"]}
MANIFEST_WITHOUT_FACADES_CASE = {
    "id": "manifest_without_facades_dir",
    "files": {"pyfun.toml": "[project]\nname = \"demo\"\n", "main.pyfun": "import Tool\nprint Tool.ping\n"},
    "args": ["check", "main.pyfun"],
}


def test_add_installs_with_uv_when_it_is_on_path(run, workdir):
    """CATCHES: ignoring `uv` (which must be preferred, pointed at the chosen interpreter
    with `--python`) and calling `python -m pip` instead."""
    _check(run, workdir, UV_ADD_CASE)


def test_remove_uninstalls_with_uv_when_it_is_on_path(run, workdir):
    """CATCHES: `remove` uninstalling with pip when `uv` is available."""
    _check(run, workdir, UV_REMOVE_CASE)


def test_remove_without_python_still_updates_the_manifest(run, workdir):
    """CATCHES: `remove` failing (or leaving the manifest unchanged) when no interpreter is
    available to uninstall with."""
    _check(run, workdir, REMOVE_NO_PYTHON_CASE)


def test_add_reports_an_installer_that_cannot_run(run, workdir):
    """CATCHES: an `add` that crashes or records the dependency when the installer cannot start."""
    _check(run, workdir, ADD_NO_INSTALLER_CASE)


def test_a_manifest_without_vendored_facades(run, workdir):
    """CATCHES: a crash when `pyfun.toml` exists but `.pyfun/facades` does not."""
    _check(run, workdir, MANIFEST_WITHOUT_FACADES_CASE)


# ---------------------------------------------------------------- REPL: compile-time and worker failures

STALL_PYTHON = (
    "#!/bin/sh\n"
    "# Answers --version, then reads one framed request and exits without replying.\n"
    "if [ \"$1\" = \"--version\" ]; then echo \"Python 3\"; exit 0; fi\n"
    "exec python3 -c 'import sys\n"
    "h = sys.stdin.buffer.read(8)\n"
    "if len(h) == 8:\n"
    "    sys.stdin.buffer.read(int(h))\n"
    "'\n"
)
OS_EXTERNS = (
    "extern import os.path\n"
    "extern exists : string -> bool = os.path.exists\n"
    "extern mkdir : string -> unit = os.mkdir\n"
    "extern die : int -> unit = os._exit\n"
)
REPL_HOLE_CASE = {"id": "repl_holes_and_lowering_errors", "args": ["repl"], "stdin": (
    "let x = ?\nlet y = 1\nlet y = 1\ny + ?\n:{\n" + GUARD + ":}\nf 0\n:quit\n")}
REPL_BAD_UTF8_CASE = {"id": "repl_invalid_utf8_input", "args": ["repl"], "stdin": b"let a = 1\n\xff\n2\n"}
REPL_BAD_UTF8_BLOCK_CASE = {"id": "repl_invalid_utf8_in_block", "args": ["repl"], "stdin": b":{\nlet a = 1\n\xff\n2\n"}
REPL_NO_WORKER_CASE = {"id": "repl_worker_cannot_start", "files": {"fake/python": STALL_PYTHON},
                       "executables": ["fake/python"], "env": {"PATH": "{workdir}/fake:{PATH}"},
                       "args": ["repl"], "stdin": "1 + 1\nlet a = 2\na\n:quit\n"}
REPL_REBUILD_FAILS_CASE = {"id": "repl_rebuild_fails", "args": ["repl"], "stdin": (
    OS_EXTERNS
    + ":{\nlet dieIfSeen p =\n  if exists p then\n    let _ = die 3\n    0\n  else\n    let _ = mkdir p\n    1\n:}\n"
    + "let k = dieIfSeen \"seen\"\nk + 1\ndie 1\n:quit\n")}
REPL_RETRY_SUCCEEDS_CASE = {"id": "repl_retry_after_restart", "args": ["repl"], "stdin": (
    OS_EXTERNS + "let base = 10\n"
    + ":{\nlet once p =\n  if exists p then 1\n  else\n    let _ = mkdir p\n    let _ = die 3\n    0\n:}\n"
    + "base + once \"flag\"\nbase * 2\n:quit\n")}


def test_repl_reports_holes_and_lowering_errors(run, workdir):
    """CATCHES: a REPL that commits a definition containing a hole, re-runs an unchanged
    duplicate definition, or crashes on a lowering error instead of rendering it."""
    _check(run, workdir, REPL_HOLE_CASE)


def test_repl_stops_on_invalid_utf8_input(run, workdir):
    """CATCHES: a REPL that panics, loops, or silently skips a line that is not UTF-8."""
    _check(run, workdir, REPL_BAD_UTF8_CASE)


def test_repl_block_ends_on_invalid_utf8_input(run, workdir):
    """CATCHES: an unreadable line inside `:{` that is not treated as the end of the block."""
    _check(run, workdir, REPL_BAD_UTF8_BLOCK_CASE)


def test_repl_reports_a_worker_that_cannot_start(run, workdir):
    """CATCHES: a REPL that hangs, or does not report "cannot start python worker", when its
    interpreter accepts a request but never answers."""
    _check(run, workdir, REPL_NO_WORKER_CASE)


def test_repl_reports_a_failed_rebuild(run, workdir):
    """CATCHES: a REPL that hangs or loops when re-running the definitions after a worker
    death kills the new worker too."""
    _check(run, workdir, REPL_REBUILD_FAILS_CASE)
    assert listing(workdir) == "seen/\n"


def test_repl_retries_the_entry_after_a_restart(run, workdir):
    """CATCHES: dropping the entry that killed the worker instead of retrying it once against
    the rebuilt namespace."""
    _check(run, workdir, REPL_RETRY_SUCCEEDS_CASE)
    assert listing(workdir) == "flag/\n"


# ---------------------------------------------------------------- kernel engine: compile-time failures

def _frame(text):
    return f"{len(text.encode('utf-8')):08}{text}"


KERNEL_CASE = {"id": "kernel_holes_and_lowering_errors", "args": ["kernel-engine"], "stdin": "".join(
    _frame(op) + _frame(payload) for op, payload in [
        ("eval", "let x = ?"), ("eval", "let y = 2"), ("eval", "y + ?"), ("eval", GUARD), ("eval", "y")])}


def test_kernel_reports_holes_and_lowering_errors(run, workdir):
    """CATCHES: an engine that returns a blob (status ok) for a cell with an unfilled hole or a
    lowering error, or commits such a definition."""
    _check(run, workdir, KERNEL_CASE)
