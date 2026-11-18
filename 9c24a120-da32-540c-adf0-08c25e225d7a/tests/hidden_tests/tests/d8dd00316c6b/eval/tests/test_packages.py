"""Façade packages: `pyfun add`, `pyfun install`, `pyfun remove` and the `pyfun.toml` manifest.

The installer is never the real pip: `PYFUN_PYTHON` points at a small stand-in
interpreter (documented: "`PYFUN_PYTHON` picks the interpreter") that logs each
`-m pip ...` call to stderr and answers the installed-metadata query for a fake
`pyfun-evalwrap` distribution whose `.pyfun` files sit under `site/` (reported as
absolute paths, as real installed metadata would be). PATH is
emptied so no `uv` on the host can change the installer that is chosen.
"""

from conftest import golden_name, listing, read_golden, run_case, transcript

FAKE_PYTHON = r"""#!/bin/sh
# Stand-in interpreter: logs pip calls, answers metadata queries.
if [ "$1" = "-m" ]; then
  echo "[pip] $*" >&2
  case "$*" in
    *broken-pkg*) exit 1 ;;
  esac
  exit 0
fi
if [ "$1" = "-c" ]; then
  case "$3" in
    pyfun-evalwrap|pyfun_evalwrap|Pyfun_Evalwrap)
      echo "0.1.0"
      echo "${0%/*}/../site/pyfun_evalwrap/wrap.pyfun"
      echo "${0%/*}/../site/pyfun_evalwrap/extras.pyfun" ;;
    plain-lib)
      echo "2.4.1" ;;
    *)
      echo "importlib.metadata.PackageNotFoundError: No package metadata was found for $3" >&2
      exit 1 ;;
  esac
  exit 0
fi
echo "unexpected: $*" >&2
exit 2
"""

WRAP = (
    "## Wrap text to a width (textwrap.fill).\n"
    "extern fillText : string -> int -> string = textwrap.fill\n"
    "let fill width text = fillText text width\n"
)
EXTRAS = "let banner s = String.upper s\n"

BASE_FILES = {
    "tools/python": FAKE_PYTHON,
    "site/pyfun_evalwrap/wrap.pyfun": WRAP,
    "site/pyfun_evalwrap/extras.pyfun": EXTRAS,
}
ENV = {"PYFUN_PYTHON": "{workdir}/tools/python", "PATH": "{workdir}/no-bin"}

# Every case brings its own manifest: the project root is the nearest `pyfun.toml` at
# or above the working directory, so a case without one would depend on the host's
# directories above the temporary workdir.
FRESH_MANIFEST = "[project]\nname = \"demo\"\n"


def _case(id, args, files=None, cwd=None, outputs=()):
    files = {"pyfun.toml": FRESH_MANIFEST, **(files or {})}
    case = {"id": id, "files": {**BASE_FILES, **files}, "executables": ["tools/python"],
            "env": ENV, "args": args, "outputs": list(outputs)}
    if cwd:
        case["cwd"] = cwd
    return case


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))
    return proc


# ---------------------------------------------------------------- add

ADD_MINIMAL_MANIFEST_CASE = _case(
    "add_into_minimal_manifest", ["add", "pyfun-evalwrap"],
    outputs=["pyfun.toml", ".pyfun/facades/pyfun-evalwrap/wrap.pyfun", ".pyfun/facades/pyfun-evalwrap/extras.pyfun"])
ADD_WITH_VERSION_CASE = _case("add_with_version_specifier", ["add", "pyfun-evalwrap>=0.1,<1"], outputs=["pyfun.toml"])
ADD_EXISTING_MANIFEST_CASE = _case(
    "add_into_existing_manifest", ["add", "pyfun-evalwrap"],
    files={"pyfun.toml": "# my project\n[project]\nname = \"scrabble\"  # the game\n\n[dependencies]\nother-facade = \"1.2.3\"\n\n[tool.extra]\nkeep = \"me\"\n"},
    outputs=["pyfun.toml"])
ADD_REPLACES_VERSION_CASE = _case(
    "add_replaces_recorded_version", ["add", "pyfun-evalwrap"],
    files={"pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\npyfun-evalwrap = \"0.0.9\"\nzz = \"1\"\n",
           ".pyfun/facades/pyfun-evalwrap/stale.pyfun": "let old = 1\n"},
    outputs=["pyfun.toml"])
ADD_NO_DEPS_TABLE_CASE = _case(
    "add_appends_dependencies_table", ["add", "pyfun-evalwrap"],
    files={"pyfun.toml": "[project]\nname = \"demo\""}, outputs=["pyfun.toml"])
ADD_LOCAL_DIR_CASE = _case(
    "add_local_directory", ["add", "pkg/evalwrap-facade"],
    files={"pkg/evalwrap-facade/pyproject.toml": "[build-system]\nrequires = [\"setuptools\"]\n\n[project]\nname = \"pyfun-evalwrap\"\nversion = \"0.1.0\"\n"},
    outputs=["pyfun.toml"])
ADD_FROM_SUBDIR_CASE = _case(
    "add_from_subdirectory_uses_root", ["add", "pyfun-evalwrap"],
    files={"pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\n", "src/deep/keep.txt": ""},
    cwd="src/deep", outputs=["pyfun.toml"])


def test_add_vendors_the_facade_and_records_it(run, workdir):
    """CATCHES: `add` that vendors into the wrong directory, forgets to append the
    `[dependencies]` table, records the wrong version, or prints a different summary of
    the modules the façade provides."""
    _check(run, workdir, ADD_MINIMAL_MANIFEST_CASE)
    assert listing(workdir / ".pyfun") == (
        "facades/\nfacades/pyfun-evalwrap/\nfacades/pyfun-evalwrap/extras.pyfun\nfacades/pyfun-evalwrap/wrap.pyfun\n")


def test_add_with_a_version_specifier_reads_the_name(run, workdir):
    """CATCHES: treating `name>=0.1,<1` as the distribution name, or passing a stripped
    requirement to the installer."""
    _check(run, workdir, ADD_WITH_VERSION_CASE)


def test_add_keeps_comments_and_other_tables(run, workdir):
    """CATCHES: a manifest rewrite that drops comments, reorders tables or loses other
    entries when recording a new dependency."""
    _check(run, workdir, ADD_EXISTING_MANIFEST_CASE)


def test_add_replaces_a_recorded_version_and_the_vendored_copy(run, workdir):
    """CATCHES: duplicate dependency lines, or stale vendored files left behind on re-add."""
    _check(run, workdir, ADD_REPLACES_VERSION_CASE)
    assert listing(workdir / ".pyfun/facades") == "pyfun-evalwrap/\npyfun-evalwrap/extras.pyfun\npyfun-evalwrap/wrap.pyfun\n"


def test_add_appends_a_missing_dependencies_table(run, workdir):
    """CATCHES: failing (or writing a malformed file) when the manifest has no
    `[dependencies]` table or no trailing newline."""
    _check(run, workdir, ADD_NO_DEPS_TABLE_CASE)


def test_add_a_local_directory_reads_its_project_name(run, workdir):
    """CATCHES: using the directory name instead of `[project] name` from its pyproject.toml."""
    _check(run, workdir, ADD_LOCAL_DIR_CASE)


def test_add_from_a_subdirectory_uses_the_nearest_manifest(run, workdir):
    """CATCHES: creating a second manifest in the working directory instead of finding the
    project root above it."""
    _check(run, workdir, ADD_FROM_SUBDIR_CASE)
    assert listing(workdir / "src") == "deep/\ndeep/keep.txt\n"


ADD_NOTHING_CASE = _case("add_without_package", ["add"])
ADD_NO_FACADE_FILES_CASE = _case("add_package_without_pyfun_files", ["add", "plain-lib"])
ADD_INSTALL_FAILS_CASE = _case("add_install_fails", ["add", "broken-pkg"])
ADD_METADATA_FAILS_CASE = _case("add_metadata_missing", ["add", "ghost-pkg"])
ADD_BAD_SPEC_CASE = _case("add_unreadable_name", ["add", "==1.0"])
ADD_DIR_NO_PYPROJECT_CASE = _case("add_directory_without_pyproject", ["add", "pkg"], files={"pkg/readme.txt": "x\n"})
ADD_DIR_NO_NAME_CASE = _case("add_directory_without_project_name", ["add", "pkg"],
                             files={"pkg/pyproject.toml": "[tool.other]\nname = \"nope\"\n"})


def test_add_needs_a_package(run, workdir):
    """CATCHES: `add` with no package that touches the manifest or exits 0."""
    _check(run, workdir, ADD_NOTHING_CASE)
    assert (workdir / "pyfun.toml").read_text() == FRESH_MANIFEST


def test_add_rejects_a_package_that_ships_no_pyfun_files(run, workdir):
    """CATCHES: recording an ordinary Python package as a façade dependency."""
    _check(run, workdir, ADD_NO_FACADE_FILES_CASE)


def test_add_reports_a_failed_install(run, workdir):
    """CATCHES: continuing to vendor and record a package whose installation failed."""
    _check(run, workdir, ADD_INSTALL_FAILS_CASE)


def test_add_reports_missing_installed_metadata(run, workdir):
    """CATCHES: a metadata failure that is swallowed instead of reported with its stderr."""
    _check(run, workdir, ADD_METADATA_FAILS_CASE)


def test_add_rejects_a_spec_without_a_name(run, workdir):
    """CATCHES: passing a requirement with an empty package name to the installer."""
    _check(run, workdir, ADD_BAD_SPEC_CASE)


def test_add_rejects_a_directory_without_pyproject(run, workdir):
    """CATCHES: treating any directory as an installable façade."""
    _check(run, workdir, ADD_DIR_NO_PYPROJECT_CASE)


def test_add_rejects_a_pyproject_without_a_project_name(run, workdir):
    """CATCHES: reading `name` from a table other than `[project]`."""
    _check(run, workdir, ADD_DIR_NO_NAME_CASE)


# ---------------------------------------------------------------- install

INSTALL_EMPTY_CASE = _case("install_no_dependencies", ["install"],
                           files={"pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\n"})
INSTALL_PINNED_CASE = _case(
    "install_pins_recorded_versions", ["install"],
    files={"pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\npyfun-evalwrap = \"0.1.0\"\n"},
    outputs=["pyfun.toml", ".pyfun/facades/pyfun-evalwrap/wrap.pyfun"])
INSTALL_UNPINNED_CASE = _case(
    "install_unpinned_dependency", ["install"],
    files={"pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\npyfun-evalwrap = \"\"\n"},
    outputs=["pyfun.toml"])
INSTALL_STOPS_ON_FAILURE_CASE = _case(
    "install_stops_on_failure", ["install"],
    files={"pyfun.toml": "[project]\nname = \"demo\"\n\n[dependencies]\nbroken-pkg = \"1.0\"\npyfun-evalwrap = \"0.1.0\"\n"})


def test_install_with_no_dependencies(run, workdir):
    """CATCHES: running the installer (or failing) when nothing is listed."""
    _check(run, workdir, INSTALL_EMPTY_CASE)


def test_install_pins_each_recorded_version(run, workdir):
    """CATCHES: installing the latest version instead of `name==recorded`, or not vendoring
    the façade files."""
    _check(run, workdir, INSTALL_PINNED_CASE)


def test_install_an_unpinned_dependency(run, workdir):
    """CATCHES: passing `name==` (an empty pin) to the installer."""
    _check(run, workdir, INSTALL_UNPINNED_CASE)


def test_install_stops_at_the_first_failure(run, workdir):
    """CATCHES: an `install` that reports success after a dependency failed to install."""
    _check(run, workdir, INSTALL_STOPS_ON_FAILURE_CASE)


# ---------------------------------------------------------------- remove

MANIFEST_WITH_DEPS = (
    "[project]\nname = \"demo\"\n\n[dependencies]\n# façades\nPyfun_Evalwrap = \"0.1.0\"\nother = \"2\"\n"
)
REMOVE_CASE = _case(
    "remove_drops_entry_and_vendored_copy", ["remove", "pyfun-evalwrap"],
    files={"pyfun.toml": MANIFEST_WITH_DEPS, ".pyfun/facades/pyfun-evalwrap/wrap.pyfun": WRAP,
           ".pyfun/facades/other/o.pyfun": "let o = 1\n"},
    outputs=["pyfun.toml"])
REMOVE_MISSING_CASE = _case("remove_unknown_dependency", ["remove", "absent"],
                            files={"pyfun.toml": MANIFEST_WITH_DEPS}, outputs=["pyfun.toml"])
REMOVE_NOTHING_CASE = _case("remove_without_package", ["remove"])
REMOVE_TWO_CASE = _case("remove_two_packages", ["remove", "other", "pyfun_evalwrap"],
                        files={"pyfun.toml": MANIFEST_WITH_DEPS}, outputs=["pyfun.toml"])


def test_remove_drops_the_entry_and_the_vendored_copy(run, workdir):
    """CATCHES: matching dependency names without PEP 503 normalisation, deleting the
    wrong façade directory, losing comments, or not uninstalling the distribution."""
    _check(run, workdir, REMOVE_CASE)
    assert listing(workdir / ".pyfun") == "facades/\nfacades/other/\nfacades/other/o.pyfun\n"


def test_remove_an_unknown_dependency_fails(run, workdir):
    """CATCHES: reporting success (or rewriting the manifest) for a package that is not listed."""
    _check(run, workdir, REMOVE_MISSING_CASE)


def test_remove_needs_a_package(run, workdir):
    """CATCHES: `remove` with no package that exits 0 or touches the manifest."""
    _check(run, workdir, REMOVE_NOTHING_CASE)


def test_remove_several_packages(run, workdir):
    """CATCHES: removing only the first of several packages named on the command line."""
    _check(run, workdir, REMOVE_TWO_CASE)


# ---------------------------------------------------------------- using an added façade

USE_FACADE_CASE = dict(
    _case("added_facade_is_importable", ["compile", "main.pyfun"],
          files={"main.pyfun": "import Wrap\nimport Extras\nprint (Wrap.fill 10 (Extras.banner \"a long line of text\"))\n"}),
    setup=[["add", "pyfun-evalwrap"]])


def test_an_added_facade_can_be_imported(run, workdir):
    """CATCHES: vendoring façades somewhere the module resolver does not look, or a façade
    module that is not lowered to its own `.py` file."""
    _check(run, workdir, USE_FACADE_CASE)
