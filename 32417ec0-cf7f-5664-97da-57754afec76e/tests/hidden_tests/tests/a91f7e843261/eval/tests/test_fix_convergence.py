"""One -fix pass over packages built so that a careless fix would break the build or create a new report.

Each case records the diagnostics, the same as -json with the fixes offered, the -fix run, every file afterwards, and the diagnostics left. The rewrite
must produce the same files and leave the same reports, so a fix that is withheld here must be withheld there.
"""

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


def converge_report(ds, workdir):
    before = ds(["./..."])
    offered = ds(["-json", "./..."])
    fix = ds(["-fix", "./..."])
    changed = snapshot_tree(workdir)
    after = ds(["./..."])
    return "\n".join([
        "## diagnostics", before.transcript,
        "## -json", offered.json_transcript,
        "## -fix", fix.transcript,
        "## tree after -fix", changed,
        "## diagnostics after -fix", after.transcript,
    ])


# boundary and qualify on the same declaration
CASE_01 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

func orderRun() int { return helper() }

var _ = orderRun
""",
    'user.go': """package x

func helper() int { return 1 }
""",
}

# foreign method an interface asks for
CASE_02 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

type orderT struct{ userHelp int }

type orderHelper interface{ help() int }

var _ orderHelper = orderT{}

var _ = orderT{}.userHelp
""",
    'user.go': """package x

func (o orderT) help() int { return 1 }
""",
}

# embedded type beside a field of its new name
CASE_03 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

func orderRun() int { return 1 }

var _ = orderRun
""",
    'user.go': """package x

type item struct{ n int }

type userHolder struct {
	item
	userItem int
}

var _ = userHolder{}.item.n
""",
}

# field of a single-line struct
CASE_04 = {
    'order.go': """package x

func orderRun(u *User) string { return u.name }

var _ = orderRun
""",
    'user.go': """package x

type User struct{ name string }
""",
}

# declaration already carrying a doc comment
CASE_05 = {
    'order.go': """package x

func orderRun() int { return userCache() }

var _ = orderRun
""",
    'user.go': """package x

// userCache caches.
func userCache() int { return 1 }
""",
}

# grouped var and const blocks
CASE_06 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

func orderRun() int { return seed + other + limit }

var _ = orderRun
""",
    'user.go': """package x

var (
	seed  = 1
	other = 2
)

const (
	limit = 3
)
""",
}

# type and member crossing together
CASE_07 = {
    'order.go': """package x

func Order() string {
	e := entry{key: "x"}
	return e.key
}
""",
    'user.go': """package x

type entry struct {
	key string
}
""",
}

# rename target already taken
CASE_08 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

func orderRun() int { return taken() + userTaken() }

var _ = orderRun
""",
    'user.go': """package x

func taken() int { return 1 }

func userTaken() int { return 2 }
""",
}

# method on a type belonging to another namespace
CASE_09 = {
    'order.go': """package x

func (u *User) bump() { u.ID++ }

func OrderRun(u *User) { u.bump() }
""",
    'user.go': """package x

type User struct{ ID int }
""",
}

# qualify required in a single-namespace package
CASE_10 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'only.go': """package x

func helper() int { return 1 }

type shape struct{ side int }

func Exported() int { return helper() + shape{}.side }
""",
}

# type embedded, and selected through the embedding, in its own namespace
CASE_11 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

func OrderRun() {}
""",
    'user.go': """package x

type count struct{ n int }

type User struct{ *count }

func (u *User) Total() int { return u.count.n }
""",
}

# type embedded from another namespace
CASE_12 = {
    'order.go': """package x

type Order struct{ userCount }
""",
    'user.go': """package x

type userCount struct{ n int }
""",
}

# scope stated by a directive, which must not be rewritten
CASE_13 = {
    'order.go': """package x

func orderRun() int { return userForced() }

var _ = orderRun
""",
    'user.go': """package x

//declscope:private
func userForced() int { return 1 }
""",
}

# fields a type's directive widens for nothing, under strict
CASE_14 = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'order.go': """package x

func orderRun(a account, t tiny) int { return a.id + t.id }

var _ = orderRun
""",
    'user.go': """package x

//declscope:shared
type account struct {
	id int

	// balance is local.
	balance int
	left, right int
}

//declscope:shared
type tiny struct{ id int; n int }

func userLocal(a account, t tiny) int { return a.balance + a.left + a.right + t.n }

var _ = userLocal
""",
}

# declarations a file's directive widens for nothing, under strict
CASE_15 = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'order.go': """package x

func orderRun() int { return userShared() + userPair().x }

var _ = orderRun
""",
    'user.go': """//declscope:shared

package x

// userShared is called from order.go.
func userShared() int { return userLocal() }

// userLocal is not.
func userLocal() int { return 1 }

var userA, userB = 1, 2

type box struct {
	n int
}

type pair struct {
	x int
	y int
}

func userPair() pair { return pair{} }

var _ = userA + userB + box{}.n + userPair().y
""",
}

# a field whose narrowing would leave the directive unused, under strict
CASE_16 = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'user.go': """package x

//declscope:shared
type DTO struct {
	Name string
	seq  int
}

func userSeq(d DTO) int { return d.seq }

var _ = userSeq
""",
}

# boundary fix on a type whose fields nobody else reads, under strict
CASE_17 = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'order.go': """package x

func orderRun(i item) int { return i.shared }

var _ = orderRun
""",
    'user.go': """package x

type item struct {
	shared int

	// count is local.
	count int
}

func userCount(i item) int { return i.count }

var _ = userCount
""",
    'user_test.go': """package x

import "testing"

func TestItem(t *testing.T) {
	if userCount(item{count: 1}) != 1 {
		t.Fatal("no")
	}
}
""",
}

# redundant directives at every level, under unused strict
CASE_18 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'order.go': """package x

func OrderRun() int { return 1 }
""",
    'user.go': """//declscope:private

package x

// userDoc is documented.
//
//declscope:private
func userDoc() int { return 1 }

//declscope:private
type userShape struct {
	//declscope:private
	side int
	edge int //declscope:private
}

//declscope:private
var (
	//declscope:private
	userSeed = 1
	userLimit = 2
)

var _ = userDoc() + userShape{}.side + userShape{}.edge + userSeed + userLimit
""",
}

# a spec narrowing its block, under unused strict
CASE_19 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'user.go': """//declscope:private

package x

//declscope:shared
var (
	//declscope:private
	userA = 1
)

var _ = userA
""",
}

# a redundant directive on a crossing declaration, under unused strict
CASE_20 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'order.go': """package x

func OrderRun() int { return userShared() + userBox{}.n }
""",
    'user.go': """package x

//declscope:private
func userShared() int { return 1 }

//declscope:private
type userBox struct {
	n int
}
""",
}

# a field's redundant directive under a type the boundary fix widens, under unused strict
CASE_21 = {
    '.declscope.yaml': """rules:
  unused: strict
  surplus: strict
""",
    'order.go': """package x

func OrderRun() entry { return entry{} }
""",
    'user.go': """package x

type entry struct {
	//declscope:private
	key string
}

func userKey(e entry) string { return e.key }

var _ = userKey
""",
}

# a block every spec overrides, under unused strict
CASE_22 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'user.go': """package x

//declscope:private
//declscope:ignore directive
var (
	//declscope:private
	userA = 1
	//declscope:shared
	UserB = 2
)

var _ = userA
""",
}

# a spec restating a block a bare ignore answers, under unused strict
CASE_23 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'user.go': """package x

//declscope:private
//declscope:ignore
var (
	//declscope:private
	UserA = 1
)
""",
}

# a shared directive restating the shared default, under unused strict
CASE_24 = {
    '.declscope.yaml': """defaults:
  unexported: shared
rules:
  unused: strict
""",
    'user.go': """package x

//declscope:shared
func userHelper() int { return 1 }

//declscope:shared
//declscope:ignore surplus
func userQuiet() int { return 2 }

var _ = userHelper() + userQuiet()
""",
}

# a shared directive restating the file's, under unused and surplus strict
CASE_25 = {
    '.declscope.yaml': """rules:
  unused: strict
  surplus: strict
""",
    'order.go': """package x

func OrderRun() int { return userShared() }
""",
    'user.go': """//declscope:shared

package x

func userShared() int { return 1 }

//declscope:shared
func userLocal() int { return 2 }

var _ = userLocal()
""",
}

# a redundant directive on a declaration only a test uses from elsewhere, under unused strict
CASE_26 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'order_test.go': """package x

import "testing"

func TestOrder(t *testing.T) { _ = userShared() }
""",
    'user.go': """package x

//declscope:private
func userShared() int { return 1 }
""",
}

# a spec restating a block that keeps its report, under unused strict
CASE_27 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'order.go': """package x

var _ = userA
""",
    'user.go': """package x

//declscope:private
var (
	userA = 1
	//declscope:private
	userB = 2
)

var _ = userB
""",
}

# a spec restating a block that is reported but not redundant, under unused strict
CASE_28 = {
    '.declscope.yaml': """rules:
  unused: strict
  surplus: off
""",
    'user.go': """package x

//declscope:shared
var (
	//declscope:shared
	Exported = 1
	//declscope:private
	narrowed = 2
)

var _ = narrowed
""",
}

# a file-level directive one declaration overrides and one restates, under unused strict
CASE_29 = {
    '.declscope.yaml': """defaults:
  unexported: shared
rules:
  unused: strict
  surplus: off
""",
    'user.go': """//declscope:shared

package x

//declscope:private
func userNarrow() int { return 1 }

//declscope:shared
func userOwn() int { return 2 }

var _ = userNarrow() + userOwn()
""",
}

# a spec under a block that decides nothing, under surplus strict
CASE_30 = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'order.go': """package x

func OrderRun() int { return userShared + userF() }
""",
    'user.go': """//declscope:shared

package x

//declscope:shared
var (
	userShared = 1
	userLocal  = 2
)

func userF() int { return userLocal }

var _ = userF()
""",
}

# a field under a type that decides nothing, under surplus strict
CASE_31 = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'order.go': """package x

func OrderRun() int { return userEntry{}.userKey }
""",
    'user.go': """//declscope:shared

package x

//declscope:shared
type userEntry struct {
	userKey   int
	userSpare int
}

var _ = userEntry{}.userSpare
""",
}

# a field under an unnamed type that decides nothing, under surplus and unused strict
CASE_32 = {
    '.declscope.yaml': """rules:
  surplus: strict
  unused: strict
""",
    'order.go': """package x

func OrderRun() int { return userF() }
""",
    'user.go': """//declscope:shared

package x

func userF() int { return 1 }

//declscope:shared
type _ struct {
	UserWide  int
	userSpare int
}
""",
}

# an unnamed type one field takes, one restates and one overrides, under unused strict
CASE_33 = {
    '.declscope.yaml': """rules:
  unused: strict
  surplus: off
""",
    'user.go': """package x

//declscope:private
type _ struct {
	userTaken int
	//declscope:private
	userSame int
	//declscope:shared
	userWide int
}
""",
}

# an unnamed type whose report is kept beside a field that restates it, under unused strict
CASE_34 = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'user.go': """//declscope:shared

package x

func userF() int { return 1 }

//declscope:shared
type _ struct {
	userTaken int
	//declscope:shared
	userSame int
	//declscope:private
	userNarrow int
}

var _ = userF()
""",
}

# rename captured by a parameter or a local at a reference
CASE_35 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'foo.go': """package x

var count = 10

func Add(fooCount string) int { return len(fooCount) + count }

func Sub() int {
	fooCount := "x"
	return len(fooCount) - count
}
""",
}

# rename colliding with an import in another file
CASE_36 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'bar.go': """package x

import fooCount "strings"

func Bar(s string) string { return fooCount.ToUpper(s) }
""",
    'foo.go': """package x

var count = 10

func Add(x int) int { return x + count }
""",
}

# two qualify renames converging through a non-injective prefix
CASE_37 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'a.go': """package x

func bX() int { return 1 }

var _ = bX
""",
    'a_b.go': """package x

func x() int { return 2 }

var _ = x
""",
}

# reference in a generated file
CASE_38 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package x

func OrderRun() int { return helper() }
""",
    'user.go': """package x

//declscope:shared
func helper() int { return 1 }
""",
    'zz_gen.go': """// Code generated by a tool. DO NOT EDIT.

package x

func GenUse() int { return helper() }
""",
}

# reference in an omitted file
CASE_39 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: ondemand
filter:
  omit:
    - "**/ext.go"
""",
    'ext.go': """package x

func ExtUse() int { return helper() }
""",
    'order.go': """package x

func OrderRun() int { return helper() }
""",
    'user.go': """package x

//declscope:shared
func helper() int { return 1 }
""",
}

# declaration named by a go:linkname directive
CASE_40 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'foo.go': """package x

import _ "unsafe"

//go:linkname helper
func helper() int { return 1 }

func Exported() int { return helper() }
""",
}

# rename target declared only in the test variant
CASE_41 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'foo.go': """package x

var count = 10

func Add(x int) int { return x + count }
""",
    'foo_test.go': """package x

var fooCount = 1

var _ = fooCount
""",
}

# rename referenced from a test file
CASE_42 = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'foo.go': """package x

var count = 10

func Add(x int) int { return x + count }
""",
    'foo_test.go': """package x

import "testing"

func TestAdd(t *testing.T) {
	if Add(1) != 1+count {
		t.Fatal("unexpected")
	}
}
""",
}


def test_converge_boundary_and_qualify_on_the_same_declaration(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: boundary and qualify on the
    same declaration.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_01})
    assert converge_report(ds, workdir) == golden("boundary_and_qualify_on_the_same_declaration")


def test_converge_foreign_method_an_interface_asks_for(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: foreign method an interface
    asks for.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_02})
    assert converge_report(ds, workdir) == golden("foreign_method_an_interface_asks_for")


def test_converge_embedded_type_beside_a_field_of_its_new_name(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: embedded type beside a field
    of its new name.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_03})
    assert converge_report(ds, workdir) == golden("embedded_type_beside_a_field_of_its_new_name")


def test_converge_field_of_a_single_line_struct(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: field of a single-line
    struct.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_04})
    assert converge_report(ds, workdir) == golden("field_of_a_single_line_struct")


def test_converge_declaration_already_carrying_a_doc_comment(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: declaration already carrying
    a doc comment.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_05})
    assert converge_report(ds, workdir) == golden("declaration_already_carrying_a_doc_comment")


def test_converge_grouped_var_and_const_blocks(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: grouped var and const
    blocks.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_06})
    assert converge_report(ds, workdir) == golden("grouped_var_and_const_blocks")


def test_converge_type_and_member_crossing_together(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: type and member crossing
    together.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_07})
    assert converge_report(ds, workdir) == golden("type_and_member_crossing_together")


def test_converge_rename_target_already_taken(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: rename target already taken.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_08})
    assert converge_report(ds, workdir) == golden("rename_target_already_taken")


def test_converge_method_on_a_type_belonging_to_another_namespace(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: method on a type belonging
    to another namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_09})
    assert converge_report(ds, workdir) == golden("method_on_a_type_belonging_to_another_namespace")


def test_converge_qualify_required_in_a_single_namespace_package(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: qualify required in a
    single-namespace package.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_10})
    assert converge_report(ds, workdir) == golden("qualify_required_in_a_single_namespace_package")


def test_converge_type_embedded_and_selected_through_the_embedding_in_its_own_namespace(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: type embedded, and selected
    through the embedding, in its own namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_11})
    assert converge_report(ds, workdir) == golden("type_embedded_and_selected_through_the_embedding_in_its_own_namespace")


def test_converge_type_embedded_from_another_namespace(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: type embedded from another
    namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_12})
    assert converge_report(ds, workdir) == golden("type_embedded_from_another_namespace")


def test_converge_scope_stated_by_a_directive_which_must_not_be_rewritten(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: scope stated by a directive,
    which must not be rewritten.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_13})
    assert converge_report(ds, workdir) == golden("scope_stated_by_a_directive_which_must_not_be_rewritten")


def test_converge_fields_a_type_s_directive_widens_for_nothing_under_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: fields a type's directive
    widens for nothing, under strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_14})
    assert converge_report(ds, workdir) == golden("fields_a_type_s_directive_widens_for_nothing_under_strict")


def test_converge_declarations_a_file_s_directive_widens_for_nothing_under_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: declarations a file's
    directive widens for nothing, under strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_15})
    assert converge_report(ds, workdir) == golden("declarations_a_file_s_directive_widens_for_nothing_under_strict")


def test_converge_a_field_whose_narrowing_would_leave_the_directive_unused_under_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a field whose narrowing
    would leave the directive unused, under strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_16})
    assert converge_report(ds, workdir) == golden("a_field_whose_narrowing_would_leave_the_directive_unused_under_strict")


def test_converge_boundary_fix_on_a_type_whose_fields_nobody_else_reads_under_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: boundary fix on a type whose
    fields nobody else reads, under strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_17})
    assert converge_report(ds, workdir) == golden("boundary_fix_on_a_type_whose_fields_nobody_else_reads_under_strict")


def test_converge_redundant_directives_at_every_level_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: redundant directives at
    every level, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_18})
    assert converge_report(ds, workdir) == golden("redundant_directives_at_every_level_under_unused_strict")


def test_converge_a_spec_narrowing_its_block_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a spec narrowing its block,
    under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_19})
    assert converge_report(ds, workdir) == golden("a_spec_narrowing_its_block_under_unused_strict")


def test_converge_a_redundant_directive_on_a_crossing_declaration_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a redundant directive on a
    crossing declaration, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_20})
    assert converge_report(ds, workdir) == golden("a_redundant_directive_on_a_crossing_declaration_under_unused_strict")


def test_converge_a_field_s_redundant_directive_under_a_type_the_boundary_fix_widens_und(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a field's redundant
    directive under a type the boundary fix widens, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_21})
    assert converge_report(ds, workdir) == golden("a_field_s_redundant_directive_under_a_type_the_boundary_fix_widens_und")


def test_converge_a_block_every_spec_overrides_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a block every spec
    overrides, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_22})
    assert converge_report(ds, workdir) == golden("a_block_every_spec_overrides_under_unused_strict")


def test_converge_a_spec_restating_a_block_a_bare_ignore_answers_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a spec restating a block a
    bare ignore answers, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_23})
    assert converge_report(ds, workdir) == golden("a_spec_restating_a_block_a_bare_ignore_answers_under_unused_strict")


def test_converge_a_shared_directive_restating_the_shared_default_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a shared directive restating
    the shared default, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_24})
    assert converge_report(ds, workdir) == golden("a_shared_directive_restating_the_shared_default_under_unused_strict")


def test_converge_a_shared_directive_restating_the_file_s_under_unused_and_surplus_stric(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a shared directive restating
    the file's, under unused and surplus strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_25})
    assert converge_report(ds, workdir) == golden("a_shared_directive_restating_the_file_s_under_unused_and_surplus_stric")


def test_converge_a_redundant_directive_on_a_declaration_only_a_test_uses_from_elsewhere(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a redundant directive on a
    declaration only a test uses from elsewhere, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_26})
    assert converge_report(ds, workdir) == golden("a_redundant_directive_on_a_declaration_only_a_test_uses_from_elsewhere")


def test_converge_a_spec_restating_a_block_that_keeps_its_report_under_unused_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a spec restating a block
    that keeps its report, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_27})
    assert converge_report(ds, workdir) == golden("a_spec_restating_a_block_that_keeps_its_report_under_unused_strict")


def test_converge_a_spec_restating_a_block_that_is_reported_but_not_redundant_under_unus(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a spec restating a block
    that is reported but not redundant, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_28})
    assert converge_report(ds, workdir) == golden("a_spec_restating_a_block_that_is_reported_but_not_redundant_under_unus")


def test_converge_a_file_level_directive_one_declaration_overrides_and_one_restates_unde(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a file-level directive one
    declaration overrides and one restates, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_29})
    assert converge_report(ds, workdir) == golden("a_file_level_directive_one_declaration_overrides_and_one_restates_unde")


def test_converge_a_spec_under_a_block_that_decides_nothing_under_surplus_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a spec under a block that
    decides nothing, under surplus strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_30})
    assert converge_report(ds, workdir) == golden("a_spec_under_a_block_that_decides_nothing_under_surplus_strict")


def test_converge_a_field_under_a_type_that_decides_nothing_under_surplus_strict(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a field under a type that
    decides nothing, under surplus strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_31})
    assert converge_report(ds, workdir) == golden("a_field_under_a_type_that_decides_nothing_under_surplus_strict")


def test_converge_a_field_under_an_unnamed_type_that_decides_nothing_under_surplus_and_u(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: a field under an unnamed
    type that decides nothing, under surplus and unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_32})
    assert converge_report(ds, workdir) == golden("a_field_under_an_unnamed_type_that_decides_nothing_under_surplus_and_u")


def test_converge_an_unnamed_type_one_field_takes_one_restates_and_one_overrides_under_u(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: an unnamed type one field
    takes, one restates and one overrides, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_33})
    assert converge_report(ds, workdir) == golden("an_unnamed_type_one_field_takes_one_restates_and_one_overrides_under_u")


def test_converge_an_unnamed_type_whose_report_is_kept_beside_a_field_that_restates_it_u(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: an unnamed type whose report
    is kept beside a field that restates it, under unused strict.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_34})
    assert converge_report(ds, workdir) == golden("an_unnamed_type_whose_report_is_kept_beside_a_field_that_restates_it_u")


def test_converge_rename_captured_by_a_parameter_or_a_local_at_a_reference(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: rename captured by a
    parameter or a local at a reference.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_35})
    assert converge_report(ds, workdir) == golden("rename_captured_by_a_parameter_or_a_local_at_a_reference")


def test_converge_rename_colliding_with_an_import_in_another_file(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: rename colliding with an
    import in another file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_36})
    assert converge_report(ds, workdir) == golden("rename_colliding_with_an_import_in_another_file")


def test_converge_two_qualify_renames_converging_through_a_non_injective_prefix(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: two qualify renames
    converging through a non-injective prefix.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_37})
    assert converge_report(ds, workdir) == golden("two_qualify_renames_converging_through_a_non_injective_prefix")


def test_converge_reference_in_a_generated_file(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: reference in a generated
    file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_38})
    assert converge_report(ds, workdir) == golden("reference_in_a_generated_file")


def test_converge_reference_in_an_omitted_file(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: reference in an omitted
    file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_39})
    assert converge_report(ds, workdir) == golden("reference_in_an_omitted_file")


def test_converge_declaration_named_by_a_go_linkname_directive(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: declaration named by a
    go:linkname directive.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_40})
    assert converge_report(ds, workdir) == golden("declaration_named_by_a_go_linkname_directive")


def test_converge_rename_target_declared_only_in_the_test_variant(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: rename target declared only
    in the test variant.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_41})
    assert converge_report(ds, workdir) == golden("rename_target_declared_only_in_the_test_variant")


def test_converge_rename_referenced_from_a_test_file(ds, workdir):
    """CATCHES: a -fix that edits differently, applies a fix that should be withheld, withholds one that is
    sound, or leaves a different set of diagnostics after one pass, for the case: rename referenced from a
    test file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **CASE_42})
    assert converge_report(ds, workdir) == golden("rename_referenced_from_a_test_file")
