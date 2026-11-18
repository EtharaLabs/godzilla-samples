"""The examples the README documents, run as written: each one pins a documented report, fix or file."""

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


DOMAIN = {
    "go.mod": GO_MOD,
    "domain/domain.go": "package domain\n\ntype User struct {\n\tID    int64\n\tEmail string\n}\n\n"
                        "type Order struct {\n\tID         int64\n\tBuyerEmail string\n}\n",
}

USER_REPOSITORY = """package database

import (
	"context"
	"database/sql"
	"strings"

	"example.com/app/domain"
)

type UserRepository struct{ db *sql.DB }

func (r *UserRepository) Find(ctx context.Context, id int64) (*domain.User, error) {
	row := r.db.QueryRowContext(ctx, `SELECT id, email FROM users WHERE id = ?`, id)
	return scanUser(row)
}

func scanUser(row *sql.Row) (*domain.User, error) {
	var u domain.User
	var email string
	if err := row.Scan(&u.ID, &email); err != nil {
		return nil, err
	}
	u.Email = normalizeEmail(email)
	return &u, nil
}

func normalizeEmail(s string) string {
	return strings.ToLower(strings.TrimSpace(s))
}
"""

ORDER_REPOSITORY = """package database

import (
	"database/sql"

	"example.com/app/domain"
)

type OrderRepository struct{ db *sql.DB }

func scanOrder(rows *sql.Rows) (domain.Order, error) {
	var o domain.Order
	var email string
	if err := rows.Scan(&o.ID, &email); err != nil {
		return domain.Order{}, err
	}
	o.BuyerEmail = normalizeEmail(email)
	return o, nil
}
"""


def test_what_it_reports(ds, workdir):
    """CATCHES: an analyzer that does not report normalizeEmail at user_repository.go:28:6 with the use at
    order_repository.go:17:17, as the README's first example shows; and one that still reports once the helper
    moves to email.go under //declscope:shared, where both repositories may use it."""
    write_tree(workdir, {**DOMAIN, "database/user_repository.go": USER_REPOSITORY,
                         "database/order_repository.go": ORDER_REPOSITORY})
    before = ds(["./..."])
    moved = USER_REPOSITORY.replace("\nfunc normalizeEmail(s string) string {\n\treturn strings.ToLower(strings.TrimSpace(s))\n}\n", "")
    moved = moved.replace('\t"strings"\n', "")
    write_tree(workdir, {
        "database/user_repository.go": moved,
        "database/email.go": "package database\n\nimport \"strings\"\n\n//declscope:shared\nfunc normalizeEmail(s string) string {\n"
                             "\treturn strings.ToLower(strings.TrimSpace(s))\n}\n",
    })
    after = ds(["./..."])
    assert before.transcript + "\n" + after.transcript == golden("what_it_reports")


def test_naming_rule_on_the_repository_example(ds, workdir):
    """CATCHES: a naming rule that does not ask scanUser to carry userRepository, with the README's rename
    advice, and that is satisfied once the file joins the user namespace by directive."""
    write_tree(workdir, {**DOMAIN, ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
                         "database/user_repository.go": USER_REPOSITORY,
                         "database/order_repository.go": ORDER_REPOSITORY})
    before = ds(["./..."])
    write_tree(workdir, {"database/user_repository.go": "//declscope:namespace user\n\n" + USER_REPOSITORY})
    after = ds(["./..."])
    assert before.transcript + "\n" + after.transcript == golden("naming_repository")


NAMESPACE_FILES = [
    "user_repository.go", "user_repository_test.go", "parser_linux.go", "parser_test_linux.go",
    "parser_linux.pb.go", "parser.x_linux.go", "user_id.go", "user_ids.go", "parse_json.go", "foo-bar.go",
    "Foo.go", "HTTPServer.go", "URLs.go", "IPv4.go", "2fa_auth.go", "用户.go",
]


def test_namespace_of_each_file_name(ds, workdir):
    """CATCHES: a namespace derivation that differs from the README's table: test files sharing their subject,
    GOOS suffixes dropped only before the first dot, _test only at the end, initialisms and their plurals
    spelled the Go way, separators and PascalCase stems turned to lowerCamelCase, digits and non-Latin
    letters kept."""
    files = {"go.mod": GO_MOD}
    for i, name in enumerate(NAMESPACE_FILES):
        if name.endswith("_test.go"):
            files[name] = f"package x\n\nfunc testDecl{i}() int {{ return {i} }}\n"
        else:
            files[name] = f"package x\n\nfunc decl{i}() int {{ return {i} }}\n"
    write_tree(workdir, files)
    out = ds(["inspect", "-format=json", "."], env_overrides={"GOOS": "linux"})
    assert out.transcript == golden("namespace_table")


def test_boundary_message_names_where_the_scope_came_from(ds, workdir):
    """CATCHES: a boundary report that words the scope's origin differently: the default, the declaration's own
    directive, its type's directive, or the file's directive; and a fix offered where the declaration states
    its own scope."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user_repository.go": "package database\n\nfunc normalizeEmail(s string) string { return s }\n\n"
                              "//declscope:private\nfunc normalizePhone(s string) string { return s }\n",
        "statement.go": "package database\n\n//declscope:private\ntype Statement struct {\n\tTable  string\n\twheres []string\n}\n",
        "util.go": "//declscope:private\n\npackage database\n\nfunc NormalizeName(s string) string { return s }\n",
        "order_repository.go": "package database\n\nfunc orderAll(s *Statement) string {\n"
                               "\treturn normalizeEmail(s.Table) + normalizePhone(\"\") + NormalizeName(\"\") + s.wheres[0]\n}\n\n"
                               "var _ = orderAll\n",
    })
    text = ds(["./..."])
    diff = ds(["-fix", "-diff", "./..."])
    assert text.transcript + "\n" + diff.transcript == golden("boundary_origins")


def test_methods_filed_in_another_file(ds, workdir):
    """CATCHES: an analyzer that binds a method to its type's file instead of its own, misses the field the
    method reaches, or asks for a different rename of the method; and one that still reports once
    //declscope:namespace statement joins the two files."""
    statement = "package database\n\ntype Statement struct {\n\tTable  string\n\twheres []string\n}\n"
    query = "package database\n\nfunc (s *Statement) Where(cond string) *Statement {\n\ts.wheres = append(s.wheres, cond)\n\treturn s\n}\n"
    write_tree(workdir, {"go.mod": GO_MOD, ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
                         "statement.go": statement, "query.go": query})
    split = ds(["./..."])
    write_tree(workdir, {"query.go": "//declscope:namespace statement\n\n" + query})
    joined = ds(["./..."])
    assert split.transcript + "\n" + joined.transcript == golden("methods_elsewhere")


UNUSED_MODES_FILE = """package app

type user struct {
	//declscope:private
	name string
}

//declscope:shared
func Helper() {}

//declscope:ignore boundary
func greet(u user) string { return u.name }
"""


def test_unused_modes_on_one_file(ds, workdir):
    """CATCHES: an unused rule that reports differently under off, loose and strict than the README's table:
    nothing under off, a scope-independent reason under loose, the current-config reason under strict, and
    the unused ignore under both."""
    write_tree(workdir, {"go.mod": GO_MOD, "user.go": UNUSED_MODES_FILE,
                         "off.yaml": "rules:\n  unused: off\n", "loose.yaml": "rules:\n  unused: loose\n",
                         "strict.yaml": "rules:\n  unused: strict\n"})
    outs = [ds(["-config", f"{mode}.yaml", "./..."]).transcript for mode in ("off", "loose", "strict")]
    assert "\n".join(outs) == golden("unused_modes")


def test_strict_fix_deletes_one_directive_and_withholds_another(ds, workdir):
    """CATCHES: a strict unused fix that deletes a redundant directive the boundary report names, or keeps one
    nothing depends on, as the README's normalize/trim example shows."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": "package app\n\n//declscope:private\nfunc normalize() {}\n\n//declscope:private\nfunc trim() {}\n",
        "order.go": "package app\n\nvar _ = normalize\n",
    })
    before = ds(["./..."])
    diff = ds(["-fix", "-diff", "./..."])
    assert before.transcript + "\n" + diff.transcript == golden("strict_fix")


def test_silencing_unused_reports(ds, workdir):
    """CATCHES: an ignore that silences unused reports it should not (its own, a type's members, another rule's
    ignore) or fails to silence the ones it should, against the README's A, B, T, C, D example."""
    write_tree(workdir, {"go.mod": GO_MOD, "user.go": """package app

//declscope:shared
//declscope:ignore unused
func A() {}

//declscope:shared
//declscope:ignore directive
func B() {}

//declscope:ignore unused
type T struct {
	//declscope:shared
	F int
}

//declscope:ignore qualify
//declscope:ignore unused
func C() {}

//declscope:ignore unused
func D() {}
"""})
    out = ds(["./..."])
    assert out.transcript == golden("silencing_unused")


MALFORMED = """package app

//declscope:foo
func a() {}

// declscope:shared
func b() {}

/*declscope:shared*/
func c() {}

//declscope:shared x
func d() {}

//declscope:private
//declscope:shared
func e() {}

//declscope:ignore foo
func f() {}

//declscope:ignore ,
func g() {}

//declscope:ignore boundary,
func h() {}

//declscope:shared
//declscope:shared
func i() {}

//declscope:ignore boundary,unused
//declscope:ignore unused,boundary
func j() {}

func k() {
	//declscope:shared
	_ = 1
}

//declscope:namespace billing
func l() {}

//declscope:core
func m() {}

var _ = []func(){a, b, c, d, e, f, g, h, i, j, k, l, m}
"""


def test_malformed_directive_on_declarations(ds, workdir):
    """CATCHES: a directive rule that words any of the README's malformed-directive reports differently, binds
    a malformed directive anyway, or reports a duplicate ignore (in any rule order) as unused too."""
    write_tree(workdir, {"go.mod": GO_MOD, "user.go": MALFORMED})
    out = ds(["./..."])
    assert out.transcript == golden("malformed_declarations")


def test_malformed_directive_on_files(ds, workdir):
    """CATCHES: a directive rule that words the file-level reports differently: an unknown file directive, a
    namespace with no name or an invalid one, core and namespace together, duplicates, arguments to core or
    a scope, conflicting file scopes, and an empty ignore rule list."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "a.go": "//declscope:foo\n\npackage app\n\nfunc aRun() {}\n",
        "b.go": "//declscope:namespace\n\npackage app\n\nfunc bRun() {}\n",
        "c.go": "//declscope:namespace Billing\n\npackage app\n\nfunc cRun() {}\n",
        "d.go": "//declscope:core\n//declscope:namespace billing\n\npackage app\n\nfunc dRun() {}\n",
        "e.go": "//declscope:core x\n//declscope:core\n//declscope:core\n\npackage app\n\nfunc eRun() {}\n",
        "f.go": "//declscope:shared x\n//declscope:shared\n//declscope:private\n//declscope:shared\n\npackage app\n\nfunc fRun() {}\n",
        "g.go": "//declscope:namespace gee\n//declscope:namespace gee\n\npackage app\n\nfunc geeRun() {}\n",
        "h.go": "//declscope:ignore ,\n//declscope:ignore nope\n//declscope:ignore boundary\n//declscope:ignore boundary\n"
                "/*declscope:core*/\n\npackage app\n\nfunc hRun() {}\n",
        "i.go": "package app\n\n//declscope:namespace late\n//declscope:core\n\nfunc iRun() {}\n",
        "uses.go": "package app\n\nvar _ = []func(){aRun, bRun, cRun, dRun, eRun, fRun, geeRun, hRun, iRun}\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("malformed_files")


def test_keyword_namespace_and_placements(ds, workdir):
    """CATCHES: a namespace directive refused for a Go keyword (import.go's namespace), or not read in each of
    the three placements the README accepts: a blank line before package, directly above it, or at the
    bottom of the package doc comment."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "a.go": "//declscope:namespace import\n\npackage app\n\nfunc importA() {}\n",
        "b.go": "//declscope:namespace billing\npackage app\n\nfunc billingB() {}\n",
        "c.go": "// Package app bills users.\n//\n//declscope:namespace billing\npackage app\n\nfunc billingC() {}\n",
        "d.go": "//declscope:namespace billing\n\npackage app\n\nfunc dRun() {}\n",
        "uses.go": "package app\n\nvar _ = []func(){importA, billingB, billingC, dRun}\n",
    })
    out = ds(["./..."])
    shape = ds(["inspect", "-format=json", "."])
    assert out.transcript + "\n" + shape.transcript == golden("keyword_and_placements")


def test_block_and_spec_directives(ds, workdir):
    """CATCHES: a block directive that does not reach every spec, or a spec directive that does not override
    its block's, per the README's seed/limit example."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "user.go": "package app\n\n//declscope:shared\nvar (\n\tseed  = 1\n\t//declscope:private\n\tlimit = 2 // this one is private\n)\n",
        "order.go": "package app\n\nvar _ = seed + limit\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("block_and_spec")


def test_private_type_binds_exported_fields(ds, workdir):
    """CATCHES: an analyzer that leaves the exported fields of an unexported type shared under the type's
    //declscope:private, or that bounds them without it."""
    entry = "package app\n\n// Capitalized for encoding/json, not for an audience.\n%stype entry struct {\n" \
            "\tKey   string `json:\"key\"`\n\tValue []byte `json:\"value\"`\n}\n\nvar _ = entry{}\n"
    write_tree(workdir, {"go.mod": GO_MOD, "entry.go": entry % "",
                         "order.go": "package app\n\nfunc orderKey(e *entry) string { return e.Key + string(e.Value) }\n\n"
                                     "var _ = orderKey\n"})
    open_fields = ds(["./..."])
    write_tree(workdir, {"entry.go": entry % "//declscope:private\n"})
    bound = ds(["./..."])
    assert open_fields.transcript + "\n" + bound.transcript == golden("private_type_fields")


def test_core_namespace(ds, workdir):
    """CATCHES: a core that does not share one namespace across its files, asks core declarations for a prefix,
    lets other files use a core declaration without a crossing, or does not take a test of a core file into
    the core."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: ondemand\n",
        "client.go": "//declscope:core\n\npackage transport\n\nfunc dial() int { return 1 }\n",
        "conn.go": "//declscope:core\n\npackage transport\n\nfunc open() int { return dial() }\n",
        "client_test.go": "package transport\n\nimport \"testing\"\n\nfunc TestDial(t *testing.T) { _ = open() }\n\nfunc helper() {}\n",
        "retry.go": "package transport\n\nfunc retryOpen() int { return open() }\n\nfunc backoff() int { return 2 }\n\nvar _ = retryOpen() + backoff()\n",
        "shared.go": "//declscope:core\n//declscope:shared\n\npackage transport\n\nfunc wide() int { return 3 }\n\nvar _ = retryOpen\n",
        "use.go": "package transport\n\nvar _ = wide\n",
    })
    out = ds(["./..."])
    shape = ds(["inspect", "."])
    assert out.transcript + "\n" + shape.transcript == golden("core_namespace")


def test_what_carries_a_namespace(ds, workdir):
    """CATCHES: a naming rule whose match differs from the README: case-insensitive from a word boundary with
    a free right edge, the e-dropping and y-to-i inflections, never a stemmed name, and the vocabulary hint
    for an inflected namespace."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "user_id.go": "package app\n\nfunc userIDCache() int { return 1 }\n\nfunc userIdCache() int { return 2 }\n\n"
                      "func loadUserID() int { return 3 }\n\nfunc parseUserIds() int { return 4 }\n\n"
                      "func poweruserID() int { return 5 }\n\nvar _ = userIDCache() + userIdCache() + loadUserID() + "
                      "parseUserIds() + poweruserID()\n",
        "store.go": "package app\n\nfunc storing() int { return 1 }\n\nfunc story() int { return 2 }\n\nfunc storm() int { return 3 }\n\n"
                    "var _ = storing() + story() + storm()\n",
        "apply.go": "package app\n\nfunc applies() int { return 1 }\n\nfunc applied() int { return 2 }\n\nvar _ = applies() + applied()\n",
        "tracing.go": "package app\n\nfunc traceValue() int { return 1 }\n\nvar _ = traceValue\n",
        "user.go": "package app\n\nfunc user() int { return 1 }\n\nvar _ = user\n",
    })
    out = ds(["./..."])
    assert out.transcript == golden("carries_namespace")


def test_withheld_rename_that_would_capture(ds, workdir):
    """CATCHES: a rename that compiles and computes something else: count renamed to fooCount where a parameter
    of that name would capture it. The report stays and the fix is withheld."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "foo.go": "package app\n\nvar count = 10\n\nfunc Add(fooCount int) int { return fooCount + count }\n",
    })
    out = ds(["-json", "./..."])
    fix = ds(["-fix", "./..."])
    assert out.transcript + "\n" + fix.transcript + "\n" + snapshot_tree(workdir) == golden("withheld_capture")


def test_assembly_withholds_renames(ds, workdir):
    """CATCHES: a rename offered in a package holding an assembly file, which names Go functions by text the
    rename cannot follow."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n",
        "fast.go": "package app\n\nfunc sum() int { return 1 }\n\nvar _ = sum\n",
        "fast_other.s": "// assembly for another architecture\n",
    })
    out = ds(["-json", "./..."])
    assert out.transcript == golden("assembly_withholds")


def test_surplus_loose_and_strict(ds, workdir):
    """CATCHES: a surplus rule that reports differently from the README's examples: one report per unused
    //declscope:shared under loose, and under strict each field a used directive widens for nothing, with a
    fix that inserts //declscope:private on its own line without reordering fields."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "email.go": "package bank\n\n//declscope:shared\nfunc normalizeEmail(s string) string { return s }\n\nvar _ = normalizeEmail\n",
        "account.go": "package bank\n\n//declscope:shared\ntype account struct {\n\tid      int\n\tbalance int\n}\n\n"
                      "func accountDeposit(a *account, n int) { a.balance += n }\n\nvar _ = accountDeposit\n",
        "ledger.go": "package bank\n\nfunc ledgerKey(a account) int { return a.id }\n\nvar _ = ledgerKey\n",
        "loose.yaml": "rules:\n  surplus: loose\n",
    })
    loose = ds(["-config", "loose.yaml", "./..."])
    strict = ds(["./..."])
    diff = ds(["-fix", "-diff", "./..."])
    assert "\n".join([loose.transcript, strict.transcript, diff.transcript]) == golden("surplus_modes")


def test_shrink_readme_example(ds, workdir):
    """CATCHES: a shrink that reports Load (used by api) or Record (read by fmt through reflection), or that does
    not unexport Format and the doc comment opening with it, as the README describes."""
    write_tree(workdir, {
        "go.mod": GO_MOD,
        "internal/user/user.go": "package user\n\nimport \"fmt\"\n\nfunc Load(id int) string { return Format(id) }\n\n"
                                 "// Format renders an ID for display.\nfunc Format(id int) string { return fmt.Sprint(id) }\n\n"
                                 "type Record struct {\n\tID   int\n\tName string\n}\n\nfunc Dump(r Record) { fmt.Println(r) }\n",
        "api/api.go": "package api\n\nimport \"example.com/app/internal/user\"\n\nfunc Run() string { user.Dump(user.Record{}); "
                      "return user.Load(1) }\n",
    })
    report = ds(["shrink"])
    narrow = ds(["shrink", "./internal/user/..."])
    fix = ds(["shrink", "-fix", "./..."])
    analyzer = ds(["./..."])
    assert "\n".join([report.transcript, narrow.transcript, fix.transcript,
                      (workdir / "internal/user/user.go").read_text(), analyzer.transcript]) == golden("shrink_example")


def test_baseline_layout_example(ds, workdir):
    """CATCHES: a baseline that does not split entries between the root file, the file a nested config names and
    an existing nested default-named file, as the README's internal/billing and internal/legacy layout shows."""
    two = {"user.go": "package {p}\n\nfunc helper() int {{ return 1 }}\n",
           "order.go": "package {p}\n\nfunc orderRun() int {{ return helper() }}\n\nvar _ = orderRun\n"}
    files = {"go.mod": GO_MOD, "internal/billing/.declscope.yaml": "baseline: billing-baseline.yaml\n",
             "internal/legacy/.declscope-baseline.yaml": ""}
    for pkg in ("user", "billing", "legacy"):
        for name, body in two.items():
            files[f"internal/{pkg}/{name}"] = body.format(p=pkg)
    write_tree(workdir, files)
    rec = ds(["baseline", "-shrink=false", "./..."])
    after = ds(["./..."])
    assert "\n".join([rec.transcript, snapshot_tree(workdir), after.transcript]) == golden("baseline_layout")
