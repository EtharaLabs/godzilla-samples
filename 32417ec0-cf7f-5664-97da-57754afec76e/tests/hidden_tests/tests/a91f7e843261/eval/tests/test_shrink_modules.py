"""declscope shrink over whole modules: which exported declarations of internal/ packages no importer uses.

Each module is laid out in the work directory, with any sibling directory it replaces a module with. The
report records the shrink run, the shrink -fix run, every file of the module tree afterwards, and the shrink
run that follows.
"""

from conftest import read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


def shrink_report(ds, workdir, root, env=None):
    report = ds(["shrink"], cwd=root, env_overrides=env)
    fix = ds(["shrink", "-fix"], cwd=root, env_overrides=env)
    tree = snapshot_tree(workdir)
    after = ds(["shrink"], cwd=root, env_overrides=env)
    return "\n".join([
        "## shrink", report.transcript,
        "## shrink -fix", fix.transcript,
        "## tree after shrink -fix", tree,
        "## shrink after -fix", after.transcript,
    ])


MOD_USES = {
    'uses/b/b.go': """package b

import (
	_ "unsafe"

	"example.com/uses/internal/a"
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

var (
	_, _, _, _, _ = linked, byValue, byPointer, nodot, missing
	_             = &a.Point{1, 2}
	_             = []a.NamedPointPtr{{1, 2}}
	_             = bParamPoints[*a.ParamPoint]
	_             = a.Make()
	_             = a.MakeHandle()
	_             a.Spelled2
)

func bParamPoints[P interface{ *a.ParamPoint }]() []P { return []P{{1, 2}} }

func init() { a.Spelled() }
""",
    'uses/b/b_never.go': """//go:build never

package b

import (
	"example.com/uses/internal/go-foo"
	"example.com/uses/internal/q"
)

var _ = q.ExclQual

var _ = foo.Foo
""",
    'uses/go.mod': """module example.com/uses

go 1.25
""",
    'uses/internal/a/a.go': """// Package a is judged. Each exported declaration here is used from outside the
// package in one way, and is not reported, unless a want comment says so.
package a

import (
	"fmt"
	"io"
)

// Spelled is named by package b.
func Spelled() {}

// Point is written unkeyed by package b, through a pointer, which b can only
// while every field is exported.
type Point struct{ X, Y int }

// Left and Right are converted into each other, which pairs X by name. The
// type names themselves are free to go.
type Left struct { // want: type Left is exported, but nothing.*uses it$
	X int
}

type Right struct { // want: type Right is exported, but nothing.*uses it$
	X int
}

var (
	_ = Right(Left{})
	_ = (*Right)(&Left{})
)

// Solo is converted to itself, which pairs nothing, and to an unnamed struct,
// which pairs X with the unnamed struct's field.
type Solo struct { // want: type Solo is exported, but nothing.*uses it$
	X int
}

var (
	_ = Solo(Solo{})
	_ = struct{ X int }(Solo{})
)

// NamedPoint and ParamPoint are written unkeyed by package b, through a
// defined pointer type and through a type parameter allowing only a pointer.
// The pointer is left out of the literal both times.
type NamedPoint struct{ X, Y int }

type NamedPointPtr *NamedPoint

type ParamPoint struct{ X, Y int }

// ParamLeft is converted to a type parameter allowing only *ParamRight, which
// pairs W by name as (*ParamRight)(l) does. No unnamed struct here has a
// field W, so nothing else pairs it.
type ParamLeft struct { // want: type ParamLeft is exported, but nothing.*uses it$
	W int
}

type ParamRight struct { // want: type ParamRight is exported, but nothing.*uses it$
	W int
}

func toParam[P ~*ParamRight](l *ParamLeft) P { return P(l) }

var _ = toParam[*ParamRight]

// Linked is pulled by a //go:linkname in package b.
func Linked() int { return 1 }

// ByValue and ByPointer have methods pulled as T.M and (*T).M, which spell
// the type as well.
type ByValue struct{}

func (ByValue) Pulled() {}

type ByPointer struct{}

func (*ByPointer) Pulled() {}

// Wr satisfies io.Writer where the compiler checks it, so Write is used.
type Wr struct{} // want: type Wr is exported, but nothing.*uses it$

func (Wr) Write(p []byte) (int, error) { return len(p), nil }

var _ io.Writer = Wr{}

// Label's String satisfies the constraint of show, instantiated with Label.
type Label struct{} // want: type Label is exported, but nothing.*uses it$

func (Label) String() string { return "" }

func show[T fmt.Stringer](v T) string { return v.String() }

var _ = show[Label]

// Exposed is handed out by pub.Get, so another module can call M and read F
// on a value of it without naming the type.
type Exposed struct {
	F int
}

func (Exposed) M() {}

// Promoted is embedded by pub.Wrapper, which pub hands out.
type Promoted struct {
	Via int
}

func (Promoted) Call() {}

// Inner is embedded in Outer, which pub hands out, so another module selects
// v.Inner by the type's name.
type Inner struct{}

type Outer struct{ Inner }

// Out is what the method of pub.Iface returns.
type Out struct {
	Field int
}

func (Out) Method() {}

// Kept is held by pub.K, but its unexported field and method are no part of
// what another module can reach.
type Kept struct {
	hidden int
}

func (Kept) secret() {}

var (
	_ = Kept{}.hidden
	_ = Kept{}.secret
)

// Made is returned by Make, which package b calls. b holds a Made without
// naming it, and must still be able to name it. V is not fixed: b/b_never.go
// may read it through a Made that b.go holds.
type Made struct {
	V int // want: field V is exported.*no fix: a build-excluded file of another package may use it
}

func Make() Made { return Made{} }

// Handle is an alias, returned by MakeHandle, which package b calls. The
// alias is the name b would write, so it is carried like a defined type.
type Handle = generic[int]

type generic[T any] struct{ v T }

func MakeHandle() *Handle { return &Handle{} }

// Spelled2 is named by package b, but its method Build is not. Build is
// reported, but not fixed, for the same reason as Made.V, so Product, which
// Build returns, stays carried by it and is not reported.
type Spelled2 struct{}

func (Spelled2) Build() *Product { return nil } // want: method Build is exported.*no fix: a build-excluded file of another package may use it

type Product struct{}

var _ = Spelled2{}.Build

// OnlyExtTest, Ext and Shown are used by the external tests alone.
var OnlyExtTest = 1 // want: var OnlyExtTest is exported, but only the external tests.*no fix: external tests use it

type Ext struct { // want: type Ext is exported, but only the external tests.*no fix: external tests use it
	A int // want: field A is exported, but only the external tests.*no fix: external tests use it
}

func Shown() {} // want: func Shown is exported, but only the external tests.*no fix: external tests use it

func parse() int { return 2 }
""",
    'uses/internal/a/export_test.go': """package a

// The export_test.go idiom: exported for the external tests alone, which is
// its job, so nothing is said.
var ParseForTest = parse
""",
    'uses/internal/a/x_test.go': """package a_test

import (
	"testing"

	"example.com/uses/internal/a"
)

func TestX(t *testing.T) { _ = a.OnlyExtTest + a.Ext{1}.A + a.ParseForTest() }

// ExampleShown names Shown, which go vet checks.
func ExampleShown() {}
""",
    'uses/internal/go-foo/foo.go': """// Package foo lives in go-foo, so an import of it with no name of its own
// binds foo. Foo is used under that name by a build-excluded file.
package foo

func Foo() {}
""",
    'uses/internal/plug/plug.go': """// Package plug is held by a variable of package main, which a plugin host
// looks up, so Plug's method and field are used there.
package plug

type Plug struct {
	F int
}

func (Plug) M() {}
""",
    'uses/internal/q/q.go': """// Package q is imported by a build-excluded file of package b. It holds a
// package-level name alone: any field or method would be held back by that
// import, which is not what this module pins.
package q

// ExclQual is named only by the build-excluded file.
var ExclQual = 1
""",
    'uses/internal/tool/main.go': """// Package main is an exposure root though it sits under internal/, since a
// plugin host looks its exported symbols up. It is itself never judged.
package main

import "example.com/uses/internal/plug"

var V plug.Plug

func main() {}
""",
    'uses/pub/pub.go': """// Package pub is importable by other modules. Its exported API is where the
// exposure walk starts.
package pub

import "example.com/uses/internal/a"

// Unused is exported and unused, but outside internal/, so another module may
// import it and nothing is said.
func Unused() {}

func Get() a.Exposed { return a.Exposed{} }

type Wrapper struct{ a.Promoted }

func GetWrapper() Wrapper { return Wrapper{} }

func GetOuter() a.Outer { return a.Outer{} }

type Iface interface{ Get() a.Out }

var K a.Kept
""",
    'uses/pub/pub_test.go': """// An external test package is imported by nothing, so it is no root of the
// exposure walk.
package pub_test

import "example.com/uses/pub"

var _ = pub.K
""",
    'uses/testdata/other/go.mod': """// A nested module with an unrelated path cannot import internal/a, so it
// keeps nothing unjudged.
module example.com/unrelated

go 1.25
""",
    'uses/testdata/other/other.go': """package other
""",
}

MOD_ESCAPES = {
    'escapes/go.mod': """module example.com/escapes

go 1.25
""",
    'escapes/internal/e/e.go': """// Package e holds values that escape into an interface, where fmt,
// encoding/json and reflect find methods and fields at run time. An escape is
// a use, so none of them is reported. So is a struct tag, which declares one.
package e

import (
	"encoding/json"
	"fmt"
	"io"
	"sync/atomic"
)

// Printed escapes through fmt.Println, behind a pointer.
type Printed struct {
	Field int
}

func (Printed) Method() {}

func printed() { fmt.Println(&Printed{}) }

// Wire shares Record's struct, so json.Marshal(Wire(r)) reads Record's
// fields under either name. Record's own name is not read, and is reported.
type Record struct { // want: type Record is exported, but nothing.*uses it$
	Name string
}

type Wire Record

func encode(r Record) ([]byte, error) { return json.Marshal(Wire(r)) }

// Shown reaches fmt.Println inside show[Shown], a generic of the module that
// is instantiated with it.
type Shown struct{}

func show[T any](v T) { fmt.Println(v) }

func useShown() { show(Shown{}) }

// Held is a type argument of sync/atomic.Pointer, a generic declared outside
// the module whose body is not built here, so it is taken to escape.
type Held struct{}

var _ atomic.Pointer[Held]

// Bag escapes, and reaches Elem through every kind of container and through
// an instantiation.
type Bag struct {
	S []Elem
	R [1]Elem
	C chan Elem
	M map[Elem]Elem
	G Gen[Elem]
}

type Elem struct{}

type Gen[T any] struct{ v T }

func bag() { fmt.Println(Bag{}) }

// Carrier escapes, and its field of function type hands out a Result, whose
// field reflection reaches by calling it.
type Carrier struct {
	Make func() Result
}

type Result struct {
	Value int
}

func carry() { fmt.Println(Carrier{}) }

// Wr satisfies io.Writer only in a check that makes no value at run time,
// which is no escape.
type Wr struct{} // want: type Wr is exported, but nothing.*uses it$

func (Wr) Write(p []byte) (int, error) { return len(p), nil }

var _ io.Writer = Wr{}

// Tagged is never converted to an interface here, but its struct tags say a
// marshaller reads it through reflection, so it escapes: its untagged field
// too, which encoding/json would drop once unexported. go vet also rejects a
// json tag on an unexported field. An empty tag declares nothing, and Bare
// is reported.
type Tagged struct {
	Name  string `json:"name"`
	Count int    `xml:"count"`
	Plain int
}

type Bare struct { // want: type Bare is exported, but nothing.*uses it$
	Field int `` // want: field Field is exported, but nothing.*uses it$
}

var _ = Bare{}.Field

// Config's only tag is on a field of a struct it holds without naming it,
// which a marshaller reads with Config.
type Config struct {
	Server struct {
		Port int `yaml:"port"`
	}
}

// Conf names a tagged struct through an alias, which is no name of its own,
// so Relay, holding a Conf, escapes as Config does. Relay keeps Conf.
type Conf = struct { // want: type Conf is exported.*no fix: an exported declaration that keeps its name hands it out
	Port int `yaml:"port"`
}

type Relay struct {
	Server Conf
}

var _ = Config{}.Server.Port + Relay{}.Server.Port

var _ = Tagged{}.Name + fmt.Sprint(Tagged{}.Count, Tagged{}.Plain)

// Dead is converted only in a function literal that never runs, which is no
// escape either.
type Dead struct{} // want: type Dead is exported, but nothing.*uses it$

var _ = func() { fmt.Println(Dead{}) }

var _, _, _, _, _, _, _ = printed, encode, useShown, bag, carry, Gen[int]{}.v, failed

// Failed escapes holding an error. The predeclared error has no position,
// so its key is "", which no reader looks up.
type Failed struct{ Err error }

func failed() { fmt.Println(Failed{}) }
""",
}

MOD_GENERIC_VARIANT = {
    'generic-variant/cmd/gv/main.go': """package main

import (
	"fmt"

	"example.com/gv/internal/p"
	"example.com/gv/internal/q"
	"example.com/gv/internal/s"
)

func main() {
	fmt.Println(q.Encode(p.Make()))
	fmt.Println(s.Wrap(p.MakeU()))
}
""",
    'generic-variant/go.mod': """module example.com/gv

go 1.25
""",
    'generic-variant/internal/p/p.go': """// Package p holds values that escape into json.Marshal inside q.Encode, a
// generic of the module. cmd/gv calls it through the variant of q without
// its tests, which is not the variant read, so SSA has no body for the
// instance. The escape still counts, and neither field is reported.
package p

type T struct{ Secret int }

func Make() T { return T{Secret: 1} }

// U reaches q.Encode only through s.Wrap, whose own instance has a body.
type U struct{ Hidden int }

func MakeU() U { return U{Hidden: 1} }
""",
    'generic-variant/internal/q/q.go': """// Package q has a test, so the variant read is q with its test, not the one
// cmd/gv imports.
package q

import "encoding/json"

func Encode[V any](v V) string {
	b, _ := json.Marshal(v)
	return string(b)
}
""",
    'generic-variant/internal/q/q_test.go': """package q

import "testing"

func TestEncode(t *testing.T) { _ = Encode(1) }
""",
    'generic-variant/internal/s/s.go': """// Package s has no test, so its variant read is the one cmd/gv imports, and
// SSA builds Wrap's instance. The call to q.Encode inside it still goes to
// the variant of q without its tests, and is given a type parameter, which
// names no type of p.
package s

import "example.com/gv/internal/q"

func Wrap[V any](v V) string { return q.Encode(v) }
""",
}

MOD_NESTED_MODULE_GENERIC = {
    'nested-module-generic/go.mod': """module example.com/ng

go 1.25
""",
    'nested-module-generic/internal/a/a.go': """// Package a holds a value that the nested module in tools passes to
// q.Encode, a generic of this module. The nested module's load has q only
// as an import, which SSA builds no body for. The escape still counts, and
// Secret is not reported.
package a

type T struct{ Secret int }

func Make() T { return T{Secret: 1} }
""",
    'nested-module-generic/internal/q/q.go': """package q

import "encoding/json"

func Encode[V any](v V) string {
	b, _ := json.Marshal(v)
	return string(b)
}
""",
    'nested-module-generic/tools/go.mod': """module example.com/ng/tools

go 1.25

require example.com/ng v0.0.0

replace example.com/ng => ../
""",
    'nested-module-generic/tools/tools.go': """package tools

import (
	"example.com/ng/internal/a"
	"example.com/ng/internal/q"
)

func Use() string { return q.Encode(a.Make()) }
""",
}

MOD_CONST_SETS = {
    'const-sets/b/b.go': """package b

import "example.com/constsets/internal/e"

var (
	_ = e.StClaimed
	_ = e.StDone
	_ e.ItemStatus
	_ e.Due
	_ = e.Mixed
	_ = e.Week
	_ = e.Current()
)
""",
    'const-sets/b/b_never.go': """//go:build never

package b

import "example.com/constsets/internal/e"

var _ = e.ExcludedA
""",
    'const-sets/go.mod': """module example.com/constsets

go 1.25
""",
    'const-sets/internal/e/e.go': '// Package e exercises const sets: a const block of two or more constants,\n// every one of them of one exported type of the package, is left alone or\n// unexported as a whole.\npackage e\n\nimport "time"\n\n// RequestStatus is used through its values. The values nothing outside uses\n// stay exported with them.\ntype RequestStatus string\n\nconst (\n\tStUnclaimed RequestStatus = "unclaimed"\n\tStClaimed   RequestStatus = "claimed"\n\tStDone      RequestStatus = "done"\n\tStWithdrawn RequestStatus = "withdrawn"\n)\n\n// ItemStatus is named outside, and none of its values is: they stay exported\n// with it, implicit types included.\ntype ItemStatus int\n\nconst (\n\t_ ItemStatus = iota\n\tItemInFridge\n\tItemUsedUp\n)\n\n// Due is named outside. A lone constant of it is an internal choice, not a\n// value of the set, and a block mixing in another constant is not a set.\ntype Due string\n\nconst (\n\tDueSoon Due = "soon"\n\tDueWeek Due = "week"\n)\n\nconst DefaultDue Due = DueWeek // want: const DefaultDue is exported, but nothing\n\nconst (\n\tMixedDue Due = "mixed" // want: const MixedDue is exported, but nothing\n\tMixed        = 10\n)\n\n// A block of one type from another package is not a set.\nconst (\n\tDay  time.Duration = 24 * time.Hour // want: const Day is exported, but nothing\n\tWeek time.Duration = 7 * Day\n)\n\n// Lonely is reported, and so is every value of its set: they go together.\ntype Lonely int // want: type Lonely is exported, but nothing\n\nconst (\n\tLonelyA Lonely = iota // want: const LonelyA is exported, but nothing outside \\S+ uses it$\n\tLonelyB               // want: const LonelyB is exported, but nothing outside \\S+ uses it$\n)\n\n// Held is reported, and one of its values keeps its name, so every other one\n// does too, and so does the type the value hands out.\ntype Held int // want: type Held is exported.*no fix: an exported declaration that keeps its name hands it out\n\nconst (\n\t//declscope:ignore overexported // kept on purpose\n\tHeldA Held = iota\n\tHeldB // want: const HeldB is exported.*no fix: another value of its const block keeps its name\n)\n\n// The type is silenced, so its set is left alone, and an ignore over a value\n// of it silences nothing.\n//\n//declscope:ignore overexported // kept on purpose\ntype Silent int\n\nconst (\n\tSilentA Silent = iota\n\t//declscope:ignore overexported // want: unused //declscope:ignore overexported\n\tSilentB\n)\n\n// Excluded is reported, since nothing names it. A build-excluded file uses one\n// of its values, which keeps the set exported, and keeps the type that the\n// value hands out.\ntype Excluded int // want: type Excluded is exported.*no fix: an exported declaration that keeps its name hands it out\n\nconst (\n\tExcludedA Excluded = iota\n\tExcludedB\n)\n\n// Carried is never named outside, but a function another package calls\n// returns it, so it is used, and its values stay exported with it.\ntype Carried int\n\nconst (\n\tCarriedA Carried = iota\n\tCarriedB\n)\n\nfunc Current() Carried { return CarriedA }\n',
}

MOD_TYPEPARAM_SETS = {
    'typeparam-sets/b/b.go': """package b

import "example.com/typeparamsets/internal/a"

type U struct{ X, Y int }

type PtrTo[T any] interface{ *T }

func Named[P interface{ a.Named }]() []P { return []P{P{1, 2}, {3, 4}} }

func Converted[P interface{ a.Converted }](u U) P { return P(u) }

func Narrow[P interface {
	~*a.Narrow | ~*a.Wide
	~*a.Narrow
}]() []P {
	return []P{{1, 2}}
}

func Via[P interface{ PtrTo[a.Via] | *a.Via }]() []P { return []P{{3, 4}} }

func Twins[P interface{ a.Left | a.Right }]() P { return P{1, 2} }
""",
    'typeparam-sets/go.mod': """module example.com/typeparamsets

go 1.25
""",
    'typeparam-sets/internal/a/a.go': """// Package a declares structs that package b writes through a type parameter
// only: each literal or conversion there spells none of their fields. Each
// struct is written in one shape.
package a

// Named is the constraint itself: P interface{ a.Named }.
type Named struct{ X, Y int }

// Converted is the constraint of P, and P(u) pairs its fields with u's.
type Converted struct{ X, Y int }

// Narrow and Wide are both in a union, which a second element intersects
// with ~*Narrow alone, so only Narrow's fields are written.
type Narrow struct{ X, Y int }

type Wide struct {
	X int // want: field X is exported, but nothing.*uses it$
	Y int // want: field Y is exported, but nothing.*uses it$
}

// Via is reached through an interface term of a union.
type Via struct{ X, Y int }

// Left and Right share one underlying type, so a literal of
// P interface{ a.Left | a.Right } writes the fields of both.
type Left struct{ X, Y int }

type Right struct{ X, Y int }
""",
}

MOD_FIX_WITHHELD = {
    'fix-withheld/go.mod': """module example.com/withheld

go 1.25
""",
    'fix-withheld/internal/s/s.go': """// Package s is imported by package t. t's build-excluded file imports
// nothing, but reads a value of s through a variable its compiled sibling
// declares. That is enough to need any field or method of s, so none is
// fixed.
package s

type S struct {
	Field int // want: field Field is exported.*no fix: a build-excluded file of another package may use it
}

func (S) Method() string { return "" } // want: method Method is exported.*no fix: a build-excluded file of another package may use it

func New() S { return S{} }
""",
    'fix-withheld/internal/t/t.go': """package t

import "example.com/withheld/internal/s"

var v = s.New()
""",
    'fix-withheld/internal/t/t_never.go': """//go:build never

package t

func w() string { return v.Method() + string(rune(v.Field)) }
""",
    'fix-withheld/internal/u/u.go': """package u
""",
    'fix-withheld/internal/u/u_never.go': """//go:build never

package u

import . "example.com/withheld/internal/y"

var _ = Dotted

func pick(p interface{ Pick() }) { p.Pick() }

var _ = DotFilled{1}
""",
    'fix-withheld/internal/v/v.go': """package v
""",
    'fix-withheld/internal/v/v_never.go': """//go:build never

package v

import "example.com/withheld/internal/y"

type runner interface{ Run() }

var (
	_ = y.Keyed{Flag: 1}
	_ = y.Filled{1, "x"}
	_ = []y.InSlice{{1}}
	_ = map[string]*y.InMap{"k": {1}}
	_ = []*y.InSlice{&y.InSlice{2}}

	_ runner = y.NewRunner()
	_        = y.Converted(struct{ Flag int }{1})
	_        = y.NewHolder().Embedded
)
""",
    'fix-withheld/internal/w/gen.go': """// Code generated by hand for a test. DO NOT EDIT.

package w

var _ = GenRef
""",
    'fix-withheld/internal/w/w.go': """// Package w holds declarations nothing outside the package uses, where the
// fix is withheld for a reason other than the rename itself. Each is
// reported, and says why.
package w

// Lonely has no reason to keep its name, and is fixed.
func Lonely() int { return 1 } // want: func Lonely is exported, but nothing.*uses it$

// GenRef is named by a generated file, which a regeneration would put back.
var GenRef = 1 // want: var GenRef is exported.*no fix: a generated file names it

// Helper, Tool and Run are named by example functions, which go vet checks.
func Helper() int { return 1 } // want: func Helper is exported.*no fix: an example function names it

type Tool struct{} // want: type Tool is exported.*no fix: an example function names it

func (Tool) Run() {} // want: method Run is exported.*no fix: an example function names it

// Version may be set by -ldflags -X, which names it where go/types never
// looks.
var Version = "dev" // want: var Version is exported.*no fix: a string variable may be set by -ldflags -X

func current() string { return Version }

// Build is a string too, through an alias, so -X may set it.
var Build alias = "dev" // want: var Build is exported.*no fix: a string variable may be set by -ldflags -X

type alias = string

// Sentinel is of a named string type, which the linker refuses to set, so no
// -X names it and it is fixed.
var Sentinel = errorText("sentinel") // want: var Sentinel is exported, but nothing.*uses it$

type errorText string

// Made keeps its name, since an example function names it, so the type it
// returns must stay nameable. Deeper keeps its name for the same reason, so
// Deep, which it hands out, keeps its name too, with its report. Unused, a
// method like Deeper would be unexported with Deep in the same run.
func Made() Produced { return Produced{} } // want: func Made is exported.*no fix: an example function names it

type Produced struct{} // want: type Produced is exported.*no fix: an example function names it

func (Produced) Deeper() *Deep { return nil } // want: method Deeper is exported.*no fix: an example function names it

type Deep struct{} // want: type Deep is exported.*no fix: an exported declaration that keeps its name hands it out

// Parent keeps its name, and so does its method Kid, since an example names
// both, so Child, which Kid hands out, keeps its name with its report.
// Child's method Back hands Parent back, and keeps its name because the
// unexported one is taken. A type kept only through what it keeps holds
// nothing up, so Parent's own report stays.
type Parent struct{} // want: type Parent is exported.*no fix: an example function names it

func (Parent) Kid() *Child { return nil } // want: method Kid is exported.*no fix: an example function names it

type Child struct { // want: type Child is exported.*no fix: an exported declaration that keeps its name hands it out
	back int
}

func (Child) Back() *Parent { return nil } // want: method Back is exported.*no fix: the unexported name is taken on its type

// Outer keeps its name, since an example names it, and embeds Inner. Code
// holding an Outer names Inner only by spelling the field, which would be a
// use of Inner, or writes it by position, which is one too (Framed below).
// Neither happens, so Inner is fixed, and the field with it.
type Outer struct { // want: type Outer is exported.*no fix: an example function names it
	Inner
}

type Inner struct{} // want: type Inner is exported, but nothing.*uses it$

// The external tests write a Framed by position, which writes its embedded
// Frame too: unexported, it could not be written there.
type Framed struct{ Frame } // want: type Framed is exported, but only the external tests.*no fix: external tests use it

type Frame int // want: type Frame is exported, but only the external tests.*no fix: external tests use it

var (
	_ = Parent{}.Kid
	_ = Outer{}.Inner
	_ = Child{}.Back
	_ = Child{}.back
	_ = Made
	_ = Lonely() + GenRef + Helper()
	_ = Tool{}.Run
	_ = current
	_ = Build
	_ = Sentinel
)
""",
    'fix-withheld/internal/w/w_test.go': """package w

import (
	"os"
	"testing"
)

// The test functions are found by name, so none of them is reported.
func TestMain(m *testing.M) { os.Exit(m.Run()) }

func TestHelper(t *testing.T) { _ = Helper() + Exported() }

func BenchmarkHelper(b *testing.B) {}

func FuzzHelper(f *testing.F) {}

func ExampleHelper() {}

func ExampleTool_Run() {}

func ExampleTool_suffix() {}

func ExampleMade() {}

func ExampleProduced_Deeper() {}

func ExampleParent_Kid() {}

func ExampleOuter() {}

// Exported is declared in a test file and used only by the package's own
// tests, so it is fixed, and the fix renames the test that calls it.
func Exported() int { return 2 } // want: func Exported is exported, but nothing.*uses it$
""",
    'fix-withheld/internal/w/x_test.go': """package w_test

import "example.com/withheld/internal/w"

var _ = w.Framed{3}
""",
    'fix-withheld/internal/x/x.go': """// Package x has a build-excluded file of its own. That file is not
// type-checked, so a field or a method of x may be used there without its
// name showing: satisfying an interface, or matched in a conversion. So no
// field or method of x is fixed, and a name the file writes is not either.
package x

// WinRef is named by the build-excluded file, which the rename would leave
// behind.
var WinRef = 1 // want: var WinRef is exported.*no fix: a build-excluded file of its package names it

// Unnamed is written nowhere, and a package-level name has no use that does
// not spell it, so it is fixed.
func Unnamed() {} // want: func Unnamed is exported, but nothing.*uses it$

// Own is written nowhere in the build-excluded file, which only asks for an
// io.Closer that newOwn returns, but that is enough to need Close.
type Own struct { // want: type Own is exported, but nothing.*uses it$
	F int // want: field F is exported.*no fix: a build-excluded file of its package may use it
}

func (Own) Close() error { return nil } // want: method Close is exported.*no fix: a build-excluded file of its package may use it

func newOwn() Own { return Own{} }

var _ = Own{}.F
""",
    'fix-withheld/internal/x/x_never.go': """//go:build never

package x

import "io"

var _ = WinRef

var _ io.Closer = newOwn()
""",
    'fix-withheld/internal/y/y.go': """// Package y is imported by build-excluded files of packages u and v. They
// are not type-checked, so any field or method of y, and any type of y a
// struct embeds, may be used there without its name showing. None of those
// is fixed. A package-level name counts only where it is written.
package y

// Dotted is named under a dot import by the file of package u.
var Dotted = 1 // want: var Dotted is exported.*no fix: a build-excluded file of another package may use it

// Unnamed is written by neither file, so it is fixed.
func Unnamed() {} // want: func Unnamed is exported, but nothing.*uses it$

// Picker's method is selected by name in the file of package u.
type Picker struct{} // want: type Picker is exported, but nothing.*uses it$

func (Picker) Pick() {} // want: method Pick is exported.*no fix: a build-excluded file of another package may use it

// Runner's method satisfies an interface in the file of package v, which
// never writes its name.
type Runner struct{} // want: type Runner is exported.*no fix: an exported declaration that keeps its name hands it out

func (Runner) Run() {} // want: method Run is exported.*no fix: a build-excluded file of another package may use it

func NewRunner() Runner { return Runner{} }

// Converted's field is matched by name when the file of package v converts
// an unnamed struct to it.
type Converted struct {
	Flag int // want: field Flag is exported.*no fix: a build-excluded file of another package may use it
}

// Holder embeds Embedded, and the file of package v selects the embedded
// field by the type's name.
type Holder struct{ Embedded } // want: type Holder is exported.*no fix: an exported declaration that keeps its name hands it out

type Embedded struct{} // want: type Embedded is exported, but nothing.*no fix: a build-excluded file of another package may use it

func NewHolder() Holder { return Holder{} }

// Keyed, Filled, InSlice, InMap and DotFilled are written in composite
// literals: by key, and by position, with the type elided or not.
type Keyed struct {
	Flag  int // want: field Flag is exported.*no fix: a build-excluded file of another package may use it
	Other int // want: field Other is exported.*no fix: a build-excluded file of another package may use it
}

type Filled struct {
	A int    // want: field A is exported.*no fix: a build-excluded file of another package may use it
	B string // want: field B is exported.*no fix: a build-excluded file of another package may use it
}

type InSlice struct {
	C int // want: field C is exported.*no fix: a build-excluded file of another package may use it
}

type InMap struct {
	D int // want: field D is exported.*no fix: a build-excluded file of another package may use it
}

type DotFilled struct { // want: type DotFilled is exported.*no fix: a build-excluded file of another package may use it
	E int // want: field E is exported.*no fix: a build-excluded file of another package may use it
}

var (
	_ = Picker{}.Pick
	_ = Dotted
)
""",
}

MOD_RENAME_GUARDS = {
    'rename-guards/go.mod': """module example.com/rename

go 1.25
""",
    'rename-guards/internal/r/imp.go': """package r

import "strings"

var _ = strings.ToUpper
""",
    'rename-guards/internal/r/line.go': """package r

// A //line directive moves reported positions elsewhere. The fix must still
// edit this file.
//
//line fake.tmpl:1
func Lined() int { return 1 } // want: func Lined is exported, but nothing.*uses it$
""",
    'rename-guards/internal/r/r.go': """// Package r exercises the rename: what it rewrites, and every guard that
// withholds it. Nothing outside the package uses anything here.
package r

import _ "unsafe"

// Plain is fixed, and the name its doc comment opens with is rewritten too.
func Plain() int { return 1 } // want: func Plain is exported, but nothing.*uses it$

// A Thing is fixed, and so is the name after the article.
type Thing struct{} // want: type Thing is exported, but nothing.*uses it$

// Keep keeps its name, since an example names it, so Kept keeps its own.
// Kept then claims no name, and KEPT, which lowers to the same, is fixed
// with the Toy it returns, all in one run. Kept's report reads as taken,
// the way the next run reads it once KEPT is kept.
func Keep() Kept { return Kept{} } // want: func Keep is exported.*no fix: an example function names it

type Kept struct{} // want: type Kept is exported.*no fix: the unexported name is taken or would be captured

func KEPT() *Toy { return nil } // want: func KEPT is exported, but nothing.*uses it$

type Toy struct{} // want: type Toy is exported, but nothing.*uses it$

// Wrap and WRAP both lower to wrap, and WRAP hands out Wrap. Wrap claims
// the name first, so WRAP's fix is withheld, and WRAP, keeping its name,
// keeps Wrap's: neither would be fixed, for a name neither takes. The claim
// is made again with WRAP first, and Wrap's fix is the one withheld.
type Wrap struct{} // want: type Wrap is exported.*no fix: the unexported name is taken or would be captured

func WRAP() Wrap { return Wrap{} } // want: func WRAP is exported, but nothing.*uses it$

// Nest is embedded two levels down in stack, beside hopper, whose method
// nest sits at the depth Nest's field would take: renaming Nest would make
// stack{}.nest() ambiguous.
type Nest struct{} // want: type Nest is exported.*no fix: the unexported name is taken or would be captured

type hopper struct{}

func (hopper) nest() int { return 0 }

type nested struct{ Nest }

type stack struct {
	nested
	hopper
}

// Span and SPAN both lower to span, and meet only in spanOut, one level down
// from Span's field. SPAN claims the name first, and Span's report reads as
// taken, the way the next run, with SPAN fixed, reads it.
type Pv struct{} // want: type Pv is exported, but nothing.*uses it$

func (Pv) SPAN() {} // want: method SPAN is exported, but nothing.*uses it$

type Span struct{} // want: type Span is exported.*no fix: the unexported name is taken or would be captured

type spanIn struct{ Span }

type spanOut struct {
	spanIn
	Pv
}

// NewThing returns a Thing, and is fixed in the same run, so it keeps
// nothing exported: one run of -fix settles both.
func NewThing() *Thing { return nil } // want: func NewThing is exported, but nothing.*uses it$

// Svc's method is fixed, and so is the name its doc comment opens with.
type Svc struct{} // want: type Svc is exported, but nothing.*uses it$

// Serve is fixed with its doc comment.
func (Svc) Serve() {} // want: method Serve is exported, but nothing.*uses it$

/* Block is a block comment, which the fix leaves alone. */
func Block() {} // want: func Block is exported, but nothing.*uses it$

// Loader opens this comment, which is another word, and is left alone.
func Load() {} // want: func Load is exported, but nothing.*uses it$

func Taken() int { return taken() } // want: func Taken is exported.*no fix: the unexported name is taken or would be captured

func taken() int { return 0 }

// Count is captured by the parameter of the same name at its one use.
var Count = func(count int) int { return count } // want: var Count is exported.*no fix: the unexported name is taken or would be captured

func useCount(count int) int { return count + Count(count) }

// DUP lowers to the name Dup's fix claims.
func Dup() int { return 1 } // want: func Dup is exported, but nothing.*uses it$

func DUP() int { return 2 } // want: func DUP is exported.*no fix: the unexported name is taken or would be captured

func Type() {} // want: func Type is exported.*no fix: the unexported name is not an identifier

func Init() {} // want: func Init is exported.*no fix: the unexported name means something to the toolchain

//go:linkname Pushed
func Pushed() {} // want: func Pushed is exported.*no fix: a //go:linkname or //export names it

// The unexported name is an import of another file of the package.
func Strings() {} // want: func Strings is exported.*no fix: the unexported name is taken or would be captured

// HTTPServer becomes httpServer. MAX_RETRIES has no spelling Go would use.
func HTTPServer() {} // want: func HTTPServer is exported, but nothing.*uses it$

const MAX_RETRIES = 3 // want: const MAX_RETRIES is exported.*no fix: the name has no unexported spelling Go would use

const Limit = 3 // want: const Limit is exported, but nothing.*uses it$

type Alias = Pair // want: type Alias is exported, but nothing.*uses it$

// Level is not a struct, so nothing embeds it to collide with.
type Level int // want: type Level is exported, but nothing.*uses it$

// Named has a method whose unexported name is a field, and a field whose
// unexported name is a method.
type Named struct { // want: type Named is exported, but nothing.*uses it$
	name string
	Size int // want: field Size is exported.*no fix: the unexported name is taken on its type
}

func (Named) Name() string { return "" } // want: method Name is exported.*no fix: the unexported name is taken on its type

func (Named) size() int { return 0 }

// Asked would start satisfying the interface of a type assertion.
type Asked struct{} // want: type Asked is exported, but nothing.*uses it$

func (Asked) Run() {} // want: method Run is exported.*no fix: the unexported name is taken on its type

// Quiet would start satisfying husher, a named interface of the package.
type Quiet struct{} // want: type Quiet is exported, but nothing.*uses it$

func (Quiet) Hush() {} // want: method Hush is exported.*no fix: the unexported name is taken on its type

type husher interface{ hush() }

// derived promotes Hop, and already has a field of the unexported name.
type Base struct{} // want: type Base is exported, but nothing.*uses it$

func (Base) Hop() {} // want: method Hop is exported.*no fix: the unexported name is taken on its type

type derived struct {
	Base
	hop int
}

// An unnamed struct promotes Size, and has a field of the unexported name.
type Boxed struct { // want: type Boxed is exported, but nothing.*uses it$
	Size int // want: field Size is exported.*no fix: the unexported name is taken on its type
}

// amb embeds T and U, so its F is ambiguous, and renaming T's F to f would
// make its f ambiguous too.
type T struct { // want: type T is exported, but nothing.*uses it$
	F int // want: field F is exported.*no fix: the unexported name is taken on its type
}

type U struct { // want: type U is exported, but nothing.*uses it$
	F int // want: field F is exported.*no fix: the unexported name is taken on its type
	f int
}

type amb struct {
	T
	U
}

// First.ID and Second.Id both lower to id, and both embeds the two, so only
// the first is fixed.
type First struct { // want: type First is exported, but nothing.*uses it$
	ID int // want: field ID is exported, but nothing.*uses it$
}

type Second struct { // want: type Second is exported, but nothing.*uses it$
	Id int // want: field Id is exported.*no fix: the unexported name is taken on its type
}

type both struct {
	First
	Second
}

// ID and Id of one type lower to one name, so only the first is fixed.
// First.ID's claim on id above does not reach Pair.
type Pair struct { // want: type Pair is exported, but nothing.*uses it$
	ID int // want: field ID is exported, but nothing.*uses it$
	Id int // want: field Id is exported.*no fix: the unexported name is taken on its type
}

// Emb's unexported name is taken by a field of a struct embedding it, since
// the embedded field takes the type's name.
type Emb struct{} // want: type Emb is exported.*no fix: the unexported name is taken or would be captured

type Holder struct { // want: type Holder is exported, but nothing.*uses it$
	Emb
	emb int
}

// Inner is embedded and selected by its name, which the rename rewrites.
type Inner struct{} // want: type Inner is exported, but nothing.*uses it$

type outer struct{ Inner }

// Shared is embedded twice in diamond, through left and right, and its
// field Val with it. Both are found through either path, and both are fixed.
type Shared struct { // want: type Shared is exported, but nothing.*uses it$
	Val int // want: field Val is exported, but nothing.*uses it$
}

type left struct{ Shared }

type right struct{ Shared }

type diamond struct {
	left
	right
}

// Pointed and AliasOfAliased are embedded through a pointer and an alias.
type Pointed struct{} // want: type Pointed is exported, but nothing.*uses it$

type Aliased struct{} // want: type Aliased is exported, but nothing.*uses it$

type AliasOfAliased = Aliased // want: type AliasOfAliased is exported, but nothing.*uses it$

type embedder struct {
	*Pointed
	AliasOfAliased
}

// A predeclared type embedded by name is no declaration of the package.
type basic struct{ int }

// An unkeyed literal in the package itself is renamed with the fields.
type Local struct { // want: type Local is exported, but nothing.*uses it$
	A int // want: field A is exported, but nothing.*uses it$
}

// A selection on an instantiation names the origin's member.
type List[E any] struct { // want: type List is exported, but nothing.*uses it$
	Items []E // want: field Items is exported, but nothing.*uses it$
}

func (l *List[E]) Len() int { return len(l.Items) } // want: method Len is exported.*no fix: the unexported name is predeclared

func uses() int {
	var l List[int]
	_ = func(v any) bool { _, ok := v.(interface{ run() }); return ok }
	var _ husher
	var v struct {
		Boxed
		size int
	}
	return l.Len() + len(l.Items) + useCount(1) + Plain() + Dup() + DUP() + MAX_RETRIES + Limit +
		Named{}.Size + Named{}.size() + len(Named{}.name+Named{}.Name()) + derived{}.hop + v.Size + v.size +
		amb{}.f + T{}.F + U{}.F + both{}.ID + both{}.Id + Pair{}.ID + Pair{}.Id + Holder{}.emb + Local{1}.A + Local{A: 2}.A +
		basic{}.int
}

var (
	_ Thing
	_ = NewThing
	_ = Keep
	_ = KEPT
	_ = stack{}.nest()
	_ = spanOut{}
	_ = WRAP
	_ Alias
	_ Level
	_ = Asked{}.Run
	_ = Quiet{}.Hush
	_ = derived{}.Hop
	_ = Holder{}.Emb
	_ = outer{}.Inner
	_ = embedder{}.Pointed
	_ = embedder{}.AliasOfAliased
	_ = uses
	_ = Svc{}.Serve
	// A conversion and a literal of types that are no struct pair nothing.
	_ = float64(Limit)
	_ = []int{1}
)
""",
    'rename-guards/internal/r/r_test.go': """package r

func ExampleKeep() {}
""",
    'rename-guards/internal/rx/rx.go': """// Package rx has a build-excluded file of its own, so it is apart from r:
// that file holds back every field and method of its package.
package rx

// The unexported name is written by the build-excluded file.
func Clash() {} // want: func Clash is exported.*no fix: a build-excluded file of its package writes the unexported name

// The build-excluded file binds the name with //go:linkname.
func Linked() {} // want: func Linked is exported.*no fix: a //go:linkname or //export names it
""",
    'rename-guards/internal/rx/rx_never.go': """//go:build never

package rx

import _ "unsafe"

var clash = 1

//go:linkname Linked example.com/rename/internal/rx.pushed
""",
}

MOD_IGNORES = {
    'ignores/b/b.go': """package b

import "example.com/ignores/internal/i"

var _ = i.Ignored() + i.Mixed() + i.F() + i.Answered() + i.FileAnswered() + i.Used()

var _ = i.Hand()

var _ = i.Mode{}.Plain

var _ = i.Typed(i.Valued + i.Blocked)
""",
    'ignores/b/tagged.go': """//go:build !never

package b

import (
	"fmt"

	"example.com/ignores/internal/i"
)

// This file is behind a build constraint, and -tags=never leaves it out.
var _ = i.Mode{}.Tagged + i.Mode{}.Plain

var _ = i.TaggedFunc

// Shown and Printed escape into fmt.Println, behind the constraint as well.
func show() { fmt.Println(i.Shown{Field: 1}, i.Printed{}) }

var _ = show
""",
    'ignores/c/c.go': """package c

import "example.com/ignores/internal/h"

var held = h.Hold()
""",
    'ignores/c/tagged.go': """//go:build !never

package c

// This file imports nothing, and reads h through the variable c.go declares.
var _ = held.Mark
""",
    'ignores/go.mod': """module example.com/ignores

go 1.25
""",
    'ignores/internal/h/h.go': """// Package h is imported only by c/c.go. Its field is used outside only by
// c/tagged.go, which is behind a build constraint and imports nothing: it
// reads the Held that c.go holds. Without tagged.go, the field is reported
// with its fix withheld, since c.go may hand tagged.go a Held, so the ignore
// is needed there.
package h

type Held struct {
	//declscope:ignore overexported
	Mark int
}

func Hold() Held { return Held{} }
""",
    'ignores/internal/i/file.go': """// A file-level ignore covering unused answers the unused report of every
// ignore in the file, as it does for the analyzer.
//
//declscope:ignore unused

package i

//declscope:ignore overexported
func FileAnswered() int { return Used() }
""",
    'ignores/internal/i/i.go': """// Package i exercises //declscope:ignore overexported: where it binds, what
// it silences, and when it is itself reported unused.
package i

//declscope:ignore overexported
func Silenced() {}

// The declaration is used by package b, so the ignore silences nothing.
//
//declscope:ignore overexported // want: unused //declscope:ignore overexported
func Ignored() int { return Used() }

// An ignore naming another rule as well is judged by neither side: the
// analyzer cannot see overexported, and this run cannot see the analyzer's.
//
//declscope:ignore overexported,qualify
func Mixed() int { return Used() }

// A bare ignore does not reach overexported, so this is reported anyway, and
// the ignore is the analyzer's to judge.
//
//declscope:ignore
func Bare() {} // want: func Bare is exported, but nothing.*uses it$

// A comment trailing a func's first or last line binds, as it does for the
// analyzer.
func Trailing() {} //declscope:ignore overexported

func Multi() {
} //declscope:ignore overexported

// An earlier comment on the line does not stop it binding.
func Commented(n int /* units */) int { //declscope:ignore overexported
	return n
}

// So does one after `struct {` or `var (`.
type Braced struct { //declscope:ignore overexported
	n int
}

var ( //declscope:ignore overexported
	Parened = 1
)

// F is used by package b, so the trailing ignore silences nothing. The doc
// ignore naming unused answers its unused report: both are bound to F.
//
//declscope:ignore unused
func F() int { return 1 } //declscope:ignore overexported

// An ignore beside it naming unused answers the same report.
//
//declscope:ignore overexported
//declscope:ignore unused
func Answered() int { return Used() }

// An ignore repeated on one binding is the analyzer's to report, as a
// duplicate, and it drops it. It is not also unused here: the first one
// silences Twice, and the repeat is no second site to judge.
//
//declscope:ignore overexported
func Twice() {} //declscope:ignore overexported

// The doc and the trailing comment of an ungrouped type or var are one
// binding too, so the ignore naming unused answers the doc's report.
//
//declscope:ignore overexported
type Typed int //declscope:ignore unused

//declscope:ignore overexported
var Valued = 1 //declscope:ignore unused

// A block's doc and the comment after its "(" are one binding.
//
//declscope:ignore overexported
var ( //declscope:ignore unused
	Blocked = 1
)

// A silenced declaration claims no name, so FOO's fix is offered.
//
//declscope:ignore overexported
func Foo() {}

func FOO() {} // want: func FOO is exported, but nothing.*uses it$

// An ignore bound to no declaration silences nothing, and nothing beside it
// answers its unused report.
func stray() {
	//declscope:ignore overexported // want: unused //declscope:ignore overexported
}

func Used() int { return 1 }

// Hand is called by package b, so the Handed it returns is used there, and
// the ignore silences nothing.
//
//declscope:ignore overexported // want: unused //declscope:ignore overexported
type Handed struct{}

func Hand() *Handed { return nil }

// Build is silenced, so it keeps its name, and the type it returns keeps its
// own, with its report.
//
//declscope:ignore overexported
func Build() *Built { return nil }

type Built struct{} // want: type Built is exported.*no fix: an exported declaration that keeps its name hands it out

var (
	_ = Braced{}.n
	_ = stray
)

// Mode's fields are used outside only by b/tagged.go, which is behind a build
// constraint, except Plain, which b.go uses too. A configuration that leaves
// tagged.go out reports Tagged, with its fix withheld, and the ignore answers
// that report there, so it is not unused here either. Plain's ignore is,
// since b.go uses Plain in every configuration.
type Mode struct {
	//declscope:ignore overexported
	Tagged int
	//declscope:ignore overexported // want: unused //declscope:ignore overexported
	Plain int
}

// TaggedFunc is used only by b/tagged.go too, but tagged.go spells
// i.TaggedFunc, which a configuration leaving it out still reads as a use.
// The ignore is needed in none of them.
//
//declscope:ignore overexported // want: unused //declscope:ignore overexported
func TaggedFunc() {}

// Shown's field is used outside only by b/tagged.go, which also passes a
// Shown to fmt.Println. The escape is behind the constraint too, so the run
// without tagged.go reports Field and needs the ignore.
type Shown struct {
	//declscope:ignore overexported
	Field int
}

// Printed's field is never named outside, but b/tagged.go passes a Printed to
// fmt.Println, which reads its fields. Without tagged.go, the field is
// reported with its fix withheld, so the ignore is needed there.
type Printed struct {
	//declscope:ignore overexported
	Hidden int
}
""",
    'ignores/internal/i/i_test.go': """package i

import "testing"

// A test function is no candidate, since go test finds it by name, but its
// ignores are still one binding, as they are for the analyzer: the ignore
// naming unused answers the doc's report.
//
//declscope:ignore overexported
func TestX(t *testing.T) {} //declscope:ignore unused

// A repeat is the analyzer's to report, as a duplicate, and no second site
// here.
//
//declscope:ignore overexported // want: unused //declscope:ignore overexported
func TestY(t *testing.T) {} //declscope:ignore overexported
""",
    'ignores/internal/i/members.go': """package i

// The doc and the trailing comment of a member are one binding, whatever
// the type: an interface's method and an alias struct type's field are no
// candidates here, but the ignore naming unused still answers the doc's
// report, as it does for the analyzer.
type iface interface {
	//declscope:ignore overexported
	M() //declscope:ignore unused
}

type aliased = struct {
	//declscope:ignore overexported
	F int //declscope:ignore unused
}

type fielded struct {
	//declscope:ignore overexported
	F int //declscope:ignore unused
}
""",
    'ignores/internal/i/twice.go': """// A file-level ignore repeated is the analyzer's to report, as a duplicate,
// and it drops it. It is not also unused here, even in a comment group of its
// own: the first one silences TwiceFile, and the repeat is no second site to
// judge.
//
//declscope:ignore overexported

//declscope:ignore overexported

package i

func TwiceFile() {}
""",
}

MOD_NOT_JUDGED = {
    'not-judged/go.mod': """module example.com/notjudged

go 1.25
""",
    'not-judged/internal/asm/asm.go': """// Package asm holds assembly for this architecture, which may name any symbol
// of the package, so nothing is said.
package asm

func Unused() {}
""",
    'not-judged/internal/asm/asm_amd64.s': """// An empty assembly file.
""",
    'not-judged/internal/asm/asm_arm64.s': """// An empty assembly file.
""",
    'not-judged/internal/crc/crc.go': """// Package crc holds assembly for an architecture this run does not build,
// which may read Table by name, so nothing is said.
package crc

var Table = 1
""",
    'not-judged/internal/crc/crc_s390x.s': """// Assembly for s390x, which the host build leaves out.
""",
    'not-judged/internal/tool/main.go': """// Package main is never judged: -buildmode=plugin looks its exported symbols
// up.
package main

func Plugged() {}

func main() {}
""",
    'not-judged/pub/pub.go': """// Package pub is outside internal/, so another module may import it, and
// nothing is said.
package pub

func Unused() {}
""",
}

MOD_NESTED_MODULE = {
    'nested-module/go.mod': """module example.com/nested

go 1.25
""",
    'nested-module/internal/x/x.go': """// Package x has a nested module under its parent. That module is loaded, and
// imports nothing of this one, so x is judged like any other package.
package x

func Unused() {} // want: func Unused is exported, but nothing outside example.com/nested/internal/x uses it$
""",
    'nested-module/tools/go.mod': """module example.com/nested/tools

go 1.25
""",
    'nested-module/tools/tools.go': """package tools
""",
}

MOD_NESTED_MODULE_IN_UNDERSCORE_DIR = {
    'nested-module-in-underscore-dir/_tools/go.mod': """module example.com/tl/_tools

go 1.25

require example.com/tl v0.0.0

replace example.com/tl => ../
""",
    'nested-module-in-underscore-dir/_tools/tools.go': """package tools

import "example.com/tl/internal/a"

var _ = a.F
""",
    'nested-module-in-underscore-dir/go.mod': """module example.com/tl

go 1.25
""",
    'nested-module-in-underscore-dir/internal/a/a.go': """// Package a is imported by the nested module in _tools, whose path lies under
// this module's. That module is loaded, so its use of F counts.
package a

func F() {}
""",
}

MOD_NESTED_MODULE_USES = {
    'nested-module-uses/go.mod': """module example.com/nu

go 1.25
""",
    'nested-module-uses/internal/a/a.go': """// Package a is imported by the nested module in tools, which is loaded, so
// each way it uses a declaration counts, and only what it leaves is reported.
package a

// Called is called from tools.
func Called() {}

func Unused() {} // want: func Unused is exported, but nothing outside example.com/nu/internal/a uses it$

// Runner has Run called through tools' own interface, which names no method
// of this package.
type Runner struct{}

func (Runner) Run() {}

// Printed reaches fmt.Println in tools, so reflection may read its fields.
type Printed struct {
	Field int
}

// NewPrinted is how tools gets a Printed without naming its field.
func NewPrinted() Printed { return Printed{} }

// Tagged is written only in a file of tools that a build tag excludes.
func Tagged() {}

// InTest is called only from a test of tools.
func InTest() {}
""",
    'nested-module-uses/internal/a/a_test.go': """package a

import "testing"

// TestCalled gives this package a test variant, which tools' load must not
// read as what tools imports.
func TestCalled(t *testing.T) { Called() }
""",
    'nested-module-uses/tools/go.mod': """module example.com/nu/tools

go 1.25

require example.com/nu v0.0.0

replace example.com/nu => ../
""",
    'nested-module-uses/tools/tagged.go': """//go:build special

package tools

import "example.com/nu/internal/a"

func init() { a.Tagged() }
""",
    'nested-module-uses/tools/tools.go': """package tools

import (
	"fmt"

	"example.com/nu/internal/a"
)

type runner interface{ Run() }

func Use() {
	a.Called()
	var r runner = a.Runner{}
	r.Run()
	fmt.Println(a.NewPrinted())
}
""",
    'nested-module-uses/tools/tools_test.go': """package tools

import (
	"testing"

	"example.com/nu/internal/a"
)

func TestInTest(t *testing.T) { a.InTest() }
""",
}

MOD_NESTED_MODULE_EXCLUDED = {
    'nested-module-excluded/go.mod': """module example.com/nx

go 1.25
""",
    'nested-module-excluded/internal/a/a.go': """// Package a is imported by the nested module in tools, whose package q holds
// a value of T in a compiled file. A file of q that its build excludes imports
// nothing, but may still call T's method through that value.
package a

type T struct{}

func New() T { return T{} }

func (T) Method() int { return 0 } // want: method Method is exported.*no fix: a build-excluded file of another package may use it

func Unused() {} // want: func Unused is exported, but nothing outside example.com/nx/internal/a uses it$
""",
    'nested-module-excluded/tools/go.mod': """module example.com/nx/tools

go 1.25

require example.com/nx v0.0.0

replace example.com/nx => ../
""",
    'nested-module-excluded/tools/q/q.go': """package q

import "example.com/nx/internal/a"

var v = a.New()

var _ = v
""",
    'nested-module-excluded/tools/q/q_never.go': """//go:build never

package q

func use() int { return v.Method() }
""",
}

MOD_NESTED_MODULE_ABOVE = {
    'nested-module-above/go.mod': """module example.com/nan

go 1.24
""",
    'nested-module-above/tools/go.mod': """module example.com/nan/x

go 1.24

require example.com/nan v0.0.0

replace example.com/nan => ../
""",
    'nested-module-above/tools/y/z/z.go': """package z

import "example.com/nan/x/y/internal/foo"

var V = foo.Hello()
""",
    'nested-module-above/x/y/internal/foo/foo.go': """package foo

// Hello is what the nested module tools uses. Its path, example.com/nan/x,
// lies above this package's internal/ parent, example.com/nan/x/y, so its
// package example.com/nan/x/y/z may import this one.
func Hello() string { return "hi" }

func Bye() {} // want: func Bye is exported, but nothing outside example.com/nan/x/y/internal/foo uses it
""",
}

MOD_NESTED_MODULE_ELSEWHERE = {
    'nested-module-elsewhere/go.mod': """module example.com/ne

go 1.25
""",
    'nested-module-elsewhere/internal/a/a.go': """// Package a is not judged: the nested module in tools reads example.com/ne
// from nested-module-elsewhere-copy, so its uses are of other source.
package a

func F() {}
""",
    'nested-module-elsewhere/tools/go.mod': """module example.com/ne/tools

go 1.25

require example.com/ne v0.0.0

replace example.com/ne => ../../nested-module-elsewhere-copy
""",
    'nested-module-elsewhere/tools/tools.go': """package tools

import "example.com/ne/internal/a"

var _ = a.F
""",
    'nested-module-elsewhere-copy/go.mod': """module example.com/ne

go 1.25
""",
    'nested-module-elsewhere-copy/internal/a/a.go': """// Package a is the copy nested-module-elsewhere/tools builds against. It is
// not a fixture of its own.
package a

func F() {}
""",
}

MOD_NESTED_MODULE_BROKEN = {
    'nested-module-broken/go.mod': """module example.com/nb

go 1.25
""",
    'nested-module-broken/internal/a/a.go': """// Package a is not judged: the nested module in tools imports it but does
// not type-check, so whether it uses F is unknown.
package a

func F() {}
""",
    'nested-module-broken/tools/go.mod': """module example.com/nb/tools

go 1.25

require example.com/nb v0.0.0

replace example.com/nb => ../
""",
    'nested-module-broken/tools/tools.go': """package tools

import "example.com/nb/internal/a"

var _ = a.F

var _ int = "not an int"
""",
}

MOD_BUILD_LIST_REPLACE = {
    'build-list-replace/cmd/c/main.go': """package main

import "example.com/blr/ext"

func main() { ext.Run() }
""",
    'build-list-replace/ext/e.go': """package ext

import "example.com/blr/internal/a"

func Run() { a.New() }
""",
    'build-list-replace/ext/go.mod': """module example.com/blr/ext

go 1.24

require example.com/blr v0.0.0

replace example.com/blr => ../
""",
    'build-list-replace/go.mod': """module example.com/blr

go 1.24

require example.com/blr/ext v0.0.0

replace example.com/blr/ext => ../build-list-replace-ext
""",
    'build-list-replace/internal/a/a.go': """package a

// New is what the nested module ext uses.
func New() {}

// Used is what the copy of ext the build reads uses. Nothing in this tree
// does, and unexporting it breaks go build ./... of this module.
func Used() {}
""",
    'build-list-replace-ext/e.go': """package ext

import "example.com/blr/internal/a"

func Run() { a.Used() }
""",
    'build-list-replace-ext/go.mod': """module example.com/blr/ext

go 1.24
""",
}

MOD_BUILD_LIST_VENDORED = {
    'build-list-vendored/cmd/c/main.go': """package main

import "example.com/blv/ext"

func main() { ext.Run() }
""",
    'build-list-vendored/go.mod': """module example.com/blv

go 1.24

require example.com/blv/ext v1.0.0
""",
    'build-list-vendored/internal/a/a.go': """package a

// Old is what the vendored ext v1.0.0, which the build reads, uses.
func Old() {}
""",
    'build-list-vendored/vendor/example.com/blv/ext/e.go': """package ext

import "example.com/blv/internal/a"

func Run() { a.Old() }
""",
    'build-list-vendored/vendor/modules.txt': """# example.com/blv/ext v1.0.0
## explicit; go 1.24
example.com/blv/ext
""",
}

MOD_NESTED_BUILD_LIST = {
    'nested-build-list/m/a/internal/y/y.go': """package y

// Unused lies in a range that no copy of t has a path in, so it is judged.
func Unused() {} // want: func Unused is exported, but nothing outside example.com/nbl/a/internal/y uses it
""",
    'nested-build-list/m/b/g/g.go': """package g
""",
    'nested-build-list/m/b/g/go.mod': """module example.com/nbl/b/g

go 1.24

require (
	example.com/nbl v0.0.0
	example.com/nbl/b/u v0.0.0
)

replace (
	example.com/nbl => ../../
	example.com/nbl/b/u => ../../../u-copy
)
""",
    'nested-build-list/m/b/g/tagged.go': """//go:build never

package g

import "example.com/nbl/b/u"

// Run is compiled only under the never tag, so this run's load never
// compiles u. The build under that tag does.
func Run() { u.Run() }
""",
    'nested-build-list/m/b/internal/z/z.go': 'package z\n\n// Baz is what the copy of u that the nested module b/g builds with under the\n// never tag uses. Nothing in this tree does, and unexporting it breaks\n// go build -tags=never ./... of b/g, so its fix is withheld.\nfunc Baz() {} // want: func Baz is exported, but nothing outside example.com/nbl/b/internal/z uses it \\(no fix: the build of the nested module example.com/nbl/b/g uses example.com/nbl/b/u from .*u-copy, which imports example.com/nbl/b/internal/z\\)\n',
    'nested-build-list/m/c/internal/w/w.go': 'package w\n\n// Qux is what the copy of v that the nested module k builds with uses. k\n// lies under no internal parent, so this run never loads it, but its build\n// list still names that copy. Unexporting Qux breaks go build ./... of k, so\n// its fix is withheld.\nfunc Qux() {} // want: func Qux is exported, but nothing outside example.com/nbl/c/internal/w uses it \\(no fix: the build of the nested module example.com/nbl/k uses example.com/nbl/c/v from .*v-copy, which imports example.com/nbl/c/internal/w\\)\n',
    'nested-build-list/m/go.mod': """module example.com/nbl

go 1.24
""",
    'nested-build-list/m/k/go.mod': """module example.com/nbl/k

go 1.24

require (
	example.com/nbl v0.0.0
	example.com/nbl/c/v v0.0.0
)

replace (
	example.com/nbl => ../
	example.com/nbl/c/v => ../../v-copy
)
""",
    'nested-build-list/m/k/k.go': """package k

import "example.com/nbl/c/v"

func Run() { v.Run() }
""",
    'nested-build-list/m/s/internal/x/x.go': 'package x\n\n// Foo is what the copy of t that the nested module s/n builds with uses.\n// Nothing in this tree does, and unexporting it breaks go build ./... of s/n,\n// so its fix is withheld.\nfunc Foo() {} // want: func Foo is exported, but nothing outside example.com/nbl/s/internal/x uses it \\(no fix: the build of the nested module example.com/nbl/s/n uses example.com/nbl/s/t from .*, which imports example.com/nbl/s/internal/x\\)\n\n// Bar is used by nothing, but the copy may use it too, so its fix is\n// withheld all the same.\nfunc Bar() {} // want: func Bar is exported, but nothing outside example.com/nbl/s/internal/x uses it \\(no fix: the build of the nested module example.com/nbl/s/n uses example.com/nbl/s/t from\n',
    'nested-build-list/m/s/n/go.mod': """module example.com/nbl/s/n

go 1.24

require (
	example.com/nbl v0.0.0
	example.com/nbl/s/t v0.0.0
)

replace (
	example.com/nbl => ../../
	example.com/nbl/s/t => ../../../t-copy
)
""",
    'nested-build-list/m/s/n/n.go': """package n

import "example.com/nbl/s/t"

func Run() { t.Run() }
""",
    'nested-build-list/m/s/t/go.mod': """module example.com/nbl/s/t

go 1.24
""",
    'nested-build-list/m/s/t/t.go': """package t

// Run uses neither x.Foo nor x.Bar. The copy of t that n builds with does.
func Run() {}
""",
    'nested-build-list/t-copy/go.mod': """module example.com/nbl/s/t

go 1.24
""",
    'nested-build-list/t-copy/t.go': """package t

import "example.com/nbl/s/internal/x"

func Run() { x.Foo() }
""",
    'nested-build-list/u-copy/go.mod': """module example.com/nbl/b/u

go 1.24
""",
    'nested-build-list/u-copy/u.go': """package u

import "example.com/nbl/b/internal/z"

func Run() { z.Baz() }
""",
    'nested-build-list/v-copy/go.mod': """module example.com/nbl/c/v

go 1.24
""",
    'nested-build-list/v-copy/v.go': """package v

import "example.com/nbl/c/internal/w"

func Run() { w.Qux() }
""",
}

MOD_WORKSPACE_UNLISTED = {
    'workspace-unlisted/go.work': """go 1.24

use (
	./m
	./other
)
""",
    'workspace-unlisted/m/go.mod': """module example.com/wu

go 1.24
""",
    'workspace-unlisted/m/internal/a/a.go': """package a

// Used is what the nested module tools uses.
func Used() {}

func Unused() {} // want: func Unused is exported, but nothing outside example.com/wu/internal/a uses it
""",
    'workspace-unlisted/m/tools/go.mod': """module example.com/wu/tools

go 1.24

require example.com/wu v0.0.0

replace example.com/wu => ../
""",
    'workspace-unlisted/m/tools/main.go': """package main

import "example.com/wu/internal/a"

func main() { a.Used() }
""",
    'workspace-unlisted/other/go.mod': """module example.com/wuo

go 1.24
""",
    'workspace-unlisted/other/o.go': """package o
""",
}

MOD_NESTED_OWN_WORKSPACE = {
    'nested-own-workspace/go.mod': """module example.com/now

go 1.24
""",
    'nested-own-workspace/internal/x/x.go': """package x

// Foo is what the nested module n uses, through its own go.work.
func Foo() {}

func Bar() {} // want: func Bar is exported, but nothing outside example.com/now/internal/x uses it
""",
    'nested-own-workspace/n/go.mod': """module example.com/now/n

go 1.24
""",
    'nested-own-workspace/n/go.work': """go 1.24

use (
	.
	..
)
""",
    'nested-own-workspace/n/n.go': """package n

import "example.com/now/internal/x"

func Run() { x.Foo() }
""",
}

MOD_NESTED_MODULE_IN_TESTDATA = {
    'nested-module-in-testdata/go.mod': """module example.com/dp

go 1.25
""",
    'nested-module-in-testdata/internal/q/q.go': """// Package q may be imported by the module in testdata/tools, one level
// below a directory ./... skips. That module is loaded, and imports nothing
// of this one, so q is judged.
package q

func F() {} // want: func F is exported, but nothing outside example.com/dp/internal/q uses it$
""",
    'nested-module-in-testdata/testdata/tools/go.mod': """module example.com/dp/tools

go 1.25
""",
    'nested-module-in-testdata/testdata/tools/tools.go': """package tools
""",
}

MOD_MODULE_UNDER_INTERNAL = {
    'module-under-internal/go.mod': """module example.com/x/internal/y

go 1.25
""",
    'module-under-internal/internal/z/z.go': """package z

// T reaches another module through y.Get, so M and F are used there.
type T struct {
	F int
}

func (T) M() {}

func Unused() {} // want: func Unused is exported, but nothing.*uses it$
""",
    'module-under-internal/y.go': """// Package y is importable from example.com/x, which lies above this module,
// so its exported API is a root of the exposure walk though its path runs
// through internal/.
package y

import "example.com/x/internal/y/internal/z"

func Get() z.T { return z.T{} }
""",
}


def test_shrink_uses(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins what
    counts as a use from outside the package: a spelled name, an unkeyed literal, a struct conversion, a
    linkname, a static satisfaction, a value handed out by an importable package, a type an API carries, an
    external test, and a build-excluded file.
    """
    write_tree(workdir, MOD_USES)
    assert shrink_report(ds, workdir, workdir / 'uses') == golden("shrink_uses")


def test_shrink_escapes(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    value escaping into an interface is a use.
    """
    write_tree(workdir, MOD_ESCAPES)
    assert shrink_report(ds, workdir, workdir / 'escapes') == golden("shrink_escapes")


def test_shrink_generic_variant(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    value escapes through a generic of the module called through a variant SSA has no body for: the package
    without its tests, when the variant read is the one with them. The module is then changed so the use is
    gone, and shrink must report what it kept quiet about, so the silence is shown to come from the use.
    """
    write_tree(workdir, MOD_GENERIC_VARIANT)
    report = shrink_report(ds, workdir, workdir / 'generic-variant')
    write_tree(workdir, {
        'generic-variant/cmd/gv/main.go': """package main

import (
	"example.com/gv/internal/p"
	"example.com/gv/internal/q"
	"example.com/gv/internal/s"
)

func main() {
	_ = p.Make()
	_ = p.MakeU()
	_ = q.Encode(1)
	_ = s.Wrap(2)
}
""",
    })
    without = ds(["shrink"], cwd=workdir / 'generic-variant')
    assert report + "\n## shrink once the use is gone\n" + without.transcript == golden("shrink_generic_variant")


def test_shrink_nested_module_generic(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins the same
    for a nested module calling a generic of the main module, which its load has only as an import. The module
    is then changed so the use is gone, and shrink must report what it kept quiet about, so the silence is
    shown to come from the use.
    """
    write_tree(workdir, MOD_NESTED_MODULE_GENERIC)
    report = shrink_report(ds, workdir, workdir / 'nested-module-generic')
    write_tree(workdir, {
        'nested-module-generic/tools/tools.go': """package tools

import (
	"example.com/ng/internal/a"
	"example.com/ng/internal/q"
)

func Use() string { _ = a.Make(); return q.Encode(1) }
""",
    })
    without = ds(["shrink"], cwd=workdir / 'nested-module-generic')
    assert report + "\n## shrink once the use is gone\n" + without.transcript == golden("shrink_nested_module_generic")


def test_shrink_const_sets(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    const block of one exported type of the package is judged as a whole, with its type.
    """
    write_tree(workdir, MOD_CONST_SETS)
    assert shrink_report(ds, workdir, workdir / 'const-sets') == golden("shrink_const_sets")


def test_shrink_type_param_sets(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins the
    literals and conversions that write a struct's fields through the type set of a type parameter: a named
    struct as the constraint, an intersection, an interface term inside a union, and two structs sharing one
    underlying type.
    """
    write_tree(workdir, MOD_TYPEPARAM_SETS)
    assert shrink_report(ds, workdir, workdir / 'typeparam-sets') == golden("shrink_type_param_sets")


def test_shrink_fix_withheld(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins the
    reports whose fix is withheld for a reason other than the rename: build-excluded and generated files,
    example functions, and -ldflags -X.
    """
    write_tree(workdir, MOD_FIX_WITHHELD)
    assert shrink_report(ds, workdir, workdir / 'fix-withheld') == golden("shrink_fix_withheld")


def test_shrink_rename_guards(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins what the
    rename rewrites and every guard that withholds it.
    """
    write_tree(workdir, MOD_RENAME_GUARDS)
    assert shrink_report(ds, workdir, workdir / 'rename-guards') == golden("shrink_rename_guards")


def test_shrink_ignores(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins where
    //declscope:ignore overexported binds, and when it is itself reported unused.
    """
    write_tree(workdir, MOD_IGNORES)
    assert shrink_report(ds, workdir, workdir / 'ignores') == golden("shrink_ignores")


def test_shrink_ignores_excluded(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which runs the same
    module with b/tagged.go left out. Every report must read the same: an ignore needed only in one
    configuration must pass the other as well.
    """
    write_tree(workdir, MOD_IGNORES)
    assert shrink_report(ds, workdir, workdir / 'ignores', env={'GOFLAGS': '-tags=never'}) == golden("shrink_ignores_excluded")


def test_shrink_not_judged(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins the
    packages that are never judged, and that the internal ones among them are named with the reason.
    """
    write_tree(workdir, MOD_NOT_JUDGED)
    assert shrink_report(ds, workdir, workdir / 'not-judged') == golden("shrink_not_judged")


def test_shrink_nested_module(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module whose path extends an internal/ parent keeps every package under it unjudged.
    """
    write_tree(workdir, MOD_NESTED_MODULE)
    assert shrink_report(ds, workdir, workdir / 'nested-module') == golden("shrink_nested_module")


def test_shrink_nested_module_in_underscore_dir(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module in a directory ./... skips is still found and loaded, so the use it makes of a.F counts and
    nothing is left unjudged. The module is then changed so the use is gone, and shrink must report what it
    kept quiet about, so the silence is shown to come from the use.
    """
    write_tree(workdir, MOD_NESTED_MODULE_IN_UNDERSCORE_DIR)
    report = shrink_report(ds, workdir, workdir / 'nested-module-in-underscore-dir')
    write_tree(workdir, {
        'nested-module-in-underscore-dir/_tools/tools.go': """package tools
""",
    })
    without = ds(["shrink"], cwd=workdir / 'nested-module-in-underscore-dir')
    assert report + "\n## shrink once the use is gone\n" + without.transcript == golden("shrink_nested_module_in_underscore_dir")


def test_shrink_nested_module_uses(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    loaded nested module counts as an importer in every way the evidence reads: a call, a static interface
    satisfaction, a value that escapes into fmt, and a name written in a file its build excludes.
    """
    write_tree(workdir, MOD_NESTED_MODULE_USES)
    assert shrink_report(ds, workdir, workdir / 'nested-module-uses') == golden("shrink_nested_module_uses")


def test_shrink_nested_module_excluded(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    build-excluded file of a nested module is reached through its compiled sibling, as one of the main module
    is: a package-level variable beside it may hold a value of the package's types.
    """
    write_tree(workdir, MOD_NESTED_MODULE_EXCLUDED)
    assert shrink_report(ds, workdir, workdir / 'nested-module-excluded') == golden("shrink_nested_module_excluded")


def test_shrink_nested_module_above(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module whose path lies above an internal/ parent is loaded too: tools is example.com/nan/x, and its
    package example.com/nan/x/y/z may import example.com/nan/x/y/internal/foo. Its use of foo.Hello counts,
    and foo.Bye is judged.
    """
    write_tree(workdir, MOD_NESTED_MODULE_ABOVE)
    assert shrink_report(ds, workdir, workdir / 'nested-module-above') == golden("shrink_nested_module_above")


def test_shrink_nested_module_elsewhere(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module reading the module from another directory leaves the range unjudged, and says where it reads
    it from.
    """
    write_tree(workdir, MOD_NESTED_MODULE_ELSEWHERE)
    assert shrink_report(ds, workdir, workdir / 'nested-module-elsewhere') == golden("shrink_nested_module_elsewhere")


def test_shrink_nested_module_broken(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module that does not type-check leaves the range unjudged, rather than reading as a module that
    uses nothing.
    """
    write_tree(workdir, MOD_NESTED_MODULE_BROKEN)
    assert shrink_report(ds, workdir, workdir / 'nested-module-broken') == golden("shrink_nested_module_broken")


def test_shrink_build_list_replace(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    module of the build list whose path lies in the range, replaced by a directory outside the tree, leaves
    the range unjudged: the build compiles that copy, not the nested module ext, and only the copy uses
    a.Used.
    """
    write_tree(workdir, MOD_BUILD_LIST_REPLACE)
    assert shrink_report(ds, workdir, workdir / 'build-list-replace') == golden("shrink_build_list_replace")


def test_shrink_build_list_vendored(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins the same
    in vendor mode, where the go command computes no build list: vendor/modules.txt names ext, and the build
    reads its vendored copy, which uses a.Old.
    """
    write_tree(workdir, MOD_BUILD_LIST_VENDORED)
    assert shrink_report(ds, workdir, workdir / 'build-list-vendored') == golden("shrink_build_list_vendored")


def test_shrink_nested_build_list(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    module of a nested module's build list whose path lies in the range, replaced by a directory outside the
    tree, withholds the fixes in the range when the copy imports a package in it, and keeps the reports: s/n
    builds with that copy of t, not the nested module t, and only the copy uses x.Foo. b/g builds the copy of
    u only under the never tag, and it uses z.Baz, so z's fix is withheld too. The range of y, which no copy
    imports, keeps its fix. The wants pin the reports.
    """
    write_tree(workdir, MOD_NESTED_BUILD_LIST)
    assert shrink_report(ds, workdir, workdir / 'nested-build-list/m') == golden("shrink_nested_build_list")


def test_shrink_workspace_unlisted_nested(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module the go.work does not list is loaded from its own go.mod, outside the workspace, so its use
    of a.Used counts and a.Unused is judged.
    """
    write_tree(workdir, MOD_WORKSPACE_UNLISTED)
    assert shrink_report(ds, workdir, workdir / 'workspace-unlisted/m') == golden("shrink_workspace_unlisted_nested")


def test_shrink_nested_own_workspace(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    nested module with a go.work of its own is loaded through it: its go.mod does not require the main module,
    which only its go.work uses, so x.Foo counts and x.Bar is judged.
    """
    write_tree(workdir, MOD_NESTED_OWN_WORKSPACE)
    assert shrink_report(ds, workdir, workdir / 'nested-own-workspace') == golden("shrink_nested_own_workspace")


def test_shrink_nested_module_in_testdata(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins the same
    for a nested module one level below a directory ./... skips.
    """
    write_tree(workdir, MOD_NESTED_MODULE_IN_TESTDATA)
    assert shrink_report(ds, workdir, workdir / 'nested-module-in-testdata') == golden("shrink_nested_module_in_testdata")


def test_shrink_module_under_internal(ds, workdir):
    """CATCHES: a shrink that reports a different set of overexported declarations, words a withheld fix or a
    skipped package differently, or rewrites different files under -fix, on this module, which pins that a
    package whose path runs through internal/ is still an exposure root when a module this run does not load
    may import it.
    """
    write_tree(workdir, MOD_MODULE_UNDER_INTERNAL)
    assert shrink_report(ds, workdir, workdir / 'module-under-internal') == golden("shrink_module_under_internal")
