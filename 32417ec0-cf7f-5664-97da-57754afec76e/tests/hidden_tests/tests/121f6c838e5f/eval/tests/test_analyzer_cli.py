"""The analyzer driver: its flags, exit codes, output formats, -fix and -diff."""

import json

from conftest import GO_MOD, assert_golden, assert_run_golden, normalize

USER_REPO = """package database

import "strings"

type UserRepository struct{}

func scanUser(s string) string {
	return normalizeEmail(s)
}

func normalizeEmail(s string) string {
	return strings.ToLower(strings.TrimSpace(s))
}
"""

ORDER_REPO = """package database

type OrderRepository struct{}

func scanOrder(s string) string {
	return normalizeEmail(s)
}
"""

ORDER_TEST = """package database

import "testing"

func TestScan(t *testing.T) {
	_ = scanUser("x")
}
"""

CROSSING = {
    "go.mod": GO_MOD,
    "database/user_repository.go": USER_REPO,
    "database/order_repository.go": ORDER_REPO,
    "database/order_repository_test.go": ORDER_TEST,
}

# The same package without its test file: most tests are not about tests, and a test file makes every
# load also build a test binary's package graph.
CROSSING_NO_TEST = {k: v for k, v in CROSSING.items() if not k.endswith("_test.go")}

CLEAN = {
    "go.mod": GO_MOD,
    "clean/clean.go": "package clean\n\nfunc helper() int { return 1 }\n\nfunc Use() int { return helper() }\n",
}


def test_reports_crossing_and_exits_3(run, tree, workdir):
    """CATCHES: a driver that does not report a private helper used from another file, misattributes the
    namespaces, omits the indented 'used here' related line, or exits with anything but 3."""
    tree(CROSSING)
    r = run(["./..."])
    assert_run_golden(__file__, "crossing_text", r, workdir)


def test_clean_package_exits_0_silently(run, tree, workdir):
    """CATCHES: a driver that prints anything or exits non-zero for a package whose private helper is
    only used inside its own file."""
    tree(CLEAN)
    r = run(["./..."])
    assert_run_golden(__file__, "clean", r, workdir)
    j = run(["-json", "./..."])
    assert normalize(j.stdout, workdir) == "{}\n"


def test_test_false_skips_test_files(run, tree, workdir):
    """CATCHES: -test=false still reading _test.go files: the crossing from order_repository_test.go into
    scanUser must disappear while the non-test crossing stays."""
    tree(CROSSING)
    r = run(["-test=false", "./..."])
    assert_run_golden(__file__, "crossing_no_tests", r, workdir)


def test_json_output_exits_0(run, tree, workdir):
    """CATCHES: -json that keeps exit status 3, drops the category, the suggested fix edits with byte
    offsets, or the related use sites, or does not key results by package and test variant."""
    tree(CROSSING)
    r = run(["-json", "./..."])
    assert r.returncode == 0
    assert r.stderr == b""
    data = json.loads(r.stdout)
    assert sorted(data) == ["example.com/app/database", "example.com/app/database [example.com/app/database.test]"]
    assert_golden(__file__, "crossing_json", normalize(r.stdout, workdir))


def test_context_lines(run, tree, workdir):
    """CATCHES: -c N that prints no source context, the wrong number of lines around each position, or
    no context for the related use sites."""
    tree(CROSSING_NO_TEST)
    r = run(["-c", "1", "-test=false", "./..."])
    assert_run_golden(__file__, "context_1", r, workdir)


def test_context_zero_lines(run, tree, workdir):
    """CATCHES: -c=0 that is treated like the default -1 (no context) instead of printing just the
    offending line itself."""
    tree(CROSSING_NO_TEST)
    r = run(["-c=0", "-test=false", "./..."])
    assert_run_golden(__file__, "context_0", r, workdir)


def test_fix_inserts_shared_directive(run, tree, workdir):
    """CATCHES: -fix that does not write //declscope:shared directly above each crossed declaration, writes
    it elsewhere, or touches the file whose use crossed the boundary."""
    tree(CROSSING)
    r = run(["-fix", "./..."])
    assert r.returncode == 0
    assert normalize(r.stdout, workdir) == ""
    assert normalize(r.stderr, workdir) == ""
    assert_golden(__file__, "fixed_user_repository", (workdir / "database/user_repository.go").read_text())
    assert (workdir / "database/order_repository.go").read_text() == ORDER_REPO


def test_fix_converges_in_one_pass(run, tree, workdir):
    """CATCHES: a fix that leaves new reports behind (for example an unused or surplus report on the
    inserted directive); a second plain run after -fix must be clean."""
    tree(CROSSING)
    run(["-fix", "./..."])
    r = run(["./..."])
    assert_run_golden(__file__, "after_fix", r, workdir)
    assert_golden(__file__, "fixed_user_repository", (workdir / "database/user_repository.go").read_text())


def test_fix_diff_prints_diff_without_writing(run, tree, workdir):
    """CATCHES: -fix -diff that writes the files anyway, or prints a diff that differs from the reference
    unified diff with (old)/(new) headers."""
    tree(CROSSING)
    r = run(["-fix", "-diff", "./..."])
    assert_run_golden(__file__, "fix_diff", r, workdir)
    assert (workdir / "database/user_repository.go").read_text() == USER_REPO


def test_diff_without_fix_reports_normally(run, tree, workdir):
    """CATCHES: -diff alone acting like -fix -diff; without -fix the driver reports as usual and exits 3."""
    tree(CROSSING_NO_TEST)
    r = run(["-diff", "-test=false", "./..."])
    assert_run_golden(__file__, "crossing_no_tests", r, workdir)


def test_named_package_directory(run, tree, workdir):
    """CATCHES: a driver that only accepts ./... and not a single package directory pattern."""
    tree(CROSSING)
    r = run(["./database"])
    assert_run_golden(__file__, "crossing_text", r, workdir)


def test_import_path_pattern(run, tree, workdir):
    """CATCHES: a driver that does not resolve full import-path patterns through the go command."""
    tree(CROSSING_NO_TEST)
    r = run(["example.com/app/database"])
    assert_run_golden(__file__, "crossing_no_tests", r, workdir)


def test_missing_directory_pattern(run, tree, workdir):
    """CATCHES: a missing package directory that is silently skipped with exit 0 instead of the go
    command's error and 'analysis skipped due to errors in package' with exit 1."""
    tree(CLEAN)
    r = run(["./missing"])
    assert_run_golden(__file__, "missing_dir", r, workdir)


def test_type_error_skips_analysis(run, tree, workdir):
    """CATCHES: a driver that analyzes a package that does not type-check (and so reports nothing and
    exits 0) instead of printing the compiler error and exiting 1."""
    tree({"go.mod": GO_MOD, "broken/b.go": "package broken\n\nfunc f() int { return \"x\" }\n"})
    r = run(["./broken"])
    assert_run_golden(__file__, "type_error", r, workdir)


def test_explicit_config_missing_file(run, tree, workdir):
    """CATCHES: a -config naming a missing file that falls back to discovery or defaults; the reference
    fails each package with 'open <path>: no such file or directory' and exits 1."""
    tree(CLEAN)
    r = run(["-config", "nope.yaml", "-test=false", "./..."])
    assert_run_golden(__file__, "config_missing", r, workdir)


def test_explicit_config_is_directory(run, tree, workdir):
    """CATCHES: a -config naming a directory that is accepted as an empty config."""
    tree(CLEAN)
    r = run(["-config", "clean", "-test=false", "./..."])
    assert_run_golden(__file__, "config_is_dir", r, workdir)


def test_explicit_config_skips_discovery(run, tree, workdir):
    """CATCHES: -config that is merged with a discovered .declscope.yaml; the discovered file here is
    invalid, and naming a valid file explicitly must not read it at all."""
    tree(CROSSING_NO_TEST)
    tree({".declscope.yaml": "rules:\n  nonsense: 1\n", "other.yaml": "rules:\n  boundary: off\n"})
    discovered = run(["-test=false", "./..."])
    r = run(["-config", "other.yaml", "./..."])
    assert_run_golden(__file__, "discovered_invalid", discovered, workdir)
    assert_run_golden(__file__, "clean", r, workdir)


def test_empty_config_flag_value_means_discovery(run, tree, workdir):
    """CATCHES: -config= (empty) being treated as a path to open rather than as 'no explicit config'."""
    tree(CROSSING_NO_TEST)
    r = run(["-config=", "./..."])
    assert_run_golden(__file__, "crossing_no_tests", r, workdir)


def test_two_packages_in_one_run(run, tree, workdir):
    """CATCHES: a driver that stops after the first package with findings or merges both packages'
    namespaces; each package is analyzed on its own."""
    tree(CROSSING_NO_TEST)
    tree({
        "other/a.go": "package other\n\nfunc aHelper() {}\n",
        "other/b.go": "package other\n\nfunc B() { aHelper() }\n",
    })
    r = run(["-test=false", "./..."])
    assert_run_golden(__file__, "two_packages", r, workdir)


def test_build_tags_from_goflags(run, tree, workdir):
    """CATCHES: an analyzer that ignores GOFLAGS=-tags: the crossing lives only in a file behind the gui
    build tag, so it is reported only when that tag is set."""
    tree({
        "go.mod": GO_MOD,
        "p/user.go": "package p\n\nfunc userName() string { return \"u\" }\n\nfunc UserName() string { return userName() }\n",
        "p/gui.go": "//go:build gui\n\npackage p\n\nvar _ = userName\n",
    })
    plain = run(["./..."])
    tagged = run(["./..."], env_overrides={"GOFLAGS": "-p=1 -tags=gui"})
    assert_run_golden(__file__, "tags_plain", plain, workdir)
    assert_run_golden(__file__, "tags_gui", tagged, workdir)


def test_fix_json_reports_and_applies(run, tree, workdir):
    """CATCHES: -fix combined with -json that does not apply the fixes; the files must change exactly as
    with -fix alone."""
    tree(CROSSING)
    run(["-fix", "-json", "./..."])
    assert_golden(__file__, "fixed_user_repository", (workdir / "database/user_repository.go").read_text())


def test_version_flag_ignores_patterns(run, tree, workdir):
    """CATCHES: -V=full that analyzes the patterns given after it instead of printing the version line
    and exiting 0 at once."""
    tree(CROSSING_NO_TEST)
    r = run(["-V=full", "./..."])
    assert r.returncode == 0
    assert r.stderr == b""
    assert normalize(r.stdout).split(" ")[1:4] == ["version", "devel", "comments-go-here"]
    assert normalize(r.stdout, workdir).count("\n") == 1
