"""`pyfun bundle <entry> -o <dir> [--asset <file>]... [--page <fragment.html>]`: a static web
page (index.html + loader + compiled Python + assets) that runs the program on Pyodide."""

from conftest import case_transcript, golden_name, listing, read_golden, run_case

HELLO = (
    "let greet who = f\"hello, {who}!\"\n"
    "print (greet \"browser\")\n"
)
WORDS = "alpha\nbeta\ngamma\n"
PAGE = "<h1>Word counter</h1>\n<p id=\"intro\">Counts the words in <code>words.txt</code>.</p>\n"


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert case_transcript(proc, case) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


SINGLE_CASE = {
    "id": "single_file",
    "files": {"hello.pyfun": HELLO},
    "args": ["bundle", "hello.pyfun", "-o", "site"],
    "outputs": ["site/index.html", "site/pyfun-bundle.js", "site/main.py"],
}
WITH_ASSETS_CASE = {
    "id": "assets_and_page",
    "files": {"hello.pyfun": HELLO, "data/words.txt": WORDS, "data/stop.txt": "the\na\n", "page.html": PAGE},
    "args": ["bundle", "hello.pyfun", "-o", "site", "--asset", "data/words.txt", "--page", "page.html",
             "--asset", "data/stop.txt"],
    "outputs": ["site/index.html", "site/pyfun-bundle.js", "site/words.txt", "site/stop.txt"],
}
PROJECT_CASE = {
    "id": "project",
    "files": {
        "geometry.pyfun": "let area w h = w * h\nlet lookup k = if k > 0 then Some k else None\n",
        "app.pyfun": "import Geometry\nprint (Geometry.area 2 3)\nprint (Geometry.lookup 4)\n",
    },
    "args": ["bundle", "app.pyfun", "-o", "out/www"],
    "outputs": ["out/www/index.html", "out/www/pyfun-bundle.js", "out/www/app.py", "out/www/geometry.py",
                "out/www/_pyfun_rt.py"],
}
TITLE_ESCAPE_CASE = {
    "id": "title_is_html_escaped",
    "files": {"a&b<c>.pyfun": "print 1\n"},
    "args": ["bundle", "a&b<c>.pyfun", "-o", "site"],
    "outputs": ["site/index.html"],
}
ASSET_NAME_ESCAPE_CASE = {
    "id": "asset_names_are_json_escaped",
    "files": {"hello.pyfun": HELLO, 'we"ird\\name.txt': "x\n"},
    "args": ["bundle", "hello.pyfun", "-o", "site", "--asset", 'we"ird\\name.txt'],
    "outputs": ["site/pyfun-bundle.js"],
}
NOTE_CASE = {
    "id": "notes_are_reported",
    "files": {"loop.pyfun": (
        "let collect n acc =\n"
        "  if n == 0 then acc\n"
        "  else\n"
        "    let f = fun x -> x + n\n"
        "    collect (n - 1) (f acc)\n"
        "print (collect 3 0)\n"
    )},
    "args": ["bundle", "loop.pyfun", "-o", "site"],
    "outputs": ["site/main.py"],
}


def test_bundle_a_single_file(run, workdir):
    """CATCHES: a bundle missing index.html, the loader or `main.py`; a loader with the
    wrong Pyodide URL, FILES/ASSETS/ENTRY values; or a different summary line."""
    _check(run, workdir, SINGLE_CASE)
    assert listing(workdir / "site") == "index.html\nmain.py\npyfun-bundle.js\n"


def test_bundle_copies_assets_and_embeds_the_page(run, workdir):
    """CATCHES: assets copied under their directory path instead of their file name, assets
    listed in the wrong order, the page fragment not spliced into index.html, or a wrong
    asset count in the summary."""
    _check(run, workdir, WITH_ASSETS_CASE)
    assert listing(workdir / "site") == "index.html\nmain.py\npyfun-bundle.js\nstop.txt\nwords.txt\n"


def test_bundle_a_project(run, workdir):
    """CATCHES: bundling only the entry module of a project, naming the entry `main.py`
    instead of after its module, or leaving out the shared runtime."""
    _check(run, workdir, PROJECT_CASE)
    assert listing(workdir / "out") == "www/\nwww/_pyfun_rt.py\nwww/app.py\nwww/geometry.py\nwww/index.html\nwww/pyfun-bundle.js\n"


def test_bundle_escapes_the_page_title(run, workdir):
    """CATCHES: an entry file name inserted into `<title>` without HTML escaping."""
    _check(run, workdir, TITLE_ESCAPE_CASE)


def test_bundle_escapes_asset_names_in_the_loader(run, workdir):
    """CATCHES: quotes or backslashes in an asset name that break the loader's JSON arrays."""
    _check(run, workdir, ASSET_NAME_ESCAPE_CASE)


def test_bundle_reports_lowering_notes(run, workdir):
    """CATCHES: a bundle path that drops the lowering notes `compile` would print."""
    _check(run, workdir, NOTE_CASE)


# ---------------------------------------------------------------- failures

TYPE_ERROR_CASE = {"id": "type_error_writes_nothing", "files": {"bad.pyfun": "let x = 1 + \"s\"\n"},
                   "args": ["bundle", "bad.pyfun", "-o", "site"]}
PROJECT_TYPE_ERROR_CASE = {
    "id": "project_type_error_writes_nothing",
    "files": {"util.pyfun": "let f x = x + 1\n", "main.pyfun": "import Util\nprint (Util.f true)\n"},
    "args": ["bundle", "main.pyfun", "-o", "site"],
}
PROJECT_MISSING_CASE = {
    "id": "project_missing_module",
    "files": {"main.pyfun": "import Nowhere\nprint 1\n"},
    "args": ["bundle", "main.pyfun", "-o", "site"],
}
MISSING_ENTRY_CASE = {"id": "missing_entry", "args": ["bundle", "gone.pyfun", "-o", "site"]}
MISSING_ASSET_CASE = {"id": "missing_asset", "files": {"hello.pyfun": HELLO},
                      "args": ["bundle", "hello.pyfun", "-o", "site", "--asset", "nope.txt"]}
MISSING_PAGE_CASE = {"id": "missing_page", "files": {"hello.pyfun": HELLO},
                     "args": ["bundle", "hello.pyfun", "-o", "site", "--page", "nope.html"]}
ASSET_WITHOUT_NAME_CASE = {"id": "asset_without_file_name", "files": {"hello.pyfun": HELLO},
                           "args": ["bundle", "hello.pyfun", "-o", "site", "--asset", ".."]}
OUT_IS_FILE_CASE = {"id": "out_is_a_file", "files": {"hello.pyfun": HELLO, "site": "occupied\n"},
                    "args": ["bundle", "hello.pyfun", "-o", "site"]}
NO_OUT_CASE = {"id": "needs_output_dir", "files": {"hello.pyfun": HELLO}, "args": ["bundle", "hello.pyfun"]}
NO_ENTRY_CASE = {"id": "needs_entry", "args": ["bundle", "-o", "site"]}
EXTRA_ARG_CASE = {"id": "unexpected_argument", "files": {"hello.pyfun": HELLO},
                  "args": ["bundle", "hello.pyfun", "other.pyfun", "-o", "site"]}
DANGLING_O_CASE = {"id": "dangling_o", "files": {"hello.pyfun": HELLO}, "args": ["bundle", "hello.pyfun", "-o"]}
DANGLING_ASSET_CASE = {"id": "dangling_asset", "files": {"hello.pyfun": HELLO},
                       "args": ["bundle", "hello.pyfun", "-o", "site", "--asset"]}
DANGLING_PAGE_CASE = {"id": "dangling_page", "files": {"hello.pyfun": HELLO},
                      "args": ["bundle", "hello.pyfun", "-o", "site", "--page"]}


def test_a_type_error_stops_the_bundle_before_writing(run, workdir):
    """CATCHES: creating the output directory or any file for an ill-typed program."""
    _check(run, workdir, TYPE_ERROR_CASE)
    assert listing(workdir) == "bad.pyfun\n"


def test_a_project_type_error_stops_the_bundle(run, workdir):
    """CATCHES: bundling a project that does not type-check."""
    _check(run, workdir, PROJECT_TYPE_ERROR_CASE)
    assert listing(workdir) == "main.pyfun\nutil.pyfun\n"


def test_a_project_graph_error_stops_the_bundle(run, workdir):
    """CATCHES: a bundle that ignores an unresolvable import."""
    _check(run, workdir, PROJECT_MISSING_CASE)


def test_a_missing_entry_is_a_read_error(run, workdir):
    """CATCHES: a bundle of a missing file that writes an empty page."""
    _check(run, workdir, MISSING_ENTRY_CASE)


def test_a_missing_asset_is_reported(run, workdir):
    """CATCHES: silently skipping an asset that cannot be copied."""
    _check(run, workdir, MISSING_ASSET_CASE)


def test_a_missing_page_fragment_is_reported(run, workdir):
    """CATCHES: silently using an empty page when `--page` cannot be read."""
    _check(run, workdir, MISSING_PAGE_CASE)


def test_an_asset_path_without_a_file_name_is_rejected(run, workdir):
    """CATCHES: copying `..` (a path with no file name) or crashing on it."""
    _check(run, workdir, ASSET_WITHOUT_NAME_CASE)


def test_an_output_path_that_is_a_file_is_rejected(run, workdir):
    """CATCHES: replacing a file with the bundle directory, or reporting success."""
    _check(run, workdir, OUT_IS_FILE_CASE)


def test_bundle_needs_an_output_directory(run, workdir):
    """CATCHES: defaulting the bundle directory instead of requiring `-o`."""
    _check(run, workdir, NO_OUT_CASE)


def test_bundle_needs_an_entry(run, workdir):
    """CATCHES: a bundle with no entry that does not report "`bundle` needs a file path"."""
    _check(run, workdir, NO_ENTRY_CASE)


def test_bundle_rejects_a_second_entry(run, workdir):
    """CATCHES: silently ignoring an extra positional argument."""
    _check(run, workdir, EXTRA_ARG_CASE)


def test_bundle_dangling_output_flag(run, workdir):
    """CATCHES: a trailing `-o` without a directory that is accepted or misreported."""
    _check(run, workdir, DANGLING_O_CASE)


def test_bundle_dangling_asset_flag(run, workdir):
    """CATCHES: a trailing `--asset` without a path that is accepted or misreported."""
    _check(run, workdir, DANGLING_ASSET_CASE)


def test_bundle_dangling_page_flag(run, workdir):
    """CATCHES: a trailing `--page` without a file that is accepted or misreported."""
    _check(run, workdir, DANGLING_PAGE_CASE)
