"""declscope inspect: the shape of one package (namespaces, crossings, reached declarations, naming)."""

from conftest import GO_MOD, read_golden, write_tree


def golden(name):
    return read_golden(__file__, name)


# One package with a core, a mutual pair of namespaces, a declared crossing, a baselined crossing, an exported
# (open) crossing and a test file, under an explicit config so the report names it by the path given.
SHAPE = {
    "go.mod": GO_MOD,
    "ci.yaml": "rules:\n  naming:\n    qualify: ondemand\nbaseline: base.yaml\n",
    "base.yaml": "packages:\n  example.com/app/shop:\n    boundary:\n      cart:\n        - cartTotal\n",
    "shop/client.go": "//declscope:core\n\npackage shop\n\nfunc dial() int { return 1 }\n\nfunc Open() int { return dial() }\n",
    "shop/user.go": "package shop\n\ntype userRecord struct {\n\tname  string\n\temail string\n}\n\n"
                    "func userLoad() userRecord { return userRecord{name: \"n\"} }\n\n"
                    "//declscope:shared\nfunc userFind(id int) userRecord { _ = id; return userLoad() }\n\n"
                    "func userAudit() int { return cartTotal() }\n",
    "shop/order.go": "package shop\n\nfunc orderPlace() string {\n\tu := userFind(1)\n\treturn u.name + u.email\n}\n\n"
                     "func orderCount() int { return dial() + cartTotal() + userAudit() }\n\nvar _ = orderPlace\n\n"
                     "func Exported() int { return Open() }\n",
    "shop/cart.go": "package shop\n\nfunc cartTotal() int { return len(orderPlace()) }\n\nfunc helper() int { return 2 }\n",
    "shop/cart_test.go": "package shop\n\nimport \"testing\"\n\nfunc TestCart(t *testing.T) { _ = orderCount() + helper() }\n",
}


def test_markdown_report(ds, workdir):
    """CATCHES: an inspect whose markdown differs in any section: the namespace table, the Mermaid edges and
    their weights and line styles, the folded crossing table (mutual, declared, baselined, reported, clears,
    reached, uses), the most-reached list or the qualify table."""
    write_tree(workdir, SHAPE)
    out = ds(["inspect", "-config", "ci.yaml", "./shop"])
    assert out.transcript == golden("markdown_report")


def test_json_report(ds, workdir):
    """CATCHES: an inspect whose JSON differs in its findings, namespaces, crossings (with clears), edges or
    names arrays, in key names, in ordering, or in the states it gives each crossing."""
    write_tree(workdir, SHAPE)
    out = ds(["inspect", "-config", "ci.yaml", "-format=json", "./shop"])
    assert out.transcript == golden("json_report")


def test_without_tests(ds, workdir):
    """CATCHES: an inspect that ignores -test=false, still counting the crossings only cart_test.go makes and
    the test file in the core."""
    write_tree(workdir, SHAPE)
    md = ds(["inspect", "-config", "ci.yaml", "-test=false", "./shop"])
    js = ds(["inspect", "-config", "ci.yaml", "-test=false", "-format", "json", "./shop"])
    assert md.transcript + "\n" + js.transcript == golden("without_tests")


def test_discovered_config_named_in_report(ds, workdir):
    """CATCHES: an inspect that does not name the discovered config chain, outermost first, or names only the
    nearest file although both composed the rules that ran."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "p/.declscope.yaml": "rules:\n  surplus: loose\n",
        "p/user.go": "package p\n\nfunc helper() int { return 1 }\n\nvar _ = helper\n",
    })
    md = ds(["inspect", "./p"])
    js = ds(["inspect", "-format=json", "./p"])
    assert md.transcript + "\n" + js.transcript == golden("discovered_config")


def test_external_test_package_not_reported_in_place_of_subject(ds, workdir):
    """CATCHES: an inspect that reports the external test package q_test, which has more files, in place of the
    package q it was asked for."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "q/q.go": "package q\n\nfunc Run() int { return 1 }\n",
        "q/a_test.go": "package q_test\n\nimport \"testing\"\n\nfunc TestA(t *testing.T) {}\n",
        "q/b_test.go": "package q_test\n\nimport \"testing\"\n\nfunc TestB(t *testing.T) {}\n",
    })
    out = ds(["inspect", "./q"])
    assert out.transcript == golden("external_test_not_reported")


def test_refuses_more_than_one_package(ds, workdir):
    """CATCHES: an inspect that measures several packages at once instead of refusing and listing them, for a
    wildcard, the all meta pattern and two plain paths."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "a/a.go": "package a\n\nfunc Run() int { return 1 }\n",
        "b/b.go": "package b\n\nfunc Run() int { return 1 }\n",
    })
    outs = [ds(["inspect", *args]).transcript for args in (["./..."], ["all"], ["./a", "./b"])]
    assert "\n".join(outs) == golden("refuses_many")


def test_refuses_many_before_type_checking(ds, workdir):
    """CATCHES: an inspect that type-checks before counting packages, so the refusal speaks of a broken package
    rather than of the pattern; and one that counts a mistyped directory instead of reporting its error."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "a/a.go": "package a\n\nfunc Run() int { return 1 }\n",
        "broken/broken.go": "package broken\n\nfunc Run() int { return nope }\n",
    })
    many = ds(["inspect", "./..."])
    missing = ds(["inspect", "./a", "./nope"])
    broken = ds(["inspect", "./broken"])
    assert "\n".join([many.transcript, missing.transcript, broken.transcript]) == golden("refuses_before_type_check")


def test_real_package_named_like_an_external_test(ds, workdir):
    """CATCHES: an inspect that discards a real package named q_test by its path suffix, so a two-package
    pattern is answered for one."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "q/q.go": "package q\n\nfunc Run() int { return 1 }\n",
        "q_test/q.go": "package q_test\n\nfunc Run() int { return 1 }\n",
    })
    out = ds(["inspect", "./..."])
    assert out.transcript == golden("real_q_test_package")


def test_errors_in_skipped_external_test_package_ignored(ds, workdir):
    """CATCHES: an inspect that refuses q because q_test, which it never reports, does not type-check."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "q/q.go": "package q\n\nfunc Run() int { return 1 }\n",
        "q/q_test.go": "package q_test\n\nfunc broken() { undefinedThing() }\n",
    })
    out = ds(["inspect", "-format=json", "./q"])
    assert out.transcript == golden("skipped_external_errors")


def test_without_a_package_prints_usage(ds, workdir):
    """CATCHES: an inspect that defaults to ./... or the current directory instead of printing its usage and
    exiting 2."""
    write_tree(workdir, {"go.mod": GO_MOD})
    out = ds(["inspect"])
    assert out.transcript == golden("usage_without_package")


def test_says_nothing_was_read(ds, workdir):
    """CATCHES: an inspect that prints empty tables, which read as a clean package, for a package whose every
    file is generated, instead of saying that no file was read."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/zz_gen.go": "// Code generated by a tool. DO NOT EDIT.\n\npackage p\n\nfunc genHelper() int { return 1 }\n\n"
                       "var _ = genHelper\n",
    })
    md = ds(["inspect", "./p"])
    js = ds(["inspect", "-format=json", "./p"])
    assert md.transcript + "\n" + js.transcript == golden("nothing_read")


def test_refusals(ds, workdir):
    """CATCHES: an inspect that answers anyway for an unknown format, a pattern naming a missing directory, a
    package that does not compile, a module with no package, or a missing -config file."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/p.go": "package p\n\nfunc Run() int { return 1 }\n",
        "broken/broken.go": "package broken\n\nfunc Run() int { return nope }\n",
    })
    outs = [ds(["inspect", *args]).transcript for args in (
        ["-format=toml", "./p"], ["./nope"], ["./broken"], ["-config", "absent.yaml", "./p"])]
    assert "\n".join(outs) == golden("refusals")


def test_pattern_matching_nothing(ds, workdir):
    """CATCHES: an inspect that answers for an empty module instead of refusing a pattern that matched no
    packages."""
    write_tree(workdir, {"go.mod": GO_MOD})
    out = ds(["inspect", "./..."])
    assert out.transcript == golden("matching_nothing")


def test_explicit_config_replaces_the_chain(ds, workdir):
    """CATCHES: an inspect that names or applies the .declscope.yaml beside the package when -config chose
    another file."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "chosen.yaml": "rules:\n  naming:\n    qualify: always\n",
        "p/.declscope.yaml": "rules:\n  naming:\n    qualify: never\n",
        "p/user.go": "package p\n\nfunc helper() int { return 1 }\n\nvar _ = helper\n",
    })
    out = ds(["inspect", "-config=chosen.yaml", "./p"])
    assert out.transcript == golden("explicit_config")


def test_test_files_alone_without_tests(ds, workdir):
    """CATCHES: an inspect that reports zero packages as many, or measures nothing silently, for a directory of
    test files under -test=false."""
    write_tree(workdir, {"go.mod": GO_MOD, "q/q_test.go": "package q\n\nimport \"testing\"\n\nfunc TestQ(t *testing.T) {}\n"})
    without = ds(["inspect", "-test=false", "./q"])
    with_tests = ds(["inspect", "./q"])
    assert without.transcript + "\n" + with_tests.transcript == golden("test_files_alone")


def test_mutual_and_open_crossings(ds, workdir):
    """CATCHES: an inspect that does not mark a mutual pair, counts open (exported) crossings in the table
    instead of the line under it, or computes clears without subtracting declarations a third namespace also
    reaches."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "m/alpha.go": "package m\n\nfunc alphaA() int { return betaB() }\n\nfunc alphaShared() int { return 1 }\n\n"
                      "func AlphaOpen() int { return 2 }\n",
        "m/beta.go": "package m\n\nfunc betaB() int { return alphaA() + alphaShared() + AlphaOpen() }\n",
        "m/gamma.go": "package m\n\nfunc gammaG() int { return alphaShared() + AlphaOpen() }\n\nvar _ = gammaG\n",
    })
    md = ds(["inspect", "./m"])
    js = ds(["inspect", "-format=json", "./m"])
    assert md.transcript + "\n" + js.transcript == golden("mutual_and_open")


def test_qualify_saturation(ds, workdir):
    """CATCHES: an inspect whose qualify section miscounts targets, reported names or saturation per namespace,
    or leaves the core and exempt names in the count."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n",
        "n/client.go": "//declscope:core\n\npackage n\n\nfunc dial() int { return 1 }\n",
        "n/tracing.go": "package n\n\nfunc traceValue() int { return dial() }\n\nfunc tracingStart() int { return 1 }\n\n"
                        "func Export() int { return traceValue() + tracingStart() }\n",
        "n/store.go": "package n\n\nfunc storing() int { return 1 }\n\nfunc load() int { return storing() }\n\n"
                      "//declscope:ignore qualify\nfunc keep() int { return load() }\n\nvar _ = keep\n",
    })
    out = ds(["inspect", "./n"])
    js = ds(["inspect", "-format=json", "./n"])
    assert out.transcript + "\n" + js.transcript == golden("qualify_saturation")
