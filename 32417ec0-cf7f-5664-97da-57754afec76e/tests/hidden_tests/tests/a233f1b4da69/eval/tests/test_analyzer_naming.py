"""Namespaces and the analyzer's naming (qualify) rule, on the repository's own fixtures.

Each fixture is a module of its own here. A test runs the analyzer over ./..., and where the fixture
offers fixes, runs -fix and records every file it changed."""

from conftest import analyze_fixture, assert_golden


FILES_BLANKIMPORT = {
    '.declscope.yaml': '''# A file holding only a blank import still declares something: the import runs.
rules:
  naming:
    qualify: ondemand
''',
    'blankimport.go': '''package blankimport

// driver.go declares nothing but an import, which registers whatever the
// imported package registers. That is a second namespace, so the rule applies.
func seed() int { return 1 } // want `func seed does not carry namespace "blankimport" anywhere in its name; rename it to blankimportSeed, or to another name that carries "blankimport"`

var _ = seed
''',
    'driver.go': '''package blankimport

import _ "errors"
''',
}


def test_blankimport(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the blankimport
    fixture. It checks the other side: a file whose only content is an import declares something, because the import
    runs."""
    out = analyze_fixture(run, workdir, 'blankimport', FILES_BLANKIMPORT, fix=False)
    assert_golden(out, __file__, 'blankimport')

FILES_COREGOOSSIBLING = {
    'foo.go': '''package coregoossibling

// foo_linux.go is in the core, but a GOOS sibling does not join it, so this
// file keeps its namespace in every build. Joining in a linux build only made a
// baseline recorded there suppress nothing elsewhere.
func fooHelper() int { return 1 } // want `func fooHelper is private to namespace "foo", but is used from the core namespace`
''',
    'foo_darwin.go': '''//declscope:core

package coregoossibling

func Platform() int { return fooHelper() }
''',
    'foo_linux.go': '''//declscope:core

package coregoossibling

func Platform() int { return fooHelper() }
''',
    'foo_windows.go': '''//declscope:core

package coregoossibling

func Platform() int { return fooHelper() }
''',
    'platform_other.go': '''//go:build !linux && !darwin && !windows

//declscope:core

package coregoossibling

// This keeps the report in a build that compiles none of the GOOS files.
func Platform() int { return fooHelper() }
''',
}


def test_coregoossibling(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the coregoossibling
    fixture. It checks that a core GOOS file does not take its plain sibling into the core. Joining made foo.go's
    namespace depend on the build."""
    out = analyze_fixture(run, workdir, 'coregoossibling', FILES_COREGOOSSIBLING, fix=False)
    assert_golden(out, __file__, 'coregoossibling')

FILES_CORENAMEDTEST = {
    'client.go': '''//declscope:core

package corenamedtest

func New() int { return 1 }
''',
    'client_test.go': '''//declscope:namespace probe

package corenamedtest

// This file shares client.go's stem but names its own namespace. Only a file
// with no namespace directive joins the core, so the directive holds and
// probeHelper is private to probe. The report sits in a test file, which only
// the test variant reads, so it is pinned there alone.
func probeHelper() int { return New() } // want `func probeHelper is private to namespace "probe", but is used from the core namespace`
''',
    'errors.go': '''//declscope:core

package corenamedtest

var ErrClosed = New()
''',
    'errors_test.go': '''package corenamedtest

import "testing"

// No directive, so this file joins its core subject.
func TestErrClosed(t *testing.T) {
	if ErrClosed != probeHelper() {
		t.Fatal("unexpected")
	}
}
''',
}


def test_corenamedtest(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the corenamedtest
    fixture. It checks that a test file naming its own namespace keeps it, though its stem is a core file's. Only a
    file with no namespace directive joins the core. Joining anyway dropped the directive without a report, so a
    core test file could reach what the named one declares."""
    out = analyze_fixture(run, workdir, 'corenamedtest', FILES_CORENAMEDTEST, fix=False)
    assert_golden(out, __file__, 'corenamedtest')

FILES_CORENS = {
    '.declscope.yaml': '''# The core exists to be left alone by the naming rule, so it is on its
# strictest setting: whatever the core is spared here, it is spared everywhere.
rules:
  naming:
    qualify: always
    exported: true
''',
    'client.go': '''//declscope:core

package corens

// The core namespace has no name, so there is no prefix to require or to drop.
// These are the package's API and are asked for nothing.
func New() int { return 1 }

type ClientConfig struct{ retries int }

func helper() int { return 2 } // want `func helper is private to the core namespace, but is used from namespace "retry"`
''',
    'client_test.go': '''package corens

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
''',
    'errors.go': '''//declscope:core

package corens

// A second core file shares the one core namespace, the way //declscope:namespace
// merges files under a name — the core simply has none. Sharing it is what makes
// "unprefixed" still name exactly one unit, and lets this file reach client.go's
// private helper.
var ErrClosed = helper()
''',
    'pool.go': '''//declscope:core
//declscope:shared

package corens

// The two directives are orthogonal. //declscope:core decides the namespace;
// //declscope:shared decides the scope. A file may carry both, and then what
// it declares is core and package-wide at once.
func acquire() int { return 3 }
''',
    'retry.go': '''package corens

// Not core, so an ordinary namespace: the prefix is required here, and carries
// the exportedness of the name it joins.
func WithBackoff() int { return 1 } // want `func WithBackoff does not carry namespace "retry" anywhere in its name; rename it to RetryWithBackoff, or to another name that carries "retry"`

// helper is private to the core, so naming it from here crosses a boundary:
// //declscope:core carries no scope of its own. acquire does not, because
// pool.go states one.
func attempt() int { return helper() + acquire() } // want `func attempt does not carry namespace "retry" anywhere in its name; rename it to retryAttempt, or to another name that carries "retry"`

var _ = attempt
''',
}


def test_corens(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the corens fixture. It
    checks the core: several files share the one unnamed namespace, the naming rules are outside it, and an ordinary
    namespace in the same package is asked for its prefix as usual. It also checks that //declscope:core carries no
    scope. A core declaration is private to the core by default, so naming it from outside crosses a boundary, and a
    file wanting both states both."""
    out = analyze_fixture(run, workdir, 'corens', FILES_CORENS, fix=False, survey=True)
    assert_golden(out, __file__, 'corens')

FILES_CORETESTSUBJECT = {
    'client.go': '''package coretestsubject

// client_test.go is in the core, but this file is not its test, so it keeps
// its own namespace. Joining the core through its test file made the test
// variant report this crossing as private to the core, and a baseline record
// the one declaration under two keys.
func clientHelper() int { return 1 } // want `func clientHelper is private to namespace "client", but is used from namespace "order"`
''',
    'client_test.go': '''//declscope:core

package coretestsubject

import "testing"

func TestClient(t *testing.T) {}
''',
    'order.go': '''package coretestsubject

func orderTotal() int { return clientHelper() }
''',
}


def test_coretestsubject(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the coretestsubject
    fixture. It checks that a core test file does not take its subject into the core. Only a test file joins, so the
    package and its test variant report client.go's crossing under the same namespace."""
    out = analyze_fixture(run, workdir, 'coretestsubject', FILES_CORETESTSUBJECT, fix=False)
    assert_golden(out, __file__, 'coretestsubject')

FILES_EMPTYFILE = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts what the namespace
# count does once it is in force.
rules:
  naming:
    qualify: ondemand
''',
    'doc.go': '''// Package emptyfile documents itself and declares nothing.
package emptyfile
''',
    'emptyfile.go': '''package emptyfile

// doc.go holds a package comment and nothing else, so it is not a second unit.
// The naming rule stays out, and this name is left alone.
func seed() int { return 1 }

var _ = seed
''',
}


def test_emptyfile(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the emptyfile fixture.
    It checks that a file holding only a package clause and comments does not add to the namespace count. A doc.go
    is the usual one."""
    out = analyze_fixture(run, workdir, 'emptyfile', FILES_EMPTYFILE, fix=False, survey=True)
    assert_golden(out, __file__, 'emptyfile')

FILES_EXPORTEDPREFIXES = {
    '.declscope.yaml': '''rules:
  naming:
    qualify: always
    exported: true
''',
    'client.go': '''package exportedprefixes

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
''',
}


def test_exportedprefixes(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the exportedprefixes
    fixture. It checks rules.naming.exported, and that the prefix carries the exportedness of the name it joins: New
    is reported against ClientNew, never clientNew, since a rename must not delete the API it is renaming."""
    out = analyze_fixture(run, workdir, 'exportedprefixes', FILES_EXPORTEDPREFIXES, fix=False)
    assert_golden(out, __file__, 'exportedprefixes')

FILES_EXPORTEDSCOPE = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
''',
    'api.go': '''package exportedscope

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
''',
    'use.go': '''package exportedscope

func useRun(c *Config, e *entry) int {
	c.Timeout = 1
	_ = e.Key
	return Seal()
}

var _ = useRun
''',
}


def test_exportedscope(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the exportedscope
    fixture. It checks that exportedness decides the default and nothing else: an exported declaration carries no
    boundary until a directive gives it one, and a directive on a type reaches its exported fields — which is how a
    DTO capitalized for a serializer is protected, without the analysis guessing at reachability it cannot compute."""
    out = analyze_fixture(run, workdir, 'exportedscope', FILES_EXPORTEDSCOPE, fix=False)
    assert_golden(out, __file__, 'exportedscope')

FILES_FOREIGNMETHOD = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts which methods it
# reaches once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
  surplus: off
''',
    'order.go': '''package foreignmethod

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
''',
    'user.go': '''package foreignmethod

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
''',
}


def test_foreignmethod(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the foreignmethod
    fixture. It checks which methods the naming rule reaches. A method filed away from its receiver's type is read
    through a receiver that names a different unit, so the rule asks for the namespace the method is written in. A
    local method and an interface method name are left alone."""
    out = analyze_fixture(run, workdir, 'foreignmethod', FILES_FOREIGNMETHOD, fix=False)
    assert_golden(out, __file__, 'foreignmethod')

FILES_MAINPKG = {
    '.declscope.yaml': '''# always, so that the func main exemption is exercised rather than assumed.
rules:
  naming:
    qualify: always
''',
    'handler.go': '''package main

func handlerDo() { // want `func handlerDo is private to namespace "handler", but is used from namespace "main"`
	c := ServerNew()
	c.Addr = ":80"
	_ = c
}
''',
    'main.go': '''//declscope:private

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
''',
}


def test_mainpkg(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the mainpkg fixture.
    It checks the two rules that only package main exercises: func main is the one name the toolchain requires, so
    the naming rules pass it by even at qualify: always, and a file-level scope directive reaches exported
    declarations, which is the only thing holding Config and ServerNew back."""
    out = analyze_fixture(run, workdir, 'mainpkg', FILES_MAINPKG, fix=False)
    assert_golden(out, __file__, 'mainpkg')

FILES_NSDETACHED = {
    'a.go': '''//declscope:namespace shared

// Package nsdetached checks that a namespace directive is recognized when a
// blank line separates it from the package clause, which is how a file that
// already carries a package doc comment keeps the two apart.
package nsdetached

func helper() int { return 1 }
''',
    'b.go': '''//declscope:namespace shared

package nsdetached

func use() int { return helper() }

var _ = use
''',
}


def test_nsdetached(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the nsdetached
    fixture. It checks that a namespace directive separated from the package clause by a blank line still applies to
    the file."""
    out = analyze_fixture(run, workdir, 'nsdetached', FILES_NSDETACHED, fix=False, survey=True)
    assert_golden(out, __file__, 'nsdetached')

FILES_NSIDENTITY = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
''',
    '2fa.go': '''package nsidentity

// The stem 2fa is a namespace like any other, so 2fa_test.go shares it and
// may use totp. It cannot be a prefix, since no identifier starts with a
// digit, so qualify asks nothing of totp even though the package has a second
// namespace; the privacy rules still bound it, so the use from other.go is
// reported here.
func totp() int { return 1 } // want `func totp is private to namespace "2fa", but is used from namespace "other"`

func Verify() int { return totp() }
''',
    '2fa_test.go': '''package nsidentity

import "testing"

func TestTOTP(t *testing.T) {
	if totp() != 1 {
		t.Fatal("unexpected")
	}
}
''',
    'other.go': '''package nsidentity

// The second namespace, which is what puts qualify in force for the package.
// It is a prefix, so its own declarations are held to it.
func otherRun() int { return 1 }

func helper() int { return 2 } // want `func helper does not carry namespace "other" anywhere in its name; rename it to otherHelper, or to another name that carries "other"`

// A cross-namespace use is still a violation: 2fa is an identity even though
// it is not a prefix.
var _ = totp

var _ = otherRun() + helper()
''',
}


def test_nsidentity(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the nsidentity
    fixture. It checks that a file whose stem cannot be a prefix, such as 2fa.go, is still a namespace: its test
    file shares it, a use from another namespace is reported, and the naming rule asks nothing of it."""
    out = analyze_fixture(run, workdir, 'nsidentity', FILES_NSIDENTITY, fix=False)
    assert_golden(out, __file__, 'nsidentity')

FILES_NSINDOC = {
    'a.go': '''// Package nsindoc checks the placement Go's own doc comment convention
// prescribes for directives: at the bottom of the package comment, preceded by
// a blank comment line. go/doc strips directive lines, so the rendered package
// documentation is unaffected.
//
//declscope:namespace shared
package nsindoc

func helper() int { return 1 }
''',
    'b.go': '''//declscope:namespace shared

package nsindoc

func use() int { return helper() }

var _ = use
''',
}


def test_nsindoc(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the nsindoc fixture.
    It checks the placement prescribed by Go's doc comment convention: a directive at the bottom of the package
    comment, which go/doc strips from the rendered documentation."""
    out = analyze_fixture(run, workdir, 'nsindoc', FILES_NSINDOC, fix=False, survey=True)
    assert_golden(out, __file__, 'nsindoc')

FILES_NSINITIALISM = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
''',
    'parse_json.go': '''package nsinitialism

// The second namespace. An initialism in a later segment is spelled the way
// Go does, so the prefix is parseJSON and parseJsonTree carries it too.
func parseJSONTree() int { return 1 }
func parseJsonTree() int { return 2 }

func tree() int { return 3 } // want `func tree does not carry namespace "parseJSON" anywhere in its name; rename it to parseJSONTree, or to another name that carries "parseJSON"`

func ParseExported() int { return parseJSONTree() + parseJsonTree() + tree() }
''',
    'user_id.go': '''package nsinitialism

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
''',
    'user_ids.go': '''package nsinitialism

// The namespace of user_ids.go is userIDs, spelled the way Go spells a plural
// initialism, not userIds.
func load() int { return 1 } // want `func load does not carry namespace "userIDs" anywhere in its name; rename it to userIDsLoad, or to another name that carries "userIDs"`
''',
}


def test_nsinitialism(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the nsinitialism
    fixture. It checks that a namespace spells its initialisms the way Go does, that the prefix is matched ignoring
    case, and that the rename offered by qualify spells the name's first word the same way."""
    out = analyze_fixture(run, workdir, 'nsinitialism', FILES_NSINITIALISM, fix=False)
    assert_golden(out, __file__, 'nsinitialism')

FILES_NSNORMALIZE = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
''',
    'Foo.go': '''package nsnormalize

// A PascalCase stem is lowered, so the suggested name stays unexported rather
// than becoming FooBar.
func bar() int { return 1 } // want `func bar does not carry namespace "foo" anywhere in its name; rename it to fooBar, or to another name that carries "foo"`

func fooOK() int { return bar() + fooBarOK() }
''',
    'URLs.go': '''package nsnormalize

// A stem that opens with a plural initialism is lowered whole, as Go lowers
// the identifier URLs, so the suggested name is urlsHelper rather than
// urLsHelper.
func helper() int { return 1 } // want `func helper does not carry namespace "urls" anywhere in its name; rename it to urlsHelper, or to another name that carries "urls"`

func urlsOK() int { return helper() }
''',
    'foo-bar.go': '''package nsnormalize

// Any separator yields a lowerCamelCase namespace, so the suggested name is
// an identifier rather than foo-barBaz.
func baz() int { return 1 } // want `func baz does not carry namespace "fooBar" anywhere in its name; rename it to fooBarBaz, or to another name that carries "fooBar"`

// Used from Foo.go, which is namespace foo: the two stems are distinct
// identities, and the boundary is reported here at the declaration.
func fooBarOK() int { return baz() } // want `func fooBarOK is private to namespace "fooBar", but is used from namespace "foo"`
''',
}


def test_nsnormalize(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the nsnormalize
    fixture. It checks that separators other than _ and a PascalCase stem yield a lowerCamelCase namespace, so that
    the rename offered by qualify is a valid unexported identifier."""
    out = analyze_fixture(run, workdir, 'nsnormalize', FILES_NSNORMALIZE, fix=False)
    assert_golden(out, __file__, 'nsnormalize')

FILES_NSTESTSUFFIX = {
    'foo.go': '''package nstestsuffix

// foo_test_linux.go is an ordinary linux file, not a test of this one: only a
// name ending in _test.go is a test file. It is namespace fooTest, so its use
// is a crossing.
func fooHelper() int { return 1 } // want `func fooHelper is private to namespace "foo", but is used from namespace "fooTest"`

func fooOK() int { return fooHelper() }
''',
    'foo_test_linux.go': '''package nstestsuffix

func fooTestRun() int { return fooHelper() }
''',
}


def test_nstestsuffix(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the nstestsuffix
    fixture. It checks that a file with a build suffix after _test, such as foo_test_linux.go, is not a test of
    foo.go and has a namespace of its own. GOOS is set so that the file is compiled on every host."""
    out = analyze_fixture(run, workdir, 'nstestsuffix', FILES_NSTESTSUFFIX, fix=False)
    assert_golden(out, __file__, 'nstestsuffix')

FILES_QUALIFYALWAYS = {
    '.declscope.yaml': '''# Require the prefix even in a package with one namespace, so that gaining a
# second one is not a mass rename.
rules:
  naming:
    qualify: always
''',
    'only.go': '''package qualifyalways

// The package has a single namespace, so the default would not require a
// prefix here. rules.qualify: always asks for it anyway.
func helper() int { return 1 } // want `func helper does not carry namespace "only" anywhere in its name; rename it to onlyHelper, or to another name that carries "only"`

func onlyOK() int { return helper() }

var _ = onlyOK
''',
}


def test_qualifyalways(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the qualifyalways
    fixture. It checks rules.qualify: always, which requires the prefix even in a package with a single namespace."""
    out = analyze_fixture(run, workdir, 'qualifyalways', FILES_QUALIFYALWAYS, fix=False)
    assert_golden(out, __file__, 'qualifyalways')

FILES_QUALIFYBASELINED = {
    '.declscope-baseline.yaml': '''packages:
  qualifybaselined:
    qualify:
      user:
        - orderA.help
''',
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts how a baseline
# absorbs what it reports.
rules:
  naming:
    qualify: always
''',
    'order.go': '''package qualifybaselined

//declscope:shared // user.go declares a method on it
type orderA struct{}

//declscope:shared // user.go declares a method on it
type orderB struct{}
''',
    'user.go': '''package qualifybaselined

// orderA.help is recorded in the baseline, so it stays quiet.
func (orderA) help() int { return 1 }

// orderB.help shares its name and namespace but not its receiver, so the
// entry for orderA.help does not absorb it.
func (orderB) help() int { return 2 } // want `method help does not carry namespace "user" anywhere in its name; rename it to userHelp, or to another name that carries "user"`

var _, _ = orderA{}.help, orderB{}.help
''',
}


def test_qualifybaselined(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the qualifybaselined
    fixture. It checks that a qualify baseline entry names a method with its receiver type, so baselining
    orderA.help does not absorb a new orderB.help in the same namespace."""
    out = analyze_fixture(run, workdir, 'qualifybaselined', FILES_QUALIFYBASELINED, fix=False, survey=True)
    assert_golden(out, __file__, 'qualifybaselined')

FILES_QUALIFYDEFAULT = {
    'order.go': '''package qualifydefault

func orderRun() int { return helper() }

var _ = orderRun
''',
    'user.go': '''package qualifydefault

// No config reaches this package, so the naming rule is at its default: off.
// helper carries no namespace and draws no qualify diagnostic even though the
// package has a second namespace. The boundary rule is untouched by the
// default and still fires below.
func helper() int { return 1 } // want `func helper is private to namespace "user", but is used from namespace "order"`

// bare is used only from its own namespace: no boundary, and no qualify.
func bare() int { return helper() }

var _ = bare
''',
}


def test_qualifydefault(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the qualifydefault
    fixture. It checks the built-in default: with no config, the naming rule asks nothing even of a package with a
    second namespace, while the boundary rule fires as it always did."""
    out = analyze_fixture(run, workdir, 'qualifydefault', FILES_QUALIFYDEFAULT, fix=False)
    assert_golden(out, __file__, 'qualifydefault')

FILES_QUALIFYINFLECT = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package pins what the inflected
# forms buy it — and what the stem of a namespace must never buy.
rules:
  naming:
    qualify: ondemand
''',
    'apply.go': '''package qualifyinflect

// The final y turns to i: applied is appli + ed, and the generated form
// accepts it wherever it opens a word.
func appliedResults() int { return 3 }

var _ = appliedResults
''',
    'store.go': '''package qualifyinflect

// The namespace's own spelling changes under -ing, so plain containment
// cannot see it: storing is stor + ing, not store + anything. The generated
// form accepts it.
func storing() int { return 1 }

// Only the generated whole form counts. A name that merely shares the stem
// does not carry the namespace: matching stor loose would accept story, which
// has nothing to do with store.
func story() int { return 2 } // want `func story does not carry namespace "store" anywhere in its name; rename it to storeStory, or to another name that carries "store"`

var _, _ = storing, story
''',
}


def test_qualifyinflect(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the qualifyinflect
    fixture. It checks the two inflections whose spelling leaves the namespace behind: a final e dropped before -ing
    (store → storing) and a final y turned to i (apply → applied). Only forms generated from the namespace are
    accepted, so a name that merely shares the stem (story) is still reported."""
    out = analyze_fixture(run, workdir, 'qualifyinflect', FILES_QUALIFYINFLECT, fix=False)
    assert_golden(out, __file__, 'qualifyinflect')

FILES_QUALIFYINFLECTED = {
    '.declscope.yaml': '''# The naming rule is off by default. This package pins the message an
# inflected namespace gets: its stem does not carry it, and the vocabulary key
# to list the stem under.
rules:
  naming:
    qualify: ondemand
''',
    'string.go': '''package qualifyinflected

// string ends in -ing, but str holds no vowel, so it is not read as an
// inflected form and the message has nothing to add.
func quote() int { return 3 } // want `func quote does not carry namespace "string" anywhere in its name; rename it to stringQuote, or to another name that carries "string"$`

var _ = quote
''',
    'tracing.go': '''package qualifyinflected

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
''',
}


def test_qualifyinflected(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the qualifyinflected
    fixture. It checks the message of a namespace that is itself an inflected form. Its stem does not carry it,
    since generation runs only from the namespace, so the message names the vocabulary key instead. A namespace with
    no vowel before -ing (string) gets the plain message."""
    out = analyze_fixture(run, workdir, 'qualifyinflected', FILES_QUALIFYINFLECTED, fix=False)
    assert_golden(out, __file__, 'qualifyinflected')

FILES_QUALIFYRULE = {
    '.declscope.yaml': '''# The naming rule is off by default, and this package asserts what it does
# once a second namespace puts it in force.
rules:
  naming:
    qualify: ondemand
''',
    'order.go': '''package qualifyrule

// A second namespace, which is what gives the prefixes something to distinguish.
// It deliberately touches nothing in namespace "user", so the only rule under
// test here is the naming rule.
func orderRun() int { return 1 }

var _ = orderRun
''',
    'user.go': '''package qualifyrule

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
''',
    'user_test.go': '''package qualifyrule

import "testing"

// The toolchain finds a test by its name, so no rename is asked of it.
func TestUser(t *testing.T) { _ = fixture() }

// Any other function in a test file is an ordinary declaration.
func fixture() int { return 1 } // want `func fixture does not carry namespace "user" anywhere in its name; rename it to userFixture, or to another name that carries "user"`
''',
}


def test_qualifyrule(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the qualifyrule
    fixture. It checks that an unexported package-level declaration must carry its namespace as a prefix, and that
    members and exported identifiers are exempt."""
    out = analyze_fixture(run, workdir, 'qualifyrule', FILES_QUALIFYRULE, fix=False)
    assert_golden(out, __file__, 'qualifyrule')

FILES_SINGLENS = {
    '.declscope.yaml': '''# ondemand is stated so that the silence below is the rule's own: in a package
# with one namespace it asks nothing, not because the rule is off (the default)
# but because there is no boundary for a prefix to mark.
rules:
  naming:
    qualify: ondemand
''',
    'a.go': '''//declscope:namespace shared

package singlens

// The package has a single namespace, so there is no boundary for a prefix to
// mark and the prefix is not required. Every other rule is structurally inert
// here too, since every reference is already inside the one namespace.
func helper() int { return 1 }

var count int
''',
    'b.go': '''//declscope:namespace shared

package singlens

func use() int { return helper() + count }

var _ = use
''',
}


def test_singlens(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the singlens fixture.
    It checks that the prefix is not required in a package with only one namespace, where there is no boundary for
    it to mark."""
    out = analyze_fixture(run, workdir, 'singlens', FILES_SINGLENS, fix=False, survey=True)
    assert_golden(out, __file__, 'singlens')

FILES_TESTNS = {
    'calc.go': '''package testns

// helper is private to namespace "calc". A _test.go file shares its
// subject's namespace, so using it from calc_test.go is not a violation.
func helper() int { return 1 }

func calcShared() int { return helper() }
''',
    'calc_test.go': '''package testns

import "testing"

func TestHelper(t *testing.T) {
	if helper() != 1 {
		t.Fatal("unexpected")
	}
	if calcShared() != 1 {
		t.Fatal("unexpected")
	}
}
''',
}


def test_testns(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the testns fixture. It
    checks that a _test.go file may use the private declarations of its subject."""
    out = analyze_fixture(run, workdir, 'testns', FILES_TESTNS, fix=False, survey=True)
    assert_golden(out, __file__, 'testns')

FILES_TOOLCHAINNAMES = {
    '.declscope.yaml': '''# Strictest, so the exemption is exercised rather than assumed: without it the
# toolchain names would every one be asked for a prefix.
rules:
  naming:
    qualify: always
    exported: true
''',
    'user.go': '''package toolchainnames

// TestHelper is not in a _test.go file, so the toolchain never finds it by
// name and the prefix is asked for like any other.
func TestHelper() int { return 1 } // want `func TestHelper does not carry namespace "user" anywhere in its name; rename it to UserTestHelper, or to another name that carries "user"`

func userLoad() int { return 2 }
''',
    'user_test.go': '''package toolchainnames

import "testing"

// The toolchain finds each of these by name. Prefixing one leaves a function
// nothing runs, so none is asked for a prefix.
func TestLoad(t *testing.T)      { _ = userLoad() }
func BenchmarkLoad(b *testing.B) { _ = userLoad() }
func FuzzLoad(f *testing.F)      { _ = userLoad() }
func ExampleTestHelper()         { _ = TestHelper() }
''',
}


def test_toolchainnames(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the toolchainnames
    fixture. It checks that a name the toolchain finds by name is never asked for a prefix. The silences carry the
    assertion: TestLoad, BenchmarkLoad, FuzzLoad and ExampleTestHelper would each be a function nothing runs once
    prefixed. TestHelper in a non-test file is still asked, because nothing collects it by name."""
    out = analyze_fixture(run, workdir, 'toolchainnames', FILES_TOOLCHAINNAMES, fix=False)
    assert_golden(out, __file__, 'toolchainnames')

FILES_UNCAPITALIZABLE = {
    '.declscope.yaml': '''rules:
  naming:
    qualify: always
    exported: true
''',
    'order.go': '''package uncapitalizable

// A namespace with a capital form is still held to the rule.
func Total() int { return 1 } // want `func Total does not carry namespace "order" anywhere in its name; rename it to OrderTotal, or to another name that carries "order"`
''',
    'under.go': '''//declscope:namespace _foo

package uncapitalizable

// _foo is a valid namespace, but _ has no capital form either, so Save is not
// asked to become _fooSave.
func Save() int { return 1 }
''',
    '用户.go': '''package uncapitalizable

// 用户 has no capital form, so an exported name could neither carry it nor take
// it as a prefix and stay exported. The naming rule asks nothing here, as for
// 2fa.go; it used to tell the author to rename Load to 用户Load, which
// unexports it.
func Load() int { return 1 }

func helper() int { return 2 }

var _ = helper
''',
}


def test_uncapitalizable(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the uncapitalizable
    fixture. It checks that a namespace whose first letter has no capital form, such as 用户 or _foo, gets no naming
    diagnostic. Qualify could not keep an exported name exported with it, so the advice unexported the name."""
    out = analyze_fixture(run, workdir, 'uncapitalizable', FILES_UNCAPITALIZABLE, fix=False)
    assert_golden(out, __file__, 'uncapitalizable')

FILES_VOCABULARY = {
    '.declscope.yaml': '''# The vocabulary maps a namespace to the extra words that carry it: irregular
# inflections and domain synonyms the generated forms cannot reach. The words
# go through the same test as the namespace itself — word boundary on the
# left, free right edge — which pinwheel below is the negative for.
rules:
  naming:
    qualify: ondemand
    vocabulary:
      mouse: [wheel]
      index: [indices]
''',
    'index.go': '''package vocabulary

// The irregular plural, listed as vocabulary because no generated inflection
// produces it. The right edge stays free, so the word may end inside the name.
func indicesSorted() int { return 5 }

var _ = indicesSorted
''',
    'mouse.go': '''package vocabulary

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
''',
}


def test_vocabulary(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the vocabulary
    fixture. It checks rules.naming.vocabulary: a word listed for a namespace satisfies the naming rule under the
    same test as the namespace itself — word boundary on the left, free right edge — and nothing more."""
    out = analyze_fixture(run, workdir, 'vocabulary', FILES_VOCABULARY, fix=False)
    assert_golden(out, __file__, 'vocabulary')

FILES_SYMBOLFILE = {
    'order.go': '''package symbolfile

func orderRun() int { return helper() }

var _ = orderRun
''',
    '★.go': '''package symbolfile

// A file whose name holds no letter or digit has no namespace of its own,
// so a report names the file instead.
func helper() int { return 1 } // want `func helper is private to file ★.go, but is used from namespace "order"`
''',
}


def test_symbolfile(run, workdir):
    """CATCHES: an analyzer whose diagnostics, fixes or exit status differ from the reference on the symbolfile
    fixture. It checks a file whose name yields no namespace."""
    out = analyze_fixture(run, workdir, 'symbolfile', FILES_SYMBOLFILE, fix=False)
    assert_golden(out, __file__, 'symbolfile')
