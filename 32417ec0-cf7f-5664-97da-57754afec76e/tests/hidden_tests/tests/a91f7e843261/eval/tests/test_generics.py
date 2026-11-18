"""Generic code: members of generic types, and fields written through a type parameter's type set."""

from conftest import GO_MOD, read_golden, write_tree


def golden(name):
    return read_golden(__file__, name)


USER = """package x

type userA struct{ n int }

type userB struct{ n int }

type userC struct{ m string }

type userList[T any] struct {
	items []T
	size  int
}

func (l *userList[T]) push(v T) { l.items = append(l.items, v); l.size++ }
"""


def run_all(ds):
    text = ds(["./..."])
    surplus = ds(["-config", "strict.yaml", "./..."])
    shape = ds(["inspect", "-format=json", "."])
    return "\n".join([text.transcript, surplus.transcript, shape.transcript])


def test_generic_type_members(ds, workdir):
    """CATCHES: an analyzer that does not normalize an instantiated generic's fields and methods to their
    origin, so uses through userList[int] or inside a generic function go unreported."""
    write_tree(workdir, {
        "go.mod": GO_MOD, "strict.yaml": "rules:\n  surplus: strict\n", "user.go": USER,
        "order.go": "package x\n\nfunc orderFill[T any](l *userList[T], v T) int { l.push(v); return l.size }\n\n"
                    "func orderInts() int {\n\tvar l userList[int]\n\tl.push(1)\n\treturn len(l.items) + orderFill(&l, 2)\n}\n\n"
                    "var _ = orderInts\n",
    })
    assert run_all(ds) == golden("generic_members")


def test_literal_through_a_union_of_structs(ds, workdir):
    """CATCHES: an analyzer that does not count P{1}, for P constrained to userA | userB, as writing the n field
    of both structs, or that counts it for a struct outside the union."""
    write_tree(workdir, {
        "go.mod": GO_MOD, "strict.yaml": "rules:\n  surplus: strict\n", "user.go": USER,
        "order.go": "package x\n\ntype orderSet interface{ userA | userB }\n\nfunc orderMake[P orderSet]() P { return P{1} }\n\n"
                    "var _ = orderMake[userA]\n\nvar _ = userC{}\n",
    })
    assert run_all(ds) == golden("union_literal")


def test_literal_through_an_intersection_and_comparable(ds, workdir):
    """CATCHES: a type set computation that mishandles an interface embedding another constraint and
    comparable, so the fields written by P{} are not found."""
    write_tree(workdir, {
        "go.mod": GO_MOD, "strict.yaml": "rules:\n  surplus: strict\n", "user.go": USER,
        "order.go": "package x\n\ntype orderSet interface{ userA | userB }\n\ntype orderBoth interface {\n\torderSet\n\tcomparable\n}\n\n"
                    "func orderMake[P orderBoth]() P { return P{n: 2} }\n\nvar _ = orderMake[userB]\n",
    })
    assert run_all(ds) == golden("intersection_literal")


def test_conversion_through_a_pointer_core(ds, workdir):
    """CATCHES: an analyzer that does not follow a constraint whose core type is a pointer to a struct, so a
    literal of the pointed-to struct or a conversion through it is missed."""
    write_tree(workdir, {
        "go.mod": GO_MOD, "strict.yaml": "rules:\n  surplus: strict\n", "user.go": USER,
        "order.go": "package x\n\ntype orderPtr interface{ ~*userA }\n\nfunc orderNew[P orderPtr]() P { return P(&userA{n: 3}) }\n\n"
                    "type orderMine struct{ n int }\n\nfunc orderConv[P interface{ userA | userB }](o orderMine) P { return P(o) }\n\n"
                    "var _ = orderNew[*userA]\n\nvar _ = orderConv[userA]\n",
    })
    assert run_all(ds) == golden("pointer_core")


def test_constraints_with_no_struct_core(ds, workdir):
    """CATCHES: a type set computation that fails or invents a struct for constraints with no core struct: a
    union of integer terms built from an embedded union, a method-only interface, an empty intersection,
    and a struct union whose members differ."""
    write_tree(workdir, {
        "go.mod": GO_MOD, "strict.yaml": "rules:\n  surplus: strict\n", "user.go": USER,
        "order.go": "package x\n\ntype orderSigned interface{ ~int | ~int8 }\n\ntype orderNum interface{ orderSigned | int16 }\n\n"
                    "func orderConv[P orderNum](v int) P { return P(v) }\n\n"
                    "type orderStringer interface{ String() string }\n\nfunc orderS[P orderStringer](p P) string { return p.String() }\n\n"
                    "type orderNone interface {\n\tint\n\tstring\n}\n\nfunc orderNothing[P orderNone]() {}\n\n"
                    "type orderMixed interface{ userA | userC }\n\nfunc orderZero[P orderMixed]() P { var p P; return p }\n\n"
                    "var _ = orderConv[int]\nvar _ = orderS[interface{ String() string }]\nvar _ = orderZero[userC]\n",
    })
    assert run_all(ds) == golden("no_struct_core")


def test_type_param_sets_in_shrink(ds, workdir):
    """CATCHES: a shrink that reports the fields of an exported struct which a generic function in another
    package writes through its type parameter, or that keeps a field nothing writes."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/a/a.go": "package a\n\ntype Point struct {\n\tX int\n\tY int\n}\n\ntype Pair struct {\n\tL int\n\tR int\n}\n\n"
                           "func Origin() Point { return Point{} }\n\nfunc Zero() Pair { return Pair{} }\n",
        "b/b.go": "package b\n\nimport \"example.com/app/internal/a\"\n\n"
                  "func Make[P interface{ a.Point }]() P { return P{1, 2} }\n\nvar _ = Make[a.Point]\n\nvar _ = a.Origin\n\n"
                  "var _ = a.Zero\n",
    })
    out = ds(["shrink"])
    assert out.transcript == golden("shrink_type_params")
