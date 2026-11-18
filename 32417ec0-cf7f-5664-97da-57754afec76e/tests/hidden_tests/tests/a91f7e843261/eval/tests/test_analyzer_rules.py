"""The analyzer's rules on whole packages: boundary, naming, surplus, unused and directive reports.

Each scenario is one small package laid out at the root of a module, analyzed with `declscope ./...`. The
expected output is the full transcript: exit status, stdout and stderr, with the work directory written as
$WORK.
"""

from conftest import GO_MOD, read_golden, write_tree


def golden(name):
    return read_golden(__file__, name)


SRC_PKGLEVEL = {
    'order.go': """package pkglevel

func orderRun() int {
	_ = userPayload{}
	return userHelper() + userShared() + userCount + userLimit + userTotal
}

var _ = orderRun
""",
    'user.go': """package pkglevel

// The prefix is an ownership prefix and grants nothing, so this is still
// private to its namespace.
func userHelper() int { return 1 } // want `func userHelper is private to namespace "user", but is used from namespace "order"`

// Surplus is always an explicit act.
//
//declscope:shared
func userShared() int { return 2 }

// Exported identifiers carry no boundary, and no prefix unless
// rules.naming.exported asks for one.
func Exported() int { return userHelper() }

var userCount int // want `var userCount is private to namespace "user", but is used from namespace "order"`

//declscope:shared
var userTotal int

const userLimit = 10 // want `const userLimit is private to namespace "user", but is used from namespace "order"`

type userPayload struct{} // want `type userPayload is private to namespace "user", but is used from namespace "order"`

// Used only inside its own namespace, and none the worse for carrying the
// prefix: the prefix says which unit owns it, not how far it reaches.
func userLocal() int { return userCount }

var _ = userLocal
""",
}

SRC_MEMBERS = {
    'order.go': """package members

func orderDump(u *User) string {
	u.normalize()
	return u.name
}

var _ = orderDump
var _ = userMake
""",
    'user.go': """package members

type User struct {
	// ID is exported, so it resolves to shared and carries no boundary. The
	// owner plays no part.
	ID int
	// name is unexported, so it is bounded by the namespace declaring User.
	name string // want `field User.name is private to namespace "user", but is used from namespace "order"`
	// note is only touched inside this namespace.
	note string
}

func (u *User) normalize() { // want `method User.normalize is private to namespace "user", but is used from namespace "order"`
	u.note = u.name
}

// Name is exported, so it carries no boundary either.
func (u *User) Name() string { return u.name }

//declscope:shared
func userMake(name string) *User {
	u := &User{name: name}
	u.normalize()
	return u
}
""",
}

SRC_FOREIGNMETHOD = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts which methods it
# reaches once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
  surplus: off
""",
    'order.go': """package foreignmethod

// A foreign method: userRecord is declared in user.go, so the receiver names a
// unit that does not hold this method. The rule asks for order.
func (u *userRecord) leak() string { // want `method leak does not carry namespace "order" anywhere in its name; rename it to orderLeak, or to another name that carries "order"`
	return u.name
}

// Already carrying the namespace: nothing is asked.
func (u *userRecord) orderDump() string { return u.name }

func orderRun(s userSealed) string {
	u := userMake()
	return u.bump() + u.leak() + u.orderDump()
}
""",
    'user.go': """package foreignmethod

type userRecord struct { // want `type userRecord is private to namespace "user", but is used from namespace "order"`
	name string // want `field userRecord.name is private to namespace "user", but is used from namespace "order"`
}

// A local method is read through a receiver that names the unit holding it, so
// the naming rule asks nothing of it.
func (u *userRecord) bump() string { // want `method userRecord.bump is private to namespace "user", but is used from namespace "order"`
	return u.name
}

// An interface method name is a member, not a method with a receiver.
type userSealed interface { // want `type userSealed is private to namespace "user", but is used from namespace "order"`
	seal()
}

func userMake() *userRecord { return &userRecord{} } // want `func userMake is private to namespace "user", but is used from namespace "order"`
""",
}

SRC_BOUNDARYOFF = {
    '.declscope.yaml': """# The boundary rule is off, so reach goes unchecked and the naming rule is all
# that is left. surplus goes with it: a //declscope:shared directive means
# nothing once nothing enforces reach.
rules:
  naming:
    qualify: ondemand
  boundary: off
  surplus: off
""",
    'order.go': """package boundaryoff

// orderRun carries its namespace, so the naming rule is quiet about it. It
// reaches across a boundary that nothing is checking.
func orderRun() int { return userCache() }

// helper does not carry "order", and the naming rule still says so.
func helper() int { return 2 } // want `func helper does not carry namespace "order" anywhere in its name; rename it to orderHelper, or to another name that carries "order"`

var _ = orderRun
""",
    'user.go': """package boundaryoff

// userCache is private to this file, and order.go reaches it. With the
// boundary rule off, that is not reported.
func userCache() int { return 1 }
""",
}

SRC_FILTERCANCELLED_SUB = {
    '.declscope.yaml': """# The root admits only keep/, and nothing under sub/ is in it.
filter:
  only:
    - "keep/**"
""",
    'sub/.declscope.yaml': """# This only matches the files beside it, and the root's only removes them all,
# so the package is read as empty and the config can never take effect.
filter:
  only:
    - "*.go"
""",
    'sub/a.go': 'package sub // want `filter\\.only stated in .* matches 1 file\\(s\\) here, but an only above it removes them all, so this package is read as empty`\n\nfunc helper() int { return 1 }\n',
}

SRC_IGNOREFILTER = {
    'a.go': """//declscope:ignore filter // want `unused file-level //declscope:ignore filter`

package ignorefilter

// The filter rule reports a chain of config files, and the package it reports
// had nothing read from it, so no ignore there is ever read. An ignore naming
// the rule silences nothing, and the unused rule reports it like any other.
func helper() int { return 1 }

var _ = helper()
""",
}

SRC_EMPTYFILE = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what the namespace
# count does once it is in force.
rules:
  naming:
    qualify: ondemand
""",
    'doc.go': """// Package emptyfile documents itself and declares nothing.
package emptyfile
""",
    'emptyfile.go': """package emptyfile

// doc.go holds a package comment and nothing else, so it is not a second unit.
// The naming rule stays out, and this name is left alone.
func seed() int { return 1 }

var _ = seed
""",
}

SRC_BLANKIMPORT = {
    '.declscope.yaml': """# A file holding only a blank import still declares something: the import runs.
rules:
  naming:
    qualify: ondemand
""",
    'blankimport.go': """package blankimport

// driver.go declares nothing but an import, which registers whatever the
// imported package registers. That is a second namespace, so the rule applies.
func seed() int { return 1 } // want `func seed does not carry namespace "blankimport" anywhere in its name; rename it to blankimportSeed, or to another name that carries "blankimport"`

var _ = seed
""",
    'driver.go': """package blankimport

import _ "errors"
""",
}

SRC_IGNOREDIRECTIVE = {
    '.declscope.yaml': """# Focused on which ignore answers a report of the directive rule. The naming
# rule is stated off so that the ignores here silence nothing by accident: an
# ignore that did silence something would not be judged unused.
rules:
  naming:
    qualify: never
  unused: loose
""",
    'decl.go': """package ignoredirective

// A malformed directive is answered by an ignore on the same declaration,
// where the two are still in hand together. Nothing is reported for either:
// the ignore silenced the report about the typo, so it is not unused.
//
//declscope:bogus
//declscope:ignore directive
func declTypo() int { return 3 }

// An ignore for the directive rule answers no unused report. That report is
// the unused rule's, so the ignore silenced nothing and is reported beside
// the directive it was written for.
//
//declscope:shared // want `unused //declscope:shared on DeclLeftover: nothing it reaches takes a scope`
//declscope:ignore directive // want `unused //declscope:ignore directive on DeclLeftover`
func DeclLeftover() int { return 4 }

// An ignore for the unused rule answers no directive report.
//
//declscope:bogus // want `unknown directive declscope:bogus`
//declscope:ignore unused // want `unused //declscope:ignore unused on declWrongRule`
func declWrongRule() int { return 5 }

// The doc comment and the trailing comment of an ungrouped type or var are one
// binding, as a func's are.
//
//declscope:bogus
type declTypoType int //declscope:ignore directive

//declscope:bogus
var declTypoVar declTypoType = 6 //declscope:ignore directive

// So are a block's doc comment and the comment after its "(".
//
//declscope:bogus
var ( //declscope:ignore directive
	declTypoBlock = 7
)

var _ = int(declTypoVar) + declTypoBlock + declTypo() + DeclLeftover() + declWrongRule()
""",
    'file.go': """//declscope:ignore directive

package ignoredirective

// A report about a directive hangs on a comment, not on a declaration, so a
// declaration-level ignore can never answer one written where no declaration
// is. The file-level ignore above stands the rule down for the whole file,
// which is why nothing below is reported.
func fileLoose() int {
	//declscope:shared
	return 1
}

// The unused-ignore report is the unused rule's, not the directive rule's, so
// the file-level ignore above does not answer it.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary on fileLoud`
func fileLoud() int { return 2 }

var _ = fileLoose() + fileLoud()
""",
}

SRC_IGNOREUNUSED = {
    '.declscope.yaml': """# Focused on which ignore answers the unused rule's report on another ignore.
# The naming rule is stated off so that the ignores here silence nothing by
# accident: an ignore that did silence something would not be judged unused.
rules:
  naming:
    qualify: never
""",
    'decl.go': """package ignoreunused

// An ignore beside this one that names the unused rule answers for it: the
// author has already said that the unused report on this declaration's
// directives is not to be made. Answering it is a use.
//
//declscope:ignore qualify
//declscope:ignore unused
func declQuiet() int { return 1 }

// Without that sibling the same ignore is reported, which is what makes the
// line above a decision rather than a blanket.
//
//declscope:ignore qualify // want `unused //declscope:ignore qualify on declLoud`
func declLoud() int { return 2 }

// A bare ignore covers the unused rule, but on a declaration it answers no
// sibling: it would let a group of ignores exempt one another. Both are
// reported.
//
//declscope:ignore qualify // want `unused //declscope:ignore qualify on declBare`
//declscope:ignore // want `unused //declscope:ignore on declBare`
func declBare() int { return 3 }

// An ignore never answers its own report, whatever it names. One that could
// would never be called unused.
//
//declscope:ignore unused // want `unused //declscope:ignore unused on declSelf`
func declSelf() int { return 4 }

//declscope:ignore qualify,unused // want `unused //declscope:ignore qualify,unused on declBoth`
func declBoth() int { return 5 }

// The unused report on a scope directive is answered by an ignore naming the
// rule on the same declaration, and a bare one there answers it too.
//
//declscope:shared
//declscope:ignore unused
func DeclNamed() int { return 6 }

//declscope:shared
//declscope:ignore
func DeclBare() int { return 7 }

// The doc comment and the trailing comment of an ungrouped type or var are one
// binding, as a func's are, so the ignore trailing it answers the doc's
// directive.
//
//declscope:private
type declTrailingType int //declscope:ignore unused

//declscope:private
var declTrailingVar declTrailingType = 8 //declscope:ignore unused

// So are a block's doc comment and the comment after its "(".
//
//declscope:private
var ( //declscope:ignore unused
	declBlockVar = 9
)

var _ = int(declTrailingVar) + declBlockVar + declQuiet() + declLoud() + declBare() + declSelf() + declBoth() + DeclNamed() + DeclBare()
""",
    'fileanswer.go': """//declscope:ignore unused
//declscope:shared

package ignoreunused

// The file-level ignore above answers every unused report in the file: the
// file's own scope directive, which nothing takes since everything here is
// exported, and the declaration's ignore below, which silences nothing.
// Answering them is its use, so nothing in this file is reported.

//declscope:ignore boundary
func FileAnswered() int { return 1 }

var _ = FileAnswered()
""",
    'filebare.go': """//declscope:ignore // want `unused file-level //declscope:ignore`

package ignoreunused

// A bare file-level ignore covers every rule, the unused rule included, and
// still never its own report. Nothing here needs it, so it is reported.
func fileBare() int { return 1 }

var _ = fileBare()
""",
    'filepair.go': """//declscope:ignore
//declscope:ignore boundary

package ignoreunused

// At the file level a bare ignore answers another's report, since it stands
// every rule down for the file. The second ignore silences nothing, the first
// answers its report, and neither is reported.
func filePair() int { return 1 }

var _ = filePair()
""",
    'fileself.go': """//declscope:ignore unused // want `unused file-level //declscope:ignore unused`

package ignoreunused

// A file-level ignore naming the unused rule answers the reports of the file,
// but not its own. Nothing else here needs it, so it is reported.
func fileSelf() int { return 1 }

var _ = fileSelf()
""",
}

SRC_IGNOREUNSEEN = {
    'a.go': """package ignoreunseen

// aHelper is crossed into only by tagged.go, which the build leaves out. A
// configuration that reads that file reports the crossing, and the ignore
// answers it there, so it is not unused here.
//
//declscope:ignore boundary // tagged.go calls it behind the never tag
func aHelper() int { return 1 }

// A bare ignore covers boundary too.
//
//declscope:ignore
func aBare() int { return 2 }

// No unseen file names aStale, so its ignore silences nothing anywhere.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary on aStale`
func aStale() int { return 3 }

// qualify is judged on the declaration, not on its uses, so an unseen file
// naming aQualify cannot make its ignore needed.
//
//declscope:ignore qualify // want `unused //declscope:ignore qualify on aQualify`
func aQualify() int { return 4 }

func A() int { return aHelper() + aBare() + aStale() + aQualify() }

// tagged.go writes an aPoint by position, which crosses into x without
// naming it. The type's name counts for its fields.
type aPoint struct {
	//declscope:ignore boundary // tagged.go writes it by position
	x int
}

// tagged.go writes an aCoord through an alias, which counts too.
type aCoord struct {
	//declscope:ignore boundary // tagged.go writes it by position, through aAlias
	y int
}

type aAlias = aCoord

// Nothing unseen names aPair or its field, so the ignore silences nothing.
type aPair struct {
	//declscope:ignore boundary // want `unused //declscope:ignore boundary on aPair.z`
	z int
}

func B() int { return aPoint{x: 1}.x + aAlias{y: 2}.y + aPair{z: 3}.z }
""",
    'filelevel.go': """// A file-level ignore reaches every declaration of its file, and tagged.go
// crosses into one of them.
//
//declscope:ignore boundary

package ignoreunseen

func filelevelHelper() int { return 5 }
""",
    'tagged.go': """//go:build never

package ignoreunseen

// This file is left out of the build. It crosses into a.go's declarations.
func Tagged() int { return aHelper() + aBare() + aQualify() + filelevelHelper() }

// Unkeyed literals fill the fields by position.
func Positional() (aPoint, aAlias) { return aPoint{1}, aAlias{2} }
""",
}

SRC_IGNOREUNSEENTEST = {
    'a.go': """package ignoreunseentest

// The only test file is b_tagged_test.go, which the build leaves out, so the
// package has no test variant. The non-test variant reads it for its names,
// as for any excluded file, and judges the ignores.

// aHelper is crossed into only by b_tagged_test.go. A configuration that
// reads that file reports the crossing, and the ignore answers it there, so
// it is not unused here.
//
//declscope:ignore boundary // b_tagged_test.go calls it behind the never tag
func aHelper() int { return 1 }

// No unseen file names aStale, so its ignore silences nothing anywhere.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary on aStale`
func aStale() int { return 2 }

func A() int { return aHelper() + aStale() }
""",
    'b_tagged_test.go': """//go:build declscope_never

package ignoreunseentest

// This test file is left out of the build. It crosses into a.go.
var _ = aHelper
""",
}

SRC_IGNOREMODULEWIDE = {
    '.declscope.yaml': """# Focused on ignores naming overexported, which only declscope shrink reports.
# The naming rule is stated off so that nothing else is silenced by accident.
rules:
  naming:
    qualify: never
""",
    'a.go': """package ignoremodulewide

// An ignore naming overexported silences nothing this analyzer reports, and
// it may be doing its job in declscope shrink, which this pass cannot see. It
// is not called unused here.
//
//declscope:ignore overexported
func Shrunk() int { return 1 }

// Naming another rule beside it does not make the analyzer the judge either:
// the part it cannot see may be the part in use.
//
//declscope:ignore overexported,qualify
func Mixed() int { return 2 }

// A bare ignore does not reach overexported, so the analyzer can judge it
// alone, and one that silenced nothing it reports is unused.
//
//declscope:ignore // want `unused //declscope:ignore on Bare`
func Bare() int { return 3 }

// An ignore naming unused beside one naming overexported may be answering
// the unused report declscope shrink makes, which this pass cannot see, so it
// is not called unused here either.
//
//declscope:ignore overexported
//declscope:ignore unused
func Answering() int { return 4 }
""",
    'b.go': """// A file-level ignore covering unused, in a file holding an ignore that names
// overexported, may be answering that ignore's unused report in declscope
// shrink, so it is not called unused here.
//
//declscope:ignore unused

package ignoremodulewide

//declscope:ignore overexported
func FileAnswered() int { return 5 }
""",
    'c.go': """// The same file-level ignore in a file with no such ignore answers nothing
// declscope shrink reports, and the analyzer judges it as always.
//
//declscope:ignore unused // want `unused file-level //declscope:ignore unused`

package ignoremodulewide

func Plain() int { return 6 }
""",
}

SRC_DIRECTIVES = {
    '.declscope.yaml': """rules:
  unused: loose
""",
    'order.go': """package directives

func orderRun() int {
	return userExplicitlyShared() + userNotReallyShared() + userIgnoredLeak() +
		userTrailing() + userSharedA + userPrivateB + userSharedC + userPrivateD
}

var _ = orderRun
""",
    'report.go': """//declscope:namespace user

package directives

// This file joins namespace "user", so it may use its namespace-private
// declarations without surplus them, and its own declarations carry the
// "user" prefix rather than a "report" one.
func userReportAll() int {
	return userExplicitlyShared() + userNotReallyShared() + userIgnoredLeak() +
		userTrailing() + userSharedA + userPrivateB + userSharedC + userPrivateD
}

var _ = userReportAll
var _ = userNeverLeaks
var _ = userTypo
""",
    'user.go': """package directives

//declscope:shared
func userExplicitlyShared() int { return 1 }

//declscope:private
func userNotReallyShared() int { return 2 } // want `func userNotReallyShared is declared private by //declscope:private, but is used from namespace "order"`

//declscope:ignore
func userIgnoredLeak() int { return 3 }

//declscope:ignore // want `unused //declscope:ignore on userNeverLeaks`
func userNeverLeaks() int { return 4 }

//declscope:bogus // want `unknown directive declscope:bogus`
func userTypo() int { return 5 }

// Only Go's canonical //tool:name form is a directive. Anything else
// addressed to declscope is reported and takes no effect.

// declscope:shared // want `malformed declscope directive: write it as //declscope:name`
func userSpaced() int { return 7 }

//declscope: package // want `malformed declscope directive: write it as //declscope:name`
func userSpacedName() int { return 8 }

/*declscope:shared*/ // want `malformed declscope directive: write it as //declscope:name`
func userBlock() int { return 9 }

//declscope:Package // want `malformed declscope directive: write it as //declscope:name`
func userUppercase() int { return 10 }

func userTrailing() int { return 6 } //declscope:shared // used by the reporting code

var (
	//declscope:shared
	userSharedA  = 1
	userPrivateB = 2 // want `var userPrivateB is private to namespace "user", but is used from namespace "order"`
)

// A scope directive on the block reaches every spec, and one on a spec
// replaces it: a declaration has exactly one scope.
//
//declscope:shared
var (
	userSharedC = 3
	//declscope:private
	userPrivateD = 4 // want `var userPrivateD is declared private by //declscope:private, but is used from namespace "order"`
)
""",
}

SRC_DUPLICATEDIRECTIVE = {
    'order.go': """package duplicatedirective

func orderRun() int {
	return sharedHelper() + userShared() + UserPrivate() + userIgnored() + userTrailing() + userWider()
}

var _ = orderRun
""",
    'shared.go': """// A file-level scope written twice is reported at the second. The first still
// shares the file, so the use from order.go is not reported.
//
//declscope:shared
//declscope:shared // want `duplicate declscope:shared directive`

package duplicatedirective

func sharedHelper() int { return 1 }
""",
    'user.go': """package duplicatedirective

// A scope directive written twice is reported at the second. The first still
// decides the scope.
//
//declscope:shared
//declscope:shared // want `duplicate declscope:shared directive`
func userShared() int { return 2 }

//declscope:private
//declscope:private // want `duplicate declscope:private directive`
func UserPrivate() int { return 3 } // want `func UserPrivate is declared private by //declscope:private, but is used from namespace "order"`

// An ignore naming the same rules as one before it, in any order, is reported
// at the second and dropped. The first silences the use from order.go.
//
//declscope:ignore boundary,qualify
//declscope:ignore qualify,boundary // want `duplicate declscope:ignore directive`
func userIgnored() int { return 4 }

// The doc comment and a trailing comment are one binding, so a repeat across
// the two is a duplicate too.
//
//declscope:ignore boundary
func userTrailing() int { return 5 } //declscope:ignore boundary // want `duplicate declscope:ignore directive`

// Dropped, the duplicate is no second site for the unused report: the one
// mistake gets one report. The first ignore silences nothing and is reported
// on its own.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary on userNeverLeaks`
//declscope:ignore boundary // want `duplicate declscope:ignore directive`
func userNeverLeaks() int { return 6 }

// An ignore naming a rule the other leaves out is no duplicate.
//
//declscope:ignore boundary
//declscope:ignore boundary,surplus
func userWider() int { return 7 }

var _ = userNeverLeaks
""",
}

SRC_TESTNS = {
    'calc.go': """package testns

// helper is private to namespace "calc". A _test.go file shares its
// subject's namespace, so using it from calc_test.go is not a violation.
func helper() int { return 1 }

func calcShared() int { return helper() }
""",
    'calc_test.go': """package testns

import "testing"

func TestHelper(t *testing.T) {
	if helper() != 1 {
		t.Fatal("unexpected")
	}
	if calcShared() != 1 {
		t.Fatal("unexpected")
	}
}
""",
}

SRC_GENERATED = {
    'gen.go': """// Code generated by a tool. DO NOT EDIT.

package generated

func genSecret() int { return 1 }
""",
    'use.go': """package generated

// Generated files are excluded entirely, so referencing genSecret from another
// namespace produces no diagnostic.
func useRun() int { return genSecret() }

var _ = useRun
""",
}

SRC_QUALIFYRULE = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package qualifyrule

// A second namespace, which is what gives the prefixes something to distinguish.
// It deliberately touches nothing in namespace "user", so the only rule under
// test here is the naming rule.
func orderRun() int { return 1 }

var _ = orderRun
""",
    'user.go': """package qualifyrule

// Unexported package-level declarations must say which unit owns them.
func helper() int { return 1 } // want `func helper does not carry namespace "user" anywhere in its name; rename it to userHelper, or to another name that carries "user"`

// The right edge of the match is free, so a plural spells the namespace as
// plainly as the singular would.
func users() int { return 2 }

var count int // want `var count does not carry namespace "user" anywhere in its name; rename it to userCount, or to another name that carries "user"`

const limit = 3 // want `const limit does not carry namespace "user" anywhere in its name; rename it to userLimit, or to another name that carries "user"`

type payload struct { // want `type payload does not carry namespace "user" anywhere in its name; rename it to userPayload, or to another name that carries "user"`
	// Members are exempt: they are already namespaced by the type that owns
	// them, and a prefix here would be the stutter Go idiom avoids.
	field int
}

func (p *payload) method() int { return p.field }

// Exported identifiers need no prefix by default; rules.naming.exported asks
// them for one.
func Exported() int {
	p := &payload{}
	return helper() + users() + count + limit + p.method() + userOK() + newUser() + deliberatelyUnprefixed()
}

// Already prefixed.
func userOK() int { return 4 }

// The namespace need not lead the name: Go spells a constructor newX, and the
// namespace inside it marks the owner as plainly as a prefix would.
func newUser() int { return 6 }

//declscope:ignore
func deliberatelyUnprefixed() int { return 5 }
""",
    'user_test.go': """package qualifyrule

import "testing"

// The toolchain finds a test by its name, so no rename is asked of it.
func TestUser(t *testing.T) { _ = fixture() }

// Any other function in a test file is an ordinary declaration.
func fixture() int { return 1 } // want `func fixture does not carry namespace "user" anywhere in its name; rename it to userFixture, or to another name that carries "user"`
""",
}

SRC_SINGLENS = {
    '.declscope.yaml': """# ondemand is stated so that the silence below is the rule's own: in a package
# with one namespace it asks nothing, not because the rule is off (the default)
# but because there is no boundary for a prefix to mark.
rules:
  naming:
    qualify: ondemand
""",
    'a.go': """//declscope:namespace shared

package singlens

// The package has a single namespace, so there is no boundary for a prefix to
// mark and the prefix is not required. Every other rule is structurally inert
// here too, since every reference is already inside the one namespace.
func helper() int { return 1 }

var count int
""",
    'b.go': """//declscope:namespace shared

package singlens

func use() int { return helper() + count }

var _ = use
""",
}

SRC_QUALIFYINFLECT = {
    '.declscope.yaml': """# The naming rule is off by default, and this package pins what the inflected
# forms buy it — and what the stem of a namespace must never buy.
rules:
  naming:
    qualify: ondemand
""",
    'apply.go': """package qualifyinflect

// The final y turns to i: applied is appli + ed, and the generated form
// accepts it wherever it opens a word.
func appliedResults() int { return 3 }

var _ = appliedResults
""",
    'store.go': """package qualifyinflect

// The namespace's own spelling changes under -ing, so plain containment
// cannot see it: storing is stor + ing, not store + anything. The generated
// form accepts it.
func storing() int { return 1 }

// Only the generated whole form counts. A name that merely shares the stem
// does not carry the namespace: matching stor loose would accept story, which
// has nothing to do with store.
func story() int { return 2 } // want `func story does not carry namespace "store" anywhere in its name; rename it to storeStory, or to another name that carries "store"`

var _, _ = storing, story
""",
}

SRC_QUALIFYINFLECTED = {
    '.declscope.yaml': """# The naming rule is off by default. This package pins the message an
# inflected namespace gets: its stem does not carry it, and the vocabulary key
# to list the stem under.
rules:
  naming:
    qualify: ondemand
""",
    'string.go': """package qualifyinflected

// string ends in -ing, but str holds no vowel, so it is not read as an
// inflected form and the message has nothing to add.
func quote() int { return 3 } // want `func quote does not carry namespace "string" anywhere in its name; rename it to stringQuote, or to another name that carries "string"$`

var _ = quote
""",
    'tracing.go': """package qualifyinflected

// tracing is trace + ing with the e dropped, but generation never runs back
// from tracing to trace: the stem would be a guess. The message points at the
// vocabulary instead, since the rename would stutter.
func traceValue() int { return 1 } // want `func traceValue does not carry namespace "tracing" anywhere in its name; rename it to tracingTraceValue, or to another name that carries "tracing"; if the name spells "tracing" in another form, list that form under rules.naming.vocabulary.tracing`

// The free right edge runs only from the namespace, so tracer does not carry
// tracing either.
type tracerType struct{} // want `type tracerType does not carry namespace "tracing" anywhere in its name; rename it to tracingTracerType, or to another name that carries "tracing"; if the name spells "tracing" in another form, list that form under rules.naming.vocabulary.tracing`

// The namespace's own spelling carries it as usual.
func tracingStart() int { return 2 }

var _, _ = traceValue, tracingStart
var _ tracerType
""",
}

SRC_VOCABULARY = {
    '.declscope.yaml': """# The vocabulary maps a namespace to the extra words that carry it: irregular
# inflections and domain synonyms the generated forms cannot reach. The words
# go through the same test as the namespace itself — word boundary on the
# left, free right edge — which pinwheel below is the negative for.
rules:
  naming:
    qualify: ondemand
    vocabulary:
      mouse: [wheel]
      index: [indices]
""",
    'index.go': """package vocabulary

// The irregular plural, listed as vocabulary because no generated inflection
// produces it. The right edge stays free, so the word may end inside the name.
func indicesSorted() int { return 5 }

var _ = indicesSorted
""",
    'mouse.go': """package vocabulary

// wheel is listed under the mouse namespace, so it carries the namespace the
// way mouse itself would.
func wheelDelta() int { return 1 }

// A vocabulary word must still open a word of the name: pinwheel spells wheel
// with no boundary before it, the monkey/key shape.
func pinwheel() int { return 2 } // want `func pinwheel does not carry namespace "mouse" anywhere in its name; rename it to mousePinwheel, or to another name that carries "mouse"`

// A name outside the vocabulary is asked as usual.
func scrollSpeed() int { return 3 } // want `func scrollSpeed does not carry namespace "mouse" anywhere in its name; rename it to mouseScrollSpeed, or to another name that carries "mouse"`

// The namespace's own spelling still counts, vocabulary or not.
func mouseButton() int { return 4 }

var _, _, _, _ = wheelDelta, pinwheel, scrollSpeed, mouseButton
""",
}

SRC_QUALIFYDEFAULT = {
    'order.go': """package qualifydefault

func orderRun() int { return helper() }

var _ = orderRun
""",
    'user.go': """package qualifydefault

// No config reaches this package, so the naming rule is at its default: off.
// helper carries no namespace and draws no qualify diagnostic even though the
// package has a second namespace. The boundary rule is untouched by the
// default and still fires below.
func helper() int { return 1 } // want `func helper is private to namespace "user", but is used from namespace "order"`

// bare is used only from its own namespace: no boundary, and no qualify.
func bare() int { return helper() }

var _ = bare
""",
}

SRC_NSDETACHED = {
    'a.go': """//declscope:namespace shared

// Package nsdetached checks that a namespace directive is recognized when a
// blank line separates it from the package clause, which is how a file that
// already carries a package doc comment keeps the two apart.
package nsdetached

func helper() int { return 1 }
""",
    'b.go': """//declscope:namespace shared

package nsdetached

func use() int { return helper() }

var _ = use
""",
}

SRC_NSINDOC = {
    'a.go': """// Package nsindoc checks the placement Go's own doc comment convention
// prescribes for directives: at the bottom of the package comment, preceded by
// a blank comment line. go/doc strips directive lines, so the rendered package
// documentation is unaffected.
//
//declscope:namespace shared
package nsindoc

func helper() int { return 1 }
""",
    'b.go': """//declscope:namespace shared

package nsindoc

func use() int { return helper() }

var _ = use
""",
}

SRC_BASELINED = {
    '.declscope-baseline.yaml': """packages:
  baselined:
    boundary:
      user:
        - User.name
        - userHelper
""",
    'order.go': """package baselined

func orderRun(u *User) string {
	_ = userHelper() + userFresh()
	return u.name + u.note
}

var _ = orderRun
""",
    'user.go': """package baselined

// userHelper is recorded in the baseline, so it stays quiet.
func userHelper() int { return 1 }

// userFresh is not, so it is reported.
func userFresh() int { return 2 } // want `func userFresh is private to namespace "user", but is used from namespace "order"`

type User struct {
	// name is recorded in the baseline.
	name string
	// note is not.
	note string // want `field User.note is private to namespace "user", but is used from namespace "order"`
}
""",
}

SRC_QUALIFYBASELINED = {
    '.declscope-baseline.yaml': """packages:
  qualifybaselined:
    qualify:
      user:
        - orderA.help
""",
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts how a baseline
# absorbs what it reports.
rules:
  naming:
    qualify: always
""",
    'order.go': """package qualifybaselined

//declscope:shared // user.go declares a method on it
type orderA struct{}

//declscope:shared // user.go declares a method on it
type orderB struct{}
""",
    'user.go': """package qualifybaselined

// orderA.help is recorded in the baseline, so it stays quiet.
func (orderA) help() int { return 1 }

// orderB.help shares its name and namespace but not its receiver, so the
// entry for orderA.help does not absorb it.
func (orderB) help() int { return 2 } // want `method help does not carry namespace "user" anywhere in its name; rename it to userHelp, or to another name that carries "user"`

var _, _ = orderA{}.help, orderB{}.help
""",
}

SRC_EXPLICIT = {
    '.declscope.yaml': """rules:
  unused: loose
""",
    'order.go': """package explicit

func orderRun() int {
	_ = userShape{}
	return userForced()
}

var _ = orderRun
""",
    'user.go': """package explicit

// userForced carries the namespace prefix but is forced private, so the
// name and the directive disagree with the use site. Both are deliberate
// statements by the author, so no fix is offered: -fix must not silently
// overwrite a directive that was written on purpose, and renaming alone would
// leave the directive keeping it private while the new name claims otherwise.
//
//declscope:private
func userForced() int { return 1 } // want `func userForced is declared private by //declscope:private, but is used from namespace "order"`

//declscope:private
type userShape struct{} // want `type userShape is declared private by //declscope:private, but is used from namespace "order"`
""",
}

SRC_QUALIFYALWAYS = {
    '.declscope.yaml': """# Require the prefix even in a package with one namespace, so that gaining a
# second one is not a mass rename.
rules:
  naming:
    qualify: always
""",
    'only.go': """package qualifyalways

// The package has a single namespace, so the default would not require a
// prefix here. rules.qualify: always asks for it anyway.
func helper() int { return 1 } // want `func helper does not carry namespace "only" anywhere in its name; rename it to onlyHelper, or to another name that carries "only"`

func onlyOK() int { return helper() }

var _ = onlyOK
""",
}

SRC_IGNORESCOPE = {
    '.declscope.yaml': """# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package ignorescope

func orderRun() int {
	return helper() + helper2() + userKept() + userTypo() + helper3() + userBlockA + userBlockB
}

var _ = orderRun
""",
    'user.go': 'package ignorescope\n\n// Silencing one rule leaves the rest in force: the missing prefix is ignored,\n// the boundary crossing is not.\n//\n//declscope:ignore qualify\nfunc helper() int { return 1 } // want `func helper is private to namespace "user", but is used from namespace "order"`\n\n// Silencing everything.\n//\n//declscope:ignore\nfunc helper2() int { return 2 }\n\n// Two directives, each judged on its own: the crossing is silenced and so the\n// first is used, while qualify never fires on a name that carries its\n// namespace, so the second is reported.\n//\n//declscope:ignore boundary\n//declscope:ignore qualify // want `unused //declscope:ignore qualify on userKept`\nfunc userKept() int { return 3 }\n\n// An unparseable directive silences nothing.\n//\n//declscope:ignore bogus // want `unknown rule "bogus" in declscope:ignore \\(want one of boundary, qualify, surplus, unused, directive, filter, overexported\\)`\nfunc userTypo() int { return 4 } // want `func userTypo is private to namespace "user", but is used from namespace "order"`\n\n//declscope:ignore boundary,qualify\nfunc helper3() int { return 5 }\n\n// Ignores accumulate across a block and its specs rather than the spec\'s\n// replacing the block\'s: the bare ignore on the block keeps silencing boundary\n// for userBlockB, and only its own qualify — needless on a prefixed name — is\n// unused.\n//\n//declscope:ignore\nvar (\n\tuserBlockA = 6\n\t//declscope:ignore qualify // want `unused //declscope:ignore qualify on userBlockB`\n\tuserBlockB = 7\n)\n',
}

SRC_FILEIGNORE = {
    '.declscope.yaml': """# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
""",
    'clean.go': """//declscope:ignore qualify // want `unused file-level //declscope:ignore qualify`

package fileignore

// The name carries its namespace, so the directive silences nothing.
func cleanOK() int { return 4 }

var _ = cleanOK
""",
    'order.go': """package fileignore

func orderRun() int { return helper2() + thing() }

var _ = orderRun
""",
    'quiet.go': """//declscope:ignore

package fileignore

// A bare file-level ignore silences every rule, reach included.
func thing() int { return 3 }
""",
    'util.go': """//declscope:ignore qualify

package fileignore

// The file stands outside the naming rule, so neither of these is asked to
// carry the "util" prefix.
func helper() int { return 1 }

// The boundary still holds: only qualify was silenced.
func helper2() int { return 2 } // want `func helper2 is private to namespace "util", but is used from namespace "order"`

var _ = helper
""",
}

SRC_FILEIGNORESCOPE = {
    '.declscope.yaml': """# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package fileignorescope

// A second namespace, so the naming rule applies at all.
func orderRun() int { return 3 }

var _ = orderRun
""",
    'util.go': """//declscope:ignore qualify

package fileignorescope

// This file stands outside the naming rule.
func helper() int { return 1 }

var _ = helper
""",
    'util_extra.go': """//declscope:namespace util

package fileignorescope

// The same namespace as util.go, but a file-level ignore belongs to the file
// that carries it, so this one is still asked for its prefix.
func extra() int { return 2 } // want `func extra does not carry namespace "util" anywhere in its name; rename it to utilExtra, or to another name that carries "util"`

var _ = extra
""",
}

SRC_TYPEIGNORE = {
    '.declscope.yaml': """# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package typeignore

func orderRun(u *User, o *Open, c *Closed) string {
	u.normalize()
	return u.name + string(rune(u.id)) + o.secret + c.hidden
}

var _ = orderRun
""",
    'user.go': """package typeignore

// A directive on the type covers what the type contains: its fields, which are
// written inside this declaration. It does not reach its methods — a method is
// an ordinary top-level declaration, and the suppression chain walks the same
// levels as scope resolution, so that learning one teaches the other.
//
//declscope:ignore boundary
type User struct {
	name string
	id   int
}

// Open carries a directive of its own as well as the one on its type. Both
// count as used, so neither is reported.
//
//declscope:ignore boundary
type Open struct {
	secret string
}

//declscope:ignore qualify // want `unused //declscope:ignore qualify on Closed`
type Closed struct {
	// The type's directive names a rule that never fires, so the field is
	// still reported.
	hidden string // want `field Closed.hidden is private to namespace "user", but is used from namespace "order"`
}
""",
    'user_methods.go': """//declscope:namespace user

package typeignore

// The directive on User does not reach here: a method needs its own. Without
// one this is reported, which is what pins the type's ignore to what the type
// contains.
func (u *User) normalize() { u.name = "x" } // want `method User.normalize is private to namespace "user", but is used from namespace "order"`
""",
}

SRC_DEFAULTSMEMBERS = {
    '.declscope.yaml': """# defaults.unexported must reach members as well as package-level declarations,
# so that a defaults key governs every declaration in a package rather than half
# of them.
defaults:
  unexported: shared
rules:
  naming:
    qualify: never
""",
    'order.go': """package defaultsmembers

func orderRun(u *User) string {
	u.bump()
	u.seal()
	_ = u.name
	return u.secret
}

var _ = orderRun
""",
    'user.go': """package defaultsmembers

// The configured default reaches fields and methods, not only package-level
// declarations, so a key that says "shared" governs every declaration here
// rather than half of them. A directive on one of them still overrides it.
type User struct {
	name string

	//declscope:private
	secret string // want `field User.secret is declared private by //declscope:private, but is used from namespace "order"`
}

func (u *User) bump() {}

//declscope:private
func (u *User) seal() {} // want `method User.seal is declared private by //declscope:private, but is used from namespace "order"`
""",
}

SRC_UNKEYED = {
    'build.go': """package unkeyed

// An unkeyed literal lists every field in declaration order, so each element
// writes one field. None of them is named here.
func buildMake() Entry { return Entry{1, 2, "x"} }

// A keyed literal naming only exported fields crosses nothing.
func buildExported() Entry { return Entry{ID: 3} }

// The same for an instantiation of a generic struct.
func buildPair() Pair[string] { return Pair[string]{4, "y"} }

// Each literal below leaves out a pointer type, and still writes the fields.
func buildElided() int {
	slots := []*Slot{{1}}
	cells := [...]*Cell{{1}}
	keys := map[*Key]int{{1}: 0}
	values := map[int]*Value{0: {1}}
	deep := [][]*Deep{{{1}}}
	named := []*Named{{count: 1}}
	return len(slots) + len(cells) + len(keys) + len(values) + len(deep) + len(named)
}

// The pointer may be a defined type, or a type parameter whose constraint
// allows only pointers to one struct.
func buildElidedNamed() int {
	slots := []SlotPtr{{1}}
	return len(slots)
}

func buildElidedParam[P interface{ *Snap }]() int {
	snaps := []P{{1}}
	return len(snaps)
}

// A constraint written with a tilde, in an interface the constraint embeds.
func buildElidedTilde[P interface{ SnapPtrs }]() int {
	snaps := []P{{1}}
	return len(snaps)
}

var _ = buildMake
var _ = buildPair
var _ = buildExported
var _ = buildElided
var _ = buildElidedNamed
var _ = buildElidedParam[*Snap]
var _ = buildElidedTilde[*Tilde]
""",
    'entry.go': """package unkeyed

type Entry struct {
	// ID is exported, so it resolves to shared and carries no boundary.
	ID int
	// count is unexported, so it is bounded by the namespace declaring Entry.
	// An unkeyed literal writes it without naming it, and that is still a use.
	count int // want `field Entry.count is private to namespace "entry", but is used from namespace "build"`
	// note is written by the same literal. An unkeyed literal writes every
	// field, so there is no writing one without the others.
	note string // want `field Entry.note is private to namespace "entry", but is used from namespace "build"`
}

func entryMake() Entry { return Entry{ID: 1, count: 2, note: "x"} }

var _ = entryMake

// A generic struct is written the same way. The literal's type is an
// instantiation, whose fields are mapped back to the ones declared here.
type Pair[T any] struct {
	ID  int
	val T // want `field Pair.val is private to namespace "entry", but is used from namespace "build"`
}

// A literal inside another may leave out its type, a pointer one too. In
// []*Slot{{1}} the inner literal has the type *Slot, and writes the fields of
// the struct it points to. Each type below is written in one form only.
type Slot struct {
	count int // want `field Slot.count is private to namespace "entry", but is used from namespace "build"`
}

type Cell struct {
	count int // want `field Cell.count is private to namespace "entry", but is used from namespace "build"`
}

type Key struct {
	count int // want `field Key.count is private to namespace "entry", but is used from namespace "build"`
}

type Value struct {
	count int // want `field Value.count is private to namespace "entry", but is used from namespace "build"`
}

type Deep struct {
	count int // want `field Deep.count is private to namespace "entry", but is used from namespace "build"`
}

// A keyed literal names its fields, so its type does not matter.
type Named struct {
	count int // want `field Named.count is private to namespace "entry", but is used from namespace "build"`
}

// A defined pointer type is a pointer through its underlying type.
type SlotPtr *NamedSlot

type NamedSlot struct {
	count int // want `field NamedSlot.count is private to namespace "entry", but is used from namespace "build"`
}

// A type parameter allowing only *Snap points to Snap.
type Snap struct {
	count int // want `field Snap.count is private to namespace "entry", but is used from namespace "build"`
}

type SnapPtrs interface{ ~*Tilde }

type Tilde struct {
	count int // want `field Tilde.count is private to namespace "entry", but is used from namespace "build"`
}
""",
}

SRC_GENERICS = {
    'list.go': """package generics

// List is exported, but its unexported fields are still in the subject: they
// are written inside this declaration, so the namespace declaring it bounds
// them. go/types records the instantiated member for a
// selection on List[int] — and on List[T] inside the type's own methods —
// so the lookup has to go through the origin object.
type List[T any] struct {
	items []T // want `field List.items is private to namespace "list", but is used from namespace "use"`
	// size is only touched inside this namespace.
	size int
}

func (l *List[T]) push(v T) { // want `method List.push is private to namespace "list", but is used from namespace "use"`
	l.items = append(l.items, v)
	l.size++
}

// Len is exported, so it resolves to shared and carries no boundary.
func (l *List[T]) Len() int { return l.size }

// listNode is a generic type private to this namespace.
type listNode[T any] struct { // want `type listNode is private to namespace "list", but is used from namespace "use"`
	val T // want `field listNode.val is private to namespace "list", but is used from namespace "use"`
}
""",
    'use.go': """package generics

// drain is grown on List from another namespace. It belongs to the file that
// wrote it, so this file may call it; what it reaches for does not. The
// receiver is the generic List[T], which must still resolve to List, so that
// the field selection below is recognized as a use of List.items — that is the
// crossing, and it is reported against list.go.
func (l *List[T]) drain() []T {
	out := l.items
	l.items = nil
	return out
}

func Use(l *List[int]) int {
	l.push(1)
	n := listNode[int]{val: 1}
	_ = l.drain()
	return len(l.items) + n.val + l.Len()
}
""",
}

SRC_EMBEDDED = {
    'order.go': """package embedded

type Order struct {
	userCount
	*userTotal
}

// Count reaches n through the embedding, which is a use of userCount.n.
func (o *Order) Count() int { return o.n }
""",
    'user.go': """package embedded

// userCount is embedded by another namespace. The embedding names the type,
// so it is a use of the type like any other.
type userCount struct { // want `type userCount is private to namespace "user", but is used from namespace "order"`
	n int // want `field userCount.n is private to namespace "user", but is used from namespace "order"`
}

// userTotal is embedded by pointer.
type userTotal struct { // want `type userTotal is private to namespace "user", but is used from namespace "order"`
	sum int
}

// User embeds both inside their own namespace, which crosses nothing.
type User struct {
	userCount
	*userTotal
}

func (u *User) Sum() int { return u.n + u.sum }
""",
}

SRC_MEMBEROWNER = {
    '2fa.go': """package memberowner

// Auth's fields are written inside this declaration, so they are bounded by
// this file's namespace wherever they are read.
type Auth struct {
	secret int // want `field Auth.secret is private to namespace "2fa", but is used from namespace "order"`
}
""",
    'order.go': """package memberowner

// A method is an ordinary top-level declaration: written here, it belongs to
// this file's namespace, so this file may use it and the call below is not a
// crossing. What it may not do is reach into Auth's fields, which belong to the
// file that declares them — and that is the boundary doing the work. Binding
// the method itself to 2fa.go instead would have made it unusable from the file
// that wrote it, with no scope able to say otherwise.
func (a *Auth) helper() int { return a.secret }

func orderRun(a *Auth) int { return a.helper() }

var _ = orderRun
""",
}

SRC_CORENS = {
    '.declscope.yaml': """# The core exists to be left alone by the naming rule, so it is on its
# strictest setting: whatever the core is spared here, it is spared everywhere.
rules:
  naming:
    qualify: always
    exported: true
""",
    'client.go': """//declscope:core

package corens

// The core namespace has no name, so there is no prefix to require or to drop.
// These are the package's API and are asked for nothing.
func New() int { return 1 }

type ClientConfig struct{ retries int }

func helper() int { return 2 } // want `func helper is private to the core namespace, but is used from namespace "retry"`
""",
    'client_test.go': """package corens

import "testing"

// A test file joins its subject's namespace, and the core is a namespace like
// any other: client.go is core, so this file is too and reaches what it
// declares. Deriving the join from the stem alone would leave the core out of
// it, and the only repair would be to widen everything the core holds.
func TestClient(t *testing.T) {
	if helper() == 0 {
		t.Fatal("helper answered zero")
	}
}
""",
    'errors.go': """//declscope:core

package corens

// A second core file shares the one core namespace, the way //declscope:namespace
// merges files under a name — the core simply has none. Sharing it is what makes
// "unprefixed" still name exactly one unit, and lets this file reach client.go's
// private helper.
var ErrClosed = helper()
""",
    'pool.go': """//declscope:core
//declscope:shared

package corens

// The two directives are orthogonal. //declscope:core decides the namespace;
// //declscope:shared decides the scope. A file may carry both, and then what
// it declares is core and package-wide at once.
func acquire() int { return 3 }
""",
    'retry.go': """package corens

// Not core, so an ordinary namespace: the prefix is required here, and carries
// the exportedness of the name it joins.
func WithBackoff() int { return 1 } // want `func WithBackoff does not carry namespace "retry" anywhere in its name; rename it to RetryWithBackoff, or to another name that carries "retry"`

// helper is private to the core, so naming it from here crosses a boundary:
// //declscope:core carries no scope of its own. acquire does not, because
// pool.go states one.
func attempt() int { return helper() + acquire() } // want `func attempt does not carry namespace "retry" anywhere in its name; rename it to retryAttempt, or to another name that carries "retry"`

var _ = attempt
""",
}

SRC_CORENAMEDTEST = {
    'client.go': """//declscope:core

package corenamedtest

func New() int { return 1 }
""",
    'client_test.go': """//declscope:namespace probe

package corenamedtest

// This file shares client.go's stem but names its own namespace. Only a file
// with no namespace directive joins the core, so the directive holds and
// probeHelper is private to probe. The report sits in a test file, which only
// the test variant reads, so it is pinned there alone.
func probeHelper() int { return New() } // want `func probeHelper is private to namespace "probe", but is used from the core namespace`
""",
    'errors.go': """//declscope:core

package corenamedtest

var ErrClosed = New()
""",
    'errors_test.go': """package corenamedtest

import "testing"

// No directive, so this file joins its core subject.
func TestErrClosed(t *testing.T) {
	if ErrClosed != probeHelper() {
		t.Fatal("unexpected")
	}
}
""",
}

SRC_CORETESTSUBJECT = {
    'client.go': """package coretestsubject

// client_test.go is in the core, but this file is not its test, so it keeps
// its own namespace. Joining the core through its test file made the test
// variant report this crossing as private to the core, and a baseline record
// the one declaration under two keys.
func clientHelper() int { return 1 } // want `func clientHelper is private to namespace "client", but is used from namespace "order"`
""",
    'client_test.go': """//declscope:core

package coretestsubject

import "testing"

func TestClient(t *testing.T) {}
""",
    'order.go': """package coretestsubject

func orderTotal() int { return clientHelper() }
""",
}

SRC_COREGOOSSIBLING = {
    'foo.go': """package coregoossibling

// foo_linux.go is in the core, but a GOOS sibling does not join it, so this
// file keeps its namespace in every build. Joining in a linux build only made a
// baseline recorded there suppress nothing elsewhere.
func fooHelper() int { return 1 } // want `func fooHelper is private to namespace "foo", but is used from the core namespace`
""",
    'foo_darwin.go': """//declscope:core

package coregoossibling

func Platform() int { return fooHelper() }
""",
    'foo_linux.go': """//declscope:core

package coregoossibling

func Platform() int { return fooHelper() }
""",
    'foo_windows.go': """//declscope:core

package coregoossibling

func Platform() int { return fooHelper() }
""",
    'platform_other.go': """//go:build !linux && !darwin && !windows

//declscope:core

package coregoossibling

// This keeps the report in a build that compiles none of the GOOS files.
func Platform() int { return fooHelper() }
""",
}

SRC_UNCAPITALIZABLE = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
    exported: true
""",
    'order.go': """package uncapitalizable

// A namespace with a capital form is still held to the rule.
func Total() int { return 1 } // want `func Total does not carry namespace "order" anywhere in its name; rename it to OrderTotal, or to another name that carries "order"`
""",
    'under.go': """//declscope:namespace _foo

package uncapitalizable

// _foo is a valid namespace, but _ has no capital form either, so Save is not
// asked to become _fooSave.
func Save() int { return 1 }
""",
    '用户.go': """package uncapitalizable

// 用户 has no capital form, so an exported name could neither carry it nor take
// it as a prefix and stay exported. The naming rule asks nothing here, as for
// 2fa.go; it used to tell the author to rename Load to 用户Load, which
// unexports it.
func Load() int { return 1 }

func helper() int { return 2 }

var _ = helper
""",
}

SRC_FILESCOPE = {
    'caller.go': """package filescope

func callerRun() int {
	_ = utilMust(nil)
	return utilFirst([]int{1}) + utilCache
}

var _ = callerRun
""",
    'util.go': """//declscope:shared

package filescope

// A file whose whole contents are meant to be package-wide says so in one line,
// with a scope rather than an ignore. The difference is endorsing rather than
// suppressing: these declarations *are* package, so the naming rule still reaches
// them, and one that turns out not to be shared can be narrowed back below.
func utilMust(e error) error { return e }

func utilFirst(s []int) int { return s[0] }

// A declaration may still state its own scope, which outranks the file's. Under
// an ignore this line would have meant nothing at all.
//
//declscope:private
var utilCache int // want `var utilCache is declared private by //declscope:private, but is used from namespace "caller"`
""",
}

SRC_EXPORTEDPREFIXES = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
    exported: true
""",
    'client.go': """package exportedprefixes

// The prefix carries the exportedness of the name it joins: New becomes
// ClientNew, never clientNew. A rename that quietly unexported a declaration
// would delete the package's API to satisfy a linter.
func New() int { return 1 } // want `func New does not carry namespace "client" anywhere in its name; rename it to ClientNew, or to another name that carries "client"`

// No rename is offered for an exported declaration — its uses outside the
// package are never analyzed, so the rewrite could not be completed — so the
// suggested name in the message is all the author gets. fixexported pins the
// absence of the fix; here only the wording is checked.
var ErrClosed = 2 // want `var ErrClosed does not carry namespace "client" anywhere in its name; rename it to ClientErrClosed, or to another name that carries "client"`

func helper() int { return 3 } // want `func helper does not carry namespace "client" anywhere in its name; rename it to clientHelper, or to another name that carries "client"`

var _ = helper
""",
}

SRC_EXPORTEDSCOPE = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
""",
    'api.go': """package exportedscope

// An exported declaration has no boundary by default. Asking instead whether it
// is reachable from outside the package is a question a single-package analysis
// cannot answer — a type escapes through an exported signature, an embedding,
// an alias, or an interface it satisfies — and guessing reported boundaries on
// API that every importer reaches.
type Config struct{ Timeout int }

func Open() *Config { return nil }

// An author may still state the boundary the analysis will not guess. This is a
// statement, not a guess, so it binds and it is enforced.
//
//declscope:private
func Seal() int { return 1 } // want `func Seal is declared private by //declscope:private, but is used from namespace "use"`

// A DTO whose fields are capitalized for a serializer rather than for an
// audience says so on the type, and the directive reaches the fields.
//
//declscope:private
type entry struct { // want `type entry is declared private by //declscope:private, but is used from namespace "use"` `type entry does not carry namespace "api" anywhere in its name; rename it to apiEntry, or to another name that carries "api"`
	Key   string `json:"key"` // want `field entry.Key is declared private by //declscope:private on entry, but is used from namespace "use"`
	Value []byte `json:"value"`
}
""",
    'use.go': """package exportedscope

func useRun(c *Config, e *entry) int {
	c.Timeout = 1
	_ = e.Key
	return Seal()
}

var _ = useRun
""",
}

SRC_UNUSEDSCOPE = {
    '.declscope.yaml': """# Focused on the unused rule: the naming rule would otherwise land on the
# same lines and obscure what this package is for. The surplus rule is off for
# the same reason, since it reports the block directive kept here on purpose.
rules:
  naming:
    qualify: never
  surplus: off
  unused: loose
""",
    'a.go': """package unusedscope

// Nothing beneath an exported func takes a scope, so the directive binds
// nothing and is reported.
//
//declscope:shared // want `unused //declscope:shared on Helper: nothing it reaches takes a scope`
func Helper() int { return 1 }

// An exported type whose every field is exported is the same case.
//
//declscope:shared // want `unused //declscope:shared on Box: nothing it reaches takes a scope`
type Box struct{ Name string }

// But an exported type with an unexported field does have a subject beneath it,
// and the directive lives through it. This is the whole of the carve-out.
//
//declscope:shared
type Entry struct{ key string }

// Restating the scope already in force is NOT reported. The test is quantified
// over configurations rather than read off the current one: defaults.unexported
// may be either scope, so nothing about this could have gone another way only
// because of how the file is set today.
//
//declscope:private
func restates() int { return 2 }

var _ = restates

// A block directive that every spec overrides reaches no declaration, the same
// as one written where nothing checked can carry it — and the report has to
// separate the two, since one line is redundant and the other is misplaced.
//
//declscope:shared // want `unused //declscope:shared: every declaration it reaches states its own scope`
var (
	//declscope:private
	seed = 1
	//declscope:private
	limit = 2
)

// One spec taking the block's scope is enough to keep it: nothing is reported
// here.
//
//declscope:shared
var (
	//declscope:private
	other  = 3
	shared = 4
)

// Written where no checked declaration can carry it.
//
//declscope:shared // want `unused //declscope:shared: no checked declaration carries it`
func init() {}

// The blank function is declared but never checked, like init.
//
//declscope:shared // want `unused //declscope:shared: no checked declaration carries it`
func _() {}

// A blank field declares nothing to check either.
type blankField struct {
	//declscope:shared // want `unused //declscope:shared: no checked declaration carries it`
	_ int
}

var _ = blankField{}

var _ = seed + limit + other + shared
""",
    'b.go': """package unusedscope

func bUse(e *Entry) string { return e.key }

var _ = bUse
""",
    'c.go': """//declscope:shared // want `unused file-level //declscope:shared$`

package unusedscope

// A file-level scope is the default for what the file declares, and every
// declaration here is exported: an exported declaration is shared
// under every configuration, so nothing below takes its scope from the line
// above. The file-level report names no declaration, since the directive was
// written about the file rather than about any one of them.
func Widget() int { return 1 }

type Crate struct{ Name string }
""",
    'd.go': """package unusedscope

// A block's directive that one spec overrides and another spec takes without
// needing it is not overridden by every spec. The report names the spec that
// takes it: Exported is shared under every configuration.
//
//declscope:shared // want `unused //declscope:shared on Exported: nothing it reaches takes a scope`
var (
	Exported = 1
	//declscope:private
	dNarrowed = 2
)

var _ = dNarrowed
""",
    'e.go': """//declscope:private // want `unused file-level //declscope:private$`

package unusedscope

// The same under a file-level directive: eOther restates the file, and
// eWidened overrides the block.
//
//declscope:private // want `unused //declscope:private on eOther: nothing it reaches takes a scope`
var (
	eOther = 1
	//declscope:shared
	eWidened = 2
)

var _ = eOther + eWidened
""",
}

SRC_NSIDENTITY = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
""",
    '2fa.go': """package nsidentity

// The stem 2fa is a namespace like any other, so 2fa_test.go shares it and
// may use totp. It cannot be a prefix, since no identifier starts with a
// digit, so qualify asks nothing of totp even though the package has a second
// namespace; the privacy rules still bound it, so the use from other.go is
// reported here.
func totp() int { return 1 } // want `func totp is private to namespace "2fa", but is used from namespace "other"`

func Verify() int { return totp() }
""",
    '2fa_test.go': """package nsidentity

import "testing"

func TestTOTP(t *testing.T) {
	if totp() != 1 {
		t.Fatal("unexpected")
	}
}
""",
    'other.go': """package nsidentity

// The second namespace, which is what puts qualify in force for the package.
// It is a prefix, so its own declarations are held to it.
func otherRun() int { return 1 }

func helper() int { return 2 } // want `func helper does not carry namespace "other" anywhere in its name; rename it to otherHelper, or to another name that carries "other"`

// A cross-namespace use is still a violation: 2fa is an identity even though
// it is not a prefix.
var _ = totp

var _ = otherRun() + helper()
""",
}

SRC_NSNORMALIZE = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
""",
    'Foo.go': """package nsnormalize

// A PascalCase stem is lowered, so the suggested name stays unexported rather
// than becoming FooBar.
func bar() int { return 1 } // want `func bar does not carry namespace "foo" anywhere in its name; rename it to fooBar, or to another name that carries "foo"`

func fooOK() int { return bar() + fooBarOK() }
""",
    'URLs.go': """package nsnormalize

// A stem that opens with a plural initialism is lowered whole, as Go lowers
// the identifier URLs, so the suggested name is urlsHelper rather than
// urLsHelper.
func helper() int { return 1 } // want `func helper does not carry namespace "urls" anywhere in its name; rename it to urlsHelper, or to another name that carries "urls"`

func urlsOK() int { return helper() }
""",
    'foo-bar.go': """package nsnormalize

// Any separator yields a lowerCamelCase namespace, so the suggested name is
// an identifier rather than foo-barBaz.
func baz() int { return 1 } // want `func baz does not carry namespace "fooBar" anywhere in its name; rename it to fooBarBaz, or to another name that carries "fooBar"`

// Used from Foo.go, which is namespace foo: the two stems are distinct
// identities, and the boundary is reported here at the declaration.
func fooBarOK() int { return baz() } // want `func fooBarOK is private to namespace "fooBar", but is used from namespace "foo"`
""",
}

SRC_NSINITIALISM = {
    '.declscope.yaml': """# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
""",
    'parse_json.go': """package nsinitialism

// The second namespace. An initialism in a later segment is spelled the way
// Go does, so the prefix is parseJSON and parseJsonTree carries it too.
func parseJSONTree() int { return 1 }
func parseJsonTree() int { return 2 }

func tree() int { return 3 } // want `func tree does not carry namespace "parseJSON" anywhere in its name; rename it to parseJSONTree, or to another name that carries "parseJSON"`

func ParseExported() int { return parseJSONTree() + parseJsonTree() + tree() }
""",
    'user_id.go': """package nsinitialism

// The namespace of user_id.go is userID, spelled the way Go spells the
// initialism, and the prefix is matched ignoring case: every spelling below
// carries it.
func userIDCache() int { return 1 }
func userIdCache() int { return 2 }
func userIdcache() int { return 3 }

// The name is the namespace, in another spelling, and qualify accepts it.
var userId = 4

// The suggestion spells the namespace and the first word of the name the way
// Go does: not userIdLookup, and not userIDUrlPath.
func lookup() int { return 5 } // want `func lookup does not carry namespace "userID" anywhere in its name; rename it to userIDLookup, or to another name that carries "userID"`

func urlPath() string { return "" } // want `func urlPath does not carry namespace "userID" anywhere in its name; rename it to userIDURLPath, or to another name that carries "userID"`

// The namespace opens the name and the match may run on into the rest of the
// word, so this carries userID even though userid is one word here.
func useridentity() int { return 6 }

func UserExported() int {
	return userIDCache() + userIdCache() + userIdcache() + userId + lookup() + len(urlPath()) + useridentity()
}
""",
    'user_ids.go': """package nsinitialism

// The namespace of user_ids.go is userIDs, spelled the way Go spells a plural
// initialism, not userIds.
func load() int { return 1 } // want `func load does not carry namespace "userIDs" anywhere in its name; rename it to userIDsLoad, or to another name that carries "userIDs"`
""",
}

SRC_NSTESTSUFFIX = {
    'foo.go': """package nstestsuffix

// foo_test_linux.go is an ordinary linux file, not a test of this one: only a
// name ending in _test.go is a test file. It is namespace fooTest, so its use
// is a crossing.
func fooHelper() int { return 1 } // want `func fooHelper is private to namespace "foo", but is used from namespace "fooTest"`

func fooOK() int { return fooHelper() }
""",
    'foo_test_linux.go': """package nstestsuffix

func fooTestRun() int { return fooHelper() }
""",
}

SRC_BLOCKIGNORE = {
    '.declscope.yaml': """# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
""",
    'order.go': """package blockignore

func orderRun(u *User) int {
	return userA + userC + userG + u.x
}

var _ = orderRun
""",
    'user.go': """package blockignore

// A directive on a block is one comment, however many specs it reaches. It
// is used by userA's crossing and not needed by userB, and that is enough:
// it silenced something, so it is not unused.
//
//declscope:ignore boundary
var (
	userA = 1
	userB = 2
)

// One directive shared by both names on a line, needed by userC alone.
var userC, userD = 3, 4 //declscope:ignore boundary

// A block directive that silenced nothing is reported once, at the comment,
// naming every declaration it reached — not once per spec.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary on userE, userF`
var (
	userE = 5
	userF = 6
)

type User struct {
	// Shared by both fields, needed by x alone.
	x, y int //declscope:ignore boundary
	// Silenced nothing for either: the naming rule never reaches a member.
	p, q int //declscope:ignore qualify // want `unused //declscope:ignore qualify on User.p, User.q`
}

// A spec's own ignore is judged as its own comment, apart from the block's:
// the block's is used by userG, the spec's qualify — needless on a name that
// carries its namespace — is not.
//
//declscope:ignore boundary
var (
	userG = 7
	//declscope:ignore qualify // want `unused //declscope:ignore qualify on userH`
	userH = 8
)

// Written where nothing checked can carry it. The report has no declaration to
// name, so it says that rather than printing an empty list.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary: no checked declaration carries it`
func init() {}
""",
}

SRC_TESTONLYIGNORE = {
    'order_test.go': """package testonlyignore

import "testing"

func TestHelper(t *testing.T) {
	if userHelper() != 1 {
		t.Fatal("unexpected")
	}
}

// The test variant sees every file in the package, so it does judge, and a
// directive written in a test file is checked by that variant alone.
//
//declscope:ignore boundary // want `unused //declscope:ignore boundary on orderUnused`
func orderUnused() int { return 3 }

var _ = orderUnused
""",
    'user.go': """package testonlyignore

// userHelper is used from order_test.go, in namespace "order", and from
// nowhere else. Only the test variant of the package sees that reference, so
// only it can tell whether the directive did anything; the ordinary variant,
// which cannot see order_test.go, must not call it unused. Neither variant
// reports it: the test variant because it was used, the ordinary one because
// it defers to the test variant.
//
//declscope:ignore boundary
func userHelper() int { return 1 }
""",
}

SRC_BRACEIGNORE = {
    'order.go': """package braceignore

func orderRun(t *UserT, v *UserV, w *UserW, m *UserM) int {
	return t.x + v.z + w.w + w.v + m.m + userA + userB + userC + userHelper() + userLoose()
}

var _ = orderRun
""",
    'user.go': """package braceignore

// A directive after the opening brace binds to the type, the way one after a
// function's opening brace binds to the function, and covers the fields like
// any directive on the type.
type UserT struct { //declscope:ignore boundary
	x int
}

// It is parsed there too, so a bogus one is reported rather than dropped.
type UserV struct { //declscope:bogus // want `unknown directive declscope:bogus`
	z int // want `field UserV.z is private to namespace "user", but is used from namespace "order"`
}

// A comment the parser hung on a field is the field's even on the brace
// line: only w is covered. This is the one shape here gofmt would rewrite —
// it moves w to its own line — and it is kept as written because that is
// the shape the rule is about.
type UserW struct { w int //declscope:ignore boundary
	v int // want `field UserW.v is private to namespace "user", but is used from namespace "order"`
}

// After "(" a directive reaches every spec of the block...
var ( //declscope:ignore boundary
	userA = 1
	userB = 2
)

// ...and after ")" as well.
const (
	userC = 3
) //declscope:ignore boundary

// A function's closing brace is its last line.
func userHelper() int {
	return 4
} //declscope:ignore boundary

// A directive that binds nowhere is reported as misplaced instead of being
// dropped: one separated from its declaration by a blank line...
//
//declscope:ignore boundary // want `misplaced declscope:ignore: no declaration here for it to bind to`

func userLoose() int { return 5 } // want `func userLoose is private to namespace "user", but is used from namespace "order"`

// ...one inside a function body...
func userBody() int {
	//declscope:shared // want `misplaced declscope:shared: no declaration here for it to bind to`
	return 6
}

var _ = userBody

// ...and one on a line in the middle of a declaration.
type UserM struct {
	//declscope:ignore boundary // want `misplaced declscope:ignore: no declaration here for it to bind to`

	m int // want `field UserM.m is private to namespace "user", but is used from namespace "order"`
}

// A namespace directive is answered with where it belongs rather than with the
// generic misplacement: there is no declaration it could ever bind to, since a
// namespace is a property of the file.
func userNamed() int {
	//declscope:namespace other // want `declscope:namespace must appear before the package clause`
	return 7
}

var _ = userNamed

// So is core, also a property of the file. A directive no declaration would
// accept either is reported as it is on a declaration: an unknown keyword is
// unknown wherever it is written.
func userCored() int {
	//declscope:core // want `declscope:core must appear before the package clause`
	//declscope:bogus // want `unknown directive declscope:bogus`
	return 8
}

var _ = userCored
""",
}

SRC_LINEAFTERCOMMENT = {
    'order.go': """package lineaftercomment

func orderRun(t UserT[int]) int {
	return userHelper(1) + userOne() + t.x + userA
}

var _ = orderRun
""",
    'user.go': """package lineaftercomment

// A directive trailing a declaration's first or last line binds even when an
// earlier comment shares that line. The earlier comment is not a directive,
// so it is not reported either.

func userHelper(a int /* units */) int { //declscope:shared
	return a
}

func userOne() int { return 1 /* one */ } //declscope:ignore boundary

type UserT[E any /* elem */] struct { //declscope:ignore boundary
	x E
}

var /* group */ ( //declscope:ignore boundary
	userA = 1
)
""",
}

SRC_ALIASES = {
    '.declscope.yaml': """rules:
  naming:
    qualify: never
  unused: loose
""",
    'alias.go': """package aliases

// A scope directive on an alias binds the alias name, which is an ordinary
// declaration bounded by this file. It does not reach Base's members.
//
//declscope:shared
type al = Base
""",
    'base.go': """package aliases

// Base is exported, so alias.go naming it crosses nothing. Its unexported
// field is still bounded by this file, and no directive written on an alias
// reaches it.
type Base struct {
	n int // want `field Base.n is private to namespace "base", but is used from namespace "use"`
}
""",
    'inline.go': """package aliases

// An alias whose right-hand side is written inline does contain its fields,
// for the same reason any other declaration does.
//
//declscope:private
type entry = struct { // want `type entry is declared private by //declscope:private, but is used from namespace "use"`
	key string // want `field entry.key is declared private by //declscope:private on entry, but is used from namespace "use"`
}
""",
    'use.go': """package aliases

// al is reachable: the directive in alias.go widened it. base.n is not: the
// alias never reached it. entry is not: inline.go narrowed it.
func useIt(x al, e entry) int { return x.n + len(e.key) }

var _ = useIt
""",
}

SRC_IFACEMEMBERS = {
    '.declscope.yaml': """# The naming rules do not reach members, so they would only add noise here.
rules:
  naming:
    qualify: never
""",
    'impl.go': """package ifacemembers

// Satisfying an interface is not a use of its method names. A method set is
// resolved, not written, so this file crosses nothing — and if it did, the
// idiom would be a violation in every codebase that uses it, repairable only
// by a directive that changes nothing about Go semantics.
type conc struct{}

func (conc) sealed() bool { return true }
func (conc) Open() int    { return 1 }

var _ Sealed = conc{}
""",
    'order.go': """package ifacemembers

func orderRun(s Sealed, w Widened, m Mixed, q Quiet, st Store[int]) int {
	if s.sealed() {
		return w.shared() + m.ok() + m.nope() + q.hushed() + st.fetch(1) + s.Open()
	}
	return 0
}

var _ = orderRun
""",
    'user.go': """package ifacemembers

// An interface declares its method names, and only this package can spell an
// unexported one. That is the sealed-interface idiom, and the boundary gives
// it file granularity.
type Sealed interface {
	sealed() bool // want `method Sealed.sealed is private to namespace "user", but is used from namespace "order"`
	// Exported: published to every importer, so no boundary by default.
	Open() int
}

// The type's directive reaches its methods, the way it reaches a struct's
// fields: both are written inside the declaration.
//
//declscope:shared
type Widened interface {
	shared() int
}

// A method may state its own scope, which outranks the type's.
type Mixed interface {
	//declscope:shared
	ok() int
	nope() int // want `method Mixed.nope is private to namespace "user", but is used from namespace "order"`
}

// The type's ignore covers its methods too.
//
//declscope:ignore boundary
type Quiet interface {
	hushed() int
}

// Generic interfaces are no different.
type Store[T any] interface {
	fetch(id int) T // want `method Store.fetch is private to namespace "user", but is used from namespace "order"`
}

// Nothing here declares a name of its own: an embedded interface takes the
// embedded type's names, and a type-constraint element has none at all.
type Combined interface {
	Sealed
	Store[int]
}

type Number interface{ ~int | ~float64 }
""",
}

SRC_MAINPKG = {
    '.declscope.yaml': """# always, so that the func main exemption is exercised rather than assumed.
rules:
  naming:
    qualify: always
""",
    'handler.go': """package main

func handlerDo() { // want `func handlerDo is private to namespace "handler", but is used from namespace "main"`
	c := ServerNew()
	c.Addr = ":80"
	_ = c
}
""",
    'main.go': """//declscope:private

package main

// Exportedness keeps its meaning here, so Config and ServerNew are held back
// only because this file says so: a file-level directive reaches exported
// declarations too.
type Config struct {
	Addr string // want `field Config.Addr is declared private by the file's //declscope:private, but is used from namespace "handler"`
}

func ServerNew() *Config { return &Config{} } // want `func ServerNew is declared private by the file's //declscope:private, but is used from namespace "handler"`

// func main is the one name the toolchain requires, so the naming rules pass
// it by however they are set.
func main() { handlerDo() }
""",
}

SRC_TOOLCHAINNAMES = {
    '.declscope.yaml': """# Strictest, so the exemption is exercised rather than assumed: without it the
# toolchain names would every one be asked for a prefix.
rules:
  naming:
    qualify: always
    exported: true
""",
    'user.go': """package toolchainnames

// TestHelper is not in a _test.go file, so the toolchain never finds it by
// name and the prefix is asked for like any other.
func TestHelper() int { return 1 } // want `func TestHelper does not carry namespace "user" anywhere in its name; rename it to UserTestHelper, or to another name that carries "user"`

func userLoad() int { return 2 }
""",
    'user_test.go': """package toolchainnames

import "testing"

// The toolchain finds each of these by name. Prefixing one leaves a function
// nothing runs, so none is asked for a prefix.
func TestLoad(t *testing.T)      { _ = userLoad() }
func BenchmarkLoad(b *testing.B) { _ = userLoad() }
func FuzzLoad(f *testing.F)      { _ = userLoad() }
func ExampleTestHelper()         { _ = TestHelper() }
""",
}

SRC_SURPLUS = {
    'order.go': """// The file's directive widens everything the file declares, and is judged as
// the one comment it is.
//
//declscope:shared // want `the file's //declscope:shared: no use from another namespace is visible to declscope`

package surplus

func orderQuiet() int { return 5 }

var _ = orderQuiet
""",
    'user.go': """package surplus

// Reported: no other namespace is seen to use it, and a use from the same
// namespace keeps nothing.
//
//declscope:shared // want `//declscope:shared on userSeed: no use from another namespace is visible to declscope`
var userSeed = 1

var _ = userSeed

// One comment reaches every spec and is judged once, so one report lists both.
//
//declscope:shared // want `//declscope:shared on userLimit, userCap: no use from another namespace is visible to declscope`
var (
	userLimit = 2
	userCap   = 3
)

// A type's directive also reaches its fields, and the report lists them.
//
//declscope:shared // want `//declscope:shared on userBox, userBox.item: no use from another namespace is visible to declscope`
type userBox struct{ item int }

//declscope:shared // want `//declscope:shared on userBox.zero: no use from another namespace is visible to declscope`
func (userBox) zero() int { return 0 }

// An ignore silences the rule like any other.
//
//declscope:shared
//declscope:ignore surplus
var userQuiet = 4

// Key is exported, so importers reach it without this analysis seeing them.
// The whole comment stays quiet rather than advise against that doubt.
//
//declscope:shared
type userEntry struct{ Key string }
""",
}

SRC_SURPLUSUSED = {
    '.declscope.yaml': """rules:
  surplus: loose
""",
    'order.go': """package surplusused

func orderRun() int {
	return userShared() + userMakePair().second
}

var (
	_ = orderRun
	_ = userMake
	_ = UserRec{7}
	_ = append(userSlots(), []userSlotPtr{{1}}...)
)
""",
    'user.go': """package surplusused

// Spelled from order.go, so the directive is doing its job.
//
//declscope:shared
func userShared() int { return 1 }

// One field's use keeps the whole comment: deleting it would narrow second
// back, which order.go still reaches.
//
//declscope:shared
type userPair struct {
	first  int
	second int
}

//declscope:shared
func userMakePair() userPair { return userPair{} }

// The field narrows itself back, so it does not depend on the type's
// directive, and the type's comment is judged on the type alone.
//
//declscope:shared // want `//declscope:shared on userSolo: no use from another namespace is visible to declscope`
type userSolo struct {
	//declscope:private
	name string
}

//declscope:shared
func userMake() userSolo { return userSolo{name: "n"} }

// UserRec is exported, so spelling it from order.go keeps nothing here alive.
// The field's directive is kept only by the composite literal without keys,
// which writes the field without spelling it and still counts as the use it
// is.
type UserRec struct {
	//declscope:shared
	n int
}

// userSlotPtr is a defined pointer type. A literal leaving it out in
// order.go writes the field of userSlot, which keeps its directive.
//
//declscope:shared
type userSlotPtr *userSlot

type userSlot struct {
	//declscope:shared
	count int
}

//declscope:shared
func userSlots() []userSlotPtr { return nil }
""",
}

SRC_SURPLUSSATISFIES = {
    'box.go': """package surplussatisfies

// The type's directive reaches v too; both are spelled from use.go, which is
// what keeps this comment. Only get is reached through the contract alone.
//
//declscope:shared
type box[T any] struct{ v T }

//declscope:shared
func (b box[T]) get() T { return b.v }
""",
    'closer.go': """package surplussatisfies

//declscope:shared
type closer struct{}

//declscope:shared
func (closer) close() string { return "c" }
""",
    'inner.go': """package surplussatisfies

//declscope:shared
type inner struct{}

//declscope:shared
func (*inner) run() {}
""",
    'myint.go': """package surplussatisfies

//declscope:shared
type myInt int

//declscope:shared
func (myInt) str() string { return "n" }
""",
    'reader.go': """package surplussatisfies

// The type is spelled from use.go, which keeps its own directive alive. The
// methods are reached only through interface contracts.
//
//declscope:shared
type reader struct{}

//declscope:shared
func (reader) read() string { return "r" }

// stray participates in no contract, so its directive is reported.
//
//declscope:shared // want `//declscope:shared on reader.stray: no use from another namespace is visible to declscope`
func (reader) stray() string { return "s" }
""",
    'use.go': """package surplussatisfies

type readCloser interface {
	read() string
	close() string
}

type intGetter interface{ get() int }

type runner interface{ run() }

// An anonymous struct satisfies through embedded methods, spelling none of
// them.
func useBoth() string {
	var rc readCloser = struct {
		reader
		closer
	}{}
	return rc.read() + rc.close()
}

// A type declared inside a function does the same, and appears in no package
// scope.
func useLocal() string {
	type both struct {
		reader
		closer
	}
	var rc readCloser = both{}
	return rc.read() + rc.close()
}

// An instantiated generic type satisfies with an instantiated method, which is
// a different object from the one the source declares.
func useGet() int {
	var g intGetter = box[int]{v: 42}
	return g.get()
}

// A promoted instantiation satisfies through the embedding.
type outer struct{ box[int] }

var _ intGetter = outer{}

// A pointer-receiver method promotes only through the address.
type holder struct{ inner }

var _ runner = &holder{}

// An anonymous interface in a type assertion is a contract too.
func useRun(v any) {
	if r, ok := v.(interface{ run() }); ok {
		r.run()
	}
}

// A constraint carrying a type term is an interface contract as well.
func useFormat[T interface {
	~int
	str() string
}](t T) string {
	return t.str()
}

var (
	_ = useBoth
	_ = useLocal
	_ = useGet
	_ = useRun
	_ = useFormat[myInt]
)
""",
}

SRC_SURPLUSSATISFIESPAIRS = {
    'brake.go': """package surplussatisfiespairs

//declscope:shared
type brake struct{}

//declscope:shared
func (brake) stop() {}
""",
    'cell.go': """package surplussatisfiespairs

//declscope:shared
type cell[T any] struct{}

//declscope:shared
func (cell[T]) peek() (v T) { return v }

//declscope:shared
func (*cell[T]) poke(T) {}
""",
    'clock.go': """package surplussatisfiespairs

//declscope:shared
type clock struct{}

//declscope:shared
func (clock) tick() {}

//declscope:shared
func (clock) tock() {}
""",
    'engine.go': """package surplussatisfiespairs

// engine is embedded by pointer in use.go, which spells it and keeps its
// directive. spin is promoted from there into a contract.
//
//declscope:shared
type engine struct{}

//declscope:shared
func (*engine) spin() {}

// idle is in no contract, so its directive is reported. It shows the rule is
// on in this package, and that the pairs kept are no wider than they need be.
//
//declscope:shared // want `//declscope:shared on engine.idle: no use from another namespace is visible to declscope`
func (*engine) idle() {}
""",
    'handler.go': """package surplussatisfiespairs

// A named function type has methods although its underlying type cannot.
//
//declscope:shared
type handlerFunc func() string

//declscope:shared
func (f handlerFunc) serve() string { return f() }
""",
    'ticket.go': """package surplussatisfiespairs

//declscope:shared
type ticket struct{}

//declscope:shared
func (ticket) fetch() int { return 1 }
""",
    'use.go': """package surplussatisfiespairs

// Each contract below is the only way its methods are reached. The rule may
// skip an interface or a type before testing satisfaction, and these are the
// shapes such a skip could get wrong.

// A method promoted through an embedded pointer. Only wrap has both methods:
// spin comes from *engine and stop from brake, so neither type satisfies
// the interface alone.
type spinStopper interface {
	spin()
	stop()
}

type wrap struct {
	*engine
	brake
}

var _ spinStopper = wrap{}

// A method of a generic type, satisfied by an instantiation alone. poke has
// a pointer receiver, so only the instantiation's address satisfies.
type peekPoker interface {
	peek() string
	poke(string)
}

var _ peekPoker = &cell[string]{}

// An interface embedding another. tock is asked for by tickTocker alone, and
// tick by both.
type ticker interface{ tick() }

type tickTocker interface {
	ticker
	tock()
}

var _ tickTocker = clock{}

// A requirement that only an embedded interface asks for. fetcherOf declares
// no method of its own, and the instantiation that asks fetch() int is never
// written: it exists only inside fetcherOf[int]. No other interface of the
// package asks for fetch with that signature.
type getterOf[T any] interface{ fetch() T }

type fetcherOf[T any] interface{ getterOf[T] }

var _ fetcherOf[int] = ticket{}

// A named type whose underlying type has no methods. Only the named type
// satisfies, and its address is never written.
type server interface{ serve() string }

var _ server = handlerFunc(nil)

// A requirement named like a function. Nothing satisfies it, and no method of
// the package is called shut, so the pair it could form marks nothing.
type shutter interface{ shut() }

var _ shutter = nil
""",
    'valve.go': """package surplussatisfiespairs

// shut is a function, and shutter in use.go asks for a method of that name.
// A contract reaches methods alone, so no contract reaches the function, and
// its directive is reported.
//
//declscope:shared // want `//declscope:shared on shut: no use from another namespace is visible to declscope`
func shut() {}

var _ = shut
""",
}

SRC_SURPLUSCARRIER = {
    'alias.go': """package surpluscarrier

type impl struct{}

//declscope:shared
func (impl) fire() {}

// Public is an exported alias: the method set travels under its name.
type Public = impl
""",
    'base.go': """package surpluscarrier

// Base is exported: an importer can embed it, inherit run, and complete an
// interface satisfaction this analysis never sees.
type Base struct{}

//declscope:shared
func (Base) run() {}
""",
    'sealed.go': """package surpluscarrier

// Sealed is the sealed-interface idiom: the requirement travels with the
// exported interface, and an importer that embeds it passes it on.
type Sealed interface {
	Do()
	//declscope:shared
	seal()
}
""",
    'solo.go': """package surpluscarrier

// solo is unexported, so nothing carries quiet out, and the directive is
// reported.
type solo struct{}

//declscope:shared // want `//declscope:shared on solo.quiet: no use from another namespace is visible to declscope`
func (solo) quiet() {}
""",
    'wrap.go': """package surpluscarrier

type hidden struct{}

//declscope:shared
func (hidden) tick() {}

// Wrapper carries tick out of the package through the embedding.
type Wrapper struct{ hidden }
""",
}

SRC_SURPLUSLINKNAME = {
    'user.go': """package surpluslinkname

import _ "unsafe"

// userClock is reached through the linkname as text, never through a spelled
// reference.
//
//go:linkname userClock
//declscope:shared
func userClock() int64 { return 0 }

// userTick is named by an //export directive the same way.
//
//export userTick
//declscope:shared
func userTick() int32 { return 1 }

// userQuiet is named by neither, so its directive is reported.
//
//declscope:shared // want `//declscope:shared on userQuiet: no use from another namespace is visible to declscope`
func userQuiet() int { return 2 }
""",
}

SRC_SURPLUSOPAQUE = {
    'gen.go': """// Code generated by a tool. DO NOT EDIT.

package surplusopaque

func genUse() int { return userMagic() }

var _ = genUse
""",
    'user.go': """package surplusopaque

// The only use is in gen.go, which the analysis excludes as a reference site.
// The package holds a source the rule cannot read, so the rule switches off
// rather than read the absence as evidence.
//
//declscope:shared
func userMagic() int { return 7 }
""",
}

SRC_SURPLUSGENERATOR = {
    'gen.go': """//go:build ignore

package main

func userHelper() int { return 2 }

func main() { _ = userHelper() }
""",
    'user.go': """package surplusgenerator

// gen.go is a generator of another package, which the build excludes. It
// declares a userHelper of its own, not this one, so the directive is still
// reported.
//
//declscope:shared // want `//declscope:shared on userHelper: no use from another namespace is visible to declscope`
func userHelper() int { return 1 }
""",
}

SRC_SURPLUSEXCLUDED = {
    'order_tagged.go': """//go:build never

package surplusexcluded

var _ = userHelper()
""",
    'user.go': """package surplusexcluded

// The only use is in order_tagged.go, which the build excludes. That file is
// of this package, so the rule switches off rather than read the absence as
// evidence. The silence is the assertion.
//
//declscope:shared
func userHelper() int { return 1 }
""",
}

SRC_SURPLUSTESTS = {
    'other_test.go': """package surplustests

import "testing"

func TestOther(t *testing.T) {
	if userHelp() != 1 {
		t.Fatal("no")
	}
}
""",
    'user.go': """package surplustests

// The only use is in other_test.go. The test variant sees it and stays quiet;
// the ordinary variant does not see every file, so the rule switches off there
// instead of reporting.
//
//declscope:shared
func userHelp() int { return 1 }
""",
}

SRC_SURPLUSCONVERT = {
    'model.go': """package surplusconvert

type model struct {
	ID int
	//declscope:shared
	rev int
}

//declscope:shared
func modelNew() model { return model{ID: 1, rev: 2} }

// genModel is generic. A conversion from its instantiation pairs the
// instantiated fields, which are mapped back to the ones declared here.
type genModel[T any] struct {
	ID int
	//declscope:shared
	rev T
}

//declscope:shared
func genModelNew() genModel[int] { return genModel[int]{ID: 1, rev: 2} }

// Ledger is converted to its own type from snapshot.go. That conversion is the
// identity: it pairs no field with another type's, so it keeps nothing wide.
type Ledger struct {
	//declscope:shared // want `//declscope:shared on Ledger.seq: no use from another namespace is visible to declscope`
	seq int
}

var _ = Ledger{seq: 1}

// ParamModel is exported only so snapshot.go may spell it. Its field takes
// private scope, which its own directive widens.
type ParamModel struct {
	ID int
	//declscope:shared
	rev int
}

var _ = ParamModel{ID: 1, rev: 2}
""",
    'snapshot.go': """package surplusconvert

// snapshot mirrors model for persistence. The conversion pairs every field by
// name and spells none of them, so rev's directive is load-bearing without a
// visible reference — the rule must stay quiet.
type snapshot struct {
	ID  int
	rev int
}

func snapshotOf() snapshot { return snapshot(modelNew()) }

var _ = snapshotOf

type genSnapshot struct {
	ID  int
	rev int
}

func snapshotOfGen() genSnapshot { return genSnapshot(genModelNew()) }

var _ = snapshotOfGen

func snapshotLedger(l Ledger) Ledger { return Ledger(l) }

var _ = snapshotLedger

// A conversion to a type parameter allowing only *ParamModel pairs its fields
// with paramRow's, as (*ParamModel)(r) does. The source side alone was read
// before, which is why the directive in model.go sits on the target side.
type paramRow struct {
	ID  int
	rev int
}

func snapshotOfParam[P ~*ParamModel](r *paramRow) P { return P(r) }

var _ = snapshotOfParam[*ParamModel]
""",
}

SRC_TYPEPARAMSETS = {
    'build.go': """package typeparamsets

func buildNamed[P interface{ Named }]() []P { return []P{P{1}, {2}} }

func buildNarrow[P interface {
	~*Narrow | ~*Wide
	~*Narrow
}]() []P {
	return []P{{1}}
}

func buildVia[P interface{ PtrTo[Via] | *Via }]() []P { return []P{{1}} }

func buildTwins[P interface{ Left | Right }]() P { return P{1} }

type buildMirror struct{ count int }

func buildConverted[P interface{ Converted }](u buildMirror) P { return P(u) }

var (
	_ = buildNamed[Named]
	_ = buildNarrow[*Narrow]
	_ = buildVia[*Via]
	_ = buildTwins[Left]
	_ = buildConverted[Converted]
)
""",
    'entry.go': """package typeparamsets

// Each type below is written by build.go in one shape only, through a type
// parameter, and the literal or conversion spells none of its fields.

// Named is the constraint itself: P interface{ Named }. Its type set holds one
// struct, so P{1} and []P{{1}} write count.
type Named struct {
	count int // want `field Named.count is private to namespace "entry", but is used from namespace "build"`
}

// Narrow and Wide are both in a union, which a second element intersects
// with ~*Narrow alone. Only Narrow is left, so []P{{1}} writes Narrow.count.
type Narrow struct {
	count int // want `field Narrow.count is private to namespace "entry", but is used from namespace "build"`
}

type Wide struct {
	count int
}

// Via is reached through an interface term of a union, PtrTo[Via] | *Via.
type Via struct {
	count int // want `field Via.count is private to namespace "entry", but is used from namespace "build"`
}

type PtrTo[T any] interface{ *T }

// Left and Right have one underlying type, so P interface{ Left | Right }
// has it as its core type, and P{1} writes the fields of both.
type Left struct {
	count int // want `field Left.count is private to namespace "entry", but is used from namespace "build"`
}

type Right struct {
	count int // want `field Right.count is private to namespace "entry", but is used from namespace "build"`
}

// Converted is the constraint of P, and P(u) pairs its field with u's by name.
// The pairing is what the directive holds up, so it is not surplus.
type Converted struct {
	//declscope:shared
	count int
}

var _ = Wide{count: 1}

var _ = Converted{count: 1}
""",
}

SRC_SURPLUSDEFAULT = {
    'user.go': """package surplusdefault

// The rule is on with no configuration.
//
//declscope:shared // want `//declscope:shared on userQuiet: no use from another namespace is visible to declscope`
func userQuiet() int { return 1 }
""",
}

SRC_SURPLUSDEFAULTSTRICT = {
    'order.go': """package surplusdefaultstrict

var _ = userShared()
""",
    'user.go': """//declscope:shared

package surplusdefaultstrict

func userShared() int { return 1 }

func userLocal() int { return 2 } // want `func userLocal takes shared scope from the file's //declscope:shared, but no use from another namespace is visible to declscope`
""",
}

SRC_SURPLUSBASELINED = {
    '.declscope-baseline.yaml': """packages:
  surplusbaselined:
    surplus:
      user:
        - userOld
""",
    'user.go': """package surplusbaselined

// userOld is recorded in the baseline, so it stays quiet.
//
//declscope:shared
func userOld() int { return 1 }

// userNew is not, so it is reported.
//
//declscope:shared // want `//declscope:shared on userNew: no use from another namespace is visible to declscope`
func userNew() int { return 2 }
""",
}

SRC_SURPLUSSTRICT = {
    '.declscope.yaml': """# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
""",
    'file.go': """// A file-level directive widens every field the file declares, and the report
// names it.
//
//declscope:shared

package surplusstrict

type fileCursor struct {
	pos  int
	seen int // want `field fileCursor.seen takes shared scope from the file's //declscope:shared, but no use from another namespace is visible to declscope`
}

func fileAdvance(c *fileCursor) { c.seen++ }
""",
    'helper.go': """// The file's directive widens everything it declares. helperShared is called
// from order.go, so the directive is in use and loose says nothing. strict
// judges each declaration under it on its own.
//
//declscope:shared

package surplusstrict

func helperShared() int { return helperLocal() }

// Called only here.
func helperLocal() int { return 1 } // want `func helperLocal takes shared scope from the file's //declscope:shared, but no use from another namespace is visible to declscope`

// One spec holding two names takes one directive, so both are reported.
var helperA, helperB = 1, 2 // want `var helperA takes shared scope` `var helperB takes shared scope`

// helperC is read from order.go, and a directive above the spec would narrow
// it too, so neither name is reported.
var helperC, helperD = 3, 4

// Nothing outside spells helperBox or reads n. Narrowing the type narrows n
// with it, so the type is reported and n is not reported again.
type helperBox struct { // want `type helperBox takes shared scope from the file's //declscope:shared`
	n int
}

// A method is its own declaration, and narrowing the type does not reach it.
func (b helperBox) helperSize() int { return b.n } // want `method helperBox.helperSize takes shared scope`

// order.go reads x through helperMakePair without spelling the type, so
// narrowing the type would narrow x and start a boundary report. The type
// stays, and y, which nothing outside reads, is reported on its own.
type helperPair struct {
	x int
	y int // want `field helperPair.y takes shared scope from the file's //declscope:shared`
}

func helperMakePair() helperPair { return helperPair{} }

var _ = helperLocal() + helperA + helperB + helperD + helperBox{}.helperSize() + helperMakePair().y
""",
    'order.go': """package surplusstrict

func orderRun(a userAccount, p userPair, m userMixed, n userNeedless, q userQuiet, h userHushed) int {
	var s userSaver
	_ = s
	return a.id + len(a.Name) + p.shared + m.top + n.read + len([]any{q, h})
}

var _ = orderRun

func orderHelpers() int { return helperShared() + helperC + helperMakePair().x + blockUsed }

var _ = orderHelpers
""",
    'reader.go': """package surplusstrict

func readerUse(c *fileCursor) int {
	fileAdvance(c)
	return c.pos
}

var _ = readerUse
""",
    'user.go': """package surplusstrict

// userAccount is shared: order.go spells it and reads id. balance is read
// only here, so the type's directive widens it for nothing.
//
//declscope:shared
type userAccount struct {
	id      int
	balance int // want `field userAccount.balance takes shared scope from //declscope:shared on userAccount, but no use from another namespace is visible to declscope`

	// Name is exported, so it is shared whatever the type says.
	Name string

	// owner states its own scope, so the type's directive does not reach it.
	//
	//declscope:private
	owner string

	// An embedded field has no name of its own, and is never a target.
	*userLedger
}

type userLedger struct{ entries int }

// One entry holds two names, and one directive above it would bind both. Both
// are read only here, so both are reported, and one fix narrows the two.
//
//declscope:shared
type userPair struct {
	left, right int // want `field userPair.left takes shared scope` `field userPair.right takes shared scope`
	shared      int
}

// top is read from order.go and bottom is not. Only a directive above the
// whole entry could narrow bottom, and it would narrow top as well, so the
// entry is not reported.
//
//declscope:shared
type userMixed struct {
	top, bottom int
}

// The type's directive is surplus: nothing about userIdle crosses. surplus
// reports the directive, and the fields are not reported again under it.
//
//declscope:shared // want `//declscope:shared on userIdle, userIdle.count: no use from another namespace is visible to declscope`
type userIdle struct {
	count int
}

// An ignore silences the rule on a field, and on every field of a type.
//
//declscope:shared
type userQuiet struct {
	//declscope:ignore surplus
	hush int
	kept int // want `field userQuiet.kept takes shared scope`
}

//declscope:shared
//declscope:ignore surplus
type userHushed struct {
	a int
	b int
}

// An ignore for this rule on a field that it would not report is unused.
//
//declscope:shared
type userNeedless struct {
	//declscope:ignore surplus // want `unused //declscope:ignore surplus on userNeedless.read`
	read int
}

// An interface's method names are members too, and are judged like fields.
// Satisfying the interface is not a use of the name, so an implementation in
// another namespace would not keep save wide; a call from there would.
//
//declscope:shared
type userSaver interface {
	save() int // want `method userSaver.save takes shared scope from //declscope:shared on userSaver`
}

func userLocal() int {
	a := userAccount{balance: 1, owner: "o"}
	p := userPair{left: 1, right: 2}
	q := userQuiet{hush: 1, kept: 2}
	h := userHushed{a: 1, b: 2}
	var s userSaver
	_ = s
	return a.balance + p.left + p.right + q.hush + q.kept + h.a + h.b + userIdle{}.count + len(a.owner)
}

var _ = userLocal

// A directive on a block reaches every spec, and strict judges each one.
//
//declscope:shared
var (
	blockUsed  = 1
	blockLocal = 2 // want `var blockLocal takes shared scope from the //declscope:shared on its block, but no use from another namespace is visible to declscope`
)

var _ = blockLocal
""",
}

SRC_SURPLUSSTRICTREACH = {
    '.declscope.yaml': """# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
""",
    'order.go': """package surplusstrictreach

type orderOuter struct{ userInner }

type orderSnap struct{ rev int }

type orderGenSnap struct{ gen int }

type orderPtrSnap struct{ rev int }

func (b *userBox) orderBump() { b.v++ }

func orderRun() int {
	r := userRec{1, 2}
	o := orderOuter{}
	l := userList[int]{}
	s := orderSnap(userModel{})
	p := userPair[string]{1, "x"}
	g := orderGenSnap(userGenModel[int]{})
	pr := []*userPtrRec{{1}}
	ps := (*orderPtrSnap)(&userPtrModel{})
	var b userBox
	b.orderBump()
	return len([]any{r, p}) + o.n + len(l.items) + s.rev + g.gen + len(pr) + ps.rev
}

var _ = orderRun
""",
    'user.go': """package surplusstrictreach

// Every field below is reached from order.go by a path that spells nothing
// or spells it through something else. Each one keeps the type's scope.

// A composite literal without keys writes both fields by position.
//
//declscope:shared
type userRec struct {
	a int
	b int
}

// A selection through an embedding names the field of the embedded type.
//
//declscope:shared
type userInner struct {
	n int
}

// A selection on an instantiation names the instantiated field, which is
// mapped back to the declared one.
//
//declscope:shared
type userList[T any] struct {
	items []T
}

// The same for an instantiation of a generic struct, whose fields are mapped
// back to the declared ones.
//
//declscope:shared
type userPair[T any] struct {
	k int
	v T
}

// A struct conversion pairs every field by name and spells none of them.
//
//declscope:shared
type userModel struct {
	rev int
}

// The same for a conversion from an instantiation of a generic struct.
//
//declscope:shared
type userGenModel[T any] struct {
	gen T
}

// A literal inside another may leave out its pointer type: in
// []*userPtrRec{{1}} it writes the fields of the struct the pointer points to.
//
//declscope:shared
type userPtrRec struct {
	a int
}

// A conversion between pointers to struct types pairs the fields as well.
//
//declscope:shared
type userPtrModel struct {
	rev int
}

// A method written in order.go reads the field from there.
//
//declscope:shared
type userBox struct {
	v int
	// stray is read by nothing outside, which shows the guards above are
	// precise rather than off.
	stray int // want `field userBox.stray takes shared scope from //declscope:shared on userBox, but no use from another namespace is visible to declscope`
}

func userTouch(b userBox) int { return b.stray }

var _ = userTouch
""",
}

SRC_SURPLUSSTRICTDEFAULTS = {
    '.declscope.yaml': """# strict, but under defaults.unexported: shared the directive widens nothing.
defaults:
  unexported: shared
rules:
  surplus: strict
  unused: loose
""",
    'order.go': """package surplusstrictdefaults

func orderRun(c userCard) int { return c.id }

var _ = orderRun
""",
    'user.go': """package surplusstrictdefaults

// Under defaults.unexported: shared the field would be shared with
// no directive at all, so the type's directive widened nothing and the rule
// has nothing to say.
//
//declscope:shared
type userCard struct {
	id   int
	note int
}

func userRead(c userCard) int { return c.note }

var _ = userRead
""",
}

SRC_SURPLUSLOOSE = {
    '.declscope.yaml': """rules:
  surplus: loose
""",
    'helper.go': """// helperShared is called from order.go, so the directive is in use, and under
// loose, that is all the rule asks. helperLocal is not reported;
// strict is what judges it on its own.
//
//declscope:shared

package surplusloose

func helperShared() int { return helperLocal() }

func helperLocal() int { return 1 }
""",
    'order.go': """package surplusloose

func orderRun() int { return helperShared() }

var _ = orderRun
""",
}

SRC_SURPLUSSTRICTTESTS = {
    '.declscope.yaml': """# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
""",
    'integration_test.go': """package surplusstricttests

import "testing"

func TestIntegration(t *testing.T) {
	if (userCard{note: 1}).note != 1 {
		t.Fatal("no")
	}
}

var _ = userFixture{}.name
""",
    'order.go': """package surplusstricttests

func orderRun(c userCard) int { return c.id }

var _ = orderRun
""",
    'user.go': """package surplusstricttests

// note's only outside use is in integration_test.go, a namespace of its own.
// The test variant sees it and stays quiet. The ordinary variant does not see
// every file, so the rule switches off there instead of reporting.
//
//declscope:shared
type userCard struct {
	id   int
	note int
}
""",
    'user_test.go': """package surplusstricttests

// Only the test variant sees this file, so only it can report here, and it
// does: a want in a _test.go file is checked in that variant alone.
//
//declscope:shared
type userFixture struct {
	name  string
	extra int // want `field userFixture.extra takes shared scope from //declscope:shared on userFixture, but no use from another namespace is visible to declscope`
}

func userFixtureExtra(f userFixture) int { return f.extra }

var _ = userFixtureExtra
""",
}

SRC_SURPLUSSTRICTOPAQUE = {
    '.declscope.yaml': """# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
""",
    'box.go': """package surplusstrictopaque

// userBox crosses, so it is reported and its fix widens it. Under strict the
// fix would also narrow n, which nothing outside reads, but the rule cannot
// read gen.go, so it predicts nothing and the fix narrows no member.
type userBox struct { // want `type userBox is private to namespace "box", but is used from namespace "order"`
	n int
}

func boxRead(b userBox) int { return b.n }

var _ = boxRead
""",
    'gen.go': """// Code generated by a tool. DO NOT EDIT.

package surplusstrictopaque

func genUse(c userCard) int { return c.note }

var _ = genUse
""",
    'order.go': """package surplusstrictopaque

func orderRun(c userCard, b userBox) int { return c.id + len([]any{b}) }

var _ = orderRun
""",
    'user.go': """package surplusstrictopaque

// note's only outside use is in gen.go, which the analysis excludes as a
// reference site. The package holds a source the rule cannot read, so the
// rule switches off for it.
//
//declscope:shared
type userCard struct {
	id   int
	note int
}
""",
}

SRC_SURPLUSSTRICTBASELINED = {
    '.declscope-baseline.yaml': """packages:
  surplusstrictbaselined:
    surplus:
      box:
        - boxRead
        - boxed
        - boxed.n
      user:
        - userCard.old
""",
    '.declscope.yaml': """# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
""",
    'box.go': """//declscope:shared

package surplusstrictbaselined

// boxKind is read from order.go, which keeps the file's directive in use.
type boxKind int

// boxed was reported with its field n, and both are in the baseline. The
// type's finding then offers no fix to narrow extra, which came later.
type boxed struct {
	n     int
	extra int // want `field boxed.extra takes shared scope from the file's //declscope:shared, but no use from another namespace is visible to declscope`
}

func boxRead(b boxed) int { return b.n + b.extra }

var _ = boxRead
""",
    'order.go': """package surplusstrictbaselined

func orderRun(c userCard, k boxKind) int { return c.id + int(k) }

var _ = orderRun
""",
    'user.go': """package surplusstrictbaselined

// old is recorded in the baseline, so it stays quiet. fresh is not.
//
//declscope:shared
type userCard struct {
	id    int
	old   int
	fresh int // want `field userCard.fresh takes shared scope from //declscope:shared on userCard, but no use from another namespace is visible to declscope`
}

func userRead(c userCard) int { return c.old + c.fresh }

var _ = userRead
""",
}

SRC_UNUSEDLOOSE = {
    '.declscope.yaml': """rules:
  unused: loose
""",
    'a.go': """package unusedloose

// This fixture selects rules.unused: loose. A private field of a type that states
// no scope names the scope defaults.unexported gives it today, but another
// configuration could give it package, so the directive is not reported.
type implicit struct {
	//declscope:private
	x int
}

// Restating the type's directive decides nothing under any configuration, and
// loose reports it.
//
//declscope:private
type explicit struct {
	//declscope:private // want `unused //declscope:private on explicit.x: nothing it reaches takes a scope`
	x int
}

var _ = implicit{}.x + explicit{}.x
""",
    'b.go': """//declscope:private // want `unused file-level //declscope:private$`

package unusedloose

// The spec's private narrows its block's package. Deleting it would widen the
// spec, so it binds, whatever the file says. The block's directive and the
// file's reach no declaration that takes their scope, and are reported.
//
//declscope:shared // want `unused //declscope:shared: every declaration it reaches states its own scope`
var (
	//declscope:private
	bNarrowed = 1
)

var _ = bNarrowed
""",
    'c.go': """package unusedloose

// The exported spec's package widens it back from its block's private.
// Deleting it would narrow the spec, so it binds. The block binds cOther.
//
//declscope:private
var (
	//declscope:shared
	CWidened = 2
	cOther   = 3
)

var _ = cOther
""",
    'd.go': """package unusedloose

// A type that declares no name is reached through its fields alone. DWide
// takes the type's package, which it has anyway as an exported name, and
// dNarrow states private. The report must not say that every field states
// its own scope: DWide states none.
//
//declscope:shared // want `unused //declscope:shared: nothing it reaches takes a scope$`
type _ struct {
	DWide int
	//declscope:private
	dNarrow int
}

// Its only field takes the type's package, so the directive reaches a checked
// declaration and the report must not say that none carries it.
//
//declscope:shared // want `unused //declscope:shared: nothing it reaches takes a scope$`
type _ struct {
	DOnly int
}
""",
}

SRC_UNUSEDSTRICT = {
    '.declscope.yaml': """rules:
  unused: strict
  # surplus would report the shared directives kept here as widening for
  # nothing; this package is about the unused rule alone.
  surplus: off
""",
    'a.go': """package unusedstrict

// Under strict, a private field of a type that states no scope is reported:
// defaults.unexported gives it private without the directive.
type implicit struct {
	//declscope:private // want `unused //declscope:private on implicit.x: it already has private scope`
	x int
}

// The type's directive restates the default too, and the field's restates the
// type's. Both are reported, as loose reports the field's.
//
//declscope:private // want `unused //declscope:private on explicit: it already has private scope`
type explicit struct {
	//declscope:private // want `unused //declscope:private on explicit.x: it already has private scope`
	x int
}

// A directive that changes the scope is kept: package widens an unexported
// declaration, and private narrows an exported one.
//
//declscope:shared
func widened() int { return 1 }

//declscope:private
func Narrowed() int { return 2 }

// A type's directive that one field overrides is judged by that field too:
// without the type's, the field's own would restate the default instead.
//
//declscope:shared
type mixed struct {
	shared int
	//declscope:private
	own int
}

var _ = implicit{}.x + explicit{}.x + widened() + mixed{}.shared + mixed{}.own
""",
    'b.go': """package unusedstrict

// A block's directive that restates the default is reported with every spec
// that takes it.
//
//declscope:private // want `unused //declscope:private on seed, limit: each already has private scope`
var (
	seed  = 1
	limit = 2
)

// A spec restating its block is reported. The block keeps its report too: it
// names what every spec already has.
//
//declscope:private // want `unused //declscope:private: every declaration it reaches already has private scope`
var (
	//declscope:private // want `unused //declscope:private on other: it already has private scope`
	other = 3
)

// A spec narrowing its block's package is not redundant: without it the spec
// would take the block's scope, not the default.
//
//declscope:shared
var (
	//declscope:private
	narrowed = 4
	wide     = 5
)

var _ = seed + limit + other + narrowed + wide
""",
    'c.go': """//declscope:private // want `unused file-level //declscope:private: every declaration it reaches already has private scope`

package unusedstrict

// A declaration restating the file's directive is reported, and so is the
// file's, which restates the default for everything here.
//
//declscope:private // want `unused //declscope:private on cFile: it already has private scope`
func cFile() int { return 1 }

func cOther() int { return 2 }

var _ = cFile() + cOther()
""",
    'd.go': """package unusedstrict

// A redundant directive on a declaration another namespace uses is reported,
// but deleting it would move the level the boundary report names.
//
//declscope:private // want `unused //declscope:private on dShared: it already has private scope`
func dShared() int { return 1 } // want `func dShared is declared private by //declscope:private, but is used from namespace "e"`

// An ignore for the unused rule answers the strict report as well.
//
//declscope:private
//declscope:ignore unused
func dQuiet() int { return 2 }

var _ = dQuiet()
""",
    'e.go': """package unusedstrict

var _ = dShared()
""",
    'f.go': """//declscope:private // want `unused file-level //declscope:private: every declaration it reaches already has private scope`

package unusedstrict

// The spec's private narrows its block's package, so strict keeps it too. The
// block reaches no declaration that takes its scope. The file's private is
// what fNarrowed would have from the default anyway.
//
//declscope:shared // want `unused //declscope:shared: every declaration it reaches states its own scope`
var (
	//declscope:private
	fNarrowed = 1
)

var _ = fNarrowed
""",
    'g.go': """package unusedstrict

// The exported spec's package widens it back from its block's private, so
// strict keeps it. The block is kept as well: without it, the spec's package
// would restate what exportedness gives.
//
//declscope:private
var (
	//declscope:shared
	GWidened = 2
	gOther   = 3
)

var _ = gOther
""",
    'h.go': """//declscope:shared

package unusedstrict

// The block restates the file's package, so strict reports it. Its only spec
// states private, so the report says the spec states its own scope: it does
// not have the block's.
//
//declscope:shared // want `unused //declscope:shared: every declaration it reaches states its own scope`
var (
	//declscope:private
	hNarrowed = 1
)

func hWide() int { return 2 }

var _ = hNarrowed + hWide()
""",
    'i.go': """package unusedstrict

// A type that declares no name is reached through its fields alone. Its
// private restates the default, and its only field states package, so the
// report says the field states its own scope.
//
//declscope:private // want `unused //declscope:private: every declaration it reaches states its own scope`
type _ struct {
	//declscope:shared
	x int
}
""",
    'j.go': """package unusedstrict

// A type that declares no name, one field taking its private and one stating
// package. The private restates the default, so strict reports it. The report
// must not say that every field states its own scope: jTaken states none.
//
//declscope:private // want `unused //declscope:private: every declaration it reaches states its own scope or already has private scope$`
type _ struct {
	jTaken int
	//declscope:shared
	jWidened int
}
""",
}

SRC_UNUSEDDEFAULTSTRICT = {
    'user.go': """package unuseddefaultstrict

//declscope:private // want `unused //declscope:private on userLocal: it already has private scope`
func userLocal() {}
""",
}

SRC_UNUSEDOFF = {
    '.declscope.yaml': """rules:
  unused: off
""",
    'a.go': """package unusedoff

// Under rules.unused: off nothing is reported unused. Not an ignore that
// silences nothing,
//
//declscope:ignore boundary
func aIgnore() int { return 1 }

// nor a scope directive no configuration could make bind,
//
//declscope:shared
func AExported() int { return 2 }

// nor one naming the scope the declaration would have without it.
type aImplicit struct {
	//declscope:private
	x int
}

// The directive rule has no switch, so a malformed directive is still
// reported.
//
//declscope:bogus // want `unknown directive declscope:bogus`
func aTypo() int { return 3 }

var _ = aIgnore() + AExported() + aImplicit{}.x + aTypo()
""",
    'b.go': """//declscope:ignore

package unusedoff

// A file-level ignore that silences nothing is not reported either.
func bQuiet() int { return 1 }

var _ = bQuiet()
""",
}

SRC_UNUSEDSTRICTPKG = {
    '.declscope.yaml': """defaults:
  unexported: shared
rules:
  unused: strict
  surplus: off
""",
    'a.go': """package unusedstrictpkg

// Under defaults.unexported: shared the private field narrows it, and is kept.
type implicit struct {
	//declscope:private
	x int
}

// A shared directive on an unexported declaration restates the default.
//
//declscope:shared // want `unused //declscope:shared on helper: it already has shared scope`
func helper() int { return 1 }

// So does a type's, and a field's restating it.
//
//declscope:shared // want `unused //declscope:shared on shape: it already has shared scope`
type shape struct {
	//declscope:shared // want `unused //declscope:shared on shape.side: it already has shared scope`
	side int
}

var _ = implicit{}.x + helper() + shape{}.side
""",
    'b.go': """//declscope:shared // want `unused file-level //declscope:shared: every declaration it reaches takes a nearer directive's scope$`

package unusedstrictpkg

// The file's package restates the default, and its only declaration states
// private. The report must not say that bNarrow has shared scope.
//
//declscope:private
func bNarrow() int { return 1 }

var _ = bNarrow()
""",
    'c.go': """//declscope:shared // want `unused file-level //declscope:shared: every declaration it reaches takes a nearer directive's scope or already has shared scope`

package unusedstrictpkg

// One declaration takes the file's package, which the default gives anyway,
// and one states private. The report names both kinds.
func cWide() int { return 1 }

//declscope:private
func cNarrow() int { return 2 }

var _ = cWide() + cNarrow()
""",
}

SRC_SYMBOLFILE = {
    'order.go': """package symbolfile

func orderRun() int { return helper() }

var _ = orderRun
""",
    '★.go': """package symbolfile

// A file whose name holds no letter or digit has no namespace of its own,
// so a report names the file instead.
func helper() int { return 1 } // want `func helper is private to file ★.go, but is used from namespace "order"`
""",
}

SRC_GENERATEDOWNER = {
    '.declscope.yaml': """rules:
  naming:
    qualify: always
""",
    'gen.go': """// Code generated by hand, for this test. DO NOT EDIT.

package generatedowner

type Gen struct{}
""",
    'user.go': """package generatedowner

// A method on a type declared in a generated file has no second file to be
// foreign to: the generated file is not read, so the naming rule leaves the
// method alone, as it does a method beside its type.
func (Gen) run() int { return 1 }

var _ = Gen{}.run
""",
}

SRC_LINEIGNORE = {
    'x.go': """//declscope:ignore

package lineignore

// A //line directive renames the positions below it. The file-level ignore
// above still covers them, because it is about the file on disk.
//
//line x.tmpl:1
//declscope:bogus
func run() {}
""",
}

SRC_LINEFOREIGN = {
    '.declscope.yaml': """# The naming rule is off by default. This package asserts that it still
# reaches a foreign method below a //line directive.
rules:
  naming:
    qualify: ondemand
  surplus: off
""",
    'order.go': """package lineforeign

// A foreign method: its receiver's type is declared in user.go.
func (u *userRecord) leak() string { // want `method leak does not carry namespace "order" anywhere in its name; rename it to orderLeak, or to another name that carries "order"`
	return u.name
}

func orderRun() string { return (&userRecord{}).leak() }

var _ = orderRun
""",
    'user.go': """package lineforeign

// The type below a //line directive is still declared in user.go, so a method
// filed in order.go is away from it.
//
//line user.tmpl:1
type userRecord struct { // want `type userRecord is private to namespace "user", but is used from namespace "order"`
	name string // want `field userRecord.name is private to namespace "user", but is used from namespace "order"`
}
""",
}

SRC_LINEUNSEEN = {
    'user.go': """//line gen/user.tmpl:1
package lineunseen

// A //line directive above the package clause renames the file itself. The
// file is still the one the pass holds, so nothing is withheld.
//
//declscope:shared // want `//declscope:shared on userQuiet: no use from another namespace is visible to declscope`
func userQuiet() int { return 1 }
""",
}


def test_package_level(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a package-level func, var, const and type used from another
    file's namespace is reported on the declaration with the use attached, that a name prefix grants nothing,
    and that //declscope:shared and exported names carry no boundary.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_PKGLEVEL})
    out = ds(["./..."])
    assert out.transcript == golden("package_level")


def test_members(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an unexported field and method are bounded by their type's
    file, that exported members carry no boundary, and that a shared constructor may touch them.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_MEMBERS})
    out = ds(["./..."])
    assert out.transcript == golden("members")


def test_foreign_method(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks which methods the naming rule reaches. A method filed away from its
    receiver's type is read through a receiver that names a different unit, so the rule asks for the namespace
    the method is written in. A local method and an interface method name are left alone.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FOREIGNMETHOD})
    out = ds(["./..."])
    assert out.transcript == golden("foreign_method")


def test_boundary_off(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that rules.boundary: off leaves the naming rule running on its own.
    A reach that would be reported is not, and a name that does not carry its namespace still is.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_BOUNDARYOFF})
    out = ds(["./..."])
    assert out.transcript == golden("boundary_off")


def test_filter_cancelled(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the one filter report. A config beside a package states an only, the
    files it matches are all removed by an only above it, and the package is read as empty. Nobody writes a
    filter for a subtree they meant to exclude, so the tool says the config cannot take effect.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FILTERCANCELLED_SUB})
    out = ds(["./..."])
    assert out.transcript == golden("filter_cancelled")


def test_ignore_filter(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an ignore naming the filter rule silences nothing. Fixing
    filter.only in the config chain is what resolves that report, so the ignore is reported as unused.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNOREFILTER})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_filter")


def test_empty_file(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a file holding only a package clause and comments does not add
    to the namespace count. A doc.go is the usual one. The analyzer must print nothing here, so the namespaces
    and declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_EMPTYFILE})
    out = ds(["./..."])
    assert out.transcript == golden("empty_file")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("empty_file_inspect")


def test_blank_import(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the other side: a file whose only content is an import declares
    something, because the import runs.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_BLANKIMPORT})
    out = ds(["./..."])
    assert out.transcript == golden("blank_import")


def test_ignore_directive(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks which ignore answers a report of the directive rule. Such a report
    hangs on a comment rather than on a declaration, so the file level answers one written where no
    declaration is. An ignore naming directive answers no unused report, and is itself reported as unused when
    that is all it was written for.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNOREDIRECTIVE})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_directive")


def test_ignore_unused(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks which ignore answers the unused rule's report on another ignore: one
    beside it naming unused, or one at the file level, bare or named. A bare one beside it does not, and no
    ignore answers its own report, whatever it names.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNOREUNUSED})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_unused")


def test_ignore_unseen(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an ignore of boundary is not unused when a file the build
    excluded names the declaration it reaches: that file may cross into it in a configuration that reads it.
    An ignore no unseen file gives a job, or one of a rule judged on the declaration, is still unused.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNOREUNSEEN})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_unseen")


def test_ignore_unseen_test(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the same where the excluded file is the package's only test file. No
    variant sees it, so the non-test variant reads it for its names and still reports an ignore it gives no
    job.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNOREUNSEENTEST})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_unseen_test")


def test_ignore_module_wide(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an ignore naming a rule only declscope shrink reports is never
    judged unused here, and that a bare ignore does not reach such a rule, so the analyzer still judges it.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNOREMODULEWIDE})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_module_wide")


def test_directives(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks every malformed, unknown, conflicting and misplaced directive report
    of the directive rule, with its exact message and position.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_DIRECTIVES})
    out = ds(["./..."])
    assert out.transcript == golden("directives")


def test_duplicate_directive(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a scope directive or an ignore repeated on one declaration or
    one file is reported at the second, and that a repeated ignore is not also reported unused.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_DUPLICATEDIRECTIVE})
    out = ds(["./..."])
    assert out.transcript == golden("duplicate_directive")


def test_test_files_share_namespace(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a _test.go file may use the private declarations of its
    subject. The analyzer must print nothing here, so the namespaces and declarations that inspect reads from
    the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_TESTNS})
    out = ds(["./..."])
    assert out.transcript == golden("test_files_share_namespace")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("test_files_share_namespace_inspect")


def test_generated_files_excluded(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that generated files are neither checked nor treated as reference
    sites. The analyzer must print nothing here, so the namespaces and declarations that inspect reads from
    the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_GENERATED})
    out = ds(["./..."])
    assert out.transcript == golden("generated_files_excluded")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("generated_files_excluded_inspect")


def test_qualify(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an unexported package-level declaration must carry its
    namespace as a prefix, and that members and exported identifiers are exempt.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_QUALIFYRULE})
    out = ds(["./..."])
    assert out.transcript == golden("qualify")


def test_single_namespace(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that the prefix is not required in a package with only one
    namespace, where there is no boundary for it to mark. The analyzer must print nothing here, so the
    namespaces and declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SINGLENS})
    out = ds(["./..."])
    assert out.transcript == golden("single_namespace")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("single_namespace_inspect")


def test_qualify_inflections(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the two inflections whose spelling leaves the namespace behind: a
    final e dropped before -ing (store → storing) and a final y turned to i (apply → applied). Only forms
    generated from the namespace are accepted, so a name that merely shares the stem (story) is still
    reported.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_QUALIFYINFLECT})
    out = ds(["./..."])
    assert out.transcript == golden("qualify_inflections")


def test_qualify_inflected_namespace(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the message of a namespace that is itself an inflected form. Its
    stem does not carry it, since generation runs only from the namespace, so the message names the vocabulary
    key instead. A namespace with no vowel before -ing (string) gets the plain message.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_QUALIFYINFLECTED})
    out = ds(["./..."])
    assert out.transcript == golden("qualify_inflected_namespace")


def test_qualify_vocabulary(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks rules.naming.vocabulary: a word listed for a namespace satisfies the
    naming rule under the same test as the namespace itself — word boundary on the left, free right edge — and
    nothing more.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_VOCABULARY})
    out = ds(["./..."])
    assert out.transcript == golden("qualify_vocabulary")


def test_qualify_default_off(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the built-in default: with no config, the naming rule asks nothing
    even of a package with a second namespace, while the boundary rule fires as it always did.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_QUALIFYDEFAULT})
    out = ds(["./..."])
    assert out.transcript == golden("qualify_default_off")


def test_namespace_directive_detached(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a namespace directive separated from the package clause by a
    blank line still applies to the file. The analyzer must print nothing here, so the namespaces and
    declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_NSDETACHED})
    out = ds(["./..."])
    assert out.transcript == golden("namespace_directive_detached")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("namespace_directive_detached_inspect")


def test_namespace_directive_in_package_doc(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the placement prescribed by Go's doc comment convention: a directive
    at the bottom of the package comment, which go/doc strips from the rendered documentation. The analyzer
    must print nothing here, so the namespaces and declarations that inspect reads from the same package are
    pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_NSINDOC})
    out = ds(["./..."])
    assert out.transcript == golden("namespace_directive_in_package_doc")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("namespace_directive_in_package_doc_inspect")


def test_baseline(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that recorded violations are suppressed while new ones are still
    reported. The baseline lives in testdata/src/baselined and is found by the same upward lookup as the
    config file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_BASELINED})
    out = ds(["./..."])
    assert out.transcript == golden("baseline")


def test_qualify_baseline_keys_the_receiver(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a qualify baseline entry names a method with its receiver type,
    so baselining orderA.help does not absorb a new orderB.help in the same namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_QUALIFYBASELINED})
    out = ds(["./..."])
    assert out.transcript == golden("qualify_baseline_keys_the_receiver")


def test_explicit_scope_conflict(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a declaration whose scope was stated by a directive is reported
    without a fix, since -fix must not overwrite a decision the author made deliberately.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_EXPLICIT})
    out = ds(["./..."])
    assert out.transcript == golden("explicit_scope_conflict")


def test_qualify_always(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks rules.qualify: always, which requires the prefix even in a package
    with a single namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_QUALIFYALWAYS})
    out = ds(["./..."])
    assert out.transcript == golden("qualify_always")


def test_ignore_scope(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an ignore directive can name the rules it silences, and that
    each directive is reported unused on its own.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IGNORESCOPE})
    out = ds(["./..."])
    assert out.transcript == golden("ignore_scope")


def test_file_ignore(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an ignore directive before the package clause applies to every
    declaration in the file, and is reported when it silences nothing.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FILEIGNORE})
    out = ds(["./..."])
    assert out.transcript == golden("file_ignore")


def test_file_ignore_is_file_scoped(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a file-level ignore covers only the file carrying it, not every
    file sharing its namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FILEIGNORESCOPE})
    out = ds(["./..."])
    assert out.transcript == golden("file_ignore_is_file_scoped")


def test_type_ignore(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a member inherits the ignore directives written on the type
    that owns it, wherever the member is declared, and that a directive used up only by a member still counts
    as used.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_TYPEIGNORE})
    out = ds(["./..."])
    assert out.transcript == golden("type_ignore")


def test_defaults_reach_members(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that defaults.unexported resolves members too, not only
    package-level declarations.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_DEFAULTSMEMBERS})
    out = ds(["./..."])
    assert out.transcript == golden("defaults_reach_members")


def test_unkeyed_literal(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a composite literal without keys uses every field it writes,
    though it names none of them, and that a literal of a generic struct's instantiation uses the declared
    fields. A literal that leaves out a pointer type, as in []*T{{1}}, writes the fields of T.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNKEYED})
    out = ds(["./..."])
    assert out.transcript == golden("unkeyed_literal")


def test_generics(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that the members of a generic type are bounded like those of any
    other type. go/types records the instantiated field or method for a selection on List[int], and on List[T]
    inside the type's own methods, so the lookup has to normalize to the origin object.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_GENERICS})
    out = ds(["./..."])
    assert out.transcript == golden("generics")


def test_embedded(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that embedding a type is a use of it. The embedded field's ident is
    both a definition (the field) and a use (the type), and the second role is the one boundary has to see.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_EMBEDDED})
    out = ds(["./..."])
    assert out.transcript == golden("embedded")


def test_member_owner_file(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the split between a field and a method. A field is written inside
    its type's declaration, so the type's file bounds it wherever it is read; a method is an ordinary
    top-level declaration and belongs to the file that wrote it. Binding methods to their type's file instead
    left one unusable from the file declaring it, with no scope able to say otherwise.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_MEMBEROWNER})
    out = ds(["./..."])
    assert out.transcript == golden("member_owner_file")


def test_core_namespace(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the core: several files share the one unnamed namespace, the naming
    rules are outside it, and an ordinary namespace in the same package is asked for its prefix as usual. It
    also checks that //declscope:core carries no scope. A core declaration is private to the core by default,
    so naming it from outside crosses a boundary, and a file wanting both states both.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_CORENS})
    out = ds(["./..."])
    assert out.transcript == golden("core_namespace")


def test_core_named_test(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a test file naming its own namespace keeps it, though its stem
    is a core file's. Only a file with no namespace directive joins the core. Joining anyway dropped the
    directive without a report, so a core test file could reach what the named one declares.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_CORENAMEDTEST})
    out = ds(["./..."])
    assert out.transcript == golden("core_named_test")


def test_core_test_subject(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a core test file does not take its subject into the core. Only
    a test file joins, so the package and its test variant report client.go's crossing under the same
    namespace.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_CORETESTSUBJECT})
    out = ds(["./..."])
    assert out.transcript == golden("core_test_subject")


def test_core_goos_sibling(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a core GOOS file does not take its plain sibling into the core.
    Joining made foo.go's namespace depend on the build.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_COREGOOSSIBLING})
    out = ds(["./..."])
    assert out.transcript == golden("core_goos_sibling")


def test_uncapitalizable_namespace(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a namespace whose first letter has no capital form, such as 用户
    or _foo, gets no naming diagnostic. Qualify could not keep an exported name exported with it, so the
    advice unexported the name.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNCAPITALIZABLE})
    out = ds(["./..."])
    assert out.transcript == golden("uncapitalizable_namespace")


def test_file_scope(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks a file-level scope directive: a default for what the file declares,
    which a declaration may still narrow back. Under the ignore this replaces, the narrowing would have meant
    nothing.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_FILESCOPE})
    out = ds(["./..."])
    assert out.transcript == golden("file_scope")


def test_name_exported(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks rules.naming.exported, and that the prefix carries the exportedness
    of the name it joins: New is reported against ClientNew, never clientNew, since a rename must not delete
    the API it is renaming.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_EXPORTEDPREFIXES})
    out = ds(["./..."])
    assert out.transcript == golden("name_exported")


def test_exported_scope(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that exportedness decides the default and nothing else: an exported
    declaration carries no boundary until a directive gives it one, and a directive on a type reaches its
    exported fields — which is how a DTO capitalized for a serializer is protected, without the analysis
    guessing at reachability it cannot compute.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_EXPORTEDSCOPE})
    out = ds(["./..."])
    assert out.transcript == golden("exported_scope")


def test_unused_scope_directive(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the structural test: a scope directive that binds nothing is
    reported, an exported type with an unexported field still binds one, and restating the scope already in
    force is not reported at all. The two ways a block's directive can reach nothing — every spec overriding
    it, and nothing checked being able to carry it — are reported apart.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNUSEDSCOPE})
    out = ds(["./..."])
    assert out.transcript == golden("unused_scope_directive")


def test_namespace_identity(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a file whose stem cannot be a prefix, such as 2fa.go, is still
    a namespace: its test file shares it, a use from another namespace is reported, and the naming rule asks
    nothing of it.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_NSIDENTITY})
    out = ds(["./..."])
    assert out.transcript == golden("namespace_identity")


def test_namespace_normalize(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that separators other than _ and a PascalCase stem yield a
    lowerCamelCase namespace, so that the rename offered by qualify is a valid unexported identifier.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_NSNORMALIZE})
    out = ds(["./..."])
    assert out.transcript == golden("namespace_normalize")


def test_namespace_initialism(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a namespace spells its initialisms the way Go does, that the
    prefix is matched ignoring case, and that the rename offered by qualify spells the name's first word the
    same way.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_NSINITIALISM})
    out = ds(["./..."])
    assert out.transcript == golden("namespace_initialism")


def test_namespace_test_suffix(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a file with a build suffix after _test, such as
    foo_test_linux.go, is not a test of foo.go and has a namespace of its own. GOOS is set so that the file is
    compiled on every host.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_NSTESTSUFFIX})
    out = ds(["./..."], env_overrides={"GOOS": "linux"})
    assert out.transcript == golden("namespace_test_suffix")


def test_block_ignore(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an ignore directive is judged once per comment, not once per
    declaration it reaches: one on a block, or shared by the names of one spec, is used as soon as any of them
    needed it, and is reported once when none did.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_BLOCKIGNORE})
    out = ds(["./..."])
    assert out.transcript == golden("block_ignore")


def test_test_only_ignore(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a directive needed only by a reference in a _test.go file is
    not reported unused by the ordinary variant of the package, which cannot see that reference. Only the test
    variant, which sees every file, judges, and a directive in a test file shows that it does.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_TESTONLYIGNORE})
    out = ds(["./..."])
    assert out.transcript == golden("test_only_ignore")


def test_brace_ignore(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the two placements go/parser attaches to nothing: a trailing comment
    on the first or last line of a multi-line declaration binds to it, and a directive anywhere else after the
    package clause is reported as misplaced rather than silently dropped.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_BRACEIGNORE})
    out = ds(["./..."])
    assert out.transcript == golden("brace_ignore")


def test_line_after_comment(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a directive trailing a declaration's first or last line binds
    even when an earlier comment, one that is not a directive, starts on that line too. The analyzer must
    print nothing here, so the namespaces and declarations that inspect reads from the same package are pinned
    too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_LINEAFTERCOMMENT})
    out = ds(["./..."])
    assert out.transcript == golden("line_after_comment")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("line_after_comment_inspect")


def test_aliases(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks what a directive on a type alias reaches. The alias name is an
    ordinary declaration, so //declscope:shared on it widens the name and use.go may take an al — the silence
    on alias.go is the assertion. It does not reach the aliased defined type's members, so Base.n keeps
    base.go's boundary. An alias to a struct written inline does contain its fields.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_ALIASES})
    out = ds(["./..."])
    assert out.transcript == golden("aliases")


def test_interface_members(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that an interface's method names are members. The silences carry as
    much as the reports: implicit satisfaction in impl.go is not a use, the type's directive and its ignore
    reach the methods, and an embedded interface or a type-constraint element declares no name to bound.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_IFACEMEMBERS})
    out = ds(["./..."])
    assert out.transcript == golden("interface_members")


def test_package_main(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the two rules that only package main exercises: func main is the one
    name the toolchain requires, so the naming rules pass it by even at qualify: always, and a file-level
    scope directive reaches exported declarations, which is the only thing holding Config and ServerNew back.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_MAINPKG})
    out = ds(["./..."])
    assert out.transcript == golden("package_main")


def test_toolchain_names(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a name the toolchain finds by name is never asked for a prefix.
    The silences carry the assertion: TestLoad, BenchmarkLoad, FuzzLoad and ExampleTestHelper would each be a
    function nothing runs once prefixed. TestHelper in a non-test file is still asked, because nothing
    collects it by name.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_TOOLCHAINNAMES})
    out = ds(["./..."])
    assert out.transcript == golden("toolchain_names")


def test_surplus(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the surplus rule's reporting shapes: one report per physical
    //declscope:shared, listing every declaration that takes its scope from it, at every level the directive
    can be written. The quiet cases carry as much: an ignore silences it, and an exported name anywhere in the
    comment's reach keeps the whole comment.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUS})
    out = ds(["./..."])
    assert out.transcript == golden("surplus")


def test_surplus_used_outside(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the first suppressor: a name spelled from another namespace keeps
    its directive, one member's use keeps a shared comment, a member that states its own scope stops carrying
    the type's, and a composite literal without keys counts as the use it is.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSUSED})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_used_outside")


def test_surplus_satisfies(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the interface suppressor: a method reached only through a contract
    stays quiet, including through an anonymous struct, a function-local type, an instantiated generic type, a
    promoted pointer-receiver method, an anonymous interface in a type assertion, and a constraint carrying a
    type term. A method in no contract is still reported.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSATISFIES})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_satisfies")


def test_surplus_satisfies_pairs(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the shapes that decide which pairs of an interface and a type are
    tested for satisfaction: a method promoted through an embedded pointer, a method of an instantiated
    generic type with a pointer receiver, an interface embedding another, a requirement asked for only through
    an embedded instantiation, and a named function type. Each method stays quiet, and one in no contract is
    still reported.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSATISFIESPAIRS})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_satisfies_pairs")


def test_surplus_carrier(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the carrier suppressor: an exported type — or an exported alias, or
    an exported interface — carries an unexported method out of the package, where an importer can complete a
    satisfaction the analysis never sees. Only a method nothing exported carries is reported.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSCARRIER})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_carrier")


def test_surplus_linkname(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the linkname suppressor: //go:linkname and //export name a
    declaration as text, from code the analysis does not read.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSLINKNAME})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_linkname")


def test_surplus_opaque_source(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the opaque-source suppressor: a package holding a generated file has
    reference sites the analysis excludes, so the rule switches off for the package rather than read the
    absence as evidence. The silence is the assertion. The analyzer must print nothing here, so the namespaces
    and declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSOPAQUE})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_opaque_source")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("surplus_opaque_source_inspect")


def test_surplus_excluded_generator(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a build-excluded file of another package, the //go:build ignore
    generator declaring package main, does not switch the rule off: it can name nothing of this package
    (https://github.com/mpyw/declscope/issues/253).
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSGENERATOR})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_excluded_generator")


def test_surplus_excluded_own_file(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a build-excluded file of the package itself still switches the
    rule off. It is read for names only, and a name is not enough to rule out a use. The silence is the
    assertion. The analyzer must print nothing here, so the namespaces and declarations that inspect reads
    from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSEXCLUDED})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_excluded_own_file")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("surplus_excluded_own_file_inspect")


def test_surplus_sees_all_files(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that only a pass reading every file may report: the ordinary variant
    of a package with in-package tests switches the rule off, and the test variant sees the use. The silence
    in both variants is the assertion. The analyzer must print nothing here, so the namespaces and
    declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSTESTS})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_sees_all_files")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("surplus_sees_all_files_inspect")


def test_surplus_conversion(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a struct conversion counts as reach: it pairs every field by
    name and spells none of them, so a field whose directive holds the conversion together must stay
    unreported.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSCONVERT})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_conversion")


def test_type_param_sets(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a literal or a conversion through a type parameter writes the
    fields of every struct in its type set: a named struct as the constraint, an intersection leaving one
    pointer, an interface term inside a union, and two structs sharing one underlying type.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_TYPEPARAMSETS})
    out = ds(["./..."])
    assert out.transcript == golden("type_param_sets")


def test_surplus_default_surplusdefault(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which pins the built-in default: with no config, the rule reports a directive
    nothing needs.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSDEFAULT})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_default_surplusdefault")


def test_surplus_default_surplusdefaultstrict(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which pins the built-in default: with no config, the rule reports a directive
    nothing needs.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSDEFAULTSTRICT})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_default_surplusdefaultstrict")


def test_surplus_baseline(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a recorded surplus finding is suppressed while a new one is
    still reported, through the same lookup as every rule.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSBASELINED})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_baseline")


def test_surplus_strict(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks strict's reporting shapes, at every level a directive encloses a
    declaration: a field under its type's directive, a declaration under its file's, a spec under its block's.
    Each is reported one per name when nothing outside reaches it, while its directive is otherwise in use. An
    entry holding a name that is read outside is not; neither is an exported declaration, one stating its own
    scope, an embedded field or a directive loose already reports. A type is reported with the members it
    would narrow, and not when one of them is reached. An ignore for surplus silences it, with the
    unused-ignore accounting.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSTRICT})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_strict")


def test_surplus_strict_reach(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks every way a field is reached without its name being spelled from
    outside: a composite literal without keys, also one behind an elided pointer type, a selection promoted
    through an embedding, a selection on an instantiated generic type, a struct conversion, also one between
    pointers, and a method written in another namespace. Each keeps the type's scope, and a field reached by
    none of them is still reported.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSTRICTREACH})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_strict_reach")


def test_surplus_strict_defaults(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that under defaults.unexported: shared strict adds nothing: the
    declaration would be shared with no directive, so the directive widened nothing. The analyzer must print
    nothing here, so the namespaces and declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSTRICTDEFAULTS})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_strict_defaults")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("surplus_strict_defaults_inspect")


def test_surplus_loose(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks the loose mode: a directive in use says nothing about the
    declarations under it that nothing outside reaches. The analyzer must print nothing here, so the
    namespaces and declarations that inspect reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSLOOSE})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_loose")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("surplus_loose_inspect")


def test_surplus_strict_sees_all_files(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that only a pass reading every file may report: the ordinary variant
    of a package with in-package tests switches the rule off, and the test variant sees the use a test file
    makes. What the test variant alone reports is pinned from a _test.go file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSTRICTTESTS})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_strict_sees_all_files")


def test_surplus_strict_opaque_source(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a package holding a generated file, whose reference sites the
    analysis excludes, gets no report.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSTRICTOPAQUE})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_strict_opaque_source")


def test_surplus_strict_baseline(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a recorded strict finding is suppressed while a new one is
    still reported, keyed like any surplus finding by the declaration's name.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SURPLUSSTRICTBASELINED})
    out = ds(["./..."])
    assert out.transcript == golden("surplus_strict_baseline")


def test_unused_loose(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks rules.unused: loose: a scope directive naming the scope
    defaults.unexported gives today is kept, since another configuration could make it bind, and one restating
    an enclosing directive is reported as before.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNUSEDLOOSE})
    out = ds(["./..."])
    assert out.transcript == golden("unused_loose")


def test_unused_strict(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks rules.unused: strict under the private default. A directive naming
    the scope its declarations would have without it is reported, at the field, type, block, spec and file
    levels, and one that widens, narrows, or is overridden to another effect is not. A block's directive
    judged only through the specs that override it is reported when they agree with it.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNUSEDSTRICT})
    out = ds(["./..."])
    assert out.transcript == golden("unused_strict")


def test_unused_default(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which pins the built-in strict mode without a config file.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNUSEDDEFAULTSTRICT})
    out = ds(["./..."])
    assert out.transcript == golden("unused_default")


def test_unused_off(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks rules.unused: off. No directive is reported unused, neither an
    ignore nor a scope directive, and a malformed directive is still reported, since the directive rule has no
    switch.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNUSEDOFF})
    out = ds(["./..."])
    assert out.transcript == golden("unused_off")


def test_unused_strict_shared_default(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks strict under defaults.unexported: shared, where the same private
    field binds and a shared directive on an unexported declaration is the redundant one.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_UNUSEDSTRICTPKG})
    out = ds(["./..."])
    assert out.transcript == golden("unused_strict_shared_default")


def test_symbol_file_name(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks a file whose name yields no namespace, such as ★.go. It is its own
    unit, and a report names the file. The module zip refuses such a name, and go install with it, so the
    fixture lives outside testdata/src and is written to a temporary tree here.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_SYMBOLFILE})
    out = ds(["./..."])
    assert out.transcript == golden("symbol_file_name")


def test_method_on_generated_type(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks a method whose receiver is declared in a generated file, which the
    pass does not read. The analyzer must print nothing here, so the namespaces and declarations that inspect
    reads from the same package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_GENERATEDOWNER})
    out = ds(["./..."])
    assert out.transcript == golden("method_on_generated_type")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("method_on_generated_type_inspect")


def test_line_directive_lineignore(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a //line directive changes nothing about which file a position
    belongs to. A file-level ignore still covers the lines below one, a type below one is still apart from a
    method filed elsewhere, and a file renamed from above its package clause is still the one the pass holds.
    The analyzer must print nothing here, so the namespaces and declarations that inspect reads from the same
    package are pinned too.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_LINEIGNORE})
    out = ds(["./..."])
    assert out.transcript == golden("line_directive_lineignore")
    shape = ds(["inspect", "-format=json", "."])
    assert shape.transcript == golden("line_directive_lineignore_inspect")


def test_line_directive_lineforeign(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a //line directive changes nothing about which file a position
    belongs to. A file-level ignore still covers the lines below one, a type below one is still apart from a
    method filed elsewhere, and a file renamed from above its package clause is still the one the pass holds.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_LINEFOREIGN})
    out = ds(["./..."])
    assert out.transcript == golden("line_directive_lineforeign")


def test_line_directive_lineunseen(ds, workdir):
    """CATCHES: an analyzer whose diagnostics (message text, positions, attached use sites, order or exit status)
    differ on this scenario, which checks that a //line directive changes nothing about which file a position
    belongs to. A file-level ignore still covers the lines below one, a type below one is still apart from a
    method filed elsewhere, and a file renamed from above its package clause is still the one the pass holds.
    """
    write_tree(workdir, {"go.mod": GO_MOD, **SRC_LINEUNSEEN})
    out = ds(["./..."])
    assert out.transcript == golden("line_directive_lineunseen")
