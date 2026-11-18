"""Configuration: .declscope.yaml discovery and composition, every key and value, filter patterns, errors."""

import pytest

from conftest import GO_MOD, read_golden, write_tree


def golden(name):
    return read_golden(__file__, name)


def crossing(pkg):
    """user.go declares helper; order.go and gen.go each use it from their own namespace."""
    return {
        "user.go": f"package {pkg}\n\nfunc helper() int {{ return 1 }}\n",
        "order.go": f"package {pkg}\n\nfunc orderRun() int {{ return helper() }}\n\nvar _ = orderRun\n",
        "gen.go": f"package {pkg}\n\nfunc genRun() int {{ return helper() }}\n\nvar _ = genRun\n",
    }


def three_packages():
    files = {"go.mod": GO_MOD}
    for prefix, pkg in (("", "app"), ("gen/", "gen"), ("q/gen/", "deep")):
        files.update({prefix + name: body for name, body in crossing(pkg).items()})
    return files


FILTER_CASES = {
    "float_file": "gen.go",
    "anchored_slash_file": "/gen.go",
    "anchored_dot_file": "./gen.go",
    "anchored_dir_glob": "gen/**",
    "any_depth_dir": "**/gen/**",
    "trailing_slash_dir": "gen/",
    "anchored_trailing_slash": "/gen/",
    "dot_trailing_slash": "./gen/",
    "star_in_segment": "or*.go",
    "question_mark": "?en.go",
    "dot_names_a_file": "./gen",
}


@pytest.mark.parametrize("case", sorted(FILTER_CASES))
def test_omit_pattern_anchoring(ds, workdir, case):
    """CATCHES: a filter that anchors or floats a pattern differently from .gitignore's rules (a bare name at
    any depth, a leading / or ./ beside the config, a trailing / naming a directory, * and ? within one
    segment), so the wrong files are left unread and the wrong crossings reported."""
    write_tree(workdir, {**three_packages(), ".declscope.yaml": f"filter:\n  omit:\n    - {FILTER_CASES[case]!r}\n"})
    out = ds(["./..."])
    assert out.transcript == golden(f"omit_{case}")


def test_only_restricts_and_omit_subtracts(ds, workdir):
    """CATCHES: a filter where only does not keep files outside its patterns unread, or where omit cannot take
    back a file only admitted."""
    write_tree(workdir, {**three_packages(),
                         ".declscope.yaml": "filter:\n  only:\n    - \"**/gen/**\"\n  omit:\n    - \"q/**\"\n"})
    out = ds(["./..."])
    assert out.transcript == golden("only_and_omit")


def test_nested_only_intersects_and_omit_unions(ds, workdir):
    """CATCHES: a nested config whose filter replaces the root's instead of composing with it: only must
    intersect, omit must union, so a nested file can narrow what is read and never widen it."""
    write_tree(workdir, {
        **three_packages(),
        ".declscope.yaml": "filter:\n  only:\n    - \"gen/**\"\n    - \"q/**\"\n  omit:\n    - order.go\n",
        "q/.declscope.yaml": "filter:\n  only:\n    - \"gen/user.go\"\n    - \"gen/gen.go\"\n    - \"gen/order.go\"\n"
                             "  omit:\n    - gen.go\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("nested_filters")


def test_filter_cancelled_by_only_above(ds, workdir):
    """CATCHES: an analyzer that reads the package as empty in silence when a nested only matches files an only
    above removes, instead of the filter report at the first file; and an ignore naming filter that
    silences it."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "filter:\n  only:\n    - \"keep/**\"\n",
        "keep/k.go": "package keep\n\nfunc Run() int { return 1 }\n",
        "sub/.declscope.yaml": "filter:\n  only:\n    - \"*.go\"\n",
        "sub/a.go": "//declscope:ignore filter\n\npackage sub\n\nfunc helper() int { return 1 }\n",
        "sub/b.go": "package sub\n\nfunc bRun() int { return helper() }\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("filter_cancelled")


def test_pattern_leaving_the_config_directory(ds, workdir):
    """CATCHES: a filter that accepts a pattern with .. (which could never match) instead of refusing it with a
    message naming the pattern."""
    write_tree(workdir, {**three_packages(), ".declscope.yaml": "filter:\n  omit:\n    - \"../gen.go\"\n"})
    out = ds(["./..."])
    assert out.transcript == golden("pattern_leaves_directory")


def test_defaults_unexported_shared(ds, workdir):
    """CATCHES: an analyzer that ignores defaults.unexported: shared, so unexported declarations still cross,
    while //declscope:private still narrows one back."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "defaults:\n  unexported: shared\nrules:\n  surplus: off\n",
        "user.go": "package x\n\nfunc helper() int { return 1 }\n\n//declscope:private\nfunc narrow() int { return 2 }\n",
        "order.go": "package x\n\nfunc orderRun() int { return helper() + narrow() }\n\nvar _ = orderRun\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("defaults_shared")


def test_boundary_off(ds, workdir):
    """CATCHES: an analyzer that still reports crossings under rules.boundary: off, or that turns the naming
    rule off with it."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n  boundary: off\n  surplus: off\n",
        "user.go": "package x\n\nfunc helper() int { return 1 }\n",
        "order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("boundary_off")


def test_naming_exported_and_vocabulary(ds, workdir):
    """CATCHES: a naming rule that skips exported names under rules.naming.exported: true, lowers the prefix of
    an exported rename, or ignores vocabulary words (with the same word-boundary test as the namespace)."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n    vocabulary:\n"
                           "      mouse: [wheel]\n      tracing: [trace]\n",
        "mouse.go": "package x\n\nfunc wheelDelta() int { return 1 }\n\nfunc pinwheel() int { return 2 }\n\n"
                    "func Load() int { return wheelDelta() + pinwheel() }\n",
        "tracing.go": "package x\n\nfunc traceValue() int { return 1 }\n\nfunc spanValue() int { return traceValue() }\n\n"
                      "var _ = spanValue\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("exported_and_vocabulary")


def test_vocabulary_merges_per_namespace(ds, workdir):
    """CATCHES: a nested config whose vocabulary replaces the root's whole map instead of merging per
    namespace, with the nearer file winning the namespaces it states."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    vocabulary:\n      mouse: [wheel]\n"
                           "      index: [indices]\n",
        "p/.declscope.yaml": "rules:\n  naming:\n    vocabulary:\n      mouse: [scroll]\n",
        "p/mouse.go": "package p\n\nfunc wheelDelta() int { return 1 }\n\nfunc scrollDelta() int { return 2 }\n\n"
                      "var _ = wheelDelta() + scrollDelta()\n",
        "p/index.go": "package p\n\nfunc indicesOf() int { return 1 }\n\nvar _ = indicesOf\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("vocabulary_merge")


def test_nearer_file_overrides_only_the_keys_it_states(ds, workdir):
    """CATCHES: a config chain where the nearer file replaces the outer one wholesale, dropping the outer
    file's qualify mode, instead of overriding key by key."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n  surplus: off\n",
        "p/.declscope.yaml": "rules:\n  surplus: strict\n",
        "p/user.go": "package p\n\n//declscope:shared\nfunc helper() int { return 1 }\n\nvar _ = helper\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("key_by_key")


def test_yml_extension_and_empty_file(ds, workdir):
    """CATCHES: a lookup that does not find .declscope.yml, or that rejects an empty config file instead of
    reading it as changing nothing."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yml": "rules:\n  naming:\n    qualify: always\n",
        "p/.declscope.yaml": "",
        "p/user.go": "package p\n\nfunc helper() int { return 1 }\n\nvar _ = helper\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("yml_and_empty")


def test_explicit_config_reads_no_other(ds, workdir):
    """CATCHES: a -config that is merged with the discovered .declscope.yaml files instead of being the only
    file read, and a -config naming a missing file that is not refused."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "ci.yaml": "rules:\n  surplus: loose\n",
        "user.go": "package x\n\nfunc helper() int { return 1 }\n\n//declscope:shared\nfunc wide() int { return 2 }\n\n"
                   "var _ = helper() + wide()\n",
    })
    chosen = ds(["-config", "ci.yaml", "./..."])
    discovered = ds(["./..."])
    missing = ds(["-config", "absent.yaml", "./..."])
    assert "\n".join([chosen.transcript, discovered.transcript, missing.transcript]) == golden("explicit_config")


CONFIG_ERRORS = {
    "unknown_top_key": "rule:\n  surplus: off\n",
    "unknown_rules_key": "rules:\n  surplas: off\n",
    "unknown_naming_key": "rules:\n  naming:\n    qualifiy: always\n",
    "unknown_defaults_key": "defaults:\n  exported: shared\n",
    "unknown_filter_key": "filter:\n  exclude: [a.go]\n",
    "bad_unexported": "defaults:\n  unexported: package\n",
    "bad_qualify": "rules:\n  naming:\n    qualify: sometimes\n",
    "bad_exported": "rules:\n  naming:\n    exported: maybe\n",
    "bad_boundary": "rules:\n  boundary: strict\n",
    "bad_surplus": "rules:\n  surplus: on\n",
    "bad_unused": "rules:\n  unused: on\n",
    "not_yaml": "rules: [\n",
    "two_unknown_keys": "rules:\n  naming:\n    qualify: never\n    prefix: x\n  surplas: off\n",
}


@pytest.mark.parametrize("case", sorted(CONFIG_ERRORS))
def test_config_errors(ds, workdir, case):
    """CATCHES: a config reader that accepts an unknown key or an invalid value (leaving a rule at its default in
    silence), or whose error does not name the file, the line, the key and what the section or key takes."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": CONFIG_ERRORS[case],
        "user.go": "package x\n\nfunc helper() int { return 1 }\n",
        "order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    })
    analyzer = ds(["./..."])
    survey = ds(["survey", "-format=json"])
    assert analyzer.transcript + "\n" + survey.transcript == golden(f"error_{case}")


def test_baseline_key_relative_to_config(ds, workdir):
    """CATCHES: a baseline key resolved against the working directory instead of the config file's own
    directory, so the analyzer reads no baseline from a nested config."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "p/.declscope.yaml": "baseline: recorded/base.yaml\n",
        "p/recorded/base.yaml": "packages:\n  example.com/app/p:\n    boundary:\n      user:\n        - helper\n",
        "p/user.go": "package p\n\nfunc helper() int { return 1 }\n\nfunc spare() int { return 2 }\n",
        "p/order.go": "package p\n\nfunc orderRun() int { return helper() + spare() }\n\nvar _ = orderRun\n",
    })
    out = ds(["./..."])
    survey = ds(["survey", "-format=json"])
    assert out.transcript + "\n" + survey.transcript == golden("baseline_relative")


def test_baseline_found_by_upward_lookup(ds, workdir):
    """CATCHES: an analyzer that only reads a baseline beside the package, instead of the nearest
    .declscope-baseline.yaml (or .yml) found walking up to the module root."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope-baseline.yml": "packages:\n  example.com/app/p/inner:\n    boundary:\n      user:\n        - helper\n",
        "p/inner/user.go": "package inner\n\nfunc helper() int { return 1 }\n\nfunc spare() int { return 2 }\n",
        "p/inner/order.go": "package inner\n\nfunc orderRun() int { return helper() + spare() }\n\nvar _ = orderRun\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("baseline_upward")


def test_lookup_stops_at_the_module_root(ds, workdir):
    """CATCHES: a config lookup that walks past go.mod into a parent directory's .declscope.yaml."""
    write_tree(workdir, {
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "mod/go.mod": GO_MOD,
        "mod/user.go": "package x\n\nfunc helper() int { return 1 }\n",
        "mod/order.go": "package x\n\nfunc orderRun() int { return helper() }\n\nvar _ = orderRun\n",
    })
    out = ds(["./..."], cwd=workdir / "mod")
    assert out.transcript == golden("stops_at_module_root")
