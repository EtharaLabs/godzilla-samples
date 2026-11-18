"""declscope shrink: what it reports in internal/ packages, -fix, patterns, packages it does not judge."""

from conftest import GO_MOD, assert_golden, assert_run_golden

USER_GO = """package user

import "fmt"

func Load(id int) string { return Format(id) }

// Format renders an ID for display.
func Format(id int) string { return fmt.Sprint(id) }

type Record struct {
	ID   int
	Name string
}

func Dump(r Record) { fmt.Println(r) }

var Version = "dev"

func Helper() string { return helper() }

func helper() string { return "" }

type Status string

const (
	Active  Status = "active"
	Blocked Status = "blocked"
)

const DefaultStatus Status = Active
"""

API_GO = """package api

import "example.com/app/internal/user"

var _ = user.Load
var _ = user.Dump
var _ = user.Active
"""

EXT_TEST = """package user_test

import (
	"testing"

	"example.com/app/internal/user"
)

func TestHelper(t *testing.T) { _ = user.Helper() }
"""

MODULE = {"go.mod": GO_MOD, "internal/user/user.go": USER_GO, "api/api.go": API_GO,
          "internal/user/user_test.go": EXT_TEST}

CONTROL = {"internal/ctl/ctl.go": "package ctl\n\nfunc Reported() {}\n"}

IGN_GO = """package ign

//declscope:ignore overexported // set by reflection
func Kept() {}

//declscope:ignore overexported
func Used() {}

//declscope:ignore
func Bare() {}
"""


def test_shrink_reports_and_exits_3(run, tree, workdir):
    """CATCHES: a shrink that misses an unused exported function or a lone const, reports a type read
    through reflection or a const set that is used, or omits the reason a fix is withheld for a string
    var (-ldflags -X) and a function only external tests use; it exits 3 when it reports."""
    tree(MODULE)
    r = run(["shrink"])
    assert_run_golden(__file__, "reports", r, workdir)


def test_shrink_dot_dot_dot_same_as_default(run, tree, workdir):
    """CATCHES: a shrink whose default patterns differ from ./..."""
    tree(MODULE)
    r = run(["shrink", "./..."])
    assert_run_golden(__file__, "reports", r, workdir)


def test_shrink_fix_unexports(run, tree, workdir):
    """CATCHES: shrink -fix that does not rename Format and DefaultStatus (and the doc comment opening with
    Format), that renames something whose fix is withheld, or that still prints the fixed findings;
    only reports left without a fix are printed, and they make the exit status 3."""
    tree(MODULE)
    r = run(["shrink", "-fix"])
    assert_run_golden(__file__, "fix_run", r, workdir)
    assert_golden(__file__, "fix_user_go", (workdir / "internal/user/user.go").read_text())


def test_shrink_fix_then_analyzer_is_consistent(run, tree, workdir):
    """CATCHES: a shrink -fix whose result no longer type-checks or that the analyzer then reports;
    the documented order shrink -fix then declscope must leave a clean analyzer run."""
    tree(MODULE)
    run(["shrink", "-fix"])
    r = run(["./..."])
    assert_run_golden(__file__, "analyzer_after_fix", r, workdir)
    assert_golden(__file__, "fix_user_go", (workdir / "internal/user/user.go").read_text())


def test_shrink_pattern_narrows_reports_not_uses(run, tree, workdir):
    """CATCHES: a shrink that only loads the packages its patterns name: ./api names no internal package
    so nothing is reported, while ./internal/user/... reports the same as the whole module because uses
    in api still count."""
    tree(MODULE)
    api = run(["shrink", "./api"])
    user = run(["shrink", "./internal/user/..."])
    assert_run_golden(__file__, "pattern_api", api, workdir)
    assert_run_golden(__file__, "reports", user, workdir)


def test_shrink_not_judged_packages(run, tree, workdir):
    """CATCHES: a shrink that judges a package main (plugin symbols) or a package holding assembly, or that
    skips them without naming each on stderr with its reason; the exit status ignores them."""
    tree({**MODULE,
          "internal/tool/main.go": "package main\n\nfunc Run() {}\n\nfunc main() { Run() }\n",
          "internal/fast/fast.go": "package fast\n\nfunc Add() {}\n",
          "internal/fast/fast_arm64.s": "// asm\n",
          "internal/fast/fast_amd64.s": "// asm\n"})
    r = run(["shrink", "./internal/tool", "./internal/fast"])
    assert_run_golden(__file__, "not_judged", r, workdir)


def test_shrink_testdata_not_loaded(run, tree, workdir):
    """CATCHES: a shrink that judges a testdata package named explicitly; ./... leaves it out, so the run
    names it as not judged and exits 0."""
    tree({**MODULE, "internal/user/testdata/fixture/f.go": "package fixture\n\nfunc Fix() {}\n"})
    r = run(["shrink", "./internal/user/testdata/fixture"])
    assert_run_golden(__file__, "testdata", r, workdir)


def test_shrink_ignore_overexported(run, tree, workdir):
    """CATCHES: an ignore of overexported that does not silence the report, a bare ignore that does (it
    must not reach this rule), or a missing report for an ignore that silenced nothing."""
    tree({"go.mod": GO_MOD, "internal/ign/ign.go": IGN_GO,
          "api/ign.go": 'package api\n\nimport "example.com/app/internal/ign"\n\nvar _ = ign.Used\n'})
    r = run(["shrink"])
    assert_run_golden(__file__, "ignores", r, workdir)


def test_shrink_ignore_unused_silences_unused_ignore(run, tree, workdir):
    """CATCHES: //declscope:ignore unused not answering shrink's report of an unused overexported ignore."""
    tree({"go.mod": GO_MOD, **CONTROL,
          "internal/ign/ign.go": "package ign\n\n//declscope:ignore overexported\n//declscope:ignore unused\nfunc Used() {}\n",
          "api/ign.go": 'package api\n\nimport "example.com/app/internal/ign"\n\nvar _ = ign.Used\n'})
    r = run(["shrink"])
    assert_run_golden(__file__, "ignore_unused", r, workdir)


def test_shrink_file_level_ignore(run, tree, workdir):
    """CATCHES: a file-level //declscope:ignore overexported above the package clause that does not cover
    every declaration of the file."""
    tree({"go.mod": GO_MOD, **CONTROL,
          "internal/ign/ign.go": "//declscope:ignore overexported\n\npackage ign\n\nfunc A() {}\n\nfunc B() {}\n",
          "api/api.go": "package api\n"})
    r = run(["shrink"])
    assert_run_golden(__file__, "file_ignore", r, workdir)


def test_shrink_no_match(run, tree, workdir):
    """CATCHES: a shrink whose only pattern matches nothing that exits 0 silently instead of refusing."""
    tree({**MODULE, "emptydir/x/README": "nothing\n"})
    r = run(["shrink", "./emptydir/..."])
    assert_run_golden(__file__, "no_match", r, workdir)


def test_shrink_partial_match_warns(run, tree, workdir):
    """CATCHES: a shrink that refuses, or stays silent, when one of several patterns matches nothing."""
    tree({**MODULE, "emptydir/x/README": "nothing\n"})
    r = run(["shrink", "./api", "./emptydir/..."])
    assert_run_golden(__file__, "partial_match", r, workdir)


def test_shrink_missing_directory(run, tree, workdir):
    """CATCHES: a shrink that ignores a pattern the go command rejects instead of stopping with exit 1."""
    tree(MODULE)
    r = run(["shrink", "./missing"])
    assert_run_golden(__file__, "missing_dir", r, workdir)


def test_shrink_foreign_import_path(run, tree, workdir):
    """CATCHES: a shrink that accepts an import-path pattern outside the module as matching nothing
    harmlessly; the reference refuses it."""
    tree(MODULE)
    r = run(["shrink", "example.com/other/..."])
    assert_run_golden(__file__, "foreign_pattern", r, workdir)


def test_shrink_outside_a_module(run, tree, workdir):
    """CATCHES: a shrink that reports nothing and exits 0 where no go.mod exists."""
    tree({"p/p.go": "package p\n"})
    r = run(["shrink"])
    assert_run_golden(__file__, "no_module", r, workdir)


def test_shrink_refuses_type_errors(run, tree, workdir):
    """CATCHES: a shrink that runs over a module where a package does not type-check, which would show no
    uses at all; the whole run is refused."""
    tree({**MODULE, "broken/b.go": "package broken\n\nfunc F() int { return \"x\" }\n"})
    r = run(["shrink", "./internal/..."])
    assert_run_golden(__file__, "type_error", r, workdir)


def test_shrink_config_names_baseline(run, tree, workdir):
    """CATCHES: shrink -config that is ignored: the config names a baseline holding Format, so Format is
    no longer reported while the other findings remain."""
    tree({**MODULE, "cfg/shrink.yaml": "baseline: base.yaml\n",
          "cfg/base.yaml": "packages:\n  example.com/app/internal/user:\n    overexported:\n      user:\n        - Format\n"})
    r = run(["shrink", "-config", "cfg/shrink.yaml"])
    assert_run_golden(__file__, "config_baseline", r, workdir)


def test_shrink_config_missing(run, tree, workdir):
    """CATCHES: shrink -config naming a missing file that falls back to discovery."""
    tree(MODULE)
    r = run(["shrink", "-config", "nope.yaml"])
    assert_run_golden(__file__, "config_missing", r, workdir)


def test_shrink_interface_method_and_stringer(run, tree, workdir):
    """CATCHES: a shrink that reports a method satisfying fmt.Stringer, an interface's method names, or a
    struct field with a tag, all of which are documented as never reported."""
    tree({"go.mod": GO_MOD, **CONTROL,
          "internal/user/user.go": (
              "package user\n\ntype ID int\n\nfunc (ID) String() string { return \"\" }\n\n"
              "func New() ID { return 0 }\n\ntype Getter interface {\n\tGet() int\n}\n\n"
              "type Row struct {\n\tName string `json:\"name\"`\n}\n"),
          "api/api.go": ('package api\n\nimport (\n\t"fmt"\n\n\t"example.com/app/internal/user"\n)\n\n'
                         "var _ fmt.Stringer = user.New()\nvar _ user.Getter\nvar _ user.Row\n")})
    r = run(["shrink"])
    assert_run_golden(__file__, "never_reported", r, workdir)


def test_shrink_build_excluded_use_counts(run, tree, workdir):
    """CATCHES: a shrink that only reads files of the current build: a use written in a file behind a
    build tag still counts, and GOFLAGS=-tags brings that file into the build."""
    tree({"go.mod": GO_MOD,
          "internal/a/a.go": "package a\n\ntype Mode struct {\n\tFlag string\n}\n\nfunc Format() {}\n",
          "app/gui.go": '//go:build gui\n\npackage app\n\nimport "example.com/app/internal/a"\n\nvar _ = a.Mode{Flag: "gui"}\nvar _ = a.Format\n',
          "app/app.go": 'package app\n\nimport "example.com/app/internal/a"\n\nvar _ a.Mode\n'})
    plain = run(["shrink"])
    tagged = run(["shrink"], env_overrides={"GOFLAGS": "-p=1 -tags=gui"})
    assert_run_golden(__file__, "excluded_plain", plain, workdir)
    assert_run_golden(__file__, "excluded_tagged", tagged, workdir)


def test_shrink_unexported_name_taken(run, tree, workdir):
    """CATCHES: a shrink fix that renames Format to format although format is already declared."""
    tree({"go.mod": GO_MOD,
          "internal/user/user.go": "package user\n\nfunc Format(id int) string { return format(id) }\n\nfunc format(id int) string { return \"\" }\n",
          "api/api.go": "package api\n"})
    r = run(["shrink", "-fix"])
    assert_run_golden(__file__, "name_taken", r, workdir)
    assert (workdir / "internal/user/user.go").read_text() == (
        "package user\n\nfunc Format(id int) string { return format(id) }\n\nfunc format(id int) string { return \"\" }\n")


def test_shrink_workspace_loads_every_module(run, tree, workdir):
    """CATCHES: a shrink that ignores go.work: a use from another module of the workspace counts, so
    only the declaration nothing uses is reported."""
    tree({"go.work": "go 1.25\n\nuse (\n\t.\n\t./tools\n)\n",
          "go.mod": GO_MOD,
          "internal/user/user.go": "package user\n\nfunc Used() {}\n\nfunc Unused() {}\n",
          "tools/go.mod": "module example.com/app/tools\n\ngo 1.25\n",
          "tools/t.go": 'package tools\n\nimport "example.com/app/internal/user"\n\nvar _ = user.Used\n'})
    r = run(["shrink"])
    assert_run_golden(__file__, "workspace", r, workdir)


def test_shrink_non_internal_package_not_reported(run, tree, workdir):
    """CATCHES: a shrink that reports exported declarations outside internal/, which another module may
    import, or names such packages on stderr."""
    tree({"go.mod": GO_MOD, "pub/pub.go": "package pub\n\nfunc Unused() {}\n",
          "internal/x/x.go": "package x\n\nfunc Unused() {}\n"})
    r = run(["shrink"])
    assert_run_golden(__file__, "public", r, workdir)
