"""What declscope shrink counts as a use from outside a package: each way another package can reach an exported
declaration without the analyzer's single-package view seeing it."""

from conftest import assert_golden, gomod, transcript, write_files

MOD = "example.com/uses"


def shrink(run, workdir, files, *args):
    write_files(workdir, {"go.mod": gomod(MOD), **files})
    return transcript(run(["shrink", *args]), workdir)


def test_unkeyed_literal_through_pointers_uses_every_field(run, workdir):
    """CATCHES: an implementation that counts only spelled field names, and so reports the fields another
    package writes by position, through &T{...}, a defined pointer type, or a type parameter's pointer."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Point struct{ X, Y int }

type NamedPoint struct{ X, Y int }

type NamedPointPtr *NamedPoint

type ParamPoint struct{ X, Y int }

type Keyed struct{ X, Y int }
""",
        "b/b.go": """package b

import "example.com/uses/internal/a"

var (
	_ = &a.Point{1, 2}
	_ = []a.NamedPointPtr{{1, 2}}
	_ = bParamPoints[*a.ParamPoint]
	_ = a.Keyed{X: 1}
)

func bParamPoints[P interface{ *a.ParamPoint }]() []P { return []P{{1, 2}} }
""",
    })
    assert_golden(out, __file__, "unkeyed")


def test_struct_conversions_pair_fields_by_name(run, workdir):
    """CATCHES: a shrink that reports the fields a struct conversion pairs by name (Right(Left{}), pointer
    conversions, a conversion to an unnamed struct, or through a type parameter), or that counts a conversion of a
    struct to itself as pairing anything."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Left struct {
	X int
}

type Right struct {
	X int
}

var (
	_ = Right(Left{})
	_ = (*Right)(&Left{})
)

type Solo struct {
	X int
}

var (
	_ = Solo(Solo{})
	_ = struct{ X int }(Solo{})
)

type Self struct {
	Z int
}

var _ = Self(Self{})

type ParamLeft struct {
	W int
}

type ParamRight struct {
	W int
}

func toParam[P ~*ParamRight](l *ParamLeft) P { return P(l) }

var _ = toParam[*ParamRight]
""",
    })
    assert_golden(out, __file__, "conversions")


def test_unnamed_struct_identical_to_a_named_one_pairs_its_fields(run, workdir):
    """CATCHES: a shrink that misses an unnamed struct type written somewhere (a variable, a parameter of a
    function, inside a slice or map) identical to a named struct: assignment between them needs the field names."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Opts struct {
	Depth int
	Name  string
}

type Pair struct {
	K int
}

type Alone struct {
	Q int
}

var _ = Alone{}.Q
""",
        "b/b.go": """package b

func Take(o struct {
	Depth int
	Name  string
}) {
}

var Table map[string][]struct{ K int }
""",
    })
    assert_golden(out, __file__, "unnamed_structs")


def test_linkname_pulls_declarations_by_import_path(run, workdir):
    """CATCHES: a shrink that ignores //go:linkname in another package, so it reports and would rename a function
    or a method (T.M and (*T).M forms) the linker pulls by name."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

func Linked() int { return 1 }

type ByValue struct{}

func (ByValue) Pulled() {}

type ByPointer struct{}

func (*ByPointer) Pulled() {}

func NotLinked() {}
""",
        "b/b.go": """package b

import (
	_ "unsafe"

	_ "example.com/uses/internal/a"
)

//go:linkname linked example.com/uses/internal/a.Linked
func linked() int

//go:linkname byValue example.com/uses/internal/a.ByValue.Pulled
func byValue()

//go:linkname byPointer example.com/uses/internal/a.(*ByPointer).Pulled
func byPointer()

//go:linkname nodot nodot
func nodot()

//go:linkname missing example.com/uses/internal/a.Missing
func missing()

var _, _, _, _, _ = linked, byValue, byPointer, nodot, missing
""",
    })
    assert_golden(out, __file__, "linkname")


def test_static_interface_satisfaction_uses_the_method(run, workdir):
    """CATCHES: a shrink that reports a method needed to satisfy an interface at an assignment or a type
    parameter's constraint, which no selector names; the types themselves are still reported."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type writer interface{ Write(p []byte) (int, error) }

type Wr struct{}

func (Wr) Write(p []byte) (int, error) { return len(p), nil }

var _ writer = Wr{}

type stringer interface{ String() string }

type Label struct{}

func (Label) String() string { return "" }

func show[T stringer](v T) string { return v.String() }

var _ = show[Label]

type Idle struct{}

func (Idle) Spin() {}
""",
    })
    assert_golden(out, __file__, "satisfaction")


def test_value_handed_out_by_an_importable_package_is_exposed(run, workdir):
    """CATCHES: a shrink that forgets another module can call methods and read fields of a value an importable
    package hands out (a result, an embedded type, an interface's result, a variable), or that also counts the
    unexported members and the importable package's own external test."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Exposed struct {
	F int
}

func (Exposed) M() {}

type Promoted struct {
	Via int
}

func (Promoted) Call() {}

type Inner struct{}

type Outer struct{ Inner }

type Out struct {
	Field int
}

func (Out) Method() {}

type Kept struct {
	hidden int
}

func (Kept) secret() {}

var (
	_ = Kept{}.hidden
	_ = Kept{}.secret
)

type Private struct {
	Unseen int
}
""",
        "pub/pub.go": """package pub

import "example.com/uses/internal/a"

func Unused() {}

func Get() a.Exposed { return a.Exposed{} }

type Wrapper struct{ a.Promoted }

func GetWrapper() Wrapper { return Wrapper{} }

func GetOuter() a.Outer { return a.Outer{} }

type Iface interface{ Get() a.Out }

var K a.Kept

func private() a.Private { return a.Private{} }

var _ = private
""",
    })
    assert_golden(out, __file__, "exposure")


def test_package_main_under_internal_is_an_exposure_root(run, workdir):
    """CATCHES: a shrink that judges package main under internal/ (a plugin host looks its symbols up), or that
    forgets the values main's exported variables hold are reachable from it."""
    out = shrink(run, workdir, {
        "internal/plug/plug.go": "package plug\n\ntype Plug struct {\n\tF int\n}\n\nfunc (Plug) M() {}\n\nfunc Lone() {}\n",
        "internal/tool/main.go": """package main

import "example.com/uses/internal/plug"

var V plug.Plug

func Plugged() {}

func main() {}
""",
    })
    assert_golden(out, __file__, "plugin_main")


def test_type_carried_by_a_used_api_is_used(run, workdir):
    """CATCHES: a shrink that reports a type another package only holds through a function's result (or an
    alias of a generic instance), so that the fix would leave a caller unable to name what it holds."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Made struct {
	V int
}

func Make() Made { return Made{} }

type Handle = generic[int]

type generic[T any] struct{ v T }

func MakeHandle() *Handle { return &Handle{} }

type Spelled struct{}

func (Spelled) Build() *Product { return nil }

type Product struct{}

var _ = Spelled{}.Build
""",
        "b/b.go": """package b

import "example.com/uses/internal/a"

var (
	_ = a.Make()
	_ = a.MakeHandle()
	_ a.Spelled
)
""",
    })
    assert_golden(out, __file__, "carried")


def test_external_tests_alone_keep_a_name_without_a_fix(run, workdir):
    """CATCHES: a shrink that treats a use from the package's external tests as a use from outside (no report),
    or that offers a fix that would break those tests; also one that reports the export_test.go idiom."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

var OnlyExtTest = 1

type Ext struct {
	A int
}

func Shown() {}

func parse() int { return 2 }
""",
        "internal/a/export_test.go": "package a\n\nvar ParseForTest = parse\n",
        "internal/a/x_test.go": """package a_test

import (
	"testing"

	"example.com/uses/internal/a"
)

func TestX(t *testing.T) { _ = a.OnlyExtTest + a.Ext{1}.A + a.ParseForTest() }

func ExampleShown() {}
""",
    })
    assert_golden(out, __file__, "external_tests")


def test_build_excluded_file_of_another_package(run, workdir):
    """CATCHES: a shrink that reads only compiled files: a name a build-excluded file writes as pkg.Name (also
    through an import bound to the package's own name) is a use, and a field or method it may reach through a value
    keeps its report but loses its fix."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Made struct {
	V int
}

func Make() Made { return Made{} }

func Unnamed() {}
""",
        "internal/q/q.go": "package q\n\nvar ExclQual = 1\n",
        "internal/go-foo/foo.go": "package foo\n\nfunc Foo() {}\n\nfunc Bar() {}\n",
        "b/b.go": 'package b\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.Make()\n',
        "b/b_never.go": """//go:build never

package b

import (
	"example.com/uses/internal/go-foo"
	"example.com/uses/internal/q"
)

var _ = q.ExclQual

var _ = foo.Foo
""",
    })
    assert_golden(out, __file__, "excluded_other")


def test_ignored_and_testdata_directories_are_not_read(run, workdir):
    """CATCHES: a shrink that counts uses in files ./... never builds (testdata, _dirs, .dirs, vendor, or a
    directory a go.mod ignore directive names) as uses of the module's packages."""
    write_files(workdir, {
        "go.mod": gomod(MOD, "ignore (\n\t./gen\n\tscratch\n)\n"),
        "internal/a/a.go": "package a\n\nfunc A() {}\n\nfunc B() {}\n\nfunc C() {}\n\nfunc D() {}\n\nfunc E() {}\n",
        "testdata/t/t.go": 'package t\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.A\n',
        "_skip/s/s.go": 'package s\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.B\n',
        "gen/g/g.go": 'package g\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.C\n',
        "deep/scratch/s.go": 'package s\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.D\n',
        "b/b_never.go": '//go:build never\n\npackage b\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.E\n',
    })
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "unread_dirs")


def test_dot_imported_name_in_excluded_file(run, workdir):
    """CATCHES: a shrink that only reads pkg.Name selections in build-excluded files and misses a bare name under
    a dot import, which keeps the report but must withhold the fix; a name written nowhere stays fixable."""
    out = shrink(run, workdir, {
        "internal/y/y.go": "package y\n\nvar Dotted = 1\n\nfunc Unnamed() {}\n",
        "internal/u/u.go": "package u\n",
        "internal/u/u_never.go": '//go:build never\n\npackage u\n\nimport . "example.com/uses/internal/y"\n\nvar _ = Dotted\n',
    })
    assert_golden(out, __file__, "dot_import")


def test_generic_alias_and_labels(run, workdir):
    """CATCHES: a shrink that fails on an instantiated generic alias (which has no type parameters of a named type to
    read), or that judges a function's exported label as a declaration that may carry a type."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Pair[T any] = struct{ L, R T }

var Kept Pair[int]

func Loop() int {
Outer:
	for {
		break Outer
	}
	return Kept.L
}
""",
        "b/b.go": 'package b\n\nimport "example.com/uses/internal/a"\n\nvar _ = a.Loop()\n',
    })
    assert_golden(out, __file__, "alias_and_label")


def test_external_test_of_an_importable_package_is_no_exposure_root(run, workdir):
    """CATCHES: an exposure walk that starts from the external test package of an importable package (nothing imports
    it), so a type only that test holds counts as reachable by another module."""
    out = shrink(run, workdir, {
        "internal/a/a.go": "package a\n\ntype Seen struct{ F int }\n\ntype OnlyTest struct{ G int }\n",
        "pub/pub.go": 'package pub\n\nimport "example.com/uses/internal/a"\n\nfunc Get() a.Seen { return a.Seen{} }\n',
        "pub/pub_test.go": 'package pub_test\n\nimport "example.com/uses/internal/a"\n\nvar Held a.OnlyTest\n',
    })
    assert_golden(out, __file__, "pub_external_test")
