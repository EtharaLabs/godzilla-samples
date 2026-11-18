"""The analyzer's directive, ignore and unused rules, on the repository's own fixtures.

Each fixture is a module of its own here. A test runs the analyzer over ./..., and where the fixture
offers fixes, runs -fix and records every file it changed."""

from conftest import analyze_fixture, assert_golden


FILES_BLOCKIGNORE = {
    '.declscope.yaml': '''# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
''',
    'order.go': '''package blockignore

func orderRun(u *User) int {
	return userA + userC + userG + u.x
}

var _ = orderRun
''',
    'user.go': '''package blockignore

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
''',
}


def test_blockignore(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the blockignore
    fixture. It checks that an ignore directive is judged once per comment, not once per declaration it reaches: one
    on a block, or shared by the names of one spec, is used as soon as any of them needed it, and is reported once
    when none did."""
    out = analyze_fixture(run, workdir, 'blockignore', FILES_BLOCKIGNORE, fix=False)
    assert_golden(out, __file__, 'blockignore')

FILES_BRACEIGNORE = {
    'order.go': '''package braceignore

func orderRun(t *UserT, v *UserV, w *UserW, m *UserM) int {
	return t.x + v.z + w.w + w.v + m.m + userA + userB + userC + userHelper() + userLoose()
}

var _ = orderRun
''',
    'user.go': '''package braceignore

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
''',
}


def test_braceignore(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the braceignore
    fixture. It checks the two placements go/parser attaches to nothing: a trailing comment on the first or last
    line of a multi-line declaration binds to it, and a directive anywhere else after the package clause is reported
    as misplaced rather than silently dropped."""
    out = analyze_fixture(run, workdir, 'braceignore', FILES_BRACEIGNORE, fix=False)
    assert_golden(out, __file__, 'braceignore')

FILES_DIRECTIVES = {
    '.declscope.yaml': '''rules:
  unused: loose
''',
    'order.go': '''package directives

func orderRun() int {
	return userExplicitlyShared() + userNotReallyShared() + userIgnoredLeak() +
		userTrailing() + userSharedA + userPrivateB + userSharedC + userPrivateD
}

var _ = orderRun
''',
    'report.go': '''//declscope:namespace user

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
''',
    'user.go': '''package directives

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
''',
}


def test_directives(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the directives
    fixture. It checks every malformed, unknown, conflicting or misplaced directive reported by the directive rule,
    and having no effect."""
    out = analyze_fixture(run, workdir, 'directives', FILES_DIRECTIVES, fix=False)
    assert_golden(out, __file__, 'directives')

FILES_DUPLICATEDIRECTIVE = {
    'order.go': '''package duplicatedirective

func orderRun() int {
	return sharedHelper() + userShared() + UserPrivate() + userIgnored() + userTrailing() + userWider()
}

var _ = orderRun
''',
    'shared.go': '''// A file-level scope written twice is reported at the second. The first still
// shares the file, so the use from order.go is not reported.
//
//declscope:shared
//declscope:shared // want `duplicate declscope:shared directive`

package duplicatedirective

func sharedHelper() int { return 1 }
''',
    'user.go': '''package duplicatedirective

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
''',
}


def test_duplicatedirective(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the duplicatedirective
    fixture. It checks that a scope directive or an ignore repeated on one declaration or one file is reported at
    the second, and that a repeated ignore is not also reported unused."""
    out = analyze_fixture(run, workdir, 'duplicatedirective', FILES_DUPLICATEDIRECTIVE, fix=False)
    assert_golden(out, __file__, 'duplicatedirective')

FILES_FILEIGNORE = {
    '.declscope.yaml': '''# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
''',
    'clean.go': '''//declscope:ignore qualify // want `unused file-level //declscope:ignore qualify`

package fileignore

// The name carries its namespace, so the directive silences nothing.
func cleanOK() int { return 4 }

var _ = cleanOK
''',
    'order.go': '''package fileignore

func orderRun() int { return helper2() + thing() }

var _ = orderRun
''',
    'quiet.go': '''//declscope:ignore

package fileignore

// A bare file-level ignore silences every rule, reach included.
func thing() int { return 3 }
''',
    'util.go': '''//declscope:ignore qualify

package fileignore

// The file stands outside the naming rule, so neither of these is asked to
// carry the "util" prefix.
func helper() int { return 1 }

// The boundary still holds: only qualify was silenced.
func helper2() int { return 2 } // want `func helper2 is private to namespace "util", but is used from namespace "order"`

var _ = helper
''',
}


def test_fileignore(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the fileignore
    fixture. It checks that an ignore directive before the package clause applies to every declaration in the file,
    and is reported when it silences nothing."""
    out = analyze_fixture(run, workdir, 'fileignore', FILES_FILEIGNORE, fix=False, survey=True)
    assert_golden(out, __file__, 'fileignore')

FILES_FILEIGNORESCOPE = {
    '.declscope.yaml': '''# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
''',
    'order.go': '''package fileignorescope

// A second namespace, so the naming rule applies at all.
func orderRun() int { return 3 }

var _ = orderRun
''',
    'util.go': '''//declscope:ignore qualify

package fileignorescope

// This file stands outside the naming rule.
func helper() int { return 1 }

var _ = helper
''',
    'util_extra.go': '''//declscope:namespace util

package fileignorescope

// The same namespace as util.go, but a file-level ignore belongs to the file
// that carries it, so this one is still asked for its prefix.
func extra() int { return 2 } // want `func extra does not carry namespace "util" anywhere in its name; rename it to utilExtra, or to another name that carries "util"`

var _ = extra
''',
}


def test_fileignorescope(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the fileignorescope
    fixture. It checks that a file-level ignore covers only the file carrying it, not every file sharing its
    namespace."""
    out = analyze_fixture(run, workdir, 'fileignorescope', FILES_FILEIGNORESCOPE, fix=False)
    assert_golden(out, __file__, 'fileignorescope')

FILES_IGNOREDIRECTIVE = {
    '.declscope.yaml': '''# Focused on which ignore answers a report of the directive rule. The naming
# rule is stated off so that the ignores here silence nothing by accident: an
# ignore that did silence something would not be judged unused.
rules:
  naming:
    qualify: never
  unused: loose
''',
    'decl.go': '''package ignoredirective

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
''',
    'file.go': '''//declscope:ignore directive

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
''',
}


def test_ignoredirective(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignoredirective
    fixture. It checks which ignore answers a report of the directive rule. Such a report hangs on a comment rather
    than on a declaration, so the file level answers one written where no declaration is. An ignore naming directive
    answers no unused report, and is itself reported as unused when that is all it was written for."""
    out = analyze_fixture(run, workdir, 'ignoredirective', FILES_IGNOREDIRECTIVE, fix=False)
    assert_golden(out, __file__, 'ignoredirective')

FILES_IGNOREFILTER = {
    'a.go': '''//declscope:ignore filter // want `unused file-level //declscope:ignore filter`

package ignorefilter

// The filter rule reports a chain of config files, and the package it reports
// had nothing read from it, so no ignore there is ever read. An ignore naming
// the rule silences nothing, and the unused rule reports it like any other.
func helper() int { return 1 }

var _ = helper()
''',
}


def test_ignorefilter(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignorefilter
    fixture. It checks that an ignore naming the filter rule silences nothing. Fixing filter.only in the config
    chain is what resolves that report, so the ignore is reported as unused."""
    out = analyze_fixture(run, workdir, 'ignorefilter', FILES_IGNOREFILTER, fix=False)
    assert_golden(out, __file__, 'ignorefilter')

FILES_IGNOREMODULEWIDE = {
    '.declscope.yaml': '''# Focused on ignores naming overexported, which only declscope shrink reports.
# The naming rule is stated off so that nothing else is silenced by accident.
rules:
  naming:
    qualify: never
''',
    'a.go': '''package ignoremodulewide

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
''',
    'b.go': '''// A file-level ignore covering unused, in a file holding an ignore that names
// overexported, may be answering that ignore's unused report in declscope
// shrink, so it is not called unused here.
//
//declscope:ignore unused

package ignoremodulewide

//declscope:ignore overexported
func FileAnswered() int { return 5 }
''',
    'c.go': '''// The same file-level ignore in a file with no such ignore answers nothing
// declscope shrink reports, and the analyzer judges it as always.
//
//declscope:ignore unused // want `unused file-level //declscope:ignore unused`

package ignoremodulewide

func Plain() int { return 6 }
''',
}


def test_ignoremodulewide(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignoremodulewide
    fixture. It checks that an ignore naming a rule only declscope shrink reports is never judged unused here, and
    that a bare ignore does not reach such a rule, so the analyzer still judges it."""
    out = analyze_fixture(run, workdir, 'ignoremodulewide', FILES_IGNOREMODULEWIDE, fix=False)
    assert_golden(out, __file__, 'ignoremodulewide')

FILES_IGNORESCOPE = {
    '.declscope.yaml': '''# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
''',
    'order.go': '''package ignorescope

func orderRun() int {
	return helper() + helper2() + userKept() + userTypo() + helper3() + userBlockA + userBlockB
}

var _ = orderRun
''',
    'user.go': r'''package ignorescope

// Silencing one rule leaves the rest in force: the missing prefix is ignored,
// the boundary crossing is not.
//
//declscope:ignore qualify
func helper() int { return 1 } // want `func helper is private to namespace "user", but is used from namespace "order"`

// Silencing everything.
//
//declscope:ignore
func helper2() int { return 2 }

// Two directives, each judged on its own: the crossing is silenced and so the
// first is used, while qualify never fires on a name that carries its
// namespace, so the second is reported.
//
//declscope:ignore boundary
//declscope:ignore qualify // want `unused //declscope:ignore qualify on userKept`
func userKept() int { return 3 }

// An unparseable directive silences nothing.
//
//declscope:ignore bogus // want `unknown rule "bogus" in declscope:ignore \(want one of boundary, qualify, surplus, unused, directive, filter, overexported\)`
func userTypo() int { return 4 } // want `func userTypo is private to namespace "user", but is used from namespace "order"`

//declscope:ignore boundary,qualify
func helper3() int { return 5 }

// Ignores accumulate across a block and its specs rather than the spec's
// replacing the block's: the bare ignore on the block keeps silencing boundary
// for userBlockB, and only its own qualify — needless on a prefixed name — is
// unused.
//
//declscope:ignore
var (
	userBlockA = 6
	//declscope:ignore qualify // want `unused //declscope:ignore qualify on userBlockB`
	userBlockB = 7
)
''',
}


def test_ignorescope(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignorescope
    fixture. It checks that an ignore directive can name the rules it silences, and that each directive is reported
    unused on its own."""
    out = analyze_fixture(run, workdir, 'ignorescope', FILES_IGNORESCOPE, fix=False, survey=True)
    assert_golden(out, __file__, 'ignorescope')

FILES_IGNOREUNSEEN = {
    'a.go': '''package ignoreunseen

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
''',
    'filelevel.go': '''// A file-level ignore reaches every declaration of its file, and tagged.go
// crosses into one of them.
//
//declscope:ignore boundary

package ignoreunseen

func filelevelHelper() int { return 5 }
''',
    'tagged.go': '''//go:build never

package ignoreunseen

// This file is left out of the build. It crosses into a.go's declarations.
func Tagged() int { return aHelper() + aBare() + aQualify() + filelevelHelper() }

// Unkeyed literals fill the fields by position.
func Positional() (aPoint, aAlias) { return aPoint{1}, aAlias{2} }
''',
}


def test_ignoreunseen(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignoreunseen
    fixture. It checks that an ignore of boundary is not unused when a file the build excluded names the declaration
    it reaches: that file may cross into it in a configuration that reads it. An ignore no unseen file gives a job,
    or one of a rule judged on the declaration, is still unused."""
    out = analyze_fixture(run, workdir, 'ignoreunseen', FILES_IGNOREUNSEEN, fix=False)
    assert_golden(out, __file__, 'ignoreunseen')

FILES_IGNOREUNSEENTEST = {
    'a.go': '''package ignoreunseentest

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
''',
    'b_tagged_test.go': '''//go:build declscope_never

package ignoreunseentest

// This test file is left out of the build. It crosses into a.go.
var _ = aHelper
''',
}


def test_ignoreunseentest(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignoreunseentest
    fixture. It checks the same where the excluded file is the package's only test file. No variant sees it, so the
    non-test variant reads it for its names and still reports an ignore it gives no job."""
    out = analyze_fixture(run, workdir, 'ignoreunseentest', FILES_IGNOREUNSEENTEST, fix=False)
    assert_golden(out, __file__, 'ignoreunseentest')

FILES_IGNOREUNUSED = {
    '.declscope.yaml': '''# Focused on which ignore answers the unused rule's report on another ignore.
# The naming rule is stated off so that the ignores here silence nothing by
# accident: an ignore that did silence something would not be judged unused.
rules:
  naming:
    qualify: never
''',
    'decl.go': '''package ignoreunused

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
''',
    'fileanswer.go': '''//declscope:ignore unused
//declscope:shared

package ignoreunused

// The file-level ignore above answers every unused report in the file: the
// file's own scope directive, which nothing takes since everything here is
// exported, and the declaration's ignore below, which silences nothing.
// Answering them is its use, so nothing in this file is reported.

//declscope:ignore boundary
func FileAnswered() int { return 1 }

var _ = FileAnswered()
''',
    'filebare.go': '''//declscope:ignore // want `unused file-level //declscope:ignore`

package ignoreunused

// A bare file-level ignore covers every rule, the unused rule included, and
// still never its own report. Nothing here needs it, so it is reported.
func fileBare() int { return 1 }

var _ = fileBare()
''',
    'filepair.go': '''//declscope:ignore
//declscope:ignore boundary

package ignoreunused

// At the file level a bare ignore answers another's report, since it stands
// every rule down for the file. The second ignore silences nothing, the first
// answers its report, and neither is reported.
func filePair() int { return 1 }

var _ = filePair()
''',
    'fileself.go': '''//declscope:ignore unused // want `unused file-level //declscope:ignore unused`

package ignoreunused

// A file-level ignore naming the unused rule answers the reports of the file,
// but not its own. Nothing else here needs it, so it is reported.
func fileSelf() int { return 1 }

var _ = fileSelf()
''',
}


def test_ignoreunused(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ignoreunused
    fixture. It checks which ignore answers the unused rule's report on another ignore: one beside it naming unused,
    or one at the file level, bare or named. A bare one beside it does not, and no ignore answers its own report,
    whatever it names."""
    out = analyze_fixture(run, workdir, 'ignoreunused', FILES_IGNOREUNUSED, fix=False)
    assert_golden(out, __file__, 'ignoreunused')

FILES_LINEAFTERCOMMENT = {
    'order.go': '''package lineaftercomment

func orderRun(t UserT[int]) int {
	return userHelper(1) + userOne() + t.x + userA
}

var _ = orderRun
''',
    'user.go': '''package lineaftercomment

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
''',
}


def test_lineaftercomment(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the lineaftercomment
    fixture. It checks that a directive trailing a declaration's first or last line binds even when an earlier
    comment, one that is not a directive, starts on that line too."""
    out = analyze_fixture(run, workdir, 'lineaftercomment', FILES_LINEAFTERCOMMENT, fix=False, survey=True)
    assert_golden(out, __file__, 'lineaftercomment')

FILES_LINEIGNORE = {
    'x.go': '''//declscope:ignore

package lineignore

// A //line directive renames the positions below it. The file-level ignore
// above still covers them, because it is about the file on disk.
//
//line x.tmpl:1
//declscope:bogus
func run() {}
''',
}


def test_lineignore(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the lineignore
    fixture. It checks that a //line directive changes nothing about which file a position belongs to. A file-level
    ignore still covers the lines below one, a type below one is still apart from a method filed elsewhere, and a
    file renamed from above its package clause is still the one the pass holds."""
    out = analyze_fixture(run, workdir, 'lineignore', FILES_LINEIGNORE, fix=False, survey=True)
    assert_golden(out, __file__, 'lineignore')

FILES_TESTONLYIGNORE = {
    'order_test.go': '''package testonlyignore

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
''',
    'user.go': '''package testonlyignore

// userHelper is used from order_test.go, in namespace "order", and from
// nowhere else. Only the test variant of the package sees that reference, so
// only it can tell whether the directive did anything; the ordinary variant,
// which cannot see order_test.go, must not call it unused. Neither variant
// reports it: the test variant because it was used, the ordinary one because
// it defers to the test variant.
//
//declscope:ignore boundary
func userHelper() int { return 1 }
''',
}


def test_testonlyignore(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the testonlyignore
    fixture. It checks that a directive needed only by a reference in a _test.go file is not reported unused by the
    ordinary variant of the package, which cannot see that reference. Only the test variant, which sees every file,
    judges, and a directive in a test file shows that it does."""
    out = analyze_fixture(run, workdir, 'testonlyignore', FILES_TESTONLYIGNORE, fix=False)
    assert_golden(out, __file__, 'testonlyignore')

FILES_TYPEIGNORE = {
    '.declscope.yaml': '''# The ignore accounting under test needs the naming rule in force: whether an
# //declscope:ignore qualify is used or unused is decided by whether qualify
# could have fired, and by default it never does.
rules:
  naming:
    qualify: ondemand
''',
    'order.go': '''package typeignore

func orderRun(u *User, o *Open, c *Closed) string {
	u.normalize()
	return u.name + string(rune(u.id)) + o.secret + c.hidden
}

var _ = orderRun
''',
    'user.go': '''package typeignore

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
''',
    'user_methods.go': '''//declscope:namespace user

package typeignore

// The directive on User does not reach here: a method needs its own. Without
// one this is reported, which is what pins the type's ignore to what the type
// contains.
func (u *User) normalize() { u.name = "x" } // want `method User.normalize is private to namespace "user", but is used from namespace "order"`
''',
}


def test_typeignore(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the typeignore
    fixture. It checks that a member inherits the ignore directives written on the type that owns it, wherever the
    member is declared, and that a directive used up only by a member still counts as used."""
    out = analyze_fixture(run, workdir, 'typeignore', FILES_TYPEIGNORE, fix=False, survey=True)
    assert_golden(out, __file__, 'typeignore')

FILES_UNUSEDDEFAULTSTRICT = {
    'user.go': '''package unuseddefaultstrict

//declscope:private // want `unused //declscope:private on userLocal: it already has private scope`
func userLocal() {}
''',
}


def test_unuseddefaultstrict(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the
    unuseddefaultstrict fixture. It pins the built-in strict mode without a config file."""
    out = analyze_fixture(run, workdir, 'unuseddefaultstrict', FILES_UNUSEDDEFAULTSTRICT, fix=False)
    assert_golden(out, __file__, 'unuseddefaultstrict')

FILES_UNUSEDLOOSE = {
    '.declscope.yaml': '''rules:
  unused: loose
''',
    'a.go': '''package unusedloose

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
''',
    'b.go': '''//declscope:private // want `unused file-level //declscope:private$`

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
''',
    'c.go': '''package unusedloose

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
''',
    'd.go': '''package unusedloose

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
''',
}


def test_unusedloose(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unusedloose
    fixture. It checks rules.unused: loose: a scope directive naming the scope defaults.unexported gives today is
    kept, since another configuration could make it bind, and one restating an enclosing directive is reported as
    before."""
    out = analyze_fixture(run, workdir, 'unusedloose', FILES_UNUSEDLOOSE, fix=False)
    assert_golden(out, __file__, 'unusedloose')

FILES_UNUSEDOFF = {
    '.declscope.yaml': '''rules:
  unused: off
''',
    'a.go': '''package unusedoff

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
''',
    'b.go': '''//declscope:ignore

package unusedoff

// A file-level ignore that silences nothing is not reported either.
func bQuiet() int { return 1 }

var _ = bQuiet()
''',
}


def test_unusedoff(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unusedoff fixture.
    It checks rules.unused: off. No directive is reported unused, neither an ignore nor a scope directive, and a
    malformed directive is still reported, since the directive rule has no switch."""
    out = analyze_fixture(run, workdir, 'unusedoff', FILES_UNUSEDOFF, fix=False)
    assert_golden(out, __file__, 'unusedoff')

FILES_UNUSEDSCOPE = {
    '.declscope.yaml': '''# Focused on the unused rule: the naming rule would otherwise land on the
# same lines and obscure what this package is for. The surplus rule is off for
# the same reason, since it reports the block directive kept here on purpose.
rules:
  naming:
    qualify: never
  surplus: off
  unused: loose
''',
    'a.go': '''package unusedscope

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
''',
    'b.go': '''package unusedscope

func bUse(e *Entry) string { return e.key }

var _ = bUse
''',
    'c.go': '''//declscope:shared // want `unused file-level //declscope:shared$`

package unusedscope

// A file-level scope is the default for what the file declares, and every
// declaration here is exported: an exported declaration is shared
// under every configuration, so nothing below takes its scope from the line
// above. The file-level report names no declaration, since the directive was
// written about the file rather than about any one of them.
func Widget() int { return 1 }

type Crate struct{ Name string }
''',
    'd.go': '''package unusedscope

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
''',
    'e.go': '''//declscope:private // want `unused file-level //declscope:private$`

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
''',
}


def test_unusedscope(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unusedscope
    fixture. It checks the structural test: a scope directive that binds nothing is reported, an exported type with
    an unexported field still binds one, and restating the scope already in force is not reported at all. The two
    ways a block's directive can reach nothing — every spec overriding it, and nothing checked being able to carry
    it — are reported apart."""
    out = analyze_fixture(run, workdir, 'unusedscope', FILES_UNUSEDSCOPE, fix=False)
    assert_golden(out, __file__, 'unusedscope')

FILES_UNUSEDSTRICT = {
    '.declscope.yaml': '''rules:
  unused: strict
  # surplus would report the shared directives kept here as widening for
  # nothing; this package is about the unused rule alone.
  surplus: off
''',
    'a.go': '''package unusedstrict

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
''',
    'b.go': '''package unusedstrict

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
''',
    'c.go': '''//declscope:private // want `unused file-level //declscope:private: every declaration it reaches already has private scope`

package unusedstrict

// A declaration restating the file's directive is reported, and so is the
// file's, which restates the default for everything here.
//
//declscope:private // want `unused //declscope:private on cFile: it already has private scope`
func cFile() int { return 1 }

func cOther() int { return 2 }

var _ = cFile() + cOther()
''',
    'd.go': '''package unusedstrict

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
''',
    'e.go': '''package unusedstrict

var _ = dShared()
''',
    'f.go': '''//declscope:private // want `unused file-level //declscope:private: every declaration it reaches already has private scope`

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
''',
    'g.go': '''package unusedstrict

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
''',
    'h.go': '''//declscope:shared

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
''',
    'i.go': '''package unusedstrict

// A type that declares no name is reached through its fields alone. Its
// private restates the default, and its only field states package, so the
// report says the field states its own scope.
//
//declscope:private // want `unused //declscope:private: every declaration it reaches states its own scope`
type _ struct {
	//declscope:shared
	x int
}
''',
    'j.go': '''package unusedstrict

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
''',
}


def test_unusedstrict(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unusedstrict
    fixture. It checks rules.unused: strict under the private default. A directive naming the scope its declarations
    would have without it is reported, at the field, type, block, spec and file levels, and one that widens,
    narrows, or is overridden to another effect is not. A block's directive judged only through the specs that
    override it is reported when they agree with it."""
    out = analyze_fixture(run, workdir, 'unusedstrict', FILES_UNUSEDSTRICT, fix=False)
    assert_golden(out, __file__, 'unusedstrict')

FILES_UNUSEDSTRICTPKG = {
    '.declscope.yaml': '''defaults:
  unexported: shared
rules:
  unused: strict
  surplus: off
''',
    'a.go': '''package unusedstrictpkg

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
''',
    'b.go': '''//declscope:shared // want `unused file-level //declscope:shared: every declaration it reaches takes a nearer directive's scope$`

package unusedstrictpkg

// The file's package restates the default, and its only declaration states
// private. The report must not say that bNarrow has shared scope.
//
//declscope:private
func bNarrow() int { return 1 }

var _ = bNarrow()
''',
    'c.go': '''//declscope:shared // want `unused file-level //declscope:shared: every declaration it reaches takes a nearer directive's scope or already has shared scope`

package unusedstrictpkg

// One declaration takes the file's package, which the default gives anyway,
// and one states private. The report names both kinds.
func cWide() int { return 1 }

//declscope:private
func cNarrow() int { return 2 }

var _ = cWide() + cNarrow()
''',
}


def test_unusedstrictpkg(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unusedstrictpkg
    fixture. It checks strict under defaults.unexported: shared, where the same private field binds and a shared
    directive on an unexported declaration is the redundant one."""
    out = analyze_fixture(run, workdir, 'unusedstrictpkg', FILES_UNUSEDSTRICTPKG, fix=False)
    assert_golden(out, __file__, 'unusedstrictpkg')

FILES_UNUSEDSTRICTTESTS = {
    '.declscope.yaml': '''rules:
  unused: strict
''',
    'order_test.go': '''package unusedstricttests

import "testing"

func TestOrder(t *testing.T) {
	if userShared() != 1 {
		t.Fatal("userShared")
	}
}
''',
    'user.go': '''package unusedstricttests

// userShared restates the default. order_test.go uses it from another
// namespace, which only the test variant sees.
//
//declscope:private
func userShared() int { return 1 }
''',
}


def test_unusedstricttests(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unusedstricttests
    fixture. It checks that the ordinary variant of a package with in-package tests offers no deletion. Only the
    test variant sees order_test.go use userShared from another namespace, and it withholds the fix, since the
    boundary report names the directive. The driver applies the fixes of both variants, so an offer from the
    ordinary one would be applied anyway. The boundary report exists in the test variant alone, and a want in
    user.go must hold in both, so the diagnostics are read here directly."""
    out = analyze_fixture(run, workdir, 'unusedstricttests', FILES_UNUSEDSTRICTTESTS, fix=False)
    assert_golden(out, __file__, 'unusedstricttests')
