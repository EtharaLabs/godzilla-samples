"""Configuration files: the errors an invalid one is refused with, how a chain of them composes, and where the
baseline they name is read from."""

import pytest

from conftest import assert_golden, gomod, transcript, write_files

CROSSING = {
    "go.mod": gomod("example.com/c"),
    "user.go": "package c\n\nfunc helper() int { return 1 }\n\ntype box struct {\n\tn int\n}\n",
    "order.go": "package c\n\nfunc orderRun() int { return helper() + box{}.n }\n\nvar _ = orderRun\n",
}

INVALID = {
    "bad_bool": "rules:\n  naming:\n    exported: maybe\n",
    "bad_scope": "defaults:\n  unexported: public\n",
    "bad_qualify": "rules:\n  naming:\n    qualify: sometimes\n",
    "bad_boundary": "rules:\n  boundary: maybe\n",
    "bad_surplus": "rules:\n  surplus: total\n",
    "bad_unused": "rules:\n  unused: never\n",
    "unknown_top_key": "rule:\n  boundary: off\n",
    "unknown_rules_key": "rules:\n  bogus: on\n",
    "unknown_naming_key": "rules:\n  naming:\n    prefix: always\n",
    "unknown_filter_key": "filter:\n  exclude: [x]\n",
    "wrong_type_section": "rules: 5\n",
    "wrong_type_list": "filter:\n  only: gen.go\n",
    "vocabulary_not_a_list": "rules:\n  naming:\n    vocabulary:\n      user: account\n",
    "pattern_leaves_dir": "filter:\n  omit: [../other.go]\n",
    "not_yaml": "rules: [\n",
    "legacy_package_scope": "defaults:\n  unexported: package\n",
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalid_config_is_refused(run, workdir, name):
    """CATCHES: an invalid config (bad value, unknown key in any section, wrong YAML type, a filter pattern leaving
    its directory, a legacy spelling) that is silently ignored, leaving a rule at its default, or refused with a
    message that does not name the key and what it takes."""
    write_files(workdir, {**CROSSING, ".declscope.yaml": INVALID[name]})
    assert_golden(transcript(run(["./..."]), workdir), __file__, f"invalid_{name}")


def test_empty_config_changes_nothing(run, workdir):
    """CATCHES: an empty .declscope.yaml (or a .yml one) read as an error, or as switching rules off."""
    write_files(workdir, {**CROSSING, ".declscope.yml": ""})
    assert_golden(transcript(run(["./..."]), workdir), __file__, "empty")


def test_chain_composes_key_by_key(run, workdir):
    """CATCHES: a nested config that replaces the one above it instead of composing key by key: the nearer file wins
    the keys it states (qualify), the outer file's other keys still hold (exported), vocabulary merges per namespace."""
    write_files(workdir, {
        "go.mod": gomod("example.com/c"),
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n    vocabulary:\n      user: [account]\n",
        "sub/.declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n    vocabulary:\n      order: [purchase]\n",
        "sub/user.go": "package sub\n\nfunc accountGet() int { return 1 }\n\nfunc Fetch() int { return accountGet() }\n",
        "sub/order.go": "package sub\n\nfunc purchaseRun() int { return Fetch() }\n\nfunc Other() int { return purchaseRun() }\n",
        "top/only.go": "package top\n\nfunc alone() int { return 1 }\n\nvar _ = alone\n",
    })
    assert_golden(transcript(run(["./..."]), workdir), __file__, "chain")


def test_config_and_baseline_lookup_stops_at_the_module_root(run, workdir):
    """CATCHES: a config lookup that walks past the module root, so a .declscope.yaml above the module changes its
    rules."""
    write_files(workdir, {
        ".declscope.yaml": "rules:\n  boundary: off\n",
        **{f"mod/{k}": v for k, v in CROSSING.items()},
    })
    assert_golden(transcript(run(["./..."], cwd=workdir / "mod"), workdir), __file__, "module_root")


def test_named_baseline_that_does_not_exist_is_empty(run, workdir):
    """CATCHES: a baseline named by the config that does not exist yet treated as an error (it is an empty baseline)
    instead of reporting every violation."""
    write_files(workdir, {**CROSSING, ".declscope.yaml": "baseline: missing.yaml\n"})
    assert_golden(transcript(run(["./..."]), workdir), __file__, "missing_baseline")


def test_absolute_baseline_path(run, workdir):
    """CATCHES: an absolute baseline path joined onto the config file's directory instead of read as written."""
    write_files(workdir, {**CROSSING, "store/base.yaml": "packages:\n  example.com/c:\n    boundary:\n      user:\n        - helper\n"})
    (workdir / ".declscope.yaml").write_text(f"baseline: {workdir / 'store' / 'base.yaml'}\n")
    assert_golden(transcript(run(["./..."]), workdir), __file__, "absolute_baseline")


def test_baseline_relative_to_the_config_file(run, workdir):
    """CATCHES: a baseline path resolved against the working directory rather than the config file that names it."""
    write_files(workdir, {
        **CROSSING,
        "conf/cfg.yaml": "baseline: base.yaml\n",
        "conf/base.yaml": "packages:\n  example.com/c:\n    boundary:\n      user:\n        - helper\n",
    })
    assert_golden(transcript(run(["-config", "conf/cfg.yaml", "./..."]), workdir), __file__, "relative_baseline")


def test_defaults_unexported_shared(run, workdir):
    """CATCHES: defaults.unexported: shared that does not widen undirected unexported declarations, or that leaves
    a //declscope:shared on one unreported as redundant under strict."""
    write_files(workdir, {
        **CROSSING,
        ".declscope.yaml": "defaults:\n  unexported: shared\n",
        "extra.go": "package c\n\n//declscope:shared\nfunc extraHelper() int { return orderRun() }\n\n//declscope:private\nfunc extraOwn() int { return extraHelper() }\n\nvar _ = extraOwn\n",
    })
    assert_golden(transcript(run(["./..."]), workdir), __file__, "defaults_shared")


def test_baseline_path_through_a_file(run, workdir):
    """CATCHES: a baseline path that cannot be looked at (a component of it is a file) read as an empty baseline,
    which would report every recorded violation as new, instead of failing with the error."""
    write_files(workdir, {**CROSSING, ".declscope.yaml": "baseline: blocker/base.yaml\n", "blocker": "a file\n"})
    assert_golden(transcript(run(["./..."]), workdir), __file__, "baseline_through_file")
