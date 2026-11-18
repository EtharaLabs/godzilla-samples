"""declscope survey: what was checked and what was found, one row per package, as markdown or JSON."""

from conftest import GO_MOD, read_golden, write_tree


def golden(name):
    return read_golden(__file__, name)


# A package where user.go's helper is reached from order.go and from a test file of a third namespace.
CROSSING = {
    "go.mod": GO_MOD,
    "p/user.go": "package p\n\nfunc userHelper() int { return 1 }\n\nfunc userName() string { return \"u\" }\n",
    "p/order.go": "package p\n\nfunc orderTotal() int { return userHelper() }\n",
    "p/cart_test.go": "package p\n\nimport \"testing\"\n\nfunc TestCart(t *testing.T) { _ = userName() }\n",
}


def test_markdown_default_pattern_is_every_package(ds, workdir):
    """CATCHES: a survey that needs an explicit pattern instead of defaulting to ./..., that counts the test
    variant of a package as a second row, or that renders the checks, findings and package tables with
    different headings, alignment, dashes or padding."""
    write_tree(workdir, CROSSING)
    out = ds(["survey"])
    assert out.transcript == golden("markdown_default_pattern")


def test_json_counts_a_package_once(ds, workdir):
    """CATCHES: a survey whose JSON counts both variants of a package (three crossings instead of two), names
    the keys differently, or orders the totals and package fields differently."""
    write_tree(workdir, CROSSING)
    out = ds(["survey", "-format=json", "./..."])
    assert out.transcript == golden("json_counts_a_package_once")


def test_without_tests_drops_the_test_file_crossing(ds, workdir):
    """CATCHES: a survey that ignores -test=false and still counts the crossing only cart_test.go makes."""
    write_tree(workdir, CROSSING)
    out = ds(["survey", "-test=false", "-format=json", "./..."])
    assert out.transcript == golden("without_tests")


def test_rows_ordered_by_what_is_outstanding(ds, workdir):
    """CATCHES: a survey that orders package rows alphabetically or by load order instead of by how much is
    outstanding, or that names the wrong largest crossing for a package."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "a/one.go": "package a\n\nfunc oneHelper() int { return 1 }\n",
        "a/two.go": "package a\n\nfunc twoRun() int { return oneHelper() }\n",
        "b/user.go": "package b\n\nfunc userA() int { return 1 }\n\nfunc userB() int { return 2 }\n\n"
                     "func userC() int { return 3 }\n",
        "b/order.go": "package b\n\nfunc orderRun() int { return userA() + userB() }\n",
        "b/cart.go": "package b\n\nfunc cartRun() int { return userC() + orderRun() }\n",
        "c/only.go": "package c\n\nfunc Run() int { return 1 }\n",
    })
    out = ds(["survey", "./..."])
    assert out.transcript == golden("rows_ordered")


def test_package_of_test_files_alone_without_tests_warns(ds, workdir):
    """CATCHES: a survey that silently drops a package of test files under -test=false instead of warning on
    stderr, or that warns when tests are measured."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/p.go": "package p\n\nfunc Run() int { return 1 }\n",
        "q/q_test.go": "package q\n\nimport \"testing\"\n\nfunc TestQ(t *testing.T) {}\n",
    })
    without = ds(["survey", "-test=false", "./..."])
    with_tests = ds(["survey", "./..."])
    assert without.transcript + "\n" + with_tests.transcript == golden("test_files_alone")


def test_pattern_matching_nothing_is_refused(ds, workdir):
    """CATCHES: a survey that answers zeros for a directory that does not exist instead of refusing with the
    go command's error and exit status 1."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n"})
    out = ds(["survey", "./nope"])
    assert out.transcript == golden("pattern_matching_nothing")


def test_pattern_matching_nothing_beside_one_that_does_warns(ds, workdir):
    """CATCHES: a survey that refuses, or stays silent, when one pattern of several matches no package; it must
    warn about that one on stderr and measure the rest."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc Run() int { return 1 }\n",
                         "empty/README": "nothing here\n"})
    out = ds(["survey", "-format=json", "./p", "./empty/..."])
    assert out.transcript == golden("pattern_warning")


def test_package_that_does_not_compile_is_refused(ds, workdir):
    """CATCHES: a survey that prints counts for a package that does not type-check, or words the refusal or
    the failing entry differently."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc broken() int { return undefinedThing }\n"})
    out = ds(["survey", "./..."])
    assert out.transcript == golden("does_not_compile")


def test_allow_errors_names_the_failed_package(ds, workdir):
    """CATCHES: a survey -allow-errors that gives a broken package a clean row, omits it from the type check
    count, or does not list it with its first type error under the checks table."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/p.go": "package p\n\nfunc broken() int { return undefinedThing }\n",
        "q/user.go": "package q\n\nfunc userHelper() int { return 1 }\n",
        "q/order.go": "package q\n\nfunc orderRun() int { return userHelper() }\n",
    })
    md = ds(["survey", "-allow-errors", "./..."])
    js = ds(["survey", "-allow-errors", "-format=json", "./..."])
    assert md.transcript + "\n" + js.transcript == golden("allow_errors")


def test_failing_dependency_counts_as_failed(ds, workdir):
    """CATCHES: a survey that measures a package whose import, directly or not, does not compile, or that
    names the package without the dependency that broke it."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "b/b.go": "package b\n\nfunc Broken() int { return undefinedThing }\n",
        "c/c.go": "package c\n\nimport \"example.com/app/b\"\n\nfunc Middle() int { return b.Broken() }\n",
        "a/a.go": "package a\n\nimport \"example.com/app/c\"\n\nfunc Top() int { return c.Middle() }\n",
    })
    one = ds(["survey", "-allow-errors", "-format=json", "./a"])
    every = ds(["survey", "-allow-errors", "-format=json", "./..."])
    refused = ds(["survey", "./a"])
    assert "\n".join([one.transcript, every.transcript, refused.transcript]) == golden("failing_dependency")


def test_unknown_format_is_refused(ds, workdir):
    """CATCHES: a survey that falls back to markdown for an unknown -format instead of refusing and naming the
    formats it accepts."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc Run() int { return 1 }\n"})
    yaml = ds(["survey", "-format=yaml", "./..."])
    toml = ds(["survey", "-format=toml", "./..."])
    assert yaml.transcript + "\n" + toml.transcript == golden("unknown_format")


def test_surplus_stands_down_beside_assembly(ds, workdir):
    """CATCHES: a survey that builds its own pass without the package's non-Go files and so reports surplus as
    asked, where the analyzer stands the rule down for a package holding assembly."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/a.go": "package p\n\n//declscope:shared\nfunc wide() int { return 1 }\n",
        "p/b.go": "package p\n\nfunc local() int { return wide() }\n",
        "p/p.s": "",
    })
    analyzed = ds(["./p"])
    surveyed = ds(["survey", "./p"])
    assert analyzed.transcript + "\n" + surveyed.transcript == golden("surplus_beside_assembly")


def test_checks_in_force_name_config_and_baseline(ds, workdir):
    """CATCHES: a survey whose JSON omits the config chain, the rules it set, or the baseline the analyzer
    would read with its entry count, so a quiet package hides what suppressed it."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  surplus: off\n  unused: strict\n  naming:\n    qualify: always\n",
        ".declscope-baseline.yaml": "packages:\n  example.com/app/p:\n    boundary:\n      user: [userHelper]\n",
        "p/user.go": "package p\n\nfunc userHelper() int { return 1 }\n",
        "p/order.go": "package p\n\nfunc orderTotal() int { return userHelper() }\n",
    })
    out = ds(["survey", "-format=json", "./..."])
    assert out.transcript == golden("checks_in_force_json")


def test_checks_in_force_as_markdown(ds, workdir):
    """CATCHES: a survey markdown that does not show a rule turned off as off, does not name the baseline and
    its entries, or pads the checks table differently when a path is long."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  surplus: off\n  naming:\n    qualify: ondemand\n    exported: true\n",
        ".declscope-baseline.yaml": "packages:\n  example.com/app/p:\n    boundary:\n      user: [userHelper]\n"
                                    "    qualify:\n      order: [total]\n",
        "p/user.go": "package p\n\nfunc userHelper() int { return 1 }\n",
        "p/order.go": "package p\n\nfunc total() int { return userHelper() }\n\nfunc Exported() int { return total() }\n",
    })
    out = ds(["survey"])
    assert out.transcript == golden("checks_in_force_markdown")


def test_unused_off_reads_as_not_asked(ds, workdir):
    """CATCHES: a survey that prints zeros for the unused rule when rules.unused is off, instead of dashes, or
    that stops counting the directive rule, which has no switch."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "ci.yaml": "rules:\n  unused: off\n",
        "p/user.go": "package p\n\n//declscope:ignore boundary\n//declscope:bogus\nfunc userHelper() int { return 1 }\n\n"
                     "var _ = userHelper\n",
    })
    out = ds(["survey", "-config", "ci.yaml"])
    assert out.transcript == golden("unused_off")


def test_explicit_config_replaces_the_chain(ds, workdir):
    """CATCHES: a survey that adds -config to the discovered .declscope.yaml chain instead of replacing it, or
    that reports the discovered file's qualify mode."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "chosen.yaml": "rules:\n  naming:\n    qualify: never\n",
        "p/user.go": "package p\n\nfunc userHelper() int { return 1 }\n",
        "p/order.go": "package p\n\nfunc orderTotal() int { return userHelper() }\n",
    })
    out = ds(["survey", "-config=chosen.yaml", "-format=json", "./..."])
    assert out.transcript == golden("explicit_config")


def test_broken_config_stops_the_run(ds, workdir):
    """CATCHES: a survey that measures under defaults when one package's config has an invalid value, or that
    loses that error among the other packages measured in parallel."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "a/a.go": "package a\n",
        "b/b.go": "package b\n",
        "b/.declscope.yaml": "rules:\n  surplus: bogus\n",
    })
    out = ds(["survey", "./..."])
    assert out.transcript == golden("broken_config")


def test_ignored_findings_counted_under_their_rule(ds, workdir):
    """CATCHES: a survey that does not count a finding an ignore answered as ignored under its own rule, or
    does not show the silenced naming finding as exempt in the package row."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "p/misc.go": "//declscope:ignore unused\n//declscope:ignore directive\n\npackage p\n\n//declscope:private\n"
                     "func init() {}\n\n//declscope:bogus\n//declscope:ignore qualify\nfunc stray() int { return 1 }\n\n"
                     "var _ = stray\n",
    })
    out = ds(["survey", "-format=json", "./..."])
    assert out.transcript == golden("ignored_counted")


def test_baselined_name_counted_as_baselined(ds, workdir):
    """CATCHES: a survey that counts a naming finding the baseline absorbs as reported instead of baselined."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        ".declscope-baseline.yaml": "packages:\n  example.com/app/p:\n    qualify:\n      user: [helper]\n",
        "p/user.go": "package p\n\nfunc helper() int { return 1 }\n\nvar _ = helper\n",
    })
    out = ds(["survey", "-format=json", "./..."])
    assert out.transcript == golden("baselined_name")


def test_real_package_ending_in_dot_test_is_kept(ds, workdir):
    """CATCHES: a survey that mistakes a real package whose path ends in .test for the synthesized test main and
    drops it."""
    write_tree(workdir, {"go.mod": GO_MOD, "cmd.test/main.go": "package main\n\nfunc main() {}\n"})
    out = ds(["survey", "-test=false", "-format=json", "./..."])
    assert out.transcript == golden("dot_test_package")


def test_file_level_shared_counts_unexported_declarations_only(ds, workdir):
    """CATCHES: an inspect that counts an exported name under a file-level //declscope:shared as a decision
    (declared) rather than open, or that loses the crossing of the unexported helper."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/util.go": "//declscope:shared\n\npackage p\n\nfunc utilHelper() int { return 1 }\n\n"
                     "func UtilExported() int { return 2 }\n",
        "p/order.go": "package p\n\nfunc orderTotal() int { return utilHelper() + UtilExported() }\n",
    })
    survey = ds(["survey", "-format=json", "./..."])
    inspect = ds(["inspect", "-format=json", "./p"])
    assert survey.transcript + "\n" + inspect.transcript == golden("file_level_shared")


def test_nested_config_chains_grouped(ds, workdir):
    """CATCHES: a survey that reports one config for the run instead of one row per config chain that applied,
    or that does not list the chain outermost first."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
        "a/a.go": "package a\n\nfunc Run() int { return 1 }\n",
        "b/.declscope.yaml": "rules:\n  surplus: loose\n  unused: loose\n",
        "b/b.go": "package b\n\nfunc Run() int { return 1 }\n",
        "b/c/c.go": "package c\n\nfunc Run() int { return 1 }\n",
    })
    out = ds(["survey", "-format=json", "./..."])
    assert out.transcript == golden("nested_config_chains")


def test_core_and_qualify_columns(ds, workdir):
    """CATCHES: a survey whose qualify table miscounts reported, baselined and exempt names, or names the
    wrong worst namespace, in a package with a core namespace and the naming rule on."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "ci.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
        "p/client.go": "//declscope:core\n\npackage p\n\nfunc open() int { return 1 }\n",
        "p/user.go": "package p\n\nfunc helper() int { return open() }\n\nfunc lookup() int { return helper() }\n\n"
                     "//declscope:ignore qualify\nfunc spare() int { return lookup() }\n",
        "p/order.go": "package p\n\nfunc orderRun() int { return spare() }\n\nfunc total() int { return orderRun() }\n",
    })
    md = ds(["survey", "-config", "ci.yaml"])
    js = ds(["survey", "-config", "ci.yaml", "-format=json"])
    assert md.transcript + "\n" + js.transcript == golden("core_and_qualify")
