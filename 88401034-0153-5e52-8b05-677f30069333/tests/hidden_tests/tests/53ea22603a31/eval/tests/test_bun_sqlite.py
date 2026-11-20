"""bun:sqlite: Database/Statement API over SQLite — CRUD and JS type mapping, SQLiteError classes and
codes, transactions and savepoints, value binding (int52 boundary, BigInt, safeIntegers, blobs),
parameter forms and strict mode, statement lifecycle, SQL features, and file-backed databases."""

import sqlite3

from conftest import check_script, resources_for

G = resources_for(__file__)

PRELUDE = r'''
const { Database, Statement, SQLiteError, constants } = require("bun:sqlite");
const show = (v) => JSON.stringify(v, (k, x) => typeof x === "bigint" ? x + "n" : x instanceof Uint8Array ? "u8:" + Array.from(x).join(",") : x);
const fail = (label, f) => {
  try { console.log(label, "ok", show(f())); }
  catch (e) { console.log(label, e.constructor.name, e.name, e.code, e.errno, "|", e.message); }
};
'''


def test_crud_and_type_mapping(run, workdir):
    """CATCHES: wrong JS types for SQLite storage classes (INTEGER/REAL -> number, TEXT -> string, BLOB ->
    Uint8Array, NULL -> null), get() not returning null for no row, all()/values()/get() shapes,
    run() results ({changes, lastInsertRowid}, changes counted for UPDATE/DELETE, 0 for SELECT),
    db.exec running every statement of a multi-statement string, and column naming with aliases."""
    check_script(run, workdir, G, "crud_and_type_mapping", PRELUDE + r'''
const db = new Database(":memory:");
console.log("create", show(db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, val REAL, data BLOB, n INTEGER)")));
const ins = db.query("INSERT INTO t (name, val, data, n) VALUES ($name, $val, $data, $n)");
console.log("insert", show(ins.run({ $name: "alice", $val: 3.5, $data: new Uint8Array([1, 2, 3]), $n: 42 })));
console.log("insert", show(ins.run({ $name: "bob", $val: -0.25, $data: null, $n: 7 })));
console.log("insert", show(ins.run({ $name: "", $val: 1e300, $data: new Uint8Array(0), $n: -1 })));
const one = db.query("SELECT * FROM t WHERE id = ?").get(1);
console.log("types", typeof one.id, typeof one.name, typeof one.val, one.data instanceof Uint8Array, one.data.constructor.name,
            Buffer.isBuffer(one.data), Array.from(one.data).join(","), typeof one.n);
console.log("row", show(one));
console.log("missing", db.query("SELECT * FROM t WHERE id = 999").get(), show(db.query("SELECT * FROM t WHERE id = 999").all()));
console.log("values", show(db.query("SELECT id, name, data FROM t ORDER BY id").values()));
console.log("all", show(db.query("SELECT id AS key, upper(name) AS 'Upper Name', val * 2 FROM t ORDER BY id").all()));
console.log("update", show(db.query("UPDATE t SET n = n + 1 WHERE n > 0").run()));
console.log("select-run", show(db.query("SELECT * FROM t").run()));
console.log("delete", show(db.run("DELETE FROM t WHERE name = ?", "bob")));
console.log("exec", show(db.exec("INSERT INTO t (name) VALUES ('x'); INSERT INTO t (name) VALUES ('y'); UPDATE t SET val = 0 WHERE val IS NULL")));
console.log("after", show(db.query("SELECT id, name, val, n FROM t ORDER BY id").values()));
console.log("literal", show(db.query("SELECT 1 AS one, 1.0 AS onef, 1.5 AS f, 'x' AS s, x'00ff' AS b, NULL AS n, 9007199254740993 AS big, -0.0 AS negz").get()));
console.log("dup-names", show(db.query("SELECT 1 AS a, 2 AS a, 3 AS b").get()), show(db.query("SELECT 1 AS a, 2 AS a").values()));
console.log("count", show(db.query("SELECT count(*) FROM t").get()));
const blob = db.query("SELECT x'deadbeef' AS b").get().b;
console.log("blob", blob.constructor.name, blob.length, Buffer.from(blob).toString("hex"));
''')


def test_error_classes_and_codes(run, workdir):
    """CATCHES: SQLite failures not surfacing as SQLiteError (an Error subclass with own name/code/errno),
    wrong extended result codes/names (UNIQUE 2067, PRIMARYKEY 1555, NOTNULL 1299, CHECK 275, FOREIGNKEY
    787, TRIGGER 1811, DATATYPE 3091, READONLY 8, TOOBIG 18, MISMATCH 20) or a code set for plain
    SQLITE_ERROR, inexact engine
    messages, plain Error vs TypeError for binding/arity problems, and user-constructible SQLiteError."""
    check_script(run, workdir, G, "error_classes_and_codes", PRELUDE + r'''
const db = new Database();
db.run("PRAGMA foreign_keys = ON");
db.run("CREATE TABLE p (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, age INTEGER CHECK (age >= 0))");
db.run("CREATE TABLE c (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES p(id))");
db.run("INSERT INTO p VALUES (1, 'a', 5)");
fail("unique", () => db.run("INSERT INTO p VALUES (2, 'a', 5)"));
fail("primary-key", () => db.run("INSERT INTO p VALUES (1, 'b', 5)"));
fail("check", () => db.run("INSERT INTO p VALUES (3, 'c', -1)"));
fail("not-null", () => db.run("INSERT INTO p (id, age) VALUES (4, 1)"));
fail("foreign-key", () => db.run("INSERT INTO c VALUES (1, 99)"));
fail("foreign-key-prepared", () => db.query("INSERT INTO c VALUES (?, ?)").run(1, 99));
fail("unique-prepared", () => db.prepare("INSERT INTO p VALUES (?, ?, ?)").run(2, "a", 1));
fail("syntax-run", () => db.run("SELCT bad"));
fail("syntax-prepare", () => db.prepare("SELEC 1"));
fail("syntax-query", () => db.query("SELECT * FORM p"));
fail("no-column", () => db.query("SELECT nope FROM p").all());
fail("no-table", () => db.query("SELECT * FROM missing"));
fail("ambiguous", () => db.query("SELECT id FROM p, c").all());
fail("empty-sql", () => db.prepare(""));
fail("comment-only", () => db.prepare("-- nothing"));
fail("exec-partial", () => db.exec("INSERT INTO p VALUES (10, 'x', 1); INSERT INTO p VALUES (10, 'y', 1)"));
fail("after-partial", () => db.query("SELECT id, name FROM p ORDER BY id").all());
db.run("CREATE TRIGGER tr BEFORE INSERT ON c WHEN NEW.id > 100 BEGIN SELECT RAISE(ABORT, 'too big'); END");
fail("raise", () => db.run("INSERT INTO c VALUES (101, 1)"));
db.run("CREATE TABLE s (x INTEGER) STRICT");
fail("strict-table", () => db.run("INSERT INTO s VALUES ('abc')"));
fail("arity", () => db.query("SELECT ?1, ?2").all(1));
fail("arity-array", () => db.query("SELECT ?, ?").all([1, 2, 3]));
fail("bind-object", () => db.query("SELECT ?").all([{}]));
fail("bind-date", () => db.query("SELECT ?").all([new Date(0)]));
fail("bind-nested-array", () => db.query("SELECT ?").all([[1]]));
fail("bind-function", () => db.query("SELECT ?").all(() => 1));
fail("bind-symbol", () => db.query("SELECT ?").all(Symbol("s")));
db.run("PRAGMA query_only = ON");
fail("readonly", () => db.run("INSERT INTO c VALUES (5, 1)"));
db.run("PRAGMA query_only = OFF");
fail("rollback-without-tx", () => db.run("ROLLBACK"));
fail("commit-without-tx", () => db.run("COMMIT"));
fail("malformed-json", () => db.query("SELECT json('{bad') AS j").get());
fail("divide-by-zero-is-null", () => db.query("SELECT 1 / 0 AS x, 5 % 0 AS y").get());
fail("too-big", () => db.query("SELECT zeroblob(2000000000) AS z").get());
fail("datatype-mismatch", () => db.run("INSERT INTO p (id, name) VALUES ('abc', 'q')"));
fail("construct", () => new SQLiteError("x"));
try { db.run("SELCT"); } catch (e) {
  console.log("shape", e instanceof SQLiteError, e instanceof Error, Object.prototype.toString.call(e), String(e), show(Object.keys(e)),
              "code" in e, e.code === undefined);
}
try { db.run("INSERT INTO p VALUES (1, 'z', 0)"); } catch (e) { console.log("constraint-shape", String(e), show(Object.keys(e)), e.stack.split("\n")[0]); }
''')


def test_transactions_and_savepoints(run, workdir):
    """CATCHES: db.transaction() not committing on return / rolling back and rethrowing on throw,
    not forwarding arguments and `this` or the return value, nested transactions not using savepoints
    (an inner failure must undo only its own writes), missing deferred/immediate/exclusive variants,
    and manual BEGIN/SAVEPOINT/ROLLBACK TO statements misbehaving through db.run."""
    check_script(run, workdir, G, "transactions_and_savepoints", PRELUDE + r'''
const db = new Database(":memory:");
db.run("CREATE TABLE tx (a)");
const rows = () => show(db.query("SELECT a FROM tx ORDER BY rowid").values().map((r) => r[0]));
const t1 = db.transaction((n) => { db.run("INSERT INTO tx VALUES (?)", [n]); return n * 2; });
console.log("ret", t1(21), rows());
try {
  db.transaction(() => { db.run("INSERT INTO tx VALUES (99)"); throw new Error("boom"); })();
} catch (e) { console.log("threw", e.message, rows()); }
const inner = db.transaction(() => { db.run("INSERT INTO tx VALUES (10)"); });
const outer = db.transaction(() => {
  db.run("INSERT INTO tx VALUES (20)");
  try { db.transaction(() => { db.run("INSERT INTO tx VALUES (30)"); throw new Error("x"); })(); } catch (e) { console.log("inner failed", e.message); }
  inner();
  return "outer-done";
});
console.log("nested", outer(), rows());
const failingOuter = db.transaction(() => { inner(); db.run("INSERT INTO tx VALUES (40)"); throw new TypeError("outer boom"); });
try { failingOuter(); } catch (e) { console.log("outer threw", e.name, e.message, rows()); }
const tv = db.transaction(function (a, b) { return [this && this.tag, a, b]; });
console.log("variants", typeof tv.deferred, typeof tv.immediate, typeof tv.exclusive, show(tv.call({ tag: "T" }, 1, 2)),
            show(tv.immediate(3, 4)), show(tv.deferred()), show(tv.exclusive("e")));
const many = db.transaction((items) => { for (const it of items) db.query("INSERT INTO tx VALUES (?)").run(it); return items.length; });
console.log("batch", many([1, 2, 3]), db.query("SELECT count(*) n FROM tx").get().n);
const deep = db.transaction((d) => { db.run("INSERT INTO tx VALUES (?)", 100 + d); if (d < 3) deep(d + 1); else throw new Error("depth"); });
try { deep(0); } catch (e) { console.log("deep", e.message, db.query("SELECT count(*) n FROM tx WHERE a >= 100").get().n); }
const keepInner = db.transaction(() => {
  db.run("INSERT INTO tx VALUES (200)");
  try { deep(1); } catch (e) { console.log("caught", e.message); }
  db.run("INSERT INTO tx VALUES (201)");
});
keepInner();
console.log("partial", show(db.query("SELECT a FROM tx WHERE a >= 100 ORDER BY a").values()));
try { db.transaction(42); } catch (e) { console.log("not-a-function", e.name, e.message); }
db.run("BEGIN");
db.run("INSERT INTO tx VALUES ('manual')");
db.run("SAVEPOINT sp1");
db.run("INSERT INTO tx VALUES ('dropped')");
db.run("ROLLBACK TO sp1");
db.run("RELEASE sp1");
db.run("COMMIT");
console.log("manual", show(db.query("SELECT a FROM tx WHERE typeof(a) = 'text'").values()));
db.run("BEGIN");
fail("begin-twice", () => db.run("BEGIN"));
fail("tx-inside-manual", () => db.transaction(() => 1)());
db.run("ROLLBACK");
fail("tx-after-manual", () => db.transaction(() => 2)());
''')


def test_value_binding_and_safe_integers(run, workdir):
    """CATCHES: numbers bound with the wrong storage class (integral values in [-2^51, 2^51) are INTEGER,
    others and -0 are REAL; NaN -> NULL; booleans -> 0/1), BigInt binding and 64-bit wrap-around,
    TypedArrays of any element type bound as their raw bytes, strings with NUL/non-ASCII, and
    safeIntegers (per statement and per database) not returning exact BigInts or BigInt lastInsertRowid."""
    check_script(run, workdir, G, "value_binding_and_safe_integers", PRELUDE + r'''
const db = new Database(":memory:");
db.run("CREATE TABLE v (x)");
const ins = db.query("INSERT INTO v VALUES (?)");
const last = db.query("SELECT x, typeof(x) t, hex(x) h FROM v ORDER BY rowid DESC LIMIT 1");
const cases = [["42", 42], ["2^40", 2 ** 40], ["2^50", 2 ** 50], ["2^51-1", 2 ** 51 - 1], ["2^51", 2 ** 51], ["2^53", 2 ** 53],
  ["-2^51", -(2 ** 51)], ["-2^51-1", -(2 ** 51) - 1], ["1.5", 1.5], ["-0", -0], ["0", 0], ["NaN", NaN], ["Infinity", Infinity],
  ["-Infinity", -Infinity], ["MAX_VALUE", Number.MAX_VALUE], ["MIN_VALUE", Number.MIN_VALUE], ["0.1+0.2", 0.1 + 0.2],
  ["true", true], ["false", false], ["null", null], ["undefined", undefined], ["10n", 10n], ["-1n", -1n], ["2^63-1n", 2n ** 63n - 1n],
  ["-2^63n", -(2n ** 63n)], ["2^63n", 2n ** 63n], ["2^64n", 2n ** 64n], ["empty", ""], ["nul", "a\0b"], ["unicode", "😀é"],
  ["buffer", Buffer.from("hi")], ["u16", new Uint16Array([1, 256])], ["f32", new Float32Array([1])], ["i8", new Int8Array([-1, -128])],
  ["sub", new Uint8Array([9, 8, 7, 6]).subarray(1, 3)], ["empty-u8", new Uint8Array(0)]];
for (const [label, value] of cases) {
  ins.run(value);
  const r = last.get();
  console.log("bind", label, "->", r.t, r.h, typeof r.x === "number" ? String(r.x) : show(r.x));
}
db.run("CREATE TABLE n (v INTEGER)");
db.run("INSERT INTO n VALUES (9007199254740993), (-9007199254740993), (9223372036854775807), (-9223372036854775808), (42), (1.25)");
const sel = db.query("SELECT v FROM n ORDER BY rowid");
console.log("default", show(sel.values().map((r) => typeof r[0] + ":" + String(r[0]))));
console.log("chain", sel.safeIntegers() === sel);
console.log("safe", show(sel.values().map((r) => typeof r[0] + ":" + String(r[0]))));
console.log("get-safe", show(sel.get()), show(sel.all()[3]));
sel.safeIntegers(false);
console.log("off-again", show(sel.values().map((r) => typeof r[0])));
console.log("bigint-param-compare", show(db.query("SELECT v FROM n WHERE v = ?").safeIntegers(true).get(9007199254740993n)));
console.log("rowid-number", show(db.query("INSERT INTO n VALUES (1)").run()));
console.log("rowid-safe", show(db.query("INSERT INTO n VALUES (2)").safeIntegers(true).run()));
const sdb = new Database(":memory:", { safeIntegers: true });
sdb.run("CREATE TABLE z (v)");
const r1 = sdb.run("INSERT INTO z VALUES (5)");
const r2 = sdb.run("INSERT INTO z VALUES (?)", 6);
const r3 = sdb.query("INSERT INTO z VALUES (2.5)").run();
console.log("db-safe", typeof r1.lastInsertRowid, String(r1.lastInsertRowid), typeof r2.lastInsertRowid, String(r2.lastInsertRowid),
            typeof r3.lastInsertRowid, typeof r1.changes);
console.log("db-safe-rows", show(sdb.query("SELECT v, typeof(v) t FROM z").all()));
console.log("db-safe-off", show(sdb.query("SELECT v FROM z").safeIntegers(false).all()));
console.log("bool-and-null-params", show(db.query("SELECT ? AS a, ? AS b, ? AS c, ? AS d").get(true, false, null, undefined)));
''')


def test_parameter_forms_and_strict_mode(run, workdir):
    """CATCHES: wrong mapping of call shapes to bindings (varargs vs one array vs one named object vs a
    lone TypedArray), $x/:x/@x names needing their prefix outside strict mode (bare keys silently bind
    NULL) and bare names in strict mode (missing -> Error 'Missing parameter'), ?NNN numbering,
    positional count mismatches, parameterless statements ignoring args, and reuse of the previous
    bindings when a statement is re-run without arguments."""
    check_script(run, workdir, G, "parameter_forms_and_strict_mode", PRELUDE + r'''
const db = new Database(":memory:");
db.run("CREATE TABLE p (a, b, c)");
db.run("INSERT INTO p VALUES (?, ?, ?)", 1, 2, 3);
db.run("INSERT INTO p VALUES (?, ?, ?)", [4, 5, 6]);
db.query("INSERT INTO p VALUES ($a, :b, @c)").run({ $a: 7, ":b": 8, "@c": 9 });
db.query("INSERT INTO p VALUES ($a, :b, @c)").run({ a: 10, b: 11, c: 12 });
db.query("INSERT INTO p VALUES ($a, $b, $c)").run({ $a: 13, $c: 15, $extra: 99 });
console.log("forms", show(db.query("SELECT * FROM p ORDER BY rowid").values()));
console.log("numbered", show(db.query("SELECT ?1 AS a, ?1 AS b, ?2 AS c").get(7, 8)), show(db.query("SELECT ?3 AS c, ?1 AS a").get(1, 2, 3)));
console.log("numbered-array", show(db.query("SELECT ?2 AS two, ?1 AS one").get(["x", "y"])));
console.log("mixed", show(db.query("SELECT $n AS n, ? AS q").get({ $n: "named" })));
console.log("blob-arg", show(db.query("SELECT ? AS b").get(new Uint8Array([1, 2]))));
console.log("array-arg", show(db.query("SELECT ? AS x").get(["only"])));
const st = db.query("SELECT ? AS x, ? AS y");
console.log("paramsCount", st.paramsCount, db.query("SELECT 1").paramsCount, db.query("SELECT $a, $a, :b").paramsCount, db.query("SELECT ?5").paramsCount);
console.log("first", show(st.get(1, 2)));
console.log("reuse", show(st.get()), show(st.all()), st.toString());
console.log("rebind", show(st.get("p", "q")), st.toString());
fail("mismatch-few", () => db.query("INSERT INTO p VALUES (?, ?, ?)").run(1));
fail("mismatch-many", () => db.query("SELECT ?").get(1, 2));
console.log("zero-param-ignores", show(db.query("SELECT count(*) c FROM p").get(123)), show(db.query("SELECT 1 AS one").all({ $x: 1 })));
const sdb = new Database(":memory:", { strict: true });
sdb.run("CREATE TABLE s (a, b)");
sdb.query("INSERT INTO s VALUES ($a, $b)").run({ a: 10, b: 20 });
sdb.query("INSERT INTO s VALUES (:a, @b)").run({ a: 30, b: 40, unused: 0 });
sdb.query("INSERT INTO s VALUES (?, ?)").run(50, 60);
console.log("strict", show(sdb.query("SELECT * FROM s").all()));
fail("strict-missing", () => sdb.query("INSERT INTO s VALUES ($a, $b)").run({ a: 1 }));
fail("strict-prefixed", () => sdb.query("INSERT INTO s VALUES ($a, $b)").run({ $a: 1, $b: 2 }));
fail("strict-positional-to-named", () => sdb.query("SELECT $a AS a").get(5));
console.log("strict-get", show(sdb.query("SELECT $x AS x, $y AS y").get({ x: "X", y: null })));
console.log("strict-flag-with-readwrite", show(new Database(":memory:", { strict: true, readwrite: true, create: true }).query("SELECT $v AS v").get({ v: 1 })));
''')


def test_statement_lifecycle(run, workdir):
    """CATCHES: db.query() not caching statements by SQL text (db.prepare must not), wrong
    Statement.toString() (expanded SQL with the last bindings), columnNames/paramsCount, iterate() and
    for-of iteration (including early break), .as(Class) row mapping, finalize() idempotence and the
    'Statement has finalized' error, closed-database errors (RangeError for query, Error for run),
    and Statement not being directly constructible."""
    check_script(run, workdir, G, "statement_lifecycle", PRELUDE + r'''
const db = new Database(":memory:");
db.exec("CREATE TABLE it (id INTEGER, name TEXT); INSERT INTO it VALUES (1,'a'),(2,'b'),(3,'c')");
console.log("cached", db.query("SELECT 1") === db.query("SELECT 1"), db.prepare("SELECT 1") === db.prepare("SELECT 1"),
            db.query("SELECT 1") === db.query("SELECT 1 "), db.query("SELECT 1") instanceof Statement);
const q = db.query("SELECT id AS foo, name FROM it WHERE id = ?");
console.log("before-run", q.toString());
q.get(2);
console.log("toString", q.toString(), String(q));
q.get("it's");
console.log("toString-text", q.toString());
console.log("columnNames", show(q.columnNames), "paramsCount", q.paramsCount);
console.log("columnNames-star", show(db.query("SELECT *, id * 2 FROM it").columnNames), show(db.query("INSERT INTO it VALUES (9, 'z')").columnNames));
const seen = [];
for (const row of db.query("SELECT * FROM it ORDER BY id")) seen.push(row.id + row.name);
console.log("for-of", show(seen));
const it = db.query("SELECT * FROM it ORDER BY id").iterate();
console.log("next", show(it.next()), show(it.next()), show(it.next()), show(it.next()), show(it.next()));
const early = [];
for (const row of db.query("SELECT id FROM it ORDER BY id").iterate()) { early.push(row.id); if (row.id === 2) break; }
console.log("break", show(early), show(db.query("SELECT id FROM it ORDER BY id").all().map((r) => r.id)));
const filtered = db.query("SELECT name FROM it WHERE id > ? ORDER BY id");
console.log("iterate-params", show([...filtered.iterate(1)].map((r) => r.name)));
class Row { label() { return this.id + ":" + this.name.toUpperCase(); } }
const mapped = db.query("SELECT * FROM it ORDER BY id").as(Row);
const all = mapped.all();
console.log("as", all[0] instanceof Row, all.map((r) => r.label()).join(","), show(Object.keys(all[0])), mapped.get().label(),
            [...mapped].length, Object.getPrototypeOf(db.query("SELECT 1 AS x").get()) === Object.prototype);
const f = db.query("SELECT 1 AS x");
f.finalize();
f.finalize();
fail("finalized-get", () => f.get());
fail("finalized-columnNames", () => f.columnNames);
console.log("finalized-toString", f.toString());
console.log("recreated", show(db.query("SELECT 1 AS x").get()));
fail("construct-statement", () => new Statement());
const c = new Database(":memory:");
const cq = c.query("SELECT 1 AS one");
c.close();
c.close();
fail("closed-query", () => c.query("SELECT 1"));
fail("closed-prepare", () => c.prepare("SELECT 1"));
fail("closed-run", () => c.run("SELECT 1"));
fail("closed-exec", () => c.exec("SELECT 1"));
fail("closed-statement", () => cq.get());
console.log("surface", typeof Database.open, Database.MAX_QUERY_CACHE_SIZE, typeof Statement, constants.SQLITE_OPEN_READONLY,
            constants.SQLITE_OPEN_READWRITE, constants.SQLITE_OPEN_CREATE, constants.SQLITE_OPEN_MEMORY, constants.SQLITE_PREPARE_PERSISTENT,
            constants.SQLITE_FCNTL_RESET_CACHE, require("bun:sqlite").default === Database);
''')


def test_sql_features_through_queries(run, workdir):
    """CATCHES: result rows/values mangled for joins, aggregates (count/sum/avg/min/max/total/
    group_concat), GROUP BY/HAVING, ORDER BY/LIMIT/OFFSET, window functions, recursive CTEs, subqueries,
    set operations, collations, built-in string/number/date/JSON functions, views, triggers (whose
    writes this runtime counts in run().changes), UPSERT, RETURNING (rows from .all()), ALTER TABLE and
    AUTOINCREMENT bookkeeping."""
    check_script(run, workdir, G, "sql_features_through_queries", PRELUDE + r'''
const db = new Database(":memory:");
db.exec(`
CREATE TABLE dept (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER REFERENCES dept(id), salary REAL, hired TEXT);
INSERT INTO dept (name) VALUES ('eng'), ('ops'), ('empty');
INSERT INTO emp VALUES (1,'ann',1,120.5,'2020-01-15'),(2,'bob',1,99,'2019-06-01'),(3,'cid',2,80,'2021-03-10'),
                       (4,'dee',NULL,55.25,'2022-12-31'),(5,'eve',1,99,'2018-02-28');
`);
const q = (label, sql, ...p) => { try { console.log(label, show(db.query(sql).all(...p))); } catch (e) { console.log(label, "threw", e.message); } };
q("inner", "SELECT e.name, d.name AS dept FROM emp e JOIN dept d ON d.id = e.dept_id ORDER BY e.id");
q("left", "SELECT d.name, count(e.id) AS n FROM dept d LEFT JOIN emp e ON e.dept_id = d.id GROUP BY d.id ORDER BY d.id");
q("agg", "SELECT count(*) c, count(dept_id) cd, sum(salary) s, avg(salary) a, min(salary) mn, max(salary) mx, total(NULL) t, sum(NULL) sn, group_concat(name, '|') g FROM emp");
q("having", "SELECT dept_id, count(*) n, sum(salary) s FROM emp GROUP BY dept_id HAVING count(*) > 1 ORDER BY s DESC");
q("limit-offset", "SELECT name FROM emp ORDER BY salary DESC, name LIMIT ? OFFSET ?", 2, 1);
q("window", "SELECT name, rank() OVER (ORDER BY salary DESC) r, dense_rank() OVER (ORDER BY salary DESC) dr, row_number() OVER (PARTITION BY dept_id ORDER BY id) rn, sum(salary) OVER (ORDER BY id ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) running, lag(name) OVER (ORDER BY id) prev FROM emp ORDER BY id");
q("cte", "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x * 2 FROM n WHERE x < 100) SELECT group_concat(x) AS xs, count(*) AS c FROM n");
q("subquery", "SELECT name FROM emp WHERE salary > (SELECT avg(salary) FROM emp) ORDER BY name");
q("not-exists", "SELECT name FROM dept d WHERE NOT EXISTS (SELECT 1 FROM emp WHERE dept_id = d.id)");
q("in-between", "SELECT name FROM emp WHERE id IN (1, 3, 5) AND salary BETWEEN 80 AND 100 ORDER BY id");
q("like-glob", "SELECT name LIKE 'A%' l, name GLOB 'a*' g, name GLOB 'A*' g2, 'a_c' LIKE 'a\\_c' ESCAPE '\\' esc FROM emp WHERE id = 1");
q("case", "SELECT name, CASE WHEN salary >= 100 THEN 'high' WHEN salary >= 80 THEN 'mid' ELSE 'low' END band FROM emp ORDER BY id");
q("strings", "SELECT lower('ÀB') lo, upper('abc') up, length('héllo') len, length(x'0102') blen, substr('abcdef', 2, 3) sub, substr('abc', -2) neg, replace('a-b-c', '-', '+') rep, trim('  x  ') tr, ltrim('xxy', 'x') lt, instr('hello', 'll') ins, hex('AB') hx, quote('it''s') qt, char(72, 105) ch, unicode('é') uc, 'a' || 1 || NULL cat");
q("numbers", "SELECT printf('%05.2f|%-4s|%x|%d|%5.1e', 3.14159, 'ab', 255, -7, 12345.678) pf, abs(-4.5) ab, round(2.567, 2) rd, round(-2.5) rn, 7 / 2 idiv, 7 / 2.0 fdiv, 7 % 3 md, -7 % 3 md2, max(1, 'a', 2) mx, min(3, 2.5) mn, CAST('12abc' AS INTEGER) ci, CAST(3.9 AS INTEGER) ct, 1e308 * 10 inf, typeof(1) t1, typeof(1.0) t2, typeof('a') t3, typeof(x'00') t4, typeof(NULL) t5");
q("nulls", "SELECT coalesce(NULL, NULL, 'z') co, ifnull(NULL, 1) inn, nullif(3, 3) nf, NULL = NULL a, NULL IS NULL b, NULL AND 0 d, NULL OR 1 e, count(*) FILTER (WHERE dept_id IS NULL) f FROM emp");
q("dates", "SELECT date('2024-02-28', '+1 day') d1, date('2023-02-28', '+1 day') d2, datetime('2024-01-31 10:00:00', '+1 month') dt, strftime('%Y/%m/%d %H:%M %j %w', '2024-03-01 13:45:00') sf, julianday('2000-01-01') - julianday('1999-12-31') jd, date('2024-05-15', 'start of month', '-1 day') eom, strftime('%s', '1970-01-02') secs, time('12:34:56', '+90 minutes') tm, date(86400 * 365, 'unixepoch') ue, date('not a date') bad");
q("json", "SELECT json_extract('{\"a\":{\"b\":[1,2,3]}}', '$.a.b[1]') je, json_array(1, 'two', NULL) ja, json_object('k', 1, 'n', NULL) jo, json_array_length('[1,2,3]') jl, json_type('{\"x\":1.5}', '$.x') jt, json_valid('{') jv, json_set('{\"a\":1}', '$.b', 2) js");
q("json-each", "SELECT key, value, type FROM json_each('{\"x\":1,\"y\":[2],\"z\":\"s\"}') ORDER BY key");
q("json-group", "SELECT dept_id, json_group_array(name) names FROM emp WHERE dept_id IS NOT NULL GROUP BY dept_id ORDER BY dept_id");
q("union", "SELECT name FROM dept UNION SELECT 'zed' UNION ALL SELECT 'eng' ORDER BY 1");
q("intersect-except", "SELECT dept_id FROM emp INTERSECT SELECT id FROM dept EXCEPT SELECT 2");
q("collate", "SELECT x FROM (SELECT 'b' x UNION ALL SELECT 'A' UNION ALL SELECT 'a' UNION ALL SELECT 'B') ORDER BY x COLLATE NOCASE, x");
q("binary-order", "SELECT x FROM (SELECT 'b' x UNION ALL SELECT 'A' UNION ALL SELECT 'a' UNION ALL SELECT 'B' UNION ALL SELECT 10 UNION ALL SELECT 9.5 UNION ALL SELECT x'00' UNION ALL SELECT NULL) ORDER BY x");
q("distinct", "SELECT DISTINCT salary FROM emp ORDER BY salary");
db.exec("CREATE VIEW rich AS SELECT name FROM emp WHERE salary > 90; CREATE INDEX emp_salary ON emp(salary); CREATE TABLE log (msg TEXT); CREATE TRIGGER t_ins AFTER INSERT ON emp BEGIN INSERT INTO log VALUES ('added ' || NEW.name); END;");
q("view", "SELECT * FROM rich ORDER BY name");
q("schema", "SELECT type, name, tbl_name FROM sqlite_master ORDER BY type, name");
console.log("trigger-run", show(db.query("INSERT INTO emp (name, salary) VALUES (?, ?)").run("fay", 70)));
q("trigger-log", "SELECT * FROM log");
console.log("upsert", show(db.query("INSERT INTO dept (id, name) VALUES (1, 'ENG') ON CONFLICT(id) DO UPDATE SET name = excluded.name || '!'").run()));
q("after-upsert", "SELECT * FROM dept ORDER BY id");
q("returning", "UPDATE emp SET salary = salary * 2 WHERE dept_id = 1 RETURNING id, salary");
console.log("returning-run", show(db.query("UPDATE emp SET salary = salary + 1 WHERE id = 3 RETURNING salary").run()));
console.log("alter", show(db.run("ALTER TABLE emp ADD COLUMN active INTEGER DEFAULT 1")));
q("alter-select", "SELECT id, active FROM emp WHERE id < 3");
console.log("delete", show(db.query("DELETE FROM emp WHERE salary < ?").run(80)));
console.log("autoincrement", show(db.query("INSERT INTO dept (name) VALUES ('new')").run()), show(db.query("SELECT * FROM sqlite_sequence").all()));
q("or-replace", "INSERT OR REPLACE INTO dept (id, name) VALUES (2, 'OPS') RETURNING *");
q("or-ignore", "INSERT OR IGNORE INTO dept (id, name) VALUES (2, 'dup') RETURNING *");
q("pragma", "PRAGMA table_info(dept)");
q("generate-rows", "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r WHERE i < 1000) SELECT count(*) n, sum(i) s, max(i) mx FROM r");
''')


def test_file_backed_database(run, workdir):
    """CATCHES: file databases not persisted on close (content checked with an independent SQLite
    reader), wrong open-flag mapping (readonly, create:false, {} -> SQLITE_MISUSE, numeric flags,
    readwrite), creating files that must not be created, wrong SQLITE_CANTOPEN/READONLY/BUSY errors
    (a second connection blocked by IMMEDIATE/EXCLUSIVE locks without waiting),
    filename property, and serialize()/deserialize() not producing an independent in-memory copy."""
    check_script(run, workdir, G, "file_backed_database", PRELUDE + r'''
const fs = require("fs");
const db = new Database("data.db");
console.log("filename", db.filename);
db.exec("CREATE TABLE kv (k TEXT PRIMARY KEY, v)");
const ins = db.prepare("INSERT INTO kv VALUES (?, ?)");
db.transaction((rows) => { for (const r of rows) ins.run(...r); })([["a", 1], ["b", "two"], ["c", new Uint8Array([1, 2])], ["d", 2.5], ["e", null]]);
db.close();
console.log("header", JSON.stringify(fs.readFileSync("data.db").subarray(0, 16).toString("latin1")), fs.statSync("data.db").size % 512);
const ro = new Database("data.db", { readonly: true });
fail("readonly-read", () => ro.query("SELECT k, typeof(v) t FROM kv ORDER BY k").all());
fail("readonly-write", () => ro.run("INSERT INTO kv VALUES ('x', 4)"));
ro.close();
fail("create-false", () => new Database("missing.db", { create: false }));
fail("readonly-missing", () => new Database("missing2.db", { readonly: true }));
fail("empty-options", () => new Database("missing3.db", {}));
fail("numeric-readonly", () => { const d = new Database("data.db", constants.SQLITE_OPEN_READONLY); try { return d.query("SELECT count(*) n FROM kv").get(); } finally { d.close(); } });
fail("numeric-readonly-write", () => new Database("data.db", constants.SQLITE_OPEN_READONLY).run("DELETE FROM kv"));
fail("readwrite", () => { const d = new Database("data.db", { readwrite: true }); d.run("INSERT INTO kv VALUES ('f', 5)"); const n = d.query("SELECT count(*) n FROM kv").get(); d.close(); return n; });
fail("directory", () => new Database("."));
fail("missing-parent", () => new Database("no/such/dir/x.db"));
fail("static-open", () => { const d = Database.open("data.db"); try { return d.query("SELECT group_concat(k) g FROM kv").get(); } finally { d.close(); } });
console.log("created", fs.existsSync("missing.db"), fs.existsSync("missing2.db"), fs.existsSync("missing3.db"), fs.existsSync("no"));
console.log("memory-names", new Database(":memory:").filename, new Database().filename, new Database(null).filename);
const src = Database.open("data.db");
const img = src.serialize();
console.log("serialize", img.constructor.name, img.subarray(0, 15).toString(), img.length % 512);
const copy = Database.deserialize(img);
console.log("copy", show(copy.query("SELECT k FROM kv ORDER BY k").values()));
copy.run("INSERT INTO kv VALUES ('z', 26)");
console.log("independent", show(src.query("SELECT count(*) n FROM kv").get()), show(copy.query("SELECT count(*) n FROM kv").get()));
console.log("ctor-bytes", show(new Database(img).query("SELECT max(k) m FROM kv").get()), new Database(img).filename);
fail("garbage-image", () => new Database(new Uint8Array([1, 2, 3])).query("SELECT name FROM sqlite_master").all());
src.run("UPDATE kv SET v = 'updated' WHERE k = 'a'");
const other = new Database("data.db");
src.run("BEGIN IMMEDIATE");
fail("busy-begin", () => other.run("BEGIN IMMEDIATE"));
fail("busy-write", () => other.run("DELETE FROM kv"));
fail("read-during-reserved", () => other.query("SELECT count(*) n FROM kv").get());
src.run("COMMIT");
src.run("BEGIN EXCLUSIVE");
src.run("INSERT INTO kv VALUES ('tmp', 0)");
fail("busy-read-exclusive", () => other.query("SELECT count(*) n FROM kv").get());
src.run("ROLLBACK");
fail("after-rollback", () => other.query("SELECT count(*) n FROM kv").get());
other.close();
src.close();
''')
    con = sqlite3.connect(str(workdir / "data.db"))
    try:
        rows = con.execute("SELECT k, v, typeof(v) FROM kv ORDER BY k").fetchall()
    finally:
        con.close()
    assert rows == [("a", "updated", "text"), ("b", "two", "text"), ("c", b"\x01\x02", "blob"), ("d", 2.5, "real"),
                    ("e", None, "null"), ("f", 5, "integer")]
    assert not (workdir / "missing.db").exists()
    assert not (workdir / "missing2.db").exists()


def test_rare_database_apis_and_closed_handles(run, workdir):
    """CATCHES: Database.setCustomSQLite not validating its path or not refusing once a database is open,
    fileControl value-type checking and its error for unsupported opcodes, loadExtension errors surfacing
    as SQLiteError, every API on a closed database throwing 'Database has closed', and deserialize() of
    an empty image yielding a usable empty database."""
    check_script(run, workdir, G, "rare_database_apis_and_closed_handles", PRELUDE + r'''
fail("custom-missing", () => Database.setCustomSQLite("./nope.so"));
fail("custom-directory", () => Database.setCustomSQLite("."));
const db = new Database("fc.db");
fail("custom-after-open", () => Database.setCustomSQLite("rare_database_apis_and_closed_handles.js"));
fail("fcntl-memory", () => new Database(":memory:").fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, 1));
fail("fcntl-persist-wal", () => db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, 1));
fail("fcntl-chunk-size", () => db.fileControl(constants.SQLITE_FCNTL_CHUNK_SIZE, 4096));
fail("fcntl-typed-array", () => db.fileControl(constants.SQLITE_FCNTL_LOCKSTATE, new Int32Array(1)));
fail("fcntl-null", () => db.fileControl(constants.SQLITE_FCNTL_SYNC_OMITTED, null));
fail("fcntl-string", () => db.fileControl(constants.SQLITE_FCNTL_LOCKSTATE, "str"));
fail("fcntl-unknown-opcode", () => db.fileControl(9999, 0));
fail("load-extension-missing", () => db.loadExtension("./nope-ext"));
db.run("CREATE TABLE t (x)");
db.close();
for (const [label, f] of [["run", () => db.run("SELECT 1")], ["exec", () => db.exec("SELECT 1")], ["serialize", () => db.serialize()],
                          ["fileControl", () => db.fileControl(1, 0)], ["loadExtension", () => db.loadExtension("x")],
                          ["query", () => db.query("SELECT 1")], ["transaction", () => db.transaction(() => 1)()]]) fail("closed-" + label, f);
fail("close-again", () => db.close());
fail("deserialize-empty", () => Database.deserialize(new Uint8Array(0)).query("SELECT count(*) n FROM sqlite_master").get());
const reopened = new Database("fc.db");
fail("reopened", () => reopened.query("SELECT name FROM sqlite_master").all());
''')
