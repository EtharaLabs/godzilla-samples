"""declscope inspect: one package's namespaces, crossings and naming, and its refusals."""

import json

from conftest import GO_MOD, assert_golden, assert_run_golden, normalize
from sources import BROKEN, DEPENDS_ON_BROKEN, MODULE, TEST_ONLY

QUALIFY = {".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n"}


def test_inspect_markdown(run, tree, workdir):
    """CATCHES: an inspect report whose namespaces table, Mermaid diagram, crossing table, most-reached
    table or qualify table differs from the reference for a package with a core, member and method
    crossings."""
    tree({**MODULE, **QUALIFY})
    r = run(["inspect", "./b"])
    assert_run_golden(__file__, "b_markdown", r, workdir)


def test_inspect_json(run, tree, workdir):
    """CATCHES: -format=json output that lacks or alters the edges, names, crossings and namespaces
    arrays or the findings with their asked flags."""
    tree({**MODULE, **QUALIFY})
    r = run(["inspect", "-format=json", "./b"])
    assert r.returncode == 0
    assert r.stderr == b""
    json.loads(r.stdout)
    assert_golden(__file__, "b_json", normalize(r.stdout, workdir))


def test_inspect_default_config(run, tree, workdir):
    """CATCHES: an inspect that names a config when none applies, instead of built-in defaults."""
    tree(MODULE)
    r = run(["inspect", "./app"])
    assert_run_golden(__file__, "app_defaults", r, workdir)


def test_inspect_import_path(run, tree, workdir):
    """CATCHES: an inspect that only accepts directory patterns and not an import path."""
    tree(MODULE)
    r = run(["inspect", "example.com/app/app"])
    assert_run_golden(__file__, "app_defaults", r, workdir)


def test_inspect_refuses_many_packages(run, tree, workdir):
    """CATCHES: an inspect that reports the first of several packages or sums them; a wildcard naming
    more than one package is refused with the sorted list."""
    tree(MODULE)
    r = run(["inspect", "./..."])
    assert_run_golden(__file__, "many_wildcard", r, workdir)


def test_inspect_refuses_two_patterns(run, tree, workdir):
    """CATCHES: an inspect that accepts two plain package patterns."""
    tree(MODULE)
    r = run(["inspect", "./app", "./b"])
    assert_run_golden(__file__, "many_two", r, workdir)


def test_inspect_wildcard_matching_one(run, tree, workdir):
    """CATCHES: an inspect that refuses every wildcard; ./b/... names one package and is measured."""
    tree({**MODULE, **QUALIFY})
    r = run(["inspect", "./b/..."])
    assert_run_golden(__file__, "b_markdown", r, workdir)


def test_inspect_refuses_dependency_error(run, tree, workdir):
    """CATCHES: an inspect that measures a package whose dependency does not type-check."""
    tree({**MODULE, "broken/b.go": BROKEN, "dep/d.go": DEPENDS_ON_BROKEN})
    r = run(["inspect", "./dep"])
    assert_run_golden(__file__, "dep_error", r, workdir)


def test_inspect_refuses_type_error(run, tree, workdir):
    """CATCHES: an inspect that reports a package that does not type-check as having no crossings."""
    tree({**MODULE, "broken/b.go": BROKEN})
    r = run(["inspect", "./broken"])
    assert_run_golden(__file__, "type_error", r, workdir)


def test_inspect_test_only_without_tests(run, tree, workdir):
    """CATCHES: an inspect that prints an empty report for a package of test files under -test=false."""
    tree({**MODULE, "testonly/t_test.go": TEST_ONLY})
    r = run(["inspect", "-test=false", "./testonly"])
    assert_run_golden(__file__, "test_only", r, workdir)


def test_inspect_no_match(run, tree, workdir):
    """CATCHES: an inspect that prints nothing and exits 0 when the pattern matches no package."""
    tree({**MODULE, "empty/x/README": "nothing\n"})
    r = run(["inspect", "./empty/..."])
    assert_run_golden(__file__, "no_match", r, workdir)


def test_inspect_unknown_format(run, tree, workdir):
    """CATCHES: inspect accepting -format=yaml."""
    tree(MODULE)
    r = run(["inspect", "-format=yaml", "./app"])
    assert_run_golden(__file__, "unknown_format", r, workdir)


def test_inspect_missing_config(run, tree, workdir):
    """CATCHES: inspect falling back to defaults when -config names a missing file."""
    tree(MODULE)
    r = run(["inspect", "-config", "nope.yaml", "./app"])
    assert_run_golden(__file__, "missing_config", r, workdir)


def test_inspect_explicit_config(run, tree, workdir):
    """CATCHES: inspect that ignores -config, or shows it differently from how it was given."""
    tree({**MODULE, "cfg.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n"})
    r = run(["inspect", "-config", "cfg.yaml", "./app"])
    assert_run_golden(__file__, "explicit_config", r, workdir)


def test_inspect_skips_external_test_package(run, tree, workdir):
    """CATCHES: an inspect that refuses a package because its external foo_test package is loaded too, or
    that reports the external test package instead of the one asked for."""
    tree({**MODULE, "b/b_ext_test.go": "package b_test\n\nimport (\n\t\"testing\"\n\n\t\"example.com/app/b\"\n)\n\nfunc TestB(t *testing.T) { _ = b.Statement{} }\n"})
    r = run(["inspect", "./b"])
    assert_run_golden(__file__, "external_test", r, workdir)


def test_inspect_ignores_errors_in_external_test(run, tree, workdir):
    """CATCHES: an inspect that refuses a package because only its separate external test package fails to
    type-check."""
    tree({**MODULE, "b/b_ext_test.go": "package b_test\n\nfunc broken() int { return \"x\" }\n"})
    r = run(["inspect", "./b"])
    assert_run_golden(__file__, "external_test_error", r, workdir)


def test_inspect_test_false_drops_test_crossing(run, tree, workdir):
    """CATCHES: inspect -test=false still counting a crossing that only a _test.go file makes."""
    tree({**MODULE, "app/user_test.go": "package app\n\nimport \"testing\"\n\nfunc TestU(t *testing.T) { _ = orderTotal() }\n"})
    with_tests = run(["inspect", "./app"])
    without = run(["inspect", "-test=false", "./app"])
    assert_run_golden(__file__, "app_with_tests", with_tests, workdir)
    assert_run_golden(__file__, "app_without_tests", without, workdir)


def test_inspect_baselined_and_declared(run, tree, workdir):
    """CATCHES: an inspect that does not split crossed declarations into reported, baselined and declared:
    after a baseline, and with one crossing settled by //declscope:shared, each lands in its column."""
    tree({"go.mod": GO_MOD,
          "a/a.go": "package a\n\nfunc aHelper() {}\n\n//declscope:shared\nfunc aShared() {}\n\nfunc aLate() {}\n",
          "a/b.go": "package a\n\nfunc bUse() { aHelper(); aShared() }\n\nvar _ = bUse\n"})
    run(["baseline", "-shrink=false"])
    tree({"a/c.go": "package a\n\nfunc cUse() { aLate() }\n\nvar _ = cUse\n"})
    r = run(["inspect", "./a"])
    assert_run_golden(__file__, "baselined_declared", r, workdir)


def test_inspect_mutual_crossing(run, tree, workdir):
    """CATCHES: an inspect that does not mark a pair of namespaces reaching each other as mutual."""
    tree({"go.mod": GO_MOD,
          "a/a.go": "package a\n\nfunc aHelper() {}\n\nfunc aUse() { bHelper() }\n\nvar _ = aUse\n",
          "a/b.go": "package a\n\nfunc bHelper() {}\n\nfunc bUse() { aHelper() }\n\nvar _ = bUse\n"})
    r = run(["inspect", "-format=markdown", "./a"])
    assert_run_golden(__file__, "mutual", r, workdir)


def test_inspect_exit_zero_with_findings(run, tree, workdir):
    """CATCHES: an inspect that exits 3 because the package has findings; it measures and exits 0."""
    tree({"go.mod": GO_MOD, "a/a.go": "package a\n\nfunc aHelper() {}\n",
          "a/b.go": "package a\n\nfunc bUse() { aHelper() }\n\nvar _ = bUse\n"})
    r = run(["inspect", "-format", "json", "./a"])
    assert_run_golden(__file__, "exit_zero_json", r, workdir)
