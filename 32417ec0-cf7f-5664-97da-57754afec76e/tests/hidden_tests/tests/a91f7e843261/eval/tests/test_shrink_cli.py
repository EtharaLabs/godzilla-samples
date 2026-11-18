"""declscope shrink from the command line: patterns, workspaces, refusals, -fix, and the baseline handshake."""

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


# One declaration nothing outside its package uses, one another package uses, and one whose fix is withheld
# because its unexported spelling is taken.
SHRINK_MODULE = {
    "go.mod": GO_MOD,
    "internal/a/a.go": "package a\n\nfunc Lonely() int { return 1 }\n\nfunc Used() int { return Lonely() + Taken() }\n\n"
                       "func Taken() int { return taken() }\n\nfunc taken() int { return 0 }\n",
    "b/b.go": "package b\n\nimport \"example.com/app/internal/a\"\n\nvar _ = a.Used()\n",
}


def test_reports_and_fix(ds, workdir):
    """CATCHES: a shrink that reports a declaration another package uses, words a report or its withheld fix
    differently, exits other than 3, or whose -fix misses an identifier, prints a report it fixed, or renames
    the declaration whose fix is withheld."""
    write_tree(workdir, SHRINK_MODULE)
    report = ds(["shrink"])
    fix = ds(["shrink", "-fix"])
    tree = snapshot_tree(workdir)
    after = ds(["shrink"])
    analyzer = ds(["./..."])
    assert "\n".join([report.transcript, fix.transcript, tree, after.transcript, analyzer.transcript]) == golden(
        "reports_and_fix")


def test_patterns_choose_what_is_reported(ds, workdir):
    """CATCHES: a shrink that loads only the packages its patterns name, so a.Used looks unused when only
    internal/a is named, or that reports internal/a when only b is named."""
    write_tree(workdir, SHRINK_MODULE)
    from_b = ds(["shrink", "."], cwd=workdir / "b")
    from_a = ds(["shrink", "."], cwd=workdir / "internal" / "a")
    named = ds(["shrink", "./internal/..."])
    assert "\n".join([from_b.transcript, from_a.transcript, named.transcript]) == golden("patterns")


def test_refuses_type_errors(ds, workdir):
    """CATCHES: a shrink that judges a module where a package does not type-check, or names that package by the
    go command's build output instead of its type error on one line."""
    write_tree(workdir, {**SHRINK_MODULE, "c/c.go": "package c\n\nvar _ int = \"x\"\n"})
    out = ds(["shrink"])
    assert out.transcript == golden("type_errors")


def test_refuses_outside_a_module(ds, workdir):
    """CATCHES: a shrink that runs outside any module, with or without a standard-library pattern, instead of
    refusing."""
    plain = ds(["shrink"])
    fmt = ds(["shrink", "fmt"])
    assert plain.transcript + "\n" + fmt.transcript == golden("outside_a_module")


def test_usage(ds, workdir):
    """CATCHES: a shrink -h that prints a different usage text, flags or exit status."""
    out = ds(["shrink", "-h"])
    assert out.transcript == golden("usage")


def test_workspace_loaded_as_one(ds, workdir):
    """CATCHES: a shrink that leaves internal/a unjudged for a nested module the workspace already loads, or
    does not judge every module of the workspace its patterns name."""
    write_tree(workdir, {
        "go.mod": "module example.com/root\n\ngo 1.22\n",
        "internal/a/a.go": "package a\n\nfunc Used() {}\n\nfunc Unused() {}\n",
        "tool/go.mod": "module example.com/root/tool\n\ngo 1.22\n\nrequire example.com/root v0.0.0\n",
        "tool/main.go": "package main\n\nimport \"example.com/root/internal/a\"\n\nfunc main() { a.Used() }\n",
        "other/go.mod": "module example.com/other\n\ngo 1.22\n",
        "other/internal/o/o.go": "package o\n\nfunc Lone() {}\n",
    })
    without = ds(["shrink"])
    write_tree(workdir, {"go.work": "go 1.22\n\nuse (\n\t.\n\t./tool\n\t./other\n)\n"})
    within = ds(["shrink", "./...", "./other/..."])
    assert without.transcript + "\n" + within.transcript == golden("workspace")


def test_pattern_errors(ds, workdir):
    """CATCHES: a shrink that silently passes a pattern the go command rejects (a missing directory, a nested
    module's directory) instead of stopping with the go command's message."""
    write_tree(workdir, {**SHRINK_MODULE, "sub/go.mod": "module example.com/sub\n\ngo 1.22\n", "sub/s.go": "package s\n"})
    missing = ds(["shrink", "./nope/..."])
    nested = ds(["shrink", "./sub/..."])
    assert missing.transcript + "\n" + nested.transcript == golden("pattern_errors")


def test_unmatched_patterns(ds, workdir):
    """CATCHES: a shrink that refuses when one of several patterns matches nothing, or that only warns when no
    pattern matches anything."""
    write_tree(workdir, {**SHRINK_MODULE, "empty/README": "no Go here\n"})
    some = ds(["shrink", "./empty/...", "./internal/..."])
    none = ds(["shrink", "./empty/..."])
    assert some.transcript + "\n" + none.transcript == golden("unmatched")


def test_names_what_it_does_not_load(ds, workdir):
    """CATCHES: a shrink that judges a testdata package ./... never loads, though none of its uses were read."""
    write_tree(workdir, {**SHRINK_MODULE, "internal/a/testdata/fixture/f.go": "package fixture\n\nfunc Lone() {}\n"})
    out = ds(["shrink", "./internal/a/testdata/fixture"])
    assert out.transcript == golden("not_loaded")


def test_counts_packages_outside(ds, workdir):
    """CATCHES: a shrink that drops or lists standard-library packages its patterns name instead of counting
    them on one not-judged line."""
    write_tree(workdir, SHRINK_MODULE)
    out = ds(["shrink", "fmt", "errors", "./..."])
    assert out.transcript == golden("outside_main_module")


def test_module_under_internal(ds, workdir):
    """CATCHES: a shrink that judges a module whose own path runs through internal/, where the tree allowed to
    import it lies above the module."""
    write_tree(workdir, {"go.mod": "module example.com/x/internal/y\n\ngo 1.22\n", "y.go": "package y\n\nfunc Unused() {}\n"})
    out = ds(["shrink"])
    assert out.transcript == golden("module_under_internal")


def test_skips_what_go_skips(ds, workdir):
    """CATCHES: a shrink that counts names written in build-excluded files under testdata, dot, underscore,
    vendor or go.mod-ignored directories as uses, or that refuses an unparsable file in an ignored directory;
    while a build-excluded file elsewhere still counts."""
    excluded = "//go:build never\n\npackage x\n\nimport \"example.com/app/internal/a\"\n\nvar _ = a.Lonely\n"
    files = {**SHRINK_MODULE, "go.mod": GO_MOD + "\nignore (\n\t./gen\n\tstatic\n)\n"}
    for d in ("internal/a/testdata", "internal/a/.hidden", "internal/a/_skipped", "vendor/example.com/v",
              "internal/a/vendor/w", "gen", "web/static"):
        files[f"{d}/x.go"] = excluded
    files["gen/broken.go"] = "package gen\n\nthis is not Go\n"
    files["internal/gen/x.go"] = ("//go:build never\n\npackage gen\n\nimport \"example.com/app/internal/a\"\n\n"
                                  "var _ = a.Taken\n")
    write_tree(workdir, files)
    out = ds(["shrink"])
    assert out.transcript == golden("skips_what_go_skips")


def test_refuses_unreadable_excluded_file(ds, workdir):
    """CATCHES: a shrink that ignores a build-excluded file it cannot parse, though that file may name anything,
    and a baseline that writes anything when its shrink half fails."""
    write_tree(workdir, {**SHRINK_MODULE, "b/b_never.go": "//go:build never\n\npackage b\n\nfunc {\n"})
    shrink = ds(["shrink"])
    baseline = ds(["baseline", "./..."])
    tree = snapshot_tree(workdir)
    analyzer_only = ds(["baseline", "-shrink=false", "./..."])
    assert "\n".join([shrink.transcript, baseline.transcript, tree, analyzer_only.transcript]) == golden(
        "unreadable_excluded")


def test_refuses_nested_module_without_path(ds, workdir):
    """CATCHES: a shrink that ignores a nested go.mod naming no module, though whether it may import an internal
    package depends on that path."""
    write_tree(workdir, {**SHRINK_MODULE, "tools/go.mod": "go 1.22\n"})
    out = ds(["shrink"])
    assert out.transcript == golden("nested_without_path")


def test_names_skipped_packages(ds, workdir):
    """CATCHES: a shrink that judges internal/a although a nested module importing it does not type-check, or
    names the skip without the type error on one line, or exits non-zero for it."""
    write_tree(workdir, {
        **SHRINK_MODULE,
        "tools/go.mod": "module example.com/app/tools\n\ngo 1.22\n\nrequire example.com/app v0.0.0\n\n"
                        "replace example.com/app => ../\n",
        "tools/t.go": "package tools\n\nimport \"example.com/app/internal/a\"\n\nvar _ string = a.Used()\n",
    })
    out = ds(["shrink"])
    assert out.transcript == golden("skipped_packages")


def test_skips_git_and_accepts_missing_examples(ds, workdir):
    """CATCHES: a shrink that walks into .git for excluded files, or refuses an example function naming
    nothing."""
    write_tree(workdir, {**SHRINK_MODULE, ".git/x.go": "package x\n\nfunc {\n",
                         "internal/a/a_test.go": "package a\n\nfunc ExampleMissing() {}\n"})
    out = ds(["shrink"])
    assert out.transcript == golden("git_and_examples")


def test_refuses_empty_module(ds, workdir):
    """CATCHES: a shrink that answers for a module with no package, with ./... or with a standard-library
    pattern, instead of refusing."""
    write_tree(workdir, {"go.mod": GO_MOD})
    every = ds(["shrink"])
    fmt = ds(["shrink", "fmt"])
    assert every.transcript + "\n" + fmt.transcript == golden("empty_module")


def test_baseline_handshake(ds, workdir):
    """CATCHES: a baseline that does not record shrink's reports (members under their owner), records an unused
    ignore, or a shrink that reports what the baseline holds, renames a baselined declaration under -fix, or
    misses a new one; and a -shrink=false that still records overexported entries."""
    write_tree(workdir, {
        **SHRINK_MODULE,
        "internal/a/box.go": "package a\n\ntype Box struct{ Field int }\n\nfunc NewBox() Box { return Box{} }\n",
        "b/box.go": "package b\n\nimport \"example.com/app/internal/a\"\n\nvar _ = a.NewBox()\n",
        "internal/a/idle.go": "package a\n\n//declscope:ignore overexported // nothing to silence\nfunc idle() {}\n",
    })
    outs = [ds(["baseline", "./..."]).transcript, (workdir / ".declscope-baseline.yaml").read_text(),
            ds(["shrink"]).transcript]
    (workdir / "internal" / "a" / "idle.go").unlink()
    outs.append(ds(["shrink", "-fix"]).transcript)
    outs.append((workdir / "internal" / "a" / "a.go").read_text())
    write_tree(workdir, {"internal/a/fresh.go": "package a\n\nfunc Fresh() {}\n"})
    outs.append(ds(["shrink"]).transcript)
    outs.append(ds(["baseline", "-shrink=false", "./..."]).transcript)
    outs.append((workdir / ".declscope-baseline.yaml").read_text())
    assert "\n".join(outs) == golden("baseline_handshake")


def test_baselined_declaration_keeps_what_it_carries(ds, workdir):
    """CATCHES: a shrink that offers to unexport a type a baselined exported function returns."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/a/a.go": "package a\n\nfunc Make() Box { return Box{} }\n\ntype Box struct{}\n",
        ".declscope-baseline.yaml": "packages:\n  example.com/app/internal/a:\n    overexported:\n      a:\n        - Make\n",
    })
    out = ds(["shrink"])
    assert out.transcript == golden("baselined_carries")


def test_ignore_consulted_before_baseline(ds, workdir):
    """CATCHES: a shrink that consults the baseline before the ignore, and so reports an ignore over a
    baselined declaration as unused; while a declaration neither covers is still reported."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/a/a.go": "package a\n\n//declscope:ignore overexported // kept for a plugin\nfunc Kept() {}\n\n"
                           "func Other() {}\n",
        ".declscope-baseline.yaml": "packages:\n  example.com/app/internal/a:\n    overexported:\n      a:\n        - Kept\n",
    })
    out = ds(["shrink"])
    assert out.transcript == golden("ignore_before_baseline")


def test_baseline_named_by_config(ds, workdir):
    """CATCHES: a shrink that does not consult the baseline a -config file names, consults it without -config,
    or accepts a config file that does not parse."""
    write_tree(workdir, {**SHRINK_MODULE, "ci.yaml": "baseline: recorded.yaml\n", "bad.yaml": "rules: [\n"})
    outs = [ds(["baseline", "-config", "ci.yaml", "./..."]).transcript, (workdir / "recorded.yaml").read_text(),
            ds(["shrink", "-config", "ci.yaml"]).transcript, ds(["shrink"]).transcript,
            ds(["shrink", "-config", "bad.yaml"]).transcript]
    assert "\n".join(outs) == golden("baseline_by_config")


def test_fix_renames_doc_comment_and_uses(ds, workdir):
    """CATCHES: a shrink -fix that leaves the doc comment opening with the old name, misses a use in a test file
    or a method value, or unexports a type without its uses in signatures."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/user/user.go": "package user\n\nimport \"fmt\"\n\nfunc Load(id int) string { return Format(id) }\n\n"
                                 "// Format renders an ID for display.\nfunc Format(id int) string { return fmt.Sprint(id) }\n\n"
                                 "// Record is one row.\ntype Record struct {\n\tID   int\n\tName string\n}\n\n"
                                 "// Counter counts.\ntype Counter struct{ n int }\n\n"
                                 "// Bump adds one.\nfunc (c *Counter) Bump() { c.n++ }\n\n"
                                 "func NewCounter() *Counter { c := &Counter{}; f := c.Bump; f(); return c }\n\n"
                                 "func Dump(r Record) { fmt.Println(r) }\n",
        "internal/user/user_test.go": "package user\n\nimport \"testing\"\n\n"
                                      "func TestFormat(t *testing.T) {\n\tif Format(1) != \"1\" {\n\t\tt.Fatal(Format(1))\n\t}\n}\n",
        "api/api.go": "package api\n\nimport \"example.com/app/internal/user\"\n\n"
                      "func Run() string { user.Dump(user.Record{}); _ = user.NewCounter(); return user.Load(1) }\n",
    })
    report = ds(["shrink"])
    fix = ds(["shrink", "-fix"])
    tree = snapshot_tree(workdir / "internal")
    after = ds(["shrink"])
    assert "\n".join([report.transcript, fix.transcript, tree, after.transcript]) == golden("fix_doc_and_uses")


def test_const_block_judged_as_one_set(ds, workdir):
    """CATCHES: a shrink that judges each constant of a typed const block alone instead of as one set with its
    type, or judges a constant outside the block as part of it."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/user/user.go": "package user\n\ntype Status string\n\nconst (\n\tActive  Status = \"active\"\n"
                                 "\tBlocked Status = \"blocked\"\n)\n\nconst DefaultStatus Status = Active\n\n"
                                 "type Level int\n\nconst (\n\tLow Level = iota\n\tHigh\n)\n",
        "api/api.go": "package api\n\nimport \"example.com/app/internal/user\"\n\nvar _ = user.Active\n",
    })
    report = ds(["shrink"])
    fix = ds(["shrink", "-fix"])
    tree = snapshot_tree(workdir / "internal")
    assert "\n".join([report.transcript, fix.transcript, tree]) == golden("const_sets")


def test_withheld_fix_reasons(ds, workdir):
    """CATCHES: a shrink that offers a fix where a use cannot be ruled out, or words the reason differently:
    an external test, an -ldflags -X string variable, a name already taken, a generated file naming it, a
    type a reflection call reads, a struct tag."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/w/w.go": "package w\n\nvar Version = \"dev\"\n\nvar Count = 3\n\nfunc Format(id int) string { return format(id) }\n\n"
                           "func format(id int) string { return \"\" }\n\nfunc Shown() int { return 1 }\n\n"
                           "type Tagged struct {\n\tName string `json:\"name\"`\n}\n\nfunc MakeTagged() Tagged { return Tagged{} }\n",
        "internal/w/zz_gen.go": "// Code generated by a tool. DO NOT EDIT.\n\npackage w\n\nvar GenUse = Count\n",
        "internal/w/w_test.go": "package w_test\n\nimport (\n\t\"testing\"\n\n\t\"example.com/app/internal/w\"\n)\n\n"
                                "func TestShown(t *testing.T) { _ = w.Shown() }\n",
        "cmd/c/main.go": "package main\n\nimport \"example.com/app/internal/w\"\n\nfunc main() { _ = w.MakeTagged() }\n",
    })
    report = ds(["shrink"])
    fix = ds(["shrink", "-fix"])
    after = ds(["shrink"])
    assert "\n".join([report.transcript, fix.transcript, snapshot_tree(workdir / "internal"), after.transcript]) == \
        golden("withheld_reasons")


def test_ignore_placements(ds, workdir):
    """CATCHES: a shrink whose //declscope:ignore overexported does not bind on a declaration, a field or the
    package clause, that lets a bare ignore reach overexported, or that does not report an ignore that silenced
    nothing (and its //declscope:ignore unused answer)."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/i/i.go": "package i\n\n//declscope:ignore overexported // a plugin looks it up\nfunc Plugin() {}\n\n"
                           "//declscope:ignore\nfunc Bare() {}\n\ntype Mode struct {\n\t//declscope:ignore overexported\n"
                           "\tFlag string\n\tOther int\n}\n\nfunc NewMode() Mode { return Mode{} }\n\n"
                           "//declscope:ignore overexported\nfunc used() {}\n\n//declscope:ignore overexported\n"
                           "//declscope:ignore unused\nfunc quiet() {}\n",
        "internal/j/j.go": "//declscope:ignore overexported\n\npackage j\n\nfunc One() {}\n\nfunc Two() {}\n",
        "cmd/c/main.go": "package main\n\nimport \"example.com/app/internal/i\"\n\nfunc main() { _ = i.NewMode() }\n",
    })
    out = ds(["shrink"])
    assert out.transcript == golden("ignore_placements")
