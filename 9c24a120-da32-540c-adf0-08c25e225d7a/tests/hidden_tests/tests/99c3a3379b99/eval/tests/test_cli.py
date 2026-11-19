"""The top-level command-line surface of `pyfun`: usage/help, version, dispatch and argument validation.

Every argument error is a one-line `error: ...` message on stderr with exit status 1 and nothing on
stdout; help goes to stderr with exit status 0; the version goes to stdout.
"""

import pytest

from conftest import assert_no_manifest_above, golden

VERSION = b"pyfun 0.10.0\n"


def assert_error(r, message: str):
    """The exact one-line CLI error contract: nothing on stdout, `error: <message>` on stderr, exit 1."""
    assert r.stdout == b""
    assert r.stderr == f"error: {message}\n".encode()
    assert r.returncode == 1


# ------------------------------------------------------------------ help and version


def test_no_arguments_prints_usage_to_stderr(run):
    """CATCHES: printing the usage to stdout instead of stderr, exiting non-zero when run with no
    arguments, or any drift in the usage text (command list, column alignment, flag spellings)."""
    r = run([])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "usage.golden")
    assert r.returncode == 0


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_flags_print_the_same_usage(run, flag):
    """CATCHES: a `--help`/`-h` that is not recognised (treated as a file path), prints a different text
    from the no-argument usage, writes it to stdout, or exits with a failure status."""
    r = run([flag])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "usage.golden")
    assert r.returncode == 0


def test_help_ignores_whatever_follows_it(run):
    """CATCHES: an implementation that treats `--help check` as per-subcommand help or as an error;
    the first argument alone selects help and the rest is ignored."""
    r = run(["--help", "check", "prog.pyfun"])
    assert r.stdout == b""
    assert r.stderr == golden(__file__, "usage.golden")
    assert r.returncode == 0


@pytest.mark.parametrize("spelling", ["--version", "version"])
def test_version_spellings_print_the_version_on_stdout(run, spelling):
    """CATCHES: a missing alias among `--version` and the `version` word, the version printed on
    stderr, a different version string or format (`pyfun X.Y.Z`), or a non-zero exit."""
    r = run([spelling])
    assert r.stdout == VERSION
    assert r.stderr == b""
    assert r.returncode == 0


def test_version_ignores_trailing_arguments(run):
    """CATCHES: rejecting extra words after `--version` instead of printing the version and exiting 0."""
    r = run(["--version", "extra", "--native"])
    assert r.stdout == VERSION
    assert r.stderr == b""
    assert r.returncode == 0


def test_usage_lists_every_subcommand_once(run):
    """CATCHES: a usage text that drops or duplicates a subcommand line (check, compile, run, build,
    parse, bundle, add, install, remove, lsp, repl, kernel-engine, --version, the bare-path shorthand)."""
    r = run([])
    commands = [line.split()[1] for line in r.stderr.decode().splitlines() if line.startswith("  pyfun ")]
    assert commands == ["check", "compile", "run", "build", "parse", "bundle", "add", "install", "remove", "lsp",
                        "repl", "kernel-engine", "--version", "<file.pyfun>"]
    assert r.returncode == 0


# ------------------------------------------------------------------ missing required arguments


@pytest.mark.parametrize("command", ["check", "compile", "run", "parse", "bundle"])
def test_subcommand_without_a_path_names_the_subcommand(run, command):
    """CATCHES: a subcommand that crashes, prints usage, or reports a generic message when its required
    file path is missing; the reference names the subcommand: "`check` needs a file path"."""
    assert_error(run([command]), f"`{command}` needs a file path")


def test_add_without_a_package_suggests_an_example(run, workdir):
    """CATCHES: `add` with no package doing nothing silently, creating a manifest anyway, or printing a
    different hint than the documented `pyfun add pyfun-textwrap` example."""
    assert_error(run(["add"]), "`add` needs a package, e.g. `pyfun add pyfun-textwrap`")
    assert sorted(p.name for p in workdir.iterdir()) == []


def test_remove_without_a_package(run):
    """CATCHES: `remove` with no package name succeeding silently or failing with another message."""
    assert_error(run(["remove"]), "`remove` needs a package name")


@pytest.mark.parametrize("command", [["install"], ["remove", "pyfun-textwrap"]])
def test_install_and_remove_need_a_manifest(run, workdir, command):
    """CATCHES: `install`/`remove` creating a `pyfun.toml` (only `add` may), or not explaining that no
    manifest was found in the working directory or any parent."""
    assert_no_manifest_above(workdir)
    assert_error(run(command),
                 "no pyfun.toml here or in any parent directory (`pyfun add <package>` creates one)")
    assert sorted(p.name for p in workdir.iterdir()) == []


# ------------------------------------------------------------------ compile argument parsing


@pytest.mark.parametrize("flag", ["-o", "--output"])
def test_compile_output_flag_without_a_value(run, flag):
    """CATCHES: an `-o`/`--output` at the end of the line being ignored, consuming nothing, or reported
    with a message other than "`-o` needs a path" (the long form reports the short spelling too)."""
    assert_error(run(["compile", "prog.pyfun", flag]), "`-o` needs a path")


def test_compile_target_without_a_value(run):
    """CATCHES: a trailing `--target` silently defaulting to 3.12 instead of failing with the list of
    accepted versions."""
    assert_error(run(["compile", "prog.pyfun", "--target"]), "`--target` needs a version (3.11 or 3.12)")


@pytest.mark.parametrize("value", ["3.10", "3.13", "py3.11", "311", ""])
def test_compile_target_rejects_unsupported_versions(run, value):
    """CATCHES: accepting a target other than exactly `3.11` or `3.12` (e.g. 3.13, `py3.11`, an empty
    string), or reporting the rejection without echoing the offending value."""
    assert_error(run(["compile", "prog.pyfun", "--target", value]),
                 f"`--target` must be 3.11 or 3.12, got `{value}`")


def test_compile_rejects_a_second_path(run):
    """CATCHES: silently compiling two files, or using the last path, instead of rejecting the second
    positional argument by name."""
    assert_error(run(["compile", "a.pyfun", "b.pyfun"]), "unexpected argument `b.pyfun`")


def test_compile_rejects_an_unknown_flag_after_the_path(run):
    """CATCHES: unknown flags being ignored; once the path is taken any other word is unexpected."""
    assert_error(run(["compile", "a.pyfun", "--verbose"]), "unexpected argument `--verbose`")


def test_compile_unknown_flag_before_the_path_is_taken_as_the_path(run):
    """CATCHES: rejecting a leading unknown flag; the reference takes the first unrecognised word as the
    file path, so the second word is the unexpected one."""
    assert_error(run(["compile", "--verbose", "a.pyfun"]), "unexpected argument `a.pyfun`")


def test_compile_arguments_are_validated_before_reading_the_file(run):
    """CATCHES: reading/compiling the input before validating every flag: a bad `--target` must be
    reported even though the input file does not exist."""
    assert_error(run(["compile", "missing.pyfun", "--target", "2.7"]), "`--target` must be 3.11 or 3.12, got `2.7`")


def test_compile_flags_only_still_needs_a_path(run):
    """CATCHES: treating `--native`/`--target` values as the input path when no path is given."""
    assert_error(run(["compile", "--native", "--target", "3.11", "-o", "out.py"]), "`compile` needs a file path")


# ------------------------------------------------------------------ bundle argument parsing


def test_bundle_needs_an_output_directory(run):
    """CATCHES: `bundle` defaulting to some output directory (or the current one) instead of requiring
    `-o <dir>` with the documented explanation."""
    assert_error(run(["bundle", "prog.pyfun"]), "`bundle` needs `-o <dir>` (the page's directory)")


@pytest.mark.parametrize("flag", ["-o", "--output"])
def test_bundle_output_flag_without_a_value(run, flag):
    """CATCHES: a dangling `-o`/`--output` for bundle reported with the compile wording ("a path")
    instead of bundle's "`-o` needs a directory"."""
    assert_error(run(["bundle", "prog.pyfun", flag]), "`-o` needs a directory")


def test_bundle_asset_flag_without_a_value(run):
    """CATCHES: a trailing `--asset` being ignored instead of rejected with its own message."""
    assert_error(run(["bundle", "prog.pyfun", "-o", "site", "--asset"]), "`--asset` needs a file path")


def test_bundle_page_flag_without_a_value(run):
    """CATCHES: a trailing `--page` being ignored instead of rejected with its own message."""
    assert_error(run(["bundle", "prog.pyfun", "-o", "site", "--page"]), "`--page` needs an HTML file")


def test_bundle_rejects_a_second_path(run):
    """CATCHES: bundling several entries or using the last one instead of rejecting the extra word."""
    assert_error(run(["bundle", "prog.pyfun", "other.pyfun", "-o", "site"]), "unexpected argument `other.pyfun`")


def test_bundle_without_a_path_but_with_an_output(run):
    """CATCHES: taking the `-o` value as the entry; the entry is still missing and must be reported first."""
    assert_error(run(["bundle", "-o", "site"]), "`bundle` needs a file path")


def test_bundle_validates_arguments_before_compiling(run, workdir):
    """CATCHES: compiling or creating the output directory before the argument list is validated."""
    (workdir / "prog.pyfun").write_text("print 1\n")
    assert_error(run(["bundle", "prog.pyfun", "-o", "site", "extra"]), "unexpected argument `extra`")
    assert sorted(p.name for p in workdir.iterdir()) == ["prog.pyfun"]


# ------------------------------------------------------------------ build argument parsing


@pytest.mark.parametrize("args", [[], ["prog.pyfun"], ["prog.pyfun", "-o", "out"]])
def test_build_requires_the_native_flag(run, args):
    """CATCHES: `build` without `--native` doing a non-native build or failing with another message; the
    reference insists on `--native` first, before checking the path or the output directory."""
    assert_error(run(["build", *args]),
                 "`build` compiles with mypyc and needs `--native` (pyfun build --native <file> -o <dir>)")


def test_build_native_needs_a_path(run):
    """CATCHES: a missing input path for `build --native` not being reported (or reported after `-o`)."""
    assert_error(run(["build", "--native", "-o", "out"]), "`build` needs a file path")


@pytest.mark.parametrize("args", [["prog.pyfun"], ["prog.pyfun", "-o"], ["prog.pyfun", "--output"]])
def test_build_native_needs_an_output_directory(run, args):
    """CATCHES: `build` defaulting the output directory, or reporting a dangling `-o` differently from a
    missing one (the reference reports both as a missing output directory)."""
    assert_error(run(["build", "--native", *args]), "`build` needs an output directory (-o <dir>)")


def test_build_rejects_a_second_path(run):
    """CATCHES: building two files or ignoring the extra positional argument."""
    assert_error(run(["build", "--native", "a.pyfun", "b.pyfun", "-o", "out"]), "unexpected argument `b.pyfun`")


def test_build_rejects_an_unknown_flag_before_checking_native(run):
    """CATCHES: argument order bugs: an unexpected word is rejected while scanning, even before the
    missing `--native` would be reported."""
    assert_error(run(["build", "a.pyfun", "--fast"]), "unexpected argument `--fast`")


# ------------------------------------------------------------------ input files


@pytest.mark.parametrize("command", [["check"], ["compile"], ["run"], ["parse"], []])
def test_missing_input_file_is_reported_with_the_os_error(run, command):
    """CATCHES: a crash or a different message when the input does not exist; every reading command
    (and the bare-path shorthand) reports `cannot read <path>: <OS error>` and exits 1."""
    assert_error(run([*command, "nope.pyfun"]), "cannot read nope.pyfun: No such file or directory (os error 2)")


def test_bundle_missing_input_file(run, workdir):
    """CATCHES: `bundle` creating its output directory before it has read the entry file."""
    assert_error(run(["bundle", "nope.pyfun", "-o", "site"]),
                 "cannot read nope.pyfun: No such file or directory (os error 2)")
    assert sorted(p.name for p in workdir.iterdir()) == []


def test_build_missing_input_file(run, workdir):
    """CATCHES: `build` creating the output directory, or wording the read error differently, when the
    input does not exist."""
    assert_error(run(["build", "--native", "nope.pyfun", "-o", "out"]),
                 "cannot read nope.pyfun: No such file or directory (os error 2)")
    assert sorted(p.name for p in workdir.iterdir()) == []


def test_reading_a_directory_reports_the_os_error(run, workdir):
    """CATCHES: treating a directory argument as an empty program (or crashing) instead of reporting
    that it cannot be read."""
    (workdir / "src.pyfun").mkdir()
    assert_error(run(["check", "src.pyfun"]), "cannot read src.pyfun: Is a directory (os error 21)")


def test_reading_invalid_utf8_is_an_error(run, workdir):
    """CATCHES: lossy decoding of a non-UTF-8 source file instead of refusing it with the read error."""
    (workdir / "latin1.pyfun").write_bytes(b"let caf\xe9 = 1\n")
    assert_error(run(["check", "latin1.pyfun"]), "cannot read latin1.pyfun: stream did not contain valid UTF-8")


def test_unknown_word_is_treated_as_a_file_to_compile(run):
    """CATCHES: an unknown subcommand or flag being reported as such; the reference treats any other
    first word as the bare-path shorthand for `compile` and tries to read it."""
    assert_error(run(["frobnicate"]), "cannot read frobnicate: No such file or directory (os error 2)")
    assert_error(run(["--bogus"]), "cannot read --bogus: No such file or directory (os error 2)")


def test_subcommand_names_are_case_sensitive(run):
    """CATCHES: case-insensitive subcommand matching: `CHECK` is a file name for the shorthand, not `check`."""
    assert_error(run(["CHECK", "prog.pyfun"]), "cannot read CHECK: No such file or directory (os error 2)")


def test_bare_path_shorthand_compiles_to_stdout(run, workdir):
    """CATCHES: the documented `pyfun <file.pyfun>` shorthand doing anything other than exactly what
    `pyfun compile <file.pyfun>` does (same Python on stdout, nothing on stderr, exit 0)."""
    (workdir / "prog.pyfun").write_text("let add a b = a + b\nprint (add 1 2)\n")
    short = run(["prog.pyfun"])
    full = run(["compile", "prog.pyfun"])
    assert short.stdout == b"def add(a, b):\n    return a + b\nprint(add(1, 2))\n"
    assert (short.stdout, short.stderr, short.returncode) == (full.stdout, full.stderr, full.returncode)
    assert short.stderr == b""
    assert short.returncode == 0
