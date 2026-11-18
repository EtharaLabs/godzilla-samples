"""The rename declscope shrink -fix makes: what it rewrites, and each guard that withholds it."""

from conftest import assert_golden, gomod, transcript, write_files

MOD = "example.com/rename"


def shrink_fix(run, workdir, files, fixed):
    """One -fix run: the reports it leaves without a fix, and the files it rewrote."""
    write_files(workdir, {"go.mod": gomod(MOD), **files})
    return transcript(run(["shrink", "-fix"]), workdir, fixed)


def test_package_level_name_guards(run, workdir):
    """CATCHES: a rename to a name that is taken, captured by a parameter at a use, a keyword, predeclared,
    init or main, an import name of another file (cmp), or one with no Go spelling (MAX_RETRIES); and a rename that
    misses a use, a doc comment's leading name (also after an article), or that edits a block comment."""
    out = shrink_fix(run, workdir, {
        "internal/r/imp.go": 'package r\n\nimport "cmp"\n\nvar _ = cmp.Compare[int]\n',
        "internal/r/r.go": """package r

// Plain is fixed, and the name its doc comment opens with is rewritten too.
func Plain() int { return 1 }

// A Thing is fixed, and so is the name after the article.
type Thing struct{}

// The Gadget is fixed, and so is the name after the article.
type Gadget struct{}

/* Block is a block comment, which the fix leaves alone. */
func Block() {}

// Loader opens this comment, which is another word, and is left alone.
func Load() {}

func Taken() int { return taken() }

func taken() int { return 0 }

// Count is captured by the parameter of the same name at its one use.
var Count = func(count int) int { return count }

func useCount(count int) int { return count + Count(count) }

func Dup() int { return 1 }

func DUP() int { return 2 }

func Type() {}

func Func() {}

func Init() {}

func Main() {}

func Cmp() {}

func HTTPServer() {}

const MAX_RETRIES = 3

const Limit = 3

var (
	_ Thing
	_ Gadget
	_ = useCount
	_ = Plain() + Dup() + DUP() + MAX_RETRIES + Limit
)
""",
    }, ("internal/r/r.go",))
    assert_golden(out, __file__, "package_level")


def test_linkname_and_export_directives_withhold(run, workdir):
    """CATCHES: a rename of a function that a //go:linkname in its own package pushes, or that a build-excluded
    file of its package links or writes under the new name."""
    out = shrink_fix(run, workdir, {
        "internal/r/r.go": 'package r\n\nimport _ "unsafe"\n\n//go:linkname Pushed\nfunc Pushed() {}\n\nfunc Free() {}\n',
        "internal/rx/rx.go": "package rx\n\nfunc Clash() {}\n\nfunc Linked() {}\n\nfunc Clean() {}\n",
        "internal/rx/rx_never.go": """//go:build never

package rx

import _ "unsafe"

var clash = 1

//go:linkname Linked example.com/rename/internal/rx.pushed
""",
    }, ("internal/r/r.go", "internal/rx/rx.go"))
    assert_golden(out, __file__, "linkname")


def test_member_name_guards(run, workdir):
    """CATCHES: a rename of a method or field to a name its type, a type promoting it (named or an unnamed
    struct), or an ambiguous selection already holds, or that a named interface or a type assertion asks for;
    and one that renames both of two members lowering to one name."""
    out = shrink_fix(run, workdir, {
        "internal/r/r.go": """package r

type Named struct {
	name string
	Size int
}

func (Named) Name() string { return "" }

func (Named) size() int { return 0 }

type Asked struct{}

func (Asked) Run() {}

type Quiet struct{}

func (Quiet) Hush() {}

type husher interface{ hush() }

type Base struct{}

func (Base) Hop() {}

type derived struct {
	Base
	hop int
}

type Boxed struct {
	Size int
}

type T struct {
	F int
}

type U struct {
	F int
	f int
}

type amb struct {
	T
	U
}

type First struct {
	ID int
}

type Second struct {
	Id int
}

type both struct {
	First
	Second
}

type Pair struct {
	ID int
	Id int
}

func uses() int {
	_ = func(v any) bool { _, ok := v.(interface{ run() }); return ok }
	var _ husher
	var v struct {
		Boxed
		size int
	}
	return Named{}.Size + Named{}.size() + len(Named{}.name+Named{}.Name()) + derived{}.hop + v.Size + v.size +
		amb{}.f + T{}.F + U{}.F + both{}.ID + both{}.Id + Pair{}.ID + Pair{}.Id
}

var (
	_ = Asked{}.Run
	_ = Quiet{}.Hush
	_ = derived{}.Hop
	_ = uses
)
""",
    }, ("internal/r/r.go",))
    assert_golden(out, __file__, "members")


def test_embedded_type_guards(run, workdir):
    """CATCHES: a rename of an embedded type whose new field name a struct embedding it already holds, or that
    would make a deeper selection ambiguous; and a rename that misses the selector naming an embedded field,
    through a pointer, an alias, or two paths of a diamond."""
    out = shrink_fix(run, workdir, {
        "internal/r/r.go": """package r

type Emb struct{}

type Holder struct {
	Emb
	emb int
}

type Inner struct{}

type outer struct{ Inner }

type Shared struct {
	Val int
}

type left struct{ Shared }

type right struct{ Shared }

type diamond struct {
	left
	right
}

type Pointed struct{}

type Aliased struct{}

type AliasOfAliased = Aliased

type embedder struct {
	*Pointed
	AliasOfAliased
}

type Nest struct{}

type hopper struct{}

func (hopper) nest() int { return 0 }

type nested struct{ Nest }

type stack struct {
	nested
	hopper
}

type basic struct{ int }

var (
	_ = Holder{}.Emb
	_ = Holder{}.emb
	_ = outer{}.Inner
	_ = embedder{}.Pointed
	_ = embedder{}.AliasOfAliased
	_ = stack{}.nest()
	_ = diamond{}
	_ = basic{}.int
)
""",
    }, ("internal/r/r.go",))
    assert_golden(out, __file__, "embedded")


def test_claims_between_fixes_of_one_run(run, workdir):
    """CATCHES: two fixes of one run that claim one new name (Kept/KEPT, Wrap/WRAP, Span/SPAN), producing a
    clash, or that withhold both; the report of the loser reads as taken, as the next run would read it."""
    out = shrink_fix(run, workdir, {
        "internal/r/r.go": """package r

func Keep() Kept { return Kept{} }

type Kept struct{}

func KEPT() *Toy { return nil }

type Toy struct{}

type Wrap struct{}

func WRAP() Wrap { return Wrap{} }

type Pv struct{}

func (Pv) SPAN() {}

type Span struct{}

type spanIn struct{ Span }

type spanOut struct {
	spanIn
	Pv
}

var (
	_ = Keep
	_ = KEPT
	_ = WRAP
	_ = spanOut{}
)
""",
        "internal/r/r_test.go": "package r\n\nfunc ExampleKeep() {}\n",
    }, ("internal/r/r.go",))
    assert_golden(out, __file__, "claims")


def test_generic_alias_and_literal_renames(run, workdir):
    """CATCHES: a rename that misses a selection on an instantiated generic type, a field written in an unkeyed or
    keyed literal of its own package, an alias of a type, or that renames Len to the predeclared len."""
    out = shrink_fix(run, workdir, {
        "internal/r/r.go": """package r

type Alias = Pair

type Pair struct {
	K int
}

type Level int

type Local struct {
	A int
}

type List[E any] struct {
	Items []E
}

func (l *List[E]) Len() int { return len(l.Items) }

func uses() int {
	var l List[int]
	return l.Len() + len(l.Items) + Local{1}.A + Local{A: 2}.A + Pair{}.K
}

var (
	_ Alias
	_ Level
	_ = uses
	_ = float64(Level(1))
	_ = []int{1}
)
""",
    }, ("internal/r/r.go",))
    assert_golden(out, __file__, "generics")


def test_line_directive_does_not_misplace_the_edit(run, workdir):
    """CATCHES: a fix that follows a //line directive to the fake file name, editing nothing or the wrong place;
    reports and edits must use the real file."""
    out = shrink_fix(run, workdir, {
        "internal/r/line.go": "package r\n\n//line fake.tmpl:1\nfunc Lined() int { return 1 }\n\nvar _ = Lined\n",
    }, ("internal/r/line.go",))
    assert_golden(out, __file__, "line_directive")


def test_fix_preserves_file_mode(run, workdir):
    """CATCHES: a -fix that rewrites a file with a different permission mode than it had."""
    write_files(workdir, {"go.mod": gomod(MOD), "internal/r/r.go": "package r\n\nfunc Plain() {}\n"})
    (workdir / "internal/r/r.go").chmod(0o640)
    r = run(["shrink", "-fix"])
    mode = oct((workdir / "internal/r/r.go").stat().st_mode & 0o777)
    assert transcript(r, workdir, ("internal/r/r.go",)) + f"\nmode: {mode}\n" == \
        "exit: 0\n--- stdout\n\n--- stderr\n\n--- file internal/r/r.go\npackage r\n\nfunc plain() {}\n\nmode: 0o640\n"
