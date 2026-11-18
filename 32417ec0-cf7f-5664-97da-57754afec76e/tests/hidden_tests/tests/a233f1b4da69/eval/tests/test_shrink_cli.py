"""declscope shrink as a command: its flags, its patterns, its exit status, and the runs it refuses."""

from conftest import assert_golden, gomod, transcript, write_files

MOD = "example.com/m"

# One package of every kind of exported declaration, half of them used from b.
KINDS = {
    "go.mod": gomod(MOD),
    "internal/a/a.go": """package a

// Format renders an ID for display.
func Format(id int) int { return id }

func Used() int { return Format(1) }

// A Thing is a value.
type Thing struct {
	Name  string
	Count int
}

// Loader opens this comment, which is another word.
func Load() Thing { return Thing{} }

func (t Thing) Size() int { return t.Count }

var Version = "dev"

var Limit = 3

const Max = 10

// The Mode is a mode.
type Mode int

const (
	Fast Mode = iota
	Slow
)
""",
    "b/b.go": """package b

import "example.com/m/internal/a"

var X = a.Used()
""",
}


def test_help_prints_usage_on_stderr(run, workdir):
    """CATCHES: a shrink -h that prints nothing, prints to stdout, exits non-zero, or omits the -config and -fix
    flags from the usage text."""
    r = run(["shrink", "-h"])
    assert_golden(transcript(r, workdir), __file__, "help")


def test_unknown_flag_exits_2_with_usage(run, workdir):
    """CATCHES: an unknown shrink flag that is ignored, treated as a package pattern, or exits with a status
    other than the flag package's 2."""
    r = run(["shrink", "-bogus"])
    assert_golden(transcript(r, workdir), __file__, "unknown_flag")


def test_default_pattern_outside_a_module_fails(run, workdir):
    """CATCHES: a run outside any module that reports nothing and exits 0 instead of failing on the ./...
    pattern the go command rejects."""
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "outside_module_default")


def test_std_pattern_outside_a_module_is_not_inside_a_module(run, workdir):
    """CATCHES: an implementation that resolves a standard-library pattern outside a module and then crashes or
    succeeds instead of refusing with 'not inside a module'."""
    r = run(["shrink", "unsafe"])
    assert_golden(transcript(r, workdir), __file__, "outside_module_std")


def test_reports_every_kind_of_declaration(run, workdir):
    """CATCHES: a shrink that misses a kind (func, type, field, method, var, const, const set), mislabels the kind,
    reports a declaration another package uses, or exits 0 while reporting."""
    write_files(workdir, KINDS)
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "kinds")


def test_fix_unexports_and_prints_only_reports_without_a_fix(run, workdir):
    """CATCHES: a -fix that leaves names exported, misses a use or a doc comment's leading name, rewrites a doc
    comment opening with a longer word, prints fixed reports, or exits 0 while unfixable reports remain."""
    write_files(workdir, KINDS)
    r = run(["shrink", "-fix"])
    assert_golden(transcript(r, workdir, ("internal/a/a.go", "b/b.go")), __file__, "kinds_fix")


def test_fix_with_everything_fixable_exits_zero(run, workdir):
    """CATCHES: a -fix that still counts reports it fixed towards exit status 3, or prints them."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\n// Helper helps.\nfunc Helper() int { return 1 }\n\nvar _ = Helper()\n",
    })
    r = run(["shrink", "-fix"])
    assert_golden(transcript(r, workdir, ("internal/a/a.go",)), __file__, "all_fixable")


def test_second_fix_run_finds_nothing(run, workdir):
    """CATCHES: a fix that does not converge: the run after -fix still reports a declaration the first run fixed."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc Helper() int { return 1 }\n\ntype Box struct{ N int }\n\nvar _ = Box{N: Helper()}\n",
    })
    first = run(["shrink", "-fix"])
    second = run(["shrink"])
    assert_golden(transcript(first, workdir) + "\n=== second run\n" + transcript(second, workdir, ("internal/a/a.go",)),
                  __file__, "converges")


def test_clean_module_reports_nothing(run, workdir):
    """CATCHES: a shrink that reports a declaration another package uses, or exits non-zero with nothing to say; the
    standard-library pattern beside ./... is counted on stderr, not judged."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc F() int { return 1 }\n",
        "b/b.go": 'package b\n\nimport "example.com/m/internal/a"\n\nvar X = a.F()\n',
    })
    r = run(["shrink", "./...", "unsafe"])
    assert_golden(transcript(r, workdir), __file__, "clean")


def test_pattern_chooses_reports_but_every_importer_counts(run, workdir):
    """CATCHES: a shrink that loads only the named packages, and so reports Used, which b outside the pattern
    calls, or reports packages outside the pattern."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc Used() {}\n\nfunc Unused() {}\n",
        "internal/c/c.go": "package c\n\nfunc Other() {}\n",
        "b/b.go": 'package b\n\nimport "example.com/m/internal/a"\n\nfunc init() { a.Used() }\n',
    })
    r = run(["shrink", "./internal/a/..."])
    assert_golden(transcript(r, workdir), __file__, "pattern")


def test_import_path_pattern(run, workdir):
    """CATCHES: a shrink that accepts only directory patterns and not an import path the go command resolves."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc Unused() {}\n",
        "internal/c/c.go": "package c\n\nfunc Other() {}\n",
    })
    r = run(["shrink", "example.com/m/internal/c"])
    assert_golden(transcript(r, workdir), __file__, "import_path")


def test_pattern_matching_nothing_beside_others_warns(run, workdir):
    """CATCHES: a pattern that matches no package silently dropped, or treated as fatal when another pattern
    matches."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc Unused() {}\n",
        "empty/README": "nothing here\n",
    })
    r = run(["shrink", "./internal/...", "./empty/..."])
    assert_golden(transcript(r, workdir), __file__, "unmatched_warning")


def test_every_pattern_matching_nothing_fails(run, workdir):
    """CATCHES: a run whose only pattern names nothing that exits 0 as if nothing were overexported."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc Unused() {}\n",
        "empty/README": "nothing here\n",
    })
    r = run(["shrink", "./empty/..."])
    assert_golden(transcript(r, workdir), __file__, "unmatched_only")


def test_missing_directory_pattern_fails(run, workdir):
    """CATCHES: a pattern naming a directory that does not exist accepted as matching nothing instead of
    stopping the run as the go command does."""
    write_files(workdir, {"go.mod": gomod(MOD), "internal/a/a.go": "package a\n\nfunc Unused() {}\n"})
    r = run(["shrink", "./nope"])
    assert_golden(transcript(r, workdir), __file__, "missing_dir")


def test_packages_outside_the_module_are_counted(run, workdir):
    """CATCHES: standard-library packages named by a pattern listed one by one, judged, or not mentioned at all."""
    write_files(workdir, {"go.mod": gomod(MOD), "b/b.go": "package b\n\nfunc F() {}\n"})
    r = run(["shrink", "unsafe", "./b"])
    assert_golden(transcript(r, workdir), __file__, "outside_count")


def test_package_that_does_not_type_check_refuses_the_run(run, workdir):
    """CATCHES: a shrink that judges a module with a type error, where every absence of a use is meaningless,
    or that does not name the failing package and error."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": 'package a\n\nfunc F() int { return "x" }\n',
        "b/b.go": 'package b\n\nimport "example.com/m/internal/a"\n\nvar X = a.F()\n',
    })
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "type_error")


def test_module_with_no_package_fails(run, workdir):
    """CATCHES: a module holding no Go package that is reported clean instead of refused."""
    write_files(workdir, {"go.mod": gomod(MOD)})
    r = run(["shrink", "unsafe"])
    assert_golden(transcript(r, workdir), __file__, "no_package")


def test_build_excluded_file_that_does_not_parse_fails(run, workdir):
    """CATCHES: a build-excluded file that does not parse skipped silently, though its uses could not be read."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
        "internal/a/a_never.go": "//go:build never\n\npackage a\n\nfunc G( {\n",
    })
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "excluded_parse_error")


def test_nested_go_mod_without_module_path_fails(run, workdir):
    """CATCHES: a nested go.mod with no module line ignored instead of stopping the run."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
        "tools/go.mod": "go 1.25\n",
    })
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "nested_no_module_path")


def test_package_outside_internal_is_never_judged_or_listed(run, workdir):
    """CATCHES: a shrink that reports exported declarations of a package another module may import, or names
    such a package on stderr, while it still judges the internal package beside it."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "pub/pub.go": "package pub\n\nfunc Unused() {}\n\ntype T struct{ F int }\n",
        "internal/in/in.go": "package in\n\nfunc Unused() {}\n",
    })
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "outside_internal")


def test_build_tags_from_goflags(run, workdir):
    """CATCHES: a shrink that ignores GOFLAGS build tags: with -tags=never the tagged file is compiled, so its call
    is a use, and its own exported function is judged."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/a/a.go": "package a\n\nfunc Tagged() {}\n\nfunc Unused() {}\n",
        "b/b_never.go": '//go:build never\n\npackage b\n\nimport "example.com/m/internal/a"\n\nfunc Run() { a.Tagged() }\n',
        "internal/t/t_never.go": "//go:build never\n\npackage t\n\nfunc OnlyTagged() {}\n",
    })
    plain = run(["shrink"])
    tagged = run(["shrink"], env_overrides={"GOFLAGS": "-tags=never"})
    assert_golden(transcript(plain, workdir) + "\n=== GOFLAGS=-tags=never\n" + transcript(tagged, workdir),
                  __file__, "goflags_tags")
