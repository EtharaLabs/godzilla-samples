"""Façade packages: `pyfun add <package>...`, `pyfun install`, `pyfun remove <package>...` and the
`pyfun.toml` manifest they maintain.

The Python environment is replaced by a stand-in interpreter (named through the documented
`PYFUN_PYTHON` variable) that logs every call, answers `-m pip install/uninstall` and the
installed-metadata query (`-c <script> <dist>`) from a fake site directory, so tests see exactly
which installer commands pyfun runs and what it vendors. PATH is restricted to a directory of our
own so that only the stand-ins (and optionally a fake `uv`) are found.
"""

import stat

from conftest import assert_no_manifest_above, write_files

FAKE_PYTHON = r"""#!/bin/sh
# Stand-in interpreter: logs each call; fakes pip and the installed-metadata query.
if [ "$1" = "-c" ]; then
  printf 'python -c <metadata script> %s\n' "$3" >> "$FAKE_LOG"
  dir="$FAKE_SITE/$3"
  if [ ! -d "$dir" ]; then
    echo "PackageNotFoundError: No package metadata was found for $3" >&2
    exit 1
  fi
  version=0.0.0
  if [ -f "$dir/VERSION" ]; then read version < "$dir/VERSION"; fi
  echo "$version"
  for f in "$dir"/*.pyfun "$dir"/*/*.pyfun; do
    if [ -f "$f" ]; then echo "$f"; fi
  done
  exit 0
fi
printf 'python %s\n' "$*" >> "$FAKE_LOG"
if [ "$1 $2 $3" = "-m pip install" ]; then
  if [ -f "$FAKE_SITE/fail-install" ]; then
    echo "ERROR: No matching distribution found for $4"
    exit 1
  fi
  echo "Successfully installed $4"
  exit 0
fi
if [ "$1 $2 $3" = "-m pip uninstall" ]; then
  echo "Found existing installation: $5"
fi
exit 0
"""

FAKE_UV = r"""#!/bin/sh
# Stand-in for `uv`: answers `--version`, logs `pip ...` calls (with the interpreter path elided).
if [ "$1" = "--version" ]; then echo "uv 0.0.0-fake"; exit 0; fi
py=$4
if [ "$py" = "$PYFUN_PYTHON" ]; then py='$PYFUN_PYTHON'; fi
printf 'uv %s %s %s %s %s\n' "$1" "$2" "$3" "$py" "$5" >> "$FAKE_LOG"
echo "uv: done $2 $5"
exit 0
"""

WRAP = """extern import textwrap
extern pure fillText: string -> int -> string = textwrap.fill(width = ...)
let fill width text = fillText text width
"""

MAIN = """import Wrap
print ("the quick brown fox jumps over the lazy dog" |> Wrap.fill 16)
"""


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def setup(workdir, site=None, files=None, uv=False):
    """Create the fake site (`{dist: {relpath: text}}`), project files, and the stand-in tools; return env."""
    root = workdir.parent
    for dist, entries in (site or {}).items():
        write_files(root / "site" / dist, entries)
    (root / "site").mkdir(exist_ok=True)
    write_files(workdir, files or {})
    bindir = root / "bin"
    bindir.mkdir(exist_ok=True)
    executable(bindir / "fakepy", FAKE_PYTHON)
    if uv:
        executable(bindir / "uv", FAKE_UV)
    return {"PYFUN_PYTHON": str(bindir / "fakepy"), "PATH": str(bindir), "FAKE_LOG": str(root / "calls.log"),
            "FAKE_SITE": str(root / "site")}


def calls(workdir):
    log = workdir.parent / "calls.log"
    return log.read_text() if log.exists() else ""


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# A project manifest in the working directory itself, so the project root never depends on what the
# directories above the test's temporary directory contain.
DEMO = '[project]\nname = "demo"\n\n[dependencies]\n'

TEXTWRAP_SITE = {"pyfun-textwrap": {"VERSION": "0.1.0\n", "pyfun_textwrap/wrap.pyfun": WRAP}}


# ============================================================================ add


def test_add_creates_the_manifest_and_vendors_the_facade(run, workdir):
    """CATCHES: not creating `pyfun.toml` (named after the directory) when absent, a different manifest
    layout, vendoring somewhere other than `.pyfun/facades/<dist>/`, recording the requested instead of
    the installed version, or a different `added <dist> <version> (import <Modules>)` line."""
    env = setup(workdir, site=TEXTWRAP_SITE)
    assert_no_manifest_above(workdir)
    r = run(["add", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == (b"created pyfun.toml\nSuccessfully installed pyfun-textwrap\n"
                        b"added pyfun-textwrap 0.1.0 (import Wrap)\n")
    assert r.stderr == b""
    assert r.returncode == 0
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "work"\n\n[dependencies]\npyfun-textwrap = "0.1.0"\n')
    assert tree(workdir) == [".pyfun/facades/pyfun-textwrap/wrap.pyfun", "pyfun.toml"]
    assert (workdir / ".pyfun/facades/pyfun-textwrap/wrap.pyfun").read_text() == WRAP
    assert calls(workdir) == ("python -m pip install pyfun-textwrap\n"
                              "python -c <metadata script> pyfun-textwrap\n")


def test_added_facade_resolves_for_check_and_run(run, workdir):
    """CATCHES: `import Wrap` not resolving from the vendored façade after `add`, or the façade module
    not being compiled into the program."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={"pyfun.toml": DEMO, "main.pyfun": MAIN})
    assert run(["add", "pyfun-textwrap"], env_overrides=env).returncode == 0
    check = run(["check", "main.pyfun"])
    assert (check.stdout, check.stderr, check.returncode) == (b"", b"ok: no type errors (2 modules)\n", 0)
    r = run(["run", "main.pyfun"])
    assert (r.stdout, r.stderr, r.returncode) == (b"the quick brown\nfox jumps over\nthe lazy dog\n", b"", 0)


def test_add_with_a_version_specifier(run, workdir):
    """CATCHES: passing only the bare name to the installer, or keeping the specifier in the dependency
    key; the full requirement goes to pip and the name before the specifier is the dist."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={"pyfun.toml": DEMO})
    r = run(["add", "pyfun-textwrap==0.1.0"], env_overrides=env)
    assert r.stdout == (b"Successfully installed pyfun-textwrap==0.1.0\n"
                        b"added pyfun-textwrap 0.1.0 (import Wrap)\n")
    assert r.returncode == 0
    assert calls(workdir) == ("python -m pip install pyfun-textwrap==0.1.0\n"
                              "python -c <metadata script> pyfun-textwrap\n")


def test_add_requirement_with_extras_and_markers(run, workdir):
    """CATCHES: a requirement parser that does not stop the name at `[`, `>`, `;` or spaces."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={"pyfun.toml": DEMO})
    r = run(["add", "pyfun-textwrap[extra]>=0.1 ; python_version > '3'"], env_overrides=env)
    assert r.returncode == 0
    assert calls(workdir) == ("python -m pip install pyfun-textwrap[extra]>=0.1 ; python_version > '3'\n"
                              "python -c <metadata script> pyfun-textwrap\n")
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "demo"\n\n[dependencies]\npyfun-textwrap = "0.1.0"\n')


def test_add_several_packages_in_order(run, workdir):
    """CATCHES: only the first of several packages being added, or entries recorded out of order; module
    names in the `added` line are sorted."""
    env = setup(workdir, site={
        "pyfun-zeta": {"VERSION": "2.0\n", "z/zed.pyfun": "let z = 1\n", "z/alpha.pyfun": "let a = 1\n"},
        "pyfun-beta": {"VERSION": "1.5\n", "b/beta.pyfun": "let b = 2\n"},
    }, files={"pyfun.toml": DEMO})
    r = run(["add", "pyfun-zeta", "pyfun-beta"], env_overrides=env)
    assert r.stdout == (b"Successfully installed pyfun-zeta\nadded pyfun-zeta 2.0 (import Alpha, Zed)\n"
                        b"Successfully installed pyfun-beta\nadded pyfun-beta 1.5 (import Beta)\n")
    assert r.returncode == 0
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "demo"\n\n[dependencies]\npyfun-zeta = "2.0"\npyfun-beta = "1.5"\n')
    assert tree(workdir) == [".pyfun/facades/pyfun-beta/beta.pyfun", ".pyfun/facades/pyfun-zeta/alpha.pyfun",
                             ".pyfun/facades/pyfun-zeta/zed.pyfun", "pyfun.toml"]


def test_add_normalises_the_vendor_directory_name(run, workdir):
    """CATCHES: vendoring under the raw distribution spelling instead of its PEP 503 normalised name
    (lower case, runs of `-`, `_`, `.` folded to one `-`) while the manifest keeps the given name."""
    env = setup(workdir, site={"Pyfun_Text..Wrap": {"VERSION": "3\n", "wrap.pyfun": WRAP}}, files={"pyfun.toml": DEMO})
    r = run(["add", "Pyfun_Text..Wrap"], env_overrides=env)
    assert r.returncode == 0
    assert tree(workdir) == [".pyfun/facades/pyfun-text-wrap/wrap.pyfun", "pyfun.toml"]
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "demo"\n\n[dependencies]\nPyfun_Text..Wrap = "3"\n')


def test_add_again_updates_in_place_and_replaces_the_vendored_copy(run, workdir):
    """CATCHES: duplicating the dependency line on a re-add, disturbing comments and other tables, or
    leaving stale files from the previous version in the vendored directory."""
    env = setup(workdir, site={"pyfun-textwrap": {"VERSION": "0.2.0\n", "wrap.pyfun": WRAP}}, files={
        "pyfun.toml": '# my project\n[project]\nname = "demo"\n\n[dependencies]\n# façades\n'
                      'pyfun-textwrap = "0.1.0"  # old\nother = "1.0"\n\n[tool]\nx = "y"\n',
        ".pyfun/facades/pyfun-textwrap/old.pyfun": "let old = 1\n",
    })
    r = run(["add", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == b"Successfully installed pyfun-textwrap\nadded pyfun-textwrap 0.2.0 (import Wrap)\n"
    assert (r.stderr, r.returncode) == (b"", 0)
    assert (workdir / "pyfun.toml").read_text() == (
        '# my project\n[project]\nname = "demo"\n\n[dependencies]\n# façades\n'
        'pyfun-textwrap = "0.2.0"\nother = "1.0"\n\n[tool]\nx = "y"\n')
    assert tree(workdir) == [".pyfun/facades/pyfun-textwrap/wrap.pyfun", "pyfun.toml"]


def test_add_appends_after_the_last_dependency(run, workdir):
    """CATCHES: inserting a new dependency at the top of the table or at the end of the file instead of
    right after the table's last entry (blank lines and the next table stay where they were)."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={
        "pyfun.toml": '[project]\nname = "demo"\n\n[dependencies]\nfirst = "1"\n\n# trailing comment\n\n[tool]\nk = "v"\n',
    })
    r = run(["add", "pyfun-textwrap"], env_overrides=env)
    assert r.returncode == 0
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "demo"\n\n[dependencies]\nfirst = "1"\npyfun-textwrap = "0.1.0"\n\n# trailing comment\n'
        '\n[tool]\nk = "v"\n')


def test_add_creates_a_missing_dependencies_table(run, workdir):
    """CATCHES: failing (or writing a bare entry) when the manifest has no `[dependencies]` table; the
    table is appended after a blank line."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={"pyfun.toml": '[project]\nname = "demo"'})
    r = run(["add", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == b"Successfully installed pyfun-textwrap\nadded pyfun-textwrap 0.1.0 (import Wrap)\n"
    assert r.returncode == 0
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "demo"\n\n[dependencies]\npyfun-textwrap = "0.1.0"\n')


def test_add_uses_the_nearest_manifest_above_the_working_directory(run, workdir):
    """CATCHES: creating a new manifest in a subdirectory instead of using the project root found by
    walking up; the façade is vendored at that root."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={"pyfun.toml": '[project]\nname = "demo"\n\n[dependencies]\n',
                                                    "src/deep/.keep": ""})
    r = run(["add", "pyfun-textwrap"], cwd=workdir / "src" / "deep", env_overrides=env)
    assert r.stdout == b"Successfully installed pyfun-textwrap\nadded pyfun-textwrap 0.1.0 (import Wrap)\n"
    assert r.returncode == 0
    assert tree(workdir) == [".pyfun/facades/pyfun-textwrap/wrap.pyfun", "pyfun.toml", "src/deep/.keep"]
    assert (workdir / "pyfun.toml").read_text() == '[project]\nname = "demo"\n\n[dependencies]\npyfun-textwrap = "0.1.0"\n'


def test_add_a_local_directory_reads_its_project_name(run, workdir):
    """CATCHES: treating a local directory requirement as a distribution name; its `pyproject.toml`
    `[project] name` names the dist, while the installer receives the path."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={
        "pyfun.toml": DEMO,
        "vendor/textwrap/pyproject.toml": '[build-system]\nrequires = ["setuptools"]\n\n[project]\n'
                                          'name = "pyfun-textwrap"\nversion = "0.1.0"\n',
    })
    r = run(["add", "vendor/textwrap"], env_overrides=env)
    assert r.stdout == (b"Successfully installed vendor/textwrap\n"
                        b"added pyfun-textwrap 0.1.0 (import Wrap)\n")
    assert r.returncode == 0
    assert calls(workdir) == "python -m pip install vendor/textwrap\npython -c <metadata script> pyfun-textwrap\n"


def test_add_local_directory_without_pyproject(run, workdir):
    """CATCHES: installing a directory that is not a Python project instead of refusing it."""
    env = setup(workdir, files={"pyfun.toml": DEMO, "notaproject/readme.txt": "hi\n"})
    r = run(["add", "notaproject"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: `notaproject` is a directory with no pyproject.toml\n"
    assert r.returncode == 1
    assert calls(workdir) == ""


def test_add_local_directory_without_a_project_name(run, workdir):
    """CATCHES: guessing a name (e.g. the directory name) when `pyproject.toml` has no `[project] name`."""
    env = setup(workdir, files={"pyfun.toml": DEMO, "pkg/pyproject.toml": '[tool.x]\nname = "not-this"\n[project]\nversion = "1"\n'})
    r = run(["add", "pkg"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: `pkg/pyproject.toml` has no [project] name\n"
    assert r.returncode == 1


def test_add_a_requirement_without_a_name(run, workdir):
    """CATCHES: passing a nameless requirement such as `==1.0` to the installer."""
    env = setup(workdir, files={"pyfun.toml": DEMO})
    r = run(["add", "==1.0"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot read a package name from `==1.0`\n"
    assert r.returncode == 1
    assert calls(workdir) == ""


def test_add_installer_failure(run, workdir):
    """CATCHES: continuing to vendor/record a package whose installation failed; the installer's own
    output stays visible and the manifest is left as it was."""
    env = setup(workdir, files={"pyfun.toml": DEMO})
    (workdir.parent / "site" / "fail-install").write_text("")
    r = run(["add", "pyfun-missing"], env_overrides=env)
    assert r.stdout == b"ERROR: No matching distribution found for pyfun-missing\n"
    assert r.stderr == b"error: installing `pyfun-missing` failed (see the installer's output above)\n"
    assert r.returncode == 1
    assert (workdir / "pyfun.toml").read_text() == '[project]\nname = "demo"\n\n[dependencies]\n'


def test_add_unreadable_metadata(run, workdir):
    """CATCHES: ignoring a failed metadata query; the interpreter's trimmed stderr is quoted in the error."""
    env = setup(workdir, files={"pyfun.toml": DEMO})
    r = run(["add", "pyfun-ghost"], env_overrides=env)
    assert r.stdout == b"Successfully installed pyfun-ghost\n"
    assert r.stderr == (b"error: cannot read the installed metadata of `pyfun-ghost`: PackageNotFoundError: "
                        b"No package metadata was found for pyfun-ghost\n")
    assert r.returncode == 1


def test_add_a_package_without_pyfun_files(run, workdir):
    """CATCHES: recording an ordinary Python package as a façade; it must ship `.pyfun` files."""
    env = setup(workdir, site={"requests": {"VERSION": "2.31\n", "requests/__init__.py": ""}}, files={"pyfun.toml": DEMO})
    r = run(["add", "requests"], env_overrides=env)
    assert r.stdout == b"Successfully installed requests\n"
    assert r.stderr == b"error: `requests` installed, but it ships no .pyfun files, so it is not a Pyfun fa\xc3\xa7ade\n"
    assert r.returncode == 1
    assert tree(workdir) == ["pyfun.toml"]


def test_add_with_a_missing_interpreter(run, workdir):
    """CATCHES: a crash or a silent fallback when `PYFUN_PYTHON` names a program that does not exist."""
    env = setup(workdir, files={"pyfun.toml": DEMO})
    env["PYFUN_PYTHON"] = str(workdir / "no-python")
    r = run(["add", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: cannot run the installer: No such file or directory (os error 2)\n"
    assert r.returncode == 1


def test_add_without_any_interpreter(run, workdir):
    """CATCHES: not explaining how to point pyfun at an interpreter when none is on PATH."""
    env = setup(workdir, files={"pyfun.toml": DEMO})
    del env["PYFUN_PYTHON"]
    r = run(["add", "pyfun-textwrap"], env_overrides={**env, "PYFUN_PYTHON": ""})
    assert r.stdout == b""
    assert r.stderr == b"error: no Python interpreter found (set PYFUN_PYTHON)\n"
    assert r.returncode == 1


def test_add_prefers_uv_when_it_is_on_path(run, workdir):
    """CATCHES: ignoring `uv` on PATH: the install goes through `uv pip install --python <interpreter>`
    while the metadata query still runs on the interpreter itself."""
    env = setup(workdir, site=TEXTWRAP_SITE, uv=True, files={"pyfun.toml": DEMO})
    r = run(["add", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == (b"uv: done install pyfun-textwrap\n"
                        b"added pyfun-textwrap 0.1.0 (import Wrap)\n")
    assert (r.stderr, r.returncode) == (b"", 0)
    assert calls(workdir) == ("uv pip install --python $PYFUN_PYTHON pyfun-textwrap\n"
                              "python -c <metadata script> pyfun-textwrap\n")


# ============================================================================ install


def test_install_with_no_dependencies(run, workdir):
    """CATCHES: failing, or calling the installer, when the manifest lists nothing."""
    env = setup(workdir, files={"pyfun.toml": '[project]\nname = "demo"\n\n[dependencies]\n'})
    r = run(["install"], env_overrides=env)
    assert (r.stdout, r.stderr, r.returncode) == (b"no dependencies in pyfun.toml\n", b"", 0)
    assert calls(workdir) == ""


def test_install_restores_every_pinned_facade(run, workdir):
    """CATCHES: installing unpinned versions, skipping entries, honouring commented-out lines, or not
    re-vendoring; quoted keys, inline comments and an empty version (installed unpinned) are read as in
    the manifest subset of TOML."""
    env = setup(workdir, site={
        "pyfun-textwrap": {"VERSION": "0.1.0\n", "wrap.pyfun": WRAP},
        "pyfun-extra": {"VERSION": "9\n", "extra.pyfun": "let e = 1\n"},
    }, files={"pyfun.toml": '[project]\nname = "demo"\n\n[dependencies]\n# skipped = "1"\n'
                            'pyfun-textwrap = "0.1.0"  # pinned\n"pyfun-extra" = ""\n'})
    r = run(["install"], env_overrides=env)
    assert r.stdout == (b"Successfully installed pyfun-textwrap==0.1.0\nadded pyfun-textwrap 0.1.0 (import Wrap)\n"
                        b"Successfully installed pyfun-extra\nadded pyfun-extra 9 (import Extra)\n")
    assert (r.stderr, r.returncode) == (b"", 0)
    assert calls(workdir) == ("python -m pip install pyfun-textwrap==0.1.0\npython -c <metadata script> pyfun-textwrap\n"
                              "python -m pip install pyfun-extra\npython -c <metadata script> pyfun-extra\n")
    assert tree(workdir) == [".pyfun/facades/pyfun-extra/extra.pyfun", ".pyfun/facades/pyfun-textwrap/wrap.pyfun",
                             "pyfun.toml"]
    assert (workdir / "pyfun.toml").read_text() == (
        '[project]\nname = "demo"\n\n[dependencies]\n# skipped = "1"\npyfun-textwrap = "0.1.0"\npyfun-extra = "9"\n')


def test_install_from_a_subdirectory(run, workdir):
    """CATCHES: `install` only looking in the working directory for `pyfun.toml`."""
    env = setup(workdir, site=TEXTWRAP_SITE, files={"pyfun.toml": '[dependencies]\npyfun-textwrap = "0.1.0"\n',
                                                    "src/.keep": ""})
    r = run(["install"], cwd=workdir / "src", env_overrides=env)
    assert r.stdout == b"Successfully installed pyfun-textwrap==0.1.0\nadded pyfun-textwrap 0.1.0 (import Wrap)\n"
    assert r.returncode == 0
    assert tree(workdir) == [".pyfun/facades/pyfun-textwrap/wrap.pyfun", "pyfun.toml", "src/.keep"]


def test_install_stops_at_the_first_failure(run, workdir):
    """CATCHES: continuing past a failed installation or exiting 0."""
    env = setup(workdir, files={"pyfun.toml": '[dependencies]\npyfun-gone = "1.0"\npyfun-textwrap = "0.1.0"\n'})
    (workdir.parent / "site" / "fail-install").write_text("")
    r = run(["install"], env_overrides=env)
    assert r.stdout == b"ERROR: No matching distribution found for pyfun-gone==1.0\n"
    assert r.stderr == b"error: installing `pyfun-gone==1.0` failed (see the installer's output above)\n"
    assert r.returncode == 1
    assert calls(workdir) == "python -m pip install pyfun-gone==1.0\n"


# ============================================================================ remove


def test_remove_drops_the_entry_the_vendored_copy_and_uninstalls(run, workdir):
    """CATCHES: leaving the manifest entry or the vendored directory behind, not uninstalling with
    `pip uninstall -y`, or a different `removed <dist>` line; other entries and comments survive."""
    env = setup(workdir, files={
        "pyfun.toml": '[project]\nname = "demo"\n\n[dependencies]\n# keep me\npyfun-textwrap = "0.1.0"\nother = "2"\n',
        ".pyfun/facades/pyfun-textwrap/wrap.pyfun": WRAP,
        ".pyfun/facades/other/other.pyfun": "let o = 1\n",
    })
    r = run(["remove", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == b"Found existing installation: pyfun-textwrap\nremoved pyfun-textwrap\n"
    assert (r.stderr, r.returncode) == (b"", 0)
    assert (workdir / "pyfun.toml").read_text() == '[project]\nname = "demo"\n\n[dependencies]\n# keep me\nother = "2"\n'
    assert tree(workdir) == [".pyfun/facades/other/other.pyfun", "pyfun.toml"]
    assert calls(workdir) == "python -m pip uninstall -y pyfun-textwrap\n"


def test_remove_matches_names_after_normalisation(run, workdir):
    """CATCHES: requiring the exact spelling: `Pyfun_Textwrap` removes the `pyfun-textwrap` entry and its
    normalised vendored directory (the installer gets the name as typed)."""
    env = setup(workdir, files={"pyfun.toml": '[dependencies]\npyfun-textwrap = "0.1.0"\n',
                                ".pyfun/facades/pyfun-textwrap/wrap.pyfun": WRAP})
    r = run(["remove", "Pyfun_Textwrap"], env_overrides=env)
    assert r.stdout == b"Found existing installation: Pyfun_Textwrap\nremoved Pyfun_Textwrap\n"
    assert r.returncode == 0
    assert (workdir / "pyfun.toml").read_text() == "[dependencies]\n"
    assert tree(workdir) == ["pyfun.toml"]


def test_remove_several(run, workdir):
    """CATCHES: removing only the first of several packages."""
    env = setup(workdir, files={"pyfun.toml": '[dependencies]\na = "1"\nb = "2"\nc = "3"\n'})
    r = run(["remove", "c", "a"], env_overrides=env)
    assert r.stdout == b"Found existing installation: c\nremoved c\nFound existing installation: a\nremoved a\n"
    assert r.returncode == 0
    assert (workdir / "pyfun.toml").read_text() == '[dependencies]\nb = "2"\n'


def test_remove_an_unknown_package(run, workdir):
    """CATCHES: uninstalling or rewriting the manifest for a package that is not a dependency, or only
    looking at other tables (a `[project] name` is not a dependency)."""
    env = setup(workdir, files={"pyfun.toml": '[project]\nname = "pyfun-textwrap"\n\n[dependencies]\nother = "1"\n'})
    r = run(["remove", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == b""
    assert r.stderr == b"error: `pyfun-textwrap` is not a dependency in pyfun.toml\n"
    assert r.returncode == 1
    assert (workdir / "pyfun.toml").read_text() == '[project]\nname = "pyfun-textwrap"\n\n[dependencies]\nother = "1"\n'
    assert calls(workdir) == ""


def test_remove_through_uv(run, workdir):
    """CATCHES: uninstalling with pip when `uv` is on PATH (it must be `uv pip uninstall --python ...`)."""
    env = setup(workdir, uv=True, files={"pyfun.toml": '[dependencies]\npyfun-textwrap = "0.1.0"\n'})
    r = run(["remove", "pyfun-textwrap"], env_overrides=env)
    assert r.stdout == b"uv: done uninstall pyfun-textwrap\nremoved pyfun-textwrap\n"
    assert r.returncode == 0
    assert calls(workdir) == "uv pip uninstall --python $PYFUN_PYTHON pyfun-textwrap\n"


def test_remove_without_an_interpreter_still_updates_the_project(run, workdir):
    """CATCHES: failing `remove` when no Python is available; the manifest and vendored copy are still
    cleaned up (there is just nothing to uninstall from)."""
    env = setup(workdir, files={"pyfun.toml": '[dependencies]\npyfun-textwrap = "0.1.0"\n',
                                ".pyfun/facades/pyfun-textwrap/wrap.pyfun": WRAP})
    r = run(["remove", "pyfun-textwrap"], env_overrides={**env, "PYFUN_PYTHON": ""})
    assert (r.stdout, r.stderr, r.returncode) == (b"removed pyfun-textwrap\n", b"", 0)
    assert (workdir / "pyfun.toml").read_text() == "[dependencies]\n"
    assert tree(workdir) == ["pyfun.toml"]
