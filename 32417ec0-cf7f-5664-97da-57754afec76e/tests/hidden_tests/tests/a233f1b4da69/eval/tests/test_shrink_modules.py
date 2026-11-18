"""declscope shrink across module boundaries: nested modules, workspaces and build lists decide whether an
internal/ range can be judged, and whether its fixes are safe."""

import pytest

from conftest import assert_golden, gomod, transcript, write_files


def shrink(run, workdir, files, *args, cwd="", env=None):
    write_files(workdir, files)
    r = run(["shrink", *args], cwd=workdir / cwd if cwd else None, env_overrides=env)
    return transcript(r, workdir)


def test_nested_module_importing_nothing_leaves_range_judged(run, workdir):
    """CATCHES: a nested module whose path extends the internal parent that leaves the range unjudged even though
    it was loaded and imports nothing of the main module."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nested"),
        "internal/x/x.go": "package x\n\nfunc Unused() {}\n",
        "tools/go.mod": gomod("example.com/nested/tools"),
        "tools/tools.go": "package tools\n",
    })
    assert_golden(out, __file__, "nested_plain")


def test_nested_module_uses_count(run, workdir):
    """CATCHES: a shrink that does not load a nested module that may import the internal package, and so reports
    what that module calls, satisfies through its own interface, passes to an interface, or names in a file its build
    excludes."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nu"),
        "internal/a/a.go": """package a

func Called() {}

func Unused() {}

type Runner struct{}

func (Runner) Run() {}

type Printed struct {
	Field int
}

func NewPrinted() Printed { return Printed{} }

func Tagged() {}
""",
        "tools/go.mod": gomod("example.com/nu/tools", "require example.com/nu v0.0.0\n\nreplace example.com/nu => ../\n"),
        "tools/tagged.go": '//go:build special\n\npackage tools\n\nimport "example.com/nu/internal/a"\n\nfunc init() { a.Tagged() }\n',
        "tools/tools.go": """package tools

import "example.com/nu/internal/a"

type runner interface{ Run() }

func sink(any) {}

func Use() {
	a.Called()
	var r runner = a.Runner{}
	r.Run()
	sink(a.NewPrinted())
}
""",
    })
    assert_golden(out, __file__, "nested_uses")


def test_nested_module_that_does_not_type_check(run, workdir):
    """CATCHES: a nested module with a type error read as one that uses nothing; the range it may import must be
    left unjudged, naming the error."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nb"),
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
        "tools/go.mod": gomod("example.com/nb/tools", "require example.com/nb v0.0.0\n\nreplace example.com/nb => ../\n"),
        "tools/tools.go": 'package tools\n\nimport "example.com/nb/internal/a"\n\nvar _ = a.F\n\nvar _ int = "not an int"\n',
    })
    assert_golden(out, __file__, "nested_broken")


def test_nested_module_with_a_missing_import(run, workdir):
    """CATCHES: a nested module whose own load fails (an import nothing provides) read as one that uses nothing."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nm"),
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
        "tools/go.mod": gomod("example.com/nm/tools"),
        "tools/tools.go": 'package tools\n\nimport _ "example.com/nowhere/pkg"\n',
    })
    assert_golden(out, __file__, "nested_missing_import")


def test_nested_module_reading_the_main_module_elsewhere(run, workdir):
    """CATCHES: a nested module that reads the main module from another directory (a replace outside the tree)
    counted as an importer of this source; the range stays unjudged, naming the directory."""
    out = shrink(run, workdir, {
        "m/go.mod": gomod("example.com/ne"),
        "m/internal/a/a.go": "package a\n\nfunc F() {}\n",
        "m/tools/go.mod": gomod("example.com/ne/tools", "require example.com/ne v0.0.0\n\nreplace example.com/ne => ../../copy\n"),
        "m/tools/tools.go": 'package tools\n\nimport "example.com/ne/internal/a"\n\nvar _ = a.F\n',
        "copy/go.mod": gomod("example.com/ne"),
        "copy/internal/a/a.go": "package a\n\nfunc F() {}\n",
    }, cwd="m")
    assert_golden(out, __file__, "nested_elsewhere")


def test_nested_module_whose_path_lies_above_the_internal_parent(run, workdir):
    """CATCHES: a shrink that only loads nested modules whose path lies inside the internal parent, missing one whose
    path lies above it and whose package may import the internal package."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nan"),
        "tools/go.mod": gomod("example.com/nan/x", "require example.com/nan v0.0.0\n\nreplace example.com/nan => ../\n"),
        "tools/y/z/z.go": 'package z\n\nimport "example.com/nan/x/y/internal/foo"\n\nvar V = foo.Hello()\n',
        "x/y/internal/foo/foo.go": 'package foo\n\nfunc Hello() string { return "hi" }\n\nfunc Bye() {}\n',
    })
    assert_golden(out, __file__, "nested_above")


def test_nested_module_excluded_file_through_compiled_sibling(run, workdir):
    """CATCHES: build-excluded files of a nested module left unread, or read without their compiled siblings, so a
    method they may call through a held value is fixed."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nx"),
        "internal/a/a.go": "package a\n\ntype T struct{}\n\nfunc New() T { return T{} }\n\nfunc (T) Method() int { return 0 }\n\nfunc Unused() {}\n",
        "tools/go.mod": gomod("example.com/nx/tools", "require example.com/nx v0.0.0\n\nreplace example.com/nx => ../\n"),
        "tools/q/q.go": 'package q\n\nimport "example.com/nx/internal/a"\n\nvar v = a.New()\n\nvar _ = v\n',
        "tools/q/q_never.go": "//go:build never\n\npackage q\n\nfunc use() int { return v.Method() }\n",
    })
    assert_golden(out, __file__, "nested_excluded")


def test_nested_module_calls_a_generic_of_the_main_module(run, workdir):
    """CATCHES: a nested module's call of a main-module generic (which its load has only as an import) losing the
    escape inside it, so the field reflection may read is reported."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/ng"),
        "internal/a/a.go": "package a\n\ntype T struct{ Secret int }\n\nfunc Make() T { return T{Secret: 1} }\n\ntype Spare struct{ Free int }\n",
        "internal/q/q.go": "package q\n\nvar sunk []any\n\nfunc Encode[V any](v V) { sunk = append(sunk, v) }\n",
        "tools/go.mod": gomod("example.com/ng/tools", "require example.com/ng v0.0.0\n\nreplace example.com/ng => ../\n"),
        "tools/tools.go": 'package tools\n\nimport (\n\t"example.com/ng/internal/a"\n\t"example.com/ng/internal/q"\n)\n\nfunc Use() { q.Encode(a.Make()) }\n',
    })
    assert_golden(out, __file__, "nested_generic")


def test_nested_module_in_directories_go_skips(run, workdir):
    """CATCHES: nested modules under testdata/ or an _underscore directory overlooked because ./... skips those
    directories: they can still import the internal package, so they are loaded and their uses count."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/tl"),
        "internal/a/a.go": "package a\n\nfunc F() {}\n\nfunc G() {}\n\nfunc H() {}\n",
        "_tools/go.mod": gomod("example.com/tl/_tools", "require example.com/tl v0.0.0\n\nreplace example.com/tl => ../\n"),
        "_tools/tools.go": 'package tools\n\nimport "example.com/tl/internal/a"\n\nvar _ = a.F\n',
        "testdata/gen/go.mod": gomod("example.com/tl/gen", "require example.com/tl v0.0.0\n\nreplace example.com/tl => ../../\n"),
        "testdata/gen/gen.go": 'package gen\n\nimport "example.com/tl/internal/a"\n\nvar _ = a.G\n',
    })
    assert_golden(out, __file__, "nested_skipped_dirs")


def test_nested_module_with_its_own_workspace(run, workdir):
    """CATCHES: a nested module loaded without its own go.work, which is how it reaches the main module its go.mod
    does not require; its use of Foo must count and Bar be judged."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/now"),
        "internal/x/x.go": "package x\n\nfunc Foo() {}\n\nfunc Bar() {}\n",
        "n/go.mod": gomod("example.com/now/n"),
        "n/go.work": "go 1.25\n\nuse (\n\t.\n\t..\n)\n",
        "n/n.go": 'package n\n\nimport "example.com/now/internal/x"\n\nfunc Run() { x.Foo() }\n',
    })
    assert_golden(out, __file__, "nested_own_workspace")


def test_workspace_loads_every_module_and_unlisted_nested_ones(run, workdir):
    """CATCHES: a workspace run that loads only the module holding the working directory, or that loads a nested
    module the go.work does not list through the workspace (where it fails), losing its use of Used."""
    out = shrink(run, workdir, {
        "go.work": "go 1.25\n\nuse (\n\t./m\n\t./other\n)\n",
        "m/go.mod": gomod("example.com/wu"),
        "m/internal/a/a.go": "package a\n\nfunc Used() {}\n\nfunc Unused() {}\n\nfunc FromOther() {}\n",
        "m/tools/go.mod": gomod("example.com/wu/tools", "require example.com/wu v0.0.0\n\nreplace example.com/wu => ../\n"),
        "m/tools/main.go": 'package main\n\nimport "example.com/wu/internal/a"\n\nfunc main() { a.Used() }\n',
        "other/go.mod": gomod("example.com/wuo"),
        "other/o.go": "package o\n",
    }, cwd="m")
    assert_golden(out, __file__, "workspace_unlisted")


def test_workspace_module_importing_another_modules_internal_package(run, workdir):
    """CATCHES: a workspace run that judges each module alone: a main module whose path extends another's may import
    its internal packages, and that use counts."""
    out = shrink(run, workdir, {
        "go.work": "go 1.25\n\nuse (\n\t./core\n\t./core/ext\n)\n",
        "core/go.mod": gomod("example.com/core"),
        "core/internal/a/a.go": "package a\n\nfunc Shared() {}\n\nfunc Alone() {}\n",
        "core/ext/go.mod": gomod("example.com/core/ext"),
        "core/ext/e.go": 'package ext\n\nimport "example.com/core/internal/a"\n\nfunc Run() { a.Shared() }\n',
    }, "./...", cwd="core")
    assert_golden(out, __file__, "workspace_cross")


def test_module_path_running_through_internal(run, workdir):
    """CATCHES: a shrink that judges a package whose internal parent lies above the module (another module may
    import it), or that leaves out of the exposure walk the API such a package hands out."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/x/internal/y"),
        "internal/z/z.go": "package z\n\ntype T struct {\n\tF int\n}\n\nfunc (T) M() {}\n\nfunc Unused() {}\n",
        "y.go": 'package y\n\nimport "example.com/x/internal/y/internal/z"\n\nfunc Get() z.T { return z.T{} }\n\nfunc Own() {}\n',
    })
    assert_golden(out, __file__, "module_under_internal")


BUILD_LIST = {
    "m/a/internal/y/y.go": "package y\n\nfunc Unused() {}\n",
    "m/b/g/g.go": "package g\n",
    "m/b/g/go.mod": gomod("example.com/nbl/b/g", "require (\n\texample.com/nbl v0.0.0\n\texample.com/nbl/b/u v0.0.0\n)\n\n"
                                               "replace (\n\texample.com/nbl => ../../\n\texample.com/nbl/b/u => ../../../u-copy\n)\n"),
    "m/b/g/tagged.go": '//go:build never\n\npackage g\n\nimport "example.com/nbl/b/u"\n\nfunc Run() { u.Run() }\n',
    "m/b/internal/z/z.go": "package z\n\nfunc Baz() {}\n",
    "m/c/internal/w/w.go": "package w\n\nfunc Qux() {}\n",
    "m/go.mod": gomod("example.com/nbl"),
    "m/k/go.mod": gomod("example.com/nbl/k", "require (\n\texample.com/nbl v0.0.0\n\texample.com/nbl/c/v v0.0.0\n)\n\n"
                                           "replace (\n\texample.com/nbl => ../\n\texample.com/nbl/c/v => ../../v-copy\n)\n"),
    "m/k/k.go": 'package k\n\nimport "example.com/nbl/c/v"\n\nfunc Run() { v.Run() }\n',
    "m/s/internal/x/x.go": "package x\n\nfunc Foo() {}\n\nfunc Bar() {}\n",
    "m/s/n/go.mod": gomod("example.com/nbl/s/n", "require (\n\texample.com/nbl v0.0.0\n\texample.com/nbl/s/t v0.0.0\n)\n\n"
                                               "replace (\n\texample.com/nbl => ../../\n\texample.com/nbl/s/t => ../../../t-copy\n)\n"),
    "m/s/n/n.go": 'package n\n\nimport "example.com/nbl/s/t"\n\nfunc Run() { t.Run() }\n',
    "m/s/t/go.mod": gomod("example.com/nbl/s/t"),
    "m/s/t/t.go": "package t\n\nfunc Run() {}\n",
    "t-copy/go.mod": gomod("example.com/nbl/s/t"),
    "t-copy/t.go": 'package t\n\nimport "example.com/nbl/s/internal/x"\n\nfunc Run() { x.Foo() }\n',
    "u-copy/go.mod": gomod("example.com/nbl/b/u"),
    "u-copy/u.go": 'package u\n\nimport "example.com/nbl/b/internal/z"\n\nfunc Run() { z.Baz() }\n',
    "v-copy/go.mod": gomod("example.com/nbl/c/v"),
    "v-copy/v.go": 'package v\n\nimport "example.com/nbl/c/internal/w"\n\nfunc Run() { w.Qux() }\n',
}


def test_nested_build_lists_withhold_fixes_in_reached_ranges(run, workdir):
    """CATCHES: a shrink that ignores the build lists of nested modules: a copy of other source they build (a
    replacement outside the tree, also one only a tag compiles, also for a nested module no internal parent covers)
    whose files import an internal package withholds every fix in that range, while the reports stand."""
    write_files(workdir, BUILD_LIST)
    r = run(["shrink", "-fix"], cwd=workdir / "m")
    out = transcript(r, workdir, ("m/a/internal/y/y.go", "m/s/internal/x/x.go"))
    assert_golden(out, __file__, "nested_build_list")


def test_main_build_list_naming_a_copy_outside_the_tree(run, workdir):
    """CATCHES: a main module whose build list replaces a module of its own path with a directory outside the tree:
    the build compiles that copy, so the range stays unjudged, naming the copy."""
    out = shrink(run, workdir, {
        "m/cmd/c/main.go": 'package main\n\nimport "example.com/blr/ext"\n\nfunc main() { ext.Run() }\n',
        "m/ext/e.go": 'package ext\n\nimport "example.com/blr/internal/a"\n\nfunc Run() { a.New() }\n',
        "m/ext/go.mod": gomod("example.com/blr/ext", "require example.com/blr v0.0.0\n\nreplace example.com/blr => ../\n"),
        "m/go.mod": gomod("example.com/blr", "require example.com/blr/ext v0.0.0\n\nreplace example.com/blr/ext => ../ext-copy\n"),
        "m/internal/a/a.go": "package a\n\nfunc New() {}\n\nfunc Used() {}\n",
        "ext-copy/e.go": 'package ext\n\nimport "example.com/blr/internal/a"\n\nfunc Run() { a.Used() }\n',
        "ext-copy/go.mod": gomod("example.com/blr/ext"),
    }, cwd="m")
    assert_golden(out, __file__, "build_list_replace")


def test_vendored_build_list(run, workdir):
    """CATCHES: vendor mode, where the go command computes no build list, read as no build list at all; the
    vendored copy that uses Old must leave the range unjudged."""
    out = shrink(run, workdir, {
        "cmd/c/main.go": 'package main\n\nimport "example.com/blv/ext"\n\nfunc main() { ext.Run() }\n',
        "go.mod": gomod("example.com/blv", "require example.com/blv/ext v1.0.0\n"),
        "internal/a/a.go": "package a\n\nfunc Old() {}\n",
        "vendor/example.com/blv/ext/e.go": 'package ext\n\nimport "example.com/blv/internal/a"\n\nfunc Run() { a.Old() }\n',
        "vendor/modules.txt": "# example.com/blv/ext v1.0.0\n## explicit; go 1.25\nexample.com/blv/ext\n",
    })
    assert_golden(out, __file__, "vendored")


UNCOVERED_MAIN = {
    "m/go.mod": gomod("example.com/m"),
    "m/internal/a/a.go": "package a\n\nfunc F() {}\n\ntype T struct{ X int }\n",
    "m/tools/t.go": "package tools\n",
}


@pytest.mark.parametrize("name, tools_mod", [
    ("unparsable", "module example.com/other\n\ngo 1.25\n\nbogus directive\n"),
    ("pruned_missing_in_range", "module example.com/other\n\ngo 1.25\n\nrequire example.com/m/ext v1.0.0\n"),
    ("pruned_missing_outside", "module example.com/other\n\ngo 1.25\n\nrequire example.com/zzz/ext v1.0.0\n"),
    ("unpruned_missing", "module example.com/other\n\ngo 1.16\n\nrequire example.com/m/ext v1.0.0\n"),
])
def test_build_list_of_a_nested_module_no_parent_covers(run, workdir, name, tools_mod):
    """CATCHES: a nested module with an unrelated path whose build list is not read, or read wrongly: a go.mod that
    does not parse builds nothing; a pruned go.mod naming a module of the main module's path it cannot fetch withholds
    the fixes in that range; one outside every range is passed over; an unpruned list that cannot be read withholds
    every fix."""
    out = shrink(run, workdir, {**UNCOVERED_MAIN, "m/tools/go.mod": tools_mod}, cwd="m")
    assert_golden(out, __file__, f"uncovered_{name}")


def test_main_build_list_that_cannot_be_read(run, workdir):
    """CATCHES: a main module whose build list cannot be read (a requirement this run cannot fetch) judged anyway:
    every range stays unjudged, naming the failure."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/m", "require example.com/dep v1.0.0\n"),
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
    })
    assert_golden(out, __file__, "main_build_list_unreadable")


NESTED_ABOVE_BROKEN = {
    "go.mod": gomod("example.com/nan"),
    "x/y/internal/foo/foo.go": "package foo\n\nfunc Bye() {}\n",
    "tools/go.mod": gomod("example.com/nan/x"),
    "tools/t.go": 'package tools\n\nimport _ "example.com/nowhere/p"\n',
}


@pytest.mark.parametrize("name, extra", [
    ("no_directory", {}),
    ("directory", {"tools/y/y.go": "package y\n"}),
    ("own_module", {"tools/y/y.go": "package y\n", "tools/y/go.mod": gomod("example.com/nan/x/y")}),
    ("file", {"tools/y": "not a directory\n"}),
])
def test_failed_nested_module_above_the_parent(run, workdir, name, extra):
    """CATCHES: a failed nested module whose path lies above an internal parent that unjudges the range whatever its
    directory holds: only a directory where the parent's package would sit, outside any further module, can hold a
    package that imports it."""
    assert_golden(shrink(run, workdir, {**NESTED_ABOVE_BROKEN, **extra}), __file__, f"above_broken_{name}")


@pytest.mark.parametrize("name, imported", [("nested_module", "example.com/other/x"), ("nowhere", "example.com/zzz/x")])
def test_excluded_file_importing_a_package_this_run_did_not_load(run, workdir, name, imported):
    """CATCHES: a build-excluded file importing a package of a module this run reads but did not load (it may depend on
    anything, so fields and methods lose their fix) treated like one importing a package outside every module (which
    cannot reach an internal package)."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/m"),
        "internal/a/a.go": "package a\n\ntype T struct{ F int }\n\nfunc (T) M() {}\n\nfunc New() T { return T{} }\n",
        "other/go.mod": gomod("example.com/other"),
        "other/x/x.go": "package x\n",
        "c/c_never.go": f'//go:build never\n\npackage c\n\nimport "{imported}"\n\nvar _ = x.Y\n',
    })
    assert_golden(out, __file__, f"excluded_import_{name}")


def test_copy_imports_only_from_places_its_build_skips(run, workdir):
    """CATCHES: a copy of other source scanned for internal imports in places its build never compiles (vendor/, a
    module of its own, a file whose imports do not parse), withholding a fix nothing can break."""
    out = shrink(run, workdir, {
        "m/go.mod": gomod("example.com/nbl"),
        "m/s/internal/x/x.go": "package x\n\nfunc Foo() {}\n",
        "m/s/n/go.mod": gomod("example.com/nbl/s/n", "require (\n\texample.com/nbl v0.0.0\n\texample.com/nbl/s/t v0.0.0\n)\n\n"
                                                   "replace (\n\texample.com/nbl => ../../\n\texample.com/nbl/s/t => ../../../copy\n)\n"),
        "m/s/n/n.go": 'package n\n\nimport "example.com/nbl/s/t"\n\nfunc Run() { t.Run() }\n',
        "copy/go.mod": gomod("example.com/nbl/s/t"),
        "copy/t.go": "package t\n\nfunc Run() {}\n",
        "copy/vendor/v/v.go": 'package v\n\nimport "example.com/nbl/s/internal/x"\n\nvar _ = x.Foo\n',
        "copy/sub/go.mod": gomod("example.com/nbl/s/t/sub"),
        "copy/sub/sub.go": 'package sub\n\nimport "example.com/nbl/s/internal/x"\n\nvar _ = x.Foo\n',
        "copy/bad/bad.go": 'package bad\n\nimport (\n\t"example.com/nbl/s/internal/x"\n\nfunc\n',
    }, cwd="m")
    assert_golden(out, __file__, "copy_skipped_places")


def test_vendor_directory_without_modules_txt(run, workdir):
    """CATCHES: a vendor directory with no modules.txt read as vendoring something, or as an unreadable build list."""
    out = shrink(run, workdir, {"go.mod": gomod("example.com/m"), "internal/a/a.go": "package a\n\nfunc F() {}\n",
                                "vendor/README": "nothing vendored\n"})
    assert_golden(out, __file__, "vendor_without_modules_txt")


def test_workspace_vendor_directory(run, workdir):
    """CATCHES: a workspace's vendor directory (beside go.work, not the module) left unread, so the vendored copy
    that uses Old does not leave the range unjudged."""
    out = shrink(run, workdir, {
        "go.work": "go 1.25\n\nuse ./m\n",
        "m/go.mod": gomod("example.com/blv", "require example.com/blv/ext v1.0.0\n"),
        "m/internal/a/a.go": "package a\n\nfunc Old() {}\n",
        "m/cmd/c/main.go": 'package main\n\nimport "example.com/blv/ext"\n\nfunc main() { ext.Run() }\n',
        "vendor/example.com/blv/ext/e.go": 'package ext\n\nimport "example.com/blv/internal/a"\n\nfunc Run() { a.Old() }\n',
        "vendor/modules.txt": "## workspace\n# example.com/blv/ext v1.0.0\n## explicit; go 1.25\nexample.com/blv/ext\n",
    }, cwd="m")
    assert_golden(out, __file__, "workspace_vendor")


def test_nested_module_importing_a_tested_package(run, workdir):
    """CATCHES: a nested module's load that reads the main package's test variant (or its test main) as what the nested
    module imports, failing or double-counting; Called stays used and Unused is judged."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nu"),
        "internal/a/a.go": "package a\n\nfunc Called() {}\n\nfunc Unused() {}\n",
        "internal/a/a_test.go": 'package a\n\nimport "testing"\n\nfunc TestCalled(t *testing.T) { Called() }\n',
        "tools/go.mod": gomod("example.com/nu/tools", "require example.com/nu v0.0.0\n\nreplace example.com/nu => ../\n"),
        "tools/tools.go": 'package tools\n\nimport "example.com/nu/internal/a"\n\nfunc Use() { a.Called() }\n',
    })
    assert_golden(out, __file__, "nested_tested_import")


def test_nested_module_with_an_unparsable_excluded_file(run, workdir):
    """CATCHES: a nested module's build-excluded file that does not parse skipped silently; its uses are unknown, so
    the range it may import stays unjudged, naming the file."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/nu"),
        "internal/a/a.go": "package a\n\nfunc Called() {}\n",
        "tools/go.mod": gomod("example.com/nu/tools", "require example.com/nu v0.0.0\n\nreplace example.com/nu => ../\n"),
        "tools/tools.go": 'package tools\n\nimport "example.com/nu/internal/a"\n\nfunc Use() { a.Called() }\n',
        "tools/bad_never.go": "//go:build never\n\npackage tools\n\nfunc (\n",
    })
    assert_golden(out, __file__, "nested_excluded_unparsable")


def test_go_command_that_cannot_list(run, workdir):
    """CATCHES: a go command that cannot list the packages at all (GOFLAGS=-mod=bogus) read as a module with nothing
    in it, instead of stopping with the go command's error."""
    out = shrink(run, workdir, {"go.mod": gomod("example.com/m"), "internal/a/a.go": "package a\n\nfunc F() {}\n"},
                 env={"GOFLAGS": "-mod=bogus"})
    assert_golden(out, __file__, "mod_bogus")


def test_real_main_package_ending_in_dot_test(run, workdir):
    """CATCHES: a real package main whose import path ends in .test mistaken for the synthetic test main and dropped,
    or judged; it is named as package main."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/m"),
        "internal/tool.test/main.go": "package main\n\nfunc Exported() {}\n\nfunc main() {}\n",
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
    })
    assert_golden(out, __file__, "dot_test_main")


def test_package_named_under_testdata(run, workdir):
    """CATCHES: an internal package named explicitly though ./... leaves it out (under testdata) judged with none of
    its uses read, instead of being named as not judged."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/m"),
        "internal/a/a.go": "package a\n\nfunc F() {}\n",
        "internal/a/testdata/fixture/f.go": "package fixture\n\nfunc G() {}\n",
    }, "./internal/a/testdata/fixture", "./internal/a")
    assert_golden(out, __file__, "testdata_named")


def test_package_with_assembly_for_this_build(run, workdir):
    """CATCHES: a package holding assembly that every architecture assembles (it may name any symbol) judged anyway;
    one for another architecture only is named the same."""
    out = shrink(run, workdir, {
        "go.mod": gomod("example.com/m"),
        "internal/asm/asm.go": "package asm\n\nfunc Unused() {}\n",
        "internal/asm/asm.s": "// An empty assembly file.\n",
        "internal/crc/crc.go": "package crc\n\nvar Table = 1\n",
        "internal/crc/crc_s390x.s": "// Assembly for s390x only.\n",
        "internal/plain/plain.go": "package plain\n\nfunc Unused() {}\n",
    })
    assert_golden(out, __file__, "assembly")


def test_nested_build_list_names_a_module_outside_the_range(run, workdir):
    """CATCHES: a module a nested build list names that lies in the main module's path but outside the internal
    parent's tree withholding that range's fixes anyway."""
    out = shrink(run, workdir, {
        "m/go.mod": gomod("example.com/m"),
        "m/sub/internal/a/a.go": "package a\n\nfunc F() {}\n",
        "m/tools/go.mod": gomod("example.com/other", "require example.com/m/elsewhere v1.0.0\n"),
        "m/tools/t.go": "package tools\n",
    }, cwd="m")
    assert_golden(out, __file__, "nested_list_outside_range")


@pytest.mark.parametrize("name, path", [("uncovered", "example.com/other"), ("covered", "example.com/m/tools")])
def test_nested_module_whose_go_mod_needs_updates(run, workdir, name, path):
    """CATCHES: a nested module whose go.mod lacks a requirement its dependency raises read through go list -m -e all
    (which quietly lists the graph a tidy go.mod would hold) instead of being treated as a build list nobody can read."""
    out = shrink(run, workdir, {
        "m/go.mod": gomod("example.com/m"),
        "m/internal/a/a.go": "package a\n\nfunc F() {}\n",
        "m/tools/go.mod": gomod(path, "require (\n\texample.com/x v1.0.0\n\texample.com/y v1.0.0\n)\n\n"
                                      "replace (\n\texample.com/x => ../../x\n\texample.com/y => ../../y\n)\n"),
        "m/tools/t.go": 'package tools\n\nimport "example.com/x"\n\nvar _ = x.X\n',
        "x/go.mod": gomod("example.com/x", "require example.com/y v1.1.0\n"),
        "x/x.go": 'package x\n\nimport "example.com/y"\n\nvar X = y.Y\n',
        "y/go.mod": gomod("example.com/y"),
        "y/y.go": "package y\n\nvar Y = 1\n",
    }, cwd="m")
    assert_golden(out, __file__, f"untidy_{name}")
