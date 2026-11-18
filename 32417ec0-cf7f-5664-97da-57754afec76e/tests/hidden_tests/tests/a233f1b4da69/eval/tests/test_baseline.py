"""declscope baseline: where it writes each package's entries, what it records (the analyzer's and shrink's),
-o, -merge and -shrink=false, and the runs it refuses."""

from conftest import assert_golden, gomod, snapshot, changes, transcript, write_files

QUALIFY_ON = "rules:\n  naming:\n    qualify: ondemand\n"

# The comment every baseline file opens with.
BASELINE_HEADER = """# declscope baseline
#
# Violations recorded here are suppressed; new ones are still reported.
# Regenerate with:
#
#     declscope baseline ./...
#
# Do not edit by hand. An entry disappears when its violation is fixed, so the
# diff of a regeneration is the record of what was cleaned up.
"""

# helper crosses from order.go into user.go, and under QUALIFY_ON does not carry its namespace either.
TWO_FILES = {
    "user.go": "package x\n\nfunc helper() int { return 1 }\n",
    "order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
}


def tree(*pkgs, extra=None):
    files = {"go.mod": gomod("example.com/m"), ".declscope.yaml": QUALIFY_ON}
    for pkg in pkgs:
        for name, body in TWO_FILES.items():
            files[f"{pkg}/{name}" if pkg else name] = body
    files.update(extra or {})
    return files


def steps(run, workdir, *argvs, cwd=None):
    """Run each argv in turn; the transcript of each, and then every file the runs changed."""
    before = snapshot(workdir)
    parts = []
    for argv in argvs:
        parts.append(f"=== declscope {' '.join(argv)}\n" + transcript(run(argv, cwd=cwd), workdir))
    return "\n".join(parts) + "\n=== files\n" + changes(before, workdir)


def test_help(run, workdir):
    """CATCHES: a baseline -h that does not describe the lookup, -merge and -shrink, lists other flags, or exits
    non-zero."""
    assert_golden(transcript(run(["baseline", "-h"]), workdir), __file__, "help")


def test_unknown_flag(run, workdir):
    """CATCHES: a baseline that accepts an unknown flag, or answers it with another status than 2 and its usage."""
    assert_golden(transcript(run(["baseline", "-bogus"]), workdir), __file__, "unknown_flag")


def test_default_pattern_records_and_suppresses(run, workdir):
    """CATCHES: a baseline that does not default to ./..., miscounts the entries it writes, writes another file
    layout (header comment, packages, rule, namespace, declaration), or whose entries the analyzer does not then
    suppress."""
    write_files(workdir, tree("", "sub"))
    assert_golden(steps(run, workdir, ["baseline"], ["./..."]), __file__, "default_pattern")


def test_per_package_targets(run, workdir):
    """CATCHES: a baseline that writes every entry to one file instead of the file each package's lookup finds:
    a config naming its own baseline, an existing default-named file nearer the package, or the working directory."""
    write_files(workdir, tree("", "sub/inner", "deep/inner", "plain", extra={
        "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n" + QUALIFY_ON,
        "deep/.declscope-baseline.yaml": "",
    }))
    assert_golden(steps(run, workdir, ["baseline", "./..."], ["./..."]), __file__, "per_package")


def test_run_from_a_subdirectory_leaves_the_root_baseline(run, workdir):
    """CATCHES: the data-loss case: a run from a subdirectory that rewrites the root baseline, dropping entries of
    packages it never loaded, instead of writing its own file there."""
    write_files(workdir, tree("", "store/inner"))
    run(["baseline", "./..."])
    assert_golden(steps(run, workdir, ["baseline", "./..."], cwd=workdir / "store"), __file__, "subdirectory")


def test_refuses_a_package_whose_lookup_never_reaches_the_working_directory(run, workdir):
    """CATCHES: a baseline that silently writes entries no lookup would find (a workspace module with its own
    go.mod), or writes the placeable packages' file anyway; -o takes over placement and records both."""
    write_files(workdir, tree("", "nested", extra={
        "go.work": "go 1.25\n\nuse (\n\t.\n\t./nested\n)\n",
        "nested/go.mod": gomod("example.com/nested"),
    }))
    out = steps(run, workdir, ["baseline", "./...", "./nested/..."], ["baseline", "-o", "all.yaml", "./...", "./nested/..."])
    assert_golden(out, __file__, "unreachable")


def test_corrupt_baseline_is_regenerated(run, workdir):
    """CATCHES: an analyzer that silently accepts a corrupt baseline, or a baseline run blocked by the corrupt file it
    is asked to regenerate."""
    write_files(workdir, tree("", extra={
        ".declscope-baseline.yaml": "packages:\n  x:\n    boundary:\n      user: [helper]\nbogus: 1\n",
    }))
    assert_golden(steps(run, workdir, ["./..."], ["baseline", "./..."], ["./..."]), __file__, "corrupt")


def test_ignore_answered_finding_is_not_recorded(run, workdir):
    """CATCHES: a baseline that records a finding an ignore directive already silences, which would outlive the
    directive."""
    write_files(workdir, {
        "go.mod": gomod("example.com/m"),
        "p/user.go": "package p\n\n//declscope:ignore boundary\nfunc helper() int { return 1 }\n",
        "p/order.go": "package p\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    })
    assert_golden(steps(run, workdir, ["baseline", "./..."]), __file__, "ignored")


SHRINK_PACKAGE = {
    "internal/app/user.go": "package x\n\nfunc helper() int { return 1 }\n",
    "internal/app/order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    "internal/app/core.go": "//declscope:core\n\npackage x\n\nfunc CoreThing() {}\n",
    "internal/app/charge.go": "//declscope:namespace billing\n\npackage x\n\nfunc ChargeBilling() {}\n",
    "internal/app/box.go": "package x\n\ntype Box struct{ Field int }\n\nfunc NewBox() Box { return Box{} }\n",
    "internal/app/stale.go": "package x\n\n//declscope:ignore overexported\nfunc Stale() {}\n\nvar _ = Stale\n",
    "cmd/use/main.go": 'package main\n\nimport x "example.com/m/internal/app"\n\nfunc main() { _ = x.NewBox(); x.Stale() }\n',
}


def test_records_shrink_beside_the_analyzer(run, workdir):
    """CATCHES: a baseline that leaves out what shrink reports, spells its namespaces differently from the analyzer
    ((core), a declared namespace, a member under its owner), records shrink's unused-ignore report, or after which
    the analyzer or shrink still report."""
    write_files(workdir, {"go.mod": gomod("example.com/m"), ".declscope.yaml": QUALIFY_ON, **SHRINK_PACKAGE})
    assert_golden(steps(run, workdir, ["baseline", "./..."], ["./..."], ["shrink"]), __file__, "with_shrink")


def test_shrink_false_records_the_analyzer_alone(run, workdir):
    """CATCHES: a -shrink=false that still records shrink's reports (or loads the module for them)."""
    write_files(workdir, {"go.mod": gomod("example.com/m"), ".declscope.yaml": QUALIFY_ON, **SHRINK_PACKAGE})
    assert_golden(steps(run, workdir, ["baseline", "-shrink=false", "./..."]), __file__, "shrink_false")


def test_shrink_entries_are_placed_per_package(run, workdir):
    """CATCHES: shrink's entries gathered into one file instead of the baseline each declaring package resolves
    to, or -o that does not gather them all."""
    files = {"go.mod": gomod("example.com/m"), "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n",
             "deep/.declscope-baseline.yaml": ""}
    for d in ("internal/top", "sub/internal/inner", "deep/internal/inner"):
        files[f"{d}/lonely.go"] = "package inner\n\nfunc Lonely() {}\n"
    write_files(workdir, files)
    assert_golden(steps(run, workdir, ["baseline", "./..."], ["shrink"], ["baseline", "-o", "one.yaml", "./..."]),
                  __file__, "shrink_per_package")


def test_shrink_skips_and_outside_packages_are_named(run, workdir):
    """CATCHES: a baseline that does not say on stderr which internal packages shrink left unjudged, or how many
    named packages lie outside the main module."""
    write_files(workdir, {
        "go.mod": gomod("example.com/m"),
        "internal/a/a.go": "package a\n\nfunc Lonely() {}\n",
        "internal/tool/main.go": "package main\n\nfunc Plugged() {}\n\nfunc main() {}\n",
    })
    assert_golden(steps(run, workdir, ["baseline", "-o", "one.yaml", "unsafe", "./..."]), __file__, "shrink_skipped")


def test_shrink_failure_fails_the_baseline(run, workdir):
    """CATCHES: a baseline that writes the analyzer's entries when shrink's module-wide load fails, or that does not
    point at -shrink=false."""
    write_files(workdir, tree("", extra={"tools/go.mod": "go 1.25\n"}))
    assert_golden(steps(run, workdir, ["baseline", "./..."]), __file__, "shrink_failure")


MERGE = {
    "go.mod": gomod("example.com/m"),
    ".declscope.yaml": QUALIFY_ON,
    "a/user.go": TWO_FILES["user.go"],
    "a/order.go": TWO_FILES["order.go"],
    "internal/b/user.go": TWO_FILES["user.go"],
    "internal/b/order.go": TWO_FILES["order.go"],
    "internal/b/lonely.go": "package x\n\nfunc Lonely() {}\n",
}


def test_narrow_pattern_without_merge_drops_other_packages(run, workdir):
    """CATCHES: a regeneration over a narrower pattern that keeps the entries of packages it did not load (the file
    is regenerated wholesale), after which the analyzer would stay silent about them."""
    write_files(workdir, MERGE)
    run(["baseline", "./..."])
    assert_golden(steps(run, workdir, ["baseline", "./a"], ["./..."]), __file__, "narrow")


def test_merge_keeps_unloaded_packages(run, workdir):
    """CATCHES: a -merge that drops the entries of packages the patterns do not load (the analyzer's and shrink's),
    or one under -shrink=false that drops shrink's entries of the package it loads."""
    write_files(workdir, MERGE)
    run(["baseline", "./..."])
    out = steps(run, workdir, ["baseline", "-merge", "./a"], ["baseline", "-merge", "-shrink=false", "./internal/b"])
    assert_golden(out, __file__, "merge")


def test_merge_drops_a_fixed_entry_of_a_loaded_package(run, workdir):
    """CATCHES: a -merge that keeps every old entry instead of replacing the loaded packages' entries with the
    current violations."""
    write_files(workdir, MERGE)
    run(["baseline", "./..."])
    (workdir / "a/order.go").write_text("package x\n\nfunc orderRun() int { return 1 }\n\nvar _ = orderRun\n")
    assert_golden(steps(run, workdir, ["baseline", "-merge", "./a"]), __file__, "merge_fixed")


def test_merge_refuses_an_unparsable_file(run, workdir):
    """CATCHES: a -merge that replaces a file it cannot parse, or writes the other targets before finding out;
    without -merge the same file is replaced."""
    write_files(workdir, tree("a", "sub/inner", extra={
        "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n" + QUALIFY_ON,
        ".declscope-baseline.yaml": "packages:\n  x:\n    boundary:\n      user: [helper]\nbogus: 1\n",
    }))
    assert_golden(steps(run, workdir, ["baseline", "-merge", "./..."]), __file__, "merge_unparsable")


def test_merge_reports_a_file_it_cannot_read(run, workdir):
    """CATCHES: a -merge target that is a directory reported as unparsable (with advice that cannot work) instead of
    unreadable."""
    write_files(workdir, MERGE)
    (workdir / "dir.yaml").mkdir()
    assert_golden(steps(run, workdir, ["baseline", "-merge", "-o", "dir.yaml", "./..."]), __file__, "merge_unreadable")


def test_merge_with_o(run, workdir):
    """CATCHES: -merge with -o that does not read the file -o names, so a narrower run drops the other packages."""
    write_files(workdir, MERGE)
    run(["baseline", "-o", "one.yaml", "./..."])
    assert_golden(steps(run, workdir, ["baseline", "-o", "one.yaml", "-merge", "./a"]), __file__, "merge_with_o")


def test_merge_keeps_what_shrink_left_unjudged(run, workdir):
    """CATCHES: a -merge that drops the overexported entries of a package shrink did not judge this time (its build
    reads a copy from outside the tree), or does not name the package on stderr."""
    write_files(workdir, {
        "m/go.mod": gomod("example.com/m"),
        "m/internal/a/a.go": "package a\n\nfunc Used() {}\n\nfunc Unused() {}\n",
        "m/cmd/c/main.go": 'package main\n\nimport "example.com/m/internal/a"\n\nfunc main() { a.Used() }\n',
        "m/ext/go.mod": gomod("example.com/m/ext", "require example.com/m v0.0.0\n\nreplace example.com/m => ../\n"),
        "m/ext/e.go": 'package ext\n\nimport "example.com/m/internal/a"\n\nfunc Run() { a.Used() }\n',
    })
    write_files(workdir, {
        # What `baseline ./...` records before the build reads ext from outside the tree.
        "m/.declscope-baseline.yaml": BASELINE_HEADER + "packages:\n  example.com/m/internal/a:\n    overexported:\n"
                                      "      a:\n        - Unused\n",
        "m/go.mod": gomod("example.com/m", "require example.com/m/ext v0.0.0\n\nreplace example.com/m/ext => ../extcopy\n"),
        "extcopy/go.mod": gomod("example.com/m/ext"),
    })
    assert_golden(steps(run, workdir, ["baseline", "-merge", "./..."], ["baseline", "./..."], cwd=workdir / "m"),
                  __file__, "merge_unjudged")


def test_broken_config_writes_nothing(run, workdir):
    """CATCHES: a config error in one package lost among the others' results, or a baseline written anyway."""
    write_files(workdir, {
        "go.mod": gomod("example.com/m"),
        "a/a.go": "package a\n",
        "b/b.go": "package b\n",
        "b/.declscope.yaml": "rules:\n  surplus: bogus\n",
    })
    assert_golden(steps(run, workdir, ["baseline", "./..."]), __file__, "broken_config")


def test_package_that_does_not_compile(run, workdir):
    """CATCHES: a baseline written without the findings of a package that does not type-check."""
    write_files(workdir, {"go.mod": gomod("example.com/m"), "p/p.go": 'package p\n\nfunc broken() int { return "x" }\n'})
    assert_golden(steps(run, workdir, ["baseline", "./..."]), __file__, "type_error")


def test_nothing_to_record(run, workdir):
    """CATCHES: a module with no package answered with an empty baseline, which would read as a clean codebase."""
    write_files(workdir, {"go.mod": gomod("example.com/m")})
    assert_golden(steps(run, workdir, ["baseline", "./..."]), __file__, "nothing")


def test_pattern_matching_nothing_keeps_the_o_file(run, workdir):
    """CATCHES: -o with patterns naming no package that replaces every recorded violation with none."""
    write_files(workdir, {
        "go.mod": gomod("example.com/m"),
        "empty/README": "no Go here\n",
        "keep.yaml": "packages:\n  example.com/m/p:\n    boundary:\n      p:\n        - helper\n",
    })
    assert_golden(steps(run, workdir, ["baseline", "-o", "keep.yaml", "./empty/..."]), __file__, "keeps_o")


def test_unmatched_pattern_beside_another_warns(run, workdir):
    """CATCHES: a pattern matching nothing beside one that matches, treated as fatal or passed over silently."""
    write_files(workdir, {"go.mod": gomod("example.com/m"), "p/p.go": "package p\n", "empty/README": "x\n"})
    assert_golden(steps(run, workdir, ["baseline", "-o", "b.yaml", "./empty/...", "./p"]), __file__, "unmatched")


def test_file_that_cannot_be_written(run, workdir):
    """CATCHES: a baseline whose target cannot be written (its directory is a file) that exits 0."""
    write_files(workdir, {"go.mod": gomod("example.com/m"), "blocker": "", **{f"p/{k}": v for k, v in TWO_FILES.items()}})
    assert_golden(steps(run, workdir, ["baseline", "-o", "blocker/b.yaml", "./..."]), __file__, "unwritable")


def test_entry_does_not_survive_a_move_to_another_namespace(run, workdir):
    """CATCHES: a baseline keyed by something that survives a declaration moving to another namespace (where the
    same use crosses another boundary), instead of package, rule, namespace and declaration."""
    write_files(workdir, tree(""))
    run(["baseline", "./..."])
    (workdir / "user.go").unlink()
    write_files(workdir, {"account.go": "package x\n\nfunc helper() int { return 1 }\n"})
    assert_golden(steps(run, workdir, ["./..."]), __file__, "moved")


def test_strict_surplus_type_recorded_with_its_fields(run, workdir):
    """CATCHES: a baseline that records a strict surplus type without the fields it stood in for (the next run
    would report them), or that suppresses a field added afterwards."""
    box = "//declscope:shared\n\npackage x\n\ntype boxKind int\n\ntype boxed struct {\n\tn int\n%s}\n\nvar _ = boxed{}\n"
    write_files(workdir, {
        "go.mod": gomod("example.com/m"),
        ".declscope.yaml": "rules:\n  surplus: strict\n",
        "order.go": "package x\n\nfunc orderRun(k boxKind) int { return int(k) }\n\nvar _ = orderRun\n",
        "box.go": box % "",
    })
    first = steps(run, workdir, ["./..."], ["baseline", "./..."], ["./..."])
    (workdir / "box.go").write_text(box % "\textra int\n")
    assert_golden(first + "\n" + steps(run, workdir, ["./..."]), __file__, "settled_members")


def test_test_variants_and_external_tests(run, workdir):
    """CATCHES: a baseline that records the ordinary and the test variant's identical findings twice, or drops the
    external test package's own entries."""
    write_files(workdir, tree("", extra={
        "order_test.go": 'package x\n\nimport "testing"\n\nfunc TestOrder(t *testing.T) { _ = helper() }\n',
        "ext_user_test.go": "package x_test\n\nfunc extHelper() int { return 1 }\n",
        "ext_order_test.go": 'package x_test\n\nimport "testing"\n\nfunc TestExt(t *testing.T) { _ = extHelper() }\n',
    }))
    assert_golden(steps(run, workdir, ["baseline", "-shrink=false", "./..."]), __file__, "test_variants")
