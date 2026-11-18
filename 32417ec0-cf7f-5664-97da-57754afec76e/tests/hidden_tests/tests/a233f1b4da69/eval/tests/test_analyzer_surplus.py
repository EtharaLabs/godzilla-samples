"""The analyzer's surplus rule, on the repository's own surplus fixtures.

Each fixture is a module of its own here. A test runs the analyzer over ./..., and where the fixture
offers fixes, runs -fix and records every file it changed."""

from conftest import analyze_fixture, assert_golden


FILES_SURPLUS = {
    'order.go': '''// The file's directive widens everything the file declares, and is judged as
// the one comment it is.
//
//declscope:shared // want `the file's //declscope:shared: no use from another namespace is visible to declscope`

package surplus

func orderQuiet() int { return 5 }

var _ = orderQuiet
''',
    'user.go': '''package surplus

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
''',
}


def test_surplus(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplus fixture.
    It checks the surplus rule's reporting shapes: one report per physical //declscope:shared, listing every
    declaration that takes its scope from it, at every level the directive can be written. The quiet cases carry as
    much: an ignore silences it, and an exported name anywhere in the comment's reach keeps the whole comment."""
    out = analyze_fixture(run, workdir, 'surplus', FILES_SURPLUS, fix=False)
    assert_golden(out, __file__, 'surplus')

FILES_SURPLUSALLOWED = {
    '.declscope.yaml': '''# surplus: off turns the rule off. The directive below is the one
# surplusdefault reports.
rules:
  surplus: off
''',
    'user.go': '''package surplusallowed

// Nothing is reported: the rule is off.
//
//declscope:shared
func userQuiet() int { return 1 }
''',
}


def test_surplusallowed(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusallowed
    fixture. It checks the behaviour the surplusallowed fixture pins."""
    out = analyze_fixture(run, workdir, 'surplusallowed', FILES_SURPLUSALLOWED, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusallowed')

FILES_SURPLUSBASELINED = {
    '.declscope-baseline.yaml': '''packages:
  surplusbaselined:
    surplus:
      user:
        - userOld
''',
    'user.go': '''package surplusbaselined

// userOld is recorded in the baseline, so it stays quiet.
//
//declscope:shared
func userOld() int { return 1 }

// userNew is not, so it is reported.
//
//declscope:shared // want `//declscope:shared on userNew: no use from another namespace is visible to declscope`
func userNew() int { return 2 }
''',
}


def test_surplusbaselined(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusbaselined
    fixture. It checks that a recorded surplus finding is suppressed while a new one is still reported, through the
    same lookup as every rule."""
    out = analyze_fixture(run, workdir, 'surplusbaselined', FILES_SURPLUSBASELINED, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusbaselined')

FILES_SURPLUSCARRIER = {
    'alias.go': '''package surpluscarrier

type impl struct{}

//declscope:shared
func (impl) fire() {}

// Public is an exported alias: the method set travels under its name.
type Public = impl
''',
    'base.go': '''package surpluscarrier

// Base is exported: an importer can embed it, inherit run, and complete an
// interface satisfaction this analysis never sees.
type Base struct{}

//declscope:shared
func (Base) run() {}
''',
    'sealed.go': '''package surpluscarrier

// Sealed is the sealed-interface idiom: the requirement travels with the
// exported interface, and an importer that embeds it passes it on.
type Sealed interface {
	Do()
	//declscope:shared
	seal()
}
''',
    'solo.go': '''package surpluscarrier

// solo is unexported, so nothing carries quiet out, and the directive is
// reported.
type solo struct{}

//declscope:shared // want `//declscope:shared on solo.quiet: no use from another namespace is visible to declscope`
func (solo) quiet() {}
''',
    'wrap.go': '''package surpluscarrier

type hidden struct{}

//declscope:shared
func (hidden) tick() {}

// Wrapper carries tick out of the package through the embedding.
type Wrapper struct{ hidden }
''',
}


def test_surpluscarrier(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surpluscarrier
    fixture. It checks the carrier suppressor: an exported type — or an exported alias, or an exported interface —
    carries an unexported method out of the package, where an importer can complete a satisfaction the analysis
    never sees. Only a method nothing exported carries is reported."""
    out = analyze_fixture(run, workdir, 'surpluscarrier', FILES_SURPLUSCARRIER, fix=False)
    assert_golden(out, __file__, 'surpluscarrier')

FILES_SURPLUSCONVERT = {
    'model.go': '''package surplusconvert

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
''',
    'snapshot.go': '''package surplusconvert

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
''',
}


def test_surplusconvert(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusconvert
    fixture. It checks that a struct conversion counts as reach: it pairs every field by name and spells none of
    them, so a field whose directive holds the conversion together must stay unreported."""
    out = analyze_fixture(run, workdir, 'surplusconvert', FILES_SURPLUSCONVERT, fix=False)
    assert_golden(out, __file__, 'surplusconvert')

FILES_SURPLUSDEFAULT = {
    'user.go': '''package surplusdefault

// The rule is on with no configuration.
//
//declscope:shared // want `//declscope:shared on userQuiet: no use from another namespace is visible to declscope`
func userQuiet() int { return 1 }
''',
}


def test_surplusdefault(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusdefault
    fixture. It pins the built-in default: with no config, the rule reports a directive nothing needs."""
    out = analyze_fixture(run, workdir, 'surplusdefault', FILES_SURPLUSDEFAULT, fix=False)
    assert_golden(out, __file__, 'surplusdefault')

FILES_SURPLUSDEFAULTSTRICT = {
    'order.go': '''package surplusdefaultstrict

var _ = userShared()
''',
    'user.go': '''//declscope:shared

package surplusdefaultstrict

func userShared() int { return 1 }

func userLocal() int { return 2 } // want `func userLocal takes shared scope from the file's //declscope:shared, but no use from another namespace is visible to declscope`
''',
}


def test_surplusdefaultstrict(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the
    surplusdefaultstrict fixture. It pins the built-in default: with no config, the rule reports a directive nothing
    needs."""
    out = analyze_fixture(run, workdir, 'surplusdefaultstrict', FILES_SURPLUSDEFAULTSTRICT, fix=False)
    assert_golden(out, __file__, 'surplusdefaultstrict')

FILES_SURPLUSEXCLUDED = {
    'order_tagged.go': '''//go:build never

package surplusexcluded

var _ = userHelper()
''',
    'user.go': '''package surplusexcluded

// The only use is in order_tagged.go, which the build excludes. That file is
// of this package, so the rule switches off rather than read the absence as
// evidence. The silence is the assertion.
//
//declscope:shared
func userHelper() int { return 1 }
''',
}


def test_surplusexcluded(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusexcluded
    fixture. It checks that a build-excluded file of the package itself still switches the rule off. It is read for
    names only, and a name is not enough to rule out a use. The silence is the assertion."""
    out = analyze_fixture(run, workdir, 'surplusexcluded', FILES_SURPLUSEXCLUDED, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusexcluded')

FILES_SURPLUSGENERATOR = {
    'gen.go': '''//go:build ignore

package main

func userHelper() int { return 2 }

func main() { _ = userHelper() }
''',
    'user.go': '''package surplusgenerator

// gen.go is a generator of another package, which the build excludes. It
// declares a userHelper of its own, not this one, so the directive is still
// reported.
//
//declscope:shared // want `//declscope:shared on userHelper: no use from another namespace is visible to declscope`
func userHelper() int { return 1 }
''',
}


def test_surplusgenerator(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusgenerator
    fixture. It checks that a build-excluded file of another package, the //go:build ignore generator declaring
    package main, does not switch the rule off: it can name nothing of this package
    (https://github.com/mpyw/declscope/issues/253)."""
    out = analyze_fixture(run, workdir, 'surplusgenerator', FILES_SURPLUSGENERATOR, fix=False)
    assert_golden(out, __file__, 'surplusgenerator')

FILES_SURPLUSLINKNAME = {
    'user.go': '''package surpluslinkname

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
''',
}


def test_surpluslinkname(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surpluslinkname
    fixture. It checks the linkname suppressor: //go:linkname and //export name a declaration as text, from code the
    analysis does not read."""
    out = analyze_fixture(run, workdir, 'surpluslinkname', FILES_SURPLUSLINKNAME, fix=False)
    assert_golden(out, __file__, 'surpluslinkname')

FILES_SURPLUSLOOSE = {
    '.declscope.yaml': '''rules:
  surplus: loose
''',
    'helper.go': '''// helperShared is called from order.go, so the directive is in use, and under
// loose, that is all the rule asks. helperLocal is not reported;
// strict is what judges it on its own.
//
//declscope:shared

package surplusloose

func helperShared() int { return helperLocal() }

func helperLocal() int { return 1 }
''',
    'order.go': '''package surplusloose

func orderRun() int { return helperShared() }

var _ = orderRun
''',
}


def test_surplusloose(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusloose
    fixture. It checks the loose mode: a directive in use says nothing about the declarations under it that nothing
    outside reaches."""
    out = analyze_fixture(run, workdir, 'surplusloose', FILES_SURPLUSLOOSE, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusloose')

FILES_SURPLUSOPAQUE = {
    'gen.go': '''// Code generated by a tool. DO NOT EDIT.

package surplusopaque

func genUse() int { return userMagic() }

var _ = genUse
''',
    'user.go': '''package surplusopaque

// The only use is in gen.go, which the analysis excludes as a reference site.
// The package holds a source the rule cannot read, so the rule switches off
// rather than read the absence as evidence.
//
//declscope:shared
func userMagic() int { return 7 }
''',
}


def test_surplusopaque(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusopaque
    fixture. It checks the opaque-source suppressor: a package holding a generated file has reference sites the
    analysis excludes, so the rule switches off for the package rather than read the absence as evidence. The
    silence is the assertion."""
    out = analyze_fixture(run, workdir, 'surplusopaque', FILES_SURPLUSOPAQUE, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusopaque')

FILES_SURPLUSSATISFIES = {
    'box.go': '''package surplussatisfies

// The type's directive reaches v too; both are spelled from use.go, which is
// what keeps this comment. Only get is reached through the contract alone.
//
//declscope:shared
type box[T any] struct{ v T }

//declscope:shared
func (b box[T]) get() T { return b.v }
''',
    'closer.go': '''package surplussatisfies

//declscope:shared
type closer struct{}

//declscope:shared
func (closer) close() string { return "c" }
''',
    'inner.go': '''package surplussatisfies

//declscope:shared
type inner struct{}

//declscope:shared
func (*inner) run() {}
''',
    'myint.go': '''package surplussatisfies

//declscope:shared
type myInt int

//declscope:shared
func (myInt) str() string { return "n" }
''',
    'reader.go': '''package surplussatisfies

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
''',
    'use.go': '''package surplussatisfies

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
''',
}


def test_surplussatisfies(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplussatisfies
    fixture. It checks the interface suppressor: a method reached only through a contract stays quiet, including
    through an anonymous struct, a function-local type, an instantiated generic type, a promoted pointer-receiver
    method, an anonymous interface in a type assertion, and a constraint carrying a type term. A method in no
    contract is still reported."""
    out = analyze_fixture(run, workdir, 'surplussatisfies', FILES_SURPLUSSATISFIES, fix=False)
    assert_golden(out, __file__, 'surplussatisfies')

FILES_SURPLUSSATISFIESPAIRS = {
    'brake.go': '''package surplussatisfiespairs

//declscope:shared
type brake struct{}

//declscope:shared
func (brake) stop() {}
''',
    'cell.go': '''package surplussatisfiespairs

//declscope:shared
type cell[T any] struct{}

//declscope:shared
func (cell[T]) peek() (v T) { return v }

//declscope:shared
func (*cell[T]) poke(T) {}
''',
    'clock.go': '''package surplussatisfiespairs

//declscope:shared
type clock struct{}

//declscope:shared
func (clock) tick() {}

//declscope:shared
func (clock) tock() {}
''',
    'engine.go': '''package surplussatisfiespairs

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
''',
    'handler.go': '''package surplussatisfiespairs

// A named function type has methods although its underlying type cannot.
//
//declscope:shared
type handlerFunc func() string

//declscope:shared
func (f handlerFunc) serve() string { return f() }
''',
    'ticket.go': '''package surplussatisfiespairs

//declscope:shared
type ticket struct{}

//declscope:shared
func (ticket) fetch() int { return 1 }
''',
    'use.go': '''package surplussatisfiespairs

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
''',
    'valve.go': '''package surplussatisfiespairs

// shut is a function, and shutter in use.go asks for a method of that name.
// A contract reaches methods alone, so no contract reaches the function, and
// its directive is reported.
//
//declscope:shared // want `//declscope:shared on shut: no use from another namespace is visible to declscope`
func shut() {}

var _ = shut
''',
}


def test_surplussatisfiespairs(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the
    surplussatisfiespairs fixture. It checks the shapes that decide which pairs of an interface and a type are
    tested for satisfaction: a method promoted through an embedded pointer, a method of an instantiated generic type
    with a pointer receiver, an interface embedding another, a requirement asked for only through an embedded
    instantiation, and a named function type. Each method stays quiet, and one in no contract is still reported."""
    out = analyze_fixture(run, workdir, 'surplussatisfiespairs', FILES_SURPLUSSATISFIESPAIRS, fix=False)
    assert_golden(out, __file__, 'surplussatisfiespairs')

FILES_SURPLUSSTRICT = {
    '.declscope.yaml': '''# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
''',
    'file.go': '''// A file-level directive widens every field the file declares, and the report
// names it.
//
//declscope:shared

package surplusstrict

type fileCursor struct {
	pos  int
	seen int // want `field fileCursor.seen takes shared scope from the file's //declscope:shared, but no use from another namespace is visible to declscope`
}

func fileAdvance(c *fileCursor) { c.seen++ }
''',
    'helper.go': '''// The file's directive widens everything it declares. helperShared is called
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
''',
    'order.go': '''package surplusstrict

func orderRun(a userAccount, p userPair, m userMixed, n userNeedless, q userQuiet, h userHushed) int {
	var s userSaver
	_ = s
	return a.id + len(a.Name) + p.shared + m.top + n.read + len([]any{q, h})
}

var _ = orderRun

func orderHelpers() int { return helperShared() + helperC + helperMakePair().x + blockUsed }

var _ = orderHelpers
''',
    'reader.go': '''package surplusstrict

func readerUse(c *fileCursor) int {
	fileAdvance(c)
	return c.pos
}

var _ = readerUse
''',
    'user.go': '''package surplusstrict

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
''',
}


def test_surplusstrict(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusstrict
    fixture. It checks strict's reporting shapes, at every level a directive encloses a declaration: a field under
    its type's directive, a declaration under its file's, a spec under its block's. Each is reported one per name
    when nothing outside reaches it, while its directive is otherwise in use. An entry holding a name that is read
    outside is not; neither is an exported declaration, one stating its own scope, an embedded field or a directive
    loose already reports. A type is reported with the members it would narrow, and not when one of them is reached.
    An ignore for surplus silences it, with the unused-ignore accounting."""
    out = analyze_fixture(run, workdir, 'surplusstrict', FILES_SURPLUSSTRICT, fix=False)
    assert_golden(out, __file__, 'surplusstrict')

FILES_SURPLUSSTRICTBASELINED = {
    '.declscope-baseline.yaml': '''packages:
  surplusstrictbaselined:
    surplus:
      box:
        - boxRead
        - boxed
        - boxed.n
      user:
        - userCard.old
''',
    '.declscope.yaml': '''# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
''',
    'box.go': '''//declscope:shared

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
''',
    'order.go': '''package surplusstrictbaselined

func orderRun(c userCard, k boxKind) int { return c.id + int(k) }

var _ = orderRun
''',
    'user.go': '''package surplusstrictbaselined

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
''',
}


def test_surplusstrictbaselined(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the
    surplusstrictbaselined fixture. It checks that a recorded strict finding is suppressed while a new one is still
    reported, keyed like any surplus finding by the declaration's name."""
    out = analyze_fixture(run, workdir, 'surplusstrictbaselined', FILES_SURPLUSSTRICTBASELINED, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusstrictbaselined')

FILES_SURPLUSSTRICTDEFAULTS = {
    '.declscope.yaml': '''# strict, but under defaults.unexported: shared the directive widens nothing.
defaults:
  unexported: shared
rules:
  surplus: strict
  unused: loose
''',
    'order.go': '''package surplusstrictdefaults

func orderRun(c userCard) int { return c.id }

var _ = orderRun
''',
    'user.go': '''package surplusstrictdefaults

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
''',
}


def test_surplusstrictdefaults(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the
    surplusstrictdefaults fixture. It checks that under defaults.unexported: shared strict adds nothing: the
    declaration would be shared with no directive, so the directive widened nothing."""
    out = analyze_fixture(run, workdir, 'surplusstrictdefaults', FILES_SURPLUSSTRICTDEFAULTS, fix=False, survey=True)
    assert_golden(out, __file__, 'surplusstrictdefaults')

FILES_SURPLUSSTRICTOPAQUE = {
    '.declscope.yaml': '''# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
''',
    'box.go': '''package surplusstrictopaque

// userBox crosses, so it is reported and its fix widens it. Under strict the
// fix would also narrow n, which nothing outside reads, but the rule cannot
// read gen.go, so it predicts nothing and the fix narrows no member.
type userBox struct { // want `type userBox is private to namespace "box", but is used from namespace "order"`
	n int
}

func boxRead(b userBox) int { return b.n }

var _ = boxRead
''',
    'gen.go': '''// Code generated by a tool. DO NOT EDIT.

package surplusstrictopaque

func genUse(c userCard) int { return c.note }

var _ = genUse
''',
    'order.go': '''package surplusstrictopaque

func orderRun(c userCard, b userBox) int { return c.id + len([]any{b}) }

var _ = orderRun
''',
    'user.go': '''package surplusstrictopaque

// note's only outside use is in gen.go, which the analysis excludes as a
// reference site. The package holds a source the rule cannot read, so the
// rule switches off for it.
//
//declscope:shared
type userCard struct {
	id   int
	note int
}
''',
}


def test_surplusstrictopaque(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the
    surplusstrictopaque fixture. It checks that a package holding a generated file, whose reference sites the
    analysis excludes, gets no report."""
    out = analyze_fixture(run, workdir, 'surplusstrictopaque', FILES_SURPLUSSTRICTOPAQUE, fix=False)
    assert_golden(out, __file__, 'surplusstrictopaque')

FILES_SURPLUSSTRICTREACH = {
    '.declscope.yaml': '''# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
''',
    'order.go': '''package surplusstrictreach

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
''',
    'user.go': '''package surplusstrictreach

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
''',
}


def test_surplusstrictreach(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusstrictreach
    fixture. It checks every way a field is reached without its name being spelled from outside: a composite literal
    without keys, also one behind an elided pointer type, a selection promoted through an embedding, a selection on
    an instantiated generic type, a struct conversion, also one between pointers, and a method written in another
    namespace. Each keeps the type's scope, and a field reached by none of them is still reported."""
    out = analyze_fixture(run, workdir, 'surplusstrictreach', FILES_SURPLUSSTRICTREACH, fix=False)
    assert_golden(out, __file__, 'surplusstrictreach')

FILES_SURPLUSSTRICTTESTS = {
    '.declscope.yaml': '''# strict judges each declaration under a directive that is otherwise in use.
rules:
  surplus: strict
''',
    'integration_test.go': '''package surplusstricttests

import "testing"

func TestIntegration(t *testing.T) {
	if (userCard{note: 1}).note != 1 {
		t.Fatal("no")
	}
}

var _ = userFixture{}.name
''',
    'order.go': '''package surplusstricttests

func orderRun(c userCard) int { return c.id }

var _ = orderRun
''',
    'user.go': '''package surplusstricttests

// note's only outside use is in integration_test.go, a namespace of its own.
// The test variant sees it and stays quiet. The ordinary variant does not see
// every file, so the rule switches off there instead of reporting.
//
//declscope:shared
type userCard struct {
	id   int
	note int
}
''',
    'user_test.go': '''package surplusstricttests

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
''',
}


def test_surplusstricttests(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusstricttests
    fixture. It checks that only a pass reading every file may report: the ordinary variant of a package with
    in-package tests switches the rule off, and the test variant sees the use a test file makes. What the test
    variant alone reports is pinned from a _test.go file."""
    out = analyze_fixture(run, workdir, 'surplusstricttests', FILES_SURPLUSSTRICTTESTS, fix=False)
    assert_golden(out, __file__, 'surplusstricttests')

FILES_SURPLUSTESTS = {
    'other_test.go': '''package surplustests

import "testing"

func TestOther(t *testing.T) {
	if userHelp() != 1 {
		t.Fatal("no")
	}
}
''',
    'user.go': '''package surplustests

// The only use is in other_test.go. The test variant sees it and stays quiet;
// the ordinary variant does not see every file, so the rule switches off there
// instead of reporting.
//
//declscope:shared
func userHelp() int { return 1 }
''',
}


def test_surplustests(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplustests
    fixture. It checks that only a pass reading every file may report: the ordinary variant of a package with
    in-package tests switches the rule off, and the test variant sees the use. The silence in both variants is the
    assertion."""
    out = analyze_fixture(run, workdir, 'surplustests', FILES_SURPLUSTESTS, fix=False, survey=True)
    assert_golden(out, __file__, 'surplustests')

FILES_SURPLUSUSED = {
    '.declscope.yaml': '''rules:
  surplus: loose
''',
    'order.go': '''package surplusused

func orderRun() int {
	return userShared() + userMakePair().second
}

var (
	_ = orderRun
	_ = userMake
	_ = UserRec{7}
	_ = append(userSlots(), []userSlotPtr{{1}}...)
)
''',
    'user.go': '''package surplusused

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
''',
}


def test_surplusused(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the surplusused
    fixture. It checks the first suppressor: a name spelled from another namespace keeps its directive, one member's
    use keeps a shared comment, a member that states its own scope stops carrying the type's, and a composite
    literal without keys counts as the use it is."""
    out = analyze_fixture(run, workdir, 'surplusused', FILES_SURPLUSUSED, fix=False)
    assert_golden(out, __file__, 'surplusused')
