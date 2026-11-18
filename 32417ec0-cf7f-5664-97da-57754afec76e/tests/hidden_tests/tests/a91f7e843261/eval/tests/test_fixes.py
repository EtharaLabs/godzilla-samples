"""Suggested fixes applied by -fix, and printed by -fix -diff, on whole packages.

Each scenario lays a package out at a module root and records, in order: the diagnostics, the patch -fix -diff
prints (which must leave the files alone), the -fix run itself, every file afterwards, and the diagnostics
left after one pass.
"""

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


def fix_report(ds, workdir):
    before = ds(["./..."])
    diff = ds(["-fix", "-diff", "./..."])
    untouched = snapshot_tree(workdir)
    fix = ds(["-fix", "./..."])
    changed = snapshot_tree(workdir)
    after = ds(["./..."])
    return "\n".join([
        "## diagnostics", before.transcript,
        "## -fix -diff", diff.transcript,
        "## tree after -fix -diff", untouched,
        "## -fix", fix.transcript,
        "## tree after -fix", changed,
        "## diagnostics after -fix", after.transcript,
    ])


SRC_FIXES = {
    '.declscope.yaml': """rules:
  surplus: loose
""",
    'order.go': """package fixes

func orderRun() int { return userHelper() + userSeed }

var _ = orderRun

var _ userBox
""",
    'user.go': """package fixes

func userHelper() int { return 1 } // want `func userHelper is private to namespace "user", but is used from namespace "order"`

var (
	userSeed = 2 // want `var userSeed is private to namespace "user", but is used from namespace "order"`
)

// A type block is anchored a spec at a time, the way a var block is: the
// directive lands on the type that crosses, and the one beside it keeps the
// scope it had.
type (
	userBox  struct{ n int } // want `type userBox is private to namespace "user", but is used from namespace "order"`
	userCase struct{ n int }
)

var _ userCase
""",
}

SRC_FIXINLINE = {
    'order.go': """package fixinline

func orderRun(u *User) string { return u.name }

var _ = orderRun
""",
    'user.go': """package fixinline

// A field of a single-line struct has no line of its own, so the directive
// has to break it onto one.
type User struct{ name string } // want `field User.name is private to namespace "user", but is used from namespace "order"`
""",
}

SRC_FIXQUALIFY = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force. The surplus rule is turned off so
# that it does not land on the same directives and obscure the fix.
rules:
  naming:
    qualify: ondemand
  surplus: off
""",
    'order.go': """package fixqualify

//declscope:shared
func orderRun() int { return 4 }
""",
    'user.go': """package fixqualify

func helper() int { return 1 } // want `func helper does not carry namespace "user" anywhere in its name; rename it to userHelper, or to another name that carries "user"`

// The rename target is taken, so no fix is offered for this one.
func taken() int { return 2 } // want `func taken does not carry namespace "user" anywhere in its name; rename it to userTaken, or to another name that carries "user"`

func userTaken() int { return 3 }
""",
}

SRC_FIXEMBEDDED = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force. The surplus rule is turned off so
# that it does not land on the same directives and obscure the fix.
rules:
  naming:
    qualify: ondemand
  surplus: off
""",
    'order.go': """package fixembedded

//declscope:shared
func orderRun() int { return 4 }
""",
    'user.go': """package fixembedded

type count struct{ n int } // want `type count does not carry namespace "user" anywhere in its name; rename it to userCount, or to another name that carries "user"`

type total struct{ sum int } // want `type total does not carry namespace "user" anywhere in its name; rename it to userTotal, or to another name that carries "user"`

type userBase struct{ v int }

// view is an alias. A field embedding it is spelled with the alias's name, not
// the type it denotes, so the rename rewrites the selection through it too.
type view = userBase // want `type view does not carry namespace "user" anywhere in its name; rename it to userView, or to another name that carries "user"`

// User embeds all three. The embedding ident and every selection through it are
// spelled with the type's name, so the rename has to rewrite all of them.
type User struct {
	count
	*total
	view
}

func (u *User) Sum() int { return u.count.n + u.total.sum + u.view.v }
""",
}

SRC_FIXEMBEDDEDGENERIC = {
    '.declscope.yaml': """# The naming rule is off by default. Always puts it in force with the single
# namespace this package has, so the rename is offered.
rules:
  naming:
    qualify: always
""",
    'user.go': """package fixembeddedgeneric

import "strings"

type box[T any] struct{ v T } // want `type box does not carry namespace "user" anywhere in its name; rename it to userBox, or to another name that carries "user"`

// UserList embeds an instantiation that mentions its type parameter. Uses holds
// the instantiated field for u.box, which origin maps back to the declared one.
type UserList[T any] struct {
	box[T]
	*strings.Builder
}

func (u *UserList[T]) Get() T { return u.box.v }

// UserInts embeds a plain instantiation. Its field is not a target, but the
// selection through it is spelled with the type's name.
type UserInts struct{ box[int] }

func (u UserInts) Get() int {
	box := u.box.v // a local that shares the name is not rewritten
	return box
}

func UserLen(u *UserList[int]) int { return u.Builder.Len() }
""",
}

SRC_FIXCAPTURE = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'order.go': """package fixcapture

import userTotal "strings"

func OrderUpper(s string) string { return userTotal.ToUpper(s) }
""",
    'user.go': """package fixcapture

// The new name is free in package scope but bound at a reference by a
// parameter. Renaming would silently retarget that reference, so no fix.
var count = 10 // want `var count does not carry namespace "user" anywhere in its name; rename it to userCount, or to another name that carries "user"`

func Add(userCount int) int { return userCount + count }

// Bound at a reference by a local declared before it.
var limit = 3 // want `var limit does not carry namespace "user" anywhere in its name; rename it to userLimit, or to another name that carries "user"`

func Limited() int {
	userLimit := 1
	return userLimit + limit
}

// Bound in file scope by an import in order.go. Go rejects a package-level
// name that any file of the package imports, whether or not that file
// references the declaration.
var total = 7 // want `var total does not carry namespace "user" anywhere in its name; rename it to userTotal, or to another name that carries "user"`

var _ = total

// A local declared after the reference does not bind it, so this one is
// renamed: the reference keeps resolving to the package-level declaration.
var size = 1 // want `var size does not carry namespace "user" anywhere in its name; rename it to userSize, or to another name that carries "user"`

func Sized() int {
	s := size
	userSize := 2
	return s + userSize
}
""",
}

SRC_FIXFOREIGNMETHOD = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'order.go': """package fixforeignmethod

// orderT holds a field named like one rename below would name a method.
//
//declscope:shared
type orderT struct {
	//declscope:private
	userSize int
}

// orderOuter promotes every method of orderT, and declares a field of its own.
//
//declscope:shared
type orderOuter struct {
	orderT
	//declscope:private
	userDepth int
}

// An unnamed struct promotes the methods too.
var orderAnon struct {
	orderT
	userWidth int
}

type orderHelper interface{ help() int }

type orderChecker interface{ userCheck() bool }

// orderT satisfies orderHelper statically.
var _ orderHelper = orderT{}

// orderAsserted asks only through type assertions, one to a named interface
// and one to an unnamed one. Renaming a method would still compile, but flip
// what an assertion answers.
func orderAsserted() (bool, bool) {
	_, checked := any(orderT{}).(orderChecker)
	_, asserted := any(orderT{}).(interface{ assert() int })
	return checked, asserted
}

var _, _ = orderOuter{}, orderAnon
""",
    'user.go': """package fixforeignmethod

// help satisfies orderHelper. Renamed, orderT would no longer implement it,
// and the assignment in order.go would not compile.
func (o orderT) help() int { return 1 } // want `method help does not carry namespace "user" anywhere in its name; rename it to userHelp, or to another name that carries "user"`

// assert is asked for only by a type assertion. Renamed, the program would
// still compile, but the assertion would fail where it now succeeds.
func (o orderT) assert() int { return 2 } // want `method assert does not carry namespace "user" anywhere in its name; rename it to userAssert, or to another name that carries "user"`

// check would become userCheck, which orderChecker asks for. Renamed, orderT
// would start satisfying it, and the assertion would succeed where it now fails.
func (o orderT) check() bool { return true } // want `method check does not carry namespace "user" anywhere in its name; rename it to userCheck, or to another name that carries "user"`

// size would become userSize, the name of a field orderT already has.
func (o orderT) size() int { return 3 } // want `method size does not carry namespace "user" anywhere in its name; rename it to userSize, or to another name that carries "user"`

// depth would become userDepth, a field of orderOuter, which promotes depth.
func (o orderT) depth() int { return 4 } // want `method depth does not carry namespace "user" anywhere in its name; rename it to userDepth, or to another name that carries "user"`

// width would become userWidth, a field of the unnamed struct orderAnon has.
func (o *orderT) width() int { return 5 } // want `method width does not carry namespace "user" anywhere in its name; rename it to userWidth, or to another name that carries "user"`

// spare is free on orderT, on every type promoting it, and in every interface,
// so it is renamed.
func (o orderT) spare() int { return 6 } // want `method spare does not carry namespace "user" anywhere in its name; rename it to userSpare, or to another name that carries "user"`

func userCall(o orderOuter) int { return o.help() + o.spare() }
""",
}

SRC_FIXEMBEDDER = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixembedder

import "fmt"

// item is embedded in userHolder, which already has a field userItem.
// Renamed, the embedded field would be redeclared.
type item struct{ n int } // want `type item does not carry namespace "user" anywhere in its name; rename it to userItem, or to another name that carries "user"`

type userHolder struct {
	item
	userItem int
}

// part is embedded beside userOther, which has a field userPart. Renamed, the
// embedded field would be shallower than userOther.userPart, so h.userPart
// would select it instead: the program would still compile, and read part.
type part struct{ n int } // want `type part does not carry namespace "user" anywhere in its name; rename it to userPart, or to another name that carries "user"`

type userOther struct{ userPart int }

type userShallow struct {
	part
	userOther
}

func userRead(h userShallow) int { return h.userPart + h.part.n }

// deep is embedded two levels down, beside a field the rename would collide
// with at the same depth, which would make h.userDeep ambiguous.
type deep struct{ n int } // want `type deep does not carry namespace "user" anywhere in its name; rename it to userDeep, or to another name that carries "user"`

type userMiddle struct{ deep }

type userSide struct{ userDeep int }

type userTop struct {
	userMiddle
	userSide
}

func userReadTop(h userTop) int { return h.userDeep + h.deep.n }

// spare is embedded where nothing else is called userSpare, so it is renamed.
type spare struct{ n int } // want `type spare does not carry namespace "user" anywhere in its name; rename it to userSpare, or to another name that carries "user"`

type userFree struct{ spare }

func userReadFree(h userFree) int { return h.spare.n }

// userNode embeds itself through a pointer, and an interface, which holds no
// field. The search through it ends either way.
type userNode struct {
	*userNode
	fmt.Stringer
}
""",
}

SRC_FIXSIBLINGS = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
""",
    'a.go': """package fixsiblings

// Prefixing is not injective across namespaces: bX in namespace "a" and x in
// namespace "aB" both prefix to aBX. The first declaration in the pass claims
// the name; the second is reported without a fix.
func bX() int { return 1 } // want `func bX does not carry namespace "a" anywhere in its name; rename it to aBX, or to another name that carries "a"`

var _ = bX
""",
    'a_b.go': """package fixsiblings

func x() int { return 2 } // want `func x does not carry namespace "aB" anywhere in its name; rename it to aBX, or to another name that carries "aB"`

var _ = x
""",
}

SRC_FIXOUTSIDE = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
filter:
  omit:
    - "**/ext.go"
""",
    'ext.go': """package fixoutside

func Ext() int { return aux() }
""",
    'gen.go': """// Code generated by hand, for this test. DO NOT EDIT.

package fixoutside

func Gen() int { return helper() }

func GenBox(h UserHolder) int { return h.box.n }
""",
    'user.go': """package fixoutside

// helper is also named from gen.go, which is generated and so not a file the
// pass rewrites; the rename would leave that use dangling.
//
//declscope:shared
func helper() int { return 1 } // want `func helper does not carry namespace "user" anywhere in its name; rename it to userHelper, or to another name that carries "user"`

// aux is named from ext.go, which the configuration excludes.
//
//declscope:shared
func aux() int { return 2 } // want `func aux does not carry namespace "user" anywhere in its name; rename it to userAux, or to another name that carries "user"`

// Every use is in a collected file, so this one is renamed.
func local() int { return 3 } // want `func local does not carry namespace "user" anywhere in its name; rename it to userLocal, or to another name that carries "user"`

var _ = local

// box is named from gen.go only through the field embedding it, which is
// spelled with the type's name, so the rename would leave that use dangling.
type box struct{ n int } // want `type box does not carry namespace "user" anywhere in its name; rename it to userBox, or to another name that carries "user"`

// UserHolder embeds box.
type UserHolder struct{ box }
""",
}

SRC_FIXLINKNAME = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixlinkname

import _ "unsafe"

// The directive names helper as text, which a rename cannot follow.
//
//go:linkname helper
func helper() int { return 1 } // want `func helper does not carry namespace "user" anywhere in its name; rename it to userHelper, or to another name that carries "user"`

// A cgo //export names tick as text the same way.
//
//export tick
func tick() int { return 3 } // want `func tick does not carry namespace "user" anywhere in its name; rename it to userTick, or to another name that carries "user"`

func plain() int { return 2 } // want `func plain does not carry namespace "user" anywhere in its name; rename it to userPlain, or to another name that carries "user"`

func Exported() int { return helper() + tick() + plain() }
""",
}

SRC_FIXTESTVARIANT = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'foo.go': """package fixtestvariant

// fooCount is free in this variant's package scope but declared in
// foo_test.go, which only the test variant sees. Neither variant renames: the
// test variant finds the name taken, and this one cannot see enough of the
// package to prove anything, so it defers.
var count = 10 // want `var count does not carry namespace "foo" anywhere in its name; rename it to fooCount, or to another name that carries "foo"`

// Free in both variants. Only the test variant, which sees every file, offers
// the rename, and its edits cover this file too.
var size = 1 // want `var size does not carry namespace "foo" anywhere in its name; rename it to fooSize, or to another name that carries "foo"`

func Exported() int { return count + size }
""",
    'foo_test.go': """package fixtestvariant

var fooCount = 1

var _ = fooCount

var _ = size
""",
}

SRC_FIXEXCLUDED = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'excluded.go': """//go:build declscope_never

package fixexcluded

// This file belongs to the package but no build configuration the analysis
// runs under includes it, so it is absent from pass.Files and the fix never
// rewrites it. It names load, and it declares userSpare.

func userSpare() int { return 0 }

func excludedUse() int { return load() + userSpare() }
""",
    'user.go': """package fixexcluded

// load is named from excluded.go, which this build configuration leaves out.
// Renaming it here would leave that file calling a name that no longer
// exists, so the rename is withheld and only the violation is reported.
func load() int { return 1 } // want `func load does not carry namespace "user" anywhere in its name; rename it to userLoad, or to another name that carries "user"`

// userSpare is already declared in excluded.go, so claiming that name would
// declare it twice in the configuration that includes the file.
func spare() int { return 2 } // want `func spare does not carry namespace "user" anywhere in its name; rename it to userSpare, or to another name that carries "user"`

// Named nowhere outside this file, so nothing the excluded file writes is
// disturbed and the rename is offered.
func free() int { return 3 } // want `func free does not carry namespace "user" anywhere in its name; rename it to userFree, or to another name that carries "user"`

func Exported() int { return load() + spare() + free() }
""",
}

SRC_FIXTESTEXCLUDED = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixtestexcluded

// The directory lists user_test.go before zz_excluded.go. The non-test
// variant stops reading at the test file, which already withholds every
// rename there. The test variant sees the test file and still reads the
// excluded one, so only a rename that file does not disturb is offered.

// load is named from zz_excluded.go, so neither variant renames it.
func load() int { return 1 } // want `func load does not carry namespace "user" anywhere in its name; rename it to userLoad, or to another name that carries "user"`

// Named only in files the fix rewrites, so the test variant renames it here
// and in user_test.go.
func free() int { return 3 } // want `func free does not carry namespace "user" anywhere in its name; rename it to userFree, or to another name that carries "user"`

func Exported() int { return load() + free() }
""",
    'user_test.go': """package fixtestexcluded

var _ = free
""",
    'zz_excluded.go': """//go:build declscope_never

package fixtestexcluded

// This file belongs to the package, but no build configuration the analysis
// runs under includes it. It names load.

func excludedUse() int { return load() }
""",
}

SRC_FIXTESTTAGGED = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixtesttagged

// user_test.go is in the test variant. zz_tagged_test.go is an in-package
// test file the build leaves out, so the test variant lacks it too. The
// non-test variant stops at user_test.go and offers no rename. The test
// variant reads the tagged file for its names, as for any excluded file, and
// withholds only the rename that file would notice.

// load is named from zz_tagged_test.go, so neither variant renames it.
func load() int { return 1 } // want `func load does not carry namespace "user" anywhere in its name; rename it to userLoad, or to another name that carries "user"`

// Named only in files the fix rewrites, so the test variant renames it here
// and in user_test.go.
func free() int { return 3 } // want `func free does not carry namespace "user" anywhere in its name; rename it to userFree, or to another name that carries "user"`

func Exported() int { return load() + free() }
""",
    'user_test.go': """package fixtesttagged

var _ = free
""",
    'zz_tagged_test.go': """//go:build declscope_never

package fixtesttagged

// This test file belongs to the package, but no build configuration the
// analysis runs under includes it. It names load.

var _ = load
""",
}

SRC_FIXTESTTAGGEDONLY = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixtesttaggedonly

// The only test file is user_tagged_test.go, which the build leaves out, so
// the package has no test variant. The non-test variant learns from the
// ignored files that no variant sees it, and reads it for its names.

// load is named from user_tagged_test.go, so it is not renamed.
func load() int { return 1 } // want `func load does not carry namespace "user" anywhere in its name; rename it to userLoad, or to another name that carries "user"`

// Named only in this file, so it is renamed.
func free() int { return 3 } // want `func free does not carry namespace "user" anywhere in its name; rename it to userFree, or to another name that carries "user"`

func Exported() int { return load() + free() }
""",
    'user_tagged_test.go': """//go:build declscope_never

package fixtesttaggedonly

// No build configuration the analysis runs under includes this file. It
// names load.

var _ = load
""",
}

SRC_FIXMEMBERS = {
    'order.go': """package fixmembers

func orderRun() string {
	e := entry{key: "x"}
	return e.key
}

func orderRead() bool { return UserMake().flag }

var _, _ = orderRun, orderRead
""",
    'user.go': """package fixmembers

// Both the type and its field cross, and a directive on the type reaches the
// field. Only the wider one is written: a directive on the field as well would
// bind nothing, and the directive rule would report what -fix had just
// written.
type entry struct { // want `type entry is private to namespace "user", but is used from namespace "order"`
	key string // want `field entry.key is private to namespace "user", but is used from namespace "order"`
}

// Here the type itself does not cross — another namespace reaches a value of
// it without ever naming it — so nothing widens the field but its own
// directive, and the fix is offered.
type kept struct {
	flag bool // want `field kept.flag is private to namespace "user", but is used from namespace "order"`
}

func UserMake() kept { return kept{flag: true} }
""",
}

SRC_FIXSURPLUSSTRICT = {
    '.declscope.yaml': """# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
  unused: loose
""",
    'box.go': """package fixsurplusstrict

// boxItem takes private from the default and crosses, so the boundary fix
// widens it. The same fix narrows count, which nothing outside reads, and
// leaves shared, which order.go reads, and memo, whose author asked this rule
// to stay out.
type boxItem struct { // want `type boxItem is private to namespace "box", but is used from namespace "order"`
	shared int // want `field boxItem.shared is private to namespace "box", but is used from namespace "order"`

	// count is read here only.
	count int

	//declscope:ignore surplus // want `unused //declscope:ignore surplus on boxItem.memo`
	memo int
}

func boxLocal(b boxItem) int { return b.count + b.memo }

var _ = boxLocal
""",
    'crate.go': """package fixsurplusstrict

// crateItem crosses, so the boundary fix widens it. Its own ignore reaches
// weight through the type, so the fix leaves weight alone.
//
//declscope:ignore surplus // want `unused //declscope:ignore surplus on crateItem`
type crateItem struct { // want `type crateItem is private to namespace "crate", but is used from namespace "order"`
	weight int
}

func crateLocal(c crateItem) int { return c.weight }

var _ = crateLocal
""",
    'dto.go': """package fixsurplusstrict

// The directive decides only for the unexported fields: UserDTO and Name are
// shared by exportedness. Narrowing both fields would leave it binding
// nothing, so the fields are reported without a fix, and this file takes no
// edit. The directive is the thing to delete, which no fix does.
//
//declscope:shared
type UserDTO struct {
	Name string
	seq  int // want `field UserDTO.seq takes shared scope`
	rev  int // want `field UserDTO.rev takes shared scope`
}

func dtoLocal(d UserDTO) int { return d.seq + d.rev }

var _ = dtoLocal
""",
    'order.go': """package fixsurplusstrict

func orderRun(a userAccount, t userTiny, b boxItem, c crateItem) int {
	return a.id + len([]any{t, c}) + b.shared + restatedShared + restatedHelper() + restatedEntry{}.key
}

var _ = orderRun
""",
    'restated.go': """//declscope:shared

package fixsurplusstrict

// restatedHelper takes the file's package, and order.go calls it.
func restatedHelper() int { return 3 }

// restatedSpare takes it too, and nothing else calls it. Its narrowing gives
// this file an edit whatever the rest gets, so the golden is compared.
func restatedSpare() int { return 4 } // want `func restatedSpare takes shared scope`

var _ = restatedSpare

// The block restates the file's package, so it decides nothing, and the
// unused rule reports it naming both specs. Narrowing restatedLocal would
// reword that report, so the fix is withheld. The block is the thing to
// delete, which no fix does.
//
//declscope:shared // want `unused //declscope:shared on restatedShared, restatedLocal: nothing it reaches takes a scope`
var (
	restatedShared = 1
	restatedLocal  = 2 // want `var restatedLocal takes shared scope`
)

var _ = restatedLocal

// The type restates the file's package too, but its report names the type
// alone, and a field it reaches is never named. Narrowing spare leaves that
// report reading the same, so the fix is offered.
//
//declscope:shared // want `unused //declscope:shared on restatedEntry: nothing it reaches takes a scope`
type restatedEntry struct {
	key   int
	spare int // want `field restatedEntry.spare takes shared scope`
}

var _ = restatedEntry{}.spare

// A type that declares no name is named on no report, which reads whether
// anything took its scope. Wide takes it and stays, so narrowing spare leaves
// the report reading the same, and the fix is offered.
//
//declscope:shared // want `unused //declscope:shared: nothing it reaches takes a scope`
type _ struct {
	Wide  int
	spare int // want `field _.spare takes shared scope`
}
""",
    'user.go': """package fixsurplusstrict

//declscope:shared
type userAccount struct {
	id int

	// balance is read only here, so it is narrowed, and the directive lands
	// under its doc comment after a bare comment line.
	balance int // want `field userAccount.balance takes shared scope from //declscope:shared on userAccount, but no use from another namespace is visible to declscope`

	// A doc comment that already ends in a bare line takes no second one.
	//
	limit int // want `field userAccount.limit takes shared scope`

	plain int // want `field userAccount.plain takes shared scope`

	// Two names in one entry take one directive, written once.
	left, right int // want `field userAccount.left takes shared scope` `field userAccount.right takes shared scope`
}

// A field that shares its line with the type is broken onto its own.
//
//declscope:shared
type userTiny struct{ n int } // want `field userTiny.n takes shared scope`

func userLocal(a userAccount, t userTiny) int {
	return a.balance + a.limit + a.plain + a.left + a.right + t.n
}

var _ = userLocal
""",
}

SRC_FIXSURPLUSSTRICTUNUSEDOFF = {
    '.declscope.yaml': """# The unused rule is off, so a directive that decides nothing has no report
# for narrowing to reword, and strict's fix is offered under it.
rules:
  surplus: strict
  unused: off
""",
    'order.go': """package fixsurplusstrictunusedoff

func orderRun() int { return userShared + userHelper() }

var _ = orderRun
""",
    'user.go': """//declscope:shared

package fixsurplusstrictunusedoff

// userHelper takes the file's package, and order.go calls it.
func userHelper() int { return 3 }

// userSpare takes it too, and nothing else calls it. Its narrowing gives
// this file an edit whatever the block's specs get, so the golden is compared.
func userSpare() int { return 4 } // want `func userSpare takes shared scope`

var _ = userSpare

// The block restates the file's package and decides nothing. With the unused
// rule off nothing reports it, so userLocal is narrowed.
//
//declscope:shared
var (
	userShared = 1
	userLocal  = 2 // want `var userLocal takes shared scope`
)

var _ = userLocal
""",
}

SRC_FIXUNUSEDSTRICT = {
    '.declscope.yaml': """rules:
  unused: strict
""",
    'a.go': """//declscope:private // want `unused file-level //declscope:private: every declaration it reaches already has private scope`

package fixunusedstrict

// aDoc has a doc comment, separated from the directive by a bare line that
// the fix takes along.
//
//declscope:private // want `unused //declscope:private on aDoc: it already has private scope`
func aDoc() int { return 1 }

//declscope:private // want `unused //declscope:private on aBare: it already has private scope`
func aBare() int { return 2 }

// aIgnored keeps its ignore: only the scope directive goes, and the bare line
// still separates the doc comment from what is left.
//
//declscope:private // want `unused //declscope:private on aIgnored: it already has private scope`
//declscope:ignore qualify // want `unused //declscope:ignore qualify on aIgnored`
func aIgnored() int { return 3 }

type aShape struct {
	side int //declscope:private // want `unused //declscope:private on aShape.side: it already has private scope`

	// edge is documented.
	//
	//declscope:private // want `unused //declscope:private on aShape.edge: it already has private scope`
	edge int
}

//declscope:private // want `unused //declscope:private on aSeed, aLimit: each already has private scope`
var (
	aSeed  = 1
	aLimit = 2
)

var _ = aDoc() + aBare() + aIgnored() + aShape{}.side + aShape{}.edge + aSeed + aLimit
""",
    'b.go': """package fixunusedstrict

// bShared is used from c.go, so deleting its directive would move the level
// the boundary report names. It is reported without a fix, and this file takes
// no edit.
//
//declscope:private // want `unused //declscope:private on bShared: it already has private scope`
func bShared() int { return 1 } // want `func bShared is declared private by //declscope:private, but is used from namespace "c"`
""",
    'c.go': """package fixunusedstrict

var _ = bShared()
""",
}

SRC_FIXUNUSEDSTRICTWITHHELD = {
    '.declscope.yaml': """rules:
  unused: strict
  # surplus would withhold the shared directives' fixes on its own account;
  # this package is about the unused rule's own reasons.
  surplus: off
""",
    'a.go': """package fixunusedstrictwithheld

// aBare restates the default, and nothing withholds its fix.
//
//declscope:private // want `unused //declscope:private on aBare: it already has private scope`
func aBare() int { return 1 }

// An ignore answers the block's report. The block is redundant, so it stays
// redundant and answered once aSpec takes it, and aSpec's directive goes.
//
//declscope:private
//declscope:ignore unused
var (
	//declscope:private // want `unused //declscope:private on aSpec: it already has private scope`
	aSpec = 2
)

var _ = aBare() + aSpec
""",
    'b.go': """package fixunusedstrictwithheld

// The boundary fix widens bEntry, so the field's directive stays: without it
// the field would take the type's new directive.
type bEntry struct { // want `type bEntry is private to namespace "b", but is used from namespace "c"`
	//declscope:private // want `unused //declscope:private on bEntry.key: it already has private scope`
	key string
}

var _ = bEntry{}.key
""",
    'c.go': """package fixunusedstrictwithheld

var _ bEntry
""",
    'd.go': """package fixunusedstrictwithheld

// The block keeps its report, since e.go uses dA. Deleting dB's directive
// would hand dB to the block, and the block's report would name it too.
//
//declscope:private // want `unused //declscope:private on dA: it already has private scope`
var (
	dA = 1 // want `var dA is declared private by //declscope:private, but is used from namespace "e"`
	//declscope:private // want `unused //declscope:private on dB: it already has private scope`
	dB = 2
)

var _ = dB
""",
    'e.go': """package fixunusedstrictwithheld

var _ = dA
""",
    'f.go': """package fixunusedstrictwithheld

// The block binds nothing, but fNarrowed needs it, so loose alone reports it.
// Deleting FExported's directive would hand FExported to the block, and the
// block's report would name it.
//
//declscope:shared // want `unused //declscope:shared: every declaration it reaches states its own scope`
var (
	//declscope:shared // want `unused //declscope:shared on FExported: it already has shared scope`
	FExported = 1
	//declscope:private
	fNarrowed = 2
)

var _ = fNarrowed
""",
    'g.go': """package fixunusedstrictwithheld

// gShared is named by g_other.go, which the build excludes and the pass reads
// for its names alone: the crossing may be there.
//
//declscope:private // want `unused //declscope:private on gShared: it already has private scope`
func gShared() int { return 1 }
""",
    'g_other.go': """//go:build ignore

package fixunusedstrictwithheld

var _ = gShared()
""",
}

SRC_FIXUNUSEDSTRICTSURPLUS = {
    '.declscope.yaml': """defaults:
  unexported: shared
rules:
  unused: strict
""",
    'a.go': """package fixunusedstrictsurplus

// aHelper's directive restates the default. surplus reports it too, and the
// deletion settles both.
//
//declscope:shared // want `unused //declscope:shared on aHelper: it already has shared scope` `//declscope:shared on aHelper: no use from another namespace is visible to declscope`
func aHelper() int { return 1 }

var _ = aHelper()
""",
    'b.go': """package fixunusedstrictsurplus

// An ignore answers surplus for bQuiet, and would answer nothing once the
// directive is gone.
//
//declscope:shared // want `unused //declscope:shared on bQuiet: it already has shared scope`
//declscope:ignore surplus
func bQuiet() int { return 1 }

var _ = bQuiet()
""",
    'c.go': """//declscope:private

package fixunusedstrictsurplus

// cLocal's directive restates its block's, which cTaker keeps in use.
// Deleting it would make cLocal one of the block's dependents, which surplus
// judges.
//
//declscope:shared // want `//declscope:shared on cTaker: no use from another namespace is visible to declscope`
var (
	cTaker = 1
	//declscope:shared // want `unused //declscope:shared on cLocal: it already has shared scope` `//declscope:shared on cLocal: no use from another namespace is visible to declscope`
	cLocal = 2
)

func cOther() int { return 3 }

var _ = cTaker + cLocal + cOther()
""",
}

SRC_FIXUNSEENBODY = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'broken.go': """//go:build ignore

package fixunseenbody

func (
""",
    'user.go': """package fixunseenbody

// broken.go is excluded by the build and cannot be parsed, so the pass cannot
// tell whether it names helper or userHelper. The rename is withheld.
func helper() int { return 1 } // want `func helper does not carry namespace "user" anywhere in its name; rename it to userHelper, or to another name that carries "user"`

var _ = helper
""",
}

SRC_FIXSURPLUSNARROW = {
    '.declscope.yaml': """rules:
  surplus: strict
""",
    'order.go': """package fixsurplusnarrow

func OrderKey() string { return entry{}.key }
""",
    'user.go': """package fixsurplusnarrow

// entry crosses, and the boundary fix widens it. note is read here alone, so
// the same edit narrows it back, or surplus would report what -fix wrote.
// memo shares its line, so one directive narrows both, and extra takes its
// own.

type entry struct { // want `type entry is private to namespace "user", but is used from namespace "order"`
	key        string // want `field entry.key is private to namespace "user", but is used from namespace "order"`
	note, memo string
	extra      int
}

func userNote(e entry) string { return e.note + e.memo + string(rune(e.extra)) }

var _ = userNote
""",
}

SRC_FIXSURPLUSSTRICTUNUSEDSTRICT = {
    '.declscope.yaml': """# Both rules strict: an unused report under strict reads what the declarations
# already have, so narrowing one of them can reword it where loose's cannot.
rules:
  surplus: strict
  unused: strict
""",
    'order.go': """package fixsurplusstrictunusedstrict

func orderRun() int { return userHelper() + userEntry{}.key }

var _ = orderRun
""",
    'user.go': """//declscope:shared

package fixsurplusstrictunusedstrict

// userHelper takes the file's package, and order.go calls it.
func userHelper() int { return 3 }

// userSpare takes it too, and nothing else calls it. Its narrowing gives
// this file an edit whatever the rest gets, so the golden is compared.
func userSpare() int { return 4 } // want `func userSpare takes shared scope`

var _ = userSpare

// The type restates the file's package, and its report names the type alone.
// Narrowing spare leaves it reading the same, so the fix is offered. The
// directive's own deletion is withheld, since surplus reads it.
//
//declscope:shared // want `unused //declscope:shared on userEntry: it already has shared scope`
type userEntry struct {
	key   int
	spare int // want `field userEntry.spare takes shared scope`
}

var _ = userEntry{}.spare

// A type that declares no name has a report that says what everything it
// reaches has. Narrowing spare would make it say that one field states its
// own scope, so the fix is withheld.
//
//declscope:shared // want `unused //declscope:shared: every declaration it reaches already has shared scope`
type _ struct {
	Wide  int
	spare int // want `field _.spare takes shared scope`
}
""",
}

SRC_LINEFIX = {
    'order.go': """package linefix

func orderRead() bool { return UserMake().flag }

var _ = orderRead
""",
    'user.go': """package linefix

// A //line directive without a column leaves the adjusted column at 0. The
// field does not start its line, so the fix still breaks the line first.
//
//line user.tmpl:1
type kept struct{ flag bool } // want `field kept.flag is private to namespace "user", but is used from namespace "order"`

func UserMake() kept { return kept{flag: true} }
""",
}

SRC_FIXASM = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixasm

// user.s defines add, and the linker finds it by this name.
func add(a, b int64) int64 // want `func add does not carry namespace "user" anywhere in its name; rename it to userAdd, or to another name that carries "user"`

// Nothing names plain from assembly, but the package holds it, so plain is
// not renamed either.
func plain() int64 { return 2 } // want `func plain does not carry namespace "user" anywhere in its name; rename it to userPlain, or to another name that carries "user"`

func Exported() int64 { return add(1, 2) + plain() }
""",
    'user.s': """#include "textflag.h"

TEXT ·add(SB), NOSPLIT, $0-24
	RET
""",
    'user_test.go': """package fixasm_test

// user.s is built into package fixasm only, so it names nothing in this
// external test package, which keeps its rename and its surplus report.

//declscope:shared // want `//declscope:shared on userThing: no use from another namespace is visible to declscope`
var userThing = 1

func plain() int64 { return 2 } // want `func plain does not carry namespace "user" anywhere in its name; rename it to userPlain, or to another name that carries "user"`
""",
}

SRC_FIXASMIGNORED = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'user.go': """package fixasmignored

// user_s390x.s calls double, in a build this pass does not see.
func double(a int64) int64 { return 2 * a } // want `func double does not carry namespace "user" anywhere in its name; rename it to userDouble, or to another name that carries "user"`

func Exported() int64 { return double(1) }
""",
    'user_s390x.s': """#include "textflag.h"

TEXT ·quadruple(SB), NOSPLIT, $0-16
	CALL ·double(SB)
	RET
""",
}

SRC_FIXASMSKIPPED = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    '_old.s': """#include "textflag.h"

TEXT ·quadruple(SB), NOSPLIT, $0-16
	CALL ·plain(SB)
	RET
""",
    'user.go': """package fixasmskipped

// The go command skips _old.s, as it skips every name that starts with _ or
// ., so plain is still renamed.
func plain() int64 { return 2 } // want `func plain does not carry namespace "user" anywhere in its name; rename it to userPlain, or to another name that carries "user"`

func Exported() int64 { return plain() }
""",
}


def test_fixes(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    directive fix inserted above each crossing declaration, field and method, and that the files compile into
    the shape the fix promises.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXES})
    assert fix_report(ds, workdir) == golden("fixes")


def test_fix_inline_struct(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    directive fix for a field that shares its line with the struct type, which has to be broken onto a line of
    its own for the directive to bind to it.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXINLINE})
    assert fix_report(ds, workdir) == golden("fix_inline_struct")


def test_fix_qualify(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    rename offered by the naming rule. It never changes a declaration's reach, so it cannot conflict with the
    directive fix.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXQUALIFY})
    assert fix_report(ds, workdir) == golden("fix_qualify")


def test_fix_embedded(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    renaming a type also rewrites the idents that embed it, and the selections that reach the embedded field
    by the type's name.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXEMBEDDED})
    assert fix_report(ds, workdir) == golden("fix_embedded")


def test_fix_embedded_generic(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    same for an embedded generic type. The selection through an instantiated field, the embedding and the
    declaration are all rewritten. An imported embedded type and a local that shares the name are left alone.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXEMBEDDEDGENERIC})
    assert fix_report(ds, workdir) == golden("fix_embedded_generic")


def test_fix_capture(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a new name bound at a reference by a parameter or a local, or in file scope by an import anywhere in the
    package, withholds the rename. A local declared after the reference does not bind it, and withholds
    nothing.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXCAPTURE})
    assert fix_report(ds, workdir) == golden("fix_capture")


def test_fix_foreign_method(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a method renamed in another file's namespace keeps the type's method set as it was. A new name already
    selected on the type or on a type promoting the method, or an old or new name an interface of the package
    asks for, withholds the rename: the first would not compile, and the second can, while changing what an
    assertion answers.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXFOREIGNMETHOD})
    assert fix_report(ds, workdir) == golden("fix_foreign_method")


def test_fix_embedder(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a type is not renamed when the field embedding it would take a name already selected on the embedding
    struct. The struct could then not compile, or compile with a selector now reaching the embedded field
    instead of the one it reached before, or reaching neither.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXEMBEDDER})
    assert fix_report(ds, workdir) == golden("fix_embedder")


def test_fix_siblings(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    two fixes in one pass cannot rename two declarations to the same name: the first claims it, the second is
    reported without a fix.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXSIBLINGS})
    assert fix_report(ds, workdir) == golden("fix_siblings")


def test_fix_outside(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a declaration referenced from a generated or excluded file, which the pass does not rewrite, is not
    renamed.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXOUTSIDE})
    assert fix_report(ds, workdir) == golden("fix_outside")


def test_fix_linkname(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a declaration named by a //go:linkname directive, which a rename cannot follow, is not renamed.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXLINKNAME})
    assert fix_report(ds, workdir) == golden("fix_linkname")


def test_fix_test_variant(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    the non-test variant of a package with in-package tests offers no rename, since it cannot see what the
    test files declare, and that the test variant, which can, still does.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXTESTVARIANT})
    assert fix_report(ds, workdir) == golden("fix_test_variant")


def test_fix_excluded(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a declaration named from a file the build configuration excludes is not renamed, in either direction: the
    excluded file names load, and already declares the name spare would take. Neither is rewritten by the fix,
    and no variant of this package ever sees the file. A declaration it does not mention is still renamed.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXEXCLUDED})
    assert fix_report(ds, workdir) == golden("fix_excluded")


def test_fix_test_excluded(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    two together, with the test file first in the directory. The non-test variant stops at it and offers no
    rename. The test variant still reads the excluded file, and withholds only the rename that file would
    notice.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXTESTEXCLUDED})
    assert fix_report(ds, workdir) == golden("fix_test_excluded")


def test_fix_test_tagged(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    same with an in-package test file the build excludes. The test variant lacks it too, so the test variant
    reads it for its names rather than deferring to a variant that would also lack it.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXTESTTAGGED})
    assert fix_report(ds, workdir) == golden("fix_test_tagged")


def test_fix_test_tagged_only(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks a
    package whose only test file the build excludes, so there is no test variant. The non-test variant reads
    the file for its names and still offers the rename that file does not disturb.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXTESTTAGGEDONLY})
    assert fix_report(ds, workdir) == golden("fix_test_tagged_only")


def test_fix_members(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    two directive insertions in one pass cannot converge. A directive inserted on a type reaches the type's
    members, so a member whose type is widened in the same run is reported without a fix of its own; a member
    whose type is not gets one.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXMEMBERS})
    assert fix_report(ds, workdir) == golden("fix_members")


def test_fix_surplus_strict(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks
    strict's fix: //declscope:private above the declaration, after a bare comment line under a doc comment,
    once for an entry holding two names, and on a line of its own for a field that shared one. A directive
    that narrowing would leave binding nothing withholds the fix, so that file takes no edit. And a boundary
    fix on a type narrows, in the same edit, each member the widened type would otherwise leave wide.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXSURPLUSSTRICT})
    assert fix_report(ds, workdir) == golden("fix_surplus_strict")


def test_fix_surplus_strict_unused_off(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    strict's fix is offered under a directive that decides nothing when the unused rule is off. With the rule
    on, that directive's report names what narrowing would change, and fixsurplusstrict/restated.go pins that
    the fix is withheld there.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXSURPLUSSTRICTUNUSEDOFF})
    assert fix_report(ds, workdir) == golden("fix_surplus_strict_unused_off")


def test_fix_unused_strict(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    fix rules.unused: strict offers: it deletes the redundant directive, whether it stands on its own line or
    trails a field, with the bare // that separated it from a doc comment, and with the blank line after a
    file-level one. A directive on a declaration another namespace uses is reported without a fix, so that
    file takes no edit.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXUNUSEDSTRICT})
    assert fix_report(ds, workdir) == golden("fix_unused_strict")


def test_fix_unused_strict_withheld(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks each
    reason the directive rule's strict fix is withheld, with the report kept: a field whose type the boundary
    fix widens (b.go), a spec whose block keeps a report the deletion would change (d.go, and f.go where loose
    alone reports the block), and a declaration a file the build excludes names (g.go). Only a.go and the
    boundary fix in b.go take edits; an outer directive an ignore answers does not withhold.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXUNUSEDSTRICTWITHHELD})
    assert fix_report(ds, workdir) == golden("fix_unused_strict_withheld")


def test_fix_unused_strict_surplus(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks the
    reasons the directive rule's strict fix is withheld while surplus reads a //declscope:shared: an ignore
    answering surplus (b.go), and a directive restating an enclosing one (c.go). Only a.go, where the deletion
    settles surplus's report too, takes an edit.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXUNUSEDSTRICTSURPLUS})
    assert fix_report(ds, workdir) == golden("fix_unused_strict_surplus")


def test_fix_unparsable_excluded_file_fixunseenbody(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a file the build excludes and the pass cannot parse withholds every rename, whether its package clause or
    its body is what fails: the pass cannot tell what it names.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXUNSEENBODY})
    assert fix_report(ds, workdir) == golden("fix_unparsable_excluded_file_fixunseenbody")


def test_fix_surplus_narrows_with_type_fix(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    under surplus strict a boundary fix on a type narrows, in the same edit, the members no other namespace
    reads.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXSURPLUSNARROW})
    assert fix_report(ds, workdir) == golden("fix_surplus_narrows_with_type_fix")


def test_fix_surplus_strict_unused_strict(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks
    strict's fix under a directive that decides nothing while the unused rule is strict. The fix is offered
    where the directive's report reads the same after it, and withheld where narrowing would reword that
    report.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXSURPLUSSTRICTUNUSEDSTRICT})
    assert fix_report(ds, workdir) == golden("fix_surplus_strict_unused_strict")


def test_fix_line_directive(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    the fix reads the file on disk under a //line directive. The adjusted column is 0 there, which would make
    a field in the middle of a line look like it starts one.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_LINEFIX})
    assert fix_report(ds, workdir) == golden("fix_line_directive")


def test_fix_assembly_fixasm(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a package holding assembly offers no rename, since an .s file names Go symbols the rename cannot follow.
    That holds for assembly in this build and for assembly the build excludes. The external test package
    beside it keeps its rename (#323): the assembly is built into the package under test only. A file the go
    command skips, such as _old.s, blocks nothing (#324).
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXASM})
    assert fix_report(ds, workdir) == golden("fix_assembly_fixasm")


def test_fix_assembly_fixasmignored(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a package holding assembly offers no rename, since an .s file names Go symbols the rename cannot follow.
    That holds for assembly in this build and for assembly the build excludes. The external test package
    beside it keeps its rename (#323): the assembly is built into the package under test only. A file the go
    command skips, such as _old.s, blocks nothing (#324).
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXASMIGNORED})
    assert fix_report(ds, workdir) == golden("fix_assembly_fixasmignored")


def test_fix_assembly_fixasmskipped(ds, workdir):
    """CATCHES: a -fix that writes different edits (placement, spelling, which fixes are withheld), a -diff that
    prints a different patch, or diagnostics that differ before or after, on this scenario, which checks that
    a package holding assembly offers no rename, since an .s file names Go symbols the rename cannot follow.
    That holds for assembly in this build and for assembly the build excludes. The external test package
    beside it keeps its rename (#323): the assembly is built into the package under test only. A file the go
    command skips, such as _old.s, blocks nothing (#324).
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FIXASMSKIPPED})
    assert fix_report(ds, workdir) == golden("fix_assembly_fixasmskipped")
