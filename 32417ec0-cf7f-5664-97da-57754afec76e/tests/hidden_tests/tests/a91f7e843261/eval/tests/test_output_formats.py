"""The analyzer's command line: patterns and file arguments, -json, -c, -fix and -diff, help, and odd inputs."""

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


TWO_PACKAGES = {
    "go.mod": GO_MOD,
    "a/user.go": "package a\n\nfunc userHelper() int { return 1 }\n",
    "a/order.go": "package a\n\nfunc orderRun() int { return userHelper() }\n\nvar _ = orderRun\n",
    "b/user.go": "package b\n\n// userBox holds a count.\ntype userBox struct {\n\tn int\n\tm int\n}\n",
    "b/order.go": "package b\n\nvar _ = userBox{}.n\n\nfunc orderMake() userBox {\n\treturn userBox{n: 1, m: 2}\n}\n\n"
                  "var _ = orderMake\n",
}


def test_text_output_for_every_package(ds, workdir):
    """CATCHES: an analyzer that prints diagnostics in a different order, with different positions, without the
    tab-indented use sites, or exits other than 3 when it reports."""
    write_tree(workdir, TWO_PACKAGES)
    out = ds(["./..."])
    assert out.transcript == golden("text_every_package")


def test_several_patterns(ds, workdir):
    """CATCHES: an analyzer that analyzes only the first of several package patterns."""
    write_tree(workdir, TWO_PACKAGES)
    out = ds(["./b", "./a"])
    assert out.transcript == golden("several_patterns")


def test_relative_package_directory(ds, workdir):
    """CATCHES: an analyzer that cannot be pointed at one package by directory, or run from inside it with ."""
    write_tree(workdir, TWO_PACKAGES)
    named = ds(["./a"])
    inside = ds(["."], cwd=workdir / "b")
    assert named.transcript + "\n" + inside.transcript == golden("package_directory")


def test_file_arguments(ds, workdir):
    """CATCHES: an analyzer that rejects .go file arguments, or that does not treat them as one ad hoc package
    (command-line-arguments) holding only the named files."""
    write_tree(workdir, TWO_PACKAGES)
    both = ds(["a/user.go", "a/order.go"])
    js = ds(["-json", "b/user.go", "b/order.go"])
    one = ds(["a/user.go"])
    assert "\n".join([both.transcript, js.transcript, one.transcript]) == golden("file_arguments")


def test_json_output(ds, workdir):
    """CATCHES: a -json output that differs in its nesting by package and analyzer, its keys, its positions and
    end positions, its suggested fixes (byte offsets and inserted text), its related use sites, or that
    exits non-zero."""
    write_tree(workdir, TWO_PACKAGES)
    out = ds(["-json", "./..."])
    assert out.transcript == golden("json_output")


def test_json_for_a_clean_package(ds, workdir):
    """CATCHES: a -json that prints nothing, or an entry with an empty list, for a package with no diagnostics."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc Run() int { return 1 }\n"})
    out = ds(["-json", "./..."])
    assert out.transcript == golden("json_clean")


def test_context_lines(ds, workdir):
    """CATCHES: a -c that prints a different number of context lines, numbers them differently, or omits them
    for the attached use sites."""
    write_tree(workdir, TWO_PACKAGES)
    zero = ds(["-c=0", "./..."])
    two = ds(["-c", "2", "./b"])
    assert zero.transcript + "\n" + two.transcript == golden("context_lines")


def test_without_tests(ds, workdir):
    """CATCHES: an analyzer that reads _test.go files under -test=false, or ignores them by default."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": "package x\n\nfunc helper() int { return 1 }\n",
        "order_test.go": "package x\n\nimport \"testing\"\n\nfunc TestOrder(t *testing.T) { _ = helper() }\n",
        "user_test.go": "package x\n\nimport \"testing\"\n\nfunc TestUser(t *testing.T) { _ = helper() }\n",
    })
    with_tests = ds(["./..."])
    without = ds(["-test=false", "./..."])
    assert with_tests.transcript + "\n" + without.transcript == golden("without_tests")


def test_fix_then_clean(ds, workdir):
    """CATCHES: a -fix that leaves a file unformatted, edits other files, prints the diagnostics it fixed, or
    exits non-zero when every diagnostic had a fix."""
    write_tree(workdir, TWO_PACKAGES)
    fix = ds(["-fix", "./..."])
    tree = snapshot_tree(workdir)
    after = ds(["./..."])
    assert "\n".join([fix.transcript, tree, after.transcript]) == golden("fix_then_clean")


def test_diff_leaves_files_alone(ds, workdir):
    """CATCHES: a -fix -diff that writes the files instead of printing a unified diff, or prints the diff with
    different headers or hunks."""
    write_tree(workdir, TWO_PACKAGES)
    diff = ds(["-fix", "-diff", "./..."])
    assert diff.transcript + "\n" + snapshot_tree(workdir) == golden("diff_only")


def test_fix_with_a_diagnostic_it_cannot_fix(ds, workdir):
    """CATCHES: a -fix that rewrites a declaration whose own directive stated its scope, skips the fix it can
    apply beside it, or prints diagnostics or exits non-zero (-fix applies what it can, silently)."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": "package x\n\n//declscope:private\nfunc forced() int { return 1 }\n\nfunc helper() int { return 2 }\n",
        "order.go": "package x\n\nfunc orderRun() int { return forced() + helper() }\n\nvar _ = orderRun\n",
    })
    fix = ds(["-fix", "./..."])
    assert fix.transcript + "\n" + snapshot_tree(workdir) == golden("fix_with_unfixable")


def test_rename_fix_across_files(ds, workdir):
    """CATCHES: a qualify rename that misses a reference in another file or a test file, or a -diff that does
    not print one hunk per file touched."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "user.go": "package x\n\n// count is how many users there are.\nvar count = 10\n\n"
                   "func limit() int { return count * 2 }\n\nfunc (u *User) id() int { return u.ID }\n\n"
                   "type User struct{ ID int }\n",
        "order.go": "//declscope:shared\n\npackage x\n\nfunc orderTotal(u *User) int { return count + limit() + u.id() }\n\n"
                    "var _ = orderTotal\n",
        "user_test.go": "package x\n\nimport \"testing\"\n\nfunc TestLimit(t *testing.T) {\n\tif limit() != 2*count {\n"
                        "\t\tt.Fatal(limit())\n\t}\n}\n",
    })
    before = ds(["./..."])
    diff = ds(["-fix", "-diff", "./..."])
    fix = ds(["-fix", "./..."])
    tree = snapshot_tree(workdir)
    after = ds(["./..."])
    assert "\n".join([before.transcript, diff.transcript, fix.transcript, tree, after.transcript]) == golden(
        "rename_across_files")


def test_help_and_bare_invocation(ds, workdir):
    """CATCHES: a help text that does not list the subcommands before the flags, a bare invocation that does not
    print the same help and exit 1, or a flag-only invocation that adds the subcommands."""
    write_tree(workdir, {"go.mod": GO_MOD})
    help_flag = ds(["-h"])
    bare = ds([])
    flags_only = ds(["-test=false"])
    assert "\n".join([help_flag.transcript, bare.transcript, flags_only.transcript]) == golden("help")


def test_flags_json(ds, workdir):
    """CATCHES: a -flags that prints a different list of analyzer flags, or different names, kinds or usage
    strings."""
    out = ds(["-flags"])
    assert out.transcript == golden("flags_json")


def test_bad_flag_values(ds, workdir):
    """CATCHES: a -V that accepts a value other than full, or an unknown flag that is not refused with the help
    and exit status 2."""
    write_tree(workdir, {"go.mod": GO_MOD})
    v = ds(["-V=yes"])
    unknown = ds(["-bogus", "./..."])
    assert v.transcript + "\n" + unknown.transcript == golden("bad_flags")


def test_package_with_type_errors(ds, workdir):
    """CATCHES: an analyzer that reports nothing and exits 0 for a package that does not type-check, instead of
    printing the error and that the analysis was skipped, with exit status 1."""
    write_tree(workdir, {"go.mod": GO_MOD, "p/p.go": "package p\n\nfunc broken() int { return \"x\" }\n"})
    out = ds(["./..."])
    assert out.transcript == golden("type_errors")


def test_missing_directory_and_empty_module(ds, workdir):
    """CATCHES: an analyzer that passes silently for a directory that does not exist or a module with no
    package."""
    write_tree(workdir, {"go.mod": GO_MOD})
    missing = ds(["./nope"])
    empty = ds(["./..."])
    assert missing.transcript + "\n" + empty.transcript == golden("missing_and_empty")


def test_crlf_bom_and_unicode_file_names(ds, workdir):
    """CATCHES: an analyzer that misreads a directive on a CRLF line, a file opening with a UTF-8 byte order
    mark, or derives a different namespace from a non-ASCII file name; and a -fix that does not rewrite the
    CRLF file with LF line endings as the formatter does."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": b"package x\r\n\r\n//declscope:shared\r\nfunc wide() int { return 1 }\r\n\r\nfunc helper() int { return 1 }\r\n",
        "order.go": b"\xef\xbb\xbfpackage x\n\nfunc orderRun() int { return helper() + wide() }\n\nvar _ = orderRun\n",
        "用户.go": "package x\n\nfunc 用户Run() int { return helper() }\n\nvar _ = 用户Run\n",
    })
    before = ds(["./..."])
    fix = ds(["-fix", "./..."])
    raw = (workdir / "user.go").read_bytes()
    after = ds(["./..."])
    assert "\n".join([before.transcript, fix.transcript, repr(raw), after.transcript]) == golden("crlf_bom_unicode")


def test_empty_and_comment_only_files(ds, workdir):
    """CATCHES: an analyzer that counts a file holding only a package clause and comments (a doc.go) as a second
    namespace, and so turns the naming rule on under ondemand."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
        "doc.go": "// Package x does things.\npackage x\n",
        "empty.go": "package x\n",
        "worker.go": "package x\n\nfunc helper() int { return 1 }\n\nvar _ = helper\n",
    })
    out = ds(["./..."])
    shape = ds(["inspect", "-format=json", "."])
    assert out.transcript + "\n" + shape.transcript == golden("comment_only_files")


def test_many_declarations(ds, workdir):
    """CATCHES: an analyzer that drops, merges or reorders diagnostics in a package with hundreds of crossing
    declarations, or a survey that miscounts them."""
    decls = "".join(f"func userF{i:03d}() int {{ return {i} }}\n\n" for i in range(250))
    uses = " + ".join(f"userF{i:03d}()" for i in range(250))
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": "package x\n\n" + decls,
        "order.go": f"package x\n\nfunc orderSum() int {{\n\treturn {uses}\n}}\n\nvar _ = orderSum\n",
    })
    out = ds(["./..."])
    survey = ds(["survey"])
    assert out.transcript + "\n" + survey.transcript == golden("many_declarations")


def test_version_flag_shape(ds, workdir):
    """CATCHES: a -V=full whose line does not have the tool-ID shape go vet reads (program path, version,
    comments-go-here, and a sha256 buildID on one line, exit 0), here with the build-specific parts masked."""
    import re

    out = ds(["-V=full"])
    masked = re.sub(r"^/\S+ version [^ /]+ comments-go-here buildID=[0-9a-f]{64}\n$",
                    "PROGRAM version VERSION comments-go-here buildID=HASH\n", out.stdout)
    assert f"exit {out.returncode}\n{masked}--- stderr\n{out.stderr}" == golden("version")
