"""The directive rule: every malformed, unknown, conflicting, duplicated or misplaced //declscope: directive, at the
file level and on declarations, and what such a directive no longer does."""

from conftest import assert_golden, gomod, transcript, write_files


def analyze(run, workdir, files, *args):
    write_files(workdir, {"go.mod": gomod("example.com/d"), **files})
    return transcript(run([*args, "./..."]), workdir)


def test_file_level_problems(run, workdir):
    """CATCHES: a file-level directive problem passed over or worded differently: a malformed comment, a declaration-
    only directive above the package clause, a namespace with no name or an invalid one, a duplicated namespace, core
    with an argument or twice, core beside a namespace, a scope with an argument, two scopes that conflict, a repeated
    scope, an ignore naming an unknown rule, and a repeated ignore."""
    out = analyze(run, workdir, {
        "a.go": """// declscope:shared
//declscope:bogus
//declscope:namespace
//declscope:namespace Billing
//declscope:namespace foo-bar

package d

func a() {}
""",
        "b.go": """//declscope:namespace billing
//declscope:namespace billing
//declscope:core
//declscope:core x
//declscope:core

package d

func b() {}
""",
        "c.go": """//declscope:shared now
//declscope:private
//declscope:shared
//declscope:private
//declscope:ignore nope
//declscope:ignore boundary
//declscope:ignore boundary

package d

func c() {}
""",
    })
    assert_golden(out, __file__, "file_level")


def test_declaration_level_problems(run, workdir):
    """CATCHES: a declaration directive problem passed over or worded differently: a scope with an argument, a
    conflicting pair, namespace or core after the package clause, an empty rule name, a trailing comma, an unknown rule,
    a malformed block comment, and a malformed or valid directive inside a function body (misplaced)."""
    out = analyze(run, workdir, {
        "user.go": """package d

//declscope:shared x
func userA() {}

//declscope:private
//declscope:shared
func userB() {}

//declscope:namespace user
func userC() {}

//declscope:core
func userD() {}

//declscope:ignore ,
func userE() {}

//declscope:ignore boundary,
func userF() {}

//declscope:ignore surplus, qualify ,nope
func userG() {}

/*declscope:shared*/
func userH() {}

func userI() {
	// declscope:shared
	//declscope:ignore
	//declscope:bogus
	_ = 1
}
""",
        "order.go": "package d\n\nvar _ = []any{userA, userB, userC, userD, userE, userF, userG, userH, userI}\n",
    })
    assert_golden(out, __file__, "decl_level")


def test_namespace_spelled_as_a_keyword_is_accepted(run, workdir):
    """CATCHES: a namespace directive that refuses a Go keyword (map.go, range.go have such namespaces) or accepts
    an exported name; the keyword namespace joins files as any other name does."""
    out = analyze(run, workdir, {
        "map.go": "package d\n\nfunc lookup() int { return 1 }\n",
        "other.go": "//declscope:namespace map\n\npackage d\n\nvar _ = lookup()\n",
        "third.go": "//declscope:namespace Map\n\npackage d\n\nvar _ = lookup()\n",
    })
    assert_golden(out, __file__, "keyword_namespace")


def test_directive_rule_survives_unused_off_and_ignores(run, workdir):
    """CATCHES: rules.unused: off switching off the directive rule too, or a file-level ignore of directive that does
    not silence the file's directive reports (and is itself reported unused where nothing needed it)."""
    out = analyze(run, workdir, {
        ".declscope.yaml": "rules:\n  unused: off\n",
        "a.go": "package d\n\n//declscope:bogus\nfunc a() {}\n",
        "b.go": "//declscope:ignore directive\n\npackage d\n\n//declscope:bogus\nfunc b() {}\n",
        "c.go": "//declscope:ignore directive\n\npackage d\n\nfunc c() {}\n",
    })
    assert_golden(out, __file__, "rule_survives")


def test_export_and_linkname_directives_block_the_rename(run, workdir):
    """CATCHES: a qualify rename offered for a function a //go:linkname or cgo-style //export comment names as text,
    or an //export comment with no name treated as naming something."""
    out = analyze(run, workdir, {
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "user.go": """package d

import _ "unsafe"

//export pushed
func pushed() {}

//go:linkname linked
func linked() {}

//export
func free() {}
""",
    }, "-json")
    assert_golden(out, __file__, "linkname_export")


def test_strict_fix_removes_a_trailing_redundant_directive(run, workdir):
    """CATCHES: a strict unused fix that deletes the whole line of a trailing redundant directive (and with it the
    declaration), or leaves a stray carriage return in a CRLF file; only the comment goes."""
    write_files(workdir, {
        "go.mod": gomod("example.com/d"),
        "lf.go": "package d\n\nfunc lfA() {} //declscope:private\n\nvar _ = lfA\n",
    })
    (workdir / "crlf.go").write_bytes(b"package d\r\n\r\nfunc crlfA() {} //declscope:private\r\n\r\nvar _ = crlfA\r\n")
    out = transcript(run(["./..."]), workdir)
    fixed = transcript(run(["-fix", "./..."]), workdir)
    after = "".join(f"--- {name}\n{(workdir / name).read_bytes()!r}\n" for name in ("lf.go", "crlf.go"))
    assert_golden(out + "\n=== -fix\n" + fixed + after, __file__, "trailing_removal")
