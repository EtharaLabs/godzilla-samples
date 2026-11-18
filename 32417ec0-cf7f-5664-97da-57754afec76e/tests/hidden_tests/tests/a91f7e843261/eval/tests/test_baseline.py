"""declscope baseline: recording the violations a codebase already has, and the analyzer consulting them.

Every test records the baseline run, the files it wrote (compared whole), and the analyzer or shrink run that
must then be quiet, or must report only what is new.
"""

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


QUALIFY_ON = "rules:\n  naming:\n    qualify: ondemand\n"

# helper crosses from user to order, from both the ordinary and the test variant.
TWO_FILES = {
    "user.go": "package x\n\nfunc helper() int { return 1 }\n",
    "order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    "order_test.go": "package x\n\nimport \"testing\"\n\nfunc TestOrder(t *testing.T) { _ = helper() }\n",
}


def at(prefix, files):
    return {f"{prefix}/{name}" if prefix else name: body for name, body in files.items()}


def test_records_and_then_suppresses(ds, workdir):
    """CATCHES: a baseline that is written somewhere else, holds a differently shaped or ordered YAML file,
    counts the two variants' identical keys twice, or does not silence the analyzer afterwards."""
    write_tree(workdir, {"go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON, **TWO_FILES})
    before = ds(["./..."])
    rec = ds(["baseline", "./..."])
    tree = snapshot_tree(workdir)
    after = ds(["./..."])
    assert "\n".join([before.transcript, rec.transcript, tree, after.transcript]) == golden("records_and_suppresses")


def test_default_pattern_is_every_package(ds, workdir):
    """CATCHES: a baseline with no pattern that records only the current directory's package instead of
    every package under it."""
    write_tree(workdir, {"go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON, **TWO_FILES, **at("sub", TWO_FILES)})
    rec = ds(["baseline"])
    after = ds(["./..."])
    assert "\n".join([rec.transcript, snapshot_tree(workdir), after.transcript]) == golden("default_pattern")


def test_per_package_targets(ds, workdir):
    """CATCHES: a baseline that writes every entry into one file instead of the file each package's lookup
    reaches: a config's baseline key, a nearer default-named file, else the working directory."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": QUALIFY_ON,
        "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n" + QUALIFY_ON,
        "deep/.declscope-baseline.yaml": "",
        **TWO_FILES, **at("sub/inner", TWO_FILES), **at("deep/inner", TWO_FILES), **at("plain", TWO_FILES),
    })
    rec = ds(["baseline", "./..."])
    after = ds(["./..."])
    assert "\n".join([rec.transcript, snapshot_tree(workdir), after.transcript]) == golden("per_package_targets")


def test_from_subdirectory_leaves_root_alone(ds, workdir):
    """CATCHES: a baseline run from a subdirectory that rewrites the root baseline (losing the entries of
    packages the run never saw) instead of writing beneath the working directory."""
    write_tree(workdir, {"go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON, **TWO_FILES, **at("store/inner", TWO_FILES)})
    first = ds(["baseline", "./..."])
    second = ds(["baseline", "./..."], cwd=workdir / "store")
    assert "\n".join([first.transcript, second.transcript, snapshot_tree(workdir)]) == golden("from_subdirectory")


def test_refuses_unreachable_default_and_o_overrides(ds, workdir):
    """CATCHES: a baseline that silently writes entries for a workspace module whose lookup never reaches the
    working directory, writes the placeable package's half anyway, or refuses even with -o."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "go.work": "go 1.22\n\nuse (\n\t.\n\t./nested\n)\n",
        "nested/go.mod": "module example.com/nested\n\ngo 1.22\n",
        **TWO_FILES, **at("nested", TWO_FILES),
    })
    refused = ds(["baseline", "./...", "./nested/..."])
    tree = snapshot_tree(workdir)
    forced = ds(["baseline", "-o", "all.yaml", "./...", "./nested/..."])
    written = (workdir / "all.yaml").read_text()
    assert "\n".join([refused.transcript, tree, forced.transcript, written]) == golden("unreachable_default")


def test_refusal_comes_before_shrink(ds, workdir):
    """CATCHES: a baseline that runs shrink's module-wide load before refusing an unplaceable package, so a
    broken package elsewhere hides the refusal."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "go.work": "go 1.22\n\nuse (\n\t.\n\t./nested\n)\n",
        "nested/go.mod": "module example.com/nested\n\ngo 1.22\n",
        **at("nested", TWO_FILES),
        "broken/broken.go": "package broken\n\nvar _ int = \"\"\n",
    })
    out = ds(["baseline", "./nested/..."])
    assert out.transcript == golden("refusal_before_shrink")


def test_corrupt_baseline_is_regenerated(ds, workdir):
    """CATCHES: an analyzer that silently accepts a baseline with an unknown key, or a baseline command that is
    blocked by the corrupt file it is meant to replace, with or without -o."""
    corrupt = "packages:\n  x:\n    boundary:\n      user: [helper]\nbogus: 1\n"
    write_tree(workdir, {"go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON, **TWO_FILES,
                         ".declscope-baseline.yaml": corrupt})
    rejected = ds(["./..."])
    alt = ds(["baseline", "-o", "alt.yaml", "./..."])
    regen = ds(["baseline", "./..."])
    after = ds(["./..."])
    assert "\n".join([rejected.transcript, alt.transcript, regen.transcript, snapshot_tree(workdir),
                      after.transcript]) == golden("corrupt_regenerated")


def test_entry_does_not_survive_a_move(ds, workdir):
    """CATCHES: a baseline keyed by declaration name alone, which keeps suppressing a crossing once the
    declaration moves to a file of another namespace."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": "package x\n\nfunc helper() int { return 1 }\n",
        "csv.go": "package x\n\nfunc csvRun() int { return helper() }\n\nvar _ = csvRun\n",
    })
    rec = ds(["baseline", "./..."])
    quiet = ds(["./..."])
    (workdir / "user.go").unlink()
    write_tree(workdir, {"order.go": "package x\n\nfunc helper() int { return 1 }\n"})
    moved = ds(["./..."])
    assert "\n".join([rec.transcript, quiet.transcript, moved.transcript]) == golden("does_not_survive_move")


def test_records_members_a_type_stood_in_for(ds, workdir):
    """CATCHES: a baseline that records a strict surplus type without the fields its report covered, so the
    fields are reported next run; and one that keeps a field added later quiet."""
    box = "//declscope:shared\n\npackage x\n\ntype boxKind int\n\ntype boxed struct {\n\tn int\n%s}\n\nvar _ = boxed{}\n"
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  surplus: strict\n",
        "order.go": "package x\n\nfunc orderRun(k boxKind) int { return int(k) }\n\nvar _ = orderRun\n",
        "box.go": box % "",
    })
    before = ds(["./..."])
    rec = ds(["baseline", "./..."])
    tree = snapshot_tree(workdir)
    quiet = ds(["./..."])
    write_tree(workdir, {"box.go": box % "\textra int\n"})
    new = ds(["./..."])
    assert "\n".join([before.transcript, rec.transcript, tree, quiet.transcript, new.transcript]) == golden(
        "settled_members")


def test_broken_config_writes_nothing(ds, workdir):
    """CATCHES: a baseline that records under defaults when one package's config is invalid, or writes a file
    for the other packages anyway."""
    write_tree(workdir, {"go.mod": GO_MOD, "a/a.go": "package a\n", "b/b.go": "package b\n",
                         "b/.declscope.yaml": "rules:\n  surplus: bogus\n"})
    out = ds(["baseline", "./..."])
    assert out.transcript + "\n" + snapshot_tree(workdir) == golden("broken_config")


def test_subcommands_refuse_an_unknown_flag(ds, workdir):
    """CATCHES: a subcommand that ignores an unknown flag or reports it without its own usage and exit status
    2."""
    write_tree(workdir, {"go.mod": GO_MOD})
    outs = [ds([sub, "-bogus"]).transcript for sub in ("baseline", "survey", "inspect", "shrink")]
    assert "\n".join(outs) == golden("unknown_flag")


def test_subcommands_report_a_load_failure(ds, workdir):
    """CATCHES: a subcommand that reads a go command failure (an invalid -mod in GOFLAGS) as a module with
    nothing in it instead of stopping with the go command's error."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n"})
    env = {"GOFLAGS": "-mod=bogus"}
    outs = [ds([sub, "./p"], env_overrides=env).transcript for sub in ("baseline", "survey", "inspect")]
    outs.append(ds(["inspect", "./..."], env_overrides=env).transcript)
    assert "\n".join(outs) == golden("load_failure")


def test_nothing_to_record(ds, workdir):
    """CATCHES: a baseline that writes an empty file for a module with no package, or that rewrites the -o file
    when its patterns match nothing."""
    recorded = "packages:\n  example.com/app/p:\n    boundary:\n      p:\n        - helper\n"
    write_tree(workdir, {"go.mod": GO_MOD, "empty/README": "no Go here\n", "keep.yaml": recorded})
    every = ds(["baseline", "./..."])
    keep = ds(["baseline", "-o", "keep.yaml", "./empty/..."])
    assert "\n".join([every.transcript, keep.transcript, snapshot_tree(workdir)]) == golden("nothing_to_record")


def test_unmatched_pattern_warns(ds, workdir):
    """CATCHES: a subcommand that refuses a pattern naming nothing when another names a package (it must warn
    and go on), or that only warns when nothing at all is matched (it must refuse)."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n", "empty/README": "no Go here\n"})
    outs = []
    for args in (["baseline", "-o", "b.yaml"], ["survey"], ["inspect"]):
        outs.append(ds([*args, "./empty/...", "./p"]).transcript)
        outs.append(ds([*args, "./empty/..."]).transcript)
    assert "\n".join(outs) == golden("unmatched_pattern")


def test_file_it_cannot_write(ds, workdir):
    """CATCHES: a baseline that exits 0 when the -o file cannot be created because its directory is a file."""
    write_tree(workdir, {"go.mod": GO_MOD, **at("p", TWO_FILES), "blocker": ""})
    out = ds(["baseline", "-o", "blocker/b.yaml", "./..."])
    assert out.transcript == golden("cannot_write")


def test_package_that_does_not_compile(ds, workdir):
    """CATCHES: a baseline that records the findings of the packages that compile and drops a broken one's,
    instead of refusing the whole run."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc broken() int { return \"x\" }\n"})
    out = ds(["baseline", "./..."])
    assert out.transcript + "\n" + snapshot_tree(workdir) == golden("does_not_compile")


def test_ignored_finding_not_recorded(ds, workdir):
    """CATCHES: a baseline that records a crossing an ignore directive already answers."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/user.go": "package p\n\n//declscope:ignore boundary\nfunc helper() int { return 1 }\n",
        "p/order.go": "package p\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    })
    out = ds(["baseline", "./..."])
    assert out.transcript + "\n" + snapshot_tree(workdir) == golden("ignored_not_recorded")


SHRINK_PACKAGE = {
    "user.go": "package x\n\nfunc helper() int { return 1 }\n",
    "order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    "core.go": "//declscope:core\n\npackage x\n\nfunc CoreThing() {}\n",
    "charge.go": "//declscope:namespace billing\n\npackage x\n\nfunc ChargeBilling() {}\n",
    "box.go": "package x\n\ntype Box struct{ Field int }\n\nfunc NewBox() Box { return Box{} }\n",
}


def test_records_shrink_with_the_analyzer(ds, workdir):
    """CATCHES: a baseline that leaves out shrink's overexported entries, spells their namespaces differently
    from the analyzer ((core), a declared namespace, a member under its owner), or leaves either tool
    reporting afterwards."""
    write_tree(workdir, {
        "go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON, **at("internal/app", SHRINK_PACKAGE),
        "cmd/use/main.go": "package main\n\nimport x \"example.com/app/internal/app\"\n\nfunc main() { _ = x.NewBox() }\n",
    })
    shrink_before = ds(["shrink"])
    rec = ds(["baseline", "./..."])
    tree = snapshot_tree(workdir)
    analyzer = ds(["./..."])
    shrink_after = ds(["shrink"])
    assert "\n".join([shrink_before.transcript, rec.transcript, tree, analyzer.transcript,
                      shrink_after.transcript]) == golden("records_shrink")


def test_shrink_false_skips_overexported(ds, workdir):
    """CATCHES: a baseline -shrink=false that still loads the module for shrink and records overexported
    entries, so shrink stays quiet when it should report."""
    write_tree(workdir, {
        "go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON, **at("internal/app", SHRINK_PACKAGE),
        "cmd/use/main.go": "package main\n\nimport x \"example.com/app/internal/app\"\n\nfunc main() { _ = x.NewBox() }\n",
    })
    rec = ds(["baseline", "-shrink=false", "./..."])
    tree = snapshot_tree(workdir)
    shrink_after = ds(["shrink"])
    assert "\n".join([rec.transcript, tree, shrink_after.transcript]) == golden("shrink_false")


def test_places_shrink_entries_per_package(ds, workdir):
    """CATCHES: a baseline that writes every overexported entry into the root file instead of the file each
    package's lookup reaches, and a -o that does not gather them all into one."""
    lonely = "package inner\n\nfunc Lonely() {}\n"
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n",
        "deep/.declscope-baseline.yaml": "",
        "internal/top/lonely.go": lonely,
        "sub/internal/inner/lonely.go": lonely,
        "deep/internal/inner/lonely.go": lonely,
    })
    rec = ds(["baseline", "./..."])
    tree = snapshot_tree(workdir)
    quiet = ds(["shrink"])
    one = ds(["baseline", "-o", "one.yaml", "./..."])
    written = (workdir / "one.yaml").read_text()
    assert "\n".join([rec.transcript, tree, quiet.transcript, one.transcript, written]) == golden(
        "shrink_per_package")


EXT_TEST = {
    "ext_user_test.go": "package x_test\n\nfunc extHelper() int { return 1 }\n",
    "ext_order_test.go": "package x_test\n\nimport \"testing\"\n\nfunc TestExt(t *testing.T) { _ = extHelper() }\n",
}


def merge_module(workdir):
    write_tree(workdir, {
        "go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON,
        **at("a", TWO_FILES), **at("internal/b", TWO_FILES), **at("a", EXT_TEST),
        "internal/b/lonely.go": "package x\n\nfunc Lonely() {}\n",
    })


def test_narrow_pattern_without_merge_drops_others(ds, workdir):
    """CATCHES: a baseline that keeps the entries of packages a narrower pattern did not load, when only -merge
    should keep them, so the analyzer stays quiet about them."""
    merge_module(workdir)
    full = ds(["baseline", "./..."])
    narrow = ds(["baseline", "./a"])
    written = (workdir / ".declscope-baseline.yaml").read_text()
    after = ds(["./..."])
    assert "\n".join([full.transcript, narrow.transcript, written, after.transcript]) == golden("narrow_without_merge")


def test_merge_keeps_unloaded_packages(ds, workdir):
    """CATCHES: a -merge that drops the entries of packages it did not load, drops shrink's entries under
    -shrink=false, treats the external test package as unloaded, or keeps an entry whose violation was
    fixed."""
    merge_module(workdir)
    outs = [ds(["baseline", "./..."]).transcript, (workdir / ".declscope-baseline.yaml").read_text()]
    for args in (["-merge", "./a"], ["-merge", "./internal/b"], ["-merge", "-shrink=false", "./internal/b"]):
        outs.append(ds(["baseline", *args]).transcript)
        outs.append((workdir / ".declscope-baseline.yaml").read_text())
    (workdir / "a" / "ext_order_test.go").unlink()
    outs.append(ds(["baseline", "-merge", "./a"]).transcript)
    outs.append((workdir / ".declscope-baseline.yaml").read_text())
    outs.append(ds(["./..."]).transcript)
    outs.append(ds(["shrink"]).transcript)
    assert "\n".join(outs) == golden("merge_keeps_unloaded")


def test_merge_refuses_an_unparsable_file(ds, workdir):
    """CATCHES: a -merge that replaces a file it cannot parse, or writes the other target before refusing,
    instead of stopping with the parse error and leaving every file as it was."""
    corrupt = "packages:\n  x:\n    boundary:\n      user: [helper]\nbogus: 1\n"
    write_tree(workdir, {
        "go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON,
        "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n" + QUALIFY_ON,
        **at("a", TWO_FILES), **at("sub/inner", TWO_FILES),
        ".declscope-baseline.yaml": corrupt,
    })
    refused = ds(["baseline", "-merge", "./..."])
    tree = snapshot_tree(workdir)
    replaced = ds(["baseline", "./..."])
    assert "\n".join([refused.transcript, tree, replaced.transcript, snapshot_tree(workdir)]) == golden(
        "merge_unparsable")


def test_merge_cannot_read_a_directory(ds, workdir):
    """CATCHES: a -merge that advises running without -merge when the target cannot be read at all, here
    because it is a directory."""
    merge_module(workdir)
    (workdir / "dir.yaml").mkdir()
    out = ds(["baseline", "-merge", "-o", "dir.yaml", "./..."])
    assert out.transcript == golden("merge_cannot_read")


def test_merge_with_o(ds, workdir):
    """CATCHES: a -merge with -o that does not read the -o file first, and a -o without -merge that keeps the
    entries of packages it did not load."""
    merge_module(workdir)
    outs = [ds(["baseline", "-o", "one.yaml", "./..."]).transcript, (workdir / "one.yaml").read_text()]
    outs.append(ds(["baseline", "-o", "one.yaml", "-merge", "./a"]).transcript)
    outs.append((workdir / "one.yaml").read_text())
    outs.append(ds(["baseline", "-o", "one.yaml", "./a"]).transcript)
    outs.append((workdir / "one.yaml").read_text())
    assert "\n".join(outs) == golden("merge_with_o")


def test_merge_with_nested_targets(ds, workdir):
    """CATCHES: a -merge that writes a file no loaded package resolves to, or mixes the root's and the nested
    baseline's packages."""
    write_tree(workdir, {
        "go.mod": GO_MOD, ".declscope.yaml": QUALIFY_ON,
        "sub/.declscope.yaml": "baseline: sub-baseline.yaml\n" + QUALIFY_ON,
        **at("a", TWO_FILES), **at("c", TWO_FILES), **at("sub/inner", TWO_FILES), **at("sub/other", TWO_FILES),
    })
    outs = [ds(["baseline", "./..."]).transcript, snapshot_tree(workdir)]
    for patterns in (["./sub/inner"], ["./a"], ["./a", "./sub/other"]):
        outs.append(ds(["baseline", "-merge", *patterns]).transcript)
    outs.append(snapshot_tree(workdir))
    outs.append(ds(["./..."]).transcript)
    assert "\n".join(outs) == golden("merge_nested_targets")


def test_counts_packages_outside_the_module(ds, workdir):
    """CATCHES: a baseline that does not count the standard-library package a pattern named as not judged
    by shrink."""
    write_tree(workdir, {"go.mod": GO_MOD, "internal/a/a.go": "package a\n\nfunc Lonely() {}\n"})
    out = ds(["baseline", "-o", "one.yaml", "errors", "./..."])
    assert out.transcript + "\n" + (workdir / "one.yaml").read_text() == golden("packages_outside")


def test_baseline_key_of_a_method_names_its_receiver(ds, workdir):
    """CATCHES: a baseline that keys a method by its bare name, so recording orderA.help also absorbs a new
    orderB.help in the same namespace."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
        "order.go": "package x\n\ntype orderA struct{}\n\nfunc (orderA) help() int { return 1 }\n",
        "user.go": "package x\n\nfunc (orderA) userHelp() int { return 2 }\n",
    })
    rec = ds(["baseline", "./..."])
    written = (workdir / ".declscope-baseline.yaml").read_text()
    write_tree(workdir, {"order.go": "package x\n\ntype orderA struct{}\n\nfunc (orderA) help() int { return 1 }\n\n"
                                     "type orderB struct{}\n\nfunc (b orderB) helper() int { return 1 }\n"})
    after = ds(["./..."])
    assert "\n".join([rec.transcript, written, after.transcript]) == golden("method_key")
