"""Configuration files: discovery, composition down the chain, every key's values, and invalid input."""

import pytest

from conftest import GO_MOD, assert_run_golden

# One package in which every analyzer rule has something to say.
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

ORDER_GO = """package app

func orderTotal() int { return load() }

var _ = orderTotal
"""

MOUSE_GO = """package app

func wheelDelta() int { return 1 }

var _ = wheelDelta
"""

RULES = {"go.mod": GO_MOD, "app/user.go": USER_GO, "app/order.go": ORDER_GO}

SETTINGS = {
    "unused_loose": "rules:\n  unused: loose\n",
    "unused_off": "rules:\n  unused: off\n",
    "unused_strict": "rules:\n  unused: strict\n",
    "surplus_loose": "rules:\n  surplus: loose\n",
    "surplus_off": "rules:\n  surplus: off\n",
    "boundary_off": "rules:\n  boundary: off\n",
    "boundary_on": "rules:\n  boundary: on\n",
    "qualify_always": "rules:\n  naming:\n    qualify: always\n",
    "qualify_never": "rules:\n  naming:\n    qualify: never\n",
    "qualify_ondemand_exported": "rules:\n  naming:\n    qualify: ondemand\n    exported: true\n",
    "qualify_always_exported_false": "rules:\n  naming:\n    qualify: always\n    exported: false\n",
    "defaults_shared": "defaults:\n  unexported: shared\n",
    "defaults_private": "defaults:\n  unexported: private\n",
    "empty_file": "",
    "comment_only": "# nothing configured here\n",
    "recommended": "rules:\n  naming:\n    qualify: ondemand\n    exported: true\n",
    "reach_without_boundary": "rules:\n  naming:\n    qualify: ondemand\n  boundary: off\n  surplus: off\n",
}


@pytest.mark.parametrize("name", sorted(SETTINGS))
def test_setting_changes_reports(run, tree, workdir, name):
    """CATCHES: a config key that is ignored or misread: every value of rules.unused, rules.surplus,
    rules.boundary, rules.naming.qualify/exported and defaults.unexported must yield exactly the
    reference set of reports for one package where every rule has something to say."""
    tree({**RULES, ".declscope.yaml": SETTINGS[name]})
    r = run(["./..."])
    assert_run_golden(__file__, f"setting_{name}", r, workdir)


ERRORS = {
    "unknown_top_key": "nope: 1\n",
    "unknown_rules_key": "rules:\n  bogus: 1\n",
    "unknown_naming_key": "rules:\n  naming:\n    vocab: {}\n",
    "unknown_defaults_key": "defaults:\n  exported: shared\n",
    "unknown_filter_key": "filter:\n  only: [a]\n  bogus: 1\n",
    "old_package_scope": "defaults:\n  unexported: package\n",
    "bad_qualify": "rules:\n  naming:\n    qualify: sometimes\n",
    "bad_exported": "rules:\n  naming:\n    exported: maybe\n",
    "bad_boundary": "rules:\n  boundary: yes\n",
    "bad_surplus": "rules:\n  surplus: on\n",
    "bad_unused": "rules:\n  unused: strictest\n",
    "yaml_syntax": ": : :\n",
    "two_unknown_keys": "rules:\n  bogus: 1\n  other: 2\n",
    "vocabulary_not_list": "rules:\n  naming:\n    vocabulary:\n      mouse: wheel\n",
    "baseline_not_string": "baseline: [a, b]\n",
    "case_sensitive_mode": "rules:\n  boundary: ON\n",
}


@pytest.mark.parametrize("name", sorted(ERRORS))
def test_invalid_config_is_an_error(run, tree, workdir, name):
    """CATCHES: an invalid config that silently falls back to defaults; the reference names the file, the
    line or key, and what the section or key accepts, and exits 1 without analyzing."""
    tree({**RULES, ".declscope.yaml": ERRORS[name]})
    r = run(["-test=false", "./..."])
    assert_run_golden(__file__, f"error_{name}", r, workdir)


def test_yaml_wins_over_yml(run, tree, workdir):
    """CATCHES: a lookup that reads .declscope.yml when .declscope.yaml is beside it; the .yml here is
    invalid and must not be read, while the .yaml turns boundary off."""
    tree({**RULES, ".declscope.yaml": "rules:\n  boundary: off\n", ".declscope.yml": "bogus: 1\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "yaml_over_yml", r, workdir)


def test_yml_alone_is_read(run, tree, workdir):
    """CATCHES: a lookup that knows only the .yaml spelling; a lone .declscope.yml is read too."""
    tree({**RULES, ".declscope.yml": "rules:\n  boundary: off\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "yaml_over_yml", r, workdir)


def test_lookup_stops_at_module_root(run, tree, workdir):
    """CATCHES: a lookup that walks above the directory holding go.mod; the invalid config above the
    module must not be read."""
    tree({".declscope.yaml": "bogus: 1\n", **{f"mod/{k}": v for k, v in RULES.items()}})
    r = run(["./..."], cwd=workdir / "mod")
    assert_run_golden(__file__, "above_module", r, workdir)


def test_nearer_file_overrides_per_key(run, tree, workdir):
    """CATCHES: a nearer config that replaces the outer one wholesale, or one that is ignored: the root
    turns qualify on and unused off, the nested file turns boundary off, and all three must apply."""
    tree({
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n  unused: off\n",
        "app/.declscope.yaml": "rules:\n  boundary: off\n",
        "app/user.go": USER_GO,
        "app/order.go": ORDER_GO,
    })
    r = run(["./..."])
    assert_run_golden(__file__, "chain_per_key", r, workdir)


def test_nearer_file_restates_a_key(run, tree, workdir):
    """CATCHES: a chain where the outer file wins a key both files state; the nearer file's unused: off
    must win over the root's unused: loose."""
    tree({
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  unused: loose\n",
        "app/.declscope.yaml": "rules:\n  unused: off\n",
        "app/user.go": USER_GO,
        "app/order.go": ORDER_GO,
    })
    r = run(["./..."])
    assert_run_golden(__file__, "chain_restated", r, workdir)


def test_invalid_outer_file_in_chain_fails(run, tree, workdir):
    """CATCHES: a chain that reads only the nearest file; an invalid file at the module root is read too
    and fails the run even though a valid nearer file exists."""
    tree({**RULES, ".declscope.yaml": "rules:\n  surplus: maybe\n", "app/.declscope.yaml": "rules:\n  boundary: off\n"})
    r = run(["-test=false", "./..."])
    assert_run_golden(__file__, "chain_outer_invalid", r, workdir)


def test_vocabulary_word_carries_namespace(run, tree, workdir):
    """CATCHES: rules.naming.vocabulary being ignored: wheelDelta in mouse.go is reported without the
    vocabulary and accepted with mouse: [wheel]."""
    tree({"go.mod": GO_MOD, "app/mouse.go": MOUSE_GO, "app/key.go": "package app\n\nfunc keyPress() {}\n\nvar _ = keyPress\n"})
    tree({".declscope.yaml": "rules:\n  naming:\n    qualify: always\n"})
    without = run(["./..."])
    tree({".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    vocabulary:\n      mouse: [wheel]\n"})
    with_vocab = run(["./..."])
    assert_run_golden(__file__, "vocabulary_without", without, workdir)
    assert_run_golden(__file__, "vocabulary_with", with_vocab, workdir)


def test_vocabulary_merges_down_the_chain(run, tree, workdir):
    """CATCHES: a nested vocabulary that replaces the outer map instead of merging per namespace: the
    root's mouse: [wheel] must still hold when a nested file adds key: [press]."""
    tree({
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    vocabulary:\n      mouse: [wheel]\n",
        "app/.declscope.yaml": "rules:\n  naming:\n    vocabulary:\n      key: [press]\n",
        "app/mouse.go": MOUSE_GO,
        "app/key.go": "package app\n\nfunc pressDown() {}\n\nvar _ = pressDown\n",
    })
    r = run(["./..."])
    (workdir / "app/.declscope.yaml").unlink()
    outer_only = run(["./..."])
    assert_run_golden(__file__, "vocabulary_merged", r, workdir)
    assert_run_golden(__file__, "vocabulary_outer_only", outer_only, workdir)


def test_vocabulary_word_needs_word_boundary(run, tree, workdir):
    """CATCHES: a vocabulary match that is a plain substring search; pinwheel does not start the word
    wheel, so it is still reported under mouse: [wheel]."""
    tree({
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    vocabulary:\n      mouse: [wheel]\n",
        "app/mouse.go": "package app\n\nfunc pinwheel() {}\n\nvar _ = pinwheel\n",
    })
    r = run(["./..."])
    assert_run_golden(__file__, "vocabulary_boundary", r, workdir)


def test_explicit_relative_config(run, tree, workdir):
    """CATCHES: -config resolved against the package directory instead of the working directory."""
    tree({**RULES, "configs/strict.yaml": "rules:\n  naming:\n    qualify: always\n  unused: off\n  surplus: off\n"})
    r = run(["-config", "configs/strict.yaml", "./..."])
    assert_run_golden(__file__, "explicit_relative", r, workdir)


def test_explicit_config_from_subdirectory(run, tree, workdir):
    """CATCHES: a relative -config that is resolved from the module root rather than the working
    directory the command runs in."""
    tree({**RULES, "app/local.yaml": "rules:\n  boundary: off\n  surplus: off\n  unused: off\n"})
    control = run(["."], cwd=workdir / "app")
    r = run(["-config", "local.yaml", "."], cwd=workdir / "app")
    assert_run_golden(__file__, "filter_control", control, workdir)
    assert_run_golden(__file__, "explicit_subdir", r, workdir)


FILTERS = {
    "omit_file_any_depth": "filter:\n  omit: [order.go]\n",
    "omit_anchored_miss": "filter:\n  omit: [/order.go]\n",
    "omit_anchored_hit": "filter:\n  omit: [/app/order.go]\n",
    "omit_dot_anchored_hit": "filter:\n  omit: [./app/order.go]\n",
    "omit_dir_slash": "filter:\n  omit: [app/]\n",
    "omit_dir_glob": "filter:\n  omit: [\"app/**\"]\n",
    "omit_star": "filter:\n  omit: [\"o*.go\"]\n",
    "omit_question": "filter:\n  omit: [\"use?.go\"]\n",
    "only_user": "filter:\n  only: [user.go]\n",
    "only_empty_list": "filter:\n  only: []\n",
    "only_and_omit": "filter:\n  only: [\"*.go\"]\n  omit: [user.go]\n",
    "omit_no_slash_dir_name": "filter:\n  omit: [./app]\n",
    "omit_doublestar_dir": "filter:\n  omit: [\"**/app/**\"]\n",
}


@pytest.mark.parametrize("name", sorted(FILTERS))
def test_filter_patterns(run, tree, workdir, name):
    """CATCHES: filter patterns matched with the wrong anchoring: a bare name matches at any depth, a
    leading / or ./ anchors at the config's directory, a trailing / names a directory, and * and ?
    stay within one path segment, as the README's table states."""
    tree(RULES)
    control = run(["./..."])
    tree({".declscope.yaml": FILTERS[name]})
    r = run(["./..."])
    assert_run_golden(__file__, "filter_control", control, workdir)
    assert_run_golden(__file__, f"filter_{name}", r, workdir)


def test_filter_only_cancelled_by_outer_only(run, tree, workdir):
    """CATCHES: a missing filter report: a nested only that matches files which the root's only removes
    leaves the package read as empty, and the reference reports that once at the first file."""
    tree({**RULES, ".declscope.yaml": "filter:\n  only: [\"other/**\"]\n", "app/.declscope.yaml": "filter:\n  only: [user.go]\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "filter_cancelled", r, workdir)


def test_filter_only_intersects(run, tree, workdir):
    """CATCHES: a chain that unions only lists; a file must match every stating file's only list, so
    with root only: [\"*.go\"] and nested only: [order.go] only order.go is read."""
    tree({**RULES, ".declscope.yaml": "filter:\n  only: [\"*.go\"]\n"})
    control = run(["./..."])
    tree({"app/.declscope.yaml": "filter:\n  only: [order.go]\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "filter_control", control, workdir)
    assert_run_golden(__file__, "filter_intersect", r, workdir)


def test_filter_omit_unions(run, tree, workdir):
    """CATCHES: a nested omit that replaces the root's omit; both lists apply, so neither file is read."""
    tree({**RULES, ".declscope.yaml": "filter:\n  omit: [order.go]\n"})
    control = run(["./..."])
    tree({"app/.declscope.yaml": "filter:\n  omit: [user.go]\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "filter_omit_file_any_depth", control, workdir)
    assert_run_golden(__file__, "filter_union", r, workdir)


def test_filter_pattern_relative_to_its_config(run, tree, workdir):
    """CATCHES: anchored patterns resolved against the module root instead of the directory of the config
    file that states them; /order.go in app/.declscope.yaml names app/order.go."""
    tree({**RULES, "app/.declscope.yaml": "filter:\n  omit: [/order.go]\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "filter_relative_base", r, workdir)


def test_ignore_filter_is_unused(run, tree, workdir):
    """CATCHES: an implementation that lets //declscope:ignore filter silence something; it silences
    nothing, so the unused rule reports it."""
    tree({"go.mod": GO_MOD, "app/a.go": "package app\n\n//declscope:ignore filter\nfunc aRun() {}\n\nvar _ = aRun\n"})
    r = run(["./..."])
    assert_run_golden(__file__, "ignore_filter_unused", r, workdir)
