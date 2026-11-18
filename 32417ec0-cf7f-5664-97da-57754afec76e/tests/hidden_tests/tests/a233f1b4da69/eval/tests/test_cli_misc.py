"""The top-level command: its help, -V=full, -flags, the analyzer's -config/-c/-json/-diff output modes, and the
skill subcommand."""

import hashlib
import subprocess

import pytest

from conftest import EXECUTABLE, assert_golden, gomod, snapshot, changes, transcript, write_files

CROSSING = {
    "go.mod": gomod("example.com/m"),
    "user.go": "package p\n\nfunc helper() int { return 1 }\n\ntype box struct {\n\tn int\n}\n",
    "order.go": "package p\n\nfunc orderRun() int {\n\treturn helper() + box{}.n\n}\n\nvar _ = orderRun\n",
}


def test_bare_invocation_prints_help_and_exits_1(run, workdir):
    """CATCHES: a declscope with no argument that analyzes the working directory, prints nothing, or exits 0 instead
    of printing the help, subcommands included, and exiting 1."""
    assert_golden(transcript(run([]), workdir), __file__, "bare")


def test_dash_h_lists_subcommands_and_flags(run, workdir):
    """CATCHES: a -h that leaves out the subcommands, the analyzer's flags (-config, -test, -fix, -diff, -V), or exits
    with a non-zero status."""
    assert_golden(transcript(run(["-h"]), workdir), __file__, "help")


def test_unknown_flag(run, workdir):
    """CATCHES: an unknown top-level flag that is ignored or treated as a package instead of exiting 2 with the help."""
    assert_golden(transcript(run(["-bogus", "./..."]), workdir), __file__, "unknown_flag")


def test_version_full(run, workdir):
    """CATCHES: a -V=full that does not print the tool-ID line go vet reads: the executable's path, version devel
    for an unstamped build, and the sha256 of the binary as buildID."""
    r = run(["-V=full"])
    digest = hashlib.sha256(EXECUTABLE.read_bytes()).hexdigest()
    expected = f"{EXECUTABLE.resolve()} version devel comments-go-here buildID={digest}\n"
    assert (r.returncode, r.stdout.decode(), r.stderr.decode()) == (0, expected, "")


@pytest.mark.parametrize("arg", ["-V=short", "-V"])
def test_version_refuses_other_values(run, workdir, arg):
    """CATCHES: a -V that accepts a value other than full (or no value) instead of refusing it with the help and
    exit 2, as the tool-ID protocol expects."""
    assert_golden(transcript(run([arg]), workdir), __file__, f"version_{arg.strip('-').replace('=', '_')}")


def test_flags_json(run, workdir):
    """CATCHES: a -flags that does not print the analyzer's flags as JSON, as the go vet -vettool protocol reads
    them."""
    assert_golden(transcript(run(["-flags"]), workdir), __file__, "flags")


def test_outside_a_module(run, workdir):
    """CATCHES: an analyzer run outside any module that exits 0 as if nothing were wrong."""
    assert_golden(transcript(run(["./..."]), workdir), __file__, "outside_module")


def test_report_exit_status_and_related_uses(run, workdir):
    """CATCHES: an analyzer that reports a crossing on the use instead of the declaration, omits a use site, or exits
    with a status other than 3 when it reports."""
    write_files(workdir, CROSSING)
    assert_golden(transcript(run(["./..."]), workdir), __file__, "report")


def test_context_lines(run, workdir):
    """CATCHES: a -c that does not print the offending line with the requested lines of context."""
    write_files(workdir, CROSSING)
    assert_golden(transcript(run(["-c=1", "./..."]), workdir), __file__, "context")


def test_json_output(run, workdir):
    """CATCHES: a -json that drops the rule category, the suggested fix and its edits, or the related use positions,
    or that exits 3 (the driver reports JSON with status 0)."""
    write_files(workdir, CROSSING)
    assert_golden(transcript(run(["-json", "./..."]), workdir), __file__, "json")


def test_fix_diff_prints_without_writing(run, workdir):
    """CATCHES: a -fix -diff that writes the files, or prints a diff that differs from the fix -fix would write."""
    write_files(workdir, CROSSING)
    before = snapshot(workdir)
    diff = transcript(run(["-fix", "-diff", "./..."]), workdir) + changes(before, workdir)
    fixed = transcript(run(["-fix", "./..."]), workdir) + changes(before, workdir)
    assert_golden(diff + "\n=== -fix\n" + fixed, __file__, "fix_diff")


def test_test_false_skips_test_files(run, workdir):
    """CATCHES: a -test=false that still reads _test.go files, so a crossing made only by a test is reported."""
    write_files(workdir, {
        "go.mod": gomod("example.com/m"),
        "user.go": "package p\n\nfunc helper() int { return 1 }\n",
        "order_test.go": "package p\n\nvar _ = helper()\n",
    })
    with_tests = transcript(run(["./..."]), workdir)
    without = transcript(run(["-test=false", "./..."]), workdir)
    assert_golden(with_tests + "\n=== -test=false\n" + without, __file__, "test_false")


def test_explicit_config(run, workdir):
    """CATCHES: -config that does not replace the discovered config, or that silently ignores a missing file."""
    write_files(workdir, {
        **CROSSING,
        ".declscope.yaml": "rules:\n  boundary: off\n",
        "loud.yaml": "rules:\n  naming:\n    qualify: always\n",
    })
    discovered = transcript(run(["./..."]), workdir)
    explicit = transcript(run(["-config", "loud.yaml", "./..."]), workdir)
    missing = transcript(run(["-config", "nope.yaml", "./..."]), workdir)
    assert_golden(discovered + "\n=== -config loud.yaml\n" + explicit + "\n=== -config nope.yaml\n" + missing,
                  __file__, "explicit_config")


def test_skill_help(run, workdir):
    """CATCHES: a skill subcommand without arguments that does nothing, or that does not list the embedded
    declscope-adoption and declscope-authoring skills and the flags."""
    assert_golden(transcript(run(["skill"]), workdir), __file__, "skill_help")


def test_skill_install_into_a_directory(run, workdir):
    """CATCHES: a skill install -dir that writes elsewhere, writes something other than the two SKILL.md files, or
    a list that does not then report them current."""
    install = transcript(run(["skill", "install", "-dir", "out"]), workdir)
    listed = transcript(run(["skill", "list", "-dir", "out"]), workdir)
    files = sorted(p.relative_to(workdir).as_posix() for p in (workdir / "out").rglob("*") if p.is_file())
    assert_golden(install + "\n=== list\n" + listed + "\n=== files\n" + "\n".join(files) + "\n", __file__, "skill_dir")


def test_skill_install_dry_run_writes_nothing(run, workdir):
    """CATCHES: a skill install -dry-run that writes the skills, or does not report what it would do."""
    out = transcript(run(["skill", "install", "-dry-run", "-dir", "out"]), workdir)
    assert_golden(out + f"\nwritten: {(workdir / 'out').exists()}\n", __file__, "skill_dry_run")


def test_skill_uninstall(run, workdir):
    """CATCHES: a skill uninstall that leaves the installed skills in place or removes other files."""
    run(["skill", "install", "-dir", "out"])
    (workdir / "out" / "keep.txt").write_text("mine\n")
    out = transcript(run(["skill", "uninstall", "-dir", "out"]), workdir)
    left = sorted(p.relative_to(workdir).as_posix() for p in (workdir / "out").rglob("*"))
    assert_golden(out + "\n=== left\n" + "\n".join(left) + "\n", __file__, "skill_uninstall")


@pytest.mark.parametrize("argv", [["baseline", "./p"], ["survey", "./p"], ["inspect", "./p"], ["inspect", "./..."],
                                  ["./p"]])
def test_go_command_that_cannot_list(run, workdir, argv):
    """CATCHES: a subcommand (or the analyzer) that reads a go command unable to list anything (GOFLAGS=-mod=bogus)
    as a module with nothing in it, instead of stopping with the go command's error."""
    write_files(workdir, {"go.mod": gomod("example.com/m"), "p/p.go": "package p\n"})
    r = run(argv, env_overrides={"GOFLAGS": "-mod=bogus"})
    assert_golden(transcript(r, workdir), __file__, "mod_bogus_" + "_".join(a.strip("./") or "all" for a in argv))


@pytest.mark.parametrize("argv", [["survey", "./..."], ["survey", "-format=json", "./..."], ["inspect", "."],
                                  ["inspect", "-format=json", "."]])
def test_report_that_cannot_be_written(workdir, env, argv):
    """CATCHES: a survey or inspect whose report cannot be written (stdout is a full device) that exits 0 as if the
    report had been delivered, instead of naming the write error and exiting 1."""
    write_files(workdir, CROSSING)
    with open("/dev/full", "wb") as full:
        r = subprocess.run([str(EXECUTABLE), *argv], cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=full,
                           stderr=subprocess.PIPE, timeout=20)
    assert (r.returncode, r.stderr.decode()) == (1, f"declscope {argv[0]}: write /dev/stdout: no space left on device\n")
