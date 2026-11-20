"""Bun-compatible runtime APIs: Bun.hash families, Bun.password (bcrypt/argon2), bun:sqlite and the
smaller Bun.* helpers (file/write, spawnSync, semver, TOML/YAML, Glob, hashing, colors, ...)."""

from conftest import golden, write_files


def _ok(r):
    assert (r.returncode, r.stderr) == (0, b""), r.stderr


PROG_HASH = r"""
const out = (...a) => console.log(...a);
const pat = (n) => { const b = new Uint8Array(n); for (let i = 0; i < n; i++) b[i] = (i * 31 + 7) & 0xff; return b; };
const fams = ["wyhash", "cityHash32", "cityHash64", "xxHash32", "xxHash64", "xxHash3", "murmur32v3", "murmur32v2", "murmur64v2", "rapidhash", "crc32", "adler32"];
const lens = [0, 1, 2, 3, 4, 5, 7, 8, 9, 12, 13, 15, 16, 17, 23, 24, 25, 31, 32, 33, 47, 48, 49, 63, 64, 65, 96, 112, 127, 128, 129, 160, 200, 240, 241, 256, 300, 1024, 5000];
const hx = (v) => (typeof v === "bigint" ? v.toString(16) : (v >>> 0).toString(16));
for (const f of fams) {
  out(f, typeof Bun.hash[f](""), lens.map((n) => hx(Bun.hash[f](pat(n)))).join(" "));
  out(f + " seeded", [1, 0xdeadbeef, 2n ** 63n, 2n ** 64n - 1n].map((s) => hx(Bun.hash[f](pat(37), s))).join(" "));
}
out("zero/ff", fams.map((f) => hx(Bun.hash[f](new Uint8Array(64))) + "/" + hx(Bun.hash[f](new Uint8Array(64).fill(255)))).join(" "));
out("default", typeof Bun.hash("hello"), Bun.hash("hello"), Bun.hash("hello") === Bun.hash.wyhash("hello"), Bun.hash("hello", 1));
const h = Bun.hash;
out("glue", `${typeof h("hello")} ${h("hello")}`, `${h.wyhash("hello", 1)}`, `${typeof h.cityHash32("hello")} ${h.cityHash32("hello")}`, `${h.cityHash64("hello")}`);
out("glue2", `${h.xxHash32("hello")} ${h.xxHash64("hello")} ${h.xxHash3("hello")}`, `${h.murmur32v3("hello")} ${h.murmur32v2("hello")} ${h.murmur64v2("hello")}`, `${h.rapidhash("hello")} ${h.crc32("hello")} ${h.adler32("hello")}`);
out("seed coercion", `${h.wyhash("x", -1)} ${h.wyhash("x", 2 ** 51) === h.wyhash("x", 0)}`, `${h.wyhash("hello world test", 2n ** 64n - 1n)}`, h.wyhash("x", 1.9) === h.wyhash("x", 1), h.crc32("x", -1), h.xxHash32("x", 2 ** 32 + 5) === h.xxHash32("x", 5));
const bytes = new TextEncoder().encode("hello");
const sub = new Uint8Array(new TextEncoder().encode("XXhelloYY").buffer, 2, 5);
out("input coercion", h.wyhash(bytes) === h.wyhash("hello"), h.wyhash(sub) === h.wyhash("hello"), h.wyhash(null) === h.wyhash("null"), h.wyhash(bytes.buffer) === h.wyhash("hello"), h.wyhash(new DataView(bytes.buffer)) === h.wyhash("hello"), h.wyhash(12) === h.wyhash("12"), h.crc32(Buffer.from("hello")) === h.crc32("hello"));
out("utf8", h.wyhash("héllo wörld 你好 🌍"), h.crc32("héllo"), h.adler32("héllo"), h.xxHash3("héllo"), h.murmur64v2("😀"));
"""


def test_bun_hash_families(run):
    """CATCHES: Bun.hash variants (wyhash, cityHash32/64, xxHash32/64/3, murmur32v3/v2, murmur64v2,
    rapidhash, crc32, adler32) that diverge from Bun at any tail length/block boundary up to 5000 bytes,
    mishandle u64 seeds (BigInt wrap, int32 sign extension, ignored seeds) or input coercion."""
    r = run(["-e", PROG_HASH])
    _ok(r)
    assert r.stdout == golden(__file__, "hash")


PROG_PASSWORD_VERIFY = r"""
const out = (...a) => console.log(...a);
const P = Bun.password;
const known = {
  bcrypt4: "$2b$04$JdQy7E0gFXE5DhZd7ylnwOxh.yIPzJmVMwr1cPXF32P0Y.ApTweN2",
  argon2id: "$argon2id$v=19$m=64,t=1,p=1$357oDTn3JiZb4pILTVOuNuwaJ/+oWLMvRfQfpb1hZLs$ftCAa/kQbbk/2zdOqZYlzb2yCL+72rrhzaow6Z/Wp/w",
  argon2i: "$argon2i$v=19$m=32,t=2,p=1$qkKrA4AiG7+zYWIKOqbrqioIoGBQsrNeX3mEjedLl5k$EBEqM6o6pMhp3155gj5ELfxme+iiqUiNBKPJlqGAyYY",
  argon2d: "$argon2d$v=19$m=16,t=3,p=1$C9xIwn3CSVaLdyTFCeyLZEbwsawgIjvB2J7GZA2EBMg$ITGrOOL89WmABk5sK6JkgDZtMOtxVZXg6alVz+YYuS4",
  bcrypt5long: "$2b$05$zKcP0wcgN8ECjhcke4WeFehC6rHc3SnDlEODl6Z7jgPzF.KXKN8MO",
  openbsd: "$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW",
  refI: "$argon2i$v=19$m=65536,t=2,p=1$c29tZXNhbHQ$wWKIMhR9lyDFvRz9YTZweHKfbftvj+qf+YFY4NeBbtA",
  refId: "$argon2id$v=19$m=65536,t=2,p=1$c29tZXNhbHQ$CTFhFdXPJO1aFaMaO6Mm5c8y7cJHAph8ArZWb2GRPPc",
  refV16: "$argon2i$v=16$m=256,t=2,p=1$c29tZXNhbHQ$/U3YPXYsSb3q9XxHvc0MLxur+GP960kN9j7emXX8zwY",
};
out("verify bcrypt", P.verifySync("correct horse", known.bcrypt4), P.verifySync("correct horsE", known.bcrypt4), P.verifySync("correct horse", known.bcrypt4.replace("$2b$", "$2a$")), P.verifySync("correct horse", known.bcrypt4.replace("$2b$", "$2y$")), P.verifySync("correct horse", known.bcrypt4.replace("$2b$", "$2x$")));
out("verify argon2", P.verifySync("correct horse", known.argon2id), P.verifySync("wrong", known.argon2id), P.verifySync("pässwörd", known.argon2i), P.verifySync(new Uint8Array([0, 1, 2, 255]), known.argon2d), P.verifySync(Buffer.from([0, 1, 2, 254]), known.argon2d));
out("verify long bcrypt", P.verifySync("x".repeat(80), known.bcrypt5long), P.verifySync("x".repeat(72), known.bcrypt5long), P.verifySync("x".repeat(71), known.bcrypt5long));
out("openbsd vector", P.verifySync("U*U", known.openbsd), P.verifySync("U*V", known.openbsd));
out("argon2 reference vectors", P.verifySync("password", known.refI), P.verifySync("password", known.refId), P.verifySync("password", known.refV16), P.verifySync("passwore", known.refV16));
for (const [label, h] of [["garbage", "nothing"], ["empty", ""], ["badargon", "$argon2id$v=19$m=0,t=1,p=1$c2FsdA$dGFn"], ["argonver", "$argon2id$v=18$m=8,t=1,p=1$c2FsdHNhbHQ$dGFndGFn"], ["argonkey", "$argon2id$v=19$m=8,t=1,x=1$c2FsdHNhbHQ$dGFndGFn"], ["argonvariant", "$argon2q$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$dGFndGFn"], ["argontag", "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$dGE"], ["argonextra", "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$dGFndGFn$x"], ["bcryptshort", "$2b$04$short"], ["bcryptcost", "$2b$99$JdQy7E0gFXE5DhZd7ylnwOxh.yIPzJmVMwr1cPXF32P0Y.ApTweN2"], ["bcrypt3", "$2b$03$JdQy7E0gFXE5DhZd7ylnwOxh.yIPzJmVMwr1cPXF32P0Y.ApTweN2"], ["md5crypt", "$1$abc$def"]]) {
  try { out("bad", label, P.verifySync("pw", h)); } catch (e) { out("bad", label, e.name, e.code, e.message); }
}
(async () => {
  out("async verify", await P.verify("correct horse", known.argon2id), await P.verify("correct horse", known.bcrypt4), await P.verify(Buffer.from("U*U"), known.openbsd));
  try { await P.verify("pw", "garbage"); } catch (e) { out("async bad", e.name, e.code, e.message); }
  try { await P.verify("pw", "$argon2id$v=19$broken"); } catch (e) { out("async bad2", e.name, e.message); }
})();
"""


def test_bun_password_verify_known_hashes(run):
    """CATCHES: Bun.password.verify(Sync) that rejects valid bcrypt ($2a/$2b/$2x/$2y, 72-byte password
    truncation, OpenBSD vector) or argon2i/d/id PHC strings (v=19 and v=16 reference vectors), accepts
    wrong passwords, or reports malformed hashes with different UnsupportedAlgorithm/InvalidEncoding errors."""
    r = run(["-e", PROG_PASSWORD_VERIFY], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "password_verify")


PROG_PASSWORD_HASH = r"""
const out = (...a) => console.log(...a);
const P = Bun.password;
const h1 = P.hashSync("round trip", { algorithm: "bcrypt", cost: 4 });
out("bcrypt hash", h1.length, h1.slice(0, 7), /^\$2b\$04\$[./A-Za-z0-9]{53}$/.test(h1), P.verifySync("round trip", h1), P.verifySync("round trap", h1));
const h2 = P.hashSync("round trip", { algorithm: "argon2id", memoryCost: 32, timeCost: 1 });
out("argon2id hash", /^\$argon2id\$v=19\$m=32,t=1,p=1\$[A-Za-z0-9+/]{43}\$[A-Za-z0-9+/]{43}$/.test(h2), P.verifySync("round trip", h2), P.verifySync("round", h2));
const h3 = P.hashSync("x", "argon2i");
out("default argon2i params", h3.startsWith("$argon2i$v=19$m=65536,t=2,p=1$"), P.verifySync("x", h3));
const h4 = P.hashSync(new Uint8Array([1, 2, 3]), { algorithm: "argon2d", memoryCost: 8, timeCost: 2 });
out("argon2d bytes", h4.slice(0, 26), P.verifySync(new Uint8Array([1, 2, 3]), h4), P.verifySync("\u0001\u0002\u0003", h4));
const h5 = P.hashSync("BCRYPT upper", { algorithm: "BCRYPT", cost: 4 });
out("algorithm case", h5.slice(0, 7), P.verifySync("BCRYPT upper", h5));
out("salted", P.hashSync("same", { algorithm: "bcrypt", cost: 4 }) !== P.hashSync("same", { algorithm: "bcrypt", cost: 4 }));
for (const [label, o] of [["alg", { algorithm: "scrypt" }], ["cost", { algorithm: "bcrypt", cost: 3 }], ["cost2", { algorithm: "bcrypt", cost: 32 }], ["costf", { algorithm: "bcrypt", cost: 4.5 }], ["mem", { memoryCost: 0 }], ["time", { timeCost: 1.5 }], ["type", 42], ["null", null]]) {
  try { P.hashSync("pw", o); out("opt", label, "accepted"); } catch (e) { out("opt", label, e.name, e.message); }
}
(async () => {
  const ha = await P.hash("async pw", { algorithm: "bcrypt", cost: 4 });
  out("async hash", ha.slice(0, 7), await P.verify("async pw", ha), await P.verify("nope", ha));
  out("async argon", (await P.hash("a", { memoryCost: 16, timeCost: 1 })).slice(0, 26));
  try { await P.hash("pw", { algorithm: "nope" }); } catch (e) { out("async bad alg", e.name, e.message); }
  try { await P.hash("pw", { algorithm: "bcrypt", cost: 40 }); } catch (e) { out("async bad cost", e.name, e.message); }
})();
"""


def test_bun_password_hash_round_trips(run):
    """CATCHES: Bun.password.hash(Sync) emitting the wrong PHC/bcrypt string shape (prefix, params,
    base64 lengths, default argon2 parameters), unsalted (repeatable) hashes, hashes that fail to verify,
    or different validation errors for algorithm/cost/memoryCost/timeCost/options."""
    r = run(["-e", PROG_PASSWORD_HASH], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "password_hash")


PROG_SQLITE_QUERIES = r"""
const { Database, constants } = require("bun:sqlite");
const out = (...a) => console.log(...a);
const show = (v) => JSON.stringify(v, (k, x) => (typeof x === "bigint" ? x + "n" : x instanceof Uint8Array ? "u8:" + Array.from(x).join(",") : x));
const db = new Database(":memory:");
out("db", db.filename, typeof Database.open, Database.MAX_QUERY_CACHE_SIZE, constants.SQLITE_OPEN_READWRITE, constants.SQLITE_OPEN_CREATE);
db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL, score REAL, data BLOB, big INTEGER)");
const ins = db.prepare("INSERT INTO t (name, score, data, big) VALUES (?, ?, ?, ?)");
out("run", show(ins.run("alice", 9.5, new Uint8Array([1, 2, 3]), 2 ** 40)), show(ins.run("bob", null, null, -7)), show(ins.run("carol", 7, Buffer.from("hi"), 9007199254740991)));
out("paramsCount", ins.paramsCount, ins.columnNames.length);
const q = db.query("SELECT id, name, score, data, big FROM t ORDER BY id");
out("all", show(q.all()));
out("get", show(db.query("SELECT * FROM t WHERE name = ?").get("bob")), db.query("SELECT * FROM t WHERE name = ?").get("nobody"));
out("values", show(db.query("SELECT name, score FROM t ORDER BY id").values()));
out("columnNames", q.columnNames.join(","), db.query("SELECT 1 AS one, 'x' AS two").columnNames.join(","));
out("named", show(db.query("SELECT $a + $b AS s, :c AS c, @d AS d").get({ $a: 1, $b: 2, ":c": "colon", "@d": null })));
out("named missing", show(db.query("SELECT $a AS a, $b AS b").get({ $a: 5 })), show(db.query("SELECT $a AS a").get({ a: 5 })));
out("positional array", show(db.query("SELECT ?1 || ?2 AS cat").get(["x", "y"])), show(db.query("SELECT ? AS a, ? AS b").get(1, "two")));
try { db.query("SELECT ? AS a, ? AS b").get(1); } catch (e) { out("count mismatch", e.name, e.message); }
out("types", show(db.query("SELECT typeof(?) a, typeof(?) b, typeof(?) c, typeof(?) d, typeof(?) e, typeof(?) f").get(1, 1.5, "s", null, new Uint8Array(1), true)));
out("bool/bigint", show(db.query("SELECT ? AS t, ? AS f, ? AS b, ? AS neg").get(true, false, 123n, -(2n ** 62n))));
out("real results", show(db.query("SELECT 1.0 AS a, 0.1 + 0.2 AS b, 1e308 * 10 AS inf, 7 / 2 AS idiv, 7 / 2.0 AS fdiv").get()));
out("iterate", [...db.query("SELECT name FROM t ORDER BY id DESC").iterate()].map((r) => r.name).join(","), [...db.query("SELECT id FROM t")].length);
const it = db.query("SELECT id FROM t ORDER BY id").iterate();
out("iterate early return", it.next().value.id, JSON.stringify(it.return(9)), JSON.stringify(it.next()));
class Row { get upper() { return this.name.toUpperCase(); } }
out("as", db.query("SELECT name FROM t ORDER BY id LIMIT 1").as(Row).get().upper, db.query("SELECT name FROM t ORDER BY id LIMIT 1").as(Row).get() instanceof Row);
out("safeIntegers", show(db.query("SELECT big FROM t WHERE name='carol'").safeIntegers().get()), show(db.query("SELECT big FROM t WHERE name='carol'").safeIntegers(false).get()));
const sdb = new Database(":memory:", { safeIntegers: true });
out("db safeIntegers", show(sdb.query("SELECT 5 AS n").get()), show(sdb.run("CREATE TABLE z(a)")), show(sdb.query("INSERT INTO z VALUES (1)").run()));
sdb.close();
out("query cache", db.query("SELECT 1") === db.query("SELECT 1"), db.prepare("SELECT 1") === db.prepare("SELECT 1"));
const ts = db.prepare("SELECT ? AS v, ? AS w"); ts.get(42, "s'q");
out("toString", ts.toString(), String(db.query("SELECT ?1 AS v")));
out("reuse bindings", show(ts.get()), show(ts.all()));
out("exec multi", show(db.run("CREATE TABLE u(x); INSERT INTO u VALUES (1); INSERT INTO u VALUES (2);")), db.query("SELECT count(*) AS c FROM u").get().c);
out("run with params", show(db.run("INSERT INTO u VALUES (?)", [3])), show(db.exec("DELETE FROM u WHERE x > ?", 1)));
out("run select changes", show(db.query("SELECT * FROM u").run()), show(db.query("INSERT INTO u VALUES (9) RETURNING x").all()));
const strict = new Database(":memory:", { strict: true });
out("strict", show(strict.query("SELECT $a AS a, :b AS b").get({ a: 1, b: 2 })));
try { strict.query("SELECT $a AS a").get({}); } catch (e) { out("strict missing", e.message); }
strict.close();
"""


def test_bun_sqlite_queries(run):
    """CATCHES: bun:sqlite query/prepare/run/get/all/values/iterate semantics: changes/lastInsertRowid,
    named ($/:/@) vs positional bindings (non-strict bare keys do not bind), value type mapping (blobs,
    booleans, bigint, reals), .as() classes, safeIntegers, query caching, expanded toString, strict mode."""
    r = run(["-e", PROG_SQLITE_QUERIES])
    _ok(r)
    assert r.stdout == golden(__file__, "sqlite_queries")


PROG_SQLITE_TX_ERRORS = r"""
const { Database, Statement, SQLiteError } = require("bun:sqlite");
const out = (...a) => console.log(...a);
const db = new Database();
db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL)");
const ins = db.prepare("INSERT INTO t (name) VALUES (?)");
ins.run("a"); ins.run("b"); ins.run("c");
const tx = db.transaction((names) => { for (const n of names) ins.run(n); return names.length; });
out("transaction", tx(["d1", "d2"]), db.query("SELECT count(*) AS c FROM t").get().c);
const failing = db.transaction(() => { ins.run("rolled"); throw new Error("abort tx"); });
try { failing(); } catch (e) { out("tx rollback", e.message, db.query("SELECT count(*) AS c FROM t WHERE name='rolled'").get().c); }
const outer = db.transaction(() => { ins.run("outer"); try { db.transaction(() => { ins.run("inner"); throw new Error("inner fail"); })(); } catch {} return "outer ok"; });
out("nested", outer(), JSON.stringify(db.query("SELECT name FROM t WHERE name IN ('outer','inner')").all()));
out("tx variants", typeof tx.deferred, typeof tx.immediate, typeof tx.exclusive, tx.immediate(["e1"]), tx.exclusive(["e2"]), tx.deferred([]));
try { db.transaction(42); } catch (e) { out("tx arg", e.name, e.message); }
for (const [label, sql] of [["syntax", "SELEC 1"], ["no table", "SELECT * FROM nope"], ["constraint", "INSERT INTO t (id, name) VALUES (1, 'dup')"], ["notnull", "INSERT INTO t (name) VALUES (NULL)"], ["incomplete", "SELECT ("]]) {
  try { db.run(sql); out("err", label, "none"); } catch (e) { out("err", label, e.name, e.code, e.errno, e instanceof SQLiteError, e instanceof Error, e.message); }
}
try { db.prepare("SELECT * FROM nope"); } catch (e) { out("prepare err", e.name, e.code, e.message); }
try { ins.run(null); } catch (e) { out("bind notnull", e.code, e.message); }
try { new SQLiteError("x"); } catch (e) { out("ctor", e.message); }
try { new Statement(); } catch (e) { out("stmt ctor", e.name, e.message); }
const bytes = db.serialize();
out("serialize", Buffer.isBuffer(bytes), bytes.subarray(0, 15).toString(), bytes.length % 4096);
const copy = Database.deserialize(bytes);
out("deserialize", copy.query("SELECT count(*) AS c FROM t").get().c, copy.filename);
copy.run("INSERT INTO t (name) VALUES ('only in copy')");
out("independent", copy.query("SELECT count(*) AS c FROM t").get().c, db.query("SELECT count(*) AS c FROM t").get().c);
copy.close();
const fromBytes = new Database(bytes);
out("ctor from bytes", fromBytes.query("SELECT max(id) AS m FROM t").get().m);
fromBytes.close();
const st = db.prepare("SELECT 1 AS one");
st.finalize(); st.finalize();
try { st.get(); } catch (e) { out("finalized", e.message); }
out("finalized toString", st.toString());
const fdb = new Database("file.db");
fdb.run("CREATE TABLE f(v TEXT)"); fdb.run("INSERT INTO f VALUES ('persisted')");
fdb.close(); fdb.close();
const ro = new Database("file.db", { readonly: true });
out("file db", ro.query("SELECT v FROM f").get().v, ro.filename);
try { ro.run("INSERT INTO f VALUES ('x')"); } catch (e) { out("readonly", e.code, e.message); }
ro.close();
const rw = Database.open("file.db", { readwrite: true });
rw.run("INSERT INTO f VALUES ('second')"); out("readwrite", rw.query("SELECT count(*) AS c FROM f").get().c); rw.close();
try { new Database("missing-dir/x.db", { readonly: true }); } catch (e) { out("open missing", e.name, e.code, e.message); }
try { new Database("nofile.db", { create: false }); } catch (e) { out("open nocreate", e.name, e.code, e.message); }
try { new Database("nofile.db", {}); } catch (e) { out("open empty opts", e.code); }
db.close();
try { db.query("SELECT 1"); } catch (e) { out("closed", e.name, e.message); }
try { db.run("SELECT 1"); } catch (e) { out("closed run", e.name, e.message); }
try { db.serialize(); } catch (e) { out("closed serialize", e.message); }
try { db.loadExtension("x"); } catch (e) { out("loadExtension", e.message); }
out("default import", require("bun:sqlite").default === Database, require("fs").existsSync("nofile.db"));
"""


def test_bun_sqlite_transactions_errors_files(run, workdir):
    """CATCHES: bun:sqlite transactions (commit, rollback on throw, nested savepoints, deferred/
    immediate/exclusive), SQLiteError code/errno/message shapes, serialize/deserialize independence,
    finalize, file databases with readonly/readwrite/create flags and closed-database errors."""
    r = run(["-e", PROG_SQLITE_TX_ERRORS])
    _ok(r)
    assert r.stdout == golden(__file__, "sqlite_tx_errors")
    assert (workdir / "file.db").read_bytes()[:16] == b"SQLite format 3\x00"


PROG_BUN_MISC = r"""
const out = (...a) => console.log(...a);
(async () => {
  out("version", typeof Bun.version, typeof Bun.revision, Bun.main === process.cwd().slice(1) + "/main.js", Bun.isMainThread, typeof Bun.env.PATH, Bun.env === process.env, JSON.stringify(Bun.argv.slice(2)));
  await Bun.write("bw.txt", "bun write");
  const f = Bun.file("bw.txt");
  out("file", f.size, f.type, await f.text(), await f.exists(), await Bun.file("nope.txt").exists(), f.name, Bun.file("x.json").type, Bun.file("x.html").type);
  await Bun.write("j.json", JSON.stringify({ a: [1] }));
  out("file json", JSON.stringify(await Bun.file("j.json").json()));
  out("file bytes", Array.from(await Bun.file("bw.txt").bytes()).slice(0, 3).join(), (await Bun.file("bw.txt").arrayBuffer()).byteLength, Bun.file("bw.txt").slice(4, 9).size, await Bun.file("bw.txt").slice(4).text());
  out("write returns", await Bun.write("bw2.txt", new Uint8Array([65, 66])), await Bun.write("bw3.txt", Bun.file("bw.txt")), await Bun.file("bw3.txt").text(), await Bun.write(Bun.file("bw4.txt"), new Blob(["blob!"])));
  out("escapeHTML", Bun.escapeHTML(`<a href="x">'&'</a>`), Bun.escapeHTML(42));
  out("stringWidth", Bun.stringWidth("hello"), Bun.stringWidth("你好"), Bun.stringWidth("\u001b[31mred\u001b[0m"), Bun.stringWidth("é"), Bun.stringWidth("😀"), Bun.stringWidth(""));
  out("stripANSI", Bun.stripANSI("\u001b[1mbold\u001b[22m"));
  out("deepEquals", Bun.deepEquals({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] }), Bun.deepEquals([1], ["1"]), Bun.deepEquals({ a: undefined }, {}), Bun.deepEquals({ a: undefined }, {}, true), Bun.deepMatch({ a: 1 }, { a: 1, b: 2 }), Bun.deepMatch({ a: 2 }, { a: 1 }));
  out("inspect", Bun.inspect({ a: 1, b: [1, 2] }), Bun.inspect("s"), typeof Bun.inspect.custom);
  out("peek", Bun.peek(42), Bun.peek.status(new Promise(() => {})), Bun.peek.status(Promise.reject(new Error("r")).catch(() => {}) && 1));
  out("sleep", Bun.sleepSync(1), typeof (await Bun.sleep(1)), typeof Bun.nanoseconds());
  out("which", Bun.which("sh") !== null, Bun.which("definitely-not-here-zz"));
  out("fileURL", Bun.fileURLToPath("file:///a/b"), Bun.pathToFileURL("/a b").href);
  out("concat", new Uint8Array(Bun.concatArrayBuffers([new Uint8Array([1]), new Uint8Array([2, 3]).buffer])).join());
  out("indexOfLine", Bun.indexOfLine(Buffer.from("ab\ncd\nef"), 1), Bun.indexOfLine(Buffer.from("ab\ncd\nef"), 4), Bun.indexOfLine(Buffer.from("abc"), 0));
  const sp = Bun.spawnSync(["sh", "-c", "echo out; echo err >&2; exit 3"]);
  out("spawnSync", sp.exitCode, sp.success, JSON.stringify(sp.stdout.toString()), JSON.stringify(sp.stderr.toString()), typeof sp.pid);
  const sp2 = Bun.spawnSync({ cmd: ["cat"], stdin: Buffer.from("fed in") });
  out("spawnSync stdin", sp2.exitCode, sp2.stdout.toString());
  const proc = Bun.spawn(["sh", "-c", "exit 4"]);
  out("spawn exit", await proc.exited, proc.exitCode, typeof proc.pid);
  out("shell", typeof Bun.$, (await Bun.$`sh -c "exit 3"`.nothrow()).exitCode);
  out("semver", Bun.semver.satisfies("1.2.3", "^1.0.0"), Bun.semver.satisfies("2.0.0", "~1.2"), Bun.semver.satisfies("1.2.9", ">=1.2.3 <1.3.0"), Bun.semver.order("1.2.3", "1.10.0"), Bun.semver.order("2.0.0", "2.0.0-beta"), Bun.semver.order("1.0.0", "1.0.0"));
  out("TOML", JSON.stringify(Bun.TOML.parse('title = "x"\n[owner]\nname = "y"\nnums = [1, 2]\nflag = true\n')));
  out("YAML", JSON.stringify(Bun.YAML.parse("a: 1\nb:\n  - x\n  - y\nc: {d: true}\ns: 'quoted'\n")));
  const g = new Bun.Glob("**/*.txt");
  out("Glob", g.match("a/b/c.txt"), g.match("c.js"), new Bun.Glob("*.{js,ts}").match("x.ts"), new Bun.Glob("?.md").match("a.md"), [...g.scanSync(".")].sort().join(","));
  const hasher = new Bun.CryptoHasher("sha256"); hasher.update("ab"); hasher.update("c");
  out("CryptoHasher", hasher.digest("hex"), Bun.CryptoHasher.hash("md5", "abc", "hex"), new Bun.SHA1().update("abc").digest("hex"), Bun.MD5.hash("abc", "hex"), Bun.sha("abc", "hex"), Bun.SHA512.hash("abc", "hex").slice(0, 16));
  try { new Bun.SHA224().update("abc").digest("hex"); } catch (e) { out("SHA224", e.message); }
  out("compress", new TextDecoder().decode(Bun.gunzipSync(Bun.gzipSync("bun gzip"))), new TextDecoder().decode(Bun.inflateSync(Bun.deflateSync("bun deflate"))), new TextDecoder().decode(Bun.zstdDecompressSync(Bun.zstdCompressSync("zstd"))), new TextDecoder().decode(await Bun.zstdDecompress(await Bun.zstdCompress("async zstd"))));
  out("uuid", Bun.randomUUIDv5("hello", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"), Bun.randomUUIDv5("hello", "url"), /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(Bun.randomUUIDv7()));
  out("color", Bun.color("red", "hex"), Bun.color("#00ff00", "number"), JSON.stringify(Bun.color("blue", "[rgb]")), JSON.stringify(Bun.color("rgb(1, 2, 3)", "{rgba}")), Bun.color("rebeccapurple", "HEX"), JSON.stringify(Bun.color("#f00", "ansi-16m")), Bun.color("not a color", "hex"), Bun.color([10, 20, 30], "css"));
  try { Bun.color("red", "rgb"); } catch (e) { out("color err", e.message); }
  const tr = new Bun.Transpiler({ loader: "ts" });
  out("Transpiler", JSON.stringify(tr.transformSync("const x: number = 1; export default x;")), JSON.stringify(tr.scan("import a from 'a'; export const b = 1;")), JSON.stringify(tr.scanImports("import 'side'; const m = require('cjs');")));
  const c = new Bun.Cookie("name", "value", { path: "/", httpOnly: true });
  const cm = new Bun.CookieMap("a=1; b=2");
  cm.set("c", "3");
  out("Cookie", c.toString(), cm.get("b"), cm.has("a"), cm.size, JSON.stringify(cm.toSetCookieHeaders()), typeof Bun.Cookie.parse);
  out("readableStream", await Bun.readableStreamToText(new Response("stream text").body), JSON.stringify(await Bun.readableStreamToJSON(new Response('{"j":1}').body)), (await Bun.readableStreamToArrayBuffer(new Response("abc").body)).byteLength, (await Bun.readableStreamToBytes(new Response("ab").body)).length);
  out("ArrayBufferSink", (() => { const s = new Bun.ArrayBufferSink(); s.write("ab"); s.write(new Uint8Array([99])); return new TextDecoder().decode(s.end()); })());
})().catch((e) => out("ERR", e.name, e.message));
"""


def test_bun_misc_helpers(run, workdir):
    """CATCHES: Bun.* helpers diverging from the reference: Bun.file/Bun.write (size/type/text/json/
    bytes/slice), escapeHTML, stringWidth, deepEquals/deepMatch, peek, which, spawnSync/spawn exit codes,
    $ nothrow, semver, TOML/YAML parsing, Glob (no brace expansion), CryptoHasher/SHA*/MD5, compression,
    UUIDv5/v7, color formats, Transpiler, Cookie/CookieMap, stream readers and ArrayBufferSink."""
    write_files(workdir, {"main.js": PROG_BUN_MISC})
    r = run(["main.js", "arg1"], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "misc")
    assert (workdir / "bw4.txt").read_bytes() == b"blob!"
    assert (workdir / "bw2.txt").read_bytes() == b"AB"


PROG_FFI = r"""
const { dlopen, FFIType, ptr, CString, read, toArrayBuffer, toBuffer, JSCallback, CFunction, suffix, viewSource } = require("bun:ffi");
const out = (...a) => console.log(...a);
out("suffix", suffix, FFIType.i32, FFIType.cstring, FFIType[5], FFIType.ptr, FFIType.void, FFIType.function);
const libc = dlopen("libc.so.6", {
  strlen: { args: ["ptr"], returns: "usize" },
  abs: { args: ["i32"], returns: "i32" },
  labs: { args: ["i64"], returns: "i64" },
  toupper: { args: [FFIType.int], returns: FFIType.int },
  atoi: { args: ["cstring"], returns: "i32" },
  strtol: { args: ["ptr", "ptr", "i32"], returns: "i64" },
  getenv: { args: ["cstring"], returns: "cstring" },
  memcpy: { args: ["ptr", "ptr", "usize"], returns: "ptr" },
  memset: { args: ["ptr", "i32", "usize"], returns: "ptr" },
  qsort: { args: ["ptr", "usize", "usize", "function"], returns: "void" },
  strchr: { args: ["ptr", "i32"], returns: "ptr" },
  myAbs: { name: "abs", args: ["i32"], returns: "i32" },
});
const s = Buffer.from("hello ffi\0");
out("strlen", libc.symbols.strlen(ptr(s)), typeof libc.symbols.strlen(ptr(s)));
out("abs", libc.symbols.abs(-42), libc.symbols.labs(-5000000000n), libc.symbols.toupper(97), libc.symbols.myAbs(-7));
out("atoi", libc.symbols.atoi(Buffer.from("1234xyz\0")), libc.symbols.strtol(ptr(Buffer.from("ff\0")), null, 16));
const tz = libc.symbols.getenv(Buffer.from("TZ\0"));
out("getenv", tz instanceof CString, String(tz), tz.length, JSON.stringify(String(libc.symbols.getenv(Buffer.from("NOPE_NOT_SET\0")))));
const dst = new Uint8Array(8);
libc.symbols.memcpy(ptr(dst), ptr(Buffer.from("copyme!!")), 8);
out("memcpy", Buffer.from(dst).toString());
libc.symbols.memset(ptr(dst, 2), 0x41, 3);
out("memset offset", Buffer.from(dst).toString());
const arr = new Int32Array([5, -3, 9, 0, 2]);
const cmp = new JSCallback((a, b) => read.i32(a) - read.i32(b), { args: ["ptr", "ptr"], returns: "i32" });
libc.symbols.qsort(ptr(arr), arr.length, 4, cmp.ptr);
out("qsort", Array.from(arr).join(","));
cmp.close();
out("closed cb", cmp.ptr);
const buf = new Uint8Array([1, 2, 3, 4, 0xff, 0xfe, 0, 0x80]);
const p = ptr(buf);
out("read", read.u8(p), read.u8(p, 4), read.i8(p, 4), read.u16(p), read.i16(p, 4), read.u32(p), read.i32(p, 4), read.u64(p), read.i64(p));
const f = new Float64Array([1.5, -2.25]); out("read float", read.f64(ptr(f)), read.f64(ptr(f), 8), read.f32(ptr(new Float32Array([0.5]))));
out("toArrayBuffer", new Uint8Array(toArrayBuffer(p, 1, 3)).join(), toBuffer(p, 0, 4).toString("hex"));
out("CString", new CString(ptr(Buffer.from("abc\0def"))).toString(), new CString(ptr(Buffer.from("abcdef")), 1, 3).toString(), new CString(0).toString() === "");
const hit = libc.symbols.strchr(ptr(s), "f".charCodeAt(0));
out("strchr", hit - ptr(s), new CString(hit).toString());
const libm = dlopen("libm.so.6", { sqrt: { args: ["f64"], returns: "f64" }, floorf: { args: ["f32"], returns: "f32" }, pow: { args: ["f64", "f64"], returns: "f64" } });
out("libm", libm.symbols.sqrt(2), libm.symbols.pow(2, 10), libm.symbols.floorf(2.7));
try { dlopen("libdefinitely-missing.so", {}); } catch (e) { out("dlopen missing", e.name, e.message.split(":")[0]); }
try { dlopen("libc.so.6", { no_such_symbol_zz: { args: [], returns: "void" } }); } catch (e) { out("dlsym missing", e.name, e.message); }
try { dlopen("libc.so.6", { abs: { args: ["weird"], returns: "i32" } }); } catch (e) { out("bad type", e.name, e.message); }
out("viewSource", viewSource(libc.symbols.abs).replace(/0x[0-9a-f]+/, "0xADDR"), viewSource(libc.symbols.strlen).replace(/0x[0-9a-f]+/, "0xADDR"));
libc.close(); libm.close();
"""


def test_bun_ffi_libc(run):
    """CATCHES: bun:ffi marshalling bugs calling real libc/libm symbols: integer/i64/usize/float/double
    arguments and returns, cstring arguments and CString returns, ptr() offsets, read.* typed reads,
    toArrayBuffer/toBuffer views, a JSCallback qsort comparator, and dlopen/dlsym/type error messages."""
    r = run(["-e", PROG_FFI])
    _ok(r)
    assert r.stdout == golden(__file__, "ffi")


PROG_SQLITE_EXTRAS = r"""const { Database, constants } = require("bun:sqlite");
const out = (...a) => console.log(...a);
const err = (label, f) => { try { const v = f(); out(label, "ok", JSON.stringify(v)); } catch (e) { out(label, e.name, e.code, e.errno, e.message); } };
err("setCustomSQLite missing", () => Database.setCustomSQLite("/definitely/not/libsqlite.so"));
const db = new Database(":memory:");
err("setCustomSQLite after open", () => Database.setCustomSQLite("/etc/hostname"));
db.run("PRAGMA foreign_keys = ON");
db.run("CREATE TABLE p (id INTEGER PRIMARY KEY)");
db.run("CREATE TABLE c (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES p(id), n INTEGER CHECK (n > 0), u TEXT UNIQUE)");
db.run("INSERT INTO p VALUES (1)");
err("fk", () => db.run("INSERT INTO c (pid, n) VALUES (99, 1)"));
err("check", () => db.run("INSERT INTO c (pid, n) VALUES (1, -1)"));
db.run("INSERT INTO c (pid, n, u) VALUES (1, 1, 'x')");
err("unique", () => db.run("INSERT INTO c (pid, n, u) VALUES (1, 2, 'x')"));
err("mismatch", () => db.run("INSERT INTO p VALUES ('not an int')"));
err("range", () => db.query("SELECT ?1 AS a").get({ "?5": 1 }));
db.run("CREATE TABLE s (v INTEGER) STRICT");
err("strict datatype", () => db.run("INSERT INTO s VALUES ('text')"));
db.run("CREATE TRIGGER tr BEFORE INSERT ON p BEGIN SELECT RAISE(ABORT, 'trigger says no') WHERE NEW.id = 42; END");
err("trigger", () => db.run("INSERT INTO p VALUES (42)"));
err("bind symbol", () => db.query("SELECT ? AS a").get(Symbol("s")));
err("bind object in array", () => db.query("SELECT ? AS a").get([{}]));
err("bind function", () => db.query("SELECT ? AS a").get(() => 1));
err("bind huge bigint", () => db.query("SELECT ? AS a").get(2n ** 70n));
err("bind dataview", () => db.query("SELECT length(?) AS a").get(new DataView(new ArrayBuffer(3))));
err("bind empty u8", () => db.query("SELECT typeof(?) AS t, length(?) AS l").get(new Uint8Array(0), new Uint8Array(0)));
err("bind float32", () => db.query("SELECT hex(?) AS h").get(new Float32Array([1])));
err("loadExtension", () => db.loadExtension("./definitely-missing-ext"));
err("fileControl bad value", () => db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, "str"));
err("fileControl number", () => db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, 1));
err("fileControl null", () => db.fileControl(constants.SQLITE_FCNTL_SYNC, null));
err("fileControl typed", () => db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, new Int32Array([0])));
err("deserialize string opens a file", () => { const d = Database.deserialize("not bytes"); const f = d.filename; d.close(); return [f, require("fs").existsSync("not bytes")]; });
err("deserialize empty", () => Database.deserialize(new Uint8Array(0)).query("SELECT 1 AS x").get());
err("deserialize garbage", () => Database.deserialize(new Uint8Array(512).fill(7)).query("SELECT * FROM sqlite_master").all());
err("libversion-ish", () => typeof db.query("SELECT sqlite_version() AS v").get().v);
err("busy", () => { const a = new Database("x.db"); a.run("CREATE TABLE IF NOT EXISTS t(v)"); a.run("BEGIN EXCLUSIVE"); a.run("INSERT INTO t VALUES (1)"); const b = new Database("x.db"); try { return b.run("INSERT INTO t VALUES (2)"); } finally { a.run("COMMIT"); a.close(); b.close(); } });
err("notadb", () => { require("fs").writeFileSync("junk.db", "this is not a database file at all".repeat(40)); const j = new Database("junk.db"); return j.query("SELECT * FROM sqlite_master").all(); });
err("closed stmt after db close", () => { const d = new Database(); const st = d.prepare("SELECT 1 AS x"); d.close(); return st.get(); });
err("finalize then all", () => { const st = db.prepare("SELECT 1"); st.finalize(); return st.all(); });
err("multiple statements prepare", () => db.prepare("SELECT 1 AS a; SELECT 2 AS b").all());
err("empty sql", () => db.prepare("").all());
err("comment only", () => db.run("-- nothing"));
err("columnNames of insert", () => db.prepare("INSERT INTO p VALUES (?)").columnNames);
err("paramsCount named", () => db.prepare("SELECT $a, :b, @c, ?").paramsCount);
err("native", () => typeof db.prepare("SELECT 1").native);
"""


def test_bun_sqlite_error_codes_and_extras(run, workdir):
    """CATCHES: SQLiteError code/errno mapping for foreign-key/check/unique/datatype/trigger/mismatch/
    busy/notadb failures, bind TypeErrors for unbindable values, blob binding of typed arrays,
    setCustomSQLite/loadExtension/fileControl/deserialize edge cases and prepare() of odd SQL."""
    r = run(["-e", PROG_SQLITE_EXTRAS])
    _ok(r)
    assert r.stdout == golden(__file__, "sqlite_extras")


PROG_JSX_TRANSPILER = r"""const out = (...a) => console.log(...a);
const tr = new Bun.Transpiler({ loader: "jsx" });
const cases = [
  `const a = <div />;`,
  `const b = <div className="x" id='y' hidden data-n={1 + 2}>hello</div>;`,
  `const c = <Foo.Bar {...props} key="k" on:click={h} aria-label="l">{items.map(i => <li key={i}>{i}</li>)}</Foo.Bar>;`,
  `const d = <>\n  <span>one</span>\n  two   words\n  {/* comment */}\n  {three}\n</>;`,
  `const e = <p>\n    multi\n    line   text  \n</p>;`,
  `const f = <a href="x">it's &amp; "quoted"</a>;`,
  `const g = x < y && y > z ? <b>yes</b> : <i>no</i>;`,
  `const h = "<div>" + '<span>' + \`<p>\${<em>t</em>}</p>\`; const re = /<div>/g; // <div> in comment`,
  `function F() { return <Comp render={() => <inner attr={{ a: 1 }} />} />; }`,
  `const i = <svg:rect xlink:href="#a" />;`,
  `const j = [1,2].map((n) => (<Item n={n} />));`,
  `/* <x> */ const k = a /b/ c; const l = <div>{/* only comment */}</div>;`,
  `const m = <div>{" "}{value}{' '}</div>;`,
  `const n = <div\n  a="1"\n  b={2}\n/>;`,
];
for (const src of cases) {
  try { out(JSON.stringify(tr.transformSync(src))); } catch (e) { out("ERR", e.name, e.message); }
}
for (const bad of [`const x = <div>unclosed`, `const y = <div></span>;`, `const z = <div attr=>x</div>;`, `const w = <div>{a</div>;`]) {
  try { out("bad", JSON.stringify(tr.transformSync(bad))); } catch (e) { out("bad ERR", e.name, e.message); }
}
const React = { createElement: (t, p, ...c) => ({ t: typeof t === "string" ? t : t.name || "frag", p, c }), Fragment: function Fragment() {} };
const code = tr.transformSync(`function App({ name }) { return <section title={"hi " + name}><h1>Hello {name}!</h1><>{[1, 2].map((n) => <b key={n}>{n}</b>)}</></section>; } result = App({ name: "Ann" });`);
let result; eval(code);
out("rendered", JSON.stringify(result));
const tsx = new Bun.Transpiler({ loader: "tsx" });
out("tsx", JSON.stringify(tsx.transformSync(`const t: number = 1; const el = <div n={t as number}>ts</div>;`)));
"""


def test_bun_transpiler_jsx(run):
    """CATCHES: JSX lowering differences in Bun.Transpiler (loader jsx/tsx): createElement call shape,
    attribute quoting/spread/boolean shorthand, text whitespace collapsing, fragments, JSX inside
    expressions vs `<` comparisons/strings/regexes/templates/comments, the reference's error messages
    for malformed JSX, and evaluating the lowered code against a stub React factory."""
    r = run(["-e", PROG_JSX_TRANSPILER])
    _ok(r)
    assert r.stdout == golden(__file__, "jsx_transpiler")


PROG_JSC = r"""
const jsc = require("bun:jsc");
const out = (...a) => console.log(...a);
const t = (l, f) => { try { out(l, JSON.stringify(f())); } catch (e) { out(l, "ERR", e.name, e.message); } };
out("keys", Object.keys(jsc).sort().join(","));
t("gc", () => [typeof Bun.gc(true), typeof Bun.gc(false), typeof jsc.edenGC(), typeof jsc.fullGC(), typeof jsc.gcAndSweep()]);
t("heap", () => [typeof jsc.heapSize(), jsc.heapSize() > 0, jsc.heapStats().objectCount > 0, Object.keys(jsc.heapStats()).sort(), Object.keys(jsc.memoryUsage()).sort()]);
let n = 0; Promise.resolve().then(() => n++); queueMicrotask(() => n++);
jsc.drainMicrotasks();
t("drainMicrotasks", () => n);
t("serialize", () => { const v = jsc.deserialize(jsc.serialize({ a: [1, "x"], m: new Map([[1, 2]]) })); return [v.a, v.m instanceof Map, v.m.get(1)]; });
t("describe", () => [jsc.describe(1), jsc.describe([1, { a: 2 }]), jsc.describeArray([3]), jsc.jscDescribe("s")]);
t("inert hooks", () => [jsc.noInline(function f() {}), jsc.noFTL(function f() {}), jsc.optimizeNextInvocation(function f() {}), jsc.numberOfDFGCompiles(function f() {}), jsc.reoptimizationRetryCount(function f() {}), jsc.releaseWeakRefs(), jsc.noOSRExitFuzzing ? typeof jsc.noOSRExitFuzzing : "none"]);
t("seeds", () => [typeof jsc.getRandomSeed(), jsc.setRandomSeed(42), jsc.isRope("a" + "b"), typeof jsc.callerSourceOrigin()]);
t("misc", () => [typeof jsc.estimateShallowMemoryUsageOf({}), typeof jsc.percentAvailableMemoryInUse(), Array.isArray(jsc.getProtectedObjects()), typeof jsc.totalCompileTime(() => {}), typeof jsc.generateHeapSnapshotForDebugging()]);
t("coverage missing file", () => jsc.codeCoverageForFile("x"));
"""


def test_bun_jsc_introspection(run):
    """CATCHES: bun:jsc surface differences: GC triggers and heap/memory statistics shapes,
    drainMicrotasks actually running queued microtasks synchronously, serialize/deserialize round
    trips, describe strings, inert JIT hooks, and the codeCoverageForFile error for a missing file."""
    r = run(["-e", PROG_JSC])
    _ok(r)
    assert r.stdout == golden(__file__, "jsc")


PROG_FFI_EDGES = r"""const { dlopen, FFIType, ptr, CString, read, toArrayBuffer, toBuffer, JSCallback, CFunction, linkSymbols, cc, viewSource } = require("bun:ffi");
const out = (...a) => console.log(...a);
const t = (l, f) => { try { const v = f(); out(l, typeof v === "bigint" ? v + "n" : JSON.stringify(v)); } catch (e) { out(l, "ERR", e.name, e.message); } };
const libc = dlopen("libc.so.6", {
  abs_i8: { name: "abs", args: ["i32"], returns: "i8" },
  abs_u8: { name: "abs", args: ["i32"], returns: "u8" },
  abs_i16: { name: "abs", args: ["i32"], returns: "i16" },
  abs_u16: { name: "abs", args: ["i32"], returns: "u16" },
  abs_u32: { name: "abs", args: ["i32"], returns: "u32" },
  abs_bool: { name: "abs", args: ["i32"], returns: "bool" },
  abs_char: { name: "abs", args: ["i32"], returns: "char" },
  labs_fast: { name: "labs", args: ["i64_fast"], returns: "i64_fast" },
  labs_ufast: { name: "labs", args: ["i64"], returns: "u64_fast" },
  labs_u64: { name: "labs", args: ["i64"], returns: "u64" },
  strlen: { args: ["ptr"], returns: "usize" },
  getenv_ptr: { name: "getenv", args: ["cstring"], returns: "ptr" },
  memcmp: { args: ["buffer", "buffer", "usize"], returns: "i32" },
});
const S = libc.symbols;
t("i8", () => S.abs_i8(-200)); t("u8", () => S.abs_u8(-200)); t("i16", () => S.abs_i16(-40000)); t("u16", () => S.abs_u16(-40000)); t("u32", () => S.abs_u32(-7)); t("bool0", () => S.abs_bool(0)); t("bool1", () => S.abs_bool(3)); t("char", () => S.abs_char(-65));
t("i64_fast", () => S.labs_fast(-123)); t("u64_fast", () => S.labs_ufast(-5n)); t("u64", () => S.labs_u64(-9n));
t("i64 non-integer", () => S.labs_u64(1.5));
t("null ptr return", () => S.getenv_ptr(Buffer.from("NOPE_NOT_SET_X\0")));
t("memcmp buffer", () => [S.memcmp(Buffer.from("abc"), Buffer.from("abd"), 3) < 0, S.memcmp(Buffer.from("abc"), Buffer.from("abc"), 3)]);
t("ptr string", () => S.strlen("not a buffer"));
t("ptr bigint", () => S.strlen(5n));
t("ptr object", () => S.strlen({}));
t("ptr null", () => typeof S.strlen === "function" && ptr);
t("ptr arraybuffer", () => ptr(new ArrayBuffer(4)));
t("toArrayBuffer null", () => toArrayBuffer(0, 0, 4).byteLength);
t("toBuffer null", () => toBuffer(null, 0, 4).length);
const words = new BigUint64Array([0x1122334455667788n]);
t("read.ptr", () => read.ptr(ptr(words)) === Number(0x1122334455667788n));
t("read.intptr", () => typeof read.intptr(ptr(words)));
t("cstring len", () => { const c = new CString(ptr(Buffer.from("hello world")), 6, 5); return [String(c), c.byteLength, new Uint8Array(c.arrayBuffer).length]; });
t("cstring no len arraybuffer", () => new CString(ptr(Buffer.from("x\0"))).arrayBuffer);
const cb = new JSCallback((a, b) => a * 10 + b, { args: ["i32", "i32"], returns: "i32" });
const viaC = CFunction({ ptr: cb.ptr, args: ["i32", "i32"], returns: "i32" });
t("CFunction over JSCallback", () => viaC(4, 2));
const linked = linkSymbols({ combine: { ptr: cb.ptr, args: ["i32", "i32"], returns: "i32" } });
t("linkSymbols", () => linked.symbols.combine(7, 3));
linked.close();
const cbVoid = new JSCallback(() => { out("void callback ran"); }, { returns: "void" });
t("void cb", () => CFunction({ ptr: cbVoid.ptr, returns: "void" })());
const cbI64 = new JSCallback((x) => x, { args: ["i64"], returns: "i64" });
t("i64 cb", () => CFunction({ ptr: cbI64.ptr, args: ["i64"], returns: "i64" })(-77n));
t("cb float arg", () => new JSCallback(() => 0, { args: ["f64"], returns: "i32" }));
t("cb float ret", () => new JSCallback(() => 0, { args: [], returns: "f32" }));
t("cb many args", () => new JSCallback(() => 0, { args: Array(9).fill("i32"), returns: "i32" }));
t("cb not fn", () => new JSCallback(42, {}));
t("call many args", () => dlopen("libc.so.6", { abs: { args: Array(9).fill("i32"), returns: "i32" } }).symbols.abs(1, 2, 3, 4, 5, 6, 7, 8, 9));
const libm = dlopen("libm.so.6", { powf: { args: ["f32", "f32"], returns: "f32" }, fmaf: { args: ["float", "float", "float"], returns: "float" }, ldexp: { args: ["f64", "i32"], returns: "f64" }, hypot: { args: [FFIType.double, FFIType.double], returns: FFIType.double } });
t("powf", () => libm.symbols.powf(1.5, 2)); t("fmaf", () => libm.symbols.fmaf(2, 3, 0.5)); t("ldexp mixed", () => libm.symbols.ldexp(1.5, 4)); t("hypot", () => libm.symbols.hypot(3, 4));
t("cc missing source", () => cc({ source: "./nope.c", symbols: {} }));
t("cc bad options", () => cc(null));
t("cc bad source", () => cc({ source: 42 }));
t("viewSource non fn", () => viewSource(1));
t("viewSource js fn", () => viewSource(function named() { return 1; }));
t("native", () => typeof require("bun:ffi").native.dlopen);
cb.close(); cbVoid.close(); cbI64.close(); cb.close();
libc.close(); libm.close();
"""


def test_bun_ffi_types_callbacks_and_errors(run):
    """CATCHES: bun:ffi return-type narrowing (i8/u8/i16/u16/u32/bool/char/i64_fast/u64_fast/u64),
    null pointer returns, buffer arguments, pointer-coercion TypeErrors, CString with explicit length,
    JSCallback thunks invoked through CFunction/linkSymbols (void and i64 signatures), unsupported
    callback/call signatures, float/double mixing in libm calls, and cc/viewSource argument errors."""
    r = run(["-e", PROG_FFI_EDGES])
    _ok(r)
    assert r.stdout == golden(__file__, "ffi_edges")


PROG_HARVEST = r"""const out = (...a) => console.log(...a);
const fs = require("fs");
const types = require("node:util/types");
const { createSecretKey } = require("node:crypto");
out("util/types", types.isProxy(new Proxy({}, {})), types.isProxy({}), types.isKeyObject(createSecretKey("secret")), types.isKeyObject(Buffer.from("secret")), types.isCryptoKey({}), types === require("util").types);
const jsc = require("bun:jsc");
const stats = jsc.heapStats(), memory = jsc.memoryUsage();
out("jsc stats", stats.objectCount > 0, stats.heapSize > 0, memory.current > 0);
out("jsc estimate", jsc.estimateShallowMemoryUsageOf("hello"), jsc.estimateShallowMemoryUsageOf(new Uint8Array(20)) >= 20);
const fn = () => 42;
out("jsc hooks", jsc.noFTL(fn) === fn, jsc.noInline(fn)());
const profile = jsc.profile((a, b) => a + b, 100, 2, 3);
out("jsc profile", typeof profile.functions, Array.isArray(profile.stackTraces));
let cycle = {}; cycle.self = cycle; cycle = null;
out("jsc gc", jsc.fullGC() >= 0, Array.isArray(jsc.getProtectedObjects()));
const v8Snapshot = Bun.generateHeapSnapshot("v8");
const parsed = JSON.parse(v8Snapshot);
const jscSnapshot = Bun.generateHeapSnapshot();
out("heap snapshots", parsed.snapshot.node_count, parsed.snapshot.lumen_object_count > 0, jscSnapshot.objectCount > 0, typeof jscSnapshot);
out("gc/shrink", Bun.gc() >= 0, Bun.shrink() >= 0);
const { Transpiler } = require("bun");
const ts = new Transpiler({ loader: "ts", define: { DEBUG: "false" } });
const js = ts.transformSync("const answer: number = 42; if (DEBUG) throw 1;");
out("transpiler ts", js.includes(": number"), js.includes("if (false)"), Function(`${js}; return answer`)());
const jsx = new Transpiler({ loader: "jsx" }).transformSync('const el = <div id="x">hello</div>;');
out("transpiler jsx", jsx.includes('React.createElement("div"'), jsx.includes('"hello"'));
const scan = ts.scan('import value from "pkg"; export { value as result }; const lazy = import("later");');
out("transpiler scan", scan.exports.join(","), scan.imports.map((item) => `${item.kind}:${item.path}`).join(","));
out("transpiler loaders", JSON.stringify(ts.transformSync('{"a":1}', "json")), JSON.stringify(ts.transformSync("raw text", { loader: "text" })));
try { new Transpiler({ loader: "css" }); } catch (e) { out("transpiler bad loader", e.name, e.message); }
fs.writeFileSync("mapped.bin", Uint8Array.of(1, 2, 3, 4));
const mapped = Bun.mmap("mapped.bin");
out("mmap", mapped instanceof Uint8Array, mapped.length, mapped[1]);
fs.writeFileSync("mapped.bin", Uint8Array.of(9, 8, 7, 6));
out("mmap sees write", mapped[1]);
mapped[2] = 42;
mapped.close();
out("mmap shared write", fs.readFileSync("mapped.bin")[2]);
const { Database, constants } = require("bun:sqlite");
const db = new Database("control.sqlite", { create: true });
out("wal", JSON.stringify(db.query("PRAGMA journal_mode=WAL").get()));
out("fileControl", db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, 0) === undefined);
try { db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, {}); } catch (error) { out("fileControl bad", error.name); }
db.close();
ts.transform("const value: string = 'ok'").then((code) => out("transform async", !code.includes(": string")));
"""


def test_bun_runtime_harvest_mmap_transpiler_jsc(run, workdir):
    """CATCHES: regressions in the runtime-level Bun cases: util/types isProxy/isKeyObject, bun:jsc
    live heap stats/estimates/profile, v8 and jsc heap snapshots, Transpiler define/scan/loaders,
    Bun.mmap's emulated mapping (indexed reads re-read the file, close() flushes the whole buffer
    back) and sqlite fileControl on a WAL file database."""
    r = run(["-e", PROG_HARVEST])
    _ok(r)
    assert r.stdout == golden(__file__, "harvest")
    # close() flushes the reference's emulated mapping, whose untouched bytes are still the original ones
    assert (workdir / "mapped.bin").read_bytes() == bytes([1, 8, 42, 4])
