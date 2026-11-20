"""bun:sqlite result codes and native entry points the main sqlite module leaves unexercised: the
rowid and STRICT-datatype constraint codes, Database.fileControl with a NULL argument and with an
opcode the VFS does not know, deserializing from a non-byte view, and finalizing a statement whose
database was already closed (its native statement is gone).

The remaining crypto.rs native ops (AES-CTR/GCM one-shots, the native SHA-384/512 variants and
the defensive argument checks) are never called by the node:crypto glue, which streams CTR/GCM
through aesEcb, hashes SHA-384/512 in JS and validates every argument first, so no test can reach
them through the public API.
"""

import pytest

from conftest import err, out


def skip_without_sqlite(r):
    """bun:sqlite dlopens the system libsqlite3 lazily; skip when this machine has none."""
    if "bun:sqlite unavailable" in err(r):
        pytest.skip("system libsqlite3 is not available")


def test_sqlite_rowid_datatype_codes_and_native_edge_calls(js, golden):
    """CATCHES: SQLiteError codes that are missing or wrong for a duplicate explicit rowid
    (SQLITE_CONSTRAINT_ROWID) and a STRICT-table type violation (SQLITE_CONSTRAINT_DATATYPE),
    fileControl that rejects a null/undefined argument or hides an unknown opcode's failure, and a
    deserialize that accepts a DataView or a finalize-after-close that throws."""
    code = r"""
const { Database, SQLiteError, constants } = require("bun:sqlite");
const t = (label, f) => {
  try { console.log(label, "OK", JSON.stringify(f())); }
  catch (e) { console.log(label, e.name, e instanceof SQLiteError, JSON.stringify(e.code), e.errno, e.message); }
};
const db = new Database();
db.run("CREATE TABLE plain (a); CREATE TABLE typed (i INTEGER, r REAL, t TEXT, b BLOB, x ANY) STRICT");
t("first rowid", () => db.run("INSERT INTO plain (rowid, a) VALUES (7, 'x')"));
t("duplicate rowid", () => db.run("INSERT INTO plain (rowid, a) VALUES (7, 'y')"));
t("duplicate rowid (prepared)", () => db.prepare("INSERT INTO plain (rowid, a) VALUES (?, ?)").run(7, "z"));
t("strict text into integer", () => db.run("INSERT INTO typed (i) VALUES ('abc')"));
t("strict blob into real", () => db.query("INSERT INTO typed (r) VALUES (?)").run(new Uint8Array([1])));
t("strict coercible values", () => db.run("INSERT INTO typed VALUES ('12', 3, 4.5, x'00ff', 'any')"));
t("strict rows", () => db.query("SELECT i, typeof(i) AS ti, r, typeof(r) AS tr, t, typeof(t) AS tt, hex(b) AS b, x FROM typed").all());
t("fileControl null", () => db.fileControl(constants.SQLITE_FCNTL_RESET_CACHE, null));
t("fileControl undefined", () => db.fileControl(constants.SQLITE_FCNTL_RESET_CACHE));
t("fileControl unknown opcode", () => db.fileControl(987654, null));
const file = new Database("fc.db");
file.run("CREATE TABLE k (v)");
t("file fileControl unknown opcode", () => file.fileControl(987654, 0));
t("file fileControl reset cache", () => file.fileControl(constants.SQLITE_FCNTL_RESET_CACHE, undefined));
t("file still usable", () => file.query("SELECT count(*) AS n FROM k").get());
t("deserialize DataView", () => new Database(new DataView(new ArrayBuffer(16))));
t("deserialize Float64Array of zeros", () => new Database(new Float64Array(4)).query("SELECT 41 + 1 AS v").get());
const orphan = db.prepare("SELECT 1 AS one");
db.close();
t("finalize after close", () => orphan.finalize());
t("finalize twice after close", () => orphan.finalize());
t("toString after close", () => orphan.toString());
file.close();
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_rowid_datatype_codes")
    assert (r.returncode, r.stderr) == (0, b"")
