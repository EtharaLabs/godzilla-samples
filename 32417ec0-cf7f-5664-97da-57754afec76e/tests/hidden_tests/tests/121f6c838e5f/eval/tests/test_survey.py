"""declscope survey: the checks in force, the findings per rule, one row per package, and refusals."""

import json

from conftest import GO_MOD, assert_golden, assert_run_golden, normalize
from sources import BROKEN, DEPENDS_ON_BROKEN, MODULE, TEST_ONLY

QUALIFY = {".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n"}


def test_survey_markdown_defaults(run, tree, workdir):
    """CATCHES: a survey that does not default to ./..., misnames the config as something other than
    built-in defaults, miscounts findings per rule, prints 0 instead of - for a rule that was not asked,
    or orders package rows other than by what is outstanding."""
    tree(MODULE)
    r = run(["survey"])
    assert_run_golden(__file__, "defaults_markdown", r, workdir)


def test_survey_markdown_with_config(run, tree, workdir):
    """CATCHES: a survey whose rules row does not reflect the discovered config (qualify ondemand), or
    whose qualify table does not count reported names and the worst namespace."""
    tree({**MODULE, **QUALIFY})
    r = run(["survey", "./..."])
    assert_run_golden(__file__, "config_markdown", r, workdir)


def test_survey_json(run, tree, workdir):
    """CATCHES: a -format=json survey whose structure or values differ from the reference: the checks,
    the per-rule findings with their asked flag, and the per-package rows."""
    tree({**MODULE, **QUALIFY})
    r = run(["survey", "-format=json"])
    assert r.returncode == 0
    assert r.stderr == b""
    json.loads(r.stdout)
    assert_golden(__file__, "config_json", normalize(r.stdout, workdir))


def test_survey_json_space_separated_flag(run, tree, workdir):
    """CATCHES: a -format flag that only accepts the -format=value spelling and not -format value."""
    tree({**MODULE, **QUALIFY})
    r = run(["survey", "-format", "json", "./..."])
    assert_golden(__file__, "config_json", normalize(r.stdout, workdir))


def test_survey_explicit_markdown(run, tree, workdir):
    """CATCHES: -format=markdown rejected or rendered differently from the default."""
    tree(MODULE)
    r = run(["survey", "-format=markdown"])
    assert_run_golden(__file__, "defaults_markdown", r, workdir)


def test_survey_unknown_format(run, tree, workdir):
    """CATCHES: an unknown -format value silently falling back to markdown; the reference names the
    accepted values and exits 1."""
    tree(MODULE)
    r = run(["survey", "-format=xml"])
    assert_run_golden(__file__, "unknown_format", r, workdir)


def test_survey_test_false(run, tree, workdir):
    """CATCHES: survey -test=false that still reads _test.go files, so a crossing only a test makes is
    still counted."""
    tree({**MODULE, "app/user_test.go": "package app\n\nimport \"testing\"\n\nfunc TestU(t *testing.T) { _ = orderTotal() }\n"})
    with_tests = run(["survey", "./app"])
    without = run(["survey", "-test=false", "./app"])
    assert_run_golden(__file__, "with_tests", with_tests, workdir)
    assert_run_golden(__file__, "without_tests", without, workdir)


def test_survey_refuses_type_errors(run, tree, workdir):
    """CATCHES: a survey that reports zero findings for a package that does not type-check; it refuses,
    names the failed package and the one whose dependency failed, and suggests -allow-errors."""
    tree({**MODULE, "broken/b.go": BROKEN, "dep/d.go": DEPENDS_ON_BROKEN})
    r = run(["survey"])
    assert_run_golden(__file__, "type_errors", r, workdir)


def test_survey_allow_errors(run, tree, workdir):
    """CATCHES: -allow-errors that gives failed packages a clean row, or omits the list of packages that
    did not type-check and the failure count in the type check row."""
    tree({**MODULE, "broken/b.go": BROKEN, "dep/d.go": DEPENDS_ON_BROKEN})
    r = run(["survey", "-allow-errors"])
    assert_run_golden(__file__, "allow_errors", r, workdir)


def test_survey_allow_errors_json(run, tree, workdir):
    """CATCHES: a JSON survey that does not carry the failed packages under -allow-errors."""
    tree({**MODULE, "broken/b.go": BROKEN, "dep/d.go": DEPENDS_ON_BROKEN})
    r = run(["survey", "-allow-errors", "-format=json", "./broken", "./dep", "./app"])
    assert_golden(__file__, "allow_errors_json", normalize(r.stdout, workdir))
    assert r.returncode == 0


def test_survey_test_only_package_warns(run, tree, workdir):
    """CATCHES: a package of test files alone vanishing silently under -test=false; survey warns that it
    has only test files and measures the rest."""
    tree({**MODULE, "testonly/t_test.go": TEST_ONLY})
    r = run(["survey", "-test=false", "./testonly", "./app"])
    assert_run_golden(__file__, "test_only", r, workdir)


def test_survey_no_package_matched(run, tree, workdir):
    """CATCHES: a survey that prints an empty report when its patterns match nothing; it refuses."""
    tree({**MODULE, "empty/x/README": "nothing\n"})
    r = run(["survey", "./empty/..."])
    assert_run_golden(__file__, "no_match", r, workdir)


def test_survey_partial_match_warns(run, tree, workdir):
    """CATCHES: an unmatched pattern beside a matching one that is not warned about or that stops the run."""
    tree({**MODULE, "empty/x/README": "nothing\n"})
    r = run(["survey", "./b", "./empty/..."])
    assert_run_golden(__file__, "partial_match", r, workdir)


def test_survey_explicit_config(run, tree, workdir):
    """CATCHES: a survey that does not show an explicit -config as given, or that still composes the
    discovered chain with it."""
    tree({**MODULE, **QUALIFY, "cfg/strict.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n  unused: off\n"})
    r = run(["survey", "-config", "cfg/strict.yaml", "./app", "./b"])
    assert_run_golden(__file__, "explicit_config", r, workdir)


def test_survey_config_chain_rows(run, tree, workdir):
    """CATCHES: a survey that names one config for the run instead of one row per distinct chain, each
    with its packages count and the rules it put in force."""
    tree({**MODULE, **QUALIFY, "b/.declscope.yaml": "rules:\n  boundary: off\n  surplus: loose\n"})
    r = run(["survey", "./app", "./b", "./api"])
    assert_run_golden(__file__, "chain_rows", r, workdir)


def test_survey_counts_baselined(run, tree, workdir):
    """CATCHES: a survey that does not show the baseline in force with its entry count, or counts
    baselined findings as reported."""
    tree(MODULE)
    run(["baseline"])
    r = run(["survey"])
    assert_run_golden(__file__, "baselined", r, workdir)


def test_survey_counts_ignored(run, tree, workdir):
    """CATCHES: a survey that does not count a finding silenced by //declscope:ignore in the ignored
    column of its rule."""
    tree({"go.mod": GO_MOD,
          "a/a.go": "package a\n\n//declscope:ignore boundary // reason\nfunc aHelper() {}\n\nfunc aOther() {}\n",
          "a/b.go": "package a\n\nfunc bUse() { aHelper(); aOther() }\n\nvar _ = bUse\n"})
    r = run(["survey"])
    assert_run_golden(__file__, "ignored", r, workdir)


def test_survey_refuses_broken_config(run, tree, workdir):
    """CATCHES: a survey that measures under defaults when a config file is invalid."""
    tree({**MODULE, ".declscope.yaml": "rules:\n  unused: sometimes\n"})
    r = run(["survey"])
    assert_run_golden(__file__, "broken_config", r, workdir)


def test_survey_unused_and_boundary_off(run, tree, workdir):
    """CATCHES: a survey that prints 0 rather than - for rules switched off in the config."""
    tree({**MODULE, ".declscope.yaml": "rules:\n  unused: off\n  boundary: off\n  surplus: off\n"})
    r = run(["survey", "./app"])
    assert_run_golden(__file__, "rules_off", r, workdir)


def test_survey_missing_directory(run, tree, workdir):
    """CATCHES: a survey that treats a missing directory as an empty package with a clean row; it names
    the go command's error as a type-check failure and refuses."""
    tree(MODULE)
    r = run(["survey", "./missing"])
    assert_run_golden(__file__, "missing_dir", r, workdir)


def test_survey_directive_problems_counted(run, tree, workdir):
    """CATCHES: a survey whose directive row does not count malformed directives."""
    tree({"go.mod": GO_MOD, "a/a.go": "package a\n\n//declscope:bogus\nfunc aRun() {}\n\n// declscope:shared\nfunc aTwo() {}\n\nvar _, _ = aRun, aTwo\n"})
    r = run(["survey"])
    assert_run_golden(__file__, "directives", r, workdir)


def test_survey_exit_zero_with_findings(run, tree, workdir):
    """CATCHES: a survey that gates like the analyzer (exit 3); it decides nothing and exits 0 even when
    findings are reported."""
    tree({"go.mod": GO_MOD, "a/a.go": "package a\n\nfunc aHelper() {}\n",
          "a/b.go": "package a\n\nfunc bUse() { aHelper() }\n\nvar _ = bUse\n"})
    r = run(["survey", "./a"])
    assert_run_golden(__file__, "exit_zero", r, workdir)
