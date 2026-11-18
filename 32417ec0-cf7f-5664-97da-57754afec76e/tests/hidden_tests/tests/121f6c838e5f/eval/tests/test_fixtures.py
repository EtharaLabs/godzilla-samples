"""The analyzer's reports and fixes over a broad set of example packages, one module per package.

Each package exercises one rule or behaviour: boundary crossings of declarations and members, the
naming rule and its renames, surplus and unused directives in every mode, malformed directives,
namespaces from file names and directives, the core namespace, ignores, baselines, filters, generics,
embedding, build-excluded files, //line directives and assembly beside Go files.
"""

import pytest

from conftest import assert_golden, assert_run_golden, normalize, write_tree
from fixture_sources import FIX, FIXTURES


def module(name: str) -> dict[str, str]:
    return {"go.mod": f"module {name}\n\ngo 1.25\n", **FIXTURES[name]}


def go_files(workdir) -> str:
    """Every .go file of the module, in path order, with a header line each."""
    parts = []
    for p in sorted(workdir.rglob("*.go")):
        parts.append(f"=== {p.relative_to(workdir)}\n{p.read_text()}")
    return "".join(parts)


# Packages the analyzer finds nothing to report in. Their text output is empty, so they are compared
# through -json, which still prints the (empty) result for every package variant.
CLEAN = ["emptyfile", "generated", "generatedowner", "lineaftercomment", "lineignore", "nsdetached", "nsindoc",
         "singlens", "surplusallowed", "surplusexcluded", "surplusloose", "surplusopaque",
         "surplusstrictdefaults", "surplustests", "testns"]


@pytest.mark.parametrize("name", sorted(set(FIXTURES) - set(CLEAN)))
def test_fixture_report(run, workdir, name):
    """CATCHES: an analyzer whose diagnostics differ from the reference for this example package: a missed
    or extra report, a wrong namespace or scope source in the message, a wrong position, a missing related
    use site, or a different order of reports."""
    write_tree(workdir, module(name))
    r = run(["./..."])
    assert_run_golden(__file__, f"report_{name}", r, workdir)


@pytest.mark.parametrize("name", CLEAN)
def test_fixture_clean_json(run, workdir, name):
    """CATCHES: a false positive in a package where the reference reports nothing: a generated file read, a
    namespace directive misread, a surplus report where a use the analyzer cannot see may exist, or a test
    file not sharing its subject's namespace; -json must print exactly the reference's empty results."""
    write_tree(workdir, module(name))
    r = run(["-json", "./..."])
    assert_run_golden(__file__, f"json_{name}", r, workdir)


@pytest.mark.parametrize("name", FIX)
def test_fixture_fix(run, workdir, name):
    """CATCHES: -fix that writes a different edit from the reference (a directive in the wrong place, a
    rename that misses a use or is offered where it must be withheld, a narrowing or deletion applied
    where the reference withholds it), that touches files it should leave alone, or that leaves behind
    different reports than the reference does on the next run."""
    write_tree(workdir, module(name))
    r = run(["-fix", "./..."])
    after = run(["-test=false", "./..."])
    assert_run_golden(__file__, f"fix_run_{name}", r, workdir)
    assert_golden(__file__, f"fixed_{name}", go_files(workdir))
    assert_run_golden(__file__, f"after_fix_{name}", after, workdir)


@pytest.mark.parametrize("name", ["fixes", "fixqualify", "fixmembers", "fixsurplusstrict", "fixunusedstrict"])
def test_fixture_fix_diff(run, workdir, name):
    """CATCHES: -fix -diff that writes files, or prints a diff that differs from the edits -fix writes."""
    write_tree(workdir, module(name))
    before = go_files(workdir)
    r = run(["-fix", "-diff", "./..."])
    assert_golden(__file__, f"diff_{name}", normalize(r.stdout, workdir))
    assert go_files(workdir) == before
