"""`pyfun build --native <file> -o <dir>`: compile with `--native`, hand the modules to
mypyc, drop their `.py` sources and write a `__main__.py` entry point.

mypyc itself is replaced by a stand-in interpreter selected with `PYFUN_PYTHON`: it
logs which module files it was asked to build, writes a placeholder extension next
to each, and creates a `build/` scratch directory, the way mypyc leaves one.
"""

from conftest import golden_name, listing, read_golden, run_case, transcript

FAKE_MYPYC = r"""#!/bin/sh
# Stand-in for `python -m mypyc ...`.
if [ "$1" != "-m" ] || [ "$2" != "mypyc" ]; then
  echo "unexpected: $*" >&2
  exit 2
fi
mods=""
for a in "$@"; do
  case "$a" in
    *.py) mods="$mods $a"; : > "${a%.py}.fake-ext" ;;
  esac
done
echo "[mypyc] building:$mods" >&2
mkdir -p build/temp
if [ -f ../FAIL ]; then
  echo "[mypyc] error: no C compiler" >&2
  exit 1
fi
exit 0
"""

PROGRAM = (
    "type Shape = Circle float | Rect float float\n"
    "\n"
    "let area s =\n"
    "  match s:\n"
    "    case Circle r: 3.0 * r * r\n"
    "    case Rect w h: w * h\n"
    "\n"
    "print (area (Rect 2.0 4.0))\n"
)
ENV = {"PYFUN_PYTHON": "{workdir}/tools/python"}


def _case(id, args, files, outputs=()):
    return {"id": id, "files": {"tools/python": FAKE_MYPYC, **files}, "executables": ["tools/python"],
            "env": ENV, "args": args, "outputs": list(outputs)}


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


SINGLE_CASE = _case("single_file", ["build", "--native", "shapes.pyfun", "-o", "native"],
                    {"shapes.pyfun": PROGRAM}, outputs=["native/__main__.py"])
ODD_NAME_CASE = _case("file_name_python_cannot_import", ["build", "--native", "01-intro.pyfun", "-o", "out"],
                      {"01-intro.pyfun": PROGRAM}, outputs=["out/__main__.py"])
PROJECT_CASE = _case(
    "project", ["build", "-o", "dist", "--native", "main.pyfun"],
    {"geometry.pyfun": "let area w h = w * h\nlet find k = if k > 0 then Some k else None\n",
     "main.pyfun": "import Geometry\nprint (Geometry.area 3 4)\nprint (Geometry.find 2)\n"},
    outputs=["dist/__main__.py", "dist/_pyfun_rt.py"])
FAILS_CASE = _case("mypyc_fails", ["build", "--native", "shapes.pyfun", "-o", "native"],
                   {"shapes.pyfun": PROGRAM, "FAIL": ""}, outputs=["native/shapes.py"])
TYPE_ERROR_CASE = _case("type_error", ["build", "--native", "bad.pyfun", "-o", "native"],
                        {"bad.pyfun": "let x = 1 + true\n"})
PROJECT_TYPE_ERROR_CASE = _case(
    "project_type_error", ["build", "--native", "main.pyfun", "-o", "native"],
    {"util.pyfun": "let f x = x + 1\n", "main.pyfun": "import Util\nlet y = Util.f \"s\"\n"})
PROJECT_MISSING_CASE = _case("project_missing_module", ["build", "--native", "main.pyfun", "-o", "native"],
                             {"main.pyfun": "import Absent\nlet y = 1\n"})
MISSING_FILE_CASE = _case("missing_file", ["build", "--native", "gone.pyfun", "-o", "native"], {})
OUT_IS_FILE_CASE = _case("out_is_a_file", ["build", "--native", "shapes.pyfun", "-o", "native"],
                         {"shapes.pyfun": PROGRAM, "native": "occupied\n"})
NOTE_CASE = _case(
    "notes_are_reported", ["build", "--native", "loop.pyfun", "-o", "native"],
    {"loop.pyfun": "let collect n acc =\n  if n == 0 then acc\n  else\n    let f = fun x -> x + n\n    collect (n - 1) (f acc)\nprint (collect 3 0)\n"})


def test_build_a_single_file(run, workdir):
    """CATCHES: a build that does not compile in native mode, hands mypyc the wrong module,
    keeps the `.py` source or the `build/` directory, writes a different `__main__.py`,
    or prints a different success line."""
    _check(run, workdir, SINGLE_CASE)
    assert listing(workdir / "native") == "__main__.py\nshapes.fake-ext\n"


def test_build_renames_a_module_python_cannot_import(run, workdir):
    """CATCHES: building `01-intro.pyfun` as module `01-intro`, which Python cannot import,
    instead of the sanitised `_pf_01_intro`."""
    _check(run, workdir, ODD_NAME_CASE)
    assert listing(workdir / "out") == "__main__.py\n_pf_01_intro.fake-ext\n"


def test_build_a_project(run, workdir):
    """CATCHES: building only the entry of a project, compiling the shared `_pyfun_rt.py`
    with mypyc (it must stay Python), or flags that must accept any argument order."""
    _check(run, workdir, PROJECT_CASE)
    assert listing(workdir / "dist") == "__main__.py\n_pyfun_rt.py\ngeometry.fake-ext\nmain.fake-ext\n"


def test_build_reports_a_mypyc_failure(run, workdir):
    """CATCHES: reporting success, or deleting the generated Python, when mypyc fails."""
    _check(run, workdir, FAILS_CASE)


def test_build_stops_on_a_type_error(run, workdir):
    """CATCHES: invoking mypyc (or writing files) for an ill-typed program."""
    _check(run, workdir, TYPE_ERROR_CASE)
    assert not (workdir / "native").exists()


def test_build_stops_on_a_project_type_error(run, workdir):
    """CATCHES: building a project whose modules do not type-check."""
    _check(run, workdir, PROJECT_TYPE_ERROR_CASE)
    assert not (workdir / "native").exists()


def test_build_stops_on_a_project_graph_error(run, workdir):
    """CATCHES: building a project with an unresolvable import."""
    _check(run, workdir, PROJECT_MISSING_CASE)


def test_build_reports_a_missing_file(run, workdir):
    """CATCHES: a missing source file reported differently from the other commands."""
    _check(run, workdir, MISSING_FILE_CASE)


def test_build_output_that_is_a_file(run, workdir):
    """CATCHES: overwriting a file where the build directory should go."""
    _check(run, workdir, OUT_IS_FILE_CASE)


def test_build_reports_lowering_notes(run, workdir):
    """CATCHES: a native build that drops the "note:" lines the compiler produces."""
    _check(run, workdir, NOTE_CASE)


ARG_CASES = [
    _case("needs_native_flag", ["build", "shapes.pyfun", "-o", "native"], {"shapes.pyfun": PROGRAM}),
    _case("needs_a_path", ["build", "--native", "-o", "native"], {}),
    _case("needs_an_output_dir", ["build", "--native", "shapes.pyfun"], {"shapes.pyfun": PROGRAM}),
    _case("rejects_a_second_path", ["build", "--native", "a.pyfun", "b.pyfun", "-o", "x"], {}),
]


def test_build_requires_the_native_flag(run, workdir):
    """CATCHES: a `build` that silently defaults to native or to plain Python."""
    _check(run, workdir, ARG_CASES[0])


def test_build_requires_a_path(run, workdir):
    """CATCHES: a `build` without a source file that does not say it needs one."""
    _check(run, workdir, ARG_CASES[1])


def test_build_requires_an_output_directory(run, workdir):
    """CATCHES: a default output directory instead of the "needs an output directory" error."""
    _check(run, workdir, ARG_CASES[2])


def test_build_rejects_an_extra_positional_argument(run, workdir):
    """CATCHES: a `build` that silently ignores (or builds) a second source path instead of
    rejecting it as an unexpected argument."""
    _check(run, workdir, ARG_CASES[3])
