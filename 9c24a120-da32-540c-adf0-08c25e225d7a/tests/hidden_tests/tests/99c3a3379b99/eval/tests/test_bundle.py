"""`pyfun bundle <entry> -o <dir> [--asset <file>]... [--page <fragment.html>]`: a static web page that runs
the compiled program on Pyodide. Checks the exact files written, the loader and page templates, the
summary line, and every failure path."""

import pytest

from conftest import golden, write_files

HELLO = "print 42\n"
NOTE_PROG = """let collect n acc =
  if n == 0 then acc
  else collect (n - 1) (List.concat acc [fun k -> n])
let fns = collect 3 []
print (List.len fns)
"""


def tree(root):
    """Sorted relative paths of every file under `root`."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_bundle_single_file(run, workdir):
    """CATCHES: a bundle missing one of index.html / pyfun-bundle.js / main.py, a loader that does not list
    the module and entry, a different page template or Pyodide URL, or a different summary line."""
    (workdir / "hello.pyfun").write_text(HELLO)
    r = run(["bundle", "hello.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == (b"wrote index.html to site (1 module, 0 assets); serve the directory over http and open it\n")
    assert r.returncode == 0
    site = workdir / "site"
    assert tree(site) == ["index.html", "main.py", "pyfun-bundle.js"]
    assert (site / "main.py").read_bytes() == b"print(42)\n"
    assert (site / "index.html").read_bytes() == golden(__file__, "hello_index.html.golden")
    assert (site / "pyfun-bundle.js").read_bytes() == golden(__file__, "hello_loader.js.golden")


def test_bundle_with_assets_and_page(run, workdir):
    """CATCHES: assets not copied byte-for-byte under their bare file names, the loader's ASSETS list
    missing them, the page fragment not inserted verbatim (no escaping) above the output panes, or the
    plural `assets` count being wrong."""
    write_files(workdir, {
        "hello.pyfun": HELLO,
        "data/words.txt": "alpha\nbeta\n",
        "img/logo.bin": b"\x00\x01\x02\xff\xfe binary \x80",
        "page.html": "<h1>Hi & bye</h1>\n<div id=\"app\"></div>\n",
    })
    r = run(["bundle", "hello.pyfun", "--asset", "data/words.txt", "-o", "site", "--page", "page.html",
             "--asset", "img/logo.bin"])
    assert r.stdout == b""
    assert r.stderr == (b"wrote index.html to site (1 module, 2 assets); serve the directory over http and open it\n")
    assert r.returncode == 0
    site = workdir / "site"
    assert tree(site) == ["index.html", "logo.bin", "main.py", "pyfun-bundle.js", "words.txt"]
    assert (site / "words.txt").read_bytes() == b"alpha\nbeta\n"
    assert (site / "logo.bin").read_bytes() == b"\x00\x01\x02\xff\xfe binary \x80"
    assert (site / "index.html").read_bytes() == golden(__file__, "page_index.html.golden")
    assert (site / "pyfun-bundle.js").read_bytes() == golden(__file__, "assets_loader.js.golden")


def test_bundle_one_asset_is_singular(run, workdir):
    """CATCHES: `1 assets` (wrong pluralisation) in the summary line."""
    write_files(workdir, {"hello.pyfun": HELLO, "words.txt": "x\n"})
    r = run(["bundle", "hello.pyfun", "-o", "site", "--asset", "words.txt"])
    assert r.stderr == b"wrote index.html to site (1 module, 1 asset); serve the directory over http and open it\n"
    assert (r.stdout, r.returncode) == (b"", 0)


def test_bundle_long_output_flag(run, workdir):
    """CATCHES: `--output` not being accepted as the long form of `-o` for bundle."""
    (workdir / "hello.pyfun").write_text(HELLO)
    r = run(["bundle", "--output", "out/site", "hello.pyfun"])
    assert r.stderr == (b"wrote index.html to out/site (1 module, 0 assets); serve the directory over http and open it\n")
    assert (r.stdout, r.returncode) == (b"", 0)
    assert tree(workdir / "out") == ["site/index.html", "site/main.py", "site/pyfun-bundle.js"]


def test_bundle_title_is_the_escaped_file_stem(run, workdir):
    """CATCHES: a page title taken from somewhere other than the entry's file stem, or not HTML-escaping
    `&`, `<` and `>` in it."""
    (workdir / "a&b<c>.pyfun").write_text(HELLO)
    r = run(["bundle", "a&b<c>.pyfun", "-o", "site"])
    assert r.returncode == 0
    index = (workdir / "site" / "index.html").read_bytes()
    assert index == golden(__file__, "hello_index.html.golden").replace(b"<title>hello</title>",
                                                                       b"<title>a&amp;b&lt;c&gt;</title>")


def test_bundle_entry_in_a_subdirectory_and_page_escapes_nothing(run, workdir):
    """CATCHES: a title including the directory, or a page fragment that is HTML-escaped instead of
    inserted as markup."""
    write_files(workdir, {"src/app.pyfun": HELLO, "frag.html": "<p class=\"x\">a < b & c</p>\n"})
    r = run(["bundle", "src/app.pyfun", "-o", "site", "--page", "frag.html"])
    assert r.returncode == 0
    assert (workdir / "site" / "index.html").read_bytes() == golden(__file__, "app_index.html.golden")


def test_bundle_escapes_asset_names_in_the_loader(run, workdir):
    """CATCHES: asset file names written into the loader's JSON array without escaping `"` and `\\`."""
    write_files(workdir, {"hello.pyfun": HELLO, 'we"ird\\name.txt': "odd\n"})
    r = run(["bundle", "hello.pyfun", "-o", "site", "--asset", 'we"ird\\name.txt'])
    assert r.returncode == 0
    loader = (workdir / "site" / "pyfun-bundle.js").read_bytes()
    assert loader == golden(__file__, "hello_loader.js.golden").replace(
        b"const ASSETS = [];", b'const ASSETS = ["we\\"ird\\\\name.txt"];')
    assert (workdir / "site" / 'we"ird\\name.txt').read_bytes() == b"odd\n"


def test_bundle_last_page_wins(run, workdir):
    """CATCHES: concatenating several `--page` fragments or keeping the first one."""
    write_files(workdir, {"hello.pyfun": HELLO, "one.html": "<p>one</p>\n", "two.html": "<p>two</p>\n"})
    r = run(["bundle", "hello.pyfun", "-o", "site", "--page", "one.html", "--page", "two.html"])
    assert r.returncode == 0
    index = (workdir / "site" / "index.html").read_bytes()
    assert index == golden(__file__, "hello_index.html.golden").replace(b"<body>\n\n", b"<body>\n<p>two</p>\n\n")


def test_bundle_into_an_existing_directory_keeps_other_files(run, workdir):
    """CATCHES: wiping the output directory first; the bundle only adds/overwrites its own files."""
    write_files(workdir, {"hello.pyfun": HELLO, "site/README.txt": "keep me\n", "site/main.py": "stale\n"})
    r = run(["bundle", "hello.pyfun", "-o", "site"])
    assert r.returncode == 0
    assert tree(workdir / "site") == ["README.txt", "index.html", "main.py", "pyfun-bundle.js"]
    assert (workdir / "site" / "README.txt").read_bytes() == b"keep me\n"
    assert (workdir / "site" / "main.py").read_bytes() == b"print(42)\n"


def test_bundle_project_writes_every_module(run, workdir):
    """CATCHES: bundling only the entry of a multi-module program, missing the shared runtime, or naming
    the entry `main.py` regardless of its module (the loader's ENTRY is the entry module's file)."""
    write_files(workdir, {
        "app.pyfun": "import Store\nprint (Option.withDefault 0 (Store.lookup 7))\n",
        "store.pyfun": "let lookup k = Some k\n",
    })
    r = run(["bundle", "app.pyfun", "-o", "site"])
    assert r.stderr == b"wrote index.html to site (3 modules, 0 assets); serve the directory over http and open it\n"
    assert (r.stdout, r.returncode) == (b"", 0)
    site = workdir / "site"
    assert tree(site) == ["_pyfun_rt.py", "app.py", "index.html", "pyfun-bundle.js", "store.py"]
    assert (site / "pyfun-bundle.js").read_bytes() == golden(__file__, "project_loader.js.golden")
    assert (site / "app.py").read_bytes() == golden(__file__, "project_app.py.golden")
    assert (site / "store.py").read_bytes() == golden(__file__, "project_store.py.golden")
    assert (site / "_pyfun_rt.py").read_bytes() == golden(__file__, "project_rt.py.golden")


def test_bundle_project_type_error(run, workdir):
    """CATCHES: bundling a project whose modules do not type-check, or reporting the errors without the
    per-module header and total count."""
    write_files(workdir, {"app.pyfun": "import Geo\nlet bad = Geo.area 4 \"five\"\n", "geo.pyfun": "let area w h = w * h\n"})
    r = run(["bundle", "app.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "project_type_error.golden")
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["app.pyfun", "geo.pyfun"]


def test_bundle_project_missing_module(run, workdir):
    """CATCHES: a missing imported module not being reported (with its expected file name) before the
    bundle is written."""
    (workdir / "app.pyfun").write_text("import Nope\nprint 1\n")
    r = run(["bundle", "app.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot find module `Nope` (expected `nope.pyfun`), imported by `App`\n"
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["app.pyfun"]


def test_bundle_project_lowering_failure(run, workdir):
    """CATCHES: a project with a typed hole being bundled; project lowering refuses it with
    `lowering failed`."""
    write_files(workdir, {"app.pyfun": "import Geo\nprint (Geo.area 2 3)\n", "geo.pyfun": "let area w h = ?todo\n"})
    r = run(["bundle", "app.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "project_hole.golden")
    assert r.returncode == 1


def test_bundle_type_error_writes_nothing(run, workdir):
    """CATCHES: creating the output directory or any file before the program type-checks."""
    (workdir / "bad.pyfun").write_text('let x = 1 + "s"\n')
    r = run(["bundle", "bad.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "type_error.golden")
    assert r.returncode == 1
    assert sorted(p.name for p in workdir.iterdir()) == ["bad.pyfun"]


def test_bundle_reports_lowering_notes(run, workdir):
    """CATCHES: lowering notes being dropped by `bundle` (they precede the summary line on stderr)."""
    (workdir / "prog.pyfun").write_text(NOTE_PROG)
    r = run(["bundle", "prog.pyfun", "-o", "site"])
    assert r.stderr == (b"note: `collect` calls itself in tail position but keeps its recursive form: a closure in "
                        b"it captures `n`\n"
                        b"wrote index.html to site (1 module, 0 assets); serve the directory over http and open it\n")
    assert (r.stdout, r.returncode) == (b"", 0)


@pytest.mark.parametrize("asset", ["..", ".", "/"])
def test_bundle_asset_without_a_file_name(run, workdir, asset):
    """CATCHES: copying a directory-like asset path or crashing; an asset path with no file name is
    rejected by name (after the modules were written)."""
    (workdir / "hello.pyfun").write_text(HELLO)
    r = run(["bundle", "hello.pyfun", "-o", "site", "--asset", asset])
    assert r.stdout == b""
    assert r.stderr == f"error: `--asset {asset}` has no file name\n".encode()
    assert r.returncode == 1
    assert tree(workdir / "site") == ["main.py"]


def test_bundle_missing_asset(run, workdir):
    """CATCHES: skipping a missing asset silently instead of failing with the copy error."""
    (workdir / "hello.pyfun").write_text(HELLO)
    r = run(["bundle", "hello.pyfun", "-o", "site", "--asset", "nope.txt"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot copy nope.txt: No such file or directory (os error 2)\n"
    assert r.returncode == 1
    assert tree(workdir / "site") == ["main.py"]


def test_bundle_asset_destination_is_a_directory(run, workdir):
    """CATCHES: ignoring a failed asset copy (a directory squatting on the asset's name in the output)."""
    write_files(workdir, {"hello.pyfun": HELLO, "words.txt": "x\n", "site/words.txt/keep": "k\n"})
    r = run(["bundle", "hello.pyfun", "-o", "site", "--asset", "words.txt"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot copy words.txt: Is a directory (os error 21)\n"
    assert r.returncode == 1
    assert tree(workdir / "site") == ["main.py", "words.txt/keep"]


def test_bundle_missing_page(run, workdir):
    """CATCHES: an unreadable `--page` fragment being ignored instead of failing the bundle."""
    (workdir / "hello.pyfun").write_text(HELLO)
    r = run(["bundle", "hello.pyfun", "-o", "site", "--page", "nope.html"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot read nope.html: No such file or directory (os error 2)\n"
    assert r.returncode == 1
    assert tree(workdir / "site") == ["main.py"]


def test_bundle_output_is_an_existing_file(run, workdir):
    """CATCHES: overwriting a regular file named by `-o`, or failing without the OS error."""
    write_files(workdir, {"hello.pyfun": HELLO, "site": "i am a file\n"})
    r = run(["bundle", "hello.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot create site: File exists (os error 17)\n"
    assert r.returncode == 1
    assert (workdir / "site").read_bytes() == b"i am a file\n"


def test_bundle_cannot_write_a_module(run, workdir):
    """CATCHES: ignoring a failed module write (a directory squatting on `main.py`)."""
    (workdir / "hello.pyfun").write_text(HELLO)
    (workdir / "site" / "main.py").mkdir(parents=True)
    r = run(["bundle", "hello.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot write main.py: Is a directory (os error 21)\n"
    assert r.returncode == 1


def test_bundle_cannot_write_the_page(run, workdir):
    """CATCHES: reporting success when `index.html` cannot be written; the loader is written first."""
    (workdir / "hello.pyfun").write_text(HELLO)
    (workdir / "site" / "index.html").mkdir(parents=True)
    r = run(["bundle", "hello.pyfun", "-o", "site"])
    assert r.stdout == b""
    assert r.stderr == b"error: cannot write index.html: Is a directory (os error 21)\n"
    assert r.returncode == 1
    assert tree(workdir / "site") == ["main.py", "pyfun-bundle.js"]
