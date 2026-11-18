"""`pyfun build --native <file> -o <dir>`: native compile, then mypyc through the interpreter named by
`PYFUN_PYTHON`. mypyc itself is replaced by a stand-in interpreter script that logs how it was invoked
(its arguments and the files in its working directory) and simulates a successful or failing build, so
the test sees exactly what pyfun hands to mypyc and what it leaves in the output directory."""

import stat

from conftest import golden, write_files

SHAPES = """type Shape = Circle float | Rect float float

let area s =
  match s:
    case Circle r: 3.14159 * r * r
    case Rect w h: w * h

print (area (Rect 2.0 3.0))
"""

FAKE_PYTHON = r"""#!/bin/sh
# Stand-in for `python -m mypyc ...`: log the call, then fake the build outcome.
{
  printf 'cwd:'
  for f in *; do printf ' %s' "$f"; done
  printf '\nargv:'
  for a in "$@"; do printf ' %s' "$a"; done
  printf '\n'
} >> "$FAKE_LOG"
if [ "$FAKE_MODE" = fail ]; then
  echo "mypyc: error: no C compiler"
  exit 1
fi
for a in "$@"; do
  case "$a" in
    *.py) : > "${a%.py}.cpython-fake.so" ;;
  esac
done
mkdir build
: > build/temp.o
echo "fake mypyc: built"
"""

MYPYC_FLAGS = ("-m mypyc --allow-redefinition-new --local-partial-types --disable-error-code func-returns-value "
               "--disable-error-code var-annotated --disable-error-code union-attr")


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def setup(workdir, files):
    write_files(workdir, files)
    py = workdir / "fakepy"
    py.write_text(FAKE_PYTHON)
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"PYFUN_PYTHON": str(py), "FAKE_LOG": str(workdir / "mypyc.log")}


def test_build_single_file(run, workdir):
    """CATCHES: not compiling in native mode before mypyc, invoking mypyc with different flags or from a
    different directory, leaving the Python source or the `build/` directory behind, or writing a
    different `__main__.py` / success line."""
    env = setup(workdir, {"prog.pyfun": SHAPES})
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b"fake mypyc: built\nbuilt prog.pyfun natively: run it with `python out`\n"
    assert r.stderr == b""
    assert r.returncode == 0
    assert (workdir / "mypyc.log").read_text() == f"cwd: prog.py\nargv: {MYPYC_FLAGS} prog.py\n"
    out = workdir / "out"
    assert tree(out) == ["__main__.py", "prog.cpython-fake.so"]
    assert (out / "__main__.py").read_bytes() == (b"# Runs the mypyc-compiled Pyfun program `prog`.\n"
                                                  b"import prog  # noqa: F401\n")


def test_build_compiles_the_native_form(run, workdir):
    """CATCHES: handing mypyc the default (match-statement) emission instead of the `--native` one: the
    staged module equals `compile --native` output, and stays in place when mypyc fails."""
    env = setup(workdir, {"prog.pyfun": SHAPES})
    native = run(["compile", "prog.pyfun", "--native"])
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides={**env, "FAKE_MODE": "fail"})
    assert r.stdout == b"mypyc: error: no C compiler\n"
    assert r.stderr == (b"error: mypyc could not build the program (see its output above); it needs "
                        b"`pip install mypy setuptools` and a C compiler\n")
    assert r.returncode == 1
    assert tree(workdir / "out") == ["prog.py"]
    assert (workdir / "out" / "prog.py").read_bytes() == native.stdout == golden(__file__, "shapes_native.golden")


def test_build_flags_in_any_order_and_long_output(run, workdir):
    """CATCHES: `--native` only recognised first, or `--output` not accepted for `-o`; also a success
    line that does not echo the input path as given (`src/prog.pyfun`)."""
    env = setup(workdir, {"src/prog.pyfun": "print 1\n"})
    r = run(["build", "src/prog.pyfun", "--output", "dist/native", "--native"], env_overrides=env)
    assert r.stdout == b"fake mypyc: built\nbuilt src/prog.pyfun natively: run it with `python dist/native`\n"
    assert (r.stderr, r.returncode) == (b"", 0)
    assert tree(workdir / "dist") == ["native/__main__.py", "native/prog.cpython-fake.so"]


def test_build_sanitises_an_unimportable_file_name(run, workdir):
    """CATCHES: naming the module after a stem Python cannot import (`01-intro`): it becomes the
    lower-cased, underscore-cleaned `_pf_01_intro`, used both for mypyc and in `__main__.py`."""
    env = setup(workdir, {"01-Intro.pyfun": "print 1\n"})
    r = run(["build", "--native", "01-Intro.pyfun", "-o", "out"], env_overrides=env)
    assert r.returncode == 0
    assert (workdir / "mypyc.log").read_text() == f"cwd: _pf_01_intro.py\nargv: {MYPYC_FLAGS} _pf_01_intro.py\n"
    assert tree(workdir / "out") == ["__main__.py", "_pf_01_intro.cpython-fake.so"]
    assert (workdir / "out" / "__main__.py").read_bytes() == (
        b"# Runs the mypyc-compiled Pyfun program `_pf_01_intro`.\nimport _pf_01_intro  # noqa: F401\n")


def test_build_lowercases_an_importable_file_name(run, workdir):
    """CATCHES: keeping capitals in the module name, or adding the `_pf_` prefix to a valid identifier."""
    env = setup(workdir, {"Hello_World.pyfun": "print 1\n"})
    r = run(["build", "--native", "Hello_World.pyfun", "-o", "out"], env_overrides=env)
    assert r.returncode == 0
    assert tree(workdir / "out") == ["__main__.py", "hello_world.cpython-fake.so"]
    assert (workdir / "mypyc.log").read_text() == f"cwd: hello_world.py\nargv: {MYPYC_FLAGS} hello_world.py\n"


def test_build_project_compiles_every_module_but_the_runtime(run, workdir):
    """CATCHES: building only the entry of a project, compiling the shared `_pyfun_rt.py` with mypyc
    (it must stay Python), or a `__main__.py` that imports anything but the entry module."""
    env = setup(workdir, {
        "app.pyfun": "import Store\nprint (Option.withDefault 0 (Store.lookup 7))\n",
        "store.pyfun": "let lookup k = Some k\n",
    })
    r = run(["build", "--native", "app.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b"fake mypyc: built\nbuilt app.pyfun natively: run it with `python out`\n"
    assert (r.stderr, r.returncode) == (b"", 0)
    assert (workdir / "mypyc.log").read_text() == (
        f"cwd: _pyfun_rt.py app.py store.py\nargv: {MYPYC_FLAGS} store.py app.py\n")
    out = workdir / "out"
    assert tree(out) == ["__main__.py", "_pyfun_rt.py", "app.cpython-fake.so", "store.cpython-fake.so"]
    assert (out / "__main__.py").read_bytes() == b"# Runs the mypyc-compiled Pyfun program `app`.\nimport app  # noqa: F401\n"
    assert (out / "_pyfun_rt.py").read_bytes() == golden(__file__, "project_rt_native.golden")


def test_build_project_type_error(run, workdir):
    """CATCHES: running mypyc on a project that does not type-check."""
    env = setup(workdir, {"app.pyfun": "import Geo\nlet bad = Geo.area 4 \"five\"\n", "geo.pyfun": "let area w h = w * h\n"})
    r = run(["build", "--native", "app.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "project_type_error.golden")
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["app.pyfun", "fakepy", "geo.pyfun"]


def test_build_project_missing_module(run, workdir):
    """CATCHES: a graph error not being reported before anything is written."""
    env = setup(workdir, {"app.pyfun": "import Nope\nprint 1\n"})
    r = run(["build", "--native", "app.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot find module `Nope` (expected `nope.pyfun`), imported by `App`\n"
    assert r.returncode == 1


def test_build_project_lowering_failure(run, workdir):
    """CATCHES: a project with a typed hole reaching mypyc; project lowering fails first."""
    env = setup(workdir, {"app.pyfun": "import Geo\nprint (Geo.area 2 3)\n", "geo.pyfun": "let area w h = ?todo\n"})
    r = run(["build", "--native", "app.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: lowering failed: cannot compile: unfilled hole `?todo`\n"
    assert r.returncode == 1


def test_build_project_output_is_a_file(run, workdir):
    """CATCHES: a project build overwriting a regular file named by `-o`."""
    env = setup(workdir, {"app.pyfun": "import Geo\nprint (Geo.area 2 3)\n", "geo.pyfun": "let area w h = w * h\n",
                          "out": "not a directory\n"})
    r = run(["build", "--native", "app.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot create out: File exists (os error 17)\n"
    assert r.returncode == 1


def test_build_project_cannot_write_a_module(run, workdir):
    """CATCHES: ignoring a failed module write in a project build."""
    env = setup(workdir, {"app.pyfun": "import Geo\nprint (Geo.area 2 3)\n", "geo.pyfun": "let area w h = w * h\n",
                          "out/geo.py/keep": "x\n"})
    r = run(["build", "--native", "app.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot write geo.py: Is a directory (os error 21)\n"
    assert r.returncode == 1


def test_build_type_error_writes_nothing(run, workdir):
    """CATCHES: creating the output directory or calling mypyc when the program does not type-check."""
    env = setup(workdir, {"prog.pyfun": "let r = 1 + true\n"})
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == (b"error: expected int, found bool\n --> 1:13\n  |\n1 | let r = 1 + true\n"
                        b"  |             ^^^^\n")
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["fakepy", "prog.pyfun"]


def test_build_reports_notes(run, workdir):
    """CATCHES: lowering notes being dropped by `build`."""
    env = setup(workdir, {"prog.pyfun": """let collect n acc =
  if n == 0 then acc
  else collect (n - 1) (List.concat acc [fun k -> n])
let fns = collect 3 []
"""})
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b"fake mypyc: built\nbuilt prog.pyfun natively: run it with `python out`\n"
    assert r.stderr == (b"note: `collect` calls itself in tail position but keeps its recursive form: a closure in "
                        b"it captures `n`\n")
    assert r.returncode == 0


def test_build_output_is_an_existing_file(run, workdir):
    """CATCHES: replacing a regular file named by `-o`, or failing without the OS error."""
    env = setup(workdir, {"prog.pyfun": "print 1\n", "out": "a file\n"})
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot create out: File exists (os error 17)\n"
    assert r.returncode == 1
    assert (workdir / "out").read_bytes() == b"a file\n"


def test_build_cannot_write_the_module_source(run, workdir):
    """CATCHES: ignoring a failed write of the staged module (path reported in full)."""
    env = setup(workdir, {"prog.pyfun": "print 1\n", "out/prog.py/keep": "x\n"})
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot write out/prog.py: Is a directory (os error 21)\n"
    assert r.returncode == 1


def test_build_missing_interpreter_named_by_pyfun_python(run, workdir):
    """CATCHES: falling back to PATH when `PYFUN_PYTHON` names a missing program, or not reporting it."""
    (workdir / "prog.pyfun").write_text("print 1\n")
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides={"PYFUN_PYTHON": "./no-python"})
    assert r.stdout == b""
    assert r.stderr == b"error: cannot run ./no-python: No such file or directory (os error 2)\n"
    assert r.returncode == 1
    assert tree(workdir / "out") == ["prog.py"]


def test_build_without_any_python(run, workdir):
    """CATCHES: a crash, or the `run`-style wording, when no interpreter exists; `build` suggests
    setting PYFUN_PYTHON (the native module has already been written)."""
    (workdir / "prog.pyfun").write_text("print 1\n")
    (workdir / "emptybin").mkdir()
    r = run(["build", "--native", "prog.pyfun", "-o", "out"], env_overrides={"PATH": str(workdir / "emptybin")})
    assert r.stdout == b""
    assert r.stderr == b"error: no Python interpreter found (set PYFUN_PYTHON)\n"
    assert r.returncode == 1
    assert tree(workdir / "out") == ["prog.py"]
