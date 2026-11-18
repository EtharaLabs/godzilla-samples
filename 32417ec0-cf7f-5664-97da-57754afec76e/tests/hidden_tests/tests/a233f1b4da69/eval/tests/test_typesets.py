"""Type sets of type parameters, as declscope computes them for literals and conversions written through a type
parameter: unions, intersections, tilde terms, interface terms and the universe. Both the analyzer and shrink read
the fields such a literal or conversion writes without naming them."""

from conftest import assert_golden, gomod, transcript, write_files

STRUCTS = """package a

type A struct{ X int }

type B struct{ X int }

type C struct{ X int }

type D struct{ X int }

type E struct{ X int }

type F struct{ X int }

type G struct{ Y int }

type Unused struct{ X int }
"""


def shrink(run, workdir, b_go):
    write_files(workdir, {"go.mod": gomod("example.com/ts"), "internal/a/a.go": STRUCTS, "b/b.go": b_go})
    return transcript(run(["shrink"]), workdir)


def test_union_with_interface_terms_and_absorption(run, workdir):
    """CATCHES: a type-set computation that drops a named struct a ~struct term absorbs (written through an interface
    term so go/types accepts it), or that does not take in the later terms an inserted tilde term covers; the fields
    of every struct in the set are written by the literal, and only Unused stays reported."""
    out = shrink(run, workdir, """package b

import "example.com/ts/internal/a"

type tildeX interface{ ~struct{ X int } }

func Absorbed[P interface{ tildeX | a.A }]() P { return P{1} }

func TakenIn[P interface{ a.B | a.C | tildeX }]() P { return P{2} }
""")
    assert_golden(out, __file__, "absorbed")


def test_intersections_of_unions(run, workdir):
    """CATCHES: an intersection of two unions mixing exact and tilde terms computed wrongly: the set keeps exact
    terms an overlapping tilde term narrows to, and a conversion pairs the fields of each struct in it."""
    out = shrink(run, workdir, """package b

import "example.com/ts/internal/a"

type U struct{ X int }

type tildeX interface{ ~struct{ X int } }

type left interface{ a.D | a.E | tildeX }

type right interface{ a.D | tildeX }

func Both[P interface {
	left
	right
}](p P) U {
	return U(p)
}

func Narrowed[P interface {
	a.F | a.D
	a.F
}](p P) U {
	return U(p)
}
""")
    assert_golden(out, __file__, "intersections")


def test_universe_and_diamonds(run, workdir):
    """CATCHES: a type-set computation that fails on a union holding any (the set of every type, which pairs nothing),
    or on a constraint reaching one interface through two embedding paths."""
    out = shrink(run, workdir, """package b

import "example.com/ts/internal/a"

type U struct{ X int }

func Wide[P interface{ any | a.A }](p P) any { return any(p) }

type tildeX interface{ ~struct{ X int } }

type viaL interface{ tildeX }

type viaR interface{ tildeX }

func Diamond[P interface {
	viaL
	viaR
	a.B | a.C
}](p P) U {
	return U(p)
}
""")
    assert_golden(out, __file__, "universe")


def test_literals_whose_core_type_is_not_a_struct(run, workdir):
    """CATCHES: a literal through a pointer whose element is not a struct ([]*[]int{{1}}), or through a type
    parameter whose core type is a pointer to a slice, treated as writing a struct's fields; a pointer type
    parameter whose element is a struct type set does write them."""
    out = shrink(run, workdir, """package b

import "example.com/ts/internal/a"

var _ = []*[]int{{1}}

func Slices[Q interface{ ~[]int }, P interface{ *Q }]() []P { return []P{{1}} }

func Ptrs[Q interface{ a.G }, P interface{ *Q }]() []P { return []P{{1}} }
""")
    assert_golden(out, __file__, "non_struct_core")


def test_analyzer_reads_type_sets_for_boundary(run, workdir):
    """CATCHES: an analyzer that misses a field crossing a namespace by an unkeyed literal or a conversion through a
    type parameter's type set (union, intersection, tilde term), reporting nothing where the field is written."""
    write_files(workdir, {
        "go.mod": gomod("example.com/ts"),
        "user.go": "package p\n\ntype userA struct{ x int }\n\ntype userB struct{ x int }\n\ntype userC struct{ y int }\n",
        "order.go": """package p

type orderU struct{ x int }

type tildeX interface{ ~struct{ x int } }

func orderLit[P interface{ tildeX | userA }]() P { return P{1} }

func orderConv[P interface {
	userA | userB | tildeX
	userB | tildeX
}](p P) orderU {
	return orderU(p)
}

func orderPtr[Q interface{ userC }, P interface{ *Q }]() []P { return []P{{2}} }

var _, _, _ = orderLit[userA], orderConv[userB], orderPtr[userC, *userC]
""",
    })
    assert_golden(transcript(run(["./..."]), workdir), __file__, "analyzer")


def test_empty_type_set(run, workdir):
    """CATCHES: a type-set computation that fails or loops on a constraint no type satisfies (int and string at
    once): a value of such a type parameter may still be converted to an interface, which pairs nothing."""
    out = shrink(run, workdir, """package b

import "example.com/ts/internal/a"

func Never[P interface {
	int
	string
}](p P) any {
	return any(p)
}

var _ = a.A{X: 1}
""")
    assert_golden(out, __file__, "empty_type_set")
