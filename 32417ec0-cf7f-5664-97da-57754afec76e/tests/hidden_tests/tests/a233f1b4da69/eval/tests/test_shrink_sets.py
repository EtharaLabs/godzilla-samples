"""declscope shrink on const sets, on literals written through type parameters, and on values that escape into
an interface where reflection reads them."""

from conftest import assert_golden, gomod, transcript, write_files

MOD = "example.com/sets"


def shrink_fix(run, workdir, files, fixed):
    """One -fix run: the reports it leaves without a fix, and the files it rewrote."""
    write_files(workdir, {"go.mod": gomod(MOD), **files})
    return transcript(run(["shrink", "-fix"]), workdir, fixed)


def shrink(run, workdir, files):
    write_files(workdir, {"go.mod": gomod(MOD), **files})
    return transcript(run(["shrink"]), workdir)


def test_const_block_of_one_type_is_judged_as_a_set(run, workdir):
    """CATCHES: a shrink that judges each value of an enum alone: a used value or a used type keeps the whole
    block, an unused set goes together; a lone constant, a mixed block and one of another package's type are
    judged on their own."""
    out = shrink(run, workdir, {
        "internal/e/e.go": """package e

type RequestStatus string

const (
	StUnclaimed RequestStatus = "unclaimed"
	StClaimed   RequestStatus = "claimed"
	StDone      RequestStatus = "done"
)

type ItemStatus int

const (
	_ ItemStatus = iota
	ItemInFridge
	ItemUsedUp
)

type Due string

const (
	DueSoon Due = "soon"
	DueWeek Due = "week"
)

const DefaultDue Due = DueWeek

const (
	MixedDue Due = "mixed"
	Mixed        = 10
)

type Lonely int

const (
	LonelyA Lonely = iota
	LonelyB
)

type Carried int

const (
	CarriedA Carried = iota
	CarriedB
)

func Current() Carried { return CarriedA }
""",
        "b/b.go": """package b

import "example.com/sets/internal/e"

var (
	_ = e.StClaimed
	_ e.ItemStatus
	_ e.Due
	_ = e.Mixed
	_ = e.Current()
)
""",
    })
    assert_golden(out, __file__, "const_sets")


def test_const_set_held_by_one_kept_value(run, workdir):
    """CATCHES: a fix that unexports the other values of a const block when one value keeps its name (an ignore,
    or a build-excluded file using it), splitting the set; an ignore over a value of a silenced type is unused."""
    out = shrink_fix(run, workdir, {
        "internal/e/e.go": """package e

type Held int

const (
	//declscope:ignore overexported // kept on purpose
	HeldA Held = iota
	HeldB
)

//declscope:ignore overexported // kept on purpose
type Silent int

const (
	SilentA Silent = iota
	//declscope:ignore overexported
	SilentB
)

type Excluded int

const (
	ExcludedA Excluded = iota
	ExcludedB
)

type Gone int

const (
	GoneA Gone = iota
	GoneB
)
""",
        "b/b_never.go": '//go:build never\n\npackage b\n\nimport "example.com/sets/internal/e"\n\nvar _ = e.ExcludedA\n',
    }, ("internal/e/e.go",))
    assert_golden(out, __file__, "const_sets_held")


def test_literals_through_type_parameters(run, workdir):
    """CATCHES: a shrink that misses the fields another package writes through a type parameter's type set: the
    constraint itself, a conversion, an intersection narrowing a union, an interface term of a union, and two structs
    sharing an underlying type."""
    out = shrink(run, workdir, {
        "internal/a/a.go": """package a

type Named struct{ X, Y int }

type Converted struct{ X, Y int }

type Narrow struct{ X, Y int }

type Wide struct {
	X int
	Y int
}

type Via struct{ X, Y int }

type Left struct{ X, Y int }

type Right struct{ X, Y int }
""",
        "b/b.go": """package b

import "example.com/sets/internal/a"

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
    })
    assert_golden(out, __file__, "type_param_literals")


def test_tilde_term_absorbing_a_named_struct(run, workdir):
    """CATCHES: a type-set computation that drops a named struct a ~struct term absorbs, so its fields would be
    renamed while a literal of the type parameter still writes them by position."""
    out = shrink(run, workdir, {
        "internal/a/a.go": "package a\n\ntype S struct{ X int }\n\ntype T struct{ Q int }\n",
        "b/b.go": """package b

import "example.com/sets/internal/a"

func Make[P interface{ ~struct{ X int } | a.S }]() P { return P{1} }

func Keep[P interface{ a.T | ~int }](p P) P { return p }
""",
    })
    assert_golden(out, __file__, "tilde_absorbed")


def test_type_set_that_cannot_be_computed_withholds_the_fix(run, workdir):
    """CATCHES: a shrink that treats a literal through a type parameter whose type set is too large to compute as
    writing nothing (it may write any of the structs written), instead of keeping the report and withholding the
    fix."""
    terms = " | ".join(f"~[{i}]int" for i in range(1, 102))
    out = shrink_fix(run, workdir, {
        "internal/a/a.go": "package a\n\ntype S struct{ X int }\n\nfunc Free() {}\n",
        "b/b.go": f"""package b

import "example.com/sets/internal/a"

type big interface {{
	{terms} | *a.S
}}

func Make[P big](p P) P {{ return P(p) }}

var _ = a.S{{}}
""",
    }, ("internal/a/a.go",))
    assert_golden(out, __file__, "guessed_type_set")


def test_values_escaping_into_interfaces(run, workdir):
    """CATCHES: a shrink that reports a type, field or method a value reaches after escaping into an interface
    (a sink taking any, behind a pointer, a generic instantiated with it, a generic declared outside the module, every kind of
    container, a func field's result); a compile-time-only satisfaction and a never-run closure are no escape."""
    out = shrink(run, workdir, {
        "internal/e/e.go": """package e

import "sync/atomic"

func sink(...any) {}

type writer interface{ Write(p []byte) (int, error) }

type Printed struct {
	Field int
}

func (Printed) Method() {}

func printed() { sink(&Printed{}) }

type Shown struct{}

func show[T any](v T) { sink(v) }

func useShown() { show(Shown{}) }

type Held struct{}

var _ atomic.Pointer[Held]

type Bag struct {
	S []Elem
	R [1]Elem
	C chan Elem
	M map[Elem]Elem
	G Gen[Elem]
}

type Elem struct{}

type Gen[T any] struct{ v T }

func bag() { sink(Bag{}) }

type Carrier struct {
	Make func() Result
}

type Result struct {
	Value int
}

func carry() { sink(Carrier{}) }

type Wr struct{}

func (Wr) Write(p []byte) (int, error) { return len(p), nil }

var _ writer = Wr{}

type Dead struct{}

var _ = func() { sink(Dead{}) }

type Failed struct{ Err error }

func failed() { sink(Failed{}) }

var _, _, _, _, _, _, _ = printed, useShown, bag, carry, Gen[int]{}.v, failed, Wr{}
""",
    })
    assert_golden(out, __file__, "escapes")


def test_struct_tags_declare_reflection(run, workdir):
    """CATCHES: a shrink that ignores struct tags (json, xml, yaml on a nested unnamed struct or an alias): a tag in
    key:"value" form says a marshaller reads the struct, untagged fields too; an empty tag declares nothing; a json
    round trip through a conversion keeps the fields but not the converted type's name."""
    out = shrink(run, workdir, {
        "internal/e/e.go": """package e

func sink(any) {}

type Record struct {
	Name string
}

type Wire Record

func encode(r Record) { sink(Wire(r)) }

type Tagged struct {
	Name  string `json:"name"`
	Count int    `xml:"count"`
	Plain int
}

type Bare struct {
	Field int ``
}

var _ = Bare{}.Field

type Config struct {
	Server struct {
		Port int `yaml:"port"`
	}
}

type Conf = struct {
	Port int `yaml:"port"`
}

type Relay struct {
	Server Conf
}

var _ = Config{}.Server.Port + Relay{}.Server.Port + Tagged{}.Count

var _ = encode
""",
    })
    assert_golden(out, __file__, "tags")


def test_generic_of_the_module_called_through_a_test_variant(run, workdir):
    """CATCHES: a shrink that loses an escape when the generic doing it is called through the variant of its
    package without tests (SSA has no body for it there), and so reports fields reflection may read."""
    out = shrink(run, workdir, {
        "cmd/gv/main.go": """package main

import (
	"example.com/sets/internal/p"
	"example.com/sets/internal/q"
	"example.com/sets/internal/s"
)

func main() {
	println(q.Encode(p.Make()))
	println(s.Wrap(p.MakeU()))
}
""",
        "internal/p/p.go": """package p

type T struct{ Secret int }

func Make() T { return T{Secret: 1} }

type U struct{ Hidden int }

func MakeU() U { return U{Hidden: 1} }

type V struct{ Lost int }
""",
        "internal/q/q.go": """package q

var sunk []any

func Encode[V any](v V) string {
	sunk = append(sunk, v)
	return ""
}
""",
        "internal/q/q_test.go": 'package q\n\nimport "testing"\n\nfunc TestEncode(t *testing.T) { _ = Encode(1) }\n',
        "internal/s/s.go": 'package s\n\nimport "example.com/sets/internal/q"\n\nfunc Wrap[V any](v V) string { return q.Encode(v) }\n',
    })
    assert_golden(out, __file__, "generic_variant")
