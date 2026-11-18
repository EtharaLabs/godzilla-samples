"""Scopes and the analyzer's boundary rule, on the repository's own fixtures.

Each fixture is a module of its own here. A test runs the analyzer over ./..., and where the fixture
offers fixes, runs -fix and records every file it changed."""

from conftest import analyze_fixture, assert_golden


FILES_ALIASES = {
    '.declscope.yaml': '''rules:
  naming:
    qualify: never
  unused: loose
''',
    'alias.go': '''package aliases

// A scope directive on an alias binds the alias name, which is an ordinary
// declaration bounded by this file. It does not reach Base's members.
//
//declscope:shared
type al = Base
''',
    'base.go': '''package aliases

// Base is exported, so alias.go naming it crosses nothing. Its unexported
// field is still bounded by this file, and no directive written on an alias
// reaches it.
type Base struct {
	n int // want `field Base.n is private to namespace "base", but is used from namespace "use"`
}
''',
    'inline.go': '''package aliases

// An alias whose right-hand side is written inline does contain its fields,
// for the same reason any other declaration does.
//
//declscope:private
type entry = struct { // want `type entry is declared private by //declscope:private, but is used from namespace "use"`
	key string // want `field entry.key is declared private by //declscope:private on entry, but is used from namespace "use"`
}
''',
    'use.go': '''package aliases

// al is reachable: the directive in alias.go widened it. base.n is not: the
// alias never reached it. entry is not: inline.go narrowed it.
func useIt(x al, e entry) int { return x.n + len(e.key) }

var _ = useIt
''',
}


def test_aliases(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the aliases fixture.
    It checks what a directive on a type alias reaches. The alias name is an ordinary declaration, so
    //declscope:shared on it widens the name and use.go may take an al — the silence on alias.go is the assertion.
    It does not reach the aliased defined type's members, so Base.n keeps base.go's boundary. An alias to a struct
    written inline does contain its fields."""
    out = analyze_fixture(run, workdir, 'aliases', FILES_ALIASES, fix=False)
    assert_golden(out, __file__, 'aliases')

FILES_BASELINED = {
    '.declscope-baseline.yaml': '''packages:
  baselined:
    boundary:
      user:
        - User.name
        - userHelper
''',
    'order.go': '''package baselined

func orderRun(u *User) string {
	_ = userHelper() + userFresh()
	return u.name + u.note
}

var _ = orderRun
''',
    'user.go': '''package baselined

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
''',
}


def test_baselined(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the baselined fixture.
    It checks that recorded violations are suppressed while new ones are still reported. The baseline lives in
    testdata/src/baselined and is found by the same upward lookup as the config file."""
    out = analyze_fixture(run, workdir, 'baselined', FILES_BASELINED, fix=False, survey=True)
    assert_golden(out, __file__, 'baselined')

FILES_BOUNDARYOFF = {
    '.declscope.yaml': '''# The boundary rule is off, so reach goes unchecked and the naming rule is all
# that is left. surplus goes with it: a //declscope:shared directive means
# nothing once nothing enforces reach.
rules:
  naming:
    qualify: ondemand
  boundary: off
  surplus: off
''',
    'order.go': '''package boundaryoff

// orderRun carries its namespace, so the naming rule is quiet about it. It
// reaches across a boundary that nothing is checking.
func orderRun() int { return userCache() }

// helper does not carry "order", and the naming rule still says so.
func helper() int { return 2 } // want `func helper does not carry namespace "order" anywhere in its name; rename it to orderHelper, or to another name that carries "order"`

var _ = orderRun
''',
    'user.go': '''package boundaryoff

// userCache is private to this file, and order.go reaches it. With the
// boundary rule off, that is not reported.
func userCache() int { return 1 }
''',
}


def test_boundaryoff(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the boundaryoff
    fixture. It checks that rules.boundary: off leaves the naming rule running on its own. A reach that would be
    reported is not, and a name that does not carry its namespace still is."""
    out = analyze_fixture(run, workdir, 'boundaryoff', FILES_BOUNDARYOFF, fix=False, survey=True)
    assert_golden(out, __file__, 'boundaryoff')

FILES_DEFAULTSMEMBERS = {
    '.declscope.yaml': '''# defaults.unexported must reach members as well as package-level declarations,
# so that a defaults key governs every declaration in a package rather than half
# of them.
defaults:
  unexported: shared
rules:
  naming:
    qualify: never
''',
    'order.go': '''package defaultsmembers

func orderRun(u *User) string {
	u.bump()
	u.seal()
	_ = u.name
	return u.secret
}

var _ = orderRun
''',
    'user.go': '''package defaultsmembers

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
''',
}


def test_defaultsmembers(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the defaultsmembers
    fixture. It checks that defaults.unexported resolves members too, not only package-level declarations."""
    out = analyze_fixture(run, workdir, 'defaultsmembers', FILES_DEFAULTSMEMBERS, fix=False)
    assert_golden(out, __file__, 'defaultsmembers')

FILES_EMBEDDED = {
    'order.go': '''package embedded

type Order struct {
	userCount
	*userTotal
}

// Count reaches n through the embedding, which is a use of userCount.n.
func (o *Order) Count() int { return o.n }
''',
    'user.go': '''package embedded

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
''',
}


def test_embedded(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the embedded fixture.
    It checks that embedding a type is a use of it. The embedded field's ident is both a definition (the field) and
    a use (the type), and the second role is the one boundary has to see."""
    out = analyze_fixture(run, workdir, 'embedded', FILES_EMBEDDED, fix=False)
    assert_golden(out, __file__, 'embedded')

FILES_EXPLICIT = {
    '.declscope.yaml': '''rules:
  unused: loose
''',
    'order.go': '''package explicit

func orderRun() int {
	_ = userShape{}
	return userForced()
}

var _ = orderRun
''',
    'user.go': '''package explicit

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
''',
}


def test_explicit(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the explicit fixture.
    It checks that a declaration whose scope was stated by a directive is reported without a fix, since -fix must
    not overwrite a decision the author made deliberately."""
    out = analyze_fixture(run, workdir, 'explicit', FILES_EXPLICIT, fix=False)
    assert_golden(out, __file__, 'explicit')

FILES_FILESCOPE = {
    'caller.go': '''package filescope

func callerRun() int {
	_ = utilMust(nil)
	return utilFirst([]int{1}) + utilCache
}

var _ = callerRun
''',
    'util.go': '''//declscope:shared

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
''',
}


def test_filescope(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the filescope fixture.
    It checks a file-level scope directive: a default for what the file declares, which a declaration may still
    narrow back. Under the ignore this replaces, the narrowing would have meant nothing."""
    out = analyze_fixture(run, workdir, 'filescope', FILES_FILESCOPE, fix=False)
    assert_golden(out, __file__, 'filescope')

FILES_FILTERCANCELLED = {
    '.declscope.yaml': '''# The root admits only keep/, and nothing under sub/ is in it.
filter:
  only:
    - "keep/**"
''',
    'sub/.declscope.yaml': '''# This only matches the files beside it, and the root's only removes them all,
# so the package is read as empty and the config can never take effect.
filter:
  only:
    - "*.go"
''',
    'sub/a.go': r'''package sub // want `filter\.only stated in .* matches 1 file\(s\) here, but an only above it removes them all, so this package is read as empty`

func helper() int { return 1 }
''',
}


def test_filtercancelled(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the filtercancelled
    fixture. It checks the one filter report. A config beside a package states an only, the files it matches are all
    removed by an only above it, and the package is read as empty. Nobody writes a filter for a subtree they meant
    to exclude, so the tool says the config cannot take effect."""
    out = analyze_fixture(run, workdir, 'filtercancelled', FILES_FILTERCANCELLED, fix=False, survey=True)
    assert_golden(out, __file__, 'filtercancelled')

FILES_GENERATED = {
    'gen.go': '''// Code generated by a tool. DO NOT EDIT.

package generated

func genSecret() int { return 1 }
''',
    'use.go': '''package generated

// Generated files are excluded entirely, so referencing genSecret from another
// namespace produces no diagnostic.
func useRun() int { return genSecret() }

var _ = useRun
''',
}


def test_generated(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the generated fixture.
    It checks that generated files are neither checked nor treated as reference sites."""
    out = analyze_fixture(run, workdir, 'generated', FILES_GENERATED, fix=False, survey=True)
    assert_golden(out, __file__, 'generated')

FILES_GENERATEDOWNER = {
    '.declscope.yaml': '''rules:
  naming:
    qualify: always
''',
    'gen.go': '''// Code generated by hand, for this test. DO NOT EDIT.

package generatedowner

type Gen struct{}
''',
    'user.go': '''package generatedowner

// A method on a type declared in a generated file has no second file to be
// foreign to: the generated file is not read, so the naming rule leaves the
// method alone, as it does a method beside its type.
func (Gen) run() int { return 1 }

var _ = Gen{}.run
''',
}


def test_generatedowner(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the generatedowner
    fixture. It checks a method whose receiver is declared in a generated file, which the pass does not read."""
    out = analyze_fixture(run, workdir, 'generatedowner', FILES_GENERATEDOWNER, fix=False, survey=True)
    assert_golden(out, __file__, 'generatedowner')

FILES_GENERICS = {
    'list.go': '''package generics

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
''',
    'use.go': '''package generics

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
''',
}


def test_generics(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the generics fixture.
    It checks that the members of a generic type are bounded like those of any other type. go/types records the
    instantiated field or method for a selection on List[int], and on List[T] inside the type's own methods, so the
    lookup has to normalize to the origin object."""
    out = analyze_fixture(run, workdir, 'generics', FILES_GENERICS, fix=False)
    assert_golden(out, __file__, 'generics')

FILES_IFACEMEMBERS = {
    '.declscope.yaml': '''# The naming rules do not reach members, so they would only add noise here.
rules:
  naming:
    qualify: never
''',
    'impl.go': '''package ifacemembers

// Satisfying an interface is not a use of its method names. A method set is
// resolved, not written, so this file crosses nothing — and if it did, the
// idiom would be a violation in every codebase that uses it, repairable only
// by a directive that changes nothing about Go semantics.
type conc struct{}

func (conc) sealed() bool { return true }
func (conc) Open() int    { return 1 }

var _ Sealed = conc{}
''',
    'order.go': '''package ifacemembers

func orderRun(s Sealed, w Widened, m Mixed, q Quiet, st Store[int]) int {
	if s.sealed() {
		return w.shared() + m.ok() + m.nope() + q.hushed() + st.fetch(1) + s.Open()
	}
	return 0
}

var _ = orderRun
''',
    'user.go': '''package ifacemembers

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
''',
}


def test_ifacemembers(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the ifacemembers
    fixture. It checks that an interface's method names are members. The silences carry as much as the reports:
    implicit satisfaction in impl.go is not a use, the type's directive and its ignore reach the methods, and an
    embedded interface or a type-constraint element declares no name to bound."""
    out = analyze_fixture(run, workdir, 'ifacemembers', FILES_IFACEMEMBERS, fix=False)
    assert_golden(out, __file__, 'ifacemembers')

FILES_LINEFOREIGN = {
    '.declscope.yaml': '''# The naming rule is off by default. This package asserts that it still
# reaches a foreign method below a //line directive.
rules:
  naming:
    qualify: ondemand
  surplus: off
''',
    'order.go': '''package lineforeign

// A foreign method: its receiver's type is declared in user.go.
func (u *userRecord) leak() string { // want `method leak does not carry namespace "order" anywhere in its name; rename it to orderLeak, or to another name that carries "order"`
	return u.name
}

func orderRun() string { return (&userRecord{}).leak() }

var _ = orderRun
''',
    'user.go': '''package lineforeign

// The type below a //line directive is still declared in user.go, so a method
// filed in order.go is away from it.
//
//line user.tmpl:1
type userRecord struct { // want `type userRecord is private to namespace "user", but is used from namespace "order"`
	name string // want `field userRecord.name is private to namespace "user", but is used from namespace "order"`
}
''',
}


def test_lineforeign(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the lineforeign
    fixture. It checks that a //line directive changes nothing about which file a position belongs to. A file-level
    ignore still covers the lines below one, a type below one is still apart from a method filed elsewhere, and a
    file renamed from above its package clause is still the one the pass holds."""
    out = analyze_fixture(run, workdir, 'lineforeign', FILES_LINEFOREIGN, fix=False)
    assert_golden(out, __file__, 'lineforeign')

FILES_LINEUNSEEN = {
    'user.go': '''//line gen/user.tmpl:1
package lineunseen

// A //line directive above the package clause renames the file itself. The
// file is still the one the pass holds, so nothing is withheld.
//
//declscope:shared // want `//declscope:shared on userQuiet: no use from another namespace is visible to declscope`
func userQuiet() int { return 1 }
''',
}


def test_lineunseen(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the lineunseen
    fixture. It checks that a //line directive changes nothing about which file a position belongs to. A file-level
    ignore still covers the lines below one, a type below one is still apart from a method filed elsewhere, and a
    file renamed from above its package clause is still the one the pass holds."""
    out = analyze_fixture(run, workdir, 'lineunseen', FILES_LINEUNSEEN, fix=False)
    assert_golden(out, __file__, 'lineunseen')

FILES_MEMBEROWNER = {
    '2fa.go': '''package memberowner

// Auth's fields are written inside this declaration, so they are bounded by
// this file's namespace wherever they are read.
type Auth struct {
	secret int // want `field Auth.secret is private to namespace "2fa", but is used from namespace "order"`
}
''',
    'order.go': '''package memberowner

// A method is an ordinary top-level declaration: written here, it belongs to
// this file's namespace, so this file may use it and the call below is not a
// crossing. What it may not do is reach into Auth's fields, which belong to the
// file that declares them — and that is the boundary doing the work. Binding
// the method itself to 2fa.go instead would have made it unusable from the file
// that wrote it, with no scope able to say otherwise.
func (a *Auth) helper() int { return a.secret }

func orderRun(a *Auth) int { return a.helper() }

var _ = orderRun
''',
}


def test_memberowner(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the memberowner
    fixture. It checks the split between a field and a method. A field is written inside its type's declaration, so
    the type's file bounds it wherever it is read; a method is an ordinary top-level declaration and belongs to the
    file that wrote it. Binding methods to their type's file instead left one unusable from the file declaring it,
    with no scope able to say otherwise."""
    out = analyze_fixture(run, workdir, 'memberowner', FILES_MEMBEROWNER, fix=False)
    assert_golden(out, __file__, 'memberowner')

FILES_MEMBERS = {
    'order.go': '''package members

func orderDump(u *User) string {
	u.normalize()
	return u.name
}

var _ = orderDump
var _ = userMake
''',
    'user.go': '''package members

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
''',
}


def test_members(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the members fixture.
    It checks struct fields and interface method names bounded by the namespace of their type's file."""
    out = analyze_fixture(run, workdir, 'members', FILES_MEMBERS, fix=False)
    assert_golden(out, __file__, 'members')

FILES_PKGLEVEL = {
    'order.go': '''package pkglevel

func orderRun() int {
	_ = userPayload{}
	return userHelper() + userShared() + userCount + userLimit + userTotal
}

var _ = orderRun
''',
    'user.go': '''package pkglevel

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
''',
}


def test_pkglevel(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the pkglevel fixture.
    It checks package-level declarations of every kind (func, var, const, type, block specs) bounded by their file's
    namespace."""
    out = analyze_fixture(run, workdir, 'pkglevel', FILES_PKGLEVEL, fix=False)
    assert_golden(out, __file__, 'pkglevel')

FILES_TYPEPARAMSETS = {
    'build.go': '''package typeparamsets

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
''',
    'entry.go': '''package typeparamsets

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
''',
}


def test_typeparamsets(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the typeparamsets
    fixture. It checks that a literal or a conversion through a type parameter writes the fields of every struct in
    its type set: a named struct as the constraint, an intersection leaving one pointer, an interface term inside a
    union, and two structs sharing one underlying type."""
    out = analyze_fixture(run, workdir, 'typeparamsets', FILES_TYPEPARAMSETS, fix=False)
    assert_golden(out, __file__, 'typeparamsets')

FILES_UNKEYED = {
    'build.go': '''package unkeyed

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
''',
    'entry.go': '''package unkeyed

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
''',
}


def test_unkeyed(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the unkeyed fixture.
    It checks that a composite literal without keys uses every field it writes, though it names none of them, and
    that a literal of a generic struct's instantiation uses the declared fields. A literal that leaves out a pointer
    type, as in []*T{{1}}, writes the fields of T."""
    out = analyze_fixture(run, workdir, 'unkeyed', FILES_UNKEYED, fix=False)
    assert_golden(out, __file__, 'unkeyed')
