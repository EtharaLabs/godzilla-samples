"""Multi-module projects driven from the command line: graph errors, `-o <dir>` trees,
façade resolution, and the run/check/compile commands over an import graph."""

from conftest import case_transcript, golden_name, listing, read_golden, resources_for, run_case

GEOMETRY = (
    "## Geometry helpers shared by the app.\n"
    "type Shape = Circle float | Rect float float\n"
    "\n"
    "let area s =\n"
    "  match s:\n"
    "    case Circle r: 3.0 * r * r\n"
    "    case Rect w h: w * h\n"
    "\n"
    "let biggest shapes = List.fold (fun acc s -> max acc (area s)) 0.0 shapes\n"
)
STORE = (
    "import Geometry\n"
    "\n"
    "type Item = { name: string, shape: Geometry.Shape }\n"
    "\n"
    "let find name items = List.find (fun i -> i.name == name) items\n"
)
MAIN = (
    "import Geometry\n"
    "import Store\n"
    "\n"
    "let items = [\n"
    "  Store.Item { name = \"disc\", shape = Geometry.Circle 1.0 },\n"
    "  Store.Item { name = \"tile\", shape = Geometry.Rect 2.0 3.0 },\n"
    "]\n"
    "\n"
    "let report name =\n"
    "  match Store.find name items:\n"
    "    case Some item: f\"{item.name}: {Geometry.area item.shape}\"\n"
    "    case None: f\"{name}: missing\"\n"
    "\n"
    "print (report \"disc\")\n"
    "print (report \"tile\")\n"
    "print (report \"cone\")\n"
    "print (Geometry.biggest (List.map (fun i -> i.shape) items))\n"
)
APP = {"geometry.pyfun": GEOMETRY, "store.pyfun": STORE, "main.pyfun": MAIN}


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert case_transcript(proc, case) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


# ---------------------------------------------------------------- the happy paths

CHECK_OK_CASE = {"id": "check_ok_counts_modules", "files": APP, "args": ["check", "main.pyfun"]}
COMPILE_STDOUT_CASE = {"id": "compile_prints_banners", "files": APP, "args": ["compile", "main.pyfun"]}
COMPILE_DIR_CASE = {
    "id": "compile_writes_a_tree",
    "files": APP,
    "args": ["compile", "main.pyfun", "-o", "build/py"],
    "outputs": ["build/py/main.py", "build/py/store.py", "build/py/geometry.py", "build/py/_pyfun_rt.py"],
}
RUN_CASE = {"id": "run_project", "files": APP, "args": ["run", "main.pyfun"]}
NATIVE_CASE = {"id": "compile_native_project", "files": APP, "args": ["compile", "main.pyfun", "--native"]}
TARGET_311_CASE = {
    "id": "compile_project_target_311",
    "files": {
        "util.pyfun": "let quote s = f\"<{s}>\"\n",
        "main.pyfun": "import Util\nlet xs = [\"a\", \"b\"]\nprint f\"joined: {String.join \", \" (List.map Util.quote xs)}\"\n",
    },
    "args": ["compile", "main.pyfun", "--target", "3.11"],
}


def test_check_over_the_graph_counts_the_modules(run, workdir):
    """CATCHES: a project `check` that only checks the entry file, or prints a different
    "ok: no type errors (N modules)" summary."""
    _check(run, workdir, CHECK_OK_CASE)


def test_compile_without_o_prints_every_file_under_a_banner(run, workdir):
    """CATCHES: wrong module order (dependencies must come first), wrong `.py` file names,
    a missing `_pyfun_rt.py`, missing banners or blank separator lines, or wrongly
    qualified cross-module references."""
    _check(run, workdir, COMPILE_STDOUT_CASE)


def test_compile_o_writes_the_python_tree(run, workdir):
    """CATCHES: `-o` for a project that writes a single file, forgets to create the directory,
    omits the runtime module, or reports a different file count."""
    _check(run, workdir, COMPILE_DIR_CASE)
    assert listing(workdir / "build") == "py/\npy/_pyfun_rt.py\npy/geometry.py\npy/main.py\npy/store.py\n"


def test_run_executes_the_whole_graph(run, workdir):
    """CATCHES: a project `run` whose staged tree cannot import its sibling modules or the
    shared runtime, or computes different values across the module boundary."""
    _check(run, workdir, RUN_CASE)


def test_native_project_lowers_every_module(run, workdir):
    """CATCHES: `--native` applied only to the entry module of a project."""
    _check(run, workdir, NATIVE_CASE)


def test_target_311_applies_to_every_module(run, workdir):
    """CATCHES: `--target 3.11` ignored on the project path, leaving PEP 701 f-strings."""
    _check(run, workdir, TARGET_311_CASE)


NO_RUNTIME_CASE = {
    "id": "no_runtime_without_option",
    "files": {"calc.pyfun": "let double x = x * 2\n", "main.pyfun": "import Calc\nprint (Calc.double 21)\n"},
    "args": ["compile", "main.pyfun", "-o", "out"],
    "outputs": ["out/main.py", "out/calc.py"],
}


def test_no_runtime_module_when_nothing_needs_it(run, workdir):
    """CATCHES: always emitting `_pyfun_rt.py` even when no module uses Option/Result."""
    _check(run, workdir, NO_RUNTIME_CASE)
    assert listing(workdir / "out") == "calc.py\nmain.py\n"


RUN_ARGS_CASE = {
    "id": "run_project_forwards_arguments",
    "files": {
        "args.pyfun": "extern import sys\nextern getArgv : unit -> List string = sys.argv.copy\nlet rest u = List.drop 1 (getArgv u)\n",
        "main.pyfun": "import Args\nprint (Args.rest ())\n",
    },
    "args": ["run", "main.pyfun", "--", "one", "--two"],
}
RUN_STDIN_CASE = {
    "id": "run_project_reads_stdin",
    "files": {
        "ask.pyfun": "let ask q = input q\n",
        "main.pyfun": "import Ask\nlet n = Ask.ask \"n? \"\nprint (String.upper n)\n",
    },
    "args": ["run", "main.pyfun"],
    "stdin": "quiet\n",
}
RUN_RUNTIME_ERROR_CASE = {
    "id": "run_project_runtime_error",
    "files": {
        "calc.pyfun": "let ratio a b = a / b\n",
        "main.pyfun": "import Calc\nprint \"computing\"\nprint (Calc.ratio 1 0)\n",
    },
    "args": ["run", "main.pyfun"],
    "normalize": [(r'File "[^"]*/pyfun_run_\d+/', 'File "<staged>/')],
}
RUN_PROJECT_CWD_CASE = {
    "id": "run_project_keeps_cwd",
    "files": {
        "notes.txt": "kept in the caller's directory\n",
        "app/reader.pyfun": (
            "extern readFile : string -> string = pathlib.Path.read_text\n"
            "extern pure path : string -> string = pathlib.Path\n"
            "let slurp p = readFile (path p)\n"
        ),
        "app/main.pyfun": "import Reader\nprint (Reader.slurp \"notes.txt\")\n",
    },
    "args": ["run", "app/main.pyfun"],
}


def test_run_project_forwards_arguments(run, workdir):
    """CATCHES: the project `run` path dropping program arguments or the `--` handling."""
    _check(run, workdir, RUN_ARGS_CASE)


def test_run_project_passes_stdin(run, workdir):
    """CATCHES: the project `run` path not wiring stdin to the program."""
    _check(run, workdir, RUN_STDIN_CASE)


def test_run_project_runtime_error_fails(run, workdir):
    """CATCHES: a project `run` that exits 0 after an exception in an imported module."""
    _check(run, workdir, RUN_RUNTIME_ERROR_CASE)


def test_run_project_keeps_the_working_directory(run, workdir):
    """CATCHES: a project `run` that changes into the entry's or the staging directory."""
    _check(run, workdir, RUN_PROJECT_CWD_CASE)


# ---------------------------------------------------------------- graph errors

MISSING_CASE = {"id": "missing_import", "files": {"main.pyfun": "import Nope\nlet x = 1\n"},
                "args": ["check", "main.pyfun"]}
MISSING_TRANSITIVE_CASE = {
    "id": "missing_transitive_import",
    "files": {"main.pyfun": "import Mid\nlet x = Mid.y\n", "mid.pyfun": "import Deep\nlet y = Deep.z\n"},
    "args": ["compile", "main.pyfun"],
}
CYCLE_CASE = {
    "id": "import_cycle",
    "files": {"main.pyfun": "import A\nlet x = A.a\n", "a.pyfun": "import B\nlet a = 1\n", "b.pyfun": "import A\nlet b = 2\n"},
    "args": ["check", "main.pyfun"],
}
SELF_IMPORT_CASE = {"id": "self_import", "files": {"main.pyfun": "import Main\nlet x = 1\n"},
                    "args": ["compile", "main.pyfun"]}
PARSE_ERROR_IN_MODULE_CASE = {
    "id": "parse_error_in_imported_module",
    "files": {"main.pyfun": "import Broken\nlet x = Broken.y\n", "broken.pyfun": "let y = 1\nlet z = (2 +\n"},
    "args": ["check", "main.pyfun"],
}
LEX_ERROR_IN_MODULE_CASE = {
    "id": "lex_error_in_imported_module",
    "files": {"main.pyfun": "import Broken\nlet x = Broken.y\n", "broken.pyfun": "let y = \"unterminated\n"},
    "args": ["run", "main.pyfun"],
}
TYPE_ERRORS_IN_TWO_MODULES_CASE = {
    "id": "type_errors_in_two_modules",
    "files": {
        "util.pyfun": "let bad = 1 + true\nlet twice x = x * 2\n",
        "main.pyfun": "import Util\nlet r = Util.twice \"no\"\nlet s = Util.missing\n",
    },
    "args": ["check", "main.pyfun"],
}
COMPILE_GATED_CASE = {
    "id": "compile_project_gated_on_check",
    "files": {"util.pyfun": "let twice x = x * 2\n", "main.pyfun": "import Util\nlet r = Util.twice \"no\"\n"},
    "args": ["compile", "main.pyfun", "-o", "out"],
}
RUN_GATED_CASE = {
    "id": "run_project_gated_on_check",
    "files": {"util.pyfun": "print \"util loaded\"\nlet twice x = x * 2\n",
              "main.pyfun": "import Util\nlet r = Util.twice \"no\"\n"},
    "args": ["run", "main.pyfun"],
}
LOWERCASE_IMPORT_CASE = {"id": "lowercase_import_name", "files": {"main.pyfun": "import geometry\n"},
                         "args": ["check", "main.pyfun"]}


def test_a_missing_import_is_reported(run, workdir):
    """CATCHES: a missing module reported without its expected file name, or treated as an
    empty module."""
    _check(run, workdir, MISSING_CASE)


def test_a_missing_transitive_import_names_the_importer(run, workdir):
    """CATCHES: a missing-module error that does not say which module imported it."""
    _check(run, workdir, MISSING_TRANSITIVE_CASE)


def test_an_import_cycle_is_reported_in_order(run, workdir):
    """CATCHES: an infinite loop on cyclic imports, or a cycle printed in a different order
    or without repeating its first module."""
    _check(run, workdir, CYCLE_CASE)


def test_a_module_importing_itself_is_a_cycle(run, workdir):
    """CATCHES: a self-import that is silently ignored or recurses forever."""
    _check(run, workdir, SELF_IMPORT_CASE)


def test_a_parse_error_is_rendered_against_the_imported_module(run, workdir):
    """CATCHES: rendering a dependency's parse error against the entry file's source (wrong
    line text under the caret)."""
    _check(run, workdir, PARSE_ERROR_IN_MODULE_CASE)


def test_a_lex_error_in_a_module_stops_run(run, workdir):
    """CATCHES: running a project whose dependency does not even lex."""
    _check(run, workdir, LEX_ERROR_IN_MODULE_CASE)


def test_type_errors_are_grouped_per_module(run, workdir):
    """CATCHES: errors not grouped under `-- module ... --` headers, attributed to the wrong
    module, or a wrong total count."""
    _check(run, workdir, TYPE_ERRORS_IN_TWO_MODULES_CASE)


def test_compile_project_is_gated_on_type_checking(run, workdir):
    """CATCHES: writing the `-o` tree for a project that does not type-check."""
    _check(run, workdir, COMPILE_GATED_CASE)
    assert listing(workdir) == "main.pyfun\nutil.pyfun\n"


def test_run_project_is_gated_on_type_checking(run, workdir):
    """CATCHES: executing any module of a project that does not type-check."""
    _check(run, workdir, RUN_GATED_CASE)


def test_a_lowercase_import_name_is_rejected(run, workdir):
    """CATCHES: accepting `import geometry` (module names must be capitalized)."""
    _check(run, workdir, LOWERCASE_IMPORT_CASE)


OUT_IS_A_FILE_CASE = {
    "id": "project_out_dir_is_a_file",
    "files": {"calc.pyfun": "let double x = x * 2\n", "main.pyfun": "import Calc\nprint (Calc.double 2)\n",
              "out": "i am a file\n"},
    "args": ["compile", "main.pyfun", "-o", "out"],
}


def test_project_output_directory_that_is_a_file(run, workdir):
    """CATCHES: overwriting a file that sits where the output directory should be, or
    reporting success."""
    _check(run, workdir, OUT_IS_A_FILE_CASE)


ENTRY_IN_SUBDIR_CASE = {
    "id": "entry_in_subdirectory",
    "files": {"src/calc.pyfun": "let double x = x * 2\n", "src/main.pyfun": "import Calc\nprint (Calc.double 21)\n",
              "calc.pyfun": "let double x = x * 100\n"},
    "args": ["run", "src/main.pyfun"],
}


def test_imports_resolve_next_to_the_entry_file(run, workdir):
    """CATCHES: resolving imports against the working directory instead of the entry file's
    directory."""
    _check(run, workdir, ENTRY_IN_SUBDIR_CASE)


# ---------------------------------------------------------------- vendored façades

FACADE_CASE = {
    "id": "import_from_vendored_facade",
    "files": {
        "pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\npyfun-shout = \"0.1.0\"\n",
        ".pyfun/facades/pyfun-shout/shout.pyfun": "## Loud strings.\nlet loud s = String.concat (String.upper s) \"!\"\n",
        "main.pyfun": "import Shout\nprint (Shout.loud \"hello\")\n",
    },
    "args": ["compile", "main.pyfun"],
}
FACADE_RUN_CASE = dict(FACADE_CASE, id="run_with_vendored_facade", args=["run", "main.pyfun"])
SIBLING_WINS_CASE = {
    "id": "sibling_module_wins_over_facade",
    "files": {
        "pyfun.toml": "[project]\nname = \"demo\"\n",
        ".pyfun/facades/pyfun-shout/shout.pyfun": "let loud s = String.upper s\n",
        "shout.pyfun": "let loud s = String.lower s\n",
        "main.pyfun": "import Shout\nprint (Shout.loud \"MiXeD\")\n",
    },
    "args": ["run", "main.pyfun"],
}
FACADE_NEEDS_MANIFEST_CASE = {
    "id": "facade_ignored_without_manifest",
    "files": {
        ".pyfun/facades/pyfun-shout/shout.pyfun": "let loud s = String.upper s\n",
        "main.pyfun": "import Shout\nprint (Shout.loud \"x\")\n",
    },
    "args": ["check", "main.pyfun"],
}
FACADE_FROM_PARENT_CASE = {
    "id": "facade_found_from_nearest_manifest",
    "files": {
        "pyfun.toml": "[project]\nname = \"demo\"\n",
        ".pyfun/facades/pyfun-b/beta.pyfun": "let name = \"beta\"\n",
        ".pyfun/facades/pyfun-a/alpha.pyfun": "let name = \"alpha\"\n",
        "src/app/main.pyfun": "import Alpha\nimport Beta\nprint f\"{Alpha.name}+{Beta.name}\"\n",
    },
    "args": ["run", "src/app/main.pyfun"],
}
FACADE_PARSE_ERROR_CASE = {
    "id": "facade_parse_error",
    "files": {
        "pyfun.toml": "[project]\nname = \"demo\"\n",
        ".pyfun/facades/pyfun-bad/bad.pyfun": "let = 1\n",
        "main.pyfun": "import Bad\nlet x = 1\n",
    },
    "args": ["check", "main.pyfun"],
}


def test_imports_resolve_from_a_vendored_facade(run, workdir):
    """CATCHES: ignoring `.pyfun/facades/<dist>/` under the project's `pyfun.toml`."""
    _check(run, workdir, FACADE_CASE)


def test_a_vendored_facade_runs(run, workdir):
    """CATCHES: a façade module that compiles but is not staged next to the entry for `run`."""
    _check(run, workdir, FACADE_RUN_CASE)


def test_a_sibling_module_wins_over_a_facade(run, workdir):
    """CATCHES: resolving a façade before the project's own sibling module of the same name."""
    _check(run, workdir, SIBLING_WINS_CASE)


def test_facades_need_a_manifest(run, workdir):
    """CATCHES: searching `.pyfun/facades` even when no `pyfun.toml` marks the project root."""
    _check(run, workdir, FACADE_NEEDS_MANIFEST_CASE)


def test_facades_are_found_from_the_nearest_manifest_above_the_entry(run, workdir):
    """CATCHES: looking for `pyfun.toml` only in the entry's own directory."""
    _check(run, workdir, FACADE_FROM_PARENT_CASE)


def test_a_facade_parse_error_names_the_module(run, workdir):
    """CATCHES: a façade parse error that crashes or is attributed to the entry module."""
    _check(run, workdir, FACADE_PARSE_ERROR_CASE)


# ---------------------------------------------------------------- the shipped example

def _example(name):
    # A verbatim copy of the repository's documented examples/modules/ project.
    return (resources_for(__file__) / "inputs" / name).read_text(encoding="utf-8")


EXAMPLE_FILES = {n: _example(n) for n in ("main.pyfun", "geometry.pyfun", "store.pyfun")}
EXAMPLE_RUN_CASE = {"id": "examples_modules_run", "files": EXAMPLE_FILES, "args": ["run", "main.pyfun"]}
EXAMPLE_COMPILE_CASE = {"id": "examples_modules_compile", "files": EXAMPLE_FILES, "args": ["compile", "main.pyfun"]}


def test_the_documented_modules_example_runs(run, workdir):
    """CATCHES: regressions on the README's `pyfun run examples/modules/main.pyfun` tour."""
    _check(run, workdir, EXAMPLE_RUN_CASE)


def test_the_documented_modules_example_compiles(run, workdir):
    """CATCHES: different Python for the README's multi-module example."""
    _check(run, workdir, EXAMPLE_COMPILE_CASE)
