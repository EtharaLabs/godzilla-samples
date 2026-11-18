"""//declscope:ignore overexported under declscope shrink: where it binds, what it silences, and when shrink
reports it as unused."""

from conftest import assert_golden, gomod, transcript, write_files

MOD = "example.com/ignores"

USER = """package b

import "example.com/ignores/internal/i"

var _ = i.Ignored() + i.Mixed() + i.F() + i.Answered() + i.Used()

var _ = i.Hand()
"""


def shrink(run, workdir, files, *args, env=None):
    write_files(workdir, {"go.mod": gomod(MOD), **files})
    return transcript(run(["shrink", *args], env_overrides=env), workdir)


def test_where_an_ignore_binds_and_what_it_silences(run, workdir):
    """CATCHES: an ignore that does not bind where the analyzer binds it (doc comment, a trailing comment on a func's
    first or last line, after `struct {` or `var (`), a bare ignore that reaches overexported, or an ignore of a used
    declaration not reported unused."""
    out = shrink(run, workdir, {
        "internal/i/i.go": """package i

//declscope:ignore overexported
func Silenced() {}

// The declaration is used by package b, so the ignore silences nothing.
//
//declscope:ignore overexported
func Ignored() int { return Used() }

//declscope:ignore overexported,qualify
func Mixed() int { return Used() }

//declscope:ignore
func Bare() {}

func Trailing() {} //declscope:ignore overexported

func Multi() {
} //declscope:ignore overexported

func Commented(n int /* units */) int { //declscope:ignore overexported
	return n
}

type Braced struct { //declscope:ignore overexported
	n int
}

var ( //declscope:ignore overexported
	Parened = 1
)

func Used() int { return 1 }

var _ = Braced{}.n
""",
        "b/b.go": 'package b\n\nimport "example.com/ignores/internal/i"\n\nvar _ = i.Ignored() + i.Mixed()\n',
    })
    assert_golden(out, __file__, "binding")


def test_unused_reports_and_their_answers(run, workdir):
    """CATCHES: an unused-ignore report that is not answered by an ignore naming unused beside it (doc and trailing
    comment, block doc and the comment after "("), that is reported for a duplicate the analyzer reports, or that is
    missing for an ignore bound to no declaration."""
    out = shrink(run, workdir, {
        "internal/i/i.go": """package i

//declscope:ignore unused
func F() int { return 1 } //declscope:ignore overexported

//declscope:ignore overexported
//declscope:ignore unused
func Answered() int { return Used() }

//declscope:ignore overexported
func Twice() {} //declscope:ignore overexported

//declscope:ignore overexported
type Typed int //declscope:ignore unused

//declscope:ignore overexported
var Valued = 1 //declscope:ignore unused

//declscope:ignore overexported
var ( //declscope:ignore unused
	Blocked = 1
)

func stray() {
	//declscope:ignore overexported
}

func Used() int { return 1 }

var _ = stray
""",
        "b/b.go": 'package b\n\nimport "example.com/ignores/internal/i"\n\nvar _ = i.F() + i.Answered() + i.Used()\n\nvar _ = i.Typed(i.Valued + i.Blocked)\n',
    })
    assert_golden(out, __file__, "answers")


def test_file_level_ignores(run, workdir):
    """CATCHES: a file-level ignore covering unused that does not answer the unused reports in its file, or a
    repeated file-level ignore reported unused as well as duplicated; a file-level overexported ignore silences
    every declaration of its own file, and no other file of the package."""
    out = shrink(run, workdir, {
        "internal/i/file.go": """// A file-level ignore covering unused answers every ignore in the file.
//
//declscope:ignore unused

package i

//declscope:ignore overexported
func FileAnswered() int { return Used() }
""",
        "internal/i/twice.go": """//declscope:ignore overexported

//declscope:ignore overexported

package i

func TwiceFile() {}
""",
        "internal/i/used.go": "package i\n\nfunc Used() int { return 1 }\n",
        "internal/j/j.go": "//declscope:ignore overexported\n\npackage j\n\nfunc A() {}\n\nfunc B() {}\n",
        "internal/j/k.go": "package j\n\nfunc C() {}\n",
        "b/b.go": 'package b\n\nimport (\n\t"example.com/ignores/internal/i"\n\t"example.com/ignores/internal/j"\n)\n\nvar _ = i.FileAnswered() + i.Used()\n\nvar _ = j.A\n',
    })
    assert_golden(out, __file__, "file_level")


def test_silenced_declarations_keep_names_and_types(run, workdir):
    """CATCHES: a silenced declaration whose name is still claimed by the run (FOO's fix must be offered), a
    silenced function whose returned type is fixed anyway, or an ignore on a type a used API returns that is not
    reported unused."""
    out = shrink(run, workdir, {
        "internal/i/i.go": """package i

//declscope:ignore overexported
func Foo() {}

func FOO() {}

//declscope:ignore overexported
type Handed struct{}

func Hand() *Handed { return nil }

//declscope:ignore overexported
func Build() *Built { return nil }

type Built struct{}
""",
        "b/b.go": 'package b\n\nimport "example.com/ignores/internal/i"\n\nvar _ = i.Hand()\n',
    })
    assert_golden(out, __file__, "silenced_types")


def test_member_ignores_are_one_binding(run, workdir):
    """CATCHES: member ignores parsed only for candidates: an interface method's or an alias struct's field ignore
    is still one binding with its trailing comment, so the ignore naming unused answers it there too."""
    out = shrink(run, workdir, {
        "internal/i/members.go": """package i

type iface interface {
	//declscope:ignore overexported
	M() //declscope:ignore unused
}

type aliased = struct {
	//declscope:ignore overexported
	F int //declscope:ignore unused
}

type fielded struct {
	//declscope:ignore overexported
	F int //declscope:ignore unused
}

type Open struct {
	//declscope:ignore overexported
	Kept int
	Lost int
}

var _ = []any{(*iface)(nil), aliased{}, fielded{}}
""",
    })
    assert_golden(out, __file__, "members")


CONSTRAINED = {
    "internal/i/i.go": """package i

type Mode struct {
	//declscope:ignore overexported
	Tagged int
	//declscope:ignore overexported
	Plain int
}

//declscope:ignore overexported
func TaggedFunc() {}

type Shown struct {
	//declscope:ignore overexported
	Field int
}

type Printed struct {
	//declscope:ignore overexported
	Hidden int
}
""",
    "internal/h/h.go": """package h

type Held struct {
	//declscope:ignore overexported
	Mark int
}

func Hold() Held { return Held{} }
""",
    "b/b.go": 'package b\n\nimport "example.com/ignores/internal/i"\n\nvar _ = i.Mode{}.Plain\n',
    "b/tagged.go": """//go:build !never

package b

import "example.com/ignores/internal/i"

var _ = i.Mode{}.Tagged + i.Mode{}.Plain

var _ = i.TaggedFunc

func sink(...any) {}

func show() { sink(i.Shown{Field: 1}, i.Printed{}) }

var _ = show
""",
    "c/c.go": 'package c\n\nimport "example.com/ignores/internal/h"\n\nvar held = h.Hold()\n',
    "c/tagged.go": "//go:build !never\n\npackage c\n\nvar _ = held.Mark\n",
}


def test_ignore_needed_only_without_a_build_constraint(run, workdir):
    """CATCHES: an ignore reported unused because the files using its member are compiled in this run, though a
    configuration leaving them out would report the member; one used in every configuration is still unused."""
    assert_golden(shrink(run, workdir, CONSTRAINED), __file__, "constrained")


def test_ignore_needed_only_without_a_build_constraint_other_configuration(run, workdir):
    """CATCHES: a run with -tags=never (the constrained files left out) whose reports differ from the default run:
    the same ignores must pass both configurations."""
    out = shrink(run, workdir, CONSTRAINED, env={"GOFLAGS": "-tags=never"})
    assert_golden(out, __file__, "constrained_never")


def test_ignores_on_test_functions(run, workdir):
    """CATCHES: a test function's ignores treated as no binding (the ignore naming unused must answer the doc's
    report), or a repeated ignore on a test function reported twice."""
    out = shrink(run, workdir, {
        "internal/i/i.go": "package i\n",
        "internal/i/i_test.go": """package i

import "testing"

//declscope:ignore overexported
func TestX(t *testing.T) {} //declscope:ignore unused

//declscope:ignore overexported
func TestY(t *testing.T) {} //declscope:ignore overexported
""",
    })
    assert_golden(out, __file__, "test_functions")


def test_baseline_entry_suppresses_a_report(run, workdir):
    """CATCHES: a shrink that ignores the baseline the analyzer would consult, or that lets an ignore over a
    baselined declaration count as unused; a baselined declaration also keeps its name under -fix."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/i/i.go": "package i\n\nfunc Recorded() {}\n\n//declscope:ignore overexported\nfunc Both() {}\n\nfunc Fresh() {}\n",
        ".declscope-baseline.yaml": """packages:
  example.com/ignores/internal/i:
    overexported:
      i:
        - Recorded
        - Both
""",
    })
    r = run(["shrink", "-fix"])
    assert_golden(transcript(r, workdir, ("internal/i/i.go",)), __file__, "baselined")


def test_baseline_named_by_explicit_config(run, workdir):
    """CATCHES: shrink -config that does not read the baseline the named config file points to."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/i/i.go": "package i\n\nfunc Recorded() {}\n\nfunc Fresh() {}\n",
        "conf/strict.yaml": "baseline: base.yaml\n",
        "conf/base.yaml": "packages:\n  example.com/ignores/internal/i:\n    overexported:\n      i:\n        - Recorded\n",
    })
    r = run(["shrink", "-config", "conf/strict.yaml"])
    assert_golden(transcript(r, workdir), __file__, "explicit_config")


def test_broken_config_fails_the_run(run, workdir):
    """CATCHES: a config file shrink cannot read (unknown key) that is ignored instead of failing the run, as it
    fails the analyzer."""
    write_files(workdir, {
        "go.mod": gomod(MOD),
        "internal/i/i.go": "package i\n\nfunc Fresh() {}\n",
        ".declscope.yaml": "rules:\n  bogus: on\n",
    })
    r = run(["shrink"])
    assert_golden(transcript(r, workdir), __file__, "broken_config")
