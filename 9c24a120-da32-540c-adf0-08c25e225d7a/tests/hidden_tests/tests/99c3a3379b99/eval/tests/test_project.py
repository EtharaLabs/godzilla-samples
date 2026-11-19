"""Black-box tests for multi-module projects (DESIGN.md §6.1 file modules, §6.2 façades).

A file with at least one `import Name` is the entry of a project: `check`, `compile` (stdout banners or
`-o <dir>`), and `run` drive the whole import graph. Each test writes real source files into the empty
`workdir`, runs the CLI with relative paths, and compares exact stdout/stderr/exit code (and every file
written) with goldens captured from the reference binary under eval/test_resources/test_project/.
"""

from pathlib import Path

from conftest import golden, write_files

# ----------------------------------------------------------------------------------- helpers


def _expected(value):
    """A `str` names a golden file; `bytes` are the literal expectation."""
    return golden(__file__, value) if isinstance(value, str) else value


def expect(r, rc, out=b"", err=b""):
    """Assert the exact stdout, stderr and exit code of one CLI run."""
    assert r.stdout == _expected(out)
    assert r.stderr == _expected(err)
    assert r.returncode == rc


def listing(root: Path) -> bytes:
    """Every file under `root` (relative POSIX paths, sorted), one per line."""
    names = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    return "".join(name + "\n" for name in names).encode()


def listing_of(files: dict) -> bytes:
    """What `listing` gives for a directory holding exactly `files`."""
    return "".join(name + "\n" for name in sorted(files)).encode()


def expect_tree(root: Path, case: str):
    """Assert the exact file list under `root` and every file's bytes against `<case>.tree/` goldens."""
    names = listing(root)
    assert names == golden(__file__, f"{case}.tree/FILES")
    for name in names.decode().splitlines():
        assert (root / name).read_bytes() == golden(__file__, f"{case}.tree/{name}")


# ----------------------------------------------------------------------------------- sources

# examples/modules, verbatim.
EX_GEOMETRY = """\
# The Geometry module — one module per file (`DESIGN.md` §6.1). Its top-level
# `let` values are its public interface; Main imports them as `Geometry.*`.
# Compiles to a sibling `geometry.py` with un-mangled `def area`/`def square`.
let area w h = w * h

# A module member sees its siblings unqualified (`square` calls `area`).
let square x = area x x
"""

EX_STORE = """\
# The Store module — returns an `Option` that crosses the module boundary back
# to Main. Because the nominal `Some`/`None` classes are hoisted into a shared
# `_pyfun_rt.py` that every module imports, the `Some` built here is the *same*
# type Main inspects with the `Option` module — so it works across files.
let lookup key =
  match key:
    case 1: Some 100
    case 2: Some 200
    case _: None
"""

EX_MAIN = """\
# A multi-file Pyfun project (`DESIGN.md` §6.1). From this directory:
#   pyfun run     examples/modules/main.pyfun          # run the whole project
#   pyfun check   examples/modules/main.pyfun          # type-check every module
#   pyfun compile examples/modules/main.pyfun -o out   # emit the .py tree
#
# `import` brings a sibling source file into scope under its capitalized name
# (`Geometry` ← geometry.pyfun); members are used qualified, `Geometry.area`.
# The import graph must be acyclic. Each module compiles to its own readable
# `.py`; a cross-module call lowers to plain Python attribute access
# (`geometry.area(4, 5)`) with `import geometry` hoisted to the file header.
import Geometry
import Store

# Cross-module full application → geometry.area(4, 5).
let floor = Geometry.area 4 5
let nine = Geometry.square 3

# Cross-module *partial* application still curries (→ functools.partial).
let widen = Geometry.area 10
let strip = widen 2                  # 20

# An Option built in Store and consumed here — one `Some` type via the shared
# runtime, so `Option.withDefault` matches it correctly across the boundary.
# `|>` pipes the value into the (curried, partially-applied) transform.
let hit = Store.lookup 1 |> Option.withDefault 0
let miss = Store.lookup 9 |> Option.withDefault 0

print floor                          # 20
print nine                           # 9
print strip                          # 20
print hit                            # 100
print miss                           # 0
"""

EXAMPLE = {"main.pyfun": EX_MAIN, "geometry.pyfun": EX_GEOMETRY, "store.pyfun": EX_STORE}
EXAMPLE_OUTPUT = b"20\n9\n20\n100\n0\n"

GEOMETRY = "let area w h = w * h\n"
TWO_MODULES = {"main.pyfun": "import Geometry\nprint (Geometry.area 4 5)\n", "geometry.pyfun": GEOMETRY}

# Three modules for the transitive-interface cases: Inner declares a record, Middle wraps it.
INNER = "type Config = { cSize: int }\nlet make n = Config { cSize = n }\n"
MIDDLE = """\
import Inner
type Wrap = { wConf: Inner.Config }
let mk n = Wrap { wConf = Inner.make n }
let size w = w.wConf.cSize
"""

MANIFEST = '[project]\nname = "demo"\n\n[dependencies]\npyfun-shout = "0.1.0"\n'
SHOUT_FACADE = ".pyfun/facades/pyfun-shout/shout.pyfun"
SHOUT_MAIN = 'import Shout\n"hi" |> Shout.loud |> print\n'

# examples/facades/pyfun-textwrap/pyfun_textwrap/wrap.pyfun, verbatim.
WRAP_FACADE = """\
# Typed declarations for Python's `textwrap`, imported in Pyfun as `Wrap`.
# Every function here is pure: it reads its arguments and returns a string.
#
# A façade is ordinary Pyfun, so beside the `extern`s it can hold small
# functions that give the Python API a pipe-friendly shape: the text comes
# last, so `text |> Wrap.fill 24` reads left to right.

extern import textwrap

extern pure fillText: string -> int -> string = textwrap.fill(width = ...)
extern pure shortenText: string -> int -> string = textwrap.shorten(width = ...)
extern pure indentText: string -> string -> string = textwrap.indent

# `text |> Wrap.fill 24`: the text re-flowed to lines of at most 24 characters.
let fill width text = fillText text width

# `text |> Wrap.shorten 30`: the text collapsed and cut to fit 30 characters,
# ending in " [...]" when something was cut.
let shorten width text = shortenText text width

# `text |> Wrap.indent "> "`: every non-blank line prefixed.
let indent prefix text = indentText text prefix
"""


# =================================================================== the shipped modules example


def test_example_check_counts_every_module(run, workdir):
    """CATCHES: a project `check` that only checks the entry file, prints the single-file ok line, or miscounts the modules in the import graph."""
    write_files(workdir, EXAMPLE)
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")


def test_example_compile_prints_each_file_under_a_banner(run, workdir):
    """CATCHES: compile without -o that emits only the entry, drops the `# ==== name.py ====` banners, orders files non-topologically or omits _pyfun_rt.py."""
    write_files(workdir, EXAMPLE)
    expect(run(["compile", "main.pyfun"]), 0, out="example_compile.out")


def test_example_bare_path_is_compile_shorthand_for_a_project(run, workdir):
    """CATCHES: the `pyfun <file>` shorthand taking the single-file path for a file with imports instead of the project driver's banner output."""
    write_files(workdir, EXAMPLE)
    expect(run(["main.pyfun"]), 0, out="example_compile.out")


def test_example_compile_to_directory_writes_the_python_tree(run, workdir):
    """CATCHES: `compile -o dir` that writes a single file, misnames module files, skips the shared runtime, or misreports the count in `wrote N files to dir`."""
    write_files(workdir, EXAMPLE)
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=b"wrote 4 files to out\n")
    expect_tree(workdir / "out", "example_out")


def test_example_run_executes_the_whole_project(run, workdir):
    """CATCHES: `run` on a project that stages only the entry module (ImportError) or loses the shared Option class so withDefault misreads Store's values."""
    write_files(workdir, EXAMPLE)
    expect(run(["run", "main.pyfun"]), 0, out=EXAMPLE_OUTPUT)


def test_example_native_lowering_covers_every_module(run, workdir):
    """CATCHES: `--native` applied only to the entry module, or a native project still emitting `match` statements or the non-native runtime classes."""
    write_files(workdir, EXAMPLE)
    expect(run(["compile", "main.pyfun", "--native", "-o", "native"]), 0, err=b"wrote 4 files to native\n")
    expect_tree(workdir / "native", "example_native")


# =================================================================== project vs single-file dispatch


def test_a_module_without_imports_takes_the_single_file_path(run, workdir):
    """CATCHES: treating every file as a project (module count in the ok line, banners, _pyfun_rt import) even when the file itself has no import."""
    write_files(workdir, EXAMPLE)
    expect(run(["check", "geometry.pyfun"]), 0, err=b"ok: no type errors\n")
    expect(run(["compile", "store.pyfun"]), 0, out="single_file_store.out")


def test_an_entry_parse_error_is_reported_before_any_import_is_resolved(run, workdir):
    """CATCHES: resolving the import graph before parsing the entry, which would report the missing module instead of the entry's own syntax error."""
    write_files(workdir, {"main.pyfun": "import Nowhere\nlet x = 1\nlet = 2\nlet y = 3\n"})
    expect(run(["check", "main.pyfun"]), 1, err="entry_parse_error.err")
    expect(run(["compile", "main.pyfun"]), 1, err="entry_parse_error.err")
    expect(run(["run", "main.pyfun"]), 1, err="entry_parse_error.err")


def test_dash_o_is_a_file_for_one_module_and_a_directory_for_a_project(run, workdir):
    """CATCHES: treating `-o` as a directory for an import-free file, or as a single output file for a project, contrary to the documented split."""
    write_files(workdir, TWO_MODULES)
    expect(run(["compile", "geometry.pyfun", "-o", "geo.py"]), 0, err=b"wrote geo.py\n")
    expect(run(["compile", "main.pyfun", "-o", "tree"]), 0, err=b"wrote 2 files to tree\n")
    assert listing(workdir) == b"geo.py\ngeometry.pyfun\nmain.pyfun\ntree/geometry.py\ntree/main.py\n"
    assert (workdir / "geo.py").read_bytes() == golden(__file__, "two_modules.tree/geometry.py")
    expect_tree(workdir / "tree", "two_modules")


def test_imports_may_follow_other_items(run, workdir):
    """CATCHES: a driver that only recognises imports at the top of the file, so a later `import Geometry` is not followed and the member is unknown."""
    write_files(workdir, {"main.pyfun": "let x = 6\nimport Geometry\nprint (Geometry.area x 7)\n", "geometry.pyfun": GEOMETRY})
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")
    expect(run(["run", "main.pyfun"]), 0, out=b"42\n")


def test_module_files_are_named_by_the_lowercased_module_name(run, workdir):
    """CATCHES: emitting `MyApp.py` for a capitalised entry or resolving `import MyLib` to anything but `mylib.pyfun` (the lowercased stem convention)."""
    write_files(workdir, {"MyApp.pyfun": "import MyLib\nprint (MyLib.twice 21)\n", "mylib.pyfun": "let twice x = x * 2\n"})
    expect(run(["compile", "MyApp.pyfun", "-o", "out"]), 0, err=b"wrote 2 files to out\n")
    expect_tree(workdir / "out", "capitalised_entry")
    expect(run(["run", "MyApp.pyfun"]), 0, out=b"42\n")


# =================================================================== graph errors


def test_a_missing_module_names_its_importer_for_every_command(run, workdir):
    """CATCHES: a missing import that is silently skipped, reported without the expected file name or importer, or that still creates the -o directory."""
    files = {"main.pyfun": "import Nope\nlet x = 1\n"}
    write_files(workdir, files)
    message = b"error: cannot find module `Nope` (expected `nope.pyfun`), imported by `Main`\n"
    expect(run(["check", "main.pyfun"]), 1, err=message)
    expect(run(["compile", "main.pyfun", "-o", "out"]), 1, err=message)
    expect(run(["run", "main.pyfun"]), 1, err=message)
    assert listing(workdir) == listing_of(files)


def test_a_missing_transitive_module_names_the_module_that_imports_it(run, workdir):
    """CATCHES: attributing every missing module to the entry file instead of the dependency whose own `import Units` statement failed to resolve."""
    write_files(workdir, {"main.pyfun": "import Geometry\nprint (Geometry.area 1 2)\n",
                          "geometry.pyfun": "import Units\nlet area w h = w * h\n"})
    expect(run(["check", "main.pyfun"]), 1,
           err=b"error: cannot find module `Units` (expected `units.pyfun`), imported by `Geometry`\n")


def test_an_import_cycle_is_listed_from_the_entry_around_the_loop(run, workdir):
    """CATCHES: cycle detection that loops forever, accepts the cycle, or lists the modules in the wrong order or without repeating the start."""
    write_files(workdir, {"a.pyfun": "import B\nlet a = 1\n", "b.pyfun": "import C\nlet b = 1\n",
                          "c.pyfun": "import A\nlet c = 1\n"})
    expect(run(["check", "a.pyfun"]), 1, err=b"error: import cycle: A -> B -> C -> A\n")
    expect(run(["compile", "b.pyfun"]), 1, err=b"error: import cycle: B -> C -> A -> B\n")
    expect(run(["run", "c.pyfun"]), 1, err=b"error: import cycle: C -> A -> B -> C\n")


def test_a_cycle_below_the_entry_starts_where_the_loop_begins(run, workdir):
    """CATCHES: a cycle report that includes the acyclic prefix (Main) instead of starting at the first module on the loop, A -> B -> A."""
    write_files(workdir, {"main.pyfun": "import A\nlet m = 1\n", "a.pyfun": "import B\nlet a = 1\n",
                          "b.pyfun": "import A\nlet b = 1\n"})
    expect(run(["check", "main.pyfun"]), 1, err=b"error: import cycle: A -> B -> A\n")


def test_a_module_importing_itself_or_the_entry_is_a_cycle(run, workdir):
    """CATCHES: a self-import treated as a no-op, or an import of the entry module by its dependency loaded as a second copy instead of a cycle."""
    write_files(workdir, {"selfish.pyfun": "import Selfish\nlet a = 1\n", "main.pyfun": "import Util\nlet m = 1\n",
                          "util.pyfun": "import Main\nlet u = 1\n"})
    expect(run(["check", "selfish.pyfun"]), 1, err=b"error: import cycle: Selfish -> Selfish\n")
    expect(run(["compile", "main.pyfun"]), 1, err=b"error: import cycle: Main -> Util -> Main\n")


def test_a_parse_error_in_an_imported_module_is_rendered_against_its_source(run, workdir):
    """CATCHES: rendering an imported module's parse error against the entry's text (wrong line/snippet) or only as raw byte offsets."""
    write_files(workdir, {"main.pyfun": "import Broken\nlet x = 1\n", "broken.pyfun": "let a = 1\nlet b = 2\nlet = 3\n"})
    expect(run(["check", "main.pyfun"]), 1, err="imported_parse_error.err")
    expect(run(["compile", "main.pyfun", "-o", "out"]), 1, err="imported_parse_error.err")
    expect(run(["run", "main.pyfun"]), 1, err="imported_parse_error.err")
    assert listing(workdir) == listing_of({"main.pyfun": "", "broken.pyfun": ""})


def test_a_lex_error_in_an_imported_module_is_rendered_against_its_source(run, workdir):
    """CATCHES: a lexer failure in a dependency (an unterminated string) that crashes, is ignored, or is shown with the entry file's snippet."""
    write_files(workdir, {"main.pyfun": "import Greet\nprint Greet.hello\n",
                          "greet.pyfun": "let hello = \"hi\"\nlet bye = \"unterminated\n"})
    expect(run(["check", "main.pyfun"]), 1, err="imported_lex_error.err")


def test_graph_errors_are_reported_before_type_checking(run, workdir):
    """CATCHES: type-checking modules before the whole graph resolves, so the entry's type error is shown alongside or instead of the missing module."""
    write_files(workdir, {"main.pyfun": "import Geometry\nimport Missing\nlet bad = 1 + \"s\"\n", "geometry.pyfun": GEOMETRY})
    expect(run(["check", "main.pyfun"]), 1,
           err=b"error: cannot find module `Missing` (expected `missing.pyfun`), imported by `Main`\n")


def test_the_first_failing_import_in_depth_first_order_is_reported(run, workdir):
    """CATCHES: a resolver that visits imports breadth-first or in reverse, reporting the later broken module instead of the earlier one's missing dependency."""
    write_files(workdir, {"main.pyfun": "import Left\nimport Right\nlet m = 1\n",
                          "left.pyfun": "import Deep\nlet l = 1\n", "right.pyfun": "let = 1\n"})
    expect(run(["check", "main.pyfun"]), 1,
           err=b"error: cannot find module `Deep` (expected `deep.pyfun`), imported by `Left`\n")


# =================================================================== type errors across modules


def test_type_errors_are_grouped_by_module_with_a_total(run, workdir):
    """CATCHES: errors not grouped under `-- module` headers, rendered against the wrong module's source, counted per module, or compile/run proceeding anyway."""
    files = {"main.pyfun": "import Geometry\nimport Util\nlet bad = Geometry.area 4 \"five\"\nlet v = Geometry.volume 1 2\nprint (Util.id 3)\n",
             "geometry.pyfun": "let area w h = w * h\nlet oops = 1 + \"x\"\n",
             "util.pyfun": "let id x = x\n"}
    write_files(workdir, files)
    expect(run(["check", "main.pyfun"]), 1, err="grouped_errors.err")
    expect(run(["compile", "main.pyfun", "-o", "out"]), 1, err="grouped_errors.err")
    expect(run(["run", "main.pyfun"]), 1, err="grouped_errors.err")
    assert listing(workdir) == listing_of(files)


def test_a_single_project_error_uses_the_singular_count(run, workdir):
    """CATCHES: a hard-coded plural `1 errors` summary, or a project error reported without the module header for the importing module."""
    write_files(workdir, {"main.pyfun": "import Geometry\nlet bad = Geometry.area 4 \"five\"\n", "geometry.pyfun": GEOMETRY})
    expect(run(["check", "main.pyfun"]), 1, err="single_error.err")


def test_an_error_in_a_dependency_is_reported_under_its_own_header(run, workdir):
    """CATCHES: stopping at the entry, or blaming the importer, when only the imported module has a type error; its exports must still serve the entry."""
    write_files(workdir, {"main.pyfun": "import Geometry\nprint (Geometry.area 2 3)\n",
                          "geometry.pyfun": "let area w h = w * h\nlet broken = area \"a\" 1\n"})
    expect(run(["check", "main.pyfun"]), 1, err="dependency_error.err")


def test_unknown_members_are_not_a_member_errors_in_the_importer(run, workdir):
    """CATCHES: leaking members that a module does not export, or that come from a module never imported, instead of the `is not a member of` error."""
    write_files(workdir, {"main.pyfun": "import Geometry\nlet v = Geometry.volume 1 2\nlet w = Geometry.Widget { x = 1 }\nlet c = Shape.Circle 2.0\nlet r = Mathx.fabs 1.0\n",
                          "geometry.pyfun": "type Point = { x: int, y: int }\nlet area w h = w * h\n",
                          "shape.pyfun": "type Shape = Circle float | Rect float float\n",
                          "mathx.pyfun": "extern fabs : float -> float = math.fabs\n"})
    expect(run(["check", "main.pyfun"]), 1, err="not_a_member.err")


def test_a_cross_module_match_must_be_exhaustive(run, workdir):
    """CATCHES: exhaustiveness skipped for imported sum types, or a witness that names the constructor unqualified instead of `Shape.Rect _ _`."""
    write_files(workdir, {"main.pyfun": "import Shape\nlet f s =\n  match s:\n    case Shape.Circle r: r\n",
                          "shape.pyfun": "type Shape = Circle float | Rect float float\n"})
    expect(run(["check", "main.pyfun"]), 1, err="non_exhaustive.err")


def test_an_imported_opaque_type_is_distinct_from_its_representation(run, workdir):
    """CATCHES: erasing the nominal wall of an imported `opaque type`, so a raw string is wrongly accepted where `Ids.UserId` is expected."""
    write_files(workdir, {"main.pyfun": "import Ids\nlet bad = Ids.greet \"raw\"\n",
                          "ids.pyfun": "opaque type UserId = string\nlet greet u =\n  match u:\n    case UserId s: s\n"})
    expect(run(["check", "main.pyfun"]), 1, err="newtype_distinct.err")


def test_an_imported_record_needs_a_qualified_tag(run, workdir):
    """CATCHES: letting a bare `Point { ... }` construct an imported record, which would compile to an undefined Python name."""
    write_files(workdir, {"main.pyfun": "import Geometry\nlet p = Point { x = 1, y = 2 }\n",
                          "geometry.pyfun": "type Point = { x: int, y: int }\n"})
    expect(run(["check", "main.pyfun"]), 1, err="bare_record_tag.err")


def test_a_field_shared_by_a_local_and_an_imported_record_is_ambiguous(run, workdir):
    """CATCHES: silently picking one record when a local and an imported record both declare `x` and the access gives no type."""
    write_files(workdir, {"main.pyfun": "import Geometry\ntype Vec = { x: int, z: int }\nlet get p = p.x\n",
                          "geometry.pyfun": "type Point = { x: int, y: int }\n"})
    expect(run(["check", "main.pyfun"]), 1, err="ambiguous_field.err")


def test_an_unknown_qualified_type_is_reported_once(run, workdir):
    """CATCHES: stripping an unknown qualifier to a bare name, or cascading extra errors, when a module exports no type of that name."""
    write_files(workdir, {"records.pyfun": "import Shapes\ntype Holder = { item: Shapes.Widget }\n",
                          "shapes.pyfun": "type Placed = { row: int, col: int }\n",
                          "handles.pyfun": "import Gen\ntype Holder = { h: Gen.Nope }\n",
                          "gen.pyfun": "extern type Rng\nextern newRng : int -> Rng = random.Random\n"})
    expect(run(["check", "records.pyfun"]), 1, err="unknown_qualified_type_record.err")
    expect(run(["check", "handles.pyfun"]), 1, err="unknown_qualified_type_opaque.err")


def test_a_local_type_clashing_with_an_imported_type_is_reported(run, workdir):
    """CATCHES: a local `type Rng` silently conflated with the imported extern type `Gen.Rng` instead of the import clash error."""
    write_files(workdir, {"main.pyfun": "import Gen\ntype Rng = A | B\nlet x = A\n",
                          "gen.pyfun": "extern type Rng\nextern newRng : int -> Rng = random.Random\n"})
    expect(run(["check", "main.pyfun"]), 1, err="opaque_clash.err")


def test_imported_type_names_must_not_clash(run, workdir):
    """CATCHES: an imported sum type or record silently merged with a same-named local type, or two imports both exporting `Color` accepted without a clash."""
    write_files(workdir, {"shapes.pyfun": "type Shape = Circle int | Rect int int\n",
                          "localsum.pyfun": "import Shapes\ntype Shape = Dot | Line\nlet x = Dot\n",
                          "geometry.pyfun": "type Point = { x: int, y: int }\n",
                          "localrec.pyfun": "import Geometry\ntype Point = { a: int }\nlet x = Point { a = 1 }\n",
                          "pa.pyfun": "type Color = Red | Green\n", "pb.pyfun": "type Color = Blue | Red\n",
                          "twoimports.pyfun": "import Pa\nimport Pb\nlet x = Pa.Red\n"})
    expect(run(["check", "localsum.pyfun"]), 1, err="clash_sum.err")
    expect(run(["check", "localrec.pyfun"]), 1, err="clash_record.err")
    expect(run(["check", "twoimports.pyfun"]), 1, err="clash_two_imports.err")


def test_an_imported_function_that_spawns_needs_a_task_scope(run, workdir):
    """CATCHES: losing the `spawn` effect of an imported function at the module boundary, so starting its task at top level outside `Task.scope` is accepted."""
    jobs = "let worker name = async {\n  do! Async.sleep 0.0\n  print name\n}\nlet launch name = Task.start (worker name)\n"
    write_files(workdir, {"jobs.pyfun": jobs, "main.pyfun": "import Jobs\nJobs.launch \"x\"\n"})
    expect(run(["check", "main.pyfun"]), 1, err="spawn_outside_scope.err")


def test_mutually_recursive_functions_are_exported_as_a_group(run, workdir):
    """CATCHES: a mutually recursive group (`isEven`/`isOdd`) that type-checks in its own module but is missing from or mistyped in its exported interface."""
    parity = "let isEven n = if n == 0 then true else isOdd (n - 1)\nlet isOdd n = if n == 0 then false else isEven (n - 1)\n"
    write_files(workdir, {"parity.pyfun": parity, "main.pyfun": "import Parity\nprint (Parity.isEven 10)\nprint (Parity.isOdd 4)\n"})
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")
    expect(run(["run", "main.pyfun"]), 0, out=b"True\nFalse\n")


def test_measures_cross_only_through_imports_and_aliases_must_agree(run, workdir):
    """CATCHES: measures leaking without an import, or two imports defining alias `N` differently being merged instead of reported as a conflict."""
    write_files(workdir, {"conflict.pyfun": "import Ua\nimport Ub\nlet x = 1\n",
                          "ua.pyfun": "measure m\nmeasure s\nmeasure N = m / s\n",
                          "ub.pyfun": "measure m\nmeasure s\nmeasure N = m s\n",
                          "unimported.pyfun": "import Dist\nlet d = 100<m>\n",
                          "units.pyfun": "measure m\nmeasure s\nmeasure N = m / s\n",
                          "dist.pyfun": "import Units\nlet far d = d + 1<m>\n",
                          "shared.pyfun": "import Units\nimport Dist\nlet here = 100<m>\nlet f = 10<N>\nlet g = Dist.far 5<m>\n",
                          "va.pyfun": "measure m\nlet a = 1<m>\n", "vb.pyfun": "measure m\nlet b = 2<m>\n",
                          "both.pyfun": "import Va\nimport Vb\nlet x = Va.a + Vb.b\n"})
    expect(run(["check", "conflict.pyfun"]), 1, err="measure_alias_conflict.err")
    expect(run(["check", "unimported.pyfun"]), 1, err="measure_unimported.err")
    expect(run(["check", "shared.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")
    expect(run(["check", "both.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")


def test_an_imported_extern_keeps_its_effect(run, workdir):
    """CATCHES: dropping the `io` effect of an imported impure extern at the module boundary, so a `let pure` caller is wrongly accepted."""
    logx = "extern log : string -> unit = builtins.print\nextern pure ident : int -> int = builtins.abs\n"
    write_files(workdir, {"logx.pyfun": logx, "bad.pyfun": "import Logx\nlet pure bad s = Logx.log s\n",
                          "good.pyfun": "import Logx\nlet pure ok n = Logx.ident n\nprint (ok (-3))\n"})
    expect(run(["check", "bad.pyfun"]), 1, err="impure_extern.err")
    expect(run(["run", "good.pyfun"]), 0, out=b"3\n")


def test_a_carried_record_cannot_be_built_or_matched_without_its_module(run, workdir):
    """CATCHES: treating a transitively carried record as a member (constructible, matchable) without a direct import of its declaring module."""
    write_files(workdir, {"inner.pyfun": INNER, "middle.pyfun": MIDDLE,
                          "main.pyfun": "import Middle\nlet bad = Inner.Config { cSize = 1 }\nlet bad2 = Config { cSize = 1 }\nlet f w =\n  match w:\n    case Config { cSize = n }: n\n"})
    expect(run(["check", "main.pyfun"]), 1, err="carried_construct.err")


def test_a_shadowed_carried_record_names_its_declaring_module(run, workdir):
    """CATCHES: a hidden carried record giving a bare `no field` message (or a clash error) instead of naming module `Inner` where it is declared."""
    write_files(workdir, {"inner.pyfun": INNER, "middle.pyfun": MIDDLE,
                          "main.pyfun": "import Middle\ntype Config = { other: int }\nlet x = Middle.mk 5\nlet bad = x.wConf.cSize\nlet get w = w.cSize\n"})
    expect(run(["check", "main.pyfun"]), 1, err="carried_shadowed.err")


def test_two_carried_records_sharing_a_field_are_ambiguous(run, workdir):
    """CATCHES: resolving a by-name field access to an arbitrary carried record when two carried records alone declare `size`."""
    write_files(workdir, {"twin.pyfun": "type A = { size: int }\ntype B = { size: bool }\nlet mkA n = A { size = n }\nlet mkB b = B { size = b }\n",
                          "carry.pyfun": "import Twin\ntype WrapA = { wa: Twin.A }\ntype WrapB = { wb: Twin.B }\nlet mka n = WrapA { wa = Twin.mkA n }\nlet mkb b = WrapB { wb = Twin.mkB b }\n",
                          "main.pyfun": "import Carry\nlet get w = w.size\n"})
    expect(run(["check", "main.pyfun"]), 1, err="carried_ambiguous.err")


def test_well_typed_cross_module_interfaces_check_clean(run, workdir):
    """CATCHES: spurious errors for transitively carried opaque types and records, mutually referencing records, diamonds, or qualified-vs-bare type spellings."""
    write_files(workdir, {
        "inner.pyfun": INNER, "middle.pyfun": MIDDLE,
        "gen.pyfun": "extern type Rng\nextern newRng : int -> Rng = random.Random\nlet make seed = newRng seed\n",
        "relay.pyfun": "import Gen\nlet fresh n = Gen.make n\n",
        "opaque.pyfun": "import Relay\ntype H = { h: Rng }\nlet x = H { h = Relay.fresh 1 }\n",
        "mutual.pyfun": "type A = { av: int, ab: Option B }\ntype B = { bv: int, ba: Option A }\nlet mkA n = A { av = n, ab = None }\nlet mkB n = B { bv = n, ba = Some (mkA n) }\n",
        "hop.pyfun": "import Mutual\nlet make n = Mutual.mkB n\n",
        "cyclic.pyfun": "import Hop\nlet b = Hop.make 3\nlet v = b.bv\nlet w = Option.map (fun a -> a.av) b.ba\n",
        "left.pyfun": "import Inner\ntype LWrap = { lc: Inner.Config }\nlet mkL n = LWrap { lc = Inner.make n }\n",
        "right.pyfun": "import Inner\ntype RWrap = { rc: Inner.Config }\nlet mkR n = RWrap { rc = Inner.make n }\n",
        "diamond.pyfun": "import Left\nimport Right\nlet a = (Left.mkL 1).lc.cSize\nlet b = (Right.mkR 2).rc.cSize\n",
        "direct.pyfun": "import Inner\nimport Middle\nlet x = Middle.mk 5\nlet a = x.wConf.cSize\nlet mine = Inner.Config { cSize = 1 }\n",
        "tiered.pyfun": "import Middle\ntype Local = { cSize: bool, other: int }\nlet get w = w.cSize\nlet v = get (Local { cSize = true, other = 1 })\n",
        "shapes.pyfun": "type Placed = { row: int, col: int }\n",
        "spelling.pyfun": "import Shapes\nextern pure widen : Shapes.Placed -> Placed = builtins.id\nlet same p = widen p\n",
    })
    expect(run(["check", "opaque.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")
    expect(run(["check", "cyclic.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")
    expect(run(["check", "diamond.pyfun"]), 0, err=b"ok: no type errors (4 modules)\n")
    expect(run(["check", "direct.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")
    expect(run(["check", "tiered.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")
    expect(run(["check", "spelling.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")


# =================================================================== lowering across modules


def test_a_cross_module_sum_type_constructs_and_matches(run, workdir):
    """CATCHES: imported constructors redefined locally or left unqualified, so `shape.Circle` patterns would not match values built by the other module."""
    write_files(workdir, {"shape.pyfun": "type Shape = Circle int | Rect int int\n",
                          "main.pyfun": "import Shape\nlet area s =\n  match s:\n    case Shape.Circle r: r * r\n    case Shape.Rect w h: w * h\nprint (area (Shape.Circle 3))\nprint (area (Shape.Rect 4 5))\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="adt.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"9\n20\n")


def test_imported_nullary_constructors_use_the_exporting_singletons(run, workdir):
    """CATCHES: an imported nullary constructor emitted as a bare class reference (not an instance) or a fresh object instead of `color._Green`."""
    write_files(workdir, {"color.pyfun": "type Color = Red | Green | Blue\n",
                          "main.pyfun": "import Color\nlet name k =\n  match k:\n    case Color.Red: \"r\"\n    case Color.Green: \"g\"\n    case Color.Blue: \"b\"\nlet last xs =\n  match List.last xs:\n    case Some c: name c\n    case None: \"-\"\nprint (last [Color.Green, Color.Red])\nprint (last [])\nprint (Color.Red == Color.Red)\nprint (Set.len (Set.ofList [Color.Red, Color.Red, Color.Blue]))\n"})
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=b"wrote 3 files to out\n")
    expect_tree(workdir / "out", "nullary")
    expect(run(["run", "main.pyfun"]), 0, out=b"r\n-\nTrue\n2\n")


def test_a_nullary_constructor_is_called_when_its_singleton_name_is_taken(run, workdir):
    """CATCHES: referencing `color._Green` even though the defining module binds `_Green` itself, which would hand the importer the integer 1."""
    write_files(workdir, {"color.pyfun": "type Color = Red | Green | Blue\nlet _Green = 1\n",
                          "main.pyfun": "import Color\nlet favourite = Color.Green\nlet red = Color.Red\nprint favourite\nprint red\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="nullary_taken.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"Green\nRed\n")


def test_a_cross_module_record_constructs_updates_and_matches(run, workdir):
    """CATCHES: an imported record class redefined in the consumer, built with fields out of declared order, or updated through the wrong class."""
    write_files(workdir, {"geometry.pyfun": "type Point = { x: int, y: int }\nlet origin = Point { x = 0, y = 0 }\nlet mag p = p.x + p.y\n",
                          "main.pyfun": "import Geometry\nlet p = Geometry.Point { y = 4, x = 3 }\nlet shifted = { p with x = 10 }\nlet describe q =\n  match q:\n    case Geometry.Point { x = 0, y }: y\n    case Geometry.Point { x, y }: x + y\nprint (describe p)\nprint shifted.x\nprint (Geometry.mag p)\nprint (describe Geometry.origin)\nprint shifted\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="record.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"7\n10\n7\n0\nPoint(x=10, y=4)\n")


def test_a_parameterised_imported_record_instantiates_freshly(run, workdir):
    """CATCHES: an imported polymorphic record `Box a` fixed to one instantiation, so using it at int and at string in one module is rejected."""
    write_files(workdir, {"store.pyfun": "type Box a = { item: a, label: string }\n",
                          "main.pyfun": "import Store\nlet b = Store.Box { item = 42, label = \"answer\" }\nlet c = Store.Box { item = \"s\", label = \"text\" }\nprint b.item\nprint c.item\nprint b.label\n"})
    expect(run(["run", "main.pyfun"]), 0, out=b"42\ns\nanswer\n")


def test_a_local_type_can_name_an_imported_type_bare_or_qualified(run, workdir):
    """CATCHES: rejecting `Shapes.Placed` or bare `Placed` inside local type declarations, or treating the two spellings as different types."""
    write_files(workdir, {"shapes.pyfun": "type Placed = { row: int, col: int }\nlet mk r = Placed { row = r, col = r }\nlet rowOf p = p.row\n",
                          "main.pyfun": "import Shapes\ntype Holder = { item: Shapes.Placed, tag: string }\ntype Slot = Empty | Filled Placed\nlet describe s =\n  match s:\n    case Empty: 0\n    case Filled p: Shapes.rowOf p\nlet h = Holder { item = Shapes.mk 3, tag = \"a\" }\nprint h.tag\nprint (describe (Filled h.item))\nprint (describe Empty)\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="imported_type_in_decl.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"a\n3\n0\n")


def test_an_imported_extern_is_bound_in_its_module_and_curries(run, workdir):
    """CATCHES: erasing an imported extern so `mathx.fabs` does not exist at run time, or losing its arity so a partial application is miscalled."""
    write_files(workdir, {"mathx.pyfun": "extern fabs : float -> float = math.fabs\n",
                          "main.pyfun": "import Mathx\nlet r = Mathx.fabs (-8.0)\nprint r\nprint (List.map Mathx.fabs [-1.5, 2.0])\n"})
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=b"wrote 2 files to out\n")
    expect_tree(workdir / "out", "extern")
    expect(run(["run", "main.pyfun"]), 0, out=b"8.0\n[1.5, 2.0]\n")


def test_cross_module_measures_erase_to_plain_numbers(run, workdir):
    """CATCHES: unit-annotated values from a shared measure module emitted with leftover unit syntax or wrapped instead of plain Python numerics."""
    write_files(workdir, {"units.pyfun": "measure m\n",
                          "main.pyfun": "import Units\nlet d = 100<m>\nlet e = d + 50<m>\nprint e\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="measures.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"150\n")


def test_an_imported_opaque_type_erases_in_every_module(run, workdir):
    """CATCHES: a cross-module newtype that emits a class or a wrapper call on either side, or whose first-class constructor is not the identity."""
    write_files(workdir, {"ids.pyfun": "opaque type UserId = string\nlet greet u =\n  match u:\n    case UserId s: String.concat \"hi \" s\n",
                          "main.pyfun": "import Ids\nlet uid = Ids.UserId \"ana\"\nlet unwrapped =\n  match uid:\n    case Ids.UserId s: s\nlet mapped = List.map Ids.UserId [\"a\", \"b\"]\nprint (Ids.greet uid)\nprint unwrapped\nprint (List.len mapped)\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="newtype.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"hi ana\nana\n2\n")


def test_an_extern_type_can_be_named_across_the_boundary(run, workdir):
    """CATCHES: an `extern type` whose name does not cross with its module's interface, so the consumer's record field `Gen.Rng` is an unknown type."""
    write_files(workdir, {"gen.pyfun": "extern type Rng\nextern newRng : int -> Rng = random.Random\nlet make seed = newRng seed\n",
                          "main.pyfun": "import Gen\ntype Holder = { h: Gen.Rng }\nlet x = Holder { h = Gen.make 1 }\nprint \"ok\"\n"})
    expect(run(["run", "main.pyfun"]), 0, out=b"ok\n")


def test_a_transitive_record_update_uses_the_declaring_class(run, workdir):
    """CATCHES: rebuilding a carried record through a class the consumer never imported, without hoisting `import inner`, so the update raises NameError."""
    write_files(workdir, {"inner.pyfun": INNER, "middle.pyfun": MIDDLE,
                          "main.pyfun": "import Middle\nlet x = Middle.mk 5\nlet y = { x with wConf.cSize = 9 }\nlet z = { x.wConf with cSize = 7 }\nprint y.wConf.cSize\nprint z.cSize\nprint (Middle.size y)\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="transitive_update.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"9\n7\n9\n")


def test_a_transitive_record_field_is_readable_at_any_depth(run, workdir):
    """CATCHES: an interface closure that carries records only one hop, so a field declared three imports away is an unknown record field."""
    write_files(workdir, {"deep.pyfun": "type Core = { cv: int }\nlet mkCore n = Core { cv = n }\n",
                          "mid.pyfun": "import Deep\ntype Two = { w1: Deep.Core }\nlet mk2 n = Two { w1 = Deep.mkCore n }\n",
                          "top.pyfun": "import Mid\ntype Three = { w2: Mid.Two }\nlet mk3 n = Three { w2 = Mid.mk2 n }\n",
                          "main.pyfun": "import Top\nlet x = Top.mk3 7\nprint x.w2.w1.cv\n"})
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (4 modules)\n")
    expect(run(["run", "main.pyfun"]), 0, out=b"7\n")


def test_a_carried_record_does_not_break_a_local_field_access(run, workdir):
    """CATCHES: a record two imports away (never named here) capturing the local record's field name, making a working `p.size` ambiguous or mistyped."""
    write_files(workdir, {"inner.pyfun": "type Config = { size: int }\nlet make n = Config { size = n }\n",
                          "middle.pyfun": "import Inner\ntype Wrap = { wConf: Inner.Config }\nlet mk n = Wrap { wConf = Inner.make n }\n",
                          "main.pyfun": "import Middle\ntype Local = { size: bool }\nlet f p = p.size\nprint (f (Local { size = true }))\n"})
    expect(run(["run", "main.pyfun"]), 0, out=b"True\n")


def test_a_binding_named_like_a_module_aliases_the_import(run, workdir):
    """CATCHES: emitting `import ids` and then `ids = [...]`, which clobbers the module object so the later `ids.greet` call fails at run time."""
    write_files(workdir, {"ids.pyfun": "let greet s = String.concat \"hi \" s\nlet tag = \"x\"\n",
                          "main.pyfun": "import Ids\nlet ids = [1, 2, 3]\nlet g = Ids.greet \"ana\"\nprint g\nprint (List.len ids)\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="alias_collision.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"hi ana\n3\n")


def test_local_binders_named_like_a_module_also_alias_the_import(run, workdir):
    """CATCHES: only top-level bindings triggering the import alias, so a parameter, lambda, match capture or CE binder named `ids` shadows the module."""
    main = """\
import Ids
let viaParam ids = List.map (fun n -> Ids.greet n) ids
let hoisted u =
    let g = Ids.greet u
    let ids = [1, 2]
    List.len ids + String.len g
let viaLambda xs = List.map (fun ids -> Ids.greet ids) xs
let fromMatch xs =
  match xs:
    case [ids]: Ids.greet ids
    case _: "none"
let fromCe =
  result {
    let! ids = Ok [1]
    return Ids.greet "g"
  }
let topLevel =
  match ["f"]:
    case [ids]: Ids.greet ids
    case _: "none"
print (List.len (viaParam ["a", "b"]))
print (hoisted "c")
print (List.len (viaLambda ["d"]))
print (fromMatch ["e"])
print (Result.withDefault "err" fromCe)
print topLevel
"""
    write_files(workdir, {"ids.pyfun": "let greet s = String.concat \"hi \" s\n", "main.pyfun": main})
    expect(run(["compile", "main.pyfun"]), 0, out="alias_local_collision.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"2\n6\n1\nhi e\nhi g\nhi f\n")


def test_a_member_named_after_a_python_builtin_is_mangled_on_both_sides(run, workdir):
    """CATCHES: mangling `set`/`len` in the defining module but not at the importer's `helper.set_` reference (or vice versa), an AttributeError at run time."""
    write_files(workdir, {"helper.pyfun": "let set = 41\nlet len xs = List.len xs\n",
                          "main.pyfun": "import Helper\nprint (Helper.set + 1)\nprint (Helper.len [\"a\", \"b\"])\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="builtin_names.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"42\n2\n")


def test_a_module_that_only_matches_an_imported_option_imports_the_runtime(run, workdir):
    """CATCHES: importing Some/None_ from _pyfun_rt only in modules that construct an Option, so a module that merely matches one raises NameError."""
    write_files(workdir, {"helper.pyfun": "let firstOf xs = List.get 0 xs\n",
                          "main.pyfun": "import Helper\nlet probe xs =\n  match Helper.firstOf xs:\n    case None: \"none\"\n    case Some k: k\nprint (probe [\"A\", \"B\"])\nprint (probe [])\n"})
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=b"wrote 3 files to out\n")
    expect_tree(workdir / "out", "option_match_only")
    expect(run(["run", "main.pyfun"]), 0, out=b"A\nnone\n")


def test_imported_polymorphic_functions_instantiate_per_use(run, workdir):
    """CATCHES: imported schemes not generalised or sharing type variables with the importer, so a second use at another type is rejected."""
    write_files(workdir, {"util.pyfun": "let id x = x\nlet id2 y = y\n",
                          "middle.pyfun": "import Util\nlet f0 a b = (a, b)\nlet f1 a b = (a, b)\n",
                          "main.pyfun": "import Util\nimport Middle\nlet f0 a b = (a, b)\nlet f1 a b = (a, b)\nprint (Util.id 1)\nprint (Util.id \"hi\")\nprint (f1 1 2)\nprint (f1 \"x\" \"y\")\nprint (Middle.f1 3 4)\nprint (Middle.f1 \"p\" \"q\")\n"})
    expect(run(["run", "main.pyfun"]), 0, out=b"1\nhi\n(1, 2)\n('x', 'y')\n(3, 4)\n('p', 'q')\n")


def test_a_task_started_in_one_module_joins_a_scope_opened_in_another(run, workdir):
    """CATCHES: per-module copies of the task-scope context variable instead of the shared `_pf_scope` in _pyfun_rt.py, so the scope never sees the tasks."""
    write_files(workdir, {"jobs.pyfun": "let worker name = async {\n  do! Async.sleep 0.0\n  print name\n}\nlet launch name = Task.start (worker name)\n",
                          "main.pyfun": "import Jobs\nextern runAsync: Async a -> a = asyncio.run\nlet session = Task.scope (async {\n  Jobs.launch \"x\"\n  Jobs.launch \"y\"\n  return 7\n})\nprint (runAsync session)\n"})
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=b"wrote 3 files to out\n")
    expect_tree(workdir / "out", "task_scope")
    expect(run(["run", "main.pyfun"]), 0, out=b"x\ny\n7\n")


def test_an_imported_async_extern_stays_cold(run, workdir):
    """CATCHES: an imported async extern bound as a plain call (hot coroutine reused) so awaiting the same value twice fails or runs once."""
    write_files(workdir, {"clock.pyfun": "extern runAsync: Async a -> a = asyncio.run\nextern pause: float -> Async unit = asyncio.sleep\n",
                          "main.pyfun": "import Clock\nlet tick = Clock.pause 0.0\nlet twice = async {\n  do! tick\n  do! tick\n  return 2\n}\nprint (Clock.runAsync twice)\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="async_extern.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"2\n")


def test_derived_codecs_cross_a_module_import(run, workdir):
    """CATCHES: an auto codec descriptor that names the importer's (nonexistent) classes instead of `rules.View`/`rules.Guest`, breaking encode/decode round-trips."""
    rules = """\
type Placed = { letter: string, score: int }
type Player = Ann | Bob | Guest string
let _Ann = 0
type View = { board: Map (int, int) Placed, turn: Option Player }
let sample = View { board = Map.ofList [((1, 2), Placed { letter = "Q", score = 10 })], turn = Some Bob }
"""
    main = """\
import Rules
type Seat = { who: Rules.Player, at: int }
let wire = Encode.auto Rules.sample
print wire
let back = Decode.decodeString Decode.auto wire
match back:
  case Ok v: print (v == Rules.sample)
  case Error e: print e.errorMessage
let seats = [Seat { who = Rules.Guest "zed", at = 1 }, Seat { who = Rules.Ann, at = 2 }, Seat { who = Rules.Bob, at = 3 }]
let seatWire = Encode.auto seats
print seatWire
match Decode.decodeString Decode.auto seatWire:
  case Ok v: print (v == seats)
  case Error e: print e.errorMessage
"""
    write_files(workdir, {"rules.pyfun": rules, "main.pyfun": main})
    expect(run(["compile", "main.pyfun"]), 0, out="codecs.out")
    expect(run(["run", "main.pyfun"]), 0,
           out=b'{"board": [[[1, 2], {"letter": "Q", "score": 10}]], "turn": {"type": "Bob"}}\nTrue\n'
               b'[{"who": {"type": "Guest", "fields": ["zed"]}, "at": 1}, {"who": {"type": "Ann"}, "at": 2}, '
               b'{"who": {"type": "Bob"}, "at": 3}]\nTrue\n')


def test_imported_externs_of_every_form_are_bound_for_their_importers(run, workdir):
    """CATCHES: project-mode extern bindings that only handle plain dotted targets, so receiver methods/properties or unit-taking externs are missing or miscalled."""
    strx = """\
extern import sys
extern import operator
extern shout : string -> string = .upper()
extern realPart : int -> int = .real
extern limit : unit -> int = sys.getrecursionlimit
extern times : string -> unit -> int -> string = operator.mul
"""
    main = """\
import Strx
print (Strx.shout "hi")
print (List.map Strx.shout ["ab", "cd"])
print (Strx.realPart 5)
print (Strx.limit ())
print (Strx.times "ab" () 3)
"""
    write_files(workdir, {"strx.pyfun": strx, "main.pyfun": main})
    expect(run(["compile", "main.pyfun"]), 0, out="extern_forms.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"HI\n['AB', 'CD']\n5\n1000\nababab\n")


def test_a_lambda_bound_export_keeps_its_arity(run, workdir):
    """CATCHES: arity export that only counts `let f a b` parameters, so a partial application of `let add = fun a b -> ...` is emitted as a one-argument call."""
    write_files(workdir, {"util.pyfun": "let add = fun a b -> a + b\nlet twice = fun f x -> f (f x)\n",
                          "main.pyfun": "import Util\nlet inc = Util.add 1\nprint (inc 41)\nprint (Util.twice inc 0)\nprint (List.map (Util.add 10) [1, 2])\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="lambda_arity.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"42\n2\n[11, 12]\n")


def test_lowering_notes_name_the_module_they_come_from(run, workdir):
    """CATCHES: project lowering that drops per-module notes or prints them without the `in `Loops`:` prefix saying which module the function lives in."""
    loops = "let go n acc =\n  match n:\n    case 0: acc\n    case _: go (n - 1) (List.map (fun x -> x + n) acc)\n"
    write_files(workdir, {"loops.pyfun": loops, "main.pyfun": "import Loops\nprint (Loops.go 3 [0])\n"})
    note = (b"note: in `Loops`: `go` calls itself in tail position but keeps its recursive form: "
            b"a closure in it captures `n`\n")
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")
    expect(run(["compile", "main.pyfun"]), 0, out="notes.out", err=note)
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=note + b"wrote 2 files to out\n")
    expect_tree(workdir / "out", "notes")
    expect(run(["run", "main.pyfun"]), 0, out=b"[6]\n", err=note)


def test_a_diamond_dependency_is_emitted_once_before_its_users(run, workdir):
    """CATCHES: loading a shared dependency once per importer (duplicate shared.py banners) or emitting modules before the modules they import."""
    write_files(workdir, {"main.pyfun": "import Left\nimport Right\nprint (Left.l + Right.r)\n",
                          "left.pyfun": "import Shared\nlet l = Shared.s + 1\n",
                          "right.pyfun": "import Shared\nlet r = Shared.s + 2\n",
                          "shared.pyfun": "let s = 10\n"})
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (4 modules)\n")
    expect(run(["compile", "main.pyfun"]), 0, out="diamond.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"23\n")


def test_the_shared_runtime_is_emitted_only_when_option_or_result_is_used(run, workdir):
    """CATCHES: always emitting _pyfun_rt.py (or never), or inlining the Option classes per module so values stop being isinstance-compatible."""
    write_files(workdir, {"plain/main.pyfun": "import Geometry\nprint (Geometry.area 4 5)\n", "plain/geometry.pyfun": GEOMETRY,
                          "opt/main.pyfun": "import Geometry\nlet x = Ok (Geometry.area 2 3)\nprint (Result.withDefault 0 x)\n",
                          "opt/geometry.pyfun": GEOMETRY})
    expect(run(["compile", "plain/main.pyfun", "-o", "plain_out"]), 0, err=b"wrote 2 files to plain_out\n")
    expect_tree(workdir / "plain_out", "runtime_absent")
    expect(run(["compile", "opt/main.pyfun", "-o", "opt_out"]), 0, err=b"wrote 3 files to opt_out\n")
    expect_tree(workdir / "opt_out", "runtime_present")


def test_target_311_applies_to_every_module(run, workdir):
    """CATCHES: `--target 3.11` honoured only for the entry file, leaving PEP 701 nested-quote f-strings in imported modules that PyPy cannot parse."""
    write_files(workdir, {"greet.pyfun": "let hello name = f\"hi {String.concat \"dear \" name}!\"\n",
                          "main.pyfun": "import Greet\nlet who = \"bo\"\nprint f\"{Greet.hello who} / {String.upper \"x\"}\"\nprint (Some 1)\n"})
    expect(run(["compile", "main.pyfun", "--target", "3.11"]), 0, out="target311.out")
    expect(run(["compile", "main.pyfun", "--target", "3.12"]), 0, out="target312.out")
    expect(run(["compile", "main.pyfun"]), 0, out="target312.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"hi dear bo! / X\nSome(1)\n")


def test_native_lowering_of_a_project_uses_isinstance_ladders(run, workdir):
    """CATCHES: `--native` ignored for imported sum types or for the shared runtime (which must be the annotated native variant without total_ordering)."""
    write_files(workdir, {"shape.pyfun": "type Shape = Circle int | Rect int int\nlet describe s =\n  match s:\n    case Circle r: f\"circle {r}\"\n    case Rect w h: f\"rect {w}x{h}\"\n",
                          "main.pyfun": "import Shape\nlet area s =\n  match s:\n    case Shape.Circle r: r * r\n    case Shape.Rect w h: w * h\nlet shapes = [Shape.Circle 3, Shape.Rect 4 5]\nshapes |> List.iter (fun s -> print f\"{Shape.describe s} has area {area s}\")\nprint (List.head shapes |> Option.map area)\n"})
    expect(run(["compile", "main.pyfun", "--native", "--target", "3.11", "-o", "native"]), 0, err=b"wrote 3 files to native\n")
    expect_tree(workdir / "native", "native_shapes")
    expect(run(["run", "main.pyfun"]), 0, out=b"circle 3 has area 9\nrect 4x5 has area 20\nSome(9)\n")


def test_a_hole_in_a_project_stops_compilation_at_lowering(run, workdir):
    """CATCHES: lowering an unfilled `?todo` hole into Python, or a lowering failure that still writes the -o directory or runs the program."""
    files = {"main.pyfun": "import Geometry\nlet h = ?todo\nprint (Geometry.area 2 3)\n", "geometry.pyfun": GEOMETRY}
    write_files(workdir, files)
    message = b"error: lowering failed: cannot compile: unfilled hole `?todo`\n"
    expect(run(["compile", "main.pyfun"]), 1, err=message)
    expect(run(["compile", "main.pyfun", "-o", "out"]), 1, err=message)
    expect(run(["run", "main.pyfun"]), 1, err=message)
    assert listing(workdir) == listing_of(files)


# =================================================================== compile -o <dir>


def test_compile_creates_a_nested_output_directory(run, workdir):
    """CATCHES: `-o` creating only the last path component (failing on a missing parent) or writing the files beside the sources instead."""
    write_files(workdir, TWO_MODULES)
    expect(run(["compile", "main.pyfun", "-o", "build/py/out"]), 0, err=b"wrote 2 files to build/py/out\n")
    expect_tree(workdir / "build", "nested_out")


def test_compile_into_an_existing_directory_overwrites_only_its_own_files(run, workdir):
    """CATCHES: `-o` into an existing directory that fails, wipes unrelated files, or appends to a stale main.py instead of replacing it."""
    write_files(workdir, {**TWO_MODULES, "out/main.py": "stale = True\n", "out/notes.txt": "keep me\n"})
    expect(run(["compile", "main.pyfun", "-o", "out"]), 0, err=b"wrote 2 files to out\n")
    expect_tree(workdir / "out", "existing_out")


def test_compile_option_order_and_long_output_flag(run, workdir):
    """CATCHES: argument parsing that requires the path first or rejects `--output`, the long spelling of `-o`, for a project."""
    write_files(workdir, TWO_MODULES)
    expect(run(["compile", "-o", "first", "main.pyfun"]), 0, err=b"wrote 2 files to first\n")
    expect(run(["compile", "main.pyfun", "--output", "second"]), 0, err=b"wrote 2 files to second\n")
    assert listing(workdir / "first") == b"geometry.py\nmain.py\n"
    assert (workdir / "first" / "main.py").read_bytes() == golden(__file__, "two_modules.tree/main.py")
    assert (workdir / "first" / "geometry.py").read_bytes() == golden(__file__, "two_modules.tree/geometry.py")
    expect_tree(workdir / "second", "two_modules")


def test_compile_reports_an_output_path_that_is_a_file(run, workdir):
    """CATCHES: overwriting an existing regular file named by `-o`, or failing silently, instead of `cannot create out.txt: File exists`."""
    write_files(workdir, {**TWO_MODULES, "out.txt": "not a directory\n"})
    expect(run(["compile", "main.pyfun", "-o", "out.txt"]), 1, err=b"error: cannot create out.txt: File exists (os error 17)\n")
    assert (workdir / "out.txt").read_bytes() == b"not a directory\n"


def test_compile_reports_a_module_file_it_cannot_write(run, workdir):
    """CATCHES: ignoring a failed write (reporting success) or not naming the failing path; modules before it in topological order are already written."""
    write_files(workdir, TWO_MODULES)
    (workdir / "out" / "main.py").mkdir(parents=True)
    expect(run(["compile", "main.pyfun", "-o", "out"]), 1, err=b"error: cannot write out/main.py: Is a directory (os error 21)\n")
    assert listing(workdir / "out") == b"geometry.py\n"
    assert (workdir / "out" / "geometry.py").read_bytes() == golden(__file__, "two_modules.tree/geometry.py")


# =================================================================== run


def test_run_passes_program_arguments_with_or_without_a_separator(run, workdir):
    """CATCHES: the project `run` path dropping argv, keeping the `--` separator, or swallowing program flags like `-o`/`--help` as pyfun options."""
    main = ("import Geometry\nextern import sys\nextern getArgv : unit -> List string = sys.argv.copy\n"
            "print (Geometry.area 4 5)\nprint (List.drop 1 (getArgv ()))\n")
    write_files(workdir, {"main.pyfun": main, "geometry.pyfun": GEOMETRY})
    expect(run(["run", "main.pyfun"]), 0, out=b"20\n[]\n")
    expect(run(["run", "main.pyfun", "hello", "42"]), 0, out=b"20\n['hello', '42']\n")
    expect(run(["run", "main.pyfun", "--", "hello", "-o", "--help"]), 0, out=b"20\n['hello', '-o', '--help']\n")
    expect(run(["run", "main.pyfun", "--", "--", "x"]), 0, out=b"20\n['--', 'x']\n")
    expect(run(["run", "main.pyfun", "a", "--", "b"]), 0, out=b"20\n['a', '--', 'b']\n")


def test_run_stages_the_tree_in_a_temp_dir_and_removes_it(run, workdir, tmp_path):
    """CATCHES: `run` staging only the entry module, naming the entry script other than main.py, or leaving its temp directory behind."""
    main = """\
import Geometry
extern import sys
extern import os
extern getArgv : unit -> List string = sys.argv.copy
extern listdir : string -> List string = os.listdir
extern dirname : string -> string = os.path.dirname
extern basename : string -> string = os.path.basename
let script = getArgv () |> List.head |> Option.withDefault ""
print (basename script)
print (List.sort (listdir (dirname script)))
print (Some (Geometry.area 2 3))
"""
    write_files(workdir, {"main.pyfun": main, "geometry.pyfun": GEOMETRY})
    stage = tmp_path / "stage"
    stage.mkdir()
    r = run(["run", "main.pyfun"], env_overrides={"TMPDIR": str(stage), "PYTHONDONTWRITEBYTECODE": "1"})
    expect(r, 0, out=b"main.py\n['_pyfun_rt.py', 'geometry.py', 'main.py']\nSome(6)\n")
    assert sorted(stage.iterdir()) == []


def test_run_reports_a_failing_program_with_a_nonzero_exit(run, workdir):
    """CATCHES: the project `run` path exiting 0 when the Python program exits non-zero, or swallowing the output printed before the exit."""
    main = "import Geometry\nextern import sys\nextern exit : int -> unit = sys.exit\nprint (Geometry.area 2 2)\nexit 3\nprint \"after\"\n"
    write_files(workdir, {"main.pyfun": main, "geometry.pyfun": GEOMETRY})
    expect(run(["run", "main.pyfun"]), 1, out=b"4\n")


def test_run_keeps_the_callers_working_directory(run, workdir):
    """CATCHES: running the program from the entry's directory or the staging dir, so relative paths no longer mean what they meant on the command line."""
    main = "import Geometry\nextern import os\nextern listdir : string -> List string = os.listdir\nprint (List.sort (listdir \".\"))\nprint (Geometry.area 2 2)\n"
    write_files(workdir, {"sub/main.pyfun": main, "sub/geometry.pyfun": GEOMETRY, "data.txt": "x\n"})
    expect(run(["run", "sub/main.pyfun"]), 0, out=b"['data.txt', 'sub']\n4\n")


def test_run_gives_the_program_the_callers_stdin(run, workdir):
    """CATCHES: piping the compiled project to `python -` (spending stdin on the source) so the program's first `input` hits EOFError."""
    main = "import Geometry\nlet name = input \"\"\nprint (String.concat \"hello \" name)\nprint (Geometry.area 2 2)\n"
    write_files(workdir, {"main.pyfun": main, "geometry.pyfun": GEOMETRY})
    expect(run(["run", "main.pyfun"], input="world\n"), 0, out=b"hello world\n4\n")


def test_run_uses_the_interpreter_named_by_pyfun_python(run, workdir):
    """CATCHES: the project `run` path ignoring PYFUN_PYTHON, or crashing instead of reporting the interpreter that could not be started."""
    write_files(workdir, TWO_MODULES)
    expect(run(["run", "main.pyfun"], env_overrides={"PYFUN_PYTHON": "no-such-python-xyz"}), 1,
           err=b"error: `no-such-python-xyz` did not finish: No such file or directory (os error 2)\n")
    expect(run(["run", "main.pyfun"], env_overrides={"PYFUN_PYTHON": "python3"}), 0, out=b"20\n")


def test_run_reports_when_no_interpreter_is_on_path(run, workdir, tmp_path):
    """CATCHES: the project `run` path crashing or exiting 0 when neither `python` nor `python3` can be found on PATH and PYFUN_PYTHON is unset."""
    write_files(workdir, TWO_MODULES)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    expect(run(["run", "main.pyfun"], env_overrides={"PATH": str(empty)}), 1,
           err=b"error: no Python interpreter found on PATH (tried `python`, `python3`)\n")


def test_run_reports_a_temp_dir_it_cannot_create(run, workdir, tmp_path):
    """CATCHES: the project `run` path ignoring a failure to create its staging directory (TMPDIR under a regular file) and running nothing silently."""
    write_files(workdir, TWO_MODULES)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory\n")
    expect(run(["run", "main.pyfun"], env_overrides={"TMPDIR": str(blocker)}), 1,
           err=b"error: cannot create temp dir: Not a directory (os error 20)\n")
    assert blocker.read_bytes() == b"a file, not a directory\n"


def test_run_reports_a_module_it_cannot_stage_and_cleans_up(run, workdir, tmp_path):
    """CATCHES: ignoring a failed write while staging the project (running a partial tree) or leaving the half-staged temp directory behind."""
    module = "m" + "x" * 199
    write_files(workdir, {f"{module}.pyfun": "let v = 1\n", "main.pyfun": f"import M{module[1:]}\nprint M{module[1:]}.v\n"})
    # A staging root so deep that `<root>/pyfun_run_<pid>` fits in PATH_MAX but the 203-byte module file does not.
    deep = str(tmp_path / "stage")
    while len(deep) < 4000:
        deep += "/" + "d" * min(200, 4000 - len(deep) - 1)
    Path(deep).mkdir(parents=True)
    expect(run(["run", "main.pyfun"], env_overrides={"TMPDIR": deep}), 1,
           err=f"error: cannot stage {module}.py: File name too long (os error 36)\n".encode())
    assert sorted(Path(deep).iterdir()) == []


# =================================================================== entry in a subdirectory


def test_an_entry_in_a_subdirectory_resolves_its_own_siblings(run, workdir):
    """CATCHES: resolving imports against the current directory instead of the entry's directory, which here would pick the decoy top-level geometry.pyfun."""
    write_files(workdir, {"sub/main.pyfun": "import Geometry\nprint (Geometry.area 4 5)\n", "sub/geometry.pyfun": GEOMETRY,
                          "geometry.pyfun": "let area w h = w + h\n"})
    expect(run(["check", "sub/main.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")
    expect(run(["compile", "sub/main.pyfun"]), 0, out="subdir.out")
    expect(run(["compile", "sub/main.pyfun", "-o", "out"]), 0, err=b"wrote 2 files to out\n")
    expect_tree(workdir / "out", "subdir")
    expect(run(["run", "sub/main.pyfun"]), 0, out=b"20\n")


def test_errors_of_modules_in_a_subdirectory_render_their_source(run, workdir):
    """CATCHES: re-reading a broken module relative to the cwd instead of the entry's directory, losing the snippet, or a missing module in the wrong dir."""
    write_files(workdir, {"app/main.pyfun": "import Broken\nimport Geometry\nlet x = Geometry.area 1 \"y\"\n",
                          "app/broken.pyfun": "let ok = 1\nlet = 2\nlet z = 3\n", "app/geometry.pyfun": GEOMETRY,
                          "other/main.pyfun": "import Geometry\nlet x = Geometry.area 1 \"y\"\n", "other/geometry.pyfun": GEOMETRY,
                          "lonely/main.pyfun": "import Geometry\nlet x = 1\n"})
    expect(run(["check", "app/main.pyfun"]), 1, err="subdir_parse_error.err")
    expect(run(["check", "other/main.pyfun"]), 1, err="subdir_type_error.err")
    expect(run(["check", "lonely/main.pyfun"]), 1,
           err=b"error: cannot find module `Geometry` (expected `geometry.pyfun`), imported by `Main`\n")


# =================================================================== façades (pyfun.toml + .pyfun/facades)


def test_an_import_resolves_from_a_vendored_facade(run, workdir):
    """CATCHES: façade resolution not implemented (missing module), or the façade module not compiled to its own shout.py beside the entry."""
    write_files(workdir, {"pyfun.toml": MANIFEST, SHOUT_FACADE: "let loud s = String.upper s\n", "src/main.pyfun": SHOUT_MAIN})
    expect(run(["check", "src/main.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")
    expect(run(["compile", "src/main.pyfun"]), 0, out="facade.out")
    expect(run(["compile", "src/main.pyfun", "-o", "build"]), 0, err=b"wrote 2 files to build\n")
    expect_tree(workdir / "build", "facade")
    expect(run(["run", "src/main.pyfun"]), 0, out=b"HI\n")


def test_a_project_module_wins_over_a_facade_of_the_same_name(run, workdir):
    """CATCHES: searching façades before sibling files, so a vendored shout.pyfun overrides the project's own module of the same name."""
    write_files(workdir, {"pyfun.toml": MANIFEST, SHOUT_FACADE: "let loud s = String.upper s\n", "src/main.pyfun": SHOUT_MAIN,
                          "src/shout.pyfun": "let loud s = String.concat s \"!\"\n"})
    expect(run(["compile", "src/main.pyfun"]), 0, out="facade_shadowed.out")
    expect(run(["run", "src/main.pyfun"]), 0, out=b"hi!\n")


def test_facades_are_only_searched_inside_a_manifest_project(run, workdir):
    """CATCHES: reading .pyfun/facades without a pyfun.toml marking the root, or picking up a stray .pyfun file that is not inside a <dist>/ directory."""
    write_files(workdir, {SHOUT_FACADE: "let loud s = String.upper s\n", "src/main.pyfun": SHOUT_MAIN,
                          "rooted/pyfun.toml": MANIFEST, "rooted/.pyfun/facades/shout.pyfun": "let loud s = s\n",
                          "rooted/.pyfun/facades/pyfun-other/other.pyfun": "let x = 1\n", "rooted/main.pyfun": SHOUT_MAIN})
    message = b"error: cannot find module `Shout` (expected `shout.pyfun`), imported by `Main`\n"
    expect(run(["check", "src/main.pyfun"]), 1, err=message)
    expect(run(["run", "rooted/main.pyfun"]), 1, err=message)


def test_the_manifest_is_found_in_an_ancestor_directory(run, workdir):
    """CATCHES: looking for pyfun.toml only beside the entry file rather than walking up through its parent directories to the project root."""
    write_files(workdir, {"proj/pyfun.toml": MANIFEST, "proj/" + SHOUT_FACADE: "let loud s = String.upper s\n",
                          "proj/app/src/main.pyfun": SHOUT_MAIN})
    expect(run(["check", "proj/app/src/main.pyfun"]), 0, err=b"ok: no type errors (2 modules)\n")
    expect(run(["run", "proj/app/src/main.pyfun"]), 0, out=b"HI\n")


def test_the_nearest_manifest_marks_the_project_root(run, workdir):
    """CATCHES: continuing past the nearest pyfun.toml to an outer project's façades, instead of treating the nearest manifest as the root."""
    write_files(workdir, {"proj/pyfun.toml": MANIFEST, "proj/" + SHOUT_FACADE: "let loud s = String.upper s\n",
                          "proj/inner/pyfun.toml": '[project]\nname = "inner"\n', "proj/inner/main.pyfun": SHOUT_MAIN})
    expect(run(["check", "proj/inner/main.pyfun"]), 1,
           err=b"error: cannot find module `Shout` (expected `shout.pyfun`), imported by `Main`\n")


def test_a_facade_module_can_import_another_facade_module(run, workdir):
    """CATCHES: façade modules treated as leaves whose own imports are not resolved through the vendored directories, or emitted in the wrong order."""
    write_files(workdir, {"pyfun.toml": MANIFEST,
                          ".pyfun/facades/pyfun-strs/strs.pyfun": "import Core\nlet shout s = Core.bang (String.upper s)\n",
                          ".pyfun/facades/pyfun-strs/core.pyfun": "let bang s = String.concat s \"!\"\n",
                          "main.pyfun": "import Strs\nprint (Strs.shout \"hey\")\n"})
    expect(run(["check", "main.pyfun"]), 0, err=b"ok: no type errors (3 modules)\n")
    expect(run(["compile", "main.pyfun"]), 0, out="facade_chain.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"HEY!\n")


def test_the_textwrap_facade_example_compiles_and_runs(run, workdir):
    """CATCHES: a façade's extern keyword slots or `extern import` not lowered into the façade's own wrap.py, so the pipe-friendly wrappers fail."""
    write_files(workdir, {"pyfun.toml": '[project]\nname = "wrapdemo"\n\n[dependencies]\npyfun-textwrap = "0.1.0"\n',
                          ".pyfun/facades/pyfun-textwrap/wrap.pyfun": WRAP_FACADE,
                          "main.pyfun": "import Wrap\nlet text = \"the quick brown fox jumps over the lazy dog\"\ntext |> Wrap.fill 16 |> print\ntext |> Wrap.shorten 25 |> print\n\"a\\nb\" |> Wrap.indent \"> \" |> print\n"})
    expect(run(["compile", "main.pyfun"]), 0, out="textwrap_facade.out")
    expect(run(["run", "main.pyfun"]), 0, out=b"the quick brown\nfox jumps over\nthe lazy dog\nthe quick brown fox [...]\n> a\n> b\n")


def test_a_parse_error_in_a_facade_module_is_reported_with_offsets(run, workdir):
    """CATCHES: a broken façade module being skipped or crashing; its source is not a sibling, so the error falls back to the module name and byte offsets."""
    write_files(workdir, {"pyfun.toml": MANIFEST, SHOUT_FACADE: "let loud s =\n  String.upper s\nlet = 3\n", "src/main.pyfun": SHOUT_MAIN})
    expect(run(["check", "src/main.pyfun"]), 1,
           err=b"error: in module `Shout`: parse error: expected binding name, found `=` (at 34..35)\n")


def test_a_type_error_in_a_facade_module_is_grouped_under_its_name(run, workdir):
    """CATCHES: façade modules excluded from type checking, or their errors rendered against the wrong source or without the `-- module` header."""
    write_files(workdir, {"pyfun.toml": MANIFEST, SHOUT_FACADE: "let loud s = String.upper s\nlet bad = 1 + true\n", "src/main.pyfun": SHOUT_MAIN})
    expect(run(["check", "src/main.pyfun"]), 1, err="facade_type_error.err")
