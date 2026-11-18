"""Help, usage and version output of the top-level command and every subcommand."""

import hashlib
import re
from pathlib import Path

from conftest import assert_run_golden


def test_dash_h_prints_help_with_subcommands(run):
    """CATCHES: a -h that prints to stdout, exits non-zero, omits the subcommand list before the flags, or
    renders the analyzer description differently from the reference help text."""
    r = run(["-h"])
    assert_run_golden(__file__, "help_h", r)


def test_single_dash_help_word(run):
    """CATCHES: an implementation that rejects the Go-style -help spelling, which the flag package accepts
    as a request for the same usage text as -h."""
    r = run(["-help"])
    assert_run_golden(__file__, "help_h", r)


def test_bare_invocation_prints_help_and_exits_1(run):
    """CATCHES: a bare run that analyzes the current directory, exits 0, or prints a shorter usage than
    -h; the reference prints the full help on stderr and exits with status 1."""
    r = run([])
    assert_run_golden(__file__, "bare", r)


def test_unknown_flag_exits_2_with_message_and_help(run):
    """CATCHES: an unknown flag that is ignored, treated as a package, or reported without the
    'flag provided but not defined' line followed by the full help and exit status 2."""
    r = run(["-nonsense"])
    assert_run_golden(__file__, "unknown_flag", r)


def test_flags_without_package_print_driver_usage(run):
    """CATCHES: a run with flags but no package pattern that defaults to ./... or prints the
    subcommand-bearing help; the driver answers with its own short usage and exit status 1."""
    r = run(["-fix"])
    assert_run_golden(__file__, "flags_no_package", r)


def test_version_full_line_shape(run):
    """CATCHES: a -V=full that prints only a version number, omits the comments-go-here field the go
    command's tool-ID protocol expects, or prints a buildID that is not the SHA-256 of the binary."""
    r = run(["-V=full"])
    out = r.stdout.decode()
    m = re.fullmatch(r"(/\S+) version (\S+) comments-go-here buildID=([0-9a-f]{64})\n", out)
    assert m is not None, out
    assert hashlib.sha256(Path(m.group(1)).read_bytes()).hexdigest() == m.group(3)
    normalized = out.replace(m.group(1), "$EXE", 1).replace(m.group(3), "$SHA256")
    assert normalized == "$EXE version devel comments-go-here buildID=$SHA256\n"
    assert r.stderr == b""
    assert r.returncode == 0


def test_version_rejects_other_value(run):
    """CATCHES: a -V that accepts any value; -V=short must be refused with the message naming -V=full,
    followed by the help, and exit status 2."""
    r = run(["-V=short"])
    assert_run_golden(__file__, "version_short", r)


def test_version_bare_flag_is_refused(run):
    """CATCHES: treating a bare -V as -V=full; the reference treats it as -V=true and refuses it with
    'invalid boolean flag V' and exit status 2."""
    r = run(["-V"])
    assert_run_golden(__file__, "version_bare", r)


def test_flags_prints_analyzer_flags_json(run):
    """CATCHES: a -flags that is missing, prints the wrong set of flags, or describes them differently
    from the JSON the go vet protocol reads (names, Bool and Usage fields, in order)."""
    r = run(["-flags"])
    assert_run_golden(__file__, "flags_json", r)


def test_baseline_help(run):
    """CATCHES: baseline -h text that drifts from the reference: the description of where entries are
    written, -merge, -shrink, and the flag list with the -shrink default of true."""
    r = run(["baseline", "-h"])
    assert_run_golden(__file__, "baseline_help", r)


def test_baseline_unknown_flag(run):
    """CATCHES: a baseline subcommand that ignores unknown flags instead of printing the complaint and
    its usage, exiting 2 before loading anything."""
    r = run(["baseline", "-bogus"])
    assert_run_golden(__file__, "baseline_unknown_flag", r)


def test_survey_help(run):
    """CATCHES: survey -h text that lists the wrong flags, misses -allow-errors, or shows a different
    default for -format or -test."""
    r = run(["survey", "-h"])
    assert_run_golden(__file__, "survey_help", r)


def test_survey_unknown_flag(run):
    """CATCHES: a survey subcommand that accepts the analyzer's -fix flag instead of refusing it as
    undefined with exit status 2."""
    r = run(["survey", "-fix"])
    assert_run_golden(__file__, "survey_unknown_flag", r)


def test_inspect_help(run):
    """CATCHES: inspect -h text that differs from the reference, such as missing the explanation that
    it takes exactly one package."""
    r = run(["inspect", "-h"])
    assert_run_golden(__file__, "inspect_help", r)


def test_inspect_without_package_prints_usage_exit_2(run):
    """CATCHES: an inspect with no package that defaults to ./... or the current directory; the reference
    prints its usage on stderr and exits 2."""
    r = run(["inspect"])
    assert_run_golden(__file__, "inspect_no_package", r)


def test_inspect_flags_only_prints_usage_exit_2(run):
    """CATCHES: an inspect that treats parsed flags as satisfying its one required package argument."""
    r = run(["inspect", "-format=json", "-test=false"])
    assert_run_golden(__file__, "inspect_no_package", r)


def test_inspect_unknown_flag(run):
    """CATCHES: an inspect subcommand that accepts -allow-errors, which only survey defines."""
    r = run(["inspect", "-allow-errors", "./x"])
    assert_run_golden(__file__, "inspect_unknown_flag", r)


def test_shrink_help(run):
    """CATCHES: shrink -h text that differs from the reference, such as omitting that every package of
    the module is loaded or listing flags other than -config and -fix."""
    r = run(["shrink", "-h"])
    assert_run_golden(__file__, "shrink_help", r)


def test_shrink_unknown_flag(run):
    """CATCHES: a shrink subcommand that accepts -diff, which only the analyzer driver defines."""
    r = run(["shrink", "-diff"])
    assert_run_golden(__file__, "shrink_unknown_flag", r)


def test_skill_bare_prints_overview(run):
    """CATCHES: a bare 'skill' that errors, or whose overview omits the three subcommands, the shared
    flag block or the embedded skill list with truncated descriptions; it exits 0 on stdout."""
    r = run(["skill"])
    assert_run_golden(__file__, "skill_overview", r)


def test_skill_help_word(run):
    """CATCHES: a skill command that does not take 'help' as a request for its overview."""
    r = run(["skill", "help"])
    assert_run_golden(__file__, "skill_overview", r)


def test_skill_dash_h(run):
    """CATCHES: a skill command that does not take -h as a request for its overview."""
    r = run(["skill", "-h"])
    assert_run_golden(__file__, "skill_overview", r)


def test_skill_install_help(run):
    """CATCHES: skill install -h whose summary does not warn that install removes skills the binary no
    longer carries, or whose usage line differs from the reference."""
    r = run(["skill", "install", "-h"])
    assert_run_golden(__file__, "skill_install_help", r)


def test_skill_uninstall_help(run):
    """CATCHES: skill uninstall -help that prints the overview or the install help instead of its
    own summary and usage line."""
    r = run(["skill", "uninstall", "-help"])
    assert_run_golden(__file__, "skill_uninstall_help", r)


def test_skill_list_help(run):
    """CATCHES: skill list -help that prints another subcommand's summary or fails."""
    r = run(["skill", "list", "-help"])
    assert_run_golden(__file__, "skill_list_help", r)


def test_skill_unknown_subcommand(run):
    """CATCHES: an unknown skill subcommand that exits 0 or prints its usage on stdout; the reference
    writes the overview to stderr, then 'declscope: unknown skill subcommand', and exits 1."""
    r = run(["skill", "bogus"])
    assert_run_golden(__file__, "skill_unknown_sub", r)


def test_skill_install_unknown_flag(run):
    """CATCHES: skill install that ignores an unknown flag; the reference prints the install help on
    stderr followed by the flag error and exits 1 (not 2)."""
    r = run(["skill", "install", "--bogus"])
    assert_run_golden(__file__, "skill_install_unknown_flag", r)


def test_skill_ls_alias_help(run):
    """CATCHES: an implementation without the 'ls' alias of 'list'; skill ls -h prints the list help."""
    r = run(["skill", "ls", "-h"])
    assert_run_golden(__file__, "skill_list_help", r)


def test_skill_remove_alias_help(run):
    """CATCHES: an implementation without the 'remove' alias of 'uninstall'."""
    r = run(["skill", "remove", "-h"])
    assert_run_golden(__file__, "skill_uninstall_help", r)


def test_help_does_not_need_a_module(run, workdir):
    """CATCHES: a help path that consults the go command or the working directory; help in a directory
    with a broken go.mod is still printed unchanged."""
    (workdir / "go.mod").write_text("this is not a go.mod\n")
    r = run(["-h"])
    assert_run_golden(__file__, "help_h", r)
