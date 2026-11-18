"""declscope baseline: where entries go, what they record, -o, -merge, -shrink and its refusals."""

from conftest import GO_MOD, assert_golden, assert_run_golden, normalize

USER_GO = """package app

type user struct {
	//declscope:private
	name string
}

//declscope:shared
func Helper() {}

//declscope:ignore boundary
func greet(u user) string { return u.name }

func load() int { return 1 }

//declscope:shared
func userShared() {}

var _ = greet
var _ = userShared
"""

ORDER_GO = "package app\n\nfunc orderTotal() int { return load() }\n\nvar _ = orderTotal\n"

SHRINK_USER = """package user

import "fmt"

func Load(id int) string { return Format(id) }

// Format renders an ID for display.
func Format(id int) string { return fmt.Sprint(id) }
"""

API_GO = 'package api\n\nimport "example.com/app/internal/user"\n\nvar _ = user.Load\n'

# What a full `declscope baseline` records for MODULE, written by hand so a test can start from it.
RECORDED = """packages:
  example.com/app/app:
    boundary:
      user:
        - load
    surplus:
      user:
        - userShared
  example.com/app/internal/user:
    overexported:
      user:
        - Format
"""

MODULE = {
    "go.mod": GO_MOD,
    "app/user.go": USER_GO,
    "app/order.go": ORDER_GO,
    "internal/user/user.go": SHRINK_USER,
    "api/api.go": API_GO,
}

STATEMENT_GO = """//declscope:core

package b

type Statement struct {
	Table  string
	wheres []string
}

func open() {}
"""

QUERY_GO = """package b

func (s *Statement) Where(cond string) *Statement {
	s.wheres = append(s.wheres, cond)
	open()
	return s
}

func (s *Statement) helper() {}
"""

OTHER_GO = "package b\n\nfunc other(s *Statement) { s.helper() }\n\nvar _ = other\n"

A_GO = "package a\n\nfunc aHelper() {}\n"
B_GO = "package a\n\nfunc bUse() { aHelper() }\n\nvar _ = bUse\n"


def test_baseline_default_target_and_content(run, tree, workdir):
    """CATCHES: a baseline that is written somewhere other than ./.declscope-baseline.yaml, lacks the
    generated header, misses shrink's overexported entries, or prints a wrong violation count."""
    tree(MODULE)
    r = run(["baseline"])
    assert_run_golden(__file__, "default_run", r, workdir)
    assert_golden(__file__, "default_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_suppresses_recorded_violations(run, tree, workdir):
    """CATCHES: an analyzer that does not consult the discovered baseline: after recording, the boundary
    and surplus reports disappear, and only the unused-directive reports (never baselined) remain."""
    tree(MODULE)
    run(["baseline", "-shrink=false"])
    r = run(["./..."])
    assert_run_golden(__file__, "after_baseline_analyzer", r, workdir)


def test_baseline_suppresses_shrink(run, tree, workdir):
    """CATCHES: shrink that ignores the baseline: an overexported entry recorded by baseline makes the
    next shrink run exit 0 with no report."""
    tree(MODULE)
    before = run(["shrink"])
    tree({".declscope-baseline.yaml": "packages:\n  example.com/app/internal/user:\n    overexported:\n      user:\n        - Format\n"})
    r = run(["shrink"])
    assert_run_golden(__file__, "before_baseline_shrink", before, workdir)
    assert_run_golden(__file__, "after_baseline_shrink", r, workdir)


def test_baseline_shrink_false(run, tree, workdir):
    """CATCHES: -shrink=false that still records overexported entries, or that drops the analyzer's."""
    tree(MODULE)
    r = run(["baseline", "-shrink=false"])
    assert_run_golden(__file__, "shrink_false_run", r, workdir)
    assert_golden(__file__, "shrink_false_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_o_writes_one_file(run, tree, workdir):
    """CATCHES: -o that is ignored, that does not create missing parent directories, or that reports the
    path differently from how it was given."""
    tree(MODULE)
    r = run(["baseline", "-shrink=false", "-o", "out/b.yaml", "./app"])
    assert_run_golden(__file__, "o_run", r, workdir)
    assert_golden(__file__, "o_file", (workdir / "out/b.yaml").read_text())
    assert not (workdir / ".declscope-baseline.yaml").exists()


def test_baseline_with_nothing_to_record(run, tree, workdir):
    """CATCHES: a baseline run that writes nothing, or writes 'packages: null', for a clean module; the
    reference still writes the header and an empty packages map and reports 0 violations."""
    tree({"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc helper() {}\n\nvar _ = helper\n"})
    r = run(["baseline"])
    assert_run_golden(__file__, "nothing_run", r, workdir)
    assert_golden(__file__, "nothing_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_pattern_matching_nothing_refuses(run, tree, workdir):
    """CATCHES: a baseline run that writes an empty file when its only pattern matches no package; the
    reference stops with exit 1 and writes nothing."""
    tree({**MODULE, "emptydir/sub/README": "no go here\n"})
    r = run(["baseline", "./emptydir/..."])
    assert_run_golden(__file__, "no_match", r, workdir)
    assert sorted(p.name for p in workdir.iterdir()) == ["api", "app", "emptydir", "go.mod", "internal"]


def test_baseline_unmatched_pattern_beside_others_warns(run, tree, workdir):
    """CATCHES: an unmatched pattern beside matching ones that stops the run or is not warned about."""
    tree({**MODULE, "emptydir/sub/README": "no go here\n"})
    r = run(["baseline", "-shrink=false", "./app", "./emptydir/..."])
    assert_run_golden(__file__, "partial_match", r, workdir)


def test_baseline_missing_directory_pattern(run, tree, workdir):
    """CATCHES: a pattern naming a missing directory that is skipped silently; the go command's error is
    printed and the run fails with 'packages contain errors'."""
    tree(MODULE)
    r = run(["baseline", "./nothing/..."])
    assert_run_golden(__file__, "missing_dir", r, workdir)


def test_baseline_narrow_pattern_drops_other_packages(run, tree, workdir):
    """CATCHES: a regeneration that merges by default; without -merge a narrower pattern rewrites the file
    wholesale and drops every package it did not load."""
    tree(MODULE)
    run(["baseline", "-shrink=false"])
    r = run(["baseline", "-shrink=false", "./api"])
    assert_run_golden(__file__, "narrow_run", r, workdir)
    assert_golden(__file__, "narrow_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_merge_keeps_other_packages(run, tree, workdir):
    """CATCHES: -merge that drops entries of packages this run did not load, or (under -shrink=false)
    drops shrink's overexported entries that the run did not regenerate."""
    tree({**MODULE, ".declscope-baseline.yaml": RECORDED})
    r = run(["baseline", "-merge", "-shrink=false", "./api"])
    assert_run_golden(__file__, "merge_run", r, workdir)
    assert_golden(__file__, "default_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_merge_regenerates_loaded_package(run, tree, workdir):
    """CATCHES: -merge that keeps stale entries for a package it did load; fixing the crossing in app and
    re-running with -merge ./app must remove app's boundary entry and keep the rest."""
    tree({**MODULE, ".declscope-baseline.yaml": RECORDED})
    tree({"app/order.go": "package app\n\nfunc orderTotal() int { return 2 }\n\nvar _ = orderTotal\n"})
    r = run(["baseline", "-merge", "./app"])
    assert_run_golden(__file__, "merge_regen_run", r, workdir)
    assert_golden(__file__, "merge_regen_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_merge_refuses_unparsable_file(run, tree, workdir):
    """CATCHES: -merge that replaces a baseline it cannot parse; it must stop with exit 1, explain to run
    without -merge, and leave the file untouched."""
    tree({**MODULE, ".declscope-baseline.yaml": "packages: [\n"})
    r = run(["baseline", "-merge", "./app"])
    assert_run_golden(__file__, "merge_corrupt", r, workdir)
    assert (workdir / ".declscope-baseline.yaml").read_text() == "packages: [\n"


def test_baseline_replaces_unparsable_file_without_merge(run, tree, workdir):
    """CATCHES: a regeneration that refuses because the old file does not parse; without -merge the old
    file is never read and is replaced."""
    tree({**MODULE, ".declscope-baseline.yaml": "packages: [\n"})
    r = run(["baseline", "-shrink=false", "./app"])
    assert_run_golden(__file__, "replace_corrupt_run", r, workdir)
    assert_golden(__file__, "replace_corrupt_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_merge_unreadable_target(run, tree, workdir):
    """CATCHES: -merge with a target that cannot be read (a directory) being reported as a parse error or
    ignored; the reference says it cannot be read and exits 1."""
    tree({**MODULE, "dirout/keep": "x\n"})
    r = run(["baseline", "-merge", "-o", "dirout", "-shrink=false", "./app"])
    assert_run_golden(__file__, "merge_unreadable", r, workdir)


def test_baseline_unwritable_target(run, tree, workdir):
    """CATCHES: a write failure that is ignored or reported with exit 0."""
    tree({**MODULE, "dirout/keep": "x\n"})
    r = run(["baseline", "-o", "dirout", "-shrink=false", "./app"])
    assert_run_golden(__file__, "unwritable", r, workdir)


def test_analyzer_refuses_unparsable_baseline(run, tree, workdir):
    """CATCHES: an analyzer that ignores a corrupt baseline and reports everything; it must fail with the
    parse error and the advice to regenerate."""
    tree({**MODULE, ".declscope-baseline.yaml": "packages: [\n"})
    r = run(["-test=false", "./app"])
    assert_run_golden(__file__, "analyzer_corrupt", r, workdir)


def test_survey_refuses_unparsable_baseline(run, tree, workdir):
    """CATCHES: survey that measures with a baseline it could not read instead of failing."""
    tree({**MODULE, ".declscope-baseline.yaml": "packages: [\n"})
    r = run(["survey", "./app"])
    assert_run_golden(__file__, "survey_corrupt", r, workdir)


def test_shrink_refuses_unparsable_baseline(run, tree, workdir):
    """CATCHES: shrink that ignores a corrupt baseline instead of failing with its parse error."""
    tree({**MODULE, ".declscope-baseline.yaml": "packages: [\n"})
    r = run(["shrink"])
    assert_run_golden(__file__, "shrink_corrupt", r, workdir)


def test_baseline_spells_members_methods_and_core(run, tree, workdir):
    """CATCHES: wrong baseline keys: a member is Type.member under its type's namespace, a method is
    Type.method under its own file's namespace, and the core namespace is spelled (core)."""
    tree({"go.mod": GO_MOD, "b/statement.go": STATEMENT_GO, "b/query.go": QUERY_GO, "b/other.go": OTHER_GO})
    r = run(["baseline", "-shrink=false"])
    assert_run_golden(__file__, "spellings_run", r, workdir)
    assert_golden(__file__, "spellings_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_per_package_targets(run, tree, workdir):
    """CATCHES: a baseline that gathers every entry into one file; a package beside an existing
    default-named baseline, and one whose config names its own, each get their entries there."""
    tree({
        "go.mod": GO_MOD,
        "a/a.go": A_GO, "a/b.go": B_GO, "a/.declscope-baseline.yaml": "",
        "c/a.go": A_GO.replace("package a", "package c"), "c/b.go": B_GO.replace("package a", "package c"),
        "c/.declscope.yaml": "baseline: custom-baseline.yaml\n",
        "b/statement.go": STATEMENT_GO, "b/query.go": QUERY_GO, "b/other.go": OTHER_GO,
    })
    r = run(["baseline", "-shrink=false"])
    assert_run_golden(__file__, "targets_run", r, workdir)
    assert_golden(__file__, "targets_a", (workdir / "a/.declscope-baseline.yaml").read_text())
    assert_golden(__file__, "targets_c", (workdir / "c/custom-baseline.yaml").read_text())


def test_configured_baseline_is_consulted(run, tree, workdir):
    """CATCHES: an analyzer that only looks for the default-named baseline and ignores the baseline key
    of the config file, which is resolved relative to that config file."""
    tree({
        "go.mod": GO_MOD,
        "c/a.go": A_GO.replace("package a", "package c"), "c/b.go": B_GO.replace("package a", "package c"),
        "c/.declscope.yaml": "baseline: custom-baseline.yaml\n",
    })
    before = run(["./..."])
    run(["baseline", "-shrink=false"])
    after = run(["./..."])
    assert_run_golden(__file__, "configured_before", before, workdir)
    assert_run_golden(__file__, "configured_after", after, workdir)


def test_yml_baseline_is_discovered(run, tree, workdir):
    """CATCHES: a lookup that only knows .declscope-baseline.yaml; the .yml spelling is consulted too."""
    tree({"go.mod": GO_MOD, "a/a.go": A_GO, "a/b.go": B_GO,
          "a/.declscope-baseline.yml.off": "packages:\n  example.com/app/a:\n    boundary:\n      a:\n        - aHelper\n"})
    before = run(["./..."])
    (workdir / "a/.declscope-baseline.yml.off").rename(workdir / ".declscope-baseline.yml")
    r = run(["./..."])
    assert_run_golden(__file__, "wrong_namespace", before, workdir)
    assert_run_golden(__file__, "yml_discovered", r, workdir)


def test_hand_written_baseline_matches_by_namespace(run, tree, workdir):
    """CATCHES: a baseline match that ignores the namespace: an entry recorded under namespace b does not
    suppress the crossing of aHelper, which belongs to namespace a."""
    tree({"go.mod": GO_MOD, "a/a.go": A_GO, "a/b.go": B_GO,
          ".declscope-baseline.yaml": "packages:\n  example.com/app/a:\n    boundary:\n      b:\n        - aHelper\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "wrong_namespace", r, workdir)


def test_baseline_does_not_survive_a_move(run, tree, workdir):
    """CATCHES: a key that ignores the namespace: moving aHelper into c.go puts it in namespace c, so the
    recorded entry no longer applies and the crossing is reported again."""
    tree({"go.mod": GO_MOD, "a/a.go": A_GO, "a/b.go": B_GO})
    run(["baseline", "-shrink=false"])
    (workdir / "a/a.go").unlink()
    tree({"a/c.go": "package a\n\nfunc aHelper() {}\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "after_move", r, workdir)


def test_baseline_refuses_unreachable_default(run, tree, workdir):
    """CATCHES: a baseline written in the working directory for a package whose lookup never reaches it;
    the reference refuses, names the package and its directory, and suggests -o."""
    tree({"go.mod": GO_MOD, "a/a.go": A_GO, "a/b.go": B_GO,
          "b/statement.go": STATEMENT_GO, "b/query.go": QUERY_GO, "b/other.go": OTHER_GO})
    r = run(["baseline", "-shrink=false", "../b"], cwd=workdir / "a")
    assert_run_golden(__file__, "unreachable", r, workdir)
    assert not (workdir / "a/.declscope-baseline.yaml").exists()


def test_baseline_unreachable_is_allowed_with_o(run, tree, workdir):
    """CATCHES: an -o run that still refuses a package whose default lookup misses the working directory."""
    tree({"go.mod": GO_MOD, "b/statement.go": STATEMENT_GO, "b/query.go": QUERY_GO, "b/other.go": OTHER_GO,
          "a/a.go": A_GO})
    r = run(["baseline", "-shrink=false", "-o", "here.yaml", "../b"], cwd=workdir / "a")
    assert_run_golden(__file__, "unreachable_o_run", r, workdir)
    assert_golden(__file__, "spellings_file", (workdir / "a/here.yaml").read_text())


def test_baseline_refuses_type_errors(run, tree, workdir):
    """CATCHES: a baseline that records a package that does not type-check as clean."""
    tree({"go.mod": GO_MOD, "broken/b.go": "package broken\n\nfunc f() int { return \"x\" }\n"})
    r = run(["baseline"])
    assert_run_golden(__file__, "type_error", r, workdir)
    assert not (workdir / ".declscope-baseline.yaml").exists()


def test_baseline_refuses_broken_config(run, tree, workdir):
    """CATCHES: a baseline run that ignores an invalid config and records under defaults."""
    tree({**MODULE, ".declscope.yaml": "rules:\n  bogus: 1\n"})
    r = run(["baseline"])
    assert_run_golden(__file__, "broken_config", r, workdir)


def test_baseline_explicit_config_rules(run, tree, workdir):
    """CATCHES: a baseline that records under the default rules when -config turns boundary off; only the
    surplus entry remains."""
    tree({**MODULE, "cfg.yaml": "rules:\n  boundary: off\n"})
    r = run(["baseline", "-shrink=false", "-config", "cfg.yaml", "./app"])
    assert_run_golden(__file__, "explicit_config_run", r, workdir)
    assert_golden(__file__, "explicit_config_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_leaves_out_what_an_ignore_answers(run, tree, workdir):
    """CATCHES: a baseline that records a crossing an ignore directive already silences."""
    tree({"go.mod": GO_MOD, "a/b.go": B_GO,
          "a/a.go": "package a\n\n//declscope:ignore boundary\nfunc aHelper() {}\n"})
    r = run(["baseline", "-shrink=false"])
    assert_run_golden(__file__, "ignored_run", r, workdir)
    assert_golden(__file__, "nothing_file", (workdir / ".declscope-baseline.yaml").read_text())


def test_baseline_merge_with_o(run, tree, workdir):
    """CATCHES: -merge -o that does not read the -o file first and so loses the other package's entries."""
    tree({"go.mod": GO_MOD, "a/a.go": A_GO, "a/b.go": B_GO,
          "b/statement.go": STATEMENT_GO, "b/query.go": QUERY_GO, "b/other.go": OTHER_GO})
    run(["baseline", "-shrink=false", "-o", "all.yaml"])
    r = run(["baseline", "-shrink=false", "-merge", "-o", "all.yaml", "./a"])
    assert_run_golden(__file__, "merge_o_run", r, workdir)
    assert_golden(__file__, "merge_o_file", normalize((workdir / "all.yaml").read_text(), workdir))


def test_baseline_shrink_not_judged_is_named(run, tree, workdir):
    """CATCHES: a baseline that silently skips internal packages shrink cannot judge; a package main
    under internal/ is named on stderr with the reason."""
    tree({**MODULE, "internal/tool/main.go": "package main\n\nfunc Run() {}\n\nfunc main() { Run() }\n"})
    r = run(["baseline"])
    assert_run_golden(__file__, "not_judged", r, workdir)
