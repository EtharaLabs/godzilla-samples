"""The naming rule's rename fix: when the rename to the namespace-carrying name is offered, and what -fix rewrites,
for methods filed away from their type and for types embedded through pointers, interfaces and generics."""

from conftest import assert_golden, changes, gomod, snapshot, transcript, write_files

ALWAYS = "rules:\n  naming:\n    qualify: always\n"


def report_and_fix(run, workdir, files):
    write_files(workdir, {"go.mod": gomod("example.com/q"), ".declscope.yaml": ALWAYS, **files})
    before = snapshot(workdir)
    report = transcript(run(["./..."]), workdir)
    fixed = transcript(run(["-fix", "./..."]), workdir) + changes(before, workdir)
    return report + "\n=== -fix\n" + fixed


def test_foreign_method_on_a_type_embedded_through_a_pointer(run, workdir):
    """CATCHES: a rename of a method filed away from its type that does not look through every type holding it: a
    struct embedding the type through a pointer that already has a field of the new name (withheld), or one embedding
    an interface (free); a method with no clash is renamed with every call."""
    out = report_and_fix(run, workdir, {
        "user.go": """package q

type userBase struct{}

type userIface interface{ userPing() }

type userHolder struct {
	*userBase
	userIface
	orderSpin int
}

type userFree struct {
	*userBase
	userIface
}

var _ = []any{userHolder{}, userFree{}}
""",
        "order.go": """package q

func (userBase) spin() {}

func (userBase) stop() {}

func orderUse(b userBase) { b.spin(); b.stop() }

var _ = orderUse
""",
    })
    assert_golden(out, __file__, "foreign_method_pointer")


def test_foreign_method_on_a_generic_type(run, workdir):
    """CATCHES: a rename of a method of a generic type, filed away from it, that misses a selection on an instance or
    on the type parameter's receiver."""
    out = report_and_fix(run, workdir, {
        "user.go": "package q\n\ntype userList[T any] struct{ items []T }\n\ntype userWrap struct{ userList[int] }\n\nvar _ = userWrap{}\n",
        "order.go": """package q

func (l *userList[T]) size() int { return len(l.items) }

func orderCount() int {
	var l userList[string]
	return l.size() + (&userWrap{}).size()
}

var _ = orderCount
""",
    })
    assert_golden(out, __file__, "foreign_method_generic")


def test_rename_withheld_when_the_new_name_is_bound_at_a_use(run, workdir):
    """CATCHES: the wrong rename that compiles and computes something else: a new name already bound by a parameter or
    local at a use site, or by an import of another file, must withhold the fix while a free one is renamed."""
    out = report_and_fix(run, workdir, {
        "imp.go": 'package q\n\nimport countCompare "cmp"\n\nvar _ = countCompare.Compare[int]\n',
        "count.go": """package q

var limit = 10

func add(countLimit int) int { return countLimit + limit }

func compare() int { return 0 }

func free() int { return add(1) + compare() }

var _ = free
""",
    })
    assert_golden(out, __file__, "captured")


def test_exported_names_keep_their_exportedness(run, workdir):
    """CATCHES: rules.naming.exported renaming Load to userLoad (unexporting the API) instead of UserLoad, or
    offering a rename for an exported declaration at all (the report stands, no fix)."""
    write_files(workdir, {
        "go.mod": gomod("example.com/q"),
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n",
        "user.go": "package q\n\nfunc Load() int { return id() }\n\nfunc id() int { return 1 }\n\ntype ID int\n",
    })
    before = snapshot(workdir)
    out = transcript(run(["-json", "./..."]), workdir)
    out += "\n=== -fix\n" + transcript(run(["-fix", "./..."]), workdir) + changes(before, workdir)
    assert_golden(out, __file__, "exported")
