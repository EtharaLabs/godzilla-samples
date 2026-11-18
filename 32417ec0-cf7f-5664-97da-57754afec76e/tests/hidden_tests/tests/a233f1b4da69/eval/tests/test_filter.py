"""filter.only and filter.omit: which files the analyzer reads, how each pattern spelling anchors, how a chain of
configs intersects only and unions omit, and patterns seen through symbolic links."""

import os

import pytest

from conftest import assert_golden, gomod, transcript, write_files

# Every file holds a malformed directive, so each file the analyzer reads shows up as one report naming it.
MARK = "package {pkg}\n\n// declscope:shared\nfunc {name}() {{}}\n"

TREE = {
    "go.mod": gomod("example.com/f"),
    "a.go": MARK.format(pkg="f", name="a"),
    "gen.go": MARK.format(pkg="f", name="g"),
    "x.go": MARK.format(pkg="f", name="x"),
    "gen/gen.go": MARK.format(pkg="gen", name="g"),
    "gen/other.go": MARK.format(pkg="gen", name="o"),
    "sub/sub.go": MARK.format(pkg="sub", name="s"),
    "sub/gen.go": MARK.format(pkg="sub", name="g"),
    "sub/gen/gen.go": MARK.format(pkg="gen", name="g"),
    "vendored/vendor.go": MARK.format(pkg="vendored", name="v"),
}

PATTERNS = {
    "omit_floating_file": "filter:\n  omit: [gen.go]\n",
    "omit_anchored_slash": "filter:\n  omit: [/gen.go]\n",
    "omit_anchored_dot": "filter:\n  omit: [./gen.go]\n",
    "omit_anchored_dir": "filter:\n  omit: [gen/**]\n",
    "omit_floating_dir": "filter:\n  omit: [\"**/gen/**\"]\n",
    "omit_trailing_slash": "filter:\n  omit: [gen/]\n",
    "omit_anchored_trailing_slash": "filter:\n  omit: [/gen/]\n",
    "omit_dot_trailing_slash": "filter:\n  omit: [./gen/]\n",
    "omit_question_mark": "filter:\n  omit: [\"?.go\"]\n",
    "omit_star_in_segment": "filter:\n  omit: [\"sub/*.go\"]\n",
    "omit_double_star_suffix": "filter:\n  omit: [\"sub/g**\"]\n",
    "omit_dot_vendor_is_a_file": "filter:\n  omit: [./vendored]\n",
    "only_one_dir": "filter:\n  only: [\"sub/**\"]\n",
    "only_and_omit": "filter:\n  only: [\"sub/**\", a.go]\n  omit: [\"**/gen.go\"]\n",
}


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_pattern_spellings(run, workdir, name):
    """CATCHES: a filter pattern anchored or floated against .gitignore's rules (a leading / or ./ anchors, a bare
    name floats, a trailing / names a directory, ** spans segments, * and ? stay in one), so that the wrong files are
    read or left out."""
    write_files(workdir, {**TREE, ".declscope.yaml": PATTERNS[name]})
    assert_golden(transcript(run(["./..."]), workdir), __file__, name)


def test_chain_intersects_only_and_unions_omit(run, workdir):
    """CATCHES: a nested config whose filter replaces the outer one: only must intersect (a file is read only if every
    stating file's list matches it) and omit must union (a nested file cannot put back what the root omits)."""
    write_files(workdir, {
        **TREE,
        ".declscope.yaml": "filter:\n  only: [\"sub/**\", \"gen/**\"]\n  omit: [sub/gen.go]\n",
        "sub/.declscope.yaml": "filter:\n  only: [\"*.go\"]\n",
    })
    assert_golden(transcript(run(["./..."]), workdir), __file__, "chain")


def test_nested_only_cancelled_by_an_outer_only(run, workdir):
    """CATCHES: the filter rule's one report missing: a nested only that matches files which an only above it removes
    entirely, so the package is read as empty (and an ignore naming filter silences nothing)."""
    write_files(workdir, {
        "go.mod": gomod("example.com/f"),
        ".declscope.yaml": "filter:\n  only: [\"other/**\"]\n",
        "other/o.go": "package other\n",
        "sub/.declscope.yaml": "filter:\n  only: [a.go]\n",
        "sub/a.go": "//declscope:ignore filter\n\npackage sub\n\nfunc a() {}\n",
    })
    assert_golden(transcript(run(["./..."]), workdir), __file__, "cancelled")


def test_explicit_config_in_a_subdirectory_anchors_there(run, workdir):
    """CATCHES: an anchored pattern of an explicit -config resolved against the working directory instead of the
    config file's own directory, so it matches files outside the tree it speaks for."""
    write_files(workdir, {**TREE, "conf/cfg.yaml": "filter:\n  omit: [/a.go, \"gen/**\"]\n", "conf/gen/x.txt": "x\n"})
    assert_golden(transcript(run(["-config", "conf/cfg.yaml", "./..."]), workdir), __file__, "explicit_subdir")


def test_config_named_through_a_symlink(run, workdir):
    """CATCHES: an anchored pattern that stops matching when its config file is named through a symbolic link (the
    driver spells the files by their real path)."""
    write_files(workdir, {**TREE, "cfg.yaml": "filter:\n  omit: [/x.go, \"gen/**\"]\n"})
    os.symlink(workdir, workdir.parent / "link")
    r = run(["-config", str(workdir.parent / "link" / "cfg.yaml"), "./..."])
    assert_golden(transcript(r, workdir), __file__, "symlinked_config")


def test_files_spelled_through_a_symlink(run, workdir):
    """CATCHES: an anchored pattern of a config named by its real path that misses files the driver spells through a
    symbolic link to the module, because it compares the spellings as text."""
    write_files(workdir, {**TREE, "cfg.yaml": "filter:\n  omit: [/x.go, \"gen/**\"]\n"})
    link = workdir.parent / "link"
    os.symlink(workdir, link)
    r = run(["-config", str(workdir / "cfg.yaml"), "./..."], cwd=link, env_overrides={"PWD": str(link)})
    assert_golden(transcript(r, workdir), __file__, "symlinked_files")


def test_pattern_leaving_its_directory_is_refused(run, workdir):
    """CATCHES: a pattern containing .. accepted (it can never match a path taken from the config directory)."""
    write_files(workdir, {**TREE, ".declscope.yaml": "filter:\n  only: [sub/../a.go]\n"})
    assert_golden(transcript(run(["./..."]), workdir), __file__, "dotdot")
