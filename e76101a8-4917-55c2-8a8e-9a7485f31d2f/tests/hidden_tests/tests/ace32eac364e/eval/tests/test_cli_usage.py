"""The top-level command line: usage, version, and how wrong invocations are refused."""

import pytest


USAGE_CASES = {
    "no_arguments": [],
    "help_flag": ["--help"],
    "short_help_flag": ["-h"],
    "help_word": ["help"],
    "unknown_subcommand": ["frobnicate"],
    "version_with_extra_argument": ["--version", "x"],
    "info_without_file": ["info"],
    "info_with_two_files": ["info", "a.bimcraft", "b.bimcraft"],
    "convert_with_one_path": ["convert", "a.bimcraft"],
    "convert_with_three_paths": ["convert", "a.bimcraft", "b.ifc", "c.svg"],
    "commands_with_argument": ["commands", "wall"],
    "subcommand_in_upper_case": ["RUN"],
    "empty_string_argument": [""],
}


@pytest.mark.parametrize("case", sorted(USAGE_CASES))
def test_wrong_invocations_print_the_usage_and_fail(run, golden, case):
    """CATCHES: a rewrite that accepts a malformed top-level invocation, prints the usage to stdout instead of stderr,
    exits 0 or 2 instead of 1, or words the usage text differently from the reference."""
    r = run(USAGE_CASES[case])
    assert r.stdout == b""
    assert r.returncode == 1
    assert r.stderr.decode() == golden.read("usage.txt")


def test_usage_text_is_the_documented_one(run, golden):
    """CATCHES: a rewrite whose usage omits a subcommand (run, info, convert, commands, mcp, --version) or an option
    of run (--sample, --highrise, --cmd, --script, --save), or changes its layout."""
    r = run([])
    golden.check(r.stderr.decode(), "usage.txt")
    assert r.returncode == 1


def test_version_names_the_release(run):
    """CATCHES: a rewrite that prints a different program name or release number for --version, writes it to
    stderr, or exits non-zero."""
    r = run(["--version"])
    assert r.stdout == b"bimcraft-cli 0.10.0\n"
    assert r.stderr == b""
    assert r.returncode == 0


def test_version_is_only_a_lone_argument(run, golden):
    """CATCHES: a rewrite that prints the version when --version comes after a subcommand instead of treating it as an
    unknown option of run."""
    r = run(["run", "--version"])
    golden.check_run(r, "run_version.txt")


def test_commands_takes_no_options(run, golden):
    """CATCHES: a rewrite that lets `commands --json` through as if it were the plain catalog."""
    r = run(["commands", "--json"])
    assert r.stdout == b""
    assert r.returncode == 1
    assert r.stderr.decode() == golden.read("usage.txt")


def test_commands_prints_the_whole_catalog(run, golden):
    """CATCHES: a rewrite whose `commands` catalog leaves out, renames or reorders a command, changes a label, a shortcut,
    a menu or a params doc, or prints it as compact rather than pretty JSON."""
    r = run(["commands"])
    golden.check_run(r, "commands.txt")


def test_every_shortcut_runs_its_command(run, workdir, golden):
    """CATCHES: a rewrite where a Revit-style shortcut from the catalog (typed in lower case) is not accepted in a script
    in place of its command's id, or resolves to another command (CL is both column's and structural_column's: the first
    in the catalog wins)."""
    import json
    from concurrent.futures import ThreadPoolExecutor

    from conftest import normalize

    catalog = json.loads(run(["commands"]).stdout)
    # Each runs alone on an empty project with a key no command takes: most then fail in words that name the command
    # the shortcut stands for.
    lines = [f"{alias.lower()} {{\"zzz\": 1}}" for c in catalog for alias in c["aliases"]]

    def one(line):
        r = run(["run", "--cmd", line])
        return f"$ {line}\nexit {r.returncode}\n{normalize(r.stdout.decode())}{normalize(r.stderr.decode())}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        golden.check("".join(pool.map(one, lines)), "shortcuts.txt")
